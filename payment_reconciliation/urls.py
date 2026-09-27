from orders.urls import urlpatterns  # noqa: F401
from orders.views import bad_request, not_found, server_error

handler400 = bad_request
handler404 = not_found
handler500 = server_error
