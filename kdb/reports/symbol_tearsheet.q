/ Symbol Tearsheet -- loaded by kdb/gateway.q from the q_file column of
/ data/reports.csv. Helpers live in kdb/lib.q.

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
