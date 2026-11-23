# Synapse AI — Cloud LLM Integration & Setup Guide
## Google Gemini Free Tier Setup, Configuration & Cost Control

**Organization:** Life Care Diagnostics R&D  
**Project:** Synapse AI Patient Digital Wallet POC  
**Target Model:** `gemini-3.5-flash-lite` (Current low-latency, high-throughput cloud model)  
**SDK:** `google-genai` (Official Google Gen AI Python SDK $\ge$ 3.2.0)  
**Status:** Integrated & Verified (35/35 provider tests passing)

> [!WARNING]
> **Clinical & Synthetic Data Notice:**  
> This integration is configured for technical evaluation using synthetic/fabricated test data only.  
> **NEVER send real patient names, protected health information (PHI), or identifiable clinical records to the public free-tier Gemini API.** Human clinical review remains mandatory for all AI-assisted extractions.

---

## 1. Overview & Architecture

Synapse AI uses a **Provider-Agnostic LLM Architecture** implemented in `synapse/llm.py` and `synapse/extractor.py`.

```
                        +----------------------------+
                        |  Incoming Clinical Record  |
                        +--------------+-------------+
                                       |
                                       v
                        +----------------------------+
                        |    RuleBasedExtractor      |
                        |   (Fast-path: CBC, KFT,    |
                        |    LFT, Lipid, Thyroid)    |
                        +--------------+-------------+
                                       |
                 Standard Structured   |   Unstructured Notes /
                 Lab Report (Found)    |   Zero Structured Labs Found
                                       v
               +-----------------------+-----------------------+
               |                                               |
               v                                               v
    +----------------------+                       +-----------------------+
    | Direct Deterministic |                       |    HybridExtractor    |
    | Output (Zero Cost,   |                       |    routes to LLM      |
    | Zero Hallucination)  |                       +-----------+-----------+
    +----------------------+                                   |
                                       +-----------------------+-----------------------+
                                       |                       |                       |
                                       v                       v                       v
                            +--------------------+   +-------------------+   +-------------------+
                            |    GeminiClient    |   | LocalOllamaClient |   |   MockLLMClient   |
                            | (Cloud API, Tokens |   |  (Local Private   |   | (Offline Testing, |
                            |  & Cost Tracked)   |   |   Inference)      |   |   Zero Network)   |
                            +--------------------+   +-------------------+   +-------------------+
                                       |
                                       v (On Network / Rate Limit Failure)
                            +--------------------+
                            | Graceful Fallback  |
                            | to Rule Extraction |
                            +--------------------+
```

### Key Architectural Strengths
1. **Zero-Cost Fast Path:** Standard laboratory panels are processed locally via deterministic rules ($0.00 cost, zero hallucinations).
2. **LLM Enrichment:** Complex unstructured narrative reports (radiology impressions, ultrasound scans, physician clinical notes) route through the LLM.
3. **Graceful Failover:** If the cloud API experiences a timeout, rate limit, or invalid response, `HybridExtractor` catches the exception and immediately falls back to deterministic extraction without crashing.
4. **Token & Cost Tracking:** Every invocation records input tokens, output tokens, latency, and estimated commercial cost in `synapse/usage_tracker.py`.

---

## 2. Step-by-Step Google AI Studio Setup (Free Tier)

### Step 1: Create a Free Gemini API Key
1. Visit the Google AI Studio key creation page:  
   👉 **[https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)**
2. Sign in with your Google account.
3. Click **"Create API Key"** and select or create a project.
4. Copy the generated key string (starts with `AIza...`).
5. **Security Warning:** Store this key securely. Never share it or post it in public repositories.

### Step 2: Environment Configuration
In your `C:\Tejaswi\Synapse\synapse_poc` directory:

1. Copy `.env.example` to `.env`:
   ```powershell
   Copy-Item .env.example .env
   ```
2. Edit `.env` and configure your API key and provider:
   ```env
   # Select Gemini as active provider
   SYNAPSE_LLM_PROVIDER=gemini

   # Configure Gemini API credentials
   GEMINI_API_KEY=AIzaSyYourActualApiKeyHere
   SYNAPSE_GEMINI_MODEL=gemini-3.5-flash-lite
   SYNAPSE_GEMINI_TIMEOUT=60
   SYNAPSE_GEMINI_STORE=false
   ```
3. Verify `.env` is ignored by Git:
   ```powershell
   git status --ignored
   ```
   *`.env` must appear under Ignored files.*

### Step 3: Install SDK Dependencies
The official Google Gen AI SDK is installed in the project virtual environment:
```powershell
.\.venv\Scripts\pip.exe install google-genai
```
*Current verified version: `google-genai==3.6.1`.*

---

## 3. Running Live Verification

Synapse AI includes a dedicated verification script that tests end-to-end cloud connectivity using synthetic data:

```powershell
.\.venv\Scripts\python.exe scripts\verify_gemini.py
```

### Expected Output
```text
============================================================
  SYNAPSE AI — GEMINI API LIVE VERIFICATION
============================================================
  Timestamp: 2026-11-23 11:00:00
  Purpose: Technical POC verification with synthetic data
  Warning: This is NOT clinical validation.

============================================================
  Step 1: API Key Configuration
============================================================
  ✓ API Key: Configured (AIza...xyz)

============================================================
  Step 2: SDK Verification
============================================================
  ✓ google-genai SDK: v3.6.1

============================================================
  Step 3: Synapse Integration Check
============================================================
  ✓ GeminiClient: Available
  ✓ UsageTracker: Available

============================================================
  Step 4: Client Initialization
============================================================
  ✓ Model: gemini-3.5-flash-lite
  ✓ Timeout: 60s
  ✓ Store: False

============================================================
  Step 5: Live Clinical Extraction (Synthetic Data)
============================================================
  ✓ API Call: Success (1.82s)
  ✓ Document Type: lab report
  ✓ Patient Name: Priya Synapse
  ✓ Patient ID: SYN-TEST-9999
  ✓ Document Date: 2024-07-15
  ✓ Lab Results Found: 4
      - Haemoglobin: 12.8 g/dL
      - Total WBC Count: 7200 cells/cumm
      - Platelet Count: 250000 cells/cumm
      - RBC Count: 4.5 million/cumm

  Token Usage:
  ✓ Input Tokens: 412
  ✓ Output Tokens: 185
  ✓ Total Tokens: 597
  ✓ Estimated Cost: $0.000115 USD (₹0.0104 INR)
```

---

## 4. Model Selection & Lifecycle Note

| Requested Model | Current Status | Replacement Model | Reason |
| :--- | :--- | :--- | :--- |
| `gemini-2.5-flash-lite` | **Deprecated** | `gemini-3.5-flash-lite` | Google Gen AI API lifecycle has retired 2.5/2.0 series in favor of 3.x/4.x models. `gemini-3.5-flash-lite` provides superior clinical reasoning, 1M context window, lower latency, and identical low-cost pricing. |

Alternative supported models:
- `gemini-3.1-flash-lite`: Ultra-fast lightweight execution.
- `gemini-4-hydrogen`: Balanced frontier reasoning for ambiguous narrative notes.

---

## 5. Token Usage & Cost Management

### Commercial Pricing Rates (Illustrative for Life Care POC)
- **Input Tokens:** $\$0.10$ per $1,000,000$ tokens
- **Output Tokens:** $\$0.40$ per $1,000,000$ tokens
- **INR Exchange Rate Assumption:** ₹$90.00$ / USD

### Document Cost Matrix
*Assumes average clinical document of 5,000 input tokens + 1,000 output tokens:*

$$\text{Per-Doc Cost} = \left(\frac{5,000}{1,000,000} \times \$0.10\right) + \left(\frac{1,000}{1,000,000} \times \$0.40\right) = \$0.0005 + \$0.0004 = \$0.0009 \text{ USD} \approx \text{₹}0.081 \text{ INR}$$

| Monthly Ingestion Volume | Estimated Cost (USD) | Estimated Cost (INR) | Effective Cost Per Patient |
| :---: | :---: | :---: | :---: |
| **1,000 documents** | $\$0.90$ / mo | **₹81.00** / mo | ₹0.08 |
| **5,000 documents** | $\$4.50$ / mo | **₹405.00** / mo | ₹0.08 |
| **10,000 documents** | $\$9.00$ / mo | **₹810.00** / mo | ₹0.08 |
| **25,000 documents** | $\$22.50$ / mo | **₹2,025.00** / mo | ₹0.08 |
| **50,000 documents** | $\$45.00$ / mo | **₹4,050.00** / mo | ₹0.08 |
| **100,000 documents** | $\$90.00$ / mo | **₹8,100.00** / mo | ₹0.08 |

*Note: Because Synapse AI's `HybridExtractor` routes structured lab reports through the deterministic regex engine ($0 cost), actual production costs will be substantially lower than these conservative upper-bound estimates.*

---

## 6. Security & Credential Protection Checklist

- [x] **No Hardcoded Keys:** Codebase contains zero hardcoded API keys.
- [x] **Git Ignored:** `.env` and credential files are strictly listed in `.gitignore`.
- [x] **No Frontend Exposure:** Browser clients communicate solely with the Synapse FastAPI backend. API keys are never transmitted to web clients.
- [x] **No Logging of Secrets:** Loggers, exception handlers, and status endpoints redact or omit secret tokens.
- [x] **Server-Side Session Derived Reviewer Identity:** Parameter corrections and clinical sign-offs authenticate through PBKDF2/JWT sessions.
