"""Cached graph assembly + the notification fan-out (backend prompt §10/§11)."""

from __future__ import annotations

import logging
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app import events
from app.cache import (
    get_cached_graph,
    graph_cache_key,
    invalidate_graph_cache,
    set_cached_graph,
)
from app.graph.assemble import assemble_graph, repository_to_schema
from app.models import Repository

logger = logging.getLogger(__name__)


async def _cache_key(session: AsyncSession) -> str:
    repos = (await session.exec(select(Repository))).all()
    return graph_cache_key([(r.full_name, r.last_synced_commit_sha) for r in repos])


async def get_graph_payload(session: AsyncSession) -> dict[str, Any]:
    """Serve the assembled graph from cache, or build it and cache it (§11)."""
    key = await _cache_key(session)
    cached = await get_cached_graph(key)
    if cached is not None:
        return cached
    payload = (await assemble_graph(session)).model_dump(by_alias=True, mode="json")
    await set_cached_graph(key, payload)
    return payload


async def rebuild_graph_payload(session: AsyncSession) -> dict[str, Any]:
    """Invalidate, then reassemble and re-cache. Used after any state change."""
    await invalidate_graph_cache()
    key = await _cache_key(session)
    payload = (await assemble_graph(session)).model_dump(by_alias=True, mode="json")
    await set_cached_graph(key, payload)
    return payload


async def notify_repository(repo: Repository) -> None:
    """Invalidate the graph cache and emit ``repository_updated`` (§5/§10).

    Invalidation is explicit on *every* repository state change, not left to
    ``GRAPH_CACHE_TTL_SECONDS``: a cached graph embeds each repo's status, so
    a pending→fetching transition alone makes it stale even though no commit
    SHA moved and the cache key is unchanged.
    """
    await invalidate_graph_cache()
    events.publish(
        "repository_updated", repository_to_schema(repo).model_dump(by_alias=True, mode="json")
    )


async def publish_graph(session: AsyncSession) -> None:
    """Emit ``graph_updated`` carrying the **full** GraphResponse, never a diff.

    (Contract invariant, orchestrator §5 — the frontend replaces its cached
    graph wholesale.)
    """
    try:
        payload = await rebuild_graph_payload(session)
    except Exception:  # noqa: BLE001 - a failed broadcast must not fail a sync
        logger.exception("Failed to assemble graph for graph_updated broadcast")
        return
    events.publish("graph_updated", payload)
