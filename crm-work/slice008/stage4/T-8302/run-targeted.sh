#!/usr/bin/env bash
# T-8302 (повтор после правок): m01…m13 в четырёх кругах, e10 в Chromium и Яндексе, 24 узла повтора.
set -uo pipefail
umask 077
CRM=/home/gpgr/Документы/CRM
W=/home/gpgr/Документы/crm-work
D=$CRM/crm-work/slice008/stage4/T-8302
PLUGIN=$W/slice005/stage4/t5302/plugin
LOCK=$W/slice005/stage2/test.lock
PY=$CRM/.venv/bin/python
TAG=${1:?метка копии before-T8302-YYYYMMDD-HHMMSS}
[[ $TAG =~ ^before-T8302-[0-9]{8}-[0-9]{6}$ ]] || { echo 'invalid tag'; exit 3; }
OUT=$(mktemp -d "$D/targeted-$TAG-XXXXXX")
trap 'rc=$?; printf "exit=%s\nfinished=%s\n" "$rc" "$(date --iso-8601=seconds)" > "$OUT/status"' EXIT
exec > >(tee -a "$OUT/gate.log") 2>&1
log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }
printf 'directory=%s\ntag=%s\n' "$OUT" "$TAG"

for f in "crm-db-$TAG.dump" "crm_media-$TAG.tgz" "crm_protected-$TAG.tgz" "env-$TAG"; do
  [ -s "$W/stand-backup/$f" ] || { log "копия не найдена: $f"; exit 4; }
done

exec 9>"$LOCK"
if ! flock -n 9; then log 'заблокировано: lock занят'; exit 2; fi
if pgrep -f '[p]ytest' >/dev/null; then log 'заблокировано: идёт pytest'; exit 2; fi

set -a
. "$CRM/deploy/.env" >/dev/null 2>&1 || { log 'не прочитан deploy/.env'; exit 5; }
set +a
unset COMPOSE_PROJECT_NAME COMPOSE_PROFILES COMPOSE_FILE COMPOSE_ENV_FILE DOCKER_HOST DOCKER_CONTEXT
unset E2E_IDS_FILE E2E_ADMIN_CMD E2E_SHELL_CMD E2E_PORTAL_URL PYTEST_ADDOPTS PYTEST_PLUGINS PYTEST_DISABLE_PLUGIN_AUTOLOAD
export COMPOSE_PROFILES=dev E2E_MAILPIT_URL=http://127.0.0.1:8025
export E2E_RESET_CMD="docker compose -p crm -f $CRM/deploy/docker-compose.yml --profile dev exec -T standtools python manage.py e2e_reset_stand"
export PYTHONPATH="$PLUGIN"
cd "$CRM/backend" || exit 7

log 'проверка стенда'
curl -sk -o /dev/null -w 'messenger=%{http_code}\n' "https://127.0.0.1:8031/messenger/" | tee -a "$OUT/gate.log"
docker compose -p crm -f "$CRM/deploy/docker-compose.yml" --profile dev ps --format '{{.Service}} {{.Status}}' > "$OUT/services.txt"
grep -q '^web .*healthy' "$OUT/services.txt" || { log 'web не healthy'; exit 9; }

log 'сбор e2e nodeid'
"$PY" -m pytest tests/e2e --collect-only -q -p no:cacheprovider > "$OUT/collect-all.txt" 2> "$OUT/collect-errors.txt" || { log 'collection failed'; exit 6; }
"$PY" "$D/make-ids-targeted.py" "$D/retry/ids.txt" < "$OUT/collect-all.txt" > "$OUT/ids.txt" 2> "$OUT/ids-count.txt"
cat "$OUT/ids-count.txt"
[ -s "$OUT/ids.txt" ] || { log 'пустой список nodeid'; exit 6; }
export E2E_IDS_FILE="$OUT/ids.txt"

log 'точечный прогон, сброс перед кругом'
"$PY" -m pytest tests/e2e -p e2e_ids_filter -p no:cacheprovider -q -rfE \
  --junitxml="$OUT/main.xml" --output="$OUT/artifacts" > "$OUT/main-pytest.txt" 2>&1
rc=$?
printf 'main-exit=%s\n' "$rc" > "$OUT/main.status"
python3 - "$OUT" <<'PY'
import json, sys
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET
p = Path(sys.argv[1])
counts = Counter(); by_round = Counter()
for case in ET.parse(p / 'main.xml').iter('testcase'):
    state = next((s for s in ('failure', 'error', 'skipped') if case.find(s) is not None), 'passed')
    counts[state] += 1
    name = case.get('name', '')
    tag = name.rsplit('[', 1)[-1].rstrip(']') if '[' in name else '—'
    by_round[f'{tag}:{state}'] += 1
(p / 'summary.json').write_text(json.dumps({'states': dict(counts), 'by_round': dict(by_round)}, indent=2, ensure_ascii=False) + '\n')
print('e2e JUnit', json.dumps(dict(counts)))
PY
log "готово: exit=$rc результаты=$OUT"
exit "$rc"