#!/usr/bin/env python3
"""Локальная карта CRM: сбор фактов из SDD-источников репозитория.

Инструмент разработчика (план docs/superpowers/plans/2026-11-22-crm-project-map.md):
читает рабочую копию и собирает снимок `build_snapshot(root)` — факты о срезах,
возможностях и Git-истории отметок задач. В Git выполняются только операции чтения
(log / show / status), `fetch` не запускается, ничего не коммитится.

Источники карты: `specs/NNN-*/` (спека, план, задачи), `docs/reference/capabilities.md`,
`docs/reviews/TASKS-NNN.md`. Прогресс не выдумывается: пустые и частично
отсутствующие источники обозначаются явно и попадают в `warnings`.

Схема снимка (dict, ключи как в плане — slices, capabilities, history, revision, warnings):

    slices: [
        {
            "number": "008",            # номер из имени каталога
            "dir": "008-messenger",
            "title": "Мессенджер",      # из заголовка спеки («# Срез 008: …»)
            "docs": {                   # статус каждого документа из frontmatter
                "spec":  {"path": str, "exists": bool, "id": str|None, "status": str|None},
                "plan":  {...}, "tasks": {...},
            },
            "tasks": {
                "present": bool,        # найден ли чек-лист задач T-*
                "total": int, "done": int, "open": int, "open_ids": [str],
                "percent": float|None,  # доля отмеченных задач; None — чек-листа нет
                "items": [{"id": "T-8001", "done": bool, "title": str}],
                "duplicates": [str],    # id, встретившиеся в строках задач повторно
            },
            "caps": ["CAP-52", ...],    # ссылки CAP в спеке: запланированное покрытие
            "acceptance": {             # подтверждение приёмки из отчёта TASKS-NNN
                "confirmed": bool,      # False → «не подтверждено картой»
                "source": "docs/reviews/TASKS-008.md"|None,
                "section": "Приёмка (T-8309)"|None,
                "date": "2026-11-21"|None,
                "note": str,
            },
            "exceptions": ["T-7304"],   # открытые задачи принятого среза
        },
    ]
    capabilities: [
        {
            "id": "CAP-105", "title": str,
            "proposal": "позже", "proposal_raw": str,   # колонка «Предложение»
            "decision": "MVP", "decision_raw": str,     # колонка «Решение» — решает владелец
            "covered_by": ["006"],                      # срезы, запланировавшие покрытие
            "state": str,          # «MVP: покрыта срезами» | «MVP: не покрыта срезами»
                                   # | «позже» | «позже: включена в срез» | «не нужно»
                                   # | «нет решения»
        },
    ]
    history: {
        "available": bool, "limit": int,
        "commits": [               # новые сверху, только коммиты, тронувшие источники карты
            {"sha": str, "short": str, "date": str, "message": str,
             "tasks": {"009": {
                 "checked":   ["T-9201"],   # появившиеся отметки ([ ] → [x])
                 "unchecked": ["T-9302"],   # снятые отметки ([x] → [ ])
                 "added":     ["T-9203"],   # добавленные строки задач
                 "removed":   ["T-9202"],   # исчезнувшие строки задач
             }}},
        ],
        "worktree": {              # отдельный слой: незакоммиченные изменения
            "dirty": bool, "files": [str],
            "tasks": {"009": {"checked": [...], "unchecked": [...], "added": [...], "removed": [...]}},
        },
    }
    revision: {"available": bool, "sha": str|None, "short": str|None,
               "date": str|None, "message": str|None, "dirty": bool}
    warnings: [{"code": str, "text": str, "slice": str}]   # slice — необязательно

Правила чтения (план, «Модель данных»):
    * строка задачи — «- [ ]/- [x] T-NNNN» в начале строки; вложенные чек-листы,
      нумерованные списки и примеры кода задачами не считаются;
    * приёмка — только явная запись в отчёте («владелец принял срез NNN» /
      «Срез NNN … принят владельцем»); серверные прогоны приёмкой не считаются;
    * решение по возможности — колонка «Решение», а не «Предложение»;
    * ссылка CAP в спеке — запланированное покрытие, не приёмка.

Запуск:
    python3 tools/project_map.py
"""

from __future__ import annotations

import re
import os
import stat
import subprocess
from pathlib import Path

HISTORY_LIMIT = 50
_GIT_TIMEOUT = 60  # секунды; только чтение, без fetch

# Источники карты в терминах pathspec git (чтение).
MAP_PATHS = ("specs", "docs/reference/capabilities.md", "docs/reviews/TASKS-*.md")
_TASKS_PATHSPEC = "specs/*/tasks.md"

_SLICE_DIR_RE = re.compile(r"^(\d{3})-")
_TASKS_PATH_RE = re.compile(r"^specs/(\d{3})-[^/]+/tasks\.md$")
# Строка задачи: только в начале строки — вложенные чек-листы не считаются.
# Номер произвольной длины: в планах фигурируют и короткие примеры (T-123),
# и реальные четырёхзначные (T-9309) с буквенным суффиксом (T-8109a).
TASK_LINE_RE = re.compile(r"^- \[([ xX])\]\s+(T-\d+[a-z]?)(?:\s+(.*))?$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_CAP_TOKEN_RE = re.compile(r"\bCAP-(\d+)\b")
_CAP_ROW_RE = re.compile(r"^\|\s*(CAP-\d+)\s*\|")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")
# Факт приёмки владельцем: «принял срез NNN» либо «Срез NNN … принят владельцем».
# Номер обязателен: упоминание чужого среза приёмкой этого среза не считается.
_ACCEPT_PHRASE_RE = re.compile(
    r"^(?:владелец(?: через форму)?\s+принял[а]?\s+срез\s+(\d+))"
    r"|^(?:срез\s+(\d+)(?:\s+«[^»]+»)?\s+принят\s+владельцем)",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")

_DECISION_VALUES = ("не нужно", "MVP", "позже")
_NOTE_LIMIT = 200


# --------------------------------------------------------------------------
# Точка входа


def build_snapshot(root: Path, history_limit: int = HISTORY_LIMIT) -> dict:
    """Собирает снимок карты по корню рабочей копии (только чтение)."""
    root = Path(root)
    warnings: list[dict] = []
    slices = _collect_slices(root, warnings)
    capabilities = _collect_capabilities(root, warnings)
    _link_coverage(slices, capabilities)
    history = _collect_history(root, history_limit, warnings)
    revision = _collect_revision(root)
    revision["dirty"] = history["worktree"]["dirty"]
    return {
        "slices": slices,
        "capabilities": capabilities,
        "history": history,
        "revision": revision,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# Срезы


def _collect_slices(root: Path, warnings: list) -> list:
    specs_dir = root / "specs"
    fd = _open_beneath(root, "specs", directory=True)
    if fd is None:
        warnings.append(_warning("no-specs-dir", "каталог specs/ не найден — срезов нет"))
        return []
    try:
        names = sorted(os.listdir(fd))
    finally:
        os.close(fd)
    slices = []
    for name in names:
        directory = specs_dir / name
        if not _safe_directory(root, f"specs/{directory.name}"):
            continue
        match = _SLICE_DIR_RE.match(directory.name)
        if not match:
            continue
        slices.append(_read_slice(root, directory, match.group(1), warnings))
    return slices


def _read_slice(root: Path, directory: Path, number: str, warnings: list) -> dict:
    rel_dir = directory.relative_to(root).as_posix()
    docs = {}
    texts = {}
    for key, filename in (("spec", "spec.md"), ("plan", "plan.md"), ("tasks", "tasks.md")):
        path = directory / filename
        text = _safe_read(root, f"{rel_dir}/{filename}")
        entry = {"path": f"{rel_dir}/{filename}", "exists": text is not None, "id": None, "status": None}
        if entry["exists"]:
            texts[key] = text
            meta = _parse_frontmatter(text)
            entry["id"] = meta.get("id")
            entry["status"] = meta.get("статус")
        else:
            warnings.append(_warning(f"no-{key}-file", f"{entry['path']} не найден", slice_=number))
        docs[key] = entry

    tasks = _read_tasks(texts.get("tasks"), docs["tasks"]["exists"])
    if docs["tasks"]["exists"] and not tasks["present"]:
        warnings.append(_warning("no-checklist", f"{docs['tasks']['path']}: чек-лист задач не найден — прогресс не определён", slice_=number))
    if tasks["duplicates"]:
        joined = ", ".join(sorted(tasks["duplicates"]))
        warnings.append(_warning("duplicate-task-id", f"{docs['tasks']['path']}: повторные строки задач {joined}", slice_=number))

    acceptance = _read_acceptance(root, number, warnings)
    exceptions = sorted(item["id"] for item in tasks["items"] if not item["done"]) if acceptance["confirmed"] else []
    if acceptance["confirmed"] and exceptions:
        warnings.append(_warning("accepted-with-open-tasks", f"срез {number} принят, но открыты задачи: {', '.join(exceptions)}", slice_=number))
    if not acceptance["confirmed"] and tasks["present"] and tasks["total"] and tasks["done"] == tasks["total"]:
        warnings.append(_warning("done-without-acceptance", f"срез {number}: 100 % отметок, но приёмка не подтверждена ({acceptance['source'] or 'отчёта нет'})", slice_=number))

    spec_text = texts.get("spec", "")
    return {
        "number": number,
        "dir": directory.name,
        "title": _slice_title(spec_text),
        "docs": docs,
        "tasks": tasks,
        "caps": _cap_tokens(spec_text),
        "acceptance": acceptance,
        "exceptions": exceptions,
    }


def _slice_title(spec_text: str):
    """Название среза — текст заголовка спеки после «# Срез NNN: »."""
    for line in spec_text.splitlines():
        if line.startswith("# "):
            match = re.match(r"^#\s*Срез\s+\d+:\s*(.+?)\s*$", line)
            return match.group(1) if match else line[2:].strip()
    return None


def _read_tasks(text, exists: bool) -> dict:
    tasks = {
        "present": False, "total": 0, "done": 0, "open": 0, "open_ids": [],
        "percent": None, "items": [], "duplicates": [],
    }
    if not exists or text is None:
        return tasks
    items, duplicates = _parse_task_lines(text)
    tasks["items"] = list(items.values())
    tasks["duplicates"] = duplicates
    tasks["total"] = len(items)
    tasks["done"] = sum(1 for item in items.values() if item["done"])
    tasks["open"] = tasks["total"] - tasks["done"]
    tasks["open_ids"] = [item["id"] for item in items.values() if not item["done"]]
    if tasks["total"]:
        tasks["present"] = True
        tasks["percent"] = round(tasks["done"] / tasks["total"] * 100, 2)
    return tasks


def _parse_task_lines(text: str):
    """Разбирает строки задач; вложенные чек-листы и код в блоках не считаются."""
    items: dict[str, dict] = {}
    duplicates: list[str] = []
    for line in _outside_fences(text):
        match = TASK_LINE_RE.match(line)
        if not match:
            continue
        task_id = match.group(2)
        if task_id in items:
            if task_id not in duplicates:
                duplicates.append(task_id)
            continue
        items[task_id] = {
            "id": task_id,
            "done": match.group(1) in ("x", "X"),
            "title": (match.group(3) or "").strip(),
        }
    return items, duplicates


def _parse_frontmatter(text: str) -> dict:
    """Плоский frontmatter «ключ: значение» (как в tools/sdd.py)."""
    meta: dict[str, str] = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return meta
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = re.match(r"^([\wа-яёА-ЯЁ\-]+):\s*(.*)$", line)
        if match:
            meta[match.group(1)] = match.group(2).strip()
    return meta


def _read_acceptance(root: Path, number: str, warnings: list) -> dict:
    """Ищет в docs/reviews/TASKS-NNN.md явную запись о приёмке среза владельцем."""
    rel = f"docs/reviews/TASKS-{number}.md"
    path = root / rel
    acceptance = {"confirmed": False, "source": None, "section": None, "date": None, "note": "не подтверждено картой"}
    text = _safe_read(root, rel)
    if text is None:
        acceptance["note"] = f"отчёт {rel} не найден — не подтверждено картой"
        warnings.append(_warning("no-review-file", f"{rel} не найден — факт приёмки не проверить", slice_=number))
        return acceptance
    section = None
    target = int(number)
    for line in _outside_fences(text):
        if line.startswith("\t") or line.startswith("    ") or "?" in line:
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            section = heading.group(1)
            continue
        cleaned = line.strip().replace("**", "")
        cleaned = re.sub(r"^[-*]\s+", "", cleaned)
        if re.search(r"\b(?:если|когда|пока|возможно|якобы|ли|не)\b", cleaned, re.IGNORECASE):
            continue
        match = _ACCEPT_PHRASE_RE.search(cleaned)
        if not match:
            continue
        found = match.group(1) or match.group(2)
        if found is None or int(found) != target:
            continue  # упоминание чужого среза — не приёмка этого
        note = line.strip().replace("**", "")
        if len(note) > _NOTE_LIMIT:
            note = note[:_NOTE_LIMIT] + "…"
        date = _DATE_RE.search(line)
        acceptance.update({
            "confirmed": True,
            "source": rel,
            "section": section,
            "date": date.group(1) if date else None,
            "note": note,
        })
        return acceptance
    return acceptance


# --------------------------------------------------------------------------
# Карта возможностей


def _collect_capabilities(root: Path, warnings: list) -> list:
    path = root / "docs" / "reference" / "capabilities.md"
    text = _safe_read(root, "docs/reference/capabilities.md")
    if text is None:
        warnings.append(_warning("no-capabilities", "docs/reference/capabilities.md не найден"))
        return []
    rows = []
    for line in text.splitlines():
        if not _CAP_ROW_RE.match(line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        while len(cells) < 5:
            cells.append("")
        cap_id, title, _ref, proposal_raw, decision_raw = cells[:5]
        rows.append({
            "id": cap_id,
            "title": title,
            "proposal": _normalize_decision(proposal_raw),
            "proposal_raw": proposal_raw,
            "decision": _normalize_decision(decision_raw),
            "decision_raw": decision_raw,
            "covered_by": [],
            "state": None,
        })
    if not rows:
        warnings.append(_warning("empty-capabilities", f"{path.relative_to(root).as_posix()}: строк возможностей CAP нет"))
    for row in rows:
        if not row["decision"]:
            warnings.append(_warning("cap-without-decision", f"{row['id']}: решение владельца не заполнено"))
    return rows


def _normalize_decision(raw: str) -> str:
    """«MVP (…)» → «MVP», «позже (…)» → «позже», «не нужно (…)» → «не нужно»."""
    value = (raw or "").strip()
    for known in _DECISION_VALUES:
        if value == known or value.startswith(known + " ") or value.startswith(known + "("):
            return known
    return value


def _cap_tokens(text: str) -> list:
    """Уникальные ссылки CAP из спеки, по возрастанию номера."""
    seen = {}
    for number in _CAP_TOKEN_RE.findall(text):
        seen.setdefault(int(number), f"CAP-{number}")
    return [seen[number] for number in sorted(seen)]


def _link_coverage(slices: list, capabilities: list) -> None:
    """Ссылка CAP в спеке — запланированное покрытие (не приёмка)."""
    by_number = {int(re.search(r"\d+", cap["id"]).group()): cap for cap in capabilities}
    for slice_ in slices:
        numbers = {int(token[4:]) for token in slice_["caps"]}
        for number in numbers:
            cap = by_number.get(number)
            if cap is not None:
                cap["covered_by"].append(slice_["number"])
    for cap in capabilities:
        cap["covered_by"] = sorted(set(cap["covered_by"]))
        cap["state"] = _cap_state(cap["decision"], bool(cap["covered_by"]))


def _cap_state(decision: str, covered: bool) -> str:
    if not decision:
        return "нет решения"
    if decision == "MVP":
        return "MVP: покрыта срезами" if covered else "MVP: не покрыта срезами"
    if decision == "позже":
        return "позже: включена в срез" if covered else "позже"
    if decision == "не нужно":
        return "не нужно"
    return decision


# --------------------------------------------------------------------------
# Git: только чтение (log / show / status), без fetch


def _git(root: Path, *args: str):
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, check=False, timeout=_GIT_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        return subprocess.CompletedProcess(args, returncode=128, stdout="", stderr="git недоступен")


def _git_file(root: Path, path: str, revision: str = "HEAD"):
    """Читает только обычный Git-blob разрешённого чек-листа."""
    if not _TASKS_PATH_RE.fullmatch(path) or not re.fullmatch(r"(?:HEAD|[0-9a-f]{40})(?:\^)?", revision):
        return None
    tree = _git(root, "ls-tree", "-z", revision, "--", path)
    if tree.returncode != 0 or not tree.stdout:
        return None
    metadata, _, found = tree.stdout.rstrip("\0").partition("\t")
    if found != path or not re.fullmatch(r"100(?:644|755) blob [0-9a-f]{40}", metadata):
        return None
    result = _git(root, "show", f"{revision}:{path}")
    return result.stdout if result.returncode == 0 else None


def _collect_history(root: Path, limit: int, warnings: list) -> dict:
    history = {
        "available": False,
        "limit": limit,
        "commits": [],
        "worktree": {"dirty": False, "files": [], "tasks": {}},
    }
    log = _git(root, "log", f"-n{limit}", "--format=%H%x1f%h%x1f%cI%x1f%s", "--", *MAP_PATHS)
    if log.returncode != 0 or not log.stdout.strip():
        reason = (log.stderr or "").strip().splitlines()
        warnings.append(_warning("no-git", "git-история недоступна (только чтение, без fetch): " + (reason[0] if reason else "нет данных")))
        return history
    history["available"] = True
    for line in log.stdout.splitlines():
        if not line:
            continue
        sha, short, date, message = line.split("\x1f", 3)
        history["commits"].append({
            "sha": sha,
            "short": short,
            "date": date,
            "message": message,
            "tasks": _commit_tasks(root, sha),
        })
    history["worktree"] = _collect_worktree(root, warnings)
    return history


def _commit_tasks(root: Path, sha: str) -> dict:
    """Сравнивает полные чек-листы с первым родителем коммита."""
    diff = _git(root, "diff-tree", "--root", "--first-parent", "--no-commit-id", "--name-only", "-r", "-z", "--no-renames", sha, "--", _TASKS_PATHSPEC)
    if diff.returncode != 0:
        return {}
    tasks = {}
    for path in sorted(diff.stdout.split("\0")):
        match = _TASKS_PATH_RE.match(path)
        if not match:
            continue
        tasks[match.group(1)] = _task_delta(_git_file(root, path, sha + "^"), _git_file(root, path, sha))
    return tasks


def _collect_worktree(root: Path, warnings: list) -> dict:
    """Незакоммиченные изменения источников карты — отдельный слой."""
    layer = {"dirty": False, "files": [], "tasks": {}}
    status = _git(root, "status", "--porcelain", "-uall", "--", *MAP_PATHS)
    if status.returncode != 0:
        return layer
    for line in status.stdout.splitlines():
        if not line:
            continue
        code = line[:2]
        raw_path = line[3:].strip().strip('"')
        if " -> " in raw_path:  # переименование: старое имя теряется, новое появляется
            old, new = (part.strip() for part in raw_path.split(" -> ", 1))
        else:
            old = new = raw_path
        for path in {old, new}:
            layer["files"].append(path)
            match = _TASKS_PATH_RE.match(path)
            if match:
                layer["tasks"][match.group(1)] = _worktree_tasks(root, code, path)
        if code == "??":
            warnings.append(_warning("untracked-map-file", f"источник карты не в git: {raw_path}"))
    layer["files"] = sorted(set(layer["files"]))
    layer["dirty"] = bool(layer["files"])
    return layer


def _worktree_tasks(root: Path, code: str, path: str) -> dict:
    return _task_delta(_git_file(root, path), _safe_read(root, path))


def _task_delta(old_text, new_text) -> dict:
    entry = {"checked": [], "unchecked": [], "added": [], "removed": []}
    old, _ = _parse_task_lines(old_text or "")
    new, _ = _parse_task_lines(new_text or "")
    for task_id in sorted(set(old) | set(new)):
        if task_id in old and task_id in new:
            if new[task_id]["done"] and not old[task_id]["done"]:
                entry["checked"].append(task_id)
            elif old[task_id]["done"] and not new[task_id]["done"]:
                entry["unchecked"].append(task_id)
        elif task_id in new:
            entry["added"].append(task_id)
        else:
            entry["removed"].append(task_id)
    return entry


def _collect_revision(root: Path) -> dict:
    """Короткий SHA и дата последнего коммита, тронувшего источники карты."""
    revision = {"available": False, "sha": None, "short": None, "date": None, "message": None, "dirty": False}
    log = _git(root, "log", "-1", "--format=%H%x1f%h%x1f%cI%x1f%s", "--", *MAP_PATHS)
    if log.returncode != 0 or not log.stdout.strip():
        return revision
    sha, short, date, message = log.stdout.strip().split("\x1f", 3)
    revision.update({"available": True, "sha": sha, "short": short, "date": date, "message": message})
    return revision


# --------------------------------------------------------------------------
# Прочее


def _open_beneath(root: Path, relative: str, *, directory: bool = False):
    """Открывает компоненты по dirfd, не проходя по символическим ссылкам."""
    parts = Path(relative).parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        return None
    fd = None
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        for index, part in enumerate(parts):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if index < len(parts) - 1 or directory:
                flags |= os.O_DIRECTORY
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        if not directory and not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            return None
        return fd
    except OSError:
        if fd is not None:
            os.close(fd)
        return None


def _safe_directory(root: Path, relative: str) -> bool:
    fd = _open_beneath(root, relative, directory=True)
    if fd is None:
        return False
    os.close(fd)
    return True


def _safe_read(root: Path, relative: str):
    fd = _open_beneath(root, relative)
    if fd is None:
        return None
    with os.fdopen(fd, encoding="utf-8", errors="replace") as source:
        return source.read()


def _outside_fences(text: str):
    fence = None
    for line in text.splitlines():
        match = _FENCE_RE.match(line)
        if fence:
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence) and not match.group(2).strip():
                fence = None
            continue
        if match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
            fence = match.group(1)
            continue
        yield line


def _warning(code: str, text: str, slice_: str | None = None) -> dict:
    entry = {"code": code, "text": text}
    if slice_ is not None:
        entry["slice"] = slice_
    return entry


def make_server(root: Path, port: int = 8765):
    """Создаёт сервер только на IPv4 loopback, с двумя точными маршрутами."""
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def respond(self, status, body, content_type="text/plain; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            hosts = self.headers.get_all("Host", [])
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if len(hosts) != 1 or hosts[0].lower() not in allowed:
                self.respond(403, b"Forbidden")
                return
            # BaseHTTPRequestHandler normalizes leading //, so use the original target.
            target = self.requestline.split()[1]
            if target == "/":
                try:
                    body = Path(__file__).with_name("project_map.html").read_bytes()
                except OSError:
                    self.respond(500, b"Page unavailable")
                    return
                self.respond(200, body, "text/html; charset=utf-8")
            elif target == "/api/map":
                try:
                    body = json.dumps(build_snapshot(root), ensure_ascii=False).encode("utf-8")
                except Exception:
                    self.respond(500, b"Snapshot unavailable")
                    return
                self.respond(200, body, "application/json; charset=utf-8")
            else:
                self.respond(404, b"Not found")

        def do_POST(self):
            self.respond(405, b"Method not allowed")

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    server = make_server(Path(__file__).resolve().parent.parent)
    print("Карта: http://127.0.0.1:8765/ (остановка: Ctrl+C)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
