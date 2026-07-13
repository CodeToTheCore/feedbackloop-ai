"""
schemas.py
----------
Pydantic response models. These define exactly what the API returns to the
frontend (and what shows up in the auto-generated docs at /docs).
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


class CriterionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category: str
    text: str
    priority: int
    set_by: str
    set_on: datetime


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sent_at: datetime
    channel: str
    status: str


class EscalationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    reason: str
    created_at: datetime


class ScorecardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    score: Optional[str] = None
    written_feedback: Optional[str] = None
    submitted_at: Optional[datetime] = None
    flagged_injection: bool
    excluded_from_synthesis: bool
    flag_reason: Optional[str] = None


class InterviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    candidate_id: int
    interviewer_name: str
    interviewer_role: str
    panel_stage: str
    scheduled_time: datetime
    feedback_due: datetime
    scorecard: Optional[ScorecardOut] = None
    reminders: List[ReminderOut] = []
    escalations: List[EscalationOut] = []


class CandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    req_id: int
    name: str
    stage: str
    email: Optional[str] = None
    person_id: Optional[str] = None
    fraud_flagged: bool = False
    fraud_reason: Optional[str] = None


class RequisitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    req_code: str
    title: str
    status: str
    opened_date: datetime


class RemindRequest(BaseModel):
    """Body for POST /api/interviews/{id}/remind — kept minimal on purpose."""
    channel: Optional[str] = "slack"


class ScorecardSubmit(BaseModel):
    """Body for POST /api/interviews/{id}/scorecard — the interviewer's notes."""
    score: str
    written_feedback: str = ""


class EmailUpdateRequest(BaseModel):
    """Body for PATCH /api/candidates/{id} — reconcile a person's email (2b switch)."""
    email: str


class FraudFlagRequest(BaseModel):
    """Body for POST /api/candidates/{id}/flag-fraud (2a). Reason is optional."""
    reason: Optional[str] = None
