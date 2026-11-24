"""End-to-end pipeline tests with a fake LLM / fake search (offline). See tests/fakes.py for the caveat."""
import os
import sys
import json
import shutil
import pathlib
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:  # sandbox without Flask-Login installed
    import flask_login  # noqa: F401
except ImportError:
    sys.path.insert(0, "/tmp/shims")

from config import Config
from tests import fakes


class PipelineBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls._old = (Config.DATABASE_PATH, Config.EXPORTS_DIR)
        Config.DATABASE_PATH = os.path.join(cls.tmp, "t.db")
        Config.EXPORTS_DIR = pathlib.Path(cls.tmp) / "exports"
        from database.db import init_db
        init_db()
        import orchestration.pipeline as _p
        _p._ACTIVE_PIPELINES.clear()
        from database.models import User
        u = User.create("tester", "t@example.com", "pw12345", "Tester")
        cls.uid = getattr(u, "id", u)
        import agents.competitor_agent as ca
        cls._orig_fetch = ca.fetch_page
        ca.fetch_page = fakes.fake_fetch_page

    @classmethod
    def tearDownClass(cls):
        import agents.competitor_agent as ca
        ca.fetch_page = cls._orig_fetch
        Config.DATABASE_PATH, Config.EXPORTS_DIR = cls._old
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def run_idea(cls, key, groq=None, search=None):
        from database.models import StartupIdea
        from orchestration.pipeline import OrchestrationPipeline
        s = fakes.IDEAS[key]
        iid = StartupIdea.create(cls.uid, s["title"], s["description"])
        out = OrchestrationPipeline(iid, cls.uid, groq_service=groq or fakes.FakeGroq(),
                                    search_service=search or fakes.FakeSearch()).run_synchronous()
        return iid, out

    @staticmethod
    def results(iid):
        from database.models import AnalysisResult
        return {k: v["data"] for k, v in AnalysisResult.get_all_for_idea(iid).items()}


class TestThreeIdeas(PipelineBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.runs = {key: cls.run_idea(key) for key in fakes.IDEAS}

    def test_all_complete_with_pdf(self):
        for key, (iid, out) in self.runs.items():
            self.assertEqual(out["status"], "completed", key)
            self.assertTrue((Config.EXPORTS_DIR / out["pdf_filename"]).exists())
            self.assertGreater((Config.EXPORTS_DIR / out["pdf_filename"]).stat().st_size, 5000)

    def test_competitors_are_verified_only(self):
        for key, (iid, _) in self.runs.items():
            comp = self.results(iid)["competitors"]
            names = [c["name"] for c in comp["competitors"]]
            self.assertEqual(sorted(names), sorted(c[0] for c in fakes.IDEAS[key]["competitors"]))
            self.assertNotIn(fakes.IDEAS[key]["ghost"], names)          # named in a listicle but no website -> excluded
            self.assertEqual([u["name"] for u in comp["unverified_mentions"]], [fakes.IDEAS[key]["ghost"]])
            for c in comp["competitors"]:
                self.assertTrue(c["website_verified"])
                expected = {n: p for n, _, p in fakes.IDEAS[key]["competitors"]}[c["name"]]
                if expected:
                    self.assertIn(expected.split(" ")[0], c["pricing_text"])
                else:
                    self.assertIn("Not publicly listed", c["pricing_text"])      # never invented
            self.assertTrue(comp["comparison_features"])

    def test_market_figures_come_from_sources(self):
        for key, (iid, _) in self.runs.items():
            m = self.results(iid)["market"]
            s = fakes.IDEAS[key]
            self.assertEqual(len(m["verified_figures"]), 1)
            self.assertAlmostEqual(m["verified_figures"][0]["value"], s["market_usd_b"] * 1e9, places=0)
            self.assertTrue(m["verified_figures"][0]["url"].startswith("https://"))
            self.assertEqual(m["cagr_info"]["status"], "verified_single")
            self.assertEqual(m["cagr_info"]["sources"][0]["pct"], s["cagr"])
            self.assertEqual(m["sizing"]["status"], "calculated")
            tam = s["units"] * s["arpu"]
            self.assertAlmostEqual(m["sizing"]["tam"]["value"], tam, delta=1)
            self.assertAlmostEqual(m["sizing"]["som"]["value"], tam * 0.2 * 0.03, delta=1)
            for d in m["demand_signals"]:   # basis is assigned by code from real source ids
                self.assertEqual(d["basis"], "sourced" if d["source_ids"] else "ai_analysis")

    def test_no_cross_idea_leakage(self):
        """Each report must contain its own idea's vocabulary and none of the other ideas'."""
        blobs = {k: json.dumps({n: v for n, v in self.results(iid).items() if n in
                                ("market", "competitors", "swot_risk", "mvp", "gtm", "report")}).lower()
                 for k, (iid, _) in self.runs.items()}
        for key, blob in blobs.items():
            own = fakes.IDEAS[key]
            self.assertIn(own["feature"].lower(), blob)
            self.assertIn(own["regulation"].lower(), blob)
            for other_key, other in fakes.IDEAS.items():
                if other_key == key:
                    continue
                for term in (other["feature"], other["regulation"], other["competitors"][0][0], other["users"]):
                    self.assertNotIn(term.lower(), blob, f"{key} report contains '{term}' from {other_key}")

    def test_scores_are_explained(self):
        for key, (iid, _) in self.runs.items():
            rep = self.results(iid)["report"]
            dims = rep["score_breakdown"]["dimensions"]
            self.assertEqual(set(dims), {"market", "competition", "execution", "business", "risk_resistance"})
            for name, d in dims.items():
                self.assertIsNotNone(d["score"], name)
                self.assertGreater(len(d["explanation"]), 40)
            for f in dims["market"]["factors"]:
                self.assertGreaterEqual(len(f["reason"]), 20)
            weights = sum(d["weight"] for d in dims.values())
            self.assertAlmostEqual(weights, 1.0)
            expected = round(sum(d["score"] * d["weight"] for d in dims.values()) / weights)
            self.assertEqual(rep["viability_score"], expected)

    def test_swot_risk_mvp_gtm_shapes(self):
        for key, (iid, _) in self.runs.items():
            r = self.results(iid)
            for q in ("strengths", "weaknesses", "opportunities", "threats"):
                self.assertGreaterEqual(len(r["swot_risk"]["swot"][q]), 3)
            self.assertTrue(all(x["severity"] in ("Low", "Medium", "High") for x in r["swot_risk"]["risks"]))
            self.assertTrue(r["mvp"]["must_have"] and r["mvp"]["roadmap"] and r["mvp"]["estimated_mvp_weeks"])
            self.assertEqual([p["phase"] for p in r["gtm"]["launch_roadmap_90_days"]], ["Days 1-30", "Days 31-60", "Days 61-90"])
            self.assertTrue(r["gtm"]["year_one_targets"]["target_revenue"] > 0)
            # competitor prices found by the competitor agent are passed to GTM as anchors
            self.assertEqual(r["gtm"]["price_anchors"], r["competitors"]["price_anchors"])

    def test_db_competitor_rows(self):
        from database.models import Competitor
        for key, (iid, _) in self.runs.items():
            rows = Competitor.get_by_idea(iid)
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(r["website_url"].startswith("https://www.") and r["verified_source"] for r in rows))


class TestFailureModes(PipelineBase):
    def test_no_groq_key_fails_cleanly_without_fake_report(self):
        from services.groq_service import GroqService
        from database.models import StartupIdea
        with mock.patch.object(Config, "GROQ_API_KEY", ""):
            iid, out = self.run_idea("food", groq=GroqService(api_key="", model="openai/gpt-oss-120b"))
        self.assertEqual(out["status"], "failed")
        self.assertIn("GROQ_API_KEY", out["error"])
        self.assertEqual(StartupIdea.get_by_id(iid)["status"], "failed")
        self.assertNotIn("market", self.results(iid))             # nothing fabricated

    def test_no_web_results_means_no_invented_research(self):
        iid, out = self.run_idea("agri", search=fakes.FakeSearch(empty=True))
        r = self.results(iid)
        self.assertEqual(out["status"], "completed")
        self.assertEqual(r["market"]["verified_figures"], [])
        self.assertEqual(r["market"]["cagr_info"]["status"], "unavailable")
        self.assertEqual(r["market"]["cagr"], "Insufficient data")
        self.assertEqual(r["competitors"]["competitors"], [])
        self.assertIn("could not be researched", r["competitors"]["note"])
        self.assertEqual(r["report"]["confidence"]["level"], "Low")
        self.assertLessEqual(r["report"]["score_breakdown"]["dimensions"]["market"]["score"], 70)
        # sizing still calculated, but every input is flagged as an AI assumption
        self.assertTrue(all(a["basis"] == "ai_assumption" for a in r["market"]["sizing"]["assumptions"]))
        self.assertTrue(any("AI assumption" in c for c in r["market"]["sizing"]["cautions"]))

    def test_one_agent_failing_does_not_hide_the_rest(self):
        iid, out = self.run_idea("career", groq=fakes.FakeGroq(fail_task="MARKET"))
        r = self.results(iid)
        self.assertEqual(out["status"], "completed")
        self.assertIn("_error", r["market"])
        self.assertIn("rate limit", r["market"]["_error"].lower())
        self.assertEqual(r["market"]["_meta"]["status"], "failed")
        self.assertIn("competitors", r)
        self.assertIsNone(r["report"]["score_breakdown"]["dimensions"]["market"]["score"])
        self.assertIsNotNone(r["report"]["viability_score"])       # 4 dimensions still scored

    def test_extractor_failure_aborts(self):
        iid, out = self.run_idea("food", groq=fakes.FakeGroq(fail_task="IDEA"))
        self.assertEqual(out["status"], "failed")

    def test_generic_swot_triggers_one_corrective_retry(self):
        g = fakes.FakeGroq(generic_swot_first=True)
        iid, out = self.run_idea("food", groq=g)
        self.assertEqual(g.calls.count("SWOT AND RISK ANALYSIS"), 2)
        sw = self.results(iid)["swot_risk"]["swot"]
        blob = json.dumps(sw).lower()
        self.assertNotIn("ai-native", blob)
        self.assertIn("smart-bin", blob)

    def test_quick_mode_skips_advisor_and_still_completes(self):
        Config.QUICK_MODE = True
        try:
            g = fakes.FakeGroq()
            iid, out = self.run_idea("agri", groq=g)
        finally:
            Config.QUICK_MODE = False
        self.assertEqual(out["status"], "completed")
        self.assertNotIn("ADVISORY BRIEF", g.calls)
        self.assertTrue(self.results(iid)["advisor"].get("skipped"))
        self.assertGreater(len(self.results(iid)["competitors"]["competitors"]), 0)

    def test_rerun_replaces_old_results(self):
        from orchestration.pipeline import OrchestrationPipeline
        iid, _ = self.run_idea("food")
        OrchestrationPipeline(iid, self.uid, groq_service=fakes.FakeGroq(), search_service=fakes.FakeSearch()).run_synchronous()
        from database.models import Competitor
        self.assertEqual(len(Competitor.get_by_idea(iid)), 2)     # not 4

    def test_interrupted_runs_are_recovered(self):
        from database.models import StartupIdea
        from orchestration.pipeline import OrchestrationPipeline
        iid = StartupIdea.create(self.uid, "stuck idea", "x")
        StartupIdea.update_status(iid, "analyzing")
        self.assertGreaterEqual(OrchestrationPipeline.recover_interrupted(), 1)
        self.assertEqual(StartupIdea.get_by_id(iid)["status"], "failed")
        prog = OrchestrationPipeline.get_progress(iid)
        self.assertEqual(prog["status"], "failed")
        self.assertIn("interrupted", prog["message"])


if __name__ == "__main__":
    unittest.main()
