import unittest
from unittest.mock import Mock, patch

from investment_assistant.historical_analytics import (
    EXACT_DATE_UNAVAILABLE_MESSAGE,
    INSUFFICIENT_DRAWDOWN_MESSAGE,
    INSUFFICIENT_TREND_MESSAGE,
    generate_historical_analytics,
)


def history_item(
    snapshot_date,
    value,
    total_pnl,
    return_percent,
    *,
    invested=None,
    realized=None,
    unrealized=None,
):
    return {
        "date": snapshot_date,
        "total_invested": invested,
        "total_current_value": value,
        "total_realized_pnl": realized,
        "total_unrealized_pnl": unrealized,
        "total_pnl": total_pnl,
        "total_return_percent": return_percent,
    }


def raw_snapshot(item, details=None):
    return {
        **item,
        "holding_snapshot_json": details,
    }


def generate(history, *, snapshots=None, drawdown=None, summary=None):
    if snapshots is None:
        snapshots = [raw_snapshot(item) for item in history]
    if summary is None:
        values = [item["total_current_value"] for item in history]
        maximum = max(values) if values else None
        minimum = min(values) if values else None
        summary = {
            "highest_value": maximum,
            "highest_value_date": next(
                (item["date"] for item in history if item["total_current_value"] == maximum),
                None,
            ),
            "lowest_value": minimum,
            "lowest_value_date": next(
                (item["date"] for item in history if item["total_current_value"] == minimum),
                None,
            ),
        }
    if drawdown is None:
        drawdown = {
            "max_drawdown_amount": 0,
            "max_drawdown_percent": 0,
            "peak_date": None,
            "trough_date": None,
        }
    return generate_historical_analytics(
        history=history,
        snapshots=snapshots,
        historical_summary=summary,
        max_drawdown=drawdown,
    )


class HistoricalAnalyticsTests(unittest.TestCase):
    def test_empty_history_is_explicit_and_does_not_create_points(self):
        report = generate([])
        self.assertEqual(report["history"], [])
        self.assertEqual(report["trend_metrics"]["snapshot_count"], 0)
        self.assertFalse(report["trend_metrics"]["available"])
        self.assertEqual(report["trend_metrics"]["trend"], "Insufficient history")
        self.assertFalse(report["drawdown"]["available"])
        self.assertEqual(report["drawdown"]["message"], INSUFFICIENT_DRAWDOWN_MESSAGE)
        self.assertEqual(report["data_quality"]["snapshot_count"], 0)

    def test_one_snapshot_is_not_enough_for_trend_or_drawdown(self):
        history = [history_item("2026-01-01", 1000, 100, 10)]
        report = generate(history)

        self.assertEqual(len(report["history"]), 1)
        self.assertFalse(report["trend_metrics"]["available"])
        self.assertEqual(report["trend_metrics"]["trend"], "Insufficient history")
        self.assertFalse(report["drawdown"]["available"])
        self.assertIn(INSUFFICIENT_TREND_MESSAGE, report["data_quality"]["limitations"])

    def test_two_snapshots_return_first_latest_and_change(self):
        history = [
            history_item("2026-01-01", 1000, 10, 1),
            history_item("2026-01-02", 1100, 20, 2),
        ]
        report = generate(history)
        metrics = report["trend_metrics"]

        self.assertTrue(metrics["available"])
        self.assertEqual(metrics["first_recorded_value"], 1000)
        self.assertEqual(metrics["latest_portfolio_value"], 1100)
        self.assertEqual(metrics["first_to_latest_change"], 100)
        self.assertEqual(metrics["first_to_latest_change_percent"], 10)
        self.assertEqual(metrics["first_snapshot_date"], "2026-01-01")
        self.assertEqual(metrics["latest_snapshot_date"], "2026-01-02")

    def test_multiple_snapshots_sort_chronologically_and_keep_actual_dates(self):
        history = [
            history_item("2026-01-03", 120, 3, 3),
            history_item("2026-01-01", 100, 1, 1),
            history_item("2026-01-02", 110, 2, 2),
        ]
        report = generate(history)

        self.assertEqual(
            [item["date"] for item in report["history"]],
            ["2026-01-01", "2026-01-02", "2026-01-03"],
        )
        self.assertEqual(len(report["history"]), 3)

    def test_first_latest_value_and_extrema(self):
        history = [
            history_item("2026-01-01", 100, 1, 1),
            history_item("2026-01-02", 200, 2, 2),
            history_item("2026-01-03", 150, 3, 3),
        ]
        report = generate(history)
        metrics = report["trend_metrics"]

        self.assertEqual(metrics["first_recorded_value"], 100)
        self.assertEqual(metrics["latest_portfolio_value"], 150)
        self.assertEqual(metrics["highest_recorded_value"], 200)
        self.assertEqual(metrics["lowest_recorded_value"], 100)

    def test_highest_and_lowest_pnl_and_return(self):
        history = [
            history_item("2026-01-01", 100, -20, -5),
            history_item("2026-01-02", 120, 50, 10),
            history_item("2026-01-03", 110, 10, 2),
        ]
        metrics = generate(history)["trend_metrics"]

        self.assertEqual(metrics["highest_total_pnl"], 50)
        self.assertEqual(metrics["lowest_total_pnl"], -20)
        self.assertEqual(metrics["highest_unrealized_return_percent"], 10)
        self.assertEqual(metrics["lowest_unrealized_return_percent"], -5)

    def test_increasing_decreasing_mixed_and_insufficient_trends(self):
        cases = [
            ([100, 110, 120], "Increasing over available history"),
            ([120, 110, 100], "Decreasing over available history"),
            ([100, 120, 110], "Mixed / fluctuating"),
            ([100], "Insufficient history"),
        ]
        for values, expected in cases:
            with self.subTest(values=values):
                history = [
                    history_item(
                        f"2026-01-0{index + 1}",
                        value,
                        value - 100,
                        index,
                    )
                    for index, value in enumerate(values)
                ]
                self.assertEqual(
                    generate(history)["trend_metrics"]["trend"],
                    expected,
                )

    def test_maximum_drawdown_reuses_supplied_calculation_and_dates(self):
        history = [
            history_item("2026-01-01", 1000, 0, 0),
            history_item("2026-01-02", 1200, 0, 0),
            history_item("2026-01-03", 900, 0, 0),
        ]
        report = generate(
            history,
            drawdown={
                "max_drawdown_amount": 300,
                "max_drawdown_percent": 25,
                "peak_date": "2026-01-02",
                "trough_date": "2026-01-03",
            },
        )

        self.assertEqual(report["drawdown"]["peak_value"], 1200)
        self.assertEqual(report["drawdown"]["trough_value"], 900)
        self.assertEqual(report["drawdown"]["max_drawdown_amount"], 300)
        self.assertEqual(report["drawdown"]["max_drawdown_percent"], 25)

    def test_latest_previous_and_first_period_comparisons(self):
        history = [
            history_item("2026-01-01", 1000, 0, 0),
            history_item("2026-01-03", 1200, 0, 0),
        ]
        report = generate(history)

        latest_previous = report["period_comparisons"]["latest_vs_previous"]
        self.assertTrue(latest_previous["available"])
        self.assertEqual(latest_previous["value_change"], 200)
        self.assertTrue(report["period_comparisons"]["latest_vs_first"]["available"])

    def test_exact_7_day_comparison_uses_only_exact_date(self):
        history = [
            history_item("2026-09-24", 1000, 0, 0),
            history_item("2026-10-01", 1100, 0, 0),
        ]
        comparison = generate(history)["period_comparisons"]["latest_vs_7_days"]

        self.assertTrue(comparison["available"])
        self.assertEqual(comparison["comparison_date"], "2026-09-24")
        self.assertEqual(comparison["value_change"], 100)
        self.assertEqual(comparison["value_change_percent"], 10)

    def test_missing_exact_7_day_snapshot_does_not_substitute_nearby_date(self):
        history = [
            history_item("2026-09-23", 1000, 0, 0),
            history_item("2026-10-01", 1100, 0, 0),
        ]
        comparison = generate(history)["period_comparisons"]["latest_vs_7_days"]

        self.assertFalse(comparison["available"])
        self.assertEqual(comparison["comparison_date"], "2026-09-24")
        self.assertEqual(comparison["message"], EXACT_DATE_UNAVAILABLE_MESSAGE)

    def test_exact_30_day_comparison_uses_exact_snapshot(self):
        history = [
            history_item("2026-09-01", 1000, 0, 0),
            history_item("2026-10-01", 900, 0, 0),
        ]
        comparison = generate(history)["period_comparisons"]["latest_vs_30_days"]

        self.assertTrue(comparison["available"])
        self.assertEqual(comparison["value_change"], -100)
        self.assertEqual(comparison["value_change_percent"], -10)

    def test_missing_exact_30_day_snapshot_is_explicit(self):
        history = [
            history_item("2026-09-02", 1000, 0, 0),
            history_item("2026-10-01", 900, 0, 0),
        ]
        comparison = generate(history)["period_comparisons"]["latest_vs_30_days"]
        self.assertFalse(comparison["available"])
        self.assertEqual(comparison["comparison_date"], "2026-09-01")
        self.assertEqual(comparison["message"], EXACT_DATE_UNAVAILABLE_MESSAGE)

    def test_pnl_trend_reports_progression_and_latest_deltas(self):
        history = [
            history_item("2026-01-01", 100, 10, 5, realized=2, unrealized=8),
            history_item("2026-01-02", 120, 20, 10, realized=3, unrealized=17),
        ]
        pnl = generate(history)["pnl_trend"]

        self.assertEqual(pnl["total_pnl"], [10, 20])
        self.assertEqual(pnl["unrealized_pnl"], [8, 17])
        self.assertEqual(pnl["realized_pnl"], [2, 3])
        self.assertEqual(pnl["latest_total_pnl_change"], 10)
        self.assertEqual(pnl["latest_unrealized_pnl_change"], 9)
        self.assertEqual(pnl["latest_realized_pnl_change"], 1)

    def test_data_quality_reports_detail_and_aggregate_only_counts(self):
        history = [
            history_item("2026-01-01", 100, 1, 1),
            history_item("2026-01-02", 110, 2, 2),
        ]
        snapshots = [
            raw_snapshot(history[0], None),
            raw_snapshot(history[1], '{"AAA": {"symbol": "AAA"}}'),
        ]
        quality = generate(history, snapshots=snapshots)["data_quality"]

        self.assertEqual(quality["snapshot_count"], 2)
        self.assertEqual(quality["detailed_snapshot_count"], 1)
        self.assertEqual(quality["aggregate_only_snapshot_count"], 1)
        self.assertTrue(quality["detailed_holding_history_available"])
        self.assertTrue(any("aggregate data only" in item for item in quality["limitations"]))

    def test_empty_holding_snapshot_is_still_detailed_snapshot_data(self):
        history = [
            history_item("2026-01-01", 100, 1, 1),
            history_item("2026-01-02", 110, 2, 2),
        ]
        snapshots = [raw_snapshot(item, "{}") for item in history]
        quality = generate(history, snapshots=snapshots)["data_quality"]

        self.assertEqual(quality["detailed_snapshot_count"], 2)
        self.assertEqual(quality["aggregate_only_snapshot_count"], 0)
        self.assertTrue(quality["detailed_holding_history_available"])

    def test_date_range_and_sufficiency_flags_use_actual_history(self):
        history = [
            history_item("2026-01-01", 100, 1, 1),
            history_item("2026-01-08", 110, 2, 2),
        ]
        quality = generate(history)["data_quality"]

        self.assertEqual(quality["date_range_start"], "2026-01-01")
        self.assertEqual(quality["date_range_end"], "2026-01-08")
        self.assertTrue(quality["trend_analysis_sufficient"])
        self.assertTrue(quality["drawdown_analysis_sufficient"])

    def test_period_comparison_changes_do_not_depend_on_nearest_date(self):
        history = [
            history_item("2026-09-23", 900, 0, 0),
            history_item("2026-09-25", 950, 0, 0),
            history_item("2026-10-01", 1000, 0, 0),
        ]
        comparisons = generate(history)["period_comparisons"]

        self.assertEqual(
            comparisons["latest_vs_7_days"]["message"],
            EXACT_DATE_UNAVAILABLE_MESSAGE,
        )
        self.assertEqual(
            comparisons["latest_vs_30_days"]["message"],
            EXACT_DATE_UNAVAILABLE_MESSAGE,
        )

    def test_no_future_prediction_language_in_report(self):
        history = [
            history_item("2026-01-01", 100, 1, 1),
            history_item("2026-01-02", 110, 2, 2),
        ]
        report_text = repr(generate(history)).casefold()

        for term in ("bullish", "bearish", "will rise", "will fall", "forecast"):
            self.assertNotIn(term, report_text)

    def test_no_fabricated_snapshots_or_interpolated_dates(self):
        history = [
            history_item("2026-01-01", 100, 1, 1),
            history_item("2026-01-10", 110, 2, 2),
        ]
        report = generate(history)

        self.assertEqual(
            [item["date"] for item in report["history"]],
            ["2026-01-01", "2026-01-10"],
        )
        self.assertEqual(report["data_quality"]["snapshot_count"], 2)

    def test_dashboard_passes_structured_history_report_and_template_uses_it(self):
        from dashboard import app as dashboard_module

        history = [
            history_item("2026-01-01", 1000, 0, 0),
            history_item("2026-01-02", 1100, 10, 1),
        ]
        dashboard_data = {
            "portfolio": {"positions": {}},
            "analytics": {
                "allocation": {},
                "concentration": {"holding_count": 0},
                "max_drawdown": {},
            },
            "historical": {
                **{
                    "highest_value": 1100,
                    "highest_value_date": "2026-01-02",
                    "lowest_value": 1000,
                    "lowest_value_date": "2026-01-01",
                },
                "history": history,
            },
        }
        connection = Mock()
        connection.execute.return_value.fetchall.return_value = []
        report = generate_historical_analytics(
            history=history,
            snapshots=[raw_snapshot(item) for item in history],
            historical_summary=dashboard_data["historical"],
            max_drawdown={"max_drawdown_amount": 0, "max_drawdown_percent": 0},
        )
        with (
            patch.object(dashboard_module, "get_dashboard_data", return_value=dashboard_data),
            patch.object(dashboard_module, "get_portfolio_snapshots", return_value=[]),
            patch.object(dashboard_module, "get_portfolio_alerts", return_value=[]),
            patch.object(dashboard_module, "get_portfolio_change_report", return_value={"available": False, "alerts": []}),
            patch.object(dashboard_module, "get_company_news", return_value=[]),
            patch.object(dashboard_module.sqlite3, "connect", return_value=connection),
            patch.object(dashboard_module, "generate_portfolio_intelligence", return_value={}),
            patch.object(dashboard_module, "generate_risk_intelligence", return_value={}),
            patch.object(dashboard_module, "generate_performance_attribution", return_value={}),
            patch.object(dashboard_module, "generate_historical_analytics", return_value=report),
            patch.object(dashboard_module, "generate_goals_intelligence", return_value={"goals": [], "benchmarks": []}),
            patch.object(dashboard_module, "generate_portfolio_analysis", return_value=""),
            patch.object(dashboard_module, "render_template", return_value="dashboard") as render,
        ):
            dashboard_module._render_dashboard()

        self.assertEqual(render.call_args.kwargs["historical_analytics"], report)
        source, _, _ = dashboard_module.app.jinja_env.loader.get_source(
            dashboard_module.app.jinja_env,
            "dashboard.html",
        )
        self.assertIn("<h2>Historical Performance</h2>", source)
        self.assertIn("history | length >= 2", source)
        self.assertIn("Insufficient historical data to display a portfolio-value trend chart.", source)
        self.assertIn("snapshot.total_unrealized_pnl", source)

    def test_assistant_supplies_historical_analytics_to_gemini(self):
        from investment_assistant import assistant

        expected = {"trend_metrics": {"trend": "Increasing over available history"}}
        portfolio_data = {
            "positions": {},
            "total_invested": 0,
            "total_current_value": 0,
            "total_realized_pnl": 0,
            "total_unrealized_pnl": 0,
            "total_pnl": 0,
            "total_return_percent": None,
        }
        history = [
            history_item("2026-01-01", 1000, 0, 0),
            history_item("2026-01-02", 1100, 10, 1),
        ]
        with (
            patch.object(assistant.portfolio, "get_transactions", return_value=[]),
            patch.object(assistant.portfolio, "get_opening_positions", return_value=[]),
            patch.object(assistant.portfolio, "calculate_portfolio_valuation", return_value=portfolio_data),
            patch.object(assistant.portfolio, "get_portfolio_analytics_summary", return_value={"allocation": {}, "concentration": {}}),
            patch.object(assistant.portfolio, "get_portfolio_performance_history", return_value=history),
            patch.object(assistant.portfolio, "get_portfolio_snapshots", return_value=[]),
            patch.object(assistant.portfolio, "get_historical_performance_summary", return_value={}),
            patch.object(assistant.portfolio, "calculate_max_drawdown", return_value={}),
            patch.object(assistant.alerts, "get_portfolio_change_report", return_value={"available": False}),
            patch.object(assistant.performance_attribution, "generate_performance_attribution", return_value={}),
            patch.object(assistant.risk_intelligence, "generate_risk_intelligence", return_value={}),
            patch.object(assistant.historical_analytics, "generate_historical_analytics", return_value=expected),
            patch.object(assistant.goals_intelligence, "generate_goals_intelligence", return_value={"goals": [], "benchmarks": []}),
            patch.object(assistant.intelligence, "generate_portfolio_intelligence", return_value={}),
            patch.object(assistant.ai_analysis, "generate_portfolio_answer", return_value="ok") as answer,
        ):
            assistant.answer_portfolio_question("What is my portfolio trend?")

        self.assertEqual(answer.call_args.args[1]["historical_analytics"], expected)

    def test_gemini_prompt_has_historical_data_constraints(self):
        from investment_assistant import ai_analysis

        report = {"trend_metrics": {"trend": "Increasing over available history"}}
        with (
            patch.object(ai_analysis, "GEMINI_API_KEY", "test-key"),
            patch.object(ai_analysis, "_request_gemini", return_value="answer") as request,
        ):
            ai_analysis.generate_portfolio_answer(
                "How has my portfolio performed?",
                {"historical_analytics": report},
            )

        normalized = " ".join(request.call_args.args[0].split())
        self.assertIn('"trend": "Increasing over available history"', normalized)
        self.assertIn("never interpolate, substitute a nearby date", normalized)
        self.assertIn("Never invent missing snapshots", normalized)
        self.assertIn("do not predict future performance", normalized)

    def test_briefing_includes_historical_analytics(self):
        from investment_assistant import briefing

        history = [
            history_item("2026-01-01", 1000, 0, 0),
            history_item("2026-01-02", 1100, 100, 10),
        ]
        snapshots = [raw_snapshot(item) for item in history]
        expected = generate(
            history,
            snapshots=snapshots,
            drawdown={"max_drawdown_amount": 0, "max_drawdown_percent": 0},
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
            patch.object(briefing, "get_portfolio_snapshots", return_value=snapshots),
            patch.object(briefing, "get_portfolio_performance_history", return_value=history),
            patch.object(briefing, "get_historical_performance_summary", return_value={"highest_value": 1100, "lowest_value": 1000}),
            patch.object(briefing, "calculate_max_drawdown", return_value={"max_drawdown_amount": 0, "max_drawdown_percent": 0}),
            patch.object(briefing, "get_transactions", return_value=[]),
            patch.object(briefing, "get_company_news", return_value=[]),
            patch.object(briefing, "calculate_portfolio_changes", return_value={"available": False, "alerts": []}),
            patch.object(briefing, "generate_performance_attribution", return_value={}),
            patch.object(briefing, "generate_portfolio_intelligence", return_value={}),
            patch.object(briefing, "get_portfolio_analytics_summary", return_value={"allocation": {}, "concentration": {}, "max_drawdown": {}}),
            patch.object(briefing, "generate_risk_intelligence", return_value={}),
            patch.object(briefing, "generate_historical_analytics", return_value=expected) as historical_report,
            patch.object(briefing, "generate_goals_intelligence", return_value={"goals": [], "benchmarks": []}),
            patch.object(briefing, "generate_portfolio_analysis", return_value="Summary") as analysis,
        ):
            result, _, _ = briefing.build_briefing(news_overrides={})

        self.assertEqual(result["historical_analytics"], expected)
        self.assertEqual(
            analysis.call_args.kwargs["intelligence_report"]["historical_analytics"],
            expected,
        )
        historical_report.assert_called_once()
        email = briefing.build_html_email(result, "Summary")
        self.assertIn("<h2>Historical Performance</h2>", email)
        self.assertIn("Increasing over available history", email)
        self.assertIn("Maximum drawdown", email)


if __name__ == "__main__":
    unittest.main()
