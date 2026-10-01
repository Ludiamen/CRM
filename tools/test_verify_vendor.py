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


if __name__ == "__main__":
    unittest.main()
