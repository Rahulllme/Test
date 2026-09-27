"""Builds the service the HTTP views and the management commands run against."""

import threading

from django.conf import settings

import paylink

from .clock import SystemClock
from .service import Service

_lock = threading.Lock()
_service = None


def get_service() -> Service:
    global _service
    with _lock:
        if _service is None:
            _service = Service(paylink.Client(settings.PAYLINK_BASE_URL), SystemClock())
        return _service


def set_service(service: Service | None) -> None:
    """Replaces the service, for tests. None goes back to the default one."""
    global _service
    with _lock:
        _service = service
