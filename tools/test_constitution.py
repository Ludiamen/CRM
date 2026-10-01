"""Тесты регулярок и запрет-слов конституции (docs/constitution.json).

Ворота (`tools/sdd.py проверить`) ловят нарушения жёстких инвариантов
(«запрет-слов» / «запрет-в-коде» / «запрет-регулярок») построчно функцией
`sdd._нарушение_на_строке` (см. `sdd.проверить_код_по_конституции`). Этот
файл проверяет саму функцию на НАСТОЯЩЕМ `docs/constitution.json` репозитория,
а не на выдуманном мини-наборе инвариантов, — иначе тест мог бы годами не
замечать, что правка регулярки в конституции завела ложное срабатывание или
перестала ловить то, для чего заводилась.

Два набора строк:
  - «честный код» — типичный код Django + HTMX + docker-compose; ни одна
    строка не должна задеть НИ ОДИН жёсткий инвариант;
  - «нарушения» — типовые нарушения; каждая строка должна дать срабатывание
    ИМЕННО того инварианта, для которого она подобрана, и никакого другого.

Тест не меняет constitution.json: если строка «честного кода» ловится (ложное
срабатывание) или строка «нарушения» не ловится/ловится не тем инвариантом —
тест падает, а решение по регулярке — за владельцем/Opus, не за этим файлом.

Секреты в тестовых строках собраны конкатенацией (`"password=" + '"..."'`),
чтобы pre-commit `tools/check_secrets.py` не принял сам этот файл за коммит
с секретом. Проверить: `python3 -c "import sys; sys.path.insert(0, 'tools');
import check_secrets as c; print(c.проверить_текст('tools/test_constitution.py',
open('tools/test_constitution.py').read()))"` → `[]`.

Запуск: python3 -m unittest tools/test_constitution.py — из корня CRM.
"""

import json
import unittest
from pathlib import Path

try:
    from tools import sdd
except ImportError:  # запуск не через "python3 -m unittest tools/test_constitution.py"
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sdd

КОРЕНЬ = Path(__file__).resolve().parent.parent


def _загрузить_конституцию() -> dict:
    путь = КОРЕНЬ / "docs" / "constitution.json"
    return json.loads(путь.read_text(encoding="utf-8"))


def _жёсткие_инварианты(данные: dict) -> list:
    return [инв for инв in данные.get("инварианты", []) or [] if инв.get("тип") in sdd.ТИПЫ_ЖЁСТКИЕ]


# --------------------------------------------------------------------------
# «Честный код»: типичный Django + HTMX + docker-compose. Ни одна строка не
# должна дать нарушение ни одного жёсткого инварианта.

ЧЕСТНЫЙ_КОД = [
    # settings.py через django-environ — секрет читается из окружения, а не лежит в коде
    "SECRET_KEY = env(" + '"SECRET_KEY")',
    '"PASSWORD": env(' + '"DB_PASSWORD"),',
    "EMAIL_HOST_PASSWORD = env(" + '"EMAIL_HOST_PASSWORD")',
    # имя настройки/константы, оканчивающееся на PASSWORD, но не присваивание секрета
    "AUTH_PASSWORD_VALIDATORS = [",
    "PASSWORD_RESET_TIMEOUT = 3600",
    # вход: пароль передаётся переменной, а не литералом
    "user = authenticate(request, username=u, password=password)",
    # тесты по решению владельца 2026-09-29: пароль не литерал, а из фикстуры
    "self.password = secrets.token_urlsafe(16)",
    'self.client.login(username=' + '"ivanov", password=self.password)',
    'User.objects.create_user(' + '"ivanov", password=self.password)',
    # docker-compose: секрет подставляется из окружения, а не хранится в файле
    "- POSTGRES_PASSWORD=" + "${POSTGRES_PASSWORD}",
    "POSTGRES_PASSWORD: " + "${POSTGRES_PASSWORD}",
    # шаблоны Django/HTMX: csrf-токен — не секрет-в-url и не секрет-в-коде
    "{% csrf_token %}",
    "hx-headers='" + '{"X-CSRFToken": ' + '"{{ csrf_token }}"}' + "'",
    # модель с полем "token" — имя поля, а не секрет в коде
    "token = models.CharField(max_length=64)",
    # параметризованный SQL — не подстановка в текст запроса
    "cursor.execute(sql, [ticket_id])",
    # свои/сторонние импорты, которые лишь похожи на запрещённые слова
    "import reactive_utils",  # не "react" (запрет-слов "стек-интерфейс") — граница слова
    "from django_rq import job",  # не "celery" (запрет-слов "стек-бэкенд")
    # эталон в комментарии по-русски (кириллицей) — не запрещённое латинское "bitrix"
    "# как в Битриксе",
]


# --------------------------------------------------------------------------
# «Нарушения»: (строка, код инварианта, который ОБЯЗАН сработать — и только он).

НАРУШЕНИЯ = [
    ("password=" + '"testpass123"', "секреты-вне-кода"),
    ("API_KEY = " + '"abcd1234efgh"', "секреты-вне-кода"),
    ("DB_PASSWORD=" + "S3cr3t-value", "секреты-вне-кода"),
    ("  POSTGRES_PASSWORD: " + "plainsecret", "секреты-вне-кода"),
    ("url = " + '"https://h/?token=' + 'abc"', "секреты-в-url"),
    ('cursor.execute(f"select * from t where id={x}")', "sql-только-параметры"),
    ("from celery import shared_task", "стек-бэкенд"),
    ('import React from "react"', "стек-интерфейс"),
    ('ENGINE = "django.db.backends.sqlite3"', "бд"),
    ("# перенесено из bitrix", "эталон-не-копия"),
]


class ТестЧестногоКода(unittest.TestCase):
    """Типичный честный код не должен задевать ни один жёсткий инвариант."""

    @classmethod
    def setUpClass(cls):
        cls.данные = _загрузить_конституцию()
        cls.жёсткие = _жёсткие_инварианты(cls.данные)

    def test_есть_жёсткие_инварианты_для_проверки(self):
        # если конституция вдруг лишится жёстких инвариантов, тест ниже
        # молча "пройдёт", ничего не проверив — это тоже надо заметить
        self.assertTrue(self.жёсткие, "в docs/constitution.json нет ни одного жёсткого инварианта")

    def test_честный_код_не_даёт_ложных_срабатываний(self):
        находки = []
        for строка in ЧЕСТНЫЙ_КОД:
            for инв in self.жёсткие:
                результат = sdd._нарушение_на_строке(инв, строка)
                if результат:
                    находки.append(f"инвариант «{инв.get('код')}» сработал на {строка!r} (совпало: {результат!r})")
        self.assertEqual(находки, [], "ложные срабатывания на честном коде:\n  " + "\n  ".join(находки))


class ТестНарушений(unittest.TestCase):
    """Каждое типовое нарушение обязано поймать именно ожидаемый инвариант."""

    @classmethod
    def setUpClass(cls):
        cls.данные = _загрузить_конституцию()
        cls.жёсткие = _жёсткие_инварианты(cls.данные)
        cls.коды_жёстких = {инв.get("код") for инв in cls.жёсткие}

    def test_ожидаемые_коды_есть_среди_жёстких_инвариантов(self):
        for _, ожидаемый in НАРУШЕНИЯ:
            with self.subTest(инвариант=ожидаемый):
                self.assertIn(ожидаемый, self.коды_жёстких)

    def test_нарушение_ловится_именно_ожидаемым_инвариантом_и_только_им(self):
        for строка, ожидаемый in НАРУШЕНИЯ:
            with self.subTest(строка=строка):
                сработавшие = [
                    инв.get("код") for инв in self.жёсткие if sdd._нарушение_на_строке(инв, строка)
                ]
                self.assertEqual(
                    сработавшие,
                    [ожидаемый],
                    f"строка {строка!r}: сработали {сработавшие}, ожидался ровно [{ожидаемый!r}]",
                )


if __name__ == "__main__":
    unittest.main()


class ТестНеПроверять(unittest.TestCase):
    """Поле «не_проверять» настоящей конституции: сторонняя статика вне проверки."""

    @classmethod
    def setUpClass(cls):
        cls.данные = _загрузить_конституцию()

    def test_vendor_объявлен_в_не_проверять(self):
        self.assertIn("backend/static/vendor/**", self.данные.get("не_проверять", []))
        self.assertEqual(sdd.проверить_инварианты(self.данные), [])

    def test_файлы_vendor_не_попадают_в_проверку_а_наши_попадают(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            корень = Path(tmp)
            (корень / "backend" / "static" / "vendor").mkdir(parents=True)
            (корень / "backend" / "apps").mkdir(parents=True)
            (корень / "backend" / "static" / "vendor" / "lib.js").write_text("x\n", encoding="utf-8")
            (корень / "backend" / "apps" / "a.py").write_text("x\n", encoding="utf-8")
            файлы = sdd.собрать_файлы_для_проверки(
                корень, self.данные["проверять"], self.данные["не_проверять"]
            )
            имена = [f.relative_to(корень.resolve()).as_posix() for f in файлы]
            self.assertEqual(имена, ["backend/apps/a.py"])
