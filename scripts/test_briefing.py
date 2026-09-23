from investment_assistant.briefing import (
    build_briefing,
    build_html_email,
)


def main():
    print("Building investment briefing...")

    portfolio, news, analysis = build_briefing()

    html = build_html_email(
        portfolio,
        analysis,
    )

    print("\n" + "=" * 70)
    print("INVESTMENT BRIEFING GENERATED")
    print("=" * 70)

    print(f"\nTotal Invested: ₹{portfolio['total_invested']:,.2f}")
    print(
        f"Current Value: ₹{portfolio['total_current_value']:,.2f}"
    )
    print(
        f"Unrealized P&L: "
        f"₹{portfolio['total_unrealized_pnl']:,.2f}"
    )
    print(
        f"Return: "
        f"{portfolio['total_return_percent']:.2f}%"
    )

    print("\nHTML email length:", len(html))

    print("\nNews collected:")

    for symbol, articles in news.items():
        print(f"  {symbol}: {len(articles)} articles")

    print("\nAI analysis generated: YES")
    print("=" * 70)


if __name__ == "__main__":
    main()