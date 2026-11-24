import json
from .base_agent import BaseAgent
from services.groq_service import LLMError


def _t(item, *keys):
    """Text of a str/dict item."""
    if isinstance(item, dict):
        for k in keys:
            if item.get(k):
                return str(item[k])
        return ""
    return str(item or "")


def _compact(ctx):
    """Factual digest of ALL validation results for prompts (kept short; every field comes from the stored analysis)."""
    ex, mk = ctx.get("extractor_data", {}) or {}, ctx.get("market_data", {}) or {}
    cp, sw = ctx.get("competitor_data", {}) or {}, (ctx.get("swot_data") or ctx.get("swot_risk_data") or {})
    mvp, gtm, rp = ctx.get("mvp_data", {}) or {}, ctx.get("gtm_data", {}) or {}, ctx.get("report_data", {}) or {}
    dims = ((rp.get("score_breakdown") or {}).get("dimensions") or {})
    ce = mvp.get("cost_estimate") or {}
    fc = gtm.get("first_customers") or {}
    digest = {
        "idea": {"title": ctx.get("title"), "description": (ctx.get("raw_description") or "")[:700], "audience": ex.get("target_audience"),
                 "problem": ex.get("problem_statement"), "solution": ex.get("proposed_solution"), "industry": ex.get("industry"),
                 "geography": ex.get("geography")},
        "scores": {"viability": rp.get("viability_score"), "verdict": rp.get("recommendation"), "why_verdict": rp.get("verdict_explanation"),
                   "categories": {d.get("label"): d.get("score") for d in dims.values()},
                   "held_back_by": [f"{r.get('factor_label')} ({r.get('rating')}/5): {r.get('reason')}" for r in (rp.get("main_score_reducers") or [])[:3]],
                   "confidence": (rp.get("confidence") or {}).get("level")},
        "market": {"summary": mk.get("market_summary"), "cagr": mk.get("cagr"), "tam": mk.get("tam"), "sam": mk.get("sam"), "som": mk.get("som"),
                   "sizing_formula": (mk.get("sizing") or {}).get("formula"),
                   "sourced_figures": [f"{f.get('value_text')} - {f.get('source_title')} ({f.get('url')})" for f in mk.get("verified_figures", [])[:3]],
                   "demand": [_t(d, "signal") for d in mk.get("demand_signals", [])[:4]],
                   "trends": [_t(d, "trend") for d in mk.get("trends", [])[:3]],
                   "opportunities": [_t(o, "opportunity") for o in mk.get("opportunities", [])[:3]]},
        "competitors": [{"name": c.get("name"), "type": c.get("competitor_type"), "site": c.get("website_url"), "pricing": c.get("pricing_text"),
                         "strengths": c.get("site_strengths"), "weaknesses_ai": c.get("ai_weaknesses"), "how_we_differ": c.get("differentiation_opportunity")}
                        for c in (cp.get("competitors") or [])[:6]],
        "market_gaps": [f"{g.get('capability')} ({g.get('status')})" for g in (cp.get("gap_analysis") or [])[:5]],
        "swot": {k: [f"{_t(i, 'point')} [{i.get('basis') if isinstance(i, dict) else ''}]" for i in v[:4]] for k, v in (sw.get("swot") or {}).items()},
        "risks": [{"category": r.get("category"), "risk": r.get("risk"), "severity": r.get("severity"), "mitigation": r.get("mitigation_steps"),
                   "fix": r.get("realistic_solution"), "warning_sign": r.get("early_warning_sign")} for r in (sw.get("risks") or [])[:6]],
        "mvp": {"must_have": [_t(f, "feature") for f in mvp.get("must_have", [])], "build_first": [_t(b, "what") for b in mvp.get("build_order", [])],
                "weeks": mvp.get("estimated_mvp_weeks"), "team": mvp.get("team_assumption"),
                "cost_cash": (ce.get("cash_total") or {}).get("text"), "cost_own_time": (ce.get("own_time_total") or {}).get("text"),
                "cost_assumptions": (ce.get("assumptions") or [])[:3], "stack": [f"{t.get('layer')}: {t.get('technology')}" for t in mvp.get("recommended_tech_stack", [])[:5]]},
        "gtm": {"positioning": gtm.get("positioning_statement"), "recommended_model": gtm.get("recommended_revenue_model"),
                "pricing": [f"{t.get('name')}: {t.get('price')}" for t in (gtm.get("pricing_strategy") or {}).get("tiers", [])],
                "first_customers": [f"{w.get('channel')}: {w.get('specific_action') or w.get('action')}" for w in fc.get("where_to_find", [])[:4]],
                "first_30_days": ((gtm.get("launch_roadmap_90_days") or [{}])[0].get("actions") or [])[:4]},
    }
    return digest


class StartupAdvisorAgent(BaseAgent):
    """Agent 7: executive advisory brief + conversational advisor. LLM only; no canned answers."""

    GUARD_PATHS = ["top_strategic_recommendations", "key_red_flags_to_monitor"]

    def __init__(self, **kw):
        super().__init__(name="advisor", description="Synthesises strategic advice and answers founder questions.", **kw)

    def _execute_llm(self, context):
        digest = json.dumps(_compact(context), ensure_ascii=False)[:7000]
        user = f"""TASK: ADVISORY BRIEF
Analysis digest (JSON): {digest}

Return JSON:
{{
 "advisory_summary": "3-4 sentences of candid advice for this founder, naming specific competitors, users or numbers",
 "top_strategic_recommendations": [{{"recommendation": "", "reason": "tied to a finding above"}}],
 "key_red_flags_to_monitor": [{{"flag": "", "how_to_measure": ""}}],
 "founder_elevator_pitch": "2 sentences",
 "first_100_customers_playbook": ["5 concrete steps specific to these customers"],
 "pricing_and_unit_economics_advice": "specific, referencing the competitor pricing found (or the lack of it)"
}}
Give 4 recommendations and 3 red flags."""
        return self.llm_json("You are a seasoned startup mentor giving direct, specific advice.", user, max_tokens=2500,
                             temperature=0.4, fast=True, required_keys=["advisory_summary", "top_strategic_recommendations"],
                             anchors=self.anchors_for(context))

    def answer_query(self, context, user_message, history=None):
        """Chat reply grounded in the stored analysis. Raises LLMError if the LLM is unavailable."""
        if not self.groq_service.is_available():
            raise LLMError("no_key")
        digest = json.dumps(_compact(context), ensure_ascii=False)[:9000]
        messages = [{"role": "system", "content":
                     "You are the founder's AI startup advisor. Ground answers in the analysis digest below. "
                     "Answer ONLY from this idea's analysis digest: name its actual competitors, scores, risks, costs and plan items. "
                     "Never give generic startup advice that ignores the digest. If the digest lacks a fact (a number, a competitor, a price), "
                     "say it is not in the analysis (or 'insufficient data') instead of guessing, and say what to do to find out. "
                     "Mark anything that is your own judgement as an assumption. Be practical and concise (max ~220 words, short bullets welcome)."
                     "\n\nANALYSIS DIGEST:\n" + digest}]
        for m in (history or [])[-8:]:
            role = "assistant" if m.get("role") == "assistant" else "user"
            messages.append({"role": role, "content": (m.get("message") or "")[:1500]})
        messages.append({"role": "user", "content": user_message[:2000]})
        return self.groq_service.chat_completion(messages, temperature=0.5, max_tokens=1500).strip()
