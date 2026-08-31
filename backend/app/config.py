"""Application configuration via pydantic-settings.

All settings are read from environment variables (see ``.env.example`` for the
documented names and defaults) — 12-factor, per the backend prompt §3.

This slice of the backend implements GitHub PAT authentication only (settings
storage, encryption, validation). ``GRAPH_CACHE_TTL_SECONDS`` and
``FETCH_CONCURRENCY`` are part of the documented contract but are not consumed
yet — they're provisioned here so the repo-sync/graph-assembly work that lands
next doesn't need a config rewrite.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the Calleegraph backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- GitHub ---
    # Bootstrap PAT. If set and the DB has none, settings are seeded with it on
    # startup. Can also be set (or replaced) in-app via PUT /api/settings.
    github_pat: str | None = None
    github_api_version: str = "2022-11-28"
    # Overridable for GitHub Enterprise Server deployments.
    github_api_base: str = "https://api.github.com"

    # --- Backend runtime ---
    # Fernet key that encrypts the PAT at rest in Postgres. Required — there is
    # no safe default. Missing/invalid keys raise only when an encrypt/decrypt
    # is attempted (see crypto.py), so the app still boots and can serve
    # /api/health without one configured.
    encryption_key: str | None = None
    database_url: str = ""
    redis_url: str = ""
    graph_cache_ttl_seconds: int = 300
    fetch_concurrency: int = 3
    # Comma-separated CORS origins.
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
