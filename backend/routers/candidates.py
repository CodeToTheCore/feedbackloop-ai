"""
routers/candidates.py
-----------------------
Deep-dive detail on a single candidate. The /full endpoint is what a click
on a candidate card opens -- it returns the raw underlying DB rows (every
interview, scorecard, reminder, escalation) so the class demo can show
"this is a real database record", not just a summary string.

The /summary endpoint is the hiring-manager-safe view: synthesized feedback
only, never the cross-candidate ranking (PRD constraint, section 3b/3c).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from .. import models, schemas, agent

router = APIRouter(prefix="/api/candidates", tags=["candidates"])


@router.get("/{candidate_id}/full")
def candidate_full_detail(candidate_id: int, db: Session = Depends(get_db)):
    """Raw DB record inspector: every column, every related row, for this candidate."""
    cand = db.query(models.Candidate).options(
        joinedload(models.Candidate.interviews).joinedload(models.Interview.scorecard),
        joinedload(models.Candidate.interviews).joinedload(models.Interview.reminders),
        joinedload(models.Candidate.interviews).joinedload(models.Interview.escalations),
    ).filter(models.Candidate.id == candidate_id).first()
    if not cand:
        raise HTTPException(404, "Candidate not found")

    return {
        "candidate": {"id": cand.id, "name": cand.name, "stage": cand.stage, "req_id": cand.req_id},
        "interviews": [
            {
                "id": iv.id,
                "interviewer_name": iv.interviewer_name,
                "interviewer_role": iv.interviewer_role,
                "panel_stage": iv.panel_stage,
                "scheduled_time": iv.scheduled_time.isoformat(),
                "feedback_due": iv.feedback_due.isoformat(),
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
            for iv in cand.interviews
        ],
        "synthesis": agent.synthesize_candidate(cand),
    }


@router.get("/{candidate_id}/history")
def candidate_history(candidate_id: int, db: Session = Depends(get_db)):
    """
    Maps to the get_candidate_history tool (PRD 3a): read-only, cross-requisition.
    Returns prior requisitions this same candidate (name + normalized email)
    appears on, with the stage reached and outcome. Empty list when there is no
    confident match -- never a name-only guess.
    """
    cand = db.query(models.Candidate).filter(models.Candidate.id == candidate_id).first()
    if not cand:
        raise HTTPException(404, "Candidate not found")
    return {"candidate_id": cand.id, "history": agent.get_candidate_history(db, cand)}


@router.get("/{candidate_id}/summary")
def candidate_summary(candidate_id: int, db: Session = Depends(get_db)):
    """Hiring-manager-safe single-candidate summary. No cross-candidate ranking data here."""
    cand = db.query(models.Candidate).options(
        joinedload(models.Candidate.interviews).joinedload(models.Interview.scorecard)
    ).filter(models.Candidate.id == candidate_id).first()
    if not cand:
        raise HTTPException(404, "Candidate not found")
    return agent.synthesize_candidate(cand)
