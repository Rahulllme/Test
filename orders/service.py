from __future__ import annotations

from dataclasses import dataclass
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


# How often the provider call is retried on a transport error.
CHARGE_ATTEMPTS = 3


class Service:
    def __init__(self, provider: Provider, clock):
        self.provider = provider
        self.clock = clock

    def place_order(self, input: PlaceOrderInput) -> Order:
        """Stores the order and charges the card as one unit of work, so an order is never stored
        without the charge that belongs to it."""
        if not input.order_no or not input.customer_email or input.amount_jpy <= 0 or not input.card_token:
            raise InvalidRequest()
        with transaction.atomic():
            now = self.clock.now()
            try:
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
            except IntegrityError as exc:
                if "orders_order_no_key" in str(exc):
                    raise Conflict() from exc
                raise

            last_error = None
            for attempt in range(1, CHARGE_ATTEMPTS + 1):
                try:
                    charge = self.provider.create_charge(stored.order_no, stored.amount_jpy, input.card_token)
                except paylink.PaylinkError as exc:
                    last_error = exc
                    continue
                # The provider answered 2xx, so the charge went through.
                repository.insert_charge(
                    Charge(
                        order_id=stored.id,
                        provider_charge_id=charge.id,
                        amount_jpy=stored.amount_jpy,
                        status=ChargeStatus.SUCCEEDED,
                        attempts=attempt,
                        created_at=now,
                        updated_at=self.clock.now(),
                    )
                )
                repository.set_order_status(stored.id, Status.PAID, self.clock.now())
                stored.status = Status.PAID
                return stored

            repository.insert_charge(
                Charge(
                    order_id=stored.id,
                    amount_jpy=stored.amount_jpy,
                    status=ChargeStatus.FAILED,
                    attempts=CHARGE_ATTEMPTS,
                    last_error=str(last_error),
                    created_at=now,
                    updated_at=self.clock.now(),
                )
            )
            repository.set_order_status(stored.id, Status.FAILED, self.clock.now())
            stored.status = Status.FAILED
            return stored

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
            charges = repository.list_charges(value.id)
            if not charges:
                raise NotFound()
            charge = charges[-1]
            self.provider.create_refund(charge.provider_charge_id, value.amount_jpy)
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
