"""Тесты tools/verify_vendor.py: в каталоге сторонних библиотек нет ничего лишнего.

Каталог backend/static/vendor/ исключён из проверки по конституции
(`не_проверять`), поэтому всё, что в нём лежит, должно быть перечислено в
VERSIONS.md — иначе туда можно спрятать свой файл от ворот.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_vendor as vv  # noqa: E402


class ТестЛишнегоВVendor(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.каталог = Path(self._tmp.name)
        for имя in ("VERSIONS.md", "LICENSE-htmx", "htmx-2.0.11.min.js"):
            (self.каталог / имя).write_text("x", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_только_перечисленное_без_замечаний(self):
        self.assertEqual(vv.лишнее_в_vendor(self.каталог, {"htmx-2.0.11.min.js"}), [])

    def test_неперечисленный_файл_лишний(self):
        (self.каталог / "наш.js").write_text("x", encoding="utf-8")
        лишнее = vv.лишнее_в_vendor(self.каталог, {"htmx-2.0.11.min.js"})
        self.assertEqual(len(лишнее), 1)
        self.assertIn("наш.js", лишнее[0])

    def test_символическая_ссылка_лишняя_даже_с_разрешённым_именем(self):
        цель = self.каталог.parent / "чужой.py"
        цель.write_text("x", encoding="utf-8")
        self.addCleanup(цель.unlink)
        (self.каталог / "htmx-2.0.11.min.js").unlink()
        (self.каталог / "htmx-2.0.11.min.js").symlink_to(цель)
        лишнее = vv.лишнее_в_vendor(self.каталог, {"htmx-2.0.11.min.js"})
        self.assertTrue(any("символическая ссылка" in л for л in лишнее))

    def test_подкаталог_лишний(self):
        (self.каталог / "sub").mkdir()
        лишнее = vv.лишнее_в_vendor(self.каталог, {"htmx-2.0.11.min.js"})
        self.assertTrue(any("подкаталог" in л for л in лишнее))

    def test_настоящий_vendor_чист(self):
        разделы = vv.разобрать_versions()
        перечисленные = {файл for _, _, файлы in разделы for файл, _, _ in файлы}
        self.assertEqual(vv.лишнее_в_vendor(vv.VENDOR, перечисленные), [])


ХЕШ_ЯДРА = "a" * 64
ХЕШ_РАСШИРЕНИЯ = "b" * 64
VERSIONS_ПРИМЕР = f"""# Сторонняя статика

## HTMX 2.0.11

| Файл | Файл в пакете | SHA256 |
|------|---------------|--------|
| htmx-2.0.11.min.js | package/dist/htmx.min.js | {ХЕШ_ЯДРА} |

## htmx-ext-ws 2.0.4

- **Лицензия**: 0BSD (`LICENSE-htmx-ext-ws`, взят из пакета)

| Файл | Файл в пакете | SHA256 |
|------|---------------|--------|
| htmx-ext-ws-2.0.4.min.js | package/dist/ws.min.js | {ХЕШ_РАСШИРЕНИЯ} |

## Как проверять

Раздел без версии в заголовке пропускается.
"""


class ТестРазбораVersions(unittest.TestCase):
    """Заголовок раздела htmx-ext-ws разбирается и не сливается с разделом HTMX (T-4138, п. 13)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.каталог = Path(self._tmp.name)
        (self.каталог / "VERSIONS.md").write_text(VERSIONS_ПРИМЕР, encoding="utf-8")
        старый = vv.VENDOR
        vv.VENDOR = self.каталог
        self.addCleanup(setattr, vv, "VENDOR", старый)
        self.addCleanup(self._tmp.cleanup)

    def test_заголовок_htmx_ext_ws_даёт_отдельный_раздел_с_файлом_и_версией(self):
        разделы = vv.разобрать_versions()
        self.assertEqual([имя for имя, _, _ in разделы], ["HTMX", "htmx-ext-ws"])
        имя, версия, файлы = разделы[1]
        self.assertEqual(версия, "2.0.4")
        self.assertEqual(файлы, [("htmx-ext-ws-2.0.4.min.js", "package/dist/ws.min.js", ХЕШ_РАСШИРЕНИЯ)])
        self.assertEqual(разделы[0][2], [("htmx-2.0.11.min.js", "package/dist/htmx.min.js", ХЕШ_ЯДРА)])

    def test_ключ_htmx_ext_ws_в_пакетах_с_лицензией_и_веткой(self):
        пакет, лицензия, ветка = vv.ПАКЕТЫ["htmx-ext-ws"]
        self.assertEqual((пакет, лицензия), ("htmx-ext-ws", "LICENSE-htmx-ext-ws"))
        self.assertRegex("2.0.4", ветка)
        self.assertNotRegex("3.0.0", ветка)

    def test_каждый_раздел_настоящего_versions_имеет_ключ_в_пакетах(self):
        vv.VENDOR = vv.КОРЕНЬ / "backend" / "static" / "vendor"  # прежнее значение вернёт setUp
        имена = [имя for имя, _, _ in vv.разобрать_versions()]
        self.assertIn("htmx-ext-ws", имена)
        self.assertEqual(sorted(имена), sorted(vv.ПАКЕТЫ))


if __name__ == "__main__":
    unittest.main()
