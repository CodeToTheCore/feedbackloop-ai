"""
routers/requisitions.py
------------------------
Endpoints scoped to a requisition: criteria (get_req_criteria), the SLA
monitor list (get_interview_schedule across all candidates), and the
ranked comparison (get_req_criteria + get_req_candidates -> agent.compare_candidates).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from .. import models, schemas, agent

router = APIRouter(prefix="/api/requisitions", tags=["requisitions"])


@router.get("", response_model=list[schemas.RequisitionOut])
def list_requisitions(db: Session = Depends(get_db)):
    return db.query(models.Requisition).all()


@router.get("/{req_id}", response_model=schemas.RequisitionOut)
def get_requisition(req_id: int, db: Session = Depends(get_db)):
    req = db.query(models.Requisition).filter(models.Requisition.id == req_id).first()
    if not req:
        raise HTTPException(404, "Requisition not found")
    return req


@router.get("/{req_id}/criteria", response_model=list[schemas.CriterionOut])
def get_req_criteria(req_id: int, db: Session = Depends(get_db)):
    """Maps to the get_req_criteria tool in the PRD."""
    return db.query(models.Criterion).filter(models.Criterion.req_id == req_id).order_by(models.Criterion.priority).all()


@router.get("/{req_id}/candidates", response_model=list[schemas.CandidateOut])
def get_req_candidates(req_id: int, db: Session = Depends(get_db)):
    """Maps to the get_req_candidates tool in the PRD."""
    return db.query(models.Candidate).filter(models.Candidate.req_id == req_id).all()


@router.get("/{req_id}/sla-monitor")
def sla_monitor(req_id: int, db: Session = Depends(get_db)):
    """
    Every interview for every candidate in this req, with computed SLA state.
    This is what the SLA Monitor tab renders -- one row per interview.
    """
    req = db.query(models.Requisition).options(
        joinedload(models.Requisition.candidates)
        .joinedload(models.Candidate.interviews)
        .joinedload(models.Interview.scorecard)
    ).filter(models.Requisition.id == req_id).first()
    if not req:
        raise HTTPException(404, "Requisition not found")

    rows = []
    for cand in req.candidates:
        for iv in cand.interviews:
            status = agent.sla_status(iv)
            rows.append({
                "interview_id": iv.id,
                "candidate_id": cand.id,
                "candidate_name": cand.name,
                "interviewer_name": iv.interviewer_name,
                "interviewer_role": iv.interviewer_role,
                "scheduled_time": iv.scheduled_time.isoformat(),
                "feedback_due": iv.feedback_due.isoformat(),
                "scorecard_status": iv.scorecard.status if iv.scorecard else "pending",
                "flagged": bool(iv.scorecard and iv.scorecard.flagged_injection),
                **status,
            })
    return rows


@router.get("/{req_id}/comparison")
def comparison(req_id: int, db: Session = Depends(get_db)):
    """
    Maps to Synthesis & Comparison mode in the PRD system prompt: retrieves
    criteria first, then candidates, and produces the ranked, rationale-backed
    table. This endpoint is what the Candidate Comparison tab (recruiter view) renders.
    """
    req = db.query(models.Requisition).options(
        joinedload(models.Requisition.criteria),
        joinedload(models.Requisition.candidates).joinedload(models.Candidate.interviews).joinedload(models.Interview.scorecard),
    ).filter(models.Requisition.id == req_id).first()
    if not req:
        raise HTTPException(404, "Requisition not found")

    return {
        "req_code": req.req_code,
        "title": req.title,
        "criteria": [{"category": c.category, "text": c.text} for c in req.criteria],
        "ranking": agent.compare_candidates(db, req),
    }
