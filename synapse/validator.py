"""
synapse_poc/synapse/validator.py
Validation, unit normalisation, and flag calculation for ExtractedDocument.
"""

from datetime import datetime
import re
from typing import List
from synapse.schema import ExtractedDocument, LabResult


class DocumentValidator:
    """
    Validates an ExtractedDocument against clinical and schema constraints,
    normalises units, and calculates clinical flags.
    Never crashes; all issues are collected into document.validation_errors.
    """

    UNIT_NORMALISATIONS = {
        "gm/dl": "g/dL",
        "gm/dL": "g/dL",
        "g/dl": "g/dL",
        "mg/dl": "mg/dL",
        "meq/l": "mEq/L",
        "uiu/ml": "uIU/mL",
        "ng/dl": "ng/dL",
        "ug/dl": "ug/dL",
    }

    def validate(self, doc: ExtractedDocument) -> ExtractedDocument:
        """
        Validate document, mutate flags/units in place, and return the document.
        """
        errors: List[str] = list(doc.validation_errors)

        # 1. Required fields check
        if not doc.document_id:
            errors.append("Missing required field: document_id")
        if not doc.source_file:
            errors.append("Missing required field: source_file")
        if not doc.document_type:
            errors.append("Missing required field: document_type")
        if not doc.patient_id:
            errors.append("Missing required field: patient_id")
        if not doc.document_date:
            errors.append("Missing required field: document_date")
        else:
            # 2. ISO date validation
            if not self._is_valid_iso_date(doc.document_date):
                errors.append(f"Invalid ISO date format: '{doc.document_date}' (expected YYYY-MM-DD)")

        # 3. Lab results validation and flag calculation
        for res in doc.lab_results:
            # Check result_value
            if res.result_value is None:
                errors.append(f"Missing numeric result value for test: {res.test_name}")
            elif not isinstance(res.result_value, (int, float)):
                errors.append(f"Invalid non-numeric result value for test: {res.test_name}")

            # Unit normalisation & missing unit check
            if res.unit:
                unit_lower = res.unit.strip().lower()
                for key, val in self.UNIT_NORMALISATIONS.items():
                    if unit_lower == key.lower():
                        res.unit = val
                        break
            else:
                # Some tests like ratios legitimately have no unit
                if "ratio" not in res.test_name.lower():
                    errors.append(f"Missing unit for test: {res.test_name}")

            # Calculate clinical flag against reference range
            res.flag = self._calculate_flag(res)

        doc.validation_errors = errors
        return doc

    def _is_valid_iso_date(self, date_str: str) -> bool:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            return False
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    def _calculate_flag(self, res: LabResult) -> str:
        """
        Compute clinical flag ('low', 'normal', 'high', 'unknown') based on:
        - 'Up to X': low=None, high=X inclusive (value > high -> high, else normal)
        - 'Less than X': low=None, high=X exclusive (value >= high -> high, else normal)
        - 'low - high': value < low -> low, value > high -> high, else normal
        - None / no range: 'unknown' (rule: never infer flag from Comment line)
        """
        if res.result_value is None or not res.reference_range_text:
            return "unknown"

        ref_lower = res.reference_range_text.lower()
        val = res.result_value

        if "up to" in ref_lower:
            if res.reference_high is not None:
                return "high" if val > res.reference_high else "normal"
            return "unknown"

        if "less than" in ref_lower:
            if res.reference_high is not None:
                return "high" if val >= res.reference_high else "normal"
            return "unknown"

        if res.reference_low is not None and res.reference_high is not None:
            if val < res.reference_low:
                return "low"
            elif val > res.reference_high:
                return "high"
            else:
                return "normal"

        return "unknown"
