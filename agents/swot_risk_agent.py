from .base_agent import BaseAgent
from services import quality
from services.scoring import score_risks

SWOT_BASIS = {"idea", "market_evidence", "competitor_evidence", "ai_inference"}


class SWOTRiskAgent(BaseAgent):
    """Agent 4: idea-specific SWOT and a scored, actionable risk register."""

    GUARD_PATHS = ["swot.strengths", "swot.weaknesses", "swot.opportunities", "swot.threats", "risks"]

    def __init__(self, **kw):
        super().__init__(name="swot_risk",
                         description="Builds idea-specific SWOT and a scored risk register with realistic mitigations.", **kw)

    def _research(self, ex):
        found = self.search_service.search_many((ex.get("search_queries", {}).get("risks", []) or [])[:2], max_results=5)
        return self.add_sources(found)

    CATEGORY_MAP = {"technical": "Technical", "financial": "Financial", "market": "Market", "operational": "Operational",
                    "legal": "Legal/Regulatory", "regulatory": "Legal/Regulatory", "compliance": "Legal/Regulatory",
                    "competitive": "Competitive", "competition": "Competitive", "adoption": "Customer adoption",
                    "customer": "Customer adoption", "privacy": "Data privacy/security", "security": "Data privacy/security",
                    "data": "Data privacy/security"}
    REQUIRED = ("Technical", "Financial", "Market", "Operational", "Legal/Regulatory", "Competitive")

    def _normalise_risks(self, risks):
        """Canonical categories, at most 2 per category, and a note when a required category is missing."""
        out, per_cat = [], {}
        for r in risks:
            raw = (r.get("category") or "").lower()
            r["category"] = next((v for k, v in self.CATEGORY_MAP.items() if k in raw), "Operational")
            if per_cat.get(r["category"], 0) >= 2:
                continue
            per_cat[r["category"]] = per_cat.get(r["category"], 0) + 1
            r["impact_reason"] = (r.get("impact_reason") or "").strip()
            r["likelihood_reason"] = (r.get("likelihood_reason") or "").strip()
            r["evidence_backed"] = bool(r.get("source_ids"))
            out.append(r)
        missing = [c for c in self.REQUIRED if c not in per_cat]
        if missing:
            self.warnings.append("No risk was returned for: " + ", ".join(missing))
        return out

    @staticmethod
    def _competitor_digest(comp):
        rows = []
        for c in (comp.get("competitors") or [])[:6]:
            rows.append(f"- {c['name']} ({c.get('competitor_type')}): {c.get('positioning', '')[:140]} | pricing: {c.get('pricing_text')} | gap: {c.get('gaps_vs_idea', '')[:120]}")
        return "\n".join(rows) or "(no verified competitors)"

    def _execute_llm(self, context):
        ex = context.get("extractor_data", {})
        market, comp = context.get("market_data", {}) or {}, context.get("competitor_data", {}) or {}
        sources = self._research(ex)
        ids = {s["id"] for s in sources}
        market_ids = {s["id"] for s in market.get("research_sources", [])}
        all_ids = ids | market_ids | {s["id"] for s in comp.get("research_sources", [])}

        evidence_lines = self.book.for_prompt(sources, snippet_chars=220, limit=8)
        figs = "; ".join(f"{f['label']} {f['value_text']} [{f['source_id']}]" for f in market.get("verified_figures", [])[:4]) or "none"
        user = f"""TASK: SWOT AND RISK ANALYSIS
{self.idea_brief(context)}

MARKET FINDINGS: {market.get('market_summary', 'insufficient data')}
Verified figures: {figs}; CAGR: {market.get('cagr', 'Insufficient data')}
Opportunities found: {[o.get('opportunity') for o in market.get('opportunities', [])]}
VERIFIED COMPETITORS:
{self._competitor_digest(comp)}
Competitive whitespace: {[o.get('opportunity') for o in comp.get('opportunities', [])]}

RISK EVIDENCE (regulation / adoption barriers; cite by id):
{evidence_lines}

Return JSON:
{{
 "swot": {{
  "strengths": [{{"point": "", "why": "what in THIS idea or evidence makes it true", "basis": "idea|market_evidence|competitor_evidence|ai_inference", "source_ids": []}}],
  "weaknesses": [same shape], "opportunities": [same shape], "threats": [same shape]
 }},
 "cross_strategies": {{"SO": "use a named strength to capture a named opportunity", "WO": "", "ST": "", "WT": ""}},
 "risks": [{{
   "category": "Technical|Financial|Market|Operational|Legal/Regulatory|Competitive|Customer adoption|Data privacy/security",
   "risk": "specific risk for this idea", "why_this_idea": "the concrete trigger or evidence",
   "impact_score": 1, "impact_reason": "why this impact level for THIS idea",
   "likelihood_score": 1, "likelihood_reason": "the evidence or fact behind this likelihood",
   "mitigation_steps": ["2-4 concrete steps"], "realistic_solution": "the single most practical fix a small team can do",
   "early_warning_sign": "a measurable signal", "effort": "Low|Medium|High", "source_ids": []
 }}]
}}
Give 4 items per SWOT quadrant. Each "why" must explain why the point matters for THIS idea.
RISKS: give exactly one risk for each of Technical, Financial, Market, Operational, Legal/Regulatory and Competitive, plus up to two more
(Customer adoption, Data privacy/security) ONLY when they matter for this idea (personal data, payments, health, children, etc.).
SCALE (integers): impact 1-3 small setback fixable in days; 4-6 delays launch by weeks or loses some customers; 7-8 threatens revenue or legal
standing; 9-10 could end the business. Likelihood 1-3 unlikely within 12 months; 4-6 could well happen; 7-8 probable; 9-10 almost certain.
Base likelihood on evidence (sources, competitor facts) and state that evidence in likelihood_reason. Rate at most two risks 8 or higher.
Reference named competitors, features, user groups, regulations or figures. Mitigations must be affordable for a student/early-stage team."""
        data = self.llm_json("You are a startup risk analyst. Every statement must be traceable to this idea or the evidence.",
                             user, max_tokens=4500, temperature=0.3,
                             required_keys=["swot", "risks"], anchors=self.anchors_for(context,
                                                [c["name"] for c in comp.get("competitors", [])]))

        swot = {}
        for quad in ("strengths", "weaknesses", "opportunities", "threats"):
            items = []
            for it in (data["swot"].get(quad) or []):
                if isinstance(it, str):
                    it = {"point": it, "why": "", "basis": "ai_inference", "source_ids": []}
                if not isinstance(it, dict) or not it.get("point"):
                    continue
                valid = [i for i in (it.get("source_ids") or []) if i in all_ids]
                it["source_ids"] = valid
                it["basis"] = "sourced" if valid else (it.get("basis") if it.get("basis") in SWOT_BASIS else "ai_inference")
                items.append(it)
            swot[quad] = items
        if sum(len(v) for v in swot.values()) < 8:
            self.warnings.append("SWOT came back with fewer items than requested.")

        # Labels must be honest: downgrade a basis the text cannot support
        founder_tokens = quality.tokens(" ".join(str(context.get(k) or "") for k in ("title", "raw_description", "industry"))
                                        + " " + " ".join(str((context.get("extractor_data") or {}).get(k) or "")
                                                         for k in ("problem_statement", "proposed_solution", "target_audience")))
        comp_names = [c["name"].lower() for c in comp.get("competitors", [])]
        for items in swot.values():
            for it in items:
                text = f"{it.get('point', '')} {it.get('why', '')}"
                if it["basis"] == "idea" and not (quality.tokens(text) & founder_tokens):
                    it["basis"] = "ai_inference"
                elif it["basis"] == "competitor_evidence" and not any(n in text.lower() for n in comp_names):
                    it["basis"] = "ai_inference"
                elif it["basis"] == "market_evidence":
                    it["basis"] = "ai_inference"      # only real source ids earn the "sourced" label

        risks, overall, rating = score_risks(data.get("risks"))
        risks = self._normalise_risks(risks)
        for r in risks:
            r["source_ids"] = [i for i in (r.get("source_ids") or []) if i in all_ids]
            if isinstance(r.get("mitigation_steps"), str):
                r["mitigation_steps"] = [r["mitigation_steps"]]
        if not risks:
            self.warnings.append("No valid risks were returned.")
        cats = {}
        for r in risks:
            cats[r.get("category", "Other")] = max(cats.get(r.get("category", "Other"), 0), r["risk_points"])
        return {
            "swot": swot, "cross_strategies": data.get("cross_strategies", {}), "risks": risks,
            "overall_risk_score": overall, "risk_rating": rating, "risk_categories": cats,
            "research_sources": self.book.public([s["id"] for s in sources]),
        }
