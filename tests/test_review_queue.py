"""
Tests for Phase 6B: Review Queue and Clinical Audit UI / API.
Verifies review queue listing, review actions (approve/reject/needs_review),
field-level parameter correction with audit logging, and FHIR export safeguards.
"""

import json
import pytest
from fastapi import HTTPException
from synapse.schema import (
    PatientDemographics,
    PatientReport,
    ReportParameter,
    ReviewFlag,
)
from synapse.storage import WalletStorage
from synapse.api import create_app


@pytest.fixture
def mock_storage():
    """In-memory WalletStorage instance for review queue testing."""
    return WalletStorage(":memory:")


@pytest.fixture
def app_instance(mock_storage):
    """FastAPI application with injected test storage."""
    return create_app(mock_storage)


@pytest.fixture
def sample_review_setup(mock_storage):
    """Pre-populates storage with a patient and reports needing review."""
    demo = PatientDemographics(
        patient_id="SYN-9001",
        patient_name="Rajesh Khanna",
        date_of_birth="1975-08-20",
        age=51,
        sex="Male",
        medical_history=[],
    )
    mock_storage.save_patient(demo)

    param1 = ReportParameter(
        parameter_id="PARAM-901",
        report_id="REP-REV-01",
        patient_id="SYN-9001",
        original_name="Hb",
        standardized_name="Hemoglobin",
        result_value=8.4,
        unit="g/dL",
        reference_range_text="13.0 - 17.0",
        reference_low=13.0,
        reference_high=17.0,
        clinical_flag="low",
        abnormality_category="below_range",
        extraction_status="ok",
        source_text="Hb: 8.4 g/dL",
        review_flags=[],
        report_date="2026-11-19",
    )
    param2 = ReportParameter(
        parameter_id="PARAM-902",
        report_id="REP-REV-01",
        patient_id="SYN-9001",
        original_name="Fasting Sugar",
        standardized_name="Glucose, Fasting",
        result_value=142.0,
        unit="mg/dL",
        reference_range_text="70.0 - 99.0",
        reference_low=70.0,
        reference_high=99.0,
        clinical_flag="high",
        abnormality_category="above_range",
        extraction_status="needs_review",
        source_text="Fasting Sugar: 142 mg/dL",
        review_flags=[ReviewFlag(field="Fasting Sugar", reason="Verify fasting duration", severity="warning")],
        report_date="2026-11-19",
    )

    report = PatientReport(
        report_id="REP-REV-01",
        patient_id="SYN-9001",
        report_date="2026-11-19",
        date_label="Collected On",
        report_category="Complete Blood Count",
        original_filename="rajesh_cbc.pdf",
        file_format="pdf",
        upload_datetime="2026-11-19T09:30:00Z",
        extraction_status="needs_review",
        review_status="needs_review",
        original_document_location="/docs/rajesh_cbc.pdf",
        content_hash="hash901",
        parameters=[param1, param2],
        key_text_sections={"Impression": "Moderate microcytic hypochromic anemia."},
        document_level_flags=[],
        validation_errors=[],
    )
    mock_storage.save_report(report)
    return report


def test_review_queue_listing(app_instance, sample_review_setup):
    """Verify that reports needing review appear in the review queue."""
    route = next(r for r in app_instance.routes if r.path == "/api/v1/review/queue" and "GET" in r.methods)
    res = route.endpoint(status=None)

    assert "queue" in res
    assert res["total"] >= 1
    found = next((r for r in res["queue"] if r["report_id"] == "REP-REV-01"), None)
    assert found is not None
    assert found["review_status"] == "needs_review"
    assert found["patient_name"] == "Rajesh Khanna"


def test_record_review_action_approve(app_instance, sample_review_setup):
    """Verify approving a report changes review_status and records audit entry."""
    route = next(r for r in app_instance.routes if r.path == "/api/v1/review/reports/{report_id}/action" and "POST" in r.methods)
    from synapse.api import create_app

    # Execute approval
    payload = type("Payload", (), {
        "action": "approve",
        "reviewer": "Dr. Sunita Rao (Pathologist)",
        "comments": "Values verified against laboratory analyzer printout.",
    })()
    res = route.endpoint(report_id="REP-REV-01", payload=payload)

    assert res["new_status"] == "approved"
    assert res["audit_entry"]["action"] == "approve"
    assert res["audit_entry"]["reviewer"] == "Dr. Sunita Rao (Pathologist)"
    assert res["audit_entry"]["previous_status"] == "needs_review"
    assert res["audit_entry"]["new_status"] == "approved"


def test_record_review_action_reject(app_instance, sample_review_setup):
    """Verify rejecting a report changes status to rejected with comment."""
    route = next(r for r in app_instance.routes if r.path == "/api/v1/review/reports/{report_id}/action" and "POST" in r.methods)
    payload = type("Payload", (), {
        "action": "reject",
        "reviewer": "Dr. Sunita Rao (Pathologist)",
        "comments": "Sample hemolysis detected. Re-collection requested.",
    })()
    res = route.endpoint(report_id="REP-REV-01", payload=payload)

    assert res["new_status"] == "rejected"
    assert res["audit_entry"]["action"] == "reject"
    assert res["audit_entry"]["comments"] == "Sample hemolysis detected. Re-collection requested."


def test_field_level_parameter_correction(app_instance, sample_review_setup, mock_storage):
    """Verify correcting a field updates the value, recalculates flags, and creates audit record."""
    route = next(r for r in app_instance.routes if r.path == "/api/v1/review/reports/{report_id}/parameters/{parameter_id}/correct" and "POST" in r.methods)

    # Correct Hb from 8.4 to 14.0 (normal range 13.0 - 17.0)
    payload = type("Payload", (), {
        "corrected_value": 14.0,
        "corrected_name": "Hemoglobin Total",
        "corrected_unit": "g/dL",
        "reviewer": "Quality Auditor Meera",
        "reason": "OCR read 8.4 instead of 14.0 due to smudge on paper.",
    })()

    res = route.endpoint(report_id="REP-REV-01", parameter_id="PARAM-901", payload=payload)
    assert res["message"] == "Parameter corrected successfully."
    assert res["data"]["result_value"] == 14.0
    assert res["data"]["clinical_flag"] == "normal"
    assert res["data"]["abnormality_category"] == "within_range"

    # Verify report status is updated to 'corrected'
    rep = mock_storage.get_report("REP-REV-01")
    assert rep.review_status == "corrected"

    # Verify parameter in storage
    param = next(p for p in rep.parameters if p.parameter_id == "PARAM-901")
    assert param.result_value == 14.0
    assert param.clinical_flag == "normal"


def test_review_history_endpoint(app_instance, sample_review_setup):
    """Verify chronological audit trail endpoint returns all actions and corrections."""
    action_route = next(r for r in app_instance.routes if r.path == "/api/v1/review/reports/{report_id}/action" and "POST" in r.methods)
    history_route = next(r for r in app_instance.routes if r.path == "/api/v1/review/reports/{report_id}/history" and "GET" in r.methods)

    payload = type("Payload", (), {
        "action": "needs_review",
        "reviewer": "Lab Tech Anil",
        "comments": "Flagged for senior review due to outlier glucose.",
    })()
    action_route.endpoint(report_id="REP-REV-01", payload=payload)

    history_res = history_route.endpoint(report_id="REP-REV-01")
    assert history_res["report_id"] == "REP-REV-01"
    assert history_res["total_entries"] >= 1
    assert any(h["action"] == "needs_review" for h in history_res["history"])


def test_export_safeguard_blocks_unapproved_report(app_instance, sample_review_setup):
    """Verify FHIR export is blocked with HTTP 403 when a report has needs_review status."""
    export_route = next(r for r in app_instance.routes if r.path == "/api/v1/interop/fhir/reports/{report_id}" and "GET" in r.methods)

    with pytest.raises(HTTPException) as exc:
        export_route.endpoint(report_id="REP-REV-01", enforce_approval=True)
    assert exc.value.status_code == 403
    assert "Export blocked: Clinical approval required" in exc.value.detail


def test_export_safeguard_blocks_rejected_report(app_instance, sample_review_setup):
    """Verify FHIR export is blocked with HTTP 403 when a report is rejected."""
    action_route = next(r for r in app_instance.routes if r.path == "/api/v1/review/reports/{report_id}/action" and "POST" in r.methods)
    export_route = next(r for r in app_instance.routes if r.path == "/api/v1/interop/fhir/reports/{report_id}" and "GET" in r.methods)

    # Reject report
    payload = type("Payload", (), {
        "action": "reject",
        "reviewer": "Dr. Sunita Rao",
        "comments": "Invalid specimen.",
    })()
    action_route.endpoint(report_id="REP-REV-01", payload=payload)

    with pytest.raises(HTTPException) as exc:
        export_route.endpoint(report_id="REP-REV-01", enforce_approval=True)
    assert exc.value.status_code == 403
    assert "rejected" in exc.value.detail.lower()


def test_export_safeguard_allows_approved_report(app_instance, sample_review_setup):
    """Verify approving a report allows FHIR export to succeed."""
    action_route = next(r for r in app_instance.routes if r.path == "/api/v1/review/reports/{report_id}/action" and "POST" in r.methods)
    export_route = next(r for r in app_instance.routes if r.path == "/api/v1/interop/fhir/reports/{report_id}" and "GET" in r.methods)

    # Approve report
    payload = type("Payload", (), {
        "action": "approve",
        "reviewer": "Dr. Sunita Rao",
        "comments": "Approved after clinical verification.",
    })()
    action_route.endpoint(report_id="REP-REV-01", payload=payload)

    bundle = export_route.endpoint(report_id="REP-REV-01", enforce_approval=True)
    assert bundle["resourceType"] == "Bundle"
    assert bundle["total"] == 4  # Patient + 2 Observations + DiagnosticReport


def test_patient_export_filters_unapproved_reports(app_instance, sample_review_setup, mock_storage):
    """Verify patient FHIR export omits reports that are not approved when enforce_approval=True."""
    pat_export_route = next(r for r in app_instance.routes if r.path == "/api/v1/interop/fhir/patients/{patient_id}" and "GET" in r.methods)

    # Initially REP-REV-01 has review_status='needs_review'
    bundle = pat_export_route.endpoint(patient_id="SYN-9001", enforce_approval=True)
    # Bundle should only contain the Patient resource, omitting the unapproved DiagnosticReport & Observations
    assert bundle["resourceType"] == "Bundle"
    assert bundle["total"] == 1
    assert bundle["entry"][0]["resource"]["resourceType"] == "Patient"
