
from flask import Flask, render_template, request, jsonify

from structured_extraction import (
    extract_startup_idea,
    IdeaExtractionError,
)

app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/ideas", methods=["POST"])
def submit_idea():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "success": False,
            "message": "Invalid request. Please submit the form again."
        }), 400

    idea = {
        "idea_description": str(
            data.get("idea_description", "")
        ).strip(),
        "industry": str(data.get("industry", "")).strip(),
        "target_customers": str(
            data.get("target_customers", "")
        ).strip(),
        "relevant_details": str(
            data.get("relevant_details", "")
        ).strip(),
    }

    errors = {}

    if len(idea["idea_description"]) < 20:
        errors["idea_description"] = (
            "Enter at least 20 characters."
        )
    elif len(idea["idea_description"]) > 5000:
        errors["idea_description"] = (
            "Maximum 5000 characters allowed."
        )

    if not idea["industry"]:
        errors["industry"] = "Please select an industry."
    elif len(idea["industry"]) > 100:
        errors["industry"] = "Industry is too long."

    if not idea["target_customers"]:
        errors["target_customers"] = (
            "Please enter your target customers."
        )
    elif len(idea["target_customers"]) > 500:
        errors["target_customers"] = (
            "Maximum 500 characters allowed."
        )

    if len(idea["relevant_details"]) > 2000:
        errors["relevant_details"] = (
            "Maximum 2000 characters allowed."
        )

    if errors:
        return jsonify({
            "success": False,
            "message": "Please correct the highlighted fields.",
            "errors": errors,
        }), 400

    try:
        # Task 2: send the valid submission to the LLM.
        extracted_idea = extract_startup_idea(idea)

        print("Original submission:", idea)
        print("Structured LLM output:", extracted_idea)

        return jsonify({
            "success": True,
            "message": "Startup idea extracted successfully!",
            "idea": idea,
            "extracted_idea": extracted_idea,
        }), 200

    except IdeaExtractionError as exc:
        app.logger.warning("Idea extraction failed: %s", exc)

        return jsonify({
            "success": False,
            "message": str(exc),
        }), 502

    except Exception:
        app.logger.exception("Unexpected submission error")

        return jsonify({
            "success": False,
            "message": "An unexpected server error occurred.",
        }), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
