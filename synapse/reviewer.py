"""
synapse_poc/synapse/reviewer.py
Post-extraction review and flagging module.

Analyses a validated ExtractedDocument and attaches structured ReviewFlag objects
for each condition requiring human attention. Does NOT modify clinical values.
All determinations are rule-based; no model probabilities are used or implied.
"""

import re
from typing import Set
from synapse.schema import ExtractedDocument, ReviewFlag

# ---------------------------------------------------------------------------
# Known test name registry
# Tests recognised by the rule-based extractor. Any extracted test_name not
# in this set will be flagged as "unrecognised".
# ---------------------------------------------------------------------------
KNOWN_TEST_NAMES: Set[str] = {
    # CBC
    "Haemoglobin", "RBC Count", "WBC Count", "Platelet Count",
    "Neutrophils", "Lymphocytes", "Eosinophils", "Monocytes",
    # Biochemistry
    "Fasting Glucose", "Post-Prandial Glucose", "HbA1c",
    "Total Bilirubin", "Direct Bilirubin", "Indirect Bilirubin",
    "ALT", "AST", "Alkaline Phosphatase", "Total Protein", "Albumin",
    # Lipid profile
    "Total Cholesterol", "Triglycerides", "HDL Cholesterol",
    "LDL Cholesterol", "VLDL Cholesterol", "Cholesterol : HDL Ratio",
    # Renal
    "Urea", "Creatinine", "Uric Acid", "Sodium", "Potassium",
    "Chloride", "Bicarbonate", "eGFR",
    # Thyroid
    "T3", "T4", "TSH",
}

# Regex patterns that signal a value is likely malformed or ambiguous
_AMBIGUOUS_VALUE_PATTERNS = [
    re.compile(r"[<>]\s*\d+"),           # e.g. ">10" or "<5" — not a plain number
    re.compile(r"\d+\s*-\s*\d+"),         # e.g. "10-20" parsed as single value
]


class ExtractionReviewer:
    """
    Attaches ReviewFlag objects to an already-validated ExtractedDocument.

    Rules applied (in order):
    1. Unrecognised test name → severity=warning, extraction_status=unsupported
    2. Missing result value   → severity=error,   extraction_status=needs_review
    3. Missing unit (non-ratio) → severity=warning, extraction_status=needs_review
    4. Missing reference range → severity=info,    extraction_status=ok  (informational only)
    5. Value cannot be validated against reference range (flag remains unknown after range present) → severity=warning
    6. Missing document date  → severity=error,    document-level flag
    7. Missing patient_id     → severity=warning,  document-level flag
    8. Ambiguous source text  → severity=warning,  extraction_status=needs_review

    Existing validation_errors list is NOT modified; ReviewFlags are additive.
    """

    def review(self, doc: ExtractedDocument) -> ExtractedDocument:
        """
        Attach review flags and compute extraction_summary. Returns the document.
        """
        doc_flags = list(doc.review_flags)

        # Document-level flags
        if not doc.document_date:
            doc_flags.append(ReviewFlag(
                field="document_date",
                reason="Document date is missing; cannot verify report currency or match to patient timeline.",
                severity="error",
            ))

        if not doc.patient_id:
            doc_flags.append(ReviewFlag(
                field="patient_id",
                reason="Patient ID is missing; result cannot be linked to a patient record.",
                severity="warning",
            ))

        # Per-result flags
        ok_count = 0
        review_count = 0
        unsupported_count = 0

        for result in doc.lab_results:
            result_flags = list(result.review_flags)
            status = "ok"

            # Rule 1: Unrecognised test name
            if result.test_name not in KNOWN_TEST_NAMES:
                result_flags.append(ReviewFlag(
                    field="test_name",
                    reason=f"Test name '{result.test_name}' is not in the recognised test registry. "
                           "Verify spelling, mapping, or add to KNOWN_TEST_NAMES.",
                    severity="warning",
                ))
                status = "unsupported"

            # Rule 2: Missing result value
            if result.result_value is None:
                result_flags.append(ReviewFlag(
                    field="result_value",
                    reason=f"No numeric result value could be extracted for '{result.test_name}'. "
                           "Manual review required.",
                    severity="error",
                ))
                if status == "ok":
                    status = "needs_review"

            # Rule 3: Missing unit (non-ratio tests)
            if result.unit is None and "ratio" not in result.test_name.lower():
                result_flags.append(ReviewFlag(
                    field="unit",
                    reason=f"Unit of measurement is absent for '{result.test_name}'. "
                           "Cannot confirm whether value is in expected scale.",
                    severity="warning",
                ))
                if status == "ok":
                    status = "needs_review"

            # Rule 4: Missing reference range (informational)
            if result.reference_range_text is None and result.result_value is not None:
                result_flags.append(ReviewFlag(
                    field="reference_range_text",
                    reason=f"No reference range available for '{result.test_name}'. "
                           "Clinical flag will remain 'unknown'.",
                    severity="info",
                ))

            # Rule 5: Value present and reference range present but flag is still unknown
            if (result.result_value is not None
                    and result.reference_range_text is not None
                    and result.flag == "unknown"):
                result_flags.append(ReviewFlag(
                    field="flag",
                    reason=f"Reference range text is present ('{result.reference_range_text}') "
                           f"but could not be parsed to compute a clinical flag for '{result.test_name}'. "
                           "Verify format.",
                    severity="warning",
                ))
                if status == "ok":
                    status = "needs_review"

            # Rule 8: Ambiguous source text heuristic
            src = result.source_text or ""
            if _looks_ambiguous(src):
                result_flags.append(ReviewFlag(
                    field="source_text",
                    reason=f"Source text for '{result.test_name}' contains characters that suggest "
                           "a range or non-numeric value was parsed as a single numeric result.",
                    severity="warning",
                ))
                if status == "ok":
                    status = "needs_review"

            result.review_flags = result_flags
            result.extraction_status = status

            if status == "ok":
                ok_count += 1
            elif status == "needs_review":
                review_count += 1
            else:
                unsupported_count += 1

        doc.review_flags = doc_flags
        doc.extraction_summary = {
            "ok": ok_count,
            "needs_review": review_count,
            "unsupported": unsupported_count,
        }
        return doc


def _looks_ambiguous(source_text: str) -> bool:
    """
    Heuristic: returns True if the source text looks like it contains a range or
    inequality that may have been misread as a plain numeric value.
    Only checks the value portion after the colon if present.
    """
    # Isolate the value part (after the first colon, before any parenthetical reference range)
    # e.g. "Fasting Glucose: 95 mg/dL (Reference 70 - 110)" -> "95 mg/dL"
    if ":" in source_text:
        after_colon = source_text.split(":", 1)[1].strip()
        # Strip parenthetical content (reference ranges) to avoid false positives
        value_part = re.sub(r"\(.*?\)", "", after_colon).strip()
    else:
        value_part = source_text

    # A plain number or "number unit" is fine
    if re.match(r"^[0-9]+\.?[0-9]*\s*[A-Za-z%^/]*$", value_part):
        return False

    for pattern in _AMBIGUOUS_VALUE_PATTERNS:
        if pattern.search(value_part):
            return True
    return False
