"""filter_reit_etf の単体テスト（ネット非接触）。

JPX からの xlsx 取得（_fetch_from_xlsx）はネット依存なので対象外。行解析（_parse_rows）と
キャッシュ・フォールバック（get_excluded_codes / save_cache / load_cache）、絞り込み
（filter_disclosures）を検証する。日付は固定値を渡す。
"""
import json
from datetime import date

import filter_reit_etf as f


class _D:
    """.code だけ持てばよい最小の開示オブジェクト。"""
    def __init__(self, code):
        self.code = code


# 現行 xlsx と同じヘッダー
_HEADER = ("日付", "コード", "銘柄名", "市場・商品区分", "33業種コード", "33業種区分",
           "17業種コード", "17業種区分", "規模コード", "規模区分")


def _row(code, name, segment):
    return ("20260918", code, name, segment, "-", "-", "-", "-", "-", "-")


# ── _parse_rows ─────────────────────────────────────────────
def test_parse_rows_matches_segment_keywords_and_normalizes_cell_types():
    rows = [
        _row(1326, "ＳＰＤＲゴールド・シェア", "ETF・ETN"),                 # int セル
        _row(2989.0, "東海道リート投資法人",
             "REIT・ベンチャーファンド・カントリーファンド・インフラファンド"),  # float セル
        _row("443A", "ｉＦｒｅｅＥＴＦ 東証ＲＥＩＴ指数", "ETF・ETN"),          # 英字コード
        _row("8500", "某金庫", "出資証券"),
        _row(7203, "トヨタ自動車", "プライム（内国株式）"),                  # 除外しない
        _row("133A", "某社", "グロース（内国株式）"),                        # 除外しない
        _row(1234, "某社", "PRO Market"),                                    # 除外しない（東証本則フィルタが担当）
    ]
    assert f._parse_rows(_HEADER, rows) == {"1326", "2989", "443A", "8500"}


def test_parse_rows_falls_back_to_default_columns_when_header_unknown():
    header = ("a", "b", "c", "d")
    rows = [("x", 1326, "ETF", "ETF・ETN"), ("x", 7203, "トヨタ", "プライム（内国株式）")]
    assert f._parse_rows(header, rows) == {"1326"}


def test_parse_rows_skips_short_and_none_rows():
    rows = [None, ("20260918",), _row(1326, "ETF", "ETF・ETN")]
    assert f._parse_rows(_HEADER, rows) == {"1326"}


# ── キャッシュ ─────────────────────────────────────────────
def test_save_cache_writes_only_when_codes_change(tmp_path):
    path = tmp_path / "cache" / "jpx_excluded.json"
    assert f.save_cache({"1326", "2989"}, str(path), today=date(2026, 9, 18)) is True
    assert f.load_cache(str(path)) == ({"1326", "2989"}, "2026-09-18")

    # 同じ集合なら書き換えない（fetched_at も据え置き）
    assert f.save_cache({"2989", "1326"}, str(path), today=date(2026, 9, 19)) is False
    assert f.load_cache(str(path))[1] == "2026-09-18"

    # 変化したら書き換える
    assert f.save_cache({"1326"}, str(path), today=date(2026, 9, 20)) is True
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["codes"] == ["1326"] and saved["fetched_at"] == "2026-09-20" and saved["count"] == 1


def test_load_cache_missing_or_broken_file(tmp_path):
    assert f.load_cache(str(tmp_path / "nope.json")) == (set(), None)
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert f.load_cache(str(broken)) == (set(), None)


# ── get_excluded_codes（取得関数を注入） ───────────────────
def test_get_excluded_codes_fetch_success_updates_cache(tmp_path):
    path = tmp_path / "jpx_excluded.json"
    out = f.get_excluded_codes(str(path), fetch=lambda: {"1326", "443A"}, today=date(2026, 9, 18))
    assert out == {"1326", "443A"}
    assert f.load_cache(str(path)) == ({"1326", "443A"}, "2026-09-18")


def test_get_excluded_codes_uses_cache_when_fetch_raises(tmp_path):
    path = tmp_path / "jpx_excluded.json"
    f.save_cache({"1326"}, str(path), today=date(2026, 9, 1))

    def _boom():
        raise RuntimeError("404")

    assert f.get_excluded_codes(str(path), fetch=_boom) == {"1326"}
    assert f.load_cache(str(path))[1] == "2026-09-01"   # 失敗時はキャッシュを触らない


def test_get_excluded_codes_uses_cache_when_fetch_returns_empty(tmp_path):
    path = tmp_path / "jpx_excluded.json"
    f.save_cache({"1326"}, str(path), today=date(2026, 9, 1))
    assert f.get_excluded_codes(str(path), fetch=lambda: set()) == {"1326"}


def test_get_excluded_codes_empty_when_no_cache_and_fetch_fails(tmp_path):
    def _boom():
        raise RuntimeError("404")

    assert f.get_excluded_codes(str(tmp_path / "none.json"), fetch=_boom) == set()


# ── filter_disclosures ─────────────────────────────────────
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
