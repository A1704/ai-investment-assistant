from datetime import datetime

from investment_assistant.briefing import (
    build_briefing,
    build_html_email,
)
from investment_assistant.gmail_sender import send_email


def main():
    print("Building daily investment briefing...")

    portfolio, news, analysis = build_briefing()

    html = build_html_email(
        portfolio,
        analysis,
    )

    today = datetime.now().strftime("%d %B %Y")

    subject = f"📊 AI Investment Assistant — {today}"

    print("Sending briefing email...")

    send_email(
        subject,
        html,
    )

    print("Daily investment briefing sent successfully.")


if __name__ == "__main__":
    main()