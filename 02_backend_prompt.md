# Calleegraph — Backend Implementation Prompt

> **Status:** GitHub PAT authentication is implemented — see [PR #1](https://github.com/willianmh/calleegraph/pull/1), `backend/WORKLOG.md`, and `docs/github-authentication.md`. This covers the `settings` table, PAT encryption/validation, `GET`/`PUT /api/settings`, and `GET /api/health` (all of §3, §4's `settings` table, and §5's Settings + Health sections below). Everything else in this prompt — repository registration, workflow discovery/parsing, graph assembly, and SSE — is not yet built. A fresh session should read `backend/WORKLOG.md` before starting, per §13.

You are a senior Python engineer. Build the **backend** for **Calleegraph**, a tool that statically analyzes GitHub Actions workflows across one or more repos and exposes a combined dependency graph of which workflow calls which reusable workflow — including input wiring and conditional gating — so a frontend can render it interactively.

Build only the backend. The frontend (React/Vite/TS/Tailwind) and the docker-compose glue are separate deliverables; conform exactly to the API contract below so they drop in cleanly.

---

## 1. What this tool does (domain)

The pain being solved: as an org's GitHub Actions usage grows, workflows call reusable workflows which call other reusable workflows — sometimes across repos — and nobody has a full picture of the graph. A caller can pass an input the callee no longer declares, or a callee can require an input the caller never learned to pass, and nothing catches it until a run fails. Calleegraph fixes this by:

1. Letting the user **register a repo**, then discovering every workflow file in it via the GitHub API — no manual file listing.
2. **Parsing each workflow statically** (no execution) to classify it as top-level or reusable (`on.workflow_call`), and to extract its jobs, each job's `uses:` target (if it calls a reusable workflow), the `with:` input mapping, the gating `if:` condition, and intra-workflow `needs:` dependencies.
3. **Resolving calls into a graph**: when a job's `uses:` targets a workflow in a tracked repo (at a ref Calleegraph has actually fetched), wire it to that workflow's node; otherwise mark the edge `unresolved` and keep the raw reference visible.
4. **Validating** each resolved call against the callee's declared inputs — unknown inputs, missing required inputs, type mismatches, and conditions that reference something that doesn't exist — producing specific, actionable issues rather than a bare "broken" flag.
5. **Caching and serving** the combined graph across all currently tracked repos, and keeping it live via SSE as repos are added, removed, or re-synced.

---

## 2. Tech constraints (non-negotiable)

- **Python 3.12+**, dependency + venv management with **uv** (`pyproject.toml` + `uv.lock`, no `requirements.txt`).
- **FastAPI** (async) for the API.
- **SQLModel** over **PostgreSQL** for persistence, async access via `asyncpg`. Use **Alembic** for migrations — this is a real multi-user-capable database, not a throwaway single file, so don't rely on create-all in place of migrations.
- **Redis** for caching: (a) parsed per-file workflow data keyed by `(repository_full_name, commit_sha, path)`, and (b) the fully-assembled `GraphResponse` keyed by a hash of all tracked repos' current commit SHAs. `GRAPH_CACHE_TTL_SECONDS` is a safety-net expiry only — the primary invalidation path is explicit, on any repository state change (see §10).
- Direct GitHub REST calls (repo tree listing, blob/content fetch, repo metadata) via **httpx** (async). No GraphQL requirement, but it's an acceptable substitute for tree listing if you prefer — REST is the documented default here.
- Workflow parsing with **PyYAML** (or `ruamel.yaml` if you need round-trip fidelity for future features — not required for v1, plain PyYAML is fine).
- Background fetch/parse work uses **plain asyncio tasks** kicked off per repository — **no Celery, no external queue**. Redis here is a cache, not a broker.
- Real-time updates via a single **Server-Sent Events** stream.
- Runs in **Docker**; provide a `Dockerfile`. Configuration via env vars only (12-factor).
- Type-checked and linted: **ruff** and **mypy** (or pyright); pass cleanly.
- Tests with **pytest** (+ `pytest-asyncio`); GitHub calls mocked (use fixture YAML files representing real workflow shapes, including malformed/edge-case ones).

---

## 3. Configuration (env vars)

> ✅ **Implemented** — `backend/app/config.py`. All rows below are read as documented, via `pydantic-settings`.

Read via a `pydantic-settings` `Settings` object, with sensible defaults documented in code.

| Var | Required | Default | Purpose |
|---|---|---|---|
| `GITHUB_PAT` | no | — | Bootstrap PAT; if set and DB has none, seed settings with it |
| `GITHUB_API_VERSION` | no | `2022-11-28` | Sent as `X-GitHub-Api-Version` |
| `GITHUB_API_BASE` | no | `https://api.github.com` | Allows GitHub Enterprise |
| `ENCRYPTION_KEY` | yes | — | Fernet key; encrypts the PAT at rest in Postgres |
| `DATABASE_URL` | yes | — | `postgresql+asyncpg://...` |
| `REDIS_URL` | yes | — | Cache backend |
| `GRAPH_CACHE_TTL_SECONDS` | no | `300` | Safety-net expiry for the assembled-graph cache |
| `FETCH_CONCURRENCY` | no | `3` | Max repos fetched/parsed concurrently |
| `CORS_ORIGINS` | no | `http://localhost:5173` | Frontend origin(s) |

The PAT must be **encrypted at rest** (Fernet) and never returned by any API — only a `pat_set: bool` flag is exposed.

---

## 4. Data model (SQLModel tables, Postgres, Alembic-migrated)

**settings** (singleton, id=1) — ✅ **Implemented** — `backend/app/models.py`, migrated by `backend/alembic/versions/0001_create_settings_table.py`.
- `github_pat_encrypted: str | None`
- `github_actor_login: str | None` — cached from `GET /user` when a PAT is validated
- `github_api_version: str`
- `github_api_base: str`
- `updated_at: datetime`

**repository** — not yet built.
- `id: int pk`
- `owner: str`, `name: str`, `full_name: str` (unique)
- `default_branch: str`
- `status: enum` — `pending` | `fetching` | `parsing` | `done` | `error`
- `error: str | None`
- `last_synced_commit_sha: str | None`
- `last_synced_at: datetime | None`
- `created_at`

**workflow_node** (parsed workflow, one row per file per repo, reflecting the last successfully synced commit) — not yet built.
- `id: str pk` — `f"{repository_full_name}/{path}"`
- `repository_id: int fk`
- `path: str`, `name: str`
- `kind: enum` — `top_level` | `reusable` (reusable iff `on.workflow_call` is present)
- `triggers: JSONB` — list of trigger keys under `on`
- `declared_inputs: JSONB` — `WorkflowIODef[]` from `on.workflow_call.inputs`; `[]` if not reusable
- `declared_secrets: JSONB` — list of secret names from `on.workflow_call.secrets`
- `declared_outputs: JSONB` — `WorkflowIODef[]` from `on.workflow_call.outputs`
- `source_commit_sha: str`
- `updated_at`

**job** — not yet built.
- `id: str pk` — `f"{workflow_node_id}#{job_key}"`
- `workflow_node_id: str fk`
- `job_key: str`, `name: str | None`
- `needs: JSONB` — list of sibling `job_key`s
- `condition: str | None` — the job's `if:`

**job_call** (present only when the job's `uses:` targets a reusable workflow, not a plain action) — not yet built.
- `id: int pk`
- `job_id: str fk` (1:1 with job)
- `target_ref: str` — the raw `uses:` string, always kept even if unresolved
- `target_node_id: str | None fk` — resolved `workflow_node.id`, null if unresolved
- `with_mapping: JSONB` — `{ input_name: raw_expression_or_literal }`
- `secrets_mode: enum` — `inherit` | `explicit` | `none`
- `secrets: JSONB | None` — explicit secret names, if `secrets_mode = explicit`

Validation issues (`EdgeIssue[]`) are **not persisted** — they're computed deterministically at graph-assembly time (§11) from the tables above, and cached only as part of the assembled `GraphResponse` in Redis. Don't add an issues table; recompute instead.

---

## 5. REST API contract (canonical — frontend depends on this)

All routes under `/api`. JSON in/out. Return appropriate 4xx with `{ "detail": "..." }` on error.

### Settings — ✅ Implemented (`backend/app/routers/settings.py`)
- `GET /api/settings` → `{ pat_set, github_actor_login, github_api_version, github_api_base }`
- `PUT /api/settings` → body `{ github_pat?, github_api_version?, github_api_base? }`. When a PAT is supplied, validate it via `GET /user`; on success store it encrypted and cache `github_actor_login`. Auth failures → `400` with a clear detail.

### Repositories — not yet built
- `GET /api/repositories` → `Repository[]`
- `POST /api/repositories` → body `{ full_name: string }` (`owner/name`). Validate the repo is reachable; `409` if already registered. Creates the row with `status="pending"` and **immediately returns** it, then kicks off the background fetch/parse task (§10). Returns the created `Repository`.
- `DELETE /api/repositories/{id}` → cascades deletion of its `workflow_node`/`job`/`job_call` rows, invalidates the graph cache, returns `204`.
- `POST /api/repositories/{id}/refresh` → re-checks the remote default branch HEAD; if it moved (or `force=true` query param), re-runs fetch/parse. Returns the updated `Repository`.

`Repository = { id, owner, name, full_name, default_branch, status, error, last_synced_commit_sha, last_synced_at, created_at }`

### Graph — not yet built
- `GET /api/graph` → assembles (or serves from cache) the combined graph across all tracked repos and returns `GraphResponse` (see §11 for assembly logic).

`GraphResponse = { repositories: Repository[], nodes: WorkflowNode[], edges: Edge[], generated_at: string }`

(`WorkflowNode`, `JobNode`, `JobCall`, `Edge`, `EdgeIssue`, `WorkflowIODef` — exact shapes as defined in the Orchestrator Prompt §5; implement those verbatim, they are not repeated here to avoid drift.)

### Live updates (SSE) — not yet built
- `GET /api/events/stream` → `text/event-stream`, one connection serves both:
  - event `repository_updated`, `data` = full `Repository` JSON — emitted on every status transition for any repo.
  - event `graph_updated`, `data` = full `GraphResponse` JSON — emitted whenever the assembled graph changes (i.e. whenever any repo finishes a sync in either direction, `done` or `error`, or a repo is removed).
  Also emit periodic `: keepalive` comments. The frontend keeps one global subscription and upserts/replaces by id.

### Health — ✅ Implemented (`backend/app/main.py`)
- `GET /api/health` → `{ status: "ok", db: "connected"|"unavailable", cache: "connected"|"unavailable" }`

---

## 6. Workflow discovery

For a repository at its current default-branch HEAD:
1. `GET /repos/{owner}/{repo}/git/trees/{sha}?recursive=1` (one call) to list every file in the repo at that commit.
2. Filter paths matching `.github/workflows/*.yml` and `*.yaml`.
3. Fetch each matched file's content — either via the blob SHA from the tree response (`GET /repos/{owner}/{repo}/git/blobs/{blob_sha}`, base64-decoded) or the contents API. Prefer the tree+blob path since it's already enumerated and avoids one request per directory listing.

Do not walk directories one at a time with the contents API — that's an easy way to blow through rate limits on repos with many workflow files.

---

## 7. Workflow parsing

For each fetched file, parse YAML defensively — `on:` may be a string, a list, or a map; `workflow_call`/`workflow_dispatch` may be `null` (no inputs) or absent entirely. For each job in `jobs:`:
- `needs:` may be a string or a list — normalize to a list.
- `if:` — keep the raw expression string as-is; don't attempt to evaluate it, only to check the names it references (§9).
- `uses:` — only treat it as a **workflow call** (populate `job_call`) if it points at a workflow file path (`.../.github/workflows/....yml@ref`), whether same-repo (`./.github/workflows/x.yml`) or cross-repo (`owner/repo/.github/workflows/x.yml@ref`). A `uses:` pointing at a plain action (e.g. `actions/checkout@v4`) is not graphed in v1 — leave `job.call = null` for those jobs.
- `with:` under a workflow-calling job → `with_mapping`, keeping values as raw strings (including unresolved `${{ }}` expressions) rather than attempting expression evaluation.
- `secrets:` → `inherit` (literal string), an explicit map (→ `secrets_mode="explicit"`, list the names), or absent (→ `"none"`).

For a workflow with `on.workflow_call` present, also parse `inputs`, `outputs`, and `secrets` under it into `declared_inputs` / `declared_outputs` / `declared_secrets`, mapping GitHub's input types faithfully (`choice` → populate `options`, `boolean`/`number`/`string` as-is).

A single malformed workflow file must not fail the whole repo sync: catch parse errors per file, skip that file with a logged warning, and continue with the rest.

---

## 8. Cross-repo / cross-ref resolution (documented v1 limitation)

Calleegraph fetches and parses **one ref per tracked repo**: its current default-branch HEAD. When resolving a `job_call.target_ref`:
- If the target repo (parsed from the `uses:` string) is currently tracked **and** the `@ref` in the string matches that repo's `last_synced_commit_sha`, its branch name, or is omitted (implicitly same-repo) — resolve `target_node_id` to that workflow's node.
- Otherwise (target repo not tracked, or pinned to a tag/SHA/branch different from what's currently synced) — leave `target_node_id = null`; the edge is `unresolved`, and `target_ref` is preserved so the UI can still show what it points at.

This is a known v1 scope boundary, not a bug: multi-ref fetching per repo is future work. Document it plainly in code comments and surface it in the README (owned by the orchestrator).

---

## 9. Validation rules (produce `EdgeIssue[]` per edge)

Only evaluated when `target_node_id` is resolved (an `unresolved` edge doesn't get these — it gets `status="unresolved"` and no issues, since there's nothing to validate against yet):

- **`unknown_input`**: a key in `with_mapping` that isn't in the callee's `declared_inputs`. Suggestion: if a declared input name is a close string match (e.g. Levenshtein distance ≤ 2), suggest it by name ("Did you mean `environment`?"); otherwise suggest removing the key.
- **`missing_required_input`**: a `declared_inputs` entry with `required=true` and no `default` that isn't present in `with_mapping`. Suggestion names the exact missing input.
- **`type_mismatch`**: `with_mapping`'s value is a literal (not a `${{ }}` expression) and doesn't match the declared type (e.g. a non-boolean literal for a `boolean` input, or a value outside `options` for a `choice` input). Skip this check when the value is an unresolvable runtime expression — don't guess.
- **`unresolvable_condition`**: the job's `if:` (or the calling job's own condition) references `needs.<job_key>.outputs.<x>` where `job_key` isn't in this workflow's jobs, or `inputs.<x>` where `x` isn't in this workflow's own `declared_inputs` (only meaningful if this workflow is itself reusable). Severity `warning`, not `error` — it's suspicious, not necessarily wrong (the expression parser is intentionally simple, not a full GitHub Actions expression evaluator).

Set `edge.status`: `"error"` if any issue has `severity="error"`, else `"warning"` if any issue has `severity="warning"`, else `"ok"`. `"unresolved"` is set independently of issues, per §8.

---

## 10. Background fetch/parse flow

One asyncio task per repository, launched on `POST /api/repositories` and on `.../refresh`:

1. `status = "fetching"` → emit `repository_updated`. List + download workflow files (§6).
2. `status = "parsing"` → emit `repository_updated`. Parse each file (§7), upsert `workflow_node`/`job`/`job_call` rows for this repo, replacing its previous rows in a transaction (so a failed sync doesn't leave a half-updated state).
3. On success: `status = "done"`, set `last_synced_commit_sha`/`last_synced_at`, emit `repository_updated`, invalidate the graph cache, recompute and emit `graph_updated`.
4. On any exception: `status = "error"`, set `error` to a specific message, emit `repository_updated` — but **do not delete** previously-good `workflow_node`/`job`/`job_call` rows from an earlier successful sync, so a transient failure doesn't blank out an already-working part of the graph.

`FETCH_CONCURRENCY` caps how many of these tasks run at once (a simple `asyncio.Semaphore`).

---

## 11. Graph assembly (`GET /api/graph`)

1. Check Redis for a cached `GraphResponse` keyed by a hash of all tracked repos' `last_synced_commit_sha` (repos still `pending`/`fetching`/`parsing` don't have a SHA yet and are simply included in `repositories` with their current status, contributing no nodes yet). If present and unexpired, return it.
2. Otherwise: load all `workflow_node`/`job`/`job_call` rows for repos with a `last_synced_commit_sha`, resolve each `job_call` (§8), run validation (§9) to build `Edge[]`, assemble `GraphResponse`, cache it in Redis with `GRAPH_CACHE_TTL_SECONDS`, and return it.

---

## 12. Project layout

> ✅ Everything under `app/` marked below with a leading `✓ ` exists today (auth slice only); the rest of this tree is still to be built.

```
backend/
├── Dockerfile                 ✓
├── pyproject.toml             ✓
├── uv.lock                    ✓
├── .dockerignore               ✓
├── alembic/                    ✓ (versions/0001_create_settings_table.py only)
│   └── versions/
├── app/
│   ├── main.py            # FastAPI app, lifespan wiring          ✓
│   ├── config.py          # pydantic-settings                     ✓
│   ├── db.py              # async engine/session                  ✓
│   ├── crypto.py          # Fernet encrypt/decrypt for PAT        ✓
│   ├── models.py          # SQLModel tables (settings only so far) ✓
│   ├── schemas.py         # pydantic request/response models (contract types) ✓ (Settings/Health only)
│   ├── events.py          # SSE broker (async pub/sub)
│   ├── cache.py           # Redis client + graph-cache helpers    ✓ (connection + health check only)
│   ├── github/
│   │   ├── client.py      # httpx REST client (trees, blobs, repo metadata) ✓ (get_user only so far)
│   │   └── parse.py       # YAML → WorkflowNode/Job/JobCall
│   ├── graph/
│   │   ├── resolve.py     # cross-repo/ref resolution
│   │   ├── validate.py    # EdgeIssue rules
│   │   └── assemble.py    # builds GraphResponse from DB rows
│   ├── sync.py             # per-repo async fetch/parse task
│   └── routers/
│       ├── settings.py     ✓
│       ├── repositories.py
│       ├── graph.py
│       └── events.py       # /api/events/stream
└── tests/
    ├── conftest.py          ✓
    ├── fixtures/            # sample workflow YAML, incl. malformed cases
    ├── test_parse.py
    ├── test_resolve.py
    ├── test_validate.py
    ├── test_sync_flow.py
    └── test_api.py          ✓ (test_settings_api.py, test_github_client.py, test_health.py)
```

---

## 13. Progress tracking (`backend/WORKLOG.md`)

This build may be interrupted and resumed across sessions. Maintain `backend/WORKLOG.md`, append-only — never edit or delete a past entry. Add a new entry at the end of every work session (at minimum, after each major checkpoint: discovery/fetch working, parsing working, validation rules working, API endpoints complete, tests green):
```
## [YYYY-MM-DD HH:MM] <short title>
- Did: <what was actually built/changed, with file paths>
- Deviated: <any deviation from this prompt, and why — or "none">
- Blocked: <an open question or blocker for the orchestrator — or "none">
- Next: <the concrete next step, specific enough that a fresh session can resume without re-reading the whole codebase>
```
Before starting or resuming any work, read your own `WORKLOG.md` (at least the last few entries) and the root `PROGRESS.md` first, and state which entry's `Next` you're resuming from. Do not silently redo or contradict work a past entry says is done — if you believe a past entry was wrong, say so explicitly in your new entry rather than overwriting history. Flag anything that affects the shared contract (§5) as `Blocked` for the orchestrator rather than resolving it unilaterally.

A first entry already exists, covering the GitHub authentication slice (§3, the `settings` table in §4, and the Settings + Health sections of §5) — read it before resuming.

## 14. Acceptance criteria

- `uv sync` then `uv run uvicorn app.main:app` boots; `GET /api/health` reports db and cache connected. — ✅ done
- Registering a repo with a valid PAT discovers its workflows, and `GET /api/graph` reflects them once `status="done"`. — not yet built (repository registration/discovery)
- A repo whose workflow calls a reusable workflow in another tracked repo resolves to a real edge once both are synced; the same call before the second repo is added renders `status="unresolved"`. — not yet built
- A deliberately mismatched input (unknown key, or missing required input) produces an `Edge` with `status="error"` and an `EdgeIssue` whose `suggestion` names the correct input. — not yet built
- A malformed workflow file in one repo doesn't prevent the rest of that repo's (or any other repo's) workflows from parsing. — not yet built
- The PAT is never returned by any endpoint; it's encrypted at rest. — ✅ done
- `ruff`, `mypy`/pyright, and `pytest` pass. GitHub calls are mocked in tests. — ✅ true for the code that exists today (auth slice); re-verify as each new slice lands
- `docker build` succeeds; container runs against the documented env vars, migrating on startup. — ✅ done for the current (auth-only) app; re-verify once repositories/graph land

## 15. Non-goals (v1)

No execution or dispatch of any workflow — read-only static analysis. No multi-ref fetching per repo (§8 limitation is intentional). No graphing of plain marketplace-action `uses:` steps, only workflow-to-workflow calls. No auto-fix / PR creation for detected issues — surface them only. No auth beyond the single stored GitHub PAT.
