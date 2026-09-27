# Order Service and Paylink Payment Integration

An API that accepts orders and charges cards through the external payment provider Paylink.

## Requirements

- Python 3.11 or newer (the candidate environment ships 3.11)
- PostgreSQL 16 (started with Docker Compose)

## Running

### 1. The Paylink sandbox

It ships in `tools/paylink-sandbox` (linux/amd64). Leave it running in its own terminal.

```bash
chmod +x tools/paylink-sandbox
./tools/paylink-sandbox --listen 127.0.0.1:9900
```

Check that it answers:

```bash
curl -s 'http://127.0.0.1:9900/v1/charges?limit=1'
```

### 2. The database and the application

```bash
docker compose up -d db
cp .env.example .env
export $(grep -v '^#' .env | xargs)
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py prepare_local_db   # prepares the schema and the existing data (next section)
python manage.py runserver 8080
```

The API listens on `http://localhost:8080`. Run `prepare_local_db` before `runserver`. In any other terminal you work from, run `export $(grep -v '^#' .env | xargs)` and `. .venv/bin/activate` there as well.

## Migrations and initial data

`python manage.py prepare_local_db` prepares the database in this order:

1. Only when the `orders` table does not exist yet (a fresh database):
   1. apply migrations up to the baseline `orders.0001_initial` (`python manage.py migrate orders 0001`)
   2. load `seed/current_data.sql`, the canonical snapshot: 15 orders from August together with their charge records
2. apply every pending migration in order (`python manage.py migrate`)

On an existing database (the `orders` table is there) only step 2 runs and the snapshot is not loaded again, so it is safe to run repeatedly. The schema lives under `orders/migrations/`. To change the schema, add a numbered migration instead of editing an existing one, and run `python manage.py prepare_local_db` (or `python manage.py migrate`) again. `runserver` does not apply migrations.

The Paylink sandbox holds its own charge history for the same period. The two sides do not necessarily agree.

## Tests

```bash
docker compose up -d db
pytest
```

Tests run in a dedicated test database (`test_orders`) that Django creates. Its schema is built from the migrations alone; `seed/current_data.sql` is not loaded. The tests error out when the database is unreachable.

## Checking the API

```bash
# Place an order and charge the card
curl -s -X POST localhost:8080/orders -H 'Content-Type: application/json' \
  -d '{"order_no":"ord-4001","customer_email":"test@example.com","amount_jpy":4500,"card_token":"tok_visa"}'
# => {"order_no":"ord-4001", ..., "status":"paid"}

# Read one order
curl -s localhost:8080/orders/ord-4001
# => status is paid

# Inspect the charge records of an order (operator endpoint)
curl -s localhost:8080/admin/orders/ord-4001/charges
# => one charge carrying a provider_charge_id

# Refund
curl -s -X POST localhost:8080/orders/ord-4001/refund
# => status is refunded

# Reconcile the orders that were never settled (operator endpoint; also available as a CLI)
curl -s -X POST localhost:8080/admin/reconcile
python manage.py reconcile
```

`POST /v1/sandbox/reset` restores the sandbox charge and refund history to its initial state (so does restarting the process). To restore the database, run `docker compose down -v`, then `docker compose up -d db` and `python manage.py prepare_local_db` again. **The sandbox and the database are reset separately, so resetting only one of them leaves the two sides inconsistent.**

## Layout

```
.
├── manage.py
├── requirements.txt
├── payment_reconciliation/   # Django project settings (settings, urls)
├── orders/                   # Order and charge business logic and the HTTP API
│   ├── service.py            # Placing orders and refunds
│   ├── reconcile.py          # Reconciliation
│   ├── views.py / urls.py    # HTTP API
│   ├── migrations/           # Schema migrations
│   ├── management/commands/
│   │   ├── prepare_local_db.py  # Prepares the schema and the existing data
│   │   └── reconcile.py         # Reconciliation batch (operators run it by hand)
│   └── tests/
├── paylink/                  # Paylink API client
├── seed/                     # Production-like existing data
├── tools/
│   └── paylink-sandbox       # The Paylink sandbox (do not modify)
└── docs/
    └── paylink-api.md        # Paylink integration document, written in-house when the integration was built
```

## API

| Operation | Method and path |
| --- | --- |
| Place an order and charge | `POST /orders` |
| List orders | `GET /orders` |
| Get an order | `GET /orders/{order_no}` |
| Refund | `POST /orders/{order_no}/refund` |
| Inspect charge records (operator) | `GET /admin/orders/{order_no}/charges` |
| Reconcile (operator) | `POST /admin/reconcile` |

See `docs/paylink-api.md` for the provider side of the integration.
