import logging

from .views import write_error

logger = logging.getLogger(__name__)


class JSONErrorMiddleware:
    """Turns an exception no view handled into the API's JSON error shape."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        logger.exception("unhandled error on %s %s", request.method, request.path)
        return write_error(exception)
