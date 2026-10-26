"""T-4125: «Мои уведомления» — таблица «вид × канал», тихие часы, сохранение (FR-321…FR-325, FR-336, FR-342).
Сценарии 4, 5 и 8 спеки среза 004.

Маршрут `/me/notifications/` — CONTRACT-004 § 13.2; зацепки — § 14.3; коды отказов — § 6.2; тексты — § 15.4-15.5;
решения B1 (ячейки недоступных каналов не меняются), D4 (две сводные строки), D5 (ячейка `push` всегда с флажком),
дополнения 10 и 18 раздела 17. Страницу и ответы разбирает `html.parser` (разбор скопирован из test_notify_pages.py),
элементы ищутся по зацепкам. Тела POST собираются так же, как это делает браузер: из разметки страницы (отмеченные
`cell`, выбранный режим, отмеченные дни, время). Имена кода среза 004 — внутри тестов или через `support.model`.
"""
import datetime
from html.parser import HTMLParser

import pytest

from tests import support, support_notify, support_org, support_servicedesk
from tests.support import HX, model

pytestmark = pytest.mark.django_db

URL = "/me/notifications/"
CHANNELS = ("portal", "email", "push", "telegram", "max")

NEW_IN_QUEUE = "servicedesk.new_in_queue"
ASSIGNED = "servicedesk.assigned"
REPLIED = "servicedesk.requester_replied"
FAILED = "servicedesk.reply_failed"
SD_KINDS = (NEW_IN_QUEUE, ASSIGNED, REPLIED, FAILED)
RUBRIC_KIND = "knowledge.rubric_subscription"   # пятая строка таблицы участника очереди: вид доступен всем (срез 005)
LISTS_KIND = "lists.deadline"   # шестая строка таблицы: вид доступен всем (срез 006, CONTRACT-006, раздел 7.3)
TITLES = {NEW_IN_QUEUE: "Новая заявка в моей очереди", ASSIGNED: "Мне назначили заявку",
          REPLIED: "Заявитель ответил", FAILED: "Ответ заявителю не ушёл",
          RUBRIC_KIND: "Статья в рубрике по подписке", LISTS_KIND: "Срок в записи списка"}
EXTERNAL = ["email", "push", "telegram", "max"]     # `default_channels` видов сервис-деска без `portal`


# --- разбор разметки -----------------------------------------------------------------------------------------

_VOID = {"meta", "link", "input", "br", "hr", "img", "source", "area", "base", "col", "embed", "param", "track", "wbr"}


class _El:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.raw = tag, attrs, parent, ""

    @property
    def text(self) -> str:
        return " ".join(self.raw.split())


class _Doc(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.elements, self._stack = [], []
        self.feed(html)

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


def doc_of(response) -> _Doc:
    return _Doc(response.content.decode("utf-8", "replace"))


def inside(el, ancestor) -> bool:
    node = el.parent
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent
    return False


def find(doc, tag=None, attrs=None, *, within=None) -> list:
    """Элементы с тегом и атрибутами (`True` — атрибут есть с любым значением); `within` — только потомки."""
    wanted = attrs or {}
    found = [el for el in doc.elements
             if (tag is None or el.tag == tag) and all(k in el.attrs and (v is True or el.attrs[k] == v)
                                                      for k, v in wanted.items())]
    return [el for el in found if inside(el, within)] if within is not None else found


def one(doc, tag=None, attrs=None, *, within=None):
    found = find(doc, tag, attrs, within=within)
    assert len(found) == 1, f"ожидали один элемент {tag or '*'}{attrs}, нашли {len(found)}"
    return found[0]


# --- данные теста ----------------------------------------------------------------------------------------------

def _member():
    """Сотрудник — прямой участник очереди (ему видны все четыре вида сервис-деска) и его клиент."""
    user = support.make_employee()
    queue = support_servicedesk.make_queue()
    support_org.make_member(user, queue.unit)
    return user, support.logged_in(user)


def _set_admin(**fields) -> None:
    model("notify.NotifySettings").objects.update_or_create(pk=1, defaults=fields)


def _bind(user, channel: str) -> None:
    model("notify.ChatBinding").objects.create(user=user, channel=channel, chat_id=f"{user.pk}00{len(channel)}")


def _get(client):
    response = client.get(URL)
    assert response.status_code == 200, f"GET {URL}: {response.status_code}"
    return doc_of(response)


def _row(doc, code: str):
    return one(doc, "tr", {"data-notify-kind": code})


def _td(doc, code: str, channel: str):
    return one(doc, "td", {"data-channel": channel}, within=_row(doc, code))


def _box(doc, code: str, channel: str):
    """Флажок ячейки или `None`, если в ячейке флажка нет."""
    boxes = find(doc, "input", {"type": "checkbox"}, within=_td(doc, code, channel))
    assert len(boxes) <= 1, f"в ячейке {code}:{channel} несколько флажков"
    return boxes[0] if boxes else None


def _on(doc, code: str, channel: str) -> bool:
    box = _box(doc, code, channel)
    assert box is not None, f"в ячейке {code}:{channel} нет флажка"
    return "checked" in box.attrs


def _form_data(doc, *, off=(), on=(), **extra) -> dict:
    """Тело POST, как его соберёт браузер из страницы: `table=1`, отмеченные `cell`, режим, дни, время.
    `off` и `on` — ячейки вида `код:канал`, которые нужно снять или поставить; `extra` заменяет поля целиком."""
    cells = [el.attrs["value"] for el in find(doc, "input", {"type": "checkbox", "name": "cell"})
             if "checked" in el.attrs]
    cells = [c for c in cells if c not in off] + [c for c in on if c not in cells]
    modes = [el.attrs["value"] for el in find(doc, "input", {"type": "radio", "name": "quiet_mode"})
             if "checked" in el.attrs]
    days = [el.attrs["value"] for el in find(doc, "input", {"type": "checkbox", "name": "own_days"})
            if "checked" in el.attrs]
    start = one(doc, "input", {"type": "time", "name": "own_start"}).attrs.get("value", "")
    end = one(doc, "input", {"type": "time", "name": "own_end"}).attrs.get("value", "")
    data = {"table": "1", "cell": cells, "quiet_mode": modes[0] if modes else "calendar", "own_days": days,
            "own_start": start, "own_end": end}
    data.update(extra)
    return {name: value for name, value in data.items() if value is not None}


def _saved(client, data: dict, **headers):
    """POST, который должен пройти: 302 на страницу; возвращает страницу, где показано сообщение об успехе."""
    response = client.post(URL, data, **headers)
    assert response.status_code == 302 and response["Location"] == URL, (
        f"POST {URL}: ждали 302 на {URL}, получили {response.status_code}")
    return _get(client)


def _refused(client, data: dict, **headers):
    response = client.post(URL, data, **headers)
    assert response.status_code == 200, f"отказ формы должен быть 200 той же страницы, получили {response.status_code}"
    return response


def _settings_row(user):
    return model("notify.UserNotifySettings").objects.filter(user=user).first()


def _error(doc, field: str, code: str):
    el = one(doc, None, {"data-error": field, "data-code": code})
    assert el.text, f"у ошибки {field}/{code} нет текста для сотрудника"
    return el


def _audit_count(user) -> int:
    return model("core.AuditEvent").objects.filter(action="notify.user_settings_changed",
                                                   object_id=str(user.pk)).count()


# --- строки и столбцы таблицы (FR-321) ------------------------------------------------------------------------

def test_table_rows_show_kind_title_and_module():
    """FR-321: у участника очереди в таблице шесть строк по порядку каталога: четыре вида сервис-деска, вид «Статья в рубрике по подписке»
    и вид «Срок в записи списка» (оба доступны всем, срезы 005 и 006); у каждой строки `tr[data-notify-kind]` — название вида
    в `[data-field=title]` и модуль («Сервис-деск», «База знаний» или «Списки») в `[data-field=module]`;
    виды `mandatory` отдельными строками видов не показаны."""
    user, client = _member()
    doc = _get(client)
    table = one(doc, "table", {"data-notify-table": True})
    rows = find(doc, "tr", {"data-notify-kind": True}, within=table)
    assert [r.attrs["data-notify-kind"] for r in rows] == list(SD_KINDS) + [RUBRIC_KIND, LISTS_KIND], (
        "строки видов или их порядок")
    for row in rows:
        code = row.attrs["data-notify-kind"]
        assert one(doc, None, {"data-field": "title"}, within=row).text == TITLES[code]
        expected_module = {RUBRIC_KIND: "База знаний", LISTS_KIND: "Списки"}.get(code, "Сервис-деск")  # CONTRACT-006, 7.3
        assert one(doc, None, {"data-field": "module"}, within=row).text == expected_module
    assert not find(doc, "tr", {"data-notify-kind": "core.new_device"})
    assert not find(doc, "tr", {"data-notify-kind": "notify.channel_unbound"})


def test_table_has_five_channel_columns_in_order():
    """FR-321: заголовки таблицы — «На портале», «Почта», «Push в браузере», «Telegram», «MAX» по порядку
    (`th[data-channel]`), у каждой строки вида пять `td[data-channel]` в том же порядке. Таблица с пятью
    заголовками и `tbody[data-fixed-rows]` есть и у сотрудника без очередей и прав: у него две строки — вид «по подписке» (доп. 18а, срез 005)
    и вид «Срок в записи списка» (срез 006, CONTRACT-006, раздел 7.3)."""
    user, client = _member()
    doc = _get(client)
    table = one(doc, "table", {"data-notify-table": True})
    heads = find(doc, "th", {"data-channel": True}, within=table)
    assert [(h.attrs["data-channel"], h.text) for h in heads] == [
        ("portal", "На портале"), ("email", "Почта"), ("push", "Push в браузере"), ("telegram", "Telegram"),
        ("max", "MAX")]
    for code in SD_KINDS:
        cells = find(doc, "td", {"data-channel": True}, within=_row(doc, code))
        assert [c.attrs["data-channel"] for c in cells] == list(CHANNELS), f"ячейки строки {code}"

    plain = support.make_employee()
    doc = _get(support.logged_in(plain))
    table = one(doc, "table", {"data-notify-table": True})
    assert [h.attrs["data-channel"] for h in find(doc, "th", {"data-channel": True}, within=table)] == list(CHANNELS)
    assert [r.attrs["data-notify-kind"] for r in find(doc, "tr", {"data-notify-kind": True})] == [RUBRIC_KIND, LISTS_KIND], (
        "у сотрудника без прав и очередей в таблице ровно две строки — виды «по подписке» и «Срок в записи списка» "
        "(доступны всем)")
    one(doc, "tbody", {"data-fixed-rows": True})


def test_portal_column_checked_and_locked_for_every_kind():
    """FR-321: ячейка «На портале» каждой строки — `td[data-locked=1]` с флажком `checked` и `disabled`, без `name`
    (ничего не присылает); так у всех видов."""
    user, client = _member()
    doc = _get(client)
    for code in SD_KINDS:
        cell = _td(doc, code, "portal")
        assert cell.attrs.get("data-locked") == "1", f"{code}: ячейка портала не заблокирована"
        box = _box(doc, code, "portal")
        assert box is not None, f"{code}: в ячейке портала нет флажка"
        assert "checked" in box.attrs and "disabled" in box.attrs, f"{code}: флажок портала не checked+disabled"
        assert "name" not in box.attrs, f"{code}: у флажка портала есть name"


def test_post_cannot_switch_off_portal_channel():
    """FR-321: канал «На портале» нельзя выключить: поле `cell` со значением `<вид>:portal` отбрасывается,
    в `matrix` кода `portal` нет, а после сохранения, где `portal` ни у одного вида не отмечен, все ячейки портала
    по-прежнему отмечены и заблокированы."""
    user, client = _member()
    data = {"table": "1", "cell": [f"{ASSIGNED}:portal", f"{ASSIGNED}:email", f"{REPLIED}:portal"]}
    doc = _saved(client, data)
    row = _settings_row(user)
    assert row is not None, "строка настроек не создана: ячейки других каналов изменились"
    # Telegram и MAX здесь недоступны (нет привязок и службы ботов): их ячейки сохраняют прежнее значение (B1);
    # `push` доступен всегда и в POST не прислан у видов, кроме отмеченных, — снят.
    assert row.matrix[ASSIGNED] == ["email", "telegram", "max"]
    assert row.matrix[NEW_IN_QUEUE] == ["telegram", "max"] and row.matrix[REPLIED] == ["telegram", "max"]
    assert all("portal" not in channels for channels in row.matrix.values()), "в matrix сохранён portal"
    for code in SD_KINDS:
        assert _td(doc, code, "portal").attrs.get("data-locked") == "1"
        assert "checked" in _box(doc, code, "portal").attrs


def test_mandatory_security_kinds_shown_as_always_row_without_checkboxes():
    """FR-321: три вида безопасности показаны одной сводной строкой `tr[data-notify-fixed=security]`
    «Безопасность: всегда» в `tbody[data-fixed-rows]`, без флажков (решение D4); строк видов `core.*` нет."""
    user, client = _member()
    doc = _get(client)
    fixed_body = one(doc, "tbody", {"data-fixed-rows": True})
    row = one(doc, "tr", {"data-notify-fixed": "security"})
    assert inside(row, fixed_body)
    assert "Безопасность: всегда" in row.text
    assert not find(doc, "input", within=row), "в строке «Безопасность» есть флажки"
    for code in ("core.new_device", "core.password_changed", "core.second_factor_reset"):
        assert not find(doc, "tr", {"data-notify-kind": code}), f"вид {code} показан отдельной строкой"


def test_channel_unbound_kind_shown_portal_only_row_without_checkboxes():
    """FR-321: вид «Канал отвязан» — сводная строка `tr[data-notify-fixed=channel_unbound]` «Канал отвязан: всегда,
    только на портале» без флажков; сводных строк ровно две (решение D4)."""
    user, client = _member()
    doc = _get(client)
    fixed_body = one(doc, "tbody", {"data-fixed-rows": True})
    row = one(doc, "tr", {"data-notify-fixed": "channel_unbound"})
    assert inside(row, fixed_body)
    assert "Канал отвязан: всегда, только на портале" in row.text
    assert not find(doc, "input", within=row), "в строке «Канал отвязан» есть флажки"
    assert len(find(doc, "tr", {"data-notify-fixed": True})) == 2
    assert not find(doc, "tr", {"data-notify-kind": "notify.channel_unbound"})


def test_queue_kind_hidden_for_employee_who_is_not_direct_queue_member():
    """FR-321: «Новая заявка в моей очереди» не показана сотруднику, который не прямой участник очереди — ни
    держателю «Все заявки», ни руководителю вышестоящего узла; остальные виды сервис-деска и сводные строки при
    этом на странице есть."""
    holder = support.make_with_permissions("servicedesk.all")
    doc = _get(support.logged_in(holder))
    assert not find(doc, "tr", {"data-notify-kind": NEW_IN_QUEUE}), "вид очереди показан не члену очереди"
    one(doc, "tr", {"data-notify-kind": ASSIGNED})
    one(doc, "tr", {"data-notify-fixed": "security"})

    parent = support_org.make_unit()
    child = support_org.make_unit(parent=parent)
    support_servicedesk.make_queue(child)
    head = support.make_with_permissions("servicedesk.all")
    support_org.make_member(head, parent, mark="head")
    doc = _get(support.logged_in(head))
    assert not find(doc, "tr", {"data-notify-kind": NEW_IN_QUEUE}), "вид очереди показан руководителю вышестоящего узла"
    one(doc, "table", {"data-notify-table": True})


def test_queue_kind_shown_for_direct_queue_member():
    """FR-321: прямому участнику очереди (в том числе заместителю руководителя этого же узла) вид «Новая заявка в
    моей очереди» показан со всеми пятью ячейками."""
    user, client = _member()
    doc = _get(client)
    row = _row(doc, NEW_IN_QUEUE)
    assert len(find(doc, "td", {"data-channel": True}, within=row)) == 5

    deputy = support.make_employee()
    queue = support_servicedesk.make_queue()
    support_org.make_member(deputy, queue.unit, mark="deputy")
    doc = _get(support.logged_in(deputy))
    one(doc, "tr", {"data-notify-kind": NEW_IN_QUEUE})


# --- доступность каналов (FR-321, FR-324, FR-325, FR-336) ---------------------------------------------------

def test_unbound_telegram_and_max_columns_unavailable_with_bind_hint(bots_on):
    """FR-321, FR-325: канал включён, но привязки нет — ячейки Telegram и MAX у каждой строки
    `data-available=0`, `data-reason=not_bound`, без флажка, с подсказкой «Привяжите Telegram» / «Привяжите MAX»;
    после привязки Telegram его ячейки доступны (флажок `cell`), MAX остаётся недоступным."""
    user, client = _member()
    doc = _get(client)
    for code in SD_KINDS:
        for channel, hint in (("telegram", "Привяжите Telegram"), ("max", "Привяжите MAX")):
            cell = _td(doc, code, channel)
            assert cell.attrs.get("data-available") == "0", f"{code}:{channel} доступна без привязки"
            assert cell.attrs.get("data-reason") == "not_bound"
            assert not find(doc, "input", within=cell), f"{code}:{channel}: у недоступной ячейки есть флажок"
            assert one(doc, None, {"data-hint": True}, within=cell).text == hint

    _bind(user, "telegram")
    doc = _get(client)
    for code in SD_KINDS:
        cell = _td(doc, code, "telegram")
        assert cell.attrs.get("data-available") == "1"
        box = _box(doc, code, "telegram")
        assert box is not None and box.attrs.get("name") == "cell" and box.attrs.get("value") == f"{code}:telegram"
        assert "disabled" not in box.attrs
        assert _td(doc, code, "max").attrs.get("data-reason") == "not_bound"


def test_browser_push_column_unavailable_without_subscription_with_allow_hint(webpush_on):
    """FR-321, FR-324: Web Push включён, но подписки нет — ячейка `push` у каждой строки `data-available=0`,
    `data-reason=no_subscriptions`, с подсказкой «Разрешите push на этом устройстве»; флажок в ней есть всегда
    (`name=cell`, `value=<вид>:push`) и без `disabled` (решение D5); после подписки `data-available=1`."""
    user, client = _member()
    doc = _get(client)
    for code in SD_KINDS:
        cell = _td(doc, code, "push")
        assert cell.attrs.get("data-available") == "0"
        assert cell.attrs.get("data-reason") == "no_subscriptions"
        assert one(doc, None, {"data-hint": True}, within=cell).text == "Разрешите push на этом устройстве"
        box = _box(doc, code, "push")
        assert box is not None, f"{code}: у ячейки push нет флажка"
        assert box.attrs.get("name") == "cell" and box.attrs.get("value") == f"{code}:push"
        assert "disabled" not in box.attrs, f"{code}: флажок push с disabled"

    support_notify.subscribe(user)
    doc = _get(client)
    for code in SD_KINDS:
        cell = _td(doc, code, "push")
        assert cell.attrs.get("data-available") == "1" and cell.attrs.get("data-reason") == ""


def test_channel_disabled_by_admin_column_unavailable_with_disabled_hint(bots_on, webpush_on):
    """FR-321, FR-336: пока каналы включены и у сотрудника есть привязки и подписка — ячейки доступны; когда
    администратор выключил Web Push, Telegram и MAX, их ячейки `data-available=0`, `data-reason=channel_disabled`
    (главнее `not_bound`, доп. 18б); у Telegram и MAX флажка нет, подсказка «Канал отключён администратором»;
    у `push` флажок остаётся без `disabled`, подсказка называет отключение администратором."""
    user, client = _member()
    _bind(user, "telegram")
    _bind(user, "max")
    support_notify.subscribe(user)
    doc = _get(client)
    for channel in ("push", "telegram", "max"):
        assert _td(doc, ASSIGNED, channel).attrs.get("data-available") == "1", f"{channel} недоступен при включённом"

    _set_admin(webpush_enabled=False, telegram_enabled=False, max_enabled=False)
    doc = _get(client)
    for code in SD_KINDS:
        push = _td(doc, code, "push")
        assert push.attrs.get("data-available") == "0" and push.attrs.get("data-reason") == "channel_disabled"
        assert "отключён администратором" in one(doc, None, {"data-hint": True}, within=push).text
        box = _box(doc, code, "push")
        assert box is not None and "disabled" not in box.attrs
        for channel in ("telegram", "max"):
            cell = _td(doc, code, channel)
            assert cell.attrs.get("data-available") == "0" and cell.attrs.get("data-reason") == "channel_disabled"
            assert not find(doc, "input", within=cell)
            assert one(doc, None, {"data-hint": True}, within=cell).text == "Канал отключён администратором"

    other = support.make_employee()
    support_org.make_member(other, support_servicedesk.make_queue().unit)
    doc = _get(support.logged_in(other))
    assert _td(doc, ASSIGNED, "telegram").attrs.get("data-reason") == "channel_disabled", (
        "у непривязанного при выключенном канале причина — channel_disabled, а не not_bound")


# --- значения ячеек и сохранение таблицы (FR-321, FR-322) -------------------------------------------------

def test_unchecking_mail_cell_saves_own_matrix_and_keeps_portal():
    """FR-321: сотрудник снимает галочку «Почта» у одного вида и сохраняет: создаётся его строка настроек,
    на странице почта этого вида снята, у других видов отмечена, «На портале» отмечен; сообщение об успехе —
    `[role=status]`; недоступные каналы (Telegram, MAX) сохраняют прежнее значение (решение B1)."""
    user, client = _member()
    doc = _get(client)
    assert _settings_row(user) is None, "просмотр страницы создал строку настроек"
    doc = _saved(client, _form_data(doc, off=[f"{ASSIGNED}:email"]))
    statuses = find(doc, None, {"role": "status"})
    assert any("Настройки уведомлений сохранены." in el.text for el in statuses), "нет сообщения об успехе"

    row = _settings_row(user)
    assert row is not None
    assert row.matrix[ASSIGNED] == ["push", "telegram", "max"]
    for code in (NEW_IN_QUEUE, REPLIED, FAILED):
        assert row.matrix[code] == EXTERNAL, f"{code}: ячейки без изменений должны остаться действующими"
    assert not _on(doc, ASSIGNED, "email")
    assert _on(doc, ASSIGNED, "push")
    assert _on(doc, REPLIED, "email") and _on(doc, NEW_IN_QUEUE, "email")
    for code in SD_KINDS:
        assert "checked" in _box(doc, code, "portal").attrs


def test_first_view_shows_admin_defaults_as_checked_cells(bots_on):
    """FR-322: пока сотрудник не сохранял таблицу, галочки показывают значения администратора: вид со своим
    списком — по списку (пустой список — всё снято), вида в `defaults` нет — каналы вида по умолчанию;
    просмотр строку настроек сотрудника не создаёт."""
    user, client = _member()
    _bind(user, "telegram")
    _bind(user, "max")
    _set_admin(defaults={ASSIGNED: ["email", "telegram"], NEW_IN_QUEUE: [], REPLIED: ["email", "push"]})
    doc = _get(client)

    assert [_on(doc, ASSIGNED, c) for c in ("email", "push", "telegram", "max")] == [True, False, True, False]
    assert [_on(doc, NEW_IN_QUEUE, c) for c in ("email", "push", "telegram", "max")] == [False] * 4
    assert [_on(doc, REPLIED, c) for c in ("email", "push", "telegram", "max")] == [True, True, False, False]
    assert [_on(doc, FAILED, c) for c in ("email", "push", "telegram", "max")] == [True] * 4
    assert _settings_row(user) is None


def test_after_first_save_later_admin_defaults_change_does_not_touch_own_cells():
    """FR-322: после первого сохранения таблицы сотрудником действуют его значения: когда администратор потом
    меняет значения по умолчанию, галочки сотрудника остаются прежними, а у сотрудника, который не сохранял, —
    меняются."""
    user, client = _member()
    other, other_client = _member()
    _set_admin(defaults={code: ["email", "push"] for code in SD_KINDS})
    doc = _saved(client, _form_data(_get(client), off=[f"{ASSIGNED}:email"]))
    assert not _on(doc, ASSIGNED, "email") and _on(doc, ASSIGNED, "push")

    _set_admin(defaults={code: [] for code in SD_KINDS})
    doc = _get(client)
    assert not _on(doc, ASSIGNED, "email") and _on(doc, ASSIGNED, "push")
    for code in (NEW_IN_QUEUE, REPLIED, FAILED):
        assert _on(doc, code, "email") and _on(doc, code, "push"), f"{code}: значения сотрудника сдвинулись"

    doc = _get(other_client)
    for code in SD_KINDS:
        assert not _on(doc, code, "email") and not _on(doc, code, "push"), f"{code}: у не менявшего — новые значения"


def test_save_with_changed_cell_writes_matrix():
    """FR-321, FR-322: если сотрудник изменил хотя бы одну ячейку, в `matrix` записывается снимок всех строк
    таблицы (изменённые — как выбрал, остальные — действующие значения администратора) в порядке каталога, без
    `portal` и без видов `mandatory`; журнал `notify.user_settings_changed` — одна запись."""
    user, client = _member()
    _set_admin(defaults={ASSIGNED: ["email"]})
    before = _audit_count(user)
    _saved(client, _form_data(_get(client), off=[f"{REPLIED}:push"]))

    row = _settings_row(user)
    assert row is not None
    assert row.matrix == {NEW_IN_QUEUE: EXTERNAL, ASSIGNED: ["email"], REPLIED: ["email", "telegram", "max"],
                          FAILED: EXTERNAL, RUBRIC_KIND: ["email"],  # умолчание вида ("portal", "email") без `portal`
                          LISTS_KIND: ["email"]}  # то же умолчание у вида среза 006 (CONTRACT-006, раздел 7.1)
    assert _audit_count(user) == before + 1, "ждали одну запись журнала на сохранение"


def test_save_of_quiet_hours_only_does_not_write_matrix():
    """FR-322, FR-323: сохранение одних тихих часов (без `table`) и сохранение формы с неизменёнными ячейками
    строку настроек с режимом создаёт, но `matrix` не записывают: значения администратора не замораживаются,
    его последующее изменение по-прежнему действует."""
    user, client = _member()
    _set_admin(defaults={ASSIGNED: ["email", "push"]})

    # доп. 21 (д): `calendar` при прежнем `calendar` (строки настроек нет) изменением не считается
    fresh, fresh_client = _member()
    _saved(fresh_client, {"quiet_mode": "calendar"})
    assert _settings_row(fresh) is None, "неизменный режим создал строку настроек"
    assert _audit_count(fresh) == 0, "неизменный режим записал событие журнала"

    doc = _saved(client, {"quiet_mode": "none"})
    row = _settings_row(user)
    assert row is not None and row.quiet_mode == "none"
    assert row.matrix == {}, "сохранение одних тихих часов записало matrix"

    doc = _saved(client, _form_data(doc, quiet_mode="calendar"))
    row = _settings_row(user)
    assert row.quiet_mode == "calendar" and row.matrix == {}, "форма без изменённых ячеек записала matrix"

    _set_admin(defaults={ASSIGNED: ["email"]})
    doc = _get(client)
    assert _on(doc, ASSIGNED, "email") and not _on(doc, ASSIGNED, "push"), "новые значения администратора не действуют"

    # решение D6: без `table` ячейки не трогаются — и когда `matrix` уже записана
    doc = _saved(client, _form_data(doc, off=[f"{REPLIED}:email"]))
    written = _settings_row(user).matrix
    assert REPLIED in written and "email" not in written[REPLIED], "ячейка не сохранилась"
    _saved(client, {"quiet_mode": "none"})
    row = _settings_row(user)
    assert row.quiet_mode == "none" and row.matrix == written, "сохранение без `table` изменило matrix"


def test_table_and_quiet_hours_saved_with_one_post():
    """FR-321, FR-323: таблица и тихие часы сохраняются одним POST: ячейка снята, режим «Свои часы», дни
    понедельник-пятница, 09:00-18:00; на странице отмечены режим, дни и значения полей времени в формате ЧЧ:ММ."""
    user, client = _member()
    doc = _get(client)
    data = _form_data(doc, off=[f"{ASSIGNED}:push"], quiet_mode="own", own_days=["0", "1", "2", "3", "4"],
                      own_start="09:00", own_end="18:00")
    doc = _saved(client, data)

    row = _settings_row(user)
    assert ASSIGNED in row.matrix and "push" not in row.matrix[ASSIGNED]
    assert row.quiet_mode == "own" and row.own_days == [0, 1, 2, 3, 4]
    assert row.own_start == datetime.time(9, 0) and row.own_end == datetime.time(18, 0)

    radios = {el.attrs["value"]: el for el in find(doc, "input", {"type": "radio", "name": "quiet_mode"})}
    assert set(radios) == {"calendar", "own", "none"}
    assert "checked" in radios["own"].attrs and "checked" not in radios["calendar"].attrs
    days = {el.attrs["value"]: el for el in find(doc, "input", {"type": "checkbox", "name": "own_days"})}
    assert set(days) == {str(n) for n in range(7)}
    assert [n for n in sorted(days) if "checked" in days[n].attrs] == ["0", "1", "2", "3", "4"]
    assert one(doc, "input", {"type": "time", "name": "own_start"}).attrs.get("value") == "09:00"
    assert one(doc, "input", {"type": "time", "name": "own_end"}).attrs.get("value") == "18:00"
    assert not _on(doc, ASSIGNED, "push")


def test_quiet_mode_calendar_own_hours_and_none_are_saved():
    """FR-323: каждый из трёх режимов сохраняется и показывается выбранным; «Свои часы» хранят дни и время;
    переключение на «По рабочему календарю» и «Без тихих часов» (без `own_*` в теле) прежние дни и время не
    трогает."""
    user, client = _member()

    def selected(doc):
        return [el.attrs["value"] for el in find(doc, "input", {"type": "radio", "name": "quiet_mode"})
                if "checked" in el.attrs]

    assert selected(_get(client)) == ["calendar"], "у сотрудника без строки настроек выбран не календарь"
    doc = _saved(client, {"quiet_mode": "none"})
    assert _settings_row(user).quiet_mode == "none" and selected(doc) == ["none"]

    doc = _saved(client, {"quiet_mode": "own", "own_days": ["5", "6"], "own_start": "10:00", "own_end": "14:00"})
    row = _settings_row(user)
    assert row.quiet_mode == "own" and row.own_days == [5, 6]
    assert row.own_start == datetime.time(10, 0) and row.own_end == datetime.time(14, 0)
    assert selected(doc) == ["own"]

    for mode in ("calendar", "none"):
        doc = _saved(client, {"quiet_mode": mode})
        row = _settings_row(user)
        assert row.quiet_mode == mode and selected(doc) == [mode]
        assert row.own_days == [5, 6] and row.own_start == datetime.time(10, 0) and row.own_end == datetime.time(14, 0)


# --- проверка ввода тихих часов (FR-323) ---------------------------------------------------------------------

def test_own_hours_with_start_equal_to_end_rejected_with_message():
    """FR-323: «с» равно «до» — отказ `own_same_time`: ответ 200 той же страницы, у поля «до»
    `[data-error=own_end][data-code=own_same_time]` с текстом, введённые значения остались в форме, настройки
    не сохранены."""
    user, client = _member()
    data = {"table": "1", "cell": [f"{ASSIGNED}:email"], "quiet_mode": "own", "own_days": ["0", "1"],
            "own_start": "09:00", "own_end": "09:00"}
    doc = doc_of(_refused(client, data))
    _error(doc, "own_end", "own_same_time")
    assert one(doc, "input", {"type": "time", "name": "own_start"}).attrs.get("value") == "09:00"
    assert one(doc, "input", {"type": "time", "name": "own_end"}).attrs.get("value") == "09:00"
    days = [el.attrs["value"] for el in find(doc, "input", {"type": "checkbox", "name": "own_days"})
            if "checked" in el.attrs]
    assert days == ["0", "1"], "отмеченные дни не остались в форме"
    assert _settings_row(user) is None


def test_own_hours_without_any_day_rejected_with_message():
    """FR-323: «Свои часы» без отмеченных дней — отказ `own_no_days`: 200, `[data-error=own_days]
    [data-code=own_no_days]` с понятным текстом, настройки не сохранены."""
    user, client = _member()
    data = {"quiet_mode": "own", "own_start": "09:00", "own_end": "18:00"}
    doc = doc_of(_refused(client, data))
    _error(doc, "own_days", "own_no_days")
    assert _settings_row(user) is None


def test_own_hours_20_to_08_across_midnight_accepted():
    """FR-323: «с» позже «до» допустимо (20:00-08:00 через полночь): сохранение проходит, значения записаны;
    интервал относится ко дню начала — понедельник 22:00 и вторник 07:59 рабочие, вторник 08:00 тихое."""
    user, client = _member()
    _saved(client, {"quiet_mode": "own", "own_days": ["0", "1", "2", "3", "4"], "own_start": "20:00",
                    "own_end": "08:00"})
    row = _settings_row(user)
    assert row.quiet_mode == "own" and row.own_days == [0, 1, 2, 3, 4]
    assert row.own_start == datetime.time(20, 0) and row.own_end == datetime.time(8, 0)

    from zoneinfo import ZoneInfo
    from apps.notify.services import quiet
    moscow = ZoneInfo("Europe/Moscow")
    assert quiet.is_working(row, datetime.datetime(2026, 10, 12, 22, 0, tzinfo=moscow))      # понедельник
    assert quiet.is_working(row, datetime.datetime(2026, 10, 13, 7, 59, tzinfo=moscow))      # вторник утром
    assert not quiet.is_working(row, datetime.datetime(2026, 10, 13, 8, 0, tzinfo=moscow))


def test_rejected_input_on_htmx_request_returns_200_with_error_fragment():
    """FR-323: отказ на запрос HTMX — 200 и фрагмент без `<html>` с корнем `#notify-prefs-root`, внутри него
    `[data-error][data-code]` у поля; исправленный ввод тем же способом проходит: 200 с пустым телом и
    `HX-Redirect: /me/notifications/`."""
    user, client = _member()
    data = {"quiet_mode": "own", "own_days": ["2"], "own_start": "08:00", "own_end": "08:00"}
    response = _refused(client, data, **HX)
    body = response.content.decode("utf-8")
    assert "<html" not in body.lower(), "на запрос HTMX пришла полная страница"
    doc = _Doc(body)
    root = one(doc, None, {"id": "notify-prefs-root"})
    error = one(doc, None, {"data-error": "own_end", "data-code": "own_same_time"})
    assert inside(error, root) and error.text
    assert _settings_row(user) is None

    data["own_end"] = "17:00"
    response = client.post(URL, data, **HX)
    assert response.status_code == 200 and response.content == b"", "успех на запрос HTMX — 200 с пустым телом"
    assert response["HX-Redirect"] == URL
    assert _settings_row(user).quiet_mode == "own"


def test_rejected_save_keeps_previous_settings():
    """FR-323: отказ откатывает всё целиком — и ячейки таблицы, посланные в том же POST, и тихие часы:
    `matrix`, режим, дни и время прежние, записи журнала нет; тихие часы с неизвестным режимом — отказ
    `bad_quiet_mode`."""
    user, client = _member()
    doc = _saved(client, _form_data(_get(client), off=[f"{ASSIGNED}:email"], quiet_mode="own",
                                    own_days=["0", "1", "2"], own_start="09:00", own_end="18:00"))
    row = _settings_row(user)
    saved = (row.pk, row.matrix, row.quiet_mode, row.own_days, row.own_start, row.own_end)
    events = _audit_count(user)

    bad_same = _form_data(doc, off=[f"{REPLIED}:email"], quiet_mode="own", own_days=["3"], own_start="10:00",
                          own_end="10:00")
    assert _error(doc_of(_refused(client, bad_same)), "own_end", "own_same_time")
    bad_mode = _form_data(doc, off=[f"{REPLIED}:email"], quiet_mode="weekends")
    assert _error(doc_of(_refused(client, bad_mode)), "quiet_mode", "bad_quiet_mode")

    row = _settings_row(user)
    assert (row.pk, row.matrix, row.quiet_mode, row.own_days, row.own_start, row.own_end) == saved
    assert _audit_count(user) == events, "отказ записал событие журнала"
    doc = _get(client)
    assert _on(doc, REPLIED, "email") and not _on(doc, ASSIGNED, "email")


# --- разметка и чужие настройки (FR-321, FR-342) -----------------------------------------------------------------

def test_page_markup_has_card_layout_without_wide_table_at_narrow_width():
    """FR-321: таблица лежит в контейнере `[data-narrow=cards]` (на узкой ширине складывается в карточки по виду,
    без горизонтальной прокрутки); у страницы `<html lang=ru>` и `<meta name=viewport>`; корень страницы
    `[data-notify-prefs]#notify-prefs-root` с формой `form[data-form=notify-prefs]`."""
    user, client = _member()
    doc = _get(client)
    cards = one(doc, None, {"data-narrow": "cards"})
    assert find(doc, "table", {"data-notify-table": True}, within=cards), "таблица вне контейнера data-narrow=cards"
    assert one(doc, "html", {"lang": "ru"})
    assert one(doc, "meta", {"name": "viewport"}).attrs.get("content")
    root = one(doc, None, {"data-notify-prefs": True, "id": "notify-prefs-root"})
    form = one(doc, "form", {"data-form": "notify-prefs"}, within=root)
    assert find(doc, "table", {"data-notify-table": True}, within=form)
    assert one(doc, "input", {"type": "hidden", "name": "table", "value": "1"}, within=form)
    assert one(doc, "button", {"type": "submit", "data-action": "save-prefs"}, within=form)


def test_post_changes_only_own_settings_ignoring_foreign_user_id():
    """FR-342: форма меняет только настройки вошедшего: поля `user` и `user_id` с номером другого сотрудника
    игнорируются — его строка настроек не меняется, а у вошедшего сохранены и ячейки, и тихие часы."""
    user, client = _member()
    victim = support.make_employee()
    UserNotifySettings = model("notify.UserNotifySettings")
    UserNotifySettings.objects.create(user=victim, matrix={ASSIGNED: ["email"]}, quiet_mode="none")

    data = _form_data(_get(client), off=[f"{ASSIGNED}:email"], quiet_mode="own", own_days=["1"], own_start="08:00",
                      own_end="12:00", user=str(victim.pk), user_id=str(victim.pk))
    _saved(client, data)

    foreign = UserNotifySettings.objects.get(user=victim)
    assert foreign.matrix == {ASSIGNED: ["email"]} and foreign.quiet_mode == "none"
    assert foreign.own_days == [] and foreign.own_start is None and foreign.own_end is None
    own = UserNotifySettings.objects.get(user=user)
    assert own.quiet_mode == "own" and own.own_days == [1] and own.own_start == datetime.time(8, 0)
    assert ASSIGNED in own.matrix and "email" not in own.matrix[ASSIGNED]
    assert _audit_count(victim) == 0
