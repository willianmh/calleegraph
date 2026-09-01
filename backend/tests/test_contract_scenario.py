"""The executable statement of the shared contract.

This walks the full end-to-end demo of **orchestrator prompt §11.2** against
the synthetic repo set in ``tests/repos.py`` — the stand-in for the three
contract-verification repos of §2.2, since no live test PAT is available:

    1. `acme/website`  — only top-level workflows: nodes, no outgoing edges.
    2. `acme/services` — calls a reusable workflow in another tracked repo:
                         `unresolved` before that repo is registered, a real
                         resolved edge after. Also holds one malformed file.
    3. `acme/broken`   — a deliberately broken input mapping: an error edge
                         whose suggestions name the real declared inputs.

and asserts the contract invariants of orchestrator §5 along the way: stable
`node.id`/`edge.id` across a re-sync of the same commit, `unresolved` never
collapsed into `error`, `graph_updated` carrying the full graph, and the PAT
appearing in no response payload.

Read this file to know what the backend promises the frontend.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager

from app.main import app
from app.sync import wait_for_pending_syncs
from tests.repos import FakeGitHub

REUSABLE = "acme/platform/.github/workflows/reusable-deploy.yml"
CROSS_REPO_CALLER = "acme/services/.github/workflows/cross-repo.yml"
BROKEN_CALLER = "acme/broken/.github/workflows/release.yml"


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def register(client: httpx.AsyncClient, full_name: str) -> dict[str, Any]:
    """Register a repo and wait for its background sync to finish."""
    resp = await client.post("/api/repositories", json={"full_name": full_name})
    assert resp.status_code == 201, resp.text
    # Contract invariant: POST returns immediately as `pending` (§5).
    assert resp.json()["status"] == "pending"
    await wait_for_pending_syncs()
    return resp.json()


async def graph(client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await client.get("/api/graph")
    assert resp.status_code == 200
    return resp.json()


def edges_from(g: dict[str, Any], node_id: str) -> list[dict[str, Any]]:
    return [e for e in g["edges"] if e["source_node_id"] == node_id]


def node_ids(g: dict[str, Any]) -> list[str]:
    return [n["id"] for n in g["nodes"]]


async def test_end_to_end_contract_scenario(
    client: httpx.AsyncClient, fake_github: FakeGitHub, seed_pat: str
) -> None:
    # --- 1. A repo with only top-level workflows -------------------------
    await register(client, "acme/website")
    g = await graph(client)

    assert node_ids(g) == [
        "acme/website/.github/workflows/ci.yml",
        "acme/website/.github/workflows/triggers.yml",
    ]
    assert all(n["kind"] == "top_level" for n in g["nodes"])
    # Top-level workflows call no reusable workflows, so they emit no edges.
    assert g["edges"] == []
    assert [r["status"] for r in g["repositories"]] == ["done"]

    # --- 2a. A cross-repo caller, before its target repo is tracked ------
    await register(client, "acme/services")
    g = await graph(client)

    # The one malformed file in acme/services was skipped; every other
    # workflow in that repo — and in acme/website — still parsed (§7).
    assert CROSS_REPO_CALLER in node_ids(g)
    assert "acme/services/.github/workflows/ci.yml" in node_ids(g)
    assert "acme/services/.github/workflows/broken.yml" not in node_ids(g)
    assert "acme/website/.github/workflows/ci.yml" in node_ids(g)
    assert [r["status"] for r in g["repositories"]] == ["done", "done"]

    cross_edges = edges_from(g, CROSS_REPO_CALLER)
    assert len(cross_edges) == 2
    for edge in cross_edges:
        # acme/platform isn't registered yet — a data-completeness gap, not a
        # validation failure. `unresolved` is never collapsed into `error`,
        # even though the edge does carry an issue explaining itself.
        assert edge["status"] == "unresolved"
        assert edge["target_node_id"] is None
        # The raw `uses:` is preserved so the UI can show what it points at.
        assert edge["target_ref"].startswith("acme/platform/.github/workflows/")

        # Exactly one issue, and it names the repo to add. The frontend renders
        # this copy verbatim, so the backend has to supply it.
        assert [i["code"] for i in edge["issues"]] == ["unresolved_target"]
        issue = edge["issues"][0]
        assert issue["severity"] == "warning"
        assert issue["input_name"] is None
        assert issue["suggestion"] == "Add `acme/platform` under Repositories to resolve this call."
        # No input-wiring rules ran: there's no parsed callee to check against.
        assert not any(
            i["code"] in {"unknown_input", "missing_required_input", "type_mismatch"}
            for i in edge["issues"]
        )

    unresolved_edge_ids = {e["id"] for e in cross_edges}

    # --- 2b. Register the target repo; the same call now resolves --------
    await register(client, "acme/platform")
    g = await graph(client)
    assert REUSABLE in node_ids(g)

    cross_edges = edges_from(g, CROSS_REPO_CALLER)
    by_ref = {e["target_ref"]: e for e in cross_edges}
    resolved = by_ref[f"{REUSABLE}@main"]
    assert resolved["target_node_id"] == REUSABLE
    # The edge id did not change when it flipped from unresolved to resolved,
    # so the frontend can animate the transition rather than swapping edges.
    assert {e["id"] for e in cross_edges} == unresolved_edge_ids
    # The call is otherwise valid, but its `if:` names a job that doesn't
    # exist — a warning, not an error (§9).
    assert resolved["status"] == "warning"
    assert [i["code"] for i in resolved["issues"]] == ["unresolvable_condition"]
    assert resolved["issues"][0]["severity"] == "warning"

    # The v1 limitation, verbatim: the same workflow pinned to a tag stays
    # unresolved even though the target repo is now tracked (§8).
    pinned = by_ref[f"{REUSABLE}@v1.2.3"]
    assert pinned["status"] == "unresolved"
    assert pinned["target_node_id"] is None

    # …and its copy must not be the "add the repo" copy — acme/platform is
    # already tracked, so that advice would send the user nowhere useful.
    pinned_issue = pinned["issues"][0]
    assert pinned_issue["code"] == "unresolved_target"
    assert "v1.2.3" in pinned_issue["message"]
    assert pinned_issue["suggestion"] is not None
    assert "Add `acme/platform` under Repositories" not in pinned_issue["suggestion"]
    assert "one ref per repo" in pinned_issue["suggestion"]

    # --- 3. A repo with a deliberately broken input mapping --------------
    await register(client, "acme/broken")
    g = await graph(client)

    broken_edges = edges_from(g, BROKEN_CALLER)
    assert len(broken_edges) == 1
    broken = broken_edges[0]
    assert broken["target_node_id"] == REUSABLE
    assert broken["status"] == "error"

    issues = {i["code"]: i for i in broken["issues"]}
    assert set(issues) >= {"unknown_input", "missing_required_input", "type_mismatch"}

    # `enviroment:` is one edit away from the real input — the suggestion says
    # so by name, rather than offering a generic string.
    unknown = issues["unknown_input"]
    assert unknown["input_name"] == "enviroment"
    assert unknown["suggestion"] == "Did you mean `environment`?"
    assert unknown["severity"] == "error"

    # …and because it was misspelled, the real input is missing.
    missing = issues["missing_required_input"]
    assert missing["input_name"] == "environment"
    assert missing["suggestion"] is not None
    assert "`environment:`" in missing["suggestion"]

    # `tier: enterprise` is not one of the declared `choice` options; the
    # suggestion lists the real ones.
    mismatches = [i for i in broken["issues"] if i["code"] == "type_mismatch"]
    tier = next(i for i in mismatches if i["input_name"] == "tier")
    assert tier["suggestion"] is not None
    assert "`standard`" in tier["suggestion"] and "`premium`" in tier["suggestion"]

    # --- 4. node.id / edge.id are stable across a re-sync ----------------
    before_nodes, before_edges = node_ids(g), sorted(e["id"] for e in g["edges"])

    services_id = next(
        r["id"] for r in g["repositories"] if r["full_name"] == "acme/services"
    )
    resp = await client.post(f"/api/repositories/{services_id}/refresh?force=true")
    assert resp.status_code == 200
    await wait_for_pending_syncs()

    g = await graph(client)
    # Same commit SHA, same ids — the frontend can diff and animate rather
    # than re-rendering from scratch (contract invariant §5).
    assert node_ids(g) == before_nodes
    assert sorted(e["id"] for e in g["edges"]) == before_edges

    # --- 5. Removing a repo flips edges that pointed at it ---------------
    platform_id = next(
        r["id"] for r in g["repositories"] if r["full_name"] == "acme/platform"
    )
    assert (await client.delete(f"/api/repositories/{platform_id}")).status_code == 204

    g = await graph(client)
    # Its nodes disappear…
    assert REUSABLE not in node_ids(g)
    assert not any(n["repository_full_name"] == "acme/platform" for n in g["nodes"])
    # …and every edge that pointed at it flips to `unresolved`, never `error`.
    dangling = [e for e in g["edges"] if e["target_ref"].startswith("acme/platform/")]
    assert dangling
    for edge in dangling:
        assert edge["status"] == "unresolved"
        assert edge["target_node_id"] is None
        # Back to a single self-explaining issue, pointing at the repo to re-add.
        assert [i["code"] for i in edge["issues"]] == ["unresolved_target"]

    # The previously-broken call is now merely unresolved, not an error — and
    # its input-mismatch issues are gone, since there is no callee to check.
    broken_again = edges_from(g, BROKEN_CALLER)[0]
    assert broken_again["status"] == "unresolved"
    assert [i["code"] for i in broken_again["issues"]] == ["unresolved_target"]

    # Everything else still parses and renders.
    assert "acme/website/.github/workflows/ci.yml" in node_ids(g)
    assert CROSS_REPO_CALLER in node_ids(g)


async def test_the_pat_never_appears_in_any_response(
    client: httpx.AsyncClient, fake_github: FakeGitHub, seed_pat: str
) -> None:
    """Contract invariant §5 / DoD 4: the PAT is write-only."""
    await register(client, "acme/services")
    await register(client, "acme/platform")

    for path in ("/api/settings", "/api/repositories", "/api/graph", "/api/health"):
        resp = await client.get(path)
        assert resp.status_code == 200
        assert seed_pat not in resp.text
        assert "ghp_" not in resp.text

    settings = (await client.get("/api/settings")).json()
    assert settings["pat_set"] is True
    assert "github_pat" not in settings
    assert "github_pat_encrypted" not in settings
