"""Unit tests for the research/analysis building blocks (offline)."""
import os
import sys
import json
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import quality, scoring, sizing
from services.evidence import extract_figures, extract_prices, format_money, registered_domain, classify_source, EvidenceBook
from services.groq_service import GroqService, LLMError, parse_json_response
from services.search_service import SearchService
from config import resolve_model


class FakeResp:
    def __init__(self, status=200, body=None, headers=None, text=""):
        self.status_code, self._body, self.headers, self.text = status, body, headers or {}, text

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def ok_body(content):
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}}


class TestModelMigration(unittest.TestCase):
    def test_retired_models_are_migrated(self):
        for old in ("llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768", "gemma2-9b-it"):
            new, note = resolve_model(old)
            self.assertTrue(new.startswith("openai/gpt-oss"), old)
            self.assertIn("retired", note)
        self.assertEqual(resolve_model("openai/gpt-oss-120b"), ("openai/gpt-oss-120b", ""))


class TestEvidence(unittest.TestCase):
    def test_market_size_and_cagr_parsed_with_source(self):
        text = ("The global food waste software market was valued at USD 4.5 billion in 2024. "
                "The market is projected to grow at a CAGR of 9.2% from 2025 to 2030.")
        figs = extract_figures(text, "S1", "food waste software market", ["food", "waste"])
        kinds = {f["kind"] for f in figs}
        self.assertEqual(kinds, {"market_size", "cagr"})
        size = next(f for f in figs if f["kind"] == "market_size")
        self.assertAlmostEqual(size["value"], 4.5e9)
        self.assertEqual(next(f for f in figs if f["kind"] == "cagr")["pct"], 9.2)
        self.assertTrue(all(f["source_id"] == "S1" for f in figs))

    def test_prices_and_irrelevant_text_are_not_market_sizes(self):
        self.assertEqual(extract_figures("The plan costs $29 per month for the market leader.", "S1"), [])
        self.assertEqual(extract_figures("The cryptocurrency market hit USD 2 billion.", "S1", "", ["farm"]), [])

    def test_extract_prices_only_literal(self):
        self.assertEqual(extract_prices("Starter $29/month, Pro ₹999 per month"), ["$29/month", "₹999 per month"])
        self.assertEqual(extract_prices("Contact us for a quote"), [])

    def test_domain_and_source_classification(self):
        self.assertEqual(registered_domain("https://www.shop.example.co.uk/x"), "example.co.uk")
        self.assertEqual(classify_source("https://data.worldbank.org/x")["reliability"], "High")
        self.assertEqual(classify_source("https://www.reddit.com/r/x")["reliability"], "Low")

    def test_format_money(self):
        self.assertEqual(format_money(1_250_000_000), "$1.25 B")
        self.assertEqual(format_money(1200), "$1,200")

    def test_evidence_book_dedupes_and_ids(self):
        b = EvidenceBook()
        r = {"title": "t", "url": "https://a.example/x", "snippet": "s", "domain": "a.example"}
        a1 = b.add([r, r])
        self.assertEqual([i["id"] for i in a1], ["S1"])  # duplicates collapse
        self.assertEqual(b.valid_ids(["S1", "S9"]), ["S1"])


class TestSizingAndCagr(unittest.TestCase):
    RAW = {"customer_unit": "clinics", "currency": "USD",
           "unit_count": {"value": 1000, "basis": "sourced", "source_ids": ["S1"]},
           "annual_revenue_per_unit": {"value": 2000, "basis": "ai_assumption"},
           "serviceable_share": {"value": 0.25}, "obtainable_share": {"value": 0.04}}

    def test_math(self):
        s = sizing.build_sizing(self.RAW, ["S1"])
        self.assertEqual(s["status"], "calculated")
        self.assertAlmostEqual(s["tam"]["value"], 2_000_000)
        self.assertAlmostEqual(s["sam"]["value"], 500_000)
        self.assertAlmostEqual(s["som"]["value"], 20_000)
        self.assertLessEqual(s["som"]["low"], s["som"]["value"])
        self.assertGreaterEqual(s["som"]["high"], s["som"]["value"])

    def test_fake_source_is_downgraded(self):
        s = sizing.build_sizing(self.RAW, [])  # S1 was never retrieved
        uc = s["assumptions"][0]
        self.assertEqual(uc["basis"], "ai_assumption")
        self.assertTrue(any("not in the retrieved evidence" in c for c in s["cautions"]))

    def test_missing_assumptions_gives_reason_not_numbers(self):
        s = sizing.build_sizing({"unit_count": {"value": 5}}, [])
        self.assertEqual(s["status"], "unavailable")
        self.assertIn("Insufficient data", s["reason"])

    def test_cagr_unavailable_explains_why(self):
        self.assertEqual(sizing.resolve_cagr([], {}, had_any_sources=False)["status"], "unavailable")
        c = sizing.resolve_cagr([], {}, had_any_sources=True)
        self.assertIn("rather than guessing", c["explanation"])

    def test_cagr_range_from_two_publishers(self):
        look = {"S1": {"id": "S1", "url": "https://a.example/1", "title": "A", "domain": "a.example"},
                "S2": {"id": "S2", "url": "https://b.example/1", "title": "B", "domain": "b.example"}}
        figs = [{"kind": "cagr", "pct": 8.0, "sentence": "x", "source_id": "S1"},
                {"kind": "cagr", "pct": 11.0, "sentence": "y", "source_id": "S2"}]
        c = sizing.resolve_cagr(figs, look, True)
        self.assertEqual(c["status"], "verified_multi")
        self.assertEqual(c["value_text"], "8% – 11%")

    def test_cagr_ignores_low_reliability_sources(self):
        look = {"S1": {"id": "S1", "url": "https://www.reddit.com/r/x", "title": "R", "domain": "reddit.com"}}
        c = sizing.resolve_cagr([{"kind": "cagr", "pct": 30.0, "sentence": "x", "source_id": "S1"}], look, True)
        self.assertEqual(c["status"], "unavailable")


class TestScoring(unittest.TestCase):
    @staticmethod
    def r(n, text="a reason that is long enough to count"):
        return {"rating": n, "reason": text}

    def ratings(self, keys, n):
        return {k: self.r(n) for k in keys}

    def test_weighted_score_and_threshold(self):
        ev = {"figures": 3, "publishers": 3, "sources": 8}
        out = scoring.compute_viability(
            self.ratings(scoring.FACTOR_KEYS["market"][:3], 5), self.ratings(scoring.FACTOR_KEYS["competition"], 5),
            self.ratings(scoring.FACTOR_KEYS["execution"], 5), self.ratings(scoring.FACTOR_KEYS["business"], 5),
            overall_risk=10, evidence=ev, competitors_verified=4, risk_count=6)
        self.assertEqual(out["recommendation"], "PROCEED")
        self.assertGreaterEqual(out["viability_score"], 90)
        self.assertEqual(out["confidence"]["level"], "High")

    def test_market_capped_without_evidence(self):
        ev = {"figures": 0, "publishers": 0, "sources": 0}
        out = scoring.compute_viability(self.ratings(scoring.FACTOR_KEYS["market"][:3], 5), None, None, None,
                                        overall_risk=None, evidence=ev)
        self.assertEqual(out["dimensions"]["market"]["score"], 70)
        self.assertIn("Capped", out["dimensions"]["market"]["explanation"])
        self.assertIsNone(out["viability_score"])      # <3 dimensions -> no overall score
        self.assertEqual(out["recommendation"], "PENDING")

    def test_short_reasons_are_rejected(self):
        bad = {k: {"rating": 5, "reason": "good"} for k in scoring.FACTOR_KEYS["business"]}
        out = scoring.compute_viability(None, None, None, bad, overall_risk=20)
        self.assertIsNone(out["dimensions"]["business"]["score"])

    def test_risk_scoring(self):
        risks, overall, rating = scoring.score_risks([
            {"risk": "a", "impact_score": 9, "likelihood_score": 8}, {"risk": "b", "impact_score": 2, "likelihood_score": 2},
            {"risk": "c", "impact_score": "x", "likelihood_score": 3}])
        self.assertEqual(len(risks), 2)                 # invalid one dropped
        self.assertEqual(risks[0]["severity"], "High")
        self.assertEqual(risks[1]["severity"], "Low")
        self.assertIsNotNone(overall)


class TestQuality(unittest.TestCase):
    def test_boilerplate_detected_and_specific_passes(self):
        anchors = quality.build_anchors("Smart bins for canteen food waste", ["surplus meals"])
        self.assertTrue(quality.is_generic("Leverages cutting-edge AI-native workflows for seamless integration", anchors)[0])
        self.assertTrue(quality.is_generic("The team may struggle with limited early capital and brand recognition overall", anchors)[0])
        self.assertFalse(quality.is_generic("Canteen managers can see surplus meals per shift from the smart bins", anchors)[0])

    def test_strip_keeps_lists_healthy(self):
        data = {"a": ["x1", "x2", "x3", "x4"]}
        removed = quality.strip_flagged(data, [("a", 0, "", ""), ("a", 1, "", "")], min_keep=3)
        self.assertEqual(removed, 0)          # would leave only 2
        removed = quality.strip_flagged(data, [("a", 0, "", "")], min_keep=3)
        self.assertEqual(removed, 1)


class TestGroqService(unittest.TestCase):
    def svc(self):
        return GroqService(api_key="gsk_test_key_123456", model="openai/gpt-oss-120b",
                           fallback_model="openai/gpt-oss-20b", sleep=lambda s: None)

    def test_no_key_raises_not_fakes(self):
        from config import Config
        with mock.patch.object(Config, "GROQ_API_KEY", ""), self.assertRaises(LLMError) as cm:
            GroqService(api_key="", model="openai/gpt-oss-120b").chat_completion([{"role": "user", "content": "x"}])
        self.assertEqual(cm.exception.kind, "no_key")

    def test_non_ascii_key_gives_clear_error_not_a_crash(self):
        bad = GroqService(api_key="gsk_\u2026your\u2019key_1234567890", model="openai/gpt-oss-120b")
        with self.assertRaises(LLMError) as cm:
            bad.chat_completion([{"role": "user", "content": "x"}])
        self.assertEqual(cm.exception.kind, "bad_key")
        ok, msg = bad.test_connection()
        self.assertFalse(ok)
        self.assertIn("console.groq.com", msg)

    def test_quoted_key_is_cleaned(self):
        self.assertEqual(GroqService(api_key=' "gsk_abcdefghijk123" ').api_key, "gsk_abcdefghijk123")

    def test_json_fenced_and_trailing_comma_repaired(self):
        self.assertEqual(parse_json_response('```json\n{"a": [1,2,],}\n```'), {"a": [1, 2]})
        self.assertEqual(parse_json_response('Sure! {"a": {"b": "}"}} thanks'), {"a": {"b": "}"}})
        with self.assertRaises(LLMError):
            parse_json_response("no json here")

    def test_retired_model_falls_back_to_second_model(self):
        calls = []

        def post(url, headers=None, json=None, timeout=None):
            calls.append(json["model"])
            if json["model"] == "openai/gpt-oss-120b":
                return FakeResp(404, {"error": {"code": "model_decommissioned", "message": "The model has been decommissioned"}})
            return FakeResp(200, ok_body('{"ok": true}'))
        with mock.patch("requests.post", post):
            s = self.svc()
            self.assertEqual(s.chat_completion([{"role": "user", "content": "JSON please"}], json_mode=True), {"ok": True})
        self.assertEqual(calls, ["openai/gpt-oss-120b", "openai/gpt-oss-20b"])
        self.assertEqual(s.last_model_used, "openai/gpt-oss-20b")

    def test_rate_limit_retries_then_succeeds(self):
        seq = [FakeResp(429, {"error": {"message": "slow down"}}, {"retry-after": "1"}), FakeResp(200, ok_body("hello"))]
        with mock.patch("requests.post", lambda *a, **k: seq.pop(0)):
            self.assertEqual(self.svc().chat_completion([{"role": "user", "content": "hi"}]), "hello")

    def test_auth_error_is_not_retried(self):
        n = []
        with mock.patch("requests.post", lambda *a, **k: (n.append(1), FakeResp(401, {"error": {"message": "bad key"}}))[1]):
            with self.assertRaises(LLMError) as cm:
                self.svc().chat_completion([{"role": "user", "content": "hi"}])
        self.assertEqual(cm.exception.kind, "auth")
        self.assertEqual(len(n), 1)

    def test_json_mode_400_retries_without_json_mode(self):
        seq = [FakeResp(400, {"error": {"code": "json_validate_failed", "message": "Failed to generate JSON"}}),
               FakeResp(200, ok_body('{"x": 1}'))]
        payloads = []

        def post(url, headers=None, json=None, timeout=None):
            payloads.append(json)
            return seq.pop(0)
        with mock.patch("requests.post", post):
            self.assertEqual(self.svc().chat_completion([{"role": "user", "content": "JSON"}], json_mode=True), {"x": 1})
        self.assertIn("response_format", payloads[0])
        self.assertNotIn("response_format", payloads[1])

    def test_payload_uses_current_param_names(self):
        p = self.svc()._payload("openai/gpt-oss-120b", [], 0.3, 1234, True)
        self.assertEqual(p["max_completion_tokens"], 1234)
        self.assertEqual(p["reasoning_effort"], "low")
        self.assertNotIn("max_tokens", p)


DDG_HTML = """<html><body>
<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.acme.example%2Fproduct&rut=abc">Acme Product</a>
<a class="result__snippet">Acme helps kitchens cut waste.</a></div>
<div class="result"><a class="result__a" href="https://other.example/page">Other</a><a class="result__snippet">Other text</a></div>
</body></html>"""


class TestSearchService(unittest.TestCase):
    def test_ddg_html_parse(self):
        rows = SearchService.parse_ddg_html(DDG_HTML, 5)
        self.assertEqual(rows[0][1], "https://www.acme.example/product")
        self.assertEqual(rows[1][0], "Other")

    def test_all_providers_failing_returns_empty_not_simulated(self):
        s = SearchService(api_key="", max_searches=5)
        with mock.patch.object(SearchService, "_ddg_lib", side_effect=RuntimeError("down")), \
                mock.patch.object(SearchService, "_ddg_html", side_effect=RuntimeError("down")):
            self.assertEqual(s.search("unique offline query zzz"), [])
        self.assertEqual(s.summary()["with_results"], 0)
        self.assertIn("down", s.diagnostics[-1]["error"])

    def test_tavily_uses_bearer_header(self):
        s = SearchService(api_key="tvly-testkey123", max_searches=5)
        captured = {}

        def post(url, headers=None, json=None, timeout=None):
            captured["h"] = headers
            return FakeResp(200, {"results": [{"title": "T", "url": "https://x.example/a", "content": "c"}]})
        with mock.patch("requests.post", post):
            res = s.search("bearer check query 1")
        self.assertEqual(captured["h"]["Authorization"], "Bearer tvly-testkey123")
        self.assertEqual(res[0]["provider"], "Tavily")

    def test_search_budget(self):
        s = SearchService(api_key="", max_searches=1)
        with mock.patch.object(SearchService, "_ddg_lib", return_value=[]), mock.patch.object(SearchService, "_ddg_html", return_value=[]):
            s.search("budget q one")
            s.search("budget q two")
        self.assertIn("budget", s.diagnostics[-1]["error"])


if __name__ == "__main__":
    unittest.main()
