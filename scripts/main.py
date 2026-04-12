"""TDnet 適時開示モニター メイン処理"""

import os
import sys
import json
import glob
from datetime import date, datetime, timedelta
import jpholiday


def is_market_open(target_date: date) -> bool:
    """
    東証が開場しているかを判定する。
    - 土日 → 休場
    - 祝日 → 休場
    - 12/31, 1/1, 1/2, 1/3 → 休場（年末年始）
    """
    if target_date.weekday() >= 5:
        print(f"  {target_date}: Weekend - market closed")
        return False
    if jpholiday.is_holiday(target_date):
        name = jpholiday.is_holiday_name(target_date)
        print(f"  {target_date}: Holiday ({name}) - market closed")
        return False
    md = (target_date.month, target_date.day)
    if md in [(12, 31), (1, 1), (1, 2), (1, 3)]:
        print(f"  {target_date}: Year-end/New Year - market closed")
        return False
    return True


def save_daily_json(items: list, target_date: date, docs_dir: str) -> None:
    """当日の開示データを JSON として保存する"""
    data_dir = os.path.join(docs_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    records = []
    for item in items:
        records.append({
            "code": item.code,
            "company_name": item.company_name,
            "market_cap": item.market_cap,
            "time": item.time,
            "title": item.title,
            "pdf_url": item.pdf_url,
        })

    daily_data = {
        "date": target_date.isoformat(),
        "company_count": len(set(item.code for item in items)),
        "total_count": len(items),
        "items": records,
    }

    json_path = os.path.join(data_dir, f"{target_date.isoformat()}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(daily_data, f, ensure_ascii=False, indent=2)
    print(f"  Daily JSON saved: {json_path}")


def cleanup_old_data(docs_dir: str, keep_days: int = 14) -> None:
    """keep_days 日より古い JSON を削除する"""
    data_dir = os.path.join(docs_dir, "data")
    if not os.path.exists(data_dir):
        return

    cutoff = date.today() - timedelta(days=keep_days)
    removed = 0

    for json_file in glob.glob(os.path.join(data_dir, "*.json")):
        fname = os.path.basename(json_file)
        if fname == "manifest.json":
            continue
        try:
            file_date = date.fromisoformat(fname.replace(".json", ""))
            if file_date < cutoff:
                os.remove(json_file)
                removed += 1
        except ValueError:
            pass

    if removed:
        print(f"  Cleaned up {removed} old JSON files (older than {cutoff})")


def update_manifest(docs_dir: str) -> list[str]:
    """利用可能な日付一覧を manifest.json に書き出す"""
    data_dir = os.path.join(docs_dir, "data")
    dates = []

    for json_file in sorted(glob.glob(os.path.join(data_dir, "*.json")), reverse=True):
        fname = os.path.basename(json_file)
        if fname == "manifest.json":
            continue
        try:
            d = date.fromisoformat(fname.replace(".json", ""))
            dates.append(d.isoformat())
        except ValueError:
            pass

    manifest_path = os.path.join(data_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({"dates": dates}, f, ensure_ascii=False)
    print(f"  Manifest updated: {len(dates)} dates available")
    return dates


def main():
    print("=" * 60)
    print("TDnet 適時開示モニター")
    print("=" * 60)

    # 対象日
    date_arg = os.environ.get("TARGET_DATE")
    if date_arg:
        target_date = datetime.strptime(date_arg, "%Y-%m-%d").date()
    else:
        target_date = date.today()

    print(f"\nTarget date: {target_date}")

    if not is_market_open(target_date):
        print("Market is closed. Skipping.")
        return

    print("\n[1/6] Fetching disclosures from TDnet...")
    from tdnet_scraper import fetch_disclosures
    disclosures = fetch_disclosures(target_date)

    if not disclosures:
        print("No disclosures found. Exiting.")
        return

    print(f"\n[2/6] Filtering REIT/ETF...")
    from filter_reit_etf import get_excluded_codes, filter_disclosures
    excluded_codes = get_excluded_codes()
    disclosures = filter_disclosures(disclosures, excluded_codes)

    if not disclosures:
        print("No disclosures after filtering. Exiting.")
        return

    print(f"\n[3/6] Fetching market cap data...")
    from market_cap import fetch_market_caps
    codes = set(d.code for d in disclosures)
    market_caps = fetch_market_caps(codes)

    print(f"\n[4/6] Saving daily data...")
    from html_generator import prepare_display_items, generate_email_html, generate_pages_html

    items = prepare_display_items(disclosures, market_caps)

    docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
    os.makedirs(docs_dir, exist_ok=True)

    # JSON 保存・古いデータ削除・マニフェスト更新
    save_daily_json(items, target_date, docs_dir)
    cleanup_old_data(docs_dir, keep_days=14)
    available_dates = update_manifest(docs_dir)

    print(f"\n[5/6] Generating GitHub Pages HTML...")
    github_user = os.environ.get("GITHUB_REPOSITORY_OWNER", "user")
    repo_name = os.environ.get("GITHUB_REPOSITORY", "").split("/")[-1] or "tdnet-monitor"
    pages_url = f"https://{github_user}.github.io/{repo_name}/"

    # GitHub Pages 用 HTML（日付選択式）
    pages_html = generate_pages_html(available_dates)
    pages_path = os.path.join(docs_dir, "index.html")
    with open(pages_path, "w", encoding="utf-8") as f:
        f.write(pages_html)
    print(f"  GitHub Pages HTML written to: {pages_path}")

    # メール用 HTML
    email_html = generate_email_html(items, target_date, pages_url)

    print(f"\n[6/6] Sending Gmail notification...")
    from gmail_sender import send_gmail
    send_gmail(email_html, target_date)

    print(f"\n{'=' * 60}")
    print(f"Done! {len(items)} disclosures processed.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
