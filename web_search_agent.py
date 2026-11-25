
import os
from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()


def search_startup_market(idea):
    api_key = os.getenv("TAVILY_API_KEY")

    if not api_key:
        raise ValueError("TAVILY_API_KEY is missing in .env")

    description = idea.get("idea_description", "").strip()
    industry = idea.get("industry", "").strip()
    customers = idea.get("target_customers", "").strip()

    if not description:
        raise ValueError("Please enter a startup idea.")

    client = TavilyClient(api_key=api_key)

    queries = [
        f"{description} market trends",
        f"{description} competitors alternatives",
        f"{industry or description} market size and growth",
        f"{customers or 'potential customers'} needs in {industry or description}"
    ]

    results = []
    seen_urls = set()

    for query in queries:
        response = client.search(
            query=query,
            search_depth="basic",
            max_results=3
        )

        for item in response.get("results", []):
            url = item.get("url", "")

            if url and url not in seen_urls:
                seen_urls.add(url)

                results.append({
                    "query": query,
                    "title": item.get("title", "Untitled"),
                    "url": url,
                    "content": item.get("content", "")
                })

    return {
        "queries": queries,
        "results": results,
        "total_results": len(results)
    }
