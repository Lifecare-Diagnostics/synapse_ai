"""
synapse_poc/synapse/api.py
FastAPI application for Synapse AI Patient Digital Wallet.
Exposes REST endpoints for patient profiles, chronological records, calendar,
abnormal summaries, longitudinal trends, file uploads, and mock API ingestion.
"""

import hashlib
import json
import os
import shutil
from typing import Any, Dict, List, Optional
import uuid

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from synapse.schema import (
    PatientReport,
    ReviewFlag,
)
from synapse.auth import (
    User,
    LoginRequest,
    TokenResponse,
    ROLE_PERMISSIONS,
    ENVIRONMENT,
    has_permission,
    check_permission,
    check_role,
    verify_password,
    create_access_token,
    decode_access_token,
)
from synapse.mllp import MLLPListener
from synapse.smart_fhir import (
    SMARTClient,
    MockSMARTEHRServer,
    get_synthetic_smart_configuration,
)
from synapse.storage import WalletStorage
from synapse.reader import read_pdf_text, read_image_file
from synapse.ocr import get_ocr_engine_info, is_tesseract_available
from synapse.extractor import HybridExtractor, RuleBasedExtractor
from synapse.validator import DocumentValidator
from synapse.reviewer import ExtractionReviewer
from synapse.usage_tracker import get_usage_tracker
from synapse.fhir import (
    get_interop_status,
    get_interop_audit_logs,
    export_report_to_fhir_bundle,
    export_patient_to_fhir_bundle,
    validate_fhir_bundle,
    parse_fhir_bundle_to_synapse_record,
    parse_hl7_v2_oru_r01,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
DEFAULT_DB_PATH = os.path.join(DATA_DIR, "synapse_wallet.db")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# Shared pipelines
extractor = HybridExtractor()
validator = DocumentValidator()
reviewer = ExtractionReviewer()


def _validate_safe_path(file_path: str) -> str:
    """Validate that path resides strictly within the permitted project directories."""
    resolved = os.path.realpath(file_path)
    allowed_root = os.path.realpath(BASE_DIR)
    try:
        common = os.path.commonpath([resolved, allowed_root])
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Invalid drive or path.",
        )
    if common != allowed_root:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: File location is outside permitted document directory.",
        )
    return resolved


def create_app(storage_instance: Optional[WalletStorage] = None) -> FastAPI:
    """Factory to create FastAPI application with injected or default storage."""
    storage = storage_instance or WalletStorage(DEFAULT_DB_PATH)

    app = FastAPI(
        title="Life Care Diagnostics — Synapse AI Digital Wallet",
        description="Core patient digital record system with chronological wallet, abnormal parameter summary, and longitudinal trend analysis.",
        version="3.2.0",
    )

    env_origins = os.environ.get("SYNAPSE_ALLOWED_ORIGINS")
    allow_all = os.environ.get("SYNAPSE_ALLOW_ALL_ORIGINS", "false").lower() in ("true", "1", "yes")

    if allow_all or (ENVIRONMENT == "development" and not env_origins):
        origins = ["*"]
    elif env_origins:
        origins = [orig.strip() for orig in env_origins.split(",") if orig.strip()]
    else:
        origins = [
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def global_sanitized_exception_handler(request, exc: Exception):
        if isinstance(exc, HTTPException):
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=exc.headers,
            )
        tracking_id = f"err_{uuid.uuid4().hex[:10]}"
        import logging
        logging.getLogger("synapse.api").error(
            f"Unhandled server exception [tracking_id={tracking_id}]: {exc}",
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "Internal server error occurred. Please contact the system administrator.",
                "error_code": "INTERNAL_SERVER_ERROR",
                "tracking_id": tracking_id,
            },
        )

    def get_authenticated_user(authorization: Optional[str] = None) -> Optional[User]:
        """
        Extract and validate authenticated user from JWT bearer token.
        Returns User instance if valid token present.
        If invalid token present, raises HTTP 401 Unauthorized.
        If no token present, returns None.
        """
        if not authorization or not isinstance(authorization, str):
            return None
        if not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header format. Expected 'Bearer <token>'.",
            )
        token = authorization[7:].strip()
        try:
            payload = decode_access_token(token)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Authentication failed: {str(e)}",
            )
        user_db = storage.get_user_by_username(payload["sub"])
        if not user_db or not user_db.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account inactive or not found.",
            )
        return User(
            user_id=user_db.user_id,
            username=user_db.username,
            full_name=user_db.full_name,
            role=user_db.role,
            is_active=user_db.is_active,
        )

    # -------------------------------------------------------------------------
    # Authentication & User Management (Phase 7A / 7B)
    # -------------------------------------------------------------------------

    @app.post("/api/v1/auth/login", response_model=TokenResponse, tags=["Authentication"])
    def login_for_access_token(payload: LoginRequest):
        """
        Authenticate user credentials and issue signed JWT bearer token.
        """
        user_db = storage.get_user_by_username(payload.username)
        if not user_db or not verify_password(payload.password, user_db.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
            )
        user = User(
            user_id=user_db.user_id,
            username=user_db.username,
            full_name=user_db.full_name,
            role=user_db.role,
            is_active=user_db.is_active,
        )
        token = create_access_token(user)
        perms = sorted(list(ROLE_PERMISSIONS.get(user.role, set())))
        return TokenResponse(
            access_token=token,
            token_type="bearer",
            user=user,
            permissions=perms,
        )

    @app.get("/api/v1/auth/me", tags=["Authentication"])
    def get_current_user_profile(authorization: Optional[str] = Header(None)):
        """
        Return authenticated user profile and assigned RBAC permissions.
        """
        user = get_authenticated_user(authorization)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required. Please provide a valid Bearer token.",
            )
        return {
            "user": user.model_dump(),
            "permissions": sorted(list(ROLE_PERMISSIONS.get(user.role, set()))),
        }

    @app.get("/api/v1/auth/users", tags=["Authentication"])
    def list_system_users(authorization: Optional[str] = Header(None)):
        """
        List all registered system users (Requires 'user:manage' or Administrator role).
        """
        user = get_authenticated_user(authorization)
        if user and not has_permission(user.role, "user:manage"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: User with role '{user.role}' lacks 'user:manage' permission.",
            )
        users = storage.list_users()
        return {"total": len(users), "users": [u.model_dump() for u in users]}

    # -------------------------------------------------------------------------
    # Patient Endpoints
    # -------------------------------------------------------------------------

    @app.get("/api/v1/patients", tags=["Patients"])
    def list_patients(q: Optional[str] = Query(None, description="Search query for name or ID")):
        """List all registered patients with report counts and latest report date."""
        all_patients = storage.list_patients()
        if q:
            query = q.strip().lower()
            all_patients = [
                p for p in all_patients
                if query in p["patient_id"].lower() or query in p["patient_name"].lower()
            ]
        return {"total": len(all_patients), "patients": all_patients}

    @app.get("/api/v1/patients/{patient_id}", tags=["Patients"])
    def get_patient(patient_id: str):
        """Retrieve patient profile, demographics, and clinical history."""
        demo = storage.get_patient_demographics(patient_id)
        if not demo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Patient '{patient_id}' not found in digital wallet.",
            )
        reports = storage.list_patient_reports(patient_id)
        latest_date = reports[0].report_date if reports else None
        return {
            "patient": demo.model_dump(),
            "total_reports": len(reports),
            "latest_report_date": latest_date,
        }

    @app.get("/api/v1/patients/{patient_id}/reports", tags=["Reports"])
    def list_patient_reports(
        patient_id: str,
        category: Optional[str] = Query(None, description="Filter by report category"),
        start_date: Optional[str] = Query(None, description="Earliest report date (YYYY-MM-DD)"),
        end_date: Optional[str] = Query(None, description="Latest report date (YYYY-MM-DD)"),
        q: Optional[str] = Query(None, description="Search by test/parameter name"),
    ):
        """List reports belonging to a patient in chronological order (newest first)."""
        demo = storage.get_patient_demographics(patient_id)
        if not demo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Patient '{patient_id}' not found.",
            )
        reports = storage.list_patient_reports(
            patient_id,
            category=category,
            start_date=start_date,
            end_date=end_date,
            search_query=q,
        )
        return {
            "patient_id": patient_id,
            "count": len(reports),
            "reports": [r.model_dump() for r in reports],
        }

    @app.get("/api/v1/patients/{patient_id}/calendar", tags=["Calendar"])
    def get_calendar_view(patient_id: str):
        """Retrieve calendar view of patient reports grouped by report_date."""
        demo = storage.get_patient_demographics(patient_id)
        if not demo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Patient '{patient_id}' not found.",
            )
        calendar = storage.get_calendar_view(patient_id)
        return {"patient_id": patient_id, "calendar": calendar}

    @app.get("/api/v1/patients/{patient_id}/parameters", tags=["Trends"])
    def get_available_parameters(patient_id: str):
        """List all standardized parameters with historical observations for this patient."""
        demo = storage.get_patient_demographics(patient_id)
        if not demo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Patient '{patient_id}' not found.",
            )
        params = storage.get_available_parameters(patient_id)
        return {"patient_id": patient_id, "parameters": params}

    @app.get("/api/v1/patients/{patient_id}/trends", tags=["Trends"])
    def get_longitudinal_trends(
        patient_id: str,
        parameter: str = Query(..., description="Standardized parameter name (e.g. Hemoglobin)"),
    ):
        """
        Retrieve chronological parameter observations across dates.
        Strictly checks unit compatibility. Incompatible units are not combined.
        """
        demo = storage.get_patient_demographics(patient_id)
        if not demo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Patient '{patient_id}' not found.",
            )

        pts = storage.get_longitudinal_parameters(patient_id, parameter)
        if not pts:
            return {
                "patient_id": patient_id,
                "parameter": parameter,
                "data_points_count": 0,
                "unit_compatible": True,
                "units_detected": [],
                "data_points": [],
                "warning": None,
            }

        # Check unit consistency
        units = sorted(list({p.unit for p in pts if p.unit}))
        unit_compatible = len(units) <= 1
        warning = None
        if not unit_compatible:
            warning = (
                f"Incompatible units detected across reports ({', '.join(units)}). "
                "Values cannot be directly compared on a single scale without verified clinical conversion."
            )

        data_points = [
            {
                "report_id": p.report_id,
                "report_date": p.report_date,
                "original_name": p.original_name,
                "result_value": p.result_value,
                "unit": p.unit,
                "reference_range_text": p.reference_range_text,
                "reference_low": p.reference_low,
                "reference_high": p.reference_high,
                "clinical_flag": p.clinical_flag,
                "abnormality_category": p.abnormality_category,
                "source_text": p.source_text,
            }
            for p in pts
        ]

        return {
            "patient_id": patient_id,
            "parameter": parameter,
            "data_points_count": len(data_points),
            "unit_compatible": unit_compatible,
            "units_detected": units,
            "data_points": data_points,
            "warning": warning,
        }

    # -------------------------------------------------------------------------
    # Report & Abnormality Endpoints
    # -------------------------------------------------------------------------

    @app.get("/api/v1/reports/{report_id}", tags=["Reports"])
    def get_report_details(report_id: str):
        """Retrieve full structured report information including parameters and raw sections."""
        rep = storage.get_report(report_id)
        if not rep:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Report '{report_id}' not found.",
            )
        return rep.model_dump()

    @app.get("/api/v1/reports/{report_id}/abnormal-summary", tags=["Abnormal Summary"])
    def get_abnormal_summary(report_id: str):
        """
        Categorize report parameters into:
        - below_range
        - above_range
        - within_range
        - reference_range_unavailable
        - requires_review
        """
        rep = storage.get_report(report_id)
        if not rep:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Report '{report_id}' not found.",
            )

        summary = storage.get_abnormal_summary(report_id)
        return {
            "report_id": report_id,
            "patient_id": rep.patient_id,
            "report_date": rep.report_date,
            "report_category": rep.report_category,
            "below_range": [p.model_dump() for p in summary["below_range"]],
            "above_range": [p.model_dump() for p in summary["above_range"]],
            "within_range": [p.model_dump() for p in summary["within_range"]],
            "reference_range_unavailable": [p.model_dump() for p in summary["reference_range_unavailable"]],
            "requires_review": [p.model_dump() for p in summary["requires_review"]],
        }

    @app.get("/api/v1/reports/{report_id}/document", tags=["Reports"])
    def get_report_document(report_id: str):
        """
        Safely stream or return the original document file (PDF, TXT, JSON).
        Guards against directory traversal using _validate_safe_path.
        """
        rep = storage.get_report(report_id)
        if not rep:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Report '{report_id}' not found.",
            )

        if not rep.original_document_location:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No original document file path recorded for this report.",
            )

        if rep.original_document_location.startswith("api://"):
            return JSONResponse(
                content={
                    "message": "Report was ingested via digital API JSON payload.",
                    "report_id": rep.report_id,
                    "patient_id": rep.patient_id,
                    "report_category": rep.report_category,
                    "payload": rep.model_dump(),
                }
            )

        safe_path = _validate_safe_path(rep.original_document_location)
        if not os.path.isfile(safe_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Original document file not found at '{rep.original_filename}'.",
            )

        ext = os.path.splitext(safe_path)[1].lower()
        if ext == ".pdf":
            media_type = "application/pdf"
        elif ext in [".txt", ".text"]:
            media_type = "text/plain; charset=utf-8"
        elif ext == ".json":
            media_type = "application/json"
        elif ext == ".png":
            media_type = "image/png"
        elif ext in [".jpg", ".jpeg"]:
            media_type = "image/jpeg"
        else:
            media_type = "application/octet-stream"

        return FileResponse(
            path=safe_path,
            media_type=media_type,
            filename=rep.original_filename,
        )

    @app.get("/api/v1/ocr/status", tags=["OCR"])
    def get_ocr_status():
        """
        Check OCR engine availability, binary location, and version.
        """
        return get_ocr_engine_info()

    @app.get("/api/v1/reports/{report_id}/content", tags=["Reports"])
    def get_report_content(report_id: str):
        """
        Retrieve document presentation content:
        Returns raw text for TXT/JSON documents, or metadata + document URL for PDFs.
        """
        rep = storage.get_report(report_id)
        if not rep:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Report '{report_id}' not found.",
            )

        doc_url = f"/api/v1/reports/{report_id}/document"
        file_format = (rep.file_format or "unknown").lower()

        if not rep.original_document_location:
            return {
                "report_id": report_id,
                "patient_id": rep.patient_id,
                "filename": rep.original_filename,
                "file_format": file_format,
                "is_text": False,
                "content": None,
                "document_url": doc_url,
                "error": "No file path associated with this report.",
            }

        if rep.original_document_location.startswith("api://"):
            return {
                "report_id": report_id,
                "patient_id": rep.patient_id,
                "filename": rep.original_filename,
                "file_format": "json",
                "is_text": True,
                "content": rep.raw_clinical_narrative or json.dumps(rep.model_dump(), indent=2),
                "document_url": doc_url,
            }

        safe_path = _validate_safe_path(rep.original_document_location)
        if not os.path.isfile(safe_path):
            return {
                "report_id": report_id,
                "patient_id": rep.patient_id,
                "filename": rep.original_filename,
                "file_format": file_format,
                "is_text": False,
                "content": None,
                "document_url": doc_url,
                "error": f"File '{rep.original_filename}' is not accessible on disk.",
            }

        if file_format == "pdf" or safe_path.lower().endswith(".pdf"):
            return {
                "report_id": report_id,
                "patient_id": rep.patient_id,
                "filename": rep.original_filename,
                "file_format": "pdf",
                "is_text": False,
                "content": None,
                "document_url": doc_url,
            }

        if (
            file_format in ["png", "jpg", "jpeg", "bmp", "tiff"]
            or safe_path.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".tiff"))
        ):
            return {
                "report_id": report_id,
                "patient_id": rep.patient_id,
                "filename": rep.original_filename,
                "file_format": file_format,
                "is_text": False,
                "is_image": True,
                "content": rep.key_text_sections.get("Status"),
                "document_url": doc_url,
            }

        # For text / json files
        try:
            with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
                raw_text = f.read()
            return {
                "report_id": report_id,
                "patient_id": rep.patient_id,
                "filename": rep.original_filename,
                "file_format": file_format,
                "is_text": True,
                "content": raw_text,
                "document_url": doc_url,
            }
        except Exception as e:
            return {
                "report_id": report_id,
                "patient_id": rep.patient_id,
                "filename": rep.original_filename,
                "file_format": file_format,
                "is_text": False,
                "content": None,
                "document_url": doc_url,
                "error": f"Failed reading text: {str(e)}",
            }

    # -------------------------------------------------------------------------
    # Ingestion Endpoints (Mock API JSON & File Uploads)
    # -------------------------------------------------------------------------

    @app.post("/api/v1/reports/json", status_code=status.HTTP_201_CREATED, tags=["Ingestion"])
    def ingest_json_report(payload: Dict[str, Any]):
        """
        Mock API endpoint accepting structured digital report data in JSON format.
        Validates schema, checks patient existence, prevents duplicate ingestion,
        and saves standardized parameters.
        """
        patient_id = payload.get("patient_id")
        if not patient_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Validation error: 'patient_id' is required.",
            )

        report_id = payload.get("report_id") or f"API-{uuid.uuid4().hex[:8].upper()}"

        # Hash payload to prevent exact duplicate ingestion
        payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        content_hash = hashlib.sha256(payload_bytes).hexdigest()

        # Check duplicate
        dup = storage.find_duplicate_report(patient_id, f"{report_id}.json", content_hash=content_hash)
        if dup:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Duplicate report detected: Report '{report_id}' has already been ingested for patient '{patient_id}'.",
            )

        try:
            report = storage.ingest_api_json_record(payload, content_hash=content_hash)
            return {
                "message": "Report successfully ingested through API.",
                "report_id": report.report_id,
                "patient_id": report.patient_id,
                "report_date": report.report_date,
                "parameters_count": len(report.parameters),
                "review_status": report.review_status,
            }
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @app.post("/api/v1/reports/upload", status_code=status.HTTP_201_CREATED, tags=["Ingestion"])
    async def upload_report_file(
        file: UploadFile = File(...),
        patient_id: Optional[str] = Form(None),
    ):
        """
        Upload medical report document (.txt, .pdf, .json).
        Identifies format, reads layer (handling OCR requirement), extracts,
        validates, applies review flags, checks for duplicates, and saves to wallet.
        """
        filename = os.path.basename(file.filename or "upload.txt")
        ext = os.path.splitext(filename)[1].lower()

        if ext not in [".txt", ".pdf", ".json", ".png", ".jpg", ".jpeg"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file format '{ext}'. Supported formats: .txt, .pdf, .json, .png, .jpg, .jpeg",
            )

        content_bytes = await file.read()
        if len(content_bytes) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty file uploaded.",
            )

        content_hash = hashlib.sha256(content_bytes).hexdigest()

        # 1. JSON File Ingestion
        if ext == ".json":
            try:
                data = json.loads(content_bytes.decode("utf-8"))
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid JSON file: {e}",
                )

            pid = patient_id or data.get("patient_id")
            if not pid:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Missing 'patient_id' in JSON file or upload form.",
                )
            data["patient_id"] = pid

            dup = storage.find_duplicate_report(pid, filename, content_hash=content_hash)
            if dup:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Duplicate report detected: '{filename}' has already been ingested for patient '{pid}' (Report ID: {dup.report_id}).",
                )

            rep = storage.ingest_api_json_record(data, content_hash=content_hash)
            return {
                "message": "JSON report uploaded and ingested successfully.",
                "report_id": rep.report_id,
                "patient_id": rep.patient_id,
                "report_date": rep.report_date,
                "parameters_count": len(rep.parameters),
                "extraction_status": rep.extraction_status,
                "review_status": rep.review_status,
            }

        # 2. Text / PDF / Image File Handling
        target_path = os.path.join(UPLOADS_DIR, f"{uuid.uuid4().hex[:6]}_{filename}")
        with open(target_path, "wb") as f_out:
            f_out.write(content_bytes)

        if ext == ".pdf":
            raw_text = read_pdf_text(target_path)
            # Check for scanned / empty text layer
            if raw_text == "needs OCR - not supported yet":
                pid = patient_id or "UNKNOWN-PATIENT"
                dup = storage.find_duplicate_report(pid, filename, content_hash=content_hash)
                if dup:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Duplicate report detected: '{filename}' has already been ingested for patient '{pid}'.",
                    )

                # Store as OCR required report
                ocr_report = PatientReport(
                    report_id=f"REP-{uuid.uuid4().hex[:8].upper()}",
                    patient_id=pid,
                    report_date=None,
                    date_label=None,
                    report_category="Imaging",
                    original_filename=filename,
                    file_format="pdf",
                    upload_datetime=os.path.basename(target_path),
                    extraction_status="ocr_required",
                    review_status="needs_review",
                    original_document_location=target_path,
                    parameters=[],
                    key_text_sections={"Status": "Scanned document layer requires OCR (not supported in current phase)."},
                    document_level_flags=[
                        ReviewFlag(
                            field="file_content",
                            reason="Scanned / image-based PDF has no digital text layer. OCR processing is required.",
                            severity="warning",
                        )
                    ],
                    validation_errors=["Scanned PDF requires OCR."],
                )
                storage.save_report(ocr_report)
                return {
                    "message": "File received. Scanned PDF contains no digital text layer — marked as 'needs OCR'.",
                    "report_id": ocr_report.report_id,
                    "patient_id": ocr_report.patient_id,
                    "report_date": None,
                    "parameters_count": 0,
                    "extraction_status": "ocr_required",
                    "review_status": "needs_review",
                }
        elif ext in [".png", ".jpg", ".jpeg"]:
            raw_text = read_image_file(target_path)
            if raw_text == "needs OCR - not supported yet":
                pid = patient_id or "UNKNOWN-PATIENT"
                dup = storage.find_duplicate_report(pid, filename, content_hash=content_hash)
                if dup:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Duplicate report detected: '{filename}' has already been ingested for patient '{pid}'.",
                    )

                ocr_report = PatientReport(
                    report_id=f"REP-{uuid.uuid4().hex[:8].upper()}",
                    patient_id=pid,
                    report_date=None,
                    date_label=None,
                    report_category="Imaging",
                    original_filename=filename,
                    file_format=ext.replace(".", ""),
                    upload_datetime=os.path.basename(target_path),
                    extraction_status="ocr_required",
                    review_status="needs_review",
                    original_document_location=target_path,
                    parameters=[],
                    key_text_sections={"Status": "Medical image scan requires OCR processing."},
                    document_level_flags=[
                        ReviewFlag(
                            field="file_content",
                            reason="Medical image has no digital text layer. OCR processing is required.",
                            severity="warning",
                        )
                    ],
                    validation_errors=["Scanned image requires OCR."],
                )
                storage.save_report(ocr_report)
                return {
                    "message": "File received. Scanned image requires OCR engine — marked as 'needs OCR'.",
                    "report_id": ocr_report.report_id,
                    "patient_id": ocr_report.patient_id,
                    "report_date": None,
                    "parameters_count": 0,
                    "extraction_status": "ocr_required",
                    "review_status": "needs_review",
                }
        else:
            raw_text = content_bytes.decode("utf-8", errors="replace")

        # 3. Extract, Validate, Review
        doc = extractor.extract(raw_text, source_file=filename)
        if patient_id:
            doc.patient_id = patient_id
        doc = validator.validate(doc)
        doc = reviewer.review(doc)

        pid = doc.patient_id or "UNKNOWN-PATIENT"

        # Check Duplicate
        dup = storage.find_duplicate_report(pid, filename, content_hash=content_hash)
        if dup:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Duplicate report detected: '{filename}' has already been ingested for patient '{pid}' (Report ID: {dup.report_id}).",
            )

        rep = storage.ingest_extracted_document(
            doc,
            original_location=target_path,
            file_format=ext.replace(".", ""),
            content_hash=content_hash,
        )

        return {
            "message": "Report uploaded and extracted successfully.",
            "report_id": rep.report_id,
            "patient_id": rep.patient_id,
            "report_date": rep.report_date,
            "parameters_count": len(rep.parameters),
            "extraction_status": rep.extraction_status,
            "review_status": rep.review_status,
        }

    # -------------------------------------------------------------------------
    # Interoperability Endpoints (FHIR R4 & HL7 v2)
    # -------------------------------------------------------------------------

    @app.get("/api/v1/interop/status", tags=["Interoperability"])
    def get_interoperability_status():
        """Get interoperability gateway capabilities, supported specifications, and configuration."""
        return get_interop_status()

    @app.get("/api/v1/interop/audit", tags=["Interoperability"])
    def get_interoperability_audit(limit: int = Query(50, ge=1, le=200)):
        """Retrieve recent integration audit events."""
        return {"audit_events": get_interop_audit_logs(limit=limit)}

    @app.get("/api/v1/interop/fhir/reports/{report_id}", tags=["Interoperability"])
    def export_fhir_report(
        report_id: str,
        enforce_approval: bool = Query(True),
        authorization: Optional[str] = Header(None),
    ):
        """
        Export a single PatientReport, its parameters, and associated patient demographics
        as an official HL7 FHIR R4 Collection Bundle.
        Safeguards: Blocks export if report is rejected or pending clinical review.
        RBAC: Requires 'interop:export' permission (Pathologist or Administrator).
        """
        user = get_authenticated_user(authorization)
        if user and not has_permission(user.role, "interop:export"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: User with role '{user.role}' cannot export FHIR data. Pathologist or Administrator role required.",
            )
        report = storage.get_report(report_id)
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Report '{report_id}' not found.",
            )
        if report.review_status == "rejected":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Export blocked: Report '{report_id}' has been rejected by clinical review.",
            )
        if enforce_approval and report.review_status in ("needs_review", "unsupported_parameters"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Export blocked: Clinical approval required before export (current status: '{report.review_status}').",
            )
        demographics = storage.get_patient_demographics(report.patient_id)
        return export_report_to_fhir_bundle(report, demographics)

    @app.get("/api/v1/interop/fhir/patients/{patient_id}", tags=["Interoperability"])
    def export_fhir_patient(patient_id: str, enforce_approval: bool = Query(True)):
        """
        Export an entire patient record (demographics and all linked reports/observations)
        as an official HL7 FHIR R4 Collection Bundle.
        Safeguard: Omits unapproved or rejected reports if enforce_approval is True.
        """
        patient_obj = storage.get_patient(patient_id)
        if not patient_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Patient '{patient_id}' not found.",
            )
        if enforce_approval:
            patient_obj.reports = [
                r for r in patient_obj.reports
                if r.review_status not in ("rejected", "needs_review", "unsupported_parameters")
            ]
        return export_patient_to_fhir_bundle(patient_obj)

    @app.post("/api/v1/interop/fhir/ingest", status_code=status.HTTP_201_CREATED, tags=["Interoperability"])
    def ingest_fhir_bundle(payload: Dict[str, Any]):
        """
        Ingest an HL7 FHIR R4 Bundle containing Patient, DiagnosticReport, and Observation resources.
        Validates schema, checks duplicates, updates demographics, and records observations.
        """
        is_valid, validation_errors = validate_fhir_bundle(payload)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"FHIR validation error: {'; '.join(validation_errors)}",
            )

        try:
            parsed = parse_fhir_bundle_to_synapse_record(payload)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        patient_id = parsed["patient_id"]
        report_id = parsed["report_id"]

        # Duplicate check via content hash
        payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        content_hash = hashlib.sha256(payload_bytes).hexdigest()

        dup = storage.find_duplicate_report(patient_id, f"{report_id}.json", content_hash=content_hash)
        if dup:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Duplicate FHIR report detected: '{report_id}' has already been ingested for patient '{patient_id}'.",
            )

        # Save demographics if present
        demographics = parsed.get("demographics")
        if demographics:
            storage.save_patient(demographics)

        api_payload = {
            "patient_id": patient_id,
            "report_id": report_id,
            "report_date": parsed["report_date"],
            "report_category": parsed["report_category"],
            "parameters": parsed["parameters"],
            "notes": json.dumps(parsed.get("key_text_sections", {})),
        }
        report = storage.ingest_api_json_record(api_payload, content_hash=content_hash)
        return {
            "message": "FHIR R4 Bundle ingested successfully.",
            "report_id": report.report_id,
            "patient_id": report.patient_id,
            "report_date": report.report_date,
            "parameters_count": len(report.parameters),
            "review_status": report.review_status,
            "source": "FHIR R4",
        }

    @app.post("/api/v1/interop/hl7/ingest", status_code=status.HTTP_201_CREATED, tags=["Interoperability"])
    def ingest_hl7_v2_message(payload: Dict[str, Any]):
        """
        Ingest a standard HL7 v2.5.1 ORU^R01 clinical laboratory message.
        Accepts {"message": "<HL7 pipe-delimited text>"}.
        """
        hl7_text = payload.get("message")
        if not hl7_text:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Missing 'message' field in HL7 ingestion payload.",
            )

        try:
            parsed = parse_hl7_v2_oru_r01(hl7_text)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed parsing HL7 v2 message: {e}",
            )

        patient_id = parsed["patient_id"]
        report_id = parsed["report_id"]

        content_hash = hashlib.sha256(hl7_text.encode("utf-8")).hexdigest()
        dup = storage.find_duplicate_report(patient_id, f"{report_id}.hl7", content_hash=content_hash)
        if dup:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Duplicate HL7 message detected: '{report_id}' has already been ingested for patient '{patient_id}'.",
            )

        # Save demographics if present
        demographics = parsed.get("demographics")
        if demographics:
            storage.save_patient(demographics)

        api_payload = {
            "patient_id": patient_id,
            "report_id": report_id,
            "report_date": parsed["report_date"],
            "report_category": parsed["report_category"],
            "parameters": parsed["parameters"],
            "notes": json.dumps(parsed.get("key_text_sections", {})),
        }
        report = storage.ingest_api_json_record(api_payload, content_hash=content_hash)
        return {
            "message": "HL7 v2 ORU^R01 message ingested successfully.",
            "report_id": report.report_id,
            "patient_id": report.patient_id,
            "report_date": report.report_date,
            "parameters_count": len(report.parameters),
            "review_status": report.review_status,
            "source": "HL7 v2.5.1",
        }

    # -------------------------------------------------------------------------
    # SMART on FHIR & MLLP Gateway Endpoints (Phase 7C)
    # -------------------------------------------------------------------------

    class SMARTLaunchRequest(BaseModel):
        flow: str = "standalone"  # "standalone" or "ehr"
        aud: Optional[str] = "http://localhost:8000/api/v1/interop/fhir"
        launch: Optional[str] = None
        scopes: Optional[List[str]] = None

    class SMARTTokenExchangeRequest(BaseModel):
        code: str
        state: str
        code_verifier: Optional[str] = None
        client_id: Optional[str] = "synapse-ai-smart-client"

    # Shared synthetic mock EHR server and client
    mock_ehr_server = MockSMARTEHRServer()
    smart_client = SMARTClient()

    @app.get("/api/v1/interop/mllp/status", tags=["Interoperability"])
    def get_mllp_service_status():
        """
        Return Minimal Lower Layer Protocol (MLLP) TCP/TLS service status and framing configuration.
        """
        dummy_listener = MLLPListener(is_synthetic=True)
        return dummy_listener.get_status()

    @app.get("/api/v1/interop/smart/configuration", tags=["Interoperability"])
    def get_smart_discovery_configuration():
        """
        Return standard SMART-on-FHIR OAuth2 discovery metadata (.well-known/smart-configuration).
        """
        return get_synthetic_smart_configuration()

    @app.post("/api/v1/interop/smart/launch", tags=["Interoperability"])
    def initiate_smart_launch(payload: SMARTLaunchRequest):
        """
        Initiate a SMART-on-FHIR launch sequence with PKCE (RFC 7636).
        Returns the authorization redirect URL, state, and PKCE challenge.
        """
        auth_endpoint = "https://ehr.synthetic.lifecare.local/oauth/authorize"
        if payload.flow == "ehr":
            if not payload.launch:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Missing 'launch' parameter for EHR launch flow.",
                )
            result = smart_client.initiate_ehr_launch(
                authorization_endpoint=auth_endpoint,
                launch_context_token=payload.launch,
                scopes=payload.scopes,
            )
        else:
            result = smart_client.initiate_standalone_launch(
                authorization_endpoint=auth_endpoint,
                fhir_base_url=payload.aud or "http://localhost:8000/api/v1/interop/fhir",
                scopes=payload.scopes,
            )
        # Pre-seed authorization code in mock server for instant test redemption
        mock_code = mock_ehr_server.create_authorization_code(
            client_id=smart_client.client_id,
            redirect_uri=smart_client.redirect_uri,
            scope=result["scope"],
            state=result["state"],
            code_challenge=result["code_challenge"],
            patient_id="SYN-1001",
            launch=payload.launch,
        )
        result["simulated_authorization_code"] = mock_code
        return result

    @app.post("/api/v1/interop/smart/token", tags=["Interoperability"])
    def exchange_smart_token(payload: SMARTTokenExchangeRequest):
        """
        Exchange SMART authorization code + PKCE verifier for OAuth2 access token and patient context.
        """
        try:
            tokens = smart_client.complete_token_exchange(
                code=payload.code,
                state=payload.state,
                mock_ehr_server=mock_ehr_server,
            )
            return tokens
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"SMART token exchange failed: {e}",
            )

    # -------------------------------------------------------------------------
    # Review Queue & Quality Audit Endpoints (Phase 6B)
    # -------------------------------------------------------------------------

    class ReviewActionPayload(BaseModel):
        action: str
        reviewer: str
        comments: Optional[str] = None

    class ParameterCorrectionPayload(BaseModel):
        corrected_value: Optional[float] = None
        corrected_name: Optional[str] = None
        corrected_unit: Optional[str] = None
        reviewer: str
        reason: str

    @app.get("/api/v1/review/queue", tags=["Review Queue"])
    def get_review_queue(status: Optional[str] = Query(None, description="Filter by review status")):
        """
        List reports queued for clinical/data review.
        By default returns reports needing review, unsupported parameters, or corrected.
        """
        items = storage.list_review_queue(status_filter=status)
        return {"total": len(items), "queue": items}

    @app.post("/api/v1/review/reports/{report_id}/action", tags=["Review Queue"])
    def record_report_review_action(
        report_id: str,
        payload: ReviewActionPayload,
        authorization: Optional[str] = Header(None),
    ):
        """
        Record a clinical review action (approve, reject, needs_review) for a report.
        RBAC & Identity: When authenticated, clinical sign-off (approve/reject) requires
        'report:signoff' (Pathologist role) and identity is derived from session.
        """
        if payload.action not in ("approve", "reject", "needs_review", "correct"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid action '{payload.action}'. Must be one of: approve, reject, needs_review.",
            )

        user = get_authenticated_user(authorization)
        if user:
            if payload.action in ("approve", "reject") and not has_permission(user.role, "report:signoff"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied: User with role '{user.role}' cannot perform clinical sign-off ('{payload.action}'). Pathologist role required.",
                )
            reviewer_identity = user.full_name
        else:
            reviewer_identity = payload.reviewer or "Dr. Pathologist"

        try:
            entry = storage.record_review_action(
                report_id=report_id,
                action=payload.action,
                reviewer=reviewer_identity,
                comments=payload.comments,
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

        rep = storage.get_report(report_id)
        return {
            "message": f"Review action '{payload.action}' recorded successfully.",
            "report_id": report_id,
            "new_status": rep.review_status if rep else payload.action,
            "audit_entry": entry.model_dump(),
        }

    @app.post("/api/v1/review/reports/{report_id}/parameters/{parameter_id}/correct", tags=["Review Queue"])
    def correct_parameter_value(
        report_id: str,
        parameter_id: str,
        payload: ParameterCorrectionPayload,
        authorization: Optional[str] = Header(None),
    ):
        """
        Perform field-level human correction on an extracted lab parameter.
        Re-computes flags, stores change in review audit log, and marks report as 'corrected'.
        RBAC & Identity: When authenticated, requires 'parameter:correct' (Auditor or Pathologist)
        and identity is derived from session.
        """
        user = get_authenticated_user(authorization)
        if user:
            if not has_permission(user.role, "parameter:correct"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied: User with role '{user.role}' cannot perform parameter corrections. Auditor or Pathologist role required.",
                )
            reviewer_identity = user.full_name
        else:
            reviewer_identity = payload.reviewer or "Clinical Auditor"

        try:
            result = storage.correct_report_parameter(
                report_id=report_id,
                parameter_id=parameter_id,
                corrected_value=payload.corrected_value,
                corrected_name=payload.corrected_name,
                corrected_unit=payload.corrected_unit,
                reviewer=reviewer_identity,
                reason=payload.reason,
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

        return {
            "message": "Parameter corrected successfully.",
            "data": result,
        }

    @app.get("/api/v1/review/reports/{report_id}/history", tags=["Review Queue"])
    def get_report_review_history(report_id: str):
        """
        Retrieve complete chronological review and correction audit history for a report.
        """
        rep = storage.get_report(report_id)
        if not rep:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Report '{report_id}' not found.")
        history = storage.get_report_review_history(report_id)
        return {
            "report_id": report_id,
            "total_entries": len(history),
            "history": [h.model_dump() for h in history],
        }

    # -------------------------------------------------------------------------
    # LLM Provider, Usage Tracking & Cost Projections
    # -------------------------------------------------------------------------

    @app.get("/api/v1/llm/status", tags=["LLM & Intelligence"])
    def get_llm_status():
        """
        Retrieve active LLM provider configuration, selected model, and service status.
        Never exposes API keys or secrets.
        """
        provider = os.getenv("SYNAPSE_LLM_PROVIDER", "mock").lower()
        model_name = None
        has_key = False

        if provider == "gemini":
            from synapse.llm import GeminiClient
            model_name = os.getenv("SYNAPSE_GEMINI_MODEL", GeminiClient.DEFAULT_MODEL)
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            has_key = bool(api_key)
        elif provider == "ollama":
            model_name = os.getenv("SYNAPSE_OLLAMA_MODEL", "llama3.2")
        else:
            model_name = "mock-internal-rules"

        return {
            "provider": provider,
            "active_model": model_name,
            "api_key_configured": has_key if provider == "gemini" else None,
            "status": "ready" if (provider != "gemini" or has_key) else "needs_configuration",
            "offline_fallback_enabled": True,
        }

    @app.get("/api/v1/llm/usage", tags=["LLM & Intelligence"])
    def get_llm_usage_summary():
        """
        Retrieve aggregated token usage, cost estimates in USD and INR,
        breakdown by provider, and recent API calls.
        """
        tracker = get_usage_tracker(DEFAULT_DB_PATH)
        return tracker.get_summary()

    @app.get("/api/v1/llm/cost-estimate", tags=["LLM & Intelligence"])
    def calculate_llm_cost_estimate(
        documents_per_month: int = Query(1000, ge=1, le=10_000_000, description="Monthly document volume"),
        model: Optional[str] = Query(None, description="Model identifier (default: gemini-3.5-flash-lite)"),
        avg_input_tokens: int = Query(5000, ge=100, le=100_000, description="Average prompt/input tokens per document"),
        avg_output_tokens: int = Query(1000, ge=50, le=50_000, description="Average output tokens per document"),
    ):
        """
        Estimate projected monthly LLM inference cost in USD and INR for Life Care management.
        Allows varying document volumes and token averages.
        """
        tracker = get_usage_tracker(DEFAULT_DB_PATH)
        return tracker.get_monthly_cost_estimate(
            documents_per_month=documents_per_month,
            model=model,
            avg_input_tokens=avg_input_tokens,
            avg_output_tokens=avg_output_tokens,
        )

    # -------------------------------------------------------------------------
    # Frontend Static & HTML Routes
    # -------------------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def serve_frontend_root():
        index_file = os.path.join(STATIC_DIR, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return {"status": "Synapse AI API Online", "docs": "/docs"}

    # Mount static assets if any
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


# Default instance for uvicorn run: `uvicorn synapse.api:app`
app = create_app()

