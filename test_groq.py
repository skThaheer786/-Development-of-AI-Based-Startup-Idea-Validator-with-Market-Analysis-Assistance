
from dotenv import load_dotenv
from groq import Groq
import os

load_dotenv()

api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    print("ERROR: GROQ_API_KEY was not loaded from .env")
    raise SystemExit(1)

try:
    client = Groq(api_key=api_key, max_retries=0)

    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {
                "role": "user",
                "content": 'Return JSON only: {"status": "working"}'
            }
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    print("SUCCESS: Groq API is working.")
    print(response.choices[0].message.content)

except Exception as exc:
    print("Groq test failed.")
    print("Error type:", type(exc).__name__)
    print("HTTP status:", getattr(exc, "status_code", "unknown"))
    print("Details:", str(exc))
