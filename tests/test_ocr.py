"""
Tests for synapse/ocr.py and hybrid OCR reader functionality in synapse/reader.py.
"""

import os
import pytest
from PIL import Image, ImageDraw
from fpdf import FPDF

from synapse.ocr import (
    is_tesseract_available,
    get_ocr_engine_info,
    resolve_tesseract_binary,
    ocr_image,
)
from synapse.reader import (
    read_text_file,
    read_pdf_text,
    read_image_file,
    read_document_text,
)


def create_synthetic_image(path: str, text: str = "SYNTHETIC OCR TEST"):
    """Helper to create a simple PNG image with text rendered via PIL."""
    img = Image.new("RGB", (400, 100), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((20, 40), text, fill=(0, 0, 0))
    img.save(path)
    return path


def test_is_tesseract_available_boolean():
    """Verify is_tesseract_available returns a boolean without throwing."""
    res = is_tesseract_available()
    assert isinstance(res, bool)


def test_get_ocr_engine_info_structure():
    """Verify get_ocr_engine_info returns expected keys and correct data types."""
    info = get_ocr_engine_info()
    assert info["engine"] == "tesseract"
    assert isinstance(info["available"], bool)
    assert info["binary_path"] is None or isinstance(info["binary_path"], str)
    assert info["version"] is None or isinstance(info["version"], str)


def test_read_image_file_not_found():
    """Verify missing image file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        read_image_file("non_existent_image_12345.png")


def test_read_image_file_invalid_extension():
    """Verify non-image file passed to read_image_file raises ValueError."""
    with pytest.raises(ValueError, match="Unsupported image format"):
        read_image_file("sample_report.pdf")


def test_read_image_file_fallback_when_no_ocr(monkeypatch, tmp_path):
    """Verify that when OCR is unavailable, read_image_file returns needs OCR status."""
    img_path = str(tmp_path / "test_report.png")
    create_synthetic_image(img_path)

    monkeypatch.setattr("synapse.reader.is_tesseract_available", lambda: False)
    result = read_image_file(img_path)
    assert result == "needs OCR - not supported yet"


def test_read_document_text_routing(tmp_path):
    """Verify read_document_text dispatches appropriately by extension."""
    # 1. Text file
    txt_path = tmp_path / "test.txt"
    txt_path.write_text("SYNTHETIC TEXT CONTENT", encoding="utf-8")
    assert "SYNTHETIC TEXT CONTENT" in read_document_text(str(txt_path))

    # 2. Unsupported extension
    doc_path = tmp_path / "test.docx"
    doc_path.write_text("dummy", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported file format"):
        read_document_text(str(doc_path))


def test_ocr_image_with_mocked_tesseract(monkeypatch, tmp_path):
    """Verify end-to-end OCR image extraction when OCR engine is active."""
    img_path = str(tmp_path / "scanned_lab.png")
    create_synthetic_image(img_path)

    expected_text = (
        "LIFECARE DIAGNOSTICS - SYNTHETIC REPORT\n"
        "Patient Name: Rohan Example\n"
        "Patient ID: SYN-1001\n"
        "Haemoglobin: 13.9 g/dL\n"
    )

    monkeypatch.setattr("synapse.ocr.is_tesseract_available", lambda: True)
    monkeypatch.setattr("synapse.reader.is_tesseract_available", lambda: True)
    monkeypatch.setattr("pytesseract.image_to_string", lambda *args, **kwargs: expected_text)

    extracted = read_image_file(img_path)
    assert "Rohan Example" in extracted
    assert "Haemoglobin: 13.9" in extracted


def test_hybrid_pdf_scanned_page_triggers_ocr(monkeypatch, tmp_path):
    """Verify that a PDF page with low character density triggers OCR fallback."""
    pdf_path = tmp_path / "scanned_page.pdf"
    pdf = FPDF()
    pdf.add_page()
    # Blank page / image only - zero digital text characters
    pdf.output(str(pdf_path))

    mock_ocr_result = "OCR EXTRACTED: Patient Name: Kavya Placeholder\nSerum Creatinine: 0.9 mg/dL"
    ocr_called = []

    def mock_ocr(pix):
        ocr_called.append(True)
        return mock_ocr_result

    monkeypatch.setattr("synapse.reader.is_tesseract_available", lambda: True)
    monkeypatch.setattr("synapse.reader.ocr_pymupdf_pixmap", mock_ocr)

    extracted = read_pdf_text(str(pdf_path))
    assert len(ocr_called) == 1, "Expected OCR fallback to be invoked for scanned page"
    assert "Kavya Placeholder" in extracted
    assert "Serum Creatinine: 0.9" in extracted


def test_hybrid_pdf_digital_page_skips_ocr(monkeypatch, tmp_path):
    """Verify that a high-density digital PDF extracts via PyMuPDF without invoking OCR."""
    pdf_path = tmp_path / "digital_page.pdf"
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(200, 10, text="LIFECARE DIAGNOSTICS - SYNTHETIC CLINICAL REPORT WITH SUFFICIENT CHARACTERS")
    pdf.output(str(pdf_path))

    ocr_called = []

    def mock_ocr(pix):
        ocr_called.append(True)
        return "UNEXPECTED OCR RESULT"

    monkeypatch.setattr("synapse.reader.is_tesseract_available", lambda: True)
    monkeypatch.setattr("synapse.reader.ocr_pymupdf_pixmap", mock_ocr)

    extracted = read_pdf_text(str(pdf_path))
    assert len(ocr_called) == 0, "OCR should not be invoked for standard digital PDF pages"
    assert "LIFECARE DIAGNOSTICS" in extracted

