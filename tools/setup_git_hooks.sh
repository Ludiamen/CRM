#!/bin/sh
# Подключает к клону pre-commit хук: он не пускает в коммит секреты
# (SECRET_KEY литералом, пароль в DSN, пароль/токен/ключ литералом, токен
# Telegram-бота, приватный ключ, файлы .env) — см. tools/check_secrets.py.
cd "$(git rev-parse --show-toplevel)" || exit 1
cat > .git/hooks/pre-commit <<'HOOK'
#!/bin/sh
exec python3 tools/check_secrets.py
HOOK
chmod +x .git/hooks/pre-commit
echo "pre-commit хук подключён"
