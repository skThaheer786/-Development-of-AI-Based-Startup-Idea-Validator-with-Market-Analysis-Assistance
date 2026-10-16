
from web_search_agent import search_startup_market
from structured_extraction import extract_startup_idea


def convert_to_dict(value):
    """Convert a Pydantic model or dictionary into a dictionary."""

    if isinstance(value, dict):
        return value

    if hasattr(value, "model_dump"):
        return value.model_dump()

    if hasattr(value, "dict"):
        return value.dict()

    raise ValueError("Idea extraction did not return valid structured data.")


def run_startup_workflow(raw_idea):
    """
    Orchestrate the initial startup validation workflow.

    1. Validate input.
    2. Extract structured idea using Groq.
    3. Search the market using Tavily.
    4. Return all outputs in one response.
    """

    if not isinstance(raw_idea, dict):
        raise ValueError("Startup idea must be a JSON object.")

    description = str(
        raw_idea.get("idea_description", "")
    ).strip()

    industry = str(raw_idea.get("industry", "")).strip()
    customers = str(
        raw_idea.get("target_customers", "")
    ).strip()

    details = str(
        raw_idea.get("relevant_details", "")
    ).strip()

    if not description:
        raise ValueError("Startup idea description is required.")

    if len(description) < 20:
        raise ValueError("Idea description must contain at least 20 characters.")

    if len(description) > 5000:
        raise ValueError("Idea description is too long.")

    if not industry:
        raise ValueError("Industry is required.")

    if not customers:
        raise ValueError("Target customers are required.")

    # Step 1: Prepare validated input.
    input_data = {
        "idea_description": description,
        "industry": industry,
        "target_customers": customers,
        "relevant_details": details
    }

    # Step 2: Ask Groq to extract the structured idea.
    extraction_output = extract_startup_idea(input_data)
    structured_idea = convert_to_dict(extraction_output)

    # Step 3: Preserve the original information as fallbacks.
    # Use the extracted fields when they are available.
    search_idea = {
        "idea_description": (
            structured_idea.get("idea_description")
            or structured_idea.get("description")
            or description
        ),
        "industry": structured_idea.get("industry") or industry,
        "target_customers": (
            structured_idea.get("target_customers") or customers
        )
    }

    # Step 4: Send the idea to the Tavily Web Search Agent.
    market_research = search_startup_market(search_idea)

    # Step 5: Return a combined result for the Flask frontend.
    return {
        "success": True,
        "workflow": [
            "input_validation",
            "idea_extraction",
            "market_search",
            "response_assembly"
        ],
        "structured_idea": structured_idea,
        "search_input": search_idea,
        "market_research": market_research
    }
