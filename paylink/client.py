"""Paylink client for the current API observed in the supplied sandbox.

``docs/paylink-api.md`` records the historical 2023 contract; the compatibility differences and
the resulting safety decisions are documented in ``SOLUTION.md``.
"""

import hashlib
import json
import re
import time
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
            id=_string_field(data, "id", required=True),
            reference=_string_field(data, "reference", required=True),
            amount=_integer_field(data, "amount"),
            currency=_string_field(data, "currency", required=True),
            status=_string_field(data, "status", required=True),
            card_token=_string_field(data, "card_token"),
            refunded_amount=_integer_field(data, "refunded_amount", default=0),
            created_at=_time_field(data, "created_at"),
            updated_at=_time_field(data, "updated_at"),
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
            id=_string_field(data, "id", required=True),
            charge_id=_string_field(data, "charge_id", required=True),
            amount=_integer_field(data, "amount"),
            status=_string_field(data, "status", required=True),
            created_at=_time_field(data, "created_at"),
        )


# Paylink serves the current contract even when the old version is requested.  Keep this explicit
# so production and the sandbox agree about the representation we parse.
API_VERSION = "2026-04-01"
PAGE_SIZE = 5
REQUEST_ATTEMPTS = 3


class PaylinkError(Exception):
    """A call to Paylink that did not produce a result."""


class HTTPError(PaylinkError):
    """Raised for a non-2xx response."""

    def __init__(self, status: int, code: str):
        super().__init__(f"paylink: http {status} ({code})")
        self.status = status
        self.code = code


def _string_field(data: dict, name: str, required: bool = False) -> str:
    if not isinstance(data, dict):
        raise PaylinkError("paylink: invalid response shape")
    value = data.get(name, "")
    if not isinstance(value, str) or (required and not value.strip()):
        raise PaylinkError(f"paylink: invalid {name}")
    return value


def _integer_field(data: dict, name: str, default=None) -> int:
    if not isinstance(data, dict):
        raise PaylinkError("paylink: invalid response shape")
    value = data.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PaylinkError(f"paylink: invalid {name}")
    return value


def _time_field(data: dict, name: str) -> datetime:
    if not isinstance(data, dict):
        raise PaylinkError("paylink: invalid response shape")
    value = data.get(name)
    if not isinstance(value, str) or not value:
        raise PaylinkError(f"paylink: invalid {name}")
    try:
        parsed = parse_time(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PaylinkError(f"paylink: invalid {name}") from exc
    if parsed is None:
        raise PaylinkError(f"paylink: invalid {name}")
    return parsed


class Client:
    def __init__(self, base_url: str, sleep=time.sleep):
        self._base_url = base_url
        self._session = requests.Session()
        self._timeout = 3  # seconds
        self._sleep = sleep

    def create_charge(self, reference: str, amount: int, card_token: str) -> Charge:
        """Charges the card."""
        body = {"amount": amount, "currency": "JPY", "card_token": card_token, "reference": reference}
        return Charge.from_json(
            self._do("POST", "/v1/charges", body, idempotency_key=_key("charge", reference))
        )

    def get_charge(self, charge_id: str) -> Charge:
        return Charge.from_json(self._do("GET", "/v1/charges/" + quote(charge_id, safe="")))

    def list_charges(self, reference: str) -> list[Charge]:
        """Returns charges for a reference, or every charge when reference is empty.

        Paylink 2026 ignores its old ``reference`` query parameter and caps a page at five, so
        filtering has to happen after every page has been read.
        """
        values = [Charge.from_json(item) for item in self._list_pages("/v1/charges")]
        if not reference:
            return values
        return [value for value in values if value.reference == reference]

    def create_refund(self, charge_id: str, amount: int) -> Refund:
        """Refunds a charge once.

        Unlike charges, the current Paylink sandbox does not deduplicate refunds carrying the
        same idempotency key.  A transport error is therefore left unresolved for the caller to
        inspect with ``list_refunds`` instead of blindly repeating a money-moving request.
        """
        body = {"charge_id": charge_id, "amount": amount}
        return Refund.from_json(
            self._do(
                "POST",
                "/v1/refunds",
                body,
                idempotency_key=_key("refund", charge_id, str(amount)),
                retry_ambiguous=False,
            )
        )

    def list_refunds(self, charge_id: str) -> list[Refund]:
        values = [Refund.from_json(item) for item in self._list_pages("/v1/refunds")]
        if not charge_id:
            return values
        return [value for value in values if value.charge_id == charge_id]

    def _list_pages(self, path: str) -> list[dict]:
        result: list[dict] = []
        cursor = ""
        seen: set[str] = set()
        while True:
            query = f"?limit={PAGE_SIZE}"
            if cursor:
                query += "&cursor=" + quote(cursor, safe="")
            page = self._do("GET", path + query)
            data = page.get("data")
            if not isinstance(data, list):
                raise PaylinkError("paylink: invalid list response")
            if any(not isinstance(item, dict) for item in data):
                raise PaylinkError("paylink: invalid list item")
            result.extend(data)
            next_cursor = page.get("next_cursor") or ""
            if not isinstance(next_cursor, str):
                raise PaylinkError("paylink: invalid next cursor")
            if not next_cursor:
                return result
            if next_cursor in seen:
                raise PaylinkError("paylink: repeated next cursor")
            seen.add(next_cursor)
            cursor = next_cursor

    def _do(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        idempotency_key: str = "",
        retry_ambiguous: bool = True,
    ) -> dict:
        headers = {"X-Paylink-Api-Version": API_VERSION}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body)
        response = None
        last_error = None
        for attempt in range(REQUEST_ATTEMPTS):
            try:
                response = self._session.request(
                    method, self._base_url + path, data=data, headers=headers, timeout=self._timeout
                )
            except requests.RequestException as exc:
                last_error = exc
                if retry_ambiguous and attempt + 1 < REQUEST_ATTEMPTS:
                    self._sleep(0.1 * (2**attempt))
                    continue
                raise PaylinkError(f"paylink: {exc}") from exc

            if response.status_code == 429 and attempt + 1 < REQUEST_ATTEMPTS:
                self._sleep(_retry_after(response.headers.get("Retry-After")))
                continue
            if retry_ambiguous and response.status_code >= 500 and attempt + 1 < REQUEST_ATTEMPTS:
                self._sleep(0.1 * (2**attempt))
                continue
            break

        if response is None:  # defensive: the loop always returns or assigns a response
            raise PaylinkError(f"paylink: {last_error}")
        if not 200 <= response.status_code <= 299:
            try:
                code = response.json().get("error", "")
            except (ValueError, AttributeError):
                code = ""
            raise HTTPError(response.status_code, code)
        try:
            value = response.json()
        except ValueError as exc:
            raise PaylinkError(f"paylink: decode response: {exc}") from exc
        if not isinstance(value, dict):
            raise PaylinkError("paylink: invalid response shape")
        return value


def _key(operation: str, *parts: str) -> str:
    material = "\x00".join(parts).encode("utf-8")
    return f"orders-{operation}-" + hashlib.sha256(material).hexdigest()


def _retry_after(value: str | None) -> float:
    try:
        delay = float(value or "1")
    except ValueError:
        delay = 1.0
    return max(0.0, min(delay, 30.0))


_FRACTION = re.compile(r"\.(\d+)")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    if not isinstance(value, str):
        raise TypeError("timestamp must be a string")
    # Python keeps microseconds; longer fractions are cut to six digits.
    value = _FRACTION.sub(lambda m: "." + m.group(1)[:6].ljust(6, "0"), value, count=1)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)
