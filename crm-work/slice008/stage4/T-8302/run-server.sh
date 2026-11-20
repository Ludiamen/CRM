#!/bin/bash
# T-8302 (после правок): серверные тесты затронутых модулей под общей блокировкой.
set -u
ROOT=/home/gpgr/Документы/CRM
BASE="$ROOT/crm-work/slice008/stage4/T-8302"
OUT="$BASE/server-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
cd "$ROOT" || exit 99
printf 'running\n' > "$BASE/server.status"
FILES=$(cd backend && ls tests/test_messenger_*.py tests/test_notify_*.py tests/test_feed_notify_2.py | tr '\n' ' ')

exec 9>/home/gpgr/Документы/crm-work/slice005/stage2/test.lock
flock 9
docker compose -f deploy/docker-compose.yml --profile test run --rm --no-deps test -q $FILES \
  > "$OUT/server.log" 2>&1
result=$?
flock -u 9
printf '%s\n' "$result" > "$OUT/server.exit"
printf '%s\n' "$OUT" > "$BASE/last-server.txt"
if [ "$result" -eq 0 ]; then printf 'passed\n' > "$BASE/server.status"; else printf 'failed\n' > "$BASE/server.status"; fi
exit "$result"