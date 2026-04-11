"""時価総額データの取得 (J-Quants API V2)

J-Quants API V2 (JPX公式) から時価総額を取得する。
V2 では API キーによる認証に変更されている。
Free プランで利用可能。
"""

import os
import requests


def _get_headers() -> dict[str, str]:
    """J-Quants API V2 の認証ヘッダーを返す"""
    api_key = os.environ.get("JQUANTS_API_KEY", "")

    if not api_key:
        raise RuntimeError(
            "環境変数 JQUANTS_API_KEY が設定されていません。"
            "J-Quants ダッシュボードから API キーを取得し、"
            "GitHub Secrets に JQUANTS_API_KEY として登録してください。"
        )

    return {"Authorization": f"Bearer {api_key}"}


def fetch_market_caps(codes: set[str]) -> dict[str, float]:
    """
    証券コードのセットを受け取り、{code: 時価総額(億円)} の辞書を返す。

    J-Quants API V2 の /v1/prices/daily_quotes エンドポイントを使用。
    Free プランでは株価データに2営業日の遅延がある。
    """
    print("  Authenticating with J-Quants API V2...")
    headers = _get_headers()

    # 全銘柄の直近株価を一括取得（ページネーション対応）
    print("  Fetching daily quotes for market cap...")
    all_quotes = []
    pagination_key = None
    page_count = 0

    while True:
        params = {}
        if pagination_key:
            params["pagination_key"] = pagination_key

        resp = requests.get(
            "https://api.jquants.com/v1/prices/daily_quotes",
            headers=headers,
            params=params,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        quotes = data.get("daily_quotes", [])
        all_quotes.extend(quotes)
        page_count += 1

        pagination_key = data.get("pagination_key")
        if not pagination_key:
            break

        if page_count % 5 == 0:
            print(f"    ... fetched {len(all_quotes)} quotes so far")

    print(f"  Total quotes fetched: {len(all_quotes)}")

    # 各銘柄の時価総額を取得
    market_caps: dict[str, float] = {}
    for q in all_quotes:
        c = str(q.get("Code", ""))[:4]
        if c in codes:
            mcap = q.get("MarketCapitalization")
            if mcap is not None:
                # 億円に変換（元データは円）
                market_caps[c] = round(mcap / 1_0000_0000, 1)

    print(f"  Market caps resolved: {len(market_caps)} / {len(codes)} codes")
    return market_caps
