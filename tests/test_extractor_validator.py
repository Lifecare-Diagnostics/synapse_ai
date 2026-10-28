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
