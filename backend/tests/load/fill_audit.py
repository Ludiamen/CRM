"""Журнал стенда для нагрузочного прогона T-304 (NFR-002, PLAN-001 версия 4): дополняет журнал событий
синтетическими записями до LOAD_AUDIT_EVENTS (по умолчанию 300 000 — 3 года хранения, FR-045, при нагрузке
среза около 400 событий в день). События разбросаны по последним 3 годам; действующие лица — сотрудники стенда
(3 % — «система»). Смесь действий — оценка Opus, а не замер: вход 55 %, выход 15 %, неудачный вход 10 %,
письма 6 %, правка профиля 6 % (с «было/стало»), смена пароля 3 %, роли 2 %, настройки 1,5 %, блокировка 1,5 %.
Работает ТОЛЬКО при E2E_STAND=1; записи убирает следующий сброс приёмки (e2e_reset_stand). Вход — как у
prepare_users.py:

    docker compose -f deploy/docker-compose.yml --profile dev exec -T -e LOAD_AUDIT_EVENTS=300000 standtools \
        python manage.py shell --no-imports < backend/tests/load/fill_audit.py
"""
import os
import sys

from django.db import connection

from apps.core.models import AuditEvent

FILL_SQL = """
INSERT INTO core_auditevent (at, actor_id, action, object_type, object_id, before, after, ip)
SELECT now() - random() * interval '1095 days',
       CASE WHEN r < 0.03 THEN NULL ELSE u.ids[1 + floor(random() * cardinality(u.ids))::int] END,
       CASE WHEN r < 0.55 THEN 'login.success' WHEN r < 0.70 THEN 'logout' WHEN r < 0.80 THEN 'login.failed'
            WHEN r < 0.86 THEN 'mail.status_changed' WHEN r < 0.92 THEN 'user.updated'
            WHEN r < 0.95 THEN 'password.changed' WHEN r < 0.97 THEN 'role.assigned'
            WHEN r < 0.985 THEN 'security_settings.updated' ELSE 'account.locked' END,
       'user', u.ids[1 + floor(random() * cardinality(u.ids))::int]::text,
       CASE WHEN r >= 0.86 AND r < 0.92 THEN '{"position": "Инженер"}'::jsonb ELSE '{}'::jsonb END,
       CASE WHEN r >= 0.86 AND r < 0.92 THEN '{"position": "Ведущий инженер"}'::jsonb ELSE '{}'::jsonb END,
       ('10.0.' || floor(random() * 255)::int || '.' || floor(random() * 255)::int)::inet
FROM (SELECT random() AS r FROM generate_series(1, %s)) AS g,
     (SELECT array_agg(id) AS ids FROM core_user) AS u
"""

if os.environ.get("E2E_STAND") != "1":
    sys.exit("Скрипт работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено.")

target = int(os.environ.get("LOAD_AUDIT_EVENTS", "300000"))
missing = target - AuditEvent.objects.count()
if missing > 0:
    with connection.cursor() as cursor:  # статистику планировщика обновит автоочистка PostgreSQL
        cursor.execute(FILL_SQL, [missing])
print(f"событий в журнале: {AuditEvent.objects.count()} (добавлено {max(missing, 0)})")
