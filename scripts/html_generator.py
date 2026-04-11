"""GitHub Pages 用 HTML および メール本文 HTML の生成"""

from datetime import date
from dataclasses import dataclass


@dataclass
class DisplayItem:
    """表示用の開示情報（時価総額でソート済み）"""
    code: str
    company_name: str
    market_cap: float      # 億円
    time: str
    title: str
    pdf_url: str


def _format_market_cap(value: float) -> str:
    """時価総額を読みやすい形式にフォーマット"""
    if value >= 10000:
        return f"{value/10000:.1f}兆円"
    elif value >= 1:
        return f"{value:,.0f}億円"
    else:
        return f"{value:.1f}億円"


def prepare_display_items(
    disclosures: list,
    market_caps: dict[str, float],
) -> list[DisplayItem]:
    """
    開示情報を表示用に変換・ソートする。
    - 発行体の時価総額で降順
    - 同一発行体内は開示時刻で昇順
    """
    items = []
    for d in disclosures:
        items.append(DisplayItem(
            code=d.code,
            company_name=d.company_name,
            market_cap=market_caps.get(d.code, 0),
            time=d.time,
            title=d.title,
            pdf_url=d.pdf_url,
        ))

    # ソート: 時価総額降順 → 同一コード内は時刻昇順
    items.sort(key=lambda x: (-x.market_cap, x.code, x.time))
    return items


def _table_html(items: list[DisplayItem], max_items: int | None = None) -> str:
    """テーブルHTMLを生成する共通関数"""
    display = items[:max_items] if max_items else items

    rows = []
    for item in display:
        mcap_str = _format_market_cap(item.market_cap) if item.market_cap > 0 else "—"
        title_html = (
            f'<a href="{item.pdf_url}" target="_blank" '
            f'style="color:#1a73e8;text-decoration:none;">{item.title}</a>'
            if item.pdf_url
            else item.title
        )
        rows.append(f"""        <tr>
          <td style="padding:6px 10px;border-bottom:1px solid #e0e0e0;font-family:monospace;white-space:nowrap;">{item.code}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #e0e0e0;white-space:nowrap;">{item.company_name}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #e0e0e0;text-align:right;white-space:nowrap;">{mcap_str}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #e0e0e0;font-family:monospace;white-space:nowrap;">{item.time}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #e0e0e0;">{title_html}</td>
        </tr>""")

    return "\n".join(rows)


def generate_email_html(
    items: list[DisplayItem],
    target_date: date,
    pages_url: str,
) -> str:
    """Gmail 通知用の HTML を生成する（上位30件）"""
    date_str = target_date.strftime("%Y年%m月%d日")
    total_count = len(items)
    company_count = len(set(item.code for item in items))

    table_rows = _table_html(items, max_items=30)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:'Helvetica Neue',Arial,'Hiragino Sans',sans-serif;color:#333;margin:0;padding:0;background:#f5f5f5;">
  <div style="max-width:960px;margin:20px auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);">

    <div style="background:#1a237e;color:#fff;padding:20px 24px;">
      <h1 style="margin:0;font-size:20px;font-weight:600;">📋 適時開示モニター</h1>
      <p style="margin:6px 0 0;font-size:14px;opacity:0.9;">{date_str}｜{company_count}社・{total_count}件</p>
    </div>

    <div style="padding:16px 24px;">
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead>
          <tr style="background:#f8f9fa;">
            <th style="padding:8px 10px;text-align:left;border-bottom:2px solid #1a237e;white-space:nowrap;">コード</th>
            <th style="padding:8px 10px;text-align:left;border-bottom:2px solid #1a237e;white-space:nowrap;">会社名</th>
            <th style="padding:8px 10px;text-align:right;border-bottom:2px solid #1a237e;white-space:nowrap;">時価総額</th>
            <th style="padding:8px 10px;text-align:left;border-bottom:2px solid #1a237e;white-space:nowrap;">時刻</th>
            <th style="padding:8px 10px;text-align:left;border-bottom:2px solid #1a237e;">開示内容</th>
          </tr>
        </thead>
        <tbody>
{table_rows}
        </tbody>
      </table>

      {"<p style='margin:16px 0 0;font-size:13px;color:#666;'>※ 上位30件を表示。</p>" if total_count > 30 else ""}

      <div style="margin:20px 0;text-align:center;">
        <a href="{pages_url}" target="_blank"
           style="display:inline-block;background:#1a237e;color:#fff;padding:10px 28px;border-radius:6px;text-decoration:none;font-size:14px;font-weight:500;">
          全{total_count}件を表示 →
        </a>
      </div>
    </div>

    <div style="background:#f8f9fa;padding:12px 24px;font-size:11px;color:#999;text-align:center;">
      TDnet 適時開示モニター｜GitHub Actions 自動送信
    </div>
  </div>
</body>
</html>"""


def generate_pages_html(
    items: list[DisplayItem],
    target_date: date,
) -> str:
    """GitHub Pages 用の全件一覧 HTML を生成する"""
    date_str = target_date.strftime("%Y年%m月%d日")
    total_count = len(items)
    company_count = len(set(item.code for item in items))

    table_rows = _table_html(items)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>適時開示一覧 - {date_str}</title>
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{
      font-family: 'Helvetica Neue', Arial, 'Hiragino Sans', sans-serif;
      background: #f0f2f5; color: #333;
    }}
    .header {{
      background: #1a237e; color: #fff;
      padding: 24px 32px;
    }}
    .header h1 {{ font-size: 22px; font-weight: 600; }}
    .header p {{ margin-top: 6px; font-size: 14px; opacity: 0.85; }}
    .container {{
      max-width: 1100px; margin: 24px auto; padding: 0 16px;
    }}
    .card {{
      background: #fff; border-radius: 8px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
      overflow-x: auto;
    }}
    table {{
      width: 100%; border-collapse: collapse; font-size: 13px;
    }}
    th {{
      padding: 10px 12px; text-align: left;
      background: #f8f9fa; border-bottom: 2px solid #1a237e;
      position: sticky; top: 0; white-space: nowrap;
    }}
    td {{
      padding: 7px 12px; border-bottom: 1px solid #eee;
    }}
    tr:hover td {{ background: #f8f9ff; }}
    a {{ color: #1a73e8; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .mono {{ font-family: monospace; }}
    .right {{ text-align: right; }}
    .nowrap {{ white-space: nowrap; }}
    .footer {{
      text-align: center; padding: 20px;
      font-size: 12px; color: #999;
    }}
    /* フィルタ */
    .filter-bar {{
      padding: 12px 16px; background: #fff;
      border-bottom: 1px solid #eee;
    }}
    .filter-bar input {{
      padding: 6px 12px; border: 1px solid #ddd;
      border-radius: 4px; font-size: 13px; width: 260px;
    }}
  </style>
</head>
<body>
  <div class="header">
    <h1>📋 適時開示一覧</h1>
    <p>{date_str}｜{company_count}社・{total_count}件（REIT/ETF除外済み・時価総額降順）</p>
  </div>
  <div class="container">
    <div class="card">
      <div class="filter-bar">
        <input type="text" id="filterInput" placeholder="銘柄コード・会社名で絞り込み..."
               oninput="filterTable()">
      </div>
      <table id="disclosureTable">
        <thead>
          <tr>
            <th>コード</th>
            <th>会社名</th>
            <th style="text-align:right;">時価総額</th>
            <th>時刻</th>
            <th>開示内容</th>
          </tr>
        </thead>
        <tbody>
{table_rows}
        </tbody>
      </table>
    </div>
  </div>
  <div class="footer">
    TDnet 適時開示モニター｜GitHub Actions 自動生成
  </div>
  <script>
    function filterTable() {{
      const q = document.getElementById('filterInput').value.toLowerCase();
      const rows = document.querySelectorAll('#disclosureTable tbody tr');
      rows.forEach(row => {{
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(q) ? '' : 'none';
      }});
    }}
  </script>
</body>
</html>"""
