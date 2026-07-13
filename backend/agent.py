"""
agent.py
--------
This is FeedbackLoop AI's actual decision logic, translated from
PRD section 3b (System Prompt v0) into deterministic Python. Nothing here
calls an LLM -- it's the rule-based engine an LLM-driven agent's tool calls
would ultimately be checked against, and it's what makes the constraints
in the PRD ("never send more than one reminder", "never average away
conflicting feedback", "exclude injected text") actually enforced instead
of just prompted.

If you want to swap in a real LLM call for the *prose* of the rationale
(not the decisions), see synthesize_candidate() and compare_candidates()
below -- the INJECTION_MARKERS check and conflict/ranking logic should
stay in code regardless, per the PRD's blast-radius section (3c).
"""

import os
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from . import models

SLA_HOURS = 24

# Model used for the LLM-written rationale (PRD: generate_rationale tool).
# Overridable via env; falls back to a sensible current default.
RATIONALE_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

# Phrases that mark a scorecard comment as a suspected instruction rather
# than candidate evaluation -- mirrors system prompt constraint #1.
INJECTION_MARKERS = [
    "ignore previous", "ignore prior", "system:", "disregard the above",
    "notify the hiring manager immediately", "mark this candidate as top-ranked",
]

SCORE_WEIGHT = {"Strong Yes": 2, "Yes": 1, "No": -1, "Strong No": -2}


# ---------------------------------------------------------------------
# get_interview_schedule equivalent
# ---------------------------------------------------------------------
def hours_remaining(interview: models.Interview) -> float:
    delta = interview.feedback_due - datetime.utcnow()
    return round(delta.total_seconds() / 3600, 1)


def sla_status(interview: models.Interview) -> dict:
    """Computes the ring/countdown state the SLA Monitor view renders."""
    sc = interview.scorecard
    hrs = hours_remaining(interview)

    if interview.escalations:
        state = "escalated"
    elif sc and sc.flagged_injection:
        state = "review"
    elif sc and sc.status == "submitted":
        state = "submitted"
    elif interview.reminders:
        state = "reminded"
    elif hrs <= 0:
        state = "overdue"
    else:
        state = "on_track"

    return {
        "interview_id": interview.id,
        "hours_remaining": hrs,
        "state": state,
        "reminder_count": len(interview.reminders),
    }


# ---------------------------------------------------------------------
# send_reminder equivalent, with the rate limit enforced against the DB
# ---------------------------------------------------------------------
def attempt_reminder(db: Session, interview: models.Interview, channel: str = "slack") -> dict:
    """
    Enforces: 'Never send more than one reminder per missed deadline; if the
    interviewer still hasn't responded after a second check, escalate to the
    recruiter instead of sending another reminder.' (System Prompt v0)
    """
    if interview.scorecard and interview.scorecard.status == "submitted":
        return {"action": "none", "reason": "Scorecard already submitted -- nothing to remind."}

    if hours_remaining(interview) > 0:
        return {"action": "none", "reason": "Not past the 24h SLA deadline yet."}

    if interview.escalations:
        return {"action": "none", "reason": "Already escalated -- belongs to the recruiter now."}

    if interview.reminders:
        # A reminder already went out; a second miss means escalate, not remind again.
        escalation = models.Escalation(
            interview_id=interview.id,
            reason="No scorecard after one reminder and a follow-up check.",
        )
        db.add(escalation)
        db.commit()
        return {"action": "escalated", "reason": escalation.reason}

    reminder = models.Reminder(interview_id=interview.id, channel=channel, status="sent")
    db.add(reminder)
    db.commit()
    return {"action": "reminded", "channel": channel}


# ---------------------------------------------------------------------
# Scorecard text safety check (constraint #1 in system prompt v0)
# ---------------------------------------------------------------------
def check_injection(text: str) -> tuple[bool, str | None]:
    if not text:
        return False, None
    lowered = text.lower()
    for marker in INJECTION_MARKERS:
        if marker in lowered:
            return True, f"Scorecard text resembles an embedded instruction ('{marker}'), not candidate evaluation."
    return False, None


# ---------------------------------------------------------------------
# get_scorecard_status + single-candidate synthesis
# ---------------------------------------------------------------------
def synthesize_candidate(candidate: models.Candidate) -> dict:
    usable, excluded = [], []
    for iv in candidate.interviews:
        sc = iv.scorecard
        if not sc or sc.status != "submitted":
            continue
        if sc.flagged_injection or sc.excluded_from_synthesis:
            excluded.append({"interviewer": iv.interviewer_name, "reason": sc.flag_reason})
        else:
            usable.append((iv, sc))

    scores = [s.score for _, s in usable]
    conflict = len(set(scores)) > 1 and any(SCORE_WEIGHT.get(s, 0) < 0 for s in scores) and any(
        SCORE_WEIGHT.get(s, 0) > 0 for s in scores
    )

    if not usable:
        next_step = "Needs manual review -- no usable scorecards yet."
    elif conflict:
        next_step = "Panel feedback conflicts -- recruiter decision needed before advancing."
    else:
        avg = sum(SCORE_WEIGHT.get(s, 0) for s in scores) / len(scores)
        next_step = "Ready for recruiter's advance decision." if avg > 0 else "Lean toward reject, recruiter to confirm."

    return {
        "candidate_id": candidate.id,
        "candidate_name": candidate.name,
        "scores": [
            {"interviewer": iv.interviewer_name, "score": sc.score, "feedback": sc.written_feedback}
            for iv, sc in usable
        ],
        "conflict": conflict,
        "excluded": excluded,
        "next_step": next_step,
    }


# ---------------------------------------------------------------------
# get_candidate_history equivalent (PRD 3a -- NEW read-only, cross-req)
# ---------------------------------------------------------------------
def _normalize_email(email: str | None) -> str | None:
    return email.strip().lower() if email and email.strip() else None


def _pid(candidate: models.Candidate) -> str | None:
    return candidate.person_id.strip() if candidate.person_id and candidate.person_id.strip() else None


def resolve_candidate_identity(db: Session, candidate: models.Candidate) -> dict:
    """
    Resolves this candidate against every OTHER requisition and returns three
    signals. Identity is keyed on person_id (the ATS's stable per-person id);
    email is only a corroboration/conflict signal on top:

      history        -- other reqs for the SAME person (person_id match), each
                        with the stage reached + outcome. This is what a clean
                        "re-participated candidate" is built from.
      email_update   -- 2b: same person_id, but an older record has a DIFFERENT
                        email. Surfaces a verify/switch prompt so the recruiter
                        can reconcile contact info. Includes the record id to PATCH.
      email_conflict -- 2a: the SAME email is attached to a DIFFERENT person_id.
                        Email reuse across identities -> possible fraud. The
                        conflicting record is NEVER attached as history.

    No person_id -> no identity claims at all (we never guess on name alone).
    """
    pid = _pid(candidate)
    norm_email = _normalize_email(candidate.email)

    others = (
        db.query(models.Candidate)
        .filter(models.Candidate.id != candidate.id)
        .filter(models.Candidate.req_id != candidate.req_id)
        .all()
    )

    history, update_records, conflict_records = [], [], []
    for other in others:
        other_pid = _pid(other)
        other_email = _normalize_email(other.email)
        req = other.requisition

        same_person = pid and other_pid and other_pid == pid
        diff_person = pid and other_pid and other_pid != pid
        same_email = norm_email and other_email and other_email == norm_email

        if same_person:
            history.append({
                "candidate_id": other.id,
                "req_code": req.req_code if req else None,
                "title": req.title if req else None,
                "stage_reached": other.stage,
                "outcome": other.outcome or "in_progress",
                "date": req.opened_date.date().isoformat() if req and req.opened_date else None,
            })
            if other_email and other_email != norm_email:  # 2b: same person, email changed
                update_records.append({
                    "candidate_id": other.id,
                    "req_code": req.req_code if req else None,
                    "email": other.email,
                })
        elif same_email and diff_person:  # 2a: email reuse across identities
            conflict_records.append({
                "candidate_id": other.id,
                "name": other.name,
                "req_code": req.req_code if req else None,
                "person_id": other_pid,
            })

    history.sort(key=lambda h: h["date"] or "", reverse=True)

    return {
        "history": history,
        "email_update": ({"current_email": candidate.email, "records": update_records}
                         if update_records else None),
        "email_conflict": ({"conflicting_email": candidate.email, "records": conflict_records}
                           if conflict_records else None),
    }


def get_candidate_history(db: Session, candidate: models.Candidate) -> list[dict]:
    """Back-compat shim: just the same-person history list."""
    return resolve_candidate_identity(db, candidate)["history"]


# ---------------------------------------------------------------------
# get_req_criteria + get_req_candidates -> ranked comparison
# ---------------------------------------------------------------------
def _matched_criteria(synthesis: dict, criteria: list[models.Criterion]) -> list[dict]:
    """
    Deterministically derives WHICH intake criteria the (already-safe) feedback
    touched. This is the 'summary' the LLM rationale is built from -- it exports
    only intake criteria text, never raw scorecard/written_feedback content
    (PRD 3b: never pass raw written_feedback, only pre-computed summaries).
    """
    matched = []
    for crit in criteria:
        key_words = [w for w in crit.text.lower().replace(",", " ").split() if len(w) > 3][:4]
        for s in synthesis["scores"]:
            fb = (s["feedback"] or "").lower()
            if any(word in fb for word in key_words):
                matched.append({"category": crit.category, "text": crit.text})
                break
    return matched


def compare_candidates(db: Session, requisition: models.Requisition) -> list[dict]:
    """
    Ranks candidates against the criteria set in intake (never a self-generated
    rubric -- system prompt constraint). Conflicting feedback is flagged, not
    averaged away. Ranking/label/signal_score logic is unchanged from v1 and
    stays deterministic Python (PRD 2b out-of-scope) -- only the rationale prose
    is now LLM-written, and a cross-req history lookup is added per candidate.
    """
    must_haves = [c.text.lower() for c in requisition.criteria if c.category == "must_have"]

    ranked = []
    for cand in requisition.candidates:
        synthesis = synthesize_candidate(cand)
        scores = [s["score"] for s in synthesis["scores"]]

        base = sum(SCORE_WEIGHT.get(s, 0) for s in scores)

        # Boost signal when written feedback explicitly touches a must-have criterion.
        must_have_hits = 0
        for s in synthesis["scores"]:
            fb = (s["feedback"] or "").lower()
            must_have_hits += sum(1 for mh in must_haves if any(word in fb for word in mh.split()[:3]))

        signal_score = base + (0.5 * must_have_hits)

        if synthesis["conflict"]:
            label = "Conflicted"
        elif not synthesis["scores"]:
            label = "Insufficient data"
        elif signal_score >= 3:
            label = "Strong Hire"
        elif signal_score >= 0:
            label = "Lean Hire"
        else:
            label = "Lean No Hire"

        # NEW: cross-req identity resolution + structured summary -> LLM rationale.
        identity = resolve_candidate_identity(db, cand)
        history = identity["history"]
        matched_criteria = _matched_criteria(synthesis, requisition.criteria)
        payload = _build_synthesis_payload(cand.name, synthesis, label, signal_score,
                                           matched_criteria, history)
        rationale = generate_rationale(payload, synthesis, label)

        ranked.append({
            "candidate_id": cand.id,
            "candidate_name": cand.name,
            "signal_score": signal_score,
            "label": label,
            "conflict": synthesis["conflict"],
            "excluded": synthesis["excluded"],
            "num_scorecards_in": len(synthesis["scores"]),
            "history": history,
            "email_update": identity["email_update"],      # 2b: verify/switch prompt
            "email_conflict": identity["email_conflict"],   # 2a: possible fraud
            "fraud_flagged": bool(cand.fraud_flagged),
            "fraud_reason": cand.fraud_reason,
            "rationale": rationale,
        })

    # Conflicted candidates are surfaced, not hidden -- but ranked by signal strength.
    ranked.sort(key=lambda r: r["signal_score"], reverse=True)
    for i, r in enumerate(ranked, start=1):
        r["rank"] = i
    return ranked


# ---------------------------------------------------------------------
# generate_rationale equivalent (PRD 3a -- NEW, the only LLM call)
# ---------------------------------------------------------------------
def _build_synthesis_payload(name, synthesis, label, signal_score, matched_criteria, history) -> dict:
    """
    The ONLY thing sent to the LLM. Contains pre-computed labels + summaries,
    never raw written_feedback and never excluded/flagged scorecard text. The
    excluded entries are reduced to a count + generic reason so an injected
    instruction can never ride along into the prompt (PRD 2b goal #3 / Case 3).
    """
    score_distribution: dict[str, int] = {}
    for s in synthesis["scores"]:
        score_distribution[s["score"]] = score_distribution.get(s["score"], 0) + 1

    return {
        "candidate_name": name,
        "label": label,
        "signal_score": signal_score,
        "num_usable_scorecards": len(synthesis["scores"]),
        "score_distribution": score_distribution,
        "conflict": synthesis["conflict"],
        "num_excluded_scorecards": len(synthesis["excluded"]),
        "excluded_reason": ("One or more scorecards were excluded as suspected embedded "
                            "instructions, not evaluation." if synthesis["excluded"] else None),
        "criteria_supported_by_feedback": [c["text"] for c in matched_criteria],
        "prior_requisition_history": history,
    }


RATIONALE_SYSTEM_PROMPT = (
    "You write a single, concise ranking rationale for a recruiter comparing candidates. "
    "You are given a STRUCTURED synthesis object only -- never raw interview feedback. "
    "Rules:\n"
    "1. Use ONLY facts present in the structured object. Never invent scorecard details, "
    "quotes, numbers, or specifics that are not given. If a fact is not in the object, do not state it.\n"
    "2. When 'criteria_supported_by_feedback' is present, ground the rationale in those "
    "specific intake criteria so same-label candidates read differently.\n"
    "3. If 'prior_requisition_history' is empty, do NOT mention history at all. If it is "
    "present, state the prior req factually (req code, stage reached, outcome) without "
    "editorializing on why the candidate was previously rejected.\n"
    "4. If there are no usable scorecards, say the ranking is limited by insufficient data. "
    "Never reproduce or speculate about excluded/flagged scorecard content.\n"
    "5. Output 1-2 sentences of plain prose. No lists, no preamble, no quotes."
)


def generate_rationale(payload: dict, synthesis: dict, label: str) -> str:
    """
    Sends the structured payload to the Anthropic API and returns rationale prose.
    Degrades gracefully to v1's deterministic template on any failure (missing
    key, import error, timeout, API error) so a broken LLM call never blocks the
    ranking from loading (PRD 3c failure mode #3).
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return _build_rationale(payload["candidate_name"], synthesis, label)

    try:
        import json
        import anthropic

        client = anthropic.Anthropic(api_key=api_key, timeout=15.0)
        message = client.messages.create(
            model=RATIONALE_MODEL,
            max_tokens=180,
            system=RATIONALE_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": ("Write the rationale for this candidate from the structured "
                            "synthesis object below.\n\n" + json.dumps(payload, indent=2)),
            }],
        )
        text = "".join(block.text for block in message.content if block.type == "text").strip()
        return text or _build_rationale(payload["candidate_name"], synthesis, label)
    except Exception:
        # Never let the rationale generator take down the comparison view.
        return _build_rationale(payload["candidate_name"], synthesis, label)


def _build_rationale(name: str, synthesis: dict, label: str) -> str:
    """v1's deterministic template -- retained as the graceful-degradation fallback."""
    n = len(synthesis["scores"])
    if synthesis["conflict"]:
        return (f"{name}'s {n} scorecards disagree on a fundamental question, not a scoring nuance -- "
                f"flagged for recruiter review rather than averaged into a misleading single score.")
    if not synthesis["scores"]:
        return f"No usable scorecards yet for {name}; ranking will update once panel feedback is in."
    return (f"{name} rated '{label}' across {n} scorecard(s), weighed against this req's intake criteria "
            f"rather than a generic rubric.")
