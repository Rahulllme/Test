from collections import defaultdict
from dataclasses import dataclass, field

from django.db import transaction

import paylink

from . import repository
from .models import Charge, ChargeStatus, Status


@dataclass
class Report:
    """The outcome of one reconciliation run."""

    checked: int = 0
    settled: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def as_json(self) -> dict:
        return {"checked": self.checked, "settled": self.settled, "unresolved": self.unresolved}


def reconcile(service) -> Report:
    """Rebuild local payment state from one complete provider snapshot.

    The current Paylink API no longer filters by reference, so fetching once is both safer and far
    less likely to hit the rate limit than scanning every page for every order. Duplicate charges
    are refunded only when reference, amount, currency, and successful status all agree.
    """
    # Lock every existing order before taking the provider snapshot. This serializes the operator
    # batch with customer refunds and other reconciliation runs. It matters because the current
    # Paylink refund endpoint does not actually honor Idempotency-Key.
    with transaction.atomic():
        return _reconcile_locked(service)


def _reconcile_locked(service) -> Report:
    orders = repository.list_orders_for_reconciliation()
    report = Report(checked=len(orders))

    charges_by_reference: dict[str, list[paylink.Charge]] = defaultdict(list)
    for charge in service.provider.list_charges(""):
        charges_by_reference[charge.reference].append(charge)

    refunds_by_charge: dict[str, list[paylink.Refund]] = defaultdict(list)
    for refund in service.provider.list_refunds(""):
        refunds_by_charge[refund.charge_id].append(refund)

    for order in orders:
        provider_charges = charges_by_reference.get(order.order_no, [])
        if not provider_charges:
            report.unresolved.append(order.order_no)
            continue

        # A reused reference with a different amount cannot safely be assigned to this order.
        if any(
            not charge.id
            or charge.reference != order.order_no
            or charge.amount != order.amount_jpy
            or charge.currency != "JPY"
            for charge in provider_charges
        ):
            report.unresolved.append(order.order_no)
            continue

        successful = [charge for charge in provider_charges if charge.status == "succeeded"]
        active: list[paylink.Charge] = []
        fully_refunded: list[paylink.Charge] = []
        ambiguous = False
        for charge in successful:
            refunded = sum(
                refund.amount
                for refund in refunds_by_charge.get(charge.id, [])
                if refund.status == "succeeded"
            )
            if refunded == 0:
                active.append(charge)
            elif refunded == charge.amount:
                fully_refunded.append(charge)
            else:
                ambiguous = True
        if ambiguous:
            report.unresolved.append(order.order_no)
            continue

        repaired_duplicate = False
        if len(active) > 1:
            canonical = _canonical_charge(order.id, active)
            extras = [charge for charge in active if charge.id != canonical.id]
            try:
                for duplicate in extras:
                    refund = service.provider.create_refund(duplicate.id, duplicate.amount)
                    if (
                        refund.charge_id != duplicate.id
                        or refund.amount != duplicate.amount
                        or refund.status != "succeeded"
                    ):
                        raise paylink.PaylinkError("paylink: invalid duplicate-refund response")
                    refunds_by_charge[duplicate.id].append(refund)
                    fully_refunded.append(duplicate)
                active = [canonical]
                repaired_duplicate = True
            except paylink.PaylinkError:
                report.unresolved.append(order.order_no)
                continue

        target = _target_status(provider_charges, successful, active, fully_refunded)
        if target is None:
            report.unresolved.append(order.order_no)
            continue

        now = service.clock.now()
        _sync_charge_rows(order, provider_charges, {charge.id for charge in fully_refunded}, now)
        changed = order.status != target
        if changed:
            repository.set_order_status(order.id, target, now)
        if changed or repaired_duplicate:
            report.settled.append(order.order_no)
        order.status = target
    return report


def _canonical_charge(order_id: int, active: list[paylink.Charge]) -> paylink.Charge:
    """Prefer a provider id accepted locally; otherwise retain the earliest charge."""
    active_by_id = {charge.id: charge for charge in active}
    locally_accepted = [
        active_by_id[row.provider_charge_id]
        for row in repository.list_charges(order_id)
        if row.status == ChargeStatus.SUCCEEDED and row.provider_charge_id in active_by_id
    ]
    candidates = locally_accepted or active
    return min(candidates, key=lambda charge: (charge.created_at is None, charge.created_at, charge.id))


def _target_status(
    provider_charges: list[paylink.Charge],
    successful: list[paylink.Charge],
    active: list[paylink.Charge],
    fully_refunded: list[paylink.Charge],
) -> str | None:
    if len(active) == 1:
        return Status.PAID
    if not active and successful and len(fully_refunded) == len(successful):
        return Status.REFUNDED
    if not successful:
        statuses = {charge.status for charge in provider_charges}
        if statuses == {"failed"}:
            return Status.FAILED
        if statuses <= {"failed", "requires_action"} and "requires_action" in statuses:
            return Status.PENDING
    return None


def _sync_charge_rows(order, provider_charges, refunded_ids: set[str], now) -> None:
    stored = repository.list_charges(order.id)
    by_provider_id = {row.provider_charge_id: row for row in stored if row.provider_charge_id}
    unassigned = [row for row in stored if not row.provider_charge_id]

    for provider_charge in provider_charges:
        status = ChargeStatus.UNKNOWN
        error = ""
        if provider_charge.id in refunded_ids:
            status = ChargeStatus.REFUNDED
        elif provider_charge.status == "succeeded":
            status = ChargeStatus.SUCCEEDED
        elif provider_charge.status == "failed":
            status = ChargeStatus.FAILED
            error = "provider status: failed"
        else:
            error = f"provider status: {provider_charge.status or 'missing'}"

        row = by_provider_id.get(provider_charge.id)
        if row is None and unassigned:
            row = unassigned.pop(0)
        if row is not None:
            repository.update_charge(
                row.id,
                provider_charge.id,
                status,
                max(row.attempts, 1),
                error,
                now,
            )
            continue

        created_at = provider_charge.created_at or order.created_at
        repository.insert_charge(
            Charge(
                order_id=order.id,
                provider_charge_id=provider_charge.id,
                amount_jpy=provider_charge.amount,
                status=status,
                attempts=1,
                last_error=error,
                created_at=created_at,
                updated_at=now,
            )
        )
