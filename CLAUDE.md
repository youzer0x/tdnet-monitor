# CLAUDE.md — 開発時の規範（Claude Code 向け）

TDnet 適時開示モニター。毎営業日 evening(17:05・cron-job.org 起動)/night(00:10)/night 予備(05:30) の
3回、GitHub Actions で無人実行し、Gmail 通知＋GitHub Pages 公開する（予備は1回目が済んでいれば何もしない）。運用フローは `README.md` を参照。

## テスト規範（pytest）

- `scripts/` 配下の `.py` を変更したら、commit の前に必ず `python -m pytest` を実行する。
- テストが1件でも失敗している状態で commit しない。
- テストが失敗したら、**まず実装側のバグを疑う**。期待値を変える必要がある場合は「仕様が
  変わったため」であることをユーザーに説明し、同意を得てからテストを更新する。
  **テストの削除・skip 追加・assert の弱体化を黙って行うことを禁止する**（テストを通すために
  テスト側を書き換えるのは、番犬の口を塞ぐのと同じ）。
- 新しい関数・条件分岐を追加したら、対になるテストを `tests/` に追加する（純粋関数は必須。
  ファイル I/O を伴う関数は `tmp_path` フィクスチャで）。
- テストはネットワーク・認証情報・実行日時（`date.today()`）に依存させない。外部 API・
  スクレイピングは対象外とし、日付は固定値を渡す（`pytest-socket` が通信を機械遮断する）。
- テストは日次データ（`docs/data/`）を実行時に直接読まない。必要なら `tmp_path` に
  最小の JSON を組み立てて使う。

## SOT（単一の真実源）との同期

`market_cap_jquants.py` / `market_cap_yahoo.py` / `check_vendor.py` は、共有リポ **`market-scripts-common`** を
単一の真実源とするベンダリング（時価総額取得ロジックの出自は本リポ。v2.0.0 以降は J-Quants
`equities/valuation` の `MktCap`＝自己株式控除後を使用）。`scripts/vendor.lock.json` に
バージョン・sha256 が刻印され、CI の `python scripts/check_vendor.py` が不一致を検知して fail する。

- **ベンダリング済みファイルは本リポで直接編集しない**。変更フロー：market-scripts-common 側の
  `src/` を修正 → 同リポでテスト → VERSION 更新・tag → `python sync.py` で再配布 → 本リポでコミット。

## テストの実行

```bash
python -m pip install -r requirements-dev.txt   # 初回のみ
python -m pytest                                 # 全テスト（数秒・オフラインで完結）
```

CI: `.github/workflows/tests.yml` が push 時（`scripts/`・`tests/`・`requirements*`・`pytest.ini`・`tests.yml` 自身の変更時）に
自動で `python -m pytest` を回す。**日次運用ジョブ（`daily_monitor.yml`）とは独立**で、
docs/data への bot コミットでは走らない。

配信前テストゲート: `daily_monitor.yml` も `main.py` の前に `python -m pytest` を回す（警告のみ）。
失敗しても配信は止めず、メール件名の先頭に「⚠テスト失敗」が付く（`PYTEST_OUTCOME` → `gate_warning_prefix`）。
push CI では拾えない、実行時に入る依存ライブラリの新バージョン（`>=` 指定）による不具合の検知が目的。
