"""Static YAML → workflow-model parsing (backend prompt §7).

Everything here is defensive: GitHub Actions YAML is written by humans, and a
single malformed file must never fail a repo sync. ``parse_workflow`` raises
``WorkflowParseError`` for anything it can't make sense of; the sync loop
catches it per file, logs, and moves on.

A note on ``on:``: YAML 1.1 (which PyYAML implements) resolves the bare token
``on`` to the boolean ``True``. So ``on:`` in an unquoted workflow file comes
back as the key ``True``, not ``"on"``. Both spellings are handled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

import yaml

# `.github/workflows/<file>.yml|.yaml`, directly in that directory — GitHub
# does not read workflows from nested subdirectories.
WORKFLOW_PATH_RE = re.compile(r"^\.github/workflows/[^/]+\.(ya?ml)$")

# A `uses:` that points at a workflow file rather than a plain action.
# Same-repo:  ./.github/workflows/x.yml
# Cross-repo: owner/repo/.github/workflows/x.yml@ref
_WORKFLOW_USES_RE = re.compile(r"\.github/workflows/[^/@]+\.ya?ml(@.+)?$")

IOType = Literal["string", "boolean", "number", "choice"]
_IO_TYPES: set[str] = {"string", "boolean", "number", "choice"}


class WorkflowParseError(Exception):
    """A workflow file could not be parsed into the model."""


@dataclass(slots=True)
class ParsedIODef:
    name: str
    type: IOType
    required: bool
    default: str | bool | float | None
    description: str | None
    options: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "default": self.default,
            "description": self.description,
            "options": self.options,
        }


@dataclass(slots=True)
class ParsedJobCall:
    target_ref: str
    with_mapping: dict[str, str]
    secrets_mode: Literal["inherit", "explicit", "none"]
    secrets: list[str] | None


@dataclass(slots=True)
class ParsedJob:
    job_key: str
    name: str | None
    needs: list[str]
    condition: str | None
    call: ParsedJobCall | None


@dataclass(slots=True)
class ParsedWorkflow:
    path: str
    name: str
    kind: Literal["top_level", "reusable"]
    triggers: list[str]
    declared_inputs: list[ParsedIODef] = field(default_factory=list)
    declared_secrets: list[str] = field(default_factory=list)
    declared_outputs: list[ParsedIODef] = field(default_factory=list)
    jobs: list[ParsedJob] = field(default_factory=list)


def is_workflow_path(path: str) -> bool:
    """True for `.github/workflows/*.yml|*.yaml` (§6 discovery filter)."""
    return bool(WORKFLOW_PATH_RE.match(path))


def is_workflow_call_uses(uses: str) -> bool:
    """True when a `uses:` targets a reusable workflow, not a marketplace action.

    v1 graphs workflow→workflow calls only; `actions/checkout@v4` and friends
    are not nodes (backend prompt §7/§15).
    """
    return bool(_WORKFLOW_USES_RE.search(uses.strip()))


def _scalar_to_str(value: Any) -> str:
    """Render a YAML scalar as the raw string the contract expects.

    `with:` values stay raw — including unevaluated `${{ }}` expressions — but
    YAML has already turned `true`/`42` into Python objects, so booleans are
    lower-cased back to their workflow spelling rather than Python's `True`.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _normalize_str_list(value: Any) -> list[str]:
    """`needs:` (and friends) may be a bare string or a list — always a list here."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [_scalar_to_str(v) for v in value if v is not None]
    return []


def _trigger_keys(on_value: Any) -> list[str]:
    """`on:` may be a string, a list, or a map (§7)."""
    if on_value is None:
        return []
    if isinstance(on_value, str):
        return [on_value]
    if isinstance(on_value, list):
        return [str(v) for v in on_value if v is not None]
    if isinstance(on_value, dict):
        return [str(k) for k in on_value]
    return []


def _get_on(doc: dict[Any, Any]) -> Any:
    """Read the `on:` block, tolerating PyYAML's boolean-`on` resolution."""
    if "on" in doc:
        return doc["on"]
    if True in doc:
        return doc[True]
    return None


def _parse_io_defs(raw: Any, *, default_required: bool) -> list[ParsedIODef]:
    """Parse an `inputs:`/`outputs:` map into IO definitions."""
    if not isinstance(raw, dict):
        return []
    defs: list[ParsedIODef] = []
    for name, spec in raw.items():
        if spec is None:
            spec = {}
        if not isinstance(spec, dict):
            continue
        declared_type = spec.get("type")
        io_type: IOType = "string"
        if isinstance(declared_type, str) and declared_type in _IO_TYPES:
            io_type = declared_type  # type: ignore[assignment]
        options = spec.get("options")
        opts = [_scalar_to_str(o) for o in options] if isinstance(options, list) else None
        default = spec.get("default")
        if isinstance(default, (list, dict)):
            default = _scalar_to_str(default)
        description = spec.get("description")
        defs.append(
            ParsedIODef(
                name=str(name),
                type=io_type,
                required=bool(spec.get("required", default_required)),
                default=default,
                description=str(description) if description is not None else None,
                options=opts if io_type == "choice" else None,
            )
        )
    return defs


def _parse_secret_names(raw: Any) -> list[str]:
    if isinstance(raw, dict):
        return [str(k) for k in raw]
    if isinstance(raw, list):
        return [str(v) for v in raw]
    return []


def _parse_job_call(job: dict[str, Any]) -> ParsedJobCall | None:
    uses = job.get("uses")
    if not isinstance(uses, str) or not is_workflow_call_uses(uses):
        return None

    raw_with = job.get("with")
    with_mapping: dict[str, str] = {}
    if isinstance(raw_with, dict):
        with_mapping = {str(k): _scalar_to_str(v) for k, v in raw_with.items()}

    raw_secrets = job.get("secrets")
    secrets_mode: Literal["inherit", "explicit", "none"]
    secrets: list[str] | None
    if isinstance(raw_secrets, str) and raw_secrets.strip() == "inherit":
        secrets_mode, secrets = "inherit", None
    elif isinstance(raw_secrets, dict):
        secrets_mode, secrets = "explicit", [str(k) for k in raw_secrets]
    else:
        secrets_mode, secrets = "none", None

    return ParsedJobCall(
        target_ref=uses.strip(),
        with_mapping=with_mapping,
        secrets_mode=secrets_mode,
        secrets=secrets,
    )


def parse_workflow(path: str, content: str) -> ParsedWorkflow:
    """Parse one workflow file's YAML into the model (§7).

    Raises ``WorkflowParseError`` on anything unusable so the caller can skip
    this single file and keep syncing the rest of the repo.
    """
    try:
        doc = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise WorkflowParseError(f"{path}: invalid YAML: {exc}") from exc

    if doc is None:
        raise WorkflowParseError(f"{path}: file is empty")
    if not isinstance(doc, dict):
        raise WorkflowParseError(f"{path}: top level is {type(doc).__name__}, expected a mapping")

    on_value = _get_on(doc)
    triggers = _trigger_keys(on_value)

    workflow_call: Any = None
    if isinstance(on_value, dict):
        # `workflow_call:` may legitimately be null (no inputs) — a present key
        # with a None value still means "this is a reusable workflow".
        if "workflow_call" in on_value:
            workflow_call = on_value["workflow_call"] or {}
    elif "workflow_call" in triggers:
        # `on: workflow_call` or `on: [push, workflow_call]` — reusable, but
        # with no inputs/outputs/secrets declared.
        workflow_call = {}

    is_reusable = workflow_call is not None
    declared_inputs: list[ParsedIODef] = []
    declared_outputs: list[ParsedIODef] = []
    declared_secrets: list[str] = []
    if isinstance(workflow_call, dict):
        declared_inputs = _parse_io_defs(workflow_call.get("inputs"), default_required=False)
        # Reusable-workflow outputs declare `description`/`value` only; they
        # are never "required" and carry no type, so they normalize to string.
        declared_outputs = _parse_io_defs(workflow_call.get("outputs"), default_required=False)
        declared_secrets = _parse_secret_names(workflow_call.get("secrets"))

    raw_jobs = doc.get("jobs")
    jobs: list[ParsedJob] = []
    if isinstance(raw_jobs, dict):
        for job_key, raw_job in raw_jobs.items():
            if not isinstance(raw_job, dict):
                continue
            name = raw_job.get("name")
            condition = raw_job.get("if")
            jobs.append(
                ParsedJob(
                    job_key=str(job_key),
                    name=str(name) if name is not None else None,
                    needs=_normalize_str_list(raw_job.get("needs")),
                    condition=_scalar_to_str(condition) if condition is not None else None,
                    call=_parse_job_call(raw_job),
                )
            )

    raw_name = doc.get("name")
    name = str(raw_name) if raw_name is not None else path.rsplit("/", 1)[-1]

    return ParsedWorkflow(
        path=path,
        name=name,
        kind="reusable" if is_reusable else "top_level",
        triggers=triggers,
        declared_inputs=declared_inputs,
        declared_secrets=declared_secrets,
        declared_outputs=declared_outputs,
        jobs=jobs,
    )
