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

    # DID numbers owned by this org (JSON array of E.164 strings, used for inbound routing)
    # e.g. '["918045613563", "918045613564"]'
    did_numbers: Optional[str] = Field(default="[]")

    # Ozonetel SIP trunk extension — the short numeric ID (e.g. "525836") that goes in
    # the <stream> body.  All DIDs on the same Ozonetel account share one trunk extension.
    # Defaults to "525836" which was the legacy Vehana account trunk ID.
    trunk_extension: Optional[str] = Field(default="525836")

    # Call limits
    max_concurrent_calls: int = Field(default=5)
    calls_per_minute_limit: int = Field(default=10)

    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow())
