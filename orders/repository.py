from datetime import datetime

from .models import Charge, Order


def insert_order(value: Order) -> Order:
    value.save(force_insert=True)
    return value


def find_order(order_no: str) -> Order:
    return Order.objects.get(order_no=order_no)


def find_order_for_update(order_no: str) -> Order:
    """Locks the order row for the rest of the transaction so two refunds for the same order
    cannot run at the same time."""
    return Order.objects.select_for_update().get(order_no=order_no)


def list_orders() -> list[Order]:
    return list(Order.objects.order_by("created_at", "id"))


def list_orders_by_status(status: str) -> list[Order]:
    return list(Order.objects.filter(status=status).order_by("created_at", "id"))


def set_order_status(order_id: int, status: str, now: datetime) -> None:
    Order.objects.filter(id=order_id).update(status=status, updated_at=now)


def list_charges(order_id: int) -> list[Charge]:
    return list(Charge.objects.filter(order_id=order_id).order_by("id"))


def insert_charge(value: Charge) -> None:
    value.save(force_insert=True)


def update_charge(
    charge_id: int, provider_charge_id: str, status: str, attempts: int, last_error: str, now: datetime
) -> None:
    Charge.objects.filter(id=charge_id).update(
        provider_charge_id=provider_charge_id,
        status=status,
        attempts=attempts,
        last_error=last_error,
        updated_at=now,
    )
