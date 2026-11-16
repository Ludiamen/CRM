"""T-8103: тесты прав и одной функции видимости (FR-643, FR-645, FR-650, FR-651, FR-660, FR-661, FR-663, FR-668, FR-669).

CONTRACT-008, разделы 5.1, 6 (места V1-V13), 10.1, 13; PLAN-008, «Права и неприкосновенность», «Состав чата».
Приём: чужой, несуществующий и удалённый чат, его сообщение, файл и эскиз отвечают одинаково — 404 обычной страницы
«Не найдено» без подробностей (`support.same_failure` в пределах одного клиента, как CONTRACT-006). Все места решения
о доступе зовут одну функцию `members.get_chat` (раздел 6) или то же правило в SQL поиска; состав и видимость чатов
считаются одной функцией участия. Код среза импортируется внутри тестов, поэтому `pytest --collect-only` проходит до
появления кода. Секретов и ПДн нет: адреса и телефоны не создаются.
"""
import re
from urllib.parse import unquote

import pytest
from django.http import Http404
from django.utils import timezone

from tests import support
from tests import support_messenger as sm
from tests import support_org as org

pytestmark = pytest.mark.django_db

MISSING = 999999


# --- помощники файла (общие помощники среза не правятся) ------------------------------------------------------------

def _employee(name: str, **extra):
    """Действующий сотрудник с клиентом (`sm.make_user`)."""
    return sm.make_user(full_name=name, **extra)


def _ids(items) -> set[int]:
    """Номера чатов из `visible_chats`: помощник не навязывает вид возврата (модели или номера)."""
    return {getattr(item, "pk", item) for item in items}


def _chat_rows(html: str) -> set[int]:
    """Номера чатов списка — зацепка строки `[data-chat-id="<id>"]` (раздел 12.2)."""
    return {int(found) for found in re.findall(r'data-chat-id="(\d+)"', html)}


def _assert_like_missing(session, path: str, missing_path: str, method: str = "get", data=None):
    """Ответ на `path` — 404, неотличимый от ответа на `missing_path` (правила среза, разделы 6, 10.1)."""
    send = getattr(session.client, method)
    response = send(path, data or {})
    missing = send(missing_path, data or {})
    assert response.status_code == 404, f"{method.upper()} {path}: {response.status_code}"
    assert support.same_failure(response, missing), (
        f"{method.upper()} {path}: ответ отличается от ответа несуществующего")
    return response


def _login_redirect(response, path: str) -> bool:
    """302 на `/login/?next=<путь>` (раздел 10.1; как `test_lists_access._login_redirect`)."""
    if (response.status_code != 302 or not response["Location"].startswith("/login/")
            or "next=" not in response["Location"]):
        return False
    return unquote(response["Location"].split("next=", 1)[1]) == path


def _messenger_kind(code: str):
    """Запись вида уведомлений из точки `notification_kinds` (раздел 7.1) — её и зовут почта и сводка."""
    from apps.core import extensions

    for factory in extensions.registered("notification_kinds"):
        for kind in factory():
            if kind.code == code:
                return kind
    raise AssertionError(f"вид уведомления {code} не зарегистрирован")


def _messenger_provider():
    """Поставщик группы «Мессенджер» из точки `search_providers` (раздел 9)."""
    from apps.core import extensions

    found = [provider for factory in extensions.registered("search_providers")
             for provider in factory() if provider.key == "messenger"]
    assert len(found) == 1, f"поставщик «Мессенджер» зарегистрирован не один раз: {len(found)}"
    return found[0]


# --- V7 и одинаковый 404 ---------------------------------------------------------------------------------------------

def test_get_chat_same_http404_for_missing_foreign_and_deleted():
    """FR-669: `members.get_chat` — одна точка решения: невидимый, несуществующий и удалённый чат дают одинаковый
    `Http404`, а страница беседы отвечает тем же 404, что и на несуществующий чат."""
    from apps.messenger.services import members

    author = _employee("Автор Диалога")
    friend = _employee("Собеседник Диалога")
    outsider = _employee("Посторонний Сотрудник")
    chat = sm.personal(author, friend)
    deleted = sm.group(author, [friend], title="Удалённый чат")
    deleted_id = deleted.pk
    support.model("messenger.Chat").objects.filter(pk=deleted_id).delete()

    assert members.get_chat(friend.user, chat.pk).pk == chat.pk

    details = []
    for chat_id in (MISSING, chat.pk, deleted_id):
        with pytest.raises(Http404) as caught:
            members.get_chat(outsider.user, chat_id)
        details.append(str(caught.value))
    assert len(set(details)) == 1, f"Http404 различается по причине: {details}"

    missing = f"/messenger/chats/{MISSING}/"
    assert outsider.client.get(missing).status_code == 404
    for chat_id in (chat.pk, deleted_id):
        _assert_like_missing(outsider, f"/messenger/chats/{chat_id}/", missing)


# --- V2-V7: одна функция видимости во всех местах -------------------------------------------------------------------

def test_every_endpoint_of_chat_uses_one_visibility_function(monkeypatch):
    """FR-669: каждое место решения о доступе зовёт `members.get_chat` (раздел 6): беседа (V2), история (V3),
    поиск по беседе (V4), подсказка «@» (V5), отправка/правка/удаление (V6), отметка прочтения (V7), состав,
    выход и удаление чата; чужой чат везде — 404, как несуществующий."""
    from apps.messenger.services import members

    author = _employee("Автор Чужого Чата")
    friend = _employee("Участник Чужого Чата")
    outsider = _employee("Посторонний Наблюдатель")
    chat = sm.group(author, [friend], title="Чужой чат")
    message = sm.post(chat, author, "Текст чужого чата")

    calls: list[int] = []
    real = members.get_chat

    def spy(*args, **kwargs):
        user = args[0] if args else kwargs["user"]
        chat_id = args[1] if len(args) > 1 else kwargs.get("chat_id")
        calls.append(int(chat_id))
        return real(user, chat_id)

    monkeypatch.setattr(members, "get_chat", spy)

    assert friend.client.get(f"/messenger/chats/{chat.pk}/").status_code == 200
    assert calls and set(calls) == {chat.pk}, "участнику беседа открывается не через get_chat"

    at = timezone.now().isoformat()
    endpoints = [
        ("беседа", "get", f"/messenger/chats/{chat.pk}/", None,
         f"/messenger/chats/{MISSING}/"),
        ("история", "get", f"/messenger/chats/{chat.pk}/messages/", None,
         f"/messenger/chats/{MISSING}/messages/"),
        ("поиск по беседе", "get", f"/messenger/chats/{chat.pk}/search/?q=чужого", None,
         f"/messenger/chats/{MISSING}/search/?q=чужого"),
        ("подсказка «@»", "get", f"/messenger/mentions/?chat={chat.pk}&q=Уча", None,
         f"/messenger/mentions/?chat={MISSING}&q=Уча"),
        ("отправка", "post", f"/messenger/chats/{chat.pk}/messages/", {"text": "Привет"},
         f"/messenger/chats/{MISSING}/messages/"),
        ("правка", "post", f"/messenger/messages/{message.pk}/edit/", {"text": "Правка"},
         f"/messenger/messages/{MISSING}/edit/"),
        ("удаление сообщения", "post", f"/messenger/messages/{message.pk}/delete/", None,
         f"/messenger/messages/{MISSING}/delete/"),
        ("прочтение", "post", f"/messenger/chats/{chat.pk}/read/", {"at": at},
         f"/messenger/chats/{MISSING}/read/"),
        ("состав", "post", f"/messenger/chats/{chat.pk}/members/", {"add": [friend.user.pk]},
         f"/messenger/chats/{MISSING}/members/"),
        ("выход", "post", f"/messenger/chats/{chat.pk}/leave/", {"confirm": "1"},
         f"/messenger/chats/{MISSING}/leave/"),
        ("удаление чата", "post", f"/messenger/chats/{chat.pk}/delete/", {"confirm": "1"},
         f"/messenger/chats/{MISSING}/delete/"),
    ]
    for label, method, path, data, missing_path in endpoints:
        calls.clear()
        send = getattr(outsider.client, method)
        response = send(path, data or {})
        assert response.status_code == 404, f"{label}: {response.status_code}"
        assert calls and set(calls) == {chat.pk}, f"{label}: видимость спрошена не через одну функцию: {calls}"
        missing = send(missing_path, data or {})
        assert support.same_failure(response, missing), f"{label}: ответ отличается от ответа несуществующего"


# --- V13: администратор портала --------------------------------------------------------------------------------------

def test_admin_of_portal_gets_404_on_foreign_personal_dialog():
    """FR-669, FR-643: администратор портала проходит тот же фильтр: чужой личный диалог — 404, как несуществующий;
    чужих сообщений он не правит и не удаляет (эндпоинтов нет), в списке диалога нет."""
    author = _employee("Автор Личного")
    friend = _employee("Собеседник Личного")
    admin = sm.as_admin(full_name="Администратор Портала")
    chat = sm.personal(author, friend)
    message = sm.post(chat, author, "Личное сообщение")

    _assert_like_missing(admin, f"/messenger/chats/{chat.pk}/", f"/messenger/chats/{MISSING}/")
    _assert_like_missing(admin, f"/messenger/chats/{chat.pk}/messages/", f"/messenger/chats/{MISSING}/messages/")
    _assert_like_missing(admin, f"/messenger/chats/{chat.pk}/messages/", f"/messenger/chats/{MISSING}/messages/",
                         "post", {"text": "Сообщение администратора"})
    _assert_like_missing(admin, f"/messenger/messages/{message.pk}/edit/", f"/messenger/messages/{MISSING}/edit/",
                         "post", {"text": "Правка администратора"})
    _assert_like_missing(admin, f"/messenger/messages/{message.pk}/delete/",
                         f"/messenger/messages/{MISSING}/delete/", "post")

    Message = support.model("messenger.Message")
    assert Message.objects.filter(pk=message.pk, text="Личное сообщение").exists()
    assert not Message.objects.filter(chat=chat, text="Правка администратора").exists()
    assert not Message.objects.filter(chat=chat, text="Сообщение администратора").exists()

    page = admin.client.get("/messenger/list/")
    assert page.status_code == 200
    assert chat.pk not in _chat_rows(page.content.decode()), "чужой личный диалог попал в список администратора"

    own = sm.personal(admin, author)
    assert admin.client.get(f"/messenger/chats/{own.pk}/").status_code == 200, "тот же фильтр закрыл свой диалог"


# --- FR-643: уволенный ------------------------------------------------------------------------------------------------

def test_dismissed_employee_has_no_access_to_portal_and_chats():
    """FR-643: уволенный доступа к порталу и чатам не имеет — сессии закрываются при увольнении, вход отклоняется,
    сообщение не отправляется, а в составе чата уволенного нет."""
    from apps.core.services import accounts
    from apps.messenger.services import members

    employee = _employee("Увольняемый Сотрудник")
    friend = _employee("Собеседник Увольняемого")
    chat = sm.personal(employee, friend)
    general = sm.general()
    assert employee.client.get("/messenger/").status_code == 200

    accounts.dismiss(employee.user, actor=support.make_admin())

    for path in ("/messenger/", "/messenger/list/", f"/messenger/chats/{chat.pk}/"):
        response = employee.client.get(path)
        assert _login_redirect(response, path), f"{path}: {response.status_code} {response.get('Location')}"

    sending = f"/messenger/chats/{chat.pk}/messages/"
    response = employee.client.post(sending, {"text": "Привет после увольнения"})
    assert _login_redirect(response, sending), f"отправка: {response.status_code} {response.get('Location')}"
    assert not support.model("messenger.Message").objects.filter(chat=chat).exists()

    client = support.make_client()
    refused = support.post_password(client, employee.user)
    assert refused.status_code == 200 and "/login/code/" not in refused.get("Location", ""), "уволенного пустили к коду"
    assert not support.model("core.UserSession").objects.filter(user=employee.user).exists()

    assert employee.user.pk not in members.members(chat)
    assert employee.user.pk not in members.members(general)


# --- V2, V3, V6, V7: посторонний ------------------------------------------------------------------------------------

def test_employee_outside_chat_cannot_open_message_edit_delete_read_or_search():
    """FR-669: посторонний не открывает беседу, историю и поиск по беседе, не отправляет, не правит, не удаляет и не
    отмечает прочитанным — везде 404, как у несуществующего чата; в чате ничего не меняется."""
    author = _employee("Автор Беседы")
    friend = _employee("Участник Беседы")
    outsider = _employee("Посторонний Читатель")
    chat = sm.group(author, [friend], title="Беседа Двоих")
    message = sm.post(chat, author, "Текст беседы")

    _assert_like_missing(outsider, f"/messenger/chats/{chat.pk}/", f"/messenger/chats/{MISSING}/")
    _assert_like_missing(outsider, f"/messenger/chats/{chat.pk}/messages/", f"/messenger/chats/{MISSING}/messages/")
    _assert_like_missing(outsider, f"/messenger/chats/{chat.pk}/messages/", f"/messenger/chats/{MISSING}/messages/",
                         "post", {"text": "Привет в чужой чат"})
    _assert_like_missing(outsider, f"/messenger/messages/{message.pk}/edit/", f"/messenger/messages/{MISSING}/edit/",
                         "post", {"text": "Правка постороннего"})
    _assert_like_missing(outsider, f"/messenger/messages/{message.pk}/delete/",
                         f"/messenger/messages/{MISSING}/delete/", "post")
    _assert_like_missing(outsider, f"/messenger/chats/{chat.pk}/read/", f"/messenger/chats/{MISSING}/read/",
                         "post", {"at": timezone.now().isoformat()})
    _assert_like_missing(outsider, f"/messenger/chats/{chat.pk}/search/?q=беседы",
                         f"/messenger/chats/{MISSING}/search/?q=беседы")

    Message = support.model("messenger.Message")
    assert Message.objects.filter(pk=message.pk, text="Текст беседы", deleted_at__isnull=True).exists()
    assert Message.objects.filter(chat=chat).count() == 1
    assert not Message.objects.filter(chat=chat, text="Привет в чужой чат").exists()
    assert not support.model("messenger.ChatRead").objects.filter(chat=chat, user=outsider.user).exists()


# --- V8: файлы и эскизы -----------------------------------------------------------------------------------------------

def test_foreign_chat_file_and_thumb_answer_like_missing(protected_root):
    """FR-669: оригинал и эскиз файла чужого чата — 404, как у несуществующего файла; участнику они доступны,
    а непривязанный файл видит только загрузивший."""
    author = _employee("Автор Файла")
    friend = _employee("Участник с Файлом")
    outsider = _employee("Посторонний у Файла")
    chat = sm.group(author, [friend], title="Чат с файлом")
    attachment = sm.attach(chat, name="схема.png", write=True, thumb=True)
    sm.post(chat, author, "Файл к сообщению", files=[attachment])
    unbound = sm.attach(chat, name="черновик.txt", write=True)

    assert friend.client.get(f"/messenger/files/{attachment.pk}/").status_code == 200
    assert friend.client.get(f"/messenger/files/{attachment.pk}/thumb/").status_code == 200
    _assert_like_missing(outsider, f"/messenger/files/{attachment.pk}/", f"/messenger/files/{MISSING}/")
    _assert_like_missing(outsider, f"/messenger/files/{attachment.pk}/thumb/", f"/messenger/files/{MISSING}/thumb/")
    _assert_like_missing(outsider, f"/messenger/files/{unbound.pk}/", f"/messenger/files/{MISSING}/")
    assert author.client.get(f"/messenger/files/{unbound.pk}/").status_code == 200, "загрузивший не видит свой файл"


# --- V9: сквозной поиск -----------------------------------------------------------------------------------------------

def test_search_does_not_show_foreign_chat_and_does_not_count_it():
    """FR-668, FR-669: слово из чужого чата не попадает в выдачу и в число группы «Мессенджер»: видимость — то же
    правило участия в SQL поставщика."""
    from apps.search.parse import parse

    author = _employee("Автор Закрытого")
    friend = _employee("Участник Закрытого")
    outsider = _employee("Посторонний Поиска")
    chat = sm.group(author, [friend], title="Секретный чат")
    sm.post(chat, author, "Квазар в закрытом чате")

    parsed = parse("Квазар")
    provider = _messenger_provider()
    assert provider.available(friend.user) is True
    assert provider.available(outsider.user) is True

    rows = provider.search(friend.user, parsed, 20, 0)
    assert len(rows) == 1, f"участник не нашёл своё сообщение: {len(rows)} строк"
    assert f"/messenger/chats/{chat.pk}/#m" in rows[0].url
    assert "Секретный чат" in rows[0].title

    assert provider.search(outsider.user, parsed, 20, 0) == []
    assert provider.count(friend.user, parsed)[0] == 1
    assert provider.count(outsider.user, parsed) == (0, False)


# --- V10, V11: рассылка и still_relevant -----------------------------------------------------------------------------

def test_live_recipients_and_still_relevant_use_same_membership(django_capture_on_commit_callbacks):
    """FR-661, FR-663: получатели рассылки — `members(chat)` без автора на момент рассылки; уведомление живо ровно
    пока получатель в составе (`still_relevant` по тому же правилу участия)."""
    from apps.messenger.services import members, messages

    author = _employee("Автор Рассылки")
    peer = _employee("Получатель Рассылки")
    witness = _employee("Свидетель Рассылки")
    outsider = _employee("Посторонний Рассылки")
    chat = sm.group(author, [peer, witness], title="Рассылка")
    kind = _messenger_kind("messenger.message")
    ref = f"messenger.chat:{chat.pk}"

    with sm.layer_spy() as first_spy:
        with django_capture_on_commit_callbacks(execute=True):
            messages.send(chat, author.user, "Первое сообщение")
        sm.run_jobs("notify")

    assert members.is_member(peer.user, chat) is True
    assert kind.still_relevant(peer.user.pk, ref) is True
    assert f"messenger.u.{peer.user.pk}" in first_spy.by_group
    assert f"messenger.u.{witness.user.pk}" in first_spy.by_group
    for absent in (author.user.pk, outsider.user.pk):
        assert f"messenger.u.{absent}" not in first_spy.by_group, f"кадр ушёл в группу {absent}"

    support.model("messenger.ChatMember").objects.filter(chat=chat, user=peer.user).update(left_at=timezone.now())
    assert members.is_member(peer.user, chat) is False
    assert kind.still_relevant(peer.user.pk, ref) is False

    with sm.layer_spy() as second_spy:
        with django_capture_on_commit_callbacks(execute=True):
            messages.send(chat, author.user, "Второе сообщение")
        sm.run_jobs("notify")
    assert f"messenger.u.{witness.user.pk}" in second_spy.by_group
    assert f"messenger.u.{peer.user.pk}" not in second_spy.by_group, "кадр ушёл вышедшему участнику"


# --- V1, V12: видимость списка и состав отдела ----------------------------------------------------------------------

def test_visible_chats_for_employee_personal_group_department_chain_and_general():
    """FR-643, FR-650, FR-651: видимы свои личный и групповой чаты, чаты отдела по цепочке узлов (свой и родительский)
    и «Общий чат»; чужой отдел, чужие личный и групповой не видны ни функцией, ни в списке; выключенный «Общий чат»
    исчезает из обоих мест."""
    from apps.messenger.services import members

    employee = _employee("Сотрудник Отдела")
    peer = _employee("Собеседник Личный")
    outsider = _employee("Посторонний Сотрудник")
    it_unit = sm.unit("Отдел ИТ")
    net_unit = sm.unit("Группа сети", parent=it_unit)
    other_unit = sm.unit("Бухгалтерия")
    org.make_member(employee.user, net_unit)
    support.model("messenger.MessengerSettings").objects.get_or_create(pk=1, defaults={"retention_years": 3})

    personal = sm.personal(employee, peer)
    group = sm.group(employee, [peer], title="Своя группа")
    department_own = sm.department_chat(net_unit)
    department_parent = sm.department_chat(it_unit)
    department_foreign = sm.department_chat(other_unit)
    general = sm.general()
    foreign_personal = sm.personal(peer, outsider)
    foreign_group = sm.group(peer, [outsider], title="Чужая группа")

    expected = {personal.pk, group.pk, department_own.pk, department_parent.pk, general.pk}
    assert _ids(members.visible_chats(employee.user)) == expected

    page = employee.client.get("/messenger/list/")
    assert page.status_code == 200
    rows = _chat_rows(page.content.decode())
    assert expected <= rows, f"список не показал видимые чаты: нет {expected - rows}"
    assert not ({department_foreign.pk, foreign_personal.pk, foreign_group.pk} & rows), "список показал чужой чат"

    support.model("messenger.MessengerSettings").objects.filter(pk=1).update(general_chat_enabled=False)
    assert general.pk not in _ids(members.visible_chats(employee.user))
    page = employee.client.get("/messenger/list/")
    assert general.pk not in _chat_rows(page.content.decode()), "выключенный «Общий чат» остался в списке"


def test_members_of_department_chat_are_subtree_without_dismissed():
    """FR-650: состав чата отдела — сотрудники узла и вложенных узлов без уволенных; сотрудник другого отдела
    и уволенный в состав не входят, хотя строк `ChatMember` у чата отдела нет."""
    from apps.messenger.services import members

    head = _employee("Руководитель Отдела")
    newcomer = _employee("Новый Сотрудник")
    outsider = _employee("Сотрудник Бухгалтерии")
    gone = sm.make_user(state="dismissed", full_name="Уволенный Сотрудник")
    it_unit = sm.unit("Отдел ИТ")
    net_unit = sm.unit("Группа сети", parent=it_unit)
    other_unit = sm.unit("Бухгалтерия")
    org.make_member(head.user, it_unit)
    org.make_member(newcomer.user, net_unit)
    org.make_member(gone.user, net_unit)
    org.make_member(outsider.user, other_unit)

    chat = sm.department_chat(it_unit)
    assert members.members(chat) == frozenset({head.user.pk, newcomer.user.pk})
    assert members.is_member(head.user, chat) is True
    assert members.is_member(newcomer.user, chat) is True
    assert members.is_member(gone.user, chat) is False
    assert members.is_member(outsider.user, chat) is False


def test_general_members_are_active_employees_with_one_query():
    """FR-651: состав «Общего чата» — действующие сотрудники одним запросом: активные и заблокированный входят,
    приглашённый и уволенный нет."""
    from apps.messenger.services import members

    first = _employee("Первый Сотрудник")
    second = _employee("Второй Сотрудник")
    sm.make_user(state="invited", full_name="Приглашённый Сотрудник")
    sm.make_user(state="dismissed", full_name="Уволенный Сотрудник")
    blocked = sm.make_user(state="blocked", full_name="Заблокированный Сотрудник")
    chat = sm.general()

    with sm.capture_sql() as sqls:
        found = members.members(chat)

    assert found == frozenset({first.user.pk, second.user.pk, blocked.user.pk})
    selects = [sql for sql in sqls if "core_user" in sql and sql.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1, f"состав «Общего чата» — {len(selects)} запроса к core_user вместо одного"


def test_blocked_member_counted_but_gets_no_frames_or_notifications(django_capture_on_commit_callbacks):
    """FR-660, FR-663: заблокированный участник входит в состав и в «Прочитали N из M», но не получает ни кадров
    рассылки, ни уведомлений."""
    from apps.messenger.services import members, messages, read

    author = _employee("Автор Сообщений")
    peer = _employee("Обычный Участник")
    blocked = sm.make_user(state="blocked", full_name="Заблокированный Участник")
    chat = sm.group(author, [peer, blocked], title="Чат с заблокированным")
    assert members.members(chat) == frozenset({author.user.pk, peer.user.pk, blocked.user.pk})

    with sm.layer_spy() as spy:
        with django_capture_on_commit_callbacks(execute=True):
            message = messages.send(chat, author.user, "Текст для всех")
        sm.run_jobs("notify")

    assert f"messenger.u.{peer.user.pk}" in spy.by_group
    assert f"messenger.u.{blocked.user.pk}" not in spy.by_group, "кадр ушёл заблокированному"
    assert f"notify.u.{blocked.user.pk}" not in spy.by_group, "кадр колокольчика ушёл заблокированному"
    assert read.line(chat, message) == (0, 2), "заблокированный не учтён в «Прочитали N из M»"

    notes = support.model("notify.Notification").objects.filter(kind__startswith="messenger.")
    assert set(notes.values_list("user_id", flat=True)) == {peer.user.pk}, "уведомление создано не только участнику"