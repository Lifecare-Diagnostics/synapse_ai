"""
synapse_poc/synapse/smart_fhir.py
SMART-on-FHIR OAuth2 Client and External Gateway Architecture.
Implements the HL7 SMART App Launch Framework (v2.0.0 & v1.0.0 compliant)
featuring OAuth2 Discovery (.well-known/smart-configuration), Proof Key for
Code Exchange (PKCE - RFC 7636), EHR/Standalone Launch flows, and a synthetic
Mock EHR OAuth2 Server harness for offline testing without external dependencies.
"""

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse

from pydantic import BaseModel, Field

# Standard SMART on FHIR scopes
DEFAULT_SMART_SCOPES = [
    "launch/patient",
    "patient/*.read",
    "patient/Observation.read",
    "patient/DiagnosticReport.read",
    "patient/Patient.read",
    "openid",
    "fhirUser",
    "offline_access",
]


# ---------------------------------------------------------------------------
# PKCE Utilities (RFC 7636)
# ---------------------------------------------------------------------------

def _b64url_encode(data: bytes) -> str:
    """Base64URL encode without trailing padding '=' characters."""
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def generate_pkce_verifier(length: int = 64) -> str:
    """
    Generate a cryptographically random code_verifier between 43 and 128 characters (RFC 7636 Section 4.1).
    Uses unreserved URI characters [A-Z, a-z, 0-9, -, ., _, ~].
    """
    if length < 43 or length > 128:
        raise ValueError("PKCE code_verifier length must be between 43 and 128 characters.")
    # token_urlsafe uses characters A-Z, a-z, 0-9, -, _
    return secrets.token_urlsafe(length)[:length]


def generate_pkce_challenge(verifier: str) -> str:
    """
    Compute S256 code_challenge: BASE64URL(SHA256(ASCII(code_verifier))) without padding.
    """
    sha256_hash = hashlib.sha256(verifier.encode("ascii")).digest()
    return _b64url_encode(sha256_hash)


def generate_pkce_pair(length: int = 64) -> Tuple[str, str]:
    """Generate a (code_verifier, code_challenge) pair using method S256."""
    verifier = generate_pkce_verifier(length=length)
    challenge = generate_pkce_challenge(verifier)
    return verifier, challenge


# ---------------------------------------------------------------------------
# SMART Discovery (.well-known/smart-configuration)
# ---------------------------------------------------------------------------

def get_synthetic_smart_configuration(
    issuer_url: str = "https://ehr.synthetic.lifecare.local",
) -> Dict[str, Any]:
    """
    Return standard SMART on FHIR Discovery metadata.
    Complies with SMART on FHIR v2.0.0 specifications.
    """
    return {
        "issuer": issuer_url,
        "jwks_uri": f"{issuer_url}/oauth/jwks.json",
        "authorization_endpoint": f"{issuer_url}/oauth/authorize",
        "token_endpoint": f"{issuer_url}/oauth/token",
        "introspection_endpoint": f"{issuer_url}/oauth/introspect",
        "revocation_endpoint": f"{issuer_url}/oauth/revoke",
        "userinfo_endpoint": f"{issuer_url}/oauth/userinfo",
        "management_endpoint": f"{issuer_url}/oauth/manage",
        "capabilities": [
            "launch-ehr",
            "launch-standalone",
            "client-public",
            "client-confidential-symmetric",
            "sso-openid-connect",
            "context-ehr-patient",
            "permission-patient",
            "permission-v2",
        ],
        "scopes_supported": DEFAULT_SMART_SCOPES,
        "response_types_supported": ["code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post", "none"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
    }


# ---------------------------------------------------------------------------
# Authorization URL Construction
# ---------------------------------------------------------------------------

def build_smart_authorization_url(
    authorization_endpoint: str,
    client_id: str,
    redirect_uri: str,
    scope: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
    aud: Optional[str] = None,
    launch: Optional[str] = None,
) -> str:
    """
    Construct the full SMART on FHIR OAuth2 authorization URL with PKCE parameters.
    Supports both Standalone Launch (with 'aud' parameter) and EHR Launch (with 'launch' context).
    """
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
    }
    if aud:
        params["aud"] = aud
    if launch:
        params["launch"] = launch

    return f"{authorization_endpoint}?{urllib.parse.urlencode(params)}"


# ---------------------------------------------------------------------------
# Synthetic Mock EHR OAuth2 Server (Harness for Offline Testing)
# ---------------------------------------------------------------------------

class MockSMARTEHRServer:
    """
    Simulated EHR OAuth2 Identity & Token Server.
    Enforces PKCE verification, handles simulated authorization grants,
    and returns SMART patient context without requiring live hospital network access.
    """

    def __init__(self, issuer_url: str = "https://ehr.synthetic.lifecare.local"):
        self.issuer_url = issuer_url
        self._auth_codes: Dict[str, Dict[str, Any]] = {}
        self._tokens: Dict[str, Dict[str, Any]] = {}

    def create_authorization_code(
        self,
        client_id: str,
        redirect_uri: str,
        scope: str,
        state: str,
        code_challenge: str,
        code_challenge_method: str = "S256",
        patient_id: str = "SYN-1001",
        launch: Optional[str] = None,
    ) -> str:
        """Issue a simulated one-time authorization code associated with the PKCE challenge."""
        code = f"smart_code_{secrets.token_hex(16)}"
        self._auth_codes[code] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "patient_id": patient_id,
            "launch": launch,
            "issued_at": time.time(),
            "used": False,
        }
        return code

    def exchange_code_for_token(
        self,
        code: str,
        code_verifier: str,
        client_id: str,
        redirect_uri: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Exchange authorization code and PKCE code_verifier for access token and patient context.
        Validates:
        1. Code existence and non-reuse.
        2. Client ID match.
        3. PKCE S256 challenge match: SHA256(verifier) == stored_challenge.
        """
        if code not in self._auth_codes:
            raise ValueError("Invalid authorization code.")
        record = self._auth_codes[code]
        if record["used"]:
            raise ValueError("Authorization code has already been redeemed.")
        if record["client_id"] != client_id:
            raise ValueError("Client ID mismatch during token exchange.")

        # Validate PKCE
        stored_challenge = record["code_challenge"]
        computed_challenge = generate_pkce_challenge(code_verifier)
        if not secrets.compare_digest(stored_challenge, computed_challenge):
            raise ValueError("PKCE verification failed: code_verifier does not match code_challenge.")

        # Mark code as used
        record["used"] = True

        access_token = f"smart_at_{secrets.token_hex(32)}"
        refresh_token = f"smart_rt_{secrets.token_hex(32)}"
        patient_id = record["patient_id"]

        token_payload = {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": 3600,
            "scope": record["scope"],
            "patient": patient_id,
            "refresh_token": refresh_token,
            "id_token": f"mock.id_token.{secrets.token_hex(16)}",
            "need_patient_banner": True,
            "smart_style_url": f"{self.issuer_url}/smart-style.json",
        }
        self._tokens[access_token] = token_payload
        return token_payload

    def introspect_token(self, token: str) -> Dict[str, Any]:
        """Introspect an issued access token."""
        if token in self._tokens:
            payload = self._tokens[token]
            return {
                "active": True,
                "scope": payload["scope"],
                "patient": payload["patient"],
                "client_id": "synapse-ai-client",
                "exp": int(time.time()) + 3600,
            }
        return {"active": False}


# ---------------------------------------------------------------------------
# SMART on FHIR Client Gateway
# ---------------------------------------------------------------------------

class SMARTClient:
    """
    Client gateway implementing SMART on FHIR Launch flows with PKCE protection.
    Manages active launch states, verifiers, and access tokens for FHIR API queries.
    """

    def __init__(
        self,
        client_id: str = "synapse-ai-smart-client",
        redirect_uri: str = "http://localhost:8000/api/v1/interop/smart/callback",
        is_synthetic: bool = True,
    ):
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.is_synthetic = is_synthetic
        self._pending_launches: Dict[str, Dict[str, Any]] = {}

    def initiate_standalone_launch(
        self,
        authorization_endpoint: str,
        fhir_base_url: str,
        scopes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Initiate a SMART Standalone Launch flow with PKCE S256.
        Returns authorization URL and state/verifier session data.
        """
        verifier, challenge = generate_pkce_pair(length=64)
        state = secrets.token_urlsafe(32)
        scope_str = " ".join(scopes or DEFAULT_SMART_SCOPES)

        auth_url = build_smart_authorization_url(
            authorization_endpoint=authorization_endpoint,
            client_id=self.client_id,
            redirect_uri=self.redirect_uri,
            scope=scope_str,
            state=state,
            code_challenge=challenge,
            code_challenge_method="S256",
            aud=fhir_base_url,
        )

        launch_record = {
            "flow": "standalone",
            "state": state,
            "verifier": verifier,
            "challenge": challenge,
            "aud": fhir_base_url,
            "scope": scope_str,
            "created_at": time.time(),
        }
        self._pending_launches[state] = launch_record

        return {
            "authorization_url": auth_url,
            "state": state,
            "code_verifier": verifier,
            "code_challenge": challenge,
            "scope": scope_str,
        }

    def initiate_ehr_launch(
        self,
        authorization_endpoint: str,
        launch_context_token: str,
        scopes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Initiate a SMART EHR Launch flow (where launch parameter is supplied by the EHR).
        """
        verifier, challenge = generate_pkce_pair(length=64)
        state = secrets.token_urlsafe(32)
        scope_str = " ".join(scopes or DEFAULT_SMART_SCOPES)

        auth_url = build_smart_authorization_url(
            authorization_endpoint=authorization_endpoint,
            client_id=self.client_id,
            redirect_uri=self.redirect_uri,
            scope=scope_str,
            state=state,
            code_challenge=challenge,
            code_challenge_method="S256",
            launch=launch_context_token,
        )

        launch_record = {
            "flow": "ehr",
            "state": state,
            "verifier": verifier,
            "challenge": challenge,
            "launch": launch_context_token,
            "scope": scope_str,
            "created_at": time.time(),
        }
        self._pending_launches[state] = launch_record

        return {
            "authorization_url": auth_url,
            "state": state,
            "code_verifier": verifier,
            "code_challenge": challenge,
            "scope": scope_str,
            "launch": launch_context_token,
        }

    def complete_token_exchange(
        self,
        code: str,
        state: str,
        mock_ehr_server: Optional[MockSMARTEHRServer] = None,
    ) -> Dict[str, Any]:
        """
        Complete launch flow: verify state, retrieve code_verifier, and exchange
        authorization code for access token via the mock EHR server.
        """
        if state not in self._pending_launches:
            raise ValueError("Unknown or expired launch state parameter.")

        launch_record = self._pending_launches.pop(state)
        verifier = launch_record["verifier"]

        server = mock_ehr_server or MockSMARTEHRServer()
        token_data = server.exchange_code_for_token(
            code=code,
            code_verifier=verifier,
            client_id=self.client_id,
            redirect_uri=self.redirect_uri,
        )
        return token_data

    @staticmethod
    def get_fhir_auth_headers(access_token: str) -> Dict[str, str]:
        """Build standard HTTP Authorization header for querying FHIR APIs."""
        return {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/fhir+json",
        }
