"""OHLCV bars for one symbol, read from the websocket feed that draws TradingView's charts.

Not logged in, so exchange data is delayed (NSE/BSE by 15 minutes) and intraday history stops at
about 5,000 bars. Asking for more bars than exist returns what there is.

Indicators are computed by TradingView on the same kind of feed and come back as extra columns.
"""
from __future__ import annotations

import json
import random
import re
import string
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from websocket import WebSocketException, WebSocketTimeoutException, create_connection

from ._http import HEADERS, ORIGIN, TIMEOUT, NotFound, TradingViewError
from .indicators import NA, STUDY_TYPE, Indicator
from .indicators import load as load_indicator

# Two feeds serve the same symbols. The one behind TradingView's embeddable chart widget also
# computes indicators for anyone; the one behind its own chart page refuses them unless you are
# signed in. The widget feed goes first, so bars are the same with and without indicators (the
# two can differ by a few ticks on the current day's intraday bars).
WIDGET_FEED = ("wss://widgetdata.tradingview.com/socket.io/websocket", "https://s.tradingview.com")
DATA_FEED = ("wss://data.tradingview.com/socket.io/websocket", ORIGIN)
MAX_INDICATORS = 10
# Each connection lands on one of TradingView's chart servers, and now and then one of them sits
# on a request for about a minute. Past this many seconds without bars, ask a different server.
STALL_AFTER = 6
PRICE_COLUMNS = ("time", "open", "high", "low", "close", "volume")
FRAME_RE = re.compile(r"~m~(\d+)~m~")
ERRORS = {"series_error", "critical_error", "protocol_error"}


class _Stalled(Exception):
    """The server took the request but sent no bars in time."""


def to_resolution(interval: str) -> str:
    """'5m' -> '5', '1h' -> '60', '1d' -> '1D', '1w' -> '1W', '1M' -> '1M' (capital M is months)."""
    m = re.fullmatch(r"(\d+)\s*([A-Za-z]*)", interval.strip())
    if not m:
        raise ValueError(f"bad interval {interval!r} (try 5m, 1h, 1D, 1W, 1M)")
    n, unit = int(m.group(1)), m.group(2)
    if unit in ("", "m", "min"):
        return str(n)
    if unit in ("M", "mo", "Mo", "MO"):
        return f"{n}M"
    if unit.lower() == "h":
        return str(n * 60)
    if unit.lower() in ("d", "w"):
        return f"{n}{unit.upper()}"
    raise ValueError(f"bad interval {interval!r} (try 5m, 1h, 1D, 1W, 1M)")


def encode(method: str, params: list) -> str:
    body = json.dumps({"m": method, "p": params}, separators=(",", ":"))
    return f"~m~{len(body)}~m~{body}"


def decode(raw: str) -> list[str]:
    """Split one websocket message into its length-prefixed payloads."""
    payloads, pos = [], 0
    while True:
        m = FRAME_RE.match(raw, pos)
        if not m:
            return payloads
        end = m.end() + int(m.group(1))
        payloads.append(raw[m.end():end])
        pos = end


def _zone(name: str | None):
    try:
        return ZoneInfo(name) if name else timezone.utc
    except ZoneInfoNotFoundError:
        return timezone.utc


def study_error(reason) -> str:
    """TradingView's reason for refusing an indicator, with its {placeholders} filled in."""
    if not isinstance(reason, dict):
        return str(reason)
    context = reason.get("ctx") or {}
    text = re.sub(r"\{(\w+)\}", lambda m: str(context.get(m.group(1), m.group(0))), str(reason.get("error", "")))
    return text or str(context.get("code", "no reason given"))


def load_indicators(specs: Sequence[str]) -> list[Indicator]:
    """Indicators for the given specs, with column names that do not clash with each other."""
    if len(specs) > MAX_INDICATORS:
        raise ValueError(f"at most {MAX_INDICATORS} indicators per request, got {len(specs)}")
    try:
        studies = [load_indicator(spec) for spec in specs]
    except NotFound as exc:  # a wrong name is the caller's mistake, not a missing price history
        raise ValueError(str(exc)) from exc
    taken = set(PRICE_COLUMNS)
    for study in studies:  # the same indicator twice, or one named like a price column
        for pos, name in study.columns.items():
            unique, n = name, 2
            while unique in taken:
                unique, n = f"{name} ({n})", n + 1
            study.columns[pos] = unique
            taken.add(unique)
    return studies


def _stream(feed, ticker: str, resolution: str, bars: int, studies: list[Indicator], deadline: float):
    """One connection's worth of work: the symbol's metadata, its candles and each study's rows."""
    url, origin = feed
    session = "cs_" + "".join(random.choices(string.ascii_lowercase, k=12))
    symbol = "=" + json.dumps({"symbol": ticker, "adjustment": "splits", "session": "regular"})
    try:
        ws = create_connection(url, origin=origin, header={"User-Agent": HEADERS["User-Agent"]}, timeout=TIMEOUT)
    except (WebSocketException, OSError) as exc:
        raise TradingViewError(f"could not open TradingView data feed: {exc}") from exc

    info: dict = {}
    candles: dict[float, list] = {}  # by bar time: a live bar is sent again whenever it changes
    plots: dict[str, dict[float, list]] = {f"st{n}": {} for n in range(len(studies))}
    waiting = {"sds_1", *plots}
    stalled_at = time.monotonic() + STALL_AFTER
    try:
        ws.settimeout(1)  # wake up often enough to notice a stall or the deadline
        ws.send(encode("set_auth_token", ["unauthorized_user_token"]))
        ws.send(encode("chart_create_session", [session, ""]))
        ws.send(encode("resolve_symbol", [session, "sds_sym_1", symbol]))
        ws.send(encode("create_series", [session, "sds_1", "s1", "sds_sym_1", resolution, bars, ""]))
        for study_id, study in zip(plots, studies):
            ws.send(encode("create_study", [session, study_id, "st1", "sds_1", STUDY_TYPE, study.payload]))

        while waiting:
            now = time.monotonic()
            if now > deadline:
                raise TradingViewError(f"timed out waiting for {ticker} {resolution} bars")
            if not candles and now > stalled_at and now + STALL_AFTER < deadline:
                raise _Stalled
            try:
                raw = ws.recv()
            except WebSocketTimeoutException:
                continue
            for payload in decode(raw):
                if payload.startswith("~h~"):  # heartbeat: echo it or the server drops us
                    ws.send(f"~m~{len(payload)}~m~{payload}")
                    continue
                msg = json.loads(payload)
                method, params = msg.get("m"), msg.get("p", [])
                if method == "symbol_resolved":
                    info = params[2]
                elif method in ("timescale_update", "du"):
                    for key, update in params[1].items():
                        if key == "sds_1":
                            candles.update((row["v"][0], row["v"]) for row in update.get("s", []))
                        elif key in plots:
                            plots[key].update((row["v"][0], row["v"]) for row in update.get("st", []))
                elif method in ("series_completed", "study_completed"):
                    waiting.discard(params[1])
                elif method == "study_error":
                    study = studies[list(plots).index(params[1])]
                    raise ValueError(f"TradingView could not compute {study.label}: {study_error(params[3])}")
                elif method == "symbol_error":
                    reason = params[2] if len(params) > 2 else "no reason given"
                    if reason == "invalid symbol":
                        raise NotFound(f"TradingView has no symbol {ticker}")
                    if reason == "permission denied":  # e.g. MCX: the snapshot is public, the bars are not
                        raise TradingViewError(f"TradingView only gives {ticker} price history to signed-in accounts")
                    raise TradingViewError(f"TradingView refused {ticker}: {reason}")
                elif method in ERRORS:
                    raise TradingViewError(f"TradingView refused {ticker} {resolution}: {method} {params[1:]}")
    except (WebSocketException, OSError) as exc:
        raise TradingViewError(f"TradingView data feed failed for {ticker}: {exc}") from exc
    finally:
        ws.close()
    return info, candles, plots


def history(
    ticker: str,
    interval: str = "1D",
    bars: int = 250,
    timeout: float = 30,
    indicators: Sequence[str] = (),
) -> dict:
    """The most recent `bars` candles for `ticker`, oldest first.

    Daily and longer bars are dated in the exchange's timezone; intraday bars carry the bar's
    opening time with that timezone's offset. Each entry of `indicators` ("RSI", "SMA(200)",
    "PUB;175") adds its values to every bar, under the column names listed in the result.
    """
    resolution = to_resolution(interval)
    studies = load_indicators(indicators)
    feeds = [WIDGET_FEED] if studies else [WIDGET_FEED, DATA_FEED]
    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        try:
            info, candles, plots = _stream(feeds[attempt % len(feeds)], ticker, resolution, bars, studies, deadline)
            break
        except _Stalled:
            attempt += 1  # a new connection is routed to another server; plain requests also switch feed

    zone = _zone(info.get("timezone"))
    intraday = resolution.isdigit()
    out = []
    for ts in sorted(candles):
        _, o, h, l, c, *rest = candles[ts]
        when = datetime.fromtimestamp(ts, zone)
        bar = {
            "time": when.isoformat() if intraday else when.date().isoformat(),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": rest[0] if rest else None,
        }
        for study_id, study in zip(plots, studies):
            row = plots[study_id].get(ts, [])
            for pos, column in study.columns.items():
                value = row[pos] if pos < len(row) else None
                bar[column] = value if isinstance(value, (int, float)) and value != NA else None
        out.append(bar)
    return {
        "interval": resolution,
        "timezone": info.get("timezone"),
        "currency": info.get("currency_code"),
        "indicators": [study.to_dict() for study in studies],
        "bars": out,
    }
