"""Configuration, all overridable by environment variable."""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


# --- KDB / Sandbox IPC endpoint
KDB_HOST = os.environ.get("KDB_HOST", "127.0.0.1")
KDB_PORT = _int("KDB_PORT", 5000)
KDB_USER = os.environ.get("KDB_USER", "reportapp")
KDB_PASSWORD = os.environ.get("KDB_PASSWORD", "")

# Handles kept open. kdb+ evaluates on one thread, so a big pool buys nothing
# except queued messages -- it exists for isolation, not parallelism.
POOL_SIZE = _int("KDB_POOL_SIZE", 4)
# Ceiling on the per-report timeout in data/reports.csv.
MAX_TIMEOUT_S = _float("KDB_MAX_TIMEOUT_S", 120.0)
CONNECT_TIMEOUT_S = _float("KDB_CONNECT_TIMEOUT_S", 5.0)

# --- catalog
DATA_DIR = os.environ.get("REPORT_DATA_DIR", os.path.join(ROOT, "data"))
REPORTS_CSV = os.path.join(DATA_DIR, "reports.csv")
PARAMS_CSV = os.path.join(DATA_DIR, "report_params.csv")
# Dataset date range is read from kdb and cached this long, so @max_date
# defaults follow the data without a round trip on every form load.
RANGE_TTL_S = _float("REPORT_RANGE_TTL_S", 60.0)

# --- generated artefacts
# Must match KDB_REPORT_DIR on the kdb+ side. Any path kdb returns is rejected
# unless it resolves to somewhere inside this directory.
REPORT_DIR = os.path.abspath(
    os.environ.get("KDB_REPORT_DIR", os.path.join(ROOT, "var", "reports"))
)
ARTIFACT_TTL_S = _float("REPORT_ARTIFACT_TTL_S", 3600.0)

STATIC_DIR = os.path.join(ROOT, "app", "static")

