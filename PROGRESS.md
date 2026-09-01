# Calleegraph — build progress

Orchestrator-owned. **Worker agents never edit this file** — they append to
`backend/WORKLOG.md` / `frontend/WORKLOG.md`, and the orchestrator reconciles
those into this checklist.

A box is `[x]` only when the orchestrator **verified** it, not when an agent
claimed it. Read this file first when resuming after an interruption.

Authoritative contract: `03_orchestrator_prompt.md` §5. If a worker's log and
§5 disagree, §5 wins and the correction is logged here.

---

## Build order (orchestrator prompt §2)

- [x] Scaffold monorepo: `docker-compose.yml`, `.env.example`, root `README.md` skeleton, `PROGRESS.md` — 2026-08-31, written by orchestrator; compose references `./frontend`, which the frontend agent creates.
- [x] **Backend** — feature-complete. Gates re-verified independently by the orchestrator on 2026-09-01: `ruff` clean, `mypy` clean (24 files), `pytest` **109 passed**. The `unresolved_target` ruling has fully landed.
  - [x] Settings + health + PAT encryption/validation — verified in PR #1, `backend/WORKLOG.md` entry 2026-08-31 19:45.
  - [x] `POST/GET/DELETE /api/repositories` + `/refresh` — built; orchestrator re-ran ruff/mypy/pytest independently 2026-08-31.
  - [x] Workflow discovery (trees + blobs) and defensive YAML parsing — `app/github/{client,parse}.py`; 3 malformed fixtures covered.
  - [x] Cross-repo/ref resolution + validation rules — `app/graph/{resolve,validate}.py`, incl. Levenshtein≤2 suggestions.
  - [x] `GET /api/graph` with Redis caching + explicit invalidation — `app/graph/{assemble,service}.py`.
  - [x] `GET /api/events/stream` SSE — `app/events.py` + `app/routers/events.py`; live-boot smoke-tested.
  - [x] Contract verified against a **synthetic** repo set via mocked GitHub — `tests/repos.py` + `tests/test_contract_scenario.py` walk the whole §11.2 demo. Orchestrator re-ran the suite: **102 passed**.
  - [ ] Live contract verification against real GitHub repos — **deferred**, open for the user to run when credentials exist.
  - [x] `unresolved_target` emitted per the orchestrator ruling; `edge.status` stays `"unresolved"`, pinned by regression tests. Suite grew 102 → **109 passed**.
- [x] **Design import** — resolved 2026-08-31: the user exported the project as a local handoff bundle at `canvas-requirements-clarification/`. Verified byte-identical (sha256) to what DesignSync returns for `Calleegraph.dc.html` and `support.js`. No MCP or network access is needed to read the design any more. Design system is **Broadsheet** (Source Serif 4 on paper ground, cyan/magenta process accents, whitespace-not-boxes).
- [x] **Frontend** — built against the local design bundle; finished by the orchestrator after the agent hit a session rate limit. Gates verified independently 2026-09-01: `tsc --noEmit` clean, `eslint` **0 problems**, `prettier --check` clean, `npm run build` succeeds. `nginx.conf` validated by real `nginx -t`. Both density bands and all four edge statuses exercised against the mock.
  - [x] App shell + routing + global SSE subscription — `src/{App,router,main}.tsx`, `src/lib/sse.ts`.
  - [x] Graph screen — `src/features/graph/` (density 15/40, hover, click-to-expand, four distinct edge visuals, verbatim issue copy, view state preserved by id).
  - [x] Repositories + Settings — write-only PAT confirmed by inspection (nothing reads or renders a token).
  - [x] Dockerfile + nginx.conf — SSE location ordered before generic `/api`, `proxy_buffering off`, 24h read timeouts, `X-Accel-Buffering: no`.
- [ ] **Integrate** — blocked only on `docker compose up --build`, which needs a networked machine (see Open blockers). No known contract drift: the frontend consumes §5 as written and the backend emits it.

## Definition of done (orchestrator prompt §11)

- [ ] 1. `cp .env.example .env` → `docker compose up --build` → app at `:8080`, backend healthy.
- [ ] 2. E2E demo: two repos with a cross-repo reusable call → live status transitions → resolved edge → third repo with a mismatched input → red error edge with a correct suggestion → remove a repo → its nodes vanish and dangling edges flip to `unresolved`.
- [x] 3. Density verified against the mock: 5 nodes → Detailed band, 58 nodes across 4 repos → Grouped band (`DETAILED_BELOW = 15`, `GROUPED_ABOVE = 40`, recomputed from node count).
- [x] 4. PAT never exposed — backend: no token value in any log call, `pat_set` only in responses (asserted in `test_contract_scenario.py`). Frontend: the field is write-only, never populated from the server.
- [ ] 5. Quality gates: backend `ruff`/`mypy`/`pytest` (**109 passed**) and frontend `tsc`/`eslint`/`prettier`/`build` **all green, all independently re-run 2026-09-01**. README written. Remaining: **both Docker image builds are UNVERIFIABLE here** — see Open blockers.
- [x] 6. `PROGRESS.md` + `backend/WORKLOG.md` + `frontend/WORKLOG.md` all current as of 2026-09-01, including who did what after the agents were rate-limited.

## Open blockers

- **`docker build` cannot be verified in this session — environmental, not a defect.**
  Build containers have no outbound network here. Proven with a control image:
  `FROM alpine` + `wget https://pypi.org` fails with
  `SSL routines::unexpected eof while reading` / connection reset, while the same
  fetch **from the host returns HTTP 200**. The backend image fails identically
  pulling wheels (`tls handshake eof` on files.pythonhosted.org), and any frontend
  `npm install` layer will too. Nothing about either Dockerfile is implicated.
  Mitigation: `uv sync --frozen --no-dev` — the exact failing command — succeeds on
  the host against the committed `uv.lock`. **Action for the user: run
  `docker compose up --build` on a networked machine** to close DoD items 1 and 5.
- **Live contract verification** — deferred by the user (2026-08-31). No test PAT
  available, so the backend is verified against a synthetic three-repo fixture set
  with mocked GitHub. Running orchestrator §11.2 against real repos stays open.

## Handover — what is left

1. **Run `docker compose up --build` on a networked machine.** This is the only
   thing standing between here and Definition of Done items 1 and 5. Both
   Dockerfiles are written and their non-network steps verified.
2. **Then walk the §11.2 demo** end to end in the browser at `:8080`.
3. Optional: point it at real GitHub repos with a PAT to close the deferred
   live contract verification.

Nothing is committed. Both halves are working-tree changes on `main`.

## Corrections log

- **2026-08-31 — design import path substituted.** Frontend prompt §2.1 says to
  import the design via the `claude_design` MCP (`https://api.anthropic.com/v1/design/mcp`,
  auth via `/design-login`). That MCP is **not connected** in this environment and
  adding it was not needed: after `/design-login`, the built-in **`DesignSync`**
  tool reads the same project. The frontend agent was dispatched to import via
  `DesignSync` read methods (`get_project`/`list_files`/`get_file`) on project
  `0bfa75f4-cdf4-4816-b514-02dc95df4cdb`, and explicitly forbidden from calling any
  DesignSync write method — the import is read-only and must not modify the user's
  design project. Fetched files are cached under `frontend/design-reference/`.
  Note: the project is `PROJECT_TYPE_PROJECT`, not a design system, which is why
  the design-system-oriented DesignSync write path does not apply here anyway.
  **Superseded the same day — see the next entry.**
- **2026-08-31 — design import resolved: local bundle, no MCP.** The DesignSync
  path above worked for the *orchestrator* but not for a *worker agent*: deferred
  tools are per-session, so a subagent does not inherit `DesignSync`. The first
  frontend dispatch burned a session discovering this (it also correctly found
  that `WebFetch` on `claude.ai` returns 403 and that no `claude_design` MCP is
  configured) and stopped without building. **Root cause: the orchestrator assumed
  its own toolset extended to subagents.** Resolution: the user exported the design
  as a local handoff bundle at `canvas-requirements-clarification/`, verified
  byte-identical by sha256 to the DesignSync content. `01_frontend_prompt.md` §2.1
  has been rewritten to point at the local files and to state explicitly that the
  MCP, DesignSync and WebFetch routes are all dead ends — so no future session
  re-runs that investigation. **General lesson: hand a worker agent files on disk,
  never a tool the orchestrator happens to hold.**
- **2026-09-01 — both worker agents killed mid-task by a session rate limit.**
  The backend agent died while adding the `unresolved_target` regression tests;
  the frontend agent while writing its ESLint/Prettier config. Neither left a
  worklog entry for its final stretch. The orchestrator verified the backend
  change had fully landed (109 tests pass, invariant pinned) and finished the
  frontend's quality gates by hand. `frontend/WORKLOG.md` marks which entry was
  written by the orchestrator rather than the agent, so the history stays honest
  about authorship.
- **2026-09-01 — `vitest` removed from the frontend.** `vite.config.ts` imported
  `defineConfig` from `vitest/config`; vitest 3.2.7 installs a nested vite 7 that
  collides with the root vite 8 under `exactOptionalPropertyTypes`, an error not
  fixable without a version change. No test files existed. Removed the dependency
  rather than paper over the conflict. Consequence: no frontend unit tests —
  density and edge-state behaviour is exercised through `mock/server.mjs`, which
  is how §9's acceptance criteria are phrased. **If frontend unit tests are wanted
  later, pin a vitest release that matches the installed vite major.**
- **2026-08-31 — `unresolved_target` ruled emittable (§5 over §9).** The backend
  agent correctly flagged that §5 defines `IssueCode: "unresolved_target"` while
  backend prompt §9 says an unresolved edge gets "no issues", leaving the code dead.
  **Ruling: emit it.** Frontend §4.2 requires an unresolved edge's tooltip to help
  the user go add the target repo, *and* requires issue copy to be rendered verbatim
  from the backend rather than invented client-side — so with no issue emitted, that
  requirement is unsatisfiable. §9's "no issues" means "don't run input validation
  against a callee you never parsed", which still holds. Constraint attached to the
  ruling: `edge.status` **stays `"unresolved"`** and must not roll up to `"warning"`,
  with a regression test pinning it, since that would collapse the §5 invariant.
  `01_backend_prompt.md` §9 should be updated to match.
- **2026-08-31 — three backend deviations reviewed and accepted.** Async
  `/refresh` (returns `pending`, does the HEAD check in the task — §5 behaviour
  preserved); `edge.id` keyed on raw `target_ref` rather than the resolved target
  (keeps ids stable across unresolved↔resolved flips, so the frontend can animate);
  persisted `target_node_id` treated as a cache recomputed at assembly (this is what
  makes cross-repo add/remove work). All sound, none contradict §5.
- **2026-08-31 — sans-serif drift caught in the frontend scaffold.** The first
  dispatch's `frontend/package.json` added `@fontsource-variable/inter` before
  anyone had read the design. Broadsheet's readme is explicit: "Do not introduce a
  sans-serif for UI chrome; the serif is the chrome." Flagged to the re-dispatched
  agent to remove and replace with Source Serif 4.
