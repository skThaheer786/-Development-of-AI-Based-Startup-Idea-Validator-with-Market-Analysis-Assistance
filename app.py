import os
import io
import csv
import json
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, Response, abort
)
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from config import Config
from services.scoring import RECOMMENDATION_LABELS
from database.db import init_db, get_db
from database.models import (
    User, StartupIdea, AnalysisResult, Competitor, ChatMessage, ValidationReport
)
from orchestration.pipeline import OrchestrationPipeline
from agents.startup_advisor import StartupAdvisorAgent
from services.groq_service import GroqService, LLMError
from services.search_service import SearchService
from services.pdf_service import PDFReportService

def item_text(item, *keys):
    """Return display text for a str-or-dict item (older reports stored plain strings)."""
    if isinstance(item, dict):
        for k in keys or ("point", "feature", "risk", "opportunity", "signal", "trend", "name", "text"):
            if item.get(k):
                return str(item[k])
        return " ".join(str(v) for v in item.values() if isinstance(v, str))[:200]
    return "" if item is None else str(item)


def _rel_url(target):
    """Only allow same-site relative redirects after login (prevents open redirects)."""
    return target if target and target.startswith("/") and not target.startswith("//") else None


def create_app(test_config=None):
    """Application factory for Startup Idea Validator AI"""
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.from_object(Config)

    if test_config:
        app.config.update(test_config)

    # Initialize LoginManager
    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.login_message = "Please sign in to access your startup dashboard."
    login_manager.login_message_category = "info"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.get_by_id(int(user_id))

    # Initialize Database Schema
    with app.app_context():
        init_db()
        # A server restart kills background threads: never leave ideas stuck in "analyzing"
        with get_db() as conn:
            conn.execute("UPDATE startup_ideas SET status = 'failed' WHERE status = 'analyzing'")

    # Context processor to inject global parameters
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    from services.scoring import RECOMMENDATION_LABELS

    def _wants_json():
        return request.path.startswith("/api/")

    @app.errorhandler(404)
    def not_found(_e):
        if _wants_json():
            return jsonify({"status": "error", "message": "Not found"}), 404
        return render_template("error.html", code=404, title="Page not found",
                               message="That page or analysis does not exist, or it belongs to another account."), 404

    @app.errorhandler(500)
    def server_error(_e):
        if _wants_json():
            return jsonify({"status": "error", "message": "Something went wrong on the server. Please try again."}), 500
        return render_template("error.html", code=500, title="Something went wrong",
                               message="The page could not be displayed. Your data is safe; please go back and try again."), 500

    @app.template_filter("rec_label")
    def rec_label(value):
        """PROCEED / IMPROVE / RECONSIDER -> Proceed / Improve / High Risk (stored values are unchanged)."""
        return RECOMMENDATION_LABELS.get((value or "").upper(), value or "Pending")

    @app.context_processor
    def inject_globals():
        static_dir = os.path.join(app.root_path, "static")
        stamps = [os.path.getmtime(os.path.join(d, f)) for d, _, fs in os.walk(static_dir) for f in fs]
        return {
            "asset_v": int(max(stamps)) if stamps else 0,   # changes whenever CSS/JS change -> no stale cache
            "current_year": datetime.now().year,
            "demo_mode": False,
            "groq_configured": bool(Config.GROQ_API_KEY),
            "tavily_configured": bool(Config.TAVILY_API_KEY),
            "selected_model": Config.GROQ_MODEL,
            "model_note": Config.MODEL_NOTE,
        }

    @app.template_filter("item_text")
    def _item_text_filter(item, *keys):
        return item_text(item, *keys)

    @app.template_filter("basis_label")
    def _basis_label(basis):
        return {"sourced": "Sourced", "from_idea": "From your idea", "market_evidence": "Market data",
                "competitor_data": "Competitor data", "ai_analysis": "AI analysis",
                "ai_inference": "AI inference", "ai_assumption": "AI assumption",
                "idea": "From your idea", "competitor_evidence": "Competitor data"}.get(basis, "AI analysis")

    # =========================================================================
    # 1. AUTHENTICATION ROUTES (Page 1)
    # =========================================================================
    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")
            remember = bool(request.form.get("remember"))

            user = User.get_by_email(email)
            if user and user.check_password(password):
                login_user(user, remember=remember)
                flash(f"Welcome back, {user.full_name or user.username}!", "success")
                next_page = _rel_url(request.args.get("next"))
                return redirect(next_page or url_for("dashboard"))
            else:
                flash("Invalid email address or password. Please try again.", "danger")

        return render_template("auth/login.html")

    @app.route("/demo-login")
    def demo_login():
        """1-click instant login helper for judges and reviewers"""
        demo_user = User.get_by_email("demo@startupvalidator.com")
        if not demo_user:
            demo_user = User.create(
                username="demofounder",
                email="demo@startupvalidator.com",
                password="password123",
                full_name="Alex Rivera (Founder)"
            )
        login_user(demo_user)
        flash("Logged in with Founder Demo Account. Welcome!", "success")
        return redirect(url_for("dashboard"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            full_name = request.form.get("full_name", "").strip()
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm_password", "")

            if not email or not username or not password:
                flash("All required fields must be filled.", "warning")
                return render_template("auth/register.html")

            if password != confirm:
                flash("Passwords do not match.", "warning")
                return render_template("auth/register.html")

            if User.get_by_email(email):
                flash("An account with that email already exists.", "danger")
                return render_template("auth/register.html")

            if User.get_by_username(username):
                flash("That username is already taken. Please choose another.", "danger")
                return render_template("auth/register.html")

            new_user = User.create(username, email, password, full_name=full_name)
            login_user(new_user)
            flash("Account created successfully! Welcome to your Startup Validator.", "success")
            return redirect(url_for("dashboard"))

        return render_template("auth/register.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        flash("You have signed out successfully.", "info")
        return redirect(url_for("login"))

    # =========================================================================
    # 2. MAIN DASHBOARD (Page 2)
    # =========================================================================
    @app.route("/dashboard")
    @login_required
    def dashboard():
        selected_id = request.args.get("idea_id", type=int)
        stats = StartupIdea.get_user_stats(current_user.id)
        recent_ideas = StartupIdea.get_recent_by_user(current_user.id, limit=6)
        all_ideas = StartupIdea.get_all_by_user(current_user.id)

        # Determine which idea to display final verdict & insights for
        active_idea = None
        if selected_id:
            active_idea = StartupIdea.get_by_id(selected_id, current_user.id)
        if not active_idea and recent_ideas:
            active_idea = recent_ideas[0]

        latest_verdict = None
        active_analyses = {}
        if active_idea:
            latest_verdict = StartupIdea.get_final_verdict(active_idea["id"])
            active_analyses = AnalysisResult.get_all_for_idea(active_idea["id"])

        return render_template(
            "dashboard/index.html",
            stats=stats,
            recent_ideas=recent_ideas,
            all_ideas=all_ideas,
            active_idea=active_idea,
            latest_verdict=latest_verdict,
            active_analyses=active_analyses
        )

    # =========================================================================
    # 3. STARTUP IDEA SUBMISSION (Page 3)
    # =========================================================================
    @app.route("/submit", methods=["GET", "POST"])
    @login_required
    def submit_idea():
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            industry = request.form.get("industry", "").strip()
            raw_description = request.form.get("raw_description", "").strip()
            target_audience = request.form.get("target_audience", "").strip()
            problem_statement = request.form.get("problem_statement", "").strip()
            proposed_solution = request.form.get("proposed_solution", "").strip()
            revenue_model = request.form.get("revenue_model", "").strip()
            run_async_flag = request.form.get("run_async", "true") == "true"

            if not title or not raw_description:
                flash("Please provide at least an Idea Title and a Description.", "warning")
                return render_template("dashboard/submit.html")

            idea_id = StartupIdea.create(
                user_id=current_user.id,
                title=title,
                raw_description=raw_description,
                industry=industry,
                target_audience=target_audience,
                problem_statement=problem_statement,
                proposed_solution=proposed_solution,
                revenue_model=revenue_model
            )

            flash(f"Startup idea '{title}' submitted. Researching the web and running the analysis agents...", "success")

            # Kick off validation
            pipeline = OrchestrationPipeline(idea_id=idea_id, user_id=current_user.id)
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
                pipeline.run_async()
                return jsonify({
                    "status": "started",
                    "idea_id": idea_id,
                    "redirect_url": url_for("view_report", idea_id=idea_id)
                })

            if run_async_flag:
                pipeline.run_async()
                return redirect(url_for("view_market", idea_id=idea_id, validated="started"))
            else:
                outcome = pipeline.run_synchronous()
                if outcome.get("status") == "failed":
                    flash(f"Validation could not be completed: {outcome.get('error')}", "danger")
                return redirect(url_for("view_report", idea_id=idea_id))

        return render_template("dashboard/submit.html")

    # =========================================================================
    # 4. MARKET OPPORTUNITY ANALYSIS (Page 4)
    # =========================================================================
    @app.route("/idea/<int:idea_id>/market")
    @login_required
    def view_market(idea_id):
        idea = StartupIdea.get_by_id(idea_id, current_user.id)
        if not idea:
            abort(404)
        analyses = AnalysisResult.get_all_for_idea(idea_id)
        market_res = analyses.get("market", {})
        extractor_res = analyses.get("extractor", {})
        return render_template(
            "dashboard/market.html",
            idea=idea,
            market=market_res.get("data", {}),
            extractor=extractor_res.get("data", {}),
            analyses=analyses
        )

    # =========================================================================
    # 5. COMPETITOR ANALYSIS (Page 5)
    # =========================================================================
    @app.route("/idea/<int:idea_id>/competitors")
    @login_required
    def view_competitors(idea_id):
        idea = StartupIdea.get_by_id(idea_id, current_user.id)
        if not idea:
            abort(404)
        competitors = Competitor.get_by_idea(idea_id)
        analyses = AnalysisResult.get_all_for_idea(idea_id)
        comp_agent_data = analyses.get("competitors", {}).get("data", {})
        return render_template(
            "dashboard/competitors.html",
            idea=idea,
            competitors=competitors,
            comp_data=comp_agent_data,
            analyses=analyses
        )

    # =========================================================================
    # 6. SWOT ANALYSIS (Page 6)
    # =========================================================================
    @app.route("/idea/<int:idea_id>/swot")
    @login_required
    def view_swot(idea_id):
        idea = StartupIdea.get_by_id(idea_id, current_user.id)
        if not idea:
            abort(404)
        analyses = AnalysisResult.get_all_for_idea(idea_id)
        swot_data = analyses.get("swot_risk", {}).get("data", {}).get("swot", {})
        return render_template(
            "dashboard/swot.html",
            idea=idea,
            swot=swot_data,
            analyses=analyses
        )

    # =========================================================================
    # 7. RISK ANALYSIS (Page 7)
    # =========================================================================
    @app.route("/idea/<int:idea_id>/risks")
    @login_required
    def view_risks(idea_id):
        idea = StartupIdea.get_by_id(idea_id, current_user.id)
        if not idea:
            abort(404)
        analyses = AnalysisResult.get_all_for_idea(idea_id)
        swot_risk_res = analyses.get("swot_risk", {}).get("data", {})
        risks = swot_risk_res.get("risks", [])
        overall_risk_score = swot_risk_res.get("overall_risk_score")
        risk_rating = swot_risk_res.get("risk_rating", "Not assessed")
        return render_template(
            "dashboard/risks.html",
            idea=idea,
            risks=risks,
            overall_risk_score=overall_risk_score,
            risk_rating=risk_rating,
            founder_advice=swot_risk_res.get("founder_advice", ""),
            analyses=analyses
        )

    # =========================================================================
    # 8. MVP FEATURE RECOMMENDATIONS (Page 8)
    # =========================================================================
    @app.route("/idea/<int:idea_id>/mvp")
    @login_required
    def view_mvp(idea_id):
        idea = StartupIdea.get_by_id(idea_id, current_user.id)
        if not idea:
            abort(404)
        analyses = AnalysisResult.get_all_for_idea(idea_id)
        mvp_data = analyses.get("mvp", {}).get("data", {})
        return render_template(
            "dashboard/mvp.html",
            idea=idea,
            mvp=mvp_data,
            analyses=analyses
        )

    # =========================================================================
    # 9. GO-TO-MARKET STRATEGY (Page 9)
    # =========================================================================
    @app.route("/idea/<int:idea_id>/gtm")
    @login_required
    def view_gtm(idea_id):
        idea = StartupIdea.get_by_id(idea_id, current_user.id)
        if not idea:
            abort(404)
        analyses = AnalysisResult.get_all_for_idea(idea_id)
        gtm_data = analyses.get("gtm", {}).get("data", {})
        return render_template(
            "dashboard/gtm.html",
            idea=idea,
            gtm=gtm_data,
            analyses=analyses
        )

    # =========================================================================
    # 10. AI STARTUP ADVISOR CHATBOT (Page 10)
    # =========================================================================
    @app.route("/advisor")
    @login_required
    def general_advisor():
        ideas = StartupIdea.get_all_by_user(current_user.id)
        if ideas:
            return redirect(url_for("view_chat", idea_id=ideas[0]["id"]))
        flash("Please submit or generate a startup idea first to chat with the AI Advisor.", "info")
        return redirect(url_for("submit_idea"))

    @app.route("/idea/<int:idea_id>/chat")
    @login_required
    def view_chat(idea_id):
        idea = StartupIdea.get_by_id(idea_id, current_user.id)
        if not idea:
            abort(404)
        all_ideas = StartupIdea.get_all_by_user(current_user.id)
        chat_history = ChatMessage.get_history_for_idea(idea_id)
        analyses = AnalysisResult.get_all_for_idea(idea_id)
        return render_template(
            "dashboard/chat.html",
            idea=idea,
            all_ideas=all_ideas,
            chat_history=chat_history,
            analyses=analyses
        )

    # =========================================================================
    # 11. VALIDATION HISTORY (Page 11)
    # =========================================================================
    @app.route("/history")
    @login_required
    def view_history():
        ideas = StartupIdea.get_all_by_user(current_user.id)
        return render_template("dashboard/history.html", ideas=ideas)

    # =========================================================================
    # 12. FINAL REPORT GENERATION (Page 12)
    # =========================================================================
    @app.route("/idea/<int:idea_id>/report")
    @login_required
    def view_report(idea_id):
        idea = StartupIdea.get_by_id(idea_id, current_user.id)
        if not idea:
            abort(404)
        analyses = AnalysisResult.get_all_for_idea(idea_id)
        competitors = Competitor.get_by_idea(idea_id)
        report_record = ValidationReport.get_by_idea(idea_id)
        report_data = analyses.get("report", {}).get("data", {})
        return render_template(
            "dashboard/report.html",
            idea=idea,
            analyses=analyses,
            competitors=competitors,
            report_record=report_record,
            report_data=report_data,
            legacy_report=bool(report_data) and "score_breakdown" not in report_data,
        )

    # =========================================================================
    # 13. SETTINGS & PROFILE (Page 13)
    # =========================================================================
    @app.route("/settings", methods=["GET", "POST"])
    @login_required
    def view_settings():
        if request.method == "POST":
            groq_key = request.form.get("groq_api_key", "").strip()
            tavily_key = request.form.get("tavily_api_key", "").strip()
            groq_model = request.form.get("groq_model", Config.GROQ_MODEL).strip()

            Config.QUICK_MODE = request.form.get("analysis_mode") == "quick"
            from services.groq_service import clean_key, key_problem
            groq_key, tavily_key = clean_key(groq_key), clean_key(tavily_key)
            if key_problem(groq_key):
                flash("Groq key not saved: " + key_problem(groq_key), "danger")
                return redirect(url_for("view_settings"))
            if tavily_key and (not tavily_key.isascii() or " " in tavily_key):
                flash("Tavily key not saved: it contains invalid characters. Re-copy it from tavily.com.", "danger")
                return redirect(url_for("view_settings"))

            Config.update_runtime_keys(
                groq_key=groq_key if groq_key else Config.GROQ_API_KEY,
                tavily_key=tavily_key if tavily_key else Config.TAVILY_API_KEY,
                model=groq_model,
            )

            flash("Settings and API configuration updated successfully!", "success")
            return redirect(url_for("view_settings"))

        return render_template(
            "dashboard/settings.html",
            models=Config.AVAILABLE_MODELS,
            current_model=Config.GROQ_MODEL,
            quick_mode=Config.QUICK_MODE,
            groq_key_set=bool(Config.GROQ_API_KEY),
            tavily_key_set=bool(Config.TAVILY_API_KEY),
        )

    # =========================================================================
    # API ENDPOINTS (Asynchronous Pipeline, Chat, Status, Exports)
    # =========================================================================
    @app.route("/api/idea/<int:idea_id>/status")
    @login_required
    def api_idea_status(idea_id):
        idea = StartupIdea.get_by_id(idea_id, current_user.id)
        if not idea:
            return jsonify({"status": "error", "message": "Idea not found"}), 404
        progress = OrchestrationPipeline.get_progress(idea_id)
        verdict = StartupIdea.get_final_verdict(idea_id) if idea.get("status") == "completed" else None
        return jsonify({
            "idea_id": idea_id,
            "status": idea.get("status"),
            "viability_score": idea.get("viability_score"),
            "recommendation": idea.get("recommendation"),
            "progress": progress,
            "verdict": verdict
        })

    @app.route("/api/idea/<int:idea_id>/run", methods=["POST"])
    @login_required
    def api_trigger_validation(idea_id):
        idea = StartupIdea.get_by_id(idea_id, current_user.id)
        if not idea:
            return jsonify({"status": "error", "message": "Idea not found"}), 404
        if OrchestrationPipeline.is_running(idea_id):
            return jsonify({"status": "running", "message": "This idea is already being analysed."}), 409
        pipeline = OrchestrationPipeline(idea_id=idea_id, user_id=current_user.id)
        pipeline.run_async()
        return jsonify({"status": "started", "message": "Validation pipeline initiated."})

    @app.route("/api/idea/<int:idea_id>/chat", methods=["POST"])
    @login_required
    def api_chat(idea_id):
        idea = StartupIdea.get_by_id(idea_id, current_user.id)
        if not idea:
            return jsonify({"status": "error", "message": "Idea not found"}), 404

        data = request.get_json() or {}
        user_message = data.get("message", "").strip()
        if not user_message:
            return jsonify({"status": "error", "message": "Empty message"}), 400

        # Save user message
        ChatMessage.add_message(idea_id=idea_id, user_id=current_user.id, role="user", message=user_message)

        analyses = AnalysisResult.get_all_for_idea(idea_id)
        history = ChatMessage.get_history_for_idea(idea_id)
        ctx = {
            "title": idea.get("title"), "raw_description": idea.get("raw_description"),
            "extractor_data": analyses.get("extractor", {}).get("data", {}),
            "market_data": analyses.get("market", {}).get("data", {}),
            "competitor_data": analyses.get("competitors", {}).get("data", {}),
            "swot_risk_data": analyses.get("swot_risk", {}).get("data", {}),
            "mvp_data": analyses.get("mvp", {}).get("data", {}),
            "gtm_data": analyses.get("gtm", {}).get("data", {}),
            "report_data": analyses.get("report", {}).get("data", {}),
        }
        try:
            reply = StartupAdvisorAgent().answer_query(ctx, user_message, history[:-1])
        except LLMError as exc:
            return jsonify({"status": "error", "message": exc.user_message}), 503
        except Exception as exc:
            return jsonify({"status": "error", "message": f"Advisor error: {type(exc).__name__}"}), 500

        ChatMessage.add_message(idea_id=idea_id, user_id=current_user.id, role="assistant", message=reply)
        return jsonify({"status": "success", "reply": reply, "source": f"Groq {Config.GROQ_MODEL}"})

    @app.route("/api/idea/<int:idea_id>/chat/clear", methods=["POST"])
    @login_required
    def api_clear_chat(idea_id):
        idea = StartupIdea.get_by_id(idea_id, current_user.id)
        if not idea:
            return jsonify({"status": "error", "message": "Idea not found"}), 404
        ChatMessage.clear_history(idea_id)
        return jsonify({"status": "success", "message": "Chat history cleared."})

    @app.route("/api/idea/<int:idea_id>/delete", methods=["POST"])
    @login_required
    def api_delete_idea(idea_id):
        success = StartupIdea.delete(idea_id, current_user.id)
        if success:
            flash("Startup idea deleted successfully.", "info")
            return redirect(url_for("view_history"))
        flash("Could not delete idea or unauthorized.", "danger")
        return redirect(url_for("view_history"))

    @app.route("/api/export/<int:idea_id>/pdf")
    @login_required
    def export_pdf(idea_id):
        idea = StartupIdea.get_by_id(idea_id, current_user.id)
        if not idea:
            abort(404)
        analyses = AnalysisResult.get_all_for_idea(idea_id)
        competitors = Competitor.get_by_idea(idea_id)
        report_record = ValidationReport.get_by_idea(idea_id)

        # If PDF file already exists on disk, send it
        if report_record and report_record.get("pdf_filename"):
            filepath = os.path.join(Config.EXPORTS_DIR, report_record.get("pdf_filename"))
            if os.path.exists(filepath):
                return send_file(
                    filepath,
                    as_attachment=True,
                    download_name=f"Validation_Report_{idea.get('title', 'Startup')}.pdf",
                    mimetype="application/pdf"
                )

        # Generate on the fly
        pdf_bytes = PDFReportService.generate_report(
            idea=idea,
            analysis_dict=analyses,
            competitors=competitors,
            report_meta=report_record or {}
        )
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f"attachment;filename=Validation_Report_{idea.get('title', 'Startup')}.pdf"}
        )

    @app.route("/api/export/<int:idea_id>/json")
    @login_required
    def export_json(idea_id):
        idea = StartupIdea.get_by_id(idea_id, current_user.id)
        if not idea:
            abort(404)
        analyses = AnalysisResult.get_all_for_idea(idea_id)
        competitors = Competitor.get_by_idea(idea_id)
        report = ValidationReport.get_by_idea(idea_id)

        export_payload = {
            "startup_idea": idea,
            "analyses": analyses,
            "competitors": competitors,
            "validation_report": report,
            "exported_at": datetime.now().isoformat(),
            "export_source": "Startup Idea Validator AI"
        }
        return Response(
            json.dumps(export_payload, indent=2, ensure_ascii=False),
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment;filename=Startup_Validation_{idea_id}.json"}
        )

    def _bundle(idea_id):
        analyses = AnalysisResult.get_all_for_idea(idea_id)
        g = lambda k: analyses.get(k, {}).get("data", {}) or {}
        return analyses, g("extractor"), g("market"), g("competitors"), g("swot_risk"), g("mvp"), g("gtm"), g("report")

    @app.route("/api/export/<int:idea_id>/markdown")
    @login_required
    def export_markdown(idea_id):
        idea = StartupIdea.get_by_id(idea_id, current_user.id)
        if not idea:
            abort(404)
        analyses, ex, market, comp, swot_risk, mvp, gtm, report = _bundle(idea_id)
        competitors = Competitor.get_by_idea(idea_id)
        swot = swot_risk.get("swot", {})
        score = report.get("viability_score")

        md = [f"# Startup Validation Report: {idea.get('title')}",
              f"**Industry:** {idea.get('industry') or 'Not specified'}  ",
              f"**Viability Score:** {score if score is not None else 'n/a'}/100 ({RECOMMENDATION_LABELS.get(str(report.get('recommendation', 'Pending')).upper(), report.get('recommendation', 'Pending'))})  ",
              f"**Confidence:** {(report.get('confidence') or {}).get('level', 'n/a')}  ",
              f"**Date:** {datetime.now().strftime('%B %d, %Y')}", "", "---", "",
              "## 1. Executive Summary", report.get("executive_summary") or "Not available.", ""]
        if report.get("verdict_explanation"):
            md += ["", "### Why this verdict", report["verdict_explanation"], ""]
            for r_ in report.get("main_score_reducers") or []:
                md.append(f"- **{r_.get('factor_label')}** ({r_.get('dimension_label')}, {r_.get('rating')}/5): {r_.get('reason')} (+{r_.get('points_if_raised_to_4')} pts if raised to 4/5)")
            for title_, key_, field_ in (("Main strengths", "key_strengths", "point"), ("Main weaknesses", "key_weaknesses", "point"), ("Main risks", "key_risks", "risk")):
                if report.get(key_):
                    md += ["", f"**{title_}**"] + [f"- {i_.get(field_)}" for i_ in report[key_]]
            md.append("")
        if report.get("disclaimer"):
            md += [f"> {report['disclaimer']}", ""]
        if report.get("verdict_explanation"):
            md += ["", "**Why this verdict:** " + report["verdict_explanation"], ""]
            for f in report.get("main_score_reducers") or []:
                md.append(f"- Holding the score down: {f['factor_label']} ({f['dimension_label']}, {f['rating']}/5) - {f['reason']} (+{f['points_to_raise'] if 'points_to_raise' in f else f['points_if_raised_to_4']} pts if raised to 4/5)")
            for title, key, field in (("Main strengths", "key_strengths", "point"), ("Main weaknesses", "key_weaknesses", "point"), ("Top risks", "key_risks", "risk")):
                if report.get(key):
                    md += ["", f"**{title}**"] + [f"- {i.get(field)}" for i in report[key] if isinstance(i, dict)]
            if report.get("disclaimer"):
                md += ["", f"*{report['disclaimer']}*"]
            md.append("")
        for key, dim in (report.get("score_breakdown", {}).get("dimensions") or {}).items():
            md.append(f"- **{dim['label']}: {dim['score'] if dim['score'] is not None else 'n/a'}/100** - {dim['explanation']}")
        md += ["", "## 2. Market Research",
               market.get("market_summary") or market.get("_error") or "Not available.", ""]
        for f in market.get("verified_figures", []):
            md.append(f"- Sourced figure: **{f['value_text']}** ({f.get('note', '')}) - [{f['source_title'] or f['url']}]({f['url']})")
        md.append(f"- Growth (CAGR): {market.get('cagr', 'Insufficient data')} - {market.get('cagr_info', {}).get('explanation', '')}")
        sizing = market.get("sizing", {})
        if sizing.get("status") in ("calculated", "partial"):
            md += ["", f"### Market sizing ({sizing.get('approach_label', '')}; {sizing.get('currency', '')}; {sizing.get('timeframe', '')})"]
            md += [f"- {v}" for v in sizing["formula"].values()] + [f"- {m}" for m in (sizing.get("missing") or {}).values()]
            if sizing.get("tam_source"):
                md.append(f"- TAM source: [{sizing['tam_source'].get('title') or 'source'}]({sizing['tam_source'].get('url')})")
            md += [f"- Assumption - {a['label']}: {a['display']['value']} ({item_text(a.get('basis'))})" for a in sizing["assumptions"]]
        else:
            md.append(f"- Market sizing: {sizing.get('reason', 'Insufficient data')}")
        md += ["", "## 3. Competitors (websites verified)"]
        for c in competitors:
            md.append(f"- **{c.get('name')}** ({c.get('competitor_type')}) {c.get('website_url')} - pricing: {c.get('pricing_model')} - strengths (from site): {c.get('strengths')} - weaknesses (AI): {c.get('weaknesses')} - how you differ: {c.get('market_gap')}")
        if not competitors:
            md.append("- No competitor could be verified.")
        md += ["", "## 4. SWOT"]
        for q in ("strengths", "weaknesses", "opportunities", "threats"):
            md.append(f"**{q.title()}**")
            md += [f"- {item_text(i)}" for i in swot.get(q, [])]
        md += ["", "## 5. Risks"]
        for r in swot_risk.get("risks", []):
            md.append(f"- [{r.get('severity')}] {item_text(r)} -> {r.get('realistic_solution', '')}")
        md += ["", "## 6. MVP"]
        md += [f"- Must-have: {item_text(f, 'feature')}" for f in mvp.get("must_have", [])]
        md += [f"- Should-have: {item_text(f, 'feature')}" for f in mvp.get("should_have", [])]
        md += ["", "## 7. Go-to-market and 30/60/90-day plan", gtm.get("positioning_statement", "")]
        for ph in gtm.get("launch_roadmap_90_days", []):
            md.append(f"**{ph.get('phase')}** - {ph.get('goal', '')} (success: {ph.get('success_metric', '')})")
            md += [f"  - {a}" for a in ph.get("actions", [])]
        md += ["", "## 8. Sources"]
        for src in (report.get("research_summary", {}).get("sources") or []):
            md.append(f"- [{src['id']}] [{src['title']}]({src['url']})")
        return Response("\n".join(md), mimetype="text/markdown",
                        headers={"Content-Disposition": f"attachment;filename=Validation_Report_{idea_id}.md"})

    @app.route("/api/export/<int:idea_id>/csv")
    @login_required
    def export_csv(idea_id):
        idea = StartupIdea.get_by_id(idea_id, current_user.id)
        if not idea:
            abort(404)
        analyses, ex, market, comp, swot_risk, mvp, gtm, report = _bundle(idea_id)
        competitors = Competitor.get_by_idea(idea_id)
        verdict = StartupIdea.get_final_verdict(idea_id) or {}
        swot = swot_risk.get("swot", {})

        output = io.StringIO()
        w = csv.writer(output)
        w.writerow(["=== STARTUP IDEA VALIDATION REPORT ==="])
        w.writerow(["Title", idea.get("title", "")])
        w.writerow(["Industry", idea.get("industry", "")])
        w.writerow(["Viability Score", f"{verdict.get('viability_score')}/100" if verdict.get("viability_score") is not None else "n/a"])
        w.writerow(["Recommendation", RECOMMENDATION_LABELS.get(str(verdict.get("recommendation", "N/A")).upper(), verdict.get("recommendation", "N/A"))])
        w.writerow(["Confidence", verdict.get("confidence") or "n/a"])
        w.writerow(["Biggest Strength", verdict.get("biggest_strength") or ""])
        w.writerow(["Biggest Weakness", verdict.get("biggest_weakness") or ""])
        w.writerow([])
        w.writerow(["=== MARKET (sourced figures vs AI estimates) ==="])
        for f in market.get("verified_figures", []):
            w.writerow(["Sourced market figure", f["value_text"], f.get("note", ""), f["url"]])
        w.writerow(["CAGR", market.get("cagr", "Insufficient data"), market.get("cagr_info", {}).get("explanation", "")])
        for k in ("tam", "sam", "som"):
            w.writerow([k.upper() + " (AI-calculated)", market.get(k, "Insufficient data")])
        w.writerow([])
        w.writerow(["=== COMPETITORS (websites verified) ==="])
        w.writerow(["Name", "Type", "Website", "Pricing found", "Key features", "Gap vs idea"])
        for c in competitors:
            feats = c.get("key_features") or c.get("features") or ""
            w.writerow([c.get("name"), c.get("competitor_type"), c.get("website_url"), c.get("pricing_model"),
                        "; ".join(feats) if isinstance(feats, list) else feats, c.get("weaknesses")])
        w.writerow([])
        w.writerow(["=== 30/60/90-DAY PLAN ==="])
        w.writerow(["Phase", "Goal", "Actions", "Success metric"])
        for ph in gtm.get("launch_roadmap_90_days", []):
            w.writerow([ph.get("phase"), ph.get("goal"), "; ".join(ph.get("actions", [])), ph.get("success_metric")])
        w.writerow([])
        w.writerow(["=== SWOT ==="])
        for q in ("strengths", "weaknesses", "opportunities", "threats"):
            w.writerow([q.title(), " | ".join(item_text(i) for i in swot.get(q, []))])
        w.writerow([])
        w.writerow(["=== RISKS ==="])
        w.writerow(["Category", "Risk", "Severity", "Realistic solution"])
        for r in swot_risk.get("risks", []):
            w.writerow([r.get("category"), item_text(r, "risk"), r.get("severity"), r.get("realistic_solution")])

        safe_title = "".join(c for c in idea.get("title", "startup") if c.isalnum() or c in (" ", "_", "-")).strip()
        return Response(output.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment;filename=Validation_{safe_title}_{idea_id}.csv"})

    @app.route("/api/ideas/compare")
    @login_required
    def api_compare_ideas():
        id1 = request.args.get("id1", type=int)
        id2 = request.args.get("id2", type=int)
        if not id1 or not id2:
            return jsonify({"status": "error", "message": "Both id1 and id2 are required"}), 400

        idea1 = StartupIdea.get_by_id(id1, current_user.id)
        idea2 = StartupIdea.get_by_id(id2, current_user.id)
        if not idea1 or not idea2:
            return jsonify({"status": "error", "message": "One or both ideas not found"}), 404

        v1 = StartupIdea.get_final_verdict(id1)
        v2 = StartupIdea.get_final_verdict(id2)
        analyses1 = AnalysisResult.get_all_for_idea(id1)
        analyses2 = AnalysisResult.get_all_for_idea(id2)
        comps1 = Competitor.get_by_idea(id1)
        comps2 = Competitor.get_by_idea(id2)

        return jsonify({
            "status": "success",
            "idea1": {
                "id": idea1["id"],
                "title": idea1["title"],
                "industry": idea1.get("industry"),
                "created_at": str(idea1.get("created_at")),
                "verdict": v1,
                "competitor_count": len(comps1),
                "tam": analyses1.get("market", {}).get("data", {}).get("tam", "N/A"),
                "cagr": analyses1.get("market", {}).get("data", {}).get("cagr", "N/A"),
                "strengths": [item_text(i) for i in analyses1.get("swot_risk", {}).get("data", {}).get("swot", {}).get("strengths", [])[:3]],
                "risks": [item_text(r, "risk") for r in analyses1.get("swot_risk", {}).get("data", {}).get("risks", [])[:3]]
            },
            "idea2": {
                "id": idea2["id"],
                "title": idea2["title"],
                "industry": idea2.get("industry"),
                "created_at": str(idea2.get("created_at")),
                "verdict": v2,
                "competitor_count": len(comps2),
                "tam": analyses2.get("market", {}).get("data", {}).get("tam", "N/A"),
                "cagr": analyses2.get("market", {}).get("data", {}).get("cagr", "N/A"),
                "strengths": [item_text(i) for i in analyses2.get("swot_risk", {}).get("data", {}).get("swot", {}).get("strengths", [])[:3]],
                "risks": [item_text(r, "risk") for r in analyses2.get("swot_risk", {}).get("data", {}).get("risks", [])[:3]]
            }
        })

    @app.route("/api/settings/test-groq")
    @login_required
    def api_test_groq():
        service = GroqService()
        success, message = service.test_connection()
        return jsonify({"success": success, "message": message})

    @app.route("/api/settings/test-tavily")
    @login_required
    def api_test_tavily():
        service = SearchService()
        success, message = service.test_connection()
        return jsonify({"success": success, "message": message})

    SAMPLE_IDEAS = [
        dict(title="LexiDraft AI — Freelancer Contract Copilot",
             raw_description=("An AI assistant for freelance software developers and independent designers that reviews client "
                              "master service agreements, highlights unfair indemnification clauses, and generates polite "
                              "counter-proposal emails to protect payment terms."),
             industry="LegalTech / Productivity SaaS",
             target_audience="Freelance developers, independent designers, boutique digital agencies",
             problem_statement="Freelancers sign one-sided contracts because a contract lawyer costs hundreds of dollars per hour.",
             proposed_solution="A contract redlining copilot that explains clauses in plain English, flags liabilities and drafts counter-edits.",
             revenue_model="Freemium with a monthly Pro subscription"),
        dict(title="CarbonTrace — Automated Scope 3 Carbon Accounting",
             raw_description=("Lightweight carbon accounting software for mid-market manufacturing suppliers that ingests utility "
                              "bills, ERP supplier receipts and logistics manifests to produce emissions reports for enterprise buyers."),
             industry="ClimateTech / Enterprise ESG",
             target_audience="Mid-market manufacturers and Tier-1 supply chain contractors",
             problem_statement="Suppliers are asked by large customers to disclose Scope 3 emissions but cannot afford consulting audits.",
             proposed_solution="Connects to accounting/ERP data and fleet fuel records to produce GHG-Protocol footprints within days.",
             revenue_model="Tiered B2B SaaS subscription"),
    ]

    @app.route("/api/sample/load", methods=["POST"])
    @login_required
    def api_load_sample_data():
        """Creates two SAMPLE IDEAS (inputs only) and analyses them with the real research pipeline."""
        if not GroqService().is_available():
            flash("Sample ideas are analysed with the live research pipeline, which needs a Groq API key. "
                  "Add GROQ_API_KEY to .env or Settings first.", "warning")
            return redirect(url_for("view_settings"))
        for sample in SAMPLE_IDEAS:
            idea_id = StartupIdea.create(user_id=current_user.id, is_sample=True, **sample)
            OrchestrationPipeline(idea_id=idea_id, user_id=current_user.id).run_async()
        flash("Two sample ideas were submitted and are being researched now (about 2-4 minutes each).", "success")
        return redirect(url_for("view_history"))

    return app

if __name__ == "__main__":
    application = create_app()
    application.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
