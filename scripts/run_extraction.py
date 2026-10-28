"""
synapse_poc/scripts/run_extraction.py
Runs the extraction and validation pipeline on all test files and saves structured JSON to outputs/.
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

files_to_process = []

# 1. 10 txt files
for f in sorted(os.listdir(INPUT_DIR)):
    if f.endswith(".txt"):
        files_to_process.append((os.path.join(INPUT_DIR, f), "txt"))

# 2. 5 pdf files
for f in sorted(os.listdir(PDF_DIR)):
    if f.endswith(".pdf"):
        files_to_process.append((os.path.join(PDF_DIR, f), "pdf"))

# 3. 2 messy files
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
    validated_doc = validator.validate(doc)

    out_filename = f"{filename}.json"
    out_path = os.path.join(OUTPUT_DIR, out_filename)
    with open(out_path, "w", encoding="utf-8") as out_f:
        json.dump(validated_doc.model_dump(), out_f, indent=2)

    results.append((filename, len(validated_doc.lab_results), len(validated_doc.validation_errors)))
    print(f"Processed {filename} -> {out_filename} (Lab results: {len(validated_doc.lab_results)}, Errors: {len(validated_doc.validation_errors)})")

print(f"\nSuccessfully extracted and saved {len(results)} files to {OUTPUT_DIR}")
