"""
Tests for synapse/extractor.py and synapse/validator.py
"""

import os
import pytest
from synapse.schema import ExtractedDocument, LabResult
from synapse.extractor import RuleBasedExtractor
from synapse.validator import DocumentValidator
from synapse.reader import read_text_file

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE_ROOT = os.path.dirname(BASE_DIR)
LOCAL_INPUT_DIR = os.path.join(BASE_DIR, "data", "synthetic_inputs")
PARENT_INPUT_DIR = os.path.join(WORKSPACE_ROOT, "lifecare_ai_poc_phase3_input", "input")
INPUT_DIR = LOCAL_INPUT_DIR if os.path.exists(LOCAL_INPUT_DIR) else PARENT_INPUT_DIR
MESSY_DIR = os.path.join(BASE_DIR, "data", "messy")


@pytest.fixture
def extractor():
    return RuleBasedExtractor()


@pytest.fixture
def validator():
    return DocumentValidator()


def test_extractor_lab_report(extractor, validator):
    """Test full extraction and validation on patient_001_cbc.txt."""
    path = os.path.join(INPUT_DIR, "patient_001_cbc.txt")
    text = read_text_file(path)
    doc = extractor.extract(text, source_file="patient_001_cbc.txt")
    doc = validator.validate(doc)

    assert doc.patient_id == "SYN-1001"
    assert doc.patient_name == "Rohan Example"
    assert doc.document_date == "2026-04-03"
    assert doc.date_label == "Registered On"
    assert doc.document_type == "lab report"
    assert len(doc.lab_results) == 8
    assert len(doc.validation_errors) == 0

    # Check first result
    hb = doc.lab_results[0]
    assert hb.test_name == "Haemoglobin"
    assert hb.result_value == 14.2
    assert hb.unit == "g/dL"
    assert hb.flag == "normal"
    assert hb.confidence is None


def test_reference_range_boundary_values(validator):
    """
    Test reference range boundary values:
    - 'Up to X': low=None, high=X inclusive (<= X is normal, > X is high)
    - 'Less than X': low=None, high=X exclusive (< X is normal, >= X is high)
    - 'low - high': < low is low, > high is high, [low, high] is normal
    """
    # 1. 'Up to 200'
    res_at_200 = LabResult(
        test_name="Cholesterol",
        result_value=200.0,
        unit="mg/dL",
        reference_range_text="Up to 200",
        reference_low=None,
        reference_high=200.0,
        source_text="raw",
    )
    assert validator._calculate_flag(res_at_200) == "normal"

    res_above_200 = LabResult(
        test_name="Cholesterol",
        result_value=200.1,
        unit="mg/dL",
        reference_range_text="Up to 200",
        reference_low=None,
        reference_high=200.0,
        source_text="raw",
    )
    assert validator._calculate_flag(res_above_200) == "high"

    # 2. 'Less than 150'
    res_at_150 = LabResult(
        test_name="Triglycerides",
        result_value=150.0,
        unit="mg/dL",
        reference_range_text="Less than 150",
        reference_low=None,
        reference_high=150.0,
        source_text="raw",
    )
    # 150 is NOT strictly less than 150, so it must be high
    assert validator._calculate_flag(res_at_150) == "high"

    res_below_150 = LabResult(
        test_name="Triglycerides",
        result_value=149.9,
        unit="mg/dL",
        reference_range_text="Less than 150",
        reference_low=None,
        reference_high=150.0,
        source_text="raw",
    )
    assert validator._calculate_flag(res_below_150) == "normal"

    # 3. '10 - 38.5'
    res_low = LabResult(
        test_name="Urea",
        result_value=9.9,
        unit="mg/dL",
        reference_range_text="10 - 38.5",
        reference_low=10.0,
        reference_high=38.5,
        source_text="raw",
    )
    assert validator._calculate_flag(res_low) == "low"

    res_norm = LabResult(
        test_name="Urea",
        result_value=24.0,
        unit="mg/dL",
        reference_range_text="10 - 38.5",
        reference_low=10.0,
        reference_high=38.5,
        source_text="raw",
    )
    assert validator._calculate_flag(res_norm) == "normal"

    res_high = LabResult(
        test_name="Urea",
        result_value=38.6,
        unit="mg/dL",
        reference_range_text="10 - 38.5",
        reference_low=10.0,
        reference_high=38.5,
        source_text="raw",
    )
    assert validator._calculate_flag(res_high) == "high"


def test_no_reference_range_yields_unknown_flag(validator):
    """Rule 3: No reference range means flag='unknown'. Never infer from comments."""
    res = LabResult(
        test_name="Neutrophils",
        result_value=58.0,
        unit="%",
        reference_range_text=None,
        reference_low=None,
        reference_high=None,
        source_text="Neutrophils: 58 %",
    )
    assert validator._calculate_flag(res) == "unknown"


def test_unit_normalisation(validator):
    """Rule 4: Obvious spelling variants such as gm/dL normalise to g/dL."""
    doc = ExtractedDocument(
        document_id="DOC-T",
        source_file="test.txt",
        document_type="lab report",
        patient_id="SYN-001",
        document_date="2026-01-01",
        lab_results=[
            LabResult(
                test_name="Hb",
                result_value=12.0,
                unit="gm/dL",
                source_text="Hb: 12 gm/dL",
            )
        ],
    )
    val_doc = validator.validate(doc)
    assert val_doc.lab_results[0].unit == "g/dL"


def test_messy_file_missing_date(extractor, validator):
    """Verify messy file with missing date produces validation error and does not crash."""
    path = os.path.join(MESSY_DIR, "messy_001_missing_date.txt")
    text = read_text_file(path)
    doc = extractor.extract(text, source_file="messy_001_missing_date.txt")
    doc = validator.validate(doc)

    assert doc.document_date is None
    assert any("Missing required field: document_date" in err for err in doc.validation_errors)
    assert len(doc.lab_results) == 1


def test_messy_file_missing_unit(extractor, validator):
    """Verify messy file with missing unit produces validation error and does not crash."""
    path = os.path.join(MESSY_DIR, "messy_002_missing_unit.txt")
    text = read_text_file(path)
    doc = extractor.extract(text, source_file="messy_002_missing_unit.txt")
    doc = validator.validate(doc)

    assert any("Missing unit for test: T3" in err for err in doc.validation_errors)
    assert len(doc.lab_results) == 1


# =============================================================================
# Phase 2 — Review flags and error condition tests
# =============================================================================

from synapse.reviewer import ExtractionReviewer, KNOWN_TEST_NAMES


@pytest.fixture
def reviewer():
    return ExtractionReviewer()


def test_unknown_test_name_flagged(extractor, validator, reviewer):
    """Unknown test names must be flagged as 'unsupported' with a review flag."""
    text = (
        "SYNTHETIC TEST DOCUMENT - NOT REAL PATIENT DATA\n\n"
        "Patient: Test Person\nPatient ID: SYN-9001\n"
        "Report Date: 2026-06-01\nReport: Fasting Biochemistry\n\n"
        "Fasting Glucose: 95 mg/dL (Reference 70 - 110)\n"
        "XyloProtein-Q7: 3.4 mg/dL (Reference 1.0 - 5.0)\n"
    )
    doc = extractor.extract(text, source_file="test_unknown.txt")
    doc = validator.validate(doc)
    doc = reviewer.review(doc)

    unknown = [r for r in doc.lab_results if r.test_name == "XyloProtein-Q7"]
    assert len(unknown) == 1, "Unknown test should still be extracted"
    assert unknown[0].extraction_status == "unsupported"
    assert any("not in the recognised test registry" in f.reason for f in unknown[0].review_flags)


def test_missing_value_flagged(extractor, validator, reviewer):
    """A result with no numeric value must receive a needs_review flag."""
    doc = ExtractedDocument(
        document_id="DOC-T",
        source_file="test.txt",
        document_type="lab report",
        patient_id="SYN-001",
        document_date="2026-01-01",
        lab_results=[
            LabResult(
                test_name="Haemoglobin",
                result_value=None,
                unit="g/dL",
                source_text="Haemoglobin: N/A g/dL",
            )
        ],
    )
    doc = validator.validate(doc)
    doc = reviewer.review(doc)

    result = doc.lab_results[0]
    assert result.extraction_status == "needs_review"
    assert any(f.field == "result_value" for f in result.review_flags)


def test_missing_unit_flagged(extractor, validator, reviewer):
    """Missing unit on a non-ratio test must produce a needs_review flag."""
    text = (
        "SYNTHETIC TEST DOCUMENT - NOT REAL PATIENT DATA\n\n"
        "Patient: Isha Testerson\nPatient ID: SYN-1005\n"
        "Report Date: 2026-04-15\nDepartment: Immunoassay\n\n"
        "T3: 112 (Reference 60 - 181)\n"
    )
    doc = extractor.extract(text, source_file="messy_002_missing_unit.txt")
    doc = validator.validate(doc)
    doc = reviewer.review(doc)

    t3 = next((r for r in doc.lab_results if r.test_name == "T3"), None)
    assert t3 is not None
    assert t3.extraction_status == "needs_review"
    assert any(f.field == "unit" for f in t3.review_flags)


def test_missing_date_document_flag(extractor, validator, reviewer):
    """Missing document_date must produce a document-level review flag with severity=error."""
    text = (
        "SYNTHETIC TEST DOCUMENT - NOT REAL PATIENT DATA\n\n"
        "Patient: Meera Sample\nPatient ID: SYN-1002\n"
        "Report: Fasting Biochemistry\n\n"
        "Fasting Glucose: 96 mg/dL (Reference 70 - 110)\n"
    )
    doc = extractor.extract(text, source_file="messy_001_missing_date.txt")
    doc = validator.validate(doc)
    doc = reviewer.review(doc)

    assert doc.document_date is None
    date_flags = [f for f in doc.review_flags if f.field == "document_date"]
    assert len(date_flags) == 1
    assert date_flags[0].severity == "error"


def test_missing_patient_id_document_flag(extractor, validator, reviewer):
    """Missing patient_id must produce a document-level review flag."""
    text = (
        "SYNTHETIC TEST DOCUMENT - NOT REAL PATIENT DATA\n\n"
        "Patient: Test Person\n"
        "Report Date: 2026-06-03\nReport: Fasting Biochemistry\n\n"
        "Fasting Glucose: 101 mg/dL (Reference 70 - 110)\n"
    )
    doc = extractor.extract(text, source_file="messy_005_missing_patient_id.txt")
    doc = validator.validate(doc)
    doc = reviewer.review(doc)

    assert doc.patient_id is None
    pid_flags = [f for f in doc.review_flags if f.field == "patient_id"]
    assert len(pid_flags) == 1
    assert pid_flags[0].severity == "warning"


def test_negative_value_validation_error(validator):
    """A negative result_value must produce a validation error (implausible value)."""
    doc = ExtractedDocument(
        document_id="DOC-T",
        source_file="test.txt",
        document_type="lab report",
        patient_id="SYN-001",
        document_date="2026-01-01",
        lab_results=[
            LabResult(
                test_name="Haemoglobin",
                result_value=-5.0,
                unit="g/dL",
                source_text="Haemoglobin: -5 g/dL",
            )
        ],
    )
    doc = validator.validate(doc)
    assert any("Implausible negative" in e for e in doc.validation_errors)


def test_extraction_summary_counts(extractor, validator, reviewer):
    """extraction_summary must correctly count ok/needs_review/unsupported."""
    text = (
        "SYNTHETIC TEST DOCUMENT - NOT REAL PATIENT DATA\n\n"
        "Patient: Test Person\nPatient ID: SYN-9001\n"
        "Report Date: 2026-06-01\nReport: Fasting Biochemistry\n\n"
        "Fasting Glucose: 95 mg/dL (Reference 70 - 110)\n"
        "XyloProtein-Q7: 3.4 mg/dL (Reference 1.0 - 5.0)\n"
        "T3: 112 (Reference 60 - 181)\n"
    )
    doc = extractor.extract(text, source_file="test_summary.txt")
    doc = validator.validate(doc)
    doc = reviewer.review(doc)

    s = doc.extraction_summary
    assert "ok" in s
    assert "needs_review" in s
    assert "unsupported" in s
    # Fasting Glucose = ok, XyloProtein-Q7 = unsupported, T3 = needs_review (missing unit)
    assert s["ok"] >= 1
    assert s["unsupported"] >= 1
    assert s["needs_review"] >= 1


def test_no_false_flags_on_clean_document(extractor, validator, reviewer):
    """A clean lab report should have no error/warning-severity review flags on results."""
    path = os.path.join(INPUT_DIR, "patient_001_cbc.txt")
    text = read_text_file(path)
    doc = extractor.extract(text, source_file="patient_001_cbc.txt")
    doc = validator.validate(doc)
    doc = reviewer.review(doc)

    assert doc.validation_errors == []
    # All results should be ok or info-only flags
    for result in doc.lab_results:
        non_info = [f for f in result.review_flags if f.severity in ("warning", "error")]
        assert len(non_info) == 0, (
            f"Unexpected warning/error flag on {result.test_name}: "
            + str([f.reason for f in non_info])
        )
