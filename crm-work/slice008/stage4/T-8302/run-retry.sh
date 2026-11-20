#!/usr/bin/env bash
# T-8302: изолированный повтор упавших nodeid (без системных A/B и дефекта пагинатора), сброс перед кругом.
set -uo pipefail
umask 077
CRM=/home/gpgr/Документы/CRM
W=/home/gpgr/Документы/crm-work
D=$CRM/crm-work/slice008/stage4/T-8302/retry
LOCK=$W/slice005/stage2/test.lock
PY=$CRM/.venv/bin/python
OUT=$(mktemp -d "$D/run-XXXXXX")
trap 'rc=$?; printf "exit=%s\nfinished=%s\n" "$rc" "$(date --iso-8601=seconds)" > "$OUT/status"' EXIT
exec > >(tee -a "$OUT/retry.log") 2>&1
log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }
printf 'directory=%s\n' "$OUT"

exec 9>"$LOCK"
if ! flock -n 9; then log 'заблокировано: lock занят'; exit 2; fi
if pgrep -f '[p]ython -m pytest' >/dev/null; then log 'заблокировано: идёт pytest'; exit 2; fi

set -a
. "$CRM/deploy/.env" >/dev/null 2>&1 || { log 'не прочитан deploy/.env'; exit 5; }
set +a
unset COMPOSE_PROJECT_NAME COMPOSE_PROFILES COMPOSE_FILE COMPOSE_ENV_FILE DOCKER_HOST DOCKER_CONTEXT
unset E2E_IDS_FILE E2E_ADMIN_CMD E2E_SHELL_CMD E2E_PORTAL_URL PYTEST_ADDOPTS PYTEST_PLUGINS PYTEST_DISABLE_PLUGIN_AUTOLOAD
export COMPOSE_PROFILES=dev E2E_MAILPIT_URL=http://127.0.0.1:8025
export E2E_RESET_CMD="docker compose -p crm -f $CRM/deploy/docker-compose.yml --profile dev exec -T standtools python manage.py e2e_reset_stand"
export PYTHONPATH="$W/slice005/stage4/t5302/plugin"
export E2E_IDS_FILE="$D/ids.txt"
cd "$CRM/backend" || exit 7

"$PY" -m pytest tests/e2e -p e2e_ids_filter -p no:cacheprovider -q -rfE \
  --junitxml="$OUT/retry.xml" --output="$OUT/artifacts" > "$OUT/retry-pytest.txt" 2>&1
rc=$?
printf 'exit=%s\n' "$rc" > "$OUT/retry.status"
log "готово: exit=$rc результаты=$OUT"
exit "$rc"