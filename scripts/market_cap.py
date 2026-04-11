"""時価総額データの取得 (J-Quants API)

J-Quants API (JPX公式) から銘柄情報・時価総額を取得する。
Free プランで利用可能。
"""

import os
import requests


def _get_id_token() -> str:
    """J-Quants API の認証トークンを取得する"""
    email = os.environ.get("JQUANTS_EMAIL", "")
    password = os.environ.get("JQUANTS_PASSWORD", "")

    if not email or not password:
        raise RuntimeError(
            "環境変数 JQUANTS_EMAIL / JQUANTS_PASSWORD が設定されていません"
        )

    # Step 1: リフレッシュトークン取得
    resp = requests.post(
        "https://api.jquants.com/v1/token/auth_user",
        json={"mailaddress": email, "password": password},
        timeout=30,
    )
    resp.raise_for_status()
    refresh_token = resp.json()["refreshToken"]

    # Step 2: ID トークン取得
    resp = requests.post(
        f"https://api.jquants.com/v1/token/auth_refresh?refreshtoken={refresh_token}",
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["idToken"]


def fetch_market_caps(codes: set[str]) -> dict[str, float]:
    """
    証券コードのセットを受け取り、{code: 時価総額(億円)} の辞書を返す。

    J-Quants API の /v1/listed/info エンドポイントで全銘柄情報を取得し、
    MarketCapitalization フィールドを使用する。
    Free プランでは株価データに2営業日遅延があるため、
    /v1/prices/daily_quotes から直近の時価総額を取得する。
    """
    print("  Authenticating with J-Quants API...")
    id_token = _get_id_token()
    headers = {"Authorization": f"Bearer {id_token}"}

    # 全銘柄の株価情報を取得（直近日付）
    # listed/info から時価総額は直接取れないため、
    # prices/daily_quotes を使う
    market_caps: dict[str, float] = {}

    # まず listed/info で全銘柄情報を取得
    print("  Fetching listed info...")
    resp = requests.get(
        "https://api.jquants.com/v1/listed/info",
        headers=headers,
        timeout=60,
    )
    resp.raise_for_status()
    info_list = resp.json().get("info", [])

    # コードから銘柄名のマッピングも構築
    code_to_name: dict[str, str] = {}
    for item in info_list:
        c = str(item.get("Code", ""))[:4]
        code_to_name[c] = item.get("CompanyName", "")

    # 個別に株価を取得すると API 制限に引っかかるため、
    # 全銘柄の直近株価を一括取得
    print("  Fetching daily quotes for market cap...")

    # 日付指定なしで最新を取得（Free プランは2営業日遅延）
    # ページネーション対応
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

    # 各銘柄の最新時価総額を取得
    for q in all_quotes:
        c = str(q.get("Code", ""))[:4]
        if c in codes:
            mcap = q.get("MarketCapitalization")
            if mcap is not None:
                # 億円に変換（元データは円）
                market_caps[c] = round(mcap / 1_0000_0000, 1)

    print(f"  Market caps resolved: {len(market_caps)} / {len(codes)} codes")
    return market_caps
