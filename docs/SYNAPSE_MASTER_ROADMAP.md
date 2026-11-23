# Synapse AI — Master Development Roadmap
## Life Care Diagnostics R&D / Clinical AI POC

**Repository:** `synapse_ai`  
**Location:** `C:\Tejaswi\Synapse\synapse_poc`  
**Current Branch:** `main`  
**Status:** **POC Core Development Complete (Phases 1 through 8 Verified)**  
**Pass Rate:** **148 / 148 tests passing (100%)**

---

## 1. Architecture & Strategy Overview

Synapse AI is designed as a modular, privacy-first diagnostic data extraction and clinical intelligence engine. The system prioritizes local execution, deterministic clinical reference boundaries, explicit audit trails, and strict error flagging before introducing generative AI layers.

---

## 2. Phase-by-Phase Roadmap & Delivery Status

### [x] Phase 1: Baseline Extraction & Structured Schema (COMPLETED)
- PyMuPDF digital text layer extraction and UTF-8 plain text ingestion.
- Strict Pydantic schemas (`LabReport`, `LabResult`).
- Regex-based extraction for 5 standard laboratory panels (CBC, Biochemistry, Lipid Profile, Renal Function, Thyroid).
- Evaluation Benchmark: 100% field accuracy (352/352 fields).
- Automated Tests: 10/10 passed.

### [x] Phase 2: Extraction Confidence, Validation & Review Flagging (COMPLETED)
- `ExtractionReviewer` audit rules flagging missing values, missing units, ambiguous numbers, and missing report dates.
- Three-tier status classification (`valid`, `needs_review`, `rejected`).
- Automated Tests: 18/18 passed.

### [x] Phase 3: Patient Digital Wallet Data Foundation & Web Dashboard (COMPLETED)
- SQLite storage backend with foreign key enforcement and relational schema.
- Standardization engine with synonym mapping and 5-category abnormality classification.
- FastAPI backend exposing patient profiles, chronological timelines, calendar view, 4-box summaries, and longitudinal trends.
- Safe document serving with path traversal protection.
- Automated Tests: 39/39 passed.

### [x] Phase 4: OCR Engine & Image Document Ingestion (COMPLETED)
- Tesseract OCR integration with PyMuPDF digital text fallback heuristic.
- Support for scanned PDFs, PNG, JPG, and JPEG images.
- Unreadable and blurry scan detection without hallucinating clinical results.
- Automated Tests: 9/9 passed.

### [x] Phase 5: LLM Architecture & Hybrid Extraction (COMPLETED)
- Abstract `LLMClient` interface, `MockLLMClient`, and `LocalOllamaClient`.
- `HybridExtractor` combining deterministic fast path ($0 cost) with LLM clinical understanding for narrative notes.
- Graceful offline fallback to rule-based extraction upon LLM error or timeout.
- Automated Tests: 10/10 passed.

### [x] Phase 6A: FHIR R4 & HL7 v2.5.1 Interoperability (COMPLETED)
- HL7 FHIR R4 Patient, Observation, and DiagnosticReport bundle generation and validation.
- HL7 v2.5.1 ORU^R01 message parsing and synthetic ingestion.
- Payload SHA-256 duplicate detection and integration audit logging.
- Automated Tests: 14/14 passed.

### [x] Phase 6B: Clinical Review Queue & Safeguards (COMPLETED)
- Review Queue with approval, rejection, and review-flagging actions.
- Field-level parameter correction preserving verbatim original and corrected values.
- Chronological quality audit trail.
- Strict export safeguards blocking unapproved or rejected reports from FHIR export.
- Automated Tests: 9/9 passed.

### [x] Phase 7A: Role-Based Access Control (COMPLETED)
- 4 clinical roles: Technician, Auditor, Pathologist, Administrator.
- PBKDF2-HMAC-SHA256 password hashing and RFC 7519 JWT session authentication.
- Server-side authorization guards preventing identity spoofing.
- Automated Tests: 11/11 passed.

### [x] Phase 7B: Security Foundations (COMPLETED)
- Production secret key validation (`SYNAPSE_SECRET_KEY`).
- Environment-driven CORS whitelist configuration (`SYNAPSE_ALLOWED_ORIGINS`).
- Global sanitized exception handling with unique tracking IDs.
- Automated Tests: 4/4 passed.

### [x] Phase 7C: External Interoperability Gateway (COMPLETED)
- Asynchronous MLLP TCP listener with standard framing and ACK generation.
- SMART-on-FHIR OAuth2 gateway with RFC 7636 PKCE verification and mock EHR server.
- Automated Tests: 14/14 passed.

### [x] Phase 8: Google Gemini API Integration & Cost Control (COMPLETED)
- Official `google-genai` Python SDK v3.6.1 integration with `gemini-3.5-flash-lite`.
- Thread-safe `UsageTracker` recording tokens, latency, and costs in SQLite.
- Management monthly cost calculator API endpoints (`/api/v1/llm/usage`, `/api/v1/llm/cost-estimate`).
- Standalone live API verification script (`scripts/verify_gemini.py`).
- Automated Tests: 35/35 passed.

---

## 3. Post-POC Production Roadmap (Phase 9 & Beyond)

| Target Phase | Strategic Objective | Priority |
| :---: | :--- | :---: |
| **Phase 9A** | Enterprise Vertex AI Deployment with signed HIPAA BAA and Zero Data Retention | High |
| **Phase 9B** | Live Laboratory Information System (LIS) MLLP socket binding | High |
| **Phase 9C** | Clinical trial / pilot with 500 de-identified real clinical reports | High |
| **Phase 9D** | ABDM (Ayushman Bharat Digital Mission) M1/M2/M3 milestone certification | Medium |
