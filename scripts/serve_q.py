"""Serve the *real* kdb/*.q gateway over IPC, backed by embedded kdb+.

KDB-X ships as an embedded library (PyKX's libq) rather than a standalone `q`
binary, so `q kdb/start.q -p 5000` is not available on this machine. This
bridge closes that gap: it accepts genuine kdb+ IPC connections and answers
them out of a real q interpreter running kdb/data.q, reports.q and gateway.q.

    python3 scripts/serve_q.py -p 5000

The trick is that no value is ever converted between Python and q. The client's
message bytes go straight into q's own deserialiser and the answer comes back
out of its own serialiser:

    -9!  raw request bytes  ->  the exact q value the client sent, types intact
    .z.pg                   ->  the real gateway handler, allow list and all
    -8!  the result         ->  wire bytes, header included

So the middle tier is talking to kdb+ proper: same `.z.pg`, same `.Q.trp`, same
q-computed numbers. Only the socket accept loop is Python.

All q work runs on one dedicated thread, because embedded q is single threaded
-- which is also exactly how a real q process behaves, and is required for
`system` calls, which kdb+ refuses off the main thread with 'sys.
"""
from __future__ import annotations

import argparse
import logging
import os
import socket
import queue
import socketserver
import struct
import sys
import threading

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
log = logging.getLogger("serve_q")

kx = None  # set on the q thread, after chdir so relative data paths resolve

SYNC, RESPONSE = 1, 2

# Every q call runs on ONE dedicated thread, for two reasons. It is what a real
# q process does -- kdb+ evaluates on its main thread -- and kdb+ refuses some
# operations off it: `system` signals 'sys when called from a secondary thread,
# which is how .rpt.sleep first failed here. Connection handlers therefore hand
# work to this thread and wait for the answer.
_WORK: "queue.Queue" = None  # created in main()
_READY = threading.Event()
_INIT_ERROR = [None]


def _as_bytes(v) -> bytes:
    """PyKX byte vector -> bytes."""
    if isinstance(v, (bytes, bytearray)):
        return bytes(v)
    return bytes(bytearray(v))


def error_message(msg: str) -> bytes:
    """Hand-build a kdb+ error response: type -128, then a null-terminated string.

    -8! cannot serialise a signal, so this is the one frame the bridge writes
    itself. Byte 0x80 is the -128 type marker the client's reader looks for.
    """
    body = b"\x80" + msg.encode("latin-1", "replace") + b"\x00"
    return struct.pack("<BBBBI", 1, RESPONSE, 0, 0, 8 + len(body)) + body


def _evaluate_on_q_thread(raw: bytes) -> bytes:
    """Runs only on the q thread. One request frame in, one response frame out."""
    out = kx.q(
        '{@[{(1b;-8!.z.pg -9!x)}; x; {(0b; x)}]}',
        np.frombuffer(raw, dtype=np.uint8),
    )
    if not bool(out[0].py()):
        sig = out[1].py()
        if isinstance(sig, bytes):
            sig = sig.decode("latin-1")
        log.info("q signalled '%s", sig)
        return error_message(str(sig))
    resp = bytearray(_as_bytes(out[1].py()))
    resp[1] = RESPONSE  # -8! stamps msg type 0; the client expects a response
    return bytes(resp)


def q_thread(files) -> None:
    """Owns the embedded q interpreter for the life of the process."""
    global kx
    try:
        os.chdir(ROOT)
        import warnings
        warnings.filterwarnings("ignore")
        import pykx as kx_  # noqa: N813
        kx = kx_
        for f in files:
            kx.q('system"l %s"' % f)
            log.info("loaded %s", f)
        log.info("kdb+ %s, %s rows, %s symbols",
                 kx.q(".z.K").py(),
                 format(kx.q("count daily").py(), ","),
                 kx.q("count .dat.symUniverse").py())
    except Exception as e:
        _INIT_ERROR[0] = e
        _READY.set()
        return
    _READY.set()

    while True:
        item = _WORK.get()
        if item is None:
            return
        raw, reply = item
        try:
            reply.put(("ok", _evaluate_on_q_thread(raw)))
        except Exception as e:  # a bridge failure, not a q signal
            log.exception("bridge error")
            reply.put(("err", e))


def evaluate(raw: bytes) -> bytes:
    """Called from a connection thread; never raises."""
    reply: "queue.Queue" = queue.Queue(1)
    _WORK.put((raw, reply))
    kind, value = reply.get()
    if kind == "ok":
        return value
    return error_message("bridge-error: %s" % value)


class Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        peer = "%s:%s" % self.client_address[:2]
        sock: socket.socket = self.request
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if not self._handshake(sock):
            return
        log.info("[%s] connected", peer)
        try:
            while True:
                header = self._recv_exactly(sock, 8)
                if not header:
                    break
                little = header[0] == 1
                msg_type = header[1]
                (size,) = struct.unpack("<I" if little else ">I", header[4:8])
                body = self._recv_exactly(sock, size - 8)
                if body is None:
                    break
                resp = evaluate(header + body)
                if msg_type == SYNC:
                    sock.sendall(resp)
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            log.info("[%s] disconnected", peer)

    @staticmethod
    def _recv_exactly(sock: socket.socket, n: int):
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                return None if buf else b""
            buf += chunk
        return buf

    @staticmethod
    def _handshake(sock: socket.socket) -> bool:
        buf = b""
        sock.settimeout(10.0)
        try:
            while not buf.endswith(b"\x00"):
                c = sock.recv(1)
                if not c:
                    return False
                buf += c
                if len(buf) > 2048:
                    return False
        except socket.timeout:
            return False
        finally:
            sock.settimeout(None)
        ver = buf[-2] if len(buf) >= 2 else 0
        if ver > 6:
            ver = 0
        sock.sendall(struct.pack("B", min(ver, 3)))
        return True


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Serve kdb/*.q over IPC using embedded kdb+ (KDB-X)"
    )
    ap.add_argument("-p", "--port", type=int,
                    default=int(os.environ.get("KDB_PORT", 5000)))
    ap.add_argument("--host", default=os.environ.get("KDB_HOST", "127.0.0.1"))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    global _WORK
    _WORK = queue.Queue()
    worker = threading.Thread(
        target=q_thread,
        args=(("kdb/data.q", "kdb/reports.q", "kdb/gateway.q"),),
        daemon=True,
        name="kdb+",
    )
    worker.start()
    _READY.wait()
    if _INIT_ERROR[0] is not None:
        log.error("could not start embedded kdb+: %s", _INIT_ERROR[0])
        return 1

    srv = Server((args.host, args.port), Handler)
    log.info("real q gateway listening on %s:%d -- ctrl-c to stop",
             args.host, args.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        srv.shutdown()
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
