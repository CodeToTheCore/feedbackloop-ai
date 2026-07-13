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
    Cross-requisition identity resolution (get_candidate_history tool, PRD 3a).
    Keyed on person_id; returns same-person history plus two email signals:
    email_update (2b: same person, changed email) and email_conflict (2a: same
    email on a different identity -> possible fraud). Empty/null when there's no
    confident match -- never a name-only guess.
    """
    cand = db.query(models.Candidate).filter(models.Candidate.id == candidate_id).first()
    if not cand:
        raise HTTPException(404, "Candidate not found")
    identity = agent.resolve_candidate_identity(db, cand)
    return {
        "candidate_id": cand.id,
        "fraud_flagged": bool(cand.fraud_flagged),
        "fraud_reason": cand.fraud_reason,
        **identity,
    }


@router.patch("/{candidate_id}", response_model=schemas.CandidateOut)
def update_candidate_email(candidate_id: int, body: schemas.EmailUpdateRequest,
                           db: Session = Depends(get_db)):
    """
    2b write: reconcile a person's email after the recruiter verifies the switch.
    Updates just this record's email so future person_id matches no longer report
    an email mismatch. Intentionally narrow -- email only.
    """
    cand = db.query(models.Candidate).filter(models.Candidate.id == candidate_id).first()
    if not cand:
        raise HTTPException(404, "Candidate not found")
    new_email = (body.email or "").strip()
    if not new_email:
        raise HTTPException(422, "Email must not be empty")
    try:
        cand.email = new_email
        db.commit()
        db.refresh(cand)
    except Exception:
        db.rollback()
        raise
    return cand


@router.post("/{candidate_id}/flag-fraud", response_model=schemas.CandidateOut)
def flag_candidate_fraud(candidate_id: int, body: schemas.FraudFlagRequest,
                         db: Session = Depends(get_db)):
    """
    2a write: recruiter marks this record fraudulent (email shared with a
    different identity). Recruiter-driven, never automatic.
    """
    cand = db.query(models.Candidate).filter(models.Candidate.id == candidate_id).first()
    if not cand:
        raise HTTPException(404, "Candidate not found")
    try:
        cand.fraud_flagged = True
        cand.fraud_reason = (body.reason or "").strip() or "Email shared with a different candidate identity."
        db.commit()
        db.refresh(cand)
    except Exception:
        db.rollback()
        raise
    return cand


@router.get("/{candidate_id}/summary")
def candidate_summary(candidate_id: int, db: Session = Depends(get_db)):
    """Hiring-manager-safe single-candidate summary. No cross-candidate ranking data here."""
    cand = db.query(models.Candidate).options(
        joinedload(models.Candidate.interviews).joinedload(models.Interview.scorecard)
    ).filter(models.Candidate.id == candidate_id).first()
    if not cand:
        raise HTTPException(404, "Candidate not found")
    return agent.synthesize_candidate(cand)
