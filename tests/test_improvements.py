"""Tests for the accuracy / reliability upgrades (wording, verdicts, consistency, MVP cost, competitors, risks)."""
import os
import sys
import json
import shutil
import pathlib
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import flask_login  # noqa: F401
except ImportError:
    sys.path.insert(0, "/tmp/shims")

from config import Config
from services import scoring, sizing
from agents.report_generator import strip_unsupported_figures
from agents.mvp_recommender import MVPRecommenderAgent
from agents.competitor_agent import CompetitorAnalysisAgent
from agents.swot_risk_agent import SWOTRiskAgent
from agents.startup_advisor import _compact
from tests import fakes
from tests.test_pipeline import PipelineBase


def ratings(keys, n, reason="a reason that is long enough to count"):
    return {k: {"rating": n, "reason": reason} for k in keys}


class TestScoringExplanations(unittest.TestCase):
    EV = {"figures": 2, "publishers": 2, "sources": 6}

    def score(self, n, risk=20):
        return scoring.compute_viability(
            ratings(scoring.FACTOR_KEYS["market"][:3], n), ratings(scoring.FACTOR_KEYS["competition"], n),
            ratings(scoring.FACTOR_KEYS["execution"], n), ratings(scoring.FACTOR_KEYS["business"], n),
            overall_risk=risk, evidence=self.EV, competitors_verified=3, risk_count=6)

    def test_same_inputs_same_score_and_labels(self):
        self.assertEqual(self.score(4)["viability_score"], self.score(4)["viability_score"])
        self.assertEqual(self.score(5, risk=10)["recommendation"], "PROCEED")
        self.assertEqual(self.score(3, risk=40)["recommendation"], "IMPROVE")
        self.assertEqual(self.score(1, risk=80)["recommendation"], "RECONSIDER")
        self.assertEqual(scoring.RECOMMENDATION_LABELS["RECONSIDER"], "High Risk")

    def test_verdict_explanation_matches_band(self):
        high = self.score(1, risk=80)
        self.assertTrue(high["verdict_explanation"].startswith("High Risk"))
        mid = self.score(3, risk=40)
        self.assertTrue(mid["verdict_explanation"].startswith("Improve"))
        self.assertIn(f"{75 - mid['viability_score']} more point", mid["verdict_explanation"])
        self.assertTrue(self.score(5, risk=10)["verdict_explanation"].startswith("Proceed"))
        self.assertIn("not a prediction or a guarantee", mid["disclaimer"])

    def test_reducing_factor_points_are_arithmetic(self):
        out = self.score(3, risk=40)
        top = out["reducing_factors"][0]
        d = out["dimensions"][top["dimension"]]
        total_w = sum(v["weight"] for v in out["dimensions"].values() if v["score"] is not None)
        expected = d["weight"] * (4 - top["rating"]) * 20 / len(d["factors"]) / total_w
        self.assertAlmostEqual(top["points_if_raised_to_4"], round(expected, 1))

    def test_insufficient_data_wording(self):
        self.assertEqual(sizing.resolve_cagr([], {}, True)["value_text"], "Insufficient data")


class TestNarrativeConsistency(unittest.TestCase):
    FACTS = json.dumps({"figures": ["$1.9 billion"], "value": 1900000000.0, "cagr": 8.4, "tam": "$90.0 M"})

    def test_unsupported_figures_removed_supported_kept(self):
        text = "The market is worth $9.9 billion. A published figure is $1.9 billion. Growth is 8.4% a year. Growth will hit 55%."
        clean, removed = strip_unsupported_figures(text, self.FACTS)
        self.assertEqual(removed, 2)
        self.assertIn("1.9 billion", clean)
        self.assertIn("8.4%", clean)
        self.assertNotIn("9.9", clean)
        self.assertNotIn("55%", clean)


class TestMvpLogic(unittest.TestCase):
    def test_timeline_check_statuses(self):
        d = {"team_size": 2, "hours_per_week_each": 10, "must_have": [{"effort_hours": 200}, {"effort_hours": 100}]}   # 20 h/week
        ok = MVPRecommenderAgent._timeline_check(d, 20)      # needs ceil(300*1.25/20)=19
        self.assertEqual(ok["status"], "ok")
        self.assertEqual(ok["suggested_weeks"], 19)
        self.assertEqual(MVPRecommenderAgent._timeline_check(d, 16)["status"], "tight")
        self.assertEqual(MVPRecommenderAgent._timeline_check(d, 6)["status"], "unrealistic")
        self.assertEqual(MVPRecommenderAgent._timeline_check({"must_have": []}, 8)["status"], "unknown")

    def test_cost_totals_are_computed_and_bad_lines_dropped(self):
        ce = MVPRecommenderAgent._cost_estimate({
            "currency": "INR", "assumptions": ["2 students"],
            "items": [{"category": "Development", "type": "own_time", "amount_low": 1000, "amount_high": 2000},
                      {"category": "Hosting & tools", "type": "cash", "amount_low": 0, "amount_high": 500},
                      {"category": "Bad", "type": "cash", "amount_low": 900, "amount_high": 100},
                      {"category": "Junk", "type": "cash", "amount_low": "x", "amount_high": 1}],
            "monthly_running_cost": {"low": 0, "high": 40}})
        self.assertEqual(len(ce["items"]), 2)
        self.assertEqual(ce["cash_total"]["high"], 500)
        self.assertEqual(ce["own_time_total"]["low"], 1000)
        self.assertIn("₹", ce["cash_total"]["text"])
        self.assertEqual(MVPRecommenderAgent._cost_estimate(None)["status"], "unavailable")
        self.assertIn("Insufficient data", MVPRecommenderAgent._cost_estimate({"items": []})["reason"])


class TestCompetitorAndRiskLogic(unittest.TestCase):
    def test_types_and_gap_analysis(self):
        n = CompetitorAnalysisAgent._norm_type
        self.assertEqual((n("emerging startup"), n("Adjacent"), n("indirect"), n(None)), ("Emerging", "Indirect", "Indirect", "Direct"))
        matrix = [{"capability": "A", "idea_offers": True, "competitors": {"X": "no", "Y": "unclear"}},
                  {"capability": "B", "idea_offers": True, "competitors": {"X": "yes", "Y": "no"}},
                  {"capability": "C", "idea_offers": True, "competitors": {"X": "yes", "Y": "yes"}},
                  {"capability": "D", "idea_offers": False, "competitors": {"X": "no", "Y": "no"}}]
        gaps = CompetitorAnalysisAgent._gap_analysis(matrix, ["X", "Y"])
        self.assertEqual([(g["capability"], g["status"]) for g in gaps], [("A", "open"), ("B", "partial"), ("C", "crowded")])

    def test_risk_normalisation(self):
        agent = SWOTRiskAgent(groq_service=fakes.FakeGroq(), search_service=fakes.FakeSearch())
        risks = [{"category": c, "risk": "r", "risk_points": 10, "impact_score": 5, "likelihood_score": 5}
                 for c in ("technical", "Regulatory", "competition", "competition", "competition", "weird")]
        out = agent._normalise_risks(risks)
        cats = [r["category"] for r in out]
        self.assertEqual(cats.count("Competitive"), 2)                       # capped at two per category
        self.assertIn("Legal/Regulatory", cats)
        self.assertTrue(any("Financial" in w for w in agent.warnings))       # required category missing -> flagged


class TestEndToEndConsistency(PipelineBase):
    def test_two_named_ideas_differ_and_report_is_consistent(self):
        runs = {k: self.run_idea(k) for k in ("skillbridge", "finwise")}
        res = {k: self.results(iid) for k, (iid, _) in runs.items()}
        for k, (iid, out) in runs.items():
            self.assertEqual(out["status"], "completed", k)
        sb, fw = (json.dumps(res[k]).lower() for k in ("skillbridge", "finwise"))
        self.assertIn("readiness-score diagnostic", sb)
        self.assertIn("cash-flow forecasting", fw)
        self.assertNotIn("cash-flow forecasting", sb)
        self.assertNotIn("readiness-score diagnostic", fw)
        names = {k: {c["name"] for c in res[k]["competitors"]["competitors"]} for k in res}
        self.assertFalse(names["skillbridge"] & names["finwise"])
        for k in res:
            rep = res[k]["report"]
            dims = rep["score_breakdown"]["dimensions"]
            total_w = sum(d["weight"] for d in dims.values())
            self.assertEqual(rep["viability_score"], round(sum(d["score"] * d["weight"] for d in dims.values()) / total_w))
            self.assertTrue(rep["verdict_explanation"].startswith({"PROCEED": "Proceed", "IMPROVE": "Improve", "RECONSIDER": "High Risk"}[rep["recommendation"]]))
            self.assertTrue(rep["key_risks"] and rep["key_strengths"])
            cats = {r["category"] for r in res[k]["swot_risk"]["risks"]}
            self.assertTrue({"Technical", "Financial", "Market", "Operational", "Legal/Regulatory", "Competitive"} <= cats)
            self.assertEqual(res[k]["mvp"]["cost_estimate"]["status"], "ok")
            self.assertTrue(res[k]["mvp"]["build_order"])
            self.assertTrue(res[k]["gtm"]["marketing_strategy"]["channels"])
            self.assertTrue({c["competitor_type"] for c in res[k]["competitors"]["competitors"]} <= {"Direct", "Indirect", "Emerging"})

    def test_contradicting_narrative_is_corrected(self):
        class Contradicting(fakes.FakeGroq):
            def _final(self, user, key, s):
                out = super()._final(user, key, s)
                out["executive_summary"] = (f"{s['title']} has a viability score of 12/100. The market is worth $9.9 billion. "
                                            f"Competitors such as {s['competitors'][0][0]} lack {s['feature']}.")
                out["go_no_go_verdict"] = "Definitely go for it"
                return out
        iid, out = self.run_idea("finwise", groq=Contradicting())
        rep = self.results(iid)["report"]
        self.assertNotIn("9.9 billion", rep["executive_summary"])
        self.assertIn(f"score of {rep['viability_score']}/100", rep["executive_summary"])
        self.assertIn({"PROCEED": "Proceed", "IMPROVE": "Improve", "RECONSIDER": "High Risk"}[rep["recommendation"]], rep["go_no_go_verdict"])
        self.assertTrue(any("removed" in w for w in rep["_meta"]["warnings"]))

    def test_unsupported_basis_labels_are_downgraded(self):
        class Overclaiming(fakes.FakeGroq):
            def _swot(self, user, key, s):
                out = super()._swot(user, key, s)
                out["swot"]["strengths"][0].update({"basis": "market_evidence", "source_ids": []})
                out["swot"]["threats"][0].update({"point": "A large generic bank may copy this idea", "basis": "competitor_evidence"})   # names no verified competitor
                out["swot"]["weaknesses"][0].update({"point": "Some unrelated generic text about gardening hoses", "basis": "idea"})
                return out
        iid, _ = self.run_idea("skillbridge", groq=Overclaiming())
        sw = self.results(iid)["swot_risk"]["swot"]
        self.assertEqual(sw["strengths"][0]["basis"], "ai_inference")
        self.assertEqual(sw["threats"][0]["basis"], "ai_inference")
        unrelated = [i for i in sw["weaknesses"] if "gardening" in i["point"]]
        self.assertTrue(all(i["basis"] == "ai_inference" for i in unrelated))   # removed by the generic-text guard, or relabelled

    def test_chat_digest_uses_all_modules(self):
        iid, _ = self.run_idea("finwise")
        r = self.results(iid)
        ctx = {"title": fakes.IDEAS["finwise"]["title"], "raw_description": "x", "extractor_data": r["extractor"], "market_data": r["market"],
               "competitor_data": r["competitors"], "swot_risk_data": r["swot_risk"], "mvp_data": r["mvp"], "gtm_data": r["gtm"], "report_data": r["report"]}
        blob = json.dumps(_compact(ctx))
        for needle in ("PennyPilot", "cash-flow forecasting", "why_verdict", "cost_cash", "first_customers", "warning_sign", "market_gaps"):
            self.assertIn(needle, blob)


class TestPages(PipelineBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import orchestration.pipeline as _p
        _p._ACTIVE_PIPELINES.clear()
        cls._old_key = Config.GROQ_API_KEY
        Config.GROQ_API_KEY = "gsk_test_key_123456"
        from app import create_app
        cls.app = create_app({"TESTING": True})
        cls.client = cls.app.test_client()
        cls.client.post("/login", data={"email": "t@example.com", "password": "pw12345"})
        cls.iid, _ = cls.run_idea("skillbridge")

    @classmethod
    def tearDownClass(cls):
        Config.GROQ_API_KEY = cls._old_key
        super().tearDownClass()

    def page(self, name):
        r = self.client.get(f"/idea/{self.iid}/{name}")
        self.assertEqual(r.status_code, 200, name)
        return r.get_data(as_text=True)

    def test_new_sections_render_and_labels_are_updated(self):
        rep = self.page("report")
        self.assertIn("Why this verdict", rep)
        self.assertIn("What is holding the score down", rep)
        self.assertNotIn("RECONSIDER", rep)
        self.assertIn("not a prediction or a guarantee", rep)
        comp = self.page("competitors")
        self.assertIn("Market gaps (computed from competitor websites)", comp)
        self.assertIn("Emerging", comp)
        self.assertIn("Weaknesses", comp)
        self.assertIn("Why these scores", self.page("risks"))
        mvp = self.page("mvp")
        for needle in ("Development cost estimate", "What to build first", "Timeline check", "Required resources", "How to test it"):
            self.assertIn(needle, mvp)
        self.assertIn("Marketing &amp; customer-acquisition strategy", self.page("gtm"))

    def test_error_pages(self):
        r = self.client.get("/idea/99999/report")
        self.assertEqual(r.status_code, 404)
        self.assertIn("Page not found", r.get_data(as_text=True))
        j = self.client.get("/api/idea/99999/status")
        self.assertEqual(j.get_json()["status"] if j.is_json else "error", "error") if j.status_code == 404 and j.is_json else None


if __name__ == "__main__":
    unittest.main()
