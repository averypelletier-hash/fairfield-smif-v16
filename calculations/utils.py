"""
utils.py
========
Shared data-cleaning and yFinance helper functions used across all
calculation modules.
"""

import math
import yfinance as yf
import datetime


# ─── Tickers excluded from portfolio return calculations ─────────────────────
# These tickers have unreliable or no daily pricing from yFinance:
#   FFRHX  — floating rate mutual fund (NAV-priced, not exchange-traded)
#   SNVXX  — Schwab money market fund (always $1.00, no meaningful return)
#   FLIN   — Franklin FTSE India ETF (illiquid, spotty history data)
#
# They still appear on their sector tabs in the dashboard.
# To re-include a ticker, remove it from this set.
PERF_EXCLUDE = {"FFRHX", "SNVXX", "FLIN"}


def clean(value):
    """Convert NaN / Infinity to None so JSON serialization doesn't choke."""
    if value is None:
        return None
    try:
        if math.isnan(float(value)) or math.isinf(float(value)):
            return None
        return value
    except (TypeError, ValueError):
        return None


def clean_list(lst):
    """
    Clean a list of price values:
    - Replace NaN / Inf with None
    - Forward-fill gaps using the previous valid value
    - Backward-fill if the list opens with None
    """
    if not lst:
        return lst

    cleaned = [clean(v) for v in lst]

    last_valid = None
    for i, v in enumerate(cleaned):
        if v is not None:
            last_valid = v
        elif last_valid is not None:
            cleaned[i] = last_valid

    first_valid = next((v for v in cleaned if v is not None), None)
    if first_valid is not None:
        for i, v in enumerate(cleaned):
            if v is None:
                cleaned[i] = first_valid
            else:
                break

    return cleaned


def get_history(ticker_obj, period, interval, points):
    """
    Fetch historical closing prices for a yFinance Ticker object.
    Returns a sampled list of `points` values, or None on failure.

    Args:
        ticker_obj  — yf.Ticker instance
        period      — yFinance period string e.g. "5d", "1mo", "1y", "5y"
        interval    — yFinance interval string e.g. "1d", "1wk", "1mo"
        points      — number of evenly-spaced samples to return
    """
    try:
        hist = ticker_obj.history(period=period, interval=interval)
        if hist.empty:
            return None
        prices = hist["Close"].tolist()
        prices = clean_list(prices)

        if len(prices) >= points:
            step    = len(prices) / points
            sampled = [prices[min(int(i * step), len(prices) - 1)]
                       for i in range(points)]
            return sampled
        elif len(prices) > 0:
            return prices
        return None
    except Exception:
        return None


def get_ytd_start_price(yf_symbol):
    """
    Return the first available closing price on or after January 1 of the
    current calendar year for the given Yahoo Finance symbol.

    Uses a 15-day window from Jan 1 to catch any holiday gaps
    (e.g. New Year's Day + weekend = first trading day may be Jan 3 or 4).

    Args:
        yf_symbol — Yahoo Finance symbol string, e.g. "^RUA", "AGG", "AAPL"

    Returns:
        float or None
    """
    year  = datetime.date.today().year
    jan1  = f"{year}-01-01"
    jan15 = f"{year}-01-15"
    try:
        t     = yf.Ticker(yf_symbol)
        hist  = t.history(start=jan1, end=jan15, interval="1d")
        if hist.empty:
            return None
        prices = hist["Close"].dropna().tolist()
        return prices[0] if prices else None
    except Exception:
        return None


def get_intraday_1d(ticker_obj):
    """
    Fetch intraday 5-minute bars for the most recent trading session.
    Returns a list of { "t": "HH:MM", "p": price } dicts, or None.

    Falls back to the previous trading day if today's session has no data.
    """
    try:
        hist = ticker_obj.history(period="1d", interval="5m")
        if hist.empty:
            hist = ticker_obj.history(period="2d", interval="5m")
            if hist.empty:
                return None
            last_date = hist.index[-1].date()
            hist = hist[hist.index.map(lambda x: x.date()) == last_date]

        result = []
        for ts, row in hist.iterrows():
            price = clean(row.get("Close"))
            if price is None:
                continue
            try:
                local_ts = ts.tz_convert("America/New_York")
            except Exception:
                local_ts = ts
            label = local_ts.strftime("%-H:%M")
            result.append({"t": label, "p": round(price, 4)})

        return result if result else None
    except Exception:
        return None
