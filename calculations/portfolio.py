"""
portfolio.py
============
Portfolio-level calculations: current value, cost basis P&L, and YTD return.

All math is here. To change how portfolio return is calculated, edit this file.
"""

import yfinance as yf
from .utils import clean, PERF_EXCLUDE, get_ytd_start_price


def calc_portfolio_value(holdings, market_data):
    """
    Calculate total current market value and total cost basis.

    Args:
        holdings    — list of holding dicts { ticker, shares, cost_basis, sector }
        market_data — dict of { TICKER: { price, ... } } from market-data endpoint

    Returns:
        total_value  — sum of (current_price × shares) for all holdings
        total_cost   — sum of (cost_basis × shares) for all holdings
        pnl          — total_value - total_cost
        pnl_pct      — pnl / total_cost × 100
    """
    total_value = 0.0
    total_cost  = 0.0

    for h in holdings:
        ticker = h["ticker"].upper()
        price  = market_data.get(ticker, {}).get("price")
        cost   = h["cost_basis"]
        shares = h["shares"]

        if price is not None:
            total_value += price * shares
        total_cost += cost * shares

    pnl     = total_value - total_cost
    pnl_pct = (pnl / total_cost * 100) if total_cost else 0.0

    return {
        "totalValue": round(total_value, 2),
        "totalCost":  round(total_cost, 2),
        "pnl":        round(pnl, 2),
        "pnlPct":     round(pnl_pct, 4),
    }


def calc_portfolio_ytd(holdings, current_prices=None):
    """
    Calculate the value-weighted YTD return of the portfolio.

    Method:
      1. For each qualifying holding, fetch price on Jan 1 and current price.
      2. YTD return per holding = (current - jan1) / jan1 × 100
      3. Weight each holding by its current market value as % of total portfolio.
      4. Portfolio YTD = Σ (holding_ytd × holding_weight)

    Tickers in PERF_EXCLUDE are skipped (unreliable pricing data).

    Args:
        holdings       — list of holding dicts
        current_prices — optional pre-fetched { ticker: price } dict.
                         If None, prices will be fetched from yFinance.

    Returns dict with:
        portfolioYTD  — weighted YTD % (float or None)
        holdingDetails — per-holding breakdown for transparency
        excluded       — list of tickers skipped
    """
    qualifying = [h for h in holdings
                  if h["ticker"].upper() not in PERF_EXCLUDE]
    excluded   = list(PERF_EXCLUDE & {h["ticker"].upper() for h in holdings})

    # Fetch current prices if not provided
    if current_prices is None:
        current_prices = {}
        for h in qualifying:
            sym = h["ticker"].upper()
            if sym not in current_prices:
                try:
                    info = yf.Ticker(sym).info or {}
                    p = clean(
                        info.get("currentPrice")
                        or info.get("regularMarketPrice")
                        or info.get("navPrice")
                        or info.get("previousClose")
                    )
                    current_prices[sym] = p
                except Exception:
                    current_prices[sym] = None

    # Fetch Jan 1 prices
    ytd_start = {}
    for h in qualifying:
        sym = h["ticker"].upper()
        if sym not in ytd_start:
            ytd_start[sym] = get_ytd_start_price(sym)

    # Total portfolio value (for weighting)
    total_value = sum(
        (current_prices.get(h["ticker"].upper()) or 0) * h["shares"]
        for h in qualifying
        if current_prices.get(h["ticker"].upper()) is not None
    )

    holding_details = []
    weighted_sum    = 0.0

    for h in qualifying:
        sym    = h["ticker"].upper()
        c      = current_prices.get(sym)
        s      = ytd_start.get(sym)

        if c and s and s != 0 and total_value > 0:
            ret    = (c - s) / s * 100
            weight = (c * h["shares"]) / total_value
            weighted_sum += ret * weight
            holding_details.append({
                "ticker":        sym,
                "sector":        h.get("sector", ""),
                "shares":        h["shares"],
                "currentPrice":  round(c, 4),
                "ytdStartPrice": round(s, 4),
                "ytdReturn":     round(ret, 4),
                "weight":        round(weight * 100, 4),
            })
        else:
            holding_details.append({
                "ticker":        sym,
                "sector":        h.get("sector", ""),
                "shares":        h["shares"],
                "currentPrice":  c,
                "ytdStartPrice": s,
                "ytdReturn":     None,
                "weight":        None,
            })

    port_ytd = round(weighted_sum, 4) if total_value > 0 else None

    return {
        "portfolioYTD":   port_ytd,
        "holdingDetails": holding_details,
        "excluded":       excluded,
    }
