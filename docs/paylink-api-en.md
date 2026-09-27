# Paylink Payment API Integration

| | |
| --- | --- |
| API version covered | `2023-02-01` |
| Written | 2023-02, when the integration was built |
| Last updated | 2023-02 |

The integration specification for the payment API provided by Paylink. It was written in-house from Paylink's public documentation when the integration was built, and has not been updated since.

## Endpoints

The sandbox runs at `http://127.0.0.1:9900`. Production is `https://api.paylink.example.com`. Authentication is required in production only; the sandbox needs none.

Amounts are integers in the smallest currency unit (yen for JPY). Only `JPY` is supported.

## POST /v1/charges

Creates a charge.

```json
{
  "amount": 12000,
  "currency": "JPY",
  "card_token": "tok_visa",
  "reference": "ord-20260803-4821"
}
```

`reference` carries the merchant-side identifier; we pass the order number. **Paylink prevents duplicate creation for the same `reference`.**

The response is `201 Created`.

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

`status` is `succeeded` when the charge goes through. When the card is declined, and when additional authentication (3-D Secure) is required, the response is `402 Payment Required` rather than `201`. Therefore **a 2xx status means the charge went through.**

The response time is 800ms at p99. If the call times out, no charge was created.

### Idempotency-Key

An optional `Idempotency-Key` header may be sent. A retry with the same key returns the first result instead of charging twice. **Keys are valid for 24 hours.**

### Test card tokens

The sandbox accepts the following tokens.

| Token | Behavior |
| --- | --- |
| `tok_visa` | Succeeds |
| `tok_insufficient` | Declined for insufficient funds |
| `tok_3ds` | Requires additional authentication |

## GET /v1/charges/{id}

Reads one charge. A charge that was just created **is readable immediately**. An unknown id returns `404`.

## GET /v1/charges

Lists charges.

| Query | Description |
| --- | --- |
| `limit` | Page size. Default 20, **maximum 100** |
| `cursor` | Cursor for the next page. Pass the `next_cursor` from the response as-is |
| `reference` | **Filters by the merchant-side identifier** |
| `status` | Filters by `status` |

```json
{
  "data": [ { "id": "ch_...", "reference": "ord-20260803-4821", "...": "..." } ],
  "next_cursor": "off_20"
}
```

**Records are ordered by `created_at` ascending, and cursors are stable across pages.** When the response has no `next_cursor`, that page is the last one.

## POST /v1/refunds

Refunds a charge.

```json
{
  "charge_id": "ch_000000000000000000000001",
  "amount": 12000
}
```

The response is `201 Created` with `{"id": "rf_...", "charge_id": "...", "amount": 12000, "status": "succeeded", "created_at": "..."}`.

**Refunds are made idempotent through `Idempotency-Key`.** A refund beyond the charged amount is rejected with `400 Bad Request`.

## GET /v1/refunds

Lists the refunds of a charge, selected by `charge_id`.

## Rate limit

Above **20 req/sec** the API answers `429 Too Many Requests`. The response includes a **`Retry-After` header**; wait that many seconds and retry.

## POST /v1/sandbox/reset

A sandbox-only endpoint. It restores the sandbox charge and refund history to its initial state. It does not exist in production and is not rate limited.
