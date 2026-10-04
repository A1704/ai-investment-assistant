import unittest
from unittest.mock import patch

from investment_assistant.assistant import handle_assistant_request
from investment_assistant.computer_control import (
    ComputerCommand,
    ComputerControlError,
    execute_computer_command,
    open_chrome,
    open_google,
    open_url,
    open_youtube,
    parse_computer_command,
    search_google,
    validate_safe_url,
)


class ParseComputerCommandTests(unittest.TestCase):
    def test_parses_each_supported_action(self):
        cases = (
            ("Open Google", ComputerCommand("open_google")),
            ("Open Chrome", ComputerCommand("open_chrome")),
            ("Open YouTube", ComputerCommand("open_youtube")),
            (
                "Search Google for Python internships",
                ComputerCommand("search_google", "Python internships"),
            ),
            (
                "Open https://example.com/path",
                ComputerCommand("open_url", "https://example.com/path"),
            ),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(parse_computer_command(text), expected)

    def test_normal_portfolio_question_is_not_a_computer_command(self):
        self.assertIsNone(
            parse_computer_command("What is my current total P&L?")
        )

    def test_unsupported_computer_commands_are_rejected(self):
        for text in ("Open PowerShell", "Run notepad", "Delete my files"):
            with self.subTest(text=text):
                with self.assertRaises(ComputerControlError):
                    parse_computer_command(text)

    def test_arbitrary_shell_command_is_rejected(self):
        with self.assertRaises(ComputerControlError):
            parse_computer_command("Run powershell -Command Get-Process")


class ExecuteComputerCommandTests(unittest.TestCase):
    @patch("investment_assistant.computer_control.webbrowser.open", return_value=True)
    def test_open_google(self, browser_open):
        self.assertEqual(open_google(), "Opened Google.")
        browser_open.assert_called_once_with("https://www.google.com/", new=2)

    @patch(
        "investment_assistant.computer_control._chrome_executable_path",
        return_value=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    )
    @patch("investment_assistant.computer_control.subprocess.Popen")
    def test_open_chrome_uses_fixed_executable_without_shell(self, popen, _path):
        self.assertEqual(open_chrome(), "Opened Google Chrome.")
        popen.assert_called_once_with(
            [r"C:\Program Files\Google\Chrome\Application\chrome.exe"],
            shell=False,
        )

    @patch("investment_assistant.computer_control.webbrowser.open", return_value=True)
    def test_open_youtube(self, browser_open):
        self.assertEqual(open_youtube(), "Opened YouTube.")
        browser_open.assert_called_once_with("https://www.youtube.com/", new=2)

    @patch("investment_assistant.computer_control.webbrowser.open", return_value=True)
    def test_google_search_query_is_url_encoded(self, browser_open):
        self.assertEqual(
            search_google("Python internships & jobs"),
            "Opened Google search results for your query.",
        )
        browser_open.assert_called_once_with(
            "https://www.google.com/search?q=Python+internships+%26+jobs",
            new=2,
        )

    @patch("investment_assistant.computer_control.webbrowser.open", return_value=True)
    def test_open_user_url(self, browser_open):
        self.assertEqual(
            open_url("https://example.com"),
            "Opened https://example.com/.",
        )
        browser_open.assert_called_once_with("https://example.com/", new=2)

    def test_url_validation_rejects_unsafe_urls(self):
        unsafe_urls = (
            "javascript:alert(1)",
            "file:///C:/Windows/win.ini",
            "http://localhost/",
            "http://127.0.0.1/",
            "http://192.168.1.5/",
            "https://user:password@example.com/",
            "https://example.com:8080/",
        )
        for url in unsafe_urls:
            with self.subTest(url=url):
                with self.assertRaises(ComputerControlError):
                    validate_safe_url(url)

    @patch("investment_assistant.computer_control.webbrowser.open", return_value=True)
    def test_unsupported_search_service_is_not_opened(self, browser_open):
        with self.assertRaises(ComputerControlError):
            parse_computer_command("Search YouTube for music")
        browser_open.assert_not_called()

    @patch("investment_assistant.assistant.answer_portfolio_question")
    def test_portfolio_question_uses_existing_assistant(self, answer):
        answer.return_value = "Your answer"

        result = handle_assistant_request(
            "What is my current total P&L?",
            conversation_history=[{"user_question": "Earlier", "assistant_answer": "Answer"}],
        )

        self.assertEqual(result, "Your answer")
        answer.assert_called_once()

    @patch("investment_assistant.assistant.answer_portfolio_question")
    @patch(
        "investment_assistant.computer_control.webbrowser.open",
        return_value=True,
    )
    def test_supported_command_bypasses_portfolio_ai(self, browser_open, answer):
        result = handle_assistant_request("Open Google")

        self.assertEqual(result, "Opened Google.")
        browser_open.assert_called_once()
        answer.assert_not_called()

    @patch("investment_assistant.assistant.answer_portfolio_question")
    def test_unsupported_command_does_not_reach_portfolio_ai(self, answer):
        result = handle_assistant_request("Run powershell -Command Get-Process")

        self.assertIn("That computer command is not supported", result)
        answer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
