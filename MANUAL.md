# KDB Report Console — Manual

A working prototype of the design we settled on: a **light front-end** that lets a
user search for a report, fill in its parameters, and get back a table, an HTML
page or a PDF — with a **FastAPI + PyKX middle tier** that validates the
parameters and calls kdb+ over IPC.

> This manual is the operational guide. For *why* the system is shaped this way
> — the options rejected, the invariants, what was deferred — see
> **[DESIGN.md](DESIGN.md)**.

Everything in this manual has been run. Where something has *not* been verified,
it says so explicitly (see [§10 Known limitations](#10-known-limitations)).

---

## 1. Quick start

```bash
make setup
```

```bash
make data
```

```bash
make dev
```

Then open <http://127.0.0.1:8000>. `make stop` shuts it down.

`make setup` builds `.venv` and installs dependencies. `make data` downloads two
public CSVs (~30 MB) and builds the dataset. `make dev` starts the kdb+
gateway and the app on port 8000, and tails both logs.

To run the pieces in separate terminals instead:

```bash
make kdb
```

```bash
make app
```

`make dev` starts the kdb+ gateway and the app together. There is only one
backend: the real `kdb/*.q`. See [§9](#9-running-against-real-kdb).

---

## 2. What actually got built

| Layer | Lives in | What it is |
|---|---|---|
| Front-end | `app/static/` | One HTML page, one CSS file, one JS file. No framework, no npm, no build step, no external requests. |
| Middle tier | `app/` | FastAPI. Loads the catalog, validates parameters, calls kdb over **PyKX**, serves PDFs. |
| kdb+ gateway | `kdb/` | `.q` sources: the reports, the `.z.pg` entry point, the allow list. Executed against KDB-X 5.0. |
| Local host for it | `scripts/serve_q.py` | Serves `kdb/*.q` on a socket from embedded KDB-X — see [§9](#9-running-against-real-kdb). |
| Catalog | `data/*.csv` | The report list and their parameters. Two CSVs. |
| Tests | `tests/` | 44 end-to-end tests against real kdb+. Nothing stubbed. |

---

## 3. How a request flows

```
BROWSER                    MIDDLE TIER (FastAPI)                 KDB
   │                                │                             │
   │ GET /api/reports               │                             │
   │───────────────────────────────>│  read data/reports.csv      │
   │<───────────────────────────────│                             │
   │                                │                             │
   │ GET /api/reports/top_movers    │                             │
   │───────────────────────────────>│  resolve @max_date tokens   │
   │<─── param specs ───────────────│                             │
   │                                │                             │
   │ POST /api/run                  │                             │
   │  {report_id, params, format}   │                             │
   │───────────────────────────────>│                             │
   │                                │ 1. look up report in catalog│
   │                                │ 2. coerce each param to a   │
   │                                │    q type; reject bad ones  │
   │                                │    BEFORE touching kdb      │
   │                                │ 3. .rpt.run[id;dict;max;fmt]│
   │                                │────────────────────────────>│
   │                                │                             │ .Q.trp
   │                                │<─── envelope ───────────────│
   │<─── columns + rows ────────────│                             │
```

### The three invariants

**1. The browser never sends q code.** It sends a `report_id` and a parameter
object. The catalog maps `report_id → q function name`; the client cannot name a
function. Parameters travel over IPC as *typed values*, never concatenated into a
query string, so there is no injection surface to defend.

**2. One response envelope for every format.** kdb always returns:

```q
`status`report`format`payload`meta!(`ok; `top_movers; `table; <data>; <meta>)
```

`format` is `` `table ``, `` `html `` or `` `pdf ``. Errors reuse the same shape
with ``status:`err``. The front-end has one code path.

**3. The catalog is the contract.** Both sides read it; the gateway even loads
its q from it. Adding a report is a CSV row plus a `.q` file.

---

## 4. The data

Two public files, fetched by `scripts/fetch_raw.sh`:

| File | Source | What it gives |
|---|---|---|
| `all_stocks_5yr.csv` | `plotly/datasets` on GitHub | Real daily OHLCV, 2013-02-08 → 2018-02-07 |
| `nasdaq-listed-symbols.csv` | `datasets/nasdaq-listings` on GitHub | Official NASDAQ listing reference |

`scripts/build_data.py` keeps only symbols present in **both**, which leaves a
NASDAQ-listed universe with genuine historical prices:

```
139,778 rows · 114 symbols · 2013-02-08 to 2018-02-07
```

**Every price, volume and date is from the source files.** Nothing is
synthesised. Company names have their commas stripped, because kdb's `0:` CSV
loader has no concept of a quoted field — see `q_safe()` in
`scripts/build_data.py`.

> Scope note: the price file covers large-cap US names, so the 114 symbols are
> the NASDAQ-listed subset of that (AAPL, MSFT, NVDA, AMD, INTC, GOOGL…), not
> the whole NASDAQ. Fine for a prototype; swap the source file for a wider one
> if you want more.

---

## 5. The catalog — adding a report

### `data/reports.csv` — one row per report

| Column | Meaning |
|---|---|
| `report_id` | Stable key used by the API and as the join key |
| `category` | First dropdown |
| `name` | Second dropdown, filtered by category |
| `description` | Shown under the pickers; searched |
| `q_file` | The file defining the report, e.g. `kdb/reports/top_movers.q` |
| `q_func` | The entry point in that file. **This is the whitelist** |
| `formats` | Pipe-separated: `table`, `html`, `pdf` |
| `default_format` | Pre-selected in the UI |
| `timeout_s` | Per-report IPC timeout, capped by `KDB_MAX_TIMEOUT_S` |
| `max_rows` | Truncation ceiling; the response flags when it bites |
| `tags` | Extra search terms |

The gateway reads this file at startup, loads every `q_file` it names, and
builds its dispatch table from `q_func`:

```q
.gw.catalog:("SSS*SSSSFJS";enlist ",") 0: hsym `$.gw.catalogFile;
{system "l ",string x} each distinct .gw.catalog`q_file;
.rpt.fn:(!). .gw.catalog`report_id`q_func;
```

So the CSV is the single source of truth for both sides, and nothing about a
report is hardcoded in q.

> **No value may contain a comma.** kdb's `0:` has no quoted-field support, so
> a comma would silently shift every column to its right. Descriptions are
> written comma-free for that reason.

### `data/report_params.csv`

| Column | Meaning |
|---|---|
| `param` | Name passed to q, and the dict key |
| `label`, `help` | UI text |
| `type` | `date` `sym` `symlist` `long` `float` `enum` `bool` `string` |
| `required` | `1`/`0` |
| `default` | Literal, or a `@token` (below) |
| `widget` | `date` `number` `text` `select` `multiselect` |
| `options` | Static list for `select`, pipe-separated |
| `options_q` | q function that supplies the options instead |
| `min`, `max` | Bounds, literal or `@token` |
| `ord` | Display order |

### Date tokens

Defaults and bounds can be tokens instead of fixed dates, resolved per request
against what kdb reports:

| Token | Resolves to |
|---|---|
| `@min_date` | First business date in the dataset |
| `@max_date` | Last business date |
| `@max_date-30d` | 30 calendar days before the last |
| `@min_date+90d` | 90 days after the first |
| `@today` | The real current date |

They are clamped into the dataset, so a default can never fall outside it. This
is why the form opens on `2018-02-07` rather than an empty box.

### Adding one, end to end

1. Write the q function in a new `kdb/reports/<report_id>.q`, using the
   helpers in `kdb/lib.q`.
2. Add one row to `reports.csv` and one row per parameter to
   `report_params.csv`.
3. Reload the page. The CSVs are hot-reloaded on mtime change — no restart.

---

## 6. The API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | App + kdb liveness, pool stats, dataset range |
| `GET` | `/api/reports?q=` | Catalog, optionally filtered |
| `GET` | `/api/reports/{id}` | One report with resolved parameter defaults |
| `GET` | `/api/reports/{id}/options/{param}` | Dropdown values from kdb |
| `POST` | `/api/run` | Run a report |
| `GET` | `/api/download/{token}` | Stream a generated PDF |

### Running a report

```bash
curl -s -X POST http://127.0.0.1:8000/api/run \
  -H 'Content-Type: application/json' \
  -d '{"report_id":"top_movers","params":{"dt":"2018-02-07","direction":"both","top_n":5,"min_volume":0}}'
```

Response (table):

```json
{
  "status": "ok",
  "report": "top_movers",
  "format": "table",
  "meta": {"rows": 10, "truncated": false, "kdb_ms": 0.211,
           "total_ms": 2.9, "generated": "...", "max_rows": 5000},
  "columns": [{"name": "rank", "type": "number"}, {"name": "sym", "type": "symbol"}],
  "rows": [[1, "HAS"], [2, "WYNN"]]
}
```

Column-oriented output is ~40% smaller than a list of objects and hands the grid
the column types it needs to right-align numbers.

### PDF handling

kdb writes the file and returns a **path**. The browser never sees it. The path
is validated (`app/artifacts.py`), registered under an opaque token, and the
response carries `/api/download/<token>`:

```json
{"format": "pdf", "download_url": "/api/download/d7b4…", 
 "filename": "tearsheet_NVDA_….pdf", "size_bytes": 7121}
```

`safe_path()` resolves symlinks and `..` **before** comparing against
`REPORT_DIR`, so `/reports/../../etc/passwd` and a symlink pointing out of the
directory both fail. That check is the entire security boundary for this format,
which is why it lives on the app side rather than trusting kdb.

---

## 7. The error model

Every failure the browser can see has the same shape:

```json
{"status": "err", "code": "unknown_symbol",
 "message": "not in the NASDAQ universe: NOTREAL",
 "field": "symbols", "detail": "..."}
```

**`field` set → the message renders under that input. No `field` → banner.**
That is the whole front-end error contract.

| Code | HTTP | Raised where | Trigger |
|---|---|---|---|
| `invalid_param` | 400 | app | Bad type, bad format, out of bounds, bad enum |
| `unknown_report` | 404 | app | `report_id` not in the catalog |
| `unsupported_format` | 400 | app | Format not offered by that report |
| `unknown_symbol` | 400 | **kdb** | Symbol not in the universe |
| `invalid_range` | 400 | **kdb** | `date_from` after `date_to` |
| `no_data_for_date` | 400 | **kdb** | Not a business date |
| `empty_result` | 400 | **kdb** | Filters matched nothing |
| `kdb_timeout` | 504 | app | Exceeded `timeout_s` |
| `kdb_unavailable` | 502 | app | Cannot open or lost a handle |
| `report_error` | 500 | app | kdb signalled (a real q error) |
| `artifact_missing` | 404 | app | Download token expired or unknown |

### The split is deliberate

The app validates what it can know from the catalog (types, ranges, enums,
required-ness) and rejects those **before opening a socket**. kdb validates what
only it knows (does this symbol exist, is this a business date, did anything
match). Both produce the same envelope, so the UI cannot tell — and does not
care — which side said no.

### The one subtle bit: timed-out handles are poisoned

When a sync call times out, the reply is *still coming down the socket*. Reusing
that handle would return the previous call's result and every later answer would
be off by one. `app/kdbclient.py` therefore **closes** a timed-out handle instead
of returning it to the pool. A `QException` is the opposite case — kdb answered,
the answer was an error — and that handle goes straight back. There is a test for
each.

---

## 8. Testing

### The suite

```bash
make test
```

44 tests, ~18 seconds. Each one boots a real mock-KDB server on a free port and
drives the real FastAPI app through a real socket. Coverage:

- every report, every format (table / HTML / PDF)
- known real values (`AAPL` closed at `159.54` on 2018-02-07 — asserted, not computed)
- each error code above, app-side and kdb-side
- truncation flagging, path-traversal refusal, expired download tokens
- the timeout-poisons-the-handle behaviour, and pool recovery afterwards

### Things worth trying by hand

**1. The form builds itself from the CSV.** Open `data/report_params.csv`, change
a `label`, save, reload the page. No restart.

**2. Dropdowns come from kdb.** Pick *Symbol Tearsheet* — the symbol list is 114
real companies fetched live via `options_q=.rpt.symbols`.

```bash
curl -s http://127.0.0.1:8000/api/reports/daily_close/options/symbols | head -c 300
```

**3. A kdb-side error lands on the right field.** Pick *Top Movers*, set the date
to `2018-02-04` (a Sunday), run. The message appears under *Business Date*, in
red, with the field outlined — and the previous result stays on screen dimmed and
labelled "previous result".

**4. An app-side error never reaches kdb.** Watch the kdb log while sending a bad
enum — nothing appears, because it was rejected first:

```bash
curl -s -X POST http://127.0.0.1:8000/api/run -H 'Content-Type: application/json' -d '{"report_id":"top_movers","params":{"dt":"2018-02-07","direction":"sideways","top_n":5}}'
```

**5. Timeout handling.** The mock exposes `.rpt.sleep` for exactly this. Set a
report's `timeout_s` to `1` in `reports.csv`, or drive the pool directly:

```bash
./.venv/bin/python -c "import sys;sys.path.insert(0,'.');from app.kdbclient import KdbPool;p=KdbPool();p.call('.rpt.sleep',5,timeout=1.0)"
```

**6. kdb going away mid-session.** Stop the mock server (`make stop`), then hit
*Run report*. You get a `502 kdb_unavailable` banner and the health dot in the
top bar turns red within 20 seconds. Restart it and the next run succeeds — the
pool reconnects on demand.

**7. Truncation is never silent.** Set `max_rows` to `50` for `daily_close` in
`reports.csv`, run a wide date range, and the meta bar shows
`⚠ truncated to 50 rows` alongside the true row count kdb saw.

**8. kdb+ is single threaded — and you can feel it.** The mock serialises report
execution behind one lock on purpose, because kdb+ evaluates on its main thread.
Run `.rpt.sleep` in one terminal and try the UI in another: everything queues.
Start the mock with `--concurrent` to remove the lock and watch the difference.
This is the property that argues for a *separate* gateway process.

---

## 9. Running against real kdb+

The q sources are **executed and verified** against KDB-X 5.0. Three ways to run
them:

```bash
make kdb
```

Serves `kdb/*.q` from embedded KDB-X. This is what this machine has: KDB-X
ships as a library (PyKX's `libq`), not a standalone `q` binary, so
`scripts/serve_q.py` accepts real kdb+ IPC connections and answers them from a
real q interpreter. No value is converted between Python and q -- the client's
bytes go into q's own `-9!` deserialiser, through the real `.z.pg`, and back out
of `-8!`. Only the socket accept loop is Python.

```bash
make kdb-q
```

The same `kdb/*.q` under a standalone `q` binary (`q kdb/start.q -p 5000`), for
when you have one.

Either way the app is unchanged:

```bash
KDB_HOST=your-host KDB_PORT=5000 make app
```

### Verifying it

```bash
make test
```

44 end-to-end tests against real kdb+: every report, every format, every error
path, plus the transport behaviours in §7. The suite starts its own gateway;
set `KDB_TEST_PORT` to point it at one you already run.

### What running it actually caught

Six bugs that review had missed. They are worth knowing because every one is a
silent-or-cryptic failure mode rather than a clear error:

**1. A lone `/` on its own line comments out the rest of the file.** Every `.q`
file opened with a header block like:

```q
/ Loads the NASDAQ daily bars.
/
/ Both CSVs are written unquoted because ...
```

That bare `/` on line 2 starts a **multi-line comment block** that runs until a
line containing only `\`. There is no such line, so the entire file after line 2
was a comment. `\l kdb/data.q` returned cleanly and defined *nothing*. No error,
no warning. Blank comment separators are now `/-`.

**2. `rank` is a q keyword.** `update rank:1+til count t from t` signals
`'assign`. The column is built as `rnk` and renamed last via `xcol`, which takes
symbols rather than identifiers and so can produce a name the parser rejects.

**3. `meta` is a q keyword too.** A local named `meta` inside `.gw.wrap`
signalled the same way. Renamed `mkMeta`. The envelope key `` `meta `` is a
symbol and was always fine.

**4. A symbol literal cannot start with an underscore.** `` `_format `` does not
tokenise as one symbol — q reads it as the empty symbol `` ` `` followed by the
identifier `format`, and signals `'format`. This one changed the design for the
better: output format is a property of the request, not a report parameter, so
`.rpt.run` now takes it as a fourth argument and there is no magic key inside
the parameter dict at all.

**5. A relative `.rpt.outDir` produced an unfindable path.** kdb returned
`var/reports/tearsheet_….pdf`; the middle tier joined that onto its own
`REPORT_DIR` and looked for `var/reports/var/reports/…`. `.rpt.outDir` is now
resolved to an absolute path at load time.

**6. `system` is refused off the main thread.** `.rpt.sleep` shells out to
`sleep`, which signalled `'sys` when the bridge called q from a socket worker
thread. Fixed in the bridge, which now marshals all q work onto one dedicated
thread — which is what a real q process does anyway.

Plus one divergence the cross-check found: the Python mock rounded its outputs
and q did not, so `pct_advancing` came back as `0.8771929824561403` from q and
`0.88` from the mock. q now rounds identically via `.rpt.rnd`, using `"j"$`,
which rounds half-to-even and so matches `numpy.round` and Python's `round()`.

`kdb/` contains:

| File | Contents |
|---|---|
| `data.q` | Loads the CSVs, derives `prev_close`/`chg_pct`, applies `` `s# ``/`` `g# `` |
| `reports.q` | The six report functions and `.rpt.fn`, the function whitelist |
| `gateway.q` | `.rpt.run` with `.Q.trp`, the envelope builders, and `.z.pg` |
| `start.q` | Loader |

To go through your Sandbox IPC layer, replace the `daily`/`syms` tables in
`data.q` with handles to the sandbox and leave `reports.q` and `gateway.q` alone.

### Two guards on the q side

```q
.gw.allow:`.rpt.run`.rpt.symbols`.rpt.range`.rpt.ping`.rpt.sleep;
.z.pg:{[x] f:.gw.name x; if[not f in .gw.allow; '"access"]; value x};
```

`.gw.allow` restricts what an inbound message may name at all; `.rpt.fn`
restricts what `.rpt.run` will dispatch to. Defence in depth — a bug in one does
not open the other.

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `KDB_HOST` / `KDB_PORT` | `127.0.0.1` / `5000` | Where kdb is |
| `KDB_USER` / `KDB_PASSWORD` | `reportapp` / empty | IPC credentials |
| `KDB_POOL_SIZE` | `4` | Idle handles kept |
| `KDB_MAX_TIMEOUT_S` | `120` | Ceiling on any report's `timeout_s` |
| `KDB_REPORT_DIR` | `var/reports` | **Must match on both sides** |
| `KDB_HTML2PDF` | unset | q-side HTML→PDF converter, e.g. `wkhtmltopdf --quiet` |
| `REPORT_DATA_DIR` | `data` | Where the catalog CSVs live |

---

## 10. Known limitations

Read this section before drawing conclusions from anything above.

**PDF from real kdb+ needs an external converter.** The mock renders PDFs
itself with `fpdf2`. kdb+ has no PDF writer, so `kdb/reports.q` renders HTML and
shells out to `KDB_HTML2PDF`; `scripts/html2pdf.sh` picks the first of
wkhtmltopdf / weasyprint / prince / headless Chrome that is installed. With none
of them present the PDF format returns a clean `pdf_unavailable` error rather
than failing obscurely, and the PDF test skips itself.

**PyKX imposes four constraints the client is built around.** Each is a silent
or cryptic failure if you do not know about it, and all four are in
`app/kdbclient.py` and `app/__init__.py`:

1. **The context interface probes the server on connect.** `.gw.allow` rejects
   it with `'access` and the connection cannot even be constructed. The client
   passes `no_ctx=True` rather than widening the allow list.
2. **Licensed mode forbids sockets off the main thread** (`'nosocket`), which is
   fatal for FastAPI's threadpool. `PYKX_THREADING=1` is set in
   `app/__init__.py` *before* `import pykx`, and `kx.shutdown_thread()` runs on
   shutdown or the process will not exit.
3. **The timeout is fixed when the connection opens, not per call.** Assigning
   `conn._timeout` afterwards looks like it works and does nothing, so idle
   connections are pooled per timeout value.
4. **Unlicensed mode cannot index a returned q dictionary by key**, since that
   needs q evaluation — which is why licensed mode plus `PYKX_THREADING` is used
   rather than the licence-free alternative.

**Execution is synchronous.** `/api/run` blocks until kdb answers. That is fine
at these timings (sub-10 ms for every report here) but will not survive a
multi-minute report. The response already carries everything needed to switch to
a `202 + job_id + polling` model later without a redesign — but it has not been
built.

**No authentication.** `.z.pw` returns `1b` and the app has no auth at all. Put
nginx in front for TLS and SSO before this leaves a sandbox.

**The dataset ends 2018-02-07.** Date pickers are bounded to the data on
purpose, so a default can never produce an empty report.

---

## 11. File map

```
├── MANUAL.md                this file
├── Makefile                 setup / data / kdb / app / dev / test / stop
├── requirements.txt
├── pytest.ini
│
├── data/
│   ├── reports.csv          the report catalog
│   ├── report_params.csv    parameter definitions
│   ├── nsdq_daily.csv       139,778 real NASDAQ daily bars (generated)
│   ├── nsdq_symbols.csv     114 symbols with company names (generated)
│   └── raw/                 downloaded sources (gitignored)
│
├── scripts/
│   ├── fetch_raw.sh         download the public CSVs
│   ├── build_data.py        intersect them into the dataset
│   ├── serve_q.py           hosts kdb/*.q on a socket via embedded KDB-X
│   └── html2pdf.sh          HTML→PDF for the q side (KDB_HTML2PDF)
│
├── app/                     ── MIDDLE TIER ──
│   ├── config.py            env-driven settings
│   ├── catalog.py           CSV loader, hot reload, @token resolver
│   ├── validate.py          param coercion to q types   ← the safety layer
│   ├── kdbclient.py         PyKX pool (keyed by timeout), error mapping
│   ├── serialize.py         PyKX values → JSON
│   ├── artifacts.py         PDF custody, path whitelist
│   ├── errors.py            the one error shape
│   ├── main.py              the endpoints
│   ├── __init__.py          sets PYKX_THREADING before pykx loads ← read this
│   └── static/              index.html · app.js · styles.css
│
├── kdb/                     ── kdb+ gateway, verified on KDB-X 5.0 ──
│   ├── start.q              loader
│   ├── data.q               loads the NASDAQ bars, derives chg_pct
│   ├── lib.q                shared helpers every report calls
│   ├── gateway.q            reads the catalog, loads q_file, .z.pg, .Q.trp
│   └── reports/             one .q file per report, named by the catalog
│
└── tests/
    ├── conftest.py          boots a real kdb+ gateway per session
    └── test_api.py          44 end-to-end tests against real kdb+
```

---

## 12. The six reports

| Report | Formats | Parameters | What it does |
|---|---|---|---|
| Daily Closing Prices | table | date range, symbols | OHLCV + daily % change per symbol |
| Top Movers | table | date, direction, rows/side, min volume | Biggest gainers and losers on one date |
| Volume Leaders | table | date range, top N | Ranked by total volume, with notional |
| Symbol Statistics Summary | table | date range, symbols, min obs | Return, annualised vol, high/low per symbol |
| Market Breadth | table, html | date range | Advancers / decliners / unchanged per day |
| Symbol Tearsheet | **pdf**, html | symbol, date range | One-page research summary with charts |

The tearsheet is the one to look at first — it exercises the whole PDF path from
kdb writing a file to the browser streaming it through a token.
