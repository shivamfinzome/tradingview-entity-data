"""Checks that need no network: wire format, interval parsing, search-row mapping, rating buckets."""
import json
import unittest

from tvdata.history import decode, encode, to_resolution
from tvdata.search import TICKER_RE, _to_match
from tvdata.snapshot import rating_label


class WireFormat(unittest.TestCase):
    def test_round_trip(self):
        frame = encode("create_series", ["cs_x", "sds_1", "s1", "sds_sym_1", "1D", 250, ""])
        self.assertTrue(frame.startswith("~m~"))
        (payload,) = decode(frame)
        self.assertEqual(json.loads(payload), {"m": "create_series", "p": ["cs_x", "sds_1", "s1", "sds_sym_1", "1D", 250, ""]})

    def test_several_payloads_in_one_message(self):
        raw = encode("a", [1]) + "~m~4~m~~h~7" + encode("b", ["~m~3~m~not a frame"])
        payloads = decode(raw)
        self.assertEqual(len(payloads), 3)
        self.assertEqual(payloads[1], "~h~7")
        self.assertEqual(json.loads(payloads[2])["p"], ["~m~3~m~not a frame"])


class Intervals(unittest.TestCase):
    def test_aliases(self):
        cases = {"1": "1", "5m": "5", "15min": "15", "1h": "60", "4H": "240", "1d": "1D", "1D": "1D", "1w": "1W", "1M": "1M", "3mo": "3M"}
        for given, expected in cases.items():
            self.assertEqual(to_resolution(given), expected, given)

    def test_rejects_garbage(self):
        for bad in ("", "daily", "7x", "h1"):
            with self.assertRaises(ValueError):
                to_resolution(bad)


class SearchRows(unittest.TestCase):
    def test_stock(self):
        m = _to_match({"symbol": "RELIANCE", "description": "Reliance Industries Limited", "type": "stock", "exchange": "NSE",
                       "source_id": "NSE", "country": "IN", "currency_code": "INR", "isin": "INE002A01018", "is_primary_listing": True})
        self.assertEqual(m.ticker, "NSE:RELIANCE")
        self.assertTrue(m.primary_listing)

    def test_prefix_wins_over_display_exchange(self):
        m = _to_match({"symbol": "BTCUSD", "type": "spot", "exchange": "Bitstamp", "source_id": "BITSTAMP", "prefix": "BITSTAMP"})
        self.assertEqual(m.ticker, "BITSTAMP:BTCUSD")

    def test_futures_use_front_contract(self):
        m = _to_match({"symbol": "HDFCBANK", "type": "futures", "exchange": "NSE", "source_id": "NSE",
                       "contracts": [{"symbol": "HDFCBANK1!"}, {"symbol": "HDFCBANK2!"}]})
        self.assertEqual(m.ticker, "NSE:HDFCBANK1!")

    def test_ticker_detection(self):
        self.assertTrue(TICKER_RE.match("NSE:RELIANCE"))
        self.assertTrue(TICKER_RE.match("nse:hdfcbank1!"))
        self.assertFalse(TICKER_RE.match("Reliance Industries"))
        self.assertFalse(TICKER_RE.match("RELIANCE"))


class Ratings(unittest.TestCase):
    def test_buckets(self):
        cases = {1: "Strong buy", 0.5: "Buy", 0.1: "Neutral", 0: "Neutral", -0.1: "Neutral", -0.27: "Sell", -0.5: "Sell", -0.51: "Strong sell"}
        for score, label in cases.items():
            self.assertEqual(rating_label(score), label, score)
        self.assertIsNone(rating_label(None))


if __name__ == "__main__":
    unittest.main()
