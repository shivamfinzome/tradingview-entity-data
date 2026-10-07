"""Indicator specs, inputs and column names, checked against a cut-down RSI definition (no network)."""
import unittest

from tvdata.history import study_error
from tvdata.indicators import IndicatorMatch, _rank, _norm, build, parse_spec

RSI = {
    "ilTemplate": "encoded-script",
    "metaInfo": {
        "scriptIdPart": "STD;RSI",
        "description": "Relative strength index",
        "shortDescription": "RSI",
        "pine": {"version": "47.0"},
        "inputs": [
            {"id": "text", "type": "text", "defval": "encoded-script", "isHidden": True, "name": "text"},
            {"id": "pineFeatures", "type": "text", "defval": "{}", "isHidden": True, "isFake": True, "name": "pineFeatures"},
            {"id": "in_0", "name": "RSI Length", "type": "integer", "defval": 14, "display": 4294967295, "isFake": True},
            {"id": "in_1", "name": "Source", "type": "source", "defval": "close", "display": 4294967295, "isFake": True,
             "options": ["open", "high", "low", "close", "hl2", "hlc3"]},
            {"id": "in_2", "name": "Calculate Divergence", "type": "bool", "defval": False, "display": 0, "isFake": True},
            {"id": "in_4", "name": "Length", "type": "integer", "defval": 14, "display": 0, "isFake": True},
        ],
        "plots": [
            {"id": "plot_0", "type": "line"},
            {"id": "plot_1", "type": "line"},
            {"id": "plot_2", "type": "line"},
            {"id": "plot_3", "type": "colorer", "target": "plot_2"},
            {"id": "plot_4", "type": "alertcondition"},
        ],
        "styles": {
            "plot_0": {"title": "RSI", "isHidden": False},
            "plot_1": {"title": "Plot", "isHidden": True},
            "plot_2": {"title": "RSI-based MA", "isHidden": False},
        },
    },
}


class Specs(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_spec("RSI"), ("RSI", [], {}))
        self.assertEqual(parse_spec(" BB(20, 2, source=hl2) "), ("BB", ["20", "2"], {"source": "hl2"}))
        self.assertEqual(parse_spec("STD;RSI(in_3=SMMA (RMA))"), ("STD;RSI", [], {"in_3": "SMMA (RMA)"}))
        self.assertEqual(parse_spec("PUB;175"), ("PUB;175", [], {}))

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            parse_spec("   ")


class Building(unittest.TestCase):
    def test_defaults(self):
        rsi = build(RSI)
        self.assertEqual((rsi.id, rsi.short, rsi.label), ("STD;RSI", "RSI", "RSI 14"))
        # value positions: [time, plot_0, plot_1, plot_2, ...]; the hidden midline is skipped
        self.assertEqual(rsi.columns, {1: "RSI 14", 3: "RSI 14 RSI-based MA"})
        self.assertEqual(rsi.payload["text"], "encoded-script")
        self.assertEqual(rsi.payload["pineId"], "STD;RSI")
        self.assertEqual(rsi.payload["pineVersion"], "47.0")
        self.assertEqual(rsi.payload["in_0"], {"v": 14, "f": True, "t": "integer"})
        self.assertEqual(rsi.payload["pineFeatures"], {"v": "{}", "f": True, "t": "text"})

    def test_positional_number_fills_the_legend_input(self):
        rsi = build(RSI, ["21"])
        self.assertEqual(rsi.payload["in_0"]["v"], 21)
        self.assertEqual(rsi.payload["in_4"]["v"], 14)
        self.assertEqual(rsi.label, "RSI 21")

    def test_named_inputs(self):
        rsi = build(RSI, [], {"length": "21", "source": "HLC3", "calculate divergence": "yes"})
        self.assertEqual(rsi.payload["in_0"]["v"], 21)  # "length" means the legend's RSI Length, not the smoothing one
        self.assertEqual(rsi.payload["in_1"]["v"], "hlc3")
        self.assertIs(rsi.payload["in_2"]["v"], True)
        self.assertEqual(rsi.label, "RSI 21 hlc3 True")

    def test_input_by_id(self):
        self.assertEqual(build(RSI, [], {"in_4": "5"}).payload["in_4"]["v"], 5)

    def test_bad_values(self):
        for args, kwargs in ((["abc"], {}), (["1", "2"], {}), ([], {"source": "vwap"}), ([], {"length": "2.5"}),
                             ([], {"nonsense": "1"}), ([], {"calculate divergence": "maybe"})):
            with self.assertRaises(ValueError, msg=(args, kwargs)):
                build(RSI, args, kwargs)

    def test_nothing_to_plot(self):
        script = {**RSI, "metaInfo": {**RSI["metaInfo"], "plots": [{"id": "plot_4", "type": "alertcondition"}]}}
        with self.assertRaises(ValueError):
            build(script)


class Matching(unittest.TestCase):
    def test_rank_order(self):
        rsi = IndicatorMatch("STD;RSI", "Relative strength index", "RSI")
        stoch = IndicatorMatch("STD;Stochastic_RSI", "Stochastic RSI", "Stoch RSI")
        self.assertEqual(_rank(rsi, _norm("rsi")), 0)
        self.assertEqual(_rank(rsi, _norm("Relative Strength Index")), 1)
        self.assertEqual(_rank(stoch, _norm("stochastic")), 2)
        self.assertEqual(_rank(stoch, _norm("rsi")), 3)
        self.assertIsNone(_rank(rsi, _norm("macd")))


class StudyErrors(unittest.TestCase):
    def test_fills_placeholders(self):
        reason = {"ctx": {"argName": "length", "value": -5.0, "bar_index": 0},
                  "error": "Error on bar {bar_index}: Invalid value of the '{argName}' argument ({value})."}
        self.assertEqual(study_error(reason), "Error on bar 0: Invalid value of the 'length' argument (-5.0).")

    def test_plain_and_coded(self):
        self.assertEqual(study_error("error in series"), "error in series")
        self.assertEqual(study_error({"ctx": {"code": "study_limit_exceeded"}}), "study_limit_exceeded")


if __name__ == "__main__":
    unittest.main()
