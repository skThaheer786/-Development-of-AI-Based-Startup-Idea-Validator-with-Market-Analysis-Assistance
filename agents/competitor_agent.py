import re
from config import Config
from .base_agent import BaseAgent
from services.evidence import fetch_page, extract_prices, registered_domain, is_non_company_site


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


class CompetitorAnalysisAgent(BaseAgent):
    """
    Agent 3: finds real competitors. Names come from web evidence (or the model's suggestions), but a competitor
    is only listed when its official website was actually fetched and mentions the company. Products, features
    and pricing are read from those pages -- never invented.
    """

    GUARD_PATHS = ["opportunities", "status_quo_alternatives"]
    MAX_CANDIDATES = 8

    def __init__(self, **kw):
        super().__init__(name="competitor",
                         description="Identifies verified competitors, compares features/pricing and finds differentiation gaps.", **kw)

    def _limit(self):
        return 4 if Config.QUICK_MODE else self.MAX_CANDIDATES

    # ------------------------------------------------------------------
    def _search(self, ex):
        sq = ex.get("search_queries", {})
        queries = list(sq.get("competitors", []))[:3]
        cat = ex.get("market_category", "")
        if cat:
            queries.append(f"best {cat} alternatives pricing")
        return self.add_sources(self.search_service.search_many(queries, max_results=7))

    def _resolve_site(self, name, hinted_url, sources):
        """Find the official website for a company name using only search results / provided URLs."""
        n = _norm(name)
        if len(n) < 3:
            return None
        if hinted_url and hinted_url.startswith("http") and not is_non_company_site(hinted_url):
            dom = _norm(registered_domain(hinted_url).split(".")[0])
            if n in dom or dom in n:
                return hinted_url
        # companies whose own site already appears in the retrieved results
        for s in sources:
            if is_non_company_site(s["url"]):
                continue
            dom = _norm(s["domain"].split(".")[0])
            if len(dom) >= 4 and (n in dom or dom in n):
                return s["url"]
        # dedicated lookup
        for r in self.search_service.search(f"{name} official website", max_results=5):
            if is_non_company_site(r["url"]):
                continue
            dom = _norm(r["domain"].split(".")[0])
            if len(dom) >= 4 and (n in dom or dom in n):
                self.add_sources([r])
                return r["url"]
        return None

    def _verify(self, name, url):
        page = fetch_page(url)
        if not page["ok"]:
            return None
        haystack = _norm(page["title"] + page["description"] + page["text"][:1500])
        if _norm(name) not in haystack and _norm(registered_domain(page["final_url"]).split(".")[0]) not in _norm(name):
            return None
        pricing = {"status": "not_found", "prices": [], "source_url": ""}
        prices, price_url = [], ""
        if page["pricing_url"]:
            pp = fetch_page(page["pricing_url"])
            if pp["ok"]:
                prices, price_url = extract_prices(pp["text"]), pp["final_url"]
        if not prices:
            prices, price_url = extract_prices(page["text"]), page["final_url"]
        if prices:
            pricing = {"status": "found", "prices": prices, "source_url": price_url}
        elif page["pricing_url"]:
            pricing["source_url"] = page["pricing_url"]
        return {"page": page, "pricing": pricing}

    # ------------------------------------------------------------------
    def _execute_llm(self, context):
        ex = context.get("extractor_data", {})
        sources = self._search(ex)

        # Step A: candidate names
        user_a = f"""TASK: COMPETITOR IDENTIFICATION
{self.idea_brief(context)}

WEB EVIDENCE (search results; cite by id):
{self.book.for_prompt(sources, snippet_chars=280, limit=14)}

List up to {self._limit()} real companies/products that serve the same customers or solve the same problem.
Prefer companies named in the evidence. You may add well-known companies you are certain exist, but mark them "from_evidence": false.
Do NOT include review sites, news sites, directories or market-research publishers.
Types: Direct = same customer, same problem, similar solution. Indirect = same customer or problem solved a different way (or a bigger platform that partly covers it). Emerging = a newer, smaller or fast-growing entrant, or a player from an adjacent category moving in. Include a mix of types where real companies exist.
Return JSON: {{"candidates": [{{"name": "", "official_website": "only if it appears in the evidence, else null",
 "competitor_type": "Direct | Indirect | Emerging", "why_relevant": "", "from_evidence": true, "source_ids": []}}]}}"""
        cand = self.llm_json("You identify real competitors for early-stage startups. You never invent companies.",
                             user_a, max_tokens=2500, temperature=0.2, required_keys=["candidates"])
        candidates, seen = [], set()
        for c in cand.get("candidates", []):
            nm = (c.get("name") or "").strip() if isinstance(c, dict) else ""
            if nm and _norm(nm) not in seen:
                seen.add(_norm(nm))
                candidates.append(c)
        candidates = candidates[:self._limit()]

        # Step B: verify each candidate's real website
        from concurrent.futures import ThreadPoolExecutor

        def check(c):
            url = self._resolve_site(c["name"], c.get("official_website"), sources)
            return c, (self._verify(c["name"], url) if url else None)

        verified, unverified = [], []
        with ThreadPoolExecutor(max_workers=4) as pool:
            for c, res in pool.map(check, candidates):
                if not res:
                    unverified.append(c["name"])
                else:
                    verified.append({"cand": c, "url": res["page"]["final_url"], "res": res})
        if not verified:
            self.warnings.append("No competitor websites could be verified.")

        # Step C: profile only from fetched page text
        comp_blocks = []
        for v in verified:
            pg = v["res"]["page"]
            comp_blocks.append(
                f"### {v['cand']['name']} ({v['url']})\nTitle: {pg['title']}\nMeta: {pg['description']}\n"
                f"Headings: {' | '.join(pg['headings'])}\nPage text: {pg['text'][:900]}\n"
                f"Prices found on page: {', '.join(v['res']['pricing']['prices']) or 'none'}")
        if not verified:
            return self._empty(ex, sources, unverified)

        names = [v["cand"]["name"] for v in verified]
        user_c = f"""TASK: COMPETITOR PROFILING AND COMPARISON
{self.idea_brief(context)}

VERIFIED COMPETITOR WEBSITES (the ONLY facts you may use about them):
{chr(10).join(comp_blocks)}

Rules: describe a competitor ONLY with what its page text says; use null/[] when the text does not say. Do not state prices.
Return JSON:
{{
 "profiles": [{{"name": "exactly one of {names}", "products": ["products/services named on the page"], "key_features": ["features named on the page"],
   "target_customers": "from the page or null", "positioning": "one sentence from the page",
   "site_strengths": ["what the company clearly does well or emphasises, ONLY as stated on its page (max 4)"],
   "ai_weaknesses": ["likely limitations for THIS idea's customers, inferred from what the page does not cover (max 4, short)"],
   "overlap_with_idea": "where it overlaps with THIS idea", "gaps_vs_idea": "what THIS idea does that the page does not mention (AI analysis)",
   "differentiation_opportunity": "specific way this idea can be different from this competitor", "threat_level": "Low|Medium|High", "threat_reason": ""}}],
 "opportunities": [{{"opportunity": "idea-specific whitespace across competitors", "why": "", "competitors_lacking": ["names"]}}],
 "status_quo_alternatives": ["non-software alternatives customers use today (spreadsheets, manual process, agencies...) for this idea"],
 "comparison_features": [{{"capability": "capability that matters to these customers", "idea_offers": true, "competitors": {{"<name>": "yes|no|unclear"}}}}],
 "market_saturation": "Low|Medium|High", "saturation_reason": "",
 "positioning_recommendation": "how to position against these specific competitors",
 "ratings": {{
  "differentiation_potential": {{"rating": 1, "reason": "1-5, reference named competitors"}},
  "competitive_headroom": {{"rating": 1, "reason": "1-5: 5 = incumbents are weak/few"}},
  "switching_barriers": {{"rating": 1, "reason": "1-5: 5 = customers are easy to win"}}
 }}
}}
Give 4-6 capabilities in comparison_features. Mark "yes" only when the page text states it."""
        data = self.llm_json("You are a competitive intelligence analyst. You only report what the supplied pages say.",
                             user_c, max_tokens=4200, temperature=0.25,
                             required_keys=["profiles", "ratings"], anchors=self.anchors_for(context, names))

        profiles = {p.get("name"): p for p in data.get("profiles", []) if isinstance(p, dict)}
        competitors = []
        for v in verified:
            nm, p, pr = v["cand"]["name"], profiles.get(v["cand"]["name"], {}), v["res"]["pricing"]
            pg = v["res"]["page"]
            if pr["status"] == "found":
                pricing_text = "Listed on website: " + "; ".join(pr["prices"][:4])
            else:
                pricing_text = "Not publicly listed (no price found on the website)"
            entry = {
                "name": nm, "competitor_type": self._norm_type(v["cand"].get("competitor_type")),
                "site_strengths": [str(x)[:160] for x in (p.get("site_strengths") or []) if x][:4],
                "ai_weaknesses": [str(x)[:160] for x in (p.get("ai_weaknesses") or []) if x][:4],
                "website_url": v["url"], "website_verified": True,
                "website_title": pg["title"], "website_description": pg["description"],
                "products": p.get("products") or [], "key_features": p.get("key_features") or [],
                "target_customers": p.get("target_customers"), "positioning": p.get("positioning") or pg["description"],
                "pricing": pr, "pricing_text": pricing_text,
                "overlap_with_idea": p.get("overlap_with_idea", ""), "gaps_vs_idea": p.get("gaps_vs_idea", ""),
                "differentiation_opportunity": p.get("differentiation_opportunity", ""),
                "threat_level": p.get("threat_level") if p.get("threat_level") in ("Low", "Medium", "High") else "Medium",
                "threat_reason": p.get("threat_reason", ""), "why_relevant": v["cand"].get("why_relevant", ""),
            }
            entry["pricing"]["text"] = pricing_text
            competitors.append(entry)

        # comparison matrix (validated against verified names)
        matrix = []
        for row in data.get("comparison_features", []) or []:
            if not isinstance(row, dict) or not row.get("capability"):
                continue
            cells = row.get("competitors") if isinstance(row.get("competitors"), dict) else {}
            matrix.append({"capability": row["capability"], "idea_offers": bool(row.get("idea_offers")),
                           "competitors": {n: (cells.get(n) if cells.get(n) in ("yes", "no", "unclear") else "unclear")
                                           for n in names}})
        gaps = self._gap_analysis(matrix, names)
        type_counts = {t: sum(1 for c in competitors if c["competitor_type"] == t) for t in ("Direct", "Indirect", "Emerging")}
        anchors_pricing = [{"competitor": c["name"], "prices": c["pricing"]["prices"], "url": c["pricing"]["source_url"]}
                           for c in competitors if c["pricing"]["status"] == "found"]
        return {
            "competitors": competitors, "comparison_features": matrix,
            "opportunities": data.get("opportunities", []),
            "status_quo_alternatives": [s for s in data.get("status_quo_alternatives", []) if isinstance(s, str)],
            "market_saturation": data.get("market_saturation", "Unknown"),
            "saturation_reason": data.get("saturation_reason", ""),
            "positioning_recommendation": data.get("positioning_recommendation", ""),
            "price_anchors": anchors_pricing, "gap_analysis": gaps, "type_counts": type_counts,
            "unverified_mentions": [{"name": n} for n in unverified],
            "ratings": data.get("ratings", {}),
            "research_sources": self.book.public([s["id"] for s in sources]),
            "data_quality": {"candidates_considered": len(candidates), "verified": len(competitors),
                             "unverified": len(unverified), "sources_retrieved": len(sources),
                             "web_search": self.search_service.summary()},
        }

    @staticmethod
    def _norm_type(value):
        v = (value or "").lower()
        if "emerg" in v:
            return "Emerging"
        if "indirect" in v or "adjacent" in v:
            return "Indirect"
        return "Direct"

    @staticmethod
    def _gap_analysis(matrix, names):
        """
        Genuine market gaps computed from the capability matrix (website text only):
        open = no verified competitor states the capability; partial = some do; crowded = all do.
        'unclear' means the competitor's pages are silent, so an open gap is a lead to verify, not proof.
        """
        out = []
        for row in matrix:
            if not row.get("idea_offers"):
                continue
            cells = row["competitors"]
            yes = [n for n in names if cells.get(n) == "yes"]
            unclear = [n for n in names if cells.get(n) == "unclear"]
            status = "open" if not yes else "crowded" if len(yes) == len(names) else "partial"
            out.append({"capability": row["capability"], "status": status, "offered_by": yes, "unclear": unclear})
        order = {"open": 0, "partial": 1, "crowded": 2}
        return sorted(out, key=lambda g: order[g["status"]])

    def _empty(self, ex, sources, unverified):
        why = ("Web search returned no results, so competitors could not be researched." if not sources else
               "No candidate company website could be fetched and verified, so no competitor is listed rather than guessing.")
        return {"competitors": [], "comparison_features": [], "opportunities": [], "status_quo_alternatives": [],
                "gap_analysis": [], "type_counts": {},
                "price_anchors": [], "unverified_mentions": [{"name": n} for n in unverified], "ratings": {},
                "market_saturation": "Unknown", "saturation_reason": why, "positioning_recommendation": "",
                "unavailable_reason": why, "note": why, "research_sources": self.book.public([s["id"] for s in sources]),
                "data_quality": {"candidates_considered": len(unverified), "verified": 0, "unverified": len(unverified),
                                 "sources_retrieved": len(sources), "web_search": self.search_service.summary()}}


# Backwards-compatible alias (older code imported this name)
CompetitorDiscoveryAgent = CompetitorAnalysisAgent
