#!/usr/bin/env bash
# T-10301/T-10302: браузерные сценарии t10 (BROWSER=chromium|firefox|msedge|yandex|all).
set -uo pipefail
umask 077
CRM=/home/gpgr/Документы/CRM
W=/home/gpgr/Документы/crm-work
D=$CRM/crm-work/slice010/stage4/browser
LOCK=$W/slice005/stage2/test.lock
PY=$CRM/.venv/bin/python
BROWSER=${BROWSER:-chromium}
OUT=$D/run-$BROWSER-$(date +%Y%m%d-%H%M%S)
mkdir -p "$OUT" "$D"
exec > >(tee -a "$OUT/run.log") 2>&1
log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }
printf 'directory=%s\nbrowser=%s\n' "$OUT" "$BROWSER"
printf '%s\n' "$OUT" > "$D/last-$BROWSER.txt"

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
cd "$CRM/backend" || exit 7

"$PY" -m pytest tests/e2e --collect-only -q -p no:cacheprovider > "$OUT/collect-all.txt" 2> "$OUT/collect-errors.txt" || { log 'collection failed'; exit 6; }
if [ "$BROWSER" = "all" ]; then
  grep -E '^tests/e2e/test_t10_[a-z0-9_]+\.py::.*\[(chromium|firefox|msedge|yandex)\]$' "$OUT/collect-all.txt" > "$OUT/ids.txt"
else
  grep -E "^tests/e2e/test_t10_[a-z0-9_]+\.py::.*\[$BROWSER\]\$" "$OUT/collect-all.txt" > "$OUT/ids.txt"
fi
wc -l < "$OUT/ids.txt"
[ -s "$OUT/ids.txt" ] || { log 'пустой список nodeid'; exit 6; }
export E2E_IDS_FILE="$OUT/ids.txt"

"$PY" -m pytest tests/e2e -p e2e_ids_filter -p no:cacheprovider -q -rfE \
  --junitxml="$OUT/main.xml" --output="$OUT/artifacts" > "$OUT/main-pytest.txt" 2>&1
rc=$?
printf '%s\n' "$rc" > "$OUT/exit"
log "готово: exit=$rc результаты=$OUT"
exit "$rc"
