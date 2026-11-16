"""T-8116b: каталог видов, настройки каналов и `still_relevant` мессенджера (FR-651, FR-663, FR-664, FR-665, FR-666).

Источники: TASKS-008 T-8116b (шесть тестов); PLAN-008 «Уведомления» (два вида `messenger.message` и
`messenger.mention`, `order` 80/81 после видов ленты, каналы по умолчанию «портал» и «почта», постоянный внешний
текст, склейка только у сообщения, «Мои уведомления» отключают почту и внешние каналы, портал приходит всегда,
`still_relevant` перед письмом и сводкой — получатель всё ещё участник, чат виден, есть непрочитанные) и «Вкладка
„Уведомления“» (первая страница потока рендерится на сервере тем же `notify/_list_body.html`, строки `_row.html`,
открытие беседы гасит непрочитанные, FR-667); CONTRACT-008: 5.1 (`members.visible_chats`), 5.3
(`notify_rules.still_relevant`, `unread.counts`), 7.1 (записи видов), 7.3 (портал всегда, почта и внешние каналы
отключаются сотрудником), 7.4 (таблица «код вида → модуль», двадцать два вида, две строки «Мессенджер»), 10.1
(адреса), 12 (зацепки разметки).

Проверки идут путями портала, которые есть у среза: каталог — `apps.notify.services.kinds.catalog()`, «Мои
уведомления» — `/me/notifications/` (CONTRACT-004, 13.2; зацепки — `tr[data-notify-kind]`, `td[data-channel]`,
`[data-field]`), поток уведомлений — `/messenger/notifications/` (зацепки `li[data-notification]` и `data-unread`
из `notify/_row.html`). Уведомления и доставки создаёт настоящая служба `messages.send`; отложенное письмо
разбирает `apps.notify.services.mail.send_due` — им же проверяется, что при `still_relevant = False` письма нет.
Код среза на уровне модуля не импортируется (CONTRACT-008, «Правила для всех тестов среза»): модели берутся через
`support.model`, службы — внутри тестов. Секретов и ПДн нет: адреса и телефоны не создаются.

Допущения писателя (см. отчёт T-8116b): 1) `notify_rules.still_relevant` вызывается так же, как одноимённые
проверки прочих модулей и как её зовут `notify.services.mail` и `notify.services.digest` —
`still_relevant(user_id, object_ref)`, где `object_ref = "messenger.chat:<id>"` (CONTRACT-008, 5.3 называет
единственный довод «notification»; форму вызова задаёт прежняя точка `NotificationKind.still_relevant` ядра и
T-8116a сверяет тождество функции, поэтому тест зовёт службу по форме ядра); 2) «удалённое сообщение» даёт
`still_relevant = False` не ссылкой, а данными: удалённое сообщение не входит в непрочитанные, и у чата без других
непрочитанных писем нет (план, «Уведомления»: номер сообщения вид не получает); 3) ячейка `push` в «Моих
уведомлениях» показывается всегда (решение D5 CONTRACT-004), её доступность зависит от VAPID и подписки — тест
проверяет флажок и ячейку, а не доступность; `telegram`/`max` становятся доступными после привязки.
"""
import importlib
from datetime import timedelta
from html.parser import HTMLParser

import pytest
from django.utils import timezone

from tests import support
from tests import support_messenger as messenger

pytestmark = pytest.mark.django_db

MESSAGE_KIND, MENTION_KIND = "messenger.message", "messenger.mention"
MESSENGER_PAGE = "/messenger/notifications/"
MY_PAGE = "/me/notifications/"
EXTERNAL_CHANNELS = ("email", "push", "telegram", "max")
# таблица «код вида → модуль» (CONTRACT-008, 7.4): двадцать два вида семи модулей
MODULE_COUNTS = {"Сервис-деск": 4, "База знаний": 3, "Списки": 1, "Лента": 8, "Мессенджер": 2, "Ядро": 3,
                 "Уведомления": 1}

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- помощники только этого файла (общие помощники среза не правятся) ------------------------------------------

class _El:
    """Элемент разметки: тег, разобранные атрибуты, родитель и собранный текст."""

    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}
        self.parent = parent
        self.raw = ""

    @property
    def text(self) -> str:
        return " ".join(self.raw.split())


class _Doc(HTMLParser):
    """Разбор страницы: плоский список элементов с родителями (образец — `test_notify_prefs.py`)."""

    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.elements, self._stack = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        element = _El(tag, attrs, self._stack[-1] if self._stack else None)
        self.elements.append(element)
        if tag not in _VOID:
            self._stack.append(element)

    def handle_startendtag(self, tag, attrs):
        self.elements.append(_El(tag, attrs, self._stack[-1] if self._stack else None))

    def handle_endtag(self, tag):
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                break

    def handle_data(self, data):
        for element in self._stack:
            element.raw += data


def _doc(response) -> _Doc:
    return _Doc(response.content.decode("utf-8", "replace"))


def _page(session, url: str) -> _Doc:
    response = session.client.get(url)
    assert response.status_code == 200, f"GET {url}: {response.status_code}"
    return _doc(response)


def _inside(element, ancestor) -> bool:
    node = element.parent
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent
    return False


def _find(doc, tag=None, attrs=None, *, within=None) -> list:
    """Элементы с тегом и атрибутами (`True` — атрибут есть с любым значением); `within` — только потомки."""
    wanted = attrs or {}
    found = [element for element in doc.elements
             if (tag is None or element.tag == tag)
             and all(name in element.attrs and (value is True or element.attrs[name] == value)
                     for name, value in wanted.items())]
    return [element for element in found if _inside(element, within)] if within is not None else found


def _one(doc, tag=None, attrs=None, *, within=None):
    found = _find(doc, tag, attrs, within=within)
    assert len(found) == 1, f"ожидали один элемент {tag or '*'}{attrs}, нашли {len(found)}"
    return found[0]


def _box(doc, row, channel: str):
    """Флажок ячейки канала в строке `tr[data-notify-kind]` или `None`, если флажка нет."""
    cell = _one(doc, "td", {"data-channel": channel}, within=row)
    boxes = _find(doc, "input", {"type": "checkbox"}, within=cell)
    assert len(boxes) <= 1, f"в ячейке {row.attrs.get('data-notify-kind')}:{channel} несколько флажков"
    return boxes[0] if boxes else None


def _checked(doc, row, channel: str) -> bool:
    """Отмечен ли флажок ячейки; ячейка без флажка — отказ с понятным текстом."""
    box = _box(doc, row, channel)
    assert box is not None, f"в ячейке {row.attrs.get('data-notify-kind')}:{channel} нет флажка"
    return "checked" in box.attrs


def _person(value):
    """Сотрудник из `Session` или сам `core.User`."""
    return getattr(value, "user", value)


def _employee(name: str):
    """Действующий сотрудник с паролем и клиентом (`Session`)."""
    return messenger.make_user(full_name=name)


def _kind(code: str):
    """Вид каталога по коду."""
    from apps.notify.services import kinds as notify_kinds

    return notify_kinds.get(code)


def _ref(chat) -> str:
    """`object_ref` обоих видов уведомлений и `object.viewed` (CONTRACT-008, 2.2)."""
    return f"messenger.chat:{chat.pk}"


def _relevant(session, chat) -> bool:
    """`notify_rules.still_relevant(user_id, object_ref)` — проверка перед письмом и сводкой (CONTRACT-008, 5.3)."""
    return _relevant_ref(session, _ref(chat))


def _relevant_ref(session, ref: str) -> bool:
    """Та же проверка по готовой ссылке `object_ref`."""
    rules = importlib.import_module("apps.messenger.services.notify_rules")
    return rules.still_relevant(_person(session).pk, ref)


def _counts(session) -> dict:
    """Числа непрочитанного по чатам; кэш 5 с сбрасывается — его поведение сверяет T-8113."""
    from apps.messenger.services import unread

    unread.invalidate(None)
    return unread.counts(_person(session))


def _visible(session) -> set:
    from apps.messenger.services import members

    return {getattr(item, "pk", item) for item in members.visible_chats(_person(session))}


def _send(chat, author, text: str):
    """`messages.send(chat, author, text)` — путь службы целиком, включая уведомления и доставки."""
    from apps.messenger.services import messages

    return messages.send(chat, _person(author), text)


def _mark(*sessions) -> str:
    """Маркеры упоминаний людей: `@[u<id>]` (CONTRACT-008, 5.2)."""
    return " ".join(f"@[u{_person(session).pk}]" for session in sessions)


def _notes(user=None, kind: str | None = None):
    """Уведомления мессенджера; `user` — `Session` или `core.User`."""
    rows = support.model("notify.Notification").objects.filter(kind__startswith="messenger.")
    if user is not None:
        rows = rows.filter(user=_person(user))
    if kind is not None:
        rows = rows.filter(kind=kind)
    return rows


def _note(user, kind: str):
    return _notes(user, kind).get()


def _prefs(user, **fields):
    """Строка личных настроек уведомлений сотрудника (тихие часы — по умолчанию календарь)."""
    return support.model("notify.UserNotifySettings").objects.update_or_create(
        user=_person(user), defaults=fields)[0]


def _settings(**fields):
    """Строка `MessengerSettings` (одна, `pk=1`); возвращает строку."""
    Settings = support.model("messenger.MessengerSettings")
    defaults = {"retention_years": 3, "general_chat_enabled": True}
    defaults.update(fields)
    row, _ = Settings.objects.update_or_create(pk=1, defaults=defaults)
    return row


# --- каталог (FR-663, 664, NFR-705) -----------------------------------------------------------------------------

def test_catalog_has_22_kinds_and_two_messenger_rows():
    """FR-663, 664: каталог собран из двадцати двух видов семи модулей (сервис-деск 4, база знаний 3, списки 1,
    лента 8, мессенджер 2, ядро 3, уведомления 1); две строки «Мессенджер» — `messenger.message` (order 80) и
    `messenger.mention` (order 81) сразу после видов ленты (77), с названиями, каналами по умолчанию «портал» и
    «почта», без обязательности и событий шины и с постоянным внешним текстом; каталог отсортирован по `order`."""
    from apps.notify.services import kinds as notify_kinds

    catalog = notify_kinds.catalog()
    employee = _employee("Проверяющий Каталог")

    assert len(catalog) == 22, f"видов в каталоге: {len(catalog)}"
    assert len({kind.code for kind in catalog}) == 22, "коды видов в каталоге повторяются"
    modules = [kind.module for kind in catalog]
    for module, count in MODULE_COUNTS.items():
        assert modules.count(module) == count, f"видов модуля «{module}»: {modules.count(module)}"
    assert [kind.order for kind in catalog] == sorted(kind.order for kind in catalog), "каталог не по `order`"

    rows = [kind for kind in catalog if kind.module == messenger.MESSENGER_MODULE]
    assert [kind.code for kind in rows] == list(messenger.MESSENGER_CODES), (
        f"строки «Мессенджер»: {[kind.code for kind in rows]}")
    assert [kind.order for kind in rows] == [80, 81], f"order строк «Мессенджер»: {[kind.order for kind in rows]}"
    codes = [kind.code for kind in catalog]
    feed_codes = [kind.code for kind in catalog if kind.module == "Лента"]
    assert feed_codes, "видов ленты в каталоге нет"
    after_feed = codes.index(feed_codes[-1]) + 1
    assert codes[after_feed:after_feed + 2] == list(messenger.MESSENGER_CODES), (
        f"после видов ленты идут {codes[after_feed:after_feed + 2]}")

    for code, title, module, order, mandatory, channels, events, external in messenger.MESSENGER_KINDS:
        kind = notify_kinds.get(code)
        assert (kind.title, kind.module, kind.order, kind.mandatory) == (title, module, order, mandatory), code
        assert tuple(kind.default_channels) == tuple(channels) == ("portal", "email"), code
        assert tuple(kind.events) == tuple(events) == (), code
        assert kind.external_text == external, code
        assert "«" not in external and "»" not in external and "@" not in external, (
            f"{code}: во внешнем тексте есть имя, название или отрывок (NFR-705)")
        assert kind.available(employee.user) is True, f"{code}: вид закрыт действующему сотруднику"


# --- «Мои уведомления»: две строки и каналы (FR-665) -----------------------------------------------------------

def test_my_notifications_lists_two_rows_with_email_and_external_channels():
    """FR-665: в «Моих уведомлениях» у обычного сотрудника обе строки «Мессенджер» — «Новое сообщение в чате» и
    «Упомянул вас в чате» (последние в таблице); у каждой есть «На портале» (заблокирована), «Почта» (отмечена) и
    внешние каналы: ячейки `push`, `telegram`, `max` с флажками — `telegram`/`max` доступны после привязки, ячейка
    `push` показывается всегда (решение D5 CONTRACT-004)."""
    user = _employee("Настройщик Каналов")
    for channel in ("telegram", "max"):
        support.model("notify.ChatBinding").objects.create(
            user=user.user, channel=channel, chat_id=f"{user.user.pk}0{len(channel)}")

    doc = _page(user, MY_PAGE)
    rows = {row.attrs["data-notify-kind"]: row
            for row in _find(doc, "tr", {"data-notify-kind": True})}
    assert list(rows)[-2:] == list(messenger.MESSENGER_CODES), (
        f"строки «Мессенджер» в таблице: {list(rows)[-2:]}")

    for code in messenger.MESSENGER_CODES:
        row = rows[code]
        assert _one(doc, None, {"data-field": "title"}, within=row).text == messenger.MESSENGER_TITLES[code]
        assert _one(doc, None, {"data-field": "module"}, within=row).text == messenger.MESSENGER_MODULE

        portal = _one(doc, "td", {"data-channel": "portal"}, within=row)
        assert portal.attrs.get("data-locked") == "1", f"{code}: «На портале» не заблокирована"
        assert _checked(doc, row, "portal"), f"{code}: «На портале» не отмечена"

        for channel in EXTERNAL_CHANNELS:
            cell = _one(doc, "td", {"data-channel": channel}, within=row)
            box = _box(doc, row, channel)
            assert box is not None, f"{code}:{channel}: у внешнего канала нет флажка"
            assert box.attrs.get("name") == "cell" and box.attrs.get("value") == f"{code}:{channel}", (
                f"{code}:{channel}: флажок не сохраняет ячейку")
            if channel == "email":
                assert "checked" in box.attrs, f"{code}: почта выключена по умолчанию"
                assert "disabled" not in box.attrs, f"{code}: почту нельзя выключить"
            if channel in ("telegram", "max"):
                assert cell.attrs.get("data-available") == "1", f"{code}:{channel} недоступен после привязки"


# --- отключение почты: только портал (FR-665) -------------------------------------------------------------------

def test_employee_turns_off_email_and_gets_portal_only():
    """FR-665: сотрудник снимает в «Моих уведомлениях» почту у обоих видов мессенджера — внешних каналов у видов нет
    (`channels_for` пуст), но уведомление на портале приходит: записи `Notification` по обычному сообщению и по
    упоминанию есть, доставок нет, отправлять нечего; у сотрудника с почтой по умолчанию та же рассылка письмо
    создаёт (контроль); ячейки «На портале» по-прежнему отмечены и заблокированы."""
    from apps.notify.services import mail, prefs

    author = _employee("Автор Отключения")
    reader = _employee("Читатель Отключения")
    other = _employee("Читатель Почтовый")
    plain_chat = messenger.group(author, [reader, other], title="Беседа без почты")
    mention_chat = messenger.group(author, [reader], title="Беседа с упоминанием")

    assert prefs.save(reader.user, table={code: [] for code in messenger.MESSENGER_CODES}) is True, (
        "таблица каналов не сохранилась")
    for code in messenger.MESSENGER_CODES:
        assert prefs.channels_for(reader.user.pk, _kind(code)) == [], f"{code}: внешние каналы остались включены"

    _send(plain_chat, author, "Сообщение без письма")
    _send(mention_chat, author, f"Посмотри, пожалуйста {_mark(reader)}")

    notes = _notes(user=reader.user)
    assert sorted(notes.values_list("kind", flat=True)) == sorted((MESSAGE_KIND, MENTION_KIND)), (
        f"портал не получил уведомлений: {sorted(notes.values_list('kind', flat=True))}")
    assert not support.model("notify.Delivery").objects.filter(notification__in=notes).exists(), (
        "при выключенной почте создана доставка")
    control = _note(other.user, MESSAGE_KIND).deliveries.get(channel="email")
    assert control.state == "waiting", "контроль: у сотрудника с почтой письмо не создано"
    assert mail.send_due() == 0, "при выключенной почте нашлось письмо к отправке"

    doc = _page(reader, MY_PAGE)
    rows = {row.attrs["data-notify-kind"]: row for row in _find(doc, "tr", {"data-notify-kind": True})}
    for code in messenger.MESSENGER_CODES:
        assert _checked(doc, rows[code], "portal"), f"{code}: портал выключился"
        assert not _checked(doc, rows[code], "email"), f"{code}: почта осталась отмеченной"


# --- `still_relevant` (FR-663, 666) -----------------------------------------------------------------------------

def test_still_relevant_false_for_left_transferred_deleted_message_and_read_chat(clock):
    """FR-663, 666: `still_relevant` истинно, пока получатель — участник, чат виден и есть непрочитанные; ложно для
    вышедшего (строка `ChatMember` с `left_at`), переведённого в другой отдел (чат отдела выпал из цепочки узлов),
    чата, где непрочитанное сообщение удалено, и прочитанного чата. После новой отметки/нового сообщения проверка
    снова истинна — она считается по данным, а не по таймеру."""
    from apps.messenger.services import messages
    from apps.org.services import membership
    from tests import support_org as org

    author = _employee("Автор Актуальности")
    base = timezone.now().replace(microsecond=0)
    clock.set(base)
    admin = messenger.as_admin()

    # живой непрочитанный чат — истина (контроль)
    reader = _employee("Читатель Живой")
    chat = messenger.group(author, [reader], title="Беседа живая")
    clock.set(base + timedelta(minutes=1))
    messenger.post(chat, author, "Посмотрите, пожалуйста", created_at=timezone.now())
    assert _counts(reader).get(chat.pk, 0) == 1, "контроль: у читателя нет непрочитанного"
    assert _relevant(reader, chat) is True, "непрочитанный чат признан неактуальным"

    # вышедший участник
    support.model("messenger.ChatMember").objects.filter(
        chat=chat, user=reader.user).update(left_at=timezone.now())
    assert _relevant(reader, chat) is False, "вышедшему участнику письмо считалось бы актуальным"

    # прочитанный чат; новое сообщение возвращает актуальность
    reader_2 = _employee("Читатель Прочитавший")
    clock.set(base + timedelta(minutes=2))
    read_chat = messenger.group(author, [reader_2], title="Беседа прочитанная")
    clock.set(base + timedelta(minutes=3))
    messenger.post(read_chat, author, "Прочитанное сообщение", created_at=timezone.now())
    assert _counts(reader_2).get(read_chat.pk, 0) == 1, "контроль: непрочитанное сообщение не посчиталось"
    clock.set(base + timedelta(minutes=4))
    messenger.read(read_chat, reader_2, timezone.now())
    assert _counts(reader_2).get(read_chat.pk, 0) == 0, "контроль: у читателя осталось непрочитанное"
    assert _relevant(reader_2, read_chat) is False, "прочитанный чат признан актуальным"
    clock.set(base + timedelta(minutes=5))
    messenger.post(read_chat, author, "Ещё одно сообщение", created_at=timezone.now())
    assert _relevant(reader_2, read_chat) is True, "новое сообщение не вернуло актуальность"

    # удалённое непрочитанное сообщение
    reader_3 = _employee("Читатель Удалённого")
    clock.set(base + timedelta(minutes=6))
    deleted_chat = messenger.group(author, [reader_3], title="Беседа удалённая")
    clock.set(base + timedelta(minutes=7))
    message = messenger.post(deleted_chat, author, "Скоро удалю", created_at=timezone.now())
    assert _counts(reader_3).get(deleted_chat.pk, 0) == 1, "контроль: непрочитанное сообщение не посчиталось"
    assert _relevant(reader_3, deleted_chat) is True, "контроль: непрочитанное сообщение не дало актуальности"
    messages.delete(message, author.user)
    assert _counts(reader_3).get(deleted_chat.pk, 0) == 0, "удалённое сообщение осталось непрочитанным"
    assert _relevant(reader_3, deleted_chat) is False, "удалённое сообщение осталось актуальным"

    # переведённый сотрудник: чат прежнего отдела выпадает из цепочки узлов
    old_unit = messenger.unit("Прежний отдел актуальности")
    new_unit = messenger.unit("Новый отдел актуальности")
    reader_4 = _employee("Читатель Переведённый")
    member_from = _employee("Сотрудник Отдела")

    org.make_member(reader_4.user, old_unit)
    org.make_member(member_from.user, old_unit)
    clock.set(base + timedelta(minutes=8))
    department_chat = messenger.department_chat(old_unit)
    clock.set(base + timedelta(minutes=9))
    messenger.post(department_chat, member_from, "Сообщение отдела", created_at=timezone.now())
    assert _counts(reader_4).get(department_chat.pk, 0) == 1, "контроль: у сотрудника отдела нет непрочитанного"
    assert _relevant(reader_4, department_chat) is True, "чат своего отдела признан неактуальным"

    membership.transfer_member(reader_4.user, old_unit, new_unit, actor=admin.user)
    assert department_chat.pk not in _visible(reader_4), "переведённый всё ещё видит чат прежнего отдела"
    assert _relevant(reader_4, department_chat) is False, "переведённому письмо считалось бы актуальным"

    # несуществующий чат — ложно
    assert _relevant_ref(reader_4, "messenger.chat:999999") is False, "несуществующий чат признан актуальным"


# --- открытие беседы во вкладке «Уведомления» (FR-666) ---------------------------------------------------------

def test_viewing_chat_silences_unread_notifications(django_capture_on_commit_callbacks):
    """FR-666: непрочитанное уведомление мессенджера видно во вкладке «Уведомления» (`/messenger/notifications/`,
    строка `li[data-notification]` с `data-unread="1"`); открытие беседы публикует `object.viewed` — уведомление
    этого чата прочитано, в потоке с фильтром «непрочитанные» его нет, строка на общей странице помечена прочитанной,
    а число непрочитанных уведомлений сотрудника — 0."""
    from apps.notify.services import reading

    author = _employee("Автор Открытия")
    reader = _employee("Читатель Открытия")
    chat = messenger.group(author, [reader], title="Беседа для открытия")
    _send(chat, author, "Непрочитанное до открытия")
    note = _note(reader.user, MESSAGE_KIND)
    assert note.read_at is None, "уведомление создано прочитанным"
    assert reading.unread_count(reader.user.pk) == 1, "контроль: непрочитанных уведомлений не одно"

    doc = _page(reader, MESSENGER_PAGE)
    _one(doc, None, {"data-messenger-page": "notifications"})
    tab = _one(doc, None, {"data-messenger-tab": "notifications"})
    assert tab.attrs.get("aria-selected") == "true", "вкладка «Уведомления» не выбрана"
    row = _one(doc, "li", {"data-notification": str(note.pk)})
    assert row.attrs.get("data-unread") == "1", f"строка потока: data-unread={row.attrs.get('data-unread')!r}"

    with django_capture_on_commit_callbacks(execute=True):
        opened = reader.client.get(f"/messenger/chats/{chat.pk}/")
    assert opened.status_code == 200, f"беседа: {opened.status_code}"

    note.refresh_from_db()
    assert note.read_at is not None, "открытие беседы не погасило уведомление чата"
    assert reading.unread_count(reader.user.pk) == 0, "число непрочитанных уведомлений не обнулилось"
    assert not _find(_page(reader, f"{MESSENGER_PAGE}?f=unread"), "li", {"data-notification": str(note.pk)}), (
        "погашенное уведомление осталось в потоке непрочитанных")
    read_row = _one(_page(reader, MESSENGER_PAGE), "li", {"data-notification": str(note.pk)})
    assert read_row.attrs.get("data-unread") == "0", "в потоке строка осталась непрочитанной"


# --- выключенный «Общий чат» (FR-651, 663) ----------------------------------------------------------------------

def test_general_chat_disabled_makes_still_relevant_false():
    """FR-651, 663: в «Общем чате» уведомление актуально, пока чат включён; выключенный чат выпадает из видимых
    (`visible_chats`) и `still_relevant` ложно — отложенное письмо разбирается как `skipped`/`not_relevant`, письма
    нет; включение возвращает актуальность."""
    from apps.notify.services import mail

    author = _employee("Автор Общего")
    reader = _employee("Читатель Общего")
    _prefs(reader, quiet_mode="none")
    _settings(general_chat_enabled=True)
    chat = messenger.general()

    _send(chat, author, "Всем доброе утро")
    note = _note(reader.user, MESSAGE_KIND)
    delivery = note.deliveries.get(channel="email")
    assert delivery.state == "waiting", f"письмо не ждёт отправки: {delivery.state!r}"
    assert _relevant(reader, chat) is True, "включённый общий чат признан неактуальным"
    assert chat.pk in _visible(reader), "включённый общий чат не виден сотруднику"

    _settings(general_chat_enabled=False)
    assert chat.pk not in _visible(reader), "выключенный общий чат остался в видимых"
    assert _relevant(reader, chat) is False, "выключенный общий чат остался актуальным"

    support.model("notify.Delivery").objects.filter(pk=delivery.pk).update(due_at=timezone.now())
    assert mail.send_due() == 1, "доставка письма не разобрана обходом"
    delivery.refresh_from_db()
    assert (delivery.state, delivery.reason) == ("skipped", "not_relevant"), (
        f"письмо по выключенному чату: {delivery.state!r}/{delivery.reason!r}")
    assert delivery.mail_id is None, "письмо поставлено, хотя чат выключен"

    _settings(general_chat_enabled=True)
    assert _relevant(reader, chat) is True, "включение общего чата не вернуло актуальность"