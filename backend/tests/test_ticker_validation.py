"""Tests for ticker validation/repair (hermetic — universe is monkeypatched)."""

import pytest

from app import ticker_validation


@pytest.fixture(autouse=True)
def _fixed_universe(monkeypatch):
    universe = frozenset({"AAPL", "NVDA", "CRWD", "MSFT", "PLTR"})
    monkeypatch.setattr(ticker_validation, "_universe", lambda: universe)


def test_corrects_hallucinated_dollar_ticker():
    out, corrections = ticker_validation.validate_content_tickers("Buy $CRWDS now")
    assert "$CRWD" in out
    assert ("CRWDS", "CRWD") in corrections


def test_leaves_valid_ticker_untouched():
    out, corrections = ticker_validation.validate_content_tickers("Buy $NVDA now")
    assert out == "Buy $NVDA now"
    assert corrections == []


def test_never_rewrites_acronym_in_parens():
    text = "The (CEO) said (GDP) growth is strong."
    out, corrections = ticker_validation.validate_content_tickers(text)
    assert out == text
    assert corrections == []


def test_holdings_extend_valid_set():
    out, corrections = ticker_validation.validate_content_tickers(
        "Adding $TSLAX", holdings=["TSLA"]
    )
    assert "$TSLA" in out
    assert ("TSLAX", "TSLA") in corrections


def test_validate_meta_drops_invalid_and_fixes():
    meta = {
        "actions": [{"tickers": ["NVDA", "CRWDS", "ZZZZZZ"]}],
        "watchlist_adds": [{"ticker": "AAPLX"}, {"ticker": "MSFT"}],
    }
    out = ticker_validation.validate_meta_tickers(meta)
    assert out["actions"][0]["tickers"] == ["NVDA", "CRWD"]
    adds = [a["ticker"] for a in out["watchlist_adds"]]
    assert adds == ["AAPL", "MSFT"]
