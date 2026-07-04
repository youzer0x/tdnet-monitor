"""html_generator.py の書式・変換関数の単体テスト（純粋変換・ネット非接触）。"""
from datetime import date

from html_generator import (
    _format_market_cap, prepare_display_items, generate_email_html, DisplayItem,
)


class _D:
    """prepare_display_items 用の最小開示オブジェクト。"""
    def __init__(self, code, time, title="開示", pdf="https://x/a.pdf"):
        self.code = code
        self.company_name = "会社" + code
        self.time = time
        self.title = title
        self.pdf_url = pdf


# ── _format_market_cap ───────────────────────────────────────
def test_format_market_cap():
    assert _format_market_cap(12000) == "1.2兆円"      # 1兆以上
    assert _format_market_cap(1500) == "1,500億円"     # 1億以上はカンマ・整数
    assert _format_market_cap(0.5) == "0.5億円"        # 1億未満は小数1桁


# ── prepare_display_items（join＋ソート）──────────────────────
def test_prepare_display_items_joins_and_sorts_by_mcap_desc():
    disclosures = [_D("6758", "10:00"), _D("7203", "09:30"), _D("9999", "11:00")]
    caps = {"7203": 400000, "6758": 600000}   # 9999 は時価総額なし → 0 扱い
    items = prepare_display_items(disclosures, caps)
    # 時価総額降順 → コード昇順 → 時刻昇順
    assert [it.code for it in items] == ["6758", "7203", "9999"]
    assert items[0].market_cap == 600000
    assert items[-1].market_cap == 0


# ── generate_email_html ──────────────────────────────────────
def _items(n):
    return [DisplayItem(code=f"700{i}", company_name=f"テスト銘柄{i}",
                        market_cap=1000 * (n - i), time=f"09:{i:02d}",
                        title=f"開示{i}", pdf_url=f"https://x/{i}.pdf")
            for i in range(n)]


def test_generate_email_html_contains_names_and_link():
    html = generate_email_html(_items(3), date(2026, 7, 3), "https://example.github.io/x/")
    assert "テスト銘柄0" in html and "テスト銘柄2" in html
    assert "https://example.github.io/x/" in html


def test_generate_email_html_respects_max_items():
    html = generate_email_html(_items(5), date(2026, 7, 3), "https://x/", max_items=2)
    # max_items=2 → 先頭2件のみ描画（時価総額降順で 7000/7001）、以降は出ない
    assert "テスト銘柄0" in html and "テスト銘柄1" in html
    assert "テスト銘柄2" not in html and "テスト銘柄4" not in html


def test_generate_email_html_handles_empty():
    html = generate_email_html([], date(2026, 7, 3), "https://x/")
    assert isinstance(html, str) and len(html) > 0
