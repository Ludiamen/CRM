#!/usr/bin/env bash
# T-8302 (перед приёмкой): проверенная копия -> обновление стенда до текущего кода. Без reset/down/удаления томов.
set -euo pipefail
umask 077
CRM=/home/gpgr/Документы/CRM
W=/home/gpgr/Документы/crm-work
B=$W/stand-backup
BACKUP=$W/slice005/stage4/t5301/backup-stand.sh
LOCK=$W/slice005/stage2/test.lock
D=$CRM/crm-work/slice008/stage4/T-8302/stand-update
unset COMPOSE_PROJECT_NAME COMPOSE_PROFILES COMPOSE_FILE COMPOSE_ENV_FILE DOCKER_HOST DOCKER_CONTEXT
export COMPOSE_PROFILES=dev
DC=(docker compose -p crm -f "$CRM/deploy/docker-compose.yml" --profile dev)
TAG="before-T8302-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$D"
OUT=$(mktemp -d "$D/update-$TAG-XXXXXX")
trap 'rc=$?; printf "exit=%s\nfinished=%s\n" "$rc" "$(date --iso-8601=seconds)" > "$D/status-$TAG"' EXIT
exec > >(tee -a "$OUT/update.log") 2>&1
log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }
printf 'directory=%s\ntag=%s\n' "$OUT" "$TAG"
printf '%s\n' "$TAG" > "$D/last-tag.txt"

exec 9>"$LOCK"
if ! flock -n 9; then log 'заблокировано: test.lock занят'; exit 2; fi
if pgrep -f '[p]ytest' >/dev/null; then log 'заблокировано: идёт pytest'; exit 2; fi
cd "$CRM"
[ -f "$BACKUP" ] || { log 'нет скрипта копии'; exit 3; }
if compgen -G "$B/*$TAG*" >/dev/null; then log 'метка копии занята'; exit 3; fi

log 'копия до изменения служб; содержимое не выводится'
bash "$BACKUP" "$TAG"
for name in "crm-db-$TAG.dump" "crm_media-$TAG.tgz" "crm_protected-$TAG.tgz" "env-$TAG"; do
  [ -s "$B/$name" ] || { log 'нет непустого артефакта копии'; exit 4; }
  [ "$(stat -c '%a' "$B/$name")" = 600 ] || { log 'небезопасные права копии'; exit 4; }
done
docker exec -i crm-postgres-1 pg_restore --list < "$B/crm-db-$TAG.dump" > /dev/null
tar -tzf "$B/crm_media-$TAG.tgz" > /dev/null
tar -tzf "$B/crm_protected-$TAG.tgz" > /dev/null
log 'копия проверена: dump читается, оба архива читаются, четыре файла mode 600'

log 'сборка web'; "${DC[@]}" build web
log 'сборка nginx'; "${DC[@]}" build nginx
log 'миграции'; "${DC[@]}" run --rm --no-deps migrate
log 'обновление служб'
"${DC[@]}" up -d --no-deps web web-heavy worker worker-mail worker-inbox worker-notify notify-poller scheduler standtools nginx
"${DC[@]}" restart nginx
ok=0
for i in $(seq 1 60); do
  st=$("${DC[@]}" ps --format '{{.Service}} {{.Health}}' web web-heavy nginx || true)
  total=$(printf '%s\n' "$st" | grep -c . || true)
  good=$(printf '%s\n' "$st" | grep -c ' healthy$' || true)
  if [ "$total" -ge 3 ] && [ "$total" = "$good" ]; then ok=1; break; fi
  sleep 5
done
if [ "$ok" != 1 ]; then log 'health gate не пройден'; exit 5; fi
NEW=$(docker image inspect crm-portal:local --format '{{.Id}}')
NEW_NGINX=$(docker image inspect crm-portal-nginx:local --format '{{.Id}}')
for service in web web-heavy worker worker-mail worker-inbox worker-notify notify-poller scheduler standtools nginx; do
  ids=$("${DC[@]}" ps -q "$service")
  [ -n "$ids" ] || { log "нет контейнера $service"; exit 6; }
  want=$NEW; [ "$service" = nginx ] && want=$NEW_NGINX
  for container in $ids; do
    [ "$(docker inspect --format '{{.Image}}' "$container")" = "$want" ] || { log "старый образ: $service"; exit 6; }
  done
done

log 'проверка кода среза в образе и в базе'
"${DC[@]}" exec -T standtools sh -c 'cd /app/backend && DJANGO_SETTINGS_MODULE=config.settings python -c "import django; django.setup(); from apps.messenger.services import page; print(\"page\", len(open(page.__file__, encoding=\"utf-8\").read()))"'
TABLES=$(docker exec crm-postgres-1 psql -U postgres -d crm -Atc "select count(*) from information_schema.tables where table_schema='public' and table_name like 'messenger%'")
[ "${TABLES:-0}" -ge 6 ] || { log "в базе нет таблиц мессенджера: $TABLES"; exit 7; }
CODE=$(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1:8031/messenger/)
case "$CODE" in 200|302) ;; *) log "стенд: /messenger/ отвечает $CODE"; exit 7;; esac

"${DC[@]}" ps --format '{{.Service}} {{.Status}}'
log "готово: копия $TAG проверена; health/image gates пройдены; таблиц мессенджера: $TABLES; /messenger/ 200; reset не выполнялся"