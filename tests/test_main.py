"""main.py の単体テスト。

純粋関数：retention_cutoff / is_market_open / filter_by_time / resolve_target_date /
          item_key / split_new_records / merge_records / select_notification / apply_notification
ファイル I/O（tmp_path）：load_daily_data / save_daily_data / save_daily_json /
          _load_cached_market_caps / cleanup_old_data / update_manifest / export_github_env
日付・時刻は固定値で渡す（date.today() / datetime.now() に依存させない）。
"""
import json
import os
from datetime import date, datetime

import pytest

import main
from html_generator import DisplayItem

JST = main.JST
TDNET = "https://www.release.tdnet.info/inbs/140120260917000001.pdf"
REL = "https://github.com/youzer0x/tdnet-monitor/releases/download/pdf-20260917/140120260917000001.pdf"


def _disp(code, mcap, time, title="開示", pdf=None):
    """save_daily_json 用の DisplayItem（pdf_url は既定でコード＋時刻から一意化）。"""
    return DisplayItem(code=code, company_name="会社" + code, market_cap=mcap,
                       time=time, title=title, pdf_url=pdf or f"https://x/{code}_{time}.pdf")


def _rec(code, mcap, time, title="開示", pdf=None, **extra):
    """JSON レコード（dict）。pdf は None なら TDnet 風の一意 URL。"""
    url = pdf if pdf is not None else f"https://www.release.tdnet.info/inbs/1401{code}{time.replace(':', '')}.pdf"
    r = {"code": code, "company_name": "会社" + code, "market_cap": mcap,
         "time": time, "title": title, "pdf_url": url}
    r.update(extra)
    return r


class _Timed:
    """filter_by_time 用の最小オブジェクト（.time だけ持てばよい）。"""
    def __init__(self, t):
        self.time = t


class _Discl:
    """disclosure_to_record 用の最小開示オブジェクト。"""
    def __init__(self, code, company_name, time, title, pdf_url):
        self.code, self.company_name, self.time, self.title, self.pdf_url = code, company_name, time, title, pdf_url


# ── 純粋関数 ────────────────────────────────────────────────
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


# ── 対象日の決定 ────────────────────────────────────────────
def test_resolve_target_date_night_before_17_rolls_back():
    for hh, mm in [(0, 10), (5, 30), (14, 30)]:
        now = datetime(2026, 9, 18, hh, mm, tzinfo=JST)
        assert main.resolve_target_date("night", now, None) == date(2026, 9, 17)


def test_resolve_target_date_night_at_or_after_17_same_day():
    for hh, mm in [(17, 0), (23, 59)]:
        now = datetime(2026, 9, 17, hh, mm, tzinfo=JST)
        assert main.resolve_target_date("night", now, None) == date(2026, 9, 17)


def test_resolve_target_date_evening_same_day():
    assert main.resolve_target_date("evening", datetime(2026, 9, 17, 17, 5, tzinfo=JST), None) == date(2026, 9, 17)
    assert main.resolve_target_date("evening", datetime(2026, 9, 18, 3, 0, tzinfo=JST), None) == date(2026, 9, 18)


def test_resolve_target_date_explicit_arg_wins():
    now = datetime(2026, 9, 18, 3, 0, tzinfo=JST)
    assert main.resolve_target_date("night", now, "2026-09-10") == date(2026, 9, 10)
    assert main.resolve_target_date("evening", now, "2026-09-10") == date(2026, 9, 10)


def test_export_github_env_appends_or_noop(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_ENV", raising=False)
    main.export_github_env("A", "1")                       # 未設定なら何もしない
    p = tmp_path / "github_env"
    monkeypatch.setenv("GITHUB_ENV", str(p))
    main.export_github_env("TARGET_DATE_RESOLVED", "2026-09-17")
    assert p.read_text(encoding="utf-8") == "TARGET_DATE_RESOLVED=2026-09-17\n"


# ── 同一性キー・追記・マージ ─────────────────────────────────
def test_item_key_same_for_tdnet_and_release_url():
    assert main.item_key({"pdf_url": TDNET}) == main.item_key({"pdf_url": REL}) == "140120260917000001"


def test_item_key_fallback_without_url():
    assert main.item_key({"code": "7203", "time": "09:00", "title": "T", "pdf_url": ""}) == "7203|09:00|T"


def test_split_new_records_by_pdf_id():
    existing = [_rec("7203", 1, "09:00", pdf=REL)]                       # 退避済み URL
    fetched = [_rec("7203", 0, "09:00", pdf=TDNET), _rec("6758", 0, "10:00")]  # 同じ書類を原本 URL で再取得
    assert [r["code"] for r in main.split_new_records(existing, fetched)] == ["6758"]


def test_split_new_records_urlless_existing_matches_by_code_time_title():
    existing = [_rec("2462", 1, "15:30", title="X", pdf="")]            # TDnet にリンクが無かった項目
    fetched = [_rec("2462", 0, "15:30", title="X")]                     # 後から URL 付きで取れても追加しない
    assert main.split_new_records(existing, fetched) == []


def test_split_new_records_same_title_distinct_ids_both_kept():
    fetched = [_rec("4626", 0, "15:00", title="同名", pdf="https://x/1.pdf"),
               _rec("4626", 0, "15:00", title="同名", pdf="https://x/2.pdf")]
    assert len(main.split_new_records([], fetched)) == 2


def test_split_new_records_dedups_within_fetch():
    fetched = [_rec("7203", 0, "09:00", pdf=TDNET), _rec("7203", 0, "09:00", pdf=TDNET)]
    assert len(main.split_new_records([], fetched)) == 1


def test_merge_records_dedup_by_pdf_id_and_sort():
    # 仕様変更（2026-09）: 重複判定は pdf_url の文字列一致ではなく TDnet の書類 ID で行う。
    # 夕方に退避して Release URL に書き換わった開示を、深夜に原本 URL で取り直しても1件と見なす。
    existing = [_rec("7203", 400000, "09:30", title="既存", pdf=REL),
                _rec("2462", 100, "15:30", pdf="", pdf_expired=True)]
    fetched = [_rec("7203", 0, "09:30", title="既存", pdf=TDNET),   # 重複（ID 一致）
               _rec("6758", 0, "10:00", pdf="https://x/b.pdf")]      # 新規
    new = main.split_new_records(existing, fetched)
    for r in new:
        r["market_cap"] = 600000
    merged = main.merge_records(existing, new)
    assert [m["code"] for m in merged] == ["6758", "7203", "2462"]   # 時価総額降順
    assert merged[1]["pdf_url"] == REL                                # 既存の退避済み URL を保持
    assert merged[2]["pdf_expired"] is True                           # 既存の付加情報を保持


def test_disclosure_to_record():
    d = _Discl("7203", "トヨタ", "09:00", "T", TDNET)
    assert main.disclosure_to_record(d) == {
        "code": "7203", "company_name": "トヨタ", "market_cap": 0,
        "time": "09:00", "title": "T", "pdf_url": TDNET,
    }


def test_records_to_display_items_order_and_email_url():
    recs = [_rec("7203", 100, "09:00", pdf=REL), _rec("9999", 0, "11:00", pdf="")]
    items = main.records_to_display_items(recs)
    assert [i.code for i in items] == ["7203", "9999"]
    assert isinstance(items[0], DisplayItem) and items[0].pdf_url == REL and items[1].pdf_url == ""
    email = main.records_to_display_items(recs, for_email=True)
    assert email[0].pdf_url == TDNET     # メールは原本 URL（ブラウザ内表示）に再構成
    assert email[1].pdf_url == ""


# ── 日次 JSON の読み書き（tmp_path）────────────────────────
def test_load_daily_data_missing_file_skeleton(tmp_path):
    d = main.load_daily_data(str(tmp_path / "2026-09-17.json"), date(2026, 9, 17))
    assert d == {"date": "2026-09-17", "items": [], "notified": {}}


def test_save_daily_data_roundtrip_preserves_top_level_keys(tmp_path):
    p = tmp_path / "2026-09-17.json"
    data = {"date": "2026-09-17",
            "items": [_rec("7203", 1, "09:00"), _rec("7203", 1, "10:00")],
            "tdnet_available": True, "notified": {"evening": True}}
    main.save_daily_data(str(p), data)
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert list(saved)[:4] == ["date", "company_count", "total_count", "items"]
    assert saved["company_count"] == 1 and saved["total_count"] == 2
    assert saved["tdnet_available"] is True and saved["notified"] == {"evening": True}
    assert main.load_daily_data(str(p))["notified"] == {"evening": True}


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


def test_save_daily_json_wrapper_keeps_existing_top_level_keys(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    p = data_dir / "2026-07-03.json"
    p.write_text(json.dumps({"date": "2026-07-03", "items": [],
                             "tdnet_available": False, "notified": {"night": True}}), encoding="utf-8")
    main.save_daily_json([_disp("7203", 1, "09:00")], date(2026, 7, 3), str(tmp_path))
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["total_count"] == 1
    assert saved["tdnet_available"] is False and saved["notified"] == {"night": True}


def test_load_existing_json_missing_file_returns_empty(tmp_path):
    assert main.load_existing_json(str(tmp_path / "nope.json")) == []


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


# ── 通知判定 ────────────────────────────────────────────────
def _data(pending_codes, notified, extra_codes=()):
    items = ([_rec(c, 10, "09:00", pending_notify=True) for c in pending_codes]
             + [_rec(c, 10, "10:00") for c in extra_codes])
    return {"date": "2026-09-17", "items": items, "notified": dict(notified)}


def test_select_notification_none_when_no_pending():
    d = main.select_notification(_data([], {}, extra_codes=["7203"]), "evening", True)
    assert d.action == "none" and d.items == []


def test_select_notification_evening_sends_top30():
    d = main.select_notification(_data(["7203", "6758"], {}), "evening", True)
    assert d.action == "send" and d.max_items == 30 and d.subject_suffix == ""
    assert d.mark == {"evening": True}
    assert {r["code"] for r in d.items} == {"7203", "6758"}


def test_select_notification_clears_when_already_notified():
    d = main.select_notification(_data(["7203"], {"evening": True, "night": True}), "night", True)
    assert d.action == "clear" and d.mark == {} and len(d.items) == 1


def test_select_notification_send_email_off_marks_notified():
    d = main.select_notification(_data(["7203"], {}), "night", False)
    assert d.action == "clear" and d.mark == {"night": True}


def test_select_notification_night_normal_uncapped():
    d = main.select_notification(_data(["7203"], {"evening": True}), "night", True)
    assert d.action == "send" and d.max_items is None
    assert d.subject_suffix == "（夜間更新分）" and d.mark == {"night": True}


def test_select_notification_night_compensates_when_evening_missing():
    d = main.select_notification(_data(["7203"], {}), "night", True)
    assert d.action == "send" and d.max_items == 30
    assert "夕方分を補完" in d.subject_suffix
    assert d.mark == {"evening": True, "night": True}


def test_apply_notification_strips_pending_and_sets_flags():
    data = _data(["7203"], {"evening": True}, extra_codes=["6758"])
    out = main.apply_notification(data, main.select_notification(data, "night", True))
    assert all("pending_notify" not in r for r in out["items"])
    assert out["notified"] == {"evening": True, "night": True}


def test_backup_night_run_is_silent_after_first_run_notified():
    # 1回目の night が送信済み → 予備は何もしない。遅れて見つかった追加分は記録のみ。
    data = _data(["7203"], {"evening": True})
    data = main.apply_notification(data, main.select_notification(data, "night", True))
    assert main.select_notification(data, "night", True).action == "none"
    data["items"].append(_rec("6758", 1, "23:00", pending_notify=True))
    late = main.select_notification(data, "night", True)
    assert late.action == "clear" and late.mark == {}


def test_backup_night_run_resends_when_first_run_saved_but_did_not_notify():
    # 1回目が記録後・送信前に落ちた → pending が残り night 未通知 → 予備が送る
    data = _data(["7203"], {"evening": True})
    d = main.select_notification(data, "night", True)
    assert d.action == "send" and [r["code"] for r in d.items] == ["7203"]


@pytest.mark.parametrize("outcome, expected", [
    ("failure", "⚠テスト失敗 "),
    ("success", ""),
    ("skipped", ""),
    (None, ""),   # ローカル実行・手動実行で PYTEST_OUTCOME 未設定
    ("", ""),
])
def test_gate_warning_prefix_only_on_failure(outcome, expected):
    assert main.gate_warning_prefix(outcome) == expected
