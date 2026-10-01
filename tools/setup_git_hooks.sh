#!/bin/sh
# Подключает к клону pre-commit хук. Он по очереди запускает:
#   1. tools/check_secrets.py — не пускает в коммит секреты (SECRET_KEY литералом,
#      пароль в DSN, пароль/токен/ключ литералом, токен Telegram-бота, приватный
#      ключ, файлы .env);
#   2. python3 tools/sdd.py проверить — ворота документов и конституции;
#   3. tools/test_constitution.py — быстрые тесты регулярок конституции.
# Вывод шагов 2 и 3 показывается только при отказе; значения секретов хук не
# печатает (check_secrets.py называет файл, строку и причину).
cd "$(git rev-parse --show-toplevel)" || exit 1
cat > .git/hooks/pre-commit <<'HOOK'
#!/bin/sh
cd "$(git rev-parse --show-toplevel)" || exit 1

python3 tools/check_secrets.py || exit 1

if ! out=$(python3 tools/sdd.py проверить 2>&1); then
    printf '%s\n' "$out" | tail -n 40
    echo "ОТКАЗ: python3 tools/sdd.py проверить нашёл ошибки"
    exit 1
fi

if ! out=$(python3 -m unittest tools/test_constitution.py 2>&1); then
    printf '%s\n' "$out" | tail -n 40
    echo "ОТКАЗ: tools/test_constitution.py не проходит"
    exit 1
fi
HOOK
chmod +x .git/hooks/pre-commit
echo "pre-commit хук подключён"
