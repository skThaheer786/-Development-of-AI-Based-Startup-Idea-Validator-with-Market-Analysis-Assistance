"""
Test doubles for an OFFLINE test run (no Groq, no web).

IMPORTANT: everything in this file is synthetic test data. It exists only to exercise the application's
plumbing (evidence gating, verification, scoring, rendering). It is never imported by the application and
must not be read as market research. Company names/domains use the reserved ".example" TLD.
"""
import re
import json

from services.groq_service import GroqService
from services.search_service import SearchService

IDEAS = {
    "food": {
        "title": "Smart Food Waste Management Platform",
        "description": "A platform that helps restaurants, hotel kitchens and canteens track daily food waste with smart bins, "
                       "predict over-production and route surplus meals to NGOs and biogas plants.",
        "category": "food waste tracking software for commercial kitchens",
        "audience": "restaurant owners and canteen managers", "users": "canteen managers",
        "terms": ["food waste", "smart bins", "surplus meals", "biogas", "kitchen"],
        "feature": "smart-bin weight tracking", "regulation": "FSSAI food donation rules",
        "market_usd_b": 1.9, "cagr": 8.4, "unit": "commercial kitchens", "units": 60000, "arpu": 1500,
        "competitors": [("BinSense", "binsense.example", "$49 per month"), ("LeftoverLoop", "leftoverloop.example", None)],
        "ghost": "PhantomWaste",
    },
    "agri": {
        "title": "AI-Based Agriculture Assistant",
        "description": "A mobile assistant that gives smallholder farmers crop-disease diagnosis from leaf photos, local "
                       "weather-based irrigation advice and mandi price alerts in regional languages.",
        "category": "AI crop advisory app for smallholder farmers",
        "audience": "smallholder farmers", "users": "smallholder farmers",
        "terms": ["crop disease", "leaf photos", "irrigation", "mandi prices", "regional languages"],
        "feature": "leaf-photo disease diagnosis", "regulation": "agricultural advisory data rules",
        "market_usd_b": 3.2, "cagr": 12.1, "unit": "smallholder farms", "units": 90000000, "arpu": 20,
        "competitors": [("CropWise", "cropwise.example", None), ("KisanPal", "kisanpal.example", "$3 per month")],
        "ghost": "PhantomFarm",
    },
    "career": {
        "title": "AI-Based Student Career Guidance Platform",
        "description": "A web platform where engineering students take skill assessments and get personalised career paths, "
                       "course suggestions and mock-interview feedback matched to live job openings.",
        "category": "AI career guidance platform for engineering students",
        "audience": "engineering students and placement cells", "users": "engineering students",
        "terms": ["skill assessment", "career paths", "mock interview", "placement cell", "job openings"],
        "feature": "skill-gap career path planner", "regulation": "student data privacy rules",
        "market_usd_b": 5.6, "cagr": 14.7, "unit": "engineering colleges", "units": 4000, "arpu": 3000,
        "competitors": [("PathPilot", "pathpilot.example", "$9 per month"), ("CampusCompass", "campuscompass.example", None)],
        "ghost": "PhantomCareer",
    },
}


IDEAS["skillbridge"] = {
    "title": "SkillBridge AI – Smart Career Readiness Platform",
    "description": "SkillBridge AI scores how ready final-year graduates are for entry-level jobs, builds a personalised upskilling "
                   "roadmap with portfolio projects, and matches ready candidates to employers for interview practice and hiring.",
    "category": "career readiness scoring platform for fresh graduates",
    "audience": "fresh graduates and training institutes", "users": "fresh graduates",
    "terms": ["readiness score", "portfolio projects", "employer matching", "interview practice", "upskilling roadmap"],
    "feature": "readiness-score diagnostic", "regulation": "graduate data consent rules",
    "market_usd_b": 2.4, "cagr": 10.3, "unit": "colleges and training institutes", "units": 12000, "arpu": 2500,
    "competitors": [("ReadyRank", "readyrank.example", "$12 per month"), ("HireBridgeLabs", "hirebridgelabs.example", None)],
    "ghost": "PhantomReady",
}
IDEAS["finwise"] = {
    "title": "FinWise AI – Smart Personal Finance Manager",
    "description": "FinWise AI reads a user's bank statements to categorise spending, forecast monthly cash flow, set savings goals "
                   "and nudge users away from overspending and missed bill payments.",
    "category": "personal budgeting and expense tracking app",
    "audience": "young salaried professionals", "users": "young salaried professionals",
    "terms": ["spending categories", "cash flow forecast", "savings goals", "bill reminders", "overspending alerts"],
    "feature": "cash-flow forecasting", "regulation": "financial data privacy and consent rules",
    "market_usd_b": 1.4, "cagr": 13.2, "unit": "salaried professionals", "units": 20000000, "arpu": 30,
    "competitors": [("PennyPilot", "pennypilot.example", "$4 per month"), ("LedgerLark", "ledgerlark.example", None)],
    "ghost": "PhantomFin",
}


def spec_for(text):
    for key, s in IDEAS.items():
        if s["title"] in text:
            return key, s
    raise AssertionError("prompt did not contain a known test idea title")


class FakeSearch(SearchService):
    """Returns synthetic, idea-specific results; records diagnostics like the real service."""

    def __init__(self, empty=False, **kw):
        super().__init__(api_key="", max_searches=60)
        self.empty = empty
        self.queries = []

    def search(self, query, max_results=6):
        self.queries.append(query)
        if self.empty:
            self.diagnostics.append({"query": query, "provider": None, "results": 0, "error": "offline test", "cached": False})
            return []
        self.searches_used += 1
        key, s = next(((k, v) for k, v in IDEAS.items() if v["category"] in query.lower() or v["users"] in query.lower()
                       or any(t in query.lower() for t in v["terms"])), (None, None))
        low = query.lower()
        for name, dom, _ in (c for v in IDEAS.values() for c in v["competitors"]):
            if name.lower() in low and "official" in low:
                return self._ret(query, [self._norm_r(name, f"https://www.{dom}/", f"{name} - official site")])
        if s is None:
            return self._ret(query, [])
        cat, dom0 = s["category"], "marketresearch.example"
        res = []
        if "market" in low or "growth" in low or "demand" in low or "size" in low:
            res.append(self._norm_r(f"{cat} market report", f"https://www.{dom0}/{key}-market",
                       f"The {cat} market was valued at USD {s['market_usd_b']} billion in 2025. The market is projected to grow at a "
                       f"CAGR of {s['cagr']}% from 2026 to 2032. Demand is driven by {s['terms'][0]} and {s['terms'][1]}."))
            res.append(self._norm_r(f"{s['users']} survey", f"https://www.stats.gov.example/{key}",
                       f"A survey found {s['users']} struggle with {s['terms'][0]}; adoption of {s['terms'][1]} is low."))
        if "alternatives" in low or "companies" in low or "competitor" in low or "similar" in low or "software" in low or "apps" in low or "best" in low:
            names = ", ".join(c[0] for c in s["competitors"]) + f", {s['ghost']}"
            res.append(self._norm_r(f"Best {cat} tools", "https://www.g2.com/" + key, f"Top {cat}: {names}."))
        if "regulat" in low or "compliance" in low or "barrier" in low or "challenge" in low:
            res.append(self._norm_r(f"{s['regulation']} overview", f"https://www.law.example/{key}", f"Operators must follow {s['regulation']}."))
        if "associat" in low or "communit" in low or "gather" in low or "buy" in low:
            res.append(self._norm_r(f"{s['users']} associations", f"https://www.assoc.example/{key}", f"Associations of {s['users']} hold annual meetups."))
        return self._ret(query, res[:max_results])

    def _norm_r(self, title, url, snippet):
        return self._normalize(title, url, snippet, "TestSearch")

    def _ret(self, query, res):
        self.diagnostics.append({"query": query, "provider": "TestSearch" if res else None, "results": len(res),
                                 "error": None if res else "no results", "cached": False})
        return res

    def wikipedia_summary(self, term):
        return None


def fake_fetch_page(url, **kw):
    """Stands in for evidence.fetch_page: only the synthetic competitor domains 'exist'."""
    for s in IDEAS.values():
        for name, dom, price in s["competitors"]:
            if dom in url:
                text = f"{name} helps {s['users']} with {s['terms'][0]}. Features: {s['terms'][1]}, reporting dashboards."
                if price:
                    text += f" Plans start at {price.split(' ')[0]}/month."
                return {"ok": True, "status": 200, "final_url": f"https://www.{dom}/", "title": f"{name} | {s['category']}",
                        "description": f"{name} for {s['users']}", "headings": [f"{name} for {s['terms'][0]}"],
                        "text": text, "pricing_url": "", "error": ""}
    return {"ok": False, "status": None, "final_url": url, "title": "", "description": "", "headings": [],
            "text": "", "pricing_url": "", "error": "unreachable"}


class FakeGroq(GroqService):
    """Deterministic fake LLM. Dispatches on the 'TASK:' line and builds idea-specific JSON from the idea spec."""

    def __init__(self, generic_swot_first=False, fail_task=None, sizing_mode="clean", fail_once_task=None, **kw):
        super().__init__(api_key="test-key-1234567890", model="openai/gpt-oss-120b")
        self.calls = []
        self.generic_swot_first = generic_swot_first
        self.fail_once_task = fail_once_task    # raises a transient error the FIRST time this task runs
        self._failed_once = False
        self.sizing_mode = sizing_mode      # clean | messy | topdown_only | nulls
        self.fail_task = fail_task
        self._swot_calls = 0

    def chat_completion(self, messages, temperature=0.7, max_tokens=2048, json_mode=False, retries=3, fast=False):
        user = messages[-1]["content"]
        m = re.search(r"TASK: ([A-Z /]+)", user)
        task = m.group(1).strip() if m else "CHAT"
        self.calls.append(task)
        self.last_model_used = self.model
        if self.fail_once_task and task.startswith(self.fail_once_task) and not self._failed_once:
            self._failed_once = True
            from services.groq_service import LLMError
            raise LLMError("rate_limit")
        if self.fail_task and task.startswith(self.fail_task):
            from services.groq_service import LLMError
            raise LLMError("rate_limit")
        if not json_mode:
            return "OK"
        key, s = spec_for(user + " " + messages[0]["content"])
        if "SIZING" in task:
            self.sizing_retries = getattr(self, "sizing_retries", 0) + 1
            return {"sizing_assumptions": self._sizing_block(s, "clean" if self.sizing_mode in ("messy", "nulls_then_clean") else self.sizing_mode)}
        fn = getattr(self, "_" + task.split()[0].lower())
        out = fn(user, key, s)
        if task.startswith("MARKET RESEARCH"):
            out["sizing_assumptions"] = self._sizing_block(s, "nulls" if self.sizing_mode == "nulls_then_clean" else self.sizing_mode)
        return out

    @staticmethod
    def _sizing_block(s, mode):
        """The sizing assumptions as a model might really return them."""
        base = {"customer_unit": s["unit"], "currency": "USD", "geography": "India"}
        if mode == "messy":                      # numbers as text, percent signs, bare numbers, missing share
            base.update({"unit_count": f"{s['units']:,}", "annual_revenue_per_unit": f"${s['arpu']:,}",
                         "serviceable_share": "20%", "obtainable_share": 0.03})
        elif mode == "topdown_only":             # bottom-up inputs unusable, top-down share usable
            base.update({"unit_count": None, "annual_revenue_per_unit": "n/a",
                         "topdown_serviceable_share": {"value": "5%", "low": "3%", "high": "8%", "basis": "ai_assumption", "note": "niche share"},
                         "obtainable_share": {"value": 0.04, "basis": "ai_assumption", "note": "3-year share"}})
        elif mode == "nulls":
            base.update({"unit_count": None, "annual_revenue_per_unit": 0, "serviceable_share": None, "obtainable_share": "unknown"})
        else:                                    # clean
            base.update({"unit_count": {"value": s["units"], "low": s["units"] * 0.7, "high": s["units"] * 1.3, "basis": "ai_assumption", "source_ids": [], "note": "rough count"},
                         "annual_revenue_per_unit": {"value": s["arpu"], "basis": "ai_assumption", "source_ids": [], "note": "price x seats"},
                         "serviceable_share": {"value": 0.2, "basis": "ai_assumption", "source_ids": [], "note": "reachable share"},
                         "obtainable_share": {"value": 0.03, "basis": "ai_assumption", "source_ids": [], "note": "3-year share"}})
        return base

    # ---- tasks ----
    def _idea(self, user, key, s):
        cat = s["category"]
        return {"business_concept": s["description"][:120], "problem_statement": f"{s['users']} lose time and money on {s['terms'][0]}.",
                "proposed_solution": f"{s['feature']} for {s['users']}", "target_audience": s["audience"], "industry": s["category"].split()[0].title(),
                "market_category": cat, "customer_type": "B2B", "geography": "India", "revenue_model": "Subscription",
                "unique_value_proposition": s["feature"], "key_terms": s["terms"],
                "search_queries": {"market": [f"{cat} market size", f"{cat} market growth CAGR", f"{s['terms'][0]} market trends"],
                                   "customer_demand": [f"{s['users']} {s['terms'][0]} demand statistics"],
                                   "competitors": [f"{cat} alternatives", f"best {s['terms'][1]} software", f"{cat} companies"],
                                   "risks": [f"{s['terms'][0]} regulation compliance", f"{cat} adoption barriers challenges"],
                                   "channels": [f"{s['users']} associations communities"]},
                "assumptions_made": [], "idea_quality_notes": [], "suggested_tags": ["test"]}

    def _market(self, user, key, s):
        ids = re.findall(r"^\[(S\d+)\]", user, flags=re.M)
        first = ids[:2]
        fa = [{"id": i, "relevant": True, "scope": "segment", "note": f"describes the {s['category']} market"}
              for i in re.findall(r"^(F\d+):", user, flags=re.M)]
        t = s["terms"]
        return {
            "market_summary": f"Buyers of {s['category']} are {s['users']}; spending is driven by {t[0]} and {t[1]}.",
            "demand_signals": [{"signal": f"{s['users']} report {t[0]} pain", "detail": f"Surveyed {s['users']} struggle with {t[0]}", "source_ids": first[1:2] or []},
                               {"signal": f"Low adoption of {t[1]}", "detail": f"{t[1]} is rarely used by {s['users']}", "source_ids": []},
                               {"signal": f"{t[2]} interest", "detail": f"Interest in {t[2]} among {s['users']}", "source_ids": []}],
            "trends": [{"trend": f"Growing {t[1]} adoption", "impact": f"More {s['users']} expect {t[1]}", "source_ids": first[:1]},
                       {"trend": f"{s['regulation']} tightening", "impact": f"{s['feature']} helps comply", "source_ids": []},
                       {"trend": f"Cheaper {t[3]} data", "impact": f"Makes {s['feature']} viable", "source_ids": []}],
            "opportunities": [{"opportunity": f"{s['feature']} for small {s['users']} groups", "why": f"Existing tools ignore {t[4]}", "source_ids": []},
                              {"opportunity": f"Bundle {t[3]} insights", "why": f"{s['users']} lack {t[3]} visibility", "source_ids": []},
                              {"opportunity": f"Partner with {t[0]} stakeholders", "why": "Shared incentives", "source_ids": []}],
            "customer_segments": [{"segment_name": s["users"].title(), "persona": s["users"], "pain_point": f"{t[0]} costs", "willingness_to_pay": "Medium - budget limited", "acquisition_channel": "associations"}],
            "unmet_needs": [f"Affordable {s['feature']}", f"{t[4]} support for {s['users']}"],
            "figure_assessment": fa,
            "sizing_assumptions": {"customer_unit": s["unit"], "currency": "USD", "geography": "India",
                "unit_count": {"value": s["units"], "low": s["units"] * 0.7, "high": s["units"] * 1.3, "basis": "ai_assumption", "source_ids": [], "note": "rough count"},
                "annual_revenue_per_unit": {"value": s["arpu"], "basis": "ai_assumption", "source_ids": [], "note": "price x seats"},
                "serviceable_share": {"value": 0.2, "basis": "ai_assumption", "source_ids": [], "note": "reachable share"},
                "obtainable_share": {"value": 0.03, "basis": "ai_assumption", "source_ids": [], "note": "3-year share"}},
            "ratings": {"demand_strength": {"rating": 4, "reason": f"Surveyed {s['users']} report {t[0]} pain, a clear demand signal."},
                        "growth_outlook": {"rating": 4, "reason": f"A source reports growth for {s['category']}."},
                        "market_accessibility": {"rating": 3, "reason": f"{s['users']} are reachable via associations but fragmented."}}}

    def _competitor(self, user, key, s):
        if "IDENTIFICATION" in user:
            cands = [{"name": n, "official_website": None, "competitor_type": "Emerging" if n == s["competitors"][-1][0] else "Direct", "why_relevant": f"serves {s['users']}",
                      "from_evidence": True, "source_ids": []} for n, _, _ in s["competitors"]]
            cands.append({"name": s["ghost"], "official_website": None, "competitor_type": "Indirect", "why_relevant": "named in a listicle", "from_evidence": True, "source_ids": []})
            return {"candidates": cands}
        names = re.findall(r"^### (.+?) \(", user, flags=re.M)
        t = s["terms"]
        return {"profiles": [{"name": n, "products": [f"{n} platform"], "key_features": [t[1]], "target_customers": s["users"],
                              "positioning": f"{n} serves {s['users']}", "overlap_with_idea": f"both address {t[0]}",
                              "site_strengths": [f"{n} emphasises {t[1]}"], "ai_weaknesses": [f"No mention of {s['feature']} for {s['users']}"], "gaps_vs_idea": f"No mention of {s['feature']} on the site", "differentiation_opportunity": f"Lead with {s['feature']} for {t[4]}",
                              "threat_level": "Medium", "threat_reason": "established"} for n in names],
                "opportunities": [{"opportunity": f"{s['feature']} is not offered by {names[0] if names else 'incumbents'}", "why": f"pages never mention {s['feature']}", "competitors_lacking": names}],
                "status_quo_alternatives": [f"Spreadsheets kept by {s['users']}"],
                "comparison_features": [{"capability": s["feature"], "idea_offers": True, "competitors": {n: "no" for n in names}},
                                        {"capability": t[1], "idea_offers": True, "competitors": {n: "yes" for n in names}}],
                "market_saturation": "Medium", "saturation_reason": f"{len(names)} verified players for {s['category']}",
                "positioning_recommendation": f"Position {s['feature']} against {', '.join(names)}",
                "ratings": {"differentiation_potential": {"rating": 4, "reason": f"{s['feature']} is absent on competitor pages."},
                            "competitive_headroom": {"rating": 3, "reason": f"{', '.join(names)} are established but narrow."},
                            "switching_barriers": {"rating": 3, "reason": f"{s['users']} switch tools infrequently."}}}

    def _swot(self, user, key, s):
        self._swot_calls += 1
        t = s["terms"]
        if self.generic_swot_first and self._swot_calls == 1:
            g = [{"point": "Leverages cutting-edge AI-native workflow for seamless integration", "why": "", "basis": "ai_inference", "source_ids": []}] * 4
            return {"swot": {q: g for q in ("strengths", "weaknesses", "opportunities", "threats")}, "cross_strategies": {}, "risks": [
                {"category": "Market", "risk": "Early brand recognition is limited", "why_this_idea": "", "impact_score": 5, "likelihood_score": 5, "mitigation_steps": ["x"], "realistic_solution": "x"}] * 6}
        mk = lambda p, w: {"point": p, "why": w, "basis": "idea", "source_ids": []}
        sw = {"strengths": [mk(f"{s['feature']} is the core of the product", f"{s['users']} need it") for _ in range(1)] + [mk(f"Focus on {t[0]} for {s['users']}", "narrow niche"), mk(f"{t[1]} data moat", "accumulates"), mk(f"Low-cost {t[3]} approach", "cheap")],
              "weaknesses": [mk(f"Needs {t[3]} data from {s['users']}", "cold start"), mk(f"{s['feature']} accuracy unproven", "no pilots"), mk(f"Small team versus {s['competitors'][0][0] if False else 'incumbents'} {t[0]}", "resources"), mk(f"{t[4]} support is costly", "services")],
              "opportunities": [mk(f"{s['regulation']} creates demand", "compliance"), mk(f"{t[4]} gaps left by competitors", "whitespace"), mk(f"Partnerships around {t[0]}", "channel"), mk(f"Upsell {t[2]} analytics", "expansion")],
              "threats": [mk(f"{s['competitors'][0][0]} could add {s['feature']}", "incumbent"), mk(f"{s['regulation']} may change", "regulatory"), mk(f"{s['users']} budgets are tight", "budget"), mk(f"Free {t[1]} alternatives", "substitutes")]}
        risks = [{"category": c, "risk": f"{c} risk: {t[i % 5]} for {s['users']}", "why_this_idea": f"Because {s['feature']} depends on {t[i % 5]}",
                  "impact_score": 4 + i, "likelihood_score": 3 + (i % 4), "impact_reason": f"A {c} failure delays {s['feature']}", "likelihood_reason": f"No pilot of {s['feature']} yet", "mitigation_steps": [f"Pilot {s['feature']} with 3 {s['users']}"],
                  "realistic_solution": f"Run a 4-week pilot of {s['feature']}", "early_warning_sign": f"<30% of {s['users']} activate", "effort": "Low", "source_ids": []}
                 for i, c in enumerate(["Technical", "Financial", "Market", "Operational", "Legal/Regulatory", "Competitive"])]
        return {"swot": sw, "cross_strategies": {"SO": f"Use {s['feature']} to win {t[4]}", "WO": "", "ST": "", "WT": ""}, "risks": risks}

    def _mvp(self, user, key, s):
        t = s["terms"]
        return {"team_assumption": "2 student developers, part-time", "riskiest_assumption": f"{s['users']} will adopt {s['feature']}",
                "team_size": 2, "hours_per_week_each": 15,
                "build_order": [{"step": 1, "what": s["feature"], "why_first": f"it tests whether {s['users']} care"}],
                "cost_estimate": {"currency": "USD", "assumptions": ["2 students, free-tier hosting", "own time valued at $10/hour"],
                                  "items": [{"category": "Development", "type": "own_time", "amount_low": 2000, "amount_high": 3000, "note": "240 hours"},
                                            {"category": "Hosting & tools", "type": "cash", "amount_low": 0, "amount_high": 200, "note": "free tiers"}],
                                  "monthly_running_cost": {"low": 0, "high": 40, "note": "hosting"}},
                "required_resources": [f"Access to 3 {s['users']} for testing"], "testing_methods": ["Usability tests with 5 users"],
                "must_have": [{"feature": s["feature"], "why": f"core pain: {t[0]}", "effort": "Medium", "impact": "High", "effort_hours": 120},
                              {"feature": f"{t[1]} dashboard", "why": "visibility", "effort": "Low", "impact": "High", "effort_hours": 60}],
                "should_have": [{"feature": f"{t[2]} reports", "why": "retention"}], "could_have": [{"feature": f"{t[4]} integrations", "why": "later"}],
                "wont_have_yet": [{"feature": "native mobile app", "reason": "web first"}],
                "roadmap": [{"phase": "Prototype", "weeks": "1-3", "goal": f"Build {s['feature']}", "deliverables": ["demo"], "exit_criteria": f"3 {s['users']} try it"},
                            {"phase": "Pilot", "weeks": "4-8", "goal": f"Pilot with {s['users']}", "deliverables": ["pilot"], "exit_criteria": "2 repeat users"}],
                "recommended_tech_stack": [{"layer": "Backend", "technology": "FastAPI", "reason": "free tier"}], "data_needs": [f"{t[3]} data"],
                "validation_experiments": [{"experiment": f"Interview 10 {s['users']}", "success_metric": "6 want pilot", "duration": "2 weeks"}],
                "ratings": {"technical_feasibility": {"rating": 4, "reason": f"{s['feature']} is buildable by a small team."},
                            "data_and_integration_dependency": {"rating": 3, "reason": f"Needs {t[3]} data from {s['users']}."},
                            "time_to_first_version": {"rating": 4, "reason": "A first version fits in 8 weeks."}}}

    def _go(self, user, key, s):
        t = s["terms"]
        return {"positioning_statement": f"For {s['users']} who struggle with {t[0]}, we offer {s['feature']}.",
                "ideal_customer_profile": {"who": s["users"], "size_or_stage": "small", "trigger_event": f"{t[0]} audit", "decision_maker": "owner"},
                "revenue_models": [{"model": "Subscription", "fit_reason": f"{s['users']} like predictable cost", "example_price": f"${s['arpu'] / 12:.0f}/month", "tradeoff": "churn"}] * 1 +
                                  [{"model": "Pilot fee", "fit_reason": f"proves {s['feature']}", "example_price": "$100", "tradeoff": "small"}, {"model": "Usage", "fit_reason": f"scales with {t[1]}", "example_price": "$0.1", "tradeoff": "variable"}],
                "recommended_revenue_model": "Subscription",
                "marketing_strategy": {"core_message": f"{s['feature']} for {s['users']}", "competitor_positioning": f"Versus {s['competitors'][0][0]}: lead with {s['feature']}",
                                       "channels": [{"channel": f"{s['users']} associations", "tactic": f"Demo {s['feature']} at meetups", "budget_note": "free"}], "content_ideas": ["short demo video"]},
                "pricing_strategy": {"assumptions": [f"{s['users']} budget about ${s['arpu']} per year"], "rationale": "competitor prices where found", "tiers": [{"name": "Starter", "price": f"${s['arpu'] / 12:.0f}/month", "who_its_for": s["users"], "includes": [s["feature"]], "basis": "ai_suggestion"}]},
                "year_one_targets": {"paying_customers": 20, "avg_annual_revenue_per_customer": s["arpu"], "currency": "$", "reasoning": f"20 {s['users']} pilots convert"},
                "first_customers": {"where_to_find": [{"channel": f"{s['users']} associations", "specific_action": f"Email 30 {s['users']} via association lists", "why_it_fits": "concentrated", "source_ids": ["S1"]}],
                                    "outreach_message": f"Hi, we help {s['users']} with {t[0]}.", "discovery_questions": ["How do you handle it today?"], "first_10_customers_plan": f"Offer free {s['feature']} pilots"},
                "launch_roadmap_90_days": [{"phase": "Days 1-30", "goal": f"Interview {s['users']}", "actions": [f"Interview 15 {s['users']}"], "success_metric": "15 interviews"},
                                           {"phase": "Days 31-60", "goal": "Pilot", "actions": [f"Run 3 pilots of {s['feature']}"], "success_metric": "3 pilots"},
                                           {"phase": "Days 61-90", "goal": "Convert", "actions": [f"Convert 5 {s['users']} to paid"], "success_metric": "5 paid"}],
                "acquisition_channels": ["associations"],
                "ratings": {"customer_reachability": {"rating": 3, "reason": f"{s['users']} are reachable via associations."},
                            "willingness_to_pay": {"rating": 3, "reason": f"Evidence of spend on {t[0]} is limited."},
                            "unit_economics_plausibility": {"rating": 3, "reason": f"${s['arpu']} per year per customer is plausible but untested."}}}

    def _advisory(self, user, key, s):
        return {"advisory_summary": f"Focus on {s['feature']} for {s['users']}.", "top_strategic_recommendations": [{"recommendation": f"Pilot {s['feature']}", "reason": "test demand"}],
                "key_red_flags_to_monitor": [{"flag": f"Low activation among {s['users']}", "how_to_measure": "weekly active"}],
                "founder_elevator_pitch": f"{s['feature']} for {s['users']}", "first_100_customers_playbook": [f"Email {s['users']}"], "pricing_and_unit_economics_advice": "test prices"}

    def _final(self, user, key, s):
        return {"executive_summary": f"{s['title']} targets {s['users']} with {s['feature']}.\nCompetitors such as {s['competitors'][0][0]} lack it.\nProve {s['users']} will pay.",
                "biggest_strength": s["feature"], "biggest_weakness": f"unproven {s['feature']}", "best_market_opportunity": f"{s['terms'][4]} gap",
                "recommended_next_action": f"Interview 10 {s['users']}", "go_no_go_verdict": "Proceed carefully", "next_immediate_steps": ["a", "b", "c"]}
