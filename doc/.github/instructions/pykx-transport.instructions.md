---
applyTo: "app/kdbclient.py,app/__init__.py,scripts/serve_q.py"
---

# PyKX transport rules

Full narrative detail is in `KNOWN-PITFALLS.md` §"PyKX". Condensed checklist:

- **`PYKX_THREADING=1` must be set in the environment before `import pykx`
  runs anywhere in the process.** It lives in `app/__init__.py` because that
  module is guaranteed to import first. Do not move this logic later in the
  import chain, and do not remove it — without it, any PyKX call made from
  FastAPI's threadpool raises `'nosocket`.
- **Call `kx.shutdown_thread()` on application shutdown.** Its absence hangs
  the process on exit. Check `app/main.py`'s shutdown handler is still
  wired to this if you touch startup/shutdown logic.
- **Always connect with `no_ctx=True`.** Without it, PyKX's context-interface
  probe on connect gets rejected by the gateway's allow-list and the
  connection never even opens (`'access`).
- **Never assume a connection's timeout can change after it's opened.** It's
  fixed at construction. `app/kdbclient.py`'s pool is keyed by timeout value
  for exactly this reason — if you add a new call site with a different
  timeout, make sure it goes through the pool, not a fresh ad-hoc
  connection with an assumption that timeouts are mutable.
- **Do not add handle-discard-on-timeout logic.** Unlike some hand-rolled
  IPC clients, a PyKX connection that just timed out is still safe to reuse
  — the pending reply is discarded, not left desynchronising the socket.
  Only discard a connection on an actual `OSError`/`EOFError`.
- **If you must set an attribute on a `no_ctx=True` connection directly**
  (rare — only needed for the timeout workaround above), use
  `object.__setattr__(conn, name, value)`, not a plain assignment; the
  latter can route through the disabled context interface and raise.
