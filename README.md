# TDnet 適時開示モニター

TDnet（適時開示情報閲覧サービス）から適時開示資料を毎営業日に自動取得し、時価総額順に整形してGmailで通知するシステムです。全件一覧はGitHub Pagesで閲覧できます。

---

## システム構成

```
GitHub Actions (毎営業日 2回)
  ├─ 18:00 JST [evening] ─┬─ 休場日判定 → 休場なら終了
  │                        ├─ TDnet スクレイピング (00:00〜18:00)
  │                        ├─ JPX 上場銘柄リストで REIT/ETF 除外
  │                        ├─ 株探から時価総額取得・ソート
  │                        ├─ JSON 保存 → GitHub Pages 更新
  │                        └─ Gmail 通知 (上位30件)
  │
  └─ 24:00 JST [night]  ──┬─ TDnet スクレイピング (18:01〜23:59)
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
│   └── daily_monitor.yml    # GitHub Actions 定義（2回/日）
├── scripts/
│   ├── main.py              # メイン処理
│   ├── tdnet_scraper.py     # TDnet スクレイピング
│   ├── filter_reit_etf.py   # REIT/ETF 除外
│   ├── market_cap.py        # 時価総額取得（株探）
│   ├── html_generator.py    # HTML 生成
│   └── gmail_sender.py      # Gmail 送信
├── docs/
│   ├── index.html           # GitHub Pages（自動更新）
│   └── data/                # 日次 JSON データ（14日分保持）
├── requirements.txt
└── README.md
```

---

## 実行スケジュール

| 時刻 (JST) | モード | 取得範囲 | メール |
|------------|--------|---------|--------|
| 18:00 | evening | 00:00〜18:00 | 上位30件 |
| 24:00 | night | 18:01〜23:59（差分） | 差分全件 |

- 土日祝日・東証休場日はスキップされます
- 実行履歴は GitHub の Actions タブで確認できます

---

## トラブルシューティング

| 症状 | 対処 |
|------|------|
| Actions が動かない | Settings → Actions → General →「Allow all actions」を確認 |
| メールが届かない | Secrets の値を再確認。アプリパスワードにスペースが入っていないか確認 |
| Pages が表示されない | Settings → Pages で Branch: main / Folder: /docs を確認 |
| 時価総額が「—」 | 株探のページ構造変更の可能性。Issue で報告してください |

---

## 技術仕様

- **REIT/ETF 除外**: JPX 上場銘柄一覧の「市場・商品区分」列から正確に判定（証券コード範囲は不使用）
- **時価総額**: 株探 (kabutan.jp) から取得（リアルタイム）
- **休場日判定**: `jpholiday`（祝日）+ 土日 + 年末年始（12/31〜1/3）
- **データ保持**: 直近14日分の JSON を GitHub Pages で公開
