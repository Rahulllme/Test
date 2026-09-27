import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from django.db import close_old_connections
from django.test import Client

import paylink
from orders.clock import ManualClock
from orders.container import set_service
from orders.errors import Conflict
from orders.models import ChargeStatus, Status
from orders.service import PlaceOrderInput, Service


class FakeProvider:
    """Stands in for the current Paylink behavior observed in the supplied sandbox."""

    def __init__(self):
        self._lock = threading.Lock()
        self.charges: list[paylink.Charge] = []
        self.refunds: list[paylink.Refund] = []
        self.sequence = 0

    def create_charge(self, reference, amount, card_token):
        with self._lock:
            self.sequence += 1
            now = datetime.now(timezone.utc)
            status = "succeeded"
            if card_token == "tok_insufficient":
                status = "failed"
            elif card_token == "tok_3ds":
                status = "requires_action"
            charge = paylink.Charge(
                id=f"ch_{self.sequence:024d}",
                reference=reference,
                amount=amount,
                currency="JPY",
                status=status,
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
    assert value.status == Status.FAILED, f"declined card produced the wrong state: {value.status}"
    charge = f.service.charges("ord-3004")[0]
    assert charge.status == ChargeStatus.FAILED and charge.provider_charge_id


def test_legacy_402_decline_is_definitive_and_not_retried(f):
    calls = 0

    def decline(reference, amount, card_token):
        nonlocal calls
        calls += 1
        raise paylink.HTTPError(402, "card_declined")

    f.provider.create_charge = decline
    w = f.post("/orders", place_order("ord-402", "declined@example.com", 3200, "tok_visa"))

    assert w.status_code == 201, w.content
    assert w.json()["status"] == Status.FAILED
    assert calls == 1
    assert f.service.charges("ord-402")[0].attempts == 1


def test_3ds_charge_remains_pending(f):
    w = f.post("/orders", place_order("ord-3ds", "3ds@example.com", 3100, "tok_3ds"))
    assert w.status_code == 201, w.content
    assert w.json()["status"] == Status.PENDING
    charge = f.service.charges("ord-3ds")[0]
    assert charge.status == ChargeStatus.UNKNOWN
    assert "requires_action" in charge.last_error


def test_transport_failure_remains_pending_for_reconciliation(f):
    def unavailable(reference, amount, card_token):
        raise paylink.PaylinkError("connection lost")

    f.provider.create_charge = unavailable
    w = f.post("/orders", place_order("ord-timeout", "t@example.com", 4100, "tok_visa"))

    assert w.status_code == 201, w.content
    assert w.json()["status"] == Status.PENDING
    charge = f.service.charges("ord-timeout")[0]
    assert charge.status == ChargeStatus.UNKNOWN
    assert charge.attempts == 3


def test_temporary_provider_failure_is_retried_and_can_recover(f):
    create_charge = f.provider.create_charge
    calls = 0

    def temporarily_unavailable(reference, amount, card_token):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise paylink.HTTPError(503, "temporarily_unavailable")
        return create_charge(reference, amount, card_token)

    f.provider.create_charge = temporarily_unavailable
    w = f.post("/orders", place_order("ord-temporary", "temp@example.com", 4150, "tok_visa"))

    assert w.status_code == 201, w.content
    assert w.json()["status"] == Status.PAID
    assert calls == 3
    assert f.service.charges("ord-temporary")[0].attempts == 3


def test_malformed_success_response_does_not_mark_order_paid(f):
    def malformed(reference, amount, card_token):
        return paylink.Charge(
            id="ch_wrong",
            reference=reference,
            amount=amount + 1,
            currency="JPY",
            status="succeeded",
        )

    f.provider.create_charge = malformed
    w = f.post("/orders", place_order("ord-malformed", "bad@example.com", 4175, "tok_visa"))

    assert w.status_code == 201, w.content
    assert w.json()["status"] == Status.PENDING
    charge = f.service.charges("ord-malformed")[0]
    assert charge.status == ChargeStatus.UNKNOWN
    assert "mismatched amount" in charge.last_error


def test_idempotency_conflict_is_not_misclassified_as_a_failed_charge(f):
    def conflict(reference, amount, card_token):
        raise paylink.HTTPError(409, "idempotency_conflict")

    f.provider.create_charge = conflict
    w = f.post("/orders", place_order("ord-idem-conflict", "i@example.com", 4200, "tok_visa"))

    assert w.status_code == 201, w.content
    assert w.json()["status"] == Status.PENDING
    charge = f.service.charges("ord-idem-conflict")[0]
    assert charge.status == ChargeStatus.UNKNOWN
    assert charge.attempts == 1


def test_refund_marks_the_order_refunded(f):
    assert f.post("/orders", place_order("ord-3005", "e@example.com", 6000, "tok_visa")).status_code == 201
    f.clock.set(f.clock.now() + timedelta(hours=1))
    w = f.post("/orders/ord-3005/refund")
    assert w.status_code == 200, w.content
    assert f.service.get("ord-3005").status == Status.REFUNDED
    refunds = f.provider.list_refunds("")
    assert len(refunds) == 1, refunds


def test_refund_retry_does_not_issue_a_second_refund(f):
    assert f.post("/orders", place_order("ord-refund-once", "r@example.com", 6100, "tok_visa")).status_code == 201
    assert f.post("/orders/ord-refund-once/refund").status_code == 200
    assert f.post("/orders/ord-refund-once/refund").status_code == 200
    assert len(f.provider.list_refunds("")) == 1


def test_concurrent_refund_requests_issue_one_provider_refund(f):
    assert f.post("/orders", place_order("ord-refund-concurrent", "rc@example.com", 6150, "tok_visa")).status_code == 201
    barrier = threading.Barrier(2)

    def refund():
        close_old_connections()
        try:
            barrier.wait()
            return f.service.refund("ord-refund-concurrent").status
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: refund(), range(2)))

    assert statuses == [Status.REFUNDED, Status.REFUNDED]
    assert len(f.provider.list_refunds("")) == 1


def test_concurrent_duplicate_order_requests_charge_once(f):
    barrier = threading.Barrier(2)
    value = PlaceOrderInput("ord-concurrent", "same@example.com", 6175, "tok_visa")

    def place():
        close_old_connections()
        try:
            barrier.wait()
            try:
                return f.service.place_order(value).status
            except Conflict:
                return "conflict"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: place(), range(2)))

    assert sorted(results) == ["conflict", Status.PAID]
    assert len(f.provider.list_charges("ord-concurrent")) == 1


def test_refund_recovers_after_provider_succeeds_but_response_is_lost(f):
    assert f.post("/orders", place_order("ord-refund-lost", "lost@example.com", 6200, "tok_visa")).status_code == 201
    create_refund = f.provider.create_refund
    lost = True

    def lose_first_response(charge_id, amount):
        nonlocal lost
        refund = create_refund(charge_id, amount)
        if lost:
            lost = False
            raise paylink.PaylinkError("response lost")
        return refund

    f.provider.create_refund = lose_first_response
    assert f.post("/orders/ord-refund-lost/refund").status_code == 500
    assert f.service.get("ord-refund-lost").status == Status.PAID
    assert len(f.provider.list_refunds("")) == 1

    assert f.post("/orders/ord-refund-lost/refund").status_code == 200
    assert f.service.get("ord-refund-lost").status == Status.REFUNDED
    assert len(f.provider.list_refunds("")) == 1


def test_reconcile_refunds_a_conclusive_duplicate_and_keeps_one_charge(f):
    assert f.post("/orders", place_order("ord-duplicate", "d@example.com", 7100, "tok_visa")).status_code == 201
    duplicate = f.provider.create_charge("ord-duplicate", 7100, "tok_visa")

    report = f.service.reconcile()

    assert report.settled == ["ord-duplicate"]
    assert len(f.provider.list_refunds(duplicate.id)) == 1
    assert f.service.get("ord-duplicate").status == Status.PAID
    rows = f.service.charges("ord-duplicate")
    assert sorted(row.status for row in rows) == [ChargeStatus.REFUNDED, ChargeStatus.SUCCEEDED]


def test_reconcile_recovers_a_duplicate_refund_after_its_response_is_lost(f):
    assert f.post("/orders", place_order("ord-duplicate-lost", "dl@example.com", 7200, "tok_visa")).status_code == 201
    duplicate = f.provider.create_charge("ord-duplicate-lost", 7200, "tok_visa")
    create_refund = f.provider.create_refund
    lost = True

    def lose_first_response(charge_id, amount):
        nonlocal lost
        refund = create_refund(charge_id, amount)
        if lost:
            lost = False
            raise paylink.PaylinkError("response lost")
        return refund

    f.provider.create_refund = lose_first_response
    first = f.service.reconcile()
    assert first.unresolved == ["ord-duplicate-lost"]
    assert len(f.provider.list_refunds(duplicate.id)) == 1

    second = f.service.reconcile()
    assert second.unresolved == []
    assert len(f.provider.list_refunds(duplicate.id)) == 1
    rows = f.service.charges("ord-duplicate-lost")
    assert sorted(row.status for row in rows) == [ChargeStatus.REFUNDED, ChargeStatus.SUCCEEDED]


def test_reconcile_does_not_settle_a_mismatched_amount(f):
    assert f.post("/orders", place_order("ord-mismatch", "m@example.com", 8100, "tok_3ds")).status_code == 201
    f.provider.charges[0].amount = 8000

    report = f.service.reconcile()

    assert report.settled == []
    assert report.unresolved == ["ord-mismatch"]
    assert f.service.get("ord-mismatch").status == Status.PENDING
