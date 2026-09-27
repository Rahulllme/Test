# 注文サービスと Paylink 決済連携

注文を受け付け、外部の決済プロバイダ Paylink へ課金する API です。

## 必要な実行環境

- Python 3.11 以上（候補者環境には 3.11 が入っています）
- PostgreSQL 16（Docker Compose で起動します）

## 起動

### 1. Paylink サンドボックス

`tools/paylink-sandbox` に同梱されています（linux/amd64）。別のターミナルで起動したままにしてください。

```bash
chmod +x tools/paylink-sandbox
./tools/paylink-sandbox --listen 127.0.0.1:9900
```

疎通確認:

```bash
curl -s 'http://127.0.0.1:9900/v1/charges?limit=1'
```

### 2. DB とアプリ

```bash
docker compose up -d db
cp .env.example .env
export $(grep -v '^#' .env | xargs)
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py prepare_local_db   # schema と既存データの用意（次節）
python manage.py runserver 8080
```

API は `http://localhost:8080` で起動します。`runserver` より先に `prepare_local_db` を実行してください。別のターミナルで操作するときは、そのターミナルでも `export $(grep -v '^#' .env | xargs)` と `. .venv/bin/activate` を実行してください。

## DB migration と初期データ

`python manage.py prepare_local_db` が、次の順序で DB を用意します。

1. `orders` テーブルがまだない（新しい DB）場合だけ:
   1. baseline migration `orders.0001_initial` までを適用する（`python manage.py migrate orders 0001`）
   2. `seed/current_data.sql` を投入する。canonical snapshot で、8 月分の注文 15 件と対応する課金レコードが入ります
2. 未適用の migration をすべて番号順に適用する（`python manage.py migrate`）

既存の DB（`orders` テーブルがある）に対しては 2 だけが行われ、snapshot は再投入されません。何度実行しても安全です。schema は `orders/migrations/` で管理されています。schema を変更する場合は既存 migration を書き換えず、連番 migration を追加し、`python manage.py prepare_local_db`（または `python manage.py migrate`）を再度実行してください。`runserver` は migration を適用しません。

Paylink サンドボックスは同じ 8 月分の課金履歴を持っています。両者は必ずしも一致していません。

## テスト

```bash
docker compose up -d db
pytest
```

テストは Django が作成する専用のテスト DB（`test_orders`）で実行します。schema は migration だけから作られ、`seed/current_data.sql` は投入されません。DB へ接続できない場合はテストがエラーになります。

## API の動作確認

```bash
# 注文を作成して課金する
curl -s -X POST localhost:8080/orders -H 'Content-Type: application/json' \
  -d '{"order_no":"ord-4001","customer_email":"test@example.com","amount_jpy":4500,"card_token":"tok_visa"}'
# => {"order_no":"ord-4001", ..., "status":"paid"}

# 注文を1件取得する
curl -s localhost:8080/orders/ord-4001
# => status が paid

# 注文の課金レコードを見る（運用向け）
curl -s localhost:8080/admin/orders/ord-4001/charges
# => provider_charge_id が入った課金が1件

# 返金する
curl -s -X POST localhost:8080/orders/ord-4001/refund
# => status が refunded

# 決着していない注文を突合する（運用向け。CLI からも実行できる）
curl -s -X POST localhost:8080/admin/reconcile
python manage.py reconcile
```

`POST /v1/sandbox/reset` でサンドボックスの課金・返金履歴を初期状態に戻せます（プロセスを再起動しても初期状態に戻ります）。DB を初期状態に戻すには `docker compose down -v` の後に `docker compose up -d db` と `python manage.py prepare_local_db` を再度実行してください。**サンドボックスと DB は別々に初期化されるため、片方だけ戻すと状態が食い違います。**

## ファイル構成

```
.
├── manage.py
├── requirements.txt
├── payment_reconciliation/   # Django プロジェクト設定（settings, urls）
├── orders/                   # 注文・課金の業務ロジックと HTTP API
│   ├── service.py            # 注文作成・返金
│   ├── reconcile.py          # 突合
│   ├── views.py / urls.py    # HTTP API
│   ├── migrations/           # schema migration
│   ├── management/commands/
│   │   ├── prepare_local_db.py  # schema と既存データの用意
│   │   └── reconcile.py         # 突合バッチ（運用担当が手で実行している）
│   └── tests/
├── paylink/                  # Paylink API クライアント
├── seed/                     # 本番相当の既存データ
├── tools/
│   └── paylink-sandbox       # Paylink サンドボックス（変更しないこと）
└── docs/
    └── paylink-api.md        # Paylink 連携仕様（連携実装時に社内向けに書き起こしたもの）
```

## API

| 操作 | 方法とパス |
| --- | --- |
| 注文作成・課金 | `POST /orders` |
| 注文一覧 | `GET /orders` |
| 注文取得 | `GET /orders/{order_no}` |
| 返金 | `POST /orders/{order_no}/refund` |
| 課金レコード参照（運用） | `GET /admin/orders/{order_no}/charges` |
| 突合（運用） | `POST /admin/reconcile` |

Paylink 側の仕様は `docs/paylink-api.md` を確認してください。
