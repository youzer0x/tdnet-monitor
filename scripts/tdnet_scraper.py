"""TDnet 適時開示情報のスクレイピング"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import date
from dataclasses import dataclass


@dataclass
class Disclosure:
    """適時開示情報1件を表すデータクラス"""
    time: str           # 開示時刻 (HH:MM)
    code: str           # 証券コード (4桁)
    company_name: str   # 会社名
    title: str          # 開示タイトル
    pdf_url: str        # PDF の URL


def fetch_disclosures(target_date: date | None = None) -> list[Disclosure]:
    """
    TDnet から指定日の適時開示一覧を取得する。
    target_date が None の場合は当日。

    TDnet の一覧ページ URL 形式:
      https://www.release.tdnet.info/inbs/I_list_001_YYYYMMDD.html
    ページネーション:
      I_list_001_..., I_list_002_..., ...（1ページ100件）
    """
    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime("%Y%m%d")
    base_url = "https://www.release.tdnet.info/inbs"
    disclosures: list[Disclosure] = []
    page = 1

    while True:
        url = f"{base_url}/I_list_{page:03d}_{date_str}.html"
        print(f"  Fetching: {url}")

        try:
            resp = requests.get(url, timeout=30)
            # ページが存在しない場合は 404 等 → 終了
            if resp.status_code != 200:
                break
        except requests.RequestException as e:
            print(f"  Warning: Request failed for page {page}: {e}")
            break

        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")

        # 開示一覧テーブルの各行を取得
        rows = soup.select("table tr")
        found_any = False

        for row in rows:
            cells = row.select("td")
            if len(cells) < 4:
                continue

            # 時刻
            time_text = cells[0].get_text(strip=True)
            if not re.match(r"^\d{2}:\d{2}$", time_text):
                continue

            # 証券コード
            # 数字4桁 (例: 7203) またはアルファベット混在4桁 (例: 464A) + 末尾0の5桁形式
            code_text = cells[1].get_text(strip=True)
            code_match = re.match(r"^([\dA-Z]{3,4})", code_text)
            if not code_match:
                continue
            code = code_match.group(1)
            # 5桁の場合は先頭4桁を取得 (例: 464A0 → 464A)
            if len(code) > 4:
                code = code[:4]
            # 最低限の検証: 少なくとも1つの数字を含むこと
            if not any(c.isdigit() for c in code):
                continue

            # 会社名
            company_name = cells[2].get_text(strip=True)

            # 開示タイトルとPDFリンク
            title_cell = cells[3]
            link_tag = title_cell.select_one("a")
            if link_tag:
                title = link_tag.get_text(strip=True)
                href = link_tag.get("href", "")
                if href.startswith("/"):
                    pdf_url = f"https://www.release.tdnet.info{href}"
                elif href.startswith("http"):
                    pdf_url = href
                else:
                    pdf_url = f"{base_url}/{href}"
            else:
                title = title_cell.get_text(strip=True)
                pdf_url = ""

            disclosures.append(Disclosure(
                time=time_text,
                code=code,
                company_name=company_name,
                title=title,
                pdf_url=pdf_url,
            ))
            found_any = True

        if not found_any:
            break

        page += 1

    print(f"  Total disclosures fetched: {len(disclosures)}")
    return disclosures
