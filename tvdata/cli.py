"""python -m tvdata "Reliance Industries" """
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import requests

from . import TradingViewError, get_entity_data, search
from .snapshot import FIELDS

LABELS = {field: label for group in FIELDS.values() for field, label in group.items()}
LABELS["rating"] = "Technical rating"


def fmt(value) -> str:
    if isinstance(value, list):
        return ", ".join(map(str, value))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(value) >= size:
            return f"{value / size:,.2f}{suffix}"
    return f"{value:,}" if isinstance(value, int) else f"{value:,.2f}"


def print_matches(matches: list[dict]) -> None:
    width = max(len(m["ticker"]) for m in matches)
    for m in matches:
        extra = " ".join(filter(None, [m["type"], m["country"], m["currency"]]))
        print(f"  {m['ticker']:<{width}}  {m['description']}  [{extra}]")


def print_report(data: dict, tail: int = 5) -> None:
    match, snap = data["match"], data["snapshot"]
    print(f"{match['description']}  ({data['ticker']})")
    if match.get("currency"):
        print(f"Prices and financials in {match['currency']}")

    for group, values in snap.items():
        print(f"\n{group.capitalize()}")
        for field, value in values.items():
            print(f"  {LABELS.get(field, field):<36} {fmt(value)}")

    hist = data.get("history")
    if hist and hist["bars"]:
        bars = hist["bars"]
        size = hist["interval"] + ("m" if hist["interval"].isdigit() else "")
        print(f"\nHistory: {len(bars)} x {size} bars, {bars[0]['time']} .. {bars[-1]['time']}"
              f" (last {min(tail, len(bars))} shown; --json or --out for all)")
        print(f"  {'time':<26}{'open':>12}{'high':>12}{'low':>12}{'close':>12}{'volume':>12}")
        for bar in bars[-tail:]:
            volume = "" if bar["volume"] is None else fmt(bar["volume"])
            print(f"  {bar['time']:<26}{bar['open']:>12,.2f}{bar['high']:>12,.2f}{bar['low']:>12,.2f}"
                  f"{bar['close']:>12,.2f}{volume:>12}")

    if data["other_matches"]:
        print("\nOther matches (re-run with one of these tickers if the pick above is wrong):")
        print_matches(data["other_matches"][:5])


def write_files(data: dict, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9]+", "_", data["ticker"]).strip("_")
    json_path = out_dir / f"{stem}.json"
    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    written = [json_path]
    hist = data.get("history")
    if hist and hist["bars"]:
        csv_path = out_dir / f"{stem}_{hist['interval']}.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(hist["bars"][0]))
            writer.writeheader()
            writer.writerows(hist["bars"])
        written.append(csv_path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tvdata",
        description="Give an entity name, get its TradingView quote, fundamentals, technicals and price history.",
    )
    parser.add_argument("name", nargs="+", help='entity name ("Reliance Industries") or exact ticker (NSE:RELIANCE)')
    parser.add_argument("--exchange", help="only match on this exchange, e.g. NSE, BSE, NASDAQ")
    parser.add_argument("--type", dest="asset_type", help="only match this type: stock, index, futures, forex, crypto, fund, bond")
    parser.add_argument("--country", default="IN", help="rank listings from this country first (default: IN)")
    parser.add_argument("--interval", default="1D", help="bar size: 1m 5m 15m 1h 4h 1D 1W 1M (default: 1D)")
    parser.add_argument("--bars", type=int, default=250, help="how many bars of history (default: 250)")
    parser.add_argument("--no-history", action="store_true", help="skip price history")
    parser.add_argument("--list", action="store_true", help="only list the symbols the name matches")
    parser.add_argument("--json", action="store_true", help="print everything as JSON")
    parser.add_argument("--out", type=Path, metavar="DIR", help="also save <ticker>.json and the bars as CSV in DIR")
    args = parser.parse_args(argv)

    # Company names are not always ASCII; do not let a legacy Windows console crash the report.
    sys.stdout.reconfigure(errors="replace")
    name = " ".join(args.name)
    try:
        if args.list:
            matches = search(name, exchange=args.exchange, asset_type=args.asset_type, country=args.country, limit=20)
            if not matches:
                raise TradingViewError(f"no TradingView symbol found for {name!r}")
            if args.json:
                print(json.dumps([m.to_dict() for m in matches], indent=2))
            else:
                print_matches([m.to_dict() for m in matches])
            return 0

        data = get_entity_data(
            name,
            exchange=args.exchange,
            asset_type=args.asset_type,
            country=args.country,
            interval=args.interval,
            bars=args.bars,
            include_history=not args.no_history,
        )
    except (TradingViewError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"error: could not reach TradingView: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print_report(data)
    if args.out:
        for path in write_files(data, args.out):
            print(f"saved {path}", file=sys.stderr)
    return 0
