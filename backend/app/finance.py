from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf
from financetoolkit import Toolkit

from app.config import settings
from app.mock_data import (
    mock_market_snapshot,
    mock_portfolio_metrics,
    mock_quotes,
    mock_screen_candidates,
)

_METRICS_LOCK = threading.Lock()
_METRICS_MEMORY: dict[str, dict[str, Any]] = {}
# Fundamentals (2023+ ratios, cumulative return, volatility) are historical — cache until
# force_refresh or first fetch for a new ticker. fetched_at is debug-only, not TTL.
_TECH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
# Technicals embed the latest close/RSI/MA — refresh every 15m during market hours.
_TECH_TTL_SECONDS = 900
_WARM_STATE: dict[str, Any] = {
    "running": False,
    "done": False,
    "progress": 0,
    "message": "Not started",
    "tickers": [],
}


def _metrics_cache_path() -> Path:
    root = Path(__file__).resolve().parent.parent / "data" / "finance_cache"
    root.mkdir(parents=True, exist_ok=True)
    return root / "metrics.json"


def _load_metrics_disk() -> dict[str, Any]:
    path = _metrics_cache_path()
    if not path.exists():
        return {"tickers": {}}
    try:
        data = json.loads(path.read_text())
        data.setdefault("tickers", {})
        return data
    except Exception:
        return {"tickers": {}}


def _save_metrics_disk(data: dict[str, Any]) -> None:
    try:
        _metrics_cache_path().write_text(json.dumps(data, default=str))
    except Exception:
        pass


def _metrics_cached(entry: dict[str, Any] | None) -> bool:
    return bool(entry and entry.get("metrics"))


def _get_cached_ticker_metrics(ticker: str, *, force_refresh: bool = False) -> dict[str, Any] | None:
    if force_refresh:
        return None
    ticker = ticker.upper()
    with _METRICS_LOCK:
        mem = _METRICS_MEMORY.get(ticker)
        if mem and _metrics_cached(mem):
            return mem["metrics"]
    disk = _load_metrics_disk()
    entry = disk.get("tickers", {}).get(ticker)
    if _metrics_cached(entry):
        with _METRICS_LOCK:
            _METRICS_MEMORY[ticker] = entry
        return entry["metrics"]
    return None


def _store_ticker_metrics(ticker: str, metrics: dict[str, Any]) -> None:
    ticker = ticker.upper()
    entry = {"fetched_at": time.time(), "metrics": metrics}
    with _METRICS_LOCK:
        _METRICS_MEMORY[ticker] = entry
        disk = _load_metrics_disk()
        disk.setdefault("tickers", {})[ticker] = entry
        _save_metrics_disk(disk)


def _toolkit(tickers: list[str]) -> Toolkit | None:
    kwargs: dict[str, Any] = {
        "tickers": tickers,
        "start_date": "2023-01-01",
    }
    if settings.fmp_api_key:
        kwargs["api_key"] = settings.fmp_api_key
    try:
        return Toolkit(**kwargs)
    except Exception:
        return None


def get_quotes(tickers: list[str]) -> dict[str, dict[str, float | str | None]]:
    """Live quotes — intentionally uncached (intraday prices change continuously)."""
    if settings.mock_mode:
        return mock_quotes(tickers)
    if not tickers:
        return {}
    result: dict[str, dict[str, float | str | None]] = {}
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}
            hist = t.history(period="5d")
            prev_close = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else None
            last = float(hist["Close"].iloc[-1]) if len(hist) >= 1 else None
            change_pct = ((last - prev_close) / prev_close * 100) if last and prev_close else None
            result[ticker] = {
                "name": info.get("shortName") or info.get("longName") or ticker,
                "price": last,
                "prev_close": prev_close,
                "change_pct": round(change_pct, 2) if change_pct is not None else None,
                "sector": info.get("sector"),
                "industry": info.get("industry"),
            }
        except Exception:
            result[ticker] = {
                "name": ticker,
                "price": None,
                "prev_close": None,
                "change_pct": None,
                "sector": None,
                "industry": None,
            }
    return result


def _latest_metric_row(df: pd.DataFrame | None, ticker: str) -> dict[str, Any]:
    if df is None or df.empty:
        return {}
    try:
        if isinstance(df.index, pd.MultiIndex):
            sub = df.xs(ticker, level=0)
        else:
            sub = df
        col = sub.columns[-1]
        out: dict[str, Any] = {}
        for idx, val in sub[col].items():
            if pd.isna(val):
                continue
            try:
                out[str(idx)] = round(float(val), 4)
            except (TypeError, ValueError):
                out[str(idx)] = val
        return out
    except Exception:
        return {}


def _latest_scalar(df: pd.DataFrame | None, ticker: str) -> float | None:
    if df is None or df.empty:
        return None
    try:
        if isinstance(df.index, pd.MultiIndex):
            sub = df.xs(ticker, level=0)
        else:
            sub = df
        val = sub.iloc[-1, -1]
        return round(float(val), 4) if pd.notna(val) else None
    except Exception:
        return None


def _fetch_ticker_fundamentals(ticker: str) -> dict[str, Any]:
    tk = _toolkit([ticker])
    if tk is None:
        return {"profitability": {}, "valuation": {}, "cumulative_return": None, "volatility": None}
    out: dict[str, Any] = {
        "profitability": {},
        "valuation": {},
        "cumulative_return": None,
        "volatility": None,
    }
    try:
        prof = tk.ratios.collect_profitability_ratios()
        val = tk.ratios.collect_valuation_ratios()
        out["profitability"] = _latest_metric_row(prof, ticker)
        out["valuation"] = _latest_metric_row(val, ticker)
    except Exception as e:
        out["error"] = str(e)
    try:
        perf = tk.performance.get_cumulative_returns(period="daily")
        out["cumulative_return"] = _latest_scalar(perf, ticker)
    except Exception:
        pass
    try:
        vol = tk.risk.get_volatility(period="weekly")
        out["volatility"] = _latest_scalar(vol, ticker)
    except Exception:
        pass
    return out


def _assemble_portfolio_metrics(by_ticker: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not by_ticker:
        return {"ratios": {}, "performance": {}, "risk": {}}
    return {
        "ratios": {
            "profitability": {t: d.get("profitability") or {} for t, d in by_ticker.items()},
            "valuation": {t: d.get("valuation") or {} for t, d in by_ticker.items()},
        },
        "performance": {
            "cumulative_returns": {t: d.get("cumulative_return") for t, d in by_ticker.items()},
        },
        "risk": {
            "volatility": {t: d.get("volatility") for t, d in by_ticker.items()},
        },
    }


def finance_warm_status() -> dict[str, Any]:
    return dict(_WARM_STATE)


def warm_finance_cache(
    tickers: list[str],
    *,
    blocking: bool = False,
    force_refresh: bool = False,
) -> None:
    """Prefetch FinanceToolkit metrics + technicals for holdings (persistent fundamentals cache)."""
    tickers = sorted({t.upper() for t in tickers if t})
    if not tickers or settings.mock_mode:
        return

    def _run() -> None:
        _WARM_STATE.update(
            running=True,
            done=False,
            progress=0,
            message="Warming finance cache…",
            tickers=tickers,
        )
        try:
            n = len(tickers)
            for i, ticker in enumerate(tickers):
                cached = _get_cached_ticker_metrics(ticker, force_refresh=force_refresh)
                if not cached:
                    _store_ticker_metrics(ticker, _fetch_ticker_fundamentals(ticker))
                get_technicals(ticker, force_refresh=force_refresh)
                _WARM_STATE.update(
                    progress=int((i + 1) / n * 100),
                    message=f"Cached fundamentals for {ticker} ({i + 1}/{n})",
                )
            portfolio_metrics(tickers, force_refresh=force_refresh)
            portfolio_technicals(tickers, force_refresh=force_refresh)
            _WARM_STATE.update(running=False, done=True, progress=100, message="Finance cache ready")
        except Exception as e:
            _WARM_STATE.update(running=False, done=True, progress=100, message=f"Finance warm warning: {e}")

    if blocking:
        _run()
    else:
        threading.Thread(target=_run, daemon=True, name="finance-warm").start()


def get_market_snapshot() -> dict[str, Any]:
    if settings.mock_mode:
        return mock_market_snapshot()
    indices = ["^GSPC", "^IXIC", "^DJI", "^VIX"]
    quotes = get_quotes(indices)
    labels = {
        "^GSPC": "S&P 500",
        "^IXIC": "Nasdaq",
        "^DJI": "Dow Jones",
        "^VIX": "VIX",
    }
    return {
        labels.get(k, k): v for k, v in quotes.items()
    }


def portfolio_metrics(tickers: list[str], *, force_refresh: bool = False) -> dict[str, Any]:
    if settings.mock_mode:
        return mock_portfolio_metrics(tickers)
    if not tickers:
        return {"ratios": {}, "performance": {}, "risk": {}}

    unique = list(dict.fromkeys(t.upper() for t in tickers[:24]))
    by_ticker: dict[str, dict[str, Any]] = {}
    missing: list[str] = []

    for ticker in unique:
        cached = _get_cached_ticker_metrics(ticker, force_refresh=force_refresh)
        if cached:
            by_ticker[ticker] = cached
        else:
            missing.append(ticker)

    for ticker in missing:
        by_ticker[ticker] = _fetch_ticker_fundamentals(ticker)
        _store_ticker_metrics(ticker, by_ticker[ticker])

    return _assemble_portfolio_metrics(by_ticker)


def screen_candidates(tickers: list[str], max_market_cap: float | None = None) -> list[dict[str, Any]]:
    """Score a universe of tickers for top-picks screening."""
    if settings.mock_mode:
        return mock_screen_candidates(tickers)
    quotes = get_quotes(tickers)
    scored: list[dict[str, Any]] = []
    for ticker in tickers:
        q = quotes.get(ticker, {})
        change = q.get("change_pct")
        price = q.get("price")
        if price is None:
            continue
        market_cap = None
        if max_market_cap is not None:
            try:
                info = yf.Ticker(ticker).info or {}
                market_cap = info.get("marketCap")
                if market_cap is None or market_cap > max_market_cap:
                    continue
            except Exception:
                continue
        momentum = change if change is not None else 0
        scored.append({
            "ticker": ticker,
            "name": q.get("name", ticker),
            "price": price,
            "change_pct": change,
            "sector": q.get("sector"),
            "market_cap": market_cap,
            "score": round(momentum, 2),
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def market_peers(sector_query: str, sample_tickers: list[str] | None = None) -> dict[str, Any]:
    tickers = sample_tickers or _default_universe_for_market(sector_query)
    quotes = get_quotes(tickers)
    metrics = portfolio_metrics(tickers[:8])
    return {
        "query": sector_query,
        "tickers": tickers,
        "quotes": quotes,
        "metrics": metrics,
    }


def _default_universe_for_market(query: str) -> list[str]:
    q = query.lower()
    mapping = {
        "semiconductor": ["NVDA", "AMD", "INTC", "AVGO", "QCOM", "TSM", "ASML", "MU"],
        "ai": ["NVDA", "MSFT", "GOOGL", "META", "AMZN", "PLTR", "CRM", "SNOW"],
        "tech": ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "NVDA", "CRM", "ORCL"],
        "energy": ["XOM", "CVX", "COP", "SLB", "EOG", "OXY", "MPC", "VLO"],
        "health": ["UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT"],
        "finance": ["JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "V"],
        "consumer": ["AMZN", "WMT", "COST", "HD", "MCD", "NKE", "SBUX", "TGT"],
        "ev": ["TSLA", "RIVN", "LCID", "NIO", "LI", "GM", "F", "BYD"],
    }
    for key, tickers in mapping.items():
        if key in q:
            return tickers
    return ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B"]


def get_technicals(ticker: str, *, force_refresh: bool = False) -> dict[str, Any]:
    if settings.mock_mode:
        return {"ma20": None, "ma50": None, "rsi14": None, "high_52w": None, "low_52w": None}
    ticker = ticker.upper()
    cached = _TECH_CACHE.get(ticker)
    if not force_refresh and cached and (time.time() - cached[0]) < _TECH_TTL_SECONDS:
        return cached[1]
    try:
        hist = yf.Ticker(ticker).history(period="1y")
        if hist is None or hist.empty:
            return {}
        close = hist["Close"]
        last = float(close.iloc[-1])
        ma20 = float(close.tail(20).mean()) if len(close) >= 20 else None
        ma50 = float(close.tail(50).mean()) if len(close) >= 50 else None
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, pd.NA)
        rsi = 100 - (100 / (1 + rs))
        rsi14 = float(rsi.iloc[-1]) if len(rsi.dropna()) else None
        result = {
            "price": round(last, 2),
            "ma20": round(ma20, 2) if ma20 else None,
            "ma50": round(ma50, 2) if ma50 else None,
            "rsi14": round(rsi14, 1) if rsi14 is not None else None,
            "high_52w": round(float(close.max()), 2),
            "low_52w": round(float(close.min()), 2),
            "above_ma20": ma20 and last > ma20,
            "above_ma50": ma50 and last > ma50,
        }
        _TECH_CACHE[ticker] = (time.time(), result)
        return result
    except Exception:
        return {}


def portfolio_technicals(tickers: list[str], *, force_refresh: bool = False) -> dict[str, dict[str, Any]]:
    if not tickers:
        return {}
    from concurrent.futures import ThreadPoolExecutor, as_completed
    out: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(tickers))) as pool:
        futs = {pool.submit(get_technicals, t, force_refresh=force_refresh): t for t in tickers}
        for fut in as_completed(futs):
            ticker = futs[fut]
            try:
                out[ticker] = fut.result()
            except Exception:
                out[ticker] = {}
    return out
