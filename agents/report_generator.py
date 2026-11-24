import re
import json
import time
import logging

from .base_agent import BaseAgent
from config import Config
from services import scoring
from services.scoring import compute_viability, score_risks

logger = logging.getLogger(__name__)


_MONEY_RX = re.compile(r"(?P<cur>[$₹€£]|USD|INR|EUR|GBP)\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s?(?P<unit>trillion|billion|million|thousand|crore|lakh|bn|mn|[BMK]\b)?", re.I)
_PCT_RX = re.compile(r"(?P<num>\d+(?:\.\d+)?)\s?%")
_MULT = {"trillion": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mn": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3,
         "crore": 1e7, "lakh": 1e5}


def _numbers_in(text):
    vals = []
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", text or ""):
        try:
            vals.append(float(m.group(0).replace(",", "")))
        except ValueError:
            pass
    return vals


def _supported(value, pool):
    return any(abs(v - value) <= max(abs(value) * 0.011, 0.0001) for v in pool)


def strip_unsupported_figures(text, facts_text):
    """
    Drops sentences that quote money amounts or percentages which appear nowhere in the structured research results.
    Returns (clean_text, number_of_sentences_removed).
    """
    pool = _numbers_in(facts_text)
    kept, removed = [], 0
    for sent in re.split(r"(?<=[.!?])\s+", text or ""):
        bad = False
        for m in _MONEY_RX.finditer(sent):
            v = float(m.group("num").replace(",", ""))
            unit = (m.group("unit") or "").lower()
            # with a unit ("9.9 billion") only the scaled value may match; a bare "$29" must match as written
            ok = _supported(v * _MULT[unit], pool) if unit in _MULT else _supported(v, pool)
            if not ok:
                bad = True
        for m in _PCT_RX.finditer(sent):
            if not _supported(float(m.group("num")), pool):
                bad = True
        if bad:
            removed += 1
        else:
            kept.append(sent)
    return " ".join(kept), removed


class ReportGeneratorAgent(BaseAgent):
    """
    Agent 8: computes explainable scores (deterministic) and writes the narrative summary.
    The numbers never come from the LLM; the narrative is checked against them.
    """

    GUARD_PATHS = []

    def __init__(self, **kw):
        super().__init__(name="report", description="Computes the explainable viability score and compiles the final report.", **kw)

    # ------------------------------------------------------------------
    @staticmethod
    def _evidence(market, comp):
        figs = market.get("verified_figures", []) or []
        pubs = {f.get("url", "").split("/")[2] for f in figs if f.get("url")}
        srcs = {s["id"] for s in (market.get("research_sources") or [])}
        return {"figures": len(figs), "publishers": len(pubs), "sources": len(srcs)}

    def compute_scores(self, analysis):
        """Pure scoring step (also used by tests)."""
        market = analysis.get("market", {}).get("data", {}) or {}
        comp = analysis.get("competitors", {}).get("data", {}) or {}
        swot = analysis.get("swot_risk", {}).get("data", {}) or {}
        mvp = analysis.get("mvp", {}).get("data", {}) or {}
        gtm = analysis.get("gtm", {}).get("data", {}) or {}
        risks = swot.get("risks") or []
        overall = swot.get("overall_risk_score")
        return compute_viability(
            market_ratings=market.get("ratings") if "_error" not in market else None,
            competition_ratings=comp.get("ratings"),
            execution_ratings=mvp.get("ratings") if "_error" not in mvp else None,
            business_ratings=gtm.get("ratings") if "_error" not in gtm else None,
            overall_risk=overall, evidence=self._evidence(market, comp),
            competitors_verified=len(comp.get("competitors") or []), risk_count=len(risks))

    # ------------------------------------------------------------------
    def _fallback_narrative(self, idea, breakdown, analysis):
        """Data-driven summary built from this idea's own results (used only if the narrative call fails)."""
        dims = [(d["label"], d["score"]) for d in breakdown["dimensions"].values() if d["score"] is not None]
        if not dims:
            return {}
        best, worst = max(dims, key=lambda x: x[1]), min(dims, key=lambda x: x[1])
        comp = analysis.get("competitors", {}).get("data", {}) or {}
        names = ", ".join(c["name"] for c in (comp.get("competitors") or [])[:3]) or "no verified competitors"
        return {
            "executive_summary": (f"{idea.get('title')} scored {breakdown['viability_score']}/100 ({breakdown['recommendation']}). "
                                  f"Its strongest area is {best[0]} ({best[1]}/100) and its weakest is {worst[0]} ({worst[1]}/100). "
                                  f"Verified competitors considered: {names}. See the score breakdown for the reason behind each number."),
            "narrative_source": "computed",
        }

    def _execute_llm(self, context):
        idea, analysis = context["idea"], context["analysis_dict"]
        breakdown = self.compute_scores(analysis)
        dims = breakdown["dimensions"]
        score = breakdown["viability_score"]

        market = analysis.get("market", {}).get("data", {}) or {}
        comp = analysis.get("competitors", {}).get("data", {}) or {}
        swot = analysis.get("swot_risk", {}).get("data", {}) or {}
        result = {
            "viability_score": score if score is not None else 0,
            "score_available": score is not None,
            "recommendation": breakdown["recommendation"],
            "market_score": dims["market"]["score"], "competition_score": dims["competition"]["score"],
            "execution_score": dims["execution"]["score"], "business_score": dims["business"]["score"],
            "risk_score": swot.get("overall_risk_score"), "risk_resistance_score": dims["risk_resistance"]["score"],
            "score_breakdown": breakdown, "confidence": breakdown["confidence"],
            "scoring_rules": breakdown["rules"], "agent_status": {
                k: (v.get("data", {}).get("_meta", {}) or {}).get("status", "unknown") for k, v in analysis.items()},
        }
        result["verdict_explanation"] = breakdown["verdict_explanation"]
        result["main_score_reducers"] = breakdown["reducing_factors"]
        result["points_to_proceed"] = breakdown["points_to_proceed"]
        result["disclaimer"] = breakdown["disclaimer"]
        sw_items = swot.get("swot") or {}
        pick = lambda q, n: sorted(sw_items.get(q, []), key=lambda i: 0 if i.get("basis") == "sourced" else 1)[:n]
        result["key_strengths"] = [{"point": i.get("point"), "why": i.get("why"), "basis": i.get("basis")} for i in pick("strengths", 3)]
        result["key_weaknesses"] = [{"point": i.get("point"), "why": i.get("why"), "basis": i.get("basis")} for i in pick("weaknesses", 3)]
        result["key_risks"] = [{"risk": r.get("risk"), "severity": r.get("severity"), "fix": r.get("realistic_solution")}
                               for r in (swot.get("risks") or [])[:3]]
        result["scoring_rationale"] = {k: v["explanation"] for k, v in dims.items()}

        if score is None:
            self.warnings.append("Not enough analysis completed to compute an overall score.")
            result["executive_summary"] = ("An overall viability score could not be computed because too many analysis "
                                           "steps failed. Re-run the analysis; see the warnings below.")
            return result

        digest = {
            "idea": idea.get("title"), "score": score, "recommendation": breakdown["recommendation"],
            "dimension_scores": {d["label"]: d["score"] for d in dims.values()},
            "dimension_explanations": {d["label"]: d["explanation"][:420] for d in dims.values()},
            "confidence": breakdown["confidence"],
            "market_summary": market.get("market_summary"), "cagr": market.get("cagr"),
            "sizing": market.get("sizing", {}).get("formula"),
            "competitors": [c["name"] for c in comp.get("competitors", [])],
            "whitespace": [o.get("opportunity") for o in comp.get("opportunities", [])[:3]],
            "top_risks": [r["risk"] for r in (swot.get("risks") or [])[:3]],
        }
        user = f"""TASK: FINAL REPORT NARRATIVE
The scores below are final and computed. Do NOT change or restate different numbers.
Facts (JSON): {json.dumps(digest, ensure_ascii=False)[:6500]}

Return JSON:
{{
 "executive_summary": "3 short paragraphs: verdict and why; what the evidence says about demand and competitors; what must be proven next. Name specific competitors, users and risks.",
 "biggest_strength": "", "biggest_weakness": "", "best_market_opportunity": "",
 "recommended_next_action": "the single most valuable next step this week",
 "go_no_go_verdict": "one sentence consistent with the recommendation {breakdown['recommendation']}",
 "next_immediate_steps": ["3 concrete steps"]
}}"""
        try:
            narrative = self.llm_json("You are the lead analyst writing the final verdict. You explain computed scores, you do not alter them.",
                                      user, max_tokens=2200, temperature=0.3, fast=True, required_keys=["executive_summary"])
            facts = json.dumps({k: v.get("data") for k, v in analysis.items()}, default=str) + json.dumps(breakdown, default=str)
            dropped = 0
            for key in ("executive_summary", "biggest_strength", "biggest_weakness", "best_market_opportunity", "recommended_next_action"):
                if isinstance(narrative.get(key), str):
                    narrative[key], n = strip_unsupported_figures(narrative[key].replace("\n", " \n "), facts)
                    narrative[key] = narrative[key].replace(" \n ", "\n").strip()
                    dropped += n
            if dropped:
                self.warnings.append(f"{dropped} sentence(s) in the written summary quoted figures that are not in the research data and were removed.")
            # the stated score must be the computed one
            narrative["executive_summary"] = re.sub(r"(score of )\d{1,3}(\s*/\s*100)?", lambda m: f"{m.group(1)}{score}{m.group(2) or ''}",
                                                    narrative.get("executive_summary") or "")
            label = {"PROCEED": "Proceed", "IMPROVE": "Improve", "RECONSIDER": "High Risk"}[breakdown["recommendation"]]
            verdict = narrative.get("go_no_go_verdict") or ""
            if label.lower() not in verdict.lower() and not (label == "High Risk" and "reconsider" in verdict.lower()):
                narrative["go_no_go_verdict"] = f"{label}: {breakdown['verdict_explanation'].split(': ', 1)[-1].split('. ')[0]}."
            result.update({k: narrative.get(k) for k in ("executive_summary", "biggest_strength", "biggest_weakness",
                                                          "best_market_opportunity", "recommended_next_action",
                                                          "go_no_go_verdict", "next_immediate_steps")})
        except Exception as exc:
            logger.warning("Narrative generation failed: %s", exc)
            self.warnings.append("The written summary could not be generated by the AI; a computed summary is shown instead.")
            result.update(self._fallback_narrative(idea, breakdown, analysis))
        return result

    # ------------------------------------------------------------------
    def generate_pdf_document(self, idea, analysis_dict, competitors, report_data):
        """Writes the PDF into the exports folder and returns the filename."""
        import os
        from services.pdf_service import PDFReportService
        os.makedirs(Config.EXPORTS_DIR, exist_ok=True)
        filename = f"report_{idea['id']}_{int(time.time())}.pdf"
        PDFReportService.generate_report(idea, analysis_dict, competitors, report_meta=report_data,
                                         output_path=str(Config.EXPORTS_DIR / filename))
        return filename
