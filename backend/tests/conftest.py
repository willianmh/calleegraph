"""Shared pytest fixtures.

The app is exercised against a real Postgres + Redis (``TEST_DATABASE_URL`` /
``TEST_REDIS_URL``, defaulting to local dev instances — see README). GitHub
REST is mocked via an ``httpx.MockTransport`` injected into the
``GitHubClient``; no network calls occur.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlmodel import SQLModel

# Configure environment BEFORE importing app modules (settings are cached).
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://calleegraph:calleegraph@localhost:5432/calleegraph",
    ),
)
os.environ.setdefault("REDIS_URL", os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/1"))
os.environ.pop("GITHUB_PAT", None)

from app import crypto  # noqa: E402
from app.cache import dispose_redis, get_redis, init_redis  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import dispose_engine, get_engine, init_engine, session_scope  # noqa: E402
from app.models import Settings as SettingsRow  # noqa: E402


@pytest.fixture(autouse=True)
async def _db() -> AsyncIterator[None]:
    """Fresh schema per test (create_all/drop_all — tests don't run Alembic)."""
    get_settings.cache_clear()
    init_engine()
    init_redis()
    async with get_engine().begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield
    # A test's `client` fixture may exercise the app's own lifespan (via
    # LifespanManager), which disposes the engine/redis client on shutdown
    # before this teardown runs — re-init so drop_all/flushdb always have a
    # live connection regardless of fixture teardown order.
    init_engine()
    init_redis()
    async with get_engine().begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await get_redis().flushdb()
    await dispose_redis()
    await dispose_engine()


@pytest.fixture
async def seed_pat() -> str:
    """Seed the settings row with a known PAT + actor login (idempotent)."""
    pat = "ghp_testtoken"
    async with session_scope() as session:
        row = await session.get(SettingsRow, 1)
        if row is None:
            row = SettingsRow(id=1)
            session.add(row)
        row.github_pat_encrypted = crypto.encrypt(pat)
        row.github_actor_login = "octocat"
        await session.commit()
    return pat


def make_mock_github_client(handler):  # type: ignore[no-untyped-def]
    """Build a GitHubClient whose transport is driven by ``handler``."""
    from app.github.client import GitHubClient

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return GitHubClient("ghp_testtoken", client=http_client)
