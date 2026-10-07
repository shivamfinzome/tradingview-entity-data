# TradingView entity data

When the user gives an entity name and wants its TradingView data, run the tool and report from
its output; do not answer from memory.

```bash
.venv/Scripts/python -m tvdata "<entity name>" --json
```

- State which ticker the name resolved to. If `other_matches` holds a plausible alternative
  (another listing or a demerged company), say so.
- `--list` shows candidates without fetching. A ticker such as `NSE:TMCV` skips the search.
- When the user names an indicator, add `-i` per indicator (`-i RSI -i "SMA(200)"`); its values
  become columns on the bars. `--find-indicator TEXT` lists matches, ids and inputs. Say which
  indicator each name resolved to (`history.indicators`).
- Exchange data is delayed when not logged in; `snapshot.quote.update_mode` says by how much.
- Tests: `.venv/Scripts/python -m unittest discover -s tests` (offline only).
- Web page: `.venv/Scripts/python -m uvicorn tvdata.web:app --port 8770`, one file at
  `tvdata/static/index.html`. Restart the server after changing Python; the HTML is read per request.
- Hosted copies are locked with `TVDATA_PASSWORD` (see Hosting in the README). Never write a real
  password into the repo; `.env` is git-ignored and `.env.example` holds only the names.
- Field names and labels live in `FIELDS` in `tvdata/snapshot.py`. TradingView returns null for
  unknown field names instead of an error, so check a new field against a real symbol.
