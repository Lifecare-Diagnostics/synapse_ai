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
| **Validator & Flag Engine** | `synapse_poc/synapse/validator.py` with ISO date checking, unit normalization (`gm/dL` $\rightarrow$ `g/dL`), and boundary-value flag calculation (`Up to X`, `Less than X`, and ranges). | **Verified by running**: 6/6 pytest tests passing (`tests/test_extractor_validator.py`). |
| **Evaluation Suite** | `synapse_poc/scripts/evaluate.py` running automated comparisons against `ground_truth.json`. Documented in `docs/EVALUATION.md`. | **Verified by running**: 100% field accuracy (352/352 fields across 17 files). |

---

## 3. Test & Verification Evidence

- **Pytest Suite:** 10 passed out of 10 tests in 1.36s.
  ```powershell
  .venv\Scripts\pytest.exe -v
  tests/test_extractor_validator.py::test_extractor_lab_report PASSED
  tests/test_extractor_validator.py::test_reference_range_boundary_values PASSED
  tests/test_extractor_validator.py::test_no_reference_range_yields_unknown_flag PASSED
  tests/test_extractor_validator.py::test_unit_normalisation PASSED
  tests/test_extractor_validator.py::test_messy_file_missing_date PASSED
  tests/test_extractor_validator.py::test_messy_file_missing_unit PASSED
  tests/test_reader.py::test_every_input_txt_reads PASSED
  tests/test_reader.py::test_every_generated_pdf_contains_patient_name PASSED
  tests/test_reader.py::test_missing_files_give_clear_results PASSED
  tests/test_reader.py::test_empty_pdf_gives_needs_ocr_result PASSED
  ```
- **Evaluation Script:** 17/17 files passed (352/352 fields correct).

---

## 4. Current Limitations & What Remains Incomplete

1. **OCR Layer:** Scanned images and non-searchable PDFs return `"needs OCR - not supported yet"`. (Intentionally omitted per POC scope).
2. **LLM Extraction:** The extractor currently runs deterministic regex rules. The `Extractor` interface is in place with a documented placeholder for future LLM integration.
3. **Evaluation Optimism:** Ground truth was authored against the synthetic files and the extractor tuned to those formats; real diagnostic reports will feature significantly higher variance.
4. **Backend API / Service:** No REST API (FastAPI / Flask) has been introduced.
5. **UI Integration:** The modular HTML/JS wireframe in `synapse-wireframe-project/` remains static mockups and has not yet been wired to the Python backend outputs.
