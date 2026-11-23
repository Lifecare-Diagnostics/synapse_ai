"""
synapse_poc/synapse/reader.py
Hybrid document reader supporting plain text (.txt), digital PDF, scanned PDF,
and medical images (.png, .jpg, .jpeg) with PyMuPDF and Tesseract OCR.
"""

import os
from typing import Optional
import pymupdf
from PIL import Image

from synapse.ocr import (
    is_tesseract_available,
    ocr_image,
    ocr_pymupdf_pixmap,
)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}


def read_text_file(path: str) -> str:
    """
    Read plain text from a file.
    Raises FileNotFoundError if file does not exist.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def read_pdf_text(path: str, min_char_threshold: int = 40) -> str:
    """
    Extract text from a PDF file using a hybrid PyMuPDF + OCR approach.
    1. Attempts digital vector text layer extraction via PyMuPDF.
    2. If a page contains fewer than `min_char_threshold` characters (e.g. scanned image),
       attempts OCR using Tesseract if the OCR engine is available.
    3. If no extractable text is found and OCR cannot extract text, returns
       'needs OCR - not supported yet'.

    Raises FileNotFoundError if file does not exist.
    Raises ValueError if PDF cannot be opened.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    try:
        doc = pymupdf.open(path)
    except Exception as e:
        raise ValueError(f"Failed to open PDF file: {path} ({e})")

    try:
        if len(doc) == 0:
            return "needs OCR - not supported yet"

        extracted_pages = []
        has_ocr = is_tesseract_available()

        for page in doc:
            page_text = page.get_text() or ""
            cleaned_text = page_text.strip()

            if len(cleaned_text) >= min_char_threshold:
                # Page contains sufficient digital text
                extracted_pages.append(cleaned_text)
            else:
                # Low-density page (likely scanned / image-only page)
                ocr_text = ""
                if has_ocr:
                    try:
                        # Render page at 300 DPI for high-accuracy optical recognition
                        pix = page.get_pixmap(dpi=300)
                        ocr_text = ocr_pymupdf_pixmap(pix)
                    except Exception:
                        ocr_text = ""

                if ocr_text.strip():
                    extracted_pages.append(ocr_text.strip())
                elif cleaned_text:
                    extracted_pages.append(cleaned_text)

        full_text = "\n".join(extracted_pages).strip()
        if not full_text:
            return "needs OCR - not supported yet"

        return full_text
    finally:
        doc.close()


def read_image_file(path: str) -> str:
    """
    Extract text from a medical image file (.png, .jpg, .jpeg) using OCR.
    If OCR is not available or extracts no text, returns 'needs OCR - not supported yet'.
    Raises ValueError if extension is unsupported or file cannot be opened as an image.
    Raises FileNotFoundError if file does not exist.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ValueError(f"Unsupported image format '{ext}'. Expected one of {sorted(IMAGE_EXTENSIONS)}")

    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    try:
        with Image.open(path) as img:
            img.verify()
    except Exception as e:
        raise ValueError(f"Failed to open image file: {path} ({e})")

    if not is_tesseract_available():
        return "needs OCR - not supported yet"

    try:
        extracted = ocr_image(path)
        if not extracted.strip():
            return "needs OCR - not supported yet"
        return extracted.strip()
    except Exception:
        return "needs OCR - not supported yet"


def read_document_text(path: str) -> str:
    """
    Unified entrypoint to read any supported document file (.txt, .pdf, or images).
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    ext = os.path.splitext(path)[1].lower()
    if ext == ".txt":
        return read_text_file(path)
    elif ext == ".pdf":
        return read_pdf_text(path)
    elif ext in IMAGE_EXTENSIONS:
        return read_image_file(path)
    else:
        raise ValueError(f"Unsupported file format '{ext}' for document reading.")
