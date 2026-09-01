"""Cross-repo / cross-ref resolution and its documented v1 limitation (§8)."""

from __future__ import annotations

import pytest

from app.graph.resolve import (
    RepoRefState,
    parse_uses,
    ref_is_current,
    resolve_call,
    resolve_target_node_id,
)

PLATFORM = RepoRefState(
    full_name="acme/platform", default_branch="main", last_synced_commit_sha="b" * 40
)
NODE_ID = "acme/platform/.github/workflows/reusable-deploy.yml"
KNOWN = {NODE_ID, "acme/services/.github/workflows/cross-repo.yml"}
STATES = {
    "acme/platform": PLATFORM,
    "acme/services": RepoRefState(
        full_name="acme/services", default_branch="main", last_synced_commit_sha="c" * 40
    ),
}


def test_parse_uses_same_repo() -> None:
    parsed = parse_uses("./.github/workflows/x.yml", source_repo_full_name="acme/services")
    assert parsed is not None
    assert parsed.repo_full_name == "acme/services"
    assert parsed.path == ".github/workflows/x.yml"
    assert parsed.ref is None


def test_parse_uses_cross_repo() -> None:
    parsed = parse_uses(
        "acme/platform/.github/workflows/reusable-deploy.yml@main",
        source_repo_full_name="acme/services",
    )
    assert parsed is not None
    assert parsed.repo_full_name == "acme/platform"
    assert parsed.path == ".github/workflows/reusable-deploy.yml"
    assert parsed.ref == "main"


def test_parse_uses_rejects_non_workflow_shape() -> None:
    assert parse_uses("", source_repo_full_name="acme/services") is None
    assert parse_uses("actions/checkout@v4", source_repo_full_name="acme/services") is None


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        (None, True),  # implicit — the caller's own commit
        ("main", True),  # the default branch
        ("refs/heads/main", True),
        ("b" * 40, True),  # the exact synced commit
        ("b" * 8, True),  # abbreviated synced commit
        ("v1.2.3", False),  # a tag — not fetched in v1
        ("release", False),  # another branch — not fetched in v1
        ("f" * 40, False),  # some other commit
    ],
)
def test_ref_is_current(ref: str | None, expected: bool) -> None:
    assert ref_is_current(ref, PLATFORM) is expected


def _resolve(target_ref: str, **kwargs: object) -> str | None:
    return resolve_target_node_id(
        target_ref,
        source_repo_full_name=kwargs.get("source", "acme/services"),  # type: ignore[arg-type]
        repo_states=kwargs.get("states", STATES),  # type: ignore[arg-type]
        known_node_ids=kwargs.get("known", KNOWN),  # type: ignore[arg-type]
    )


def test_resolves_cross_repo_call_at_default_branch() -> None:
    assert _resolve("acme/platform/.github/workflows/reusable-deploy.yml@main") == NODE_ID


def test_resolves_same_repo_call() -> None:
    assert (
        _resolve("./.github/workflows/cross-repo.yml")
        == "acme/services/.github/workflows/cross-repo.yml"
    )


def test_untracked_target_repo_is_unresolved() -> None:
    assert _resolve("other/repo/.github/workflows/x.yml@main") is None


def test_pinned_tag_is_unresolved_even_when_repo_is_tracked() -> None:
    """The documented v1 limitation: only the synced default-branch HEAD resolves."""
    assert _resolve("acme/platform/.github/workflows/reusable-deploy.yml@v1.2.3") is None


def test_repo_tracked_but_not_yet_synced_is_unresolved() -> None:
    states = dict(STATES)
    states["acme/platform"] = RepoRefState("acme/platform", "main", None)
    assert _resolve("acme/platform/.github/workflows/x.yml@main", states=states) is None


def test_missing_workflow_file_in_tracked_repo_is_unresolved() -> None:
    assert _resolve("acme/platform/.github/workflows/does-not-exist.yml@main") is None


def _resolution(target_ref: str, **kwargs: object):  # type: ignore[no-untyped-def]
    return resolve_call(
        target_ref,
        source_repo_full_name=kwargs.get("source", "acme/services"),  # type: ignore[arg-type]
        repo_states=kwargs.get("states", STATES),  # type: ignore[arg-type]
        known_node_ids=kwargs.get("known", KNOWN),  # type: ignore[arg-type]
    )


def test_resolution_reason_is_none_when_resolved() -> None:
    res = _resolution(f"{NODE_ID}@main")
    assert res.node_id == NODE_ID
    assert res.reason is None
    assert res.target_repo_full_name == "acme/platform"
    assert res.target_default_branch == "main"


def test_resolution_reason_repo_not_tracked() -> None:
    res = _resolution("other/repo/.github/workflows/x.yml@main")
    assert res.node_id is None
    assert res.reason == "repo_not_tracked"
    assert res.target_repo_full_name == "other/repo"


def test_resolution_reason_repo_not_synced() -> None:
    states = dict(STATES)
    states["acme/platform"] = RepoRefState("acme/platform", "main", None)
    res = _resolution(f"{NODE_ID}@main", states=states)
    assert res.reason == "repo_not_synced"


def test_resolution_reason_ref_not_synced_carries_the_default_branch() -> None:
    """The §8 limitation needs the branch name to tell the user what to use."""
    res = _resolution(f"{NODE_ID}@v1.2.3")
    assert res.reason == "ref_not_synced"
    assert res.target_ref == "v1.2.3"
    assert res.target_default_branch == "main"


def test_resolution_reason_workflow_not_found() -> None:
    res = _resolution("acme/platform/.github/workflows/nope.yml@main")
    assert res.reason == "workflow_not_found"
    assert res.target_path == ".github/workflows/nope.yml"


def test_resolution_reason_malformed_ref() -> None:
    assert _resolution("actions/checkout@v4").reason == "malformed_ref"


def test_every_unresolved_reason_is_reachable() -> None:
    """A guard: if a reason is added, this test forces it to be exercised."""
    from typing import get_args

    from app.graph.resolve import UnresolvedReason

    states = dict(STATES)
    states["untracked/pending"] = RepoRefState("untracked/pending", "main", None)
    produced = {
        _resolution("actions/checkout@v4", states=states).reason,
        _resolution("other/repo/.github/workflows/x.yml@main", states=states).reason,
        _resolution("untracked/pending/.github/workflows/x.yml@main", states=states).reason,
        _resolution(f"{NODE_ID}@v1.2.3", states=states).reason,
        _resolution("acme/platform/.github/workflows/nope.yml@main", states=states).reason,
    }
    assert produced == set(get_args(UnresolvedReason))
