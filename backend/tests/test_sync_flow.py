"""Background fetch/parse flow (backend prompt §6/§10)."""

from __future__ import annotations

from sqlmodel import select

from app.db import session_scope
from app.models import Job, JobCall, Repository, RepoStatus, WorkflowNode
from app.sync import sync_repository
from tests.repos import FakeGitHub


async def register(full_name: str, head_sha: str | None = None) -> int:
    """Insert a repo row directly, bypassing the API."""
    async with session_scope() as session:
        repo = Repository(
            owner=full_name.split("/")[0],
            name=full_name.split("/")[1],
            full_name=full_name,
            default_branch="main",
            status=RepoStatus.pending,
            last_synced_commit_sha=head_sha,
        )
        session.add(repo)
        await session.commit()
        await session.refresh(repo)
        assert repo.id is not None
        return repo.id


async def get_repo(repo_id: int) -> Repository:
    async with session_scope() as session:
        repo = await session.get(Repository, repo_id)
        assert repo is not None
        return repo


async def node_ids() -> list[str]:
    async with session_scope() as session:
        return list((await session.exec(select(WorkflowNode.id))).all())


async def test_sync_discovers_and_persists_workflows(fake_github: FakeGitHub) -> None:
    repo_id = await register("acme/platform")
    await sync_repository(repo_id)

    repo = await get_repo(repo_id)
    assert repo.status is RepoStatus.done
    assert repo.error is None
    assert repo.last_synced_commit_sha == "b" * 40
    assert repo.last_synced_at is not None

    async with session_scope() as session:
        nodes = (await session.exec(select(WorkflowNode))).all()
        assert [n.id for n in nodes] == [
            "acme/platform/.github/workflows/reusable-deploy.yml"
        ]
        assert nodes[0].kind.value == "reusable"
        assert nodes[0].source_commit_sha == "b" * 40
        jobs = (await session.exec(select(Job))).all()
        assert [j.id for j in jobs] == [
            "acme/platform/.github/workflows/reusable-deploy.yml#deploy"
        ]


async def test_discovery_uses_one_tree_call_and_ignores_non_workflow_paths(
    fake_github: FakeGitHub,
) -> None:
    """§6: one recursive tree call per repo, never a per-directory walk."""
    repo_id = await register("acme/website")
    await sync_repository(repo_id)

    assert fake_github.tree_calls() == 1
    assert not any("/contents/" in r for r in fake_github.requests)
    # README.md / src/index.ts / .github/dependabot.yml are in the tree but
    # must not become nodes.
    assert sorted(await node_ids()) == [
        "acme/website/.github/workflows/ci.yml",
        "acme/website/.github/workflows/triggers.yml",
    ]


async def test_malformed_file_does_not_fail_the_repo_sync(fake_github: FakeGitHub) -> None:
    """§7: skip the one bad file, keep the rest of the repo."""
    repo_id = await register("acme/services")
    await sync_repository(repo_id)

    repo = await get_repo(repo_id)
    assert repo.status is RepoStatus.done
    assert repo.error is None
    assert sorted(await node_ids()) == [
        "acme/services/.github/workflows/ci.yml",
        "acme/services/.github/workflows/cross-repo.yml",
    ]


async def test_job_calls_recorded_for_workflow_calls_only(fake_github: FakeGitHub) -> None:
    repo_id = await register("acme/services")
    await sync_repository(repo_id)

    async with session_scope() as session:
        calls = (await session.exec(select(JobCall))).all()
        refs = sorted(c.target_ref for c in calls)
    assert refs == [
        "acme/platform/.github/workflows/reusable-deploy.yml@main",
        "acme/platform/.github/workflows/reusable-deploy.yml@v1.2.3",
    ]
    # `plain-action-job` uses actions/checkout and gets no job_call row.


async def test_status_transitions_are_emitted_in_order(
    fake_github: FakeGitHub, events_sink: list
) -> None:
    repo_id = await register("acme/platform")
    await sync_repository(repo_id)

    statuses = [
        data["status"] for event, data in events_sink if event == "repository_updated"
    ]
    assert statuses == ["fetching", "parsing", "done"]
    assert any(event == "graph_updated" for event, _ in events_sink)


async def test_graph_updated_carries_the_full_graph_not_a_diff(
    fake_github: FakeGitHub, events_sink: list
) -> None:
    repo_id = await register("acme/platform")
    await sync_repository(repo_id)

    _, payload = next((e, d) for e, d in events_sink if e == "graph_updated")
    assert set(payload) == {"repositories", "nodes", "edges", "generated_at"}
    assert len(payload["nodes"]) == 1


async def test_transient_failure_keeps_previously_good_rows(fake_github: FakeGitHub) -> None:
    """§10.4: an error must not blank out an already-working part of the graph."""
    repo_id = await register("acme/platform")
    await sync_repository(repo_id)
    good_nodes = await node_ids()
    assert good_nodes

    # GitHub starts failing, and the repo is refreshed.
    fake_github.repos["acme/platform"].fail_with = 500
    await sync_repository(repo_id, force=True)

    repo = await get_repo(repo_id)
    assert repo.status is RepoStatus.error
    assert repo.error
    # The previous successful sync's data survives, untouched.
    assert await node_ids() == good_nodes
    assert repo.last_synced_commit_sha == "b" * 40


async def test_unchanged_head_short_circuits_without_reparsing(
    fake_github: FakeGitHub,
) -> None:
    repo_id = await register("acme/platform", head_sha="b" * 40)
    await sync_repository(repo_id)

    repo = await get_repo(repo_id)
    assert repo.status is RepoStatus.done
    assert fake_github.tree_calls() == 0  # nothing moved, nothing re-fetched
    assert await node_ids() == []


async def test_force_refresh_reparses_even_when_head_is_unchanged(
    fake_github: FakeGitHub,
) -> None:
    repo_id = await register("acme/platform", head_sha="b" * 40)
    await sync_repository(repo_id, force=True)

    assert fake_github.tree_calls() == 1
    assert await node_ids() == ["acme/platform/.github/workflows/reusable-deploy.yml"]


async def test_moved_head_replaces_previous_rows(fake_github: FakeGitHub) -> None:
    repo_id = await register("acme/platform")
    await sync_repository(repo_id)

    gh_repo = fake_github.repos["acme/platform"]
    gh_repo.head_sha = "e" * 40
    gh_repo.files = {".github/workflows/other.yml": gh_repo.files.pop(
        ".github/workflows/reusable-deploy.yml"
    )}
    await sync_repository(repo_id)

    assert await node_ids() == ["acme/platform/.github/workflows/other.yml"]
    assert (await get_repo(repo_id)).last_synced_commit_sha == "e" * 40


async def test_sync_of_a_deleted_repository_is_a_no_op(fake_github: FakeGitHub) -> None:
    repo_id = await register("acme/platform")
    async with session_scope() as session:
        repo = await session.get(Repository, repo_id)
        assert repo is not None
        await session.delete(repo)
        await session.commit()
    await sync_repository(repo_id)  # must not raise
