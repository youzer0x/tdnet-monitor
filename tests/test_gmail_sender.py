"""gmail_sender.py の単体テスト（件名の組み立てのみ。SMTP 送信は対象外）。"""
from datetime import date

from gmail_sender import build_subject

D = date(2026, 9, 17)


def test_build_subject_plain():
    assert build_subject(D) == "【適時開示】2026/09/17 の開示情報"


def test_build_subject_suffix():
    assert build_subject(D, "（夜間更新分）") == "【適時開示】2026/09/17 の開示情報（夜間更新分）"


def test_build_subject_prefix_and_suffix():
    assert (build_subject(D, "（夜間更新分）", "⚠テスト失敗 ")
            == "⚠テスト失敗 【適時開示】2026/09/17 の開示情報（夜間更新分）")
