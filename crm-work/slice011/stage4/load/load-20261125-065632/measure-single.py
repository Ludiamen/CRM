"""T-11303, контроль на свободной машине: одна учётка, те же страницы, что в L1."""
import csv
import statistics
import time
from pathlib import Path

import requests
import urllib3
from django_otp.oath import TOTP

BASE = "https://127.0.0.1:8031"
RUN = Path(__file__).resolve().parent
rows = [row for row in csv.reader(open(RUN / "creds.csv", encoding="utf-8")) if row]
email, password, key = rows[0]
urllib3.disable_warnings()

session = requests.Session()
session.verify = False
session.get(f"{BASE}/login/", timeout=60)
session.post(f"{BASE}/login/", data={"email": email, "password": password,
                                     "csrfmiddlewaretoken": session.cookies["csrftoken"]},
             headers={"Referer": f"{BASE}/login/"}, timeout=60)
session.get(f"{BASE}/login/code/", timeout=60)
session.post(f"{BASE}/login/code/", data={"code": str(TOTP(bytes.fromhex(key), step=30, digits=6).token()).zfill(6),
                                          "csrfmiddlewaretoken": session.cookies["csrftoken"]},
             headers={"Referer": f"{BASE}/login/code/"}, timeout=60)

paths = ("/tickets/?preset=all", "/tickets/?due=overdue", "/tickets/count/?due=overdue",
         "/servicedesk/reports/?period=week")
for path in paths:
    times = []
    status = None
    for _ in range(5):
        started = time.monotonic()
        response = session.get(f"{BASE}{path}", timeout=120)
        status = response.status_code
        times.append((time.monotonic() - started) * 1000)
    times.sort()
    print(f"{path}: {status} медиана {statistics.median(times):.0f} мс, p95 {times[-1]:.0f} мс")
