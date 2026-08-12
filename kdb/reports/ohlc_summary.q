/ Symbol Statistics Summary -- loaded by kdb/gateway.q from the q_file column of
/ data/reports.csv. Helpers live in kdb/lib.q.

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
