"""T-4102: действующая таблица «вид × канал» и доступность каналов (FR-302, FR-303, FR-304, FR-305, FR-321,
FR-322, FR-344). Сценарии 1 и 4 спеки среза 004.

Что проверяется: строки таблицы (виды, доступные сотруднику и не обязательные), признак `available` видов
сервис-деска, порядок значений ячейки («matrix» сотрудника, затем значения администратора, затем каналы вида
по умолчанию без `portal`), сохранение одних тихих часов, доступность каналов Web Push, Telegram и MAX и разметка
страницы `/me/notifications/` (CONTRACT-004, 6.4, 14.3). Код среза на уровне модуля не импортируется: имена
берутся внутри тестов (CONTRACT-004, шапка).
"""
import importlib
from html.parser import HTMLParser

import pytest

from tests import support
from tests import support_notify as notify
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

CHANNELS = ("portal", "email", "push", "telegram", "max")
EXTERNAL = ("email", "push", "telegram", "max")
NEW_IN_QUEUE = "servicedesk.new_in_queue"
ASSIGNED = "servicedesk.assigned"
REPLIED = "servicedesk.requester_replied"
FAILED = "servicedesk.reply_failed"
SD_CODES = [NEW_IN_QUEUE, ASSIGNED, REPLIED, FAILED]
OTHER_SD_CODES = [ASSIGNED, REPLIED, FAILED]
TITLES = {
    NEW_IN_QUEUE: "Новая заявка в моей очереди",
    ASSIGNED: "Мне назначили заявку",
    REPLIED: "Заявитель ответил",
    FAILED: "Ответ заявителю не ушёл",
}
SECURITY_CODES = ["core.new_device", "core.password_changed", "core.second_factor_reset"]
PAGE = "/me/notifications/"
HEADERS = {"portal": "На портале", "email": "Почта", "push": "Push в браузере", "telegram": "Telegram", "max": "MAX"}


# --- помощники только этого файла -------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.notify.services.{name}")


def _catalog() -> dict:
    return {kind.code: kind for kind in _svc("kinds").catalog()}


def _queue_unit(name: str | None = None):
    """Узел, отмеченный очередью."""
    unit = org.make_unit(name) if name else org.make_unit()
    sd.make_queue(unit)
    return unit


def _member(unit, *, mark: str = ""):
    """Сотрудник, состоящий в узле."""
    user = support.make_employee()
    org.make_member(user, unit, mark=mark)
    return user


def _queue_member(mark: str = ""):
    unit = _queue_unit()
    return _member(unit, mark=mark), unit


def _cells(user) -> dict:
    """Код вида -> ячейки строки действующей таблицы."""
    return {row.kind.code: dict(row.cells) for row in _svc("prefs").effective(user).rows}


def _on(cells: dict) -> list[str]:
    """Внешние каналы, включённые в ячейках строки, в порядке каталога."""
    return [channel for channel in EXTERNAL if cells[channel]]


def _checked(user) -> dict:
    """Что отметила бы форма: код вида -> включённые внешние каналы."""
    return {code: _on(cells) for code, cells in _cells(user).items()}


def _expected(*on: str) -> dict:
    """Ячейки строки: `portal` всегда включён, остальные — по списку."""
    return {channel: channel == "portal" or channel in on for channel in CHANNELS}


def _set_defaults(mapping: dict) -> None:
    """Значения администратора по умолчанию — прямой записью (форма хранения: контракт 2.2)."""
    model("notify.NotifySettings").objects.update_or_create(pk=1, defaults={"defaults": mapping})


def _admin_update(**fields):
    return _svc("settings").update(actor=support.make_admin(), **fields)


def _row_of(user):
    return model("notify.UserNotifySettings").objects.filter(user=user).first()


def _plain(text: str) -> str:
    return " ".join(text.split())


class _Node:
    """Узел разобранной страницы."""

    def __init__(self, tag, attrs, parent, order):
        self.tag, self.attrs, self.parent, self.order = tag, attrs, parent, order
        self.children = []
        self.parts = []

    @property
    def text(self) -> str:
        pieces = []

        def walk(node):
            for item in node.parts:
                if isinstance(item, str):
                    pieces.append(item)
                else:
                    walk(item)

        walk(self)
        return _plain(" ".join(pieces))

    def find_all(self, tag=None, attrs=None) -> list:
        """Потомки по тегу и условиям: значение `True` — атрибут есть, строка — равен ей."""
        found = []
        for node in self.children:
            ok = tag is None or node.tag == tag
            for name, want in (attrs or {}).items():
                if name not in node.attrs or (want is not True and node.attrs[name] != want):
                    ok = False
            if ok:
                found.append(node)
            found.extend(node.find_all(tag, attrs))
        return sorted(found, key=lambda item: item.order)

    def one(self, tag=None, attrs=None):
        found = self.find_all(tag, attrs)
        assert len(found) == 1, f"ожидали один элемент {tag} {attrs}, нашли {len(found)}"
        return found[0]


class _Page(HTMLParser):
    VOID = {"input", "br", "hr", "meta", "link", "img", "source", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {}, None, 0)
        self.current = self.root
        self.counter = 0

    def handle_starttag(self, tag, attrs):
        self.counter += 1
        node = _Node(tag, {name: (value or "") for name, value in attrs}, self.current, self.counter)
        self.current.children.append(node)
        self.current.parts.append(node)
        if tag not in self.VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.current = self.current.parent

    def handle_endtag(self, tag):
        node = self.current
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.current = node.parent

    def handle_data(self, data):
        self.current.parts.append(data)


def _parse(html: str) -> _Node:
    parser = _Page()
    parser.feed(html)
    parser.close()
    return parser.root


def _get(client) -> _Node:
    response = client.get(PAGE)
    assert response.status_code == 200, f"{PAGE}: {response.status_code}"
    return _parse(response.content.decode())


def _page(user) -> _Node:
    return _get(support.logged_in(user))


def _table(root: _Node) -> _Node:
    return root.one("table", {"data-notify-table": True})


def _kind_rows(root: _Node) -> dict:
    return {row.attrs["data-notify-kind"]: row for row in _table(root).find_all("tr", {"data-notify-kind": True})}


def _cell(row: _Node, channel: str) -> _Node:
    return row.one("td", {"data-channel": channel})


def _hint(cell: _Node) -> str:
    found = cell.find_all(None, {"data-hint": True})
    assert len(found) == 1, "в ячейке ожидали одну подсказку [data-hint]"
    return found[0].text


# --- строки действующей таблицы (FR-321, FR-304, FR-305, FR-344) -------------------------------------

def test_effective_table_rows_are_available_non_mandatory_kinds_in_order():
    """FR-321: строки — доступные сотруднику виды без обязательных, в порядке каталога; ячейки — пять каналов по порядку."""
    prefs = _svc("prefs")
    user, _ = _queue_member()
    table = prefs.effective(user)
    assert [row.kind.code for row in table.rows] == SD_CODES
    expected = [kind.code for kind in _svc("kinds").catalog() if not kind.mandatory and kind.available(user)]
    assert [row.kind.code for row in table.rows] == expected
    for row in table.rows:
        assert list(row.cells) == list(CHANNELS)
        assert row.cells["portal"] is True
    outsider = support.make_employee()
    assert prefs.effective(outsider).rows == []


def test_effective_table_excludes_security_kinds_and_channel_unbound():
    """FR-305, FR-321, FR-344: виды безопасности и «Канал отвязан» не строки таблицы, они обязательные и лежат в `fixed`."""
    prefs = _svc("prefs")
    for user in (_queue_member()[0], support.make_employee()):
        table = prefs.effective(user)
        row_codes = {row.kind.code for row in table.rows}
        assert not row_codes & set(SECURITY_CODES + ["notify.channel_unbound"])
        assert sorted(kind.code for kind in table.fixed) == sorted(SECURITY_CODES + ["notify.channel_unbound"])
        assert all(kind.mandatory for kind in table.fixed)


# --- признак `available` видов сервис-деска (FR-304, FR-321) ------------------------------------------

def test_available_new_in_queue_true_for_direct_member_concurrent_head_and_deputy():
    """FR-304, FR-321: «Новая заявка в моей очереди» доступна прямому участнику, совместителю-руководителю и заместителю узла-очереди."""
    unit = _queue_unit()
    plain = _member(unit)
    head = _member(unit, mark="head")
    org.make_member(head, org.make_unit())
    deputy = _member(unit, mark="deputy")
    kind = _catalog()[NEW_IN_QUEUE]
    for user in (plain, head, deputy):
        assert kind.available(user) is True
        assert NEW_IN_QUEUE in [row.kind.code for row in _svc("prefs").effective(user).rows]


def test_available_new_in_queue_false_for_head_of_upper_node_not_marked_as_queue_all_tickets_holder_and_outsider():
    """FR-304, FR-321: руководитель вышестоящего узла, участник узла без отметки очереди, держатель «Все заявки» и посторонний — без вида."""
    parent = org.make_unit()
    sd.make_queue(org.make_unit(parent=parent))
    upper_head = _member(parent, mark="head")
    unmarked = _member(org.make_unit())
    holder = support.make_with_permissions("servicedesk.all")
    outsider = support.make_employee()
    kind = _catalog()[NEW_IN_QUEUE]
    for user in (upper_head, unmarked, holder, outsider):
        assert kind.available(user) is False
        assert NEW_IN_QUEUE not in [row.kind.code for row in _svc("prefs").effective(user).rows]


def test_available_other_sd_kinds_true_for_participant_all_tickets_holder_or_assignee_only():
    """FR-304, FR-321: три остальных вида доступны участнику очереди, держателю «Все заявки» и тому, кто только ответственный по заявке."""
    queue_unit = _queue_unit()
    participant = _member(queue_unit)
    holder = support.make_with_permissions("servicedesk.all")
    assignee = support.make_employee()
    sd.make_ticket(queue=queue_unit, kind="in_progress", assignee=assignee, assigned_once=True)
    catalog = _catalog()
    for user in (participant, holder, assignee):
        for code in OTHER_SD_CODES:
            assert catalog[code].available(user) is True, code
        shown = [row.kind.code for row in _svc("prefs").effective(user).rows]
        assert [code for code in shown if code in OTHER_SD_CODES] == OTHER_SD_CODES


def test_available_other_sd_kinds_false_without_tickets_menu_item():
    """FR-304, FR-321: без пункта «Заявки» (не участник очереди, нет права «Все заявки», нет своих заявок) видов сервис-деска нет."""
    queue_unit = _queue_unit()
    sd.make_ticket(queue=queue_unit)
    outsider = support.make_employee()
    in_unmarked = _member(org.make_unit())
    catalog = _catalog()
    for user in (outsider, in_unmarked):
        for code in SD_CODES:
            assert catalog[code].available(user) is False, code
        assert _svc("prefs").effective(user).rows == []


# --- какие значения действуют (FR-322) --------------------------------------------------------------

def test_effective_uses_admin_defaults_while_employee_never_saved():
    """FR-322: пока сотрудник не сохранял таблицу, действуют значения администратора; пустой список — все внешние каналы выключены."""
    user, _ = _queue_member()
    _set_defaults({ASSIGNED: ["email"], NEW_IN_QUEUE: []})
    cells = _cells(user)
    assert cells[ASSIGNED] == _expected("email")
    assert cells[NEW_IN_QUEUE] == _expected()
    assert cells[REPLIED] == _expected(*EXTERNAL)
    assert _row_of(user) is None


def test_effective_uses_own_matrix_after_first_save():
    """FR-322: после первого сохранения действуют собственные значения сотрудника, снимок хранится в `matrix` без `portal`."""
    user, _ = _queue_member()
    _set_defaults({ASSIGNED: ["email"]})
    submitted = _checked(user)
    submitted[ASSIGNED] = ["push"]
    assert _svc("prefs").save(user, table=submitted) is True
    cells = _cells(user)
    assert cells[ASSIGNED]["push"] is True and cells[ASSIGNED]["email"] is False
    assert cells[ASSIGNED]["portal"] is True
    matrix = _row_of(user).matrix
    assert set(matrix) == set(SD_CODES)
    assert "push" in matrix[ASSIGNED] and "email" not in matrix[ASSIGNED]
    assert all("portal" not in channels for channels in matrix.values())


def test_changing_admin_defaults_does_not_touch_saved_employee_matrix():
    """FR-322: изменение значений администратора не трогает таблицу сотрудника, который её уже сохранял."""
    user, _ = _queue_member()
    _admin_update(defaults={ASSIGNED: ["email"]})
    submitted = _checked(user)
    submitted[ASSIGNED] = ["push"]
    _svc("prefs").save(user, table=submitted)
    before_cells, before_matrix = _cells(user), dict(_row_of(user).matrix)
    _admin_update(defaults={ASSIGNED: ["telegram"], FAILED: []})
    assert _cells(user) == before_cells
    assert _row_of(user).matrix == before_matrix


def test_changing_admin_defaults_applies_to_employee_who_never_saved():
    """FR-322: изменение значений администратора сразу действует у сотрудника, который таблицу не сохранял."""
    user, _ = _queue_member()
    assert _cells(user)[ASSIGNED] == _expected(*EXTERNAL)
    _admin_update(defaults={ASSIGNED: ["telegram"], FAILED: []})
    cells = _cells(user)
    assert cells[ASSIGNED] == _expected("telegram")
    assert cells[FAILED] == _expected()
    assert _row_of(user) is None


def test_kind_absent_from_matrix_takes_value_from_defaults():
    """FR-322: вида нет в `matrix` сотрудника (его добавили позже) — значение берётся из значений администратора."""
    user, _ = _queue_member()
    model("notify.UserNotifySettings").objects.create(user=user, matrix={ASSIGNED: ["email"]})
    _set_defaults({REPLIED: ["push"], ASSIGNED: ["telegram"]})
    cells = _cells(user)
    assert cells[ASSIGNED] == _expected("email")
    assert cells[REPLIED] == _expected("push")


def test_kind_absent_from_matrix_and_defaults_takes_default_channels():
    """FR-322: вида нет ни в `matrix`, ни в значениях администратора — действуют `default_channels` вида без `portal`."""
    from apps.core.extensions import NotificationKind

    extensions = importlib.import_module("apps.core.extensions")
    kind = NotificationKind(code="test.alpha", title="Тестовый вид", module="Тест",
                            default_channels=("portal", "email"))
    user = support.make_employee()
    with extensions.empty():
        notify.register_kind(kind)
        assert _cells(user) == {"test.alpha": _expected("email")}
        model("notify.UserNotifySettings").objects.create(user=user, matrix={"servicedesk.other": ["push"]})
        _set_defaults({"servicedesk.other": ["max"]})
        assert _cells(user) == {"test.alpha": _expected("email")}


def test_saving_only_quiet_hours_does_not_freeze_admin_defaults_into_matrix():
    """FR-322: сохранение одних тихих часов не пишет `matrix`: значения администратора по-прежнему следуют за его изменениями."""
    prefs = _svc("prefs")
    user, _ = _queue_member()
    _set_defaults({ASSIGNED: ["email"]})
    assert prefs.save(user, quiet_mode="none") is True
    row = _row_of(user)
    assert row.quiet_mode == "none"
    assert row.matrix == {}
    _set_defaults({ASSIGNED: ["push"]})
    assert _cells(user)[ASSIGNED] == _expected("push")
    assert prefs.save(user, table=_checked(user)) is False
    assert _row_of(user).matrix == {}


# --- доступность каналов (FR-302, FR-303, FR-321) -----------------------------------------------------

def test_portal_and_email_channels_always_available():
    """FR-303, FR-321: «На портале» и «Почта» доступны всегда, при любых настройках администратора; `push` в таблице доступен всегда."""
    prefs = _svc("prefs")
    user = support.make_employee()
    table = prefs.effective(user)
    assert set(table.channels) == set(CHANNELS)
    for channel in ("portal", "email"):
        assert table.channels[channel].available is True
        assert table.channels[channel].reason == ""
    assert table.channels["push"].available is True
    model("notify.NotifySettings").objects.update_or_create(
        pk=1, defaults={"webpush_enabled": False, "telegram_enabled": False, "max_enabled": False})
    states = prefs.channel_states(user.pk)
    for channel in ("portal", "email"):
        assert states[channel].available is True and states[channel].reason == ""


def test_web_push_available_only_when_enabled_by_admin_and_subscription_exists(webpush_on):
    """FR-321, FR-302: Web Push доступен, когда он включён администратором с ключами и у сотрудника есть подписка; причины — по контракту."""
    prefs = _svc("prefs")
    settings_row = model("notify.NotifySettings").objects.filter(pk=1)
    user, other = support.make_employee(), support.make_employee()
    settings_row.update(webpush_enabled=False)
    table = prefs.effective(user)
    assert (table.web_push_available, table.web_push_reason) == (False, "channel_disabled")
    settings_row.update(webpush_enabled=True)
    table = prefs.effective(user)
    assert (table.web_push_available, table.web_push_reason) == (False, "no_subscriptions")
    notify.subscribe(user)
    table = prefs.effective(user)
    assert (table.web_push_available, table.web_push_reason) == (True, "")
    other_table = prefs.effective(other)
    assert (other_table.web_push_available, other_table.web_push_reason) == (False, "no_subscriptions")
    settings_row.update(webpush_enabled=False)
    table = prefs.effective(user)
    assert (table.web_push_available, table.web_push_reason) == (False, "channel_disabled")
    assert table.channels["push"].available is True


def test_telegram_and_max_available_only_with_enabled_channel_token_and_binding(bots_on, settings):
    """FR-321, FR-302: Telegram и MAX доступны при включённом канале, заданных ключах и привязке сотрудника; иначе причина по контракту."""
    prefs = _svc("prefs")
    user, other = support.make_employee(), support.make_employee()
    bound = model("notify.ChatBinding")
    bound.objects.create(user=other, channel="telegram", chat_id="9001")
    for channel in ("telegram", "max"):
        state = prefs.channel_states(user.pk)[channel]
        assert (state.available, state.reason) == (False, "not_bound")
    _svc("binding").bind(user.pk, "telegram", "4242")
    bound.objects.create(user=user, channel="max", chat_id="777")
    states = prefs.channel_states(user.pk)
    assert (states["telegram"].available, states["telegram"].reason) == (True, "")
    assert (states["max"].available, states["max"].reason) == (True, "")
    table = prefs.effective(user)
    assert table.channels["telegram"].available is True and table.channels["max"].available is True
    model("notify.NotifySettings").objects.filter(pk=1).update(telegram_enabled=False)
    settings.MAX_BOT_TOKEN = ""
    states = prefs.channel_states(user.pk)
    assert (states["telegram"].available, states["telegram"].reason) == (False, "channel_disabled")
    assert (states["max"].available, states["max"].reason) == (False, "channel_disabled")


# --- страница «Мои уведомления» (FR-302, FR-303, FR-305, FR-321, FR-344) -------------------------------

def test_my_notifications_page_has_five_channel_columns_portal_checked_and_fixed():
    """FR-302, FR-303, FR-321: пять столбцов по порядку; ячейка «На портале» отмечена, заблокирована и ничего не присылает."""
    user, _ = _queue_member()
    root = _page(user)
    table = _table(root)
    heads = table.find_all("th", {"data-channel": True})
    assert [head.attrs["data-channel"] for head in heads] == list(CHANNELS)
    assert [head.text for head in heads] == [HEADERS[channel] for channel in CHANNELS]
    rows = _kind_rows(root)
    assert list(rows) == SD_CODES
    for row in rows.values():
        cells = row.find_all("td", {"data-channel": True})
        assert [cell.attrs["data-channel"] for cell in cells] == list(CHANNELS)
        portal = _cell(row, "portal")
        assert portal.attrs.get("data-locked") == "1"
        box = portal.one("input", {"type": "checkbox"})
        assert "checked" in box.attrs and "disabled" in box.attrs
        assert "name" not in box.attrs
    assert not [box for box in table.find_all("input", {"name": "cell"}) if box.attrs.get("value", "").endswith(":portal")]


def test_my_notifications_page_rows_show_kind_title_and_module():
    """FR-321: строка вида показывает название и модуль (`[data-field]`)."""
    user, _ = _queue_member()
    for code, row in _kind_rows(_page(user)).items():
        assert row.one(None, {"data-field": "title"}).text == TITLES[code]
        assert row.one(None, {"data-field": "module"}).text == "Сервис-деск"


def test_my_notifications_page_push_is_one_column_for_both_push_kinds():
    """FR-302: системное уведомление во вкладке и Web Push — один столбец `push`: ни второго столбца, ни ячеек с другим кодом."""
    user, _ = _queue_member()
    root = _page(user)
    table = _table(root)
    heads = [head.attrs["data-channel"] for head in table.find_all("th", {"data-channel": True})]
    assert heads.count("push") == 1 and len(heads) == 5
    for row in _kind_rows(root).values():
        assert len(row.find_all("td", {"data-channel": "push"})) == 1
        assert len(row.find_all("td", {"data-channel": True})) == 5
    values = [box.attrs.get("value", "") for box in table.find_all("input", {"name": "cell"})]
    assert sorted(value.split(":", 1)[1] for value in values if value.endswith(":push")) == ["push"] * 4
    assert not [value for value in values if value.endswith(":webpush")]


def test_my_notifications_page_telegram_column_unavailable_with_bind_hint(bots_on):
    """FR-321: пока Telegram не привязан, ячейка недоступна: без флажка, с подсказкой «Привяжите Telegram»; после привязки — флажок."""
    user, _ = _queue_member()
    client = support.logged_in(user)
    rows = _kind_rows(_get(client))
    for code, row in rows.items():
        telegram, max_cell = _cell(row, "telegram"), _cell(row, "max")
        assert telegram.attrs.get("data-available") == "0"
        assert telegram.attrs.get("data-reason") == "not_bound"
        assert not telegram.find_all("input")
        assert _hint(telegram) == "Привяжите Telegram"
        assert max_cell.attrs.get("data-available") == "0"
        assert not max_cell.find_all("input")
        assert _hint(max_cell) == "Привяжите MAX"
    _svc("binding").bind(user.pk, "telegram", "4242")
    for code, row in _kind_rows(_get(client)).items():
        telegram = _cell(row, "telegram")
        assert telegram.attrs.get("data-available") == "1"
        box = telegram.one("input", {"type": "checkbox", "name": "cell"})
        assert box.attrs["value"] == f"{code}:telegram"
        assert _cell(row, "max").attrs.get("data-available") == "0"


def test_my_notifications_page_push_column_carries_permission_hint_and_script_hook_server_does_not_read_permission(request):
    """FR-321, FR-302: разметка столбца `push` зависит только от Web Push (признак, причина, подсказка), флажок без `disabled`, кнопка разрешения есть всегда."""
    user, unit = _queue_member()
    second = _member(unit)
    model("notify.UserNotifySettings").objects.create(user=second, matrix={code: [] for code in SD_CODES})
    client = support.logged_in(user)
    second_client = support.logged_in(second)
    admin_text = "Push при закрытой вкладке отключён администратором"
    allow_text = "Разрешите push на этом устройстве"

    def push_cells(root):
        return {code: _cell(row, "push") for code, row in _kind_rows(root).items()}

    def check(root, available, reason, hint):
        assert len(root.find_all("button", {"data-action": "push-permission"})) == 1
        assert len(push_cells(root)) == 4
        for code, cell in push_cells(root).items():
            assert cell.attrs.get("data-available") == available
            assert cell.attrs.get("data-reason", "") == reason
            box = cell.one("input", {"type": "checkbox", "name": "cell"})
            assert box.attrs["value"] == f"{code}:push"
            assert "disabled" not in box.attrs
            if hint:
                assert _hint(cell) == hint

    check(_get(client), "0", "channel_disabled", admin_text)
    request.getfixturevalue("webpush_on")
    first_root, second_root = _get(client), _get(second_client)
    check(first_root, "0", "no_subscriptions", allow_text)
    check(second_root, "0", "no_subscriptions", allow_text)
    for code in SD_CODES:
        mine, theirs = push_cells(first_root)[code], push_cells(second_root)[code]
        assert mine.one("input", {"name": "cell"}).attrs.get("checked") is not None
        assert "checked" not in theirs.one("input", {"name": "cell"}).attrs
        assert _hint(mine) == _hint(theirs)
    notify.subscribe(user)
    check(_get(client), "1", "", "")


def test_my_notifications_page_security_and_unbound_rows_without_checkboxes():
    """FR-305, FR-321, FR-344: две сводные строки «Безопасность: всегда» и «Канал отвязан: всегда, только на портале» без флажков после строк видов."""
    for user in (_queue_member()[0], support.make_employee()):
        root = _page(user)
        table = _table(root)
        fixed = table.find_all("tr", {"data-notify-fixed": True})
        assert sorted(row.attrs["data-notify-fixed"] for row in fixed) == ["channel_unbound", "security"]
        by_name = {row.attrs["data-notify-fixed"]: row for row in fixed}
        assert "Безопасность: всегда" in by_name["security"].text
        assert "Канал отвязан: всегда, только на портале" in by_name["channel_unbound"].text
        for row in fixed:
            assert not row.find_all("input")
            assert row.parent.tag == "tbody" and "data-fixed-rows" in row.parent.attrs
        kind_rows = list(_kind_rows(root).values())
        assert all(row.order < min(item.order for item in fixed) for row in kind_rows)
        assert not [code for code in _kind_rows(root) if code.startswith(("core.", "notify."))]
