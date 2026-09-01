"""Repository registration endpoints (backend prompt §5)."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import get_session
from app.github.client import GitHubError
from app.graph.assemble import repository_to_schema
from app.graph.service import notify_repository, publish_graph
from app.models import Repository, RepoStatus
from app.schemas import RepositoryCreate, RepositoryResponse
from app.services import make_github_client
from app.sync import schedule_sync

router = APIRouter(prefix="/api/repositories", tags=["repositories"])

_FULL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@router.get("", response_model=list[RepositoryResponse])
async def list_repositories(
    session: AsyncSession = Depends(get_session),
) -> list[RepositoryResponse]:
    repos = (await session.exec(select(Repository).order_by(col(Repository.id)))).all()
    return [repository_to_schema(r) for r in repos]


@router.post("", response_model=RepositoryResponse, status_code=201)
async def create_repository(
    body: RepositoryCreate, session: AsyncSession = Depends(get_session)
) -> RepositoryResponse:
    full_name = body.full_name.strip().strip("/")
    if not _FULL_NAME_RE.match(full_name):
        raise HTTPException(status_code=400, detail="full_name must be in the form 'owner/name'")

    existing = (
        await session.exec(select(Repository).where(Repository.full_name == full_name))
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"{full_name} is already registered")

    owner, name = full_name.split("/", 1)

    # Reachability check is synchronous so the user gets an immediate, specific
    # error for a typo or a missing PAT scope, rather than a repo row that
    # silently lands in `error` a second later.
    client = await make_github_client(session)
    try:
        meta = await client.get_repo(owner, name)
    except GitHubError as exc:
        status = 404 if exc.status == 404 else 400
        raise HTTPException(
            status_code=status, detail=f"Cannot access {full_name}: {exc}"
        ) from exc
    finally:
        await client.aclose()

    repo = Repository(
        owner=meta.get("owner", {}).get("login", owner),
        name=meta.get("name", name),
        full_name=meta.get("full_name", full_name),
        default_branch=meta.get("default_branch") or "main",
        status=RepoStatus.pending,
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    await notify_repository(repo)

    # Return immediately with status="pending"; progress arrives via SSE (§5).
    assert repo.id is not None
    schedule_sync(repo.id)
    return repository_to_schema(repo)


@router.delete("/{repository_id}", status_code=204)
async def delete_repository(
    repository_id: int, session: AsyncSession = Depends(get_session)
) -> Response:
    repo = await session.get(Repository, repository_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    await session.delete(repo)
    await session.commit()
    # Edges that pointed into this repo become `unresolved` on reassembly —
    # never `error` (contract invariant §5).
    await publish_graph(session)
    return Response(status_code=204)


@router.post("/{repository_id}/refresh", response_model=RepositoryResponse)
async def refresh_repository(
    repository_id: int,
    force: bool = Query(False),
    session: AsyncSession = Depends(get_session),
) -> RepositoryResponse:
    repo = await session.get(Repository, repository_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo.status = RepoStatus.pending
    repo.error = None
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    await notify_repository(repo)

    # The HEAD comparison happens inside the background task, which needs the
    # SHA anyway — the endpoint stays fast and the outcome (re-parsed, or
    # straight back to `done` because nothing moved) arrives over SSE.
    schedule_sync(repository_id, force=force)
    return repository_to_schema(repo)
