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

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from synapse.schema import (
    PatientReport,
    ReviewFlag,
)
from synapse.storage import WalletStorage
from synapse.reader import read_pdf_text
from synapse.extractor import RuleBasedExtractor
from synapse.validator import DocumentValidator
from synapse.reviewer import ExtractionReviewer

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
DEFAULT_DB_PATH = os.path.join(DATA_DIR, "synapse_wallet.db")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# Shared pipelines
extractor = RuleBasedExtractor()
validator = DocumentValidator()
reviewer = ExtractionReviewer()


def create_app(storage_instance: Optional[WalletStorage] = None) -> FastAPI:
    """Factory to create FastAPI application with injected or default storage."""
    storage = storage_instance or WalletStorage(DEFAULT_DB_PATH)

    app = FastAPI(
        title="Life Care Diagnostics — Synapse AI Digital Wallet",
        description="Core patient digital record system with chronological wallet, abnormal parameter summary, and longitudinal trend analysis.",
        version="3.2.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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

        if ext not in [".txt", ".pdf", ".json"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file format '{ext}'. Supported formats: .txt, .pdf, .json",
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
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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

        # 2. Text / PDF File Handling
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
