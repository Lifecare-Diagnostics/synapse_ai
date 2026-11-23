"""
synapse_poc/scripts/seed_wallet.py
Populate local SQLite database (data/synapse_wallet.db) with verified synthetic demonstration records.
"""

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from synapse.schema import MedicalHistoryEntry, PatientDemographics
from synapse.reader import read_pdf_text, read_text_file
from synapse.extractor import RuleBasedExtractor
from synapse.validator import DocumentValidator
from synapse.reviewer import ExtractionReviewer
from synapse.storage import WalletStorage


def seed_database(db_path: str = os.path.join(BASE_DIR, "data", "synapse_wallet.db")):
    print(f"--> Initializing wallet database at: {db_path}")
    if os.path.exists(db_path):
        os.remove(db_path)
    storage = WalletStorage(db_path)
    extractor = RuleBasedExtractor()
    validator = DocumentValidator()
    reviewer = ExtractionReviewer()

    # 1. Setup Patient Profiles & Demographics
    patients_data = [
        PatientDemographics(
            patient_id="SYN-1001",
            patient_name="Rohan Example",
            date_of_birth="1984-05-12",
            age=42,
            sex="Male",
            medical_history=[
                MedicalHistoryEntry(
                    entry_id="HIST-1001-01",
                    condition_or_event="Essential Hypertension",
                    entry_date="2024-02-15",
                    source="Clinical Assessment Note 008",
                    notes="Managed with Telmisartan 40mg OD. Blood pressure monitored quarterly.",
                ),
                MedicalHistoryEntry(
                    entry_id="HIST-1001-02",
                    condition_or_event="Seasonal Allergic Rhinitis",
                    entry_date="2025-08-10",
                    source="Prescription Record 009",
                    notes="Symptomatic flare-ups during monsoon season.",
                ),
            ],
        ),
        PatientDemographics(
            patient_id="SYN-1002",
            patient_name="Meera Sample",
            date_of_birth="1975-09-20",
            age=51,
            sex="Female",
            medical_history=[
                MedicalHistoryEntry(
                    entry_id="HIST-1002-01",
                    condition_or_event="Type 2 Diabetes Mellitus",
                    entry_date="2023-11-05",
                    source="Endocrinology OPD Note",
                    notes="Dietary regulation and Metformin 500mg twice daily.",
                ),
            ],
        ),
        PatientDemographics(
            patient_id="SYN-1005",
            patient_name="Isha Testerson",
            date_of_birth="1991-03-14",
            age=35,
            sex="Female",
            medical_history=[
                MedicalHistoryEntry(
                    entry_id="HIST-1005-01",
                    condition_or_event="Primary Hypothyroidism",
                    entry_date="2022-01-18",
                    source="Endocrine Review",
                    notes="On Levothyroxine 50 mcg OD fasting.",
                ),
            ],
        ),
    ]

    for p in patients_data:
        storage.save_patient(p)
        print(f"  [Saved Patient] {p.patient_id} - {p.patient_name} ({len(p.medical_history)} history entries)")

    # 2. Ingest baseline synthetic inputs
    inputs_dir = os.path.join(BASE_DIR, "data", "synthetic_inputs")
    wallet_dir = os.path.join(BASE_DIR, "data", "synthetic_wallet")
    messy_dir = os.path.join(BASE_DIR, "data", "messy")

    file_list = []
    # Primary clinical files
    for f in sorted(os.listdir(inputs_dir)):
        if f.endswith(".txt"):
            file_list.append((os.path.join(inputs_dir, f), "txt"))

    # Longitudinal CBC followup files
    if os.path.exists(wallet_dir):
        for f in sorted(os.listdir(wallet_dir)):
            if f.endswith(".txt"):
                file_list.append((os.path.join(wallet_dir, f), "txt"))

    # Messy edge cases
    if os.path.exists(messy_dir):
        for f in ["messy_001_missing_date.txt", "messy_002_missing_unit.txt"]:
            fp = os.path.join(messy_dir, f)
            if os.path.exists(fp):
                file_list.append((fp, "txt"))

    # PDF sample reports
    pdf_samples_dir = os.path.join(BASE_DIR, "data", "pdf_samples")
    if os.path.exists(pdf_samples_dir):
        for f in sorted(os.listdir(pdf_samples_dir)):
            if f.endswith(".pdf"):
                file_list.append((os.path.join(pdf_samples_dir, f), "pdf"))

    print("\n--> Ingesting document files into digital wallet...")
    for fpath, ffmt in file_list:
        fname = os.path.basename(fpath)
        if ffmt == "pdf":
            content = read_pdf_text(fpath)
        else:
            content = read_text_file(fpath)
        doc = extractor.extract(content, fname)
        doc = validator.validate(doc)
        doc = reviewer.review(doc)
        rep = storage.ingest_extracted_document(doc, original_location=fpath, file_format=ffmt)
        print(f"  [Ingested] {fname:<35} -> Patient: {rep.patient_id:<10} | Date: {str(rep.report_date):<10} | Params: {len(rep.parameters)}")

    # 3. Ingest Digital API JSON record
    api_json_path = os.path.join(wallet_dir, "patient_002_api_biochemistry.json")
    if os.path.exists(api_json_path):
        with open(api_json_path, "r", encoding="utf-8") as jf:
            payload = json.load(jf)
        rep_api = storage.ingest_api_json_record(payload)
        print(f"  [Ingested API JSON] {api_json_path} -> Patient: {rep_api.patient_id} | Params: {len(rep_api.parameters)}")

    # 4. Summary verification
    print("\n=======================================================")
    print("           PATIENT DIGITAL WALLET SUMMARY              ")
    print("=======================================================")
    patients = storage.list_patients()
    for p in patients:
        pid = p["patient_id"]
        p_reports = storage.list_patient_reports(pid)
        print(f"\nPatient: {p['patient_name']} ({pid}) | Age: {p['age']} | Sex: {p['sex']}")
        print(f"Total Reports: {len(p_reports)}")
        for r in p_reports:
            print(f"  * {str(r.report_date):<12} | Category: {r.report_category:<20} | Status: {r.extraction_status:<10} | Params: {len(r.parameters)}")

    # Longitudinal check for SYN-1001 Hemoglobin
    hb_trend = storage.get_longitudinal_parameters("SYN-1001", "Hemoglobin")
    print("\nLongitudinal Hemoglobin Trend for SYN-1001:")
    for pt in hb_trend:
        print(f"  Date: {pt.report_date} | Value: {pt.result_value} {pt.unit} | Range: {pt.reference_range_text} | Flag: {pt.clinical_flag}")

    print("\nDatabase seeded successfully!")
    return storage


if __name__ == "__main__":
    seed_database()

