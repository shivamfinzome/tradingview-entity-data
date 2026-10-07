"""TradingView indicators, computed by TradingView and added to the price history as columns.

An indicator is named the way TradingView names it: a built-in by short or full name ("RSI",
"Bollinger Bands"), a community script by its title, or either one by id ("STD;RSI", "PUB;175").
Inputs go in brackets: "SMA(200)", "BB(20, 2)", "RSI(source=hlc3)", "STD;MACD(in_1=8)".
"""
from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from urllib.parse import quote

import requests

from ._http import HEADERS, TIMEOUT, NotFound, TradingViewError

LIST_URL = "https://pine-facade.tradingview.com/pine-facade/list/"
TRANSLATE_URL = "https://pine-facade.tradingview.com/pine-facade/translate/{id}/last"
COMMUNITY_URL = "https://www.tradingview.com/pubscripts-suggest-json/"

STUDY_TYPE = "Script@tv-scripting-101!"
NA = 1e100  # how TradingView sends "no value on this bar"
ID_RE = re.compile(r"^(STD|PUB|USER);\S+$")
SPEC_RE = re.compile(r"^\s*(.+?)\s*(?:\((.*)\))?\s*$", re.S)
INTERNAL_INPUTS = {"text", "pineId", "pineVersion"}  # filled in by us, never by the caller
NUMERIC = {"integer", "float"}


@dataclass
class IndicatorMatch:
    id: str  # "STD;RSI", "PUB;175"
    name: str  # "Relative strength index"
    short: str  # "RSI"
    author: str | None = None  # None for TradingView's own built-ins

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Indicator:
    id: str
    name: str
    short: str
    label: str  # "RSI 14": the short name plus the inputs TradingView shows in its chart legend
    inputs: list[dict]  # user-facing inputs: id, name, type, value, default, options, shown
    columns: dict[int, str]  # position of a plot in a study row -> column name
    payload: dict = field(repr=False)  # the create_study argument

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "short": self.short, "label": self.label,
                "inputs": self.inputs, "columns": list(self.columns.values())}


def _get_json(url: str, **params):
    resp = requests.get(url, params=params or None, headers=HEADERS, timeout=TIMEOUT)
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, None


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9%]+", "", text.lower())


@lru_cache(maxsize=1)
def builtins() -> tuple[IndicatorMatch, ...]:
    """TradingView's own indicators (not strategies or libraries)."""
    status, rows = _get_json(LIST_URL, filter="standard")
    if status != 200 or not isinstance(rows, list):
        raise TradingViewError(f"could not list TradingView's built-in indicators: HTTP {status}")
    return tuple(
        IndicatorMatch(id=row["scriptIdPart"], name=html.unescape(row["scriptName"]),
                       short=(row.get("extra") or {}).get("shortDescription") or row["scriptName"])
        for row in rows
        if (row.get("extra") or {}).get("kind") == "study"
    )


def _rank(match: IndicatorMatch, wanted: str) -> int | None:
    """Lower is better; None is no match. Exact short name beats exact name beats a partial name."""
    short, name, tail = _norm(match.short), _norm(match.name), _norm(match.id.split(";", 1)[1])
    if wanted == short:
        return 0
    if wanted in (name, tail):
        return 1
    if name.startswith(wanted) or short.startswith(wanted):
        return 2
    if wanted in name:
        return 3
    return None


def search(text: str, limit: int = 10) -> list[IndicatorMatch]:
    """Indicators matching `text`: built-ins first (best match first), then community scripts."""
    wanted = _norm(text)
    if not wanted:
        return []
    ranked = [(rank, len(m.name), m) for m in builtins() if (rank := _rank(m, wanted)) is not None]
    found = [m for _, _, m in sorted(ranked, key=lambda item: item[:2])]
    if len(found) < limit:
        status, body = _get_json(COMMUNITY_URL, search=text)
        if status != 200 or not isinstance(body, dict):
            raise TradingViewError(f"TradingView's community script search failed: HTTP {status}")
        for row in body.get("results", []):
            if (row.get("extra") or {}).get("kind") != "study":
                continue
            name = html.unescape(row.get("scriptName") or "")
            found.append(IndicatorMatch(id=row["scriptIdPart"], name=name, short=row.get("shortTitle") or name,
                                        author=(row.get("author") or {}).get("username")))
    return found[:limit]


def parse_spec(spec: str) -> tuple[str, list[str], dict[str, str]]:
    """'BB(20, 2, source=hl2)' -> ('BB', ['20', '2'], {'source': 'hl2'})."""
    m = SPEC_RE.match(spec.strip())
    if not m:
        raise ValueError(f"cannot read the indicator {spec!r}")
    args, kwargs = [], {}
    for part in filter(None, (p.strip() for p in (m.group(2) or "").split(","))):
        key, sep, value = part.partition("=")
        if sep:
            kwargs[key.strip()] = value.strip()
        else:
            args.append(part)
    return m.group(1), args, kwargs


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _coerce(inp: dict, raw: str):
    """Turn the text a caller typed into the type the input wants."""
    kind, name = inp["type"], inp["name"] or inp["id"]
    if kind in NUMERIC:
        value = _number(raw)
        if value is None or (kind == "integer" and value != int(value)):
            raise ValueError(f"{name} needs {'a whole number' if kind == 'integer' else 'a number'}, not {raw!r}")
        return int(value) if kind == "integer" else value
    if kind == "bool":
        if raw.lower() in ("true", "yes", "on", "1"):
            return True
        if raw.lower() in ("false", "no", "off", "0"):
            return False
        raise ValueError(f"{name} needs true or false, not {raw!r}")
    options = inp.get("options")
    if options:
        for option in options:
            if str(option).lower() == raw.lower():
                return option
        raise ValueError(f"{name} must be one of: {', '.join(map(str, options))}")
    return raw


def _pick_input(inputs: list[dict], shown: set[str], key: str) -> dict:
    """The input a caller means by `key`: its id, its name, or a distinctive part of its name.

    Inputs in the chart legend win, so RSI's "length" is the RSI length, not its smoothing length.
    """
    wanted = _norm(key)
    for pool in ([i for i in inputs if i["id"] in shown], inputs):
        exact = [i for i in pool if wanted in (_norm(i["name"]), _norm(i["id"]))]
        if exact:
            return exact[0]
        partial = [i for i in pool if wanted and wanted in _norm(i["name"])]
        if len(partial) == 1:
            return partial[0]
    names = ", ".join(f"{i['name']} ({i['id']})" for i in inputs if i["name"])
    raise ValueError(f"no single input matches {key!r}. Inputs: {names}")


def _plain(value) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


def build(script: dict, args: list[str] = (), kwargs: dict[str, str] | None = None) -> Indicator:
    """Indicator from TradingView's script definition, with the caller's input values applied.

    Positional values fill the numeric inputs in order, which is the order of the numbers in
    TradingView's legend: MACD(12, 26, 9), BB(20, 2), Supertrend(10, 3).
    """
    meta = script["metaInfo"]
    short = meta.get("shortDescription") or meta.get("description") or meta["scriptIdPart"]
    declared = [i for i in meta["inputs"] if i["id"] not in INTERNAL_INPUTS]
    visible = [i for i in declared if not i.get("isHidden")]
    # Built-ins flag which inputs the chart legend shows; community scripts flag none, so show all.
    flagged = any("display" in i for i in visible)
    shown = {i["id"] for i in visible if not flagged or i.get("display")}

    values = {i["id"]: i.get("defval") for i in declared}
    changed: set[str] = set()
    numeric = [i for i in visible if i["id"] in shown and i["type"] in NUMERIC]
    if len(args) > len(numeric):
        raise ValueError(f"{short} has {len(numeric)} numeric legend inputs, got {len(args)} numbers: {', '.join(args)}")
    for inp, raw in zip(numeric, args):
        if _number(raw) is None:
            raise ValueError(f"{raw!r} is not a number; write other inputs as name=value")
        values[inp["id"]] = _coerce(inp, raw)
        changed.add(inp["id"])
    for key, raw in (kwargs or {}).items():
        inp = _pick_input(visible, shown, key)
        values[inp["id"]] = _coerce(inp, raw)
        changed.add(inp["id"])

    inputs, legend = [], [short]
    for inp in visible:
        value = values[inp["id"]]
        in_legend = inp["id"] in shown and inp["type"] in NUMERIC
        if in_legend or (inp["id"] in changed and value != inp.get("defval")):
            legend.append(_plain(value))
        inputs.append({"id": inp["id"], "name": inp["name"], "type": inp["type"], "value": value,
                       "default": inp.get("defval"), "options": inp.get("options"), "shown": inp["id"] in shown})
    label = " ".join(legend)

    # A study row is [time, plot_0, plot_1, ...]. Keep the plots a chart would draw as a series.
    lines = [(n + 1, meta["styles"].get(plot["id"], {})) for n, plot in enumerate(meta["plots"]) if plot["type"] == "line"]
    lines = [(pos, style) for pos, style in lines if not style.get("isHidden")]
    columns: dict[int, str] = {}
    for pos, style in lines:
        title = (style.get("title") or "").strip()
        name = label if len(lines) == 1 or _norm(title) == _norm(short) else f"{label} {title}".strip()
        taken, n = set(columns.values()), 2
        unique = name
        while unique in taken:
            unique, n = f"{name} {n}", n + 1
        columns[pos] = unique
    if not columns:
        raise ValueError(f"{meta.get('description') or short} draws no value series, so it has nothing to add as a column")

    payload = {"text": script["ilTemplate"], "pineId": meta["scriptIdPart"], "pineVersion": meta["pine"]["version"]}
    for n, inp in enumerate(declared):
        payload[inp["id"]] = {"v": n if inp["type"] == "color" else values[inp["id"]],
                              "f": bool(inp.get("isFake")), "t": inp["type"]}
    return Indicator(id=meta["scriptIdPart"], name=meta.get("description") or short, short=short, label=label,
                     inputs=inputs, columns=columns, payload=payload)


def resolve(name: str) -> str:
    """Indicator id for a name, short name or id."""
    if ID_RE.match(name):
        return name
    matches = search(name, limit=1)
    if not matches:
        raise NotFound(f"no TradingView indicator matches {name!r}")
    return matches[0].id


@lru_cache(maxsize=64)
def _script(script_id: str) -> dict:
    status, body = _get_json(TRANSLATE_URL.format(id=quote(script_id, safe="")))
    if status == 404 or (isinstance(body, dict) and body.get("success") is False):
        raise NotFound(f"TradingView has no usable indicator {script_id} (it may be private or invite-only)")
    if status != 200 or not isinstance(body, dict) or "result" not in body:
        raise TradingViewError(f"could not load the indicator {script_id}: HTTP {status}")
    return body["result"]


def load(spec: str) -> Indicator:
    """'RSI', 'SMA(200)', 'PUB;175(in_0=30)' -> an Indicator ready to attach to a price series."""
    name, args, kwargs = parse_spec(spec)
    return build(_script(resolve(name)), args, kwargs)
