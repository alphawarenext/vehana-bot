from datetime import datetime, timezone
from datetime import date as date_type
from typing import Optional
from uuid import UUID, uuid4
from enum import Enum
from decimal import Decimal

from sqlmodel import SQLModel, Field


class LLMProvider(str, Enum):
    GEMINI = "gemini"
    OPENAI = "openai"
    GROQ = "groq"
    SARVAM_STT = "sarvam_stt"
    SARVAM_TTS = "sarvam_tts"
    ELEVENLABS = "elevenlabs"
    BEDROCK = "bedrock"
    OZONETEL = "ozonetel"  # per-minute call cost


class UsageEvent(SQLModel, table=True):
    """One row per LLM/STT/TTS API call. Used for cost tracking per org."""
    __tablename__ = "usage_event"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    call_log_id: Optional[UUID] = Field(default=None, foreign_key="call_log.id", index=True)
    conversation_id: Optional[UUID] = Field(default=None, foreign_key="conversation.id")

    provider: LLMProvider
    model: str

    # Tokens (for LLM providers)
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)

    # Audio (for STT/TTS providers)
    audio_seconds: float = Field(default=0.0)
    character_count: int = Field(default=0)  # for TTS providers billed per char

    # Cost in USD — calculated at event time from PRICING table
    cost_usd: float = Field(default=0.0)

    timestamp: datetime = Field(default_factory=lambda: datetime.utcnow())


class DailyCallStats(SQLModel, table=True):
    """Aggregated daily stats per org — written by a nightly Celery job."""
    __tablename__ = "daily_call_stats"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    stat_date: date_type = Field(index=True)

    total_calls: int = Field(default=0)
    connected_calls: int = Field(default=0)
    avg_duration_seconds: float = Field(default=0.0)

    # Outcome breakdown
    ptp_count: int = Field(default=0)
    payment_confirmed_count: int = Field(default=0)
    refused_count: int = Field(default=0)
    no_answer_count: int = Field(default=0)

    # Cost breakdown
    llm_cost_usd: float = Field(default=0.0)
    stt_cost_usd: float = Field(default=0.0)
    tts_cost_usd: float = Field(default=0.0)
    total_cost_usd: float = Field(default=0.0)

    # Performance
    avg_first_response_ms: float = Field(default=0.0)
