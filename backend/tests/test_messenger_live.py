"""T-8114: тесты рассылки живых обновлений (FR-648, 650, 660, 661, 669).

План: «Живые обновления и рассылка» (получатели, варианты на класс, одно сообщение слоя, числа в нём,
`notify.html`, задание очереди `notify`, сбой слоя и постановки, удаление чата). CONTRACT-008: 2.2, 4.2, 5.1,
5.3 (`live.publish`, `tasks.publish_event`, `unread.counts/total`), 5.6 (`layer_spy`, `layer_down`, очередь),
5.7 (`support_messenger`), 10.2 (`/chats/<id>/messages/`, `/chats/<id>/read/`, `/chats/<id>/delete/`), 11.1
(группы `messenger.u.<id>`/`notify.u.<id>`, ключи `counts`/`variants`, `meta`), 11.3 (`#menu-badge-messenger`,
`#chat-<id>-unread`, `#chat-<id>-preview`), 12.2–12.3, 13.3.

Код среза на уровне модуля не импортируется: модели — `support.model("messenger.*")`, службы, `django_rq` и
`notify.services.live` — внутри тестов. Рассылка выполняется заданием очереди `notify`:
`django_capture_on_commit_callbacks(execute=True)` ставит задание, `support_messenger.run_jobs("notify")`
выполняет его в том же процессе под шпионом слоя `publish` (как в `test_feed_live*`).

Допущения писателя (см. отчёт T-8114):
1) получатели живого кадра — участники без автора действия (имя теста `..._excludes_author...`, тест
   `test_messenger_chats.py::test_live_recipients_and_still_relevant_use_same_membership`); поэтому класс
   `author` проверяется на действии прочтения: кадр «Прочитали N из M» уходит автору сообщения (FR-659), а
   владелец действия `read` — автор сообщения (как `owner` ленты в CONTRACT-007), и он среди получателей;
2) `counts` в тестах — числа этого чата у получателей (в сценариях один чат с непрочитанным, поэтому
   толкование «только этот чат» и «все чаты» совпадают); `total` сверяется как целое не меньше наибольшего
   числа в `counts` — контракт не уточняет, сумма это или максимум;
3) номер сотрудника в ключах `counts` может стать строкой в JSON-транспорте слоя — тест приводит ключи и
   значения к `int` (решение контракта К16).
"""
import json
import logging
import re
import time
from datetime import datetime

import pytest
from django.utils import timezone

from tests import support
from tests import support_messenger as messenger
from tests import support_org as org
from tests.support import HX
from tests.support_notify import ws_fragments

pytestmark = pytest.mark.django_db

VARIANT = re.compile(r"^(author|reader):([01])$")
PUBLISH_FUNC = "apps.messenger.tasks.publish_event"
PUBLISH_QUEUE = "notify"
LIVE_LOGGER = "apps.messenger.services.live"
SEND_TEXT = "Живое сообщение рассылки"


# --- помощники только этого файла -----------------------------------------------------------------------------

def _employee(name: str) -> messenger.Session:
    return messenger.make_user(full_name=name)


def _staff(name: str) -> messenger.Session:
    """Сотрудник с правом `staff.view`: у него ФИО в тексте — ссылка на карточку (`link_staff`)."""
    user = support.make_with_permissions("staff.view", full_name=name)
    return messenger.Session(user, support.logged_in(user))


def _chat(author, others, title: str = "Чат рассылки"):
    return messenger.group(author, others, title=title)


def _send(session, chat, text: str = SEND_TEXT):
    """`POST /messenger/chats/<id>/messages/` (CONTRACT-008, 10.2)."""
    return session.client.post(f"/messenger/chats/{chat.pk}/messages/", {"text": text}, **HX)


def _read(session, chat, at=None):
    """`POST /messenger/chats/<id>/read/` с `at` (CONTRACT-008, 10.2)."""
    data = {"at": (at or timezone.now()).isoformat()}
    return session.client.post(f"/messenger/chats/{chat.pk}/read/", data, **HX)


def _do(capture, action):
    """Действие, фиксация (задание рассылки ставится в `on_commit`), затем выполнение очереди `notify`."""
    with capture(execute=True):
        response = action()
    messenger.run_jobs(PUBLISH_QUEUE)
    return response


def _spied(capture, action, *, passthrough: bool = False):
    with messenger.layer_spy(passthrough=passthrough) as spy:
        response = _do(capture, action)
    return spy, response


def _gid(user) -> str:
    return f"messenger.u.{user.pk}"


def _nid(user) -> str:
    return f"notify.u.{user.pk}"


def _groups(spy) -> set[str]:
    """Группы беседы, в которые ушёл хотя бы один кадр."""
    return {group for group in spy.by_group if group.startswith("messenger.u.")}


def _events(spy) -> list[dict]:
    """Различные сообщения `messenger.event` (одно и то же сообщение уходит во все группы)."""
    seen, result = set(), []
    for _, message in spy.calls:
        if isinstance(message, dict) and message.get("type") == "messenger.event":
            fingerprint = json.dumps(message, sort_keys=True, default=str)
            if fingerprint not in seen:
                seen.add(fingerprint)
                result.append(message)
    return result


def _event(spy, action: str | None = None) -> dict:
    found = [message for message in _events(spy) if action is None or message["action"] == action]
    assert len(found) == 1, f"ожидалось одно сообщение messenger.event ({action}), получено {len(found)}"
    return found[0]


def _publish_jobs(chat_id: int | None = None) -> list:
    """Задания `messenger.tasks.publish_event` очереди `notify` (фильтр по номеру чата)."""
    import django_rq

    jobs = [job for job in django_rq.get_queue(PUBLISH_QUEUE).jobs if job.func_name == PUBLISH_FUNC]
    if chat_id is None:
        return jobs
    return [job for job in jobs
            if (job.args and job.args[0] == chat_id) or job.kwargs.get("chat_id") == chat_id]


def _job_value(job, index: int, name: str):
    """Аргумент задания: позиционный или именованный (`tasks.publish_event` зовут по-разному в очереди)."""
    if len(job.args) > index:
        return job.args[index]
    return job.kwargs.get(name)


def _counts(message: dict) -> dict[int, int]:
    """Числа из сообщения слоя: ключи и значения приведены к `int` (решение контракта К16)."""
    return {int(key): int(value) for key, value in message["counts"].items()}


def _message(chat, text: str | None = None):
    rows = support.model("messenger.Message").objects.filter(chat=chat).order_by("-pk")
    if text is not None:
        rows = rows.filter(text=text)
    message = rows.first()
    assert message is not None, "сообщение не сохранено"
    return message


def _notify_htmls(spy, user) -> list[str]:
    return [message["html"] for message in spy.by_group.get(_nid(user), [])
            if message.get("type") == "notify.html"]


# --- постановка задания и состав получателей -------------------------------------------------------------------

def test_send_enqueues_publish_event_to_notify_queue_on_commit(django_capture_on_commit_callbacks):
    """FR-661: отправка ставит `messenger.tasks.publish_event` в очередь `notify` только после фиксации;
    аргументы — чат, сообщение и действие `new`; получатели в задании пусты (считаются на момент рассылки)."""
    author = _employee("Автор Очереди")
    reader = _employee("Читатель Очереди")
    chat = _chat(author, [reader.user], title="Очередь рассылки")

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        response = _send(author, chat, "Сообщение в очередь")
        assert response.status_code == 200
        assert _publish_jobs(chat.pk) == [], "задание поставлено до фиксации транзакции"
        message = _message(chat)

    # Django 5.2 заполняет список захвата на выходе из `with` (как и в тестах ленты).
    assert callbacks, "рассылка ставится в `transaction.on_commit`"
    for callback in callbacks:   # фиксация: `on_commit` ставит задание очереди
        callback()

    jobs = _publish_jobs(chat.pk)
    assert len(jobs) == 1, f"заданий рассылки: {len(jobs)}"
    job = jobs[0]
    assert job.func_name == PUBLISH_FUNC
    assert [_job_value(job, 0, "chat_id"), _job_value(job, 1, "message_id"),
            _job_value(job, 2, "action")] == [chat.pk, message.pk, "new"]
    assert job.kwargs.get("recipients") is None, "получатели считаются на момент рассылки, а не на отправке"


def test_recipients_snapshot_excludes_author_and_uses_current_members(django_capture_on_commit_callbacks):
    """FR-661, 669: кадр получают участники чата на момент рассылки без автора; уволенный и посторонний не
    получают; вышедший после отправки — тоже, а вступивший после отправки — получает."""
    author = _employee("Автор Состава")
    stays = _employee("Остаётся В Чате")
    leaves = _employee("Выходит После Отправки")
    newcomer = _employee("Вступает После Отправки")
    dismissed = messenger.make_user(state="dismissed", full_name="Уволенный Получатель")
    outsider = _employee("Посторонний Состава")
    chat = _chat(author, [stays.user, leaves.user, dismissed.user], title="Состав на момент рассылки")
    member = support.model("messenger.ChatMember")

    with messenger.layer_spy() as spy:
        with django_capture_on_commit_callbacks(execute=True):
            response = _send(author, chat, SEND_TEXT)
            # состав меняется после отправки, но до выполнения задания рассылки
            member.objects.filter(chat=chat, user=leaves.user).update(left_at=timezone.now())
            member.objects.create(chat=chat, user=newcomer.user, is_creator=False, joined_at=timezone.now())
        messenger.run_jobs(PUBLISH_QUEUE)

    assert response.status_code == 200
    assert _groups(spy) == {_gid(stays.user), _gid(newcomer.user)}, "получатели — текущий состав без автора"
    for absent in (author.user, leaves.user, dismissed.user, outsider.user):
        assert _gid(absent) not in spy.by_group, f"кадр ушёл в группу {absent.pk}"
    assert len(_events(spy)) == 1, "в каждую группу уходит одно и то же сообщение слоя"


def test_fragment_rendered_once_per_role_and_link_staff_variant(django_capture_on_commit_callbacks):
    """FR-661: фрагмент рендерится один раз на класс получателя: роль `author` (автор сообщения) или `reader`,
    признак `link_staff` — по праву `staff.view`; ключей не больше четырёх, только классы получателей.

    Кадр прочтения уходит автору сообщения (FR-659), поэтому среди получателей есть оба класса; сотрудник с
    `staff.view` видит упоминание ссылкой на карточку, остальные — текстом."""
    author = _employee("Автор Классов")
    staff = _staff("Кадровик Классов")
    plain = _employee("Читатель Классов")
    other = _employee("Второй Читатель Классов")
    chat = _chat(author, [staff.user, plain.user, other.user], title="Классы получателей")
    messenger.post(chat, author, f"Смотрите, @[u{other.user.pk}]")

    spy, response = _spied(django_capture_on_commit_callbacks, lambda: _read(plain, chat))
    assert response.status_code == 200

    message = _event(spy, "read")
    variants = message["variants"]
    assert isinstance(variants, dict) and variants
    assert len(variants) <= 4, f"вариантов больше четырёх: {sorted(variants)}"
    assert all(VARIANT.match(key) for key in variants), sorted(variants)
    assert all(isinstance(html, str) and html.strip() for html in variants.values())
    assert set(variants) == {"author:0", "reader:0", "reader:1"}, sorted(variants)
    assert len(set(variants.values())) >= 2, "роль или признак card-ссылок не меняет фрагмент"

    plain_reader = variants["reader:0"]
    staff_reader = variants["reader:1"]
    assert f'href="/staff/{other.user.pk}/"' in staff_reader, "у сотрудника с `staff.view` нет ссылки на карточку"
    assert f'href="/staff/{other.user.pk}/"' not in plain_reader, "ссылка на карточку у читателя без права"


def test_one_layer_message_contains_counts_total_and_variants(django_capture_on_commit_callbacks):
    """FR-660, 661: одно сообщение `messenger.event` несёт чат, действие, номер сообщения, владельца, числа
    непрочитанных `counts`, общее `total`, варианты и `meta.created_at`; ключи `counts` — сотрудники."""
    author = _employee("Автор Сообщения Слоя")
    first = _employee("Первый Получатель Слоя")
    second = _employee("Второй Получатель Слоя")
    chat = _chat(author, [first.user, second.user], title="Сообщение слоя")

    spy, response = _spied(django_capture_on_commit_callbacks, lambda: _send(author, chat, "Одно сообщение слоя"))
    assert response.status_code == 200
    saved = _message(chat, "Одно сообщение слоя")

    events = _events(spy)
    assert len(events) == 1, f"сообщений слоя: {len(events)}"
    message = events[0]
    assert set(message) == {"type", "chat", "action", "message", "owner", "counts", "total", "variants", "meta"}, \
        sorted(message)
    assert message["type"] == "messenger.event"
    assert message["chat"] == chat.pk and message["action"] == "new"
    assert message["message"] == saved.pk and message["owner"] == author.user.pk

    counts = _counts(message)
    assert set(counts) == {first.user.pk, second.user.pk}, f"получатели чисел: {sorted(counts)}"
    assert list(counts.values()) == [1, 1], "у каждого получателя одно непрочитанное в этом чате"
    assert isinstance(message["total"], int) and not isinstance(message["total"], bool)
    assert message["total"] >= max(counts.values()), f"total={message['total']!r}"

    assert isinstance(message["variants"], dict) and message["variants"]
    assert all(VARIANT.match(key) for key in message["variants"])

    assert set(message["meta"]) == {"created_at"}
    created_at = datetime.fromisoformat(message["meta"]["created_at"])
    assert created_at.tzinfo is not None, message["meta"]["created_at"]
    assert abs((timezone.now() - created_at).total_seconds()) < 300, "`meta.created_at` — не время сообщения"


def test_transferred_employee_gets_no_next_frame(django_capture_on_commit_callbacks):
    """FR-650, 661: состав чата отдела считается по узлам на момент каждой рассылки — переведённый сотрудник
    получает кадр до перевода и не получает следующего."""
    from apps.org.services import membership

    admin = messenger.as_admin()
    old_unit = messenger.unit("Прежний отдел рассылки")
    new_unit = messenger.unit("Новый отдел рассылки")
    author = _employee("Автор Перевода")
    person = _employee("Переведённый Получатель")
    org.make_member(author.user, old_unit)
    org.make_member(person.user, old_unit)
    chat = messenger.department_chat(old_unit)

    first_spy, first_response = _spied(django_capture_on_commit_callbacks,
                                       lambda: _send(author, chat, "До перевода"))
    assert first_response.status_code == 200
    assert _gid(person.user) in _groups(first_spy), "до перевода сотрудник не получил кадр"

    membership.transfer_member(person.user, old_unit, new_unit, actor=admin.user)

    second_spy, second_response = _spied(django_capture_on_commit_callbacks,
                                         lambda: _send(author, chat, "После перевода"))
    assert second_response.status_code == 200
    assert _gid(person.user) not in second_spy.by_group, "переведённый получил кадр прежнего отдела"


def test_third_employee_outside_chat_gets_no_frame(django_capture_on_commit_callbacks):
    """FR-661, 669: посторонний сотрудник (не участник чата) не получает ни кадра, ни числа: его группы нет
    среди групп рассылки, а его номера нет в `counts`."""
    author = _employee("Автор Закрытой Беседы")
    insider = _employee("Участник Закрытой Беседы")
    outsider = _employee("Посторонний Закрытой Беседы")
    chat = _chat(author, [insider.user], title="Закрытая беседа")

    spy, response = _spied(django_capture_on_commit_callbacks, lambda: _send(author, chat, "Только участнику"))
    assert response.status_code == 200
    assert _groups(spy) == {_gid(insider.user)}
    assert _gid(outsider.user) not in spy.by_group
    counts = _counts(_event(spy, "new"))
    assert outsider.user.pk not in counts
    assert set(counts) == {insider.user.pk}, "число ушло не участнику"


# --- сбои слоя и очереди ----------------------------------------------------------------------------------------

def test_layer_down_send_succeeds_fast_and_logs_warning(django_capture_on_commit_callbacks, caplog):
    """FR-661: слой `publish` недоступен — сообщение сохранено, ответ успешен и быстрый (меньше 3 с), сбой слоя
    записан предупреждением журнала `apps.messenger.services.live`; текст сообщения в журнал не попадает."""
    author = _employee("Автор Сбоя Слоя")
    people = [_employee(f"Получатель Сбоя Слоя {number}") for number in range(3)]
    chat = _chat(author, [person.user for person in people], title="Сбой слоя")
    marker = "Текст который не должен попасть в журнал слоя"

    started = time.monotonic()
    with caplog.at_level(logging.WARNING):
        with messenger.layer_down(delay=0.2):
            with django_capture_on_commit_callbacks(execute=True):
                response = _send(author, chat, marker)
            messenger.run_jobs(PUBLISH_QUEUE)   # рассылка выполняется заданием очереди
    elapsed = time.monotonic() - started

    assert response.status_code == 200
    assert support.model("messenger.Message").objects.filter(chat=chat, text=marker).exists()
    assert elapsed < 3.0, f"отправка при сбое слоя заняла {elapsed:.2f} с"
    warnings = [record for record in caplog.records
                if record.name == LIVE_LOGGER and record.levelno == logging.WARNING]
    assert warnings, f"нет предупреждения `{LIVE_LOGGER}`"
    assert not any(marker in record.getMessage() for record in caplog.records), "текст сообщения попал в журнал"


def test_queue_failure_keeps_message_and_logs_warning(django_capture_on_commit_callbacks, caplog, monkeypatch):
    """FR-661: сбой постановки задания (очередь `notify` недоступна) не ломает отправку — сообщение сохранено,
    ответ успешен, предупреждение записано; текст сообщения в журнал не попадает."""
    import django_rq

    author = _employee("Автор Сбоя Очереди")
    reader = _employee("Получатель Сбоя Очереди")
    chat = _chat(author, [reader.user], title="Сбой очереди")
    marker = "Текст при сбое очереди"

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        response = _send(author, chat, marker)
    assert response.status_code == 200
    assert callbacks, "постановка задания — в `transaction.on_commit`"

    def unavailable(*args, **kwargs):
        raise ConnectionError("очередь notify недоступна (подмена теста)")

    with caplog.at_level(logging.WARNING):
        with monkeypatch.context() as patch:
            patch.setattr(django_rq, "get_queue", unavailable)
            for callback in callbacks:   # фиксация: постановка задания падает
                callback()

    assert support.model("messenger.Message").objects.filter(chat=chat, text=marker).exists()
    warnings = [record for record in caplog.records
                if record.name == LIVE_LOGGER and record.levelno == logging.WARNING]
    assert warnings, f"сбой постановки не записан в журнал `{LIVE_LOGGER}`"
    assert not any(marker in record.getMessage() for record in caplog.records), "текст сообщения попал в журнал"


# --- удаление чата ---------------------------------------------------------------------------------------------

def test_chat_delete_recipients_collected_before_cascade(django_capture_on_commit_callbacks):
    """FR-648, 661: при удалении чата получатели кадра снимаются до каскада и передаются заданию готовым
    списком: после удаления строк участников кадр `chat_delete` всё равно уходит всем прежним участникам,
    кроме автора действия."""
    creator = _employee("Создатель Удаляемого Чата")
    first = _employee("Первый Участник Удаляемого")
    second = _employee("Второй Участник Удаляемого")
    chat = _chat(creator, [first.user, second.user], title="Удаляемый чат")
    chat_id = chat.pk

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        response = creator.client.post(f"/messenger/chats/{chat_id}/delete/", {"confirm": "1"})
        assert response.status_code == 302
    # Django 5.2 заполняет список захвата на выходе из `with`.
    assert callbacks, "рассылка удаления ставится в `on_commit`"
    for callback in callbacks:   # получатели уже сняты, строк чата в базе после фиксации нет
        callback()

    jobs = _publish_jobs(chat_id)
    assert len(jobs) == 1, f"заданий удаления: {len(jobs)}"
    recipients = _job_value(jobs[0], 3, "recipients")
    assert recipients is not None, "получатели удаления не переданы готовым списком"
    assert {int(number) for number in recipients} == {first.user.pk, second.user.pk}, recipients

    with messenger.layer_spy() as spy:
        messenger.run_jobs(PUBLISH_QUEUE)

    assert not support.model("messenger.Chat").objects.filter(pk=chat_id).exists()
    assert not support.model("messenger.ChatMember").objects.filter(chat_id=chat_id).exists()
    assert _groups(spy) == {_gid(first.user), _gid(second.user)}
    message = _event(spy, "chat_delete")
    assert message["chat"] == chat_id and message["message"] is None
    assert _gid(creator.user) not in spy.by_group, "кадр удаления ушёл автору действия"


# --- число пункта меню и строки списка -------------------------------------------------------------------------

def test_badge_and_row_fragments_go_to_personal_notify_group(django_capture_on_commit_callbacks):
    """FR-660: каждому получателю в личную группу `notify.u.<id>` уходит одно сообщение `notify.html` с готовым
    фрагментом `#menu-badge-messenger` (`hx-swap-oob`, `data-count`) и OOB-фрагментами строки списка
    `#chat-<id>-unread` и `#chat-<id>-preview` под числа получателя; постороннему — ничего."""
    from apps.notify.services import live as notify_live

    author = _employee("Автор Числа")
    reader = _employee("Получатель Числа")
    stranger = _employee("Посторонний Числа")
    chat = _chat(author, [reader.user], title="Число у получателя")
    marker = "Текст живой строки списка"

    spy, response = _spied(django_capture_on_commit_callbacks, lambda: _send(author, chat, marker))
    assert response.status_code == 200

    group = notify_live.group(reader.user.pk)
    assert group == _nid(reader.user)
    messages = [message for message in spy.by_group.get(group, []) if message.get("type") == "notify.html"]
    assert len(messages) == 1, f"сообщений `notify.html` у получателя: {len(messages)}"
    assert set(messages[0]) == {"type", "html"}

    fragments = ws_fragments(messages[0]["html"])
    badge = fragments.get("menu-badge-messenger")
    assert badge is not None, "в `notify.html` нет `#menu-badge-messenger`"
    assert badge.attrs.get("hx-swap-oob") == "true"
    assert badge.attrs.get("data-count") == "1" and badge.text.strip() == "1"
    assert "data-menu-live-badge" in badge.attrs

    unread = fragments.get(f"chat-{chat.pk}-unread")
    assert unread is not None and unread.attrs.get("hx-swap-oob") is not None, "нет OOB-числа строки списка"
    assert unread.attrs.get("data-count") == "1"

    preview = fragments.get(f"chat-{chat.pk}-preview")
    assert preview is not None and preview.attrs.get("hx-swap-oob") is not None, "нет OOB-превью строки списка"
    assert marker in preview.text, preview.text

    assert _notify_htmls(spy, stranger.user) == [], "постороннему ушло число"