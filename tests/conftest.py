"""Boots a real kdb+ gateway, then the app against it over PyKX IPC.

There is no Python mock any more: every test runs against the actual q code in
kdb/*.q. `scripts/serve_q.py` hosts those files on a socket using embedded
KDB-X, because KDB-X ships as a library rather than a standalone `q` binary.

Set KDB_TEST_PORT to run the suite against a server you started yourself --
including a real `q kdb/start.q -p 5000` on another host.

The environment has to be set before app.config is imported, because the pool
reads host/port at import time; hence the local imports inside the fixtures.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_for_port(port: int, deadline: float, proc=None) -> bool:
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return False
        with socket.socket() as s:
            s.settimeout(0.4)
            try:
                s.connect(("127.0.0.1", port))
                return True
            except OSError:
                time.sleep(0.25)
    return False


@pytest.fixture(scope="session")
def kdb_port():
    external = os.environ.get("KDB_TEST_PORT")
    if external:
        yield int(external)
        return

    port = free_port()
    # A separate process, not a thread: embedded kdb+ must own its interpreter,
    # and the app talks to it over a real socket exactly as in production.
    proc = subprocess.Popen(
        [sys.executable if os.environ.get("USE_VENV_Q") else "python3",
         os.path.join(ROOT, "scripts", "serve_q.py"), "-p", str(port)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if not wait_for_port(port, time.time() + 60, proc):
        out = b""
        if proc.poll() is None:
            proc.kill()
        try:
            out = proc.stdout.read()[-2000:]
        except Exception:
            pass
        pytest.fail("kdb gateway did not start on port %d\n%s"
                    % (port, out.decode("utf-8", "replace")))
    yield port
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def client(kdb_port):
    os.environ["KDB_PORT"] = str(kdb_port)
    os.environ["KDB_HOST"] = "127.0.0.1"
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def pool(client):
    from app.main import pool as p
    return p


def run(client, report_id, params=None, fmt=None):
    body = {"report_id": report_id, "params": params or {}}
    if fmt:
        body["format"] = fmt
    return client.post("/api/run", json=body)
