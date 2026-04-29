"""
server.py
=========
Fairfield SMIF Portfolio Dashboard — Flask API Server

Run:  python server.py
      Then open dashboard.html in your browser.

All calculation logic lives in the calculations/ folder:
  calculations/utils.py       — shared helpers, PERF_EXCLUDE list
  calculations/benchmark.py   — RUA/AGG benchmark config and math
  calculations/portfolio.py   — portfolio value, P&L, YTD return
  calculations/performance.py — 5-day return vs benchmark
  calculations/alpha.py       — YTD alpha = portfolio YTD - benchmark YTD
  calculations/risk.py        — below cost basis, 5-day decliners

Endpoints:
  GET  /holdings              — full holdings.json + sector structure
  POST /holdings              — overwrite holdings.json
  GET  /api/market-data       — live prices + history for all tickers
  GET  /api/alpha             — YTD alpha vs benchmark
  GET  /api/risk              — risk analysis data (below cost + 5d decliners)
  GET  /api/debug/benchmark   — diagnostic: what does yFinance return for RUA/AGG?
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import yfinance as yf
import json
import os

# ── Import all calculation modules ────────────────────────────────────────────
from calculations.utils       import clean, clean_list, get_history, get_intraday_1d, PERF_EXCLUDE
from calculations.benchmark   import BENCHMARK_FETCH, BENCHMARK_WEIGHTS, BENCHMARK_LABEL
from calculations.alpha       import calc_alpha_ytd
from calculations.performance import calc_5d_performance
from calculations.risk        import (calc_below_cost_basis, calc_negative_5d,
                                      calc_risk_summary)

app = Flask(__name__)
CORS(app)

HOLDINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holdings.json")


# ═════════════════════════════════════════════════════════════════════════════
# Holdings file helpers
# ═════════════════════════════════════════════════════════════════════════════

def load_holdings():
    try:
        with open(HOLDINGS_FILE, "r") as f:
            return json.load(f).get("holdings", [])
    except FileNotFoundError:
        print(f"  ⚠  holdings.json not found at {HOLDINGS_FILE}")
        return []
    except json.JSONDecodeError as e:
        print(f"  ⚠  holdings.json is malformed: {e}")
        return []


def save_holdings(holdings_list):
    tmp = HOLDINGS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"holdings": holdings_list}, f, indent=2)
    os.replace(tmp, HOLDINGS_FILE)


def get_all_fetch_symbols():
    """
    Return list of (yf_fetch_symbol, store_key) pairs for all tickers.
    Benchmark index symbols (^RUA) are fetched via their yFinance symbol
    but stored under their clean key (RUA) in the response JSON.
    CASH is skipped — it's a plain balance entry, not a real ticker.
    """
    # Tickers that are not real yFinance symbols — skip fetching entirely
    NO_FETCH = {"CASH"}

    holdings     = load_holdings()
    holding_syms = [(h["ticker"].upper(), h["ticker"].upper())
                    for h in holdings
                    if h.get("ticker") and h["ticker"].upper() not in NO_FETCH]
    bench_syms   = [(yf_sym, clean_key)
                    for clean_key, yf_sym in BENCHMARK_FETCH.items()]
    # Deduplicate while preserving order, benchmark first
    seen   = set()
    result = []
    for yf_sym, store_key in bench_syms + holding_syms:
        if store_key not in seen:
            seen.add(store_key)
            result.append((yf_sym, store_key))
    return result


# ═════════════════════════════════════════════════════════════════════════════
# Holdings endpoints
# ═════════════════════════════════════════════════════════════════════════════

@app.route("/holdings", methods=["GET"])
def get_holdings():
    holdings = load_holdings()
    sectors  = {}
    for h in holdings:
        sector = h.get("sector", "Other")
        sectors.setdefault(sector, [])
        sectors[sector].append({
            "ticker":    h["ticker"].upper(),
            "shares":    h["shares"],
            "costBasis": h["cost_basis"],
        })
    return jsonify({
        "holdings":         holdings,
        "sectors":          sectors,
        "sectorOrder":      list(sectors.keys()),   # explicit ordered list for the dashboard
        "benchmarkWeights": {k: v for k, v in BENCHMARK_WEIGHTS.items()},
        "benchmarkLabel":   BENCHMARK_LABEL,
    })


@app.route("/holdings", methods=["POST"])
def post_holdings():
    try:
        body = request.get_json(force=True)
        if not body or "holdings" not in body:
            return jsonify({"error": "Body must contain a 'holdings' array."}), 400

        new_holdings = body["holdings"]
        errors = []
        for i, h in enumerate(new_holdings):
            row = i + 1
            if not h.get("ticker") or not str(h["ticker"]).strip():
                errors.append(f"Row {row}: ticker required.")
            if not isinstance(h.get("shares"), (int, float)) or h["shares"] <= 0:
                errors.append(f"Row {row} ({h.get('ticker','?')}): shares must be positive.")
            if not isinstance(h.get("cost_basis"), (int, float)) or h["cost_basis"] <= 0:
                errors.append(f"Row {row} ({h.get('ticker','?')}): cost_basis must be positive.")
            if not h.get("sector") or not str(h["sector"]).strip():
                errors.append(f"Row {row} ({h.get('ticker','?')}): sector required.")
        if errors:
            return jsonify({"error": "Validation failed.", "details": errors}), 422

        for h in new_holdings:
            h["ticker"] = str(h["ticker"]).strip().upper()
            h["sector"] = str(h["sector"]).strip()

        save_holdings(new_holdings)
        print(f"\n  ✓ holdings.json updated — {len(new_holdings)} holdings.\n")
        return jsonify({"ok": True, "count": len(new_holdings)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═════════════════════════════════════════════════════════════════════════════
# Market data endpoint
# ═════════════════════════════════════════════════════════════════════════════

def _fix_yield(raw):
    """
    Pass dividendYield through as-is from yFinance.
    yFinance returns it as a decimal (e.g. 0.0097 for 0.97%).
    The dashboard multiplies by 100 for display.
    Returns None for null/zero values.
    """
    if not raw:
        return None
    try:
        v = float(raw)
        return round(v, 6) if v > 0 else None
    except (TypeError, ValueError):
        return None


@app.route("/api/market-data")
def market_data():
    """
    Fetch live prices, fundamentals, and historical OHLCV for all tickers.
    Benchmark index tickers (^RUA) are fetched via their yFinance symbol
    and stored under their clean key (RUA) in the response.
    """
    ticker_pairs = get_all_fetch_symbols()
    results      = {}
    key_map      = {yf_sym: store_key for yf_sym, store_key in ticker_pairs}

    print(f"\nFetching market data for {len(ticker_pairs)} tickers...\n")

    for yf_sym, store_key in ticker_pairs:
        print(f"  → {store_key} ({yf_sym})", end="", flush=True)
        try:
            t    = yf.Ticker(yf_sym)
            info = t.info or {}

            price = clean(
                info.get("currentPrice")
                or info.get("regularMarketPrice")
                or info.get("navPrice")
                or info.get("previousClose")
            )
            prev_close = clean(
                info.get("regularMarketPreviousClose") or info.get("previousClose")
            )
            change     = clean((price - prev_close) if price and prev_close else None)
            change_pct = clean(
                ((price - prev_close) / prev_close * 100)
                if price and prev_close and prev_close != 0 else None
            )

            results[store_key] = {
                "price":         price,
                "change":        change,
                "changePct":     change_pct,
                "open":          clean(info.get("open") or info.get("regularMarketOpen")),
                "high":          clean(info.get("dayHigh") or info.get("regularMarketDayHigh")),
                "low":           clean(info.get("dayLow")  or info.get("regularMarketDayLow")),
                "volume":        clean(info.get("volume")  or info.get("regularMarketVolume")),
                "avgVolume":     clean(info.get("averageVolume") or info.get("averageVolume10days")),
                "marketCap":     clean(info.get("marketCap")),
                "beta":          clean(info.get("beta")),
                "peRatio":       clean(info.get("trailingPE") or info.get("forwardPE")),
                "eps":           clean(info.get("trailingEps")),
                "dividendYield": _fix_yield(info.get("dividendYield")),
                "week52High":    clean(info.get("fiftyTwoWeekHigh")),
                "week52Low":     clean(info.get("fiftyTwoWeekLow")),
                "expenseRatio":  (clean((info.get("annualReportExpenseRatio") or 0) * 100)
                                  if info.get("annualReportExpenseRatio") else None),
                "history1d":     get_intraday_1d(t),
                "history5d":     get_history(t, "5d",  "1d",  6),
                "history1m":     get_history(t, "1mo", "1d",  22),
                "history1y":     get_history(t, "1y",  "1wk", 52),
                "history5y":     get_history(t, "5y",  "1mo", 60),
            }
            print(" ✓")

        except Exception as e:
            print(f" ✗ ({e})")
            results[store_key] = {"error": str(e)}

    raw = json.dumps(results)
    raw = raw.replace(": NaN", ": null").replace(": Infinity", ": null").replace(": -Infinity", ": null")
    print(f"\nDone. {len(results)} tickers.\n")
    return app.response_class(response=raw, status=200, mimetype="application/json")


# ═════════════════════════════════════════════════════════════════════════════
# Alpha endpoint
# ═════════════════════════════════════════════════════════════════════════════

@app.route("/api/alpha")
def alpha():
    """
    YTD alpha = portfolio YTD return − benchmark YTD return.
    All logic in calculations/alpha.py and calculations/benchmark.py.
    """
    holdings = load_holdings()
    if not holdings:
        return jsonify({"error": "No holdings loaded."}), 400
    result = calc_alpha_ytd(holdings)
    return jsonify(result)


# ═════════════════════════════════════════════════════════════════════════════
# Risk endpoint
# ═════════════════════════════════════════════════════════════════════════════

@app.route("/api/risk")
def risk():
    """
    Risk analysis data for the Risk Analysis tab.
    All logic in calculations/risk.py.
    Pulls market data fresh on each call so it's always current.
    """
    holdings = load_holdings()
    if not holdings:
        return jsonify({"error": "No holdings loaded."}), 400

    # Get market data (already fetched and cached by market-data endpoint normally,
    # but we call it fresh here so risk can be called independently)
    from flask import current_app
    with current_app.test_client() as c:
        resp     = c.get("/api/market-data")
        mkt_data = json.loads(resp.data)

    below_cost  = calc_below_cost_basis(holdings, mkt_data)
    neg_5d      = calc_negative_5d(holdings, mkt_data)
    total_value = sum(
        (mkt_data.get(h["ticker"].upper(), {}).get("price") or 0) * h["shares"]
        for h in holdings
    )
    summary = calc_risk_summary(below_cost, len(holdings), total_value)

    return jsonify({
        "summary":      summary,
        "belowCost":    below_cost,
        "negative5d":   neg_5d,
    })


# ═════════════════════════════════════════════════════════════════════════════
# Debug endpoint
# ═════════════════════════════════════════════════════════════════════════════

@app.route("/api/debug/benchmark")
def debug_benchmark():
    """
    Diagnostic — open http://localhost:5050/api/debug/benchmark in your browser
    to see exactly what yFinance returns for the benchmark tickers.
    """
    out = {}
    for clean_key, yf_sym in BENCHMARK_FETCH.items():
        try:
            t    = yf.Ticker(yf_sym)
            info = t.info or {}
            hist = t.history(period="5d", interval="1d")
            closes = [clean(c) for c in hist["Close"].tolist()] if not hist.empty else []
            out[clean_key] = {
                "yfSymbol":   yf_sym,
                "price":      clean(info.get("currentPrice") or info.get("regularMarketPrice")
                                    or info.get("navPrice") or info.get("previousClose")),
                "changePct":  clean(info.get("regularMarketChangePercent")),
                "history5d":  closes,
                "infoKeys":   list(info.keys())[:15],
            }
        except Exception as e:
            out[clean_key] = {"yfSymbol": yf_sym, "error": str(e)}
    return jsonify(out)


# ═════════════════════════════════════════════════════════════════════════════
# Russell 3000 sector weights endpoint
# ═════════════════════════════════════════════════════════════════════════════

# Approximate Russell 3000 sector weights (GICS sectors, as of 2025).
# yFinance does not expose index constituent weights directly, so we use
# published approximate weights from iShares IWV (Russell 3000 ETF) holdings.
# Update these annually or when rebalancing.
RUSSELL_3000_WEIGHTS = {
    "Technology":        29.5,
    "Healthcare":        11.8,
    "Financials":        13.9,
    "Consumer Disc.":     9.8,
    "Consumer":           9.8,   # alias used in our holdings
    "Industrials":        9.2,
    "Communication":      8.3,
    "Energy":             3.7,
    "Real Estate":        3.4,
    "Materials":          3.2,
    "Utilities":          2.5,
    "Consumer Staples":   2.7,
}

@app.route("/api/sector-weights")
def sector_weights():
    """
    Return approximate Russell 3000 sector weights for the allocation
    comparison table on the Overview page.

    These are sourced from iShares IWV (Russell 3000 ETF) published holdings
    and updated manually. yFinance does not expose index-level sector weights
    directly via its API.
    """
    return jsonify({
        "russell3000": RUSSELL_3000_WEIGHTS,
        "source": "iShares IWV published holdings (approximate, 2025)",
        "note": "Update RUSSELL_3000_WEIGHTS in server.py annually."
    })




if __name__ == "__main__":
    holdings_count = len(load_holdings())
    print("=" * 60)
    print("  Fairfield SMIF Portfolio Server")
    print(f"  Holdings:  {HOLDINGS_FILE}  ({holdings_count} positions)")
    print(f"  Benchmark: {BENCHMARK_LABEL}")
    print("  Calc modules: calculations/")
    print("    benchmark.py · portfolio.py · performance.py")
    print("    alpha.py     · risk.py      · utils.py")
    print("  Endpoints:")
    print("    GET  /holdings")
    print("    POST /holdings")
    print("    GET  /api/market-data")
    print("    GET  /api/alpha")
    print("    GET  /api/risk")
    print("    GET  /api/debug/benchmark")
    print("=" * 60)
    app.run(port=5050, debug=False)