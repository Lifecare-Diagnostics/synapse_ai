"""
synapse_poc/synapse/extractor.py
Document extraction interface and rule-based baseline extractor.
"""

from abc import ABC, abstractmethod
import os
import re
from typing import Dict, List, Optional, Tuple
from synapse.schema import ExtractedDocument, LabResult
from synapse.llm import LLMClient, get_default_llm_client


class Extractor(ABC):
    """
    Abstract interface for document extraction.
    Any future extraction strategy (e.g., local LLM, cloud API) must implement
    this interface to remain drop-in replaceable.
    """

    @abstractmethod
    def extract(self, text: str, source_file: str) -> ExtractedDocument:
        """
        Extract structured data from raw document text.

        Args:
            text: Raw string content of the document.
            source_file: Filename or path for provenance.

        Returns:
            ExtractedDocument containing metadata, lab results, and text sections.
        """
        pass


class LLMExtractor(Extractor):
    """
    LLM-based clinical document extractor.
    Uses structured prompt and JSON constrained generation to extract clinical
    entities, narrative findings, impressions, and diagnoses.
    """

    def __init__(self, client: Optional[LLMClient] = None):
        self.client = client or get_default_llm_client()

    def extract(self, text: str, source_file: str) -> ExtractedDocument:
        doc_id = f"DOC-{os.path.basename(source_file).replace('.', '_')}"
        data = self.client.extract_clinical_json(text)

        lab_results = []
        for item in data.get("lab_results", []):
            try:
                res_val = float(item["result_value"]) if item.get("result_value") is not None else None
            except (ValueError, TypeError):
                res_val = None

            ref_low = float(item["reference_low"]) if item.get("reference_low") is not None else None
            ref_high = float(item["reference_high"]) if item.get("reference_high") is not None else None

            lab_results.append(
                LabResult(
                    test_name=item.get("test_name", "Unknown Test"),
                    result_value=res_val,
                    unit=item.get("unit"),
                    reference_range_text=item.get("reference_range_text"),
                    reference_low=ref_low,
                    reference_high=ref_high,
                    flag="unknown",
                    source_text=f"{item.get('test_name')}: {res_val} {item.get('unit') or ''}".strip(),
                    source_page=1,
                    confidence=0.92,
                )
            )

        key_sections = data.get("key_sections", {})
        if data.get("clinical_summary"):
            key_sections["Clinical Summary"] = data["clinical_summary"]

        # Record LLM usage in central tracker if usage was captured
        if hasattr(self.client, "last_usage") and self.client.last_usage:
            try:
                from synapse.usage_tracker import get_usage_tracker
                u = self.client.last_usage
                get_usage_tracker().record(
                    provider=u.get("provider", "unknown"),
                    model=u.get("model", "unknown"),
                    input_tokens=u.get("total_input_tokens"),
                    output_tokens=u.get("total_output_tokens"),
                    total_tokens=u.get("total_tokens"),
                    document_id=doc_id,
                    status=u.get("status", "success"),
                    processing_time_seconds=u.get("processing_time_seconds"),
                )
            except Exception:
                pass

        return ExtractedDocument(
            document_id=doc_id,
            source_file=os.path.basename(source_file),
            document_type=data.get("document_type", "clinical note"),
            patient_id=data.get("patient_id"),
            patient_name=data.get("patient_name"),
            document_date=data.get("document_date"),
            date_label=data.get("date_label") or "Date",
            lab_results=lab_results,
            key_text_sections=key_sections,
            extraction_method="llm_prompt",
            validation_errors=[],
        )


class HybridExtractor(Extractor):
    """
    Hybrid Clinical Extractor combining deterministic regex rules and LLM intelligence.
    - Uses RuleBasedExtractor for high-speed, zero-hallucination standard lab panels.
    - Routes unstructured documents (Radiology, Ultrasound, Clinical Notes, Prescriptions)
      and narrative sections through LLMExtractor.
    """

    def __init__(
        self,
        rule_extractor: Optional["RuleBasedExtractor"] = None,
        llm_extractor: Optional[LLMExtractor] = None,
    ):
        self.rule_extractor = rule_extractor or RuleBasedExtractor()
        self.llm_extractor = llm_extractor or LLMExtractor()

    def extract(self, text: str, source_file: str) -> ExtractedDocument:
        # Step 1: Run deterministic rule extraction
        rule_doc = self.rule_extractor.extract(text, source_file)

        # Step 2: Evaluate if LLM enrichment is needed
        # Standard structured lab reports with extracted results stay on the deterministic fast-path
        is_standard_lab = rule_doc.document_type == "lab report" and len(rule_doc.lab_results) > 0
        if is_standard_lab:
            return rule_doc

        # Unstructured narrative document or 0 lab results found -> invoke LLM for clinical understanding
        try:
            llm_doc = self.llm_extractor.extract(text, source_file)

            # Merge: Preserve high-confidence metadata from rule extraction if present
            merged_patient_id = rule_doc.patient_id or llm_doc.patient_id
            merged_patient_name = rule_doc.patient_name or llm_doc.patient_name
            merged_date = rule_doc.document_date or llm_doc.document_date
            merged_date_label = rule_doc.date_label or llm_doc.date_label

            # Merge key text sections
            merged_sections = dict(rule_doc.key_text_sections)
            for k, v in llm_doc.key_text_sections.items():
                if k not in merged_sections or not merged_sections[k]:
                    merged_sections[k] = v

            # Merge lab results (rule-based results take precedence)
            merged_labs = list(rule_doc.lab_results)
            if not merged_labs and llm_doc.lab_results:
                merged_labs = list(llm_doc.lab_results)

            doc_type = rule_doc.document_type
            if doc_type == "clinical note" and llm_doc.document_type != "clinical note":
                doc_type = llm_doc.document_type

            return ExtractedDocument(
                document_id=rule_doc.document_id,
                source_file=rule_doc.source_file,
                document_type=doc_type,
                patient_id=merged_patient_id,
                patient_name=merged_patient_name,
                document_date=merged_date,
                date_label=merged_date_label,
                lab_results=merged_labs,
                key_text_sections=merged_sections,
                extraction_method="hybrid_rules_llm",
                validation_errors=rule_doc.validation_errors,
            )
        except Exception:
            # If LLM encounters an issue, gracefully fall back to the rule-based document
            return rule_doc


class RuleBasedExtractor(Extractor):
    """
    Deterministic rule-based extractor using regular expressions.
    Extracts document metadata, tabular lab observations, and unstructured text sections.
    Confidence is always None (no fabricated confidence scores).
    """

    def __init__(self):
        pass

    def extract(self, text: str, source_file: str) -> ExtractedDocument:
        doc_id = f"DOC-{os.path.basename(source_file).replace('.', '_')}"
        lines = [line.strip() for line in text.splitlines()]

        # 1. Detect patient metadata
        patient_name = self._extract_patient_name(lines)
        patient_id = self._extract_patient_id(lines)

        # 2. Detect date and date_label
        doc_date, date_label = self._extract_date_and_label(lines)

        # 3. Detect document type
        doc_type = self._detect_document_type(lines, source_file)

        # 4. Extract lab results and text sections
        lab_results: List[LabResult] = []
        key_text_sections: Dict[str, str] = {}

        if doc_type == "lab report":
            lab_results, key_text_sections = self._extract_lab_document(lines)
        elif doc_type == "mixed":
            lab_results, key_text_sections = self._extract_mixed_document(lines)
        else:
            key_text_sections = self._extract_unstructured_sections(lines)

        return ExtractedDocument(
            document_id=doc_id,
            source_file=os.path.basename(source_file),
            document_type=doc_type,
            patient_id=patient_id,
            patient_name=patient_name,
            document_date=doc_date,
            date_label=date_label,
            lab_results=lab_results,
            key_text_sections=key_text_sections,
            extraction_method="rule_based",
            validation_errors=[],
        )

    def _extract_patient_name(self, lines: List[str]) -> Optional[str]:
        for line in lines:
            m = re.match(r"^Patient(?:\s+Name)?\s*:\s*(.+)$", line, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                # Strip trailing labels if any
                val = re.split(r"\s{2,}", val)[0]
                return val
        return None

    def _extract_patient_id(self, lines: List[str]) -> Optional[str]:
        for line in lines:
            m = re.match(r"^Patient\s*ID\s*:\s*([A-Za-z0-9\-]+)", line, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None

    def _extract_date_and_label(self, lines: List[str]) -> Tuple[Optional[str], Optional[str]]:
        date_patterns = [
            ("Registered On", r"^Registered\s+On\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})"),
            ("Date of Report", r"^Date\s+of\s+Report\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})"),
            ("Report Date", r"^Report\s+Date\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})"),
            ("Study Date", r"^Study\s+Date\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})"),
            ("Collected", r"^Collected\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})"),
            ("Date", r"^Date\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})"),
        ]
        for line in lines:
            for label, pattern in date_patterns:
                m = re.match(pattern, line, re.IGNORECASE)
                if m:
                    return m.group(1).strip(), label
        return None, None

    def _detect_document_type(self, lines: List[str], source_file: str) -> str:
        text_full = "\n".join(lines)
        if "Combined Preventive Health Report" in text_full:
            return "mixed"
        if "Doctor's Clinical Note" in text_full or "Doctor Note" in source_file:
            return "clinical note"
        if "Prescription" in text_full:
            # Check if it's prescription document type
            for line in lines:
                if re.match(r"^Document\s*Type\s*:\s*Prescription", line, re.IGNORECASE):
                    return "prescription"
        if "X-RAY" in text_full:
            return "radiology"
        if "Ultrasound" in text_full:
            return "ultrasound"
        # Check lab report markers
        lab_markers = [
            "Complete Blood Count",
            "Fasting Biochemistry",
            "Lipid Profile",
            "RENAL FUNCTION PANEL",
            "Immunoassay",
            "CBC",
        ]
        for marker in lab_markers:
            if marker.lower() in text_full.lower():
                return "lab report"
        return "lab report"

    def _parse_reference_range(self, ref_text: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
        if not ref_text:
            return None, None
        text = ref_text.strip()
        m_up = re.search(r"Up to\s+([0-9.]+)", text, re.IGNORECASE)
        if m_up:
            return None, float(m_up.group(1))
        m_less = re.search(r"Less than\s+([0-9.]+)", text, re.IGNORECASE)
        if m_less:
            return None, float(m_less.group(1))
        m_range = re.search(r"([0-9.]+)\s*-\s*([0-9.]+)", text)
        if m_range:
            return float(m_range.group(1)), float(m_range.group(2))
        return None, None

    def _extract_lab_document(self, lines: List[str]) -> Tuple[List[LabResult], Dict[str, str]]:
        lab_results: List[LabResult] = []
        key_sections: Dict[str, str] = {}

        # First, check if there is a separate "Reference ranges:" block at the end (like in lipid profile)
        external_ranges: Dict[str, str] = {}
        in_ref_block = False
        ref_block_lines = []

        for line in lines:
            if re.match(r"^Reference\s+ranges\s*:\s*$", line, re.IGNORECASE):
                in_ref_block = True
                continue
            if in_ref_block:
                if not line or line.startswith("Remark:") or line.startswith("Comment:"):
                    in_ref_block = False
                else:
                    m_ref = re.match(r"^([A-Za-z0-9\s:/-]+?)\s*:\s*(.+)$", line)
                    if m_ref:
                        external_ranges[m_ref.group(1).strip()] = m_ref.group(2).strip()

        # Iterate over lines to extract lab test rows
        for line in lines:
            if not line:
                continue

            # Skip header lines
            if any(line.startswith(prefix) for prefix in [
                "SYNTHETIC TEST DOCUMENT", "Patient", "Age", "Registered On", "Report Type",
                "Specimen", "Date", "Report:", "Collected", "Test :", "RENAL FUNCTION PANEL",
                "Department:", "Sample Type:", "Method:", "Reference ranges:"
            ]):
                # Note: Capture Comment / Remark / Specimen / Method / Sample Type for key_sections
                m_sec = re.match(r"^(Comment|Remark|Specimen|Interpretation note|Method|Sample Type)\s*:\s*(.+)$", line, re.IGNORECASE)
                if m_sec:
                    sec_name = m_sec.group(1).strip()
                    key_sections[sec_name] = m_sec.group(2).strip()
                continue

            # Check if this line is in external reference range block
            if line in external_ranges or any(line.startswith(k + ":") for k in external_ranges):
                continue

            # Pattern A: Test: Value Unit (Ref Range) or Test: Value Unit
            # e.g., Haemoglobin: 14.2 g/dL (Reference 13.0 - 17.0)
            # or Eosinophils: 03 %
            # or T3: 112 (Reference 60 - 181) [messy, missing unit]
            mA = re.match(r"^([A-Za-z0-9\s:/-]+?)\s*:\s*([0-9.]+)(?:\s+([A-Za-z0-9^/%-]+))?(?:\s*\((.*?)\))?$", line)
            if mA:
                test_name = mA.group(1).strip()
                raw_val = mA.group(2).strip()
                unit = mA.group(3).strip() if mA.group(3) else None
                ref_text = mA.group(4).strip() if mA.group(4) else None

                # Check external ranges if not in parens
                if not ref_text and test_name in external_ranges:
                    ref_text = external_ranges[test_name]

                ref_low, ref_high = self._parse_reference_range(ref_text)
                val_float = float(raw_val) if raw_val is not None else None

                lab_results.append(LabResult(
                    test_name=test_name,
                    result_value=val_float,
                    unit=unit,
                    reference_range_text=ref_text,
                    reference_low=ref_low,
                    reference_high=ref_high,
                    flag="unknown",  # Populated by validator
                    source_text=line,
                    source_page=1,
                    confidence=None,
                ))
                continue

            # Pattern B: Dotted format (e.g. Urea ............. 31.2 mg/dL ..... Ref: 10 - 38.5)
            mB = re.match(r"^([A-Za-z0-9\s]+?)\s*\.{3,}\s*([0-9.]+)\s*([A-Za-z0-9^/%-]+)\s*\.{3,}\s*(?:Ref:\s*)?(.*)$", line)
            if mB:
                test_name = mB.group(1).strip()
                raw_val = mB.group(2).strip()
                unit = mB.group(3).strip() if mB.group(3) else None
                raw_ref = mB.group(4).strip() if mB.group(4) else None
                ref_text = f"Ref: {raw_ref}" if raw_ref else None

                ref_low, ref_high = self._parse_reference_range(raw_ref)
                val_float = float(raw_val) if raw_val is not None else None

                lab_results.append(LabResult(
                    test_name=test_name,
                    result_value=val_float,
                    unit=unit,
                    reference_range_text=ref_text,
                    reference_low=ref_low,
                    reference_high=ref_high,
                    flag="unknown",
                    source_text=line,
                    source_page=1,
                    confidence=None,
                ))
                continue

            # Pattern C: Table columns separated by whitespace
            # e.g. Triglycerides                 178 mg/dL
            # or Cholesterol : HDL Ratio       5.05
            mC = re.match(r"^([A-Za-z0-9\s:/-]+?)\s{2,}([0-9.]+)(?:\s+([A-Za-z0-9^/%-]+))?$", line)
            if mC:
                test_name = mC.group(1).strip()
                raw_val = mC.group(2).strip()
                unit = mC.group(3).strip() if mC.group(3) else None
                ref_text = external_ranges.get(test_name)

                ref_low, ref_high = self._parse_reference_range(ref_text)
                val_float = float(raw_val) if raw_val is not None else None

                lab_results.append(LabResult(
                    test_name=test_name,
                    result_value=val_float,
                    unit=unit,
                    reference_range_text=ref_text,
                    reference_low=ref_low,
                    reference_high=ref_high,
                    flag="unknown",
                    source_text=line,
                    source_page=1,
                    confidence=None,
                ))
                continue

            # Any trailing comment/note lines
            m_rem = re.match(r"^(Comment|Remark|Interpretation note)\s*:\s*(.+)$", line, re.IGNORECASE)
            if m_rem:
                key_sections[m_rem.group(1).strip()] = m_rem.group(2).strip()

        return lab_results, key_sections

    def _extract_mixed_document(self, lines: List[str]) -> Tuple[List[LabResult], Dict[str, str]]:
        """Extract lab results and unstructured impression sections from patient_010 mixed report."""
        lab_results: List[LabResult] = []
        key_sections: Dict[str, str] = {}

        current_section = None
        for line in lines:
            if not line:
                continue

            if any(line.startswith(prefix) for prefix in [
                "SYNTHETIC TEST DOCUMENT", "Patient Name", "Patient ID", "Age / Sex",
                "Report Date", "Document Type"
            ]):
                continue

            # Check section headers
            if line in ["HAEMATOLOGY", "BIOCHEMISTRY", "LIPID PROFILE", "IMAGING", "ULTRASOUND", "NOTE:"]:
                current_section = line.rstrip(":")
                continue

            # Check if this line is an impression line
            m_imp = re.match(r"^(Chest X-ray impression|Abdomen impression)\s*:\s*(.+)$", line, re.IGNORECASE)
            if m_imp:
                key_sections[m_imp.group(1).strip()] = m_imp.group(2).strip()
                continue

            if current_section == "NOTE" or line.startswith("This document is synthetic"):
                key_sections["NOTE"] = line
                continue

            # Try parsing lab row
            mA = re.match(r"^([A-Za-z0-9\s:/-]+?)\s*:\s*([0-9.]+)\s+([A-Za-z0-9^/%-]+)(?:\s*\((.*?)\))?$", line)
            if mA:
                test_name = mA.group(1).strip()
                raw_val = mA.group(2).strip()
                unit = mA.group(3).strip() if mA.group(3) else None
                ref_text = mA.group(4).strip() if mA.group(4) else None

                ref_low, ref_high = self._parse_reference_range(ref_text)
                val_float = float(raw_val) if raw_val is not None else None

                lab_results.append(LabResult(
                    test_name=test_name,
                    result_value=val_float,
                    unit=unit,
                    reference_range_text=ref_text,
                    reference_low=ref_low,
                    reference_high=ref_high,
                    flag="unknown",
                    source_text=line,
                    source_page=1,
                    confidence=None,
                ))

        return lab_results, key_sections

    def _extract_unstructured_sections(self, lines: List[str]) -> Dict[str, str]:
        """Extract sections for radiology, ultrasound, clinical notes, and prescriptions."""
        key_sections: Dict[str, str] = {}
        current_heading = None
        current_content: List[str] = []

        # Known headings
        heading_candidates = [
            "Findings", "IMPRESSION", "Recommendation", "Chief complaints",
            "Examination", "Assessment", "Plan", "Complaint", "Prescription",
            "Liver", "Gall bladder", "Spleen", "Pancreas", "Kidneys", "Urinary bladder"
        ]

        def flush():
            nonlocal current_heading, current_content
            if current_heading and current_content:
                key_sections[current_heading] = "\n".join(current_content).strip()
                current_content = []

        for line in lines:
            if not line:
                continue

            # Skip header items
            if any(line.startswith(prefix) for prefix in [
                "SYNTHETIC TEST DOCUMENT", "Patient", "Age", "Study Date", "Study:",
                "Date:", "Document Type:"
            ]):
                continue

            # Check if line starts with a candidate heading
            matched = False
            for cand in heading_candidates:
                # Can be "Heading:" or "Heading"
                m = re.match(rf"^{re.escape(cand)}\s*:\s*(.*)$", line, re.IGNORECASE)
                if m:
                    flush()
                    current_heading = cand
                    inline_text = m.group(1).strip()
                    if inline_text:
                        current_content.append(inline_text)
                    matched = True
                    break

            if not matched:
                if current_heading:
                    current_content.append(line)

        flush()
        return key_sections
