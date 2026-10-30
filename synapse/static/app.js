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
};

// ---------------------------------------------------------------------------
// Initialization & Navigation
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupFilters();
  setupUploadModal();
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
      <div>
        <button class="btn btn-sm btn-outline" onclick="openReportModal('${r.report_id}')">
          View Details & Abnormality
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
}

// ---------------------------------------------------------------------------
// Report Details & Abnormal Parameter Summary
// ---------------------------------------------------------------------------

async function openReportModal(reportId) {
  try {
    const [repRes, abRes] = await Promise.all([
      fetch(`${API_BASE}/reports/${reportId}`),
      fetch(`${API_BASE}/reports/${reportId}/abnormal-summary`),
    ]);

    const report = await repRes.json();
    const abSummary = await abRes.json();

    document.getElementById("modal-report-id").innerText = report.report_id;
    document.getElementById("modal-patient-id").innerText = report.patient_id;
    document.getElementById("modal-report-date").innerText = report.report_date || "Unknown";
    document.getElementById("modal-report-category").innerText = report.report_category;
    document.getElementById("modal-report-format").innerText = report.file_format.toUpperCase();
    document.getElementById("modal-report-status").innerText = report.extraction_status;

    // Render 4 abnormal summary boxes
    renderAbnormalBox("box-below", abSummary.below_range, "var(--danger)");
    renderAbnormalBox("box-above", abSummary.above_range, "#ea580c");
    renderAbnormalBox("box-normal", abSummary.within_range, "var(--success)");
    renderAbnormalBox("box-review", [...abSummary.requires_review, ...abSummary.reference_range_unavailable], "var(--warning)");

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

    document.getElementById("report-modal").classList.add("active");
  } catch (err) {
    showToast(`Error opening report: ${err.message}`, true);
  }
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
    const unkBanner = document.getElementById("calendar-unknown-dates-container");
    if (unknownReports.length > 0) {
      unkBanner.innerHTML = `
        <div style="background:var(--warning-bg); border:1px solid var(--warning); border-radius:var(--radius); padding:0.75rem 1rem; margin-top:1rem; font-size:0.85rem;">
          <strong>⚠ Notice:</strong> ${unknownReports.length} report(s) have unrecorded or missing dates. Dates are not invented.
          <button class="btn btn-sm btn-outline" style="margin-left:0.5rem;" onclick="showDateReports('Unknown Date', ${JSON.stringify(unknownReports).replace(/"/g, '&quot;')})">View Unscheduled Reports</button>
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
          <span style="font-size:0.75rem;">${r.parameter_count} parameters &bull; Status: ${r.extraction_status}</span>
        </div>
        <button class="btn btn-sm btn-outline" onclick="openReportModal('${r.report_id}')">Open</button>
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
