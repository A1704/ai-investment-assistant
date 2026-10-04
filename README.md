# AI Investment Assistant

An AI-powered personal investment assistant built with Python, Flask, SQLite, Gemini, market data, news aggregation, voice interaction, portfolio analytics, and automated email briefings.

The project is designed as an **informational decision-support tool** for understanding and tracking an investment portfolio. It does not execute trades or provide automated buy/sell recommendations.

---

## Overview

The AI Investment Assistant combines portfolio tracking, market information, AI analysis, historical analytics, risk intelligence, alerts, and conversational interaction in one application.

The system can:

- Track portfolio holdings and transactions
- Calculate cost basis and realized/unrealized P&L
- Retrieve current market prices
- Collect relevant financial news
- Generate AI-assisted portfolio analysis
- Answer portfolio questions conversationally
- Accept voice questions and read answers aloud
- Perform a limited set of safe computer-control actions
- Detect significant portfolio changes
- Analyze concentration and diversification
- Attribute portfolio changes to individual holdings
- Analyze historical portfolio performance
- Track investment goals and user-provided benchmarks
- Evaluate data quality and reliability
- Generate automated daily portfolio briefings

---

## Architecture

```text
                    ┌─────────────────────┐
                    │   User / Dashboard  │
                    └──────────┬──────────┘
                               │
                ┌──────────────┴──────────────┐
                │                             │
        ┌───────▼────────┐           ┌────────▼────────┐
        │ AI Assistant   │           │ Voice Interface │
        └───────┬────────┘           └────────┬────────┘
                │                             │
                └──────────────┬──────────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Portfolio Engine    │
                    └──────────┬──────────┘
                               │
             ┌─────────────────┼─────────────────┐
             │                 │                 │
      ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
      │ SQLite DB   │   │ Market Data │   │    News     │
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
        │ Analytics  │   │   Alerts    │  │  Briefing │
        └────────────┘   └─────────────┘  └─────┬─────┘
                                                │
                                           ┌────▼────┐
                                           │  Gmail   │
                                           └─────────┘
