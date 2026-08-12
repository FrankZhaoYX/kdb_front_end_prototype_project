"""The report catalog: two CSVs, reloaded whenever they change on disk.

This is the contract between the front-end and the middle tier. The browser
builds its form from it and the server validates against it, so a new report is
two CSV rows plus a q function -- no Python and no JavaScript.

Defaults and bounds may use tokens instead of literal dates:

    @min_date          first business date in the dataset
    @max_date          last business date in the dataset
    @max_date-30d      30 calendar days before the last business date
    @min_date+90d      90 calendar days after the first
    @today             the actual current date

They are resolved per request against the range kdb reports, so the form is
always populated with dates the data actually covers.
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import re
import threading
from typing import Dict, List, Optional

from . import config
from .errors import UnknownReport

TOKEN = re.compile(r"^@(min_date|max_date|today)(?:([+-])(\d+)d)?$")

TRUE = {"1", "true", "yes", "y", "t"}
VALID_TYPES = {"date", "sym", "symlist", "long", "float", "enum", "bool", "string"}


class Param:
    __slots__ = ("param", "label", "type", "required", "default", "widget",
                 "options", "options_q", "min", "max", "help", "ord")

    def __init__(self, row: Dict[str, str]):
        self.param = (row.get("param") or "").strip()
        self.label = (row.get("label") or self.param).strip()
        self.type = (row.get("type") or "string").strip()
        self.required = (row.get("required") or "").strip().lower() in TRUE
        self.default = (row.get("default") or "").strip()
        self.widget = (row.get("widget") or "text").strip()
        opts = (row.get("options") or "").strip()
        self.options = [o for o in opts.split("|") if o] if opts else []
        self.options_q = (row.get("options_q") or "").strip()
        self.min = (row.get("min") or "").strip()
        self.max = (row.get("max") or "").strip()
        self.help = (row.get("help") or "").strip()
        try:
            self.ord = int(row.get("ord") or 0)
        except ValueError:
            self.ord = 0
        if self.type not in VALID_TYPES:
            raise ValueError(
                "%s.%s: unknown type %r (expected one of %s)"
                % (row.get("report_id"), self.param, self.type,
                   ", ".join(sorted(VALID_TYPES)))
            )

    def as_dict(self, resolve) -> dict:
        return {
            "param": self.param,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "default": resolve(self.default),
            "widget": self.widget,
            "options": self.options,
            "dynamic_options": bool(self.options_q),
            "min": resolve(self.min),
            "max": resolve(self.max),
            "help": self.help,
        }


class Report:
    __slots__ = ("report_id", "name", "category", "description", "q_file",
                 "q_func", "formats", "default_format", "timeout_s",
                 "max_rows", "tags", "params")

    def __init__(self, row: Dict[str, str]):
        self.report_id = (row.get("report_id") or "").strip()
        self.name = (row.get("name") or self.report_id).strip()
        self.category = (row.get("category") or "General").strip()
        self.description = (row.get("description") or "").strip()
        self.q_file = (row.get("q_file") or "").strip()
        self.q_func = (row.get("q_func") or "").strip()
        self.formats = [f for f in
                        re.split(r"[|,]", (row.get("formats") or "table")) if f.strip()]
        self.formats = [f.strip() for f in self.formats]
        self.default_format = (row.get("default_format") or self.formats[0]).strip()
        self.timeout_s = min(
            float(row.get("timeout_s") or 30), config.MAX_TIMEOUT_S
        )
        self.max_rows = int(row.get("max_rows") or 0)
        tags = (row.get("tags") or "").strip()
        self.tags = [t.strip() for t in re.split(r"[|,]", tags) if t.strip()]
        self.params: List[Param] = []
        if not self.q_func:
            raise ValueError("%s: q_func is required" % self.report_id)
        if not self.q_file:
            raise ValueError("%s: q_file is required" % self.report_id)
        if self.default_format not in self.formats:
            raise ValueError(
                "%s: default_format %r not in formats %s"
                % (self.report_id, self.default_format, self.formats)
            )

    def param(self, name: str) -> Optional[Param]:
        for p in self.params:
            if p.param == name:
                return p
        return None

    def summary(self) -> dict:
        return {
            "report_id": self.report_id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "formats": self.formats,
            "default_format": self.default_format,
            "tags": self.tags,
            "param_count": len(self.params),
        }

    def detail(self, resolve) -> dict:
        d = self.summary()
        d["timeout_s"] = self.timeout_s
        d["max_rows"] = self.max_rows
        d["q_file"] = self.q_file
        d["params"] = [p.as_dict(resolve) for p in self.params]
        return d


class Catalog:
    """Loads both CSVs, and reloads them when either file's mtime changes."""

    def __init__(self, reports_csv: str = None, params_csv: str = None):
        self.reports_csv = reports_csv or config.REPORTS_CSV
        self.params_csv = params_csv or config.PARAMS_CSV
        self._lock = threading.Lock()
        self._reports: Dict[str, Report] = {}
        self._stamp = None
        self.load()

    # ----------------------------------------------------------------- load
    def _mtimes(self):
        try:
            return (os.path.getmtime(self.reports_csv),
                    os.path.getmtime(self.params_csv))
        except OSError:
            return None

    def load(self) -> None:
        with open(self.reports_csv, newline="", encoding="utf-8") as fh:
            reports = {}
            for row in csv.DictReader(fh):
                if not (row.get("report_id") or "").strip():
                    continue
                r = Report(row)
                if r.report_id in reports:
                    raise ValueError("duplicate report_id: %s" % r.report_id)
                reports[r.report_id] = r

        with open(self.params_csv, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                rid = (row.get("report_id") or "").strip()
                if not rid:
                    continue
                if rid not in reports:
                    raise ValueError(
                        "report_params.csv references unknown report_id %r" % rid
                    )
                reports[rid].params.append(Param(row))

        for r in reports.values():
            r.params.sort(key=lambda p: (p.ord, p.param))
            names = [p.param for p in r.params]
            dupes = {n for n in names if names.count(n) > 1}
            if dupes:
                raise ValueError(
                    "%s: duplicate parameters %s" % (r.report_id, ", ".join(dupes))
                )

        with self._lock:
            self._reports = reports
            self._stamp = self._mtimes()

    def maybe_reload(self) -> bool:
        """Hot-reload on mtime change so editing a CSV needs no restart."""
        if self._mtimes() == self._stamp:
            return False
        self.load()
        return True

    # ---------------------------------------------------------------- access
    @property
    def reports(self) -> Dict[str, Report]:
        return self._reports

    def get(self, report_id: str) -> Report:
        r = self._reports.get(report_id)
        if r is None:
            raise UnknownReport("no such report: %s" % report_id)
        return r

    def search(self, query: str) -> List[Report]:
        """Substring match over name, id, description, category and tags."""
        items = sorted(self._reports.values(), key=lambda r: (r.category, r.name))
        q = (query or "").strip().lower()
        if not q:
            return items
        terms = q.split()
        out = []
        for r in items:
            hay = " ".join(
                [r.report_id, r.name, r.description, r.category] + r.tags
            ).lower()
            if all(t in hay for t in terms):
                out.append(r)
        return out


def make_resolver(min_date: Optional[dt.date], max_date: Optional[dt.date]):
    """Build a function that turns @token strings into ISO dates."""

    anchors = {
        "min_date": min_date,
        "max_date": max_date,
        "today": dt.date.today(),
    }

    def resolve(value: str) -> str:
        if not value or not value.startswith("@"):
            return value
        m = TOKEN.match(value)
        if not m:
            return value
        base = anchors.get(m.group(1))
        if base is None:
            return ""
        if m.group(2):
            days = int(m.group(3))
            base = base + dt.timedelta(days=days if m.group(2) == "+" else -days)
        # Clamp into the dataset so a default can never fall outside it.
        if min_date and base < min_date:
            base = min_date
        if max_date and base > max_date:
            base = max_date
        return base.isoformat()

    return resolve

