"""T-8121: тесты журнала мессенджера (FR-648, FR-670, FR-671, NFR-708, NFR-709).

План: «Журнал»; CONTRACT-008: 2.2 (модель `MessengerSettings`), 3.4–3.5 (точка `audit_labels`, шина `unit.deleted`),
5.2 (`department.delete`, `department.on_unit_deleted`), 5.4 (`retention.run`, `messenger_settings.get`), 8.1 (шесть
кодов, виды объектов, ключи «было / стало», «журнал только дополняется»), 8.2 (подписи по-русски), 10.2 (поля
страницы настроек). Действия совершаются настоящими службами и адресами: создатель удаляет групповой чат по
`POST /messenger/chats/<id>/delete/` с `confirm=1`, администратор портала — чат отдела, снятие подразделения —
обработчик шины `department.on_unit_deleted`, срок хранения и «Общий чат» — страница `/settings/messenger/`, ночное
задание — `retention.run` через помощник `run_retention`. В журнал не попадает текст переписки (FR-671): проверяются
метки текста, а не только имена ключей. Код среза на уровне модуля не импортируется (модели — `support.model`, службы
— ленивыми импортами), поэтому `pytest --collect-only` проходит до появления кода. Секретов и ПДн нет.
"""
import inspect
import json
import re
from datetime import timedelta

import pytest
from django.db import ProgrammingError, connection, transaction
from django.utils import timezone

from tests import support_messenger as sm
from tests.support import model

pytestmark = pytest.mark.django_db

# метки: текст переписки в журнал не попадает, а название чата, имя отдела и число — попадают (раздел 8.1)
MESSAGE_MARK = "Текст-метка-журнала-1"
GROUP_TITLE_MARK = "Группа-метка-журнала-2"
UNIT_NAME_MARK = "Отдел-метка-журнала-3"
UNIT_REMOVED_MARK = "Удаляемый-отдел-метка-4"
FRESH_MARK = "Свежее-метка-журнала-5"

# ключи «было / стало», которых в журнале быть не должно: содержимое переписки (FR-671)
FORBIDDEN_KEYS = {"text", "body", "content", "preview", "snippet", "message_text", "files", "file_names"}

OBJECT_TYPE_OF_ACTION = {
    "messenger.chat_deleted": "messenger.chat",
    "messenger.department_chat_deleted": "messenger.chat",
    "messenger.unit_chat_deleted": "messenger.chat",
    "messenger.general_changed": "messenger.settings",
    "messenger.retention_changed": "messenger.settings",
    "messenger.retention_purged": "messenger.settings",
}
# подписи точки `audit_labels` — дословно раздел 8.2 (решение контракта К14)
ACTION_TITLES = {
    "messenger.chat_deleted": "Групповой чат удалён",
    "messenger.department_chat_deleted": "Чат отдела удалён администратором",
    "messenger.unit_chat_deleted": "Чат удалён вместе с подразделением",
    "messenger.general_changed": "Общий чат включён или выключен",
    "messenger.retention_changed": "Срок хранения сообщений изменён",
    "messenger.retention_purged": "Сообщения удалены по сроку",
}
OBJECT_TITLES = {"messenger.chat": "чат мессенджера", "messenger.settings": "настройки мессенджера"}
FIELD_TITLES = {
    "chat_title": "название чата", "chat_members": "участников", "chat_created_at": "создан",
    "unit_id": "номер подразделения", "years": "срок хранения, лет",
    "messages": "Удалено по сроку, сообщений",
}

SETTINGS_URL = "/settings/messenger/"
# возраст, заведомо больший срока по умолчанию (3 года): ночное задание его удаляет (раздел 5.4)
OLD = timedelta(days=4 * 366)


# --- модели среза и общие проверки файла ------------------------------------------------------------------------

def _Chat():
    return model("messenger.Chat")


def _Event():
    return model("core.AuditEvent")


def _messenger_events(action: str | None = None) -> list:
    """Записи журнала `messenger.*` по порядку номеров; `action` сужает до одного кода."""
    queryset = _Event().objects.filter(action__startswith="messenger.")
    if action is not None:
        queryset = queryset.filter(action=action)
    return list(queryset.order_by("id"))


def _journal_dump(events) -> str:
    return json.dumps([[event.action, event.object_type, event.object_id, event.before, event.after]
                       for event in events], ensure_ascii=False)


def _set_years(years: int) -> None:
    """Срок хранения строкой `pk=1` (раздел 2.3): ночное задание читает его из `messenger_settings.get()`."""
    model("messenger.MessengerSettings").objects.update_or_create(pk=1, defaults={"retention_years": years})


def _save_settings(session, *, years: int, general: bool):
    """`POST /settings/messenger/` (раздел 10.2): поле `retention_years` и галочка `general_chat_enabled`."""
    data = {"retention_years": str(years)}
    if general:
        data["general_chat_enabled"] = "on"
    return session.client.post(SETTINGS_URL, data)


def _delete_chat(session, chat) -> None:
    """`POST /messenger/chats/<id>/delete/` с `confirm=1`: удаление чата с историей (раздел 10.2)."""
    response = session.client.post(f"/messenger/chats/{chat.pk}/delete/", {"confirm": "1"})
    assert response.status_code == 302, f"удаление чата {chat.pk}: {response.status_code}"
    assert not _Chat().objects.filter(pk=chat.pk).exists(), f"чат {chat.pk} остался"


def _everything() -> dict:
    """Все шесть действий журнала настоящими службами и адресами; возвращает участников и объекты."""
    from apps.messenger.services import department as department_service

    _set_years(3)
    admin = sm.as_admin(full_name="Администратор Журнала")
    creator = sm.make_user(full_name="Создатель Группы")
    first = sm.make_user(full_name="Первый Участник")
    second = sm.make_user(full_name="Второй Участник")

    group = sm.group(creator.user, [first.user, second.user], title=GROUP_TITLE_MARK)
    sm.post(group, creator.user, text=MESSAGE_MARK)
    _delete_chat(creator, group)

    unit = sm.unit(UNIT_NAME_MARK)
    department = sm.department_chat(unit)
    sm.post(department, first.user, text=MESSAGE_MARK)
    _delete_chat(admin, department)

    removed_unit = sm.unit(UNIT_REMOVED_MARK)
    removed_chat = sm.department_chat(removed_unit)
    sm.post(removed_chat, first.user, text=MESSAGE_MARK)
    department_service.on_unit_deleted(removed_unit.pk, removed_unit.name, admin.user.pk)
    assert not _Chat().objects.filter(pk=removed_chat.pk).exists(), "подразделение не сняло чат"

    author = sm.make_user(full_name="Автор Старых Сообщений")
    reader = sm.make_user(full_name="Читатель Старых Сообщений")
    dialog = sm.personal(author, reader)
    now = timezone.now()
    old = [sm.post(dialog, author.user, text=MESSAGE_MARK, created_at=now - OLD) for _ in range(2)]
    fresh = sm.post(dialog, author.user, text=FRESH_MARK, created_at=now - timedelta(days=5))
    purged = sm.run_retention(now)
    assert purged == len(old), f"ночное задание удалило {purged} сообщений вместо {len(old)}"

    # срок сначала меняется после уборки: при сроке 5 лет старые сообщения не удалились бы
    assert _save_settings(admin, years=5, general=True).status_code == 302
    assert _save_settings(admin, years=5, general=False).status_code == 302
    return {"admin": admin, "creator": creator, "group": group.pk, "group_title": GROUP_TITLE_MARK,
            "unit": unit, "removed_unit": removed_unit, "purged": purged, "fresh": fresh}


# --- FR-671: шесть кодов без текста переписки ------------------------------------------------------------------

def test_six_codes_written_without_message_text():
    """FR-671 (CONTRACT-008, 8.1): после удаления группового чата создателем, удаления чата отдела администратором
    портала, снятия подразделения с чатом, смены срока хранения, смены «Общего чата» и ночной уборки в журнале есть
    все шесть кодов `messenger.*` и ни одного другого; у каждого кода свой вид объекта (`messenger.chat` или
    `messenger.settings`), `object_id` — число строкой; текста переписки, превью и имён файлов в записях нет;
    смена «Общего чата» записана по-русски («выключен»)."""
    _everything()
    events = _messenger_events()

    assert {event.action for event in events} == set(sm.AUDIT_CODES), \
        f"коды журнала: {sorted({event.action for event in events})}"
    for event in events:
        assert event.object_type == OBJECT_TYPE_OF_ACTION[event.action], event.action
        assert event.object_id.isdigit(), (event.action, event.object_id)
        for side in (event.before or {}, event.after or {}):
            assert not set(side) & FORBIDDEN_KEYS, (event.action, sorted(side))

    dump = _journal_dump(events)
    assert MESSAGE_MARK not in dump, "текст сообщения попал в журнал"
    general = [event for event in events if event.action == "messenger.general_changed"]
    assert general, "смена «Общего чата» не записана"
    assert "выключен" in _journal_dump(general), "смена «Общего чата» записана не по-русски"


# --- FR-671, NFR-708: подписи по-русски ------------------------------------------------------------------------

def test_labels_of_actions_and_object_types_are_russian():
    """FR-671, NFR-708 (CONTRACT-008, 8.2, решения К13–К14): точка `audit_labels` мессенджера отдаёт словарь из
    четырёх частей; действия — шесть подписей раздела 8.2, виды объектов — два, ключи «было / стало» — шесть, часть
    `values` пуста (числа и «включён»/«выключен» служба пишет по-русски); все подписи с кириллицей. Ядро после
    слияния отдаёт те же подписи и не переписывает чужие: `created_at` остаётся «написано», `title` — «заголовок»,
    `years` — «срок хранения, лет», виды объекта ленты на месте. Модели модуль подписей не импортирует."""
    from apps.core.services import audit_labels as core_labels
    from apps.core.services import audit_search
    from apps.messenger import audit_labels as own

    data = own.audit_labels()
    assert set(data) == {"actions", "fields", "object_types", "values"}
    assert data["actions"] == ACTION_TITLES
    assert data["object_types"] == OBJECT_TITLES
    for name, title in FIELD_TITLES.items():
        assert data["fields"].get(name) == title, f"подпись ключа {name}"
    assert data["values"] == {}, "значения мессенджер пишет по-русски сам (8.2)"

    cyrillic = re.compile("[а-яА-ЯёЁ]")
    for title in list(data["actions"].values()) + list(data["fields"].values()) + list(data["object_types"].values()):
        assert cyrillic.search(title), title

    titles = dict(audit_search.known_actions())
    for action, title in ACTION_TITLES.items():
        assert titles.get(action) == title, f"код {action} в журнале"
    for kind, title in OBJECT_TITLES.items():
        assert core_labels.object_title(kind) == title, kind
    for name, title in FIELD_TITLES.items():
        assert core_labels.label(name) == title, name

    assert core_labels.label("created_at") == "написано", "переписана подпись ленты"
    assert core_labels.label("title") == "заголовок", "переписана подпись прежних модулей"
    assert core_labels.label("years") == "срок хранения, лет"
    assert core_labels.object_title("feed.post") == "запись ленты", "переписана подпись вида объекта ленты"

    source = inspect.getsource(own)
    assert "from apps.messenger.models" not in source and "from .models" not in source, \
        "модуль подписей импортирует модели"


# --- FR-671: обычная переписка в журнал не пишется --------------------------------------------------------------

def test_ordinary_send_edit_delete_are_not_audited():
    """FR-671 (CONTRACT-008, 8.1): отправка, правка и удаление автором — содержимое переписки, в журнал они не
    пишутся: у вызова `POST .../messages/`, `.../edit/` и `.../delete/` успех (302), сообщение меняется, а записей
    `messenger.*` не прибавляется."""
    author = sm.make_user(full_name="Автор Переписки")
    peer = sm.make_user(full_name="Собеседник Переписки")
    chat = sm.group(author.user, [peer.user], title="Обычная переписка")
    Message = model("messenger.Message")
    before = _messenger_events()

    sent = author.client.post(f"/messenger/chats/{chat.pk}/messages/", {"text": "Первое-метка-переписки"})
    assert sent.status_code == 302, f"отправка: {sent.status_code}"
    message = Message.objects.get(chat=chat, author=author.user)
    assert message.text == "Первое-метка-переписки"

    edited = author.client.post(f"/messenger/messages/{message.pk}/edit/", {"text": "Второе-метка-переписки"})
    assert edited.status_code == 302, f"правка: {edited.status_code}"
    message.refresh_from_db()
    assert message.text == "Второе-метка-переписки" and message.edited_at is not None

    removed = author.client.post(f"/messenger/messages/{message.pk}/delete/")
    assert removed.status_code == 302, f"удаление: {removed.status_code}"
    message.refresh_from_db()
    assert message.deleted_at is not None and message.text == ""

    assert _messenger_events() == before, "обычная переписка попала в журнал"


# --- NFR-709: журнал только дополняется ------------------------------------------------------------------------

def test_application_role_has_no_update_or_delete_on_audit_table():
    """NFR-709 (CONTRACT-008, 8.1; тот же тест, что SPEC-006 NFR-508): у роли приложения `crm_app` нет UPDATE, DELETE
    и TRUNCATE на таблицу журнала; правка и удаление записей `messenger.*` отвергаются базой (ProgrammingError),
    строки остаются прежними."""
    _everything()
    Event = _Event()
    events = _messenger_events()
    ids = sorted(event.pk for event in events)
    assert ids, "записей журнала мессенджера нет"
    columns = ("id", "action", "object_type", "object_id", "before", "after", "actor_id")
    snapshot = list(Event.objects.filter(id__in=ids).order_by("id").values_list(*columns))

    with connection.cursor() as cur:
        cur.execute("SELECT has_table_privilege('crm_app', 'core_auditevent', 'UPDATE'), "
                    "has_table_privilege('crm_app', 'core_auditevent', 'DELETE'), "
                    "has_table_privilege('crm_app', 'core_auditevent', 'TRUNCATE')")
        assert cur.fetchone() == (False, False, False)
    with pytest.raises(ProgrammingError), transaction.atomic():
        Event.objects.filter(action__startswith="messenger.").update(action="tampered")
    with pytest.raises(ProgrammingError), transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("DELETE FROM core_auditevent WHERE action LIKE %s", ["messenger.%"])
    assert list(Event.objects.filter(id__in=ids).order_by("id").values_list(*columns)) == snapshot


# --- FR-648, FR-671: удаление чата создателем -------------------------------------------------------------------

def test_chat_deleted_records_title_members_and_created_at_only():
    """FR-648, FR-671 (CONTRACT-008, 8.1, решение К13): создатель удаляет групповой чат с историей
    (`POST .../delete/`, `confirm=1`) — одна запись `messenger.chat_deleted` на `messenger.chat` с номером чата и
    действующим-создателем; в `before` ровно `chat_title`, `chat_members` и `chat_created_at` (время по Москве),
    `after` пуст, текста переписки нет."""
    creator = sm.make_user(full_name="Создатель Удаляемого Чата")
    first = sm.make_user(full_name="Участник Первый")
    second = sm.make_user(full_name="Участник Второй")
    chat = sm.group(creator.user, [first.user, second.user], title=GROUP_TITLE_MARK)
    created = (timezone.now() - timedelta(days=40)).replace(second=0, microsecond=0)
    _Chat().objects.filter(pk=chat.pk).update(created_at=created)
    chat.refresh_from_db()
    assert chat.created_at == created
    sm.post(chat, first.user, text=MESSAGE_MARK)
    chat_pk = chat.pk

    _delete_chat(creator, chat)

    events = _messenger_events("messenger.chat_deleted")
    assert len(events) == 1, f"записей `messenger.chat_deleted`: {len(events)}"
    event = events[0]
    assert (event.object_type, event.object_id) == ("messenger.chat", str(chat_pk))
    assert event.actor_id == creator.user.pk
    assert event.before == {"chat_title": GROUP_TITLE_MARK, "chat_members": 3,
                            "chat_created_at": sm.moscow_text(created)}
    assert isinstance(event.before["chat_members"], int)
    assert re.fullmatch(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}", event.before["chat_created_at"])
    assert event.after == {}
    assert MESSAGE_MARK not in _journal_dump([event]), "текст переписки попал в журнал"


# --- FR-670, FR-671: уборка по сроку ----------------------------------------------------------------------------

def test_retention_purged_records_count_only():
    """FR-670, FR-671 (CONTRACT-008, 8.1): ночное задание, удалившее сообщения по сроку, пишет одну запись
    `messenger.retention_purged` на `messenger.settings`/«1» без действующего; `after` — только `messages` с числом
    удалённых сообщений (свежее остаётся), `before` пуст; текста переписки в журнале нет."""
    _set_years(3)
    author = sm.make_user(full_name="Автор Просроченных Сообщений")
    reader = sm.make_user(full_name="Читатель Просроченных Сообщений")
    chat = sm.personal(author, reader)
    now = timezone.now()
    old = [sm.post(chat, author.user, text=MESSAGE_MARK, created_at=now - OLD) for _ in range(3)]
    fresh = sm.post(chat, author.user, text=FRESH_MARK, created_at=now - timedelta(days=30))

    assert sm.run_retention(now) == len(old)

    events = _messenger_events("messenger.retention_purged")
    assert len(events) == 1, f"записей `messenger.retention_purged`: {len(events)}"
    event = events[0]
    assert (event.object_type, event.object_id) == ("messenger.settings", "1")
    assert event.actor_id is None
    assert event.after == {"messages": 3}
    assert isinstance(event.after["messages"], int)
    assert event.before == {}
    assert MESSAGE_MARK not in _journal_dump([event]), "текст переписки попал в журнал"
    assert model("messenger.Message").objects.filter(pk=fresh.pk).exists(), "свежее сообщение удалено"