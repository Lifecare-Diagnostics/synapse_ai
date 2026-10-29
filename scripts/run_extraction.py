"""
synapse_poc/scripts/run_extraction.py
Runs the extraction, validation, and review pipeline on all test files and saves structured JSON to outputs/.
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import json
from synapse.reader import read_text_file, read_pdf_text
from synapse.extractor import RuleBasedExtractor
from synapse.validator import DocumentValidator
from synapse.reviewer import ExtractionReviewer

WORKSPACE_ROOT = os.path.dirname(BASE_DIR)
LOCAL_INPUT_DIR = os.path.join(BASE_DIR, "data", "synthetic_inputs")
PARENT_INPUT_DIR = os.path.join(WORKSPACE_ROOT, "lifecare_ai_poc_phase3_input", "input")
INPUT_DIR = LOCAL_INPUT_DIR if os.path.exists(LOCAL_INPUT_DIR) else PARENT_INPUT_DIR
PDF_DIR = os.path.join(BASE_DIR, "data", "pdf_samples")
MESSY_DIR = os.path.join(BASE_DIR, "data", "messy")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

os.makedirs(OUTPUT_DIR, exist_ok=True)

extractor = RuleBasedExtractor()
validator = DocumentValidator()
reviewer = ExtractionReviewer()

files_to_process = []

# 1. txt files from synthetic_inputs
for f in sorted(os.listdir(INPUT_DIR)):
    if f.endswith(".txt"):
        files_to_process.append((os.path.join(INPUT_DIR, f), "txt"))

# 2. pdf files
for f in sorted(os.listdir(PDF_DIR)):
    if f.endswith(".pdf"):
        files_to_process.append((os.path.join(PDF_DIR, f), "pdf"))

# 3. messy files
for f in sorted(os.listdir(MESSY_DIR)):
    if f.endswith(".txt"):
        files_to_process.append((os.path.join(MESSY_DIR, f), "txt"))

results = []
for filepath, filetype in files_to_process:
    filename = os.path.basename(filepath)
    if filetype == "pdf":
        text = read_pdf_text(filepath)
    else:
        text = read_text_file(filepath)

    doc = extractor.extract(text, source_file=filename)
    doc = validator.validate(doc)
    doc = reviewer.review(doc)

    out_filename = f"{filename}.json"
    out_path = os.path.join(OUTPUT_DIR, out_filename)
    with open(out_path, "w", encoding="utf-8") as out_f:
        out_f.write(doc.model_dump_json(indent=2))

    results.append((filename, len(doc.lab_results), len(doc.validation_errors)))
    print(f"[OK] {filename} -> summary={doc.extraction_summary}, errors={len(doc.validation_errors)}, flags={len(doc.review_flags)}")

print(f"\nSuccessfully extracted and saved {len(results)} files to {OUTPUT_DIR}")

