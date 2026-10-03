"""Нагрузочный прогон NFR-002 (T-117, запускается на Этапе 4, T-304): 100 пользователей на
списке сотрудников, журнале и истории входов; p95 каждой из четырёх страниц не больше 500 мс.

Модель нагрузки (решение владельца 2026-10-03, PLAN-001 версия 4): 100 вошедших сотрудников,
вход по одному в секунду, пауза между действиями 5–15 с, замер после того, как вошли все
(`--reset-stats`). Запуск против стенда (https://127.0.0.1:8031):
    LOAD_CREDENTIALS=creds.csv locust -f tests/load/locustfile.py --headless -u 100 -r 1 -t 6m \
        --reset-stats --host https://127.0.0.1:8031

Замер ёмкости (не критерий): `LOAD_WAIT=1,3` и `-r 10` — около 50 запросов в секунду и 100 входов
за 10 с. `creds.csv` — строки `почта,пароль,ключ_TOTP_hex` администраторов стенда (файл вне git,
секреты — только *** в документах), готовит их tests/load/prepare_users.py. Код TOTP считается из
ключа так же, как у приложения-генератора. Пауза — LOAD_WAIT="мин,макс" в секундах.
"""
import csv
import itertools
import os
import sys
import threading

from locust import HttpUser, between, events, task

P95_LIMIT_MS = 500
_lock = threading.Lock()
_credentials = None
_cycle = None


def _next_credentials():
    global _credentials, _cycle
    with _lock:
        if _credentials is None:
            with open(os.environ["LOAD_CREDENTIALS"], newline="", encoding="utf-8") as handle:
                _credentials = [row for row in csv.reader(handle) if row]
            _cycle = itertools.cycle(_credentials)
        return next(_cycle)


def _totp(key_hex: str) -> str:
    from django_otp.oath import TOTP

    return str(TOTP(bytes.fromhex(key_hex), step=30, digits=6).token()).zfill(6)


class StaffAuditHistoryUser(HttpUser):
    """Вошедший администратор, который листает список сотрудников, журнал и историю входов."""

    wait_time = between(*(float(x) for x in os.environ.get("LOAD_WAIT", "5,15").split(",")))

    def on_start(self):
        self.client.verify = False
        self.email, self.password, self.key = _next_credentials()
        self._post_form("/login/", {"email": self.email, "password": self.password})
        self._post_form("/login/code/", {"code": _totp(self.key)})

    def _post_form(self, path, data):
        self.client.get(path, name=f"GET {path}")
        token = self.client.cookies.get("csrftoken", "")
        with self.client.post(path, data={**data, "csrfmiddlewaretoken": token}, headers={"Referer": self.host + path},
                              name=f"POST {path}", allow_redirects=True, catch_response=True) as response:
            if response.status_code >= 400:
                response.failure(f"{path}: {response.status_code}")

    @task(3)
    def staff_list(self):
        self.client.get("/staff/", name="/staff/")

    @task(3)
    def staff_filtered_fragment(self):
        self.client.get("/staff/?state=active&sort=full_name", headers={"HX-Request": "true"}, name="/staff/ (HTMX)")

    @task(2)
    def audit(self):
        self.client.get("/audit/?preset=access", name="/audit/")

    @task(2)
    def history(self):
        self.client.get("/me/security/history/", name="/me/security/history/")


PAGES = ("/staff/", "/staff/ (HTMX)", "/audit/", "/me/security/history/")


@events.quitting.add_listener
def _check_p95(environment, **_kwargs):
    """NFR-002: p95 каждой страницы среза (вход в требование не входит) и ни одной ошибки."""
    stats = environment.stats
    over = {}
    for name in PAGES:
        entry = stats.entries.get((name, "GET"))
        p95 = entry.get_response_time_percentile(0.95) if entry and entry.num_requests else None
        if p95 is None or p95 > P95_LIMIT_MS:
            over[name] = p95
    if stats.total.num_failures or over:
        print(f"NFR-002 не выполнено: p95 выше {P95_LIMIT_MS} мс или нет замера {over}, "
              f"ошибок {stats.total.num_failures}", file=sys.stderr)
        environment.process_exit_code = 1
