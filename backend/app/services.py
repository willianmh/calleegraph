"""Shared access to the singleton settings row and to a configured GitHub client.

Both the settings router and the background repo sync need these, so they live
here rather than in a router (see the 2026-08-31 19:45 WORKLOG entry, which
called for this move once a second consumer appeared).
"""

from __future__ import annotations

import logging

from sqlmodel.ext.asyncio.session import AsyncSession

from app import crypto
from app.config import get_settings as get_app_settings
from app.github.client import GitHubClient
from app.models import Settings

logger = logging.getLogger(__name__)


async def get_settings_row(session: AsyncSession) -> Settings:
    """Fetch (or lazily create) the singleton settings row, seeding it from env.

    Bootstrap PAT seeding is documented in §3: "if set and DB has none, seed
    settings with it". ``get_or_create`` semantics also cover the app's very
    first request landing before the lifespan seed has committed.
    """
    row = await session.get(Settings, 1)
    if row is None:
        cfg = get_app_settings()
        row = Settings(
            id=1,
            github_api_version=cfg.github_api_version,
            github_api_base=cfg.github_api_base,
        )
        if cfg.github_pat:
            try:
                row.github_pat_encrypted = crypto.encrypt(cfg.github_pat)
            except Exception:  # noqa: BLE001 - missing ENCRYPTION_KEY is non-fatal here
                pass
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


def stored_pat(row: Settings) -> str | None:
    """Decrypt the stored PAT, or None if unset/undecryptable.

    Never logs the token itself — only the fact that decryption failed.
    """
    if not row.github_pat_encrypted:
        return None
    try:
        return crypto.decrypt(row.github_pat_encrypted)
    except Exception:  # noqa: BLE001
        logger.warning("Stored GitHub PAT could not be decrypted (wrong ENCRYPTION_KEY?)")
        return None


async def make_github_client(session: AsyncSession) -> GitHubClient:
    """Build a GitHubClient from the stored settings.

    The PAT is optional: public repos are readable unauthenticated, just at a
    much lower rate limit. Callers must close the client (it is an async
    context manager).
    """
    row = await get_settings_row(session)
    return GitHubClient(
        stored_pat(row),
        api_base=row.github_api_base,
        api_version=row.github_api_version,
    )
