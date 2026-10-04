import unittest
from unittest.mock import Mock, patch

from investment_assistant.risk_intelligence import (
    INSUFFICIENT_HISTORY_MESSAGE,
    generate_risk_intelligence,
)


def portfolio_fixture():
    return {
        "positions": {
            "AAA": {
                "symbol": "AAA",
                "company_name": "Alpha Ltd",
                "quantity": 10,
                "current_price": 60,
                "current_value": 600,
                "remaining_cost_basis": 500,
                "unrealized_pnl": 100,
                "total_pnl": 120,
                "source": "test-feed",
            },
            "BBB": {
                "symbol": "BBB",
                "company_name": "Beta Ltd",
                "quantity": 20,
                "current_price": 20,
                "current_value": 400,
                "remaining_cost_basis": 450,
                "unrealized_pnl": -50,
                "total_pnl": -40,
                "source": "test-feed",
            },
        },
        "total_invested": 950,
        "total_current_value": 1000,
        "total_realized_pnl": 30,
        "total_unrealized_pnl": 50,
        "total_pnl": 80,
        "total_return_percent": 5.26,
    }


def analytics_fixture():
    return {
        "allocation": {
            "AAA": {"current_value": 600, "allocation_percent": 60},
            "BBB": {"current_value": 400, "allocation_percent": 40},
        },
        "concentration": {
            "holding_count": 2,
            "largest_holding_symbol": "AAA",
            "largest_holding_percent": 60,
        },
        "max_drawdown": {
            "max_drawdown_amount": 30,
            "max_drawdown_percent": 25,
            "peak_date": "2026-01-02",
            "trough_date": "2026-01-03",
        },
    }


class RiskIntelligenceTests(unittest.TestCase):
    def test_empty_portfolio_and_insufficient_history_are_explicit(self):
        report = generate_risk_intelligence(
            portfolio_data={"positions": {}, "total_current_value": 0},
            analytics={"allocation": {}, "concentration": {}},
            performance_history=[],
            historical_summary={},
        )

        self.assertEqual(report["portfolio_concentration"]["number_of_holdings"], 0)
        self.assertIsNone(
            report["portfolio_concentration"]["hhi_style_concentration_index"]
        )
        self.assertFalse(report["historical_risk"]["available"])
        self.assertEqual(
            report["historical_risk"]["limitation"],
            INSUFFICIENT_HISTORY_MESSAGE,
        )
        self.assertEqual(report["holding_exposure"], [])

    def test_allocation_largest_smallest_and_hhi_are_deterministic(self):
        report = generate_risk_intelligence(
            portfolio_data=portfolio_fixture(),
            analytics=analytics_fixture(),
            performance_history=[],
            historical_summary={},
        )
        concentration = report["portfolio_concentration"]

        self.assertEqual(concentration["total_portfolio_value"], 1000)
        self.assertEqual(concentration["number_of_holdings"], 2)
        self.assertEqual(concentration["largest_holding_symbol"], "AAA")
        self.assertEqual(concentration["largest_holding_percentage"], 60)
        self.assertEqual(concentration["smallest_holding_symbol"], "BBB")
        self.assertEqual(concentration["smallest_holding_percentage"], 40)
        self.assertEqual(concentration["hhi_style_concentration_index"], 5200)
        self.assertEqual(
            [item["allocation_percent"] for item in concentration["allocations"]],
            [60, 40],
        )

    def test_historical_extremes_change_and_drawdown_reuse_supplied_facts(self):
        history = [
            {"date": "2026-01-01", "total_current_value": 100},
            {"date": "2026-01-02", "total_current_value": 120},
            {"date": "2026-01-03", "total_current_value": 90},
        ]
        summary = {
            "highest_value": 120,
            "highest_value_date": "2026-01-02",
            "lowest_value": 90,
            "lowest_value_date": "2026-01-03",
        }

        report = generate_risk_intelligence(
            portfolio_data=portfolio_fixture(),
            analytics=analytics_fixture(),
            performance_history=history,
            historical_summary=summary,
        )
        historical = report["historical_risk"]

        self.assertTrue(historical["available"])
        self.assertEqual(historical["highest_recorded_value"], 120)
        self.assertEqual(historical["lowest_recorded_value"], 90)
        self.assertEqual(historical["latest_previous_value_change"], -30)
        self.assertAlmostEqual(
            historical["latest_previous_value_change_percent"],
            -25,
        )
        self.assertEqual(
            historical["maximum_drawdown"],
            analytics_fixture()["max_drawdown"],
        )

    def test_missing_current_price_is_counted_and_reported(self):
        portfolio_data = portfolio_fixture()
        portfolio_data["positions"]["BBB"]["current_price"] = None
        report = generate_risk_intelligence(
            portfolio_data=portfolio_data,
            analytics=analytics_fixture(),
            performance_history=[],
            historical_summary={},
        )

        self.assertEqual(report["data_quality"]["valid_current_price_count"], 1)
        self.assertEqual(
            report["data_quality"]["unavailable_current_price_count"],
            1,
        )
        self.assertIsNone(report["holding_exposure"][1]["current_price"])
        self.assertTrue(any(
            "unavailable current prices" in item
            for item in report["data_quality"]["limitations"]
        ))
        self.assertEqual(
            report["data_quality"]["market_data_sources"],
            ["test-feed"],
        )

    def test_company_names_fall_back_to_existing_portfolio_records(self):
        positions = portfolio_fixture()
        expected_names = {
            "COCHINSHIP": "Cochin Shipyard Limited",
            "HINDZINC": "Hindustan Zinc Limited",
            "SILVERBEES": "Nippon India Silver ETF",
        }
        renamed_positions = {}
        for symbol, company_name in expected_names.items():
            position = dict(positions["positions"]["AAA"])
            position.pop("company_name")
            renamed_positions[symbol] = position
        positions["positions"] = renamed_positions

        with (
            patch(
                "investment_assistant.risk_intelligence.portfolio.get_opening_positions",
                return_value=[],
            ),
            patch(
                "investment_assistant.risk_intelligence.portfolio.get_transactions",
                return_value=[
                    (1, symbol, company_name, "BUY", 10, 50, "2026-01-01")
                    for symbol, company_name in expected_names.items()
                ],
            ),
        ):
            report = generate_risk_intelligence(
                portfolio_data=positions,
                analytics=analytics_fixture(),
                performance_history=[],
                historical_summary={},
            )

        company_names = {
            holding["symbol"]: holding["company_name"]
            for holding in report["holding_exposure"]
        }
        self.assertEqual(company_names, expected_names)

    def test_position_company_name_is_preferred_and_missing_name_stays_missing(self):
        positions = portfolio_fixture()
        positions["positions"]["BBB"].pop("company_name")

        with (
            patch(
                "investment_assistant.risk_intelligence.portfolio.get_opening_positions",
                return_value=[],
            ),
            patch(
                "investment_assistant.risk_intelligence.portfolio.get_transactions",
                return_value=[],
            ),
        ):
            report = generate_risk_intelligence(
                portfolio_data=positions,
                analytics=analytics_fixture(),
                performance_history=[],
                historical_summary={},
            )

        company_names = {
            holding["symbol"]: holding["company_name"]
            for holding in report["holding_exposure"]
        }
        self.assertEqual(company_names["AAA"], "Alpha Ltd")
        self.assertIsNone(company_names["BBB"])

    def test_old_snapshots_or_missing_history_do_not_create_metrics(self):
        report = generate_risk_intelligence(
            portfolio_data=portfolio_fixture(),
            analytics=analytics_fixture(),
            performance_history=[{"date": "2026-01-01"}],
            historical_summary={"highest_value": 100},
        )

        self.assertEqual(report["historical_risk"]["snapshot_count"], 1)
        self.assertIsNone(report["historical_risk"]["highest_recorded_value"])
        self.assertIsNone(report["historical_risk"]["maximum_drawdown"])
        self.assertEqual(
            report["data_quality"]["snapshot_dates_used"],
            ["2026-01-01"],
        )

    def test_classifications_are_not_invented(self):
        report = generate_risk_intelligence(
            portfolio_data=portfolio_fixture(),
            analytics=analytics_fixture(),
            performance_history=[],
            historical_summary={},
        )
        composition = report["portfolio_composition"]

        self.assertEqual(composition["available_classifications"], [])
        self.assertIn("not available", composition["classification_message"])
        self.assertEqual(len(composition["holdings_by_symbol"]), 2)

    def test_calculation_does_not_write_snapshots_or_transactions(self):
        with (
            patch(
                "investment_assistant.risk_intelligence.portfolio.save_portfolio_snapshot"
            ) as save_snapshot,
            patch(
                "investment_assistant.risk_intelligence.portfolio.add_transaction"
            ) as add_transaction,
        ):
            generate_risk_intelligence(
                portfolio_data=portfolio_fixture(),
                analytics=analytics_fixture(),
                performance_history=[],
                historical_summary={},
            )

        save_snapshot.assert_not_called()
        add_transaction.assert_not_called()

    def test_dashboard_supplies_structured_risk_report(self):
        from dashboard import app as dashboard_module

        dashboard_data = {
            "portfolio": portfolio_fixture(),
            "analytics": analytics_fixture(),
            "historical": {
                "history": [],
                "highest_value": None,
                "lowest_value": None,
            },
        }
        connection = Mock()
        connection.execute.return_value.fetchall.return_value = []
        with (
            patch.object(dashboard_module, "get_dashboard_data", return_value=dashboard_data),
            patch.object(dashboard_module, "get_portfolio_alerts", return_value=[]),
            patch.object(dashboard_module, "get_portfolio_snapshots", return_value=[]),
            patch.object(
                dashboard_module,
                "get_portfolio_change_report",
                return_value={"available": False, "alerts": []},
            ),
            patch.object(dashboard_module, "get_company_news", return_value=[]),
            patch.object(dashboard_module.sqlite3, "connect", return_value=connection),
            patch.object(
                dashboard_module,
                "generate_portfolio_intelligence",
                return_value={},
            ),
            patch.object(dashboard_module, "generate_performance_attribution", return_value={}),
            patch.object(dashboard_module, "generate_historical_analytics", return_value={}),
            patch.object(dashboard_module, "generate_goals_intelligence", return_value={"goals": [], "benchmarks": []}),
            patch.object(dashboard_module, "generate_portfolio_analysis", return_value=""),
            patch.object(
                dashboard_module,
                "render_template",
                return_value="dashboard",
            ) as render,
        ):
            dashboard_module._render_dashboard()

        supplied = render.call_args.kwargs["risk_intelligence"]
        self.assertEqual(
            supplied["portfolio_concentration"]["hhi_style_concentration_index"],
            5200,
        )

    def test_assistant_context_contains_python_risk_report(self):
        from investment_assistant import assistant

        expected = {"portfolio_concentration": {"number_of_holdings": 2}}
        with (
            patch.object(assistant.portfolio, "calculate_portfolio_valuation", return_value=portfolio_fixture()),
            patch.object(assistant.portfolio, "get_portfolio_analytics_summary", return_value=analytics_fixture()),
            patch.object(assistant.portfolio, "get_portfolio_performance_history", return_value=[]),
            patch.object(assistant.portfolio, "get_historical_performance_summary", return_value={}),
            patch.object(assistant.portfolio, "get_transactions", return_value=[]),
            patch.object(assistant.portfolio, "get_opening_positions", return_value=[]),
            patch.object(assistant.alerts, "get_portfolio_change_report", return_value={"available": False}),
            patch.object(assistant.intelligence, "generate_portfolio_intelligence", return_value={}),
            patch.object(assistant.risk_intelligence, "generate_risk_intelligence", return_value=expected),
            patch.object(assistant.goals_intelligence, "generate_goals_intelligence", return_value={"goals": [], "benchmarks": []}),
            patch.object(assistant.ai_analysis, "generate_portfolio_answer", return_value="ok") as answer,
        ):
            assistant.answer_portfolio_question("How concentrated is my portfolio?")

        self.assertEqual(
            answer.call_args.args[1]["risk_intelligence"],
            expected,
        )

    def test_gemini_receives_report_and_safety_constraints(self):
        from investment_assistant import ai_analysis

        risk_report = {"portfolio_concentration": {"hhi_style_concentration_index": 5200}}
        with (
            patch.object(ai_analysis, "GEMINI_API_KEY", "test-key"),
            patch.object(ai_analysis, "_request_gemini", return_value="answer") as request,
        ):
            ai_analysis.generate_portfolio_answer(
                "What is my portfolio concentration?",
                {"risk_intelligence": risk_report},
            )

        prompt = request.call_args.args[0]
        self.assertIn('"hhi_style_concentration_index": 5200', prompt)
        self.assertIn("Do not invent sectors, industries, or asset classifications", prompt)
        self.assertIn("that concentration caused performance", prompt)

    def test_briefing_gemini_receives_risk_report_without_predictions(self):
        from investment_assistant import ai_analysis

        risk_report = {"portfolio_concentration": {"hhi_style_concentration_index": 5200}}
        portfolio_data = {
            "positions": {
                "AAA": {
                    "quantity": 1,
                    "average_buy_price": 10,
                    "current_price": 12,
                    "remaining_cost_basis": 10,
                    "current_value": 12,
                    "realized_pnl": 0,
                    "unrealized_pnl": 2,
                    "total_pnl": 2,
                    "return_percent": 20,
                }
            },
            "total_invested": 10,
            "total_current_value": 12,
            "total_realized_pnl": 0,
            "total_unrealized_pnl": 2,
            "total_pnl": 2,
            "total_return_percent": 20,
        }
        with (
            patch.object(ai_analysis, "GEMINI_API_KEY", "test-key"),
            patch.object(ai_analysis, "_request_gemini", return_value="briefing") as request,
        ):
            ai_analysis.generate_portfolio_analysis(
                portfolio_data,
                {},
                intelligence_report={"risk_intelligence": risk_report},
            )

        prompt = request.call_args.args[0]
        self.assertIn('"hhi_style_concentration_index": 5200', prompt)
        self.assertIn("Never predict target prices, future returns", prompt)
        self.assertIn("Never turn the measurements into buy, sell, or hold instructions", prompt)

    def test_briefing_contains_risk_section_and_limitation(self):
        from investment_assistant import briefing

        report = generate_risk_intelligence(
            portfolio_data=portfolio_fixture(),
            analytics=analytics_fixture(),
            performance_history=[],
            historical_summary={},
        )
        html = briefing._build_risk_intelligence_html(report)

        self.assertIn("Number of holdings", html)
        self.assertIn("Alpha Ltd", html)
        self.assertIn(INSUFFICIENT_HISTORY_MESSAGE, html)

    def test_briefing_builds_and_includes_risk_intelligence(self):
        from investment_assistant import briefing

        risk_report = generate_risk_intelligence(
            portfolio_data=portfolio_fixture(),
            analytics=analytics_fixture(),
            performance_history=[],
            historical_summary={},
        )
        with (
            patch.object(briefing, "calculate_portfolio_valuation", return_value=portfolio_fixture()),
            patch.object(briefing, "save_portfolio_snapshot"),
            patch.object(briefing, "get_company_news", return_value=[]),
            patch.object(briefing, "get_portfolio_snapshots", return_value=[]),
            patch.object(briefing, "calculate_portfolio_changes", return_value={"available": False, "alerts": []}),
            patch.object(briefing, "generate_portfolio_intelligence", return_value={}),
            patch.object(briefing, "get_portfolio_analytics_summary", return_value=analytics_fixture()),
            patch.object(briefing, "generate_risk_intelligence", return_value=risk_report) as risk_builder,
            patch.object(briefing, "generate_goals_intelligence", return_value={"goals": [], "benchmarks": []}),
            patch.object(briefing, "generate_portfolio_analysis", return_value="Synthetic explanation") as analysis,
        ):
            portfolio_data, _, explanation = briefing.build_briefing(
                price_overrides={"AAA": 60, "BBB": 20},
                news_overrides={},
            )

        self.assertEqual(portfolio_data["risk_intelligence"], risk_report)
        self.assertEqual(explanation, "Synthetic explanation")
        self.assertEqual(
            analysis.call_args.kwargs["intelligence_report"]["risk_intelligence"],
            risk_report,
        )
        self.assertEqual(
            risk_builder.call_args.kwargs["portfolio_data"]["positions"],
            portfolio_fixture()["positions"],
        )
        email = briefing.build_html_email(portfolio_data, explanation)
        self.assertIn("<h2>Risk &amp; Diversification</h2>", email)
        self.assertIn("Insufficient historical data for this metric.", email)

    def test_dashboard_template_has_human_readable_risk_section(self):
        from dashboard.app import app

        source, _, _ = app.jinja_env.loader.get_source(
            app.jinja_env,
            "dashboard.html",
        )
        self.assertIn("Risk &amp; Diversification", source)
        self.assertIn("Holding Exposure &amp; Allocation", source)
        self.assertIn("HHI-style", source)
        self.assertIn("Historical Data Available", source)


if __name__ == "__main__":
    unittest.main()
