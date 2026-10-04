from datetime import datetime
from html import escape
import logging

from investment_assistant.alerts import calculate_portfolio_changes
from investment_assistant.ai_analysis import generate_portfolio_analysis
from investment_assistant.intelligence import generate_portfolio_intelligence
from investment_assistant.risk_intelligence import generate_risk_intelligence
from investment_assistant.performance_attribution import (
    generate_performance_attribution,
)
from investment_assistant.historical_analytics import (
    EXACT_DATE_UNAVAILABLE_MESSAGE,
    generate_historical_analytics,
)
from investment_assistant.goals_intelligence import (
    generate_goals_intelligence,
)
from investment_assistant.data_quality import generate_data_quality_report
from investment_assistant.news import get_company_news
from investment_assistant.portfolio import (
    calculate_portfolio_valuation,
    calculate_positions,
    calculate_max_drawdown,
    get_portfolio_analytics_summary,
    get_opening_positions,
    get_portfolio_snapshots,
    get_portfolio_performance_history,
    get_historical_performance_summary,
    get_transactions,
    save_portfolio_snapshot,
)


def build_briefing(
    price_overrides=None,
    news_overrides=None,
):
    """
    Build the complete AI investment briefing.

    Args:
        price_overrides: Optional dictionary of symbol -> test price.
            Used for isolated testing without live market-data requests.

        news_overrides: Optional dictionary of symbol -> news articles.
            Used for isolated testing without external news requests.

    Returns:
        portfolio: calculated portfolio data
        news: recent news grouped by holding
        analysis: Gemini-generated explanation
    """

    market_data_error = None
    try:
        portfolio = calculate_portfolio_valuation(
            price_overrides=price_overrides
        )
    except RuntimeError as error:
        market_data_error = str(error)
        transactions = get_transactions()
        opening_positions = get_opening_positions()
        calculated_positions = calculate_positions(
            transactions,
            opening_positions,
        )
        company_names = {
            row[1].strip().upper(): row[2]
            for row in opening_positions
        }
        company_names.update({
            row[1].strip().upper(): row[2]
            for row in transactions
        })
        portfolio = {
            "positions": {
                symbol: {
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
                }
                for symbol, position in calculated_positions.items()
            },
            "total_invested": None,
            "total_current_value": None,
            "total_realized_pnl": None,
            "total_unrealized_pnl": None,
            "total_pnl": None,
            "total_return_percent": None,
        }

    if market_data_error is None:
        save_portfolio_snapshot(
            snapshot_date=datetime.now().date().isoformat(),
            total_invested=portfolio["total_invested"],
            total_current_value=portfolio["total_current_value"],
            total_realized_pnl=portfolio["total_realized_pnl"],
            total_unrealized_pnl=portfolio["total_unrealized_pnl"],
            total_pnl=portfolio["total_pnl"],
            total_return_percent=portfolio["total_return_percent"],
            holding_positions=portfolio["positions"],
        )
    news = {}
    news_errors = []

    for symbol in portfolio["positions"]:

        if news_overrides is not None and symbol in news_overrides:
            news[symbol] = news_overrides[symbol]
        else:
            try:
                news[symbol] = get_company_news(
                    symbol,
                    max_items=5,
                    days=7,
                )
            except Exception:
                logging.getLogger(__name__).exception(
                    "Could not retrieve briefing news for %s",
                    symbol,
                )
                news[symbol] = []
                news_errors.append(f"{symbol}: news retrieval failed.")

    snapshots = get_portfolio_snapshots()
    history = get_portfolio_performance_history()
    portfolio["portfolio_changes"] = calculate_portfolio_changes(snapshots)
    portfolio["performance_attribution"] = (
        generate_performance_attribution(
            snapshots=snapshots,
            transactions=get_transactions(),
        )
    )
    portfolio["historical_analytics"] = generate_historical_analytics(
        history=history,
        snapshots=snapshots,
        historical_summary=get_historical_performance_summary(history),
        max_drawdown=calculate_max_drawdown(history),
    )
    portfolio["goals_intelligence"] = generate_goals_intelligence(
        portfolio_data=portfolio,
        history=history,
    )
    intelligence_analytics = None
    if market_data_error is not None:
        intelligence_analytics = {
            "allocation": {},
            "concentration": {
                "holding_count": len(portfolio["positions"]),
                "largest_holding_symbol": None,
                "largest_holding_percent": None,
                "largest_holding_value": None,
            },
            "max_drawdown": calculate_max_drawdown(),
        }
    portfolio["portfolio_intelligence"] = (
        generate_portfolio_intelligence(
            portfolio_data=portfolio,
            analytics=intelligence_analytics,
            portfolio_changes=portfolio["portfolio_changes"],
            news_by_symbol=news,
            news_errors=news_errors,
            market_data_error=market_data_error,
        )
    )
    if intelligence_analytics is None:
        risk_price_overrides = {
            symbol: position["current_price"]
            for symbol, position in portfolio["positions"].items()
            if position.get("current_price") is not None
        }
        intelligence_analytics = get_portfolio_analytics_summary(
            price_overrides=(
                price_overrides
                if price_overrides is not None
                else risk_price_overrides
            ),
        )
    portfolio["risk_intelligence"] = generate_risk_intelligence(
        portfolio_data=portfolio,
        analytics=intelligence_analytics,
    )
    portfolio["data_quality"] = generate_data_quality_report(
        portfolio_data=portfolio,
        snapshots=snapshots,
        historical_report=portfolio["historical_analytics"],
        attribution_report=portfolio["performance_attribution"],
        risk_report=portfolio["risk_intelligence"],
        goals_report=portfolio["goals_intelligence"],
        goals=None,
        news_by_symbol=news,
        news_errors=news_errors,
        market_data_error=market_data_error,
    )
    if market_data_error is None:
        analysis = generate_portfolio_analysis(
            portfolio,
            news,
            intelligence_report={
                **portfolio["portfolio_intelligence"],
                "risk_intelligence": portfolio["risk_intelligence"],
                "performance_attribution": portfolio["performance_attribution"],
                "historical_analytics": portfolio["historical_analytics"],
                "goals_intelligence": portfolio["goals_intelligence"],
                "data_quality": portfolio["data_quality"],
            },
        )
    else:
        analysis = (
            "Gemini explanation is unavailable because current market data "
            "could not be retrieved. No current-value snapshot was recorded."
        )

    return portfolio, news, analysis


def build_html_email(portfolio, analysis):
    """
    Convert the portfolio and Gemini analysis
    into an HTML email.
    """

    today = datetime.now().strftime("%d %B %Y")

    rows = ""

    for symbol, data in portfolio["positions"].items():

        total_pnl = data.get("total_pnl")

        if total_pnl is not None and total_pnl >= 0:
            pnl_class = "positive"
        else:
            pnl_class = "negative"

        rows += f"""
        <tr>
            <td>{symbol}</td>
            <td>{data["quantity"]:.2f}</td>
            <td>{_format_intelligence_value(data.get("average_buy_price"), currency=True)}</td>
            <td>{_format_intelligence_value(data.get("current_price"), currency=True)}</td>
            <td>{_format_intelligence_value(data.get("current_value"), currency=True)}</td>
            <td class="{
                "positive"
                if data.get("realized_pnl") is not None
                and data["realized_pnl"] >= 0
                else "negative"
            }">
                {_format_intelligence_value(data.get("realized_pnl"), currency=True)}
            </td>
            <td class="{
                "positive"
                if data.get("unrealized_pnl") is not None
                and data["unrealized_pnl"] >= 0
                else "negative"
            }">
                {_format_intelligence_value(data.get("unrealized_pnl"), currency=True)}
            </td>
            <td class="{pnl_class}">
                {_format_intelligence_value(total_pnl, currency=True)}
            </td>
        </tr>
        """

    analysis_html = analysis.replace("\n", "<br>")
    changes_html = _build_portfolio_changes_html(
        portfolio.get("portfolio_changes")
    )
    intelligence_html = _build_intelligence_html(
        portfolio.get("portfolio_intelligence")
    )
    risk_html = _build_risk_intelligence_html(
        portfolio.get("risk_intelligence")
    )
    attribution_html = _build_performance_attribution_html(
        portfolio.get("performance_attribution")
    )
    historical_html = _build_historical_analytics_html(
        portfolio.get("historical_analytics")
    )
    goals_html = _build_goals_intelligence_html(
        portfolio.get("goals_intelligence")
    )
    data_quality_html = _build_data_quality_html(
        portfolio.get("data_quality")
    )

    total_pnl_class = (
        "positive"
        if portfolio.get("total_pnl") is not None
        and portfolio["total_pnl"] >= 0
        else "negative"
    )

    realized_pnl_class = (
        "positive"
        if portfolio.get("total_realized_pnl") is not None
        and portfolio["total_realized_pnl"] >= 0
        else "negative"
    )

    unrealized_pnl_class = (
        "positive"
        if portfolio.get("total_unrealized_pnl") is not None
        and portfolio["total_unrealized_pnl"] >= 0
        else "negative"
    )

    html = f"""
    <html>
    <head>
        <style>

            body {{
                font-family: Arial, sans-serif;
                background-color: #f5f7fa;
                color: #222;
                padding: 20px;
            }}

            .container {{
                max-width: 1000px;
                margin: auto;
                background: white;
                padding: 25px;
                border-radius: 10px;
            }}

            h1 {{
                margin-bottom: 5px;
            }}

            .date {{
                color: #666;
                margin-bottom: 25px;
            }}

            .summary {{
                display: flex;
                gap: 15px;
                margin-bottom: 25px;
                flex-wrap: wrap;
            }}

            .card {{
                flex: 1;
                min-width: 150px;
                padding: 15px;
                background-color: #f1f3f5;
                border-radius: 8px;
            }}

            .card-title {{
                font-size: 13px;
                color: #666;
            }}

            .card-value {{
                font-size: 20px;
                font-weight: bold;
                margin-top: 5px;
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 15px;
            }}

            th, td {{
                padding: 10px;
                border-bottom: 1px solid #ddd;
                text-align: left;
            }}

            th {{
                background-color: #f1f3f5;
            }}

            .positive {{
                color: #188038;
                font-weight: bold;
            }}

            .negative {{
                color: #c5221f;
                font-weight: bold;
            }}

            .analysis {{
                margin-top: 30px;
                line-height: 1.6;
            }}

            .disclaimer {{
                margin-top: 30px;
                padding: 15px;
                background-color: #fff4e5;
                border-radius: 8px;
                font-size: 13px;
            }}

        </style>
    </head>

    <body>

        <div class="container">

            <h1>📊 AI Investment Briefing</h1>

            <div class="date">
                {today}
            </div>

            <div class="summary">

                <div class="card">
                    <div class="card-title">
                        Remaining Cost Basis
                    </div>

                    <div class="card-value">
                        {_format_intelligence_value(portfolio.get("total_invested"), currency=True)}
                    </div>
                </div>

                <div class="card">
                    <div class="card-title">
                        Current Value
                    </div>

                    <div class="card-value">
                        {_format_intelligence_value(portfolio.get("total_current_value"), currency=True)}
                    </div>
                </div>

                <div class="card">
                    <div class="card-title">
                        Realized P&L
                    </div>

                    <div class="card-value {realized_pnl_class}">
                        {_format_intelligence_value(portfolio.get("total_realized_pnl"), currency=True)}
                    </div>
                </div>

                <div class="card">
                    <div class="card-title">
                        Unrealized P&L
                    </div>

                    <div class="card-value {unrealized_pnl_class}">
                        {_format_intelligence_value(portfolio.get("total_unrealized_pnl"), currency=True)}
                    </div>
                </div>

                <div class="card">
                    <div class="card-title">
                        Total P&L
                    </div>

                    <div class="card-value {total_pnl_class}">
                        {_format_intelligence_value(portfolio.get("total_pnl"), currency=True)}
                    </div>
                </div>

            </div>

            <h2>Portfolio Holdings</h2>

            <table>

                <tr>
                    <th>Symbol</th>
                    <th>Qty</th>
                    <th>Avg. Price</th>
                    <th>Current Price</th>
                    <th>Value</th>
                    <th>Realized P&L</th>
                    <th>Unrealized P&L</th>
                    <th>Total P&L</th>
                </tr>

                {rows}

            </table>

            <div class="analysis">
                <h2>Portfolio Intelligence</h2>
                {intelligence_html}
            </div>

            <div class="analysis">
                <h2>Portfolio Changes &amp; Alerts</h2>
                {changes_html}
            </div>

            <div class="analysis">
                <h2>Risk &amp; Diversification</h2>
                {risk_html}
            </div>

            <div class="analysis">
                <h2>Performance Attribution</h2>
                {attribution_html}
            </div>

            <div class="analysis">
                <h2>Historical Performance</h2>
                {historical_html}
            </div>

            <div class="analysis">
                <h2>Goals &amp; Benchmarks</h2>
                {goals_html}
            </div>

            <div class="analysis">
                <h2>Data Quality &amp; Reliability</h2>
                {data_quality_html}
            </div>

            <div class="analysis">

                <h2>🤖 AI Analysis / Gemini AI Explanation</h2>

                <p>
                    {analysis_html}
                </p>

            </div>

            <div class="disclaimer">

                <strong>Important:</strong>

                This briefing is for informational purposes only.
                It is not financial advice and does not constitute
                a buy, sell, or hold recommendation.

                Market prices may be delayed or sourced from
                third-party market-data providers.

            </div>

        </div>

    </body>
    </html>
    """

    return html


def _format_intelligence_value(value, currency=False, percent=False):
    if value is None:
        return "Unavailable"
    if currency:
        return f"₹{float(value):,.2f}"
    if percent:
        return f"{float(value):.2f}%"
    return escape(str(value))


def _build_risk_intelligence_html(report):
    if not report:
        return "<p>Risk and diversification data is unavailable.</p>"

    concentration = report.get("portfolio_concentration", {})
    history = report.get("historical_risk", {})
    data_quality = report.get("data_quality", {})
    html = (
        "<ul>"
        f"<li>Number of holdings: "
        f"{escape(str(concentration.get('number_of_holdings', 'Unavailable')))}</li>"
        f"<li>Largest holding: "
        f"{escape(str(concentration.get('largest_holding_symbol') or 'Unavailable'))} "
        f"({_format_intelligence_value(concentration.get('largest_holding_percentage'), percent=True)})</li>"
        f"<li>Concentration index (sum of squared allocation percentages, 0–10,000): "
        f"{_format_intelligence_value(concentration.get('hhi_style_concentration_index'))}</li>"
    )
    if history.get("available"):
        drawdown = history.get("maximum_drawdown") or {}
        html += (
            f"<li>Highest recorded value: "
            f"{_format_intelligence_value(history.get('highest_recorded_value'), currency=True)}</li>"
            f"<li>Lowest recorded value: "
            f"{_format_intelligence_value(history.get('lowest_recorded_value'), currency=True)}</li>"
            f"<li>Maximum drawdown: "
            f"{_format_intelligence_value(drawdown.get('max_drawdown_amount'), currency=True)} "
            f"({_format_intelligence_value(drawdown.get('max_drawdown_percent'), percent=True)})</li>"
        )
    else:
        html += (
            "<li>Historical risk: "
            f"{escape(str(history.get('limitation') or 'Insufficient historical data for this metric.'))}</li>"
        )
    html += "</ul>"

    holdings = report.get("holding_exposure", [])
    if holdings:
        html += (
            "<table><tr><th>Symbol</th><th>Company</th><th>Market Value</th>"
            "<th>Allocation</th><th>Unrealized P&amp;L</th></tr>"
        )
        for holding in holdings:
            html += (
                "<tr>"
                f"<td>{escape(str(holding.get('symbol') or ''))}</td>"
                f"<td>{escape(str(holding.get('company_name') or 'Unavailable'))}</td>"
                f"<td>{_format_intelligence_value(holding.get('market_value'), currency=True)}</td>"
                f"<td>{_format_intelligence_value(holding.get('allocation_percent'), percent=True)}</td>"
                f"<td>{_format_intelligence_value(holding.get('unrealized_pnl'), currency=True)}</td>"
                "</tr>"
            )
        html += "</table>"

    limitations = data_quality.get("limitations", [])
    if limitations:
        html += "<p>Data limitations: " + escape("; ".join(limitations)) + "</p>"
    return html


def _build_performance_attribution_html(report):
    if not report or not report.get("available"):
        reason = (
            report.get("reason")
            if report
            else "Performance attribution is unavailable."
        )
        return f"<p>{escape(str(reason))}</p>"

    movement = report["portfolio_movement"]
    html = (
        f"<p>Previous snapshot: {escape(str(movement['previous_date']))}; "
        f"latest snapshot: {escape(str(movement['latest_date']))}.<br>"
        f"Portfolio value: "
        f"{_format_intelligence_value(movement.get('previous_value'), currency=True)} → "
        f"{_format_intelligence_value(movement.get('latest_value'), currency=True)}"
        f" ({_format_intelligence_value(movement.get('value_change'), currency=True)}"
    )
    if movement.get("value_change_percent") is not None:
        html += f" / {movement['value_change_percent']:+.2f}%"
    html += (
        ").<br>Total P&amp;L change: "
        f"{_format_intelligence_value(movement.get('total_pnl_change'), currency=True)}."
        "</p>"
    )

    holding_report = report.get("holding_attribution", {})
    if holding_report.get("available"):
        summary = report.get("summary", {})
        for key, label in (
            ("largest_positive_contributor", "Largest positive contributor"),
            ("largest_negative_contributor", "Largest negative contributor"),
        ):
            item = summary.get(key)
            if item:
                html += (
                    f"<p>{label} to the observed change: "
                    f"{escape(str(item.get('company_name') or item['symbol']))} "
                    f"({escape(str(item['symbol']))}), "
                    f"{_format_intelligence_value(item.get('market_value_change'), currency=True)}.</p>"
                )
        html += "<h3>Holding Contributions</h3><ul>"
        for holding in holding_report.get("holdings", []):
            html += (
                f"<li>{escape(str(holding['symbol']))}: "
                f"{_format_intelligence_value(holding.get('previous_market_value'), currency=True)} → "
                f"{_format_intelligence_value(holding.get('latest_market_value'), currency=True)}; "
                f"change "
                f"{_format_intelligence_value(holding.get('market_value_change'), currency=True)}; "
                f"contribution to observed change "
                f"{_format_intelligence_value(holding.get('contribution_to_portfolio_change'), currency=True)}.</li>"
            )
        html += "</ul><p>These are observed mathematical contributions, not evidence of causation.</p>"
    else:
        html += (
            "<p>Holding-level attribution unavailable: "
            f"{escape(str(holding_report.get('reason') or 'Detailed holding history is unavailable.'))}</p>"
        )

    price_report = report.get("price_transaction_attribution", {})
    if price_report.get("available"):
        html += (
            "<p>Price/quantity breakdown is an endpoint-based arithmetic "
            "decomposition only; it does not establish causation.</p>"
        )
    else:
        html += (
            "<p>Price/transaction attribution unavailable: "
            f"{escape(str(price_report.get('reason') or 'Required snapshot data is unavailable.'))}</p>"
        )
    transactions = price_report.get("transactions_between_snapshots", [])
    if transactions:
        html += "<h3>Transactions recorded between snapshots</h3><ul>"
        for transaction in transactions:
            html += (
                f"<li>{escape(str(transaction['transaction_date']))}: "
                f"{escape(str(transaction['transaction_type']))} "
                f"{escape(str(transaction['quantity']))} of "
                f"{escape(str(transaction['symbol']))} at "
                f"{_format_intelligence_value(transaction.get('price'), currency=True)}.</li>"
            )
        html += "</ul><p>These records provide timing context and are not asserted as causes of the observed change.</p>"

    limitations = report.get("limitations", [])
    if limitations:
        html += "<p>Limitations: " + escape("; ".join(limitations)) + "</p>"
    return html


def _build_historical_analytics_html(report):
    if not report:
        return "<p>Historical performance data is unavailable.</p>"

    metrics = report.get("trend_metrics", {})
    quality = report.get("data_quality", {})
    drawdown = report.get("drawdown", {})
    date_range = (
        f"{metrics.get('first_snapshot_date')} → "
        f"{metrics.get('latest_snapshot_date')}"
        if metrics.get("first_snapshot_date")
        else "Unavailable"
    )
    html = (
        "<ul>"
        f"<li>Snapshots: {escape(str(metrics.get('snapshot_count')))}</li>"
        f"<li>Date range: {escape(date_range)}</li>"
        f"<li>Latest portfolio value: "
        f"{_format_intelligence_value(metrics.get('latest_portfolio_value'), currency=True)}</li>"
        f"<li>First-to-latest change: "
        f"{_format_intelligence_value(metrics.get('first_to_latest_change'), currency=True)}"
        f" ({_format_intelligence_value(metrics.get('first_to_latest_change_percent'), percent=True)})</li>"
        f"<li>Observed trend: "
        f"{escape(str(metrics.get('trend') or 'Insufficient history'))}</li>"
        f"<li>Highest recorded value: "
        f"{_format_intelligence_value(metrics.get('highest_recorded_value'), currency=True)}</li>"
        f"<li>Lowest recorded value: "
        f"{_format_intelligence_value(metrics.get('lowest_recorded_value'), currency=True)}</li>"
    )
    if drawdown.get("available"):
        html += (
            f"<li>Maximum drawdown: "
            f"{_format_intelligence_value(drawdown.get('max_drawdown_amount'), currency=True)} "
            f"({_format_intelligence_value(drawdown.get('max_drawdown_percent'), percent=True)})</li>"
        )
    else:
        html += (
            f"<li>Maximum drawdown: "
            f"{escape(str(drawdown.get('message') or 'Insufficient historical data for drawdown analysis.'))}</li>"
        )
    html += "</ul>"

    comparisons = report.get("period_comparisons", {})
    for key, label in (
        ("latest_vs_7_days", "Exact 7-day comparison"),
        ("latest_vs_30_days", "Exact 30-day comparison"),
    ):
        comparison = comparisons.get(key, {})
        if comparison.get("available"):
            html += (
                f"<p>{label}: "
                f"{_format_intelligence_value(comparison.get('value_change'), currency=True)} "
                f"({_format_intelligence_value(comparison.get('value_change_percent'), percent=True)})</p>"
            )
        else:
            html += (
                f"<p>{label}: "
                f"{escape(str(comparison.get('message') or EXACT_DATE_UNAVAILABLE_MESSAGE))}</p>"
            )

    limitations = quality.get("limitations", [])
    if limitations:
        html += "<p>Data limitations: " + escape("; ".join(limitations)) + "</p>"
    return html


def _build_goals_intelligence_html(report):
    if not report:
        return "<p>Goals and benchmark data is unavailable.</p>"

    goals = report.get("goals", [])
    benchmarks = report.get("benchmarks", [])
    if not goals:
        html = "<p>No portfolio goals configured.</p>"
    else:
        html = (
            "<table><tr><th>Goal</th><th>Target</th><th>Current</th>"
            "<th>Difference</th><th>Progress</th><th>Target Date</th>"
            "<th>Status</th></tr>"
        )
        for goal in goals:
            currency = goal.get("unit") == "currency"
            percent = goal.get("unit") == "percent"
            difference_percent = (
                goal.get("difference_unit") == "percentage_points"
            )
            difference = goal.get("difference")
            if difference is None:
                difference_text = "Unavailable"
            elif difference_percent:
                difference_text = f"{difference:+.2f} pp"
            else:
                difference_text = _format_intelligence_value(
                    difference,
                    currency=True,
                )
            progress = (
                f"{goal['progress_percent']:.2f}%"
                if goal.get("progress_percent") is not None
                else "Unavailable"
            )
            target_date = (
                f"{escape(str(goal['target_date']))}<br>"
                f"{escape(str(goal['target_date_status']))}"
                if goal.get("target_date")
                else "Not set"
            )
            html += (
                "<tr>"
                f"<td>{escape(str(goal['goal_name']))}</td>"
                f"<td>{_format_intelligence_value(goal.get('target_value'), currency=currency, percent=percent)}</td>"
                f"<td>{_format_intelligence_value(goal.get('current_value'), currency=currency, percent=percent)}</td>"
                f"<td>{difference_text}</td>"
                f"<td>{progress}</td>"
                f"<td>{target_date}</td>"
                f"<td>{escape(str(goal.get('status') or 'Unavailable'))}</td>"
                "</tr>"
            )
        html += "</table>"

    if not benchmarks:
        html += "<p>No portfolio benchmarks configured.</p>"
        return html

    html += (
        "<table><tr><th>Benchmark</th><th>Period</th>"
        "<th>Portfolio Return</th><th>Benchmark Return</th>"
        "<th>Difference</th></tr>"
    )
    for benchmark in benchmarks:
        comparison = benchmark.get("comparison", {})
        if not comparison.get("available"):
            html += (
                "<tr>"
                f"<td>{escape(str(benchmark.get('benchmark_name', '')))}</td>"
                "<td colspan='4'>Benchmark comparison unavailable.</td>"
                "</tr>"
            )
            continue
        html += (
            "<tr>"
            f"<td>{escape(str(benchmark.get('benchmark_name', '')))}</td>"
            f"<td>{escape(str(comparison['period_start_date']))} to "
            f"{escape(str(comparison['period_end_date']))}</td>"
            f"<td>{comparison['portfolio_return_percent']:.2f}%</td>"
            f"<td>{comparison['benchmark_return_percent']:.2f}%</td>"
            f"<td>{comparison['difference_percentage_points']:+.2f} pp</td>"
            "</tr>"
        )
    if any(
        benchmark.get("comparison", {}).get("available")
        for benchmark in benchmarks
    ):
        html += (
            "</table><p>Portfolio return is the value change between exact "
            "matching snapshots; transaction cash flows are not adjusted.</p>"
        )
        return html
    return html + "</table>"


def _build_data_quality_html(report):
    if not report:
        return "<p>Data quality report is unavailable.</p>"

    critical = [
        item for item in report.get("issues", [])
        if item.get("severity") == "CRITICAL"
    ]
    warnings = [
        item for item in report.get("issues", [])
        if item.get("severity") == "WARNING"
    ]
    history = report.get("snapshot_history", {})
    market = report.get("market_data", {})
    limitations = []
    for item in critical + warnings:
        message = item.get("message")
        if message and message not in limitations:
            limitations.append(message)
    limitations.extend(
        item for item in history.get("details", [])
        if item not in limitations
    )
    for benchmark in report.get("benchmarks", {}).get("items", []):
        if (
            benchmark.get("active")
            and benchmark.get("comparison_status") != "AVAILABLE"
        ):
            name = benchmark.get("name") or "Configured benchmark"
            message = (
                f"{name}: "
                f"{benchmark.get('comparison_message') or 'Benchmark comparison unavailable.'}"
            )
            if message not in limitations:
                limitations.append(message)

    html = (
        f"<p><strong>Data status: "
        f"{escape(str(report.get('overall_status', 'UNKNOWN')))}</strong></p>"
    )
    freshness_counts = market.get("freshness_counts", {})
    html += (
        "<p>Market-price freshness: "
        f"{freshness_counts.get('FRESH', 0)} fresh, "
        f"{freshness_counts.get('AGING', 0)} aging, "
        f"{freshness_counts.get('STALE', 0)} stale, "
        f"{freshness_counts.get('UNKNOWN', 0)} unknown. "
        f"{escape(str(market.get('source_limitation') or ''))}</p>"
    )
    if limitations:
        html += "<ul>"
        for message in limitations:
            html += f"<li>{escape(str(message))}</li>"
        html += "</ul>"
    else:
        html += "<p>No critical or warning data-quality issues were reported.</p>"
    return html


def _build_intelligence_html(report):
    if not report:
        return "<p>Portfolio intelligence is unavailable.</p>"

    overview = report.get("portfolio_overview", {})
    performance = report.get("performance", {})
    concentration = report.get("concentration", {})
    html = (
        "<h3>Portfolio Overview</h3><ul>"
        f"<li>Current cost basis: "
        f"{_format_intelligence_value(overview.get('current_cost_basis'), currency=True)}</li>"
        f"<li>Current portfolio value: "
        f"{_format_intelligence_value(overview.get('current_portfolio_value'), currency=True)}</li>"
        f"<li>Realized P&amp;L: "
        f"{_format_intelligence_value(overview.get('realized_pnl'), currency=True)}</li>"
        f"<li>Unrealized P&amp;L: "
        f"{_format_intelligence_value(overview.get('unrealized_pnl'), currency=True)}</li>"
        f"<li>Total P&amp;L: "
        f"{_format_intelligence_value(overview.get('total_pnl'), currency=True)}</li>"
        f"<li>Unrealized return: "
        f"{_format_intelligence_value(overview.get('unrealized_return_percent'), percent=True)}</li>"
        f"<li>Holdings: {escape(str(overview.get('holding_count', 'Unavailable')))}</li>"
        "</ul>"
    )

    if performance.get("available"):
        html += (
            "<h3>Recent Performance</h3><p>"
            f"Previous snapshot: {escape(str(performance.get('previous_snapshot_date')))}; "
            f"latest snapshot: {escape(str(performance.get('latest_snapshot_date')))}."
            f"<br>Portfolio value change: "
            f"{_format_intelligence_value(performance.get('portfolio_value_change'), currency=True)} "
            f"({_format_intelligence_value(performance.get('portfolio_value_change_percent'), percent=True)})."
            f"<br>Total P&amp;L change: "
            f"{_format_intelligence_value(performance.get('total_pnl_change'), currency=True)}."
            f"<br>Maximum drawdown: "
            f"{_format_intelligence_value(performance.get('max_drawdown', {}).get('max_drawdown_amount'), currency=True)}"
            "</p>"
        )

    holding_changes = report.get("holding_level_changes", {})
    if holding_changes.get("available"):
        html += (
            "<h3>Holding-Level Changes</h3><p>Comparing detailed snapshots: "
            f"{escape(str(holding_changes.get('previous_date')))} → "
            f"{escape(str(holding_changes.get('latest_date')))}</p><ul>"
        )
        for holding in holding_changes.get("items", []):
            symbol = escape(str(holding.get("symbol", "")))
            company = escape(str(holding.get("company_name", symbol)))
            if holding.get("status") in ("added", "removed"):
                html += (
                    f"<li>{company} ({symbol}): "
                    f"{escape(str(holding['status']))}</li>"
                )
            else:
                html += (
                    f"<li>{company} ({symbol}): value change "
                    f"{_format_intelligence_value(holding.get('market_value_change'), currency=True)}; "
                    f"unrealized P&amp;L change "
                    f"{_format_intelligence_value(holding.get('unrealized_pnl_change'), currency=True)}; "
                    f"total P&amp;L change "
                    f"{_format_intelligence_value(holding.get('total_pnl_change'), currency=True)}; "
                    f"allocation change "
                    f"{_format_intelligence_value(holding.get('allocation_change_percentage_points'))} pp."
                    "</li>"
                )
        html += "</ul>"
    elif holding_changes.get("limitation"):
        html += (
            "<h3>Holding-Level Changes</h3><p>"
            f"{escape(str(holding_changes['limitation']))}</p>"
        )

    contributors = report.get("contributors")
    if contributors and contributors.get("available"):
        movement_lines = []
        for key, label in (
            ("largest_positive", "Largest positive contributor"),
            ("largest_negative", "Largest negative contributor"),
        ):
            item = contributors.get(key)
            if item:
                movement_lines.append(
                    f"<li>{label} to the latest portfolio-value change: "
                    f"{escape(str(item['company_name']))} "
                    f"({escape(str(item['symbol']))}), "
                    f"{_format_intelligence_value(item['market_value_change'], currency=True)}</li>"
                )
        if movement_lines:
            html += (
                "<h3>Largest Portfolio Movements</h3><ul>"
                + "".join(movement_lines)
                + "</ul><p>These are snapshot-based movement contributions, "
                "not evidence of causation.</p>"
            )

    html += (
        "<h3>Concentration</h3><p>"
        f"{escape(str(concentration.get('observation', 'Unavailable')))}"
        "</p><ul>"
    )
    for item in concentration.get("allocations", []):
        html += (
            f"<li>{escape(str(item['symbol']))}: "
            f"{_format_intelligence_value(item.get('allocation_percent'), percent=True)} "
            f"of portfolio value</li>"
        )
    html += "</ul>"

    for title, key, value_key in (
        ("Alerts", "alerts", "description"),
        ("Things to Monitor", "things_to_monitor", "description"),
    ):
        items = report.get(key, [])
        if items:
            html += f"<h3>{title}</h3><ul>"
            for item in items:
                html += (
                    f"<li>{escape(str(item.get(value_key, '')))}</li>"
                )
            html += "</ul>"

    news_report = report.get("relevant_news", {})
    if news_report.get("items"):
        html += "<h3>Relevant News Context</h3><ul>"
        for item in news_report["items"]:
            headline = escape(str(item.get("headline", "")))
            symbol = escape(str(item.get("symbol", "")))
            source = escape(str(item.get("source") or "Source unavailable"))
            published = escape(str(item.get("publication_date") or ""))
            url = item.get("url")
            headline_html = (
                f'<a href="{escape(str(url), quote=True)}">{headline}</a>'
                if url else headline
            )
            html += (
                f"<li>{symbol}: {headline_html} — {source}"
                f"{', ' + published if published else ''}</li>"
            )
        html += "</ul>"
    elif news_report.get("message"):
        html += (
            "<h3>Relevant News</h3><p>"
            f"{escape(str(news_report['message']))}</p>"
        )

    limitations = report.get("data_limitations", [])
    if limitations:
        html += "<h3>Data Availability</h3><ul>"
        for item in limitations:
            html += f"<li>{escape(str(item))}</li>"
        html += "</ul>"
    return html


def _build_portfolio_changes_html(report):
    if not report or not report.get("available"):
        message = (
            report.get("message")
            if report
            else "Not enough historical snapshots to calculate portfolio changes yet."
        )
        return f"<p>{message}</p>"

    portfolio_change = report["portfolio_value"]
    pnl_change = report["total_pnl"]
    html = (
        f"<p>Latest snapshot: {escape(str(report['latest_date']))} · "
        f"Previous snapshot: {escape(str(report['previous_date']))}</p>"
        f"<p>Portfolio value change: ₹{portfolio_change['change']:,.2f}"
    )
    if portfolio_change["change_percent"] is not None:
        html += f" ({portfolio_change['change_percent']:+.2f}%)"
    html += (
        f"<br>Total P&amp;L change: ₹{pnl_change['change']:,.2f}</p>"
    )

    if report["holding_comparison_available"]:
        html += (
            "<h3>Holding-level changes</h3><p>Comparing detailed snapshots: "
            f"{escape(str(report.get('holding_comparison_previous_date')))} → "
            f"{escape(str(report.get('holding_comparison_latest_date')))}</p><ul>"
        )
        for holding in report["holding_changes"]:
            symbol = escape(str(holding["symbol"]))
            company_name = escape(str(holding["company_name"]))
            if holding["status"] == "added":
                html += (
                    f"<li><strong>{company_name} ({symbol})</strong>: "
                    "added holding.</li>"
                )
            elif holding["status"] == "removed":
                html += (
                    f"<li><strong>{company_name} ({symbol})</strong>: "
                    "removed holding.</li>"
                )
            else:
                html += f"<li><strong>{company_name} ({symbol})</strong><br>"
                if holding["value_change"] is not None:
                    html += (
                        f"Value: {_format_intelligence_value(holding['previous_value'], currency=True)} → "
                        f"{_format_intelligence_value(holding['current_value'], currency=True)} "
                        f"({_format_intelligence_value(holding['value_change'], currency=True)}"
                    )
                    if holding["value_change_percent"] is not None:
                        html += (
                            f" / {holding['value_change_percent']:+.2f}%"
                        )
                    html += ")"
                else:
                    html += "Value change: unavailable in older snapshot data"
                for label, start, end, delta in (
                    (
                        "Unrealized P&amp;L",
                        "previous_unrealized_pnl",
                        "current_unrealized_pnl",
                        "unrealized_pnl_change",
                    ),
                    (
                        "Total P&amp;L",
                        "previous_total_pnl",
                        "current_total_pnl",
                        "total_pnl_change",
                    ),
                    (
                        "Allocation",
                        "previous_allocation_percent",
                        "current_allocation_percent",
                        "allocation_change_percentage_points",
                    ),
                ):
                    if all(holding.get(key) is not None for key in (start, end, delta)):
                        is_allocation = label == "Allocation"
                        suffix = " pp" if is_allocation else ""
                        unit = "%" if is_allocation else ""
                        html += (
                            f"<br>{label}: "
                            f"{holding[start]:,.2f}{unit} → "
                            f"{holding[end]:,.2f}{unit} "
                            f"({holding[delta]:+,.2f}{suffix})"
                        )
                    else:
                        html += f"<br>{label}: unavailable in older snapshot data"
                if holding.get("quantity_change") is not None:
                    html += (
                        f"<br>Quantity: {holding['previous_quantity']} → "
                        f"{holding['current_quantity']} "
                        f"({holding['quantity_change']:+,.2f})"
                    )
                else:
                    html += "<br>Quantity change: unavailable in older snapshot data"
                if holding["current_price_change"] is not None:
                    html += (
                        f"<br>Current price: "
                        f"₹{holding['previous_current_price']:,.2f} → "
                        f"₹{holding['current_current_price']:,.2f} "
                        f"({holding['current_price_change']:+,.2f})"
                    )
                html += "</li>"
        html += "</ul>"
        if report["concentration_changes"]:
            html += "<h3>Concentration changes</h3><ul>"
            for change in report["concentration_changes"]:
                html += (
                    f"<li>{escape(str(change['symbol']))}: allocation changed by "
                    f"{change['change_percentage_points']:+.2f} percentage "
                    "points</li>"
                )
            html += "</ul>"
    else:
        html += f"<p>{report['holding_comparison_message']}</p>"

    if report["alerts"]:
        html += "<h3>Generated alerts</h3><ul>"
        for alert in report["alerts"]:
            html += (
                f"<li><strong>{alert['severity']}</strong>: "
                f"{escape(alert['message'])}</li>"
            )
        html += "</ul>"
    else:
        html += "<p>No significant portfolio changes detected.</p>"
    return html