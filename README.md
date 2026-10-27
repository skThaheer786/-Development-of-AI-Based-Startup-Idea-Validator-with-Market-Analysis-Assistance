
# AI-Based Startup Idea Validator with Market Analysis Assistance

## Overview

An AI-powered application that helps users evaluate startup ideas by extracting structured information using Groq and retrieving market and competitor information using the Tavily Search API.

## Features

- Startup idea submission with input validation
- Structured idea extraction using Groq
- Automated web search query generation
- Market and competitor research using Tavily
- Multi-agent workflow orchestration
- Combined results displayed in a web interface
- Error handling for invalid inputs and failed requests

## Technology Stack

- Python
- Flask
- Groq API
- Tavily Search API
- HTML, CSS, JavaScript
- python-dotenv

## Project Structure

    project/
    ├── app.py
    ├── orchestrator.py
    ├── structured_extraction.py
    ├── web_search_agent.py
    ├── market_analysis.py
    ├── templates/
    │   └── index.html
    ├── static/
    │   ├── style.css
    │   └── script.js
    ├── .env
    ├── .gitignore
    └── README.md

## Requirements

- Python 3.10 or newer
- Groq API key
- Tavily API key
- Internet connection

## Installation

1. Clone the repository.

       git clone YOUR_TEAM_REPOSITORY_URL
       cd YOUR_PROJECT_FOLDER

2. Create a virtual environment.

       python -m venv .venv

3. Activate it on Windows PowerShell.

       .\.venv\Scripts\Activate.ps1

4. Install dependencies.

       python -m pip install Flask python-dotenv groq tavily-python

## Environment Variables

Create a `.env` file in the project root:

    GROQ_API_KEY=your_groq_api_key
    TAVILY_API_KEY=your_tavily_api_key

Never commit your actual API keys.

## Run the Application

    python app.py

Open the following URL in your browser:

    http://127.0.0.1:5000

## API Endpoints

- `POST /api/ideas` — extracts structured startup idea information.
- `POST /api/market-search` — retrieves market and competitor search results.
- `POST /api/orchestrate` — executes idea extraction and market search in sequence.
- - `POST /api/market-opportunity` — researches market size and trends, analyzes customer segment hypotheses, and returns source-linked results.

## Testing

Test the workflow using startup ideas from:

1. Education technology
2. Food technology
3. Agriculture technology

Verify the extracted fields, search queries, result titles, summaries, and source URLs.

Also test missing required fields, invalid JSON, API failures, and empty search results.

## Security

- Store API keys in environment variables.
- Keep `.env` out of Git.
- Do not expose API keys in frontend JavaScript.
- Validate user inputs and handle external API errors.

## Current Milestone

Milestone 1: Startup idea submission, structured extraction, web search integration, and initial workflow orchestration.
Milestone 2, Task 1: Market opportunity and customer segmentation analysis using Tavily evidence and Groq structured analysis. Configure `GROQ_API_KEY` and `TAVILY_API_KEY` before using the endpoint. Treat segments as hypotheses and verify market claims against their linked sources.
