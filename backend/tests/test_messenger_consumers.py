"""T-8115: соединение `/ws/messenger/` — коды закрытия, кадры рассылки, входящие сообщения клиента и работа страницы
без соединения (FR-643, 648, 656, 657, 659, 661, 669; NFR-701). Сценарии 5, 8 спеки среза 008.

План: «Живые обновления и рассылка» → `MessengerConsumer`, «Без WebSocket»; CONTRACT-008: 5.5 (потребитель), 5.6
(подмены `CHECK_INTERVAL`, слоя), 11.1–11.4 (сообщения слоя, кадры, коды закрытия), 13.3 (тексты «Прочитали N из M»,
«Сообщение удалено», «изменено»). Соединение ведёт `support_messenger.ws_client` внутри `support_notify.ws_run`: весь
сценарий — одна асинхронная функция, действия с базой и заданиями — `hub.do(...)`. Кадры берутся от настоящей
рассылки `services.live.publish` и от заданий очереди `notify`, поэтому проверки разметки не зависят от строк,
подставленных тестом. Проверка сессии ускорена подменой `apps.messenger.consumers.CHECK_INTERVAL` до подключения.
Код среза на уровне модуля не импортируется (сбор тестов проходит до появления кода).
"""
import asyncio
import json
import re

import pytest
from django.conf import settings as django_settings
from django.utils import timezone

from tests import support
from tests import support_messenger as mm
from tests.support_notify import run_jobs, ws_fragments, ws_run

pytestmark = pytest.mark.django_db

# запреты кадра (CONTRACT-008, 11.3): формы, токен, скрипты, встроенные стили и обработчики
FORBIDDEN_IN_FRAME = ("<form", "csrfmiddlewaretoken", "<script", "style=")
INLINE_HANDLER = re.compile(r"\son[a-z]+\s*=")


# --- помощники только этого файла -----------------------------------------------------------------------------------

def _sid(session) -> str:
    """Ключ сессии Django клиента (значение куки)."""
    return session.client.cookies[django_settings.SESSION_COOKIE_NAME].value


def _fast(monkeypatch, interval: float = 0.2) -> None:
    """Проверка сессии в цикле — раз в `interval` секунд (модульная константа потребителя)."""
    monkeypatch.setattr("apps.messenger.consumers.CHECK_INTERVAL", interval)


def _now() -> str:
    return timezone.now().isoformat()


def _send_after_commit(capture, session, chat, text: str):
    """Отправка сообщения обычным HTMX-POST; рассылка — заданием очереди `notify` после фиксации."""
    with capture(execute=True):
        response = session.client.post(f"/messenger/chats/{chat.pk}/messages/", {"text": text}, **support.HX)
    run_jobs("notify")
    return response


def _edit_after_commit(capture, session, message, text: str):
    """Правка сообщения автором; рассылка — заданием очереди `notify` после фиксации."""
    with capture(execute=True):
        response = session.client.post(f"/messenger/messages/{message.pk}/edit/", {"text": text}, **support.HX)
    run_jobs("notify")
    return response


def _delete_message_after_commit(capture, session, message):
    """Удаление сообщения автором; рассылка — заданием очереди `notify` после фиксации."""
    with capture(execute=True):
        response = session.client.post(f"/messenger/messages/{message.pk}/delete/", **support.HX)
    run_jobs("notify")
    return response


def _last_message(chat):
    return support.model("messenger.Message").objects.filter(chat_id=chat.pk).order_by("-id").first()


def _delete_chat_after_commit(capture, session, chat_id: int):
    """Удаление чата создателем обычным POST внутри `capture(execute=True)` и рассылка заданием очереди `notify`
    (план: получатели кадра снимаются до каскада, задание ставится после фиксации)."""
    with capture(execute=True):
        response = session.client.post(f"/messenger/chats/{chat_id}/delete/", {"confirm": "1"})
    run_jobs("notify")
    return response


def _read_row(chat, session):
    return support.model("messenger.ChatRead").objects.filter(chat=chat, user=session.user).first()


async def _collect(hub, conn, *, timeout: float = 2.0, quiet: float = 0.35, jobs: bool = False) -> list[str]:
    """Все кадры соединения до паузы `quiet` секунд (не дольше `timeout`). С `jobs=True` выполняется задание очереди
    `notify`, если рассылка идёт заданием (план: `tasks.publish_event`): сначала после короткой паузы, затем ещё раз,
    если кадров нет."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    frames = []
    if jobs:
        await hub.sleep(0.2)               # потребитель отмечает прочтение и ставит задание
        await hub.do(run_jobs, "notify")
    while loop.time() < deadline:
        frame = await conn.receive(quiet)
        if frame is None:
            if jobs:
                await hub.do(run_jobs, "notify")
                jobs = False
                continue
            break
        frames.append(frame)
    return frames


def _text(frames) -> str:
    return "\n".join(frame for frame in frames if frame)


async def _assert_open(conn, timeout: float = 0.3) -> None:
    """Соединение принято, открыто и ничего не шлёт само: первый кадр — ответ на `sync`."""
    assert conn.accepted and conn.close_code is None
    assert await conn.receive(timeout) is None, "потребитель шлёт кадр до `sync`"


async def _close_code(conn, timeout: float = 2.0) -> int | None:
    """Код закрытия: уже полученный при подключении или следующий (`websocket.close`)."""
    return conn.close_code if conn.close_code is not None else await conn.wait_close(timeout)


# --- подключение: 4400, 4404, 4401 ----------------------------------------------------------------------------------

def test_connect_without_chat_zero_negative_or_text_closes_4400(monkeypatch):
    """FR-661: `chat` обязателен — нет параметра, `0`, `-1`, `abc`, `01`, дробное — приём и закрытие 4400 до
    `group_add` (ни одно соединение не подписано на группу `messenger.u.{id}`)."""
    added = []

    async def group_add(self, group, channel):
        added.append(group)

    monkeypatch.setattr("channels_redis.core.RedisChannelLayer.group_add", group_add)
    employee, peer = mm.make_user(), mm.make_user()
    chat = mm.personal(employee, peer)
    queries = ("", "chat=0", "chat=-1", "chat=abc", "chat=01", "chat=1.5", "chat=")

    async def scenario(hub):
        for query in queries:
            conn = await mm.ws_client(employee, query, hub=hub)
            assert conn.accepted, f"нет `accept()` до закрытия (запрос {query!r})"
            assert await conn.wait_close(2.0) == 4400, f"код закрытия для запроса {query!r}"
        assert added == [], "соединение подписано на группу до проверки номера чата"
        valid = await mm.ws_client(employee, f"chat={chat.pk}", hub=hub)
        assert valid.accepted and valid.close_code is None, "свой чат с номером не принят"
        assert added == [f"messenger.u.{employee.user.pk}"], "подписка не в личную группу беседы"

    ws_run(scenario)


def test_foreign_and_missing_chat_close_4404():
    """FR-661, FR-669: чужой личный диалог, несуществующий номер и удалённый чат отвечают одинаково — закрытие 4404
    (как 404 страницы, FR-669); свой чат в том же сценарии принимается."""
    employee, first, second = mm.make_user(), mm.make_user(), mm.make_user()
    foreign = mm.personal(first, second)
    own = mm.personal(employee, first)
    gone = mm.personal(employee, second)
    gone_id = gone.pk
    support.model("messenger.Chat").objects.filter(pk=gone_id).delete()

    async def scenario(hub):
        refused_foreign = await mm.ws_client(employee, f"chat={foreign.pk}", hub=hub)
        assert await _close_code(refused_foreign) == 4404, "чужой чат"
        refused_missing = await mm.ws_client(employee, "chat=987654321", hub=hub)
        assert await _close_code(refused_missing) == 4404, "несуществующий чат"
        refused_gone = await mm.ws_client(employee, f"chat={gone_id}", hub=hub)
        assert await _close_code(refused_gone) == 4404, "удалённый чат"
        accepted = await mm.ws_client(employee, f"chat={own.pk}", hub=hub)
        assert accepted.accepted and accepted.close_code is None, "свой чат не принят"

    ws_run(scenario)


def test_anonymous_no_second_factor_or_expired_session_close_4401():
    """FR-643, FR-661: без входа, без второго фактора (ограниченная сессия) и с истёкшим бездействием соединение
    принимается и закрывается 4401 (расширение после него не переподключается)."""
    from datetime import timedelta

    from apps.core.services import sessions

    anonymous_chat = mm.personal(mm.make_user(), mm.make_user())
    limited, expired = mm.make_user(), mm.make_user()
    mm.personal(limited, anonymous_chat.created_by)
    mm.personal(expired, anonymous_chat.created_by)
    limited_session = limited.client.session
    limited_session[sessions.LIMITED_KEY] = True
    limited_session.save()
    idle = support.model("core.SecuritySettings").objects.get().idle_timeout_minutes
    support.model("core.UserSession").objects.filter(session_key=_sid(expired)).update(
        last_activity=timezone.now() - timedelta(minutes=idle + 5))

    async def scenario(hub):
        anonymous = await mm.ws_client(None, f"chat={anonymous_chat.pk}", hub=hub)
        assert anonymous.accepted, "`guard_connect` сначала принимает"
        assert await _close_code(anonymous) == 4401, "без входа"
        unconfirmed = await mm.ws_client(limited, f"chat={anonymous_chat.pk}", hub=hub)
        assert unconfirmed.accepted
        assert await _close_code(unconfirmed) == 4401, "без второго фактора"
        stale = await mm.ws_client(expired, f"chat={anonymous_chat.pk}", hub=hub)
        assert stale.accepted
        assert await _close_code(stale) == 4401, "истёкшая сессия"

    ws_run(scenario)


# --- сбои соединения -------------------------------------------------------------------------------------------------

def test_ws_state_error_in_loop_closes_1013(monkeypatch):
    """FR-661: ошибка проверки сессии в цикле закрывает соединение кодом 1013 (расширение переподключится само),
    соединение не остаётся без проверки."""
    from apps.core.services import sessions

    _fast(monkeypatch)
    real, calls = sessions.ws_state, []

    def fake(session, user):
        calls.append(1)
        if len(calls) == 1:
            return real(session, user)
        raise RuntimeError("сбой проверки (подмена теста)")

    monkeypatch.setattr("apps.core.services.sessions.ws_state", fake)
    employee, peer = mm.make_user(), mm.make_user()
    chat = mm.personal(employee, peer)

    async def scenario(hub):
        conn = await mm.ws_client(employee, f"chat={chat.pk}", hub=hub)
        assert conn.accepted
        assert await _close_code(conn) == 1013

    ws_run(scenario)
    assert len(calls) >= 2, "цикл проверки не дошёл до сбоя"


# --- кадры рассылки -------------------------------------------------------------------------------------------------

def test_new_edit_delete_frames_swapped_by_message_id(django_capture_on_commit_callbacks):
    """FR-656, 657, 661: живой кадр участника привязан к номеру сообщения — новое приходит в конец беседы
    (`beforeend:#messenger-messages`, `data-message-id`, `data-own="0"`), правка заменяет `#m<id>` (`outerHTML`,
    пометка «изменено»), удаление приходит как `hx-swap-oob="delete"`; у автора свои ответы с `data-own="1"` и серой
    записью «Сообщение удалено». Кадров не для своего открытого чата нет: событие другого чата и чужой группы
    игнорируется."""
    from channels.layers import get_channel_layer

    capture = django_capture_on_commit_callbacks
    author, reader = mm.make_user(full_name="Автор Авторов"), mm.make_user(full_name="Читатель Читателев")
    chat = mm.personal(author, reader)
    other = mm.personal(author, mm.make_user(full_name="Посторонний Узлов"))
    stranger = mm.make_user(full_name="Третий Узлов")

    def foreign():
        return {"type": "messenger.event", "chat": other.pk, "action": "new", "message": 1,
                "owner": author.user.pk, "counts": {}, "total": 0,
                "variants": {"reader:0": '<div id="m1" hx-swap-oob="beforeend:#messenger-messages">ЧУЖОЙ ЧАТ</div>'},
                "meta": {"created_at": _now()}}

    async def scenario(hub):
        mine = await mm.ws_client(reader, f"chat={chat.pk}", hub=hub)
        await _assert_open(mine)

        sent = await hub.do(_send_after_commit, capture, author, chat, "Первое сообщение")
        assert sent.status_code == 200, "отправка не принята"
        message = await hub.do(_last_message, chat)
        assert message is not None, "сообщение не сохранено"
        assert f'id="m{message.pk}"' in sent.content.decode(), "автор не увидел своё сообщение в ответе"

        frames = _text(await _collect(hub, mine))
        assert f'data-message-id="{message.pk}"' in frames, "кадр нового сообщения не пришёл"
        assert f'id="m{message.pk}"' in frames
        assert 'hx-swap-oob="beforeend:#messenger-messages"' in frames, "новое не встало в конец беседы"
        assert 'data-own="0"' in frames, "чужое сообщение помечено своим"
        assert "HX-Redirect" not in frames, "обычный кадр уводит со страницы"

        edited = await hub.do(_edit_after_commit, capture, author, message, "Правка текста")
        assert edited.status_code == 200, "правка не принята"
        edited_frames = _text(await _collect(hub, mine))
        assert f'id="m{message.pk}"' in edited_frames and 'hx-swap-oob="outerHTML"' in edited_frames, \
            "правка не заменила сообщение"
        assert "изменено" in edited_frames, "пометки «изменено» нет у читателя"

        removed = await hub.do(_delete_message_after_commit, capture, author, message)
        assert removed.status_code == 200, "удаление не принято"
        assert "Сообщение удалено" in removed.content.decode(), "у автора нет серой записи «Сообщение удалено»"
        deleted = _text(await _collect(hub, mine))
        assert f'id="m{message.pk}"' in deleted and 'hx-swap-oob="delete"' in deleted, "удаление не убрало сообщение"

        layer = await hub.do(get_channel_layer)
        await layer.group_send(f"messenger.u.{reader.user.pk}", foreign())
        assert await mine.receive(0.6) is None, "кадр чужого открытого чата дошёл"
        await layer.group_send(f"messenger.u.{stranger.user.pk}", foreign())
        assert await mine.receive(0.4) is None, "кадр чужой группы дошёл"

    ws_run(scenario)


def test_chat_delete_frame_sends_hx_redirect_to_list(django_capture_on_commit_callbacks):
    """FR-648, FR-661: удаление чата даёт участнику кадр `HX-Redirect: /messenger/` (чат исчез у всех); список после
    этого открывается обычным запросом, без соединения, и удалённого чата в нём нет."""
    capture = django_capture_on_commit_callbacks
    creator, member = mm.make_user(full_name="Создатель Создателев"), mm.make_user(full_name="Участник Участников")
    title = "Группа на удаление"
    chat = mm.group(creator, [member], title=title)

    async def scenario(hub):
        conn = await mm.ws_client(member, f"chat={chat.pk}", hub=hub)
        await _assert_open(conn)
        response = await hub.do(_delete_chat_after_commit, capture, creator, chat.pk)
        assert response.status_code == 302, "удаление создателем не принято"
        frames = _text(await _collect(hub, conn, timeout=3.0))
        assert "HX-Redirect" in frames, "кадра с `HX-Redirect` нет"
        assert "/messenger/" in frames, "перехода на список нет"
        page = await hub.do(member.client.get, "/messenger/")
        assert page.status_code == 200, "список без соединения не открылся"
        assert title not in page.content.decode(), "удалённый чат остался в списке"

    ws_run(scenario)


def test_read_message_updates_read_line_for_author():
    """FR-659, FR-661: входящий `read` от читателя отмечает прочтение (`ChatRead`) и рассылает автору кадр
    `#messenger-read` «Прочитали N из M»."""
    author, reader = mm.make_user(full_name="Автор Авторов"), mm.make_user(full_name="Читатель Читателев")
    chat = mm.personal(author, reader)
    message = mm.post(chat, author, "Сообщение автора")

    async def scenario(hub):
        own = await mm.ws_client(author, f"chat={chat.pk}", hub=hub)
        mine = await mm.ws_client(reader, f"chat={chat.pk}", hub=hub)
        await _assert_open(own)
        await _assert_open(mine)
        await mine.send(json.dumps({"sync": {"chat": chat.pk, "at": _now()}}))
        assert await mine.receive(2.0) is not None, "ответа на `sync` нет"
        await mine.send(json.dumps({"read": {"chat": chat.pk, "at": _now()}}))
        frames = await _collect(hub, own, jobs=True)
        line = ws_fragments(_text(frames)).get("messenger-read")
        assert line is not None, "у автора нет кадра «Прочитали N из M»"
        assert line.attrs.get("hx-swap-oob") == "true", "кадр строки прочтения не OOB"
        assert "Прочитали 1 из 1" in line.text, "число прочитавших неверно"
        row = await hub.do(_read_row, chat, reader)
        assert row is not None and row.last_read_at >= message.created_at, "отметка прочтения не записана"

    ws_run(scenario)


# --- входящие сообщения клиента --------------------------------------------------------------------------------------

def test_client_message_over_4kb_closes_1009_and_other_frames_ignored():
    """FR-661: `sync` со своим чатом всегда отвечает служебным кадром `#messenger-synced`; неизвестные кадры, чужой и
    неверный номер чата и неверное время игнорируются без ошибки сервера (соединение живо), сообщение клиента больше
    4 КБ закрывает соединение кодом 1009."""
    employee, peer = mm.make_user(), mm.make_user()
    chat = mm.personal(employee, peer)
    ignored = (
        "не json",
        json.dumps([]),
        json.dumps({"unknown": True}),
        json.dumps({"sync": {"chat": 0, "at": _now()}}),
        json.dumps({"sync": {"chat": chat.pk + 987, "at": _now()}}),
        json.dumps({"sync": {"chat": "1", "at": _now()}}),
        json.dumps({"read": {"chat": chat.pk, "at": "вчера"}}),
        json.dumps({"read": {"chat": chat.pk + 987, "at": _now()}}),
    )
    oversized = json.dumps({"sync": {"chat": chat.pk, "at": _now(), "pad": "x" * 4200}})

    async def scenario(hub):
        conn = await mm.ws_client(employee, f"chat={chat.pk}", hub=hub)
        await _assert_open(conn)
        for frame in ignored:
            await conn.send(frame)
        assert await conn.receive(0.6) is None, "игнорируемый кадр дал ответ или закрыл соединение"
        await conn.send(json.dumps({"sync": {"chat": chat.pk, "at": _now()}}))
        frame = await conn.receive(2.0)
        synced = ws_fragments(frame or "").get("messenger-synced")
        assert synced is not None, "ответа на `sync` нет"
        assert synced.attrs.get("hx-swap-oob") == "true", "служебный кадр не OOB"
        assert len(oversized.encode("utf-8")) > 4096, "кадр проверки не больше 4 КБ"
        await conn.send(oversized)
        assert await _close_code(conn) == 1009

    ws_run(scenario)


# --- запреты кадра и работа без соединения ---------------------------------------------------------------------------

def test_frame_has_no_csrf_token(django_capture_on_commit_callbacks):
    """FR-661: живой кадр — готовый фрагмент без `<form`, `csrfmiddlewaretoken`, `<script`, `style=` и `on…=`; текст
    пользователя экранирован; беседа открывается обычным запросом без соединения и показывает отправленное."""
    capture = django_capture_on_commit_callbacks
    author, reader = mm.make_user(full_name="Автор Авторов"), mm.make_user(full_name="Читатель Читателев")
    chat = mm.personal(author, reader)

    async def scenario(hub):
        mine = await mm.ws_client(reader, f"chat={chat.pk}", hub=hub)
        await _assert_open(mine)
        sent = await hub.do(_send_after_commit, capture, author, chat, 'Текст <b>Ловушка</b> и "кавычки"')
        assert sent.status_code == 200, "отправка не принята"
        message = await hub.do(_last_message, chat)
        frames = _text(await _collect(hub, mine))
        assert f'id="m{message.pk}"' in frames, "кадр сообщения не пришёл"
        for token in FORBIDDEN_IN_FRAME:
            assert token not in frames, f"в кадре есть {token!r}"
        assert INLINE_HANDLER.search(frames) is None, "в кадре есть обработчик `on…=`"
        assert "<b>Ловушка" not in frames, "текст пользователя не экранирован"
        assert "Ловушка" in frames, "текст сообщения потерян"
        page = await hub.do(reader.client.get, f"/messenger/chats/{chat.pk}/")
        assert page.status_code == 200, "беседа без соединения не открылась"
        assert "Ловушка" in page.content.decode(), "новое сообщение не видно после обновления страницы"

    ws_run(scenario)


# --- сбой слоя каналов в потребителе ---------------------------------------------------------------------------------

def test_layer_error_in_consumer_closes_1011(monkeypatch):
    """FR-661: ошибка слоя каналов в потребителе (подписка на группу) закрывает соединение кодом 1011 — расширение
    переподключится само."""
    async def broken(self, group, channel):
        raise OSError("слой каналов недоступен (подмена теста)")

    monkeypatch.setattr("channels_redis.core.RedisChannelLayer.group_add", broken)
    employee, peer = mm.make_user(), mm.make_user()
    chat = mm.personal(employee, peer)

    async def scenario(hub):
        conn = await mm.ws_client(employee, f"chat={chat.pk}", hub=hub)
        assert await _close_code(conn) == 1011

    ws_run(scenario)
