"""Последовательность номеров заявок (начало с 1, шаг 1).

Права роли приложения на неё даёт `ALTER DEFAULT PRIVILEGES` в deploy/postgres-init.
"""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("servicedesk", "0001_initial"),
    ]
    operations = [
        migrations.RunSQL(
            "CREATE SEQUENCE servicedesk_ticket_number START WITH 1 INCREMENT BY 1",
            reverse_sql="DROP SEQUENCE servicedesk_ticket_number",
        ),
    ]
