"""Entity name -> TradingView symbol, using the same search the website's symbol box uses."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import requests

from ._http import HEADERS, TIMEOUT, NotFound, TradingViewError

SEARCH_URL = "https://symbol-search.tradingview.com/symbol_search/v3/"
# "NSE:RELIANCE", "BITSTAMP:BTCUSD", "NSE:HDFCBANK1!" - already a symbol, no search needed.
TICKER_RE = re.compile(r"^[A-Za-z0-9_]+:[A-Za-z0-9_.!&\-/]+$")


@dataclass
class Match:
    ticker: str  # "NSE:RELIANCE" - what the other TradingView endpoints expect
    symbol: str
    exchange: str
    description: str
    type: str
    country: str | None = None
    currency: str | None = None
    isin: str | None = None
    primary_listing: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _to_match(row: dict) -> Match:
    source = row.get("prefix") or row.get("source_id") or row.get("exchange") or ""
    symbol = row["symbol"]
    # Futures come back as a root ("HDFCBANK"); the first contract is the continuous front month.
    if row.get("contracts"):
        symbol = row["contracts"][0]["symbol"]
    return Match(
        ticker=f"{source}:{symbol}".upper(),
        symbol=symbol,
        exchange=row.get("exchange") or source,
        description=row.get("description") or "",
        type=row.get("type") or "",
        country=row.get("country"),
        currency=row.get("currency_code"),
        isin=row.get("isin"),
        primary_listing=bool(row.get("is_primary_listing")),
    )


def search(
    text: str,
    *,
    exchange: str | None = None,
    asset_type: str | None = None,
    country: str = "IN",
    limit: int = 10,
) -> list[Match]:
    """Candidates for `text`, in TradingView's own relevance order.

    `country` only biases the ordering (an Indian listing ranks above its ADR); it does not filter.
    """
    params = {
        "text": text,
        "hl": 0,
        "exchange": (exchange or "").upper(),
        "lang": "en",
        "search_type": asset_type or "undefined",
        "domain": "production",
        "sort_by_country": country.upper(),
    }
    resp = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
    if resp.status_code != 200:
        raise TradingViewError(f"symbol search failed: HTTP {resp.status_code}")
    return [_to_match(row) for row in resp.json().get("symbols", [])[:limit]]


def resolve(
    name: str,
    *,
    exchange: str | None = None,
    asset_type: str | None = None,
    country: str = "IN",
    limit: int = 10,
) -> tuple[Match, list[Match]]:
    """Best match for an entity name, plus the runners-up so a wrong pick is visible."""
    name = name.strip()
    if TICKER_RE.match(name):
        source, symbol = name.upper().split(":", 1)
        return Match(ticker=f"{source}:{symbol}", symbol=symbol, exchange=source, description="", type=""), []

    matches = search(name, exchange=exchange, asset_type=asset_type, country=country, limit=limit)
    if not matches:
        scope = "".join(f" ({k}={v})" for k, v in (("exchange", exchange), ("type", asset_type)) if v)
        raise NotFound(f"no TradingView symbol found for {name!r}{scope}")
    return matches[0], matches[1:]
