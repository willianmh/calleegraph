# Calleegraph backend

Statically analyzes GitHub Actions workflows across the registered repos and
serves the combined reusable-workflow dependency graph.

| Endpoint | Purpose |
|---|---|
| `GET`/`PUT /api/settings` | GitHub PAT (write-only, encrypted at rest) and API base/version |
| `GET`/`POST /api/repositories`, `DELETE /api/repositories/{id}`, `POST /api/repositories/{id}/refresh` | Register and sync repos; `POST` returns `pending` immediately and syncs in the background |
| `GET /api/graph` | The combined `GraphResponse` across all tracked repos |
| `GET /api/events/stream` | SSE: `repository_updated` and `graph_updated` on one connection |
| `GET /api/health` | `db`/`cache` connectivity |

The authoritative wire contract is `03_orchestrator_prompt.md` §5;
`app/schemas.py` implements it verbatim, and `tests/test_contract_scenario.py`
is its executable statement. See
[`docs/github-authentication.md`](../docs/github-authentication.md) for the
PAT handling specifically.

### Known v1 limitation

Each tracked repo is fetched at **one ref**: its current default-branch HEAD.
A `uses:` pinned to a tag, a SHA, or another branch therefore stays
`unresolved` even when the target repo is tracked — the raw `uses:` string is
preserved so the UI can still show what it points at. See `app/graph/resolve.py`.

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
the schema uses Postgres-specific column types: `JSONB` and native enums).
Point them at a
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
tests. `tests/repos.py` serves a synthetic four-repo GitHub built from the
YAML in `tests/fixtures/`, standing in for the contract-verification repos of
`03_orchestrator_prompt.md` §2.2.

## Lint / typecheck

```bash
uv run ruff check .
uv run mypy app
```
