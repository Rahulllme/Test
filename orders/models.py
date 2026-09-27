from datetime import datetime, timezone

from django.db import models


class Status:
    # PENDING is an order whose charge has not been settled yet.
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class ChargeStatus:
    # UNKNOWN is recorded when the provider call did not return an answer.
    UNKNOWN = "unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


class Order(models.Model):
    id = models.BigAutoField(primary_key=True)
    order_no = models.TextField(unique=True)
    customer_email = models.TextField()
    amount_jpy = models.BigIntegerField()
    status = models.TextField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "orders"


class Charge(models.Model):
    id = models.BigAutoField(primary_key=True)
    order = models.ForeignKey(Order, on_delete=models.DO_NOTHING, related_name="charges")
    provider_charge_id = models.TextField(default="")
    amount_jpy = models.BigIntegerField()
    status = models.TextField()
    attempts = models.IntegerField(default=0)
    last_error = models.TextField(default="")
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "charges"


def format_time(value: datetime) -> str:
    """RFC 3339 in UTC, e.g. 2026-08-01T03:00:00Z."""
    value = value.astimezone(timezone.utc)
    text = value.strftime("%Y-%m-%dT%H:%M:%S")
    if value.microsecond:
        text += ("." + f"{value.microsecond:06d}").rstrip("0")
    return text + "Z"


def public_response(value: Order) -> dict:
    """The customer-facing shape of an order. Provider identifiers and internal bookkeeping stay
    out of it."""
    return {
        "order_no": value.order_no,
        "customer_email": value.customer_email,
        "amount_jpy": value.amount_jpy,
        "status": value.status,
        "created_at": format_time(value.created_at),
        "updated_at": format_time(value.updated_at),
    }


def charge_record(value: Charge) -> dict:
    """The operator view of one charge row."""
    return {
        "id": value.id,
        "order_id": value.order_id,
        "provider_charge_id": value.provider_charge_id,
        "amount_jpy": value.amount_jpy,
        "status": value.status,
        "attempts": value.attempts,
        "last_error": value.last_error,
        "created_at": format_time(value.created_at),
        "updated_at": format_time(value.updated_at),
    }
