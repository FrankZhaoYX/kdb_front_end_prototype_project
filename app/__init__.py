"""Package init -- this runs before anything imports PyKX, which matters.

PyKX in licensed mode refuses to open or use a socket from any thread but the
main one:

    QError: nosocket: Cannot open or use a socket on a thread other than main.

FastAPI serves every request from a threadpool, so without this the first
report call fails. PYKX_THREADING=1 makes PyKX run q on its own dedicated
thread and marshal calls onto it, which is the supported way to use a
connection from many threads. It has to be set *before* `import pykx`, so it
lives here rather than in config.py.

Side effects worth knowing:
  * `kx.shutdown_thread()` must be called at exit or the process hangs; see
    the shutdown hook in main.py.
  * All q calls serialise through that one thread. That costs nothing here --
    kdb+ evaluates on a single thread anyway, so the work was already serial.

The alternative is unlicensed mode (PYKX_UNLICENSED=1), where sockets work
from any thread because there is no embedded q. It is rejected because
indexing a returned q dictionary by key needs q evaluation, which unlicensed
mode cannot do -- the envelope would have to be taken apart positionally.
"""
import os

os.environ.setdefault("PYKX_THREADING", "1")
# Suppresses the KDB-X community banner on every worker import.
os.environ.setdefault("PYKX_NO_SIGNAL", "1")
