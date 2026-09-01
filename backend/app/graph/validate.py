"""Validation rules producing ``EdgeIssue[]`` per edge (backend prompt §9).

Two separate things happen here, and the split matters:

* **Input-wiring rules** (`unknown_input`, `missing_required_input`,
  `type_mismatch`) run *only* against a resolved callee. An unresolved edge has
  no parsed callee to check against, so these stay suppressed there — that is
  what §9's "no issues" line is about.
* **`unresolved_target`** explains the unresolved state itself, which is a
  different claim entirely. Every unresolved edge carries exactly one, because
  the frontend renders issue `message`/`suggestion` verbatim and so cannot
  author that copy itself (frontend prompt §4.2). Orchestrator §5 defines the
  code for precisely this.

``edge.status`` stays ``"unresolved"`` regardless: ``edge_status`` never rolls
an unresolved edge's issues up into ``"warning"``/``"error"``, because §5 names
those three as distinct states the UI must style differently.

Issues are recomputed at assembly time and never persisted (§4).
"""

from __future__ import annotations

import re

from app.graph.resolve import Resolution
from app.schemas import EdgeIssue, EdgeStatus, WorkflowIODef

# Matches `${{ … }}` — a runtime expression whose value we cannot know
# statically, so literal type checks are skipped for it.
_EXPRESSION_RE = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)

# Deliberately simple name extraction, not a GitHub Actions expression
# evaluator — hence `unresolvable_condition` is a warning, never an error.
_NEEDS_REF_RE = re.compile(r"\bneeds\.([A-Za-z_][A-Za-z0-9_-]*)\b")
_INPUTS_REF_RE = re.compile(r"\binputs\.([A-Za-z_][A-Za-z0-9_-]*)\b")

_MAX_SUGGESTION_DISTANCE = 2


def is_expression(value: str) -> bool:
    """True if the value contains a `${{ }}` expression (unknowable statically)."""
    return bool(_EXPRESSION_RE.search(value))


def levenshtein(a: str, b: str) -> int:
    """Plain edit distance. Used for the "did you mean" suggestion (§9)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (ca != cb),  # substitution
                )
            )
        previous = current
    return previous[-1]


def closest_name(
    name: str, candidates: list[str], *, max_distance: int = _MAX_SUGGESTION_DISTANCE
) -> str | None:
    """Nearest candidate within ``max_distance`` edits, or None."""
    best: str | None = None
    best_distance = max_distance + 1
    for candidate in candidates:
        distance = levenshtein(name.lower(), candidate.lower())
        if distance < best_distance:
            best, best_distance = candidate, distance
    return best if best_distance <= max_distance else None


def _check_unknown_inputs(
    with_mapping: dict[str, str], declared: list[WorkflowIODef]
) -> list[EdgeIssue]:
    declared_names = [d.name for d in declared]
    declared_set = set(declared_names)
    issues: list[EdgeIssue] = []
    for key in with_mapping:
        if key in declared_set:
            continue
        suggestion_name = closest_name(key, declared_names)
        if suggestion_name is not None:
            suggestion = f"Did you mean `{suggestion_name}`?"
        elif declared_names:
            suggestion = (
                f"Remove `{key}` — this workflow declares only: "
                + ", ".join(f"`{n}`" for n in sorted(declared_names))
                + "."
            )
        else:
            suggestion = f"Remove `{key}` — this workflow declares no `workflow_call` inputs."
        issues.append(
            EdgeIssue(
                severity="error",
                code="unknown_input",
                message=f"`{key}` is not a declared input of the called workflow.",
                suggestion=suggestion,
                input_name=key,
            )
        )
    return issues


def _check_missing_required(
    with_mapping: dict[str, str], declared: list[WorkflowIODef]
) -> list[EdgeIssue]:
    issues: list[EdgeIssue] = []
    for item in declared:
        if not item.required or item.default is not None:
            continue
        if item.name in with_mapping:
            continue
        issues.append(
            EdgeIssue(
                severity="error",
                code="missing_required_input",
                message=f"Required input `{item.name}` is not passed by this call.",
                suggestion=(
                    f"Add `{item.name}:` to this job's `with:` block "
                    f"(declared type `{item.type}`, no default)."
                ),
                input_name=item.name,
            )
        )
    return issues


def _check_type_mismatches(
    with_mapping: dict[str, str], declared: list[WorkflowIODef]
) -> list[EdgeIssue]:
    by_name = {d.name: d for d in declared}
    issues: list[EdgeIssue] = []
    for key, value in with_mapping.items():
        item = by_name.get(key)
        if item is None:
            continue  # already reported as unknown_input
        # A runtime expression's value is unknowable statically — don't guess.
        if is_expression(value):
            continue
        literal = value.strip()
        problem: str | None = None
        suggestion: str | None = None
        if item.type == "boolean" and literal.lower() not in {"true", "false"}:
            problem = f"`{key}` is declared `boolean` but is passed the literal `{literal}`."
            suggestion = f"Pass `true` or `false` for `{key}`."
        elif item.type == "number":
            try:
                float(literal)
            except ValueError:
                problem = f"`{key}` is declared `number` but is passed the literal `{literal}`."
                suggestion = f"Pass a numeric literal for `{key}`."
        elif item.type == "choice" and item.options and literal not in item.options:
            problem = f"`{key}` is declared `choice` but `{literal}` is not one of its options."
            suggestion = (
                "Use one of: " + ", ".join(f"`{o}`" for o in item.options) + "."
            )
        if problem is not None:
            issues.append(
                EdgeIssue(
                    severity="error",
                    code="type_mismatch",
                    message=problem,
                    suggestion=suggestion,
                    input_name=key,
                )
            )
    return issues


def check_condition(
    condition: str | None,
    *,
    sibling_job_keys: set[str],
    own_declared_input_names: set[str],
    check_inputs: bool,
) -> list[EdgeIssue]:
    """`if:` sanity check — warnings only (§9).

    The expression "parser" here is a pair of regexes, not an evaluator, so a
    hit means "suspicious", not "wrong". Hence severity ``warning``.
    """
    if not condition:
        return []
    issues: list[EdgeIssue] = []
    for job_key in sorted(set(_NEEDS_REF_RE.findall(condition))):
        if job_key in sibling_job_keys:
            continue
        known = ", ".join(f"`{k}`" for k in sorted(sibling_job_keys)) or "none"
        issues.append(
            EdgeIssue(
                severity="warning",
                code="unresolvable_condition",
                message=(
                    f"This job's `if:` references `needs.{job_key}`, but no job "
                    f"`{job_key}` exists in this workflow."
                ),
                suggestion=(
                    f"Reference one of this workflow's jobs instead ({known}), "
                    f"or add `{job_key}` to this job's `needs:`."
                ),
                input_name=None,
            )
        )
    if check_inputs:
        for input_name in sorted(set(_INPUTS_REF_RE.findall(condition))):
            if input_name in own_declared_input_names:
                continue
            known = ", ".join(f"`{n}`" for n in sorted(own_declared_input_names)) or "none"
            issues.append(
                EdgeIssue(
                    severity="warning",
                    code="unresolvable_condition",
                    message=(
                        f"This job's `if:` references `inputs.{input_name}`, which this "
                        f"workflow does not declare under `on.workflow_call.inputs`."
                    ),
                    suggestion=(
                        f"Declare `{input_name}` under `on.workflow_call.inputs`, "
                        f"or use one of the declared inputs ({known})."
                    ),
                    input_name=input_name,
                )
            )
    return issues


def validate_call(
    with_mapping: dict[str, str], callee_declared_inputs: list[WorkflowIODef]
) -> list[EdgeIssue]:
    """Input-wiring checks for a resolved call (§9)."""
    return [
        *_check_unknown_inputs(with_mapping, callee_declared_inputs),
        *_check_missing_required(with_mapping, callee_declared_inputs),
        *_check_type_mismatches(with_mapping, callee_declared_inputs),
    ]


def unresolved_target_issue(resolution: Resolution) -> EdgeIssue:
    """The single issue carried by every unresolved edge.

    Copy is specific per cause, because the user action differs per cause: an
    untracked repo is fixed by adding it, a pinned tag is a v1 scope boundary
    with no "add the repo" fix at all, and a bad path is a typo in the caller.
    Collapsing these into one generic string would send users to Repositories
    to add a repo that is already there.
    """
    repo = resolution.target_repo_full_name
    path = resolution.target_path
    ref = resolution.target_ref
    branch = resolution.target_default_branch

    if resolution.reason == "repo_not_tracked" and repo:
        message = (
            f"This call targets `{repo}`, which Calleegraph isn't tracking, so its "
            f"workflows haven't been parsed yet."
        )
        suggestion = f"Add `{repo}` under Repositories to resolve this call."
    elif resolution.reason == "repo_not_synced" and repo:
        message = (
            f"`{repo}` is registered but hasn't completed a sync yet, so this call "
            f"has nothing to resolve against."
        )
        suggestion = (
            f"Wait for `{repo}` to finish syncing — or, if it's stuck in an error "
            f"state, re-sync it from Repositories."
        )
    elif resolution.reason == "ref_not_synced" and repo:
        # The §8 v1 limitation. Deliberately *not* an "add the repo" prompt:
        # the repo is already tracked, and adding it again would change nothing.
        message = (
            f"This call pins `{repo}` at `{ref}`, but Calleegraph only holds that "
            f"repo's default branch (`{branch}`) at its current commit."
        )
        suggestion = (
            f"Point this call at `{branch}` to resolve it. Calleegraph tracks one "
            f"ref per repo in v1, so tags, commit SHAs and other branches stay "
            f"unresolved."
        )
    elif resolution.reason == "workflow_not_found" and repo:
        message = (
            f"`{repo}` is synced, but it has no workflow file at `{path}` on "
            f"`{branch}`."
        )
        suggestion = (
            f"Check the path in `uses:` — `{path}` doesn't exist in `{repo}` at the "
            f"commit Calleegraph has synced."
        )
    else:
        message = "This job's `uses:` isn't a recognizable reusable-workflow reference."
        suggestion = (
            "Use `./.github/workflows/<file>.yml` for a same-repo call, or "
            "`owner/repo/.github/workflows/<file>.yml@ref` for a cross-repo one."
        )

    return EdgeIssue(
        severity="warning",
        code="unresolved_target",
        message=message,
        suggestion=suggestion,
        input_name=None,
    )


def edge_status(resolved: bool, issues: list[EdgeIssue]) -> EdgeStatus:
    """`unresolved` is set independently of issues and never collapsed into
    `error` or `warning` — it's a data-completeness gap, not a validation
    failure (orchestrator §5 contract invariant).

    The early return below is load-bearing: an unresolved edge always carries
    an ``unresolved_target`` issue of severity ``warning``, and rolling that up
    would erase the very distinction §5 requires the UI to style separately.
    """
    if not resolved:
        return "unresolved"
    if any(i.severity == "error" for i in issues):
        return "error"
    if any(i.severity == "warning" for i in issues):
        return "warning"
    return "ok"
