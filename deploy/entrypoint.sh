#!/bin/sh
# Точка входа образа портала (T-260). Миграции идут под владельцем схемы
# crm_owner (DATABASE_MIGRATE_URL), сам портал работает под crm_app.
# RUN_MIGRATIONS=1 ставит compose только у web: миграции выполняет одна служба.
set -eu

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    if [ -z "${DATABASE_MIGRATE_URL:-}" ]; then
        echo "DATABASE_MIGRATE_URL не задан: миграции не выполнить" >&2
        exit 1
    fi
    python manage.py migrate --database=migrate --noinput
fi

exec "$@"
