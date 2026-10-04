import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import investment_assistant.database as database
from investment_assistant.portfolio import (
    add_opening_position,
    add_transaction,
    calculate_positions,
    calculate_portfolio_valuation,
    get_opening_positions,
    get_transactions,
    save_portfolio_snapshot as _save_portfolio_snapshot,
    get_portfolio_snapshots,
    record_current_portfolio_snapshot,
    get_portfolio_performance_history,
    calculate_snapshot_changes,
    calculate_max_drawdown,
    calculate_portfolio_allocation,
    calculate_portfolio_concentration,
    get_portfolio_analytics_summary,
    get_historical_performance_summary,
    get_dashboard_data,
)


def save_portfolio_snapshot(*args, **kwargs):
    """Use an explicit empty test holding set for aggregate-only fixtures."""
    kwargs.setdefault("holding_positions", {})
    return _save_portfolio_snapshot(*args, **kwargs)


def transaction(
    transaction_id,
    symbol,
    transaction_type,
    quantity,
    price,
):
    return (
        transaction_id,
        symbol,
        f"{symbol} Company",
        transaction_type,
        quantity,
        price,
        "2026-01-01",
    )


class CalculatePositionsTests(unittest.TestCase):

    def test_opening_position_is_included(self):
        opening_positions = [
            (1, "ABC", "ABC Company", 10, 100, 1000, None),
        ]

        positions = calculate_positions(
            [],
            opening_positions,
        )

        self.assertEqual(
            positions["ABC"]["total_buy_quantity"],
            10,
        )

        self.assertEqual(
            positions["ABC"]["total_buy_cost"],
            1000,
        )

        self.assertEqual(
            positions["ABC"]["current_quantity"],
            10,
        )

        self.assertAlmostEqual(
            positions["ABC"]["average_buy_price"],
            100,
        )

        self.assertAlmostEqual(
            positions["ABC"]["remaining_cost_basis"],
            1000,
        )

        self.assertAlmostEqual(
            positions["ABC"]["realized_pnl"],
            0,
        )

    def test_opening_position_combines_with_transactions(self):
        opening_positions = [
            (1, "ABC", "ABC Company", 10, 100, 1000, None),
        ]

        positions = calculate_positions(
            [
                transaction(
                    2,
                    "ABC",
                    "BUY",
                    5,
                    120,
                )
            ],
            opening_positions,
        )

        position = positions["ABC"]

        self.assertEqual(
            position["total_buy_quantity"],
            15,
        )

        self.assertEqual(
            position["total_buy_cost"],
            1600,
        )

        self.assertAlmostEqual(
            position["average_buy_price"],
            1600 / 15,
        )

        self.assertAlmostEqual(
            position["remaining_cost_basis"],
            1600,
        )

        self.assertEqual(
            position["current_quantity"],
            15,
        )

    def test_one_buy(self):
        positions = calculate_positions(
            [
                transaction(
                    1,
                    "ABC",
                    "BUY",
                    10,
                    100,
                )
            ]
        )

        position = positions["ABC"]

        self.assertEqual(
            position["total_buy_quantity"],
            10,
        )

        self.assertEqual(
            position["total_sell_quantity"],
            0,
        )

        self.assertEqual(
            position["current_quantity"],
            10,
        )

        self.assertEqual(
            position["total_buy_cost"],
            1000,
        )

        self.assertEqual(
            position["total_sell_proceeds"],
            0,
        )

        self.assertAlmostEqual(
            position["average_buy_price"],
            100,
        )

        self.assertAlmostEqual(
            position["remaining_cost_basis"],
            1000,
        )

        self.assertAlmostEqual(
            position["realized_pnl"],
            0,
        )

        self.assertFalse(
            position["is_zero_quantity"]
        )

    def test_multiple_buys_of_same_stock(self):
        positions = calculate_positions(
            [
                transaction(
                    1,
                    "ABC",
                    "BUY",
                    10,
                    100,
                ),
                transaction(
                    2,
                    "ABC",
                    "BUY",
                    5,
                    120,
                ),
            ]
        )

        position = positions["ABC"]

        self.assertEqual(
            position["total_buy_quantity"],
            15,
        )

        self.assertEqual(
            position["total_buy_cost"],
            1600,
        )

        self.assertAlmostEqual(
            position["average_buy_price"],
            1600 / 15,
        )

        self.assertAlmostEqual(
            position["remaining_cost_basis"],
            1600,
        )

        self.assertEqual(
            position["current_quantity"],
            15,
        )

    def test_buy_followed_by_sell_calculates_realized_pnl(self):
        positions = calculate_positions(
            [
                transaction(
                    1,
                    "ABC",
                    "BUY",
                    10,
                    100,
                ),
                transaction(
                    2,
                    "ABC",
                    "SELL",
                    4,
                    130,
                ),
            ]
        )

        position = positions["ABC"]

        self.assertEqual(
            position["total_sell_quantity"],
            4,
        )

        self.assertEqual(
            position["total_sell_proceeds"],
            520,
        )

        self.assertEqual(
            position["current_quantity"],
            6,
        )

        # Cost of 4 shares = 4 × ₹100 = ₹400
        # Sale proceeds = ₹520
        # Realized P&L = ₹120
        self.assertAlmostEqual(
            position["realized_pnl"],
            120,
        )

        self.assertAlmostEqual(
            position["remaining_cost_basis"],
            600,
        )

        self.assertAlmostEqual(
            position["average_buy_price"],
            100,
        )

    def test_multiple_buys_and_sells(self):
        positions = calculate_positions(
            [
                transaction(
                    1,
                    "ABC",
                    "BUY",
                    10,
                    100,
                ),
                transaction(
                    2,
                    "ABC",
                    "BUY",
                    5,
                    120,
                ),
                transaction(
                    3,
                    "ABC",
                    "SELL",
                    4,
                    130,
                ),
                transaction(
                    4,
                    "ABC",
                    "SELL",
                    3,
                    140,
                ),
            ]
        )

        position = positions["ABC"]

        self.assertEqual(
            position["total_buy_quantity"],
            15,
        )

        self.assertEqual(
            position["total_sell_quantity"],
            7,
        )

        self.assertEqual(
            position["current_quantity"],
            8,
        )

        self.assertEqual(
            position["total_buy_cost"],
            1600,
        )

        self.assertEqual(
            position["total_sell_proceeds"],
            940,
        )

        self.assertAlmostEqual(
            position["average_buy_price"],
            1600 / 15,
        )

        expected_remaining_cost = (
            8 * (1600 / 15)
        )

        self.assertAlmostEqual(
            position["remaining_cost_basis"],
            expected_remaining_cost,
        )

        expected_realized_pnl = (
            940 - (7 * (1600 / 15))
        )

        self.assertAlmostEqual(
            position["realized_pnl"],
            expected_realized_pnl,
        )

    def test_cannot_sell_more_than_available_quantity(self):
        with self.assertRaises(ValueError):

            calculate_positions(
                [
                    transaction(
                        1,
                        "ABC",
                        "BUY",
                        5,
                        100,
                    ),
                    transaction(
                        2,
                        "ABC",
                        "SELL",
                        6,
                        120,
                    ),
                ]
            )

    def test_complete_liquidation_calculates_realized_pnl(self):
        positions = calculate_positions(
            [
                transaction(
                    1,
                    "ABC",
                    "BUY",
                    10,
                    100,
                ),
                transaction(
                    2,
                    "ABC",
                    "SELL",
                    10,
                    130,
                ),
            ]
        )

        position = positions["ABC"]

        self.assertEqual(
            position["current_quantity"],
            0,
        )

        self.assertTrue(
            position["is_zero_quantity"]
        )

        self.assertEqual(
            position["remaining_cost_basis"],
            0,
        )

        self.assertIsNone(
            position["average_buy_price"]
        )

        self.assertAlmostEqual(
            position["realized_pnl"],
            300,
        )

    def test_opening_position_and_sell_uses_weighted_average_cost(self):
        opening_positions = [
            (
                1,
                "ABC",
                "ABC Company",
                10,
                100,
                1000,
                None,
            ),
        ]

        positions = calculate_positions(
            [
                transaction(
                    2,
                    "ABC",
                    "BUY",
                    10,
                    120,
                ),
                transaction(
                    3,
                    "ABC",
                    "SELL",
                    5,
                    150,
                ),
            ],
            opening_positions,
        )

        position = positions["ABC"]

        self.assertEqual(
            position["current_quantity"],
            15,
        )

        self.assertAlmostEqual(
            position["average_buy_price"],
            110,
        )

        self.assertAlmostEqual(
            position["remaining_cost_basis"],
            1650,
        )

        self.assertAlmostEqual(
            position["realized_pnl"],
            200,
        )

    def test_position_reduced_to_zero(self):
        positions = calculate_positions(
            [
                transaction(
                    1,
                    "ABC",
                    "BUY",
                    10,
                    100,
                ),
                transaction(
                    2,
                    "ABC",
                    "SELL",
                    10,
                    110,
                ),
            ]
        )

        self.assertEqual(
            positions["ABC"]["current_quantity"],
            0,
        )

        self.assertTrue(
            positions["ABC"]["is_zero_quantity"]
        )

        self.assertEqual(
            positions["ABC"]["remaining_cost_basis"],
            0,
        )

        self.assertAlmostEqual(
            positions["ABC"]["realized_pnl"],
            100,
        )

    def test_calculation_does_not_modify_database(self):
        connection = sqlite3.connect(
            database.DB_PATH
        )

        try:
            before = connection.execute(
                "SELECT COUNT(*) FROM transactions"
            ).fetchone()[0]

        finally:
            connection.close()

        calculate_positions(
            [
                transaction(
                    1,
                    "ABC",
                    "BUY",
                    10,
                    100,
                ),
                transaction(
                    2,
                    "ABC",
                    "SELL",
                    10,
                    110,
                ),
            ]
        )

        connection = sqlite3.connect(
            database.DB_PATH
        )

        try:
            after = connection.execute(
                "SELECT COUNT(*) FROM transactions"
            ).fetchone()[0]

        finally:
            connection.close()

        self.assertEqual(
            before,
            after,
        )

    def test_opening_position_can_have_unknown_purchase_date(self):
        original_path = database.DB_PATH

        with tempfile.TemporaryDirectory() as directory:

            database.DB_PATH = (
                Path(directory) / "test.db"
            )

            try:

                add_opening_position(
                    "ABC",
                    "ABC Company",
                    10,
                    100,
                    1000,
                )

                self.assertEqual(
                    get_opening_positions()[0][6],
                    None,
                )

            finally:

                database.DB_PATH = original_path
    def test_portfolio_valuation_with_realized_and_unrealized_pnl(self):
        original_path = database.DB_PATH

        with tempfile.TemporaryDirectory() as directory:
            database.DB_PATH = Path(directory) / "test.db"

            try:
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

                portfolio = calculate_portfolio_valuation(
                    price_overrides={"TEST": 120}
                )

                position = portfolio["positions"]["TEST"]

                self.assertEqual(
                    position["quantity"],
                    6,
                )

                self.assertEqual(
                    position["remaining_cost_basis"],
                    600,
                )

                self.assertEqual(
                    position["current_value"],
                    720,
                )

                self.assertEqual(
                    position["realized_pnl"],
                    120,
                )

                self.assertEqual(
                    position["unrealized_pnl"],
                    120,
                )

                self.assertEqual(
                    position["total_pnl"],
                    240,
                )

                self.assertEqual(
                    portfolio["total_invested"],
                    600,
                )

                self.assertEqual(
                    portfolio["total_current_value"],
                    720,
                )

                self.assertEqual(
                    portfolio["total_realized_pnl"],
                    120,
                )

                self.assertEqual(
                    portfolio["total_unrealized_pnl"],
                    120,
                )

                self.assertEqual(
                    portfolio["total_pnl"],
                    240,
                )

                self.assertEqual(
                    portfolio["total_return_percent"],
                    20,
                )

            finally:
                database.DB_PATH = original_path

    def test_valuation_preserves_market_quote_metadata(self):
        original_path = database.DB_PATH
        quote = {
            "price": 100,
            "market_timestamp": "2026-10-01T10:00:00+00:00",
            "retrieved_at": "2026-10-01T10:05:00+00:00",
            "source": "Synthetic provider fixture",
            "currency": "INR",
            "exchange": "NSE",
        }
        with tempfile.TemporaryDirectory() as directory:
            database.DB_PATH = Path(directory) / "test.db"
            try:
                add_transaction(
                    "TEST",
                    "Test Company",
                    "BUY",
                    1,
                    90,
                    "2026-01-01",
                )
                with patch(
                    "investment_assistant.portfolio.get_yahoo_quote",
                    return_value=quote,
                ):
                    result = calculate_portfolio_valuation()
                held = result["positions"]["TEST"]
                self.assertEqual(held["retrieved_at"], quote["retrieved_at"])
                self.assertEqual(held["market_timestamp"], quote["market_timestamp"])
                self.assertEqual(held["currency"], "INR")
                self.assertEqual(held["exchange"], "NSE")
            finally:
                database.DB_PATH = original_path

    def test_invalid_sell_is_rejected_before_database_insert(self):
        original_path = database.DB_PATH

        with tempfile.TemporaryDirectory() as directory:
            database.DB_PATH = Path(directory) / "test.db"

            try:
                add_transaction(
                    "TEST",
                    "Test Company",
                    "BUY",
                    5,
                    100,
                    "2026-09-28",
                )

                with self.assertRaises(ValueError):
                    add_transaction(
                        "TEST",
                        "Test Company",
                        "SELL",
                        6,
                        120,
                        "2026-09-28",
                    )

                transactions = get_transactions()

                self.assertEqual(len(transactions), 1)
                self.assertEqual(transactions[0][3], "BUY")
                self.assertEqual(transactions[0][4], 5)

            finally:
                database.DB_PATH = original_path


    def test_sell_unknown_stock_is_rejected_before_database_insert(self):
        original_path = database.DB_PATH

        with tempfile.TemporaryDirectory() as directory:
            database.DB_PATH = Path(directory) / "test.db"

            try:
                with self.assertRaises(ValueError):
                    add_transaction(
                        "UNKNOWN",
                        "Unknown Company",
                        "SELL",
                        1,
                        100,
                        "2026-09-28",
                    )

                transactions = get_transactions()

                self.assertEqual(len(transactions), 0)

            finally:
                database.DB_PATH = original_path

    def test_portfolio_snapshot_can_be_saved_and_retrieved(self):
        original_path = database.DB_PATH

        with tempfile.TemporaryDirectory() as directory:
            database.DB_PATH = Path(directory) / "test.db"

            try:
                save_portfolio_snapshot(
                    snapshot_date="2026-09-24",
                    total_invested=10000,
                    total_current_value=12000,
                    total_realized_pnl=500,
                    total_unrealized_pnl=1500,
                    total_pnl=2000,
                    total_return_percent=20,
                )

                snapshots = get_portfolio_snapshots()

                self.assertEqual(len(snapshots), 1)
                self.assertEqual(snapshots[0][1], "2026-09-24")
                self.assertEqual(snapshots[0][2], 10000)
                self.assertEqual(snapshots[0][3], 12000)
                self.assertEqual(snapshots[0][4], 500)
                self.assertEqual(snapshots[0][5], 1500)
                self.assertEqual(snapshots[0][6], 2000)
                self.assertEqual(snapshots[0][7], 20)

            finally:
                database.DB_PATH = original_path


    def test_duplicate_snapshot_date_updates_existing_snapshot(self):
        original_path = database.DB_PATH

        with tempfile.TemporaryDirectory() as directory:
            database.DB_PATH = Path(directory) / "test.db"

            try:
                save_portfolio_snapshot(
                    snapshot_date="2026-09-24",
                    total_invested=10000,
                    total_current_value=12000,
                    total_realized_pnl=500,
                    total_unrealized_pnl=1500,
                    total_pnl=2000,
                    total_return_percent=20,
                )

                save_portfolio_snapshot(
                    snapshot_date="2026-09-24",
                    total_invested=10000,
                    total_current_value=13000,
                    total_realized_pnl=500,
                    total_unrealized_pnl=2500,
                    total_pnl=3000,
                    total_return_percent=30,
                )

                snapshots = get_portfolio_snapshots()

                self.assertEqual(len(snapshots), 1)
                self.assertEqual(snapshots[0][3], 13000)
                self.assertEqual(snapshots[0][5], 2500)
                self.assertEqual(snapshots[0][6], 3000)
                self.assertEqual(snapshots[0][7], 30)

            finally:
                database.DB_PATH = original_path
    
    def test_current_portfolio_can_be_recorded_as_snapshot(self):
        original_path = database.DB_PATH

        with tempfile.TemporaryDirectory() as directory:
            database.DB_PATH = Path(directory) / "test.db"

            try:
                add_transaction(
                    "TEST",
                    "Test Company",
                    "BUY",
                    10,
                    100,
                    "2026-09-24",
                )

                portfolio = record_current_portfolio_snapshot(
                    snapshot_date="2026-09-24",
                    price_overrides={"TEST": 120},
                )

                self.assertEqual(
                    portfolio["total_invested"],
                    1000,
                )

                self.assertEqual(
                    portfolio["total_current_value"],
                    1200,
                )

                self.assertEqual(
                    portfolio["total_unrealized_pnl"],
                    200,
                )

                self.assertEqual(
                    portfolio["total_pnl"],
                    200,
                )

                snapshots = get_portfolio_snapshots()

                self.assertEqual(len(snapshots), 1)
                self.assertEqual(snapshots[0][1], "2026-09-24")
                self.assertEqual(snapshots[0][2], 1000)
                self.assertEqual(snapshots[0][3], 1200)
                self.assertEqual(snapshots[0][5], 200)
                self.assertEqual(snapshots[0][6], 200)

            finally:
                database.DB_PATH = original_path

    def test_portfolio_performance_history_returns_saved_snapshots(self):
        original_path = database.DB_PATH

        with tempfile.TemporaryDirectory() as directory:
            database.DB_PATH = Path(directory) / "test.db"

            try:
                save_portfolio_snapshot(
                    snapshot_date="2026-09-24",
                    total_invested=10000,
                    total_current_value=12000,
                    total_realized_pnl=500,
                    total_unrealized_pnl=1500,
                    total_pnl=2000,
                    total_return_percent=20,
                )

                save_portfolio_snapshot(
                    snapshot_date="2026-09-25",
                    total_invested=10000,
                    total_current_value=13000,
                    total_realized_pnl=500,
                    total_unrealized_pnl=2500,
                    total_pnl=3000,
                    total_return_percent=30,
                )

                history = get_portfolio_performance_history()

                self.assertEqual(len(history), 2)

                self.assertEqual(
                    history[0]["date"],
                    "2026-09-24",
                )

                self.assertEqual(
                    history[0]["total_current_value"],
                    12000,
                )

                self.assertEqual(
                    history[0]["total_pnl"],
                    2000,
                )

                self.assertEqual(
                    history[1]["date"],
                    "2026-09-25",
                )

                self.assertEqual(
                    history[1]["total_current_value"],
                    13000,
                )

                self.assertEqual(
                    history[1]["total_pnl"],
                    3000,
                )

            finally:
                database.DB_PATH = original_path

    def test_snapshot_changes_are_calculated_correctly(self):
        original_path = database.DB_PATH

        with tempfile.TemporaryDirectory() as directory:
            database.DB_PATH = Path(directory) / "test.db"

            try:
                save_portfolio_snapshot(
                    snapshot_date="2026-09-24",
                    total_invested=10000,
                    total_current_value=10000,
                    total_realized_pnl=0,
                    total_unrealized_pnl=0,
                    total_pnl=0,
                    total_return_percent=0,
                )

                save_portfolio_snapshot(
                    snapshot_date="2026-09-25",
                    total_invested=10000,
                    total_current_value=12000,
                    total_realized_pnl=0,
                    total_unrealized_pnl=2000,
                    total_pnl=2000,
                    total_return_percent=20,
                )

                history = calculate_snapshot_changes()

                self.assertEqual(len(history), 2)

                # First snapshot has no comparison value.
                self.assertIsNone(history[0]["value_change"])
                self.assertIsNone(history[0]["value_change_percent"])

                # Second snapshot rose from 10,000 to 12,000.
                self.assertEqual(history[1]["previous_value"], 10000)
                self.assertEqual(history[1]["value_change"], 2000)
                self.assertEqual(history[1]["value_change_percent"], 20)

            finally:
                database.DB_PATH = original_path

    def test_max_drawdown_is_calculated_correctly(self):
        original_path = database.DB_PATH

        with tempfile.TemporaryDirectory() as directory:
            database.DB_PATH = Path(directory) / "test.db"

            try:
                save_portfolio_snapshot(
                    snapshot_date="2026-09-24",
                    total_invested=10000,
                    total_current_value=10000,
                    total_realized_pnl=0,
                    total_unrealized_pnl=0,
                    total_pnl=0,
                    total_return_percent=0,
                )

                save_portfolio_snapshot(
                    snapshot_date="2026-09-25",
                    total_invested=10000,
                    total_current_value=12000,
                    total_realized_pnl=0,
                    total_unrealized_pnl=2000,
                    total_pnl=2000,
                    total_return_percent=20,
                )

                save_portfolio_snapshot(
                    snapshot_date="2026-09-26",
                    total_invested=10000,
                    total_current_value=9000,
                    total_realized_pnl=0,
                    total_unrealized_pnl=-1000,
                    total_pnl=-1000,
                    total_return_percent=-10,
                )

                result = calculate_max_drawdown()

                self.assertEqual(
                    result["max_drawdown_amount"],
                    3000,
                )

                self.assertEqual(
                    result["max_drawdown_percent"],
                    25,
                )

                self.assertEqual(
                    result["peak_date"],
                    "2026-09-25",
                )

                self.assertEqual(
                    result["trough_date"],
                    "2026-09-26",
                )

            finally:
                database.DB_PATH = original_path

    def test_portfolio_allocation_is_calculated_correctly(self):
        original_path = database.DB_PATH

        with tempfile.TemporaryDirectory() as directory:
            database.DB_PATH = Path(directory) / "test.db"

            try:
                add_transaction(
                    "AAA",
                    "Company AAA",
                    "BUY",
                    10,
                    100,
                    "2026-09-24",
                )

                add_transaction(
                    "BBB",
                    "Company BBB",
                    "BUY",
                    5,
                    100,
                    "2026-09-24",
                )

                allocation = calculate_portfolio_allocation(
                    price_overrides={
                        "AAA": 100,
                        "BBB": 200,
                    }
                )

                self.assertEqual(
                    allocation["AAA"]["current_value"],
                    1000,
                )

                self.assertEqual(
                    allocation["BBB"]["current_value"],
                    1000,
                )

                self.assertEqual(
                    allocation["AAA"]["allocation_percent"],
                    50,
                )

                self.assertEqual(
                    allocation["BBB"]["allocation_percent"],
                    50,
                )

                
            finally:
                database.DB_PATH = original_path

    def test_portfolio_concentration_is_calculated_correctly(self):
        original_path = database.DB_PATH

        with tempfile.TemporaryDirectory() as directory:
            database.DB_PATH = Path(directory) / "test.db"

            try:
                add_transaction(
                    "AAA",
                    "Company AAA",
                    "BUY",
                    10,
                    100,
                    "2026-09-24",
                )

                add_transaction(
                    "BBB",
                    "Company BBB",
                    "BUY",
                    5,
                    100,
                    "2026-09-24",
                )

                concentration = calculate_portfolio_concentration(
                    price_overrides={
                        "AAA": 100,
                        "BBB": 300,
                    }
                )

                self.assertEqual(
                    concentration["holding_count"],
                    2,
                )

                self.assertEqual(
                    concentration["largest_holding_symbol"],
                    "BBB",
                )

                self.assertEqual(
                    concentration["largest_holding_percent"],
                    60,
                )

                self.assertEqual(
                    concentration["largest_holding_value"],
                    1500,
                )

            finally:
                database.DB_PATH = original_path

    def test_portfolio_analytics_summary_combines_metrics(self):
        original_path = database.DB_PATH

        with tempfile.TemporaryDirectory() as directory:
            database.DB_PATH = Path(directory) / "test.db"

            try:
                add_transaction(
                    "AAA",
                    "Company AAA",
                    "BUY",
                    10,
                    100,
                    "2026-09-24",
                )

                add_transaction(
                    "BBB",
                    "Company BBB",
                    "BUY",
                    5,
                    100,
                    "2026-09-24",
                )

                # Create snapshots for drawdown calculation.
                save_portfolio_snapshot(
                    "2026-09-24",
                    1500,
                    1500,
                    0,
                    0,
                    0,
                    0,
                )

                save_portfolio_snapshot(
                    "2026-09-25",
                    1500,
                    1200,
                    0,
                    -300,
                    -300,
                    -20,
                )

                summary = get_portfolio_analytics_summary(
                    price_overrides={
                        "AAA": 100,
                        "BBB": 300,
                    }
                )

                self.assertIn(
                    "allocation",
                    summary,
                )

                self.assertIn(
                    "concentration",
                    summary,
                )

                self.assertIn(
                    "max_drawdown",
                    summary,
                )

                self.assertEqual(
                    summary["concentration"]["holding_count"],
                    2,
                )

                self.assertEqual(
                    summary["concentration"]["largest_holding_symbol"],
                    "BBB",
                )

                self.assertEqual(
                    summary["concentration"]["largest_holding_percent"],
                    60,
                )

                self.assertEqual(
                    summary["max_drawdown"]["max_drawdown_amount"],
                    300,
                )

            finally:
                database.DB_PATH = original_path

    def test_historical_performance_summary_is_calculated_correctly(self):
        original_path = database.DB_PATH

        with tempfile.TemporaryDirectory() as directory:
            database.DB_PATH = Path(directory) / "test.db"

            try:
                save_portfolio_snapshot(
                    "2026-09-24",
                    1000,
                    1000,
                    0,
                    0,
                    0,
                    0,
                )

                save_portfolio_snapshot(
                    "2026-09-25",
                    1000,
                    1500,
                    0,
                    500,
                    500,
                    50,
                )

                save_portfolio_snapshot(
                    "2026-09-26",
                    1000,
                    1200,
                    0,
                    200,
                    200,
                    20,
                )

                summary = get_historical_performance_summary()

                self.assertEqual(
                    summary["starting_value"],
                    1000,
                )

                self.assertEqual(
                    summary["latest_value"],
                    1200,
                )

                self.assertEqual(
                    summary["value_change"],
                    200,
                )

                self.assertEqual(
                    summary["value_change_percent"],
                    20,
                )

                self.assertEqual(
                    summary["highest_value"],
                    1500,
                )

                self.assertEqual(
                    summary["lowest_value"],
                    1000,
                )

                self.assertEqual(
                    summary["starting_date"],
                    "2026-09-24",
                )

                self.assertEqual(
                    summary["latest_date"],
                    "2026-09-26",
                )

                self.assertEqual(
                    summary["highest_value_date"],
                    "2026-09-25",
                )

                self.assertEqual(
                    summary["lowest_value_date"],
                    "2026-09-24",
                )

            finally:
                database.DB_PATH = original_path

    def test_dashboard_data_combines_portfolio_analytics_and_history(self):
        original_path = database.DB_PATH

        with tempfile.TemporaryDirectory() as directory:
            database.DB_PATH = Path(directory) / "test.db"

            try:
                add_transaction(
                    "AAA",
                    "Company AAA",
                    "BUY",
                    10,
                    100,
                    "2026-09-24",
                )

                add_transaction(
                    "BBB",
                    "Company BBB",
                    "BUY",
                    5,
                    100,
                    "2026-09-24",
                )

                save_portfolio_snapshot(
                    "2026-09-24",
                    1500,
                    1500,
                    0,
                    0,
                    0,
                    0,
                )

                save_portfolio_snapshot(
                    "2026-09-25",
                    1500,
                    1200,
                    0,
                    -300,
                    -300,
                    -20,
                )

                dashboard_data = get_dashboard_data(
                    price_overrides={
                        "AAA": 100,
                        "BBB": 300,
                    }
                )

                self.assertIn(
                    "portfolio",
                    dashboard_data,
                )

                self.assertIn(
                    "analytics",
                    dashboard_data,
                )

                self.assertIn(
                    "historical",
                    dashboard_data,
                )

                self.assertEqual(
                    dashboard_data["portfolio"]["total_current_value"],
                    2500,
                )

                self.assertEqual(
                    dashboard_data["analytics"]["concentration"][
                        "largest_holding_symbol"
                    ],
                    "BBB",
                )

                self.assertEqual(
                    dashboard_data["analytics"]["concentration"][
                        "largest_holding_percent"
                    ],
                    60,
                )

                self.assertEqual(
                    dashboard_data["historical"]["starting_value"],
                    1500,
                )

                self.assertEqual(
                    dashboard_data["historical"]["latest_value"],
                    1200,
                )

            finally:
                database.DB_PATH = original_path

if __name__ == "__main__":
    unittest.main()