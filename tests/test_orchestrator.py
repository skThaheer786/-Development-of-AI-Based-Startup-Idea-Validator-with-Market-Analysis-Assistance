import unittest
import os
import tempfile
from config import Config
from database.db import init_db
from database.models import User, StartupIdea, AnalysisResult, Competitor, ValidationReport
from orchestration.pipeline import OrchestrationPipeline
import orchestration.pipeline as _pipe
import agents.competitor_agent as _ca
from services.groq_service import GroqService
from tests import fakes


class OrchestratorTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        Config.DATABASE_PATH = self.temp_db.name
        _pipe._ACTIVE_PIPELINES.clear()
        self._orig_fetch = _ca.fetch_page
        _ca.fetch_page = fakes.fake_fetch_page
        init_db()
        self.user = User.create("testorch", "orch@venture.com", "pass123")
        s = fakes.IDEAS["career"]
        self.idea_id = StartupIdea.create(user_id=self.user.id, title=s["title"], raw_description=s["description"])

    def tearDown(self):
        _ca.fetch_page = self._orig_fetch
        try:
            os.remove(self.temp_db.name)
        except Exception:
            pass

    def test_pipeline_execution_synchronous(self):
        result = OrchestrationPipeline(idea_id=self.idea_id, user_id=self.user.id, groq_service=fakes.FakeGroq(),
                                       search_service=fakes.FakeSearch()).run_synchronous()
        self.assertEqual(result["status"], "completed")
        self.assertGreater(result["viability_score"], 0)
        self.assertIsNotNone(result["pdf_filename"])

        updated = StartupIdea.get_by_id(self.idea_id)
        self.assertEqual(updated["status"], "completed")
        self.assertEqual(updated["viability_score"], result["viability_score"])

        stored = AnalysisResult.get_all_for_idea(self.idea_id)
        for agent_name in ["extractor", "market", "competitors", "swot_risk", "mvp", "gtm", "advisor", "report"]:
            self.assertIn(agent_name, stored)
            self.assertNotIn("_error", stored[agent_name]["data"])
        self.assertGreater(len(Competitor.get_by_idea(self.idea_id)), 0)
        report = ValidationReport.get_by_idea(self.idea_id)
        self.assertEqual(report["viability_score"], result["viability_score"])

    def test_without_groq_key_the_run_fails_and_stores_no_fake_analysis(self):
        old = Config.GROQ_API_KEY
        Config.GROQ_API_KEY = ""
        try:
            result = OrchestrationPipeline(idea_id=self.idea_id, user_id=self.user.id).run_synchronous()
        finally:
            Config.GROQ_API_KEY = old
        self.assertEqual(result["status"], "failed")
        self.assertEqual(StartupIdea.get_by_id(self.idea_id)["status"], "failed")
        self.assertNotIn("market", AnalysisResult.get_all_for_idea(self.idea_id))
        self.assertIsNone(ValidationReport.get_by_idea(self.idea_id))


if __name__ == "__main__":
    unittest.main()
