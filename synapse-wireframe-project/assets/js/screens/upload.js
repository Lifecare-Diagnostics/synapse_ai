// upload.js: Logic for Upload screen supporting multi-format ingestion pipeline
window.Synapse = window.Synapse || {};
window.Synapse.screens = window.Synapse.screens || {};

window.Synapse.screens.upload = {
    currentTimer: null,
    
    samples: {
        digital_pdf: {
            filename: "CBC_report.pdf",
            badgeText: "Digital PDF",
            badgeClass: "status-blue",
            steps: [
                "1/5 Uploaded (248 KB)",
                "2/5 Format detected: Digital PDF (vector text layer)",
                "3/5 Digital text extracted via PyMuPDF (100% density)",
                "4/5 Deterministic rule-based fields extracted (CBC panel)",
                "5/5 Awaiting clinical review"
            ]
        },
        scanned_pdf: {
            filename: "scanned_lipid_profile.pdf",
            badgeText: "Scanned PDF (OCR)",
            badgeClass: "status-amber",
            steps: [
                "1/5 Uploaded (1.2 MB)",
                "2/5 Format detected: Scanned PDF (0 text layer detected)",
                "3/5 Hybrid OCR fallback initiated (rendering 300 DPI)",
                "4/5 Optical character recognition extracted 6 parameters",
                "5/5 Awaiting clinical review"
            ]
        },
        medical_image: {
            filename: "biochemistry_slip.png",
            badgeText: "Medical Image (OCR)",
            badgeClass: "status-amber",
            steps: [
                "1/5 Uploaded (820 KB)",
                "2/5 Format detected: Medical Image (.png)",
                "3/5 Image contrast pre-processing applied",
                "4/5 Tesseract OCR extraction complete",
                "5/5 Awaiting clinical review"
            ]
        },
        clinical_note: {
            filename: "dr_sharma_clinical_note.txt",
            badgeText: "Narrative Note (LLM)",
            badgeClass: "status-green",
            steps: [
                "1/5 Uploaded (14 KB)",
                "2/5 Format detected: Unstructured Doctor Note",
                "3/5 Phase 5 Hybrid LLM Router activated",
                "4/5 Clinical entities, findings & diagnoses structured",
                "5/5 Awaiting clinical review"
            ]
        }
    },

    simulate: function(formatKey = "digital_pdf") {
        if (this.currentTimer) {
            clearInterval(this.currentTimer);
        }

        const sample = this.samples[formatKey] || this.samples.digital_pdf;
        const list = document.getElementById('upload-list');
        list.style.display = 'block';

        const nameEl = document.getElementById('upload-filename');
        const badgeEl = document.getElementById('upload-badge');
        const textEl = document.getElementById('upload-progress-text');
        const actionEl = document.getElementById('upload-action-btn');

        if (nameEl) nameEl.innerText = sample.filename;
        if (badgeEl) {
            badgeEl.innerText = sample.badgeText;
            badgeEl.className = "badge badge-status " + sample.badgeClass;
        }
        if (actionEl) actionEl.style.display = 'none';

        textEl.style.color = "var(--text-muted)";
        textEl.style.fontWeight = "normal";

        const steps = sample.steps;
        let i = 0;
        textEl.innerText = steps[0];

        this.currentTimer = setInterval(() => {
            i++;
            if (i < steps.length) {
                textEl.innerText = steps[i];
                if (i === steps.length - 1) {
                    textEl.style.color = "var(--amber)";
                    textEl.style.fontWeight = "bold";
                    if (actionEl) actionEl.style.display = 'inline-block';
                    clearInterval(this.currentTimer);
                }
            } else {
                clearInterval(this.currentTimer);
            }
        }, 650);
    },

    render: function(container) {},
    init: function() {}
};

// Global aliases
window.simulateUpload = function(formatKey) {
    window.Synapse.screens.upload.simulate(formatKey || "digital_pdf");
};
