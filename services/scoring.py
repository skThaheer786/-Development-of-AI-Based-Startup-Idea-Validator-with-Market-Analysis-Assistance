"""
Deterministic scoring. The LLM supplies 1-5 ratings WITH reasons; the arithmetic, caps and thresholds
live here so every score can be explained and reproduced.
"""

WEIGHTS = {"market": 0.25, "competition": 0.20, "execution": 0.20, "business": 0.15, "risk_resistance": 0.20}

DIMENSION_LABELS = {
    "market": "Market Demand",
    "competition": "Competitive Position",
    "execution": "Execution Feasibility",
    "business": "Business Model",
    "risk_resistance": "Risk Resistance",
}

FACTOR_LABELS = {
    "demand_strength": "Customer demand strength",
    "growth_outlook": "Growth outlook",
    "market_accessibility": "Ease of reaching this market",
    "evidence_strength": "Strength of research evidence",
    "differentiation_potential": "Differentiation potential",
    "competitive_headroom": "Headroom against incumbents",
    "switching_barriers": "Ease of winning customers away",
    "technical_feasibility": "Technical feasibility",
    "data_and_integration_dependency": "Data / integration dependency",
    "time_to_first_version": "Time to a first usable version",
    "customer_reachability": "Customer reachability",
    "willingness_to_pay": "Willingness to pay",
    "unit_economics_plausibility": "Unit-economics plausibility",
}

FACTOR_KEYS = {
    "market": ["demand_strength", "growth_outlook", "market_accessibility", "evidence_strength"],
    "competition": ["differentiation_potential", "competitive_headroom", "switching_barriers"],
    "execution": ["technical_feasibility", "data_and_integration_dependency", "time_to_first_version"],
    "business": ["customer_reachability", "willingness_to_pay", "unit_economics_plausibility"],
}

SCORING_RULES = ("Viability = Market Demand 25% + Competitive Position 20% + Execution Feasibility 20% + "
                 "Business Model 15% + Risk Resistance 20%. Each of the first four is the average of 1-5 ratings "
                 "(each with a written reason) converted to 0-100; Risk Resistance = 100 minus the composite risk score. "
                 "Proceed >= 75, Improve 55-74, High Risk < 55. Market Demand is capped at 70 when no sourced market "
                 "data was found.")


RECOMMENDATION_LABELS = {"PROCEED": "Proceed", "IMPROVE": "Improve", "RECONSIDER": "High Risk", "PENDING": "Pending"}


def recommendation_for(score):
    if score is None:
        return "PENDING"
    return "PROCEED" if score >= 75 else "IMPROVE" if score >= 55 else "RECONSIDER"


def _clean_ratings(ratings, keys):
    out = []
    for k in keys:
        r = (ratings or {}).get(k)
        if not isinstance(r, dict):
            continue
        try:
            val = int(round(float(r.get("rating"))))
        except (TypeError, ValueError):
            continue
        if not 1 <= val <= 5:
            continue
        reason = (r.get("reason") or "").strip()
        if len(reason) < 20:
            continue
        out.append({"key": k, "label": FACTOR_LABELS.get(k, k), "rating": val, "reason": reason,
                    "source": r.get("source", "ai_analysis")})
    return out


def evidence_rating(n_figures, n_publishers, n_sources):
    """Deterministic 'strength of evidence' factor for the market dimension."""
    if n_figures >= 3 and n_publishers >= 3:
        rating = 5
    elif n_figures >= 2 and n_publishers >= 2:
        rating = 4
    elif n_figures >= 1 or n_sources >= 4:
        rating = 3
    elif n_sources >= 2:
        rating = 2
    else:
        rating = 1
    reason = (f"Retrieved {n_sources} web source(s); {n_figures} sourced market figure(s) from "
              f"{n_publishers} publisher(s). This factor is computed from the research, not estimated by the AI.")
    return {"rating": rating, "reason": reason, "source": "computed"}


def score_risks(risks):
    """Adds score/severity to each risk and returns (risks, overall_score, rating)."""
    scored = []
    for r in risks or []:
        try:
            impact = max(1, min(10, int(round(float(r.get("impact_score"))))))
            like = max(1, min(10, int(round(float(r.get("likelihood_score"))))))
        except (TypeError, ValueError):
            continue
        s = dict(r)
        s["impact_score"], s["likelihood_score"] = impact, like
        s["risk_points"] = impact * like
        s["severity"] = "High" if s["risk_points"] >= 56 else "Medium" if s["risk_points"] >= 30 else "Low"
        scored.append(s)
    scored.sort(key=lambda x: x["risk_points"], reverse=True)
    if not scored:
        return [], None, "Not assessed"
    pts = [s["risk_points"] for s in scored]
    top3 = pts[:3]
    overall = round(0.6 * (sum(top3) / len(top3)) + 0.4 * (sum(pts) / len(pts)))
    rating = "High Risk" if overall >= 50 else "Moderate Risk" if overall >= 30 else "Low Risk"
    return scored, overall, rating


def _explain(label, score, factors, cap_note=""):
    if not factors:
        return f"{label}: not enough data to score."
    best = max(factors, key=lambda f: f["rating"])
    worst = min(factors, key=lambda f: f["rating"])
    text = f"{label} scored {score}/100. Strongest factor: {best['label'].lower()} ({best['rating']}/5) — {best['reason']}"
    if worst is not best:
        text += f" Weakest: {worst['label'].lower()} ({worst['rating']}/5) — {worst['reason']}"
    if cap_note:
        text += f" {cap_note}"
    return text


DISCLAIMER = ("This score is an AI-assisted assessment built from retrieved web sources and AI estimates. It is a structured aid "
              "for decision-making, not a prediction or a guarantee of business success. Validate the key assumptions with "
              "real customers before investing money or time.")


def reducing_factors(dims, total_weight, limit=5):
    """
    Factors rated 3/5 or lower, ranked by how many overall points raising them to 4/5 would add.
    Pure arithmetic on the stored ratings (nothing is estimated by the AI).
    """
    out = []
    for key, d in dims.items():
        facs = d.get("factors") or []
        if d.get("score") is None or not facs or not total_weight:
            continue
        for f in facs:
            if f["rating"] <= 3:
                gain = d["weight"] * (4 - f["rating"]) * 20 / len(facs) / total_weight
                out.append({"dimension": key, "dimension_label": d["label"], "factor_label": f["label"],
                            "rating": f["rating"], "reason": f["reason"], "points_if_raised_to_4": round(gain, 1)})
    out.sort(key=lambda x: (x["points_if_raised_to_4"], -x["rating"]), reverse=True)
    return out[:limit]


def verdict_explanation(score, dims, reducers, confidence, overall_risk):
    """Plain-language reason for Proceed / Improve / High Risk, built only from the computed numbers."""
    if score is None:
        return "No verdict: too few scoring categories could be computed."
    scored = sorted(((d["label"], d["score"]) for d in dims.values() if d["score"] is not None), key=lambda x: x[1], reverse=True)
    best, worst = scored[:2], scored[-2:][::-1]
    fmt = lambda pairs: " and ".join(f"{n} ({s}/100)" for n, s in pairs)
    if score >= 75:
        text = (f"Proceed: the weighted score of {score}/100 is at or above the 75-point threshold. The strongest categories are "
                f"{fmt(best)}. The weakest are {fmt(worst)}; keep an eye on them while you build.")
    elif score >= 55:
        text = (f"Improve: the weighted score of {score}/100 falls in the 55-74 band, so the idea has promise but is not yet ready to "
                f"commit to. It is held back mainly by {fmt(worst)}; it needs {75 - score} more point(s) to reach Proceed.")
    else:
        text = (f"High Risk: the weighted score of {score}/100 is below the 55-point threshold. The biggest drags are {fmt(worst)}. "
                f"Resolve these before spending significant money or time, or reconsider the idea.")
    if reducers:
        r = reducers[0]
        text += (f" The single most valuable fix is “{r['factor_label']}” ({r['dimension_label']}, rated {r['rating']}/5): "
                 f"raising it to 4/5 would add about {r['points_if_raised_to_4']} points.")
    if overall_risk is not None and overall_risk >= 50:
        text += f" The composite risk score is high ({overall_risk}/100), which lowers the Risk Resistance score."
    if confidence["level"] == "Low":
        text += " Research confidence is low, so treat this verdict as provisional."
    return text


def compute_viability(market_ratings=None, competition_ratings=None, execution_ratings=None, business_ratings=None,
                      overall_risk=None, evidence=None, competitors_verified=0, risk_count=0):
    """
    Returns a full, explainable score breakdown.
    evidence = {"figures": n, "publishers": n, "sources": n}
    """
    evidence = evidence or {"figures": 0, "publishers": 0, "sources": 0}
    inputs = {"market": market_ratings, "competition": competition_ratings,
              "execution": execution_ratings, "business": business_ratings}

    dims = {}
    for dim, ratings in inputs.items():
        ratings = dict(ratings or {})
        if dim == "market":
            ratings["evidence_strength"] = evidence_rating(evidence["figures"], evidence["publishers"],
                                                           evidence["sources"])
        factors = _clean_ratings(ratings, FACTOR_KEYS[dim])
        needed = max(2, len(FACTOR_KEYS[dim]) // 2 + 1)
        if len(factors) < needed:
            dims[dim] = {"score": None, "factors": factors, "weight": WEIGHTS[dim],
                         "label": DIMENSION_LABELS[dim],
                         "explanation": f"{DIMENSION_LABELS[dim]} could not be scored: the analysis returned too few valid rated factors."}
            continue
        score = round(sum(f["rating"] for f in factors) / len(factors) * 20)
        cap_note = ""
        if dim == "market" and evidence["figures"] == 0 and evidence["sources"] < 2 and score > 70:
            score = 70
            cap_note = "Capped at 70 because no sourced market data was found to support a higher score."
        dims[dim] = {"score": score, "factors": factors, "weight": WEIGHTS[dim], "label": DIMENSION_LABELS[dim],
                     "explanation": _explain(DIMENSION_LABELS[dim], score, factors, cap_note), "cap_note": cap_note}

    if overall_risk is None:
        dims["risk_resistance"] = {"score": None, "factors": [], "weight": WEIGHTS["risk_resistance"],
                                   "label": DIMENSION_LABELS["risk_resistance"],
                                   "explanation": "Risk Resistance could not be scored: no risks were assessed."}
    else:
        rr = max(0, min(100, 100 - overall_risk))
        dims["risk_resistance"] = {
            "score": rr, "factors": [], "weight": WEIGHTS["risk_resistance"],
            "label": DIMENSION_LABELS["risk_resistance"],
            "explanation": (f"Risk Resistance scored {rr}/100 = 100 minus the composite risk score of {overall_risk}, "
                            f"calculated from {risk_count} assessed risks (impact × likelihood, weighted toward the top three).")}

    available = {k: v for k, v in dims.items() if v["score"] is not None}
    viability = None
    if len(available) >= 3:
        total_w = sum(v["weight"] for v in available.values())
        viability = round(sum(v["score"] * v["weight"] for v in available.values()) / total_w)

    # Confidence
    reasons, level_pts = [], 0
    if evidence["figures"] >= 2:
        level_pts += 2
    elif evidence["figures"] == 1:
        level_pts += 1
    else:
        reasons.append("No sourced market figures were found.")
    if competitors_verified >= 3:
        level_pts += 2
    elif competitors_verified >= 1:
        level_pts += 1
    else:
        reasons.append("No competitor websites could be verified.")
    if evidence["sources"] >= 6:
        level_pts += 1
    elif evidence["sources"] == 0:
        reasons.append("Web search returned no sources.")
    if len(available) < 5:
        reasons.append(f"{5 - len(available)} scoring dimension(s) could not be computed.")
    level = "High" if level_pts >= 4 and len(available) == 5 else "Medium" if level_pts >= 2 else "Low"

    reducers = reducing_factors(dims, sum(v["weight"] for v in available.values())) if viability is not None else []
    return {
        "reducing_factors": reducers,
        "verdict_explanation": verdict_explanation(viability, dims, reducers, {"level": level}, overall_risk),
        "points_to_proceed": max(0, 75 - viability) if viability is not None else None,
        "disclaimer": DISCLAIMER,
        "viability_score": viability,
        "recommendation": recommendation_for(viability),
        "dimensions": dims,
        "confidence": {"level": level, "reasons": reasons},
        "rules": SCORING_RULES,
    }
