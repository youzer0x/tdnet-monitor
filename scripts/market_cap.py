"""時価総額データの取得 (株探 kabutan.jp)

株探の個別銘柄ページから時価総額を取得する。
静的HTMLに時価総額が含まれるため、requests のみで確実に取得可能。
API キー不要。
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed


def _fetch_single(code: str) -> tuple[str, float | None, str | None]:
    """1銘柄の時価総額を株探から取得する。

    戻り値: (code, market_cap, failure_reason)
    - 成功時: (code, value, None)
    - 失敗時: (code, None, reason_string)  reason は HTTP ステータス・例外型・parse miss など
    """
    url = f"https://kabutan.jp/stock/?code={code}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    }

    last_reason: str | None = None
    for attempt in (1, 2):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                last_reason = f"http_{resp.status_code}"
            else:
                resp.encoding = "utf-8"
                soup = BeautifulSoup(resp.text, "lxml")

                # 方法1: テーブルから「時価総額」を探す
                for th in soup.find_all("th"):
                    if "時価総額" in th.get_text(strip=True):
                        td = th.find_next_sibling("td")
                        if td:
                            result = _parse_market_cap(td.get_text(strip=True))
                            if result:
                                return code, result, None

                # 方法2: ページ全体のテキストから正規表現で探す
                result = _extract_from_text(soup.get_text())
                if result:
                    return code, result, None

                last_reason = f"parse_miss(len={len(resp.text)})"
        except Exception as e:
            last_reason = f"{type(e).__name__}: {str(e)[:80]}"

        if attempt == 1:
            time.sleep(2.0)

    return code, None, last_reason


def _parse_market_cap(text: str) -> float | None:
    """時価総額テキストを億円単位にパースする"""
    text = text.replace(",", "").replace("　", "").replace(" ", "").strip()

    # "1兆2,345億円" or "1.5兆円"
    m = re.search(r"([\d.]+)\s*兆\s*([\d.]*)\s*億?", text)
    if m:
        cho = float(m.group(1))
        oku = float(m.group(2)) if m.group(2) else 0
        return round(cho * 10000 + oku, 1)

    # "1,234億円"
    m = re.search(r"([\d.]+)\s*億", text)
    if m:
        return round(float(m.group(1)), 1)

    # "12,345百万円"
    m = re.search(r"([\d.]+)\s*百万", text)
    if m:
        return round(float(m.group(1)) / 100, 1)

    return None


def _extract_from_text(text: str) -> float | None:
    """ページ全体テキストから時価総額を抽出"""
    patterns = [
        r"時価総額[^\d]{0,30}?([\d,.]+)\s*兆\s*([\d,.]*)\s*億",
        r"時価総額[^\d]{0,30}?([\d,.]+)\s*兆",
        r"時価総額[^\d]{0,30}?([\d,.]+)\s*億",
        r"時価総額[^\d]{0,30}?([\d,.]+)\s*百万",
    ]

    for i, pat in enumerate(patterns):
        m = re.search(pat, text)
        if m:
            if i == 0:
                cho = float(m.group(1).replace(",", ""))
                oku = float(m.group(2).replace(",", "")) if m.group(2) else 0
                return round(cho * 10000 + oku, 1)
            elif i == 1:
                return round(float(m.group(1).replace(",", "")) * 10000, 1)
            elif i == 2:
                return round(float(m.group(1).replace(",", "")), 1)
            elif i == 3:
                return round(float(m.group(1).replace(",", "")) / 100, 1)

    return None


def fetch_market_caps(codes: set[str]) -> dict[str, float]:
    """
    証券コードのセットを受け取り、{code: 時価総額(億円)} の辞書を返す。
    株探 (kabutan.jp) から取得。並列処理で高速化。
    """
    print(f"  Fetching market caps for {len(codes)} codes from kabutan.jp...")
    market_caps: dict[str, float] = {}
    failed: list[tuple[str, str]] = []

    sorted_codes = sorted(codes)

    # 並列3スレッドで取得（サーバー負荷を考慮）
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {}
        for code in sorted_codes:
            future = executor.submit(_fetch_single, code)
            futures[future] = code
            time.sleep(0.15)  # submit 間隔

        done_count = 0
        for future in as_completed(futures):
            code, mcap, reason = future.result()
            done_count += 1
            if mcap is not None:
                market_caps[code] = mcap
            else:
                failed.append((code, reason or "unknown"))

            if done_count % 50 == 0:
                print(f"    ... {done_count}/{len(sorted_codes)} processed")

    print(f"  Market caps resolved: {len(market_caps)} / {len(codes)} codes")
    if failed:
        reason_counts = Counter(r for _, r in failed)
        print(f"  Failed: {len(failed)} codes. Reasons: {dict(reason_counts.most_common(5))}")
        print(f"  Sample failures: {failed[:5]}")
        if len(failed) == len(codes):
            print("  !!! ALL fetches failed - likely IP block or kabutan.jp outage. Falling back to cache.")

    return market_caps
