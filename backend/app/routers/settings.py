"""Settings endpoints (backend prompt §5). The PAT is write-only: never
returned, only ``pat_set``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app import crypto
from app.config import get_settings as get_app_settings
from app.db import get_session
from app.github.client import GitHubClient, GitHubError
from app.models import Settings, utcnow
from app.schemas import SettingsResponse, SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


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


def _to_response(row: Settings) -> SettingsResponse:
    return SettingsResponse(
        pat_set=bool(row.github_pat_encrypted),
        github_actor_login=row.github_actor_login,
        github_api_version=row.github_api_version,
        github_api_base=row.github_api_base,
    )


@router.get("", response_model=SettingsResponse)
async def get_settings(session: AsyncSession = Depends(get_session)) -> SettingsResponse:
    row = await get_settings_row(session)
    return _to_response(row)


@router.put("", response_model=SettingsResponse)
async def update_settings(
    body: SettingsUpdate, session: AsyncSession = Depends(get_session)
) -> SettingsResponse:
    row = await get_settings_row(session)
    cfg = get_app_settings()

    if body.github_api_version is not None:
        row.github_api_version = body.github_api_version
    if body.github_api_base is not None:
        row.github_api_base = body.github_api_base

    if body.github_pat is not None and body.github_pat != "":
        api_base = body.github_api_base or row.github_api_base or cfg.github_api_base
        api_version = body.github_api_version or row.github_api_version or cfg.github_api_version
        async with GitHubClient(
            body.github_pat, api_base=api_base, api_version=api_version
        ) as client:
            try:
                user = await client.get_user()
            except GitHubError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid GitHub PAT: {exc}") from exc
        try:
            row.github_pat_encrypted = crypto.encrypt(body.github_pat)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=400,
                detail=f"Cannot store PAT — encryption unavailable: {exc}",
            ) from exc
        row.github_actor_login = user.get("login")

    row.updated_at = utcnow()
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _to_response(row)
