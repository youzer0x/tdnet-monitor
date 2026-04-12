"""Gmail 送信"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date


def send_gmail(html_body: str, target_date: date, subject_suffix: str = "") -> None:
    """Gmail でHTML形式のメールを送信する"""
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("NOTIFY_TO", sender)

    date_str = target_date.strftime("%Y/%m/%d")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"【適時開示】{date_str} の開示情報{subject_suffix}"
    msg["From"] = sender
    msg["To"] = recipient

    # テキストフォールバック
    text_part = MIMEText(
        f"{date_str} の適時開示情報です。HTML表示に対応したメーラーでご覧ください。",
        "plain",
        "utf-8",
    )
    html_part = MIMEText(html_body, "html", "utf-8")

    msg.attach(text_part)
    msg.attach(html_part)

    print(f"  Sending email to {recipient}...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
        server.login(sender, password)
        server.send_message(msg)

    print("  Email sent successfully.")
