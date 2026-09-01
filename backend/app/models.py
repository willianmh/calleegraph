"""SQLModel table definitions (backend prompt §4).

The ``settings`` singleton backs the GitHub-auth slice; ``repository`` /
``workflow_node`` / ``job`` / ``job_call`` back repository registration,
workflow discovery and graph assembly.

Deliberately absent: an issues table. Validation issues (``EdgeIssue[]``) are
recomputed deterministically at graph-assembly time from these rows (§4/§11)
and cached only as part of the assembled ``GraphResponse`` in Redis.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum, StrEnum
from typing import Any

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """Timezone-aware current UTC timestamp."""
    return datetime.now(UTC)


class RepoStatus(StrEnum):
    """``Repository.status`` — mirrors contract ``RepoStatus`` (orchestrator §5)."""

    pending = "pending"
    fetching = "fetching"
    parsing = "parsing"
    done = "done"
    error = "error"


class NodeKind(StrEnum):
    """``WorkflowNode.kind`` — reusable iff ``on.workflow_call`` is present."""

    top_level = "top_level"
    reusable = "reusable"


class SecretsMode(StrEnum):
    """How a calling job passes secrets to the callee."""

    inherit = "inherit"
    explicit = "explicit"
    none = "none"


def _enum_column(enum_cls: type[Enum], name: str, **kw: Any) -> Column[Any]:
    """A Postgres ENUM column storing the member *values* (not their names)."""
    return Column(
        SAEnum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        **kw,
    )


class Settings(SQLModel, table=True):
    """Singleton settings row (id=1). Holds the encrypted GitHub PAT."""

    __tablename__ = "settings"

    id: int | None = Field(default=1, primary_key=True)
    github_pat_encrypted: str | None = None
    # Cached from GET /user when a PAT is validated (§5).
    github_actor_login: str | None = None
    github_api_version: str = "2022-11-28"
    github_api_base: str = "https://api.github.com"
    updated_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class Repository(SQLModel, table=True):
    """A tracked GitHub repository, synced at its default-branch HEAD (§4)."""

    __tablename__ = "repository"

    id: int | None = Field(default=None, primary_key=True)
    owner: str
    name: str
    full_name: str = Field(sa_column=Column(String, nullable=False, unique=True, index=True))
    default_branch: str
    status: RepoStatus = Field(
        default=RepoStatus.pending, sa_column=_enum_column(RepoStatus, "repo_status")
    )
    error: str | None = None
    last_synced_commit_sha: str | None = None
    last_synced_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class WorkflowNode(SQLModel, table=True):
    """One parsed workflow file, at the repo's last successfully synced commit."""

    __tablename__ = "workflow_node"

    # `${repository_full_name}/${path}` — stable across re-syncs (contract §5).
    id: str = Field(primary_key=True)
    repository_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("repository.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    path: str
    name: str
    kind: NodeKind = Field(sa_column=_enum_column(NodeKind, "node_kind"))
    # list[str] — trigger keys under `on`.
    triggers: list[str] = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    # WorkflowIODef[] from `on.workflow_call.inputs`; [] if not reusable.
    declared_inputs: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    # list[str] — secret names from `on.workflow_call.secrets`.
    declared_secrets: list[str] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    # WorkflowIODef[] from `on.workflow_call.outputs`.
    declared_outputs: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    source_commit_sha: str
    updated_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class Job(SQLModel, table=True):
    """One job within a workflow file."""

    __tablename__ = "job"

    # `${workflow_node_id}#${job_key}` — stable across re-syncs (contract §5).
    id: str = Field(primary_key=True)
    workflow_node_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey("workflow_node.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    job_key: str
    name: str | None = None
    # list[str] — sibling job_keys this job `needs:`.
    needs: list[str] = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    condition: str | None = None


class JobCall(SQLModel, table=True):
    """A job whose `uses:` targets a reusable workflow (not a plain action)."""

    __tablename__ = "job_call"

    id: int | None = Field(default=None, primary_key=True)
    job_id: str = Field(
        sa_column=Column(
            String, ForeignKey("job.id", ondelete="CASCADE"), nullable=False, unique=True
        )
    )
    # The raw `uses:` string. Always preserved, even when unresolved, so the UI
    # can show what a dangling call points at (§8).
    target_ref: str
    # Best-effort resolution cached at sync time; authoritative resolution is
    # recomputed at assembly time (§11), so a SET NULL here is harmless.
    target_node_id: str | None = Field(
        default=None,
        sa_column=Column(
            String, ForeignKey("workflow_node.id", ondelete="SET NULL"), nullable=True
        ),
    )
    # { input_name: raw_expression_or_literal }
    with_mapping: dict[str, str] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    secrets_mode: SecretsMode = Field(sa_column=_enum_column(SecretsMode, "secrets_mode"))
    # Explicit secret names when secrets_mode == "explicit", else null.
    secrets: list[str] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
