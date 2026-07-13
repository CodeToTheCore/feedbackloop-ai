/*
 * app.js
 * ------
 * All data on screen comes from the FastAPI backend -- nothing here is
 * hardcoded sample content. Every card/row is clickable and opens a
 * "record inspector" modal showing the actual underlying database rows
 * (see /api/candidates/{id}/full and /api/interviews/{id}/full).
 */

const API = ""; // same-origin
let CURRENT_REQ_ID = null;
let mode = "recruiter";
let activeTab = "sla";
let hmSelectedCandidateId = null;
let reparticipationAlerted = false;  // fire the re-participation popup only once per load

const RING_CIRCUMFERENCE = 2 * Math.PI * 20; // r=20

const STATE_COLOR = {
  submitted: "#6FA88A",
  on_track: "#7C93C7",
  reminded: "#E8A33D",
  escalated: "#D5695D",
  overdue: "#D5695D",
  review: "#7C93C7",
};

const STATE_LABEL = {
  submitted: "Submitted",
  on_track: "On track",
  reminded: "Reminder sent",
  escalated: "Escalated",
  overdue: "Overdue",
  review: "Needs review",
};

async function api(path, opts) {
  const res = await fetch(API + path, opts);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

function fmt(dtStr) {
  const d = new Date(dtStr);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function fmtHours(h) {
  if (h <= 0) return "past due";
  return `${h}h`;
}

// ---------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------
async function init() {
  const reqs = await api("/api/requisitions");
  const req = reqs[0];
  CURRENT_REQ_ID = req.id;

  document.getElementById("req-picker").innerHTML =
    `<strong>${req.title}</strong>${req.req_code} &middot; opened ${new Date(req.opened_date).toLocaleDateString()}`;

  await Promise.all([loadSlaMonitor(), loadComparison()]);
  wireStaticControls();
}

function wireStaticControls() {
  document.getElementById("btn-recruiter").addEventListener("click", () => { mode = "recruiter"; render(); });
  document.getElementById("btn-hm").addEventListener("click", () => { mode = "hm"; render(); });
  document.querySelectorAll(".tab").forEach(t =>
    t.addEventListener("click", () => { activeTab = t.dataset.tab; render(); })
  );
  document.getElementById("modal-close").addEventListener("click", closeModal);
  document.getElementById("modal-backdrop").addEventListener("click", (e) => {
    if (e.target.id === "modal-backdrop") closeModal();
  });
}

// ---------------------------------------------------------------------
// SLA Monitor
// ---------------------------------------------------------------------
let slaRows = [];

async function loadSlaMonitor() {
  slaRows = await api(`/api/requisitions/${CURRENT_REQ_ID}/sla-monitor`);
  slaRows.sort((a, b) => a.hours_remaining - b.hours_remaining);
  document.getElementById("count-sla").textContent = `${slaRows.length} tracked`;
  renderSlaGrid();
}

function renderSlaGrid() {
  const grid = document.getElementById("sla-grid");
  grid.innerHTML = slaRows.map(row => {
    const color = STATE_COLOR[row.state] || "#565C68";
    const frac = Math.max(0, Math.min(1, row.hours_remaining / 24));
    const dashoffset = RING_CIRCUMFERENCE * (1 - frac);
    return `
      <div class="sla-row" data-interview-id="${row.interview_id}">
        <div class="ring-wrap">
          <svg width="48" height="48">
            <circle class="ring-bg" cx="24" cy="24" r="20"/>
            <circle class="ring-fg" cx="24" cy="24" r="20" stroke="${color}"
              stroke-dasharray="${RING_CIRCUMFERENCE}" stroke-dashoffset="${dashoffset}"/>
          </svg>
          <div class="ring-label">${fmtHours(row.hours_remaining)}</div>
        </div>
        <div class="candidate-info">
          <div class="name-row"><span class="name">${row.candidate_name}</span></div>
          <div class="meta">Panel: ${row.interviewer_name} (${row.interviewer_role}) &middot; scheduled ${fmt(row.scheduled_time)}</div>
        </div>
        <div class="status-pill ${row.state}">${STATE_LABEL[row.state] || row.state}</div>
        <div class="action-cell">
          <span class="time">Due ${fmt(row.feedback_due)}</span>
          <span class="action">${row.reminder_count} reminder(s) sent &middot; click for detail</span>
        </div>
      </div>`;
  }).join("");

  grid.querySelectorAll(".sla-row").forEach(el =>
    el.addEventListener("click", () => openInterviewModal(el.dataset.interviewId))
  );
}

// ---------------------------------------------------------------------
// Candidate Comparison (recruiter)
// ---------------------------------------------------------------------
let comparisonData = null;

async function loadComparison() {
  comparisonData = await api(`/api/requisitions/${CURRENT_REQ_ID}/comparison`);
  document.getElementById("count-compare").textContent = `${comparisonData.ranking.length} candidates`;
  renderCriteriaStrip();
  renderRankCards();
  renderHmPicker();
}

function renderCriteriaStrip() {
  const musts = comparisonData.criteria.filter(c => c.category === "must_have").map(c => c.text).join("; ");
  const nices = comparisonData.criteria.filter(c => c.category === "nice_to_have").map(c => c.text).join("; ");
  document.getElementById("criteria-strip").innerHTML = `
    <div class="crit"><span class="label">Must-have</span><span class="value">${musts}</span></div>
    <div class="crit"><span class="label">Nice-to-have</span><span class="value">${nices}</span></div>
    <div class="crit"><span class="label">Req</span><span class="value">${comparisonData.req_code} &middot; ${comparisonData.title}</span></div>
  `;
}

function renderRankCards() {
  const el = document.getElementById("rank-cards");
  el.innerHTML = comparisonData.ranking.map(r => {
    const cardClass = r.rank === 1 ? "rank-1" : (r.conflict ? "conflict" : "");
    const excludedNote = r.excluded.length
      ? `<div class="conflict-note"><span class="icon">i</span><span class="text">
          ${r.excluded.map(e => `${e.interviewer}'s scorecard excluded: ${e.reason}`).join("<br>")}
         </span></div>` : "";
    const conflictNote = r.conflict
      ? `<div class="conflict-note"><span class="icon">!</span><span class="text">Conflicting feedback, not averaged &mdash; recruiter decision needed.</span></div>`
      : "";
    const historyNote = (r.history && r.history.length)
      ? `<div class="history-note"><span class="icon">&#8635;</span><span class="text">
          <strong>Re-participated candidate</strong><br>
          ${r.history.map(h => `Prior: ${h.req_code} (${h.title}) &middot; reached ${h.stage_reached}, ${h.outcome.replace(/_/g, " ")}${h.date ? " &middot; " + h.date : ""}`).join("<br>")}
         </span></div>` : "";
    return `
      <div class="rank-card ${cardClass}" data-candidate-id="${r.candidate_id}">
        <div class="rank-card-head">
          <div style="display:flex; gap:14px;">
            <div class="rank-badge ${r.rank === 1 ? 'top' : ''}">0${r.rank}</div>
            <div><div class="rank-name">${r.candidate_name}</div>
              <div class="rank-role">${r.num_scorecards_in} scorecard(s) in ${r.excluded.length ? '&middot; ' + r.excluded.length + ' excluded' : ''}</div></div>
          </div>
          <div class="rank-signal"><div class="score" style="color:${labelColor(r.label)};">${r.label}</div>
            <div class="score-label">signal score ${r.signal_score}</div></div>
        </div>
        <div class="rationale">${r.rationale}</div>
        ${conflictNote}${historyNote}${excludedNote}
      </div>`;
  }).join("");

  el.querySelectorAll(".rank-card").forEach(card =>
    card.addEventListener("click", () => openCandidateModal(card.dataset.candidateId))
  );
}

function labelColor(label) {
  if (label === "Strong Hire") return "#6FA88A";
  if (label === "Conflicted") return "#D5695D";
  if (label === "Lean No Hire") return "#D5695D";
  if (label === "Insufficient data") return "#565C68";
  return "#E8A33D";
}

// ---------------------------------------------------------------------
// Hiring manager view
// ---------------------------------------------------------------------
function renderHmPicker() {
  const picker = document.getElementById("hm-candidate-picker");
  picker.innerHTML = comparisonData.ranking.map(r =>
    `<button data-id="${r.candidate_id}">${r.candidate_name}</button>`
  ).join("");
  picker.querySelectorAll("button").forEach(btn =>
    btn.addEventListener("click", () => { hmSelectedCandidateId = btn.dataset.id; render(); })
  );
  if (!hmSelectedCandidateId && comparisonData.ranking.length) {
    hmSelectedCandidateId = comparisonData.ranking[0].candidate_id;
  }
}

async function renderHmSummary() {
  const picker = document.getElementById("hm-candidate-picker");
  picker.querySelectorAll("button").forEach(b =>
    b.classList.toggle("active", b.dataset.id == hmSelectedCandidateId)
  );
  if (!hmSelectedCandidateId) return;
  const summary = await api(`/api/candidates/${hmSelectedCandidateId}/summary`);
  const scoresHtml = summary.scores.length
    ? summary.scores.map(s => `<div class="s"><div class="who">${s.interviewer}</div><div class="val">${s.score}</div></div>`).join("")
    : `<div class="empty-list">No usable scorecards yet.</div>`;
  document.getElementById("hm-summary").innerHTML = `
    <div class="hm-single-card">
      <h2>${summary.candidate_name}</h2>
      <div class="sub">${comparisonData.req_code} &middot; ${comparisonData.title} &middot; ${summary.scores.length} scorecard(s) usable</div>
      <div class="hm-scores">${scoresHtml}</div>
      ${summary.conflict ? '<div class="conflict-note"><span class="icon">!</span><span class="text">Panel feedback conflicts on this candidate.</span></div>' : ''}
      <div class="hm-next"><b>Suggested next step:</b> ${summary.next_step}</div>
    </div>`;
}

// ---------------------------------------------------------------------
// Deep-dive modal: raw DB record inspector
// ---------------------------------------------------------------------
function openModal(title) {
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-backdrop").style.display = "flex";
}
function closeModal() {
  document.getElementById("modal-backdrop").style.display = "none";
}

async function openInterviewModal(interviewId) {
  const data = await api(`/api/interviews/${interviewId}/full`);
  openModal(`Interview #${data.interview.id} — ${data.interview.candidate_name}`);
  const iv = data.interview, sc = data.scorecard;

  const body = document.getElementById("modal-body");
  body.innerHTML = `
    <div class="modal-section">
      <span class="db-table-label">table: interviews</span>
      <div class="kv-grid">
        <div class="k">id</div><div class="v mono">${iv.id}</div>
        <div class="k">candidate_id</div><div class="v mono">${iv.candidate_id}</div>
        <div class="k">interviewer_name</div><div class="v">${iv.interviewer_name}</div>
        <div class="k">interviewer_role</div><div class="v">${iv.interviewer_role}</div>
        <div class="k">panel_stage</div><div class="v">${iv.panel_stage}</div>
        <div class="k">scheduled_time</div><div class="v mono">${iv.scheduled_time}</div>
        <div class="k">feedback_due</div><div class="v mono">${iv.feedback_due}</div>
      </div>
    </div>

    <div class="modal-section">
      <span class="db-table-label">computed: sla_status</span>
      <div class="kv-grid">
        <div class="k">state</div><div class="v mono">${data.sla_status.state}</div>
        <div class="k">hours_remaining</div><div class="v mono">${data.sla_status.hours_remaining}</div>
      </div>
    </div>

    <div class="modal-section">
      <span class="db-table-label">table: scorecards</span>
      ${sc ? `
        <div class="kv-grid">
          <div class="k">id</div><div class="v mono">${sc.id}</div>
          <div class="k">status</div><div class="v mono">${sc.status}</div>
          <div class="k">score</div><div class="v">${sc.score ?? '—'}</div>
          <div class="k">written_feedback</div><div class="v">${sc.written_feedback ?? '—'}</div>
          <div class="k">submitted_at</div><div class="v mono">${sc.submitted_at ?? '—'}</div>
          <div class="k">flagged_injection</div><div class="v mono">${sc.flagged_injection}</div>
          <div class="k">excluded_from_synthesis</div><div class="v mono">${sc.excluded_from_synthesis}</div>
          <div class="k">flag_reason</div><div class="v">${sc.flag_reason ?? '—'}</div>
        </div>` : `<div class="empty-list">No scorecard row yet — pending.</div>`}
    </div>

    <div class="modal-section">
      <span class="db-table-label">table: reminders</span>
      ${data.reminders.length ? `<div class="kv-grid">${data.reminders.map(r =>
        `<div class="k">#${r.id}</div><div class="v mono">${r.sent_at} &middot; ${r.channel} &middot; ${r.status}</div>`
      ).join("")}</div>` : `<div class="empty-list">No reminders sent yet.</div>`}
    </div>

    <div class="modal-section">
      <span class="db-table-label">table: escalations</span>
      ${data.escalations.length ? `<div class="kv-grid">${data.escalations.map(e =>
        `<div class="k">#${e.id}</div><div class="v">${e.reason} <span class="mono">(${e.created_at})</span></div>`
      ).join("")}</div>` : `<div class="empty-list">Not escalated.</div>`}
    </div>

    <button class="remind-btn" id="remind-action">Trigger send_reminder for this interview</button>
    <div class="remind-result" id="remind-result"></div>
  `;

  document.getElementById("remind-action").addEventListener("click", async () => {
    const result = await api(`/api/interviews/${interviewId}/remind`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel: "slack" }),
    });
    document.getElementById("remind-result").textContent =
      `action: ${result.action}${result.reason ? " — " + result.reason : ""}`;
    await loadSlaMonitor(); // refresh underlying rows so the rate limit is visibly enforced
  });
}

async function openCandidateModal(candidateId) {
  const data = await api(`/api/candidates/${candidateId}/full`);
  openModal(`Candidate #${data.candidate.id} — ${data.candidate.name}`);

  const body = document.getElementById("modal-body");
  body.innerHTML = `
    <div class="modal-section">
      <span class="db-table-label">table: candidates</span>
      <div class="kv-grid">
        <div class="k">id</div><div class="v mono">${data.candidate.id}</div>
        <div class="k">req_id</div><div class="v mono">${data.candidate.req_id}</div>
        <div class="k">name</div><div class="v">${data.candidate.name}</div>
        <div class="k">stage</div><div class="v">${data.candidate.stage}</div>
      </div>
    </div>

    <div class="modal-section">
      <span class="db-table-label">computed: synthesis (agent.synthesize_candidate)</span>
      <div class="kv-grid">
        <div class="k">conflict</div><div class="v mono">${data.synthesis.conflict}</div>
        <div class="k">next_step</div><div class="v">${data.synthesis.next_step}</div>
        <div class="k">excluded</div><div class="v">${data.synthesis.excluded.length ? data.synthesis.excluded.map(e => e.reason).join("; ") : "none"}</div>
      </div>
    </div>

    <div class="modal-section">
      <span class="db-table-label">table: interviews (${data.interviews.length} rows, joined)</span>
      ${data.interviews.map(iv => `
        <div style="border-top:1px solid var(--border-soft); padding-top:10px; margin-top:10px;">
          <div class="kv-grid">
            <div class="k">interview_id</div><div class="v mono">${iv.id}</div>
            <div class="k">interviewer</div><div class="v">${iv.interviewer_name} (${iv.interviewer_role})</div>
            <div class="k">scorecard.status</div><div class="v mono">${iv.scorecard ? iv.scorecard.status : '—'}</div>
            <div class="k">scorecard.score</div><div class="v">${iv.scorecard ? (iv.scorecard.score ?? '—') : '—'}</div>
            <div class="k">flagged_injection</div><div class="v mono">${iv.scorecard ? iv.scorecard.flagged_injection : '—'}</div>
          </div>
        </div>
      `).join("")}
    </div>
  `;
}

// ---------------------------------------------------------------------
// Render dispatcher
// ---------------------------------------------------------------------
function render() {
  document.getElementById("btn-recruiter").classList.toggle("active", mode === "recruiter");
  document.getElementById("btn-hm").classList.toggle("active", mode === "hm");
  document.getElementById("hm-note").style.display = mode === "hm" ? "flex" : "none";

  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === activeTab));
  document.getElementById("view-sla").style.display = activeTab === "sla" ? "block" : "none";

  const showCompareRecruiter = activeTab === "compare" && mode === "recruiter";
  const showCompareHm = activeTab === "compare" && mode === "hm";
  document.getElementById("view-compare").style.display = showCompareRecruiter ? "block" : "none";
  document.getElementById("view-compare-hm").style.display = showCompareHm ? "block" : "none";

  if (showCompareHm) renderHmSummary();
  if (showCompareRecruiter) maybeShowReparticipationAlert();
}

// ---------------------------------------------------------------------
// Re-participated candidate alert: fires once when the recruiter's
// Candidate Comparison view first loads, if any candidate has cross-req
// history (get_candidate_history match). Alert + popup per the PRD follow-up.
// ---------------------------------------------------------------------
function maybeShowReparticipationAlert() {
  if (reparticipationAlerted || !comparisonData) return;
  const matches = comparisonData.ranking.filter(r => r.history && r.history.length);
  if (!matches.length) return;
  reparticipationAlerted = true;

  openModal(`Re-participated candidate${matches.length > 1 ? "s" : ""} detected`);
  const body = document.getElementById("modal-body");
  body.innerHTML = `
    <div class="modal-section">
      <p class="reparticipation-lead">
        ${matches.length} candidate${matches.length > 1 ? "s have" : " has"} interviewed with the company
        before. Prior outcomes are surfaced below &mdash; verify against the full record before advancing.
      </p>
      ${matches.map(m => `
        <div class="reparticipation-item">
          <div class="reparticipation-name">${m.candidate_name}</div>
          ${m.history.map(h => `<div class="reparticipation-hist">
              ${h.req_code} &middot; ${h.title} &middot; reached ${h.stage_reached}, ${h.outcome.replace(/_/g, " ")}${h.date ? " &middot; " + h.date : ""}
            </div>`).join("")}
          <button class="reparticipation-view" data-candidate-id="${m.candidate_id}">View candidate record</button>
        </div>`).join("")}
      <div class="reparticipation-actions"><button id="reparticipation-dismiss">Dismiss</button></div>
    </div>`;

  body.querySelector("#reparticipation-dismiss").addEventListener("click", closeModal);
  body.querySelectorAll(".reparticipation-view").forEach(b =>
    b.addEventListener("click", () => openCandidateModal(b.dataset.candidateId))
  );
}

init();
