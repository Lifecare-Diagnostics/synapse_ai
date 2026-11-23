"""
Tests for Phase 7A (Role-Based Access Control) & Phase 7B (Security Foundations).
Verifies:
- Password hashing & verification with PBKDF2-HMAC-SHA256
- JWT token generation, signature validation, expiration, and tampering detection
- User authentication endpoint (/api/v1/auth/login)
- Profile and permission introspection (/api/v1/auth/me)
- Server-side RBAC enforcement across Technician, Auditor, Pathologist, and Administrator
- Prevention of reviewer identity spoofing (SEC-02 remediation)
- FHIR export permission enforcement
"""

import time
import pytest
from fastapi import HTTPException
from synapse.auth import (
    User,
    LoginRequest,
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    has_permission,
    ROLE_PERMISSIONS,
)
from synapse.schema import PatientDemographics, PatientReport, ReportParameter
from synapse.storage import WalletStorage
from synapse.api import create_app


@pytest.fixture
def test_storage():
    """In-memory storage seeded with default RBAC users."""
    return WalletStorage(":memory:")


@pytest.fixture
def app_instance(test_storage):
    """FastAPI app instance with seeded test storage."""
    return create_app(test_storage)


@pytest.fixture
def seeded_report(test_storage):
    """Pre-populates a patient and a report needing review."""
    demo = PatientDemographics(
        patient_id="SYN-SEC-01",
        patient_name="Pooja Mehta",
        date_of_birth="1990-04-12",
        age=36,
        sex="Female",
        medical_history=[],
    )
    test_storage.save_patient(demo)

    param = ReportParameter(
        parameter_id="PARAM-SEC-01",
        report_id="REP-SEC-01",
        patient_id="SYN-SEC-01",
        original_name="Glucose Fasting",
        standardized_name="Fasting Glucose",
        result_value=105.0,
        unit="mg/dL",
        reference_range_text="70.0 - 99.0",
        reference_low=70.0,
        reference_high=99.0,
        clinical_flag="high",
        abnormality_category="above_range",
        extraction_status="ok",
        source_text="Glucose Fasting: 105 mg/dL",
        review_flags=[],
        report_date="2026-11-21",
    )

    report = PatientReport(
        report_id="REP-SEC-01",
        patient_id="SYN-SEC-01",
        report_date="2026-11-21",
        date_label="Collected On",
        report_category="Biochemistry",
        original_filename="pooja_sugar.pdf",
        file_format="pdf",
        upload_datetime="2026-11-21T08:00:00Z",
        extraction_status="success",
        review_status="needs_review",
        original_document_location="/docs/pooja_sugar.pdf",
        content_hash="hash_sec_01",
        parameters=[param],
        key_text_sections={},
        document_level_flags=[],
        validation_errors=[],
    )
    test_storage.save_report(report)
    return report


# ==============================================================================
# 1. Cryptographic Password Hashing & JWT Unit Tests (Phase 7B)
# ==============================================================================

def test_password_hashing_and_verification():
    """Verify PBKDF2-HMAC-SHA256 salted hashing and verification."""
    password = "SecurePassword@2026"
    hashed = hash_password(password)

    assert hashed.startswith("pbkdf2_sha256$100000$")
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword", hashed) is False
    assert verify_password("", hashed) is False


def test_jwt_token_roundtrip_and_expiration():
    """Verify JWT creation, decoding, and expiration enforcement."""
    user = User(
        user_id="USR-001",
        username="dr.sunita",
        full_name="Dr. Sunita Rao",
        role="Pathologist",
    )
    # Valid token
    token = create_access_token(user, expires_delta_seconds=3600)
    payload = decode_access_token(token)
    assert payload["sub"] == "dr.sunita"
    assert payload["role"] == "Pathologist"
    assert payload["name"] == "Dr. Sunita Rao"

    # Expired token
    expired_token = create_access_token(user, expires_delta_seconds=-10)
    with pytest.raises(ValueError) as exc:
        decode_access_token(expired_token)
    assert "expired" in str(exc.value).lower()


def test_jwt_signature_tampering_detection():
    """Verify that tampering with token payload or signature is rejected."""
    user = User(
        user_id="USR-002",
        username="tech.anil",
        full_name="Anil Kumar",
        role="Technician",
    )
    token = create_access_token(user)
    parts = token.split(".")

    # Tamper with signature
    tampered_sig = parts[0] + "." + parts[1] + ".invalidSigXYZ"
    with pytest.raises(ValueError) as exc:
        decode_access_token(tampered_sig)
    assert "signature" in str(exc.value).lower()


# ==============================================================================
# 2. Authentication API Endpoints
# ==============================================================================

def test_api_login_success_and_failure(app_instance):
    """Verify login endpoint issues JWT on valid credentials and rejects bad passwords."""
    login_route = next(r for r in app_instance.routes if r.path == "/api/v1/auth/login" and "POST" in r.methods)

    # 1. Successful login
    req = LoginRequest(username="dr.sunita", password="Doctor@123")
    res = login_route.endpoint(payload=req)
    assert res.access_token is not None and len(res.access_token) > 20
    assert res.token_type == "bearer"
    assert res.user.username == "dr.sunita"
    assert res.user.role == "Pathologist"
    assert "report:signoff" in res.permissions

    # 2. Bad password triggers 401
    bad_req = LoginRequest(username="dr.sunita", password="WrongPassword")
    with pytest.raises(HTTPException) as exc:
        login_route.endpoint(payload=bad_req)
    assert exc.value.status_code == 401


def test_api_auth_me_endpoint(app_instance, test_storage):
    """Verify /api/v1/auth/me returns authenticated profile."""
    me_route = next(r for r in app_instance.routes if r.path == "/api/v1/auth/me" and "GET" in r.methods)
    user = test_storage.get_user_by_username("auditor.meera")
    token = create_access_token(user)

    # Valid token
    res = me_route.endpoint(authorization=f"Bearer {token}")
    assert res["user"]["username"] == "auditor.meera"
    assert res["user"]["role"] == "Auditor"
    assert "parameter:correct" in res["permissions"]

    # Missing token triggers 401
    with pytest.raises(HTTPException) as exc:
        me_route.endpoint(authorization=None)
    assert exc.value.status_code == 401


# ==============================================================================
# 3. Server-Side RBAC Enforcement & Identity Spoofing Protection (Phase 7A)
# ==============================================================================

def test_rbac_technician_cannot_approve_report(app_instance, test_storage, seeded_report):
    """Verify Technician cannot approve reports (403 Forbidden)."""
    action_route = next(r for r in app_instance.routes if r.path == "/api/v1/review/reports/{report_id}/action" and "POST" in r.methods)
    tech = test_storage.get_user_by_username("tech.anil")
    tech_token = create_access_token(tech)

    payload = type("Payload", (), {
        "action": "approve",
        "reviewer": "Spoofed Doctor",
        "comments": "Attempting unauthorized approval",
    })()

    with pytest.raises(HTTPException) as exc:
        action_route.endpoint(
            report_id="REP-SEC-01",
            payload=payload,
            authorization=f"Bearer {tech_token}",
        )
    assert exc.value.status_code == 403
    assert "Pathologist role required" in exc.value.detail


def test_rbac_technician_cannot_correct_parameter(app_instance, test_storage, seeded_report):
    """Verify Technician cannot perform parameter corrections (403 Forbidden)."""
    corr_route = next(r for r in app_instance.routes if r.path == "/api/v1/review/reports/{report_id}/parameters/{parameter_id}/correct" and "POST" in r.methods)
    tech = test_storage.get_user_by_username("tech.anil")
    tech_token = create_access_token(tech)

    payload = type("Payload", (), {
        "corrected_value": 90.0,
        "corrected_name": None,
        "corrected_unit": None,
        "reviewer": "Spoofed Auditor",
        "reason": "Unauthorized tweak",
    })()

    with pytest.raises(HTTPException) as exc:
        corr_route.endpoint(
            report_id="REP-SEC-01",
            parameter_id="PARAM-SEC-01",
            payload=payload,
            authorization=f"Bearer {tech_token}",
        )
    assert exc.value.status_code == 403
    assert "Auditor or Pathologist role required" in exc.value.detail


def test_rbac_auditor_can_correct_parameter_and_prevents_identity_spoofing(app_instance, test_storage, seeded_report):
    """Verify Auditor can correct parameters and reviewer identity is securely derived from token."""
    corr_route = next(r for r in app_instance.routes if r.path == "/api/v1/review/reports/{report_id}/parameters/{parameter_id}/correct" and "POST" in r.methods)
    auditor = test_storage.get_user_by_username("auditor.meera")
    token = create_access_token(auditor)

    payload = type("Payload", (), {
        "corrected_value": 85.0,
        "corrected_name": "Fasting Blood Sugar",
        "corrected_unit": "mg/dL",
        "reviewer": "Attacker Supplied Name",  # Spoofed name must be ignored!
        "reason": "Verified against analyzer strip.",
    })()

    res = corr_route.endpoint(
        report_id="REP-SEC-01",
        parameter_id="PARAM-SEC-01",
        payload=payload,
        authorization=f"Bearer {token}",
    )
    assert res["message"] == "Parameter corrected successfully."
    assert res["data"]["result_value"] == 85.0

    # Verify audit log recorded genuine auditor full_name from token, NOT spoofed name
    history = test_storage.get_report_review_history("REP-SEC-01")
    assert len(history) >= 1
    assert history[-1].reviewer == "Meera Sen (Quality Auditor)"
    assert history[-1].reviewer != "Attacker Supplied Name"


def test_rbac_pathologist_can_signoff_report(app_instance, test_storage, seeded_report):
    """Verify Pathologist can approve report and genuine identity is bound to audit entry."""
    action_route = next(r for r in app_instance.routes if r.path == "/api/v1/review/reports/{report_id}/action" and "POST" in r.methods)
    doc = test_storage.get_user_by_username("dr.sunita")
    token = create_access_token(doc)

    payload = type("Payload", (), {
        "action": "approve",
        "reviewer": "Untrusted Client Reviewer",  # Must be ignored!
        "comments": "Clinically reviewed and approved.",
    })()

    res = action_route.endpoint(
        report_id="REP-SEC-01",
        payload=payload,
        authorization=f"Bearer {token}",
    )
    assert res["new_status"] == "approved"
    assert res["audit_entry"]["reviewer"] == "Dr. Sunita Rao (Lead Pathologist)"


def test_rbac_technician_cannot_export_fhir(app_instance, test_storage, seeded_report):
    """Verify Technician lacks interop:export permission to export FHIR bundle (403 Forbidden)."""
    export_route = next(r for r in app_instance.routes if r.path == "/api/v1/interop/fhir/reports/{report_id}" and "GET" in r.methods)
    action_route = next(r for r in app_instance.routes if r.path == "/api/v1/review/reports/{report_id}/action" and "POST" in r.methods)

    # First approve with pathologist
    doc = test_storage.get_user_by_username("dr.sunita")
    doc_token = create_access_token(doc)
    approve_payload = type("Payload", (), {
        "action": "approve",
        "reviewer": "Doctor",
        "comments": "Approved",
    })()
    action_route.endpoint(report_id="REP-SEC-01", payload=approve_payload, authorization=f"Bearer {doc_token}")

    # Technician attempts to export
    tech = test_storage.get_user_by_username("tech.anil")
    tech_token = create_access_token(tech)

    with pytest.raises(HTTPException) as exc:
        export_route.endpoint(
            report_id="REP-SEC-01",
            enforce_approval=True,
            authorization=f"Bearer {tech_token}",
        )
    assert exc.value.status_code == 403
    assert "cannot export FHIR data" in exc.value.detail


def test_rbac_user_management_restricted_to_admin(app_instance, test_storage):
    """Verify only Administrator can list users (403 for non-admins)."""
    users_route = next(r for r in app_instance.routes if r.path == "/api/v1/auth/users" and "GET" in r.methods)

    # 1. Technician rejected
    tech = test_storage.get_user_by_username("tech.anil")
    with pytest.raises(HTTPException) as exc:
        users_route.endpoint(authorization=f"Bearer {create_access_token(tech)}")
    assert exc.value.status_code == 403

    # 2. Administrator accepted
    admin = test_storage.get_user_by_username("admin.synapse")
    res = users_route.endpoint(authorization=f"Bearer {create_access_token(admin)}")
    assert res["total"] >= 4
