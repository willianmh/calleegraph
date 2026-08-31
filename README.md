# calleegraph

Statically analyzes GitHub Actions workflows across one or more repos and
exposes a combined dependency graph of which workflow calls which reusable
workflow.

- [`backend/README.md`](backend/README.md) — backend setup and local dev.
- [`docs/github-authentication.md`](docs/github-authentication.md) — how the
  backend authenticates to GitHub (the only backend slice implemented so
  far).
