"""Redis client for caching.

Only the connection + health check live here for this slice of the backend.
The per-file workflow cache and the assembled-``GraphResponse`` cache
(backend prompt §2/§11) land with the parsing/graph-assembly work.
"""

from __future__ import annotations

from redis.asyncio import Redis

from app.config import get_settings

_redis: Redis | None = None


def init_redis() -> None:
    """Create the global Redis client (idempotent)."""
    global _redis
    if _redis is not None:
        return
    settings = get_settings()
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is not set")
    _redis = Redis.from_url(settings.redis_url, decode_responses=True)


async def dispose_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
    _redis = None


def get_redis() -> Redis:
    assert _redis is not None, "init_redis() must be called first"
    return _redis


async def cache_healthy() -> bool:
    """Best-effort ``PING`` used by /api/health. Never raises."""
    if _redis is None:
        return False
    try:
        return bool(await _redis.ping())
    except Exception:  # noqa: BLE001 - health check must not raise
        return False
