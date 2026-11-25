import json
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from .db import get_db

def normalize_recommendation(rec, score=0):
    """Normalizes any recommendation text to PROCEED, IMPROVE, or RECONSIDER"""
    if not rec or rec == 'Pending Validation' or rec == 'Pending':
        if score >= 75:
            return "PROCEED"
        elif score >= 55:
            return "IMPROVE"
        elif score > 0:
            return "RECONSIDER"
        return "PENDING"
    r = str(rec).upper()
    if "PROCEED" in r or "PURSUE" in r or "STRONG" in r:
        return "PROCEED"
    elif "IMPROVE" in r or "POTENTIAL" in r or "MODERATE" in r:
        return "IMPROVE"
    elif "RECONSIDER" in r or "PIVOT" in r or "RISK" in r or "HALT" in r:
        return "RECONSIDER"
    return "IMPROVE" if score >= 55 else "RECONSIDER"


class User(UserMixin):
    def __init__(self, id, username, email, password_hash, full_name, created_at, role='entrepreneur'):
        self.id = id
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.full_name = full_name
        self.created_at = created_at
        self.role = role

    @classmethod
    def get_by_id(cls, user_id):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                return cls(**dict(row))
        return None

    @classmethod
    def get_by_email(cls, email):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(?)", (email.strip(),))
            row = cursor.fetchone()
            if row:
                return cls(**dict(row))
        return None

    @classmethod
    def get_by_username(cls, username):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username.strip(),))
            row = cursor.fetchone()
            if row:
                return cls(**dict(row))
        return None

    @classmethod
    def create(cls, username, email, password, full_name=None):
        hashed = generate_password_hash(password)
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (username, email, password_hash, full_name)
                VALUES (?, ?, ?, ?)
            """, (username.strip(), email.strip(), hashed, full_name or username))
            user_id = cursor.lastrowid
        return cls.get_by_id(user_id)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "created_at": str(self.created_at),
            "role": self.role
        }


class StartupIdea:
    @classmethod
    def create(cls, user_id, title, raw_description, industry=None, target_audience=None,
               problem_statement=None, proposed_solution=None, revenue_model=None, is_sample=False):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO startup_ideas (
                    user_id, title, raw_description, industry, target_audience,
                    problem_statement, proposed_solution, revenue_model, status, is_sample
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?)
            """, (
                user_id, title, raw_description, industry, target_audience,
                problem_statement, proposed_solution, revenue_model, 1 if is_sample else 0
            ))
            return cursor.lastrowid

    @classmethod
    def get_by_id(cls, idea_id, user_id=None):
        with get_db() as conn:
            cursor = conn.cursor()
            if user_id:
                cursor.execute("SELECT * FROM startup_ideas WHERE id = ? AND user_id = ?", (idea_id, user_id))
            else:
                cursor.execute("SELECT * FROM startup_ideas WHERE id = ?", (idea_id,))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                d['recommendation'] = normalize_recommendation(d.get('recommendation'), d.get('viability_score', 0))
                return d
            return None

    @classmethod
    def get_all_by_user(cls, user_id):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM startup_ideas
                WHERE user_id = ?
                ORDER BY created_at DESC
            """, (user_id,))
            rows = cursor.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d['recommendation'] = normalize_recommendation(d.get('recommendation'), d.get('viability_score', 0))
                result.append(d)
            return result

    @classmethod
    def get_recent_by_user(cls, user_id, limit=5):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM startup_ideas
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (user_id, limit))
            rows = cursor.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d['recommendation'] = normalize_recommendation(d.get('recommendation'), d.get('viability_score', 0))
                result.append(d)
            return result

    @classmethod
    def update_extracted_data(cls, idea_id, industry, target_audience, problem_statement, proposed_solution, revenue_model):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE startup_ideas
                SET industry = COALESCE(NULLIF(?, ''), industry),
                    target_audience = COALESCE(NULLIF(?, ''), target_audience),
                    problem_statement = COALESCE(NULLIF(?, ''), problem_statement),
                    proposed_solution = COALESCE(NULLIF(?, ''), proposed_solution),
                    revenue_model = COALESCE(NULLIF(?, ''), revenue_model),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (industry or '', target_audience or '', problem_statement or '',
                  proposed_solution or '', revenue_model or '', idea_id))

    @classmethod
    def update_status(cls, idea_id, status, viability_score=None, recommendation=None):
        with get_db() as conn:
            cursor = conn.cursor()
            updates = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
            params = [status]
            if viability_score is not None:
                updates.append("viability_score = ?")
                params.append(viability_score)
            if recommendation is not None:
                updates.append("recommendation = ?")
                params.append(normalize_recommendation(recommendation, viability_score or 0))
            params.append(idea_id)

            cursor.execute(f"UPDATE startup_ideas SET {', '.join(updates)} WHERE id = ?", params)

    @classmethod
    def delete(cls, idea_id, user_id):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM startup_ideas WHERE id = ? AND user_id = ?", (idea_id, user_id))
            return cursor.rowcount > 0

    @classmethod
    def get_user_stats(cls, user_id):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_ideas,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_validations,
                    AVG(CASE WHEN status = 'completed' THEN viability_score ELSE NULL END) as avg_score,
                    SUM(CASE WHEN status = 'completed' AND viability_score >= 75 THEN 1 ELSE 0 END) as proceed_count,
                    SUM(CASE WHEN status = 'completed' AND viability_score >= 55 AND viability_score < 75 THEN 1 ELSE 0 END) as improve_count,
                    SUM(CASE WHEN viability_score < 55 AND status = 'completed' THEN 1 ELSE 0 END) as reconsider_count,
                    SUM(CASE WHEN status = 'completed' AND viability_score >= 75 THEN 1 ELSE 0 END) as high_potential
                FROM startup_ideas
                WHERE user_id = ?
            """, (user_id,))
            row = cursor.fetchone()
            data = dict(row) if row else {}
            return {
                "total_ideas": data.get("total_ideas") or 0,
                "completed_validations": data.get("completed_validations") or 0,
                "avg_score": round(data.get("avg_score") or 0, 1),
                "high_potential": data.get("high_potential") or 0,
                "proceed_count": data.get("proceed_count") or 0,
                "improve_count": data.get("improve_count") or 0,
                "reconsider_count": data.get("reconsider_count") or 0
            }

    @classmethod
    def get_final_verdict(cls, idea_id):
        """Final verdict built ONLY from stored analysis results (no fabricated defaults)."""
        idea = cls.get_by_id(idea_id)
        if not idea:
            return None

        analyses = AnalysisResult.get_all_for_idea(idea_id)
        report = analyses.get("report", {}).get("data", {}) or {}
        swot_risk = analyses.get("swot_risk", {}).get("data", {}) or {}
        market = analyses.get("market", {}).get("data", {}) or {}
        comp = analyses.get("competitors", {}).get("data", {}) or {}

        score = report.get("viability_score")
        if score is None:
            score = idea.get("viability_score")
        rec = normalize_recommendation(report.get("recommendation") or idea.get("recommendation"), score or 0) \
            if score is not None else "PENDING"

        def first_text(items):
            if items and isinstance(items, list):
                it = items[0]
                return it.get("point") or it.get("risk") if isinstance(it, dict) else str(it)
            return None

        strength = report.get("biggest_strength") or first_text(swot_risk.get("swot", {}).get("strengths"))
        weakness = report.get("biggest_weakness") or first_text(swot_risk.get("risks"))
        opportunity = report.get("best_market_opportunity") or first_text(swot_risk.get("swot", {}).get("opportunities"))
        action = report.get("recommended_next_action") or first_text(report.get("next_immediate_steps"))

        return {
            "idea_id": idea["id"],
            "title": idea["title"],
            "industry": idea.get("industry") or "Not specified",
            "viability_score": score,
            "recommendation": rec,
            "biggest_strength": strength,
            "biggest_weakness": weakness,
            "best_market_opportunity": opportunity,
            "recommended_next_action": action,
            "scoring_rationale": report.get("scoring_rationale") or {},
            "confidence": (report.get("confidence") or {}).get("level"),
            "radar_scores": {
                "market": report.get("market_score"),
                "competition": report.get("competition_score"),
                "execution": report.get("execution_score"),
                "business": report.get("business_score"),
                "riskResistance": report.get("risk_resistance_score"),
            },
            "market_tam": market.get("tam") if market.get("tam") not in (None, "Not available", "Insufficient data") else None,
            "verified_competitors": len(comp.get("competitors", [])) if comp and not comp.get("_error") else 0,
            "created_at": idea.get("created_at"),
        }


class AnalysisResult:
    @classmethod
    def save_or_update(cls, idea_id, agent_name, result_data, status='completed', execution_time_sec=0.0):
        result_json = json.dumps(result_data, ensure_ascii=False) if not isinstance(result_data, str) else result_data
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO analysis_results (idea_id, agent_name, result_json, status, execution_time_sec)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(idea_id, agent_name) DO UPDATE SET
                    result_json = excluded.result_json,
                    status = excluded.status,
                    execution_time_sec = excluded.execution_time_sec,
                    created_at = CURRENT_TIMESTAMP
            """, (idea_id, agent_name, result_json, status, execution_time_sec))

    @classmethod
    def get_by_idea_and_agent(cls, idea_id, agent_name):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM analysis_results
                WHERE idea_id = ? AND agent_name = ?
            """, (idea_id, agent_name))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                try:
                    d["data"] = json.loads(d["result_json"])
                except Exception:
                    d["data"] = {}
                return d
        return None

    @classmethod
    def get_all_for_idea(cls, idea_id):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM analysis_results WHERE idea_id = ?", (idea_id,))
            rows = cursor.fetchall()
            results = {}
            for r in rows:
                d = dict(r)
                try:
                    d["data"] = json.loads(d["result_json"])
                except Exception:
                    d["data"] = {}
                results[d["agent_name"]] = d
            return results


class Competitor:
    @classmethod
    def save_batch(cls, idea_id, competitors_list):
        import json as _json
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM competitors WHERE idea_id = ?", (idea_id,))
            for comp in competitors_list or []:
                feat = comp.get("key_features") or comp.get("features") or ""
                if isinstance(feat, list):
                    feat = ", ".join(feat)
                pricing = comp.get("pricing")
                pricing_text = pricing.get("text") if isinstance(pricing, dict) else (comp.get("pricing_model") or "Not found")
                src = (pricing.get("source_url") if isinstance(pricing, dict) else "") or comp.get("website_url", "")
                cursor.execute("""
                    INSERT INTO competitors (
                        idea_id, name, competitor_type, website_url, pricing_model,
                        features, strengths, weaknesses, market_gap, source_reference, verified_source, details_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    idea_id,
                    comp.get("name", "Unknown"),
                    comp.get("competitor_type", "Direct"),
                    comp.get("website_url", ""),
                    pricing_text,
                    feat,
                    "; ".join(comp.get("site_strengths") or []) or comp.get("positioning", comp.get("strengths", "")),
                    "; ".join(comp.get("ai_weaknesses") or []) or comp.get("gaps_vs_idea", comp.get("weaknesses", "")),
                    comp.get("differentiation_opportunity", comp.get("market_gap", "")),
                    src,
                    1 if comp.get("website_verified", comp.get("verified_source")) else 0,
                    _json.dumps(comp, default=str),
                ))

    @classmethod
    def get_by_idea(cls, idea_id):
        import json as _json
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM competitors WHERE idea_id = ? ORDER BY id ASC", (idea_id,))
            rows = []
            for r in cursor.fetchall():
                d = dict(r)
                try:
                    details = _json.loads(d.get("details_json") or "{}")
                except ValueError:
                    details = {}
                merged = {**details, **{k: v for k, v in d.items() if k != "details_json"}}
                merged["details"] = details
                rows.append(merged)
            return rows


class ChatMessage:
    @classmethod
    def add_message(cls, idea_id, user_id, role, message):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO chat_messages (idea_id, user_id, role, message)
                VALUES (?, ?, ?, ?)
            """, (idea_id, user_id, role, message))
            return cursor.lastrowid

    @classmethod
    def get_history_for_idea(cls, idea_id, limit=50):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM chat_messages
                WHERE idea_id = ?
                ORDER BY created_at ASC
                LIMIT ?
            """, (idea_id, limit))
            return [dict(r) for r in cursor.fetchall()]

    @classmethod
    def clear_history(cls, idea_id):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM chat_messages WHERE idea_id = ?", (idea_id,))


class ValidationReport:
    @classmethod
    def save_report(cls, idea_id, user_id, summary_text, viability_score, market_score,
                    competition_score, execution_score, risk_score, pdf_filename, full_report_data):
        report_json = json.dumps(full_report_data, ensure_ascii=False) if not isinstance(full_report_data, str) else full_report_data
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO validation_reports (
                    idea_id, user_id, summary_text, viability_score, market_score,
                    competition_score, execution_score, risk_score, pdf_filename, full_report_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                idea_id, user_id, summary_text, viability_score, market_score,
                competition_score, execution_score, risk_score, pdf_filename, report_json
            ))
            return cursor.lastrowid

    @classmethod
    def get_by_idea(cls, idea_id):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM validation_reports
                WHERE idea_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (idea_id,))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                try:
                    d["data"] = json.loads(d["full_report_json"])
                except Exception:
                    d["data"] = {}
                return d
        return None
