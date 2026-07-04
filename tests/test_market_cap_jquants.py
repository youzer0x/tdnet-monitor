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


def test_normalize_alphanumeric_code_kept_as_is():
    # 現状の挙動：英字を含む5桁コード（例 285A0）は数字プレフィックスでないため
    # 末尾0が落ちず "285A0" のまま返る。TDnet 側は "285A" 表記なので、英数字コードは
    # fetch_tse_codes の突合で一致しない（＝この関数の既知の限界を固定化するテスト）。
    assert mc._normalize_code("285A0") == "285A0"
