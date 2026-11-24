"""
The validator must work for ANY idea in ANY industry. These tests push six unrelated industries through the full
pipeline (offline fakes, see tests/fakes.py) and check that nothing in the application is tied to particular ideas.
"""
import os
import re
import sys
import json
import unittest
import pathlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import flask_login  # noqa: F401
except ImportError:
    sys.path.insert(0, "/tmp/shims")

from tests import fakes
from tests.test_pipeline import PipelineBase

ROOT = pathlib.Path(__file__).resolve().parent.parent


def spec(title, desc, cat, users, terms, feature, regulation, comps, ghost, usd_b, cagr, unit, units, arpu):
    return {"title": title, "description": desc, "category": cat, "audience": users, "users": users, "terms": terms,
            "feature": feature, "regulation": regulation, "market_usd_b": usd_b, "cagr": cagr, "unit": unit, "units": units,
            "arpu": arpu, "competitors": comps, "ghost": ghost}


EXTRA = {
    "health": spec("MediRemind – Medication Adherence App for Elderly Patients",
                   "An app that reminds elderly patients to take medicines, alerts caregivers about missed doses and shares adherence reports with doctors.",
                   "medication adherence app for elderly patients", "elderly patients and caregivers",
                   ["pill reminders", "missed doses", "caregiver alerts", "adherence reports", "pharmacy refills"],
                   "missed-dose caregiver alerts", "medical data privacy rules",
                   [("DoseMate", "dosemate.example", "$5 per month"), ("PillPal", "pillpal.example", None)], "PhantomPill", 2.8, 9.6,
                   "households with elderly patients", 3000000, 60),
    "legal": spec("ClauseCheck – Contract Review Tool for Freelancers",
                  "A tool that scans freelance contracts, highlights risky clauses such as unpaid revisions and late-payment terms, and suggests fair rewrites.",
                  "contract review software for freelancers", "freelancers and small agencies",
                  ["contract scanning", "risky clauses", "late-payment terms", "fair rewrites", "freelance invoices"],
                  "risky-clause highlighter", "legal advice disclaimer rules",
                  [("ClauseWise", "clausewise.example", "$15 per month"), ("DealGuard", "dealguard.example", None)], "PhantomClause", 1.2, 11.4,
                  "freelancers", 15000000, 120),
    "climate": spec("CarbonLens – Carbon Footprint Tracker for Small Businesses",
                    "A dashboard that converts electricity bills and fuel receipts into a monthly carbon footprint and suggests low-cost reduction steps.",
                    "carbon footprint tracking for small businesses", "small business owners",
                    ["carbon footprint", "electricity bills", "fuel receipts", "emission reports", "reduction steps"],
                    "bill-to-emissions converter", "emission reporting standards",
                    [("GreenLedger", "greenledger.example", "$29 per month"), ("EcoMeter", "ecometer.example", None)], "PhantomCarbon", 6.1, 18.2,
                    "small businesses", 2000000, 240),
    "logistics": spec("RouteMate – Last-Mile Delivery Planner for Local Shops",
                      "A planner that batches orders from small local shops, assigns them to nearby riders and shows live delivery status to customers.",
                      "last-mile delivery planning for local shops", "local shop owners",
                      ["delivery batching", "rider assignment", "live tracking", "order routes", "delivery slots"],
                      "order batching engine", "gig worker regulations",
                      [("DropSmart", "dropsmart.example", None), ("RiderHub", "riderhub.example", "$19 per month")], "PhantomRoute", 4.5, 15.0,
                      "local shops", 800000, 300),
    "ecom": spec("StyleSwap – Peer-to-Peer Clothing Rental Marketplace",
                 "A marketplace where students rent out party outfits to each other, with deposits, cleaning partners and size-matching.",
                 "peer-to-peer clothing rental marketplace", "college students",
                 ["outfit rentals", "deposit handling", "cleaning partners", "size matching", "campus delivery"],
                 "size-matching rental search", "consumer protection rules",
                 [("WardrobeLoop", "wardrobeloop.example", None), ("RentTheLook", "rentthelook.example", "$25 per rental")], "PhantomStyle", 1.7, 12.5,
                 "college students", 9000000, 40),
    "edtech": spec("LinguaPal – Spoken English Practice for Rural Students",
                   "A voice-based app where rural school students practise spoken English with an AI partner and get pronunciation feedback in their mother tongue.",
                   "spoken English practice app for rural students", "rural school students and teachers",
                   ["spoken English", "pronunciation feedback", "voice practice", "mother tongue", "school licences"],
                   "mother-tongue pronunciation coach", "children's data protection rules",
                   [("SpeakEasy", "speakeasy.example", "$4 per month"), ("TalkTutor", "talktutor.example", None)], "PhantomSpeak", 3.9, 16.4,
                   "rural schools", 600000, 500),
}


class TestAnyIdea(PipelineBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        fakes.IDEAS.update(EXTRA)
        cls.runs = {k: cls.run_idea(k) for k in EXTRA}

    @classmethod
    def tearDownClass(cls):
        for k in EXTRA:
            fakes.IDEAS.pop(k, None)
        super().tearDownClass()

    def test_every_industry_completes_with_full_analysis(self):
        for k, (iid, out) in self.runs.items():
            self.assertEqual(out["status"], "completed", k)
            r = self.results(iid)
            for agent in ("market", "competitors", "swot_risk", "mvp", "gtm", "report"):
                self.assertNotIn("_error", r[agent], f"{k}/{agent}")
            self.assertEqual(len(r["competitors"]["competitors"]), 2, k)
            self.assertNotIn(EXTRA[k]["ghost"], [c["name"] for c in r["competitors"]["competitors"]])

    def test_each_industry_gets_its_own_vocabulary_only(self):
        blobs = {k: json.dumps({n: v for n, v in self.results(iid).items() if n in ("market", "competitors", "swot_risk", "mvp", "gtm")}).lower()
                 for k, (iid, _) in self.runs.items()}
        for k, blob in blobs.items():
            self.assertIn(EXTRA[k]["feature"].lower(), blob)
            for other, o in EXTRA.items():
                if other != k:
                    self.assertNotIn(o["feature"].lower(), blob, f"{k} contains {other}'s feature")
                    self.assertNotIn(o["competitors"][0][0].lower(), blob)

    def test_scores_follow_the_same_formula_for_every_industry(self):
        for k, (iid, _) in self.runs.items():
            rep = self.results(iid)["report"]
            dims = rep["score_breakdown"]["dimensions"]
            tw = sum(d["weight"] for d in dims.values())
            self.assertEqual(rep["viability_score"], round(sum(d["score"] * d["weight"] for d in dims.values()) / tw), k)
            self.assertIn(rep["recommendation"], ("PROCEED", "IMPROVE", "RECONSIDER"))
            self.assertTrue(rep["verdict_explanation"])

    def test_application_source_has_no_hardcoded_ideas(self):
        banned = re.compile(r"skillbridge|finwise|medi ?remind|clausecheck|carbonlens|routemate|styleswap|linguapal", re.I)
        offenders = []
        for folder in ("app.py", "agents", "services", "orchestration", "database", "templates", "static"):
            p = ROOT / folder
            files = [p] if p.is_file() else [f for f in p.rglob("*") if f.suffix in (".py", ".html", ".js", ".css")]
            for f in files:
                if banned.search(f.read_text(encoding="utf-8", errors="ignore")):
                    offenders.append(str(f.relative_to(ROOT)))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
