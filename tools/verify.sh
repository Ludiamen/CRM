#!/bin/sh
# Вся проверка проекта одной командой (PLAN-001, «Проверка»; T-011).
#
#   tools/verify.sh            # всё, включая pytest в контейнере
#   tools/verify.sh --быстро   # без pytest в контейнере (без Docker)
#
# Шаги идут все подряд, не останавливаясь на первом отказе; код возврата —
# код первого упавшего шага (0, если упавших нет). Значения секретов не
# печатаются: check_secrets.py называет только файл, строку и причину.
cd "$(dirname "$0")/.." || exit 1

rc=0
step() {
    title=$1
    shift
    echo "== $title"
    "$@"
    code=$?
    if [ "$code" -ne 0 ]; then
        echo "-- ОТКАЗ ($code): $title"
        if [ "$rc" -eq 0 ]; then rc=$code; fi
    fi
}

step "ворота документов и конституции (sdd.py проверить)" python3 tools/sdd.py проверить
step "тесты инструментов (unittest)" python3 -m unittest discover -s tools -p "test_*.py"
step "тесты конституции" python3 -m unittest tools/test_constitution.py
step "сканер секретов (индекс git)" python3 tools/check_secrets.py
step "сверка сторонней статики (vendor) с реестром npm" python3 tools/verify_vendor.py

if [ "${1:-}" != "--быстро" ]; then
    if [ ! -f deploy/.env ]; then
        python3 tools/make_dev_env.py
    fi
    step "pytest на PostgreSQL в контейнере" \
        docker compose -f deploy/docker-compose.yml --profile dev --profile test run --rm test
fi

echo
if [ "$rc" -eq 0 ]; then echo "verify: всё прошло"; else echo "verify: есть отказы, код $rc"; fi
exit "$rc"
