"""T-8116a: виды и правила уведомлений мессенджера (FR-656, FR-657, FR-663, FR-664, FR-666, NFR-705, NFR-708).

Источники: PLAN-008 «Уведомления» (два вида `messenger.message`/`messenger.mention`, `order` 80/81 после видов ленты,
каналы по умолчанию «портал» и «почта», постоянный внешний текст без ФИО и названий, получатели — участники чата без
автора и без уволенных, одно сообщение — одно уведомление, упомянутый получает только «Упомянул вас в чате», себе и
упоминание себя — без уведомлений, склейка по чату, отрывок сообщения в уведомление не кладётся, письмо — по данным
`still_relevant`, правка и удаление уведомлений не создают); TASKS-008 T-8116a; CONTRACT-008: 5.2
(`messages.send`/`edit`/`delete`), 5.3 (`notify_rules.decide`, `notify_rules.still_relevant`), 7.1 (записи видов),
7.2 (черновики, тексты, ссылка и `object_ref`), 7.3 (портал сразу, письмо по `email_delay_minutes`), 7.4 (два
`messenger.*` в каталоге после ленты), 13.3 (тексты интерфейса).

Проверки идут настоящим путём службы отправки (`apps.messenger.services.messages`), результат читается из
`notify.Notification` и `notify.Delivery`; `notify_rules.decide` вызывается службой, поэтому поля вида (склейка,
`still_relevant`), каналы и срок письма сверяются по записям видов и доставок. Код среза на уровне модуля не
импортируется (CONTRACT-008, «Правила для всех тестов среза»): модели берутся через `support.model`, службы — внутри
функций. Секретов и ПДн нет: адреса и телефоны не создаются.

Допущения писателя (см. отчёт T-8116a): 1) «письмо через 15 минут» проверяется данными: у вида
`still_relevant` — `notify_rules.still_relevant`, а доставка почты ждёт `created_at + email_delay_minutes` (15 по
умолчанию), таймера среза нет; отправку письма, тихие часы и отключение каналов сверяют T-8116b/T-8116c своими
файлами; 2) текст упоминания пишется с «упомянул(а)» — тест ищет основу «упомянул» и название чата, а не целую
фразу; 3) уволенный в чате остаётся строкой `ChatMember` (помощник `group`), уведомление ему не создаётся правилом
`decide`, а не отсутствием участия.
"""
import importlib
from datetime import timedelta

import pytest

from tests import support
from tests import support_messenger as messenger

pytestmark = pytest.mark.django_db

MESSAGE_KIND, MENTION_KIND = "messenger.message", "messenger.mention"
CHANNEL_EMAIL = "email"


# --- помощники только этого файла (общие помощники среза не правятся) ------------------------------------------

def _notes(user=None, kind: str | None = None):
    """Уведомления мессенджера; `user` — `Session` или `core.User`."""
    rows = support.model("notify.Notification").objects.filter(kind__startswith="messenger.")
    if user is not None:
        rows = rows.filter(user=getattr(user, "user", user))
    if kind is not None:
        rows = rows.filter(kind=kind)
    return rows


def _kinds_of(user) -> list[str]:
    """Виды уведомлений сотрудника по возрастанию номера записи."""
    return list(_notes(user=user).order_by("pk").values_list("kind", flat=True))


def _note(user, kind: str):
    return _notes(user, kind).get()


def _send(chat, author, text: str):
    """`messages.send(chat, author, text)` — путь службы со всей транзакцией, включая уведомления."""
    from apps.messenger.services import messages

    return messages.send(chat, author.user, text)


def _marks(*sessions) -> str:
    """Маркеры упоминаний людей: `@[u<id>]` через пробел (CONTRACT-008, 5.2)."""
    return " ".join(f"@[u{session.user.pk}]" for session in sessions)


def _employee(name: str):
    return messenger.make_user(full_name=name)


# --- виды уведомлений (FR-663, FR-664) ---------------------------------------------------------------------------

def test_two_kinds_with_titles_orders_channels_and_module():
    """FR-663, 664: в каталоге два вида «Мессенджер» — `messenger.message` и `messenger.mention`, названия и `order`
    80/81 после видов ленты, каналы по умолчанию «портал» и «почта», обязательности и событий шины нет, внешний текст
    постоянный (без ФИО, названий и отрывков); склейка с текстом — только у сообщения, `still_relevant` — правило
    `notify_rules`, а письмо ждёт срок из настроек (15 минут по умолчанию)."""
    from apps.notify.services import kinds as notify_kinds

    catalog = notify_kinds.catalog()
    module_kinds = [kind for kind in catalog if kind.module == messenger.MESSENGER_MODULE]
    assert [kind.code for kind in module_kinds] == list(messenger.MESSENGER_CODES), (
        f"виды мессенджера в каталоге: {[kind.code for kind in module_kinds]}")
    assert [kind.order for kind in module_kinds] == [80, 81], "порядок видов мессенджера — 80 и 81"

    feed_orders = [kind.order for kind in catalog if kind.module == "Лента"]
    assert feed_orders, "видов ленты в каталоге нет"
    assert min(kind.order for kind in module_kinds) > max(feed_orders), "виды мессенджера стоят не после видов ленты"

    for code, title, module, order, mandatory, channels, events, external in messenger.MESSENGER_KINDS:
        kind = notify_kinds.get(code)
        assert kind.title == title, code
        assert kind.module == module, code
        assert kind.order == order, code
        assert kind.mandatory is mandatory, code
        assert tuple(kind.default_channels) == channels, code
        assert tuple(kind.events) == events, code
        assert kind.external_text == external, code
        assert kind.external_text_of is None, f"{code}: внешний текст зависит от объекта"
        assert kind.available(_employee("Проверяемый Сотрудник").user) is True, f"{code}: вид закрыт сотруднику"

    message_kind, mention_kind = notify_kinds.get(MESSAGE_KIND), notify_kinds.get(MENTION_KIND)
    assert message_kind.coalesce is True and mention_kind.coalesce is False, "склейка — только у сообщения"
    assert callable(message_kind.coalesce_text), "у сообщения нет функции текста склейки"
    assert mention_kind.coalesce_text is None, "у упоминания не должно быть склейки"

    external_text = messenger.MESSENGER_KINDS[0][7]
    assert "«" not in external_text and "»" not in external_text and "@" not in external_text, (
        "внешний текст содержит имя, название или отрывок")

    rules = importlib.import_module("apps.messenger.services.notify_rules")
    still_relevant = getattr(rules, "still_relevant", None)
    assert still_relevant is not None, "у notify_rules нет still_relevant (CONTRACT-008, 5.3)"
    for kind in (message_kind, mention_kind):
        assert kind.still_relevant is still_relevant, f"{kind.code}: проверка перед письмом не из notify_rules"

    author = _employee("Анна Автор")
    member = _employee("Пётр Получатель")
    chat = messenger.group(author, [member], title="Рабочая группа")
    _send(chat, author, "Доброе утро, коллеги")

    note = _note(member.user, MESSAGE_KIND)
    settings_row = support.model("notify.NotifySettings").objects.get_or_create(pk=1)[0]
    assert settings_row.email_delay_minutes == 15, "задержка письма по умолчанию — 15 минут"
    delivery = note.deliveries.get(channel=CHANNEL_EMAIL)
    assert delivery.state == "waiting", f"письмо не ждёт отправки: {delivery.state!r}"
    assert delivery.due_at == note.created_at + timedelta(minutes=settings_row.email_delay_minutes), (
        "срок письма считается по данным настроек, а не таймером")


# --- получатели (FR-663, 664, 666) -------------------------------------------------------------------------------

def test_message_kind_goes_to_every_member_except_author():
    """FR-663, 666: вида `messenger.message` получают все участники чата, кроме автора и уволенных; посторонний
    уведомления не получает; на одно сообщение — одно уведомление каждому получателю."""
    author = _employee("Автор Беседы")
    first = _employee("Первый Участник")
    second = _employee("Второй Участник")
    dismissed = messenger.make_user(state="dismissed", full_name="Уволенный Участник")
    outsider = _employee("Посторонний Сотрудник")
    chat = messenger.group(author, [first, second, dismissed], title="Беседа отдела")

    _send(chat, author, "Привет всем")

    assert _kinds_of(first.user) == [MESSAGE_KIND], "первому участнику не ушло одно уведомление о сообщении"
    assert _kinds_of(second.user) == [MESSAGE_KIND], "второму участнику не ушло одно уведомление о сообщении"
    assert not _notes(user=author.user).exists(), "автору ушло уведомление о своём сообщении"
    assert not _notes(user=dismissed.user).exists(), "уволенному участнику ушло уведомление"
    assert not _notes(user=outsider.user).exists(), "постороннему ушло уведомление"
    assert _notes(kind=MESSAGE_KIND).count() == 2, "на одно сообщение создано не по одному уведомлению"


def test_mention_kind_goes_only_to_mentioned_member():
    """FR-664: вид `messenger.mention` получает только упомянутый участник; остальным участникам идёт обычное
    «Новое сообщение в чате», автору — ничего."""
    author = _employee("Автор Упоминания")
    mentioned = _employee("Алиса Упомянутая")
    other = _employee("Борис Молчащий")
    chat = messenger.group(author, [mentioned, other], title="Беседа упоминаний")

    _send(chat, author, f"Посмотри, пожалуйста {_marks(mentioned)}")

    assert _kinds_of(mentioned.user) == [MENTION_KIND], "упомянутый получил не одно «Упомянул вас в чате»"
    assert _notes(kind=MENTION_KIND).count() == 1, "вид «упоминание» создан не только упомянутому"
    assert _kinds_of(other.user) == [MESSAGE_KIND], "обычному участнику не ушло уведомление о сообщении"
    assert not _notes(user=author.user).exists(), "автору ушло уведомление"


def test_mentioned_gets_only_mention_not_message():
    """FR-664, 666: упомянутому не приходит вдобавок «Новое сообщение в чате» — на одно сообщение у него ровно одно
    уведомление, и это упоминание."""
    author = _employee("Автор Одного")
    mentioned = _employee("Алиса Единственная")
    chat = messenger.group(author, [mentioned], title="Беседа одного")

    _send(chat, author, f"Только тебе {_marks(mentioned)}")

    assert _notes(user=mentioned.user).count() == 1, "упомянутому создано больше одного уведомления"
    assert not _notes(user=mentioned.user, kind=MESSAGE_KIND).exists(), "упомянутому ушло обычное уведомление"
    assert _notes(user=mentioned.user, kind=MENTION_KIND).count() == 1


# --- тексты (FR-663, 664, NFR-708) -------------------------------------------------------------------------------

def test_texts_of_message_and_mention_are_russian():
    """FR-663, 664, NFR-708: тексты по-русски — «<ФИО>: новое сообщение в чате «<название>»» и «<ФИО> упомянул(а)
    вас в чате «<название>»»; ссылка ведёт на сообщение, `object_ref` — `messenger.chat:<id>`; отрывка сообщения в
    уведомлении нет."""
    author = _employee("Анна Авторова")
    mentioned = _employee("Алиса Упомянутая")
    chat = messenger.group(author, [mentioned], title="Рабочая группа")
    body = "секретный план на завтра"
    message = _send(chat, author, f"{body} {_marks(mentioned)}")

    mention_note = _note(mentioned.user, MENTION_KIND)
    assert mention_note.text.startswith("Анна Авторова"), f"текст упоминания: {mention_note.text!r}"
    assert "упомянул" in mention_note.text.lower(), f"текст упоминания: {mention_note.text!r}"
    assert "в чате «Рабочая группа»" in mention_note.text, f"текст упоминания: {mention_note.text!r}"

    regular = _employee("Борис Обычный")
    chat_with_regular = messenger.group(author, [regular], title="Вторая беседа")
    second = _send(chat_with_regular, author, body)
    message_note = _note(regular.user, MESSAGE_KIND)
    assert message_note.text == "Анна Авторова: новое сообщение в чате «Вторая беседа»", (
        f"текст сообщения: {message_note.text!r}")

    for note, chat_of_note in ((mention_note, chat), (message_note, chat_with_regular)):
        assert any("а" <= char.lower() <= "я" for char in note.text), f"текст не по-русски: {note.text!r}"
        assert body not in note.text, "в уведомление попал отрывок сообщения"
        assert note.object_ref == f"messenger.chat:{chat_of_note.pk}", f"object_ref: {note.object_ref!r}"

    assert mention_note.url == f"/messenger/chats/{chat.pk}/#m{message.pk}"
    assert message_note.url == f"/messenger/chats/{chat_with_regular.pk}/#m{second.pk}"


# --- себе и упоминание себя (FR-666) -----------------------------------------------------------------------------

def test_own_message_and_self_mention_give_no_notification():
    """FR-666: своё сообщение и упоминание самого себя уведомлений автору не дают — ни в чате, где он один, ни в общем
    чате; другим участникам уходит обычное уведомление, а не упоминание."""
    author = messenger.make_user(full_name="Автор Себе")
    friend = _employee("Собеседник Другой")

    solo = messenger.group(author, [], title="Сам с собой")
    _send(solo, author, f"Заметка себе {_marks(author)}")
    assert not _notes(user=author.user).exists(), "сообщение себе дало уведомление"

    chat = messenger.group(author, [friend], title="Беседа с собой")
    _send(chat, author, f"Привет {_marks(author)}")
    assert not _notes(user=author.user).exists(), "упоминание себя дало уведомление автору"
    assert _kinds_of(friend.user) == [MESSAGE_KIND], "участник получил упоминание вместо обычного уведомления"
    assert not _notes(kind=MENTION_KIND).exists(), "создан вид «упоминание» на самого себя"


# --- склейка (FR-666) --------------------------------------------------------------------------------------------

def test_three_messages_coalesce_into_one_with_count():
    """FR-666: три сообщения подряд в одном чате до прочтения — одно уведомление «Новых сообщений: 3 в чате «…»»;
    сообщение другого чата даёт отдельное уведомление (ключ склейки — получатель, вид и `object_ref`)."""
    author = _employee("Автор Склейки")
    member = _employee("Пётр Читатель")
    chat = messenger.group(author, [member], title="Беседа склейки")
    other_chat = messenger.group(author, [member], title="Вторая склейка")

    _send(chat, author, "Первое")
    _send(chat, author, "Второе")
    _send(chat, author, "Третье")

    assert _notes(user=member.user, kind=MESSAGE_KIND).count() == 1, "три сообщения дали не одно уведомление"
    note = _note(member.user, MESSAGE_KIND)
    assert note.text == "Новых сообщений: 3 в чате «Беседа склейки»", f"текст склейки: {note.text!r}"
    assert note.object_ref == f"messenger.chat:{chat.pk}"

    _send(other_chat, author, "Другой чат")
    assert _notes(user=member.user, kind=MESSAGE_KIND).count() == 2, "сообщение другого чата склеилось с первым"


# --- правка и удаление (FR-656, FR-657) --------------------------------------------------------------------------

def test_edit_and_delete_create_no_notifications():
    """FR-656, 657: правка (в том числе с новым упоминанием) и удаление сообщения уведомлений не создают — набор
    записей до и после совпадает, новому упомянутому ничего не уходит."""
    from apps.messenger.services import messages

    author = _employee("Автор Правки")
    member = _employee("Пётр Участник")
    added = _employee("Новый Упомянутый")
    chat = messenger.group(author, [member], title="Беседа правки")
    message = _send(chat, author, "Черновик")
    before = set(_notes().values_list("pk", flat=True))
    assert before, "отправка не создала ни одного уведомления"

    messages.edit(message, author.user, f"Черновик {_marks(added)}")
    assert set(_notes().values_list("pk", flat=True)) == before, "правка создала уведомление"
    assert not _notes(user=added.user).exists(), "новому упомянутому правкой ушло уведомление"

    messages.delete(message, author.user)
    assert set(_notes().values_list("pk", flat=True)) == before, "удаление создало уведомление"
    assert not _notes(kind=MENTION_KIND).exists(), "правка или удаление создали вид «упоминание»"