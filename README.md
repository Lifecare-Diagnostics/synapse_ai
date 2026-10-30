# Synapse AI — Proof of Concept (POC)
**Life Care Diagnostics R&D Project**

## 1. Project Purpose & Current POC Scope
Synapse AI is an intelligent diagnostic and clinical document extraction engine developed for Life Care Diagnostics. The objective of this Proof of Concept (POC) is to evaluate automated, structured data extraction from diagnostic lab reports, clinical notes, prescriptions, and imaging reports into strongly-typed, schema-validated representations.

### Scope of Current POC
- **Deterministic Rule-Based Ingestion:** Validates end-to-end ingestion, parsing, clinical normalisation, and boundary-value flag calculation on digital documents.
- **Strict Clinical Schema Validation:** Enforces Pydantic models for individual laboratory observations (`LabResult`) and comprehensive clinical documents (`ExtractedDocument`).
- **Benchmark Evaluation:** Compares extraction outputs against a standardized clinical ground truth across diverse report categories and malformed edge cases.

---

## 2. Implemented Capabilities vs. Planned Work

### Implemented Capabilities (Functional)
- **Document Ingestion (`synapse/reader.py`):**
  - Reads UTF-8 plain text diagnostic reports (`.txt`).
  - Extracts text layers from digitally generated PDF documents (`.pdf`) using PyMuPDF.
  - Safe fallback: files without an extractable text layer gracefully return `"needs OCR - not supported yet"` rather than failing.
- **Rule-Based Extractor (`synapse/extractor.py`):**
  - Regex-driven document type classification (`lab report`, `radiology`, `ultrasound`, `clinical note`, `prescription`, `mixed`).
  - Metadata parsing for synthetic patient IDs, patient names, and report dates with flexible date label matching.
  - Test observation parsing including test name, numeric result, unit, and reference interval text.
- **Validation & Clinical Flag Calculation (`synapse/validator.py`):**
  - ISO date validation (`YYYY-MM-DD`).
  - Unit normalisation (e.g., standardises `gm/dL`, `gm/dl`, `g/dl` $\rightarrow$ `g/dL`; `meq/l` $\rightarrow$ `mEq/L`; `uiu/ml` $\rightarrow$ `uIU/mL`).
  - Reference range evaluation: supports ranges (`low - high`), upper limits (`Up to X`), and thresholds (`Less than X`), tagging results as `low`, `normal`, `high`, or `unknown`.
  - Non-crashing validation design: accumulates schema issues into `validation_errors`.
- **Automated Test Suite & Evaluation (`tests/`, `scripts/`):**
  - 10 automated unit and integration tests passing via `pytest`.
  - Benchmark evaluation script (`scripts/evaluate.py`) comparing 17 synthetic test files against `data/ground_truth.json`.

### Current Limitations
- **No OCR Layer:** Scanned paper records, images, and non-searchable PDFs are not yet parsed (PyMuPDF identifies missing text layers and marks them for OCR).
- **Rule-Based Matching:** Regex rules were developed to match known patterns in the test files; real clinical documents exhibit greater variability in formatting, layouts, and terminology.
- **Evaluation Optimism:** Ground truth was authored against the synthetic files and the extractor tuned to those formats; real diagnostic reports will feature significantly higher variance.
- **No Live LLM Connection:** The extractor contains an extensible interface (`Extractor` base class), but LLM inference is not yet integrated.

### Planned Work & Roadmap
1. **Source-Level Ground-Truth Verification:** Human-in-the-loop clinical review and validation of `data/ground_truth.json` by laboratory specialists.
2. **Confidence Thresholds & Error Handling:** Quantitative confidence scoring for extracted fields and automated fallback routing.
3. **LLM Research & Integration:** Evaluation of hosted and local Large Language Models (LLMs) for semi-structured extraction, complex medical summaries, and reasoning over ambiguous clinical narratives.
4. **OCR Feasibility Research:** Ingestion research on OCR engines (e.g., Tesseract, cloud OCR, or vision-language models) for scanned diagnostic slips and faxes.
5. **Backend Service & UI Integration:** Exposing extraction endpoints via a lightweight API (e.g., FastAPI) and connecting to the Synapse clinical wireframe interface and database store.

---

## 3. Synthetic Data Policy
> **CRITICAL COMPLIANCE NOTICE:**
> This repository strictly adheres to a **Synthetic Data Only** policy.
> All documents in `data/synthetic_inputs/`, `data/pdf_samples/`, `data/messy/`, and `data/ground_truth.json` contain **entirely fictitious, synthetically generated sample data**. No Protected Health Information (PHI), Personally Identifiable Information (PII), or real patient diagnostic reports are stored in or processed by this repository.

---

## 4. Repository Structure

```
synapse_poc/
├── .env.example              # Placeholder configuration template for planned features
├── .gitignore                # Version control exclusions (venvs, outputs, secrets, caches)
├── README.md                 # Project documentation and developer guide
├── requirements.txt          # Pinned project dependencies
├── data/
│   ├── ground_truth.json     # Clinical benchmark ground truth (drafted from synthetic inputs)
│   ├── messy/                # Deliberately malformed synthetic test files (edge cases)
│   ├── pdf_samples/          # Digitally generated PDF test files with native text layers
│   └── synthetic_inputs/     # Primary synthetic clinical text reports (10 document types)
├── docs/
│   ├── EVALUATION.md         # Automated evaluation report and field accuracy breakdown
│   ├── PROJECT_STATUS.md     # Technical progress and milestone verification report
│   └── schema.md             # Pydantic schema specification and field dictionary
├── outputs/                  # Local directory for generated JSON extraction outputs (git-ignored)
│   └── .gitkeep
├── scripts/
│   ├── evaluate.py           # Evaluation script: benchmarks extraction against ground truth
│   ├── generate_test_files.py # Generator for synthetic PDF samples and edge-case text files
│   └── run_extraction.py     # Pipeline runner: extracts all test files into outputs/
├── synapse/
│   ├── __init__.py           # Package marker
│   ├── extractor.py          # Abstract Extractor base class & RuleBasedExtractor
│   ├── reader.py             # File reader for .txt and digital .pdf (PyMuPDF)
│   ├── schema.py             # Pydantic data models (ExtractedDocument, LabResult)
│   └── validator.py          # DocumentValidator with unit normalisation & flag logic
└── tests/
    ├── __init__.py
    ├── test_extractor_validator.py # Tests for extraction rules, boundary values, and validator
    └── test_reader.py              # Tests for document reader and error conditions
```

---

## 5. Environment Setup & Installation

### Prerequisites
- Python 3.10+ (tested on Python 3.15.0)
- `pip` package manager

### Setup Instructions
1. **Clone the repository:**
   ```bash
   git clone https://github.com/Lifecare-Diagnostics/synapse_ai.git
   cd synapse_ai
   ```

2. **Create and activate a virtual environment:**
   ```powershell
   # Windows PowerShell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```
   ```bash
   # Linux / macOS
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Configuration (Optional):**
   Copy the `.env.example` file to create a local `.env` file (reserved for future LLM integration):
   ```bash
   cp .env.example .env
   ```

---

## 6. Running Scripts & Automated Tests

### 1. Run Automated Tests
Execute the full test suite using `pytest`:
```bash
pytest -v
```
*Expected result: 38 passed tests covering extraction, validation, review flags, wallet storage, abnormal summaries, longitudinal trends, and API endpoints.*

### 2. Seed the Patient Digital Wallet Database
Populate the local SQLite database (`data/synapse_wallet.db`) with synthetic patient profiles, medical histories, multi-date CBC reports, and digital API records:
```bash
python scripts/seed_wallet.py
```

### 3. Launch the Patient Digital Wallet Web Application
Run the local FastAPI server with the interactive clinical dashboard:
```bash
uvicorn synapse.api:app --host 127.0.0.1 --port 8000
```
Open your browser to:
- **Web Dashboard:** [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Interactive OpenAPI Docs:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 4. Run the Extraction Pipeline
Run extraction on all synthetic files (text files, PDFs, and messy edge cases) and save structured JSON files into `outputs/`:
```bash
python scripts/run_extraction.py
```
*Outputs are saved to `outputs/<filename>.json`.*

### 5. Run Benchmark Evaluation
Evaluate extracted outputs against `data/ground_truth.json` and generate an updated evaluation report:
```bash
python scripts/evaluate.py
```
*Displays per-field and per-file accuracy metrics and updates `docs/EVALUATION.md`.*

### 4. Regenerate Synthetic Test Files (Optional)
If synthetic PDFs or messy test files need to be regenerated:
```bash
python scripts/generate_test_files.py
```
