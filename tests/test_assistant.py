import unittest
from datetime import date
from unittest.mock import patch

import requests
from investment_assistant.ai_analysis import generate_portfolio_answer
from investment_assistant.assistant import answer_portfolio_question


PORTFOLIO = {
    "positions": {
        "ABC": {
            "symbol": "ABC",
            "quantity": 10,
            "average_buy_price": 100,
            "current_price": 120,
            "remaining_cost_basis": 1000,
            "current_value": 1200,
            "realized_pnl": 25,
            "unrealized_pnl": 200,
            "total_pnl": 225,
            "return_percent": 20,
            "market_timestamp": "2026-09-30T10:00:00Z",
            "source": "test",
        }
    },
    "total_invested": 1000,
    "total_current_value": 1200,
    "total_realized_pnl": 25,
    "total_unrealized_pnl": 200,
    "total_pnl": 225,
    "total_return_percent": 20,
}

ANALYTICS = {
    "allocation": {"ABC": {"current_value": 1200, "allocation_percent": 100}},
    "concentration": {
        "holding_count": 1,
        "largest_holding_symbol": "ABC",
        "largest_holding_percent": 100,
        "largest_holding_value": 1200,
    },
    "max_drawdown": {
        "max_drawdown_amount": 0,
        "max_drawdown_percent": 0,
        "peak_date": None,
        "trough_date": None,
    },
}

TRANSACTIONS = [(1, "ABC", "ABC Company", "BUY", 10, 100, "2026-01-01")]


class AnswerPortfolioQuestionTests(unittest.TestCase):
    def setUp(self):
        patches = [
            patch(
                "investment_assistant.assistant.portfolio.calculate_portfolio_valuation",
                return_value=PORTFOLIO.copy(),
            ),
            patch(
                "investment_assistant.assistant.portfolio.get_portfolio_analytics_summary",
                return_value=ANALYTICS,
            ),
            patch(
                "investment_assistant.assistant.portfolio.get_portfolio_performance_history",
                return_value=[{"date": "2026-09-30", "total_pnl": 225}],
            ),
            patch(
                "investment_assistant.assistant.portfolio.get_historical_performance_summary",
                return_value={"latest_value": 1200},
            ),
            patch(
                "investment_assistant.assistant.portfolio.get_transactions",
                return_value=TRANSACTIONS,
            ),
            patch(
                "investment_assistant.assistant.portfolio.get_opening_positions",
                return_value=[],
            ),
            patch(
                "investment_assistant.assistant.news.get_company_news",
                return_value=[],
            ),
            patch(
                "investment_assistant.assistant.ai_analysis.generate_portfolio_answer",
                return_value="Mock answer",
            ),
            patch(
                "investment_assistant.assistant.alerts.get_portfolio_change_report",
                return_value={"available": False, "alerts": []},
            ),
            patch(
                "investment_assistant.assistant.intelligence.generate_portfolio_intelligence",
                return_value={"what_changed": {"available": False}},
            ),
            patch(
                "investment_assistant.assistant.portfolio.get_portfolio_snapshots",
                return_value=[],
            ),
            patch(
                "investment_assistant.assistant.historical_analytics.generate_historical_analytics",
                return_value={},
            ),
            patch(
                "investment_assistant.assistant.goals_intelligence.generate_goals_intelligence",
                return_value={"goals": [], "benchmarks": []},
            ),
        ]
        self.mocks = [item.start() for item in patches]
        self.addCleanup(self._stop_patches, patches)

    @staticmethod
    def _stop_patches(patches):
        for item in reversed(patches):
            item.stop()

    def test_portfolio_pnl_question_supplies_python_totals(self):
        answer = answer_portfolio_question("What is my portfolio P&L?")

        self.assertEqual(answer, "Mock answer")
        submitted = self.mocks[7].call_args.args[1]
        self.assertEqual(submitted["portfolio"]["total_realized_pnl"], 25)
        self.assertEqual(submitted["portfolio"]["total_unrealized_pnl"], 200)
        self.assertEqual(submitted["portfolio"]["total_pnl"], 225)
        self.assertIn("portfolio_changes", submitted)

    def test_holding_specific_question_supplies_position(self):
        answer_portfolio_question("How many ABC shares do I hold?")

        submitted = self.mocks[7].call_args.args[1]
        self.assertEqual(submitted["portfolio"]["positions"]["ABC"]["quantity"], 10)
        self.assertEqual(submitted["portfolio"]["positions"]["ABC"]["current_value"], 1200)

    def test_unrequested_news_is_not_reported_as_unavailable(self):
        answer_portfolio_question("What is my current total P&L?")

        submitted = self.mocks[7].call_args.args[1]
        self.assertEqual(
            submitted["data_quality"]["news"]["status"],
            "UNKNOWN",
        )
        self.assertEqual(
            submitted["data_quality"]["news"]["holdings"],
            [],
        )

    def test_data_quality_question_uses_deterministic_report(self):
        answer = answer_portfolio_question(
            "Are there any data-quality issues?"
        )

        self.assertIn("Data status:", answer)
        self.assertIn("Market timestamp for ABC", answer)
        self.assertIn("Yahoo Finance chart endpoint", answer)
        self.assertNotIn("No relevant news items were available", answer)
        self.mocks[7].assert_not_called()

    def test_allocation_and_concentration_are_supplied(self):
        answer_portfolio_question("What is my allocation and concentration?")

        submitted = self.mocks[7].call_args.args[1]
        self.assertEqual(submitted["analytics"]["allocation"], ANALYTICS["allocation"])
        self.assertEqual(
            submitted["analytics"]["concentration"],
            ANALYTICS["concentration"],
        )

    def test_news_question_retrieves_news_for_matching_holding(self):
        answer_portfolio_question("What is the latest news about ABC?")

        self.mocks[6].assert_called_once_with("ABC", max_items=5, days=7)
        submitted = self.mocks[7].call_args.args[1]
        self.assertIn("ABC", submitted["recent_news"])

    def test_empty_question_is_rejected(self):
        with self.assertRaises(ValueError):
            answer_portfolio_question("  ")

        self.mocks[0].assert_not_called()
        self.mocks[7].assert_not_called()

    def test_gemini_failure_returns_fallback(self):
        self.mocks[7].side_effect = ConnectionError("Gemini unavailable")

        answer = answer_portfolio_question("What is my total P&L?")

        self.assertIn("AI service is currently unavailable", answer)

    def test_current_portfolio_data_is_separate_from_history_context(self):
        history = [
            {
                "user_question": "What was the old P&L?",
                "assistant_answer": "The old total P&L was ₹10.",
            }
        ]

        answer_portfolio_question(
            "What is my current total P&L?",
            conversation_history=history,
        )

        submitted_data = self.mocks[7].call_args.args[1]
        submitted_history = self.mocks[7].call_args.kwargs[
            "conversation_history"
        ]
        self.assertEqual(submitted_data["portfolio"]["total_pnl"], 225)
        self.assertEqual(submitted_history, history)

    def test_change_question_receives_deterministic_alert_data(self):
        answer_portfolio_question("What changed since my last snapshot?")

        submitted = self.mocks[7].call_args.args[1]
        self.assertEqual(
            submitted["portfolio_changes"],
            {"available": False, "alerts": []},
        )
        self.assertEqual(
            submitted["portfolio_intelligence"],
            {"what_changed": {"available": False}},
        )

    def test_intelligence_context_includes_news_for_why_and_monitor_questions(self):
        answer_portfolio_question("Why did my portfolio change?")

        self.mocks[6].assert_called_once_with("ABC", max_items=5, days=7)
        submitted = self.mocks[7].call_args.args[1]
        self.assertIn("portfolio_intelligence", submitted)

    def test_relative_date_portfolio_value_uses_matching_snapshot_first(self):
        from investment_assistant import assistant

        history = [
            {"date": "2026-09-29", "total_current_value": 20070.5},
            {"date": "2026-10-01", "total_current_value": 19886.0},
        ]
        with (
            patch.object(
                assistant.portfolio,
                "get_portfolio_performance_history",
                return_value=history,
            ),
            patch.object(assistant, "date") as mocked_date,
        ):
            mocked_date.today.return_value = date(2026, 10, 1)
            answer = assistant.answer_portfolio_question(
                "What was my portfolio value two days ago?"
            )

        self.assertEqual(
            answer,
            "Two days ago (September 29, 2026), your portfolio value was ₹20,070.50.",
        )
        self.mocks[7].assert_not_called()

    def test_relative_date_portfolio_value_does_not_fabricate_missing_snapshot(self):
        from investment_assistant import assistant

        with (
            patch.object(
                assistant.portfolio,
                "get_portfolio_performance_history",
                return_value=[
                    {"date": "2026-09-30", "total_current_value": 20000},
                ],
            ),
            patch.object(assistant, "date") as mocked_date,
        ):
            mocked_date.today.return_value = date(2026, 10, 1)
            answer = assistant.answer_portfolio_question(
                "What was my portfolio value two days ago?"
            )

        self.assertEqual(
            answer,
            "No portfolio-value snapshot is available for two days ago (September 29, 2026).",
        )
        self.mocks[7].assert_not_called()

    def test_assistant_rounds_percentages_in_generated_answer(self):
        self.mocks[7].return_value = (
            "The portfolio value changed by -0.91925960987519% "
            "and one holding changed by +12.5%."
        )

        answer = answer_portfolio_question("What changed in my portfolio?")

        self.assertEqual(
            answer,
            "The portfolio value changed by -0.92% and one holding changed by +12.50%.",
        )

    def test_conversation_history_redacts_secrets(self):
        from investment_assistant.assistant import sanitize_conversation_history

        history = sanitize_conversation_history([
            {
                "user_question": "My api_key=hidden-value, what is P&L?",
                "assistant_answer": "Use password is hidden-answer.",
            }
        ])

        self.assertNotIn("hidden-value", history[0]["user_question"])
        self.assertNotIn("hidden-answer", history[0]["assistant_answer"])


class GeminiAnswerTests(unittest.TestCase):
    @patch("investment_assistant.ai_analysis.GEMINI_API_KEY", None)
    def test_missing_ai_service_configuration_uses_friendly_message(self):
        answer = generate_portfolio_answer("Question", {})

        self.assertEqual(
            answer,
            "AI analysis is temporarily unavailable. Your portfolio data "
            "and other dashboard information are still available.",
        )

    @patch(
        "investment_assistant.ai_analysis._request_gemini",
        return_value="Mocked response",
    )
    def test_prompt_marks_live_data_authoritative_over_history(self, request):
        generate_portfolio_answer(
            "What is my current total P&L?",
            {"portfolio": {"total_pnl": 225}},
            conversation_history=[
                {
                    "user_question": "What was my P&L?",
                    "assistant_answer": "The old total P&L was 10.",
                }
            ],
        )

        prompt = request.call_args.args[0]
        self.assertIn('"total_pnl": 225', prompt)
        self.assertIn("The old total P&L was 10.", prompt)
        self.assertIn(
            "The current structured application data above is authoritative.",
            prompt,
        )
        self.assertIn("calculate or infer missing comparisons.", prompt)
        self.assertIn("target-price predictions", prompt)
        self.assertIn(
            "format all portfolio percentages to exactly",
            prompt,
        )
        self.assertIn("two decimal places", prompt)
        self.assertIn("requested snapshot value first", prompt)

    @patch(
        "investment_assistant.ai_analysis._request_gemini",
        return_value="Mocked briefing",
    )
    def test_analysis_prompt_receives_intelligence_and_safety_rules(self, request):
        from investment_assistant.ai_analysis import generate_portfolio_analysis

        intelligence_report = {
            "what_changed": {
                "portfolio_value_change": 125,
                "contributors": None,
            },
            "data_limitations": ["Only one snapshot is available."],
        }
        generate_portfolio_analysis(
            {
                **PORTFOLIO,
                "total_return_percent": 20,
            },
            {},
            intelligence_report=intelligence_report,
        )

        prompt = request.call_args.args[0]
        self.assertIn('"portfolio_value_change": 125', prompt)
        self.assertIn("Do not describe an investment as good, bad, safe", prompt)
        self.assertIn("Never predict target prices", prompt)
        self.assertIn("caused a price movement", prompt)
        self.assertIn("Python is the sole source", prompt)

    @patch("investment_assistant.ai_analysis.GEMINI_API_KEY", "test-api-key")
    @patch(
        "investment_assistant.ai_analysis.requests.post",
        side_effect=requests.exceptions.ConnectionError("offline"),
    )
    def test_api_failure_uses_fallback_without_live_request(self, post):
        answer = generate_portfolio_answer(
            "What is my P&L?",
            {"portfolio": {"total_pnl": 125}},
        )

        self.assertIn("AI service is temporarily unavailable", answer)
        post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
