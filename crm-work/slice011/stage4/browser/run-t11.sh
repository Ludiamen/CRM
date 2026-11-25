#!/usr/bin/env bash
# T-11301 (срез 011): круг браузерных сценариев t11 в одном браузере.
# Стенд сбрасывается, затем e2e_sla_seed; pytest берёт только узлы этого браузера.
set -uo pipefail
CRM=/home/gpgr/Документы/CRM
W=/home/gpgr/Документы/crm-work
D=$CRM/crm-work/slice011/stage4/browser
LOCK=$W/slice005/stage2/test.lock
PY=$CRM/.venv/bin/python
BROWSER=${1:?браузер: chromium|firefox|edge|yandex}
OUT=$D/$BROWSER-$(date +%Y%m%d-%H%M%S)
mkdir -p "$OUT"
exec 9>"$LOCK"; flock -n 9 || { echo 'lock'; exit 2; }
set -a; . "$CRM/deploy/.env" >/dev/null 2>&1; set +a
unset COMPOSE_PROJECT_NAME COMPOSE_PROFILES COMPOSE_FILE COMPOSE_ENV_FILE DOCKER_HOST DOCKER_CONTEXT E2E_IDS_FILE E2E_RESET_CMD
export COMPOSE_PROFILES=dev E2E_MAILPIT_URL=http://127.0.0.1:8025
export PYTHONPATH="$W/slice005/stage4/t5302/plugin"
DC=(docker compose -p crm -f "$CRM/deploy/docker-compose.yml" --profile dev)
"${DC[@]}" exec -T standtools python manage.py e2e_reset_stand > "$OUT/reset.log" 2>&1 || { echo 'reset'; exit 3; }
"${DC[@]}" exec -T standtools python manage.py e2e_sla_seed > "$OUT/seed.log" 2>&1 || { echo 'seed'; exit 3; }
cd "$CRM/backend" || exit 7
"$PY" -m pytest tests/e2e --collect-only -q -p no:cacheprovider > "$OUT/collect.txt" 2> "$OUT/collect-errors.txt" || exit 6
grep -E "^tests/e2e/test_t11_[0-9]+\.py::.*\[$BROWSER\]$" "$OUT/collect.txt" > "$OUT/ids.txt"
wc -l < "$OUT/ids.txt"
[ -s "$OUT/ids.txt" ] || exit 6
export E2E_IDS_FILE="$OUT/ids.txt"
"$PY" -m pytest tests/e2e -p e2e_ids_filter -p no:cacheprovider -q -rfE --junitxml="$OUT/main.xml" --output="$OUT/artifacts" > "$OUT/main-pytest.txt" 2>&1
rc=$?
printf '%s\n' "$OUT" > "$D/last-$BROWSER.txt"
tail -3 "$OUT/main-pytest.txt"
exit "$rc"
