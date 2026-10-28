"""
Tests for synapse/reader.py
"""

import os
import pytest
from fpdf import FPDF
from synapse.reader import read_text_file, read_pdf_text

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE_ROOT = os.path.dirname(BASE_DIR)
LOCAL_INPUT_DIR = os.path.join(BASE_DIR, "data", "synthetic_inputs")
PARENT_INPUT_DIR = os.path.join(WORKSPACE_ROOT, "lifecare_ai_poc_phase3_input", "input")
INPUT_DIR = LOCAL_INPUT_DIR if os.path.exists(LOCAL_INPUT_DIR) else PARENT_INPUT_DIR
PDF_DIR = os.path.join(BASE_DIR, "data", "pdf_samples")


def test_every_input_txt_reads():
    """Verify that all 10 synthetic .txt files read successfully and contain synthetic header."""
    txt_files = [f for f in os.listdir(INPUT_DIR) if f.endswith(".txt")]
    assert len(txt_files) == 10, f"Expected 10 .txt files, found {len(txt_files)}"

    for filename in txt_files:
        filepath = os.path.join(INPUT_DIR, filename)
        content = read_text_file(filepath)
        assert len(content) > 0, f"Empty content in {filename}"
        assert "SYNTHETIC TEST DOCUMENT" in content, f"Missing synthetic header in {filename}"


def test_every_generated_pdf_contains_patient_name():
    """Verify that each generated PDF returns text containing its expected patient name."""
    pdf_patient_map = {
        "patient_001_cbc.pdf": "Rohan Example",
        "patient_002_biochemistry.pdf": "Meera Sample",
        "patient_003_lipid_profile.pdf": "Arjun Fiction",
        "patient_004_renal_function.pdf": "Kavya Placeholder",
        "patient_005_thyroid.pdf": "Isha Testerson",
    }

    for pdf_filename, expected_name in pdf_patient_map.items():
        pdf_path = os.path.join(PDF_DIR, pdf_filename)
        assert os.path.exists(pdf_path), f"PDF file not found: {pdf_filename}"
        extracted_text = read_pdf_text(pdf_path)
        assert expected_name in extracted_text, (
            f"Expected patient '{expected_name}' not found in extracted PDF text for {pdf_filename}"
        )


def test_missing_files_give_clear_results():
    """Verify that missing files raise FileNotFoundError."""
    missing_txt = os.path.join(INPUT_DIR, "non_existent_file_xyz.txt")
    with pytest.raises(FileNotFoundError):
        read_text_file(missing_txt)

    missing_pdf = os.path.join(PDF_DIR, "non_existent_file_xyz.pdf")
    with pytest.raises(FileNotFoundError):
        read_pdf_text(missing_pdf)


def test_empty_pdf_gives_needs_ocr_result(tmp_path):
    """Verify that a blank PDF without text layer returns 'needs OCR - not supported yet'."""
    blank_pdf_path = tmp_path / "blank_test.pdf"
    pdf = FPDF()
    pdf.add_page()
    # No text added
    pdf.output(str(blank_pdf_path))

    result = read_pdf_text(str(blank_pdf_path))
    assert result == "needs OCR - not supported yet"
