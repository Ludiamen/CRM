"""Одиночные запросы на свободном стенде после прогона нагрузки (T-8304).

Вход одним пользователем из creds.csv, по 5 повторов каждого адреса; медиана и максимум в мс.
Пишет measure-idle.txt рядом.
"""
import csv
import re
import statistics
import time
from pathlib import Path

import requests

BASE = "https://127.0.0.1:8031"
D = Path(__file__).resolve().parent
ROW = next(csv.reader(D.joinpath("creds.csv").open(encoding="utf-8")))
EMAIL, PASSWORD, KEY = ROW

from django_otp.oath import TOTP  # noqa: E402  (venv проекта)


def code() -> str:
    return str(TOTP(bytes.fromhex(KEY), step=30, digits=6).token()).zfill(6)


s = requests.Session()
s.verify = False
requests.packages.urllib3.disable_warnings()

s.get(f"{BASE}/login/", timeout=60)
r = s.post(f"{BASE}/login/", data={"email": EMAIL, "password": PASSWORD,
                                   "csrfmiddlewaretoken": s.cookies["csrftoken"]},
           headers={"Referer": f"{BASE}/login/"}, timeout=60)
assert r.status_code in (200, 302), r.status_code
s.get(f"{BASE}/login/code/", timeout=60)
r = s.post(f"{BASE}/login/code/", data={"code": code(), "csrfmiddlewaretoken": s.cookies["csrftoken"]},
           headers={"Referer": f"{BASE}/login/code/"}, timeout=60)
assert r.status_code in (200, 302), r.status_code

page = s.get(f"{BASE}/messenger/", timeout=60).text
chat = re.search(r'data-chat-id="(\d+)"', page).group(1)

targets = [
    ("GET /messenger/", f"{BASE}/messenger/"),
    ("GET /messenger/list/", f"{BASE}/messenger/list/"),
    ("GET /messenger/list/?q", f"{BASE}/messenger/list/?q=%D1%81%D0%BE%D0%BE%D0%B1%D1%89%D0%B5%D0%BD%D0%B8%D0%B5"),
    ("GET /messenger/chats/<id>/", f"{BASE}/messenger/chats/{chat}/"),
    ("GET chat search", f"{BASE}/messenger/chats/{chat}/search/?q=%D1%81%D0%BE%D0%BE%D0%B1%D1%89%D0%B5%D0%BD%D0%B8%D0%B5"),
    ("GET /messenger/mentions/?chat", f"{BASE}/messenger/mentions/?chat={chat}&q=%D0%9D%D0%B0"),
    ("GET /search/?q", f"{BASE}/search/?q=%D1%81%D0%BE%D0%BE%D0%B1%D1%89%D0%B5%D0%BD%D0%B8%D0%B5"),
    ("GET /messenger/notifications/", f"{BASE}/messenger/notifications/"),
]

lines = []
for name, url in targets:
    times = []
    codes = []
    for _ in range(5):
        started = time.monotonic()
        r = s.get(url, timeout=120)
        times.append((time.monotonic() - started) * 1000)
        codes.append(r.status_code)
    line = (f"{name:34} {codes} медиана {statistics.median(times):9.0f} мс, "
            f"мин {min(times):8.0f}, макс {max(times):8.0f}")
    print(line)
    lines.append(line)

sends = []
for i in range(3):
    s.get(f"{BASE}/messenger/chats/{chat}/", timeout=60)
    started = time.monotonic()
    r = s.post(f"{BASE}/messenger/chats/{chat}/messages/",
               data={"text": f"Одиночный замер {i}", "csrfmiddlewaretoken": s.cookies["csrftoken"]},
               headers={"Referer": f"{BASE}/messenger/chats/{chat}/", "HX-Request": "true"}, timeout=120)
    sends.append((time.monotonic() - started) * 1000)
    assert r.status_code in (200, 302), r.status_code
line = (f"{'POST message':34} [200/302] медиана {statistics.median(sends):9.0f} мс, "
        f"мин {min(sends):8.0f}, макс {max(sends):8.0f}")
print(line)
lines.append(line)

D.joinpath("measure-idle.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")