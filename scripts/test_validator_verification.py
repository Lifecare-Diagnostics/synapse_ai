"""
Verification of deterministic clinical validation rules for Synapse AI POC.
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from synapse.schema import ExtractedDocument, LabResult
from synapse.validator import DocumentValidator

tests_data = [
    ("Hemoglobin", 9.2, "g/dL", "12 - 16", 12.0, 16.0, "low"),
    ("WBC", 7.2, "cells/cumm", "4 - 11", 4.0, 11.0, "normal"),
    ("Glucose", 180.0, "mg/dL", "70 - 140", 70.0, 140.0, "high"),
    ("Vitamin D", 25.0, "ng/mL", None, None, None, "unknown"),
]

lab_results = []
for name, val, unit, ref_text, ref_low, ref_high, expected in tests_data:
    lab_results.append(
        LabResult(
            test_name=name,
            result_value=val,
            unit=unit,
            reference_range_text=ref_text,
            reference_low=ref_low,
            reference_high=ref_high,
            flag="unknown",
            source_text=f"{name}: {val}",
            source_page=1,
            confidence=1.0,
        )
    )

doc = ExtractedDocument(
    document_id="DOC-CLINICAL-TEST",
    source_file="synthetic_clinical_test.txt",
    document_type="lab report",
    patient_id="SYN-TEST-001",
    patient_name="Test Patient",
    document_date="2026-11-23",
    lab_results=lab_results,
    key_text_sections={},
    extraction_method="rule_based",
    validation_errors=[],
)

validator = DocumentValidator()
validated_doc = validator.validate(doc)

print("=== CLINICAL VALIDATOR TEST RESULTS ===")
all_ok = True
for res, (name, val, unit, ref_text, ref_low, ref_high, expected) in zip(
    validated_doc.lab_results, tests_data
):
    actual_flag = res.flag.upper()
    expected_flag = expected.upper()
    match = actual_flag == expected_flag
    if not match:
        all_ok = False
    status = "PASS" if match else "FAIL"
    print(
        f"Test: {res.test_name:12} | Result: {res.result_value:5} | Range: {str(res.reference_range_text):10} | Flag: {actual_flag:7} | Expected: {expected_flag:7} | Status: {status}"
    )

print("Overall Validator Test:", "PASSED" if all_ok else "FAILED")
if not all_ok:
    sys.exit(1)
