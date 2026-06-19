"""
Nightly analytics aggregation and quota management tasks.
"""
import asyncio
from datetime import date, datetime, timezone, timedelta
from uuid import UUID

from celery import shared_task
from celery.utils.log import get_task_logger
from sqlmodel import select, func

from core.database import AsyncSessionLocal
from models.organization import Organization
from models.borrower import CallLog, CallOutcome
from models.usage import UsageEvent, DailyCallStats, LLMProvider

logger = get_task_logger(__name__)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@shared_task(name="workers.analytics_tasks.aggregate_daily_stats")
def aggregate_daily_stats():
    """Aggregate yesterday's call logs + usage events into DailyCallStats for each org."""
    async def _inner():
        yesterday = date.today() - timedelta(days=1)
        async with AsyncSessionLocal() as session:
            orgs_result = await session.exec(select(Organization).where(Organization.is_active == True))
            orgs = orgs_result.all()

            for org in orgs:
                await _aggregate_org_day(session, org.id, yesterday)

        logger.info(f"Daily stats aggregated for {yesterday}")

    _run(_inner())


async def _aggregate_org_day(session, org_id: UUID, day: date):
    start = datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc)
    end = datetime.combine(day, datetime.max.time()).replace(tzinfo=timezone.utc)

    # Call stats
    logs_result = await session.exec(
        select(CallLog).where(
            CallLog.org_id == org_id,
            CallLog.created_at >= start,
            CallLog.created_at <= end,
        )
    )
    logs = logs_result.all()

    total = len(logs)
    connected = sum(1 for l in logs if l.outcome not in (CallOutcome.NO_ANSWER, CallOutcome.BUSY, CallOutcome.IN_PROGRESS))
    ptp = sum(1 for l in logs if l.outcome == CallOutcome.PTP_CAPTURED)
    paid = sum(1 for l in logs if l.outcome in (CallOutcome.PAYMENT_CONFIRMED, CallOutcome.PAID_ON_CALL))
    refused = sum(1 for l in logs if l.outcome == CallOutcome.REFUSED)
    no_answer = sum(1 for l in logs if l.outcome == CallOutcome.NO_ANSWER)

    durations = [l.duration_seconds for l in logs if l.duration_seconds]
    avg_duration = sum(durations) / len(durations) if durations else 0.0

    # Cost stats from UsageEvent
    llm_providers = {LLMProvider.GEMINI, LLMProvider.OPENAI, LLMProvider.GROQ, LLMProvider.BEDROCK}
    stt_providers = {LLMProvider.SARVAM_STT}
    tts_providers = {LLMProvider.SARVAM_TTS, LLMProvider.ELEVENLABS}

    events_result = await session.exec(
        select(UsageEvent).where(
            UsageEvent.org_id == org_id,
            UsageEvent.timestamp >= start,
            UsageEvent.timestamp <= end,
        )
    )
    events = events_result.all()

    llm_cost = sum(e.cost_usd for e in events if e.provider in llm_providers)
    stt_cost = sum(e.cost_usd for e in events if e.provider in stt_providers)
    tts_cost = sum(e.cost_usd for e in events if e.provider in tts_providers)

    # Upsert DailyCallStats
    existing_result = await session.exec(
        select(DailyCallStats).where(DailyCallStats.org_id == org_id, DailyCallStats.stat_date == day)
    )
    stats = existing_result.first() or DailyCallStats(org_id=org_id, date=day)

    stats.total_calls = total
    stats.connected_calls = connected
    stats.avg_duration_seconds = avg_duration
    stats.ptp_count = ptp
    stats.payment_confirmed_count = paid
    stats.refused_count = refused
    stats.no_answer_count = no_answer
    stats.llm_cost_usd = llm_cost
    stats.stt_cost_usd = stt_cost
    stats.tts_cost_usd = tts_cost
    stats.total_cost_usd = llm_cost + stt_cost + tts_cost

    session.add(stats)
    await session.commit()


@shared_task(name="workers.analytics_tasks.reset_monthly_quotas")
def reset_monthly_quotas():
    """Reset calls_used_this_month for orgs whose billing_reset_date is today."""
    async def _inner():
        today = date.today()
        async with AsyncSessionLocal() as session:
            result = await session.exec(
                select(Organization).where(Organization.billing_reset_date == today)
            )
            for org in result.all():
                org.calls_used_this_month = 0
                org.billing_reset_date = date(today.year, today.month + 1 if today.month < 12 else 1, today.day)
                session.add(org)
            await session.commit()
        logger.info(f"Monthly quotas reset for orgs with billing date {today}")

    _run(_inner())


@shared_task(name="workers.analytics_tasks.update_org_monthly_costs")
def update_org_monthly_costs():
    """Roll up current-month usage costs into Organization.monthly_cost_usd."""
    async def _inner():
        async with AsyncSessionLocal() as session:
            result = await session.exec(
                select(
                    UsageEvent.org_id,
                    func.sum(UsageEvent.cost_usd).label("total"),
                )
                .where(func.date_trunc("month", UsageEvent.timestamp) == func.date_trunc("month", func.now()))
                .group_by(UsageEvent.org_id)
            )
            for row in result.all():
                org = await session.get(Organization, row.org_id)
                if org:
                    org.monthly_cost_usd = round(row.total or 0.0, 4)
                    session.add(org)
            await session.commit()

    _run(_inner())
