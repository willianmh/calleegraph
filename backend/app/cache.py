"""Redis client and the two caches described in backend prompt §2.

(a) Parsed per-file workflow data, keyed by ``(full_name, commit_sha, path)``.
(b) The fully-assembled ``GraphResponse``, keyed by a hash of every tracked
    repo's current commit SHA.

``GRAPH_CACHE_TTL_SECONDS`` is a safety net only — the primary invalidation
path is explicit, on any repository state change (§10). Redis is a cache here,
never a source of truth and never a queue: every entry is reconstructible from
Postgres, so a cold or unavailable Redis degrades latency, not correctness.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from redis.asyncio import Redis

from app.config import get_settings

logger = logging.getLogger(__name__)

GRAPH_KEY_PREFIX = "calleegraph:graph:"
WORKFLOW_KEY_PREFIX = "calleegraph:workflow:"

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


# --- Assembled-graph cache (§11) ---


def graph_cache_key(repo_shas: list[tuple[str, str | None]]) -> str:
    """Key for the assembled graph: a hash of all tracked repos' commit SHAs."""
    digest = hashlib.sha256()
    for full_name, sha in sorted(repo_shas):
        digest.update(f"{full_name}@{sha or ''}\n".encode())
    return f"{GRAPH_KEY_PREFIX}{digest.hexdigest()}"


async def get_cached_graph(key: str) -> dict[str, Any] | None:
    """Read a cached graph. A cache miss and a cache outage look the same."""
    try:
        raw = await get_redis().get(key)
    except Exception:  # noqa: BLE001 - cache outages must not break the API
        logger.warning("Redis unavailable reading graph cache; assembling from Postgres")
        return None
    if raw is None:
        return None
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


async def set_cached_graph(key: str, payload: dict[str, Any]) -> None:
    try:
        await get_redis().set(key, json.dumps(payload), ex=get_settings().graph_cache_ttl_seconds)
    except Exception:  # noqa: BLE001
        logger.warning("Redis unavailable writing graph cache; continuing uncached")


async def invalidate_graph_cache() -> None:
    """Drop every assembled-graph entry.

    Called on *any* repository state change (§10) — add, delete, status
    transition, or completed sync — rather than relying on the TTL.
    """
    try:
        redis = get_redis()
        keys = [k async for k in redis.scan_iter(match=f"{GRAPH_KEY_PREFIX}*")]
        if keys:
            await redis.delete(*keys)
    except Exception:  # noqa: BLE001
        logger.warning("Redis unavailable invalidating graph cache")


# --- Parsed-workflow cache (§2a) ---


def workflow_cache_key(full_name: str, commit_sha: str, path: str) -> str:
    return f"{WORKFLOW_KEY_PREFIX}{full_name}:{commit_sha}:{path}"


async def get_cached_workflow(key: str) -> dict[str, Any] | None:
    try:
        raw = await get_redis().get(key)
    except Exception:  # noqa: BLE001
        return None
    if raw is None:
        return None
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


async def set_cached_workflow(key: str, payload: dict[str, Any]) -> None:
    try:
        # A parsed file at a fixed commit is immutable, so this can live far
        # longer than the graph cache; a day is plenty for a refresh loop.
        await get_redis().set(key, json.dumps(payload), ex=86400)
    except Exception:  # noqa: BLE001
        pass
