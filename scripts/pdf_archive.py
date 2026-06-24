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
from datetime import date, timedelta

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


# 1営業日 = 1リリース。決算ピーク日は開示が1日1000件超になり得るが、GitHub の
# 上限は「1リリースあたり1000アセット」のため、超過分は -2, -3 ... の追加リリース
# (パート)へ退避する。1リリースあたりは ASSET_CAP 未満に保つ。
ASSET_CAP = 900  # 1000未満の安全マージン


def _part_tag(d: date, part: int) -> str:
    """part<=1 -> pdf-YYYYMMDD, part>=2 -> pdf-YYYYMMDD-{part}."""
    base = "pdf-" + d.strftime("%Y%m%d")
    return base if part <= 1 else f"{base}-{part}"


def _release_title(d: date, part: int = 1) -> str:
    t = "TDnet PDF " + d.isoformat()
    return t if part <= 1 else f"{t} ({part})"


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


# 退避/期限切れ削除で対象とする日次リリースのタグ形式（無関係リリースに触れない）。
# pdf-YYYYMMDD（基本）と pdf-YYYYMMDD-N（決算ピーク日の追加パート）。
_RELEASE_TAG_RE = re.compile(r"^pdf-(\d{8})(?:-(\d+))?$")


def _tag_date(tag: str) -> date | None:
    """リリースタグ(pdf-YYYYMMDD[-N])から開示日を取り出す。不正なら None。

    保持判定はアセット名(訂正開示等で日付がずれ得る)ではなく、
    その開示が掲載された一覧の日付＝タグ日付で行う。
    """
    m = _RELEASE_TAG_RE.match(tag.strip())
    if not m:
        return None
    d8 = m.group(1)
    try:
        return date(int(d8[0:4]), int(d8[4:6]), int(d8[6:8]))
    except ValueError:
        return None


def _part_num(tag: str) -> int:
    """タグのパート番号（pdf-YYYYMMDD=1, pdf-YYYYMMDD-N=N）。"""
    m = _RELEASE_TAG_RE.match(tag.strip())
    return int(m.group(2)) if (m and m.group(2)) else 1


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


def _is_rate_limited(blob: str) -> bool:
    b = blob.lower()
    return ("secondary rate limit" in b
            or "api rate limit exceeded" in b
            or "you have exceeded a secondary" in b
            or "rate limit" in b and "exceeded" in b)


def _run_gh(cmd: list[str], what: str, attempts: int = 6) -> subprocess.CompletedProcess:
    """gh コマンドを実行。GitHub のレート制限(403)時はバックオフ再試行する。

    二次レート制限(作成系の速度制限。数分で解除)を待ち越すのが主目的。
    一次の時間あたり上限を使い切った場合は短いバックオフでは解除されないため、
    数回で諦めて呼び出し側がエラー計上 → 後続の再実行で続きから処理する（冪等）。
    レート制限以外のエラーは即座に返す。
    """
    res = None
    for i in range(attempts):
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            return res
        blob = res.stderr + res.stdout
        if _is_rate_limited(blob):
            wait = min(300, 30 * (2 ** i))  # 30,60,120,240,300...
            print(f"    … GitHub rate limited on {what}; wait {wait}s and retry (attempt {i + 1})")
            time.sleep(wait)
            continue
        return res  # レート制限以外は再試行しない
    return res


def _ensure_release(repo: str, tag: str, title: str) -> bool:
    """リリースが無ければ作成する。既存なら True。"""
    res = _run_gh(
        ["gh", "release", "create", tag, "--repo", repo,
         "--title", title, "--notes", title],
        f"create {tag}",
    )
    if res.returncode == 0:
        return True
    blob = (res.stderr + res.stdout).lower()
    if "already exists" in blob or "already_exists" in blob:
        return True
    print(f"    ! release create failed ({tag}): {res.stderr.strip()[:200]}")
    return False


# 二次レート制限(作成系の速度制限)を避けるため、小さめのチャンクで間隔を空けて投入する。
UPLOAD_CHUNK = 20
UPLOAD_PAUSE = 2.0  # チャンク間の待機(秒)


def _upload(repo: str, tag: str, files: list[str]) -> bool:
    """アセットをまとめてアップロード（引数長対策＋レート制限対策で小分け）。"""
    ok = True
    for i in range(0, len(files), UPLOAD_CHUNK):
        part = files[i:i + UPLOAD_CHUNK]
        res = _run_gh(
            ["gh", "release", "upload", tag, *part, "--repo", repo, "--clobber"],
            f"upload {tag}",
        )
        if res.returncode != 0:
            print(f"    ! upload failed ({tag}): {res.stderr.strip()[:200]}")
            ok = False
        elif UPLOAD_PAUSE:
            time.sleep(UPLOAD_PAUSE)
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


def _day_part_tags(repo: str, d: date) -> list[str]:
    """その日の既存パートタグを part 番号順に返す。"""
    ymd = d.strftime("%Y%m%d")
    found = []
    for tag in _list_release_tags(repo):
        m = _RELEASE_TAG_RE.match(tag)
        if m and m.group(1) == ymd:
            found.append((_part_num(tag), tag))
    found.sort()
    return [t for _, t in found]


def mirror_json_file(
    json_path: str,
    repo: str | None = None,
    throttle: float = 0.25,
) -> dict:
    """1つの日次 JSON を処理し、PDF を Release へ退避して pdf_url を書き換える。

    1営業日 = 1リリース。アセットが ASSET_CAP を超える日は追加パート
    (pdf-YYYYMMDD-2 ...) へ振り分ける。既存アセットは元のパートに留め、
    新規分だけ末尾パート→新パートの順に詰めるため冪等。
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

    # 既存パートのアセット配置と充填状況（冪等性のため既存は動かさない）
    asset_to_tag: dict[str, str] = {}
    part_fill: dict[str, int] = {}
    part_tags: list[str] = _day_part_tags(repo, d)
    for tag in part_tags:
        a = _existing_assets(repo, tag)
        part_fill[tag] = len(a)
        for name in a:
            asset_to_tag[name] = tag
    if not part_tags:
        part_tags = [_part_tag(d, 1)]
        part_fill[part_tags[0]] = 0

    def target_part_tag() -> str:
        last = part_tags[-1]
        if part_fill.get(last, 0) < ASSET_CAP:
            return last
        tag = _part_tag(d, len(part_tags) + 1)  # 末尾が満杯 → 新パート
        part_tags.append(tag)
        part_fill[tag] = 0
        return tag

    session = requests.Session()
    session.headers["User-Agent"] = _UA

    tmpdir = tempfile.mkdtemp(prefix="tdnetpdf_")
    # part tag -> [(item, filepath, asset_url)]（アップロード成功後に書換え）
    queued: dict[str, list[tuple[dict, str, str]]] = {}
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

            if name in asset_to_tag:
                # 既にどこかのパートにある → URL だけ差し替え（安全）
                tag = asset_to_tag[name]
                it["pdf_url"] = f"{_asset_base(repo, tag)}/{name}"
                it.pop("pdf_expired", None)
                stats["already"] += 1
                continue

            status, content = _download(session, url)
            if status == "ok":
                tag = target_part_tag()
                fp = os.path.join(tmpdir, name)
                with open(fp, "wb") as wf:
                    wf.write(content)
                asset_url = f"{_asset_base(repo, tag)}/{name}"
                queued.setdefault(tag, []).append((it, fp, asset_url))
                part_fill[tag] = part_fill.get(tag, 0) + 1
                asset_to_tag[name] = tag
                stats["archived"] += 1
            elif status == "expired":
                it["pdf_url"] = ""
                it["pdf_expired"] = True
                stats["expired"] += 1
            else:
                stats["error"] += 1  # 据え置き（次回再試行）
            if throttle:
                time.sleep(throttle)

        # パートごとにアップロードし、成功した分だけ URL を書き換える
        for tag, entries in queued.items():
            files = [fp for (_, fp, _) in entries]
            uploaded = (_ensure_release(repo, tag, _release_title(d, _part_num(tag)))
                        and _upload(repo, tag, files))
            if uploaded:
                for it, _fp, asset_url in entries:
                    it["pdf_url"] = asset_url
                    it.pop("pdf_expired", None)
            else:
                stats["archived"] -= len(entries)
                stats["error"] += len(entries)  # 書き換えず据え置き

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return stats


def _list_release_tags(repo: str) -> list[str]:
    """`pdf-YYYYMMDD[-N]` 形式の日次リリースタグ一覧。失敗時は空。"""
    res = subprocess.run(
        ["gh", "release", "list", "--repo", repo, "--limit", "1000",
         "--json", "tagName", "-q", ".[].tagName"],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        print(f"    ! release list failed: {res.stderr.strip()[:200]}")
        return []
    return [ln.strip() for ln in res.stdout.splitlines()
            if _RELEASE_TAG_RE.match(ln.strip())]


def cleanup_expired_assets(
    repo: str | None = None,
    cutoff_date: date | None = None,
    throttle: float = 0.1,
    max_deletes: int | None = None,
    dry_run: bool = False,
) -> dict:
    """保持期間を過ぎた日次リリース(PDF)を Release ごと削除する（ローリング保持）。

    タグ pdf-YYYYMMDD[-N] の日付が cutoff_date より前なら、その日のリリースを
    パートごと（pdf-YYYYMMDD も pdf-YYYYMMDD-N も）タグごと削除する。実際の
    リリースを走査するため JSON に依存しない（自己修復）。冪等・非致命。

    安全策:
      - 削除判定はタグ日付のみ（訂正開示でアセット名の日付がずれても安全）。
      - 対象タグは `pdf-YYYYMMDD[-N]` のみ（許可リスト）。日付不明は KEEP。
      - 1リリース=1日分なので、削除はリリース単位の確実な操作。
    """
    repo = repo or repo_slug()
    if cutoff_date is None:
        cutoff_date = date.today() - timedelta(days=90)

    stats = {"deleted_releases": 0, "kept": 0, "unparsed": 0, "errors": 0}
    deleted = 0

    for tag in _list_release_tags(repo):
        if max_deletes is not None and deleted >= max_deletes:
            break
        td = _tag_date(tag)
        if td is None:
            stats["unparsed"] += 1          # 日付不明は絶対に消さない
            continue
        if td >= cutoff_date:
            stats["kept"] += 1               # 保持期間内
            continue
        # td < cutoff_date → 91日以上経過 → リリースごと削除
        if dry_run:
            print(f"    [dry-run] would delete release {tag} ({td})")
            stats["deleted_releases"] += 1
            deleted += 1
            continue
        res = subprocess.run(
            ["gh", "release", "delete", tag, "--cleanup-tag", "-y", "--repo", repo],
            capture_output=True, text=True,
        )
        if res.returncode == 0:
            stats["deleted_releases"] += 1
            deleted += 1
        else:
            stats["errors"] += 1
            print(f"    ! release delete failed ({tag}): {res.stderr.strip()[:200]}")
        if throttle:
            time.sleep(throttle)

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
    #   python pdf_archive.py <data_dir>                    # 退避状況の集計のみ（ネット不要）
    #   python pdf_archive.py <path/to/date.json>           # その日を退避（gh 認証必要）
    #   python pdf_archive.py --cleanup [YYYY-MM-DD] [--dry-run]
    #       cutoff より前(=保持外)の Release アセットを削除。日付省略時は今日-90日。
    if len(sys.argv) < 2:
        print("Usage: python pdf_archive.py <data_dir | date.json | --cleanup [YYYY-MM-DD] [--dry-run]>")
        sys.exit(1)

    if sys.argv[1] == "--cleanup":
        rest = sys.argv[2:]
        dry = "--dry-run" in rest
        rest = [a for a in rest if a != "--dry-run"]
        cutoff = date.fromisoformat(rest[0]) if rest else (date.today() - timedelta(days=90))
        if not gh_available():
            print("gh CLI not found / not authenticated.")
            sys.exit(1)
        print(f"cutoff={cutoff} (keep >= cutoff), dry_run={dry}")
        print(cleanup_expired_assets(cutoff_date=cutoff, dry_run=dry))
        sys.exit(0)

    target = sys.argv[1]
    if os.path.isdir(target):
        _status_report(target)
    else:
        if not gh_available():
            print("gh CLI not found / not authenticated.")
            sys.exit(1)
        print(mirror_json_file(target))
