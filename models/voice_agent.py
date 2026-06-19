from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlmodel import SQLModel, Field


class VoiceAgent(SQLModel, table=True):
    __tablename__ = "voice_agent"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)

    name: str = Field(index=True)
    call_direction: str = Field(default="outbound")  # "inbound" | "outbound" | "both"

    # LLM config
    prompt: str = Field(default="")
    examples: str = Field(default="")
    llm_model: str = Field(default="gemini-2.5-flash")
    temperature: float = Field(default=0.7)
    max_tokens: int = Field(default=160)
    max_call_turns: int = Field(default=20)

    # STT config
    stt_model: str = Field(default="saaras:v3")

    # TTS config
    tts_model: str = Field(default="bulbul:v2")
    voice: str = Field(default="shreya")
    language: str = Field(default="hi-IN")

    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow())
