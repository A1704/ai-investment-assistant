import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv


load_dotenv()


GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")


def send_email(subject, html_content):
    """
    Send an HTML email using Gmail SMTP.
    """

    if not GMAIL_ADDRESS:
        raise RuntimeError("GMAIL_ADDRESS is not configured.")

    if not GMAIL_APP_PASSWORD:
        raise RuntimeError("GMAIL_APP_PASSWORD is not configured.")

    if not RECIPIENT_EMAIL:
        raise RuntimeError("RECIPIENT_EMAIL is not configured.")

    message = MIMEMultipart("alternative")

    message["From"] = GMAIL_ADDRESS
    message["To"] = RECIPIENT_EMAIL
    message["Subject"] = subject

    html_part = MIMEText(
        html_content,
        "html",
        "utf-8",
    )

    message.attach(html_part)

    with smtplib.SMTP_SSL(
        "smtp.gmail.com",
        465,
        timeout=30,
    ) as server:

        server.login(
            GMAIL_ADDRESS,
            GMAIL_APP_PASSWORD,
        )

        server.sendmail(
            GMAIL_ADDRESS,
            RECIPIENT_EMAIL,
            message.as_string(),
        )


if __name__ == "__main__":
    send_email(
        "AI Investment Assistant - Test Email",
        """
        <html>
            <body>
                <h2>AI Investment Assistant</h2>
                <p>Your email system is working successfully.</p>
                <p>This is a test email.</p>
            </body>
        </html>
        """,
    )

    print("Test email sent successfully.")