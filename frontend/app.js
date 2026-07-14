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

const GENERIC_ERROR = "System error! Please refresh and try again";

async function api(path, opts) {
  let res;
  try {
    res = await fetch(API + path, opts);
  } catch (e) {
    // Network / connectivity failure -- the server (and its DB) is unreachable.
    showError(GENERIC_ERROR);
    throw e;
  }
  if (!res.ok) {
    // Surface the server's message when it provides one (DB errors send the
    // "System error! Please refresh and try again" detail); fall back otherwise.
    let msg = GENERIC_ERROR;
    try {
      const body = await res.json();
      if (body && body.detail) msg = body.detail;
    } catch (_) { /* non-JSON error body */ }
    showError(msg);
    throw new Error(`${path} -> ${res.status}`);
  }
  return res.json();
}

function showError(msg) {
  document.getElementById("error-banner-text").textContent = msg;
  document.getElementById("error-banner").style.display = "flex";
}

function hideError() {
  document.getElementById("error-banner").style.display = "none";
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
  // Wire static UI first so controls (tabs, modal, error dismiss) work even
  // when data loading fails -- e.g. a DB error, where the banner must be
  // dismissable and the app must not be left half-initialised.
  wireStaticControls();

  // Interviewer link (?interview={id}) -> show only the scorecard dashboard.
  const ivId = new URLSearchParams(location.search).get("interview");
  if (ivId) {
    const o = document.getElementById("intro-overlay");
    if (o) o.remove();
    document.querySelector(".app").style.display = "none";
    await renderInterviewerView(ivId);
    return;
  }

  scheduleIntroDismiss();  // fade the cold-open splash into the app

  let req;
  try {
    const reqs = await api("/api/requisitions");
    req = reqs[0];
  } catch (e) {
    return; // api() already surfaced the error banner
  }
  CURRENT_REQ_ID = req.id;

  document.getElementById("req-picker").innerHTML =
    `<strong>${req.title}</strong>${req.req_code} &middot; opened ${new Date(req.opened_date).toLocaleDateString()}`;

  // allSettled: one view failing (e.g. its query errors) still lets the other load.
  await Promise.allSettled([loadSlaMonitor(), loadComparison()]);
}

function wireStaticControls() {
  document.getElementById("btn-recruiter").addEventListener("click", () => { mode = "recruiter"; render(); });
  document.getElementById("btn-hm").addEventListener("click", () => { mode = "hm"; render(); });
  document.querySelectorAll(".tab").forEach(t =>
    t.addEventListener("click", () => { activeTab = t.dataset.tab; render(); })
  );
  document.getElementById("error-banner-close").addEventListener("click", hideError);
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
          <a class="scorecard-link" href="/?interview=${row.interview_id}" target="_blank" rel="noopener">add / review notes &#8599;</a>
        </div>
      </div>`;
  }).join("");

  grid.querySelectorAll(".scorecard-link").forEach(a =>
    a.addEventListener("click", e => e.stopPropagation())  // don't open the record modal
  );
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
  renderDebrief();
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

    // Case 2b: same person, different email on file -> verify/switch prompt.
    const emailUpdateNote = (r.email_update && !r.fraud_flagged)
      ? `<div class="switch-note"><span class="icon">&#9998;</span><span class="text">
          <strong>Different email on file</strong><br>
          Same person previously used ${r.email_update.records.map(x => `${x.email} (${x.req_code})`).join(", ")}.
          Current: ${r.email_update.current_email}.
          <button class="note-action" data-action="switch-email" data-candidate-id="${r.candidate_id}">Verify &amp; switch</button>
         </span></div>` : "";

    // Case 2a: same email on a different identity -> possible fraud.
    const fraudNote = r.fraud_flagged
      ? `<div class="fraud-note flagged"><span class="icon">&#9873;</span><span class="text">
          <strong>Flagged as fraudulent</strong><br>${r.fraud_reason || ""}
         </span></div>`
      : (r.email_conflict
        ? `<div class="fraud-note"><span class="icon">&#9888;</span><span class="text">
            <strong>Possible fraud &mdash; shared email</strong><br>
            ${r.email_conflict.conflicting_email} is also on file for a different identity:
            ${r.email_conflict.records.map(x => `${x.name} (${x.req_code})`).join(", ")}. No prior history attached.
            <button class="note-action danger" data-action="flag-fraud" data-candidate-id="${r.candidate_id}">Mark as fraudulent</button>
           </span></div>` : "");
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
        ${conflictNote}${historyNote}${emailUpdateNote}${fraudNote}${excludedNote}
      </div>`;
  }).join("");

  // Note-action buttons must not bubble up to the card's record-modal click.
  el.querySelectorAll(".note-action").forEach(btn =>
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const id = btn.dataset.candidateId;
      if (btn.dataset.action === "flag-fraud") confirmFlagFraud(id);
      else if (btn.dataset.action === "switch-email") confirmSwitchEmail(id);
    })
  );

  el.querySelectorAll(".rank-card").forEach(card =>
    card.addEventListener("click", () => openCandidateModal(card.dataset.candidateId))
  );
}

// ---------------------------------------------------------------------
// 2a/2b identity actions (fraud flag + email switch), each behind a confirm
// prompt. On success we reload the comparison so the card reflects the new state.
// ---------------------------------------------------------------------
function findRanked(candidateId) {
  return comparisonData.ranking.find(r => String(r.candidate_id) === String(candidateId));
}

function confirmFlagFraud(candidateId) {
  const r = findRanked(candidateId);
  const who = r.email_conflict ? r.email_conflict.records.map(x => `${x.name} (${x.req_code})`).join(", ") : "another identity";
  confirmModal(
    "Mark as fraudulent?",
    `${r.candidate_name}'s email (${r.email_conflict ? r.email_conflict.conflicting_email : ""}) is shared with ${who}. ` +
      `Marking this record fraudulent flags it for review. This is a recruiter decision and can be seen by others.`,
    "Mark as fraudulent",
    async () => {
      await api(`/api/candidates/${candidateId}/flag-fraud`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: `Email shared with ${who}.` }),
      });
      await loadComparison();
    }
  );
}

function confirmSwitchEmail(candidateId) {
  const r = findRanked(candidateId);
  const target = r.email_update.current_email;
  const stale = r.email_update.records;
  confirmModal(
    "Verify & switch email?",
    `This is the same person across requisitions, but ${stale.map(x => `${x.email} (${x.req_code})`).join(", ")} ` +
      `differs from the current ${target}. Confirm it's the same person to reconcile the older record(s) to ${target}.`,
    "Switch to current email",
    async () => {
      for (const rec of stale) {
        await api(`/api/candidates/${rec.candidate_id}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: target }),
        });
      }
      await loadComparison();
    }
  );
}

function confirmModal(title, message, confirmLabel, onConfirm) {
  openModal(title);
  const body = document.getElementById("modal-body");
  body.innerHTML = `
    <div class="modal-section">
      <p class="confirm-message">${message}</p>
      <div class="confirm-actions">
        <button id="confirm-cancel">Cancel</button>
        <button id="confirm-ok" class="danger">${confirmLabel}</button>
      </div>
    </div>`;
  body.querySelector("#confirm-cancel").addEventListener("click", closeModal);
  body.querySelector("#confirm-ok").addEventListener("click", async () => {
    const ok = body.querySelector("#confirm-ok");
    ok.disabled = true;
    try {
      await onConfirm();
      closeModal();
    } catch (e) {
      // api() already showed the error banner; leave the modal open to retry.
      ok.disabled = false;
    }
  });
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
    const link = result.scorecard_url
      ? ` &middot; <a href="${result.scorecard_url}" target="_blank" rel="noopener">open interviewer scorecard &#8599;</a>` : "";
    document.getElementById("remind-result").innerHTML =
      `action: ${result.action}${result.reason ? " — " + result.reason : ""}${link}`;
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

// ---------------------------------------------------------------------
// Interviewer scorecard dashboard (opened via the agent's reminder link).
// Lets a panelist add notes and review the notes they've made.
// ---------------------------------------------------------------------
const SCORE_OPTIONS = ["Strong Yes", "Yes", "No", "Strong No"];

// Fade the cold-open splash out after it plays, revealing the dashboard.
function scheduleIntroDismiss() {
  const o = document.getElementById("intro-overlay");
  if (!o) return;
  const kill = () => { o.classList.add("fade"); setTimeout(() => o.remove(), 750); };
  const skip = document.getElementById("intro-skip");
  if (skip) skip.addEventListener("click", (e) => { e.preventDefault(); kill(); });
  setTimeout(kill, 7500);  // let the animation play, then dissolve into the app
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function renderInterviewerView(interviewId) {
  const view = document.getElementById("interviewer-view");
  view.style.display = "block";
  let data;
  try {
    data = await api(`/api/interviews/${interviewId}/scorecard-view`);
  } catch (e) {
    view.innerHTML = `<div class="iv-wrap"><div class="iv-card"><h1 class="iv-candidate">Scorecard unavailable</h1>
      <div class="iv-sub">We couldn't load this interview. Please check the link and try again.</div></div></div>`;
    return;
  }
  renderInterviewerCard(interviewId, data, false);
}

function renderInterviewerCard(interviewId, data, editing) {
  const view = document.getElementById("interviewer-view");
  const sc = data.scorecard;
  const submitted = sc && sc.status === "submitted";
  const musts = data.criteria.filter(c => c.category === "must_have");
  const nices = data.criteria.filter(c => c.category === "nice_to_have");
  const showForm = !submitted || editing;

  const critHtml = `
    <div class="iv-criteria">
      <div class="iv-crit-group"><span class="iv-crit-label">Must-have</span>
        <ul>${musts.map(c => `<li>${c.text}</li>`).join("")}</ul></div>
      ${nices.length ? `<div class="iv-crit-group"><span class="iv-crit-label">Nice-to-have</span>
        <ul>${nices.map(c => `<li>${c.text}</li>`).join("")}</ul></div>` : ""}
    </div>`;

  const bodyHtml = showForm
    ? `<form id="iv-form" class="iv-form">
        <div class="iv-field-label">Your recommendation</div>
        <div class="iv-score-options">
          ${SCORE_OPTIONS.map(o => `<label class="iv-score-opt">
            <input type="radio" name="score" value="${o}" ${sc && sc.score === o ? "checked" : ""}> ${o}</label>`).join("")}
        </div>
        <label class="iv-field-label" for="iv-notes">Your notes</label>
        <textarea id="iv-notes" class="iv-notes" rows="6"
          placeholder="What did you assess? Be specific against the criteria above.">${sc && sc.written_feedback ? escapeHtml(sc.written_feedback) : ""}</textarea>
        <div class="iv-actions"><button type="submit" class="iv-submit">${submitted ? "Update my notes" : "Submit scorecard"}</button></div>
        <div class="iv-msg" id="iv-msg"></div>
      </form>`
    : `<div class="iv-review">
        <div class="iv-review-head"><span class="iv-badge">Submitted</span>${sc.submitted_at ? " on " + new Date(sc.submitted_at).toLocaleString() : ""}</div>
        <div class="iv-review-score">Recommendation: <strong>${sc.score}</strong></div>
        <div class="iv-review-notes">${sc.written_feedback ? escapeHtml(sc.written_feedback) : "(no written notes)"}</div>
        ${sc.flagged_injection ? `<div class="iv-flag">This note was flagged as a possible embedded instruction and excluded from the candidate synthesis. If this was a genuine evaluation, please rephrase and resubmit.</div>` : ""}
        <div class="iv-actions"><button id="iv-edit" class="iv-submit ghost">Update my notes</button></div>
      </div>`;

  view.innerHTML = `
    <div class="iv-wrap">
      <div class="iv-card">
        <div class="iv-brand"><div class="brand-mark">FL</div>
          <div><div class="iv-brand-title">FeedbackLoop AI</div><div class="iv-brand-sub">Interview scorecard</div></div></div>
        <h1 class="iv-candidate">${data.candidate_name}</h1>
        <div class="iv-sub">${data.req_code} &middot; ${data.title} &middot; ${data.interview.panel_stage} panel</div>
        <div class="iv-sub">You: ${data.interview.interviewer_name} (${data.interview.interviewer_role}) &middot; feedback due ${new Date(data.interview.feedback_due).toLocaleString()}</div>
        <div class="iv-section-label">Assess against the intake criteria</div>
        ${critHtml}
        <div class="iv-section-label">${showForm ? "Add your notes" : "Your submitted notes"}</div>
        ${bodyHtml}
      </div>
    </div>`;

  if (showForm) {
    document.getElementById("iv-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const picked = view.querySelector('input[name="score"]:checked');
      const msg = document.getElementById("iv-msg");
      if (!picked) { msg.textContent = "Please choose a recommendation."; msg.className = "iv-msg error"; return; }
      try {
        await api(`/api/interviews/${interviewId}/scorecard`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ score: picked.value, written_feedback: document.getElementById("iv-notes").value }),
        });
        const fresh = await api(`/api/interviews/${interviewId}/scorecard-view`);
        renderInterviewerCard(interviewId, fresh, false);  // -> review state
      } catch (err) { /* api() already surfaced the error banner */ }
    });
  } else {
    document.getElementById("iv-edit").addEventListener("click", () =>
      renderInterviewerCard(interviewId, data, true));
  }
}

// ---------------------------------------------------------------------
// Recruiter debrief: a one-glance "who to move along" summary of the ranking.
// ---------------------------------------------------------------------
function renderDebrief() {
  const r = comparisonData.ranking;
  const flagged = r.filter(c => c.fraud_flagged);
  const decide = r.filter(c => c.conflict && !c.fraud_flagged);
  const advance = r.filter(c => !c.conflict && !c.fraud_flagged && (c.label === "Strong Hire" || c.label === "Lean Hire"));
  const hold = r.filter(c => !flagged.includes(c) && !decide.includes(c) && !advance.includes(c));
  const chip = arr => arr.length ? arr.map(c => c.candidate_name).join(", ") : "—";
  document.getElementById("compare-debrief").innerHTML = `
    <div class="debrief">
      <div class="debrief-title">Debrief &mdash; who to move along</div>
      <div class="debrief-grid">
        <div class="debrief-col advance"><span class="dl">Move forward</span><span class="dv">${chip(advance)}</span></div>
        <div class="debrief-col decide"><span class="dl">Needs your decision</span><span class="dv">${chip(decide)}</span></div>
        <div class="debrief-col flagged"><span class="dl">Flagged</span><span class="dv">${chip(flagged)}</span></div>
        <div class="debrief-col hold"><span class="dl">Hold / insufficient</span><span class="dv">${chip(hold)}</span></div>
      </div>
    </div>`;
}

init();
