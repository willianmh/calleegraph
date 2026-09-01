"""In-process SSE broker (backend prompt §5 "Live updates").

One connection per client serves both event types — ``repository_updated``
and ``graph_updated`` — as the contract requires. The broker is deliberately
in-process: a single backend container is the deployment shape (orchestrator
§7), and Redis here is a cache, not a message broker (§2).

Publishing never blocks and never raises: a slow or dead subscriber drops
events rather than stalling a background sync. The frontend reconnects and
re-fetches, so a dropped event costs a refresh, not correctness.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

logger = logging.getLogger(__name__)

EventType = Literal["repository_updated", "graph_updated"]

# Bounded so a wedged client cannot grow the queue without limit. A graph
# payload is large; a handful in flight is more than enough.
_QUEUE_MAXSIZE = 32

_subscribers: set[asyncio.Queue[tuple[str, str]]] = set()


@asynccontextmanager
async def subscribe() -> AsyncIterator[asyncio.Queue[tuple[str, str]]]:
    """Register a subscriber queue for the lifetime of one SSE connection."""
    queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    _subscribers.add(queue)
    try:
        yield queue
    finally:
        _subscribers.discard(queue)


def publish(event: EventType, data: dict[str, Any]) -> None:
    """Fan an event out to every current subscriber (non-blocking)."""
    if not _subscribers:
        return
    payload = json.dumps(data, default=str)
    for queue in list(_subscribers):
        try:
            queue.put_nowait((event, payload))
        except asyncio.QueueFull:
            logger.warning("SSE subscriber queue full; dropping %s event", event)


def format_sse(event: str, data: str) -> str:
    """Render one SSE frame. Multi-line data needs one `data:` line each."""
    lines = "".join(f"data: {line}\n" for line in data.split("\n"))
    return f"event: {event}\n{lines}\n"


def subscriber_count() -> int:
    """Number of live SSE connections (used by tests)."""
    return len(_subscribers)
