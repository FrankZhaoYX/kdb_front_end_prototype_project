---
mode: agent
description: Add a new report to the catalog, following the existing pattern end to end.
---

Ask the user, if not already stated in this conversation: the report's
`category`, `name`, `description`, the q logic it needs, its parameters, and
which output format(s) it should support (`table`/`html`/`pdf`).

Then, in order:

1. Pick a `report_id` (snake_case, unique — check it's not already in
   `data/reports.csv`).
2. Write `kdb/reports/<report_id>.q`, modelled closely on an existing file in
   `kdb/reports/` that's structurally similar (a single-symbol lookup looks
   like `symbol_tearsheet.q`; a date-range aggregation looks like
   `market_breadth.q` or `ohlc_summary.q`). Reuse helpers from `kdb/lib.q`
   rather than duplicating validation/rounding logic. Follow every rule in
   `.github/instructions/q-lang.instructions.md`.
3. Add one row to `data/reports.csv` for this report, and one row per
   parameter to `data/report_params.csv`, following
   `.github/instructions/catalog-csv.instructions.md` exactly — **no commas
   in any value**.
4. Restart the local kdb+ gateway (the catalog's q side does not hot-reload)
   and confirm the new report loads without error.
5. Add a test to `tests/test_api.py`: at least one happy-path assertion
   against real values from the dataset, plus one test per error path the
   report can produce (bad range, unknown symbol, empty result — whichever
   apply).
6. Run `./.venv/bin/python -m pytest -q` and confirm it's still fully green,
   including the new test.
7. Confirm the new report appears correctly in the browser: it shows up
   under the right category, its parameter fields render, and running it
   returns output in each format it declares.

Report back with the `report_id` and a one-line summary — not the file
contents.
