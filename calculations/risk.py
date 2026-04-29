"""
risk.py
=======
Risk analysis calculations for the Risk Analysis tab.

Section 1 — Holdings below cost basis (underwater positions)
Section 2 — Holdings that declined over the past 5 trading days

Severity thresholds (applied to loss %):
  Mild     : 0% – 5%   below cost basis / 5-day decline
  Moderate : 5% – 15%  below cost basis / 5-day decline
  Severe   : 15%+      below cost basis / 5-day decline

To change severity thresholds, edit SEVERITY_THRESHOLDS below.
"""

SEVERITY_THRESHOLDS = {
    "mild":     5.0,    # loss < 5%  → mild
    "moderate": 15.0,   # loss < 15% → moderate
    # loss >= 15% → severe
}


def get_severity(loss_pct):
    """
    Return severity label for a given loss percentage (negative number = loss).
    loss_pct should be negative, e.g. -8.3 means 8.3% below cost/5d start.
    """
    abs_loss = abs(loss_pct)
    if abs_loss < SEVERITY_THRESHOLDS["mild"]:
        return "mild"
    elif abs_loss < SEVERITY_THRESHOLDS["moderate"]:
        return "moderate"
    else:
        return "severe"


def calc_below_cost_basis(holdings, market_data):
    """
    Find all holdings where current price is below the purchase cost basis.

    Args:
        holdings    — list of holding dicts { ticker, shares, cost_basis, sector }
        market_data — dict of { TICKER: { price, ... } }

    Returns list of dicts, sorted worst loss first:
        ticker, sector, shares, costBasis, currentPrice,
        pnlDollar, pnlPct, portfolioWeight, severity
    """
    # Calculate total portfolio value for weight %
    total_value = sum(
        (market_data.get(h["ticker"].upper(), {}).get("price") or 0) * h["shares"]
        for h in holdings
    )

    results = []
    for h in holdings:
        ticker = h["ticker"].upper()
        price  = market_data.get(ticker, {}).get("price")
        cost   = h["cost_basis"]

        if price is None or price >= cost:
            continue   # not underwater

        pnl_dollar = (price - cost) * h["shares"]
        pnl_pct    = (price - cost) / cost * 100
        weight     = (price * h["shares"] / total_value * 100) if total_value else 0

        results.append({
            "ticker":          ticker,
            "sector":          h.get("sector", "—"),
            "shares":          h["shares"],
            "costBasis":       cost,
            "currentPrice":    price,
            "pnlDollar":       round(pnl_dollar, 2),
            "pnlPct":          round(pnl_pct, 4),
            "portfolioWeight": round(weight, 4),
            "severity":        get_severity(pnl_pct),
        })

    # Sort worst loss first
    results.sort(key=lambda x: x["pnlPct"])
    return results


def calc_negative_5d(holdings, market_data):
    """
    Find all holdings that declined over the past 5 trading days.
    Uses history5d[0] as the "5 days ago" price and history5d[-1] as today.

    Args:
        holdings    — list of holding dicts
        market_data — dict of { TICKER: { price, history5d, ... } }

    Returns list of dicts, sorted worst decline first:
        ticker, sector, price5dAgo, currentPrice,
        chgDollar, chgPct, portfolioWeight, severity
    """
    total_value = sum(
        (market_data.get(h["ticker"].upper(), {}).get("price") or 0) * h["shares"]
        for h in holdings
    )

    results = []
    for h in holdings:
        ticker  = h["ticker"].upper()
        info    = market_data.get(ticker, {})
        hist    = info.get("history5d") or []
        price   = info.get("price")

        valid_hist = [v for v in hist if v is not None]
        if len(valid_hist) < 2 or price is None:
            continue

        price_5d_ago = valid_hist[0]
        if price >= price_5d_ago:
            continue   # flat or positive over 5 days

        chg_dollar = price - price_5d_ago
        chg_pct    = (price - price_5d_ago) / price_5d_ago * 100
        weight     = (price * h["shares"] / total_value * 100) if total_value else 0

        results.append({
            "ticker":          ticker,
            "sector":          h.get("sector", "—"),
            "shares":          h["shares"],
            "price5dAgo":      round(price_5d_ago, 4),
            "currentPrice":    round(price, 4),
            "chgDollar":       round(chg_dollar, 2),
            "chgPct":          round(chg_pct, 4),
            "portfolioWeight": round(weight, 4),
            "severity":        get_severity(chg_pct),
        })

    results.sort(key=lambda x: x["chgPct"])
    return results


def calc_risk_summary(below_cost, total_holdings, total_portfolio_value):
    """
    Build the summary banner numbers shown at the top of the Risk Analysis tab.

    Args:
        below_cost           — list returned by calc_below_cost_basis()
        total_holdings       — total number of holdings
        total_portfolio_value — total current portfolio value in dollars

    Returns:
        negativeCount        — number of underwater positions
        combinedWeight       — their combined % of portfolio
        totalUnrealizedLoss  — total dollar loss across underwater positions
    """
    count        = len(below_cost)
    combined_wt  = sum(x["portfolioWeight"] for x in below_cost)
    total_loss   = sum(x["pnlDollar"] for x in below_cost)

    return {
        "negativeCount":       count,
        "totalHoldings":       total_holdings,
        "combinedWeight":      round(combined_wt, 4),
        "totalUnrealizedLoss": round(total_loss, 2),
    }
