"""T-8302: отбор nodeid приёмки среза 008 по правилу владельца 2026-10-21.

Срез 008 (tests/e2e/test_m01…m13) — все четыре круга (chromium, firefox, edge, yandex);
прежние срезы 001–007 — только chromium и yandex. Первым в каждом круге идёт
test_s01_first_admin (свежий стенд после E2E_RESET_CMD).

Вход — вывод `pytest tests/e2e --collect-only -q` (stdin), выход — nodeid по строке.
"""
import re
import sys

NEW = re.compile(r"^tests/e2e/test_m\d\d_")
FIRST = "tests/e2e/test_s01_first_admin.py"
ALL_ROUNDS = {"chromium", "yandex"}
kept = {"chromium": 0, "firefox": 0, "edge": 0, "yandex": 0}

for line in sys.stdin:
    node = line.strip()
    m = re.search(r"\[(chromium|firefox|edge|yandex)[^\]]*\]$", node)
    if "::" not in node or not m:
        continue
    rnd = m.group(1)
    if rnd in ALL_ROUNDS or NEW.match(node) or node.startswith(FIRST):
        print(node)
        kept[rnd] += 1

print(kept, file=sys.stderr)