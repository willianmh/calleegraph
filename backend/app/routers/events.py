"""Server-Sent Events stream (backend prompt §5 "Live updates").

One connection serves both ``repository_updated`` and ``graph_updated``; the
frontend keeps a single global subscription and upserts/replaces by id.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.events import format_sse, subscribe

router = APIRouter(prefix="/api/events", tags=["events"])

# Comment frames keep proxies (nginx, §7) from timing the connection out.
KEEPALIVE_SECONDS = 15.0


async def event_stream() -> AsyncIterator[str]:
    async with subscribe() as queue:
        # An immediate comment flushes headers so the client's EventSource
        # opens right away instead of waiting for the first real event.
        yield ": connected\n\n"
        while True:
            try:
                event, data = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield format_sse(event, data)


@router.get("/stream")
async def stream() -> StreamingResponse:
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Belt and braces for proxies that buffer by default.
            "X-Accel-Buffering": "no",
        },
    )
