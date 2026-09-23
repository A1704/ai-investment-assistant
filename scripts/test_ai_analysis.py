from investment_assistant.ai_analysis import generate_portfolio_analysis
from investment_assistant.news import get_company_news
from investment_assistant.portfolio import calculate_portfolio_valuation


def main():
    # Calculate current portfolio
    portfolio = calculate_portfolio_valuation()

    # Fetch recent news for each portfolio holding
    news = {}

    for symbol in portfolio["positions"]:
        news[symbol] = get_company_news(
            symbol,
            max_items=5,
            days=7,
        )

    # Send portfolio + news to Gemini
    analysis = generate_portfolio_analysis(
        portfolio,
        news,
    )

    print("\n")
    print("=" * 70)
    print("              AI PORTFOLIO ANALYSIS")
    print("=" * 70)
    print()
    print(analysis)
    print()
    print("=" * 70)


if __name__ == "__main__":
    main()