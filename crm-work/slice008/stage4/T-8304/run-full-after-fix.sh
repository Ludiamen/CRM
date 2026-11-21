#!/bin/bash
# T-8304: полный серверный прогон после правки рассылки (решение владельца 2026-11-21).
# Тот же порядок, что у T-8260: общая блокировка тестов, вывод и статус рядом с задачей.
set -u
ROOT=/home/gpgr/Документы/CRM
BASE="$ROOT/crm-work/slice008/stage4/T-8304"
OUT="$BASE/full-after-fix-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
cd "$ROOT" || exit 99
printf 'running\n' > "$BASE/full-after-fix.status"
flock /home/gpgr/Документы/crm-work/slice005/stage2/test.lock -c \
  'docker compose -f deploy/docker-compose.yml --profile test run --rm --no-deps test -q' \
  > "$OUT/full.log" 2>&1
result=$?
printf '%s\n' "$result" > "$OUT/full.exit"
printf '%s\n' "$OUT" > "$BASE/full-after-fix.last-run"
if [ "$result" -eq 0 ]; then printf 'passed\n' > "$BASE/full-after-fix.status"; else printf 'failed\n' > "$BASE/full-after-fix.status"; fi
exit "$result"