"""OHLCV bars for one symbol, read from the websocket feed that draws TradingView's charts.

Not logged in, so exchange data is delayed (NSE/BSE by 15 minutes) and intraday history stops at
about 5,000 bars. Asking for more bars than exist returns what there is.
"""
from __future__ import annotations

import json
import random
import re
import string
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from websocket import WebSocketException, create_connection

from ._http import HEADERS, ORIGIN, TIMEOUT, TradingViewError

WS_URL = "wss://data.tradingview.com/socket.io/websocket"
FRAME_RE = re.compile(r"~m~(\d+)~m~")
ERRORS = {"symbol_error", "series_error", "critical_error", "protocol_error"}


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


def history(ticker: str, interval: str = "1D", bars: int = 250, timeout: float = TIMEOUT) -> dict:
    """The most recent `bars` candles for `ticker`, oldest first.

    Daily and longer bars are dated in the exchange's timezone; intraday bars carry the bar's
    opening time with that timezone's offset.
    """
    resolution = to_resolution(interval)
    session = "cs_" + "".join(random.choices(string.ascii_lowercase, k=12))
    symbol = "=" + json.dumps({"symbol": ticker, "adjustment": "splits", "session": "regular"})

    try:
        ws = create_connection(WS_URL, origin=ORIGIN, header={"User-Agent": HEADERS["User-Agent"]}, timeout=timeout)
    except (WebSocketException, OSError) as exc:
        raise TradingViewError(f"could not open TradingView data feed: {exc}") from exc

    info: dict = {}
    rows: list[dict] = []
    try:
        ws.send(encode("set_auth_token", ["unauthorized_user_token"]))
        ws.send(encode("chart_create_session", [session, ""]))
        ws.send(encode("resolve_symbol", [session, "sds_sym_1", symbol]))
        ws.send(encode("create_series", [session, "sds_1", "s1", "sds_sym_1", resolution, bars, ""]))

        deadline = time.monotonic() + timeout
        done = False
        while not done:
            if time.monotonic() > deadline:
                raise TradingViewError(f"timed out waiting for {ticker} {resolution} bars")
            for payload in decode(ws.recv()):
                if payload.startswith("~h~"):  # heartbeat: echo it or the server drops us
                    ws.send(f"~m~{len(payload)}~m~{payload}")
                    continue
                msg = json.loads(payload)
                method, params = msg.get("m"), msg.get("p", [])
                if method == "symbol_resolved":
                    info = params[2]
                elif method == "timescale_update":
                    rows.extend(params[1].get("sds_1", {}).get("s", []))
                elif method == "series_completed":
                    done = True
                elif method in ERRORS:
                    raise TradingViewError(f"TradingView refused {ticker} {resolution}: {method} {params[1:]}")
    except (WebSocketException, OSError) as exc:
        raise TradingViewError(f"TradingView data feed failed for {ticker}: {exc}") from exc
    finally:
        ws.close()

    zone = _zone(info.get("timezone"))
    intraday = resolution.isdigit()
    out = []
    for row in rows:
        ts, o, h, l, c, *rest = row["v"]
        when = datetime.fromtimestamp(ts, zone)
        out.append({
            "time": when.isoformat() if intraday else when.date().isoformat(),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": rest[0] if rest else None,
        })
    return {
        "interval": resolution,
        "timezone": info.get("timezone"),
        "currency": info.get("currency_code"),
        "bars": out,
    }
