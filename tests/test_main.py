"""main.py の単体テスト。

第1波（純粋関数）：retention_cutoff / is_market_open / filter_by_time
第2波（ファイル I/O・tmp_path）：load/save 往復 / _load_cached_market_caps /
                                 cleanup_old_data / update_manifest / merge_items
日付・時刻は固定値で渡す（date.today() に依存させない）。
"""
import json
from datetime import date

import pytest

import main
from html_generator import DisplayItem


def _disp(code, mcap, time, title="開示", pdf=None):
    """save/merge 用の DisplayItem（pdf_url は既定でコード＋時刻から一意化）。"""
    return DisplayItem(code=code, company_name="会社" + code, market_cap=mcap,
                       time=time, title=title, pdf_url=pdf or f"https://x/{code}_{time}.pdf")


class _Timed:
    """filter_by_time 用の最小オブジェクト（.time だけ持てばよい）。"""
    def __init__(self, t):
        self.time = t


# ── 第1波：純粋関数 ────────────────────────────────────────────
def test_retention_cutoff_is_90_days_before():
    assert main.retention_cutoff(date(2026, 7, 4)) == date(2026, 4, 5)   # 90日前
    assert main.RETAIN_DAYS == 90


def test_is_market_open_weekday():
    assert main.is_market_open(date(2026, 7, 3)) is True   # 金


def test_is_market_open_weekend():
    assert main.is_market_open(date(2026, 7, 4)) is False  # 土
    assert main.is_market_open(date(2026, 7, 5)) is False  # 日


def test_is_market_open_holiday():
    assert main.is_market_open(date(2026, 7, 20)) is False  # 海の日


def test_is_market_open_year_end_new_year():
    for d in [date(2026, 12, 31), date(2027, 1, 1), date(2027, 1, 2), date(2027, 1, 3)]:
        assert main.is_market_open(d) is False


def test_filter_by_time_inclusive_bounds():
    items = [_Timed("09:00"), _Timed("17:00"), _Timed("17:30")]
    out = main.filter_by_time(items, "00:00", "17:00")
    # 境界（17:00 ちょうど）は含み、17:30 は除外
    assert [d.time for d in out] == ["09:00", "17:00"]


# ── 第2波：ファイル I/O（tmp_path）─────────────────────────────
def test_save_and_load_json_roundtrip(tmp_path):
    items = [_disp("7203", 400000, "09:30"), _disp("6758", 200000, "10:00")]
    target = date(2026, 7, 3)
    main.save_daily_json(items, target, str(tmp_path))

    json_path = tmp_path / "data" / "2026-07-03.json"
    assert json_path.exists()
    loaded = main.load_existing_json(str(json_path))
    assert [r["code"] for r in loaded] == ["7203", "6758"]
    assert loaded[0]["market_cap"] == 400000

    saved = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved["company_count"] == 2 and saved["total_count"] == 2


def test_load_existing_json_missing_file_returns_empty(tmp_path):
    assert main.load_existing_json(str(tmp_path / "nope.json")) == []


def test_merge_items_dedup_by_pdf_url_and_sort(tmp_path):
    existing = [{"code": "7203", "company_name": "トヨタ", "market_cap": 400000,
                 "time": "09:30", "title": "既存", "pdf_url": "https://x/a.pdf"}]
    new_items = [
        _disp("7203", 400000, "09:30", pdf="https://x/a.pdf"),   # 重複（pdf_url 一致）
        _disp("6758", 600000, "10:00", pdf="https://x/b.pdf"),   # 新規・時価総額最大
    ]
    merged = main.merge_items(existing, new_items)
    assert len(merged) == 2                       # 重複は追加されない
    assert merged[0].code == "6758"               # 時価総額降順で先頭
    assert [m.pdf_url for m in merged] == ["https://x/b.pdf", "https://x/a.pdf"]


def test_load_cached_market_caps_newest_wins_and_excludes_target(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    def _write(name, items):
        (data_dir / name).write_text(
            json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")

    _write("2026-07-01.json", [{"code": "7203", "market_cap": 100},
                               {"code": "6758", "market_cap": 30}])
    _write("2026-07-02.json", [{"code": "7203", "market_cap": 200}])   # 新しい方が優先
    _write("2026-07-03.json", [{"code": "7203", "market_cap": 999}])   # target 自身は除外
    _write("manifest.json", {"dates": []})                             # manifest は無視

    cache = main._load_cached_market_caps(str(data_dir), date(2026, 7, 3))
    assert cache == {"7203": 200, "6758": 30}


def test_cleanup_old_data_removes_before_cutoff(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for name in ["2026-06-01.json", "2026-07-01.json", "2026-07-03.json", "manifest.json"]:
        (data_dir / name).write_text("{}", encoding="utf-8")

    main.cleanup_old_data(str(tmp_path), date(2026, 7, 1))
    remaining = sorted(p.name for p in data_dir.glob("*.json"))
    # 07-01 以降は残り、06-01 は削除、manifest は常に残る
    assert remaining == ["2026-07-01.json", "2026-07-03.json", "manifest.json"]


def test_update_manifest_lists_dates_descending(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for name in ["2026-07-01.json", "2026-07-03.json", "2026-07-02.json"]:
        (data_dir / name).write_text("{}", encoding="utf-8")

    dates = main.update_manifest(str(tmp_path))
    assert dates == ["2026-07-03", "2026-07-02", "2026-07-01"]
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dates"] == dates
