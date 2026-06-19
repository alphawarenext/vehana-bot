from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlmodel import SQLModel, Field


class DNDEntry(SQLModel, table=True):
    """Do-Not-Disturb registry per org. No calls made to numbers in this table."""
    __tablename__ = "dnd_entry"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    phone: str = Field(index=True)

    reason: Optional[str] = Field(default=None)  # "user_requested" | "regulator" | "manual"
    added_by_call_log_id: Optional[UUID] = Field(default=None, foreign_key="call_log.id")

    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
