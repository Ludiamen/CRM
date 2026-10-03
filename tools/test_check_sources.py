"""Тесты для tools/check_sources.py — проверки реестра источников.

Каждый случай строит во временном каталоге маленький репозиторий
(docs/reference/sources.md, ui-patterns.md) и каталог снимков.

Запуск: python3 -m unittest tools/test_check_sources.py — из корня репозитория.
"""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

try:
    from tools import check_sources as cs
except ImportError:
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import check_sources as cs

ШАПКА = "| Источник | Что это | Где | Про что | Дата обращения | Опорная фраза |\n|---|---|---|---|---|---|\n"


def строка_снимка(n, имя=None, где=None, про="коробка, тестовый портал", дата="2026-10-03"):
    имя = имя or f"{n - 400:03d}-page.png"
    где = где if где is not None else f"bitrix-demo/screens/{имя} (/stream/)"
    return f"| SRC-{n} | Экран {n} | {где} | {про} | {дата} | «фраза» |\n"


def реестр(строки_снимков, прочее=""):
    return (
        "# Реестр\n\n## Страницы документации\n\n" + ШАПКА
        + "| SRC-001 | Страница | https://example.com/a | про | 2026-09-01 | «фраза» |\n"
        + прочее
        + "\n## Снимки экранов тестового портала\n\n" + ШАПКА + "".join(строки_снимков)
    )


class База(unittest.TestCase):
    def setUp(self):
        self._врем = tempfile.TemporaryDirectory()
        self.addCleanup(self._врем.cleanup)
        self.корень = Path(self._врем.name) / "repo"
        (self.корень / "docs" / "reference").mkdir(parents=True)
        self.снимки = Path(self._врем.name) / "screens"
        self.снимки.mkdir()

    def записать(self, текст_реестра, ui="Текст без ссылок.\n", файлы=("001-page.png", "002-page.png")):
        (self.корень / cs.РЕЕСТР).write_text(текст_реестра, encoding="utf-8")
        (self.корень / cs.ПАТТЕРНЫ_UI).write_text(ui, encoding="utf-8")
        for имя in файлы:
            (self.снимки / имя).write_bytes(b"x")

    def запустить(self):
        return cs.проверить(self.корень, self.снимки)

    def хорошие(self):
        return [строка_снимка(401), строка_снимка(402)]


class ТестПроверок(База):
    def test_корректный_набор_проходит(self):
        self.записать(реестр(self.хорошие()), ui="Ссылка SRC-401 и SRC-001, в `SRC-999` не считается.\n")
        self.assertEqual(self.запустить(), ([], []))

    def test_пять_ячеек(self):
        плохая = "| SRC-002 | Что | Где | про | 2026-09-01 |\n"
        self.записать(реестр(self.хорошие(), плохая))
        находки, _ = self.запустить()
        self.assertEqual(len(находки), 1)
        self.assertIn("5 ячеек", находки[0])

    def test_строка_без_пробела_после_черты_тоже_проверяется(self):
        плохая = "|SRC-002|Что|Где|про|2026-09-01|\n"
        self.записать(реестр(self.хорошие(), плохая))
        находки, _ = self.запустить()
        self.assertEqual(len(находки), 1)
        self.assertIn("5 ячеек", находки[0])

    def test_плохая_дата(self):
        плохая = "| SRC-002 | Что | Где | про | 03.10.2026 | фраза |\n"
        self.записать(реестр(self.хорошие(), плохая))
        находки, _ = self.запустить()
        self.assertTrue(any("дата" in н for н in находки))

    def test_пустая_ячейка(self):
        плохая = "| SRC-002 | Что |  | про | 2026-09-01 | фраза |\n"
        self.записать(реестр(self.хорошие(), плохая))
        находки, _ = self.запустить()
        self.assertTrue(any("пустая ячейка «Где»" in н for н in находки))

    def test_повтор_кода(self):
        повтор = "| SRC-001 | Ещё | где | про | 2026-09-01 | фраза |\n"
        self.записать(реестр(self.хорошие(), повтор))
        находки, _ = self.запустить()
        self.assertTrue(any("SRC-001 повторяется" in н for н in находки))

    def test_пропуск_номера_снимка(self):
        self.записать(реестр([строка_снимка(401), строка_снимка(403)]), файлы=("001-page.png", "003-page.png"))
        находки, _ = self.запустить()
        self.assertTrue(any("ожидался SRC-402" in н for н in находки))

    def test_номер_в_имени_не_совпадает(self):
        self.записать(реестр([строка_снимка(401), строка_снимка(402, имя="005-page.png")]),
                      файлы=("001-page.png", "005-page.png"))
        находки, _ = self.запустить()
        self.assertTrue(any("не равен 002" in н for н in находки))

    def test_плохой_вид_где(self):
        self.записать(реестр([строка_снимка(401), строка_снимка(402, где="screens/002-page.png")]))
        находки, _ = self.запустить()
        self.assertTrue(any("«Где» не вида" in н for н in находки))

    def test_про_что_без_слова_коробка(self):
        self.записать(реестр([строка_снимка(401), строка_снимка(402, про="демо-стенд")]))
        находки, _ = self.запустить()
        self.assertTrue(any("«коробка»" in н for н in находки))

    def test_пропуски_номеров_в_других_разделах_допустимы(self):
        прочее = "| SRC-005 | Что | где | про | 2026-09-01 | фраза |\n| SRC-003 | Что | где | про | 2026-09-01 | фраза |\n"
        self.записать(реестр(self.хорошие(), прочее))
        self.assertEqual(self.запустить(), ([], []))

    def test_нет_файла_снимка(self):
        self.записать(реестр(self.хорошие()), файлы=("001-page.png",))
        находки, _ = self.запустить()
        self.assertTrue(any("002-page.png не найден" in н for н in находки))

    def test_лишний_файл_в_каталоге(self):
        self.записать(реестр(self.хорошие()), файлы=("001-page.png", "002-page.png", "003-extra.png"))
        находки, _ = self.запустить()
        self.assertTrue(any("003-extra.png" in н and "не описан" in н for н in находки))

    def test_один_файл_в_двух_строках(self):
        self.записать(реестр([строка_снимка(401), строка_снимка(402, имя="001-page.png", где="bitrix-demo/screens/001-page.png (/x/)")]),
                      файлы=("001-page.png",))
        находки, _ = self.запустить()
        self.assertTrue(any("уже упомянут" in н for н in находки))

    def test_каталога_снимков_нет_пропуск_и_код_ноль(self):
        self.записать(реестр(self.хорошие()))
        нет = Path(self._врем.name) / "нет-такого"
        находки, пропуски = cs.проверить(self.корень, нет)
        self.assertEqual(находки, [])
        self.assertEqual(len(пропуски), 1)
        self.assertTrue(пропуски[0].startswith("ПРОПУСК: каталог снимков не найден:"))
        вывод = io.StringIO()
        with redirect_stdout(вывод):
            код = cs.main(["--корень", str(self.корень), "--снимки", str(нет)])
        self.assertEqual(код, 0)
        self.assertIn("ПРОПУСК", вывод.getvalue())

    def test_код_возврата_один_при_находках(self):
        self.записать(реестр(self.хорошие()), файлы=("001-page.png",))
        with redirect_stdout(io.StringIO()):
            код = cs.main(["--корень", str(self.корень), "--снимки", str(self.снимки)])
        self.assertEqual(код, 1)


class ТестПочтыИСсылок(База):
    def test_почта_не_на_example_com(self):
        адрес = "user" + "@" + "mail.test"
        self.записать(реестр(self.хорошие(), f"| SRC-002 | Что | где {адрес} | про | 2026-09-01 | фраза |\n"))
        находки, _ = self.запустить()
        self.assertEqual(len(находки), 1)
        self.assertIn("адрес почты не на example.com", находки[0])
        self.assertNotIn("mail.test", находки[0])

    def test_почта_на_кириллическом_домене(self):
        адрес = "отдел" + "@" + "почта.рф"
        self.записать(реестр(self.хорошие()), ui=f"пишите на {адрес}\n")
        находки, _ = self.запустить()
        self.assertEqual(находки, [f"{cs.ПАТТЕРНЫ_UI}:1: адрес почты не на example.com"])

    def test_почта_на_example_com_допустима(self):
        ui = "Пишите user@example.com или a@mail.example.com.\n"
        self.записать(реестр(self.хорошие(), "| SRC-002 | Что | a@example.com | про | 2026-09-01 | фраза |\n"), ui=ui)
        self.assertEqual(self.запустить(), ([], []))

    def test_почта_в_ui_patterns(self):
        ui = "ok\nпишите на " + "x" + "@" + "evil.test\n"
        self.записать(реестр(self.хорошие()), ui=ui)
        находки, _ = self.запустить()
        self.assertEqual(находки, [f"{cs.ПАТТЕРНЫ_UI}:2: адрес почты не на example.com"])

    def test_неизвестный_src_в_ui_patterns(self):
        self.записать(реестр(self.хорошие()), ui="Строка 1\nСсылка SRC-777 тут.\n")
        находки, _ = self.запустить()
        self.assertEqual(len(находки), 1)
        self.assertIn(":2: SRC-777", находки[0])


НАСТОЯЩИЕ_СНИМКИ = cs.КОРЕНЬ.parent / "bitrix-demo" / "screens"


class ТестНастоящихФайлов(unittest.TestCase):
    @unittest.skipUnless(НАСТОЯЩИЕ_СНИМКИ.is_dir(), "каталога снимков нет")
    def test_реестр_репозитория_без_находок(self):
        находки, пропуски = cs.проверить(cs.КОРЕНЬ)
        self.assertEqual(находки, [])
        self.assertEqual(пропуски, [])


if __name__ == "__main__":
    unittest.main()
