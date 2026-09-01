"""Validation rules and edge status (backend prompt §9)."""

from __future__ import annotations

import pytest

from app.graph.validate import (
    check_condition,
    closest_name,
    edge_status,
    is_expression,
    levenshtein,
    validate_call,
)
from app.schemas import EdgeIssue, WorkflowIODef


def io(
    name: str,
    type_: str = "string",
    *,
    required: bool = False,
    default: object = None,
    options: list[str] | None = None,
) -> WorkflowIODef:
    return WorkflowIODef(
        name=name,
        type=type_,  # type: ignore[arg-type]
        required=required,
        default=default,  # type: ignore[arg-type]
        description=None,
        options=options,
    )


DECLARED = [
    io("environment", required=True),
    io("dry_run", "boolean", default=False),
    io("replicas", "number", default=2),
    io("tier", "choice", default="standard", options=["standard", "premium"]),
]


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [("", "", 0), ("abc", "abc", 0), ("enviroment", "environment", 1), ("kitten", "sitting", 3)],
)
def test_levenshtein(a: str, b: str, expected: int) -> None:
    assert levenshtein(a, b) == expected


def test_closest_name_respects_distance_ceiling() -> None:
    assert closest_name("enviroment", ["environment", "tier"]) == "environment"
    assert closest_name("completely-different", ["environment", "tier"]) is None


def test_is_expression() -> None:
    assert is_expression("${{ inputs.env }}")
    assert is_expression("prefix-${{ github.sha }}")
    assert not is_expression("production")


def test_unknown_input_suggests_the_close_match_by_name() -> None:
    issues = validate_call({"enviroment": "production"}, DECLARED)
    unknown = [i for i in issues if i.code == "unknown_input"]
    assert len(unknown) == 1
    assert unknown[0].severity == "error"
    assert unknown[0].input_name == "enviroment"
    # The suggestion names the real declared input, not a generic string.
    assert unknown[0].suggestion == "Did you mean `environment`?"


def test_unknown_input_without_a_close_match_suggests_removal() -> None:
    issues = validate_call({"totally_bogus": "x"}, DECLARED)
    unknown = next(i for i in issues if i.code == "unknown_input")
    assert unknown.suggestion is not None
    assert "Remove `totally_bogus`" in unknown.suggestion
    assert "`environment`" in unknown.suggestion


def test_missing_required_input_names_the_input() -> None:
    issues = validate_call({}, DECLARED)
    missing = [i for i in issues if i.code == "missing_required_input"]
    assert [i.input_name for i in missing] == ["environment"]
    assert missing[0].severity == "error"
    assert missing[0].suggestion is not None
    assert "`environment:`" in missing[0].suggestion


def test_input_with_a_default_is_never_missing() -> None:
    declared = [io("thing", required=True, default="fallback")]
    assert validate_call({}, declared) == []


def test_type_mismatch_boolean_number_and_choice() -> None:
    issues = validate_call(
        {"environment": "prod", "dry_run": "maybe", "replicas": "lots", "tier": "enterprise"},
        DECLARED,
    )
    mismatches = {i.input_name: i for i in issues if i.code == "type_mismatch"}
    assert set(mismatches) == {"dry_run", "replicas", "tier"}
    assert mismatches["tier"].suggestion is not None
    assert "`standard`" in mismatches["tier"].suggestion


def test_type_mismatch_skipped_for_runtime_expressions() -> None:
    """An unresolvable `${{ }}` value is not guessed at (§9)."""
    issues = validate_call(
        {"environment": "prod", "dry_run": "${{ inputs.dry }}", "replicas": "${{ vars.N }}"},
        DECLARED,
    )
    assert [i for i in issues if i.code == "type_mismatch"] == []


def test_valid_call_produces_no_issues() -> None:
    assert validate_call({"environment": "production", "dry_run": "true"}, DECLARED) == []


def test_unresolvable_condition_on_missing_needs_is_a_warning() -> None:
    issues = check_condition(
        "needs.nonexistent.outputs.ok == 'true'",
        sibling_job_keys={"build", "deploy"},
        own_declared_input_names=set(),
        check_inputs=False,
    )
    assert len(issues) == 1
    assert issues[0].code == "unresolvable_condition"
    assert issues[0].severity == "warning"
    assert issues[0].suggestion is not None
    assert "`build`" in issues[0].suggestion


def test_condition_referencing_a_real_sibling_is_fine() -> None:
    assert (
        check_condition(
            "needs.build.result == 'success'",
            sibling_job_keys={"build"},
            own_declared_input_names=set(),
            check_inputs=False,
        )
        == []
    )


def test_unresolvable_condition_on_undeclared_input() -> None:
    issues = check_condition(
        "inputs.nope == 'yes'",
        sibling_job_keys=set(),
        own_declared_input_names={"environment"},
        check_inputs=True,
    )
    assert [i.code for i in issues] == ["unresolvable_condition"]
    assert issues[0].input_name == "nope"


def test_inputs_reference_not_checked_for_non_reusable_workflows() -> None:
    assert (
        check_condition(
            "inputs.nope == 'yes'",
            sibling_job_keys=set(),
            own_declared_input_names=set(),
            check_inputs=False,
        )
        == []
    )


def _issue(severity: str) -> EdgeIssue:
    return EdgeIssue(
        severity=severity,  # type: ignore[arg-type]
        code="unknown_input",
        message="m",
        suggestion=None,
        input_name=None,
    )


def test_edge_status_precedence() -> None:
    assert edge_status(True, []) == "ok"
    assert edge_status(True, [_issue("warning")]) == "warning"
    assert edge_status(True, [_issue("warning"), _issue("error")]) == "error"


def test_unresolved_is_never_collapsed_into_error_or_warning() -> None:
    """Contract invariant (orchestrator §5): the three are distinct."""
    assert edge_status(False, []) == "unresolved"
    assert edge_status(False, [_issue("error")]) == "unresolved"
    assert edge_status(False, [_issue("warning")]) == "unresolved"
