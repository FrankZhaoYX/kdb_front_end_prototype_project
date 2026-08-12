---
mode: agent
description: Run the full verification checklist against a freshly built or modified stack.
---

Run each check below in order. Stop at the first failure, report it with the
exact command and output that failed (trimmed to the relevant lines, not the
full log), and check `KNOWN-PITFALLS.md` before proposing a fix.

1. `./.venv/bin/python -m pytest -q` → expect `44 passed` (or more, if
   reports have been added since the reference build).
2. Start the stack (`make dev`, or its ported equivalent per `PLAN.md`
   Phase 8) and confirm:
   - `curl -s http://127.0.0.1:8000/api/health` → `"status":"ok"`,
     `"reachable":true`
   - `curl -s http://127.0.0.1:8000/api/reports` → returns all catalog
     reports with no error
3. In a browser at `http://127.0.0.1:8000`:
   - The Category dropdown populates.
   - Selecting a category filters the Report dropdown.
   - Selecting a report regenerates its parameter fields in the same
     control bar (not a separate panel).
   - Run at least one `table` report → a sortable grid renders with data.
   - Run the `html`-format report → renders inline.
   - Run the `pdf`-format report → downloads/opens a real PDF (check its
     first bytes are `%PDF-`, not an error page).
4. Trigger one deliberate input error (e.g. an out-of-range date) and
   confirm it renders under the correct field, not as a generic banner.
5. `make stop` (or equivalent) cleanly stops both processes — confirm with
   `curl` that port 8000 and the kdb+ port are no longer accepting
   connections afterward.

If every check passes, report a one-line summary: what was run, that all
checks passed, and nothing else.
