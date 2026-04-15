"""TDnet 適時開示モニター メイン処理

2回/日の実行に対応:
  - evening (18:00): 00:00〜18:00 の開示を取得・メール通知（上位30件）
  - night   (24:00): 18:01〜24:00 の開示を取得・既存データにマージ・メール通知（差分全件）
"""

import os
import json
import glob
from datetime import date, datetime, timedelta
import jpholiday


def is_market_open(target_date: date) -> bool:
    """東証が開場しているかを判定する"""
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


def filter_by_time(disclosures: list, start_time: str, end_time: str) -> list:
    """開示時刻で絞り込む (HH:MM 形式で比較)"""
    filtered = [d for d in disclosures if start_time <= d.time <= end_time]
    print(f"  Time filter [{start_time}~{end_time}]: {len(disclosures)} -> {len(filtered)}")
    return filtered


def load_existing_json(json_path: str) -> list[dict]:
    """既存の JSON データを読み込む"""
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("items", [])
    return []


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
    print(f"  Daily JSON saved: {json_path} ({len(items)} items)")


def merge_items(existing_records: list[dict], new_items: list) -> list:
    """既存のレコード（dict）と新規アイテム（DisplayItem）をマージする

    重複排除は pdf_url で判定する。
    マージ後は時価総額降順 → 同一コード内は時刻昇順でソートする。
    """
    from html_generator import DisplayItem

    # 既存レコードを DisplayItem に変換
    existing = []
    for r in existing_records:
        existing.append(DisplayItem(
            code=r["code"],
            company_name=r["company_name"],
            market_cap=r.get("market_cap", 0),
            time=r["time"],
            title=r["title"],
            pdf_url=r["pdf_url"],
        ))

    # 既存の pdf_url セット
    existing_urls = set(item.pdf_url for item in existing)

    # 新規アイテムのうち、既存にないものだけ追加
    added = 0
    for item in new_items:
        if item.pdf_url not in existing_urls:
            existing.append(item)
            existing_urls.add(item.pdf_url)
            added += 1

    print(f"  Merge: {len(existing) - added} existing + {added} new = {len(existing)} total")

    # 再ソート: 時価総額降順 → コード昇順 → 時刻昇順
    existing.sort(key=lambda x: (-x.market_cap, x.code, x.time))
    return existing


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

    # 実行モード: evening (18:00) or night (24:00)
    run_mode = os.environ.get("RUN_MODE", "evening")
    print(f"\nRUN_MODE env: '{run_mode}'")
    print(f"date.today(): {date.today()}")

    # night モードは JST 24:00 = 翌日 0:00 に実行されるため、
    # date.today() が翌日を返す → 前日に戻す
    if run_mode == "night" and not date_arg:
        target_date = target_date - timedelta(days=1)
        print(f"Night mode: adjusted target_date to previous day")

    print(f"Target date: {target_date}")
    print(f"Run mode: {run_mode}")

    if not is_market_open(target_date):
        print("Market is closed. Skipping.")
        return

    # 時間フィルタの設定
    if run_mode == "night":
        time_start, time_end = "18:01", "23:59"
    else:
        time_start, time_end = "00:00", "18:00"

    print(f"\n[1/6] Fetching disclosures from TDnet...")
    from tdnet_scraper import fetch_disclosures
    all_disclosures = fetch_disclosures(target_date)

    if not all_disclosures:
        print("No disclosures found. Exiting.")
        return

    # 時間フィルタ適用
    disclosures = filter_by_time(all_disclosures, time_start, time_end)

    if not disclosures:
        print(f"No disclosures in time range [{time_start}~{time_end}]. Exiting.")
        return

    print(f"\n[2/6] Filtering REIT/ETF...")
    from filter_reit_etf import get_excluded_codes, filter_disclosures as reit_filter
    excluded_codes = get_excluded_codes()
    disclosures = reit_filter(disclosures, excluded_codes)

    if not disclosures:
        print("No disclosures after filtering. Exiting.")
        return

    print(f"\n[3/6] Fetching market cap data...")
    from market_cap import fetch_market_caps
    codes = set(d.code for d in disclosures)
    market_caps = fetch_market_caps(codes)

    print(f"\n[4/6] Processing data...")
    from html_generator import prepare_display_items, generate_email_html, generate_pages_html

    new_items = prepare_display_items(disclosures, market_caps)

    docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
    os.makedirs(docs_dir, exist_ok=True)
    data_dir = os.path.join(docs_dir, "data")
    json_path = os.path.join(data_dir, f"{target_date.isoformat()}.json")

    if run_mode == "night":
        # night: 既存データとマージ
        existing_records = load_existing_json(json_path)
        all_items = merge_items(existing_records, new_items)
        email_items = new_items  # メールには差分のみ
        email_max_items = None   # 全件
    else:
        # evening: 新規データのみ
        all_items = new_items
        email_items = new_items
        email_max_items = 30     # 上位30件

    # JSON 保存（evening: 新規、night: マージ済み）
    save_daily_json(all_items, target_date, docs_dir)
    cleanup_old_data(docs_dir, keep_days=14)
    available_dates = update_manifest(docs_dir)

    print(f"\n[5/6] Generating GitHub Pages HTML...")
    github_user = os.environ.get("GITHUB_REPOSITORY_OWNER", "user")
    repo_name = os.environ.get("GITHUB_REPOSITORY", "").split("/")[-1] or "tdnet-monitor"
    pages_url = f"https://{github_user}.github.io/{repo_name}/"

    pages_html = generate_pages_html(available_dates)
    pages_path = os.path.join(docs_dir, "index.html")
    with open(pages_path, "w", encoding="utf-8") as f:
        f.write(pages_html)
    print(f"  GitHub Pages HTML written to: {pages_path}")

    # メール用 HTML
    if run_mode == "night":
        email_subject_suffix = "（夜間更新分）"
    else:
        email_subject_suffix = ""

    email_html = generate_email_html(
        email_items, target_date, pages_url,
        max_items=email_max_items,
        subject_suffix=email_subject_suffix,
    )

    print(f"\n[6/6] Sending Gmail notification...")
    from gmail_sender import send_gmail
    send_gmail(email_html, target_date, subject_suffix=email_subject_suffix)

    print(f"\n{'=' * 60}")
    print(f"Done! mode={run_mode}, {len(email_items)} items in email, {len(all_items)} items total.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
