#!/bin/bash
# T-8300: тесты среза 008 на HEAD (после правок T-8260, коммит 56da46d) под общей блокировкой.
set -u
ROOT=/home/gpgr/Документы/CRM
BASE="$ROOT/crm-work/slice008/stage4/T-8300"
OUT="$BASE/slice-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
cd "$ROOT" || exit 99
printf 'running\n' > "$BASE/slice.status"
FILES=$(cd backend && ls tests/test_messenger_*.py | tr '\n' ' ')

exec 9>/home/gpgr/Документы/crm-work/slice005/stage2/test.lock
flock 9
docker compose -f deploy/docker-compose.yml --profile test run --rm --no-deps test -q $FILES \
  > "$OUT/slice.log" 2>&1
result=$?
flock -u 9
printf '%s\n' "$result" > "$OUT/slice.exit"
printf '%s\n' "$OUT" > "$BASE/last-slice.txt"
if [ "$result" -eq 0 ]; then printf 'passed\n' > "$BASE/slice.status"; else printf 'failed\n' > "$BASE/slice.status"; fi
exit "$result"