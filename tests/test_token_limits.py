"""
Groq's free tier allows ~8,000 tokens/minute and ~200,000 tokens/day PER MODEL, and rejects any request whose input plus
requested output exceeds the minute budget (HTTP 413). Before the fix, a 413 was treated as a generic bad request (the agent
failed on the spot, without shrinking the request or using the second model), the "answer was cut off" retry made requests
BIGGER, and rate-limit waits were capped at 20 s although Groq's window is 60 s. These tests use Groq's real error wording.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import flask_login  # noqa: F401
except ImportError:
    sys.path.insert(0, "/tmp/shims")

from config import Config
from services import groq_service as gs
from services.groq_service import GroqService, LLMError, TokenPacer, parse_duration, parse_rate_message, fmt_wait
from tests import fakes
from tests.test_pipeline import PipelineBase
from tests.test_core import FakeResp, ok_body

MSG_413 = ("Request too large for model `openai/gpt-oss-120b` in organization `org_x` service tier `on_demand` on tokens per minute (TPM): "
           "Limit 8000, Requested 9500, please reduce your message size and try again.")
MSG_TPM = ("Rate limit reached for model `openai/gpt-oss-120b` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 7000, "
           "Requested 3000. Please try again in 45.2s.")
MSG_TPD = ("Rate limit reached for model `openai/gpt-oss-120b` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 193487, "
           "Requested 7464. Please try again in 6m50.832s.")


def err(status, message, code="rate_limit_exceeded", headers=None):
    return FakeResp(status, {"error": {"code": code, "message": message}}, headers or {})


class Base(unittest.TestCase):
    def setUp(self):
        gs._PACER.reset()
        self.sleeps, self.payloads = [], []
        self.svc = GroqService(api_key="gsk_test_key_123456", model="openai/gpt-oss-120b", fallback_model="openai/gpt-oss-20b",
                               sleep=lambda s: self.sleeps.append(s))

    def post_sequence(self, responses):
        seq = list(responses)

        def post(url, headers=None, json=None, timeout=None):
            self.payloads.append(json)
            r = seq.pop(0) if len(seq) > 1 else seq[0]
            return r(json) if callable(r) else r
        return mock.patch("requests.post", post)

    @staticmethod
    def user(chars):
        return [{"role": "user", "content": "x" * chars}]


class TestParsing(unittest.TestCase):
    def test_durations(self):
        self.assertAlmostEqual(parse_duration("try again in 6m50.832s."), 410.832, places=2)
        self.assertAlmostEqual(parse_duration("7.66s"), 7.66)
        self.assertAlmostEqual(parse_duration("820ms"), 0.82)
        self.assertEqual(parse_duration("1h2m3s"), 3723)
        self.assertIsNone(parse_duration("soon"))
        self.assertEqual(fmt_wait(410), "6 min 50 s")

    def test_real_groq_messages(self):
        a = parse_rate_message(MSG_413)
        self.assertEqual((a["scope"], a["limit"], a["requested"]), ("tpm", 8000, 9500))
        b = parse_rate_message(MSG_TPD)
        self.assertEqual((b["scope"], b["limit"], b["used"]), ("tpd", 200000, 193487))
        self.assertAlmostEqual(b["wait"], 410.832, places=2)
        self.assertAlmostEqual(parse_rate_message(MSG_TPM)["wait"], 45.2)


class TestRequestTooLarge(Base):
    def test_output_is_clamped_up_front_so_the_413_never_happens(self):
        with self.post_sequence([FakeResp(200, ok_body("hi"))]):
            self.svc.chat_completion(self.user(9000), max_tokens=6000)           # ~2,700 tokens in + 6,000 out would be 8,700
        sent = self.payloads[0]["max_completion_tokens"]
        self.assertLessEqual(sent + self.svc._estimate_tokens(self.user(9000)), 8000)
        self.assertLess(sent, 6000)

    def test_a_413_shrinks_the_request_and_retries_instead_of_failing(self):
        with mock.patch.object(Config, "GROQ_TPM_LIMIT", 0):                     # no pre-flight clamp: exercise the reactive path
            with self.post_sequence([err(413, MSG_413), FakeResp(200, ok_body('{"ok": true}'))]):
                out = self.svc.chat_completion(self.user(300), max_tokens=6000, json_mode=True)
        self.assertEqual(out, {"ok": True})
        self.assertEqual(len(self.payloads), 2)
        self.assertLessEqual(self.payloads[1]["max_completion_tokens"], 6000 - (9500 - 8000))   # reduced by the overshoot
        self.assertEqual({p["model"] for p in self.payloads}, {"openai/gpt-oss-120b"})           # same model, no pointless switch

    def test_prompt_larger_than_the_whole_budget_is_trimmed_not_rejected(self):
        with self.post_sequence([FakeResp(200, ok_body("hi"))]):
            self.svc.chat_completion(self.user(40000), max_tokens=3000)           # ~12,000 tokens: can never fit 8,000
        content = self.payloads[0]["messages"][0]["content"]
        self.assertIn("trimmed to fit", content)
        self.assertLess(len(content), 40000)

    def test_pacing_can_be_switched_off_for_paid_plans(self):
        with mock.patch.object(Config, "GROQ_TPM_LIMIT", 0), self.post_sequence([FakeResp(200, ok_body("hi"))]):
            self.svc.chat_completion(self.user(9000), max_tokens=6000)
        self.assertEqual(self.payloads[0]["max_completion_tokens"], 6000)


class TestRateLimits(Base):
    def test_per_minute_wait_follows_groqs_own_hint_not_a_20s_cap(self):
        with self.post_sequence([err(429, MSG_TPM), FakeResp(200, ok_body("hi"))]):
            self.assertEqual(self.svc.chat_completion(self.user(200)), "hi")
        self.assertTrue(any(44 <= s <= 66 for s in self.sleeps), self.sleeps)

    def test_daily_limit_switches_to_the_other_model_and_remembers(self):
        def by_model(payload):
            return err(429, MSG_TPD) if payload["model"] == "openai/gpt-oss-120b" else FakeResp(200, ok_body("ok"))
        with self.post_sequence([by_model]):
            self.assertEqual(self.svc.chat_completion(self.user(200)), "ok")
            self.assertEqual(self.svc.last_model_used, "openai/gpt-oss-20b")
            self.payloads.clear()
            self.svc.chat_completion(self.user(200))
        self.assertEqual({p["model"] for p in self.payloads}, {"openai/gpt-oss-20b"})            # exhausted model is skipped

    def test_both_models_exhausted_gives_a_clear_message_with_the_reset_time(self):
        with self.post_sequence([err(429, MSG_TPD)]):
            with self.assertRaises(LLMError) as cm:
                self.svc.chat_completion(self.user(200))
        self.assertEqual(cm.exception.kind, "daily_limit")
        self.assertIn("resets in about", cm.exception.user_message)
        self.assertIn("200,000", cm.exception.user_message)
        with self.assertRaises(LLMError) as again:                                              # no further calls are wasted
            self.svc.chat_completion(self.user(200))
        self.assertEqual(again.exception.kind, "daily_limit")


class TestPacer(Base):
    def test_busy_model_is_avoided_when_the_other_has_room(self):
        gs._PACER.reserve("openai/gpt-oss-120b", 7500)                  # the main model is nearly full this minute
        with self.post_sequence([FakeResp(200, ok_body("ok"))]):
            self.svc.chat_completion(self.user(3000), max_tokens=2000)
        self.assertEqual(self.payloads[0]["model"], "openai/gpt-oss-20b")

    def test_window_slides_with_a_fake_clock(self):
        now = [1000.0]
        p = TokenPacer(clock=lambda: now[0])
        p.reserve("m", 7000)
        self.assertAlmostEqual(p.wait_needed("m", 2000), 60.0, delta=1)
        now[0] += 61
        self.assertEqual(p.wait_needed("m", 2000), 0.0)

    def test_actual_usage_replaces_the_pessimistic_reservation(self):
        p = TokenPacer()
        h = p.reserve("m", 7500)
        p.settle(h, 1200)
        self.assertEqual(p.wait_needed("m", 5000), 0.0)


class TestPipelineResilience(PipelineBase):
    def test_a_transient_failure_is_retried_automatically(self):
        g = fakes.FakeGroq(fail_once_task="SWOT")
        iid, out = self.run_idea("food", groq=g)
        r = self.results(iid)
        self.assertEqual(out["status"], "completed")
        self.assertNotIn("_error", r["swot_risk"])                        # healed without the user re-running anything
        self.assertEqual(g.calls.count("SWOT AND RISK ANALYSIS"), 2)

    def test_a_permanent_failure_is_still_reported_after_the_retry(self):
        g = fakes.FakeGroq(fail_task="MVP")
        iid, out = self.run_idea("food", groq=g)
        self.assertEqual(out["status"], "completed")
        self.assertIn("_error", self.results(iid)["mvp"])
        self.assertEqual(g.calls.count("MVP AND ROADMAP"), 2)              # exactly one extra attempt, not a loop

    def test_daily_limit_stops_the_run_early_with_the_real_reason(self):
        class Exhausted(fakes.FakeGroq):
            def chat_completion(self, *a, **k):
                raise LLMError("daily_limit", "resets in about 6 min 50 s")
        iid, out = self.run_idea("food", groq=Exhausted())
        self.assertEqual(out["status"], "failed")
        self.assertIn("daily token limit", out["error"])


if __name__ == "__main__":
    unittest.main()
