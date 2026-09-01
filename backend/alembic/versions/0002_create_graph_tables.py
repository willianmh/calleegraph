"""create repository / workflow_node / job / job_call tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-31 00:00:00

Validation issues are intentionally not persisted — they're recomputed at
graph-assembly time (backend prompt §4/§11).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

repo_status = sa.Enum(
    "pending", "fetching", "parsing", "done", "error", name="repo_status"
)
node_kind = sa.Enum("top_level", "reusable", name="node_kind")
secrets_mode = sa.Enum("inherit", "explicit", "none", name="secrets_mode")


def upgrade() -> None:
    op.create_table(
        "repository",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("default_branch", sa.String(), nullable=False),
        sa.Column("status", repo_status, nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("last_synced_commit_sha", sa.String(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # SQLModel's Column(unique=True, index=True) yields one unique index (not a
    # separate UNIQUE constraint) — keep the migration byte-identical to the
    # model so `alembic check` stays clean.
    op.create_index("ix_repository_full_name", "repository", ["full_name"], unique=True)

    op.create_table(
        "workflow_node",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("repository_id", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", node_kind, nullable=False),
        sa.Column("triggers", postgresql.JSONB(), nullable=False),
        sa.Column("declared_inputs", postgresql.JSONB(), nullable=False),
        sa.Column("declared_secrets", postgresql.JSONB(), nullable=False),
        sa.Column("declared_outputs", postgresql.JSONB(), nullable=False),
        sa.Column("source_commit_sha", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["repository.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_node_repository_id", "workflow_node", ["repository_id"])

    op.create_table(
        "job",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workflow_node_id", sa.String(), nullable=False),
        sa.Column("job_key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("needs", postgresql.JSONB(), nullable=False),
        sa.Column("condition", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["workflow_node_id"], ["workflow_node.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_workflow_node_id", "job", ["workflow_node_id"])

    op.create_table(
        "job_call",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("target_ref", sa.String(), nullable=False),
        sa.Column("target_node_id", sa.String(), nullable=True),
        sa.Column("with_mapping", postgresql.JSONB(), nullable=False),
        sa.Column("secrets_mode", secrets_mode, nullable=False),
        sa.Column("secrets", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_node_id"], ["workflow_node.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )


def downgrade() -> None:
    op.drop_table("job_call")
    op.drop_index("ix_job_workflow_node_id", table_name="job")
    op.drop_table("job")
    op.drop_index("ix_workflow_node_repository_id", table_name="workflow_node")
    op.drop_table("workflow_node")
    op.drop_index("ix_repository_full_name", table_name="repository")
    op.drop_table("repository")
    bind = op.get_bind()
    secrets_mode.drop(bind, checkfirst=True)
    node_kind.drop(bind, checkfirst=True)
    repo_status.drop(bind, checkfirst=True)
