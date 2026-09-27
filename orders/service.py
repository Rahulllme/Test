from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from django.db import IntegrityError, transaction

import paylink

from . import repository
from .errors import Conflict, InvalidRequest, NotFound
from .models import Charge, ChargeStatus, Order, Status


class Provider(Protocol):
    """The part of the Paylink client this service uses."""

    def create_charge(self, reference: str, amount: int, card_token: str) -> paylink.Charge: ...
    def get_charge(self, charge_id: str) -> paylink.Charge: ...
    def list_charges(self, reference: str) -> list[paylink.Charge]: ...
    def create_refund(self, charge_id: str, amount: int) -> paylink.Refund: ...
    def list_refunds(self, charge_id: str) -> list[paylink.Refund]: ...


@dataclass
class PlaceOrderInput:
    order_no: str = ""
    customer_email: str = ""
    amount_jpy: int = 0
    card_token: str = ""


# How often the provider call is retried when it produced no definitive result.  The Paylink
# client sends a stable idempotency key, so repeating one logical charge cannot move money twice.
CHARGE_ATTEMPTS = 3


class Service:
    def __init__(self, provider: Provider, clock):
        self.provider = provider
        self.clock = clock

    def place_order(self, input: PlaceOrderInput) -> Order:
        """Persist the intent before contacting Paylink, then record its definitive result."""
        if not input.order_no or not input.customer_email or input.amount_jpy <= 0 or not input.card_token:
            raise InvalidRequest()
        try:
            with transaction.atomic():
                now = self.clock.now()
                stored = repository.insert_order(
                    Order(
                        order_no=input.order_no,
                        customer_email=input.customer_email,
                        amount_jpy=input.amount_jpy,
                        status=Status.PENDING,
                        created_at=now,
                        updated_at=now,
                    )
                )
                charge_row = Charge(
                    order_id=stored.id,
                    amount_jpy=stored.amount_jpy,
                    status=ChargeStatus.UNKNOWN,
                    attempts=0,
                    created_at=now,
                    updated_at=now,
                )
                repository.insert_charge(charge_row)
        except IntegrityError as exc:
            # The order number is the public idempotency boundary of this API.  Do not contact
            # Paylink after another request has already claimed it.
            try:
                repository.find_order(input.order_no)
            except Order.DoesNotExist:
                raise
            raise Conflict() from exc

        last_error = ""
        for attempt in range(1, CHARGE_ATTEMPTS + 1):
            try:
                provider_charge = self.provider.create_charge(
                    stored.order_no, stored.amount_jpy, input.card_token
                )
            except paylink.HTTPError as exc:
                last_error = str(exc)
                repository.update_charge(
                    charge_row.id, "", ChargeStatus.UNKNOWN, attempt, last_error, self.clock.now()
                )
                if exc.status == 409:
                    # An idempotency conflict can mean Paylink already has a result for this key.
                    # It is not evidence that no charge exists, so reconciliation must decide.
                    self._finish_charge(
                        stored, charge_row, "", ChargeStatus.UNKNOWN, attempt, last_error
                    )
                    return stored
                if 400 <= exc.status < 500 and exc.status not in (408, 429):
                    self._finish_charge(stored, charge_row, "", ChargeStatus.FAILED, attempt, last_error)
                    return stored
                continue
            except paylink.PaylinkError as exc:
                last_error = str(exc)
                repository.update_charge(
                    charge_row.id, "", ChargeStatus.UNKNOWN, attempt, last_error, self.clock.now()
                )
                continue

            error = self._validate_charge(provider_charge, stored)
            if error:
                provider_id = ""
                if (
                    isinstance(provider_charge, paylink.Charge)
                    and isinstance(provider_charge.id, str)
                    and provider_charge.id.strip()
                ):
                    provider_id = provider_charge.id
                self._finish_charge(
                    stored, charge_row, provider_id, ChargeStatus.UNKNOWN, attempt, error
                )
                return stored
            if provider_charge.status == "succeeded":
                self._finish_charge(
                    stored, charge_row, provider_charge.id, ChargeStatus.SUCCEEDED, attempt, ""
                )
                return stored
            if provider_charge.status == "failed":
                self._finish_charge(
                    stored,
                    charge_row,
                    provider_charge.id,
                    ChargeStatus.FAILED,
                    attempt,
                    "provider status: failed",
                )
                return stored

            # ``requires_action`` and future statuses are not successful charges.  They also are
            # not safe to call failures: Paylink may still transition them later.
            self._finish_charge(
                stored,
                charge_row,
                provider_charge.id,
                ChargeStatus.UNKNOWN,
                attempt,
                f"provider status: {provider_charge.status or 'missing'}",
            )
            return stored

        # A timeout is not proof of failure.  Reconciliation can discover the provider record.
        stored.status = Status.PENDING
        stored.updated_at = self.clock.now()
        return stored

    def _validate_charge_shape(self, charge: paylink.Charge) -> str:
        if not isinstance(charge, paylink.Charge):
            return "provider returned an invalid charge object"
        if not isinstance(charge.id, str) or not charge.id.strip():
            return "provider returned a charge without an id"
        if not isinstance(charge.reference, str) or not charge.reference:
            return "provider returned an invalid charge reference"
        if isinstance(charge.amount, bool) or not isinstance(charge.amount, int) or charge.amount <= 0:
            return "provider returned an invalid charge amount"
        if (
            isinstance(charge.refunded_amount, bool)
            or not isinstance(charge.refunded_amount, int)
            or charge.refunded_amount < 0
        ):
            return "provider returned an invalid refunded amount"
        if not isinstance(charge.currency, str) or not charge.currency:
            return "provider returned an invalid charge currency"
        if not isinstance(charge.status, str) or not charge.status.strip():
            return "provider returned an invalid charge status"
        if (
            not isinstance(charge.created_at, datetime)
            or charge.created_at.tzinfo is None
            or not isinstance(charge.updated_at, datetime)
            or charge.updated_at.tzinfo is None
            or charge.updated_at < charge.created_at
        ):
            return "provider returned invalid charge timestamps"
        return ""

    def _validate_charge(self, charge: paylink.Charge, order: Order) -> str:
        error = self._validate_charge_shape(charge)
        if error:
            return error
        if not isinstance(charge.reference, str) or charge.reference != order.order_no:
            return "provider returned a mismatched reference"
        if (
            charge.amount != order.amount_jpy
            or charge.currency != "JPY"
        ):
            return "provider returned a mismatched amount or currency"
        return ""

    def _validate_refund(
        self,
        refund: paylink.Refund,
        charge_id: str | None = None,
        amount: int | None = None,
    ) -> str:
        if not isinstance(refund, paylink.Refund):
            return "provider returned an invalid refund object"
        if not isinstance(refund.id, str) or not refund.id.strip():
            return "provider returned a refund without an id"
        if not isinstance(refund.charge_id, str) or not refund.charge_id.strip():
            return "provider returned a refund without a charge id"
        if charge_id is not None and refund.charge_id != charge_id:
            return "provider returned a refund for a different charge"
        if isinstance(refund.amount, bool) or not isinstance(refund.amount, int) or refund.amount <= 0:
            return "provider returned an invalid refund amount"
        if amount is not None and refund.amount != amount:
            return "provider returned a refund for a different amount"
        if not isinstance(refund.status, str) or not refund.status.strip():
            return "provider returned an invalid refund status"
        if not isinstance(refund.created_at, datetime) or refund.created_at.tzinfo is None:
            return "provider returned an invalid refund timestamp"
        return ""

    def _finish_charge(
        self,
        order: Order,
        charge_row: Charge,
        provider_charge_id: str,
        charge_status: str,
        attempts: int,
        error: str,
    ) -> None:
        order_status = Status.PENDING
        if charge_status == ChargeStatus.SUCCEEDED:
            order_status = Status.PAID
        elif charge_status == ChargeStatus.FAILED:
            order_status = Status.FAILED
        with transaction.atomic():
            now = self.clock.now()
            repository.update_charge(
                charge_row.id, provider_charge_id, charge_status, attempts, error, now
            )
            repository.set_order_status(order.id, order_status, now)
        order.status = order_status
        order.updated_at = now

    def get(self, order_no: str) -> Order:
        try:
            return repository.find_order(order_no)
        except Order.DoesNotExist as exc:
            raise NotFound() from exc

    def list(self) -> list[Order]:
        return repository.list_orders()

    def charges(self, order_no: str) -> list[Charge]:
        value = self.get(order_no)
        return repository.list_charges(value.id)

    def refund(self, order_no: str) -> Order:
        """Returns the money for an order. The order row is locked for the duration so two refunds
        for the same order cannot overlap."""
        with transaction.atomic():
            try:
                value = repository.find_order_for_update(order_no)
            except Order.DoesNotExist as exc:
                raise NotFound() from exc
            if value.status == Status.REFUNDED:
                return value
            if value.status != Status.PAID:
                raise Conflict()
            charges = repository.list_charges(value.id)
            candidates = [
                charge
                for charge in charges
                if charge.status == ChargeStatus.SUCCEEDED
                and charge.provider_charge_id
                and charge.amount_jpy == value.amount_jpy
            ]
            provider_ids = {charge.provider_charge_id for charge in candidates}
            if len(provider_ids) != 1:
                raise Conflict()
            charge = candidates[0]
            provider_charge = self.provider.get_charge(charge.provider_charge_id)
            if self._validate_charge(provider_charge, value) or provider_charge.status != "succeeded":
                raise Conflict()

            refunds = self.provider.list_refunds(charge.provider_charge_id)
            if not isinstance(refunds, list):
                raise paylink.PaylinkError("paylink: invalid refund list")
            for item in refunds:
                error = self._validate_refund(item, charge.provider_charge_id)
                if error:
                    raise paylink.PaylinkError(f"paylink: {error}")
                if item.status not in ("succeeded", "failed"):
                    raise paylink.PaylinkError("paylink: unresolved refund status")
            refunded = sum(item.amount for item in refunds if item.status == "succeeded")
            if refunded not in (0, value.amount_jpy):
                raise Conflict()
            if refunded == 0:
                refund = self.provider.create_refund(charge.provider_charge_id, value.amount_jpy)
                error = self._validate_refund(refund, charge.provider_charge_id, value.amount_jpy)
                if error or refund.status != "succeeded":
                    raise paylink.PaylinkError(f"paylink: {error or 'refund did not succeed'}")
            now = self.clock.now()
            repository.update_charge(
                charge.id, charge.provider_charge_id, ChargeStatus.REFUNDED, charge.attempts, "", now
            )
            repository.set_order_status(value.id, Status.REFUNDED, now)
        value.status = Status.REFUNDED
        value.updated_at = now
        return value

    def reconcile(self):
        from .reconcile import reconcile

        return reconcile(self)
