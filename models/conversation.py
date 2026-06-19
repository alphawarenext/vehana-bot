from datetime import datetime, timezone
from typing import Optional, Any
from uuid import UUID, uuid4

from sqlmodel import SQLModel, Field
from sqlalchemy import Column, JSON


class Conversation(SQLModel, table=True):
    __tablename__ = "conversation"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)

    agent_id: Optional[UUID] = Field(default=None, foreign_key="voice_agent.id", index=True)
    borrower_id: Optional[UUID] = Field(default=None, foreign_key="borrower.id", index=True)
    campaign_id: Optional[UUID] = Field(default=None, foreign_key="campaign.id", index=True)
    call_log_id: Optional[UUID] = Field(default=None, foreign_key="call_log.id")

    phone_number: Optional[str] = Field(default=None, index=True)
    call_direction: str = Field(default="outbound")
    status: str = Field(default="active")  # active | completed | failed

    summary: Optional[str] = Field(default=None)
    meta_data: Optional[Any] = Field(default=None, sa_column=Column(JSON))

    started_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    ended_at: Optional[datetime] = Field(default=None)


class Message(SQLModel, table=True):
    __tablename__ = "message"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    conversation_id: UUID = Field(foreign_key="conversation.id", index=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)

    sender: str = Field(index=True)  # "agent" | "user"
    text: str
    sequence_no: int = Field(default=0)

    # STT metadata
    confidence: Optional[float] = Field(default=None)
    speech_start_time: Optional[float] = Field(default=None)
    speech_end_time: Optional[float] = Field(default=None)

    timestamp: datetime = Field(default_factory=lambda: datetime.utcnow())
    meta_data: Optional[Any] = Field(default=None, sa_column=Column(JSON))
