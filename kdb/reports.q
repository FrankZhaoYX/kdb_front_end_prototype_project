/ Report implementations. One function per report_id in data/reports.csv.
/-
/ Each takes the parameter dictionary the gateway received and returns a table
/ (or, for the tearsheet, a char vector). Problems the caller can fix are
/ signalled through .rpt.throw, which encodes "code|message|field" so the
/ gateway can rebuild a structured error envelope on the other side of .Q.trp.

/ -------------------------------------------------------------- error helper
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

/ ------------------------------------------------------------------ reports
.rpt.dailyClose:{[p]
  a:p`date_from; b:p`date_to; s:p`symbols;
  .rpt.assertRange[a;b];
  .rpt.assertSyms[s];
  t:select dt,sym,open,high,low,close,volume,
           chg_pct:.rpt.rnd[4] chg_pct
      from daily where dt within (a;b);
  if[count s; t:select from t where sym in s];
  .rpt.assertRows[t;string[a]," .. ",string b]};

.rpt.topMovers:{[p]
  d:p`dt; dir:p`direction; n:p`top_n; mv:p`min_volume;
  t:select from daily where dt=d, not null chg_pct;
  if[not count t;
    .rpt.throw[`no_data_for_date;
      "not a business date in the dataset: ",string d; `dt]];
  if[mv>0; t:select from t where volume>=mv];
  .rpt.assertRows[t;"volume >= ",string mv];
  / n sublist, never n#: `#` cycles rows when n exceeds the row count.
  up:n sublist `chg_pct xdesc t;
  dn:n sublist `chg_pct xasc t;
  r:distinct $[dir~`up; up; dir~`down; dn; up,dn];
  r:update rnk:1+til count r, side:?[chg_pct>=0;`gainer;`loser] from r;
  r:r lj `sym xkey select sym,name from syms;
  r:select rnk,side,sym,name,close,prev_close,
           chg_pct:.rpt.rnd[4] chg_pct, volume from r;
  .rpt.asRank r};

.rpt.volumeLeaders:{[p]
  a:p`date_from; b:p`date_to; n:p`top_n;
  .rpt.assertRange[a;b];
  t:select days:count i,
           total_volume:sum volume,
           avg_volume:avg volume,
           notional_usd:sum close*volume,
           last_close:last close
      by sym from daily where dt within (a;b);
  .rpt.assertRows[t;string[a]," .. ",string b];
  t:n sublist `total_volume xdesc 0!t;
  t:t lj `sym xkey select sym,name from syms;
  t:update rnk:1+til count t from t;
  t:select rnk,sym,name,days,total_volume,
           avg_volume:.rpt.rnd[1] avg_volume,
           notional_usd:.rpt.rnd[2] notional_usd,
           last_close from t;
  .rpt.asRank t};

.rpt.ohlcSummary:{[p]
  a:p`date_from; b:p`date_to; s:p`symbols; mo:p`min_observations;
  .rpt.assertRange[a;b];
  .rpt.assertSyms[s];
  t:select from daily where dt within (a;b);
  if[count s; t:select from t where sym in s];
  .rpt.assertRows[t;string[a]," .. ",string b];
  t:select obs:count i,
           first_close:first close,
           last_close:last close,
           high:max high,
           low:min low,
           return_pct:100*(last[close]-first close)%first close,
           / sdev is the sample stddev (n-1); dev would be the population one.
           ann_vol_pct:100*sqrt[252]*sdev 0.01*chg_pct,
           avg_volume:avg volume
      by sym from t;
  t:select from 0!t where obs>=mo;
  .rpt.assertRows[t;"symbols with at least ",string[mo]," observations"];
  t:t lj `sym xkey select sym,name from syms;
  select sym,name,obs,
         first_close:.rpt.rnd[4] first_close,
         last_close:.rpt.rnd[4] last_close,
         high:.rpt.rnd[4] high,
         low:.rpt.rnd[4] low,
         return_pct:.rpt.rnd[4] return_pct,
         ann_vol_pct:.rpt.rnd[4] ann_vol_pct,
         avg_volume:.rpt.rnd[1] avg_volume from t};

.rpt.marketBreadth:{[p]
  a:p`date_from; b:p`date_to;
  .rpt.assertRange[a;b];
  t:select advancers:sum chg_pct>0,
           decliners:sum chg_pct<0,
           unchanged:sum chg_pct=0,
           avg_chg_pct:avg chg_pct
      by dt from daily where dt within (a;b), not null chg_pct;
  .rpt.assertRows[t;string[a]," .. ",string b];
  t:0!t;
  t:update adv_dec_ratio:?[decliners>0; advancers%decliners; 0n],
           pct_advancing:100*advancers%advancers+decliners+unchanged from t;
  select dt,advancers,decliners,unchanged,
         adv_dec_ratio:.rpt.rnd[4] adv_dec_ratio,
         pct_advancing:.rpt.rnd[2] pct_advancing,
         avg_chg_pct:.rpt.rnd[4] avg_chg_pct from t};

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

.rpt.symbolTearsheet:{[p]
  s:p`sym; a:p`date_from; b:p`date_to;
  fmt:$[`outputFormat in key p; p`outputFormat; `pdf];
  .rpt.assertRange[a;b];
  .rpt.assertSyms[enlist s];
  t:select from daily where dt within (a;b), sym=s;
  if[2>count t;
    .rpt.throw[`empty_result;
      "need at least 2 business dates for ",string s; `sym]];
  html:.rpt.tearsheetHtml[s;t];
  if[fmt~`html; :html];

  conv:getenv`KDB_HTML2PDF;
  if[not count conv;
    .rpt.throw[`pdf_unavailable;
      "KDB_HTML2PDF is not set on the kdb+ host, so PDF cannot be produced";
      `]];
  / `except` on a char vector drops those characters -- ssr does substring
  / replacement, not character classes, so it is the wrong tool here.
  stem:.rpt.outDir,"/tearsheet_",string[s],"_",
       (string .z.p) except ".:DT-";
  hsym[`$stem,".html"] 0: enlist html;
  system conv," ",stem,".html ",stem,".pdf";
  if[()~key hsym `$stem,".pdf";
    .rpt.throw[`pdf_failed;"the HTML to PDF converter produced no output";`]];
  stem,".pdf"};

/ report_id -> function name. The gateway will not call anything outside this
/ dictionary, so a client can never name an arbitrary q function.
.rpt.fn:`daily_close`top_movers`volume_leaders`ohlc_summary`market_breadth`symbol_tearsheet!
        `.rpt.dailyClose`.rpt.topMovers`.rpt.volumeLeaders`.rpt.ohlcSummary`.rpt.marketBreadth`.rpt.symbolTearsheet;
