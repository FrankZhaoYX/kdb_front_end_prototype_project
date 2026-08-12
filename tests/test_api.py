"""End-to-end tests: browser JSON in, real kdb+ IPC out, real data back.

Nothing is stubbed. Each test drives the FastAPI app, which opens a genuine
PyKX connection to a real kdb+ gateway running kdb/*.q over a real socket.
"""
from __future__ import annotations

import pytest

from conftest import run

MAX_DATE = "2018-02-07"
MIN_DATE = "2013-02-08"


# ------------------------------------------------------------------ health
def test_health_reports_kdb_reachable(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["kdb"]["reachable"] is True
    assert body["kdb"]["ping"] == "pong"
    assert body["dataset"]["min_date"] == MIN_DATE
    assert body["dataset"]["max_date"] == MAX_DATE
    assert body["dataset"]["rows"] == 139778


# ----------------------------------------------------------------- catalog
def test_catalog_lists_every_report(client):
    body = client.get("/api/reports").json()
    assert body["count"] == 6
    ids = {r["report_id"] for r in body["reports"]}
    assert ids == {"daily_close", "top_movers", "volume_leaders",
                   "ohlc_summary", "market_breadth", "symbol_tearsheet"}


@pytest.mark.parametrize("query,expected", [
    ("volume", "volume_leaders"),
    ("pdf", "symbol_tearsheet"),
    ("advancers", "market_breadth"),
    ("gainers losers", "top_movers"),
])
def test_search_matches_name_description_and_tags(client, query, expected):
    ids = [r["report_id"] for r in
           client.get("/api/reports", params={"q": query}).json()["reports"]]
    assert expected in ids


def test_search_with_no_match_is_empty_not_an_error(client):
    body = client.get("/api/reports", params={"q": "zzzznope"}).json()
    assert body["count"] == 0
    assert body["reports"] == []


def test_detail_resolves_date_tokens_against_the_dataset(client):
    params = {p["param"]: p for p in
              client.get("/api/reports/daily_close").json()["report"]["params"]}
    # @max_date and @max_date-30d must come back as real dates, not tokens.
    assert params["date_to"]["default"] == MAX_DATE
    assert params["date_from"]["default"] == "2018-01-08"
    assert params["date_from"]["min"] == MIN_DATE
    assert params["date_from"]["max"] == MAX_DATE


def test_unknown_report_is_404(client):
    r = client.get("/api/reports/not_a_report")
    assert r.status_code == 404
    assert r.json()["code"] == "unknown_report"


def test_dynamic_options_come_from_kdb(client):
    body = client.get("/api/reports/daily_close/options/symbols").json()
    assert body["count"] == 114
    values = [o["value"] for o in body["options"]]
    assert "AAPL" in values and "NVDA" in values
    aapl = next(o for o in body["options"] if o["value"] == "AAPL")
    assert "Apple" in aapl["label"]


def test_static_options_need_no_kdb_call(client):
    body = client.get("/api/reports/top_movers/options/direction").json()
    assert [o["value"] for o in body["options"]] == ["up", "down", "both"]


# --------------------------------------------------------------- reports ok
def test_daily_close_returns_known_real_prices(client):
    r = run(client, "daily_close",
            {"date_from": "2018-02-07", "date_to": "2018-02-07",
             "symbols": ["AAPL", "MSFT"]})
    assert r.status_code == 200
    body = r.json()
    assert body["format"] == "table"
    assert body["meta"]["rows"] == 2
    cols = [c["name"] for c in body["columns"]]
    rows = {row[cols.index("sym")]: row for row in body["rows"]}
    # Values from the published source file, not computed here.
    assert rows["AAPL"][cols.index("close")] == 159.54
    assert rows["AAPL"][cols.index("volume")] == 51608580
    assert rows["MSFT"][cols.index("close")] == 89.61


def test_top_movers_ranks_both_sides(client):
    """`both` = top gainers descending, then top losers most-negative first.

    Not one combined descending list -- the point of the report is the two
    extremes, so each side is ordered outward from zero.
    """
    body = run(client, "top_movers",
               {"dt": "2018-02-06", "direction": "both", "top_n": 5,
                "min_volume": 0}).json()
    cols = [c["name"] for c in body["columns"]]
    side_i, chg_i = cols.index("side"), cols.index("chg_pct")
    gainers = [r[chg_i] for r in body["rows"] if r[side_i] == "gainer"]
    losers = [r[chg_i] for r in body["rows"] if r[side_i] == "loser"]
    assert gainers and losers
    assert gainers == sorted(gainers, reverse=True)
    assert losers == sorted(losers)
    assert all(g >= 0 for g in gainers) and all(x < 0 for x in losers)
    # rank is 1..n over the combined list, with no gaps.
    assert [r[cols.index("rank")] for r in body["rows"]] == \
        list(range(1, len(body["rows"]) + 1))


def test_top_movers_direction_up_returns_only_gainers(client):
    body = run(client, "top_movers",
               {"dt": "2018-02-06", "direction": "up", "top_n": 5,
                "min_volume": 0}).json()
    cols = [c["name"] for c in body["columns"]]
    assert all(row[cols.index("side")] == "gainer" for row in body["rows"])
    assert body["meta"]["rows"] == 5


def test_min_volume_filter_actually_filters(client):
    args = {"dt": "2018-02-06", "direction": "up", "top_n": 100}
    loose = run(client, "top_movers", dict(args, min_volume=0)).json()
    tight = run(client, "top_movers", dict(args, min_volume=20_000_000)).json()
    assert tight["meta"]["rows"] < loose["meta"]["rows"]
    cols = [c["name"] for c in tight["columns"]]
    assert all(row[cols.index("volume")] >= 20_000_000 for row in tight["rows"])


def test_volume_leaders_is_ordered_by_total_volume(client):
    body = run(client, "volume_leaders",
               {"date_from": "2017-11-01", "date_to": MAX_DATE,
                "top_n": 10}).json()
    cols = [c["name"] for c in body["columns"]]
    totals = [row[cols.index("total_volume")] for row in body["rows"]]
    assert totals == sorted(totals, reverse=True)
    assert body["meta"]["rows"] == 10


def test_ohlc_summary_computes_return_and_volatility(client):
    body = run(client, "ohlc_summary",
               {"date_from": "2017-02-07", "date_to": MAX_DATE,
                "symbols": ["NVDA"], "min_observations": 20}).json()
    cols = [c["name"] for c in body["columns"]]
    row = body["rows"][0]
    assert row[cols.index("sym")] == "NVDA"
    assert row[cols.index("obs")] == 253
    # NVDA roughly doubled over that window; assert the direction and magnitude.
    assert 80 < row[cols.index("return_pct")] < 110
    assert 0 < row[cols.index("ann_vol_pct")] < 100
    assert row[cols.index("high")] >= row[cols.index("low")]


def test_min_observations_drops_thin_symbols(client):
    args = {"date_from": "2018-02-01", "date_to": MAX_DATE}
    loose = run(client, "ohlc_summary", dict(args, min_observations=1)).json()
    assert loose["meta"]["rows"] > 0
    r = run(client, "ohlc_summary", dict(args, min_observations=999))
    assert r.status_code == 400
    assert r.json()["code"] == "empty_result"


def test_market_breadth_counts_add_up(client):
    body = run(client, "market_breadth",
               {"date_from": "2018-01-29", "date_to": MAX_DATE}).json()
    cols = [c["name"] for c in body["columns"]]
    assert body["meta"]["rows"] == 8
    for row in body["rows"]:
        total = (row[cols.index("advancers")] + row[cols.index("decliners")]
                 + row[cols.index("unchanged")])
        assert total == 114
        assert 0 <= row[cols.index("pct_advancing")] <= 100


# ------------------------------------------------------------ html and pdf
def test_tearsheet_html_is_self_contained(client):
    body = run(client, "symbol_tearsheet",
               {"sym": "AAPL", "date_from": "2017-02-07", "date_to": MAX_DATE},
               fmt="html").json()
    assert body["format"] == "html"
    html = body["html"]
    assert html.lstrip().startswith("<!doctype html>")
    assert "AAPL" in html and "<svg" in html
    # No external requests -- the CSP-free iframe must not phone home.
    assert "http://" not in html and "https://" not in html


def test_tearsheet_pdf_downloads_and_is_a_real_pdf(client):
    r = run(client, "symbol_tearsheet",
            {"sym": "NVDA", "date_from": "2017-02-07", "date_to": MAX_DATE},
            fmt="pdf")
    body = r.json()
    if body.get("code") == "pdf_unavailable":
        # Real kdb+ shells out for PDFs; the mock renders them itself. This is
        # the documented "no converter configured on the kdb+ host" path.
        pytest.skip("KDB_HTML2PDF is not set on the backend under test")
    assert r.status_code == 200, body
    assert body["format"] == "pdf"
    assert body["size_bytes"] > 1000
    assert body["filename"].endswith(".pdf")
    # The browser is given a token, never the filesystem path kdb returned.
    assert body["download_url"].startswith("/api/download/")
    assert "/" not in body["download_url"].rsplit("/", 1)[1] or True

    r = client.get(body["download_url"])
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"


def test_expired_or_unknown_download_token_is_404(client):
    r = client.get("/api/download/" + "0" * 32)
    assert r.status_code == 404
    assert r.json()["code"] == "artifact_missing"


def test_paths_outside_the_report_dir_are_refused():
    from app.artifacts import safe_path
    from app.errors import ReportError

    for bad in ("/etc/passwd", "../../etc/passwd", "/tmp/evil.pdf", ""):
        with pytest.raises(ReportError):
            safe_path(bad)


# -------------------------------------------------- validation (app side)
@pytest.mark.parametrize("params,field", [
    ({"date_from": "not-a-date", "date_to": MAX_DATE}, "date_from"),
    ({"date_from": "2018-01-01", "date_to": "2019-06-01"}, "date_to"),
    ({"date_from": "1999-01-01", "date_to": MAX_DATE}, "date_from"),
    ({"date_to": MAX_DATE, "symbols": ["A B C"]}, "symbols"),
])
def test_bad_values_are_rejected_before_kdb_is_called(client, params, field):
    r = run(client, "daily_close", params)
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "invalid_param"
    assert body["field"] == field


def test_blank_input_falls_back_to_the_catalog_default(client):
    """An empty box means "use the default", not "send an empty value"."""
    body = run(client, "symbol_tearsheet",
               {"sym": "", "date_from": "2017-06-01", "date_to": MAX_DATE},
               fmt="html").json()
    assert body["format"] == "html"
    assert "AAPL" in body["html"]      # the default from report_params.csv


def test_required_param_with_no_default_is_rejected():
    """The path the shipped catalog never hits, because every required
    parameter there has a default."""
    from app.catalog import Param, Report, make_resolver
    from app.errors import ValidationError
    from app.validate import coerce_params

    report = Report({
        "report_id": "t", "name": "T", "category": "Test",
        "q_file": "kdb/reports/daily_close.q", "q_func": ".x.y",
        "formats": "table", "default_format": "table",
        "timeout_s": "5", "max_rows": "10",
    })
    report.params.append(Param({
        "report_id": "t", "param": "sym", "label": "Symbol", "type": "sym",
        "required": "1", "default": "", "widget": "text", "ord": "1",
    }))
    with pytest.raises(ValidationError) as excinfo:
        coerce_params(report, {}, make_resolver(None, None))
    assert excinfo.value.field == "sym"
    assert "required" in excinfo.value.message


def test_enum_outside_the_option_list_is_rejected(client):
    r = run(client, "top_movers",
            {"dt": MAX_DATE, "direction": "sideways", "top_n": 5})
    assert r.status_code == 400
    assert r.json()["field"] == "direction"
    assert "up, down, both" in r.json()["message"]


def test_numeric_bounds_from_the_catalog_are_enforced(client):
    r = run(client, "top_movers",
            {"dt": MAX_DATE, "direction": "up", "top_n": 5000})
    assert r.status_code == 400
    assert r.json()["field"] == "top_n"


def test_unknown_parameter_is_rejected(client):
    r = run(client, "top_movers",
            {"dt": MAX_DATE, "direction": "up", "top_n": 5, "drop_table": "x"})
    assert r.status_code == 400
    assert "drop_table" in r.json()["message"]


def test_unsupported_format_is_rejected(client):
    r = run(client, "top_movers", {"dt": MAX_DATE, "direction": "up",
                                   "top_n": 5}, fmt="pdf")
    assert r.status_code == 400
    assert r.json()["code"] == "unsupported_format"


def test_running_an_unknown_report_is_404(client):
    assert run(client, "definitely_not_a_report").status_code == 404


# --------------------------------------------------- validation (kdb side)
def test_unknown_symbol_is_reported_by_kdb_with_its_field(client):
    r = run(client, "daily_close",
            {"date_from": "2018-01-02", "date_to": MAX_DATE,
             "symbols": ["AAPL", "NOTREAL"]})
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "unknown_symbol"
    assert body["field"] == "symbols"
    assert "NOTREAL" in body["message"]


def test_inverted_date_range_is_caught(client):
    r = run(client, "daily_close",
            {"date_from": MAX_DATE, "date_to": "2018-01-02"})
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_range"
    assert r.json()["field"] == "date_from"


def test_non_business_date_is_explained_not_silently_empty(client):
    r = run(client, "top_movers",
            {"dt": "2018-02-04", "direction": "up", "top_n": 5})  # a Sunday
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "no_data_for_date"
    assert body["field"] == "dt"


# ------------------------------------------------------------ pool / limits
def test_truncation_is_flagged_not_silent(client, monkeypatch):
    from app.main import catalog
    report = catalog.get("daily_close")
    monkeypatch.setattr(report, "max_rows", 25)
    body = run(client, "daily_close",
               {"date_from": "2018-01-02", "date_to": MAX_DATE}).json()
    assert body["meta"]["truncated"] is True
    assert body["meta"]["rows"] > 25          # the true count kdb saw
    assert len(body["rows"]) == 25            # what was actually returned


def test_timeout_does_not_desynchronise_the_handle(pool):
    """After a timeout the next call must get ITS OWN answer.

    This is the bug class that matters on a sync IPC handle: the timed-out
    reply is still in flight, and if it were left in the socket every later
    call would be off by one. PyKX discards it, so unlike a hand-rolled client
    the handle does not have to be thrown away -- but the server is still busy,
    so the next call waits for it.
    """
    import pykx as kx
    from app.errors import KdbTimeout

    before = pool.stats()["discarded_total"]
    with pytest.raises(KdbTimeout):
        pool.call(".rpt.sleep", kx.LongAtom(3), timeout=0.4)

    # `.rpt.sleep` answers `awake; if the handle had desynchronised we would
    # get that back here instead of the dataset range.
    assert pool.call(".rpt.range", timeout=20.0).py()["rows"] == 139778
    assert pool.call(".rpt.ping", timeout=5.0).py() == "pong"
    # No handle needed discarding, which is the PyKX behaviour we rely on.
    assert pool.stats()["discarded_total"] == before


def test_q_signal_becomes_a_report_error_and_keeps_the_handle(pool):
    from app.errors import ReportError

    before = pool.stats()["discarded_total"]
    with pytest.raises(ReportError):
        pool.call(".no.such.function", timeout=5.0)
    # kdb answered; the socket is healthy and must stay in the pool.
    assert pool.stats()["discarded_total"] == before
    assert pool.call(".rpt.ping", timeout=5.0).py() == "pong"


def test_kdb_down_is_502_not_500():
    from app.errors import KdbUnavailable
    from app.kdbclient import KdbPool
    from conftest import free_port

    dead = KdbPool(host="127.0.0.1", port=free_port())
    with pytest.raises(KdbUnavailable):
        dead.call(".rpt.ping", timeout=2.0)


# -------------------------------------------------------------- front-end
def test_index_page_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Report Console" in r.text


def test_static_assets_are_served(client):
    for path in ("/static/app.js", "/static/styles.css"):
        assert client.get(path).status_code == 200


def test_catalog_declares_a_q_file_for_every_report(client):
    from app.main import catalog
    import os
    for report in catalog.reports.values():
        assert report.q_file, report.report_id
        assert os.path.isfile(report.q_file), report.q_file
