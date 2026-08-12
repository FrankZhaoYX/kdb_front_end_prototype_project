#!/usr/bin/env bash
# HTML -> PDF converter for the kdb+ side of the tearsheet report.
#
#   export KDB_HTML2PDF="$PWD/scripts/html2pdf.sh"
#
# kdb+ has no PDF writer, so kdb/reports.q renders the tearsheet as HTML and
# shells out to whatever KDB_HTML2PDF names, called as:
#
#   $KDB_HTML2PDF <input.html> <output.pdf>
#
# This wrapper picks the first converter actually installed. Order matters:
# wkhtmltopdf and weasyprint are purpose-built; headless Chrome renders CSS
# faithfully and is present on most desktops; cupsfilter is a last resort and
# cannot do HTML at all on current macOS, so it is not attempted.
set -euo pipefail

IN="${1:?usage: html2pdf.sh <input.html> <output.pdf>}"
OUT="${2:?usage: html2pdf.sh <input.html> <output.pdf>}"

# Chrome needs an absolute file:// URL and an absolute output path.
abspath() { python3 -c 'import os,sys;print(os.path.abspath(sys.argv[1]))' "$1"; }
IN_ABS="$(abspath "$IN")"
OUT_ABS="$(abspath "$OUT")"

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

if command -v wkhtmltopdf >/dev/null 2>&1; then
  exec wkhtmltopdf --quiet --enable-local-file-access "$IN_ABS" "$OUT_ABS"

elif command -v weasyprint >/dev/null 2>&1; then
  exec weasyprint "$IN_ABS" "$OUT_ABS"

elif command -v prince >/dev/null 2>&1; then
  exec prince "$IN_ABS" -o "$OUT_ABS"

elif [ -x "$CHROME" ] || command -v google-chrome >/dev/null 2>&1 \
     || command -v chromium >/dev/null 2>&1; then
  BIN="$CHROME"
  [ -x "$BIN" ] || BIN="$(command -v google-chrome || command -v chromium)"
  # A throwaway profile keeps this from touching (or being blocked by) the
  # user's real Chrome session.
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  "$BIN" --headless --disable-gpu --no-sandbox --no-first-run \
         --user-data-dir="$TMP" \
         --disable-extensions --disable-background-networking --disable-sync \
         --no-pdf-header-footer \
         --print-to-pdf="$OUT_ABS" "file://$IN_ABS" >/dev/null 2>&1 &
  pid=$!
  # Headless Chrome writes the PDF and then sometimes fails to exit, so wait on
  # the file rather than the process, and kill it once the output is complete.
  for _ in $(seq 1 "${HTML2PDF_TIMEOUT:-40}"); do
    kill -0 "$pid" 2>/dev/null || break
    [ -s "$OUT_ABS" ] && sleep 1 && break
    sleep 1
  done
  kill -9 "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  [ -s "$OUT_ABS" ]

else
  echo "html2pdf: no converter found. Install one of wkhtmltopdf, weasyprint," >&2
  echo "          prince, or Google Chrome, or leave KDB_HTML2PDF unset to" >&2
  echo "          have the PDF format return a clean pdf_unavailable error." >&2
  exit 127
fi
