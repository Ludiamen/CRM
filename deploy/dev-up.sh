#!/bin/sh
# Стенд одной командой: сертификат (если нет), сборка образов, все службы с
# профилем dev (Mailpit, standtools). Портал — https://127.0.0.1:8031/
set -eu
cd "$(dirname "$0")"
./dev-cert.sh
docker compose --profile dev up -d --build "$@"
docker compose --profile dev ps
