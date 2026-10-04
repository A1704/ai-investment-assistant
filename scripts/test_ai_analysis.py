import sqlite3
import tempfile
from pathlib import Path

import investment_assistant.database as database
from investment_assistant.ai_analysis import generate_portfolio_analysis
from investment_assistant.news import get_company_news
from investment_assistant.portfolio import calculate_portfolio_valuation


def main():
    original_path = database.DB_PATH

    with tempfile.TemporaryDirectory() as directory:
        database.DB_PATH = Path(directory) / "test.db"

        try:
            # Create a small test portfolio.
            connection = sqlite3.connect(database.DB_PATH)

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    transaction_type TEXT NOT NULL CHECK(
                        transaction_type IN ('BUY', 'SELL')
                    ),
                    quantity REAL NOT NULL CHECK(quantity > 0),
                    price REAL NOT NULL CHECK(price >= 0),
                    transaction_date TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            connection.commit()
            connection.close()

            # Add test transaction data.
            from investment_assistant.portfolio import add_transaction

            add_transaction(
                symbol="TEST",
                company_name="Test Company",
                transaction_type="BUY",
                quantity=10,
                price=100,
                transaction_date="2026-01-01",
            )

            add_transaction(
                symbol="TEST",
                company_name="Test Company",
                transaction_type="SELL",
                quantity=4,
                price=130,
                transaction_date="2026-02-01",
            )

            # Use a test price instead of requesting a real market quote.
            portfolio = calculate_portfolio_valuation(
                price_overrides={
                    "TEST": 120
                }
            )

            # No external news lookup for the TEST symbol.
            news = {
                "TEST": []
            }

            # Send portfolio + news to Gemini.
            analysis = generate_portfolio_analysis(
                portfolio,
                news,
            )

            print("\n")
            print("=" * 70)
            print("              AI PORTFOLIO ANALYSIS")
            print("=" * 70)
            print()
            print(analysis)
            print()
            print("=" * 70)

        finally:
            database.DB_PATH = original_path


if __name__ == "__main__":
    main()