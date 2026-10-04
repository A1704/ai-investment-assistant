import sqlite3
import tempfile
from pathlib import Path

import investment_assistant.database as database

from investment_assistant.briefing import (
    build_briefing,
    build_html_email,
)
from investment_assistant.portfolio import add_transaction


def main():
    original_path = database.DB_PATH

    with tempfile.TemporaryDirectory() as directory:
        database.DB_PATH = Path(directory) / "test.db"

        try:
            # Create the required transactions table.
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

            # Create isolated test portfolio.
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

            print("Building investment briefing...")

            portfolio, news, analysis = build_briefing(
                price_overrides={
                    "TEST": 120
                },
                news_overrides={
                    "TEST": []
                },
            )

            html = build_html_email(
                portfolio,
                analysis,
            )

            print("\n" + "=" * 70)
            print("INVESTMENT BRIEFING GENERATED")
            print("=" * 70)

            print(
                f"\nRemaining Cost Basis: "
                f"₹{portfolio['total_invested']:,.2f}"
            )

            print(
                f"Current Value: "
                f"₹{portfolio['total_current_value']:,.2f}"
            )

            print(
                f"Realized P&L: "
                f"₹{portfolio['total_realized_pnl']:,.2f}"
            )

            print(
                f"Unrealized P&L: "
                f"₹{portfolio['total_unrealized_pnl']:,.2f}"
            )

            print(
                f"Total P&L: "
                f"₹{portfolio['total_pnl']:,.2f}"
            )

            print(
                f"Unrealized Return: "
                f"{portfolio['total_return_percent']:.2f}%"
            )

            print("\nHTML email length:", len(html))

            # Verify important V2 values.
            assert portfolio["total_invested"] == 600
            assert portfolio["total_current_value"] == 720
            assert portfolio["total_realized_pnl"] == 120
            assert portfolio["total_unrealized_pnl"] == 120
            assert portfolio["total_pnl"] == 240

            # Verify important V2 fields appear in the email.
            assert "Remaining Cost Basis" in html
            assert "Realized P&L" in html
            assert "Unrealized P&L" in html
            assert "Total P&L" in html

            print("\nV2 portfolio calculations: PASSED")
            print("V2 HTML email fields: PASSED")

            print("\nNews collected:")

            for symbol, articles in news.items():
                print(f"  {symbol}: {len(articles)} articles")

            print("\nAI analysis generated: YES")
            print("=" * 70)

        finally:
            database.DB_PATH = original_path


if __name__ == "__main__":
    main()