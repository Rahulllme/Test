import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from django.test import Client

import paylink
from orders.clock import ManualClock
from orders.container import set_service
from orders.models import ChargeStatus, Status
from orders.service import Service


class FakeProvider:
    """Stands in for Paylink in tests. It behaves the way docs/paylink-api.md describes the
    provider."""

    def __init__(self):
        self._lock = threading.Lock()
        self.charges: list[paylink.Charge] = []
        self.refunds: list[paylink.Refund] = []
        self.sequence = 0

    def create_charge(self, reference, amount, card_token):
        with self._lock:
            if card_token == "tok_insufficient":
                raise paylink.HTTPError(402, "card_declined")
            self.sequence += 1
            now = datetime.now(timezone.utc)
            charge = paylink.Charge(
                id=f"ch_{self.sequence:024d}",
                reference=reference,
                amount=amount,
                currency="JPY",
                status="succeeded",
                card_token=card_token,
                created_at=now,
                updated_at=now,
            )
            self.charges.append(charge)
            return charge

    def get_charge(self, charge_id):
        with self._lock:
            for charge in self.charges:
                if charge.id == charge_id:
                    return charge
            raise paylink.HTTPError(404, "not_found")

    def list_charges(self, reference):
        with self._lock:
            return [charge for charge in self.charges if reference == "" or charge.reference == reference]

    def create_refund(self, charge_id, amount):
        with self._lock:
            for charge in self.charges:
                if charge.id != charge_id:
                    continue
                self.sequence += 1
                refund = paylink.Refund(
                    id=f"rf_{self.sequence:024d}",
                    charge_id=charge_id,
                    amount=amount,
                    status="succeeded",
                    created_at=datetime.now(timezone.utc),
                )
                self.refunds.append(refund)
                charge.refunded_amount += amount
                return refund
            raise paylink.HTTPError(404, "not_found")

    def list_refunds(self, charge_id):
        with self._lock:
            return [refund for refund in self.refunds if charge_id == "" or refund.charge_id == charge_id]


@dataclass
class Fixture:
    service: Service
    provider: FakeProvider
    clock: ManualClock
    client: Client

    def post(self, path, body=None):
        if body is None:
            return self.client.post(path)
        return self.client.post(path, data=json.dumps(body), content_type="application/json")


@pytest.fixture
def f(transactional_db):
    # Each test runs against the test database built from the migrations, emptied afterwards.
    provider = FakeProvider()
    clock = ManualClock(datetime(2026, 9, 1, tzinfo=timezone.utc))
    service = Service(provider, clock)
    set_service(service)
    yield Fixture(service=service, provider=provider, clock=clock, client=Client())
    set_service(None)


def place_order(order_no, email, amount, token):
    return {"order_no": order_no, "customer_email": email, "amount_jpy": amount, "card_token": token}


def test_place_order_charges_the_card_and_stores_the_paid_order(f):
    w = f.post("/orders", place_order("ord-3001", "a@example.com", 4500, "tok_visa"))
    assert w.status_code == 201, w.content
    body = w.json()
    assert body["status"] == Status.PAID and body["amount_jpy"] == 4500, body
    charges = f.service.charges("ord-3001")
    assert len(charges) == 1, charges
    assert charges[0].status == ChargeStatus.SUCCEEDED and charges[0].provider_charge_id != ""


def test_order_response_hides_internal_fields(f):
    assert f.post("/orders", place_order("ord-3002", "b@example.com", 1000, "tok_visa")).status_code == 201
    w = f.client.get("/orders/ord-3002")
    assert w.status_code == 200
    body = w.json()
    assert len(body) == 6, f"unexpected response shape: {body}"
    for hidden in ("id", "provider_charge_id", "card_token"):
        assert hidden not in body, f"{hidden} leaked: {body}"


def test_duplicate_order_number_is_rejected(f):
    order = place_order("ord-3003", "c@example.com", 2000, "tok_visa")
    assert f.post("/orders", order).status_code == 201
    w = f.post("/orders", order)
    assert w.status_code == 409, f"second order accepted: status={w.status_code} body={w.content}"


def test_declined_card_leaves_the_order_unpaid(f):
    w = f.post("/orders", place_order("ord-3004", "d@example.com", 3000, "tok_insufficient"))
    assert w.status_code == 201, w.content
    value = f.service.get("ord-3004")
    assert value.status != Status.PAID, f"declined card produced a paid order: {value.status}"


def test_refund_marks_the_order_refunded(f):
    assert f.post("/orders", place_order("ord-3005", "e@example.com", 6000, "tok_visa")).status_code == 201
    f.clock.set(f.clock.now() + timedelta(hours=1))
    w = f.post("/orders/ord-3005/refund")
    assert w.status_code == 200, w.content
    assert f.service.get("ord-3005").status == Status.REFUNDED
    refunds = f.provider.list_refunds("")
    assert len(refunds) == 1, refunds
