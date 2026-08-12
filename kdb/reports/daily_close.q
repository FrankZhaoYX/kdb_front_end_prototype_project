/ Daily Closing Prices -- loaded by kdb/gateway.q from the q_file column of
/ data/reports.csv. Helpers live in kdb/lib.q.

.rpt.dailyClose:{[p]
  a:p`date_from; b:p`date_to; s:p`symbols;
  .rpt.assertRange[a;b];
  .rpt.assertSyms[s];
  t:select dt,sym,open,high,low,close,volume,
           chg_pct:.rpt.rnd[4] chg_pct
      from daily where dt within (a;b);
  if[count s; t:select from t where sym in s];
  .rpt.assertRows[t;string[a]," .. ",string b]};
