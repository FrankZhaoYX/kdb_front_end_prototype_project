/ The IPC entry point. Everything a client can reach goes through here.
/-
/ Two independent guards:
/   .gw.allow  restricts which q names an inbound message may name at all
/   .rpt.fn    restricts which report functions .rpt.run will dispatch to
/-
/ A client sends a report_id and a parameter dictionary. It never sends q code,
/ so there is nothing to escape or sanitise -- parameters arrive already typed
/ by the IPC layer and are only ever used as values.

/ --------------------------------------------------------------- envelopes
.gw.err:{[code;msg;fld]
  `status`code`error`field!(`err; code; msg; fld)};

/ .rpt.throw encodes "code|message|field"; anything else is an unexpected
/ signal (a genuine q error) and is reported as such with its backtrace logged.
.gw.parseErr:{[m;bt]
  p:"|" vs m;
  if[3=count p; :.gw.err[`$p 0; p 1; `$p 2]];
  -2 "gateway: unhandled signal '",m,"\n",bt;
  .gw.err[`report_error; m; `]};

/ Local is mkMeta, not meta: `meta` is a q keyword and assigning to it signals
/ 'assign. The envelope key `meta is a symbol, so that stays as it is.
.gw.wrap:{[rid;fmt;res;maxRows;el]
  mkMeta:{[n;tr;el] `rows`truncated`elapsed_ms`generated!
          (n; tr; (`long$el)%1000000; string .z.p)};
  if[fmt in `pdf`html;
    :`status`report`format`payload`meta!
      (`ok; rid; fmt; res; mkMeta[1j;0b;el])];
  n:count res;
  tr:(maxRows>0)&n>maxRows;
  if[tr; res:maxRows sublist res];
  `status`report`format`payload`meta!(`ok; rid; `table; res; mkMeta[n;tr;el])};

/ ------------------------------------------------------- catalog-driven load
/ data/reports.csv is the single source of truth for both sides. The gateway
/- reads it, loads every q file it names, and builds the dispatch whitelist
/- from the q_func column -- so adding a report is a CSV row plus a .q file,
/- with no q edit here.
/-
/ 0: has no quoted-field support, so no value in the catalog may contain a
/- comma. Descriptions are written comma-free for exactly that reason.
.gw.catalogFile:$[count getenv`REPORT_CATALOG;
                  getenv`REPORT_CATALOG;
                  "data/reports.csv"];

/ report_id category name description q_file q_func formats
/ default_format timeout_s max_rows tags
.gw.catalog:("SSS*SSSSFJS";enlist ",") 0: hsym `$.gw.catalogFile;

{system "l ",string x} each distinct .gw.catalog`q_file;

/ report_id -> function name. A client can never name anything outside this.
.rpt.fn:(!). .gw.catalog`report_id`q_func;

-1 "gateway.q: ",string[count .rpt.fn]," reports from ",.gw.catalogFile;

/ ------------------------------------------------------------------- .rpt.run
/ Output format is a property of the *request*, not a report parameter, so it
/ is a separate argument rather than a magic key inside p. (It also has to be:
/ q will not tokenise a leading underscore in a symbol literal, so `_format
/ parses as the empty symbol followed by the identifier `format` and signals.)
/ Reports that care about it read `outputFormat, which the gateway adds below.
.rpt.run:{[rid;p;maxRows;fmt]
  if[not rid in key .rpt.fn;
    :.gw.err[`unknown_report;
      "no such report: ",string[rid],
      " (known: ",(", " sv string key .rpt.fn),")"; `]];
  fmt:$[null fmt; `table; fmt];
  p:p,(enlist `outputFormat)!enlist fmt;
  t0:.z.p;
  / .Q.trp gives the error message *and* a backtrace instead of unwinding to
  / the client, which is what turns a q signal into a structured envelope.
  r:.Q.trp[{[f;p] (1b; value[f] p)}[.rpt.fn rid]; p; {[m;bt] (0b; m; .Q.sbt bt)}];
  $[first r;
    .gw.wrap[rid; fmt; r 1; maxRows; .z.p-t0];
    .gw.parseErr[r 1; r 2]]};

/ ------------------------------------------------------------------ .z.pg
/ Sync IPC handler. Rejects anything not on the allow list before evaluating.
.gw.allow:`.rpt.run`.rpt.symbols`.rpt.range`.rpt.ping`.rpt.sleep;

.gw.name:{[x]
  t:type x;
  $[10h=t; `$x;                    / "expr"        -- bare string
    0h=t;  `$x 0;                  / ("fn";a;b)    -- function call
    t in -11 11h; $[0>t; x; first x];
    '"nyi"]};

/ qPython sends a bare char vector when a call has no parameters, and a mixed
/ list (fn;args...) when it does. `value "someFn"` would return the *function*
/ rather than call it, so the no-argument form is applied niladically.
.z.pg:{[x]
  f:.gw.name x;
  if[not f in .gw.allow; '"access"];
  $[10h=type x; value[f][]; value x]};

/ Async messages are not part of this design; refuse them loudly rather than
/ silently evaluating something nobody will read the result of.
.z.ps:{[x] '"async not supported"};

.z.pw:{[u;p] 1b};   / replace with a real check before this leaves a sandbox
.z.po:{[h] 0N!(`connected;h;.z.a);};
.z.pc:{[h] 0N!(`disconnected;h);};
