#!/usr/bin/env bash
# T-10260: полный зелёный серверный прогон после Этапа 3.
set -u
CRM=/home/gpgr/Документы/CRM
BASE=$CRM/crm-work/slice010/stage3/T-10260
LOCK=/home/gpgr/Документы/crm-work/slice005/stage2/test.lock
OUT=$BASE/full-$(date +%Y%m%d-%H%M%S)
mkdir -p "$OUT" "$BASE"
printf 'running\n' > "$BASE/status"
printf '%s\n' "$OUT" > "$BASE/last-run.txt"
cd "$CRM" || exit 99
(
  printf 'started=%s\n' "$(date --iso-8601=seconds)"
  exec 9>"$LOCK"
  flock 9
  docker compose -f deploy/docker-compose.yml --profile test run --rm --no-deps test -q
  code=$?
  flock -u 9
  printf 'exit=%s\nfinished=%s\n' "$code" "$(date --iso-8601=seconds)"
  exit "$code"
) > "$OUT/full.log" 2>&1
code=$?
printf '%s\n' "$code" > "$OUT/full.exit"
if [ "$code" -eq 0 ]; then printf 'passed\n' > "$BASE/status"; else printf 'failed\n' > "$BASE/status"; fi
exit "$code"
