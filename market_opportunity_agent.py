"""Source-grounded market opportunity and customer segmentation agent."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from groq import Groq
from pydantic import BaseModel, Field, ValidationError
from tavily import TavilyClient

load_dotenv()


class MarketClaim(BaseModel):
    claim: str
    source_ids: list[str] = Field(default_factory=list)
    confidence: str = Field(description="low, medium, or high")


class CustomerSegment(BaseModel):
    name: str
    description: str
    problem_and_need: str
    buying_or_adoption_factors: list[str] = Field(default_factory=list)
    fit_rationale: str
    assumptions_to_validate: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class MarketOpportunityAnalysis(BaseModel):
    executive_summary: str
    market_size_and_growth: list[MarketClaim] = Field(default_factory=list)
    market_trends: list[MarketClaim] = Field(default_factory=list)
    customer_segments: list[CustomerSegment] = Field(default_factory=list)
    opportunity_gaps: list[str] = Field(default_factory=list)
    validation_questions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _required_text(idea: dict[str, Any], key: str) -> str:
    value = str(idea.get(key, "")).strip()
    if not value:
        raise ValueError(f"{key} is required.")
    return value


def _search_evidence(idea: dict[str, Any], client: TavilyClient) -> tuple[list[dict[str, Any]], list[str]]:
    description = _required_text(idea, "idea_description")
    industry = _required_text(idea, "industry")
    customers = _required_text(idea, "target_customers")
    geography = str(idea.get("geography") or "global").strip()
    queries = [
        f"{industry} market size revenue growth forecast {geography}",
        f"{industry} market trends adoption drivers challenges {geography}",
        f"{customers} needs buying behavior {industry}",
        f"{description} market demand problem evidence {geography}",
    ]
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for query in queries:
        response = client.search(query=query, search_depth="advanced", max_results=5)
        for result in response.get("results", []):
            url = str(result.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            sources.append({
                "id": f"S{len(sources) + 1}",
                "query": query,
                "title": result.get("title") or "Untitled source",
                "url": url,
                "snippet": result.get("content") or "",
                "published_date": result.get("published_date"),
                "score": result.get("score"),
            })
    return sources, queries


def analyze_market_opportunity(idea: dict[str, Any], *, tavily_client: TavilyClient | None = None,
                               groq_client: Groq | None = None) -> dict[str, Any]:
    """Research a market and assess candidate segments; all estimates require source review."""
    description = _required_text(idea, "idea_description")
    industry = _required_text(idea, "industry")
    customers = _required_text(idea, "target_customers")
    geography = str(idea.get("geography") or "global").strip()
    tavily_key = os.getenv("TAVILY_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")
    if not tavily_client and not tavily_key:
        raise ValueError("TAVILY_API_KEY is missing from the environment or .env file.")
    if not groq_client and not groq_key:
        raise ValueError("GROQ_API_KEY is missing from the environment or .env file.")
    tavily_client = tavily_client or TavilyClient(api_key=tavily_key)
    groq_client = groq_client or Groq(api_key=groq_key, timeout=45.0, max_retries=1)

    sources, queries = _search_evidence(idea, tavily_client)
    if not sources:
        raise ValueError("No market evidence was returned. Try a broader industry or geography.")

    schema = MarketOpportunityAnalysis.model_json_schema()
    prompt = f"""Analyze the startup opportunity using only the supplied research evidence.

STARTUP IDEA: {description}
INDUSTRY: {industry}
USER-PROVIDED TARGET CUSTOMERS: {customers}
GEOGRAPHY: {geography}
ADDITIONAL CONTEXT: {str(idea.get('relevant_details') or '')[:2000]}

EVIDENCE (IDs are the only valid citations):
{json.dumps(sources, ensure_ascii=False)}

Return JSON matching this schema exactly:
{json.dumps(schema)}

Rules:
- Never invent market size, growth rates, dates, source IDs, or customer behavior.
- Separate sourced claims from inferences. If evidence has no reliable numeric estimate, say so in the claim.
- Cite claims and segment rationale with source_ids from the evidence only; use [] when unsupported.
- Treat each segment as a hypothesis. Start with the user-provided target customers; add other segments only when evidence supports them.
- Include geography and time period when evidence provides them. Flag inconsistent definitions and stale data in limitations.
- Confidence reflects the strength and agreement of retrieved evidence, not certainty that demand exists.
- Recommend validation questions that could be answered by prospective customers or primary data.
"""
    response = groq_client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {"role": "system", "content": "You are a cautious market research analyst. Return valid JSON and cite only provided source IDs."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("Groq returned an empty market analysis.")
    try:
        analysis = MarketOpportunityAnalysis.model_validate_json(content)
    except ValidationError as error:
        raise ValueError("The market analysis response did not match the expected schema.") from error

    valid_ids = {source["id"] for source in sources}
    serialized = analysis.model_dump()
    for claim_group in ("market_size_and_growth", "market_trends"):
        for item in serialized[claim_group]:
            item["source_ids"] = [source_id for source_id in item["source_ids"] if source_id in valid_ids]
    for segment in serialized["customer_segments"]:
        segment["source_ids"] = [source_id for source_id in segment["source_ids"] if source_id in valid_ids]
    return {
        "agent": "market_opportunity_customer_segmentation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "idea": {"idea_description": description, "industry": industry,
                 "target_customers": customers, "geography": geography},
        "queries": queries,
        "analysis": serialized,
        "sources": sources,
        "evidence_note": "Search results and model analysis are decision support, not proof of customer demand or market viability.",
    }
