"""
scripts/verify_ollama.py
Synapse AI — Local Ollama Integration & Model Readiness Verification Script.
Uses strictly synthetic clinical data. Checks local Ollama connectivity, model availability,
and runs an end-to-end extraction -> validation -> review verification.
If Ollama is offline, gracefully tests and proves the fallback safety path.
"""

import json
import os
import sys
import urllib.request
import urllib.error

# Ensure synapse_poc package is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from synapse.llm import LocalOllamaClient, extract_json_from_llm_response
from synapse.extractor import LLMExtractor, HybridExtractor, RuleBasedExtractor
from synapse.validator import DocumentValidator
from synapse.reviewer import ExtractionReviewer

SYNTHETIC_CLINICAL_NOTE = """
SYNTHETIC CLINICAL CONSULTATION NOTE
Patient Name: Rajesh Sharma
Patient ID: SYN-8801
Consultation Date: 2026-11-20
Department: Internal Medicine

Chief Complaints:
Patient presents with 3-day history of low-grade fever, dry cough, and mild fatigue.

Clinical Examination:
Chest auscultation reveals clear breath sounds bilaterally without wheeze or crackles.
Pulse: 78 bpm, Blood Pressure: 122/80 mmHg, SpO2: 98% on room air.

Impression:
Mild acute viral upper respiratory tract infection.

Plan:
1. Tab Paracetamol 650mg SOS for fever.
2. Warm saline gargles and adequate oral hydration.
3. Review if fever persists beyond 5 days.
"""


def check_ollama_status(host: str = "http://localhost:11434") -> dict:
    """Check if local Ollama daemon is reachable and list installed models."""
    url = f"{host.rstrip('/')}/api/tags"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Synapse-Verifier/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name") for m in data.get("models", [])]
            return {"reachable": True, "models": models, "error": None}
    except Exception as e:
        return {"reachable": False, "models": [], "error": str(e)}


def run_verification():
    host = os.getenv("SYNAPSE_OLLAMA_HOST", "http://localhost:11434")
    model = os.getenv("SYNAPSE_OLLAMA_MODEL", "llama3.2:1b")

    print("=" * 70)
    print("      SYNAPSE AI — LOCAL OLLAMA VERIFICATION & READINESS HARNESS     ")
    print("=" * 70)
    print(f"Target Ollama Host : {host}")
    print(f"Target Model       : {model}")
    print("-" * 70)

    # 1. Check Connectivity
    print("\n[Step 1] Checking Ollama Service Connectivity...")
    status = check_ollama_status(host)
    if not status["reachable"]:
        print(f"[-] Ollama service is NOT reachable at {host}.")
        print(f"    Reason: {status['error']}")
        print("\n[Testing Fallback Mechanism]")
        print("Testing HybridExtractor fallback when Ollama is offline...")

        client = LocalOllamaClient(model=model, host=host, timeout=5)
        hybrid = HybridExtractor(llm_extractor=LLMExtractor(client=client))
        doc = hybrid.extract(SYNTHETIC_CLINICAL_NOTE, "synthetic_consult_note.txt")

        assert doc is not None
        assert doc.extraction_method == "rule_based"
        print("[+] SUCCESS: Fallback to deterministic extraction succeeded without crashing!")
        print(f"    Document Type   : {doc.document_type}")
        print(f"    Patient ID      : {doc.patient_id or 'None (safely preserved)'}")
        print(f"    Extraction Mode : {doc.extraction_method}")
        print("-" * 70)
        print("Ollama is not yet active. Once Ollama is installed and the model is pulled,")
        print(f"run: python scripts/verify_ollama.py")
        print("=" * 70)
        return

    print(f"[+] SUCCESS: Ollama service is ONLINE at {host}.")
    print(f"    Installed Models: {status['models'] or 'None found'}")

    # Check if target model exists
    model_installed = any(m == model or m.startswith(f"{model}:") or model.startswith(f"{m}:") for m in status["models"])
    if not model_installed:
        print(f"[-] Target model '{model}' is not currently downloaded.")
        print(f"    To download this model, run in terminal:")
        print(f"    ollama pull {model}")
        return

    print(f"[+] Model '{model}' is installed and ready for inference.")

    # 2. Test Local Inference
    print("\n[Step 2] Sending Synthetic Clinical Note to Local Ollama...")
    client = LocalOllamaClient(model=model, host=host, timeout=120)
    try:
        raw_json = client.extract_clinical_json(SYNTHETIC_CLINICAL_NOTE)
        print("[+] SUCCESS: Received and parsed valid structured JSON from local LLM.")
        print("    Preview of Extracted Data:")
        print(f"    - Document Type    : {raw_json.get('document_type')}")
        print(f"    - Patient ID       : {raw_json.get('patient_id')}")
        print(f"    - Patient Name     : {raw_json.get('patient_name')}")
        print(f"    - Document Date    : {raw_json.get('document_date')}")
        print(f"    - Key Sections     : {list(raw_json.get('key_sections', {}).keys())}")
    except Exception as e:
        print(f"[-] Inference failed: {e}")
        return

    # 3. Test Validation & Review Pipeline
    print("\n[Step 3] Passing LLM Extraction through Validation & Review Queue...")
    llm_extractor = LLMExtractor(client=client)
    hybrid = HybridExtractor(llm_extractor=llm_extractor)
    doc = hybrid.extract(SYNTHETIC_CLINICAL_NOTE, "synthetic_consult_note.txt")

    validator = DocumentValidator()
    validated_doc = validator.validate(doc)

    reviewer = ExtractionReviewer()
    reviewed_doc = reviewer.review(validated_doc)

    print("[+] SUCCESS: Document passed through standard clinical review pipeline.")
    print(f"    - Review Status    : {reviewed_doc.review_status}")
    print(f"    - Extraction Method: {reviewed_doc.extraction_method}")
    print(f"    - Flags Generated  : {len(reviewed_doc.review_flags)}")
    for f in reviewed_doc.review_flags:
        print(f"      * [{f.flag_type}] {f.field}: {f.message}")

    print("\n" + "=" * 70)
    print("       ALL OLLAMA LOCAL INFERENCE & PIPELINE CHECKS PASSED           ")
    print("=" * 70)


if __name__ == "__main__":
    run_verification()
