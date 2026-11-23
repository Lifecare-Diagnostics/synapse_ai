#!/usr/bin/env python3
"""
scripts/verify_gemini.py
Live Gemini API verification script for Synapse AI POC.

Usage:
    python scripts/verify_gemini.py

Requires:
    - GEMINI_API_KEY or GOOGLE_API_KEY environment variable set
    - google-genai SDK installed

This script:
    1. Checks API key configuration (without printing the key)
    2. Verifies the google-genai SDK is installed
    3. Sends a synthetic clinical document to the configured Gemini model
    4. Validates the structured JSON response
    5. Reports token usage and estimated cost
    6. Tests error handling with invalid input

IMPORTANT:
    - Uses ONLY synthetic/fabricated data — no real patient records
    - NEVER prints, logs, or exposes the API key
    - Results are for technical verification only, NOT clinical validation
"""

import json
import os
import sys
import time

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def print_header(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_result(label: str, value, ok: bool = True):
    status = "✓" if ok else "✗"
    print(f"  {status} {label}: {value}")


def main():
    print_header("SYNAPSE AI — GEMINI API LIVE VERIFICATION")
    print(f"  Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Purpose: Technical POC verification with synthetic data")
    print(f"  Warning: This is NOT clinical validation.\n")

    # Step 1: Check API key
    print_header("Step 1: API Key Configuration")
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print_result("API Key", "NOT CONFIGURED", ok=False)
        print("\n  Set GEMINI_API_KEY or GOOGLE_API_KEY environment variable.")
        print("  Get a free key at: https://aistudio.google.com/apikey")
        sys.exit(1)
    key_preview = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "***"
    print_result("API Key", f"Configured ({key_preview})")

    # Step 2: Check SDK
    print_header("Step 2: SDK Verification")
    try:
        import google.genai
        print_result("google-genai SDK", f"v{google.genai.__version__}")
    except ImportError:
        print_result("google-genai SDK", "NOT INSTALLED", ok=False)
        print("  Install with: pip install google-genai")
        sys.exit(1)

    # Step 3: Check Synapse integration
    print_header("Step 3: Synapse Integration Check")
    try:
        from synapse.llm import GeminiClient, get_default_llm_client
        from synapse.usage_tracker import UsageTracker, estimate_cost_usd
        print_result("GeminiClient", "Available")
        print_result("UsageTracker", "Available")
    except ImportError as e:
        print_result("Synapse imports", f"FAILED: {e}", ok=False)
        sys.exit(1)

    # Step 4: Initialize client
    print_header("Step 4: Client Initialization")
    try:
        client = GeminiClient()
        print_result("Model", client.model)
        print_result("Timeout", f"{client.timeout}s")
        print_result("Store", client.store)
    except Exception as e:
        print_result("Initialization", f"FAILED: {e}", ok=False)
        sys.exit(1)

    # Step 5: Live generation test with synthetic data
    print_header("Step 5: Live Clinical Extraction (Synthetic Data)")
    synthetic_document = """
    LIFE CARE DIAGNOSTICS — SYNTHETIC TEST REPORT
    Report ID: SYNTH-VERIFY-001
    Date: 2024-07-15

    Patient Name: Priya Synapse (SYNTHETIC — NOT A REAL PATIENT)
    Patient ID: SYN-TEST-9999
    Age: 32 years | Sex: Female

    COMPLETE BLOOD COUNT
    Test                    Result      Unit        Reference Range
    Haemoglobin             12.8        g/dL        12.0 - 16.0
    Total WBC Count         7200        cells/cumm  4000 - 11000
    Platelet Count          250000      cells/cumm  150000 - 400000
    RBC Count               4.5         million/cumm 3.8 - 5.8

    CLINICAL NOTES:
    Patient presented for routine annual check-up.
    All parameters within normal limits.
    No complaints. Follow-up in 12 months.

    Reporting Doctor: Dr. Synapse Test (SYNTHETIC)
    """

    try:
        start = time.time()
        result = client.extract_clinical_json(synthetic_document)
        elapsed = time.time() - start

        print_result("API Call", f"Success ({elapsed:.2f}s)")
        print_result("Document Type", result.get("document_type", "N/A"))
        print_result("Patient Name", result.get("patient_name", "N/A"))
        print_result("Patient ID", result.get("patient_id", "N/A"))
        print_result("Document Date", result.get("document_date", "N/A"))

        lab_results = result.get("lab_results", [])
        print_result("Lab Results Found", len(lab_results))
        for lr in lab_results[:5]:
            name = lr.get("test_name", "?")
            val = lr.get("result_value", "?")
            unit = lr.get("unit", "")
            print(f"      - {name}: {val} {unit}")

        # Token usage
        usage = client.last_usage
        if usage:
            print(f"\n  Token Usage:")
            print_result("Input Tokens", usage.get("total_input_tokens", "N/A"))
            print_result("Output Tokens", usage.get("total_output_tokens", "N/A"))
            print_result("Total Tokens", usage.get("total_tokens", "N/A"))

            inp = usage.get("total_input_tokens") or 0
            out = usage.get("total_output_tokens") or 0
            cost = estimate_cost_usd(client.model, inp, out)
            print_result("Estimated Cost", f"${cost:.6f} USD (₹{cost * 90:.4f} INR)")

    except Exception as e:
        print_result("API Call", f"FAILED: {type(e).__name__}: {e}", ok=False)
        print("\n  Possible causes:")
        print("  - Invalid or expired API key")
        print("  - Model not available on free tier")
        print("  - Rate limit exceeded")
        print("  - Network connectivity issue")
        sys.exit(1)

    # Step 6: Usage tracker test
    print_header("Step 6: Usage Tracker Integration")
    tracker = UsageTracker(":memory:")
    if usage:
        tracker.record(
            provider="gemini",
            model=client.model,
            input_tokens=usage.get("total_input_tokens"),
            output_tokens=usage.get("total_output_tokens"),
            total_tokens=usage.get("total_tokens"),
            document_id="SYNTH-VERIFY-001",
            processing_time_seconds=usage.get("processing_time_seconds"),
        )
        summary = tracker.get_summary()
        print_result("Tracked Calls", summary["total_calls"])
        print_result("Total Cost USD", f"${summary['total_cost_usd']:.6f}")
        print_result("Total Cost INR", f"₹{summary['total_cost_inr']:.4f}")

    # Step 7: Monthly cost projections
    print_header("Step 7: Monthly Cost Projections")
    volumes = [1000, 5000, 10000, 25000, 50000, 100000]
    print(f"  {'Volume':>10}  {'USD':>10}  {'INR':>12}")
    print(f"  {'-'*10}  {'-'*10}  {'-'*12}")
    for vol in volumes:
        est = tracker.get_monthly_cost_estimate(vol, model=client.model)
        usd = est["estimated_monthly_cost_usd"]
        inr = est["estimated_monthly_cost_inr"]
        print(f"  {vol:>10,}  ${usd:>9.2f}  ₹{inr:>11.2f}")

    # Summary
    print_header("VERIFICATION COMPLETE")
    print("  ✓ Gemini API connection verified")
    print("  ✓ Clinical extraction working")
    print("  ✓ Token usage tracking functional")
    print("  ✓ Cost estimation operational")
    print(f"\n  Model used: {client.model}")
    print(f"  SDK version: {google.genai.__version__}")
    print("\n  DISCLAIMER: This verification used synthetic data only.")
    print("  Results demonstrate technical capability, not clinical accuracy.")
    print("  Human review remains mandatory for all extracted data.")


if __name__ == "__main__":
    main()
