"""Tests for the single equity-reconciliation source of truth."""

from app.portfolio_quant import reconcile_equity


def _row(ticker, price, value, shares=1.0, avg_cost=1.0):
    return {"ticker": ticker, "price": price, "value": value,
            "shares": shares, "avg_cost": avg_cost}


def test_all_priced_uses_live_quotes():
    rows = [_row("AAPL", 200.0, 2000.0), _row("NVDA", 300.0, 1500.0)]
    rec = reconcile_equity(rows, {"equity_value": 9999.0})
    assert rec["total_value"] == 3500.0
    assert rec["priced_value"] == 3500.0
    assert rec["source"] == "live_quotes"  # no stale names → ignore snapshot
    assert rec["stale_tickers"] == []


def test_stale_quote_prefers_broker_snapshot():
    rows = [_row("AAPL", 200.0, 2000.0), _row("XYZ", None, None)]
    rec = reconcile_equity(rows, {"equity_value": 11386.0})
    assert rec["total_value"] == 11386.0
    assert rec["priced_value"] == 2000.0
    assert rec["source"] == "broker_snapshot"
    assert rec["stale_tickers"] == ["XYZ"]


def test_stale_quote_without_snapshot_falls_back_to_priced():
    rows = [_row("AAPL", 200.0, 2000.0), _row("XYZ", None, None)]
    rec = reconcile_equity(rows, {})
    assert rec["total_value"] == 2000.0
    assert rec["source"] == "live_quotes"
    assert rec["stale_tickers"] == ["XYZ"]


def test_zero_price_is_treated_as_stale():
    rows = [_row("AAPL", 0.0, 0.0), _row("NVDA", 300.0, 1500.0)]
    rec = reconcile_equity(rows, {"equity_value": 5000.0})
    assert "AAPL" in rec["stale_tickers"]
    assert rec["total_value"] == 5000.0


def test_empty_rows():
    rec = reconcile_equity([], {"equity_value": 100.0})
    assert rec["total_value"] == 0.0
    assert rec["priced_value"] == 0.0
    assert rec["source"] == "live_quotes"
    assert rec["stale_tickers"] == []


def test_rows_without_ticker_ignored():
    rows = [{"price": 10.0, "value": 10.0}, _row("AAPL", 200.0, 2000.0)]
    rec = reconcile_equity(rows, {})
    assert rec["priced_value"] == 2000.0
