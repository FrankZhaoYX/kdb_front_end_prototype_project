---
applyTo: "tests/**"
---

# Test conventions

- There is **no mock of kdb+** anywhere in this project, on purpose. Every
  test drives the real FastAPI app, which opens a real PyKX connection to a
  real kdb+ gateway (`scripts/serve_q.py`, started per test session by
  `tests/conftest.py`). Do not add a mock/stub kdb backend, even for a
  single new test — extend the real gateway (a new `.q` file plus a catalog
  row) instead.
- `tests/conftest.py` starts its own gateway on a free port by default. Set
  `KDB_TEST_PORT` to point the suite at a gateway you're already running
  instead (useful when iterating quickly).
- A new report needs at least: one happy-path test with known real output
  values (not computed in the test — asserted against the actual public
  dataset), and one test per distinct error path it can produce.
- Run `./.venv/bin/python -m pytest -q` after any change under `app/` or
  `kdb/`. Don't report a change complete with a failing or unrun suite.
