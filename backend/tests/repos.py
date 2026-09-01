"""A synthetic GitHub, standing in for the three contract-verification repos.

Orchestrator prompt §2.2 asks for the backend contract to be verified against
three real repos with a test PAT: one with only top-level workflows, one whose
workflow calls a reusable workflow in *another* tracked repo, and one with a
deliberately broken input mapping. No live PAT is available to this suite, so
those repos are reproduced here as fixtures and served over
``httpx.MockTransport`` — the tests hit no network.

Four repos are modelled, not three: the cross-repo caller needs a callee, so
``acme/platform`` exists to host the reusable workflow the other two call.

    acme/website   scenario 1 — top-level workflows only, no outgoing calls
    acme/platform  the callee — hosts `reusable-deploy.yml`
    acme/services  scenario 2 — cross-repo caller (+ one malformed file)
    acme/broken    scenario 3 — deliberately broken input mapping
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def blob_sha(content: str) -> str:
    """Deterministic stand-in for a git blob SHA."""
    return hashlib.sha1(content.encode()).hexdigest()  # noqa: S324 - not security


@dataclass
class FakeRepo:
    full_name: str
    default_branch: str = "main"
    head_sha: str = "0" * 40
    # path -> file content
    files: dict[str, str] = field(default_factory=dict)
    # Extra non-workflow paths, to prove the discovery filter is doing work.
    extra_paths: list[str] = field(default_factory=list)
    # Set to make every call for this repo fail, simulating an outage.
    fail_with: int | None = None
    # Set to make only the tree listing fail: the repo is reachable (so it can
    # be registered) but discovery blows up mid-sync.
    fail_tree: bool = False

    @property
    def owner(self) -> str:
        return self.full_name.split("/")[0]

    @property
    def name(self) -> str:
        return self.full_name.split("/")[1]


def default_repos() -> dict[str, FakeRepo]:
    """The four synthetic repos, freshly built (tests mutate them)."""
    return {
        r.full_name: r
        for r in [
            FakeRepo(
                full_name="acme/website",
                head_sha="a" * 40,
                files={
                    ".github/workflows/ci.yml": fixture("top_level_ci.yml"),
                    ".github/workflows/triggers.yml": fixture("on_as_list.yml"),
                },
                extra_paths=["README.md", "src/index.ts", ".github/dependabot.yml"],
            ),
            FakeRepo(
                full_name="acme/platform",
                head_sha="b" * 40,
                files={
                    ".github/workflows/reusable-deploy.yml": fixture("reusable_deploy.yml"),
                },
            ),
            FakeRepo(
                full_name="acme/services",
                head_sha="c" * 40,
                files={
                    ".github/workflows/cross-repo.yml": fixture("cross_repo_caller.yml"),
                    # Deliberately malformed: must not stop the file above from
                    # parsing, nor fail this repo's sync (backend prompt §7).
                    ".github/workflows/broken.yml": fixture("bad_syntax.yml"),
                    ".github/workflows/ci.yml": fixture("top_level_ci.yml"),
                },
            ),
            FakeRepo(
                full_name="acme/broken",
                head_sha="d" * 40,
                files={
                    ".github/workflows/release.yml": fixture("caller_broken_inputs.yml"),
                },
            ),
        ]
    }


class FakeGitHub:
    """An ``httpx.MockTransport`` handler serving the repos above."""

    def __init__(self, repos: dict[str, FakeRepo] | None = None) -> None:
        self.repos = repos if repos is not None else default_repos()
        self.requests: list[str] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _repo_for(self, owner: str, name: str) -> FakeRepo | None:
        return self.repos.get(f"{owner}/{name}")

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(f"{request.method} {path}")

        # The PAT must never leak into a log line or a response body; the tests
        # assert on responses, and this asserts on the request side.
        assert "ghp_" not in path

        if path == "/user":
            return httpx.Response(200, json={"login": "octocat"})

        parts = [p for p in path.split("/") if p]
        if len(parts) < 3 or parts[0] != "repos":
            return httpx.Response(404, json={"message": "Not Found"})
        owner, name, rest = parts[1], parts[2], parts[3:]
        repo = self._repo_for(owner, name)
        if repo is None:
            return httpx.Response(404, json={"message": "Not Found"})
        if repo.fail_with is not None:
            return httpx.Response(repo.fail_with, json={"message": "Server Error"})

        if not rest:
            return httpx.Response(
                200,
                json={
                    "name": repo.name,
                    "full_name": repo.full_name,
                    "owner": {"login": repo.owner},
                    "default_branch": repo.default_branch,
                },
            )
        if rest[:2] == ["git", "ref"]:
            return httpx.Response(200, json={"object": {"sha": repo.head_sha}})
        if rest[:2] == ["git", "trees"]:
            if repo.fail_tree:
                return httpx.Response(500, json={"message": "Server Error"})
            return httpx.Response(200, json=self._tree(repo))
        if rest[:2] == ["git", "blobs"]:
            return self._blob(repo, rest[2])
        return httpx.Response(404, json={"message": "Not Found"})

    def _tree(self, repo: FakeRepo) -> dict[str, Any]:
        entries = [
            {"path": p, "type": "blob", "sha": blob_sha(c), "mode": "100644"}
            for p, c in sorted(repo.files.items())
        ]
        entries += [
            {"path": p, "type": "blob", "sha": blob_sha(p), "mode": "100644"}
            for p in repo.extra_paths
        ]
        entries.append({"path": ".github", "type": "tree", "sha": "t" * 40, "mode": "040000"})
        return {"sha": repo.head_sha, "truncated": False, "tree": entries}

    def _blob(self, repo: FakeRepo, sha: str) -> httpx.Response:
        for content in repo.files.values():
            if blob_sha(content) == sha:
                return httpx.Response(
                    200,
                    json={
                        "sha": sha,
                        "encoding": "base64",
                        "content": base64.b64encode(content.encode()).decode(),
                    },
                )
        return httpx.Response(404, json={"message": "Not Found"})

    def tree_calls(self) -> int:
        """How many recursive tree listings were made (§6: one per repo sync)."""
        return sum(1 for r in self.requests if "/git/trees/" in r)


def dumps(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, default=str)
