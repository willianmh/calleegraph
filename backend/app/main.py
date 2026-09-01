"""FastAPI application entrypoint.

Schema is migrated by Alembic — see ``alembic/`` — not by ``create_all``; run
``alembic upgrade head`` before starting the app (the Dockerfile CMD does).

The lifespan handler initializes the async DB engine and Redis client, seeds
the settings row from env (bootstrap PAT) if needed, and resets the per-repo
fetch semaphore so it binds to this process's event loop.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.cache import cache_healthy, dispose_redis, init_redis
from app.config import get_settings
from app.db import db_healthy, dispose_engine, init_engine, session_scope
from app.routers import events, graph, repositories, settings
from app.schemas import HealthResponse
from app.services import get_settings_row
from app.sync import reset_semaphore, wait_for_pending_syncs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_engine()
    init_redis()
    # asyncio.Semaphore binds to the running loop, so it must be (re)created
    # per app lifespan rather than at import time.
    reset_semaphore()
    # Ensure the singleton settings row exists (and seed the bootstrap PAT).
    async with session_scope() as session:
        await get_settings_row(session)
    try:
        yield
    finally:
        await wait_for_pending_syncs()
        await dispose_redis()
        await dispose_engine()


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(title="Calleegraph", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(settings.router)
    app.include_router(repositories.router)
    app.include_router(graph.router)
    app.include_router(events.router)

    @app.get("/api/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        db_ok, cache_ok = await db_healthy(), await cache_healthy()
        return HealthResponse(
            status="ok",
            db="connected" if db_ok else "unavailable",
            cache="connected" if cache_ok else "unavailable",
        )

    return app


app = create_app()
