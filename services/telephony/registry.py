"""
Active call registry backed by Redis.
Tracks all live WebSocket calls per org to enforce concurrency limits
and prevent double-dialing the same number.
"""
import json
from datetime import datetime, timezone
from uuid import UUID
from typing import Optional

from core.redis import get_redis

CALL_TTL_SECONDS = 3600  # max 1hr per call before auto-expiry


class CallRegistry:

    async def register(self, org_id: UUID, call_sid: str, phone: str, agent_id: str):
        redis = await get_redis()
        meta = json.dumps({
            "call_sid": call_sid,
            "phone": phone,
            "agent_id": agent_id,
            "started_at": datetime.utcnow().isoformat(),
        })
        async with redis.pipeline() as pipe:
            # Add to org's active call hash
            pipe.hset(f"calls:active:{org_id}", call_sid, meta)
            pipe.expire(f"calls:active:{org_id}", CALL_TTL_SECONDS)
            # Map phone → call_sid (prevent double dial)
            pipe.setex(f"calls:phone:{org_id}:{phone}", CALL_TTL_SECONDS, call_sid)
            await pipe.execute()

    async def release(self, org_id: UUID, call_sid: str, phone: str):
        redis = await get_redis()
        async with redis.pipeline() as pipe:
            pipe.hdel(f"calls:active:{org_id}", call_sid)
            pipe.delete(f"calls:phone:{org_id}:{phone}")
            await pipe.execute()

    async def get_active_count(self, org_id: UUID) -> int:
        redis = await get_redis()
        return await redis.hlen(f"calls:active:{org_id}")

    async def is_number_active(self, org_id: UUID, phone: str) -> bool:
        redis = await get_redis()
        return await redis.exists(f"calls:phone:{org_id}:{phone}") > 0

    async def can_accept_call(self, org_id: UUID, phone: str, max_concurrent: int) -> tuple[bool, str]:
        """Returns (allowed, reason). reason is non-empty if denied."""
        if await self.is_number_active(org_id, phone):
            return False, f"Number {phone} is already on an active call"
        active = await self.get_active_count(org_id)
        if active >= max_concurrent:
            return False, f"Org has reached max concurrent call limit of {max_concurrent}"
        return True, ""

    async def list_active(self, org_id: UUID) -> list[dict]:
        redis = await get_redis()
        raw = await redis.hgetall(f"calls:active:{org_id}")
        return [json.loads(v) for v in raw.values()]


call_registry = CallRegistry()
