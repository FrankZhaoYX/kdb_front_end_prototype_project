#!/usr/bin/env python3
"""Build the NASDAQ daily dataset used by the mock KDB server.

Sources (both public, both fetched by scripts/fetch_raw.sh):

  data/raw/all_stocks_5yr.csv        real daily OHLCV, 2013-02-08 .. 2018-02-07
  data/raw/nasdaq-listed-symbols.csv real NASDAQ listing reference

We keep only the symbols that appear in *both* files, which leaves a
NASDAQ-listed universe with genuine historical prices. Nothing here is
synthesised -- every price, volume and date is from the source files.

Outputs:
  data/nsdq_daily.csv    dt,sym,open,high,low,close,volume
  data/nsdq_symbols.csv  sym,name,market_category,etf
"""
from __future__ import annotations

import csv
import os
import sys
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "data")

PRICES = os.path.join(RAW, "all_stocks_5yr.csv")
LISTING = os.path.join(RAW, "nasdaq-listed-symbols.csv")


def q_safe(s: str) -> str:
    """Strip characters that q's 0: cannot survive in a delimited file.

    kdb+'s `0:` CSV loader has no notion of quoted fields, so a company name
    like "American Airlines Group, Inc." would silently shift every column to
    its right. Non-ASCII is dropped for the same reason -- the IPC encoding is
    latin-1. This is why the generated CSVs are plain and unquoted.
    """
    s = "".join(ch for ch in s if 32 <= ord(ch) < 127)
    return " ".join(s.replace(",", " ").replace('"', "").split())


def load_listing():
    """sym -> (company name, market category, is_etf). Excludes test issues."""
    out = {}
    with open(LISTING, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            sym = (row.get("Symbol") or "").strip().upper()
            if not sym or (row.get("Test Issue") or "").strip() == "Y":
                continue
            out[sym] = (
                q_safe(row.get("Company Name") or "") or sym,
                (row.get("Market Category") or "").strip() or "?",
                (row.get("ETF") or "N").strip(),
            )
    return out


def main() -> int:
    for p in (PRICES, LISTING):
        if not os.path.exists(p):
            sys.stderr.write(
                "missing %s\nrun: ./scripts/fetch_raw.sh\n" % os.path.relpath(p, ROOT)
            )
            return 2

    listing = load_listing()
    kept, seen = [], OrderedDict()
    total = skipped = 0

    with open(PRICES, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            total += 1
            sym = (row.get("Name") or "").strip().upper()
            meta = listing.get(sym)
            if meta is None:
                continue
            # Source has a handful of blank OHLC cells; drop those rows.
            try:
                o = float(row["open"])
                h = float(row["high"])
                lo = float(row["low"])
                c = float(row["close"])
                v = int(row["volume"])
            except (TypeError, ValueError):
                skipped += 1
                continue
            dt = row["date"].strip()
            if len(dt) != 10:
                skipped += 1
                continue
            kept.append((dt, sym, o, h, lo, c, v))
            seen.setdefault(sym, meta)

    # q likes sorted-by-date data; a `p attribute on sym is applied server side.
    kept.sort(key=lambda r: (r[0], r[1]))

    daily = os.path.join(OUT, "nsdq_daily.csv")
    with open(daily, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["dt", "sym", "open", "high", "low", "close", "volume"])
        w.writerows(kept)

    syms = os.path.join(OUT, "nsdq_symbols.csv")
    with open(syms, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sym", "name", "market_category", "etf"])
        for sym in sorted(seen):
            name, cat, etf = seen[sym]
            w.writerow([sym, name, cat, etf])

    dates = [r[0] for r in kept]
    print("source rows      : %d" % total)
    print("dropped (bad row): %d" % skipped)
    print("kept rows        : %d" % len(kept))
    print("nasdaq symbols   : %d" % len(seen))
    print("date range       : %s .. %s" % (dates[0], dates[-1]))
    print("wrote %s" % os.path.relpath(daily, ROOT))
    print("wrote %s" % os.path.relpath(syms, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
