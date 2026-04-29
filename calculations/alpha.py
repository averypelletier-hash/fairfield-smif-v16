"""
alpha.py
========
YTD alpha = Portfolio YTD return − Benchmark YTD return

This module wires together portfolio.py and benchmark.py to produce
the single alpha number shown on the Overview page KPI card.

To change any part of how alpha is calculated:
  - Benchmark composition  → edit benchmark.py (BENCHMARK_WEIGHTS / BENCHMARK_FETCH)
  - Portfolio YTD method   → edit portfolio.py (calc_portfolio_ytd)
  - Which tickers excluded → edit utils.py (PERF_EXCLUDE)
"""

import datetime
import yfinance as yf
from .utils import clean, PERF_EXCLUDE
from .benchmark import (
    BENCHMARK_FETCH,
    BENCHMARK_WEIGHTS,
    BENCHMARK_LABEL,
    fetch_benchmark_current_prices,
    fetch_benchmark_ytd_start_prices,
    calc_benchmark_ytd,
)
from .portfolio import calc_portfolio_ytd


def calc_alpha_ytd(holdings):
    """
    Calculate YTD alpha for the portfolio vs the 80/20 benchmark.

    Steps:
      1. Fetch current prices for benchmark tickers (^RUA, AGG).
      2. Fetch Jan 1 prices for benchmark tickers.
      3. Calculate benchmark YTD return.
      4. Fetch current + Jan 1 prices for all qualifying holdings.
      5. Calculate value-weighted portfolio YTD return.
      6. Alpha = portfolio YTD - benchmark YTD.

    Args:
        holdings — list of holding dicts from holdings.json

    Returns full result dict ready to be JSON-serialized by the Flask endpoint.
    """
    print("\n  [alpha] Fetching benchmark prices…")
    bench_current = fetch_benchmark_current_prices()
    bench_ytd_start = fetch_benchmark_ytd_start_prices()
    bench_ytd, bench_parts = calc_benchmark_ytd(bench_current, bench_ytd_start)

    print("  [alpha] Fetching portfolio YTD…")
    port_result = calc_portfolio_ytd(holdings)
    port_ytd    = port_result["portfolioYTD"]

    alpha_val = None
    if port_ytd is not None and bench_ytd is not None:
        alpha_val = round(port_ytd - bench_ytd, 4)

    print(f"  [alpha] portfolioYTD={port_ytd}  "
          f"benchmarkYTD={bench_ytd}  alpha={alpha_val}\n")

    return {
        "asOf":            datetime.date.today().isoformat(),
        "ytdYear":         datetime.date.today().year,
        "portfolioYTD":    port_ytd,
        "benchmarkYTD":    bench_ytd,
        "alpha":           alpha_val,
        "benchmarkLabel":  BENCHMARK_LABEL,
        "benchmarkParts":  bench_parts,
        "holdingDetails":  port_result["holdingDetails"],
        "excluded":        port_result["excluded"],
    }
