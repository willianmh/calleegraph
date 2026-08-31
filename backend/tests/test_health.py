"""GET /api/health reports live db/cache connectivity (backend prompt §5)."""

from __future__ import annotations

import httpx
from asgi_lifespan import LifespanManager

from app.main import app


async def test_health_ok() -> None:
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "connected"
    assert body["cache"] == "connected"
