---
applyTo: "kdb/**"
---

# q language rules for this project

Full narrative detail is in `KNOWN-PITFALLS.md` §"q language" — this is the
condensed checklist for anything you write or edit under `kdb/`.

- **Never use a bare `/` alone on a line.** It opens a block comment that
  runs until a line containing only `\`, silently swallowing everything
  after it with no error. Use `/-` for a visual separator, or put real text
  after the slash.
- **`rank` and `meta` cannot be used as column or variable names** — they are
  q reserved words and any `update`/`select`/local assignment using them
  signals `'assign`. Use a different name and, if the column must be called
  `rank` in the output, rename it last via `xcol` (which takes symbols, not
  parsed identifiers).
- **Never write a symbol literal starting with `_`** (e.g. `` `_format ``) —
  it does not tokenise as intended and signals a parse error. Pass such
  values as ordinary positional arguments instead of embedding them as dict
  keys with a leading underscore.
- **Every value written into `data/*.csv` must be comma-free.** `0:` has no
  quoted-field support; a comma silently shifts every later column.
- **Any path a q function hands back to a caller must be absolute.** Resolve
  relative paths before returning them, or the caller's own base-directory
  join will double up and the file will never be found.
- **`.gw.allow` and `.rpt.fn` in `kdb/gateway.q` are the only two places a
  client-reachable q function may be named.** Never add a new report by
  wiring it in directly here — add a row to `data/reports.csv` with the
  correct `q_file`/`q_func` instead; `gateway.q` derives both structures from
  the catalog at load time.
- **`system` calls (e.g. shelling out to convert HTML to PDF) must run on
  the q process's main/owning thread.** If you're writing anything that
  hosts q from Python (like `scripts/serve_q.py`), keep exactly one thread
  that owns all q calls — do not call into q from multiple worker threads.
