#!/bin/sh
# Резервная копия портала (NFR-210): дамп базы и архивы томов protected и media в /backups.
# Адрес базы берётся из DATABASE_MIGRATE_URL (учётная запись владельца схемы); пароль в скрипте не хранится.
set -eu

DAY=$(date +%F)
OUT=/backups

pg_dump -Fc -d "$DATABASE_MIGRATE_URL" -f "$OUT/crm-$DAY.dump"
tar -czf "$OUT/protected-$DAY.tgz" -C /data/protected .
tar -czf "$OUT/media-$DAY.tgz" -C /data/media .

# Копии старше 14 дней стираются
find "$OUT" -type f \( -name 'crm-*.dump' -o -name 'protected-*.tgz' -o -name 'media-*.tgz' \) -mtime +14 -delete
