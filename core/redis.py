import redis.asyncio as aioredis
from loguru import logger
from core.config import settings

_redis_client: aioredis.Redis | None = None
_redis_disabled = False


class _NoopRedis:
    """Drop-in stub used when Redis is unavailable. Token revocation is skipped."""
    async def setex(self, *_, **__): pass
    async def get(self, *_, **__): return None
    async def delete(self, *_, **__): pass
    async def incr(self, *_, **__): return 0
    async def expire(self, *_, **__): pass


async def get_redis() -> aioredis.Redis | _NoopRedis:
    global _redis_client, _redis_disabled

    if _redis_disabled:
        return _NoopRedis()

    if _redis_client is None:
        try:
            client = aioredis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
            await client.ping()
            _redis_client = client
            logger.info("Redis connected")
        except Exception as e:
            _redis_disabled = True
            logger.warning(f"Redis unavailable ({e}) — running without token revocation / call registry")
            return _NoopRedis()

    return _redis_client


async def close_redis():
    global _redis_client, _redis_disabled
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
    _redis_disabled = False
