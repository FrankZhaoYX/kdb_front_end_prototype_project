---
applyTo: "app/static/**"
---

# Front-end conventions

- No framework, no build step, no `package.json`. Plain HTML/CSS/JS only —
  keep it that way; this is a deliberate lightweight-stack decision, not an
  oversight.
- The report picker and the selected report's parameters live in **one**
  control bar at the top of the page: Category dropdown → Report dropdown
  (filtered by category) → that report's parameter fields, all in the same
  horizontal row, with results taking the full width below. Don't reintroduce
  a separate sidebar for parameters — that layout was tried and explicitly
  replaced.
- Parameter fields are generated dynamically from
  `GET /api/reports/{id}` — specifically from its `params` array, which
  mirrors `data/report_params.csv`. Never hardcode a report's fields in
  `app.js`; if a field is missing, the catalog CSV is where it belongs.
- Errors follow one contract from the server: `{status, code, message,
  field?, detail?}`. A `field` renders under that specific input; its
  absence means the message goes to the page-level banner. Keep this as the
  only error-rendering path — don't add a second one for a new endpoint.
