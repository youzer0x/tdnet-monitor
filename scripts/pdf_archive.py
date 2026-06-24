"""適時開示PDFを GitHub Releases へ自前保存（ミラー）するモジュール。

TDnet の配信サーバ (release.tdnet.info) は PDF を約1か月（スライド式）しか
保持せず、それより古い PDF は削除される。一覧(JSON)はリポジトリに恒久保存
しているのに、PDFリンクは消えゆく配信元を指しているため、古い開示の PDF を
開くと 404 になる。これを解消するため、取得時に PDF を GitHub Release アセット
へ退避し、JSON のリンクを恒久URLへ書き換える。

設計:
  - 1か月 = 1リリース（タグ `pdf-YYYYMM`）。アセット名は `{TDnet PDF ID}.pdf`。
  - 退避済み（Release に同名アセットが既にある）PDF は再取得・再アップロードしない（冪等）。
  - 退避できた項目は pdf_url を Release アセットURLへ書き換える。
  - 配信元から既に消えている (404/410) 項目は pdf_url="" とし pdf_expired=True を付す。
  - アップロード失敗・一時エラーの項目は pdf_url を据え置き、次回実行で再試行する。

外部の第三者アーカイブには一切依存しない。アップロードは `gh` CLI（GitHub Actions
では自動認証、ローカルでは `gh auth login` 済みであること）を使う。
"""

import os
import re
import sys
import json
import time
import glob
import shutil
import tempfile
import subprocess
from datetime import date

import requests

# 既に退避済みの URL（GitHub Release アセット）を見分けるための目印
ARCHIVE_URL_MARKER = "/releases/download/"
# 配信元（ここを指している間は退避前）
TDNET_HOST = "release.tdnet.info"
# リモートから owner/repo を取れない場合のフォールバック
DEFAULT_REPO = "youzer0x/tdnet-monitor"

_UA = "Mozilla/5.0 (compatible; tdnet-monitor/1.0; +https://github.com/youzer0x/tdnet-monitor)"


def gh_available() -> bool:
    """gh CLI が使えるか。"""
    return shutil.which("gh") is not None


def repo_slug() -> str:
    """owner/repo を返す。GITHUB_REPOSITORY → git remote → フォールバックの順。"""
    slug = os.environ.get("GITHUB_REPOSITORY")
    if slug:
        return slug
    try:
        url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:
        return DEFAULT_REPO
    # git@host:owner/repo.git / https://github.com/owner/repo.git / ssh alias 対応
    m = re.search(r"[:/]([^/:]+/[^/:]+?)(?:\.git)?$", url)
    return m.group(1) if m else DEFAULT_REPO


def _tag_for(d: date) -> str:
    """1か月1リリース。"""
    return "pdf-" + d.strftime("%Y%m")


def _release_title(d: date) -> str:
    return "TDnet PDF " + d.strftime("%Y-%m")


def _asset_base(repo: str, tag: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}"


def _pdf_id(url: str) -> str | None:
    """PDF URL から ID（ファイル名の拡張子なし部分）を取り出す。"""
    if not url:
        return None
    name = url.rsplit("/", 1)[-1].split("?")[0]
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    return name or None


def _existing_assets(repo: str, tag: str) -> set[str]:
    """リリースに既に存在するアセット名の集合。リリースが無ければ空集合。"""
    res = subprocess.run(
        ["gh", "release", "view", tag, "--repo", repo,
         "--json", "assets", "-q", ".assets[].name"],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        return set()  # リリース未作成、または取得不可
    return {ln.strip() for ln in res.stdout.splitlines() if ln.strip()}


def _ensure_release(repo: str, tag: str, title: str) -> bool:
    """リリースが無ければ作成する。既存なら True。"""
    res = subprocess.run(
        ["gh", "release", "create", tag, "--repo", repo,
         "--title", title, "--notes", title],
        capture_output=True, text=True,
    )
    if res.returncode == 0:
        return True
    blob = (res.stderr + res.stdout).lower()
    if "already exists" in blob or "already_exists" in blob:
        return True
    print(f"    ! release create failed ({tag}): {res.stderr.strip()[:200]}")
    return False


def _upload(repo: str, tag: str, files: list[str]) -> bool:
    """アセットをまとめてアップロード（引数長対策で分割）。"""
    ok = True
    chunk = 40
    for i in range(0, len(files), chunk):
        part = files[i:i + chunk]
        res = subprocess.run(
            ["gh", "release", "upload", tag, *part, "--repo", repo, "--clobber"],
            capture_output=True, text=True,
        )
        if res.returncode != 0:
            print(f"    ! upload failed ({tag}): {res.stderr.strip()[:200]}")
            ok = False
    return ok


def _download(session: requests.Session, url: str) -> tuple[str, bytes | None]:
    """PDF を取得。status は 'ok' / 'expired' / 'error'。"""
    for attempt in range(3):
        try:
            r = session.get(url, timeout=40)
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 200:
            if r.content[:4] == b"%PDF":
                return "ok", r.content
            return "error", None  # ソフト404 等（PDF でない）
        if r.status_code in (404, 410):
            return "expired", None
        time.sleep(2 * (attempt + 1))  # 403/429/5xx 等は一時エラーとして再試行
    return "error", None


def mirror_json_file(
    json_path: str,
    repo: str | None = None,
    throttle: float = 0.25,
) -> dict:
    """1つの日次 JSON を処理し、PDF を Release へ退避して pdf_url を書き換える。

    戻り値は処理件数の内訳 dict。JSON は変更があれば上書き保存する。
    """
    repo = repo or repo_slug()
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("items", [])
    try:
        d = date.fromisoformat(data.get("date") or os.path.basename(json_path)[:-5])
    except (ValueError, TypeError):
        print(f"    ! cannot determine date for {json_path}; skip")
        return {"skip": len(items)}

    tag = _tag_for(d)
    base = _asset_base(repo, tag)
    existing = _existing_assets(repo, tag)

    session = requests.Session()
    session.headers["User-Agent"] = _UA

    tmpdir = tempfile.mkdtemp(prefix="tdnetpdf_")
    to_upload: list[str] = []          # アップロード予定ファイルパス
    pending: list[tuple[dict, str]] = []  # (item, 退避後URL) アップロード成功後に書換え
    stats = {"archived": 0, "already": 0, "expired": 0, "error": 0, "skip": 0}

    try:
        for it in items:
            url = it.get("pdf_url", "") or ""
            if not url:
                stats["skip"] += 1
                continue
            if ARCHIVE_URL_MARKER in url:
                stats["already"] += 1  # 退避済み
                continue

            pid = _pdf_id(url)
            if not pid:
                stats["skip"] += 1
                continue
            name = pid + ".pdf"
            asset_url = f"{base}/{name}"

            if name in existing:
                # 既にアップロード済み → URL だけ差し替え（安全）
                it["pdf_url"] = asset_url
                it.pop("pdf_expired", None)
                stats["already"] += 1
                continue

            status, content = _download(session, url)
            if status == "ok":
                fp = os.path.join(tmpdir, name)
                with open(fp, "wb") as wf:
                    wf.write(content)
                to_upload.append(fp)
                pending.append((it, asset_url))
                stats["archived"] += 1
            elif status == "expired":
                it["pdf_url"] = ""
                it["pdf_expired"] = True
                stats["expired"] += 1
            else:
                stats["error"] += 1  # 据え置き（次回再試行）
            if throttle:
                time.sleep(throttle)

        # 取得できた分をアップロードし、成功した場合のみ URL を書き換える
        if to_upload:
            uploaded = _ensure_release(repo, tag, _release_title(d)) and _upload(repo, tag, to_upload)
            if uploaded:
                for it, asset_url in pending:
                    it["pdf_url"] = asset_url
                    it.pop("pdf_expired", None)
            else:
                stats["archived"] -= len(pending)
                stats["error"] += len(pending)  # 書き換えず据え置き

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return stats


def _status_report(data_dir: str) -> None:
    """ネットワークを使わず、各 JSON の退避状況（URL ホスト別）を集計表示する。"""
    files = sorted(glob.glob(os.path.join(data_dir, "*.json")))
    grand = {"archived": 0, "tdnet": 0, "expired": 0, "none": 0}
    for fp in files:
        if os.path.basename(fp) == "manifest.json":
            continue
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        c = {"archived": 0, "tdnet": 0, "expired": 0, "none": 0}
        for it in data.get("items", []):
            url = it.get("pdf_url", "") or ""
            if ARCHIVE_URL_MARKER in url:
                c["archived"] += 1
            elif it.get("pdf_expired"):
                c["expired"] += 1
            elif TDNET_HOST in url:
                c["tdnet"] += 1
            else:
                c["none"] += 1
        for k in grand:
            grand[k] += c[k]
        print(f"{os.path.basename(fp)[:-5]}  archived={c['archived']:4d} "
              f"tdnet={c['tdnet']:4d} expired={c['expired']:4d} none={c['none']:3d}")
    print(f"\nTOTAL  archived={grand['archived']} tdnet={grand['tdnet']} "
          f"expired={grand['expired']} none={grand['none']}")


if __name__ == "__main__":
    # 使い方:
    #   python pdf_archive.py <data_dir>            # 退避状況の集計のみ（ネット不要）
    #   python pdf_archive.py <path/to/date.json>   # その日を退避（gh 認証必要）
    if len(sys.argv) < 2:
        print("Usage: python pdf_archive.py <data_dir | date.json>")
        sys.exit(1)
    target = sys.argv[1]
    if os.path.isdir(target):
        _status_report(target)
    else:
        if not gh_available():
            print("gh CLI not found / not authenticated.")
            sys.exit(1)
        print(mirror_json_file(target))
