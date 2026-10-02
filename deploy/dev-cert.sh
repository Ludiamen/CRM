#!/bin/sh
# Самоподписанный сертификат стенда для nginx (T-264, PLAN-001 «Запуск»).
# Пишет deploy/certs/dev.crt и dev.key; каталог certs/ в .gitignore, закрытый
# ключ в репозиторий не попадает. Сертификат на 127.0.0.1 и localhost.
#
#   deploy/dev-cert.sh            # выпустить, если ещё нет
#   deploy/dev-cert.sh --заново   # выпустить заново
set -eu

dir="$(cd "$(dirname "$0")" && pwd)/certs"
mkdir -p "$dir"

if [ -f "$dir/dev.crt" ] && [ -f "$dir/dev.key" ] && [ "${1:-}" != "--заново" ]; then
    echo "Сертификат стенда уже есть: $dir/dev.crt"
    exit 0
fi

umask 077
openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
    -subj "/CN=127.0.0.1/O=Портал ИТ-отдела (стенд)" \
    -addext "subjectAltName=IP:127.0.0.1,DNS:localhost" \
    -keyout "$dir/dev.key" -out "$dir/dev.crt" 2>/dev/null
chmod 644 "$dir/dev.crt"
chmod 600 "$dir/dev.key"
echo "Выпущен сертификат стенда: $dir/dev.crt (ключ рядом, в git не попадает)"
