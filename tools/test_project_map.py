"""Тесты tools/project_map.py — сборщика фактов локальной карты CRM.

Каждый тест строит мини-репозиторий SDD во временном каталоге (specs/,
docs/reference/capabilities.md, docs/reviews/TASKS-NNN.md; при необходимости —
git-история коммитами в этом же каталоге) и вызывает project_map.build_snapshot.
Настоящие документы проекта не читаются и не меняются; секретов и ПДн нет.

Красный набор этапа 1 плана 2026-11-22-crm-project-map.md: чтение срезов,
задач с вложенными чек-листами, приёмки из отчётов, карта возможностей,
ограниченная Git-история отметок и отдельная рабочая дельта.

Запуск: python3 -m unittest tools/test_project_map.py — из корня репозитория.
"""

import subprocess
import tempfile
import unittest
import http.client
import json
import threading
from pathlib import Path

try:
    from tools import project_map
except ImportError:  # запуск не через "python3 -m unittest tools/test_project_map.py"
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import project_map


# --------------------------------------------------------------------------
# Вспомогательные функции


def _tmp_base():
    """Каталог для временных репозиториев: /tmp/opencode, если есть."""
    base = Path("/tmp/opencode")
    return base if base.is_dir() else None


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fm(doc_id: str, kind: str, status: str, body: str = "\n# Документ\n") -> str:
    """Собирает документ SDD: frontmatter + тело."""
    return (
        "---\n"
        f"id: {doc_id}\n"
        f"вид: {kind}\n"
        f"статус: {status}\n"
        "версия: 1\n"
        "---\n" + body
    )


def _make_slice(
    root: Path,
    num: str,
    slug: str,
    *,
    title: str = "Демо",
    tasks_text: str = "",
    spec_text: str | None = None,
    spec_status: str = "утверждён",
    plan_status: str = "утверждён",
    tasks_status: str = "утверждён",
) -> Path:
    """Создаёт specs/NNN-slug/ со спекой, планом и задачами."""
    directory = root / "specs" / f"{num}-{slug}"
    if spec_text is None:
        spec_text = f"# Срез {num}: {title}\n\nТекст спеки, ссылка на CAP-01.\n"
    _write(directory / "spec.md", _fm(f"SPEC-{num}", "спека", spec_status, "\n" + spec_text))
    _write(directory / "plan.md", _fm(f"PLAN-{num}", "план", plan_status, f"\n# План среза {num}\n"))
    _write(directory / "tasks.md", _fm(f"TASKS-{num}", "задачи", tasks_status, "\n# Задачи среза\n\n" + tasks_text))
    return directory


def _make_capabilities(root: Path, rows) -> Path:
    """Создаёт docs/reference/capabilities.md с таблицей возможностей."""
    lines = [
        "---",
        "id: REF-CAP",
        "вид: эталон",
        "статус: утверждён",
        "версия: 1",
        "---",
        "",
        "# Карта возможностей",
        "",
        "| CAP | Возможность | Эталон | Предложение | Решение |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    path = root / "docs" / "reference" / "capabilities.md"
    _write(path, "\n".join(lines) + "\n")
    return path


def _make_review(root: Path, num: str, body: str) -> Path:
    """Создаёт docs/reviews/TASKS-NNN.md с телом отчёта."""
    text = _fm(f"REV-TASKS-{num}", "отчёт", "черновик", "\n# Отчёт проверки TASKS-" + num + "\n\n" + body)
    path = root / "docs" / "reviews" / f"TASKS-{num}.md"
    _write(path, text)
    return path


def _git(root: Path, *args: str):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )


def _git_init(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Тестовый коммитер")
    _git(root, "config", "user.email", "test@example.com")


def _commit(root: Path, message: str, paths=("specs", "docs")) -> None:
    _git(root, "add", "--", *paths)
    _git(root, "commit", "-q", "-m", message)


def _codes(warnings) -> set:
    return {w["code"] for w in warnings}


def _by_number(snapshot):
    return {s["number"]: s for s in snapshot["slices"]}


def _by_cap(snapshot):
    return {c["id"]: c for c in snapshot["capabilities"]}


# --------------------------------------------------------------------------
# Снимок: общий вид


class SnapshotShapeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="project-map-test-", dir=_tmp_base())
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_snapshot_has_core_keys(self):
        _make_capabilities(self.root, [("CAP-01", "Учётные записи", "REF", "MVP", "MVP")])
        _make_slice(self.root, "001", "demo", tasks_text="- [x] T-1001 готово\n")
        snapshot = project_map.build_snapshot(self.root)
        for key in ("slices", "capabilities", "history", "revision", "warnings"):
            self.assertIn(key, snapshot)

    def test_symlink_sources_and_ancestors_are_not_read(self):
        outside = self.root / "outside"
        _make_slice(outside, "001", "demo", tasks_text="- [x] T-1001 чужое\n")
        (self.root / "specs").symlink_to(outside / "specs", target_is_directory=True)
        snapshot = project_map.build_snapshot(self.root)
        self.assertEqual(snapshot["slices"], [])
        self.assertTrue(snapshot["warnings"])

    def test_symlink_file_is_not_read_even_in_git_worktree(self):
        _git_init(self.root)
        directory = _make_slice(self.root, "001", "demo", tasks_text="- [ ] T-1001 своё\n")
        _commit(self.root, "база", paths=("specs",))
        (directory / "tasks.md").unlink()
        outside = self.root / "synthetic"
        outside.write_text("- [x] T-9999 чужое\n", encoding="utf-8")
        (directory / "tasks.md").symlink_to(outside)
        snapshot = project_map.build_snapshot(self.root)
        self.assertFalse(_by_number(snapshot)["001"]["tasks"]["present"])
        self.assertNotIn("T-9999", str(snapshot))

    def test_symlinked_review_capabilities_and_slice_directory_are_ignored(self):
        _make_slice(self.root, "001", "demo", tasks_text="- [ ] T-1001 своё\n")
        outside = self.root / "synthetic"
        _make_slice(outside, "002", "foreign", tasks_text="- [x] T-9999 чужое\n")
        (self.root / "specs" / "002-foreign").symlink_to(outside / "specs" / "002-foreign", target_is_directory=True)
        _make_capabilities(outside, [("CAP-99", "чужое", "REF", "MVP", "MVP")])
        _make_review(outside, "001", "Владелец принял срез 001.")
        (self.root / "docs").mkdir()
        (self.root / "docs" / "reference").symlink_to(outside / "docs" / "reference", target_is_directory=True)
        (self.root / "docs" / "reviews").symlink_to(outside / "docs" / "reviews", target_is_directory=True)
        snapshot = project_map.build_snapshot(self.root)
        self.assertEqual(list(_by_number(snapshot)), ["001"])
        self.assertEqual(snapshot["capabilities"], [])
        self.assertFalse(_by_number(snapshot)["001"]["acceptance"]["confirmed"])

    def test_git_symlink_blob_is_not_parsed_as_task(self):
        _git_init(self.root)
        directory = _make_slice(self.root, "001", "demo", tasks_text="- [ ] T-1001 своё\n")
        _commit(self.root, "база", paths=("specs",))
        (directory / "tasks.md").unlink()
        (directory / "tasks.md").symlink_to("- [x] T-9999 чужое")
        _commit(self.root, "ссылка", paths=("specs",))
        snapshot = project_map.build_snapshot(self.root)
        self.assertNotIn("T-9999", str(snapshot))
        self.assertEqual(snapshot["history"]["commits"][0]["tasks"]["001"]["removed"], ["T-1001"])


# --------------------------------------------------------------------------
# Срезы и задачи


class SliceTasksTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="project-map-test-", dir=_tmp_base())
        self.root = Path(self._tmp.name)
        _make_capabilities(self.root, [("CAP-01", "Учётные записи", "REF", "MVP", "MVP")])

    def tearDown(self):
        self._tmp.cleanup()

    def test_counts_and_open_ids(self):
        tasks_text = (
            "- [x] T-1001 первая\n"
            "- [ ] T-1002 вторая\n"
            "- [X] T-1003 третья\n"
            "- [x] T-1004a четвёртая с суффиксом\n"
        )
        _make_slice(self.root, "001", "demo", tasks_text=tasks_text)
        snapshot = project_map.build_snapshot(self.root)
        tasks = _by_number(snapshot)["001"]["tasks"]
        self.assertEqual(tasks["total"], 4)
        self.assertEqual(tasks["done"], 3)
        self.assertEqual(tasks["open"], 1)
        self.assertEqual(tasks["open_ids"], ["T-1002"])
        self.assertAlmostEqual(tasks["percent"], 75.0)
        self.assertEqual([item["id"] for item in tasks["items"]], ["T-1001", "T-1002", "T-1003", "T-1004a"])
        self.assertEqual(tasks["items"][1]["title"], "вторая")
        self.assertFalse(tasks["items"][1]["done"])

    def test_mixed_fences_require_matching_kind_and_length(self):
        text = "~~~~ markdown\n- [x] T-9999 пример\n```\n- [ ] T-9998 пример\n~~~\n- [ ] T-9997 пример\n~~~~\n- [x] T-1001 задача\n"
        items, _ = project_map._parse_task_lines(text)
        self.assertEqual(list(items), ["T-1001"])

    def test_task_counted_once_with_nested_checklist(self):
        """T-123 при вложенном чек-листе учитывается один раз (проверка плана)."""
        tasks_text = (
            "- [ ] T-123 [sonnet] внешняя задача\n"
            "  1. вложенный нумерованный пункт\n"
            "  2. ещё пункт\n"
            "  - [ ] вложенный чек-лист: сверить T-123\n"
            "  - [x] вложенная отметка про T-124\n"
        )
        _make_slice(self.root, "001", "demo", tasks_text=tasks_text)
        snapshot = project_map.build_snapshot(self.root)
        tasks = _by_number(snapshot)["001"]["tasks"]
        self.assertEqual(tasks["total"], 1)
        self.assertEqual(tasks["done"], 0)
        self.assertEqual([item["id"] for item in tasks["items"]], ["T-123"])

    def test_numbered_and_code_checklists_not_tasks(self):
        tasks_text = (
            "1. нумерованный пункт внутри задачи\n"
            "2. второй пункт\n"
            "\n"
            "- [x] T-1001 настоящая задача\n"
            "\n"
            "Пример формата:\n"
            "\n"
            "```\n"
            "- [ ] T-9999 пример строки задачи из документации\n"
            "- [x] T-9998 ещё пример\n"
            "```\n"
        )
        _make_slice(self.root, "001", "demo", tasks_text=tasks_text)
        snapshot = project_map.build_snapshot(self.root)
        tasks = _by_number(snapshot)["001"]["tasks"]
        self.assertEqual(tasks["total"], 1)
        self.assertEqual([item["id"] for item in tasks["items"]], ["T-1001"])

    def test_doc_statuses_and_slice_title(self):
        _make_slice(
            self.root, "008", "messenger",
            title="Мессенджер",
            tasks_text="- [x] T-8001 каркас\n",
            spec_status="на-проверке",
            plan_status="утверждён",
            tasks_status="черновик",
        )
        snapshot = project_map.build_snapshot(self.root)
        slice_ = _by_number(snapshot)["008"]
        self.assertEqual(slice_["title"], "Мессенджер")
        self.assertEqual(slice_["dir"], "008-messenger")
        docs = slice_["docs"]
        self.assertEqual(docs["spec"]["id"], "SPEC-008")
        self.assertEqual(docs["spec"]["status"], "на-проверке")
        self.assertEqual(docs["plan"]["status"], "утверждён")
        self.assertEqual(docs["tasks"]["status"], "черновик")
        self.assertEqual(docs["tasks"]["path"], "specs/008-messenger/tasks.md")
        self.assertTrue(all(docs[k]["exists"] for k in ("spec", "plan", "tasks")))

    def test_duplicate_task_line_counted_once_and_warns(self):
        tasks_text = "- [ ] T-1001 первая строка\n- [x] T-1001 дубль строки\n"
        _make_slice(self.root, "001", "demo", tasks_text=tasks_text)
        snapshot = project_map.build_snapshot(self.root)
        slice_ = _by_number(snapshot)["001"]
        self.assertEqual(slice_["tasks"]["total"], 1)
        self.assertIn("duplicate-task-id", _codes(snapshot["warnings"]))

    def test_html_in_task_title_stays_text(self):
        """HTML в названии задачи хранится как текст и не интерпретируется."""
        raw = "внедрить <b>жирный</b> и <img src=x onerror=alert(1)>"
        _make_slice(self.root, "001", "demo", tasks_text=f"- [x] T-1001 {raw}\n")
        snapshot = project_map.build_snapshot(self.root)
        item = _by_number(snapshot)["001"]["tasks"]["items"][0]
        self.assertEqual(item["title"], raw)


# --------------------------------------------------------------------------
# Отсутствующие и пустые источники


class MissingSourcesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="project-map-test-", dir=_tmp_base())
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_and_empty_sources_are_explicit(self):
        # 001: нет tasks.md; 002: tasks.md без чек-листа; capabilities.md нет вовсе.
        _make_slice(self.root, "001", "demo", tasks_text="")
        (self.root / "specs" / "001-demo" / "tasks.md").unlink()
        _make_slice(self.root, "002", "empty", tasks_text="Текст без задач.\n")
        snapshot = project_map.build_snapshot(self.root)
        slices = _by_number(snapshot)
        self.assertFalse(slices["001"]["docs"]["tasks"]["exists"])
        self.assertFalse(slices["001"]["tasks"]["present"])
        self.assertIsNone(slices["001"]["tasks"]["percent"])
        self.assertFalse(slices["002"]["tasks"]["present"])
        self.assertIsNone(slices["002"]["tasks"]["percent"])
        self.assertEqual(snapshot["capabilities"], [])
        codes = _codes(snapshot["warnings"])
        self.assertIn("no-tasks-file", codes)
        self.assertIn("no-checklist", codes)
        self.assertIn("no-capabilities", codes)

    def test_no_specs_dir_is_explicit(self):
        _make_capabilities(self.root, [("CAP-01", "Учётные записи", "REF", "MVP", "MVP")])
        snapshot = project_map.build_snapshot(self.root)
        self.assertEqual(snapshot["slices"], [])
        self.assertIn("no-specs-dir", _codes(snapshot["warnings"]))

    def test_capabilities_without_rows_warns(self):
        path = self.root / "docs" / "reference" / "capabilities.md"
        _write(path, "# Карта возможностей\n\nПока пусто.\n")
        _make_slice(self.root, "001", "demo", tasks_text="- [x] T-1001 готово\n")
        snapshot = project_map.build_snapshot(self.root)
        self.assertEqual(snapshot["capabilities"], [])
        self.assertIn("empty-capabilities", _codes(snapshot["warnings"]))

    def test_empty_tasks_checklist_counts_as_absent_not_zero_progress(self):
        _make_capabilities(self.root, [("CAP-01", "Учётные записи", "REF", "MVP", "MVP")])
        _make_slice(self.root, "001", "demo", tasks_text="Описание есть, чек-листа нет.\n")
        snapshot = project_map.build_snapshot(self.root)
        tasks = _by_number(snapshot)["001"]["tasks"]
        self.assertEqual(tasks["total"], 0)
        self.assertIsNone(tasks["percent"])
        self.assertFalse(tasks["present"])


# --------------------------------------------------------------------------
# Приёмка из отчётов


class AcceptanceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="project-map-test-", dir=_tmp_base())
        self.root = Path(self._tmp.name)
        _make_capabilities(self.root, [("CAP-01", "Учётные записи", "REF", "MVP", "MVP")])

    def tearDown(self):
        self._tmp.cleanup()

    def test_acceptance_extracted_from_review(self):
        _make_slice(self.root, "008", "messenger", tasks_text="- [x] T-8001 всё\n")
        _make_review(
            self.root, "008",
            "## Приёмка (T-8309)\n\n"
            "**Владелец принял срез 008 «Мессенджер» 2026-11-21** (слова: «все принимаю»). "
            "Принято: отчёт T-8307, проход T-8301.\n",
        )
        # вторая форма: «Срез NNN принят владельцем»
        _make_slice(self.root, "001", "access", tasks_text="- [x] T-1001 всё\n")
        _make_review(
            self.root, "001",
            "## T-307: приёмка среза — владелец 2026-10-04\n\n"
            "**Срез 001 принят владельцем 2026-10-04** по этому отчёту: итог T-306.\n",
        )
        snapshot = project_map.build_snapshot(self.root)
        acc8 = _by_number(snapshot)["008"]["acceptance"]
        self.assertTrue(acc8["confirmed"])
        self.assertEqual(acc8["source"], "docs/reviews/TASKS-008.md")
        self.assertEqual(acc8["section"], "Приёмка (T-8309)")
        self.assertEqual(acc8["date"], "2026-11-21")
        self.assertIn("принял срез 008", acc8["note"])
        acc1 = _by_number(snapshot)["001"]["acceptance"]
        self.assertTrue(acc1["confirmed"])
        self.assertEqual(acc1["date"], "2026-10-04")

    def test_uncertain_or_fenced_claims_are_not_acceptance(self):
        _make_slice(self.root, "009", "tasks", tasks_text="- [ ] T-9001 задача\n")
        for claim in (
            "Проверяющий принял срез 009, владелец ещё не принимал.",
            "Если владелец принял срез 009, закрыть задачу.",
            "Владелец не принял срез 009.",
            "Владелец принял срез 009?",
            "    Владелец принял срез 009.",
            "\tСрез 009 принят владельцем.",
            "~~~\nВладелец принял срез 009.\n~~~",
            "```\nСрез 009 принят владельцем.\n```",
        ):
            with self.subTest(claim=claim):
                _make_review(self.root, "009", claim)
                self.assertFalse(_by_number(project_map.build_snapshot(self.root))["009"]["acceptance"]["confirmed"])

    def test_full_done_without_acceptance_warns(self):
        """100 % отметок без приёмки — явное «не подтверждено картой» и предупреждение."""
        tasks_text = "- [x] T-5001 а\n- [x] T-5002 б\n"
        _make_slice(self.root, "005", "knowledge", tasks_text=tasks_text)
        _make_review(self.root, "005", "## Итог\n\nВсё закрыто, отчётов приёмки нет.\n")
        snapshot = project_map.build_snapshot(self.root)
        slice_ = _by_number(snapshot)["005"]
        self.assertEqual(slice_["tasks"]["percent"], 100.0)
        acc = slice_["acceptance"]
        self.assertFalse(acc["confirmed"])
        self.assertIn("не подтверждено картой", acc["note"])
        self.assertIn("done-without-acceptance", _codes(snapshot["warnings"]))

    def test_runs_without_verdict_are_not_acceptance(self):
        """Прогон запущен, итога в источнике нет — срез не принят (случай 009)."""
        tasks_text = "- [x] T-9001 а\n- [ ] T-9309 приёмка\n"
        _make_slice(self.root, "009", "tasks", tasks_text=tasks_text)
        _make_review(
            self.root, "009",
            "## Этап 4 — приёмка: прогоны и ворота (2026-11-22)\n\n"
            "- **T-9302 — приёмка Playwright запущена** (systemd-run); результат будет в этом же разделе.\n"
            "- Полный серверный прогон: 4613 passed, 0 failed.\n",
        )
        snapshot = project_map.build_snapshot(self.root)
        acc = _by_number(snapshot)["009"]["acceptance"]
        self.assertFalse(acc["confirmed"])
        self.assertIn("не подтверждено картой", acc["note"])
        self.assertNotIn("done-without-acceptance", _codes(snapshot["warnings"]))

    def test_accepted_with_open_exception(self):
        """Принято с открытым исключением: открытая задача перечислена (случай 007)."""
        tasks_text = "- [x] T-7001 всё\n- [ ] T-7304 нагрузка\n"
        _make_slice(self.root, "007", "feed", tasks_text=tasks_text)
        _make_review(
            self.root, "007",
            "## Приёмка среза (T-7310) — 2026-11-16\n\n"
            "Владелец через форму **принял срез 007** по отчёту T-7308 (известный дефект NFR-612, T-7304).\n",
        )
        snapshot = project_map.build_snapshot(self.root)
        slice_ = _by_number(snapshot)["007"]
        self.assertTrue(slice_["acceptance"]["confirmed"])
        self.assertEqual(slice_["exceptions"], ["T-7304"])
        self.assertIn("accepted-with-open-tasks", _codes(snapshot["warnings"]))

    def test_missing_review_file_is_explicit(self):
        _make_slice(self.root, "003", "servicedesk", tasks_text="- [x] T-3001 всё\n")
        snapshot = project_map.build_snapshot(self.root)
        acc = _by_number(snapshot)["003"]["acceptance"]
        self.assertFalse(acc["confirmed"])
        self.assertIsNone(acc["source"])
        self.assertIn("TASKS-003", acc["note"])
        self.assertIn("no-review-file", _codes(snapshot["warnings"]))


# --------------------------------------------------------------------------
# Карта возможностей


class CapabilitiesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="project-map-test-", dir=_tmp_base())
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_decision_beats_proposal(self):
        """CAP с предложением «позже» и решением MVP: решением считается MVP (CAP-105)."""
        _make_capabilities(
            self.root,
            [
                ("CAP-105", "Универсальные списки", "REF-MOD-BIZPROC (SRC-355)", "позже (кандидат)", "MVP (учёт оборудования)"),
                ("CAP-44", "Задачи", "REF-MOD-TASKS (SRC-101)", "MVP (внутренняя работа)", "позже (вместе с задачами)"),
            ],
        )
        _make_slice(self.root, "006", "lists", spec_text="# Срез 006: Списки\n\nТаблица: CAP-105 конструктор и CAP-105 права.\n")
        snapshot = project_map.build_snapshot(self.root)
        cap = _by_cap(snapshot)["CAP-105"]
        self.assertEqual(cap["decision"], "MVP")
        self.assertEqual(cap["proposal"], "позже")
        self.assertEqual(cap["covered_by"], ["006"])

    def test_pozzhe_cap_in_slice_is_not_untouched(self):
        """Возможность «позже», включённая в срез, не показывается как нетронутая."""
        _make_capabilities(
            self.root,
            [("CAP-44", "Задачи", "REF-MOD-TASKS", "MVP", "позже (вместе с задачами)")],
        )
        _make_slice(self.root, "009", "tasks", spec_text="# Срез 009: Задачи\n\nТребования CAP-44.\n")
        snapshot = project_map.build_snapshot(self.root)
        cap = _by_cap(snapshot)["CAP-44"]
        self.assertEqual(cap["decision"], "позже")
        self.assertEqual(cap["covered_by"], ["009"])
        self.assertNotEqual(cap["state"], "позже")

    def test_cap_without_decision(self):
        _make_capabilities(self.root, [("CAP-01", "Учётные записи", "REF", "MVP", "")])
        _make_slice(self.root, "001", "demo", tasks_text="- [x] T-1001 готово\n")
        snapshot = project_map.build_snapshot(self.root)
        cap = _by_cap(snapshot)["CAP-01"]
        self.assertEqual(cap["decision"], "")
        self.assertIn("cap-without-decision", _codes(snapshot["warnings"]))


# --------------------------------------------------------------------------
# Git: история и рабочая дельта


class GitHistoryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="project-map-test-", dir=_tmp_base())
        self.root = Path(self._tmp.name)
        _make_capabilities(self.root, [("CAP-01", "Учётные записи", "REF", "MVP", "MVP")])
        _git_init(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_history_marks_by_commit(self):
        tasks = self.root / "specs" / "001-demo" / "tasks.md"
        _make_slice(self.root, "001", "demo", tasks_text="- [ ] T-1001 а\n- [ ] T-1002 б\n")
        _commit(self.root, "база")
        tasks.write_text(
            _fm("TASKS-001", "задачи", "утверждён", "\n# Задачи среза\n\n- [x] T-1001 а\n- [x] T-1002 б\n- [ ] T-1003 в\n"),
            encoding="utf-8",
        )
        _commit(self.root, "отметки")
        tasks.write_text(
            _fm("TASKS-001", "задачи", "утверждён", "\n# Задачи среза\n\n- [x] T-1001 а\n- [ ] T-1002 б\n"),
            encoding="utf-8",
        )
        _commit(self.root, "снятие")
        snapshot = project_map.build_snapshot(self.root)
        history = snapshot["history"]
        self.assertTrue(history["available"])
        self.assertEqual(len(history["commits"]), 3)
        newest, middle, oldest = history["commits"]
        self.assertEqual(newest["message"], "снятие")
        self.assertEqual(newest["tasks"]["001"]["unchecked"], ["T-1002"])
        self.assertEqual(newest["tasks"]["001"]["removed"], ["T-1003"])
        self.assertEqual(newest["tasks"]["001"]["checked"], [])
        self.assertEqual(middle["tasks"]["001"]["checked"], ["T-1001", "T-1002"])
        self.assertEqual(middle["tasks"]["001"]["added"], ["T-1003"])
        self.assertEqual(oldest["tasks"]["001"]["added"], ["T-1001", "T-1002"])
        for commit in history["commits"]:
            self.assertTrue(commit["short"])
            self.assertTrue(commit["date"])

    def test_history_compares_full_markdown_context(self):
        directory = _make_slice(self.root, "001", "demo", tasks_text="~~~\n- [ ] T-9999 пример\n~~~\n- [ ] T-1001 задача\n")
        _commit(self.root, "база")
        tasks = directory / "tasks.md"
        tasks.write_text(tasks.read_text(encoding="utf-8").replace("- [ ] T-9999", "- [x] T-9999"), encoding="utf-8")
        _commit(self.root, "пример")
        tasks.write_text(tasks.read_text(encoding="utf-8").replace("~~~\n", "", 2), encoding="utf-8")
        snapshot = project_map.build_snapshot(self.root)
        commit_tasks = snapshot["history"]["commits"][0]["tasks"]
        self.assertFalse(commit_tasks.get("001", {}).get("checked"))
        self.assertEqual(snapshot["history"]["worktree"]["tasks"]["001"]["added"], ["T-9999"])
        _commit(self.root, "убрано ограждение")
        snapshot = project_map.build_snapshot(self.root)
        self.assertEqual(snapshot["history"]["commits"][0]["tasks"]["001"]["added"], ["T-9999"])

    def test_history_is_limited(self):
        tasks = self.root / "specs" / "001-demo" / "tasks.md"
        _make_slice(self.root, "001", "demo", tasks_text="- [ ] T-1001 а\n")
        for index in range(3):
            _commit(self.root, f"коммит {index}")
            tasks.write_text(
                _fm("TASKS-001", "задачи", "утверждён", f"\n# Задачи среза\n\n- [x] T-100{index + 2} номер {index}\n"),
                encoding="utf-8",
            )
        _commit(self.root, "последний")
        snapshot = project_map.build_snapshot(self.root, history_limit=2)
        history = snapshot["history"]
        self.assertEqual(history["limit"], 2)
        self.assertEqual(len(history["commits"]), 2)
        self.assertEqual(history["commits"][0]["message"], "последний")

    def test_worktree_removed_mark_is_separate_layer(self):
        """Снятая рабочая отметка после коммита — в дельте рабочей копии, не в истории."""
        tasks = self.root / "specs" / "001-demo" / "tasks.md"
        _make_slice(self.root, "001", "demo", tasks_text="- [x] T-1001 а\n")
        _commit(self.root, "база")
        tasks.write_text(
            _fm("TASKS-001", "задачи", "утверждён", "\n# Задачи среза\n\n- [ ] T-1001 а\n"),
            encoding="utf-8",
        )
        snapshot = project_map.build_snapshot(self.root)
        history = snapshot["history"]
        worktree = history["worktree"]
        self.assertTrue(worktree["dirty"])
        self.assertEqual(worktree["tasks"]["001"]["unchecked"], ["T-1001"])
        self.assertNotEqual(history["commits"][0]["tasks"]["001"].get("unchecked"), ["T-1001"])
        self.assertTrue(snapshot["revision"]["dirty"])
        # текущее состояние снимка читается с диска: задача открыта
        self.assertEqual(_by_number(snapshot)["001"]["tasks"]["open_ids"], ["T-1001"])

    def test_worktree_new_slice_delta(self):
        _make_slice(self.root, "001", "demo", tasks_text="- [x] T-1001 а\n")
        _commit(self.root, "база")
        _make_slice(self.root, "010", "later", tasks_text="- [x] T-1001 новая\n")
        snapshot = project_map.build_snapshot(self.root)
        worktree = snapshot["history"]["worktree"]
        self.assertTrue(worktree["dirty"])
        self.assertIn("specs/010-later/tasks.md", worktree["files"])
        self.assertEqual(worktree["tasks"]["010"]["added"], ["T-1001"])
        self.assertIn("untracked-map-file", _codes(snapshot["warnings"]))
        self.assertEqual(_by_number(snapshot)["010"]["tasks"]["total"], 1)

    def test_revision_ignores_non_map_commits(self):
        _make_slice(self.root, "001", "demo", tasks_text="- [x] T-1001 а\n")
        _commit(self.root, "карта")
        first = project_map.build_snapshot(self.root)["revision"]
        self.assertTrue(first["available"])
        self.assertEqual(first["message"], "карта")
        _write(self.root / "backend" / "code.py", "x = 1\n")
        _commit(self.root, "код вне карты", paths=("backend",))
        second = project_map.build_snapshot(self.root)["revision"]
        self.assertEqual(second["short"], first["short"])
        capabilities = self.root / "docs" / "reference" / "capabilities.md"
        capabilities.write_text(capabilities.read_text(encoding="utf-8") + "| CAP-02 | Группы | REF | MVP | MVP |\n", encoding="utf-8")
        _commit(self.root, "карта возможностей обновлена")
        third = project_map.build_snapshot(self.root)["revision"]
        self.assertNotEqual(third["short"], first["short"])
        self.assertEqual(third["message"], "карта возможностей обновлена")
        self.assertTrue(third["date"])  # дата последнего изменения источников карты

    def test_no_git_repo_still_reads_files(self):
        root = Path(tempfile.mkdtemp(prefix="project-map-nogit-", dir=_tmp_base()))
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        _make_capabilities(root, [("CAP-01", "Учётные записи", "REF", "MVP", "MVP")])
        _make_slice(root, "001", "demo", tasks_text="- [x] T-1001 а\n")
        snapshot = project_map.build_snapshot(root)
        self.assertFalse(snapshot["history"]["available"])
        self.assertFalse(snapshot["revision"]["available"])
        self.assertIn("no-git", _codes(snapshot["warnings"]))
        self.assertEqual(_by_number(snapshot)["001"]["tasks"]["done"], 1)


class HttpMapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=_tmp_base())
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.directory = _make_slice(self.root, "001", "demo", tasks_text="- [ ] T-1001 первая\n")
        self.server = project_map.make_server(self.root, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.shutdown)

    def request(self, path, host=None, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        self.addCleanup(conn.close)
        conn.request(method, path, headers={} if host is None else {"Host": host})
        response = conn.getresponse()
        return response.status, response.read()

    def test_only_page_and_map_routes(self):
        self.assertEqual(self.request("/")[0], 200)
        self.assertEqual(self.request("/api/map")[0], 200)
        for path in ("/README.md", "/.env", "/tools/project_map.py", "/%2eenv", "/api/map?x=1", "//api/map"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)

    def test_host_validation_and_methods(self):
        port = self.server.server_port
        for host in ("evil.example", f"localhost.evil.example:{port}", f"127.0.0.1:{port + 1}", "localhost", "127.0.0.1:8765,evil"):
            with self.subTest(host=host):
                self.assertEqual(self.request("/", host)[0], 403)
        self.assertEqual(self.request("/", f"localhost:{port}")[0], 200)
        self.assertEqual(self.request("/", method="POST")[0], 405)

    def test_map_is_rebuilt_on_each_request(self):
        first = json.loads(self.request("/api/map")[1])
        tasks = self.directory / "tasks.md"
        tasks.write_text(tasks.read_text(encoding="utf-8").replace("[ ]", "[x]"), encoding="utf-8")
        second = json.loads(self.request("/api/map")[1])
        self.assertEqual(first["slices"][0]["tasks"]["done"], 0)
        self.assertEqual(second["slices"][0]["tasks"]["done"], 1)

    def test_failure_does_not_disclose_exception(self):
        from unittest.mock import patch
        with patch.object(project_map, "build_snapshot", side_effect=RuntimeError("private detail")):
            status, body = self.request("/api/map")
        self.assertEqual(status, 500)
        self.assertNotIn(b"private detail", body)


if __name__ == "__main__":
    unittest.main()
