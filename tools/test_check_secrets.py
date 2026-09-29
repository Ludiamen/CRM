"""Тесты для tools/check_secrets.py — сканера секретов перед коммитом.

Тесты не трогают git: проверяются чистые функции разбора текста и имени
файла. «Секреты» в тестах собраны конкатенацией строк, чтобы сам этот файл
не выглядел секретом для стороннего сканера.

Запуск: python3 -m unittest tools/test_check_secrets.py — из корня репозитория.
"""
import unittest

try:
    from tools import check_secrets as cs
except ImportError:  # запуск не через "python3 -m unittest tools/test_check_secrets.py"
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
    import check_secrets as cs


class ТестЗаглушек(unittest.TestCase):
    def test_пустое_значение_заглушка(self):
        self.assertTrue(cs.похоже_на_заглушку(""))
        self.assertTrue(cs.похоже_на_заглушку("   "))

    def test_звёздочки_и_переменная_заглушка(self):
        self.assertTrue(cs.похоже_на_заглушку("***"))
        self.assertTrue(cs.похоже_на_заглушку("${DB_PASSWORD}"))

    def test_changeme_и_example_заглушка(self):
        self.assertTrue(cs.похоже_на_заглушку("changeme"))
        self.assertTrue(cs.похоже_на_заглушку("CHANGEME"))
        self.assertTrue(cs.похоже_на_заглушку("example-value"))

    def test_настоящее_значение_не_заглушка(self):
        значение = "х" + "y" * 20
        self.assertFalse(cs.похоже_на_заглушку(значение))


class ТестSecretKey(unittest.TestCase):
    def test_secret_key_литералом_находится(self):
        литерал = "django-insecure-" + "a1b2c3d4e5f6g7h8"
        строка = "SECRET_KE" + "Y = \"" + литерал + "\""
        находки = cs.проверить_строку(строка)
        self.assertIn("SECRET_KEY литералом", находки)

    def test_secret_key_из_окружения_не_находится(self):
        строка = "SECRET_KE" + "Y = os.environ[\"SECRET_KEY\"]"
        self.assertEqual(cs.проверить_строку(строка), [])

    def test_secret_key_через_getenv_не_находится(self):
        строка = "SECRET_KE" + "Y = getenv(\"SECRET_KEY\", \"changeme\")"
        self.assertEqual(cs.проверить_строку(строка), [])


class ТестПарольТокенКлюч(unittest.TestCase):
    def test_пароль_литералом_восемь_и_более_находится(self):
        значение = "p" + "a" * 7  # ровно 8 символов
        строка = "password = \"" + значение + "\""
        self.assertIn("пароль/токен/ключ литералом", cs.проверить_строку(строка))

    def test_короткий_пароль_не_находится(self):
        строка = "password = \"" + "short12" + "\""  # 7 символов
        self.assertEqual(cs.проверить_строку(строка), [])

    def test_json_стиль_ключа_находится(self):
        значение = "т" + "o" * 20
        строка = "  \"api_key\": \"" + значение + "\","
        self.assertIn("пароль/токен/ключ литералом", cs.проверить_строку(строка))

    def test_секрет_в_составном_имени_переменной_находится(self):
        значение = "s" * 12
        строка = "DB_PASSWORD = \"" + значение + "\""
        self.assertIn("пароль/токен/ключ литералом", cs.проверить_строку(строка))

    def test_заглушка_не_находится(self):
        for заглушка in ("changeme", "example-secret-value", "***", "${AUTH_TOKEN}", ""):
            with self.subTest(заглушка=заглушка):
                строка = "token = \"" + заглушка + "\""
                self.assertEqual(cs.проверить_строку(строка), [])

    def test_чтение_из_окружения_подавляет_находку(self):
        строка = "password = os.environ.get(\"PASSWORD\", \"" + "x" * 10 + "\")"
        # значение после os.environ.get не в форме "ключ = 'литерал'" сразу
        # после «=», но строка всё равно размечена как чтение из окружения
        self.assertEqual(cs.проверить_строку(строка), [])


class ТестPostgresDSN(unittest.TestCase):
    def test_пароль_в_dsn_находится(self):
        пароль = "s3cr" + "et-pass"
        строка = "DATABASE_URL = postgres://user:" + пароль + "@db.internal:5432/crm"
        self.assertIn("пароль в postgres DSN", cs.проверить_строку(строка))

    def test_postgresql_схема_тоже_находится(self):
        пароль = "s3cr" + "et-pass"
        строка = "postgresql://user:" + пароль + "@localhost/crm"
        self.assertIn("пароль в postgres DSN", cs.проверить_строку(строка))

    def test_плейсхолдер_в_dsn_не_находится(self):
        строка = "DATABASE_URL = postgres://user:${DB_PASSWORD}@db.internal:5432/crm"
        self.assertEqual(cs.проверить_строку(строка), [])

    def test_dsn_без_пароля_не_находится(self):
        строка = "DATABASE_URL = postgres://user@db.internal:5432/crm"
        self.assertEqual(cs.проверить_строку(строка), [])


class ТестTelegram(unittest.TestCase):
    def test_токен_бота_находится(self):
        токен = "123456789" + ":" + "AA" + "B" * 33
        находки = cs.проверить_строку("BOT_TOKEN = \"" + токен + "\"")
        self.assertIn("токен Telegram-бота", находки)

    def test_короткий_числовой_префикс_не_считается_токеном(self):
        строка = "id = \"12345:notatoken\""
        self.assertEqual(cs.проверить_строку(строка), [])


class ТестПриватногоКлюча(unittest.TestCase):
    def test_pem_блок_находится(self):
        строка = "-----BEGIN RSA PRIV" + "ATE KEY-----"
        self.assertIn("приватный ключ (PEM)", cs.проверить_строку(строка))

    def test_обычный_текст_не_находится(self):
        self.assertEqual(cs.проверить_строку("этот текст не содержит секретов"), [])


class ТестФайлаЦеликом(unittest.TestCase):
    def test_env_файл_запрещён(self):
        self.assertIsNotNone(cs.файл_запрещён_целиком(".env"))
        self.assertIsNotNone(cs.файл_запрещён_целиком("backend/.env"))
        self.assertIsNotNone(cs.файл_запрещён_целиком("deploy/prod.env"))

    def test_env_example_разрешён(self):
        self.assertIsNone(cs.файл_запрещён_целиком(".env.example"))
        self.assertIsNone(cs.файл_запрещён_целиком("backend/.env.example"))

    def test_обычный_файл_разрешён(self):
        self.assertIsNone(cs.файл_запрещён_целиком("backend/settings.py"))


class ТестПроверитьТекст(unittest.TestCase):
    def test_номер_строки_и_имя_файла_в_находке(self):
        литерал = "django-insecure-" + "x" * 20
        текст = "\n".join(["# комментарий", "SECRET_KE" + "Y = \"" + литерал + "\""])
        находки = cs.проверить_текст("backend/settings.py", текст)
        self.assertEqual(len(находки), 1)
        self.assertTrue(находки[0].startswith("backend/settings.py:2 — "))

    def test_несколько_строк_несколько_находок(self):
        литерал1 = "a" * 20
        литерал2 = "b" * 20
        текст = "\n".join([
            "password = \"" + литерал1 + "\"",
            "обычная строка",
            "token = \"" + литерал2 + "\"",
        ])
        находки = cs.проверить_текст("cfg.py", текст)
        self.assertEqual(len(находки), 2)
        self.assertIn("cfg.py:1 — пароль/токен/ключ литералом", находки)
        self.assertIn("cfg.py:3 — пароль/токен/ключ литералом", находки)


if __name__ == "__main__":
    unittest.main()
