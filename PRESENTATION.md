# FeedbackLoop AI — Presentation Guide

**Live:** https://feedbackloop-ai.onrender.com
**One-liner:** An AI interview-feedback agent that chases interviewers for scorecards, synthesizes panel feedback into a ranked candidate comparison, and helps recruiters decide who to advance — with guardrails so the AI never makes the hiring call or gets manipulated by malicious input.

**The throughline:** *Decisions stay in deterministic code; the LLM only writes prose.* Every feature keeps the "blast radius" small.

---

## Build story (in order)

### Phase 0 — Baseline (v1, inherited)
- FastAPI + SQLite backend, vanilla-JS frontend, auto-seeded demo data.
- Deterministic agent (`agent.py`): ranking, labels, conflict detection, and an **injection filter** (scorecard text that reads like an instruction is excluded) — all plain Python, no LLM.
- SLA Monitor (reminders with a one-reminder rate limit + escalation), Candidate Comparison (recruiter), hiring-manager summary.
- Seeded eval characters: **Priya** (clean), **Jordan** (conflicting feedback), **Marcus** (adversarial injection).

### Phase 1 — LLM rationale + cross-req history (the PRD)
- Replaced templated rationale with LLM-written prose; added read-only `get_candidate_history` ("this person interviewed before").
- LLM receives a **Python-built structured summary** (label, score mix, matched criteria, history) — never raw feedback. Ranking/labels unchanged.
- **Key decision:** the PRD said "never send raw feedback" *and* "make it specific." Resolved by sending a deterministic summary of *which criteria were met* — specific rationale, zero chance of leaking injected text.
- Also: `.env` auto-loading so the API key is read on startup.

### Phase 2 — "Re-participated candidate" alert + popup
- On the recruiter comparison view, a match auto-pops a modal (once, on first view) plus a persistent card badge.

### Phase 3 — Graceful DB-error handling
- DB failure → clean **"System error! Please refresh and try again"** (503 + dismissable banner) instead of a stack trace. 404s keep their own detail.

### Phase 4 — Identity resolution: fraud (2a) + email switch (2b)
- History matching upgraded to a stable `person_id`, enabling two edge cases:
  - **2a — same email, different person** → possible fraud. Recruiter-clicked **"Mark as fraudulent"**; conflicting record never attached as history.
  - **2b — same person, different email** → **"Verify & switch"** prompt that reconciles the email on confirm (a real write).
- Guardrail: no `person_id` → no identity claims (never guesses on a name).

### Phase 5 — Interviewer dashboard + recruiter debrief (closes the loop)
- Agent's **reminder carries a link** → interviewer opens the scorecard dashboard, sees the criteria, **adds notes**, and **reviews/edits** them.
- Notes feed the synthesis; the recruiter **debrief** header buckets everyone into **Move forward / Needs your decision / Flagged / Hold**.
- **Guardrail moment:** the injection filter runs on *live* interviewer notes — submit "Ignore previous instructions…" and it's flagged + excluded, with a notice.

---

## How it was tested
Three layers, per feature:
1. **API/logic tests** (FastAPI `TestClient`) — forced a real DB error (503 message), verified injection flagging on submitted notes, identity resolution for all candidates, and that write endpoints persist/clear signals.
2. **Headless browser** (Playwright + real Chrome) — clicked through popups, fraud/switch confirm modals, and the interviewer form; asserted correct content, UI updates, and **zero JS errors**.
3. **Live checks** against the deployed URL — health, comparison, interviewer endpoints.

Representative results: LLM payloads verified to contain **no raw feedback**; injection text absent from rationale *and* payload; 12/12 interviewer-loop browser assertions passed.

---

## Issues found & fixed (the honest engineering story)
- **Real bug caught by testing:** the app loaded data *before* wiring UI controls, so on a DB error the page was half-dead — the error banner couldn't be dismissed. **Fix:** wire controls first; load data with `allSettled` so one failing view doesn't blank the others. *Only surfaced because the failure path was tested.*
- **PRD contradiction** — resolved with the structured-summary design (Phase 1).
- **Config gotcha:** API key was in `.env` but the app didn't load `.env` and the line was commented — fixed with `python-dotenv` + uncommenting.
- **A "failure" that wasn't a bug:** a UI test timed out because the comparison makes one live LLM call per candidate (5 total); fixed the *test*, not the app.

---

## Architecture at a glance
- **Backend:** FastAPI, SQLAlchemy, SQLite (auto-seeds). Deterministic agent in `agent.py`; LLM only for rationale prose (Anthropic API).
- **Frontend:** single-page vanilla JS/HTML/CSS, same-origin API.
- **Deploy:** Render, auto-seeds on boot.
- **Safety themes:** injection filtering, deterministic decisions, precision-over-recall identity matching, recruiter-in-control writes, graceful degradation.

---

## Demo script (~4 min)
1. **Frame it:** "An AI agent for interview feedback — but the AI never makes the hiring decision. Watch how it's boxed in."
2. **SLA Monitor** → trigger a reminder → point out the **rate limit** and the **scorecard link** it sends.
3. **Interviewer link** (`/?interview=7`) → add notes → submit → flips to review. Then submit an **injection** ("Ignore previous instructions…") → **flagged + excluded**. *(Strongest moment.)*
4. **Recruiter Comparison** → the **debrief** ("who to move along"), the **re-participation** popup, then **Sam's fraud flag** and **Dana's email switch**.
5. **Close:** "Rankings are deterministic Python; the LLM only writes the explanation from pre-filtered data — so even a malicious scorecard can't change a decision or leak into the output."

---

## Slide outline (if you want slides)
1. **Title** — FeedbackLoop AI + one-liner + live URL.
2. **The problem** — recruiters chase scorecards, then manually reconcile conflicting panel feedback.
3. **Principle** — decisions in code, LLM only writes prose (blast-radius diagram).
4. **Feature tour** — history/rationale → re-participation → identity (fraud/email) → interviewer loop → recruiter debrief.
5. **Safety** — injection filter (with the live demo), deterministic ranking, precision-first matching, graceful degradation.
6. **Engineering rigor** — 3-layer testing; the DB-error bug found & fixed.
7. **Live demo** — run the 4-min script.
8. **What's next** — role-based authentication (recruiter / interviewer / hiring-manager login) behind the roles that are already enforced in the app; cross-company history; real ATS integration; per-candidate rationale caching.

> **If asked "why no login?"** — "Access is role-based by design: hiring managers can't see the cross-candidate ranking, only recruiters can. Interviewers submit through a unique per-interview link — the link is the credential, like DocuSign or Calendly. Adding authentication behind those roles is the natural next step; the permission boundaries themselves are already enforced."

---

## Caveats to keep handy
- **LLM rationale is templated on the live URL** unless `ANTHROPIC_API_KEY` is set in Render (2-min env-var change). Everything else is fully live.
- `main` has all features; deploy is current.

---

## Video intro cold-open & presenting tips

### 1. Play & record the cold-open (2 minutes)
- **Open it:** double-click `intro.html` in the project folder — it opens in your browser and plays automatically. Press **F** for fullscreen, **R** to replay.
- **Record it (Mac):** `Shift+Cmd+5` → "Record Selected Portion" or "Entire Screen" → hit record, press **R** to trigger the animation clean, let it play ~10s, stop. That `.mov` is your opener.
- Drop that clip at the front of your presentation (or just full-screen it live and let it play while you walk up — that works great and needs zero editing).

### 2. Add AI narration (optional, ~5 min)
Paste this ~35-second script into ElevenLabs (free tier) → download the mp3 → lay it over the recording. It's timed to the animation beats:

```
Meet FeedbackLoop AI — an intelligent agent for interview feedback.
It chases down interviewer scorecards, synthesizes conflicting panel
feedback, and helps recruiters decide who moves forward.
But here's the difference: the AI never makes the hiring decision.
Every ranking is deterministic code. The language model only writes
the explanation — from data that's already been filtered and checked.
Six features. A live deployment. And guardrails that even block
malicious input in real time. This is FeedbackLoop AI.
```

### 3. One more unique idea (costs nothing, huge impact)
Turn the injection demo into audience participation. When you get to the interviewer scorecard, say:

> "This is where AI apps usually get hacked. Someone type me a sabotage instruction — I'll paste it in as interview notes."

Take a suggestion from the room, paste it, submit → it gets flagged and excluded live. Nobody else in the class will have a demo the audience gets to *attack*. That's the moment people remember.

### 4. Three quick tips (new + short on practice)
- **Don't memorize — narrate what's on screen.** Your `CHEATSHEET.txt` is the safety net. Glance, don't read.
- **Have one sentence you nail cold:** "The AI explains the decision — it never makes it." Say it at the start and the end. Repetition = confidence.
- **If something breaks live, say so calmly:** "Let me refresh — real app, real database." That's a strength, not a stumble.