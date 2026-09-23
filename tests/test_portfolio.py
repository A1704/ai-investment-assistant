import sqlite3
import tempfile
import unittest
from pathlib import Path

import investment_assistant.database as database
from investment_assistant.portfolio import (
    add_opening_position,
    calculate_positions,
    get_opening_positions,
)


def transaction(transaction_id, symbol, transaction_type, quantity, price):
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

        positions = calculate_positions([], opening_positions)

        self.assertEqual(positions["ABC"]["total_buy_quantity"], 10)
        self.assertEqual(positions["ABC"]["total_buy_cost"], 1000)
        self.assertEqual(positions["ABC"]["current_quantity"], 10)
        self.assertEqual(positions["ABC"]["average_buy_price"], 100)

    def test_opening_position_combines_with_transactions(self):
        opening_positions = [
            (1, "ABC", "ABC Company", 10, 100, 1000, None),
        ]

        positions = calculate_positions(
            [transaction(2, "ABC", "BUY", 5, 120)],
            opening_positions,
        )

        self.assertEqual(positions["ABC"]["total_buy_quantity"], 15)
        self.assertEqual(positions["ABC"]["total_buy_cost"], 1600)
        self.assertEqual(positions["ABC"]["average_buy_price"], 1600 / 15)

    def test_one_buy(self):
        positions = calculate_positions([
            transaction(1, "ABC", "BUY", 10, 100),
        ])

        self.assertEqual(
            positions["ABC"],
            {
                "total_buy_quantity": 10,
                "total_sell_quantity": 0,
                "current_quantity": 10,
                "total_buy_cost": 1000,
                "total_sell_proceeds": 0,
                "average_buy_price": 100,
                "is_zero_quantity": False,
            },
        )

    def test_multiple_buys_of_same_stock(self):
        positions = calculate_positions([
            transaction(1, "ABC", "BUY", 10, 100),
            transaction(2, "ABC", "BUY", 5, 120),
        ])

        self.assertEqual(positions["ABC"]["total_buy_quantity"], 15)
        self.assertEqual(positions["ABC"]["total_buy_cost"], 1600)
        self.assertEqual(positions["ABC"]["average_buy_price"], 1600 / 15)
        self.assertEqual(positions["ABC"]["current_quantity"], 15)

    def test_buy_followed_by_sell(self):
        positions = calculate_positions([
            transaction(1, "ABC", "BUY", 10, 100),
            transaction(2, "ABC", "SELL", 4, 130),
        ])

        self.assertEqual(positions["ABC"]["total_sell_quantity"], 4)
        self.assertEqual(positions["ABC"]["total_sell_proceeds"], 520)
        self.assertEqual(positions["ABC"]["current_quantity"], 6)

    def test_multiple_buys_and_sells(self):
        positions = calculate_positions([
            transaction(1, "ABC", "BUY", 10, 100),
            transaction(2, "ABC", "BUY", 5, 120),
            transaction(3, "ABC", "SELL", 4, 130),
            transaction(4, "ABC", "SELL", 3, 140),
        ])

        self.assertEqual(positions["ABC"]["total_buy_quantity"], 15)
        self.assertEqual(positions["ABC"]["total_sell_quantity"], 7)
        self.assertEqual(positions["ABC"]["current_quantity"], 8)
        self.assertEqual(positions["ABC"]["total_buy_cost"], 1600)
        self.assertEqual(positions["ABC"]["total_sell_proceeds"], 940)
        self.assertEqual(positions["ABC"]["average_buy_price"], 1600 / 15)

    def test_position_reduced_to_zero(self):
        positions = calculate_positions([
            transaction(1, "ABC", "BUY", 10, 100),
            transaction(2, "ABC", "SELL", 10, 110),
        ])

        self.assertEqual(positions["ABC"]["current_quantity"], 0)
        self.assertTrue(positions["ABC"]["is_zero_quantity"])

    def test_calculation_does_not_modify_database(self):
        connection = sqlite3.connect(database.DB_PATH)
        try:
            before = connection.execute(
                "SELECT COUNT(*) FROM transactions"
            ).fetchone()[0]
        finally:
            connection.close()

        calculate_positions([
            transaction(1, "ABC", "BUY", 10, 100),
            transaction(2, "ABC", "SELL", 10, 110),
        ])

        connection = sqlite3.connect(database.DB_PATH)
        try:
            after = connection.execute(
                "SELECT COUNT(*) FROM transactions"
            ).fetchone()[0]
        finally:
            connection.close()

        self.assertEqual(before, after)

    def test_opening_position_can_have_unknown_purchase_date(self):
        original_path = database.DB_PATH
        with tempfile.TemporaryDirectory() as directory:
            database.DB_PATH = Path(directory) / "test.db"
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


if __name__ == "__main__":
    unittest.main()
