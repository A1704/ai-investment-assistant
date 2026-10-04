import unittest
from unittest.mock import patch

from investment_assistant.intelligence import generate_portfolio_intelligence


PORTFOLIO_DATA = {
    "positions": {
        "ABC": {
            "symbol": "ABC",
            "company_name": "ABC Company",
            "quantity": 10,
            "current_price": 120,
            "current_value": 1200,
            "remaining_cost_basis": 1000,
            "realized_pnl": 30,
            "unrealized_pnl": 200,
            "total_pnl": 230,
            "return_percent": 20,
        },
        "XYZ": {
            "symbol": "XYZ",
            "company_name": "XYZ Ltd",
            "quantity": 4,
            "current_price": 50,
            "current_value": 200,
            "remaining_cost_basis": 160,
            "realized_pnl": 0,
            "unrealized_pnl": 40,
            "total_pnl": 40,
            "return_percent": 25,
        },
    },
    "total_invested": 1160,
    "total_current_value": 1400,
    "total_realized_pnl": 30,
    "total_unrealized_pnl": 240,
    "total_pnl": 270,
    "total_return_percent": 20.6896551724,
}

ANALYTICS = {
    "allocation": {
        "ABC": {"current_value": 1200, "allocation_percent": 85.714},
        "XYZ": {"current_value": 200, "allocation_percent": 14.286},
    },
    "concentration": {
        "holding_count": 2,
        "largest_holding_symbol": "ABC",
        "largest_holding_percent": 85.714,
        "largest_holding_value": 1200,
    },
    "max_drawdown": {
        "max_drawdown_amount": 125,
        "max_drawdown_percent": 10,
        "peak_date": "2026-09-20",
        "trough_date": "2026-09-25",
    },
}

DETAILED_CHANGES = {
    "available": True,
    "message": None,
    "latest_date": "2026-09-30",
    "previous_date": "2026-09-29",
    "portfolio_value": {
        "previous": 1300,
        "current": 1400,
        "change": 100,
        "change_percent": 7.6923,
    },
    "total_pnl": {"previous": 170, "current": 270, "change": 100},
    "holding_comparison_available": True,
    "holding_comparison_message": None,
    "holding_changes": [
        {
            "symbol": "ABC",
            "company_name": "ABC Company",
            "status": "changed",
            "previous_value": 1100,
            "current_value": 1200,
            "value_change": 100,
            "value_change_percent": 9.0909,
            "market_value_change": 100,
            "market_value_change_percent": 9.0909,
            "previous_unrealized_pnl": 100,
            "current_unrealized_pnl": 200,
            "unrealized_pnl_change": 100,
            "previous_total_pnl": 130,
            "current_total_pnl": 230,
            "total_pnl_change": 100,
            "previous_allocation_percent": 80,
            "current_allocation_percent": 85.714,
            "allocation_change_percentage_points": 5.714,
            "previous_quantity": 10,
            "current_quantity": 10,
            "quantity_change": 0,
            "previous_current_price": 110,
            "current_current_price": 120,
            "current_price_change": 10,
        },
    ],
    "concentration_changes": [
        {
            "symbol": "ABC",
            "previous_allocation_percent": 80,
            "current_allocation_percent": 85.714,
            "change_percentage_points": 5.714,
        },
    ],
    "alerts": [
        {
            "type": "holding_value",
            "severity": "IMPORTANT",
            "symbol": "ABC",
            "threshold": 5,
            "threshold_unit": "percent",
            "message": "ABC value changed by ₹100.00 (+9.09%).",
        }
    ],
}


class PortfolioIntelligenceTests(unittest.TestCase):
    def test_report_contains_overview_performance_concentration_and_alerts(self):
        report = generate_portfolio_intelligence(
            portfolio_data=PORTFOLIO_DATA,
            analytics=ANALYTICS,
            performance_history=[
                {"date": "2026-09-29"},
                {"date": "2026-09-30"},
            ],
            historical_summary={"latest_value": 1400},
            portfolio_changes=DETAILED_CHANGES,
            news_by_symbol={
                "ABC": [{
                    "title": "ABC reports a new contract",
                    "source": "Example News",
                    "published": "2026-09-30",
                    "link": "https://example.com/story",
                }],
            },
        )

        self.assertEqual(report["portfolio_overview"]["current_cost_basis"], 1160)
        self.assertEqual(report["portfolio_overview"]["current_portfolio_value"], 1400)
        self.assertEqual(report["portfolio_overview"]["realized_pnl"], 30)
        self.assertEqual(report["portfolio_overview"]["unrealized_pnl"], 240)
        self.assertEqual(report["portfolio_overview"]["total_pnl"], 270)
        self.assertEqual(report["portfolio_overview"]["holding_count"], 2)
        self.assertEqual(report["performance"]["latest_snapshot_date"], "2026-09-30")
        self.assertEqual(report["performance"]["max_drawdown"], ANALYTICS["max_drawdown"])
        self.assertEqual(report["holding_level_changes"]["items"][0]["symbol"], "ABC")
        self.assertEqual(report["concentration"]["largest_holding_symbol"], "ABC")
        self.assertEqual(report["alerts"][0]["severity"], "IMPORTANT")
        self.assertEqual(report["relevant_news"]["items"][0]["symbol"], "ABC")
        self.assertEqual(
            report["relevant_news"]["items"][0]["url"],
            "https://example.com/story",
        )

    def test_contributors_are_deterministic_and_labeled_as_movement_context(self):
        changes = dict(DETAILED_CHANGES)
        changes["holding_changes"] = [
            {
                **DETAILED_CHANGES["holding_changes"][0],
                "symbol": "ABC",
                "market_value_change": 100,
            },
            {
                **DETAILED_CHANGES["holding_changes"][0],
                "symbol": "XYZ",
                "company_name": "XYZ Ltd",
                "market_value_change": -60,
            },
            {
                **DETAILED_CHANGES["holding_changes"][0],
                "symbol": "DEF",
                "company_name": "DEF Inc",
                "market_value_change": 25,
            },
        ]
        report = generate_portfolio_intelligence(
            portfolio_data=PORTFOLIO_DATA,
            analytics=ANALYTICS,
            performance_history=[{}, {}],
            historical_summary={},
            portfolio_changes=changes,
            news_by_symbol={},
        )
        contributors = report["contributors"]
        self.assertEqual(contributors["largest_positive"]["symbol"], "ABC")
        self.assertEqual(contributors["largest_negative"]["symbol"], "XYZ")
        self.assertIn("not causation", contributors["method"])

    def test_no_historical_or_news_data_is_explicit(self):
        changes = {
            "available": False,
            "message": "Not enough historical snapshots.",
            "holding_comparison_available": False,
            "holding_comparison_message": "Detailed history unavailable.",
            "alerts": [],
            "holding_changes": [],
            "concentration_changes": [],
        }
        report = generate_portfolio_intelligence(
            portfolio_data=PORTFOLIO_DATA,
            analytics=ANALYTICS,
            performance_history=[{"date": "2026-09-30"}],
            historical_summary={},
            portfolio_changes=changes,
            news_by_symbol={},
        )

        self.assertFalse(report["performance"]["available"])
        self.assertIsNone(report["contributors"])
        self.assertFalse(report["holding_level_changes"]["available"])
        self.assertEqual(
            report["relevant_news"]["message"],
            "No relevant recent news is available.",
        )
        self.assertIn(
            "Historical performance is limited because only one snapshot is available.",
            report["data_limitations"],
        )
        self.assertIn(
            "Not enough historical snapshots.",
            report["data_limitations"],
        )

    @patch(
        "investment_assistant.intelligence.portfolio.calculate_portfolio_valuation",
        side_effect=RuntimeError("market feed offline"),
    )
    @patch("investment_assistant.intelligence.portfolio.get_portfolio_analytics_summary")
    @patch("investment_assistant.intelligence.portfolio.get_portfolio_performance_history", return_value=[])
    @patch("investment_assistant.intelligence.portfolio.get_historical_performance_summary", return_value={})
    @patch(
        "investment_assistant.intelligence.alerts.get_portfolio_change_report",
        return_value={"available": False, "message": "No snapshots.", "alerts": []},
    )
    def test_market_data_unavailable_is_reported_without_fabrication(
        self,
        _changes,
        _summary,
        _history,
        analytics,
        valuation,
    ):
        analytics.return_value = {
            "allocation": {},
            "concentration": {},
            "max_drawdown": {},
        }
        report = generate_portfolio_intelligence()

        self.assertIsNone(
            report["portfolio_overview"]["current_portfolio_value"]
        )
        self.assertTrue(any(
            "market feed offline" in item
            for item in report["data_limitations"]
        ))
        valuation.assert_called_once()

    @patch(
        "investment_assistant.intelligence.news.get_company_news",
        side_effect=RuntimeError("news feed offline"),
    )
    def test_news_fetch_failure_becomes_limitation(self, get_news):
        report = generate_portfolio_intelligence(
            portfolio_data=PORTFOLIO_DATA,
            analytics=ANALYTICS,
            performance_history=[],
            historical_summary={},
            portfolio_changes={"available": False, "alerts": []},
        )
        self.assertFalse(report["relevant_news"]["available"])
        self.assertTrue(any(
            "news feed offline" in item
            for item in report["data_limitations"]
        ))
        self.assertEqual(get_news.call_count, 2)

    @patch("investment_assistant.briefing.generate_goals_intelligence", return_value={"goals": [], "benchmarks": []})
    @patch("investment_assistant.briefing.calculate_portfolio_valuation", side_effect=RuntimeError("market feed offline"))
    @patch("investment_assistant.briefing.get_transactions", return_value=[])
    @patch("investment_assistant.briefing.get_opening_positions", return_value=[])
    @patch("investment_assistant.briefing.calculate_positions", return_value={})
    @patch("investment_assistant.briefing.get_portfolio_snapshots", return_value=[])
    @patch(
        "investment_assistant.briefing.calculate_portfolio_changes",
        return_value={
            "available": False,
            "message": "Not enough historical snapshots.",
            "alerts": [],
        },
    )
    @patch(
        "investment_assistant.briefing.generate_portfolio_intelligence",
        return_value={"portfolio_overview": {}},
    )
    @patch("investment_assistant.briefing.calculate_max_drawdown", return_value={})
    @patch("investment_assistant.briefing.save_portfolio_snapshot")
    @patch("investment_assistant.briefing.generate_portfolio_analysis")
    def test_briefing_market_data_failure_does_not_write_snapshot_or_call_gemini(
        self,
        generate_analysis,
        save_snapshot,
        _drawdown,
        intelligence,
        _changes,
        _snapshots,
        _positions,
        _opening_positions,
        _transactions,
        _valuation,
        _goals_report,
    ):
        from investment_assistant import briefing

        portfolio_data, _, analysis = briefing.build_briefing(
            news_overrides={},
        )

        self.assertIsNone(portfolio_data["total_current_value"])
        self.assertIn("market data could not be retrieved", analysis)
        self.assertFalse(generate_analysis.called)
        self.assertFalse(save_snapshot.called)
        self.assertEqual(
            intelligence.call_args.kwargs["market_data_error"],
            "market feed offline",
        )

    @patch("dashboard.app.generate_goals_intelligence", return_value={"goals": [], "benchmarks": []})
    @patch("dashboard.app.generate_historical_analytics", return_value={})
    @patch("dashboard.app.generate_performance_attribution", return_value={})
    @patch("dashboard.app.get_dashboard_data", side_effect=RuntimeError("market feed offline"))
    @patch("dashboard.app.get_transactions", return_value=[])
    @patch("dashboard.app.get_opening_positions", return_value=[])
    @patch("dashboard.app.calculate_positions", return_value={})
    @patch("dashboard.app.get_portfolio_performance_history", return_value=[])
    @patch("dashboard.app.get_historical_performance_summary", return_value={})
    @patch("dashboard.app.get_portfolio_snapshots", return_value=[])
    @patch("dashboard.app.calculate_max_drawdown", return_value={})
    @patch("dashboard.app.get_portfolio_alerts", side_effect=RuntimeError("market feed offline"))
    @patch(
        "dashboard.app.get_portfolio_change_report",
        return_value={"available": False, "message": "No snapshot history.", "alerts": []},
    )
    @patch("dashboard.app.sqlite3.connect")
    @patch("dashboard.app.generate_portfolio_analysis")
    @patch("dashboard.app.render_template", return_value="dashboard")
    def test_dashboard_market_data_failure_renders_unavailable_state(
        self,
        render,
        generate_analysis,
        connect,
        _changes,
        _alerts,
        _drawdown,
        _snapshots,
        _summary,
        _history,
        _positions,
        _openings,
        _transactions,
        _dashboard_data,
        _attribution,
        _historical,
        _goals_report,
    ):
        from dashboard import app as dashboard_module

        connect.return_value.execute.return_value.fetchall.return_value = []
        connect.return_value.close.return_value = None
        response = dashboard_module._render_dashboard()

        self.assertEqual(response, "dashboard")
        self.assertFalse(generate_analysis.called)
        self.assertTrue(any(
            "Current price data is unavailable." in item
            for item in render.call_args.kwargs[
                "portfolio_intelligence"
            ]["data_limitations"]
        ))
        self.assertIn(
            "Portfolio alerts are unavailable",
            render.call_args.kwargs["alerts"][0]["message"],
        )


if __name__ == "__main__":
    unittest.main()
