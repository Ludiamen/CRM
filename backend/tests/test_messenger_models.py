"""T-8102: модели и миграции мессенджера (FR-643, FR-645…FR-651, FR-654, FR-657…FR-660, FR-662, FR-668, FR-670).

План: «Модель данных» → «Приложение `messenger`», «Ядро и прежние модули», «Где живёт код»; CONTRACT-008: 1.4, 2.1,
2.2, 2.3, 5.7. Модели импортируются внутри тестов (`support.model("messenger.Chat")`): сбор (`pytest --collect-only`)
проходит до появления кода среза. Каждое ограничение проверяется дважды — по имени в `Meta.constraints`/`Meta.indexes`
и поведением базы `IntegrityError` в `transaction.atomic()` (как в `test_feed_likes.py`); тест не ослабляется до
`ValidationError` Django. Службы среза не нужны: строки создают помощники `support_messenger` и менеджеры моделей.
"""
import importlib
from types import SimpleNamespace

import pytest
from django.db import IntegrityError, models, transaction
from django.db.models import (
    BooleanField,
    CharField,
    CheckConstraint,
    DateTimeField,
    Index,
    PositiveIntegerField,
    PositiveSmallIntegerField,
    Q,
    TextField,
    UniqueConstraint,
)
from django.utils import timezone

from tests import support
from tests import support_messenger as sm

pytestmark = pytest.mark.django_db


# --- разбор модели (помощники только этого файла) ---------------------------------------------------------------

def _field(model, name):
    return model._meta.get_field(name)


def _constraint(model, name):
    """Ограничение модели по имени; при отсутствии — имена того, что объявлено (без ослабления до «хоть что-нибудь»)."""
    found = [item for item in model._meta.constraints if item.name == name]
    assert found, f"нет ограничения {name!r}: {sorted(item.name for item in model._meta.constraints)}"
    return found[0]


def _index(model, name):
    found = [item for item in model._meta.indexes if item.name == name]
    assert found, f"нет индекса {name!r}: {sorted(item.name for item in model._meta.indexes)}"
    index = found[0]
    assert isinstance(index, Index)
    return index


def _unit(pk: int, name: str) -> SimpleNamespace:
    """Узел `org` на время теста: чату отдела нужен только номер и название, модель `org.Unit` не импортируется."""
    return SimpleNamespace(pk=pk, name=name)


# --- FR-643, 645, 646, 649, 650, 651: виды чатов, проверки, один «Общий чат» -------------------------------------

def test_chat_kind_checks_title_unit_pair_key_and_general_single_row():
    """FR-643, FR-645, FR-646, FR-649, FR-650, FR-651 (CONTRACT-008, 2.2): четыре вида чата с подписями плана;
    `title` — 200 и пусто у личного и чата отдела, `unit_id` — число без внешнего ключа, `pair_key` — 32; проверки
    `messenger_chat_title_chk`, `messenger_chat_unit_chk`, `messenger_chat_pair_chk` держат базу: группа без названия
    невозможна, личный без `pair_key` — тоже, чат отдела без `unit_id` — тоже, а `unit_id` и `pair_key` у прочих видов
    пусты; «Общий чат» — одна строка, созданная миграцией. Индексы списка — по последнему сообщению и создателю."""
    Chat = support.model("messenger.Chat")
    now = timezone.now()

    assert tuple(Chat.Kind.values) == sm.CHAT_KINDS
    kind = _field(Chat, "kind")
    assert isinstance(kind, CharField) and kind.max_length == 16
    assert dict(kind.choices) == {"personal": "Личный", "group": "Групповой",
                                  "department": "Чат отдела", "general": "Общий чат"}
    title = _field(Chat, "title")
    assert isinstance(title, CharField) and title.max_length == 200
    assert title.blank and title.default == ""
    unit_id = _field(Chat, "unit_id")
    assert isinstance(unit_id, PositiveIntegerField) and unit_id.null and unit_id.blank
    assert not unit_id.is_relation, "unit_id — число: модель org.Unit не импортируется (FR-650)"
    pair_key = _field(Chat, "pair_key")
    assert isinstance(pair_key, CharField) and pair_key.max_length == 32
    assert pair_key.blank and pair_key.default == ""
    created_by = _field(Chat, "created_by")
    assert created_by.remote_field.model._meta.label == "core.User"
    assert created_by.remote_field.on_delete is models.PROTECT
    assert created_by.null and created_by.blank
    created_at = _field(Chat, "created_at")
    assert isinstance(created_at, DateTimeField) and not created_at.auto_now_add
    last_message_at = _field(Chat, "last_message_at")
    assert isinstance(last_message_at, DateTimeField) and last_message_at.null and last_message_at.blank

    for name in ("messenger_chat_title_chk", "messenger_chat_unit_chk", "messenger_chat_pair_chk"):
        constraint = _constraint(Chat, name)
        assert isinstance(constraint, CheckConstraint), f"{name}: не CheckConstraint"
        assert constraint.condition is not None
    assert tuple(_index(Chat, "messenger_chat_last_msg_idx").fields) == ("-last_message_at", "-id")
    assert tuple(_index(Chat, "messenger_chat_created_by_idx").fields) == ("created_by",)

    creator, peer = support.make_employee(), support.make_employee()
    group_chat = sm.group(creator, [peer], title="Переезд серверной")
    assert (group_chat.kind, group_chat.title) == ("group", "Переезд серверной")
    with pytest.raises(IntegrityError), transaction.atomic():
        Chat.objects.create(kind="group", title="", created_at=now)

    personal = sm.personal(creator, peer)
    assert (personal.kind, personal.title) == ("personal", "")
    with pytest.raises(IntegrityError), transaction.atomic():
        Chat.objects.create(kind="personal", created_at=now)

    department = sm.department_chat(_unit(9041, "Сеть"))
    assert (department.kind, department.title, department.unit_id) == ("department", "", 9041)
    with pytest.raises(IntegrityError), transaction.atomic():
        Chat.objects.create(kind="department", title="", created_at=now)

    with pytest.raises(IntegrityError), transaction.atomic():
        Chat.objects.create(kind="personal", pair_key=f"{creator.pk}:{peer.pk}", unit_id=9041, created_at=now)
    with pytest.raises(IntegrityError), transaction.atomic():
        Chat.objects.create(kind="group", title="Группа", pair_key=f"{creator.pk}:{peer.pk}", created_at=now)

    general = sm.general()
    assert general.kind == "general"
    assert general.created_by_id is None, "у «Общего чата» создателя нет"
    assert Chat.objects.filter(kind="general").count() == 1
    assert sm.general().pk == general.pk, "«Общий чат» один: повтор возвращает ту же строку"
    with pytest.raises(IntegrityError), transaction.atomic():
        Chat.objects.create(kind="general", title="Общий чат", created_at=now)


# --- FR-645: личный диалог один на пару ------------------------------------------------------------------------

def test_personal_pair_key_unique_partial_and_duplicate_raises():
    """FR-645 (CONTRACT-008, 2.2): `pair_key` — «<меньший id>:<больший id>», уникальность частичная (`WHERE
    kind='personal'`): второй личный диалог той же пары отвергается базой, а неличные чаты с пустым `pair_key`
    (групповые, отдельские, «Общий чат») друг другу не мешают; повторный `personal` возвращает тот же чат."""
    Chat = support.model("messenger.Chat")
    constraint = _constraint(Chat, "messenger_chat_pair_uniq")
    assert isinstance(constraint, UniqueConstraint)
    assert tuple(constraint.fields) == ("pair_key",)
    assert constraint.condition == Q(kind="personal"), "уникальность pair_key — только у личных"

    first, second = support.make_employee(), support.make_employee()
    low, high = sorted((first.pk, second.pk))
    chat = sm.personal(first, second)
    assert (chat.kind, chat.pair_key) == ("personal", f"{low}:{high}")
    assert sm.personal(second, first).pk == chat.pk, "личный диалог один на пару"
    with pytest.raises(IntegrityError), transaction.atomic():
        Chat.objects.create(kind="personal", pair_key=chat.pair_key, created_at=timezone.now())

    creator = support.make_employee()
    sm.group(creator, [], title="Первая")
    sm.group(creator, [], title="Вторая")
    sm.department_chat(_unit(9042, "Сеть"))
    sm.department_chat(_unit(9043, "Серверы"))
    assert Chat.objects.filter(kind__in=["group", "department"], pair_key="").count() == 4, \
        "частичный индекс: пустой pair_key у неличных чатов не уникален"
    sm.general()
    assert Chat.objects.filter(kind="general", pair_key="").count() == 1


# --- FR-650, 651: чат отдела и «Общий чат» — по одной строке ---------------------------------------------------

def test_department_unit_unique_and_general_unique_constraints():
    """FR-650, FR-651 (CONTRACT-008, 2.2): `UniqueConstraint(unit_id) WHERE kind='department'` — у узла один чат
    отдела (второй отвергается базой, другой узел можно); `UniqueConstraint(kind) WHERE kind='general'` — «Общий чат»
    один; у чата отдела название пусто (его даёт узел), `unit_id` заполнен."""
    Chat = support.model("messenger.Chat")

    unit_constraint = _constraint(Chat, "messenger_chat_unit_uniq")
    assert isinstance(unit_constraint, UniqueConstraint)
    assert tuple(unit_constraint.fields) == ("unit_id",)
    assert unit_constraint.condition == Q(kind="department"), "уникальность unit_id — только у чата отдела"
    general_constraint = _constraint(Chat, "messenger_chat_general_uniq")
    assert isinstance(general_constraint, UniqueConstraint)
    assert tuple(general_constraint.fields) == ("kind",)
    assert general_constraint.condition == Q(kind="general"), "уникальность вида — только у «Общего чата»"

    chat = sm.department_chat(_unit(9044, "Сеть"))
    assert (chat.kind, chat.unit_id, chat.title, chat.pair_key) == ("department", 9044, "", "")
    with pytest.raises(IntegrityError), transaction.atomic():
        Chat.objects.create(kind="department", title="", unit_id=9044, created_at=timezone.now())
    sm.department_chat(_unit(9045, "Серверы"))
    assert Chat.objects.filter(kind="department", unit_id=9045).count() == 1

    general = sm.general()
    assert general.created_by_id is None
    with pytest.raises(IntegrityError), transaction.atomic():
        Chat.objects.create(kind="general", title="Общий чат", created_at=timezone.now())
    assert Chat.objects.filter(kind="general").count() == 1


# --- FR-646, 647: участники чата -------------------------------------------------------------------------------

def test_chat_member_unique_chat_user_and_partial_active_index():
    """FR-646, FR-647 (CONTRACT-008, 2.2): строка участника одна на пару «чат, сотрудник» — уникальность полная,
    поэтому вышедший не возвращается новой строкой (его `left_at`), а состав ведут `is_creator`/`joined_at`/`left_at`;
    частичный индекс `messenger_chatmember_user_idx` (`user`, `chat`) — только по действующим (`left_at IS NULL`);
    строки чата удаляются вместе с чатом, сотрудник с участием не удаляется (`PROTECT`)."""
    Chat, ChatMember = support.model("messenger.Chat"), support.model("messenger.ChatMember")

    constraint = _constraint(ChatMember, "messenger_chatmember_uniq")
    assert isinstance(constraint, UniqueConstraint)
    assert tuple(constraint.fields) == ("chat", "user")
    assert constraint.condition is None, "уникальность участника — и после выхода"
    index = _index(ChatMember, "messenger_chatmember_user_idx")
    assert tuple(index.fields) == ("user", "chat")
    assert index.condition == Q(left_at__isnull=True), "индекс — по действующим участникам"

    chat_field = _field(ChatMember, "chat")
    assert chat_field.remote_field.model is Chat and chat_field.remote_field.on_delete is models.CASCADE
    assert chat_field.remote_field.related_name == "members"
    user_field = _field(ChatMember, "user")
    assert user_field.remote_field.model._meta.label == "core.User"
    assert user_field.remote_field.on_delete is models.PROTECT
    is_creator = _field(ChatMember, "is_creator")
    assert isinstance(is_creator, BooleanField) and is_creator.default is False
    assert isinstance(_field(ChatMember, "joined_at"), DateTimeField)
    left_at = _field(ChatMember, "left_at")
    assert isinstance(left_at, DateTimeField) and left_at.null and left_at.blank

    creator, member = support.make_employee(), support.make_employee()
    chat = sm.group(creator, [member])
    assert ChatMember.objects.filter(chat=chat).count() == 2
    assert ChatMember.objects.get(chat=chat, user=creator).is_creator is True
    with pytest.raises(IntegrityError), transaction.atomic():
        ChatMember.objects.create(chat=chat, user=member, joined_at=timezone.now())

    ChatMember.objects.filter(chat=chat, user=member).update(left_at=timezone.now())
    with pytest.raises(IntegrityError), transaction.atomic():
        ChatMember.objects.create(chat=chat, user=member, joined_at=timezone.now())

    with pytest.raises(models.ProtectedError):
        member.delete()
    assert ChatMember.objects.filter(chat=chat, user=member).exists()
    Chat.objects.filter(pk=chat.pk).delete()
    assert ChatMember.objects.filter(chat_id=chat.pk).count() == 0, "участники удаляются вместе с чатом"


# --- FR-659, 660: отметки прочтения ----------------------------------------------------------------------------

def test_chat_read_unique_chat_user_and_index_for_counts():
    """FR-659, FR-660 (CONTRACT-008, 2.2): отметка прочтения — одна строка на пару «чат, сотрудник» (повтор
    обновляет её, а не добавляет), индекс `messenger_chatread_user_idx` (`user`, `chat`) без условия — числа в списке
    считаются по действующим и недействующим; отметки удаляются вместе с чатом и вместе с сотрудником
    (`CASCADE`), поля `last_read_at` в `ChatMember` нет."""
    Chat, ChatRead, ChatMember = (support.model("messenger.Chat"), support.model("messenger.ChatRead"),
                                  support.model("messenger.ChatMember"))

    constraint = _constraint(ChatRead, "messenger_chatread_uniq")
    assert isinstance(constraint, UniqueConstraint)
    assert tuple(constraint.fields) == ("chat", "user")
    assert constraint.condition is None
    index = _index(ChatRead, "messenger_chatread_user_idx")
    assert tuple(index.fields) == ("user", "chat")
    assert index.condition is None, "индекс чисел — без условия: считаются все отметки"

    chat_field = _field(ChatRead, "chat")
    assert chat_field.remote_field.model is Chat and chat_field.remote_field.on_delete is models.CASCADE
    assert chat_field.remote_field.related_name == "reads"
    user_field = _field(ChatRead, "user")
    assert user_field.remote_field.model._meta.label == "core.User"
    assert user_field.remote_field.on_delete is models.CASCADE
    assert isinstance(_field(ChatRead, "last_read_at"), DateTimeField)
    assert not hasattr(ChatMember, "last_read_at"), "отметка живёт в ChatRead, а не в ChatMember"

    first, second = support.make_employee(), support.make_employee()
    chat = sm.personal(first, second)
    now = timezone.now()
    row = sm.read(chat, first, now)
    assert sm.read(chat, first, now).pk == row.pk
    with pytest.raises(IntegrityError), transaction.atomic():
        ChatRead.objects.create(chat=chat, user=first, last_read_at=now)
    sm.read(chat, second, now)
    assert ChatRead.objects.filter(chat=chat).count() == 2

    reader = support.make_employee()
    reader_pk = reader.pk
    sm.read(chat, reader, now)
    reader.delete()
    assert ChatRead.objects.filter(user_id=reader_pk).count() == 0, "отметки уходят вместе с сотрудником"
    Chat.objects.filter(pk=chat.pk).delete()
    assert ChatRead.objects.filter(chat_id=chat.pk).count() == 0, "отметки уходят вместе с чатом"


# --- FR-649, 657: системное и удалённое сообщение --------------------------------------------------------------

def test_message_system_requires_no_author_and_deleted_requires_empty_text():
    """FR-649, FR-657 (CONTRACT-008, 2.2): системная запись — только без автора, а сообщение без автора — только
    системное (`messenger_message_system_chk`); удалённое сообщение хранит пустой текст (`messenger_message_deleted_chk`)
    — текст и файлы недоступны, «Сообщение удалено» рисует шаблон; текст хранится как есть (пробелы, табы, переносы);
    автор с сообщениями не удаляется (`PROTECT`)."""
    Chat, Message = support.model("messenger.Chat"), support.model("messenger.Message")

    for name in ("messenger_message_system_chk", "messenger_message_deleted_chk"):
        constraint = _constraint(Message, name)
        assert isinstance(constraint, CheckConstraint), f"{name}: не CheckConstraint"
        assert constraint.condition is not None
    text = _field(Message, "text")
    assert isinstance(text, TextField), "текст — TextField: до 4 000 знаков проверяет служба (FR-652)"
    assert text.max_length is None, "предел 4 000 знаков держит служба (FR-652), а не база"
    assert text.blank and text.default == ""
    is_system = _field(Message, "is_system")
    assert isinstance(is_system, BooleanField) and is_system.default is False
    author = _field(Message, "author")
    assert author.remote_field.model._meta.label == "core.User"
    assert author.remote_field.on_delete is models.PROTECT
    assert author.null and author.blank
    assert isinstance(_field(Message, "created_at"), DateTimeField)
    for name in ("edited_at", "deleted_at"):
        field = _field(Message, name)
        assert isinstance(field, DateTimeField) and field.null and field.blank

    creator = support.make_employee()
    chat = sm.group(creator, [])
    now = timezone.now()
    body = "Первая строка\n  вторая\tстрока  "
    message = Message.objects.create(chat=chat, author=creator, text=body, created_at=now)
    message.refresh_from_db()
    assert message.text == body, "текст хранится как есть"
    assert (message.is_system, message.edited_at, message.deleted_at) == (False, None, None)

    system = Message.objects.create(chat=chat, author=None, is_system=True,
                                    text="К чату присоединились сотрудники отдела «Сеть»", created_at=now)
    assert (system.author_id, system.is_system) == (None, True)
    with pytest.raises(IntegrityError), transaction.atomic():
        Message.objects.create(chat=chat, author=creator, is_system=True, text="Системная с автором", created_at=now)
    with pytest.raises(IntegrityError), transaction.atomic():
        Message.objects.create(chat=chat, author=None, is_system=False, text="Без автора", created_at=now)

    with pytest.raises(IntegrityError), transaction.atomic():
        Message.objects.create(chat=chat, author=creator, text="Ещё видно", deleted_at=now, created_at=now)
    deleted = Message.objects.create(chat=chat, author=creator, text="", deleted_at=now, created_at=now)
    assert (deleted.text, deleted.deleted_at is not None) == ("", True)

    outsider = support.make_employee()
    Message.objects.create(chat=chat, author=outsider, text="Чужое сообщение", created_at=now)
    with pytest.raises(models.ProtectedError):
        outsider.delete()
    assert Message.objects.filter(author_id=outsider.pk).count() == 1


# --- FR-654, 658, 668: цитата, индексы истории и поиска ---------------------------------------------------------

def test_message_quote_set_null_and_indexes_chat_created_search_gin():
    """FR-654, FR-658, FR-668 (CONTRACT-008, 2.2): `quote` — ссылка на сообщение того же чата (`SET_NULL`): удаление
    исходного не уносит ответ; история — индекс `messenger_message_chat_idx` (`chat`, `-created_at`, `-id`), ночное
    задание срока — `messenger_message_created_idx` (`created_at`), сквозной поиск — `GIN` по `search` с
    `SearchVectorField(null=True)`; сообщения удаляются вместе с чатом (`CASCADE`)."""
    Chat, Message = support.model("messenger.Chat"), support.model("messenger.Message")

    assert tuple(_index(Message, "messenger_message_chat_idx").fields) == ("chat", "-created_at", "-id")
    assert tuple(_index(Message, "messenger_message_created_idx").fields) == ("created_at",)
    from django.contrib.postgres.indexes import GinIndex

    gin = _index(Message, "messenger_message_search_gin")
    assert isinstance(gin, GinIndex), "поиск — GIN, а не обычный индекс"
    assert tuple(gin.fields) == ("search",)
    from django.contrib.postgres.search import SearchVectorField

    search = _field(Message, "search")
    assert isinstance(search, SearchVectorField) and search.null

    quote = _field(Message, "quote")
    assert quote.remote_field.model is Message, "цитата — сообщение того же вида"
    assert quote.remote_field.on_delete is models.SET_NULL
    assert quote.remote_field.related_name == "+", "обратной связи у цитаты нет: цепочка — один уровень"
    assert quote.null and quote.blank
    chat_field = _field(Message, "chat")
    assert chat_field.remote_field.model is Chat and chat_field.remote_field.on_delete is models.CASCADE
    assert chat_field.remote_field.related_name == "messages"

    first, second = support.make_employee(), support.make_employee()
    chat = sm.group(first, [second])
    now = timezone.now()
    question = Message.objects.create(chat=chat, author=first, text="Возьмите ключи", created_at=now)
    answer = Message.objects.create(chat=chat, author=second, text="Возьму", quote=question, created_at=now)
    assert answer.quote_id == question.pk
    question.delete()
    answer.refresh_from_db()
    assert answer.quote_id is None, "удаление исходного обнуляет цитату, ответ остаётся"

    Chat.objects.filter(pk=chat.pk).delete()
    assert Message.objects.filter(chat_id=chat.pk).count() == 0, "сообщения уходят вместе с чатом"


# --- FR-662: вложения ------------------------------------------------------------------------------------------

def test_message_attachment_unbound_partial_index_and_protect_on_stored_file():
    """FR-662 (CONTRACT-008, 2.2): вложение — строка `MessageAttachment` с назначением файла ядра `messenger`; пока
    файл не привязан, `message` пусто, и таких строк у сотрудника может быть много (частичный индекс
    `messenger_attach_unbound_idx` по `uploaded_by`, `uploaded_at`), привязанные ищутся индексом
    `messenger_attach_message_idx`; один файл — одно вложение; файл `StoredFile` и загрузивший не удаляются
    (`PROTECT`), а вложение уходит вместе с сообщением (`CASCADE`), строка файла остаётся."""
    Message, MessageAttachment = support.model("messenger.Message"), support.model("messenger.MessageAttachment")
    StoredFile = support.model("core.StoredFile")

    assert tuple(_index(MessageAttachment, "messenger_attach_message_idx").fields) == ("message",)
    unbound = _index(MessageAttachment, "messenger_attach_unbound_idx")
    assert tuple(unbound.fields) == ("uploaded_by", "uploaded_at")
    assert unbound.condition == Q(message__isnull=True), "индекс — только по непривязанным файлам"

    message_field = _field(MessageAttachment, "message")
    assert message_field.remote_field.model is Message
    assert message_field.remote_field.on_delete is models.CASCADE
    assert message_field.remote_field.related_name == "files"
    assert message_field.null and message_field.blank
    file_field = _field(MessageAttachment, "file")
    assert file_field.one_to_one and file_field.remote_field.on_delete is models.PROTECT
    assert file_field.remote_field.related_name == "+"
    assert file_field.remote_field.model._meta.label == "core.StoredFile"
    name = _field(MessageAttachment, "name")
    assert isinstance(name, CharField) and name.max_length == 255
    thumb = _field(MessageAttachment, "thumb")
    assert isinstance(thumb, CharField) and thumb.max_length == 255
    assert thumb.blank and thumb.default == ""
    uploader = _field(MessageAttachment, "uploaded_by")
    assert uploader.remote_field.model._meta.label == "core.User"
    assert uploader.remote_field.on_delete is models.PROTECT
    assert isinstance(_field(MessageAttachment, "uploaded_at"), DateTimeField)

    creator, uploader_user = support.make_employee(), support.make_employee()
    chat = sm.group(creator, [])
    first = sm.attach(chat, name="схема.png", uploaded_by=uploader_user)
    second = sm.attach(chat, name="акт.pdf", uploaded_by=uploader_user)
    assert (first.message_id, second.message_id) == (None, None), "непривязанных строк может быть много"
    stored = StoredFile.objects.get(pk=first.file_id)
    assert stored.purpose == "messenger", "файл вложения — назначение ядра messenger"
    assert (first.name, first.thumb) == ("схема.png", "")

    now = timezone.now()
    message = Message.objects.create(chat=chat, author=creator, text="Файлы", created_at=now)
    MessageAttachment.objects.filter(pk=first.pk).update(message=message)
    with pytest.raises(IntegrityError), transaction.atomic():
        MessageAttachment.objects.create(message=message, file=stored, name="копия.png",
                                         uploaded_by=uploader_user, uploaded_at=now)

    stored_pk = stored.pk
    with pytest.raises(models.ProtectedError):
        stored.delete()
    with pytest.raises(models.ProtectedError):
        uploader_user.delete()
    assert MessageAttachment.objects.filter(pk=first.pk).exists()

    Message.objects.filter(pk=message.pk).delete()
    assert not MessageAttachment.objects.filter(pk=first.pk).exists(), "вложение уходит с сообщением"
    assert MessageAttachment.objects.filter(pk=second.pk, message__isnull=True).exists()
    assert StoredFile.objects.filter(pk=stored_pk).exists(), "строка файла ядра остаётся"


# --- FR-651, 670: настройки мессенджера ------------------------------------------------------------------------

def test_messenger_settings_retention_bounds_and_general_default_on():
    """FR-651, FR-670 (CONTRACT-008, 2.2): одна строка `pk=1` — срок хранения 1…10 лет (по умолчанию 3, база
    отвергает 0, 11 и 255 проверкой `messenger_settings_years_chk`) и включённый «Общий чат» (`general_chat_enabled`
    по умолчанию истина); кто и когда менял — `updated_by` (`PROTECT`, пусто) и `updated_at`."""
    MessengerSettings = support.model("messenger.MessengerSettings")

    retention = _field(MessengerSettings, "retention_years")
    assert isinstance(retention, PositiveSmallIntegerField) and retention.default == 3
    enabled = _field(MessengerSettings, "general_chat_enabled")
    assert isinstance(enabled, BooleanField) and enabled.default is True
    updated_at = _field(MessengerSettings, "updated_at")
    assert isinstance(updated_at, DateTimeField) and updated_at.null and updated_at.blank
    updated_by = _field(MessengerSettings, "updated_by")
    assert updated_by.remote_field.model._meta.label == "core.User"
    assert updated_by.remote_field.on_delete is models.PROTECT
    assert updated_by.null and updated_by.blank

    constraint = _constraint(MessengerSettings, "messenger_settings_years_chk")
    assert isinstance(constraint, CheckConstraint) and constraint.condition is not None

    row, _ = MessengerSettings.objects.get_or_create(
        pk=1, defaults={"retention_years": 3, "general_chat_enabled": True})
    assert row.pk == 1 and row.retention_years == 3, "по умолчанию — 3 года (строка миграции 0002)"
    assert row.general_chat_enabled is True, "«Общий чат» включён после установки"
    assert MessengerSettings.objects.count() == 1, "строка настроек одна"

    for good in (1, 10):
        MessengerSettings.objects.filter(pk=1).update(retention_years=good)
        assert MessengerSettings.objects.get(pk=1).retention_years == good
    for bad in (0, 11, 255):
        with pytest.raises(IntegrityError), transaction.atomic():
            MessengerSettings.objects.filter(pk=1).update(retention_years=bad)
    assert MessengerSettings.objects.get(pk=1).retention_years == 10


# --- FR-643: миграции и данные установки -----------------------------------------------------------------------

def test_migrations_depend_on_core_0011_and_core_0002_initial_data():
    """FR-643 (CONTRACT-008, 2.3): `messenger 0001_initial` создаёт все шесть моделей с проверками и индексами и
    зависит от `core 0011_storedfile_messenger_purpose` (назначение файла `messenger` есть раньше таблиц); имена
    индексов и ограничений — не длиннее 30 знаков (решение К5); `messenger 0002_initial_data` зависит от
    `core 0002_initial_data` (роли установки) и `messenger 0001_initial`; таблицы называются `messenger_*` — на эти
    имена опирается SQL помощников среза."""
    from django.db import migrations

    initial = importlib.import_module("apps.messenger.migrations.0001_initial")
    assert list(initial.dependencies) == [("core", "0011_storedfile_messenger_purpose")]
    created = {operation.name for operation in initial.operations
               if isinstance(operation, migrations.CreateModel)}
    assert created == {"Chat", "ChatMember", "ChatRead", "Message", "MessageAttachment", "MessengerSettings"}, \
        f"0001_initial создаёт не шесть моделей: {sorted(created)}"

    names = []
    for operation in initial.operations:
        if isinstance(operation, migrations.AddIndex):
            names.append(operation.index.name)
        elif isinstance(operation, migrations.AddConstraint):
            names.append(operation.constraint.name)
        elif isinstance(operation, migrations.CreateModel):
            options = operation.options or {}
            names.extend(index.name for index in options.get("indexes", ()))
            names.extend(constraint.name for constraint in options.get("constraints", ()))
        elif isinstance(operation, migrations.AddField):
            index = getattr(operation, "index", None)
            if index is not None:
                names.append(index.name)
    assert names, "0001_initial не объявляет ни одного индекса или ограничения"
    assert sorted(name for name in names if len(name) > 30) == [], f"имена длиннее 30 знаков: {sorted(names)}"

    data = importlib.import_module("apps.messenger.migrations.0002_initial_data")
    assert set(data.dependencies) == {("core", "0002_initial_data"), ("messenger", "0001_initial")}

    tables = {"Chat": "messenger_chat", "ChatMember": "messenger_chatmember", "ChatRead": "messenger_chatread",
              "Message": "messenger_message", "MessageAttachment": "messenger_messageattachment",
              "MessengerSettings": "messenger_messengersettings"}
    for label, table in tables.items():
        assert support.model(f"messenger.{label}")._meta.db_table == table
