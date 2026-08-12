/ Volume Leaders -- loaded by kdb/gateway.q from the q_file column of
/ data/reports.csv. Helpers live in kdb/lib.q.

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
