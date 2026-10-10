"""T-4124: прочитано и открытие карточки заявки (FR-307, FR-318, FR-319, FR-327, FR-342). Сценарии 1 и 10 спеки.

Представления `/notifications/<id>/open/` (GET), `/notifications/<id>/read/` и `/notifications/read-all/` (POST)
(CONTRACT-004 § 13.1), служба `reading` (§ 6.8) и подписчик `object.viewed` на карточке заявки `GET /tickets/<номер>/`
(§ 4.2). Число на колокольчике после отметки приходит кадром `/ws/notify/` (`#notify-count[data-count]`, § 11.3): сценарий
идёт одной асинхронной функцией в `ws_run`, действия — в `hub.do` внутри `django_capture_on_commit_callbacks(execute=True)`
(§ 11.4, дополнение 2 раздела 17); «рассылки нет» — `receive(timeout=…)` даёт `None`. Имена кода среза 004 внутри
тестов или через `support.model`; подписки шины не снимаются (`bus` не берётся), в журнале нет ошибок подписчиков.
"""
import logging
from datetime import timedelta
from html.parser import HTMLParser

import pytest
from django.utils import timezone

from tests import support, support_notify as notify, support_org as org, support_servicedesk as sd
from tests.support import HX, model

pytestmark = pytest.mark.django_db

KIND = "servicedesk.assigned"
NO_FRAME = 1.5          # сколько ждём кадр, которого быть не должно


# --- помощники только этого файла ------------------------------------------------------------------------

class _Elements(HTMLParser):
    """Все начальные теги разметки: список (тег, словарь атрибутов)."""

    def __init__(self):
        super().__init__()
        self.items: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        self.items.append((tag, {name: (value if value is not None else "") for name, value in attrs}))

    handle_startendtag = handle_starttag


def _elements(response_or_text) -> list[tuple[str, dict]]:
    text = response_or_text if isinstance(response_or_text, str) else response_or_text.content.decode("utf-8")
    parser = _Elements()
    parser.feed(text)
    return parser.items


def _find(items, tag=None, **attrs) -> list[dict]:
    """Элементы с тегом `tag` и атрибутами `data-…` (в именах аргумента `_` вместо `-`); значение `True` — «есть»."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for item_tag, item_attrs in items:
        if tag is not None and item_tag != tag:
            continue
        if all((name in item_attrs) if value is True else item_attrs.get(name) == value for name, value in wanted.items()):
            found.append(item_attrs)
    return found


def _no_bus_errors(caplog) -> None:
    """Правило шапки контракта (решение 24 задач): подписчики `notify` не оставили ошибок в журнале шины."""
    bad = [r.getMessage() for r in caplog.records if r.name == "apps.core.events" and r.levelno >= logging.ERROR]
    assert not bad, f"ошибки подписчиков шины: {bad}"


def _staff():
    """Участник очереди (видит заявки очереди). Возвращает (пользователь, очередь)."""
    queue = sd.make_queue()
    user = support.make_employee()
    org.make_member(user, queue.unit)
    return user, queue


def _note(user, *, text: str = "Уведомление", url: str = "/test/", object_ref: str = "", read_at=None, ticket=None):
    """Уведомление через ORM; у заявки — путь `/tickets/<номер>/` и `object_ref` по первичному ключу (§ 4.2)."""
    if ticket is not None:
        url = f"/tickets/{ticket.number}/"
        object_ref = f"servicedesk.ticket:{ticket.pk}"
    return model("notify.Notification").objects.create(user=user, kind=KIND, text=text, url=url,
                                                       object_ref=object_ref, read_at=read_at)


def _fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


def _read_state(notes) -> list:
    """`read_at` каждого уведомления из базы."""
    return [_fresh(n).read_at for n in notes]


def _count_of(frame: str | None) -> str:
    assert frame is not None, "кадра с числом нет"
    fragments = notify.ws_fragments(frame)
    assert "notify-count" in fragments, f"в кадре нет #notify-count: {sorted(fragments)}"
    return fragments["notify-count"].attrs["data-count"]


def _act(capture, client, method: str, path: str, data=None, **extra):
    """Запрос внутри `capture(execute=True)`: подписчики шины и рассылка идут после фиксации."""
    with capture(execute=True):
        if method == "post":
            return client.post(path, data or {}, **extra)
        return client.get(path, **extra)


def _watch(client, capture, method: str, path: str, data=None, *, expect_frame: bool, **extra):
    """Подключает колокольчик, делает запрос; возвращает (ответ, число при подключении, число из кадра или `None`)."""
    result = {}

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        result["opening"] = _count_of(await conn.receive())
        result["response"] = await hub.do(_act, capture, client, method, path, data, **extra)
        frame = await conn.receive(timeout=2.0 if expect_frame else NO_FRAME)
        result["frame"] = _count_of(frame) if frame is not None else None
        if expect_frame:
            assert frame is not None, "после отметки кадра с новым числом нет"

    notify.ws_run(scenario)
    return result["response"], result["opening"], result["frame"]


# --- открытие уведомления ---------------------------------------------------------------------------------

def test_open_own_marks_read_and_redirects_to_url():
    """FR-307: GET `/notifications/<id>/open/` своего уведомления — 302 на `Notification.url`, `read_at` поставлен;
    у уже прочитанного повторное открытие тоже ведёт на `url`, а `read_at` не меняется."""
    user = support.make_employee()
    note = _note(user, url="/tickets/777/")
    other = _note(user, url="/test/other/")
    client = support.logged_in(user)

    before = timezone.now()
    response = client.get(f"/notifications/{note.pk}/open/")
    assert response.status_code == 302 and response["Location"].endswith("/tickets/777/")
    stamped = _fresh(note).read_at
    assert stamped is not None and stamped >= before
    assert _fresh(other).read_at is None, "открытие одного уведомления отметило другое"

    again = client.get(f"/notifications/{note.pk}/open/")
    assert again.status_code == 302 and again["Location"].endswith("/tickets/777/")
    assert _fresh(note).read_at == stamped, "повторное открытие перезаписало время прочтения"


def test_open_pushes_decreased_count_to_group(django_capture_on_commit_callbacks):
    """FR-307, FR-318: после открытия в группу сотрудника уходит кадр с числом на единицу меньше
    (`#notify-count[data-count]`: было 3, стало 2)."""
    user = support.make_employee()
    notes = [_note(user, text=f"Новое {i}", url=f"/test/{i}/") for i in range(3)]
    client = support.logged_in(user)

    response, opening, frame = _watch(client, django_capture_on_commit_callbacks, "get",
                                      f"/notifications/{notes[0].pk}/open/", expect_frame=True)
    assert response.status_code == 302
    assert opening == "3"
    assert frame == "2"
    assert _fresh(notes[0]).read_at is not None


def test_open_foreign_notification_returns_404_and_stays_unread():
    """FR-342: чужое уведомление открыть нельзя — 404 (как несуществующее), `read_at` у владельца не меняется."""
    owner = support.make_employee()
    stranger = support.make_employee()
    note = _note(owner, url="/tickets/555/")
    response = support.logged_in(stranger).get(f"/notifications/{note.pk}/open/")
    assert response.status_code == 404
    assert _fresh(note).read_at is None


def test_open_nonexistent_notification_returns_404():
    """FR-342: несуществующий номер — 404 (отказ тот же, что для чужого); и неверный формат номера — 404."""
    user = support.make_employee()
    note = _note(user)
    client = support.logged_in(user)
    missing = note.pk + 10 ** 6
    assert client.get(f"/notifications/{missing}/open/").status_code == 404
    assert client.get("/notifications/abc/open/").status_code == 404
    assert _fresh(note).read_at is None


# --- «Прочитать» -------------------------------------------------------------------------------------------

def test_read_marks_one_notification_without_redirect():
    """FR-307: POST `/notifications/<id>/read/` отмечает одно уведомление; запрос НХ — 200 с фрагментом строки
    `li[data-notification]` без перехода; обычный POST — 302 на `/notifications/`; соседние уведомления не затронуты."""
    user = support.make_employee()
    first, second, untouched = (_note(user, text=f"Запись {i}") for i in range(3))
    client = support.logged_in(user)

    hx = client.post(f"/notifications/{first.pk}/read/", **HX)
    assert hx.status_code == 200, "НХ: ответ — фрагмент строки, а не переход"
    assert not hx.has_header("Location")
    assert _fresh(first).read_at is not None
    assert _fresh(second).read_at is None and _fresh(untouched).read_at is None
    text = hx.content.decode("utf-8")
    assert "<html" not in text.lower(), "НХ-ответ — фрагмент без <html>"
    rows = _find(_elements(text), "li", data_notification=str(first.pk))
    assert len(rows) == 1, "в ответе нет строки li[data-notification=<id>]"
    assert rows[0].get("data-unread") == "0", "строка в ответе не в состоянии «прочитано»"
    assert not _find(_elements(text), data_unread_mark=True), "у прочитанной строки осталась отметка «новое»"
    assert not _find(_elements(text), "form", data_form="read"), "у прочитанной строки осталась кнопка «Прочитать»"

    plain = client.post(f"/notifications/{second.pk}/read/")
    assert plain.status_code == 302 and plain["Location"] == "/notifications/"
    assert _fresh(second).read_at is not None
    assert _fresh(untouched).read_at is None


def test_read_foreign_notification_returns_404():
    """FR-342: «Прочитать» чужого уведомления — 404 (и обычный, и НХ-запрос); у владельца `read_at` пуст;
    несуществующий номер — тоже 404."""
    owner = support.make_employee()
    stranger = support.make_employee()
    note = _note(owner)
    client = support.logged_in(stranger)
    assert client.post(f"/notifications/{note.pk}/read/").status_code == 404
    assert client.post(f"/notifications/{note.pk}/read/", **HX).status_code == 404
    assert client.post(f"/notifications/{note.pk + 10 ** 6}/read/").status_code == 404
    assert _fresh(note).read_at is None


def test_read_rejects_get_method():
    """FR-307: `/notifications/<id>/read/` принимает только POST — GET даёт 405 и ничего не меняет."""
    user = support.make_employee()
    note = _note(user)
    response = support.logged_in(user).get(f"/notifications/{note.pk}/read/")
    assert response.status_code == 405
    assert _fresh(note).read_at is None


# --- «Прочитать все» ---------------------------------------------------------------------------------------

def test_read_all_marks_all_own_unread_and_count_becomes_zero(django_capture_on_commit_callbacks):
    """FR-307, FR-319: POST `/notifications/read-all/` отмечает все свои непрочитанные одним действием; НХ — 200 с
    пустым телом и `HX-Redirect: /notifications/`; число на колокольчике становится 0 (кадр `data-count="0"`);
    прежнее время уже прочитанного не меняется; обычный POST — 302 на `/notifications/`."""
    user = support.make_employee()
    old = timezone.now() - timedelta(days=2)
    done = _note(user, text="Давно прочитано", read_at=old)
    unread = [_note(user, text=f"Новое {i}") for i in range(5)]
    client = support.logged_in(user)

    response, opening, frame = _watch(client, django_capture_on_commit_callbacks, "post", "/notifications/read-all/",
                                      {}, expect_frame=True, **HX)
    assert response.status_code == 200 and response.content.strip() == b""
    assert response["HX-Redirect"] == "/notifications/"
    assert opening == "5" and frame == "0"
    assert all(read is not None for read in _read_state(unread))
    assert _fresh(done).read_at == old

    later = _note(user, text="Ещё одно")
    plain = client.post("/notifications/read-all/")
    assert plain.status_code == 302 and plain["Location"] == "/notifications/"
    assert _fresh(later).read_at is not None


def test_read_all_does_not_touch_other_users_notifications():
    """FR-307, FR-342: «Прочитать все» отмечает только уведомления вошедшего сотрудника; чужие остаются непрочитанными."""
    user = support.make_employee()
    other = support.make_employee()
    mine = [_note(user), _note(user)]
    theirs = [_note(other), _note(other, url="/test/2/")]
    client = support.logged_in(user)

    assert client.post("/notifications/read-all/").status_code == 302
    assert all(read is not None for read in _read_state(mine))
    assert _read_state(theirs) == [None, None]
    assert client.get("/notifications/read-all/").status_code == 405


# --- прочитанное остаётся в списке ----------------------------------------------------------------------------

def test_read_notification_stays_in_list():
    """FR-307: прочитанное уведомление остаётся в базе и в списке «Все» (`data-unread="0"`, без отметки «новое» и
    кнопки «Прочитать»), а в списке «Непрочитанные» после перезагрузки его нет."""
    user = support.make_employee()
    note = _note(user, text="Останется в списке")
    kept = _note(user, text="Ещё непрочитанное")
    client = support.logged_in(user)
    assert client.post(f"/notifications/{note.pk}/read/", **HX).status_code == 200
    assert _fresh(note).read_at is not None

    listing = _elements(client.get("/notifications/"))
    rows = _find(listing, "li", data_notification=str(note.pk))
    assert len(rows) == 1 and rows[0].get("data-unread") == "0"
    assert _find(listing, "li", data_notification=str(kept.pk))[0].get("data-unread") == "1"
    assert len(_find(listing, "form", data_form="read")) == 1, "кнопка «Прочитать» должна остаться только у непрочитанной"

    unread = _elements(client.get("/notifications/?f=unread"))
    assert not _find(unread, "li", data_notification=str(note.pk))
    assert _find(unread, "li", data_notification=str(kept.pk))


def test_no_count_push_when_mark_changes_nothing(django_capture_on_commit_callbacks):
    """FR-307, FR-318: если отметка ничего не изменила (уведомление уже прочитано; непрочитанных нет), число в группу
    не рассылается: кадра нет."""
    user = support.make_employee()
    done = _note(user, text="Уже прочитано", read_at=timezone.now())
    unread = _note(user, text="Пока не прочитано")
    client = support.logged_in(user)
    seen = {}

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        assert _count_of(await conn.receive()) == "1"
        seen["first"] = await hub.do(_act, django_capture_on_commit_callbacks, client, "post",
                                     f"/notifications/{unread.pk}/read/", {}, **HX)
        assert _count_of(await conn.receive()) == "0", "после отметки непрочитанного кадр с новым числом обязателен"
        seen["read"] = await hub.do(_act, django_capture_on_commit_callbacks, client, "post",
                                    f"/notifications/{unread.pk}/read/", {}, **HX)
        assert await conn.receive(timeout=NO_FRAME) is None, "число разослано, хотя ничего не изменилось"
        seen["done"] = await hub.do(_act, django_capture_on_commit_callbacks, client, "post",
                                    f"/notifications/{done.pk}/read/", {}, **HX)
        assert await conn.receive(timeout=NO_FRAME) is None, "число разослано при отметке давно прочитанного"
        seen["read_all"] = await hub.do(_act, django_capture_on_commit_callbacks, client, "post",
                                        "/notifications/read-all/", {}, **HX)
        assert await conn.receive(timeout=NO_FRAME) is None, "число разослано при «Прочитать все» без непрочитанных"

    notify.ws_run(scenario)
    assert seen["first"].status_code == 200 and seen["done"].status_code == 200
    assert seen["read"].status_code == 200, "ветвь «уже прочитано» должна отвечать 200, а не отказом"
    assert seen["read_all"].status_code == 200


# --- открытие карточки заявки -----------------------------------------------------------------------------------

def test_ticket_card_get_as_slider_marks_all_ticket_notifications_read(django_capture_on_commit_callbacks, caplog):
    """FR-307: GET карточки заявки как слайдера (`HX-Request: true`) отмечает прочитанными все непрочитанные
    уведомления сотрудника об этой заявке; ранее прочитанное не перезаписывается."""
    user, queue = _staff()
    ticket = sd.make_ticket(queue=queue)
    old = timezone.now() - timedelta(days=1)
    unread = [_note(user, ticket=ticket, text=f"О заявке {i}") for i in range(3)]
    done = _note(user, ticket=ticket, text="О заявке, прочитано", read_at=old)
    client = support.logged_in(user)

    response = _act(django_capture_on_commit_callbacks, client, "get", f"/tickets/{ticket.number}/", **HX)
    assert response.status_code == 200
    assert all(read is not None for read in _read_state(unread))
    assert _fresh(done).read_at == old
    _no_bus_errors(caplog)


def test_ticket_card_get_as_page_marks_all_ticket_notifications_read(django_capture_on_commit_callbacks, caplog):
    """FR-307: GET карточки заявки страницей целиком (без `HX-Request`, например прямая ссылка из письма) отмечает
    прочитанными все уведомления об этой заявке."""
    user, queue = _staff()
    ticket = sd.make_ticket(queue=queue)
    unread = [_note(user, ticket=ticket, text=f"О заявке {i}") for i in range(2)]
    client = support.logged_in(user)

    response = _act(django_capture_on_commit_callbacks, client, "get", f"/tickets/{ticket.number}/")
    assert response.status_code == 200 and b"<html" in response.content.lower()
    assert all(read is not None for read in _read_state(unread))
    _no_bus_errors(caplog)


def test_ticket_card_open_pushes_new_count_lower_by_three(django_capture_on_commit_callbacks, caplog):
    """FR-307, FR-318: у сотрудника четыре непрочитанных, три — о заявке; после открытия карточки в группу приходит
    кадр с числом 1 (на три меньше, а не ноль)."""
    user, queue = _staff()
    ticket = sd.make_ticket(queue=queue)
    ticket_notes = [_note(user, ticket=ticket, text=f"О заявке {i}") for i in range(3)]
    unrelated = _note(user, text="Про другое", object_ref="")
    client = support.logged_in(user)

    response, opening, frame = _watch(client, django_capture_on_commit_callbacks, "get",
                                      f"/tickets/{ticket.number}/", expect_frame=True, **HX)
    assert response.status_code == 200
    assert opening == "4"
    assert frame == "1"
    assert all(read is not None for read in _read_state(ticket_notes))
    assert _fresh(unrelated).read_at is None
    _no_bus_errors(caplog)


def test_ticket_card_open_leaves_other_tickets_and_users_notifications_unread(django_capture_on_commit_callbacks):
    """FR-307, FR-342: открытие карточки отмечает только уведомления этого сотрудника об этой заявке; о другой заявке,
    без `object_ref` и чужие (даже об этой же заявке) остаются непрочитанными."""
    user, queue = _staff()
    colleague = support.make_employee()
    org.make_member(colleague, queue.unit)
    ticket = sd.make_ticket(queue=queue)
    another = sd.make_ticket(queue=queue)
    mine = _note(user, ticket=ticket, text="О заявке")
    on_another = _note(user, ticket=another, text="О другой заявке")
    no_ref = _note(user, text="Без объекта")
    theirs = _note(colleague, ticket=ticket, text="У коллеги о той же заявке")
    client = support.logged_in(user)

    response = _act(django_capture_on_commit_callbacks, client, "get", f"/tickets/{ticket.number}/")
    assert response.status_code == 200
    assert _fresh(mine).read_at is not None
    assert _read_state([on_another, no_ref, theirs]) == [None, None, None]


def test_ticket_card_post_actions_do_not_mark_notifications_read(django_capture_on_commit_callbacks):
    """FR-307: POST-действия карточки («Взять себе», комментарий обычный и НХ) — не «открытие»: уведомления о заявке
    остаются непрочитанными (запросы не идут по редиректу на карточку)."""
    user, queue = _staff()
    ticket = sd.make_ticket(queue=queue)
    notes = [_note(user, ticket=ticket, text=f"О заявке {i}") for i in range(2)]
    client = support.logged_in(user)
    path = f"/tickets/{ticket.number}/"

    took = _act(django_capture_on_commit_callbacks, client, "post", f"{path}take/")
    commented = _act(django_capture_on_commit_callbacks, client, "post", f"{path}comment/", {"text": "Заметка"})
    hx_commented = _act(django_capture_on_commit_callbacks, client, "post", f"{path}comment/", {"text": "Ещё заметка"},
                        **HX)
    assert took.status_code < 500 and commented.status_code < 500 and hx_commented.status_code < 500
    assert _fresh(ticket).assignee_id == user.pk, "«Взять себе» не выполнилось: проверка пуста"
    assert model("servicedesk.TicketEntry").objects.filter(ticket=ticket, kind="comment").count() == 2
    assert _read_state(notes) == [None, None]


def test_ticket_card_open_before_deadline_leaves_no_pending_mail(django_capture_on_commit_callbacks):
    """FR-307, FR-327: уведомление о заявке ждёт письма (`Delivery` `email`, `waiting`); сотрудник открыл карточку до
    срока — к сроку письма доставка не остаётся ожидающей: обход отправки переводит её в `skipped` с причиной `read`,
    письма нет (нет `MailMessage` с `related_ref` доставки), `mail_id` пуст."""
    user, queue = _staff()
    ticket = sd.make_ticket(queue=queue)
    note = _note(user, ticket=ticket, text="О заявке")
    delivery = model("notify.Delivery").objects.create(
        notification=note, channel="email", state="waiting", due_at=timezone.now() + timedelta(minutes=15))
    client = support.logged_in(user)

    response = _act(django_capture_on_commit_callbacks, client, "get", f"/tickets/{ticket.number}/")
    assert response.status_code == 200
    assert _fresh(note).read_at is not None

    model("notify.Delivery").objects.filter(pk=delivery.pk).update(due_at=timezone.now() - timedelta(minutes=1))
    notify.run_tick()

    done = _fresh(delivery)
    assert done.state == "skipped" and done.reason == "read"
    assert done.mail_id is None
    assert not model("mail.MailMessage").objects.filter(related_ref=f"notify.delivery:{delivery.pk}").exists()
