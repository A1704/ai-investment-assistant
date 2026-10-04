import unittest
from unittest.mock import patch

from dashboard.app import (
    _ASSISTANT_CONVERSATIONS,
    _ASSISTANT_CONVERSATIONS_LOCK,
    _format_inr,
    _format_quantity,
    app,
)


class DashboardAssistantRouteTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()
        self.dashboard_patches = [
            patch(
                "dashboard.app.get_dashboard_data",
                return_value={"portfolio": {"positions": {}}},
            ),
            patch("dashboard.app.get_portfolio_alerts", return_value=[]),
            patch(
                "dashboard.app.get_portfolio_change_report",
                return_value={
                    "available": False,
                    "message": "Not enough historical snapshots.",
                    "alerts": [],
                    "holding_changes": [],
                    "concentration_changes": [],
                },
            ),
            patch("dashboard.app.get_portfolio_snapshots", return_value=[]),
            patch(
                "dashboard.app.generate_historical_analytics",
                return_value={"history": [], "trend_metrics": {}, "data_quality": {}},
            ),
            patch(
                "dashboard.app.generate_goals_intelligence",
                return_value={"goals": [], "benchmarks": []},
            ),
            patch(
                "dashboard.app.generate_performance_attribution",
                return_value={},
            ),
            patch(
                "dashboard.app.sqlite3.connect",
                return_value=self._mock_connection(),
            ),
            patch("dashboard.app.generate_portfolio_analysis", return_value=""),
            patch("dashboard.app.render_template", return_value="assistant page"),
        ]
        self.dashboard_mocks = []
        for mocked in self.dashboard_patches:
            self.dashboard_mocks.append(mocked.start())
            self.addCleanup(mocked.stop)

    @staticmethod
    def _mock_connection():
        from unittest.mock import Mock

        connection = Mock()
        connection.execute.return_value.fetchall.return_value = []
        return connection

    @patch("dashboard.app.handle_assistant_request", return_value="Mocked answer")
    def test_post_calls_assistant_and_returns_answer_page(self, answer):
        response = self.client.post(
            "/assistant",
            data={"question": "What is my current total P&L?"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "assistant page")
        answer.assert_called_once_with(
            "What is my current total P&L?",
            conversation_history=[],
        )
        self.assertEqual(
            self.dashboard_mocks[-1].call_args.kwargs["assistant_answer"],
            "Mocked answer",
        )
        self.dashboard_mocks[8].assert_not_called()

    @patch(
        "dashboard.app.handle_assistant_request",
        side_effect=["First answer", "Follow-up answer"],
    )
    def test_follow_up_receives_previous_exchange(self, answer):
        with self.client:
            self.client.post(
                "/assistant",
                data={"question": "What is my current total P&L?"},
            )
            self.client.post(
                "/assistant",
                data={"question": "Which holding contributes the most?"},
            )

            self.assertEqual(
                answer.call_args_list[0].kwargs["conversation_history"],
                [],
            )
            self.assertEqual(
                answer.call_args_list[1].kwargs["conversation_history"],
                [
                    {
                        "user_question": "What is my current total P&L?",
                        "assistant_answer": "First answer",
                    }
                ],
            )

    @patch(
        "dashboard.app.handle_assistant_request",
        side_effect=lambda question, conversation_history: "Answer: " + question,
    )
    def test_conversation_history_is_limited_to_five_recent_exchanges(self, answer):
        with self.client:
            for index in range(6):
                self.client.post(
                    "/assistant",
                    data={"question": f"Question {index + 1}"},
                )

            passed_history = answer.call_args_list[-1].kwargs[
                "conversation_history"
            ]
            self.assertEqual(len(passed_history), 5)
            self.assertEqual(
                [item["user_question"] for item in passed_history],
                [
                    "Question 1",
                    "Question 2",
                    "Question 3",
                    "Question 4",
                    "Question 5",
                ],
            )
            with self.client.session_transaction() as flask_session:
                session_id = flask_session["assistant_session_id"]
                self.assertNotIn("assistant_history", flask_session)

            with _ASSISTANT_CONVERSATIONS_LOCK:
                self.assertEqual(
                    [
                        item["user_question"]
                        for item in _ASSISTANT_CONVERSATIONS[session_id]
                    ],
                    [
                        "Question 2",
                        "Question 3",
                        "Question 4",
                        "Question 5",
                        "Question 6",
                    ],
                )

    @patch("dashboard.app.handle_assistant_request")
    def test_empty_question_skips_assistant(self, answer):
        response = self.client.post("/assistant", data={"question": "  "})

        self.assertEqual(response.status_code, 200)
        answer.assert_not_called()
        self.assertEqual(
            self.dashboard_mocks[-1].call_args.kwargs["assistant_answer"],
            "Please enter a question for the AI Portfolio Assistant.",
        )
        self.dashboard_mocks[8].assert_not_called()

    @patch(
        "dashboard.app.handle_assistant_request",
        side_effect=RuntimeError("assistant unavailable"),
    )
    def test_assistant_error_is_handled(self, answer):
        response = self.client.post(
            "/assistant",
            data={"question": "Tell me about my holdings"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "assistant page")
        answer.assert_called_once()
        rendered = self.dashboard_mocks[-1].call_args.kwargs
        self.assertIn("could not answer right now", rendered["assistant_answer"])
        self.assertNotIn("assistant unavailable", rendered["assistant_answer"])
        self.dashboard_mocks[8].assert_not_called()

    @patch("dashboard.app.handle_assistant_request", return_value="Opened YouTube.")
    def test_computer_action_result_is_separate_from_assistant_answer(self, answer):
        response = self.client.post(
            "/assistant",
            data={"question": "Open YouTube"},
        )

        self.assertEqual(response.status_code, 200)
        answer.assert_called_once()
        rendered = self.dashboard_mocks[-1].call_args.kwargs
        self.assertEqual(rendered["assistant_action_result"], "Opened YouTube.")
        self.assertEqual(rendered["assistant_answer"], "")
        self.assertIn("not refreshed", rendered["ai_analysis"])
        self.dashboard_mocks[8].assert_not_called()


    def test_dashboard_template_contains_assistant_form_and_examples(self):
        template = app.jinja_env.get_template("dashboard.html")

        self.assertIsNotNone(template)
        source, _, _ = app.jinja_env.loader.get_source(
            app.jinja_env,
            "dashboard.html",
        )
        self.assertIn('action="{{ url_for(\'assistant_route\') }}"', source)
        self.assertIn('id="assistant-microphone"', source)
        self.assertIn("window.SpeechRecognition", source)
        self.assertIn("window.webkitSpeechRecognition", source)
        self.assertNotIn("processLocally", source)
        self.assertIn("speechSynthesis.speak(utterance)", source)
        self.assertIn("speechSynthesis.getVoices()", source)
        self.assertIn('"voiceschanged"', source)
        self.assertIn("utterance.volume = 1", source)
        self.assertIn("utterance.rate = 0.95", source)
        self.assertIn("utterance.onstart", source)
        self.assertIn("utterance.onend", source)
        self.assertIn("utterance.onerror", source)
        self.assertIn('id="assistant-test-voice"', source)
        self.assertIn('id="assistant-stop-speaking"', source)
        self.assertIn("Speech playback failed. You can still read the answer above.", source)
        self.assertIn('hidden\n            style=', source)
        self.assertIn('window.addEventListener("load", startAnswerSpeech', source)
        self.assertIn("utterance.lang = voice ? voice.lang : \"en-US\"", source)
        self.assertIn(
            "Voice input unavailable in this browser.",
            source,
        )
        self.assertIn(
            "Voice recognition uses your browser's speech service and is not stored by this app.",
            source,
        )
        self.assertIn("What changed in my portfolio?", source)
        self.assertIn("Where is my portfolio concentrated?", source)
        self.assertIn("What is my current portfolio value?", source)
        self.assertIn("How much unrealized P&amp;L do I have?", source)
        self.assertIn("Do I have enough historical data?", source)
        self.assertIn("Are there any data-quality issues?", source)
        self.assertIn("data-state=\"idle\">Ready", source)
        self.assertIn('"processing-indicator"', source)
        self.assertIn('aria-label="Dashboard sections"', source)
        self.assertIn('class="assistant-action-result"', source)
        self.assertIn('class="assistant-answer"', source)
        self.assertIn('@media (max-width: 600px)', source)
        self.assertIn("overscroll-behavior-x: contain", source)
        self.assertIn("prefers-reduced-motion", source)
        self.assertIn("Data Quality &amp; Reliability", source)
        self.assertIn("class=\"status status-", source)
        self.assertIn("scope=\"col\">Allocation", source)
        self.assertNotIn("● Live Data", source)
        self.assertIn("Portfolio Intelligence", source)
        self.assertIn("Largest positive contributor to the latest portfolio-value change", source)
        self.assertIn("News is contextual information", source)
        self.assertIn(
            'portfolio_intelligence.relevant_news["items"]',
            source,
        )
        self.assertIn(
            'portfolio_intelligence.holding_level_changes["items"]',
            source,
        )


class DashboardFormattingTests(unittest.TestCase):
    def test_currency_filter_uses_indian_grouping_and_two_decimals(self):
        self.assertEqual(_format_inr(1234567.8), "₹12,34,567.80")
        self.assertEqual(_format_inr(-123456.789), "-₹1,23,456.79")

    def test_currency_filter_does_not_turn_unavailable_values_into_zero(self):
        self.assertEqual(_format_inr(None), "Unavailable")
        self.assertEqual(_format_inr(float("inf")), "Unavailable")

    def test_quantity_filter_limits_and_trims_display_precision(self):
        self.assertEqual(_format_quantity(12.5), "12.5")
        self.assertEqual(_format_quantity(0), "0")
        self.assertEqual(_format_quantity(None), "Unavailable")


if __name__ == "__main__":
    unittest.main()
