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
    """開示情報を表示用に変換・ソートする"""
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
    items.sort(key=lambda x: (-x.market_cap, x.code, x.time))
    return items


def _email_table_html(items: list[DisplayItem], max_items: int | None = None) -> str:
    """メール用テーブル HTML（インラインスタイル）"""
    display = items[:max_items] if max_items else items
    rows = []
    for item in display:
        mcap_str = _format_market_cap(item.market_cap) if item.market_cap > 0 else "—"
        title_html = (
            f'<a href="{item.pdf_url}" target="_blank" '
            f'style="color:#1a73e8;text-decoration:none;">{item.title}</a>'
            if item.pdf_url else item.title
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
    table_rows = _email_table_html(items, max_items=30)

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


def generate_pages_html(available_dates: list[str]) -> str:
    """GitHub Pages 用の日付選択式 HTML を生成する"""

    return """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>適時開示モニター</title>
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #f0f2f5;
      --card: #ffffff;
      --primary: #1a237e;
      --primary-light: #3949ab;
      --accent: #ff6d00;
      --text: #263238;
      --text-sub: #78909c;
      --border: #e0e4e8;
      --hover: #f5f7ff;
      --shadow: 0 2px 8px rgba(0,0,0,0.06);
    }
    * { margin:0; padding:0; box-sizing:border-box; }
    body {
      font-family: 'Noto Sans JP', sans-serif;
      background: var(--bg); color: var(--text);
      line-height: 1.6;
    }

    /* ヘッダー */
    .header {
      background: linear-gradient(135deg, var(--primary) 0%, var(--primary-light) 100%);
      color: #fff; padding: 28px 32px 20px;
    }
    .header-inner {
      max-width: 1200px; margin: 0 auto;
      display: flex; align-items: center; justify-content: space-between;
      flex-wrap: wrap; gap: 16px;
    }
    .header h1 { font-size: 22px; font-weight: 700; letter-spacing: 0.02em; }
    .header-sub { font-size: 13px; opacity: 0.8; margin-top: 4px; }

    /* 日付セレクター */
    .date-selector {
      display: flex; align-items: center; gap: 10px;
    }
    .date-selector label {
      font-size: 13px; opacity: 0.9;
    }
    .date-selector select {
      padding: 7px 32px 7px 12px;
      font-size: 14px; font-family: 'JetBrains Mono', monospace;
      border: 1px solid rgba(255,255,255,0.3);
      border-radius: 6px;
      background: rgba(255,255,255,0.15);
      color: #fff;
      cursor: pointer;
      appearance: none;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M2 4l4 4 4-4' stroke='white' stroke-width='1.5' fill='none'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 10px center;
    }
    .date-selector select:focus {
      outline: none;
      border-color: rgba(255,255,255,0.6);
      background-color: rgba(255,255,255,0.25);
    }
    .date-selector select option {
      background: var(--primary); color: #fff;
    }

    /* サマリー */
    .summary {
      max-width: 1200px; margin: 16px auto 0; padding: 0 16px;
      display: flex; gap: 12px; flex-wrap: wrap;
    }
    .summary-chip {
      background: var(--card); border-radius: 8px;
      padding: 8px 16px; font-size: 13px;
      box-shadow: var(--shadow);
      display: flex; align-items: center; gap: 6px;
    }
    .summary-chip .num {
      font-family: 'JetBrains Mono', monospace;
      font-weight: 700; font-size: 16px; color: var(--primary);
    }

    /* メインカード */
    .container { max-width: 1200px; margin: 16px auto 24px; padding: 0 16px; }
    .card {
      background: var(--card); border-radius: 10px;
      box-shadow: var(--shadow); overflow: hidden;
    }

    /* ツールバー */
    .toolbar {
      padding: 12px 16px; border-bottom: 1px solid var(--border);
      display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
    }
    .toolbar input[type="text"] {
      padding: 7px 14px; border: 1px solid var(--border);
      border-radius: 6px; font-size: 13px; width: 280px;
      font-family: 'Noto Sans JP', sans-serif;
      transition: border-color 0.2s;
    }
    .toolbar input[type="text"]:focus {
      outline: none; border-color: var(--primary-light);
    }
    .toolbar .result-count {
      font-size: 12px; color: var(--text-sub);
      margin-left: auto;
    }

    /* テーブル */
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    thead th {
      padding: 10px 14px; text-align: left;
      background: #f8f9fc; border-bottom: 2px solid var(--primary);
      font-weight: 500; font-size: 12px; color: var(--text-sub);
      text-transform: uppercase; letter-spacing: 0.05em;
      position: sticky; top: 0; z-index: 1;
      white-space: nowrap;
    }
    thead th.right { text-align: right; }
    tbody td {
      padding: 8px 14px; border-bottom: 1px solid var(--border);
      vertical-align: top;
    }
    tbody tr:hover td { background: var(--hover); }
    .code-cell {
      font-family: 'JetBrains Mono', monospace;
      font-weight: 500; white-space: nowrap;
    }
    .company-cell { white-space: nowrap; }
    .mcap-cell {
      text-align: right; white-space: nowrap;
      font-family: 'JetBrains Mono', monospace; font-size: 12px;
    }
    .time-cell {
      font-family: 'JetBrains Mono', monospace;
      white-space: nowrap; color: var(--text-sub);
    }
    .title-cell a {
      color: var(--primary-light); text-decoration: none;
      transition: color 0.15s;
    }
    .title-cell a:hover { color: var(--accent); text-decoration: underline; }
    .title-cell a.visited {
      color: #b0b8c0;
    }
    .title-cell a.visited:hover { color: #90979e; }

    /* ページネーション */
    .pagination {
      display: flex; align-items: center; justify-content: center;
      gap: 4px; padding: 12px 16px;
      border-bottom: 1px solid var(--border);
    }
    .pagination button {
      padding: 5px 12px; border: 1px solid var(--border);
      border-radius: 4px; background: var(--card);
      font-size: 13px; font-family: 'Noto Sans JP', sans-serif;
      cursor: pointer; color: var(--text);
      transition: all 0.15s;
    }
    .pagination button:hover:not(:disabled) {
      background: var(--hover); border-color: var(--primary-light);
    }
    .pagination button:disabled {
      opacity: 0.4; cursor: default;
    }
    .pagination button.active {
      background: var(--primary); color: #fff;
      border-color: var(--primary);
    }
    .pagination .page-info {
      font-size: 12px; color: var(--text-sub);
      margin: 0 8px;
    }

    /* ローディング */
    .loading {
      text-align: center; padding: 60px 20px;
      color: var(--text-sub); font-size: 14px;
    }
    .loading .spinner {
      display: inline-block; width: 28px; height: 28px;
      border: 3px solid var(--border);
      border-top-color: var(--primary);
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      margin-bottom: 12px;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* 空状態 */
    .empty {
      text-align: center; padding: 60px 20px;
      color: var(--text-sub); font-size: 14px;
    }

    /* フッター */
    .footer {
      text-align: center; padding: 20px;
      font-size: 11px; color: var(--text-sub);
    }

    /* レスポンシブ */
    @media (max-width: 768px) {
      .header-inner { flex-direction: column; align-items: flex-start; }
      .toolbar input[type="text"] { width: 100%; }
      .summary { flex-direction: column; }
      table { font-size: 12px; }
      thead th, tbody td { padding: 6px 8px; }
    }
  </style>
</head>
<body>

<div class="header">
  <div class="header-inner">
    <div>
      <h1>📋 適時開示モニター</h1>
      <div class="header-sub">TDnet 適時開示情報｜REIT/ETF除外｜時価総額降順</div>
    </div>
    <div class="date-selector">
      <label for="dateSelect">開示日:</label>
      <select id="dateSelect" onchange="loadDate(this.value)">
        <option value="">読み込み中...</option>
      </select>
    </div>
  </div>
</div>

<div class="summary" id="summaryArea"></div>

<div class="container">
  <div class="card">
    <div class="toolbar">
      <input type="text" id="filterInput" placeholder="銘柄コード・会社名で絞り込み..."
             oninput="filterTable()">
      <span class="result-count" id="resultCount"></span>
    </div>
    <div id="tableArea">
      <div class="loading">
        <div class="spinner"></div><br>
        データを読み込んでいます...
      </div>
    </div>
  </div>
</div>

<div class="footer">
  TDnet 適時開示モニター｜GitHub Actions 自動生成｜直近14営業日分を保持
</div>

<script>
let currentData = null;
let currentPage = 1;
const PAGE_SIZE = 100;
let filteredItems = [];
let visitedUrls = {};

// 既読状態の保存・復元（ブラウザのローカルストレージ）
function loadVisited() {
  try {
    const stored = localStorage.getItem('tdnet_visited');
    if (stored) visitedUrls = JSON.parse(stored);
  } catch(e) {}
}
function saveVisited() {
  try {
    localStorage.setItem('tdnet_visited', JSON.stringify(visitedUrls));
  } catch(e) {}
}
function markVisited(url) {
  visitedUrls[url] = true;
  saveVisited();
  document.querySelectorAll('.disclosure-link').forEach(a => {
    if (a.dataset.url === url) a.classList.add('visited');
  });
}

loadVisited();

async function init() {
  try {
    const resp = await fetch('data/manifest.json?' + Date.now());
    const manifest = await resp.json();
    const select = document.getElementById('dateSelect');
    select.innerHTML = '';

    if (manifest.dates.length === 0) {
      select.innerHTML = '<option value="">データなし</option>';
      document.getElementById('tableArea').innerHTML =
        '<div class="empty">まだデータがありません。初回実行後に表示されます。</div>';
      return;
    }

    manifest.dates.forEach((d, i) => {
      const opt = document.createElement('option');
      opt.value = d;
      const dt = new Date(d + 'T00:00:00');
      const weekday = ['日','月','火','水','木','金','土'][dt.getDay()];
      opt.textContent = d + ' (' + weekday + ')';
      if (i === 0) opt.selected = true;
      select.appendChild(opt);
    });

    loadDate(manifest.dates[0]);
  } catch (e) {
    document.getElementById('tableArea').innerHTML =
      '<div class="empty">データの読み込みに失敗しました。</div>';
  }
}

async function loadDate(dateStr) {
  if (!dateStr) return;
  const tableArea = document.getElementById('tableArea');
  tableArea.innerHTML = '<div class="loading"><div class="spinner"></div><br>データを読み込んでいます...</div>';

  try {
    const resp = await fetch('data/' + dateStr + '.json?' + Date.now());
    currentData = await resp.json();
    filteredItems = currentData.items || [];
    currentPage = 1;
    renderAll();
    document.getElementById('filterInput').value = '';
  } catch (e) {
    tableArea.innerHTML = '<div class="empty">この日付のデータを読み込めませんでした。</div>';
    document.getElementById('summaryArea').innerHTML = '';
  }
}

function renderAll() {
  renderSummary();
  renderPaginationAndTable();
}

function renderSummary() {
  const total = filteredItems.length;
  const companies = new Set(filteredItems.map(i => i.code)).size;
  document.getElementById('summaryArea').innerHTML =
    '<div class="summary-chip"><span class="num">' + companies + '</span>社</div>' +
    '<div class="summary-chip"><span class="num">' + total + '</span>件の開示</div>';
}

function formatMcap(v) {
  if (!v || v <= 0) return '—';
  if (v >= 10000) return (v / 10000).toFixed(1) + '兆円';
  if (v >= 1) return v.toLocaleString('ja-JP', {maximumFractionDigits:0}) + '億円';
  return v.toFixed(1) + '億円';
}

function renderPaginationAndTable() {
  const total = filteredItems.length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (currentPage > totalPages) currentPage = totalPages;

  const start = (currentPage - 1) * PAGE_SIZE;
  const end = Math.min(start + PAGE_SIZE, total);
  const pageItems = filteredItems.slice(start, end);

  // ページネーション HTML
  let pagHtml = '';
  if (totalPages > 1) {
    pagHtml = '<div class="pagination">';
    pagHtml += '<button onclick="goPage(1)" ' + (currentPage===1?'disabled':'') + '>«</button>';
    pagHtml += '<button onclick="goPage(' + (currentPage-1) + ')" ' + (currentPage===1?'disabled':'') + '>‹</button>';

    // ページ番号ボタン（最大7個表示）
    let pageStart = Math.max(1, currentPage - 3);
    let pageEnd = Math.min(totalPages, pageStart + 6);
    if (pageEnd - pageStart < 6) pageStart = Math.max(1, pageEnd - 6);

    for (let p = pageStart; p <= pageEnd; p++) {
      pagHtml += '<button onclick="goPage(' + p + ')" class="' + (p===currentPage?'active':'') + '">' + p + '</button>';
    }

    pagHtml += '<button onclick="goPage(' + (currentPage+1) + ')" ' + (currentPage===totalPages?'disabled':'') + '>›</button>';
    pagHtml += '<button onclick="goPage(' + totalPages + ')" ' + (currentPage===totalPages?'disabled':'') + '>»</button>';
    pagHtml += '<span class="page-info">' + start + '–' + end + ' / ' + total + '件</span>';
    pagHtml += '</div>';
  }

  // テーブル HTML
  let tblHtml = '<table id="disclosureTable"><thead><tr>' +
    '<th>コード</th><th>会社名</th><th class="right">時価総額</th><th>時刻</th><th>開示内容</th>' +
    '</tr></thead><tbody>';

  pageItems.forEach((item, idx) => {
    const mcap = formatMcap(item.market_cap);
    const isVisited = visitedUrls[item.pdf_url] ? ' visited' : '';
    const rowId = 'row-' + currentPage + '-' + idx;
    let titleHtml;
    if (item.pdf_url) {
      const safeUrl = escapeHtml(item.pdf_url);
      titleHtml = '<a href="' + safeUrl + '" target="_blank" class="disclosure-link' + isVisited + '" data-url="' + safeUrl + '" onclick="markVisited(this.dataset.url)">' + escapeHtml(item.title) + '</a>';
    } else {
      titleHtml = escapeHtml(item.title);
    }
    tblHtml += '<tr>' +
      '<td class="code-cell">' + item.code + '</td>' +
      '<td class="company-cell">' + escapeHtml(item.company_name) + '</td>' +
      '<td class="mcap-cell">' + mcap + '</td>' +
      '<td class="time-cell">' + item.time + '</td>' +
      '<td class="title-cell">' + titleHtml + '</td>' +
      '</tr>';
  });

  tblHtml += '</tbody></table>';

  document.getElementById('tableArea').innerHTML = pagHtml + tblHtml;
  updateResultCount(total, currentData ? currentData.total_count : total);
}

function goPage(p) {
  const totalPages = Math.max(1, Math.ceil(filteredItems.length / PAGE_SIZE));
  currentPage = Math.max(1, Math.min(p, totalPages));
  renderPaginationAndTable();
  // テーブル先頭にスクロール
  document.querySelector('.card').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function filterTable() {
  const q = document.getElementById('filterInput').value.toLowerCase();
  if (!currentData || !currentData.items) return;

  if (q === '') {
    filteredItems = currentData.items;
  } else {
    filteredItems = currentData.items.filter(item =>
      item.code.includes(q) ||
      item.company_name.toLowerCase().includes(q) ||
      item.title.toLowerCase().includes(q)
    );
  }
  currentPage = 1;
  renderAll();
}

function updateResultCount(visible, total) {
  const el = document.getElementById('resultCount');
  if (visible === total) {
    el.textContent = total + '件';
  } else {
    el.textContent = visible + ' / ' + total + '件';
  }
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

function escapeAttr(str) {
  return str.replace(/&/g,'&amp;').replace(/"/g,'&quot;');
}

init();
</script>
</body>
</html>"""
