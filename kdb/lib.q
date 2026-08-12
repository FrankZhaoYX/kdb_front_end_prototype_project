/ Shared helpers for every report. Loaded before the per-report files that
/- kdb/gateway.q pulls in from the catalog, because they all call into here.
/-
/ Errors the caller can fix are signalled through .rpt.throw, which encodes
/ "code|message|field" so the gateway can rebuild a structured envelope on the
/ far side of .Q.trp.

.rpt.throw:{[code;msg;fld]
  '("|" sv (string code; msg; string fld))};

.rpt.assertRange:{[a;b]
  if[a>b;
    .rpt.throw[`invalid_range;
      "date_from (",string[a],") is after date_to (",string[b],")";
      `date_from]];
  };

.rpt.assertSyms:{[s]
  if[count s;
    u:s except .dat.symUniverse;
    if[count u;
      .rpt.throw[`unknown_symbol;
        "not in the NASDAQ universe: ",", " sv string 10 sublist asc u;
        `symbols]]];
  };

.rpt.assertRows:{[t;what]
  if[not count t; .rpt.throw[`empty_result;"no rows matched: ",what;`]];
  t};

/ `rank` is a q keyword, so `update rank:...` and `select rank,...` both signal
/ 'assign. Build the column as `rnk` and rename it last: xcol takes symbols
/ rather than identifiers, so it can produce a name the parser would reject.
.rpt.asRank:{[t] (enlist[`rnk]!enlist[`rank]) xcol t};

/ Round to d decimal places. Reports return presentation-ready numbers so the
/ payload stays small and the two implementations agree to the last digit --
/ `"j"$` rounds half-to-even, matching numpy.round and Python's round(). Nulls
/ survive: "j"$0n is 0Nj, and 0Nj%p is 0n.
.rpt.rnd:{[d;x] p:10 xexp d; ("j"$x*p)%p};

/ ------------------------------------------------------------- lookup / meta
.rpt.symbols:{[] select sym, name, market_category from syms};

.rpt.range:{[]
  `min_date`max_date`rows`symbols`dates!
    (min daily`dt;
     max daily`dt;
     count daily;
     count .dat.symUniverse;
     count distinct daily`dt)};

.rpt.ping:{[] `pong};

/ Blocks the main thread for x seconds. Exists so the middle tier's IPC timeout
/ handling can actually be tested against a busy kdb+ process.
.rpt.sleep:{[n]
  if[n>120; '"limit"];
  system "sleep ",string n;   / shell out rather than busy-wait on .z.p
  `awake};

/ ---------------------------------------------------------------- tearsheet
/ Where the PDF is produced. kdb+ has no PDF writer, so the q side renders HTML
/ and shells out to a converter. Set KDB_HTML2PDF to whatever your box has,
/ e.g. "wkhtmltopdf --quiet" or "weasyprint". The middle tier only ever sees
/ the returned path, and re-checks it is inside .rpt.outDir before streaming.
.rpt.outDir:$[count getenv`KDB_REPORT_DIR; getenv`KDB_REPORT_DIR; "var/reports"];
/ Resolve to an absolute path. The middle tier checks the returned path against
/ its own REPORT_DIR, and a relative one would be joined onto that directory a
/ second time -- var/reports/var/reports/... -- and then fail to be found.
if[not "/"~first .rpt.outDir; .rpt.outDir:(first system"pwd"),"/",.rpt.outDir];
system "mkdir -p ",.rpt.outDir;

/ Note the parameter is `s`, not `sym`: inside exec/select a column name shadows
/ any same-named variable, so `where sym=sym` would match every row.
.rpt.tearsheetHtml:{[s;t]
  c:t`close; lo:min c; hi:max c; sp:$[hi=lo;1f;hi-lo];
  w:960f; h:260f; st:w%1|(count c)-1;
  pts:" " sv {[i;y] (string i),",",string y}'[st*til count c;
        h-8f+(h-16f)*(c-lo)%sp];
  nm:first exec name from syms where sym=s;
  ret:100*(last[c]-first c)%first c;
  "<!doctype html>\n<meta charset=\"utf-8\"><title>",string[s]," Tearsheet</title>\n",
  "<style>body{font:14px system-ui,sans-serif;margin:0;padding:28px}",
  "h1{margin:0;font-size:26px}.sub{color:#6e788a;margin:4px 0 20px}",
  "table{border-collapse:collapse;margin-bottom:24px}",
  "td{padding:4px 18px 4px 0}td.k{color:#6e788a;font-size:12px;text-transform:uppercase}",
  "svg{width:100%;height:auto;border:1px solid #dee2ea;border-radius:8px}</style>\n",
  "<h1>",string[s]," &mdash; ",string[nm],"</h1>\n",
  "<div class=\"sub\">",string[first t`dt]," to ",string[last t`dt],
    " &middot; ",string[count t]," business days &middot; ",
    .Q.f[2;ret],"%</div>\n",
  "<table>",
  "<tr><td class=\"k\">First Close</td><td>",.Q.f[2;first c],"</td>",
      "<td class=\"k\">Last Close</td><td>",.Q.f[2;last c],"</td></tr>",
  "<tr><td class=\"k\">High</td><td>",.Q.f[2;max t`high],"</td>",
      "<td class=\"k\">Low</td><td>",.Q.f[2;min t`low],"</td></tr>",
  "<tr><td class=\"k\">Ann Vol</td><td>",
      .Q.f[2;100*sqrt[252]*sdev 0.01*t`chg_pct],"%</td>",
      / .Q.f[0;x] renders "17049208." with a trailing point; cast instead.
      "<td class=\"k\">Avg Volume</td><td>",string["j"$avg t`volume],"</td></tr>",
  "</table>\n",
  "<svg viewBox=\"0 0 960 260\" preserveAspectRatio=\"none\">",
  "<polyline points=\"",pts,"\" fill=\"none\" stroke=\"",
    $[ret>=0;"#059669";"#dc2626"],"\" stroke-width=\"2\"/></svg>\n",
  "<p style=\"color:#6e788a;font-size:12px;margin-top:24px\">Generated ",
    string[.z.p]," by kdb+. Source: public NASDAQ daily OHLCV. ",
    "Prototype output - not investment advice.</p>\n"};
