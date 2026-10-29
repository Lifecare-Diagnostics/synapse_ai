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
