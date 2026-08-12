"""FastAPI middle tier.

    GET  /                          the single-page front-end
    GET  /api/health                app + kdb liveness
    GET  /api/reports?q=            catalog, optionally filtered
    GET  /api/reports/{id}          one report with resolved parameter defaults
    GET  /api/reports/{id}/options/{param}   dynamic dropdown values from kdb
    POST /api/run                   run a report
    GET  /api/download/{token}      stream a PDF kdb generated

Nothing here builds a q expression. /api/run takes a report_id and a parameter
object, looks the report up in the catalog, coerces each value to a q type and
calls .rpt.run with them as data. A caller cannot name a q function, and there
is no string for them to inject into.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import pykx as kx

from . import config
from .artifacts import ArtifactStore
from .catalog import Catalog, make_resolver
from .errors import ApiError, ReportError, UnknownReport
from .kdbclient import KdbPool, RangeCache
from .serialize import qtext, table_to_json, to_json
from .validate import check_format, coerce_params, qdict, qsymbol

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("app")

app = FastAPI(title="KDB Report Front-End", version="0.1.0")

catalog = Catalog()
pool = KdbPool()
ranges = RangeCache(pool)
artifacts = ArtifactStore()


# ------------------------------------------------------------------ helpers
def resolver():
    """A @token resolver bound to the dataset range kdb currently reports."""
    rng = ranges.get() or {}
    return make_resolver(_as_date(rng.get("min_date")), _as_date(rng.get("max_date")))


def _as_date(v):
    import datetime as dt
    if not v:
        return None
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


@app.middleware("http")
async def revalidate_static(request: Request, call_next):
    """Stop the browser serving a stale app.js/styles.css after an edit.

    StaticFiles sends ETag + Last-Modified but no Cache-Control, so browsers
    reuse the cached copy without asking. `no-cache` does not disable caching --
    it requires revalidation, so unchanged assets still come back as a 304.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    log.info("%s %s -> %s: %s", request.method, request.url.path, exc.code,
             exc.message)
    return JSONResponse(status_code=exc.status, content=exc.payload())


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"status": "err", "code": "internal_error",
                 "message": "the report service hit an unexpected error"},
    )


# ------------------------------------------------------------------- health
@app.get("/api/health")
async def health():
    out: Dict[str, Any] = {
        "status": "ok",
        "kdb": pool.stats(),
        "reports": len(catalog.reports),
        "artifacts": artifacts.count(),
    }
    try:
        pong = await run_in_threadpool(pool.call, ".rpt.ping", timeout=5.0)
        out["kdb"]["reachable"] = True
        out["kdb"]["ping"] = qtext(pong)
    except ApiError as e:
        out["status"] = "degraded"
        out["kdb"]["reachable"] = False
        out["kdb"]["error"] = e.message
    out["dataset"] = ranges.get()
    return out


# ------------------------------------------------------------------ catalog
@app.get("/api/reports")
async def list_reports(q: str = Query("", description="free-text filter")):
    catalog.maybe_reload()
    items = catalog.search(q)
    return {
        "status": "ok",
        "count": len(items),
        "dataset": ranges.get(),
        "reports": [r.summary() for r in items],
    }


@app.get("/api/reports/{report_id}")
async def get_report(report_id: str):
    catalog.maybe_reload()
    report = catalog.get(report_id)
    return {"status": "ok", "dataset": ranges.get(),
            "report": report.detail(resolver())}


@app.get("/api/reports/{report_id}/options/{param}")
async def get_options(report_id: str, param: str):
    """Dropdown values sourced from kdb via the catalog's options_q column."""
    catalog.maybe_reload()
    report = catalog.get(report_id)
    p = report.param(param)
    if p is None:
        raise UnknownReport("%s has no parameter %r" % (report_id, param),
                            code="unknown_param", status=404)
    if not p.options_q:
        return {"status": "ok", "options": [{"value": o, "label": o}
                                            for o in p.options]}

    raw = await run_in_threadpool(pool.call, p.options_q, timeout=15.0)
    table = table_to_json(raw)
    names = [c["name"] for c in table["columns"]]
    vi = 0
    li = 1 if len(names) > 1 else 0
    options = [
        {"value": str(row[vi]),
         "label": ("%s - %s" % (row[vi], row[li])) if li != vi and row[li]
                  else str(row[vi])}
        for row in table["rows"]
    ]
    return {"status": "ok", "count": len(options), "options": options}


# ---------------------------------------------------------------------- run
class RunRequest(BaseModel):
    report_id: str = Field(..., min_length=1, max_length=128)
    params: Dict[str, Any] = Field(default_factory=dict)
    format: Optional[str] = None


@app.post("/api/run")
async def run_report(req: RunRequest):
    catalog.maybe_reload()
    report = catalog.get(req.report_id)
    fmt = check_format(report, req.format)

    # Everything is validated before a single byte goes to kdb.
    params = coerce_params(report, req.params, resolver())

    t0 = time.perf_counter()
    envelope = await run_in_threadpool(
        pool.call,
        ".rpt.run",
        qsymbol(report.report_id),
        qdict(params),
        kx.LongAtom(report.max_rows),
        qsymbol(fmt),
        timeout=report.timeout_s,
    )
    total_ms = (time.perf_counter() - t0) * 1000.0

    env = _env_to_dict(envelope)
    if env.get("status") == "err":
        # kdb rejected it for a reason the user can act on -- surface the field.
        raise ReportError(
            env.get("error") or "the report failed",
            code=env.get("code") or "report_error",
            status=400,
            field=env.get("field") or None,
        )

    meta = env.get("meta") or {}
    body: Dict[str, Any] = {
        "status": "ok",
        "report": report.report_id,
        "name": report.name,
        "format": env.get("format") or fmt,
        "meta": {
            "rows": meta.get("rows"),
            "truncated": bool(meta.get("truncated")),
            "kdb_ms": meta.get("elapsed_ms"),
            "total_ms": round(total_ms, 1),
            "generated": meta.get("generated"),
            "max_rows": report.max_rows,
        },
    }

    payload = env.get("_payload_raw")
    if body["format"] == "table":
        body.update(table_to_json(payload))
    elif body["format"] == "html":
        body["html"] = qtext(payload)
    elif body["format"] == "pdf":
        art = artifacts.register(qtext(payload), report.report_id)
        body["download_url"] = "/api/download/%s" % art.token
        body["filename"] = art.filename
        body["size_bytes"] = art.size
    else:
        raise ReportError("kdb returned an unsupported format: %r" % body["format"])
    return body


def _env_to_dict(envelope) -> Dict[str, Any]:
    """Flatten the q envelope, keeping the payload in its native PyKX form."""
    out: Dict[str, Any] = {}
    for key in envelope.keys().py():
        name = qtext(key)
        value = envelope[key]
        out["_payload_raw" if name == "payload" else name] = (
            value if name == "payload" else to_json(value)
        )
    return out


# ----------------------------------------------------------------- download
@app.get("/api/download/{token}")
async def download(token: str):
    art = artifacts.get(token)
    return FileResponse(
        art.path,
        media_type=art.media_type,
        filename=art.filename,
        headers={"Content-Disposition": 'inline; filename="%s"' % art.filename},
    )


# ------------------------------------------------------------------- static
@app.get("/", response_class=HTMLResponse)
async def index():
    with open(config.STATIC_DIR + "/index.html", encoding="utf-8") as fh:
        return HTMLResponse(fh.read())


app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.on_event("shutdown")
def _shutdown():
    pool.close()
    # PYKX_THREADING starts a q thread that must be stopped or the process
    # will not exit. See app/__init__.py.
    try:
        kx.shutdown_thread()
    except Exception:
        pass
