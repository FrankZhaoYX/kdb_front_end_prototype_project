#!/usr/bin/env bash
# Fetch the two public CSVs the demo dataset is built from.
# Both are plain static files on raw.githubusercontent.com -- no API key, no auth.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RAW="$ROOT/data/raw"
mkdir -p "$RAW"

fetch() { # url dest
  if [ -s "$2" ]; then
    echo "have    $(basename "$2")"
  else
    echo "fetch   $(basename "$2")"
    curl -fsSL --retry 3 -m 180 -o "$2" "$1"
  fi
}

# Real daily OHLCV for ~505 large-cap US tickers, 2013-02-08 .. 2018-02-07.
fetch "https://raw.githubusercontent.com/plotly/datasets/master/all_stocks_5yr.csv" \
      "$RAW/all_stocks_5yr.csv"

# Official NASDAQ listing reference (symbol, company name, market category, ETF flag).
fetch "https://raw.githubusercontent.com/datasets/nasdaq-listings/main/data/nasdaq-listed-symbols.csv" \
      "$RAW/nasdaq-listed-symbols.csv"

echo
python3 "$ROOT/scripts/build_data.py"
