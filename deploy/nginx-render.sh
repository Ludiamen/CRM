#!/bin/sh
# Собирает /etc/nginx/nginx.conf из шаблона (T-261). Скрипт лежит в
# /docker-entrypoint.d/ и выполняется образом nginx перед стартом.
# В шаблоне строка `set_real_ip_from ${TRUSTED_PROXIES};` заменяется строкой на
# каждый элемент TRUSTED_PROXIES (адрес или сеть CIDR, через запятую).
# Пустой список и доверие всем адресам (0.0.0.0/0, ::/0) — отказ: иначе блокировка
# по адресу видела бы подделанный заголовок.
set -eu

template=/etc/nginx/nginx.conf.template
lines=/tmp/real-ip.lines
: > "$lines"

list=$(printf '%s' "${TRUSTED_PROXIES:-}" | tr ',' ' ')
count=0
for item in $list; do
    case "$item" in
        0.0.0.0/0|::/0|0.0.0.0|::|all|'*')
            echo "TRUSTED_PROXIES: доверять всем адресам нельзя ($item)" >&2
            exit 1 ;;
    esac
    if ! printf '%s' "$item" | grep -Eq '^[0-9A-Fa-f:.]+(/[0-9]{1,3})?$'; then
        echo "TRUSTED_PROXIES: не адрес и не сеть CIDR: $item" >&2
        exit 1
    fi
    printf '    set_real_ip_from %s;\n' "$item" >> "$lines"
    count=$((count + 1))
done
if [ "$count" -eq 0 ]; then
    echo "TRUSTED_PROXIES пуст: нужен адрес прокси администратора и внутренняя сеть" >&2
    exit 1
fi

awk 'FNR == NR { block = block $0 "\n"; next }
     /^[ \t]*set_real_ip_from \$\{TRUSTED_PROXIES\};/ { printf "%s", block; next }
     { print }' "$lines" "$template" > /etc/nginx/nginx.conf
echo "nginx.conf собран: доверенных прокси — $count"
