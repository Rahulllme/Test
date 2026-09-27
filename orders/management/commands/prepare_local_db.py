"""Makes a local database look like production before pending migrations run.

When the orders table does not exist yet, it applies the schema as it stands today (the baseline
migration) and loads the current rows from seed/current_data.sql, the same way a deploy finds an
existing database and migrates it. Then every pending migration is applied. On a database that
already has the orders table only the pending migrations run.
"""

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection, transaction

BASELINE = ("orders", "0001_initial")
SNAPSHOT = settings.BASE_DIR / "seed" / "current_data.sql"


class Command(BaseCommand):
    help = "Prepare the local database: baseline schema and production snapshot on a fresh database, then pending migrations."

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('orders') IS NOT NULL")
            (exists,) = cursor.fetchone()
        if not exists:
            call_command("migrate", *BASELINE, verbosity=options["verbosity"])
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(SNAPSHOT.read_text(encoding="utf-8"))
            self.stdout.write(f"Loaded the production snapshot from {SNAPSHOT.relative_to(settings.BASE_DIR)}.")
        call_command("migrate", verbosity=options["verbosity"])
