
import os
import json
import re
from datetime import datetime

from dotenv import load_dotenv
from tavily import TavilyClient
from groq import Groq

# --------------------------------------------------
# 1. LOAD API KEYS
# --------------------------------------------------

load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not TAVILY_API_KEY:
    raise ValueError("TAVILY_API_KEY is missing from .env")

if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is missing from .env")

tavily = TavilyClient(api_key=TAVILY_API_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)

MODEL_NAME = "openai/gpt-oss-120b"


# --------------------------------------------------
# 2. CREATE A SAFE FILENAME
# --------------------------------------------------

def safe_filename(text):
    """Convert a startup idea into a safe filename."""

    name = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower())
    return name.strip("_")[:50] or "startup_idea"


# --------------------------------------------------
# 3. DISCOVER COMPETITORS USING TAVILY
# --------------------------------------------------

def discover_competitors(idea, industry, customers):
    """Search for existing competitors and alternatives."""

    query = (
        f"Existing companies, products, competitors and alternatives "
        f"for {idea} in the {industry} industry. "
        f"Target customers: {customers}. "
        f"Find product features, official websites, pricing where "
        f"available, strengths and limitations."
    )

    response = tavily.search(
        query=query,
        search_depth="advanced",
        max_results=8,
        include_answer=False
    )

    results = []

    for item in response.get("results", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": item.get("content", "")
        })

    if not results:
        raise ValueError(
            "No search results found for this startup idea."
        )

    return results


# --------------------------------------------------
# 4. COMPARE COMPETITORS USING GROQ
# --------------------------------------------------

def compare_competitors(idea, industry, customers, results):
    """Analyze competitors, compare offerings and identify gaps."""

    research_data = json.dumps(
        results,
        ensure_ascii=False
    )

    prompt = f"""
You are an AI startup competitor discovery and analysis agent.

STARTUP IDEA: {idea}
INDUSTRY: {industry}
TARGET CUSTOMERS: {customers}

WEB SEARCH RESULTS:
{research_data}

Analyze the supplied search results.

Requirements:
1. Identify up to five relevant competitors or alternatives.
2. Remove duplicate and unrelated companies.
3. Compare product offerings and target customers.
4. Identify features, strengths and limitations.
5. Report pricing only when supported by evidence.
6. Identify potential market gaps and unmet needs.
7. Recommend ways to differentiate the startup.
8. Include source URLs from the supplied search results.
9. Mark unavailable information as "Not found".
10. Never invent company details, prices or features.
11. Treat potential gaps as hypotheses unless supported by evidence.
12. Explain research limitations.

Return valid JSON using exactly this general structure:

{{
  "startup_idea": "...",
  "industry": "...",
  "target_customers": "...",
  "competitors": [
    {{
      "name": "...",
      "website": "...",
      "product": "...",
      "target_customers": "...",
      "features": ["..."],
      "pricing": "...",
      "strengths": ["..."],
      "limitations": ["..."],
      "source_urls": ["..."]
    }}
  ],
  "market_gaps": [
    {{
      "gap": "...",
      "evidence": "...",
      "confidence": "low, medium, or high"
    }}
  ],
  "differentiation_recommendations": ["..."],
  "research_limitations": ["..."]
}}

Return JSON only. Do not include Markdown fences.
"""

    response = groq_client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a careful market research analyst. "
                    "Return valid JSON only. Never invent evidence."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.2,
        response_format={"type": "json_object"}
    )

    content = response.choices[0].message.content

    if not content:
        raise ValueError("Groq returned an empty analysis.")

    report = json.loads(content)

    return report


# --------------------------------------------------
# 5. ANALYZE AND SAVE ONE STARTUP IDEA
# --------------------------------------------------

def analyze_one_idea(idea, industry, customers):
    """Run discovery and analysis, then save the report."""

    print(f"\nSearching competitors for: {idea}")

    results = discover_competitors(
        idea, industry, customers
    )

    print(f"Found {len(results)} web results.")
    print("Comparing competitors and identifying market gaps...")

    report = compare_competitors(
        idea, industry, customers, results
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    filename = (
        f"competitor_{safe_filename(idea)}_{timestamp}.json"
    )

    with open(filename, "w", encoding="utf-8") as file:
        json.dump(
            report,
            file,
            indent=4,
            ensure_ascii=False
        )

    return {
        "idea": idea,
        "status": "success",
        "report_file": filename,
        "report": report
    }


# --------------------------------------------------
# 6. ACCEPT MULTIPLE IDEAS AND DISPLAY EACH RESULT
# --------------------------------------------------

def main():
    """Analyze ideas one at a time and show each result immediately."""

    successful = 0
    failed = 0

    print("=" * 60)
    print(" COMPETITOR DISCOVERY AND COMPARISON AGENT ")
    print("=" * 60)
    print("You can enter any startup idea.")
    print("Enter 'done' when you want to exit.")

    while True:
        idea = input(
            "\nEnter startup idea (or 'done' to exit): "
        ).strip()

        if idea.lower() == "done":
            break

        if not idea:
            print("Please enter a valid startup idea.")
            continue

        industry = input("Enter industry: ").strip()
        customers = input("Enter target customers: ").strip()

        if not industry or not customers:
            print("Industry and target customers are required.")
            continue

        try:
            result = analyze_one_idea(
                idea, industry, customers
            )

            # Display the complete result immediately
            print("\n" + "=" * 60)
            print(" COMPETITOR ANALYSIS RESULT ")
            print("=" * 60)

            print(json.dumps(
                result["report"],
                indent=4,
                ensure_ascii=False
            ))

            print("\nReport saved to:", result["report_file"])
            successful += 1

        except Exception as error:
            print(f"\nAnalysis failed for '{idea}': {error}")
            failed += 1

        print("\n" + "-" * 60)
        print("Previous idea analysis is complete.")
        print("You can now enter another startup idea.")

    print("\n" + "=" * 60)
    print(" SESSION SUMMARY ")
    print("=" * 60)
    print(f"Successful analyses: {successful}")
    print(f"Failed analyses: {failed}")
    print("Thank you for using the Competitor Analysis Agent!")


# --------------------------------------------------
# 7. START THE PROGRAM
# --------------------------------------------------

if __name__ == "__main__":
    main()
