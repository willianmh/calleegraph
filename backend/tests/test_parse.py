"""Workflow YAML parsing (backend prompt §7)."""

from __future__ import annotations

import pytest

from app.github.parse import (
    WorkflowParseError,
    is_workflow_call_uses,
    is_workflow_path,
    parse_workflow,
)
from tests.repos import fixture


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (".github/workflows/ci.yml", True),
        (".github/workflows/ci.yaml", True),
        (".github/workflows/nested/ci.yml", False),  # GitHub doesn't read these
        (".github/actions/thing/action.yml", False),
        ("ci.yml", False),
        (".github/workflows/README.md", False),
    ],
)
def test_is_workflow_path(path: str, expected: bool) -> None:
    assert is_workflow_path(path) is expected


@pytest.mark.parametrize(
    ("uses", "expected"),
    [
        ("./.github/workflows/deploy.yml", True),
        ("acme/platform/.github/workflows/deploy.yml@main", True),
        ("acme/platform/.github/workflows/deploy.yaml@v1", True),
        # v1 graphs workflow→workflow calls only; plain actions are not nodes.
        ("actions/checkout@v4", False),
        ("docker://alpine:3", False),
        ("./.github/actions/setup", False),
    ],
)
def test_is_workflow_call_uses(uses: str, expected: bool) -> None:
    assert is_workflow_call_uses(uses) is expected


def test_parse_top_level_workflow() -> None:
    wf = parse_workflow(".github/workflows/ci.yml", fixture("top_level_ci.yml"))
    assert wf.kind == "top_level"
    assert wf.name == "CI"
    assert sorted(wf.triggers) == ["pull_request", "push"]
    assert wf.declared_inputs == []
    assert [j.job_key for j in wf.jobs] == ["build", "test"]
    assert wf.jobs[0].name == "Build"
    assert wf.jobs[1].needs == ["build"]
    # `uses: actions/checkout@v4` is a step, and a plain action either way.
    assert all(j.call is None for j in wf.jobs)


def test_parse_reusable_workflow_declares_io() -> None:
    wf = parse_workflow(
        ".github/workflows/reusable-deploy.yml", fixture("reusable_deploy.yml")
    )
    assert wf.kind == "reusable"
    assert wf.triggers == ["workflow_call"]

    by_name = {d.name: d for d in wf.declared_inputs}
    assert by_name["environment"].type == "string"
    assert by_name["environment"].required is True
    assert by_name["environment"].default is None
    assert by_name["dry_run"].type == "boolean"
    assert by_name["dry_run"].default is False
    assert by_name["replicas"].type == "number"
    assert by_name["replicas"].default == 2
    assert by_name["tier"].type == "choice"
    assert by_name["tier"].options == ["standard", "premium"]

    assert wf.declared_secrets == ["DEPLOY_TOKEN"]
    assert [o.name for o in wf.declared_outputs] == ["deployed_url"]


def test_parse_same_repo_call_with_inputs_and_inherited_secrets() -> None:
    wf = parse_workflow(".github/workflows/release.yml", fixture("caller_ok.yml"))
    job = wf.jobs[0]
    assert job.condition == "github.ref == 'refs/heads/main'"
    assert job.call is not None
    assert job.call.target_ref == "./.github/workflows/reusable-deploy.yml"
    # Values stay raw strings; YAML's `false` becomes the workflow spelling.
    assert job.call.with_mapping == {"environment": "production", "dry_run": "false"}
    assert job.call.secrets_mode == "inherit"
    assert job.call.secrets is None


def test_parse_explicit_secrets_mode() -> None:
    wf = parse_workflow(".github/workflows/release.yml", fixture("caller_broken_inputs.yml"))
    call = wf.jobs[0].call
    assert call is not None
    assert call.secrets_mode == "explicit"
    assert call.secrets == ["DEPLOY_TOKEN"]


def test_parse_on_as_bare_string_marks_reusable() -> None:
    wf = parse_workflow(".github/workflows/x.yml", fixture("on_as_string.yml"))
    assert wf.triggers == ["workflow_call"]
    assert wf.kind == "reusable"
    assert wf.declared_inputs == []


def test_parse_on_as_list() -> None:
    wf = parse_workflow(".github/workflows/x.yml", fixture("on_as_list.yml"))
    assert wf.triggers == ["push", "workflow_dispatch"]
    assert wf.kind == "top_level"


def test_parse_null_workflow_call_is_still_reusable() -> None:
    """`workflow_call:` with no body means reusable-with-no-inputs, not absent."""
    wf = parse_workflow(".github/workflows/x.yml", fixture("workflow_call_null.yml"))
    assert wf.kind == "reusable"
    assert wf.triggers == ["workflow_call", "workflow_dispatch"]
    assert wf.declared_inputs == []


def test_parse_needs_string_normalized_to_list() -> None:
    wf = parse_workflow(".github/workflows/x.yml", fixture("needs_as_string.yml"))
    second = next(j for j in wf.jobs if j.job_key == "second")
    assert second.needs == ["first"]
    assert second.condition == "needs.first.outputs.ready == 'true'"


def test_parse_quoted_on_key() -> None:
    """PyYAML resolves a bare `on` to boolean True; a quoted `"on"` stays a str.

    Both spellings must work identically.
    """
    quoted = parse_workflow(".github/workflows/x.yml", fixture("quoted_on.yml"))
    assert quoted.kind == "reusable"
    assert [d.name for d in quoted.declared_inputs] == ["target"]

    bare = parse_workflow(".github/workflows/x.yml", fixture("reusable_deploy.yml"))
    assert bare.kind == "reusable"


def test_parse_ignores_plain_action_jobs() -> None:
    wf = parse_workflow(".github/workflows/x.yml", fixture("cross_repo_caller.yml"))
    by_key = {j.job_key: j for j in wf.jobs}
    assert by_key["deploy"].call is not None
    assert by_key["pinned-to-a-tag"].call is not None
    assert by_key["plain-action-job"].call is None


@pytest.mark.parametrize(
    "name", ["bad_syntax.yml", "bad_not_a_mapping.yml", "bad_empty.yml"]
)
def test_malformed_files_raise_workflow_parse_error(name: str) -> None:
    """Each malformed shape raises a catchable error rather than blowing up.

    The sync loop turns this into "skip this file, keep the repo" (§7).
    """
    with pytest.raises(WorkflowParseError):
        parse_workflow(f".github/workflows/{name}", fixture(name))
