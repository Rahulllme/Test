"""Settles orders against the provider. Operations runs it by hand when customers report a
charge the order service does not know about."""

import json

from django.core.management.base import BaseCommand

from orders.container import get_service


class Command(BaseCommand):
    help = "Reconcile orders against Paylink and print the report as JSON."

    def handle(self, *args, **options):
        report = get_service().reconcile()
        self.stdout.write(json.dumps(report.as_json(), indent=2, ensure_ascii=False))
