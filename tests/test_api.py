"""
synapse_poc/tests/test_api.py
Comprehensive automated test suite for Stage 2:
FastAPI Endpoints, Patient Digital Wallet, Abnormal Summary, Trends,
File Uploads, Duplicate Detection, and OCR Identification.
Zero external test client dependencies required.
"""

import io
import pytest
from fastapi import HTTPException, UploadFile
from fpdf import FPDF

from synapse.api import create_app
from synapse.schema import MedicalHistoryEntry, PatientDemographics
from synapse.storage import WalletStorage
from synapse.extractor import RuleBasedExtractor
from synapse.validator import DocumentValidator
from synapse.reviewer import ExtractionReviewer


@pytest.fixture
def test_storage():
    """Create a seeded in-memory WalletStorage instance for API tests."""
    storage = WalletStorage(":memory:")
    extractor = RuleBasedExtractor()
    validator = DocumentValidator()
    reviewer = ExtractionReviewer()

    # 1. Register test patient SYN-1001
    storage.save_patient(
        PatientDemographics(
            patient_id="SYN-1001",
            patient_name="Rohan Example",
            date_of_birth="1984-05-12",
            age=42,
            sex="Male",
            medical_history=[
                MedicalHistoryEntry(
                    entry_id="HIST-001",
                    condition_or_event="Essential Hypertension",
                    entry_date="2024-02-15",
                    source="Clinical Note",
                    notes="Telmisartan 40mg",
                )
            ],
        )
    )

    # 2. Ingest 3 CBC documents across dates for SYN-1001
    cbc_dates_values = [
        ("2026-04-03", 14.2),
        ("2026-06-15", 13.5),
        ("2026-10-20", 14.8),
    ]
    for dt, val in cbc_dates_values:
        txt = (
            f"SYNTHETIC TEST DOCUMENT\n"
            f"Patient Name: Rohan Example\n"
            f"Patient ID: SYN-1001\n"
            f"Registered On: {dt}\n"
            f"Report Type: Complete Blood Count\n\n"
            f"Haemoglobin: {val} g/dL (Reference 13.0 - 17.0)\n"
            f"WBC Count: 7.10 x10^3/cmm (Reference 4.0 - 10.0)\n"
        )
        doc = reviewer.review(validator.validate(extractor.extract(txt, f"cbc_{dt}.txt")))
        storage.ingest_extracted_document(doc, original_location=f"cbc_{dt}.txt", file_format="txt")

    # 3. Register SYN-1002 with one normal and one missing-date report
    storage.save_patient(
        PatientDemographics(
            patient_id="SYN-1002",
            patient_name="Meera Sample",
            date_of_birth="1975-09-20",
            age=51,
            sex="Female",
            medical_history=[],
        )
    )
    txt_bio = (
        "SYNTHETIC TEST DOCUMENT\n"
        "Patient Name: Meera Sample\n"
        "Patient ID: SYN-1002\n"
        "Report Date: 2026-04-04\n"
        "Report: Fasting Biochemistry\n\n"
        "Fasting Glucose: 118.0 mg/dL (Reference 70 - 110)\n"
    )
    doc_bio = reviewer.review(validator.validate(extractor.extract(txt_bio, "bio_apr.txt")))
    storage.ingest_extracted_document(doc_bio)

    txt_no_date = (
        "SYNTHETIC TEST DOCUMENT\n"
        "Patient Name: Meera Sample\n"
        "Patient ID: SYN-1002\n"
        "Report: Fasting Biochemistry\n\n"
        "Fasting Glucose: 96 mg/dL (Reference 70 - 110)\n"
    )
    doc_no_date = reviewer.review(validator.validate(extractor.extract(txt_no_date, "no_date.txt")))
    storage.ingest_extracted_document(doc_no_date)

    return storage


@pytest.fixture
def app_instance(test_storage):
    """FastAPI application with injected test storage."""
    return create_app(test_storage)


# -----------------------------------------------------------------------------
# Patient Endpoints Tests
# -----------------------------------------------------------------------------

def test_api_list_patients(app_instance):
    """Verify listing all patients and search query filtering."""
    # Find list_patients endpoint route handler
    route = next(r for r in app_instance.routes if r.path == "/api/v1/patients" and "GET" in r.methods)
    handler = route.endpoint

    res = handler(q=None)
    assert res["total"] == 2
    assert any(p["patient_id"] == "SYN-1001" for p in res["patients"])

    # Search filter
    search_res = handler(q="Meera")
    assert search_res["total"] == 1
    assert search_res["patients"][0]["patient_id"] == "SYN-1002"


def test_api_get_patient_details(app_instance):
    """Verify retrieving patient demographics, medical history, and 404 for unknown patient."""
    route = next(r for r in app_instance.routes if r.path == "/api/v1/patients/{patient_id}" and "GET" in r.methods)
    handler = route.endpoint

    data = handler(patient_id="SYN-1001")
    assert data["patient"]["patient_name"] == "Rohan Example"
    assert data["patient"]["age"] == 42
    assert len(data["patient"]["medical_history"]) == 1
    assert data["total_reports"] == 3
    assert data["latest_report_date"] == "2026-10-20"

    # 404 check
    with pytest.raises(HTTPException) as exc:
        handler(patient_id="NON-EXISTENT-ID")
    assert exc.value.status_code == 404
    assert "not found" in exc.value.detail.lower()


# -----------------------------------------------------------------------------
# Digital Wallet Reports Endpoints Tests
# -----------------------------------------------------------------------------

def test_api_list_patient_reports_chronological(app_instance):
    """Verify reports are sorted chronologically newest first."""
    route = next(r for r in app_instance.routes if r.path == "/api/v1/patients/{patient_id}/reports" and "GET" in r.methods)
    handler = route.endpoint

    data = handler(patient_id="SYN-1001", category=None, start_date=None, end_date=None, q=None)
    assert data["count"] == 3
    dates = [r["report_date"] for r in data["reports"]]
    assert dates == ["2026-10-20", "2026-06-15", "2026-04-03"]


def test_api_report_filters(app_instance):
    """Verify category, date range, and parameter search filters."""
    route = next(r for r in app_instance.routes if r.path == "/api/v1/patients/{patient_id}/reports" and "GET" in r.methods)
    handler = route.endpoint

    # Date range filter
    res_range = handler(patient_id="SYN-1001", category=None, start_date="2026-04-01", end_date="2026-07-01", q=None)
    assert res_range["count"] == 2

    # Category filter
    res_cat = handler(patient_id="SYN-1001", category="CBC / Hematology", start_date=None, end_date=None, q=None)
    assert res_cat["count"] == 3

    # Parameter query filter
    res_q = handler(patient_id="SYN-1001", category=None, start_date=None, end_date=None, q="Haemoglobin")
    assert res_q["count"] == 3


def test_api_calendar_view(app_instance):
    """Verify calendar view groups reports by date and unknown dates are preserved."""
    route = next(r for r in app_instance.routes if r.path == "/api/v1/patients/{patient_id}/calendar" and "GET" in r.methods)
    handler = route.endpoint

    res = handler(patient_id="SYN-1002")
    cal = res["calendar"]
    assert "2026-04-04" in cal
    assert "unknown_date" in cal
    assert len(cal["unknown_date"]) == 1


# -----------------------------------------------------------------------------
# Report Details & Abnormal Summary Tests
# -----------------------------------------------------------------------------

def test_api_report_details_and_abnormal_summary(app_instance):
    """Verify report details and abnormal summary categorization."""
    rep_list_route = next(r for r in app_instance.routes if r.path == "/api/v1/patients/{patient_id}/reports" and "GET" in r.methods)
    rep_list = rep_list_route.endpoint(patient_id="SYN-1002", category=None, start_date=None, end_date=None, q=None)["reports"]
    dated_rep = next(r for r in rep_list if r["report_date"] == "2026-04-04")
    report_id = dated_rep["report_id"]

    # 1. Report details
    detail_route = next(r for r in app_instance.routes if r.path == "/api/v1/reports/{report_id}" and "GET" in r.methods)
    det = detail_route.endpoint(report_id=report_id)
    assert det["report_id"] == report_id

    # 2. Abnormal summary: Fasting Glucose was 118 (Ref 70-110) -> above_range
    ab_route = next(r for r in app_instance.routes if r.path == "/api/v1/reports/{report_id}/abnormal-summary" and "GET" in r.methods)
    ab_data = ab_route.endpoint(report_id=report_id)
    assert len(ab_data["above_range"]) == 1
    assert ab_data["above_range"][0]["original_name"] == "Fasting Glucose"
    assert ab_data["above_range"][0]["result_value"] == 118.0


# -----------------------------------------------------------------------------
# Longitudinal Trends Tests
# -----------------------------------------------------------------------------

def test_api_longitudinal_trends(app_instance):
    """Verify trend retrieval for Hemoglobin across 3 dates."""
    route = next(r for r in app_instance.routes if r.path == "/api/v1/patients/{patient_id}/trends" and "GET" in r.methods)
    handler = route.endpoint

    data = handler(patient_id="SYN-1001", parameter="Hemoglobin")
    assert data["data_points_count"] == 3
    assert data["unit_compatible"] is True
    assert data["units_detected"] == ["g/dL"]

    points = data["data_points"]
    # Ascending dates
    assert [p["report_date"] for p in points] == ["2026-04-03", "2026-06-15", "2026-10-20"]
    assert [p["result_value"] for p in points] == [14.2, 13.5, 14.8]


def test_api_available_parameters(app_instance):
    """Verify list of standardized parameters available for trend selection."""
    route = next(r for r in app_instance.routes if r.path == "/api/v1/patients/{patient_id}/parameters" and "GET" in r.methods)
    params = route.endpoint(patient_id="SYN-1001")["parameters"]
    names = [p["standardized_name"] for p in params]
    assert "Hemoglobin" in names
    assert "WBC Count" in names


# -----------------------------------------------------------------------------
# Ingestion Endpoints (Mock API JSON & Uploads) Tests
# -----------------------------------------------------------------------------

def test_api_ingest_json_report(app_instance):
    """Verify structured JSON API ingestion and duplicate prevention."""
    route = next(r for r in app_instance.routes if r.path == "/api/v1/reports/json" and "POST" in r.methods)
    handler = route.endpoint

    payload = {
        "patient_id": "SYN-1001",
        "report_id": "API-TEST-001",
        "report_date": "2026-11-01",
        "report_category": "Biochemistry",
        "parameters": [
            {
                "test_name": "Fasting Glucose",
                "result_value": 92.0,
                "unit": "mg/dL",
                "reference_range_text": "70 - 110",
                "reference_low": 70.0,
                "reference_high": 110.0,
            }
        ],
    }

    # 1. Ingest successfully
    res = handler(payload=payload)
    assert res["report_id"] == "API-TEST-001"

    # 2. Duplicate ingestion attempt -> 409 Conflict
    with pytest.raises(HTTPException) as exc:
        handler(payload=payload)
    assert exc.value.status_code == 409
    assert "duplicate" in exc.value.detail.lower()


def test_api_ingest_json_validation_error(app_instance):
    """Verify missing patient_id produces 422 error."""
    route = next(r for r in app_instance.routes if r.path == "/api/v1/reports/json" and "POST" in r.methods)
    handler = route.endpoint
    with pytest.raises(HTTPException) as exc:
        handler(payload={"report_category": "Biochemistry"})
    assert exc.value.status_code == 422


@pytest.mark.anyio
async def test_api_file_upload_text(app_instance):
    """Verify text file upload, duplicate rejection, and invalid format handling."""
    route = next(r for r in app_instance.routes if r.path == "/api/v1/reports/upload" and "POST" in r.methods)
    handler = route.endpoint

    txt_content = (
        b"SYNTHETIC TEST DOCUMENT\n"
        b"Patient Name: Rohan Example\n"
        b"Patient ID: SYN-1001\n"
        b"Registered On: 2026-11-15\n"
        b"Report Type: Complete Blood Count\n\n"
        b"Haemoglobin: 14.5 g/dL (Reference 13.0 - 17.0)\n"
    )

    # 1. Upload new report
    upload_file = UploadFile(filename="new_cbc_nov.txt", file=io.BytesIO(txt_content))
    res = await handler(file=upload_file, patient_id="SYN-1001")
    assert res["parameters_count"] == 1

    # 2. Upload duplicate -> 409 Conflict
    dup_file = UploadFile(filename="new_cbc_nov.txt", file=io.BytesIO(txt_content))
    with pytest.raises(HTTPException) as exc:
        await handler(file=dup_file, patient_id="SYN-1001")
    assert exc.value.status_code == 409
    assert "duplicate" in exc.value.detail.lower()

    # 3. Invalid extension upload -> 400 Bad Request
    inv_file = UploadFile(filename="bad_file.exe", file=io.BytesIO(b"binary"))
    with pytest.raises(HTTPException) as exc_inv:
        await handler(file=inv_file, patient_id=None)
    assert exc_inv.value.status_code == 400
    assert "unsupported file format" in exc_inv.value.detail.lower()


@pytest.mark.anyio
async def test_api_file_upload_scanned_pdf_needs_ocr(app_instance):
    """Verify blank / scanned PDF upload is explicitly marked as 'ocr_required'."""
    route = next(r for r in app_instance.routes if r.path == "/api/v1/reports/upload" and "POST" in r.methods)
    handler = route.endpoint

    pdf = FPDF()
    pdf.add_page()
    pdf_bytes = bytes(pdf.output())

    pdf_file = UploadFile(filename="scanned_blank.pdf", file=io.BytesIO(pdf_bytes))
    res = await handler(file=pdf_file, patient_id="SYN-1001")
    assert res["extraction_status"] == "ocr_required"
    assert "needs ocr" in res["message"].lower()
