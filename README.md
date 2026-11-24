# Development of AI-Based Startup Idea Validator with Market Analysis Assistance

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Flask](https://img.shields.io/badge/Framework-Flask%203.x-lightgrey)
![LLM](https://img.shields.io/badge/LLM-Groq-orange)
![Database](https://img.shields.io/badge/Database-SQLite-green)
![Tests](https://img.shields.io/badge/Tests-128%20passing-brightgreen)

An AI-assisted, evidence-based platform that helps students and first-time founders judge a startup idea **before** investing time and money.
A founder submits an idea; eight cooperating agents research the web, verify real competitors, estimate the market, analyse SWOT and risks, plan an MVP and
go-to-market strategy, and produce an **explainable viability score** and a downloadable report. Built with Python Flask, SQLite, the Groq LLM API,
Tavily / free web search, ReportLab, Bootstrap 5 and Chart.js.

> The result is **decision support, not a guarantee of success**. Every statement is labelled as *Sourced*, *AI analysis*, *AI assumption* or *Computed*.

## Table of Contents
1. [Key Features](#key-features)
2. [System Architecture](#system-architecture)
   - [High-Level Multi-Tier Architecture](#high-level-multi-tier-architecture)
   - [Eight-Agent Validation Pipeline](#eight-agent-validation-pipeline)
   - [Web Research & Competitor Verification Pipeline](#web-research--competitor-verification-pipeline)
   - [Market Sizing Mathematical Model (TAM / SAM / SOM)](#market-sizing-mathematical-model-tam--sam--som)
   - [Standardized Viability Scoring Mathematical Model](#standardized-viability-scoring-mathematical-model)
   - [Risk Scoring Model](#risk-scoring-model)
   - [Database Entity Relationship Overview](#database-entity-relationship-overview)
3. [Technology Stack](#technology-stack)
4. [Project Documentation](#project-documentation)
5. [Quick Start Guide](#quick-start-guide)
6. [API Route Catalog](#api-route-catalog)
7. [Automated Testing & Quality Assurance](#automated-testing--quality-assurance)
8. [Default System Credentials](#default-system-credentials)
9. [Project Directory Structure](#project-directory-structure)
10. [Troubleshooting](#troubleshooting)
11. [Limitations & Responsible Use](#limitations--responsible-use)
12. [License](#license)

## Key Features

### 1. Evidence-Based Market Research
- **Idea-specific web research:** search queries are generated from the submitted idea, so every industry (EdTech, FinTech, HealthTech, agriculture, e-commerce, SaaS, logistics, climate, legal, ...) is researched on its own terms.
- **Published market figures with links:** market-size and CAGR statements are extracted from retrieved page text, tied to a source id, and shown with the publisher type and a clickable link.
- **No invented numbers:** if no source states a figure the page shows **Insufficient data** with the reason, instead of guessing.
- **Market trends, customer demand, segments and opportunities**, each tagged as sourced or AI analysis.

### 2. Market Sizing (TAM / SAM / SOM)
- Two explainable methods (bottom-up and top-down from a published figure); the most complete one is used and the other is shown as a cross-check.
- The AI only proposes assumptions; **Python performs all arithmetic**, with low/high cases, the formula, currency, timeframe and every assumption labelled *Sourced* or *AI assumption*.
- Each level is calculated independently, so one missing input never blanks the others.

### 3. Verified Competitor Analysis
- A company is listed only after its **official website was fetched and confirmed**; products, features and pricing are read only from that page ("Not publicly listed" when absent).
- Competitors are typed **Direct / Indirect / Emerging**, with strengths taken from their sites, weaknesses labelled as AI analysis, a capability comparison matrix and **computed market gaps**.

### 4. Idea-Specific SWOT, Risk Register and MVP
- SWOT points carry a reason and an origin label (*from your idea*, *sourced*, *competitor data*, *AI inference*); labels are validated in code.
- Risks cover Technical, Financial, Market, Operational, Legal/Regulatory and Competitive categories (plus adoption and privacy when relevant) with impact/likelihood reasons, mitigation, realistic solution and early-warning signs.
- MVP plan: Must / Should / Could / Deferred features, build order, roadmap, **development cost estimate with stated assumptions**, resources, testing methods and a timeline check against team capacity.

### 5. Go-to-Market Strategy
- Positioning, revenue models, pricing with assumptions (anchored to competitor prices actually found), marketing strategy, first-customer plan, interview questions, sample outreach message and a **30/60/90-day action plan**.

### 6. Explainable Viability Score
- Fixed weighted formula applied identically to every idea; each factor rating needs a written reason.
- Verdict **Proceed / Improve / High Risk**, a plain-language "why this verdict", the factors holding the score down (with the points each fix would add), a confidence level and an AI-assisted-assessment disclaimer.

### 7. Idea-Aware Chat Advisor, History and Exports
- Chat advisor grounded in the selected idea's market, competitor, SWOT, risk, MVP and score results.
- Validation history with search, filters and side-by-side comparison of two ideas.
- Exports: **PDF, JSON, Markdown and CSV**.

### 8. Reliability and Speed
- Independent agents run in parallel; **Quick mode** (Settings) trades depth for speed.
- Clear error messages, a Re-run button, restart recovery for interrupted analyses, model fallback and rate-limit retries.

## System Architecture

### High-Level Multi-Tier Architecture

```
+---------------------------------------------------------------------------------------------------------------+
|                                         PRESENTATION LAYER (BROWSER)                                          |
|  +-------------------------+  +---------------------------+  +---------------------------------------------+ |
|  | Submit Idea & Progress  |  | Analysis Pages            |  | Dashboard, History, Chat Advisor, Settings  | |
|  | - sample autofill       |  | - Market / Competitors    |  | - Chart.js radar & category charts          | |
|  | - live agent progress   |  | - SWOT / Risks / MVP / GTM|  | - Compare two ideas, export downloads       | |
|  +-------------------------+  +---------------------------+  +---------------------------------------------+ |
+---------------------------------------------------+-----------------------------------------------------------+
                                                    | HTTP / JSON (Jinja2 templates, fetch API polling)
+---------------------------------------------------v-----------------------------------------------------------+
|                                        APPLICATION CONTROLLER LAYER                                           |
|  Flask app factory (app.py): authentication (Flask-Login), page routes, JSON APIs, settings, exports,         |
|  chat endpoint, template filters, error handlers                                                              |
+---------------------------------------------------+-----------------------------------------------------------+
                                                    |
+---------------------------------------------------v-----------------------------------------------------------+
|                                   ORCHESTRATION & INTELLIGENCE LAYER                                          |
|  +-------------------------------+   +---------------------------------------------------------------------+ |
|  | orchestration/pipeline.py     |   | services/                                                           | |
|  | - staged, parallel agents     |   | groq_service  search_service  evidence  sizing  scoring  quality    | |
|  | - progress + restart recovery |   | pdf_service                                                         | |
|  +-------------------------------+   +---------------------------------------------------------------------+ |
|  Agents: Idea Extractor | Market Analyzer | Competitor | SWOT & Risk | MVP | GTM | Advisor | Report Generator   |
+---------------------------------------------------+-----------------------------------------------------------+
                                                    |
+---------------------------------------------------v-----------------------------------------------------------+
|                                          PERSISTENCE & STORAGE LAYER                                          |
|  SQLite (startup_validator.db): users, startup_ideas, analysis_results, competitors, chat_messages,           |
|  validation_reports                                  |  exports/ (generated PDF reports)                      |
+---------------------------------------------------+-----------------------------------------------------------+
                                                    |
+---------------------------------------------------v-----------------------------------------------------------+
|                                            EXTERNAL SERVICES                                                  |
|  Groq LLM API  |  Tavily (optional) / DDGS / DuckDuckGo HTML  |  Wikipedia  |  competitor websites (fetched)   |
+---------------------------------------------------------------------------------------------------------------+
```

### Eight-Agent Validation Pipeline

```
 Stage 1                 Stage 2                         Stage 3                         Stage 4
+---------------+   +--------------------+   +---------------------------+   +----------------------+
| Idea Extractor|-->| Market Analyzer    |-->| SWOT & Risk Agent         |-->| Startup Advisor      |
| (structure    |   | Competitor Agent   |   | MVP Recommender           |   | Report Generator     |
|  + queries)   |   |  (run in parallel) |   | GTM Strategist (parallel) |   |  (run in parallel)   |
+---------------+   +--------------------+   +---------------------------+   +----------------------+
                                  Results stored as JSON in SQLite after every agent
```

| # | Agent | Job |
|---|-------|-----|
| 1 | Idea Extractor | Structures the idea and writes idea-specific search queries |
| 2 | Market Analyzer | Research, published figures, CAGR, trends, segments, TAM/SAM/SOM assumptions |
| 3 | Competitor Agent | Finds candidates, verifies official websites, compares features/pricing, computes gaps |
| 4 | SWOT & Risk | Idea-specific SWOT and a scored risk register |
| 5 | MVP Recommender | Feature tiers, build order, roadmap, cost estimate, timeline check |
| 6 | GTM Strategist | Positioning, pricing, marketing, first customers, 30/60/90-day plan |
| 7 | Startup Advisor | Advisory brief and idea-aware chat answers (brief skipped in Quick mode) |
| 8 | Report Generator | Computes scores and confidence, writes the narrative, builds the PDF |

### Web Research & Competitor Verification Pipeline

```
Idea -> search queries -> Tavily (if keyed) -> ddgs -> DuckDuckGo HTML   (+ Wikipedia background)
                               |
                      normalised sources (S1, S2 ...) with publisher reliability
                               |
        +----------------------+------------------------+
        v                                               v
 regex extraction of market-size / CAGR           candidate competitor names
 figures from retrieved text                      -> find official site -> fetch page
        |                                         -> page must mention the company
        v                                         -> read products / features / prices
 model judges relevance (numbers unchanged)              |
        v                                                v
 "Sourced" figures with links              verified competitors (others listed as excluded)
```

### Market Sizing Mathematical Model (TAM / SAM / SOM)

```
Bottom-up :  TAM = customers x annual revenue per customer
             SAM = TAM x share reachable with this product, geography and channel
             SOM = SAM x share a new entrant can win in about 3 years

Top-down  :  TAM = market size published in a retrieved source (sourced, with link, year, scope)
             SAM = TAM x share of that market this product can serve
             SOM = SAM x share a new entrant can win in about 3 years
```
Low and high cases use each assumption's low/high value together. A level shows **Insufficient data** only when it cannot be calculated responsibly.

CAGR is shown only when a retrieved, reasonably reliable source states a growth rate; two or more publishers give a value or range.

### Standardized Viability Scoring Mathematical Model

```
Viability = 0.25 x Market Demand
          + 0.20 x Competitive Position
          + 0.20 x Execution Feasibility
          + 0.15 x Business Model
          + 0.20 x Risk Resistance
```

| Dimension | Weight | Computed from |
|-----------|--------|---------------|
| Market Demand | 25% | Average of 1-5 ratings (demand, growth, accessibility, computed evidence strength) x 20 |
| Competitive Position | 20% | Differentiation, headroom against incumbents, ease of switching |
| Execution Feasibility | 20% | Technical feasibility, data/integration dependency, time to first version |
| Business Model | 15% | Customer reachability, willingness to pay, unit economics |
| Risk Resistance | 20% | 100 - composite risk score |

Every factor needs a rating of 1-5 **and** a written reason (at least 20 characters). Unscorable dimensions are dropped and the remaining weights renormalised (at least three
are needed). Market Demand is capped at 70 when no sourced market data was found.

| Verdict | Score | Meaning |
|---------|-------|---------|
| **Proceed** | >= 75 | Strong validation; move to customer interviews and an MVP |
| **Improve** | 55 - 74 | Promising but needs work on the weakest factors before committing |
| **High Risk** | < 55 | Resolve the biggest weaknesses before investing, or reconsider |

Confidence (High / Medium / Low) depends on the number of sourced figures, verified competitors, sources and scored dimensions. The AI supplies ratings with reasons;
**the weighted arithmetic, caps and thresholds are fixed in code**, so scores are consistent and reproducible.

### Risk Scoring Model

```
Risk points = Impact (1-10) x Likelihood (1-10)            Severity: High >= 56 | Medium 30-55 | Low < 30
Composite risk = 0.6 x average(top three risks) + 0.4 x average(all risks)
Risk Resistance = 100 - Composite risk
```

### Database Entity Relationship Overview

```
users (1) ------< startup_ideas (1) ------< analysis_results   (one JSON result per agent per idea)
                         |
                         +------< competitors          (verified companies, details JSON)
                         +------< chat_messages        (advisor conversation)
                         +------- validation_reports   (summary, scores, PDF name, full report JSON)
```

## Technology Stack
- **Backend:** Python 3.10+, Flask 3.x, Jinja2, Flask-Login, Werkzeug (password hashing), python-dotenv
- **AI & Research:** Groq chat-completions API (default `openai/gpt-oss-120b`, fallback `openai/gpt-oss-20b`), Tavily (optional), DDGS / DuckDuckGo, Wikipedia, Requests
- **Parsing & Evidence:** BeautifulSoup4, lxml, regular expressions (market figures, CAGR, prices)
- **Database:** SQLite3 with a transaction-safe connection manager
- **Reports:** ReportLab (PDF), Markdown, JSON and CSV exports
- **Frontend:** HTML5, CSS3, vanilla JavaScript, Bootstrap 5.3, Bootstrap Icons, Chart.js 4
- **Concurrency:** `concurrent.futures.ThreadPoolExecutor`, `threading`
- **Testing:** `unittest` (128 offline tests with a fake LLM and fake search)

## Project Documentation
- **Team viva guide:** [`docs/Team_Viva_Guide.pdf`](docs/Team_Viva_Guide.pdf) - architecture, technology, scoring, two validated examples and viva questions.
- **Environment template:** [`.env.example`](.env.example) - every setting with comments.
- **Diagnostics:** `scripts/diagnose.py` checks packages, `.env`, database, Groq, web search and website access in one command.

## Quick Start Guide

### 1. Clone the repository
```bash
git clone <your-repository-url>
cd startup-idea-validator-ai
```

### 2. Create a virtual environment
```powershell
# Windows
py -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure your keys
```bash
copy .env.example .env        # macOS/Linux: cp .env.example .env
```
Edit `.env` (no quotes, no spaces):

| Variable | Needed? | Notes |
|---|---|---|
| `GROQ_API_KEY` | **Yes** | Free key from https://console.groq.com |
| `TAVILY_API_KEY` | Recommended | Free tier (about 1,000 searches/month); without it the app falls back to free DuckDuckGo search |
| `GROQ_MODEL` | No | Default `openai/gpt-oss-120b`; retired model names are migrated automatically |
| `ANALYSIS_MODE` | No | `standard` (about 2 min) or `quick` (aims for about 1 min, shallower) |

Keys typed on the Settings page are held in memory only; keep permanent keys in `.env`.

### 5. Check your setup, then run
```bash
python scripts/diagnose.py
python run.py
```
Open http://127.0.0.1:5000, register (or use the demo account), click **New Idea**, and wait for the agents to finish.

## API Route Catalog

| Method | Endpoint | Description | Access |
|--------|----------|-------------|--------|
| GET | `/` | Landing / redirect | Public |
| GET / POST | `/login` | Sign in | Public |
| GET / POST | `/register` | Create an account | Public |
| GET | `/demo-login` | Sign in with the seeded demo account | Public |
| GET | `/logout` | End the session | Authenticated |
| GET | `/dashboard` | Founder Validation Hub | Authenticated |
| GET / POST | `/submit` | Submit a startup idea and start validation | Authenticated |
| GET | `/history` | Browse, filter and compare validated ideas | Authenticated |
| GET | `/advisor` | General startup advisor | Authenticated |
| GET | `/idea/<id>/market` | Market research, TAM/SAM/SOM, sources | Owner |
| GET | `/idea/<id>/competitors` | Verified competitors, matrix, gaps | Owner |
| GET | `/idea/<id>/swot` | SWOT analysis | Owner |
| GET | `/idea/<id>/risks` | Risk register and heat-map | Owner |
| GET | `/idea/<id>/mvp` | MVP scope, cost estimate, roadmap | Owner |
| GET | `/idea/<id>/gtm` | Go-to-market and 30/60/90-day plan | Owner |
| GET | `/idea/<id>/report` | Executive report and score breakdown | Owner |
| GET | `/idea/<id>/chat` | Idea-aware chat advisor | Owner |
| POST | `/api/idea/<id>/run` | Start or re-run the validation pipeline | Owner |
| GET | `/api/idea/<id>/status` | Live pipeline progress (polled by the browser) | Owner |
| POST | `/api/idea/<id>/chat` | Send a chat message | Owner |
| POST | `/api/idea/<id>/chat/clear` | Clear the conversation | Owner |
| POST | `/api/idea/<id>/delete` | Delete an idea and its results | Owner |
| GET | `/api/export/<id>/pdf` | Download the PDF report | Owner |
| GET | `/api/export/<id>/json` | Download the full report as JSON | Owner |
| GET | `/api/export/<id>/markdown` | Download the report as Markdown | Owner |
| GET | `/api/export/<id>/csv` | Download key results as CSV | Owner |
| GET | `/api/ideas/compare` | Compare two validated ideas | Authenticated |
| GET / POST | `/settings` | Profile, API keys, model, analysis speed | Authenticated |
| GET | `/api/settings/test-groq` | Test the Groq connection | Authenticated |
| GET | `/api/settings/test-tavily` | Test the Tavily connection | Authenticated |
| POST | `/api/sample/load` | Load sample ideas and analyse them | Authenticated |

## Automated Testing & Quality Assurance

Run the full suite (offline; uses a fake LLM and fake search, so no API keys are needed):

```bash
python -m unittest discover -s tests
# or
python tests/run_all_tests.py
```

| Test file | Tests | What it covers |
|-----------|-------|----------------|
| `test_core.py` | 32 | Groq client, JSON repair, search, evidence extraction, sizing, scoring, quality guard |
| `test_sizing_fix.py` | 22 | TAM/SAM/SOM with messy model output, top-down sizing, retry, pages and exports |
| `test_app.py` | 16 | Every page, link, export, chat, settings and error path |
| `test_pipeline.py` | 15 | Full pipeline on several ideas, failure modes, restart recovery |
| `test_improvements.py` | 15 | Consistency checks, honest labels, MVP cost/timeline, competitor gaps, chat digest |
| `test_agents.py` | 9 | Each agent in isolation and without a key |
| `test_routes.py` | 9 | Authentication and route behaviour |
| `test_any_idea.py` | 4 | Six unrelated industries, no cross-idea leakage, no hard-coded idea names |
| `test_db.py` | 3 | Database models |
| `test_orchestrator.py` | 2 | Pipeline orchestration |
| `test_pdf.py` | 1 | PDF generation |
| **Total** | **128** | |

The tests use synthetic fixtures (fictional companies on `.example` domains) defined in `tests/fakes.py`; they check the application's logic, **not** live market accuracy.
To check real research quality with your own keys:

```bash
python scripts/verify_three_ideas.py          # SkillBridge AI and FinWise AI (add --all for three more industries)
```

## Default System Credentials

| Role | Email | Password | Landing page |
|------|-------|----------|--------------|
| Demo user (seeded) | `demo@startupvalidator.com` | `password123` | Dashboard (`/dashboard`) |

Change or remove the demo account, and set a strong `SECRET_KEY`, before any public deployment.

## Project Directory Structure

```
startup-idea-validator-ai/
├── agents/                         # The eight AI agents
│   ├── base_agent.py               # Shared JSON calls, quality retry, error handling
│   ├── idea_extractor.py           # Agent 1: structure the idea, create search queries
│   ├── market_analyzer.py          # Agent 2: market research, figures, TAM/SAM/SOM inputs
│   ├── competitor_agent.py         # Agent 3: verified competitors, matrix, gaps
│   ├── swot_risk_agent.py          # Agent 4: SWOT and scored risk register
│   ├── mvp_recommender.py          # Agent 5: MVP features, cost estimate, roadmap
│   ├── gtm_strategist.py           # Agent 6: pricing, marketing, 30/60/90-day plan
│   ├── startup_advisor.py          # Agent 7: advisory brief and chat answers
│   └── report_generator.py         # Agent 8: scores, verdict, narrative, PDF
├── orchestration/
│   ├── pipeline.py                 # Staged parallel execution, progress, recovery
│   └── context_store.py            # Shared context between agents
├── services/
│   ├── groq_service.py             # Groq client: retries, fallback model, JSON parser
│   ├── search_service.py           # Tavily / DDGS / DuckDuckGo / Wikipedia search
│   ├── evidence.py                 # Source reliability, page fetching, figure/price extraction
│   ├── sizing.py                   # TAM/SAM/SOM and CAGR calculations
│   ├── scoring.py                  # Risk scoring, weighted viability score, verdicts
│   ├── quality.py                  # Generic-text guard
│   └── pdf_service.py              # ReportLab PDF report
├── database/
│   ├── db.py                       # SQLite connection, schema, migrations, demo seed
│   └── models.py                   # User, StartupIdea, AnalysisResult, Competitor, ChatMessage, ValidationReport
├── templates/                      # Jinja2 pages (auth/, dashboard/, partials/, base.html, error.html)
├── static/                         # css/, js/ (app, dashboard, submission, chat), img/logo.svg
├── tests/                          # 128 offline tests + fakes.py fixtures
├── scripts/
│   ├── diagnose.py                 # One-command setup checker
│   └── verify_three_ideas.py       # Live research-quality check
├── docs/
│   └── Team_Viva_Guide.pdf         # Viva preparation guide
├── exports/                        # Generated PDF reports
├── app.py                          # Flask application factory, routes and APIs
├── config.py                       # Settings, model registry, limits
├── run.py                          # Entry point
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment template
└── README.md
```

## Troubleshooting
- **A step shows "Failed" or the analysis is slow:** Groq's free tier allows about 8,000 tokens per minute and 200,000 per day **per model**, and a full analysis sends roughly 30,000-45,000 tokens. The app keeps each request inside the minute budget, spreads calls over the main and fallback model, waits when a limit is hit, and retries a transiently failed step once automatically. Hover the red *Failed* badge for the reason. If you see "daily token limit", wait for the reset time shown, use **Quick mode**, or add billing in the Groq console (then set `GROQ_TPM_LIMIT=0`).
- **"Groq rate limit reached":** wait a minute and press **Re-run analysis**.
- **Few or no web sources:** DuckDuckGo can rate-limit scrapers; add a free `TAVILY_API_KEY` or retry later.
- **"Insufficient data" for a market figure:** no retrieved source stated it, or the assumptions could not be calculated responsibly; the page shows the reason. Re-run after adding a Tavily key.
- **Competitor table empty:** no candidate website could be fetched and verified (deliberate; nothing is guessed). Try a more specific idea description.
- **Analysis interrupted by a restart:** the idea is marked failed; press **Re-run analysis**.
- **Old report looks different:** reports created by an older version keep their stored content until re-run.
- Run `python scripts/diagnose.py` to test packages, keys, search and website access.

## Limitations & Responsible Use
- Web search is not exhaustive; published market reports differ in year, region and definition, so figures can disagree.
- TAM/SAM/SOM can be calculated correctly and still rest on weak assumptions; the MVP cost estimate is an AI estimate, not a quote.
- LLM output can be wrong or biased; labels, sources and checks reduce but do not remove this risk.
- The competitor list may be incomplete and is not a legal audit.
- The viability score is a heuristic, not a statistically validated prediction. Validate key assumptions with real customers before investing.
- SQLite suits a local prototype; production use would need a managed database, backups and stronger secret management.

## License
This project was developed for academic purposes. Add a `LICENSE` file (for example MIT) to state the terms for reuse before publishing the repository.
