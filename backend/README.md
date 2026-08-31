# Calleegraph backend

This slice of the backend implements **GitHub PAT authentication only** —
storing, encrypting, and validating the GitHub personal access token used for
every other GitHub call the tool makes. See
[`docs/github-authentication.md`](../docs/github-authentication.md) at the
repo root for what's implemented and why. Repository registration, workflow
discovery/parsing, graph assembly, and the SSE stream are separate,
not-yet-built slices of `02_backend_prompt.md`.

## Requirements

- Python 3.12+, [uv](https://docs.astral.sh/uv/)
- PostgreSQL (async access via `asyncpg`)
- Redis

## Setup

```bash
cd backend
uv sync
cp .env.example .env   # fill in ENCRYPTION_KEY, DATABASE_URL, REDIS_URL
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Generate a Fernet key for `ENCRYPTION_KEY`:

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`GET /api/health` reports `db`/`cache` connectivity once the app is up.

## Tests

Tests run against real Postgres + Redis (no sqlite/fakeredis substitution —
this slice's contract is Postgres-specific column types). Point them at a
disposable database via `TEST_DATABASE_URL` / `TEST_REDIS_URL` (defaults to
the same instances as `.env.example`, database `calleegraph`); each test
creates and drops its own schema, and flushes the whole Redis DB, so use a
throwaway database/DB index, not one with data you care about:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://calleegraph:calleegraph@localhost:5432/calleegraph_test \
TEST_REDIS_URL=redis://localhost:6379/1 \
uv run pytest
```

GitHub REST calls are mocked (`httpx.MockTransport`) — no network calls in
tests.

## Lint / typecheck

```bash
uv run ruff check .
uv run mypy app
```
