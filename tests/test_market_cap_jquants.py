"""market_cap_jquants._normalize_code の単体テスト（純粋関数・ネット非接触）。

J-Quants の5桁コードを TDnet 表記へ正規化する。ネット依存の時価総額取得
（fetch_market_caps 等）はテスト対象外。
"""
import market_cap_jquants as mc


def test_normalize_5digit_numeric():
    assert mc._normalize_code("72030") == "7203"   # 末尾0を落として4桁
    assert mc._normalize_code("97600") == "9760"


def test_normalize_already_4digit():
    assert mc._normalize_code("7203") == "7203"     # 5桁でなければそのまま


def test_normalize_alphanumeric_code_strips_reserved_zero():
    # 新方式の英数字コード（例 285A）も J-Quants では末尾に予約桁 0 が付く（285A0）。
    # TDnet 側は "285A" 表記なので末尾 0 を外す（jquants.code4 と同一）。以前は "285A0" の
    # まま返しており、fetch_tse_codes の突合で英字コード銘柄が全件除外されていた（仕様変更）。
    assert mc._normalize_code("285A0") == "285A"
    assert mc._normalize_code("133A0") == "133A"


def test_normalize_5digit_not_ending_in_zero_kept():
    assert mc._normalize_code("25935") == "25935"   # 優先株等の 5 桁コードは不変


def test_fetch_tse_codes_normalizes_alphanumeric(monkeypatch):
    # 公開関数の挙動を固定: bars/daily の 5 桁コードを TDnet 表記に正規化した集合を返す。
    from datetime import date
    monkeypatch.setenv("JQUANTS_API_KEY", "x")
    monkeypatch.setattr(mc, "_fetch_close_prices",
                        lambda key, d: ({"72030": 1.0, "285A0": 2.0, "25935": 3.0}, d))
    assert mc.fetch_tse_codes(date(2026, 9, 17)) == {"7203", "285A", "25935"}


def test_fetch_tse_codes_without_api_key_is_empty(monkeypatch):
    from datetime import date
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    assert mc.fetch_tse_codes(date(2026, 9, 17)) == set()
