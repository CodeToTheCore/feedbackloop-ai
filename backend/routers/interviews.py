"""
routers/interviews.py
-----------------------
Interview-level deep dive (the record a click on an SLA Monitor row opens),
plus the write-capable send_reminder action -- the PRD's only write tool,
rate-limited in agent.attempt_reminder() rather than trusted to a prompt.
"""

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
    """
    iv = db.query(models.Interview).options(
        joinedload(models.Interview.scorecard),
        joinedload(models.Interview.reminders),
        joinedload(models.Interview.escalations),
    ).filter(models.Interview.id == interview_id).first()
    if not iv:
        raise HTTPException(404, "Interview not found")
    return agent.attempt_reminder(db, iv, channel=body.channel or "slack")
