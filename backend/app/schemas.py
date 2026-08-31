"""Pydantic request/response models for the REST API.

These define the wire contract consumed by the frontend (backend prompt §5).
Only the ``Settings`` shapes are defined here for now — this slice of the
backend implements GitHub PAT authentication only.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

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
