import re
import json
import logging
from .base_agent import BaseAgent, AgentFailure
from services import quality
from services.evidence import extract_figures, format_money
from services.sizing import build_sizing, resolve_cagr, merge_sizing_inputs, INSUFFICIENT

logger = logging.getLogger(__name__)


def _tok(text):
    return {w for w in re.findall(r"[a-z]{4,}", (text or "").lower())}


class MarketAnalyzerAgent(BaseAgent):
    """Agent 2: real market research (web evidence), demand/trends/opportunities, TAM-SAM-SOM, CAGR."""

    GUARD_PATHS = ["demand_signals", "trends", "opportunities", "unmet_needs"]

    def __init__(self, **kw):
        super().__init__(name="market",
                         description="Researches the market, demand, trends and opportunities, and sizes TAM/SAM/SOM.", **kw)

    # ------------------------------------------------------------------
    def _research(self, ex):
        sq = ex.get("search_queries", {})
        cat = ex.get("market_category", "")
        queries = list(sq.get("market", []))[:3] + list(sq.get("customer_demand", []))[:2]
        if cat:
            queries.append(f"{cat} market size CAGR forecast")
        found = self.search_service.search_many(queries, max_results=6)
        wiki = self.search_service.wikipedia_summary(cat or ex.get("industry", ""))
        if wiki:
            found.append(wiki)
        return self.add_sources(found)

    # ------------------------------------------------------------------
    def _retry_sizing(self, context, ex, verified, raw_first, source_ids, first_result):
        """
        One focused second attempt when the first answer gave unusable sizing inputs. It reuses every usable
        input from the first answer and only fills the missing ones. Never replaces a calculated result.
        """
        figs = "\n".join(f"{f['fid']}: {f['value_text']} ({f.get('scope') or 'scope unknown'}, {f.get('year') or 'year unknown'}"
                         f"{', forecast' if f.get('forecast') else ''}) [{f['source_id']}] {f.get('note') or ''}"[:260] for f in verified[:8]) \
            or "(no published market-size figure was found)"
        user = f"""TASK: MARKET SIZING ASSUMPTIONS
{self.idea_brief(context)}

PUBLISHED MARKET-SIZE FIGURES FOUND (do not change them):
{figs}

The previous answer left these sizing inputs unusable: {'; '.join((first_result.get('debug') or {}).get('problems', {}).values()) or first_result.get('reason', 'unknown')}.
Give a best-reasoned NUMERIC estimate with a low/high range for every field below (plain numbers, never null, 0 or words). Unsourced estimates are
expected: label them "ai_assumption" and explain the reasoning in note. Shares are fractions between 0 and 1.
Return JSON: {{"sizing_assumptions": {{"customer_unit": "", "currency": "3-letter code", "geography": "",
 "unit_count": {{"value": 0, "low": 0, "high": 0, "basis": "ai_assumption", "source_ids": [], "note": ""}},
 "annual_revenue_per_unit": {{"value": 0, "low": 0, "high": 0, "basis": "ai_assumption", "source_ids": [], "note": "per customer per YEAR"}},
 "serviceable_share": {{"value": 0, "low": 0, "high": 0, "basis": "ai_assumption", "source_ids": [], "note": "share of customers reachable"}},
 "topdown_serviceable_share": {{"value": 0, "low": 0, "high": 0, "basis": "ai_assumption", "source_ids": [], "applies_to_figure": "F# or empty", "note": "share of that published market this product serves"}},
 "obtainable_share": {{"value": 0, "low": 0, "high": 0, "basis": "ai_assumption", "source_ids": [], "note": "share of SAM winnable in 3 years"}}}}}}"""
        try:
            second = self.llm_json("You are a market-sizing analyst. You always give reasoned numeric estimates and label them honestly.",
                                   user, max_tokens=2500, temperature=0.2, required_keys=["sizing_assumptions"])
        except Exception as exc:                       # a failed retry must never break the market analysis
            logger.warning("Sizing retry failed: %s", exc)
            return first_result
        merged = merge_sizing_inputs(raw_first, second.get("sizing_assumptions"), source_ids)
        retried = build_sizing(merged, source_ids, figures=verified)
        order = {"unavailable": 0, "partial": 1, "calculated": 2}
        return retried if order[retried["status"]] >= order[first_result["status"]] else first_result

    def _execute_llm(self, context):
        ex = context.get("extractor_data", {})
        sources = self._research(ex)
        source_ids = {s["id"] for s in sources}
        lookup = {s["id"]: s for s in sources}

        # --- figures parsed deterministically from retrieved text ---
        rel_tokens = {t for t in _tok(ex.get("market_category", "") + " " + " ".join(ex.get("key_terms", [])))
                      if t not in {"software", "platform", "market", "solution", "services", "based"}}
        figures = []
        for s in sources:
            figures.extend(extract_figures(s["snippet"], s["id"], s["title"], rel_tokens or None))
        figures = figures[:14]
        fig_lines = []
        for i, f in enumerate(figures):
            if f["kind"] == "market_size":
                fig_lines.append(f"F{i}: market size {format_money(f['value'], f['currency'])} (years {f['years']}) "
                                 f"[{f['source_id']}] \"{f['sentence'][:200]}\"")
            else:
                fig_lines.append(f"F{i}: growth rate {f['pct']}% CAGR (years {f['years']}) [{f['source_id']}] \"{f['sentence'][:200]}\"")

        user = f"""TASK: MARKET RESEARCH SYNTHESIS
{self.idea_brief(context)}

WEB EVIDENCE (retrieved just now; cite by id):
{self.book.for_prompt(sources, snippet_chars=320, limit=12)}

NUMERIC CLAIMS PARSED FROM THAT EVIDENCE (you may not change these numbers):
{chr(10).join(fig_lines) if fig_lines else '(none found)'}

Return a JSON object:
{{
 "market_summary": "3-4 sentences about THIS market (who buys, what drives spending, what is changing) using the evidence where possible",
 "demand_signals": [{{"signal": "short title", "detail": "specific evidence of customer demand or pain for these users", "source_ids": ["S1"]}}],
 "trends": [{{"trend": "title", "impact": "how it affects THIS idea specifically", "source_ids": []}}],
 "opportunities": [{{"opportunity": "a gap or unserved need this idea can target", "why": "why it exists, tied to evidence or the idea", "source_ids": []}}],
 "customer_segments": [{{"segment_name": "", "persona": "", "pain_point": "", "willingness_to_pay": "High/Medium/Low with a reason", "acquisition_channel": ""}}],
 "unmet_needs": ["specific unmet needs"],
 "figure_assessment": [{{"id": "F0", "relevant": true, "scope": "global|regional|segment|adjacent", "note": "why it does or does not describe THIS market"}}],
 "sizing_assumptions": {{
   "customer_unit": "what one paying customer is (an organisation type or a person type) in the target geography",
   "currency": "3-letter code of the target geography's currency",
   "geography": "the region these numbers cover",
   "unit_count": {{"value": "<number>", "low": "<number>", "high": "<number>", "basis": "sourced|ai_assumption", "source_ids": [], "note": "how you got it"}},
   "annual_revenue_per_unit": {{"value": "<number>", "low": "<number>", "high": "<number>", "basis": "sourced|ai_assumption", "source_ids": [], "note": "what ONE customer would pay per YEAR"}},
   "serviceable_share": {{"value": "<fraction 0-1>", "low": "<fraction>", "high": "<fraction>", "basis": "ai_assumption", "source_ids": [], "note": "fraction of those customers reachable with this product, geography and channel"}},
   "topdown_serviceable_share": {{"value": "<fraction 0-1>", "low": "<fraction>", "high": "<fraction>", "basis": "ai_assumption", "source_ids": [], "applies_to_figure": "F# of the published market size this share refers to, or empty", "note": "fraction of THAT published market that this product's segment and geography represent"}},
   "obtainable_share": {{"value": "<fraction 0-1>", "low": "<fraction>", "high": "<fraction>", "basis": "ai_assumption", "source_ids": [], "note": "share of the SAM a new entrant can win in 3 years"}}
 }},
 "ratings": {{
   "demand_strength": {{"rating": 1, "reason": "1-5, cite the evidence or lack of it"}},
   "growth_outlook": {{"rating": 1, "reason": "1-5; if no growth data exists say so and rate cautiously"}},
   "market_accessibility": {{"rating": 1, "reason": "1-5: how reachable are these customers for a new startup"}}
 }}
}}
Give 3-5 demand_signals, 3-4 trends, 3-4 opportunities, 2-3 customer_segments. Mark basis "sourced" ONLY when the number comes from the evidence above.
SIZING RULES: for sizing_assumptions ALWAYS give a best-reasoned numeric estimate with a low/high range for every field - never null, 0 or words.
Unsourced estimates are expected here: label them "ai_assumption" and explain the reasoning in note. Use plain numbers (no currency symbols, no text).
Shares are fractions between 0 and 1 (for example 0.15). annual_revenue_per_unit is what one customer pays per YEAR in the stated currency."""
        data = self.llm_json("You are a market research analyst. You separate what the evidence shows from your own estimates.",
                             user, max_tokens=4200, temperature=0.3,
                             required_keys=["market_summary", "demand_signals", "customer_segments", "sizing_assumptions", "ratings"],
                             anchors=self.anchors_for(context))

        # --- normalise cited items: basis is decided by us, not by the model ---
        def tag(items, text_key):
            out = []
            for it in items or []:
                if not isinstance(it, dict) or not it.get(text_key):
                    continue
                ids = [i for i in (it.get("source_ids") or []) if i in source_ids]
                it["source_ids"] = ids
                it["basis"] = "sourced" if ids else "ai_analysis"
                out.append(it)
            return out

        data["demand_signals"] = tag(data.get("demand_signals"), "signal")
        data["trends"] = tag(data.get("trends"), "trend")
        data["opportunities"] = tag(data.get("opportunities"), "opportunity")

        # --- verified figures: numbers from regex, relevance judged by the model ---
        verdicts = {a.get("id"): a for a in data.get("figure_assessment", []) if isinstance(a, dict)}
        verified, cagr_figs = [], []
        for i, f in enumerate(figures):
            v = verdicts.get(f"F{i}", {})
            if v.get("relevant") is not True:
                continue
            src = lookup.get(f["source_id"], {})
            if f["kind"] == "cagr":
                cagr_figs.append(f)
            else:
                note = re.sub(r"\bF\d+\b", "This figure", (v.get("note") or ""))[:220]
                verified.append({
                    "fid": f"F{i}", "label": "Market size" + (" (forecast)" if f.get("forecast") else ""),
                    "value_text": format_money(f["value"], f["currency"]), "value": f["value"],
                    "currency": f["currency"], "year": f.get("year") or (f["years"][0] if f["years"] else None),
                    "forecast": bool(f.get("forecast")),
                    "scope": v.get("scope", ""), "note": note,
                    "context": f["sentence"], "source_id": f["source_id"], "source_title": src.get("title", ""),
                    "url": src.get("url", ""), "reliability": src.get("reliability", "Unrated")})
        cagr = resolve_cagr(cagr_figs, lookup, had_any_sources=bool(sources))
        raw_sizing = next((data[k] for k in ("sizing_assumptions", "sizing", "market_sizing", "market_size_assumptions")
                           if isinstance(data.get(k), dict)), None)
        sizing = build_sizing(raw_sizing, source_ids, figures=verified)
        if sizing["status"] != "calculated":
            sizing = self._retry_sizing(context, ex, verified, raw_sizing, source_ids, sizing)
        if sizing["status"] != "calculated":
            logger.warning("Market sizing %s for '%s': %s | missing=%s | raw=%s", sizing["status"], context.get("title"),
                           sizing.get("reason") or "some levels missing", sizing.get("missing"), json.dumps(raw_sizing, default=str)[:500])

        publishers = {v_["url"].split("/")[2] for v_ in verified if v_.get("url")}
        data_quality = {
            "sources_retrieved": len(sources), "verified_figures": len(verified), "publishers": len(publishers),
            "web_search": self.search_service.summary(),
        }
        notes = []
        if not sources:
            notes.append("Web search returned no results, so every statement on this page is AI analysis without external evidence.")
            self.warnings.append("No web sources were retrieved for market research.")
        elif not verified:
            notes.append("Sources were found but none stated a market size matching this exact market; no market-size figure is shown as verified.")
        data_quality["notes"] = notes

        data.pop("figure_assessment", None)
        data.pop("sizing_assumptions", None)
        data.update({
            "industry_label": ex.get("industry", ""),
            "verified_figures": verified,
            "cagr_info": cagr,
            "cagr": cagr["value_text"],
            "sizing": sizing,
            "tam": sizing["tam"]["text"] if "tam" in sizing else INSUFFICIENT,
            "sam": sizing["sam"]["text"] if "sam" in sizing else INSUFFICIENT,
            "som": sizing["som"]["text"] if "som" in sizing else INSUFFICIENT,
            "market_drivers": [d["signal"] for d in data["demand_signals"]],
            "industry_trends": [{"trend": t["trend"], "impact": t["impact"]} for t in data["trends"]],
            "research_sources": self.book.public([s["id"] for s in sources]),
            "data_quality": data_quality,
        })
        if sizing["status"] == "unavailable":
            self.warnings.append("TAM/SAM/SOM could not be calculated (insufficient data).")
        elif sizing["status"] == "partial":
            self.warnings.append("Only part of TAM/SAM/SOM could be calculated: " + "; ".join(sizing["missing"].values()))
        return data
