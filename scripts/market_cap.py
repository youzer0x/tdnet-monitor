"""時価総額データの取得 (J-Quants API V2)

公式 Python クライアント (jquants-api-client) の ClientV2 を使用。
V2 では API キー認証（x-api-key ヘッダー）を採用。
Free プランで利用可能。

時価総額は銘柄一覧の発行済株式数 × 日足終値から算出する。
"""

import os
from datetime import datetime, timedelta
from dateutil import tz
import jquantsapi


def fetch_market_caps(codes: set[str]) -> dict[str, float]:
    """
    証券コードのセットを受け取り、{code: 時価総額(億円)} の辞書を返す。
    """
    api_key = os.environ.get("JQUANTS_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "環境変数 JQUANTS_API_KEY が設定されていません。"
            "J-Quants ダッシュボードから API キーを取得し、"
            "GitHub Secrets に JQUANTS_API_KEY として登録してください。"
        )

    print("  Initializing J-Quants API V2 client...")
    cli = jquantsapi.ClientV2(api_key=api_key)

    # 銘柄一覧を取得（発行済株式数を含む）
    print("  Fetching listed info...")
    try:
        df_list = cli.get_list()
    except Exception as e:
        print(f"  Error fetching listed info: {e}")
        return {}

    # 直近の株価を取得（Free プランは12週間遅延）
    # 直近5営業日分を取得して最新を使う
    jst = tz.gettz("Asia/Tokyo")
    end_dt = datetime.now(jst)
    start_dt = end_dt - timedelta(days=90)  # Free プランの遅延を考慮

    print("  Fetching daily quotes...")
    try:
        df_prices = cli.get_eq_bars_daily_range(
            start_dt=start_dt,
            end_dt=end_dt,
        )
    except Exception as e:
        print(f"  Error fetching daily quotes: {e}")
        # 株価取得に失敗した場合、銘柄一覧だけで時価総額を推定
        df_prices = None

    market_caps: dict[str, float] = {}

    if df_prices is not None and not df_prices.empty:
        # MarketCapitalization 列が存在する場合はそれを使用
        if "MarketCapitalization" in df_prices.columns:
            print("  Using MarketCapitalization from daily quotes...")
            # 各銘柄の最新日のデータを使用
            for code in codes:
                code5 = code + "0"  # J-Quants は5桁コード
                mask = df_prices["Code"].astype(str).str.startswith(code)
                subset = df_prices[mask]
                if not subset.empty:
                    latest = subset.sort_values("Date").iloc[-1]
                    mcap = latest.get("MarketCapitalization")
                    if mcap and mcap > 0:
                        market_caps[code] = round(mcap / 1_0000_0000, 1)
        else:
            # MarketCapitalization がない場合: 終値 × 発行済株式数 で計算
            print("  Calculating market cap from price × shares...")
            # 銘柄一覧から発行済株式数を取得
            shares_map: dict[str, float] = {}
            if df_list is not None and not df_list.empty:
                for _, row in df_list.iterrows():
                    c = str(row.get("Code", ""))[:4]
                    shares = row.get("IssuedShares") or row.get("NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock")
                    if shares and c in codes:
                        try:
                            shares_map[c] = float(shares)
                        except (ValueError, TypeError):
                            pass

            # 各銘柄の最新終値を取得
            for code in codes:
                mask = df_prices["Code"].astype(str).str.startswith(code)
                subset = df_prices[mask]
                if not subset.empty:
                    latest = subset.sort_values("Date").iloc[-1]
                    close = latest.get("Close") or latest.get("AdjustmentClose")
                    shares = shares_map.get(code)
                    if close and shares and close > 0 and shares > 0:
                        mcap_yen = float(close) * float(shares)
                        market_caps[code] = round(mcap_yen / 1_0000_0000, 1)

    print(f"  Market caps resolved: {len(market_caps)} / {len(codes)} codes")
    return market_caps
