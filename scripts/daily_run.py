import json
import os

from investment_assistant.briefing import (
    build_briefing,
    build_html_email,
)
from investment_assistant.email import send_email
from investment_assistant.portfolio import (
    add_opening_position,
    get_opening_positions,
)


def load_portfolio_from_environment():
    """
    Load opening portfolio positions from PORTFOLIO_JSON.

    This is used by GitHub Actions because its runner starts
    with a fresh database on every run.

    If PORTFOLIO_JSON is not set, the existing local database
    is used unchanged.
    """

    portfolio_json = os.getenv("PORTFOLIO_JSON")

    if not portfolio_json:
        print("PORTFOLIO_JSON not set. Using existing local portfolio.")
        return

    existing_positions = get_opening_positions()

    if existing_positions:
        print("Portfolio already initialized. No changes needed.")
        return

    try:
        positions = json.loads(portfolio_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "PORTFOLIO_JSON contains invalid JSON."
        ) from exc

    if not isinstance(positions, list) or not positions:
        raise RuntimeError(
            "PORTFOLIO_JSON must contain a non-empty list."
        )

    for position in positions:
        add_opening_position(
            symbol=position["symbol"],
            company_name=position["company_name"],
            quantity=float(position["quantity"]),
            average_cost=float(position["average_cost"]),
            invested_amount=float(position["invested_amount"]),
            purchase_date=None,
        )

    print(
        f"Initialized portfolio with {len(positions)} opening positions."
    )


def main():
    print("Initializing portfolio...")
    load_portfolio_from_environment()

    print("Building investment briefing...")
    portfolio, news, analysis = build_briefing()

    html = build_html_email(portfolio, analysis)

    print("Sending investment briefing email...")
    send_email(
        "📊 AI Investment Briefing",
        html,
    )

    print("Investment briefing email sent successfully.")


if __name__ == "__main__":
    main()
