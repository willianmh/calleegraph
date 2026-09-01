"""Pydantic request/response models for the REST API.

These define the wire contract consumed by the frontend. The authoritative
source is the **orchestrator prompt §5**; the shapes below implement it
verbatim (backend prompt §5 defers to it to avoid drift).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# --- Contract enums (orchestrator §5) ---

RepoStatus = Literal["pending", "fetching", "parsing", "done", "error"]
NodeKind = Literal["top_level", "reusable"]
IOType = Literal["string", "boolean", "number", "choice"]
EdgeStatus = Literal["ok", "warning", "error", "unresolved"]
IssueSeverity = Literal["error", "warning"]
IssueCode = Literal[
    "unknown_input",
    "missing_required_input",
    "type_mismatch",
    "unresolvable_condition",
    "unresolved_target",
]


# --- Settings ---


class SettingsResponse(BaseModel):
    pat_set: bool
    github_actor_login: str | None
    github_api_version: str
    github_api_base: str


class SettingsUpdate(BaseModel):
    github_pat: str | None = None
    github_api_version: str | None = None
    github_api_base: str | None = None


# --- Health ---


class HealthResponse(BaseModel):
    status: Literal["ok"]
    db: Literal["connected", "unavailable"]
    cache: Literal["connected", "unavailable"]


# --- Repositories ---


class RepositoryResponse(BaseModel):
    id: int
    owner: str
    name: str
    full_name: str
    default_branch: str
    status: RepoStatus
    error: str | None
    last_synced_commit_sha: str | None
    last_synced_at: datetime | None
    created_at: datetime


class RepositoryCreate(BaseModel):
    full_name: str


# --- Graph ---


class WorkflowIODef(BaseModel):
    name: str
    type: IOType
    required: bool
    default: str | bool | float | None
    description: str | None
    # Populated for type "choice"; null otherwise.
    options: list[str] | None = None


class JobCall(BaseModel):
    # `with` is a Python keyword, so the field is named `with_mapping` and
    # aliased. Always serialize with by_alias=True (FastAPI does by default).
    model_config = ConfigDict(populate_by_name=True)

    target_node_id: str | None
    target_ref: str
    with_mapping: dict[str, str] = Field(alias="with")
    secrets_mode: Literal["inherit", "explicit", "none"]
    secrets: list[str] | None


class JobNode(BaseModel):
    id: str
    job_key: str
    name: str | None
    needs: list[str]
    condition: str | None
    call: JobCall | None


class WorkflowNode(BaseModel):
    # `${repository_full_name}/${path}` — stable across re-syncs.
    id: str
    repository_full_name: str
    path: str
    name: str
    kind: NodeKind
    triggers: list[str]
    jobs: list[JobNode]
    declared_inputs: list[WorkflowIODef]
    declared_secrets: list[str]
    declared_outputs: list[WorkflowIODef]


class EdgeIssue(BaseModel):
    severity: IssueSeverity
    code: IssueCode
    message: str
    suggestion: str | None
    input_name: str | None


class Edge(BaseModel):
    id: str
    source_node_id: str
    source_job_id: str
    target_node_id: str | None
    target_ref: str
    condition: str | None
    status: EdgeStatus
    issues: list[EdgeIssue]


class GraphResponse(BaseModel):
    repositories: list[RepositoryResponse]
    nodes: list[WorkflowNode]
    edges: list[Edge]
    generated_at: datetime
