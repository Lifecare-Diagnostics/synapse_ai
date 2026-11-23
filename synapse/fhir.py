"""
synapse_poc/synapse/fhir.py
HL7 FHIR R4 & HL7 v2 Interoperability Layer for Synapse AI.
Provides bidirectional mapping, validation, ingestion, and export
for Patient, DiagnosticReport, and Observation resources,
along with separate HL7 v2 ORU^R01 message parsing.
"""

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple
import uuid

from synapse.schema import (
    PatientDemographics,
    PatientReport,
    ReportParameter,
    Patient,
    ReviewFlag,
)
from synapse.standardizer import standardize_parameter_name, classify_abnormality

FHIR_SPEC_VERSION = "4.0.1"
SYSTEM_PATIENT_ID = "urn:lifecare:patient:id"
SYSTEM_REPORT_ID = "urn:lifecare:report:id"
SYSTEM_OBSERVATION_ID = "urn:lifecare:observation:id"
SYSTEM_UCUM = "http://unitsofmeasure.org"
SYSTEM_LOINC = "http://loinc.org"
SYSTEM_DIAGNOSTIC_SERVICE = "http://terminology.hl7.org/CodeSystem/v2-0074"
SYSTEM_OBSERVATION_CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"

# In-memory interop audit trail
_INTEROP_AUDIT_LOG: List[Dict[str, Any]] = []


def record_interop_audit(
    action: str,
    format_type: str,
    resource_count: int,
    status: str,
    identifier: Optional[str] = None,
    details: Optional[str] = None,
) -> Dict[str, Any]:
    """Record an interoperability transaction in the integration audit log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "format": format_type,
        "resource_count": resource_count,
        "status": status,
        "identifier": identifier,
        "details": details or "",
    }
    _INTEROP_AUDIT_LOG.append(entry)
    return entry


def get_interop_audit_logs(limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve recent interop audit events."""
    return _INTEROP_AUDIT_LOG[-limit:]


def get_interop_status() -> Dict[str, Any]:
    """
    Return interoperability capability metadata.
    Explicitly indicates mock/synthetic integration status.
    """
    return {
        "fhir_version": FHIR_SPEC_VERSION,
        "supported_resources": ["Patient", "DiagnosticReport", "Observation", "Bundle"],
        "hl7_version": "2.5.1",
        "supported_hl7_messages": ["ORU^R01"],
        "connection_mode": "mock_synthetic_gateway",
        "live_ehr_connected": False,
        "supported_protocols": ["REST/JSON", "MLLP/TCP", "SMART-on-FHIR"],
        "mllp": {
            "supported": True,
            "default_port": 2575,
            "framing": "MLLP v1 (VT/FS-CR)",
            "status": "ready",
            "connection_mode": "mllp_simulated_listener",
        },
        "smart_on_fhir": {
            "supported": True,
            "version": "2.0.0",
            "pkce_required": True,
            "auth_flows": ["standalone-launch", "ehr-launch"],
            "status": "ready",
            "connection_mode": "smart_synthetic_client",
        },
        "description": (
            "Life Care Diagnostics Synapse AI Interoperability Gateway. "
            "Supports local FHIR R4 JSON, HL7 v2 ORU^R01 parsing/export, "
            "secure MLLP framing/listener, and SMART-on-FHIR OAuth2 client launch architecture. "
            "Production EHR/LIS integrations run in sandboxed synthetic mode."
        ),
        "total_audit_events": len(_INTEROP_AUDIT_LOG),
    }


# ==============================================================================
# FHIR R4 Builders (Synapse -> FHIR Export)
# ==============================================================================

def build_fhir_patient(demographics: PatientDemographics) -> Dict[str, Any]:
    """Convert Synapse PatientDemographics to a FHIR R4 Patient resource."""
    gender = "unknown"
    if demographics.sex:
        s = demographics.sex.strip().lower()
        if s in ("male", "m"):
            gender = "male"
        elif s in ("female", "f"):
            gender = "female"
        elif s in ("other", "o"):
            gender = "other"

    resource: Dict[str, Any] = {
        "resourceType": "Patient",
        "id": demographics.patient_id.replace(" ", "-"),
        "identifier": [
            {
                "system": SYSTEM_PATIENT_ID,
                "value": demographics.patient_id,
            }
        ],
        "name": [
            {
                "use": "official",
                "text": demographics.patient_name,
            }
        ],
        "gender": gender,
    }

    if demographics.date_of_birth:
        resource["birthDate"] = demographics.date_of_birth

    return resource


def build_fhir_observation(parameter: ReportParameter) -> Dict[str, Any]:
    """Convert Synapse ReportParameter to a FHIR R4 Observation resource."""
    obs_id = parameter.parameter_id.replace(" ", "-")
    interpretation_code = "N"
    interpretation_display = "Normal"
    if parameter.clinical_flag == "low":
        interpretation_code = "L"
        interpretation_display = "Low"
    elif parameter.clinical_flag == "high":
        interpretation_code = "H"
        interpretation_display = "High"

    resource: Dict[str, Any] = {
        "resourceType": "Observation",
        "id": obs_id,
        "identifier": [
            {
                "system": SYSTEM_OBSERVATION_ID,
                "value": parameter.parameter_id,
            }
        ],
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": SYSTEM_OBSERVATION_CATEGORY,
                        "code": "laboratory",
                        "display": "Laboratory",
                    }
                ]
            }
        ],
        "code": {
            "text": parameter.original_name,
            "coding": [],
        },
        "subject": {
            "reference": f"Patient/{parameter.patient_id}",
            "type": "Patient",
        },
    }

    if parameter.standardized_name:
        resource["code"]["coding"].append(
            {
                "system": "urn:lifecare:synapse:parameters",
                "code": parameter.standardized_name,
                "display": parameter.standardized_name,
            }
        )

    if parameter.report_date:
        resource["effectiveDateTime"] = parameter.report_date

    # Observation Value
    if parameter.result_value is not None:
        resource["valueQuantity"] = {
            "value": float(parameter.result_value),
            "unit": parameter.unit or "1",
            "system": SYSTEM_UCUM,
        }
    else:
        resource["valueString"] = "Not Recorded"

    # Reference Range
    ref_range: Dict[str, Any] = {}
    if parameter.reference_low is not None:
        ref_range["low"] = {
            "value": float(parameter.reference_low),
            "unit": parameter.unit or "",
        }
    if parameter.reference_high is not None:
        ref_range["high"] = {
            "value": float(parameter.reference_high),
            "unit": parameter.unit or "",
        }
    if parameter.reference_range_text:
        ref_range["text"] = parameter.reference_range_text

    if ref_range:
        resource["referenceRange"] = [ref_range]

    # Clinical Flag / Interpretation
    if parameter.clinical_flag in ("low", "high", "normal"):
        resource["interpretation"] = [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                        "code": interpretation_code,
                        "display": interpretation_display,
                    }
                ],
                "text": interpretation_display,
            }
        ]

    return resource


def build_fhir_diagnostic_report(
    report: PatientReport,
    observation_refs: List[str],
) -> Dict[str, Any]:
    """Convert Synapse PatientReport to a FHIR R4 DiagnosticReport resource."""
    rep_id = report.report_id.replace(" ", "-")

    resource: Dict[str, Any] = {
        "resourceType": "DiagnosticReport",
        "id": rep_id,
        "identifier": [
            {
                "system": SYSTEM_REPORT_ID,
                "value": report.report_id,
            }
        ],
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": SYSTEM_DIAGNOSTIC_SERVICE,
                        "code": "LAB",
                        "display": "Laboratory",
                    }
                ]
            }
        ],
        "code": {
            "text": report.report_category,
        },
        "subject": {
            "reference": f"Patient/{report.patient_id}",
            "type": "Patient",
        },
        "result": [{"reference": f"Observation/{ref}"} for ref in observation_refs],
    }

    if report.report_date:
        resource["effectiveDateTime"] = report.report_date
    if report.upload_datetime:
        resource["issued"] = report.upload_datetime

    # Narrative Summary / Conclusion
    narratives = []
    if report.key_text_sections:
        for k, v in report.key_text_sections.items():
            narratives.append(f"{k}: {v}")
    if narratives:
        resource["conclusion"] = "\n".join(narratives)

    return resource


def export_report_to_fhir_bundle(
    report: PatientReport,
    demographics: Optional[PatientDemographics] = None,
) -> Dict[str, Any]:
    """
    Export a single PatientReport, its parameters, and associated patient demographics
    as a complete, validated FHIR R4 Bundle.
    """
    entries: List[Dict[str, Any]] = []

    # 1. Patient Resource
    if demographics:
        patient_res = build_fhir_patient(demographics)
    else:
        patient_res = {
            "resourceType": "Patient",
            "id": report.patient_id.replace(" ", "-"),
            "identifier": [{"system": SYSTEM_PATIENT_ID, "value": report.patient_id}],
            "name": [{"text": f"Patient {report.patient_id}"}],
        }
    entries.append({"resource": patient_res})

    # 2. Observations
    obs_ids: List[str] = []
    for param in report.parameters:
        obs_res = build_fhir_observation(param)
        obs_ids.append(obs_res["id"])
        entries.append({"resource": obs_res})

    # 3. DiagnosticReport
    diag_res = build_fhir_diagnostic_report(report, obs_ids)
    entries.append({"resource": diag_res})

    bundle_id = f"BUNDLE-{report.report_id.replace(' ', '-')}"
    bundle = {
        "resourceType": "Bundle",
        "id": bundle_id,
        "type": "collection",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(entries),
        "entry": entries,
    }

    record_interop_audit(
        action="export",
        format_type="fhir_r4",
        resource_count=len(entries),
        status="success",
        identifier=report.report_id,
        details=f"Exported DiagnosticReport {report.report_id} with {len(obs_ids)} observations.",
    )
    return bundle


def export_patient_to_fhir_bundle(patient: Patient) -> Dict[str, Any]:
    """
    Export an entire patient record (demographics and all associated reports/parameters)
    as a comprehensive FHIR R4 Bundle.
    """
    entries: List[Dict[str, Any]] = []
    patient_res = build_fhir_patient(patient.demographics)
    entries.append({"resource": patient_res})

    for rep in patient.reports:
        obs_ids: List[str] = []
        for param in rep.parameters:
            obs_res = build_fhir_observation(param)
            obs_ids.append(obs_res["id"])
            entries.append({"resource": obs_res})
        diag_res = build_fhir_diagnostic_report(rep, obs_ids)
        entries.append({"resource": diag_res})

    bundle_id = f"BUNDLE-PATIENT-{patient.patient_id.replace(' ', '-')}"
    bundle = {
        "resourceType": "Bundle",
        "id": bundle_id,
        "type": "collection",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(entries),
        "entry": entries,
    }

    record_interop_audit(
        action="export",
        format_type="fhir_r4",
        resource_count=len(entries),
        status="success",
        identifier=patient.patient_id,
        details=f"Exported Patient {patient.patient_id} with {len(patient.reports)} reports and {len(entries)} resources.",
    )
    return bundle


# ==============================================================================
# FHIR R4 Validation & Ingestion
# ==============================================================================

def validate_fhir_bundle(bundle_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate incoming FHIR R4 payload structure against essential rules.
    Returns (is_valid, validation_errors).
    """
    errors: List[str] = []
    if not isinstance(bundle_data, dict):
        return False, ["Payload must be a JSON object."]

    resource_type = bundle_data.get("resourceType")
    if resource_type != "Bundle":
        # Check if single supported resource
        if resource_type in ("DiagnosticReport", "Observation", "Patient"):
            return True, []
        return False, [f"Unsupported resourceType '{resource_type}'. Expected 'Bundle', 'DiagnosticReport', 'Observation', or 'Patient'."]

    entries = bundle_data.get("entry")
    if not isinstance(entries, list):
        return False, ["FHIR Bundle must contain an 'entry' list."]
    if len(entries) == 0:
        return False, ["FHIR Bundle 'entry' list is empty."]

    has_patient = False
    has_diagnostic = False

    for idx, e in enumerate(entries):
        if not isinstance(e, dict):
            errors.append(f"Entry #{idx} is not an object.")
            continue
        res = e.get("resource")
        if not isinstance(res, dict):
            errors.append(f"Entry #{idx} is missing 'resource' object.")
            continue

        rtype = res.get("resourceType")
        if not rtype:
            errors.append(f"Entry #{idx} resource missing 'resourceType'.")
        elif rtype == "Patient":
            has_patient = True
        elif rtype == "DiagnosticReport":
            has_diagnostic = True
            if not res.get("code"):
                errors.append(f"DiagnosticReport in entry #{idx} is missing 'code'.")
            if not res.get("subject"):
                errors.append(f"DiagnosticReport in entry #{idx} is missing 'subject'.")
        elif rtype == "Observation":
            if not res.get("code"):
                errors.append(f"Observation in entry #{idx} is missing 'code'.")

    return (len(errors) == 0), errors


def parse_fhir_bundle_to_synapse_record(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse a FHIR R4 Bundle into Synapse ingestion structures:
    Returns {
        "demographics": PatientDemographics,
        "report_id": str,
        "patient_id": str,
        "report_date": Optional[str],
        "report_category": str,
        "parameters": List[Dict[str, Any]],
        "key_text_sections": Dict[str, str],
        "source_summary": str
    }
    """
    is_valid, errors = validate_fhir_bundle(bundle)
    if not is_valid:
        raise ValueError(f"FHIR validation failed: {'; '.join(errors)}")

    entries = bundle.get("entry", [])
    patient_res: Optional[Dict[str, Any]] = None
    report_res: Optional[Dict[str, Any]] = None
    observations: List[Dict[str, Any]] = []

    for e in entries:
        res = e.get("resource", {})
        rtype = res.get("resourceType")
        if rtype == "Patient":
            patient_res = res
        elif rtype == "DiagnosticReport":
            report_res = res
        elif rtype == "Observation":
            observations.append(res)

    # 1. Parse Patient Demographics
    patient_id = "UNKNOWN-PATIENT"
    patient_name = "Unknown Patient"
    dob = None
    gender = None

    if patient_res:
        # Extract ID
        if patient_res.get("identifier"):
            patient_id = patient_res["identifier"][0].get("value") or patient_id
        elif patient_res.get("id"):
            patient_id = patient_res.get("id")

        # Extract Name
        names = patient_res.get("name", [])
        if names:
            patient_name = names[0].get("text") or " ".join(names[0].get("given", []) + [names[0].get("family", "")])
        dob = patient_res.get("birthDate")
        gender = patient_res.get("gender")

    # If subject was referenced in report, fallback
    if patient_id == "UNKNOWN-PATIENT" and report_res:
        subj = report_res.get("subject", {}).get("reference", "")
        if subj.startswith("Patient/"):
            patient_id = subj.split("/")[1]

    demographics = PatientDemographics(
        patient_id=patient_id,
        patient_name=patient_name or f"Patient {patient_id}",
        date_of_birth=dob,
        sex=gender.title() if gender else None,
        medical_history=[],
    )

    # 2. Parse DiagnosticReport Metadata
    report_id = f"FHIR-{uuid.uuid4().hex[:8].upper()}"
    report_date = None
    report_category = "Laboratory"
    key_sections = {}

    if report_res:
        if report_res.get("identifier"):
            report_id = report_res["identifier"][0].get("value") or report_id
        elif report_res.get("id"):
            report_id = report_res.get("id")

        report_date = report_res.get("effectiveDateTime")
        if report_date and len(report_date) >= 10:
            report_date = report_date[:10]  # Standardize YYYY-MM-DD

        code_obj = report_res.get("code", {})
        report_category = code_obj.get("text") or "Laboratory"

        if report_res.get("conclusion"):
            key_sections["Clinical Conclusion"] = report_res["conclusion"]

    # 3. Parse Observations into Parameters
    parameters: List[Dict[str, Any]] = []
    for obs in observations:
        obs_code = obs.get("code", {})
        orig_name = obs_code.get("text") or (obs_code.get("coding", [{}])[0].get("display") if obs_code.get("coding") else "Unknown Observation")

        val = None
        unit = None
        val_qty = obs.get("valueQuantity")
        if val_qty:
            val = val_qty.get("value")
            unit = val_qty.get("unit")
        elif obs.get("valueString"):
            # Try float conversion
            try:
                val = float(obs["valueString"])
            except Exception:
                val = None

        ref_low = None
        ref_high = None
        ref_text = None
        ref_ranges = obs.get("referenceRange", [])
        if ref_ranges:
            rr = ref_ranges[0]
            if rr.get("low"):
                ref_low = rr["low"].get("value")
            if rr.get("high"):
                ref_high = rr["high"].get("value")
            ref_text = rr.get("text") or (f"{ref_low} - {ref_high}" if ref_low is not None and ref_high is not None else None)

        parameters.append(
            {
                "original_name": orig_name,
                "result_value": val,
                "unit": unit,
                "reference_range_text": ref_text,
                "reference_low": ref_low,
                "reference_high": ref_high,
            }
        )

    record_interop_audit(
        action="ingest",
        format_type="fhir_r4",
        resource_count=len(entries),
        status="success",
        identifier=report_id,
        details=f"Parsed FHIR Bundle for Patient {patient_id} with {len(parameters)} observations.",
    )

    return {
        "demographics": demographics,
        "report_id": report_id,
        "patient_id": patient_id,
        "report_date": report_date,
        "report_category": report_category,
        "parameters": parameters,
        "key_text_sections": key_sections,
        "source_summary": f"FHIR R4 Bundle with {len(observations)} observations.",
    }


# ==============================================================================
# HL7 v2 ORU^R01 Message Parser (Separate from FHIR R4)
# ==============================================================================

def parse_hl7_v2_oru_r01(message: str) -> Dict[str, Any]:
    """
    Parse a standard HL7 v2.x ORU^R01 Observational Report message into Synapse structure.
    Parses MSH, PID, OBR, and OBX segments according to HL7 v2 standard rules.
    """
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Empty HL7 v2 message.")

    msh_found = False
    patient_id = "UNKNOWN-PATIENT"
    patient_name = "Unknown Patient"
    dob = None
    gender = None

    report_id = f"HL7-{uuid.uuid4().hex[:8].upper()}"
    report_date = None
    report_category = "Laboratory"
    observations: List[Dict[str, Any]] = []

    for line in lines:
        fields = line.split("|")
        seg = fields[0].upper()

        if seg == "MSH":
            msh_found = True
            # MSH-7 Date/Time of Message (e.g. 20261119120000)
            if len(fields) > 6 and fields[6]:
                raw_dt = fields[6]
                if len(raw_dt) >= 8:
                    report_date = f"{raw_dt[:4]}-{raw_dt[4:6]}-{raw_dt[6:8]}"
            # MSH-10 Message Control ID
            if len(fields) > 9 and fields[9]:
                report_id = f"HL7-{fields[9]}"

        elif seg == "PID":
            # PID-3 Patient Identifier List (ID^^^AssigningAuthority)
            if len(fields) > 3 and fields[3]:
                patient_id = fields[3].split("^")[0].strip() or patient_id
            # PID-5 Patient Name (Family^Given^Middle)
            if len(fields) > 5 and fields[5]:
                name_parts = fields[5].split("^")
                family = name_parts[0].strip() if len(name_parts) > 0 else ""
                given = name_parts[1].strip() if len(name_parts) > 1 else ""
                patient_name = f"{given} {family}".strip() or patient_name
            # PID-7 Date of Birth (YYYYMMDD)
            if len(fields) > 7 and fields[7] and len(fields[7]) >= 8:
                raw_dob = fields[7]
                dob = f"{raw_dob[:4]}-{raw_dob[4:6]}-{raw_dob[6:8]}"
            # PID-8 Administrative Sex (M/F/O)
            if len(fields) > 8 and fields[8]:
                raw_sex = fields[8].upper()
                gender = "Male" if raw_sex == "M" else ("Female" if raw_sex == "F" else "Other")

        elif seg == "OBR":
            # OBR-3 Filler Order Number / Report ID
            if len(fields) > 3 and fields[3]:
                report_id = f"HL7-{fields[3].split('^')[0].strip()}"
            # OBR-4 Universal Service Identifier (Code^Text^CodingSystem)
            if len(fields) > 4 and fields[4]:
                code_parts = fields[4].split("^")
                report_category = code_parts[1].strip() if len(code_parts) > 1 and code_parts[1].strip() else code_parts[0].strip()
            # OBR-7 Observation Date/Time
            if len(fields) > 7 and fields[7] and len(fields[7]) >= 8:
                raw_obr_dt = fields[7]
                report_date = f"{raw_obr_dt[:4]}-{raw_obr_dt[4:6]}-{raw_obr_dt[6:8]}"

        elif seg == "OBX":
            # OBX-2 Value Type (NM = Numeric, ST = String)
            # OBX-3 Observation Identifier (Code^Name^CodingSystem)
            # OBX-5 Observation Value
            # OBX-6 Units (Code^Text^CodingSystem)
            # OBX-7 References Range (e.g. 13.0 - 17.0)
            # OBX-8 Abnormal Flags (L, H, N, etc.)
            test_name = "Unknown Test"
            if len(fields) > 3 and fields[3]:
                test_parts = fields[3].split("^")
                test_name = test_parts[1].strip() if len(test_parts) > 1 and test_parts[1].strip() else test_parts[0].strip()

            raw_val = fields[5].strip() if len(fields) > 5 else None
            val_float = None
            if raw_val is not None:
                try:
                    val_float = float(raw_val)
                except ValueError:
                    val_float = None

            unit = None
            if len(fields) > 6 and fields[6]:
                unit = fields[6].split("^")[0].strip() or None

            ref_text = fields[7].strip() if len(fields) > 7 and fields[7].strip() else None
            ref_low = None
            ref_high = None
            if ref_text:
                m = re.search(r"([0-9.]+)\s*-\s*([0-9.]+)", ref_text)
                if m:
                    ref_low = float(m.group(1))
                    ref_high = float(m.group(2))

            observations.append(
                {
                    "original_name": test_name,
                    "result_value": val_float,
                    "unit": unit,
                    "reference_range_text": ref_text,
                    "reference_low": ref_low,
                    "reference_high": ref_high,
                }
            )

    if not msh_found:
        raise ValueError("Invalid HL7 v2 message: Missing MSH header segment.")

    demographics = PatientDemographics(
        patient_id=patient_id,
        patient_name=patient_name,
        date_of_birth=dob,
        sex=gender,
        medical_history=[],
    )

    record_interop_audit(
        action="ingest",
        format_type="hl7_v2",
        resource_count=len(observations),
        status="success",
        identifier=report_id,
        details=f"Parsed HL7 v2 ORU^R01 for Patient {patient_id} with {len(observations)} OBX observations.",
    )

    return {
        "demographics": demographics,
        "report_id": report_id,
        "patient_id": patient_id,
        "report_date": report_date,
        "report_category": report_category,
        "parameters": observations,
        "key_text_sections": {"HL7 Source": "HL7 v2.5.1 ORU^R01 Message"},
        "source_summary": f"HL7 v2 Message with {len(observations)} OBX observations.",
    }
