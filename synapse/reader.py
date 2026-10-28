"""
synapse_poc/synapse/reader.py
Document reader supporting plain text (.txt) and digital PDF (.pdf) files via PyMuPDF.
"""

import os
from typing import Optional
import pymupdf


def read_text_file(path: str) -> str:
    """
    Read plain text from a file.
    Raises FileNotFoundError if file does not exist.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def read_pdf_text(path: str) -> str:
    """
    Extract digital text layer from a PDF file using PyMuPDF.
    If the PDF has no pages or contains no extractable text, returns
    'needs OCR - not supported yet'.
    Raises FileNotFoundError if file does not exist.
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
        for page in doc:
            page_text = page.get_text()
            if page_text:
                extracted_pages.append(page_text)

        full_text = "\n".join(extracted_pages).strip()
        if not full_text:
            return "needs OCR - not supported yet"

        return full_text
    finally:
        doc.close()
