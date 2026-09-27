import pytest
import requests

import paylink


class Response:
    def __init__(self, status, body, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}

    def json(self):
        return self._body


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def charge(charge_id, reference):
    return {
        "id": charge_id,
        "reference": reference,
        "amount": 1000,
        "currency": "JPY",
        "status": "succeeded",
    }


def test_list_charges_follows_every_page_and_filters_locally():
    client = paylink.Client("https://paylink.test", sleep=lambda _: None)
    client._session = Session(
        [
            Response(200, {"data": [charge("ch_1", "other")], "next_cursor": "off_5"}),
            Response(200, {"data": [charge("ch_2", "wanted")]}),
        ]
    )

    values = client.list_charges("wanted")

    assert [value.id for value in values] == ["ch_2"]
    assert client._session.calls[0][1].endswith("/v1/charges?limit=5")
    assert client._session.calls[1][1].endswith("/v1/charges?limit=5&cursor=off_5")


def test_charge_retries_reuse_the_same_idempotency_key():
    client = paylink.Client("https://paylink.test", sleep=lambda _: None)
    client._session = Session(
        [requests.Timeout("lost response"), Response(201, charge("ch_1", "ord-1"))]
    )

    value = client.create_charge("ord-1", 1000, "tok_visa")

    assert value.id == "ch_1"
    first = client._session.calls[0][2]["headers"]["Idempotency-Key"]
    second = client._session.calls[1][2]["headers"]["Idempotency-Key"]
    assert first == second
    assert client._session.calls[1][2]["headers"]["X-Paylink-Api-Version"] == "2026-04-01"


def test_refund_does_not_retry_an_ambiguous_transport_failure():
    client = paylink.Client("https://paylink.test", sleep=lambda _: None)
    client._session = Session(
        [requests.Timeout("lost response"), Response(201, {"id": "must_not_be_used"})]
    )

    with pytest.raises(paylink.PaylinkError):
        client.create_refund("ch_1", 1000)

    assert len(client._session.calls) == 1


def test_rate_limit_honors_retry_after():
    slept = []
    client = paylink.Client("https://paylink.test", sleep=slept.append)
    client._session = Session(
        [
            Response(429, {"error": "rate_limited"}, {"Retry-After": "2"}),
            Response(200, {"data": []}),
        ]
    )

    assert client.list_refunds("") == []
    assert slept == [2.0]


def test_malformed_list_evidence_is_rejected_instead_of_silently_dropped():
    client = paylink.Client("https://paylink.test", sleep=lambda _: None)
    client._session = Session([Response(200, {"data": ["not-a-charge"]})])

    with pytest.raises(paylink.PaylinkError):
        client.list_charges("")
