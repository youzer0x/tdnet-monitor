"""market_cap_jquants の単体テスト（ネット非接触）。

market-scripts-common の同名テストのコピー（sync 対象外・手動同期）。HTTP は `_request` を monkeypatch して差し替え、
Yahoo フォールバックは market_cap_yahoo.fetch_market_cap_yahoo を差し替える。
"""
from datetime import date

import pytest

import market_cap_jquants as mc
import market_cap_yahoo


@pytest.fixture(autouse=True)
def _clear_caches():
    mc._PRICES_CACHE.clear()
    mc._VALUATION_CACHE.clear()
    yield
    mc._PRICES_CACHE.clear()
    mc._VALUATION_CACHE.clear()


def _fake_request(pages: dict[tuple[str, str], list[dict]], calls: list | None = None):
    """(path, date) → rows の辞書から _request の代替を作る。未登録は空リスト。"""
    def fake(api_key, path, params):
        if calls is not None:
            calls.append((path, params.get("date")))
        return pages.get((path, params.get("date")), [])
    return fake


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
    monkeypatch.setenv("JQUANTS_API_KEY", "x")
    monkeypatch.setattr(mc, "_fetch_close_prices",
                        lambda key, d: ({"72030": 1.0, "285A0": 2.0, "25935": 3.0}, d))
    assert mc.fetch_tse_codes(date(2026, 9, 17)) == {"7203", "285A", "25935"}


def test_fetch_tse_codes_without_api_key_is_empty(monkeypatch):
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    assert mc.fetch_tse_codes(date(2026, 9, 17)) == set()


# --- valuation API の MktCap（v2.0.0〜） ---

def test_mktcap_oku_converts_million_yen_to_oku():
    assert mc._mktcap_oku(1077137.0) == 10771.4   # 百万円 → 億円（小数1桁）
    assert mc._mktcap_oku(5) == 0.1
    assert mc._mktcap_oku(None) is None


def test_fetch_valuation_looks_back_and_skips_null(monkeypatch, capsys):
    d = date(2026, 9, 24)
    pages = {
        # 当日分はまだ無い（空）→ 前日を採用
        ("/equities/valuation", "2026-09-23"): [
            {"Code": "72030", "MktCap": 4500000.0},
            {"Code": "13050", "MktCap": None},    # ETF 等は null → 除外
        ],
    }
    monkeypatch.setattr(mc, "_request", _fake_request(pages))
    mcaps, used = mc._fetch_valuation_mktcaps("k", d)
    assert used == date(2026, 9, 23)
    assert mcaps == {"72030": 45000.0}
    # 前日終値ベースの値を採用したことはログで警告する
    assert "WARN" in capsys.readouterr().out


def test_fetch_valuation_same_day_has_no_warning(monkeypatch, capsys):
    d = date(2026, 9, 24)
    _setup_valuation(monkeypatch, d, [{"Code": "72030", "MktCap": 100.0}])
    mc._fetch_valuation_mktcaps("k", d)
    assert "WARN" not in capsys.readouterr().out


def test_fetch_valuation_uses_cache_on_second_call(monkeypatch):
    d = date(2026, 9, 24)
    calls: list = []
    pages = {("/equities/valuation", "2026-09-24"): [{"Code": "72030", "MktCap": 100.0}]}
    monkeypatch.setattr(mc, "_request", _fake_request(pages, calls))
    first = mc._fetch_valuation_mktcaps("k", d)
    second = mc._fetch_valuation_mktcaps("k", d)
    assert first == second == ({"72030": 1.0}, d)
    assert calls == [("/equities/valuation", "2026-09-24")]


def test_fetch_valuation_all_empty_returns_empty_and_caches(monkeypatch):
    d = date(2026, 9, 24)
    calls: list = []
    monkeypatch.setattr(mc, "_request", _fake_request({}, calls))
    assert mc._fetch_valuation_mktcaps("k", d) == ({}, d)
    n = len(calls)
    assert n == mc.LOOKBACK_DAYS + 1
    assert mc._fetch_valuation_mktcaps("k", d) == ({}, d)
    assert len(calls) == n   # 空もキャッシュし再取得しない


def _setup_valuation(monkeypatch, d: date, rows: list[dict]):
    pages = {("/equities/valuation", d.isoformat()): rows}
    monkeypatch.setattr(mc, "_request", _fake_request(pages))


def _forbid_yahoo(monkeypatch):
    def boom(code):
        raise AssertionError(f"Yahoo must not be called for {code}")
    monkeypatch.setattr(market_cap_yahoo, "fetch_market_cap_yahoo", boom)


def test_compute_one_uses_valuation_mktcap(monkeypatch):
    d = date(2026, 9, 24)
    _setup_valuation(monkeypatch, d, [{"Code": "72030", "MktCap": 4500000.0}])
    _forbid_yahoo(monkeypatch)
    prices = {"72030": 2800.0}
    # 株数・期末日は返さない（None）、corr は 1.0 固定（戻り値互換）
    assert mc.compute_one("k", "7203", prices, d) == (45000.0, None, None, 1.0, "jquants")


def test_compute_one_alphanumeric_code(monkeypatch):
    d = date(2026, 9, 24)
    _setup_valuation(monkeypatch, d, [{"Code": "285A0", "MktCap": 12340.0}])
    _forbid_yahoo(monkeypatch)
    assert mc.compute_one("k", "285A", {"285A0": 1000.0}, d) == (123.4, None, None, 1.0, "jquants")


def test_compute_one_non_tse_is_skipped(monkeypatch):
    d = date(2026, 9, 24)
    _setup_valuation(monkeypatch, d, [{"Code": "99990", "MktCap": 100.0}])
    _forbid_yahoo(monkeypatch)
    assert mc.compute_one("k", "9999", {"72030": 1.0}, d) == (None, None, None, 1.0, "skipped_non_tse")


def test_compute_one_null_mktcap_falls_back_to_yahoo(monkeypatch):
    d = date(2026, 9, 24)
    _setup_valuation(monkeypatch, d, [{"Code": "72030", "MktCap": 100.0},
                                      {"Code": "999A0", "MktCap": None}])
    monkeypatch.setattr(market_cap_yahoo, "fetch_market_cap_yahoo",
                        lambda code: 321.0 if code == "999A" else None)
    assert mc.compute_one("k", "999A", {"999A0": 500.0}, d) == (321.0, None, None, 1.0, "yahoo")


def test_compute_one_yahoo_failure_returns_none(monkeypatch):
    d = date(2026, 9, 24)
    _setup_valuation(monkeypatch, d, [{"Code": "72030", "MktCap": 100.0}])
    monkeypatch.setattr(market_cap_yahoo, "fetch_market_cap_yahoo", lambda code: None)
    assert mc.compute_one("k", "1234", {"12340": 500.0}, d) == (None, None, None, 1.0, None)


def test_compute_one_zero_mktcap_is_kept(monkeypatch):
    d = date(2026, 9, 24)
    _setup_valuation(monkeypatch, d, [{"Code": "72030", "MktCap": 0.0}])
    _forbid_yahoo(monkeypatch)
    assert mc.compute_one("k", "7203", {"72030": 1.0}, d) == (0.0, None, None, 1.0, "jquants")


def test_compute_one_valuation_error_does_not_hit_yahoo_nor_retry(monkeypatch):
    d = date(2026, 9, 24)
    calls: list = []

    def fail(api_key, path, params):
        calls.append(path)
        raise RuntimeError("valuation down")
    monkeypatch.setattr(mc, "_request", fail)
    _forbid_yahoo(monkeypatch)
    prices = {"72030": 1.0, "67580": 1.0}
    assert mc.compute_one("k", "7203", prices, d) == (None, None, None, 1.0, None)
    assert mc.compute_one("k", "6758", prices, d) == (None, None, None, 1.0, None)
    assert calls == ["/equities/valuation"]   # 失敗をキャッシュし銘柄ごとに再試行しない


def test_compute_one_empty_valuation_does_not_hit_yahoo(monkeypatch):
    d = date(2026, 9, 24)
    monkeypatch.setattr(mc, "_request", _fake_request({}))
    _forbid_yahoo(monkeypatch)
    assert mc.compute_one("k", "7203", {"72030": 1.0}, d) == (None, None, None, 1.0, None)


def test_fetch_market_caps_mixed(monkeypatch):
    d = date(2026, 9, 24)
    monkeypatch.setenv("JQUANTS_API_KEY", "k")
    pages = {
        ("/equities/bars/daily", "2026-09-24"): [
            {"Code": "72030", "AdjC": 2800.0},
            {"Code": "285A0", "AdjC": 1000.0},
            {"Code": "999A0", "AdjC": 500.0},
        ],
        ("/equities/valuation", "2026-09-24"): [
            {"Code": "72030", "MktCap": 4500000.0},
            {"Code": "285A0", "MktCap": 12340.0},
            {"Code": "999A0", "MktCap": None},
        ],
    }
    monkeypatch.setattr(mc, "_request", _fake_request(pages))
    monkeypatch.setattr(market_cap_yahoo, "fetch_market_cap_yahoo",
                        lambda code: 321.0 if code == "999A" else None)
    got = mc.fetch_market_caps({"7203", "285A", "999A", "9999"}, d)
    # 9999 は bars/daily に無い（非東証）→ 結果に含まれない
    assert got == {"7203": 45000.0, "285A": 123.4, "999A": 321.0}


def test_fetch_market_caps_valuation_error_returns_empty(monkeypatch):
    d = date(2026, 9, 24)
    monkeypatch.setenv("JQUANTS_API_KEY", "k")

    def fake(api_key, path, params):
        if path == "/equities/valuation":
            raise RuntimeError("valuation down")
        return [{"Code": "72030", "AdjC": 2800.0}]
    monkeypatch.setattr(mc, "_request", fake)
    _forbid_yahoo(monkeypatch)
    assert mc.fetch_market_caps({"7203"}, d) == {}


def test_fetch_market_caps_empty_valuation_returns_empty(monkeypatch):
    d = date(2026, 9, 24)
    monkeypatch.setenv("JQUANTS_API_KEY", "k")
    pages = {("/equities/bars/daily", "2026-09-24"): [{"Code": "72030", "AdjC": 2800.0}]}
    monkeypatch.setattr(mc, "_request", _fake_request(pages))
    _forbid_yahoo(monkeypatch)
    assert mc.fetch_market_caps({"7203"}, d) == {}


def test_fetch_market_caps_without_api_key_is_empty(monkeypatch):
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    assert mc.fetch_market_caps({"7203"}, date(2026, 9, 24)) == {}
