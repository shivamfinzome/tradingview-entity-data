# TradingView entity data

Give it an entity name, get that entity's TradingView data: OHLCV price history with any
TradingView indicators as extra columns, plus the quote, fundamentals, analyst view and
technical ratings.

```bash
.venv/Scripts/python -m tvdata "Reliance Industries" -i RSI -i "SMA(200)"
```

## Setup

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -r requirements.txt
```

## Web page

```bash
.venv/Scripts/python -m uvicorn tvdata.web:app --port 8770
```

Then open http://localhost:8770. Type a name (suggestions come from TradingView's search), pick
the bar size and number of bars, add indicators, and export the price history as CSV. The page
shows which symbol the name matched and the latest 10 bars; the export has all of them. Each
indicator adds one column per line it draws; its main inputs can be changed on the page. A lookup
is a link, e.g. `http://localhost:8770/?q=HDFC%20Bank`.

The JSON routes behind the page can be called directly:

| Route | Returns |
| --- | --- |
| `/api/entity?name=` | match, snapshot and history (`with_history=false` skips the bars) |
| `/api/history?ticker=&interval=&bars=&indicator=` | bars; repeat `indicator` for several |
| `/api/search?q=` | symbols matching a name |
| `/api/indicators?q=` | indicators matching a name |
| `/api/indicator?spec=` | one indicator: its inputs and the columns it adds |
| `/api/fields` | labels for the snapshot fields |

## Hosting

The page needs no TradingView account. To put it on a server, give it a login and let it listen
on the network:

| Setting | Effect |
| --- | --- |
| `TVDATA_PASSWORD` | Turns the login on (HTTP Basic) for the page and every `/api` route. Unset means no login, and the server logs a warning at start. |
| `TVDATA_USER` | User name for that login. Default `tvdata`. |
| `TVDATA_RATE_PER_MINUTE` | Lookups sent to TradingView per minute, all visitors together. Default 120. Past it the page says to wait. |
| `PORT` | Port inside the container. Default 8770. |

With Docker (`.env.example` lists the settings; copy it to `.env` and fill in a password):

```bash
docker build -t tvdata .
```

```bash
docker run --env-file .env -p 8770:8770 tvdata
```

Without Docker, set the variables in the shell and run:

```bash
.venv/Scripts/python -m uvicorn tvdata.web:app --host 0.0.0.0 --port 8770
```

- Put HTTPS in front (your host's TLS or a reverse proxy). HTTP Basic sends the password with
  every request, readable by anyone on the path if the connection is plain HTTP.
- Run one process. The request budget and the cache (60 seconds for bars, 10 minutes for name
  searches) live in memory, so several workers would each get their own.
- `/healthz` answers without a login, for the host's health check.
- Everyone signed in shares one password. For per-person accounts, put the app behind your
  identity provider instead.
- TradingView's terms and the exchanges' data rules still apply to a hosted copy; see Known
  limits. Keep it to people inside your team.

## Command line

| Want | Command |
| --- | --- |
| Readable report | `python -m tvdata "HDFC Bank"` |
| Everything as JSON | `python -m tvdata "HDFC Bank" --json` |
| Save JSON + bars CSV | `python -m tvdata "HDFC Bank" --out out` |
| Indicator columns | `python -m tvdata "HDFC Bank" -i RSI -i "BB(20, 2)" --out out` |
| Find an indicator and its inputs | `python -m tvdata --find-indicator supertrend` |
| See what a name matches | `python -m tvdata "tata motors" --list` |
| Exact symbol, no search | `python -m tvdata NSE:TMCV` |
| Restrict the match | `python -m tvdata Infosys --exchange BSE` or `--type stock` |
| Other bar sizes / depth | `--interval 1h --bars 500` (`1m 5m 15m 1h 4h 1D 1W 1M`) |
| Snapshot only | `--no-history` |

The name is resolved with TradingView's own symbol search and the top hit is used, with Indian
listings ranked first (`--country` changes that). The report ends with the runners-up, so a wrong
pick is visible: "Tata Motors" resolves to `NSE:TMPV`, and `NSE:TMCV` is listed right below it.

From Python:

```python
from tvdata import get_entity_data

data = get_entity_data("State Bank of India", interval="1W", bars=104, indicators=["RSI", "EMA(50)"])
data["ticker"]                                  # "NSE:SBIN"
data["snapshot"]["valuation"]["market_cap_basic"]
data["history"]["bars"][-1]                     # time, open, high, low, close, volume, "RSI 14", ..., "EMA 50"
```

## Indicators

Indicators are TradingView's own, computed by TradingView on the bars you asked for, so the
numbers are the ones its chart shows. Name one the way TradingView does:

| You write | Meaning |
| --- | --- |
| `RSI`, `MACD`, `BB`, `Supertrend` | a built-in, by its short name |
| `Bollinger Bands` | a built-in, by its full name |
| `Squeeze Momentum Indicator [LazyBear]` | a community script, by title (top search hit) |
| `STD;RSI`, `PUB;175` | either kind, by id (what `--find-indicator` prints) |
| `SMA(200)`, `BB(20, 2)`, `MACD(12, 26, 9)` | numbers fill the legend inputs, in legend order |
| `RSI(source=hlc3)`, `STD;MACD(in_1=8)` | any input by name or by id |

Column names are the legend text plus the plot title: `RSI` adds `RSI 14` and
`RSI 14 RSI-based MA`; `BB(20, 2)` adds `BB 20 2 Basis`, `BB 20 2 Upper`, `BB 20 2 Lower`.
Bars where an indicator has no value are left empty. `history.indicators` lists what each name
resolved to, its inputs and its columns. At most 10 indicators per request.

## What comes back

```
query, ticker
match            ticker, symbol, exchange, description, type, country, currency, isin
other_matches    same shape, the next search hits
snapshot
  profile        name, sector, industry, ISIN, currency, timezone
  quote          last price, change, day range, volume, 52-week and all-time range, data mode
  valuation      market cap, EV, P/E, P/B, P/S, EPS, dividend, beta, share counts
  financials     revenue, profit, margins, returns, debt, assets
  analysts       consensus score, price targets, earnings dates
  performance    1W .. all-time returns, volatility
  technicals     TradingView rating, RSI, MACD, stochastic, ADX, moving averages, Bollinger
history          interval, timezone, currency, indicators[], bars[]
history_error    why there are no bars, when TradingView refuses them (null otherwise)
```

Snapshot keys are TradingView's own field names (`price_earnings_ttm`, `Recommend.All`, ...); the
full list with labels is `FIELDS` in `tvdata/snapshot.py`. Fields TradingView has no value for are
left out, so an index has no `valuation` block. Money is in the listing's currency.

## How it works

| Step | File | Endpoint |
| --- | --- | --- |
| Name → symbol | `tvdata/search.py` | `symbol-search.tradingview.com/symbol_search/v3` |
| Snapshot | `tvdata/snapshot.py` | `scanner.tradingview.com/global/scan` (screener backend) |
| Price history, indicator values | `tvdata/history.py` | `wss://widgetdata.tradingview.com/socket.io/websocket` (chart-widget feed), falling back to `wss://data.tradingview.com/socket.io/websocket` (chart-page feed) for bars |
| Indicator lookup | `tvdata/indicators.py` | `pine-facade.tradingview.com` (built-ins, script definitions), `www.tradingview.com/pubscripts-suggest-json` (community search) |
| CLI | `tvdata/cli.py` | |
| Web page | `tvdata/web.py`, `tvdata/static/index.html` | FastAPI serving one HTML file, no build step |
| Login, request budget, cache | `tvdata/guard.py` | |

```bash
.venv/Scripts/python -m unittest discover -s tests
```

The tests cover the offline parts (wire format, interval parsing, search-row mapping, indicator
specs and column naming, the hosting login, budget and cache). Nothing mocks TradingView; run the
CLI to check the live path.

## Known limits

- TradingView has no public data API. These are the endpoints its website calls, used without
  logging in. They are undocumented, can change without notice, and TradingView's terms of use
  restrict automated collection, so keep this to low-volume personal use.
- Not logged in means delayed exchange data (NSE/BSE: 15 minutes; `quote.update_mode` says which)
  and shallow intraday history: about 5,000 bars per request (roughly 3 months of 5-minute bars).
  Daily bars go all the way back (`NSE:RELIANCE` returns ~7,900, from 1994).
- Bars and indicators come from the feed behind TradingView's embeddable chart widget. The feed
  behind its own chart page refuses indicators without a login, and some of its servers sit on a
  request for about a minute. A request that gets no bars within 6 seconds is retried on a new
  connection; plain bar requests alternate between the two feeds. The feeds return the same daily
  bars, but can differ by a few ticks on the current day's intraday bars. Private and invite-only
  scripts cannot be used.
- An indicator name picks the best match: built-ins first, then the top community result. Check
  `history.indicators` (or the line the CLI prints) for what it resolved to; "bollinger" alone
  matches "Bollinger bars" before "Bollinger Bands". A community title containing brackets `( )`
  is read as inputs, so use its `PUB;` id.
- It does not read saved chart layouts (`tradingview.com/chart/<id>/`): those are private to the
  account that made them. Drawings, indicators and settings on a layout are not available here.
- The top search hit is not always the entity you meant. Check `match` / `other_matches`.
- Search lists some symbols TradingView has no data for (exchange-traded bonds such as
  `NSE:708TML28.N0`), and some feeds give a snapshot but no bars without a login (MCX, e.g.
  `MCX:GOLD1!`). The first is reported as not found; the second returns the snapshot with
  `history_error` set.
- Values are whatever TradingView reports. Some symbols have gaps (for example no quarterly
  balance sheet), and derived figures such as enterprise value inherit them.
