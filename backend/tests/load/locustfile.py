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
import itertools
import os
import random
import re
import ssl
import sys
import threading
import time

import gevent
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


SD_PAGES = ("/tickets/?preset", "/tickets/?kind", "/tickets/?q", "/tickets/<n>/ (HTMX)", "/tickets/count/", "GET /request/")


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
    LOAD_LISTS_FREQUENT, LOAD_LISTS_RARE, LOAD_LISTS_MIXED (по умолчанию слова словаря `fill_lists.py`). Пределы:
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

    @task(3)
    def home(self):
        self.client.get("/lists/", name="/lists/")

    @task(6)
    def grid(self):
        list_id = self._list()
        if list_id:
            self.client.get(f"/lists/{list_id}/", name="/lists/<n>/")

    @task(4)
    def grid_filtered(self):
        list_id = self._list()
        if list_id:
            params = random.choice((
                {"sort": "title", "dir": "asc"}, {"sort": "title", "dir": "desc"}, {"sort": "number", "dir": "desc"},
                {"f.title": random.choice(self.words["frequent"].split()), "page": "1"},
                {"preset": "expiring"}, {"preset": "archive"}, {"page": "3"}))
            self.client.get(f"/lists/{list_id}/", params=params, name="/lists/<n>/?filter")

    @task(5)
    def record(self):
        list_id = self._list()
        if list_id:
            self.client.get(f"/lists/{list_id}/{random.choice(self.numbers[list_id])}/", name="/lists/<n>/<n>/")

    @task(3)
    def list_search(self):
        list_id = self._list()
        if list_id:
            self.client.get(f"/lists/{list_id}/", params={"q": self._query()}, name="/lists/<n>/?q")

    @task(4)
    def search(self):
        self.client.get("/search/", params={"q": self._query()}, name="/search/?q")

    @task(3)
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
