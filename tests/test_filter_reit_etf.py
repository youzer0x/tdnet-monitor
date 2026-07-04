"""filter_reit_etf.filter_disclosures の単体テスト（純粋関数・ネット非接触）。

get_excluded_codes（JPX からの一覧取得）はネット依存なのでテスト対象外。
除外コード集合を与えたときの絞り込みロジックのみを検証する。
"""
import filter_reit_etf as f


class _D:
    """.code だけ持てばよい最小の開示オブジェクト。"""
    def __init__(self, code):
        self.code = code


def test_filter_disclosures_removes_excluded_codes():
    disclosures = [_D("7203"), _D("1234"), _D("6758")]
    out = f.filter_disclosures(disclosures, {"1234"})
    assert [d.code for d in out] == ["7203", "6758"]


def test_filter_disclosures_empty_exclusion_keeps_all():
    disclosures = [_D("7203"), _D("6758")]
    out = f.filter_disclosures(disclosures, set())
    assert len(out) == 2


def test_filter_disclosures_empty_input():
    assert f.filter_disclosures([], {"1234"}) == []
