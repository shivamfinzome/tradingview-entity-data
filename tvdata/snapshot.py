"""Current quote, fundamentals, analyst view and technicals for one symbol (the screener backend)."""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from ._http import HEADERS, TIMEOUT, NotFound, TradingViewError

SCAN_URL = "https://scanner.tradingview.com/global/scan"

# group -> {TradingView field: label}. JSON output keeps the TradingView field names; labels are
# only for the text view. Fields a symbol does not have (an index has no P/E) are dropped.
FIELDS: dict[str, dict[str, str]] = {
    "profile": {
        "name": "Symbol",
        "description": "Name",
        "type": "Type",
        "typespecs": "Subtype",
        "exchange": "Exchange",
        "country": "Country",
        "currency": "Currency",
        "fundamental_currency_code": "Fundamentals currency",
        "sector": "Sector",
        "industry": "Industry",
        "isin": "ISIN",
        "timezone": "Exchange timezone",
    },
    "quote": {
        "close": "Last price",
        "change": "Change",
        "change_abs": "Change (absolute)",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "volume": "Volume",
        "VWAP": "VWAP",
        "average_volume_10d_calc": "Avg volume (10d)",
        "average_volume_30d_calc": "Avg volume (30d)",
        "relative_volume_10d_calc": "Relative volume (10d)",
        "price_52_week_high": "52-week high",
        "price_52_week_low": "52-week low",
        "High.All": "All-time high",
        "Low.All": "All-time low",
        "current_session": "Session",
        "update_mode": "Data mode",
    },
    "valuation": {
        "market_cap_basic": "Market cap",
        "enterprise_value_current": "Enterprise value",
        "price_earnings_ttm": "P/E (TTM)",
        "price_book_fq": "P/B (last quarter)",
        "price_book_ratio": "P/B",
        "price_sales_current": "P/S",
        "price_free_cash_flow_ttm": "P/FCF (TTM)",
        "enterprise_value_ebitda_ttm": "EV/EBITDA (TTM)",
        "earnings_per_share_basic_ttm": "EPS basic (TTM)",
        "earnings_per_share_diluted_ttm": "EPS diluted (TTM)",
        "dividends_yield_current": "Dividend yield",
        "dps_common_stock_prim_issue_fy": "Dividend per share (FY)",
        "dividend_payout_ratio_ttm": "Payout ratio (TTM)",
        "ex_dividend_date_recent": "Last ex-dividend date",
        "beta_1_year": "Beta (1Y)",
        "total_shares_outstanding": "Shares outstanding",
        "float_shares_outstanding": "Free float shares",
    },
    "financials": {
        "total_revenue_ttm": "Revenue (TTM)",
        "total_revenue_fy": "Revenue (FY)",
        "total_revenue_yoy_growth_ttm": "Revenue growth (TTM YoY)",
        "gross_profit_ttm": "Gross profit (TTM)",
        "ebitda_ttm": "EBITDA (TTM)",
        "net_income_ttm": "Net income (TTM)",
        "net_income_fy": "Net income (FY)",
        "earnings_per_share_diluted_yoy_growth_ttm": "EPS growth (TTM YoY)",
        "gross_margin_ttm": "Gross margin (TTM)",
        "operating_margin_ttm": "Operating margin (TTM)",
        "net_margin_ttm": "Net margin (TTM)",
        "free_cash_flow_ttm": "Free cash flow (TTM)",
        "return_on_equity_fq": "ROE (last quarter)",
        "return_on_equity_fy": "ROE (FY)",
        "return_on_assets_fq": "ROA (last quarter)",
        "return_on_assets_fy": "ROA (FY)",
        "return_on_invested_capital_fq": "ROIC (last quarter)",
        "total_assets_fq": "Total assets (last quarter)",
        "total_assets_fy": "Total assets (FY)",
        "total_debt_fq": "Total debt (last quarter)",
        "total_debt_fy": "Total debt (FY)",
        "cash_n_short_term_invest_fq": "Cash & short-term investments",
        "debt_to_equity_fq": "Debt/equity",
        "current_ratio_fq": "Current ratio",
        "quick_ratio_fq": "Quick ratio",
        "number_of_employees_fy": "Employees",
    },
    "analysts": {
        "recommendation_mark": "Consensus score (1 = strong buy)",
        "recommendation_total": "Analysts covering",
        "price_target_average": "Price target (avg)",
        "price_target_high": "Price target (high)",
        "price_target_low": "Price target (low)",
        "earnings_per_share_fq": "EPS (last quarter)",
        "earnings_per_share_forecast_next_fq": "EPS forecast (next quarter)",
        "earnings_release_date": "Last earnings date",
        "earnings_release_next_date": "Next earnings date",
    },
    "performance": {
        "Perf.W": "1 week",
        "Perf.1M": "1 month",
        "Perf.3M": "3 months",
        "Perf.6M": "6 months",
        "Perf.YTD": "Year to date",
        "Perf.Y": "1 year",
        "Perf.5Y": "5 years",
        "Perf.All": "All time",
        "Volatility.D": "Volatility (day)",
        "Volatility.W": "Volatility (week)",
        "Volatility.M": "Volatility (month)",
    },
    "technicals": {
        "Recommend.All": "Technical rating (-1 sell .. +1 buy)",
        "Recommend.MA": "Moving averages rating",
        "Recommend.Other": "Oscillators rating",
        "RSI": "RSI (14)",
        "MACD.macd": "MACD",
        "MACD.signal": "MACD signal",
        "Stoch.K": "Stochastic %K",
        "Stoch.D": "Stochastic %D",
        "ADX": "ADX (14)",
        "CCI20": "CCI (20)",
        "ATR": "ATR (14)",
        "Mom": "Momentum (10)",
        "SMA20": "SMA 20",
        "SMA50": "SMA 50",
        "SMA200": "SMA 200",
        "EMA20": "EMA 20",
        "EMA50": "EMA 50",
        "EMA200": "EMA 200",
        "BB.upper": "Bollinger upper",
        "BB.lower": "Bollinger lower",
    },
}

EPOCH_FIELDS = {"ex_dividend_date_recent", "earnings_release_date", "earnings_release_next_date"}
# TradingView sends these as 2.66 for 2.66%.
PERCENT_FIELDS = {
    "change", "dividends_yield_current", "dividend_payout_ratio_ttm", "total_revenue_yoy_growth_ttm",
    "earnings_per_share_diluted_yoy_growth_ttm", "gross_margin_ttm", "operating_margin_ttm", "net_margin_ttm",
    "return_on_equity_fq", "return_on_equity_fy", "return_on_assets_fq", "return_on_assets_fy",
    "return_on_invested_capital_fq", "Perf.W", "Perf.1M", "Perf.3M", "Perf.6M", "Perf.YTD", "Perf.Y",
    "Perf.5Y", "Perf.All", "Volatility.D", "Volatility.W", "Volatility.M",
}
# "rating" is derived from Recommend.All in snapshot(); it is not a TradingView field.
LABELS = {field: label for group in FIELDS.values() for field, label in group.items()} | {"rating": "Technical rating"}


def rating_label(score: float | None) -> str | None:
    """TradingView's own buckets for a -1..+1 technical rating."""
    if score is None:
        return None
    if score > 0.5:
        return "Strong buy"
    if score > 0.1:
        return "Buy"
    if score >= -0.1:
        return "Neutral"
    if score >= -0.5:
        return "Sell"
    return "Strong sell"


def snapshot(ticker: str) -> dict[str, dict]:
    """Latest values for `ticker`, grouped as in FIELDS. Money is in the listing's own currency."""
    columns = [field for group in FIELDS.values() for field in group]
    body = {
        "symbols": {"tickers": [ticker]},
        "columns": columns,
        # Without this, fundamentals come back in USD whatever the listing currency is.
        "price_conversion": {"to_symbol": True},
    }
    resp = requests.post(SCAN_URL, json=body, headers=HEADERS, timeout=TIMEOUT)
    if resp.status_code != 200:
        raise TradingViewError(f"snapshot failed for {ticker}: HTTP {resp.status_code} {resp.text[:200]}")
    rows = resp.json().get("data") or []
    if not rows:
        raise NotFound(f"TradingView has no symbol {ticker}")

    values = dict(zip(columns, rows[0]["d"]))
    out: dict[str, dict] = {}
    for group, fields in FIELDS.items():
        kept = {}
        for field in fields:
            value = values.get(field)
            if value is None or value == []:
                continue
            if field in EPOCH_FIELDS:
                value = datetime.fromtimestamp(value, timezone.utc).isoformat()
            kept[field] = value
            if field == "Recommend.All":
                kept["rating"] = rating_label(value)
        if kept:
            out[group] = kept
    return out
