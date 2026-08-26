let currentSessionId = null;
let traceEvents = [];

// ---------- API helpers ----------
async function fetchJson(url, options = {}) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text);
  }
  return resp.json();
}

function clearTraceDisplay() {
  traceEvents = [];
  renderTrace();
}

function copyAllToClipboard() {
  const text = traceEvents
    .map(
      e =>
        `[${e.timestamp}] ${e.component} ${e.action} ${e.status} ${e.duration ?? ""} ${e.result_summary ?? ""}`
    )
    .join("\n");
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text || "(empty)").catch(() => fallbackCopy(text));
  } else {
    fallbackCopy(text);
  }
}

function fallbackCopy(text) {
  const ta = document.createElement("textarea");
  ta.value = text;
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand("copy");
  } catch {
    alert("Copy not supported");
  }
  document.body.removeChild(ta);
}

// ---------- UI rendering ----------
function renderTransparency(info) {
  document.getElementById("curr-action").textContent = info.current_action || "idle";
  document.getElementById("curr-component").textContent = info.current_component || "none";
  document.getElementById("curr-mcp").textContent = info.current_mcp_tool || "none";
  document.getElementById("curr-elapsed").textContent = info.elapsed || "0s";
  document.getElementById("curr-last").textContent = info.last_completed || "none";
  document.getElementById("curr-next").textContent = info.next_expected || "none";
}

function renderTimeline(timeline) {
  const container = document.getElementById("timeline-container");
  container.innerHTML = timeline
    .map(s => `<span class="timeline-stage ${s.status}">${s.stage}</span>`)
    .join("");
}

function renderTrace() {
  const filter = document.getElementById("trace-filter").value;
  const container = document.getElementById("trace-list-container");
  const filtered = filter === "all"
    ? traceEvents
    : traceEvents.filter(e => e.component === filter);
  if (filtered.length === 0) {
    container.innerHTML = "(no events)";
    return;
  }
  const html = filtered
    .map(
      e =>
        `<div class="trace-row">
           <span class="ts">[${e.timestamp}]</span>
           <span class="comp">${e.component}</span>
           <span class="action">${e.action}</span>
           <span class="stat">${e.status}</span>
           <span class="dur">${e.duration ? e.duration.toFixed(1) + "s" : ""}</span>
           <span class="sum">${e.result_summary ? e.result_summary : ""}</span>
         </div>`
    )
    .join("");
  container.innerHTML = html;
}

function renderSetupPlan(planId, planStatus) {
  document.getElementById("setup-plan-content").innerHTML = `
    <p>Plan ID: ${planId || "?"}</p>
    <p>Status: ${planStatus || "?"}</p>
  `;
}

function renderApprovalPanel(state) {
  const area = document.getElementById("approval-area");
  if (state.approval_required && state.approval_status !== "approved") {
    area.style.display = "block";
    document.getElementById("approval-plan-text").innerText =
      `Project ${state.project_id}, plan ${state.plan_id} awaits your approval.`;
  } else {
    area.style.display = "none";
  }
}

function updateUI(state) {
  traceEvents = state.trace || [];
  renderTransparency(state.transparency);
  renderTimeline(state.timeline);
  renderTrace();
  renderSetupPlan(state.plan_id, state.approval_status);
  renderApprovalPanel(state);
}

// ---------- Actions ----------
async function startWorkflow() {
  const projectName = document.getElementById("project-name-input").value.trim();
  const projectDir = document.getElementById("project-dir-input").value.trim();
  if (!projectName || !projectDir) {
    alert("Please enter project name and directory.");
    return;
  }
  const resp = await fetchJson("/api/workflow/start", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({project_name: projectName, project_directory: projectDir}),
  });
  currentSessionId = resp.session_id;
  document.getElementById("project-name-display").textContent = projectName;
  await loadState();
}

async function loadState() {
  if (!currentSessionId) return;
  const state = await fetchJson(`/api/state/${currentSessionId}`);
  updateUI(state);
}

async function approveWorkflow() {
  if (!currentSessionId) return;
  await fetchJson(`/api/workflow/${currentSessionId}/approve`, {method: "POST"});
  await loadState();
}

async function rejectWorkflow() {
  if (!currentSessionId) return;
  await fetchJson(`/api/workflow/${currentSessionId}/reject`, {method: "POST"});
  await loadState();
}

// ---------- Event binding ----------
document.getElementById("start-workflow-btn").addEventListener("click", startWorkflow);
document.getElementById("approve-btn").addEventListener("click", approveWorkflow);
document.getElementById("reject-btn").addEventListener("click", rejectWorkflow);
document.getElementById("clear-trace-btn").addEventListener("click", clearTraceDisplay);
document.getElementById("copy-all-btn").addEventListener("click", copyAllToClipboard);
document.getElementById("trace-filter").addEventListener("change", renderTrace);
