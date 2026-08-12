"""PyKX IPC client: a small pool of handles onto the kdb+ report gateway.

The middle tier never evaluates q. It opens a connection and calls the
functions defined in kdb/*.q by name, passing already-typed parameters:

    conn('.rpt.run', report_id, params, max_rows, fmt)

Two PyKX specifics worth knowing.

**no_ctx=True is required.** PyKX's context interface probes the remote server
on connect to enumerate its namespaces. kdb/gateway.q only permits the handful
of names in `.gw.allow`, so that probe is rejected with 'access and the
connection fails to construct. Disabling the probe is the right fix -- widening
the allow list to satisfy a client convenience would weaken the one guard that
stops a caller naming arbitrary q functions.

**The timeout is fixed when the connection is opened, not per call.** Assigning
`conn._timeout` later looks like it works and silently does nothing -- PyKX
reads it while configuring the socket and never again. Since each report
declares its own `timeout_s`, idle connections are therefore pooled *per
timeout value*; there are only a handful of distinct ones in the catalog.

**A timed-out call does not poison the handle.** PyKX discards the pending
response, so the next call on the same connection still gets its own answer.
(Verified: after a 1s timeout on a 4s report, the following call returned the
correct result -- having waited ~3s for the server to finish, because kdb+ is
single threaded and was still busy.) That means no handle needs to be thrown
away on timeout, unlike a hand-rolled qPython client.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Optional

import pykx as kx

from . import config
from .errors import KdbTimeout, KdbUnavailable, ReportError

log = logging.getLogger("app.kdb")

# PyKX signals a client-side timeout as a QError carrying this text, which is
# how a slow report is told apart from a q-side error.
_TIMEOUT_MARKERS = ("timed out", "timeout")


class KdbPool:
    """Handles onto one kdb+ gateway.

    kdb+ evaluates on a single thread, so the pool exists for isolation -- one
    dead handle must not take the service down -- not for parallelism the
    server cannot provide.
    """

    def __init__(self, host=None, port=None, user=None, password=None, size=None):
        self.host = host or config.KDB_HOST
        self.port = int(port or config.KDB_PORT)
        self.user = user if user is not None else config.KDB_USER
        self.password = password if password is not None else config.KDB_PASSWORD
        self.size = int(size or config.POOL_SIZE)
        # timeout value -> idle connections opened with that timeout
        self._idle: "dict[float, queue.LifoQueue]" = {}
        self._lock = threading.Lock()
        self._open = 0
        self.opened = 0
        self.discarded = 0

    # ------------------------------------------------------------- handles
    def _bucket(self, timeout: float) -> "queue.LifoQueue":
        with self._lock:
            return self._idle.setdefault(round(float(timeout), 3), queue.LifoQueue())

    def _connect(self, timeout: float) -> kx.SyncQConnection:
        try:
            conn = kx.SyncQConnection(
                self.host,
                self.port,
                username=self.user or "",
                password=self.password or "",
                timeout=timeout,      # fixed for the life of this connection
                no_ctx=True,          # see the module docstring
            )
        except Exception as e:
            raise KdbUnavailable(
                "cannot reach kdb at %s:%d" % (self.host, self.port),
                detail="%s: %s" % (type(e).__name__, e),
            )
        with self._lock:
            self._open += 1
            self.opened += 1
        log.info("opened handle to %s:%d (timeout %.1fs)", self.host, self.port,
                 timeout)
        return conn

    def _acquire(self, timeout: float) -> kx.SyncQConnection:
        bucket = self._bucket(timeout)
        while True:
            try:
                conn = bucket.get_nowait()
            except queue.Empty:
                return self._connect(timeout)
            if not getattr(conn, "closed", False):
                return conn
            self._drop(conn)

    def _release(self, conn, timeout: float) -> None:
        bucket = self._bucket(timeout)
        if bucket.qsize() >= self.size:
            self._drop(conn)
        else:
            bucket.put(conn)

    def _drop(self, conn) -> None:
        with self._lock:
            self._open = max(0, self._open - 1)
            self.discarded += 1
        try:
            conn.close()
        except Exception:
            pass

    def close(self) -> None:
        with self._lock:
            buckets = list(self._idle.values())
        for bucket in buckets:
            while True:
                try:
                    self._drop(bucket.get_nowait())
                except queue.Empty:
                    break

    # ---------------------------------------------------------------- call
    def call(self, fname: str, *args, timeout: float = 30.0) -> Any:
        """One sync call. Every failure mode becomes an ApiError."""
        conn = self._acquire(timeout)
        try:
            t0 = time.perf_counter()
            result = conn(fname, *args)
            log.debug("%s took %.1fms", fname, (time.perf_counter() - t0) * 1000)
        except kx.exceptions.QError as e:
            message = str(e)
            if any(m in message.lower() for m in _TIMEOUT_MARKERS):
                # The handle stays usable -- PyKX drops the pending reply -- but
                # kdb is still working, so the next caller may queue behind it.
                self._release(conn, timeout)
                raise KdbTimeout(
                    "the report did not finish within %.0fs" % timeout,
                    detail="kdb is still working on it; it is single threaded, "
                           "so other requests may queue behind this one",
                )
            self._release(conn, timeout)
            raise ReportError("kdb signalled '%s" % message, detail=message)
        except (OSError, EOFError, RuntimeError) as e:
            self._drop(conn)
            raise KdbUnavailable(
                "lost the connection to kdb at %s:%d" % (self.host, self.port),
                detail="%s: %s" % (type(e).__name__, e),
            )
        else:
            self._release(conn, timeout)
            return result

    # --------------------------------------------------------------- stats
    def stats(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "idle": sum(b.qsize() for b in self._idle.values()),
            "timeout_buckets": sorted(self._idle),
            "open": self._open,
            "opened_total": self.opened,
            "discarded_total": self.discarded,
        }


class RangeCache:
    """Caches .rpt.range[] so form defaults cost one round trip per TTL."""

    def __init__(self, pool: KdbPool, ttl: float = None):
        self.pool = pool
        self.ttl = config.RANGE_TTL_S if ttl is None else ttl
        self._value: Optional[dict] = None
        self._at = 0.0
        self._lock = threading.Lock()

    def get(self, force: bool = False) -> Optional[dict]:
        now = time.time()
        with self._lock:
            if not force and self._value and (now - self._at) < self.ttl:
                return self._value
        try:
            from .serialize import to_json
            value = to_json(self.pool.call(".rpt.range", timeout=10.0))
        except Exception as e:
            log.warning("could not refresh dataset range: %s", e)
            with self._lock:
                return self._value  # stale beats nothing
        with self._lock:
            self._value = value
            self._at = now
        return value
