#!/usr/bin/env bash
# T-8302: проверка стенда после обновления (без изменений данных): health, образы, таблицы, страница входа и мессенджер.
set -uo pipefail
umask 077
CRM=/home/gpgr/Документы/CRM
D=$CRM/crm-work/slice008/stage4/T-8302/stand-update
unset COMPOSE_PROJECT_NAME COMPOSE_PROFILES COMPOSE_FILE COMPOSE_ENV_FILE DOCKER_HOST DOCKER_CONTEXT
export COMPOSE_PROFILES=dev
DC=(docker compose -p crm -f "$CRM/deploy/docker-compose.yml" --profile dev)
TAG=${1:?метка копии before-T8302-YYYYMMDD-HHMMSS}
OUT=$(mktemp -d "$D/verify-$TAG-XXXXXX")
trap 'rc=$?; printf "exit=%s\nfinished=%s\n" "$rc" "$(date --iso-8601=seconds)" > "$D/verify-status-$TAG"' EXIT
exec > >(tee -a "$OUT/verify.log") 2>&1
log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }
fail=0

log "health"
"${DC[@]}" ps --format '{{.Service}} {{.Status}}' | tee "$OUT/services.txt"
for s in web web-heavy nginx; do
  grep -q "^$s .*healthy" "$OUT/services.txt" || { log "нет healthy: $s"; fail=1; }
done

log "образы"
NEW=$(docker image inspect crm-portal:local --format '{{.Id}}')
NEW_NGINX=$(docker image inspect crm-portal-nginx:local --format '{{.Id}}')
for service in web web-heavy worker worker-mail worker-inbox worker-notify notify-poller scheduler standtools nginx; do
  ids=$("${DC[@]}" ps -q "$service")
  [ -n "$ids" ] || { log "нет контейнера $service"; fail=1; continue; }
  want=$NEW; [ "$service" = nginx ] && want=$NEW_NGINX
  for container in $ids; do
    [ "$(docker inspect --format '{{.Image}}' "$container")" = "$want" ] || { log "старый образ: $service"; fail=1; }
  done
done

log "код в образе"
"${DC[@]}" exec -T standtools sh -c 'cd /app/backend && DJANGO_SETTINGS_MODULE=config.settings python -c "import django; django.setup(); from apps.messenger.services import page; print(\"page\", len(open(page.__file__, encoding=\"utf-8\").read()))"' || fail=1

log "таблицы"
TABLES=$(docker exec crm-postgres-1 psql -U postgres -d crm -Atc "select count(*) from information_schema.tables where table_schema='public' and table_name like 'messenger%'")
log "таблиц messenger: $TABLES"
[ "${TABLES:-0}" -ge 6 ] || fail=1

log "адреса"
for path in "/login/" "/messenger/" "/messenger/notifications/"; do
  CODE=$(curl -sk -o /dev/null -w '%{http_code}' "https://127.0.0.1:8031$path")
  printf '%s %s\n' "$path" "$CODE"
done
LOGIN=$(curl -sk -o /dev/null -w '%{http_code}' "https://127.0.0.1:8031/login/")
[ "$LOGIN" = "200" ] || { log "страница входа: $LOGIN"; fail=1; }
CODE=$(curl -sk -o /dev/null -w '%{http_code}' "https://127.0.0.1:8031/messenger/")
case "$CODE" in 200|302) ;; *) log "/messenger/: $CODE"; fail=1;; esac

if [ "$fail" -eq 0 ]; then log "готово: стенд соответствует текущему коду"; exit 0; fi
log "есть замечания — см. выше"; exit 1