# KDB Report Console

A lightweight front-end for running kdb+ reports: search a catalog, fill in
typed parameters, get back a table, an HTML page or a PDF.

```
Browser ──HTTP/JSON──▶ FastAPI + PyKX ──kdb+ IPC──▶ KDB
  vanilla JS            validates params            .rpt.run[id;params;max;fmt]
  no build step         maps every error            returns one envelope
```

```bash
make setup && make data && make dev
```

Then open <http://127.0.0.1:8000>.

**[→ DESIGN.md](DESIGN.md)** — why the system is shaped this way: the options
considered and rejected, the three invariants, where validation lives, the IPC
entry point, and what was deliberately deferred.

**[→ MANUAL.md](MANUAL.md)** — how to run and test it: quick start, the catalog
format, the error table, the testing guide, and running against real kdb+.

---

### What it is

- **Front-end**: one HTML file, one JS file, one CSS file. No framework, no npm,
  no external requests. The parameter form is generated from a CSV.
- **Middle tier**: FastAPI + PyKX. Validates every parameter against the
  catalog before opening a socket. The browser never sends q code.
- **Backend**: `kdb/*.q` running on actual kdb+. `scripts/serve_q.py` hosts it
  locally on embedded KDB-X, since KDB-X ships as a library not a `q` binary.
- **Data**: 139,778 real NASDAQ daily bars, 114 symbols, 2013-02-08 → 2018-02-07,
  built from two public CSVs. Nothing synthesised.

### Verification

```bash
make test
```

43 end-to-end tests against **real kdb+ 5.0** — every report, every format,
every error path, over a real socket. Nothing is stubbed.
