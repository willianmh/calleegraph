"""create settings table

Revision ID: 0001
Revises:
Create Date: 2026-08-31 00:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("github_pat_encrypted", sa.String(), nullable=True),
        sa.Column("github_actor_login", sa.String(), nullable=True),
        sa.Column(
            "github_api_version",
            sa.String(),
            nullable=False,
            server_default="2022-11-28",
        ),
        sa.Column(
            "github_api_base",
            sa.String(),
            nullable=False,
            server_default="https://api.github.com",
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("settings")
