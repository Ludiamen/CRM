"""T-8302 (повтор): отбор nodeid после правок.

Входят: срез 008 — все круги; e10_page — Chromium и Яндекс (дефект фильтра/страниц);
24 узла изолированного повтора; test_s01_first_admin — первым в каждом круге (свежий стенд).

Вход — `pytest tests/e2e --collect-only -q` (stdin), выход — nodeid по строке.
"""
import re
import sys

ALL_ROUNDS = {"chromium", "firefox", "edge", "yandex"}
LEGACY_ROUNDS = {"chromium", "yandex"}
retry_ids = {line.strip() for line in open(sys.argv[1], encoding="utf-8") if line.strip()}
kept = {"chromium": 0, "firefox": 0, "edge": 0, "yandex": 0}

for line in sys.stdin:
    node = line.strip()
    m = re.search(r"\[(chromium|firefox|edge|yandex)[^\]]*\]$", node)
    if "::" not in node or not m:
        continue
    rnd = m.group(1)
    take = (
        node.startswith("tests/e2e/test_s01_first_admin.py")
        or (rnd in ALL_ROUNDS and node.startswith("tests/e2e/test_m"))
        or (rnd in LEGACY_ROUNDS and node.startswith("tests/e2e/test_e10_page.py"))
        or node in retry_ids
    )
    if take:
        print(node)
        kept[rnd] += 1

print(kept, file=sys.stderr)