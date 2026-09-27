"""Talks to the Paylink payment provider.

The integration was written in 2023 against the API generation documented in
docs/paylink-api.md.

TODO(2026-04-12): Paylink から API 更新の案内。連携の見直しが必要。
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote

import requests


@dataclass
class Charge:
    id: str = ""
    reference: str = ""
    amount: int = 0
    currency: str = ""
    status: str = ""
    card_token: str = ""
    refunded_amount: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_json(cls, data: dict) -> "Charge":
        return cls(
            id=data.get("id", ""),
            reference=data.get("reference", ""),
            amount=data.get("amount", 0),
            currency=data.get("currency", ""),
            status=data.get("status", ""),
            card_token=data.get("card_token", ""),
            refunded_amount=data.get("refunded_amount", 0),
            created_at=parse_time(data.get("created_at")),
            updated_at=parse_time(data.get("updated_at")),
        )


@dataclass
class Refund:
    id: str = ""
    charge_id: str = ""
    amount: int = 0
    status: str = ""
    created_at: datetime | None = None

    @classmethod
    def from_json(cls, data: dict) -> "Refund":
        return cls(
            id=data.get("id", ""),
            charge_id=data.get("charge_id", ""),
            amount=data.get("amount", 0),
            status=data.get("status", ""),
            created_at=parse_time(data.get("created_at")),
        )


# The Paylink API generation this integration was written against. It is sent on every request.
API_VERSION = "2023-02-01"


class PaylinkError(Exception):
    """A call to Paylink that did not produce a result."""


class HTTPError(PaylinkError):
    """Raised for a non-2xx response."""

    def __init__(self, status: int, code: str):
        super().__init__(f"paylink: http {status} ({code})")
        self.status = status
        self.code = code


class Client:
    def __init__(self, base_url: str):
        self._base_url = base_url
        self._session = requests.Session()
        self._timeout = 3  # seconds

    def create_charge(self, reference: str, amount: int, card_token: str) -> Charge:
        """Charges the card."""
        body = {"amount": amount, "currency": "JPY", "card_token": card_token, "reference": reference}
        return Charge.from_json(self._do("POST", "/v1/charges", body))

    def get_charge(self, charge_id: str) -> Charge:
        return Charge.from_json(self._do("GET", "/v1/charges/" + quote(charge_id, safe="")))

    def list_charges(self, reference: str) -> list[Charge]:
        """Returns the charges recorded for one reference."""
        page = self._do("GET", "/v1/charges?limit=100&reference=" + quote(reference, safe=""))
        return [Charge.from_json(item) for item in page.get("data") or []]

    def create_refund(self, charge_id: str, amount: int) -> Refund:
        """Refunds a charge."""
        return Refund.from_json(self._do("POST", "/v1/refunds", {"charge_id": charge_id, "amount": amount}))

    def list_refunds(self, charge_id: str) -> list[Refund]:
        page = self._do("GET", "/v1/refunds?charge_id=" + quote(charge_id, safe=""))
        return [Refund.from_json(item) for item in page.get("data") or []]

    def _do(self, method: str, path: str, body: dict | None = None) -> dict:
        headers = {"X-Paylink-Api-Version": API_VERSION}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body)
        try:
            response = self._session.request(
                method, self._base_url + path, data=data, headers=headers, timeout=self._timeout
            )
        except requests.RequestException as exc:
            raise PaylinkError(f"paylink: {exc}") from exc
        if not 200 <= response.status_code <= 299:
            try:
                code = response.json().get("error", "")
            except (ValueError, AttributeError):
                code = ""
            raise HTTPError(response.status_code, code)
        try:
            return response.json()
        except ValueError as exc:
            raise PaylinkError(f"paylink: decode response: {exc}") from exc


_FRACTION = re.compile(r"\.(\d+)")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    # Python keeps microseconds; longer fractions are cut to six digits.
    value = _FRACTION.sub(lambda m: "." + m.group(1)[:6].ljust(6, "0"), value, count=1)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
