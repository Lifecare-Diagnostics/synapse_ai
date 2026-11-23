"""
tests/test_security_gateway.py
Unit and integration tests for security foundations:
1. Secret key configuration validation and production hardening.
2. CORS allowed origins configuration.
3. Global sanitized exception handling preventing internal stack trace leaks.
Zero external test client dependencies required.
"""

import json
import os
from unittest.mock import patch
from starlette.middleware.cors import CORSMiddleware
import pytest
from synapse.api import create_app
from synapse.auth import (
    INSECURE_DEV_SECRET,
    validate_secret_key_configuration,
)
from synapse.storage import WalletStorage


def test_secret_key_validation_in_production():
    """Verify validate_secret_key_configuration enforces security in production."""
    # 1. In production with default insecure key -> must raise RuntimeError
    with patch("synapse.auth.ENVIRONMENT", "production"):
        with patch("synapse.auth.SECRET_KEY", INSECURE_DEV_SECRET):
            with pytest.raises(RuntimeError, match="Default insecure development key is prohibited"):
                validate_secret_key_configuration()

    # 2. In production with short secret key (< 32 bytes) -> must raise RuntimeError
    with patch("synapse.auth.ENVIRONMENT", "production"):
        with patch("synapse.auth.SECRET_KEY", "short-secret-key-too-small"):
            with pytest.raises(RuntimeError, match="must be at least 32 characters long"):
                validate_secret_key_configuration()

    # 3. In production with cryptographically secure key (>= 32 bytes) -> succeeds
    with patch("synapse.auth.ENVIRONMENT", "production"):
        with patch("synapse.auth.SECRET_KEY", "a-very-long-cryptographically-secure-production-secret-key-123456"):
            # Does not raise
            validate_secret_key_configuration()


def test_secret_key_warning_in_development():
    """Verify validate_secret_key_configuration issues UserWarning in development with default key."""
    with patch("synapse.auth.ENVIRONMENT", "development"):
        with patch("synapse.auth.SECRET_KEY", INSECURE_DEV_SECRET):
            with pytest.warns(UserWarning, match="default development key"):
                validate_secret_key_configuration()


def test_cors_origin_whitelist_configuration(tmp_path):
    """Verify that CORS middleware respects SYNAPSE_ALLOWED_ORIGINS configuration."""
    db_path = str(tmp_path / "test_cors.db")
    storage = WalletStorage(db_path)

    # 1. Configured custom origins
    with patch.dict(os.environ, {
        "SYNAPSE_ALLOWED_ORIGINS": "https://portal.lifecare.org, https://ehr.hospital.com",
        "SYNAPSE_ALLOW_ALL_ORIGINS": "false",
        "SYNAPSE_ENV": "production",
    }):
        app1 = create_app(storage_instance=storage)
        cors1 = next(m for m in app1.user_middleware if m.cls == CORSMiddleware)
        assert cors1.kwargs["allow_origins"] == [
            "https://portal.lifecare.org",
            "https://ehr.hospital.com",
        ]

    # 2. Wildcard mode
    with patch.dict(os.environ, {
        "SYNAPSE_ALLOW_ALL_ORIGINS": "true",
        "SYNAPSE_ENV": "production",
    }):
        app2 = create_app(storage_instance=storage)
        cors2 = next(m for m in app2.user_middleware if m.cls == CORSMiddleware)
        assert cors2.kwargs["allow_origins"] == ["*"]


@pytest.mark.anyio
async def test_global_sanitized_exception_handler(tmp_path):
    """Verify unhandled 500 exceptions return sanitized JSON with tracking_id without leaking tracebacks."""
    db_path = str(tmp_path / "test_error_sanitization.db")
    storage = WalletStorage(db_path)
    app = create_app(storage_instance=storage)

    handler = app.exception_handlers.get(Exception)
    assert handler is not None

    # Simulate an unexpected algorithmic failure with sensitive internal strings
    simulated_error = ZeroDivisionError("Simulated internal algorithmic failure leaking /var/secret/path")
    res = await handler(request=None, exc=simulated_error)

    assert res.status_code == 500
    body = json.loads(res.body.decode("utf-8"))
    assert body["error_code"] == "INTERNAL_SERVER_ERROR"
    assert "tracking_id" in body
    assert body["tracking_id"].startswith("err_")
    assert "Internal server error occurred" in body["detail"]

    # Ensure sensitive internal strings and stack traces are NOT exposed
    assert "ZeroDivisionError" not in body["detail"]
    assert "Simulated internal algorithmic failure" not in body["detail"]
    assert "/var/secret/path" not in body["detail"]
