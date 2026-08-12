---
applyTo: "app/**/*.py"
---

# Middle-tier (FastAPI) conventions

- Routing lives only in `app/main.py`. Validation lives only in
  `app/validate.py`. Catalog loading/hot-reload lives only in
  `app/catalog.py`. Don't fold logic from one into another for convenience —
  the split is what makes each piece independently testable.
- Every error the browser can see must be an `ApiError` subclass from
  `app/errors.py` with a stable `code`. If you add a new failure mode,
  add a new `code`, don't overload an existing one.
- Validate everything the catalog can tell you (types, ranges, enums,
  required-ness) in `app/validate.py` **before** any kdb call is made. Only
  things kdb alone can know (does this symbol exist, is this a business
  date, did the filter match anything) should surface as a kdb-side error.
- `app/static/*` is served by `StaticFiles`, which sends `ETag` but no
  `Cache-Control`. Keep the `Cache-Control: no-cache, must-revalidate`
  middleware on `/static/*` in `app/main.py` — removing it silently
  reintroduces stale-JS-after-edit bugs that are hard to notice.
- Don't add authentication. See `AGENTS.md` rule 5 — this is deliberate.
