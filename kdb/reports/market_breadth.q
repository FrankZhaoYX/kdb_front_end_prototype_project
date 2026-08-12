/ Market Breadth -- loaded by kdb/gateway.q from the q_file column of
/ data/reports.csv. Helpers live in kdb/lib.q.

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
