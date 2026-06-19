"""
DND (Do-Not-Disturb) check with Redis cache layer.
Cache TTL = 1hr. Miss falls back to DB lookup.
"""
from uuid import UUID
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from core.redis import get_redis
from models.dnd import DNDEntry

DND_CACHE_TTL = 3600  # 1 hour


async def is_dnd(org_id: UUID, phone: str, session: AsyncSession) -> bool:
    redis = await get_redis()
    cache_key = f"dnd:{org_id}:{phone}"

    cached = await redis.get(cache_key)
    if cached is not None:
        return cached == "1"

    result = await session.exec(
        select(DNDEntry).where(DNDEntry.org_id == org_id, DNDEntry.phone == phone)
    )
    is_blocked = result.first() is not None

    await redis.setex(cache_key, DND_CACHE_TTL, "1" if is_blocked else "0")
    return is_blocked


async def add_dnd(
    org_id: UUID,
    phone: str,
    session: AsyncSession,
    reason: str = "user_requested",
    call_log_id: Optional[UUID] = None,
):
    existing = await session.exec(
        select(DNDEntry).where(DNDEntry.org_id == org_id, DNDEntry.phone == phone)
    )
    if existing.first():
        return  # already in DND

    entry = DNDEntry(
        org_id=org_id,
        phone=phone,
        reason=reason,
        added_by_call_log_id=call_log_id,
    )
    session.add(entry)
    await session.commit()

    # Invalidate cache
    redis = await get_redis()
    await redis.delete(f"dnd:{org_id}:{phone}")
