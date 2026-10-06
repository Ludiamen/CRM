"""Тесты tools/make_dev_env.py: настоящий deploy/.env не читается и не меняется —
подменяются ОБРАЗЕЦ и ЦЕЛЬ во временном каталоге."""
import contextlib
import io
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_dev_env  # noqa: E402

ОБРАЗЕЦ_ТЕКСТ = """# образец
POSTGRES_PASSWORD=***
SMTP_HOST=mailpit
IMAP_PASSWORD=***
# IMAP_HOST=imap.example.com
# IMAP_USER=tickets
"""
# в старом файле есть пароль базы и закомментированный IMAP_HOST (он не в счёт)
СТАРЫЙ_ТЕКСТ = "POSTGRES_PASSWORD=старое-значение-1\nSMTP_HOST=старый-хост\n# IMAP_HOST=закомментировано\nIMAP_USER=старый-пользователь"


class MakeDevEnvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        каталог = Path(self.tmp.name)
        self.образец = каталог / ".env.example"
        self.цель = каталог / ".env"
        self.образец.write_text(ОБРАЗЕЦ_ТЕКСТ, encoding="utf-8")
        for имя, значение in (("ОБРАЗЕЦ", self.образец), ("ЦЕЛЬ", self.цель)):
            старое = getattr(make_dev_env, имя)
            setattr(make_dev_env, имя, значение)
            self.addCleanup(setattr, make_dev_env, имя, старое)
        # относительные пути в сообщениях считаются от КОРЕНЬ: он тоже во временном каталоге
        старый_корень = make_dev_env.КОРЕНЬ
        make_dev_env.КОРЕНЬ = каталог
        self.addCleanup(setattr, make_dev_env, "КОРЕНЬ", старый_корень)

    def запуск(self, арг):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            код = make_dev_env.main(арг)
        return код, out.getvalue() + err.getvalue()

    def значения(self):
        результат = {}
        for строка in self.цель.read_text(encoding="utf-8").splitlines():
            if строка and not строка.startswith("#") and "=" in строка:
                имя, _, знач = строка.partition("=")
                результат[имя] = знач
        return результат

    def test_add_missing_appends_only_missing_names_keeps_values_and_prints_no_secrets(self):
        старые_байты = СТАРЫЙ_ТЕКСТ.encode("utf-8")
        self.цель.write_bytes(старые_байты)
        self.цель.chmod(0o640)

        код, вывод = self.запуск(["--add-missing"])
        self.assertEqual(код, 0)
        новые = self.цель.read_bytes()
        self.assertTrue(новые.startswith(старые_байты), "прежние строки должны остаться побайтно и первыми")
        значения = self.значения()
        ожидаемо_дописаны = set(make_dev_env.СТЕНД) | {"IMAP_PASSWORD"}
        self.assertEqual(set(значения), {"POSTGRES_PASSWORD", "SMTP_HOST", "IMAP_USER"} | ожидаемо_дописаны)
        self.assertEqual(значения["POSTGRES_PASSWORD"], "старое-значение-1")
        self.assertEqual(значения["IMAP_USER"], "старый-пользователь")
        self.assertEqual(значения["IMAP_HOST"], make_dev_env.СТЕНД["IMAP_HOST"])
        self.assertNotIn("IMAP_USER", новые[len(старые_байты):].decode("utf-8").replace("# IMAP_USER", ""))
        self.assertTrue(значения["IMAP_PASSWORD"])
        self.assertNotEqual(значения["IMAP_PASSWORD"], "***")
        self.assertEqual(stat.S_IMODE(self.цель.stat().st_mode), 0o600)
        # в выводе — только имена
        for имя in ("IMAP_HOST", "IMAP_PORT", "IMAP_PASSWORD"):
            self.assertIn(имя, вывод)
        for знач in значения.values():
            self.assertNotIn(знач, вывод)
        for знач in ("старое-значение-1", "старый-хост", "старый-пользователь", "tickets@stand.test"):
            self.assertNotIn(знач, вывод)

        # повторный запуск ничего не дописывает
        после = self.цель.read_bytes()
        код, вывод = self.запуск(["--add-missing"])
        self.assertEqual(код, 0)
        self.assertEqual(self.цель.read_bytes(), после)
        self.assertIn("нечего дописывать", вывод)
        for знач in значения.values():
            self.assertNotIn(знач, вывод)

    def test_fresh_create_appends_stand_values_missing_from_example(self):
        код, вывод = self.запуск([])
        self.assertEqual(код, 0)
        значения = self.значения()
        for имя, знач in make_dev_env.СТЕНД.items():
            self.assertEqual(значения[имя], знач)
        self.assertNotIn("***", self.цель.read_text(encoding="utf-8"))
        self.assertEqual(stat.S_IMODE(self.цель.stat().st_mode), 0o600)
        for знач in значения.values():
            self.assertNotIn(знач, вывод)

    def test_add_missing_without_env_creates_file_like_fresh_run(self):
        # проверка R-stage1a, находка 5: без deploy/.env режим работает как обычное создание
        self.assertFalse(self.цель.exists())
        код, вывод = self.запуск(["--add-missing"])
        self.assertEqual(код, 0)
        значения = self.значения()
        for имя, знач in make_dev_env.СТЕНД.items():
            self.assertEqual(значения[имя], знач)
        self.assertNotIn("***", self.цель.read_text(encoding="utf-8"))
        self.assertEqual(stat.S_IMODE(self.цель.stat().st_mode), 0o600)
        for знач in значения.values():
            if знач:
                self.assertNotIn(знач, вывод)

    def test_add_missing_keeps_name_with_empty_value(self):
        # проверка R-stage1b, находка 8: пустое значение считается заданным (докстринг скрипта)
        self.цель.write_text("IMAP_PASSWORD=\n", encoding="utf-8")
        self.цель.chmod(0o600)
        код, вывод = self.запуск(["--add-missing"])
        self.assertEqual(код, 0)
        строки = self.цель.read_text(encoding="utf-8").splitlines()
        self.assertEqual(строки[0], "IMAP_PASSWORD=")
        self.assertEqual([с for с in строки if с.startswith("IMAP_PASSWORD=")], ["IMAP_PASSWORD="])
        self.assertNotIn("IMAP_PASSWORD", вывод)

    def test_force_with_add_missing_is_refused(self):
        self.цель.write_text("A=1\n", encoding="utf-8")
        код, _ = self.запуск(["--force", "--add-missing"])
        self.assertEqual(код, 1)
        self.assertEqual(self.цель.read_text(encoding="utf-8"), "A=1\n")


if __name__ == "__main__":
    unittest.main()
