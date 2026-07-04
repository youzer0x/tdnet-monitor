# CLAUDE.md — 開発時の規範（Claude Code 向け）

TDnet 適時開示モニター。毎営業日 evening(17:00)/night(24:00) の2回、GitHub Actions で
無人実行し、Gmail 通知＋GitHub Pages 公開する。運用フローは `README.md` を参照。

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

`market_cap_jquants.py` / `market_cap_yahoo.py` は、共有リポ **`market-scripts-common`** を
単一の真実源とするベンダリング（時価総額算出方式の出自は本リポ）。`scripts/vendor.lock.json` に
バージョン・sha256 が刻印され、CI の `python scripts/check_vendor.py` が不一致を検知して fail する。

- **ベンダリング済みファイルは本リポで直接編集しない**。変更フロー：market-scripts-common 側の
  `src/` を修正 → 同リポでテスト → VERSION 更新・tag → `python sync.py` で再配布 → 本リポでコミット。

## テストの実行

```bash
python -m pip install -r requirements-dev.txt   # 初回のみ
python -m pytest                                 # 全テスト（数秒・オフラインで完結）
```

CI: `.github/workflows/tests.yml` が push 時（`scripts/`・`tests/`・`requirements*` 変更時）に
自動で `python -m pytest` を回す。**日次運用ジョブ（`daily_monitor.yml`）とは独立**で、
docs/data への bot コミットでは走らない。

> 配信前テストゲート（`daily_monitor.yml` の実行前に pytest を挟む案）は、push CI を
> 1〜2週間運用して偽陽性が無いことを確認してから追加する方針（未導入）。
