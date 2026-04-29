"""
benchmark.py
============
All benchmark calculation logic for the Fairfield SMIF dashboard.

Benchmark composition:
  80% Russell 3000  →  fetched as ^RUA from Yahoo Finance
  20% US Aggregate  →  fetched as AGG from Yahoo Finance

To change the benchmark, edit BENCHMARK_WEIGHTS and BENCHMARK_FETCH below.
"""

import yfinance as yf
import datetime
from .utils import clean, get_history, get_ytd_start_price

# ─── Configuration ────────────────────────────────────────────────────────────

# Maps clean display key → Yahoo Finance fetch symbol
# ^RUA is the proper Yahoo Finance symbol for the Russell 3000 index
BENCHMARK_FETCH = {
    "RUA": "^RUA",
    "AGG": "AGG",
}

# Portfolio weights for the blended benchmark (must sum to 1.0)
BENCHMARK_WEIGHTS = {
    "RUA": 0.80,
    "AGG": 0.20,
}

BENCHMARK_LABEL = "80/20 Russell 3000 (RUA) / US Agg (AGG)"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def fetch_benchmark_current_prices():
    """
    Fetch the current price for each benchmark ticker.
    Returns dict: { "RUA": price_or_None, "AGG": price_or_None }
    """
    prices = {}
    for clean_key, yf_sym in BENCHMARK_FETCH.items():
        try:
            info = yf.Ticker(yf_sym).info or {}
            p = clean(
                info.get("currentPrice")
                or info.get("regularMarketPrice")
                or info.get("navPrice")
                or info.get("previousClose")
            )
            prices[clean_key] = p
            print(f"    [benchmark] {clean_key} ({yf_sym}): current={p}")
        except Exception as e:
            print(f"    [benchmark] {clean_key} failed: {e}")
            prices[clean_key] = None
    return prices


def fetch_benchmark_ytd_start_prices():
    """
    Fetch the first available closing price on or after Jan 1 of this year
    for each benchmark ticker.
    Returns dict: { "RUA": price_or_None, "AGG": price_or_None }
    """
    prices = {}
    for clean_key, yf_sym in BENCHMARK_FETCH.items():
        p = get_ytd_start_price(yf_sym)
        prices[clean_key] = p
        print(f"    [benchmark] {clean_key}: ytd_start={p}")
    return prices


def fetch_benchmark_history(period="5d", interval="1d", points=6):
    """
    Fetch historical closes for each benchmark ticker.
    Returns dict: { "RUA": [prices...], "AGG": [prices...] }
    """
    history = {}
    for clean_key, yf_sym in BENCHMARK_FETCH.items():
        t = yf.Ticker(yf_sym)
        history[clean_key] = get_history(t, period, interval, points)
    return history


# ─── Benchmark calculations ───────────────────────────────────────────────────

def calc_benchmark_ytd(current_prices, ytd_start_prices):
    """
    Calculate the blended benchmark YTD return.

    Formula:
      Each component's YTD return = (current - start) / start * 100
      Blended return = Σ (component_return × component_weight)

    Returns:
      bench_ytd   — blended YTD % (float or None if data missing)
      bench_parts — per-component detail dict for transparency
    """
    bench_parts = {}
    bench_ok = True

    for sym, w in BENCHMARK_WEIGHTS.items():
        c = current_prices.get(sym)
        s = ytd_start_prices.get(sym)
        if c and s and s != 0:
            ret = (c - s) / s * 100
            bench_parts[sym] = {
                "yfSymbol":     BENCHMARK_FETCH[sym],
                "weight":       w,
                "currentPrice": round(c, 4),
                "ytdStartPrice":round(s, 4),
                "ytdReturn":    round(ret, 4),
            }
        else:
            bench_ok = False
            bench_parts[sym] = {
                "yfSymbol":     BENCHMARK_FETCH[sym],
                "weight":       w,
                "currentPrice": c,
                "ytdStartPrice":s,
                "ytdReturn":    None,
            }

    bench_ytd = None
    if bench_ok:
        bench_ytd = round(
            sum(bench_parts[sym]["ytdReturn"] * w
                for sym, w in BENCHMARK_WEIGHTS.items()),
            4
        )

    return bench_ytd, bench_parts


def calc_benchmark_5d(history):
    """
    Calculate the blended benchmark 5-day return from history data.

    Formula:
      Each component's 5d return = (last_close - first_close) / first_close * 100
      Blended return = Σ (component_return × component_weight)

    history: dict returned by fetch_benchmark_history()

    Returns:
      b5          — blended 5-day % (float or None)
      bench_norm  — list of 6 normalized % points for sparkline
    """
    component_returns = {}
    component_norms   = {}

    for sym, w in BENCHMARK_WEIGHTS.items():
        hist = history.get(sym) or []
        valid = [v for v in hist if v is not None]
        if len(valid) >= 2 and valid[0]:
            ret  = (valid[-1] - valid[0]) / valid[0] * 100
            norm = [((v - hist[0]) / hist[0]) * 100 if v is not None else None
                    for v in hist]
            component_returns[sym] = ret
            component_norms[sym]   = norm
        else:
            component_returns[sym] = None
            component_norms[sym]   = None

    # Blend only if both components have data
    rua_ret = component_returns.get("RUA")
    agg_ret = component_returns.get("AGG")
    b5 = None
    if rua_ret is not None and agg_ret is not None:
        b5 = round(rua_ret * BENCHMARK_WEIGHTS["RUA"] +
                   agg_ret * BENCHMARK_WEIGHTS["AGG"], 2)

    # Blended sparkline
    bench_norm = None
    rua_norm = component_norms.get("RUA")
    agg_norm = component_norms.get("AGG")
    if rua_norm and agg_norm and len(rua_norm) == len(agg_norm):
        bench_norm = []
        for rp, ap in zip(rua_norm, agg_norm):
            if rp is not None and ap is not None:
                bench_norm.append(
                    rp * BENCHMARK_WEIGHTS["RUA"] + ap * BENCHMARK_WEIGHTS["AGG"]
                )
            else:
                bench_norm.append(None)

    return b5, bench_norm
