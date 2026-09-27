# Solution

## What was wrong

The integration was implemented against the 2023 document, but the supplied sandbox now serves
the `2026-04-01` API. Direct observation of that API showed several incompatible changes:

- a successful HTTP response is not necessarily a successful charge: both `failed` and
  `requires_action` charges are returned with `201 Created`;
- a merchant `reference` is no longer unique, so retrying only by order number can create several
  real charges;
- the `reference` list filter is ignored;
- charge and refund lists contain at most five records and must be followed using `next_cursor`;
- `refunded_amount` is no longer present on a charge; the complete refund list is the source of
  truth;
- charge idempotency works, but the current refund endpoint creates another refund even when the
  same `Idempotency-Key` is reused;
- the rate limit returns `429` with `Retry-After`.

The old service compounded those changes. It retried every provider error without an idempotency
key, treated every 2xx response as paid, classified timeouts as definite failures, selected the
last local charge for refunds, and read only the first provider page. Its reconciliation checked
only pending orders and accepted the first record sharing a reference without verifying amount,
currency, status, duplicates, or refunds.

## Design

### Charging

An order and an `unknown` charge intent are committed locally before Paylink is called. A crash or
timeout therefore leaves an auditable `pending` order instead of either losing the order after
moving money or declaring an uncertain charge failed.

Every logical charge uses a deterministic SHA-256-based `Idempotency-Key` derived from the order
number. All retries reuse it. A provider response is accepted only when its id, reference, amount,
and currency match the order. The order becomes `paid` only for provider status `succeeded`,
`failed` only for a definitive failure, and remains `pending` for `requires_action`, unknown
statuses, malformed responses, or exhausted transport retries.

The local unique order number remains the public API's concurrency boundary: only the request that
successfully creates the order may contact Paylink.

### Reading Paylink

The client requests API version `2026-04-01`, follows every cursor with the observed page size,
and filters references locally. It detects repeated cursors and malformed list responses rather
than silently accepting incomplete evidence. It retries transport failures, server errors, and
rate limits; `Retry-After` is honored. Charges carry a stable idempotency key and can be retried
after an unknown response. Refunds are intentionally subject to the stricter policy below.

### Refunds

A refund is allowed only for a paid order with exactly one locally accepted, full-value,
successful provider charge. The service verifies that charge directly and reads every refund page
before moving money. A full existing refund repairs local state without issuing another refund; a
partial, excessive, mismatched, or otherwise ambiguous history returns a conflict. Repeating an
already completed refund is a no-op.

Because the current provider does not honor refund idempotency, a refund request is never retried
after a timeout, connection loss, or server error. The order remains paid locally. A later request
first reads the complete provider refund history: if the original refund succeeded, it repairs the
local state without moving money again; if no refund exists, it may make one new attempt. The
idempotency header is still sent for forward compatibility but is not trusted as a safety control.

Provider payloads cross a strict validation boundary before business logic can use them. Charge
and refund identifiers must be non-empty strings, amounts must be integers (not booleans), statuses
must be non-empty strings, and timestamps must be valid timezone-qualified date strings. Malformed
payloads become `PaylinkError`; they can leave a charge pending or a reconciliation unresolved, but
cannot manufacture evidence that money moved. A successful refund additionally requires a
non-empty provider refund ID before the local order can become refunded.

### Reconciliation

One run fetches complete charge and refund snapshots once, avoiding an all-pages scan per order
and reducing rate-limit pressure. It audits every order, not only rows currently labelled pending.
Evidence is matched by reference, exact JPY amount, currency, provider status, and successful
refund totals.

When several successful, unrefunded charges agree completely, reconciliation retains the charge
already accepted locally (or the earliest charge when none was accepted) and idempotently refunds
the extras. It then synchronizes local charge rows and derives the order state from net provider
state. Missing records, reused references with different amounts, partial or excessive refunds,
and other contradictions are reported as `unresolved`; no money or local state is changed for
those cases. Reconciliation locks its full order set before taking the provider snapshot, which
serializes it with customer refunds and other reconciliation runs. This database serialization is
the duplicate-refund guard that Paylink itself does not provide.

## Existing snapshot

Against a freshly reset supplied sandbox and `seed/current_data.sql`, the first run safely:

- changes `ord-20260805-5436` and `ord-20260822-9535` from pending to paid;
- repairs the duplicate successful charges for `ord-20260809-6327` and
  `ord-20260826-1426` by refunding one full duplicate for each and marking the orders paid;
- corrects `ord-20260818-2317` from paid to failed.

It deliberately leaves these cases unresolved:

- `ord-20260811-7307`: no provider charge exists;
- `ord-20260814-4634`: the provider amount is JPY 48,500 while the order is JPY 51,000;
- `ord-20260820-3297`: successful refunds total JPY 9,700 for a JPY 9,000 charge;
- `ord-20260824-8376`: only JPY 8,000 of a JPY 20,000 charge was refunded.

The `requires_action` charge for `ord-20260829-3386` remains pending. Running reconciliation again
produces no additional refunds or settled rows.

## Verification

The test suite covers the original public API plus current decline and 3-D Secure statuses, an
explicit non-retried legacy 402 decline, recoverable temporary failures, malformed success
responses, concurrent duplicate orders, concurrent and repeated refunds, safe duplicate repair,
amount mismatch handling, cursor pagination, stable charge idempotency keys after a lost response,
non-retryable ambiguous refund failures, refund recovery after a lost response, API versioning,
missing refund identifiers, invalid charge/refund timestamps, invalid duplicate-refund responses,
duplicate identifiers across pages, malformed provider objects, unresolved refund states, orphaned
refunds, and bounded `Retry-After` handling. The refund ledger is authoritative because the live
sandbox leaves the charge-level `refunded_amount` stale after a successful refund.

Commands run:

```text
pytest -q
33 passed

python manage.py check
System check identified no issues (0 silenced).
```

The updated client was also exercised against the supplied binary sandbox: it read all 20 seeded
charges and all 9 seeded refunds across pages. The full production-like snapshot was reconciled
once and then twice more to verify that subsequent runs issue no further repairs.
