"""Per-repository background fetch/parse task (backend prompt §10).

Plain asyncio tasks — no Celery, no external queue. ``FETCH_CONCURRENCY``
caps how many repos are in flight via a single semaphore.

The load-bearing rule here: **a transient failure must never blank out
previously-good data.** Rows are replaced only inside the success path's
transaction; every error path leaves the last successful sync's
``workflow_node``/``job``/``job_call`` rows exactly as they were and surfaces
the problem on ``repository.error`` instead (§10.4).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import delete
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.cache import (
    get_cached_workflow,
    set_cached_workflow,
    workflow_cache_key,
)
from app.config import get_settings
from app.db import session_scope
from app.github.client import GitHubClient, GitHubError
from app.github.parse import (
    ParsedIODef,
    ParsedJob,
    ParsedJobCall,
    ParsedWorkflow,
    WorkflowParseError,
    is_workflow_path,
    parse_workflow,
)
from app.graph.resolve import RepoRefState, resolve_target_node_id
from app.graph.service import notify_repository, publish_graph
from app.models import (
    Job,
    JobCall,
    NodeKind,
    Repository,
    RepoStatus,
    SecretsMode,
    WorkflowNode,
    utcnow,
)
from app.services import make_github_client

logger = logging.getLogger(__name__)

# Blob downloads within a single repo. Independent of FETCH_CONCURRENCY, which
# caps whole repos; this just keeps one repo from opening 200 sockets at once.
_BLOB_CONCURRENCY = 8

_semaphore: asyncio.Semaphore | None = None
# Tasks are kept referenced so the event loop cannot garbage-collect a running
# background task mid-flight (a real asyncio footgun).
_tasks: set[asyncio.Task[None]] = set()


def get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(get_settings().fetch_concurrency)
    return _semaphore


def reset_semaphore() -> None:
    """Drop the cached semaphore (tests run across separate event loops)."""
    global _semaphore
    _semaphore = None


def schedule_sync(repository_id: int, *, force: bool = False) -> asyncio.Task[None]:
    """Kick off a repo sync in the background and return immediately."""
    task = asyncio.create_task(sync_repository(repository_id, force=force))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


async def wait_for_pending_syncs() -> None:
    """Await all in-flight sync tasks (used by tests and shutdown)."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


# --- Internals ---


async def _set_status(
    session: AsyncSession,
    repo: Repository,
    status: RepoStatus,
    *,
    error: str | None = None,
) -> None:
    repo.status = status
    repo.error = error
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    await notify_repository(repo)


def _workflow_paths(tree: dict[str, Any]) -> list[tuple[str, str]]:
    """(path, blob_sha) for every workflow file in a recursive tree response."""
    entries = tree.get("tree")
    if not isinstance(entries, list):
        return []
    found: list[tuple[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") != "blob":
            continue
        path, sha = entry.get("path"), entry.get("sha")
        if isinstance(path, str) and isinstance(sha, str) and is_workflow_path(path):
            found.append((path, sha))
    return sorted(found)


def _parsed_to_cacheable(parsed: ParsedWorkflow) -> dict[str, Any]:
    return {
        "path": parsed.path,
        "name": parsed.name,
        "kind": parsed.kind,
        "triggers": parsed.triggers,
        "declared_inputs": [d.to_dict() for d in parsed.declared_inputs],
        "declared_secrets": parsed.declared_secrets,
        "declared_outputs": [d.to_dict() for d in parsed.declared_outputs],
        "jobs": [
            {
                "job_key": j.job_key,
                "name": j.name,
                "needs": j.needs,
                "condition": j.condition,
                "call": (
                    None
                    if j.call is None
                    else {
                        "target_ref": j.call.target_ref,
                        "with_mapping": j.call.with_mapping,
                        "secrets_mode": j.call.secrets_mode,
                        "secrets": j.call.secrets,
                    }
                ),
            }
            for j in parsed.jobs
        ],
    }


def _cacheable_to_parsed(raw: dict[str, Any]) -> ParsedWorkflow:
    return ParsedWorkflow(
        path=raw["path"],
        name=raw["name"],
        kind=raw["kind"],
        triggers=raw["triggers"],
        declared_inputs=[ParsedIODef(**d) for d in raw["declared_inputs"]],
        declared_secrets=raw["declared_secrets"],
        declared_outputs=[ParsedIODef(**d) for d in raw["declared_outputs"]],
        jobs=[
            ParsedJob(
                job_key=j["job_key"],
                name=j["name"],
                needs=j["needs"],
                condition=j["condition"],
                call=None if j["call"] is None else ParsedJobCall(**j["call"]),
            )
            for j in raw["jobs"]
        ],
    )


async def _fetch_and_parse_one(
    client: GitHubClient,
    *,
    owner: str,
    name: str,
    full_name: str,
    commit_sha: str,
    path: str,
    blob_sha: str,
) -> ParsedWorkflow | None:
    """Fetch + parse one workflow file. Returns None if it should be skipped.

    A malformed file is skipped with a warning and never fails the repo sync
    (§7). A *fetch* failure for one file is likewise tolerated — the rest of
    the repo is still worth graphing.
    """
    key = workflow_cache_key(full_name, commit_sha, path)
    cached = await get_cached_workflow(key)
    if cached is not None:
        try:
            return _cacheable_to_parsed(cached)
        except (KeyError, TypeError):
            pass  # stale cache shape — fall through and re-fetch

    try:
        content = await client.get_blob_text(owner, name, blob_sha)
    except GitHubError as exc:
        logger.warning("Skipping %s/%s: could not fetch blob: %s", full_name, path, exc)
        return None

    try:
        parsed = parse_workflow(path, content)
    except WorkflowParseError as exc:
        logger.warning("Skipping malformed workflow %s/%s: %s", full_name, path, exc)
        return None
    except Exception as exc:  # noqa: BLE001 - defensive: never fail a repo on one file
        logger.warning("Skipping unparseable workflow %s/%s: %s", full_name, path, exc)
        return None

    await set_cached_workflow(key, _parsed_to_cacheable(parsed))
    return parsed


async def _replace_repo_rows(
    session: AsyncSession,
    repo: Repository,
    parsed_workflows: list[ParsedWorkflow],
    commit_sha: str,
) -> None:
    """Swap in this repo's freshly parsed rows, in a single transaction (§10.2).

    Old rows are deleted and new ones inserted together, so the repo is never
    observably half-updated; if this raises, the transaction rolls back and the
    previous sync's rows survive intact.
    """
    assert repo.id is not None
    node_ids = (
        await session.exec(select(WorkflowNode.id).where(WorkflowNode.repository_id == repo.id))
    ).all()
    if node_ids:
        # job/job_call go via ON DELETE CASCADE from workflow_node.
        await session.exec(delete(WorkflowNode).where(col(WorkflowNode.id).in_(node_ids)))  # type: ignore[call-overload]
        await session.flush()

    repo_states = {
        r.full_name: RepoRefState(
            full_name=r.full_name,
            default_branch=r.default_branch,
            last_synced_commit_sha=(commit_sha if r.id == repo.id else r.last_synced_commit_sha),
        )
        for r in (await session.exec(select(Repository))).all()
    }
    all_node_ids = set(
        (await session.exec(select(WorkflowNode.id))).all()
    ) | {f"{repo.full_name}/{p.path}" for p in parsed_workflows}

    # Insert in FK order and flush between levels: no ORM relationships are
    # declared between these tables, so SQLAlchemy's unit of work can't infer
    # the dependency and would otherwise be free to insert a job before its
    # workflow_node.
    for parsed in parsed_workflows:
        node_id = f"{repo.full_name}/{parsed.path}"
        session.add(
            WorkflowNode(
                id=node_id,
                repository_id=repo.id,
                path=parsed.path,
                name=parsed.name,
                kind=NodeKind(parsed.kind),
                triggers=parsed.triggers,
                declared_inputs=[d.to_dict() for d in parsed.declared_inputs],
                declared_secrets=parsed.declared_secrets,
                declared_outputs=[d.to_dict() for d in parsed.declared_outputs],
                source_commit_sha=commit_sha,
                updated_at=utcnow(),
            )
        )
    await session.flush()

    pending_calls: list[tuple[str, ParsedJobCall]] = []
    for parsed in parsed_workflows:
        node_id = f"{repo.full_name}/{parsed.path}"
        for job in parsed.jobs:
            job_id = f"{node_id}#{job.job_key}"
            session.add(
                Job(
                    id=job_id,
                    workflow_node_id=node_id,
                    job_key=job.job_key,
                    name=job.name,
                    needs=job.needs,
                    condition=job.condition,
                )
            )
            if job.call is not None:
                pending_calls.append((job_id, job.call))
    await session.flush()

    for job_id, call in pending_calls:
        # Best-effort resolution cached on the row; §11 recomputes it at
        # assembly time, which is what keeps cross-repo edges correct as
        # other repos come and go.
        target_node_id = resolve_target_node_id(
            call.target_ref,
            source_repo_full_name=repo.full_name,
            repo_states=repo_states,
            known_node_ids=all_node_ids,
        )
        session.add(
            JobCall(
                job_id=job_id,
                target_ref=call.target_ref,
                target_node_id=target_node_id,
                with_mapping=call.with_mapping,
                secrets_mode=SecretsMode(call.secrets_mode),
                secrets=call.secrets,
            )
        )

    await session.commit()


async def sync_repository(repository_id: int, *, force: bool = False) -> None:
    """Fetch, parse and persist one repository (§10). Never raises."""
    async with get_semaphore():
        try:
            await _sync_repository_inner(repository_id, force=force)
        except Exception:  # noqa: BLE001 - a background task must not die loudly
            logger.exception("Unhandled error syncing repository %s", repository_id)


async def _sync_repository_inner(repository_id: int, *, force: bool) -> None:
    async with session_scope() as session:
        repo = await session.get(Repository, repository_id)
        if repo is None:
            logger.info("Repository %s vanished before sync started", repository_id)
            return

        client = await make_github_client(session)
        try:
            await _do_sync(session, repo, client, force=force)
        except GitHubError as exc:
            await _fail(session, repo, str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Sync failed for %s", repo.full_name)
            await _fail(session, repo, f"sync failed: {exc}")
        finally:
            await client.aclose()


async def _fail(session: AsyncSession, repo: Repository, message: str) -> None:
    """Error path: surface the message, keep the last good rows (§10.4)."""
    await session.rollback()
    await _set_status(session, repo, RepoStatus.error, error=message)
    # The repositories list changed, so the graph did too — but every node from
    # the previous successful sync is still there.
    await publish_graph(session)


async def _do_sync(
    session: AsyncSession, repo: Repository, client: GitHubClient, *, force: bool
) -> None:
    await _set_status(session, repo, RepoStatus.fetching)

    meta = await client.get_repo(repo.owner, repo.name)
    default_branch = meta.get("default_branch") or repo.default_branch
    if default_branch != repo.default_branch:
        repo.default_branch = default_branch

    head_sha = await client.get_branch_head_sha(repo.owner, repo.name, default_branch)

    if not force and head_sha == repo.last_synced_commit_sha:
        # Nothing moved — a refresh is a no-op beyond the timestamp (§5 refresh).
        repo.last_synced_at = utcnow()
        await _set_status(session, repo, RepoStatus.done)
        await publish_graph(session)
        return

    tree = await client.get_tree(repo.owner, repo.name, head_sha)
    if tree.get("truncated"):
        logger.warning(
            "Tree for %s@%s is truncated; some workflows may be missing",
            repo.full_name,
            head_sha,
        )
    workflow_files = _workflow_paths(tree)

    await _set_status(session, repo, RepoStatus.parsing)

    blob_sem = asyncio.Semaphore(_BLOB_CONCURRENCY)

    async def one(path: str, blob_sha: str) -> ParsedWorkflow | None:
        async with blob_sem:
            return await _fetch_and_parse_one(
                client,
                owner=repo.owner,
                name=repo.name,
                full_name=repo.full_name,
                commit_sha=head_sha,
                path=path,
                blob_sha=blob_sha,
            )

    results = await asyncio.gather(*(one(p, s) for p, s in workflow_files))
    parsed_workflows = [r for r in results if r is not None]

    await _replace_repo_rows(session, repo, parsed_workflows, head_sha)

    repo.last_synced_commit_sha = head_sha
    repo.last_synced_at = utcnow()
    await _set_status(session, repo, RepoStatus.done)
    await publish_graph(session)
