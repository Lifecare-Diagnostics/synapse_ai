// review.js: Logic for Review screen
window.Synapse.screens.review = {
    render: function(container) {},
    init: function() {}
};

window.reviewAuditLog = [
    { timestamp: "2024-03-14 10:30", reviewer: "OCR / Pipeline", action: "initial_ingest", status: "needs_review", note: "Extracted with 1 low confidence field." }
];

window.currentReportStatus = "needs_review";

window.approveReportWireframe = function() {
    window.currentReportStatus = "approved";
    window.reviewAuditLog.push({
        timestamp: new Date().toISOString().replace('T', ' ').substring(0, 16),
        reviewer: "Dr. Pathologist",
        action: "approve",
        status: "approved",
        note: "Verified against laboratory analyzer output. Approved for clinical wallet."
    });
    const toast = document.getElementById('toast');
    if (toast) {
        toast.innerText = "✓ Report Approved & Verified. FHIR R4 Export unlocked.";
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 3500);
    }
    const fhirBtn = document.getElementById("btn-wireframe-export-fhir");
    if (fhirBtn) {
        fhirBtn.style.color = "var(--green)";
        fhirBtn.innerText = "✓ Export FHIR (Ready)";
    }
};

window.rejectReportWireframe = function() {
    window.currentReportStatus = "rejected";
    window.reviewAuditLog.push({
        timestamp: new Date().toISOString().replace('T', ' ').substring(0, 16),
        reviewer: "Dr. Pathologist",
        action: "reject",
        status: "rejected",
        note: "Sample hemolysis detected. Specimen rejected."
    });
    const toast = document.getElementById('toast');
    if (toast) {
        toast.innerText = "❌ Report Rejected. FHIR R4 export blocked.";
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 3500);
    }
    const fhirBtn = document.getElementById("btn-wireframe-export-fhir");
    if (fhirBtn) {
        fhirBtn.style.color = "var(--red)";
        fhirBtn.innerText = "❌ Export FHIR (Blocked)";
    }
};

window.exportFhirWireframe = function() {
    const toast = document.getElementById('toast');
    if (window.currentReportStatus === "rejected") {
        if (toast) {
            toast.innerText = "⛔ Export Blocked: Rejected report cannot be exported to FHIR.";
            toast.classList.add('show');
            setTimeout(() => toast.classList.remove('show'), 3500);
        }
        return;
    }
    if (window.currentReportStatus === "needs_review") {
        if (toast) {
            toast.innerText = "⚠ Clinical approval required before FHIR export.";
            toast.classList.add('show');
            setTimeout(() => toast.classList.remove('show'), 3500);
        }
        return;
    }
    const bundle = {
        resourceType: "Bundle",
        id: "BUNDLE-SYN-P-0001",
        type: "collection",
        entry: [
            { resource: { resourceType: "Patient", id: "SYN-P-0001", name: [{ text: "SYNTHETIC PATIENT ALPHA" }] } },
            { resource: { resourceType: "DiagnosticReport", id: "REP-0001", status: "final" } },
            { resource: { resourceType: "Observation", id: "PARAM-001", code: { text: "Hemoglobin" }, valueQuantity: { value: 11.8, unit: "g/dL" } } }
        ]
    };
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "fhir_bundle_SYN-P-0001.json";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    if (toast) {
        toast.innerText = "✓ FHIR R4 Bundle exported successfully (3 resources).";
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 3500);
    }
};
