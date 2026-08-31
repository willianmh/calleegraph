# Backend worklog

Append-only. Add a new entry at the end of every work session — never edit or
delete a past entry (see `02_backend_prompt.md` §13).

## [2026-08-31 19:45] GitHub PAT authentication (settings storage + validation)

- Did: Implemented the GitHub authentication slice of the backend, porting
  the pattern from `qm-hayashida/runbook`'s `backend/` (PAT stored encrypted
  at rest, validated against `GET /user`, never returned by any endpoint) and
  adapting it to this project's Postgres/Alembic/Redis stack instead of
  Runbook's SQLite/create-all:
  - `app/config.py` — `pydantic-settings` `Settings` per backend prompt §3
    (`GITHUB_PAT`, `GITHUB_API_VERSION`, `GITHUB_API_BASE`, `ENCRYPTION_KEY`,
    `DATABASE_URL`, `REDIS_URL`, `GRAPH_CACHE_TTL_SECONDS`,
    `FETCH_CONCURRENCY`, `CORS_ORIGINS`).
  - `app/crypto.py` — Fernet encrypt/decrypt, ported as-is from Runbook.
  - `app/models.py` — `settings` singleton table (§4), `id=1`,
    `github_pat_encrypted`, `github_actor_login`, `github_api_version`,
    `github_api_base`, `updated_at` (timezone-aware, explicit
    `DateTime(timezone=True)` column so `create_all`-in-tests and the Alembic
    migration agree on the column type).
  - `app/db.py` — async SQLAlchemy engine over `asyncpg`, no `create_all`;
    schema is Alembic-migrated (`alembic/`, revision `0001` creates
    `settings`). `db_healthy()` for `/api/health`.
  - `app/cache.py` — Redis client (`redis.asyncio`) + `cache_healthy()` for
    `/api/health`. Only the connection lives here; the workflow/graph caches
    (§2b) are out of scope for this slice.
  - `app/github/client.py` — `GitHubClient` ported from Runbook, trimmed to
    what auth needs (`get_user()` for PAT validation) plus the shared
    request/retry/backoff machinery, so repo-tree/blob endpoints (§6) can
    extend the same class later without touching this code.
  - `app/schemas.py`, `app/routers/settings.py` — `GET/PUT /api/settings`
    exactly per backend prompt §5 (`pat_set`, `github_actor_login`,
    `github_api_version`, `github_api_base`; PAT is write-only and validated
    via `GET /user` before being encrypted and stored; `400` with a clear
    `detail` on an invalid PAT).
  - `app/main.py` — app factory + lifespan (init DB/Redis, seed the
    singleton settings row incl. bootstrap `GITHUB_PAT` from env), CORS,
    `GET /api/health` (`db`/`cache` connectivity).
  - `alembic.ini`, `alembic/env.py` (async, `DATABASE_URL`-driven),
    `alembic/versions/0001_create_settings_table.py`.
  - `pyproject.toml` + `uv.lock` — Python 3.12, FastAPI, SQLModel, asyncpg,
    Alembic, httpx, cryptography, redis, pydantic-settings; ruff + mypy dev
    deps matching Runbook's config.
  - `Dockerfile`, `.dockerignore` — ported from Runbook; `CMD` runs
    `alembic upgrade head` before `uvicorn` (§14 "migrating on startup").
  - `.env.example`, `README.md` (local dev / test instructions).
  - `tests/conftest.py`, `tests/test_settings_api.py`,
    `tests/test_github_client.py`, `tests/test_health.py` — GitHub REST
    mocked via `httpx.MockTransport` (no network calls); DB/cache exercised
    against real local Postgres + Redis rather than sqlite/fakeredis
    substitutes, since this slice's whole point is the Postgres-backed
    settings table and its migration.
  - Root `docs/github-authentication.md` — what was implemented and why, for
    the user/orchestrator.
- Verified locally: `uv sync`, `uv run alembic upgrade head` against a local
  Postgres 16 + Redis, `uv run ruff check .` (clean), `uv run mypy app`
  (clean), `uv run pytest` (8/8 passing), and a live smoke test — booted
  `uvicorn`, hit `GET /api/health` (`db`/`cache` both `connected`) and
  `PUT /api/settings` with a real PAT end-to-end (validated against the live
  GitHub API, encrypted, stored; `GET /api/settings` reflected `pat_set` and
  the actor login without ever echoing the token).
- Deviated: Runbook's `services.py` layer (`get_settings_row` +
  `make_github_client` helpers shared across many features) doesn't apply
  yet since this slice only has one consumer — `get_settings_row` lives
  directly in `app/routers/settings.py` instead. Reusable settings-row access
  (e.g. `make_github_client()` for the sync/graph work) should move to a
  shared module once a second consumer exists, to avoid routers importing
  from other routers.
- Blocked: none — the settings/health contract here matches backend prompt
  §5 exactly, no orchestrator decision needed.
- Next: repository registration + workflow discovery (§6, `POST/GET/DELETE
  /api/repositories`, `app/github/client.py` needs `get_repo`, tree listing,
  and blob fetch added), which is the first consumer of the stored PAT beyond
  validation.
