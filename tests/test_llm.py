"""
Tests for synapse/llm.py and HybridExtractor in synapse/extractor.py.
"""

import os
import pytest
from synapse.llm import (
    extract_json_from_llm_response,
    MockLLMClient,
    get_default_llm_client,
)
from synapse.extractor import (
    RuleBasedExtractor,
    LLMExtractor,
    HybridExtractor,
)
from synapse.reader import read_text_file

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE_ROOT = os.path.dirname(BASE_DIR)
LOCAL_INPUT_DIR = os.path.join(BASE_DIR, "data", "synthetic_inputs")
PARENT_INPUT_DIR = os.path.join(WORKSPACE_ROOT, "lifecare_ai_poc_phase3_input", "input")
INPUT_DIR = LOCAL_INPUT_DIR if os.path.exists(LOCAL_INPUT_DIR) else PARENT_INPUT_DIR


def test_extract_json_clean():
    """Verify clean JSON string parses correctly."""
    raw = '{"patient_id": "SYN-1001", "document_type": "clinical note"}'
    res = extract_json_from_llm_response(raw)
    assert res["patient_id"] == "SYN-1001"
    assert res["document_type"] == "clinical note"


def test_extract_json_fenced_markdown():
    """Verify JSON inside ```json ... ``` code fence is extracted cleanly."""
    raw = """Here is the extracted clinical data:
```json
{
  "patient_name": "Rohan Example",
  "document_type": "lab report"
}
```
Hope this helps!"""
    res = extract_json_from_llm_response(raw)
    assert res["patient_name"] == "Rohan Example"
    assert res["document_type"] == "lab report"


def test_extract_json_conversational_chatter():
    """Verify JSON with preamble and trailing text parses."""
    raw = """Certainly! Extracting records now:
{"document_type": "radiology", "clinical_summary": "Lungs clear."}
End of report."""
    res = extract_json_from_llm_response(raw)
    assert res["document_type"] == "radiology"
    assert res["clinical_summary"] == "Lungs clear."


def test_extract_json_invalid_raises():
    """Verify invalid JSON raises ValueError with informative message."""
    with pytest.raises(ValueError, match="Failed to decode JSON"):
        extract_json_from_llm_response("No JSON object anywhere in this text.")


def test_mock_llm_client():
    """Verify MockLLMClient extracts structured dictionary."""
    client = MockLLMClient()
    doc_text = "Patient Name: Rohan Example\nPatient ID: SYN-1001\nDate: 2024-03-14\nFindings: Normal heart size."
    res = client.extract_clinical_json(doc_text)
    assert res["patient_name"] == "Rohan Example"
    assert res["patient_id"] == "SYN-1001"
    assert "Findings" in res["key_sections"]


def test_llm_extractor():
    """Verify LLMExtractor returns a valid ExtractedDocument."""
    extractor = LLMExtractor(client=MockLLMClient())
    text = "Patient Name: Kavya Placeholder\nPatient ID: SYN-1004\nDate: 2024-03-14\nFindings: Lungs clear."
    doc = extractor.extract(text, "patient_004.txt")
    assert doc.patient_name == "Kavya Placeholder"
    assert doc.extraction_method == "llm_prompt"
    assert "Findings" in doc.key_text_sections


def test_hybrid_extractor_structured_lab_stays_rule_based():
    """Verify that a structured CBC lab report stays on the deterministic rule-based path."""
    cbc_path = os.path.join(INPUT_DIR, "patient_001_cbc.txt")
    text = read_text_file(cbc_path)

    hybrid = HybridExtractor()
    doc = hybrid.extract(text, "patient_001_cbc.txt")

    assert doc.document_type == "lab report"
    assert doc.extraction_method == "rule_based"
    assert len(doc.lab_results) == 8
    assert any(r.test_name == "Haemoglobin" for r in doc.lab_results)


def test_hybrid_extractor_narrative_doctor_note():
    """Verify that a narrative doctor note is routed and enriched via LLM."""
    note_path = os.path.join(INPUT_DIR, "patient_008_doctor_note.txt")
    text = read_text_file(note_path)

    hybrid = HybridExtractor()
    doc = hybrid.extract(text, "patient_008_doctor_note.txt")

    assert doc.extraction_method == "hybrid_rules_llm"
    assert doc.document_type in ("clinical note", "doctor note")
    assert doc.patient_id is not None
    assert len(doc.key_text_sections) > 0


def test_hybrid_extractor_radiology_report():
    """Verify that a radiology X-Ray document is processed and enriched via hybrid extraction."""
    xray_path = os.path.join(INPUT_DIR, "patient_006_xray_chest.txt")
    text = read_text_file(xray_path)

    hybrid = HybridExtractor()
    doc = hybrid.extract(text, "patient_006_xray_chest.txt")

    assert doc.extraction_method == "hybrid_rules_llm"
    assert doc.document_type == "radiology"
    assert "Findings" in doc.key_text_sections or "IMPRESSION" in doc.key_text_sections


def test_hybrid_extractor_graceful_fallback_on_llm_failure(monkeypatch):
    """Verify that if LLM raises an error, HybridExtractor falls back to rule extraction safely."""
    class FailingLLMClient(MockLLMClient):
        def extract_clinical_json(self, document_text: str):
            raise RuntimeError("Simulated LLM connection timeout")

    hybrid = HybridExtractor(llm_extractor=LLMExtractor(client=FailingLLMClient()))
    xray_path = os.path.join(INPUT_DIR, "patient_006_xray_chest.txt")
    text = read_text_file(xray_path)

    # Must not raise RuntimeError
    doc = hybrid.extract(text, "patient_006_xray_chest.txt")
    assert doc.document_type == "radiology"
    assert doc.extraction_method == "rule_based"

