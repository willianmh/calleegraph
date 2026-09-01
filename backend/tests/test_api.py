"""API-level tests for /api/repositories, /api/graph and /api/events/stream."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest
from asgi_lifespan import LifespanManager

from app.main import app
from app.sync import wait_for_pending_syncs
from tests.repos import FakeGitHub


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def add_repo(client: httpx.AsyncClient, full_name: str) -> dict:
    resp = await client.post("/api/repositories", json={"full_name": full_name})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_post_repository_returns_immediately_as_pending(
    client: httpx.AsyncClient, fake_github: FakeGitHub
) -> None:
    """Contract invariant §5: POST returns `pending`, progress arrives via SSE."""
    body = await add_repo(client, "acme/platform")
    assert body["status"] == "pending"
    assert body["full_name"] == "acme/platform"
    assert body["default_branch"] == "main"
    assert body["last_synced_commit_sha"] is None
    assert set(body) == {
        "id",
        "owner",
        "name",
        "full_name",
        "default_branch",
        "status",
        "error",
        "last_synced_commit_sha",
        "last_synced_at",
        "created_at",
    }
    await wait_for_pending_syncs()


async def test_repository_reaches_done_after_the_background_task(
    client: httpx.AsyncClient, fake_github: FakeGitHub
) -> None:
    created = await add_repo(client, "acme/platform")
    await wait_for_pending_syncs()

    listed = (await client.get("/api/repositories")).json()
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]
    assert listed[0]["status"] == "done"
    assert listed[0]["last_synced_commit_sha"] == "b" * 40


async def test_duplicate_registration_is_409(
    client: httpx.AsyncClient, fake_github: FakeGitHub
) -> None:
    await add_repo(client, "acme/platform")
    resp = await client.post("/api/repositories", json={"full_name": "acme/platform"})
    assert resp.status_code == 409
    assert "already registered" in resp.json()["detail"]
    await wait_for_pending_syncs()


async def test_unreachable_repository_is_rejected_before_a_row_is_created(
    client: httpx.AsyncClient, fake_github: FakeGitHub
) -> None:
    resp = await client.post("/api/repositories", json={"full_name": "nope/missing"})
    assert resp.status_code == 404
    assert "Cannot access nope/missing" in resp.json()["detail"]
    assert (await client.get("/api/repositories")).json() == []


@pytest.mark.parametrize("full_name", ["not-a-full-name", "too/many/parts", ""])
async def test_malformed_full_name_is_400(
    client: httpx.AsyncClient, fake_github: FakeGitHub, full_name: str
) -> None:
    resp = await client.post("/api/repositories", json={"full_name": full_name})
    assert resp.status_code == 400


async def test_delete_repository_cascades_and_returns_204(
    client: httpx.AsyncClient, fake_github: FakeGitHub
) -> None:
    created = await add_repo(client, "acme/platform")
    await wait_for_pending_syncs()
    assert (await client.get("/api/graph")).json()["nodes"]

    resp = await client.delete(f"/api/repositories/{created['id']}")
    assert resp.status_code == 204
    assert (await client.get("/api/repositories")).json() == []
    assert (await client.get("/api/graph")).json()["nodes"] == []


async def test_delete_unknown_repository_is_404(
    client: httpx.AsyncClient, fake_github: FakeGitHub
) -> None:
    assert (await client.delete("/api/repositories/999")).status_code == 404


async def test_refresh_returns_the_repository_and_reruns_the_sync(
    client: httpx.AsyncClient, fake_github: FakeGitHub
) -> None:
    created = await add_repo(client, "acme/platform")
    await wait_for_pending_syncs()

    resp = await client.post(f"/api/repositories/{created['id']}/refresh?force=true")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
    await wait_for_pending_syncs()

    listed = (await client.get("/api/repositories")).json()
    assert listed[0]["status"] == "done"


async def test_refresh_unknown_repository_is_404(
    client: httpx.AsyncClient, fake_github: FakeGitHub
) -> None:
    assert (await client.post("/api/repositories/999/refresh")).status_code == 404


async def test_graph_is_empty_but_well_formed_with_no_repositories(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/api/graph")).json()
    assert body["repositories"] == []
    assert body["nodes"] == []
    assert body["edges"] == []
    assert body["generated_at"]


async def test_graph_includes_unsynced_repositories_with_no_nodes(
    client: httpx.AsyncClient, fake_github: FakeGitHub
) -> None:
    """§11: a repo without a synced SHA still appears, contributing no nodes."""
    fake_github.repos["acme/platform"].fail_tree = True
    await add_repo(client, "acme/platform")
    await wait_for_pending_syncs()

    body = (await client.get("/api/graph")).json()
    assert [r["status"] for r in body["repositories"]] == ["error"]
    assert body["nodes"] == []


async def test_graph_node_shape_matches_the_contract(
    client: httpx.AsyncClient, fake_github: FakeGitHub
) -> None:
    await add_repo(client, "acme/platform")
    await wait_for_pending_syncs()

    node = (await client.get("/api/graph")).json()["nodes"][0]
    assert set(node) == {
        "id",
        "repository_full_name",
        "path",
        "name",
        "kind",
        "triggers",
        "jobs",
        "declared_inputs",
        "declared_secrets",
        "declared_outputs",
    }
    assert node["kind"] == "reusable"
    assert set(node["jobs"][0]) == {"id", "job_key", "name", "needs", "condition", "call"}
    assert set(node["declared_inputs"][0]) == {
        "name",
        "type",
        "required",
        "default",
        "description",
        "options",
    }


async def test_job_call_serializes_the_with_mapping_as_with(
    client: httpx.AsyncClient, fake_github: FakeGitHub
) -> None:
    """The contract field is `with`, not `with_mapping`."""
    await add_repo(client, "acme/services")
    await wait_for_pending_syncs()

    nodes = (await client.get("/api/graph")).json()["nodes"]
    call = next(
        j["call"] for n in nodes for j in n["jobs"] if j["call"] is not None
    )
    assert set(call) == {"target_node_id", "target_ref", "with", "secrets_mode", "secrets"}
    assert call["with"] == {"environment": "staging"}


async def test_graph_is_served_from_cache_on_the_second_call(
    client: httpx.AsyncClient, fake_github: FakeGitHub
) -> None:
    await add_repo(client, "acme/platform")
    await wait_for_pending_syncs()

    first = (await client.get("/api/graph")).json()
    second = (await client.get("/api/graph")).json()
    # A cache hit returns the identical payload, timestamp included.
    assert first["generated_at"] == second["generated_at"]


async def test_graph_cache_is_invalidated_by_a_repository_change(
    client: httpx.AsyncClient, fake_github: FakeGitHub
) -> None:
    first = await add_repo(client, "acme/platform")
    await wait_for_pending_syncs()
    before = (await client.get("/api/graph")).json()
    assert len(before["nodes"]) == 1

    await add_repo(client, "acme/website")
    await wait_for_pending_syncs()
    after = (await client.get("/api/graph")).json()
    assert len(after["nodes"]) == 3
    assert after["generated_at"] != before["generated_at"]

    await client.delete(f"/api/repositories/{first['id']}")
    assert len((await client.get("/api/graph")).json()["nodes"]) == 2


async def test_status_change_invalidates_the_cache_at_an_unchanged_commit_sha(
    client: httpx.AsyncClient, fake_github: FakeGitHub
) -> None:
    """§10/§11: invalidation is explicit, not just key-derived.

    The commit SHA doesn't move here, so the cache key is identical before and
    after — only the explicit invalidation stops a stale `done` being served.
    """
    created = await add_repo(client, "acme/platform")
    await wait_for_pending_syncs()
    before = (await client.get("/api/graph")).json()  # populates the cache
    assert [r["status"] for r in before["repositories"]] == ["done"]

    fake_github.repos["acme/platform"].fail_tree = True
    await client.post(f"/api/repositories/{created['id']}/refresh?force=true")
    await wait_for_pending_syncs()

    after = (await client.get("/api/graph")).json()
    assert [r["status"] for r in after["repositories"]] == ["error"]
    assert after["repositories"][0]["error"]
    # …and the previously-good nodes are still there (§10.4).
    assert len(after["nodes"]) == 1


async def test_sse_stream_delivers_both_event_types_on_one_connection(
    client: httpx.AsyncClient, fake_github: FakeGitHub
) -> None:
    """§5: one connection serves `repository_updated` and `graph_updated`.

    Driven against the raw ASGI app rather than through ``client``:
    ``httpx.ASGITransport`` buffers a response until it completes, and an SSE
    stream never completes, so it cannot exercise this endpoint.
    """
    frames: list[str] = []
    disconnect = asyncio.Event()
    started: dict[str, object] = {}

    async def receive() -> dict:
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.start":
            started.update(message)
        elif message["type"] == "http.response.body":
            frames.append(message["body"].decode())

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/events/stream",
        "raw_path": b"/api/events/stream",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"test")],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
    }
    stream_task = asyncio.create_task(app(scope, receive, send))  # type: ignore[arg-type]
    await asyncio.sleep(0.1)  # let the subscriber register before publishing

    assert started["status"] == 200
    headers = {k.decode(): v.decode() for k, v in started["headers"]}  # type: ignore[union-attr]
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["cache-control"] == "no-cache"

    await add_repo(client, "acme/platform")
    await wait_for_pending_syncs()
    await asyncio.sleep(0.1)

    disconnect.set()
    await asyncio.wait_for(stream_task, timeout=5)

    body = "".join(frames)
    assert body.startswith(": connected\n\n")

    events: list[tuple[str, dict]] = []
    for frame in body.split("\n\n"):
        if not frame.startswith("event: "):
            continue
        head, _, data = frame.partition("\n")
        events.append((head[len("event: "):], json.loads(data[len("data: "):])))

    kinds = [e for e, _ in events]
    # Both event types arrived over the same single connection.
    assert "repository_updated" in kinds
    assert "graph_updated" in kinds
    assert [d["status"] for e, d in events if e == "repository_updated"] == [
        "pending",
        "fetching",
        "parsing",
        "done",
    ]
    graph_event = next(d for e, d in events if e == "graph_updated")
    assert set(graph_event) == {"repositories", "nodes", "edges", "generated_at"}
    assert len(graph_event["nodes"]) == 1


async def test_sse_stream_emits_keepalive_comments(monkeypatch: pytest.MonkeyPatch) -> None:
    """Periodic `: keepalive` comments keep proxies from timing the stream out."""
    import app.routers.events as events_router

    monkeypatch.setattr(events_router, "KEEPALIVE_SECONDS", 0.01)
    stream = events_router.event_stream()
    assert await anext(stream) == ": connected\n\n"
    assert await anext(stream) == ": keepalive\n\n"
    await stream.aclose()
