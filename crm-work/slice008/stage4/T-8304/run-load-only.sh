#!/usr/bin/env bash
# T-8304 (продолжение): стенд уже наполнен (200 чатов, 50 000 сообщений), копия и сброс не повторяются.
# Только проверка остывания, закрепление ядер и два круга нагрузки.
set -uo pipefail
umask 077
CRM=/home/gpgr/Документы/CRM
W=/home/gpgr/Документы/crm-work
D=$CRM/crm-work/slice008/stage4/T-8304
LOCK=$W/slice005/stage2/test.lock
DC=(docker compose -p crm -f "$CRM/deploy/docker-compose.yml" --profile dev)
TAG="load-only-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$D"
log() { echo "$(date '+%F %T') $*" >> "$D/run-load.log"; }
owner() { pgrep -l -u gpgr -x 'yandex_browser|Telegram|chrome|firefox|google-chrome' 2>/dev/null | awk '{print $2}' | sort | uniq -c | tr '\n' ' '; }
# Решение владельца 2026-11-21: порог остывания для этого окна — 2,5 вместо 1,5 (правила T-7304); записано в отчёт.
cool() { for i in $(seq 1 240); do read a b c rest < /proc/loadavg; awk -v a="$a" -v b="$b" 'BEGIN{exit !(a<2.5 && b<2.5)}' && return 0; sleep 10; done; return 1; }
pgconn() { "${DC[@]}" exec -T postgres psql -U postgres -d crm -tAc "select coalesce(usename,'-')||':'||coalesce(state,'-')||'='||count(*) from pg_stat_activity where datname='crm' group by usename,state order by 1" 2>/dev/null | tr '\n' ' '; }
rec() { LC_ALL=C vmstat -t 1 > "$D/vmstat-$1.txt" & V=$!; LC_ALL=C mpstat -P ALL 5 > "$D/mpstat-$1.txt" & M=$!; LC_ALL=C pidstat -u 10 > "$D/pidstat-$1.txt" & P=$!; T0=$(date -u +%FT%TZ); }
unrec() { kill $V $M $P 2>/dev/null; wait $V $M $P 2>/dev/null
  "${DC[@]}" logs --since "$T0" --until "$(date -u +%FT%TZ)" nginx 2>/dev/null | awk '$2 ~ /^\[/ {for(i=3;i<=NF;i++) if($i ~ /^[1-5][0-9][0-9]$/){print $i; break}}' | sort | uniq -c | tr '\n' ' ' > "$D/codes-$1.txt"
  log "$1 коды nginx: $(cat "$D/codes-$1.txt")"; }
run_locust() {
  local tag=$1 classes=$2
  (for i in $(seq 1 78); do echo "$(date '+%T') load=$(cut -d' ' -f1 /proc/loadavg) $(docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' | grep -E 'crm-(web|postgres|worker-notify|nginx|valkey)' | tr '\n' ' ') | $(pgconn)"; sleep 7; done > "$D/stats-$tag.txt") &
  local STATS=$!
  (sleep 130; curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8089/stats/reset > "$D/reset-$tag.txt"; date '+%T' >> "$D/reset-$tag.txt") &
  LOAD_CREDENTIALS="$D/creds.csv" LOAD_NOTIFY_FORM_PER_HOUR=30 LOAD_NOTIFY_MAIL_PER_HOUR=0 \
    taskset -c 3 "$CRM/.venv/bin/locust" -f "$CRM/backend/tests/load/locustfile.py" --autostart --autoquit 5 \
    --web-host 127.0.0.1 --web-port 8089 -u 100 -r 1 -t 9m --host https://127.0.0.1:8031 \
    --csv "$D/$tag" --only-summary $classes > "$D/locust-$tag.log" 2>&1
  log "locust $tag код $? классы $classes"
  wait $STATS
}
exec 9>"$LOCK"; flock -n 9 || { log 'lock занят'; exit 2; }
if pgrep -f '[p]ython -m pytest' >/dev/null; then log 'идёт pytest'; exit 2; fi
set -a; . "$CRM/deploy/.env" >/dev/null 2>&1; set +a
unset COMPOSE_PROJECT_NAME COMPOSE_PROFILES COMPOSE_FILE COMPOSE_ENV_FILE DOCKER_HOST DOCKER_CONTEXT PYTEST_ADDOPTS PYTEST_PLUGINS PYTEST_DISABLE_PLUGIN_AUTOLOAD
export COMPOSE_PROFILES=dev
log "старт $TAG; loadavg $(cat /proc/loadavg); программы владельца: [$(owner)]"
[ "$(docker exec crm-postgres-1 psql -U postgres -d crm -tAc "select count(*) from messenger_message")" -ge 50000 ] || { log 'стенд не наполнен — нужен полный run-t8304'; exit 3; }
for i in $(seq 1 180); do [ -z "$(owner)" ] && break; sleep 10; done
[ -z "$(owner)" ] || { log 'программы владельца не закрыты — СТОП'; exit 5; }
cool || { log 'машина не остыла — СТОП'; exit 5; }
CS=$(docker ps --format '{{.Names}}' | grep '^crm-' | grep -v 'crm-test-run')
for c in $CS; do docker update --cpuset-cpus 0-2 "$c" >/dev/null; done
log "L1 старт: loadavg $(cat /proc/loadavg)"
rec L1; run_locust L1 MessengerUser; unrec L1; log 'L1 готов'
cool || { log 'машина не остыла перед L2 — СТОП'; exit 5; }
rec L2; run_locust L2 "StaffAuditHistoryUser OrgUser ServiceDeskUser NotifyUser KnowledgeUser ListsUser FeedUser MessengerUser"; unrec L2
for c in $CS; do docker update --cpuset-cpus 0-3 "$c" >/dev/null; done
log 'L2 готов; закрепление снято'
touch "$D/run-load.done"