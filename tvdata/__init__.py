"""Give an entity name, get its TradingView data."""
from __future__ import annotations

from collections.abc import Sequence

from . import indicators
from ._http import NotFound, TradingViewError
from .history import history
from .search import Match, resolve, search
from .snapshot import snapshot

__all__ = [
    "Match", "NotFound", "TradingViewError", "get_entity_data", "history", "indicators", "resolve", "search", "snapshot",
]


def get_entity_data(
    name: str,
    *,
    exchange: str | None = None,
    asset_type: str | None = None,
    country: str = "IN",
    interval: str = "1D",
    bars: int = 250,
    include_history: bool = True,
    indicators: Sequence[str] = (),
) -> dict:
    """Resolve `name` ("Reliance Industries", or a ticker like "NSE:RELIANCE") and fetch everything.

    `indicators` ("RSI", "SMA(200)", "PUB;175") become extra columns on the history bars.
    Returns {"query", "ticker", "match", "other_matches", "snapshot", "history", "history_error"}.
    """
    match, others = resolve(name, exchange=exchange, asset_type=asset_type, country=country)
    snap = snapshot(match.ticker)

    # A ticker passed directly skips search, so fill the match in from the snapshot.
    profile = snap.get("profile", {})
    match.description = match.description or profile.get("description", "")
    match.type = match.type or profile.get("type", "")
    match.currency = match.currency or profile.get("currency")
    match.isin = match.isin or profile.get("isin")

    # Some feeds serve a snapshot but no bars without a login; keep the snapshot and say why.
    hist, hist_error = None, None
    if include_history:
        try:
            hist = history(match.ticker, interval=interval, bars=bars, indicators=indicators)
        except TradingViewError as exc:
            hist_error = str(exc)

    return {
        "query": name,
        "ticker": match.ticker,
        "match": match.to_dict(),
        "other_matches": [m.to_dict() for m in others],
        "snapshot": snap,
        "history": hist,
        "history_error": hist_error,
    }
