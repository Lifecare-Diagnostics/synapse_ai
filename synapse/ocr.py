"""
synapse_poc/synapse/ocr.py
OCR Engine integration module for Synapse AI.
Provides local OCR extraction using Tesseract OCR (via pytesseract & Pillow)
with auto-detection of Windows installation paths and graceful fallback.
"""

import io
import os
import shutil
from typing import Any, Dict, Optional, Union
from PIL import Image
import pytesseract


COMMON_TESSERACT_WINDOWS_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
]


def resolve_tesseract_binary() -> Optional[str]:
    """
    Locate Tesseract executable on the system.
    Checks PATH first, then standard Windows installation locations.
    Configures pytesseract.pytesseract.tesseract_cmd if found.
    """
    # 1. Check if pytesseract already has a working command set
    current_cmd = getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")
    if current_cmd and os.path.isabs(current_cmd) and os.path.isfile(current_cmd):
        return current_cmd

    # 2. Check PATH
    which_path = shutil.which("tesseract")
    if which_path:
        pytesseract.pytesseract.tesseract_cmd = which_path
        return which_path

    # 3. Check common Windows paths
    for cand in COMMON_TESSERACT_WINDOWS_PATHS:
        if os.path.isfile(cand):
            pytesseract.pytesseract.tesseract_cmd = cand
            return cand

    return None


def is_tesseract_available() -> bool:
    """Check whether Tesseract OCR is installed and accessible."""
    bin_path = resolve_tesseract_binary()
    if not bin_path:
        return False
    try:
        ver = pytesseract.get_tesseract_version()
        return bool(ver)
    except Exception:
        return False


def get_ocr_engine_info() -> Dict[str, Any]:
    """Return runtime metadata about the OCR engine."""
    bin_path = resolve_tesseract_binary()
    available = is_tesseract_available()
    version = None
    if available:
        try:
            version = str(pytesseract.get_tesseract_version())
        except Exception:
            version = "unknown"
    return {
        "engine": "tesseract",
        "available": available,
        "binary_path": bin_path,
        "version": version,
    }


def ocr_image(image_input: Union[Image.Image, str, bytes]) -> str:
    """
    Perform OCR on a PIL Image, file path, or raw image bytes.
    Returns extracted text, or raises RuntimeError if Tesseract is unavailable.
    """
    if not is_tesseract_available():
        raise RuntimeError("Tesseract OCR is not installed or not found on the system.")

    if isinstance(image_input, str):
        if not os.path.exists(image_input):
            raise FileNotFoundError(f"Image file not found: {image_input}")
        img = Image.open(image_input)
    elif isinstance(image_input, bytes):
        img = Image.open(io.BytesIO(image_input))
    elif isinstance(image_input, Image.Image):
        img = image_input
    else:
        raise TypeError(f"Unsupported image input type: {type(image_input)}")

    # Convert RGBA/P to RGB for clean OCR processing
    if img.mode not in ("L", "RGB"):
        img = img.convert("RGB")

    text = pytesseract.image_to_string(img)
    return text.strip()


def ocr_pymupdf_pixmap(pixmap: Any) -> str:
    """
    Perform OCR on a PyMuPDF Pixmap object.
    Converts pixmap to PIL Image before OCR.
    """
    img_bytes = pixmap.tobytes("png")
    img = Image.open(io.BytesIO(img_bytes))
    return ocr_image(img)

