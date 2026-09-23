from investment_assistant.briefing import (
    build_briefing,
    build_html_email,
)
from investment_assistant.email import send_email


def main():
    print("Building investment briefing...")

    portfolio, news, analysis = build_briefing()

    html = build_html_email(
        portfolio,
        analysis,
    )

    print("Sending investment briefing email...")

    send_email(
        "📊 AI Investment Briefing",
        html,
    )

    print("Investment briefing email sent successfully.")


if __name__ == "__main__":
    main()