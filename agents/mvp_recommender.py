import re
import math
from .base_agent import BaseAgent
from services.evidence import format_money


def _end_week(span):
    nums = [int(n) for n in re.findall(r"\d+", str(span))]
    return max(nums) if nums else 0


class MVPRecommenderAgent(BaseAgent):
    """Agent 5: prioritised MVP features, realistic roadmap, stack and validation experiments."""

    GUARD_PATHS = ["must_have", "roadmap", "validation_experiments"]

    def __init__(self, **kw):
        super().__init__(name="mvp", description="Recommends the most important MVP features and a realistic development roadmap.", **kw)

    def _execute_llm(self, context):
        market, comp, swot = (context.get("market_data") or {}), (context.get("competitor_data") or {}), (context.get("swot_data") or {})
        pains = [s.get("pain_point") for s in market.get("customer_segments", []) if isinstance(s, dict)]
        table_stakes = []
        for c in (comp.get("competitors") or [])[:5]:
            table_stakes.append(f"{c['name']}: {', '.join((c.get('key_features') or [])[:4])}")
        user = f"""TASK: MVP AND ROADMAP
{self.idea_brief(context)}

Customer pain points found: {pains}
Features competitors advertise: {table_stakes or 'none verified'}

Design the smallest product that tests the riskiest assumption with real users. Assume a team of 1-3 students/developers
working part-time with free-tier tools unless the idea clearly needs more (state your assumption).
Return JSON:
{{
 "team_assumption": "",
 "team_size": 2, "hours_per_week_each": 15,
 "build_order": [{{"step": 1, "what": "what to build FIRST", "why_first": "why it must come before the rest"}}],
 "riskiest_assumption": "the single belief that must be true for this business to work",
 "must_have": [{{"feature": "", "why": "which user pain or risk it addresses", "effort": "Low|Medium|High", "impact": "Low|Medium|High", "effort_hours": 0}}],
 "should_have": [{{"feature": "", "why": ""}}], "could_have": [{{"feature": "", "why": ""}}],
 "wont_have_yet": [{{"feature": "", "reason": "why to defer it"}}],
 "roadmap": [{{"phase": "", "weeks": "e.g. 1-2", "goal": "", "deliverables": [""], "exit_criteria": "measurable"}}],
 "recommended_tech_stack": [{{"layer": "", "technology": "", "reason": "free-tier friendly and suited to THIS idea"}}],
 "data_needs": ["data/integrations required and where they would come from"],
 "validation_experiments": [{{"experiment": "", "success_metric": "", "duration": ""}}],
 "cost_estimate": {{
   "currency": "currency of the target geography, 3 letters",
   "assumptions": ["team size, who is paid vs unpaid, tool/hosting tiers, rates used - state them all"],
   "items": [{{"category": "Development|Hosting & tools|Design|Testing|Legal & compliance|Validation & marketing|Contingency",
               "type": "cash|own_time", "amount_low": 0, "amount_high": 0, "note": "what it covers"}}],
   "monthly_running_cost": {{"low": 0, "high": 0, "note": "after launch, for hosting/APIs/tools"}}
 }},
 "required_resources": ["people, skills, data, accounts or equipment needed"],
 "testing_methods": ["how this MVP will be tested before and after launch"],
 "ratings": {{
  "technical_feasibility": {{"rating": 1, "reason": "1-5 for this team size"}},
  "data_and_integration_dependency": {{"rating": 1, "reason": "1-5: 5 = few external dependencies"}},
  "time_to_first_version": {{"rating": 1, "reason": "1-5: 5 = usable MVP in under 8 weeks"}}
 }}
}}
Give effort_hours for every must_have (a realistic range midpoint of hands-on hours). For cost, use "own_time" for unpaid student/founder hours valued at a stated hourly rate and "cash" for money actually spent; free tiers cost 0. Give 4-5 must_have, 3 should_have, 2-3 could_have, 3 wont_have_yet, 4-5 roadmap phases, 3 experiments."""
        data = self.llm_json("You are a pragmatic product lead who cuts scope ruthlessly.", user, max_tokens=4200,
                             temperature=0.3, required_keys=["must_have", "roadmap", "ratings"],
                             anchors=self.anchors_for(context))
        weeks = [_end_week(p.get("weeks")) for p in data.get("roadmap", []) if isinstance(p, dict)]
        roadmap_weeks = max(weeks) if weeks else None
        data["estimated_mvp_weeks"] = roadmap_weeks
        data["timeline_check"] = self._timeline_check(data, roadmap_weeks)
        if data["timeline_check"].get("suggested_weeks") and data["timeline_check"]["status"] != "ok":
            data["estimated_mvp_weeks"] = max(roadmap_weeks or 0, data["timeline_check"]["suggested_weeks"])
            self.warnings.append("Roadmap length did not match the estimated effort and team capacity; the longer estimate is shown.")
        data["cost_estimate"] = self._cost_estimate(data.get("cost_estimate"))
        data["build_order"] = [b for b in (data.get("build_order") or []) if isinstance(b, dict) and b.get("what")]
        for k in ("required_resources", "testing_methods"):
            data[k] = [str(x) for x in (data.get(k) or []) if x]
        for f in data.get("must_have", []):
            if isinstance(f, dict):
                f["quadrant"] = ("Quick win" if f.get("impact") == "High" and f.get("effort") != "High" else
                                 "Major project" if f.get("impact") == "High" else
                                 "Fill-in" if f.get("effort") != "High" else "Reconsider")
        return data

    @staticmethod
    def _timeline_check(data, roadmap_weeks):
        """Compares the roadmap length with estimated hands-on hours and team capacity."""
        try:
            size, hrs = float(data.get("team_size") or 0), float(data.get("hours_per_week_each") or 0)
        except (TypeError, ValueError):
            size = hrs = 0
        hours = 0.0
        for f in data.get("must_have", []):
            try:
                hours += max(0.0, float(f.get("effort_hours") or 0))
            except (TypeError, ValueError, AttributeError):
                pass
        if not (size > 0 and hrs > 0 and hours > 0 and roadmap_weeks):
            return {"status": "unknown", "note": "Effort or team capacity was not stated, so the timeline could not be cross-checked."}
        weekly = size * hrs
        needed_weeks = math.ceil(hours * 1.25 / weekly)       # +25% for testing, bugs and rework
        status = "ok" if roadmap_weeks >= needed_weeks else "tight" if roadmap_weeks >= 0.75 * needed_weeks else "unrealistic"
        note = (f"Must-have features need about {hours:.0f} hands-on hours (+25% for testing and rework). A team of {size:.0f} working "
                f"{hrs:.0f} h/week each delivers {weekly:.0f} h/week, so about {needed_weeks} weeks are needed; the roadmap plans {roadmap_weeks}.")
        return {"status": status, "required_hours": round(hours), "weekly_capacity_hours": round(weekly),
                "suggested_weeks": needed_weeks, "roadmap_weeks": roadmap_weeks, "note": note}

    @staticmethod
    def _cost_estimate(raw):
        """Validates the model's cost lines and adds the totals (arithmetic done here, not by the model)."""
        if not isinstance(raw, dict):
            return {"status": "unavailable", "reason": "Insufficient data: no cost estimate was returned."}
        cur = (raw.get("currency") or "USD").upper()[:3]
        items, tot = [], {"cash": [0.0, 0.0], "own_time": [0.0, 0.0]}
        for it in raw.get("items") or []:
            try:
                lo, hi = float(it.get("amount_low")), float(it.get("amount_high"))
            except (TypeError, ValueError, AttributeError):
                continue
            if lo < 0 or hi < lo:
                continue
            kind = "own_time" if it.get("type") == "own_time" else "cash"
            tot[kind][0] += lo
            tot[kind][1] += hi
            items.append({"category": it.get("category", "Other"), "type": kind, "low": lo, "high": hi,
                          "low_text": format_money(lo, cur), "high_text": format_money(hi, cur), "note": it.get("note", "")})
        if not items:
            return {"status": "unavailable", "reason": "Insufficient data: the cost lines were missing or invalid."}
        run = raw.get("monthly_running_cost") if isinstance(raw.get("monthly_running_cost"), dict) else {}
        out = {"status": "ok", "currency": cur, "assumptions": [str(a) for a in (raw.get("assumptions") or []) if a], "items": items,
               "cash_total": {"low": tot["cash"][0], "high": tot["cash"][1],
                              "text": f"{format_money(tot['cash'][0], cur)} – {format_money(tot['cash'][1], cur)}"},
               "own_time_total": {"low": tot["own_time"][0], "high": tot["own_time"][1],
                                  "text": f"{format_money(tot['own_time'][0], cur)} – {format_money(tot['own_time'][1], cur)}"},
               "label": "AI estimate based on the stated assumptions - not a quote"}
        try:
            out["monthly_running"] = {"low_text": format_money(float(run.get("low")), cur), "high_text": format_money(float(run.get("high")), cur),
                                      "note": run.get("note", "")}
        except (TypeError, ValueError):
            pass
        if not out["assumptions"]:
            out["assumptions"] = ["The model did not state its assumptions; treat these numbers with extra caution."]
        return out
