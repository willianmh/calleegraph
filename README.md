# Calleegraph

**A complete, static picture of how your GitHub Actions workflows call each other.**

Once an org's Actions usage grows past a handful of workflows, nobody can
answer "what calls what" with confidence. Workflows call reusable workflows,
which call other reusable workflows, sometimes across repos. A caller passes an
input the callee no longer declares; a callee starts requiring an input no
caller passes. Nothing catches it until a run fails.

Calleegraph registers your repos, fetches every workflow file, statically
parses which jobs call which reusable workflows — including how each caller's
`with:` inputs map onto the callee's declared `workflow_call` inputs, and what
`if:` conditions gate each call — and renders it as one interactive dependency
graph across every repo you've added.

It is **read-only analysis**. It never dispatches a workflow, never edits a
file, never opens a PR.

---

## Prerequisites

- **Docker** and Docker Compose.
- **A GitHub Personal Access Token** with `repo` (or fine-grained
  `contents:read`) scope, to read **private** repos. Public repos work without
  one, but at a much lower rate limit — you'll want a PAT either way.

## Quick start

```bash
cp .env.example .env
```

Generate the encryption key that protects your PAT at rest and put it in `.env`
as `ENCRYPTION_KEY`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Then:

```bash
docker compose up --build
```

Open **http://localhost:8080**, go to **Repositories**, paste your GitHub PAT,
and add a repo as `owner/name`. Its status moves through
`pending → fetching → parsing → done` live — no refreshing. Then open **Graph**.

You can also set `GITHUB_PAT` in `.env` to bootstrap the token instead of
pasting it in the UI. Either way it is encrypted before it's stored and is
never returned by any endpoint.

## How to read the graph

**Nodes** are workflow files. **Edges** are workflow-to-workflow calls — one
job's `uses:` pointing at a reusable workflow. Plain marketplace actions
(`actions/checkout@v4`) are deliberately not graphed; they'd bury the signal.

- **Density adapts to size.** A small graph auto-expands to show job names and
  key inputs. A large one collapses into grouped, counted nodes so the canvas
  stays scannable. Click any node to expand it and see its real jobs, their
  `needs`/`condition`, and the actual `with:` mapping against the target's
  declared inputs.
- **Hover a node** to highlight what it calls and what calls it, dimming
  everything else.
- **Edge colors mean exactly one thing each:**

| Edge | Meaning |
|---|---|
| Normal | `ok` — the call resolves and its inputs validate. |
| **Amber** | `warning` — suspicious but not necessarily wrong, e.g. an `if:` referencing something that doesn't appear to exist. |
| **Red** | `error` — a real validation failure: an unknown input, a missing required input, or a type mismatch. Hover or click it to see the specific problem and a suggested fix. |
| **Dashed grey** | `unresolved` — *not* an error. Calleegraph simply has no data for the target yet, usually because that repo isn't tracked. Add it under Repositories and the edge resolves. |

The distinction between **red** and **dashed grey** is the one worth
internalizing: red means *your workflow is broken*, grey means *we haven't
looked at the target yet*.

## Architecture

```
                                      ┌────────────┐
                                      │  Postgres  │  repositories, parsed
                                      │            │  nodes / jobs / calls
                                      └─────▲──────┘
                                            │
┌──────────────┐   HTTP + SSE   ┌────────────┴────────────┐        ┌──────────────┐
│   Frontend   │◄──────────────►│         Backend         │◄──────►│  GitHub REST │
│ React + Vite │   /api/*       │   FastAPI (async)       │ httpx  │  trees/blobs │
│  served by   │                │  fetch → parse → graph  │        └──────────────┘
│    nginx     │                └────────────┬────────────┘
└──────────────┘                             │
    :8080                                    ▼
                                      ┌────────────┐
                                      │   Redis    │  parsed-file cache +
                                      │            │  assembled-graph cache
                                      └────────────┘
```

Adding a repo returns immediately; the fetch and parse run as background
asyncio tasks, and progress reaches the browser over a single Server-Sent
Events stream. Redis is a cache here, not a queue.

## Development (without Docker)

Start the two datastores, then run each half natively:

```bash
docker compose up -d postgres redis
```

**Backend** (Python 3.12+, [uv](https://docs.astral.sh/uv/)):

```bash
cd backend
cp .env.example .env          # point DATABASE_URL / REDIS_URL at localhost
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

**Frontend** (Vite dev server proxies `/api` to the backend):

```bash
cd frontend
npm install
npm run dev
```

Quality gates:

```bash
cd backend  && uv run ruff check . && uv run mypy app && uv run pytest
cd frontend && npx tsc --noEmit && npm run lint && npm run format:check
```

## Known limitation (v1)

**Calleegraph tracks one ref per repo: its current default-branch HEAD.**

A call resolves only when the target repo is tracked *and* the `@ref` in the
`uses:` string matches that repo's synced default-branch commit or branch name
(or is omitted, for same-repo calls). A call pinned to a tag, a SHA, or another
branch stays `unresolved` — its raw reference is still shown so you can see
what it points at. Multi-ref fetching is future work, not a bug.

## Security

- The PAT is encrypted at rest with Fernet, is never logged, and is never
  returned by any endpoint — the API exposes only a `pat_set` boolean.
- Calleegraph needs read access only. It has no write access to your repos
  beyond reading file contents.
- **It ships with no authentication**, by design — it's a single-user, local
  tool. Don't deploy it publicly as-is.

## Project status

See [`PROGRESS.md`](PROGRESS.md) for what's built and verified, and the
per-half work logs in `backend/WORKLOG.md` and `frontend/WORKLOG.md`.

- [`backend/README.md`](backend/README.md) — backend setup and local dev.
- [`docs/github-authentication.md`](docs/github-authentication.md) — how the
  backend authenticates to GitHub and protects the PAT.
