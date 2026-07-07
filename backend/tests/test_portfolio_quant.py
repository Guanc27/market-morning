"""Tests for compute_portfolio_quant aggregates (network fetch stubbed out)."""

import pytest

from app import portfolio_quant


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    # Stub the yfinance history fetch so aggregates compute without network and
    # betas/correlation degrade to None (best-effort by design).
    monkeypatch.setattr(portfolio_quant, "_fetch_history", lambda ticker: None)
    portfolio_quant._QUANT_CACHE.clear()


def _row(ticker, price, value, shares, avg_cost, ret):
    return {"ticker": ticker, "price": price, "value": value,
            "shares": shares, "avg_cost": avg_cost, "return_pct": ret}


def test_aggregates_all_priced():
    rows = [
        _row("AAPL", 200.0, 2000.0, 10, 100.0, 100.0),
        _row("NVDA", 300.0, 1500.0, 5, 100.0, 200.0),
    ]
    q = portfolio_quant.compute_portfolio_quant(
        rows, technicals={}, market={"VIX": {"price": 15}}, account={"equity_value": 9999.0}
    )
    agg = q["aggregates"]
    assert q["available"] is True
    assert agg["total_value"] == 3500.0
    assert agg["priced_value"] == 3500.0
    assert agg["equity_source"] == "live_quotes"
    assert agg["position_count"] == 2
    assert agg["quote_unavailable_tickers"] == []
    assert agg["hhi"] is not None


def test_aggregates_stale_prefers_snapshot():
    rows = [
        _row("AAPL", 200.0, 2000.0, 10, 100.0, 100.0),
        _row("XYZ", None, None, 10, 50.0, None),
    ]
    q = portfolio_quant.compute_portfolio_quant(
        rows, technicals={}, market={}, account={"equity_value": 5000.0}
    )
    agg = q["aggregates"]
    assert agg["total_value"] == 5000.0
    assert agg["priced_value"] == 2000.0
    assert agg["equity_source"] == "broker_snapshot"
    assert "XYZ" in agg["quote_unavailable_tickers"]


def test_total_cost_spans_all_holdings():
    rows = [
        _row("AAPL", 200.0, 2000.0, 10, 100.0, 100.0),  # cost 1000
        _row("XYZ", None, None, 10, 50.0, None),          # cost 500
    ]
    q = portfolio_quant.compute_portfolio_quant(
        rows, technicals={}, market={}, account={"equity_value": 5000.0}
    )
    assert q["aggregates"]["total_cost"] == 1500.0


def test_empty_portfolio():
    q = portfolio_quant.compute_portfolio_quant([], technicals={}, market={}, account={})
    assert q == {"available": False}


def test_portfolio_concentration_uses_snapshot_when_stale():
    rows = [
        _row("NVDA", 300.0, 3000.0, 10, 100.0, 200.0),
        _row("XYZ", None, None, 10, 50.0, None),
    ]
    conc = portfolio_quant.portfolio_concentration(rows, {"equity_value": 8000.0})
    assert conc["available"] is True
    assert conc["total_value"] == 8000.0
