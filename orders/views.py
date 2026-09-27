import json
import logging

from django.http import JsonResponse

from .container import get_service
from .errors import Conflict, InvalidRequest, NotFound
from .models import charge_record, public_response
from .service import PlaceOrderInput

logger = logging.getLogger(__name__)

INT64_MAX = 2**63 - 1


def write_json(status: int, value) -> JsonResponse:
    return JsonResponse(value, status=status, safe=False, json_dumps_params={"ensure_ascii": False, "separators": (",", ":")})


def write_error(err: Exception) -> JsonResponse:
    status, code = 500, "internal_error"
    if isinstance(err, InvalidRequest):
        status, code = 400, "invalid_request"
    elif isinstance(err, NotFound):
        status, code = 404, "order_not_found"
    elif isinstance(err, Conflict):
        status, code = 409, "order_conflict"
    else:
        logger.error("request failed", exc_info=err)
    return write_json(status, {"error": code})


def route(**handlers):
    """Dispatches one path by HTTP method."""

    def view(request, **kwargs):
        handler = handlers.get(request.method)
        if handler is None:
            return write_json(405, {"error": "method_not_allowed"})
        try:
            return handler(request, **kwargs)
        except Exception as err:  # every failure answers in the API's error shape
            return write_error(err)

    return view


def decode_place_order(body: bytes) -> PlaceOrderInput:
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise InvalidRequest() from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise InvalidRequest()
    value = PlaceOrderInput()
    for name in ("order_no", "customer_email", "card_token"):
        field = data.get(name)
        if field is None:
            continue
        if not isinstance(field, str):
            raise InvalidRequest()
        setattr(value, name, field)
    amount = data.get("amount_jpy")
    if amount is not None:
        if isinstance(amount, bool) or not isinstance(amount, int) or abs(amount) > INT64_MAX:
            raise InvalidRequest()
        value.amount_jpy = amount
    return value


def health(request):
    return write_json(200, {"status": "ok"})


def place_order(request):
    value = get_service().place_order(decode_place_order(request.body))
    return write_json(201, public_response(value))


def list_orders(request):
    return write_json(200, [public_response(value) for value in get_service().list()])


def get_order(request, order_no):
    return write_json(200, public_response(get_service().get(order_no)))


def refund(request, order_no):
    return write_json(200, public_response(get_service().refund(order_no)))


# Operator endpoints. These are reachable from the internal network only.


def order_charges(request, order_no):
    return write_json(200, [charge_record(value) for value in get_service().charges(order_no)])


def reconcile(request):
    return write_json(200, get_service().reconcile().as_json())


# Fallbacks, so no path answers with an HTML page.


def not_found(request, exception=None):
    return write_json(404, {"error": "not_found"})


def bad_request(request, exception=None):
    return write_json(400, {"error": "invalid_request"})


def server_error(request):
    return write_json(500, {"error": "internal_error"})
