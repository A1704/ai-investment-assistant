import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import investment_assistant.database as database
from investment_assistant.portfolio import (
    get_portfolio_snapshots,
    save_portfolio_snapshot,
)
from investment_assistant.alerts import (
    AlertThresholds,
    INSUFFICIENT_HISTORY_MESSAGE,
    calculate_portfolio_changes,
)


def snapshot(snapshot_date, value, pnl, holdings=None):
    return {
        "date": snapshot_date,
        "total_current_value": value,
        "total_pnl": pnl,
        "holding_snapshot_json": (
            json.dumps(holdings) if holdings is not None else None
        ),
    }


class PortfolioChangeCalculationTests(unittest.TestCase):
    def test_insufficient_history_with_zero_or_one_snapshot(self):
        for snapshots in ([], [snapshot("2026-01-01", 1000, 0)]):
            report = calculate_portfolio_changes(snapshots)
            self.assertFalse(report["available"])
            self.assertEqual(report["message"], INSUFFICIENT_HISTORY_MESSAGE)
            self.assertEqual(report["alerts"], [])

    def test_calculates_normal_portfolio_and_holding_changes(self):
        report = calculate_portfolio_changes([
            snapshot(
                "2026-01-01",
                1000,
                100,
                {"ABC": {
                    "current_value": 1000,
                    "unrealized_pnl": 100,
                    "allocation_percent": 100,
                }},
            ),
            snapshot(
                "2026-01-02",
                1010,
                120,
                {"ABC": {
                    "current_value": 1010,
                    "unrealized_pnl": 120,
                    "allocation_percent": 100,
                }},
            ),
        ])

        self.assertTrue(report["available"])
        self.assertEqual(report["previous_date"], "2026-01-01")
        self.assertEqual(report["latest_date"], "2026-01-02")
        self.assertEqual(report["portfolio_value"]["change"], 10)
        self.assertEqual(report["portfolio_value"]["change_percent"], 1)
        self.assertEqual(report["total_pnl"]["change"], 20)
        self.assertEqual(
            report["holding_changes"][0]["unrealized_pnl_change"],
            20,
        )
        self.assertEqual(report["alerts"], [])

    def test_portfolio_percentage_threshold_and_severity(self):
        report = calculate_portfolio_changes([
            snapshot("2026-01-01", 1000, 0),
            snapshot("2026-01-02", 1020, 0),
        ])
        self.assertEqual(report["alerts"][0]["type"], "portfolio_value")
        self.assertEqual(report["alerts"][0]["severity"], "NOTICE")

        important = calculate_portfolio_changes([
            snapshot("2026-01-01", 1000, 0),
            snapshot("2026-01-02", 1040, 0),
        ])
        self.assertEqual(important["alerts"][0]["severity"], "IMPORTANT")

    def test_holding_percentage_threshold(self):
        report = calculate_portfolio_changes([
            snapshot("2026-01-01", 1000, 0, {"ABC": {
                "current_value": 1000,
                "unrealized_pnl": 0,
                "allocation_percent": 100,
            }}),
            snapshot("2026-01-02", 1050, 0, {"ABC": {
                "current_value": 1050,
                "unrealized_pnl": 50,
                "allocation_percent": 100,
            }}),
        ])
        self.assertIn("holding_value", [item["type"] for item in report["alerts"]])

    def test_pnl_threshold_and_multiple_simultaneous_alerts(self):
        report = calculate_portfolio_changes([
            snapshot("2026-01-01", 10000, 0, {"ABC": {
                "current_value": 10000,
                "unrealized_pnl": 0,
                "allocation_percent": 100,
            }}),
            snapshot("2026-01-02", 11000, 600, {"ABC": {
                "current_value": 11000,
                "unrealized_pnl": 600,
                "allocation_percent": 100,
            }}),
        ])
        types = {item["type"] for item in report["alerts"]}
        self.assertEqual(
            types,
            {"portfolio_value", "total_pnl", "holding_value", "holding_pnl"},
        )

    def test_no_alert_when_changes_are_below_thresholds(self):
        report = calculate_portfolio_changes([
            snapshot("2026-01-01", 1000, 0, {"ABC": {
                "current_value": 1000,
                "unrealized_pnl": 0,
                "allocation_percent": 100,
            }}),
            snapshot("2026-01-02", 1010, 20, {"ABC": {
                "current_value": 1010,
                "unrealized_pnl": 20,
                "allocation_percent": 100,
            }}),
        ])
        self.assertEqual(report["alerts"], [])

    def test_concentration_change_is_detected(self):
        report = calculate_portfolio_changes([
            snapshot("2026-01-01", 1000, 0, {
                "ABC": {
                    "current_value": 600,
                    "unrealized_pnl": 0,
                    "allocation_percent": 60,
                },
                "XYZ": {
                    "current_value": 400,
                    "unrealized_pnl": 0,
                    "allocation_percent": 40,
                },
            }),
            snapshot("2026-01-02", 1000, 0, {
                "ABC": {
                    "current_value": 540,
                    "unrealized_pnl": 0,
                    "allocation_percent": 54,
                },
                "XYZ": {
                    "current_value": 460,
                    "unrealized_pnl": 0,
                    "allocation_percent": 46,
                },
            }),
        ])
        self.assertEqual(
            [item["symbol"] for item in report["concentration_changes"]],
            ["ABC", "XYZ"],
        )

    def test_thresholds_are_configurable(self):
        thresholds = AlertThresholds(
            portfolio_value_percent=1,
            holding_value_percent=1,
            pnl_amount=100,
            allocation_change_percentage_points=2,
        )
        report = calculate_portfolio_changes(
            [
                snapshot("2026-01-01", 1000, 0),
                snapshot("2026-01-02", 1010, 0),
            ],
            thresholds=thresholds,
        )
        self.assertEqual(report["alerts"][0]["type"], "portfolio_value")

    def test_aggregate_only_legacy_snapshots_report_missing_holding_history(self):
        report = calculate_portfolio_changes([
            snapshot("2026-01-01", 1000, 0),
            snapshot("2026-01-02", 1100, 100),
        ])
        self.assertTrue(report["available"])
        self.assertFalse(report["holding_comparison_available"])
        self.assertIsNotNone(report["holding_comparison_message"])

    def test_one_null_snapshot_disables_holding_comparison_only(self):
        report = calculate_portfolio_changes([
            snapshot("2026-01-01", 1000, 0, {"ABC": {
                "market_value": 1000,
                "unrealized_pnl": 0,
                "allocation_percent": 100,
            }}),
            snapshot("2026-01-02", 1100, 100),
        ])
        self.assertTrue(report["available"])
        self.assertFalse(report["holding_comparison_available"])
        self.assertEqual(report["portfolio_value"]["change"], 100)

    def test_uses_latest_two_detailed_snapshots_when_latest_has_null_detail(self):
        report = calculate_portfolio_changes([
            snapshot("2026-01-01", 1000, 0, {"ABC": {
                "market_value": 1000,
                "unrealized_pnl": 0,
                "allocation_percent": 100,
            }}),
            snapshot("2026-01-02", 1100, 100, {"ABC": {
                "market_value": 1100,
                "unrealized_pnl": 100,
                "allocation_percent": 100,
            }}),
            snapshot("2026-01-03", 1200, 200),
        ])

        self.assertTrue(report["holding_comparison_available"])
        self.assertEqual(
            report["holding_comparison_previous_date"],
            "2026-01-01",
        )
        self.assertEqual(
            report["holding_comparison_latest_date"],
            "2026-01-02",
        )
        self.assertEqual(report["latest_date"], "2026-01-03")

    def test_compares_two_detailed_holding_snapshots(self):
        report = calculate_portfolio_changes([
            snapshot("2026-01-01", 1000, -100, {
                "ABC": {
                    "symbol": "ABC",
                    "company_name": "ABC Company",
                    "quantity": 10,
                    "current_price": 100,
                    "market_value": 1000,
                    "remaining_cost_basis": 1200,
                    "unrealized_pnl": -200,
                    "total_pnl": -150,
                    "allocation_percent": 50,
                },
            }),
            snapshot("2026-01-02", 1200, 100, {
                "ABC": {
                    "symbol": "ABC",
                    "company_name": "ABC Company",
                    "quantity": 12,
                    "current_price": 110,
                    "market_value": 1320,
                    "remaining_cost_basis": 1200,
                    "unrealized_pnl": 120,
                    "total_pnl": 170,
                    "allocation_percent": 55,
                },
            }),
        ])

        change = report["holding_changes"][0]
        self.assertEqual(change["current_value"], 1320)
        self.assertEqual(change["value_change"], 320)
        self.assertEqual(change["value_change_percent"], 32)
        self.assertEqual(change["market_value_change"], 320)
        self.assertEqual(change["market_value_change_percent"], 32)
        self.assertEqual(change["unrealized_pnl_change"], 320)
        self.assertEqual(change["total_pnl_change"], 320)
        self.assertEqual(change["allocation_change_percentage_points"], 5)
        self.assertEqual(change["quantity_change"], 2)
        self.assertEqual(change["current_price_change"], 10)
        self.assertEqual(change["status"], "changed")

    def test_legacy_partial_fields_are_not_invented(self):
        report = calculate_portfolio_changes([
            snapshot("2026-01-01", 1000, 0, {"ABC": {
                "current_value": 1000,
                "allocation_percent": 100,
            }}),
            snapshot("2026-01-02", 1050, 50, {"ABC": {
                "current_value": 1050,
                "allocation_percent": 100,
            }}),
        ])
        holding = report["holding_changes"][0]
        self.assertEqual(holding["value_change"], 50)
        self.assertIsNone(holding["unrealized_pnl_change"])
        self.assertIsNone(holding["total_pnl_change"])
        self.assertIsNone(holding["quantity_change"])
        self.assertIsNone(holding["current_price_change"])

    def test_added_and_removed_holdings_are_reported(self):
        report = calculate_portfolio_changes([
            snapshot("2026-01-01", 1000, 0, {
                "OLD": {
                    "quantity": 5,
                    "current_price": 200,
                    "market_value": 1000,
                    "unrealized_pnl": 0,
                    "total_pnl": 0,
                    "allocation_percent": 100,
                },
            }),
            snapshot("2026-01-02", 500, 0, {
                "NEW": {
                    "quantity": 2,
                    "current_price": 250,
                    "market_value": 500,
                    "unrealized_pnl": 0,
                    "total_pnl": 0,
                    "allocation_percent": 100,
                },
            }),
        ])
        self.assertEqual(
            {item["symbol"]: item["status"] for item in report["holding_changes"]},
            {"NEW": "added", "OLD": "removed"},
        )
        self.assertIn(
            "holding_added",
            [item["type"] for item in report["alerts"]],
        )
        self.assertIn(
            "holding_removed",
            [item["type"] for item in report["alerts"]],
        )

    def test_legacy_detailed_json_remains_comparable(self):
        report = calculate_portfolio_changes([
            snapshot("2026-01-01", 1000, 0, {"ABC": {
                "current_value": 1000,
                "unrealized_pnl": 0,
                "allocation_percent": 100,
            }}),
            snapshot("2026-01-02", 1050, 0, {"ABC": {
                "current_value": 1050,
                "unrealized_pnl": 50,
                "allocation_percent": 100,
            }}),
        ])
        self.assertTrue(report["holding_comparison_available"])
        self.assertIsNone(report["holding_changes"][0]["quantity_change"])
        self.assertIsNone(report["holding_changes"][0]["current_price_change"])


class PortfolioChangeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "test.db"

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def test_snapshot_migration_preserves_existing_rows(self):
        connection = sqlite3.connect(database.DB_PATH)
        connection.execute("""
            CREATE TABLE portfolio_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL UNIQUE,
                total_invested REAL NOT NULL,
                total_current_value REAL NOT NULL,
                total_realized_pnl REAL NOT NULL,
                total_unrealized_pnl REAL NOT NULL,
                total_pnl REAL NOT NULL,
                total_return_percent REAL NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            INSERT INTO portfolio_snapshots (
                snapshot_date, total_invested, total_current_value,
                total_realized_pnl, total_unrealized_pnl, total_pnl,
                total_return_percent
            ) VALUES ('2026-01-01', 100, 120, 0, 20, 20, 20)
        """)
        connection.commit()
        connection.close()

        connection = database.get_connection()
        row = connection.execute(
            "SELECT snapshot_date, total_current_value, "
            "holding_snapshot_json FROM portfolio_snapshots"
        ).fetchone()
        connection.close()

        self.assertEqual(row[:2], ("2026-01-01", 120))
        self.assertIsNone(row[2])

    def test_snapshot_stores_all_holding_fields_as_json(self):
        save_portfolio_snapshot(
            snapshot_date="2026-01-01",
            total_invested=800,
            total_current_value=1000,
            total_realized_pnl=10,
            total_unrealized_pnl=200,
            total_pnl=210,
            total_return_percent=25,
            holding_positions={"ABC": {
                "company_name": "ABC Company",
                "quantity": 10,
                "current_price": 100,
                "current_value": 1000,
                "remaining_cost_basis": 800,
                "unrealized_pnl": 200,
                "total_pnl": 210,
            }},
        )

        stored = get_portfolio_snapshots()[0][9]
        holding = json.loads(stored)["ABC"]
        self.assertEqual(
            set(holding),
            {
                "symbol",
                "company_name",
                "quantity",
                "current_price",
                "market_value",
                "remaining_cost_basis",
                "unrealized_pnl",
                "total_pnl",
                "allocation_percent",
            },
        )
        self.assertEqual(holding["market_value"], 1000)
        self.assertEqual(holding["allocation_percent"], 100)
        self.assertEqual(holding["company_name"], "ABC Company")

    def test_daily_briefing_records_snapshot_and_renders_alert_section(self):
        from investment_assistant import briefing
        from investment_assistant.portfolio import save_portfolio_snapshot

        save_portfolio_snapshot(
            snapshot_date="2000-01-01",
            total_invested=1000,
            total_current_value=1000,
            total_realized_pnl=0,
            total_unrealized_pnl=0,
            total_pnl=0,
            total_return_percent=0,
            holding_positions={"ABC": {
                "company_name": "ABC Company",
                "quantity": 10,
                "current_price": 100,
                "current_value": 1000,
                "remaining_cost_basis": 1000,
                "unrealized_pnl": 0,
                "total_pnl": 0,
            }},
        )
        current_portfolio = {
            "positions": {"ABC": {
                "company_name": "ABC Company",
                "quantity": 10,
                "average_buy_price": 100,
                "current_price": 103,
                "current_value": 1030,
                "remaining_cost_basis": 1000,
                "realized_pnl": 0,
                "unrealized_pnl": 30,
                "total_pnl": 30,
            }},
            "total_invested": 1000,
            "total_current_value": 1030,
            "total_realized_pnl": 0,
            "total_unrealized_pnl": 30,
            "total_pnl": 30,
            "total_return_percent": 3,
        }
        with (
            patch.object(
                briefing,
                "calculate_portfolio_valuation",
                return_value=current_portfolio,
            ),
            patch.object(briefing, "get_company_news", return_value=[]),
            patch.object(
                briefing,
                "generate_goals_intelligence",
                return_value={"goals": [], "benchmarks": []},
            ),
            patch.object(
                briefing,
                "generate_portfolio_analysis",
                return_value="Mock analysis",
            ) as generate_analysis,
        ):
            portfolio, _, analysis = briefing.build_briefing()

        self.assertEqual(portfolio["portfolio_changes"]["previous_date"], "2000-01-01")
        self.assertTrue(portfolio["portfolio_changes"]["available"])
        html = briefing.build_html_email(portfolio, analysis)
        self.assertIn("Portfolio Intelligence", html)
        self.assertIn("ABC Company", html)
        self.assertIn("Things to Monitor", html)
        generate_analysis.assert_called_once()
        self.assertIn(
            "portfolio_overview",
            generate_analysis.call_args.kwargs["intelligence_report"],
        )
        self.assertLess(
            html.index("Portfolio Changes &amp; Alerts"),
            html.index("AI Analysis"),
        )
        self.assertIn("NOTICE", html)

    def test_dashboard_and_assistant_receive_change_data(self):
        from dashboard import app as dashboard_module
        from investment_assistant import assistant

        report = calculate_portfolio_changes([
            snapshot("2026-01-01", 1000, 0),
            snapshot("2026-01-02", 1100, 100),
        ])
        with patch(
            "dashboard.app.get_portfolio_change_report",
            return_value=report,
        ), patch(
            "dashboard.app.render_template",
            return_value="dashboard",
        ) as render, patch(
            "dashboard.app.get_dashboard_data",
            return_value={"portfolio": {"positions": {}}},
        ), patch(
            "dashboard.app.get_portfolio_alerts",
            return_value=[],
        ), patch(
            "dashboard.app.get_portfolio_snapshots",
            return_value=[],
        ), patch(
            "dashboard.app.generate_historical_analytics",
            return_value={},
        ), patch(
            "dashboard.app.generate_goals_intelligence",
            return_value={"goals": [], "benchmarks": []},
        ), patch(
            "dashboard.app.generate_performance_attribution",
            return_value={},
        ), patch(
            "dashboard.app.sqlite3.connect"
        ) as connect, patch(
            "dashboard.app.generate_portfolio_analysis",
            return_value="",
        ):
            connect.return_value.execute.return_value.fetchall.return_value = []
            connect.return_value.close.return_value = None
            dashboard_module._render_dashboard()
            self.assertIs(render.call_args.kwargs["portfolio_changes"], report)
            self.assertIn(
                "portfolio_overview",
                render.call_args.kwargs["portfolio_intelligence"],
            )

        with patch.object(
            assistant.portfolio,
            "calculate_portfolio_valuation",
            return_value={"positions": {}, "total_pnl": 0},
        ), patch.object(
            assistant.portfolio,
            "get_portfolio_analytics_summary",
            return_value={},
        ), patch.object(
            assistant.portfolio,
            "get_portfolio_performance_history",
            return_value=[],
        ), patch.object(
            assistant.portfolio,
            "get_historical_performance_summary",
            return_value={},
        ), patch.object(
            assistant.portfolio,
            "get_transactions",
            return_value=[],
        ), patch.object(
            assistant.portfolio,
            "get_opening_positions",
            return_value=[],
        ), patch.object(
            assistant.alerts,
            "get_portfolio_change_report",
            return_value=report,
        ), patch.object(
            assistant.goals_intelligence,
            "generate_goals_intelligence",
            return_value={"goals": [], "benchmarks": []},
        ), patch.object(
            assistant.ai_analysis,
            "generate_portfolio_answer",
            return_value="Mock answer",
        ) as generate:
            assistant.answer_portfolio_question(
                "What changed in my portfolio?"
            )
            self.assertEqual(
                generate.call_args.args[1]["portfolio_changes"],
                report,
            )

    def test_dashboard_template_has_portfolio_changes_section(self):
        from dashboard.app import app

        source, _, _ = app.jinja_env.loader.get_source(
            app.jinja_env,
            "dashboard.html",
        )
        self.assertIn("Portfolio Alerts &amp; Changes", source)
        self.assertIn("No significant portfolio changes detected.", source)


if __name__ == "__main__":
    unittest.main()
