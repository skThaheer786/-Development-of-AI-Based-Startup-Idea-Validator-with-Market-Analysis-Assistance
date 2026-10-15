
import json
import os
from dotenv import load_dotenv
from tavily import TavilyClient

# Load API key from .env
load_dotenv()
API_KEY = os.getenv("TAVILY_API_KEY")


# Get any startup idea from the user
def get_startup_idea():
    print("\n=== AI STARTUP IDEA VALIDATOR ===")
    print("Enter any startup idea from any industry.")

    idea = input("\nDescribe your startup idea: ").strip()
    industry = input("Enter the industry: ").strip()
    customers = input("Enter target customers: ").strip()

    if not idea:
        raise ValueError("Startup idea cannot be empty.")

    if not industry:
        industry = "Unknown"

    if not customers:
        customers = "General customers"

    return {
        "idea": idea,
        "industry": industry,
        "customers": customers
    }


# Generate web search queries
def generate_queries(idea, industry, customers):
    return [
        f"{idea} competitors",
        f"{industry} market trends",
        f"{idea} solutions for {customers}",
        f"{idea} market size and demand",
        f"{idea} existing products and alternatives"
    ]


# Search the web using Tavily
def search_market(idea, industry, customers):
    if not API_KEY:
        raise ValueError(
            "Tavily API key is missing. Check your .env file."
        )

    client = TavilyClient(api_key=API_KEY)
    queries = generate_queries(idea, industry, customers)
    results = []

    for query in queries:
        print(f"\nSearching: {query}")

        try:
            response = client.search(
                query=query,
                max_results=3
            )

            for item in response.get("results", []):
                results.append({
                    "query": query,
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", "")
                })

        except Exception as error:
            print(f"Search failed: {error}")

    return {
        "idea": idea,
        "industry": industry,
        "customers": customers,
        "queries": queries,
        "results": results
    }


# Display the research report
def display_results(data):
    print("\n" + "=" * 60)
    print("STARTUP MARKET RESEARCH REPORT")
    print("=" * 60)

    print("Startup Idea:", data["idea"])
    print("Industry:", data["industry"])
    print("Target Customers:", data["customers"])

    print("\nSearch Results:")

    if not data["results"]:
        print("No results found. Check your API key or connection.")
        return

    for number, result in enumerate(data["results"], start=1):
        print(f"\nResult {number}")
        print("Search Query:", result["query"])
        print("Title:", result["title"])
        print("URL:", result["url"])
        print("Summary:", result["content"])
        print("-" * 60)


# Save results to a JSON file
def save_report(data):
    filename = "market_research_results.json"

    with open(filename, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)

    print(f"\nResearch report saved to {filename}")


# Main program
if __name__ == "__main__":
    try:
        if not API_KEY:
            raise ValueError(
                "TAVILY_API_KEY is missing. Check your .env file."
            )

        print("Tavily API key loaded successfully!")

        startup = get_startup_idea()

        report = search_market(
            startup["idea"],
            startup["industry"],
            startup["customers"]
        )

        display_results(report)
        save_report(report)

    except ValueError as error:
        print("\nInput/Configuration Error:", error)

    except Exception as error:
        print("\nUnexpected Error:", error)
