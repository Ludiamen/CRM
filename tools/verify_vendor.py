#!/usr/bin/env python3
"""Сверка сторонней статики backend/static/vendor/ с реестром npm (T-003).

Что проверяется:
  1. sha256 каждого файла из таблиц VERSIONS.md равен sha256 файла в пакете
     из реестра npm и хешу файла на диске;
  2. тексты лицензий (LICENSE-bootstrap, LICENSE-htmx, LICENSE-htmx-ext-ws) равны лицензиям пакета,
     LICENSE-alpine — лицензии репозитория alpinejs/alpine на теге версии;
  3. в Alpine нет `new Function` (это CSP-сборка), в Bootstrap и HTMX нет
     @import, url(http…) и обращений к внешним адресам из кода;
  4. сообщает (предупреждением), если в своей ветке вышла версия новее.

Без сети (или с --offline) шаги 1, 2 и 4 пропускаются с пометкой, а шаг 3 и
сверка хешей на диске с VERSIONS.md выполняются всегда. Расхождение даёт код 1.
Использует только стандартную библиотеку.
"""

import hashlib
import io
import json
import re
import sys
import tarfile
import urllib.request
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
VENDOR = КОРЕНЬ / "backend" / "static" / "vendor"
РЕЕСТР = "https://registry.npmjs.org"

# заголовок раздела VERSIONS.md -> (пакет, файл лицензии, ветка для поиска новее)
ПАКЕТЫ = {
    "Bootstrap": ("bootstrap", "LICENSE-bootstrap", r"^5\.3\.\d+$"),
    "HTMX": ("htmx.org", "LICENSE-htmx", r"^2\.\d+\.\d+$"),
    "Alpine.js CSP": ("@alpinejs/csp", "LICENSE-alpine", r"^3\.\d+\.\d+$"),
    "htmx-ext-ws": ("htmx-ext-ws", "LICENSE-htmx-ext-ws", r"^2\.\d+\.\d+$"),
}


def sha256(данные: bytes) -> str:
    return hashlib.sha256(данные).hexdigest()


def скачать(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def разобрать_versions() -> list:
    """[(раздел, версия, [(файл, файл_в_пакете, sha256)])]."""
    текст = (VENDOR / "VERSIONS.md").read_text(encoding="utf-8")
    разделы = []
    for блок in re.split(r"^## ", текст, flags=re.M)[1:]:
        заголовок = блок.split("\n", 1)[0]
        м = re.match(r"(Bootstrap|HTMX|Alpine\.js CSP|htmx-ext-ws) (\d+\.\d+\.\d+)", заголовок)
        if not м:
            continue
        файлы = re.findall(r"^\| (\S+) \| (package/\S+) \| ([0-9a-f]{64}) \|", блок, flags=re.M)
        разделы.append((м.group(1), м.group(2), файлы))
    return разделы


def лишнее_в_vendor(каталог: Path, перечисленные: set) -> list:
    """Всё в каталоге, кроме файлов из VERSIONS.md, LICENSE-* и самого VERSIONS.md.

    Каталог исключён из проверки по конституции (`не_проверять`), поэтому
    в нём не должно быть ни нашего кода, ни символических ссылок, ни
    подкаталогов: иначе туда можно спрятать файл от ворот.
    """
    лишнее = []
    for путь in sorted(каталог.iterdir()):
        имя = путь.name
        if путь.is_symlink():
            лишнее.append(f"{имя}: символическая ссылка")
        elif путь.is_dir():
            лишнее.append(f"{имя}: подкаталог")
        elif имя == "VERSIONS.md" or имя.startswith("LICENSE-") or имя in перечисленные:
            continue
        else:
            лишнее.append(f"{имя}: нет в VERSIONS.md")
    return лишнее


def версия_ключ(v: str):
    return tuple(int(x) for x in v.split("."))


def main(аргументы) -> int:
    офлайн = "--offline" in аргументы
    ошибки, замечания = [], []
    разделы = разобрать_versions()
    if len(разделы) != len(ПАКЕТЫ):
        ошибки.append(f"в VERSIONS.md разделов {len(разделы)}, ожидалось {len(ПАКЕТЫ)}")

    перечисленные = {файл for _, _, файлы in разделы for файл, _, _ in файлы}
    for л in лишнее_в_vendor(VENDOR, перечисленные):
        ошибки.append(f"vendor: {л}")

    for имя, версия, файлы in разделы:
        пакет, лицензия, ветка = ПАКЕТЫ[имя]
        короткое = пакет.split("/")[-1]
        if not файлы:
            ошибки.append(f"{имя}: в VERSIONS.md нет таблицы файлов")
        # хеши на диске
        for файл, _, хеш in файлы:
            путь = VENDOR / файл
            if not путь.is_file():
                ошибки.append(f"{файл}: файла нет на диске")
            elif sha256(путь.read_bytes()) != хеш:
                ошибки.append(f"{файл}: sha256 на диске не равен записанному в VERSIONS.md")
        # содержимое
        for файл, _, _ in файлы:
            путь = VENDOR / файл
            if not путь.is_file():
                continue
            текст = путь.read_text(encoding="utf-8", errors="ignore")
            if имя == "Alpine.js CSP" and "new Function" in текст:
                ошибки.append(f"{файл}: найден `new Function` — это не CSP-сборка")
            if имя != "Alpine.js CSP":
                if re.search(r"@import|url\(\s*[\"']?https?:", текст):
                    ошибки.append(f"{файл}: внешний @import или url(http…)")
                if re.search(r"(fetch|XMLHttpRequest|import)\s*\(?\s*[\"']https?://", текст):
                    ошибки.append(f"{файл}: обращение к внешнему адресу из кода")
        # сеть
        if офлайн:
            замечания.append(f"{имя}: сверка с реестром пропущена (--offline)")
            continue
        try:
            tgz = скачать(f"{РЕЕСТР}/{пакет}/-/{короткое}-{версия}.tgz")
            мета = json.loads(скачать(f"{РЕЕСТР}/{пакет}"))
        except OSError as e:
            замечания.append(f"{имя}: реестр недоступен ({e}), сверка с реестром пропущена")
            continue
        with tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz") as t:
            for файл, в_пакете, хеш in файлы:
                f = t.extractfile(в_пакете)
                if f is None:
                    ошибки.append(f"{файл}: в пакете нет {в_пакете}")
                elif sha256(f.read()) != хеш:
                    ошибки.append(f"{файл}: sha256 не равен sha256 {в_пакете} из пакета {пакет}@{версия}")
            путь_лицензии = VENDOR / лицензия
            if имя == "Alpine.js CSP":
                эталон = скачать(
                    f"https://raw.githubusercontent.com/alpinejs/alpine/v{версия}/LICENSE.md"
                )
            else:
                f = t.extractfile("package/LICENSE")
                эталон = f.read() if f else b""
            if not путь_лицензии.is_file() or путь_лицензии.read_bytes().strip() != эталон.strip():
                ошибки.append(f"{лицензия}: текст не совпадает с лицензией {пакет}@{версия}")
        # новее в своей ветке?
        новее = [v for v in мета.get("versions", {}) if re.match(ветка, v) and версия_ключ(v) > версия_ключ(версия)]
        if новее:
            замечания.append(f"{имя}: в своей ветке есть версия новее — {max(новее, key=версия_ключ)} (в проекте {версия})")

    for з in замечания:
        print("замечание:", з)
    for о in ошибки:
        print("ОШИБКА:", о)
    print(f"vendor: разделов {len(разделы)}, ошибок {len(ошибки)}, замечаний {len(замечания)}")
    return 1 if ошибки else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
