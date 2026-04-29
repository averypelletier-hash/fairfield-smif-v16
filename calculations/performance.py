"""
performance.py
==============
5-trading-day portfolio performance vs the blended benchmark.

How it works:
  - Fetches 10 days of daily closes for every qualifying holding + benchmarks.
  - "5 days ago" price = closes[-6]  (6th from the end gives 5 complete trading days)
  - "Today" price      = closes[-1]  (most recent close)
  - Portfolio 5d return = (today_value - ago_value) / ago_value × 100
  - Benchmark 5d return = RUA_5d × 0.80 + AGG_5d × 0.20

Tickers in PERF_EXCLUDE are skipped entirely from the portfolio calculation.
They still show on their sector tabs — only the 5-day return card is affected.
"""

import yfinance as yf
from .utils import clean, PERF_EXCLUDE
from .benchmark import BENCHMARK_FETCH, BENCHMARK_WEIGHTS


def calc_5d_performance(holdings):
    """
    Calculate 5-day portfolio return vs blended benchmark return.

    Args:
        holdings — list of holding dicts { ticker, shares, cost_basis, sector }

    Returns dict with:
        portfolioReturn5d  — portfolio 5-day % (float or None)
        benchmarkReturn5d  — benchmark 5-day % (float or None)
        alpha5d            — portfolio minus benchmark (float or None)
        portfolioValueAgo  — portfolio value 5 trading days ago
        portfolioValueNow  — portfolio value today
        benchmarkParts     — per-component benchmark breakdown
        included           — tickers successfully included in portfolio calc
        excluded           — tickers skipped
        sparklines         — { TICKER: [6 daily closes] } for chart rendering
    """
    qualifying = [h for h in holdings
                  if h["ticker"].upper() not in PERF_EXCLUDE]
    excluded   = list(PERF_EXCLUDE & {h["ticker"].upper() for h in holdings})

    # All symbols we need prices for
    holding_syms  = list({h["ticker"].upper() for h in qualifying})
    benchmark_syms = list(BENCHMARK_FETCH.keys())   # clean keys: ["RUA", "AGG"]

    # ── Fetch 10-day history for everything ───────────────────────────────────
    prices_ago = {}   # price 5 trading days ago
    prices_now = {}   # most recent close
    sparklines  = {}  # last 6 closes for sparkline rendering

    print("\n  [performance] Fetching 10-day history…")

    # Benchmark tickers (fetch via yFinance symbol, store under clean key)
    for clean_key, yf_sym in BENCHMARK_FETCH.items():
        try:
            hist   = yf.Ticker(yf_sym).history(period="10d", interval="1d")
            closes = hist["Close"].dropna().tolist()
            if len(closes) >= 6:
                prices_ago[clean_key] = clean(closes[-6])
                prices_now[clean_key] = clean(closes[-1])
                sparklines[clean_key] = [round(c, 4) for c in closes[-6:]]
                print(f"    {clean_key} ({yf_sym}): "
                      f"ago={prices_ago[clean_key]:.2f}  "
                      f"now={prices_now[clean_key]:.2f}")
            else:
                print(f"    {clean_key}: only {len(closes)} closes — skipping")
        except Exception as e:
            print(f"    {clean_key}: failed — {e}")

    # Holding tickers
    for sym in holding_syms:
        try:
            hist   = yf.Ticker(sym).history(period="10d", interval="1d")
            closes = hist["Close"].dropna().tolist()
            if len(closes) >= 6:
                prices_ago[sym] = clean(closes[-6])
                prices_now[sym] = clean(closes[-1])
                sparklines[sym] = [round(c, 4) for c in closes[-6:]]
                print(f"    {sym}: ago={prices_ago[sym]:.2f}  now={prices_now[sym]:.2f}")
            else:
                print(f"    {sym}: only {len(closes)} closes — skipping")
        except Exception as e:
            print(f"    {sym}: failed — {e}")

    # ── Portfolio 5-day return ────────────────────────────────────────────────
    port_val_ago = 0.0
    port_val_now = 0.0
    included     = []

    for h in qualifying:
        sym = h["ticker"].upper()
        ago = prices_ago.get(sym)
        now = prices_now.get(sym)
        if ago and now and ago > 0:
            port_val_ago += ago * h["shares"]
            port_val_now += now * h["shares"]
            included.append(sym)
        else:
            excluded.append(sym)

    port_5d = None
    if port_val_ago > 0:
        port_5d = round((port_val_now - port_val_ago) / port_val_ago * 100, 4)

    # ── Benchmark 5-day return ────────────────────────────────────────────────
    bench_5d    = None
    bench_parts = {}
    bench_ok    = True

    for clean_key, w in BENCHMARK_WEIGHTS.items():
        ago = prices_ago.get(clean_key)
        now = prices_now.get(clean_key)
        if ago and now and ago > 0:
            ret = (now - ago) / ago * 100
            bench_parts[clean_key] = {
                "yfSymbol":  BENCHMARK_FETCH[clean_key],
                "priceAgo":  ago,
                "priceNow":  now,
                "return5d":  round(ret, 4),
                "weight":    w,
            }
        else:
            bench_ok = False
            bench_parts[clean_key] = {
                "yfSymbol":  BENCHMARK_FETCH[clean_key],
                "priceAgo":  ago,
                "priceNow":  now,
                "return5d":  None,
                "weight":    w,
            }

    if bench_ok:
        bench_5d = round(
            sum(bench_parts[k]["return5d"] * w
                for k, w in BENCHMARK_WEIGHTS.items()),
            4
        )

    alpha_5d = None
    if port_5d is not None and bench_5d is not None:
        alpha_5d = round(port_5d - bench_5d, 4)

    print(f"  [performance] port_5d={port_5d}  bench_5d={bench_5d}  "
          f"alpha_5d={alpha_5d}")
    print(f"    included={len(included)} tickers, "
          f"excluded={excluded or 'none'}\n")

    return {
        "portfolioReturn5d": port_5d,
        "benchmarkReturn5d": bench_5d,
        "alpha5d":           alpha_5d,
        "portfolioValueAgo": round(port_val_ago, 2),
        "portfolioValueNow": round(port_val_now, 2),
        "benchmarkParts":    bench_parts,
        "included":          included,
        "excluded":          excluded,
        "sparklines":        sparklines,
    }
