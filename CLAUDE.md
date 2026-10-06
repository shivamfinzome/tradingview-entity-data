# TradingView entity data

When the user gives an entity name and wants its TradingView data, run the tool and report from
its output; do not answer from memory.

```bash
.venv/Scripts/python -m tvdata "<entity name>" --json
```

- State which ticker the name resolved to. If `other_matches` holds a plausible alternative
  (another listing or a demerged company), say so.
- `--list` shows candidates without fetching. A ticker such as `NSE:TMCV` skips the search.
- Exchange data is delayed when not logged in; `snapshot.quote.update_mode` says by how much.
- Tests: `.venv/Scripts/python -m unittest discover -s tests` (offline only).
- Field names and labels live in `FIELDS` in `tvdata/snapshot.py`. TradingView returns null for
  unknown field names instead of an error, so check a new field against a real symbol.
