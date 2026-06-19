from datetime import datetime, date, timezone
from typing import Optional
from uuid import UUID, uuid4
from enum import Enum

from sqlmodel import SQLModel, Field


class CallOutcome(str, Enum):
    PAYMENT_CONFIRMED = "payment_confirmed"
    ALREADY_PAID = "already_paid"
    PAID_ON_CALL = "paid_on_call"
    PTP_CAPTURED = "ptp_captured"
    PARTIAL_PAYMENT_AGREED = "partial_payment_agreed"
    CALLBACK_REQUESTED = "callback_requested"
    CANT_PAY = "cant_pay"
    DISPUTE_RAISED = "dispute_raised"
    REFUSED = "refused"
    NO_ANSWER = "no_answer"
    WRONG_NUMBER = "wrong_number"
    DND_REQUESTED = "dnd_requested"
    BUSY = "busy"
    VOICEMAIL = "voicemail"
    IN_PROGRESS = "in_progress"


class Borrower(SQLModel, table=True):
    __tablename__ = "borrower"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)

    name: str
    phone: str = Field(index=True)

    # Loan details
    loan_account_last4: str = Field(default="")
    emi_amount: float = Field(default=0.0)
    emi_due_date: Optional[date] = Field(default=None)
    overdue_amount: float = Field(default=0.0)
    days_past_due: int = Field(default=0)
    bucket: str = Field(default="pre_due")  # pre_due / bucket_0 / bucket_1 / etc.
    lender_name: str = Field(default="")

    # Payment info
    auto_debit_enabled: bool = Field(default=True)
    upi_id: Optional[str] = Field(default=None)
    payment_link: Optional[str] = Field(default=None)

    # Call history
    last_call_date: Optional[date] = Field(default=None)
    last_call_outcome: Optional[str] = Field(default=None)
    total_calls_this_cycle: int = Field(default=0)

    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow())


class CallLog(SQLModel, table=True):
    __tablename__ = "call_log"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    borrower_id: UUID = Field(foreign_key="borrower.id", index=True)

    call_sid: str = Field(unique=True, index=True)
    campaign_id: Optional[UUID] = Field(default=None, foreign_key="campaign.id", index=True)

    outcome: CallOutcome = Field(default=CallOutcome.IN_PROGRESS)
    duration_seconds: Optional[int] = Field(default=None)

    # Identity & payment
    identity_verified: bool = Field(default=False)
    ptp_date: Optional[date] = Field(default=None)
    ptp_amount: Optional[float] = Field(default=None)
    utr_reference: Optional[str] = Field(default=None)

    # Content
    transcript: Optional[str] = Field(default=None)
    recording_url: Optional[str] = Field(default=None)
    summary: Optional[str] = Field(default=None)

    # Cost tracking — filled in at end of call
    total_cost_usd: Optional[float] = Field(default=None)

    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    ended_at: Optional[datetime] = Field(default=None)
