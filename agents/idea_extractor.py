from .base_agent import BaseAgent, AgentFailure


def _clean_list(values, limit, maxlen=140):
    out = []
    for v in values or []:
        if isinstance(v, str) and v.strip():
            out.append(v.strip()[:maxlen])
    return out[:limit]


class IdeaExtractionAgent(BaseAgent):
    """Agent 1: structures the submitted idea and prepares idea-specific research queries."""

    def __init__(self, **kw):
        super().__init__(
            name="extractor",
            description="Extracts structured business concept, problem, solution, audience, industry, revenue model and research queries.",
            **kw)

    def _execute_llm(self, context):
        provided = {
            "industry": context.get("industry") or "",
            "target_audience": context.get("target_audience") or "",
            "problem_statement": context.get("problem_statement") or "",
            "proposed_solution": context.get("proposed_solution") or "",
            "revenue_model": context.get("revenue_model") or "",
        }
        user = f"""TASK: IDEA EXTRACTION
Analyse this startup submission. Keep what the founder wrote; only fill gaps. Do not add features the founder did not mention.

Title: {context.get('title', '')}
Description: {context.get('raw_description', '')}
Fields the founder filled in (may be empty): {provided}

Return a JSON object with exactly these keys:
{{
 "business_concept": "2 sentences, concrete",
 "problem_statement": "the specific pain, who has it, and how it shows up",
 "proposed_solution": "what the product actually does",
 "target_audience": "specific primary users and buyers",
 "industry": "short industry label",
 "market_category": "5-9 word noun phrase naming the product type and its customer, written in plain words a search engine would match",
 "customer_type": "B2B | B2C | B2B2C | B2G | Marketplace",
 "geography": "region stated or clearly implied, otherwise 'Not specified'",
 "revenue_model": "monetisation as described or most natural for this idea",
 "unique_value_proposition": "why a customer would pick this",
 "key_terms": ["6-8 distinctive nouns/phrases from this idea"],
 "search_queries": {{
   "market": ["3 web search queries for market size, growth and trends of this exact market"],
   "customer_demand": ["2 queries about demand, adoption or pain statistics for the target users"],
   "competitors": ["3 queries to find companies/products offering something similar"],
   "risks": ["2 queries about regulation, compliance or adoption barriers for this kind of product"],
   "channels": ["2 queries about where the target customers gather or buy (associations, communities, events)"]
 }},
 "assumptions_made": ["gaps in the submission you had to assume"],
 "idea_quality_notes": ["vague or missing details the founder should clarify"],
 "suggested_tags": ["3-4 short tags"]
}}"""
        data = self.llm_json("You are a startup analyst who turns raw ideas into precise, searchable business definitions.",
                             user, max_tokens=2200, temperature=0.2, fast=True,
                             required_keys=["business_concept", "problem_statement", "proposed_solution",
                                            "target_audience", "market_category", "search_queries"])
        # Founder-provided fields win over AI guesses
        for key, val in provided.items():
            if val.strip():
                data[key] = val.strip()
        sq = data.get("search_queries") or {}
        if not isinstance(sq, dict):
            raise AgentFailure("search queries missing")
        data["search_queries"] = {k: _clean_list(sq.get(k), 3, 160)
                                  for k in ("market", "customer_demand", "competitors", "risks", "channels")}
        if not data["search_queries"]["market"] or not data["search_queries"]["competitors"]:
            cat = data["market_category"]
            data["search_queries"]["market"] = data["search_queries"]["market"] or [f"{cat} market size", f"{cat} market growth CAGR"]
            data["search_queries"]["competitors"] = data["search_queries"]["competitors"] or [f"{cat} companies", f"{cat} alternatives"]
        data["key_terms"] = _clean_list(data.get("key_terms"), 8, 60)
        data["assumptions_made"] = _clean_list(data.get("assumptions_made"), 6, 200)
        data["idea_quality_notes"] = _clean_list(data.get("idea_quality_notes"), 6, 200)
        data["suggested_tags"] = _clean_list(data.get("suggested_tags"), 4, 30)
        data["customer_type"] = data.get("customer_type") or "Not specified"
        data["geography"] = data.get("geography") or "Not specified"
        data["industry"] = data.get("industry") or context.get("industry") or "Technology"
        return data
