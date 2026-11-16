"""Чаты и сообщения мессенджера для нагрузочного прогона среза 008 (NFR-701, NFR-707; PLAN-008, «Нагрузка»;
CONTRACT-008, 14.2): добавляет чаты до LOAD_CHATS (по умолчанию 200) и сообщения до LOAD_MESSAGES
(по умолчанию 50000), вложения — долей сообщений.

Распределение участников: 60 % личных чатов (ровно двое, `pair_key` «меньший:больший»), 30 % групповых
(3–12 участников, первый — создатель, `is_creator`), 10 % чатов отдела (по одному на узел структуры стенда,
строк `ChatMember` нет — состав считается службой). «Общий чат» приходит из данных установки и входит
в цель; сообщения получают и он, и чаты отдела. Сообщения размазаны по 2 годам 300 дням — внутри срока
хранения 3 года — и округлены до часа: совпадения времени проверяют курсор истории `(created_at, id)`.
Число сообщений на чат — со скошенным хвостом и нижним порогом 60 (у любого чата есть «Показать более
ранние»); авторы — участники чата, у чатов отдела и общего — первые 100 действующих сотрудников.
Вложения — у 3 % неудалённых сообщений (1–2 файла), у каждого своя строка `StoredFile` назначения
`messenger` в состоянии «чистый»; байты на диск не пишутся — профиль не скачивает наполненные файлы,
а загрузку проверяет живым путём приложения. Цитата (5 %) ссылается на сообщение из предыдущей пачки
того же чата; правка (3 %) ставит `edited_at`; удаление (2 %) — `deleted_at` и пустой текст, как требует
проверка модели. Упоминания — маркеры `@[u<номер>]` в 10 % сообщений групповых, отдельских и общего
чатов и `@[c<номер чата>]` в 2 %; тексты — из словаря настоящих русских слов ИТ-тематики, встроенного
в скрипт (тот же приём, что `fill_feed.py`); без имён, похожих на ПДн, файлов и секретов.
Прочтения — строки `ChatRead` у 60 % участников личных и групповых чатов и у 60 % сотрудников в общем
чате, время — между созданием чата и последним сообщением: у чатов остаются ненулевые числа непрочитанного.

Что делает: создаёт чаты, строки участников, сообщения, вложения и прочтения, пересчитывает векторы
поиска теми же UPDATE, что служба (`search.vectors`), и выставляет `last_message_at` чатов по последнему
сообщению. Повторный запуск добирает до цели: уже созданные строки не меняются и не удаляются, прочтения
не дублируются (уникальность пары чат-сотрудник). Пачки по 250 чатов и сообщений в своей транзакции,
цели и объёмы пачек не строят больших списков в памяти. Работает ТОЛЬКО при E2E_STAND=1 (как
`e2e_reset_stand`); данные убирает следующий сброс приёмки. Каталог tests в образ не входит, поэтому
скрипт подаётся на вход shell:

    docker compose -f deploy/docker-compose.yml --profile dev exec -T -e LOAD_CHATS=200 \
        -e LOAD_MESSAGES=50000 standtools python manage.py shell --no-imports \
        < backend/tests/load/fill_messenger.py

Вывод: `fill_messenger: chats=<число> messages=<число> files=<число>` (в `files` — строки
`MessageAttachment`, то есть вложения сообщений).
"""
import hashlib
import itertools
import os
import random
import sys

if os.environ.get("E2E_STAND") != "1":
    sys.exit("Скрипт работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено.")

from datetime import timedelta  # noqa: E402

from django.db import transaction  # noqa: E402
from django.db.models import Max, OuterRef, Subquery  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.core.models import StoredFile, User  # noqa: E402
from apps.messenger.models import (Chat, ChatMember, ChatRead, Message,  # noqa: E402
                                   MessageAttachment)
from apps.messenger.services import search  # noqa: E402

CHUNK = 250                  # чатов или сообщений в одной пачке (как fill_feed.py)
FLUSH = 2000                 # строк прочтений в одной пачке
CHATS_LIMIT = 2000           # безопасные границы целей из окружения
MESSAGES_LIMIT = 1000000
SPREAD_DAYS = 2 * 365 + 300   # чаты и сообщения за два года 300 дней — внутри срока хранения 3 года
MESSAGE_CAP = 2000           # хвост числа сообщений на чат
MESSAGE_FLOOR = 60           # у любого чата есть вторая страница истории (курсор)
GROUP_MEMBERS = (3, 12)      # участников группового чата, включая создателя
FILE_SHARE = 0.03            # доля неудалённых сообщений с вложениями
FILE_COUNT = (1, 2)          # вложений у такого сообщения
QUOTE_SHARE = 0.05           # цитата на сообщение предыдущей пачки своего чата
EDIT_SHARE = 0.03            # правленых сообщений
DELETE_SHARE = 0.02          # удалённых сообщений
MENTION_SHARE = 0.10         # маркеры `@[u<номер>]` в сообщении
CHAT_MENTION_SHARE = 0.02    # маркер `@[c<номер чата>]` в сообщении
READ_SHARE = 0.60            # доля участников со строкой прочтения
KIND_SHARES = (("personal", 60), ("group", 30), ("department", 10))
WORDS = (
    "сообщение беседа чат участник вложение файл прочтение уведомление упоминание цитата правка удаление "
    "принтер картридж бумага сканер монитор клавиатура мышь ноутбук компьютер сервер сеть кабель роутер "
    "коммутатор интернет почта письмо пароль логин учётная запись доступ права папка документ диск резервная "
    "копия восстановление программа установка обновление лицензия антивирус вирус защита шифрование "
    "сертификат подпись токен телефон гарнитура камера видеосвязь собрание календарь проектор экран розетка "
    "питание аккумулятор зарядка драйвер система настройка параметр профиль пользователь сотрудник отдел "
    "заявка обращение инструкция регламент порядок процедура проверка ошибка сбой отказ перезагрузка память "
    "процессор температура вентилятор договор поставка гарантия ремонт склад кабинет этаж здание номер тариф "
    "оператор карта носитель"
).split()


def phrase(rng: random.Random, low: int = 1, high: int = 4) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(rng.randint(low, high)))


def make_text(rng: random.Random) -> str:
    return " ".join(phrase(rng, 4, 9).capitalize() + "." for _ in range(rng.randint(1, 3)))


def _target(name: str, default: int, high: int) -> int:
    """Цель из окружения; не целое число или вне безопасных границ — отказ до любого изменения."""
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        sys.exit(f"{name} — не целое число: {raw!r}; ничего не изменено.")
    if not 1 <= value <= high:
        sys.exit(f"{name} вне пределов от 1 до {high}: {value}; ничего не изменено.")
    return value


def _spread(counts: list[int], missing: int, cap: int, rng: random.Random) -> int:
    """Подогнать сумму счётчиков под `missing`, не выходя за `cap`; возвращает достижимую цель."""
    missing = min(missing, cap * len(counts))
    total = sum(counts)
    while total != missing:
        index = rng.randrange(len(counts))
        if total > missing and counts[index] > 0:
            counts[index] -= 1
            total -= 1
        elif total < missing and counts[index] < cap:
            counts[index] += 1
            total += 1
    return missing


rng = random.Random(20261116)
chats_target = _target("LOAD_CHATS", 200, CHATS_LIMIT)
messages_target = _target("LOAD_MESSAGES", 50000, MESSAGES_LIMIT)
people = list(User.objects.filter(state="active").order_by("pk").values_list("pk", flat=True)[:100])
if len(people) < 2:
    sys.exit("Нет действующих сотрудников: сначала подготовьте учётные записи; ничего не изменено.")
units: list[int] = []
try:
    from apps.org.services import structure

    units = [unit.id for unit in structure.all_units()]
except Exception:  # noqa: BLE001 — без структуры подразделений доля чатов отдела уходит групповым
    pass
now = timezone.now()
max_people = max(1, len(people))
kind_pool = tuple(kind for kind, share in KIND_SHARES for _ in range(share))


def _chat_created() -> object:
    """Время создания чата: за два года 300 дней, округлено до часа."""
    return (now - timedelta(days=rng.randint(0, SPREAD_DAYS), hours=rng.randrange(24))
            ).replace(minute=0, second=0, microsecond=0)


def _build_chat(kind: str, pairs: list, units_left: list) -> tuple[Chat, list[ChatMember]]:
    """Чат выбранного вида и строки участников; у чата отдела и общего строк участников нет."""
    created = _chat_created()
    if kind == "personal":
        first, second = pairs.pop()
        low, high = sorted((first, second))
        chat = Chat(kind=kind, title="", pair_key=f"{low}:{high}", created_by_id=first, created_at=created)
        return chat, [ChatMember(chat=chat, user_id=low, is_creator=low == first, joined_at=created),
                      ChatMember(chat=chat, user_id=high, is_creator=high == first, joined_at=created)]
    if kind == "department":
        return (Chat(kind=kind, title="", unit_id=units_left.pop(), created_by=None, created_at=created), [])
    size = rng.randint(min(GROUP_MEMBERS[0], max_people), min(GROUP_MEMBERS[1], max_people))
    chosen = rng.sample(people, size)
    chat = Chat(kind="group", title=f"Группа {phrase(rng, 1, 3).capitalize()}"[:200],
                created_by_id=chosen[0], created_at=created)
    return chat, [ChatMember(chat=chat, user_id=user_id, is_creator=user_id == chosen[0], joined_at=created)
                  for user_id in chosen]


def _create_chats(missing: int) -> None:
    """Пачки чатов со строками участников; занятые пары сотрудников и узлы не повторяются."""
    used_pairs = set(Chat.objects.filter(kind="personal").values_list("pair_key", flat=True))
    pairs = [pair for pair in itertools.combinations(people, 2) if f"{pair[0]}:{pair[1]}" not in used_pairs]
    rng.shuffle(pairs)
    used_units = set(Chat.objects.filter(kind="department").values_list("unit_id", flat=True))
    units_left = [unit for unit in units if unit not in used_units]
    rng.shuffle(units_left)
    made = 0
    while made < missing:
        chats: list[Chat] = []
        members: list[ChatMember] = []
        for _ in range(min(CHUNK, missing - made)):
            kind = rng.choice(kind_pool)
            if kind == "personal" and not pairs:
                kind = "group"
            if kind == "department" and not units_left:
                kind = "group"
            chat, rows = _build_chat(kind, pairs, units_left)
            chats.append(chat)
            members.extend(rows)
        with transaction.atomic():
            Chat.objects.bulk_create(chats)
            if members:
                ChatMember.objects.bulk_create(members)
        made += len(chats)


def _authors(chat_id: int, kind: str) -> list[int]:
    """Авторы сообщений: участники чата, у чатов отдела и общего — первые действующие сотрудники."""
    if kind in ("personal", "group"):
        ids = list(ChatMember.objects.filter(chat_id=chat_id, left_at__isnull=True)
                   .order_by("user_id").values_list("user_id", flat=True))
        return ids or people
    return people


def _text(kind: str, others: list[int]) -> str:
    """Текст сообщения с маркерами упоминаний; в личном чате подсказки «@» нет — маркеров тоже."""
    text = make_text(rng)
    if kind != "personal" and rng.random() < MENTION_SHARE:
        size = rng.randint(1, min(3, max_people))
        text += " " + " ".join(f"@[u{user_id}]" for user_id in rng.sample(people, size))
    if kind != "personal" and others and rng.random() < CHAT_MENTION_SHARE:
        text += f" @[c{rng.choice(others)}]"
    return text


def _attachments(buffer: list[Message], attached: list[bool]) -> None:
    """Строки `StoredFile` и `MessageAttachment` для отмеченных сообщений; байты на диск не пишутся."""
    rows, stored_rows = [], []
    for message, flag in zip(buffer, attached):
        if not flag:
            continue
        for number in range(rng.randint(*FILE_COUNT)):
            name = f"нагрузка-{message.pk}-{number}.csv"
            payload = (f"нагрузка {message.pk} {number}\n" * 32).encode("utf-8")
            stored = StoredFile(purpose="messenger", owner_id=message.author_id, size=len(payload),
                                sha256=hashlib.sha256(payload).hexdigest(), content_type="text/csv",
                                status=StoredFile.Status.CLEAN, scanned_at=message.created_at,
                                created_at=message.created_at)
            stored_rows.append(stored)
            rows.append((stored, message, name))
    if not stored_rows:
        return
    StoredFile.objects.bulk_create(stored_rows)
    MessageAttachment.objects.bulk_create(
        [MessageAttachment(message_id=message.pk, file_id=stored.pk, name=name,
                           uploaded_by_id=stored.owner_id, uploaded_at=message.created_at)
         for stored, message, name in rows])


def _flush_messages(buffer: list[Message], attached: list[bool]) -> list[int]:
    """Пачка сообщений: ядро, вложения, векторы поиска теми же UPDATE, что служба; буферы опустошаются."""
    if not buffer:
        return []
    with transaction.atomic():
        Message.objects.bulk_create(buffer)
        _attachments(buffer, attached)
        search.vectors(message_ids=[message.pk for message in buffer])
        ids = [message.pk for message in buffer]
    buffer.clear()
    attached.clear()
    return ids


def _create_messages(missing: int) -> None:
    """Сообщения по счётчикам со скошенным хвостом; цитата — на сообщение предыдущей пачки своего чата."""
    if missing <= 0:
        return
    rows = list(Chat.objects.order_by("pk").values_list("pk", "created_at", "kind"))
    if not rows:
        return
    cap = max(MESSAGE_CAP, -(-missing // len(rows)))
    mean = max(1.0, missing / len(rows))
    counts = [max(MESSAGE_FLOOR, min(cap, int(rng.expovariate(1 / mean)))) for _ in rows]
    _spread(counts, missing, cap, rng)
    chat_ids = [row[0] for row in rows]
    for (chat_id, created, kind), count in zip(rows, counts):
        if not count:
            continue
        authors = _authors(chat_id, kind)
        others = [value for value in chat_ids if value != chat_id]
        recent: list[int] = []   # номера сообщений предыдущих пачек этого чата — для цитат
        buffer: list[Message] = []
        attached: list[bool] = []
        span = max(1, int((now - created).total_seconds() // 3600))
        for _ in range(count):
            created_at = created + timedelta(hours=rng.randrange(span))
            deleted = rng.random() < DELETE_SHARE
            message = Message(chat_id=chat_id, author_id=rng.choice(authors), created_at=created_at,
                              text="" if deleted else _text(kind, others))
            if deleted:
                message.deleted_at = min(now, created_at + timedelta(minutes=rng.randint(1, 600)))
            elif rng.random() < EDIT_SHARE:
                message.edited_at = min(now, created_at + timedelta(minutes=rng.randint(1, 240)))
            if recent and not deleted and rng.random() < QUOTE_SHARE:
                message.quote_id = rng.choice(recent)
            buffer.append(message)
            attached.append(not deleted and rng.random() < FILE_SHARE)
            if len(buffer) >= CHUNK:
                recent.extend(_flush_messages(buffer, attached))
                recent = recent[-5:]
        _flush_messages(buffer, attached)


def _create_reads() -> None:
    """Прочтения: у 60 % участников личных и групповых чатов и у 60 % сотрудников в общем чате.

    Время — между созданием чата и последним сообщением, поэтому у чатов остаются ненулевые числа
    непрочитанного. У чатов отдела строк прочтения нет: состав считается службой, отметок не ставим.
    Повторный запуск ничего не дублирует — пара чат-сотрудник уникальна.
    """
    buffer: list[ChatRead] = []
    for chat_id, kind, created in Chat.objects.order_by("pk").values_list("pk", "kind", "created_at"):
        if kind == "department":
            continue
        last = (Message.objects.filter(chat_id=chat_id).order_by("-created_at")
                .values_list("created_at", flat=True).first())
        if last is None:
            continue
        if kind in ("personal", "group"):
            members = list(ChatMember.objects.filter(chat_id=chat_id, left_at__isnull=True)
                           .values_list("user_id", flat=True))
        else:
            members = people
        span = max(1, int((last - created).total_seconds()))
        for user_id in members:
            if rng.random() >= READ_SHARE:
                continue
            buffer.append(ChatRead(chat_id=chat_id, user_id=user_id,
                                   last_read_at=created + timedelta(seconds=rng.randrange(span))))
            if len(buffer) >= FLUSH:
                _flush_reads(buffer)
    _flush_reads(buffer)


def _flush_reads(buffer: list[ChatRead]) -> None:
    if not buffer:
        return
    with transaction.atomic():
        ChatRead.objects.bulk_create(buffer, ignore_conflicts=True)
    buffer.clear()


def _set_last_message_at() -> None:
    """`last_message_at` чатов по последнему сообщению — одним UPDATE с подзапросом."""
    last = (Message.objects.filter(chat_id=OuterRef("pk")).order_by().values("chat_id")
            .annotate(last=Max("created_at")).values("last"))
    Chat.objects.update(last_message_at=Subquery(last))


Chat.objects.get_or_create(kind=Chat.Kind.GENERAL, defaults={"title": "Общий чат"})
_create_chats(max(0, chats_target - Chat.objects.count()))
_create_messages(max(0, messages_target - Message.objects.count()))
_set_last_message_at()
_create_reads()
print(f"fill_messenger: chats={Chat.objects.count()} messages={Message.objects.count()} "
      f"files={MessageAttachment.objects.count()}")