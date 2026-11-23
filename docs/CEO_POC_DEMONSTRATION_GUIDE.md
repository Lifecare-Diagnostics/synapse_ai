# Synapse AI — Executive POC Demonstration Guide
## Life Care Diagnostics: 10-Minute Walkthrough Script for Leadership

**Audience:** Chief Executive Officer, Chief Medical Officer, Head of Pathology, IT Director  
**Presenter:** AI Clinical Informatics Lead / Synapse Development Team  
**Focus:** Commercial Value, Clinical Safety, Digital Wallet Experience, Interoperability, and Cost Control  
**Duration:** 10 Minutes

---

## Executive Summary (1 Minute)

> *"Life Care Diagnostics processes thousands of diagnostic documents every week—from routine CBCs and lipid profiles to complex narrative radiology scans and external physician notes. Today, patient records are fragmented across paper, PDFs, and disconnected systems.*
> 
> *Synapse AI is our proprietary Patient Digital Wallet. It automatically ingests multi-format medical reports, organizes longitudinal patient histories, highlights abnormal parameters, enforces strict clinical review workflows, and connects securely with hospital EHRs via modern FHIR R4 standards—all at an operational AI cost of less than ₹1 per 10 documents."*

---

## Demonstration Script & Step-by-Step Flow

### 1. The Patient Digital Wallet (2 Minutes)
**Goal:** Show how fragmented reports become an organized, unified chronological health record.

1. **Launch the Dashboard:** Open `http://localhost:8000` in the browser.
2. **Select Patient:** Select **Rohan Example (`SYN-1001`)** from the active patient banner.
3. **Showcase the Wallet:**
   - Point out the chronological timeline of medical reports across multiple diagnostic categories: CBC / Hematology, Biochemistry, Lipid Profile, Renal Function, and Thyroid.
   - Click on the **Calendar View** tab to show encounter clustering by date, demonstrating intuitive visual tracking for patients and clinicians.
4. **Showcase Original File Access:**
   - Click **"View Details"** on any report card.
   - Highlight the embedded document viewer showing the original source document alongside the structured extraction.

---

### 2. Longitudinal Trends & Abnormality Summaries (2 Minutes)
**Goal:** Demonstrate clinical intelligence that saves pathologist and physician time.

1. **Abnormal Parameter Summary:**
   - Open a report modal and direct attention to the **4-Card Abnormality Box**:
     - 🔴 **Below Range:** Instantly flags critical low values.
     - 🟠 **Above Range:** Highlights elevated biomarkers.
     - 🟢 **Within Range:** Confirms normal parameters.
     - 🟡 **Requires Review:** Flags borderline or unusual tokens.
2. **Longitudinal Parameter Graph:**
   - Navigate to the **Trend Analysis** tab.
   - Select **Hemoglobin** or **Fasting Blood Glucose**.
   - Show the dynamic SVG trendline mapping changes across multiple test dates, enabling instant recognition of therapeutic progress or deterioration.

---

### 3. Hybrid AI Intelligence & Fallback Safety (2 Minutes)
**Goal:** Prove that Synapse AI is clinically safe, zero-hallucination, and resilient.

1. **The Fast Path (Deterministic):**
   - Explain that standard laboratory reports use deterministic clinical rules ($0.00 cost, zero hallucination risk, sub-second execution).
2. **The Cloud AI Path (Gemini Integration):**
   - Explain how unstructured narrative documents (doctor notes, ultrasound narratives, radiology reports) automatically route to Google Gemini's high-speed intelligence engine (`gemini-3.5-flash-lite`).
3. **The Offline Safety Net:**
   - Demonstrate that if cloud connectivity is interrupted, Synapse AI **never crashes**—it automatically falls back to deterministic extraction and queues the report for human review.

---

### 4. Quality Governance & The Clinical Review Queue (2 Minutes)
**Goal:** Assure the CMO and Pathologists that AI never replaces medical judgment.

1. **Role-Based Access Control (RBAC):**
   - Show the active user switcher in the top bar:
     - **Technician:** Can upload documents and view records; cannot approve reports.
     - **Auditor:** Can correct extraction errors with full field-level audit tracking.
     - **Pathologist:** Holds exclusive clinical sign-off authority.
2. **Field-Level Parameter Correction:**
   - Open the **Review Queue** tab.
   - Select a report flagged as `needs_review`.
   - Click **"Correct"** on a parameter to edit a value or unit.
   - Show that the original verbatim value, corrected value, reviewer identity, and timestamp are permanently recorded in the audit trail.
3. **Export Safeguards:**
   - Demonstrate that unapproved or rejected reports **cannot be exported** to hospital EHRs.

---

### 5. FHIR Interoperability & Commercial Cost Control (2 Minutes)
**Goal:** Satisfy IT Director on standards compliance and CEO on financial viability.

1. **FHIR R4 / HL7 Ingestion & Export:**
   - Show one-click export of an approved report into a standard **HL7 FHIR R4 DiagnosticReport Bundle**.
   - Point out SMART-on-FHIR and MLLP listener gateway foundations ready for LIS integration.
2. **Management Cost Calculator:**
   - Navigate to the **LLM & Costs** tab.
   - Show live token tracking and demonstrate the interactive monthly calculator:
     - At **10,000 documents/month**, estimated AI cloud inference cost is **~₹810/month** ($\approx \$9$).
     - At **100,000 documents/month**, estimated cost is **~₹8,100/month** ($\approx \$90$).
   - Conclude: *"Because our hybrid architecture processes routine lab reports locally, actual operating costs will be a fraction of traditional cloud AI implementations."*

---

## Anticipated Executive Questions & Answers

| Question | Executive Answer |
| :--- | :--- |
| **"What if the AI hallucinates a critical lab value?"** | Synapse AI uses deterministic regex rules for standard labs where hallucinations are mathematically impossible. For narrative documents processed by Gemini, all outputs must pass schema validation and clinical sign-off in the Review Queue before entering the patient wallet. |
| **"Are patient records shared with Google?"** | No. In this POC, only synthetic/fabricated data is used. For commercial production, we recommend deploying on Google Cloud Vertex AI with a signed Business Associate Agreement (BAA) and Zero Data Retention policy, or using local on-premise LLMs (Ollama) where data never leaves Life Care's network. |
| **"Can it integrate with our existing Laboratory Information System (LIS)?"** | Yes. Synapse AI includes an HL7 v2.5.1 MLLP ingestion listener, SMART-on-FHIR OAuth2 gateway, and FHIR R4 bundle generation specifically designed to interface with LIS and hospital EHR platforms. |
| **"How much will this cost to operate at scale?"** | At 100,000 tests per month, commercial cloud API cost is projected at under ₹8,500/month. Routine lab processing incurs ₹0 cloud cost. |
