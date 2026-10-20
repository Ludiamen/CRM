"""T-4144: сценарий 5 — Web Push на своём устройстве: подписка, согласие и отказ в браузере, push при закрытой
вкладке, системное уведомление во вкладке, два устройства, ответ push-сервиса «подписки нет», выход, чужая
учётная запись в том же браузере (FR-317, FR-320, FR-324, FR-328, FR-329, FR-331, FR-332, FR-336).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-004.md):
- тесты с подпиской устройства или ожиданием Web Push помечены `@helpers_notify.webpush_only` и берут устройства из
  `webpush_context()` (постоянный профиль, дополнение 23): круги `chromium` и `edge`. Тесты без подписки идут в трёх
  кругах (обычный контекст, системное уведомление вкладки — обёртка `Notification`, решение E22);
- «браузер спрашивает разрешение и сотрудник соглашается» в безголовом браузере — это `grant_notifications(context)`
  до нажатия кнопки (подтвердить окно запроса Playwright не может); «сотрудник отказал» — разрешение не выдано, и
  безголовый браузер отклоняет запрос сам;
- нажатие на системное уведомление ОС Playwright не делает (решение 12 задач): «нажатие открывает страницу
  уведомлений» проверяется по `data.url` показанного воркером уведомления и переходом по этой ссылке;
- «все вкладки закрыты» — закрыта и страница `Account.page` из `employee(...)` (в её контексте остаётся открытая
  страница портала с колокольчиком, то есть действующее соединение живых обновлений: Web Push был бы пропущен,
  `tab_open`, FR-331); страницы, которые читают уведомления воркера, — `/sw.js` (без колокольчика);
- у каждого, чьё уведомление проверяется, режим «Без тихих часов» (иначе системное уведомление и push зависели бы от
  времени суток); общие настройки: Web Push на странице администратора включается и выключается только
  `channels_on` / `channels_off` (возвращается в `finally`), очередь по умолчанию — своя на время теста;
- каждое «нет push / нет уведомления» идёт с положительным контролем того же пути (следующее событие, на которое
  push или уведомление приходит) и повторной проверкой числа в конце;
- команд стенда, кроме писем заявителя `helpers_sd.deliver` (APPEND в IMAP и разбор почты) и одного чтения базы в тесте 9
  (`_delivery`, `helpers.stand_shell`: запись «Доставка», решение 26), файл не вызывает; токены, адреса и ключи подписки
  тест не читает и не печатает.
"""
import contextlib
import json
import re
import secrets
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers, helpers_notify, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_servicedesk import build_mail

NEW_IN_QUEUE = "servicedesk.new_in_queue"
EXTERNAL_SUBJECT = "Новая заявка в вашей очереди"  # заголовок push и текст внешних каналов (§ 15.2, FR-317)
BUTTON_ALLOW = "Разрешить уведомления браузера"  # § 15.5, решение 34 задач
BUTTON_SUBSCRIBE = "Включить push на этом устройстве"  # § 15.5
DISABLED_TEXT = "Push при закрытой вкладке отключён администратором"  # § 15.5
HINT_ALLOW = "Разрешите push на этом устройстве"  # § 15.5 (подсказка ячейки push без подписки)
DENIED_START = "Браузер запретил уведомления для этого сайта"  # § 15.5 (начало пояснения)
EMPTY_DEVICES = "Устройств с push пока нет"  # § 15.5
PUSH_WAIT = 90  # секунд: настоящий push-сервис, норма NFR-302 — минута, запас до 90 с
LONG_WAIT_MS = 15_000

# Счётчик запросов разрешения и подписки: пишет в sessionStorage вкладки и потому переживает переходы между страницами
REQUEST_COUNTER = """
(() => {
  if (!window.Notification || window.__e2eRequestCounter) { return; }
  window.__e2eRequestCounter = true;
  const bump = () => {
    try { sessionStorage.setItem('e2eRequests', String(Number(sessionStorage.getItem('e2eRequests') || '0') + 1)); }
    catch (e) { /* страница без хранилища: не портал */ }
  };
  const nativeRequest = Notification.requestPermission;
  Notification.requestPermission = function () { bump(); return nativeRequest.apply(this, arguments); };
  if (window.PushManager && PushManager.prototype.subscribe) {
    const nativeSubscribe = PushManager.prototype.subscribe;
    PushManager.prototype.subscribe = function () { bump(); return nativeSubscribe.apply(this, arguments); };
  }
})();
"""

UNSUBSCRIBE = """async () => {
    const registration = await navigator.serviceWorker.getRegistration();
    if (!registration) { return false; }
    const subscription = await registration.pushManager.getSubscription();
    if (!subscription) { return false; }
    return await subscription.unsubscribe();
}"""  # отписка в самом браузере (решение 26 задач)

WAIT_DEVICE_GONE = """async ({device, ms}) => {
    const end = Date.now() + ms;
    for (;;) {
        const response = await fetch('/me/notifications/', {credentials: 'same-origin'});
        const html = await response.text();
        // страница «Мои уведомления» получена (есть раздел push) и устройства в ней уже нет
        if (html.includes('data-section="push"') && !html.includes('data-device="' + device + '"')) { return true; }
        if (Date.now() >= end) { return false; }
        await new Promise(resolve => setTimeout(resolve, 1000));
    }
}"""  # цикл внутри одного `evaluate`; вызывается со страницы `/sw.js`, у которой нет колокольчика и присутствия


# --- Общие помощники файла ----------------------------------------------------------------------------

def _norm(text: str) -> str:
    return " ".join(text.split())


def _word() -> str:
    """Уникальное слово темы: буква и шесть шестнадцатеричных знаков (не из одних цифр)."""
    return f"t{secrets.token_hex(3)}"


def _tag() -> str:
    return "Очередь" + secrets.token_hex(3)


def _queue(page, prefix: str = "Поддержка") -> tuple:
    """Новый узел `org`, отмеченный очередью: `(номер, название)`."""
    name = helpers_org.unique_name(prefix)
    unit_id = helpers_org.create_unit(page, name)
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
    """Очередь по умолчанию на время теста — своя (письмо заявителя попадает в неё); прежняя возвращается в `finally`."""
    helpers_sd.set_default_queue(page, queue_id)
    try:
        yield
    finally:
        helpers_sd.set_default_queue(page, old_id)


def _set_quiet(page, mode: str, *, days=(), start=None, end=None) -> None:
    """«Мои уведомления» сотрудника: режим тихих часов (`none` или `own` с днями и часами); ждёт сообщение страницы и
    проверяет сохранённый режим (§ 13.2, § 14.3). Таблицу «вид × канал» не трогает."""
    page.goto("/me/notifications/")
    form = page.locator('form[data-form="notify-prefs"]')
    expect(form).to_be_visible()
    form.locator(f'fieldset[data-quiet] input[type=radio][name="quiet_mode"][value="{mode}"]').check()
    if mode == "own":
        for day in range(7):
            form.locator(f'fieldset[data-quiet] input[type=checkbox][name="own_days"][value="{day}"]'
                         ).set_checked(day in days)
        form.locator('fieldset[data-quiet] input[type=time][name="own_start"]').fill(start)
        form.locator('fieldset[data-quiet] input[type=time][name="own_end"]').fill(end)
    with page.expect_navigation():
        form.locator('button[type=submit][data-action="save-prefs"]').click()
    page.wait_for_load_state()
    assert not helpers.alert_text(page), f"настройки не сохранены: {helpers.alert_text(page)}"
    expect(page.locator("[role=status]").first).to_be_visible()
    expect(page.locator(f'fieldset[data-quiet] input[name="quiet_mode"][value="{mode}"]')).to_be_checked()


def _team(page, employee, size: int = 1) -> tuple:
    """Сотрудники-участники своей очереди с режимом «Без тихих часов»: `(список, номер очереди, название очереди)`."""
    tag = _tag()
    people = [employee(full_name=f"{tag}{i} Петр Петрович") for i in range(1, size + 1)]
    queue_id, queue_name = _queue(page)
    _members(page, queue_id, people, tag)
    for person in people:
        _set_quiet(person.page, "none")
    return people, queue_id, queue_name


def _new_mail(title: str = "Не работает принтер", *, long_subject: bool = False) -> tuple:
    """Письмо заявителя в ящик заявок и сразу разбор: заявка в очереди по умолчанию без ответственного. Возвращает
    `(слово, тема)`; с `long_subject` тема начинается со слова и длиннее 100 знаков (слово не обрезается)."""
    word = _word()
    subject = f"{word} " + ("Очень длинная тема заявки про принтер " * 4).strip() if long_subject else f"{title} {word}"
    helpers_sd.deliver(build_mail(from_addr=helpers_sd.requester_email(), to=[MAILBOX], subject=subject,
                                  text=f"Нужна помощь {word}", message_id=f"<{secrets.token_hex(8)}@client.test>"))
    return word, subject


def _text_new(number, queue_name: str, subject: str) -> str:
    """Текст уведомления «Новая заявка в моей очереди» на портале и в системном уведомлении вкладки (§ 15.1)."""
    return f"Новая заявка #{number} в очереди «{queue_name}»: {subject}"


def _close_member(member) -> None:
    """Закрывает страницу `Account.page` (в её контексте открыт портал с колокольчиком — присутствие, FR-331)."""
    if member.page is not None and not member.page.is_closed():
        member.page.close()


def _notification_rows(page, word: str):
    """Открывает `/notifications/` и возвращает строки списка со словом темы (список только читает)."""
    page.goto("/notifications/")
    expect(page.locator("[data-notify-list]")).to_be_visible()
    return page.locator("ul[data-notifications] li[data-notification]").filter(has_text=word)


def _push_cell(page):
    """Ячейка «Push в браузере» вида «Новая заявка в моей очереди» (§ 14.3)."""
    return page.locator(f'form[data-form="notify-prefs"] tr[data-notify-kind="{NEW_IN_QUEUE}"] td[data-channel="push"]')


def _device_row(page, device):
    return page.locator(f'ul[data-devices] li[data-device="{device}"]')


def _push_ready(page) -> None:
    """Страница «Мои уведомления» после подписки: столбец push доступен, ячейка вида отмечена (значение по умолчанию)."""
    page.goto("/me/notifications/")
    cell = _push_cell(page)
    expect(cell).to_have_attribute("data-available", "1")
    expect(cell.locator('input[type=checkbox][name="cell"]')).to_be_checked()


def _subscribe(context, member) -> tuple:
    """Устройство с сессией сотрудника в постоянном профиле: разрешение выдано (согласие в окне запроса), кнопка
    «Включить push на этом устройстве»; возвращает `(вкладка, номер устройства)`. Вкладка остаётся открытой."""
    helpers_notify.adopt_session(context, member)
    helpers_notify.grant_notifications(context)
    tab = context.new_page()
    device = helpers_notify.enable_push_on_device(tab)
    _push_ready(tab)
    return tab, device


def _device_via_login(context, member) -> tuple:
    """То же, но «настоящее» второе устройство: вход в профиле (`helpers.sign_in`), без переноса куки."""
    tab = context.new_page()
    helpers.sign_in(tab, member)
    helpers_notify.grant_notifications(context)
    device = helpers_notify.enable_push_on_device(tab)
    return tab, device


def _requests(page) -> int:
    """Число запросов разрешения и подписки, сделанных страницами вкладки (счётчик `REQUEST_COUNTER`)."""
    return int(page.evaluate("() => sessionStorage.getItem('e2eRequests') || '0'"))


def _watch_ordinary(new_context, member, *, grant: bool, counter: bool = False):
    """Вкладка сотрудника в обычном контексте (все три круга): обёртка `Notification`, при `grant` — разрешение,
    при `counter` — счётчик запросов разрешения; соединение готово. Возвращает страницу."""
    context = new_context(storage_state=helpers_notify.session_state(member))
    if counter:
        context.add_init_script(REQUEST_COUNTER)
    return helpers_notify.open_tab(context, None, spy=True, grant=grant)


def _in_sw_page(context, action):
    """Действие на странице `/sw.js` контекста (без колокольчика и присутствия); страница закрывается."""
    page = context.new_page()
    try:
        page.goto(helpers_notify.SW_PATH)
        return action(page)
    finally:
        page.close()


def _delivery(email: str, word: str):
    """Запись «Доставка» канала `webpush` уведомления со словом темы (чтение базы, `helpers.stand_shell`, § 2.2): состояние,
    причина, записи `log` (время, итог, код ответа, причина; адресов подписок и ключей в `log` нет)."""
    code = ("import json; from django.apps import apps; "
            "D = apps.get_model('notify.Delivery'); "
            f"d = D.objects.filter(channel='webpush', notification__user__email__iexact='{email}', "
            f"notification__text__contains='{word}').order_by('-id').first(); "
            "out = None if d is None else {'state': d.state, 'reason': d.reason, "
            "'log': [{k: e.get(k) for k in ('outcome', 'code', 'reason')} for e in d.log]}; "
            "print('delivery ' + json.dumps(out))")
    lines = [ln for ln in helpers.stand_shell(code).splitlines() if ln.startswith("delivery ")]
    assert lines, "stand_shell не вернула строку delivery"
    return json.loads(lines[-1][len("delivery "):])


def _titles(shown: list) -> list:
    return [_norm(item["title"]) for item in shown]


# --- Тесты --------------------------------------------------------------------------------------------------

@helpers_notify.webpush_only
def test_e05_enable_push_on_device_after_consent_saves_subscription_lists_device_and_enables_push_column(
        admin_page, employee, webpush_context):
    """Сценарий 5, п. 1: Web Push включён администратором, сотрудник нажимает «Включить push на этом устройстве» и
    соглашается в окне браузера — подписка сохранена, устройство в списке «Моих уведомлений», столбец «Push в браузере»
    доступен (FR-324)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    (member,), _queue_id, _name = _team(page, employee)
    with helpers_notify.channels_on(page, "webpush"):
        context = webpush_context()
        helpers_notify.adopt_session(context, member)
        tab = context.new_page()
        tab.goto("/me/notifications/")
        # до подписки: раздел включён, кнопка с подписью §15.5, устройств нет, столбец push недоступен с подсказкой
        expect(tab.locator('[data-section="push"]')).to_have_attribute("data-web-push", "on")
        expect(tab.locator('button[type=button][data-action="push-subscribe"]')).to_have_text(BUTTON_SUBSCRIBE)
        expect(tab.locator('[data-empty-state="devices"]')).to_contain_text(EMPTY_DEVICES)
        expect(tab.locator("ul[data-devices] li[data-device]")).to_have_count(0)
        cell = _push_cell(tab)
        expect(cell).to_have_attribute("data-available", "0")
        expect(cell).to_have_attribute("data-reason", "no_subscriptions")
        expect(cell.locator("[data-hint]")).to_contain_text(HINT_ALLOW)
        # п. 1: «согласие в окне браузера» — разрешение выдано контексту до нажатия
        helpers_notify.grant_notifications(context)
        device = helpers_notify.enable_push_on_device(tab)
        # п. 1: подписка сохранена — устройство в списке с браузером, платформой и датой, подписка есть и в браузере
        row = _device_row(tab, device)
        expect(row).to_have_count(1)
        expect(row.locator('[data-field="browser"]')).not_to_be_empty()
        expect(row.locator('[data-field="platform"]')).not_to_be_empty()
        expect(row.locator("time[data-at]")).to_have_count(1)
        expect(tab.locator("ul[data-devices] li[data-device]")).to_have_count(1)
        assert helpers_notify.has_push_subscription(tab), "подписки нет в самом браузере"
        # п. 1: столбец «Push в браузере» доступен, ячейка вида отмечена, кнопка подписки скрыта (подписка есть)
        _push_ready(tab)
        expect(_push_cell(tab)).to_have_attribute("data-reason", "")
        subscribe = tab.locator('button[type=button][data-action="push-subscribe"]')
        expect(subscribe).to_have_attribute("data-device-subscribed", "1")  # признак с портала (дополнение 27)
        expect(subscribe).to_be_hidden()


def test_e05_opening_pages_does_not_request_browser_permission_until_button_pressed(
        admin_page, employee, new_context):
    """Сценарий 5 (решение 34 задач), п. 1: при открытии страниц портала запрос разрешения браузера не делается, он
    уходит только по нажатию кнопки «Разрешить уведомления браузера» (FR-320)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    (member,), _queue_id, _name = _team(page, employee)
    # Web Push выключен: счётчик считает только запросы разрешения, подписка браузера его не меняет
    with helpers_notify.channels_off(page, "webpush"):
        context = new_context(storage_state=helpers_notify.session_state(member))
        context.add_init_script(REQUEST_COUNTER)
        tab = helpers_notify.open_tab(context, None, url="/")
        # п. 1: страницы открыты, соединение готово (скрипты страницы отработали), запросов разрешения и подписки не было
        for url in ("/", "/notifications/", "/me/", "/me/notifications/"):
            tab.goto(url)
            helpers_notify.wait_ws_open(tab)
            assert _requests(tab) == 0, f"страница {url} запросила разрешение браузера при загрузке"
            assert helpers_notify.notification_permission(tab) != "granted"
        # п. 1: кнопка есть и по нажатию запрашивает разрешение ровно один раз
        button = tab.locator('button[type=button][data-action="push-permission"]')
        expect(button).to_have_text(BUTTON_ALLOW)
        button.click()
        tab.wait_for_function("() => Number(sessionStorage.getItem('e2eRequests') || '0') >= 1")
        assert _requests(tab) == 1


@helpers_notify.webpush_only
def test_e05_denied_permission_leaves_no_subscription_and_explains_how_to_allow_in_browser_settings(
        admin_page, employee, webpush_context):
    """Сценарий 5, п. 2: сотрудник отказал в разрешении (безголовый браузер отклоняет запрос сам) — подписки нет ни в
    браузере, ни на портале, страница объясняет, как разрешить уведомления в настройках браузера, обе кнопки скрыты
    (FR-324)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    (member,), _queue_id, _name = _team(page, employee)
    with helpers_notify.channels_on(page, "webpush"):
        context = webpush_context()
        helpers_notify.adopt_session(context, member)  # разрешение НЕ выдаётся: запрос будет отклонён
        tab = context.new_page()
        pushes = []
        tab.on("request", lambda r: pushes.append(r.url) if r.method == "POST"
               and r.url.split("?")[0].endswith("/me/notifications/push/") else None)
        tab.goto("/me/notifications/")
        subscribe = tab.locator('button[type=button][data-action="push-subscribe"]')
        if subscribe.is_visible():  # если разрешение уже отклонено браузером, кнопки нет и нажимать нечего
            subscribe.click()
        # п. 2: пояснение, как разрешить в настройках браузера; обе кнопки скрыты
        denied = tab.locator("[data-push-denied]")
        expect(denied).to_be_visible()
        expect(denied).to_contain_text(DENIED_START)
        expect(subscribe).to_be_hidden()
        expect(tab.locator('button[type=button][data-action="push-permission"]')).to_be_hidden()
        # п. 2: подписки нет — в браузере, на портале (запрос не уходил, список пуст)
        assert not helpers_notify.has_push_subscription(tab), "после отказа в браузере есть подписка"
        assert pushes == [], "после отказа портал получил подписку"
        tab.goto("/me/notifications/")
        expect(tab.locator('[data-empty-state="devices"]')).to_contain_text(EMPTY_DEVICES)
        expect(tab.locator("ul[data-devices] li[data-device]")).to_have_count(0)
        expect(_push_cell(tab)).to_have_attribute("data-available", "0")


@helpers_notify.webpush_only
def test_e05_closed_tab_gets_push_with_text_without_number_and_subject_and_click_opens_notifications_page(
        admin_page, employee, webpush_context):
    """Сценарий 5, п. 3 (и сценарий 1, п. 10 для Web Push): вкладки закрыты, не тихие часы — при событии на
    устройство приходит уведомление «Новая заявка в вашей очереди» без номера и темы; нажатие ведёт на страницу
    уведомлений (FR-317, FR-328). Тема заявки длиннее 100 знаков."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (member,), queue_id, _queue_name = _team(page, employee)
    with _default_queue(page, old_id, queue_id), helpers_notify.channels_on(page, "webpush"):
        context = webpush_context()
        tab, _device = _subscribe(context, member)
        # дано: все страницы портала закрыты (вкладка устройства и страница сотрудника), контекст жив
        tab.close()
        _close_member(member)
        # когда: приходит заявка с темой длиннее 100 знаков (событие — после настройки, не сразу после подписки)
        word, subject = _new_mail(long_subject=True)
        assert len(subject) > 100, len(subject)
        # п. 3: сервис-воркер показал одно уведомление с текстом §15.2
        shown = helpers_notify.wait_service_worker_notifications(context, count=1, timeout=PUSH_WAIT)
        number = helpers_sd.ticket_number_by_subject(page, word)
        assert _titles(shown) == [EXTERNAL_SUBJECT], _titles(shown)
        item = shown[0]
        # п. 3 и сценарий 1, п. 10: ни номера, ни темы, ни слова темы в заголовке, тексте и данных
        everything = " ".join([item["title"], item.get("body") or "", item.get("tag") or "", str(item.get("data"))])
        assert f"#{number}" not in everything and word not in everything and subject[:30] not in everything, everything
        assert re.fullmatch(r"n-\d+", item["tag"] or ""), item["tag"]
        # п. 3: нажатие открывает страницу уведомлений (нажатие ОС Playwright не делает — решение 12: ссылка из данных)
        link = (item.get("data") or {}).get("url") or ""
        assert urlsplit(link).path == "/notifications/", link
        view = context.new_page()
        view.goto(link)
        expect(view.locator("[data-notify-list]")).to_be_visible()
        expect(view.locator("ul[data-notifications] li[data-notification]").filter(has_text=word)).to_have_count(1)


@helpers_notify.webpush_only
def test_e05_open_tab_shows_system_notification_and_no_web_push_reaches_device(
        admin_page, employee, webpush_context):
    """Сценарий 5, п. 4: у учётной записи есть действующее соединение живых обновлений (вкладка открыта) и не тихие
    часы — сотрудник видит системное уведомление во вкладке, а Web Push на устройство не уходит; после закрытия
    вкладки следующее событие приходит push-уведомлением (положительный контроль) (FR-331)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (member,), queue_id, queue_name = _team(page, employee)
    with _default_queue(page, old_id, queue_id), helpers_notify.channels_on(page, "webpush"):
        context = webpush_context()
        tab, _device = _subscribe(context, member)
        tab.close()
        _close_member(member)
        # дано: вкладка портала открыта, разрешение выдано, вызовы `Notification` записываются, соединение готово
        watcher = helpers_notify.open_tab(context, None, spy=True)
        assert helpers_notify.notification_permission(watcher) == "granted"
        # когда: событие
        word_a, subject_a = _new_mail("Не работает принтер")
        shown = helpers_notify.wait_notifications(watcher, count=1)
        number_a = helpers_sd.ticket_number_by_subject(page, word_a)
        # п. 4: системное уведомление во вкладке с текстом портала
        assert len(shown) == 1 and _norm(shown[0]["title"]) == _norm(_text_new(number_a, queue_name, subject_a)), shown
        # п. 4: Web Push на устройство не ушёл (вкладка открыта)
        assert helpers_notify.no_service_worker_notifications(context, observe=10), "push пришёл при открытой вкладке"
        # положительный контроль: вкладка закрыта — следующее событие приходит push-уведомлением, и оно одно
        watcher.close()
        _new_mail("Не работает монитор")
        shown_push = helpers_notify.wait_service_worker_notifications(context, count=1, timeout=PUSH_WAIT)
        assert _titles(shown_push) == [EXTERNAL_SUBJECT], _titles(shown_push)
        assert len(helpers_notify.service_worker_notifications(context)) == 1, "push по первому событию пришёл позже"


def test_e05_allow_browser_notifications_button_present_when_web_push_disabled_and_enables_tab_push(
        admin_page, employee, new_context):
    """Сценарий 5 (решение 34 задач), п. 5: Web Push выключен администратором — кнопка «Разрешить уведомления
    браузера» есть, кнопки подписки нет; нажатие запрашивает разрешение, и после согласия системные уведомления во
    вкладке работают (FR-320)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (member,), queue_id, queue_name = _team(page, employee)
    with _default_queue(page, old_id, queue_id), helpers_notify.channels_off(page, "webpush"):
        tab = _watch_ordinary(new_context, member, grant=False, counter=True)
        tab.goto("/me/notifications/")
        helpers_notify.wait_ws_open(tab)
        # п. 5: Web Push выключен, но кнопка разрешения видна, кнопки подписки нет
        expect(tab.locator('[data-section="push"]')).to_have_attribute("data-web-push", "off")
        button = tab.locator('button[type=button][data-action="push-permission"]')
        expect(button).to_have_text(BUTTON_ALLOW)
        expect(tab.locator('button[type=button][data-action="push-subscribe"]')).to_have_count(0)
        # п. 5: нажатие запрашивает разрешение; сотрудник соглашается (окно запроса Playwright не подтверждает)
        expect(button).to_be_visible()
        button.click()
        tab.wait_for_function("() => Number(sessionStorage.getItem('e2eRequests') || '0') >= 1")
        helpers_notify.grant_notifications(tab.context)
        tab.reload()
        helpers_notify.wait_ws_open(tab)
        assert helpers_notify.notification_permission(tab) == "granted"
        expect(button).to_be_hidden()
        # п. 5: push во вкладке работает без Web Push
        word, subject = _new_mail()
        shown = helpers_notify.wait_notifications(tab, count=1)
        number = helpers_sd.ticket_number_by_subject(page, word)
        assert len(shown) == 1 and _norm(shown[0]["title"]) == _norm(_text_new(number, queue_name, subject)), shown


def test_e05_push_disabled_by_admin_hides_button_shows_disabled_text_and_tab_push_still_works(
        admin_page, employee, new_context):
    """Сценарий 5, п. 5: Web Push выключен администратором — при открытии «Моих уведомлений» кнопки «Включить push на
    этом устройстве» нет, показано «Push при закрытой вкладке отключён администратором»; системное уведомление во
    вкладке работает (FR-336). При включённом Web Push кнопка есть (положительный контроль)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (member,), queue_id, queue_name = _team(page, employee)
    with _default_queue(page, old_id, queue_id), helpers_notify.channels_on(page, "webpush"):
        view = new_context(storage_state=helpers_notify.session_state(member)).new_page()
        view.goto("/me/notifications/")
        expect(view.locator('[data-section="push"]')).to_have_attribute("data-web-push", "on")
        expect(view.locator('button[type=button][data-action="push-subscribe"]')).to_have_count(1)
        expect(view.locator("[data-push-disabled-text]")).to_have_count(0)
        with helpers_notify.channels_off(page, "webpush"):
            view.goto("/me/notifications/")
            # п. 5: кнопки нет, показан текст «отключён администратором», столбец push недоступен с той же подсказкой
            expect(view.locator('[data-section="push"]')).to_have_attribute("data-web-push", "off")
            expect(view.locator('button[type=button][data-action="push-subscribe"]')).to_have_count(0)
            expect(view.locator("[data-push-disabled-text]")).to_contain_text(DISABLED_TEXT)
            cell = _push_cell(view)
            expect(cell).to_have_attribute("data-available", "0")
            expect(cell).to_have_attribute("data-reason", "channel_disabled")
            expect(cell.locator("[data-hint]")).to_contain_text(DISABLED_TEXT)
            view.close()
            # п. 5: push во вкладке работает
            tab = helpers_notify.open_watcher(new_context, member, grant=True, spy=True)
            word, subject = _new_mail()
            shown = helpers_notify.wait_notifications(tab, count=1)
            number = helpers_sd.ticket_number_by_subject(page, word)
            assert len(shown) == 1 and _norm(shown[0]["title"]) == _norm(_text_new(number, queue_name, subject)), shown


@helpers_notify.webpush_only
def test_e05_two_devices_removing_one_stops_push_to_it_and_other_still_gets_push(
        admin_page, employee, webpush_context):
    """Сценарий 5, п. 6: у сотрудника два устройства с подпиской (два профиля, вход в каждом) — он удаляет одно: на него
    push больше не уходит, на другое уходит (до удаления push приходит на оба) (FR-324)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (member,), queue_id, _queue_name = _team(page, employee)
    with _default_queue(page, old_id, queue_id), helpers_notify.channels_on(page, "webpush"):
        first, second = webpush_context(), webpush_context()
        tab_one, device_one = _device_via_login(first, member)
        tab_two, device_two = _device_via_login(second, member)
        assert device_one != device_two
        tab_one.goto("/me/notifications/")
        expect(tab_one.locator("ul[data-devices] li[data-device]")).to_have_count(2)
        tab_one.close()
        tab_two.close()
        _close_member(member)
        # дано: оба устройства получают push (положительный контроль того же пути)
        _new_mail("Не работает принтер")
        for context in (first, second):
            shown = helpers_notify.wait_service_worker_notifications(context, count=1, timeout=PUSH_WAIT)
            assert _titles(shown) == [EXTERNAL_SUBJECT], _titles(shown)
            helpers_notify.close_service_worker_notifications(context)
        # когда: сотрудник удаляет первое устройство из списка
        view = first.new_page()
        view.goto("/me/notifications/")
        row = _device_row(view, device_one)
        expect(row).to_have_count(1)
        row.locator('form[data-form="device-delete"] button[data-action="device-delete"]').click()
        expect(row).to_have_count(0)
        view.goto("/me/notifications/")
        expect(_device_row(view, device_one)).to_have_count(0)
        expect(_device_row(view, device_two)).to_have_count(1)
        view.close()
        # п. 6: следующее событие приходит на второе устройство, на первое — нет
        _new_mail("Не работает монитор")
        shown = helpers_notify.wait_service_worker_notifications(second, count=1, timeout=PUSH_WAIT)
        assert _titles(shown) == [EXTERNAL_SUBJECT], _titles(shown)
        # сразу, до 8 с наблюдения за первым: Chromium убирает показанное уведомление примерно через 9 с
        assert len(helpers_notify.service_worker_notifications(second)) == 1
        assert helpers_notify.no_service_worker_notifications(first, observe=8), "push пришёл на удалённое устройство"
        assert helpers_notify.service_worker_notifications(first) == []


@helpers_notify.webpush_only
def test_e05_push_service_answering_subscription_gone_removes_subscription_automatically(
        admin_page, employee, webpush_context):
    """Сценарий 5, п. 7 (решение 26 задач): подписку отзывают в самом браузере (`unsubscribe()`), затем приходит
    событие — настоящий push-сервис отвечает «подписки нет» (404 или 410), и портал удаляет подписку автоматически, а
    уведомление на портале остаётся (FR-332). Если push-сервис за время теста не ответил 404/410, это наблюдение
    для отчёта (решение 26): серверный тест ответов закрывает пункт."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (member,), queue_id, _queue_name = _team(page, employee)
    with _default_queue(page, old_id, queue_id), helpers_notify.channels_on(page, "webpush"):
        context = webpush_context()
        tab, device = _subscribe(context, member)
        tab.close()
        _close_member(member)
        # дано: подписка отозвана в браузере; на портале устройство ещё в списке
        assert _in_sw_page(context, lambda p: p.evaluate(UNSUBSCRIBE)) is True, "отписка в браузере не удалась"
        assert helpers_notify.has_push_subscription_ctx(context) is False
        # когда: событие
        word, _subject = _new_mail()
        # п. 7: портал получил отказ push-сервиса и удалил подписку (опрос списка устройств со страницы без присутствия)
        gone = _in_sw_page(context, lambda p: p.evaluate(WAIT_DEVICE_GONE, {"device": device, "ms": PUSH_WAIT * 1000}))
        if not gone:
            # решение 26: читаем запись «Доставка» и различаем ошибку портала и наблюдение за push-сервисом
            found = _delivery(member.email, word)
            outcomes = [(e["outcome"], e["code"]) for e in (found or {}).get("log", [])]
            if any(code in (404, 410) for _o, code in outcomes):
                raise AssertionError(f"push-сервис ответил 404/410, а подписка осталась (ошибка портала): {found}")
            if any(outcome == "ok" or (code is not None and 200 <= code < 300) for outcome, code in outcomes):
                pytest.xfail(f"наблюдение по решению 26: push-сервис не ответил 404/410 за {PUSH_WAIT} с")
            raise AssertionError(f"подписка не удалена за {PUSH_WAIT} с, push-сервис не принял push: {found}")
        # п. 7: уведомление на портале не потеряно, устройств у сотрудника нет
        view = context.new_page()
        expect(_notification_rows(view, word)).to_have_count(1)
        view.goto("/me/notifications/")
        expect(view.locator('[data-empty-state="devices"]')).to_be_visible()
        expect(view.locator("ul[data-devices] li[data-device]")).to_have_count(0)


@helpers_notify.webpush_only
def test_e05_open_tab_without_browser_permission_updates_only_bell_counter_no_system_notification_no_push(
        admin_page, employee, new_context, webpush_context):
    """Сценарий 5, п. 8: вкладка портала открыта, но браузер не разрешил системные уведомления — при событии
    обновляется только число на колокольчике: ни системного уведомления во вкладке, ни Web Push на устройство
    сотрудника; после закрытия вкладки следующее событие приходит push-уведомлением (положительный контроль)
    (FR-331)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (member,), queue_id, _queue_name = _team(page, employee)
    with _default_queue(page, old_id, queue_id), helpers_notify.channels_on(page, "webpush"):
        context = webpush_context()
        tab, _device = _subscribe(context, member)  # устройство сотрудника с подпиской
        tab.close()
        # дано: вкладка в другом контексте, разрешения браузера у неё нет (контекст без выдачи разрешения)
        watcher = helpers_notify.open_watcher(new_context, member, grant=False, spy=True)
        _close_member(member)
        assert helpers_notify.notification_permission(watcher) != "granted"
        before = helpers_notify.bell_count(watcher)
        # когда: событие
        _new_mail("Не работает принтер")
        # п. 8: число на колокольчике выросло, системного уведомления нет, push на устройство не ушёл
        helpers_notify.wait_bell_count(watcher, before + 1, timeout_ms=LONG_WAIT_MS)
        assert helpers_notify.no_notifications(watcher, observe_ms=5_000), "системное уведомление без разрешения браузера"
        assert helpers_notify.no_service_worker_notifications(context, observe=10), "push пришёл при открытой вкладке"
        # положительный контроль: вкладка закрыта — следующее событие приходит push-уведомлением, и оно одно
        watcher.close()
        _new_mail("Не работает монитор")
        shown = helpers_notify.wait_service_worker_notifications(context, count=1, timeout=PUSH_WAIT)
        assert _titles(shown) == [EXTERNAL_SUBJECT], _titles(shown)
        assert len(helpers_notify.service_worker_notifications(context)) == 1, "push по первому событию пришёл позже"


def test_e05_open_tab_in_quiet_hours_updates_only_bell_counter_without_system_notification(
        admin_page, employee, new_context):
    """Сценарий 5, п. 9: у сотрудника открыта вкладка (разрешение выдано) и тихие часы — при событии обновляется только
    число на колокольчике, системного уведомления нет; после перехода на «Без тихих часов» следующее событие
    показывается системным уведомлением (положительный контроль) (FR-329)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (member,), queue_id, queue_name = _team(page, employee)
    with _default_queue(page, old_id, queue_id):
        # дано: «Свои часы» (рабочие часы) заведомо не включают текущий московский момент: все семь дней
        hour = datetime.now(ZoneInfo("Europe/Moscow")).hour
        start, end = ("20:00", "22:00") if hour < 12 else ("02:00", "04:00")
        _set_quiet(member.page, "own", days=range(7), start=start, end=end)
        tab = helpers_notify.open_watcher(new_context, member, grant=True, spy=True)
        assert helpers_notify.notification_permission(tab) == "granted"
        before = helpers_notify.bell_count(tab)
        # когда: событие в тихие часы
        _new_mail("Не работает принтер")
        # п. 9: число выросло, системного уведомления во вкладке нет
        helpers_notify.wait_bell_count(tab, before + 1, timeout_ms=LONG_WAIT_MS)
        assert helpers_notify.no_notifications(tab, observe_ms=5_000), "системное уведомление в тихие часы"
        # положительный контроль: «Без тихих часов» — следующее событие показывается системным уведомлением
        _set_quiet(member.page, "none")
        word, subject = _new_mail("Не работает монитор")
        shown = helpers_notify.wait_notifications(tab, count=1)
        number = helpers_sd.ticket_number_by_subject(page, word)
        assert len(shown) == 1 and _norm(shown[0]["title"]) == _norm(_text_new(number, queue_name, subject)), shown


@helpers_notify.webpush_only
def test_e05_logout_on_device_removes_its_subscription_and_next_login_offers_push_again(
        admin_page, employee, webpush_context):
    """Сценарий 5, п. 10: сотрудник вышел из портала на этом устройстве — подписка этого устройства удалена, при
    следующем входе портал снова предлагает включить push (кнопка видна, устройств нет) (FR-324)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    (member,), _queue_id, _name = _team(page, employee)
    with helpers_notify.channels_on(page, "webpush"):
        context = webpush_context()
        tab, device = _device_via_login(context, member)
        tab.goto("/me/notifications/")
        expect(_device_row(tab, device)).to_have_count(1)
        # когда: выход на этом устройстве, затем вход снова
        helpers.sign_out(tab)
        helpers.sign_in(tab, member)
        tab.goto("/me/notifications/")
        # п. 10: подписка этого устройства удалена, портал снова предлагает включить push
        expect(_device_row(tab, device)).to_have_count(0)
        expect(tab.locator('[data-empty-state="devices"]')).to_contain_text(EMPTY_DEVICES)
        expect(tab.locator('[data-section="push"]')).to_have_attribute("data-web-push", "on")
        subscribe = tab.locator('button[type=button][data-action="push-subscribe"]')
        expect(subscribe).to_be_visible()
        expect(subscribe).to_have_text(BUTTON_SUBSCRIBE)
        # дополнение 27: подписка в самом браузере осталась, но признак с портала — «0», и кнопка видна
        expect(subscribe).to_have_attribute("data-device-subscribed", "0")
        assert helpers_notify.has_push_subscription_ctx(context), "подписка браузера после выхода пропала"
        # п. 10: предложение рабочее — повторная подписка проходит и даёт новую строку
        again = helpers_notify.enable_push_on_device(tab)
        assert again != device
        expect(_device_row(tab, again)).to_have_count(1)


@helpers_notify.webpush_only
def test_e05_same_browser_subscribed_by_other_account_removes_previous_subscription_of_first_account(
        admin_page, employee, new_context, webpush_context):
    """Сценарий 5, п. 11: в том же браузере подписывается другая учётная запись — прежняя подписка этого браузера у
    первой учётной записи удалена, у второй она есть (FR-324). Первая учётная запись из браузера не выходила."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    (first, second), _queue_id, _name = _team(page, employee, 2)  # «Новая заявка в моей очереди» видна только участнику
    with helpers_notify.channels_on(page, "webpush"):
        context = webpush_context()
        tab_first, device_first = _subscribe(context, first)
        expect(_device_row(tab_first, device_first)).to_have_count(1)
        # когда: в том же профиле браузера входит вторая учётная запись (без выхода первой: куки сняты) и подписывается
        tab_first.close()
        assert helpers_notify.has_push_subscription_ctx(context), "подписки нет в самом браузере"
        context.clear_cookies()
        tab_second = context.new_page()
        helpers.sign_in(tab_second, second)
        # дополнение 27: подписка браузера есть, но на портале у второй записи её нет — кнопка видна с «0»
        tab_second.goto("/me/notifications/")
        subscribe = tab_second.locator('button[type=button][data-action="push-subscribe"]')
        expect(subscribe).to_be_visible()
        expect(subscribe).to_have_attribute("data-device-subscribed", "0")
        device_second = helpers_notify.enable_push_on_device(tab_second)
        # п. 11: у второй учётной записи подписка есть, и она одна
        tab_second.goto("/me/notifications/")
        expect(_device_row(tab_second, device_second)).to_have_count(1)
        expect(tab_second.locator("ul[data-devices] li[data-device]")).to_have_count(1)
        # п. 11: у первой учётной записи (её сессия в другом контексте жива) прежней подписки больше нет
        view = new_context(storage_state=helpers_notify.session_state(first)).new_page()
        view.goto("/me/notifications/")
        expect(view.locator('[data-section="push"]')).to_have_attribute("data-web-push", "on")
        expect(_device_row(view, device_first)).to_have_count(0)
        expect(view.locator('[data-empty-state="devices"]')).to_contain_text(EMPTY_DEVICES)
        # п. 11: прежняя подписка удалена системой с причиной «перенесена» (журнал, § 6.12, объект — прежний владелец)
        sides = helpers_org.audit_sides(page, "notify.push_removed", object_id=first.id)
        assert len(sides) == 1 and "подписка перенесена на другую учётную запись" in " ".join(sides[0]), sides
