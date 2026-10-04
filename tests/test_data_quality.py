import json
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock, patch

from investment_assistant import data_quality


NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


def position(
    symbol="AAA",
    *,
    quantity=2,
    price=100,
    value=200,
    cost=150,
    company="Alpha Ltd",
    market_age_hours=2,
    source="Yahoo Finance chart endpoint",
    retrieved=True,
    market_timestamp=True,
    currency="INR",
    exchange="NSE",
):
    timestamp = (
        (NOW - timedelta(hours=market_age_hours)).isoformat()
        if market_timestamp
        else None
    )
    return {
        "symbol": symbol,
        "company_name": company,
        "quantity": quantity,
        "current_price": price,
        "current_value": value,
        "remaining_cost_basis": cost,
        "unrealized_pnl": value - cost if value is not None and cost is not None else None,
        "total_pnl": value - cost if value is not None and cost is not None else None,
        "source": source,
        "retrieved_at": (NOW - timedelta(minutes=5)).isoformat() if retrieved else None,
        "market_timestamp": timestamp,
        "currency": currency,
        "exchange": exchange,
    }


def portfolio(positions=None, *, current_value=200, invested=150, pnl=50):
    return {
        "positions": positions if positions is not None else {"AAA": position()},
        "total_current_value": current_value,
        "total_invested": invested,
        "total_realized_pnl": 0,
        "total_unrealized_pnl": pnl,
        "total_pnl": pnl,
        "total_return_percent": pnl / invested * 100 if invested else None,
    }


def snapshot(day, value=200, details=None):
    return {
        "date": day,
        "total_current_value": value,
        "total_pnl": value - 150,
        "holding_snapshot_json": (
            json.dumps(details) if details is not None else None
        ),
    }


def history_report(count=2, detail_count=2):
    history = [
        {
            "date": f"2026-09-{29 + index:02d}",
            "total_current_value": 100 + index,
        }
        for index in range(count)
    ]
    detailed = {
        "trend_metrics": {"available": count >= 2},
        "drawdown": {"available": count >= 2},
        "data_quality": {
            "limitations": [],
            "trend_analysis_sufficient": count >= 2,
            "drawdown_analysis_sufficient": count >= 2,
        },
    }
    snapshots = [
        snapshot(
            item["date"],
            details={"AAA": {"market_value": item["total_current_value"]}}
            if index < detail_count
            else None,
        )
        for index, item in enumerate(history)
    ]
    return history, snapshots, detailed


class DataQualityTestSupport(unittest.TestCase):
    def setUp(self):
        self.db_patches = [
            patch.object(data_quality.portfolio, "get_opening_positions", return_value=[]),
            patch.object(data_quality.portfolio, "get_transactions", return_value=[]),
            patch.object(data_quality.portfolio, "get_portfolio_performance_history", return_value=[]),
            patch.object(data_quality, "get_portfolio_goals", return_value=[]),
            patch.object(data_quality, "get_portfolio_benchmarks", return_value=[]),
            patch(
                "investment_assistant.goals_intelligence.generate_goals_intelligence",
                return_value={"goals": [], "benchmarks": []},
            ),
        ]
        for item in self.db_patches:
            item.start()
            self.addCleanup(item.stop)

    def generate(self, **kwargs):
        kwargs.setdefault("now", NOW)
        kwargs.setdefault("goals", [])
        kwargs.setdefault("benchmarks", [])
        kwargs.setdefault("observations_by_benchmark", {})
        kwargs.setdefault("snapshots", [])
        kwargs.setdefault("news_by_symbol", {})
        return data_quality.generate_data_quality_report(**kwargs)


class DataQualityPortfolioTests(DataQualityTestSupport):
    def test_fully_available_portfolio_data_and_provider_limitation(self):
        history, snapshots, historical = history_report()
        report = self.generate(
            portfolio_data=portfolio(),
            snapshots=snapshots,
            historical_report=historical,
            attribution_report={
                "available": True,
                "holding_attribution": {"available": True},
            },
            risk_report={"data_quality": {"limitations": []}},
            news_by_symbol={"AAA": [{"title": "Synthetic news"}]},
        )
        self.assertEqual(report["overall_status"], "READY")
        self.assertEqual(report["portfolio"]["holding_count"], 1)
        self.assertTrue(report["portfolio"]["pnl_available"])
        self.assertIn("best-effort", report["market_data"]["source_limitation"])
        self.assertFalse(report["automatic_repairs_performed"])

    def test_missing_current_price_is_critical_and_blocks_valuation(self):
        holding = position(price=None, value=None)
        report = self.generate(
            portfolio_data=portfolio({"AAA": holding}),
        )
        issue = next(
            item for item in report["issues"]
            if item["code"] == "MISSING_MARKET_PRICE"
        )
        self.assertEqual(issue["severity"], "CRITICAL")
        self.assertTrue(issue["blocks_calculation"])
        self.assertEqual(report["overall_status"], "INSUFFICIENT DATA")
        self.assertEqual(report["market_data"]["missing_price_count"], 1)

    def test_missing_cost_basis_blocks_pnl_without_repair(self):
        report = self.generate(
            portfolio_data=portfolio({
                "AAA": position(cost=None),
            }),
        )
        issue = next(
            item for item in report["issues"]
            if item["code"] == "MISSING_COST_BASIS"
        )
        self.assertTrue(issue["blocks_calculation"])
        self.assertFalse(report["portfolio"]["pnl_available"])
        self.assertEqual(report["overall_status"], "INSUFFICIENT DATA")

    def test_invalid_quantity_is_critical(self):
        report = self.generate(
            portfolio_data=portfolio({"AAA": position(quantity=-2)}),
        )
        issue = next(
            item for item in report["issues"]
            if item["code"] == "INVALID_QUANTITY"
        )
        self.assertEqual(issue["severity"], "CRITICAL")
        self.assertTrue(issue["blocks_calculation"])

    def test_missing_company_name_warns_without_blocking_math(self):
        report = self.generate(
            portfolio_data=portfolio({"AAA": position(company=None)}),
        )
        issue = next(
            item for item in report["issues"]
            if item["code"] == "MISSING_COMPANY_NAME"
        )
        self.assertEqual(issue["severity"], "WARNING")
        self.assertFalse(issue["blocks_calculation"])
        self.assertTrue(report["portfolio"]["pnl_available"])

    def test_existing_database_company_name_is_used_for_quality_check(self):
        with patch.object(
            data_quality.portfolio,
            "get_transactions",
            return_value=[(1, "AAA", "Alpha Ltd", "BUY", 2, 75, "2026-01-01")],
        ):
            report = self.generate(portfolio_data=portfolio({
                "AAA": position(company=None),
            }))
        self.assertTrue(report["portfolio"]["company_names_available"])
        # The company name is resolved from existing transaction records.
        self.assertFalse(any(
            issue["code"] == "MISSING_COMPANY_NAME"
            for issue in report["issues"]
        ))

    def test_inconsistent_position_value_is_critical(self):
        report = self.generate(
            portfolio_data=portfolio({
                "AAA": position(value=205),
            }),
        )
        issue = next(
            item for item in report["issues"]
            if item["code"] == "POSITION_VALUE_INCONSISTENT"
        )
        self.assertTrue(issue["blocks_calculation"])

    def test_zero_quantity_closed_position_does_not_require_current_price(self):
        report = self.generate(
            portfolio_data=portfolio(
                {"AAA": position(quantity=0, price=None, value=0)},
                current_value=0,
                invested=0,
                pnl=0,
            ),
        )
        self.assertEqual(report["market_data"]["holdings"], [])
        self.assertEqual(report["market_data"]["missing_price_count"], 0)
        self.assertFalse(any(
            issue["code"] == "MISSING_MARKET_PRICE"
            for issue in report["issues"]
        ))

    def test_no_valuation_is_insufficient_data(self):
        report = self.generate(
            portfolio_data=portfolio(current_value=None),
        )
        self.assertEqual(report["overall_status"], "INSUFFICIENT DATA")
        self.assertTrue(any(
            item["code"] == "PORTFOLIO_VALUATION_UNAVAILABLE"
            for item in report["issues"]
        ))


class DataQualityMarketTests(DataQualityTestSupport):
    def test_market_metadata_is_returned_when_available(self):
        report = self.generate(portfolio_data=portfolio())
        holding = report["market_data"]["holdings"][0]
        self.assertEqual(holding["source"], "Yahoo Finance chart endpoint")
        self.assertEqual(holding["currency"], "INR")
        self.assertEqual(holding["exchange"], "NSE")
        self.assertIsNotNone(holding["retrieved_at"])
        self.assertIsNotNone(holding["market_timestamp"])

    def test_missing_timestamp_has_unknown_freshness(self):
        report = self.generate(
            portfolio_data=portfolio({
                "AAA": position(market_timestamp=False),
            }),
        )
        self.assertEqual(
            report["market_data"]["holdings"][0]["freshness"]["category"],
            "UNKNOWN",
        )

    def test_fresh_market_data(self):
        report = self.generate(
            portfolio_data=portfolio({
                "AAA": position(market_age_hours=1),
            }),
        )
        self.assertEqual(
            report["market_data"]["holdings"][0]["freshness"]["category"],
            "FRESH",
        )

    def test_aging_market_data(self):
        report = self.generate(
            portfolio_data=portfolio({
                "AAA": position(market_age_hours=48),
            }),
        )
        self.assertEqual(
            report["market_data"]["holdings"][0]["freshness"]["category"],
            "AGING",
        )

    def test_stale_market_data_warns_but_does_not_block(self):
        report = self.generate(
            portfolio_data=portfolio({
                "AAA": position(market_age_hours=100),
            }),
        )
        self.assertEqual(
            report["market_data"]["holdings"][0]["freshness"]["category"],
            "STALE",
        )
        stale_issue = next(
            item for item in report["issues"]
            if item["code"] == "PRICE_TIMESTAMP_STALE"
        )
        self.assertFalse(stale_issue["blocks_calculation"])
        self.assertIn("timestamp age only", stale_issue["message"])

    def test_future_market_timestamp_has_unknown_freshness(self):
        future = (NOW + timedelta(hours=2)).isoformat()
        with patch.object(
            data_quality,
            "_parse_timestamp",
            side_effect=lambda value: (
                datetime.fromisoformat(future)
                if value == future
                else datetime.fromisoformat(value.replace("Z", "+00:00"))
            ),
        ):
            report = self.generate(
                portfolio_data=portfolio({
                    "AAA": {
                        **position(),
                        "market_timestamp": future,
                    },
                }),
            )
        self.assertEqual(
            report["market_data"]["holdings"][0]["freshness"]["category"],
            "UNKNOWN",
        )

    def test_freshness_thresholds_are_explicit(self):
        self.assertEqual(
            data_quality.MARKET_DATA_AGING_AFTER_HOURS,
            24,
        )
        self.assertEqual(data_quality.MARKET_DATA_STALE_AFTER_HOURS, 72)

    def test_retrieval_timestamp_does_not_substitute_for_market_timestamp(self):
        report = self.generate(
            portfolio_data=portfolio({
                "AAA": position(market_timestamp=False, retrieved=True),
            }),
        )
        freshness = report["market_data"]["holdings"][0]["freshness"]
        self.assertEqual(freshness["category"], "UNKNOWN")
        self.assertIsNotNone(freshness["retrieval_age_hours"])


class DataQualityHistoryTests(DataQualityTestSupport):
    def test_no_snapshot_is_explicit(self):
        report = self.generate(portfolio_data=portfolio())
        history = report["snapshot_history"]
        self.assertEqual(history["snapshot_count"], 0)
        self.assertEqual(history["trend_analysis"]["status"], "UNAVAILABLE")
        self.assertIn("No snapshot recorded.", history["details"])

    def test_one_snapshot_limits_trend_and_drawdown(self):
        _, snapshots, historical = history_report(count=1, detail_count=0)
        historical["trend_metrics"]["available"] = False
        historical["drawdown"]["available"] = False
        report = self.generate(
            portfolio_data=portfolio(),
            snapshots=snapshots,
            historical_report=historical,
        )
        self.assertEqual(report["snapshot_history"]["snapshot_count"], 1)
        self.assertEqual(report["snapshot_history"]["trend_analysis"]["status"], "LIMITED")
        self.assertEqual(report["snapshot_history"]["drawdown_analysis"]["status"], "LIMITED")
        self.assertIn(
            "Trend analysis is limited because only one snapshot exists.",
            report["snapshot_history"]["details"],
        )

    def test_multiple_snapshots_report_date_range_and_missing_date_intervals(self):
        snapshots = [
            snapshot("2026-09-25", details=None),
            snapshot("2026-09-28", details=None),
        ]
        report = self.generate(
            portfolio_data=portfolio(),
            snapshots=snapshots,
            historical_report={
                "trend_metrics": {"available": True},
                "drawdown": {"available": True},
                "data_quality": {"limitations": []},
            },
        )
        history = report["snapshot_history"]
        self.assertEqual(history["snapshot_count"], 2)
        self.assertEqual(history["earliest_snapshot_date"], "2026-09-25")
        self.assertEqual(history["latest_snapshot_date"], "2026-09-28")
        self.assertEqual(
            history["missing_date_intervals"][0]["unrecorded_calendar_days"],
            2,
        )
        self.assertIn("cadence is not assumed", history["missing_date_intervals"][0]["interpretation"])

    def test_aggregate_only_and_detailed_snapshot_states(self):
        snapshots = [
            snapshot("2026-09-29", details=None),
            snapshot("2026-09-30", details={"AAA": {"market_value": 200}}),
        ]
        report = self.generate(
            portfolio_data=portfolio(),
            snapshots=snapshots,
            attribution_report={
                "available": True,
                "holding_attribution": {"available": False},
            },
        )
        self.assertEqual(report["snapshot_history"]["aggregate_only_snapshot_count"], 1)
        self.assertEqual(report["snapshot_history"]["detailed_snapshot_count"], 1)
        self.assertEqual(
            report["snapshot_history"]["snapshots"][0]["detail_status"],
            "AGGREGATE_ONLY",
        )
        self.assertEqual(
            report["snapshot_history"]["snapshots"][1]["detail_status"],
            "DETAILED",
        )

    def test_two_detailed_snapshots_allow_attribution_availability(self):
        _, snapshots, historical = history_report(count=2, detail_count=2)
        report = self.generate(
            portfolio_data=portfolio(),
            snapshots=snapshots,
            historical_report=historical,
            attribution_report={
                "available": True,
                "holding_attribution": {"available": True},
            },
        )
        self.assertEqual(
            report["snapshot_history"]["holding_level_attribution"]["status"],
            "AVAILABLE",
        )

    def test_attribution_limitation_is_explained(self):
        _, snapshots, historical = history_report(count=2, detail_count=1)
        report = self.generate(
            portfolio_data=portfolio(),
            snapshots=snapshots,
            historical_report=historical,
            attribution_report={
                "available": True,
                "holding_attribution": {
                    "available": False,
                    "reason": "Missing detail",
                },
            },
        )
        self.assertEqual(
            report["snapshot_history"]["holding_level_attribution"]["status"],
            "UNAVAILABLE",
        )
        self.assertIn(
            "do not both contain detailed holding data",
            report["snapshot_history"]["holding_level_attribution"]["message"],
        )

    def test_exact_date_question_uses_only_dates_with_snapshots(self):
        report = self.generate(
            portfolio_data=portfolio(),
            snapshots=[snapshot("2026-09-29"), snapshot("2026-10-01")],
        )
        exact = report["snapshot_history"]["exact_date_questions"]
        self.assertEqual(
            exact["available_snapshot_dates"],
            ["2026-09-29", "2026-10-01"],
        )
        self.assertIn("no nearby-date substitution", exact["message"])

    def test_invalid_holding_snapshot_json_is_reported_not_repaired(self):
        report = self.generate(
            portfolio_data=portfolio(),
            snapshots=[{
                **snapshot("2026-09-29"),
                "holding_snapshot_json": "{invalid",
            }],
        )
        self.assertTrue(any(
            item["code"] == "INVALID_HOLDING_SNAPSHOT_DETAIL"
            for item in report["issues"]
        ))
        self.assertEqual(
            report["snapshot_history"]["snapshots"][0]["detail_status"],
            "INVALID",
        )


class DataQualityGoalsAndBenchmarkTests(DataQualityTestSupport):
    def test_no_goals_is_unknown_not_invalid_or_judged(self):
        report = self.generate(portfolio_data=portfolio(), goals=[])
        self.assertEqual(report["goals"]["status"], "UNKNOWN")
        self.assertEqual(report["goals"]["active_goal_count"], 0)

    def test_valid_goal_and_missing_target_date_are_reported(self):
        report = self.generate(
            portfolio_data=portfolio(),
            goals=[{
                "id": 1,
                "goal_name": "Synthetic",
                "target_type": "PORTFOLIO_VALUE",
                "target_value": 1000,
                "target_date": None,
                "is_active": 1,
            }],
            goals_report={"goals": [{"id": 1, "current_value": 200}]},
        )
        self.assertEqual(report["goals"]["status"], "LIMITED")
        self.assertEqual(report["goals"]["goals_without_target_date"], [1])

    def test_invalid_goal_data_is_reported(self):
        report = self.generate(
            portfolio_data=portfolio(),
            goals=[{
                "id": 8,
                "goal_name": "Synthetic",
                "target_type": "BROKEN",
                "target_value": float("nan"),
                "target_date": "2026-02-30",
                "is_active": 1,
            }],
        )
        self.assertEqual(report["goals"]["status"], "LIMITED")
        self.assertIn(8, report["goals"]["invalid_goal_ids"])

    def test_no_benchmarks_is_unknown_without_assumption(self):
        report = self.generate(
            portfolio_data=portfolio(),
            benchmarks=[],
        )
        self.assertEqual(report["benchmarks"]["status"], "UNKNOWN")
        self.assertEqual(report["benchmarks"]["configured_count"], 0)

    def test_benchmark_with_insufficient_observations_is_limited(self):
        benchmark = {
            "id": 1,
            "benchmark_name": "User supplied",
            "benchmark_type": "USER_PROVIDED_VALUE",
            "is_active": 1,
        }
        report = self.generate(
            portfolio_data=portfolio(),
            snapshots=[snapshot("2026-09-30"), snapshot("2026-10-01")],
            benchmarks=[benchmark],
            observations_by_benchmark={
                1: [{"date": "2026-09-30", "value": 100}],
            },
            goals_report={"benchmarks": [{
                "id": 1,
                "comparison": {
                    "available": False,
                    "message": "Need two matching observations.",
                },
            }]},
        )
        self.assertEqual(report["benchmarks"]["status"], "LIMITED")
        self.assertEqual(report["benchmarks"]["items"][0]["observation_count"], 1)

    def test_benchmark_with_exact_matching_dates_is_available(self):
        benchmark = {
            "id": 1,
            "benchmark_name": "Configured",
            "benchmark_type": "USER_PROVIDED_VALUE",
            "is_active": 1,
        }
        report = self.generate(
            portfolio_data=portfolio(),
            snapshots=[snapshot("2026-09-30"), snapshot("2026-10-01")],
            benchmarks=[benchmark],
            observations_by_benchmark={
                1: [
                    {"date": "2026-09-30", "value": 100},
                    {"date": "2026-10-01", "value": 110},
                ],
            },
            goals_report={"benchmarks": [{
                "id": 1,
                "comparison": {
                    "available": True,
                    "message": None,
                },
            }]},
        )
        self.assertEqual(report["benchmarks"]["status"], "AVAILABLE")
        self.assertEqual(
            report["benchmarks"]["items"][0]["matching_snapshot_dates"],
            ["2026-09-30", "2026-10-01"],
        )

    def test_missing_benchmark_matching_dates_are_listed(self):
        report = self.generate(
            portfolio_data=portfolio(),
            snapshots=[snapshot("2026-09-30"), snapshot("2026-10-01")],
            benchmarks=[{
                "id": 1,
                "benchmark_name": "Configured",
                "benchmark_type": "USER_PROVIDED_VALUE",
                "is_active": 1,
            }],
            observations_by_benchmark={
                1: [{"date": "2026-09-30", "value": 100}],
            },
            goals_report={"benchmarks": []},
        )
        self.assertEqual(
            report["benchmarks"]["items"][0]["missing_matching_snapshot_dates"],
            ["2026-10-01"],
        )

    def test_future_benchmark_observation_is_flagged_and_not_used(self):
        report = self.generate(
            portfolio_data=portfolio(),
            snapshots=[snapshot("2026-10-01")],
            benchmarks=[{
                "id": 1,
                "benchmark_name": "Configured",
                "benchmark_type": "USER_PROVIDED_VALUE",
                "is_active": 1,
            }],
            observations_by_benchmark={
                1: [{"date": "2026-10-02", "value": 110}],
            },
            goals_report={"benchmarks": []},
        )
        item = report["benchmarks"]["items"][0]
        self.assertEqual(item["future_observation_dates"], ["2026-10-02"])
        self.assertEqual(item["observation_count"], 0)


class DataQualityNewsAndOverallTests(DataQualityTestSupport):
    def test_news_not_supplied_is_unknown_not_reported_as_empty(self):
        report = self.generate(
            portfolio_data=portfolio(),
            news_by_symbol=None,
        )

        self.assertEqual(report["news"]["status"], "UNKNOWN")
        self.assertEqual(report["news"]["holdings"], [])
        self.assertNotIn(
            "No relevant news items were available",
            " ".join(report["news"]["details"]),
        )

    def test_no_news_is_limited_and_not_interpreted(self):
        report = self.generate(
            portfolio_data=portfolio(),
            news_by_symbol={"AAA": []},
        )
        self.assertEqual(report["news"]["status"], "LIMITED")
        self.assertEqual(
            report["news"]["holdings"][0]["message"],
            "No relevant news items were available for this holding.",
        )
        self.assertNotIn("positive", report["news"]["holdings"][0]["message"])
        self.assertNotIn("negative", report["news"]["holdings"][0]["message"])

    def test_available_news_and_duplicate_filter_disclosure(self):
        report = self.generate(
            portfolio_data=portfolio(),
            news_by_symbol={"AAA": [{"title": "Story"}]},
        )
        self.assertEqual(report["news"]["status"], "AVAILABLE")
        self.assertEqual(
            report["news"]["duplicate_syndicated_filtering"]["status"],
            "APPLIED",
        )
        self.assertIsNone(
            report["news"]["duplicate_syndicated_filtering"]["removed_item_count"]
        )

    def test_news_fetch_error_is_explicit(self):
        report = self.generate(
            portfolio_data=portfolio(),
            news_errors=["AAA: retrieval failed"],
        )
        self.assertEqual(report["news"]["status"], "LIMITED")
        self.assertIn("AAA: retrieval failed", report["news"]["details"])

    def test_ai_input_limitations_do_not_block_optional_missing_inputs(self):
        report = self.generate(
            portfolio_data=portfolio(),
            snapshots=[],
            historical_report={},
            attribution_report={},
            risk_report={},
            goals_report={},
            goals=[],
            benchmarks=[],
            news_by_symbol={},
        )
        self.assertTrue(report["ai_analysis_inputs"]["can_generate_explanation"])
        self.assertEqual(report["ai_analysis_inputs"]["status"], "AVAILABLE")
        self.assertTrue(report["ai_analysis_inputs"]["limitations"])

    def test_limited_overall_status_for_optional_historical_limitations(self):
        _, snapshots, historical = history_report(count=1, detail_count=0)
        report = self.generate(
            portfolio_data=portfolio(),
            snapshots=snapshots,
            historical_report=historical,
            attribution_report={"available": False},
            news_by_symbol={"AAA": [{"title": "Story"}]},
        )
        self.assertEqual(report["overall_status"], "LIMITED")

    def test_insufficient_data_overall_status_and_issue_severity(self):
        report = self.generate(
            portfolio_data=portfolio({"AAA": position(price=None, value=None)}),
        )
        self.assertEqual(report["overall_status"], "INSUFFICIENT DATA")
        critical = [
            item for item in report["issues"]
            if item["severity"] == "CRITICAL"
        ]
        self.assertTrue(critical)
        self.assertTrue(all(item["blocks_calculation"] for item in critical))

    def test_no_automatic_repair_and_no_fabricated_values(self):
        report = self.generate(
            portfolio_data=portfolio({"AAA": position(price=None, value=None)}),
            snapshots=[snapshot("2026-09-30")],
        )
        self.assertFalse(report["automatic_repairs_performed"])
        self.assertIsNone(report["market_data"]["holdings"][0]["price"])
        self.assertEqual(report["snapshot_history"]["snapshot_count"], 1)

    def test_report_does_not_modify_supplied_financial_or_snapshot_data(self):
        portfolio_data = portfolio()
        snapshot_data = [snapshot("2026-09-30", details={"AAA": {"market_value": 200}})]
        before_portfolio = json.dumps(portfolio_data, sort_keys=True)
        before_snapshots = json.dumps(snapshot_data, sort_keys=True)
        self.generate(
            portfolio_data=portfolio_data,
            snapshots=snapshot_data,
        )
        self.assertEqual(
            json.dumps(portfolio_data, sort_keys=True),
            before_portfolio,
        )
        self.assertEqual(
            json.dumps(snapshot_data, sort_keys=True),
            before_snapshots,
        )


class DataQualityIntegrationTests(unittest.TestCase):
    def test_dashboard_passes_report_into_template_context(self):
        from dashboard import app as dashboard_module

        expected = {
            "overall_status": "LIMITED",
            "summary": "Data status: LIMITED.",
            "categories": {},
            "market_data": {"holdings": []},
            "snapshot_history": {},
            "issues": [],
        }
        connection = Mock()
        connection.execute.return_value.fetchall.return_value = []
        with (
            patch.object(
                dashboard_module,
                "get_dashboard_data",
                return_value={
                    "portfolio": portfolio(),
                    "analytics": {
                        "allocation": {},
                        "concentration": {},
                        "max_drawdown": {},
                    },
                    "historical": {"history": []},
                },
            ),
            patch.object(dashboard_module, "get_portfolio_alerts", return_value=[]),
            patch.object(dashboard_module, "get_portfolio_change_report", return_value={"available": False}),
            patch.object(dashboard_module, "get_portfolio_snapshots", return_value=[]),
            patch.object(dashboard_module, "get_transactions", return_value=[]),
            patch.object(dashboard_module, "get_opening_positions", return_value=[]),
            patch.object(dashboard_module, "get_company_news", return_value=[]),
            patch.object(dashboard_module, "generate_portfolio_intelligence", return_value={}),
            patch.object(dashboard_module, "generate_risk_intelligence", return_value={}),
            patch.object(dashboard_module, "generate_performance_attribution", return_value={}),
            patch.object(dashboard_module, "generate_historical_analytics", return_value={}),
            patch.object(dashboard_module, "generate_goals_intelligence", return_value={}),
            patch.object(dashboard_module, "generate_data_quality_report", return_value=expected),
            patch.object(dashboard_module.sqlite3, "connect", return_value=connection),
            patch.object(dashboard_module, "generate_portfolio_analysis", return_value=""),
            patch.object(dashboard_module, "render_template", return_value="page") as render,
        ):
            dashboard_module._render_dashboard()
        self.assertEqual(
            render.call_args.kwargs["data_quality_report"],
            expected,
        )

    def test_assistant_data_quality_question_uses_deterministic_report(self):
        from investment_assistant.assistant import _data_quality_question_answer

        report = {
            "overall_status": "LIMITED",
            "summary": "Data status: LIMITED.",
            "categories": {
                "snapshot_history": {
                    "details": [
                        "Trend analysis is limited because only one snapshot exists."
                    ],
                },
                "market_price": {"details": []},
                "benchmarks": {"details": []},
            },
            "snapshot_history": {
                "holding_level_attribution": {
                    "message": "Holding-level attribution unavailable."
                }
            },
            "benchmarks": {"items": []},
            "issues": [],
            "source_limitations": [],
        }
        answer = _data_quality_question_answer(
            "Do I have enough historical data?",
            report,
        )
        self.assertIn("Data status: LIMITED", answer)
        self.assertIn("only one snapshot exists", answer)
        self.assertIn("Holding-level attribution unavailable.", answer)

    def test_assistant_does_not_intercept_unrelated_questions(self):
        from investment_assistant.assistant import _data_quality_question_answer

        self.assertIsNone(
            _data_quality_question_answer(
                "What is my portfolio value?",
                {"overall_status": "READY"},
            )
        )

    def test_assistant_end_to_end_answers_data_question_from_python_report(self):
        from investment_assistant import assistant

        expected = {
            "overall_status": "LIMITED",
            "summary": "Data status: LIMITED.",
            "categories": {
                "snapshot_history": {
                    "details": [
                        "Trend analysis is limited because only one snapshot exists."
                    ],
                },
                "market_price": {"details": []},
                "benchmarks": {"details": []},
            },
            "snapshot_history": {
                "holding_level_attribution": {
                    "message": "Holding-level attribution unavailable."
                }
            },
            "benchmarks": {"items": []},
            "issues": [],
            "source_limitations": [],
        }
        with (
            patch.object(assistant.portfolio, "get_transactions", return_value=[]),
            patch.object(assistant.portfolio, "get_opening_positions", return_value=[]),
            patch.object(assistant.portfolio, "calculate_portfolio_valuation", return_value=portfolio()),
            patch.object(assistant.portfolio, "get_portfolio_analytics_summary", return_value={"allocation": {}, "concentration": {}}),
            patch.object(assistant.portfolio, "get_portfolio_performance_history", return_value=[]),
            patch.object(assistant.portfolio, "get_portfolio_snapshots", return_value=[]),
            patch.object(assistant.portfolio, "get_historical_performance_summary", return_value={}),
            patch.object(assistant.portfolio, "calculate_max_drawdown", return_value={}),
            patch.object(assistant.goals_intelligence, "generate_goals_intelligence", return_value={"goals": [], "benchmarks": []}),
            patch.object(assistant.alerts, "get_portfolio_change_report", return_value={"available": False}),
            patch.object(assistant.risk_intelligence, "generate_risk_intelligence", return_value={}),
            patch.object(assistant.performance_attribution, "generate_performance_attribution", return_value={}),
            patch.object(assistant.historical_analytics, "generate_historical_analytics", return_value={}),
            patch.object(assistant.data_quality, "generate_data_quality_report", return_value=expected) as quality,
            patch.object(assistant.ai_analysis, "generate_portfolio_answer") as gemini,
        ):
            answer = assistant.answer_portfolio_question(
                "Do I have enough historical data?"
            )
        self.assertIn("Data status: LIMITED", answer)
        self.assertIn("only one snapshot exists", answer)
        self.assertIn("Holding-level attribution unavailable.", answer)
        quality.assert_called_once()
        gemini.assert_not_called()

    def test_gemini_receives_report_and_data_quality_rules(self):
        from investment_assistant import ai_analysis

        report = {
            "overall_status": "LIMITED",
            "issues": [{"code": "PRICE_UNAVAILABLE"}],
        }
        with (
            patch.object(ai_analysis, "GEMINI_API_KEY", "test-key"),
            patch.object(ai_analysis, "_request_gemini", return_value="answer") as request,
        ):
            ai_analysis.generate_portfolio_answer(
                "Are there any data issues?",
                {"data_quality": report},
            )
        prompt = " ".join(request.call_args.args[0].split())
        self.assertIn('"overall_status": "LIMITED"', prompt)
        self.assertIn("Never invent missing data", prompt)
        self.assertIn("Never interpret missing news as positive or negative", prompt)
        self.assertIn("preserve Python-calculated statuses", prompt)

    def test_briefing_quality_html_includes_status_and_critical_warnings(self):
        from investment_assistant.briefing import _build_data_quality_html

        html = _build_data_quality_html({
            "overall_status": "LIMITED",
            "issues": [
                {
                    "severity": "CRITICAL",
                    "message": "A price is unavailable.",
                },
                {
                    "severity": "WARNING",
                    "message": "Attribution detail is limited.",
                },
                {
                    "severity": "INFO",
                    "message": "One snapshot is stored.",
                },
            ],
            "snapshot_history": {
                "details": ["Trend analysis has limited history."],
            },
            "market_data": {
                "freshness_counts": {
                    "FRESH": 1,
                    "AGING": 0,
                    "STALE": 0,
                    "UNKNOWN": 0,
                },
                "source_limitation": "Best-effort source.",
            },
            "benchmarks": {"items": []},
        })
        self.assertIn("Data status: LIMITED", html)
        self.assertIn("A price is unavailable.", html)
        self.assertIn("Trend analysis has limited history.", html)
        self.assertNotIn("One snapshot is stored.", html)

    def test_briefing_build_propagates_quality_report_into_gemini_and_email(self):
        from investment_assistant import briefing

        expected = {
            "overall_status": "LIMITED",
            "issues": [{
                "severity": "WARNING",
                "message": "Historical data is limited.",
            }],
            "snapshot_history": {"details": []},
            "market_data": {
                "freshness_counts": {
                    "FRESH": 0,
                    "AGING": 0,
                    "STALE": 0,
                    "UNKNOWN": 0,
                },
                "source_limitation": "Best-effort source.",
            },
            "benchmarks": {"items": []},
        }
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
            patch.object(briefing, "get_portfolio_performance_history", return_value=[]),
            patch.object(briefing, "get_historical_performance_summary", return_value={}),
            patch.object(briefing, "calculate_max_drawdown", return_value={}),
            patch.object(briefing, "calculate_portfolio_changes", return_value={"available": False}),
            patch.object(briefing, "generate_performance_attribution", return_value={}),
            patch.object(briefing, "get_transactions", return_value=[]),
            patch.object(briefing, "get_company_news", return_value=[]),
            patch.object(briefing, "generate_historical_analytics", return_value={}),
            patch.object(briefing, "generate_goals_intelligence", return_value={}),
            patch.object(briefing, "generate_portfolio_intelligence", return_value={}),
            patch.object(briefing, "get_portfolio_analytics_summary", return_value={}),
            patch.object(briefing, "generate_risk_intelligence", return_value={}),
            patch.object(briefing, "generate_data_quality_report", return_value=expected),
            patch.object(briefing, "generate_portfolio_analysis", return_value="Summary") as analysis,
        ):
            result, _, _ = briefing.build_briefing(news_overrides={})
        self.assertEqual(result["data_quality"], expected)
        self.assertEqual(
            analysis.call_args.kwargs["intelligence_report"]["data_quality"],
            expected,
        )
        email = briefing.build_html_email(result, "Summary")
        self.assertIn("Data Quality &amp; Reliability", email)
        self.assertIn("Historical data is limited.", email)

    def test_dashboard_template_integration_renders_data_quality_structure(self):
        from dashboard.app import app

        template = app.jinja_env.get_template("dashboard.html")
        self.assertIsNotNone(template)
        source, _, _ = app.jinja_env.loader.get_source(
            app.jinja_env,
            "dashboard.html",
        )
        for required in (
            "Data Quality &amp; Reliability",
            "Overall Status",
            "Market Data by Holding",
            "Freshness",
            "Historical Data Coverage",
            "Data Quality Issues",
            "Blocks Calculation",
        ):
            self.assertIn(required, source)

    def test_severity_classification_is_factual_and_blocking_is_explicit(self):
        report = data_quality._issue(
            "portfolio",
            "SYNTHETIC",
            "CRITICAL",
            "Synthetic required data is unavailable.",
            affected=["SYNTH"],
            blocks=True,
            next_action="Review the stored input.",
        )
        self.assertEqual(report["severity"], "CRITICAL")
        self.assertTrue(report["blocks_calculation"])
        self.assertEqual(report["affected_items"], ["SYNTH"])
        self.assertEqual(report["next_action"], "Review the stored input.")

    def test_status_and_issue_values_are_from_allowed_sets(self):
        report = data_quality.generate_data_quality_report(
            portfolio_data=portfolio(),
            snapshots=[],
            goals=[],
            benchmarks=[],
            observations_by_benchmark={},
            news_by_symbol={},
            now=NOW,
        )
        self.assertIn(
            report["overall_status"],
            {"READY", "LIMITED", "INSUFFICIENT DATA"},
        )
        for category in report["categories"].values():
            self.assertIn(
                category["status"],
                {"AVAILABLE", "LIMITED", "UNAVAILABLE", "UNKNOWN"},
            )
        for issue in report["issues"]:
            self.assertIn(issue["severity"], {"INFO", "WARNING", "CRITICAL"})


if __name__ == "__main__":
    unittest.main()
