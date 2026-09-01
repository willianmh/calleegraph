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

## [2026-08-31 20:55] Repositories, discovery/parsing, graph assembly, SSE

Resumed from the previous entry's `Next`: "repository registration + workflow
discovery (§6, `POST/GET/DELETE /api/repositories`, `app/github/client.py`
needs `get_repo`, tree listing, and blob fetch added)", and carried on through
the rest of the backend. Contract shapes come from `03_orchestrator_prompt.md`
§5 (authoritative), not from §5 of the backend prompt.

- Did:
  - `app/models.py` — `repository`, `workflow_node`, `job`, `job_call` tables
    (§4) with Postgres native enums (`repo_status`, `node_kind`,
    `secrets_mode`), `JSONB` for the list/map columns, and `ON DELETE CASCADE`
    from repository → workflow_node → job → job_call. No issues table:
    `EdgeIssue[]` is recomputed at assembly time, as §4 requires.
  - `alembic/versions/0002_create_graph_tables.py` — migration for the above.
    Verified `upgrade`/`downgrade`/`upgrade` round-trips and that
    `alembic check` reports no drift against the models.
  - `app/services.py` — the cleanup the last entry called for: `get_settings_row`
    moved out of `app/routers/settings.py`, joined by `stored_pat()` and
    `make_github_client()`, now that repo sync is a second consumer. The
    settings router imports it instead of owning it; no router imports another
    router.
  - `app/github/client.py` — extended (not rewritten) with `get_repo`,
    `get_branch_head_sha`, `get_tree` (recursive), `get_blob_text`
    (base64-decoding). Also made `token` optional so public repos work
    unauthenticated at a lower rate limit; the existing retry/backoff and PAT
    validation paths are untouched.
  - `app/github/parse.py` — defensive YAML parsing (§7): `on:` as string /
    list / map, `workflow_call: null` still meaning reusable, `needs:` as
    string or list, `choice` options, `secrets: inherit|explicit|none`,
    `uses:` classified as workflow-call vs. plain action, `with:` values kept
    raw. Handles PyYAML resolving a bare `on:` to the boolean `True`
    (YAML 1.1) as well as a quoted `"on"`. Malformed files raise
    `WorkflowParseError` for the sync loop to skip per file.
  - `app/graph/resolve.py` — §8 resolution, with the v1 one-ref-per-repo
    limitation spelled out in the module docstring and enforced by
    `ref_is_current` (omitted ref / default branch / synced SHA resolve; tags,
    other branches, other SHAs do not).
  - `app/graph/validate.py` — §9 rules: `unknown_input` (with Levenshtein ≤ 2
    "Did you mean `x`?" naming the real declared input), `missing_required_input`,
    `type_mismatch` (boolean/number/choice, skipped for `${{ }}` values),
    `unresolvable_condition` (warning). `edge_status()` keeps `unresolved`
    independent of issues.
  - `app/graph/assemble.py` + `app/graph/service.py` — §11 assembly, resolving
    and validating on every build so cross-repo edges stay correct as repos
    come and go, plus the cached/publish wrappers.
  - `app/cache.py` — both caches from §2: parsed-file cache keyed by
    `(full_name, commit_sha, path)` and the assembled-graph cache keyed by a
    hash of tracked repos' SHAs. Every Redis call degrades to a miss on
    outage. `invalidate_graph_cache()` is called explicitly on every repo
    state change, with the TTL as a safety net only.
  - `app/events.py` + `app/routers/events.py` — in-process SSE broker and
    `GET /api/events/stream`; one connection serves both event types, plus
    `: keepalive` comments. Publishing is non-blocking and drops on a full
    subscriber queue rather than stalling a sync.
  - `app/sync.py` — §10 background task: `FETCH_CONCURRENCY` semaphore, status
    transitions each emitting `repository_updated`, one recursive tree call
    per repo, bounded parallel blob fetches, per-file parse tolerance, and
    row replacement in a single transaction. Every error path leaves the last
    successful sync's rows untouched.
  - `app/routers/repositories.py`, `app/routers/graph.py`, `app/main.py` —
    `GET/POST /api/repositories`, `DELETE /api/repositories/{id}`,
    `POST /api/repositories/{id}/refresh`, `GET /api/graph`, all wired in.
  - `app/schemas.py` — every contract type from orchestrator §5 verbatim.
    `JobCall.with_mapping` is aliased to `with` on the wire (confirmed in the
    generated OpenAPI schema).
  - Tests (102 passing): `tests/test_parse.py`, `test_resolve.py`,
    `test_validate.py`, `test_sync_flow.py`, `test_api.py`, plus
    `tests/fixtures/*.yml` including three malformed/degenerate files.
  - `tests/repos.py` + `tests/test_contract_scenario.py` — **the synthetic
    stand-in for the three §2.2 contract-verification repos**, added at the
    orchestrator's request since no live test PAT is available. A synthetic
    four-repo GitHub (`acme/website` top-level-only, `acme/platform` hosting
    the reusable callee, `acme/services` cross-repo caller + a malformed file,
    `acme/broken` with a broken input mapping) served over
    `httpx.MockTransport`. One readable scenario test walks the whole
    orchestrator §11.2 demo: unresolved-before / resolved-after registering
    the target repo, the error edge whose suggestion names `environment` by
    name, deletion flipping edges back to `unresolved` (never `error`), the
    malformed file not stopping anything, and stable `node.id`/`edge.id`
    across a re-sync. A second test asserts the PAT appears in no response.
  - `backend/README.md` — endpoint table, the v1 resolution limitation, and a
    pointer to the scenario test as the executable contract.
- Verified locally (real output in the handoff): `uv sync`, `uv run ruff check .`
  (clean), `uv run mypy app` (clean, 24 files), `uv run pytest` (102 passed),
  `alembic upgrade/downgrade/upgrade` and `alembic check` against local
  Postgres 16 + Redis 7, and a live boot smoke test — `GET /api/health` both
  `connected`, `/api/repositories`, `/api/graph` and `/api/events/stream` all
  responding. No network calls in the test suite.
- Deviated:
  - `POST /api/repositories/{id}/refresh` does the remote-HEAD comparison
    *inside* the background task rather than in the request handler, so it
    returns `pending` immediately instead of blocking on a GitHub round-trip.
    The behaviour §5 describes is preserved — an unmoved HEAD goes straight
    back to `done` without re-parsing (test:
    `test_unchanged_head_short_circuits_without_reparsing`).
  - `edge.id` is `f"{source_job_id}->{target_ref}"`, deliberately *not*
    including the resolved target. §5 only requires stability across re-syncs
    of the same SHA; keying on the raw ref additionally keeps the id stable
    when an edge flips unresolved↔resolved because another repo was added or
    removed, so the frontend can animate that instead of swapping edges. Say
    the word if you'd rather it were target-derived.
  - `job_call.target_node_id` is persisted (per §4) but treated as a cache:
    §11 recomputes resolution at assembly time, which is what makes the
    cross-repo add/remove behaviour work. Its FK is `ON DELETE SET NULL`.
  - `unresolvable_condition` skips the `inputs.x` check on a reusable workflow
    that is *also* `workflow_dispatch`-triggered, since those inputs come from
    a source the model doesn't hold — a false-positive guard, not a rule change.
- Blocked:
  - **`IssueCode: "unresolved_target"` is currently never emitted.** §5 defines
    it in the `IssueCode` union, but backend prompt §9 says an unresolved edge
    "gets `status="unresolved"` and no issues". I followed §9 literally, so
    unresolved edges ship `issues: []` and that code is unused. If the frontend
    would rather render an explanatory issue ("register `acme/platform` to
    resolve this call"), say so and I'll emit one — it's a one-line change and
    `edge.status` stays `"unresolved"` either way. Flagging rather than
    deciding, since it's a §5 surface.
  - **`docker build ./backend` could not be verified in this session.** Docker
    build containers here have no outbound network (`tls handshake eof`
    fetching wheels from PyPI); a trivial control image that curls pypi.org
    fails the same way, so it is the environment, not the Dockerfile. What I
    could verify: `uv sync --frozen --no-dev` — the exact command the failing
    layer runs — succeeds locally against the committed `uv.lock`, and the only
    dependency change this session is adding `pyyaml`. Please re-run the image
    build on a networked machine before flipping that box.
- Next: nothing outstanding in the backend prompt — §5's endpoints, §6–§11 and
  §12's test list are all implemented and green. The remaining backend item on
  `PROGRESS.md` is contract verification against real repos with a real PAT
  (orchestrator-owned); `tests/test_contract_scenario.py` now covers the same
  ground against mocked GitHub. If a live PAT arrives, the useful follow-up is
  a manual run of that same scenario against three real repos to confirm the
  GitHub response shapes the mock assumes (tree `truncated`, blob encoding,
  `git/ref/heads/{branch}` payload) match production.
