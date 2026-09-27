from django.db import migrations, models
import django.db.models.deletion

INIT_SQL = """
CREATE TABLE IF NOT EXISTS orders (
    id BIGSERIAL PRIMARY KEY,
    order_no TEXT NOT NULL UNIQUE,
    customer_email TEXT NOT NULL,
    amount_jpy BIGINT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS charges (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id),
    provider_charge_id TEXT NOT NULL DEFAULT '',
    amount_jpy BIGINT NOT NULL,
    status TEXT NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS charges_order_id_idx ON charges (order_id);
"""


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.RunSQL(
            sql=INIT_SQL,
            reverse_sql="DROP TABLE IF EXISTS charges; DROP TABLE IF EXISTS orders;",
            state_operations=[
                migrations.CreateModel(
                    name="Order",
                    fields=[
                        ("id", models.BigAutoField(primary_key=True, serialize=False)),
                        ("order_no", models.TextField(unique=True)),
                        ("customer_email", models.TextField()),
                        ("amount_jpy", models.BigIntegerField()),
                        ("status", models.TextField()),
                        ("created_at", models.DateTimeField()),
                        ("updated_at", models.DateTimeField()),
                    ],
                    options={"db_table": "orders"},
                ),
                migrations.CreateModel(
                    name="Charge",
                    fields=[
                        ("id", models.BigAutoField(primary_key=True, serialize=False)),
                        (
                            "order",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.DO_NOTHING,
                                related_name="charges",
                                to="orders.order",
                            ),
                        ),
                        ("provider_charge_id", models.TextField(default="")),
                        ("amount_jpy", models.BigIntegerField()),
                        ("status", models.TextField()),
                        ("attempts", models.IntegerField(default=0)),
                        ("last_error", models.TextField(default="")),
                        ("created_at", models.DateTimeField()),
                        ("updated_at", models.DateTimeField()),
                    ],
                    options={"db_table": "charges"},
                ),
            ],
        ),
    ]
