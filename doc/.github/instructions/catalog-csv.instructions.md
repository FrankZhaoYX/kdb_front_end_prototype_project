---
applyTo: "data/**"
---

# Catalog CSV rules

`data/reports.csv` and `data/report_params.csv` are read by **both** the q
gateway (`kdb/gateway.q`) and the Python app (`app/catalog.py`). They are the
contract between every layer — treat them as load-bearing data, not
documentation.

## `data/reports.csv` — one row per report

| Column | Meaning |
|---|---|
| `report_id` | Stable key; used by the API and as the join key into `report_params.csv` |
| `category` | First dropdown in the UI |
| `name` | Second dropdown, filtered by `category` |
| `description` | Shown under the pickers; searched |
| `q_file` | Path to the file defining the report, e.g. `kdb/reports/top_movers.q` |
| `q_func` | The q entry point in that file — **this is the dispatch whitelist** |
| `formats` | Pipe-separated: `table`, `html`, `pdf` |
| `default_format` | Pre-selected in the UI |
| `timeout_s` | Per-report IPC timeout |
| `max_rows` | Truncation ceiling; the response flags when it bites |
| `tags` | Extra search terms |

## `data/report_params.csv` — one row per parameter, keyed by `report_id`

| Column | Meaning |
|---|---|
| `param` | Name passed to q, and the dict key |
| `label`, `help` | UI text |
| `type` | `date` `sym` `symlist` `long` `float` `enum` `bool` `string` |
| `required` | `1`/`0` |
| `default` | Literal, or an `@token` (`@min_date`, `@max_date`, `@max_date-30d`, `@today`) |
| `widget` | `date` `number` `text` `select` `multiselect` |
| `options` | Static pipe-separated list for `select` |
| `options_q` | q function supplying options dynamically instead |
| `min`, `max` | Bounds, literal or `@token` |
| `ord` | Display order |

## Rules

- **No value in either file may contain a comma.** kdb's `0:` CSV reader has
  no quoted-field support — a comma silently shifts every subsequent column.
  This is the single most common way to break the catalog without any error
  appearing.
- **Column order is fixed** — `kdb/gateway.q` parses `reports.csv` with a
  positional type string (`"SSS*SSSSFJS"`). Adding, removing, or reordering
  columns requires updating that type string too.
- **Every `q_file` must exist** and be loadable on its own (it will be
  `\l`'d directly by the gateway). Every `q_func` it defines must match
  exactly, including the leading `.rpt.` namespace.
- To add a report: add one row to each CSV, write the `.q` file, restart the
  gateway (or let it hot-reload — `app/catalog.py` reloads on CSV mtime
  change, but the q side does not, so a q-level catalog change needs a
  gateway restart).
