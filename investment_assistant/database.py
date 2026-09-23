import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "investment_assistant.db"


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    _initialize_tables(conn)
    return conn


def _initialize_tables(conn):
    conn.execute("""
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
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS opening_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            company_name TEXT NOT NULL,
            quantity REAL NOT NULL CHECK(quantity > 0),
            average_cost REAL NOT NULL CHECK(average_cost >= 0),
            invested_amount REAL NOT NULL CHECK(invested_amount >= 0),
            purchase_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def initialize_database():
    conn = get_connection()
    conn.close()


if __name__ == "__main__":
    initialize_database()
    print(f"Database initialized: {DB_PATH}")