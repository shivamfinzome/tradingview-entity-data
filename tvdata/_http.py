"""Shared request settings. TradingView rejects calls that do not look like its own web app."""
from __future__ import annotations

ORIGIN = "https://in.tradingview.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
    ),
    "Origin": ORIGIN,
    "Referer": ORIGIN + "/",
}
TIMEOUT = 20


class TradingViewError(RuntimeError):
    """TradingView returned an error, or nothing usable, for the request."""


class NotFound(TradingViewError):
    """TradingView answered, but has no such symbol."""
