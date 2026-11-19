#!/bin/bash
# T-8260: полный серверный прогон под общей блокировкой и systemd (TASKS-008).
set -u
ROOT=/home/gpgr/Документы/CRM
BASE="$ROOT/crm-work/slice008/stage3/T-8260"
OUT="$BASE/full-all-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
cd "$ROOT" || exit 99
printf 'running\n' > "$BASE/full.status"
flock /home/gpgr/Документы/crm-work/slice005/stage2/test.lock -c \
  'docker compose -f deploy/docker-compose.yml --profile test run --rm --no-deps test -q' \
  > "$OUT/full.log" 2>&1
result=$?
printf '%s\n' "$result" > "$OUT/full.exit"
printf '%s\n' "$OUT" > "$BASE/last-run.txt"
if [ "$result" -eq 0 ]; then printf 'passed\n' > "$BASE/full.status"; else printf 'failed\n' > "$BASE/full.status"; fi
exit "$result"
