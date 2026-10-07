"""Заявки стенда для нагрузочного прогона среза 003 (NFR-203, NFR-210; PLAN-003, «Скорость»): добавляет заявки и сообщения
до LOAD_TICKETS (по умолчанию 110 000) и LOAD_MESSAGES (550 000) — объём трёх лет.

Что делает: отмечает очередями LOAD_QUEUES узлов `Нагрузка очередь NN` (по умолчанию 10, под корнем; узлы создаются, если их
нет); заводит заявителей `load-requester-…@client.example` (LOAD_REQUESTERS, по умолчанию 2000); добавляет недостающие заявки
(повторный запуск добирает до цели) — одним запросом на порцию, номера из `nextval('servicedesk_ticket_number')` (у роли
приложения нет права на `setval`); для каждой заявки пишет сообщения (лента: письмо, ответы и комментарии, всего по
LOAD_MESSAGES на все заявки) и столбец поиска. Заявки разбросаны по последним трём годам; закрытых 60 %, остальные — «Новая»,
«В работе», «Ждёт ответа заявителя»; у части открытых заявок есть ответственный из сотрудников нагрузки (`load-…@example.org`,
их готовит prepare_users.py; нет таких — любые действующие сотрудники). Поток писем (30 в час) и форма сюда не входят.

Очереди получают участников шагом prepare_org.py: запускать его после этого скрипта. Работает ТОЛЬКО при E2E_STAND=1
(как e2e_reset_stand); данные убирает следующий сброс приёмки. SQL — только с параметрами. Каталог tests в образ не входит,
поэтому скрипт подаётся на вход shell:

    docker compose -f deploy/docker-compose.yml --profile dev exec -T -e LOAD_TICKETS=110000 standtools \
        python manage.py shell --no-imports < backend/tests/load/fill_tickets.py
"""
import os
import sys

from django.db import connection, transaction

if os.environ.get("E2E_STAND") != "1":
    sys.exit("Скрипт работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено.")

from apps.core.models import User  # noqa: E402
from apps.org.models import Unit  # noqa: E402
from apps.servicedesk.models import Priority, Queue, Requester, Source, Status, Ticket  # noqa: E402

QUEUE_PREFIX = "Нагрузка очередь"
REQUESTER_DOMAIN = "client.example"
CHUNK = 20_000
# Тексты сообщений: слова, по которым ищет locust (поиск «принтер» и подобные)
PHRASES = [
    "Не печатает принтер в бухгалтерии, пишет об ошибке бумаги",
    "Не открывается почта после смены пароля, прошу помочь",
    "Нужен доступ к общей папке отдела продаж",
    "Компьютер долго загружается и зависает при работе с таблицами",
    "Прошу установить программу для работы с договорами",
    "Пропал интернет в кабинете, сетевой кабель подключён",
    "Не работает телефон на рабочем месте, нет гудка",
    "Замените картридж в принтере на втором этаже",
    "Монитор мигает и выключается, нужна замена",
    "Забыл пароль от учётной записи, нужен сброс",
]
SUBJECTS = ["Принтер", "Почта", "Доступ", "Компьютер", "Программа", "Интернет", "Телефон", "Картридж", "Монитор", "Пароль"]


def name_key(text: str) -> str:
    return " ".join(text.split()).lower().replace("ё", "е")


def make_queue_units(count: int, author: User) -> list:
    """Узлы-очереди `Нагрузка очередь NN` под корнем; недостающие создаются и отмечаются."""
    root = Unit.objects.get(is_root=True)
    units = []
    for number in range(1, count + 1):
        name = f"{QUEUE_PREFIX} {number:02d}"
        unit = Unit.objects.filter(name_key=name_key(name)).first()
        if unit is None:
            unit = Unit.objects.create(name=name, name_key=name_key(name), kind="department", parent=root,
                                       depth=root.depth + 1, path="")
            unit.path = f"{root.path}{unit.pk}/"
            unit.save(update_fields=["path"])
        Queue.objects.get_or_create(unit=unit, defaults={"created_by": author})
        units.append(unit)
    return units


def make_requesters(count: int) -> list:
    have = list(Requester.objects.filter(email__startswith="load-requester-", email__endswith=f"@{REQUESTER_DOMAIN}")
                .order_by("id").values_list("id", flat=True)[:count])
    if len(have) < count:
        Requester.objects.bulk_create([
            Requester(email=f"load-requester-{number:05d}@{REQUESTER_DOMAIN}", full_name=f"Заявитель Нагрузка {number:05d}",
                      origin="ticket") for number in range(len(have) + 1, count + 1)], ignore_conflicts=True)
        have = list(Requester.objects.filter(email__startswith="load-requester-", email__endswith=f"@{REQUESTER_DOMAIN}")
                    .order_by("id").values_list("id", flat=True)[:count])
    return have


TICKET_SQL = """
INSERT INTO servicedesk_ticket (
    number, subject, requester_id, requester_email, requester_name, client_unit_id, category_id, queue_id, priority_id,
    complexity_id, status_id, kind, source_id, assignee_id, assigned_once, created_at, created_by_id, closed_at, closed_by_id,
    resolution, previous_id, consent_at, waiting_since, last_message_at, last_message_from, search, search_len,
    anonymized_at, updated_at)
SELECT s.number,
       (%(subjects)s::text[])[s.subject_ix] || ' ' || s.number,
       r.id, r.email, r.full_name, NULL, NULL,
       (%(queues)s::bigint[])[1 + floor(random() * cardinality(%(queues)s::bigint[]))::int],
       (%(priorities)s::bigint[])[1 + floor(random() * cardinality(%(priorities)s::bigint[]))::int],
       NULL,
       CASE s.kind WHEN 'new' THEN %(new)s::bigint WHEN 'in_progress' THEN %(in_progress)s::bigint
            WHEN 'waiting' THEN %(waiting)s::bigint ELSE %(closed)s::bigint END,
       s.kind, %(source)s::bigint,
       CASE WHEN s.kind <> 'new' AND cardinality(%(people)s::bigint[]) > 0 AND random() < 0.8
            THEN (%(people)s::bigint[])[1 + floor(random() * cardinality(%(people)s::bigint[]))::int] END,
       s.kind <> 'new', s.created_at, NULL,
       CASE WHEN s.kind = 'closed' THEN LEAST(now(), s.created_at + random() * interval '10 days') END,
       CASE WHEN s.kind = 'closed' AND cardinality(%(people)s::bigint[]) > 0
            THEN (%(people)s::bigint[])[1 + floor(random() * cardinality(%(people)s::bigint[]))::int] END,
       CASE WHEN s.kind = 'closed' THEN 'Решено' ELSE '' END, NULL, NULL,
       CASE WHEN s.kind = 'waiting' THEN LEAST(now(), s.created_at + random() * interval '5 days') END,
       LEAST(now(), s.created_at + random() * interval '10 days'),
       CASE WHEN random() < 0.5 THEN 'requester' ELSE 'staff' END, NULL, 0, NULL, now()
FROM (SELECT nextval('servicedesk_ticket_number')::int AS number,
             now() - random() * interval '1095 days' AS created_at,
             1 + floor(random() * %(subject_count)s)::int AS subject_ix,
             1 + floor(random() * %(requester_count)s)::int AS requester_ix,
             CASE WHEN random() < 0.6 THEN 'closed' ELSE (ARRAY['new', 'in_progress', 'waiting'])[1 + floor(random() * 3)::int] END
                 AS kind
      FROM generate_series(1, %(count)s)) AS s
JOIN (SELECT row_number() OVER (ORDER BY id) AS ix, id, email, full_name FROM servicedesk_requester
      WHERE id = ANY(%(requesters)s::bigint[])) AS r ON r.ix = s.requester_ix
"""

ENTRY_SQL = """
INSERT INTO servicedesk_ticketentry (ticket_id, kind, at, author_id, author_email, author_name, text, event, data, wait_flag,
                                     send_state, inbound_id, mail_id, resent_from_id)
SELECT t.id,
       CASE WHEN e.n = 1 THEN 'incoming' WHEN e.n %% 3 = 0 THEN 'comment' ELSE 'reply' END,
       LEAST(now(), t.created_at + (e.n - 1) * interval '6 hours' + random() * interval '1 hour'),
       CASE WHEN e.n = 1 THEN NULL ELSE coalesce(t.assignee_id, (%(people)s::bigint[])[1]) END,
       CASE WHEN e.n = 1 THEN t.requester_email ELSE '' END,
       CASE WHEN e.n = 1 THEN t.requester_name ELSE '' END,
       (%(phrases)s::text[])[1 + (t.number + e.n) %% %(phrase_count)s],
       '', '{}'::jsonb, false, '', NULL, NULL, NULL
FROM servicedesk_ticket t
CROSS JOIN LATERAL generate_series(1, %(per)s + CASE WHEN t.id - %(first)s < %(extra)s THEN 1 ELSE 0 END) AS e(n)
WHERE t.id > %(first)s AND t.id <= %(last)s
"""

SEARCH_SQL = """
UPDATE servicedesk_ticket t
SET search = to_tsvector('russian'::regconfig, concat_ws(' ', t.number::text, t.subject, t.requester_email,
                         translate(t.requester_email, '@._/-', '     '), t.requester_name,
                         (%(phrases)s::text[])[1 + (t.number + 1) %% %(phrase_count)s])),
    search_len = char_length((%(phrases)s::text[])[1 + (t.number + 1) %% %(phrase_count)s])
WHERE t.id > %(first)s AND t.id <= %(last)s
"""

target_tickets = int(os.environ.get("LOAD_TICKETS", "110000"))
target_messages = int(os.environ.get("LOAD_MESSAGES", "550000"))
queue_count = int(os.environ.get("LOAD_QUEUES", "10"))
requester_count = int(os.environ.get("LOAD_REQUESTERS", "2000"))

with transaction.atomic():
    people = list(User.objects.filter(email__startswith="load-", email__endswith="@example.org", state="active")
                  .order_by("email").values_list("id", flat=True)) or list(
        User.objects.filter(state="active").order_by("id").values_list("id", flat=True)[:100])
    if not people:
        sys.exit("Нет действующих сотрудников: сначала prepare_users.py. Ничего не изменено.")
    queue_units = make_queue_units(queue_count, User.objects.get(pk=people[0]))
    requesters = make_requesters(requester_count)
    queue_ids = [unit.pk for unit in queue_units]
    have = Ticket.objects.filter(queue_id__in=queue_ids).count()
    missing = max(target_tickets - have, 0)
    statuses = {kind: Status.objects.filter(kind=kind, archived=False).order_by("order").values_list("id", flat=True).first()
                for kind in ("new", "in_progress", "waiting", "closed")}
    source = Source.objects.filter(system_code="mail").values_list("id", flat=True).get()
    priorities = list(Priority.objects.filter(archived=False).values_list("id", flat=True))
    added_messages = 0
    with connection.cursor() as cursor:
        remaining = missing
        while remaining > 0:
            count = min(CHUNK, remaining)
            cursor.execute("SELECT coalesce(max(id), 0) FROM servicedesk_ticket")
            first = cursor.fetchone()[0]
            cursor.execute(TICKET_SQL, {
                "subjects": SUBJECTS, "subject_count": len(SUBJECTS), "queues": queue_ids, "priorities": priorities,
                "people": people, "requesters": requesters, "requester_count": len(requesters), "count": count,
                "source": source, **statuses})
            cursor.execute("SELECT max(id) FROM servicedesk_ticket")
            last = cursor.fetchone()[0]
            share = max(target_messages * count // max(target_tickets, 1), count)  # сообщений на эту порцию
            per, extra = divmod(share, count)
            cursor.execute(ENTRY_SQL, {"phrases": PHRASES, "phrase_count": len(PHRASES), "per": per, "extra": extra,
                                       "first": first, "last": last, "people": people})
            added_messages += share
            cursor.execute(SEARCH_SQL, {"phrases": PHRASES, "phrase_count": len(PHRASES), "first": first, "last": last})
            remaining -= count

print(f"очередей: {Queue.objects.filter(unit__in=queue_units).count()}, заявок в очередях нагрузки: "
      f"{Ticket.objects.filter(queue_id__in=queue_ids).count()} (добавлено {missing}), сообщений добавлено {added_messages}")
