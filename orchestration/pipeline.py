import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from config import Config
from database.models import StartupIdea, AnalysisResult, Competitor, ValidationReport
from database.db import get_db
from agents.idea_extractor import IdeaExtractionAgent
from agents.market_analyzer import MarketAnalyzerAgent
from agents.competitor_agent import CompetitorAnalysisAgent
from agents.swot_risk_agent import SWOTRiskAgent
from agents.mvp_recommender import MVPRecommenderAgent
from agents.gtm_strategist import GTMStrategistAgent
from agents.startup_advisor import StartupAdvisorAgent
from agents.report_generator import ReportGeneratorAgent
from services.groq_service import GroqService
from services.search_service import SearchService
from services.evidence import EvidenceBook
from .context_store import ContextStore

logger = logging.getLogger(__name__)

# Global in-memory dictionary for real-time progress monitoring
_ACTIVE_PIPELINES = {}
_LOCK = threading.Lock()


class OrchestrationPipeline:
    """Runs the 8-agent validation pipeline. Failed agents are reported honestly; nothing is fabricated."""

    AGENTS_METADATA = [
        {"id": "extractor", "name": "Idea Extractor", "icon": "bi-lightbulb-fill", "desc": "Structuring the idea and planning idea-specific research..."},
        {"id": "market", "name": "Market Analyzer", "icon": "bi-pie-chart-fill", "desc": "Searching the web for market data, trends and sizing..."},
        {"id": "competitors", "name": "Competitor Agent", "icon": "bi-binoculars-fill", "desc": "Finding and verifying real competitors..."},
        {"id": "swot_risk", "name": "SWOT & Risk Agent", "icon": "bi-shield-shaded", "desc": "Building idea-specific SWOT and scored risks..."},
        {"id": "mvp", "name": "MVP Recommender", "icon": "bi-layers-fill", "desc": "Prioritising MVP features and a realistic roadmap..."},
        {"id": "gtm", "name": "Go-to-Market Strategist", "icon": "bi-graph-up-arrow", "desc": "Pricing, first customers and the 30/60/90-day plan..."},
        {"id": "advisor", "name": "Startup Advisor", "icon": "bi-chat-square-dots-fill", "desc": "Writing the advisory brief..."},
        {"id": "report", "name": "Report Generator", "icon": "bi-file-earmark-pdf-fill", "desc": "Computing explainable scores and compiling the report..."},
    ]
    # (agent id, context key, class, percent when finished)
    STEPS = [
        ("extractor", "extractor_data", IdeaExtractionAgent, 14),
        ("market", "market_data", MarketAnalyzerAgent, 32),
        ("competitors", "competitor_data", CompetitorAnalysisAgent, 50),
        ("swot_risk", "swot_data", SWOTRiskAgent, 64),
        ("mvp", "mvp_data", MVPRecommenderAgent, 76),
        ("gtm", "gtm_data", GTMStrategistAgent, 88),
        ("advisor", "advisor_data", StartupAdvisorAgent, 94),
    ]

    FATAL_KINDS = ("auth", "no_key", "bad_key", "daily_limit")
    RETRYABLE_KINDS = ("rate_limit", "too_large", "server", "timeout", "network", "invalid_json", "empty", "agent")

    def __init__(self, idea_id, user_id=None, groq_service=None, search_service=None):
        self.idea_id = idea_id
        self.user_id = user_id
        self.context_store = ContextStore()
        self.groq = groq_service
        self.search = search_service

    # ------------------------------------------------------------------
    @classmethod
    def is_running(cls, idea_id):
        with _LOCK:
            return _ACTIVE_PIPELINES.get(idea_id, {}).get("status") == "processing"

    @classmethod
    def recover_interrupted(cls):
        """Ideas left in 'analyzing' by a server restart can never finish; mark them failed."""
        with get_db() as conn:
            rows = conn.execute("SELECT id FROM startup_ideas WHERE status = 'analyzing'").fetchall()
            for r in rows:
                conn.execute("UPDATE startup_ideas SET status = 'failed' WHERE id = ?", (r["id"],))
                conn.execute("""INSERT INTO analysis_results (idea_id, agent_name, result_json, status)
                                VALUES (?, 'pipeline', ?, 'failed')
                                ON CONFLICT(idea_id, agent_name) DO UPDATE SET result_json = excluded.result_json,
                                status = 'failed'""",
                             (r["id"], '{"_error": "The analysis was interrupted (server restarted). Please re-run it."}'))
        return len(rows)

    @classmethod
    def _idle_agents(cls, status="pending"):
        return {m["id"]: {"id": m["id"], "name": m["name"], "status": status, "time": 0.0, "icon": m["icon"]}
                for m in cls.AGENTS_METADATA}

    @classmethod
    def get_progress(cls, idea_id):
        """Live progress if running, otherwise reconstructed from the database."""
        with _LOCK:
            if idea_id in _ACTIVE_PIPELINES:
                return dict(_ACTIVE_PIPELINES[idea_id])

        idea = StartupIdea.get_by_id(idea_id)
        if not idea:
            return {"percent": 0, "current_step": "idle", "message": "Ready to validate", "status": "idle",
                    "agents": cls._idle_agents()}

        saved = AnalysisResult.get_all_for_idea(idea_id)
        is_completed, is_failed = idea.get("status") == "completed", idea.get("status") == "failed"
        agents, done = {}, 0
        for m in cls.AGENTS_METADATA:
            rec = saved.get(m["id"])
            if rec:
                st = "failed" if rec.get("status") == "failed" else "completed"
                done += 1
                agents[m["id"]] = {"id": m["id"], "name": m["name"], "icon": m["icon"], "status": st,
                                   "time": round(rec.get("execution_time_sec") or 0.0, 2),
                                   "message": "Failed" if st == "failed" else "Analysis completed"}
            else:
                agents[m["id"]] = {"id": m["id"], "name": m["name"], "icon": m["icon"],
                                   "status": "failed" if is_failed else "pending", "time": 0.0,
                                   "message": "Not run" if is_failed else "Pending analysis"}
        percent = 100 if is_completed else int(round(done / len(cls.AGENTS_METADATA) * 100))
        pipe_err = (saved.get("pipeline", {}).get("data", {}) or {}).get("_error")
        return {
            "percent": percent,
            "current_step": "completed" if is_completed else ("error" if is_failed else "idle"),
            "message": ("Validation complete." if is_completed else (pipe_err or "Analysis failed.") if is_failed
                        else f"{done}/8 agents completed"),
            "status": "completed" if is_completed else ("failed" if is_failed else "idle"),
            "agents": agents, "viability_score": idea.get("viability_score"),
            "recommendation": idea.get("recommendation"),
        }

    def _init_state(self):
        with _LOCK:
            _ACTIVE_PIPELINES[self.idea_id] = {
                "percent": 3, "current_step": "init", "message": "Initializing validation pipeline...",
                "status": "processing", "agents": self._idle_agents()}

    def _progress(self, agent_id, status, percent, message=None, elapsed=0.0):
        with _LOCK:
            p = _ACTIVE_PIPELINES.get(self.idea_id)
            if not p:
                return
            p["percent"], p["current_step"] = percent, agent_id
            if message:
                p["message"] = message
            if agent_id in p["agents"]:
                p["agents"][agent_id]["status"] = status
                if elapsed:
                    p["agents"][agent_id]["time"] = elapsed
                if message:
                    p["agents"][agent_id]["message"] = message

    def _finish(self, **fields):
        with _LOCK:
            if self.idea_id in _ACTIVE_PIPELINES:
                _ACTIVE_PIPELINES[self.idea_id].update(fields)

    def _fail(self, message):
        logger.error("Pipeline %s failed: %s", self.idea_id, message)
        AnalysisResult.save_or_update(self.idea_id, "pipeline", {"_error": message}, status="failed")
        StartupIdea.update_status(self.idea_id, "failed")
        self._finish(percent=100, current_step="error", message=message, status="failed")
        return {"status": "failed", "idea_id": self.idea_id, "error": message}

    # ------------------------------------------------------------------
    def run_synchronous(self):
        idea = StartupIdea.get_by_id(self.idea_id)
        if not idea:
            raise ValueError(f"Startup idea ID {self.idea_id} not found.")

        self._init_state()
        groq = self.groq or GroqService()
        if not groq.is_available():
            return self._fail("No Groq API key is configured. Add GROQ_API_KEY to your .env file (or in Settings) and re-run.")

        StartupIdea.update_status(self.idea_id, "analyzing")
        # clear results of a previous run so old data can never leak into the new report
        with get_db() as conn:
            conn.execute("DELETE FROM analysis_results WHERE idea_id = ?", (self.idea_id,))
            conn.execute("DELETE FROM competitors WHERE idea_id = ?", (self.idea_id,))

        search = self.search or SearchService()
        book = EvidenceBook()
        self.context_store.update({
            "idea_id": self.idea_id, "user_id": idea.get("user_id"), "title": idea.get("title"),
            "raw_description": idea.get("raw_description"), "industry": idea.get("industry"),
            "target_audience": idea.get("target_audience"), "problem_statement": idea.get("problem_statement"),
            "proposed_solution": idea.get("proposed_solution"), "revenue_model": idea.get("revenue_model"),
        })
        analysis = {}
        meta_by_id = {m["id"]: m for m in self.AGENTS_METADATA}
        step_info = {a: (ck, cls_) for a, ck, cls_, _ in self.STEPS}
        # Independent agents run at the same time (much faster than one after another)
        stages = [(["extractor"], 14), (["market", "competitors"], 45), (["swot_risk", "mvp", "gtm"], 80)]

        def run_one(agent_id, ctx):
            t0 = time.time()
            agent = step_info[agent_id][1](groq_service=groq, search_service=search, book=book)
            res = agent.run(ctx)
            return agent_id, res, round(time.time() - t0, 2)

        def record(agent_id, res, elapsed):
            """Main-thread bookkeeping (DB writes, progress); returns True when the agent failed."""
            meta = meta_by_id[agent_id]
            failed = "_error" in res
            logger.info("[idea %s] %s finished in %.0fs%s", self.idea_id, meta["name"], elapsed,
                        f" - FAILED: {res['_error'][:100]}" if failed else "")
            self.context_store.set(step_info[agent_id][0], res)
            analysis[agent_id] = {"data": res}
            AnalysisResult.save_or_update(self.idea_id, agent_id, res, status="failed" if failed else "completed",
                                          execution_time_sec=elapsed)
            if agent_id == "extractor" and not failed:
                StartupIdea.update_extracted_data(
                    self.idea_id, industry=res.get("industry"), target_audience=res.get("target_audience"),
                    problem_statement=res.get("problem_statement"), proposed_solution=res.get("proposed_solution"),
                    revenue_model=res.get("revenue_model"))
            if agent_id == "competitors" and not failed:
                Competitor.save_batch(self.idea_id, res.get("competitors", []))
            return failed

        try:
            for stage, pct_done in stages:
                ctx = self.context_store.to_dict() if stage == ["extractor"] else self.context_store.get_summary_context()
                for aid in stage:
                    self._progress(aid, "processing", max(pct_done - 10, 4), f"{meta_by_id[aid]['name']}: {meta_by_id[aid]['desc']}")
                with ThreadPoolExecutor(max_workers=len(stage)) as pool:
                    outputs = list(pool.map(lambda a: run_one(a, ctx), stage))
                for aid, res, elapsed in outputs:
                    failed = record(aid, res, elapsed)
                    self._progress(aid, "failed" if failed else "completed", pct_done,
                                   (res["_error"][:140] if failed else f"{meta_by_id[aid]['name']} completed"), elapsed=elapsed)
                    if aid == "extractor" and failed:
                        return self._fail("Could not analyse the idea: " + res["_error"])
                    if failed and res.get("_error_kind") in self.FATAL_KINDS:
                        return self._fail(res["_error"])

                # An agent that failed for a transient reason (rate limit, timeout, bad JSON...) gets one automatic retry,
                # one at a time, instead of leaving a hole in the report that the user has to re-run by hand.
                again = [a for a, r, _ in outputs if "_error" in r and r.get("_error_kind") in self.RETRYABLE_KINDS]
                if again:
                    rate_limited = any(r.get("_error_kind") in ("rate_limit", "too_large") for a, r, _ in outputs if a in again)
                    time.sleep(Config.AGENT_RETRY_PAUSE if rate_limited else min(3, Config.AGENT_RETRY_PAUSE))
                    for aid in again:
                        self._progress(aid, "processing", max(pct_done - 4, 4), f"{meta_by_id[aid]['name']}: retrying automatically...")
                        aid, res, elapsed = run_one(aid, ctx)
                        failed = record(aid, res, elapsed)
                        self._progress(aid, "failed" if failed else "completed", pct_done,
                                       (res["_error"][:140] if failed else f"{meta_by_id[aid]['name']} completed (after a retry)"), elapsed=elapsed)
                        if failed and res.get("_error_kind") in self.FATAL_KINDS:
                            return self._fail(res["_error"])

            # ---------------- Advisor + Report (in parallel) ----------------
            self._progress("advisor", "processing", 85, "Writing the advisory brief...")
            self._progress("report", "processing", 88, "Computing explainable scores...")
            ctx = self.context_store.get_summary_context()
            report_agent = ReportGeneratorAgent(groq_service=groq, search_service=search, book=book)
            t_report = time.time()

            quick = Config.QUICK_MODE

            def run_advisor():
                if quick:   # Quick mode skips the optional advisory brief
                    return "advisor", {"skipped": True, "note": "Skipped in Quick mode."}, 0.0
                return run_one("advisor", ctx)

            def run_report():
                return report_agent.run({"idea": StartupIdea.get_by_id(self.idea_id), "analysis_dict": dict(analysis)})

            with ThreadPoolExecutor(max_workers=2) as pool:
                f_adv = pool.submit(run_advisor)
                f_rep = pool.submit(run_report)
                aid, adv_res, adv_elapsed = f_adv.result()
                report_res = f_rep.result()
            failed = record("advisor", adv_res, adv_elapsed)
            self._progress("advisor", "failed" if failed else "completed", 94,
                           (adv_res["_error"][:140] if failed else "Startup Advisor completed"), elapsed=adv_elapsed)
            elapsed = round(time.time() - t_report, 2)
            report_res["all_sources"] = book.public()
            report_res["research_summary"] = {"sources": book.public(), "search": search.summary()}
            report_res["search_summary"] = search.summary()
            report_res["groq_usage"] = groq.usage
            analysis["report"] = {"data": report_res}
            AnalysisResult.save_or_update(self.idea_id, "report", report_res,
                                          status="failed" if "_error" in report_res else "completed",
                                          execution_time_sec=elapsed)
            if "_error" in report_res or not report_res.get("score_available"):
                self._progress("report", "failed", 100, "Report could not be scored", elapsed=elapsed)
                return self._fail(report_res.get("_error") or
                                  "Too many analysis steps failed to compute an overall score. Re-run the analysis.")

            pdf_filename = None
            try:
                pdf_filename = report_agent.generate_pdf_document(
                    idea=StartupIdea.get_by_id(self.idea_id), analysis_dict=analysis,
                    competitors=Competitor.get_by_idea(self.idea_id), report_data=report_res)
            except Exception as exc:  # the PDF must never break the report itself
                logger.exception("PDF generation failed")
                report_res.setdefault("_meta", {}).setdefault("warnings", []).append(f"PDF generation failed: {type(exc).__name__}")
                AnalysisResult.save_or_update(self.idea_id, "report", report_res, execution_time_sec=elapsed)

            ValidationReport.save_report(
                idea_id=self.idea_id, user_id=idea.get("user_id"), summary_text=report_res.get("executive_summary"),
                viability_score=report_res["viability_score"], market_score=report_res.get("market_score") or 0,
                competition_score=report_res.get("competition_score") or 0,
                execution_score=report_res.get("execution_score") or 0,
                risk_score=report_res.get("risk_score") or 0, pdf_filename=pdf_filename, full_report_data=report_res)
            StartupIdea.update_status(self.idea_id, "completed", viability_score=report_res["viability_score"],
                                      recommendation=report_res["recommendation"])
            self._progress("report", "completed", 100, "Report completed", elapsed=elapsed)
            self._finish(percent=100, current_step="completed", status="completed", pdf_filename=pdf_filename,
                         message=f"Validation complete! Verdict: {report_res['recommendation']}",
                         viability_score=report_res["viability_score"], recommendation=report_res["recommendation"])
            return {"status": "completed", "idea_id": self.idea_id, "viability_score": report_res["viability_score"],
                    "recommendation": report_res["recommendation"], "pdf_filename": pdf_filename}

        except Exception as exc:  # unexpected programming/DB error
            logger.exception("Pipeline crashed for idea %s", self.idea_id)
            return self._fail(f"Unexpected pipeline error: {type(exc).__name__}: {str(exc)[:140]}")

    def run_async(self):
        """Run in a background thread; the progress API polls _ACTIVE_PIPELINES."""
        self._init_state()
        thread = threading.Thread(target=self.run_synchronous, daemon=True)
        thread.start()
        return thread
