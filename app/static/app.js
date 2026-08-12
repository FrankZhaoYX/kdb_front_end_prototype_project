/* KDB Report Console -- vanilla ES2018, no dependencies, no build step.
 *
 * The form is generated entirely from /api/reports/{id}: add a row to
 * report_params.csv and the input appears here with no JS change.
 *
 * Errors follow one shape from the server: {status,code,message,field?,detail?}.
 * A `field` puts the message under that input; without one it goes to the
 * banner. That is the whole error-handling contract.
 */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var state = { reports: [], category: "", selected: null, detail: null,
                sort: null, table: null };
  var ALL = "— all categories —";

  /* ------------------------------------------------------------ utilities */
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === "class") n.className = attrs[k];
      else if (k === "text") n.textContent = attrs[k];
      else if (k.slice(0, 2) === "on") n.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] !== null && attrs[k] !== undefined) n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) n.appendChild(c); });
    return n;
  }

  function fmtNum(v) {
    if (v === null || v === undefined) return "";
    if (Math.abs(v) >= 1000 || Number.isInteger(v)) return v.toLocaleString();
    return String(v);
  }

  async function api(url, opts) {
    var res, body;
    try {
      res = await fetch(url, opts);
    } catch (e) {
      throw { code: "network_error", message: "Cannot reach the report service.",
              detail: String(e) };
    }
    try { body = await res.json(); }
    catch (e) {
      throw { code: "bad_response", message: "The server returned a malformed response.",
              detail: "HTTP " + res.status };
    }
    if (!res.ok || body.status === "err") {
      throw { code: body.code || ("http_" + res.status),
              message: body.message || "Request failed.",
              field: body.field, detail: body.detail };
    }
    return body;
  }

  /* -------------------------------------------------------------- health */
  async function health() {
    try {
      var h = await api("/api/health");
      var up = h.kdb && h.kdb.reachable;
      $("health-dot").className = "dot " + (up ? "ok" : "bad");
      $("health-text").textContent = up
        ? ("kdb " + h.kdb.host + ":" + h.kdb.port +
           (h.dataset ? "  ·  " + Number(h.dataset.rows).toLocaleString() +
            " rows  ·  " + h.dataset.min_date + " to " + h.dataset.max_date : ""))
        : ("kdb unreachable — " + ((h.kdb && h.kdb.error) || "unknown"));
    } catch (e) {
      $("health-dot").className = "dot bad";
      $("health-text").textContent = "service unreachable";
    }
  }

  /* ------------------------------------------------------------- catalog */
  async function loadReports(q) {
    try {
      var data = await api("/api/reports?q=" + encodeURIComponent(q || ""));
      state.reports = data.reports;
      populateCategories();
      populateReports();
    } catch (e) { banner(e); }
  }

  /* Layer 1a: categories, derived from whatever the search returned. The
     current choice is kept if it still has matches, so typing in the search
     box does not silently move the user to a different category. */
  function populateCategories() {
    var cats = [];
    state.reports.forEach(function (r) {
      if (cats.indexOf(r.category) === -1) cats.push(r.category);
    });
    cats.sort();
    if (cats.indexOf(state.category) === -1) state.category = "";

    var sel = $("category");
    sel.textContent = "";
    sel.appendChild(el("option", { value: "", text: ALL }));
    cats.forEach(function (c) {
      sel.appendChild(el("option", { value: c, text: c,
        selected: c === state.category ? "selected" : null }));
    });
    sel.value = state.category;
    sel.disabled = !cats.length;
  }

  /* Layer 1b: reports, filtered by the category chosen above. */
  function visibleReports() {
    return state.reports.filter(function (r) {
      return !state.category || r.category === state.category;
    });
  }

  function populateReports() {
    var items = visibleReports();
    var sel = $("report-select");
    sel.textContent = "";
    sel.disabled = !items.length;

    if (!items.length) {
      sel.appendChild(el("option", { value: "", text: "no reports match" }));
      state.selected = null;
      state.detail = null;
      $("report-desc").textContent = "";
      $("param-form").classList.add("hidden");
      $("params-empty").classList.remove("hidden");
      $("report-name").textContent = "Parameters";
      return;
    }

    items.forEach(function (r) {
      sel.appendChild(el("option", { value: r.report_id, text: r.name }));
    });

    // Keep the current report if it survived the filter, else take the first.
    var keep = items.some(function (r) { return r.report_id === state.selected; });
    var next = keep ? state.selected : items[0].report_id;
    sel.value = next;
    if (next !== state.selected || !state.detail) select(next);
  }

  /* ---------------------------------------------------------- param form */
  async function select(id) {
    state.selected = id;
    clearBanner();
    clearFieldErrors();
    try {
      var data = await api("/api/reports/" + encodeURIComponent(id));
      state.detail = data.report;
      renderForm(data.report);
    } catch (e) { banner(e); }
  }

  function field(p) {
    var wrap = el("div", { class: "field", "data-param": p.param });
    var lbl = el("label", { for: "p_" + p.param, text: p.label });
    if (p.required) lbl.appendChild(el("span", { class: "req", text: "*" }));
    wrap.appendChild(lbl);

    var input;
    if (p.widget === "multiselect") {
      input = el("select", { id: "p_" + p.param, multiple: "multiple" });
      loadOptions(p, input, true);
      wrap.appendChild(input);
      wrap.appendChild(el("div", { class: "hint",
        text: "Ctrl/Cmd-click for several. Leave empty for all." }));
    } else if (p.widget === "select") {
      input = el("select", { id: "p_" + p.param });
      if (p.dynamic_options) loadOptions(p, input, false);
      else {
        if (!p.required) input.appendChild(el("option", { value: "", text: "—" }));
        p.options.forEach(function (o) {
          input.appendChild(el("option", { value: o, text: o,
            selected: o === p.default ? "selected" : null }));
        });
      }
      wrap.appendChild(input);
    } else {
      var type = p.widget === "date" ? "date" : (p.widget === "number" ? "number" : "text");
      input = el("input", { id: "p_" + p.param, type: type, value: p.default || "" });
      if (p.min) input.setAttribute("min", p.min);
      if (p.max) input.setAttribute("max", p.max);
      wrap.appendChild(input);
    }
    input.dataset.param = p.param;
    input.dataset.ptype = p.type;

    if (p.help) wrap.appendChild(el("div", { class: "help", text: p.help }));
    wrap.appendChild(el("div", { class: "err" }));
    return wrap;
  }

  async function loadOptions(p, select, multi) {
    select.appendChild(el("option", { value: "", text: "loading…", disabled: "disabled" }));
    try {
      var data = await api("/api/reports/" + encodeURIComponent(state.selected) +
                           "/options/" + encodeURIComponent(p.param));
      select.textContent = "";
      if (!multi && !p.required) select.appendChild(el("option", { value: "", text: "—" }));
      data.options.forEach(function (o) {
        select.appendChild(el("option", { value: o.value, text: o.label,
          selected: (!multi && o.value === p.default) ? "selected" : null }));
      });
    } catch (e) {
      select.textContent = "";
      select.appendChild(el("option", { value: "", text: "could not load options" }));
      banner(e);
    }
  }

  function renderForm(r) {
    $("params-empty").classList.add("hidden");
    var form = $("param-form");
    form.classList.remove("hidden");
    // The name lives in the selector bar now; the sidebar heading just says
    // what this panel is, qualified by the report.
    $("report-name").textContent = r.name + " — parameters";
    $("report-desc").textContent = r.description;

    var fields = $("param-fields");
    fields.textContent = "";
    r.params.forEach(function (p) { fields.appendChild(field(p)); });

    var ff = $("format-field");
    ff.textContent = "";
    if (r.formats.length > 1) {
      ff.appendChild(el("label", { for: "p__format", text: "Output format" }));
      var sel = el("select", { id: "p__format" });
      r.formats.forEach(function (f) {
        sel.appendChild(el("option", { value: f, text: f.toUpperCase(),
          selected: f === r.default_format ? "selected" : null }));
      });
      ff.appendChild(sel);
    }
  }

  function collect() {
    var out = {};
    (state.detail.params || []).forEach(function (p) {
      var node = document.getElementById("p_" + p.param);
      if (!node) return;
      if (node.multiple) {
        out[p.param] = Array.prototype.filter
          .call(node.selectedOptions, function (o) { return o.value; })
          .map(function (o) { return o.value; });
      } else {
        out[p.param] = node.value;
      }
    });
    return out;
  }

  /* ---------------------------------------------------------------- run */
  async function run(ev) {
    ev.preventDefault();
    clearBanner();
    clearFieldErrors();
    var fmtNode = $("p__format");
    var payload = {
      report_id: state.selected,
      params: collect(),
      format: fmtNode ? fmtNode.value : state.detail.default_format
    };
    busy(true);
    try {
      var res = await api("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      renderResult(res);
    } catch (e) {
      if (e.field) fieldError(e.field, e.message); else banner(e);
      // Keep whatever was already on screen, but mark it stale. Blanking the
      // panel loses the user's place; leaving it undimmed reads as a result.
      $("result").classList.add("stale");
      $("result-meta").classList.add("stale");
    } finally {
      busy(false);
    }
  }

  function busy(on) {
    $("run-btn").disabled = on;
    $("run-btn").textContent = on ? "Running…" : "Run report";
    $("spinner").classList.toggle("hidden", !on);
  }

  /* ------------------------------------------------------------ results */
  function showMeta(res) {
    var box = $("result-meta");
    if (!res) { box.classList.add("hidden"); box.textContent = ""; return; }
    box.textContent = "";
    box.classList.remove("hidden");
    var m = res.meta || {};
    box.appendChild(el("span", {}, [
      el("b", { text: Number(m.rows || 0).toLocaleString() }),
      document.createTextNode(" rows")
    ]));
    box.appendChild(el("span", { text: "kdb " + (m.kdb_ms != null ? m.kdb_ms : "?") +
                                        " ms  ·  round trip " + m.total_ms + " ms" }));
    if (m.truncated) {
      box.appendChild(el("span", { class: "warn",
        text: "⚠ truncated to " + Number(m.max_rows).toLocaleString() + " rows" }));
    }
    if (m.generated) box.appendChild(el("span", { text: "generated " + m.generated }));
    if (res.format === "table" && state.table) {
      box.appendChild(el("span", { class: "grow" }, [
        el("a", { href: "#", text: "Download CSV", onclick: function (e) {
          e.preventDefault(); downloadCsv(res);
        } })
      ]));
    }
  }

  function renderResult(res) {
    state.table = res.format === "table" ? res : null;
    state.sort = null;
    showMeta(res);
    var box = $("result");
    box.classList.remove("stale");
    $("result-meta").classList.remove("stale");
    box.textContent = "";

    if (res.format === "table") {
      box.appendChild(buildGrid(res));
    } else if (res.format === "html") {
      var f = el("iframe", { class: "frame", sandbox: "", title: res.name });
      box.appendChild(f);
      f.srcdoc = res.html;   /* sandboxed: no scripts, no same-origin access */
    } else if (res.format === "pdf") {
      var wrap = el("div", { class: "pdf-wrap" }, [
        el("div", { class: "pdf-bar" }, [
          el("span", { text: res.filename + "  ·  " +
                             Math.round(res.size_bytes / 1024) + " KB" }),
          el("span", { class: "grow" }),
          el("a", { href: res.download_url, download: res.filename, text: "Download" })
        ]),
        el("iframe", { class: "frame", src: res.download_url, title: res.filename })
      ]);
      box.appendChild(wrap);
    }
  }

  function buildGrid(res) {
    var cols = res.columns, rows = res.rows.slice();
    if (state.sort) {
      var i = state.sort.index, dir = state.sort.dir;
      rows.sort(function (a, b) {
        var x = a[i], y = b[i];
        if (x === null) return 1;
        if (y === null) return -1;
        if (x === y) return 0;
        return (x > y ? 1 : -1) * dir;
      });
    }
    var head = el("tr", {}, cols.map(function (c, i) {
      var cls = state.sort && state.sort.index === i
        ? (state.sort.dir === 1 ? "asc" : "desc") : "";
      return el("th", { class: cls, text: c.name, title: "q type: " + c.type,
        onclick: function () {
          state.sort = (state.sort && state.sort.index === i)
            ? { index: i, dir: -state.sort.dir } : { index: i, dir: 1 };
          var box = $("result");
          box.textContent = "";
          box.appendChild(buildGrid(res));
        } });
    }));

    var body = el("tbody", {}, rows.map(function (r) {
      return el("tr", {}, r.map(function (v, i) {
        var c = cols[i], cls = [];
        if (v === null || v === undefined) {
          cls.push("null");
          return el("td", { class: cls.join(" "), text: "—" });
        }
        var text;
        if (c.type === "number") {
          cls.push("num");
          text = fmtNum(v);
          if (/chg_pct|return_pct|avg_chg/.test(c.name)) cls.push(v > 0 ? "pos" : (v < 0 ? "neg" : ""));
        } else if (c.type === "boolean") {
          text = v ? "true" : "false";
        } else {
          text = String(v);
        }
        return el("td", { class: cls.join(" "), text: text });
      }));
    }));

    return el("table", { class: "grid" }, [el("thead", {}, [head]), body]);
  }

  function downloadCsv(res) {
    var esc = function (v) {
      if (v === null || v === undefined) return "";
      var s = String(v);
      return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    var lines = [res.columns.map(function (c) { return esc(c.name); }).join(",")];
    res.rows.forEach(function (r) { lines.push(r.map(esc).join(",")); });
    var blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    var a = el("a", { href: URL.createObjectURL(blob),
                      download: res.report + ".csv" });
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 0);
  }

  /* -------------------------------------------------------------- errors */
  function banner(e) {
    var b = $("banner");
    b.textContent = "";
    b.classList.remove("hidden");
    b.appendChild(el("div", {}, [
      el("span", { text: e.message || "Something went wrong." }),
      document.createTextNode(" "),
      el("span", { class: "code", text: "[" + (e.code || "error") + "]" })
    ]));
    if (e.detail) b.appendChild(el("div", { class: "detail", text: e.detail }));
  }
  function clearBanner() { $("banner").classList.add("hidden"); $("banner").textContent = ""; }

  function fieldError(param, msg) {
    var wrap = document.querySelector('.field[data-param="' + param + '"]');
    if (!wrap) return banner({ code: "invalid_param", message: msg });
    wrap.classList.add("invalid");
    wrap.querySelector(".err").textContent = msg;
    var input = wrap.querySelector("input,select");
    if (input) input.focus();
  }
  function clearFieldErrors() {
    document.querySelectorAll(".field.invalid").forEach(function (f) {
      f.classList.remove("invalid");
      f.querySelector(".err").textContent = "";
    });
  }

  /* ---------------------------------------------------------------- init */
  var timer = null;
  $("search").addEventListener("input", function (e) {
    clearTimeout(timer);
    var v = e.target.value;
    timer = setTimeout(function () { loadReports(v); }, 150);
  });
  $("category").addEventListener("change", function (e) {
    state.category = e.target.value;
    populateReports();          // layer 2 follows layer 1
  });
  $("report-select").addEventListener("change", function (e) {
    if (e.target.value) select(e.target.value);
  });
  $("param-form").addEventListener("submit", run);
  $("reset-btn").addEventListener("click", function () {
    if (state.detail) renderForm(state.detail);
    clearBanner();
    clearFieldErrors();
  });

  health();
  setInterval(health, 20000);
  loadReports("");
})();
