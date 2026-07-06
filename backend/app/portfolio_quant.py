"""Server-side quant analytics for the portfolio tab.

Everything a desk needs *computed in code* (not free-formed by the LLM):
- portfolio aggregates (total value, weights, sector weights, HHI) so the
  narrated totals always reconcile to the listed positions;
- factor decomposition per name: market beta (vs SPY), sector beta + residual
  alpha + Information Ratio (vs the relevant sector ETF) so "alpha" is only
  claimed when residual survives removing sector beta;
- a correlation matrix + an "effective number of bets" metric (by name and by
  factor) so N same-sector momentum calls can't be sold as N independent ideas;
- ATR/volatility-scaled stops (+ a time stop) instead of one flat MA/RSI stop;
- transaction-cost / tax sensitivity hints (large winners in taxable accounts);
- a per-name sector template so the prompt routes each holding to the right
  signal set (rates for financials, catalysts for biotech, etc.).

All network work is TTL-cached and best-effort — a fetch failure degrades a
single field, never the whole analysis.
"""

from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

# --- Sector templates -> benchmark ETF for beta/residual/IR -------------------
# Keep the benchmark tight to the dominant risk factor of each template so the
# residual is a real "vs sector" number, not vs the broad market.
SECTOR_BENCHMARKS: dict[str, str] = {
    "semis": "SMH",
    "memory": "SMH",
    "ai_infra": "SMH",
    "software_ai": "IGV",
    "megacap_quality": "XLK",
    "financials": "XLF",
    "mobility_consumer": "XLY",
    "space_thematic": "ARKX",
    "biotech": "XBI",
    "energy": "XLE",
    "broad": "SPY",
}
MARKET_BENCHMARK = "SPY"

# Curated map for the names most likely to be held; falls back to yfinance
# sector/industry classification, then "broad".
_TICKER_TEMPLATE: dict[str, str] = {
    "NVDA": "semis", "AMD": "semis", "MRVL": "semis", "TSM": "semis",
    "NVTS": "semis", "AIP": "semis", "AVGO": "semis", "INTC": "semis",
    "QCOM": "semis", "ASML": "semis", "SMCI": "semis", "ARM": "semis",
    "MU": "memory", "WDC": "memory", "STX": "memory",
    "VRT": "ai_infra", "SMR": "ai_infra", "GEV": "ai_infra",
    "GOOG": "megacap_quality", "GOOGL": "megacap_quality", "AAPL": "megacap_quality",
    "MSFT": "megacap_quality", "META": "megacap_quality", "AMZN": "megacap_quality",
    "PLTR": "software_ai", "CRM": "software_ai", "SNOW": "software_ai",
    "NOW": "software_ai", "ORCL": "software_ai", "DDOG": "software_ai",
    "SOFI": "financials", "JPM": "financials", "BAC": "financials",
    "GS": "financials", "MS": "financials", "SCHW": "financials", "COIN": "financials",
    "UBER": "mobility_consumer", "LYFT": "mobility_consumer", "ABNB": "mobility_consumer",
    "TSLA": "mobility_consumer", "AMZN.": "mobility_consumer",
    "SPCX": "space_thematic", "RKLB": "space_thematic", "LUNR": "space_thematic",
    "XOM": "energy", "CVX": "energy", "COP": "energy", "SLB": "energy",
    "MRNA": "biotech", "VRTX": "biotech", "BIIB": "biotech", "AMGN": "biotech",
}

# Sector-specific signal guides handed to the quant persona so it stops applying
# one MA/RSI template to every name.
SECTOR_SIGNAL_GUIDES: dict[str, str] = {
    "semis": "Momentum + AI-capex cycle; high beta (1.2-2.0). Use relative strength vs SMH/SOXX, earnings-revision breadth, HBM/book-to-bill. Treat as ONE factor for sizing; vol-scale stops.",
    "memory": "Commodity DRAM/NAND price cycle — deeply cyclical, mean-reverting on multiples. Weight valuation (P/FCF) and cycle position over pure price momentum; trims into strength are structurally right.",
    "ai_infra": "Data-center power/infra — a derivative of the SAME AI-capex factor as semis, NOT a diversifier. Watch order backlog/book-to-bill; bucket WITH semis for factor exposure.",
    "software_ai": "Growth-multiple duration: rate-sensitive multiple compression, net revenue retention, FCF margin, estimate revisions. Momentum works but duration risk dominates at rate turns.",
    "megacap_quality": "Quality grind — MA crosses are noise. Weight ROE, FCF, estimate revisions, reasonable multiple. Low active risk; buyable on weakness, not chart-stopped.",
    "financials": "Rate/credit factor (NOT AI-capex): NIM, curve steepness, charge-offs, credit spreads, deposit beta, book value. RSI extremes read as rate-trade positioning, not chart signals.",
    "mobility_consumer": "Consumer-cyclical demand + take-rate + gig regulation; moderate beta. Trend signals OK but overlay idiosyncratic regulatory/event risk.",
    "space_thematic": "Venture-like, long-duration: technicals near-useless (thin history). Watch cash runway, financing/dilution risk, contract/program milestones. Size tiny; do NOT chart-stop.",
    "biotech": "Binary catalyst/event risk — technicals are actively misleading (40-80% gaps on readouts). Use catalyst calendar, probability-of-success, cash runway, implied move; position for the distribution, not MA stops.",
    "energy": "Commodity beta (oil/gas), mean-reverting > momentum. Watch crude curve, inventories, breakevens, backwardation. Different sign than semis — fade extremes.",
    "broad": "Diversified/other: use standard trend + valuation; treat as market-beta unless a clearer factor applies.",
}

_HIST_CACHE: dict[str, tuple[float, pd.DataFrame | None]] = {}
_HIST_TTL = 900  # 15 min — same cadence as technicals
_HIST_LOCK = threading.Lock()
_QUANT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_QUANT_TTL = 900


def classify_ticker(ticker: str, sector: str | None = None, industry: str | None = None) -> str:
    t = (ticker or "").upper()
    if t in _TICKER_TEMPLATE:
        return _TICKER_TEMPLATE[t]
    s = (sector or "").lower()
    ind = (industry or "").lower()
    if "semiconductor" in ind or "semiconductor" in s:
        return "semis"
    if "software" in ind or "software" in s:
        return "software_ai"
    if "bank" in ind or "financial" in s or "capital markets" in ind or "credit" in ind:
        return "financials"
    if "biotech" in ind or "drug" in ind or "pharmaceutical" in ind:
        return "biotech"
    if "oil" in ind or "gas" in ind or "energy" in s:
        return "energy"
    if "aerospace" in ind or "space" in ind:
        return "space_thematic"
    if s in ("consumer cyclical", "consumer discretionary"):
        return "mobility_consumer"
    if s in ("technology", "communication services"):
        return "megacap_quality"
    return "broad"


def _fetch_history(ticker: str) -> pd.DataFrame | None:
    now = time.time()
    with _HIST_LOCK:
        cached = _HIST_CACHE.get(ticker)
        if cached and (now - cached[0]) < _HIST_TTL:
            return cached[1]
    df: pd.DataFrame | None = None
    try:
        hist = yf.Ticker(ticker).history(period="1y")
        if hist is not None and not hist.empty:
            df = hist
    except Exception:
        df = None
    with _HIST_LOCK:
        _HIST_CACHE[ticker] = (now, df)
    return df


def _daily_returns(df: pd.DataFrame | None) -> pd.Series | None:
    if df is None or df.empty or "Close" not in df:
        return None
    close = df["Close"].dropna()
    if len(close) < 30:
        return None
    ret = close.pct_change().dropna()
    ret.index = [str(i.date()) if hasattr(i, "date") else str(i) for i in ret.index]
    return ret


def _atr(df: pd.DataFrame | None, period: int = 14) -> float | None:
    if df is None or df.empty or not {"High", "Low", "Close"}.issubset(df.columns):
        return None
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    return round(float(atr), 2) if pd.notna(atr) else None


def _beta_alpha(ri: pd.Series, rb: pd.Series) -> tuple[float | None, float | None, float | None]:
    """Return (beta, annualized residual alpha %, annualized Information Ratio)."""
    joined = pd.concat([ri, rb], axis=1, join="inner").dropna()
    if len(joined) < 30:
        return None, None, None
    a = joined.iloc[:, 0].to_numpy(dtype=float)
    b = joined.iloc[:, 1].to_numpy(dtype=float)
    var_b = float(np.var(b))
    if var_b <= 0:
        return None, None, None
    beta = float(np.cov(a, b, ddof=0)[0, 1] / var_b)
    resid = a - beta * b
    alpha_annual = float(np.mean(resid) * 252 * 100)
    active = a - b
    te = float(np.std(active, ddof=0))
    ir = float(np.mean(active) / te * math.sqrt(252)) if te > 0 else None
    return round(beta, 2), round(alpha_annual, 1), (round(ir, 2) if ir is not None else None)


def _effective_bets_by_factor(corr: pd.DataFrame) -> float | None:
    """Participation ratio of the correlation eigenvalues = effective # of factors."""
    try:
        vals = np.linalg.eigvalsh(corr.to_numpy(dtype=float))
        vals = np.clip(vals, 0, None)
        s = float(np.sum(vals))
        s2 = float(np.sum(vals ** 2))
        if s2 <= 0:
            return None
        return round((s * s) / s2, 2)
    except Exception:
        return None


def _regime(market: dict[str, Any] | None) -> dict[str, Any]:
    vix = None
    if market:
        vix_block = market.get("VIX") or {}
        if isinstance(vix_block, dict):
            vix = vix_block.get("price")
    label = "unknown"
    note = ""
    if isinstance(vix, (int, float)):
        if vix < 18:
            label = "low-vol / range"
            note = "Down-weight momentum-breakdown stops — whipsaw risk is elevated in a calm tape; require confirmation (multi-day close + volume) before acting."
        elif vix < 28:
            label = "normal"
            note = "Standard trend rules apply."
        else:
            label = "high-vol / stress"
            note = "Trend-following stops have higher precision; tail protection is worth more."
    return {"vix": vix, "label": label, "note": note}


def compute_portfolio_quant(
    portfolio_rows: list[dict[str, Any]],
    technicals: dict[str, dict[str, Any]] | None = None,
    market: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute the full quant analytics block for a set of holdings."""
    technicals = technicals or {}
    rows = [r for r in portfolio_rows if r.get("ticker")]
    if not rows:
        return {"available": False}

    cache_key = "|".join(sorted(f"{r['ticker']}:{round(r.get('value') or 0, 1)}" for r in rows))
    now = time.time()
    cached = _QUANT_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _QUANT_TTL:
        return cached[1]

    tickers = [r["ticker"].upper() for r in rows]
    templates = {
        r["ticker"].upper(): classify_ticker(
            r["ticker"], r.get("sector"), r.get("industry")
        )
        for r in rows
    }
    benchmarks = sorted({SECTOR_BENCHMARKS.get(t, "SPY") for t in templates.values()} | {MARKET_BENCHMARK})

    fetch_targets = list(dict.fromkeys(tickers + benchmarks))
    histories: dict[str, pd.DataFrame | None] = {}
    with ThreadPoolExecutor(max_workers=min(12, len(fetch_targets))) as pool:
        futs = {pool.submit(_fetch_history, t): t for t in fetch_targets}
        for fut in as_completed(futs):
            histories[futs[fut]] = fut.result()

    returns: dict[str, pd.Series] = {}
    for t in fetch_targets:
        r = _daily_returns(histories.get(t))
        if r is not None:
            returns[t] = r

    total_value = round(sum(float(r.get("value") or 0) for r in rows), 2)
    total_cost = round(sum(float(r.get("avg_cost") or 0) * float(r.get("shares") or 0) for r in rows), 2)

    per_ticker: dict[str, dict[str, Any]] = {}
    weighted_beta = 0.0
    for r in rows:
        t = r["ticker"].upper()
        value = float(r.get("value") or 0)
        weight = (value / total_value) if total_value else 0
        template = templates[t]
        bench = SECTOR_BENCHMARKS.get(template, "SPY")
        ri = returns.get(t)
        beta_mkt = beta_sec = resid_alpha = ir = None
        if ri is not None:
            if MARKET_BENCHMARK in returns:
                beta_mkt, _, _ = _beta_alpha(ri, returns[MARKET_BENCHMARK])
            if bench in returns:
                beta_sec, resid_alpha, ir = _beta_alpha(ri, returns[bench])
        if beta_mkt is not None:
            weighted_beta += weight * beta_mkt
        atr = _atr(histories.get(t))
        price = float(r.get("price") or 0)
        tech = technicals.get(t) or technicals.get(r["ticker"]) or {}
        atr_pct = round(atr / price * 100, 1) if atr and price else None
        # Vol-scaled protective stop: 2.5x ATR below price (wider for genuine
        # volatility instead of a flat MA/RSI level).
        atr_stop = round(price - 2.5 * atr, 2) if atr and price else None
        ret_pct = r.get("return_pct")
        large_winner = isinstance(ret_pct, (int, float)) and ret_pct >= 100
        per_ticker[t] = {
            "weight_pct": round(weight * 100, 1),
            "value": round(value, 2),
            "sector_template": template,
            "benchmark": bench,
            "beta_market": beta_mkt,
            "beta_sector": beta_sec,
            "residual_alpha_annual_pct": resid_alpha,
            "information_ratio": ir,
            "is_alpha": bool(ir is not None and ir > 0.3 and (resid_alpha or 0) > 0),
            "atr14": atr,
            "atr_pct": atr_pct,
            "atr_stop_2_5x": atr_stop,
            "unrealized_return_pct": ret_pct,
            "tax_sensitive_winner": large_winner,
            "rsi14": tech.get("rsi14"),
            "signal_guide": SECTOR_SIGNAL_GUIDES.get(template, SECTOR_SIGNAL_GUIDES["broad"]),
        }

    # Sector-template weights (factor buckets, not GICS)
    sector_weights: dict[str, float] = {}
    for r in rows:
        t = r["ticker"].upper()
        sector_weights[templates[t]] = sector_weights.get(templates[t], 0.0) + float(r.get("value") or 0)
    sector_weights_pct = {
        k: round(v / total_value * 100, 1) for k, v in sorted(sector_weights.items(), key=lambda x: -x[1])
    } if total_value else {}

    weights = [(float(r.get("value") or 0) / total_value) for r in rows] if total_value else []
    hhi = round(sum(w * w for w in weights), 4) if weights else None
    eff_bets_name = round(1 / hhi, 1) if hhi else None

    # Correlation matrix + factor-effective bets across the holdings
    corr_tickers = [t for t in tickers if t in returns]
    correlation: dict[str, dict[str, float]] = {}
    eff_bets_factor = None
    if len(corr_tickers) >= 2:
        ret_df = pd.concat({t: returns[t] for t in corr_tickers}, axis=1, join="inner").dropna()
        if len(ret_df) >= 30 and ret_df.shape[1] >= 2:
            corr = ret_df.corr()
            eff_bets_factor = _effective_bets_by_factor(corr)
            correlation = {
                a: {b: round(float(corr.loc[a, b]), 2) for b in corr.columns}
                for a in corr.index
            }

    # Worst / most-broken position: rank by drawdown + technical stress.
    def _stress(r: dict[str, Any]) -> float:
        t = r["ticker"].upper()
        tech = technicals.get(t) or {}
        score = 0.0
        rp = r.get("return_pct")
        if isinstance(rp, (int, float)):
            score += max(0.0, -rp)  # deeper loss = higher stress
        rsi = tech.get("rsi14")
        if isinstance(rsi, (int, float)) and rsi < 35:
            score += (35 - rsi)
        if tech.get("above_ma50") is False:
            score += 15
        if tech.get("above_ma20") is False:
            score += 8
        return score

    ranked_stress = sorted(rows, key=_stress, reverse=True)
    worst = ranked_stress[0] if ranked_stress else None
    worst_drawdown = None
    if worst and _stress(worst) > 0:
        worst_drawdown = {
            "ticker": worst["ticker"].upper(),
            "return_pct": worst.get("return_pct"),
            "weight_pct": per_ticker.get(worst["ticker"].upper(), {}).get("weight_pct"),
            "note": "Most-broken / worst-drawdown position — at least one quant action MUST address it.",
        }

    distinct_factors = sorted(set(templates.values()))
    result = {
        "available": True,
        "aggregates": {
            "total_value": total_value,
            "total_cost": total_cost,
            "return_pct": round((total_value - total_cost) / total_cost * 100, 2) if total_cost else 0,
            "position_count": len(rows),
            "hhi": hhi,
            "effective_bets_by_name": eff_bets_name,
            "effective_bets_by_factor": eff_bets_factor,
            "weighted_market_beta": round(weighted_beta, 2),
            "sector_template_weights_pct": sector_weights_pct,
            "distinct_factors": distinct_factors,
            "distinct_factor_count": len(distinct_factors),
        },
        "regime": _regime(market),
        "per_ticker": per_ticker,
        "correlation_matrix": correlation,
        "worst_drawdown": worst_drawdown,
        "methodology_note": (
            "beta_market vs SPY; beta_sector/residual_alpha/information_ratio vs the named sector ETF. "
            "Only frame a name as alpha when information_ratio > 0.3 AND residual_alpha_annual_pct > 0 "
            "(is_alpha=true). effective_bets_by_factor is the participation ratio of the correlation "
            "eigenvalues — if it is far below position_count, the book is one factor sliced by name."
        ),
    }
    _QUANT_CACHE[cache_key] = (now, result)
    return result
