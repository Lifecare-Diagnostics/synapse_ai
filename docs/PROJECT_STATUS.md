# Synapse AI — Life Care Diagnostics R&D / POC
## Workspace Status & Technical Progress Report

- **Date:** October 22, 2026
- **Lead Developer & Technical Mentor:** Antigravity AI
- **Host Environment:** Windows 11 Home 64-bit, Python 3.15.0, 8 GB RAM
- **Workspace:** `c:\Tejaswi\Synapse`
- **Active Code Base:** `synapse_poc/` (isolated lightweight POC package)

---

## 1. Executive Summary

The Synapse AI Proof of Concept pipeline has completed baseline rule-based extraction, document ingestion, schema definition, and automated evaluation.

All 10 synthetic text files, 5 digitally generated PDF files (with real text layers and synthetic watermark), and 2 deliberately malformed edge-case files were processed, validated, and evaluated against ground truth data.

---

## 2. Completed Milestones (Verified by Execution)

| Milestone | Implementation Details | Evidence / Test Status |
| :--- | :--- | :--- |
| **Virtual Environment & Dependencies** | Dedicated `.venv` created at `synapse_poc/.venv`. Minimal packages pinned in `synapse_poc/requirements.txt` (`pydantic==2.14.1`, `pymupdf==1.28.2`, `fpdf2==2.8.9`, `pytest==9.1.1`). | **Verified by running**: `pip freeze` and clean wheel installation. |
| **Schema Definition** | Pydantic data models in `synapse_poc/synapse/schema.py`: `ExtractedDocument` and `LabResult` (with `source_page`, `reference_low`, `reference_high`, `date_label`, `confidence`). | **Verified by running**: Schema instantiation and boundary tests. |
| **Ground Truth Dataset** | Hand-drafted clinical benchmark in `synapse_poc/data/ground_truth.json` covering all 10 synthetic clinical types and 2 messy files. | **Verified by running**: JSON schema loading and completeness check. |
| **PDF & Messy Test Generation** | 5 digital PDF files generated using `fpdf2` in `data/pdf_samples/`. 2 malformed test files in `data/messy/` (one missing date, one missing unit). | **Verified by running**: PyMuPDF text layer inspection. |
| **Document Reader** | `synapse_poc/synapse/reader.py` with `read_text_file()` and `read_pdf_text()` using PyMuPDF. Clean fallback to `"needs OCR - not supported yet"` for empty text layers. | **Verified by running**: 4/4 pytest tests passing (`tests/test_reader.py`). |
| **Extractor Interface & Engine** | `synapse_poc/synapse/extractor.py` featuring an abstract `Extractor` base class, marked LLM replacement placeholder, and regex-based `RuleBasedExtractor`. | **Verified by running**: 17/17 files processed cleanly. |
| **Validator & Flag Engine** | `synapse_poc/synapse/validator.py` with ISO date checking, unit normalization (`gm/dL` $\rightarrow$ `g/dL`), and boundary-value flag calculation (`Up to X`, `Less than X`, and ranges). Phase 2: `_check_implausible_value()` added for negative-value detection. | **Verified by running**: 6/6 pytest tests passing (`tests/test_extractor_validator.py`). |
| **Evaluation Suite** | `synapse_poc/scripts/evaluate.py` running automated comparisons against `ground_truth.json`. Documented in `docs/EVALUATION.md`. | **Verified by running**: 100% field accuracy (352/352 fields across 17 files). |
| **Phase 2: Extraction Review & Flagging** | `synapse/reviewer.py` — `ExtractionReviewer` attaches structured `ReviewFlag` objects for unrecognised tests, missing values, missing units, missing reference ranges, unparseable flag computation, missing document dates, missing patient IDs, and ambiguous source text. `schema.py` extended with `ReviewFlag` model, `LabResult.review_flags`, `LabResult.extraction_status`, `ExtractedDocument.review_flags`, `ExtractedDocument.extraction_summary`. 4 new synthetic messy test fixtures added. | **Verified by running**: 18/18 pytest tests passing. 100% field accuracy maintained. |
| **Phase 3 Stage 1: Data Foundation & Storage** | `synapse/schema.py` extended with `MedicalHistoryEntry`, `PatientDemographics`, `ReportParameter`, `PatientReport`, `Patient`. `synapse/standardizer.py` for canonical mapping and 5-category abnormality classification. `synapse/storage.py` SQLite relational repository with foreign keys, chronological sorting, calendar grouping, longitudinal retrieval, and adapter for extracted documents and API payloads. | **Verified by running**: 26/26 pytest tests passing (`tests/test_wallet_storage.py`). |
| **Phase 3 Stage 2: Web Interface & API Integration** | `synapse/api.py` FastAPI backend with REST endpoints for patient profiles, chronological records, filters, calendar view, 4-box abnormal summary, longitudinal trends with unit compatibility checks, mock JSON ingestion, multipart file uploads (.txt, .pdf, .json), duplicate detection (409 Conflict), and OCR identification. Web frontend (`synapse/static/index.html`, `style.css`, `app.js`) with responsive clinical UI, SVG trend line charts, and interactive calendar. | **Verified by running**: 38/38 pytest tests passing (`tests/test_api.py`). Local seeding and live API verified. |

---

## 3. Test & Verification Evidence

- **Pytest Suite:** 38 passed out of 38 tests in 2.35s (10 Phase 1 + 8 Phase 2 + 8 Phase 3 Stage 1 + 12 Phase 3 Stage 2).
  ```powershell
  .venv\Scripts\pytest.exe -v
  tests/test_api.py::test_api_list_patients PASSED
  tests/test_api.py::test_api_get_patient_details PASSED
  tests/test_api.py::test_api_list_patient_reports_chronological PASSED
  tests/test_api.py::test_api_report_filters PASSED
  tests/test_api.py::test_api_calendar_view PASSED
  tests/test_api.py::test_api_report_details_and_abnormal_summary PASSED
  tests/test_api.py::test_api_longitudinal_trends PASSED
  tests/test_api.py::test_api_available_parameters PASSED
  tests/test_api.py::test_api_ingest_json_report PASSED
  tests/test_api.py::test_api_ingest_json_validation_error PASSED
  tests/test_api.py::test_api_file_upload_text[asyncio] PASSED
  tests/test_api.py::test_api_file_upload_scanned_pdf_needs_ocr[asyncio] PASSED
  tests/test_extractor_validator.py::test_extractor_lab_report PASSED
  tests/test_extractor_validator.py::test_reference_range_boundary_values PASSED
  tests/test_extractor_validator.py::test_no_reference_range_yields_unknown_flag PASSED
  tests/test_extractor_validator.py::test_unit_normalisation PASSED
  tests/test_extractor_validator.py::test_messy_file_missing_date PASSED
  tests/test_extractor_validator.py::test_messy_file_missing_unit PASSED
  tests/test_extractor_validator.py::test_unknown_test_name_flagged PASSED
  tests/test_extractor_validator.py::test_missing_value_flagged PASSED
  tests/test_extractor_validator.py::test_missing_unit_flagged PASSED
  tests/test_extractor_validator.py::test_missing_date_document_flag PASSED
  tests/test_extractor_validator.py::test_missing_patient_id_document_flag PASSED
  tests/test_extractor_validator.py::test_negative_value_validation_error PASSED
  tests/test_extractor_validator.py::test_extraction_summary_counts PASSED
  tests/test_extractor_validator.py::test_no_false_flags_on_clean_document PASSED
  tests/test_reader.py::test_every_input_txt_reads PASSED
  tests/test_reader.py::test_every_generated_pdf_contains_patient_name PASSED
  tests/test_reader.py::test_missing_files_give_clear_results PASSED
  tests/test_reader.py::test_empty_pdf_gives_needs_ocr_result PASSED
  tests/test_wallet_storage.py::test_patient_demographics_crud PASSED
  tests/test_wallet_storage.py::test_medical_history_linking PASSED
  tests/test_wallet_storage.py::test_multiple_reports_linked_to_one_patient_chronologically PASSED
  tests/test_wallet_storage.py::test_report_filters_and_parameter_search PASSED
  tests/test_wallet_storage.py::test_calendar_view_grouping PASSED
  tests/test_wallet_storage.py::test_longitudinal_parameters_trend PASSED
  tests/test_wallet_storage.py::test_abnormal_summary_categorization PASSED
  tests/test_wallet_storage.py::test_api_json_record_ingestion PASSED
  ```
- **Evaluation Script:** 17/17 ground-truth files passed (352/352 fields correct). Phase 2 review flags summary included in EVALUATION.md.

---

## 4. Current Limitations & What Remains Incomplete

1. **OCR Layer:** Scanned images and non-searchable PDFs return `"needs OCR - not supported yet"` and are flagged as `ocr_required`. (Intentionally omitted per POC scope).
2. **LLM Extraction:** The extractor currently runs deterministic regex rules. The `Extractor` interface is in place with a documented placeholder for future LLM integration.
3. **Evaluation Optimism:** Ground truth was authored against the synthetic files and the extractor tuned to those formats; real diagnostic reports will feature significantly higher variance.
4. **Production DB & External Systems:** The local POC runs on SQLite (`data/synapse_wallet.db`); production EHR / LIS integration will be designed in subsequent phases.
