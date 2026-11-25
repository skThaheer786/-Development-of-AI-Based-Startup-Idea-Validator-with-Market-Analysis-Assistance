import time
import logging

from config import Config

from services.groq_service import GroqService, LLMError
from services.search_service import SearchService
from services import quality

logger = logging.getLogger(__name__)

RULES = """
GROUND RULES (apply to every field you write):
1. Be specific to THIS startup idea: name its actual users, features, regions, numbers, competitors or regulations.
2. Never write boilerplate such as "AI-native", "frictionless", "10x faster", "bloated legacy tools", "manual overhead",
   "early brand recognition" or "customer inertia" unless you tie it to a concrete fact about this idea.
3. Use ONLY numbers that appear in the provided evidence for anything marked as sourced. If a number is not in the
   evidence, label it an assumption and explain the reasoning (market-sizing inputs are always estimated this way); for facts such as
   company details or prices return null. Never invent statistics, company names, prices, URLs or quotes.
4. Cite evidence with the ids shown in brackets, e.g. ["S3"]. Only cite an id if that source actually supports the point.
5. Every score or rating needs a reason that explains it using details of this idea.
6. Return ONLY one valid JSON object (no markdown fences, no commentary).
""".strip()


class AgentFailure(Exception):
    """An agent could not produce trustworthy output."""


class BaseAgent:
    """Base class for all startup validator AI agents (live LLM only, no fabricated fallbacks)."""

    # list of dotted JSON paths whose items must pass the generic-text guard
    GUARD_PATHS = []

    def __init__(self, name, description, groq_service=None, search_service=None, book=None):
        self.name = name
        self.description = description
        self.groq_service = groq_service or GroqService()
        self.search_service = search_service or SearchService()
        self.book = book
        self.quality_notes = []
        self.warnings = []

    # ------------------------------------------------------------------
    def run(self, context):
        """Runs the agent. Always returns a dict. On failure the dict contains `_error` (never fake data)."""
        start = time.time()
        logger.info("Starting agent: %s", self.name)
        meta = {"agent_name": self.name}
        try:
            if not self.groq_service.is_available():
                raise LLMError("no_key")
            result = self._execute_llm(context)
            if not isinstance(result, dict):
                raise AgentFailure("agent returned no data")
            status = "partial" if self.warnings else "ok"
            meta.update({"status": status, "warnings": self.warnings, "quality_notes": self.quality_notes,
                         "source": f"Groq {self.groq_service.last_model_used or self.groq_service.model}"})
        except LLMError as exc:
            logger.error("Agent %s failed (LLM): %s", self.name, exc.kind)
            result = {"_error": exc.user_message, "_error_kind": exc.kind}
            meta.update({"status": "failed", "source": "unavailable"})
        except AgentFailure as exc:
            logger.error("Agent %s failed: %s", self.name, exc)
            result = {"_error": str(exc), "_error_kind": "agent"}
            meta.update({"status": "failed", "source": "unavailable"})
        except Exception as exc:  # defensive: never let one agent crash the pipeline
            logger.exception("Agent %s crashed", self.name)
            result = {"_error": f"Unexpected error in {self.name}: {type(exc).__name__}: {str(exc)[:120]}",
                      "_error_kind": "crash"}
            meta.update({"status": "failed", "source": "unavailable"})

        meta["execution_time_sec"] = round(time.time() - start, 2)
        meta["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
        result["_meta"] = meta
        return result

    def _execute_llm(self, context):
        raise NotImplementedError

    # ------------------------------------------------------------------
    def llm_json(self, system_prompt, user_prompt, max_tokens=4000, temperature=0.3,
                 required_keys=None, anchors=None, fast=False):
        """
        One JSON completion with (a) required-key validation and (b) one corrective retry when the
        answer contains generic boilerplate. Raises LLMError / AgentFailure if unusable.
        """
        system = f"{system_prompt}\n\n{RULES}"
        if Config.QUICK_MODE:
            fast = True
            user_prompt += ("\n\nQUICK MODE: keep every list to at most 3 items and every text field to one short, specific sentence. "
                            "Stay specific to this idea.")
        feedback = ""
        data = None
        for attempt in range(2):
            messages = [{"role": "system", "content": system},
                        {"role": "user", "content": user_prompt + feedback}]
            data = self.groq_service.chat_completion(messages, temperature=temperature,
                                                     max_tokens=max_tokens, json_mode=True, fast=fast)
            if not isinstance(data, dict):
                raise AgentFailure("model returned a non-object answer")

            missing = [k for k in (required_keys or []) if not data.get(k)]
            flagged = []
            if self.GUARD_PATHS and anchors:
                flagged = quality.audit_paths(data, self.GUARD_PATHS, anchors)
            total = max(1, quality.total_items(data, self.GUARD_PATHS))
            too_generic = len(flagged) > max(1, int(0.25 * total))

            if (missing or too_generic) and attempt == 0:
                parts = []
                if missing:
                    parts.append("Your previous answer was missing required keys: " + ", ".join(missing) + ".")
                if too_generic:
                    examples = "; ".join(f'"{t[:90]}" ({r})' for _, _, t, r in flagged[:4])
                    parts.append("Your previous answer contained generic statements that could apply to any startup, e.g. "
                                 + examples + ". Rewrite EVERYTHING so each item names a concrete detail of this idea.")
                feedback = "\n\nCORRECTION NEEDED: " + " ".join(parts)
                continue

            if missing:
                raise AgentFailure("model answer was missing: " + ", ".join(missing))
            if flagged:
                removed = quality.strip_flagged(data, flagged)
                self.quality_notes.append(
                    f"{len(flagged)} generic statement(s) detected after retry; {removed} removed, "
                    f"{len(flagged) - removed} kept (list too short to drop).")
            return data
        raise AgentFailure("model answer could not be validated")

    # ------------------------------------------------------------------
    @staticmethod
    def idea_brief(context):
        """Compact description of the idea used inside prompts."""
        ex = context.get("extractor_data", {}) or {}
        lines = [
            f"Title: {context.get('title', '')}",
            f"Founder's description: {(context.get('raw_description') or '')[:1500]}",
            f"Business concept: {ex.get('business_concept', '')}",
            f"Problem: {ex.get('problem_statement', '')}",
            f"Solution: {ex.get('proposed_solution', '')}",
            f"Target audience: {ex.get('target_audience', '')}",
            f"Industry: {ex.get('industry', '')} | Market category: {ex.get('market_category', '')}",
            f"Customer type: {ex.get('customer_type', '')} | Geography: {ex.get('geography', '')}",
            f"Revenue model (founder's): {ex.get('revenue_model', '')}",
            f"Value proposition: {ex.get('unique_value_proposition', '')}",
        ]
        return "\n".join(lines)

    @staticmethod
    def anchors_for(context, extra=None):
        ex = context.get("extractor_data", {}) or {}
        return quality.build_anchors(
            context.get("title", ""), context.get("raw_description", ""), ex.get("proposed_solution", ""),
            ex.get("target_audience", ""), ex.get("problem_statement", ""), ex.get("market_category", ""),
            ex.get("key_terms", []), ex.get("geography", ""), extra_terms=extra or [])

    def add_sources(self, results):
        """Store results in the shared evidence book (returns stored items with ids)."""
        if self.book is None:
            from services.evidence import EvidenceBook
            self.book = EvidenceBook()
        return self.book.add(results)
