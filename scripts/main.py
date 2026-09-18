"""TDnet 適時開示モニター メイン処理

1営業日あたり 3 回の実行に対応:
  - evening   (17:05 JST, cron-job.org → workflow_dispatch): 00:00〜17:00 の開示を記録・メール通知（上位30件）
  - night     (00:10 JST, GitHub schedule): 当日全件を取得し、未記録の開示だけを追記・メール通知（差分全件）
  - night 予備 (05:30 JST, GitHub schedule): 同上。1回目が記録・通知を済ませていれば何もしない

記録の単位は TDnet の書類 ID（PDF ファイル名。原本 URL でも Release 退避後の URL でも同じ）。
記録済みの開示は再取得しても追加されないため、どの実行も冪等で、夕方の実行が抜けた日は深夜の
1回目が日中分を補完する。メールは JSON の `notified`（モード別の通知済みフラグ）と各項目の
`pending_notify`（記録済み・未通知）で制御し、「未通知の開示がある」かつ「そのモードでまだ
通知していない」時だけ送る（予備実行・手動再実行・遅れて見つかった追加分ではメールが増えない）。
補完時の深夜メールは上位30件に絞り、件名で知らせる。
"""

import os
import json
import glob
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

import jpholiday

from html_generator import DisplayItem
from pdf_archive import pdf_id, TDNET_PDF_BASE


JST = timezone(timedelta(hours=9))   # 固定オフセット（tzdata 非依存）

# 日次データの保持期間（ローリング）。開示日から RETAIN_DAYS 日以内のものだけを
# GitHub 上で管理し、それより古い日次 JSON と Release 上の PDF は削除する。
# 配信元 TDnet は PDF を約30日で消すため、ここで消した分は復元不可。
RETAIN_DAYS = 90

# night の対象日: JST でこの時刻より前に動いた実行は「前日分」（GitHub schedule は 23:59 JST の
# cron でも数時間遅れて翌日未明に動く。遅延ゼロで 23:59 に動いた場合は当日）。
NIGHT_ROLLBACK_HOUR = 17

# TARGET_DATE 手動指定でこれより古い日は TDnet 一覧が複数日分を返すため取得しない（保守処理のみ）。
REPLAY_MAX_AGE_DAYS = 28

EVENING_WINDOW = ("00:00", "17:00")
EMAIL_TOP_N = 30
DOCS_DIR_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")


def retention_cutoff(today: date | None = None) -> date:
    """保持の下限日（この日を含めて以降を保持、これより前は削除）。

    基準は必ず実行日。target_date は手動リプレイや night モードで前日に
    巻き戻るため、保持窓の基準には使わない。
    """
    return (today or date.today()) - timedelta(days=RETAIN_DAYS)


def resolve_target_date(run_mode: str, now_jst: datetime, date_arg: str | None) -> date:
    """対象日を決める。TARGET_DATE 指定が最優先。night は JST 17 時前なら前日、以降は当日。"""
    if date_arg:
        return datetime.strptime(date_arg, "%Y-%m-%d").date()
    today = now_jst.date()
    if run_mode == "night" and now_jst.hour < NIGHT_ROLLBACK_HOUR:
        return today - timedelta(days=1)
    return today


def export_github_env(name: str, value: str) -> None:
    """GitHub Actions の後続ステップへ環境変数を渡す（GITHUB_ENV 未設定なら何もしない）。"""
    path = os.environ.get("GITHUB_ENV")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")


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


# ── 日次 JSON（レコード＝dict）───────────────────────────────

def _sort_key(rec: dict):
    """時価総額降順 → コード昇順 → 時刻昇順"""
    return (-(rec.get("market_cap") or 0), rec.get("code", ""), rec.get("time", ""))


def _meta_key(rec: dict) -> str:
    return f"{rec.get('code', '')}|{rec.get('time', '')}|{rec.get('title', '')}"


def item_key(rec: dict) -> str:
    """開示の同一性キー。TDnet の書類 ID（PDF ファイル名）を主キーにし、URL 無しは code|time|title。"""
    pid = pdf_id(rec.get("pdf_url") or "")
    return pid if pid else _meta_key(rec)


def split_new_records(existing: list[dict], fetched: list[dict]) -> list[dict]:
    """取得分のうち未記録のものだけを返す（順序は fetched のまま）。

    URL 無しで記録された既存項目（TDnet にリンクが無かった・公開終了で URL を落とした）は
    ID で突合できないため、(code, time, title) が一致する取得分も既登録とみなす。
    """
    known = {item_key(r) for r in existing}
    urlless = {_meta_key(r) for r in existing if not (r.get("pdf_url") or "")}
    out: list[dict] = []
    for rec in fetched:
        k = item_key(rec)
        if k in known:
            continue
        if urlless and _meta_key(rec) in urlless:
            continue
        known.add(k)
        out.append(rec)
    return out


def merge_records(existing: list[dict], new: list[dict]) -> list[dict]:
    """既存レコードはそのまま（pdf_expired 等の付加情報を保持）、新規を追記して再ソート。"""
    merged = list(existing) + list(new)
    merged.sort(key=_sort_key)
    return merged


def load_daily_data(json_path: str, target_date: date | None = None) -> dict:
    """日次 JSON 全体（top-level キー込み）を読む。無ければ骨格を返す。"""
    data: dict = {}
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    if target_date is not None:
        data.setdefault("date", target_date.isoformat())
    data.setdefault("items", [])
    data.setdefault("notified", {})
    return data


def save_daily_data(json_path: str, data: dict) -> None:
    """件数を再計算して保存。date/company_count/total_count/items 以外のキーも保持する。"""
    items = data.get("items", [])
    out = {
        "date": data.get("date"),
        "company_count": len({it.get("code") for it in items}),
        "total_count": len(items),
        "items": items,
    }
    for k, v in data.items():
        if k not in out:
            out[k] = v
    os.makedirs(os.path.dirname(os.path.abspath(json_path)), exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


def load_existing_json(json_path: str) -> list[dict]:
    """既存の JSON の items を読み込む（無ければ空）"""
    return load_daily_data(json_path).get("items", [])


def disclosure_to_record(d) -> dict:
    """スクレイプ結果（Disclosure）を JSON レコードへ（時価総額は後で付与）。"""
    return {
        "code": d.code,
        "company_name": d.company_name,
        "market_cap": 0,
        "time": d.time,
        "title": d.title,
        "pdf_url": d.pdf_url,
    }


def record_from_item(item: DisplayItem) -> dict:
    return {
        "code": item.code,
        "company_name": item.company_name,
        "market_cap": item.market_cap,
        "time": item.time,
        "title": item.title,
        "pdf_url": item.pdf_url,
    }


def records_to_display_items(records: list[dict], for_email: bool = False) -> list[DisplayItem]:
    """レコードを表示用 DisplayItem に変換する（順序は records のまま）。

    for_email=True のときは、リンク先を TDnet 原本 URL（ブラウザ内表示できる）に再構成する。
    Release 退避後の URL はダウンロードになるため、当日中に読むメールでは原本を優先する。
    """
    items = []
    for r in records:
        url = r.get("pdf_url") or ""
        if for_email and url:
            pid = pdf_id(url)
            if pid:
                url = f"{TDNET_PDF_BASE}{pid}.pdf"
        items.append(DisplayItem(
            code=r["code"],
            company_name=r["company_name"],
            market_cap=r.get("market_cap") or 0,
            time=r["time"],
            title=r["title"],
            pdf_url=url,
        ))
    return items


def save_daily_json(items: list, target_date: date, docs_dir: str) -> None:
    """DisplayItem のリストをその日の全件として保存する（backfill.py 用の互換ラッパ）。

    既存ファイルの top-level キー（tdnet_available, notified 等）は保持する。
    """
    data_dir = os.path.join(docs_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    json_path = os.path.join(data_dir, f"{target_date.isoformat()}.json")
    data = load_daily_data(json_path, target_date)
    data["items"] = [record_from_item(it) for it in items]
    save_daily_data(json_path, data)
    print(f"  Daily JSON saved: {json_path} ({len(items)} items)")


def _load_cached_market_caps(data_dir: str, target_date: date, max_days: int = 30) -> dict[str, float]:
    """直近 max_days 日分の日次 JSON を新しい順に走査し、
    各コードの最新の正値 market_cap を返す（target_date 自身は除外）。

    時価総額取得失敗時のフォールバック用。
    """
    cache: dict[str, float] = {}
    if not os.path.exists(data_dir):
        return cache
    for json_file in sorted(glob.glob(os.path.join(data_dir, "*.json")), reverse=True):
        fname = os.path.basename(json_file)
        if fname == "manifest.json":
            continue
        try:
            file_date = date.fromisoformat(fname.replace(".json", ""))
        except ValueError:
            continue
        if file_date >= target_date:
            continue
        if (target_date - file_date).days > max_days:
            break
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        for item in data.get("items", []):
            code = item.get("code")
            mcap = item.get("market_cap", 0)
            if code and mcap and mcap > 0 and code not in cache:
                cache[code] = mcap
    return cache


def cleanup_old_data(docs_dir: str, start_date: date) -> None:
    """start_date より前の日付の JSON を削除する（ローリング保持）"""
    data_dir = os.path.join(docs_dir, "data")
    if not os.path.exists(data_dir):
        return
    removed = 0
    for json_file in glob.glob(os.path.join(data_dir, "*.json")):
        fname = os.path.basename(json_file)
        if fname == "manifest.json":
            continue
        try:
            file_date = date.fromisoformat(fname.replace(".json", ""))
            if file_date < start_date:
                os.remove(json_file)
                removed += 1
        except ValueError:
            pass
    if removed:
        print(f"  Cleaned up {removed} JSON files older than {start_date}")


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


# ── 通知判定 ────────────────────────────────────────────────

class NotifyDecision(NamedTuple):
    action: str              # "send" | "clear" | "none"
    items: list              # pending レコード（未ソート）
    max_items: int | None
    subject_suffix: str
    mark: dict               # 成功後に立てる notified フラグ


def select_notification(data: dict, run_mode: str, send_email: bool) -> NotifyDecision:
    """メールを送るか・何を送るかを決める（純粋関数）。

    - 未通知（pending_notify）の項目が無い → none（保存もしない）
    - そのモードで通知済み（予備実行・手動再実行・遅れて見つかった追加分） → clear（記録のみ）
    - SEND_EMAIL=0（リプレイ） → clear、通知済み扱いにする
    - night で夕方が未通知 → 補完モード（上位30件・件名で知らせる・両モードを通知済みに）
    """
    pending = [r for r in data.get("items", []) if r.get("pending_notify")]
    notified = data.get("notified") or {}
    if not pending:
        return NotifyDecision("none", [], None, "", {})
    if notified.get(run_mode):
        return NotifyDecision("clear", pending, None, "", {})
    if not send_email:
        return NotifyDecision("clear", pending, None, "", {run_mode: True})
    if run_mode == "night":
        if not notified.get("evening"):
            return NotifyDecision("send", pending, EMAIL_TOP_N, "（夜間更新分・夕方分を補完）",
                                  {"evening": True, "night": True})
        return NotifyDecision("send", pending, None, "（夜間更新分）", {"night": True})
    return NotifyDecision("send", pending, EMAIL_TOP_N, "", {"evening": True})


def apply_notification(data: dict, decision: NotifyDecision) -> dict:
    """pending_notify を全項目から外し、notified フラグを更新する。"""
    for r in data.get("items", []):
        r.pop("pending_notify", None)
    notified = dict(data.get("notified") or {})
    notified.update(decision.mark)
    data["notified"] = notified
    return data


# ── メイン ──────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("TDnet 適時開示モニター")
    print("=" * 60)

    now_jst = datetime.now(JST)
    run_mode = os.environ.get("RUN_MODE", "evening")
    send_email = os.environ.get("SEND_EMAIL", "1") != "0"
    archive_pdfs = os.environ.get("ARCHIVE_PDFS", "1") != "0"
    date_arg = os.environ.get("TARGET_DATE") or None
    target_date = resolve_target_date(run_mode, now_jst, date_arg)
    export_github_env("TARGET_DATE_RESOLVED", target_date.isoformat())

    print(f"\nnow (JST): {now_jst:%Y-%m-%d %H:%M}  mode={run_mode}  target={target_date}"
          f"  send_email={send_email}  archive={archive_pdfs}")

    if not is_market_open(target_date):
        print("Market is closed. Skipping.")
        return

    docs_dir = os.environ.get("DOCS_DIR") or DOCS_DIR_DEFAULT
    data_dir = os.path.join(docs_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    json_path = os.path.join(data_dir, f"{target_date.isoformat()}.json")
    data = load_daily_data(json_path, target_date)
    print(f"  Existing records: {len(data['items'])}  notified={data.get('notified')}")

    # ── [1/6] 取得（失敗しても保守処理と通知判定までは進む）
    print(f"\n[1/6] Fetching disclosures from TDnet...")
    disclosures: list = []
    age_days = (now_jst.date() - target_date).days
    if age_days > REPLAY_MAX_AGE_DAYS:
        print(f"  WARNING: target is {age_days} days old (> {REPLAY_MAX_AGE_DAYS}); "
              f"TDnet returns multi-day lists for old dates. Skipping fetch.")
    else:
        try:
            from tdnet_scraper import fetch_disclosures
            disclosures = fetch_disclosures(target_date)
        except Exception as e:
            print(f"  !!! TDnet fetch failed (continuing with maintenance): {type(e).__name__}: {e}")
            disclosures = []
    if run_mode == "night":
        print("  Night mode: full day (00:00~23:59), only unrecorded items are added")
    elif disclosures:
        disclosures = filter_by_time(disclosures, *EVENING_WINDOW)

    # ── [2/6] REIT/ETF・東証本則フィルタ
    print(f"\n[2/6] Filtering REIT/ETF and non-TSE listings...")
    if disclosures:
        from filter_reit_etf import get_excluded_codes, filter_disclosures as reit_filter
        disclosures = reit_filter(disclosures, get_excluded_codes())
    from market_cap_jquants import fetch_market_caps, fetch_tse_codes
    if disclosures:
        # 東証本則 (プライム/スタンダード/グロース) のみを対象とする。
        # 東京プロマーケット・名証/福証/札証単独上場銘柄は Web ページにも掲載しない。
        tse_codes = fetch_tse_codes(target_date)
        if tse_codes:
            before = len(disclosures)
            disclosures = [d for d in disclosures if d.code in tse_codes]
            if before != len(disclosures):
                print(f"  Non-TSE filter: {before} -> {len(disclosures)} "
                      f"(excluded {before - len(disclosures)} TOKYO PRO/regional listings)")

    # ── [3/6] 未記録分だけ時価総額を付けて追記
    print(f"\n[3/6] Recording new disclosures...")
    new = split_new_records(data["items"], [disclosure_to_record(d) for d in disclosures])
    print(f"  New records: {len(new)} (fetched {len(disclosures)}, existing {len(data['items'])})")
    if new:
        codes = {r["code"] for r in new}
        market_caps = fetch_market_caps(codes, target_date)
        missing = codes - set(market_caps.keys())
        if missing:
            cached = _load_cached_market_caps(data_dir, target_date)
            filled = {c: cached[c] for c in missing if c in cached}
            if filled:
                market_caps.update(filled)
                print(f"  Filled {len(filled)} market caps from cache "
                      f"(still missing: {len(missing) - len(filled)})")
        for r in new:
            r["market_cap"] = market_caps.get(r["code"], 0)
            r["pending_notify"] = True
        data["items"] = merge_records(data["items"], new)
        save_daily_data(json_path, data)
        print(f"  Daily JSON saved: {json_path} ({len(data['items'])} items)")

    # ── [4/6] 保守（新規の有無に関わらず実行。失敗しても通常運用は止めない）
    print(f"\n[4/6] Maintenance (PDF archive, retention, availability)...")
    if archive_pdfs:
        try:
            from pdf_archive import mirror_json_file, remirror_recent, gh_available
            if gh_available():
                if os.path.exists(json_path):
                    # 適時開示PDFを GitHub Releases へ退避し、JSON のリンクを恒久URLへ書き換える。
                    print(f"  PDF archive -> Releases: {mirror_json_file(json_path)}")
                # 過去数日分で退避し損ねた PDF（GitHub の一時障害等）を拾う
                print(f"  PDF re-mirror (recent days): {remirror_recent(data_dir, today=target_date)}")
            else:
                print("  PDF archive skipped (gh CLI not available)")
        except Exception as e:
            print(f"  PDF archive error (non-fatal): {e}")

    # ローリング保持: 90日より古い日次 JSON と Release 上の PDF を削除する。
    # JSON と Release アセットで同一 cutoff を共有し、ズレを防ぐ。
    cutoff = retention_cutoff(now_jst.date())
    cleanup_old_data(docs_dir, cutoff)
    if archive_pdfs:
        try:
            from pdf_archive import cleanup_expired_assets, gh_available
            if gh_available():
                print(f"  PDF asset cleanup -> Releases: {cleanup_expired_assets(cutoff_date=cutoff)}")
            else:
                print("  PDF asset cleanup skipped (gh CLI not available)")
        except Exception as e:
            print(f"  PDF asset cleanup error (non-fatal): {e}")

    # TDnet 原本がまだ閲覧可能な日は原本(ブラウザ内表示)へ、取り下げ後はアーカイブへ
    # リンクするための per-day フラグ(tdnet_available)を実応答で更新する。非致命。
    try:
        from pdf_archive import refresh_tdnet_availability
        print(f"  TDnet availability refresh: {refresh_tdnet_availability(data_dir, today=now_jst.date())}")
    except Exception as e:
        print(f"  TDnet availability refresh error (non-fatal): {e}")

    available_dates = update_manifest(docs_dir)

    # ── [5/6] GitHub Pages
    print(f"\n[5/6] Generating GitHub Pages HTML...")
    from html_generator import generate_pages_html, generate_email_html
    github_user = os.environ.get("GITHUB_REPOSITORY_OWNER", "user")
    repo_name = os.environ.get("GITHUB_REPOSITORY", "").split("/")[-1] or "tdnet-monitor"
    pages_url = f"https://{github_user}.github.io/{repo_name}/"

    pages_path = os.path.join(docs_dir, "index.html")
    with open(pages_path, "w", encoding="utf-8") as f:
        f.write(generate_pages_html(available_dates))
    print(f"  GitHub Pages HTML written to: {pages_path}")

    # ── [6/6] 通知（退避後の JSON を再読込して判定）
    print(f"\n[6/6] Notification...")
    data = load_daily_data(json_path, target_date)
    decision = select_notification(data, run_mode, send_email)
    if decision.action == "send":
        pending_sorted = sorted(decision.items, key=_sort_key)
        email_items = records_to_display_items(pending_sorted, for_email=True)
        email_html = generate_email_html(
            email_items, target_date, pages_url,
            max_items=decision.max_items,
            subject_suffix=decision.subject_suffix,
        )
        from gmail_sender import send_gmail
        send_gmail(email_html, target_date, subject_suffix=decision.subject_suffix)
        print(f"  Notified {len(email_items)} items"
              f"{f' (top {decision.max_items} shown)' if decision.max_items else ''}"
              f"{decision.subject_suffix}")
    elif decision.action == "clear":
        why = "SEND_EMAIL=0" if not send_email else f"{run_mode} already notified"
        print(f"  Recorded {len(decision.items)} items without email ({why})")
    else:
        print("  Nothing new to notify")
    if decision.action != "none":
        save_daily_data(json_path, apply_notification(data, decision))

    print(f"\n{'=' * 60}")
    print(f"Done! mode={run_mode}, target={target_date}, new={len(new)}, "
          f"total={len(data['items'])}, notify={decision.action}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
