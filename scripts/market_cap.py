"""時価総額データの取得 (Yahoo Finance Japan)

Yahoo Finance Japan の個別銘柄ページから時価総額を取得する。
API キー不要、リアルタイムデータ。
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed


def _fetch_single(code: str) -> tuple[str, float | None]:
    """1銘柄の時価総額を Yahoo Finance Japan から取得する"""
    url = f"https://finance.yahoo.co.jp/quote/{code}.T"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return code, None

        soup = BeautifulSoup(resp.text, "lxml")
        text = soup.get_text()

        # "時価総額" の後に来る数値パターンを検索
        # パターン例: "時価総額 1,234億円" / "時価総額 1.5兆円" / "時価総額 12,345百万円"
        patterns = [
            # 兆 + 億 パターン: "1兆2,345億円"
            r"時価総額[^\d]{0,20}?([\d,]+(?:\.\d+)?)\s*兆\s*([\d,]+)\s*億",
            # 兆のみ: "1.5兆円"
            r"時価総額[^\d]{0,20}?([\d,]+(?:\.\d+)?)\s*兆",
            # 億のみ: "1,234億円"
            r"時価総額[^\d]{0,20}?([\d,]+(?:\.\d+)?)\s*億",
            # 百万: "12,345百万円"
            r"時価総額[^\d]{0,20}?([\d,]+(?:\.\d+)?)\s*百万",
        ]

        for i, pat in enumerate(patterns):
            match = re.search(pat, text)
            if match:
                if i == 0:
                    # 兆+億
                    cho = float(match.group(1).replace(",", ""))
                    oku = float(match.group(2).replace(",", ""))
                    return code, round(cho * 10000 + oku, 1)
                elif i == 1:
                    # 兆のみ
                    return code, round(float(match.group(1).replace(",", "")) * 10000, 1)
                elif i == 2:
                    # 億
                    return code, round(float(match.group(1).replace(",", "")), 1)
                elif i == 3:
                    # 百万 → 億
                    return code, round(float(match.group(1).replace(",", "")) / 100, 1)

    except Exception:
        pass

    return code, None


def fetch_market_caps(codes: set[str]) -> dict[str, float]:
    """
    証券コードのセットを受け取り、{code: 時価総額(億円)} の辞書を返す。
    Yahoo Finance Japan から取得。並列処理で高速化。
    """
    print(f"  Fetching market caps for {len(codes)} codes from Yahoo Finance...")
    market_caps: dict[str, float] = {}
    failed: list[str] = []

    sorted_codes = sorted(codes)

    # 並列5スレッドで取得（過度なアクセスを避ける）
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {}
        for code in sorted_codes:
            future = executor.submit(_fetch_single, code)
            futures[future] = code
            time.sleep(0.1)  # submit 間隔

        done_count = 0
        for future in as_completed(futures):
            code, mcap = future.result()
            done_count += 1
            if mcap is not None:
                market_caps[code] = mcap
            else:
                failed.append(code)

            if done_count % 50 == 0:
                print(f"    ... {done_count}/{len(sorted_codes)} processed")

    print(f"  Market caps resolved: {len(market_caps)} / {len(codes)} codes")
    if failed:
        print(f"  Failed to fetch: {len(failed)} codes (first 10: {failed[:10]})")

    return market_caps
