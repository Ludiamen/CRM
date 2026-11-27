"""Нагрузочный прогон NFR-002 (T-117, запускается на Этапе 4, T-304): 100 пользователей на
списке сотрудников, журнале и истории входов; p95 каждой из четырёх страниц не больше 500 мс.

Модель нагрузки (решение владельца 2026-10-03, PLAN-001 версия 4): 100 вошедших сотрудников,
вход по одному в секунду, пауза между действиями 5–15 с, замер после того, как вошли все
(`--reset-stats`). Запуск против стенда (https://127.0.0.1:8031):
    LOAD_CREDENTIALS=creds.csv locust -f tests/load/locustfile.py --headless -u 100 -r 1 -t 6m \
        --reset-stats --host https://127.0.0.1:8031 StaffAuditHistoryUser
Имя класса в конце команды обязательно: без него locust запускает все классы файла и делит `-u` между ними.
Прогон среза 002 — тот же файл с классом `OrgUser` (команда — в его докстринге).

Замер ёмкости (не критерий): `LOAD_WAIT=1,3` и `-r 10` — около 50 запросов в секунду и 100 входов
за 10 с. `creds.csv` — строки `почта,пароль,ключ_TOTP_hex` администраторов стенда (файл вне git,
секреты — только *** в документах), готовит их tests/load/prepare_users.py. Код TOTP считается из
ключа так же, как у приложения-генератора. Пауза — LOAD_WAIT="мин,макс" в секундах.
"""
import csv
import html
import itertools
import json
import os
import random
import re
import ssl
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import gevent
from locust import HttpUser, between, events, tag, task

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
    if StaffAuditHistoryUser not in environment.user_classes:
        return
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


class OrgUser(HttpUser):
    """Срез 002 (T-2120, NFR-102): вошедший сотрудник листает структуру, карточку узла, список с поиском,
    карточку сотрудника, календарь и сетку поля даты. Модель нагрузки та же (PLAN-001 версия 4); данные —
    `prepare_users.py`, затем `prepare_org.py` (200 узлов, членства 100 сотрудников) и журнал в 300 тыс.
    событий (`fill_audit.py`). Запуск только этого класса (Этап 4, T-2242):
        LOAD_CREDENTIALS=creds.csv locust -f tests/load/locustfile.py --headless -u 100 -r 1 -t 6m \
            --reset-stats --host https://127.0.0.1:8031 OrgUser
    (имя класса — в конце команды: без него locust запускает все классы файла и делит `-u` между ними)
    Поиск в списке — строка LOAD_ORG_QUERY (по умолчанию «Нагрузка», как ФИО записей prepare_users.py).
    Адреса узлов и сотрудников берутся со страниц при входе, поэтому скрипт не знает номеров заранее."""

    wait_time = between(*(float(x) for x in os.environ.get("LOAD_WAIT", "5,15").split(",")))

    def on_start(self):
        self.client.verify = False
        self.email, self.password, self.key = _next_credentials()
        StaffAuditHistoryUser._post_form(self, "/login/", {"email": self.email, "password": self.password})
        StaffAuditHistoryUser._post_form(self, "/login/code/", {"code": _totp(self.key)})
        self.query = os.environ.get("LOAD_ORG_QUERY", "Нагрузка")
        tree = self.client.get("/structure/", name="setup /structure/").text
        self.unit_ids = sorted(set(re.findall(r'<li\b[^>]*\bdata-unit-id="(\d+)"', tree))) or ["1"]
        listing = self.client.get("/staff/?state=all", name="setup /staff/").text
        self.user_ids = sorted(set(re.findall(r'href="/staff/(\d+)/"', listing))) or ["1"]

    @task(3)
    def structure(self):
        self.client.get("/structure/", name="/structure/")

    @task(3)
    def unit_card(self):
        self.client.get(f"/structure/{random.choice(self.unit_ids)}/", headers={"HX-Request": "true"},
                        name="/structure/<id>/ (HTMX)")

    @task(3)
    def staff_search(self):
        self.client.get(f"/staff/?q={self.query}&unit={random.choice(self.unit_ids)}", name="/staff/?q&unit")

    @task(2)
    def staff_card(self):
        self.client.get(f"/staff/{random.choice(self.user_ids)}/", name="/staff/<id>/")

    @task(1)
    def calendar(self):
        self.client.get("/calendar/", name="/calendar/")

    @task(1)
    def date_picker(self):
        self.client.get("/ui/date-picker/?month=2026-10", headers={"HX-Request": "true"}, name="/ui/date-picker/")


ORG_PAGES = ("/structure/", "/structure/<id>/ (HTMX)", "/staff/?q&unit", "/staff/<id>/", "/calendar/", "/ui/date-picker/")


@events.quitting.add_listener
def _check_org_p95(environment, **_kwargs):
    """NFR-102 для страниц среза 002: p95 каждой не больше 500 мс, ни одной ошибки и все страницы замерены."""
    if OrgUser not in environment.user_classes:
        return
    stats = environment.stats
    over = {}
    for name in ORG_PAGES:
        entry = stats.entries.get((name, "GET"))
        p95 = entry.get_response_time_percentile(0.95) if entry and entry.num_requests else None
        if p95 is None or p95 > P95_LIMIT_MS:
            over[name] = p95
    if stats.total.num_failures or over:
        print(f"NFR-102 (срез 002) не выполнено: p95 выше {P95_LIMIT_MS} мс или нет замера {over}, "
              f"ошибок {stats.total.num_failures}", file=sys.stderr)
        environment.process_exit_code = 1


class ServiceDeskUser(HttpUser):
    """Срез 003 (T-3242, NFR-203, NFR-210): вошедший сотрудник листает заявки — список по пресетам, список с фильтром и
    поиском, карточку-фрагмент, открытую форму (GET и POST) и счётчик. Модель нагрузки та же (PLAN-001 версия 4); данные —
    `prepare_users.py`, `fill_tickets.py` (110 тыс. заявок, 550 тыс. сообщений, очереди) и затем `prepare_org.py` (часть
    пользователей становится участниками очередей: у них список открывается на «Мои очереди», у остальных — на «Мои»).
    Запуск только этого класса (Этап 4, T-3304; на время прогона порог формы в настройках сервис-деска поднят, после —
    возвращён):
        LOAD_CREDENTIALS=creds.csv locust -f tests/load/locustfile.py --headless -u 100 -r 1 -t 6m \
            --reset-stats --host https://127.0.0.1:8031 ServiceDeskUser
    (имя класса — в конце команды: без него locust запускает все классы файла и делит `-u` между ними)
    Поиск в списке — строка LOAD_TICKET_QUERY (по умолчанию «принтер», слово из сообщений `fill_tickets.py`). Номера
    заявок для карточки и значения полей формы берутся со страниц при входе. Поток писем (30 в час через `APPEND`) и
    поток заявок формы (около 30 в час) задаёт приёмка T-3304: здесь форму отправляет с заданной долей LOAD_FORM_POST
    (по умолчанию 1 запрос из 30 действий)."""

    wait_time = between(*(float(x) for x in os.environ.get("LOAD_WAIT", "5,15").split(",")))
    PRESETS = ("mine", "unassigned", "my_queues", "waiting", "closed", "all")

    def on_start(self):
        self.client.verify = False
        self.email, self.password, self.key = _next_credentials()
        StaffAuditHistoryUser._post_form(self, "/login/", {"email": self.email, "password": self.password})
        StaffAuditHistoryUser._post_form(self, "/login/code/", {"code": _totp(self.key)})
        self.query = os.environ.get("LOAD_TICKET_QUERY", "принтер")
        listing = self.client.get("/tickets/?preset=all", name="setup /tickets/").text
        self.numbers = sorted(set(re.findall(r'href="/tickets/(\d+)/"', listing))) or ["1"]
        form = self.client.get("/request/", name="setup /request/").text
        self.category = (re.findall(r'<option[^>]*\bvalue="(\d+)"', form.split('name="category"', 1)[-1]) or [""])[0]

    @task(4)
    def preset_list(self):
        self.client.get(f"/tickets/?preset={random.choice(self.PRESETS)}", name="/tickets/?preset")

    @task(3)
    def filtered_list(self):
        kind = random.choice(("new", "in_progress", "waiting", "closed"))
        self.client.get(f"/tickets/?preset=all&kind={kind}&sort=created_at&dir=desc", name="/tickets/?kind")

    @task(3)
    def search_list(self):
        self.client.get(f"/tickets/?preset=all&q={self.query}", name="/tickets/?q")

    @task(3)
    def ticket_fragment(self):
        self.client.get(f"/tickets/{random.choice(self.numbers)}/", headers={"HX-Request": "true"},
                        name="/tickets/<n>/ (HTMX)")

    @task(2)
    def report(self):
        """Срез 011 (NFR-730): страница отчёта с типовым периодом; выгрузка не входит в 500 мс (NFR-731)."""
        self.client.get("/servicedesk/reports/?period=week", name="/servicedesk/reports/?period")

    @task(2)
    def overdue_list(self):
        """Срез 011 (FR-741, NFR-730): фильтр просроченных заявок."""
        self.client.get("/tickets/?preset=all&due=overdue", name="/tickets/?due")

    @task(2)
    def count(self):
        self.client.get(f"/tickets/count/?preset={random.choice(self.PRESETS)}", headers={"HX-Request": "true"},
                        name="/tickets/count/")

    @task(1)
    def form_get(self):
        self.client.get("/request/", name="GET /request/")

    @task(int(os.environ.get("LOAD_FORM_POST", "1")))
    def form_post(self):
        self.client.get("/request/", name="GET /request/")
        token = self.client.cookies.get("csrftoken", "")
        data = {"email": f"load-form-{random.randrange(10**9)}@client.example", "name": "Заявитель Нагрузка",
                "client_unit": "", "category": self.category, "subject": "Не печатает принтер",
                "text": "Нагрузочная заявка с открытой формы", "consent": "on", "csrfmiddlewaretoken": token}
        with self.client.post("/request/", data=data, headers={"Referer": self.host + "/request/"}, name="POST /request/",
                              allow_redirects=True, catch_response=True) as response:
            if response.status_code >= 400 or not response.url.endswith("/request/done/"):
                response.failure(f"/request/: {response.status_code}, заявка не принята")


SD_PAGES = ("/tickets/?preset", "/tickets/?kind", "/tickets/?q", "/tickets/<n>/ (HTMX)", "/tickets/count/", "GET /request/",
            "/servicedesk/reports/?period", "/tickets/?due")


@events.quitting.add_listener
def _check_sd_p95(environment, **_kwargs):
    """NFR-203 для страниц среза 003: p95 каждой не больше 500 мс, ни одной ошибки и все страницы замерены."""
    if ServiceDeskUser not in environment.user_classes:
        return
    stats = environment.stats
    over = {}
    for name in SD_PAGES:
        entry = stats.entries.get((name, "GET"))
        p95 = entry.get_response_time_percentile(0.95) if entry and entry.num_requests else None
        if p95 is None or p95 > P95_LIMIT_MS:
            over[name] = p95
    post = stats.entries.get(("POST /request/", "POST"))
    if post and post.num_requests and post.get_response_time_percentile(0.95) > P95_LIMIT_MS:
        over["POST /request/"] = post.get_response_time_percentile(0.95)
    if stats.total.num_failures or over:
        print(f"NFR-203 (срез 003) не выполнено: p95 выше {P95_LIMIT_MS} мс или нет замера {over}, "
              f"ошибок {stats.total.num_failures}", file=sys.stderr)
        environment.process_exit_code = 1


# --- срез 012: очереди, карточка, настройка и публичная оценка -------------------------------


@tag("slice012", "nfr737")
class QueueLinksUser(HttpUser):
    """NFR-737: 100 сотрудников читают очередь, карточку, правило и блок задач.

    Запуск только этого класса:
    ``LOAD_CREDENTIALS=creds.csv locust -f tests/load/locustfile.py -u 100 -r 1
    --headless --reset-stats QueueLinksUser``.
    """

    wait_time = between(*(float(x) for x in os.environ.get("LOAD_WAIT", "5,15").split(",")))

    def on_start(self):
        self.client.verify = False
        self.email, self.password, self.key = _next_credentials()
        StaffAuditHistoryUser._post_form(self, "/login/", {"email": self.email, "password": self.password})
        StaffAuditHistoryUser._post_form(self, "/login/code/", {"code": _totp(self.key)})
        queues = self.client.get("/servicedesk/queues/", name="setup /servicedesk/queues/").text
        self.queue_ids = sorted(set(re.findall(
            r'href="/servicedesk/queues/(\d+)/(?:rule|observers)/"', queues,
        ))) or sorted(set(re.findall(r"/servicedesk/queues/(\d+)/", queues))) or ["1"]
        tickets = self.client.get("/tickets/?preset=all", name="setup /tickets/").text
        self.ticket_numbers = sorted(set(re.findall(r'href="/tickets/(\d+)/"', tickets))) or ["1"]

    @task(3)
    def queue(self):
        self.client.get("/servicedesk/queues/", name="/servicedesk/queues/")

    @task(3)
    def card(self):
        self.client.get(f"/tickets/{random.choice(self.ticket_numbers)}/",
                        name="/tickets/<n>/ (queue links card)")

    @task(2)
    def queue_settings(self):
        queue_id = random.choice(self.queue_ids)
        self.client.get(f"/servicedesk/queues/{queue_id}/rule/",
                        name="/servicedesk/queues/<id>/rule/")

    @task(2)
    def tasks_block(self):
        # Карточка серверно собирает блок связанных задач; HX-Request мерит именно
        # фрагмент, не смешивая его с прежним именем карточки.
        self.client.get(f"/tickets/{random.choice(self.ticket_numbers)}/",
                        headers={"HX-Request": "true"},
                        name="/tickets/<n>/ (tasks block)")


QUEUE_LINKS_PAGES = (
    ("/servicedesk/queues/", "GET"),
    ("/tickets/<n>/ (queue links card)", "GET"),
    ("/servicedesk/queues/<id>/rule/", "GET"),
    ("/tickets/<n>/ (tasks block)", "GET"),
)


@events.quitting.add_listener
def _check_queue_links_p95(environment, **_kwargs):
    """NFR-737: все четыре независимых имени должны иметь p95 не более 500 мс."""
    if QueueLinksUser not in environment.user_classes:
        return
    stats = environment.stats
    over = {}
    for name, method in QUEUE_LINKS_PAGES:
        entry = stats.entries.get((name, method))
        p95 = entry.get_response_time_percentile(0.95) if entry and entry.num_requests else None
        if p95 is None or p95 > P95_LIMIT_MS:
            over[name] = p95
    if stats.total.num_failures or over:
        print(f"NFR-737 не выполнено: p95 {over}, ошибок {stats.total.num_failures}", file=sys.stderr)
        environment.process_exit_code = 1


@tag("slice012", "nfr738")
class RatingPublicUser(HttpUser):
    """NFR-738: 50 заявителей открывают страницу оценки и отправляют код POST.

    `LOAD_RATING_TICKET` задаёт закрытую заявку из профиля наполнения. Восемь
    синтетических попыток на пользователя проверяют 5/15-минутный rate limit;
    неверный код и 429 считаются ожидаемым ответом и не маскируются в логах.
    """

    wait_time = between(*(float(x) for x in os.environ.get("LOAD_RATING_WAIT", "5,15").split(",")))

    def on_start(self):
        self.client.verify = False
        self.ticket_number = os.environ.get("LOAD_RATING_TICKET", "1")
        path = f"/rate/?ticket={self.ticket_number}"
        self.client.get(path, name="GET /rate/?ticket")
        token = self.client.cookies.get("csrftoken", "")
        for _ in range(6):
            with self.client.post(
                path,
                data={"code": os.environ.get("LOAD_RATING_CODE", "LOADINVALID"),
                      "score": "5", "csrfmiddlewaretoken": token},
                headers={"Referer": self.host + path},
                name="POST /rate/?ticket (code)",
                catch_response=True,
            ) as response:
                # 2xx/4xx/429 are application outcomes for this probe; server
                # errors remain Locust failures.
                if response.status_code >= 500:
                    response.failure(f"/rate/: {response.status_code}")
                else:
                    response.success()

    @task
    def rating_get(self):
        self.client.get(f"/rate/?ticket={self.ticket_number}", name="GET /rate/?ticket")


RATING_PAGES = (("GET /rate/?ticket", "GET"), ("POST /rate/?ticket (code)", "POST"))


@events.quitting.add_listener
def _check_rating_p95(environment, **_kwargs):
    """NFR-738: публичные GET и POST с кодом — p95 не выше 500 мс."""
    if RatingPublicUser not in environment.user_classes:
        return
    stats = environment.stats
    over = {}
    for name, method in RATING_PAGES:
        entry = stats.entries.get((name, method))
        p95 = entry.get_response_time_percentile(0.95) if entry and entry.num_requests else None
        if p95 is None or p95 > P95_LIMIT_MS:
            over[name] = p95
    if stats.total.num_failures or over:
        print(f"NFR-738 не выполнено: p95 {over}, ошибок {stats.total.num_failures}", file=sys.stderr)
        environment.process_exit_code = 1


class NotifyUser(HttpUser):
    """Срез 004 (T-4242, NFR-301, NFR-303, NFR-305): вошедший сотрудник держит открытое соединение `/ws/notify/` и листает
    «Уведомления», колокольчик и «Мои уведомления»; параллельно идёт поток заявок около 30 в час (форма и письмо), который
    порождает уведомления. Модель нагрузки та же (PLAN-001 версия 4); данные — `prepare_users.py`, `fill_tickets.py`,
    `prepare_org.py`. Запуск только этого класса (Этап 4):
        LOAD_CREDENTIALS=creds.csv locust -f tests/load/locustfile.py --headless -u 100 -r 1 -t 6m \
            --reset-stats --host https://127.0.0.1:8031 NotifyUser
    (имя класса — в конце команды: без него locust запускает все классы файла и делит `-u` между ними)
    Соединение — `websocket-client` в гринлете пользователя, куки сессии берутся из HTTP-клиента. Поток заявок один на весь
    прогон: форма — LOAD_NOTIFY_FORM_PER_HOUR (по умолчанию 15), письмо через `APPEND` — LOAD_NOTIFY_MAIL_PER_HOUR (по
    умолчанию 15) при заданных LOAD_IMAP_HOST, LOAD_IMAP_USER, LOAD_IMAP_PASSWORD (без них письма не шлются). Задержка
    доставки числа — время от последней заявки до кадра соединения, записывается как запрос `WS bell frame` (p95 не больше
    2 с; оценка приблизительная: заявки идут вперемешку с кадрами других причин). Память процессов web до и после прогона
    снимает человек (`docker stats`)."""

    wait_time = between(*(float(x) for x in os.environ.get("LOAD_WAIT", "5,15").split(",")))
    _stream_started = False
    _last_ticket_at = 0.0

    def on_start(self):
        self.client.verify = False
        self.email, self.password, self.key = _next_credentials()
        StaffAuditHistoryUser._post_form(self, "/login/", {"email": self.email, "password": self.password})
        StaffAuditHistoryUser._post_form(self, "/login/code/", {"code": _totp(self.key)})
        form = self.client.get("/request/", name="setup /request/").text
        self.category = (re.findall(r'<option[^>]*\bvalue="(\d+)"', form.split('name="category"', 1)[-1]) or [""])[0]
        self.socket = None
        self._connect()
        with _lock:
            if not NotifyUser._stream_started:
                NotifyUser._stream_started = True
                gevent.spawn(self._ticket_stream)

    def on_stop(self):
        if self.socket is not None:
            self.socket.close()

    def _connect(self):
        """Соединение `/ws/notify/` с куками HTTP-клиента; кадры читает гринлет пользователя."""
        import websocket

        cookies = "; ".join(f"{name}={value}" for name, value in self.client.cookies.items())
        scheme = "wss" if self.host.startswith("https") else "ws"
        url = f"{scheme}://{self.host.split('://', 1)[1]}/ws/notify/"
        started = time.monotonic()
        try:
            # Origin — параметром: библиотека ставит свой заголовок, второй даёт 400 (T-4304)
            self.socket = websocket.create_connection(url, header=[f"Cookie: {cookies}"], origin=self.host,
                                                      sslopt={"cert_reqs": ssl.CERT_NONE}, timeout=60)
            self.environment.events.request.fire(request_type="WS", name="/ws/notify/ connect", exception=None,
                                                 response_time=(time.monotonic() - started) * 1000, response_length=0)
            gevent.spawn(self._read_frames)
        except Exception as error:
            self.environment.events.request.fire(request_type="WS", name="/ws/notify/ connect", exception=error,
                                                 response_time=(time.monotonic() - started) * 1000, response_length=0)

    def _read_frames(self):
        sock = self.socket
        while sock is not None and sock.connected:
            try:
                frame = sock.recv()
            except Exception:
                return
            late = time.monotonic() - NotifyUser._last_ticket_at
            if frame and NotifyUser._last_ticket_at and late < 10:
                self.environment.events.request.fire(request_type="WS", name="WS bell frame", exception=None,
                                                     response_time=late * 1000, response_length=len(frame))

    def _ticket_stream(self):
        """Поток заявок: форма и письмо, всего около 30 в час, на весь прогон."""
        per_hour = int(os.environ.get("LOAD_NOTIFY_FORM_PER_HOUR", "15")), int(os.environ.get("LOAD_NOTIFY_MAIL_PER_HOUR", "15"))
        total = max(1, sum(per_hour))
        while True:
            gevent.sleep(random.expovariate(total / 3600))
            use_mail = random.random() < per_hour[1] / total
            try:
                if use_mail and os.environ.get("LOAD_IMAP_HOST"):
                    self._append_mail()
                else:
                    self._post_request()
            except Exception as error:
                self.environment.events.request.fire(request_type="POST", name="ticket stream", exception=error,
                                                     response_time=0, response_length=0)

    def _post_request(self):
        self.client.get("/request/", name="GET /request/")
        token = self.client.cookies.get("csrftoken", "")
        data = {"email": f"load-notify-{random.randrange(10**9)}@client.example", "name": "Заявитель Нагрузка",
                "client_unit": "", "category": self.category, "subject": "Не печатает принтер",
                "text": "Нагрузочная заявка для уведомлений", "consent": "on", "csrfmiddlewaretoken": token}
        NotifyUser._last_ticket_at = time.monotonic()
        with self.client.post("/request/", data=data, headers={"Referer": self.host + "/request/"}, name="POST /request/",
                              allow_redirects=True, catch_response=True) as response:
            if response.status_code >= 400 or not response.url.endswith("/request/done/"):
                response.failure(f"/request/: {response.status_code}, заявка не принята")

    def _append_mail(self):
        """Письмо заявителя в ящик через IMAP `APPEND`; пароль берётся из окружения и никуда не пишется."""
        import imaplib
        from email.message import EmailMessage

        message = EmailMessage()
        message["From"] = f"load-notify-{random.randrange(10**9)}@client.example"
        message["To"] = os.environ.get("LOAD_IMAP_USER", "")
        message["Subject"] = "Не печатает принтер"
        message["Message-ID"] = f"<load-notify-{random.randrange(10**12)}@client.example>"
        message.set_content("Нагрузочное письмо для уведомлений")
        NotifyUser._last_ticket_at = time.monotonic()
        with imaplib.IMAP4_SSL(os.environ["LOAD_IMAP_HOST"]) as conn:
            conn.login(os.environ["LOAD_IMAP_USER"], os.environ["LOAD_IMAP_PASSWORD"])
            conn.append("INBOX", None, None, message.as_bytes())

    @task(3)
    def notifications_page(self):
        self.client.get("/notifications/", name="/notifications/")

    @task(3)
    def bell(self):
        self.client.get("/notifications/bell/", headers={"HX-Request": "true"}, name="/notifications/bell/")

    @task(2)
    def my_notifications(self):
        self.client.get("/me/notifications/", name="/me/notifications/")


NOTIFY_PAGES = ("/notifications/", "/notifications/bell/", "/me/notifications/")
BELL_LIMIT_MS = 2000


@events.quitting.add_listener
def _check_notify_p95(environment, **_kwargs):
    """NFR-305 для страниц среза 004: p95 каждой не больше 500 мс; NFR-301: p95 кадра числа не больше 2 с; ни одной ошибки."""
    if NotifyUser not in environment.user_classes:
        return
    stats = environment.stats
    over = {}
    for name in NOTIFY_PAGES:
        entry = stats.entries.get((name, "GET"))
        p95 = entry.get_response_time_percentile(0.95) if entry and entry.num_requests else None
        if p95 is None or p95 > P95_LIMIT_MS:
            over[name] = p95
    frame = stats.entries.get(("WS bell frame", "WS"))
    if frame and frame.num_requests and frame.get_response_time_percentile(0.95) > BELL_LIMIT_MS:
        over["WS bell frame"] = frame.get_response_time_percentile(0.95)
    if stats.total.num_failures or over:
        print(f"NFR-301/305 (срез 004) не выполнено: p95 выше предела или нет замера {over}, "
              f"ошибок {stats.total.num_failures}", file=sys.stderr)
        environment.process_exit_code = 1


class KnowledgeUser(HttpUser):
    """Срез 005 (T-5242, NFR-401, NFR-402, NFR-412): вошедший сотрудник листает базу знаний — главную, рубрику, статью,
    историю и сравнение версий, добавляет комментарий, набирает слово в строке поиска (всплывающая выдача), открывает
    страницу результатов и подсчёт групп на частых, редких и смешанных словах. Модель нагрузки та же (PLAN-001
    версия 4); данные — `prepare_users.py` и `fill_articles.py` (5 000 статей, 60 рубрик, 200 тегов). Часть учёток — без прав
    базы знаний и без «Все заявки» (строка `creds.csv` с четвёртым столбцом `plain`, C-15): им выдача отфильтрована, ошибок
    быть не должно; без таких строк класс работает как прежние (все учётки — администраторы). Запуск только этого класса
    (Этап 4, T-5304; только на свободной машине и по согласию владельца):
        LOAD_CREDENTIALS=creds.csv locust -f tests/load/locustfile.py --headless -u 100 -r 1 -t 6m \
            --reset-stats --host https://127.0.0.1:8031 KnowledgeUser
    (имя класса — в конце команды: без него locust запускает все классы файла и делит `-u` между ними)
    Номера статей и рубрик берутся из разметки главной (`data-article-id`, `data-rubric-id`). Слова поиска —
    LOAD_KB_FREQUENT, LOAD_KB_RARE, LOAD_KB_MIXED (по умолчанию слова словаря `fill_articles.py`). Пределы: p95 страниц
    не больше 500 мс (`P95_LIMIT_MS`), `/search/…` — 1000 мс, ошибок нет."""

    wait_time = between(*(float(x) for x in os.environ.get("LOAD_WAIT", "5,15").split(",")))

    def on_start(self):
        self.client.verify = False
        row = _next_credentials()
        self.email, self.password, self.key = row[:3]
        self.plain = len(row) > 3 and row[3] == "plain"  # учётка без прав базы знаний
        StaffAuditHistoryUser._post_form(self, "/login/", {"email": self.email, "password": self.password})
        StaffAuditHistoryUser._post_form(self, "/login/code/", {"code": _totp(self.key)})
        home = self.client.get("/kb/", name="setup /kb/").text
        self.articles = sorted(set(re.findall(r'data-article-id="(\d+)"', home))) or ["1"]
        self.rubrics = sorted(set(re.findall(r'data-rubric-id="(\d+)"', home))) or ["1"]
        self.words = {
            "frequent": os.environ.get("LOAD_KB_FREQUENT", "принтер"),
            "rare": os.environ.get("LOAD_KB_RARE", "гарнитура"),
            "mixed": os.environ.get("LOAD_KB_MIXED", "принтер сертификат"),
        }

    def _query(self) -> str:
        return random.choice(list(self.words.values()))

    @task(4)
    def home(self):
        self.client.get("/kb/", name="/kb/")

    @task(3)
    def rubric(self):
        self.client.get(f"/kb/rubrics/{random.choice(self.rubrics)}/", name="/kb/rubrics/<n>/")

    @task(5)
    def article(self):
        self.client.get(f"/kb/{random.choice(self.articles)}/", name="/kb/<n>/")

    @task(2)
    def history(self):
        self.client.get(f"/kb/{random.choice(self.articles)}/history/", name="/kb/<n>/history/")

    @task(2)
    def compare(self):
        self.client.get(f"/kb/{random.choice(self.articles)}/compare/?v=1&v=2", name="/kb/<n>/compare/")

    @task(1)
    def comment(self):
        number = random.choice(self.articles)
        token = self.client.cookies.get("csrftoken", "")
        with self.client.post(f"/kb/{number}/comments/", data={"text": "Нагрузочный комментарий", "csrfmiddlewaretoken": token},
                              headers={"Referer": self.host + f"/kb/{number}/", "HX-Request": "true"},
                              name="POST /kb/<n>/comments/", catch_response=True) as response:
            if response.status_code >= 500:
                response.failure(f"/kb/<n>/comments/: {response.status_code}")
            else:  # ожидаемый отказ 4xx (права, черновик) — ответ сайта, не сбой
                response.success()

    @task(4)
    def popup(self):
        self.client.get("/search/popup/", params={"q": self._query()}, headers={"HX-Request": "true"},
                        name="/search/popup/")

    @task(3)
    def results(self):
        self.client.get("/search/", params={"q": self._query()}, name="/search/?q")

    @task(3)
    def count(self):
        self.client.get("/search/count/", params={"q": self._query(), "group": "articles"},
                        headers={"HX-Request": "true"}, name="/search/count/")


KB_PAGES = ("/kb/", "/kb/rubrics/<n>/", "/kb/<n>/", "/kb/<n>/history/", "/kb/<n>/compare/")
KB_SEARCH_PAGES = ("/search/popup/", "/search/?q", "/search/count/")
SEARCH_LIMIT_MS = 1000


@events.quitting.add_listener
def _check_kb_p95(environment, **_kwargs):
    """NFR-401/402 для страниц среза 005: p95 страниц не больше 500 мс, `/search/…` — не больше 1000 мс; ни одной ошибки."""
    if KnowledgeUser not in environment.user_classes:
        return
    stats = environment.stats
    over = {}
    for names, limit in ((KB_PAGES, P95_LIMIT_MS), (KB_SEARCH_PAGES, SEARCH_LIMIT_MS)):
        for name in names:
            entry = stats.entries.get((name, "GET"))
            p95 = entry.get_response_time_percentile(0.95) if entry and entry.num_requests else None
            if p95 is None or p95 > limit:
                over[name] = p95
    post = stats.entries.get(("POST /kb/<n>/comments/", "POST"))
    if post and post.num_requests and post.get_response_time_percentile(0.95) > P95_LIMIT_MS:
        over["POST /kb/<n>/comments/"] = post.get_response_time_percentile(0.95)
    if stats.total.num_failures or over:
        print(f"NFR-401/402 (срез 005) не выполнено: p95 выше предела или нет замера {over}, "
              f"ошибок {stats.total.num_failures}", file=sys.stderr)
        environment.process_exit_code = 1


class ListsUser(HttpUser):
    """Срез 006 (T-6241, NFR-501…NFR-504, NFR-513): вошедший сотрудник работает со списками — таблица с фильтрами, отбором и
    сортировками, карточка записи, сквозной поиск и поиск внутри списка, выгрузка в Excel, предпросмотр загрузки 5 000 строк.
    Модель нагрузки та же (PLAN-001 версия 4); данные — `prepare_users.py` и `fill_lists.py` (10 000 записей «Оборудования»,
    50 000 всего). Каждая учётка читает только часть списков (случайная половина доступных ей, не меньше одного), поэтому
    нагрузка ложится на разные списки; учётка без доступа ни к одному списку (строка `creds.csv` с четвёртым столбцом
    `plain`) видит пустой раздел и пользуется только сквозным поиском: выдача отфильтрована по правам, ошибок быть не
    должно. Запуск только этого класса (Этап 4; только на свободной машине и по согласию владельца):
        LOAD_CREDENTIALS=creds.csv locust -f tests/load/locustfile.py --headless -u 100 -r 1 -t 6m \
            --reset-stats --host https://127.0.0.1:8031 ListsUser
    (имя класса — в конце команды: без него locust запускает все классы файла и делит `-u` между ними)
    Номера списков и записей берутся из разметки (`data-list-id`, `data-record-number`). Слова поиска —
    LOAD_LISTS_FREQUENT, LOAD_LISTS_RARE, LOAD_LISTS_MIXED (по умолчанию слова словаря `fill_lists.py`). Частота (решение 65): выгрузка и предпросмотр — около раза в час на пользователя при паузе 5–15 с (~100 в час на всех
    при 100 пользователях). Пределы:
    таблица и карточка p95 не больше 500 мс (`P95_LIMIT_MS`), поиск — 1000 мс, выгрузка — 10 с, предпросмотр — 15 с."""

    wait_time = between(*(float(x) for x in os.environ.get("LOAD_WAIT", "5,15").split(",")))

    def on_start(self):
        self.client.verify = False
        row = _next_credentials()
        self.email, self.password, self.key = row[:3]
        StaffAuditHistoryUser._post_form(self, "/login/", {"email": self.email, "password": self.password})
        StaffAuditHistoryUser._post_form(self, "/login/code/", {"code": _totp(self.key)})
        home = self.client.get("/lists/", name="setup /lists/").text
        every = sorted(set(re.findall(r'data-list-id="(\d+)"', home)))
        self.lists = random.sample(every, max(1, (len(every) + 1) // 2)) if every else []
        self.numbers = {}
        for list_id in self.lists:
            page = self.client.get(f"/lists/{list_id}/", name="setup /lists/<n>/").text
            self.numbers[list_id] = sorted(set(re.findall(r'data-record-number="(\d+)"', page))) or ["1"]
        self.words = {
            "frequent": os.environ.get("LOAD_LISTS_FREQUENT", "принтер"),
            "rare": os.environ.get("LOAD_LISTS_RARE", "гарнитура"),
            "mixed": os.environ.get("LOAD_LISTS_MIXED", "принтер сертификат"),
        }

    def _query(self) -> str:
        return random.choice(list(self.words.values()))

    def _list(self):
        return random.choice(self.lists) if self.lists else None

    @task(36)
    def home(self):
        self.client.get("/lists/", name="/lists/")

    @task(72)
    def grid(self):
        list_id = self._list()
        if list_id:
            self.client.get(f"/lists/{list_id}/", name="/lists/<n>/")

    @task(48)
    def grid_filtered(self):
        list_id = self._list()
        if list_id:
            params = random.choice((
                {"sort": "title", "dir": "asc"}, {"sort": "title", "dir": "desc"}, {"sort": "number", "dir": "desc"},
                {"f.title": random.choice(self.words["frequent"].split()), "page": "1"},
                {"preset": "expiring"}, {"preset": "archive"}, {"page": "3"}))
            self.client.get(f"/lists/{list_id}/", params=params, name="/lists/<n>/?filter")

    @task(60)
    def record(self):
        list_id = self._list()
        if list_id:
            self.client.get(f"/lists/{list_id}/{random.choice(self.numbers[list_id])}/", name="/lists/<n>/<n>/")

    @task(36)
    def list_search(self):
        list_id = self._list()
        if list_id:
            self.client.get(f"/lists/{list_id}/", params={"q": self._query()}, name="/lists/<n>/?q")

    @task(48)
    def search(self):
        self.client.get("/search/", params={"q": self._query()}, name="/search/?q")

    @task(36)
    def popup(self):
        self.client.get("/search/popup/", params={"q": self._query()}, headers={"HX-Request": "true"},
                        name="/search/popup/")

    @task(1)
    def export(self):
        list_id = self._list()
        if list_id:
            with self.client.get(f"/lists/{list_id}/export/", name="/lists/<n>/export/", catch_response=True) as response:
                if response.status_code >= 500:
                    response.failure(f"/lists/<n>/export/: {response.status_code}")
                else:
                    response.success()

    @task(1)
    def import_preview(self):
        """Загрузка файла в 5 000 строк и проверка (предпросмотр); подтверждение не нажимается: данные не меняются."""
        list_id = self._list()
        if not list_id:
            return
        token = self.client.cookies.get("csrftoken", "")
        referer = {"Referer": self.host + f"/lists/{list_id}/import/"}
        body = "Название\n" + "".join(f"Нагрузка {n}\n" for n in range(1, 5001))
        with self.client.post(f"/lists/{list_id}/import/", data={"csrfmiddlewaretoken": token}, headers=referer,
                              files={"file": ("load.csv", body.encode("utf-8"), "text/csv")},
                              name="POST /lists/<n>/import/", allow_redirects=False, catch_response=True) as response:
            target = response.headers.get("Location", "")
            if response.status_code >= 500:
                response.failure(f"/lists/<n>/import/: {response.status_code}")
            else:  # 4xx — учётка без права «Правят»: ответ сайта, не сбой
                response.success()
        found = re.fullmatch(r"/lists/\d+/import/(\d+)/", target)
        if not found:
            return
        with self.client.post(target, data={"map.0": "title", "csrfmiddlewaretoken": token}, headers=referer,
                              name="POST /lists/<n>/import/<n>/", catch_response=True) as response:
            if response.status_code >= 400:
                response.failure(f"/lists/<n>/import/<n>/: {response.status_code}")


LISTS_PAGES = ("/lists/", "/lists/<n>/", "/lists/<n>/?filter", "/lists/<n>/<n>/", "/lists/<n>/?q")
LISTS_SEARCH_PAGES = ("/search/?q", "/search/popup/")
LISTS_EXPORT_LIMIT_MS = 10000
LISTS_PREVIEW_LIMIT_MS = 15000


@events.quitting.add_listener
def _check_lists_p95(environment, **_kwargs):
    """NFR-501…NFR-504 для страниц среза 006: таблица и карточка p95 не больше 500 мс, поиск — 1000 мс, выгрузка — 10 с,
    предпросмотр — 15 с; ни одной ошибки."""
    if ListsUser not in environment.user_classes:
        return
    stats = environment.stats
    over = {}
    checks = [(name, "GET", P95_LIMIT_MS) for name in LISTS_PAGES]
    checks += [(name, "GET", SEARCH_LIMIT_MS) for name in LISTS_SEARCH_PAGES]
    checks += [("/lists/<n>/export/", "GET", LISTS_EXPORT_LIMIT_MS),
               ("POST /lists/<n>/import/<n>/", "POST", LISTS_PREVIEW_LIMIT_MS)]
    for name, method, limit in checks:
        entry = stats.entries.get((name, method))
        p95 = entry.get_response_time_percentile(0.95) if entry and entry.num_requests else None
        if p95 is None or p95 > limit:
            over[name] = p95
    if stats.total.num_failures or over:
        print(f"NFR-501…504 (срез 006) не выполнено: p95 выше предела или нет замера {over}, "
              f"ошибок {stats.total.num_failures}", file=sys.stderr)
        environment.process_exit_code = 1


# --- срез 007: лента --------------------------------------------------------------------------------------------------

FEED_POST_SECONDS = float(os.environ.get("LOAD_FEED_POST_SECONDS", "30"))
FEED_COMMENT_SECONDS = float(os.environ.get("LOAD_FEED_COMMENT_SECONDS", "10"))
FEED_KEEPER_SECONDS = 5.0    # цикл гринлета: переподключение соединений и досылка `add`
FEED_TRACK_LIMIT = 300       # предел отслеживаемых номеров записей (MAX_IDS потребителя)
FEED_PUBLISHED_LIMIT = 4096  # потолок карты «номер записи → время публикации»
_FEED_PUBLISHER_STARTED = False
_FEED_PUBLISHED: dict[int, float] = {}


def _feed_remember(post_id: int, published: float) -> None:
    """Запомнить время публикации записи для замера задержки кадров; карта ограничена."""
    with _lock:
        _FEED_PUBLISHED[post_id] = published
        while len(_FEED_PUBLISHED) > FEED_PUBLISHED_LIMIT:
            _FEED_PUBLISHED.pop(next(iter(_FEED_PUBLISHED)))


def _feed_frame_post_ids(frame: str) -> list[int]:
    """Номера записей из кадра `/ws/feed/`: атрибут `data-post-id`, идентификаторы `feed-post-<n>…`
    и селекторы `#feed-post-<n>-…`; пусто для плашки «Новых записей» и кадра `sync`."""
    ids = set(re.findall(r'data-post-id="(\d+)"', frame))
    ids.update(re.findall(r"feed-post-(\d+)", frame))
    return sorted({int(value) for value in ids})


def _feed_publish_post(user, audience: str) -> int | None:
    """Опубликовать запись публикатора; номер — из ответа (`data-post-id`), время — до отправки."""
    token = user.client.cookies.get("csrftoken", "")
    to = {"all": ["all"],
          "unit": [f"u{random.choice(user.unit_ids)}"],
          "users": [f"p{pk}" for pk in random.sample(user.person_ids, min(3, len(user.person_ids)))]}[audience]
    data = {"kind": "post", "text": f"Нагрузочная запись ленты {random.randrange(10 ** 9)}",
            "to": to, "csrfmiddlewaretoken": token}
    published = time.monotonic()
    try:
        with user.client.post("/feed/posts/", data=data, headers={"Referer": user.host + "/",
                              "HX-Request": "true"}, name="POST /feed/posts/ (publisher)",
                              catch_response=True) as response:
            if response.status_code >= 400:
                response.failure(f"/feed/posts/: {response.status_code}")
                return None
            response.success()
            match = re.search(r'data-post-id="(\d+)"', response.text)
    except Exception as error:  # noqa: BLE001 — публикация не должна ронять поток
        user.environment.events.request.fire(request_type="POST", name="POST /feed/posts/ (publisher)",
                                             exception=error, response_time=0, response_length=0)
        return None
    if not match:
        return None
    post_id = int(match.group(1))
    _feed_remember(post_id, published)
    return post_id


def _feed_publish_comment(user, post_id: int) -> None:
    """Комментарий публикатора на свою запись; время — до отправки, правило то же, что у записи."""
    token = user.client.cookies.get("csrftoken", "")
    data = {"text": f"Нагрузочный комментарий {random.randrange(10 ** 9)}", "csrfmiddlewaretoken": token}
    published = time.monotonic()
    try:
        with user.client.post(f"/feed/{post_id}/comments/", data=data, headers={
                              "Referer": user.host + f"/feed/{post_id}/", "HX-Request": "true"},
                              name="POST /feed/<n>/comments/ (publisher)",
                              catch_response=True) as response:
            if response.status_code >= 500:
                response.failure(f"/feed/{post_id}/comments/: {response.status_code}")
                return
            response.success()
    except Exception as error:  # noqa: BLE001 — комментарий не должен ронять поток
        user.environment.events.request.fire(request_type="POST", name="POST /feed/<n>/comments/ (publisher)",
                                             exception=error, response_time=0, response_length=0)
        return
    _feed_remember(post_id, published)


def _feed_publisher_loop(user):
    """Единственный на прогон поток-публикатор (не на пользователя): запись раз в FEED_POST_SECONDS
    по очереди «Всем», подразделению и людям, комментарий раз в FEED_COMMENT_SECONDS на свои записи."""
    audience_cycle = ("all", "unit", "users")
    audience_step = comment_step = 0
    own_posts: list[int] = []
    post_due = comment_due = time.monotonic()
    while True:
        moment = time.monotonic()
        if moment >= post_due:
            post_id = _feed_publish_post(user, audience_cycle[audience_step % len(audience_cycle)])
            audience_step += 1
            if post_id is not None:
                own_posts.append(post_id)
            post_due = moment + FEED_POST_SECONDS
            continue
        if moment >= comment_due:
            if own_posts:
                _feed_publish_comment(user, own_posts[comment_step % len(own_posts)])
                comment_step += 1
            comment_due = moment + FEED_COMMENT_SECONDS
            continue
        gevent.sleep(min(post_due, comment_due) - moment)


@events.test_start.add_listener
def _reset_feed_publisher(**_kwargs):
    """Новый прогон — новый публикатор: состояние модуля сбрасывается (веб-интерфейс перезапускает тесты)."""
    global _FEED_PUBLISHER_STARTED
    with _lock:
        _FEED_PUBLISHER_STARTED = False
        _FEED_PUBLISHED.clear()


class FeedUser(HttpUser):
    """Срез 007 (T-7234, NFR-601…NFR-603, NFR-612): вошедший сотрудник держит оба соединения вкладки —
    `/ws/notify/` и `/ws/feed/` (F2 Ф14) — и работает с лентой: главная, «Ещё записи», карточка, фильтры,
    сквозной поиск, подсказки «Кому» и «@», «Нравится», «Прочитано», «Пойду», комментарий. Модель
    нагрузки та же (PLAN-001 версия 4); данные — `prepare_users.py` и `fill_feed.py` (50 000 записей,
    200 000 комментариев; адресаты, виды и отметки — по распределению F1). Запуск только этого класса
    (Этап 4; свободная машина и согласие владельца, правила run4.sh среза 006):
        LOAD_CREDENTIALS=creds.csv locust -f tests/load/locustfile.py --headless -u 100 -r 1 -t 6m \
            --reset-stats --host https://127.0.0.1:8031 FeedUser
    (имя класса — в конце команды: без него locust запускает все классы файла и делит `-u` между ними)
    Номера записей, авторов и «Ещё записи» берутся из разметки страниц при входе (`data-post-id`,
    `href="/staff/…"`, ссылка `data-feed-more`); пауза — LOAD_WAIT="мин,макс" (по умолчанию 5–15 с).
    Один поток-публикатор на весь прогон: запись раз в 30 с (LOAD_FEED_POST_SECONDS) по очереди «Всем»,
    подразделению и людям, комментарий раз в 10 с (LOAD_FEED_COMMENT_SECONDS); время каждой публикации —
    `{номер записи: monotonic}`. Каждый читатель разбирает номер записи из кадра `/ws/feed/`
    (`data-post-id`, идентификаторы `feed-post-<n>…`, `data-comment-id`) и пишет событие `WS feed frame`
    с точной задержкой от публикации (NFR-602: p95 не больше 2 с): для этого соединение после входа
    посылает `sync` с номерами записей страницы, а гринлет-хранитель каждые 5 с досылает `add` со
    свежими номерами публикатора и переподключает оборванные соединения. Пределы: страницы, подсказки и
    действия p95 не больше 500 мс (NFR-601), поиск — 1000 мс (NFR-603)."""

    wait_time = between(*(float(x) for x in os.environ.get("LOAD_WAIT", "5,15").split(",")))

    def on_start(self):
        global _FEED_PUBLISHER_STARTED
        self.client.verify = False
        self.email, self.password, self.key = _next_credentials()
        StaffAuditHistoryUser._post_form(self, "/login/", {"email": self.email, "password": self.password})
        StaffAuditHistoryUser._post_form(self, "/login/code/", {"code": _totp(self.key)})
        self.post_ids: list[str] = []
        self.important_ids: list[str] = []
        self.event_ids: list[str] = []
        self.author_ids: list[str] = []
        self.more_url = None
        self._scrape(self.client.get("/", name="setup / (feed)").text)
        self.words = {
            "frequent": os.environ.get("LOAD_FEED_FREQUENT", "принтер"),
            "rare": os.environ.get("LOAD_FEED_RARE", "гарнитура"),
            "mixed": os.environ.get("LOAD_FEED_MIXED", "принтер сертификат"),
        }
        self.pick_query = os.environ.get("LOAD_FEED_PICK_QUERY", "Нагрузка")
        self._tracked = {int(value) for value in self.post_ids[:FEED_TRACK_LIMIT]}
        self._comment_posts: dict[int, int] = {}
        self._alive = True
        self.notify_socket = None
        self.feed_socket = None
        self._connect_notify()
        self._connect_feed()
        gevent.spawn(self._keep_sockets)
        become_publisher = False
        with _lock:
            if not _FEED_PUBLISHER_STARTED:
                _FEED_PUBLISHER_STARTED = True
                become_publisher = True
        if become_publisher:
            structure = self.client.get("/structure/", name="setup /structure/ (feed)").text
            self.unit_ids = sorted(set(re.findall(r'data-unit-id="(\d+)"', structure))) or ["1"]
            staff = self.client.get("/staff/?state=active", name="setup /staff/ (feed)").text
            self.person_ids = sorted(set(re.findall(r'href="/staff/(\d+)/"', staff))) or ["1"]
            gevent.spawn(_feed_publisher_loop, self)

    def on_stop(self):
        self._alive = False
        for socket in (self.notify_socket, self.feed_socket):
            if socket is not None:
                try:
                    socket.close()
                except Exception:  # noqa: BLE001 — закрытие уже закрытого соединения не ошибка
                    pass
        self.notify_socket = None
        self.feed_socket = None

    def _scrape(self, page: str) -> None:
        """Номера записей, важных, событий, авторов и ссылка «Ещё записи» из разметки страницы ленты."""
        self.post_ids = sorted(set(re.findall(r'data-post-id="(\d+)"', page))) or self.post_ids
        self.important_ids = sorted(set(re.findall(r'id="feed-post-(\d+)-imp"', page))) or self.important_ids
        self.event_ids = sorted(set(re.findall(r'id="feed-post-(\d+)-event"', page))) or self.event_ids
        self.author_ids = sorted(set(re.findall(r'href="/staff/(\d+)/"', page))) or self.author_ids
        more = re.search(r'href="(/feed/more/\?[^"]*)"', page)
        if more:
            self.more_url = html.unescape(more.group(1))

    def _connect_notify(self) -> None:
        """Соединение `/ws/notify/` с куками HTTP-клиента; кадры читает и выбрасывает гринлет."""
        if not self._alive:
            return
        import websocket

        cookies = "; ".join(f"{name}={value}" for name, value in self.client.cookies.items())
        scheme = "wss" if self.host.startswith("https") else "ws"
        url = f"{scheme}://{self.host.split('://', 1)[1]}/ws/notify/"
        started = time.monotonic()
        try:
            # Origin — параметром: библиотека ставит свой заголовок, второй даёт 400 (T-4304)
            self.notify_socket = websocket.create_connection(url, header=[f"Cookie: {cookies}"],
                                                              origin=self.host,
                                                              sslopt={"cert_reqs": ssl.CERT_NONE}, timeout=60)
            self.environment.events.request.fire(request_type="WS", name="/ws/notify/ connect (feed)",
                                                 exception=None, response_time=(time.monotonic() - started) * 1000,
                                                 response_length=0)
            gevent.spawn(self._drain_notify)
        except Exception as error:  # noqa: BLE001 — без соединения лента продолжает работать
            self.notify_socket = None
            self.environment.events.request.fire(request_type="WS", name="/ws/notify/ connect (feed)",
                                                 exception=error, response_time=(time.monotonic() - started) * 1000,
                                                 response_length=0)

    def _drain_notify(self) -> None:
        """Кадры `/ws/notify/` читаются и выбрасываются: метрика числа — срез 004, здесь держим вкладку."""
        socket = self.notify_socket
        while socket is not None and socket.connected and self._alive:
            try:
                socket.recv()
            except Exception:  # noqa: BLE001 — обрыв: гринлет-хранитель переподключит
                return

    def _connect_feed(self) -> None:
        """Соединение `/ws/feed/`: после входа — `sync` с номерами записей, кадры читает гринлет."""
        if not self._alive:
            return
        import websocket

        cookies = "; ".join(f"{name}={value}" for name, value in self.client.cookies.items())
        scheme = "wss" if self.host.startswith("https") else "ws"
        url = f"{scheme}://{self.host.split('://', 1)[1]}/ws/feed/"
        started = time.monotonic()
        try:
            self.feed_socket = websocket.create_connection(url, header=[f"Cookie: {cookies}"],
                                                            origin=self.host,
                                                            sslopt={"cert_reqs": ssl.CERT_NONE}, timeout=60)
            self.environment.events.request.fire(request_type="WS", name="/ws/feed/ connect", exception=None,
                                                 response_time=(time.monotonic() - started) * 1000, response_length=0)
        except Exception as error:  # noqa: BLE001 — без соединения лента продолжает работать
            self.feed_socket = None
            self.environment.events.request.fire(request_type="WS", name="/ws/feed/ connect", exception=error,
                                                 response_time=(time.monotonic() - started) * 1000, response_length=0)
            return
        socket = self.feed_socket
        try:  # чтение без таймаута: соединение живёт до закрытия, обрыв поднимет recv
            socket.settimeout(None)
        except Exception:  # noqa: BLE001 — старые версии websocket-client обходятся таймаутом соединения
            pass
        gevent.spawn(self._read_feed_frames, socket)
        self._send_feed_sync(socket)

    def _send_feed_sync(self, socket) -> None:
        """`sync`: отслеживать номера записей страницы, граница «новых записей» — сейчас."""
        ids = sorted(self._tracked)[:FEED_TRACK_LIMIT]
        payload = {"sync": {"since": datetime.now(timezone.utc).isoformat(), "ids": ids}}
        try:
            socket.send(json.dumps(payload))
        except Exception:  # noqa: BLE001 — обрыв: гринлет-хранитель переподключит и повторит sync
            pass

    def _read_feed_frames(self, socket) -> None:
        """Кадры `/ws/feed/`: связка комментарий→запись и замер задержки каждого кадра по записи."""
        while socket is not None and socket.connected and self._alive:
            try:
                frame = socket.recv()
            except Exception:  # noqa: BLE001 — обрыв или таймаут: закрываем, хранитель переподключит
                try:
                    socket.close()
                except Exception:  # noqa: BLE001
                    pass
                return
            if frame:
                self._handle_feed_frame(frame)

    def _handle_feed_frame(self, frame: str) -> None:
        """Разобрать кадр: выучить связку комментария с записью, записать задержку кадров известных записей."""
        received = time.monotonic()
        post_ids = _feed_frame_post_ids(frame)
        comment_ids = [int(value) for value in re.findall(r'data-comment-id="(\d+)"', frame)]
        if post_ids:
            for comment_id in comment_ids:
                self._comment_posts[comment_id] = post_ids[0]
            if len(self._comment_posts) > 2 * FEED_PUBLISHED_LIMIT:
                for comment_id in list(self._comment_posts)[:FEED_PUBLISHED_LIMIT]:
                    del self._comment_posts[comment_id]
        else:
            post_ids = [self._comment_posts[comment_id] for comment_id in comment_ids
                        if comment_id in self._comment_posts]
        known: list[tuple[int, float]] = []
        with _lock:
            for post_id in post_ids:
                published = _FEED_PUBLISHED.get(post_id)
                if published is not None:
                    known.append((post_id, published))
        for _post_id, published in known:
            latency = max(0.0, (received - published) * 1000)
            self.environment.events.request.fire(request_type="WS", name="WS feed frame", exception=None,
                                                 response_time=latency, response_length=len(frame))

    def _keep_sockets(self) -> None:
        """Гринлет-хранитель: досылка `add` со свежими номерами публикатора и переподключение соединений."""
        while self._alive:
            gevent.sleep(FEED_KEEPER_SECONDS)
            try:
                self._track_published()
            except Exception:  # noqa: BLE001 — хранитель не должен умирать
                pass
            try:
                if self.notify_socket is None or not self.notify_socket.connected:
                    self._connect_notify()
                if self.feed_socket is None or not self.feed_socket.connected:
                    self._connect_feed()
            except Exception:  # noqa: BLE001
                pass

    def _track_published(self) -> None:
        """`add`: отслеживать свежие записи публикатора, чтобы сервер слал о них кадры."""
        with _lock:
            fresh = [post_id for post_id in _FEED_PUBLISHED if post_id not in self._tracked]
        if not fresh:
            return
        for post_id in fresh:
            self._tracked.add(post_id)
        while len(self._tracked) > FEED_TRACK_LIMIT:
            self._tracked.discard(min(self._tracked))
        socket = self.feed_socket
        if socket is None or not socket.connected:
            return
        try:
            socket.send(json.dumps({"add": {"ids": fresh[-FEED_TRACK_LIMIT:]}}))
        except Exception:  # noqa: BLE001 — обрыв: хранитель переподключит и повторит sync
            pass

    def _query(self) -> str:
        return random.choice(list(self.words.values()))

    def _post_action(self, path: str, data: dict, name: str) -> None:
        """Действие ленты: ожидаемый отказ 4xx (права, вид записи, закрытые ответы) — ответ сайта, не сбой."""
        token = self.client.cookies.get("csrftoken", "")
        with self.client.post(path, data={**data, "csrfmiddlewaretoken": token},
                              headers={"Referer": self.host + path, "HX-Request": "true"},
                              name=name, catch_response=True) as response:
            if response.status_code >= 500:
                response.failure(f"{path}: {response.status_code}")
            else:
                response.success()

    @task(6)
    def home(self):
        self._scrape(self.client.get("/", name="/").text)

    @task(4)
    def load_more(self):
        if self.more_url:
            self.client.get(self.more_url, headers={"HX-Request": "true"}, name="/feed/more/ (HTMX)")

    @task(4)
    def card(self):
        if self.post_ids:
            self.client.get(f"/feed/{random.choice(self.post_ids)}/", name="/feed/<n>/")

    @task(4)
    def filtered(self):
        today = datetime.now(timezone.utc).date()
        params = random.choice((
            {"f": "important"}, {"f": "events"}, {"f": "mine"}, {"f": "mentions"},
            {"f": "all", "author": random.choice(self.author_ids or ["1"])},
            {"f": "all", "from": (today - timedelta(days=7)).isoformat(), "to": today.isoformat()}))
        self.client.get("/", params=params, name="/?f")

    @task(3)
    def search(self):
        self.client.get("/search/", params={"q": self._query()}, name="/search/?q")

    @task(3)
    def search_popup(self):
        self.client.get("/search/popup/", params={"q": self._query()}, headers={"HX-Request": "true"},
                        name="/search/popup/")

    @task(2)
    def pick_to(self):
        self.client.get("/feed/pick/", params={"scope": "to", "q": self.pick_query},
                        headers={"HX-Request": "true"}, name="/feed/pick/?scope=to")

    @task(2)
    def pick_mention(self):
        self.client.get("/feed/pick/", params={"scope": "mention", "q": self.pick_query},
                        headers={"HX-Request": "true"}, name="/feed/pick/?scope=mention")

    @task(3)
    def like(self):
        if self.post_ids:
            number = random.choice(self.post_ids)
            self._post_action(f"/feed/{number}/like/", {}, "POST /feed/<n>/like/")

    @task(1)
    def read(self):
        if self.important_ids:
            number = random.choice(self.important_ids)
            self._post_action(f"/feed/{number}/read/", {"opened": datetime.now(timezone.utc).isoformat()},
                              "POST /feed/<n>/read/")

    @task(1)
    def answer(self):
        if self.event_ids:
            number = random.choice(self.event_ids)
            self._post_action(f"/feed/{number}/answer/", {"answer": "go"}, "POST /feed/<n>/answer/")

    @task(2)
    def comment(self):
        if self.post_ids:
            number = random.choice(self.post_ids)
            self._post_action(f"/feed/{number}/comments/",
                              {"text": f"Нагрузочный комментарий {random.randrange(10 ** 9)}"},
                              "POST /feed/<n>/comments/")


FEED_PAGES = ("/", "/feed/more/ (HTMX)", "/feed/<n>/", "/?f")
FEED_PICK_PAGES = ("/feed/pick/?scope=to", "/feed/pick/?scope=mention")
FEED_SEARCH_PAGES = ("/search/?q", "/search/popup/")
FEED_ACTION_PAGES = ("POST /feed/<n>/like/", "POST /feed/<n>/read/", "POST /feed/<n>/answer/",
                     "POST /feed/<n>/comments/")
FEED_FRAME_LIMIT_MS = 2000


@events.quitting.add_listener
def _check_feed_p95(environment, **_kwargs):
    """NFR-601…NFR-603 для страниц среза 007: страницы, подсказки и действия p95 не больше 500 мс, поиск —
    не больше 1000 мс, кадр `/ws/feed/` — не больше 2000 мс (NFR-602); ни одной ошибки и всё замерено.
    Публикатор измеряется, если успел опубликовать: короткие прогоны его записей не имеют."""
    if FeedUser not in environment.user_classes:
        return
    stats = environment.stats
    over = {}
    checks = [(name, "GET", P95_LIMIT_MS) for name in (*FEED_PAGES, *FEED_PICK_PAGES)]
    checks += [(name, "GET", SEARCH_LIMIT_MS) for name in FEED_SEARCH_PAGES]
    checks += [(name, "POST", P95_LIMIT_MS) for name in FEED_ACTION_PAGES]
    for name, method, limit in checks:
        entry = stats.entries.get((name, method))
        p95 = entry.get_response_time_percentile(0.95) if entry and entry.num_requests else None
        if p95 is None or p95 > limit:
            over[name] = p95
    for name in ("POST /feed/posts/ (publisher)", "POST /feed/<n>/comments/ (publisher)"):
        entry = stats.entries.get((name, "POST"))
        if entry and entry.num_requests and entry.get_response_time_percentile(0.95) > P95_LIMIT_MS:
            over[name] = entry.get_response_time_percentile(0.95)
    frame = stats.entries.get(("WS feed frame", "WS"))
    frame_p95 = frame.get_response_time_percentile(0.95) if frame and frame.num_requests else None
    if frame_p95 is None or frame_p95 > FEED_FRAME_LIMIT_MS:
        over["WS feed frame"] = frame_p95
    if stats.total.num_failures or over:
        print(f"NFR-601…603 (срез 007) не выполнено: p95 выше предела или нет замера {over}, "
              f"ошибок {stats.total.num_failures}", file=sys.stderr)
        environment.process_exit_code = 1


# --- срез 008: мессенджер ---------------------------------------------------------------------------------------------

MESSENGER_POST_SECONDS = float(os.environ.get("LOAD_MESSENGER_POST_SECONDS", "20"))
MESSENGER_KEEPER_SECONDS = 5.0   # цикл гринлета: переподключение двух соединений вкладки и повтор `sync`
MESSENGER_SCAN_LIMIT = 250       # сколько строк списка просматривать в поисках общего и группового чата
MESSENGER_PUBLISHED_LIMIT = 4096  # потолок карты «номер сообщения → время публикации»
_MESSENGER_PUBLISHER_STARTED = False
_MESSENGER_PUBLISHED: dict[int, float] = {}
_MESSENGER_CHATS: dict[str, int] = {}


def _messenger_remember(message_id: int, published: float) -> None:
    """Запомнить время публикации сообщения для замера задержки кадров; карта ограничена."""
    with _lock:
        _MESSENGER_PUBLISHED[message_id] = published
        while len(_MESSENGER_PUBLISHED) > MESSENGER_PUBLISHED_LIMIT:
            _MESSENGER_PUBLISHED.pop(next(iter(_MESSENGER_PUBLISHED)))


def _messenger_frame_ids(frame: str) -> list[int]:
    """Номера сообщений из кадра `/ws/messenger/`: атрибут `data-message-id` и якоря `id="m<id>"`."""
    ids = set(re.findall(r'data-message-id="(\d+)"', frame))
    ids.update(re.findall(r'id="m(\d+)"', frame))
    return sorted({int(value) for value in ids})


def _messenger_chat_ids(page: str) -> list[str]:
    """Номера чатов из строк списка `#messenger-list` (`data-chat-id`), по возрастанию номера.

    Общий чат создаётся данными установки раньше наполнения, поэтому при обходе списка он впереди:
    поиск вида чата по заголовку беседы заканчивается на первых строках.
    """
    return [str(value) for value in sorted({int(value) for value in re.findall(r'data-chat-id="(\d+)"', page)})]


def _messenger_chat_kind(user, chat_id: str) -> str:
    """Вид чата из заголовка беседы (`data-chat-kind`); пусто — разметка вида не назвала."""
    page = user.client.get(f"/messenger/chats/{chat_id}/", name="setup /messenger/chats/<n>/ (kind)").text
    match = re.search(r'data-chat-kind="(personal|group|department|general)"', page)
    return match.group(1) if match else ""


def _messenger_broadcast_chat(user, kind: str, ids: list[str]) -> int | None:
    """Номер своего чата нужного вида (общий или групповой): один на прогон, найденный по заголовку беседы.

    Номер запоминается в `_MESSENGER_CHATS`: общий чат виден всем, поэтому остальные пользователи
    находят его в своём списке без обхода бесед. Не найден — соединение беседы пойдёт в первый чат списка.
    """
    with _lock:
        known = _MESSENGER_CHATS.get(kind)
    if known is not None and str(known) in ids:
        return known
    for chat_id in ids[:MESSENGER_SCAN_LIMIT]:
        if _messenger_chat_kind(user, chat_id) == kind:
            with _lock:
                _MESSENGER_CHATS[kind] = int(chat_id)
            return int(chat_id)
    return None


def _messenger_publish(user, chat_id: int) -> int | None:
    """Сообщение публикатора; номер — из ответа (`data-message-id`), время — до отправки."""
    token = user.client.cookies.get("csrftoken", "")
    data = {"text": f"Нагрузочное сообщение мессенджера {random.randrange(10 ** 9)}",
            "csrfmiddlewaretoken": token}
    published = time.monotonic()
    name = "POST /messenger/chats/<n>/messages/ (publisher)"
    try:
        with user.client.post(f"/messenger/chats/{chat_id}/messages/", data=data,
                              headers={"Referer": user.host + f"/messenger/chats/{chat_id}/",
                                       "HX-Request": "true"}, name=name, catch_response=True) as response:
            if response.status_code >= 400:
                response.failure(f"/messenger/chats/{chat_id}/messages/: {response.status_code}")
                return None
            response.success()
            match = re.search(r'data-message-id="(\d+)"', response.text)
    except Exception as error:  # noqa: BLE001 — публикация не должна ронять поток
        user.environment.events.request.fire(request_type="POST", name=name, exception=error,
                                             response_time=0, response_length=0)
        return None
    if not match:
        return None
    message_id = int(match.group(1))
    _messenger_remember(message_id, published)
    return message_id


def _messenger_publisher_loop(user, chat_ids: list[int]):
    """Единственный на прогон поток-публикатор (не на пользователя): сообщение раз в MESSENGER_POST_SECONDS
    по очереди в общий и групповой чат; время каждой публикации — `{номер сообщения: monotonic}`."""
    step = 0
    while True:
        gevent.sleep(MESSENGER_POST_SECONDS)
        _messenger_publish(user, chat_ids[step % len(chat_ids)])
        step += 1


@events.test_start.add_listener
def _reset_messenger_publisher(**_kwargs):
    """Новый прогон — новый публикатор: состояние модуля сбрасывается (веб-интерфейс перезапускает тесты)."""
    global _MESSENGER_PUBLISHER_STARTED
    with _lock:
        _MESSENGER_PUBLISHER_STARTED = False
        _MESSENGER_PUBLISHED.clear()
        _MESSENGER_CHATS.clear()


class MessengerUser(HttpUser):
    """Срез 008 (T-8150, NFR-701, NFR-707): вошедший сотрудник держит оба соединения вкладки — `/ws/notify/`
    (колокольчик) и `/ws/messenger/?chat=<id>` (беседа) — и работает с мессенджером: список и его фрагмент,
    беседа, история курсором («Показать более ранние»), поиск по беседе и сквозной, подсказка «@», отправка
    короткая и в 4000 знаков, правка и удаление своих, прочтение, файл формы. Модель нагрузки та же
    (PLAN-001 версия 4); данные — `prepare_users.py` и `fill_messenger.py` (200 чатов, 50 000 сообщений,
    участники и вложения по распределению плана). Запуск только этого класса (замер NFR-707 — после
    отдельного решения владельца, T-8304, на свободной машине, правила run4.sh среза 006):
        LOAD_CREDENTIALS=creds.csv locust -f tests/load/locustfile.py --headless -u 100 -r 1 -t 6m \
            --reset-stats --host https://127.0.0.1:8031 MessengerUser
    (имя класса — в конце команды: без него locust запускает все классы файла и делит `-u` между ними)
    Номера чатов и сообщений берутся из разметки страниц при входе (`data-chat-id`, `data-message-id`,
    `data-own`, ссылка `/messenger/chats/<id>/messages/?before=…`). Соединение беседы открывается в общем
    чате (он виден всем): после входа клиент посылает `sync`, а гринлет-хранитель каждые 5 с переподключает
    оборванные соединения и повторяет `sync`. Один поток-публикатор на весь прогон публикует сообщение раз
    в MESSENGER_POST_SECONDS (LOAD_MESSENGER_POST_SECONDS) по очереди в общий и групповой чат и запоминает
    `{номер сообщения: monotonic}`; каждый читатель разбирает `data-message-id` из кадра `/ws/messenger/`
    и пишет событие `WS messenger frame` с точной задержкой от публикации (NFR-701: p95 не больше 2 с).
    Пределы: страницы и действия p95 не больше 500 мс (NFR-707), поиск и подсказка «@» — 1000 мс.
    Слова поиска — LOAD_MESSENGER_FREQUENT, LOAD_MESSENGER_RARE, LOAD_MESSENGER_MIXED (по умолчанию слова
    словаря `fill_messenger.py`); подсказка «@» — LOAD_MESSENGER_PICK_QUERY (по умолчанию «На»)."""

    wait_time = between(*(float(x) for x in os.environ.get("LOAD_WAIT", "5,15").split(",")))

    def on_start(self):
        global _MESSENGER_PUBLISHER_STARTED
        self.client.verify = False
        self.email, self.password, self.key = _next_credentials()
        StaffAuditHistoryUser._post_form(self, "/login/", {"email": self.email, "password": self.password})
        StaffAuditHistoryUser._post_form(self, "/login/code/", {"code": _totp(self.key)})
        page = self.client.get("/messenger/", name="setup /messenger/").text
        self.chat_ids = _messenger_chat_ids(page) or ["1"]
        self.words = {
            "frequent": os.environ.get("LOAD_MESSENGER_FREQUENT", "сообщение"),
            "rare": os.environ.get("LOAD_MESSENGER_RARE", "вложение"),
            "mixed": os.environ.get("LOAD_MESSENGER_MIXED", "сообщение принтер"),
        }
        self.pick_query = os.environ.get("LOAD_MESSENGER_PICK_QUERY", "На")
        self.message_ids: list[str] = []
        self.own_ids: list[str] = []
        self.before_url = None
        general = _messenger_broadcast_chat(self, "general", self.chat_ids)
        self.chat_id = general or int(self.chat_ids[0])
        self._scrape(self.client.get(f"/messenger/chats/{self.chat_id}/",
                                     name="setup /messenger/chats/<n>/").text)
        self._alive = True
        self.notify_socket = None
        self.messenger_socket = None
        self._connect_notify()
        self._connect_messenger()
        gevent.spawn(self._keep_sockets)
        become_publisher = False
        with _lock:
            if not _MESSENGER_PUBLISHER_STARTED:
                _MESSENGER_PUBLISHER_STARTED = True
                become_publisher = True
        if become_publisher:
            group = _messenger_broadcast_chat(self, "group", self.chat_ids)
            chats = [chat for chat in (general, group) if chat is not None] or [self.chat_id]
            gevent.spawn(_messenger_publisher_loop, self, chats)

    def on_stop(self):
        self._alive = False
        for socket in (self.notify_socket, self.messenger_socket):
            if socket is not None:
                try:
                    socket.close()
                except Exception:  # noqa: BLE001 — закрытие уже закрытого соединения не ошибка
                    pass
        self.notify_socket = None
        self.messenger_socket = None

    def _scrape(self, page: str) -> None:
        """Номера сообщений, свои сообщения и ссылка «Показать более ранние» из разметки беседы."""
        self.message_ids = sorted(set(re.findall(r'data-message-id="(\d+)"', page))) or self.message_ids
        own = []
        for chunk in page.split("<article")[1:]:
            if 'data-own="1"' in chunk:
                match = re.search(r'data-message-id="(\d+)"', chunk)
                if match:
                    own.append(match.group(1))
        self.own_ids = own or self.own_ids
        more = re.search(r'href="(/messenger/chats/\d+/messages/\?before=[^"]*)"', page)
        if more:
            self.before_url = html.unescape(more.group(1))

    def _connect_notify(self) -> None:
        """Соединение `/ws/notify/` с куками HTTP-клиента; кадры читает и выбрасывает гринлет."""
        if not self._alive:
            return
        import websocket

        cookies = "; ".join(f"{name}={value}" for name, value in self.client.cookies.items())
        scheme = "wss" if self.host.startswith("https") else "ws"
        url = f"{scheme}://{self.host.split('://', 1)[1]}/ws/notify/"
        started = time.monotonic()
        try:
            # Origin — параметром: библиотека ставит свой заголовок, второй даёт 400 (T-4304)
            self.notify_socket = websocket.create_connection(url, header=[f"Cookie: {cookies}"],
                                                              origin=self.host,
                                                              sslopt={"cert_reqs": ssl.CERT_NONE}, timeout=60)
            self.environment.events.request.fire(request_type="WS", name="/ws/notify/ connect (messenger)",
                                                 exception=None, response_time=(time.monotonic() - started) * 1000,
                                                 response_length=0)
            gevent.spawn(self._drain_notify)
        except Exception as error:  # noqa: BLE001 — без соединения мессенджер продолжает работать
            self.notify_socket = None
            self.environment.events.request.fire(request_type="WS", name="/ws/notify/ connect (messenger)",
                                                 exception=error, response_time=(time.monotonic() - started) * 1000,
                                                 response_length=0)

    def _drain_notify(self) -> None:
        """Кадры `/ws/notify/` читаются и выбрасываются: здесь держим вкладку и колокольчик."""
        socket = self.notify_socket
        while socket is not None and socket.connected and self._alive:
            try:
                socket.recv()
            except Exception:  # noqa: BLE001 — обрыв: гринлет-хранитель переподключит
                return

    def _connect_messenger(self) -> None:
        """Соединение беседы `/ws/messenger/?chat=<id>`: после входа — `sync`, кадры читает гринлет."""
        if not self._alive:
            return
        import websocket

        cookies = "; ".join(f"{name}={value}" for name, value in self.client.cookies.items())
        scheme = "wss" if self.host.startswith("https") else "ws"
        url = f"{scheme}://{self.host.split('://', 1)[1]}/ws/messenger/?chat={self.chat_id}"
        started = time.monotonic()
        try:
            self.messenger_socket = websocket.create_connection(url, header=[f"Cookie: {cookies}"],
                                                                origin=self.host,
                                                                sslopt={"cert_reqs": ssl.CERT_NONE}, timeout=60)
            self.environment.events.request.fire(request_type="WS", name="/ws/messenger/ connect",
                                                 exception=None, response_time=(time.monotonic() - started) * 1000,
                                                 response_length=0)
        except Exception as error:  # noqa: BLE001 — без соединения беседа работает обычными запросами
            self.messenger_socket = None
            self.environment.events.request.fire(request_type="WS", name="/ws/messenger/ connect",
                                                 exception=error, response_time=(time.monotonic() - started) * 1000,
                                                 response_length=0)
            return
        socket = self.messenger_socket
        try:  # чтение без таймаута: соединение живёт до закрытия, обрыв поднимет recv
            socket.settimeout(None)
        except Exception:  # noqa: BLE001 — старые версии websocket-client обходятся таймаутом соединения
            pass
        gevent.spawn(self._read_messenger_frames, socket)
        self._send_messenger_sync(socket)

    def _send_messenger_sync(self, socket) -> None:
        """`sync`: граница живых кадров беседы — сейчас (CONTRACT-008, 11.2)."""
        payload = {"sync": {"chat": self.chat_id, "at": datetime.now(timezone.utc).isoformat()}}
        try:
            socket.send(json.dumps(payload))
        except Exception:  # noqa: BLE001 — обрыв: гринлет-хранитель переподключит и повторит sync
            pass

    def _read_messenger_frames(self, socket) -> None:
        """Кадры `/ws/messenger/`: задержка каждого кадра по номеру опубликованного сообщения."""
        while socket is not None and socket.connected and self._alive:
            try:
                frame = socket.recv()
            except Exception:  # noqa: BLE001 — обрыв или таймаут: закрываем, хранитель переподключит
                try:
                    socket.close()
                except Exception:  # noqa: BLE001
                    pass
                return
            if frame:
                self._handle_messenger_frame(frame)

    def _handle_messenger_frame(self, frame: str) -> None:
        """Событие `WS messenger frame` с точной задержкой от публикации (NFR-701: p95 не больше 2 с)."""
        received = time.monotonic()
        with _lock:
            known = [(message_id, _MESSENGER_PUBLISHED[message_id])
                     for message_id in _messenger_frame_ids(frame) if message_id in _MESSENGER_PUBLISHED]
        for _message_id, published in known:
            latency = max(0.0, (received - published) * 1000)
            self.environment.events.request.fire(request_type="WS", name="WS messenger frame", exception=None,
                                                 response_time=latency, response_length=len(frame))

    def _keep_sockets(self) -> None:
        """Гринлет-хранитель: переподключение соединений вкладки (после входа — снова `sync`)."""
        while self._alive:
            gevent.sleep(MESSENGER_KEEPER_SECONDS)
            try:
                if self.notify_socket is None or not self.notify_socket.connected:
                    self._connect_notify()
                if self.messenger_socket is None or not self.messenger_socket.connected:
                    self._connect_messenger()
            except Exception:  # noqa: BLE001 — хранитель не должен умирать
                pass

    def _query(self) -> str:
        return random.choice(list(self.words.values()))

    def _post_action(self, path: str, data: dict, name: str) -> None:
        """Действие мессенджера: ожидаемый отказ 4xx (права, чужое сообщение) — ответ сайта, не сбой."""
        token = self.client.cookies.get("csrftoken", "")
        with self.client.post(path, data={**data, "csrfmiddlewaretoken": token},
                              headers={"Referer": self.host + path, "HX-Request": "true"},
                              name=name, catch_response=True) as response:
            if response.status_code >= 500:
                response.failure(f"{path}: {response.status_code}")
            else:
                response.success()

    def _send(self, chat_id: str, text: str) -> int | None:
        """Сообщение формой беседы; номер — из ответа (`data-message-id`)."""
        token = self.client.cookies.get("csrftoken", "")
        with self.client.post(f"/messenger/chats/{chat_id}/messages/",
                              data={"text": text, "csrfmiddlewaretoken": token},
                              headers={"Referer": self.host + f"/messenger/chats/{chat_id}/",
                                       "HX-Request": "true"},
                              name="POST /messenger/chats/<n>/messages/", catch_response=True) as response:
            if response.status_code >= 500:
                response.failure(f"/messenger/chats/{chat_id}/messages/: {response.status_code}")
                return None
            response.success()  # 4xx — отказ формы (права, отключённый чат) — ответ сайта
            match = re.search(r'data-message-id="(\d+)"', response.text)
        return int(match.group(1)) if match else None

    @task(4)
    def list_page(self):
        self.client.get("/messenger/", name="/messenger/")

    @task(4)
    def list_fragment(self):
        self.client.get("/messenger/list/", params={"q": self._query()}, headers={"HX-Request": "true"},
                        name="/messenger/list/?q")

    @task(5)
    def chat(self):
        self._scrape(self.client.get(f"/messenger/chats/{random.choice(self.chat_ids)}/",
                                     name="/messenger/chats/<n>/").text)

    @task(3)
    def history(self):
        if self.before_url:
            self.client.get(self.before_url, headers={"HX-Request": "true"},
                            name="/messenger/chats/<n>/messages/ (HTMX)")

    @task(4)
    def send_short(self):
        message_id = self._send(random.choice(self.chat_ids),
                                f"Нагрузочное сообщение {random.randrange(10 ** 9)}")
        if message_id is not None:
            self.own_ids.append(str(message_id))

    @task(1)
    def send_long(self):
        """Отправка в 4000 знаков — предел текста сообщения (CONTRACT-008, 10.2)."""
        text = ("Нагрузочное сообщение мессенджера в четыре тысячи знаков для проверки отправки и показа. " * 60)[:4000]
        message_id = self._send(random.choice(self.chat_ids), text)
        if message_id is not None:
            self.own_ids.append(str(message_id))

    @task(2)
    def edit(self):
        if self.own_ids:
            message_id = random.choice(self.own_ids)
            self._post_action(f"/messenger/messages/{message_id}/edit/",
                              {"text": f"Нагрузочная правка {random.randrange(10 ** 9)}"},
                              "POST /messenger/messages/<mid>/edit/")

    @task(1)
    def delete(self):
        if self.own_ids:
            message_id = self.own_ids.pop()
            self._post_action(f"/messenger/messages/{message_id}/delete/", {},
                              "POST /messenger/messages/<mid>/delete/")

    @task(3)
    def read(self):
        self._post_action(f"/messenger/chats/{random.choice(self.chat_ids)}/read/",
                          {"at": datetime.now(timezone.utc).isoformat()},
                          "POST /messenger/chats/<n>/read/")

    @task(3)
    def chat_search(self):
        self.client.get(f"/messenger/chats/{random.choice(self.chat_ids)}/search/",
                        params={"q": self._query()}, name="/messenger/chats/<n>/search/?q")

    @task(3)
    def search(self):
        self.client.get("/search/", params={"q": self._query()}, name="/search/?q")

    @task(2)
    def mention(self):
        self.client.get("/messenger/mentions/", params={"chat": self.chat_id, "q": self.pick_query},
                        headers={"HX-Request": "true"}, name="/messenger/mentions/?chat")

    @task(1)
    def upload(self):
        """Файл формы: загрузка и уборка непривязанного — 30 непривязанных у сотрудника не упираются в предел."""
        chat_id = random.choice(self.chat_ids)
        token = self.client.cookies.get("csrftoken", "")
        body = ("Нагрузка\n" + "".join(f"Строка {number}\n" for number in range(1, 51))).encode("utf-8")
        with self.client.post("/messenger/files/", data={"chat": chat_id, "csrfmiddlewaretoken": token},
                              headers={"Referer": self.host + f"/messenger/chats/{chat_id}/", "HX-Request": "true"},
                              files={"file": ("load.csv", body, "text/csv")}, name="POST /messenger/files/",
                              catch_response=True) as response:
            if response.status_code >= 500:
                response.failure(f"/messenger/files/: {response.status_code}")
                return
            response.success()
            match = re.search(r'data-messenger-file="([0-9a-f-]{36})"', response.text)
        if match:
            self._post_action(f"/messenger/files/{match.group(1)}/delete/", {},
                              "POST /messenger/files/<id>/delete/")


MESSENGER_PAGES = ("/messenger/", "/messenger/list/?q", "/messenger/chats/<n>/",
                   "/messenger/chats/<n>/messages/ (HTMX)")
MESSENGER_SEARCH_PAGES = ("/messenger/chats/<n>/search/?q", "/search/?q", "/messenger/mentions/?chat")
MESSENGER_ACTIONS = ("POST /messenger/chats/<n>/messages/", "POST /messenger/messages/<mid>/edit/",
                     "POST /messenger/messages/<mid>/delete/", "POST /messenger/chats/<n>/read/",
                     "POST /messenger/files/", "POST /messenger/files/<id>/delete/")
MESSENGER_FRAME_LIMIT_MS = 2000


@events.quitting.add_listener
def _check_messenger_p95(environment, **_kwargs):
    """NFR-701, NFR-707 для среза 008: страницы и действия p95 не больше 500 мс, поиск, поиск по беседе
    и подсказка «@» — не больше 1000 мс, кадр `/ws/messenger/` — не больше 2000 мс; ни одной ошибки.
    Публикатор измеряется, если успел опубликовать: короткие прогоны его сообщений не имеют."""
    if MessengerUser not in environment.user_classes:
        return
    stats = environment.stats
    over = {}
    checks = [(name, "GET", P95_LIMIT_MS) for name in MESSENGER_PAGES]
    checks += [(name, "GET", SEARCH_LIMIT_MS) for name in MESSENGER_SEARCH_PAGES]
    checks += [(name, "POST", P95_LIMIT_MS) for name in MESSENGER_ACTIONS]
    for name, method, limit in checks:
        entry = stats.entries.get((name, method))
        p95 = entry.get_response_time_percentile(0.95) if entry and entry.num_requests else None
        if p95 is None or p95 > limit:
            over[name] = p95
    publisher = stats.entries.get(("POST /messenger/chats/<n>/messages/ (publisher)", "POST"))
    if publisher and publisher.num_requests and publisher.get_response_time_percentile(0.95) > P95_LIMIT_MS:
        over["POST /messenger/chats/<n>/messages/ (publisher)"] = publisher.get_response_time_percentile(0.95)
    frame = stats.entries.get(("WS messenger frame", "WS"))
    frame_p95 = frame.get_response_time_percentile(0.95) if frame and frame.num_requests else None
    if frame_p95 is None or frame_p95 > MESSENGER_FRAME_LIMIT_MS:
        over["WS messenger frame"] = frame_p95
    if stats.total.num_failures or over:
        print(f"NFR-701/707 (срез 008) не выполнено: p95 выше предела или нет замера {over}, "
              f"ошибок {stats.total.num_failures}", file=sys.stderr)
        environment.process_exit_code = 1


class TaskUser(HttpUser):
    """Срез 009 (T-9150, NFR-710, NFR-719): вошедший сотрудник работает с задачами — список и пресеты, карточка,
    четыре доски, перенос, комментарий и сквозной поиск. Данные — `fill_tasks.py` (1 000 задач на 100 сотрудников).
    Запуск только этого класса (замер NFR-710 — после отдельного решения владельца, T-9304, на свободной машине):
        LOAD_CREDENTIALS=creds.csv locust -f tests/load/locustfile.py --headless -u 100 -r 1 -t 6m \
            --reset-stats --host https://127.0.0.1:8031 TaskUser
    Номера задач берутся из разметки списка (`data-task-id`) при входе. Пределы: страницы и действия p95 не больше
    500 мс (NFR-710), поиск — 1000 мс; слова поиска — LOAD_TASKS_QUERY (по умолчанию «задача»)."""

    wait_time = between(*(float(x) for x in os.environ.get("LOAD_WAIT", "5,15").split(",")))

    def on_start(self):
        self.client.verify = False
        self.email, self.password, self.key = _next_credentials()
        StaffAuditHistoryUser._post_form(self, "/login/", {"email": self.email, "password": self.password})
        StaffAuditHistoryUser._post_form(self, "/login/code/", {"code": _totp(self.key)})
        page = self.client.get("/tasks/", name="setup /tasks/").text
        self.task_ids = sorted(set(re.findall(r'data-task-id="(\d+)"', page))) or ["1"]
        self.query = os.environ.get("LOAD_TASKS_QUERY", "задача")
        self.card_id = self.task_ids[0]

    def _post(self, path, data, name):
        token = self.client.cookies.get("csrftoken", "")
        with self.client.post(path, data={**data, "csrfmiddlewaretoken": token},
                              headers={"Referer": self.host + path, "HX-Request": "true"},
                              name=name, allow_redirects=True, catch_response=True) as response:
            if response.status_code >= 400:
                response.failure(f"{path}: {response.status_code}")

    @task(3)
    def task_list(self):
        self.client.get("/tasks/", name="/tasks/")

    @task(2)
    def task_preset(self):
        preset = random.choice(("mine", "authored", "subordinate", "work", "overdue"))
        self.client.get(f"/tasks/?preset={preset}", name="/tasks/?preset=<n>")
        self.client.get(f"/tasks/list/?preset={preset}", headers={"HX-Request": "true"},
                        name="/tasks/list/?preset=<n>")

    @task(2)
    def task_card(self):
        task_id = random.choice(self.task_ids)
        self.client.get(f"/tasks/{task_id}/", name="/tasks/<n>/")

    @task(2)
    def task_board(self):
        board = random.choice(("status", "deadline", "plan", "category"))
        self.client.get(f"/tasks/board/{board}/", name="/tasks/board/<board>/")

    @task(1)
    def task_move(self):
        task_id = random.choice(self.task_ids)
        self._post(f"/tasks/{task_id}/move/",
                   {"board": "status", "value": random.choice(("new", "in_progress", "waiting", "done"))},
                   name="POST /tasks/<n>/move/")

    @task(1)
    def task_comment(self):
        task_id = random.choice(self.task_ids)
        text = " ".join(random.choice(("проверка", "срок", "отчёт", "согласование")) for _ in range(5))
        self._post(f"/tasks/{task_id}/comments/", {"text": text}, name="POST /tasks/<n>/comments/")

    @task(1)
    def task_search(self):
        self.client.get("/search/", {"q": self.query}, name="/search/?q=<tasks>")


class InstructionUser(HttpUser):
    """Срез 010 (T-10150, NFR-720, NFR-728): сотрудник работает с поручениями — реестр и пресеты, карточка,
    отчёт по отчётной дате, дисциплина и Excel. Данные — `fill_instructions.py` (1 000 поручений на 100
    сотрудников). Запуск только этого класса (замер NFR-720 — после отдельного решения владельца, T-10304):

        LOAD_CREDENTIALS=creds.csv locust -f tests/load/locustfile.py --headless -u 100 -r 1 -t 6m \\
            --reset-stats --host https://127.0.0.1:8031 InstructionUser

    Номера поручений и отчётных дат берутся из разметки списка и карточки (`data-instruction-id`,
    `data-report-date`) при входе. Пределы: страницы p95 не больше 500 мс (NFR-720)."""

    wait_time = between(*(float(x) for x in os.environ.get("LOAD_WAIT", "5,15").split(",")))

    def on_start(self):
        self.client.verify = False
        self.email, self.password, self.key = _next_credentials()
        StaffAuditHistoryUser._post_form(self, "/login/", {"email": self.email, "password": self.password})
        StaffAuditHistoryUser._post_form(self, "/login/code/", {"code": _totp(self.key)})
        page = self.client.get("/instructions/?preset=mine", name="setup /instructions/").text
        self.instruction_ids = sorted(set(re.findall(r'data-instruction-id="(\d+)"', page))) or ["1"]
        self.card_id = self.instruction_ids[0]
        card = self.client.get(f"/instructions/{self.card_id}/", name="setup /instructions/<n>/").text
        self.date_ids = sorted(set(re.findall(r'data-report-date="(\d+)"', card)))
        self.text = " ".join(random.choice(("проверка", "отчёт", "срок", "согласование")) for _ in range(5))

    def _post(self, path, data, name):
        token = self.client.cookies.get("csrftoken", "")
        with self.client.post(path, data={**data, "csrfmiddlewaretoken": token},
                              headers={"Referer": self.host + path, "HX-Request": "true"},
                              name=name, allow_redirects=True, catch_response=True) as response:
            if response.status_code >= 500:
                response.failure(f"{path}: {response.status_code}")

    @task(3)
    def registry(self):
        self.client.get("/instructions/", name="/instructions/")

    @task(2)
    def registry_preset(self):
        preset = random.choice(("mine", "control", "subordinate", "overdue"))
        self.client.get(f"/instructions/?preset={preset}", name="/instructions/?preset=<n>")
        self.client.get(f"/instructions/list/?preset={preset}", headers={"HX-Request": "true"},
                        name="/instructions/list/?preset=<n>")

    @task(2)
    def card(self):
        instruction_id = random.choice(self.instruction_ids)
        self.client.get(f"/instructions/{instruction_id}/", name="/instructions/<n>/")

    @task(1)
    def submit_report(self):
        if not self.date_ids:
            return
        instruction_id = random.choice(self.instruction_ids)
        self._post(f"/instructions/{instruction_id}/reports/",
                   {"date": random.choice(self.date_ids), "text": self.text},
                   name="POST /instructions/<n>/reports/")

    @task(1)
    def discipline(self):
        with self.client.get("/instructions/discipline/", name="/instructions/discipline/",
                             catch_response=True) as response:
            if response.status_code in (200, 302, 403):
                response.success()
            else:
                response.failure(f"дисциплина: {response.status_code}")

    @task(1)
    def discipline_excel(self):
        with self.client.get("/instructions/discipline.xlsx", name="/instructions/discipline.xlsx",
                             catch_response=True) as response:
            if response.status_code in (200, 302, 403):
                response.success()
            else:
                response.failure(f"Excel: {response.status_code}")


@tag("slice013", "nfr742")
class AutomationBoardUser(HttpUser):
    """NFR-742: 100 сотрудников открывают канбан заявок и следующую порцию колонки.

    Запуск только этого класса:
    ``LOAD_CREDENTIALS=creds.csv locust -f tests/load/locustfile.py -u 100 -r 1 --headless --reset-stats AutomationBoardUser``.
    """

    wait_time = between(*(float(x) for x in os.environ.get("LOAD_WAIT", "5,15").split(",")))

    def on_start(self):
        self.client.verify = False
        self.email, self.password, self.key = _next_credentials()
        StaffAuditHistoryUser._post_form(self, "/login/", {"email": self.email, "password": self.password})
        StaffAuditHistoryUser._post_form(self, "/login/code/", {"code": _totp(self.key)})
        board = self.client.get("/tickets/board/", name="setup /tickets/board/").text
        self.columns = sorted(set(re.findall(r'data-column="([^"]+)"', board))) or ["closed"]

    @task(3)
    def board(self):
        self.client.get("/tickets/board/", name="/tickets/board/")

    @task(2)
    def column(self):
        key = random.choice(self.columns)
        self.client.get(f"/tickets/board/column/{key}/?offset=0", name="/tickets/board/column/<key>/")


BOARD_PAGES = (("/tickets/board/", "GET"), ("/tickets/board/column/<key>/", "GET"))


@events.quitting.add_listener
def _check_board_p95(environment, **_kwargs):
    if AutomationBoardUser not in environment.user_classes:
        return
    stats = environment.stats
    over = {}
    for name, method in BOARD_PAGES:
        entry = stats.entries.get((name, method))
        p95 = entry.get_response_time_percentile(0.95) if entry and entry.num_requests else None
        if p95 is None or p95 > P95_LIMIT_MS:
            over[name] = p95
    if stats.total.num_failures or over:
        print(f"NFR-742 не выполнено: p95 {over}, ошибок {stats.total.num_failures}", file=sys.stderr)
        environment.process_exit_code = 1
