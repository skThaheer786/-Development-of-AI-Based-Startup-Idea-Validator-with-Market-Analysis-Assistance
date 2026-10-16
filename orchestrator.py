"""
orchestrator.py  --  Task 4: Multi-Agent Orchestration (Milestone 1)

Flow:
    User idea (form) -> Extraction Agent (Groq LLM) -> Market Research Agent (Tavily)
                     -> [future agents] -> combined result

All steps read from / write to one shared `state` dict, so data is passed
between components in a single, predictable place.
"""

import json
import logging
from datetime import datetime

from structured_extraction import extract_startup_idea, IdeaExtractionError  # Task 2
from market_research import search_market                                    # Task 3

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("orchestrator")


# ---------------------------------------------------------------------------
# Agent registry: responsibility of each agent
# ---------------------------------------------------------------------------
AGENTS = {
    "extraction_agent": "Uses the Groq LLM to turn the raw idea into structured JSON "
                        "(problem, solution, customers, industry, key features).",
    "market_research_agent": "Generates search queries and fetches live market and "
                             "competitor data via Tavily.",
    "competitor_agent": "(Milestone 2) Identifies and compares competitors.",
    "risk_agent": "(Milestone 2) Analyses strengths, weaknesses and risks.",
    "feature_agent": "(Milestone 2) Recommends first features / MVP scope.",
    "report_agent": "(Milestone 3) Generates the final validation report.",
}


def _get_idea_text(raw_idea: dict) -> str:
    """The form field may be called 'idea_description' or 'idea'."""
    return str(raw_idea.get("idea_description") or raw_idea.get("idea") or "").strip()


def _validate_input(raw_idea: dict) -> None:
    if not isinstance(raw_idea, dict):
        raise ValueError("Input must be a dictionary of form fields.")
    if not _get_idea_text(raw_idea):
        raise ValueError("Startup idea description cannot be empty.")


# ---------------------------------------------------------------------------
# Main orchestration function
# ---------------------------------------------------------------------------
def run_workflow(raw_idea: dict) -> dict:
    """
    Run the Milestone 1 workflow and return the shared state:

    {
        "raw_idea": {...},          # from the UI form
        "structured_idea": {...},   # from Extraction Agent
        "market_research": {...},   # from Market Research Agent
        "errors": [...],
        "status": "success" | "partial" | "failed",
    }
    """
    state = {
        "raw_idea": raw_idea,
        "structured_idea": None,
        "market_research": None,
        "errors": [],
        "status": "failed",
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }

    # Step 0: validate input
    try:
        _validate_input(raw_idea)
    except ValueError as e:
        state["errors"].append({"step": "validation", "error": str(e)})
        return state

    # Step 1: Extraction Agent (LLM)
    try:
        log.info("Step 1: Extraction Agent running")
        state["structured_idea"] = extract_startup_idea(raw_idea)
    except IdeaExtractionError as e:   # API errors, bad JSON, missing key
        log.error("Extraction failed: %s", e)
        state["errors"].append({"step": "extraction", "error": str(e)})
        return state                    # later steps need the structured idea
    except Exception as e:
        log.error("Unexpected extraction error: %s", e)
        state["errors"].append({"step": "extraction", "error": str(e)})
        return state

    # Step 2: Market Research Agent (web search)
    structured = state["structured_idea"]
    try:
        log.info("Step 2: Market Research Agent running")
        research = search_market(
            _get_idea_text(raw_idea),                                   # short, search-friendly text
            structured.get("industry") or raw_idea.get("industry", "Unknown"),
            structured.get("target_customers") or raw_idea.get("target_customers", "General customers"),
        )
        state["market_research"] = research
        if research.get("results"):
            state["status"] = "success"
        else:
            state["status"] = "partial"
            state["errors"].append({"step": "market_research",
                                    "error": "No search results returned."})
    except Exception as e:
        log.error("Market research failed: %s", e)
        state["errors"].append({"step": "market_research", "error": str(e)})
        state["status"] = "partial"     # structured idea is still available

    # Future: competitor_agent, risk_agent, feature_agent, report_agent
    return state


if __name__ == "__main__":
    sample = {
        "idea_description": "An app that connects home cooks with nearby people who want homemade meals",
        "industry": "Food Tech",
        "target_customers": "Busy professionals and students",
    }
    print(json.dumps(run_workflow(sample), indent=2, ensure_ascii=False))
