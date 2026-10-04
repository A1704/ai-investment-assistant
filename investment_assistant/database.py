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

    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date TEXT NOT NULL UNIQUE,
            total_invested REAL NOT NULL,
            total_current_value REAL NOT NULL,
            total_realized_pnl REAL NOT NULL,
            total_unrealized_pnl REAL NOT NULL,
            total_pnl REAL NOT NULL,
            total_return_percent REAL NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            holding_snapshot_json TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_name TEXT NOT NULL,
            target_type TEXT NOT NULL CHECK(
                target_type IN (
                    'PORTFOLIO_VALUE',
                    'ABSOLUTE_PNL',
                    'RETURN_PERCENT'
                )
            ),
            target_value REAL NOT NULL CHECK(
                target_value >= 0
                AND target_value <= 1.7976931348623157e308
            ),
            target_date TEXT,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK(
                is_active IN (0, 1)
            ),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_benchmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            benchmark_name TEXT NOT NULL,
            benchmark_symbol TEXT,
            benchmark_type TEXT NOT NULL CHECK(
                benchmark_type IN (
                    'USER_PROVIDED_RETURN',
                    'USER_PROVIDED_VALUE'
                )
            ),
            is_active INTEGER NOT NULL DEFAULT 1 CHECK(
                is_active IN (0, 1)
            ),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_benchmark_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            benchmark_id INTEGER NOT NULL,
            observation_date TEXT NOT NULL,
            value REAL NOT NULL CHECK(
                value >= -100
                AND value <= 1.7976931348623157e308
            ),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(benchmark_id, observation_date),
            FOREIGN KEY(benchmark_id)
                REFERENCES portfolio_benchmarks(id)
        )
    """)

    snapshot_columns = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(portfolio_snapshots)"
        ).fetchall()
    }
    if "holding_snapshot_json" not in snapshot_columns:
        conn.execute(
            "ALTER TABLE portfolio_snapshots "
            "ADD COLUMN holding_snapshot_json TEXT"
        )

    conn.commit()


def initialize_database():
    conn = get_connection()
    conn.close()


if __name__ == "__main__":
    initialize_database()
    print(f"Database initialized: {DB_PATH}")