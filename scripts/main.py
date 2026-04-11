"""TDnet 適時開示モニター メイン処理"""

import os
import sys
from datetime import date, datetime
import jpholiday


def is_market_open(target_date: date) -> bool:
    """
    東証が開場しているかを判定する。
    - 土日 → 休場
    - 祝日 → 休場
    - 12/31, 1/1, 1/2, 1/3 → 休場（年末年始）
    """
    # 土日
    if target_date.weekday() >= 5:
        print(f"  {target_date}: Weekend - market closed")
        return False

    # 祝日
    if jpholiday.is_holiday(target_date):
        name = jpholiday.is_holiday_name(target_date)
        print(f"  {target_date}: Holiday ({name}) - market closed")
        return False

    # 年末年始 (12/31, 1/1, 1/2, 1/3)
    md = (target_date.month, target_date.day)
    if md in [(12, 31), (1, 1), (1, 2), (1, 3)]:
        print(f"  {target_date}: Year-end/New Year - market closed")
        return False

    return True


def main():
    print("=" * 60)
    print("TDnet 適時開示モニター")
    print("=" * 60)

    # 対象日（デフォルト: 当日）
    date_arg = os.environ.get("TARGET_DATE")
    if date_arg:
        target_date = datetime.strptime(date_arg, "%Y-%m-%d").date()
    else:
        target_date = date.today()

    print(f"\nTarget date: {target_date}")

    # 休場日チェック
    if not is_market_open(target_date):
        print("Market is closed. Skipping.")
        return

    print("\n[1/5] Fetching disclosures from TDnet...")
    from tdnet_scraper import fetch_disclosures
    disclosures = fetch_disclosures(target_date)

    if not disclosures:
        print("No disclosures found. Exiting.")
        return

    print(f"\n[2/5] Filtering REIT/ETF...")
    from filter_reit_etf import get_excluded_codes, filter_disclosures
    excluded_codes = get_excluded_codes()
    disclosures = filter_disclosures(disclosures, excluded_codes)

    if not disclosures:
        print("No disclosures after filtering. Exiting.")
        return

    print(f"\n[3/5] Fetching market cap data...")
    from market_cap import fetch_market_caps
    codes = set(d.code for d in disclosures)
    market_caps = fetch_market_caps(codes)

    print(f"\n[4/5] Generating HTML...")
    from html_generator import prepare_display_items, generate_email_html, generate_pages_html

    items = prepare_display_items(disclosures, market_caps)

    # GitHub Pages URL（環境変数から取得）
    github_user = os.environ.get("GITHUB_REPOSITORY_OWNER", "user")
    repo_name = os.environ.get("GITHUB_REPOSITORY", "").split("/")[-1] or "tdnet-monitor"
    pages_url = f"https://{github_user}.github.io/{repo_name}/"

    # GitHub Pages 用 HTML
    pages_html = generate_pages_html(items, target_date)
    docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
    os.makedirs(docs_dir, exist_ok=True)
    pages_path = os.path.join(docs_dir, "index.html")
    with open(pages_path, "w", encoding="utf-8") as f:
        f.write(pages_html)
    print(f"  GitHub Pages HTML written to: {pages_path}")

    # メール用 HTML
    email_html = generate_email_html(items, target_date, pages_url)

    print(f"\n[5/5] Sending Gmail notification...")
    from gmail_sender import send_gmail
    send_gmail(email_html, target_date)

    print(f"\n{'=' * 60}")
    print(f"Done! {len(items)} disclosures processed.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
