"""Async Postgres engine, session factory, and startup helpers.

Uses the SQLAlchemy async engine over ``asyncpg``. Unlike a throwaway
single-file store, schema changes go through Alembic (``alembic/``) — this
module does not ``create_all`` in place of migrations (backend prompt §2/§4).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

# Importing models registers the tables on SQLModel.metadata (used by Alembic
# autogenerate and by tests that need the schema).
from app import models  # noqa: F401
from app.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine() -> None:
    """Create the global async engine and session factory (idempotent)."""
    global _engine, _session_factory
    if _engine is not None:
        return

    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set")

    _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def dispose_engine() -> None:
    """Dispose the engine (used on shutdown / between tests)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def get_engine() -> AsyncEngine:
    assert _engine is not None, "init_engine() must be called first"
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    assert _session_factory is not None, "init_engine() must be called first"
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Async context manager yielding a session, committing on success."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def db_healthy() -> bool:
    """Best-effort ``SELECT 1`` used by /api/health. Never raises."""
    if _engine is None:
        return False
    try:
        from sqlalchemy import text

        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - health check must not raise
        return False
