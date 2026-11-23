"""
synapse_poc/synapse/storage.py
Lightweight SQLite-based storage engine for Patient Digital Wallet records.
Maintains relational integrity for Patients, Medical History, Reports, and Parameters.
"""

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Dict, List, Optional
import uuid

from synapse.schema import (
    MedicalHistoryEntry,
    PatientDemographics,
    Patient,
    PatientReport,
    ReportParameter,
    ReviewFlag,
    ExtractedDocument,
    FieldCorrection,
    ReviewAuditEntry,
)
from synapse.auth import User, UserInDB, hash_password
from synapse.standardizer import standardize_parameter_name, classify_abnormality


class WalletStorage:
    """
    SQLite-backed repository for the Patient Digital Wallet.
    Thread-safe connection handling with foreign key enforcement.
    """

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._mem_conn = None
        if self.db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
            self._mem_conn.execute("PRAGMA foreign_keys = ON;")
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._mem_conn is not None:
            return self._mem_conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS patients (
                patient_id TEXT PRIMARY KEY,
                patient_name TEXT NOT NULL,
                date_of_birth TEXT,
                age INTEGER,
                sex TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS medical_history (
                entry_id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL,
                condition_or_event TEXT NOT NULL,
                entry_date TEXT,
                source TEXT NOT NULL,
                notes TEXT,
                FOREIGN KEY (patient_id) REFERENCES patients(patient_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS reports (
                report_id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL,
                report_date TEXT,
                date_label TEXT,
                report_category TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                file_format TEXT NOT NULL,
                upload_datetime TEXT NOT NULL,
                extraction_status TEXT NOT NULL,
                review_status TEXT NOT NULL,
                original_document_location TEXT,
                content_hash TEXT,
                key_text_sections_json TEXT,
                document_level_flags_json TEXT,
                validation_errors_json TEXT,
                FOREIGN KEY (patient_id) REFERENCES patients(patient_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS parameters (
                parameter_id TEXT PRIMARY KEY,
                report_id TEXT NOT NULL,
                patient_id TEXT NOT NULL,
                report_date TEXT,
                original_name TEXT NOT NULL,
                standardized_name TEXT,
                result_value REAL,
                unit TEXT,
                reference_range_text TEXT,
                reference_low REAL,
                reference_high REAL,
                clinical_flag TEXT,
                abnormality_category TEXT NOT NULL,
                extraction_status TEXT NOT NULL,
                source_text TEXT NOT NULL,
                review_flags_json TEXT,
                FOREIGN KEY (report_id) REFERENCES reports(report_id) ON DELETE CASCADE,
                FOREIGN KEY (patient_id) REFERENCES patients(patient_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_reports_patient_date ON reports(patient_id, report_date);
            CREATE INDEX IF NOT EXISTS idx_parameters_patient_std ON parameters(patient_id, standardized_name, report_date);

            CREATE TABLE IF NOT EXISTS review_audit (
                audit_id TEXT PRIMARY KEY,
                report_id TEXT NOT NULL,
                action TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                previous_status TEXT NOT NULL,
                new_status TEXT NOT NULL,
                comments TEXT,
                corrections_json TEXT,
                FOREIGN KEY (report_id) REFERENCES reports(report_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_review_audit_report ON review_audit(report_id);

            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            """)

            # Add content_hash if table already existed without it
            try:
                conn.execute("ALTER TABLE reports ADD COLUMN content_hash TEXT;")
            except Exception:
                pass

            # Seed default synthetic RBAC users if users table is empty
            try:
                cur = conn.execute("SELECT count(*) as cnt FROM users;")
                if cur.fetchone()["cnt"] == 0:
                    now_iso = datetime.now(timezone.utc).isoformat()
                    defaults = [
                        ("USR-TECH-01", "tech.anil", hash_password("Tech@123"), "Anil Kumar (Lab Technician)", "Technician"),
                        ("USR-AUDIT-01", "auditor.meera", hash_password("Audit@123"), "Meera Sen (Quality Auditor)", "Auditor"),
                        ("USR-DOC-01", "dr.sunita", hash_password("Doctor@123"), "Dr. Sunita Rao (Lead Pathologist)", "Pathologist"),
                        ("USR-ADMIN-01", "admin.synapse", hash_password("Admin@123"), "Synapse Administrator", "Administrator"),
                    ]
                    conn.executemany(
                        "INSERT INTO users (user_id, username, password_hash, full_name, role, is_active, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                        [(u[0], u[1], u[2], u[3], u[4], now_iso) for u in defaults],
                    )
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Patient & Demographics Operations
    # -------------------------------------------------------------------------

    def save_patient(self, demographics: PatientDemographics) -> None:
        """Create or update patient profile and demographics."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO patients (patient_id, patient_name, date_of_birth, age, sex, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(patient_id) DO UPDATE SET
                    patient_name = excluded.patient_name,
                    date_of_birth = coalesce(excluded.date_of_birth, patients.date_of_birth),
                    age = coalesce(excluded.age, patients.age),
                    sex = coalesce(excluded.sex, patients.sex);
                """,
                (
                    demographics.patient_id,
                    demographics.patient_name,
                    demographics.date_of_birth,
                    demographics.age,
                    demographics.sex,
                    now_iso,
                ),
            )
            for entry in demographics.medical_history:
                conn.execute(
                    """
                    INSERT INTO medical_history (entry_id, patient_id, condition_or_event, entry_date, source, notes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(entry_id) DO UPDATE SET
                        condition_or_event = excluded.condition_or_event,
                        entry_date = excluded.entry_date,
                        source = excluded.source,
                        notes = excluded.notes;
                    """,
                    (
                        entry.entry_id,
                        demographics.patient_id,
                        entry.condition_or_event,
                        entry.entry_date,
                        entry.source,
                        entry.notes,
                    ),
                )

    def add_medical_history_entry(self, patient_id: str, entry: MedicalHistoryEntry) -> None:
        """Add a specific medical history record for an existing patient."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO medical_history (entry_id, patient_id, condition_or_event, entry_date, source, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(entry_id) DO UPDATE SET
                    condition_or_event = excluded.condition_or_event,
                    entry_date = excluded.entry_date,
                    source = excluded.source,
                    notes = excluded.notes;
                """,
                (
                    entry.entry_id,
                    patient_id,
                    entry.condition_or_event,
                    entry.entry_date,
                    entry.source,
                    entry.notes,
                ),
            )

    def get_patient_demographics(self, patient_id: str) -> Optional[PatientDemographics]:
        """Fetch patient demographics and history without reports."""
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM patients WHERE patient_id = ?", (patient_id,))
            p_row = cur.fetchone()
            if not p_row:
                return None

            hist_cur = conn.execute(
                "SELECT * FROM medical_history WHERE patient_id = ? ORDER BY entry_date DESC",
                (patient_id,),
            )
            history = [
                MedicalHistoryEntry(
                    entry_id=h["entry_id"],
                    condition_or_event=h["condition_or_event"],
                    entry_date=h["entry_date"],
                    source=h["source"],
                    notes=h["notes"],
                )
                for h in hist_cur.fetchall()
            ]

            return PatientDemographics(
                patient_id=p_row["patient_id"],
                patient_name=p_row["patient_name"],
                date_of_birth=p_row["date_of_birth"],
                age=p_row["age"],
                sex=p_row["sex"],
                medical_history=history,
            )

    def list_patients(self) -> List[Dict[str, Any]]:
        """List all registered patients with report counts and latest report date."""
        with self._get_connection() as conn:
            cur = conn.execute("""
                SELECT p.*, count(r.report_id) as report_count, max(r.report_date) as latest_report_date
                FROM patients p
                LEFT JOIN reports r ON p.patient_id = r.patient_id
                GROUP BY p.patient_id
                ORDER BY p.patient_name ASC;
            """)
            return [dict(row) for row in cur.fetchall()]

    def find_duplicate_report(
        self,
        patient_id: str,
        original_filename: str,
        content_hash: Optional[str] = None,
    ) -> Optional[PatientReport]:
        """
        Check if an identical report has already been ingested.
        Matches on:
        1. content_hash (if provided), OR
        2. same patient_id and same original_filename.
        """
        with self._get_connection() as conn:
            if content_hash:
                cur = conn.execute(
                    "SELECT report_id FROM reports WHERE patient_id = ? AND content_hash = ?",
                    (patient_id, content_hash),
                )
                row = cur.fetchone()
                if row:
                    return self.get_report(row["report_id"])

            cur = conn.execute(
                "SELECT report_id FROM reports WHERE patient_id = ? AND original_filename = ?",
                (patient_id, original_filename),
            )
            row = cur.fetchone()
            if row:
                return self.get_report(row["report_id"])
        return None

    def get_available_parameters(self, patient_id: str) -> List[Dict[str, Any]]:
        """
        Return the list of standardized parameters with observations for this patient.
        """
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT
                    standardized_name,
                    count(parameter_id) as observation_count,
                    max(report_date) as latest_date,
                    unit
                FROM parameters
                WHERE patient_id = ? AND standardized_name IS NOT NULL
                GROUP BY standardized_name
                ORDER BY observation_count DESC, standardized_name ASC;
                """,
                (patient_id,),
            )
            return [dict(row) for row in cur.fetchall()]

    # -------------------------------------------------------------------------
    # Report & Parameter Operations
    # -------------------------------------------------------------------------

    def save_report(self, report: PatientReport) -> None:
        """Save a report and all of its associated parameters."""
        # Ensure patient exists
        with self._get_connection() as conn:
            cur = conn.execute("SELECT patient_id FROM patients WHERE patient_id = ?", (report.patient_id,))
            if not cur.fetchone():
                conn.execute(
                    "INSERT INTO patients (patient_id, patient_name, created_at) VALUES (?, ?, ?)",
                    (report.patient_id, f"Patient {report.patient_id}", datetime.now(timezone.utc).isoformat()),
                )

            # Insert report
            conn.execute(
                """
                INSERT INTO reports (
                    report_id, patient_id, report_date, date_label, report_category,
                    original_filename, file_format, upload_datetime, extraction_status,
                    review_status, original_document_location, content_hash, key_text_sections_json,
                    document_level_flags_json, validation_errors_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(report_id) DO UPDATE SET
                    report_date = excluded.report_date,
                    date_label = excluded.date_label,
                    report_category = excluded.report_category,
                    extraction_status = excluded.extraction_status,
                    review_status = excluded.review_status,
                    original_document_location = excluded.original_document_location,
                    content_hash = excluded.content_hash,
                    key_text_sections_json = excluded.key_text_sections_json,
                    document_level_flags_json = excluded.document_level_flags_json,
                    validation_errors_json = excluded.validation_errors_json;
                """,
                (
                    report.report_id,
                    report.patient_id,
                    report.report_date,
                    report.date_label,
                    report.report_category,
                    report.original_filename,
                    report.file_format,
                    report.upload_datetime,
                    report.extraction_status,
                    report.review_status,
                    report.original_document_location,
                    report.content_hash,
                    json.dumps(report.key_text_sections),
                    json.dumps([f.model_dump() for f in report.document_level_flags]),
                    json.dumps(report.validation_errors),
                ),
            )

            # Delete old parameters if updating report
            conn.execute("DELETE FROM parameters WHERE report_id = ?", (report.report_id,))

            # Insert parameters
            for param in report.parameters:
                conn.execute(
                    """
                    INSERT INTO parameters (
                        parameter_id, report_id, patient_id, report_date, original_name,
                        standardized_name, result_value, unit, reference_range_text,
                        reference_low, reference_high, clinical_flag, abnormality_category,
                        extraction_status, source_text, review_flags_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        param.parameter_id,
                        param.report_id,
                        param.patient_id,
                        param.report_date,
                        param.original_name,
                        param.standardized_name,
                        param.result_value,
                        param.unit,
                        param.reference_range_text,
                        param.reference_low,
                        param.reference_high,
                        param.clinical_flag,
                        param.abnormality_category,
                        param.extraction_status,
                        param.source_text,
                        json.dumps([f.model_dump() for f in param.review_flags]),
                    ),
                )

    def get_report(self, report_id: str) -> Optional[PatientReport]:
        """Fetch a single report with its extracted parameters."""
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM reports WHERE report_id = ?", (report_id,))
            r = cur.fetchone()
            if not r:
                return None

            param_cur = conn.execute("SELECT * FROM parameters WHERE report_id = ?", (report_id,))
            params = []
            for p in param_cur.fetchall():
                flags = [ReviewFlag(**f) for f in json.loads(p["review_flags_json"] or "[]")]
                params.append(
                    ReportParameter(
                        parameter_id=p["parameter_id"],
                        report_id=p["report_id"],
                        patient_id=p["patient_id"],
                        original_name=p["original_name"],
                        standardized_name=p["standardized_name"],
                        result_value=p["result_value"],
                        unit=p["unit"],
                        reference_range_text=p["reference_range_text"],
                        reference_low=p["reference_low"],
                        reference_high=p["reference_high"],
                        clinical_flag=p["clinical_flag"],
                        abnormality_category=p["abnormality_category"],
                        extraction_status=p["extraction_status"],
                        source_text=p["source_text"],
                        review_flags=flags,
                        report_date=p["report_date"],
                    )
                )

            doc_flags = [ReviewFlag(**f) for f in json.loads(r["document_level_flags_json"] or "[]")]
            sections = json.loads(r["key_text_sections_json"] or "{}")
            errors = json.loads(r["validation_errors_json"] or "[]")
            history = self.get_report_review_history(report_id)

            return PatientReport(
                report_id=r["report_id"],
                patient_id=r["patient_id"],
                report_date=r["report_date"],
                date_label=r["date_label"],
                report_category=r["report_category"],
                original_filename=r["original_filename"],
                file_format=r["file_format"],
                upload_datetime=r["upload_datetime"],
                extraction_status=r["extraction_status"],
                review_status=r["review_status"],
                original_document_location=r["original_document_location"],
                content_hash=r["content_hash"] if "content_hash" in r.keys() else None,
                parameters=params,
                key_text_sections=sections,
                document_level_flags=doc_flags,
                validation_errors=errors,
                review_history=history,
            )

    def list_patient_reports(
        self,
        patient_id: str,
        category: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        search_query: Optional[str] = None,
    ) -> List[PatientReport]:
        """
        List all reports belonging to a patient, chronologically sorted by report_date.
        Supports filtering by category, date range, and parameter search query.
        """
        query = "SELECT DISTINCT r.report_id FROM reports r LEFT JOIN parameters p ON r.report_id = p.report_id WHERE r.patient_id = ?"
        params: List[Any] = [patient_id]

        if category:
            query += " AND r.report_category = ?"
            params.append(category)

        if start_date:
            query += " AND r.report_date >= ?"
            params.append(start_date)

        if end_date:
            query += " AND r.report_date <= ?"
            params.append(end_date)

        if search_query:
            query += " AND (p.original_name LIKE ? OR p.standardized_name LIKE ? OR r.report_category LIKE ?)"
            wildcard = f"%{search_query.strip()}%"
            params.extend([wildcard, wildcard, wildcard])

        # Chronological sort: newest first, unknown dates last
        query += " ORDER BY CASE WHEN r.report_date IS NULL THEN 1 ELSE 0 END, r.report_date DESC, r.report_id ASC"

        with self._get_connection() as conn:
            cur = conn.execute(query, params)
            report_ids = [row["report_id"] for row in cur.fetchall()]

        results = []
        for rid in report_ids:
            rep = self.get_report(rid)
            if rep:
                results.append(rep)
        return results

    def get_patient(self, patient_id: str) -> Optional[Patient]:
        """Fetch the full patient entity with demographics and all linked reports."""
        demographics = self.get_patient_demographics(patient_id)
        if not demographics:
            return None
        reports = self.list_patient_reports(patient_id)
        return Patient(
            patient_id=patient_id,
            demographics=demographics,
            reports=reports,
        )

    # -------------------------------------------------------------------------
    # Calendar & Longitudinal Views
    # -------------------------------------------------------------------------

    def get_calendar_view(self, patient_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group reports by report_date for calendar visualization.
        Reports without report_date are grouped under 'unknown_date'.
        """
        reports = self.list_patient_reports(patient_id)
        calendar: Dict[str, List[Dict[str, Any]]] = {}
        for r in reports:
            key = r.report_date if r.report_date else "unknown_date"
            if key not in calendar:
                calendar[key] = []
            calendar[key].append({
                "report_id": r.report_id,
                "report_category": r.report_category,
                "filename": r.original_filename,
                "file_format": r.file_format,
                "extraction_status": r.extraction_status,
                "review_status": r.review_status,
                "parameter_count": len(r.parameters),
            })
        return calendar

    def get_longitudinal_parameters(
        self, patient_id: str, standardized_name: str
    ) -> List[ReportParameter]:
        """
        Retrieve parameter values across reports chronologically for trend analysis.
        Sorted by report_date ASC.
        """
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT * FROM parameters
                WHERE patient_id = ? AND standardized_name = ? AND report_date IS NOT NULL
                ORDER BY report_date ASC, parameter_id ASC;
                """,
                (patient_id, standardized_name),
            )
            params = []
            for p in cur.fetchall():
                flags = [ReviewFlag(**f) for f in json.loads(p["review_flags_json"] or "[]")]
                params.append(
                    ReportParameter(
                        parameter_id=p["parameter_id"],
                        report_id=p["report_id"],
                        patient_id=p["patient_id"],
                        original_name=p["original_name"],
                        standardized_name=p["standardized_name"],
                        result_value=p["result_value"],
                        unit=p["unit"],
                        reference_range_text=p["reference_range_text"],
                        reference_low=p["reference_low"],
                        reference_high=p["reference_high"],
                        clinical_flag=p["clinical_flag"],
                        abnormality_category=p["abnormality_category"],
                        extraction_status=p["extraction_status"],
                        source_text=p["source_text"],
                        review_flags=flags,
                        report_date=p["report_date"],
                    )
                )
            return params

    def get_abnormal_summary(self, report_id: str) -> Dict[str, List[ReportParameter]]:
        """
        Classify all parameters of a report into:
        - below_range
        - above_range
        - within_range
        - reference_range_unavailable
        - requires_review
        """
        rep = self.get_report(report_id)
        if not rep:
            return {
                "below_range": [],
                "above_range": [],
                "within_range": [],
                "reference_range_unavailable": [],
                "requires_review": [],
            }

        summary: Dict[str, List[ReportParameter]] = {
            "below_range": [],
            "above_range": [],
            "within_range": [],
            "reference_range_unavailable": [],
            "requires_review": [],
        }

        for param in rep.parameters:
            cat = param.abnormality_category
            if cat in summary:
                summary[cat].append(param)
            else:
                summary["requires_review"].append(param)

        return summary

    # -------------------------------------------------------------------------
    # Pipeline Adapter: ExtractedDocument -> PatientReport & Parameters
    # -------------------------------------------------------------------------

    def ingest_extracted_document(
        self,
        doc: ExtractedDocument,
        original_location: Optional[str] = None,
        file_format: str = "txt",
        content_hash: Optional[str] = None,
    ) -> PatientReport:
        """
        Bridge Phase 1/2 ExtractedDocument directly into PatientReport & ReportParameter entities.
        Saves patient, report, and parameters into the digital wallet.
        """
        patient_id = doc.patient_id or "UNKNOWN-PATIENT"
        patient_name = doc.patient_name or f"Patient {patient_id}"

        # Ensure demographics record
        existing_demo = self.get_patient_demographics(patient_id)
        if not existing_demo:
            self.save_patient(
                PatientDemographics(
                    patient_id=patient_id,
                    patient_name=patient_name,
                    date_of_birth=None,
                    age=None,
                    sex=None,
                    medical_history=[],
                )
            )

        # Map document_type to category
        category_map = {
            "lab report": "CBC / Hematology" if "cbc" in doc.source_file.lower() else "Biochemistry",
            "radiology": "Imaging",
            "ultrasound": "Imaging",
            "clinical note": "Clinical Note",
            "prescription": "Prescription",
            "mixed": "Mixed Diagnostic",
        }
        category = category_map.get(doc.document_type, "Other")
        if "lipid" in doc.source_file.lower():
            category = "Lipid Profile"
        elif "renal" in doc.source_file.lower():
            category = "Kidney Function Test"
        elif "thyroid" in doc.source_file.lower():
            category = "Thyroid Profile"

        # Determine overall extraction status
        has_error_flags = any(f.severity == "error" for f in doc.review_flags)
        if "needs OCR" in doc.source_file:
            ext_status = "ocr_required"
        elif has_error_flags or len(doc.validation_errors) > 0:
            ext_status = "needs_review"
        else:
            ext_status = "success"

        # Determine review status
        unsupported = any(r.extraction_status == "unsupported" for r in doc.lab_results)
        needs_rev = any(r.extraction_status == "needs_review" for r in doc.lab_results) or has_error_flags
        if unsupported:
            rev_status = "unsupported_parameters"
        elif needs_rev:
            rev_status = "needs_review"
        else:
            rev_status = "clean"

        # Reuse existing report_id if re-ingesting identical report
        existing = self.find_duplicate_report(patient_id, doc.source_file, content_hash=content_hash)
        report_id = existing.report_id if existing else f"REP-{uuid.uuid4().hex[:8].upper()}"

        # Convert lab results to ReportParameters
        parameters: List[ReportParameter] = []
        for idx, res in enumerate(doc.lab_results):
            param_id = f"PRM-{report_id}-{idx + 1:03d}"
            std_name = standardize_parameter_name(res.test_name)
            abnorm_cat = classify_abnormality(res)

            parameters.append(
                ReportParameter(
                    parameter_id=param_id,
                    report_id=report_id,
                    patient_id=patient_id,
                    original_name=res.test_name,
                    standardized_name=std_name,
                    result_value=res.result_value,
                    unit=res.unit,
                    reference_range_text=res.reference_range_text,
                    reference_low=res.reference_low,
                    reference_high=res.reference_high,
                    clinical_flag=res.flag,
                    abnormality_category=abnorm_cat,
                    extraction_status=res.extraction_status,
                    source_text=res.source_text,
                    review_flags=res.review_flags,
                    report_date=doc.document_date,
                )
            )

        report = PatientReport(
            report_id=report_id,
            patient_id=patient_id,
            report_date=doc.document_date,
            date_label=doc.date_label,
            report_category=category,
            original_filename=doc.source_file,
            file_format=file_format,
            upload_datetime=datetime.now(timezone.utc).isoformat(),
            extraction_status=ext_status,
            review_status=rev_status,
            original_document_location=original_location or doc.source_file,
            content_hash=content_hash,
            parameters=parameters,
            key_text_sections=doc.key_text_sections,
            document_level_flags=doc.review_flags,
            validation_errors=doc.validation_errors,
        )

        self.save_report(report)
        return report

    def ingest_api_json_record(self, data: Dict[str, Any], content_hash: Optional[str] = None) -> PatientReport:
        """
        Ingest a structured digital report payload from mock API or JSON file.
        Validates structure and normalises into PatientReport & ReportParameters.
        """
        patient_id = data.get("patient_id")
        if not patient_id:
            raise ValueError("API record rejected: missing required 'patient_id'")

        patient_name = data.get("patient_name", f"Patient {patient_id}")
        existing_demo = self.get_patient_demographics(patient_id)
        if not existing_demo:
            self.save_patient(
                PatientDemographics(
                    patient_id=patient_id,
                    patient_name=patient_name,
                    date_of_birth=None,
                    age=None,
                    sex=None,
                    medical_history=[],
                )
            )

        report_id = data.get("report_id") or f"API-{uuid.uuid4().hex[:8].upper()}"
        report_date = data.get("report_date")
        date_label = data.get("date_label", "Report Date")
        report_category = data.get("report_category", "Biochemistry")

        raw_params = data.get("parameters", [])
        parameters: List[ReportParameter] = []

        for idx, item in enumerate(raw_params):
            param_id = f"PRM-{report_id}-{idx + 1:03d}"
            orig_name = item.get("test_name", f"Param_{idx + 1}")
            val = item.get("result_value")
            unit = item.get("unit")
            ref_text = item.get("reference_range_text")
            ref_low = item.get("reference_low")
            ref_high = item.get("reference_high")

            # Determine clinical flag
            flag = "unknown"
            if val is not None and ref_low is not None and ref_high is not None:
                if val < ref_low:
                    flag = "low"
                elif val > ref_high:
                    flag = "high"
                else:
                    flag = "normal"
            elif val is not None and ref_high is not None and ref_low is None:
                flag = "high" if val > ref_high else "normal"

            # Determine abnormality category
            if val is None:
                cat = "requires_review"
            elif ref_text is None and ref_low is None and ref_high is None:
                cat = "reference_range_unavailable"
            elif flag == "low":
                cat = "below_range"
            elif flag == "high":
                cat = "above_range"
            elif flag == "normal":
                cat = "within_range"
            else:
                cat = "reference_range_unavailable"

            std_name = standardize_parameter_name(orig_name)
            flags: List[ReviewFlag] = []
            status = "ok"

            if val is None:
                status = "needs_review"
                flags.append(ReviewFlag(field="result_value", reason="Missing result value in API payload", severity="error"))
            if not unit and "ratio" not in orig_name.lower():
                status = "needs_review"
                flags.append(ReviewFlag(field="unit", reason="Missing unit in API payload", severity="warning"))
            if not std_name:
                flags.append(ReviewFlag(field="test_name", reason=f"Unrecognized parameter '{orig_name}'", severity="info"))

            parameters.append(
                ReportParameter(
                    parameter_id=param_id,
                    report_id=report_id,
                    patient_id=patient_id,
                    original_name=orig_name,
                    standardized_name=std_name,
                    result_value=val,
                    unit=unit,
                    reference_range_text=ref_text,
                    reference_low=ref_low,
                    reference_high=ref_high,
                    clinical_flag=flag,
                    abnormality_category=cat,
                    extraction_status=status,
                    source_text=f"API: {orig_name} = {val} {unit or ''} ({ref_text or ''})",
                    review_flags=flags,
                    report_date=report_date,
                )
            )

        report = PatientReport(
            report_id=report_id,
            patient_id=patient_id,
            report_date=report_date,
            date_label=date_label,
            report_category=report_category,
            original_filename=f"{report_id}.json",
            file_format="json",
            upload_datetime=datetime.now(timezone.utc).isoformat(),
            extraction_status="success",
            review_status="clean" if all(p.extraction_status == "ok" for p in parameters) else "needs_review",
            original_document_location=f"api://payloads/{report_id}",
            content_hash=content_hash,
            parameters=parameters,
            key_text_sections={"API Notes": data.get("notes", "")} if data.get("notes") else {},
            document_level_flags=[],
            validation_errors=[],
        )

        self.save_report(report)
        return report

    # -------------------------------------------------------------------------
    # Review Queue & Field Correction Operations (Phase 6B)
    # -------------------------------------------------------------------------

    def record_review_action(
        self,
        report_id: str,
        action: str,
        reviewer: str,
        comments: Optional[str] = None,
        corrections: Optional[List[FieldCorrection]] = None,
    ) -> ReviewAuditEntry:
        """
        Record a review action (approve, reject, needs_review, correct_field)
        and update the report's review_status in storage.
        """
        valid_actions = {"approve", "reject", "needs_review", "correct_field"}
        if action not in valid_actions:
            raise ValueError(f"Invalid review action '{action}'. Must be one of {valid_actions}")

        status_mapping = {
            "approve": "approved",
            "reject": "rejected",
            "needs_review": "needs_review",
            "correct_field": "corrected",
        }
        new_status = status_mapping[action]

        with self._get_connection() as conn:
            cur = conn.execute("SELECT review_status FROM reports WHERE report_id = ?", (report_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Report '{report_id}' not found.")
            prev_status = row["review_status"]

            now_iso = datetime.now(timezone.utc).isoformat()
            audit_id = f"AUDIT-{uuid.uuid4().hex[:8].upper()}"
            corrections_json = json.dumps([c.model_dump() for c in (corrections or [])])

            conn.execute(
                """
                INSERT INTO review_audit (
                    audit_id, report_id, action, reviewer, timestamp,
                    previous_status, new_status, comments, corrections_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (audit_id, report_id, action, reviewer, now_iso, prev_status, new_status, comments, corrections_json),
            )
            conn.execute("UPDATE reports SET review_status = ? WHERE report_id = ?", (new_status, report_id))

        return ReviewAuditEntry(
            entry_id=audit_id,
            report_id=report_id,
            action=action,
            reviewer=reviewer,
            timestamp=now_iso,
            previous_status=prev_status,
            new_status=new_status,
            comments=comments,
            corrections=corrections or [],
        )

    def correct_report_parameter(
        self,
        report_id: str,
        parameter_id: str,
        corrected_value: Optional[float],
        corrected_name: Optional[str],
        corrected_unit: Optional[str],
        reviewer: str,
        reason: str,
    ) -> Dict[str, Any]:
        """
        Apply a field-level human correction to an extracted report parameter.
        Re-evaluates abnormality and clinical flag, maintaining a full audit trail.
        """
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM parameters WHERE parameter_id = ? AND report_id = ?",
                (parameter_id, report_id),
            )
            p_row = cur.fetchone()
            if not p_row:
                raise ValueError(f"Parameter '{parameter_id}' in report '{report_id}' not found.")

            orig_val = p_row["result_value"]
            orig_name = p_row["original_name"]
            orig_unit = p_row["unit"]

            new_val = corrected_value if corrected_value is not None else orig_val
            new_name = corrected_name if corrected_name is not None else orig_name
            new_unit = corrected_unit if corrected_unit is not None else orig_unit

            ref_low = p_row["reference_low"]
            ref_high = p_row["reference_high"]
            ref_text = p_row["reference_range_text"]

            # Determine clinical flag
            flag = "unknown"
            if new_val is not None and ref_low is not None and ref_high is not None:
                if new_val < ref_low:
                    flag = "low"
                elif new_val > ref_high:
                    flag = "high"
                else:
                    flag = "normal"
            elif new_val is not None and ref_high is not None and ref_low is None:
                flag = "high" if new_val > ref_high else "normal"

            # Determine abnormality category
            if new_val is None:
                cat = "requires_review"
            elif ref_text is None and ref_low is None and ref_high is None:
                cat = "reference_range_unavailable"
            elif flag == "low":
                cat = "below_range"
            elif flag == "high":
                cat = "above_range"
            elif flag == "normal":
                cat = "within_range"
            else:
                cat = "reference_range_unavailable"

            std_name = standardize_parameter_name(new_name)

            conn.execute(
                """
                UPDATE parameters
                SET original_name = ?, standardized_name = ?, result_value = ?,
                    unit = ?, clinical_flag = ?, abnormality_category = ?, extraction_status = 'ok'
                WHERE parameter_id = ?
                """,
                (new_name, std_name, new_val, new_unit, flag, cat, parameter_id),
            )

        correction = FieldCorrection(
            field_name=orig_name,
            original_value=orig_val,
            corrected_value=new_val,
            reviewer=reviewer,
            timestamp=datetime.now(timezone.utc).isoformat(),
            reason=reason,
        )

        audit_entry = self.record_review_action(
            report_id=report_id,
            action="correct_field",
            reviewer=reviewer,
            comments=f"Field corrected: {orig_name} ({orig_val} -> {new_val}). Reason: {reason}",
            corrections=[correction],
        )

        return {
            "parameter_id": parameter_id,
            "report_id": report_id,
            "original_name": new_name,
            "result_value": new_val,
            "unit": new_unit,
            "clinical_flag": flag,
            "abnormality_category": cat,
            "audit_entry": audit_entry.model_dump(),
        }

    def get_report_review_history(self, report_id: str) -> List[ReviewAuditEntry]:
        """Fetch chronological audit history for a report."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM review_audit WHERE report_id = ? ORDER BY timestamp ASC",
                (report_id,),
            )
            rows = cur.fetchall()

        entries: List[ReviewAuditEntry] = []
        for r in rows:
            corrs = []
            if r["corrections_json"]:
                try:
                    raw_c = json.loads(r["corrections_json"])
                    corrs = [FieldCorrection(**c) for c in raw_c]
                except Exception:
                    pass
            entries.append(
                ReviewAuditEntry(
                    entry_id=r["audit_id"],
                    report_id=r["report_id"],
                    action=r["action"],
                    reviewer=r["reviewer"],
                    timestamp=r["timestamp"],
                    previous_status=r["previous_status"],
                    new_status=r["new_status"],
                    comments=r["comments"],
                    corrections=corrs,
                )
            )
        return entries

    def list_review_queue(self, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all reports requiring human review or matching status_filter.
        """
        with self._get_connection() as conn:
            if status_filter:
                cur = conn.execute(
                    """
                    SELECT r.*, p.patient_name
                    FROM reports r
                    LEFT JOIN patients p ON r.patient_id = p.patient_id
                    WHERE r.review_status = ?
                    ORDER BY r.upload_datetime DESC
                    """,
                    (status_filter,),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT r.*, p.patient_name
                    FROM reports r
                    LEFT JOIN patients p ON r.patient_id = p.patient_id
                    WHERE r.review_status IN ('needs_review', 'unsupported_parameters', 'corrected')
                    ORDER BY r.upload_datetime DESC
                    """
                )
            rows = cur.fetchall()

        queue_items = []
        for r in rows:
            queue_items.append(
                {
                    "report_id": r["report_id"],
                    "patient_id": r["patient_id"],
                    "patient_name": r["patient_name"] or f"Patient {r['patient_id']}",
                    "report_date": r["report_date"],
                    "report_category": r["report_category"],
                    "original_filename": r["original_filename"],
                    "extraction_status": r["extraction_status"],
                    "review_status": r["review_status"],
                    "upload_datetime": r["upload_datetime"],
                }
            )
        return queue_items

    # -------------------------------------------------------------------------
    # User & Authentication Operations (Phase 7A / 7B)
    # -------------------------------------------------------------------------

    def create_user(
        self,
        username: str,
        password_hash: str,
        full_name: str,
        role: str,
    ) -> User:
        """Register a new system user with assigned RBAC role."""
        user_id = f"USR-{uuid.uuid4().hex[:8].upper()}"
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, username, password_hash, full_name, role, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (user_id, username.strip().lower(), password_hash, full_name, role, now_iso),
            )
        return User(
            user_id=user_id,
            username=username.strip().lower(),
            full_name=full_name,
            role=role,
            is_active=True,
        )

    def get_user_by_username(self, username: str) -> Optional[UserInDB]:
        """Fetch user by case-insensitive username."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM users WHERE LOWER(username) = ? AND is_active = 1",
                (username.strip().lower(),),
            )
            row = cur.fetchone()
            if not row:
                return None
            return UserInDB(
                user_id=row["user_id"],
                username=row["username"],
                password_hash=row["password_hash"],
                full_name=row["full_name"],
                role=row["role"],
                is_active=bool(row["is_active"]),
            )

    def get_user_by_id(self, user_id: str) -> Optional[UserInDB]:
        """Fetch user by user_id."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM users WHERE user_id = ? AND is_active = 1",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return UserInDB(
                user_id=row["user_id"],
                username=row["username"],
                password_hash=row["password_hash"],
                full_name=row["full_name"],
                role=row["role"],
                is_active=bool(row["is_active"]),
            )

    def list_users(self) -> List[User]:
        """List all registered system users."""
        with self._get_connection() as conn:
            cur = conn.execute("SELECT user_id, username, full_name, role, is_active FROM users ORDER BY created_at ASC")
            rows = cur.fetchall()
            return [
                User(
                    user_id=r["user_id"],
                    username=r["username"],
                    full_name=r["full_name"],
                    role=r["role"],
                    is_active=bool(r["is_active"]),
                )
                for r in rows
            ]


