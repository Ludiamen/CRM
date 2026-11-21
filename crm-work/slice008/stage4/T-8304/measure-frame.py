"""Одиночный замер кадра `/ws/messenger/` на свободном стенде (NFR-701, T-8304).

Два сотрудника: читатель A держит соединение беседы общего чата, публикатор B отправляет сообщение
обычным запросом. Задержка — от ответа публикатора до кадра с `data-message-id`. Пять повторов.
Пишет measure-frame.txt рядом.
"""
import csv
import json
import re
import ssl
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import websocket

BASE = "https://127.0.0.1:8031"
D = Path(__file__).resolve().parent
ROWS = [row for row in csv.reader(D.joinpath("creds.csv").open(encoding="utf-8")) if row]

from django_otp.oath import TOTP  # noqa: E402  (venv проекта)


def code(key: str) -> str:
    return str(TOTP(bytes.fromhex(key), step=30, digits=6).token()).zfill(6)


def sign_in(row):
    email, password, key = row
    s = requests.Session()
    s.verify = False
    s.get(f"{BASE}/login/", timeout=60)
    s.post(f"{BASE}/login/", data={"email": email, "password": password,
                                   "csrfmiddlewaretoken": s.cookies["csrftoken"]},
           headers={"Referer": f"{BASE}/login/"}, timeout=60)
    s.get(f"{BASE}/login/code/", timeout=60)
    s.post(f"{BASE}/login/code/", data={"code": code(key), "csrfmiddlewaretoken": s.cookies["csrftoken"]},
           headers={"Referer": f"{BASE}/login/code/"}, timeout=60)
    return s


requests.packages.urllib3.disable_warnings()
reader = sign_in(ROWS[0])
writer = sign_in(ROWS[1])

page = reader.get(f"{BASE}/messenger/", timeout=60).text
chat_ids = sorted({int(value) for value in re.findall(r'data-chat-id="(\d+)"', page)})
general = None
for chat_id in chat_ids[:10]:
    body = reader.get(f"{BASE}/messenger/chats/{chat_id}/", timeout=60).text
    if 'data-chat-kind="general"' in body:
        general = chat_id
        break
assert general, "общий чат не найден"
print(f"общий чат: {general}, чатов в списке: {len(chat_ids)}")

cookies = "; ".join(f"{name}={value}" for name, value in reader.cookies.items())
socket = websocket.create_connection(f"wss://127.0.0.1:8031/ws/messenger/?chat={general}",
                                     header=[f"Cookie: {cookies}"], origin=BASE,
                                     sslopt={"cert_reqs": ssl.CERT_NONE}, timeout=30)
socket.settimeout(30)
socket.send(json.dumps({"sync": {"chat": general, "at": datetime.now(timezone.utc).isoformat()}}))

latencies = []
for i in range(5):
    writer.get(f"{BASE}/messenger/chats/{general}/", timeout=60)
    started = time.monotonic()
    r = writer.post(f"{BASE}/messenger/chats/{general}/messages/",
                    data={"text": f"Замер кадра {i}", "csrfmiddlewaretoken": writer.cookies["csrftoken"]},
                    headers={"Referer": f"{BASE}/messenger/chats/{general}/", "HX-Request": "true"}, timeout=60)
    assert r.status_code in (200, 302), r.status_code
    message_id = re.search(r'data-message-id="(\d+)"', r.text)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        frame = socket.recv()
        received = time.monotonic()
        ids = {int(v) for v in re.findall(r'data-message-id="(\d+)"', frame)}
        ids.update(int(v) for v in re.findall(r'id="m(\d+)"', frame))
        if message_id and int(message_id.group(1)) in ids:
            latencies.append((received - started) * 1000)
            break
    else:
        raise SystemExit("кадр не пришёл за 30 с")

socket.close()
line = (f"кадр беседы: {len(latencies)} из 5; медиана {statistics.median(latencies):.0f} мс, "
        f"мин {min(latencies):.0f}, макс {max(latencies):.0f}")
print(line)
D.joinpath("measure-frame.txt").write_text(line + "\n", encoding="utf-8")