"""REIT / ETF のフィルタリング

JPX が公開する上場銘柄一覧を取得し、
「市場・商品区分」列から ETF/ETN/REIT/インフラファンド等を正確に判定する。
証券コード範囲による近似判定は使用しない。

JPX は .xls 形式で公開しているため、CSV版を優先的に使用する。
CSV が取得できない場合は xlrd で .xls を読み取る。
"""

import requests
import csv
from io import StringIO

# JPX 上場銘柄一覧（CSV版）
JPX_CSV_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.csv"

# Excel版のURL（フォールバック用）
JPX_XLS_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"

# 除外キーワード
EXCLUDE_KEYWORDS = [
    "ETF", "ETN",
    "REIT", "不動産投資信託",
    "インフラファンド", "インフラ投資法人",
    "出資証券",
    "ベンチャーファンド",
]


def _fetch_from_csv() -> set[str]:
    """CSV版の上場銘柄一覧からREIT/ETFコードを取得"""
    print(f"  Downloading JPX list (CSV): {JPX_CSV_URL}")
    resp = requests.get(JPX_CSV_URL, timeout=60)
    resp.raise_for_status()

    # エンコーディング判定
    for encoding in ["utf-8", "shift_jis", "cp932"]:
        try:
            text = resp.content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise RuntimeError("JPX CSV のデコードに失敗しました")

    reader = csv.reader(StringIO(text))
    header = next(reader)

    # ヘッダーから列インデックスを特定
    code_col = None
    segment_col = None
    for i, col_name in enumerate(header):
        col_name = col_name.strip()
        if "コード" in col_name and code_col is None:
            code_col = i
        if "市場・商品区分" in col_name or "市場商品区分" in col_name:
            segment_col = i

    if code_col is None or segment_col is None:
        print(f"  Warning: Header detection failed. Headers: {header[:6]}")
        code_col = 0
        segment_col = 2

    excluded: set[str] = set()
    for row in reader:
        if len(row) <= max(code_col, segment_col):
            continue
        code = row[code_col].strip()
        code = code[:4] if len(code) >= 4 else code
        if not any(c.isdigit() for c in code):
            continue

        segment = row[segment_col].strip()
        if any(kw in segment for kw in EXCLUDE_KEYWORDS):
            excluded.add(code)

    return excluded


def _fetch_from_xls() -> set[str]:
    """XLS版の上場銘柄一覧からREIT/ETFコードを取得（フォールバック）"""
    try:
        import xlrd
    except ImportError:
        raise RuntimeError(
            "xlrd がインストールされていません。"
            "pip install xlrd でインストールしてください。"
        )

    print(f"  Downloading JPX list (XLS): {JPX_XLS_URL}")
    resp = requests.get(JPX_XLS_URL, timeout=60)
    resp.raise_for_status()

    wb = xlrd.open_workbook(file_contents=resp.content)
    ws = wb.sheet_by_index(0)

    # ヘッダー行を探す
    code_col = None
    segment_col = None
    header_row = 0

    for row_idx in range(min(5, ws.nrows)):
        for col_idx in range(ws.ncols):
            val = str(ws.cell_value(row_idx, col_idx)).strip()
            if "コード" in val and code_col is None:
                code_col = col_idx
                header_row = row_idx
            if "市場・商品区分" in val or "市場商品区分" in val:
                segment_col = col_idx
                header_row = row_idx

    if code_col is None or segment_col is None:
        code_col = 0
        segment_col = 2
        header_row = 0

    excluded: set[str] = set()
    for row_idx in range(header_row + 1, ws.nrows):
        code_val = ws.cell_value(row_idx, code_col)
        if isinstance(code_val, float):
            code = str(int(code_val))
        else:
            code = str(code_val).strip()
        code = code[:4] if len(code) >= 4 else code
        if not any(c.isdigit() for c in code):
            continue

        segment = str(ws.cell_value(row_idx, segment_col)).strip()
        if any(kw in segment for kw in EXCLUDE_KEYWORDS):
            excluded.add(code)

    return excluded


def get_excluded_codes() -> set[str]:
    """
    REIT / ETF / ETN / インフラファンド 等の証券コードセットを返す。
    CSV版を優先し、失敗時はXLS版にフォールバックする。
    """
    try:
        excluded = _fetch_from_csv()
        if excluded:
            print(f"  Excluded codes (REIT/ETF/etc.): {len(excluded)} companies")
            return excluded
        print("  CSV returned no results, trying XLS...")
    except Exception as e:
        print(f"  CSV fetch failed ({e}), trying XLS...")

    try:
        excluded = _fetch_from_xls()
        print(f"  Excluded codes (REIT/ETF/etc.): {len(excluded)} companies")
        return excluded
    except Exception as e:
        print(f"  WARNING: XLS fetch also failed ({e})")
        print("  Proceeding without REIT/ETF filtering.")
        return set()


def filter_disclosures(disclosures: list, excluded_codes: set[str]) -> list:
    """REIT/ETF を除外した開示リストを返す"""
    before = len(disclosures)
    filtered = [d for d in disclosures if d.code not in excluded_codes]
    after = len(filtered)
    print(f"  Filtered: {before} -> {after} (removed {before - after} REIT/ETF disclosures)")
    return filtered
