from datetime import datetime
from zoneinfo import ZoneInfo
import os
from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()

api_key = os.getenv("TAVILY_API_KEY")
client = TavilyClient(api_key=api_key)

print("Welcome to Tavily Q&A Chatbot!")
print("Type 'exit' to stop.\n")
now = datetime.now(ZoneInfo("Asia/Kolkata"))

print("Current Date:", now.strftime("%d-%m-%Y"))
print("Current Time:", now.strftime("%I:%M:%S %p"))

while True:
    question = input("You: ").strip()

    if question.lower() == "exit":
        print("Bot: Goodbye!")
        break

    now = datetime.now(ZoneInfo("Asia/Kolkata"))

    if question.lower() in [
        "what is today's date?",
        "what is today's date",
        "what is the date today?",
        "what date is it today?"
    ]:
        print("Bot: Today's date is",
              now.strftime("%A, %B %d, %Y"))
        continue

    if not question:
        continue
    
    if not question:
        continue

    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    q = question.lower().strip().rstrip("?!.")

    if q in [
        "what is today's date",
        "what is the date today",
        "what date is it today",
        "today's date",
        "date today"
    ]:
        print("Bot: Today's date is",
              now.strftime("%A, %B %d, %Y"))
        continue

    if q in [
        "what time is it",
        "what is the current time",
        "what time is it now",
        "current time"
    ]:
        print("Bot: The current time is",
              now.strftime("%I:%M:%S %p IST"))
        continue

    try:
        response = client.search(
            query=question,
            include_answer=True,
            max_results=3
        )

        print("\nBot:", response.get(
            "answer", "No direct answer found."
        ))

        print("\nSources:")
        for result in response.get("results", []):
            print(result["title"])
            print(result["url"])

        print()

    except Exception as e:
        print("Error:", e)
