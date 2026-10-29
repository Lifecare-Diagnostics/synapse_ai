# Synapse AI — Structured Document Schema Specification

This document defines the Pydantic schema used by Synapse AI for structured extraction from clinical and diagnostic documents.

---

## 1. Input Dataset Inventory (10 Synthetic Test Files)

All test documents are located in `lifecare_ai_poc_phase3_input/input/`. All files carry synthetic disclaimers (`SYNTHETIC TEST DOCUMENT — NOT REAL PATIENT DATA`).

| File | Document Type | Patient ID | Patient Name | Date Found | Date Label | Section Headings / Key Content Labels |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `patient_001_cbc.txt` | lab report | SYN-1001 | Rohan Example | 2026-04-03 | Registered On | Patient Name, Patient ID, Age / Sex, Registered On, Report Type, Specimen Type, Haemoglobin, RBC, WBC, Platelets, Differential, Comment |
| `patient_002_biochemistry.txt` | lab report | SYN-1002 | Meera Sample | 2026-04-07 | Date | Patient, Patient ID, Age/Sex, Date, Report, Fasting Glucose, Urea, Creatinine, Electrolytes, Specimen |
| `patient_003_lipid_profile.txt` | lab report | SYN-1003 | Arjun Fiction | 2026-04-10 | Collected | Patient Name, Patient ID, Age / Sex, Collected, Test, Specimen, Lipids Table, Reference ranges, Remark |
| `patient_004_renal_function.txt` | lab report | SYN-1004 | Kavya Placeholder | 2026-04-12 | Date of Report | Patient ID, Patient Name, Age, Sex, Date of Report, RENAL FUNCTION PANEL, Comment |
| `patient_005_thyroid.txt` | lab report | SYN-1005 | Isha Testerson | 2026-04-15 | Report Date | Patient, Patient ID, Age/Sex, Report Date, Department, T3, T4, TSH, Sample Type, Method, Interpretation note |
| `patient_006_xray_chest.txt` | radiology | SYN-1006 | Dev Demo | 2026-04-18 | Study Date | Patient Name, Patient ID, Age / Sex, Study Date, Study, Findings, IMPRESSION, Recommendation |
| `patient_007_ultrasound.txt` | ultrasound | SYN-1007 | Nisha Example | 2026-04-21 | Study Date | Patient, Patient ID, Age/Sex, Study Date, Study, Organ findings (Liver, Gall bladder, Spleen, etc.), IMPRESSION |
| `patient_008_doctor_note.txt` | clinical note | SYN-1008 | Sameer Mock | 2026-04-25 | Date | Patient ID, Patient Name, Date, Document Type, Chief complaints, Examination, Assessment, Plan |
| `patient_009_prescription.txt` | prescription | SYN-1009 | Tara Placeholder | 2026-04-28 | Date | Patient, Patient ID, Date, Document Type, Complaint, Prescription, Advice |
| `patient_010_mixed_report.txt` | mixed | SYN-1010 | Vikram Fictional | 2026-05-02 | Report Date | Patient Name, Patient ID, Age / Sex, Report Date, Document Type, HAEMATOLOGY, BIOCHEMISTRY, LIPID PROFILE, IMAGING, ULTRASOUND, NOTE |

---

## 2. Pydantic Schema (`synapse_poc/synapse/schema.py`)

```python
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field

class LabResult(BaseModel):
    test_name: str
    result_value: Optional[float] = None
    unit: Optional[str] = None
    reference_range_text: Optional[str] = None
    reference_low: Optional[float] = None
    reference_high: Optional[float] = None
    flag: Literal["low", "normal", "high", "unknown"] = "unknown"
    source_text: str
    source_page: Optional[int] = None
    confidence: Optional[float] = None

class ExtractedDocument(BaseModel):
    document_id: str
    source_file: str
    document_type: str
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None
    document_date: Optional[str] = None
    date_label: Optional[str] = None
    lab_results: List[LabResult] = Field(default_factory=list)
    key_text_sections: Dict[str, str] = Field(default_factory=dict)
    extraction_method: str = "rule_based"
    validation_errors: List[str] = Field(default_factory=list)
```

---

## 3. Plain Language Field Explanations

### `ExtractedDocument` (Top-Level Container)

1. **`document_id`** (Text, required): A unique tracking code for this extraction record (e.g., `DOC-SYN-1001-20260403`).
2. **`source_file`** (Text, required): The filename or path of the ingested file (e.g., `patient_001_cbc.txt`), ensuring full provenance.
3. **`document_type`** (Text, required): The classification of the document:
   - `lab report` (CBC, Biochemistry, Lipid Profile, Renal Function, Thyroid)
   - `radiology` (X-Ray)
   - `ultrasound` (Sonography)
   - `clinical note` (Doctor consultation note)
   - `prescription` (Medication orders)
   - `mixed` (Multi-discipline reports containing both lab panels and imaging impressions)
4. **`patient_id`** (Text, optional): The synthetic patient identifier (e.g., `SYN-1001`).
5. **`patient_name`** (Text, optional): The patient's name as stated in the document (e.g., `Rohan Example`).
6. **`document_date`** (Text, optional): The standardized ISO 8601 date string (`YYYY-MM-DD`, e.g., `2026-04-03`).
7. **`date_label`** (Text, optional): The verbatim date label used in the report (`Registered On`, `Report Date`, `Study Date`, `Collected`, `Date of Report`, `Date`).
8. **`lab_results`** (List of `LabResult`, default empty): A list of structured lab measurements. Only populated for lab-type documents and the lab portions of mixed documents.
9. **`key_text_sections`** (Key-Value Dictionary, default empty): For narrative/unstructured documents (radiology findings, ultrasound impressions, doctor notes, prescriptions), stores the raw text under its heading (e.g., `"Findings": "The visualised lung fields are clear."`).
10. **`extraction_method`** (Text, default `"rule_based"`): Indicates how the fields were extracted (e.g., `"rule_based"` regex, or future `"llm_prompt"`).
11. **`validation_errors`** (List of text messages, default empty): Captures data quality problems detected by the validator (e.g., missing required fields, unparsable dates, missing units), preventing system crashes.

---

### `LabResult` (Structured Clinical Observation)

1. **`test_name`** (Text, required): The name of the specific analyte or test copied exactly as written (e.g., `Haemoglobin`, `Fasting Glucose`, `Platelet Count`).
2. **`result_value`** (Float, optional): The numerical measurement value (e.g., `14.2`, `96.0`, `3.0`).
3. **`unit`** (Text, optional): The unit of measurement (e.g., `g/dL`, `mg/dL`, `mEq/L`, `uIU/mL`, `x10^3/cmm`).
4. **`reference_range_text`** (Text, optional): The reference or biological interval as verbatim text from the report (e.g., `13.0 - 17.0`, `Less than 150`, `Up to 200`).
5. **`reference_low`** (Float, optional): Lower numeric bound of reference interval (e.g., `13.0` for `13.0 - 17.0`, `None` for `Less than 150` or `Up to 200`).
6. **`reference_high`** (Float, optional): Upper numeric bound of reference interval (e.g., `17.0` for `13.0 - 17.0`, `150.0` for `Less than 150`, `200.0` for `Up to 200`).
7. **`flag`** (Choice: `low`, `normal`, `high`, `unknown`, default `"unknown"`): The clinical status tag indicating whether the result falls below, within, or above the reference range. If no reference range exists, flag is `"unknown"`.
8. **`source_text`** (Text, required): The exact raw line of text from the source document where this test and result were located.
9. **`source_page`** (Integer, optional): Page number (1-indexed) where the source line appeared.
10. **`confidence`** (Float or None, optional): AI confidence score (0.0 to 1.0). For rule-based extraction, left as `None`.
