"""SQLModel table definitions.

Only the ``settings`` table (§4 of the backend prompt) is defined here for
now — this slice of the backend implements GitHub PAT authentication only.
The ``repository`` / ``workflow_node`` / ``job`` / ``job_call`` tables land
with the repo-discovery and graph-assembly work.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """Timezone-aware current UTC timestamp."""
    return datetime.now(UTC)


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
