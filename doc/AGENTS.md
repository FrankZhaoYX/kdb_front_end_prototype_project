# AGENTS.md — KDB Report Console

Read this once at the start of a session. It states the rules that must not
be broken regardless of how a shortcut looks in the moment. Build order and
per-phase detail live in `PLAN.md`; do not duplicate this file's content
there or vice versa.

## What this project is

A prototype front-end for running kdb+ reports: a user picks a Category, then
a Report, fills in parameters generated from a catalog, and gets back a
table, an HTML page, or a PDF. See `reference/DESIGN.md` for the full
rationale — read it before changing architecture, not after.

## Non-negotiable rules

1. **The browser never sends q code.** It sends a `report_id` and a
   parameter object. The catalog (`data/reports.csv` + `q_func`) maps
   `report_id` to a whitelisted q function; the client cannot name a
   function directly. Never build a code path where user input becomes part
   of a q expression string.

2. **The catalog is the contract.** `data/reports.csv` and
   `data/report_params.csv` are read by both the q gateway and the Python
   app. A new report is a CSV row plus a `.q` file — never hardcode a report
   definition in Python or JavaScript instead of the CSV.

3. **One response envelope, one error shape.** Every `.rpt.run` call returns
   `` `status`report`format`payload`meta ``, success or failure. Every API
   error the browser can see is `{status:"err", code, message, field?,
   detail?}` — a `field` renders under that input, no `field` means a
   banner. Don't invent a second error shape for a new endpoint.

4. **Validate what you can before touching kdb; let kdb validate the rest.**
   Types, ranges, enums, required-ness — reject those in the app before
   opening a socket. Whether a symbol exists, whether a date has data,
   whether a filter matched anything — that's kdb's job. Don't move a check
   from one side to the other without a reason.

5. **No authentication, and don't add any.** This is an explicit,
   deliberate prototype-scope decision (an entitlements layer was built and
   then removed on request). Every report is reachable by anyone who can
   reach the app. If asked to add auth, implement it — don't refuse — but
   don't add it speculatively.

6. **kdb+ is single-threaded; treat it that way.** Don't design around the
   assumption that two reports can run concurrently on one gateway. The
   PyKX connection pool exists for handle isolation, not parallelism.

7. **No Python mock of kdb+.** Every test and every dev run talks to a real
   kdb+ process (`scripts/serve_q.py`, embedded KDB-X via PyKX). A prior
   version of this project had a hand-rolled mock; it was deliberately
   removed. Do not reintroduce one.

## Where things live

| Concern | File(s) |
|---|---|
| Report catalog | `data/reports.csv`, `data/report_params.csv` |
| q report logic | `kdb/reports/*.q`, shared helpers in `kdb/lib.q` |
| q entry point | `kdb/gateway.q` (`.z.pg`, catalog loader, dispatch whitelist) |
| PyKX transport | `app/kdbclient.py` (connection pool, timeouts, error mapping) |
| Parameter validation | `app/validate.py` |
| API routes | `app/main.py` |
| Front-end | `app/static/{index.html,app.js,styles.css}` — no framework |
| Tests | `tests/test_api.py` (44 tests, all against real kdb+) |

## Before you finish any change

- Run `./.venv/bin/python -m pytest -q` and don't report done until it's
  green.
- If you touched `data/reports.csv` or `data/report_params.csv`, confirm no
  value contains a comma (see `.github/instructions/catalog-csv.instructions.md`).
- If you touched anything under `kdb/`, check `KNOWN-PITFALLS.md` — several
  entries there are silent failures (no error, wrong behavior) that are easy
  to reintroduce by accident.
