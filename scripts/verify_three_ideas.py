#!/usr/bin/env python
"""
Run the real research pipeline on three different startup ideas and check that the reports are
different, relevant and properly sourced.

    python scripts/verify_three_ideas.py            # LIVE: SkillBridge AI + FinWise AI (needs GROQ_API_KEY in .env)
    python scripts/verify_three_ideas.py --all      # LIVE: those two plus three ideas from other industries
    python scripts/verify_three_ideas.py --mock     # offline plumbing check with the test doubles

Writes scripts/verification_report.md and prints a summary. A temporary database is used, so your own
data is never touched.
"""
import os
import sys
import json
import time
import shutil
import pathlib
import tempfile
import itertools

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Your two ideas (descriptions written for testing; replace them with your own wording if you like).
NAMED = [
    ("SkillBridge AI – Smart Career Readiness Platform",
     "A platform that tests a student's job-readiness through skill assessments and project reviews, shows the gap against "
     "real job requirements, and builds a personalised learning roadmap, portfolio and interview practice plan."),
    ("FinWise AI – Smart Personal Finance Manager",
     "A personal finance app that reads bank and UPI transactions, categorises spending automatically, forecasts cash flow, "
     "and gives personalised saving and budgeting advice with bill and subscription alerts."),
]
# Extra ideas from other industries, used with --all
EXTRA = [
    ("Smart Food Waste Management Platform",
     "A platform that helps restaurants, hotel kitchens and canteens track daily food waste, predict over-production "
     "and route surplus food to NGOs, animal-feed buyers and biogas plants."),
    ("AI-Based Agriculture Assistant",
     "A mobile assistant for farmers that diagnoses crop disease from leaf photos, gives weather-based irrigation advice "
     "and alerts them to market prices, in regional languages."),
    ("AI-Based Student Career Guidance Platform",
     "A web platform where students take skill assessments and receive personalised career paths, course suggestions "
     "and mock-interview feedback matched to live job openings."),
]
IDEAS = NAMED


def main():
    mock = "--mock" in sys.argv
    from config import Config
    tmp = tempfile.mkdtemp()
    Config.DATABASE_PATH = os.path.join(tmp, "verify.db")
    Config.EXPORTS_DIR = pathlib.Path(tmp) / "exports"
    from database.db import init_db
    from database.models import User, StartupIdea, AnalysisResult
    from orchestration.pipeline import OrchestrationPipeline
    from services import quality
    init_db()
    user = User.create("verifier", "verify@example.com", "verify-pass-1", "Verifier")
    uid = getattr(user, "id", user)

    kwargs = {}
    if mock:
        sys.path.insert(0, str(ROOT))
        from tests import fakes
        import agents.competitor_agent as ca
        ca.fetch_page = fakes.fake_fetch_page
        keys = ("skillbridge", "finwise", "food", "agri", "career") if "--all" in sys.argv else ("skillbridge", "finwise")
        ideas = [(fakes.IDEAS[k]["title"], fakes.IDEAS[k]["description"]) for k in keys]
        make = lambda: dict(groq_service=fakes.FakeGroq(), search_service=fakes.FakeSearch())
    else:
        from services.groq_service import GroqService
        if not GroqService().is_available():
            sys.exit("GROQ_API_KEY is not set. Add it to .env, or run with --mock for an offline plumbing check.")
        ideas, make = (NAMED + EXTRA if "--all" in sys.argv else NAMED), dict

    runs = {}
    for title, desc in ideas:
        print(f"\n>>> Analysing: {title}")
        t0 = time.time()
        iid = StartupIdea.create(uid, title, desc)
        out = OrchestrationPipeline(iid, uid, **make()).run_synchronous()
        print(f"    {out.get('status')} in {time.time() - t0:.0f}s  score={out.get('viability_score')}  {out.get('recommendation') or out.get('error')}")
        runs[title] = {k: v["data"] for k, v in AnalysisResult.get_all_for_idea(iid).items()}

    lines = ["# Three-idea verification report", f"Mode: {'MOCK (offline test doubles)' if mock else 'LIVE (real Groq + web search)'}", ""]

    def text_block(r, keys):
        return json.dumps({k: r.get(k) for k in keys}, ensure_ascii=False)

    for title, r in runs.items():
        m, c, s, rep = (r.get("market", {}), r.get("competitors", {}), r.get("swot_risk", {}), r.get("report", {}))
        lines += [f"## {title}", f"- Viability: **{rep.get('viability_score')}** ({rep.get('recommendation')}), confidence {rep.get('confidence', {}).get('level')}",
                  f"- Web sources: {len(m.get('research_sources', []))}; sourced market figures: {len(m.get('verified_figures', []))}; CAGR: {m.get('cagr')}",
                  f"- TAM/SAM/SOM: {m.get('tam')} / {m.get('sam')} / {m.get('som')}",
                  f"- Verified competitors: {', '.join(x['name'] for x in c.get('competitors', [])) or 'none'}",
                  f"- Unverified names excluded: {', '.join(u['name'] for u in c.get('unverified_mentions', [])) or 'none'}",
                  f"- Top risks: " + "; ".join(x['risk'][:80] for x in s.get('risks', [])[:3]), ""]
        for agent, d in r.items():
            if isinstance(d, dict) and d.get("_error"):
                lines.append(f"- WARNING {agent} failed: {d['_error']}")

    lines += ["## Cross-idea similarity (lower = more idea-specific)", "| Pair | SWOT+risks | Recommendations (MVP+GTM) | Competitors shared |", "|---|---|---|---|"]
    flags = []
    for (a, ra), (b, rb) in itertools.combinations(runs.items(), 2):
        sw = quality.similarity(text_block(ra.get("swot_risk", {}), ["swot", "risks"]), text_block(rb.get("swot_risk", {}), ["swot", "risks"]))
        rc = quality.similarity(text_block(ra.get("mvp", {}), ["must_have", "roadmap"]) + text_block(ra.get("gtm", {}), ["first_customers", "launch_roadmap_90_days"]),
                                text_block(rb.get("mvp", {}), ["must_have", "roadmap"]) + text_block(rb.get("gtm", {}), ["first_customers", "launch_roadmap_90_days"]))
        shared = {x["name"] for x in ra.get("competitors", {}).get("competitors", [])} & {x["name"] for x in rb.get("competitors", {}).get("competitors", [])}
        lines.append(f"| {a[:28]} vs {b[:28]} | {sw:.2f} | {rc:.2f} | {', '.join(shared) or '-'} |")
        if sw > 0.45 or rc > 0.45:
            flags.append(f"{a} vs {b}")
    lines += ["", "Rule of thumb: pairs above 0.45 share a lot of wording and deserve a manual read." if not mock else
              "NOTE: in --mock mode the fake LLM reuses sentence templates, so similarity is not meaningful.",
              ("Flagged pairs: " + "; ".join(flags)) if flags and not mock else "No pair flagged."]
    out_path = ROOT / "scripts" / "verification_report.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print("\n" + "\n".join(lines))
    print(f"\nSaved: {out_path}")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
