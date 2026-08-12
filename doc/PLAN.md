# Build Plan — KDB Report Console (Copilot Agent Edition)

**Read this whole file once before starting Phase 0.** It is the single
source of truth for build order, current progress, and what "done" means for
each phase. `AGENTS.md` has the non-negotiable design rules; `.github/instructions/*`
has topic-specific detail that loads automatically when you edit matching
files — do not duplicate that content here or in chat responses.

## Why this plan exists

This project already has a **complete, tested, working reference
implementation** in `reference/` (40 files, git-tracked, 44/44 tests passing
on the machine it was built on). Your job is **not** to design this system —
it is already designed. Your job is to reproduce it on this machine, phase by
phase, verifying as you go, adapting only what the local environment forces
you to adapt (OS, paths, network access).

## Token-saving rules — follow these every phase

1. **Copy, don't regenerate.** For any file `PLAN.md` marks `[copy]`, read it
   from `reference/<path>` and write it to `<path>` unchanged. Do not
   re-derive its contents from the prose description — the description is
   there so you know *what it does*, not so you rewrite it from scratch.
2. **One phase per turn.** Stop when a phase's acceptance check passes. Tick
   its checkbox in the Progress Ledger below and end your turn. Do not
   continue into the next phase without being asked — this keeps each
   session's context small and lets you (or the user) start a **fresh chat
   per phase**, which is the single biggest token saver available: a new
   session pays no cost for everything already done.
3. **Don't paste code back into chat.** The file is on disk; say what you did
   in one sentence ("copied kdb/lib.q, kdb/gateway.q, 6 report files") and
   move on.
4. **Read `KNOWN-PITFALLS.md` before debugging, not after.** Every failure
   mode hit while building the reference implementation is catalogued there.
   Check it before spending tokens on trial and error.
5. **On failure, fix within the current phase only.** Do not jump ahead or
   backtrack into an already-ticked phase to "improve" it.

---

## Progress Ledger

Tick these as you complete each phase. A fresh chat session should start by
reading this ledger, not by re-reading the whole plan.

- [ ] Phase 0 — Preflight (environment, licensing, network checks)
- [ ] Phase 1 — Python environment
- [ ] Phase 2 — Public dataset
- [ ] Phase 3 — Report catalog (CSV)
- [ ] Phase 4 — kdb+ report layer (.q files)
- [ ] Phase 5 — Local kdb+ host (embedded KDB-X via PyKX)
- [ ] Phase 6 — Middle-tier app (FastAPI + PyKX client)
- [ ] Phase 7 — Front-end (vanilla HTML/CSS/JS)
- [ ] Phase 8 — Dev orchestration (Makefile / launch scripts)
- [ ] Phase 9 — Test suite
- [ ] Phase 10 — Docs + final verification

---

## Phase 0 — Preflight

**Goal:** confirm this machine can actually run the stack before writing
anything, and surface any compliance/network blocker early rather than
mid-build.

Checks to run and report (don't fix anything yet, just report results):

1. `python3 --version` — need 3.9+.
2. `python3 -m venv --help` — venv module available.
3. **Network reachability**, three separate endpoints, since work networks
   often allow some and not others:
   - `pypi.org` (needed for `pip install`)
   - `raw.githubusercontent.com` (needed for Phase 2's two public CSVs)
   - kdb+/KX's license service (needed the *first* time `pykx` runs in
     licensed mode — it fetches a free KDB-X Community license on first use
     unless one is already provisioned via `QLIC`/`QHOME`)
4. Confirm with the user, in chat, before Phase 5: **"Is installing `pykx`
   and letting it fetch a KX Community license compliant on this machine?"**
   This is a real network call to a third party and is the one step in this
   whole plan most likely to need a compliance exception. If the answer is
   no, stop and ask the user how they want to proceed — there is no silent
   workaround for this, and guessing wastes tokens.
5. OS: `uname -a` or equivalent. The reference implementation was built and
   tested on **macOS**. Shell scripts under `reference/scripts/*.sh` are
   bash. If this machine is Windows, flag it now — Phase 8 will need those
   ported to PowerShell (or run under WSL/Git Bash), not silently skipped.

**Acceptance:** all four checks reported to the user; any "no" or "blocked"
answer discussed before proceeding, not worked around unilaterally.

---

## Phase 1 — Python environment

**Files:** `requirements.txt` `[copy]`

```bash
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
```

**Acceptance:**
```bash
./.venv/bin/python -c "import fastapi, uvicorn, pykx, pytest; print('ok')"
```
prints `ok`. If `pykx` import fails or blocks on a license prompt, stop —
that's the Phase 0 §4 blocker, not something to patch around here.

---

## Phase 2 — Public dataset

**Files:** `scripts/fetch_raw.sh` `[copy]`, `scripts/build_data.py` `[copy]`

This downloads two small public CSVs and joins them into the NASDAQ daily
dataset the reports query. Nothing here is synthesised — every price, date
and symbol comes from the source files.

```bash
chmod +x scripts/fetch_raw.sh
./scripts/fetch_raw.sh
```

If network access to `raw.githubusercontent.com` is blocked (see Phase 0
§3), **stop and ask the user** how to get the two source files onto this
machine (their URLs are inside `scripts/fetch_raw.sh`) rather than inventing
a substitute dataset — the report logic and tests assume this exact data.

**Acceptance:**
```bash
./.venv/bin/python -c "
import csv
rows = list(csv.DictReader(open('data/nsdq_daily.csv')))
syms = list(csv.DictReader(open('data/nsdq_symbols.csv')))
print(len(rows), 'rows,', len(syms), 'symbols')
"
```
should print `139778 rows, 114 symbols` (exact counts — this is the same
public snapshot used throughout `reference/`, so it must match).

---

## Phase 3 — Report catalog (CSV)

**Files:** `data/reports.csv` `[copy]`, `data/report_params.csv` `[copy]`

These two files **are the application's contract** — both the q gateway and
the FastAPI app read them; nothing about a report is hardcoded elsewhere.
See `.github/instructions/catalog-csv.instructions.md` for the schema rules
before editing either file (most importantly: **no value may contain a
comma** — kdb's `0:` CSV reader has no quoted-field support).

**Acceptance:** both files copied verbatim, no reformatting. Do not
"clean up" the CSVs — their exact column order is load-bearing on the q
side (`kdb/gateway.q` parses them with a fixed type-string).

---

## Phase 4 — kdb+ report layer (.q files)

**Files** (all `[copy]`):
- `kdb/data.q` — loads the dataset, derives `prev_close`/`chg_pct`
- `kdb/lib.q` — shared helpers every report calls (validation, rounding, the
  tearsheet HTML renderer)
- `kdb/gateway.q` — reads `data/reports.csv`, loads every `q_file` it names,
  builds the dispatch whitelist from `q_func`, implements `.z.pg`
- `kdb/start.q` — loader, for use with a standalone `q` binary if one exists
- `kdb/reports/*.q` — one file per report (6 files), each named exactly as
  the `q_file` column in `data/reports.csv` says

Read `.github/instructions/q-lang.instructions.md` before touching any of
these — it lists q-specific failure modes (reserved words, comment syntax,
symbol literal rules) that cost real debugging time to discover the first
time round.

**Acceptance:** this phase has no standalone runtime check — it's verified
together with Phase 5, since kdb+ code can only be validated by loading it
into an interpreter.

---

## Phase 5 — Local kdb+ host

**Files:** `scripts/serve_q.py` `[copy]`

This hosts `kdb/*.q` on a real IPC socket using **embedded KDB-X via PyKX** —
there is no standalone `q` binary required. Read
`.github/instructions/pykx-transport.instructions.md` first; PyKX has
several non-obvious constraints (threading, connection-level timeouts) that
this script and Phase 6's client are already built around.

```bash
./.venv/bin/python scripts/serve_q.py -p 5000 &
```
(run in the background, or in a second terminal)

**Acceptance**, from a second shell:
```bash
./.venv/bin/python -c "
import pykx as kx
c = kx.SyncQConnection('127.0.0.1', 5000, timeout=10.0, no_ctx=True)
print(c('.rpt.ping').py())
print(c('.rpt.range').py())
"
```
prints `pong` and a dict with `rows: 139778`. If port 5000 is taken (common
on macOS — AirPlay Receiver squats on it), use `-p <other-port>` and note the
port for later phases.

---

## Phase 6 — Middle-tier app

**Files** (all `[copy]`): `app/__init__.py`, `app/config.py`,
`app/catalog.py`, `app/validate.py`, `app/kdbclient.py`, `app/serialize.py`,
`app/artifacts.py`, `app/errors.py`, `app/main.py`

`app/__init__.py` sets `PYKX_THREADING=1` before `pykx` is ever imported —
this is load-bearing, not decoration; see the PyKX instructions file. Do not
reorder imports across these files.

**Acceptance**, with Phase 5's server still running:
```bash
KDB_PORT=5000 ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 &
sleep 2
curl -s http://127.0.0.1:8000/api/health
```
returns `"status":"ok"` and `"reachable":true`.

---

## Phase 7 — Front-end

**Files** (all `[copy]`): `app/static/index.html`, `app/static/app.js`,
`app/static/styles.css`

Pure static assets, served by the app from Phase 6 — no build step, no
package.json, nothing to compile. Read
`.github/instructions/frontend.instructions.md` if you need to modify
anything; it explains the layout (one control bar: Category → Report →
parameters, all in one row) so a change doesn't fight the existing CSS.

**Acceptance:** with the Phase 6 server still running, open
`http://127.0.0.1:8000` in a browser. The page loads, the Category dropdown
is populated, selecting a report regenerates its parameter fields, and
clicking Run against any `public`-style report (all of them, currently)
returns a table.

---

## Phase 8 — Dev orchestration

**Files:** `Makefile` `[copy]`, `scripts/dev_stack.sh` `[copy]`,
`scripts/html2pdf.sh` `[copy]`

These are bash. **If this machine is Windows** (flagged in Phase 0), port
`dev_stack.sh` to a PowerShell equivalent (`scripts/dev_stack.ps1`) that does
the same three things in order: start `serve_q.py`, wait for its port to
open, start `uvicorn`. Keep the Makefile as documentation of the intended
commands even if `make` itself isn't available — translate its targets to
whatever task runner the user actually has (VS Code tasks, a `.ps1` script,
etc.) rather than skipping this phase.

**Acceptance:**
```bash
make data   # no-op if Phase 2 already ran
make dev
```
brings up both processes and prints the URL to open. `make stop` shuts both
down cleanly.

---

## Phase 9 — Test suite

**Files:** `pytest.ini` `[copy]`, `tests/conftest.py` `[copy]`,
`tests/test_api.py` `[copy]`

The suite starts its **own** kdb+ gateway per session (via `serve_q.py`), so
it does not depend on Phase 5's server still running. Read
`.github/instructions/tests.instructions.md` if a test needs adapting —
notably, there is no mock backend anywhere in this project; every test talks
to real kdb+ over a real socket, on purpose.

```bash
./.venv/bin/python -m pytest -q
```

**Acceptance:** `44 passed`. If fewer pass, check `KNOWN-PITFALLS.md` first —
several of the 44 tests exist specifically because of bugs listed there.

---

## Phase 10 — Docs + final verification

**Files** (all `[copy]`): `DESIGN.md`, `MANUAL.md`, `README.md`

Copy these into the project root as-is; they describe the system this plan
just rebuilt and don't need editing unless something in Phases 0–9 forced a
genuine deviation (different OS, different port, network workaround) — if
so, add a short **"Deviations from the reference build"** section at the top
of `MANUAL.md` rather than editing the inherited prose in place.

**Final acceptance checklist** — all must be true:
- [ ] `pytest -q` → `44 passed`
- [ ] `make dev` (or its ported equivalent) brings up a working page at
      `http://127.0.0.1:8000`
- [ ] At least one `table`, the `html`, and the `pdf` format have each been
      run once by hand and inspected
- [ ] `git status` is clean or everything intentional is staged
- [ ] Progress Ledger above shows all ten phases ticked

At that point the rebuild is complete and this plan's job is done.
