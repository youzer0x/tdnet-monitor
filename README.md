# TDnet 適時開示モニター

TDnet（適時開示情報閲覧サービス）から適時開示資料を毎営業日18時に自動取得し、時価総額順に整形してGmailで通知するシステムです。全件一覧はGitHub Pagesで閲覧できます。

---

## システム構成

```
GitHub Actions (毎日18時 JST)
  ├─ 休場日判定 → 休場なら終了
  ├─ TDnet スクレイピング（当日の適時開示取得）
  ├─ JPX 上場銘柄リストで REIT/ETF を除外
  ├─ J-Quants API で時価総額データ取得・ソート
  ├─ GitHub Pages 用 HTML 生成（全件一覧）
  ├─ docs/ に HTML を commit & push
  └─ Gmail で上位30件を通知
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
# 作業フォルダに移動
cd ~\Documents

# ダウンロードした tdnet-monitor フォルダが Documents 配下にある想定
cd tdnet-monitor

# Git 初期化と初回 push
git init
git remote add origin https://github.com/あなたのユーザー名/tdnet-monitor.git
git add .
git commit -m "Initial commit"
git branch -M main
git push -u origin main
```

> **補足**: `あなたのユーザー名` の部分は GitHub のユーザー名に置き換えてください。

### Step 3：GitHub Pages の有効化

1. GitHub リポジトリの「Settings」タブ → 左メニュー「Pages」
2. **Source**: 「Deploy from a branch」
3. **Branch**: 「main」、フォルダを「/docs」
4. 「Save」をクリック

数分後に `https://あなたのユーザー名.github.io/tdnet-monitor/` でページが公開されます。

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

### Step 6：J-Quants API の登録

時価総額データの取得に [J-Quants API](https://jpx-jquants.com/)（JPX公式・無料プラン）を使用します。

1. https://jpx-jquants.com/ でアカウント作成（Free プラン）
2. メール認証を完了

GitHub Secrets に追加：

| Name | Value |
|------|-------|
| `JQUANTS_EMAIL` | J-Quants 登録メールアドレス |
| `JQUANTS_PASSWORD` | J-Quants パスワード |

### Step 7：動作テスト

1. GitHub リポジトリの「Actions」タブ
2. 「TDnet Daily Monitor」→「Run workflow」→「Run workflow」
3. 実行ログでエラーがないことを確認
4. Gmailに通知が届くことを確認

---

## ファイル構成

```
tdnet-monitor/
├── .github/workflows/
│   └── daily_monitor.yml    # GitHub Actions 定義
├── scripts/
│   ├── main.py              # メイン処理
│   ├── tdnet_scraper.py     # TDnet スクレイピング
│   ├── filter_reit_etf.py   # REIT/ETF 除外
│   ├── market_cap.py        # 時価総額取得
│   ├── html_generator.py    # HTML 生成
│   └── gmail_sender.py      # Gmail 送信
├── docs/
│   └── index.html           # GitHub Pages（自動更新）
├── requirements.txt
└── README.md
```

---

## トラブルシューティング

| 症状 | 対処 |
|------|------|
| Actions が動かない | Settings → Actions → General →「Allow all actions」を確認 |
| メールが届かない | Secrets の値を再確認。アプリパスワードにスペースが入っていないか確認 |
| J-Quants エラー | Free プランの日次リクエスト上限の可能性。翌日再実行 |
| Pages が表示されない | Settings → Pages で Branch: main / Folder: /docs を確認 |

---

## 技術仕様

- **REIT/ETF 除外**: JPX 上場銘柄一覧 Excel の「市場・商品区分」列から正確に判定（証券コード範囲は不使用）
- **時価総額**: J-Quants API（Free プランは2営業日遅延あり）
- **休場日判定**: `jpholiday`（祝日）+ 土日 + 年末年始（12/31〜1/3）
- **スケジュール**: GitHub Actions cron `0 9 * * *`（UTC）= 毎日18:00 JST
