from datetime import datetime, date, timezone
from typing import Optional
from uuid import UUID, uuid4
from enum import Enum

from sqlmodel import SQLModel, Field


class PlanType(str, Enum):
    STARTER = "starter"        # 1k calls/month
    GROWTH = "growth"          # 10k calls/month
    ENTERPRISE = "enterprise"  # custom limits


class Organization(SQLModel, table=True):
    __tablename__ = "organization"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True)
    slug: str = Field(unique=True, index=True)  # used in URLs / subdomain routing

    plan: PlanType = Field(default=PlanType.STARTER)
    is_active: bool = Field(default=True)

    # Monthly quota
    calls_limit_monthly: int = Field(default=1000)
    calls_used_this_month: int = Field(default=0)
    billing_reset_date: Optional[date] = Field(default=None)

    # BYOK: clients encrypt their own provider keys here.
    # Encrypted with server ENCRYPTION_KEY via Fernet.
    # NULL means "use Vehana pool key".
    gemini_api_key_enc: Optional[str] = Field(default=None)
    openai_api_key_enc: Optional[str] = Field(default=None)
    groq_api_key_enc: Optional[str] = Field(default=None)
    sarvam_api_key_enc: Optional[str] = Field(default=None)
    elevenlabs_api_key_enc: Optional[str] = Field(default=None)

    # Billing metadata (for future Stripe integration)
    stripe_customer_id: Optional[str] = Field(default=None)
    monthly_cost_usd: float = Field(default=0.0)  # rolling cost tracked by Celery job

    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow())
