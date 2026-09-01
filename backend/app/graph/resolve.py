"""Cross-repo / cross-ref resolution of a `uses:` target (backend prompt §8).

**Documented v1 limitation.** Calleegraph fetches and parses exactly *one ref
per tracked repo*: that repo's current default-branch HEAD. So a `uses:`
pinned to a tag, a SHA, or a non-default branch cannot be resolved even when
the target repo *is* tracked — Calleegraph simply does not hold that ref's
content. Such an edge stays ``unresolved`` with its ``target_ref`` preserved,
so the UI can still show what it points at. This is a scope boundary, not a
bug; multi-ref fetching per repo is future work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class RepoRefState:
    """What Calleegraph currently holds for one tracked repo."""

    full_name: str
    default_branch: str
    last_synced_commit_sha: str | None


# Why a call could not be resolved. Each maps to a *different* user action, so
# the UI copy for them must differ (see ``validate.unresolved_target_issue``).
UnresolvedReason = Literal[
    "malformed_ref",
    "repo_not_tracked",
    "repo_not_synced",
    "ref_not_synced",
    "workflow_not_found",
]


@dataclass(frozen=True, slots=True)
class ParsedUses:
    """A `uses:` string broken into its parts."""

    # None for a same-repo `./…` reference.
    repo_full_name: str | None
    path: str
    # None when the reference omits `@ref` (only legal for same-repo `./…`).
    ref: str | None


def parse_uses(uses: str, *, source_repo_full_name: str) -> ParsedUses | None:
    """Split a workflow-call `uses:` into (repo, path, ref).

    Returns None if the string isn't shaped like a workflow reference.
    """
    raw = uses.strip()
    if not raw:
        return None

    if raw.startswith("./"):
        # Same-repo reference; the ref is implicit (the caller's own commit).
        path, _, ref = raw[2:].partition("@")
        return ParsedUses(
            repo_full_name=source_repo_full_name, path=path, ref=ref or None
        )

    body, sep, ref = raw.partition("@")
    parts = body.split("/")
    if len(parts) < 3:
        return None
    repo_full_name = f"{parts[0]}/{parts[1]}"
    path = "/".join(parts[2:])
    return ParsedUses(repo_full_name=repo_full_name, path=path, ref=(ref if sep else None) or None)


def ref_is_current(ref: str | None, state: RepoRefState) -> bool:
    """Does ``ref`` name what Calleegraph actually has synced for this repo?

    True when the ref is omitted (implicitly the caller's own commit), matches
    the synced commit SHA (full or abbreviated), or names the default branch.
    Anything else — a tag, a release SHA, another branch — is out of scope
    for v1 (see the module docstring).
    """
    if ref is None:
        return True
    if ref == state.default_branch or ref == f"refs/heads/{state.default_branch}":
        return True
    sha = state.last_synced_commit_sha
    if sha and len(ref) >= 7 and sha.startswith(ref):
        return True
    return False


@dataclass(frozen=True, slots=True)
class Resolution:
    """The outcome of resolving one `uses:`, with enough context to explain it.

    ``reason`` is None exactly when ``node_id`` is set. The remaining fields
    carry the parsed reference so the issue built from this (§9) can name real
    repos, paths and refs instead of generic copy.
    """

    node_id: str | None
    reason: UnresolvedReason | None = None
    target_repo_full_name: str | None = None
    target_path: str | None = None
    target_ref: str | None = None
    target_default_branch: str | None = None


def resolve_call(
    target_ref: str,
    *,
    source_repo_full_name: str,
    repo_states: dict[str, RepoRefState],
    known_node_ids: set[str],
) -> Resolution:
    """Resolve a `uses:` to a ``workflow_node.id``, or explain why it can't be.

    The five unresolved reasons are deliberately distinct: "the repo isn't
    registered" and "the repo is registered but you pinned a tag we don't
    hold" call for different fixes from the user.
    """
    parsed = parse_uses(target_ref, source_repo_full_name=source_repo_full_name)
    if parsed is None or parsed.repo_full_name is None:
        return Resolution(node_id=None, reason="malformed_ref")

    common = {
        "target_repo_full_name": parsed.repo_full_name,
        "target_path": parsed.path,
        "target_ref": parsed.ref,
    }

    state = repo_states.get(parsed.repo_full_name)
    if state is None:
        return Resolution(node_id=None, reason="repo_not_tracked", **common)  # type: ignore[arg-type]
    if state.last_synced_commit_sha is None:
        return Resolution(node_id=None, reason="repo_not_synced", **common)  # type: ignore[arg-type]
    if not ref_is_current(parsed.ref, state):
        # The documented v1 limitation (see the module docstring).
        return Resolution(
            node_id=None,
            reason="ref_not_synced",
            target_default_branch=state.default_branch,
            **common,  # type: ignore[arg-type]
        )

    node_id = f"{parsed.repo_full_name}/{parsed.path}"
    if node_id not in known_node_ids:
        return Resolution(node_id=None, reason="workflow_not_found", **common)  # type: ignore[arg-type]
    return Resolution(
        node_id=node_id, target_default_branch=state.default_branch, **common  # type: ignore[arg-type]
    )


def resolve_target_node_id(
    target_ref: str,
    *,
    source_repo_full_name: str,
    repo_states: dict[str, RepoRefState],
    known_node_ids: set[str],
) -> str | None:
    """``resolve_call`` when only the resolved id is wanted."""
    return resolve_call(
        target_ref,
        source_repo_full_name=source_repo_full_name,
        repo_states=repo_states,
        known_node_ids=known_node_ids,
    ).node_id
