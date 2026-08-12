/ Real kdb+ report gateway.
/-
/   q kdb/start.q -p 5000
/-
/ Run it from the repository root so the relative data paths resolve, or set
/ KDB_DATA_DIR and KDB_REPORT_DIR. This process is meant to be *separate* from
/ your production KDB server: it is the one that blocks while a report runs.
/-
/ To point it at a real KDB server through your Sandbox IPC layer, replace the
/ `daily` / `syms` tables in data.q with handles to the sandbox and leave
/ reports.q and gateway.q as they are.

\l kdb/data.q
\l kdb/lib.q
\l kdb/gateway.q

.rpt.outDir:$[count getenv`KDB_REPORT_DIR; getenv`KDB_REPORT_DIR; "var/reports"];
system "mkdir -p ",.rpt.outDir;

-1 "";
-1 "report gateway ready on port ",string system"p";
-1 "  reports  : ",", " sv string key .rpt.fn;
-1 "  allowed  : ",", " sv string .gw.allow;
-1 "  pdf conv : ",$[count getenv`KDB_HTML2PDF;
                     getenv`KDB_HTML2PDF;
                     "(unset -- KDB_HTML2PDF, PDF format will error)"];
-1 "  out dir  : ",.rpt.outDir;
-1 "";
