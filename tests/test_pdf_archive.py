"""pdf_archive.py の単体テスト（ネット非接触・gh 非依存）。

対象：pdf_id / _is_transient / _needs_mirror / remirror_recent（対象選定）/ _run_gh（再試行）。
GitHub Releases への実際の退避（mirror_json_file 等）は gh とネットに依存するため対象外。
"""
import json
import os
import subprocess
from datetime import date

import pdf_archive as pa

TDNET = "https://www.release.tdnet.info/inbs/140120260917000001.pdf"
REL = "https://github.com/o/r/releases/download/pdf-20260917/140120260917000001.pdf"


def test_pdf_id_strips_path_and_extension():
    assert pa.pdf_id(TDNET) == "140120260917000001"
    assert pa.pdf_id(REL + "?x=1") == "140120260917000001"
    assert pa.pdf_id("") is None
    assert pa._pdf_id is pa.pdf_id   # 後方互換 alias


def test_is_transient_true_for_5xx_and_rate_limit_and_network():
    for blob in ["HTTP 503: No server is currently available to service your request.",
                 "HTTP 502: Bad Gateway",
                 "You have exceeded a secondary rate limit",
                 "API rate limit exceeded for user",
                 "read: connection reset by peer"]:
        assert pa._is_transient(blob) is True, blob


def test_is_transient_false_for_permanent_errors():
    for blob in ["release not found", "HTTP 404: Not Found", "HTTP 422: Validation Failed", ""]:
        assert pa._is_transient(blob) is False, blob


def test_needs_mirror():
    assert pa._needs_mirror({"items": [{"pdf_url": TDNET}]}) is True
    assert pa._needs_mirror({"items": [{"pdf_url": REL}, {"pdf_url": "", "pdf_expired": True}]}) is False
    assert pa._needs_mirror({"items": []}) is False


def test_remirror_recent_selects_window_and_tdnet_only(tmp_path, monkeypatch):
    def _w(name, url):
        (tmp_path / name).write_text(json.dumps({"date": name[:-5], "items": [{"pdf_url": url}]}),
                                     encoding="utf-8")

    _w("2026-09-17.json", TDNET)   # today → 対象外（当日分は main が処理する）
    _w("2026-09-16.json", TDNET)   # 対象
    _w("2026-09-15.json", REL)     # 退避済み → 通信しない
    _w("2026-09-01.json", TDNET)   # 窓の外
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")

    calls = []

    def _fake_mirror(fp, repo=None):
        calls.append(os.path.basename(fp))
        return {"archived": 1, "already": 0, "expired": 0, "error": 0, "skip": 0}

    monkeypatch.setattr(pa, "mirror_json_file", _fake_mirror)
    st = pa.remirror_recent(str(tmp_path), today=date(2026, 9, 17), lookback_days=10)
    assert calls == ["2026-09-16.json"]
    assert st == {"checked": 2, "mirrored": 1, "archived": 1, "error": 0}


def test_run_gh_retries_on_transient_then_succeeds(monkeypatch):
    results = [subprocess.CompletedProcess(["gh"], 1, "", "HTTP 503: No server is currently available"),
               subprocess.CompletedProcess(["gh"], 0, "ok", "")]
    monkeypatch.setattr(pa.subprocess, "run", lambda cmd, **kw: results.pop(0))
    sleeps = []
    monkeypatch.setattr(pa.time, "sleep", lambda s: sleeps.append(s))
    res = pa._run_gh(["gh", "x"], "x")
    assert res.returncode == 0 and sleeps == [30]


def test_run_gh_does_not_retry_on_permanent_error(monkeypatch):
    calls = []

    def _run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "release not found")

    monkeypatch.setattr(pa.subprocess, "run", _run)
    monkeypatch.setattr(pa.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("must not sleep")))
    res = pa._run_gh(["gh", "x"], "x")
    assert res.returncode == 1 and len(calls) == 1
