"""
Regression tests for the "TAM / SAM / SOM always show Insufficient data" bug.

Root cause: build_sizing() demanded perfectly clean numeric JSON for ALL four inputs. Text numbers ("60,000", "$1,500",
"20%"), bare numbers, null/0 values or a single missing input made it return "unavailable" for every level, and the sourced
market figures found by research were never used for the TAM. These tests feed it the messy shapes models really return.
"""
import os
import sys
import copy
import unittest
import pathlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import flask_login  # noqa: F401
except ImportError:
    sys.path.insert(0, "/tmp/shims")

from services.sizing import build_sizing, parse_number, pick_topdown_figure, merge_sizing_inputs
from services.evidence import extract_figures
from tests import fakes
from tests.test_pipeline import PipelineBase
from tests.test_any_idea import EXTRA

OK = {"customer_unit": "restaurants", "currency": "USD",
      "unit_count": {"value": 60000, "basis": "ai_assumption"}, "annual_revenue_per_unit": {"value": 1500},
      "serviceable_share": {"value": 0.2}, "obtainable_share": {"value": 0.03}}
FIG = {"fid": "F0", "value": 40.87e9, "currency": "USD", "year": 2025, "forecast": False, "scope": "global", "label": "Market size",
       "value_text": "$40.87 B", "source_id": "S29", "source_title": "Food Waste Management Market", "url": "https://r.example/fw",
       "reliability": "Medium", "note": "overall market"}


class TestParseNumber(unittest.TestCase):
    def test_formats(self):
        cases = {"60,000": 60000, "$1,500": 1500, "1.2 million": 1.2e6, "about 60 thousand": 60000, "2 crore": 2e7, "5 lakh": 5e5,
                 "1.5M": 1.5e6, "50-70 thousand": 60000, "2025 estimate: 60000": 60000, 3: 3, 0.2: 0.2}
        for raw, want in cases.items():
            self.assertAlmostEqual(parse_number(raw)[0], want, msg=str(raw))
        self.assertEqual(parse_number("20%"), (20.0, True))
        for bad in (None, "", "unknown", "n/a", True, [], {}):
            self.assertIsNone(parse_number(bad)[0], str(bad))


class TestMessyModelOutput(unittest.TestCase):
    def sized(self, **changes):
        raw = copy.deepcopy(OK)
        raw.update(changes)
        return build_sizing(raw, [])

    def test_text_numbers_percent_and_bare_numbers_calculate(self):
        for label, change in {"comma text": {"unit_count": {"value": "60,000"}}, "currency text": {"annual_revenue_per_unit": {"value": "$1,500"}},
                              "percent text": {"serviceable_share": {"value": "20%"}}, "bare number": {"unit_count": 60000},
                              "words": {"unit_count": {"value": "about 60 thousand"}},
                              "alias keys": {"number_of_customers": {"value": 60000}, "unit_count": None}}.items():
            r = self.sized(**change)
            self.assertEqual(r["status"], "calculated", label)
            self.assertAlmostEqual(r["tam"]["value"], 90_000_000, delta=1, msg=label)
            self.assertAlmostEqual(r["som"]["value"], 90_000_000 * 0.2 * 0.03, delta=1, msg=label)

    def test_percent_one_is_one_percent_not_hundred(self):
        r = self.sized(obtainable_share={"value": "1%"})
        self.assertAlmostEqual(r["som"]["value"], 90_000_000 * 0.2 * 0.01, delta=1)

    def test_range_only_uses_midpoint(self):
        r = self.sized(unit_count={"low": 40000, "high": 80000})
        self.assertAlmostEqual(r["tam"]["value"], 60000 * 1500, delta=1)
        self.assertTrue(any("midpoint" in c for c in r["cautions"]))

    def test_one_missing_input_no_longer_blanks_everything(self):
        raw = copy.deepcopy(OK)
        del raw["obtainable_share"]
        r = build_sizing(raw, [])
        self.assertEqual(r["status"], "partial")
        self.assertIn("tam", r)
        self.assertIn("sam", r)
        self.assertNotIn("som", r)
        self.assertIn("Insufficient data for SOM", r["missing"]["som"])

    def test_genuinely_missing_data_is_still_insufficient(self):
        r = build_sizing({"unit_count": None, "annual_revenue_per_unit": 0}, [])
        self.assertEqual(r["status"], "unavailable")
        self.assertIn("Insufficient data", r["reason"])
        self.assertNotIn("tam", r)

    def test_unusable_inputs_are_not_replaced_by_made_up_numbers(self):
        r = build_sizing({"unit_count": "unknown", "annual_revenue_per_unit": "n/a", "serviceable_share": None, "obtainable_share": 0}, [])
        self.assertEqual((r["status"], r.get("tam")), ("unavailable", None))


class TestTopDownFromSourcedFigure(unittest.TestCase):
    def test_sourced_figure_becomes_tam_when_bottom_up_inputs_are_unusable(self):
        raw = {"currency": "USD", "unit_count": None, "annual_revenue_per_unit": "n/a",
               "topdown_serviceable_share": {"value": "5%", "low": "3%", "high": "8%"}, "obtainable_share": {"value": 0.04}}
        r = build_sizing(raw, [], figures=[FIG])
        self.assertEqual((r["status"], r["approach"]), ("calculated", "top_down"))
        self.assertAlmostEqual(r["tam"]["value"], 40.87e9)
        self.assertAlmostEqual(r["sam"]["value"], 40.87e9 * 0.05, delta=1)
        self.assertAlmostEqual(r["som"]["value"], 40.87e9 * 0.05 * 0.04, delta=1)
        self.assertEqual(r["tam_source"]["url"], "https://r.example/fw")
        self.assertIn("a sourced figure, not an estimate", r["formula"]["tam"])
        self.assertEqual(r["assumptions"][0]["basis"], "sourced")          # the figure is listed as sourced
        self.assertTrue(all(a["basis"] == "ai_assumption" for a in r["assumptions"][1:]))
        self.assertIn("2025", r["timeframe"])
        self.assertEqual(r["currency"], "USD")

    def test_sourced_tam_alone_is_partial_not_blank(self):
        r = build_sizing({"unit_count": None}, [], figures=[FIG])
        self.assertEqual(r["status"], "partial")
        self.assertAlmostEqual(r["tam"]["value"], 40.87e9)
        self.assertEqual(sorted(r["missing"]), ["sam", "som"])

    def test_bottom_up_preferred_when_complete_and_cross_checked(self):
        r = build_sizing(OK, [], figures=[FIG])
        self.assertEqual(r["approach"], "bottom_up")
        self.assertIn("Cross-check", r["cross_check"])

    def test_figure_choice_rules(self):
        adjacent = dict(FIG, fid="F1", scope="adjacent", value=5e9)
        low = dict(FIG, fid="F2", reliability="Low", value=6e9)
        forecast = dict(FIG, fid="F3", forecast=True, year=2035, value=68e9)
        seg = dict(FIG, fid="F4", scope="segment", value=2e9)
        self.assertIsNone(pick_topdown_figure([adjacent, low]))
        self.assertEqual(pick_topdown_figure([adjacent, low, forecast, FIG])["fid"], "F0")      # base year beats forecast
        self.assertEqual(pick_topdown_figure([FIG, seg])["fid"], "F4")                          # narrower scope wins
        self.assertEqual(pick_topdown_figure([FIG, seg], prefer_id="F0")["fid"], "F0")          # figure the model's share refers to

    def test_merge_keeps_usable_inputs_and_fills_only_gaps(self):
        primary = {"unit_count": {"value": 100}, "annual_revenue_per_unit": None, "currency": "INR"}
        second = {"unit_count": {"value": 999}, "annual_revenue_per_unit": {"value": 50}, "currency": "USD"}
        m = merge_sizing_inputs(primary, second)
        self.assertEqual(m["unit_count"]["value"], 100)
        self.assertEqual(m["annual_revenue_per_unit"]["value"], 50)
        self.assertEqual(m["currency"], "INR")


class TestFigureYearAndForecast(unittest.TestCase):
    def test_year_and_forecast_are_per_figure(self):
        t = ("The global food waste management market is valued at $40.87B in 2025 and is projected to grow at a 5.3% CAGR to $68.50B by 2035.")
        sizes = [f for f in extract_figures(t, "S1", "food waste management market", ["food", "waste"]) if f["kind"] == "market_size"]
        by = {round(f["value"] / 1e9, 2): f for f in sizes}
        self.assertEqual((by[40.87]["year"], by[40.87]["forecast"]), (2025, False))
        self.assertEqual((by[68.5]["year"], by[68.5]["forecast"]), (2035, True))


class TestEndToEndAcrossIndustries(PipelineBase):
    """Every industry x every realistic way the model can answer must still yield TAM, SAM and SOM."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        fakes.IDEAS.update(EXTRA)
        cls.keys = list(fakes.IDEAS)

    @classmethod
    def tearDownClass(cls):
        for k in EXTRA:
            fakes.IDEAS.pop(k, None)
        super().tearDownClass()

    def test_messy_answers_still_give_all_three_levels(self):
        for k in self.keys:
            iid, out = self.run_idea(k, groq=fakes.FakeGroq(sizing_mode="messy"))
            sz = self.results(iid)["market"]["sizing"]
            s = fakes.IDEAS[k]
            self.assertEqual(out["status"], "completed", k)
            self.assertEqual(sz["status"], "calculated", k)
            self.assertAlmostEqual(sz["tam"]["value"], s["units"] * s["arpu"], delta=1, msg=k)
            self.assertAlmostEqual(sz["som"]["value"], s["units"] * s["arpu"] * 0.2 * 0.03, delta=1, msg=k)

    def test_unusable_bottom_up_uses_the_published_figure(self):
        for k in self.keys:
            iid, _ = self.run_idea(k, groq=fakes.FakeGroq(sizing_mode="topdown_only"))
            m = self.results(iid)["market"]
            sz, fig = m["sizing"], m["verified_figures"][0]
            self.assertEqual((sz["status"], sz["approach"]), ("calculated", "top_down"), k)
            self.assertAlmostEqual(sz["tam"]["value"], fakes.IDEAS[k]["market_usd_b"] * 1e9, delta=1e6, msg=k)
            self.assertEqual(sz["tam_source"]["url"], fig["url"], k)
            self.assertEqual(m["tam"], sz["tam"]["text"])
            self.assertNotEqual(m["sam"], "Insufficient data")

    def test_focused_retry_recovers_when_first_answer_is_unusable_and_does_not_fire_when_not_needed(self):
        g = fakes.FakeGroq(sizing_mode="messy")
        self.run_idea("food", groq=g)
        self.assertEqual(getattr(g, "sizing_retries", 0), 0)                       # messy-but-parseable needs no retry
        g = fakes.FakeGroq(sizing_mode="nulls")
        iid, _ = self.run_idea("food", groq=g)
        self.assertEqual(g.sizing_retries, 1)                                      # exactly one focused retry
        sz = self.results(iid)["market"]["sizing"]
        self.assertIn(sz["status"], ("partial", "calculated"))                     # sourced TAM at least, never a blank page
        self.assertIn("tam", sz)

    def test_unusable_first_answer_is_repaired_by_the_focused_retry(self):
        for k in ("food", "skillbridge", "finwise", "health"):
            g = fakes.FakeGroq(sizing_mode="nulls_then_clean")
            iid, _ = self.run_idea(k, groq=g)
            sz, sp = self.results(iid)["market"]["sizing"], fakes.IDEAS[k]
            self.assertEqual(g.sizing_retries, 1, k)
            self.assertEqual(sz["status"], "calculated", k)
            self.assertAlmostEqual(sz["tam"]["value"], sp["units"] * sp["arpu"], delta=1, msg=k)

    def test_genuine_missing_data_stays_insufficient(self):
        iid, out = self.run_idea("agri", groq=fakes.FakeGroq(sizing_mode="nulls"), search=fakes.FakeSearch(empty=True))
        m = self.results(iid)["market"]
        self.assertEqual(out["status"], "completed")
        self.assertEqual((m["sizing"]["status"], m["tam"], m["sam"], m["som"]), ("unavailable", "Insufficient data", "Insufficient data", "Insufficient data"))
        self.assertTrue(m["sizing"]["reason"])


class TestSizingOnThePage(PipelineBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from app import create_app
        cls.client = create_app({"TESTING": True}).test_client()
        cls.client.post("/login", data={"email": "t@example.com", "password": "pw12345"})
        cls.ids = {m: cls.run_idea("career", groq=fakes.FakeGroq(sizing_mode=m))[0] for m in ("clean", "messy", "topdown_only")}
        cls.ids["nulls"] = cls.run_idea("career", groq=fakes.FakeGroq(sizing_mode="nulls"), search=fakes.FakeSearch(empty=True))[0]

    def page(self, mode, path="market"):
        r = self.client.get(f"/idea/{self.ids[mode]}/{path}")
        self.assertEqual(r.status_code, 200)
        return r.get_data(as_text=True)

    def test_bottom_up_page_shows_formula_assumptions_currency_timeframe(self):
        html = self.page("messy")
        self.assertIn("TAM = 4,000 engineering colleges", html)
        self.assertIn("Bottom-up", html)
        self.assertIn("Currency:", html)
        self.assertIn("Timeframe:", html)
        self.assertIn("AI assumption", html)

    def test_top_down_page_shows_source_link_and_sourced_label(self):
        html = self.page("topdown_only")
        self.assertIn("Sourced TAM", html)
        self.assertIn("marketresearch.example/career-market", html)          # clickable source
        self.assertIn("a sourced figure, not an estimate", html)
        self.assertIn("Top-down", html)

    def test_genuine_gap_page_says_insufficient_and_shows_the_reason(self):
        html = self.page("nulls")
        self.assertIn("Insufficient data for market sizing", html)
        self.assertIn("Insufficient data to size this market responsibly", html)

    def test_report_and_exports_follow_the_backend(self):
        for mode in ("messy", "topdown_only", "nulls"):
            rep = self.page(mode, "report")
            self.assertNotIn("Traceback", rep)
        md = self.client.get(f"/api/export/{self.ids['topdown_only']}/markdown").get_data(as_text=True)
        self.assertIn("Top-down", md)
        self.assertIn("marketresearch.example/career-market", md)
        pdf = self.client.get(f"/api/export/{self.ids['topdown_only']}/pdf")
        self.assertTrue(pdf.data.startswith(b"%PDF"))
        self.assertTrue(self.client.get(f"/api/export/{self.ids['nulls']}/pdf").data.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
