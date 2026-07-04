# TDnet 適時開示モニター

TDnet（適時開示情報閲覧サービス）から適時開示資料を毎営業日に自動取得し、時価総額順に整形してGmailで通知するシステムです。全件一覧はGitHub Pagesで閲覧できます。

---

## システム構成

```
GitHub Actions (毎営業日 2回)
  ├─ 17:00 JST [evening] ─┬─ 休場日判定 → 休場なら終了
  │                        ├─ TDnet スクレイピング (00:00〜17:00)
  │                        ├─ JPX 上場銘柄リストで REIT/ETF 除外
  │                        ├─ J-Quants V2 API で時価総額計算（終値×発行済株式数、分割補正）
  │                        ├─ JSON 保存 → GitHub Pages 更新
  │                        └─ Gmail 通知 (上位30件)
  │
  └─ 24:00 JST [night]  ──┬─ TDnet スクレイピング (17:01〜23:59)
                           ├─ 既存データとマージ (重複排除)
                           ├─ JSON 更新 → GitHub Pages 更新
                           └─ Gmail 通知 (差分全件)
```

---

## セットアップ手順

### Step 1：リポジトリの作成

1. [GitHub](https://github.com) にログイン
2. 右上の「+」→「New repository」をクリック
3. 以下を入力：
   - **Repository name**: `tdnet-monitor`
   - **Public** を選択（GitHub Pages に必要）
   - **Add a README file** のチェックは **外す**
4. 「Create repository」をクリック

### Step 2：ローカルにプロジェクトを配置

PowerShell を開き、以下を順に実行します。

```powershell
cd ~\Documents
cd tdnet-monitor

git init
git remote add origin https://github.com/あなたのユーザー名/tdnet-monitor.git
git add .
git commit -m "Initial commit"
git branch -M main
git push -u origin main
```

### Step 3：GitHub Pages の有効化

1. GitHub リポジトリの「Settings」タブ → 左メニュー「Pages」
2. **Source**: 「Deploy from a branch」
3. **Branch**: 「main」、フォルダを「/docs」
4. 「Save」をクリック

### Step 4：Gmail アプリパスワードの取得

1. https://myaccount.google.com/security にアクセス
2. 「2段階認証プロセス」が **有効** であることを確認
3. https://myaccount.google.com/apppasswords にアクセス
4. アプリ名に「TDnet Monitor」と入力 →「作成」
5. 表示される **16桁のパスワード** をコピー

### Step 5：GitHub Secrets の設定

リポジトリの「Settings」→「Secrets and variables」→「Actions」で以下を登録：

| Name | Value |
|------|-------|
| `GMAIL_ADDRESS` | 送信元Gmailアドレス |
| `GMAIL_APP_PASSWORD` | Step 4 の16桁パスワード |
| `NOTIFY_TO` | 通知先メールアドレス |
| `JQUANTS_API_KEY` | J-Quants Light 以上のプランの API キー |

### Step 6：動作テスト

1. GitHub リポジトリの「Actions」タブ
2. 「TDnet Daily Monitor」→「Run workflow」
3. `evening` または `night` を選択 →「Run workflow」
4. 実行ログでエラーがないことを確認
5. Gmailに通知が届くことを確認

---

## ファイル構成

```
tdnet-monitor/
├── .github/workflows/
│   ├── daily_monitor.yml    # GitHub Actions 定義（2回/日）
│   └── mirror_backfill.yml  # 既存PDFをReleasesへ退避する手動ジョブ（一回限り）
├── scripts/
│   ├── main.py              # メイン処理
│   ├── tdnet_scraper.py     # TDnet スクレイピング
│   ├── filter_reit_etf.py   # REIT/ETF 除外
│   ├── market_cap_jquants.py # 時価総額取得（J-Quants V2、主データソース）※正本は market-scripts-common（ベンダリング・直接編集禁止）
│   ├── market_cap_yahoo.py  # 時価総額取得（Yahoo Finance JP、新規上場銘柄フォールバック）※同上
│   ├── check_vendor.py      # ベンダリングのドリフト検知（vendor.lock.json と突合・CIで実行）
│   ├── html_generator.py    # HTML 生成
│   ├── pdf_archive.py       # 適時開示PDFを GitHub Releases へ退避・リンク書換え
│   ├── mirror_backfill.py   # 既存JSONのPDFを一括退避（一回限り）
│   └── gmail_sender.py      # Gmail 送信
├── docs/
│   ├── index.html           # GitHub Pages（自動更新）
│   └── data/                # 日次 JSON データ（直近90日ローリング保持）
├── requirements.txt
└── README.md
```

---

## 実行スケジュール

| 時刻 (JST) | モード | 取得範囲 | メール |
|------------|--------|---------|--------|
| 17:00 | evening | 00:00〜17:00 | 上位30件 |
| 24:00 | night | 17:01〜23:59（差分） | 差分全件 |

- 土日祝日・東証休場日はスキップされます
- 実行履歴は GitHub の Actions タブで確認できます

---

## トラブルシューティング

| 症状 | 対処 |
|------|------|
| Actions が動かない | Settings → Actions → General →「Allow all actions」を確認 |
| メールが届かない | Secrets の値を再確認。アプリパスワードにスペースが入っていないか確認 |
| Pages が表示されない | Settings → Pages で Branch: main / Folder: /docs を確認 |
| 時価総額が「—」 | `JQUANTS_API_KEY` 未設定、または Light 未満のプラン (Free は12週間遅延で当日値なし)。新規上場銘柄は Yahoo Finance JP 側も失敗した場合に発生 |
| PDFリンクが404 | 配信元(TDnet)は約1か月でPDFを削除する。当日分は自動で GitHub Releases へ退避するため**90日間は**開ける。退避前に配信元から消えた分は一覧上で「(公開終了)」と表示。90日を超えた分は JSON ごと削除され一覧からも消える（復元不可） |

---

## 技術仕様

- **REIT/ETF 除外**: JPX 上場銘柄一覧の「市場・商品区分」列から正確に判定（証券コード範囲は不使用）
- **時価総額**: J-Quants V2 API（`fins/summary` の `ShOutFY` × `equities/bars/daily` の `AdjC`、株式分割補正済）。Light プラン以上が必要。新規上場銘柄は Yahoo Finance JP からフォールバック取得
- **休場日判定**: `jpholiday`（祝日）+ 土日 + 年末年始（12/31〜1/3）
- **データ保持**: 開示日から **90日間のローリング保持**。91日以上経過した分は日次 JSON も Release 上の PDF も自動削除する（配信元 TDnet も約30日で消すため復元不可）。削除は毎営業日の実行で `cleanup_old_data`（JSON）と `pdf_archive.cleanup_expired_assets`（Release アセット）が同一 cutoff で実施。基準は実行日（JST）
- **PDF退避**: 配信元(TDnet `release.tdnet.info`)は PDF を約1か月しか保持しないため、毎回の実行で PDF を **GitHub Releases**（**1営業日=1リリース**、タグ `pdf-YYYYMMDD`、アセット名 `{TDnet ID}.pdf`）へ退避し、JSON のリンクを恒久URL（`https://github.com/<owner>/<repo>/releases/download/pdf-YYYYMMDD/<ID>.pdf`）へ書き換える。GitHub の上限は1リリース1000アセットのため、決算ピーク日（1日1000件超）は超過分を追加パート `pdf-YYYYMMDD-2`, `-3` … へ自動振り分け（1リリース900件未満）。退避は `gh` CLI で行い、Actions では `GH_TOKEN`(=`github.token`)、ローカルでは `gh auth login` 済みであることが必要。冪等（退避済みは再取得しない）。第三者アーカイブには依存しない

### 既存分の一括退避（一回限り）

過去に保存済みで「まだ配信元に残っている」PDF を退避するには、Actions タブ →「Mirror TDnet PDFs (backfill)」→ Run workflow を実行する（または `gh auth login` 済みのローカルで `cd scripts && python mirror_backfill.py`）。配信元は約1か月で消すため**早く実行するほど取りこぼしが少ない**。途中で失敗しても再実行で続きから処理する。
