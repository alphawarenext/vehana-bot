from datetime import datetime, timezone
from typing import Optional, Any
from uuid import UUID, uuid4
from enum import Enum

from sqlmodel import SQLModel, Field
from sqlalchemy import Column, JSON


class CampaignStatus(str, Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class Campaign(SQLModel, table=True):
    __tablename__ = "campaign"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    agent_id: UUID = Field(foreign_key="voice_agent.id", index=True)

    name: str = Field(index=True)
    status: CampaignStatus = Field(default=CampaignStatus.DRAFT, index=True)

    # Contacts — stored as JSON array of phone strings
    contacts: Optional[Any] = Field(default=None, sa_column=Column(JSON))

    audience_count: int = Field(default=0)
    calls_made: int = Field(default=0)
    calls_connected: int = Field(default=0)
    calls_failed: int = Field(default=0)

    schedule_at: Optional[datetime] = Field(default=None, index=True)
    objective: str = Field(default="")
    notes: Optional[str] = Field(default=None)

    # Extra metadata (upload columns, raw records from CSV, etc.)
    meta_data: Optional[Any] = Field(default=None, sa_column=Column(JSON))

    # Celery task ID for the running campaign (so we can pause/cancel)
    celery_task_id: Optional[str] = Field(default=None)

    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
