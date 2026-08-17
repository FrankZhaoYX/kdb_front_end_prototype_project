# Remote Multi-File Reports — Design Proposal

> **Status: proposed, not implemented.** Nothing in this document is part of
> the tested reference system described in [DESIGN.md](DESIGN.md) and
> [MANUAL.md](MANUAL.md). It exists as a concrete, ready-to-implement design
> for a report shape those documents don't cover: a report whose output is
> **more than one file**, generated on a **remote server** and exposed over
> **HTTP(S)**, rather than a single file already sitting on the kdb+ host's
> own filesystem.

## The problem

The existing `pdf`/`html` formats assume the report function returns either
inline text (`html`) or the absolute path to **one** file that already
exists on the same machine the kdb+ gateway is running on — `artifacts.py`
validates that path is inside `REPORT_DIR` and streams it.

A report that generates a PDF *and* an Excel workbook on a separate,
independently-managed server doesn't fit that: there are two files, not one,
and neither is reachable as a local path — they're reachable as URLs on
another host.

## The extension: a `files` format

### q side — one new envelope branch

In `kdb/gateway.q`, `` `files `` joins the existing single-shot bucket
alongside `pdf`/`html` (no truncation, `meta.rows` counts entries instead of
being hardcoded to 1):

```q
if[fmt in `pdf`html`files;
  n:$[fmt~`files; count res; 1j];
  :`status`report`format`payload`meta!(`ok; rid; fmt; res; mkMeta[n;0b;el])];
```

The report function itself just returns a plain dict of label → URL:

```q
`pdf`excel!("https://remote-host.internal/reports/foo.pdf";
             "https://remote-host.internal/reports/foo.xlsx")
```

No further q-side machinery is needed — PyKX already serialises dicts fine;
this reuses exactly what carries `.rpt.range`'s dict today.

**Building the URL from host/port/location pieces**, if that's what the
report has on hand rather than a ready string:

```q
host:"remote-host.internal";     / or `string` a symbol first if you hold one
port:8080;
loc:"/reports/foo.pdf";

url:"http://",host,":",string[port],loc;
/ -> "http://remote-host.internal:8080/reports/foo.pdf"
```

Use `https://` and the TLS port instead if the remote file server has TLS —
prefer that over plaintext HTTP when it's available, not just whichever is
less setup.

Add `files` to that report's `formats` column in `data/reports.csv`
(`default_format=files`) — same catalog mechanism as every other report,
nothing special-cased.

### App side — fetch, then reuse the existing artifact machinery

The key design choice: **the app does not trust the URL kdb hands back**.
It only fetches from an explicit allowlist of hosts — the same containment
principle `artifacts.safe_path()` already applies to local paths, just
enforced at fetch time instead of at open time. An empty allowlist means
"fetch nothing," so this fails closed by default rather than silently
following whatever a report — or a parameter that influenced its output —
happens to produce.

```python
# app/config.py — additions
REMOTE_FILE_ALLOWED_HOSTS = [h.strip() for h in
    os.environ.get("REMOTE_FILE_ALLOWED_HOSTS", "").split(",") if h.strip()]
REMOTE_FILE_TIMEOUT_S = _float("REMOTE_FILE_TIMEOUT_S", 30.0)
REMOTE_FILE_AUTH_HEADER = os.environ.get("REMOTE_FILE_AUTH_HEADER", "")  # "Authorization: Bearer xyz"
```

```python
# app/errors.py — addition
class RemoteFetchError(ApiError):
    status = 502
    code = "remote_fetch_failed"
```

```python
# app/remote_files.py — new module
"""Fetch report artefacts a report generated on a remote server.

Does not trust the URL blindly -- only fetches from hosts in
REMOTE_FILE_ALLOWED_HOSTS, mirroring the containment principle
artifacts.safe_path() already applies to local paths.
"""
import mimetypes, os, uuid
from urllib.parse import urlsplit
import httpx
from . import config
from .errors import RemoteFetchError

_EXT_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
}

def _headers() -> dict:
    h = config.REMOTE_FILE_AUTH_HEADER
    if not h or ":" not in h:
        return {}
    name, _, value = h.partition(":")
    return {name.strip(): value.strip()}

def fetch_remote_file(url: str, label: str, report_id: str):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise RemoteFetchError("refused non-HTTP(S) file address",
                                detail="scheme was %r" % parts.scheme)
    if parts.hostname not in config.REMOTE_FILE_ALLOWED_HOSTS:
        raise RemoteFetchError("refused a file from an unlisted host",
                                detail="%s not in REMOTE_FILE_ALLOWED_HOSTS" % parts.hostname)

    ext = os.path.splitext(parts.path)[1].lower() or ".bin"
    media_type = _EXT_MEDIA_TYPES.get(ext) or mimetypes.guess_type(url)[0] or "application/octet-stream"
    local_path = os.path.join(config.REPORT_DIR,
                               "%s_%s_%s%s" % (report_id, label, uuid.uuid4().hex[:12], ext))
    try:
        with httpx.stream("GET", url, headers=_headers(), timeout=config.REMOTE_FILE_TIMEOUT_S) as resp:
            resp.raise_for_status()
            with open(local_path, "wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)
    except httpx.HTTPError as e:
        raise RemoteFetchError("could not fetch %s from the remote server" % label,
                                detail="%s: %s" % (type(e).__name__, e))
    return local_path, media_type
```

`httpx` is already a dependency (pulled in for the test suite) — no new
package needed.

```python
# app/main.py -- run_report(), one new branch in the format if/elif chain
elif body["format"] == "files":
    from .remote_files import fetch_remote_file
    remote = to_json(payload)          # {"pdf": "https://...", "excel": "https://..."}
    files = []
    for label, url in remote.items():
        local_path, media_type = fetch_remote_file(url, label, report.report_id)
        art = artifacts.register(local_path, report.report_id, media_type=media_type)
        files.append({"label": label, "download_url": "/api/download/%s" % art.token,
                      "filename": art.filename, "size_bytes": art.size})
    body["files"] = files
```

This is the load-bearing design decision: the fetch writes into
`REPORT_DIR` first, then hands off to the **existing, unmodified**
`artifacts.register()` — so the current path-containment guarantee keeps
applying without needing a second, parallel safety mechanism for the remote
case.

### Front-end — one new render branch

```javascript
// app/static/app.js -- renderResult(), one new branch
} else if (res.format === "files") {
  var wrap = el("div", { class: "pdf-wrap" });
  res.files.forEach(function (f) {
    wrap.appendChild(el("div", { class: "pdf-bar" }, [
      el("span", { text: f.label.toUpperCase() + "  ·  " + f.filename + "  ·  " +
                         Math.round(f.size_bytes / 1024) + " KB" }),
      el("span", { class: "grow" }),
      el("a", { href: f.download_url, download: f.filename, text: "Download" })
    ]));
  });
  box.appendChild(wrap);
}
```

Reuses the existing `.pdf-bar` styling, just repeated per file — no new CSS.
Optional polish: give the `pdf`-labelled entry an inline iframe preview like
today's single-PDF case; Excel can't preview inline in a browser anyway, so
a plain download link is the correct treatment for it regardless.

## Open items before this is implemented for real

- **Confirm `http://` vs `https://`** with whatever actually serves these
  files — don't default to plaintext HTTP just because it's less setup if
  TLS is available.
- **Set `REMOTE_FILE_ALLOWED_HOSTS`** to the real remote host(s) before this
  can fetch anything at all — it fails closed with an empty allowlist by
  design. Only the bare hostname is needed, not `host:port` —
  `urlsplit(url).hostname` strips the port automatically.
- **Decide on auth**, if the remote endpoint needs any — the `_headers()`
  hook supports one static header via `REMOTE_FILE_AUTH_HEADER`; a real
  deployment may need something richer (mTLS, a rotating token) depending on
  how that server is secured.
- **No tests yet.** Once this is wired up against a real remote endpoint (or
  a stub one for CI), it needs the same treatment every other report gets
  per [`.github/instructions/tests.instructions.md`](.github/instructions/tests.instructions.md)
  in the Copilot kit: a happy-path test with known values, and one test per
  error path (`remote_fetch_failed` on a disallowed host, on a timeout, on a
  non-200 response).
