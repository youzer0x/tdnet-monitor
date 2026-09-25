"""Gmail 送信"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date


def build_subject(target_date: date, subject_suffix: str = "", subject_prefix: str = "") -> str:
    """メール件名を組み立てる（純粋関数）。"""
    return f"{subject_prefix}【適時開示】{target_date:%Y/%m/%d} の開示情報{subject_suffix}"


def send_gmail(html_body: str, target_date: date, subject_suffix: str = "",
               subject_prefix: str = "") -> None:
    """Gmail でHTML形式のメールを送信する"""
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("NOTIFY_TO", sender)

    date_str = target_date.strftime("%Y/%m/%d")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = build_subject(target_date, subject_suffix, subject_prefix)
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
