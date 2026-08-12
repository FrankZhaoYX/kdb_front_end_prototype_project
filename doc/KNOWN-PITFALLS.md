# Known Pitfalls

Every entry here was a real failure mode hit while building the reference
implementation — most were silent or produced a confusing error far from the
actual cause. Check this list before spending tokens on trial and error.

## q language

**A bare `/` on its own line comments out the rest of the file, silently.**
q's block comment starts at a line containing only `/` and runs until a line
containing only `\`. Using `/` alone as a visual section separator (a habit
carried over from other languages) will blank everything after it — `\l`
returns cleanly and defines nothing, with no error at all. Use `/-` or put
real text on the line instead.

**`rank` and `meta` are q reserved words.** `update rank:1+til count t from
t` or a local variable named `meta` inside a function both signal `'assign`.
Build the column under a different name (e.g. `rnk`) and rename it last with
`xcol`, which takes symbols rather than parsed identifiers and so can
produce a name the parser itself would reject:
```q
(enlist[`rnk]!enlist[`rank]) xcol t
```

**A symbol literal cannot start with an underscore.** `` `_format `` does
not tokenise as one symbol — q reads it as the empty symbol `` ` `` followed
by the bare identifier `format`, and signals `'format`. This is why output
format in this project is a **positional argument** to `.rpt.run` rather than
a magic key inside the parameter dictionary.

**kdb's `0:` CSV reader has no quoted-field support.** A comma inside any
value — a company name, a report description — silently shifts every column
after it to the right. There is no error; the data is just wrong. Every
value in `data/*.csv` must be comma-free by construction.

**A relative output directory path breaks round-tripping.** If a q function
returns a relative path (e.g. `var/reports/foo.pdf`) and the caller joins it
onto its own base directory before checking it exists, you get double-joined
paths that are never found. Resolve any such path to absolute at load time
on the q side.

## PyKX

**`no_ctx=True` is required when connecting to a restricted gateway.** PyKX's
context interface probes the server on connect to enumerate its namespaces.
If the gateway's `.z.pg` allow-list doesn't include what that probe needs
(and it shouldn't, since widening the allow list just to satisfy a client
convenience defeats its purpose), the connection fails with `'access` before
you ever get to make a real call. Pass `no_ctx=True`.

**Licensed-mode PyKX refuses sockets off the main thread.** Any attempt to
open or use a `SyncQConnection` from a non-main thread raises `QError:
nosocket: Cannot open or use a socket on a thread other than main.` FastAPI
serves every request from a threadpool, so this is fatal unless handled. Fix:
set `PYKX_THREADING=1` in the environment **before** `import pykx` happens
anywhere in the process (do this at the very top of your package's
`__init__.py`, since Python only imports a module once). Call
`kx.shutdown_thread()` on process shutdown or the interpreter will hang on
exit.

**A PyKX connection's timeout is fixed at construction, not mutable per
call.** Setting `conn._timeout = 5.0` after the connection is open looks like
it works and silently does nothing — PyKX reads the value once while
configuring the socket. If different calls need different timeouts, either
open a new connection per timeout value, or pool connections keyed by the
timeout they were opened with (the reference implementation does the
latter).

**A timed-out call does not desynchronise the connection.** Unlike some
hand-rolled IPC clients, PyKX discards the pending reply when a call times
out, so the same connection can be reused safely for the next call — you do
not need to close and reopen it on timeout, only on an actual connection
failure (`OSError`/`EOFError`).

**Assigning attributes on a `no_ctx=True` connection can raise.** PyKX's
`__setattr__` on a connection object routes unknown attribute names through
the (now-disabled) context interface. A plain `conn._timeout = x` can raise
`"Attempted to use context interface after disabling it."` Use
`object.__setattr__(conn, "_timeout", x)` to bypass that routing when you
must set an internal attribute directly.

## Environment / platform

**Installing `pykx` triggers a network call to KX's license service** the
first time it runs in licensed mode, to fetch a free KDB-X Community
license, unless one is already provisioned via `QLIC`/`QHOME`. On a
network-restricted machine this can hang or fail with no clear message.
Confirm this is compliant *before* starting the build, not after hitting the
failure.

**Port 5000 is frequently already in use on macOS** — Control Centre's
AirPlay Receiver listens on it by default. Prefer picking a free port
dynamically (or falling back to one) over hardcoding 5000 and assuming it's
free.

**FastAPI's `StaticFiles` sends `ETag`/`Last-Modified` but no
`Cache-Control`.** Browsers will happily serve a stale `app.js`/`styles.css`
after you've edited it, with no visible sign anything is wrong — the page
just doesn't reflect your change. Add a small middleware that sets
`Cache-Control: no-cache, must-revalidate` on `/static/*` responses so
browsers always revalidate.

**Shell scripts in this project (`*.sh`) are bash**, written and tested on
macOS. If the target machine is Windows, they need porting (PowerShell, or
run under WSL/Git Bash) — don't assume they'll "just work" under `cmd.exe`
or that skipping them is harmless; they're what starts the dev stack.
