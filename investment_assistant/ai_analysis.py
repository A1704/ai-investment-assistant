import warnings

warnings.filterwarnings(
    "ignore",
    category=Warning,
    module="requests",
)

import os
import time

import requests
from dotenv import load_dotenv


load_dotenv()


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)


def generate_portfolio_analysis(portfolio, news):
    """
    Send portfolio data and relevant news to Gemini.

    Python remains responsible for numerical calculations.
    Gemini only analyzes and explains the supplied information.
    """

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured."
        )

    portfolio_data = []

    for symbol, data in portfolio["positions"].items():
        portfolio_data.append(
            {
                "symbol": symbol,
                "quantity": data["quantity"],
                "average_buy_price": data["average_buy_price"],
                "current_price": data["current_price"],
                "invested_amount": data["invested_amount"],
                "current_value": data["current_value"],
                "unrealized_pnl": data["unrealized_pnl"],
                "return_percent": data["return_percent"],
            }
        )

    news_data = []

    for symbol, articles in news.items():
        for article in articles:
            news_data.append(
                {
                    "symbol": symbol,
                    "title": article["title"],
                    "source": article["source"],
                    "published": article["published"],
                }
            )

    prompt = f"""
You are a personal investment information assistant.

Analyze the portfolio data and recent news provided below.

IMPORTANT RULES:
1. Do not invent numbers, prices, news, or facts.
2. Use only the portfolio data and news provided.
3. Do not give direct buy, sell, or hold recommendations.
4. Do not predict future prices or returns.
5. Clearly distinguish facts from general financial context.
6. Explain everything in simple language.
7. Point out which holdings currently have positive or negative
   unrealized P&L.
8. Use the news only when it is relevant to a specific holding.
9. Do not assume that a news event will definitely affect future prices.
10. Do not claim that a particular investment is good or bad.
11. Mention when the available news is limited or uncertain.

Portfolio data:

{portfolio_data}

Portfolio totals:

Total invested: ₹{portfolio["total_invested"]:.2f}
Current value: ₹{portfolio["total_current_value"]:.2f}
Unrealized P&L: ₹{portfolio["total_unrealized_pnl"]:.2f}
Total return: {portfolio["total_return_percent"]:.2f}%

Recent relevant news:

{news_data}

Create a concise portfolio briefing with these sections:

1. Portfolio Overview
2. Holding-by-Holding Summary
3. Relevant News
4. Portfolio Concentration
5. Key Things to Monitor
6. Important Disclaimer

For the Relevant News section:
- Group news by portfolio holding.
- Briefly explain why each relevant headline matters.
- Do not speculate about future price movements.
- Do not turn news into a buy/sell recommendation.

Keep the explanation clear enough for a beginner investor.
"""

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ]
    }

    headers = {
        "Content-Type": "application/json"
    }

    max_attempts = 3

    for attempt in range(1, max_attempts + 1):

        response = requests.post(
            GEMINI_URL,
            headers=headers,
            params={"key": GEMINI_API_KEY},
            json=payload,
            timeout=30,
        )

        if response.status_code == 503:

            if attempt < max_attempts:

                wait_seconds = 2 ** attempt

                print(
                    f"Gemini temporarily unavailable. "
                    f"Retrying in {wait_seconds} seconds..."
                )

                time.sleep(wait_seconds)
                continue

        response.raise_for_status()
        break

    data = response.json()

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]

    except (KeyError, IndexError, TypeError) as exc:

        raise RuntimeError(
            f"Unexpected Gemini response: {data}"
        ) from exc