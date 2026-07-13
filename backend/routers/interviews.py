"""
routers/interviews.py
-----------------------
Interview-level deep dive (the record a click on an SLA Monitor row opens),
plus the write-capable send_reminder action -- the PRD's only write tool,
rate-limited in agent.attempt_reminder() rather than trusted to a prompt.
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from .. import models, schemas, agent

router = APIRouter(prefix="/api/interviews", tags=["interviews"])


@router.get("/{interview_id}/full")
def interview_full_detail(interview_id: int, db: Session = Depends(get_db)):
    """Raw DB record inspector for one interview: schedule, scorecard, reminders, escalations."""
    iv = db.query(models.Interview).options(
        joinedload(models.Interview.scorecard),
        joinedload(models.Interview.reminders),
        joinedload(models.Interview.escalations),
        joinedload(models.Interview.candidate),
    ).filter(models.Interview.id == interview_id).first()
    if not iv:
        raise HTTPException(404, "Interview not found")

    return {
        "interview": {
            "id": iv.id,
            "candidate_id": iv.candidate_id,
            "candidate_name": iv.candidate.name,
            "interviewer_name": iv.interviewer_name,
            "interviewer_role": iv.interviewer_role,
            "panel_stage": iv.panel_stage,
            "scheduled_time": iv.scheduled_time.isoformat(),
            "feedback_due": iv.feedback_due.isoformat(),
        },
        "sla_status": agent.sla_status(iv),
        "scorecard": {
            "id": iv.scorecard.id,
            "status": iv.scorecard.status,
            "score": iv.scorecard.score,
            "written_feedback": iv.scorecard.written_feedback,
            "submitted_at": iv.scorecard.submitted_at.isoformat() if iv.scorecard.submitted_at else None,
            "flagged_injection": iv.scorecard.flagged_injection,
            "excluded_from_synthesis": iv.scorecard.excluded_from_synthesis,
            "flag_reason": iv.scorecard.flag_reason,
        } if iv.scorecard else None,
        "reminders": [
            {"id": r.id, "sent_at": r.sent_at.isoformat(), "channel": r.channel, "status": r.status}
            for r in iv.reminders
        ],
        "escalations": [
            {"id": e.id, "reason": e.reason, "created_at": e.created_at.isoformat()}
            for e in iv.escalations
        ],
    }


@router.post("/{interview_id}/remind")
def remind(interview_id: int, body: schemas.RemindRequest, db: Session = Depends(get_db)):
    """
    send_reminder tool. Rate limit and escalation logic live in agent.attempt_reminder,
    not here -- so this endpoint can never fire more than the PRD's blast-radius allows.
    The reminder carries a link to the interviewer's scorecard dashboard so the
    panelist can add/review their notes in one click.
    """
    iv = db.query(models.Interview).options(
        joinedload(models.Interview.scorecard),
        joinedload(models.Interview.reminders),
        joinedload(models.Interview.escalations),
    ).filter(models.Interview.id == interview_id).first()
    if not iv:
        raise HTTPException(404, "Interview not found")
    result = agent.attempt_reminder(db, iv, channel=body.channel or "slack")
    result["scorecard_url"] = f"/?interview={iv.id}"  # relative -> same-origin dashboard link
    return result


@router.get("/{interview_id}/scorecard-view")
def scorecard_view(interview_id: int, db: Session = Depends(get_db)):
    """
    Everything the interviewer's scorecard dashboard needs: who/what they're
    assessing, the intake criteria to assess against, and their current notes
    (if any). This is what the reminder link opens.
    """
    iv = db.query(models.Interview).options(
        joinedload(models.Interview.scorecard),
        joinedload(models.Interview.candidate),
    ).filter(models.Interview.id == interview_id).first()
    if not iv:
        raise HTTPException(404, "Interview not found")

    cand = iv.candidate
    criteria = (
        db.query(models.Criterion)
        .filter(models.Criterion.req_id == cand.req_id)
        .order_by(models.Criterion.priority)
        .all()
    )
    req = cand.requisition
    sc = iv.scorecard
    return {
        "interview": {
            "id": iv.id,
            "interviewer_name": iv.interviewer_name,
            "interviewer_role": iv.interviewer_role,
            "panel_stage": iv.panel_stage,
            "feedback_due": iv.feedback_due.isoformat(),
        },
        "candidate_name": cand.name,
        "req_code": req.req_code if req else None,
        "title": req.title if req else None,
        "criteria": [{"category": c.category, "text": c.text} for c in criteria],
        "scorecard": {
            "status": sc.status,
            "score": sc.score,
            "written_feedback": sc.written_feedback,
            "submitted_at": sc.submitted_at.isoformat() if sc.submitted_at else None,
            "flagged_injection": sc.flagged_injection,
            "excluded_from_synthesis": sc.excluded_from_synthesis,
            "flag_reason": sc.flag_reason,
        } if sc else None,
    }


@router.post("/{interview_id}/scorecard")
def submit_scorecard(interview_id: int, body: schemas.ScorecardSubmit, db: Session = Depends(get_db)):
    """
    The interviewer submits (or updates) their notes. Runs the same injection
    guardrail as seeded data -- feedback that looks like an embedded instruction
    is flagged and excluded from synthesis, never trusted. Submitting flows
    straight into agent.synthesize_candidate / compare_candidates, so the
    recruiter's debrief updates immediately.
    """
    if body.score not in agent.SCORE_WEIGHT:
        raise HTTPException(422, f"score must be one of {list(agent.SCORE_WEIGHT)}")

    iv = db.query(models.Interview).options(
        joinedload(models.Interview.scorecard)
    ).filter(models.Interview.id == interview_id).first()
    if not iv:
        raise HTTPException(404, "Interview not found")

    flagged, reason = agent.check_injection(body.written_feedback)
    try:
        sc = iv.scorecard
        if sc is None:
            sc = models.Scorecard(interview_id=iv.id)
            db.add(sc)
        sc.status = "submitted"
        sc.score = body.score
        sc.written_feedback = body.written_feedback
        sc.submitted_at = datetime.utcnow()
        sc.flagged_injection = flagged
        sc.excluded_from_synthesis = flagged
        sc.flag_reason = reason
        db.commit()
        db.refresh(sc)
    except Exception:
        db.rollback()
        raise

    return {
        "status": sc.status,
        "score": sc.score,
        "written_feedback": sc.written_feedback,
        "submitted_at": sc.submitted_at.isoformat() if sc.submitted_at else None,
        "flagged_injection": sc.flagged_injection,
        "excluded_from_synthesis": sc.excluded_from_synthesis,
        "flag_reason": sc.flag_reason,
    }
