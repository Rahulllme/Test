from django.urls import path, re_path

from . import views

urlpatterns = [
    path("health", views.route(GET=views.health)),
    path("orders", views.route(GET=views.list_orders, POST=views.place_order)),
    path("orders/<str:order_no>", views.route(GET=views.get_order)),
    path("orders/<str:order_no>/refund", views.route(POST=views.refund)),
    path("admin/orders/<str:order_no>/charges", views.route(GET=views.order_charges)),
    path("admin/reconcile", views.route(POST=views.reconcile)),
    re_path(r"", views.not_found),
]
