"""T-8106: тесты чата отдела (FR-649, FR-650, FR-660, FR-669, FR-671, FR-672).

План: «Состав чата отдела и перевод/приём сотрудника», «Системные записи чата отдела», «Виды чатов и создание»
(чат отдела), «Удаление чата и файлов»; CONTRACT-008: 1.4, 3.1–3.2 (точка `unit_form_parts` и `on_saved`), 3.4–3.5
(запись точки, шина `unit.deleted`), 4.1 (`subtree_member_ids`, `unit_refs`), 5.1–5.4 (состав, создание, удаление,
название), 5.7 (помощники), 8.1 (`messenger.department_chat_deleted`, `messenger.unit_chat_deleted` — без текста),
10.1–10.2 (маршруты, 403/404, подтверждение), 12.6 (галочка `input[name="messenger_chat"]`), 13.1–13.3.

Код среза на уровне модуля не импортируется: модели берутся через `support.model`, службы (`page`, `members`,
`unread`) и `org.services` — ленивыми импортами внутри тестов, поэтому `pytest --collect-only` проходит до появления
кода. Системные записи чата отдела: «Создал чат» и «К чату присоединились сотрудники отдела «<название>»», автор пуст,
`is_system=True`; в истории они есть, но непрочитанного не дают и не правятся. Секретов и ПДн нет: адреса и телефоны
не создаются.
"""
import json

import pytest

from tests import support
from tests import support_messenger as sm
from tests import support_org as org

pytestmark = pytest.mark.django_db

# поле галочки точки `unit_form_parts` (CONTRACT-008, 3.4, 12.6); на правке созданного чата галочки нет
CHECKBOX = "messenger_chat"
SYSTEM_CREATED = "Создал чат"
SYSTEM_JOINED = "К чату присоединились сотрудники отдела «{name}»"
DELETE_CONFIRM = "Удалить чат вместе с историей?"


# --- модели среза и общие проверки файла ------------------------------------------------------------------------

def _Chat():
    return support.model("messenger.Chat")


def _Message():
    return support.model("messenger.Message")


def _Unit():
    return support.model("org.Unit")


def _Event():
    return support.model("core.AuditEvent")


def _user(value):
    """Сотрудник из `sm.Session` или сам `core.User`."""
    return getattr(value, "user", value)


def _chat_url(chat) -> str:
    return f"/messenger/chats/{chat.pk}/"


def _delete_url(chat) -> str:
    return f"/messenger/chats/{chat.pk}/delete/"


def _ids(items) -> set[int]:
    """Номера чатов из `visible_chats`: помощник не навязывает вид возврата (модели или номера)."""
    return {getattr(item, "pk", item) for item in items}


def _messages(chat) -> list:
    return list(_Message().objects.filter(chat=chat).order_by("created_at", "id"))


def _audit(action: str) -> list:
    return list(_Event().objects.filter(action=action).order_by("id"))


def _journal_values(event) -> dict:
    """Ключи «было / стало» одной записи журнала одним словарём (раздел 8.1)."""
    return {**(event.before or {}), **(event.after or {})}


def _post_new_unit(client, name: str, *, checkbox: bool, parent=None) -> "object":
    """`POST /structure/new/` с галочкой или без неё; возвращает узел из базы."""
    data = {"kind": "department", "name": name, "description": "",
            "parent": (parent if parent is not None else org.root_unit()).pk}
    if checkbox:
        data[CHECKBOX] = "on"
    response = client.post("/structure/new/", data)
    assert response.status_code == 302, f"создание узла: {response.status_code}"
    return _Unit().objects.get(name=name)


def _post_edit_unit(client, unit, *, checkbox: bool):
    """`POST /structure/<id>/edit/` без переноса узла (без ключа `parent`), с галочкой или без неё."""
    data = {"name": unit.name, "description": unit.description}
    if checkbox:
        data[CHECKBOX] = "on"
    return client.post(f"/structure/{unit.pk}/edit/", data)


# --- FR-649: галочка в форме узла и системные записи ------------------------------------------------------------

def test_checkbox_on_unit_creation_makes_chat_with_title_and_two_system_messages():
    """FR-649 (CONTRACT-008, 3.2, 3.4, 5.2, 5.4, 12.6): галочка «Создадим чат для всего отдела» на создании узла
    зовёт `department.create`: одна строка `kind="department"` с номером узла и пустым `title` (название даёт
    `page.chat_title` через `unit_refs`), две системные записи «Создал чат» и «К чату присоединились сотрудники
    отдела «<название>»» с `is_system=True` и пустым автором. Без галочки чата нет (проверяет соседний тест)."""
    from apps.messenger.services import page

    admin = sm.as_admin()
    name = "Отдел приёма"
    unit = _post_new_unit(admin.client, name, checkbox=True)

    chats = list(_Chat().objects.filter(kind="department", unit_id=unit.pk))
    assert len(chats) == 1, f"чатов отдела у узла: {len(chats)}"
    chat = chats[0]
    assert chat.title == ""
    assert page.chat_title(chat) == name

    messages = _messages(chat)
    assert [message.text for message in messages] == [SYSTEM_CREATED, SYSTEM_JOINED.format(name=name)]
    for message in messages:
        assert message.is_system is True
        assert message.author_id is None
        assert message.edited_at is None and message.deleted_at is None


def test_no_checkbox_no_chat_and_repeat_save_makes_no_second_chat():
    """FR-649 (CONTRACT-008, 3.2, 5.2): создание узла без галочки чата не делает; галочка на правке создаёт его,
    повторное сохранение с галочкой второго чата не делает — `department.create` идемпотентен по номеру узла,
    системные записи остаются в двух экземплярах."""
    admin = sm.as_admin()
    name = "Отдел без чата"
    unit = _post_new_unit(admin.client, name, checkbox=False)
    assert not _Chat().objects.filter(kind="department", unit_id=unit.pk).exists()

    response = _post_edit_unit(admin.client, unit, checkbox=True)
    assert response.status_code == 302, f"правка узла: {response.status_code}"
    chats = list(_Chat().objects.filter(kind="department", unit_id=unit.pk))
    assert len(chats) == 1
    assert len(_messages(chats[0])) == 2

    response = _post_edit_unit(admin.client, unit, checkbox=True)
    assert response.status_code == 302
    chats = list(_Chat().objects.filter(kind="department", unit_id=unit.pk))
    assert len(chats) == 1, f"после повторного сохранения чатов: {len(chats)}"
    assert len(_messages(chats[0])) == 2, "системные записи продублировались"


# --- FR-650: состав поддерева, новичок и перевод ----------------------------------------------------------------

def test_department_chat_includes_subtree_members_and_not_foreign():
    """FR-650 (CONTRACT-008, 4.1, 5.1): состав чата отдела считается на момент просмотра — `subtree_member_ids`
    берёт сотрудников узла и всех вложенных (основная работа и совместительство), уволенных и сотрудников чужих
    узлов в составе нет; строк `ChatMember` у чата отдела не появляется."""
    from apps.messenger.services import members

    unit = sm.unit("Отдел разработки")
    child = sm.unit("Группа платформы", parent=unit)
    foreign = sm.unit("Чужой отдел")

    insider = sm.make_user(full_name="Внутри Отдела")
    nested = sm.make_user(full_name="Вложенный Сотрудник")
    stranger = sm.make_user(full_name="Чужой Сотрудник")
    dismissed = sm.make_user(state="dismissed", full_name="Уволенный Сотрудник")
    org.make_member(_user(insider), unit)
    org.make_member(_user(nested), child)
    org.make_member(_user(stranger), foreign)
    org.make_member(_user(dismissed), child)

    chat = sm.department_chat(unit)

    assert members.members(chat) == frozenset({insider.user.pk, nested.user.pk})
    assert members.is_member(insider.user, chat) is True
    assert members.is_member(dismissed.user, chat) is False
    assert members.is_member(stranger.user, chat) is False
    assert not chat.members.exists(), "у чата отдела не должно быть строк ChatMember"


def test_renaming_unit_changes_chat_title_without_new_row():
    """FR-649 (CONTRACT-008, 4.1, 5.4): название чата отдела в базе не хранится — `page.chat_title` берёт имя узла
    через `unit_refs`, поэтому переименование видно сразу, без события, и новой строки чата не создаёт."""
    from apps.messenger.services import page
    from apps.org.services import structure

    admin = sm.as_admin()
    unit = sm.unit("Старое имя отдела")
    chat = sm.department_chat(unit)
    assert page.chat_title(chat) == "Старое имя отдела"

    structure.update_unit(unit, name="Новое имя отдела", description="", actor=admin.user)
    unit.refresh_from_db()

    assert unit.name == "Новое имя отдела"
    assert page.chat_title(chat) == "Новое имя отдела"
    assert chat.title == "", "название отдела не копируется в Chat.title"
    assert _Chat().objects.filter(kind="department", unit_id=unit.pk).count() == 1


def test_newcomer_sees_chat_history_and_zero_unread():
    """FR-650, FR-660 (CONTRACT-008, 5.1, 5.3, 5.7): принятый в отдел видит чат и прежнюю историю с первого
    открытия; строк `ChatMember` для этого не создаётся, непрочитанных у новичка — история после создания чата
    (решение владельца 2026-11-17: база чата отдела — создание чата или отметка), системные записи не считаются."""
    from apps.messenger.services import members, unread

    unit = sm.unit("Отдел поддержки")
    old = sm.make_user(full_name="Старожил Отдела")
    org.make_member(_user(old), unit)
    chat = sm.department_chat(unit)
    marker = "История-метка-новичка"
    sm.post(chat, old.user, text=marker)

    newcomer = sm.make_user(full_name="Новый Сотрудник")
    org.make_member(_user(newcomer), unit)

    assert members.is_member(newcomer.user, chat) is True
    assert unread.counts(newcomer.user).get(chat.pk, 0) == 1
    response = newcomer.client.get(_chat_url(chat))
    assert response.status_code == 200
    assert marker in response.content.decode("utf-8")
    assert unread.counts(newcomer.user).get(chat.pk, 0) == 0
    assert not chat.members.exists(), "новичок не должен получать строку ChatMember"


def test_transferred_employee_loses_old_department_chat_and_sees_new():
    """FR-650 (CONTRACT-008, 4.1, 5.1): переведённый выбывает из чата прежнего отдела (состав и видимость считаются
    по цепочке узлов) и видит чат нового отдела, если он создан; беседа прежнего отдела отвечает 404, нового — 200."""
    from apps.messenger.services import members
    from apps.org.services import membership

    admin = sm.as_admin()
    old_unit = sm.unit("Прежний отдел")
    new_unit = sm.unit("Новый отдел")
    person = sm.make_user(full_name="Переведённый Сотрудник")
    org.make_member(_user(person), old_unit)

    old_chat = sm.department_chat(old_unit)
    new_chat = sm.department_chat(new_unit)
    assert members.is_member(person.user, old_chat) is True
    assert members.is_member(person.user, new_chat) is False

    membership.transfer_member(person.user, old_unit, new_unit, actor=admin.user)

    assert members.is_member(person.user, old_chat) is False
    assert members.is_member(person.user, new_chat) is True
    visible = _ids(members.visible_chats(person.user))
    assert new_chat.pk in visible
    assert old_chat.pk not in visible
    assert person.client.get(_chat_url(old_chat)).status_code == 404
    assert person.client.get(_chat_url(new_chat)).status_code == 200


# --- FR-650, 671: удаление узла и чата --------------------------------------------------------------------------

def test_deleted_unit_deletes_chat_and_audits_without_text(django_capture_on_commit_callbacks):
    """FR-650, FR-671 (CONTRACT-008, 3.2, 3.5, 8.1): удаление пустого узла публикует `unit.deleted`; обработчик
    `department.on_unit_deleted` после фиксации удаляет чат отдела и пишет одну запись журнала
    `messenger.unit_chat_deleted` (`object_type="messenger.chat"`, номер чата, ключи `chat_title` и `unit_id`) без
    текста переписки; сбой обработчика удаление узла не отменяет."""
    from apps.org.services import membership, structure

    admin = sm.as_admin()
    unit = sm.unit("Удаляемый отдел")
    author = sm.make_user(full_name="Автор Сообщения")
    org.make_member(_user(author), unit)
    chat = sm.department_chat(unit)
    marker = "Текст-метка-журнала-узла"
    sm.post(chat, author.user, text=marker)
    # узел удаляется только пустым: чат его не блокирует (мессенджер не в `unit_usage`), а участников снимаем
    membership.remove_member(author.user, unit, actor=admin.user)
    chat_pk, unit_pk, unit_name = chat.pk, unit.pk, unit.name

    with django_capture_on_commit_callbacks(execute=True):
        structure.delete_unit(unit, actor=admin.user)

    assert not _Unit().objects.filter(pk=unit_pk).exists()
    assert not _Chat().objects.filter(pk=chat_pk).exists()
    assert not _Message().objects.filter(chat_id=chat_pk).exists()

    events = _audit("messenger.unit_chat_deleted")
    assert len(events) == 1, f"записей журнала: {len(events)}"
    event = events[0]
    assert event.object_type == "messenger.chat"
    assert event.object_id == str(chat_pk)
    values = _journal_values(event)
    assert values.get("chat_title") == unit_name
    assert int(values.get("unit_id")) == unit_pk
    assert marker not in json.dumps([event.before, event.after], ensure_ascii=False)


def test_portal_admin_deletes_department_chat_with_confirm_and_audit():
    """FR-672, FR-671 (CONTRACT-008, 5.2, 8.1, 10.2): администратор портала удаляет чат отдела
    `POST /messenger/chats/<id>/delete/`; без `confirm` — второй шаг «Удалить чат вместе с историей?» и чат цел,
    с `confirm=1` — 302 на `/messenger/`, чат удалён, одна запись `messenger.department_chat_deleted` с названием
    отдела и номером узла, без текста переписки."""
    admin = sm.as_admin()
    unit = sm.unit("Отдел администратора")
    chat = sm.department_chat(unit)
    author = sm.make_user(full_name="Автор Переписки")
    marker = "Текст-метка-журнала-админа"
    sm.post(chat, author.user, text=marker)
    chat_pk = chat.pk

    first = admin.client.post(_delete_url(chat), {})
    assert first.status_code == 200
    assert DELETE_CONFIRM in first.content.decode("utf-8")
    assert _Chat().objects.filter(pk=chat_pk).exists()

    confirmed = admin.client.post(_delete_url(chat), {"confirm": "1"})
    assert confirmed.status_code == 302
    assert confirmed["Location"] == "/messenger/"
    assert not _Chat().objects.filter(pk=chat_pk).exists()

    events = _audit("messenger.department_chat_deleted")
    assert len(events) == 1, f"записей журнала: {len(events)}"
    event = events[0]
    assert event.object_type == "messenger.chat"
    assert event.object_id == str(chat_pk)
    assert event.actor_id == admin.user.pk
    values = _journal_values(event)
    assert values.get("chat_title") == unit.name
    assert int(values.get("unit_id")) == unit.pk
    assert marker not in json.dumps([event.before, event.after], ensure_ascii=False)


def test_member_cannot_delete_department_chat_403():
    """FR-672, FR-669 (CONTRACT-008, 5.2, 10.1–10.2): чат отдела удаляет только администратор портала (или удаление
    узла); участнику, который видит чат, `POST .../delete/` с `confirm=1` отвечает 403, чат и история остаются."""
    unit = sm.unit("Отдел участника")
    member = sm.make_user(full_name="Участник Отдела")
    org.make_member(_user(member), unit)
    chat = sm.department_chat(unit)
    sm.post(chat, member.user, text="Сообщение-метка-участника")
    chat_pk = chat.pk

    response = member.client.post(_delete_url(chat), {"confirm": "1"})

    assert response.status_code == 403
    assert _Chat().objects.filter(pk=chat_pk).exists()
    assert _Message().objects.filter(chat_id=chat_pk, text="Сообщение-метка-участника").exists()


def test_department_chat_not_registered_in_unit_usage_so_unit_deleted():
    """FR-650 (CONTRACT-008, 3.1, 3.4, 4.1): мессенджер не регистрируется в точке `unit_usage`; иначе чат запрещал бы
    удаление узла. Пустой узел с чатом отдела удаляется без `OrgError` — спека требует «узел удаляется вместе с
    чатом», страховка — шаг ночного задания."""
    from apps.core import extensions
    from apps.org.services import structure

    messenger_usage = [func for func in extensions.registered("unit_usage")
                       if getattr(func, "__module__", "").startswith("apps.messenger")]
    assert messenger_usage == [], f"мессенджер зарегистрировал unit_usage: {messenger_usage}"

    admin = sm.as_admin()
    unit = sm.unit("Отдел без блокировки")
    chat = sm.department_chat(unit)
    assert _Chat().objects.filter(pk=chat.pk).exists()

    structure.delete_unit(unit, actor=admin.user)   # не поднимает OrgError("in_use")

    assert not _Unit().objects.filter(pk=unit.pk).exists()


# --- FR-649, 660: системные записи и непрочитанное --------------------------------------------------------------

def test_system_messages_do_not_count_as_unread_and_are_not_editable():
    """FR-649, FR-660 (CONTRACT-008, 5.1, 5.2, 5.3, 10.2): системные записи «Создал чат» и «К чату присоединились…»
    — `is_system=True` с пустым автором; непрочитанного они не дают (у новичка отдела 0); правка и удаление
    недоступны даже участнику — отказ 403 (чат виден) или 404 (запись без автора), текст и отметки не меняются."""
    from apps.messenger.services import unread

    unit = sm.unit("Отдел системных записей")
    chat = sm.department_chat(unit)
    member = sm.make_user(full_name="Читатель Отдела")
    org.make_member(_user(member), unit)

    messages = [message for message in _messages(chat) if message.is_system]
    assert len(messages) == 2
    for message in messages:
        assert message.author_id is None
        assert message.text in (SYSTEM_CREATED, SYSTEM_JOINED.format(name=unit.name))

    assert unread.counts(member.user).get(chat.pk, 0) == 0

    target = messages[0]
    edit = member.client.post(f"/messenger/messages/{target.pk}/edit/", {"text": "Подмена-метка"})
    delete = member.client.post(f"/messenger/messages/{target.pk}/delete/")
    assert edit.status_code in (403, 404), f"правка системной записи: {edit.status_code}"
    assert delete.status_code in (403, 404), f"удаление системной записи: {delete.status_code}"

    target.refresh_from_db()
    assert target.text == SYSTEM_CREATED
    assert target.edited_at is None and target.deleted_at is None
    assert unread.counts(member.user).get(chat.pk, 0) == 0