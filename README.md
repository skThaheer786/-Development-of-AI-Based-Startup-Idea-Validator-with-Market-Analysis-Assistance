
# Development of AI-Based Startup Idea Validator with Market Analysis Assistance

**Python 3.10+ | Flask 3.x | Multi-Agent AI | Groq LLM | SQLite | Market Research | Automated Testing**

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Framework](https://img.shields.io/badge/Framework-Flask%203.x-lightgrey)
![AI](https://img.shields.io/badge/AI-Multi--Agent%20System-orange)
![LLM](https://img.shields.io/badge/LLM-Groq-purple)
![Database](https://img.shields.io/badge/Database-SQLite-green)
![Frontend](https://img.shields.io/badge/Frontend-HTML%20%7C%20CSS%20%7C%20JavaScript-blue)
![Testing](https://img.shields.io/badge/Testing-Unittest-brightgreen)

An intelligent, AI-powered startup validation platform designed to help students, aspiring entrepreneurs, and first-time founders evaluate their business ideas before investing time, effort, and money.

The system uses a **multi-agent AI architecture** consisting of eight specialized agents to analyse startup ideas through market research, competitor verification, SWOT analysis, risk assessment, MVP planning, go-to-market strategy, and startup advisory.

Developed using Python Flask, Groq Large Language Models, SQLite, external web research services, Bootstrap 5, Chart.js, and ReportLab.

The platform generates structured startup validation results, an explainable viability score, actionable recommendations, and downloadable reports.

> **Important:** The system provides AI-assisted decision support. Its recommendations and viability scores are not guarantees of business success.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Key Features](#key-features)
3. [System Architecture](#system-architecture)
   - [High-Level System Architecture](#high-level-system-architecture)
   - [Multi-Agent Architecture](#multi-agent-architecture)
   - [Agent Execution Workflow](#agent-execution-workflow)
   - [Web Research Architecture](#web-research-architecture)
   - [Market Sizing Model](#market-sizing-model)
   - [Startup Viability Scoring Model](#startup-viability-scoring-model)
   - [Risk Assessment Model](#risk-assessment-model)
   - [Database Architecture](#database-architecture)
4. [Technology Stack](#technology-stack)
5. [System Requirements](#system-requirements)
6. [Installation and Configuration](#installation-and-configuration)
7. [Application Workflow](#application-workflow)
8. [API Route Documentation](#api-route-documentation)
9. [Database Management](#database-management)
10. [Automated Testing](#automated-testing)
11. [Project Directory Structure](#project-directory-structure)
12. [Troubleshooting](#troubleshooting)
13. [Limitations](#limitations)
14. [Future Enhancements](#future-enhancements)
15. [License](#license)

---

## 1. Project Overview

The AI-Based Startup Idea Validator is a web-based application that evaluates startup ideas through AI-driven analysis and external market research.

Many students and first-time entrepreneurs have business ideas but lack the knowledge and resources required to determine whether those ideas are practical, financially feasible, and suitable for the current market.

The proposed system addresses this challenge by providing a centralized platform that evaluates different aspects of a startup idea.

The user submits a startup idea with relevant details. The system processes the information through multiple AI agents, each responsible for a specific validation task.

The final output includes:

- Startup idea analysis
- Market demand and industry trends
- TAM, SAM, and SOM market estimates
- Competitor identification and comparison
- SWOT analysis
- Business risk assessment
- Minimum Viable Product (MVP) recommendations
- Go-to-market strategy
- Startup feasibility advice
- Overall viability score
- Downloadable validation report

The application supports different startup domains rather than being restricted to a particular industry.

## 2. Key Features

### 2.1 AI-Based Startup Idea Extraction

- Accepts startup ideas from different industries.
- Identifies the problem, proposed solution, target customers, industry, and key features.
- Converts unstructured user input into structured information.
- Generates idea-specific research queries.

### 2.2 Market Research and Analysis

- Investigates the relevant industry and market.
- Identifies market demand, customer segments, trends, and opportunities.
- Collects external research sources.
- Extracts published market-size and CAGR information where available.
- Provides TAM, SAM, and SOM estimates with assumptions.

### 2.3 Competitor Analysis

- Identifies potential direct, indirect, and emerging competitors.
- Searches for competitor websites.
- Verifies official websites before including competitor information.
- Compares available products, features, and pricing.
- Identifies possible market gaps and differentiation opportunities.

### 2.4 SWOT Analysis

- Evaluates business strengths and weaknesses.
- Identifies external opportunities and threats.
- Provides idea-specific explanations.
- Uses research information and AI analysis to support findings.

### 2.5 Risk Assessment

Evaluates different categories of startup risks:

- Technical risk
- Financial risk
- Market risk
- Operational risk
- Legal and regulatory risk
- Competitive risk
- Customer adoption risk
- Privacy-related risk, where relevant

Each risk includes its impact, likelihood, severity, and mitigation suggestions.

### 2.6 MVP Recommendation

- Recommends essential product features.
- Classifies features into Must, Should, Could, and Deferred.
- Suggests implementation order.
- Provides a development roadmap.
- Estimates development costs using stated assumptions.
- Recommends resources and testing methods.

### 2.7 Go-to-Market Strategy

- Recommends product positioning.
- Suggests possible revenue models.
- Analyses pricing opportunities.
- Provides marketing and customer acquisition strategies.
- Suggests first-customer approaches.
- Generates a 30/60/90-day action plan.

### 2.8 Startup Advisory and Reporting

- Provides startup-specific recommendations.
- Includes an idea-aware chat advisor.
- Generates an overall viability score.
- Displays analysis through dashboard visualizations.
- Maintains validation history.
- Supports comparison of two validated ideas.
- Generates downloadable PDF, JSON, Markdown, and CSV reports.

---

# 3. System Architecture

The application follows a modular, multi-tier architecture that separates the user interface, application processing, AI orchestration, specialized agents, external integrations, and database operations.

The central orchestration layer coordinates the execution of specialized agents and manages shared information throughout the validation process.

## 3.1 High-Level System Architecture

```text
+=====================================================================+
|                       PRESENTATION LAYER                            |
|                                                                     |
|  +----------------+  +----------------+  +-----------------------+ |
|  | Authentication |  | Startup Idea   |  | Dashboard & Results   | |
|  | Login/Register |  | Submission     |  | History / Settings    | |
|  +----------------+  +----------------+  +-----------------------+ |
|                                                                     |
|              HTML5 | CSS3 | JavaScript | Bootstrap 5                |
+==================================+==================================+
                                   |
                                   | HTTP Requests / Responses
                                   |
+==================================v==================================+
|                     APPLICATION LAYER                               |
|                                                                     |
|                         Flask Application                          |
|                                                                     |
|  +----------------+  +----------------+  +-----------------------+ |
|  | Route Handling |  | Authentication |  | API & Request         | |
|  |                |  | & Sessions     |  | Management            | |
|  +----------------+  +----------------+  +-----------------------+ |
|                                                                     |
|                       app.py / config.py                            |
+==================================+==================================+
                                   |
                                   |
+==================================v==================================+
|                  ORCHESTRATION LAYER                                |
|                                                                     |
|  +----------------------------+  +-------------------------------+ |
|  | Pipeline Orchestrator      |  | Shared Context Store          | |
|  |                            |  |                               | |
|  | Agent Coordination         |  | Intermediate Results          | |
|  | Execution Management       |  | Pipeline State                 | |
|  | Progress Tracking          |  | Agent Information              | |
|  +----------------------------+  +-------------------------------+ |
|                                                                     |
|                 orchestration/pipeline.py                           |
|                 orchestration/context_store.py                       |
+==================================+==================================+
                                   |
                                   |
+==================================v==================================+
|                  MULTI-AGENT INTELLIGENCE LAYER                     |
|                                                                     |
|  +------------------+       +----------------------+                |
|  | 1. Idea Extractor|------>| 2. Market Analyzer   |                |
|  +------------------+       +----------------------+                |
|                                      |                              |
|                                      v                              |
|  +------------------+       +----------------------+                |
|  | 3. Competitor    |       | 4. SWOT & Risk       |                |
|  |    Agent         |       |    Agent             |                |
|  +------------------+       +----------------------+                |
|                                      |                              |
|                                      v                              |
|  +------------------+       +----------------------+                |
|  | 5. MVP           |       | 6. GTM Strategist    |                |
|  |    Recommender   |       |                      |                |
|  +------------------+       +----------------------+                |
|                                      |                              |
|                                      v                              |
|  +------------------+       +----------------------+                |
|  | 7. Startup       |       | 8. Report Generator  |                |
|  |    Advisor       |       |                      |                |
|  +------------------+       +----------------------+                |
+==================================+==================================+
                                   |
                                   |
+==================================v==================================+
|                  EXTERNAL INTEGRATION LAYER                         |
|                                                                     |
|  +------------------+  +------------------+  +-------------------+ |
|  | Groq LLM API     |  | Tavily Search    |  | DuckDuckGo Search | |
|  | AI Processing    |  | Web Research     |  | Web Research      | |
|  +------------------+  +------------------+  +-------------------+ |
|                                                                     |
|                    Wikipedia / Website Fetching                    |
+==================================+==================================+
                                   |
                                   |
+==================================v==================================+
|                    DATA & STORAGE LAYER                             |
|                                                                     |
|                       SQLite Database                              |
|                                                                     |
|  +-------------+  +----------------+  +--------------------------+ |
|  | User Records|  | Startup Ideas  |  | Analysis Results         | |
|  +-------------+  +----------------+  +--------------------------+ |
|  | Competitors |  | Chat Messages  |  | Validation Reports       | |
|  +-------------+  +----------------+  +--------------------------+ |
|                                                                     |
+=====================================================================+
                                   |
                                   v
+=====================================================================+
|                         OUTPUT LAYER                                |
|                                                                     |
|  Dashboard Results | Charts | Recommendations | PDF Reports         |
|                                                                     |
+=====================================================================+
```

### Architecture Layer Description

| Layer | Components | Responsibility |
|---|---|---|
| Presentation Layer | HTML, CSS, JavaScript, Bootstrap | User interaction and visualization |
| Application Layer | Flask, routes, authentication | Handles requests and application logic |
| Orchestration Layer | Pipeline, Context Store | Coordinates AI agent execution |
| Intelligence Layer | Eight specialized agents | Performs startup idea validation |
| Integration Layer | Groq, Tavily, DuckDuckGo, Wikipedia | AI processing and external research |
| Data Layer | SQLite | Stores application and validation data |
| Output Layer | Dashboard, Chart.js, ReportLab | Displays results and generates reports |

## 3.2 Multi-Agent Architecture

The application uses eight specialized AI agents. Each agent is responsible for a specific part of the startup validation process.

The agents communicate through a shared pipeline context managed by the orchestration layer.

```text
                  +---------------------------+
                  |       USER INPUT           |
                  |     Startup Idea           |
                  +-------------+-------------+
                                |
                                v
                  +---------------------------+
                  |     IDEA EXTRACTOR         |
                  | Problem / Solution         |
                  | Customers / Industry       |
                  +-------------+-------------+
                                |
                                v
                  +---------------------------+
                  |      SHARED CONTEXT        |
                  | Structured Idea Data       |
                  +-------------+-------------+
                                |
                 +--------------+--------------+
                 |                             |
                 v                             v
       +--------------------+       +----------------------+
       | MARKET ANALYZER    |       | COMPETITOR AGENT     |
       |                    |       |                      |
       | Market Demand      |       | Competitor Research  |
       | Industry Trends    |       | Features / Pricing   |
       | TAM / SAM / SOM    |       | Market Gaps          |
       +---------+----------+       +----------+-----------+
                 |                             |
                 +--------------+--------------+
                                |
                                v
                  +---------------------------+
                  |       SHARED CONTEXT       |
                  |   Research Information    |
                  +-------------+-------------+
                                |
             +------------------+------------------+
             |                  |                  |
             v                  v                  v
     +---------------+  +---------------+  +----------------+
     | SWOT & RISK   |  | MVP           |  | GTM            |
     | AGENT         |  | RECOMMENDER   |  | STRATEGIST     |
     +-------+-------+  +-------+-------+  +--------+-------+
             |                  |                   |
             +------------------+-------------------+
                                |
                                v
                  +---------------------------+
                  |     STARTUP ADVISOR        |
                  | Feasibility & Guidance     |
                  +-------------+-------------+
                                |
                                v
                  +---------------------------+
                  |     REPORT GENERATOR       |
                  | Score / Verdict / Report   |
                  +-------------+-------------+
                                |
                                v
                  +---------------------------+
                  |     FINAL RESULTS          |
                  | Dashboard / PDF / Exports  |
                  +---------------------------+
```

### AI Agent Responsibilities

| Agent | Module | Main Responsibility |
|---|---|---|
| Agent 1 | `idea_extractor.py` | Extracts structured information from the submitted idea |
| Agent 2 | `market_analyzer.py` | Analyses market demand, industry trends, and market sizing |
| Agent 3 | `competitor_agent.py` | Identifies and verifies competitors |
| Agent 4 | `swot_risk_agent.py` | Performs SWOT analysis and evaluates business risks |
| Agent 5 | `mvp_recommender.py` | Recommends MVP features, development order, and cost estimates |
| Agent 6 | `gtm_strategist.py` | Develops positioning, pricing, marketing, and launch strategies |
| Agent 7 | `startup_advisor.py` | Provides startup guidance and advisory responses |
| Agent 8 | `report_generator.py` | Consolidates results and generates viability assessment and reports |

## 3.3 Agent Execution Workflow

The pipeline orchestrator manages the execution stages and shares information between agents.

```text
+---------------------------+
|       IDEA SUBMISSION     |
+-------------+-------------+
              |
              v
+---------------------------+
|       IDEA EXTRACTION     |
|       Structured Data     |
+-------------+-------------+
              |
              v
+---------------------------+
|    MARKET & COMPETITOR    |
|         ANALYSIS          |
|      Parallel Tasks       |
+-------------+-------------+
              |
              v
+---------------------------+
|      SWOT & RISK          |
|      MVP PLANNING         |
|      GTM STRATEGY         |
|      Parallel Tasks       |
+-------------+-------------+
              |
              v
+---------------------------+
|      STARTUP ADVISOR      |
+-------------+-------------+
              |
              v
+---------------------------+
|      REPORT GENERATION    |
|      Score & Verdict      |
+-------------+-------------+
              |
              v
+---------------------------+
|      STORE RESULTS        |
|       SQLite Database     |
+-------------+-------------+
              |
              v
+---------------------------+
|      DISPLAY RESULTS      |
|      DASHBOARD / PDF      |
+---------------------------+
```

The pipeline uses a shared context store to maintain intermediate outputs. Independent tasks can be executed concurrently using Python's `concurrent.futures` functionality where supported by the pipeline.

## 3.4 Web Research Architecture

The application uses external research services to gather information relevant to the submitted startup idea.

```text
                +-------------------------+
                |       STARTUP IDEA      |
                +------------+------------+
                             |
                             v
                +-------------------------+
                |   IDEA-SPECIFIC QUERY   |
                |       GENERATION        |
                +------------+------------+
                             |
                             v
                +-------------------------+
                |     SEARCH SERVICE      |
                +------------+------------+
                             |
            +----------------+----------------+
            |                |                |
            v                v                v
     +-------------+  +-------------+  +-------------+
     | Tavily API  |  | DuckDuckGo  |  | Wikipedia   |
     |             |  | Search      |  |             |
     +------+------+  +------+------+  +------+------+
            |                |                |
            +----------------+----------------+
                             |
                             v
                +-------------------------+
                |   NORMALIZE SOURCES     |
                |   AND EXTRACT EVIDENCE  |
                +------------+------------+
                             |
              +--------------+--------------+
              |                             |
              v                             v
     +-------------------+        +----------------------+
     | MARKET FIGURES    |        | COMPETITOR CANDIDATES|
     | CAGR / Trends     |        | Official Websites    |
     +---------+---------+        +----------+-----------+
              |                             |
              +--------------+--------------+
                             |
                             v
                +-------------------------+
                |  VERIFIED RESEARCH DATA |
                +------------+------------+
                             |
                             v
                +-------------------------+
                |    AI ANALYSIS AGENTS   |
                +-------------------------+
```

Research results are processed and organized before being used by the analysis agents.

The application distinguishes between sourced information, AI analysis, AI assumptions, and computed values to improve transparency.

## 3.5 Market Sizing Model

The system provides three market-sizing levels:

- **TAM (Total Addressable Market):** Total potential market opportunity.
- **SAM (Serviceable Available Market):** Portion of the market that the proposed product can serve.
- **SOM (Serviceable Obtainable Market):** Realistic portion of the serviceable market that a new business may capture.

### Bottom-Up Approach

```text
TAM = Potential Customers × Annual Revenue per Customer

SAM = TAM × Reachable Market Share

SOM = SAM × Estimated Obtainable Market Share
```

### Top-Down Approach

```text
TAM = Published Market Size from a Research Source

SAM = TAM × Relevant Market Segment Share

SOM = SAM × Estimated Obtainable Market Share
```

The system uses available published figures and clearly identified assumptions. Python performs the calculations rather than relying on the language model to perform arithmetic.

When reliable information is unavailable, the system reports insufficient data instead of presenting unsupported market figures.

## 3.6 Startup Viability Scoring Model

The platform uses a weighted scoring approach to evaluate the overall viability of a startup idea.

```text
Viability Score =

    (0.25 × Market Demand)
  + (0.20 × Competitive Position)
  + (0.20 × Execution Feasibility)
  + (0.15 × Business Model)
  + (0.20 × Risk Resistance)
```

### Scoring Parameters

| Parameter | Weight | Evaluation |
|---|---:|---|
| Market Demand | 25% | Customer demand, market growth, accessibility, and evidence |
| Competitive Position | 20% | Differentiation, competition, and market opportunities |
| Execution Feasibility | 20% | Technical feasibility, resources, and implementation |
| Business Model | 15% | Revenue opportunities, pricing, and customer reachability |
| Risk Resistance | 20% | Ability to manage identified business risks |

### Validation Verdict

| Score | Verdict | Interpretation |
|---|---|---|
| 75–100 | Proceed | Strong validation; proceed with customer research and MVP planning |
| 55–74 | Improve | Promising idea that needs improvements |
| Below 55 | High Risk | Significant weaknesses should be addressed before investing |

The score is an assessment based on the available information and defined calculation rules. It should not be treated as a statistically proven prediction of business success.

## 3.7 Risk Assessment Model

The system evaluates startup risks based on their impact and likelihood.

```text
Risk Points = Impact × Likelihood
```

Both impact and likelihood are evaluated on a scale of 1 to 10.

### Risk Severity

| Risk Points | Severity |
|---|---|
| 56 and above | High |
| 30–55 | Medium |
| Below 30 | Low |

The composite risk score is calculated using the highest risks and the overall risk register.

```text
Composite Risk =
    (0.6 × Average of Top Three Risks)
  + (0.4 × Average of All Risks)

Risk Resistance = 100 - Composite Risk
```

The risk assessment supports the overall viability scoring process.

## 3.8 Database Architecture

The application uses SQLite for persistent storage of user information, startup ideas, analysis results, competitors, conversations, and validation reports.

### Database Relationship Overview

```text
                  +----------------------+
                  |        USERS         |
                  |----------------------|
                  | id                   |
                  | username             |
                  | email                |
                  | password_hash        |
                  +----------+-----------+
                             |
                             | 1
                             |
                             | N
                  +----------v-----------+
                  |    STARTUP IDEAS     |
                  |----------------------|
                  | id                   |
                  | user_id              |
                  | title                |
                  | description          |
                  | industry              |
                  +----------+-----------+
                             |
              +--------------+-------------------+
              |              |                   |
              | 1            | 1                 | 1
              |              |                   |
              | N            | N                 | N
       +------v------+ +-----v---------+ +-------v----------+
       | ANALYSIS    | | COMPETITORS   | | CHAT MESSAGES    |
       | RESULTS     | |               | |                  |
       +-------------+ +---------------+ +------------------+
                             |
                             |
                             | 1
                             |
                             | N
                  +----------v-----------+
                  | VALIDATION REPORTS   |
                  |----------------------|
                  | id                   |
                  | startup_idea_id      |
                  | summary              |
                  | scores               |
                  | report_data          |
                  +----------------------+
```

The database schema and connection management are implemented through the `database/` module.

---

# 4. Technology Stack

| Category | Technologies |
|---|---|
| Programming Language | Python 3.10+ |
| Backend Framework | Flask 3.x |
| Frontend | HTML5, CSS3, JavaScript |
| UI Framework | Bootstrap 5.3 |
| Icons | Bootstrap Icons |
| AI Model Integration | Groq API |
| Language Models | GPT-OSS model family |
| Web Research | Tavily, DDGS / DuckDuckGo, Wikipedia |
| Database | SQLite |
| Data Processing | Python standard libraries, JSON |
| Visualization | Chart.js 4 |
| PDF Generation | ReportLab |
| Concurrency | concurrent.futures, threading |
| Testing | Python unittest |
| Development Environment | Visual Studio Code |
| Version Control | Git and GitHub |

---

# 5. System Requirements

## 5.1 Software Requirements

- Operating System: Windows 10 / Windows 11
- Programming Language: Python 3.10 or above
- Backend Framework: Flask 3.x
- Web Browser: Google Chrome, Microsoft Edge, or Firefox
- IDE: Visual Studio Code
- Database: SQLite
- Internet Connection: Required for external AI and research services

## 5.2 Hardware Requirements

| Component | Minimum Requirement |
|---|---|
| Processor | Dual-core processor |
| RAM | 4 GB |
| Storage | 1 GB available space |
| Internet | Stable internet connection |
| Display | Standard desktop or laptop display |

---

# 6. Installation and Configuration

Follow these steps to run the project locally.

## 6.1 Clone the Repository

```bash
git clone https://github.com/varsh120925-cmd/AI-Startup-Idea-Validator.git
```

Navigate to the project directory:

```bash
cd AI-Startup-Idea-Validator
```

## 6.2 Create a Virtual Environment

For Windows:

```bash
python -m venv venv
```

Activate the environment:

```bash
venv\Scripts\activate
```

For macOS / Linux:

```bash
python3 -m venv venv
source venv/bin/activate
```

## 6.3 Install Dependencies

```bash
pip install -r requirements.txt
```

## 6.4 Configure Environment Variables

Create a `.env` file using the provided template:

```bash
copy .env.example .env
```

Open the `.env` file and configure the required API keys.

```env
GROQ_API_KEY=your_groq_api_key
TAVILY_API_KEY=your_tavily_api_key

SECRET_KEY=your_secret_key
GROQ_MODEL=openai/gpt-oss-120b
```

**API Configuration:**

| Variable | Description |
|---|---|
| `GROQ_API_KEY` | Required for language-model processing |
| `TAVILY_API_KEY` | Optional web research integration |
| `SECRET_KEY` | Flask session security |
| `GROQ_MODEL` | Language model selection |

Obtain a Groq API key from:

https://console.groq.com

Tavily API:

https://tavily.com

Do not upload your actual `.env` file or API keys to GitHub.

## 6.5 Run the Application

Start the Flask application:

```bash
python run.py
```

Open the following address in your browser:

```text
http://127.0.0.1:5000
```

Register a new account or sign in to access the startup validation dashboard.

---

# 7. Application Workflow

The application follows a structured workflow from user registration to final startup validation.

### Step 1: User Authentication

The user registers or logs into the application using the authentication interface.

### Step 2: Startup Idea Submission

The user enters the startup title, industry, target customers, and idea description.

### Step 3: AI-Based Idea Extraction

The Idea Extractor Agent processes the submitted information and identifies the key components of the startup idea.

### Step 4: Market and Competitor Research

The Market Analyzer and Competitor Agent investigate the industry, market demand, competitors, and available market information.

### Step 5: Business Evaluation

The SWOT & Risk Agent evaluates the strengths, weaknesses, opportunities, threats, and possible risks.

### Step 6: MVP Planning

The MVP Recommender suggests the essential features, development priorities, roadmap, and estimated costs.

### Step 7: Go-to-Market Planning

The GTM Strategist prepares recommendations for positioning, pricing, marketing, and customer acquisition.

### Step 8: Startup Advisory

The Startup Advisor provides guidance based on the startup analysis.

### Step 9: Report Generation

The Report Generator consolidates the analysis and prepares the viability score, verdict, and downloadable report.

### Step 10: Results and History

The user can view the results through the dashboard, access previous validations, compare ideas, and export reports.

---

# 8. API Route Documentation

The Flask application provides routes for authentication, dashboard navigation, idea validation, analysis results, chat, settings, and report exports.

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Landing page or redirect |
| GET / POST | `/login` | User login |
| GET / POST | `/register` | User registration |
| GET | `/demo-login` | Demo account login |
| GET | `/logout` | User logout |
| GET | `/dashboard` | Main dashboard |
| GET / POST | `/submit` | Submit startup idea |
| GET | `/history` | Validation history |
| GET | `/advisor` | Startup advisor |
| GET | `/idea/<id>/market` | Market analysis |
| GET | `/idea/<id>/competitors` | Competitor analysis |
| GET | `/idea/<id>/swot` | SWOT analysis |
| GET | `/idea/<id>/risks` | Risk assessment |
| GET | `/idea/<id>/mvp` | MVP recommendations |
| GET | `/idea/<id>/gtm` | Go-to-market strategy |
| GET | `/idea/<id>/report` | Validation report |
| GET | `/idea/<id>/chat` | Idea-aware chat |
| POST | `/api/idea/<id>/run` | Start or rerun validation |
| GET | `/api/idea/<id>/status` | Check pipeline progress |
| POST | `/api/idea/<id>/chat` | Send advisor message |
| POST | `/api/idea/<id>/chat/clear` | Clear chat history |
| POST | `/api/idea/<id>/delete` | Delete startup idea |
| GET | `/api/export/<id>/pdf` | Download PDF report |
| GET | `/api/export/<id>/json` | Export JSON report |
| GET | `/api/export/<id>/markdown` | Export Markdown report |
| GET | `/api/export/<id>/csv` | Export CSV report |
| GET | `/api/ideas/compare` | Compare startup ideas |
| GET / POST | `/settings` | Application settings |
| GET | `/api/settings/test-groq` | Test Groq connection |
| GET | `/api/settings/test-tavily` | Test Tavily connection |
| POST | `/api/sample/load` | Load sample startup ideas |

---

# 9. Database Management

The application uses SQLite to maintain persistent application data.

The database module is responsible for connection handling, schema management, and database operations.

Main database entities include:

- Users
- Startup Ideas
- Analysis Results
- Competitors
- Chat Messages
- Validation Reports

The database implementation is available in:

```text
database/
├── __init__.py
├── db.py
└── models.py
```

The database file is created and managed by the application according to its configuration.

---

# 10. Automated Testing

The project includes automated tests using Python's built-in `unittest` framework.

The test suite covers application routes, database operations, AI agents, pipeline execution, report generation, and core services.

## 10.1 Execute Tests

Run the complete test suite:

```bash
python -m unittest discover -s tests
```

Alternatively:

```bash
python tests/run_all_tests.py
```

## 10.2 Test Modules

| Test File | Testing Area |
|---|---|
| `test_core.py` | Core services and processing |
| `test_sizing_fix.py` | Market sizing calculations |
| `test_app.py` | Application functionality |
| `test_pipeline.py` | Agent pipeline execution |
| `test_improvements.py` | Analysis quality and improvements |
| `test_agents.py` | Individual AI agent functionality |
| `test_routes.py` | Application routes |
| `test_any_idea.py` | Validation across different startup ideas |
| `test_db.py` | Database operations |
| `test_orchestrator.py` | Pipeline orchestration |
| `test_pdf.py` | PDF generation |
| `test_token_limits.py` | Token limit handling |

The automated tests use test fixtures and simulated external responses where appropriate. They validate application logic and do not establish the real-world accuracy of market research results.

---

# 11. Project Directory Structure

```text
AI-Startup-Idea-Validator/
│
├── agents/
│   ├── __init__.py
│   ├── base_agent.py
│   ├── idea_extractor.py
│   ├── market_analyzer.py
│   ├── competitor_agent.py
│   ├── swot_risk_agent.py
│   ├── mvp_recommender.py
│   ├── gtm_strategist.py
│   ├── startup_advisor.py
│   └── report_generator.py
│
├── orchestration/
│   ├── __init__.py
│   ├── pipeline.py
│   └── context_store.py
│
├── services/
│   ├── __init__.py
│   ├── groq_service.py
│   ├── search_service.py
│   ├── evidence.py
│   ├── sizing.py
│   ├── scoring.py
│   ├── quality.py
│   └── pdf_service.py
│
├── database/
│   ├── __init__.py
│   ├── db.py
│   └── models.py
│
├── templates/
│   ├── auth/
│   │   ├── login.html
│   │   └── register.html
│   │
│   ├── dashboard/
│   │   ├── index.html
│   │   ├── submit.html
│   │   ├── market.html
│   │   ├── competitors.html
│   │   ├── swot.html
│   │   ├── risks.html
│   │   ├── mvp.html
│   │   ├── gtm.html
│   │   ├── report.html
│   │   ├── chat.html
│   │   ├── history.html
│   │   └── settings.html
│   │
│   ├── partials/
│   ├── base.html
│   └── error.html
│
├── static/
│   ├── css/
│   │   ├── style.css
│   │   └── dashboard.css
│   │
│   ├── js/
│   │   ├── app.js
│   │   ├── dashboard.js
│   │   ├── submission.js
│   │   └── chat.js
│   │
│   └── img/
│       └── logo.svg
│
├── tests/
│   ├── __init__.py
│   ├── fakes.py
│   ├── run_all_tests.py
│   ├── test_core.py
│   ├── test_agents.py
│   ├── test_pipeline.py
│   ├── test_routes.py
│   ├── test_app.py
│   ├── test_db.py
│   ├── test_pdf.py
│   ├── test_any_idea.py
│   ├── test_orchestrator.py
│   ├── test_improvements.py
│   ├── test_sizing_fix.py
│   └── test_token_limits.py
│
├── scripts/
│   ├── diagnose.py
│   └── verify_three_ideas.py
│
├── docs/
│   └── Team_Viva_Guide.pdf
│
├── exports/
│
├── app.py
├── config.py
├── run.py
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

# 12. Troubleshooting

### Groq API Error

- Check whether the Groq API key is correctly configured.
- Verify that the selected model is available.
- Check API rate limits.
- Retry the analysis after the limit resets.

### Web Research Not Returning Results

- Check the internet connection.
- Verify the Tavily API key if configured.
- Retry the search if the external service is temporarily unavailable.
- DuckDuckGo search may be rate-limited.

### Analysis Takes Longer Than Expected

- The application uses multiple AI agents and external research requests.
- Processing time depends on API response times, search availability, and the amount of information retrieved.
- Use Quick mode when available to reduce analysis depth.

### Database Error

- Check that the application has permission to create and access its SQLite database.
- Ensure the database directory is available.
- Restart the application after resolving the issue.

### PDF Report Not Downloading

- Check the ReportLab installation.
- Verify that the exports directory is accessible.
- Retry report generation.

---

# 13. Limitations

- Market research depends on publicly available web information.
- Some industries may have limited published market data.
- Competitor information depends on the availability and accessibility of official websites.
- AI-generated recommendations may require manual verification.
- Market sizing estimates depend on the quality of available data and assumptions.
- Viability scores are decision-support indicators, not guarantees of startup success.
- SQLite is suitable for the current application but may need replacement with a managed database for larger production deployments.

---

# 14. Future Enhancements

- Integration with additional market research providers.
- Advanced market trend visualization.
- More detailed financial forecasting.
- Improved competitor intelligence and comparison.
- Additional business feasibility evaluation methods.
- Enhanced report customization.
- Cloud deployment and scalable database integration.
- Expanded industry-specific startup evaluation.

---

# 15. License

This project is developed for academic and educational purposes.

A separate `LICENSE` file should be included in the repository to define the terms of distribution and reuse.
