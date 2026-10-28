"""
Generate PDF samples and messy test files for Synapse POC.
"""
import os
from fpdf import FPDF

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE_ROOT = os.path.dirname(BASE_DIR)
LOCAL_INPUT_DIR = os.path.join(BASE_DIR, "data", "synthetic_inputs")
PARENT_INPUT_DIR = os.path.join(WORKSPACE_ROOT, "lifecare_ai_poc_phase3_input", "input")
INPUT_DIR = LOCAL_INPUT_DIR if os.path.exists(LOCAL_INPUT_DIR) else PARENT_INPUT_DIR
PDF_DIR = os.path.join(BASE_DIR, "data", "pdf_samples")
MESSY_DIR = os.path.join(BASE_DIR, "data", "messy")

os.makedirs(PDF_DIR, exist_ok=True)
os.makedirs(MESSY_DIR, exist_ok=True)

# 1. Generate 5 PDFs from the first 5 lab reports
lab_files = [
    "patient_001_cbc.txt",
    "patient_002_biochemistry.txt",
    "patient_003_lipid_profile.txt",
    "patient_004_renal_function.txt",
    "patient_005_thyroid.txt",
]

for txt_filename in lab_files:
    txt_path = os.path.join(INPUT_DIR, txt_filename)
    with open(txt_path, "r", encoding="utf-8") as f:
        content = f.read()

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)

    # Sanitize unicode dashes for basic standard font if needed
    clean_content = content.replace("—", "-").replace("–", "-")

    for line in clean_content.splitlines():
        pdf.cell(w=0, h=6, text=line, new_x="LMARGIN", new_y="NEXT")

    pdf_filename = os.path.splitext(txt_filename)[0] + ".pdf"
    pdf_path = os.path.join(PDF_DIR, pdf_filename)
    pdf.output(pdf_path)
    print(f"Generated PDF: {pdf_filename}")

# 2. Generate 2 messy files
messy_001_content = """SYNTHETIC TEST DOCUMENT - NOT REAL PATIENT DATA

Patient: Meera Sample
Patient ID: SYN-1002
Age/Sex: 51 / Female
Report: Fasting Biochemistry

Fasting Glucose: 96 mg/dL (Reference 70 - 110)
"""

messy_002_content = """SYNTHETIC TEST DOCUMENT - NOT REAL PATIENT DATA

Patient: Isha Testerson
Patient ID: SYN-1005
Age/Sex: 35 years / Female
Report Date: 2026-04-15
Department: Immunoassay

T3: 112 (Reference 60 - 181)
"""

with open(os.path.join(MESSY_DIR, "messy_001_missing_date.txt"), "w", encoding="utf-8") as f:
    f.write(messy_001_content)
print("Generated messy file: messy_001_missing_date.txt")

with open(os.path.join(MESSY_DIR, "messy_002_missing_unit.txt"), "w", encoding="utf-8") as f:
    f.write(messy_002_content)
print("Generated messy file: messy_002_missing_unit.txt")

print("All sample and messy files generated successfully.")
