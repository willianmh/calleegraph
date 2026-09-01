# Workflow fixtures

Sample GitHub Actions workflow YAML used by the parser/validation tests and by
the three synthetic repos in `tests/repos.py` (which stand in for the three
contract-verification repos of orchestrator prompt §2.2 — no live PAT is used
anywhere in the suite).

Files prefixed `bad_` are deliberately malformed or degenerate; they exist to
prove that one broken file never fails a repo sync (backend prompt §7).
