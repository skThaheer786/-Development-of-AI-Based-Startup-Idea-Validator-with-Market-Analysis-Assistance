from orchestrator import run_startup_workflow
import os
import logging
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

from structured_extraction import extract_startup_idea
from web_search_agent import search_startup_market
from market_opportunity_agent import analyze_market_opportunity

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024

logging.basicConfig(level=logging.INFO)


def error_response(message, status_code):
    return jsonify({
        "success": False,
        "error": message
    }), status_code


def to_dict(value):
    """Convert structured extraction output into JSON-compatible data."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, dict):
        return value
    raise TypeError("The extraction result is not a valid structured object.")


@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")


# TASK 2: Structured startup idea extraction using Groq
@app.route("/api/ideas", methods=["POST"])
def submit_idea():
    try:
        idea = request.get_json(silent=True)

        if not isinstance(idea, dict):
            return error_response("Please submit valid JSON data.", 400)

        description = str(idea.get("idea_description", "")).strip()
        industry = str(idea.get("industry", "")).strip()
        customers = str(idea.get("target_customers", "")).strip()
        details = str(idea.get("relevant_details", "")).strip()

        if not description:
            return error_response("Startup idea description is required.", 400)

        if len(description) < 20 or len(description) > 5000:
            return error_response(
                "Idea description must contain 20 to 5000 characters.", 400
            )

        if not industry or len(industry) > 100:
            return error_response(
                "Industry is required and must be at most 100 characters.", 400
            )

        if not customers or len(customers) > 500:
            return error_response(
                "Target customers are required and must be at most 500 characters.",
                400
            )

        if len(details) > 2000:
            return error_response(
                "Relevant details must be at most 2000 characters.", 400
            )

        # Send the idea to your existing Groq extraction function.
        idea_data = {
            "idea_description": description,
            "industry": industry,
            "target_customers": customers,
            "relevant_details": details
        }

        extracted = extract_startup_idea(idea_data)

        return jsonify({
            "success": True,
            "message": "Startup idea extracted successfully.",
            "idea": idea_data,
            "extracted_idea": to_dict(extracted)
        }), 200

    except Exception:
        app.logger.exception("Startup idea extraction failed")
        return error_response(
            "Idea extraction failed. Check your Groq API configuration.",
            502
        )


# TASK 3: Live market and competitor research using Tavily
@app.route("/api/market-search", methods=["POST"])
def market_search():
    try:
        idea = request.get_json(silent=True)

        if not isinstance(idea, dict):
            return error_response("Please submit valid JSON data.", 400)

        description = str(idea.get("idea_description", "")).strip()
        industry = str(idea.get("industry", "")).strip()
        customers = str(idea.get("target_customers", "")).strip()

        if not description:
            return error_response("Startup idea description is required.", 400)

        if len(description) > 5000:
            return error_response(
                "Idea description must be at most 5000 characters.", 400
            )

        # Calls your working Tavily search agent.
        research = search_startup_market({
            "idea_description": description,
            "industry": industry,
            "target_customers": customers
        })

        return jsonify({
            "success": True,
            "message": "Market research completed successfully.",
            "market_research": research
        }), 200

    except ValueError as error:
        return error_response(str(error), 400)

    except Exception:
        app.logger.exception("Tavily market search failed")
        return error_response(
            "Market search failed. Check your Tavily API key, "
            "network connection, and API usage.",
            502
        )


@app.errorhandler(404)
def not_found(error):
    return error_response("The requested endpoint was not found.", 404)


@app.errorhandler(413)
def request_too_large(error):
    return error_response("Request size exceeds the allowed limit.", 413)

@app.route("/api/orchestrate", methods=["POST"])
def orchestrate_startup():
    try:
        idea = request.get_json(silent=True)

        if not isinstance(idea, dict):
            return jsonify({
                "success": False,
                "error": "Please submit valid JSON."
            }), 400

        result = run_startup_workflow(idea)

        return jsonify(result), 200

    except ValueError as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except Exception:
        app.logger.exception("Startup workflow failed")

        return jsonify({
            "success": False,
            "error": (
                "Workflow failed. Check the Groq API, Tavily API, "
                "and server logs."
            )
        }), 502


if __name__ == "__main__":
    app.run(debug=True, port=5000)
