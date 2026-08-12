/ Loads the NASDAQ daily bars produced by scripts/build_data.py.
/-
/ Both CSVs are written unquoted and ASCII-only precisely because 0: has no
/ concept of a quoted field -- see q_safe() in scripts/build_data.py.

.dat.root:$[count getenv`KDB_DATA_DIR; getenv`KDB_DATA_DIR; "data"];
.dat.file:{hsym `$.dat.root,"/",x};

/ dt,sym,open,high,low,close,volume
daily:("DSFFFFJ";enlist ",") 0: .dat.file "nsdq_daily.csv";
/ sym,name,market_category,etf
syms:("SSSS";enlist ",") 0: .dat.file "nsdq_symbols.csv";

/ prev_close / chg_pct are derived once here rather than in every report.
/ `by sym` needs dt ascending inside each symbol group, so sort that way first.
daily:`sym`dt xasc daily;
update prev_close:prev close, chg_pct:100*(close-prev close)%prev close
  by sym from `daily;

/ Reports filter on dt first, so store in dt order and let `s# drive the search.
daily:`dt`sym xasc daily;
update `s#dt from `daily;
update `g#sym from `daily;

syms:`sym xasc syms;
.dat.symUniverse:exec sym from syms;

-1 "data.q: ",string[count daily]," rows, ",string[count .dat.symUniverse],
   " symbols, ",string[min daily`dt]," .. ",string[max daily`dt];
