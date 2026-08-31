# GitHub authentication — what was implemented

This document covers one slice of Calleegraph's backend: how the app
authenticates to GitHub. Everything else in `02_backend_prompt.md`
(repository registration, workflow discovery/parsing, graph assembly, SSE)
is a separate, not-yet-built slice — see `backend/WORKLOG.md` for the
handoff.

## Summary

Calleegraph calls the GitHub REST API with a single stored **personal access
token (PAT)** — there's no OAuth flow, no per-user login, no session/cookie
auth. The token is supplied once (via `PUT /api/settings` or the
`GITHUB_PAT` bootstrap env var), validated against the live GitHub API,
encrypted at rest in Postgres, and used by the backend on every subsequent
GitHub call. This matches backend prompt §3–§5 and non-goal §15 ("no auth
beyond the single stored GitHub PAT") exactly.

The implementation is carried over from `qm-hayashida/runbook`'s
`backend/` — which solves the identical problem (a backend that dispatches
GitHub Actions workflows on behalf of one stored PAT) — adapted from
Runbook's SQLite/`create_all` persistence to Calleegraph's required
Postgres/Alembic/Redis stack.

## Where it lives

```
backend/
├── app/
│   ├── config.py            # env vars: GITHUB_PAT, GITHUB_API_VERSION,
│   │                         #   GITHUB_API_BASE, ENCRYPTION_KEY, DATABASE_URL, ...
│   ├── crypto.py             # Fernet encrypt/decrypt for the PAT
│   ├── models.py             # `settings` singleton table (id=1)
│   ├── schemas.py             # SettingsResponse / SettingsUpdate wire types
│   ├── db.py                  # async Postgres engine (asyncpg), no create_all
│   ├── cache.py                # Redis client + health check
│   ├── github/
│   │   └── client.py           # GitHubClient — GET /user (PAT validation)
│   ├── routers/
│   │   └── settings.py          # GET/PUT /api/settings
│   └── main.py                   # app factory, lifespan, GET /api/health
├── alembic/
│   └── versions/0001_create_settings_table.py
└── tests/
    ├── conftest.py
    ├── test_settings_api.py
    ├── test_github_client.py
    └── test_health.py
```

## How it works

1. **Storage.** A singleton `settings` row (Postgres table, `id=1`, created
   by Alembic revision `0001`) holds `github_pat_encrypted`,
   `github_actor_login`, `github_api_version`, and `github_api_base`. The PAT
   column is Fernet-encrypted ciphertext — plaintext never touches disk.

2. **Bootstrapping.** If the `GITHUB_PAT` env var is set and no PAT is
   stored yet, the app seeds it into the settings row on startup (app
   lifespan, `app/main.py`). This lets a deployment configure a token purely
   via environment without a manual API call.

3. **Setting/replacing the PAT.** `PUT /api/settings` with
   `{ "github_pat": "..." }`:
   - Calls `GET /user` on the configured GitHub API base
     (`https://api.github.com` by default, overridable for GitHub
     Enterprise Server) using the new token as a Bearer credential.
   - On success: encrypts the token (Fernet), stores it, and caches the
     returned `login` as `github_actor_login`.
   - On failure (bad credentials, network error): returns `400` with a
     `{"detail": "Invalid GitHub PAT: ..."}` body and **does not** store
     anything — a rejected token never reaches the database.
   - `github_api_version` / `github_api_base` can be updated in the same
     call, independent of the PAT.

4. **Reading settings.** `GET /api/settings` returns
   `{ pat_set, github_actor_login, github_api_version, github_api_base }`.
   The token itself is never included in any response — `pat_set` is a
   boolean derived from "is `github_pat_encrypted` non-null", so the
   frontend can show "configured" state without ever seeing the secret.

5. **Health.** `GET /api/health` reports live `db` and `cache`
   (Postgres/Redis) connectivity, independent of whether a PAT is
   configured — the app boots and serves this endpoint either way.

6. **The GitHub client.** `app/github/client.py` is a thin async `httpx`
   wrapper that attaches `Authorization: Bearer <token>`,
   `X-GitHub-Api-Version`, and handles GitHub's rate-limit/secondary-limit
   responses (`Retry-After`, `x-ratelimit-remaining`/`-reset`) with bounded
   backoff. For this slice it exposes only `get_user()` (PAT validation);
   the repo-tree, blob, and content-fetch calls that repository registration
   needs (backend prompt §6) extend the same class without changing this
   code.

## What was ported from Runbook vs. adapted

| Piece | Runbook | Calleegraph |
|---|---|---|
| PAT storage/encryption | `app/crypto.py` (Fernet) | Copied verbatim |
| Settings table shape | `github_pat_encrypted`, `github_actor_login`, `github_api_version` | Same, plus `github_api_base` (Calleegraph's contract exposes this per §5; Runbook doesn't) |
| PAT validation flow | `PUT /api/settings` → `GET /user` → encrypt → store | Same flow, same status codes |
| `GitHubClient` | Full REST surface (dispatch, runs, commits, workflow listing — for triggering/tracking workflow runs) | Trimmed to `get_user()` only; the request/retry/backoff scaffold is unchanged so future endpoints (§6) drop in the same way |
| Persistence | SQLite (`aiosqlite`), `create_all` + manual `ALTER TABLE` migrations | Postgres (`asyncpg`), Alembic-migrated (backend prompt §2 explicitly requires this — "not a throwaway single file") |
| Cache | none | Redis client + `/api/health` check added (backend prompt §2/§5 require Redis; not used for auth itself, just wired up so the app boots to spec) |

## Verifying it

```bash
cd backend
uv sync
cp .env.example .env   # fill in ENCRYPTION_KEY / DATABASE_URL / REDIS_URL
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

```bash
curl localhost:8000/api/health
# {"status":"ok","db":"connected","cache":"connected"}

curl localhost:8000/api/settings
# {"pat_set":false,"github_actor_login":null,"github_api_version":"2022-11-28","github_api_base":"https://api.github.com"}

curl -X PUT localhost:8000/api/settings -H 'Content-Type: application/json' \
  -d '{"github_pat":"ghp_..."}'
# on a valid PAT: {"pat_set":true,"github_actor_login":"<your-login>", ...}
# on an invalid PAT: HTTP 400 {"detail":"Invalid GitHub PAT: ..."}
```

This was also exercised as a full local smoke test during development
(real Postgres 16 + Redis, a live `uvicorn` process, and a real PAT
validated against the live GitHub API) in addition to the automated test
suite below.

Automated coverage: `uv run pytest` (`tests/test_settings_api.py`,
`tests/test_github_client.py`, `tests/test_health.py`) — GitHub REST is
mocked (`httpx.MockTransport`), DB/cache run against real local Postgres +
Redis. `uv run ruff check .` and `uv run mypy app` both pass clean.

## Non-goals (unchanged from the backend prompt)

No OAuth, no multi-user auth, no per-request credentials — one PAT for the
whole deployment, exactly as specified in §15. Anything beyond that (e.g.
GitHub App auth, user-scoped tokens) is out of scope unless the prompt
changes.
