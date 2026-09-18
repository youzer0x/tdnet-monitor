"""REIT / ETF のフィルタリング

JPX が公開する上場銘柄一覧を取得し、「市場・商品区分」列から
ETF/ETN/REIT/インフラファンド等を正確に判定する。証券コード範囲による近似判定は使用しない。

配布形式は 2026-09-03 に .xls から .xlsx へ切り替わった（旧 URL の .xls/.csv は 404）。
JPX 側の URL 変更・一時障害で取得できない間に除外が黙って無効化されるのを防ぐため、
最後に取得できた除外コード集合を cache/jpx_excluded.json に保存し、取得失敗時はそれを使う。
優先順: xlsx 取得 → キャッシュ → 空集合（除外なしで続行・WARNING）。
"""

import json
import os
from datetime import date
from io import BytesIO

import requests

# JPX 上場銘柄一覧（xlsx）。ページ: https://www.jpx.co.jp/markets/statistics-equities/misc/01.html
JPX_XLSX_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xlsx"

# 最後に取得できた除外コード集合（リポジトリにコミットして GitHub Actions でも使う）
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cache", "jpx_excluded.json")

# 除外キーワード（「市場・商品区分」列に含まれていれば除外）
EXCLUDE_KEYWORDS = [
    "ETF", "ETN",
    "REIT", "不動産投資信託",
    "インフラファンド", "インフラ投資法人",
    "出資証券",
    "ベンチャーファンド",
]

# ヘッダー検出に失敗した場合の列位置（現行 xlsx: 日付, コード, 銘柄名, 市場・商品区分, ...）
_FALLBACK_CODE_COL = 1
_FALLBACK_SEGMENT_COL = 3


def _norm_cell(value) -> str:
    """セル値を文字列に正規化する（openpyxl は数値コードを int/float で返す）。"""
    if value is None:
        return ""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    return str(value).strip()


def _parse_rows(header, rows) -> set[str]:
    """ヘッダー行とデータ行から REIT/ETF 等の証券コード集合を返す（純粋関数）。

    列は「コード」「市場・商品区分」を名前で探し、見つからなければ既定位置を使う。
    """
    code_col = None
    segment_col = None
    for i, col_name in enumerate(header):
        name = _norm_cell(col_name)
        if "コード" in name and code_col is None:
            code_col = i
        if "市場・商品区分" in name or "市場商品区分" in name:
            segment_col = i
    if code_col is None or segment_col is None:
        print(f"  Warning: Header detection failed. Headers: {list(header)[:6]}")
        code_col, segment_col = _FALLBACK_CODE_COL, _FALLBACK_SEGMENT_COL

    excluded: set[str] = set()
    for row in rows:
        if row is None or len(row) <= max(code_col, segment_col):
            continue
        code = _norm_cell(row[code_col])
        code = code[:4] if len(code) >= 4 else code
        if not any(c.isdigit() for c in code):
            continue
        segment = _norm_cell(row[segment_col])
        if any(kw in segment for kw in EXCLUDE_KEYWORDS):
            excluded.add(code)
    return excluded


def _fetch_from_xlsx(url: str = JPX_XLSX_URL) -> set[str]:
    """JPX の xlsx をダウンロードして除外コード集合を返す（ネットワーク）。"""
    import openpyxl  # 遅延インポート（テスト・オフライン解析で不要）

    print(f"  Downloading JPX list (XLSX): {url}")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    wb = openpyxl.load_workbook(BytesIO(resp.content), read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        header = next(rows, None)
        if header is None:
            raise RuntimeError("JPX xlsx にヘッダー行がありません")
        return _parse_rows(header, rows)
    finally:
        wb.close()


def load_cache(path: str = CACHE_PATH) -> tuple[set[str], str | None]:
    """キャッシュを読む。無ければ (set(), None)。"""
    if not os.path.exists(path):
        return set(), None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        codes = {str(c) for c in data.get("codes", [])}
        return codes, data.get("fetched_at")
    except (OSError, json.JSONDecodeError, AttributeError):
        return set(), None


def save_cache(codes: set[str], path: str = CACHE_PATH, today: date | None = None) -> bool:
    """コード集合が前回と異なる時だけキャッシュを書き換える。書いたら True。

    毎回書き換えると内容不変でも日次コミットが発生するため、変化時のみ更新する。
    """
    existing, _ = load_cache(path)
    if existing == set(codes) and os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    payload = {
        "source": JPX_XLSX_URL,
        "fetched_at": (today or date.today()).isoformat(),
        "count": len(codes),
        "codes": sorted(codes),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return True


def get_excluded_codes(
    cache_path: str = CACHE_PATH,
    fetch=_fetch_from_xlsx,
    today: date | None = None,
) -> set[str]:
    """REIT / ETF / ETN / インフラファンド 等の証券コード集合を返す。

    JPX から取得できればキャッシュを更新して返す。取得失敗（例外・空）ならキャッシュを使い、
    キャッシュも無ければ空集合を返して除外なしで続行する（WARNING を出す）。
    """
    try:
        excluded = fetch()
        if excluded:
            if save_cache(excluded, cache_path, today=today):
                print(f"  JPX exclusion cache updated: {cache_path}")
            print(f"  Excluded codes (REIT/ETF/etc.): {len(excluded)} companies")
            return excluded
        print("  JPX list returned no excluded codes; falling back to cache...")
    except Exception as e:
        print(f"  JPX fetch failed ({e}); falling back to cache...")

    cached, fetched_at = load_cache(cache_path)
    if cached:
        print(f"  WARNING: using cached JPX exclusion list ({len(cached)} codes, fetched {fetched_at})")
        return cached

    print("  WARNING: no JPX list and no cache. Proceeding without REIT/ETF filtering.")
    return set()


def filter_disclosures(disclosures: list, excluded_codes: set[str]) -> list:
    """REIT/ETF を除外した開示リストを返す"""
    before = len(disclosures)
    filtered = [d for d in disclosures if d.code not in excluded_codes]
    after = len(filtered)
    print(f"  Filtered: {before} -> {after} (removed {before - after} REIT/ETF disclosures)")
    return filtered
