# Paylink 決済 API 連携仕様

| | |
| --- | --- |
| 対象 API バージョン | `2023-02-01` |
| 作成 | 2023-02 連携実装時 |
| 最終更新 | 2023-02 |

Paylink 社が提供する決済 API の連携仕様です。この文書は連携を実装したときに Paylink の公開ドキュメントから社内向けに書き起こしたもので、以後更新していません。

## エンドポイント

サンドボックスは `http://127.0.0.1:9900` で動作しています。本番は `https://api.paylink.example.com` です。認証は本番のみで必要で、サンドボックスでは不要です。

金額は最小通貨単位の整数（日本円なら円）で扱います。通貨は `JPY` のみ対応しています。

## POST /v1/charges

課金を作成します。

```json
{
  "amount": 12000,
  "currency": "JPY",
  "card_token": "tok_visa",
  "reference": "ord-20260803-4821"
}
```

`reference` には加盟店側の識別子（当社では注文番号）を渡します。**同じ `reference` の課金は Paylink 側で重複作成が防止されます。**

応答は `201 Created` です。

```json
{
  "id": "ch_000000000000000000000001",
  "reference": "ord-20260803-4821",
  "amount": 12000,
  "currency": "JPY",
  "status": "succeeded",
  "card_token": "tok_visa",
  "refunded_amount": 0,
  "created_at": "2026-08-03T02:10:00Z",
  "updated_at": "2026-08-03T02:10:00Z"
}
```

`status` は成立時 `succeeded` です。カードが与信に失敗した場合と追加認証（3Dセキュア）が必要な場合は、`201` ではなく `402 Payment Required` が返ります。したがって **HTTP ステータスが 2xx であれば課金は成立しています。**

応答時間は p99 で 800ms です。タイムアウトした場合、課金は作成されていません。

### Idempotency-Key

任意のヘッダとして `Idempotency-Key` を付けられます。同じキーの再送には最初の結果が返り、二重課金になりません。**キーは 24 時間有効です。**

### テスト用カードトークン

サンドボックスでは次のトークンが使えます。

| トークン | 挙動 |
| --- | --- |
| `tok_visa` | 成立する |
| `tok_insufficient` | 残高不足で与信に失敗する |
| `tok_3ds` | 追加認証が必要になる |

## GET /v1/charges/{id}

課金を 1 件取得します。作成した課金は**直後から取得できます**。存在しない ID には `404` が返ります。

## GET /v1/charges

課金の一覧を取得します。

| クエリ | 説明 |
| --- | --- |
| `limit` | 1 ページの件数。既定 20、**最大 100** |
| `cursor` | 次ページのカーソル。応答の `next_cursor` をそのまま渡す |
| `reference` | **加盟店側の識別子で絞り込む** |
| `status` | `status` で絞り込む |

```json
{
  "data": [ { "id": "ch_...", "reference": "ord-20260803-4821", "...": "..." } ],
  "next_cursor": "off_20"
}
```

**並び順は `created_at` の昇順で、カーソルはページ間で安定しています。** `next_cursor` が応答に含まれない場合、それが最終ページです。

## POST /v1/refunds

返金します。

```json
{
  "charge_id": "ch_000000000000000000000001",
  "amount": 12000
}
```

応答は `201 Created` で、`{"id": "rf_...", "charge_id": "...", "amount": 12000, "status": "succeeded", "created_at": "..."}` が返ります。

**返金は `Idempotency-Key` で冪等化されます。** 課金額を超える返金は `400 Bad Request` で拒否されます。

## GET /v1/refunds

`charge_id` を指定して、その課金に対する返金の一覧を取得します。

## レート制限

**20 req/sec** を超えると `429 Too Many Requests` が返ります。応答には **`Retry-After` ヘッダ**が含まれるので、その秒数だけ待って再送してください。

## POST /v1/sandbox/reset

サンドボックス限定のエンドポイントです。サンドボックスの課金・返金の履歴を初期状態へ戻します。本番には存在しません。レート制限の対象外です。
