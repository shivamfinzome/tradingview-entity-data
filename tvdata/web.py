"""Web page for the lookup: python -m uvicorn tvdata.web:app --port 8770

Settings come from the environment, so the same code runs open on your own machine and locked
on a server:
  TVDATA_PASSWORD         turns the login on (HTTP Basic); unset means no login
  TVDATA_USER             user name for that login (default: tvdata)
  TVDATA_RATE_PER_MINUTE  lookups sent to TradingView per minute, all visitors together (default: 120)
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import requests
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse

from . import NotFound, TradingViewError, get_entity_data, history, indicators, search
from .guard import Cache, RateLimit, credentials_ok
from .snapshot import EPOCH_FIELDS, LABELS, PERCENT_FIELDS

STATIC = Path(__file__).parent / "static"
USER = os.environ.get("TVDATA_USER", "tvdata")
PASSWORD = os.environ.get("TVDATA_PASSWORD", "")

Bars = Annotated[int, Query(ge=1, le=20000)]
Text = Annotated[str, Query(min_length=1, max_length=200)]
# Repeat the parameter for several: ?indicator=RSI&indicator=SMA(200)
Indicators = Annotated[list[str] | None, Query()]

limit = RateLimit(int(os.environ.get("TVDATA_RATE_PER_MINUTE", "120")))
cache = Cache()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not PASSWORD:
        logging.getLogger("uvicorn.error").warning(
            "TVDATA_PASSWORD is not set: anyone who can reach this server can use it."
        )
    yield


app = FastAPI(title="TradingView entity data", lifespan=lifespan)


@app.middleware("http")
async def guard(request: Request, call_next):
    """Ask for the login when one is configured, and mark every answer as private."""
    if PASSWORD and request.url.path != "/healthz":
        if not credentials_ok(request.headers.get("authorization"), USER, PASSWORD):
            return Response("Sign in to use this page.", status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="TradingView data", charset="UTF-8"'})
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


def _call(fn, *args, ttl: float = 0, **kwargs):
    """Run a lookup: from the cache if it is fresh, within the request budget if it is not.

    Failures become the status codes the page tells apart.
    """
    key = (fn.__module__, fn.__qualname__, args, tuple(sorted(kwargs.items())))
    hit, value = cache.get(key) if ttl else (False, None)
    if hit:
        return value
    if not limit.allow():
        raise HTTPException(429, "too many lookups in the last minute; wait a little and try again")
    try:
        value = fn(*args, **kwargs)
    except NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (TradingViewError, requests.RequestException) as exc:
        raise HTTPException(502, str(exc)) from exc
    if ttl:
        cache.put(key, value, ttl)
    return value


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    """For the host's health check; needs no login and touches nothing."""
    return {"ok": True}


@app.get("/api/fields")
def api_fields() -> dict:
    """Label for every snapshot field, and which fields are dates or percentages."""
    return {"labels": LABELS, "dates": sorted(EPOCH_FIELDS), "percent": sorted(PERCENT_FIELDS)}


@app.get("/api/search")
def api_search(q: Text, exchange: str | None = None, type: str | None = None, country: str = "IN") -> list[dict]:
    return [m.to_dict() for m in _call(search, q, exchange=exchange, asset_type=type, country=country, ttl=600)]


@app.get("/api/entity")
def api_entity(
    name: Text,
    exchange: str | None = None,
    type: str | None = None,
    country: str = "IN",
    interval: str = "1D",
    bars: Bars = 250,
    with_history: bool = True,
    indicator: Indicators = None,
) -> dict:
    return _call(
        get_entity_data, name, exchange=exchange, asset_type=type, country=country, interval=interval, bars=bars,
        include_history=with_history, indicators=tuple(indicator or ()), ttl=60,
    )


@app.get("/api/history")
def api_history(ticker: Text, interval: str = "1D", bars: Bars = 250, indicator: Indicators = None) -> dict:
    return _call(history, ticker, interval=interval, bars=bars, indicators=tuple(indicator or ()), ttl=60)


@app.get("/api/indicators")
def api_indicators(q: Text) -> list[dict]:
    """Indicators whose name matches: TradingView's built-ins first, then community scripts."""
    return [m.to_dict() for m in _call(indicators.search, q, ttl=3600)]


@app.get("/api/indicator")
def api_indicator(spec: Text) -> dict:
    """One indicator by name or id, with its inputs and the columns it adds."""
    return _call(indicators.load, spec, ttl=600).to_dict()
