"""
Usage and cost dashboard — per-org view of call volume and LLM spend.
"""
from datetime import date as date_type
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlmodel import select, func

from api.deps import CurrentOrg, DBSession
from models.usage import UsageEvent, DailyCallStats, LLMProvider

router = APIRouter(prefix="/usage", tags=["usage"])


class UsageSummary(BaseModel):
    calls_used_this_month: int
    calls_limit_monthly: int
    total_cost_usd_this_month: float


class DailyStatsOut(BaseModel):
    stat_date: date_type
    total_calls: int
    connected_calls: int
    ptp_count: int
    payment_confirmed_count: int
    total_cost_usd: float
    llm_cost_usd: float
    stt_cost_usd: float
    tts_cost_usd: float


class ProviderCostBreakdown(BaseModel):
    provider: str
    model: str
    total_cost_usd: float
    call_count: int


@router.get("/summary", response_model=UsageSummary)
async def get_usage_summary(org: CurrentOrg, session: DBSession):
    # Sum cost for current month from usage events
    result = await session.exec(
        select(func.sum(UsageEvent.cost_usd))
        .where(UsageEvent.org_id == org.id)
        .where(func.date_trunc("month", UsageEvent.timestamp) == func.date_trunc("month", func.now()))
    )
    total_cost = result.first() or 0.0

    return UsageSummary(
        calls_used_this_month=org.calls_used_this_month,
        calls_limit_monthly=org.calls_limit_monthly,
        total_cost_usd_this_month=round(total_cost, 4),
    )


@router.get("/daily", response_model=List[DailyStatsOut])
async def get_daily_stats(org: CurrentOrg, session: DBSession, days: int = 30):
    result = await session.exec(
        select(DailyCallStats)
        .where(DailyCallStats.org_id == org.id)
        .order_by(DailyCallStats.date.desc())
        .limit(days)
    )
    return result.all()


@router.get("/cost-breakdown", response_model=List[ProviderCostBreakdown])
async def get_cost_breakdown(org: CurrentOrg, session: DBSession, days: int = 30):
    """Cost per provider/model for the last N days."""
    result = await session.exec(
        select(
            UsageEvent.provider,
            UsageEvent.model,
            func.sum(UsageEvent.cost_usd).label("total_cost_usd"),
            func.count(UsageEvent.id).label("call_count"),
        )
        .where(UsageEvent.org_id == org.id)
        .where(UsageEvent.timestamp >= func.now() - func.make_interval(days=days))
        .group_by(UsageEvent.provider, UsageEvent.model)
        .order_by(func.sum(UsageEvent.cost_usd).desc())
    )
    rows = result.all()
    return [
        ProviderCostBreakdown(
            provider=r.provider,
            model=r.model,
            total_cost_usd=round(r.total_cost_usd or 0.0, 4),
            call_count=r.call_count,
        )
        for r in rows
    ]
