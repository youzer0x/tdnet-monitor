"""過去日付の開示データをバックフィルする一回限りのスクリプト。

ローリング保持の cleanup によって削除された 2026-05-11 以降の日次 JSON を
TDnet から再取得して復元する。1日分すべて (00:00〜23:59) を対象とし、
REIT/ETF・非東証銘柄を除外、J-Quants で時価総額を付与して保存する。
通常運用の main.py と異なり、メール送信・cleanup は行わない。

使い方:
  JQUANTS_API_KEY=... python backfill.py 2026-05-11 2026-05-19
  JQUANTS_API_KEY=... python backfill.py 2026-05-15            # 単日
"""

import os
import sys
from datetime import date, timedelta

from main import (
    is_market_open,
    save_daily_json,
    update_manifest,
    _load_cached_market_caps,
)
from tdnet_scraper import fetch_disclosures
from filter_reit_etf import get_excluded_codes, filter_disclosures as reit_filter
from market_cap_jquants import fetch_market_caps, fetch_tse_codes
from html_generator import prepare_display_items, generate_pages_html


def _disclosure_date(pdf_url: str) -> str | None:
    """TDnet の PDF ファイル名 (例 140120260514533826.pdf) から開示日 YYYYMMDD を取り出す。

    ファイル名は「4桁プレフィクス + 8桁日付(YYYYMMDD) + 6桁連番」の18桁構成。
    取り出せない場合は None。
    """
    if not pdf_url:
        return None
    name = pdf_url.rsplit("/", 1)[-1].replace(".pdf", "")
    digits = "".join(c for c in name if c.isdigit())
    if len(digits) < 12:
        return None
    d8 = digits[4:12]
    if d8.startswith("20") and d8.isdigit():
        return d8
    return None


def _filter_to_date(disclosures: list, target_date: date) -> list:
    """TDnet アーカイブは古い日付を要求すると複数日分（決算ピーク時は数千件）を
    返すため、PDF ファイル名の開示日が target_date と一致するものだけに絞る。
    """
    want = target_date.strftime("%Y%m%d")
    before = len(disclosures)
    kept = [d for d in disclosures if _disclosure_date(d.pdf_url) == want]
    print(f"  Date filter [=={want}]: {before} -> {len(kept)}")
    return kept


def backfill_date(target_date: date, docs_dir: str) -> bool:
    """単一日のデータを取得・保存する。保存したら True を返す。"""
    print(f"\n{'=' * 60}")
    print(f"Backfill {target_date}")
    print(f"{'=' * 60}")

    if not is_market_open(target_date):
        print("  Market closed. Skip.")
        return False

    all_disclosures = fetch_disclosures(target_date)
    if not all_disclosures:
        print("  No disclosures found. Skip.")
        return False

    # アーカイブが返す他日分を除外し、当日の開示だけにする
    disclosures = _filter_to_date(all_disclosures, target_date)
    if not disclosures:
        print("  No disclosures dated on target date. Skip.")
        return False

    excluded_codes = get_excluded_codes()
    disclosures = reit_filter(disclosures, excluded_codes)
    if not disclosures:
        print("  Empty after REIT/ETF filter. Skip.")
        return False

    data_dir = os.path.join(docs_dir, "data")

    # 東証本則のみ（プロマーケット・名証/福証/札証単独上場を除外）
    tse_codes = fetch_tse_codes(target_date)
    if tse_codes:
        before = len(disclosures)
        disclosures = [d for d in disclosures if d.code in tse_codes]
        print(f"  Non-TSE filter: {before} -> {len(disclosures)}")
    if not disclosures:
        print("  Empty after non-TSE filter. Skip.")
        return False

    codes = set(d.code for d in disclosures)
    market_caps = fetch_market_caps(codes, target_date)

    # 取得失敗コードは直近日次キャッシュから補完
    missing = codes - set(market_caps.keys())
    if missing:
        cached = _load_cached_market_caps(data_dir, target_date)
        filled = {c: cached[c] for c in missing if c in cached}
        if filled:
            market_caps.update(filled)
            print(f"  Filled {len(filled)} market caps from cache")

    items = prepare_display_items(disclosures, market_caps)
    save_daily_json(items, target_date, docs_dir)
    return True


def main():
    if len(sys.argv) >= 3:
        start = date.fromisoformat(sys.argv[1])
        end = date.fromisoformat(sys.argv[2])
    elif len(sys.argv) == 2:
        start = end = date.fromisoformat(sys.argv[1])
    else:
        print("Usage: python backfill.py START_DATE [END_DATE]")
        sys.exit(1)

    docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
    os.makedirs(os.path.join(docs_dir, "data"), exist_ok=True)

    # 古い日付から順に処理することで、後続日のキャッシュ補完が効くようにする
    d = start
    saved = 0
    while d <= end:
        if backfill_date(d, docs_dir):
            saved += 1
        d += timedelta(days=1)

    available_dates = update_manifest(docs_dir)

    pages_html = generate_pages_html(available_dates)
    pages_path = os.path.join(docs_dir, "index.html")
    with open(pages_path, "w", encoding="utf-8") as f:
        f.write(pages_html)

    print(f"\n{'=' * 60}")
    print(f"Backfill done. {saved} dates saved. {len(available_dates)} dates in manifest.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
