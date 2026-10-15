"""
orchestrator.py  --  Task 4: Multi-Agent Orchestration (Milestone 1)

Flow:
    User idea (form) -> Extraction Agent (LLM) -> Market Research Agent (Tavily)
                     -> [future agents] -> Final result dict

Each step reads from / writes to one shared `state` dict, so data is passed
between components in a single, predictable place.

>>> IMPORTANT: Adjust the 2 import lines below to match the function names in
>>> your teammates' files (structured_extraction.py, market_research.py).
"""

import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("orchestrator")

# ---------------------------------------------------------------------------
# Imports from teammates' modules (Task 2 and Task 3)
# Change the function names here if yours are different.
# ---------------------------------------------------------------------------
try:
    from structured_extraction import extract_startup_idea  # Task 2: returns dict
except ImportError:
    extract_startup_idea = None

try:
    from market_research import run_market_research  # Task 3: returns dict/list
except ImportError:
    run_market_research = None


# ---------------------------------------------------------------------------
# Agent registry: responsibility of each agent
# ---------------------------------------------------------------------------
AGENTS = {
    "extraction_agent": "Uses the LLM to turn the raw idea into structured JSON "
                        "(problem, solution, customers, industry, key features).",
    "market_research_agent": "Generates search queries from the structured idea and "
                             "fetches live market/competitor data via Tavily.",
    "competitor_agent": "(Milestone 2) Identifies and compares competitors.",
    "risk_agent": "(Milestone 2) Analyses strengths, weaknesses and risks.",
    "feature_agent": "(Milestone 2) Recommends first features / MVP scope.",
    "report_agent": "(Milestone 3) Generates the final validation report.",
}


# ---------------------------------------------------------------------------
# Individual steps (thin wrappers so errors are handled in one place)
# ---------------------------------------------------------------------------
def _validate_input(raw_idea: dict) -> None:
    required = ["idea_description", "industry", "target_customers"]
    missing = [f for f in required if not str(raw_idea.get(f, "")).strip()]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")


def _step_extraction(state: dict) -> dict:
    if extract_startup_idea is None:
        raise RuntimeError("structured_extraction.extract_startup_idea not found")
    structured = extract_startup_idea(state["raw_idea"])
    if not isinstance(structured, dict) or not structured:
        raise ValueError("Extraction agent returned invalid/empty JSON")
    return structured


def _step_market_research(state: dict) -> dict:
    if run_market_research is None:
        raise RuntimeError("market_research.run_market_research not found")
    return run_market_research(state["structured_idea"])


# ---------------------------------------------------------------------------
# Main orchestration function
# ---------------------------------------------------------------------------
def run_workflow(raw_idea: dict) -> dict:
    """
    Run the Milestone 1 workflow and return the shared state.

    state = {
        "raw_idea": {...},            # from UI form
        "structured_idea": {...},     # from Extraction Agent
        "market_research": {...},     # from Market Research Agent
        "errors": [...],              # any step failures
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
        state["structured_idea"] = _step_extraction(state)
    except Exception as e:  # API errors, bad JSON, etc.
        log.error("Extraction failed: %s", e)
        state["errors"].append({"step": "extraction", "error": str(e)})
        return state  # later steps need the structured idea

    # Step 2: Market Research Agent (web search)
    try:
        log.info("Step 2: Market Research Agent running")
        state["market_research"] = _step_market_research(state)
        state["status"] = "success"
    except Exception as e:
        log.error("Market research failed: %s", e)
        state["errors"].append({"step": "market_research", "error": str(e)})
        state["status"] = "partial"  # we still have the structured idea

    # Future: competitor_agent, risk_agent, feature_agent, report_agent
    return state


if __name__ == "__main__":
    import json

    sample = {
        "idea_description": "An app that connects home cooks with nearby people who want homemade meals",
        "industry": "Food Tech",
        "target_customers": "Busy professionals and students",
        "details": "Subscription + commission model",
    }
    print(json.dumps(run_workflow(sample), indent=2, default=str))
