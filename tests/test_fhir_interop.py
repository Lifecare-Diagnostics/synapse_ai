"""
Tests for Phase 6A: FHIR R4 and HL7 v2 Interoperability Layer
Verifies resource mapping, validation, ingestion, export, duplicate rejection, and audit trails.
"""

import json
import pytest
from synapse.fhir import (
    build_fhir_patient,
    build_fhir_observation,
    build_fhir_diagnostic_report,
    export_report_to_fhir_bundle,
    export_patient_to_fhir_bundle,
    validate_fhir_bundle,
    parse_fhir_bundle_to_synapse_record,
    parse_hl7_v2_oru_r01,
    get_interop_status,
    get_interop_audit_logs,
)
from synapse.schema import (
    PatientDemographics,
    PatientReport,
    ReportParameter,
    Patient,
)
from synapse.storage import WalletStorage
from synapse.api import create_app


@pytest.fixture
def mock_storage():
    """In-memory WalletStorage instance for testing."""
    return WalletStorage(":memory:")


@pytest.fixture
def app_instance(mock_storage):
    """FastAPI application with injected test storage."""
    return create_app(mock_storage)


@pytest.fixture
def sample_patient_demographics():
    return PatientDemographics(
        patient_id="SYN-2001",
        patient_name="Ananya Verma",
        date_of_birth="1988-05-14",
        age=38,
        sex="Female",
        medical_history=[],
    )


@pytest.fixture
def sample_patient_report():
    param1 = ReportParameter(
        parameter_id="PARAM-001",
        report_id="REP-CBC-01",
        patient_id="SYN-2001",
        original_name="Haemoglobin",
        standardized_name="Hemoglobin",
        result_value=11.2,
        unit="g/dL",
        reference_range_text="12.0 - 15.5",
        reference_low=12.0,
        reference_high=15.5,
        clinical_flag="low",
        abnormality_category="below_range",
        extraction_status="ok",
        source_text="Haemoglobin: 11.2 g/dL (12.0 - 15.5)",
        review_flags=[],
        report_date="2026-11-19",
    )
    param2 = ReportParameter(
        parameter_id="PARAM-002",
        report_id="REP-CBC-01",
        patient_id="SYN-2001",
        original_name="Platelet Count",
        standardized_name="Platelet Count",
        result_value=240.0,
        unit="thou/uL",
        reference_range_text="150.0 - 450.0",
        reference_low=150.0,
        reference_high=450.0,
        clinical_flag="normal",
        abnormality_category="within_range",
        extraction_status="ok",
        source_text="Platelet Count: 240 thou/uL (150 - 450)",
        review_flags=[],
        report_date="2026-11-19",
    )
    return PatientReport(
        report_id="REP-CBC-01",
        patient_id="SYN-2001",
        report_date="2026-11-19",
        date_label="Registered On",
        report_category="Complete Blood Count",
        original_filename="ananya_cbc.pdf",
        file_format="pdf",
        upload_datetime="2026-11-19T10:00:00Z",
        extraction_status="success",
        review_status="clean",
        original_document_location="/docs/ananya_cbc.pdf",
        content_hash="abc123hash",
        parameters=[param1, param2],
        key_text_sections={"Clinical Impression": "Mild microcytic anemia suggested."},
        document_level_flags=[],
        validation_errors=[],
    )


# ==============================================================================
# Unit Tests: FHIR R4 Builders & Mappings
# ==============================================================================

def test_interop_status_metadata():
    """Verify interoperability status provides correct specification versions and synthetic mode."""
    status_info = get_interop_status()
    assert status_info["fhir_version"] == "4.0.1"
    assert status_info["hl7_version"] == "2.5.1"
    assert status_info["connection_mode"] == "mock_synthetic_gateway"
    assert status_info["live_ehr_connected"] is False
    assert "Patient" in status_info["supported_resources"]


def test_build_fhir_patient(sample_patient_demographics):
    """Verify Patient resource generation conforms to FHIR R4 structure."""
    patient_res = build_fhir_patient(sample_patient_demographics)
    assert patient_res["resourceType"] == "Patient"
    assert patient_res["id"] == "SYN-2001"
    assert patient_res["name"][0]["text"] == "Ananya Verma"
    assert patient_res["gender"] == "female"
    assert patient_res["birthDate"] == "1988-05-14"
    assert patient_res["identifier"][0]["value"] == "SYN-2001"


def test_build_fhir_observation(sample_patient_report):
    """Verify Observation resource generation with values, units, reference intervals, and interpretation."""
    param = sample_patient_report.parameters[0]
    obs = build_fhir_observation(param)
    assert obs["resourceType"] == "Observation"
    assert obs["id"] == "PARAM-001"
    assert obs["status"] == "final"
    assert obs["code"]["text"] == "Haemoglobin"
    assert obs["subject"]["reference"] == "Patient/SYN-2001"
    assert obs["valueQuantity"]["value"] == 11.2
    assert obs["valueQuantity"]["unit"] == "g/dL"
    assert obs["referenceRange"][0]["low"]["value"] == 12.0
    assert obs["referenceRange"][0]["high"]["value"] == 15.5
    assert obs["interpretation"][0]["coding"][0]["code"] == "L"


def test_export_report_to_fhir_bundle(sample_patient_report, sample_patient_demographics):
    """Verify export of DiagnosticReport and Observations into a FHIR R4 Collection Bundle."""
    bundle = export_report_to_fhir_bundle(sample_patient_report, sample_patient_demographics)
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "collection"
    assert bundle["total"] == 4  # 1 Patient + 2 Observations + 1 DiagnosticReport

    res_types = [e["resource"]["resourceType"] for e in bundle["entry"]]
    assert res_types == ["Patient", "Observation", "Observation", "DiagnosticReport"]

    diag_rep = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "DiagnosticReport")
    assert diag_rep["id"] == "REP-CBC-01"
    assert len(diag_rep["result"]) == 2
    assert "Clinical Impression" in diag_rep["conclusion"]


def test_export_patient_to_fhir_bundle(sample_patient_report, sample_patient_demographics):
    """Verify export of full patient record to FHIR Bundle."""
    patient = Patient(
        patient_id="SYN-2001",
        demographics=sample_patient_demographics,
        reports=[sample_patient_report],
    )
    bundle = export_patient_to_fhir_bundle(patient)
    assert bundle["resourceType"] == "Bundle"
    assert bundle["total"] >= 4
    assert any(e["resource"]["resourceType"] == "Patient" for e in bundle["entry"])


# ==============================================================================
# Validation & Parsing Tests
# ==============================================================================

def test_validate_fhir_bundle_valid(sample_patient_report, sample_patient_demographics):
    """Verify valid FHIR bundle passes validation without errors."""
    bundle = export_report_to_fhir_bundle(sample_patient_report, sample_patient_demographics)
    is_valid, errors = validate_fhir_bundle(bundle)
    assert is_valid is True
    assert len(errors) == 0


def test_validate_fhir_bundle_invalid_payloads():
    """Verify validation detects malformed bundles, missing types, and missing codes."""
    # 1. Not a dict
    is_valid, errors = validate_fhir_bundle("not a json object")  # type: ignore
    assert is_valid is False

    # 2. Unknown resource type
    is_valid, errors = validate_fhir_bundle({"resourceType": "MedicationRequest"})
    assert is_valid is False
    assert "Unsupported resourceType" in errors[0]

    # 3. Missing entry list
    is_valid, errors = validate_fhir_bundle({"resourceType": "Bundle"})
    assert is_valid is False
    assert "must contain an 'entry' list" in errors[0]

    # 4. DiagnosticReport missing code
    bad_bundle = {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "DiagnosticReport",
                    "subject": {"reference": "Patient/123"},
                }
            }
        ],
    }
    is_valid, errors = validate_fhir_bundle(bad_bundle)
    assert is_valid is False
    assert any("missing 'code'" in err for err in errors)


def test_parse_fhir_bundle_to_synapse_record(sample_patient_report, sample_patient_demographics):
    """Verify parsing of incoming FHIR Bundle into internal Synapse ingestion payload."""
    bundle = export_report_to_fhir_bundle(sample_patient_report, sample_patient_demographics)
    parsed = parse_fhir_bundle_to_synapse_record(bundle)

    assert parsed["patient_id"] == "SYN-2001"
    assert parsed["demographics"].patient_name == "Ananya Verma"
    assert parsed["report_date"] == "2026-11-19"
    assert len(parsed["parameters"]) == 2
    assert parsed["parameters"][0]["original_name"] == "Haemoglobin"
    assert parsed["parameters"][0]["result_value"] == 11.2
    assert parsed["parameters"][0]["reference_low"] == 12.0


# ==============================================================================
# HL7 v2 ORU^R01 Message Parser Tests
# ==============================================================================

def test_parse_hl7_v2_oru_r01():
    """Verify HL7 v2 ORU^R01 message parsing into patient demographics and observations."""
    hl7_msg = """MSH|^~\\&|LAB_LIS|HOSPITAL|SYNAPSE|LIFECARE|20261119120000||ORU^R01|MSG-9901|P|2.5.1
PID|1||SYN-3001^^^LIFECARE||KAPOOR^RAJESH||19750820|M
OBR|1||ORDER-8812|CBC^Complete Blood Count^LN|||20261119103000
OBX|1|NM|WBC^White Blood Cell Count^LN||7.8|thou/uL|4.5-11.0|N|||F
OBX|2|NM|HGB^Hemoglobin^LN||16.4|g/dL|13.0-17.0|N|||F
OBX|3|NM|PLT^Platelets^LN||120|thou/uL|150-450|L|||F
"""
    parsed = parse_hl7_v2_oru_r01(hl7_msg)
    assert parsed["patient_id"] == "SYN-3001"
    assert parsed["demographics"].patient_name == "RAJESH KAPOOR"
    assert parsed["demographics"].date_of_birth == "1975-08-20"
    assert parsed["demographics"].sex == "Male"
    assert parsed["report_date"] == "2026-11-19"
    assert len(parsed["parameters"]) == 3

    p_plt = next(p for p in parsed["parameters"] if p["original_name"] == "Platelets")
    assert p_plt["result_value"] == 120.0
    assert p_plt["unit"] == "thou/uL"
    assert p_plt["reference_low"] == 150.0
    assert p_plt["reference_high"] == 450.0


def test_parse_hl7_v2_invalid_missing_msh():
    """Verify parsing message without MSH segment raises ValueError."""
    bad_msg = "PID|1||SYN-001\nOBX|1|NM|Test||10|||||F"
    with pytest.raises(ValueError, match="Missing MSH"):
        parse_hl7_v2_oru_r01(bad_msg)


# ==============================================================================
# API Integration Tests: FHIR & HL7 Endpoints
# ==============================================================================

@pytest.mark.anyio
async def test_api_fhir_ingest_and_export_roundtrip(app_instance, sample_patient_report, sample_patient_demographics):
    """Verify end-to-end API ingestion of FHIR R4 Bundle and subsequent export via REST."""
    ingest_route = next(r for r in app_instance.routes if r.path == "/api/v1/interop/fhir/ingest" and "POST" in r.methods)
    export_rep_route = next(r for r in app_instance.routes if r.path == "/api/v1/interop/fhir/reports/{report_id}" and "GET" in r.methods)
    export_pat_route = next(r for r in app_instance.routes if r.path == "/api/v1/interop/fhir/patients/{patient_id}" and "GET" in r.methods)

    bundle = export_report_to_fhir_bundle(sample_patient_report, sample_patient_demographics)
    # Give unique report ID for test isolation
    bundle["id"] = "BUNDLE-ROUNDTRIP-01"
    for e in bundle["entry"]:
        if e["resource"]["resourceType"] == "DiagnosticReport":
            e["resource"]["id"] = "REP-ROUNDTRIP-01"
            e["resource"]["identifier"] = [{"system": "urn:lifecare:report:id", "value": "REP-ROUNDTRIP-01"}]

    # 1. Ingest via API
    res = ingest_route.endpoint(payload=bundle)
    assert res["message"] == "FHIR R4 Bundle ingested successfully."
    assert res["report_id"] == "REP-ROUNDTRIP-01"
    assert res["parameters_count"] == 2

    # 2. Export DiagnosticReport Bundle
    exported_bundle = export_rep_route.endpoint(report_id="REP-ROUNDTRIP-01")
    assert exported_bundle["resourceType"] == "Bundle"
    assert exported_bundle["total"] == 4

    # 3. Export Patient Bundle
    pat_bundle = export_pat_route.endpoint(patient_id="SYN-2001")
    assert pat_bundle["resourceType"] == "Bundle"
    assert any(e["resource"]["resourceType"] == "Patient" for e in pat_bundle["entry"])


@pytest.mark.anyio
async def test_api_fhir_ingest_duplicate_conflict(app_instance, sample_patient_report, sample_patient_demographics):
    """Verify that posting the exact same FHIR bundle twice triggers a 409 Conflict."""
    ingest_route = next(r for r in app_instance.routes if r.path == "/api/v1/interop/fhir/ingest" and "POST" in r.methods)
    bundle = export_report_to_fhir_bundle(sample_patient_report, sample_patient_demographics)
    bundle["id"] = "BUNDLE-DUP-01"
    for e in bundle["entry"]:
        if e["resource"]["resourceType"] == "DiagnosticReport":
            e["resource"]["id"] = "REP-DUP-01"
            e["resource"]["identifier"] = [{"system": "urn:lifecare:report:id", "value": "REP-DUP-01"}]

    # First attempt succeeds
    ingest_route.endpoint(payload=bundle)

    # Second attempt must raise 409 Conflict
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        ingest_route.endpoint(payload=bundle)
    assert exc.value.status_code == 409
    assert "Duplicate FHIR report detected" in exc.value.detail


@pytest.mark.anyio
async def test_api_hl7_ingest_and_duplicate(app_instance):
    """Verify HL7 v2 ORU^R01 API ingestion and duplicate detection."""
    hl7_route = next(r for r in app_instance.routes if r.path == "/api/v1/interop/hl7/ingest" and "POST" in r.methods)
    from fastapi import HTTPException

    hl7_text = """MSH|^~\\&|LAB_LIS|HOSPITAL|SYNAPSE|LIFECARE|20261119130000||ORU^R01|MSG-HL7-TEST|P|2.5.1
PID|1||SYN-4001^^^LIFECARE||SHARMA^VIKRAM||19820311|M
OBR|1||ORDER-9999|LIPID^Lipid Profile^LN|||20261119110000
OBX|1|NM|CHOL^Cholesterol Total^LN||210|mg/dL|125-200|H|||F
"""
    payload = {"message": hl7_text}

    # 1. First ingestion succeeds
    res = hl7_route.endpoint(payload=payload)
    assert res["message"] == "HL7 v2 ORU^R01 message ingested successfully."
    assert res["patient_id"] == "SYN-4001"
    assert res["parameters_count"] == 1

    # 2. Second ingestion triggers 409
    with pytest.raises(HTTPException) as exc:
        hl7_route.endpoint(payload=payload)
    assert exc.value.status_code == 409
    assert "Duplicate HL7 message detected" in exc.value.detail


@pytest.mark.anyio
async def test_api_interop_audit_endpoint(app_instance):
    """Verify integration audit log endpoint returns logged interop events."""
    audit_route = next(r for r in app_instance.routes if r.path == "/api/v1/interop/audit" and "GET" in r.methods)
    res = audit_route.endpoint(limit=50)
    assert "audit_events" in res
    assert isinstance(res["audit_events"], list)
    assert len(res["audit_events"]) > 0
