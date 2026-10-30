"""T-7128: уведомления ленты — каталог, тексты, каналы, склейка, `still_relevant` (FR-606, FR-629, FR-630, FR-631,
FR-632, NFR-605, NFR-609, NFR-611). Сценарий 9 спеки среза 007.

План: «Уведомления» (виды, склейка с обновлением текста, допустимые каналы вида, тексты, перед письмом и сводкой);
CONTRACT-007: 4.2, 5.5, 7.1–7.3, решения контракта К25, К26. Каталог — `apps.notify.services.kinds`, таблицы — страницы
`/me/notifications/` и `/settings/notifications/`, письма и сводка — `mail.send_due()` и `digest.build()`, доставка во
внешние каналы — `delivery.send_delivery()`. Действия идут службами среза. Код среза на уровне модуля не
импортируется: имена берутся внутри тестов (CONTRACT-007, шапка).
"""
import html as html_lib
import importlib
import re
from datetime import datetime, time, timedelta, timezone as dt_timezone
from html.parser import HTMLParser
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from tests import support
from tests import support_feed as fd
from tests import support_notify as notify_support
from tests.support import model

pytestmark = pytest.mark.django_db

FOR_YOU, MENTION, COMMENT = "feed.for_you", "feed.mention", "feed.comment"
IMPORTANT, INVITE, CHANGED, REMINDER, LIKE = (
    "feed.important", "feed.invite", "feed.event_changed", "feed.event_reminder", "feed.like")
EXTERNAL = {row[0]: row[7] for row in fd.FEED_KINDS}
BUTTON = "Открыть уведомления"
MSK = ZoneInfo("Europe/Moscow")
UTC = dt_timezone.utc
UNIQUE_AUTHOR, UNIQUE_TITLE, UNIQUE_PLACE, UNIQUE_WORD = "Виктор Уникальный", "УникальноеНазвание", "УникальноеМесто", "УникальныйОтрывок"


# --- помощники только этого файла ---------------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.feed.services.{name}")


def _kinds():
    return importlib.import_module("apps.notify.services.kinds")


def _prefs_service():
    return importlib.import_module("apps.notify.services.prefs")


def _notify_kinds():
    return importlib.import_module("apps.feed.notify_kinds")


def _p(user) -> str:
    return f"p{user.pk}"


def _mark(user) -> str:
    return f"@[{user.pk}]"


def _at(year, month, day, hour=0, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=MSK)


def _future(days: int = 3, hours: int = 0):
    return (timezone.now() + timedelta(days=days, hours=hours)).replace(second=0, microsecond=0)


def _writer(name: str = "Анна Автор") -> fd.Session:
    return fd.as_writer(full_name=name)


def _person(name: str | None = None, **extra):
    if name:
        extra["full_name"] = name
    return support.make_employee(**extra)


def _user_prefs(user, mode: str = "none", **over):
    """Строка `UserNotifySettings`: по умолчанию «Без тихих часов» (письмо не зависит от часов хоста)."""
    return model("notify.UserNotifySettings").objects.update_or_create(
        user=user, defaults={"quiet_mode": mode, **over})[0]


def _own_quiet(user, **over):
    """«Свои часы»: понедельник 09:00–18:00 по Москве; остальное время — тихие часы."""
    return _user_prefs(user, "own", own_days=[0], own_start=time(9, 0), own_end=time(18, 0), **over)


def _event(start, end=None, title: str = "Собрание отдела", place: str = "Корпус 1") -> dict:
    end = end or start + timedelta(hours=1)
    return {"event_title": title, "event_place": place, "event_start": fd.moscow_text(start),
            "event_end": fd.moscow_text(end)}


def _publish(author, text: str, *, to, kind: str = "post", **fields):
    return _svc("posts").publish(author.user, {"kind": kind, "text": text, "to": list(to), **fields})


def _publish_event(author, *, to, text: str = "", start=None, **over):
    return _publish(author, text, to=to, kind="event", **_event(start or _future(), **over))


def _saved_to(post) -> list:
    out = ["all"] if post.to_all else []
    for row in model("feed.Recipient").objects.filter(post=post, via="to").order_by("pk"):
        out.append(f"u{row.unit_id}" if row.kind == "unit" else f"p{row.user_id}")
    return out


def _edit(author, post, **over):
    post = model("feed.Post").objects.get(pk=post.pk)
    data = {"text": post.text, "to": _saved_to(post)}
    if post.kind == "event":
        data.update(event_title=post.event_title, event_place=post.event_place,
                    event_start=fd.moscow_text(post.event_start), event_end=fd.moscow_text(post.event_end))
    data.update(over)
    return _svc("posts").edit(author.user, post.pk, data)


def _notes(user=None, kind: str | None = None):
    found = model("notify.Notification").objects.filter(kind__startswith="feed.")
    if user is not None:
        found = found.filter(user=user)
    if kind is not None:
        found = found.filter(kind=kind)
    return found


def _note(user, kind: str, ref: str | None = None):
    found = _notes(user, kind)
    return (found.filter(object_ref=ref) if ref else found).get()


def _delivery_of(note, channel: str):
    return model("notify.Delivery").objects.get(notification=note, channel=channel)


def _mail_lines(delivery) -> list[str]:
    """Строки письма доставки `email` после `send_due()` (рендерер читает базу)."""
    from apps.notify.services import mail as notify_mail

    delivery.refresh_from_db()
    assert delivery.mail_id, "письмо не поставлено"
    message = model("mail.MailMessage").objects.get(pk=delivery.mail_id)
    return notify_mail.render(message, {"delivery": delivery.pk}).body.rstrip("\n").splitlines()


def _send_due() -> int:
    from apps.notify.services import mail as notify_mail

    return notify_mail.send_due()


def _email_delay(minutes: int = 15) -> None:
    model("notify.NotifySettings").objects.filter(pk=1).update(email_delay_minutes=minutes)


def _delivery(note, channel: str):
    now = timezone.now()
    return model("notify.Delivery").objects.create(
        notification=note, channel=channel, state="waiting", due_at=now - timedelta(seconds=5), enqueued_at=now)


# --- разбор разметки (помощник только этого файла) -------------------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _El:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.raw = tag, attrs, parent, ""

    @property
    def text(self) -> str:
        return " ".join(self.raw.split())


class _Doc(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.elements, self._stack = [], []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        el = _El(tag, {k: (v if v is not None else "") for k, v in attrs}, self._stack[-1] if self._stack else None)
        self.elements.append(el)
        if tag not in _VOID:
            self._stack.append(el)

    def handle_startendtag(self, tag, attrs):
        self.elements.append(_El(tag, {k: (v if v is not None else "") for k, v in attrs},
                                 self._stack[-1] if self._stack else None))

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                break

    def handle_data(self, data):
        for el in self._stack:
            el.raw += data


def _inside(el, ancestor) -> bool:
    node = el.parent
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent
    return False


def _find(doc, tag=None, attrs=None, *, within=None) -> list:
    wanted = attrs or {}
    found = [el for el in doc.elements
             if (tag is None or el.tag == tag) and all(k in el.attrs and (v is True or el.attrs[k] == v)
                                                      for k, v in wanted.items())]
    return [el for el in found if _inside(el, within)] if within is not None else found


def _one(doc, tag=None, attrs=None, *, within=None):
    found = _find(doc, tag, attrs, within=within)
    assert len(found) == 1, f"ожидали один элемент {tag or '*'}{attrs}, нашли {len(found)}"
    return found[0]


def _doc(response) -> _Doc:
    assert response.status_code == 200
    return _Doc(response.content.decode("utf-8", "replace"))


# --- сцена: по одному уведомлению каждого вида у одного получателя -------------------------------------------------

def _scene(clock) -> SimpleNamespace:
    """Получатель «Пётр Получатель» получает уведомления всех восьми видов от автора с уникальными именем, названием,
    местом и отрывком; возвращает сцену с уведомлениями `notes[код]` и данными для ожидаемых текстов."""
    author = _writer(UNIQUE_AUTHOR)
    recipient = fd.as_plain(full_name="Пётр Получатель")
    user = recipient.user
    _user_prefs(user)
    start, new_place = _future(3), "ДругоеМесто"
    for_you = _publish(author, f"{UNIQUE_WORD} для вас", to=[_p(user)])
    mention = _publish(author, f"{UNIQUE_WORD} упоминание {_mark(user)}", to=[_p(user)])
    own = _publish(recipient, f"{UNIQUE_WORD} запись получателя", to=[_p(author.user)])
    _svc("comments").add(author.user, own.pk, "Комментарий автора")
    _svc("likes").toggle_post(author.user, own.pk)
    important = _publish(author, f"{UNIQUE_WORD} важное", to=[_p(user)], kind="important", term="day")
    event = _publish_event(author, to=[_p(user)], start=start, title=UNIQUE_TITLE, place=UNIQUE_PLACE)
    _edit(author, event, event_place=new_place)
    soon = _future(0, 2)
    reminded = _publish_event(author, to=[_p(user)], start=soon, title=UNIQUE_TITLE, place=UNIQUE_PLACE)
    clock.advance(hours=1, minutes=5)
    fd.run_reminders(timezone.now())
    refs = {FOR_YOU: for_you, MENTION: mention, COMMENT: own, LIKE: own, IMPORTANT: important, INVITE: event,
            CHANGED: event, REMINDER: reminded}
    notes = {code: _note(user, code, f"feed.post:{post.pk}") for code, post in refs.items()}
    return SimpleNamespace(author=author, recipient=recipient, user=user, notes=notes, start=start,
                           new_place=new_place, posts=refs)


# --- каталог видов и каналы (FR-629, FR-631) -----------------------------------------------------------------

def test_catalog_eight_feed_kinds_codes_titles_module_order_available_events_coalesce():
    """FR-629: в каталоге `notify` восемь видов модуля «Лента» с кодами, названиями и `order` 70…77, после видов списков
    и до видов ядра; `available` — каждому, `events=()`, не обязательные; склейка — у комментария и «Нравится» с
    функциями текста; допустимые каналы — только у «Нравится»."""
    kinds, notify_kinds = _kinds(), _notify_kinds()
    catalog = kinds.catalog()
    feed_kinds = [kind for kind in catalog if kind.code.startswith("feed.")]
    assert [kind.code for kind in feed_kinds] == fd.FEED_CODES
    for kind, row in zip(feed_kinds, fd.FEED_KINDS):
        code, title, module, order, mandatory, _channels, events, _external = row
        assert (kind.title, kind.module, kind.order, kind.mandatory) == (title, module, order, mandatory), code
        assert tuple(kind.events) == events, code
        assert kind.coalesce is (code in fd.FEED_COALESCE), code
        assert kind.channels == fd.FEED_CHANNELS[code], code
    assert feed_kinds[0].order == 70 and feed_kinds[-1].order == 77
    assert feed_kinds[2].coalesce_text is notify_kinds.comment_coalesce_text
    assert feed_kinds[7].coalesce_text is notify_kinds.like_coalesce_text
    assert all(kind.coalesce_text is None for kind in feed_kinds if kind.code not in fd.FEED_COALESCE)
    codes = [kind.code for kind in catalog]
    first = codes.index(fd.FEED_CODES[0])
    assert codes[first:first + 8] == fd.FEED_CODES, "восемь видов идут подряд"
    assert codes[first - 1] == "lists.deadline" and codes[first + 8].startswith("core.")
    for user in (fd.as_plain().user, fd.as_writer().user, support.make_employee()):
        assert all(kind.available(user) for kind in feed_kinds)
    assert [kind.code for kind in kinds.for_event("feed.anything")] == []


def test_feed_kinds_default_channels_portal_and_email_like_portal_only():
    """FR-631: по умолчанию у семи видов «На портале» и «Почта», у «Нравится» — только «На портале»; в таблице
    сотрудника у «Нравится» нет ячеек других каналов, и почта ему не назначается."""
    prefs = _prefs_service()
    user = fd.as_plain().user
    by_code = {kind.code: kind for kind in _kinds().catalog() if kind.code.startswith("feed.")}
    for code in fd.FEED_CODES:
        assert tuple(by_code[code].default_channels) == (("portal",) if code == LIKE else ("portal", "email")), code
    rows = {row.kind.code: dict(row.cells) for row in prefs.effective(user).rows if row.kind.code.startswith("feed.")}
    assert list(rows) == fd.FEED_CODES
    for code in fd.FEED_BOXED:
        assert rows[code] == {"portal": True, "email": True, "push": False, "telegram": False, "max": False}, code
        assert prefs.channels_for(user.pk, by_code[code]) == ["email"], code
    assert rows[LIKE] == {"portal": True}
    assert prefs.channels_for(user.pk, by_code[LIKE]) == []


def test_my_notifications_feed_section_eight_kinds_like_without_external_cells():
    """FR-629, FR-631 (сценарий 9 п. 4): «Мои уведомления» показывают раздел «Лента» с восемью строками; у семи видов
    флажки почты и «Push в браузере», у «Нравится» ячейки внешних каналов без флажка (`data-available="0"`), а
    «На портале» — заблокированный отмеченный флажок."""
    client = fd.as_plain().client
    doc = _doc(client.get("/me/notifications/"))
    table = _one(doc, "table", {"data-notify-table": True})
    rows = [row for row in _find(doc, "tr", {"data-notify-kind": True}, within=table)
            if row.attrs["data-notify-kind"].startswith("feed.")]
    assert [row.attrs["data-notify-kind"] for row in rows] == fd.FEED_CODES
    for row, spec in zip(rows, fd.FEED_KINDS):
        code = spec[0]
        assert _one(doc, None, {"data-field": "title"}, within=row).text == spec[1], code
        assert _one(doc, None, {"data-field": "module"}, within=row).text == "Лента", code
        cells = _find(doc, "td", {"data-channel": True}, within=row)
        assert [cell.attrs["data-channel"] for cell in cells] == ["portal", "email", "push", "telegram", "max"], code
        portal = _one(doc, "td", {"data-channel": "portal"}, within=row)
        box = _one(doc, "input", {"type": "checkbox"}, within=portal)
        assert "checked" in box.attrs and "disabled" in box.attrs and "name" not in box.attrs, code
        for channel in ("email", "push", "telegram", "max"):
            cell = _one(doc, "td", {"data-channel": channel}, within=row)
            boxes = _find(doc, "input", {"type": "checkbox"}, within=cell)
            if code == LIKE:
                assert boxes == [] and cell.attrs.get("data-available") == "0", f"{code}:{channel}"
            elif channel in ("email", "push"):
                (box,) = boxes
                assert box.attrs["name"] == "cell" and box.attrs["value"] == f"{code}:{channel}", code


def test_admin_defaults_like_has_no_email_or_messenger_cells():
    """FR-631: в таблице значений по умолчанию у администратора у «Нравится» нет флажков внешних каналов (ячейки без
    флажка), у остальных видов флажки есть."""
    admin = support.logged_in(support.make_admin())
    doc = _doc(admin.get("/settings/notifications/"))
    table = _one(doc, "table", {"data-defaults-table": True})
    like = _one(doc, "tr", {"data-notify-kind": LIKE}, within=table)
    cells = _find(doc, "td", {"data-channel": True}, within=like)
    assert cells, "у «Нравится» ячейки есть, но без флажков"
    for cell in cells:
        assert _find(doc, "input", {"type": "checkbox"}, within=cell) == [], cell.attrs["data-channel"]
        assert cell.attrs.get("data-available") == "0", cell.attrs["data-channel"]
    for code in fd.FEED_BOXED:
        row = _one(doc, "tr", {"data-notify-kind": code}, within=table)
        for cell in _find(doc, "td", {"data-channel": True}, within=row):
            box = _one(doc, "input", {"type": "checkbox", "name": "cell"}, within=cell)
            assert box.attrs["value"] == f"{code}:{cell.attrs['data-channel']}"


def test_like_delivered_only_on_portal_even_if_matrix_or_defaults_force_email_and_bots(bots_on):
    """FR-631: даже если значения по умолчанию и таблица сотрудника записаны в обход формы с почтой и мессенджерами,
    «Нравится» уходит только на портал: каналов нет, доставок нет; тот же набор у «Вас упомянули» доставки создаёт."""
    prefs = _prefs_service()
    forced = ["email", "telegram", "max"]
    model("notify.NotifySettings").objects.update_or_create(pk=1, defaults={"defaults": {LIKE: forced, MENTION: forced}})
    owner = _writer("Ольга Хозяйка")
    _user_prefs(owner.user, matrix={LIKE: forced, MENTION: forced})
    for channel in ("telegram", "max"):
        model("notify.ChatBinding").objects.get_or_create(user=owner.user, channel=channel,
                                                          defaults={"chat_id": f"c{owner.user.pk}{channel}"})
    kind = {k.code: k for k in _kinds().catalog()}[LIKE]
    assert prefs.channels_for(owner.user.pk, kind) == []
    post = _publish(owner, "Запись хозяйки", to=["all"])
    liker = _person("Лев Отметивший")
    _svc("likes").toggle_post(liker, post.pk)
    note = _note(owner.user, LIKE)
    assert model("notify.Delivery").objects.filter(notification=note).count() == 0
    mention_post = _publish(_writer("Борис Автор"), f"Привет {_mark(owner.user)}", to=["all"])
    mention_note = _note(owner.user, MENTION, f"feed.post:{mention_post.pk}")
    channels = set(model("notify.Delivery").objects.filter(notification=mention_note).values_list("channel", flat=True))
    assert {"email", "telegram"} <= channels, "контроль: у вида с каналами доставки создаются"


# --- тексты (FR-631, NFR-609, NFR-611) -------------------------------------------------------------------------

def test_text_of_each_kind_by_plan_template_with_author_and_snippet(clock):
    """FR-631, NFR-611: текст уведомления каждого из восьми видов — по шаблону плана: автор, отрывок до 100 знаков,
    у события — название, дата и время по Москве, место; весь текст — в `Notification.text`."""
    scene = _scene(clock)
    name, word = UNIQUE_AUTHOR, UNIQUE_WORD
    stamp = fd.moscow_text(scene.start)
    expected = {
        FOR_YOU: f"{name}: запись для вас — «{word} для вас»",
        MENTION: f"{name} упомянул(а) вас: «{word} упоминание @Пётр Получатель»",
        COMMENT: f"{name} прокомментировал(а) запись «{word} запись получателя»",
        IMPORTANT: f"Важная запись от {name}: «{word} важное»",
        INVITE: f"{name} приглашает на событие «{UNIQUE_TITLE}» {stamp}",
        CHANGED: f"Событие «{UNIQUE_TITLE}» изменено: {stamp}, {scene.new_place}",
        REMINDER: f"Через час: «{UNIQUE_TITLE}», {UNIQUE_PLACE}",
        LIKE: f"Нравится {name}: «{word} запись получателя»",
    }
    assert {code: note.text for code, note in scene.notes.items()} == expected


def test_event_texts_use_moscow_time_at_utc_midnight(clock):
    """FR-631, NFR-611: на полночь UTC дата и время события в тексте — по Москве (03:00 того же дня; при 21:30 UTC —
    00:30 следующего дня), и в «Приглашении», и в «Событие изменено»."""
    clock.set(datetime(2026, 11, 1, 12, 0, tzinfo=UTC))
    author = _writer("Анна Автор")
    user = _person()
    start = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)
    post = _publish_event(author, to=[_p(user)], start=start, title="Планёрка", place="Корпус 1")
    assert _note(user, INVITE).text == "Анна Автор приглашает на событие «Планёрка» 10.11.2026 03:00"
    late = datetime(2026, 11, 10, 21, 30, tzinfo=UTC)
    _edit(author, post, event_start=fd.moscow_text(late), event_end=fd.moscow_text(late + timedelta(hours=1)))
    assert _note(user, CHANGED).text == "Событие «Планёрка» изменено: 11.11.2026 00:30, Корпус 1"


def _cut_ok(piece: str, original: str, limit: int) -> None:
    """Отрезок обрезан по слову с «…» не длиннее `limit` знаков перед многоточием."""
    assert piece.endswith("…") and piece != original, piece
    cut = piece[:-1].rstrip()
    assert 0 < len(cut) <= limit and original.startswith(cut), (limit, piece)


def test_title_and_place_200_cut_to_60_snippet_100_total_at_most_300(clock):
    """FR-631 (сценарий 9 п. 9): название и место из 200 знаков в «Приглашении», «Событие изменено» и «Напоминании»
    обрезаны до 60, отрывок — до 100, весь текст не длиннее 300 знаков (длинное имя автора обрезает конец)."""
    title, place = "слов " * 39 + "слово", "мест " * 39 + "место"
    other_place = "мест " * 39 + "места"
    long_text = "тест " * 100
    assert len(title) == len(place) == 200
    author = _writer("Анна Автор")
    user = _person()
    start = _future()
    post = _publish_event(author, to=[_p(user)], start=start, title=title, place=place)
    invite = re.fullmatch(r"Анна Автор приглашает на событие «(.*)» (\d\d\.\d\d\.\d{4} \d\d:\d\d)", _note(user, INVITE).text)
    assert invite, _note(user, INVITE).text
    _cut_ok(invite.group(1), title, 60)
    _edit(author, post, event_place=other_place)
    changed = re.fullmatch(r"Событие «(.*)» изменено: \d\d\.\d\d\.\d{4} \d\d:\d\d, (.*)", _note(user, CHANGED).text)
    assert changed, _note(user, CHANGED).text
    _cut_ok(changed.group(1), title, 60)
    _cut_ok(changed.group(2), other_place, 60)
    soon = _publish_event(author, to=[_p(user)], start=_future(0, 2), title=title, place=place)
    clock.advance(hours=1, minutes=5)
    fd.run_reminders(timezone.now())
    reminder = re.fullmatch(r"Через час: «(.*)», (.*)", _note(user, REMINDER, f"feed.post:{soon.pk}").text)
    assert reminder, _note(user, REMINDER, f"feed.post:{soon.pk}").text
    _cut_ok(reminder.group(1), title, 60)
    _cut_ok(reminder.group(2), place, 60)
    _publish(author, long_text, to=[_p(user)])
    snippet = re.fullmatch(r"Анна Автор: запись для вас — «(.*)»", _note(user, FOR_YOU).text)
    assert snippet, _note(user, FOR_YOU).text
    _cut_ok(snippet.group(1), long_text, 100)
    for note in _notes(user):
        assert len(note.text) <= 300, (note.kind, len(note.text))
    big = _writer("Ф" * 255)
    other = _person()
    _publish_event(big, to=[_p(other)], start=start, title=title, place=place)
    long_note = _note(other, INVITE)
    assert len(long_note.text) <= 300 and long_note.text.endswith("…")


def test_snippet_without_markup_marker_becomes_at_full_name():
    """FR-631: отрывок строится без разметки: маркер упоминания в тексте уведомления — «@ФИО», сырого `@[номер]` нет."""
    author = _writer("Анна Автор")
    mentioned = _person("Пётр Иванов")
    _publish(author, f"Привет, {_mark(mentioned)}!  Посмотри", to=[_p(mentioned)])
    text = _note(mentioned, MENTION).text
    assert "@Пётр Иванов" in text and "@[" not in text and "[" not in text
    assert text == "Анна Автор упомянул(а) вас: «Привет, @Пётр Иванов! Посмотри»"


def test_external_text_of_each_kind_constant_without_name_title_place_snippet(clock):
    """FR-631, NFR-609: внешний текст семи видов — постоянный по каталогу; службы доставки Telegram, MAX и Web Push
    отдают его же, а ФИО, названий, мест и отрывков в нём нет, хотя в `Notification.text` они есть; у «Нравится»
    внешнего текста нет."""
    from apps.notify.services import delivery as dlv

    scene = _scene(clock)
    by_code = {kind.code: kind for kind in _kinds().catalog() if kind.code.startswith("feed.")}
    assert by_code[LIKE].external_text == ""
    leaks = ("Виктор", "Уникальный", UNIQUE_TITLE, UNIQUE_PLACE, scene.new_place, UNIQUE_WORD, "Получатель", "«", "»")
    for code in fd.FEED_BOXED:
        assert by_code[code].external_text == EXTERNAL[code], code
        note = scene.notes[code]
        assert UNIQUE_AUTHOR.split()[0] in note.text or UNIQUE_TITLE in note.text, code
        for channel in ("telegram", "max", "webpush"):
            assert dlv.external_text(_delivery(note, channel)) == EXTERNAL[code], (code, channel)
        for leak in leaks:
            assert leak not in EXTERNAL[code], (code, leak)


@pytest.mark.parametrize("channel", ["telegram", "max", "webpush"])
def test_external_channel_mention_sends_only_external_text_and_link_parametrized_telegram_max_webpush(
        channel, bots_on, webpush_on):
    """FR-631, NFR-609 (сценарий 9 п. 3): «Вас упомянули» в Telegram, MAX и Web Push уходит только внешним текстом и
    ссылкой на страницу уведомлений — без ФИО автора, отрывка и названий."""
    from django.conf import settings

    from apps.notify.services import delivery as dlv

    author = _writer(UNIQUE_AUTHOR)
    target = _person("Пётр Получатель")
    _user_prefs(target)
    _publish(author, f"{UNIQUE_WORD} {_mark(target)}", to=[_p(target)])
    note = _note(target, MENTION)
    assert "Виктор" in note.text and UNIQUE_WORD in note.text
    row = _delivery(note, channel)
    external = EXTERNAL[MENTION]
    assert external == "Вас упомянули в ленте"
    if channel == "webpush":
        pair = notify_support.browser_keys()
        sub = notify_support.subscribe(target, keys=pair)
        with notify_support.webpush_capture() as capture:
            assert dlv.send_delivery(row.pk) == "sent"
        assert [r.url for r in capture.requests] == [sub.endpoint]
        payload = capture.decrypt(capture.requests[0], pair)
        assert payload == {"title": external, "url": "/notifications/", "tag": f"n-{note.pk}"}
        sent = str(payload)
    else:
        chat = model("notify.ChatBinding").objects.get_or_create(
            user=target, channel=channel, defaults={"chat_id": f"c{target.pk}{channel}"})[0].chat_id
        link = settings.PORTAL_URL.rstrip("/") + "/notifications/"
        with notify_support.fake_bot_send(channel) as fake:
            assert dlv.send_delivery(row.pk) == "sent"
        assert fake.calls == [(chat, html_lib.escape(external), (BUTTON, link))]
        sent = str(fake.calls)
    for leak in ("Виктор", "Уникальный", UNIQUE_WORD, "Получатель"):
        assert leak not in sent, leak


def test_browser_tab_system_notification_uses_portal_text(monkeypatch, django_capture_on_commit_callbacks):
    """FR-631, NFR-609: в системное уведомление браузера во вкладке портала идёт текст портала (с автором и
    отрывком), а не внешний — прежнее исключение SPEC-004 FR-317."""
    from apps.notify.services import live

    captured = []

    def fake_push(user_ids, *, toasts=None, binding=None):
        captured.append((list(user_ids), dict(toasts or {})))

    monkeypatch.setattr(live, "push", fake_push)
    author = _writer(UNIQUE_AUTHOR)
    target = _person("Пётр Получатель")
    with django_capture_on_commit_callbacks(execute=True):
        _publish(author, f"{UNIQUE_WORD} {_mark(target)}", to=[_p(target)])
    note = _note(target, MENTION)
    toasts = {user: toast for _users, found in captured for user, toast in found.items()}
    assert toasts[target.pk]["text"] == note.text
    assert UNIQUE_AUTHOR in toasts[target.pk]["text"] and UNIQUE_WORD in toasts[target.pk]["text"]
    assert toasts[target.pk]["text"] != EXTERNAL[MENTION]


# --- письма, тихие часы, сводка (FR-631) ---------------------------------------------------------------------

def test_email_sent_only_if_unread_after_delay_with_author_and_snippet(clock):
    """FR-631 (сценарий 9 п. 3): письмо уходит, только если уведомление не прочитано за время администратора (15
    минут): через 14 минут писем нет, через 15 — письмо с автором и отрывком; прочитанное письма не получает."""
    _email_delay(15)
    author = _writer(UNIQUE_AUTHOR)
    target = _person("Пётр Получатель")
    _user_prefs(target)
    _publish(author, f"{UNIQUE_WORD} первое {_mark(target)}", to=[_p(target)])
    second = _publish(author, f"{UNIQUE_WORD} второе {_mark(target)}", to=[_p(target)])
    first_note = _notes(target, MENTION).exclude(object_ref=f"feed.post:{second.pk}").get()
    read_note = _note(target, MENTION, f"feed.post:{second.pk}")
    _notes().filter(pk=read_note.pk).update(read_at=timezone.now())
    clock.advance(minutes=14)
    assert _send_due() == 0, "до срока писем нет"
    clock.advance(minutes=1)
    assert _send_due() == 2
    sent = _delivery_of(first_note, "email")
    assert sent.state == "sent"
    body = "\n".join(_mail_lines(sent))
    assert first_note.text in body and "Виктор Уникальный" in body and f"{UNIQUE_WORD} первое" in body
    skipped = _delivery_of(read_note, "email")
    assert (skipped.state, skipped.reason, skipped.mail_id) == ("skipped", "read", None)


def test_quiet_hours_portal_immediately_email_and_messengers_held_for_digest(clock, bots_on):
    """FR-631 (сценарий 9 п. 7): в тихие часы уведомление на портале видно сразу, письмо и сообщение в мессенджер
    копятся (`held`) и уходят одной сводкой в рабочее время."""
    from apps.notify.services import digest

    _email_delay(15)
    clock.set(_at(2026, 6, 16, 12, 0))   # вторник: вне «своих часов» (понедельник 09:00–18:00)
    author = _writer(UNIQUE_AUTHOR)
    target = _person("Пётр Получатель")
    _own_quiet(target, matrix={MENTION: ["email", "telegram"]})
    model("notify.ChatBinding").objects.get_or_create(user=target, channel="telegram",
                                                      defaults={"chat_id": f"c{target.pk}t"})
    _publish(author, f"{UNIQUE_WORD} {_mark(target)}", to=[_p(target)])
    note = _note(target, MENTION)
    assert note.read_at is None, "на портале уведомление есть сразу"
    assert _delivery_of(note, "telegram").state == "held"
    assert model("notify.UserNotifySettings").objects.get(user=target).digest_due_at is not None
    clock.advance(minutes=15)
    assert _send_due() == 1
    mail_row = _delivery_of(note, "email")
    assert (mail_row.state, mail_row.mail_id) == ("held", None), "письмо копится до сводки"
    clock.set(_at(2026, 6, 22, 10, 0))   # следующий понедельник, рабочее время
    result = digest.build(target.pk)
    assert result is not None and (result.count_email, result.count_message) == (1, 1)
    assert _delivery_of(note, "telegram").state == "digested" and _delivery_of(note, "email").state == "digested"


# --- склейка (FR-629, FR-630, FR-631) ------------------------------------------------------------------------

def test_three_comments_coalesce_into_one_with_count_3_and_link_to_first(clock):
    """FR-629, FR-630, FR-631: три комментария от разных людей — одно непрочитанное «Новый комментарий» автору записи с
    числом 3 и ссылкой на первый комментарий; число растёт текстом, а не новыми уведомлениями."""
    author = _writer("Анна Автор")
    first, second, third = _person("Борис Первый"), _person("Вера Вторая"), _person("Глеб Третий")
    post = _publish(author, "Запись для обсуждения", to=["all"])
    comments = _svc("comments")
    one = comments.add(first, post.pk, "Первый")
    note = _note(author.user, COMMENT)
    assert note.text == "Борис Первый прокомментировал(а) запись «Запись для обсуждения»"
    clock.advance(minutes=1)
    comments.add(second, post.pk, "Второй")
    assert _note(author.user, COMMENT).text == "Новых комментариев: 2 к записи «Запись для обсуждения»"
    clock.advance(minutes=1)
    comments.add(third, post.pk, "Третий")
    note = _note(author.user, COMMENT)
    assert note.text == "Новых комментариев: 3 к записи «Запись для обсуждения»"
    assert note.url == f"/feed/{post.pk}/#c{one.pk}", "ссылка ведёт к первому комментарию"
    assert note.object_ref == f"feed.post:{post.pk}" and note.read_at is None


def test_three_likes_coalesce_text_last_liker_and_two_more_link_to_post(clock):
    """FR-629, FR-631: три отметки записи — одно уведомление «Нравится» автору: последний отметивший и «(и ещё 2)»,
    ссылка на запись прежняя."""
    author = _writer("Анна Автор")
    likers = [_person("Лев Первый"), _person("Мира Вторая"), _person("Нина Третья")]
    post = _publish(author, "Запись для отметок", to=["all"])
    texts = []
    for liker in likers:
        _svc("likes").toggle_post(liker, post.pk)
        texts.append(_note(author.user, LIKE).text)
        clock.advance(minutes=1)
    assert texts == ["Нравится Лев Первый: «Запись для отметок»",
                     "Нравится Мира Вторая (и ещё 1): «Запись для отметок»",
                     "Нравится Нина Третья (и ещё 2): «Запись для отметок»"]
    note = _note(author.user, LIKE)
    assert note.url == f"/feed/{post.pk}/" and note.object_ref == f"feed.post:{post.pk}"


def test_two_likes_on_comment_one_portal_notification_no_email_no_messenger(clock):
    """FR-629, FR-631: две отметки комментария — одно уведомление на портале (склеено), письма и сообщений в
    мессенджер нет (доставок не создано)."""
    author = _writer("Анна Автор")
    commenter = _person("Клим Комментатор")
    post = _publish(author, "Запись", to=["all"])
    written = fd.comment(post, commenter, "Мой комментарий")
    for name in ("Лев Первый", "Мира Вторая"):
        _svc("likes").toggle_comment(_person(name), written.pk)
        clock.advance(minutes=1)
    note = _note(commenter, LIKE)
    assert note.object_ref == f"feed.post:{post.pk}:c{written.pk}"
    assert note.text == "Нравится Мира Вторая (и ещё 1): «Мой комментарий»"
    assert model("notify.Delivery").objects.filter(notification__user=commenter).count() == 0


def test_unlike_does_not_change_unread_notification_text(clock):
    """FR-629: снятие отметки текст непрочитанного уведомления не меняет и нового уведомления не создаёт."""
    author = _writer("Анна Автор")
    first, second = _person("Лев Первый"), _person("Мира Вторая")
    post = _publish(author, "Запись для отметок", to=["all"])
    _svc("likes").toggle_post(first, post.pk)
    clock.advance(minutes=1)
    _svc("likes").toggle_post(second, post.pk)
    before = _note(author.user, LIKE).text
    assert before == "Нравится Мира Вторая (и ещё 1): «Запись для отметок»"
    clock.advance(minutes=1)
    assert _svc("likes").toggle_post(second, post.pk) is False
    assert _svc("likes").toggle_post(first, post.pk) is False
    assert _notes(author.user, LIKE).count() == 1
    assert _note(author.user, LIKE).text == before


def test_delayed_email_takes_updated_coalesced_text_at_send(clock):
    """FR-629, FR-631: отложенное письмо берёт текст записи уведомления в момент отправки — уже обновлённый склейкой
    («Новых комментариев: 2»), а не первый."""
    _email_delay(15)
    author = _writer("Анна Автор")
    _user_prefs(author.user)
    first, second = _person("Борис Первый"), _person("Вера Вторая")
    post = _publish(author, "Запись для обсуждения", to=["all"])
    _svc("comments").add(first, post.pk, "Первый")
    clock.advance(minutes=5)
    _svc("comments").add(second, post.pk, "Второй")
    clock.advance(minutes=10)
    assert _send_due() == 1
    body = "\n".join(_mail_lines(_delivery_of(_note(author.user, COMMENT), "email")))
    assert "Новых комментариев: 2 к записи «Запись для обсуждения»" in body
    assert "прокомментировал(а)" not in body


# --- still_relevant и удаление (FR-606, FR-630, FR-632) ------------------------------------------------------

def test_still_relevant_deleted_post_email_and_digest_not_sent(clock):
    """FR-630, FR-632 (сценарий 9 п. 5): запись удалена до отправки — письмо не уходит (`not_relevant`), сводка её не
    включает; уведомление на портале остаётся."""
    from apps.notify.services import digest

    still_relevant = _notify_kinds().still_relevant
    _email_delay(15)
    author = _writer(UNIQUE_AUTHOR)
    target = _person("Пётр Получатель")
    _user_prefs(target)
    post = _publish(author, f"Запись {_mark(target)}", to=[_p(target)])
    note = _note(target, MENTION)
    assert still_relevant(target.pk, f"feed.post:{post.pk}") is True
    _svc("posts").delete(author.user, post.pk)
    assert still_relevant(target.pk, f"feed.post:{post.pk}") is False
    clock.advance(minutes=15)
    assert _send_due() == 1
    row = _delivery_of(note, "email")
    assert (row.state, row.reason, row.mail_id) == ("skipped", "not_relevant", None)
    assert model("notify.Notification").objects.filter(pk=note.pk).exists(), "уведомление на портале осталось"

    clock.set(_at(2026, 6, 16, 12, 0))
    quiet = _person("Нина Тихая")
    _own_quiet(quiet)
    held_post = _publish(author, f"Запись {_mark(quiet)}", to=[_p(quiet)])
    held_note = _note(quiet, MENTION)
    clock.advance(minutes=15)
    assert _send_due() == 1 and _delivery_of(held_note, "email").state == "held"
    _svc("posts").delete(author.user, held_post.pk)
    clock.set(_at(2026, 6, 22, 10, 0))
    assert digest.build(quiet.pk) is None
    row = _delivery_of(held_note, "email")
    assert (row.state, row.reason) == ("skipped", "not_relevant")


def test_still_relevant_deleted_comment_email_not_sent(clock):
    """FR-630, FR-632: `still_relevant` для ссылки вида `feed.post:<id>:c<cid>` ложна, когда комментарий удалён, и
    истинна, пока он есть; письмо по такой ссылке не уходит (`not_relevant`); неверные ссылки — ложь."""
    still_relevant = _notify_kinds().still_relevant
    _email_delay(15)
    author = _writer("Анна Автор")
    commenter = _person("Клим Комментатор")
    target = _person("Пётр Получатель")
    _user_prefs(target)
    post = _publish(author, "Запись всем", to=["all"])
    written = fd.comment(post, commenter, "Комментарий")
    ref = f"feed.post:{post.pk}:c{written.pk}"
    assert still_relevant(target.pk, ref) is True
    # вид с письмом и ссылкой на комментарий строится вручную: в плане такая ссылка есть только у «Нравится»
    note = model("notify.Notification").objects.create(
        user=target, kind=COMMENT, text="Комментарий в ленте", url=f"/feed/{post.pk}/#c{written.pk}", object_ref=ref)
    row = _delivery(note, "email")
    _svc("comments").delete(commenter, written.pk)
    assert still_relevant(target.pk, ref) is False
    assert still_relevant(target.pk, f"feed.post:{post.pk}") is True, "запись жива"
    for bad in ("", "feed.post:", "feed.post:abc", f"feed.post:{post.pk}:cabc", f"feed.post:{post.pk + 10**6}",
                f"knowledge.article:{post.pk}"):
        assert still_relevant(target.pk, bad) is False, bad
    assert _send_due() == 1
    row.refresh_from_db()
    assert (row.state, row.reason, row.mail_id) == ("skipped", "not_relevant", None)


def test_still_relevant_recipient_stopped_seeing_email_not_sent_link_404(clock):
    """FR-606, FR-630 (сценарий 9 п. 8): сотрудник перестал видеть запись (вышел из подразделения-адресата) — письмо не
    уходит, а ссылка уведомления отвечает как на несуществующую запись."""
    _email_delay(15)
    author = _writer("Анна Автор")
    unit = importlib.import_module("tests.support_org").make_unit("Отдел ИТ")
    member = _person("Мария Участница")
    importlib.import_module("tests.support_org").make_member(member, unit)
    _user_prefs(member)
    post = _publish(author, "Важное объявление отделу", to=[f"u{unit.pk}"], kind="important", term="day")
    note = _note(member, IMPORTANT)
    client = support.logged_in(member)
    assert client.get(note.url).status_code == 200
    model("org.Membership").objects.filter(user=member, unit=unit).delete()
    assert _notify_kinds().still_relevant(member.pk, f"feed.post:{post.pk}") is False
    clock.advance(minutes=15)
    assert _send_due() == 1
    row = _delivery_of(note, "email")
    assert (row.state, row.reason, row.mail_id) == ("skipped", "not_relevant", None)
    gone = client.get(note.url)
    missing = client.get(f"/feed/{post.pk + 10**6}/")
    assert gone.status_code == 404 and support.same_failure(gone, missing)


def test_portal_notifications_kept_after_delete_by_author_moderator_or_retention_link_404():
    """FR-630, FR-632: запись удалена автором, модератором и ночным заданием по сроку — уведомления на портале
    остаются, а их ссылки отвечают как на несуществующую запись."""
    author = _writer("Анна Автор")
    moderator = fd.as_moderator()
    target = _person("Пётр Получатель")
    posts = [_publish(author, f"Запись {number} {_mark(target)}", to=["all"]) for number in (1, 2, 3)]
    notes = [_note(target, MENTION, f"feed.post:{post.pk}") for post in posts]
    _svc("posts").delete(author.user, posts[0].pk)
    _svc("posts").delete(moderator.user, posts[1].pk)
    model("feed.Post").objects.filter(pk=posts[2].pk).update(published_at=timezone.now() - timedelta(days=4 * 366))
    fd.run_retention(timezone.now())
    assert not model("feed.Post").objects.filter(pk__in=[post.pk for post in posts]).exists()
    assert _notes(target, MENTION).count() == 3
    client = support.logged_in(target)
    missing = client.get("/feed/9999999/")
    for note in notes:
        response = client.get(note.url)
        assert response.status_code == 404 and support.same_failure(response, missing), note.url


def test_opening_card_marks_post_notifications_and_own_comment_likes_read(django_capture_on_commit_callbacks):
    """FR-629, FR-630: открытие карточки записи гасит уведомления об этой записи и об отметках своих комментариев к
    ней; уведомления о другой записи и о чужих комментариях остаются непрочитанными."""
    author = _writer("Анна Автор")
    other = _person("Борис Другой")
    liker = _person("Лев Отметивший")
    post = _publish(author, "Запись с обсуждением", to=["all"])
    second = _publish(author, "Другая запись", to=["all"])
    others_comment = _svc("comments").add(other, post.pk, "Комментарий Бориса")
    mine = _svc("comments").add(author.user, post.pk, "Мой комментарий")
    _svc("likes").toggle_post(liker, post.pk)
    _svc("likes").toggle_post(liker, second.pk)
    _svc("likes").toggle_comment(liker, mine.pk)
    _svc("likes").toggle_comment(liker, others_comment.pk)
    refs = {"post": f"feed.post:{post.pk}", "second": f"feed.post:{second.pk}", "mine": f"feed.post:{post.pk}:c{mine.pk}"}
    unread = lambda user, ref: _notes(user).filter(object_ref=ref, read_at__isnull=True).count()  # noqa: E731
    assert unread(author.user, refs["post"]) == 2 and unread(author.user, refs["mine"]) == 1
    with django_capture_on_commit_callbacks(execute=True):
        assert author.client.get(f"/feed/{post.pk}/").status_code == 200
    assert unread(author.user, refs["post"]) == 0, "уведомления записи прочитаны"
    assert unread(author.user, refs["mine"]) == 0, "отметка своего комментария прочитана"
    assert unread(author.user, refs["second"]) == 1, "уведомление другой записи осталось"
    assert unread(other, f"feed.post:{post.pk}:c{others_comment.pk}") == 1, "у чужого комментария — своё уведомление"
    with django_capture_on_commit_callbacks(execute=True):
        assert support.logged_in(other).get(f"/feed/{post.pk}/").status_code == 200
    assert unread(other, f"feed.post:{post.pk}:c{others_comment.pk}") == 0


def test_notification_text_with_markup_escaped_on_display():
    """NFR-605: разметка в тексте уведомления на странице «Уведомления» и в колокольчике экранируется: тегов `script`
    и `b` в разметке нет, есть их экранированный вид."""
    from apps.core.extensions import Draft
    from apps.notify.services import dispatch

    author = _writer("Анна Автор")
    target = _person("Пётр Получатель")
    probe = "<script>alert(1)</script> и <b>жирный</b>"
    _publish(author, probe, to=[_p(target)])
    direct = dispatch.create(FOR_YOU, [Draft(target.pk, f"Анна Автор: запись для вас — «{probe}»", "/feed/1/",
                                             "feed.post:1")])
    assert direct, "уведомление с сырой разметкой в тексте создано"
    client = support.logged_in(target)
    for path in ("/notifications/", "/notifications/bell/"):
        response = client.get(path)
        assert response.status_code == 200, path
        body = response.content.decode("utf-8")
        assert "<script>alert(1)</script>" not in body and "<b>жирный</b>" not in body, path
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body and "&lt;b&gt;жирный&lt;/b&gt;" in body, path
