"""T-6116: вид уведомления `lists.deadline` — запись вида, тексты, ссылки, внешний текст, `still_relevant`, уборка
(FR-525, FR-530, FR-531, FR-533, NFR-511). Сценарий 8 спеки среза 006.

Вид в каталоге «Мои уведомления» (раздел 7.1 контракта), тексты `Draft.text` и обрезка (7.2, решение 53 задач),
ссылки по группам получателей и подмена `dispatch.create` (4.3, 5.8), `object_ref` (решение 38 задач), внешний текст
(`NotificationKind.external_text_of`, `kinds.external_text`, Telegram, MAX, Web Push и тема письма), перенос срока при
непрочитанном прежнем уведомлении, `still_relevant`, ссылка после удаления и архива, уборка `ImportJob` и `ReminderSent`.
Код среза на уровне модуля не импортируется (CONTRACT-006, шапка): службы берутся внутри тестов.
"""
import dataclasses
import html as html_lib
import importlib
import re
from datetime import date, timedelta
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from django.utils import timezone

from tests import support
from tests import support_lists as lists
from tests import support_notify as notify_support
from tests.support import model

pytestmark = pytest.mark.django_db

KIND = "lists.deadline"
TODAY = date(2026, 3, 10)
EXPIRING = "Истекает срок в записи списка"
REACHED = "Срок в записи списка наступил"
PINNED = "/me/#lists-pinned"
BUTTON = "Открыть уведомления"
REF = re.compile(r"^lists\.record:(\d+):(\d+):(\d+)$")
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- разбор разметки (помощник только этого файла; образец — test_lists_records_2.py) --------------------------

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

    def text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                if isinstance(child, Node):
                    collect(child)
                else:
                    parts.append(child)

        collect(self)
        return " ".join("".join(parts).split())


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


def q(scope, tag=None, **attrs) -> list:
    """Потомки `scope` по тегу и атрибутам; имя с дефисом пишется через `_`."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            found.append(node)
    return found


# --- помощники только этого файла ---------------------------------------------------------------------------

def _kinds():
    return importlib.import_module("apps.notify.services.kinds")


def _kind():
    return _kinds().get(KIND)


def _cut(text: str) -> str:
    """Правило обрезки контракта 7.2: длиннее 100 знаков — первые 99 и «…»."""
    return text if len(text) <= 100 else text[:99] + "…"


def _chars(length: int, start: int = 0x430) -> str:
    """Строка из `length` русских знаков (повтор алфавита, без пробелов)."""
    return "".join(chr(start + i % 32) for i in range(length))


def _ru(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def _scene(clock, *, days: int = 7, thresholds=(7,), list_name: str = "Оборудование ИТ", title: str = "Ноутбук Лидер",
           field_name: str = "Срок гарантии", people=("reader", "outsider"), with_editor: bool = False):
    """Список с полем-сроком (`date`, `deadline`, `thresholds`) и полем «сотрудник»; запись со сроком через `days` дней
    от `TODAY`. Часы — полдень `TODAY` по Москве. Читающий (`reader`) и сотрудник без прав на список (`outsider`) стоят
    в поле «сотрудник»; правящий (`editor`) в поле не стоит, он в наборе «Правят»."""
    clock.set(lists.moscow(2026, 3, 10, 12))
    lst = lists.make_list(list_name)
    date_field = lists.add_field(lst, "date", field_name, deadline=True, thresholds=thresholds)
    person_field = lists.add_field(lst, "person", "Ответственный")
    reader_session = lists.as_reader(lst) if "reader" in people else None
    outsider = support.make_employee() if "outsider" in people else None
    editor_session = lists.as_editor(lst) if with_editor else None
    ids = [u.pk for u in (reader_session and reader_session.user, outsider) if u is not None]
    due = TODAY + timedelta(days=days)
    record = lists.make_record(lst, title, {date_field.code: due.isoformat(), person_field.code: ids})
    return SimpleNamespace(
        lst=lst, date_field=date_field, person_field=person_field, record=record, due=due,
        reader_session=reader_session, reader=reader_session.user if reader_session else None, outsider=outsider,
        editor_session=editor_session, editor=editor_session.user if editor_session else None)


def _notes(user) -> list:
    return list(model("notify.Notification").objects.filter(user=user, kind=KIND).order_by("pk"))


def _one_note(user):
    notes = _notes(user)
    assert len(notes) == 1, (user.pk, [n.text for n in notes])
    return notes[0]


def _delivery(note, channel: str):
    """Доставка по каналу: уже созданная службой уведомлений или новая, готовая к отправке."""
    now = timezone.now()
    row, _ = model("notify.Delivery").objects.get_or_create(
        notification=note, channel=channel,
        defaults={"state": "waiting", "due_at": now - timedelta(seconds=5), "enqueued_at": now})
    return row


def _row_codes(root) -> list[str]:
    return [row.attrs["data-notify-kind"] for row in q(root, "tr", data_notify_kind=True)]


# --- запись вида (раздел 7.1) -----------------------------------------------------------------------------------

def test_deadline_kind_registered_with_title_module_default_channels_order_60_and_no_coalesce():
    """FR-531: вид `lists.deadline` в каталоге один; название «Срок в записи списка», модуль «Списки», без событий и
    без построителя, запасной внешний текст, каналы по умолчанию «На портале» и «Почта», не обязательный,
    `order` 60 (после видов базы знаний, до видов ядра), `coalesce` ложно; точка `notification_kinds` модуля
    отдаёт ровно этот вид."""
    kind = _kind()
    assert kind.code == KIND
    assert kind.title == "Срок в записи списка"
    assert kind.module == "Списки"
    assert kind.events == ()
    assert kind.build("lists.any_event", {}) == []
    assert kind.external_text == EXPIRING
    assert tuple(kind.default_channels) == ("portal", "email")
    assert kind.mandatory is False
    assert kind.order == 60
    assert kind.coalesce is False

    codes = [item.code for item in _kinds().catalog()]
    assert codes.count(KIND) == 1
    assert codes.index("knowledge.rubric_subscription") < codes.index(KIND) < codes.index("core.new_device")

    notify_kinds = importlib.import_module("apps.lists.notify_kinds")
    assert [item.code for item in notify_kinds.notification_kinds()] == [KIND]


def test_deadline_kind_available_and_shown_in_my_notifications_to_employee_without_list_rights():
    """FR-531: вид доступен любому сотруднику, в том числе без прав на списки; в «Мои уведомления» у него строка
    `tr[data-notify-kind="lists.deadline"]` с названием «Срок в записи списка» и модулем «Списки», «На портале»
    отмечен и заблокирован, «Почта» отмечена по умолчанию; в порядке каталога строка стоит после вида «по подписке»
    базы знаний."""
    user = support.make_employee()
    lists.make_list("Чужой список")
    assert _kind().available(user) is True

    response = support.logged_in(user).get("/me/notifications/")
    assert response.status_code == 200
    root = tree(response)
    codes = _row_codes(root)
    assert KIND in codes
    assert codes.index("knowledge.rubric_subscription") < codes.index(KIND)
    row = q(root, "tr", data_notify_kind=KIND)[0]
    assert q(row, None, data_field="title")[0].text() == "Срок в записи списка"
    assert q(row, None, data_field="module")[0].text() == "Списки"
    portal = q(row, "td", data_channel="portal")[0]
    assert portal.attrs.get("data-locked") == "1"
    box = q(portal, "input", type="checkbox")[0]
    assert "checked" in box.attrs and "disabled" in box.attrs
    email = q(row, "td", data_channel="email")[0]
    assert "checked" in q(email, "input", type="checkbox")[0].attrs


# --- тексты на портале (раздел 7.2) -----------------------------------------------------------------------------

def test_deadline_portal_text_expiring_has_list_record_field_and_date_dd_mm_yyyy(clock):
    """FR-530, FR-531: за 7 дней у обоих получателей (читающий и сотрудник без прав) — «Истекает срок: <список> —
    <название>: <поле> <ДД.ММ.ГГГГ>» с датой срока; обход создаёт два уведомления."""
    scene = _scene(clock, days=7)
    result = lists.run_reminders(TODAY)

    expected = "Истекает срок: Оборудование ИТ — Ноутбук Лидер: Срок гарантии 17.03.2026"
    assert expected == f"Истекает срок: {scene.lst.name} — {scene.record.title}: {scene.date_field.name} {_ru(scene.due)}"
    assert _one_note(scene.reader).text == expected
    assert _one_note(scene.outsider).text == expected
    assert result.notified == 2 and result.failed == []


def test_deadline_portal_text_reached_on_threshold_zero(clock):
    """FR-530, FR-531: в день срока — «Срок наступил: <список> — <название>: <поле> <ДД.ММ.ГГГГ>» с датой срока
    (сегодняшней)."""
    scene = _scene(clock, days=0)
    lists.run_reminders(TODAY)

    expected = "Срок наступил: Оборудование ИТ — Ноутбук Лидер: Срок гарантии 10.03.2026"
    assert _one_note(scene.reader).text == expected
    assert _one_note(scene.outsider).text == expected


def test_deadline_text_with_list_record_and_field_names_of_max_length_cuts_each_to_100_with_ellipsis_and_whole_text_to_300(
        clock):
    """FR-531: название записи в 200 знаков входит первыми 99 знаками и «…» (итого 100), список и поле по 100 знаков
    остаются целыми; при названиях самой большой длины строка (331 знак) обрезается до 299 знаков и «…» (итого 300,
    решение 53 задач)."""
    Record, List, Field = model("lists.Record"), model("lists.List"), model("lists.Field")
    list_max = List._meta.get_field("name").max_length
    title_max = Record._meta.get_field("title").max_length
    field_max = Field._meta.get_field("name").max_length
    assert (list_max, title_max, field_max) == (100, 200, 100)

    list_name, title, field_name = _chars(list_max), _chars(title_max, 0x410), "ф" + _chars(field_max - 1)
    scene = _scene(clock, days=7, list_name=list_name, title=title, field_name=field_name, people=("reader",))
    lists.run_reminders(TODAY)

    full = f"Истекает срок: {list_name} — {_cut(title)}: {field_name} 17.03.2026"
    assert len(_cut(title)) == 100 and _cut(title).endswith("…") and len(full) == 331
    text = _one_note(scene.reader).text
    assert len(text) == 300 and text.endswith("…")
    assert text == full[:299] + "…"

    short_scene = _scene(clock, days=7, list_name="Короткий список", title=_chars(title_max, 0x410),
                         field_name="Срок", people=("reader",))
    lists.run_reminders(TODAY)
    short = _one_note(short_scene.reader).text
    assert short == f"Истекает срок: Короткий список — {_cut(_chars(title_max, 0x410))}: Срок 17.03.2026"
    assert len(short) <= 300 and "…" in short


# --- ссылки и вызовы `dispatch.create` ---------------------------------------------------------------------------

def test_deadline_link_to_record_card_for_list_reader_and_to_pinned_section_for_others(clock):
    """FR-530, FR-531, FR-525: читающий список и правящий (из набора «Правят», не из поля) получают ссылку на карточку
    записи `/lists/<id>/<n>/`; сотрудник из поля без права на список — `/me/#lists-pinned`, и на его странице `/me/`
    запись есть в разделе «Закреплённое» без ссылки на список."""
    scene = _scene(clock, days=7, with_editor=True)
    lists.run_reminders(TODAY)

    card = f"/lists/{scene.lst.pk}/{scene.record.number}/"
    assert _one_note(scene.reader).url == card
    assert _one_note(scene.editor).url == card
    assert _one_note(scene.outsider).url == PINNED
    outsider_client = support.logged_in(scene.outsider)
    assert outsider_client.get(card).status_code == 404

    page = outsider_client.get("/me/")
    assert page.status_code == 200
    blocks = q(tree(page), None, id="lists-pinned", data_lists_pinned=True)
    assert len(blocks) == 1
    rows = q(blocks[0], "li", data_pinned_record=True)
    assert [row for row in rows if scene.record.title in row.text()], "запись не в «Закреплённом» сотрудника"
    assert not q(blocks[0], "a"), "сотруднику без права на список ссылка на список не нужна"


def test_deadline_dispatch_create_called_separately_for_readers_and_others(clock, monkeypatch):
    """FR-530, FR-531: `dispatch.create` зовётся отдельно для читающих (читающий и правящий, ссылка на карточку) и для
    остальных (ссылка на «Закреплённое»); вид вызова — `lists.deadline`; группа без получателей — вызова нет
    (только сотрудник без прав — один вызов, только читающий — один вызов)."""
    from apps.notify.services import dispatch

    real, calls = dispatch.create, []

    def spy(kind_code, drafts):
        drafts = list(drafts)
        calls.append((kind_code, drafts))
        return real(kind_code, drafts)

    monkeypatch.setattr("apps.notify.services.dispatch.create", spy)

    def groups() -> dict:
        found = {}
        for kind_code, drafts in calls:
            assert kind_code == KIND
            assert drafts, "вызов с пустым списком черновиков"
            urls = {draft.url for draft in drafts}
            assert len(urls) == 1, "в одном вызове ссылки разные"
            found.setdefault(urls.pop(), []).extend(draft.user_id for draft in drafts)
        return found

    scene = _scene(clock, days=7, with_editor=True)
    lists.run_reminders(TODAY)
    card = f"/lists/{scene.lst.pk}/{scene.record.number}/"
    assert len(calls) == 2
    assert {url: sorted(ids) for url, ids in groups().items()} == {
        card: sorted([scene.reader.pk, scene.editor.pk]), PINNED: [scene.outsider.pk]}

    calls.clear()
    only_outsider = _scene(clock, days=7, list_name="Только без прав", people=("outsider",))
    lists.run_reminders(TODAY)
    assert len(calls) == 1
    assert groups() == {PINNED: [only_outsider.outsider.pk]}

    calls.clear()
    only_reader = _scene(clock, days=7, list_name="Только читающий", people=("reader",))
    lists.run_reminders(TODAY)
    assert len(calls) == 1
    assert groups() == {f"/lists/{only_reader.lst.pk}/{only_reader.record.number}/": [only_reader.reader.pk]}


# --- `object_ref` и внешний текст ---------------------------------------------------------------------------------

def test_deadline_object_ref_has_record_field_threshold_and_fits_38_chars_with_10_digit_ids(clock):
    """FR-531: `object_ref` — `lists.record:<id записи>:<id поля>:<порог>` с настоящими номерами записи и поля и
    порогом 7 (за 7 дней) или 0 (в день срока); при номерах до 10 цифр и пороге до 3 цифр длина не больше 38 знаков
    (решение 38 задач), а значит, и предела 64 колонки `Notification.object_ref`."""
    scene = _scene(clock, days=7)
    lists.run_reminders(TODAY)
    ref = _one_note(scene.reader).object_ref
    match = REF.match(ref)
    assert match, ref
    assert tuple(int(part) for part in match.groups()) == (scene.record.pk, scene.date_field.pk, 7)
    assert _one_note(scene.outsider).object_ref == ref

    reached = _scene(clock, days=0, list_name="Срок сегодня")
    lists.run_reminders(TODAY)
    ref_zero = _one_note(reached.reader).object_ref
    assert tuple(int(part) for part in REF.match(ref_zero).groups()) == (
        reached.record.pk, reached.date_field.pk, 0)

    prefix = ref.split(":")[0]
    longest = ":".join([prefix, "9" * 10, "9" * 10, "9" * 3])
    assert REF.match(longest) and len(longest) <= 38
    assert len(longest) <= model("notify.Notification")._meta.get_field("object_ref").max_length == 64


def test_deadline_external_text_of_reached_for_zero_threshold_and_expiring_otherwise():
    """FR-531: `external_text_of(object_ref)` вида — «Срок в записи списка наступил» при пороге 0 и «Истекает срок в
    записи списка» при любом другом пороге; та же функция — `deadline_external_text` модуля."""
    notify_kinds = importlib.import_module("apps.lists.notify_kinds")
    kind = _kind()

    for ref in ("lists.record:5:6:0", "lists.record:1234567890:1234567890:0"):
        assert kind.external_text_of(ref) == REACHED
        assert notify_kinds.deadline_external_text(ref) == REACHED
    for ref in ("lists.record:5:6:7", "lists.record:5:6:1", "lists.record:5:6:30", "lists.record:5:6:100",
                "lists.record:1234567890:1234567890:999"):
        assert kind.external_text_of(ref) == EXPIRING, ref
        assert notify_kinds.deadline_external_text(ref) == EXPIRING, ref


def test_notify_kinds_external_text_uses_external_text_of_and_falls_back_to_former_external_text():
    """FR-531: у `NotificationKind` тринадцать полей, последнее — `external_text_of` (по умолчанию `None`);
    `kinds.external_text(kind, object_ref)` берёт текст из `external_text_of`, а без него — прежний `external_text`;
    у вида `lists.deadline` — текст по порогу из ссылки; у видов базы знаний текст прежний."""
    from apps.core.extensions import NotificationKind

    names = [field.name for field in dataclasses.fields(NotificationKind)]
    assert len(names) == 13 and names[-1] == "external_text_of" and names[-2] == "coalesce"

    plain = NotificationKind(code="x.plain", title="Простой", module="Проба", external_text="Прежний текст")
    assert plain.external_text_of is None
    computed = NotificationKind(code="x.computed", title="Вычисляемый", module="Проба", external_text="Запасной",
                                external_text_of=lambda ref: "Из ссылки " + ref)

    kinds = _kinds()
    assert kinds.external_text(plain, "any:1") == "Прежний текст"
    assert kinds.external_text(computed, "a:b") == "Из ссылки a:b"
    assert kinds.external_text(_kind(), "lists.record:1:2:0") == REACHED
    assert kinds.external_text(_kind(), "lists.record:1:2:7") == EXPIRING
    assert kinds.external_text(kinds.get("knowledge.my_article_changed"), "knowledge.article:1") == "Вашу статью изменили"


def test_delivery_external_text_and_mail_subject_have_no_record_or_list_name(clock):
    """FR-531: внешний текст доставки Telegram, MAX и Web Push и тема письма — «Истекает срок в записи списка» (за 7
    дней) или «Срок в записи списка наступил» (в день срока); названий списка и записи в них нет, хотя в
    `Notification.text` они есть."""
    from apps.notify.services import delivery as dlv
    from apps.notify.services import mail as notify_mail

    for days, expected, list_name, title in ((7, EXPIRING, "УникальныйСписокЭ", "УникальнаяЗаписьЭ"),
                                             (0, REACHED, "УникальныйСписокН", "УникальнаяЗаписьН")):
        scene = _scene(clock, days=days, list_name=list_name, title=title)
        lists.run_reminders(TODAY)
        for user in (scene.reader, scene.outsider):
            note = _one_note(user)
            assert list_name in note.text and title in note.text
            for channel in ("telegram", "max", "webpush"):
                text = dlv.external_text(_delivery(note, channel))
                assert text == expected, (days, channel)
            message_id = notify_mail.queue_item(_delivery(note, "email"))
            subject = model("mail.MailMessage").objects.get(pk=message_id).subject
            assert subject == expected, days
            for marker in (list_name, title, "Срок гарантии", "Уникальн"):
                assert marker not in subject, (days, marker)


def test_telegram_max_and_webpush_send_generic_text_without_record_or_list_name(clock, bots_on, webpush_on):
    """FR-531: сообщение бота — экранированный внешний текст и кнопка на страницу уведомлений; нагрузка Web Push —
    внешний текст и ссылка `/notifications/`; названий списка и записи в них нет; при пороге 0 текст «Срок в записи
    списка наступил»."""
    from django.conf import settings

    from apps.notify.services import delivery as dlv

    link = settings.PORTAL_URL.rstrip("/") + "/notifications/"
    pair = notify_support.browser_keys()
    subs: dict = {}

    for days, expected, list_name, title in ((7, EXPIRING, "УникальныйСписокЭ", "УникальнаяЗаписьЭ"),
                                             (0, REACHED, "УникальныйСписокН", "УникальнаяЗаписьН")):
        scene = _scene(clock, days=days, list_name=list_name, title=title, people=("reader",))
        lists.run_reminders(TODAY)
        user = scene.reader
        note = _one_note(user)
        chats = {channel: model("notify.ChatBinding").objects.get_or_create(
            user=user, channel=channel, defaults={"chat_id": f"c{user.pk}{channel}"})[0].chat_id
            for channel in ("telegram", "max")}
        if user.pk not in subs:
            subs[user.pk] = notify_support.subscribe(user, keys=pair)
        for channel in ("telegram", "max"):
            row = _delivery(note, channel)
            with notify_support.fake_bot_send(channel) as fake:
                assert dlv.send_delivery(row.pk) == "sent"
            assert fake.calls == [(chats[channel], html_lib.escape(expected), (BUTTON, link))], (days, channel)
        row = _delivery(note, "webpush")
        with notify_support.webpush_capture() as capture:
            assert dlv.send_delivery(row.pk) == "sent"
        assert [r.url for r in capture.requests] == [subs[user.pk].endpoint]
        payload = capture.decrypt(capture.requests[0], pair)
        assert payload == {"title": expected, "url": "/notifications/", "tag": f"n-{note.pk}"}, days
        assert list_name not in str(payload) and title not in str(payload)


# --- перенос срока ------------------------------------------------------------------------------------------------

def test_moved_deadline_with_unread_previous_notification_creates_new_notification_same_threshold(clock):
    """FR-530, FR-531: срок перенесли, прежнее уведомление по порогу 7 не прочитано — на новую дату по тому же порогу
    создаётся ещё одно уведомление (вид не склеивается): у каждого получателя два непрочитанных с одним `object_ref` и
    разными датами в тексте; отметок `ReminderSent` с порогом 7 две, по одной на дату."""
    scene = _scene(clock, days=7)
    first = lists.run_reminders(TODAY)
    assert first.notified == 2
    old_ref = _one_note(scene.reader).object_ref

    moved = TODAY + timedelta(days=14)
    scene.record.values[scene.date_field.code] = moved.isoformat()
    scene.record.save(update_fields=["values"])
    clock.set(lists.moscow(2026, 3, 17, 12))
    second = lists.run_reminders(TODAY + timedelta(days=7))

    assert second.notified == 2
    for user in (scene.reader, scene.outsider):
        notes = _notes(user)
        assert len(notes) == 2, [n.text for n in notes]
        assert all(n.read_at is None for n in notes)
        assert {n.object_ref for n in notes} == {old_ref}
        assert [n.text.rsplit(" ", 1)[1] for n in notes] == ["17.03.2026", "24.03.2026"]
    marks = model("lists.ReminderSent").objects.filter(record=scene.record, threshold_days=7)
    assert sorted(marks.values_list("due_date", flat=True)) == [TODAY + timedelta(days=7), moved]


# --- still_relevant -----------------------------------------------------------------------------------------------

def test_still_relevant_false_for_dismissed_recipient_or_deleted_record(clock):
    """FR-531: `still_relevant` истинно для действующего получателя и существующей записи; ложно для уволенного
    получателя и после удаления записи (проверка отличия: тот же получатель и та же ссылка до удаления дают
    истину); заблокированный получатель — истина (правило «не уволен»)."""
    scene = _scene(clock, days=7)
    still = _kind().still_relevant
    ref = f"lists.record:{scene.record.pk}:{scene.date_field.pk}:7"
    dismissed = support.make_employee(state="dismissed")
    blocked = support.make_employee(state="blocked")

    assert still(scene.reader.pk, ref) is True
    assert still(blocked.pk, ref) is True
    assert still(dismissed.pk, ref) is False

    scene.record.delete()
    assert still(scene.reader.pk, ref) is False
    assert still(scene.outsider.pk, ref) is False
    assert still(dismissed.pk, ref) is False


def test_still_relevant_true_for_recipient_without_list_access(clock):
    """FR-531: доступ к списку `still_relevant` не проверяет: сотрудник из поля записи без права на список (карточка
    записи ему закрыта — 404) остаётся получателем и для записи в архиве."""
    scene = _scene(clock, days=7)
    still = _kind().still_relevant
    ref = f"lists.record:{scene.record.pk}:{scene.date_field.pk}:7"
    card = f"/lists/{scene.lst.pk}/{scene.record.number}/"

    assert support.logged_in(scene.outsider).get(card).status_code == 404
    assert still(scene.outsider.pk, ref) is True
    lists.archive(scene.record)
    assert still(scene.outsider.pk, ref) is True
    assert still(scene.reader.pk, ref) is True


def test_deadline_link_after_deletion_shows_record_deleted_and_after_archive_card_with_mark(clock):
    """FR-531: ссылка из уведомления у читающего ведёт на карточку записи; после переноса записи в архив — та же
    карточка с пометкой `[data-lists-archived]` «в архиве»; после удаления записи навсегда — 404 со страницей
    «Запись удалена» (`[data-lists-page="gone"]`)."""
    scene = _scene(clock, days=7, people=("reader",))
    lists.run_reminders(TODAY)
    url = _one_note(scene.reader).url
    assert url == f"/lists/{scene.lst.pk}/{scene.record.number}/"
    client = scene.reader_session.client

    live = client.get(url)
    assert live.status_code == 200
    assert q(tree(live), None, data_lists_record=True)
    assert not q(tree(live), None, data_lists_archived=True)

    lists.archive(scene.record)
    archived = client.get(url)
    assert archived.status_code == 200
    marks = q(tree(archived), None, data_lists_archived=True)
    assert marks and "в архиве" in marks[0].text()

    scene.record.delete()
    gone = client.get(url)
    assert gone.status_code == 404
    assert "Запись удалена" in gone.content.decode("utf-8")
    assert q(tree(gone), None, data_lists_page="gone")


# --- уборка (шаг 5 плана) -----------------------------------------------------------------------------------------

def test_cleanup_deletes_import_jobs_of_any_state_older_than_one_day_and_keeps_fresh(clock):
    """FR-533: после обхода сроков удалены задания загрузки в любом из трёх состояний (`mapping`, `preview`, `done`)
    старше суток (двое суток назад), свежие (час назад) остались."""
    scene = _scene(clock, days=60, people=("reader",))
    ImportJob = model("lists.ImportJob")
    now = timezone.now()
    old, fresh = {}, {}
    for state in ("mapping", "preview", "done"):
        for bucket, age in ((old, timedelta(days=2)), (fresh, timedelta(hours=1))):
            bucket[state] = ImportJob.objects.create(
                list=scene.lst, created_by=scene.reader, created_at=now - age, file_name=f"{state}.xlsx",
                file_format="xlsx", state=state, header=["Название"], mapping={}, rows=[], summary={}).pk

    result = lists.run_reminders(TODAY)

    assert result.failed == []
    assert set(ImportJob.objects.values_list("pk", flat=True)) == set(fresh.values())
    assert not ImportJob.objects.filter(pk__in=old.values()).exists()


def test_cleanup_deletes_reminder_marks_with_due_date_older_than_year_and_keeps_fresh(clock):
    """FR-530, NFR-511: после обхода удалены отметки `ReminderSent` со сроком раньше, чем год назад (400 и 380 дней),
    остались отметки со сроком 300 дней назад и в будущем; новых отметок обход не создал (срок записи далеко)."""
    scene = _scene(clock, days=60, people=("reader",))
    Sent = model("lists.ReminderSent")
    plan = [(7, TODAY - timedelta(days=400)), (3, TODAY - timedelta(days=380)),
            (7, TODAY - timedelta(days=300)), (0, TODAY + timedelta(days=5))]
    for threshold, due in plan:
        Sent.objects.create(record=scene.record, field=scene.date_field, threshold_days=threshold, due_date=due,
                            notified=True)

    result = lists.run_reminders(TODAY)

    assert result.notified == 0 and result.failed == []
    assert set(Sent.objects.values_list("threshold_days", "due_date")) == set(plan[2:])
