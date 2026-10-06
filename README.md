# TradingView entity data

Give it an entity name, get that entity's TradingView data: quote, fundamentals, analyst view,
technical indicators and OHLCV price history.

```bash
.venv/Scripts/python -m tvdata "Reliance Industries"
```

## Setup

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -r requirements.txt
```

## Use

| Want | Command |
| --- | --- |
| Readable report | `python -m tvdata "HDFC Bank"` |
| Everything as JSON | `python -m tvdata "HDFC Bank" --json` |
| Save JSON + bars CSV | `python -m tvdata "HDFC Bank" --out out` |
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

data = get_entity_data("State Bank of India", interval="1W", bars=104)
data["ticker"]                                  # "NSE:SBIN"
data["snapshot"]["valuation"]["market_cap_basic"]
data["history"]["bars"][-1]                     # {"time", "open", "high", "low", "close", "volume"}
```

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
history          interval, timezone, currency, bars[]
```

Snapshot keys are TradingView's own field names (`price_earnings_ttm`, `Recommend.All`, ...); the
full list with labels is `FIELDS` in `tvdata/snapshot.py`. Fields TradingView has no value for are
left out, so an index has no `valuation` block. Money is in the listing's currency.

## How it works

| Step | File | Endpoint |
| --- | --- | --- |
| Name → symbol | `tvdata/search.py` | `symbol-search.tradingview.com/symbol_search/v3` |
| Snapshot | `tvdata/snapshot.py` | `scanner.tradingview.com/global/scan` (screener backend) |
| Price history | `tvdata/history.py` | `wss://data.tradingview.com/socket.io/websocket` (chart feed) |
| CLI | `tvdata/cli.py` | |

```bash
.venv/Scripts/python -m unittest discover -s tests
```

The tests cover the offline parts (wire format, interval parsing, search-row mapping). Nothing
mocks TradingView; run the CLI to check the live path.

## Known limits

- TradingView has no public data API. These are the endpoints its website calls, used without
  logging in. They are undocumented, can change without notice, and TradingView's terms of use
  restrict automated collection, so keep this to low-volume personal use.
- Not logged in means delayed exchange data (NSE/BSE: 15 minutes; `quote.update_mode` says which)
  and shallow intraday history: about 5,000 bars per request (roughly 3 months of 5-minute bars).
  Daily bars go all the way back (`NSE:RELIANCE` returns ~7,900, from 1994).
- It does not read saved chart layouts (`tradingview.com/chart/<id>/`): those are private to the
  account that made them. Drawings, indicators and settings on a layout are not available here.
- The top search hit is not always the entity you meant. Check `match` / `other_matches`.
- Values are whatever TradingView reports. Some symbols have gaps (for example no quarterly
  balance sheet), and derived figures such as enterprise value inherit them.
