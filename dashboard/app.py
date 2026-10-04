import sqlite3
import os
import secrets
import math
from collections import OrderedDict
from threading import RLock

from flask import (
    Flask,
    flash,
    get_flashed_messages,
    render_template,
    request,
    redirect,
    url_for,
    session,
    has_request_context,
)

from investment_assistant.alerts import get_portfolio_change_report
from investment_assistant.intelligence import generate_portfolio_intelligence
from investment_assistant.risk_intelligence import generate_risk_intelligence
from investment_assistant.performance_attribution import (
    generate_performance_attribution,
)
from investment_assistant.historical_analytics import (
    generate_historical_analytics,
)
from investment_assistant.goals_intelligence import (
    add_benchmark_observation,
    create_portfolio_benchmark,
    create_portfolio_goal,
    generate_goals_intelligence,
)
from investment_assistant.data_quality import generate_data_quality_report
from investment_assistant.portfolio import (
    calculate_max_drawdown,
    calculate_positions,
    get_dashboard_data,
    get_historical_performance_summary,
    get_portfolio_snapshots,
    get_opening_positions,
    get_portfolio_performance_history,
    get_portfolio_alerts,
    get_transactions,
)
from investment_assistant.ai_analysis import generate_portfolio_analysis
from investment_assistant.portfolio import add_transaction
from investment_assistant.news import get_company_news
from investment_assistant.computer_control import (
    ComputerControlError,
    parse_computer_command,
)
from investment_assistant.assistant import (
    MAX_CONVERSATION_EXCHANGES,
    handle_assistant_request,
    sanitize_conversation_history,
)


app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)


def _format_inr(value):
    if isinstance(value, bool):
        return "Unavailable"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "Unavailable"
    if not math.isfinite(amount):
        return "Unavailable"

    formatted = f"{abs(amount):.2f}"
    whole, fraction = formatted.split(".")
    if len(whole) > 3:
        trailing = whole[-3:]
        leading = whole[:-3]
        groups = []
        while leading:
            groups.insert(0, leading[-2:])
            leading = leading[:-2]
        whole = ",".join(groups + [trailing])
    sign = "-" if amount < 0 else ""
    return f"{sign}₹{whole}.{fraction}"


def _format_quantity(value):
    if isinstance(value, bool):
        return "Unavailable"
    try:
        quantity = float(value)
    except (TypeError, ValueError):
        return "Unavailable"
    if not math.isfinite(quantity):
        return "Unavailable"
    return f"{quantity:.4f}".rstrip("0").rstrip(".")


app.jinja_env.filters["inr"] = _format_inr
app.jinja_env.filters["quantity"] = _format_quantity

_ASSISTANT_CONVERSATIONS = OrderedDict()
_ASSISTANT_CONVERSATIONS_LOCK = RLock()
_MAX_ACTIVE_ASSISTANT_SESSIONS = 256


@app.route("/")
def dashboard():
    return _render_dashboard()


def _get_assistant_session_id():
    session_id = session.get("assistant_session_id")
    if not isinstance(session_id, str):
        session_id = secrets.token_urlsafe(32)
        session["assistant_session_id"] = session_id
    return session_id


def _get_assistant_history(session_id):
    with _ASSISTANT_CONVERSATIONS_LOCK:
        history = _ASSISTANT_CONVERSATIONS.get(session_id, [])
        if session_id in _ASSISTANT_CONVERSATIONS:
            _ASSISTANT_CONVERSATIONS.move_to_end(session_id)
        return sanitize_conversation_history(history)


def _save_assistant_history(session_id, history):
    sanitized_history = sanitize_conversation_history(history)[
        -MAX_CONVERSATION_EXCHANGES:
    ]

    with _ASSISTANT_CONVERSATIONS_LOCK:
        _ASSISTANT_CONVERSATIONS[session_id] = sanitized_history
        _ASSISTANT_CONVERSATIONS.move_to_end(session_id)

        while len(_ASSISTANT_CONVERSATIONS) > _MAX_ACTIVE_ASSISTANT_SESSIONS:
            _ASSISTANT_CONVERSATIONS.popitem(last=False)


def _render_dashboard(
    assistant_question="",
    assistant_answer="",
    assistant_action_result="",
    skip_ai_analysis=False,
):
    market_data_error = None
    try:
        dashboard_data = get_dashboard_data()
    except RuntimeError:
        app.logger.warning("Current market-data retrieval failed.")
        market_data_error = "Current price data is unavailable."
        transaction_rows = get_transactions()
        opening_positions = get_opening_positions()
        company_names = {
            row[1].strip().upper(): row[2]
            for row in opening_positions
        }
        company_names.update({
            row[1].strip().upper(): row[2]
            for row in transaction_rows
        })
        calculated_positions = calculate_positions(
            transaction_rows,
            opening_positions,
        )
        positions = {
            symbol: {
                "symbol": symbol,
                "company_name": company_names.get(symbol),
                "quantity": position["current_quantity"],
                "average_buy_price": position["average_buy_price"],
                "current_price": None,
                "current_value": None,
                "realized_pnl": position["realized_pnl"],
                "unrealized_pnl": None,
                "total_pnl": None,
                "remaining_cost_basis": position["remaining_cost_basis"],
                "return_percent": None,
            }
            for symbol, position in calculated_positions.items()
        }
        dashboard_data = {
            "portfolio": {
                "positions": positions,
                "total_invested": None,
                "total_current_value": None,
                "total_realized_pnl": None,
                "total_unrealized_pnl": None,
                "total_pnl": None,
                "total_return_percent": None,
            },
            "analytics": {
                "allocation": {},
                "concentration": {
                    "holding_count": len(positions),
                    "largest_holding_symbol": None,
                    "largest_holding_percent": None,
                    "largest_holding_value": None,
                },
                "max_drawdown": calculate_max_drawdown(),
            },
            "historical": {
                **get_historical_performance_summary(),
                "history": get_portfolio_performance_history(),
            },
        }

    conn = sqlite3.connect("data/investment_assistant.db")
    conn.row_factory = sqlite3.Row

    transactions = conn.execute("""
        SELECT
            symbol,
            company_name,
            transaction_type,
            quantity,
            price,
            transaction_date
        FROM transactions
        ORDER BY transaction_date DESC, id DESC
    """).fetchall()

    conn.close()

    try:
        alerts = get_portfolio_alerts()
    except RuntimeError:
        alerts = [{
            "type": "unavailable",
            "symbol": "",
            "message": (
                "Portfolio alerts are unavailable because current price "
                "data could not be retrieved."
            ),
        }]
    portfolio_changes = get_portfolio_change_report()

    news = {}
    news_errors = []

    for symbol in dashboard_data["portfolio"]["positions"]:
        try:
            news[symbol] = get_company_news(
                symbol,
                max_items=5,
                days=7,
            )
        except Exception:
            app.logger.exception("Could not retrieve news for %s", symbol)
            news[symbol] = []
            news_errors.append(f"{symbol}: news retrieval failed.")

    portfolio_intelligence = generate_portfolio_intelligence(
        portfolio_data=dashboard_data["portfolio"],
        analytics=dashboard_data.get("analytics") or {
            "allocation": {},
            "concentration": {},
            "max_drawdown": {},
        },
        performance_history=(
            dashboard_data.get("historical", {}).get("history", [])
        ),
        historical_summary=dashboard_data.get("historical", {}),
        portfolio_changes=portfolio_changes,
        news_by_symbol=news,
        news_errors=news_errors,
        market_data_error=market_data_error,
    )
    risk_report = generate_risk_intelligence(
        portfolio_data=dashboard_data["portfolio"],
        analytics=dashboard_data.get("analytics") or {
            "allocation": {},
            "concentration": {
                "holding_count": len(dashboard_data["portfolio"]["positions"]),
            },
        },
        performance_history=(
            dashboard_data.get("historical", {}).get("history", [])
        ),
        historical_summary=dashboard_data.get("historical", {}),
    )
    snapshots = get_portfolio_snapshots()
    attribution_report = generate_performance_attribution(
        snapshots=snapshots,
        transactions=get_transactions(),
    )
    history = dashboard_data.get("historical", {}).get("history", [])
    historical_report = generate_historical_analytics(
        history=history,
        snapshots=snapshots,
        historical_summary=dashboard_data.get("historical", {}),
        max_drawdown=(
            dashboard_data.get("analytics", {}).get("max_drawdown")
            if dashboard_data.get("analytics")
            else None
        ),
    )
    goals_report = generate_goals_intelligence(
        portfolio_data=dashboard_data["portfolio"],
        history=history,
    )
    data_quality_report = generate_data_quality_report(
        portfolio_data=dashboard_data["portfolio"],
        snapshots=snapshots,
        historical_report=historical_report,
        attribution_report=attribution_report,
        risk_report=risk_report,
        goals_report=goals_report,
        news_by_symbol=news,
        news_errors=news_errors,
        market_data_error=market_data_error,
    )
    if skip_ai_analysis:
        ai_analysis = (
            "AI analysis is not refreshed while answering a question. "
            "Your portfolio data and other dashboard information remain available."
        )
    elif market_data_error is None:
        ai_analysis = generate_portfolio_analysis(
            dashboard_data["portfolio"],
            news,
            intelligence_report={
                **portfolio_intelligence,
                "risk_intelligence": risk_report,
                "performance_attribution": attribution_report,
                "historical_analytics": historical_report,
                "goals_intelligence": goals_report,
                "data_quality": data_quality_report,
            },
        )
    else:
        ai_analysis = (
            "AI analysis is temporarily unavailable because current price "
            "data could not be retrieved. Other dashboard information remains available."
        )

    return render_template(
        "dashboard.html",
        data=dashboard_data,
        news=news,
        ai_analysis=ai_analysis,
        alerts=alerts,
        portfolio_changes=portfolio_changes,
        portfolio_intelligence=portfolio_intelligence,
        risk_intelligence=risk_report,
        performance_attribution=attribution_report,
        historical_analytics=historical_report,
        goals_intelligence=goals_report,
        data_quality_report=data_quality_report,
        transactions=transactions,
        flashed_messages=(
            get_flashed_messages(with_categories=True)
            if has_request_context()
            else []
        ),
        assistant_question=assistant_question,
        assistant_answer=assistant_answer,
        assistant_action_result=assistant_action_result,
    )


@app.route("/assistant", methods=["POST"])
def assistant_route():
    question = request.form.get("question", "").strip()

    if not question:
        return _render_dashboard(
            assistant_question=question,
            assistant_answer="Please enter a question for the AI Portfolio Assistant.",
            skip_ai_analysis=True,
        )

    try:
        computer_command = parse_computer_command(question)
    except ComputerControlError:
        computer_command = None

    session_id = _get_assistant_session_id()
    conversation_history = _get_assistant_history(session_id)

    try:
        answer = handle_assistant_request(
            question,
            conversation_history=conversation_history,
        )
    except ValueError:
        app.logger.info("Portfolio assistant rejected a request.")
        answer = (
            "The assistant could not use the available data to answer that. "
            "Your dashboard information is still available."
        )
    except Exception:
        app.logger.error("Portfolio assistant request failed.")
        answer = (
            "The assistant could not answer right now. "
            "Please try again later."
        )

    updated_history = conversation_history + [
        {
            "user_question": question,
            "assistant_answer": answer,
        }
    ]
    _save_assistant_history(session_id, updated_history)

    return _render_dashboard(
        assistant_question=question,
        assistant_answer="" if computer_command is not None else answer,
        assistant_action_result=(
            answer if computer_command is not None else ""
        ),
        skip_ai_analysis=True,
    )


@app.route("/transaction", methods=["POST"])
def add_transaction_route():

    symbol = request.form.get("symbol", "").strip().upper()
    company_name = request.form.get("company_name", "").strip()
    transaction_type = request.form.get("transaction_type", "").strip().upper()
    quantity = request.form.get("quantity", "").strip()
    price = request.form.get("price", "").strip()
    transaction_date = request.form.get("transaction_date", "").strip()

    try:
        add_transaction(
            symbol=symbol,
            company_name=company_name,
            transaction_type=transaction_type,
            quantity=float(quantity),
            price=float(price),
            transaction_date=transaction_date,
        )
    except (TypeError, ValueError):
        flash(
            "Transaction details were not valid. Please review the fields.",
            "error",
        )
    except Exception:
        app.logger.error("Transaction could not be recorded.")
        flash(
            "The transaction could not be recorded. Please try again.",
            "error",
        )
    else:
        flash("Transaction recorded.", "success")

    return redirect(url_for("dashboard"))


@app.route("/portfolio-goal", methods=["POST"])
def add_portfolio_goal_route():
    try:
        target_value = float(request.form.get("target_value", "").strip())
        create_portfolio_goal(
            goal_name=request.form.get("goal_name", ""),
            target_type=request.form.get("target_type", ""),
            target_value=target_value,
            target_date=request.form.get("target_date", "").strip() or None,
        )
    except ValueError as error:
        flash(str(error), "error")
    else:
        flash("Portfolio goal added.", "success")
    return redirect(url_for("dashboard"))


@app.route("/portfolio-benchmark", methods=["POST"])
def add_portfolio_benchmark_route():
    try:
        create_portfolio_benchmark(
            benchmark_name=request.form.get("benchmark_name", ""),
            benchmark_symbol=(
                request.form.get("benchmark_symbol", "").strip() or None
            ),
            benchmark_type=request.form.get("benchmark_type", ""),
        )
    except ValueError as error:
        flash(str(error), "error")
    else:
        flash("Portfolio benchmark added. No benchmark data was fetched.", "success")
    return redirect(url_for("dashboard"))


@app.route("/portfolio-benchmark-observation", methods=["POST"])
def add_portfolio_benchmark_observation_route():
    try:
        benchmark_id = int(request.form.get("benchmark_id", "").strip())
        value = float(request.form.get("value", "").strip())
        add_benchmark_observation(
            benchmark_id=benchmark_id,
            observation_date=request.form.get(
                "observation_date",
                "",
            ).strip(),
            value=value,
        )
    except ValueError as error:
        flash(str(error), "error")
    else:
        flash("User-provided benchmark observation added.", "success")
    return redirect(url_for("dashboard"))

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True,
    )