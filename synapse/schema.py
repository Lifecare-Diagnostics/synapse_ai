"""
synapse_poc/synapse/schema.py
Pydantic data models for structured diagnostic document extraction.
"""

from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ReviewFlag(BaseModel):
    """
    Represents a single review/flagging event for an extracted field or result.
    Used to distinguish between successfully extracted, needs-review, and missing/unsupported items.
    """
    field: str = Field(..., description="Name of the field or test being flagged")
    reason: str = Field(..., description="Human-readable reason for the review flag")
    severity: Literal["info", "warning", "error"] = Field("warning", description="Severity of the issue")


class MedicalHistoryEntry(BaseModel):
    """
    Structured medical history entry recorded for a patient.
    Factual record of conditions, procedures, or diagnoses from source documents.
    """
    entry_id: str = Field(..., description="Unique identifier for this history entry")
    condition_or_event: str = Field(..., description="Condition, diagnosis, or clinical event")
    entry_date: Optional[str] = Field(None, description="ISO date (YYYY-MM-DD) when condition was recorded or diagnosed")
    source: str = Field(..., description="Source document or reference where this history was recorded")
    notes: Optional[str] = Field(None, description="Factual notes from the source without AI interpretation")


class PatientDemographics(BaseModel):
    """
    Structured patient profile containing demographic details and medical history.
    Does NOT infer missing data.
    """
    patient_id: str = Field(..., description="Primary patient identifier (e.g., SYN-1001)")
    patient_name: str = Field(..., description="Full patient name as recorded")
    date_of_birth: Optional[str] = Field(None, description="ISO date (YYYY-MM-DD) if recorded; None if unavailable")
    age: Optional[int] = Field(None, description="Patient age at registration/most recent record")
    sex: Optional[str] = Field(None, description="Patient sex as recorded (e.g., Male, Female)")
    medical_history: List[MedicalHistoryEntry] = Field(default_factory=list, description="List of recorded medical history entries")


class ReportParameter(BaseModel):
    """
    Individual laboratory parameter associated with a specific report.
    Retains original verbatim name while providing standardized mapping.
    """
    parameter_id: str = Field(..., description="Unique identifier for this parameter instance")
    report_id: str = Field(..., description="Foreign key linking to parent PatientReport")
    patient_id: str = Field(..., description="Patient ID for direct longitudinal queries")
    original_name: str = Field(..., description="Verbatim test name as extracted from source")
    standardized_name: Optional[str] = Field(None, description="Canonical standardized test name if confidently mapped")
    result_value: Optional[float] = Field(None, description="Numeric result value")
    unit: Optional[str] = Field(None, description="Unit of measurement")
    reference_range_text: Optional[str] = Field(None, description="Verbatim reference range from report")
    reference_low: Optional[float] = Field(None, description="Lower bound of reference interval")
    reference_high: Optional[float] = Field(None, description="Upper bound of reference interval")
    clinical_flag: Literal["low", "normal", "high", "unknown"] = Field("unknown", description="Clinical interpretation flag")
    abnormality_category: Literal[
        "below_range", "within_range", "above_range", "reference_range_unavailable", "requires_review"
    ] = Field("reference_range_unavailable", description="Categorization against source reference range")
    extraction_status: Literal["ok", "needs_review", "unsupported"] = Field("ok", description="Status from extractor/reviewer")
    source_text: str = Field(..., description="Exact raw line from source")
    review_flags: List[ReviewFlag] = Field(default_factory=list, description="Per-parameter review flags")
    report_date: Optional[str] = Field(None, description="Date of the parent report (YYYY-MM-DD)")


class PatientReport(BaseModel):
    """
    Full metadata and record for a medical document stored in the Patient Digital Wallet.
    """
    report_id: str = Field(..., description="Unique report identifier")
    patient_id: str = Field(..., description="Unique patient identifier")
    report_date: Optional[str] = Field(None, description="Date report was performed/registered (YYYY-MM-DD)")
    date_label: Optional[str] = Field(None, description="Verbatim date label from report (e.g., Registered On)")
    report_category: str = Field("Other", description="Configurable category: CBC / Hematology, Biochemistry, etc.")
    original_filename: str = Field(..., description="Original filename of source document")
    file_format: str = Field(..., description="Format: txt, pdf, json, image, etc.")
    upload_datetime: str = Field(..., description="ISO datetime of document ingestion")
    extraction_status: Literal["success", "needs_review", "ocr_required", "failed"] = Field("success", description="Overall extraction outcome")
    review_status: Literal["clean", "needs_review", "unsupported_parameters"] = Field("clean", description="Overall review status")
    original_document_location: Optional[str] = Field(None, description="Path or URI to original document")
    content_hash: Optional[str] = Field(None, description="SHA-256 hash of raw content for duplicate detection")
    parameters: List[ReportParameter] = Field(default_factory=list, description="Extracted parameters linked to this report")
    key_text_sections: Dict[str, str] = Field(default_factory=dict, description="Unstructured narrative sections")
    document_level_flags: List[ReviewFlag] = Field(default_factory=list, description="Document-level review flags")
    validation_errors: List[str] = Field(default_factory=list, description="Validation errors encountered")


class Patient(BaseModel):
    """
    Complete patient entity combining demographics, medical history, and linked reports.
    """
    patient_id: str = Field(..., description="Unique patient identifier")
    demographics: PatientDemographics = Field(..., description="Structured patient demographics and history")
    reports: List[PatientReport] = Field(default_factory=list, description="All reports belonging to this patient")



class LabResult(BaseModel):
    """
    Represents an individual laboratory test observation.
    """
    test_name: str = Field(..., description="Standardized or extracted name of the lab test exactly as written")
    result_value: Optional[float] = Field(None, description="Extracted numerical result value")
    unit: Optional[str] = Field(None, description="Unit of measurement (e.g., g/dL, mg/dL)")
    reference_range_text: Optional[str] = Field(None, description="Verbatim reference range text from the report")
    reference_low: Optional[float] = Field(None, description="Lower bound of reference interval")
    reference_high: Optional[float] = Field(None, description="Upper bound of reference interval")
    flag: Literal["low", "normal", "high", "unknown"] = Field("unknown", description="Clinical interpretation flag")
    source_text: str = Field(..., description="Exact raw line from source document where this result was extracted")
    source_page: Optional[int] = Field(None, description="1-indexed page number where source line appeared")
    confidence: Optional[float] = Field(None, description="AI confidence score; None for rule-based extraction")
    review_flags: List["ReviewFlag"] = Field(default_factory=list, description="Per-result review flags for extraction issues")
    extraction_status: Literal["ok", "needs_review", "unsupported"] = Field("ok", description="Extraction status: ok, needs_review, or unsupported")


class ExtractedDocument(BaseModel):
    """
    Represents the full extracted structure of an ingested medical document.
    """
    document_id: str = Field(..., description="Unique identifier for the document record")
    source_file: str = Field(..., description="Filename or path of the input source file")
    document_type: str = Field(..., description="Category: lab report, radiology, ultrasound, clinical note, prescription, or mixed")
    patient_id: Optional[str] = Field(None, description="Synthetic patient identifier (e.g., SYN-1001)")
    patient_name: Optional[str] = Field(None, description="Synthetic patient full name")
    document_date: Optional[str] = Field(None, description="ISO format date (YYYY-MM-DD)")
    date_label: Optional[str] = Field(None, description="Verbatim date label as written in the report (e.g., Registered On, Date of Report)")
    lab_results: List[LabResult] = Field(default_factory=list, description="Structured lab observations (only populated for lab-type documents)")
    key_text_sections: Dict[str, str] = Field(default_factory=dict, description="Raw text mapped by section heading for unstructured documents")
    extraction_method: str = Field("rule_based", description="Method used for extraction (e.g., rule_based, llm_prompt)")
    validation_errors: List[str] = Field(default_factory=list, description="List of validation errors or missing required fields encountered")
    review_flags: List["ReviewFlag"] = Field(default_factory=list, description="Document-level review flags")
    extraction_summary: Dict[str, int] = Field(default_factory=dict, description="Count of ok/needs_review/unsupported results")


ReviewFlag.model_rebuild()
MedicalHistoryEntry.model_rebuild()
PatientDemographics.model_rebuild()
ReportParameter.model_rebuild()
PatientReport.model_rebuild()
Patient.model_rebuild()
LabResult.model_rebuild()
ExtractedDocument.model_rebuild()
