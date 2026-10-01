#!/bin/sh
# Запуск pytest в контейнере тестов (сервис test в docker-compose.yml).
# Окружение Python лежит в томе /opt/venv и пересобирается только при смене
# requirements*.txt, поэтому повторные запуски не ходят в интернет.
# Аргументы передаются pytest: docker compose --profile test run --rm test -k имя
set -eu
cd /app/backend
[ -x /opt/venv/bin/python ] || python -m venv /opt/venv
req_hash=$(cat requirements.txt requirements-dev.txt | md5sum | cut -d' ' -f1)
if [ "$(cat /opt/venv/.requirements-hash 2>/dev/null || true)" != "$req_hash" ]; then
    /opt/venv/bin/pip install -q -r requirements-dev.txt
    echo "$req_hash" > /opt/venv/.requirements-hash
fi
exec /opt/venv/bin/python -m pytest "$@"
