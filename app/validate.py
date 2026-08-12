"""Parameter validation and coercion to q types.

This is the layer that makes the design safe. The browser sends
`{"report_id": "...", "params": {...}}` -- never q code -- and every value is
coerced here into a typed q atom or vector according to the catalog. The values
then travel over IPC as *data*, so there is no query string to escape and no
injection surface to defend.

Anything that fails becomes a ValidationError carrying the field name, which the
front-end renders next to the offending input. Nothing reaches kdb until every
parameter has passed.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

import pykx as kx

from .catalog import Param, Report
from .errors import UnsupportedFormat, ValidationError


def qsymbol(s: str):
    return kx.SymbolAtom(str(s))


def qsymlist(values: List[str]):
    return kx.SymbolVector([str(v) for v in values])


def qdict(d: Dict):
    """The parameter dictionary as a q dict, keys as symbols."""
    if not d:
        return kx.Dictionary({})
    return kx.Dictionary({kx.SymbolAtom(k): v for k, v in d.items()})


# ------------------------------------------------------------------ scalars
def _date(p: Param, raw):
    if isinstance(raw, (dt.date, dt.datetime)):
        return kx.DateAtom(dt.date(raw.year, raw.month, raw.day))
    s = str(raw).strip()[:10]
    try:
        return kx.DateAtom(dt.date.fromisoformat(s))
    except ValueError:
        raise ValidationError(
            p.param, "%s must be a date as YYYY-MM-DD, got %r" % (p.label, raw)
        )


def _long(p: Param, raw):
    try:
        if isinstance(raw, bool):
            raise ValueError
        if isinstance(raw, str) and not raw.strip():
            raise ValueError
        return kx.LongAtom(int(float(raw)))
    except (TypeError, ValueError, OverflowError):
        raise ValidationError(
            p.param, "%s must be a whole number, got %r" % (p.label, raw)
        )


def _float(p: Param, raw):
    try:
        v = float(raw)
    except (TypeError, ValueError):
        raise ValidationError(
            p.param, "%s must be a number, got %r" % (p.label, raw)
        )
    if v != v:
        raise ValidationError(p.param, "%s must be a number, got NaN" % p.label)
    return kx.FloatAtom(v)


def _bool(p: Param, raw):
    if isinstance(raw, bool):
        return kx.BooleanAtom(raw)
    s = str(raw).strip().lower()
    if s in ("1", "true", "yes", "y", "t"):
        return kx.BooleanAtom(True)
    if s in ("0", "false", "no", "n", "f", ""):
        return kx.BooleanAtom(False)
    raise ValidationError(p.param, "%s must be true or false, got %r" % (p.label, raw))


def _symlist(p: Param, raw):
    if raw is None:
        return qsymlist([])
    if isinstance(raw, str):
        items = [s.strip() for s in raw.replace(";", ",").split(",")]
    elif isinstance(raw, (list, tuple)):
        items = [str(s).strip() for s in raw]
    else:
        raise ValidationError(
            p.param, "%s must be a list of symbols, got %r" % (p.label, raw)
        )
    items = [s for s in items if s]
    for s in items:
        if len(s) > 32 or any(c.isspace() for c in s):
            raise ValidationError(
                p.param, "%s: %r is not a valid symbol" % (p.label, s)
            )
    return qsymlist(items)


def _sym(p: Param, raw):
    s = str(raw).strip()
    if not s:
        raise ValidationError(p.param, "%s is required" % p.label)
    if len(s) > 32 or any(c.isspace() for c in s):
        raise ValidationError(p.param, "%s: %r is not a valid symbol" % (p.label, s))
    return qsymbol(s)


def _enum(p: Param, raw):
    s = str(raw).strip()
    if p.options and s not in p.options:
        raise ValidationError(
            p.param, "%s must be one of: %s" % (p.label, ", ".join(p.options))
        )
    return qsymbol(s)


def _string(p: Param, raw):
    s = str(raw)
    if len(s) > 4096:
        raise ValidationError(p.param, "%s is too long (max 4096 chars)" % p.label)
    return kx.CharVector(s)


COERCE = {
    "date": _date,
    "long": _long,
    "float": _float,
    "bool": _bool,
    "sym": _sym,
    "symlist": _symlist,
    "enum": _enum,
    "string": _string,
}

# What an optional parameter becomes when it is left blank and has no default.
EMPTY = {
    "symlist": lambda: qsymlist([]),
    "sym": lambda: qsymbol(""),
    "long": lambda: kx.LongAtom(0),
    "float": lambda: kx.FloatAtom(0.0),
    "bool": lambda: kx.BooleanAtom(False),
    "string": lambda: kx.CharVector(""),
    "enum": lambda: qsymbol(""),
    "date": lambda: kx.q("0Nd"),
}


# ------------------------------------------------------------------- bounds
def _check_bounds(p: Param, value, resolve) -> None:
    lo, hi = resolve(p.min), resolve(p.max)
    if p.type == "date":
        if lo and value.py() < dt.date.fromisoformat(lo):
            raise ValidationError(
                p.param, "%s cannot be earlier than %s" % (p.label, lo)
            )
        if hi and value.py() > dt.date.fromisoformat(hi):
            raise ValidationError(
                p.param, "%s cannot be later than %s" % (p.label, hi)
            )
    elif p.type in ("long", "float"):
        if lo not in ("", None) and float(value.py()) < float(lo):
            raise ValidationError(p.param, "%s must be at least %s" % (p.label, lo))
        if hi not in ("", None) and float(value.py()) > float(hi):
            raise ValidationError(p.param, "%s must be at most %s" % (p.label, hi))


def coerce_params(report: Report, raw: Dict, resolve) -> Dict:
    """Validate the submitted values and return a q-typed parameter dict."""
    if not isinstance(raw, dict):
        raise ValidationError("params", "params must be an object")

    unknown = set(raw) - {p.param for p in report.params}
    if unknown:
        raise ValidationError(
            "params",
            "unknown parameter(s) for %s: %s"
            % (report.report_id, ", ".join(sorted(unknown))),
        )

    out: Dict = {}
    for p in report.params:
        supplied = raw.get(p.param, None)
        if isinstance(supplied, str) and not supplied.strip():
            supplied = None
        if isinstance(supplied, (list, tuple)) and not supplied:
            supplied = None

        if supplied is None:
            default = resolve(p.default)
            if default not in ("", None):
                supplied = default
            elif p.required:
                raise ValidationError(p.param, "%s is required" % p.label)
            else:
                out[p.param] = EMPTY[p.type]()
                continue

        value = COERCE[p.type](p, supplied)
        _check_bounds(p, value, resolve)
        out[p.param] = value
    return out


def check_format(report: Report, fmt: str) -> str:
    fmt = (fmt or report.default_format).strip()
    if fmt not in report.formats:
        raise UnsupportedFormat(
            "%s does not produce %r (available: %s)"
            % (report.report_id, fmt, ", ".join(report.formats)),
            field="_format",
        )
    return fmt
