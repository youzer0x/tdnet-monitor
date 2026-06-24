"""既存の docs/data/*.json をすべて走査し、まだ TDnet 上に残っている PDF を
GitHub Releases へ退避してリンクを恒久URLへ書き換える一回限りのスクリプト。

通常運用では main.py が当日分を毎回退避するため不要だが、過去に保存済みで
「まだ配信元に PDF が残っている分」を今すぐ退避するために使う。配信元は
約1か月で PDF を削除するため、実行が遅れるほど取りこぼし（=復元不能）が増える。

冪等。途中で止まっても再実行で続きから処理する（退避済みは再取得しない）。
古い方（=期限切れが近い方）から処理して取りこぼしを最小化する。

使い方:
  ローカル:  gh auth login 済みで  python mirror_backfill.py
  Actions :  GH_TOKEN を渡して     python mirror_backfill.py
"""

import os
import sys
import glob

from pdf_archive import mirror_json_file, gh_available, repo_slug
from main import update_manifest
from html_generator import generate_pages_html


def main():
    if not gh_available():
        print("gh CLI not found. Run `gh auth login` locally, or set GH_TOKEN in Actions.")
        sys.exit(1)

    docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
    data_dir = os.path.join(docs_dir, "data")
    files = sorted(
        f for f in glob.glob(os.path.join(data_dir, "*.json"))
        if os.path.basename(f) != "manifest.json"
    )  # 昇順 = 古い日付（期限切れが近い）から

    repo = repo_slug()
    print(f"Repo: {repo}")
    print(f"Files: {len(files)} (oldest first)\n")

    total = {"archived": 0, "already": 0, "expired": 0, "error": 0, "skip": 0}
    for fp in files:
        name = os.path.basename(fp)[:-5]
        print(f"== {name} ==")
        st = mirror_json_file(fp, repo=repo)
        print(f"   {st}")
        for k, v in st.items():
            total[k] = total.get(k, 0) + v

    # 退避結果（pdf_expired 表示を含む最新JS）を反映するため index.html を再生成
    available_dates = update_manifest(docs_dir)
    pages_html = generate_pages_html(available_dates)
    with open(os.path.join(docs_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(pages_html)
    print(f"  Regenerated index.html ({len(available_dates)} dates)")

    print(f"\n{'=' * 50}")
    print(f"TOTAL: {total}")
    print(f"{'=' * 50}")
    if total["error"]:
        print("Some items had transient errors; re-run to retry them.")


if __name__ == "__main__":
    main()
