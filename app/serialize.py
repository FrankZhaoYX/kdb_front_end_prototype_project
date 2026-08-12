"""PyKX values -> JSON for the browser.

PyKX does most of the work that a hand-rolled IPC client would leave to us:
symbols arrive as `str`, char vectors as `bytes`, dates as `datetime.date`, and
q nulls as `None` or NaN. So this module is mostly about the last mile --
turning temporals into ISO strings and NaN into null, both of which json.dumps
would otherwise reject or mangle.

Tables go out column-oriented (`columns` + `rows`): smaller on the wire than a
list of objects, and it gives the grid the column types it needs to right-align
numbers without inspecting values.
"""
from __future__ import annotations

import datetime as _dt
import math
from typing import Any, Dict, List

import pykx as kx

# PyKX vector class name -> the hint the front-end grid uses.
_TYPE_HINTS = {
    "SymbolVector": "symbol",
    "CharVector": "text",
    "BooleanVector": "boolean",
    "DateVector": "date",
    "TimestampVector": "date",
    "TimeVector": "date",
    "MonthVector": "date",
    "ShortVector": "number",
    "IntVector": "number",
    "LongVector": "number",
    "RealVector": "number",
    "FloatVector": "number",
}


def qtext(value) -> str:
    """A q symbol or char vector -> str."""
    if isinstance(value, kx.K):
        value = value.py()
    if isinstance(value, (bytes, bytearray)):
        return value.decode("latin-1")
    return str(value)


def scalar(value) -> Any:
    """One already-Python value from PyKX -> something json.dumps accepts."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return value.decode("latin-1")
    if isinstance(value, bool):
        return value
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, _dt.timedelta):
        return value.total_seconds()
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        return {qtext(k): scalar(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scalar(v) for v in value]
    return str(value)


def to_json(value) -> Any:
    """Any PyKX value -> a JSON-safe Python structure."""
    return scalar(value.py() if isinstance(value, kx.K) else value)


def column_type(column) -> str:
    return _TYPE_HINTS.get(type(column).__name__, "text")


def table_to_json(table: "kx.Table") -> Dict[str, Any]:
    """A q table -> {columns:[{name,type}], rows:[[...]]}."""
    data = table.py()                       # dict of column -> list
    names = list(data)
    columns = [{"name": n, "type": column_type(table[n])} for n in names]
    cols = [[scalar(v) for v in data[n]] for n in names]
    rows: List[List[Any]] = [list(r) for r in zip(*cols)] if cols else []
    return {"columns": columns, "rows": rows}
