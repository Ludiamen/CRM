"""T-4151: сквозная приёмка среза и критерии успеха с замером времени и шириной 360 px — сценарий «Критерии успеха»
(NFR-301, NFR-302, NFR-303, NFR-307, NFR-308, NFR-311, FR-301, FR-302, FR-304, FR-305, FR-307, FR-308, FR-310, FR-314,
FR-316, FR-317, FR-327, FR-329, FR-330, FR-331, FR-333, FR-340, FR-344, FR-345).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-004.md):
- каждый тест заводит свою очередь, своих сотрудников и свои заявки (имена уникальны); очередь по умолчанию на время
  теста меняется на свою и возвращается в `finally`; каналы администратора — `helpers_notify.channels_on` (возврат
  в `finally`);
- тихие часы: у каждого, чьё письмо, сообщение или push проверяется, режим задан явно («Без тихих часов» или «Свои
  часы» вокруг текущего московского времени): стенд не подменяет часы;
- срок письма — `helpers_notify.tick(shift=PAST_ANY_TERM)` (121 минута больше верхней границы срока письма, § 6.5);
  сдвиг идёт по всему стенду, письма ищутся поиском Mailpit по адресу получателя и шаблону;
- замеры — `time.monotonic()` от действия до видимого результата; ожидание берётся чуть больше нормы, проверка — по
  замеру (2 с — NFR-301, 60 с — NFR-302, NFR-303);
- Web Push: тест с подпиской устройства или ожиданием push — с меткой `webpush_only` и фикстурой `webpush_context`
  (дополнение 23). Пока вкладка сотрудника открыта, push пропускается (FR-331, `tab_open`), поэтому перед ожиданием
  push все вкладки сотрудника с колокольчиком закрыты, а профиль уведён на `/sw.js` (страница без колокольчика);
- «нет письма / сообщения / push» проверяется после положительного контроля того же пути и повторно в конце.
"""
import contextlib
import json
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers, helpers_notify, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_servicedesk import build_mail

NEW_IN_QUEUE = "servicedesk.new_in_queue"
ASSIGNED = "servicedesk.assigned"
SD_ALL = "servicedesk.all"
KINDS = (  # § 3.2: код, название; модуль у всех четырёх — «Сервис-деск»
    (NEW_IN_QUEUE, "Новая заявка в моей очереди"),
    (ASSIGNED, "Мне назначили заявку"),
    ("servicedesk.requester_replied", "Заявитель ответил"),
    ("servicedesk.reply_failed", "Ответ заявителю не ушёл"),
)
MODULE = "Сервис-деск"
EXPECTED_CATALOG = {  # § 3.2: код → (название, модуль, mandatory, внешний текст)
    NEW_IN_QUEUE: ("Новая заявка в моей очереди", MODULE, False, "Новая заявка в вашей очереди"),
    ASSIGNED: ("Мне назначили заявку", MODULE, False, "Вам назначена заявка"),
    "servicedesk.requester_replied": ("Заявитель ответил", MODULE, False, "Заявитель ответил по вашей заявке"),
    "servicedesk.reply_failed": ("Ответ заявителю не ушёл", MODULE, False, "Ответ заявителю не ушёл"),
    "core.new_device": ("Вход с нового устройства", "Ядро", True, ""),
    "core.password_changed": ("Пароль изменён", "Ядро", True, ""),
    "core.second_factor_reset": ("Второй фактор сброшен", "Ядро", True, ""),
    "notify.channel_unbound": ("Канал отвязан", "Уведомления", True, ""),
}
EXTERNAL_NEW = "Новая заявка в вашей очереди"  # § 15.2
EXTERNAL_ASSIGNED = "Вам назначена заявка"  # § 15.2
FIXED_SECURITY = "Безопасность: всегда"  # § 15.5
FIXED_UNBOUND = "Канал отвязан: всегда, только на портале"  # § 15.5
SAVED = "Настройки уведомлений сохранены."  # § 15.4
PAST_ANY_TERM = 121  # минут: больше верхней границы срока письма (120 минут, § 6.5)
MOSCOW = ZoneInfo("Europe/Moscow")
MSK = timezone(timedelta(hours=3), "MSK")  # Москва без перехода на летнее время (NFR-307)
ALL_DAYS = range(7)
BELL_WAIT_MS = 15_000  # ожидание числа там, где срок 2 с (NFR-301) не проверяется
LIMIT_BELL = 2.0  # NFR-301, секунды
LIMIT_EXTERNAL = 60.0  # NFR-302, NFR-303, секунды
WAIT_EXTERNAL = 90.0  # предел ожидания внешних каналов: запас над нормой 60 с
NEW_DEVICE_RE = re.compile(r"^Вход с нового устройства \((?P<browser>.+), (?P<at>\d{2}\.\d{2}\.\d{4} \d{2}:\d{2})\)$")
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
LANGUAGE_EXCEPTIONS = ("Web Push", "Push", "push", "Telegram", "MAX")  # § 14, решение D2


# --- Общие помощники файла ----------------------------------------------------------------------------

def _word() -> str:
    """Уникальное слово темы: буква и шесть шестнадцатеричных знаков (не из одних цифр: поиск списка принял бы его за
    номер заявки)."""
    return f"t{secrets.token_hex(3)}"


def _tag() -> str:
    return "Крит" + secrets.token_hex(3)


def _chat_id() -> int:
    """Уникальный номер чата `fakebots`: служба одна на круг, сообщения выбираются по своему чату."""
    return secrets.randbelow(900_000_000) + 100_000_000


def _norm(text: str) -> str:
    return " ".join(text.split())


def _now() -> datetime:
    return datetime.now(MSK)


def _staff(employee, tag: str, index: int):
    return employee(full_name=f"{tag}{index} Петр Петрович")


def _queue(page, prefix: str = "Поддержка", *, kind: str = "department", parent_id=None) -> tuple:
    """Новый узел `org`, отмеченный очередью: `(номер, название)`."""
    name = helpers_org.unique_name(prefix)
    unit_id = helpers_org.create_unit(page, name, kind=kind, parent_id=parent_id)
    helpers_sd.mark_queue(page, unit_id)
    return unit_id, name


def _members(page, queue_id, accounts, tag: str) -> None:
    """Прямые участники узла-очереди (у отдела — режим «параллельно»)."""
    page.goto(f"/structure/{queue_id}/")
    mode = "concurrent" if page.locator("#unit-card select[name=mode]").count() else None
    note = helpers_org.add_members(page, queue_id, [a.id for a in accounts], q=tag, mode=mode)
    assert "уже участник" not in note, note
    helpers_org.open_structure(page, queue_id)
    for account in accounts:
        expect(helpers_org.member_row(page, account.id)).to_have_count(1)


@contextlib.contextmanager
def _default_queue(page, old_id, queue_id):
    """Очередь по умолчанию на время блока — своя (письмо заявителя попадает в неё); прежняя — в `finally`."""
    helpers_sd.set_default_queue(page, queue_id)
    try:
        yield
    finally:
        helpers_sd.set_default_queue(page, old_id)


def _new_mail(subject: str | None = None, requester: str | None = None) -> tuple:
    """Письмо заявителя в ящик заявок и сразу разбор: заявка в очереди по умолчанию без ответственного. Возвращает
    `(слово, тема, адрес заявителя)`; слово стоит в теме (по нему находят строки и заявку)."""
    word = _word()
    subject = (subject or "Не работает принтер {w}").replace("{w}", word)
    requester = requester or helpers_sd.requester_email()
    helpers_sd.deliver(build_mail(from_addr=requester, to=[MAILBOX], subject=subject, text=f"Нужна помощь {word}",
                                  message_id=f"<{secrets.token_hex(8)}@client.test>"))
    return word, subject, requester


def _tick() -> None:
    """Срок письма прошёл: ожидающие доставки стенда сдвинуты, обход выполнен (хотя бы одна доставка сдвинута)."""
    result = helpers_notify.tick(shift=PAST_ANY_TERM)
    assert result["shifted"] >= 1, result


def _due_now(email: str) -> None:
    """`helpers.stand_shell`: доставки по почте ожидающих уведомлений этого сотрудника получают срок «сейчас» и пустое
    `enqueued_at` (то, что делает `e2e_notify_tick --shift`, § 8.2, но только для его строки и без обхода: обход
    выполняет воркер по расписанию). Не нашлась ни одна — `AssertionError`."""
    out = helpers.stand_shell(
        "from django.apps import apps as a; from django.utils import timezone; D = a.get_model('notify', 'Delivery'); "
        f"print('due', D.objects.filter(notification__user__email__iexact={email!r}, channel='email', state='waiting')"
        ".update(due_at=timezone.now(), enqueued_at=None))")
    found = re.search(r"due (\d+)", out.splitlines()[-1] if out else "")
    assert found and int(found.group(1)) >= 1, f"нет ожидающей доставки по почте у {email}: {out!r}"


def _wait_plus(page, base: int, step: int = 1) -> int:
    helpers_notify.wait_bell_count(page, base + step, timeout_ms=BELL_WAIT_MS)
    return base + step


def _event(tab, **kwargs) -> tuple:
    """Новая заявка письмом при открытой вкладке: ждёт рост числа колокольчика на 1; `(слово, тема, заявитель)`."""
    base = helpers_notify.bell_count(tab)
    result = _new_mail(**kwargs)
    _wait_plus(tab, base)
    return result


def _rows(page, word: str):
    """Строки `/notifications/` со словом темы (список только читается)."""
    page.goto("/notifications/")
    expect(page.locator("[data-notify-list]")).to_be_visible()
    return page.locator("ul[data-notifications] li[data-notification]").filter(has_text=word)


def _list(page) -> list:
    """Строки `/notifications/` (первая страница): `id`, `unread`, `text`, `at` (`time[data-at]`), `shown`."""
    page.goto("/notifications/")
    expect(page.locator("[data-notify-list]")).to_be_visible()
    rows = []
    for item in page.locator("ul[data-notifications] li[data-notification]").all():
        stamp = item.locator("time[data-at]")
        rows.append({
            "id": item.get_attribute("data-notification"),
            "unread": item.get_attribute("data-unread"),
            "text": _norm(item.locator('[data-field="text"]').inner_text()),
            "at": stamp.first.get_attribute("data-at") if stamp.count() else "",
            "shown": _norm(stamp.first.inner_text()) if stamp.count() else "",
        })
    return rows


def _cell(page, kind: str, channel: str):
    return page.locator(f'table[data-notify-table] tr[data-notify-kind="{kind}"] td[data-channel="{channel}"] '
                        f'input[type=checkbox][name="cell"][value="{kind}:{channel}"]')


def _hours(start_offset: int, end_offset: int) -> tuple:
    """Часы «ЧЧ:ММ» (Москва) на `start_offset` и `end_offset` часов от текущего момента."""
    now = datetime.now(MOSCOW)
    return ((now + timedelta(hours=start_offset)).strftime("%H:%M"),
            (now + timedelta(hours=end_offset)).strftime("%H:%M"))


def _save_prefs(page, cells=None, quiet: str | None = "none", start=None, end=None) -> None:
    """«Мои уведомления»: ячейки `{(код вида, канал): состояние}` и режим тихих часов (`none`, `own` — все дни и часы
    `start`–`end`); ждёт «Настройки уведомлений сохранены.» (§ 13.2, § 14.3). Ячейки telegram/max и push доступны
    только после привязки или подписки."""
    page.goto("/me/notifications/")
    form = page.locator('form[data-form="notify-prefs"]')
    expect(form).to_be_visible()
    for (kind, channel), state in (cells or {}).items():
        expect(_cell(page, kind, channel)).to_have_count(1)
        _cell(page, kind, channel).set_checked(state)
    if quiet is not None:
        form.locator(f'fieldset[data-quiet] input[type=radio][name="quiet_mode"][value="{quiet}"]').check()
    if quiet == "own":
        for day in ALL_DAYS:
            form.locator(f'fieldset[data-quiet] input[type=checkbox][name="own_days"][value="{day}"]').set_checked(True)
        form.locator('fieldset[data-quiet] input[type=time][name="own_start"]').fill(start)
        form.locator('fieldset[data-quiet] input[type=time][name="own_end"]').fill(end)
    with page.expect_navigation():
        form.locator('button[type=submit][data-action="save-prefs"]').click()
    page.wait_for_load_state()
    assert not helpers.alert_text(page), f"настройки не сохранены: {helpers.alert_text(page)}"
    expect(page.locator("[role=status]").filter(has_text=SAVED).first).to_be_visible()


def _mail_prefs(page) -> None:
    """Ячейка «Почта» вида «Новая заявка в моей очереди» включена, тихих часов нет."""
    _save_prefs(page, {(NEW_IN_QUEUE, "email"): True}, quiet="none")


def _sent_texts(bots, channel: str, chat, text: str) -> list:
    """Сообщения бота в свой чат, в тексте которых есть `text` (ответы бота при привязке сюда не входят)."""
    return [m for m in helpers_notify.sent_to(bots, channel, chat) if text in (m.get("text") or "")]


def _mails(mailpit, email: str, template: str = helpers_notify.TEMPLATE_ITEM) -> list:
    return helpers_notify.find_mails(mailpit, email, template)


def _candidates_for(card, query: str) -> None:
    """Запрос в поле `q` формы назначения; ждёт подсказки (CONTRACT-003, доп. 42 (б))."""
    box = card.locator('form[data-form="ticket-assign"] input[name=q]')
    with card.page.expect_response(lambda r: "/assignees/" in r.url) as info:
        box.fill(query)
    assert info.value.ok, f"подсказки назначения: ответ {info.value.status}"
    expect(card.locator('form[data-form="ticket-assign"] [data-candidates] label[data-candidate]').first).to_be_visible()


def _assign_ready(page, number: int, user):
    """Карточка заявки с выбранным ответственным; кнопка ещё не нажата (для замера)."""
    card = helpers_sd.open_ticket(page, number)
    _candidates_for(card, user.full_name.split()[0])
    label = card.locator(f'label[data-candidate][data-user-id="{user.id}"]')
    expect(label).to_have_count(1)
    label.click()
    expect(label.locator("input[type=radio][name=assignee]")).to_be_checked()
    return card


def _assign_click(card) -> None:
    card.locator('form[data-form="ticket-assign"] button[type=submit]').first.click()


def _subscribe(webpush_context, account, *, spy: bool = False) -> tuple:
    """Постоянный профиль со своей подпиской на Web Push: сессия сотрудника перенесена, разрешение выдано, устройство
    подписано. Вкладка сотрудника в обычном контексте (`account.page`) закрыта: открытая вкладка заставила бы пропустить
    push (FR-331). Возвращает `(контекст, вкладка)`; вкладка открыта на `/me/notifications/` (колокольчик, присутствие)."""
    context = webpush_context()
    tab = helpers_notify.open_tab(context, account, url="/me/notifications/", grant=True, spy=spy)
    account.page.close()
    helpers_notify.enable_push_on_device(tab)
    return context, tab


def _is_online(user_id) -> bool:
    """`helpers.stand_shell`: `live.is_online(<номер>)` (§ 6.8); печатается только `True` или `False`."""
    out = helpers.stand_shell(f"from apps.notify.services import live; print('online', live.is_online({int(user_id)}))")
    found = re.search(r"online (True|False)", out.splitlines()[-1] if out else "")
    assert found, "stand_shell не вернула признак присутствия"
    return found.group(1) == "True"


def _away(tab, account) -> None:
    """Уводит вкладку профиля на `/sw.js`: страница без колокольчика и соединения. Ждёт, пока присутствие снято
    (`live.is_online` ложно; `mark_offline` при отключении, срок записи 60 с, § 6.8 — предел 75 с): иначе доставка Web
    Push получила бы `tab_open` и пропустилась навсегда."""
    tab.goto(helpers_notify.SW_PATH)
    end = time.monotonic() + 75
    while _is_online(account.id):
        if time.monotonic() >= end:
            raise AssertionError(f"присутствие сотрудника {account.id} не снято за 75 с после ухода вкладки")
        tab.wait_for_timeout(1_000)


def _dump(item) -> str:
    return json.dumps(item, ensure_ascii=False)


def _block(page, user_id, reason: str) -> None:
    page.goto(f"/staff/{user_id}/")
    helpers.open_security_tab(page)
    form = page.locator('form[action$="/block/"]')
    form.locator("[name=reason]").fill(reason)
    helpers.submit(form)
    page.goto("/staff/?state=blocked")
    expect(page.locator(f'tr[data-user-id="{user_id}"][data-state="blocked"]')).to_have_count(1)


def _unblock(page, user_id) -> None:
    page.goto(f"/staff/{user_id}/")
    helpers.open_security_tab(page)
    form = page.locator('form[action$="/unblock/"]')
    if form.count():
        helpers.submit(form)
        page.goto("/staff/?state=blocked")
        expect(page.locator(f'tr[data-user-id="{user_id}"][data-state="blocked"]')).to_have_count(0)


def _dismiss(page, user_id) -> None:
    page.goto(f"/staff/{user_id}/")
    card = page.locator(f'[data-card][data-user-id="{user_id}"]')
    card.locator('[data-action="dismiss"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(card.locator("[data-dismissed-badge]")).to_be_visible()


def _db_counts(email: str) -> dict:
    """`helpers.stand_shell`: подписки Web Push, привязки и неиспользованные коды привязки сотрудника (строки базы);
    использованные коды уходят обходом хранения позже, увольнение их не удаляет (дополнение 28 (б))."""
    code = (f"from django.apps import apps as a; m = lambda n: a.get_model('notify', n); f = {{'user__email__iexact': "
            f"{email!r}}}; print('counts', m('PushSubscription').objects.filter(**f).count(), "
            f"m('ChatBinding').objects.filter(**f).count(), m('BindCode').objects.filter(used_at__isnull=True, **f).count())")
    out = helpers.stand_shell(code).splitlines()
    found = re.search(r"counts (\d+) (\d+) (\d+)", out[-1] if out else "")
    assert found, "stand_shell не вернула строку counts"
    push, bindings, unused = (int(n) for n in found.groups())
    return {"push": push, "bindings": bindings, "unused_codes": unused}


def _channel_error_stamp(page, channel: str) -> str:
    """Время (`time[data-at]`) ошибки канала на странице администратора; пустая строка — ошибки нет (или времени нет)."""
    page.goto("/settings/notifications/")
    stamp = page.locator(f'section[data-channel-block="{channel}"] [data-channel-error] time[data-at]')
    return stamp.first.get_attribute("data-at") if stamp.count() else ""


def _wait_channel_error(page, channel: str, *, timeout: float = 60.0, before: str = "") -> None:
    """Ждёт на странице администратора `[data-channel-error][data-code="unavailable"]` блока канала (§ 14.4, 15.5):
    страница перечитывается, пока ошибки нет; `before` — время прежней ошибки (`_channel_error_stamp`), новая должна
    отличаться от неё."""
    end = time.monotonic() + timeout
    while True:
        page.goto("/settings/notifications/")
        try:
            block = page.locator(f'section[data-channel-block="{channel}"] [data-channel-error][data-code="unavailable"]')
            expect(block).to_be_visible(timeout=3_000)
            stamp = block.locator("time[data-at]")
            if before and stamp.count() and stamp.first.get_attribute("data-at") == before:
                raise AssertionError("прежняя ошибка")
            return
        except AssertionError:
            if time.monotonic() >= end:
                raise AssertionError(f"ошибка канала {channel} не показана администратору за {timeout:.0f} с") from None


def _make_role(page, name: str, codes) -> str:
    page.goto("/roles/new/")
    form = page.locator('form[action="/roles/new/"]')
    form.locator("[name=name]").fill(name)
    for code in codes:
        form.locator(f'input[name=permissions][value="{code}"]').check()
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    return helpers_org.role_id(page, name)


def _grant_role(page, user_id, role_id) -> None:
    page.goto(f"/staff/{user_id}/")
    form = page.locator('form[action$="/roles/"]')
    form.locator(f'input[name=roles][value="{role_id}"]').check()
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()


# --- Тесты --------------------------------------------------------------------------------------------------

def test_e12_assigned_notification_reaches_open_tab_within_two_seconds_timed(admin_page, employee, new_context):
    """Критерий «Мне назначили» — во вкладку не позже 2 с (NFR-301, FR-310): у ответственного открыта вкладка, администратор
    нажимает «Назначить» — число колокольчика растёт на 1 и вкладка показывает системное уведомление (обёртка `Notification`,
    разрешение выдано) не позже чем через 2 с (замер от нажатия), в списке строка «Вам назначена заявка #N: Тема»."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    assignee, other = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, _queue_name = _queue(page)
    _members(page, queue_id, [assignee, other], tag)
    with _default_queue(page, old_id, queue_id):
        word, subject, _requester = _new_mail()
        number = helpers_sd.ticket_number_by_subject(page, word)
        card = _assign_ready(page, number, assignee)
        # системное уведомление показывается только вне тихих часов при включённой ячейке push (§ 6.7, поле `show`);
        # ячейка push вида включена по умолчанию, а без подписки устройства недоступна и при сохранении не меняется (B1)
        _save_prefs(assignee.page, quiet="none")
        tab = helpers_notify.open_watcher(new_context, assignee, spy=True, grant=True)
        other_tab = helpers_notify.open_watcher(new_context, other)
        base, other_base = helpers_notify.bell_count(tab), helpers_notify.bell_count(other_tab)
        # когда: нажимается «Назначить»; замер до видимого результата — числа на колокольчике
        started = time.monotonic()
        _assign_click(card)
        expect(tab.locator("#notify-count")).to_have_attribute("data-count", str(base + 1), timeout=4_000)
        shown = helpers_notify.wait_notifications(tab, count=1, timeout_ms=4_000)
        elapsed = time.monotonic() - started
        assert elapsed <= LIMIT_BELL, f"число и системное уведомление за {elapsed:.2f} с, норма {LIMIT_BELL:.0f} с (NFR-301)"
        expected = f"Вам назначена заявка #{number}: {subject}"
        assert [n["title"] for n in shown] == [expected], shown
        # в списке — строка о назначении; у другого участника очереди числа не изменились (страница читает из базы)
        rows = _rows(tab, f"#{number}").filter(has_text="Вам назначена заявка")
        expect(rows).to_have_count(1)
        assert _norm(rows.locator('[data-field="text"]').inner_text()) == expected
        other_tab.goto("/")
        assert helpers_notify.bell_count(other_tab) == other_base


@helpers_notify.webpush_only
def test_e12_assigned_notification_reaches_bot_service_and_real_web_push_within_one_minute_timed(
        admin_page, employee, webpush_context):
    """Критерий «Мне назначили» — Telegram, MAX и Web Push не позже минуты (NFR-302, FR-310): учебная служба ботов и
    настоящий push-сервис браузера; замер от нажатия «Назначить» до каждого сообщения."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    assignee = _staff(employee, tag, 1)
    queue_id, _queue_name = _queue(page)
    _members(page, queue_id, [assignee], tag)
    bots = helpers_notify.fakebots()
    chat_tg, chat_max = _chat_id(), _chat_id()
    with helpers_notify.channels_on(page, "webpush", "telegram", "max"):
        # дано: устройство подписано, оба бота привязаны, у «Мне назначили» включены push, Telegram и MAX; у «Новой
        # заявки» внешние каналы выключены (push раньше нужного не приходит), тихих часов нет
        context, tab = _subscribe(webpush_context, assignee)
        helpers_notify.bind_channel(tab, bots, "telegram", chat_tg)
        helpers_notify.bind_channel(tab, bots, "max", chat_max)
        cells = {(ASSIGNED, c): True for c in ("push", "telegram", "max")}
        cells.update({(NEW_IN_QUEUE, c): False for c in ("push", "telegram", "max")})
        _save_prefs(tab, cells, quiet="none")
        _away(tab, assignee)
        with _default_queue(page, old_id, queue_id):
            word, _subject, _requester = _new_mail()
            number = helpers_sd.ticket_number_by_subject(page, word)
            card = _assign_ready(page, number, assignee)
            # когда: нажимается «Назначить»
            started = time.monotonic()
            _assign_click(card)
            telegram = helpers_notify.wait_sent(bots, "telegram", chat_id=chat_tg, text_has=EXTERNAL_ASSIGNED,
                                                timeout=WAIT_EXTERNAL)
            t_telegram = time.monotonic() - started
            maxed = helpers_notify.wait_sent(bots, "max", chat_id=chat_max, text_has=EXTERNAL_ASSIGNED,
                                             timeout=WAIT_EXTERNAL)
            t_max = time.monotonic() - started
            shown = helpers_notify.wait_service_worker_notifications(context, count=1, timeout=WAIT_EXTERNAL)
            t_push = time.monotonic() - started
        for name, spent in (("Telegram", t_telegram), ("MAX", t_max), ("Web Push", t_push)):
            assert spent <= LIMIT_EXTERNAL, f"{name}: {spent:.1f} с, норма {LIMIT_EXTERNAL:.0f} с (NFR-302)"
        # тексты — внешний текст вида (§ 15.2), без номера заявки
        assert [m["text"] for m in telegram] == [EXTERNAL_ASSIGNED]
        assert [m["text"] for m in maxed] == [EXTERNAL_ASSIGNED]
        assert [n["title"] for n in shown] == [EXTERNAL_ASSIGNED], shown
        for item in (telegram[0], maxed[0], shown[0]):
            assert f"#{number}" not in _dump(item)
        # повторно в конце: ровно по одному сообщению (дубль задания не пропущен)
        assert len(_sent_texts(bots, "telegram", chat_tg, EXTERNAL_ASSIGNED)) == 1
        assert len(_sent_texts(bots, "max", chat_max, EXTERNAL_ASSIGNED)) == 1
        assert len(helpers_notify.service_worker_notifications(context)) == 1


def test_e12_email_arrives_in_mailpit_within_one_minute_after_mail_term_timed(
        admin_page, employee, new_context, mailpit):
    """Критерий «письмо не позже минуты после срока письма» (NFR-303, FR-327): срок письма своей доставки прошёл (чтение
    базы `helpers.stand_shell`: `due_at` = сейчас, `enqueued_at` пусто — как делает `--shift`, § 8.2, но только для своей
    строки и без обхода), письмо «Новая заявка в вашей очереди» приходит в Mailpit в течение минуты — обход воркера
    раз в 30 с (plan.md:891, 967) и очередь `mail`; замер от этого момента."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _queue_name = _queue(page)
    _members(page, queue_id, [member], tag)
    _mail_prefs(member.page)
    with _default_queue(page, old_id, queue_id):
        tab = helpers_notify.open_watcher(new_context, member)
        word, _subject, _requester = _event(tab)
        # когда: срок письма проходит (замер начинается после возврата записи; обход выполняет сам воркер)
        _due_now(member.email)
        started = time.monotonic()
        letter = helpers_notify.wait_item_mail(mailpit, member.email, timeout=WAIT_EXTERNAL)
        elapsed = time.monotonic() - started
    assert elapsed <= LIMIT_EXTERNAL, f"письмо пришло за {elapsed:.1f} с, норма {LIMIT_EXTERNAL:.0f} с (NFR-303)"
    assert letter["Subject"] == EXTERNAL_NEW
    assert word not in letter["Subject"]


def test_e12_overnight_gives_at_most_one_digest_mail_and_one_messenger_message_per_employee(
        admin_page, employee, new_context, mailpit):
    """Критерий «за ночь не больше одного письма сводки и одного сообщения» (FR-330): у сотрудника тихие часы, привязаны
    Telegram и MAX; за ночь три события — ни писем по одному, ни сообщений; утром (смена режима на «Без тихих часов»,
    обход) приходит ровно одно письмо сводки и одно сообщение «У вас 3 новых уведомления» — в первый канал по порядку
    (Telegram), в MAX сообщения нет. Контроль: коллега без тихих часов получает письма по одному."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    night, control = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, _queue_name = _queue(page)
    _members(page, queue_id, [night, control], tag)
    bots = helpers_notify.fakebots()
    chat_tg, chat_max = _chat_id(), _chat_id()
    with _default_queue(page, old_id, queue_id), helpers_notify.channels_on(page, "telegram", "max"):
        helpers_notify.bind_channel(night.page, bots, "telegram", chat_tg)
        helpers_notify.bind_channel(night.page, bots, "max", chat_max)
        start, end = _hours(3, 4)  # ночь: «Свои часы» вне текущего времени, все дни
        _save_prefs(night.page, {(NEW_IN_QUEUE, c): True for c in ("email", "telegram", "max")},
                    quiet="own", start=start, end=end)
        _mail_prefs(control.page)
        tab = helpers_notify.open_watcher(new_context, night)
        # когда: за ночь три события
        for _ in range(3):
            _event(tab)
        _tick()
        # контроль: письмо коллеге пришло; ночью у спящего писем и сообщений по одному нет
        helpers_notify.wait_item_mail(mailpit, control.email)
        assert helpers_notify.no_item_mail(mailpit, night.email, wait=8), "письмо по одному в тихие часы"
        assert not _sent_texts(bots, "telegram", chat_tg, EXTERNAL_NEW) and \
            not _sent_texts(bots, "max", chat_max, EXTERNAL_NEW), "сообщение по одному в тихие часы"
        # когда: наступает утро (смена режима пересчитывает срок сводки на «сейчас»), обход ставит сводку
        _save_prefs(night.page, quiet="none")
        helpers_notify.tick()
        # утром: одно письмо сводки и одно сообщение в Telegram
        digest = helpers_notify.wait_digest_mail(mailpit, night.email, timeout=WAIT_EXTERNAL)
        assert digest["Subject"] == "За нерабочее время: 3 уведомления", digest["Subject"]
        found = helpers_notify.wait_sent(bots, "telegram", chat_id=chat_tg, text_has="У вас 3 новых уведомления",
                                         timeout=WAIT_EXTERNAL)
        assert len(found) == 1
        # повторно в конце: ещё один обход ничего не добавил (ровно одно письмо, одно сообщение, в MAX — ни одного)
        helpers_notify.tick()
        assert helpers_notify.no_digest_mail(mailpit, night.email, seen={digest["ID"]}, wait=10)
        assert len(_mails(mailpit, night.email, helpers_notify.TEMPLATE_DIGEST)) == 1
        assert len(_sent_texts(bots, "telegram", chat_tg, "У вас")) == 1
        assert _sent_texts(bots, "max", chat_max, "У вас") == []
        assert _mails(mailpit, night.email) == [], "письмо по одному после сводки"
        assert _sent_texts(bots, "telegram", chat_tg, EXTERNAL_NEW) == []
        assert _sent_texts(bots, "max", chat_max, EXTERNAL_NEW) == []


def test_e12_notification_read_on_portal_before_term_gives_zero_mails(admin_page, employee, new_context, mailpit):
    """Критерий «0 писем по уведомлению, прочитанному на портале до срока» (FR-307, FR-327): один участник прочитал своё
    уведомление кнопкой «Прочитать», другой нет — когда срок проходит, письмо получает только не прочитавший."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    reader, silent = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, _queue_name = _queue(page)
    _members(page, queue_id, [reader, silent], tag)
    for account in (reader, silent):
        _mail_prefs(account.page)
    with _default_queue(page, old_id, queue_id):
        tabs = helpers_notify.open_watchers(new_context, [reader, silent])
        bases = [helpers_notify.bell_count(t) for t in tabs]
        word, _subject, _requester = _new_mail()
        for tab, base in zip(tabs, bases):
            _wait_plus(tab, base)
        # дано: первый прочитал уведомление на портале
        rows = _rows(tabs[0], word)
        expect(rows).to_have_count(1)
        rows.locator('form[data-form="read"] button[data-action="read"]').click()
        expect(rows).to_have_attribute("data-unread", "0")
        helpers_notify.wait_bell_count(tabs[0], bases[0], timeout_ms=BELL_WAIT_MS)
        # когда: срок проходит
        _tick()
        # контроль: не прочитавший получил письмо; прочитавшему письма нет (повторно в конце — после второго обхода)
        helpers_notify.wait_item_mail(mailpit, silent.email)
        assert helpers_notify.no_item_mail(mailpit, reader.email, wait=10), "письмо по прочитанному уведомлению"
        helpers_notify.tick()
        assert helpers_notify.no_item_mail(mailpit, reader.email, wait=8), "письмо по прочитанному уведомлению после второго обхода"
        assert _mails(mailpit, reader.email) == []
        assert len(_mails(mailpit, silent.email)) == 1


@helpers_notify.webpush_only
def test_e12_open_tab_gives_zero_web_push_to_the_employee(admin_page, employee, webpush_context):
    """Критерий «0 Web Push при открытой вкладке» (FR-331): у сотрудника подписано устройство, вкладка портала открыта —
    при новой заявке число на колокольчике растёт, push воркер не показывает (контроль: вкладка уведена на страницу без
    колокольчика — то же событие даёт push; в конце показан ровно один push, за открытую вкладку его нет)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _queue_name = _queue(page)
    _members(page, queue_id, [member], tag)
    with _default_queue(page, old_id, queue_id), helpers_notify.channels_on(page, "webpush"):
        context, tab = _subscribe(webpush_context, member, spy=True)
        _save_prefs(tab, {(NEW_IN_QUEUE, "push"): True}, quiet="none")
        tab.goto("/")
        helpers_notify.wait_ws_open(tab)
        # когда: событие при открытой вкладке
        _event(tab)
        helpers_notify.wait_notifications(tab, count=1)  # вкладка показала своё системное уведомление
        # п. «0 push»: воркер ничего не показал за время, большее обычной доставки
        assert helpers_notify.no_service_worker_notifications(context, observe=15), "push при открытой вкладке"
        # контроль: вкладка закрыта (страница без колокольчика) — то же событие даёт push
        _away(tab, member)
        _new_mail()
        shown = helpers_notify.wait_service_worker_notifications(context, count=1, timeout=WAIT_EXTERNAL)
        # в конце: ровно один push (за событие при открытой вкладке второго нет)
        assert [n["title"] for n in helpers_notify.service_worker_notifications(context)] == [EXTERNAL_NEW]
        assert [n["title"] for n in shown] == [EXTERNAL_NEW]


@helpers_notify.webpush_only
def test_e12_quiet_hours_give_zero_system_notifications_mails_push_and_messages_while_bell_counter_grows(
        admin_page, employee, mailpit, webpush_context):
    """Критерий «0 системных уведомлений, писем, push и сообщений в тихие часы, число на колокольчике растёт» (FR-329):
    «Свои часы» вне текущего времени, включены почта, push, Telegram; при открытой вкладке число растёт, а системных
    уведомлений нет; при закрытой — нет push, писем и сообщений, а на портале уведомление есть. Контроль на том же
    сотруднике: после перехода на «Без тихих часов» событие при открытой вкладке даёт системное уведомление вкладки
    (контроль обёртки и разрешения), а событие при закрытой вкладке — push; письма и сообщения Telegram приходят за оба
    события; в конце лишнего нет (были только они)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _queue_name = _queue(page)
    _members(page, queue_id, [member], tag)
    bots = helpers_notify.fakebots()
    chat = _chat_id()
    with _default_queue(page, old_id, queue_id), helpers_notify.channels_on(page, "webpush", "telegram"):
        context, tab = _subscribe(webpush_context, member, spy=True)
        helpers_notify.bind_channel(tab, bots, "telegram", chat)
        start, end = _hours(3, 4)
        _save_prefs(tab, {(NEW_IN_QUEUE, c): True for c in ("email", "push", "telegram")}, quiet="own",
                    start=start, end=end)
        # тихие часы, вкладка открыта: число растёт, системного уведомления нет
        tab.goto("/")
        helpers_notify.wait_ws_open(tab)
        word_open, _s, _r = _event(tab)
        assert helpers_notify.no_notifications(tab, observe_ms=6_000), "системное уведомление в тихие часы"
        # тихие часы, вкладка закрыта: ни push, ни сообщения, ни письма
        _away(tab, member)
        word_closed, _s, _r = _new_mail()
        assert helpers_notify.no_service_worker_notifications(context, observe=15), "push в тихие часы"
        assert not _sent_texts(bots, "telegram", chat, EXTERNAL_NEW), "сообщение Telegram в тихие часы"
        # срок письма прошёл, всё ещё тихие часы: письма по одному нет (доставки удержаны для сводки)
        _tick()
        assert helpers_notify.no_item_mail(mailpit, member.email, wait=8), "письмо в тихие часы"
        # контроль: «Без тихих часов» (удержанное уходит сводкой); вкладка открыта на портале — событие даёт системное
        # уведомление вкладки (значит, обёртка и разрешение работали и «0» выше не ложное)
        _save_prefs(tab, quiet="none")
        helpers_notify.tick()
        tab.goto("/")
        helpers_notify.wait_ws_open(tab)
        word_free_open, _s, _r = _event(tab)
        assert len(helpers_notify.wait_notifications(tab, count=1)) == 1
        # вкладка закрыта — то же событие даёт push
        _away(tab, member)
        word_free, _s, _r = _new_mail()
        shown = helpers_notify.wait_service_worker_notifications(context, count=1, timeout=WAIT_EXTERNAL)
        helpers_notify.wait_sent(bots, "telegram", chat_id=chat, text_has=EXTERNAL_NEW, count=2, timeout=WAIT_EXTERNAL)
        _tick()
        first = helpers_notify.wait_item_mail(mailpit, member.email)
        helpers_notify.wait_item_mail(mailpit, member.email, seen={first["ID"]})
        # в конце: из четырёх событий внешние каналы получили только два последних (push — за закрытую вкладку)
        assert [n["title"] for n in helpers_notify.service_worker_notifications(context)] == [EXTERNAL_NEW]
        assert len(shown) == 1
        assert len(_sent_texts(bots, "telegram", chat, EXTERNAL_NEW)) == 2
        assert len(_mails(mailpit, member.email)) == 2, "письма по одному из тихих часов"
        # число на колокольчике росло и в тихие часы: строки всех трёх событий есть на портале
        tab.goto("/notifications/")
        for word in (word_open, word_closed, word_free_open, word_free):
            expect(tab.locator("ul[data-notifications] li[data-notification]").filter(has_text=word)).to_have_count(1)


def test_e12_new_ticket_in_my_queue_only_for_direct_members_not_for_parent_heads_or_all_tickets_holders(
        admin_page, employee, new_context):
    """Критерий «Новая заявка в моей очереди» — только прямым участникам (FR-308): участник команды получает, руководитель
    вышестоящего узла и держатель права «Все заявки» не получают, хотя заявку видят."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    worker, second, head, holder = (_staff(employee, tag, i) for i in (1, 2, 3, 4))
    dept_id = helpers_org.create_unit(page, helpers_org.unique_name("Сопровождение"))
    team_id, team_name = _queue(page, "Поддержка", kind="team", parent_id=dept_id)
    _members(page, dept_id, [head], tag)
    helpers_org.set_marks(page, dept_id, "heads", [head.id])  # руководитель вышестоящего узла, не участник команды
    _members(page, team_id, [worker, second], tag)
    role_id = _make_role(page, helpers_org.unique_name("Диспетчер"), [SD_ALL])
    _grant_role(page, holder.id, role_id)  # держатель права «Все заявки», не участник команды
    with _default_queue(page, old_id, team_id):
        tabs = helpers_notify.open_watchers(new_context, [worker, second, head, holder])
        bases = [helpers_notify.bell_count(t) for t in tabs]
        word, subject, _requester = _new_mail()
        number = helpers_sd.ticket_number_by_subject(page, word)
        expected = f"Новая заявка #{number} в очереди «{team_name}»: {subject}"
        # оба прямых участника получили (контроль)
        for tab, base in zip(tabs[:2], bases[:2]):
            _wait_plus(tab, base)
            rows = _rows(tab, word)
            expect(rows).to_have_count(1)
            assert _norm(rows.locator('[data-field="text"]').inner_text()) == _norm(expected)
        # руководитель вышестоящего узла и держатель «Все заявки»: числа не менялись, строк нет, заявка им видна
        for tab, base in zip(tabs[2:], bases[2:]):
            assert helpers_notify.bell_count(tab) == base
            expect(_rows(tab, word)).to_have_count(0)
            tab.goto(f"/tickets/?preset=unassigned&q={word}")
            expect(tab.locator(f'#tickets-grid tr[data-ticket="{number}"]')).to_have_count(1)
        # повторно в конце
        assert [helpers_notify.bell_count(t) for t in tabs[2:]] == bases[2:]


def test_e12_every_login_from_new_device_password_change_and_second_factor_reset_visible_on_portal(
        admin_page, employee, new_context):
    """Критерий «100 % входов с нового устройства, смен пароля и сбросов второго фактора видны» (FR-305): два входа из
    новых контекстов — две записи «Вход с нового устройства»; смена пароля — «Пароль изменён»; сброс второго фактора
    администратором и повторное подключение — «Второй фактор сброшен»; все записи непрочитанные, время московское."""
    acc = employee()
    page = acc.page
    before = _list(page)
    # когда: два входа из новых контекстов
    for _ in range(2):
        helpers.sign_in(new_context().new_page(), acc)
    devices = [r for r in _list(page) if NEW_DEVICE_RE.match(r["text"])]
    assert len(devices) - len([r for r in before if NEW_DEVICE_RE.match(r["text"])]) == 2, "не каждый вход виден"
    # когда: смена пароля
    changed = factories.new_password()
    page.goto("/me/security/password/")
    page.fill("input[name=current_password]", acc.password)
    page.fill("input[name=password1]", changed)
    page.fill("input[name=password2]", changed)
    with page.expect_navigation():
        page.locator("form:has(input[name=current_password]) button[type=submit]").click()
    page.wait_for_load_state()
    assert not helpers.alert_text(page), f"пароль не сменён: {helpers.alert_text(page)}"
    acc.password = changed
    # когда: администратор сбрасывает второй фактор, сотрудник подключает его заново
    admin_page.goto(f"/staff/{acc.id}/")
    helpers.open_security_tab(admin_page)
    helpers.submit(admin_page.locator('form[action$="/reset-2fa/"]'))
    acc.page.goto("/notifications/")  # сброс завершён: прежняя сессия закрыта
    assert "/login/" in acc.page.url, acc.page.url
    fresh = new_context().new_page()
    helpers.fill_login(fresh, acc.email, acc.password)
    fresh.wait_for_url(re.compile(r"/me/security/totp/"))
    seed = fresh.locator("#totp-secret").inner_text().strip()
    fresh.fill("input[name=code]", helpers.totp_for(seed))
    fresh.click("button[type=submit]")
    fresh.wait_for_url(re.compile(r"/me/security/backup-codes/"))
    fresh.locator("input[name=confirm]").check()
    fresh.click("button[type=submit]")
    expect(fresh.locator("#top-bar")).to_be_visible()
    # записи на портале: пароль и второй фактор — по одной, входы — не меньше двух новых, все непрочитанные, время московское
    rows = _list(fresh)
    assert len([r for r in rows if r["text"] == "Пароль изменён"]) == 1
    assert len([r for r in rows if r["text"] == "Второй фактор сброшен"]) == 1
    assert len([r for r in rows if NEW_DEVICE_RE.match(r["text"])]) >= len(devices)
    for row in rows:
        if row["text"] in ("Пароль изменён", "Второй фактор сброшен") or NEW_DEVICE_RE.match(row["text"]):
            assert row["unread"] == "1", row
            moment = datetime.fromisoformat(row["at"])
            assert moment.utcoffset() == timedelta(hours=3), row["at"]
            assert row["shown"] == moment.astimezone(MSK).strftime("%d.%m.%Y %H:%M"), row


@helpers_notify.webpush_only
def test_e12_zero_notifications_without_ticket_access_and_zero_numbers_subjects_names_addresses_in_external_channels(
        admin_page, employee, webpush_context):
    """Критерии «0 уведомлений без доступа к заявке» и «в Telegram, MAX и Web Push — 0 номеров, тем, ФИО и адресов» (FR-314,
    FR-317): участник очереди получает сообщение Telegram и MAX и push с общим текстом и ссылкой на страницу уведомлений,
    без номера, темы, названия очереди, имён и адресов; сотрудник вне очереди не получает ни записи на портале, ни
    сообщения. Проверяется один вид — «Новая заявка в моей очереди» (остальные внешние тексты — постоянные строки, § 3.2;
    их сверяет тест каталога)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    viewer, outsider = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, queue_name = _queue(page)
    _members(page, queue_id, [viewer], tag)
    bots = helpers_notify.fakebots()
    chat_view, chat_out, chat_view_max = _chat_id(), _chat_id(), _chat_id()
    with helpers_notify.channels_on(page, "webpush", "telegram", "max"):
        context, tab = _subscribe(webpush_context, viewer)
        helpers_notify.bind_channel(tab, bots, "telegram", chat_view)
        helpers_notify.bind_channel(tab, bots, "max", chat_view_max)
        helpers_notify.bind_channel(outsider.page, bots, "telegram", chat_out)
        _save_prefs(tab, {(NEW_IN_QUEUE, c): True for c in ("push", "telegram", "max")}, quiet="none")
        _away(tab, viewer)
        with _default_queue(page, old_id, queue_id):
            requester = helpers_sd.requester_email("secret")
            word, subject, _r = _new_mail("Пароль от сейфа Иванова {w}", requester)
            number = helpers_sd.ticket_number_by_subject(page, word)
            message = helpers_notify.wait_sent(bots, "telegram", chat_id=chat_view, text_has=EXTERNAL_NEW,
                                               timeout=WAIT_EXTERNAL)[0]
            message_max = helpers_notify.wait_sent(bots, "max", chat_id=chat_view_max, text_has=EXTERNAL_NEW,
                                                   timeout=WAIT_EXTERNAL)[0]
            pushes = helpers_notify.wait_service_worker_notifications(context, count=1, timeout=WAIT_EXTERNAL)
    forbidden = (word, "сейфа", "Иванова", f"#{number}", f"/tickets/{number}", queue_name, requester, viewer.email,
                 viewer.full_name, outsider.full_name, tag)
    assert message["text"] == EXTERNAL_NEW
    assert [n["title"] for n in pushes] == [EXTERNAL_NEW], pushes
    assert message_max["text"] == EXTERNAL_NEW
    for item in (message, message_max, *pushes):
        for text in forbidden:
            assert text not in _dump(item), "во внешнем канале есть внутренние данные заявки"
    markup = message["reply_markup"]
    markup = json.loads(markup) if isinstance(markup, str) else markup
    assert markup["inline_keyboard"][0][0]["url"].endswith("/notifications/"), "ссылка — не страница уведомлений"
    buttons = message_max["attachments"][0]["payload"]["buttons"]
    assert buttons[0][0]["url"].endswith("/notifications/"), "ссылка MAX — не страница уведомлений"
    assert (pushes[0]["data"] or {}).get("url", "").split("?")[0].endswith("/notifications/"), pushes[0]["data"]
    # сотрудник вне очереди: ни записи на портале, ни сообщения (контроль — участник получил оба)
    expect(_rows(outsider.page, word)).to_have_count(0)
    assert not _sent_texts(bots, "telegram", chat_out, EXTERNAL_NEW)
    assert len(_sent_texts(bots, "telegram", chat_view, EXTERNAL_NEW)) == 1
    assert len(_sent_texts(bots, "max", chat_view_max, EXTERNAL_NEW)) == 1


def test_e12_channel_failure_loses_no_portal_notification(admin_page, employee, new_context):
    """Критерий «сбой Telegram или MAX не теряет уведомление на портале» (FR-333): учебная служба на первую отправку
    отвечает 500 в обоих каналах — число на колокольчике и строка списка появились сразу; после срока повтора
    (`tick --shift`) сообщения доходят, по одному в каждый канал."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _queue_name = _queue(page)
    _members(page, queue_id, [member], tag)
    bots = helpers_notify.fakebots()
    chat_tg, chat_max = _chat_id(), _chat_id()
    with helpers_notify.channels_on(page, "telegram", "max"):
        helpers_notify.bind_channel(member.page, bots, "telegram", chat_tg)
        helpers_notify.bind_channel(member.page, bots, "max", chat_max)
        _save_prefs(member.page, {(NEW_IN_QUEUE, c): True for c in ("telegram", "max")}, quiet="none")
        with _default_queue(page, old_id, queue_id):
            try:
                tab = helpers_notify.open_watcher(new_context, member)
                base = helpers_notify.bell_count(tab)
                # ошибка канала от прошлого теста круга (если есть) запоминается: ожидание ниже ждёт новую, а не её
                before = {channel: _channel_error_stamp(page, channel) for channel in ("telegram", "max")}
                bots.fail("telegram", 500, method="sendMessage", count=1)
                bots.fail("max", 500, method="messages", count=1)
                # когда: событие при сбое обоих каналов
                word, _subject, _r = _new_mail()
                # портал: уведомление не потеряно
                _wait_plus(tab, base)
                expect(_rows(tab, word)).to_have_count(1)
                # сбой виден администратору (первая попытка состоялась и не удалась), значит повтор пойдёт по сроку
                for channel in ("telegram", "max"):
                    _wait_channel_error(page, channel, before=before[channel])
                # повтор: срок повтора прошёл — сообщения доходят
                helpers_notify.tick(shift=2)
                helpers_notify.wait_sent(bots, "telegram", chat_id=chat_tg, text_has=EXTERNAL_NEW, timeout=WAIT_EXTERNAL + 30)
                helpers_notify.wait_sent(bots, "max", chat_id=chat_max, text_has=EXTERNAL_NEW, timeout=WAIT_EXTERNAL + 30)
                # повторно в конце: на портале по-прежнему одна строка, в каждом канале ровно одно сообщение
                helpers_notify.tick()
                expect(_rows(tab, word)).to_have_count(1)
                page.goto("/settings/notifications/")
                for channel in ("telegram", "max"):
                    expect(page.locator(f'section[data-channel-block="{channel}"] [data-channel-error]')).to_have_count(0)
                assert len(_sent_texts(bots, "telegram", chat_tg, EXTERNAL_NEW)) == 1
                assert len(_sent_texts(bots, "max", chat_max, EXTERNAL_NEW)) == 1
            finally:
                bots.clear_fails("telegram", method="sendMessage")
                bots.clear_fails("max", method="messages")


def test_e12_catalog_shows_four_service_desk_kinds_three_security_kinds_and_channel_unlinked_with_texts_per_fr_316_and_317(
        admin_page, employee, new_context, mailpit):
    """Критерий «каталог: четыре вида сервис-деска, три вида безопасности и «Канал отвязан»; тексты на портале и в письме
    — FR-316, в Telegram — FR-317» (FR-301, FR-302, FR-304, FR-316, FR-317, FR-344): состав и внешние тексты каталога
    (чтение каталога `helpers.stand_shell`), строки таблицы «Мои уведомления» (четыре вида и две сводные строки),
    живое событие: портал и письмо — полный текст, Telegram — общий текст."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, queue_name = _queue(page)
    _members(page, queue_id, [member], tag)
    # состав каталога (stand_shell: kinds.catalog(), строка JSON)
    raw = helpers.stand_shell(
        "import json; from apps.notify.services import kinds; "
        "print('catalog', json.dumps([[k.code, k.title, k.module, bool(k.mandatory), k.external_text] "
        "for k in kinds.catalog()], ensure_ascii=False))").splitlines()[-1]
    assert raw.startswith("catalog "), "stand_shell не вернула каталог"
    catalog = {code: (title, module, mandatory, external) for code, title, module, mandatory, external
               in json.loads(raw[len("catalog "):])}
    for code, expected in EXPECTED_CATALOG.items():
        assert catalog.get(code) == expected, (code, catalog.get(code))
    assert set(catalog) == set(EXPECTED_CATALOG), sorted(set(catalog) ^ set(EXPECTED_CATALOG))
    assert len([c for c in catalog if c.startswith("servicedesk.")]) == 4
    assert sorted(c for c in catalog if c.startswith("core.")) == [
        "core.new_device", "core.password_changed", "core.second_factor_reset"]
    # таблица «Мои уведомления»: четыре вида сервис-деска и две сводные строки
    member.page.goto("/me/notifications/")
    for code, title in KINDS:
        row = member.page.locator(f'table[data-notify-table] tr[data-notify-kind="{code}"]')
        expect(row).to_have_count(1)
        expect(row.locator('[data-field="title"]')).to_have_text(title)
        expect(row.locator('[data-field="module"]')).to_have_text(MODULE)
    # видимый результат: ровно четыре вида сервис-деска, видов безопасности и «Канал отвязан» среди строк видов нет
    expect(member.page.locator("table[data-notify-table] tr[data-notify-kind]")).to_have_count(len(KINDS))
    expect(member.page.locator('table[data-notify-table] tr[data-notify-kind^="core."], '
                               'table[data-notify-table] tr[data-notify-kind^="notify."]')).to_have_count(0)
    # страница администратора: те же четыре вида (§ 14.4: все виды, кроме обязательных)
    page.goto("/settings/notifications/")
    expect(page.locator("table[data-defaults-table] tr[data-notify-kind]")).to_have_count(len(KINDS))
    for code, _title in KINDS:
        expect(page.locator(f'table[data-defaults-table] tr[data-notify-kind="{code}"]')).to_have_count(1)
    expect(member.page.locator('tr[data-notify-fixed="security"]')).to_contain_text(FIXED_SECURITY)
    expect(member.page.locator('tr[data-notify-fixed="channel_unbound"]')).to_contain_text(FIXED_UNBOUND)
    # живое событие: портал, письмо (FR-316) и Telegram (FR-317)
    bots = helpers_notify.fakebots()
    chat = _chat_id()
    with helpers_notify.channels_on(page, "telegram"):
        helpers_notify.bind_channel(member.page, bots, "telegram", chat)
        _save_prefs(member.page, {(NEW_IN_QUEUE, "email"): True, (NEW_IN_QUEUE, "telegram"): True}, quiet="none")
        with _default_queue(page, old_id, queue_id):
            tab = helpers_notify.open_watcher(new_context, member)
            word, subject, _r = _event(tab)
            number = helpers_sd.ticket_number_by_subject(page, word)
            full = f"Новая заявка #{number} в очереди «{queue_name}»: {subject}"
            rows = _rows(tab, word)
            expect(rows).to_have_count(1)
            assert _norm(rows.locator('[data-field="text"]').inner_text()) == _norm(full)
            sent = helpers_notify.wait_sent(bots, "telegram", chat_id=chat, text_has=EXTERNAL_NEW, timeout=WAIT_EXTERNAL)
            assert sent[0]["text"] == EXTERNAL_NEW and word not in _dump(sent[0])
            _tick()
            letter = helpers_notify.wait_item_mail(mailpit, member.email)
            assert letter["Subject"] == EXTERNAL_NEW
            assert _norm(full) in _norm(letter["Text"])


def test_e12_ticket_subject_with_markup_shown_as_text_on_portal_and_in_mail(admin_page, employee, new_context, mailpit):
    """Критерий «тема заявки с разметкой выводится текстом» (NFR-311): тема `<b>…</b> <script>…</script>` — на портале
    (список и панель колокольчика) и в письме те же знаки текстом, тегов `b` и `script` в разметке нет."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, queue_name = _queue(page)
    _members(page, queue_id, [member], tag)
    _mail_prefs(member.page)
    with _default_queue(page, old_id, queue_id):
        tab = helpers_notify.open_watcher(new_context, member)
        word, subject, _r = _event(tab, subject="<b>Жирный</b> <script>alert(1)</script> {w}")
        number = helpers_sd.ticket_number_by_subject(page, word)
        expected = f"Новая заявка #{number} в очереди «{queue_name}»: {subject}"
        # портал: список
        rows = _rows(tab, word)
        expect(rows).to_have_count(1)
        text = rows.locator('[data-field="text"]')
        assert _norm(text.inner_text()) == _norm(expected)
        assert text.locator("b, script").count() == 0 and "&lt;b&gt;" in text.inner_html()
        # портал: панель колокольчика
        tab.locator("button[data-bell-toggle]").click()
        panel = tab.locator("#notify-bell-panel [data-bell-list]")
        expect(panel).to_be_visible()
        entry = panel.locator("li[data-notification]").filter(has_text=word)
        expect(entry).to_have_count(1)
        assert "<b>Жирный</b>" in entry.inner_text() and entry.locator("b, script").count() == 0
        # письмо: тема письма — внешний текст, в теле заявка с теми же знаками текстом
        _tick()
        letter = helpers_notify.wait_item_mail(mailpit, member.email)
        assert letter["Subject"] == EXTERNAL_NEW
        assert _norm(expected) in _norm(letter["Text"])
        assert not letter.get("HTML"), "у письма уведомления есть HTML-часть"


def test_e12_notification_pages_and_my_notifications_and_admin_settings_have_no_horizontal_scroll_at_360px(
        admin_page, employee, new_context):
    """Критерий «страницы среза без горизонтальной прокрутки на 360 px» (NFR-308): «Уведомления» (все и непрочитанные),
    «Мои уведомления», страница администратора и панель колокольчика; список заполнен (60 уведомлений), таблицы складываются
    в карточки."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _queue_name = _queue(page)
    _members(page, queue_id, [member], tag)
    helpers_notify.fill(member.email, 60, read=10)
    narrow = {"width": 360, "height": 740}
    mine = new_context(storage_state=helpers_notify.session_state(member), viewport=narrow).new_page()
    admin = new_context(storage_state=page.context.storage_state(), viewport=narrow).new_page()
    for url, root in (("/notifications/", "[data-notify-list]"), ("/notifications/?page=2", "[data-notify-list]"),
                      ("/notifications/?f=unread", "[data-notify-list]"),
                      ("/me/notifications/", "[data-notify-prefs]")):
        mine.goto(url)
        expect(mine.locator(root)).to_be_visible()
        assert mine.locator('meta[name="viewport"]').count() == 1, url
        assert helpers.no_horizontal_scroll(mine), f"горизонтальная прокрутка: {url}"
    expect(mine.locator('[data-narrow="cards"] table[data-notify-table]')).to_have_count(1)
    mine.locator("button[data-bell-toggle]").click()
    expect(mine.locator("#notify-bell-panel [data-bell-list]")).to_be_visible()
    assert helpers.no_horizontal_scroll(mine), "горизонтальная прокрутка: панель колокольчика"
    admin.goto("/settings/notifications/")
    expect(admin.locator("[data-notify-settings]")).to_be_visible()
    assert admin.locator('meta[name="viewport"]').count() == 1
    expect(admin.locator('[data-narrow="cards"] table[data-defaults-table]')).to_have_count(1)
    assert helpers.no_horizontal_scroll(admin), "горизонтальная прокрутка: /settings/notifications/"


def test_e12_notification_pages_show_russian_text_and_moscow_time(admin_page, employee, new_context, mailpit):
    """Критерий «время и язык — Europe/Moscow и русский» (NFR-307): страницы среза с `lang="ru"` и русскими заголовками и
    кнопками (исключения — Push, Web Push, Telegram, MAX); время уведомления — московское и совпадает с временем события;
    письмо уведомления — по-русски."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _queue_name = _queue(page)
    _members(page, queue_id, [member], tag)
    _mail_prefs(member.page)
    with _default_queue(page, old_id, queue_id):
        tab = helpers_notify.open_watcher(new_context, member)
        started = _now()
        word, _subject, _r = _event(tab)
        finished = _now()
        _tick()
        letter = helpers_notify.wait_item_mail(mailpit, member.email)
    assert CYRILLIC.search(letter["Subject"]) and CYRILLIC.search(letter["Text"])
    # время события: московское, между началом и концом события; видимый текст — то же московское время
    row = [r for r in _list(tab) if word in r["text"]][0]
    moment = datetime.fromisoformat(row["at"])
    assert moment.utcoffset() == timedelta(hours=3), row["at"]
    assert started - timedelta(minutes=1) <= moment <= finished + timedelta(minutes=1), row["at"]
    assert row["shown"] == moment.astimezone(MSK).strftime("%d.%m.%Y %H:%M"), row
    # язык страниц
    for who, url, root, h1 in ((tab, "/notifications/", "[data-notify-list]", "Уведомления"),
                               (tab, "/me/notifications/", "[data-notify-prefs]", "Мои уведомления"),
                               (page, "/settings/notifications/", "[data-notify-settings]", "Настройки уведомлений")):
        who.goto(url)
        expect(who.locator(root)).to_be_visible()
        expect(who.locator("html")).to_have_attribute("lang", "ru")
        expect(who.locator("h1").first).to_have_text(h1)
        title = who.title()
        assert CYRILLIC.search(title), title
        expect(who).to_have_title(re.compile(re.escape(who.locator("h1").first.inner_text())))
        labels = [who.locator("h1").first.inner_text()] + [
            b.inner_text() for b in who.locator(f"{root} button").all() if b.inner_text().strip()]
        for label in labels:
            plain = label
            for word_ in LANGUAGE_EXCEPTIONS:
                plain = plain.replace(word_, "")
            assert not LATIN_WORD.search(plain), f"{url}: нерусская подпись {label!r}"
            assert CYRILLIC.search(label) or not plain.strip(), f"{url}: подпись {label!r}"


def test_e12_dismissed_employee_loses_bindings_and_blocked_one_gets_no_external_deliveries(
        admin_page, employee, new_context, mailpit):
    """Критерии «при увольнении удалены привязки и коды» (FR-340) и «у заблокированного внешние доставки не уходят»
    (FR-345): уволенный — привязка Telegram и неиспользованный код удалены (строки базы), сообщений в его чат нет;
    заблокированный — ни сообщения Telegram, ни письма, коллега (контроль) получает оба. Подписку Web Push уволенного
    проверяет e2e/test_e06_bots (метка webpush)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    leaver, blocked, keeper = (_staff(employee, tag, i) for i in (1, 2, 3))
    queue_id, _queue_name = _queue(page)
    _members(page, queue_id, [leaver, blocked, keeper], tag)
    bots = helpers_notify.fakebots()
    chat_leaver, chat_blocked, chat_keeper = _chat_id(), _chat_id(), _chat_id()
    reason = "проверка блокировки " + secrets.token_hex(3)
    with helpers_notify.channels_on(page, "telegram"):
        helpers_notify.bind_channel(leaver.page, bots, "telegram", chat_leaver)
        helpers_notify.bind_channel(blocked.page, bots, "telegram", chat_blocked)
        helpers_notify.bind_channel(keeper.page, bots, "telegram", chat_keeper)
        for account in (leaver, blocked, keeper):
            _save_prefs(account.page, {(NEW_IN_QUEUE, c): True for c in ("email", "telegram")}, quiet="none")
        issued = helpers_org.direct_post(leaver.page, "/me/notifications/bind/telegram/")
        assert issued.status == 200, f"новый код не выдан: статус {issued.status}"
        before = _db_counts(leaver.email)
        assert before["bindings"] == 1 and before["unused_codes"] >= 1, before
        known_leaver = len(helpers_notify.sent_to(bots, "telegram", chat_leaver))
        try:
            # когда: одного увольняют, другого блокируют
            _dismiss(page, leaver.id)
            assert _db_counts(leaver.email) == {"push": 0, "bindings": 0, "unused_codes": 0}
            _block(page, blocked.id, reason)
            with _default_queue(page, old_id, queue_id):
                _new_mail()
                # контроль: коллега получил сообщение и (после срока) письмо
                helpers_notify.wait_sent(bots, "telegram", chat_id=chat_keeper, text_has=EXTERNAL_NEW, timeout=WAIT_EXTERNAL)
                _tick()
                helpers_notify.wait_item_mail(mailpit, keeper.email)
        finally:
            _unblock(page, blocked.id)
        # у заблокированного и у уволенного внешних доставок нет (повторно в конце, после второго обхода)
        helpers_notify.tick()
        assert not _sent_texts(bots, "telegram", chat_blocked, EXTERNAL_NEW), "сообщение заблокированному"
        assert len(helpers_notify.sent_to(bots, "telegram", chat_leaver)) == known_leaver, "сообщение уволенному"
        assert helpers_notify.no_item_mail(mailpit, blocked.email, wait=8), "письмо заблокированному"
        assert helpers_notify.no_item_mail(mailpit, leaver.email, wait=1), "письмо уволенному"
