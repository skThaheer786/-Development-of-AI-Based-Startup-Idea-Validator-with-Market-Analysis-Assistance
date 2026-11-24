from .base_agent import BaseAgent


class GTMStrategistAgent(BaseAgent):
    """Agent 6: revenue model, pricing, first customers and a 30/60/90-day plan."""

    GUARD_PATHS = ["first_customers.where_to_find", "launch_roadmap_90_days", "revenue_models"]

    def __init__(self, **kw):
        super().__init__(name="gtm", description="Suggests pricing, revenue models, first-customer plan and a 30/60/90-day action plan.", **kw)

    def _execute_llm(self, context):
        ex = context.get("extractor_data", {})
        market, comp, mvp = (context.get("market_data") or {}), (context.get("competitor_data") or {}), (context.get("mvp_data") or {})
        found = self.search_service.search_many((ex.get("search_queries", {}).get("channels", []) or [])[:2], max_results=5)
        sources = self.add_sources(found)
        ids = {s["id"] for s in sources}
        anchors_price = comp.get("price_anchors") or []
        seg = [f"{s.get('segment_name')}: {s.get('pain_point')} (pays: {s.get('willingness_to_pay')})"
               for s in market.get("customer_segments", []) if isinstance(s, dict)]
        sizing = market.get("sizing", {})
        user = f"""TASK: GO-TO-MARKET AND PRICING
{self.idea_brief(context)}

Customer segments: {seg}
Competitor prices actually found on their websites: {anchors_price or 'none found'}
Assume a small student/early-stage team with a part-time budget.
Sizing assumption for revenue per customer: {sizing.get('formula', {}).get('tam', 'n/a')}

WHERE CUSTOMERS GATHER (web evidence; cite by id):
{self.book.for_prompt(sources, snippet_chars=260, limit=8)}

Use the currency of the target geography. Do not invent names of communities, associations or events; describe the TYPE of place
and a concrete search/outreach action, or cite a name only if it appears in the evidence above.
Return JSON:
{{
 "positioning_statement": "For <customer> who <need>, <product> is <category> that <benefit>, unlike <named alternative>.",
 "ideal_customer_profile": {{"who": "", "size_or_stage": "", "trigger_event": "what makes them look for a solution now", "decision_maker": ""}},
 "revenue_models": [{{"model": "", "fit_reason": "why for THIS customer", "example_price": "", "tradeoff": ""}}],
 "recommended_revenue_model": "",
 "marketing_strategy": {{"core_message": "the one-line message for these customers", "competitor_positioning": "how to position against the named verified competitors, using their real gaps",
   "channels": [{{"channel": "", "tactic": "a specific, low-budget action", "budget_note": "free / approx cost"}}], "content_ideas": ["3 concrete content or demo ideas"]}},
 "pricing_strategy": {{"assumptions": ["each assumption behind the prices: customer budget, usage, competitor anchors, cost to serve"],
   "rationale": "reference competitor prices above if any, otherwise say prices are untested",
   "tiers": [{{"name": "", "price": "", "who_its_for": "", "includes": [""], "basis": "competitor_anchor|ai_suggestion"}}]}},
 "year_one_targets": {{"paying_customers": 0, "avg_annual_revenue_per_customer": 0, "currency": "", "reasoning": ""}},
 "first_customers": {{
   "where_to_find": [{{"channel": "", "specific_action": "", "why_it_fits": "", "source_ids": []}}],
   "outreach_message": "a short real message the founder can send",
   "discovery_questions": ["5 interview questions"], "first_10_customers_plan": "how to land the first 10 paying or pilot users"
 }},
 "launch_roadmap_90_days": [
   {{"phase": "Days 1-30", "goal": "", "actions": ["4-5 specific actions"], "success_metric": "measurable"}},
   {{"phase": "Days 31-60", "goal": "", "actions": [""], "success_metric": ""}},
   {{"phase": "Days 61-90", "goal": "", "actions": [""], "success_metric": ""}}],
 "acquisition_channels": ["short list of channels"],
 "ratings": {{
  "customer_reachability": {{"rating": 1, "reason": "1-5"}},
  "willingness_to_pay": {{"rating": 1, "reason": "1-5 based on evidence of spend or lack of it"}},
  "unit_economics_plausibility": {{"rating": 1, "reason": "1-5"}}
 }}
}}
Pricing must follow from stated assumptions, not guesses: if competitor prices were found, say how yours compares and why; if none were found, say prices are untested. Give 3 revenue_models, 2-3 tiers, 4-5 where_to_find channels. Actions must have numbers (e.g. 'interview 15 hostel mess managers')."""
        data = self.llm_json("You are a go-to-market advisor for first-time founders with almost no budget.", user,
                             max_tokens=4500, temperature=0.35, required_keys=["revenue_models", "first_customers",
                             "launch_roadmap_90_days", "ratings"], anchors=self.anchors_for(context))
        fc = data.get("first_customers") or {}
        for w in fc.get("where_to_find", []) or []:
            if isinstance(w, dict):
                w["source_ids"] = [i for i in (w.get("source_ids") or []) if i in ids]
        icp = data.get("ideal_customer_profile")
        if isinstance(icp, dict):
            fc["ideal_customer_profile"] = (f"{icp.get('who', '')} ({icp.get('size_or_stage', '')}). Trigger: "
                                            f"{icp.get('trigger_event', '')}. Decision maker: {icp.get('decision_maker', '')}")
            data["icp_details"] = icp
        elif icp:
            fc["ideal_customer_profile"] = str(icp)
        for w in fc.get("where_to_find", []) or []:
            if isinstance(w, dict):
                w["action"] = w.get("specific_action", "")
        for tier in (data.get("pricing_strategy") or {}).get("tiers", []) or []:
            if isinstance(tier, dict):
                tier["target"] = tier.get("who_its_for", "")
        data["first_customers"] = fc
        t = data.get("year_one_targets") or {}
        try:
            n, arpc = float(t.get("paying_customers")), float(t.get("avg_annual_revenue_per_customer"))
            t["target_revenue"] = n * arpc
            t["formula"] = f"{n:,.0f} customers × {t.get('currency', '')}{arpc:,.0f} per year"
        except (TypeError, ValueError):
            data["year_one_targets"] = {}
        ms = data.get("marketing_strategy") if isinstance(data.get("marketing_strategy"), dict) else {}
        ms["channels"] = [c for c in (ms.get("channels") or []) if isinstance(c, dict) and c.get("channel")]
        ms["content_ideas"] = [str(x) for x in (ms.get("content_ideas") or []) if x]
        data["marketing_strategy"] = ms
        ps = data.get("pricing_strategy") if isinstance(data.get("pricing_strategy"), dict) else {}
        ps["assumptions"] = [str(a) for a in (ps.get("assumptions") or []) if a]
        data["pricing_strategy"] = ps
        data["price_anchors"] = anchors_price
        data["research_sources"] = self.book.public([s["id"] for s in sources])
        return data
