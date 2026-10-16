
from web_search_agent import search_startup_market

idea = {
    "idea_description": "AI-powered personalized learning platform",
    "industry": "EdTech",
    "target_customers": "College students"
}

try:
    data = search_startup_market(idea)

    print("\nSEARCH QUERIES")
    for query in data["queries"]:
        print("-", query)

    print("\nMARKET AND COMPETITOR RESULTS")

    for i, result in enumerate(data["results"], start=1):
        print(f"\n{i}. {result['title']}")
        print("URL:", result["url"])
        print("Summary:", result["content"])

    print("\nTotal results:", data["total_results"])

except Exception as error:
    print("Error:", error)
