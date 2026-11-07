# AI Investment Assistant

An AI-powered personal investment decision-support assistant built with Python, Flask, SQLite, Google Gemini, market data ingestion, financial news aggregation, browser-native voice interaction, portfolio risk analytics, and automated daily email briefings.

The project is designed strictly as an **informational decision-support tool** for understanding and tracking an investment portfolio. It does not execute trades, manage funds, or provide automated financial advice.

---

## Overview

The AI Investment Assistant bridges deterministic financial accounting and qualitative generative AI. Rather than delegating numerical calculations to a large language model, the application enforces a strict architectural boundary:

* **Python and SQLite** deterministically handle all transaction ledgers, weighted-average cost basis accounting, realized/unrealized P&L, performance attribution, drawdowns, and portfolio risk metrics.
* **Google Gemini (LLM)** receives pre-computed, verified portfolio data and curated news headlines solely to provide natural-language synthesis, conversational Q&A, and executive daily briefings without mathematical hallucinations.

---

## Architecture & Technology Stack

```text
                    ┌─────────────────────┐
                    │   User / Dashboard  │
                    └──────────┬──────────┘
                               │
                ┌──────────────┴──────────────┐
                │                             │
        ┌───────▼────────┐           ┌────────▼────────┐
        │  AI Assistant  │           │ Voice Interface │
        └───────┬────────┘           └────────┬────────┘
                │                             │
                └──────────────┬──────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Portfolio Engine   │
                    └──────────┬──────────┘
                               │
             ┌─────────────────┼─────────────────┐
             │                 │                 │
      ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
      │  SQLite DB  │   │ Market Data │   │    News     │
      └─────────────┘   └─────────────┘   └─────────────┘
                               │
                         ┌─────▼─────┐
                         │  Gemini   │
                         │ AI Layer  │
                         └─────┬─────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
        ┌─────▼─────┐   ┌──────▼──────┐  ┌─────▼─────┐
        │ Analytics │   │   Alerts    │  │ Briefing  │
        └───────────┘   └─────────────┘  └─────┬─────┘
                                               │
                                          ┌────▼────┐
                                          │  Gmail  │
                                          └─────────┘
```

### Core Technologies

* **Language & Runtime:** Python 3.12
* **Web Framework:** Flask (REST endpoints & Jinja2 server-rendered dashboard)
* **Database:** SQLite 3 (relational schema with check constraints and foreign keys)
* **Generative AI:** Google Gemini API (`gemini-3.1-flash-lite` via direct REST requests with exponential backoff)
* **Market Data:** Yahoo Finance chart endpoint with retry handling and fallback
* **News Aggregator:** RSS parsing via `feedparser` with automated headline filtering
* **Voice Interaction:** Web Speech API (`SpeechRecognition` for voice input, `SpeechSynthesis` for audio playback)
* **Automated Delivery:** SMTP over SSL for responsive HTML email briefings
* **Testing:** `pytest` (comprehensive 253-test automated test suite)

---

## Key Features

1. **Portfolio Accounting & Ledger Management:**
   * Tracks multi-asset holdings, purchase history, and sales.
   * Calculates weighted-average cost basis per asset.
   * Realizes gains/losses upon sale while preventing short selling (`quantity <= available_quantity`).
   * Distinguishes realized, unrealized, and total P&L in Indian Rupees (₹).

2. **Market Data & News Ingestion:**
   * Fetches latest market prices with automated retries.
   * Curates company news from Google News RSS.
   * Filters speculative clickbait, price predictions, and opinion articles using a 26-keyword exclusion filter to ensure factual inputs for AI analysis.

3. **Risk Intelligence & Performance Attribution:**
   * Computes asset concentration, single-holding exposure, and portfolio allocation weights.
   * Decomposes portfolio valuation changes into net capital flows vs. market price movements.
   * Tracks peak portfolio value (high-water mark), all-time lows, and maximum drawdowns.

4. **Conversational Assistant & Safe System Actions:**
   * Answers natural-language questions about holdings, performance, and risk based strictly on verified application state.
   * Deterministic routing for exact historical snapshots and goal evaluations to bypass LLM latency and hallucination risks.
   * Automated secret scrubbing regex to redact API keys and passwords from chat exchanges.
   * Allowlist-controlled computer actions (launching Google, Chrome, YouTube, or scoped web search) with strict IP/URL safety validation.

5. **Goals & Benchmark Intelligence:**
   * Tracks user-defined portfolio targets (total valuation, absolute P&L, or percentage returns).
   * Compares portfolio trajectory against user-provided external benchmark observations.

6. **Automated Daily Briefings:**
   * Generates formatted daily summaries containing portfolio changes, top movers, alerts, news, and AI commentary.
   * Dispatches responsive HTML briefings via automated email using Gmail SMTP.

---

## Installation & Setup

### 1. Prerequisites

* Python 3.10 or higher (Python 3.12 recommended)
* Git

### 2. Clone the Repository

```bash
git clone https://github.com/A1704/ai-investment-assistant.git
cd ai-investment-assistant
```

### 3. Create and Activate a Virtual Environment

**On Windows:**
```cmd
python -m venv .venv
.venv\Scripts\activate
```

**On macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Environment Variables Configuration

Copy the `.env.example` file to create your local `.env`:

```bash
cp .env.example .env
```
*(On Windows Command Prompt, use `copy .env.example .env`)*

Open `.env` in your text editor and configure the variables:

```env
# Google Gemini API Configuration (Required for AI Analysis and Assistant)
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-3.1-flash-lite

# Flask Application Security (Recommended)
FLASK_SECRET_KEY=generate_a_random_secret_key_here

# Daily Portfolio Briefing Email Notifications (Optional - Gmail SMTP)
GMAIL_ADDRESS=your_email@gmail.com
GMAIL_APP_PASSWORD=your_16_character_app_password
RECIPIENT_EMAIL=recipient_email@example.com
```

> **Note:** If `GEMINI_API_KEY` is not provided, the core dashboard, portfolio calculations, market data, and risk analytics will continue to function normally; AI conversational answers will gracefully display an informative fallback message.

---

## Launching the Application

### 1. Web Dashboard

To start the interactive web application:

**On Windows:**
```cmd
set PYTHONPATH=.
python -m dashboard.app
```

**On macOS / Linux:**
```bash
PYTHONPATH=. python3 -m dashboard.app
```

Once running, open your web browser and navigate to:
```text
http://127.0.0.1:5000
```

### 2. Automated Daily Briefing (CLI / Scheduled)

To run the daily briefing generator and send the summary email:

**On Windows:**
```cmd
run_daily_briefing.bat
```
*(Or execute directly with `set PYTHONPATH=. && python scripts/daily_briefing.py`)*

---

## Running the Test Suite

The repository includes a comprehensive automated test suite covering portfolio accounting, risk calculations, computer control security, prompt guardrails, and data quality audits.

Run all tests with:

```bash
python -m pytest tests/
```

Expected output:
```text
============================= 253 passed in ~5s =============================
```

---

## Current Scope & Limitations

This project was built as an MVP decision-support system. To maintain transparency, the following technical limitations should be noted:

1. **Curated Reference Portfolio:** The market data and news ingestion modules currently support a defined reference universe of Indian securities (`COCHINSHIP`, `HINDZINC`, and `SILVERBEES`). Expanding this requires mapping additional tickers in `market_data.py` and `news.py`.
2. **Third-Party Market Feed:** Market quotes are fetched via Yahoo Finance's chart endpoint with user-agent headers. It is suitable for personal tracking, but is not an exchange-certified real-time market data feed.
3. **Local Single-User Architecture:** The SQLite database is designed for local, single-user operation. It does not currently feature multi-tenant user authentication or session isolation.
4. **Informational Only (Non-Custodial):** The system has no broker API integrations and does not place or execute market orders. It is designed solely for monitoring, analytics, and personal decision support.

---

## License

This project is developed for educational and portfolio demonstration purposes.
