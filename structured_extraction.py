
import os
import json

from dotenv import load_dotenv
from groq import (
    Groq,
    APIError,
    APIConnectionError,
    RateLimitError,
    AuthenticationError,
)
from pydantic import BaseModel, Field, ValidationError

load_dotenv()


class StructuredIdea(BaseModel):
    problem_statement: str = Field(
        description="The main customer problem"
    )
    proposed_solution: str = Field(
        description="How the startup solves the problem"
    )
    target_customers: str = Field(
        description="The intended customers"
    )
    industry: str = Field(
        description="The startup industry"
    )
    key_features: list[str] = Field(
        min_length=1,
        max_length=10,
        description="Important product or service features"
    )


class IdeaExtractionError(Exception):
    pass


def extract_startup_idea(idea_data: dict) -> dict:
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        raise IdeaExtractionError(
            "GROQ_API_KEY is missing from the .env file."
        )

    try:
        client = Groq(
            api_key=api_key,
            timeout=30.0,
            max_retries=0,
        )

        prompt = f"""
You are an expert startup idea analyst.

Analyze this startup submission:
{json.dumps(idea_data, ensure_ascii=False)}

Extract these fields:
1. problem_statement
2. proposed_solution
3. target_customers
4. industry
5. key_features

Instructions:
- Explain the likely customer problem.
- Describe a practical proposed solution.
- Use the submitted target customers when provided.
- If customers are missing, suggest likely customers and
  identify them as inferred.
- Preserve the submitted industry.
- Suggest 3 to 6 practical features.
- Do not invent unsupported facts.
- If the idea is too vague, explain what is unclear.
- Return valid JSON only.
- Use exactly the five requested fields.
- key_features must be an array of strings.
"""

        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You analyze startup ideas and return "
                        "useful, accurate structured JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )

        content = response.choices[0].message.content

        if not content:
            raise IdeaExtractionError(
                "Groq returned an empty response."
            )

        parsed_data = json.loads(content)
        validated = StructuredIdea.model_validate(parsed_data)

        return validated.model_dump()

    except IdeaExtractionError:
        raise

    except AuthenticationError as exc:
        print("Groq authentication error:", exc)
        raise IdeaExtractionError(
            "Groq authentication failed. Check your API key."
        ) from exc

    except RateLimitError as exc:
        print("Groq rate limit error:", exc)
        raise IdeaExtractionError(
            "Groq usage limit reached. Check your API quota."
        ) from exc

    except APIConnectionError as exc:
        print("Groq connection error:", exc)
        raise IdeaExtractionError(
            "Could not connect to Groq. Check your internet."
        ) from exc

    except json.JSONDecodeError as exc:
        print("Invalid JSON:", exc)
        raise IdeaExtractionError(
            "Groq returned invalid JSON. Please retry."
        ) from exc

    except ValidationError as exc:
        print("Output validation error:", exc)
        raise IdeaExtractionError(
            "Groq returned incomplete or invalid fields."
        ) from exc

    except APIError as exc:
        print("Groq HTTP status:", getattr(exc, "status_code", "unknown"))
        print("Groq API details:", str(exc))
        raise IdeaExtractionError(
            "Groq API request failed. Check the terminal."
        ) from exc

    except Exception as exc:
        print("Unexpected error:", repr(exc))
        raise IdeaExtractionError(
            "Unexpected startup idea extraction error."
        ) from exc
