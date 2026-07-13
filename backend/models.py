"""
models.py
---------
ORM tables. Each table maps to a piece of data one of the agent's tools
(from the PRD, section 3a) reads or writes:

    get_interview_schedule  -> Interview
    get_scorecard_status    -> Scorecard
    send_reminder           -> Reminder
    get_req_candidates      -> Candidate (+ its Scorecards)
    get_req_criteria        -> Criterion

Escalation is the state-store side effect described under 3a ("lightweight
Postgres/SQLite state store... tracks reminder-sent timestamps") and is what
makes the one-reminder-per-deadline rule in the system prompt enforceable
in code, not just in a prompt instruction.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey
)
from sqlalchemy.orm import relationship
from .database import Base


class Requisition(Base):
    __tablename__ = "requisitions"

    id = Column(Integer, primary_key=True, index=True)
    req_code = Column(String, unique=True, index=True)      # e.g. "REQ-4471"
    title = Column(String, nullable=False)
    status = Column(String, default="open")                 # open / filled / closed
    opened_date = Column(DateTime, default=datetime.utcnow)

    criteria = relationship("Criterion", back_populates="requisition", cascade="all, delete-orphan")
    candidates = relationship("Candidate", back_populates="requisition", cascade="all, delete-orphan")


class Criterion(Base):
    """Success criteria set by recruiter + hiring manager in the intake meeting (get_req_criteria)."""
    __tablename__ = "criteria"

    id = Column(Integer, primary_key=True, index=True)
    req_id = Column(Integer, ForeignKey("requisitions.id"), nullable=False)
    category = Column(String, nullable=False)                # "must_have" | "nice_to_have"
    text = Column(String, nullable=False)
    priority = Column(Integer, default=1)                     # lower = higher priority
    set_by = Column(String, default="")                       # who agreed on it in intake
    set_on = Column(DateTime, default=datetime.utcnow)

    requisition = relationship("Requisition", back_populates="criteria")


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, index=True)
    req_id = Column(Integer, ForeignKey("requisitions.id"), nullable=False)
    name = Column(String, nullable=False)
    stage = Column(String, default="onsite")

    # Stable per-person identity across requisitions (the ATS's global candidate
    # id). Cross-req history is matched on this, NOT on email -- email is a
    # corroboration/conflict signal layered on top (see agent.get_candidate_history):
    #   same person_id, different email  -> same person, contact info changed (2b)
    #   same email, different person_id  -> email reuse across identities (2a, fraud)
    person_id = Column(String, nullable=True, index=True)
    email = Column(String, nullable=True, index=True)

    # Terminal outcome on THIS req, once decided -- what a *later* req's history
    # lookup surfaces (e.g. "no_hire"). Null while the candidate is still in flight.
    outcome = Column(String, nullable=True)

    # Set when a recruiter marks this record fraudulent (2a: email shared with a
    # different identity). Recruiter-driven, never automatic.
    fraud_flagged = Column(Boolean, default=False)
    fraud_reason = Column(Text, nullable=True)

    requisition = relationship("Requisition", back_populates="candidates")
    interviews = relationship("Interview", back_populates="candidate", cascade="all, delete-orphan")


class Interview(Base):
    """A single scheduled panel interview (get_interview_schedule)."""
    __tablename__ = "interviews"

    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    interviewer_name = Column(String, nullable=False)
    interviewer_role = Column(String, default="")
    panel_stage = Column(String, default="onsite")
    scheduled_time = Column(DateTime, nullable=False)
    feedback_due = Column(DateTime, nullable=False)          # scheduled_time + 24h, computed at creation

    candidate = relationship("Candidate", back_populates="interviews")
    scorecard = relationship("Scorecard", back_populates="interview", uselist=False, cascade="all, delete-orphan")
    reminders = relationship("Reminder", back_populates="interview", cascade="all, delete-orphan")
    escalations = relationship("Escalation", back_populates="interview", cascade="all, delete-orphan")


class Scorecard(Base):
    """Panelist's submitted (or not-yet-submitted) feedback (get_scorecard_status)."""
    __tablename__ = "scorecards"

    id = Column(Integer, primary_key=True, index=True)
    interview_id = Column(Integer, ForeignKey("interviews.id"), unique=True, nullable=False)
    status = Column(String, default="pending")                # pending | submitted
    score = Column(String, nullable=True)                     # "Strong Yes" | "Yes" | "No" | "Strong No"
    written_feedback = Column(Text, nullable=True)
    submitted_at = Column(DateTime, nullable=True)

    # Constraint 1 in system prompt v0: scorecard text is data, never instructions.
    flagged_injection = Column(Boolean, default=False)
    excluded_from_synthesis = Column(Boolean, default=False)
    flag_reason = Column(Text, nullable=True)

    interview = relationship("Interview", back_populates="scorecard")


class Reminder(Base):
    """Record of send_reminder firing. One row per reminder actually sent."""
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, index=True)
    interview_id = Column(Integer, ForeignKey("interviews.id"), nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow)
    channel = Column(String, default="slack")                 # slack | email (SendGrid fallback)
    status = Column(String, default="sent")                   # sent | delivery_failed

    interview = relationship("Interview", back_populates="reminders")


class Escalation(Base):
    """
    Created when an interview gets a reminder and still has no scorecard.
    Per the system prompt's termination conditions, this ends the agent's
    involvement in that interview's feedback loop -- it now belongs to the recruiter.
    """
    __tablename__ = "escalations"

    id = Column(Integer, primary_key=True, index=True)
    interview_id = Column(Integer, ForeignKey("interviews.id"), nullable=False)
    reason = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    interview = relationship("Interview", back_populates="escalations")
