import json
import logging
import re
from datetime import date, timedelta

from investment_assistant import (
    ai_analysis,
    alerts,
    intelligence,
    historical_analytics,
    news,
    portfolio,
    performance_attribution,
    risk_intelligence,
    goals_intelligence,
    data_quality,
)
from investment_assistant.computer_control import (
    ComputerControlError,
    execute_computer_command,
    parse_computer_command,
)


MAX_CONVERSATION_EXCHANGES = 5

_SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_ -]?key|password|passwd|passphrase|secret|token|"
        r"credential|private[_ -]?key)\b(\s*(?:is|:|=)\s*)([^\s,;]+)"
    ),
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)

NEWS_QUESTION_TERMS = (
    "news",
    "headline",
    "headlines",
    "update",
    "updates",
    "recent event",
    "recent events",
    "what happened",
    "what changed",
    "changed in my portfolio",
    "why did my portfolio change",
    "why did it change",
    "what should i watch",
    "monitor",
    "concentrated",
)

_RELATIVE_DAYS = {
    "one": 1,
    "a": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def sanitize_conversation_history(history):
    if not isinstance(history, list):
        return []

    sanitized = []
    for exchange in history[-MAX_CONVERSATION_EXCHANGES:]:
        if not isinstance(exchange, dict):
            continue

        question = exchange.get("user_question")
        answer = exchange.get("assistant_answer")
        if not isinstance(question, str) or not isinstance(answer, str):
            continue

        sanitized.append(
            {
                "user_question": _redact_secrets(question[:2000]),
                "assistant_answer": _redact_secrets(answer[:4000]),
            }
        )
    return sanitized


def _redact_secrets(text):
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(r"\1\2[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text


def _format_answer_percentages(text):
    percentage_pattern = re.compile(
        r"(?<![\w.])([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)\s*%"
    )

    def format_match(match):
        original_value = match.group(1)
        value = float(original_value.replace(",", ""))
        sign = "+" if original_value.startswith("+") and value >= 0 else ""
        return f"{sign}{value:.2f}%"

    return percentage_pattern.sub(format_match, text)


def _question_requests_news(question):
    question_lower = question.casefold()
    return any(term in question_lower for term in NEWS_QUESTION_TERMS)


def _company_names_by_symbol(transactions, opening_positions):
    company_names = {}

    for opening_position in opening_positions:
        company_names[opening_position[1].upper()] = opening_position[2]

    for transaction in transactions:
        company_names[transaction[1].upper()] = transaction[2]

    return company_names


def _news_symbols(question, symbols, company_names):
    question_lower = question.casefold()
    matching_symbols = [
        symbol
        for symbol in symbols
        if symbol.casefold() in question_lower
        or company_names.get(symbol, "").casefold() in question_lower
    ]
    return matching_symbols or list(symbols)


def _format_goal_number(value, *, currency=False, percent=False):
    if value is None:
        return "Unavailable"
    if currency:
        return f"₹{value:,.2f}"
    if percent:
        return f"{value:.2f}%"
    return f"{value:.2f}"


def _goals_question_answer(question, report):
    question_lower = question.casefold()
    asks_goals = any(
        term in question_lower
        for term in (
            "goal",
            "target date",
            "target value",
            "portfolio target",
            "target portfolio",
            "return target",
            "how much remains",
            "reached my",
        )
    )
    asks_benchmark = "benchmark" in question_lower
    if not asks_goals and not asks_benchmark:
        return None

    lines = []
    if asks_goals:
        goals = report.get("goals", [])
        if not goals:
            lines.append("No portfolio goals configured.")
        else:
            for goal in goals:
                difference = goal.get("difference")
                if difference is None:
                    difference_text = "Unavailable"
                elif goal["difference_unit"] == "currency":
                    difference_text = _format_goal_number(
                        difference,
                        currency=True,
                    )
                else:
                    difference_text = f"{difference:+.2f} pp"
                lines.append(
                    f"{goal['goal_name']} — {goal['target_type']}: "
                    f"target {_format_goal_number(goal['target_value'], currency=goal['unit'] == 'currency', percent=goal['unit'] == 'percent')}; "
                    f"current {_format_goal_number(goal['current_value'], currency=goal['unit'] == 'currency', percent=goal['unit'] == 'percent')}; "
                    f"difference {difference_text}."
                )
                if goal.get("progress_percent") is not None:
                    lines.append(
                        f"Progress: {goal['progress_percent']:.2f}%."
                    )
                if goal.get("remaining_amount") is not None:
                    lines.append(
                        "Remaining amount: "
                        f"{_format_goal_number(goal['remaining_amount'], currency=True)}."
                    )
                if goal.get("target_date"):
                    lines.append(
                        f"Target date: {goal['target_date']}. "
                        f"{goal['target_date_status']}"
                    )
                lines.append(f"Status: {goal['status']}.")

    if asks_benchmark:
        benchmarks = report.get("benchmarks", [])
        if not benchmarks:
            lines.append("No portfolio benchmarks configured.")
        for benchmark in benchmarks:
            comparison = benchmark["comparison"]
            if not comparison.get("available"):
                lines.append(
                    f"{benchmark['benchmark_name']}: "
                    f"{comparison.get('message') or 'Benchmark comparison unavailable.'}"
                )
                continue
            lines.append(
                f"{benchmark['benchmark_name']} "
                f"({comparison['period_start_date']} to "
                f"{comparison['period_end_date']}): portfolio return "
                f"{comparison['portfolio_return_percent']:.2f}%, "
                f"configured benchmark return "
                f"{comparison['benchmark_return_percent']:.2f}%, "
                f"difference "
                f"{comparison['difference_percentage_points']:+.2f} "
                "percentage points. "
                f"{comparison['portfolio_return_basis']}"
            )
    return "\n".join(lines)


def _data_quality_question_answer(question, report):
    question_lower = question.casefold()
    requested_terms = (
        "data reliable",
        "data issue",
        "historical data",
        "market data fresh",
        "historical question",
        "data is missing",
        "benchmark comparison",
        "trust the current",
        "limitations of my investment assistant",
        "data quality",
        "data-quality",
    )
    if not any(term in question_lower for term in requested_terms):
        return None

    lines = [
        f"Data status: {report['overall_status']}.",
        report["summary"],
    ]
    relevant_category = (
        "benchmarks" if "benchmark" in question_lower
        else "snapshot_history"
        if "historical" in question_lower
        else "market_price"
        if "market" in question_lower
        else None
    )
    if relevant_category:
        category = report["categories"][relevant_category]
        lines.extend(category.get("details", []))
        if relevant_category == "snapshot_history":
            limitation = report["snapshot_history"].get(
                "holding_level_attribution", {}
            ).get("message")
            if limitation:
                lines.append(limitation)
        if relevant_category == "benchmarks":
            for item in report["benchmarks"].get("items", []):
                if item.get("comparison_status") != "AVAILABLE":
                    lines.append(
                        f"{item.get('name')}: "
                        f"{item.get('comparison_message') or 'Benchmark comparison unavailable.'}"
                    )
    else:
        lines.extend(
            issue["message"]
            for issue in report.get("issues", [])
        )
        lines.extend(report.get("source_limitations", []))
    if len(lines) == 2:
        lines.append(
            "No additional data-quality limitation was identified in the supplied report."
        )
    return "\n".join(dict.fromkeys(lines))


def _historical_portfolio_value_answer(
    question,
    performance_history,
    today=None,
):
    question_lower = question.casefold()
    if not any(
        term in question_lower
        for term in ("portfolio value", "portfolio worth")
    ):
        return None

    if "yesterday" in question_lower:
        days_ago = 1
        relative_label = "Yesterday"
    else:
        match = re.search(
            r"\b(one|a|two|three|four|five|six|seven|eight|nine|ten|\d+)"
            r"\s+days?\s+ago\b",
            question_lower,
        )
        if not match:
            return None
        token = match.group(1)
        days_ago = int(token) if token.isdigit() else _RELATIVE_DAYS[token]
        relative_label = (
            f"{token.title()} day ago"
            if days_ago == 1 and not token.isdigit()
            else f"{days_ago} day ago"
            if days_ago == 1
            else (
                f"{token.title()} days ago"
                if not token.isdigit()
                else f"{days_ago} days ago"
            )
        )

    target_date = (today or date.today()) - timedelta(days=days_ago)
    snapshot = next(
        (
            item for item in performance_history
            if item.get("date") == target_date.isoformat()
        ),
        None,
    )
    formatted_date = target_date.strftime("%B %d, %Y").replace(" 0", " ")
    if snapshot is None or snapshot.get("total_current_value") is None:
        return (
            f"No portfolio-value snapshot is available for "
            f"{relative_label.lower()} ({formatted_date})."
        )
    return (
        f"{relative_label} ({formatted_date}), your portfolio value was "
        f"₹{snapshot['total_current_value']:,.2f}."
    )


def answer_portfolio_question(
    question: str,
    conversation_history=None,
) -> str:
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Question cannot be empty.")

    question = question.strip()
    conversation_history = sanitize_conversation_history(
        conversation_history
    )
    transactions = portfolio.get_transactions()
    opening_positions = portfolio.get_opening_positions()
    company_names = _company_names_by_symbol(
        transactions,
        opening_positions,
    )
    market_data_error = None
    try:
        portfolio_data = portfolio.calculate_portfolio_valuation()
        price_overrides = {
            symbol: position["current_price"]
            for symbol, position in portfolio_data["positions"].items()
            if position["current_price"] is not None
        }
        analytics = portfolio.get_portfolio_analytics_summary(
            price_overrides=price_overrides
        )
    except RuntimeError:
        market_data_error = "Current price data is unavailable."
        calculated_positions = portfolio.calculate_positions(
            transactions,
            opening_positions,
        )
        portfolio_positions = {}
        for symbol, position in calculated_positions.items():
            portfolio_positions[symbol] = {
                "symbol": symbol,
                "company_name": company_names.get(symbol),
                "quantity": position["current_quantity"],
                "average_buy_price": position["average_buy_price"],
                "current_price": None,
                "current_value": None,
                "remaining_cost_basis": position["remaining_cost_basis"],
                "realized_pnl": position["realized_pnl"],
                "unrealized_pnl": None,
                "total_pnl": None,
                "return_percent": None,
                "market_timestamp": None,
                "source": None,
            }
        portfolio_data = {
            "positions": portfolio_positions,
            "total_invested": None,
            "total_current_value": None,
            "total_realized_pnl": None,
            "total_unrealized_pnl": None,
            "total_pnl": None,
            "total_return_percent": None,
        }
        analytics = {
            "allocation": {},
            "concentration": {
                "holding_count": len(portfolio_positions),
                "largest_holding_symbol": None,
                "largest_holding_percent": None,
                "largest_holding_value": None,
            },
            "max_drawdown": portfolio.calculate_max_drawdown(),
        }
    performance_history = portfolio.get_portfolio_performance_history()
    snapshot_rows = portfolio.get_portfolio_snapshots()
    historical_report = historical_analytics.generate_historical_analytics(
        history=performance_history,
        snapshots=snapshot_rows,
        historical_summary=portfolio.get_historical_performance_summary(
            performance_history
        ),
        max_drawdown=(
            portfolio.calculate_max_drawdown(performance_history)
            if len(performance_history) >= 2
            else None
        ),
    )
    goals_report = goals_intelligence.generate_goals_intelligence(
        portfolio_data=portfolio_data,
        history=performance_history,
    )
    attribution_report = performance_attribution.generate_performance_attribution(
        transactions=transactions,
        snapshots=snapshot_rows,
    )
    risk_report = risk_intelligence.generate_risk_intelligence(
        portfolio_data=portfolio_data,
        analytics=analytics,
        performance_history=performance_history,
    )
    quality_report = data_quality.generate_data_quality_report(
        portfolio_data=portfolio_data,
        snapshots=snapshot_rows,
        historical_report=historical_report,
        attribution_report=attribution_report,
        risk_report=risk_report,
        goals_report=goals_report,
        news_by_symbol=None,
        market_data_error=market_data_error,
    )
    quality_answer = _data_quality_question_answer(
        question,
        quality_report,
    )
    if quality_answer is not None:
        return quality_answer
    goals_answer = _goals_question_answer(question, goals_report)
    if goals_answer is not None:
        return goals_answer
    historical_value_answer = _historical_portfolio_value_answer(
        question,
        performance_history,
    )
    if historical_value_answer is not None:
        return historical_value_answer
    historical_summary = portfolio.get_historical_performance_summary()
    portfolio_changes = alerts.get_portfolio_change_report()
    for symbol, position in portfolio_data["positions"].items():
        position["company_name"] = (
            position.get("company_name") or company_names.get(symbol)
        )

    recent_news = {}
    news_errors = []
    if _question_requests_news(question):
        symbols = _news_symbols(
            question,
            portfolio_data["positions"],
            company_names,
        )
        for symbol in symbols:
            try:
                recent_news[symbol] = news.get_company_news(
                    symbol,
                    max_items=5,
                    days=7,
                )
            except Exception:
                logging.getLogger(__name__).exception(
                    "Could not retrieve news for %s",
                    symbol,
                )
                recent_news[symbol] = []
                news_errors.append(f"{symbol}: news retrieval failed.")

    quality_report = data_quality.generate_data_quality_report(
        portfolio_data=portfolio_data,
        snapshots=snapshot_rows,
        historical_report=historical_report,
        attribution_report=attribution_report,
        risk_report=risk_report,
        goals_report=goals_report,
        news_by_symbol=(
            recent_news if _question_requests_news(question) else None
        ),
        news_errors=news_errors,
        market_data_error=market_data_error,
    )

    factual_data = {
        "portfolio": portfolio_data,
        "analytics": analytics,
        "performance_history": performance_history,
        "historical_analytics": historical_report,
        "goals_intelligence": goals_report,
        "historical_performance_summary": historical_summary,
        "portfolio_changes": portfolio_changes,
        "performance_attribution": attribution_report,
        "recent_news": recent_news,
        "risk_intelligence": risk_report,
        "data_quality": quality_report,
    }
    factual_data["portfolio_intelligence"] = (
        intelligence.generate_portfolio_intelligence(
            portfolio_data=portfolio_data,
            analytics=analytics,
            performance_history=performance_history,
            historical_summary=historical_summary,
            portfolio_changes=portfolio_changes,
            news_by_symbol=recent_news,
            news_errors=news_errors,
            market_data_error=market_data_error,
        )
    )

    try:
        answer = ai_analysis.generate_portfolio_answer(
            question,
            factual_data,
            conversation_history=conversation_history,
        )
    except (ConnectionError, TimeoutError):
        return (
            "The AI service is currently unavailable. "
            "Portfolio data was loaded, but a conversational answer "
            "could not be generated."
        )

    if not isinstance(answer, str) or not answer.strip():
        return (
            "The AI service did not return an answer. "
            "Portfolio data was loaded, but a conversational answer "
            "could not be generated."
        )

    return _format_answer_percentages(answer.strip())


def handle_assistant_request(question, conversation_history=None) -> str:
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Question cannot be empty.")

    try:
        command = parse_computer_command(question)
    except ComputerControlError as error:
        return str(error)

    if command is not None:
        try:
            return execute_computer_command(command)
        except ComputerControlError as error:
            return str(error)

    return answer_portfolio_question(
        question,
        conversation_history=conversation_history,
    )
