from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID, uuid4
from enum import Enum

from sqlmodel import SQLModel, Field
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy import String


class TelephonyProvider(str, Enum):
    OZONETEL = "ozonetel"
    TWILIO = "twilio"


class TelephonyConfig(SQLModel, table=True):
    __tablename__ = "telephony_config"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True, unique=True)

    provider: TelephonyProvider = Field(default=TelephonyProvider.OZONETEL)

    # Credentials — all encrypted at rest with Fernet
    api_key_enc: str
    username: Optional[str] = Field(default=None)
    agent_id: Optional[str] = Field(default=None)
    agent_email: Optional[str] = Field(default=None)
    agent_password_enc: Optional[str] = Field(default=None)

    # Twilio-specific (only set when provider=twilio)
    account_sid: Optional[str] = Field(default=None)
    auth_token_enc: Optional[str] = Field(default=None)
    twilio_phone_number: Optional[str] = Field(default=None)

    # DID numbers owned by this org (JSON array stored as text)
    did_numbers: Optional[str] = Field(default="[]")  # JSON string of list[str]

    # Call limits
    max_concurrent_calls: int = Field(default=5)
    calls_per_minute_limit: int = Field(default=10)

    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow())
