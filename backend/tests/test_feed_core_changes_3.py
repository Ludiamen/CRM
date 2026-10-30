"""T-7126b: поля вида уведомления `channels` и `coalesce_text` (`core/extensions.py`) и их применение в `notify`
(FR-629, FR-631, FR-641).

Фильтр `kind.channels` — в шести местах плана: `prefs._listed` (и через него `channels_for`), `prefs.effective`,
сохранение «Моих уведомлений», таблица `views/me` (ячейка без флажка), `views/admin` (строки и разбор POST) и
`services/settings._normalized_defaults`; у вида без `channels` — прежнее поведение. Склейка с обновлением текста —
в `dispatch.create` под прежним замком ключа склейки. Тестовые виды регистрируются на время блока поверх настоящего
каталога (страницы) или внутри `extensions.empty()` (склейка). Код среза на уровне модуля не импортируется.
Разделы 2.1, 4.2 контракта `CONTRACT-007.md`; план «Уведомления» (склейка с обновлением текста, допустимые каналы
вида) и «Изменения кода прежних срезов».
"""
import contextlib
import dataclasses
import datetime
import re
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import pytest
from django.db import connection

from tests import support
from tests import support_feed as feed
from tests import support_notify as notify
from tests.support import model

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
WORK = datetime.datetime(2026, 10, 14, 12, 0, tzinfo=MSK)         # среда, рабочее время
KIND = "test.coalesced"
REF = "feed.post:15"
ME_URL = "/me/notifications/"
ADMIN_URL = "/settings/notifications/"
OLD_FIELDS = ["code", "title", "module", "events", "build", "external_text", "default_channels", "mandatory",
              "available", "still_relevant", "order", "coalesce", "external_text_of"]
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- разбор разметки (помощник только этого файла; образец — test_feed_page.py) ----------------------------------------

class Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}
        self.parent = parent
        self.children = []

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def find(self, tag=None, **attrs) -> list:
        """Потомки по тегу и атрибутам; имя с дефисом пишется через `_`, `True` — «атрибут есть»."""
        wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
        return [node for node in self.walk()
                if (tag is None or node.tag == tag)
                and all(name in node.attrs and (value is True or node.attrs[name] == value)
                        for name, value in wanted.items())]

    def first(self, tag=None, **attrs):
        found = self.find(tag, **attrs)
        return found[0] if found else None


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = Node("#root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in VOID_TAGS:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def tree(response) -> Node:
    parser = _Tree()
    parser.feed(response.content.decode("utf-8"))
    return parser.root


# --- виды и данные --------------------------------------------------------------------------------------------------

def _kind(code="x.kind", *, channels=None, default=("portal", "email"), **extra):
    from apps.core.extensions import NotificationKind

    return NotificationKind(code=code, title="Тестовый вид", module="Проба", external_text="Есть новое",
                            default_channels=tuple(default), channels=channels, **extra)


@contextlib.contextmanager
def _added(*kinds):
    """Виды добавляются к настоящему каталогу на время блока (страницы и службы видят и прежние виды)."""
    from apps.core import extensions

    saved = list(extensions._registry["notification_kinds"])
    extensions.register("notification_kinds", lambda: list(kinds))
    try:
        yield
    finally:
        extensions._registry["notification_kinds"][:] = saved


def _matrix(user, **by_code):
    model("notify.UserNotifySettings").objects.update_or_create(user=user, defaults={"matrix": by_code})


def _my_matrix(user) -> dict:
    return model("notify.UserNotifySettings").objects.get(user=user).matrix


def _defaults() -> dict:
    return model("notify.NotifySettings").objects.get(pk=1).defaults


def _cells_of(row) -> dict:
    return {td.attrs["data-channel"]: td for td in row.find("td", data_channel=True)}


# --- core/extensions.py: поля вида ---------------------------------------------------------------------------------

def test_notification_kind_channels_and_coalesce_text_are_last_and_default_to_none():
    """FR-629, FR-631: `NotificationKind.channels` и `coalesce_text` — последние два поля, по умолчанию `None`."""
    from apps.core.extensions import NotificationKind

    names = [field.name for field in dataclasses.fields(NotificationKind)]
    assert names[-2:] == ["channels", "coalesce_text"]
    plain = NotificationKind(code="x.plain", title="Простой", module="Проба", external_text="Текст")
    assert plain.channels is None and plain.coalesce_text is None
    chosen = NotificationKind(code="x.chosen", title="Выбранный", module="Проба", channels=("portal",),
                              coalesce_text=lambda user_id, object_ref, since: "текст")
    assert chosen.channels == ("portal",) and chosen.coalesce_text(1, "x", None) == "текст"


def test_notification_kind_has_fifteen_fields_first_thirteen_in_old_order():
    """FR-629, FR-631, FR-641: у `NotificationKind` пятнадцать полей; прежние тринадцать — в прежнем порядке, новые
    два (`support_feed.KIND_FIELDS_007`) — после них."""
    from apps.core.extensions import NotificationKind

    names = [field.name for field in dataclasses.fields(NotificationKind)]
    assert len(names) == 15
    assert names[:13] == OLD_FIELDS
    assert tuple(names[13:]) == feed.KIND_FIELDS_007 == ("channels", "coalesce_text")


# --- фильтр channels: шесть мест -----------------------------------------------------------------------------------

def test_listed_and_channels_for_drop_channel_outside_kind_channels():
    """FR-631: `prefs._listed` и `channels_for` отбрасывают внешний канал вне `kind.channels` — из личной таблицы, из
    значений администратора и из `default_channels`; вид с `channels=("portal",)` внешних каналов не имеет."""
    from apps.notify.services import prefs

    only_mail = _kind("x.only_mail", channels=("portal", "email"), default=("portal", "email", "push", "telegram"))
    only_portal = _kind("x.only_portal", channels=("portal",), default=("portal", "email"))
    assert prefs._listed(only_mail, {}, {}) == ["email"], "default_channels тоже проходят фильтр"
    assert prefs._listed(only_mail, {only_mail.code: ["email", "push", "telegram", "max"]}, {}) == ["email"]
    assert prefs._listed(only_mail, {}, {only_mail.code: ["push", "max"]}) == []
    assert prefs._listed(only_portal, {}, {}) == []

    user = support.make_employee()
    model("notify.NotifySettings").objects.filter(pk=1).update(
        defaults={only_mail.code: ["email", "push"], only_portal.code: ["email"]})
    assert prefs.channels_for(user.pk, only_mail) == ["email"]
    assert prefs.channels_for(user.pk, only_portal) == []
    _matrix(user, **{only_mail.code: ["push", "telegram"]})
    assert prefs.channels_for(user.pk, only_mail) == []
    _matrix(user, **{only_mail.code: ["email", "max"]})
    assert prefs.channels_for(user.pk, only_mail) == ["email"]


def test_prefs_effective_has_no_cell_outside_kind_channels():
    """FR-631: в действующей таблице у вида с `channels` нет ячейки (ключа) вне допустимых каналов — ни по
    `default_channels`, ни по личной таблице, записанной в обход формы; допустимые ячейки на месте."""
    from apps.notify.services import prefs

    kind = _kind("x.only_mail", channels=("portal", "email"), default=("portal", "email", "push"))
    with _added(kind):
        user = support.make_employee()

        def row_cells():
            return {row.kind.code: row.cells for row in prefs.effective(user).rows}[kind.code]

        cells = row_cells()
        assert cells["portal"] is True and cells["email"] is True
        assert not {"push", "telegram", "max"} & set(cells), cells
        _matrix(user, **{kind.code: ["email", "push", "telegram", "max"]})
        cells = row_cells()
        assert cells["email"] is True
        assert not {"push", "telegram", "max"} & set(cells), cells


def test_my_notifications_save_drops_channel_outside_kind_channels():
    """FR-631: сохранение «Моих уведомлений» отбрасывает канал вне `kind.channels` — и службой `prefs.save`, и
    присланной формой `POST /me/notifications/`; допустимые каналы сохраняются."""
    from apps.notify.services import prefs

    kind = _kind("x.only_mail", channels=("portal", "email"), default=("portal",))
    with _added(kind):
        via_service = support.make_employee()
        assert prefs.save(via_service, table={kind.code: ["email", "push"]}) is True
        assert _my_matrix(via_service)[kind.code] == ["email"]

        via_form = support.make_employee()
        client = support.logged_in(via_form)
        response = client.post(ME_URL, {"table": "1", "cell": [f"{kind.code}:email", f"{kind.code}:push"]})
        assert response.status_code == 302, response.status_code
        assert _my_matrix(via_form)[kind.code] == ["email"]


def test_my_notifications_table_cell_outside_kind_channels_has_no_box():
    """FR-631: в таблице «Моих уведомлений» ячейка вне `kind.channels` — `td[data-channel]` без флажка, с
    `data-available="0"` и без подсказки привязки; допустимая ячейка с флажком."""
    kind = _kind("x.only_mail", channels=("portal", "email"), default=("portal", "email"))
    with _added(kind):
        client = support.logged_in(support.make_employee())
        response = client.get(ME_URL)
        assert response.status_code == 200
        row = tree(response).first("tr", data_notify_kind=kind.code)
        assert row is not None, "строки вида нет в таблице"
        cells = _cells_of(row)
        assert cells["email"].find("input", type="checkbox", name="cell")
        for channel in ("push", "telegram", "max"):
            assert cells[channel].attrs.get("data-available") == "0", channel
            assert not cells[channel].find("input"), f"ячейка {channel} вне channels с флажком"
            assert not cells[channel].find(data_hint=True), f"ячейка {channel} вне channels с подсказкой"


def test_admin_rows_and_post_parsing_drop_channel_outside_kind_channels():
    """FR-631: в таблице значений по умолчанию администратора ячейка вне `kind.channels` — без флажка, с
    `data-available="0"`; присланная в обход формы ячейка вне перечня при разборе POST отбрасывается."""
    kind = _kind("x.only_mail", channels=("portal", "email"), default=("portal", "email"))
    with _added(kind):
        admin = support.make_admin()
        client = support.logged_in(admin)
        response = client.get(ADMIN_URL)
        assert response.status_code == 200
        table = tree(response).first("table", data_defaults_table=True)
        row = table.first("tr", data_notify_kind=kind.code)
        assert row is not None
        cells = _cells_of(row)
        assert cells["email"].find("input", type="checkbox", name="cell")
        for channel in ("push", "telegram", "max"):
            assert cells[channel].attrs.get("data-available") == "0", channel
            assert not cells[channel].find("input"), f"ячейка {channel} вне channels с флажком"
        posted = client.post(ADMIN_URL, {"defaults_present": "1",
                                         "cell": [f"{kind.code}:email", f"{kind.code}:push", f"{kind.code}:telegram"]})
        assert posted.status_code == 302, posted.status_code
        assert _defaults()[kind.code] == ["email"]


def test_normalized_defaults_drop_channel_outside_kind_channels():
    """FR-631: `settings._normalized_defaults` и `settings.update` отбрасывают канал вне `kind.channels` (вид только с
    порталом остаётся с пустым списком); неизвестный канал по-прежнему отказ `bad_defaults`."""
    from apps.notify.services import settings as notify_settings
    from apps.notify.services.errors import NotifyError

    only_mail = _kind("x.only_mail", channels=("portal", "email"))
    only_portal = _kind("x.only_portal", channels=("portal",))
    plain = _kind("x.plain")
    with _added(only_mail, only_portal, plain):
        given = {only_mail.code: ["push", "email", "telegram", "max"], only_portal.code: ["email", "push"],
                 plain.code: ["push", "telegram"]}
        expected = {only_mail.code: ["email"], only_portal.code: [], plain.code: ["push", "telegram"]}
        assert notify_settings._normalized_defaults(given) == expected
        notify_settings.update(actor=support.make_admin(), defaults=given)
        saved = notify_settings.get().defaults
        assert {code: saved[code] for code in expected} == expected
        with pytest.raises(NotifyError) as refused:
            notify_settings._normalized_defaults({only_mail.code: ["fax"]})
        assert refused.value.code == "bad_defaults"


def test_kind_without_channels_keeps_cells_and_channels_as_before():
    """FR-631: у вида без `channels` всё прежнее: `_listed` и `channels_for` берут любые внешние каналы, ячейки таблицы
    все на месте (флажки у «Почты» и «Push», подсказки у каналов без привязки), у администратора — четыре флажка,
    сохранение принимает любой допустимый канал."""
    from apps.notify.services import prefs

    plain = _kind("x.plain", default=("portal", "email", "push"))
    with _added(plain):
        assert prefs._listed(plain, {}, {}) == ["email", "push"]
        assert prefs._listed(plain, {plain.code: ["push", "telegram", "max"]}, {}) == ["push", "telegram", "max"]
        assert prefs._listed(plain, {}, {plain.code: ["email", "max"]}) == ["email", "max"]
        user = support.make_employee()
        cells = {row.kind.code: row.cells for row in prefs.effective(user).rows}[plain.code]
        assert set(cells) == {"portal", "email", "push", "telegram", "max"}

        page = tree(support.logged_in(user).get(ME_URL))
        row = page.first("tr", data_notify_kind=plain.code)
        shown = _cells_of(row)
        assert shown["email"].find("input", type="checkbox") and shown["push"].find("input", type="checkbox")
        assert shown["telegram"].find(data_hint=True) and shown["max"].find(data_hint=True), (
            "у каналов без привязки подсказка прежняя")

        admin_page = tree(support.logged_in(support.make_admin()).get(ADMIN_URL))
        admin_row = admin_page.first("table", data_defaults_table=True).first("tr", data_notify_kind=plain.code)
        assert all(cell.find("input", type="checkbox") for cell in _cells_of(admin_row).values())

        assert prefs.save(user, table={plain.code: ["push"]}) is True
        assert _my_matrix(user)[plain.code] == ["push"]


# --- склейка с обновлением текста ----------------------------------------------------------------------------------

@pytest.fixture
def env(bus, clock):
    """Каталог видов и подписки шины пусты, часы стоят в рабочем времени."""
    from apps.core import extensions

    with extensions.empty():
        clock.set(WORK)
        yield clock


def _register(*, text_fn=None, coalesce=True):
    from apps.core.extensions import NotificationKind

    kind = NotificationKind(code=KIND, title="Тестовый вид", module="Проба", events=("test.happened",),
                            external_text="Есть новое", default_channels=("portal", "email"), coalesce=coalesce,
                            coalesce_text=text_fn)
    notify.register_kind(kind)
    return kind


def _draft(user, text="Событие", url="/test/", ref=REF):
    from apps.core.extensions import Draft

    return Draft(user_id=user.pk, text=text, url=url, object_ref=ref)


def _create(capture, drafts) -> list[int]:
    from apps.notify.services import dispatch

    with capture(execute=True):
        return dispatch.create(KIND, drafts)


def _notes(user):
    return model("notify.Notification").objects.filter(user=user, kind=KIND)


def _read(note) -> None:
    model("notify.Notification").objects.filter(pk=note.pk).update(read_at=WORK)


def test_coalesce_text_updates_unread_text_with_since_as_its_creation_time(env, django_capture_on_commit_callbacks):
    """FR-629: при склейке с заданным `coalesce_text` текст непрочитанного уведомления становится значением функции
    `coalesce_text(user_id, object_ref, since)`, где `since` — время создания непрочитанного (оно не меняется);
    для получателя без непрочитанного уведомление создаётся как обычно и функция не зовётся; после «прочитано»
    склейки нет."""
    calls = []

    def text_of(user_id, object_ref, since):
        calls.append((user_id, object_ref, since))
        return f"Склейка {len(calls)}"

    _register(text_fn=text_of)
    holder, fresh = support.make_employee(), support.make_employee()
    assert len(_create(django_capture_on_commit_callbacks, [_draft(holder, "Первое")])) == 1
    note = _notes(holder).get()
    assert note.created_at == WORK and calls == []
    env.advance(minutes=5)
    created = _create(django_capture_on_commit_callbacks, [_draft(holder, "Второе"), _draft(fresh, "Свежее")])
    fresh_note = _notes(fresh).get()
    assert created == [fresh_note.pk] and fresh_note.text == "Свежее"
    assert calls == [(holder.pk, REF, WORK)], "since — время создания непрочитанного, а не момент склейки"
    note.refresh_from_db()
    assert note.text == "Склейка 1" and note.created_at == WORK and note.read_at is None
    env.advance(minutes=5)
    assert _create(django_capture_on_commit_callbacks, [_draft(holder, "Третье")]) == []
    assert calls[1] == (holder.pk, REF, WORK), "since прежний: время создания не сдвигается"
    note.refresh_from_db()
    assert note.text == "Склейка 2" and _notes(holder).count() == 1
    _read(note)
    assert len(_create(django_capture_on_commit_callbacks, [_draft(holder, "Четвёртое")])) == 1
    assert len(calls) == 2, "после «прочитано» склейки нет и функция не зовётся"
    assert _notes(holder).count() == 2


def test_coalesce_text_update_happens_under_coalesce_key_lock(env, django_capture_on_commit_callbacks):
    """FR-629: функция текста зовётся и текст записывается под прежним транзакционным замком ключа склейки
    (`pg_advisory_xact_lock` с ключом `<user_id>:<код вида>:<object_ref>`): замок раньше вызова функции, вызов —
    раньше `UPDATE` уведомления."""
    timeline = []

    def text_of(user_id, object_ref, since):
        timeline.append(("<coalesce_text>", None))
        return "Обновлённый текст"

    def recorder(execute, sql, params, many, context):
        timeline.append((sql, params))
        return execute(sql, params, many, context)

    _register(text_fn=text_of)
    holder = support.make_employee()
    _create(django_capture_on_commit_callbacks, [_draft(holder, "Первое")])
    timeline.clear()
    with connection.execute_wrapper(recorder):
        assert _create(django_capture_on_commit_callbacks, [_draft(holder, "Второе")]) == []
    locks = [i for i, (sql, _) in enumerate(timeline) if "pg_advisory_xact_lock" in sql]
    called = [i for i, (sql, _) in enumerate(timeline) if sql == "<coalesce_text>"]
    updates = [i for i, (sql, _) in enumerate(timeline) if re.search(r'UPDATE "?notify_notification"?', sql)]
    assert locks and called and updates, [sql[:80] for sql, _ in timeline]
    assert locks[0] < called[0] < updates[0]
    assert f"{holder.pk}:{KIND}:{REF}" in timeline[locks[0]][1]
    assert _notes(holder).get().text == "Обновлённый текст"


def test_coalesce_text_update_keeps_url_and_sends_no_bell_frame(env, django_capture_on_commit_callbacks, monkeypatch):
    """FR-629: при обновлении текста склейкой адрес непрочитанного уведомления не меняется (ссылка ведёт к первому
    непрочитанному), а кадр колокольчику не шлётся: число не изменилось."""
    sent = []

    class Layer:
        async def group_send(self, group, message):
            sent.append((group, message))

    monkeypatch.setattr("apps.notify.services.live.get_channel_layer", lambda *args, **kwargs: Layer())
    _register(text_fn=lambda user_id, object_ref, since: "Новых комментариев: 2")
    holder = support.make_employee()
    _create(django_capture_on_commit_callbacks, [_draft(holder, "Первое", url="/feed/15/#c1")])
    sent.clear()
    assert _create(django_capture_on_commit_callbacks, [_draft(holder, "Второе", url="/feed/15/#c2")]) == []
    note = _notes(holder).get()
    assert note.text == "Новых комментариев: 2" and note.url == "/feed/15/#c1"
    assert sent == [], "кадр колокольчику при обновлении текста не шлётся"


def test_coalesce_without_coalesce_text_keeps_first_text_as_before(env, django_capture_on_commit_callbacks):
    """FR-629: у вида со склейкой, но без `coalesce_text` — прежний пропуск: нового уведомления нет, текст и адрес
    первого не меняются (как у видов базы знаний)."""
    _register(text_fn=None)
    holder = support.make_employee()
    assert len(_create(django_capture_on_commit_callbacks, [_draft(holder, "Первое", url="/test/first/")])) == 1
    assert _create(django_capture_on_commit_callbacks, [_draft(holder, "Второе", url="/test/second/")]) == []
    held = list(_notes(holder))
    assert len(held) == 1 and held[0].text == "Первое" and held[0].url == "/test/first/"
    assert held[0].read_at is None
