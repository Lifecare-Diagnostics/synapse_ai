"""
synapse_poc/tests/test_wallet_storage.py
Comprehensive automated test suite for Stage 1:
Patient Digital Wallet Schema, Relational Integrity, and Ingestion Adapter.
"""

import os
import pytest
from synapse.schema import (
    MedicalHistoryEntry,
    PatientDemographics,
    ExtractedDocument,
    LabResult,
    ReviewFlag,
)
from synapse.storage import WalletStorage
from synapse.reader import read_text_file
from synapse.extractor import RuleBasedExtractor
from synapse.validator import DocumentValidator
from synapse.reviewer import ExtractionReviewer


@pytest.fixture
def storage():
    """In-memory SQLite storage for isolated test runs."""
    return WalletStorage(":memory:")


@pytest.fixture
def sample_pipeline():
    extractor = RuleBasedExtractor()
    validator = DocumentValidator()
    reviewer = ExtractionReviewer()
    return extractor, validator, reviewer


def test_patient_demographics_crud(storage):
    """Verify patient profile and demographics persistence."""
    demo = PatientDemographics(
        patient_id="SYN-1001",
        patient_name="Rohan Example",
        date_of_birth="1984-05-12",
        age=42,
        sex="Male",
        medical_history=[],
    )
    storage.save_patient(demo)

    retrieved = storage.get_patient_demographics("SYN-1001")
    assert retrieved is not None
    assert retrieved.patient_name == "Rohan Example"
    assert retrieved.age == 42
    assert retrieved.sex == "Male"
    assert retrieved.date_of_birth == "1984-05-12"


def test_medical_history_linking(storage):
    """Verify medical history records link to patient and sort by entry_date."""
    demo = PatientDemographics(
        patient_id="SYN-1001",
        patient_name="Rohan Example",
        date_of_birth=None,
        age=42,
        sex="Male",
        medical_history=[
            MedicalHistoryEntry(
                entry_id="HIST-001",
                condition_or_event="Essential Hypertension",
                entry_date="2024-02-15",
                source="Dr Note 008",
                notes="Prescribed Telmisartan 40mg",
            )
        ],
    )
    storage.save_patient(demo)

    # Add second entry
    storage.add_medical_history_entry(
        "SYN-1001",
        MedicalHistoryEntry(
            entry_id="HIST-002",
            condition_or_event="Allergic Rhinitis",
            entry_date="2025-08-10",
            source="Clinical Assessment",
            notes=None,
        ),
    )

    retrieved = storage.get_patient_demographics("SYN-1001")
    assert len(retrieved.medical_history) == 2
    # Newest first
    assert retrieved.medical_history[0].condition_or_event == "Allergic Rhinitis"
    assert retrieved.medical_history[1].condition_or_event == "Essential Hypertension"


def test_multiple_reports_linked_to_one_patient_chronologically(storage, sample_pipeline):
    """Verify that multiple reports for one patient are stored and ordered chronologically."""
    extractor, validator, reviewer = sample_pipeline

    # Create 3 synthetic documents with different dates
    doc1_text = (
        "SYNTHETIC TEST DOCUMENT\n"
        "Patient Name: Rohan Example\n"
        "Patient ID: SYN-1001\n"
        "Registered On: 2026-04-03\n"
        "Report Type: Complete Blood Count\n\n"
        "Haemoglobin: 14.2 g/dL (Reference 13.0 - 17.0)\n"
    )
    doc2_text = (
        "SYNTHETIC TEST DOCUMENT\n"
        "Patient Name: Rohan Example\n"
        "Patient ID: SYN-1001\n"
        "Registered On: 2026-06-15\n"
        "Report Type: Complete Blood Count\n\n"
        "Haemoglobin: 13.5 g/dL (Reference 13.0 - 17.0)\n"
    )
    doc3_text = (
        "SYNTHETIC TEST DOCUMENT\n"
        "Patient Name: Rohan Example\n"
        "Patient ID: SYN-1001\n"
        "Registered On: 2026-10-20\n"
        "Report Type: Complete Blood Count\n\n"
        "Haemoglobin: 14.8 g/dL (Reference 13.0 - 17.0)\n"
    )

    for txt, fname in [(doc1_text, "cbc_apr.txt"), (doc2_text, "cbc_jun.txt"), (doc3_text, "cbc_oct.txt")]:
        doc = extractor.extract(txt, fname)
        doc = validator.validate(doc)
        doc = reviewer.review(doc)
        storage.ingest_extracted_document(doc)

    reports = storage.list_patient_reports("SYN-1001")
    assert len(reports) == 3
    # Chronological sort: newest first
    assert reports[0].report_date == "2026-10-20"
    assert reports[1].report_date == "2026-06-15"
    assert reports[2].report_date == "2026-04-03"


def test_report_filters_and_parameter_search(storage, sample_pipeline):
    """Verify report filtering by category, date range, and parameter name search."""
    extractor, validator, reviewer = sample_pipeline

    # Ingest CBC
    txt_cbc = (
        "SYNTHETIC TEST DOCUMENT\n"
        "Patient Name: Rohan Example\n"
        "Patient ID: SYN-1001\n"
        "Registered On: 2026-04-03\n"
        "Report Type: Complete Blood Count\n\n"
        "Haemoglobin: 14.2 g/dL (Reference 13.0 - 17.0)\n"
    )
    doc_cbc = reviewer.review(validator.validate(extractor.extract(txt_cbc, "patient_001_cbc.txt")))
    storage.ingest_extracted_document(doc_cbc)

    # Ingest Radiology
    txt_rad = (
        "SYNTHETIC TEST DOCUMENT\n"
        "Patient Name: Rohan Example\n"
        "Patient ID: SYN-1001\n"
        "Study Date: 2026-04-05\n"
        "Study: X-RAY CHEST\n\n"
        "Findings: Lungs clear.\n"
        "IMPRESSION: Normal study.\n"
    )
    doc_rad = reviewer.review(validator.validate(extractor.extract(txt_rad, "patient_006_xray_chest.txt")))
    storage.ingest_extracted_document(doc_rad)

    # Filter by category
    cbc_reports = storage.list_patient_reports("SYN-1001", category="CBC / Hematology")
    assert len(cbc_reports) == 1
    assert cbc_reports[0].report_category == "CBC / Hematology"

    # Filter by date range
    early_reports = storage.list_patient_reports("SYN-1001", start_date="2026-04-01", end_date="2026-04-04")
    assert len(early_reports) == 1
    assert early_reports[0].report_date == "2026-04-03"

    # Search by parameter name
    search_hb = storage.list_patient_reports("SYN-1001", search_query="Haemoglobin")
    assert len(search_hb) == 1
    assert search_hb[0].report_category == "CBC / Hematology"


def test_calendar_view_grouping(storage, sample_pipeline):
    """Verify that reports are grouped by date and missing dates are put under unknown_date."""
    extractor, validator, reviewer = sample_pipeline

    # 1. Normal report with date
    txt1 = (
        "SYNTHETIC TEST DOCUMENT\n"
        "Patient Name: Meera Sample\n"
        "Patient ID: SYN-1002\n"
        "Report Date: 2026-04-04\n"
        "Report: Fasting Biochemistry\n\n"
        "Fasting Glucose: 96 mg/dL (Reference 70 - 110)\n"
    )
    doc1 = reviewer.review(validator.validate(extractor.extract(txt1, "bio.txt")))
    storage.ingest_extracted_document(doc1)

    # 2. Messy report missing date
    txt2 = (
        "SYNTHETIC TEST DOCUMENT\n"
        "Patient Name: Meera Sample\n"
        "Patient ID: SYN-1002\n"
        "Report: Fasting Biochemistry\n\n"
        "Fasting Glucose: 96 mg/dL (Reference 70 - 110)\n"
    )
    doc2 = reviewer.review(validator.validate(extractor.extract(txt2, "messy_no_date.txt")))
    storage.ingest_extracted_document(doc2)

    calendar = storage.get_calendar_view("SYN-1002")
    assert "2026-04-04" in calendar
    assert len(calendar["2026-04-04"]) == 1
    assert "unknown_date" in calendar
    assert len(calendar["unknown_date"]) == 1


def test_longitudinal_parameters_trend(storage, sample_pipeline):
    """Verify parameters across multiple dates for the same patient are retrieved in ASC order."""
    extractor, validator, reviewer = sample_pipeline

    dates_values = [("2026-04-03", 14.2), ("2026-06-15", 13.5), ("2026-10-20", 14.8)]
    for dt, val in dates_values:
        txt = (
            f"SYNTHETIC TEST DOCUMENT\n"
            f"Patient Name: Rohan Example\n"
            f"Patient ID: SYN-1001\n"
            f"Registered On: {dt}\n"
            f"Report Type: Complete Blood Count\n\n"
            f"Haemoglobin: {val} g/dL (Reference 13.0 - 17.0)\n"
        )
        doc = reviewer.review(validator.validate(extractor.extract(txt, f"cbc_{dt}.txt")))
        storage.ingest_extracted_document(doc)

    history = storage.get_longitudinal_parameters("SYN-1001", "Hemoglobin")
    assert len(history) == 3
    # Check ascending chronological order
    assert [p.report_date for p in history] == ["2026-04-03", "2026-06-15", "2026-10-20"]
    assert [p.result_value for p in history] == [14.2, 13.5, 14.8]
    assert all(p.unit == "g/dL" for p in history)


def test_abnormal_summary_categorization(storage, sample_pipeline):
    """Verify parameters are categorized into below/above/within/unavailable/requires_review."""
    extractor, validator, reviewer = sample_pipeline

    txt = (
        "SYNTHETIC TEST DOCUMENT\n"
        "Patient Name: Test Person\n"
        "Patient ID: SYN-9999\n"
        "Report Date: 2026-05-01\n"
        "Report: Multi Panel\n\n"
        "Haemoglobin: 10.2 g/dL (Reference 13.0 - 17.0)\n"    # low -> below_range
        "Platelet Count: 2.50 x10^5/cmm (Reference 1.5 - 4.1)\n" # normal -> within_range
        "Fasting Glucose: 145 mg/dL (Reference 70 - 110)\n"   # high -> above_range
        "Neutrophils: 58 %\n"                                 # no range -> reference_range_unavailable
        "T3: 112 (Reference 60 - 181)\n"                      # missing unit -> requires_review
    )
    doc = reviewer.review(validator.validate(extractor.extract(txt, "multi_test.txt")))
    rep = storage.ingest_extracted_document(doc)

    summary = storage.get_abnormal_summary(rep.report_id)

    assert any(p.original_name == "Haemoglobin" for p in summary["below_range"])
    assert any(p.original_name == "Platelet Count" for p in summary["within_range"])
    assert any(p.original_name == "Fasting Glucose" for p in summary["above_range"])
    assert any(p.original_name == "Neutrophils" for p in summary["reference_range_unavailable"])
    assert any(p.original_name == "T3" for p in summary["requires_review"])


def test_api_json_record_ingestion(storage):
    """Verify digital JSON API record ingestion."""
    payload = {
        "patient_id": "SYN-1002",
        "patient_name": "Meera Sample",
        "report_id": "API-BIO-999",
        "report_date": "2026-07-10",
        "report_category": "Biochemistry",
        "parameters": [
            {
                "test_name": "Fasting Glucose",
                "result_value": 118.0,
                "unit": "mg/dL",
                "reference_range_text": "70 - 110",
                "reference_low": 70.0,
                "reference_high": 110.0,
            },
            {
                "test_name": "HbA1c",
                "result_value": 6.8,
                "unit": "%",
                "reference_range_text": "4.0 - 5.6",
                "reference_low": 4.0,
                "reference_high": 5.6,
            },
        ],
        "notes": "Automated lab feed",
    }
    rep = storage.ingest_api_json_record(payload)

    assert rep.patient_id == "SYN-1002"
    assert rep.file_format == "json"
    assert len(rep.parameters) == 2
    assert rep.parameters[0].standardized_name == "Fasting Glucose"
    assert rep.parameters[0].abnormality_category == "above_range"
    assert rep.parameters[1].abnormality_category == "above_range"

    # Confirm searchable in patient reports
    patient_reports = storage.list_patient_reports("SYN-1002")
    assert any(r.report_id == "API-BIO-999" for r in patient_reports)
