"""Flask route / template / export tests using the offline pipeline (fake LLM + fake search)."""
import os
import re
import sys
import json
import shutil
import pathlib
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import flask_login  # noqa: F401
except ImportError:  # sandbox without Flask-Login
    sys.path.insert(0, "/tmp/shims")

from config import Config
from tests import fakes


class TestApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls._old = (Config.DATABASE_PATH, Config.EXPORTS_DIR, Config.GROQ_API_KEY)
        Config.DATABASE_PATH = os.path.join(cls.tmp, "t.db")
        Config.EXPORTS_DIR = pathlib.Path(cls.tmp) / "exports"
        Config.GROQ_API_KEY = "gsk_test_key_123456"
        import agents.competitor_agent as ca
        cls._orig_fetch = ca.fetch_page
        ca.fetch_page = fakes.fake_fetch_page
        import orchestration.pipeline as _p
        _p._ACTIVE_PIPELINES.clear()
        from app import create_app
        cls.app = create_app({"TESTING": True})
        cls.client = cls.app.test_client()
        from database.models import User, StartupIdea
        u = User.create("tester", "t@example.com", "pw12345", "Tester")
        cls.uid = getattr(u, "id", u)
        r = cls.client.post("/login", data={"email": "t@example.com", "password": "pw12345"})
        assert r.status_code in (302, 200)
        from orchestration.pipeline import OrchestrationPipeline
        cls.ids = {}
        for key, s in fakes.IDEAS.items():
            iid = StartupIdea.create(cls.uid, s["title"], s["description"])
            OrchestrationPipeline(iid, cls.uid, groq_service=fakes.FakeGroq(), search_service=fakes.FakeSearch()).run_synchronous()
            cls.ids[key] = iid
        # an idea whose web search found nothing
        cls.empty_id = StartupIdea.create(cls.uid, fakes.IDEAS["agri"]["title"], fakes.IDEAS["agri"]["description"])
        OrchestrationPipeline(cls.empty_id, cls.uid, groq_service=fakes.FakeGroq(), search_service=fakes.FakeSearch(empty=True)).run_synchronous()
        # an idea that failed outright
        cls.failed_id = StartupIdea.create(cls.uid, "Failed one", "desc")
        Config.GROQ_API_KEY = ""
        OrchestrationPipeline(cls.failed_id, cls.uid).run_synchronous()
        Config.GROQ_API_KEY = "gsk_test_key_123456"

    @classmethod
    def tearDownClass(cls):
        import agents.competitor_agent as ca
        ca.fetch_page = cls._orig_fetch
        Config.DATABASE_PATH, Config.EXPORTS_DIR, Config.GROQ_API_KEY = cls._old
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, url, status=200):
        r = self.client.get(url)
        self.assertEqual(r.status_code, status, f"{url} -> {r.status_code}")
        return r.get_data(as_text=True)

    # ------------------------------------------------------------------
    def test_every_page_renders_for_every_idea(self):
        pages = ["report", "market", "competitors", "swot", "risks", "mvp", "gtm", "chat"]
        for key, iid in {**self.ids, "empty": self.empty_id, "failed": self.failed_id}.items():
            for p in pages:
                html = self.get(f"/idea/{iid}/{p}")
                self.assertNotIn("Traceback", html)
                self.assertNotIn("UndefinedError", html)
        for url in ("/dashboard", "/history", "/submit", "/settings", f"/dashboard?idea_id={self.ids['food']}", "/advisor"):
            self.get(url) if url != "/advisor" else self.assertIn(self.client.get(url).status_code, (200, 302))

    def test_no_fabricated_defaults_anywhere(self):
        banned = ["$14.2", "15.8%", "10x faster", "$3.1", "$180M", "Strong Pursue", "Agile SMBs"]
        for iid in list(self.ids.values()) + [self.empty_id, self.failed_id]:
            for p in ("report", "market", "competitors", "gtm", "mvp"):
                html = self.get(f"/idea/{iid}/{p}")
                for b in banned:
                    self.assertNotIn(b, html, f"{b} on {p}")
        self.get("/dashboard")

    def test_market_page_shows_sourced_and_ai_labels(self):
        html = self.get(f"/idea/{self.ids['food']}/market")
        self.assertIn("marketresearch.example/food-market", html)      # clickable source link
        self.assertIn("TAM = 60,000 commercial kitchens", html)         # formula shown
        self.assertIn("AI assumption", html)
        self.assertIn("8.4%", html)
        self.assertIn('target="_blank"', html)

    def test_empty_research_page_is_honest(self):
        html = self.get(f"/idea/{self.empty_id}/market")
        self.assertIn("No retrieved source stated a market size", html)
        self.assertIn("Insufficient data", html)
        comp = self.get(f"/idea/{self.empty_id}/competitors")
        self.assertIn("No competitor could be verified", comp)

    def test_failed_idea_shows_reason_and_retry(self):
        html = self.get(f"/idea/{self.failed_id}/report")
        self.assertIn("could not be completed", html)
        self.assertIn("GROQ_API_KEY", html)
        self.assertIn("rerunAnalysis", html)

    def test_competitor_table_links_and_comparison(self):
        html = self.get(f"/idea/{self.ids['career']}/competitors")
        self.assertIn("https://www.pathpilot.example/", html)
        self.assertIn("Listed on website: $9/month", html)
        self.assertIn("Capability comparison", html)
        self.assertNotIn(fakes.IDEAS["career"]["ghost"] + "</strong>", html)

    def test_ideas_do_not_leak_into_each_other_in_html(self):
        food = self.get(f"/idea/{self.ids['food']}/swot") + self.get(f"/idea/{self.ids['food']}/risks")
        self.assertIn("smart-bin weight tracking", food)
        self.assertNotIn("leaf-photo", food)
        self.assertNotIn("skill-gap", food)

    def test_all_internal_links_resolve(self):
        """Crawl every internal href on the report pages and the dashboard."""
        seen, bad = set(), []
        pages = [f"/idea/{self.ids['food']}/{p}" for p in ("report", "market", "competitors", "swot", "risks", "mvp", "gtm", "chat")]
        pages += ["/dashboard", "/history", "/submit", "/settings"]
        for page in pages:
            html = self.get(page)
            for href in re.findall(r'href="(/[^"#?]*(?:\?[^"#]*)?)"', html):
                if href.startswith("/static") or href in seen or "/export/" in href or href in ("/logout", "/demo-login"):
                    continue
                seen.add(href)
                code = self.client.get(href).status_code
                if code >= 400:
                    bad.append((page, href, code))
        self.assertEqual(bad, [])

    def test_all_url_for_endpoints_exist(self):
        endpoints = set(self.app.view_functions)
        used = set()
        for root, _, files in os.walk(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")):
            for f in files:
                used |= set(re.findall(r"url_for\(\s*'([a-z_]+)'", open(os.path.join(root, f), encoding="utf-8").read()))
        used.discard("static")
        self.assertEqual(sorted(used - endpoints), [])

    def test_exports(self):
        iid = self.ids["food"]
        pdf = self.client.get(f"/api/export/{iid}/pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.data.startswith(b"%PDF"))
        md = self.get(f"/api/export/{iid}/markdown")
        self.assertIn("marketresearch.example", md)
        self.assertIn("BinSense", md)
        csv_ = self.get(f"/api/export/{iid}/csv")
        self.assertIn("Sourced market figure", csv_)
        js = json.loads(self.get(f"/api/export/{iid}/json"))
        self.assertEqual(len(js["competitors"]), 2)
        # on-the-fly PDF when the cached file is gone
        for f in Config.EXPORTS_DIR.glob(f"report_{iid}_*.pdf"):
            f.unlink()
        self.assertTrue(self.client.get(f"/api/export/{iid}/pdf").data.startswith(b"%PDF"))

    def test_status_and_run_api(self):
        iid = self.ids["agri"]
        data = self.client.get(f"/api/idea/{iid}/status").get_json()
        self.assertEqual(data["progress"]["status"], "completed")
        self.assertEqual(data["progress"]["percent"], 100)
        self.assertEqual(self.client.get("/api/idea/99999/status").status_code, 404)

    def test_compare_api(self):
        d = self.client.get(f"/api/ideas/compare?id1={self.ids['food']}&id2={self.ids['agri']}").get_json()
        self.assertEqual(d["status"], "success")
        self.assertNotEqual(d["idea1"]["tam"], d["idea2"]["tam"])

    def test_chat_uses_analysis_and_errors_without_key(self):
        from agents import startup_advisor
        calls = {}

        def fake(self, messages, **k):
            calls["system"] = messages[0]["content"]
            return "Focus on BinSense gap."
        from services.groq_service import GroqService
        orig = GroqService.chat_completion
        GroqService.chat_completion = fake
        try:
            r = self.client.post(f"/api/idea/{self.ids['food']}/chat", json={"message": "What should I do first?"})
        finally:
            GroqService.chat_completion = orig
        self.assertEqual(r.get_json()["status"], "success")
        self.assertIn("BinSense", calls["system"])                    # grounded in this idea's competitors
        old = Config.GROQ_API_KEY
        Config.GROQ_API_KEY = ""
        try:
            r = self.client.post(f"/api/idea/{self.ids['food']}/chat", json={"message": "hello"})
        finally:
            Config.GROQ_API_KEY = old
        self.assertEqual(r.status_code, 503)                           # honest error, no canned reply

    def test_sample_load_requires_key_and_starts_real_pipeline(self):
        old = Config.GROQ_API_KEY
        Config.GROQ_API_KEY = ""
        try:
            r = self.client.post("/api/sample/load")
        finally:
            Config.GROQ_API_KEY = old
        self.assertEqual(r.status_code, 302)
        self.assertIn("/settings", r.headers["Location"])

    def test_settings_rejects_bad_key(self):
        old = Config.GROQ_API_KEY
        self.client.post("/settings", data={"groq_api_key": "gsk_\u2026bad key", "groq_model": "openai/gpt-oss-120b"})
        self.assertEqual(Config.GROQ_API_KEY, old)

    def test_settings_migrates_retired_model(self):
        self.client.post("/settings", data={"groq_model": "llama-3.3-70b-versatile"})
        self.assertEqual(Config.GROQ_MODEL, "openai/gpt-oss-120b")


if __name__ == "__main__":
    unittest.main()
