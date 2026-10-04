import math
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from investment_assistant import database
from investment_assistant import goals_intelligence as goals


def portfolio_value(value=1200, pnl=200, return_percent=20):
    return {
        "positions": {},
        "total_current_value": value,
        "total_pnl": pnl,
        "total_return_percent": return_percent,
    }


def portfolio_history():
    return [
        {
            "date": "2026-01-01",
            "total_current_value": 1000,
            "total_pnl": 100,
            "total_return_percent": 10,
        },
        {
            "date": "2026-01-02",
            "total_current_value": 1200,
            "total_pnl": 200,
            "total_return_percent": 20,
        },
    ]


def goal_record(
    target_type="PORTFOLIO_VALUE",
    target_value=1500,
    target_date=None,
    goal_name="Portfolio target",
):
    return {
        "id": 1,
        "goal_name": goal_name,
        "target_type": target_type,
        "target_value": target_value,
        "target_date": target_date,
        "is_active": 1,
    }


class GoalsDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "isolated.sqlite3"
        patcher = patch.object(database, "DB_PATH", self.db_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temp_dir.cleanup)
        database.initialize_database()

    def test_goal_creation(self):
        goal_id = goals.create_portfolio_goal(
            "Emergency target",
            "PORTFOLIO_VALUE",
            25000,
        )
        self.assertEqual(goal_id, 1)
        self.assertEqual(len(goals.get_portfolio_goals()), 1)

    def test_goal_retrieval_includes_inactive_records_by_default(self):
        first = goals.create_portfolio_goal("First", "ABSOLUTE_PNL", 100)
        second = goals.create_portfolio_goal("Second", "RETURN_PERCENT", 5)
        goals.deactivate_portfolio_goal(second)
        self.assertEqual([item["id"] for item in goals.get_portfolio_goals()], [first, second])
        self.assertEqual([item["id"] for item in goals.get_active_portfolio_goals()], [first])

    def test_goal_update(self):
        goal_id = goals.create_portfolio_goal("Initial", "ABSOLUTE_PNL", 100)
        goals.update_portfolio_goal(
            goal_id,
            goal_name="Updated",
            target_value=250,
            target_date="2027-02-03",
        )
        saved = goals.get_active_portfolio_goals()[0]
        self.assertEqual(saved["goal_name"], "Updated")
        self.assertEqual(saved["target_value"], 250)
        self.assertEqual(saved["target_date"], "2027-02-03")

    def test_goal_deactivation(self):
        goal_id = goals.create_portfolio_goal("Goal", "PORTFOLIO_VALUE", 1)
        goals.deactivate_portfolio_goal(goal_id)
        self.assertEqual(goals.get_active_portfolio_goals(), [])

    def test_goal_deletion(self):
        goal_id = goals.create_portfolio_goal("Goal", "PORTFOLIO_VALUE", 1)
        goals.delete_portfolio_goal(goal_id)
        self.assertEqual(goals.get_portfolio_goals(), [])

    def test_goal_name_type_date_and_numeric_validation(self):
        invalid_calls = (
            ("", "PORTFOLIO_VALUE", 10, None),
            ("Goal", "UNKNOWN", 10, None),
            ("Goal", "PORTFOLIO_VALUE", -1, None),
            ("Goal", "PORTFOLIO_VALUE", math.nan, None),
            ("Goal", "PORTFOLIO_VALUE", math.inf, None),
            ("Goal", "PORTFOLIO_VALUE", 10, "2026-02-30"),
            ("Goal", "PORTFOLIO_VALUE", 10, "01-02-2026"),
        )
        for name, target_type, value, target_date in invalid_calls:
            with self.subTest(name=name, target_type=target_type, value=value):
                with self.assertRaises(ValueError):
                    goals.create_portfolio_goal(
                        name,
                        target_type,
                        value,
                        target_date,
                    )

    def test_update_rejects_invalid_fields_and_unknown_id(self):
        goal_id = goals.create_portfolio_goal("Goal", "PORTFOLIO_VALUE", 1)
        with self.assertRaises(ValueError):
            goals.update_portfolio_goal(goal_id, target_type="NOPE")
        with self.assertRaises(ValueError):
            goals.update_portfolio_goal(goal_id, target_value=math.inf)
        with self.assertRaises(ValueError):
            goals.update_portfolio_goal(999, goal_name="Missing")

    def test_no_goal_is_created_automatically(self):
        self.assertEqual(goals.get_portfolio_goals(), [])

    def test_additive_schema_setup_preserves_existing_transaction_and_snapshot_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "legacy.sqlite3"
            connection = sqlite3.connect(db_path)
            connection.executescript("""
                CREATE TABLE transactions (
                    id INTEGER PRIMARY KEY,
                    symbol TEXT,
                    company_name TEXT,
                    transaction_type TEXT,
                    quantity REAL,
                    price REAL,
                    transaction_date TEXT,
                    created_at TEXT
                );
                INSERT INTO transactions VALUES (
                    1, 'SYNTH', 'Synthetic Fixture', 'BUY', 1, 10,
                    '2026-01-01', 'created'
                );
                CREATE TABLE portfolio_snapshots (
                    id INTEGER PRIMARY KEY,
                    snapshot_date TEXT NOT NULL UNIQUE,
                    total_invested REAL NOT NULL,
                    total_current_value REAL NOT NULL,
                    total_realized_pnl REAL NOT NULL,
                    total_unrealized_pnl REAL NOT NULL,
                    total_pnl REAL NOT NULL,
                    total_return_percent REAL NOT NULL,
                    created_at TEXT
                );
                INSERT INTO portfolio_snapshots VALUES (
                    1, '2026-01-01', 10, 11, 0, 1, 1, 10, 'created'
                );
            """)
            connection.commit()
            connection.close()
            with patch.object(database, "DB_PATH", db_path):
                database.initialize_database()
                connection = sqlite3.connect(db_path)
                transaction_row = connection.execute(
                    "SELECT symbol, quantity, price FROM transactions"
                ).fetchone()
                snapshot_row = connection.execute(
                    "SELECT snapshot_date, total_current_value "
                    "FROM portfolio_snapshots"
                ).fetchone()
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                connection.close()
        self.assertEqual(transaction_row, ("SYNTH", 1.0, 10.0))
        self.assertEqual(snapshot_row, ("2026-01-01", 11.0))
        self.assertTrue({
            "portfolio_goals",
            "portfolio_benchmarks",
            "portfolio_benchmark_observations",
        }.issubset(tables))


class GoalsCalculationTests(unittest.TestCase):
    def test_no_goals_returns_empty_report(self):
        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(),
            history=[],
            goals=[],
            benchmarks=[],
            as_of_date=date(2026, 1, 2),
        )
        self.assertEqual(report["goals"], [])
        self.assertEqual(report["active_goal_count"], 0)

    def test_one_portfolio_value_goal_calculates_progress_and_remaining(self):
        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(value=1200),
            history=[],
            goals=[goal_record(target_value=1500)],
            benchmarks=[],
            as_of_date=date(2026, 1, 2),
        )
        item = report["goals"][0]
        self.assertEqual(item["current_value"], 1200)
        self.assertEqual(item["difference"], -300)
        self.assertEqual(item["progress_percent"], 80)
        self.assertEqual(item["remaining_amount"], 300)

    def test_multiple_goal_types_use_supplied_actual_values(self):
        records = [
            goal_record(target_value=1500),
            goal_record("ABSOLUTE_PNL", 250, goal_name="P&L target"),
            goal_record("RETURN_PERCENT", 25, goal_name="Return target"),
        ]
        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(),
            history=[],
            goals=records,
            benchmarks=[],
            as_of_date=date(2026, 1, 2),
        )
        self.assertEqual(
            [item["current_value"] for item in report["goals"]],
            [1200, 200, 20],
        )
        self.assertEqual(report["goals"][2]["difference"], -5)

    def test_goal_reached_and_below_target_statuses(self):
        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(value=1500),
            history=[],
            goals=[
                goal_record(target_value=1500),
                goal_record(target_value=2000, goal_name="Higher target"),
            ],
            benchmarks=[],
            as_of_date=date(2026, 1, 2),
        )
        self.assertEqual(report["goals"][0]["status"], "Reached")
        self.assertTrue(report["goals"][0]["target_reached"])
        self.assertEqual(report["goals"][1]["status"], "Below target")

    def test_zero_target_has_defined_reached_state_and_no_division(self):
        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(value=0, pnl=0, return_percent=0),
            history=[],
            goals=[goal_record(target_value=0)],
            benchmarks=[],
            as_of_date=date(2026, 1, 2),
        )
        self.assertEqual(report["goals"][0]["status"], "Reached")
        self.assertIsNone(report["goals"][0]["progress_percent"])
        self.assertEqual(report["goals"][0]["remaining_amount"], 0)

    def test_future_target_date_is_not_evaluated_as_on_track(self):
        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(value=100),
            history=[],
            goals=[goal_record(target_value=500, target_date="2026-01-03")],
            benchmarks=[],
            as_of_date=date(2026, 1, 2),
        )
        item = report["goals"][0]
        self.assertEqual(item["status"], "In progress")
        self.assertFalse(item["target_date_arrived"])
        self.assertEqual(item["target_date_status"], "Target date has not yet arrived.")

    def test_target_date_that_has_arrived_is_reported(self):
        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(value=100),
            history=[],
            goals=[goal_record(target_value=500, target_date="2026-01-02")],
            benchmarks=[],
            as_of_date=date(2026, 1, 2),
        )
        self.assertEqual(report["goals"][0]["status"], "Below target")
        self.assertTrue(report["goals"][0]["target_date_arrived"])

    def test_no_current_valuation_uses_latest_actual_snapshot_when_available(self):
        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(value=None, pnl=None, return_percent=None),
            history=portfolio_history(),
            goals=[goal_record(target_value=1300)],
            benchmarks=[],
            as_of_date=date(2026, 1, 2),
        )
        item = report["goals"][0]
        self.assertEqual(item["current_value"], 1200)
        self.assertEqual(item["latest_portfolio_data_date"], "2026-01-02")

    def test_no_current_valuation_without_history_is_explicit(self):
        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(value=None),
            history=[],
            goals=[goal_record()],
            benchmarks=[],
            as_of_date=date(2026, 1, 2),
        )
        self.assertEqual(
            report["goals"][0]["status"],
            "No current valuation available",
        )

    def test_return_goal_reports_insufficient_history_without_actual_return(self):
        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(return_percent=None),
            history=[],
            goals=[goal_record("RETURN_PERCENT", 10)],
            benchmarks=[],
            as_of_date=date(2026, 1, 2),
        )
        self.assertEqual(
            report["goals"][0]["status"],
            "Insufficient historical data",
        )

    def test_no_benchmark_is_reported_without_assumptions(self):
        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(),
            history=portfolio_history(),
            goals=[],
            benchmarks=[],
            as_of_date=date(2026, 1, 2),
        )
        self.assertEqual(report["benchmarks"], [])
        self.assertEqual(report["active_benchmark_count"], 0)

    def test_benchmark_configuration_and_observation_crud(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "isolated.sqlite3"
            with patch.object(database, "DB_PATH", db_path):
                database.initialize_database()
                benchmark_id = goals.create_portfolio_benchmark(
                    "User index",
                    "USER_PROVIDED_VALUE",
                    "USR-INDEX",
                )
                self.assertEqual(
                    goals.get_portfolio_benchmarks(active_only=True)[0][
                        "benchmark_symbol"
                    ],
                    "USR-INDEX",
                )
                goals.add_benchmark_observation(
                    benchmark_id,
                    "2026-01-01",
                    100,
                )
                self.assertEqual(
                    goals.get_benchmark_observations(benchmark_id),
                    [{"date": "2026-01-01", "value": 100}],
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "already exists",
                ):
                    goals.add_benchmark_observation(
                        benchmark_id,
                        "2026-01-01",
                        101,
                    )

    def test_invalid_benchmark_and_observations_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "isolated.sqlite3"
            with patch.object(database, "DB_PATH", db_path):
                database.initialize_database()
                with self.assertRaises(ValueError):
                    goals.create_portfolio_benchmark(" ", "USER_PROVIDED_VALUE")
                with self.assertRaises(ValueError):
                    goals.create_portfolio_benchmark("Index", "UNKNOWN")
                benchmark_id = goals.create_portfolio_benchmark(
                    "Cumulative return",
                    "USER_PROVIDED_RETURN",
                )
                for observation_date, value in (
                    ("2026-02-30", 1),
                    ("2026-01-01", math.nan),
                    ("2026-01-02", -101),
                    ("2999-01-01", 1),
                ):
                    with self.subTest(observation_date=observation_date, value=value):
                        with self.assertRaises(ValueError):
                            goals.add_benchmark_observation(
                                benchmark_id,
                                observation_date,
                                value,
                                as_of_date=date(2026, 1, 2),
                            )
                with self.assertRaises(ValueError):
                    goals.add_benchmark_observation(999, "2026-01-01", 1)

    def test_benchmark_comparison_requires_exact_matching_dates(self):
        benchmark = {
            "id": 1,
            "benchmark_name": "Configured",
            "benchmark_type": "USER_PROVIDED_VALUE",
            "is_active": 1,
        }
        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(),
            history=portfolio_history(),
            goals=[],
            benchmarks=[benchmark],
            observations_by_benchmark={
                1: [
                    {"date": "2026-01-01", "value": 100},
                    {"date": "2026-01-02", "value": 110},
                ]
            },
            as_of_date=date(2026, 1, 2),
        )
        comparison = report["benchmarks"][0]["comparison"]
        self.assertTrue(comparison["available"])
        self.assertEqual(comparison["period_start_date"], "2026-01-01")
        self.assertEqual(comparison["period_end_date"], "2026-01-02")

    def test_missing_matching_date_reports_unavailable(self):
        benchmark = {
            "id": 1,
            "benchmark_name": "Configured",
            "benchmark_type": "USER_PROVIDED_VALUE",
            "is_active": 1,
        }
        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(),
            history=portfolio_history(),
            goals=[],
            benchmarks=[benchmark],
            observations_by_benchmark={
                1: [
                    {"date": "2026-01-01", "value": 100},
                    {"date": "2026-01-03", "value": 110},
                ]
            },
            as_of_date=date(2026, 1, 2),
        )
        comparison = report["benchmarks"][0]["comparison"]
        self.assertFalse(comparison["available"])
        self.assertEqual(
            comparison["message"],
            goals.BENCHMARK_UNAVAILABLE_MESSAGE,
        )

    def test_matching_comparison_calculates_returns_and_percentage_point_gap(self):
        benchmark = {
            "id": 1,
            "benchmark_name": "Configured index",
            "benchmark_type": "USER_PROVIDED_VALUE",
            "is_active": 1,
        }
        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(),
            history=portfolio_history(),
            goals=[],
            benchmarks=[benchmark],
            observations_by_benchmark={
                1: [
                    {"date": "2026-01-01", "value": 100},
                    {"date": "2026-01-02", "value": 120},
                ]
            },
            as_of_date=date(2026, 1, 2),
        )
        comparison = report["benchmarks"][0]["comparison"]
        self.assertAlmostEqual(comparison["portfolio_return_percent"], 20)
        self.assertAlmostEqual(comparison["benchmark_return_percent"], 20)
        self.assertAlmostEqual(comparison["difference_percentage_points"], 0)
        self.assertEqual(comparison["portfolio_value_change"], 200)
        self.assertEqual(comparison["benchmark_value_change"], 20)
        self.assertIn(
            "transaction cash flows are not adjusted",
            comparison["portfolio_return_basis"],
        )

    def test_return_observations_are_compared_only_on_exact_dates(self):
        benchmark = {
            "id": 1,
            "benchmark_name": "Cumulative return",
            "benchmark_type": "USER_PROVIDED_RETURN",
            "is_active": 1,
        }
        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(),
            history=portfolio_history(),
            goals=[],
            benchmarks=[benchmark],
            observations_by_benchmark={
                1: [
                    {"date": "2026-01-01", "value": 0},
                    {"date": "2026-01-02", "value": 10},
                ]
            },
            as_of_date=date(2026, 1, 2),
        )
        comparison = report["benchmarks"][0]["comparison"]
        self.assertAlmostEqual(comparison["benchmark_return_percent"], 10)
        self.assertIsNone(comparison["benchmark_value_change"])

    def test_no_benchmark_data_is_fabricated_or_interpolated(self):
        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(),
            history=portfolio_history(),
            goals=[],
            benchmarks=[
                {
                    "id": 1,
                    "benchmark_name": "Configured",
                    "benchmark_type": "USER_PROVIDED_VALUE",
                    "is_active": 1,
                }
            ],
            observations_by_benchmark={1: []},
            as_of_date=date(2026, 1, 2),
        )
        comparison = report["benchmarks"][0]["comparison"]
        self.assertFalse(comparison["available"])
        self.assertIsNone(comparison["benchmark_return_percent"])
        self.assertEqual(report["benchmarks"][0]["observations"], [])

    def test_future_benchmark_observations_are_not_used_or_reported(self):
        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(),
            history=portfolio_history(),
            goals=[],
            benchmarks=[
                {
                    "id": 1,
                    "benchmark_name": "Configured",
                    "benchmark_type": "USER_PROVIDED_VALUE",
                    "is_active": 1,
                }
            ],
            observations_by_benchmark={
                1: [
                    {"date": "2026-01-01", "value": 100},
                    {"date": "2999-01-01", "value": 200},
                ]
            },
            as_of_date=date(2026, 1, 2),
        )
        self.assertEqual(
            report["benchmarks"][0]["observations"],
            [{"date": "2026-01-01", "value": 100.0}],
        )
        self.assertFalse(report["benchmarks"][0]["comparison"]["available"])

    def test_inactive_goals_and_benchmarks_are_excluded(self):
        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(),
            history=[],
            goals=[{**goal_record(), "is_active": 0}],
            benchmarks=[
                {
                    "id": 1,
                    "benchmark_name": "Inactive",
                    "benchmark_type": "USER_PROVIDED_VALUE",
                    "is_active": 0,
                }
            ],
            observations_by_benchmark={},
            as_of_date=date(2026, 1, 2),
        )
        self.assertEqual(report["goals"], [])
        self.assertEqual(report["benchmarks"], [])


class GoalsIntegrationTests(unittest.TestCase):
    def test_dashboard_receives_report_and_has_forms_and_tables(self):
        from dashboard import app as dashboard_module

        expected = {
            "active_goal_count": 1,
            "latest_portfolio_value": 1200,
            "goals": [],
            "benchmarks": [],
        }
        dashboard_data = {
            "portfolio": {"positions": {}, "total_current_value": 1200},
            "analytics": {
                "allocation": {},
                "concentration": {},
                "max_drawdown": {},
            },
            "historical": {"history": []},
        }
        connection = Mock()
        connection.execute.return_value.fetchall.return_value = []
        with (
            patch.object(dashboard_module, "get_dashboard_data", return_value=dashboard_data),
            patch.object(dashboard_module, "get_portfolio_alerts", return_value=[]),
            patch.object(dashboard_module, "get_portfolio_change_report", return_value={"available": False, "alerts": []}),
            patch.object(dashboard_module, "get_portfolio_snapshots", return_value=[]),
            patch.object(dashboard_module, "generate_portfolio_intelligence", return_value={}),
            patch.object(dashboard_module, "generate_risk_intelligence", return_value={}),
            patch.object(dashboard_module, "generate_performance_attribution", return_value={}),
            patch.object(dashboard_module, "generate_historical_analytics", return_value={}),
            patch.object(dashboard_module, "generate_goals_intelligence", return_value=expected),
            patch.object(dashboard_module, "get_company_news", return_value=[]),
            patch.object(dashboard_module.sqlite3, "connect", return_value=connection),
            patch.object(dashboard_module, "generate_portfolio_analysis", return_value=""),
            patch.object(dashboard_module, "render_template", return_value="dashboard") as render,
        ):
            dashboard_module._render_dashboard()
        self.assertEqual(render.call_args.kwargs["goals_intelligence"], expected)
        source, _, _ = dashboard_module.app.jinja_env.loader.get_source(
            dashboard_module.app.jinja_env,
            "dashboard.html",
        )
        dashboard_module.app.jinja_env.get_template("dashboard.html")
        self.assertIn("Goals &amp; Benchmarks", source)
        self.assertIn('name="goal_name"', source)
        self.assertIn('name="benchmark_name"', source)
        self.assertIn('name="observation_date"', source)
        self.assertIn("Benchmark comparison unavailable.", source)

    def test_assistant_supplies_goal_report_and_answers_goal_questions_deterministically(self):
        from investment_assistant import assistant

        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(),
            history=[],
            goals=[goal_record(target_value=1500)],
            benchmarks=[],
            as_of_date=date(2026, 1, 2),
        )
        with (
            patch.object(assistant.portfolio, "get_transactions", return_value=[]),
            patch.object(assistant.portfolio, "get_opening_positions", return_value=[]),
            patch.object(assistant.portfolio, "calculate_portfolio_valuation", return_value=portfolio_value()),
            patch.object(assistant.portfolio, "get_portfolio_analytics_summary", return_value={"allocation": {}, "concentration": {}}),
            patch.object(assistant.portfolio, "get_portfolio_performance_history", return_value=[]),
            patch.object(assistant.portfolio, "get_portfolio_snapshots", return_value=[]),
            patch.object(assistant.portfolio, "get_historical_performance_summary", return_value={}),
            patch.object(assistant.portfolio, "calculate_max_drawdown", return_value={}),
            patch.object(assistant.alerts, "get_portfolio_change_report", return_value={"available": False}),
            patch.object(assistant.performance_attribution, "generate_performance_attribution", return_value={}),
            patch.object(assistant.risk_intelligence, "generate_risk_intelligence", return_value={}),
            patch.object(assistant.historical_analytics, "generate_historical_analytics", return_value={}),
            patch.object(assistant.goals_intelligence, "generate_goals_intelligence", return_value=report),
            patch.object(assistant.intelligence, "generate_portfolio_intelligence", return_value={}),
            patch.object(assistant.ai_analysis, "generate_portfolio_answer") as answer,
        ):
            response = assistant.answer_portfolio_question(
                "How much remains to reach my portfolio goal?"
            )
        self.assertIn("Remaining amount: ₹300.00", response)
        answer.assert_not_called()

    def test_assistant_adds_structured_goals_to_gemini_context_for_other_questions(self):
        from investment_assistant import assistant

        expected = {"goals": [{"goal_name": "Target"}], "benchmarks": []}
        with (
            patch.object(assistant.portfolio, "get_transactions", return_value=[]),
            patch.object(assistant.portfolio, "get_opening_positions", return_value=[]),
            patch.object(assistant.portfolio, "calculate_portfolio_valuation", return_value=portfolio_value()),
            patch.object(assistant.portfolio, "get_portfolio_analytics_summary", return_value={"allocation": {}, "concentration": {}}),
            patch.object(assistant.portfolio, "get_portfolio_performance_history", return_value=[]),
            patch.object(assistant.portfolio, "get_portfolio_snapshots", return_value=[]),
            patch.object(assistant.portfolio, "get_historical_performance_summary", return_value={}),
            patch.object(assistant.portfolio, "calculate_max_drawdown", return_value={}),
            patch.object(assistant.alerts, "get_portfolio_change_report", return_value={"available": False}),
            patch.object(assistant.performance_attribution, "generate_performance_attribution", return_value={}),
            patch.object(assistant.risk_intelligence, "generate_risk_intelligence", return_value={}),
            patch.object(assistant.historical_analytics, "generate_historical_analytics", return_value={}),
            patch.object(assistant.goals_intelligence, "generate_goals_intelligence", return_value=expected),
            patch.object(assistant.intelligence, "generate_portfolio_intelligence", return_value={}),
            patch.object(assistant.ai_analysis, "generate_portfolio_answer", return_value="summary") as answer,
        ):
            assistant.answer_portfolio_question("Summarize the available portfolio facts.")
        self.assertEqual(
            answer.call_args.args[1]["goals_intelligence"],
            expected,
        )

    def test_gemini_context_has_goal_safety_rules(self):
        from investment_assistant import ai_analysis

        report = {"goals": [], "benchmarks": []}
        with (
            patch.object(ai_analysis, "GEMINI_API_KEY", "test-key"),
            patch.object(ai_analysis, "_request_gemini", return_value="answer") as request,
        ):
            ai_analysis.generate_portfolio_answer(
                "What are my goals?",
                {"goals_intelligence": report},
            )
        prompt = " ".join(request.call_args.args[0].split())
        self.assertIn('"goals_intelligence"', prompt)
        self.assertIn('"goals": []', prompt)
        self.assertIn("Never predict whether a goal will be reached", prompt)
        self.assertIn("never invent a goal or benchmark", prompt)
        self.assertIn("buy/sell/hold recommendations", prompt)

    def test_gemini_briefing_context_includes_goals_and_benchmark_rules(self):
        from investment_assistant import ai_analysis

        report = {
            "goals_intelligence": {
                "goals": [{"goal_name": "Configured target"}],
                "benchmarks": [],
            }
        }
        portfolio = {
            "positions": {},
            "total_invested": 0,
            "total_current_value": 0,
            "total_realized_pnl": 0,
            "total_unrealized_pnl": 0,
            "total_pnl": 0,
            "total_return_percent": 0,
        }
        with (
            patch.object(ai_analysis, "GEMINI_API_KEY", "test-key"),
            patch.object(ai_analysis, "_request_gemini", return_value="answer") as request,
        ):
            ai_analysis.generate_portfolio_analysis(
                portfolio,
                {},
                intelligence_report=report,
            )
        prompt = " ".join(request.call_args.args[0].split())
        self.assertIn('"goal_name": "Configured target"', prompt)
        self.assertIn("Never predict whether a goal will be reached", prompt)
        self.assertIn("Never assume a benchmark", prompt)
        self.assertIn("Do not claim outperformance", prompt)

    def test_briefing_includes_goals_and_benchmarks_before_ai_analysis(self):
        from investment_assistant import briefing

        expected = {
            "goals": [
                {
                    "goal_name": "Value target",
                    "target_type": "PORTFOLIO_VALUE",
                    "target_value": 1500,
                    "current_value": 1200,
                    "unit": "currency",
                    "difference": -300,
                    "difference_unit": "currency",
                    "progress_percent": 80,
                    "remaining_amount": 300,
                    "target_date": "2027-01-01",
                    "target_date_status": "Target date has not yet arrived.",
                    "status": "In progress",
                }
            ],
            "benchmarks": [],
        }
        portfolio = {
            "positions": {},
            "total_invested": 1000,
            "total_current_value": 1200,
            "total_realized_pnl": 0,
            "total_unrealized_pnl": 200,
            "total_pnl": 200,
            "total_return_percent": 20,
            "goals_intelligence": expected,
        }
        html = briefing.build_html_email(portfolio, "analysis")
        self.assertIn("Goals &amp; Benchmarks", html)
        self.assertIn("Value target", html)
        self.assertIn("No portfolio benchmarks configured.", html)
        self.assertLess(html.index("Goals &amp; Benchmarks"), html.index("AI Analysis"))
        self.assertNotIn("No portfolio goals configured.", html)

    def test_briefing_generates_and_supplies_structured_goals_report(self):
        from investment_assistant import briefing

        expected = {"goals": [{"goal_name": "Synthetic goal"}], "benchmarks": []}
        portfolio = {
            "positions": {},
            "total_invested": 1000,
            "total_current_value": 1200,
            "total_realized_pnl": 0,
            "total_unrealized_pnl": 200,
            "total_pnl": 200,
            "total_return_percent": 20,
        }
        history = portfolio_history()
        with (
            patch.object(briefing, "calculate_portfolio_valuation", return_value=portfolio),
            patch.object(briefing, "save_portfolio_snapshot"),
            patch.object(briefing, "get_portfolio_snapshots", return_value=[]),
            patch.object(briefing, "get_portfolio_performance_history", return_value=history),
            patch.object(briefing, "get_historical_performance_summary", return_value={}),
            patch.object(briefing, "calculate_portfolio_changes", return_value={"available": False}),
            patch.object(briefing, "generate_performance_attribution", return_value={}),
            patch.object(briefing, "get_transactions", return_value=[]),
            patch.object(briefing, "generate_historical_analytics", return_value={}),
            patch.object(briefing, "generate_portfolio_intelligence", return_value={}),
            patch.object(briefing, "get_portfolio_analytics_summary", return_value={}),
            patch.object(briefing, "generate_risk_intelligence", return_value={}),
            patch.object(briefing, "generate_goals_intelligence", return_value=expected) as generate_goals,
            patch.object(briefing, "generate_portfolio_analysis", return_value="Summary") as analysis,
        ):
            result, _, _ = briefing.build_briefing(news_overrides={})
        self.assertEqual(result["goals_intelligence"], expected)
        self.assertEqual(
            analysis.call_args.kwargs["intelligence_report"]["goals_intelligence"],
            expected,
        )
        self.assertEqual(
            generate_goals.call_args.kwargs["history"],
            history,
        )

    def test_empty_goals_and_benchmarks_have_explicit_briefing_messages(self):
        from investment_assistant.briefing import _build_goals_intelligence_html

        html = _build_goals_intelligence_html({"goals": [], "benchmarks": []})
        self.assertIn("No portfolio goals configured.", html)
        self.assertIn("No portfolio benchmarks configured.", html)

    def test_goal_reports_and_prompt_do_not_make_recommendations_or_predictions(self):
        report = goals.generate_goals_intelligence(
            portfolio_data=portfolio_value(),
            history=[],
            goals=[goal_record()],
            benchmarks=[],
            as_of_date=date(2026, 1, 2),
        )
        rendered = str(report)
        for forbidden in (
            "buy recommendation",
            "sell recommendation",
            "hold recommendation",
            "likely to reach",
            "will reach",
            "On track",
            "Off track",
        ):
            self.assertNotIn(forbidden.casefold(), rendered.casefold())

    def test_dashboard_routes_validate_and_add_goal_and_benchmark_data(self):
        from dashboard import app as dashboard_module

        dashboard_module.app.config.update(TESTING=True)
        client = dashboard_module.app.test_client()
        with (
            patch.object(dashboard_module, "create_portfolio_goal", return_value=1) as create_goal,
            patch.object(dashboard_module, "create_portfolio_benchmark", return_value=2) as create_benchmark,
            patch.object(dashboard_module, "add_benchmark_observation") as add_observation,
        ):
            response = client.post(
                "/portfolio-goal",
                data={
                    "goal_name": "Target",
                    "target_type": "PORTFOLIO_VALUE",
                    "target_value": "1500",
                    "target_date": "2027-01-01",
                },
            )
            self.assertEqual(response.status_code, 302)
            create_goal.assert_called_once_with(
                goal_name="Target",
                target_type="PORTFOLIO_VALUE",
                target_value=1500.0,
                target_date="2027-01-01",
            )
            client.post(
                "/portfolio-benchmark",
                data={
                    "benchmark_name": "User index",
                    "benchmark_symbol": "",
                    "benchmark_type": "USER_PROVIDED_VALUE",
                },
            )
            create_benchmark.assert_called_once_with(
                benchmark_name="User index",
                benchmark_symbol=None,
                benchmark_type="USER_PROVIDED_VALUE",
            )
            client.post(
                "/portfolio-benchmark-observation",
                data={
                    "benchmark_id": "2",
                    "observation_date": "2026-01-01",
                    "value": "100",
                },
            )
            add_observation.assert_called_once_with(
                benchmark_id=2,
                observation_date="2026-01-01",
                value=100.0,
            )

    def test_invalid_dashboard_goal_form_reports_validation_error(self):
        from dashboard import app as dashboard_module

        dashboard_module.app.config.update(TESTING=True)
        client = dashboard_module.app.test_client()
        with patch.object(
            dashboard_module,
            "create_portfolio_goal",
            side_effect=ValueError("Target type is not supported."),
        ):
            response = client.post(
                "/portfolio-goal",
                data={
                    "goal_name": "Target",
                    "target_type": "INVALID",
                    "target_value": "100",
                },
            )
        self.assertEqual(response.status_code, 302)
        with client.session_transaction() as flask_session:
            self.assertEqual(
                flask_session["_flashes"][0][1],
                "Target type is not supported.",
            )

    def test_unrelated_target_price_question_is_not_misclassified_as_a_goal(self):
            from investment_assistant.assistant import _goals_question_answer

            self.assertIsNone(
                _goals_question_answer(
                    "What is the target price?",
                    {"goals": [], "benchmarks": []},
                )
            )

    def test_return_goal_difference_is_reported_in_percentage_points(self):
            from investment_assistant.assistant import _goals_question_answer

            report = goals.generate_goals_intelligence(
                portfolio_data=portfolio_value(return_percent=20),
                history=[],
                goals=[
                    goal_record(
                        "RETURN_PERCENT",
                        25,
                        goal_name="Return target",
                    )
                ],
                benchmarks=[],
                as_of_date=date(2026, 1, 2),
            )
            answer = _goals_question_answer(
                "What is my portfolio return target?",
                report,
            )
            self.assertIn("difference -5.00 pp", answer)


if __name__ == "__main__":
    unittest.main()
