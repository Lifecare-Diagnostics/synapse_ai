"""
synapse_poc/synapse/llm.py
LLM Integration layer for Synapse AI.
Provides abstract interface, clinical extraction prompts, JSON parsers,
and clients for Mock (offline testing/fallback), Ollama (local), and Gemini API.
"""

from abc import ABC, abstractmethod
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)


CLINICAL_EXTRACTION_SYSTEM_PROMPT = """You are Synapse Clinical AI, a specialized clinical diagnostic information extraction assistant for Life Care Diagnostics.
Your goal is to extract structured clinical data from medical reports, doctor notes, radiology scans, prescriptions, and lab documents.

Rules:
1. Be strictly factual. Do NOT invent, assume, or hallucinate patient details, test values, or diagnoses.
2. If a field or date is not explicitly mentioned, return null.
3. Output MUST be a valid JSON object matching the requested schema with no commentary outside the JSON.
"""

CLINICAL_EXTRACTION_USER_PROMPT = """Extract the structured clinical information from the following diagnostic document into JSON format.

JSON Schema:
{{
  "document_type": "lab report" | "radiology" | "ultrasound" | "clinical note" | "prescription" | "mixed",
  "patient_id": string | null,
  "patient_name": string | null,
  "document_date": "YYYY-MM-DD" | null,
  "date_label": string | null,
  "clinical_summary": string | null,
  "key_sections": {{
    "Section Name": "Section text content..."
  }},
  "lab_results": [
    {{
      "test_name": string,
      "result_value": number | null,
      "unit": string | null,
      "reference_range_text": string | null,
      "reference_low": number | null,
      "reference_high": number | null
    }}
  ]
}}

Source Document Text:
\"\"\"
{document_text}
\"\"\"
"""


def extract_json_from_llm_response(response_text: str) -> Dict[str, Any]:
    """
    Extract and parse JSON object from LLM response text.
    Handles responses wrapped in ```json ... ``` markdown blocks or raw JSON.
    """
    text = response_text.strip()

    # Pattern 1: Fenced code block ```json ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()

    # Pattern 2: Search for outermost curly braces
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to decode JSON from LLM response: {e}\nRaw output: {response_text[:300]}")


class LLMClient(ABC):
    """Abstract interface for clinical LLM inference providers."""

    @abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generate text completion from prompt."""
        pass

    def extract_clinical_json(self, document_text: str) -> Dict[str, Any]:
        """Format extraction prompt, call LLM, and parse JSON response."""
        prompt = CLINICAL_EXTRACTION_USER_PROMPT.format(document_text=document_text)
        raw_response = self.generate(prompt, system_prompt=CLINICAL_EXTRACTION_SYSTEM_PROMPT)
        return extract_json_from_llm_response(raw_response)


class MockLLMClient(LLMClient):
    """
    In-memory mock LLM client for offline unit testing, evaluation,
    and graceful fallback when external inference servers are unconfigured.
    """

    def __init__(self, predefined_response: Optional[Dict[str, Any]] = None):
        self.predefined_response = predefined_response

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        if self.predefined_response is not None:
            return json.dumps(self.predefined_response)

        # Smart fallback parsing from prompt text for synthetic documents
        doc_text = prompt
        doc_type = "clinical note"
        if "Chest" in doc_text or "X-Ray" in doc_text:
            doc_type = "radiology"
        elif "Ultrasound" in doc_text or "Sonography" in doc_text:
            doc_type = "ultrasound"
        elif "Prescription" in doc_text or "Rx" in doc_text:
            doc_type = "prescription"
        elif "Haemoglobin" in doc_text or "CBC" in doc_text or "Lipid" in doc_text:
            doc_type = "lab report"

        # Extract name if present
        name_match = re.search(r"Patient(?:\s+Name)?\s*:\s*([^\n\r,]+)", doc_text, re.IGNORECASE)
        patient_name = name_match.group(1).strip() if name_match else None

        # Extract ID if present
        id_match = re.search(r"(?:Patient\s+ID|PID|ID)\s*:\s*([A-Za-z0-9_-]+)", doc_text, re.IGNORECASE)
        patient_id = id_match.group(1).strip() if id_match else None

        # Extract date
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", doc_text)
        document_date = date_match.group(1) if date_match else None

        # Extract key sections
        key_sections = {}
        for section in ["Findings", "IMPRESSION", "Chief complaints", "Examination", "Plan", "Prescription"]:
            m = re.search(rf"{section}\s*:\s*([^\n]+(?:\n[^\n:]+)*)", doc_text, re.IGNORECASE)
            if m:
                key_sections[section] = m.group(1).strip()

        mock_payload = {
            "document_type": doc_type,
            "patient_id": patient_id,
            "patient_name": patient_name,
            "document_date": document_date,
            "date_label": "Date",
            "clinical_summary": f"Diagnostic evaluation for {patient_name or 'patient'} ({doc_type}).",
            "key_sections": key_sections,
            "lab_results": [],
        }
        return json.dumps(mock_payload)


class LocalOllamaClient(LLMClient):
    """Client for local Ollama server (e.g. llama3.2, mistral, meditron)."""

    def __init__(
        self,
        model: str = "llama3.2",
        host: str = "http://localhost:11434",
        timeout: int = 60,
    ):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        url = f"{self.host}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt or "",
            "stream": False,
            "format": "json",
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("response", "")
        except Exception as e:
            raise RuntimeError(f"Ollama inference error at {url}: {e}")


class GeminiClient(LLMClient):
    """
    Google Gemini API client using the official google-genai SDK.
    Uses the Interactions API (client.interactions.create) for text generation.

    Configuration via environment variables:
    - GEMINI_API_KEY or GOOGLE_API_KEY: API key (required)
    - SYNAPSE_GEMINI_MODEL: model identifier (default: gemini-3.5-flash-lite)
    - SYNAPSE_GEMINI_TIMEOUT: request timeout in seconds (default: 60)
    - SYNAPSE_GEMINI_STORE: whether to store interactions (default: false)

    Token usage from each call is exposed via self.last_usage for cost tracking.
    """

    # Default model — gemini-2.5-flash-lite is deprecated, using current equivalent
    DEFAULT_MODEL = "gemini-3.5-flash-lite"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 60,
        store: bool = False,
    ):
        self.model = model or os.getenv("SYNAPSE_GEMINI_MODEL", self.DEFAULT_MODEL)
        self.timeout = timeout
        self.store = store
        self.last_usage: Optional[Dict[str, Any]] = None
        self._client = None

        # Resolve API key — NEVER log it
        resolved_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not resolved_key:
            raise ValueError(
                "Gemini API key is required. Set GEMINI_API_KEY or GOOGLE_API_KEY "
                "environment variable, or pass api_key parameter."
            )
        self._api_key = resolved_key

    def _get_client(self):
        """Lazily initialize the genai Client on first use."""
        if self._client is None:
            try:
                from google import genai
                self._client = genai.Client(api_key=self._api_key)
            except ImportError:
                raise RuntimeError(
                    "google-genai SDK is not installed. "
                    "Install it with: pip install google-genai"
                )
        return self._client

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Generate text via Gemini Interactions API.
        Records token usage in self.last_usage after each call.
        """
        client = self._get_client()
        start_time = time.time()

        try:
            kwargs: Dict[str, Any] = {
                "model": self.model,
                "input": prompt,
                "store": self.store,
            }
            if system_prompt:
                kwargs["system_instruction"] = system_prompt

            interaction = client.interactions.create(**kwargs)
            elapsed = time.time() - start_time

            # Record usage metadata for cost tracking
            usage = interaction.usage
            self.last_usage = {
                "provider": "gemini",
                "model": self.model,
                "total_input_tokens": getattr(usage, "total_input_tokens", None) if usage else None,
                "total_output_tokens": getattr(usage, "total_output_tokens", None) if usage else None,
                "total_tokens": getattr(usage, "total_tokens", None) if usage else None,
                "processing_time_seconds": round(elapsed, 3),
                "status": "success",
            }

            text = interaction.output_text
            if not text:
                raise ValueError("Gemini returned empty response text.")
            return text

        except ImportError:
            raise
        except ValueError:
            raise
        except Exception as e:
            elapsed = time.time() - start_time
            self.last_usage = {
                "provider": "gemini",
                "model": self.model,
                "total_input_tokens": None,
                "total_output_tokens": None,
                "total_tokens": None,
                "processing_time_seconds": round(elapsed, 3),
                "status": f"error: {type(e).__name__}",
            }
            error_msg = str(e).lower()
            if "api key" in error_msg or "api_key" in error_msg:
                raise RuntimeError("Gemini API key is invalid or unauthorized.")
            elif "rate" in error_msg and "limit" in error_msg:
                raise RuntimeError(f"Gemini rate limit exceeded: {e}")
            elif "timeout" in error_msg or "timed out" in error_msg:
                raise RuntimeError(f"Gemini request timed out after {self.timeout}s: {e}")
            else:
                raise RuntimeError(f"Gemini API error: {type(e).__name__}: {e}")


def get_default_llm_client() -> LLMClient:
    """
    Factory creating configured LLM client based on environment variables:
    - SYNAPSE_LLM_PROVIDER: "gemini" | "ollama" | "mock" (default: "mock")
    - For Gemini: GEMINI_API_KEY/GOOGLE_API_KEY, SYNAPSE_GEMINI_MODEL, SYNAPSE_GEMINI_TIMEOUT
    - For Ollama: SYNAPSE_OLLAMA_MODEL, SYNAPSE_OLLAMA_HOST, SYNAPSE_OLLAMA_TIMEOUT
    """
    provider = os.getenv("SYNAPSE_LLM_PROVIDER", "mock").lower()

    if provider == "gemini":
        model = os.getenv("SYNAPSE_GEMINI_MODEL", GeminiClient.DEFAULT_MODEL)
        timeout = int(os.getenv("SYNAPSE_GEMINI_TIMEOUT", "60"))
        store = os.getenv("SYNAPSE_GEMINI_STORE", "false").lower() in ("true", "1", "yes")
        return GeminiClient(model=model, timeout=timeout, store=store)

    if provider == "ollama":
        model = os.getenv("SYNAPSE_OLLAMA_MODEL", "llama3.2")
        host = os.getenv("SYNAPSE_OLLAMA_HOST", "http://localhost:11434")
        timeout = int(os.getenv("SYNAPSE_OLLAMA_TIMEOUT", "60"))
        return LocalOllamaClient(model=model, host=host, timeout=timeout)

    return MockLLMClient()

