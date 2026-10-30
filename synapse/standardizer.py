"""
synapse_poc/synapse/standardizer.py
Standardized parameter mapping and abnormality classification.
Maps verbatim lab observation names to canonical identifiers without altering original text.
"""

from typing import Optional
from synapse.schema import LabResult

PARAMETER_CANONICAL_MAP = {
    # Hematology / CBC
    "haemoglobin": "Hemoglobin",
    "hemoglobin": "Hemoglobin",
    "hb": "Hemoglobin",
    "hgb": "Hemoglobin",
    "rbc count": "RBC Count",
    "rbc": "RBC Count",
    "red blood cells": "RBC Count",
    "wbc count": "WBC Count",
    "wbc": "WBC Count",
    "total wbc count": "WBC Count",
    "total leukocyte count": "WBC Count",
    "tlc": "WBC Count",
    "platelet count": "Platelet Count",
    "platelets": "Platelet Count",
    "plt": "Platelet Count",
    "neutrophils": "Neutrophils",
    "lymphocytes": "Lymphocytes",
    "eosinophils": "Eosinophils",
    "monocytes": "Monocytes",
    "basophils": "Basophils",
    "mcv": "MCV",
    "mch": "MCH",
    "mchc": "MCHC",

    # Biochemistry
    "fasting glucose": "Fasting Glucose",
    "glucose - fasting": "Fasting Glucose",
    "blood sugar fasting": "Fasting Glucose",
    "post-prandial glucose": "Post-Prandial Glucose",
    "pp glucose": "Post-Prandial Glucose",
    "hba1c": "HbA1c",

    # Liver Function
    "total bilirubin": "Total Bilirubin",
    "direct bilirubin": "Direct Bilirubin",
    "indirect bilirubin": "Indirect Bilirubin",
    "alt": "ALT",
    "ast": "AST",
    "alkaline phosphatase": "Alkaline Phosphatase",
    "total protein": "Total Protein",
    "albumin": "Albumin",

    # Lipid Profile
    "total cholesterol": "Total Cholesterol",
    "cholesterol": "Total Cholesterol",
    "triglycerides": "Triglycerides",
    "hdl cholesterol": "HDL Cholesterol",
    "hdl": "HDL Cholesterol",
    "ldl cholesterol": "LDL Cholesterol",
    "ldl": "LDL Cholesterol",
    "vldl cholesterol": "VLDL Cholesterol",
    "vldl": "VLDL Cholesterol",
    "cholesterol : hdl ratio": "Cholesterol : HDL Ratio",

    # Renal Panel
    "urea": "Urea",
    "blood urea": "Urea",
    "creatinine": "Creatinine",
    "serum creatinine": "Creatinine",
    "uric acid": "Uric Acid",
    "sodium": "Sodium",
    "potassium": "Potassium",
    "chloride": "Chloride",
    "bicarbonate": "Bicarbonate",
    "egfr": "eGFR",

    # Thyroid Profile
    "t3": "T3",
    "total t3": "T3",
    "t4": "T4",
    "total t4": "T4",
    "tsh": "TSH",
    "thyroid stimulating hormone": "TSH",
}


def standardize_parameter_name(raw_name: str) -> Optional[str]:
    """
    Map raw verbatim test name to a standardized canonical name if known.
    Returns None if no confident mapping is found.
    """
    if not raw_name:
        return None
    normalized = raw_name.strip().lower()
    return PARAMETER_CANONICAL_MAP.get(normalized, None)


def classify_abnormality(res: LabResult) -> str:
    """
    Classify parameter according to reference range stated in source report:
    - 'below_range'
    - 'above_range'
    - 'within_range'
    - 'reference_range_unavailable'
    - 'requires_review'
    """
    # If extraction was not ok or has error/warning flags, mark for review
    has_review_condition = (
        res.extraction_status in ("needs_review", "unsupported")
        or res.result_value is None
        or any(f.severity in ("warning", "error") for f in res.review_flags)
    )

    if has_review_condition:
        return "requires_review"

    if res.reference_range_text is None:
        return "reference_range_unavailable"

    if res.flag == "low":
        return "below_range"
    elif res.flag == "high":
        return "above_range"
    elif res.flag == "normal":
        return "within_range"
    else:
        return "reference_range_unavailable"

