# System Design

Why this system is shaped the way it is. [MANUAL.md](MANUAL.md) covers how to run
and test it; this document covers the decisions, the alternatives that were
rejected, and what was deliberately left out.

---

## 1. Requirements

A user needs to pick a report, supply parameters, and get output back.

| # | Requirement | Where it is met |
|---|---|---|
| R1 | Choose **or search** which report to generate | Two-level selector, backed by `/api/reports?q=` |
| R2 | Report list and parameters held in **CSV or similar**, simple now, extensible later | `data/reports.csv` + `data/report_params.csv` |
| R3 | Front-end hits an endpoint, which passes typed parameters to KDB to build the query | `POST /api/run` → `.rpt.run[id;params;maxRows;fmt]` |
| R4 | Input and server errors handled on **both** sides | One envelope, one error shape — §6 |
| R5 | Lightweight front-end stack, not heavy | One HTML + one JS + one CSS file, no build step |
| R6 | Return PDF / HTML / table; PDF generated server-side then fetched | Three formats, one envelope — §5 |

Team context: KDB is reached through an internal **Sandbox IPC layer**, not
directly. The gateway calls *through* it rather than around it.

---

## 2. Options considered

| Plan | Shape | Verdict |
|---|---|---|
| **A** | Python middle tier (FastAPI) + thin HTML front-end | **Chosen** |
| B | No middle tier — kdb serves HTTP directly via `.z.ph`/`.z.pp` | Rejected |
| C | Node/Express + `node-q` | Rejected |
| D | Standalone **q** report gateway serving HTTP itself | Viable; folded into A |

### Why not B (kdb-native HTTP)

Fewest moving parts, and tempting. Rejected because:

- **kdb+ is single threaded.** The HTTP server shares the main thread with query
  execution, so one 30-second report blocks every other user's *page load*, not
  just their query.
- Auth is `.z.pw` basic-only; TLS, SSO, binary streaming and multipart are all
  hand-rolled.
- kdb builds the whole response in memory — no streaming — so a large PDF is a
  heap spike on the same process serving the UI.
- The Sandbox IPC layer likely exists precisely so front-ends do not open
  sockets onto KDB. Bypassing it is a governance question, not a technical one.

### Why not C (Node)

`node-q` is thinner than the Python options and needs more hand-written type
mapping, temporal types especially. No compensating advantage here.

### The performance question that decided A vs the alternatives

The initial instinct was that a Python middle tier would be slow, and that
serving from kdb would be faster. The hop is real but small — single-digit
milliseconds against a query measured in seconds.

The cost that actually matters is **which process pays for JSON encoding**.
`.j.j` on a large table is not fast and runs on kdb's main thread — the one
resource that cannot be scaled. `orjson` in a middle tier is typically faster
*and* runs somewhere you can add processes freely. The performance argument
therefore points at a middle tier, not away from it.

### PyKX as the transport

The middle tier talks to kdb+ with **PyKX** (`kx.SyncQConnection`), calling the
functions in `kdb/*.q` by name with typed parameters. `app/kdbclient.py` is the
only module that imports `pykx`, so the transport remains a single-file concern.

PyKX earns its place here on type fidelity: symbols arrive as `str`, dates as
`datetime.date`, and `Table.py()` gives a column-oriented dict directly. That
removed most of the serialisation layer a hand-rolled IPC client needs.

Four PyKX behaviours shape the client — see §7.1; each one is a silent failure
if you do not know about it.

---

## 3. Architecture

```
BROWSER                    MIDDLE TIER (FastAPI)                 KDB
   │                                │                             │
   │ GET /api/reports               │  read the catalog CSVs      │
   │<───────────────────────────────│                             │
   │ GET /api/reports/{id}          │  resolve @max_date tokens   │
   │<─── parameter specs ───────────│                             │
   │                                │                             │
   │ POST /api/run                  │                             │
   │───────────────────────────────>│ 1. look up report in catalog│
   │                                │ 2. coerce each param to a   │
   │                                │    q type; reject bad ones  │
   │                                │    BEFORE touching kdb      │
   │                                │ 3. .rpt.run[id;dict;max;fmt]│
   │                                │────────────────────────────>│
   │                                │                             │ .Q.trp
   │                                │<─── one envelope ───────────│
   │<─── columns + rows ────────────│                             │
```

| Layer | Module | Responsibility |
|---|---|---|
| Front-end | `app/static/` | Render the catalog, build the form, display results and errors |
| API | `app/main.py` | Routing only; no business logic |
| Catalog | `app/catalog.py` | Load + hot-reload the CSVs, resolve `@date` tokens |
| Validation | `app/validate.py` | Coerce JSON to q types, enforce catalog rules |
| Transport | `app/kdbclient.py` | PyKX handle pool keyed by timeout, error mapping |
| Encoding | `app/serialize.py` | PyKX values → JSON |
| Artefacts | `app/artifacts.py` | Custody of files kdb wrote to disk |
| Gateway | `kdb/gateway.q` | `.z.pg`, allow list, `.Q.trp`, envelope construction |
| Reports | `kdb/reports.q` | The queries themselves |

---

## 4. The three invariants

Everything else follows from these.

### 4.1 The browser never sends q code

It sends a `report_id` and a parameter object. The catalog maps
`report_id → q function name`; the client cannot name a function. Parameters
cross the wire as **typed q values**, never concatenated into a query string.

This makes injection *structurally* impossible rather than a filtering problem.
There are two independent guards on the q side:

```q
.gw.allow:`.rpt.run`.rpt.symbols`.rpt.range`.rpt.ping`.rpt.sleep;  / what may be named
.rpt.fn:`daily_close`top_movers`...!`.rpt.dailyClose`.rpt.topMovers`...;  / what may be run
```

### 4.2 One envelope for every output format

```q
`status`report`format`payload`meta!(`ok; `top_movers; `table; <data>; <meta>)
```

`format` is `` `table ``, `` `html `` or `` `pdf ``; errors reuse the shape with
``status:`err``. The front-end has one code path.

### 4.3 The catalog is the contract

Both sides read it. A new report is two CSV rows plus a q function — no Python,
no JavaScript. The CSVs hot-reload on mtime change.

---

## 5. Decisions

### 5.1 Catalog storage

| Option | Non-dev editable | Nested params | Verdict |
|---|---|---|---|
| **Two CSVs** | Excel ✅ | via the join | **Chosen** |
| One YAML/JSON | text editor only | ✅ native | Better structure, worse for report owners |
| A kdb table | ❌ | awkward | Needs a KDB round trip just to draw a form |

Parameters are one-to-many with reports, so a single CSV would force ugly
encoding. Two files keep the join explicit and both stay spreadsheet-editable.

**Consequence:** kdb's `0:` has no concept of a quoted field, so the generated
data files must be unquoted and ASCII — see `q_safe()` in
`scripts/build_data.py`. A comma inside a company name would silently shift
every column to its right.

### 5.2 Date tokens

Defaults and bounds may be `@min_date`, `@max_date`, `@max_date-30d`, `@today`,
resolved per request against the range kdb reports and clamped into the dataset.
The form therefore opens on dates that actually have data, and a default can
never produce an empty report.

### 5.3 Output formats

Table first, then PDF; HTML is the one to skip if effort is short — it tends to
be a worse PDF or a worse table. Results go out **column-oriented**
(`columns` + `rows`): smaller on the wire than a list of objects, and it hands
the grid the types it needs to right-align numbers.

### 5.4 PDF transport

kdb writes the file and returns a **path**. Three ways to get it to the user:

| | Approach | Verdict |
|---|---|---|
| a | Shared filesystem; the app streams the path | **Chosen** — cheap, streams properly |
| b | Bytes back over IPC (`read1`) | No mount needed, but materialises the file in kdb's heap |
| c | Object store + presigned URL | Right answer if this goes multi-host |

The browser never sees the path. It is validated, registered under an opaque
token, and the client gets `/api/download/<token>`. `safe_path()` resolves
symlinks and `..` **before** the prefix check, so `/reports/../../etc/passwd`
and a symlink escaping the directory both fail. That check is the entire
security boundary for this format, which is why it lives in the app and not in
kdb.

Also: `.rpt.outDir` is forced absolute at load time. A relative path would be
joined onto the app's `REPORT_DIR` a second time and never found.

### 5.5 Rounding

Reports return presentation-ready numbers, rounded in the backend. This keeps
payloads small and lets the q and Python implementations agree to the last
digit. q uses `"j"$`, which rounds half-to-even, matching `numpy.round` and
Python's `round()`.

---

## 6. Error model

One shape for every failure the browser can see:

```json
{"status":"err","code":"unknown_symbol",
 "message":"not in the NASDAQ universe: NOTREAL","field":"symbols"}
```

**`field` set → render under that input. No `field` → banner.** That is the
whole front-end contract.

### Where validation lives

The split is deliberate:

- **The app** validates what the catalog knows — types, ranges, enums,
  required-ness — and rejects those **before opening a socket**. Bad input never
  reaches kdb.
- **kdb** validates what only it knows — does this symbol exist, is this a
  business date, did anything match.

Both produce the same envelope, so the UI cannot tell, and does not care, which
side said no.

| Code | HTTP | Raised by |
|---|---|---|
| `invalid_param`, `unknown_report`, `unsupported_format` | 400/404 | app |
| `unknown_symbol`, `invalid_range`, `no_data_for_date`, `empty_result` | 400 | kdb |
| `kdb_timeout` | 504 | app |
| `kdb_unavailable` | 502 | app |
| `report_error` | 500 | app (kdb signalled) |
| `artifact_missing` | 404 | app |

### Timed-out handles are poisoned

When a sync call times out the reply is **still in flight**. Reusing that handle
would return the previous call's result and desynchronise every later call on
it. `app/kdbclient.py` therefore closes a timed-out handle instead of returning
it to the pool. A `QException` is the opposite case — kdb answered, the answer
was an error — and that handle goes straight back. There is a test for each.

---

## 7. Transport and the IPC entry point

### 7.1 PyKX behaviours the client is built around

| Behaviour | Consequence |
|---|---|
| The **context interface probes the server on connect** to enumerate namespaces | `.gw.allow` rejects the probe with `'access` and the connection cannot be constructed. The client passes `no_ctx=True`. Widening the allow list to satisfy a client convenience would weaken the only guard stopping a caller naming arbitrary q functions. |
| In licensed mode, **sockets cannot be opened or used off the main thread** (`'nosocket`) | Fatal for FastAPI, which serves from a threadpool. `PYKX_THREADING=1` is set in `app/__init__.py` *before* `import pykx`, and `kx.shutdown_thread()` runs on shutdown or the process hangs. |
| The **timeout is fixed when the connection is opened**, not per call | Assigning `conn._timeout` later looks like it works and silently does nothing. Since each report declares its own `timeout_s`, idle connections are pooled **per timeout value**. |
| A **timed-out call does not desynchronise the handle** | PyKX discards the pending reply, so the connection is reusable. Unlike a hand-rolled client, no handle has to be thrown away on timeout — but kdb+ is still busy, so the next call queues behind it. |

Unlicensed mode (`PYKX_UNLICENSED=1`) would avoid the threading restriction
entirely, since there is no embedded q and sockets are ordinary Python sockets.
It is rejected because indexing a returned q dictionary by key requires q
evaluation, which unlicensed mode cannot do — the response envelope would have
to be taken apart positionally.

### 7.2 The handlers

`.z.pg` is the whole interaction surface. The other handlers were considered and
deliberately not used:

| Handler | Used | Reasoning |
|---|---|---|
| `.z.pg` | **yes** | Sync handler: allow-list check, then dispatch |
| `.z.ps` | **yes — to refuse** | Async has no reply. The browser is holding an HTTP request open; evaluating an async message would compute a result and drop it, leaving the caller to time out. Refusing turns a mysterious hang into an immediate error. |
| `.z.pw` | yes | Auth stub, returns `1b`. Replace before this leaves a sandbox |
| `.z.po` / `.z.pc` | yes | Connection logging, with `.z.a` for the peer address |
| `.z.w` | **no** | Unnecessary in a synchronous design: whatever `.z.pg` returns is sent back on the calling handle automatically. `.z.w` only earns its place when replying *later* than the handler returns |
| `.z.W` | no | Its real use is checking a handle is still open before a deferred write, and watching queue depth |

`.z.w`, `.z.W` and a serving `.z.ps` all become necessary together, in the async
job model below — and not before.

---

## 8. Concurrency: what was deferred

Execution is **synchronous**. `POST /api/run` blocks until kdb answers. That is
correct while every report here is sub-10 ms, and wrong for a report measured in
minutes: browser and proxy timeouts, and a blocked q process.

The response envelope already carries what a `202 + job_id + poll` model needs,
so the change stays confined to the gateway and the middle tier. Sketch:

```q
.rpt.submit:{[rid;p;maxRows;fmt]
  id:.job.next+:1;
  .job.handle[id]:.z.w;                / who asked
  .job.queue,:enlist (id;rid;p;maxRows;fmt);
  id};

.job.finish:{[id;envelope]
  h:.job.handle id;
  if[h in key .z.W; -30!(h; 0b; envelope)];   / deferred response
  .job.handle:.job.handle _ id;};
```

`-30!` is recognised on KDB-X 5.0, but this flow is **not implemented or
tested**. Note it cannot work through `scripts/serve_q.py`, which calls `.z.pg`
itself and owns the socket — testing it needs a standalone `q`.

**Recommendation:** stay synchronous until a report genuinely takes minutes.

Other deliberate omissions: **no authentication** (`.z.pw` returns `1b`; put
nginx in front for TLS and SSO), and **no rate limiting**.

---

## 9. Deployment shape

The gateway must be a **separate q process** from the production KDB server.
kdb+ evaluates on one thread, so whichever process runs reports is blocked while
they run. Keeping it separate contains that to report users.

The PDF path shows this concretely: generating a tearsheet shells out to an HTML
converter and takes ~3 s, during which that q process serves nobody.

For parallelism, run several gateway processes behind nginx — which is also
where TLS, auth and static files belong.

---

## 10. Testing strategy

There is **one** implementation and the tests run against it:

```bash
make test
```

43 end-to-end tests. Each boots a real kdb+ gateway, then drives the real
FastAPI app through PyKX over a real socket. Nothing is stubbed, and there is no
second implementation to drift out of sync with the q code.

`scripts/serve_q.py` hosts `kdb/*.q` on a socket using embedded KDB-X, because
KDB-X ships as a library rather than a standalone `q` binary. Set
`KDB_TEST_PORT` to run the same suite against a gateway you started yourself —
including a real `q kdb/start.q -p 5000` on another host.
