"""
tests/test_smart_fhir.py
Unit and integration tests for SMART on FHIR OAuth2 discovery, PKCE (RFC 7636),
client launch flows, and synthetic EHR token exchange endpoints.
Zero external test client dependencies required.
"""

import base64
import hashlib
import pytest
from synapse.api import create_app
from synapse.smart_fhir import (
    generate_pkce_verifier,
    generate_pkce_challenge,
    generate_pkce_pair,
    get_synthetic_smart_configuration,
    build_smart_authorization_url,
    MockSMARTEHRServer,
    SMARTClient,
)
from synapse.storage import WalletStorage


@pytest.fixture
def app_instance(tmp_path):
    db_path = str(tmp_path / "test_smart_wallet.db")
    storage = WalletStorage(db_path)
    return create_app(storage_instance=storage)


def test_pkce_generation_and_rfc7636_compliance():
    """Verify PKCE code_verifier and code_challenge comply with RFC 7636."""
    verifier, challenge = generate_pkce_pair(length=64)

    # Verifier length check
    assert len(verifier) == 64
    assert all(c.isalnum() or c in "-._~" for c in verifier)

    # Recompute S256 challenge manually and verify match
    raw_hash = hashlib.sha256(verifier.encode("ascii")).digest()
    expected_challenge = base64.urlsafe_b64encode(raw_hash).decode("utf-8").rstrip("=")
    assert challenge == expected_challenge

    # Check bounds enforcement
    with pytest.raises(ValueError):
        generate_pkce_verifier(length=30)
    with pytest.raises(ValueError):
        generate_pkce_verifier(length=150)


def test_smart_discovery_configuration_metadata():
    """Verify synthetic SMART configuration contains all required discovery keys."""
    config = get_synthetic_smart_configuration("https://ehr.synthetic.lifecare.local")

    assert config["issuer"] == "https://ehr.synthetic.lifecare.local"
    assert "authorization_endpoint" in config
    assert "token_endpoint" in config
    assert "capabilities" in config
    assert "launch-standalone" in config["capabilities"]
    assert "launch-ehr" in config["capabilities"]
    assert "S256" in config["code_challenge_methods_supported"]
    assert "patient/*.read" in config["scopes_supported"]


def test_build_smart_authorization_url():
    """Verify URL builder creates valid authorization URLs for both standalone and EHR launch."""
    # 1. Standalone launch
    url_standalone = build_smart_authorization_url(
        authorization_endpoint="https://ehr.local/oauth/authorize",
        client_id="test-client",
        redirect_uri="http://localhost:8000/callback",
        scope="patient/*.read launch/patient",
        state="xyz123",
        code_challenge="test_challenge_hash",
        aud="http://localhost:8000/api/v1/interop/fhir",
    )
    assert "https://ehr.local/oauth/authorize?" in url_standalone
    assert "client_id=test-client" in url_standalone
    assert "response_type=code" in url_standalone
    assert "code_challenge=test_challenge_hash" in url_standalone
    assert "code_challenge_method=S256" in url_standalone
    assert "aud=http%3A%2F%2Flocalhost%3A8000%2Fapi%2Fv1%2Finterop%2Ffhir" in url_standalone

    # 2. EHR launch
    url_ehr = build_smart_authorization_url(
        authorization_endpoint="https://ehr.local/oauth/authorize",
        client_id="test-client",
        redirect_uri="http://localhost:8000/callback",
        scope="patient/*.read launch",
        state="xyz456",
        code_challenge="test_challenge_hash",
        launch="ehr_ctx_999",
    )
    assert "launch=ehr_ctx_999" in url_ehr


def test_mock_ehr_server_pkce_verification_and_token_exchange():
    """Verify that MockSMARTEHRServer enforces PKCE verification and prevents replay."""
    server = MockSMARTEHRServer()
    verifier, challenge = generate_pkce_pair(length=64)

    # Create code
    code = server.create_authorization_code(
        client_id="synapse-client",
        redirect_uri="http://localhost:8000/callback",
        scope="patient/*.read launch/patient",
        state="test-state",
        code_challenge=challenge,
        patient_id="SYN-1001",
    )

    # 1. Attempt exchange with WRONG verifier -> Must fail
    with pytest.raises(ValueError, match="PKCE verification failed"):
        server.exchange_code_for_token(code, code_verifier="wrong_verifier_string_that_does_not_match", client_id="synapse-client")

    # 2. Attempt exchange with WRONG client_id -> Must fail
    with pytest.raises(ValueError, match="Client ID mismatch"):
        server.exchange_code_for_token(code, code_verifier=verifier, client_id="wrong-client")

    # 3. Correct exchange -> Must succeed
    tokens = server.exchange_code_for_token(code, code_verifier=verifier, client_id="synapse-client")
    assert "access_token" in tokens
    assert tokens["token_type"] == "bearer"
    assert tokens["patient"] == "SYN-1001"
    assert tokens["expires_in"] == 3600

    # 4. Attempt replaying the used authorization code -> Must fail
    with pytest.raises(ValueError, match="already been redeemed"):
        server.exchange_code_for_token(code, code_verifier=verifier, client_id="synapse-client")

    # 5. Token introspection
    intro = server.introspect_token(tokens["access_token"])
    assert intro["active"] is True
    assert intro["patient"] == "SYN-1001"


def test_smart_client_gateway_flow():
    """Verify SMARTClient manages state and completes the end-to-end launch workflow."""
    server = MockSMARTEHRServer()
    client = SMARTClient(client_id="test-smart-agent")

    # Initiate launch
    launch_data = client.initiate_standalone_launch(
        authorization_endpoint="https://ehr.local/oauth/authorize",
        fhir_base_url="http://localhost:8000/api/v1/interop/fhir",
    )
    state = launch_data["state"]
    challenge = launch_data["code_challenge"]

    # Simulated EHR approves and gives code
    code = server.create_authorization_code(
        client_id="test-smart-agent",
        redirect_uri=client.redirect_uri,
        scope=launch_data["scope"],
        state=state,
        code_challenge=challenge,
        patient_id="SYN-1001",
    )

    # Client redeems code using saved state & verifier
    token_response = client.complete_token_exchange(code=code, state=state, mock_ehr_server=server)
    assert token_response["patient"] == "SYN-1001"
    assert "access_token" in token_response

    # Verify authorization header helper
    headers = SMARTClient.get_fhir_auth_headers(token_response["access_token"])
    assert headers["Authorization"] == f"Bearer {token_response['access_token']}"
    assert headers["Accept"] == "application/fhir+json"


def test_api_mllp_status_endpoint(app_instance):
    """Verify GET /api/v1/interop/mllp/status returns valid MLLP gateway metadata."""
    route = next(r for r in app_instance.routes if r.path == "/api/v1/interop/mllp/status" and "GET" in r.methods)
    data = route.endpoint()
    assert data["port"] == 2575
    assert data["is_synthetic"] is True
    assert "stats" in data


def test_api_smart_configuration_endpoint(app_instance):
    """Verify GET /api/v1/interop/smart/configuration returns SMART discovery metadata."""
    route = next(r for r in app_instance.routes if r.path == "/api/v1/interop/smart/configuration" and "GET" in r.methods)
    data = route.endpoint()
    assert "authorization_endpoint" in data
    assert "token_endpoint" in data
    assert "capabilities" in data


def test_api_smart_launch_and_token_exchange(app_instance):
    """Verify POST /api/v1/interop/smart/launch and token exchange roundtrip."""
    route_launch = next(r for r in app_instance.routes if r.path == "/api/v1/interop/smart/launch" and "POST" in r.methods)
    route_token = next(r for r in app_instance.routes if r.path == "/api/v1/interop/smart/token" and "POST" in r.methods)

    # 1. Initiate Launch
    launch_request_model = route_launch.endpoint.__annotations__["payload"]
    launch_req = launch_request_model(flow="standalone", aud="http://localhost:8000/api/v1/interop/fhir")
    launch_data = route_launch.endpoint(launch_req)

    assert "authorization_url" in launch_data
    assert "state" in launch_data
    assert "code_verifier" in launch_data
    assert "simulated_authorization_code" in launch_data

    # 2. Redeem simulated authorization code
    token_request_model = route_token.endpoint.__annotations__["payload"]
    token_req = token_request_model(
        code=launch_data["simulated_authorization_code"],
        state=launch_data["state"],
        client_id="synapse-ai-smart-client",
    )
    token_data = route_token.endpoint(token_req)
    assert "access_token" in token_data
    assert token_data["patient"] == "SYN-1001"
    assert token_data["token_type"] == "bearer"
