"""
synapse_poc/synapse/auth.py
Authentication, Session Management, and Role-Based Access Control (RBAC) Engine.
Uses Python standard library cryptographic primitives (PBKDF2-HMAC-SHA256 and RFC 7519 HMAC-SHA256 JWT)
with zero external binary dependencies.
"""

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict, List, Literal, Optional, Set

import warnings
from fastapi import HTTPException, Header, status
from pydantic import BaseModel, Field


INSECURE_DEV_SECRET = "synapse-insecure-dev-secret-key-replace-in-production-min32bytes!!"
SECRET_KEY = os.environ.get("SYNAPSE_SECRET_KEY", INSECURE_DEV_SECRET)
ENVIRONMENT = os.environ.get("SYNAPSE_ENV", os.environ.get("ENVIRONMENT", "development")).lower()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_SECONDS = 3600  # 1 hour


def is_insecure_secret_key() -> bool:
    """Check if the currently active secret key matches the default development key."""
    return SECRET_KEY == INSECURE_DEV_SECRET


def validate_secret_key_configuration() -> None:
    """
    Validate secret key configuration against environment constraints.
    In staging/production environments, raises RuntimeError if insecure or short key is used.
    """
    is_prod = ENVIRONMENT in ("production", "prod", "staging")
    if is_prod:
        if is_insecure_secret_key():
            raise RuntimeError(
                "FATAL SECURITY CONFIGURATION ERROR: SYNAPSE_SECRET_KEY must be explicitly set "
                "in production/staging environments. Default insecure development key is prohibited."
            )
        if len(SECRET_KEY) < 32:
            raise RuntimeError(
                "FATAL SECURITY CONFIGURATION ERROR: SYNAPSE_SECRET_KEY must be at least 32 characters long."
            )
    elif is_insecure_secret_key() and ENVIRONMENT not in ("test", "testing"):
        warnings.warn(
            "SYNAPSE_SECRET_KEY is using the default development key. "
            "Set SYNAPSE_SECRET_KEY to a secure random string before deploying to production.",
            UserWarning,
            stacklevel=2,
        )


# Validate secret key configuration at startup
validate_secret_key_configuration()

RoleType = Literal["Technician", "Auditor", "Pathologist", "Administrator"]

# ---------------------------------------------------------------------------
# Role-Based Permission Matrix (Phase 7A)
# ---------------------------------------------------------------------------

ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "Technician": {
        "patient:read",
        "report:upload",
        "review:view",
        "parameter:propose",
    },
    "Auditor": {
        "patient:read",
        "report:upload",
        "review:view",
        "parameter:correct",
        "audit:view",
    },
    "Pathologist": {
        "patient:read",
        "report:upload",
        "review:view",
        "parameter:correct",
        "report:signoff",
        "audit:view",
        "interop:export",
    },
    "Administrator": {
        "patient:read",
        "report:upload",
        "review:view",
        "audit:view",
        "interop:export",
        "user:manage",
        "system:configure",
    },
}


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class User(BaseModel):
    user_id: str
    username: str
    full_name: str
    role: str
    is_active: bool = True


class UserInDB(User):
    password_hash: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: User
    permissions: List[str]


# ---------------------------------------------------------------------------
# Password Hashing & Verification (PBKDF2-HMAC-SHA256)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with 100,000 iterations and 16-byte salt."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"pbkdf2_sha256$100000${salt}${key.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against PBKDF2 formatted hash in constant time."""
    try:
        parts = hashed_password.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = parts[2]
        expected_key = parts[3]
        computed_key = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        ).hex()
        return hmac.compare_digest(computed_key, expected_key)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT Token Generation & Verification (RFC 7519 Compliant)
# ---------------------------------------------------------------------------

def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = 4 - (len(data) % 4)
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def create_access_token(
    user: User,
    expires_delta_seconds: Optional[int] = None,
) -> str:
    """Generate signed JWT token containing user identity and role claims."""
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    exp = now + (expires_delta_seconds if expires_delta_seconds is not None else ACCESS_TOKEN_EXPIRE_SECONDS)

    payload = {
        "sub": user.username,
        "uid": user.user_id,
        "name": user.full_name,
        "role": user.role,
        "iat": now,
        "exp": exp,
    }

    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signing_input = f"{_b64encode(header_bytes)}.{_b64encode(payload_bytes)}"

    signature = hmac.new(
        SECRET_KEY.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    return f"{signing_input}.{_b64encode(signature)}"


def decode_access_token(token: str) -> Dict[str, Any]:
    """Validate JWT signature, expiration, and payload structure."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT token format.")

    signing_input = f"{parts[0]}.{parts[1]}"
    expected_sig = hmac.new(
        SECRET_KEY.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    try:
        actual_sig = _b64decode(parts[2])
    except Exception:
        raise ValueError("Malformed token signature encoding.")

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("Invalid JWT token signature.")

    try:
        payload_bytes = _b64decode(parts[1])
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        raise ValueError("Malformed token payload.")

    now = int(time.time())
    if payload.get("exp", 0) < now:
        raise ValueError("Access token has expired.")

    return payload


# ---------------------------------------------------------------------------
# RBAC Authorization Guards
# ---------------------------------------------------------------------------

def has_permission(role: str, permission: str) -> bool:
    """Check if given role possesses specified permission."""
    perms = ROLE_PERMISSIONS.get(role, set())
    return permission in perms


def check_permission(user: User, required_permission: str) -> None:
    """Raise HTTP 403 Forbidden if user lacks required permission."""
    if not has_permission(user.role, required_permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: User '{user.username}' with role '{user.role}' lacks required permission '{required_permission}'.",
        )


def check_role(user: User, allowed_roles: List[str], action_name: str = "this action") -> None:
    """Raise HTTP 403 Forbidden if user role is not in allowed_roles."""
    if user.role not in allowed_roles:
        roles_str = ", ".join(allowed_roles)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: User '{user.username}' with role '{user.role}' is not authorized for {action_name}. Required role: {roles_str}.",
        )
