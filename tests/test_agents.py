import unittest
from agents.idea_extractor import IdeaExtractionAgent
from agents.market_analyzer import MarketAnalyzerAgent
from agents.competitor_agent import CompetitorDiscoveryAgent
from agents.swot_risk_agent import SWOTRiskAgent
from agents.mvp_recommender import MVPRecommenderAgent
from agents.gtm_strategist import GTMStrategistAgent
from agents.startup_advisor import StartupAdvisorAgent
from agents.report_generator import ReportGeneratorAgent
from services.groq_service import GroqService, LLMError
from services.evidence import EvidenceBook
import agents.competitor_agent as _ca
from tests import fakes


class AgentsTestCase(unittest.TestCase):
    """Each agent is run in isolation with the offline fakes; chaining mirrors the pipeline."""

    @classmethod
    def setUpClass(cls):
        cls._orig_fetch = _ca.fetch_page
        _ca.fetch_page = fakes.fake_fetch_page
        s = fakes.IDEAS["agri"]
        cls.ctx = {"title": s["title"], "raw_description": s["description"], "industry": ""}
        cls.kw = dict(groq_service=fakes.FakeGroq(), search_service=fakes.FakeSearch(), book=EvidenceBook())
        cls.ex = IdeaExtractionAgent(**cls.kw).run(cls.ctx)
        cls.ctx["extractor_data"] = cls.ex
        cls.market = MarketAnalyzerAgent(**cls.kw).run(cls.ctx)
        cls.ctx["market_data"] = cls.market
        cls.comp = CompetitorDiscoveryAgent(**cls.kw).run(cls.ctx)
        cls.ctx["competitor_data"] = cls.comp
        cls.swot = SWOTRiskAgent(**cls.kw).run(cls.ctx)
        cls.ctx["swot_data"] = cls.swot
        cls.mvp = MVPRecommenderAgent(**cls.kw).run(cls.ctx)
        cls.ctx["mvp_data"] = cls.mvp
        cls.gtm = GTMStrategistAgent(**cls.kw).run(cls.ctx)
        cls.ctx["gtm_data"] = cls.gtm

    @classmethod
    def tearDownClass(cls):
        _ca.fetch_page = cls._orig_fetch

    def test_agent_1_idea_extractor(self):
        for k in ("business_concept", "problem_statement", "proposed_solution", "target_audience", "market_category", "search_queries", "_meta"):
            self.assertIn(k, self.ex)
        self.assertEqual(self.ex["_meta"]["status"], "ok")
        self.assertTrue(self.ex["search_queries"]["competitors"])

    def test_agent_2_market_analyzer(self):
        for k in ("tam", "sam", "som", "cagr", "customer_segments", "verified_figures", "sizing", "data_quality", "ratings"):
            self.assertIn(k, self.market)
        self.assertNotEqual(self.market["tam"], "Insufficient data")

    def test_agent_3_competitor_discovery(self):
        self.assertEqual(len(self.comp["competitors"]), 2)
        for c in self.comp["competitors"]:
            self.assertTrue(c["website_verified"])
        self.assertIn("ratings", self.comp)

    def test_agent_4_swot_risk(self):
        self.assertIn("strengths", self.swot["swot"])
        self.assertGreaterEqual(len(self.swot["risks"]), 4)
        self.assertIsNotNone(self.swot["overall_risk_score"])

    def test_agent_5_mvp_recommender(self):
        self.assertTrue(self.mvp["must_have"])
        self.assertTrue(self.mvp["roadmap"])

    def test_agent_6_gtm_strategist(self):
        self.assertEqual(len(self.gtm["launch_roadmap_90_days"]), 3)
        self.assertTrue(self.gtm["first_customers"]["where_to_find"])

    def test_agent_7_advisor_brief_and_chat(self):
        res = StartupAdvisorAgent(**self.kw).run(self.ctx)
        self.assertIn("advisory_summary", res)
        agent = StartupAdvisorAgent(groq_service=GroqService(api_key=""))
        with self.assertRaises(LLMError):
            agent.answer_query(self.ctx, "hello")          # no canned reply without an LLM

    def test_agent_8_report_generator(self):
        analysis = {"extractor": {"data": self.ex}, "market": {"data": self.market}, "competitors": {"data": self.comp},
                    "swot_risk": {"data": self.swot}, "mvp": {"data": self.mvp}, "gtm": {"data": self.gtm}}
        res = ReportGeneratorAgent(**self.kw).run({"idea": {"id": 1, "title": self.ctx["title"]}, "analysis_dict": analysis})
        self.assertTrue(res["score_available"])
        self.assertIn(res["recommendation"], ("PROCEED", "IMPROVE", "RECONSIDER"))
        self.assertIn("score_breakdown", res)

    def test_every_agent_returns_an_error_not_fake_data_without_a_key(self):
        nokey = GroqService(api_key="")
        for cls_ in (IdeaExtractionAgent, MarketAnalyzerAgent, CompetitorDiscoveryAgent, SWOTRiskAgent,
                     MVPRecommenderAgent, GTMStrategistAgent, StartupAdvisorAgent):
            res = cls_(groq_service=nokey, search_service=fakes.FakeSearch()).run(self.ctx)
            self.assertIn("_error", res, cls_.__name__)
            self.assertEqual(res["_meta"]["status"], "failed")
            self.assertNotIn("tam", res)
            self.assertNotIn("competitors", res)


if __name__ == "__main__":
    unittest.main()
