import os
from dotenv import load_dotenv
from tavily import TavilyClient

# Load API key
load_dotenv()
api_key = os.getenv("TAVILY_API_KEY")

if not api_key:
    raise ValueError("Please add your Tavily API key to the .env file")

# Create Tavily client
client = TavilyClient(api_key=api_key)

print("🤖 Welcome to the Python Q&A Chatbot!")
print("Ask anything. Type 'exit' to stop.\n")

while True:
    question = input("You: ").strip()

    if question.lower() == "exit":
        print("Bot: Goodbye!")
        break

    if not question:
        print("Bot: Please enter a question.")
        continue

    try:
        # Search the web and get an answer
        response = client.search(
            query=question,
            include_answer=True,
            max_results=3
        )

        answer = response.get("answer")

        if answer:
            print("\nBot:", answer)
        else:
            print("\nBot: Here is what I found:")

        # Display sources
        for result in response.get("results", []):
            print("-", result["title"])
            print("  ", result["url"])

        print()

    except Exception as error:
        print("Bot: Something went wrong:", error)