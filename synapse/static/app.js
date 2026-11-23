/* Life Care Diagnostics — Synapse AI Digital Wallet Frontend Logic */

const API_BASE = "/api/v1";

let state = {
  currentPatientId: "SYN-1001",
  patients: [],
  reports: [],
  activeCategory: null,
  startDate: null,
  endDate: null,
  searchQuery: "",
  activeCalendarYear: 2026,
  activeCalendarMonth: 3, // April (0-indexed: 3)
  currentReport: null,
  selectedCorrectionParamId: null,
  reviewQueue: [],
  reviewFilterStatus: "",
  reviewFilterSearch: "",
  currentUser: null,
  authToken: null,
};

const SYNTHETIC_CREDENTIALS = {
  "dr.sunita": "Doctor@123",
  "auditor.meera": "Audit@123",
  "tech.anil": "Tech@123",
  "admin.synapse": "Admin@123",
};

async function authenticateActiveUser(username) {
  const password = SYNTHETIC_CREDENTIALS[username] || "Doctor@123";
  try {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      console.error("Authentication failed for", username);
      return;
    }
    const data = await res.json();
    state.authToken = data.access_token;
    state.currentUser = data.user;

    const badge = document.getElementById("auth-role-badge");
    if (badge) {
      const roleBadges = {
        Pathologist: "badge-success",
        Auditor: "badge-info",
        Technician: "badge-warning",
        Administrator: "badge-neutral",
      };
      badge.className = `badge ${roleBadges[data.user.role] || 'badge-neutral'}`;
      badge.innerText = data.user.role;
    }

    // Auto-update reviewer name input in modal if present
    const revInput = document.getElementById("review-action-reviewer");
    if (revInput) revInput.value = data.user.full_name;
    const corrRevInput = document.getElementById("corr-reviewer-input");
    if (corrRevInput) corrRevInput.value = data.user.full_name;
  } catch (err) {
    console.error("Auth error:", err);
  }
}

// ---------------------------------------------------------------------------
// Initialization & Navigation
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupFilters();
  setupUploadModal();

  // Initialize Active Authenticated User (Phase 7A/7B RBAC)
  const userSelect = document.getElementById("auth-user-select");
  if (userSelect) {
    authenticateActiveUser(userSelect.value);
    userSelect.addEventListener("change", (e) => {
      authenticateActiveUser(e.target.value).then(() => {
        showToast(`Switched active user to ${state.currentUser?.full_name || e.target.value}`);
      });
    });
  } else {
    authenticateActiveUser("dr.sunita");
  }

  loadPatients().then(() => {
    selectPatient(state.currentPatientId);
  });
});

function setupTabs() {
  const tabs = document.querySelectorAll(".nav-tab");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");

      const target = tab.dataset.target;
      document.querySelectorAll(".tab-pane").forEach((pane) => {
        pane.classList.remove("active");
      });
      document.getElementById(target).classList.add("active");

      if (target === "tab-calendar") {
        renderCalendar();
      } else if (target === "tab-trends") {
        loadTrendParameters();
      } else if (target === "tab-review") {
        loadReviewQueue();
      }
    });
  });
}

function showToast(message, isError = false) {
  const toast = document.getElementById("toast");
  toast.innerText = message;
  toast.style.background = isError ? "var(--danger)" : "var(--slate-900)";
  toast.classList.add("active");
  setTimeout(() => {
    toast.classList.remove("active");
  }, 4000);
}

// ---------------------------------------------------------------------------
// Patient Management
// ---------------------------------------------------------------------------

async function loadPatients(query = "") {
  try {
    const url = query ? `${API_BASE}/patients?q=${encodeURIComponent(query)}` : `${API_BASE}/patients`;
    const res = await fetch(url);
    const data = await res.json();
    state.patients = data.patients || [];
    renderPatientDirectory(state.patients);
  } catch (err) {
    console.error("Failed to load patients:", err);
  }
}

function renderPatientDirectory(patients) {
  const tbody = document.getElementById("patients-tbody");
  tbody.innerHTML = "";

  if (patients.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 2rem; color: var(--slate-500);">No patients found.</td></tr>`;
    return;
  }

  patients.forEach((p) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${p.patient_id}</strong></td>
      <td>${p.patient_name}</td>
      <td>${p.age ? p.age + " yrs" : "—"} / ${p.sex || "—"}</td>
      <td>${p.report_count} report(s)</td>
      <td>${p.latest_report_date || "—"}</td>
      <td>
        <button class="btn btn-sm ${p.patient_id === state.currentPatientId ? 'btn-primary' : 'btn-outline'}" onclick="selectPatient('${p.patient_id}')">
          ${p.patient_id === state.currentPatientId ? 'Active' : 'Open Wallet'}
        </button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function selectPatient(patientId) {
  state.currentPatientId = patientId;
  try {
    const res = await fetch(`${API_BASE}/patients/${patientId}`);
    if (!res.ok) throw new Error("Patient not found");
    const data = await res.json();

    const p = data.patient;
    document.getElementById("banner-patient-name").innerText = p.patient_name;
    document.getElementById("banner-patient-id").innerText = p.patient_id;
    document.getElementById("banner-patient-age-sex").innerText = `${p.age ? p.age + " yrs" : "Age N/A"} • ${p.sex || "Sex N/A"}`;
    document.getElementById("banner-patient-dob").innerText = p.date_of_birth ? `DOB: ${p.date_of_birth}` : "DOB N/A";
    document.getElementById("banner-patient-reports").innerText = `${data.total_reports} Reports`;

    // Render Medical History
    const histContainer = document.getElementById("patient-medical-history");
    histContainer.innerHTML = "";
    if (p.medical_history && p.medical_history.length > 0) {
      p.medical_history.forEach((h) => {
        const item = document.createElement("div");
        item.style.padding = "0.4rem 0.6rem";
        item.style.background = "var(--slate-50)";
        item.style.border = "1px solid var(--slate-200)";
        item.style.borderRadius = "var(--radius)";
        item.style.fontSize = "0.8rem";
        item.innerHTML = `<strong>${h.condition_or_event}</strong> <span style="color:var(--slate-500);">(${h.entry_date || "Date N/A"})</span><br/><span style="color:var(--slate-600);">${h.notes || ""}</span>`;
        histContainer.appendChild(item);
      });
    } else {
      histContainer.innerHTML = `<span style="font-size: 0.8rem; color: var(--slate-500);">No relevant medical history recorded.</span>`;
    }

    // Refresh directory highlighting
    renderPatientDirectory(state.patients);
    loadPatientReports();
  } catch (err) {
    showToast(`Error loading patient: ${err.message}`, true);
  }
}

// ---------------------------------------------------------------------------
// Digital Wallet (Reports List)
// ---------------------------------------------------------------------------

async function loadPatientReports() {
  if (!state.currentPatientId) return;

  let url = `${API_BASE}/patients/${state.currentPatientId}/reports?`;
  if (state.activeCategory) url += `category=${encodeURIComponent(state.activeCategory)}&`;
  if (state.startDate) url += `start_date=${encodeURIComponent(state.startDate)}&`;
  if (state.endDate) url += `end_date=${encodeURIComponent(state.endDate)}&`;
  if (state.searchQuery) url += `q=${encodeURIComponent(state.searchQuery)}&`;

  try {
    const res = await fetch(url);
    const data = await res.json();
    state.reports = data.reports || [];
    renderReportsList(state.reports);
  } catch (err) {
    console.error("Failed to load reports:", err);
  }
}

function renderReportsList(reports) {
  const container = document.getElementById("reports-list-container");
  container.innerHTML = "";

  if (reports.length === 0) {
    container.innerHTML = `
      <div style="text-align: center; padding: 3rem; background: #fff; border: 1px solid var(--slate-200); border-radius: var(--radius);">
        <p style="color: var(--slate-500); font-size: 0.95rem;">No medical reports found matching your current filters.</p>
      </div>
    `;
    return;
  }

  reports.forEach((r) => {
    const card = document.createElement("div");
    card.className = "card";
    card.style.marginBottom = "0.85rem";
    card.style.display = "flex";
    card.style.justifyContent = "space-between";
    card.style.alignItems = "center";

    // Determine status badge
    let statusBadge = `<span class="badge badge-success">OK</span>`;
    if (r.extraction_status === "ocr_required") {
      statusBadge = `<span class="badge badge-warning">Needs OCR</span>`;
    } else if (r.review_status !== "clean" || r.extraction_status !== "success") {
      statusBadge = `<span class="badge badge-warning">Needs Review</span>`;
    }

    const dateDisplay = r.report_date
      ? `<span style="font-weight:700; color:var(--slate-900); font-size:0.95rem;">${r.report_date}</span>`
      : `<span class="badge badge-danger">Unknown Date</span>`;

    card.innerHTML = `
      <div>
        <div style="display:flex; align-items:center; gap:0.6rem; margin-bottom:0.35rem;">
          ${dateDisplay}
          <span class="badge badge-neutral">${r.report_category}</span>
          <span class="badge badge-info">${r.file_format.toUpperCase()}</span>
          ${statusBadge}
        </div>
        <div style="font-size:0.8rem; color:var(--slate-600);">
          <strong>File:</strong> ${r.original_filename} &bull;
          <strong>Parameters:</strong> ${r.parameters.length} extracted &bull;
          <strong>Uploaded:</strong> ${r.upload_datetime.substring(0, 10)}
        </div>
      </div>
      <div style="display:flex; gap:0.5rem; align-items:center;">
        <a href="${API_BASE}/reports/${r.report_id}/document" target="_blank" class="btn btn-sm btn-outline" style="text-decoration:none;">
          📄 View ${(r.file_format || 'txt').toUpperCase()}
        </a>
        <button class="btn btn-sm btn-primary" onclick="openReportModal('${r.report_id}')">
          Details & Abnormality
        </button>
      </div>
    `;
    container.appendChild(card);
  });
}

function setupFilters() {
  // Category Pills
  const pills = document.querySelectorAll(".cat-pill");
  pills.forEach((p) => {
    p.addEventListener("click", () => {
      pills.forEach((x) => x.classList.remove("active"));
      p.classList.add("active");
      state.activeCategory = p.dataset.category || null;
      loadPatientReports();
    });
  });

  // Date Filters
  const startInput = document.getElementById("filter-start-date");
  const endInput = document.getElementById("filter-end-date");
  const clearBtn = document.getElementById("filter-date-clear");
  const searchInput = document.getElementById("filter-search");

  startInput.addEventListener("change", (e) => {
    state.startDate = e.target.value || null;
    loadPatientReports();
  });
  endInput.addEventListener("change", (e) => {
    state.endDate = e.target.value || null;
    loadPatientReports();
  });
  clearBtn.addEventListener("click", () => {
    startInput.value = "";
    endInput.value = "";
    state.startDate = null;
    state.endDate = null;
    loadPatientReports();
  });
  searchInput.addEventListener("input", (e) => {
    state.searchQuery = e.target.value.trim();
    loadPatientReports();
  });

  // Directory Search
  document.getElementById("patient-search-input").addEventListener("input", (e) => {
    loadPatients(e.target.value.trim());
  });

  // Review Queue Filter Pills
  const revPills = document.querySelectorAll("#review-status-pills .cat-pill");
  revPills.forEach((p) => {
    p.addEventListener("click", () => {
      revPills.forEach((x) => x.classList.remove("active"));
      p.classList.add("active");
      state.reviewFilterStatus = p.dataset.reviewStatus || "";
      loadReviewQueue();
    });
  });

  // Review Queue Search Input
  const revSearch = document.getElementById("review-filter-search");
  if (revSearch) {
    revSearch.addEventListener("input", (e) => {
      state.reviewFilterSearch = e.target.value.trim().toLowerCase();
      filterAndRenderReviewQueue();
    });
  }
}

// ---------------------------------------------------------------------------
// Report Details & Abnormal Parameter Summary
// ---------------------------------------------------------------------------

async function openReportModal(reportId) {
  try {
    const [repRes, abRes, contentRes] = await Promise.all([
      fetch(`${API_BASE}/reports/${reportId}`),
      fetch(`${API_BASE}/reports/${reportId}/abnormal-summary`),
      fetch(`${API_BASE}/reports/${reportId}/content`),
    ]);

    if (!repRes.ok) {
      throw new Error(`Report not found (${repRes.status})`);
    }

    const report = await repRes.json();
    const abSummary = abRes.ok ? await abRes.json() : { below_range: [], above_range: [], within_range: [], requires_review: [], reference_range_unavailable: [] };
    const docContent = contentRes.ok ? await contentRes.json() : null;

    document.getElementById("modal-report-id").innerText = report.report_id;
    document.getElementById("modal-patient-id").innerText = report.patient_id;
    document.getElementById("modal-report-date").innerText = report.report_date || "Unknown";
    document.getElementById("modal-report-category").innerText = report.report_category;
    document.getElementById("modal-report-format").innerText = (report.file_format || "TXT").toUpperCase();
    document.getElementById("modal-report-status").innerText = report.extraction_status;

    // Document Source viewer
    const docLink = document.getElementById("modal-doc-link");
    const docFilename = document.getElementById("modal-doc-filename");
    const textWrapper = document.getElementById("modal-doc-text-wrapper");
    const textPre = document.getElementById("modal-doc-text");
    const pdfWrapper = document.getElementById("modal-doc-pdf-wrapper");
    const pdfIframe = document.getElementById("modal-doc-pdf-iframe");
    const imgWrapper = document.getElementById("modal-doc-img-wrapper");
    const imgElement = document.getElementById("modal-doc-img");
    const errorBox = document.getElementById("modal-doc-error");

    const docUrl = `${API_BASE}/reports/${reportId}/document`;
    docLink.href = docUrl;
    docFilename.innerText = report.original_filename || "Document";

    // Reset visibility
    textWrapper.style.display = "none";
    pdfWrapper.style.display = "none";
    if (imgWrapper) imgWrapper.style.display = "none";
    errorBox.style.display = "none";

    if (docContent && docContent.error) {
      errorBox.innerText = docContent.error;
      errorBox.style.display = "block";
    } else if (docContent && docContent.is_text) {
      textPre.innerText = docContent.content || "Empty document content.";
      textWrapper.style.display = "block";
    } else if (docContent && docContent.is_image) {
      if (imgElement && imgWrapper) {
        imgElement.src = docUrl;
        imgWrapper.style.display = "block";
      }
    } else if (report.file_format === "pdf" || (docContent && docContent.file_format === "pdf")) {
      pdfIframe.src = docUrl;
      pdfWrapper.style.display = "block";
    } else if (docContent && docContent.content) {
      textPre.innerText = docContent.content;
      textWrapper.style.display = "block";
    } else {
      textPre.innerText = "No preview available.";
      textWrapper.style.display = "block";
    }

    // Render 4 abnormal summary boxes
    renderAbnormalBox("box-below", abSummary.below_range || [], "var(--danger)");
    renderAbnormalBox("box-above", abSummary.above_range || [], "#ea580c");
    renderAbnormalBox("box-normal", abSummary.within_range || [], "var(--success)");
    renderAbnormalBox("box-review", [...(abSummary.requires_review || []), ...(abSummary.reference_range_unavailable || [])], "var(--warning)");

    // Raw Narrative Sections
    const secBox = document.getElementById("modal-sections");
    secBox.innerHTML = "";
    const sections = report.key_text_sections || {};
    if (Object.keys(sections).length > 0) {
      for (const [k, v] of Object.entries(sections)) {
        secBox.innerHTML += `<div style="margin-bottom:0.5rem;"><strong>${k}:</strong> <span style="color:var(--slate-700);">${v}</span></div>`;
      }
    } else {
      secBox.innerHTML = `<span style="font-size:0.8rem; color:var(--slate-500);">No narrative text sections.</span>`;
    }

    // Review flags & errors
    const flagBox = document.getElementById("modal-flags");
    flagBox.innerHTML = "";
    const flags = report.document_level_flags || [];
    const errors = report.validation_errors || [];
    if (flags.length === 0 && errors.length === 0) {
      flagBox.innerHTML = `<span style="color:var(--success); font-size:0.85rem;">✓ 0 review flags or validation errors encountered.</span>`;
    } else {
      flags.forEach((f) => {
        flagBox.innerHTML += `<div style="color:var(--warning); font-size:0.8rem;">⚠ [${f.severity.toUpperCase()}] ${f.field}: ${f.reason}</div>`;
      });
      errors.forEach((e) => {
        flagBox.innerHTML += `<div style="color:var(--danger); font-size:0.8rem;">✖ ${e}</div>`;
      });
    }

    // Set current active report in state
    state.currentReport = report;

    // Review Status Badge & FHIR Export Safeguard UI
    const revBadge = document.getElementById("modal-review-badge");
    const fhirBtn = document.getElementById("modal-btn-export-fhir");
    const st = report.review_status || "needs_review";
    const badgeMap = {
      clean: "badge-success",
      approved: "badge-success",
      needs_review: "badge-warning",
      unsupported_parameters: "badge-warning",
      corrected: "badge-info",
      rejected: "badge-danger",
    };
    if (revBadge) {
      revBadge.className = `badge ${badgeMap[st] || 'badge-neutral'}`;
      revBadge.innerText = st.replace(/_/g, " ").toUpperCase();
    }
    if (fhirBtn) {
      if (st === "rejected") {
        fhirBtn.className = "btn btn-sm btn-outline";
        fhirBtn.style.opacity = "0.5";
        fhirBtn.title = "Export blocked: Report has been rejected.";
        fhirBtn.innerText = "❌ Export FHIR (Blocked)";
      } else if (st === "approved" || st === "clean") {
        fhirBtn.className = "btn btn-sm btn-primary";
        fhirBtn.style.opacity = "1";
        fhirBtn.title = "Approved for FHIR R4 export.";
        fhirBtn.innerText = "📤 Export FHIR R4 (Ready)";
      } else {
        fhirBtn.className = "btn btn-sm btn-outline";
        fhirBtn.style.opacity = "0.9";
        fhirBtn.title = "Clinical approval recommended before FHIR export.";
        fhirBtn.innerText = "📤 Export FHIR R4";
      }
    }

    // Render parameters table for field-level correction
    renderModalParameters(report.parameters || []);

    // Reset inline correction form
    closeCorrectionForm();

    // Load review and correction audit trail
    loadAndRenderReportReviewHistory(reportId);

    document.getElementById("report-modal").classList.add("active");
  } catch (err) {
    showToast(`Error opening report: ${err.message}`, true);
  }
}

function renderModalParameters(params) {
  const tbody = document.getElementById("modal-params-tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!params || params.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:1rem; color:var(--slate-400);">No parameters extracted.</td></tr>`;
    return;
  }
  const flagBadges = {
    low: '<span class="badge badge-danger">Low</span>',
    high: '<span class="badge badge-warning">High</span>',
    normal: '<span class="badge badge-success">Normal</span>',
  };
  params.forEach((p) => {
    const tr = document.createElement("tr");
    const flagHtml = flagBadges[p.clinical_flag] || '<span class="badge badge-neutral">—</span>';
    tr.innerHTML = `
      <td>
        <strong>${p.original_name}</strong>
        ${p.standardized_name && p.standardized_name !== p.original_name ? `<div style="font-size:0.7rem; color:var(--slate-500);">Std: ${p.standardized_name}</div>` : ""}
      </td>
      <td style="font-weight:600;">${p.result_value !== null ? p.result_value : "—"}</td>
      <td>${p.unit || "—"}</td>
      <td style="font-size:0.75rem; color:var(--slate-600);">${p.reference_range_text || "—"}</td>
      <td>${flagHtml}</td>
      <td>
        <button class="btn btn-sm btn-outline" onclick="openCorrectionForm('${p.parameter_id}')">Correct</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function openCorrectionForm(paramId) {
  if (!state.currentReport) return;
  const param = (state.currentReport.parameters || []).find((p) => p.parameter_id === paramId);
  if (!param) return;

  state.selectedCorrectionParamId = paramId;
  const nameEl = document.getElementById("corr-param-name");
  const idEl = document.getElementById("corr-param-id");
  const valInput = document.getElementById("corr-val-input");
  const nameInput = document.getElementById("corr-name-input");
  const unitInput = document.getElementById("corr-unit-input");
  const reasonInput = document.getElementById("corr-reason-input");
  const card = document.getElementById("param-correction-card");

  if (nameEl) nameEl.innerText = param.original_name;
  if (idEl) idEl.innerText = param.parameter_id;
  if (valInput) valInput.value = param.result_value !== null ? param.result_value : "";
  if (nameInput) nameInput.value = param.original_name || "";
  if (unitInput) unitInput.value = param.unit || "";
  if (reasonInput) reasonInput.value = "";
  if (card) {
    card.style.display = "block";
    card.scrollIntoView({ behavior: "smooth" });
  }
}

function closeCorrectionForm() {
  state.selectedCorrectionParamId = null;
  const card = document.getElementById("param-correction-card");
  if (card) card.style.display = "none";
}

async function submitParameterCorrection() {
  if (!state.currentReport || !state.selectedCorrectionParamId) return;

  const reportId = state.currentReport.report_id;
  const paramId = state.selectedCorrectionParamId;
  const valStr = document.getElementById("corr-val-input").value.trim();
  const nameStr = document.getElementById("corr-name-input").value.trim();
  const unitStr = document.getElementById("corr-unit-input").value.trim();
  const reviewerStr = document.getElementById("corr-reviewer-input").value.trim() || "Clinical Auditor";
  const reasonStr = document.getElementById("corr-reason-input").value.trim();

  if (!reasonStr) {
    showToast("Please enter a reason for the parameter correction.", true);
    return;
  }

  const payload = {
    corrected_value: valStr !== "" ? parseFloat(valStr) : null,
    corrected_name: nameStr || null,
    corrected_unit: unitStr || null,
    reviewer: reviewerStr,
    reason: reasonStr,
  };

  try {
    const headers = { "Content-Type": "application/json" };
    if (state.authToken) headers["Authorization"] = `Bearer ${state.authToken}`;
    const res = await fetch(`${API_BASE}/review/reports/${reportId}/parameters/${paramId}/correct`, {
      method: "POST",
      headers: headers,
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      showToast(`Correction failed: ${data.detail || 'Error'}`, true);
      return;
    }
    showToast(`✓ Parameter '${data.data?.original_name || 'value'}' corrected and logged!`);
    closeCorrectionForm();
    await openReportModal(reportId);
    if (document.getElementById("tab-review").classList.contains("active")) {
      loadReviewQueue();
    }
  } catch (err) {
    showToast(`Network error: ${err.message}`, true);
  }
}

async function submitReviewAction(action) {
  if (!state.currentReport) return;
  const reportId = state.currentReport.report_id;
  const reviewerInput = document.getElementById("review-action-reviewer");
  const commentInput = document.getElementById("review-action-comment");
  const reviewer = (reviewerInput && reviewerInput.value.trim()) || "Clinical Reviewer";
  const comments = (commentInput && commentInput.value.trim()) || null;

  try {
    const headers = { "Content-Type": "application/json" };
    if (state.authToken) headers["Authorization"] = `Bearer ${state.authToken}`;
    const res = await fetch(`${API_BASE}/review/reports/${reportId}/action`, {
      method: "POST",
      headers: headers,
      body: JSON.stringify({ action, reviewer, comments }),
    });
    const data = await res.json();
    if (!res.ok) {
      showToast(`Review action failed: ${data.detail || 'Error'}`, true);
      return;
    }
    showToast(`✓ Report ${reportId} review updated to '${data.new_status}'!`);
    await openReportModal(reportId);
    if (document.getElementById("tab-review").classList.contains("active")) {
      loadReviewQueue();
    }
  } catch (err) {
    showToast(`Network error: ${err.message}`, true);
  }
}

async function loadAndRenderReportReviewHistory(reportId) {
  const box = document.getElementById("modal-review-history");
  if (!box) return;
  box.innerHTML = `<span style="font-size:0.75rem; color:var(--slate-500);">Loading audit history...</span>`;
  try {
    const res = await fetch(`${API_BASE}/review/reports/${reportId}/history`);
    if (!res.ok) {
      box.innerHTML = `<span style="font-size:0.75rem; color:var(--slate-400);">No history recorded.</span>`;
      return;
    }
    const data = await res.json();
    const history = data.history || [];
    if (history.length === 0) {
      box.innerHTML = `<span style="font-size:0.75rem; color:var(--slate-500);">No review actions or manual corrections recorded yet.</span>`;
      return;
    }
    box.innerHTML = "";
    history.forEach((h) => {
      const item = document.createElement("div");
      item.style.padding = "0.5rem 0";
      item.style.borderBottom = "1px solid var(--slate-200)";
      item.style.fontSize = "0.785rem";

      let corrsHtml = "";
      if (h.corrections && h.corrections.length > 0) {
        corrsHtml = `<div style="margin-top:0.25rem; padding-left:0.5rem; border-left:2px solid var(--primary); font-size:0.75rem;">` +
          h.corrections.map((c) => `<div><strong>${c.field_name}:</strong> '${c.original_value !== null ? c.original_value : "null"}' &rarr; '${c.corrected_value !== null ? c.corrected_value : "null"}' (Reason: ${c.reason})</div>`).join("") +
          `</div>`;
      }

      item.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.2rem;">
          <div>
            <strong style="text-transform:uppercase; color:var(--slate-800);">${h.action}</strong>
            <span style="color:var(--slate-500); font-size:0.75rem;">by ${h.reviewer}</span>
          </div>
          <span style="font-size:0.7rem; color:var(--slate-400);">${new Date(h.timestamp).toLocaleString()}</span>
        </div>
        ${h.comments ? `<div style="color:var(--slate-700); margin-bottom:0.2rem;">Note: ${h.comments}</div>` : ""}
        ${h.previous_status ? `<div style="font-size:0.7rem; color:var(--slate-500);">Status: ${h.previous_status} &rarr; <strong>${h.new_status}</strong></div>` : ""}
        ${corrsHtml}
      `;
      box.appendChild(item);
    });
  } catch (err) {
    box.innerHTML = `<span style="font-size:0.75rem; color:var(--danger);">Error loading audit history.</span>`;
  }
}

async function exportCurrentReportFhir() {
  if (!state.currentReport) return;
  const reportId = state.currentReport.report_id;
  try {
    const headers = {};
    if (state.authToken) headers["Authorization"] = `Bearer ${state.authToken}`;
    const res = await fetch(`${API_BASE}/interop/fhir/reports/${reportId}?enforce_approval=true`, {
      headers: headers,
    });
    const data = await res.json();
    if (res.status === 403) {
      showToast(`⛔ ${data.detail}`, true);
      return;
    }
    if (!res.ok) {
      showToast(`Export error: ${data.detail || 'Failed to export FHIR'}`, true);
      return;
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `fhir_report_${reportId}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast(`✓ HL7 FHIR R4 Bundle downloaded (${data.total || 0} resources)!`);
  } catch (err) {
    showToast(`Network error exporting FHIR: ${err.message}`, true);
  }
}

async function loadReviewQueue() {
  try {
    const url = state.reviewFilterStatus
      ? `${API_BASE}/review/queue?status=${encodeURIComponent(state.reviewFilterStatus)}`
      : `${API_BASE}/review/queue`;
    const res = await fetch(url);
    const data = await res.json();
    state.reviewQueue = data.queue || [];
    filterAndRenderReviewQueue();
  } catch (err) {
    console.error("Failed to load review queue:", err);
  }
}

function filterAndRenderReviewQueue() {
  let list = state.reviewQueue;
  if (state.reviewFilterSearch) {
    const q = state.reviewFilterSearch;
    list = list.filter((r) =>
      r.report_id.toLowerCase().includes(q) ||
      (r.patient_name && r.patient_name.toLowerCase().includes(q)) ||
      (r.report_category && r.report_category.toLowerCase().includes(q))
    );
  }
  renderReviewQueue(list);
}

function renderReviewQueue(items) {
  const tbody = document.getElementById("review-queue-tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!items || items.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:2rem; color:var(--slate-500);">No reports matching review criteria.</td></tr>`;
    return;
  }
  const badgeMap = {
    clean: "badge-success",
    approved: "badge-success",
    needs_review: "badge-warning",
    unsupported_parameters: "badge-warning",
    corrected: "badge-info",
    rejected: "badge-danger",
  };
  items.forEach((r) => {
    const tr = document.createElement("tr");
    const stBadge = `<span class="badge ${badgeMap[r.review_status] || 'badge-neutral'}">${r.review_status.replace(/_/g, " ")}</span>`;
    tr.innerHTML = `
      <td><strong>${r.report_id}</strong></td>
      <td>${r.patient_name} <span style="font-size:0.75rem; color:var(--slate-500);">(${r.patient_id})</span></td>
      <td>${r.report_date || "—"}</td>
      <td>${r.report_category}</td>
      <td>${r.extraction_status}</td>
      <td>${stBadge}</td>
      <td>
        <button class="btn btn-sm btn-primary" onclick="openReportModal('${r.report_id}')">Review & Audit</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function renderAbnormalBox(boxId, items, color) {
  const container = document.getElementById(boxId);
  container.innerHTML = "";
  if (!items || items.length === 0) {
    container.innerHTML = `<div style="font-size:0.75rem; color:var(--slate-400); font-style:italic;">None</div>`;
    return;
  }

  items.forEach((item) => {
    const div = document.createElement("div");
    div.style.padding = "0.35rem 0";
    div.style.borderBottom = "1px dashed var(--slate-200)";
    div.style.fontSize = "0.775rem";
    div.innerHTML = `
      <div style="font-weight:600; color:var(--slate-900);">${item.original_name}</div>
      <div style="color:${color}; font-weight:700;">
        ${item.result_value !== null ? item.result_value : "N/A"} ${item.unit || ""}
      </div>
      <div style="font-size:0.7rem; color:var(--slate-500);">${item.reference_range_text || "No Range"}</div>
    `;
    container.appendChild(div);
  });
}

function closeReportModal() {
  document.getElementById("report-modal").classList.remove("active");
}

// ---------------------------------------------------------------------------
// Calendar View
// ---------------------------------------------------------------------------

async function renderCalendar() {
  if (!state.currentPatientId) return;

  try {
    const res = await fetch(`${API_BASE}/patients/${state.currentPatientId}/calendar`);
    const data = await res.json();
    const calendar = data.calendar || {};

    const year = state.activeCalendarYear;
    const month = state.activeCalendarMonth;

    const monthNames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
    document.getElementById("calendar-month-label").innerText = `${monthNames[month]} ${year}`;

    const grid = document.getElementById("calendar-grid");
    // Preserve day of week headers
    const headers = `
      <div class="calendar-header-day">Sun</div>
      <div class="calendar-header-day">Mon</div>
      <div class="calendar-header-day">Tue</div>
      <div class="calendar-header-day">Wed</div>
      <div class="calendar-header-day">Thu</div>
      <div class="calendar-header-day">Fri</div>
      <div class="calendar-header-day">Sat</div>
    `;
    grid.innerHTML = headers;

    const firstDay = new Date(year, month, 1).getDay();
    const totalDays = new Date(year, month + 1, 0).getDate();

    // Blank cells before month starts
    for (let i = 0; i < firstDay; i++) {
      grid.innerHTML += `<div class="calendar-day empty"></div>`;
    }

    // Days of month
    for (let d = 1; d <= totalDays; d++) {
      const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      const reportsOnDate = calendar[dateStr] || [];
      const hasReports = reportsOnDate.length > 0;

      const cell = document.createElement("div");
      cell.className = `calendar-day ${hasReports ? 'has-reports' : ''}`;
      cell.innerHTML = `
        <div class="cal-day-num">${d}</div>
        ${hasReports ? `<span class="cal-report-badge">${reportsOnDate.length} Report(s)</span>` : ""}
      `;

      if (hasReports) {
        cell.addEventListener("click", () => {
          showDateReports(dateStr, reportsOnDate);
        });
      }
      grid.appendChild(cell);
    }

    // Unknown dates banner
    const unknownReports = calendar["unknown_date"] || [];
    window._synapseUnknownReports = unknownReports;
    const unkBanner = document.getElementById("calendar-unknown-dates-container");
    if (unknownReports.length > 0) {
      unkBanner.innerHTML = `
        <div style="background:var(--warning-bg); border:1px solid var(--warning); border-radius:var(--radius); padding:0.75rem 1rem; margin-top:1rem; font-size:0.85rem;">
          <strong>⚠ Notice:</strong> ${unknownReports.length} report(s) have unrecorded or missing dates. Dates are not invented.
          <button class="btn btn-sm btn-outline" style="margin-left:0.5rem;" onclick="showDateReports('Unknown Date', window._synapseUnknownReports)">View Unscheduled Reports</button>
        </div>
      `;
    } else {
      unkBanner.innerHTML = "";
    }
  } catch (err) {
    console.error("Failed to render calendar:", err);
  }
}

function showDateReports(dateStr, reports) {
  const panel = document.getElementById("calendar-date-reports");
  panel.innerHTML = `<h4 style="margin-bottom:0.75rem;">Reports on ${dateStr} (${reports.length})</h4>`;
  reports.forEach((r) => {
    panel.innerHTML += `
      <div style="padding:0.6rem; border:1px solid var(--slate-200); border-radius:var(--radius); margin-bottom:0.5rem; background:#fff; display:flex; justify-content:space-between; align-items:center;">
        <div>
          <strong>${r.report_category}</strong> <span style="font-size:0.75rem; color:var(--slate-500);">(${r.filename})</span><br/>
          <span style="font-size:0.75rem;">${r.parameter_count} parameters &bull; Status: ${r.extraction_status} &bull; Format: ${(r.file_format || 'txt').toUpperCase()}</span>
        </div>
        <div style="display:flex; gap:0.35rem;">
          <a href="${API_BASE}/reports/${r.report_id}/document" target="_blank" class="btn btn-sm btn-outline" style="text-decoration:none;">📄 View</a>
          <button class="btn btn-sm btn-primary" onclick="openReportModal('${r.report_id}')">Details</button>
        </div>
      </div>
    `;
  });
}

function changeMonth(delta) {
  state.activeCalendarMonth += delta;
  if (state.activeCalendarMonth < 0) {
    state.activeCalendarMonth = 11;
    state.activeCalendarYear -= 1;
  } else if (state.activeCalendarMonth > 11) {
    state.activeCalendarMonth = 0;
    state.activeCalendarYear += 1;
  }
  renderCalendar();
}

// ---------------------------------------------------------------------------
// Longitudinal Trend Analysis
// ---------------------------------------------------------------------------

async function loadTrendParameters() {
  if (!state.currentPatientId) return;

  try {
    const res = await fetch(`${API_BASE}/patients/${state.currentPatientId}/parameters`);
    const data = await res.json();
    const select = document.getElementById("trend-parameter-select");
    select.innerHTML = "";

    const params = data.parameters || [];
    if (params.length === 0) {
      select.innerHTML = `<option value="">No standardized parameters found</option>`;
      return;
    }

    params.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.standardized_name;
      opt.innerText = `${p.standardized_name} (${p.observation_count} obs • ${p.unit || 'no unit'})`;
      select.appendChild(opt);
    });

    // Auto-select Hemoglobin or first parameter
    if (params.some((p) => p.standardized_name === "Hemoglobin")) {
      select.value = "Hemoglobin";
    }

    select.onchange = () => loadParameterTrend(select.value);
    loadParameterTrend(select.value);
  } catch (err) {
    console.error("Failed to load trend parameters:", err);
  }
}

async function loadParameterTrend(paramName) {
  if (!paramName || !state.currentPatientId) return;

  try {
    const res = await fetch(`${API_BASE}/patients/${state.currentPatientId}/trends?parameter=${encodeURIComponent(paramName)}`);
    const data = await res.json();

    // Incompatible Unit Warning
    const warnBox = document.getElementById("trend-unit-warning");
    if (!data.unit_compatible && data.warning) {
      warnBox.innerHTML = `
        <div style="background:var(--danger-bg); color:var(--danger); border:1px solid var(--danger); border-radius:var(--radius); padding:0.75rem 1rem; margin-bottom:1rem; font-size:0.85rem;">
          <strong>⚠ Warning:</strong> ${data.warning}
        </div>
      `;
    } else {
      warnBox.innerHTML = `
        <div style="background:var(--success-bg); color:var(--success); border:1px solid var(--success); border-radius:var(--radius); padding:0.5rem 1rem; margin-bottom:1rem; font-size:0.8rem; display:inline-block;">
          ✓ Unit Compatible: All values measured in <strong>${data.units_detected.join(", ") || "standard units"}</strong>.
        </div>
      `;
    }

    // Render SVG Line Chart
    renderTrendChart(data.data_points);

    // Render Data Table
    const tbody = document.getElementById("trend-table-tbody");
    tbody.innerHTML = "";
    if (data.data_points.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:1.5rem; color:var(--slate-500);">No historical observations recorded.</td></tr>`;
      return;
    }

    data.data_points.forEach((pt) => {
      const tr = document.createElement("tr");
      let flagBadge = `<span class="badge badge-success">Normal</span>`;
      if (pt.clinical_flag === "low") flagBadge = `<span class="badge badge-danger">Low</span>`;
      else if (pt.clinical_flag === "high") flagBadge = `<span class="badge badge-warning">High</span>`;
      else if (pt.clinical_flag === "unknown") flagBadge = `<span class="badge badge-neutral">Unknown</span>`;

      tr.innerHTML = `
        <td><strong>${pt.report_date}</strong></td>
        <td>${pt.original_name}</td>
        <td><strong>${pt.result_value}</strong></td>
        <td>${pt.unit || "—"}</td>
        <td>${pt.reference_range_text || "—"}</td>
        <td>${flagBadge}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Failed to load trend data:", err);
  }
}

function renderTrendChart(points) {
  const svg = document.getElementById("trend-chart-svg");
  svg.innerHTML = "";

  if (!points || points.length === 0) {
    svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#94a3b8">No historical data points available.</text>`;
    return;
  }

  const width = svg.clientWidth || 700;
  const height = 260;
  const padL = 60, padR = 40, padT = 30, padB = 40;

  const validPts = points.filter((p) => p.result_value !== null);
  if (validPts.length === 0) return;

  const values = validPts.map((p) => p.result_value);
  const minVal = Math.min(...values) * 0.9;
  const maxVal = Math.max(...values) * 1.1;

  const scaleX = (idx) => padL + (idx / Math.max(1, validPts.length - 1)) * (width - padL - padR);
  const scaleY = (val) => height - padB - ((val - minVal) / Math.max(0.1, maxVal - minVal)) * (height - padT - padB);

  // Background Grid Lines
  for (let i = 0; i <= 4; i++) {
    const yVal = minVal + (i / 4) * (maxVal - minVal);
    const yPos = scaleY(yVal);
    svg.innerHTML += `
      <line x1="${padL}" y1="${yPos}" x2="${width - padR}" y2="${yPos}" stroke="#e2e8f0" stroke-dasharray="3,3" />
      <text x="${padL - 8}" y="${yPos + 4}" font-size="10" fill="#64748b" text-anchor="end">${yVal.toFixed(1)}</text>
    `;
  }

  // Draw Line
  let pathD = "";
  validPts.forEach((p, idx) => {
    const x = scaleX(idx);
    const y = scaleY(p.result_value);
    pathD += (idx === 0 ? "M" : "L") + `${x},${y} `;
  });

  svg.innerHTML += `<path d="${pathD}" fill="none" stroke="var(--primary)" stroke-width="3" />`;

  // Draw Points & X-Labels
  validPts.forEach((p, idx) => {
    const x = scaleX(idx);
    const y = scaleY(p.result_value);

    // Color code point by flag
    let ptColor = "var(--primary)";
    if (p.clinical_flag === "low") ptColor = "var(--danger)";
    else if (p.clinical_flag === "high") ptColor = "#ea580c";

    svg.innerHTML += `
      <circle cx="${x}" cy="${y}" r="6" fill="${ptColor}" stroke="#fff" stroke-width="2">
        <title>${p.report_date}: ${p.result_value} ${p.unit || ''} (${p.clinical_flag})</title>
      </circle>
      <text x="${x}" y="${y - 12}" font-size="11" font-weight="700" fill="#1e293b" text-anchor="middle">${p.result_value}</text>
      <text x="${x}" y="${height - 15}" font-size="10" fill="#64748b" text-anchor="middle">${p.report_date}</text>
    `;
  });
}

// ---------------------------------------------------------------------------
// File Upload & API Ingestion
// ---------------------------------------------------------------------------

function setupUploadModal() {
  const modal = document.getElementById("upload-modal");
  const openBtn = document.getElementById("btn-open-upload");
  const closeBtn = document.getElementById("upload-modal-close");
  const form = document.getElementById("upload-form");

  openBtn.addEventListener("click", () => {
    document.getElementById("upload-patient-id").value = state.currentPatientId || "SYN-1001";
    modal.classList.add("active");
  });

  closeBtn.addEventListener("click", () => {
    modal.classList.remove("active");
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fileInput = document.getElementById("upload-file-input");
    const pidInput = document.getElementById("upload-patient-id");

    if (!fileInput.files || fileInput.files.length === 0) {
      showToast("Please select a file to upload.", true);
      return;
    }

    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append("file", file);
    if (pidInput.value.trim()) {
      formData.append("patient_id", pidInput.value.trim());
    }

    const submitBtn = form.querySelector("button[type=submit]");
    submitBtn.disabled = true;
    submitBtn.innerText = "Processing...";

    try {
      const res = await fetch(`${API_BASE}/reports/upload`, {
        method: "POST",
        body: formData,
      });

      const data = await res.json();
      if (res.status === 409) {
        showToast(`⚠ Duplicate Upload: ${data.detail}`, true);
      } else if (!res.ok) {
        showToast(`Error: ${data.detail || 'Upload failed'}`, true);
      } else {
        showToast(`✓ ${data.message}`);
        modal.classList.remove("active");
        form.reset();
        await loadPatients();
        await selectPatient(data.patient_id || state.currentPatientId);
      }
    } catch (err) {
      showToast(`Network error: ${err.message}`, true);
    } finally {
      submitBtn.disabled = false;
      submitBtn.innerText = "Upload & Process";
    }
  });
}

