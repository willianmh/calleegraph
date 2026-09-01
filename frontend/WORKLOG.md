# Frontend worklog

Append-only. Add a new entry at the end of every work session — never edit or
delete a past entry (see `01_frontend_prompt.md` §7).

## [2026-08-31 23:10] Frontend build — design import, app shell, Graph, Repositories/Settings, SSE

- Did: Built the frontend from the Claude Design handoff bundle. Read
  `canvas-requirements-clarification/project/Calleegraph.dc.html` in full plus
  the Broadsheet `styles.css` and `readme.md`, then implemented:
  - `src/main.tsx`, `App.tsx`, `router.tsx` — shell, routing, top-bar SSE dot.
  - `src/api/{types,client,queries}.ts` — contract §5 types verbatim, typed
    fetch client, TanStack Query hooks.
  - `src/lib/sse.ts` — one global `EventSource`, `repository_updated` upserts by
    id, `graph_updated` replaces the cached `GraphResponse` wholesale,
    reconnect with backoff, connection state surfaced in the shell.
  - `src/features/graph/` — `model.ts` (density thresholds, `EDGE_VISUALS` for
    all four statuses, filtering, wiring), `flow.ts` (React Flow graph build,
    grouped vs detailed), `nodes.tsx`/`edges.tsx` renderers, `GraphScreen.tsx`,
    `EdgeDetailPanel.tsx`, `GraphSidebar.tsx`, `Legend.tsx`, `EmptyState.tsx`.
  - `src/features/repositories/RepositoriesScreen.tsx`,
    `src/features/settings/SettingsScreen.tsx` (write-only PAT).
  - `src/components/` — `StatusDot`, `ConfirmDialog`, `ui.tsx` primitives.
  - `mock/server.mjs` — dev-only API mock; small (5-node) and
    `MOCK_SIZE=large` (58-node) fixtures, all four edge statuses, live status
    transitions. Outside `src/`, nothing imports it, excluded by
    `.dockerignore`.
  - `Dockerfile`, `nginx.conf`, `vite.config.ts`, `eslint.config.js`,
    `.prettierrc.json`, `tsconfig.json`.
- Deviated: The `claude_design` MCP specified in §2.1 is not connected in this
  environment, and worker agents do not have the `DesignSync` tool either. The
  user exported the project as a local handoff bundle at
  `canvas-requirements-clarification/`, verified byte-identical to the live
  project; the design was read from disk instead. §2.1 has been rewritten by the
  orchestrator to describe this.
- Blocked: none affecting contract §5.
- Next: quality gates (`tsc --noEmit`, ESLint, Prettier) and the Docker image.

## [2026-09-01 05:55] Quality gates green — finished by the orchestrator

> Written by the **orchestrator**, not the frontend agent: that agent was
> terminated mid-task by a session rate limit while writing the ESLint/Prettier
> config. This entry records what the orchestrator did to finish it, so the
> history stays accurate about who did what.

- Did: Took the build from "37 files, gates failing" to all gates green.
  - Fixed 6 TypeScript errors: `src/api/client.ts` (an explicit `undefined` for
    an optional `headers` prop, illegal under `exactOptionalPropertyTypes`; and
    `request<void>`, since `void` is not a valid generic type argument — a 204
    is now modelled as `null`), an unused `WorkflowNode` import in
    `EdgeDetailPanel.tsx`, an unused `index` parameter in `flow.ts`
    (`buildGroupedFlow` never read it), and React Flow typing `MiniMap`'s
    `node.data` as `Record<string, unknown>` in `GraphScreen.tsx`.
  - **Removed `vitest`.** `vite.config.ts` imported `defineConfig` from
    `vitest/config`, and vitest 3.2.7 installs its own nested vite (v7) that
    collides with the root vite 8 under `exactOptionalPropertyTypes`, producing
    an unfixable-in-place type error. No test files existed, so the dependency
    was removed rather than the version conflict papered over. `npm run check`
    is now `typecheck && lint && format:check`.
  - Fixed the 46 ESLint problems: 37 auto-fixed; the rest by hand — two
    `set-state-in-effect` violations rewritten as derived state
    (`GraphScreen`'s expand-override pruning became a `useMemo`;
    `SettingsScreen`'s form seeding became the React "adjust state during
    render" pattern), a generic-as-disguised-assertion in `sse.ts` narrowed to
    `unknown` + a cast at each call site, the deprecated `React.FormEvent`
    replaced, unused `CgEdgeData` imports dropped, and one justified
    `react-refresh/only-export-components` disable in `StatusDot.tsx`.
  - Ran Prettier across the tree.
- Verified (real runs, not claims): `npx tsc --noEmit` clean; `npx eslint .`
  **0 problems**; `npx prettier --check .` clean; `npm run build` succeeds
  (599.56 kB JS / 35.59 kB CSS, Source Serif 4 self-hosted — confirming the
  `@fontsource-variable/inter` the first scaffold pulled in is gone).
  `nginx.conf` validated by real nginx (`nginx -t` in `nginx:alpine`, with the
  `backend` upstream aliased) — syntax OK. Runtime smoke test against
  `mock/server.mjs`: `/api/health`, `/api/repositories`, `/api/graph` and the
  SSE stream (`: connected`) all respond; the small fixture yields 5 nodes with
  **all four edge statuses present** (`ok`/`warning`/`error`/`unresolved`) and
  an `unknown_input` issue carrying a real suggestion, and `MOCK_SIZE=large`
  yields 58 nodes across 4 repos — exercising both density bands (thresholds
  are `DETAILED_BELOW = 15`, `GROUPED_ABOVE = 40`).
  Confirmed no `mock` string reaches `dist/`.
- Deviated: `vitest` removed (above). Consequently there are no frontend unit
  tests; density and edge-state behaviour is exercised through the mock server
  instead, which is how §9's acceptance criteria are phrased anyway.
- Blocked: **`docker build ./frontend` is unverified — environmental, not a
  defect.** Build containers in this environment have no outbound network: a
  control image (`FROM alpine` + `wget https://pypi.org`) fails with a TLS
  reset while the same fetch from the host returns HTTP 200, so any `npm ci`
  layer fails for reasons unrelated to the Dockerfile. The build stage runs the
  same `npm run build` that succeeds on the host against the same lockfile.
  Needs one run on a networked machine.
- Next: end-to-end integration against the real backend through
  `docker compose up --build` — the full §11.2 demo. Nothing in the frontend is
  known to be outstanding.
