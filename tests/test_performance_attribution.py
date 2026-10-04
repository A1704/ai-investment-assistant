import json
import unittest
from unittest.mock import Mock, patch

from investment_assistant.performance_attribution import (
    INSUFFICIENT_DETAIL_MESSAGE,
    INSUFFICIENT_HISTORY_MESSAGE,
    PRICE_ATTRIBUTION_UNAVAILABLE_MESSAGE,
    generate_performance_attribution,
)


def detail(
    symbol,
    company,
    quantity,
    price,
    value,
    allocation,
):
    return {
        symbol: {
            "symbol": symbol,
            "company_name": company,
            "quantity": quantity,
            "current_price": price,
            "market_value": value,
            "allocation_percent": allocation,
        }
    }


def snapshot(date, value, pnl, holdings=None):
    return {
        "date": date,
        "total_current_value": value,
        "total_pnl": pnl,
        "holding_snapshot_json": (
            json.dumps(holdings) if holdings is not None else None
        ),
    }


class PerformanceAttributionTests(unittest.TestCase):
    def test_no_historical_snapshots(self):
        report = generate_performance_attribution(snapshots=[], transactions=[])

        self.assertFalse(report["available"])
        self.assertEqual(report["reason"], INSUFFICIENT_HISTORY_MESSAGE)
        self.assertIsNone(report["portfolio_movement"])

    def test_only_one_snapshot(self):
        report = generate_performance_attribution(
            snapshots=[snapshot("2026-01-01", 1000, 100)],
            transactions=[],
        )

        self.assertFalse(report["available"])
        self.assertEqual(report["reason"], INSUFFICIENT_HISTORY_MESSAGE)

    def test_aggregate_only_snapshots_preserve_aggregate_comparison(self):
        report = generate_performance_attribution(
            snapshots=[
                snapshot("2026-01-01", 1000, 100),
                snapshot("2026-01-02", 1200, 150),
            ],
            transactions=[],
        )

        self.assertTrue(report["available"])
        self.assertEqual(report["portfolio_movement"]["value_change"], 200)
        self.assertFalse(report["holding_attribution"]["available"])
        self.assertEqual(
            report["holding_attribution"]["reason"],
            INSUFFICIENT_DETAIL_MESSAGE,
        )
        self.assertIsNone(report["summary"]["holding_market_value_change_sum"])

    def test_two_detailed_snapshots_compare_all_movement_fields(self):
        report = generate_performance_attribution(
            snapshots=[
                snapshot("2026-01-01", 1000, 100, detail("AAA", "Alpha", 10, 100, 1000, 100)),
                snapshot("2026-01-02", 1100, 125, detail("AAA", "Alpha", 10, 110, 1100, 100)),
            ],
            transactions=[],
        )

        self.assertTrue(report["available"])
        self.assertEqual(
            report["portfolio_movement"],
            {
                "previous_date": "2026-01-01",
                "latest_date": "2026-01-02",
                "previous_value": 1000,
                "latest_value": 1100,
                "value_change": 100,
                "value_change_percent": 10,
                "previous_total_pnl": 100,
                "latest_total_pnl": 125,
                "total_pnl_change": 25,
            },
        )
        self.assertTrue(report["holding_attribution"]["available"])
        holding = report["holding_attribution"]["holdings"][0]
        self.assertEqual(holding["previous_market_value"], 1000)
        self.assertEqual(holding["latest_market_value"], 1100)
        self.assertEqual(holding["market_value_change"], 100)
        self.assertEqual(holding["market_value_change_percent"], 10)

    def test_positive_contribution(self):
        report = generate_performance_attribution(
            snapshots=[
                snapshot("2026-01-01", 1000, 0, detail("AAA", "Alpha", 10, 100, 1000, 100)),
                snapshot("2026-01-02", 1200, 0, detail("AAA", "Alpha", 10, 120, 1200, 100)),
            ],
            transactions=[],
        )

        summary = report["summary"]
        self.assertEqual(summary["largest_positive_contributor"]["symbol"], "AAA")
        self.assertEqual(
            summary["largest_positive_contributor"]["market_value_change"],
            200,
        )
        self.assertEqual(
            summary["increased_value_holdings"],
            ["AAA"],
        )

    def test_negative_contribution(self):
        report = generate_performance_attribution(
            snapshots=[
                snapshot("2026-01-01", 1000, 0, detail("AAA", "Alpha", 10, 100, 1000, 100)),
                snapshot("2026-01-02", 800, 0, detail("AAA", "Alpha", 10, 80, 800, 100)),
            ],
            transactions=[],
        )

        self.assertEqual(report["summary"]["largest_negative_contributor"]["symbol"], "AAA")
        self.assertEqual(report["summary"]["decreased_value_holdings"], ["AAA"])

    def test_multiple_contributors_and_reconciliation(self):
        before = {
            **detail("AAA", "Alpha", 10, 100, 1000, 66.6667),
            **detail("BBB", "Beta", 10, 50, 500, 33.3333),
        }
        after = {
            **detail("AAA", "Alpha", 10, 110, 1100, 68.75),
            **detail("BBB", "Beta", 10, 50, 500, 31.25),
        }
        report = generate_performance_attribution(
            snapshots=[
                snapshot("2026-01-01", 1500, 0, before),
                snapshot("2026-01-02", 1600, 0, after),
            ],
            transactions=[],
        )

        self.assertEqual(report["summary"]["increased_value_holdings"], ["AAA"])
        self.assertEqual(report["summary"]["unchanged_value_holdings"], ["BBB"])
        self.assertEqual(report["summary"]["holding_market_value_change_sum"], 100)
        self.assertEqual(report["summary"]["reconciliation_difference"], 0)
        self.assertTrue(report["summary"]["reconciles_to_portfolio_change"])
        self.assertAlmostEqual(
            report["holding_attribution"]["holdings"][0][
                "allocation_change_percentage_points"
            ],
            2.0833,
        )

    def test_added_holding(self):
        report = generate_performance_attribution(
            snapshots=[
                snapshot("2026-01-01", 1000, 0, detail("AAA", "Alpha", 10, 100, 1000, 100)),
                snapshot("2026-01-02", 1200, 0, {
                    **detail("AAA", "Alpha", 10, 100, 1000, 83.3333),
                    **detail("BBB", "Beta", 2, 100, 200, 16.6667),
                }),
            ],
            transactions=[],
        )

        self.assertEqual(report["summary"]["added_holdings"], ["BBB"])
        self.assertEqual(report["summary"]["increased_value_holdings"], ["BBB"])
        self.assertFalse(report["price_transaction_attribution"]["available"])

    def test_removed_holding(self):
        report = generate_performance_attribution(
            snapshots=[
                snapshot("2026-01-01", 1200, 0, {
                    **detail("AAA", "Alpha", 10, 100, 1000, 83.3333),
                    **detail("BBB", "Beta", 2, 100, 200, 16.6667),
                }),
                snapshot("2026-01-02", 1000, 0, detail("AAA", "Alpha", 10, 100, 1000, 100)),
            ],
            transactions=[],
        )

        self.assertEqual(report["summary"]["removed_holdings"], ["BBB"])
        self.assertEqual(report["summary"]["decreased_value_holdings"], ["BBB"])

    def test_quantity_change_is_reported_with_arithmetic_decomposition(self):
        report = generate_performance_attribution(
            snapshots=[
                snapshot("2026-01-01", 500, 0, detail("AAA", "Alpha", 5, 100, 500, 100)),
                snapshot("2026-01-02", 600, 0, detail("AAA", "Alpha", 6, 100, 600, 100)),
            ],
            transactions=[],
        )

        holding = report["holding_attribution"]["holdings"][0]
        self.assertEqual(holding["quantity_change"], 1)
        decomposition = report["price_transaction_attribution"]["holdings"][0]
        self.assertEqual(decomposition["quantity_related_movement"], 100)
        self.assertEqual(decomposition["price_related_movement"], 0)

    def test_price_change_is_reported_with_arithmetic_decomposition(self):
        report = generate_performance_attribution(
            snapshots=[
                snapshot("2026-01-01", 500, 0, detail("AAA", "Alpha", 5, 100, 500, 100)),
                snapshot("2026-01-02", 550, 0, detail("AAA", "Alpha", 5, 110, 550, 100)),
            ],
            transactions=[],
        )

        holding = report["holding_attribution"]["holdings"][0]
        self.assertEqual(holding["price_change"], 10)
        decomposition = report["price_transaction_attribution"]["holdings"][0]
        self.assertEqual(decomposition["price_related_movement"], 50)
        self.assertEqual(decomposition["quantity_related_movement"], 0)

    def test_allocation_change_is_reported(self):
        before = {
            **detail("AAA", "Alpha", 10, 100, 1000, 50),
            **detail("BBB", "Beta", 10, 100, 1000, 50),
        }
        after = {
            **detail("AAA", "Alpha", 10, 110, 1100, 55),
            **detail("BBB", "Beta", 10, 90, 900, 45),
        }
        report = generate_performance_attribution(
            snapshots=[
                snapshot("2026-01-01", 2000, 0, before),
                snapshot("2026-01-02", 2000, 0, after),
            ],
            transactions=[],
        )

        self.assertEqual(
            report["holding_attribution"]["holdings"][0][
                "allocation_change_percentage_points"
            ],
            5,
        )

    def test_contribution_reconciliation_difference_is_reported(self):
        report = generate_performance_attribution(
            snapshots=[
                snapshot("2026-01-01", 1000, 0, detail("AAA", "Alpha", 10, 100, 1000, 100)),
                snapshot("2026-01-02", 1150, 0, detail("AAA", "Alpha", 10, 110, 1100, 100)),
            ],
            transactions=[],
        )

        self.assertEqual(report["summary"]["reconciliation_difference"], 50)
        self.assertFalse(report["summary"]["reconciles_to_portfolio_change"])
        self.assertTrue(any("do not fully reconcile" in text for text in report["limitations"]))

    def test_missing_price_data_disables_price_decomposition(self):
        before = detail("AAA", "Alpha", 10, None, 1000, 100)
        after = detail("AAA", "Alpha", 10, 110, 1100, 100)
        report = generate_performance_attribution(
            snapshots=[
                snapshot("2026-01-01", 1000, 0, before),
                snapshot("2026-01-02", 1100, 0, after),
            ],
            transactions=[],
        )

        self.assertFalse(report["price_transaction_attribution"]["available"])
        self.assertEqual(
            report["price_transaction_attribution"]["reason"],
            PRICE_ATTRIBUTION_UNAVAILABLE_MESSAGE,
        )

    def test_latest_aggregate_without_details_does_not_borrow_older_history(self):
        report = generate_performance_attribution(
            snapshots=[
                snapshot("2026-01-01", 1000, 0, detail("AAA", "Alpha", 10, 100, 1000, 100)),
                snapshot("2026-01-02", 1100, 0),
                snapshot("2026-01-03", 1200, 0, detail("AAA", "Alpha", 10, 120, 1200, 100)),
            ],
            transactions=[],
        )

        self.assertFalse(report["holding_attribution"]["available"])
        self.assertEqual(report["portfolio_movement"]["previous_date"], "2026-01-02")

    def test_transactions_between_snapshots_are_factual_context(self):
        tx = [(1, "AAA", "Alpha", "BUY", 2, 100, "2026-01-02")]
        report = generate_performance_attribution(
            snapshots=[
                snapshot("2026-01-01", 500, 0, detail("AAA", "Alpha", 5, 100, 500, 100)),
                snapshot("2026-01-03", 700, 0, detail("AAA", "Alpha", 7, 100, 700, 100)),
            ],
            transactions=tx,
        )

        self.assertEqual(
            report["price_transaction_attribution"]["transactions_between_snapshots"],
            [{
                "symbol": "AAA",
                "company_name": "Alpha",
                "transaction_type": "BUY",
                "quantity": 2,
                "price": 100,
                "transaction_date": "2026-01-02",
            }],
        )
        self.assertIn(
            "not causal attribution",
            report["price_transaction_attribution"]["method"],
        )

    def test_added_removed_holdings_do_not_claim_price_causation(self):
        report = generate_performance_attribution(
            snapshots=[
                snapshot("2026-01-01", 500, 0, detail("AAA", "Alpha", 5, 100, 500, 100)),
                snapshot("2026-01-02", 500, 0, detail("BBB", "Beta", 5, 100, 500, 100)),
            ],
            transactions=[],
        )

        self.assertFalse(report["price_transaction_attribution"]["available"])
        self.assertIn("unavailable", report["price_transaction_attribution"]["reason"])

    def test_dashboard_supplies_attribution_report_and_template_section(self):
        from dashboard import app as dashboard_module

        dashboard_data = {
            "portfolio": {"positions": {}},
            "analytics": {
                "allocation": {},
                "concentration": {"holding_count": 0},
                "max_drawdown": {},
            },
            "historical": {"history": []},
        }
        connection = Mock()
        connection.execute.return_value.fetchall.return_value = []
        report = {"available": False, "reason": "Test history limitation."}
        with (
            patch.object(dashboard_module, "get_dashboard_data", return_value=dashboard_data),
            patch.object(dashboard_module, "get_portfolio_alerts", return_value=[]),
            patch.object(dashboard_module, "get_portfolio_change_report", return_value={"available": False, "alerts": []}),
            patch.object(dashboard_module, "get_portfolio_snapshots", return_value=[]),
            patch.object(dashboard_module, "get_company_news", return_value=[]),
            patch.object(dashboard_module.sqlite3, "connect", return_value=connection),
            patch.object(dashboard_module, "generate_portfolio_intelligence", return_value={}),
            patch.object(dashboard_module, "generate_risk_intelligence", return_value={}),
            patch.object(dashboard_module, "generate_performance_attribution", return_value=report),
            patch.object(dashboard_module, "generate_historical_analytics", return_value={}),
            patch.object(dashboard_module, "generate_goals_intelligence", return_value={"goals": [], "benchmarks": []}),
            patch.object(dashboard_module, "generate_portfolio_analysis", return_value=""),
            patch.object(dashboard_module, "render_template", return_value="dashboard") as render,
        ):
            dashboard_module._render_dashboard()

        self.assertEqual(render.call_args.kwargs["performance_attribution"], report)
        source, _, _ = dashboard_module.app.jinja_env.loader.get_source(
            dashboard_module.app.jinja_env,
            "dashboard.html",
        )
        self.assertIn("<h2>Performance Attribution</h2>", source)
        self.assertIn("Holding Contributions", source)
        self.assertIn("does not establish causation", source)

    def test_assistant_receives_structured_attribution_report(self):
        from investment_assistant import assistant

        report = {"available": False, "reason": INSUFFICIENT_DETAIL_MESSAGE}
        portfolio_data = {
            "positions": {},
            "total_invested": 0,
            "total_current_value": 0,
            "total_realized_pnl": 0,
            "total_unrealized_pnl": 0,
            "total_pnl": 0,
            "total_return_percent": None,
        }
        with (
            patch.object(assistant.portfolio, "get_transactions", return_value=[]),
            patch.object(assistant.portfolio, "get_opening_positions", return_value=[]),
            patch.object(assistant.portfolio, "calculate_portfolio_valuation", return_value=portfolio_data),
            patch.object(assistant.portfolio, "get_portfolio_analytics_summary", return_value={"allocation": {}, "concentration": {}}),
            patch.object(assistant.portfolio, "get_portfolio_performance_history", return_value=[]),
            patch.object(assistant.portfolio, "get_historical_performance_summary", return_value={}),
            patch.object(assistant.alerts, "get_portfolio_change_report", return_value={"available": False, "alerts": []}),
            patch.object(assistant.risk_intelligence, "generate_risk_intelligence", return_value={}),
            patch.object(assistant.performance_attribution, "generate_performance_attribution", return_value=report),
            patch.object(assistant.goals_intelligence, "generate_goals_intelligence", return_value={"goals": [], "benchmarks": []}),
            patch.object(assistant.intelligence, "generate_portfolio_intelligence", return_value={}),
            patch.object(assistant.ai_analysis, "generate_portfolio_answer", return_value="ok") as answer,
        ):
            assistant.answer_portfolio_question("Which holding contributed the most?")

        self.assertEqual(
            answer.call_args.args[1]["performance_attribution"],
            report,
        )

    def test_gemini_context_contains_attribution_and_no_causal_claim_rules(self):
        from investment_assistant import ai_analysis

        report = {
            "available": True,
            "summary": {
                "largest_positive_contributor": {
                    "symbol": "AAA",
                    "market_value_change": 200,
                }
            },
        }
        with (
            patch.object(ai_analysis, "GEMINI_API_KEY", "test-key"),
            patch.object(ai_analysis, "_request_gemini", return_value="answer") as request,
        ):
            ai_analysis.generate_portfolio_answer(
                "What contributed to the change?",
                {"performance_attribution": report},
            )

        prompt = request.call_args.args[0]
        normalized_prompt = " ".join(prompt.split())
        self.assertIn('"market_value_change": 200', prompt)
        self.assertIn(
            "never claim a holding or transaction caused a movement",
            normalized_prompt,
        )
        self.assertIn(
            "Never invent historical values, transactions, or causes",
            normalized_prompt,
        )

    def test_briefing_renders_and_propagates_attribution(self):
        from investment_assistant import briefing

        report = generate_performance_attribution(
            snapshots=[
                snapshot("2026-01-01", 1000, 0, detail("AAA", "Alpha", 10, 100, 1000, 100)),
                snapshot("2026-01-02", 1200, 0, detail("AAA", "Alpha", 10, 120, 1200, 100)),
            ],
            transactions=[],
        )
        portfolio_data = {
            "positions": {},
            "total_invested": 0,
            "total_current_value": 0,
            "total_realized_pnl": 0,
            "total_unrealized_pnl": 0,
            "total_pnl": 0,
            "total_return_percent": None,
        }
        with (
            patch.object(briefing, "calculate_portfolio_valuation", return_value=portfolio_data),
            patch.object(briefing, "save_portfolio_snapshot"),
            patch.object(briefing, "get_portfolio_snapshots", return_value=[]),
            patch.object(briefing, "get_transactions", return_value=[]),
            patch.object(briefing, "get_company_news", return_value=[]),
            patch.object(briefing, "calculate_portfolio_changes", return_value={"available": False, "alerts": []}),
            patch.object(briefing, "generate_portfolio_intelligence", return_value={}),
            patch.object(briefing, "get_portfolio_analytics_summary", return_value={"allocation": {}, "concentration": {}, "max_drawdown": {}}),
            patch.object(briefing, "generate_risk_intelligence", return_value={}),
            patch.object(briefing, "generate_goals_intelligence", return_value={"goals": [], "benchmarks": []}),
            patch.object(briefing, "generate_performance_attribution", return_value=report) as attribution,
            patch.object(briefing, "generate_portfolio_analysis", return_value="Synthetic briefing") as analysis,
        ):
            result, _, _ = briefing.build_briefing(news_overrides={})

        self.assertEqual(result["performance_attribution"], report)
        self.assertEqual(
            analysis.call_args.kwargs["intelligence_report"]["performance_attribution"],
            report,
        )
        attribution.assert_called_once()
        email = briefing.build_html_email(result, "Synthetic briefing")
        self.assertIn("<h2>Performance Attribution</h2>", email)
        self.assertIn("Largest positive contributor to the observed change", email)
        self.assertIn("not evidence of causation", email)

    def test_briefing_shows_unavailable_detail_limitation(self):
        from investment_assistant.briefing import _build_performance_attribution_html

        report = generate_performance_attribution(
            snapshots=[
                snapshot("2026-01-01", 1000, 0),
                snapshot("2026-01-02", 1200, 0),
            ],
            transactions=[],
        )
        html = _build_performance_attribution_html(report)
        self.assertIn(INSUFFICIENT_DETAIL_MESSAGE, html)
        self.assertIn(PRICE_ATTRIBUTION_UNAVAILABLE_MESSAGE, html)


if __name__ == "__main__":
    unittest.main()
