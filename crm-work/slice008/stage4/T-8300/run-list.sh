#!/bin/bash
# T-8300: «Проверить после реализации» плана — серверные файлы под общей блокировкой (TASKS-008).
set -u
ROOT=/home/gpgr/Документы/CRM
BASE="$ROOT/crm-work/slice008/stage4/T-8300"
OUT="$BASE/list-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
cd "$ROOT" || exit 99
printf 'running\n' > "$BASE/list.status"

FILES="tests/test_permissions.py tests/test_sd_access.py tests/test_org_permissions.py tests/test_feed_home.py tests/test_notify_admin.py"

exec 9>/home/gpgr/Документы/crm-work/slice005/stage2/test.lock
flock 9
docker compose -f deploy/docker-compose.yml --profile test run --rm --no-deps test -q $FILES \
  > "$OUT/list.log" 2>&1
result=$?
flock -u 9
printf '%s\n' "$result" > "$OUT/list.exit"
printf '%s\n' "$OUT" > "$BASE/last-list.txt"
if [ "$result" -eq 0 ]; then printf 'passed\n' > "$BASE/list.status"; else printf 'failed\n' > "$BASE/list.status"; fi
exit "$result"