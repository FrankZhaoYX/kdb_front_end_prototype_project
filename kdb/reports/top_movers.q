/ Top Movers -- loaded by kdb/gateway.q from the q_file column of
/ data/reports.csv. Helpers live in kdb/lib.q.

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
