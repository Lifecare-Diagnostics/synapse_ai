"""
Tests for Gemini API provider (synapse/llm.py GeminiClient)
and usage tracking (synapse/usage_tracker.py).
All tests use mocks — no live API calls are made.
"""

import json
import os
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from synapse.llm import (
    GeminiClient,
    MockLLMClient,
    get_default_llm_client,
    extract_json_from_llm_response,
    LLMClient,
)
from synapse.extractor import HybridExtractor, LLMExtractor, RuleBasedExtractor
from synapse.usage_tracker import (
    UsageTracker,
    estimate_cost_usd,
    PRICING,
    USD_TO_INR,
)


# ---------------------------------------------------------------------------
# GeminiClient — Configuration & Initialization
# ---------------------------------------------------------------------------

class TestGeminiClientConfig:
    """Tests for GeminiClient configuration and initialization."""

    def test_requires_api_key(self):
        """GeminiClient raises ValueError if no API key is provided."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove any existing key env vars
            env = {k: v for k, v in os.environ.items()
                   if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY")}
            with patch.dict(os.environ, env, clear=True):
                with pytest.raises(ValueError, match="API key is required"):
                    GeminiClient()

    def test_accepts_explicit_api_key(self):
        """GeminiClient accepts api_key parameter."""
        client = GeminiClient(api_key="test-key-12345")
        assert client._api_key == "test-key-12345"
        assert client.model == GeminiClient.DEFAULT_MODEL

    def test_reads_gemini_api_key_env(self):
        """GeminiClient reads GEMINI_API_KEY from environment."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "env-key-abc"}):
            client = GeminiClient()
            assert client._api_key == "env-key-abc"

    def test_reads_google_api_key_env(self):
        """GeminiClient falls back to GOOGLE_API_KEY if GEMINI_API_KEY not set."""
        env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
        env["GOOGLE_API_KEY"] = "google-key-xyz"
        with patch.dict(os.environ, env, clear=True):
            client = GeminiClient()
            assert client._api_key == "google-key-xyz"

    def test_custom_model(self):
        """GeminiClient accepts custom model parameter."""
        client = GeminiClient(api_key="k", model="gemini-4-hydrogen")
        assert client.model == "gemini-4-hydrogen"

    def test_model_from_env(self):
        """GeminiClient reads model from SYNAPSE_GEMINI_MODEL env var."""
        with patch.dict(os.environ, {
            "GEMINI_API_KEY": "k",
            "SYNAPSE_GEMINI_MODEL": "gemini-3.1-flash-lite",
        }):
            client = GeminiClient()
            assert client.model == "gemini-3.1-flash-lite"

    def test_default_model_is_current(self):
        """Default model should be a current, non-deprecated model."""
        assert "2.5" not in GeminiClient.DEFAULT_MODEL
        assert "2.0" not in GeminiClient.DEFAULT_MODEL
        assert "1.5" not in GeminiClient.DEFAULT_MODEL

    def test_timeout_parameter(self):
        """GeminiClient accepts timeout parameter."""
        client = GeminiClient(api_key="k", timeout=120)
        assert client.timeout == 120

    def test_store_defaults_false(self):
        """GeminiClient defaults store to False for privacy."""
        client = GeminiClient(api_key="k")
        assert client.store is False


# ---------------------------------------------------------------------------
# GeminiClient — Generate (Mocked SDK)
# ---------------------------------------------------------------------------

class TestGeminiClientGenerate:
    """Tests for GeminiClient.generate() with mocked google-genai SDK."""

    def _make_mock_interaction(self, text: str, input_tokens=100, output_tokens=50):
        """Create a mock Interaction response object."""
        mock_usage = MagicMock()
        mock_usage.total_input_tokens = input_tokens
        mock_usage.total_output_tokens = output_tokens
        mock_usage.total_tokens = input_tokens + output_tokens

        mock_interaction = MagicMock()
        mock_interaction.output_text = text
        mock_interaction.usage = mock_usage
        return mock_interaction

    def test_successful_generation(self):
        """Successful Gemini generation returns text and records usage."""
        client = GeminiClient(api_key="test-key")
        mock_interaction = self._make_mock_interaction(
            '{"patient_name": "Test Patient"}', input_tokens=200, output_tokens=80
        )
        mock_genai_client = MagicMock()
        mock_genai_client.interactions.create.return_value = mock_interaction
        client._client = mock_genai_client

        result = client.generate("Extract data from report", system_prompt="You are a clinical AI.")
        assert '"patient_name"' in result
        assert client.last_usage is not None
        assert client.last_usage["total_input_tokens"] == 200
        assert client.last_usage["total_output_tokens"] == 80
        assert client.last_usage["status"] == "success"
        assert client.last_usage["provider"] == "gemini"

    def test_system_instruction_passed(self):
        """System prompt is passed as system_instruction kwarg."""
        client = GeminiClient(api_key="test-key")
        mock_interaction = self._make_mock_interaction("response text")
        mock_genai_client = MagicMock()
        mock_genai_client.interactions.create.return_value = mock_interaction
        client._client = mock_genai_client

        client.generate("test prompt", system_prompt="system instructions")
        call_kwargs = mock_genai_client.interactions.create.call_args.kwargs
        assert call_kwargs["system_instruction"] == "system instructions"
        assert call_kwargs["store"] is False

    def test_empty_response_raises(self):
        """Empty/None response text raises ValueError."""
        client = GeminiClient(api_key="test-key")
        mock_interaction = self._make_mock_interaction(None)
        mock_interaction.output_text = None
        mock_genai_client = MagicMock()
        mock_genai_client.interactions.create.return_value = mock_interaction
        client._client = mock_genai_client

        with pytest.raises(ValueError, match="empty response"):
            client.generate("test")

    def test_rate_limit_error(self):
        """Rate limit error from API is wrapped with descriptive message."""
        client = GeminiClient(api_key="test-key")
        mock_genai_client = MagicMock()
        mock_genai_client.interactions.create.side_effect = Exception("Rate limit exceeded for model")
        client._client = mock_genai_client

        with pytest.raises(RuntimeError, match="rate limit"):
            client.generate("test")
        assert client.last_usage["status"].startswith("error:")

    def test_timeout_error(self):
        """Timeout error from API is wrapped with descriptive message."""
        client = GeminiClient(api_key="test-key")
        mock_genai_client = MagicMock()
        mock_genai_client.interactions.create.side_effect = Exception("Request timed out")
        client._client = mock_genai_client

        with pytest.raises(RuntimeError, match="timed out"):
            client.generate("test")

    def test_network_error(self):
        """Network error is wrapped as RuntimeError."""
        client = GeminiClient(api_key="test-key")
        mock_genai_client = MagicMock()
        mock_genai_client.interactions.create.side_effect = ConnectionError("DNS resolution failed")
        client._client = mock_genai_client

        with pytest.raises(RuntimeError, match="Gemini API error"):
            client.generate("test")

    def test_invalid_json_response_handled(self):
        """LLM returning non-JSON text should be handled by extract_json_from_llm_response."""
        # This tests the pipeline, not GeminiClient directly
        with pytest.raises(ValueError, match="Failed to decode JSON"):
            extract_json_from_llm_response("This is not JSON at all, just text.")

    def test_clinical_extraction_pipeline(self):
        """Full extract_clinical_json pipeline through mocked Gemini."""
        client = GeminiClient(api_key="test-key")
        mock_response = json.dumps({
            "document_type": "lab report",
            "patient_name": "Test Patient",
            "patient_id": "SYN-9999",
            "document_date": "2024-06-15",
            "lab_results": [{"test_name": "Glucose", "result_value": 95}],
        })
        mock_interaction = self._make_mock_interaction(mock_response)
        mock_genai_client = MagicMock()
        mock_genai_client.interactions.create.return_value = mock_interaction
        client._client = mock_genai_client

        result = client.extract_clinical_json("Patient Name: Test Patient\nGlucose: 95 mg/dL")
        assert result["patient_name"] == "Test Patient"
        assert result["lab_results"][0]["test_name"] == "Glucose"


# ---------------------------------------------------------------------------
# Factory function — provider selection
# ---------------------------------------------------------------------------

class TestFactoryFunction:
    """Tests for get_default_llm_client() with Gemini provider."""

    def test_gemini_provider_selection(self):
        """SYNAPSE_LLM_PROVIDER=gemini creates GeminiClient."""
        with patch.dict(os.environ, {
            "SYNAPSE_LLM_PROVIDER": "gemini",
            "GEMINI_API_KEY": "test-key",
        }):
            client = get_default_llm_client()
            assert isinstance(client, GeminiClient)

    def test_mock_still_default(self):
        """Default provider is still MockLLMClient."""
        with patch.dict(os.environ, {"SYNAPSE_LLM_PROVIDER": "mock"}):
            client = get_default_llm_client()
            assert isinstance(client, MockLLMClient)

    def test_gemini_missing_key_raises(self):
        """Selecting gemini without API key raises ValueError."""
        env = {k: v for k, v in os.environ.items()
               if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY")}
        env["SYNAPSE_LLM_PROVIDER"] = "gemini"
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="API key is required"):
                get_default_llm_client()


# ---------------------------------------------------------------------------
# HybridExtractor fallback with Gemini
# ---------------------------------------------------------------------------

class TestHybridExtractorGeminiFallback:
    """Tests that HybridExtractor gracefully falls back when Gemini fails."""

    def test_fallback_on_gemini_error(self):
        """If Gemini LLM fails, HybridExtractor returns rule-based result."""
        class FailingGeminiClient(LLMClient):
            def generate(self, prompt, system_prompt=None):
                raise RuntimeError("Simulated Gemini network failure")

        hybrid = HybridExtractor(
            llm_extractor=LLMExtractor(client=FailingGeminiClient())
        )
        # Use a narrative text that would route to LLM
        text = "Patient Name: Fallback Test\nDate: 2024-06-15\nFindings: Normal study."
        doc = hybrid.extract(text, "fallback_test.txt")
        # Should fall back to rule-based, not raise
        assert doc.extraction_method == "rule_based"


# ---------------------------------------------------------------------------
# API key security
# ---------------------------------------------------------------------------

class TestApiKeySecurity:
    """Verify API keys are never exposed."""

    def test_api_key_not_in_repr(self):
        """API key should not appear in string representation."""
        client = GeminiClient(api_key="super-secret-key-12345")
        repr_str = repr(client)
        assert "super-secret-key-12345" not in repr_str

    def test_api_key_not_in_usage_dict(self):
        """Usage tracking dict must never contain API key."""
        client = GeminiClient(api_key="secret-key-xyz")
        # Simulate a failed call to populate last_usage
        mock_genai_client = MagicMock()
        mock_genai_client.interactions.create.side_effect = Exception("test error")
        client._client = mock_genai_client
        try:
            client.generate("test")
        except RuntimeError:
            pass
        assert client.last_usage is not None
        usage_str = json.dumps(client.last_usage)
        assert "secret-key-xyz" not in usage_str


# ---------------------------------------------------------------------------
# Usage Tracker
# ---------------------------------------------------------------------------

class TestUsageTracker:
    """Tests for the UsageTracker cost tracking system."""

    def test_record_and_summary(self):
        """Record usage events and retrieve summary."""
        tracker = UsageTracker(":memory:")
        tracker.record("gemini", "gemini-3.5-flash-lite", 1000, 200, 1200, "DOC-001")
        tracker.record("gemini", "gemini-3.5-flash-lite", 2000, 400, 2400, "DOC-002")

        summary = tracker.get_summary()
        assert summary["total_calls"] == 2
        assert summary["total_input_tokens"] == 3000
        assert summary["total_output_tokens"] == 600
        assert summary["total_cost_usd"] > 0
        assert summary["total_cost_inr"] == round(summary["total_cost_usd"] * USD_TO_INR, 2)
        assert len(summary["breakdown_by_provider"]) == 1
        assert len(summary["recent_calls"]) == 2

    def test_error_calls_counted_separately(self):
        """Error calls are counted but excluded from cost totals."""
        tracker = UsageTracker(":memory:")
        tracker.record("gemini", "gemini-3.5-flash-lite", 1000, 200, 1200, status="success")
        tracker.record("gemini", "gemini-3.5-flash-lite", status="error: timeout")

        summary = tracker.get_summary()
        assert summary["total_calls"] == 1  # Only successful calls
        assert summary["error_count"] == 1

    def test_monthly_cost_estimate(self):
        """Monthly cost estimate calculates correctly."""
        tracker = UsageTracker(":memory:")
        est = tracker.get_monthly_cost_estimate(1000)
        assert est["documents_per_month"] == 1000
        assert est["estimated_monthly_cost_usd"] > 0
        assert est["estimated_monthly_cost_inr"] > 0
        assert est["model"] == "gemini-3.5-flash-lite"

    def test_monthly_cost_estimate_custom_model(self):
        """Monthly cost estimate supports custom model."""
        tracker = UsageTracker(":memory:")
        est = tracker.get_monthly_cost_estimate(5000, model="gemini-4-hydrogen")
        assert est["model"] == "gemini-4-hydrogen"
        assert est["documents_per_month"] == 5000

    def test_estimate_cost_usd(self):
        """Cost estimation helper calculates correct values."""
        # 1M input tokens at $0.10 + 1M output tokens at $0.40 = $0.50
        cost = estimate_cost_usd("gemini-3.5-flash-lite", 1_000_000, 1_000_000)
        assert abs(cost - 0.50) < 0.001

    def test_empty_summary(self):
        """Empty tracker returns zeroed summary."""
        tracker = UsageTracker(":memory:")
        summary = tracker.get_summary()
        assert summary["total_calls"] == 0
        assert summary["total_cost_usd"] == 0.0

    def test_multiple_volume_tiers(self):
        """Cost estimates scale linearly with volume."""
        tracker = UsageTracker(":memory:")
        est_1k = tracker.get_monthly_cost_estimate(1000)
        est_10k = tracker.get_monthly_cost_estimate(10000)
        # 10x volume should produce ~10x cost
        ratio = est_10k["estimated_monthly_cost_usd"] / est_1k["estimated_monthly_cost_usd"]
        assert abs(ratio - 10.0) < 0.01


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

class TestLLMEndpoints:
    """Tests for LLM API endpoints in synapse/api.py."""

    @pytest.fixture
    def app_instance(self):
        from synapse.api import create_app
        from synapse.storage import WalletStorage
        storage = WalletStorage(":memory:")
        return create_app(storage)

    def test_llm_status_mock(self, app_instance):
        """Status endpoint returns mock configuration when provider is mock."""
        route = next(r for r in app_instance.routes if getattr(r, "path", None) == "/api/v1/llm/status")
        with patch.dict(os.environ, {"SYNAPSE_LLM_PROVIDER": "mock"}):
            res = route.endpoint()
            assert res["provider"] == "mock"
            assert res["status"] == "ready"
            assert res["offline_fallback_enabled"] is True

    def test_llm_status_gemini_without_key(self, app_instance):
        """Status endpoint shows needs_configuration when Gemini has no key."""
        route = next(r for r in app_instance.routes if getattr(r, "path", None) == "/api/v1/llm/status")
        env = {k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY")}
        env["SYNAPSE_LLM_PROVIDER"] = "gemini"
        with patch.dict(os.environ, env, clear=True):
            res = route.endpoint()
            assert res["provider"] == "gemini"
            assert res["status"] == "needs_configuration"
            assert res["api_key_configured"] is False

    def test_llm_status_gemini_with_key(self, app_instance):
        """Status endpoint shows ready when Gemini key is configured."""
        route = next(r for r in app_instance.routes if getattr(r, "path", None) == "/api/v1/llm/status")
        with patch.dict(os.environ, {
            "SYNAPSE_LLM_PROVIDER": "gemini",
            "GEMINI_API_KEY": "dummy-key-12345",
        }):
            res = route.endpoint()
            assert res["provider"] == "gemini"
            assert res["status"] == "ready"
            assert res["api_key_configured"] is True
            # Confirm dummy key is not in output
            assert "dummy-key-12345" not in json.dumps(res)

    def test_llm_usage_endpoint(self, app_instance):
        """Usage summary endpoint returns valid schema."""
        route = next(r for r in app_instance.routes if getattr(r, "path", None) == "/api/v1/llm/usage")
        res = route.endpoint()
        assert "total_calls" in res
        assert "total_cost_usd" in res
        assert "total_cost_inr" in res
        assert "breakdown_by_provider" in res

    def test_llm_cost_estimate_endpoint(self, app_instance):
        """Cost estimate endpoint calculates for requested document volume."""
        route = next(r for r in app_instance.routes if getattr(r, "path", None) == "/api/v1/llm/cost-estimate")
        res = route.endpoint(documents_per_month=5000, model="gemini-3.5-flash-lite", avg_input_tokens=5000, avg_output_tokens=1000)
        assert res["documents_per_month"] == 5000
        assert res["estimated_monthly_cost_usd"] > 0
        assert res["estimated_monthly_cost_inr"] > 0
        assert "pricing_note" in res

