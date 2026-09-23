from datetime import datetime

from investment_assistant.ai_analysis import generate_portfolio_analysis
from investment_assistant.news import get_company_news
from investment_assistant.portfolio import calculate_portfolio_valuation


def build_briefing():
    """
    Build the complete AI investment briefing.

    Returns:
        portfolio: calculated portfolio data
        news: recent news grouped by holding
        analysis: Gemini-generated explanation
    """

    portfolio = calculate_portfolio_valuation()

    news = {}

    for symbol in portfolio["positions"]:
        news[symbol] = get_company_news(
            symbol,
            max_items=5,
            days=7,
        )

    analysis = generate_portfolio_analysis(
        portfolio,
        news,
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

        pnl = data["unrealized_pnl"]

        if pnl >= 0:
            pnl_class = "positive"
        else:
            pnl_class = "negative"

        rows += f"""
        <tr>
            <td>{symbol}</td>
            <td>{data["quantity"]:.2f}</td>
            <td>₹{data["average_buy_price"]:,.2f}</td>
            <td>₹{data["current_price"]:,.2f}</td>
            <td>₹{data["current_value"]:,.2f}</td>
            <td class="{pnl_class}">
                ₹{pnl:,.2f}
            </td>
            <td class="{pnl_class}">
                {data["return_percent"]:.2f}%
            </td>
        </tr>
        """

    analysis_html = analysis.replace("\n", "<br>")

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
                max-width: 900px;
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
            }}

            .card {{
                flex: 1;
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
                        Total Invested
                    </div>

                    <div class="card-value">
                        ₹{portfolio["total_invested"]:,.2f}
                    </div>
                </div>

                <div class="card">
                    <div class="card-title">
                        Current Value
                    </div>

                    <div class="card-value">
                        ₹{portfolio["total_current_value"]:,.2f}
                    </div>
                </div>

                <div class="card">
                    <div class="card-title">
                        Unrealized P&L
                    </div>

                    <div class="card-value">
                        ₹{portfolio["total_unrealized_pnl"]:,.2f}
                    </div>
                </div>

                <div class="card">
                    <div class="card-title">
                        Return
                    </div>

                    <div class="card-value">
                        {portfolio["total_return_percent"]:.2f}%
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
                    <th>P&L</th>
                    <th>Return</th>
                </tr>

                {rows}

            </table>

            <div class="analysis">

                <h2>🤖 AI Analysis</h2>

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