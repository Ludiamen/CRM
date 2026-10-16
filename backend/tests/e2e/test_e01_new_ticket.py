"""T-4140: сценарий 1 — новая заявка в очереди: колокольчик, системное уведомление во вкладке, письмо через срок
(FR-301, FR-303, FR-307, FR-308, FR-310, FR-314, FR-315, FR-316, FR-317, FR-318, FR-320, FR-327, NFR-301).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-004.md):
- каждый тест заводит свою очередь, своих сотрудников и свои заявки (имена уникальны), очередь по умолчанию
  на время теста меняется на свою и возвращается в `finally` (письмо заявителя попадает в очередь по умолчанию);
- тихие часы: у каждого, чьё письмо проверяется, режим «Без тихих часов» (письмо уходит в любое время суток,
  иначе вне рабочего времени доставка ушла бы в сводку); системное уведомление вкладки тоже не показывается в
  тихие часы (§ 6.7, поле `show`), поэтому режим ставится и в тесте с системным уведомлением;
- срок письма — `helpers_notify.tick(shift=PAST_ANY_TERM)`: сдвиг 121 минута больше верхней границы срока письма
  (120 минут, § 6.5), поэтому письмо просрочено при любом допустимом сроке на стенде (по умолчанию 15 минут); сдвиг
  идёт по всему стенду, поэтому письма ищутся поиском Mailpit по адресу получателя и шаблону `notify.item`;
- число на колокольчике сравнивается с числом до события: на общем стенде так надёжнее (вход в новом контексте даёт
  уведомление «Вход с нового устройства»).
"""
import contextlib
import json
import re
import secrets
import time
from email.header import Header

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_notify, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_servicedesk import build_mail

NEW_IN_QUEUE = "servicedesk.new_in_queue"
SD_ALL = "servicedesk.all"
PAST_ANY_TERM = 121  # минут: больше верхней границы срока письма (120 минут, § 6.5) — письмо просрочено при любом сроке
EXTERNAL_SUBJECT = "Новая заявка в вашей очереди"  # тема письма и текст внешних каналов (§ 15.2, FR-317)
REF_RE = re.compile(r"/tickets/(\d+)/$")
LONG_WAIT_MS = 15_000  # ожидание числа там, где срок 2 с (NFR-301) не проверяется


# --- Общие помощники файла ----------------------------------------------------------------------------

def _word() -> str:
    """Уникальное слово темы: буква и шесть шестнадцатеричных знаков (не из одних цифр, иначе поиск списка принял бы
    его за номер заявки; CONTRACT-003, доп. 41 (в))."""
    return f"t{secrets.token_hex(3)}"


def _tag() -> str:
    """Общее начало фамилий сотрудников теста: по нему «Добавить сотрудников» находит всех сразу."""
    return "Очередь" + secrets.token_hex(3)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _staff(employee, tag: str, index: int):
    return employee(full_name=f"{tag}{index} Петр Петрович")


def _queue(page, prefix: str = "Поддержка", *, kind: str = "department", parent_id=None) -> tuple:
    """Новый узел `org`, отмеченный очередью: `(номер, название)`."""
    name = helpers_org.unique_name(prefix)
    unit_id = helpers_org.create_unit(page, name, kind=kind, parent_id=parent_id)
    helpers_sd.mark_queue(page, unit_id)
    return unit_id, name


def _members(page, queue_id, accounts, tag: str) -> None:
    """Прямые участники узла-очереди. У отдела — режим «параллельно» (человек может состоять в нескольких узлах),
    у команды выбора режима нет."""
    page.goto(f"/structure/{queue_id}/")
    mode = "concurrent" if page.locator("#unit-card select[name=mode]").count() else None
    note = helpers_org.add_members(page, queue_id, [a.id for a in accounts], q=tag, mode=mode)
    assert "уже участник" not in note, note
    helpers_org.open_structure(page, queue_id)
    for account in accounts:
        expect(helpers_org.member_row(page, account.id)).to_have_count(1)


def _remove(page, queue_id, account) -> None:
    """Меню «…» → «Удалить из отдела»: сотрудник перестаёт быть участником очереди."""
    page.goto(f"/structure/{queue_id}/")
    helpers_org.remove_member(page, account.id)
    page.wait_for_load_state()
    expect(helpers_org.member_row(page, account.id)).to_have_count(0)


@contextlib.contextmanager
def _default_queue(page, old_id, queue_id):
    """Очередь по умолчанию на время теста — своя (письмо попадает в неё); прежняя возвращается в `finally`.
    Внутри блока тест может сам менять очередь по умолчанию (`helpers_sd.set_default_queue`)."""
    helpers_sd.set_default_queue(page, queue_id)
    try:
        yield
    finally:
        helpers_sd.set_default_queue(page, old_id)


def _prefs(page, *, email: bool = True) -> None:
    """«Мои уведомления» сотрудника (`account.page`): ячейка «Почта» вида «Новая заявка в моей очереди» и режим
    «Без тихих часов»; ждёт сообщение страницы и проверяет, что значение сохранено (§ 13.2, § 14.3). Звать, когда
    сотрудник уже участник очереди (иначе строки вида в таблице нет)."""
    page.goto("/me/notifications/")
    form = page.locator('form[data-form="notify-prefs"]')
    expect(form).to_be_visible()
    cell = form.locator(f'tr[data-notify-kind="{NEW_IN_QUEUE}"] td[data-channel="email"] '
                        f'input[type=checkbox][name="cell"][value="{NEW_IN_QUEUE}:email"]')
    expect(cell).to_have_count(1)
    cell.set_checked(email)
    form.locator('fieldset[data-quiet] input[type=radio][name="quiet_mode"][value="none"]').check()
    with page.expect_navigation():
        form.locator('button[type=submit][data-action="save-prefs"]').click()
    page.wait_for_load_state()
    assert not helpers.alert_text(page), f"настройки не сохранены: {helpers.alert_text(page)}"
    expect(page.locator("[role=status]").first).to_be_visible()
    expect(cell).to_be_checked(checked=email)
    expect(page.locator('fieldset[data-quiet] input[name="quiet_mode"][value="none"]')).to_be_checked()


def _send_mail(subject: str, word: str) -> None:
    """Письмо заявителя в ящик заявок и сразу разбор: заявка создана в очереди по умолчанию, без ответственного.
    Тема записывается заново через `email.header.Header`: генератор `policy.default` при переносе длинной нелатинской
    темы выносит пробел между словами RFC 2047, и при чтении он теряется (T-4260)."""
    raw = build_mail(from_addr=helpers_sd.requester_email(), to=[MAILBOX], subject=subject,
                     text=f"Нужна помощь {word}", message_id=f"<{secrets.token_hex(8)}@client.test>")
    head, sep, body = raw.partition(b"\r\n\r\n")
    folded = Header(subject, "utf-8", header_name="Subject").encode(linesep="\r\n")
    head = re.sub(rb"(?im)^Subject:[^\r\n]*(?:\r\n[ \t][^\r\n]*)*",
                  lambda _: b"Subject: " + folded.encode("ascii"), head)
    helpers_sd.deliver(head + sep + body)


def _new_mail(title: str = "Не работает принтер") -> tuple:
    """Письмом создаёт заявку: `(слово, тема)`; номер — `_number` (после ожиданий, чтобы не терять время NFR-301)."""
    word = _word()
    subject = f"{title} {word}"
    _send_mail(subject, word)
    return word, subject


def _number(page, word: str) -> int:
    return helpers_sd.ticket_number_by_subject(page, word)


def _text_new(number, queue_name: str, subject: str) -> str:
    """Текст уведомления «Новая заявка в моей очереди» (§ 15.1, FR-316)."""
    return f"Новая заявка #{number} в очереди «{queue_name}»: {subject}"


def _count_now(page) -> int:
    """Число колокольчика при готовом соединении (решение E21): нужно как отсчёт «до события»."""
    helpers_notify.wait_ws_open(page)
    return helpers_notify.bell_count(page)


def _wait_plus(page, base: int, step: int = 1, *, timeout_ms: int = LONG_WAIT_MS) -> int:
    """Ждёт, пока число колокольчика станет `base + step`; возвращает новое число."""
    helpers_notify.wait_bell_count(page, base + step, timeout_ms=timeout_ms)
    return base + step


def _rows(page, word: str):
    """Открывает `/notifications/` и возвращает строки списка, в тексте которых есть слово темы. Список только
    читает (не отмечает прочитанным)."""
    page.goto("/notifications/")
    expect(page.locator("[data-notify-list]")).to_be_visible()
    return page.locator("ul[data-notifications] li[data-notification]").filter(has_text=word)


def _row_text(row) -> str:
    return _norm(row.locator('[data-field="text"]').inner_text())


def _row_texts(page, word: str) -> list:
    """Тексты всех строк списка со словом темы."""
    rows = _rows(page, word)
    return [_norm(t) for t in rows.locator('[data-field="text"]').all_inner_texts()]


def _expect_text(page, word: str, expected: str, *, unread: str = "1") -> None:
    """В списке `/notifications/` ровно одна строка со словом, её текст равен `expected`, отметка — `unread`."""
    rows = _rows(page, word)
    expect(rows).to_have_count(1)
    assert _row_text(rows) == _norm(expected)
    expect(rows).to_have_attribute("data-unread", unread)


def _expect_none(page, word: str) -> None:
    """В списке `/notifications/` нет ни одной строки со словом темы."""
    expect(_rows(page, word)).to_have_count(0)


def _item_mails(mailpit, to: str) -> list:
    """Короткие записи писем `notify.item` на адрес `to` в Mailpit (поиск по адресу, не список из 50 писем)."""
    return helpers_notify.find_mails(mailpit, to, helpers_notify.TEMPLATE_ITEM)


def _tick() -> None:
    """Срок письма прошёл (`e2e_notify_tick --shift 121`): ожидающие доставки стенда сдвинуты, обход выполнен.
    Ожидающая доставка есть хотя бы у получателя этого теста (стенд один, чужие тоже сдвигаются). Только первый обход
    теста: повторный обход после него ничего не сдвигает (доставки уже отправлены) — там `helpers_notify.tick()`."""
    result = helpers_notify.tick(shift=PAST_ANY_TERM)
    assert result["shifted"] >= 1, result


def _guest(new_context):
    """Страница без входа со своим адресом клиента (TEST-NET-3): у теста свой порог открытой формы (CONTRACT-003, 7.4)."""
    ip = f"203.0.113.{secrets.randbelow(250) + 2}"
    return new_context(extra_http_headers={"X-Forwarded-For": ip}).new_page()


def _category(page, queue_id, *, default_assignee=None) -> tuple:
    """Категория с уникальным названием, показываемая на открытой форме: `(номер, название)`."""
    name = f"Принтер {secrets.token_hex(3)}"
    page.goto("/servicedesk/dictionaries/categories/new/")
    form = page.locator('form[data-form="dictionary"]')
    expect(form).to_be_visible()
    form.locator("input[name=name]").fill(name)
    form.locator("input[name=order]").fill("50")
    form.locator("select[name=queue]").select_option(value=str(queue_id))
    if default_assignee is not None:
        form.locator("select[name=default_assignee]").select_option(value=str(default_assignee))
    form.locator("input[type=checkbox][name=on_form]").set_checked(True)
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    refusal = page.locator("[data-error], [role=alert][data-code]")
    assert not refusal.count(), f"категория не создана: {refusal.first.get_attribute('data-code')}"
    row = page.locator("tr[data-dictionary-row]").filter(has=page.locator('[data-cell="name"]', has_text=name))
    expect(row).to_have_count(1)
    return row.get_attribute("data-id"), name


def _form_ticket(guest, category_name: str) -> tuple:
    """Заявка открытой формой `/request/`: `(слово, тема)`; ждёт страницу «заявка принята»."""
    word = _word()
    subject = f"Заявка с формы {word}"
    guest.goto("/request/")
    form = guest.locator('form[data-form="request"]')
    expect(form).to_be_visible()
    form.locator("input[name=email]").fill(helpers_sd.requester_email())
    form.locator("input[name=name]").fill("Тестов Тест Тестович")
    form.locator("select[name=client_unit]").select_option(value="")
    form.locator("select[name=category]").select_option(label=category_name)
    form.locator("input[name=subject]").fill(subject)
    form.locator("textarea[name=text]").fill(f"Не работает устройство {word}")
    form.locator("input[name=consent]").set_checked(True)
    form.locator("button[type=submit]").click()
    guest.wait_for_url(re.compile(r"/request/done/"))
    return word, subject


def _phone_ticket(page, category_id, queue_id) -> tuple:
    """Заявка по звонку формой `/tickets/new/` без «Взять себе»: `(слово, тема)`. Заявка остаётся в очереди категории
    без ответственного (CONTRACT-003, 13.6)."""
    word = _word()
    subject = f"Звонок {word}"
    page.goto("/tickets/new/")
    form = page.locator('form[data-form="ticket-new"]')
    expect(form).to_be_visible()
    old_fields = form.locator("input[name=name]").element_handle()
    with page.expect_response(lambda r: r.request.method == "POST"
                              and r.url.split("?")[0].endswith("/tickets/new/requester/")):
        form.locator("input[name=email]").fill(helpers_sd.requester_email("call"))
        form.locator("input[name=email]").press("Tab")
    page.wait_for_function("el => !el.isConnected", arg=old_fields)
    form.locator("input[name=name]").fill(f"Кузнецов-{word} Павел")
    old_queue = form.locator("select[name=queue]").element_handle()
    with page.expect_response(lambda r: r.request.method == "GET" and "/tickets/new/queue/" in r.url):
        form.locator("select[name=category]").select_option(value=str(category_id))
    page.wait_for_function("el => !el.isConnected", arg=old_queue)
    expect(form.locator("select[name=queue]")).to_have_value(str(queue_id))
    take = form.locator("input[name=take]")
    expect(take).to_be_enabled()
    take.set_checked(False)
    form.locator("select[name=source]").select_option(label="Телефон")
    form.locator("input[name=subject]").fill(subject)
    form.locator("textarea[name=text]").fill(f"Позвонили по телефону {word}")
    form.locator("button[type=submit]").click()
    page.wait_for_url(REF_RE)
    return word, subject


def _transfer(page, number: int, queue_id, queue_name: str) -> None:
    """«Передать в очередь» из карточки через диалог; заявка остаётся видимой тому, кто передаёт (администратор или
    участник обеих очередей), поэтому ответ — карточка с новой очередью."""
    card = helpers_sd.open_ticket(page, number)
    card.locator('a[data-action="ticket-transfer"]').click()
    dialog = page.locator('#dialog-root [data-dialog="ticket-transfer"]')
    expect(dialog).to_be_visible()
    dialog.locator("select[name=queue]").select_option(str(queue_id))
    dialog.locator("button[type=submit]").click()
    expect(dialog).to_have_count(0)
    expect(card.locator('[data-field="queue"]')).to_contain_text(queue_name)


def _badge(page) -> int:
    """Число у пункта «Заявки» главного меню (`span[data-menu-badge]`; нуля в разметке нет)."""
    page.goto("/tickets/")
    expect(page.locator("[data-tickets-list]")).to_be_visible()
    badge = page.locator('#main-menu a.menu-item[href="/tickets/"] span[data-menu-badge]')
    return int(badge.inner_text().strip()) if badge.count() else 0


def _make_role(page, name: str, codes) -> str:
    """Своя роль с правами `codes` (`/roles/new/`); возвращает её номер."""
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
    """Личная роль из формы карточки сотрудника (срез 001)."""
    page.goto(f"/staff/{user_id}/")
    form = page.locator('form[action$="/roles/"]')
    form.locator(f'input[name=roles][value="{role_id}"]').check()
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()


# --- Тесты --------------------------------------------------------------------------------------------------

def test_e01_new_ticket_bell_grows_by_one_within_two_seconds_for_every_direct_member_in_two_contexts(
        admin_page, employee, new_context):
    """Сценарий 1, п. 1: письмо заявителя создало заявку без ответственного в очереди — у каждого прямого участника
    узла (совместителя, руководителя и заместителя) в своём контексте браузера появилось уведомление «Новая заявка
    #N в очереди «…»: Тема», число колокольчика выросло на 1 не позже 2 с (FR-301, FR-308, FR-318, NFR-301)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    combiner, head, deputy = (_staff(employee, tag, i) for i in (1, 2, 3))
    queue_id, queue_name = _queue(page)
    other_id, _other = _queue(page, "Другая")
    _members(page, queue_id, [combiner, head, deputy], tag)
    _members(page, other_id, [combiner], tag)  # совместитель: состоит ещё в одном узле
    helpers_org.set_marks(page, queue_id, "heads", [head.id])
    helpers_org.set_marks(page, queue_id, "deputies", [deputy.id])
    with _default_queue(page, old_id, queue_id):
        # дано: у каждого открыта вкладка в своём контексте, соединения готовы (решение E21)
        watchers = helpers_notify.open_watchers(new_context, [combiner, head, deputy])
        before = [helpers_notify.bell_count(p) for p in watchers]
        # когда: письмо заявителя создаёт заявку без ответственного
        word, subject = _new_mail()
        # п. 1: у каждого число выросло на 1 за общие 2 с (окно одно на всех зрителей), без перезагрузки страницы
        deadline = time.monotonic() + 2
        for p, base in zip(watchers, before):
            helpers_notify.wait_bell_count(p, base + 1, timeout_ms=max(1, int((deadline - time.monotonic()) * 1000)))
        number = _number(page, word)
        # п. 1: текст уведомления — «Новая заявка #N в очереди «…»: Тема», строка непрочитанная
        for p in watchers:
            _expect_text(p, word, _text_new(number, queue_name, subject))


def test_e01_open_tab_with_permission_shows_system_notification_with_same_text_and_click_opens_ticket(
        admin_page, employee, new_context):
    """Сценарий 1, п. 2: у сотрудника открыта вкладка и браузер разрешает уведомления портала — при приходе
    уведомления во вкладке показано системное уведомление браузера с тем же текстом; нажатие открывает заявку
    (FR-320)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, queue_name = _queue(page)
    _members(page, queue_id, [member], tag)
    _prefs(member.page)  # тихих часов нет: системное уведомление во вкладке не скрывается
    with _default_queue(page, old_id, queue_id):
        # дано: вкладка открыта, разрешение выдано контексту, вызовы `Notification` записываются
        tab = helpers_notify.open_watcher(new_context, member, grant=True, spy=True)
        assert helpers_notify.notification_permission(tab) == "granted"
        assert helpers_notify.notifications(tab) == []
        before = helpers_notify.bell_count(tab)
        # когда: приходит уведомление
        word, subject = _new_mail()
        shown = helpers_notify.wait_notifications(tab, count=1)
        number = _number(page, word)
        expected = _text_new(number, queue_name, subject)
        # п. 2: показано одно системное уведомление с тем же текстом, что на портале, и ссылкой в данных
        assert len(shown) == 1, shown
        assert _norm(shown[0]["title"]) == _norm(expected), shown
        assert isinstance(shown[0]["data"], dict) and shown[0]["data"].get("url"), shown
        helpers_notify.wait_bell_count(tab, before + 1, timeout_ms=LONG_WAIT_MS)
        # п. 2: нажатие открывает заявку в этой вкладке
        helpers_notify.click_notification(tab)
        tab.wait_for_url(re.compile(rf"/tickets/{number}/$"))
        expect(tab.locator(f'[data-ticket-card][data-number="{number}"]')).to_be_visible()
        # тот же текст стоит в списке портала; открытое уведомление прочитано
        _expect_text(tab, word, expected, unread="0")


def test_e01_unread_after_term_in_working_hours_sends_one_email_to_work_address_with_same_text_and_ticket_link_in_mailpit(
        admin_page, employee, new_context, mailpit):
    """Сценарий 1, п. 3: включён канал «Почта» для вида «Новая заявка в моей очереди» и уведомление не прочитано —
    когда проходит срок письма в рабочее время, на рабочий адрес уходит одно письмо с тем же текстом и ссылкой на
    заявку (FR-327)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, queue_name = _queue(page)
    _members(page, queue_id, [member], tag)
    _prefs(member.page, email=True)  # «Почта» включена, тихих часов нет (рабочее время в любое время суток)
    with _default_queue(page, old_id, queue_id):
        watcher = helpers_notify.open_watcher(new_context, member)
        before = helpers_notify.bell_count(watcher)
        word, subject = _new_mail()
        _wait_plus(watcher, before)
        number = _number(page, word)
        expected = _text_new(number, queue_name, subject)
        _expect_text(watcher, word, expected)  # уведомление не прочитано
        assert not _item_mails(mailpit, member.email), "письмо ушло до срока"
        # когда: проходит срок письма
        _tick()
        # п. 3: на рабочий адрес пришло письмо с тем же текстом и ссылкой
        letter = helpers_notify.wait_item_mail(mailpit, member.email)
        assert letter["Subject"] == EXTERNAL_SUBJECT  # тема — внешний текст вида, без номера и темы (§ 10.1, FR-317)
        assert _norm(expected) in _norm(letter["Text"])
        link = helpers_notify.open_link_in(letter)
        # п. 3: письмо одно — повторный обход (без сдвига: сдвигать уже нечего) второго не рассылает
        helpers_notify.tick()
        assert helpers_notify.no_item_mail(mailpit, member.email, seen=[letter["ID"]], wait=6)
        assert len(_item_mails(mailpit, member.email)) == 1
        # п. 3: ссылка из письма ведёт на заявку
        watcher.goto(link)
        watcher.wait_for_url(re.compile(rf"/tickets/{number}/$"))
        expect(watcher.locator(f'[data-ticket-card][data-number="{number}"]')).to_be_visible()


def test_e01_opened_notification_or_ticket_before_term_sends_no_email(admin_page, employee, new_context, mailpit):
    """Сценарий 1, п. 4: сотрудник открыл уведомление (из списка) или карточку заявки (по адресу) до истечения срока —
    когда срок проходит, письма ему нет; не открывший получает письмо (FR-307, FR-327)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    by_notification, by_ticket, silent = (_staff(employee, tag, i) for i in (1, 2, 3))
    queue_id, queue_name = _queue(page)
    _members(page, queue_id, [by_notification, by_ticket, silent], tag)
    for account in (by_notification, by_ticket, silent):
        _prefs(account.page, email=True)
    with _default_queue(page, old_id, queue_id):
        tabs = helpers_notify.open_watchers(new_context, [by_notification, by_ticket, silent])
        before = [helpers_notify.bell_count(p) for p in tabs]
        word, subject = _new_mail()
        for p, base in zip(tabs, before):
            _wait_plus(p, base)
        number = _number(page, word)
        # дано: первый открывает уведомление из списка, второй — карточку заявки, третий ничего не открывает
        first_tab, second_tab, third_tab = tabs
        rows = _rows(first_tab, word)
        expect(rows).to_have_count(1)
        rows.locator("a[data-open]").click()
        first_tab.wait_for_url(re.compile(rf"/tickets/{number}/$"))
        helpers_sd.open_ticket(second_tab, number)
        # уведомления обоих прочитаны, третьего — нет
        _expect_text(first_tab, word, _text_new(number, queue_name, subject), unread="0")
        _expect_text(second_tab, word, _text_new(number, queue_name, subject), unread="0")
        _expect_text(third_tab, word, _text_new(number, queue_name, subject), unread="1")
        # когда: срок проходит
        _tick()
        # п. 4: не открывший получил письмо (обход отработал), открывшим писем нет
        helpers_notify.wait_item_mail(mailpit, silent.email)
        assert helpers_notify.no_item_mail(mailpit, by_notification.email, wait=10), "письмо после открытия уведомления"
        assert helpers_notify.no_item_mail(mailpit, by_ticket.email, wait=1), "письмо после открытия карточки заявки"


def test_e01_form_phone_without_take_and_transfer_to_queue_notify_direct_members_same_way(
        admin_page, employee, new_context):
    """Сценарий 1, п. 5: заявка создана формой, заведена исполнителем по звонку без «Взять себе» или передана в
    очередь без ответственного — прямым участникам узла-очереди приходит то же уведомление «Новая заявка в моей
    очереди» (FR-308)."""
    page = admin_page
    helpers_sd.ensure_ready(page)  # письмо третьего пути попадёт в очередь по умолчанию, не в эту
    tag = _tag()
    first, second = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, queue_name = _queue(page)
    _members(page, queue_id, [first, second], tag)
    category_id, category_name = _category(page, queue_id)
    tabs = helpers_notify.open_watchers(new_context, [first, second])
    base = [helpers_notify.bell_count(p) for p in tabs]
    guest = _guest(new_context)
    # путь 1: открытая форма
    word, subject = _form_ticket(guest, category_name)
    for p, b in zip(tabs, base):
        _wait_plus(p, b)
    number = _number(page, word)
    expected_form = _text_new(number, queue_name, subject)
    # путь 2: исполнитель завёл заявку по звонку, «Взять себе» снято
    word_phone, subject_phone = _phone_ticket(page, category_id, queue_id)
    number_phone = int(REF_RE.search(page.url).group(1))
    for p, b in zip(tabs, base):
        _wait_plus(p, b, 2)
    expected_phone = _text_new(number_phone, queue_name, subject_phone)
    # путь 3: заявка письмом попала в другую очередь (по умолчанию) и передана в эту без ответственного
    word_move, subject_move = _new_mail()
    number_move = _number(page, word_move)
    _transfer(page, number_move, queue_id, queue_name)
    for p, b in zip(tabs, base):
        _wait_plus(p, b, 3)
    expected_move = _text_new(number_move, queue_name, subject_move)
    # п. 5: у обоих участников по одному такому же уведомлению на каждый путь
    for p in tabs:
        _expect_text(p, word, expected_form)
        _expect_text(p, word_phone, expected_phone)
        _expect_text(p, word_move, expected_move)


def test_e01_default_assignee_gets_assigned_not_new_ticket_and_kept_assignee_after_transfer_gets_nothing(
        admin_page, employee, new_context):
    """Сценарий 1, п. 6: у заявки при создании сразу есть ответственный по умолчанию категории — уведомления «Новая
    заявка в моей очереди» нет, ответственный получает «Вам назначена заявка»; при передаче в очередь, где
    ответственный остался участником, нового уведомления нет ни у него, ни у участников новой очереди (FR-308,
    FR-310)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    default_man, kept, other = (_staff(employee, tag, i) for i in (1, 2, 3))
    first_id, first_name = _queue(page, "Первая")
    second_id, second_name = _queue(page, "Вторая")
    _members(page, first_id, [default_man, kept], tag)
    _members(page, second_id, [kept, other], tag)  # kept состоит в обеих очередях
    category_id, category_name = _category(page, first_id, default_assignee=default_man.id)
    with _default_queue(page, old_id, first_id):
        tabs = helpers_notify.open_watchers(new_context, [default_man, kept, other])
        base_default, base_kept, base_other = (helpers_notify.bell_count(p) for p in tabs)
        tab_default, tab_kept, tab_other = tabs
        # когда: открытая форма создаёт заявку, у категории ответственный по умолчанию
        guest = _guest(new_context)
        word_a, subject_a = _form_ticket(guest, category_name)
        _wait_plus(tab_default, base_default)
        number_a = _number(page, word_a)
        # п. 6: ответственный получил «Вам назначена заявка #N: Тема», а не «Новая заявка в моей очереди»
        _expect_text(tab_default, word_a, f"Вам назначена заявка #{number_a}: {subject_a}")
        # п. 6: второй участник очереди уведомления не получил
        assert helpers_notify.bell_count(tab_kept) == base_kept
        _expect_none(tab_kept, word_a)
        # дано: заявка письмом в первой очереди назначена участнику двух очередей
        word_b, subject_b = _new_mail()
        _wait_plus(tab_default, base_default, 2)  # «Новая заявка» по письму (без ответственного)
        number_b = _number(page, word_b)
        answer = helpers_org.direct_post(page, f"/tickets/{number_b}/assign/", {"assignee": str(kept.id)})
        assert answer.status == 302, f"назначение заявки #{number_b} не удалось: {answer.status}"
        _wait_plus(tab_kept, base_kept, 2)  # «Новая заявка» по письму и «Вам назначена заявка» от администратора
        # когда: заявку передают во вторую очередь, где ответственный тоже участник
        _transfer(page, number_b, second_id, second_name)
        # контроль: письмо в пустую вторую очередь даёт уведомление обоим участникам — значит, передача отработана
        helpers_sd.set_default_queue(page, second_id)
        word_c, subject_c = _new_mail()
        _wait_plus(tab_other, base_other)
        number_c = _number(page, word_c)
        # п. 6: у участника новой очереди после передачи уведомления нет — только контрольное
        assert helpers_notify.bell_count(tab_other) == base_other + 1
        _expect_none(tab_other, word_b)
        _expect_text(tab_other, word_c, _text_new(number_c, second_name, subject_c))
        # п. 6: оставшийся ответственный нового уведомления не получил: у него два уведомления по заявке, обе из первой
        # очереди, и контрольное
        _wait_plus(tab_kept, base_kept, 3)
        texts = _row_texts(tab_kept, word_b)
        assert sorted(texts) == sorted([_text_new(number_b, first_name, subject_b),
                                        f"Вам назначена заявка #{number_b}: {subject_b}"]), texts
        assert all(f"«{second_name}»" not in t for t in texts), texts


def test_e01_actor_who_created_or_transferred_ticket_gets_nothing_others_get_notification(
        admin_page, employee, new_context):
    """Сценарий 1, п. 7: исполнитель сам завёл заявку без ответственного или сам передал её в другую очередь —
    ему уведомления нет, остальным участникам — есть (FR-315)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    actor, colleague = _staff(employee, tag, 1), _staff(employee, tag, 2)
    first_id, first_name = _queue(page, "Первая")
    second_id, second_name = _queue(page, "Вторая")
    _members(page, first_id, [actor], tag)
    _members(page, second_id, [actor, colleague], tag)
    category_id, _category_name = _category(page, second_id)
    with _default_queue(page, old_id, first_id):
        tab_actor, tab_colleague = helpers_notify.open_watchers(new_context, [actor, colleague])
        base_actor, base_colleague = helpers_notify.bell_count(tab_actor), helpers_notify.bell_count(tab_colleague)
        # когда: исполнитель сам заводит заявку без «Взять себе» во второй очереди
        word_new, subject_new = _phone_ticket(actor.page, category_id, second_id)
        number_new = int(REF_RE.search(actor.page.url).group(1))
        # п. 7: коллеге уведомление пришло, заводившему — нет
        _wait_plus(tab_colleague, base_colleague)
        _expect_text(tab_colleague, word_new, _text_new(number_new, second_name, subject_new))
        assert helpers_notify.bell_count(tab_actor) == base_actor
        _expect_none(tab_actor, word_new)
        # когда: письмо создаёт заявку в первой очереди, исполнитель передаёт её во вторую
        word_move, subject_move = _new_mail()
        _wait_plus(tab_actor, base_actor)  # участник первой очереди получил «Новая заявка» по письму
        number_move = _number(page, word_move)
        _transfer(actor.page, number_move, second_id, second_name)
        # п. 7: коллега получил уведомление о переданной заявке, передавший — нет (у него одно, из первой очереди)
        _wait_plus(tab_colleague, base_colleague, 2)
        _expect_text(tab_colleague, word_move, _text_new(number_move, second_name, subject_move))
        # открытие карточки при передаче отметило его уведомление по заявке прочитанным (§ 6.8, T-4124): нового
        # непрочитанного нет — число исходное
        assert helpers_notify.bell_count(tab_actor) == base_actor
        assert _row_texts(tab_actor, word_move) == [_norm(_text_new(number_move, first_name, subject_move))]


def test_e01_former_member_gets_no_notification_and_old_link_after_access_loss_leads_to_refusal(
        admin_page, employee, new_context):
    """Сценарий 1, п. 8: сотрудник перестал быть участником очереди до события — уведомления у него нет; если он
    потерял доступ после получения уведомления, ссылка на заявку ведёт на обычный отказ (FR-314)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    former, loses_later = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, queue_name = _queue(page)
    _members(page, queue_id, [former, loses_later], tag)
    _remove(page, queue_id, former)  # перестал быть участником до события
    with _default_queue(page, old_id, queue_id):
        tab_former, tab_member = helpers_notify.open_watchers(new_context, [former, loses_later])
        base_former, base_member = helpers_notify.bell_count(tab_former), helpers_notify.bell_count(tab_member)
        word, subject = _new_mail()
        _wait_plus(tab_member, base_member)
        number = _number(page, word)
        # п. 8: у бывшего участника уведомления нет (контроль — получил оставшийся участник)
        assert helpers_notify.bell_count(tab_former) == base_former
        _expect_none(tab_former, word)
        # п. 8: у оставшегося уведомление есть; его ссылка — адрес открытия уведомления
        rows = _rows(tab_member, word)
        expect(rows).to_have_count(1)
        assert _row_text(rows) == _norm(_text_new(number, queue_name, subject))
        href = rows.locator("a[data-open]").get_attribute("href")
        assert re.fullmatch(r"/notifications/\d+/open/", href), href
        # когда: он теряет доступ (удалён из очереди) и идёт по старой ссылке
        _remove(page, queue_id, loses_later)
        answer = tab_member.goto(href)
        # п. 8: обычный отказ — карточки заявки нет, ответ 404
        assert answer is not None and answer.status == 404, answer.status if answer else None
        assert re.search(rf"/tickets/{number}/$", tab_member.url), tab_member.url
        expect(tab_member.locator("[data-ticket-card]")).to_have_count(0)


def test_e01_email_channel_off_sends_no_email_and_portal_notification_stays(
        admin_page, employee, new_context, mailpit):
    """Сценарий 1, п. 9: у сотрудника выключен канал «Почта» для этого вида — когда проходит срок, письма нет, а
    уведомление на портале остаётся (FR-303, FR-327)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    mail_off, mail_on = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, queue_name = _queue(page)
    _members(page, queue_id, [mail_off, mail_on], tag)
    _prefs(mail_off.page, email=False)
    _prefs(mail_on.page, email=True)  # контроль: письмо ему приходит
    with _default_queue(page, old_id, queue_id):
        tab_off, tab_on = helpers_notify.open_watchers(new_context, [mail_off, mail_on])
        base_off, base_on = helpers_notify.bell_count(tab_off), helpers_notify.bell_count(tab_on)
        word, subject = _new_mail()
        _wait_plus(tab_off, base_off)
        _wait_plus(tab_on, base_on)
        number = _number(page, word)
        expected = _text_new(number, queue_name, subject)
        # когда: проходит срок
        _tick()
        # п. 9: письмо получил только тот, у кого «Почта» включена
        helpers_notify.wait_item_mail(mailpit, mail_on.email)
        assert helpers_notify.no_item_mail(mailpit, mail_off.email, wait=10), "письмо при выключенной «Почте»"
        # п. 9: уведомление на портале осталось, непрочитанное
        _expect_text(tab_off, word, expected)
        assert helpers_notify.bell_count(tab_off) == base_off + 1


def _chat_id() -> int:
    """Уникальный номер чата `fakebots` для теста: служба одна на круг, сообщения выбираются по своему чату."""
    return secrets.randbelow(900_000_000) + 100_000_000


def _expect_external_cells(page) -> None:
    """Ячейки «Telegram» и «MAX» вида «Новая заявка в моей очереди» после привязки доступны и включены (§ 14.3; по
    умолчанию вид включён во всех внешних каналах, § 3.2)."""
    page.goto("/me/notifications/")
    for channel in helpers_notify.BOT_CHANNELS:
        cell = page.locator(f'tr[data-notify-kind="{NEW_IN_QUEUE}"] td[data-channel="{channel}"] '
                            f'input[type=checkbox][name="cell"][value="{NEW_IN_QUEUE}:{channel}"]')
        expect(cell).to_have_count(1)
        expect(cell).to_be_checked()


def _button_url(channel: str, message: dict) -> str:
    """Адрес кнопки внешнего сообщения: Telegram — `reply_markup.inline_keyboard[0][0].url`, MAX —
    `attachments[0].payload.buttons[0][0].url` (§ 5.2, § 15.2)."""
    if channel == "telegram":
        markup = message["reply_markup"]
        markup = json.loads(markup) if isinstance(markup, str) else markup
        return markup["inline_keyboard"][0][0]["url"]
    return message["attachments"][0]["payload"]["buttons"][0][0]["url"]


def test_e01_subject_over_100_chars_cut_on_portal_and_email_and_external_channels_get_text_and_link_only(
        admin_page, employee, new_context, mailpit):
    """Сценарий 1, п. 10: тема заявки длиннее 100 символов — на портале и в письме тема обрезана до 100 символов
    (99 знаков и «…»); тема письма — внешний текст вида без номера и темы; в Telegram и MAX (учебная служба
    `fakebots`) уходят только текст «Новая заявка в вашей очереди» и ссылка в кнопке (на `/notifications/`), без
    номера и темы ни в тексте, ни где-либо в сообщении (FR-316, FR-317, NFR-312). Web Push с длинной темой проверяет
    T-4144 (тест закрытой вкладки): здесь Web Push не проверяется."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, queue_name = _queue(page)
    _members(page, queue_id, [member], tag)
    word = _word()
    # хвост темы (после 99-го знака) неповторим: иначе «хвоста нет» не проверить — тема из повторов (T-4260)
    subject = f"{word} " + "Длинная тема заявки " * 7 + f"конец {word}"
    assert 100 < len(subject) <= 255 and subject[98] != " " and subject == _norm(subject)
    cut = subject[:99] + "…"
    bots = helpers_notify.fakebots()  # без сброса: сообщения своего теста — по своему chat_id
    chats = {"telegram": _chat_id(), "max": _chat_id()}
    # каналы включает администратор на время теста (возврат в `finally`); токены ботов на стенде ставит T-4159
    with helpers_notify.channels_on(page, "telegram", "max"):
        # дано: оба бота привязаны кодом (до минуты уходит на пробуждение опроса включённого канала, § 5.4)
        for channel, chat in chats.items():
            helpers_notify.bind_channel(member.page, bots, channel, chat)
        _prefs(member.page, email=True)
        _expect_external_cells(member.page)
        with _default_queue(page, old_id, queue_id):
            tab = helpers_notify.open_watcher(new_context, member)
            before = helpers_notify.bell_count(tab)
            _send_mail(subject, word)
            _wait_plus(tab, before)
            number = _number(page, word)
            # заявка хранит тему целиком
            card = helpers_sd.open_ticket(page, number)
            assert _norm(helpers_sd.field_text(card, "subject")) == subject
            # п. 10: на портале тема обрезана до 100 знаков: первые 99 и «…»
            expected = _text_new(number, queue_name, cut)
            _expect_text(tab, word, expected)
            assert len(cut) == 100 and subject[99:] not in expected
            # п. 10: в Telegram и MAX — только внешний текст и ссылка в кнопке; доставка идёт сразу, без срока
            for channel, chat in chats.items():
                found = helpers_notify.wait_sent(bots, channel, chat_id=chat, text_has=EXTERNAL_SUBJECT)
                assert len(found) == 1, f"{channel}: сообщений «{EXTERNAL_SUBJECT}» в свой чат {len(found)}"
                message = found[0]
                assert message["text"] == EXTERNAL_SUBJECT, f"{channel}: текст {message['text']!r}"
                dump = json.dumps(message, ensure_ascii=False)
                for forbidden in (word, "Длинная", f"#{number}", f"/tickets/{number}", queue_name):
                    assert forbidden not in dump, f"{channel}: в сообщении есть {forbidden!r}"
                url = _button_url(channel, message)
                assert url.endswith("/notifications/"), f"{channel}: адрес кнопки оканчивается не на /notifications/"
            # когда: проходит срок письма
            _tick()
            # п. 10: в письме тот же обрезанный текст; хвоста темы нет; тема письма — внешний текст без номера и темы
            letter = helpers_notify.wait_item_mail(mailpit, member.email)
            body = _norm(letter["Text"])
            assert _norm(expected) in body
            assert subject[99:] not in body and subject not in body
            assert letter["Subject"] == EXTERNAL_SUBJECT
            helpers_notify.open_link_in(letter)


def test_e01_head_of_parent_node_and_all_tickets_holder_get_no_notification_but_see_ticket_in_list_and_counter(
        admin_page, employee, new_context):
    """Сценарий 1, п. 11: заявка в очереди «Поддержка» вложенного узла без ответственного — уведомления «Новая заявка
    в моей очереди» нет у руководителя вышестоящего узла и у держателя права «Все заявки», если они не входят в сам
    узел; заявка видна им в списке «Без ответственного» и в счётчике пункта «Заявки» (FR-308)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    worker, head, holder = (_staff(employee, tag, i) for i in (1, 2, 3))
    dept_id = helpers_org.create_unit(page, helpers_org.unique_name("Сопровождение"))
    team_id, team_name = _queue(page, "Поддержка", kind="team", parent_id=dept_id)
    _members(page, dept_id, [head], tag)
    helpers_org.set_marks(page, dept_id, "heads", [head.id])  # руководитель вышестоящего узла, не участник команды
    _members(page, team_id, [worker], tag)
    role_id = _make_role(page, helpers_org.unique_name("Диспетчер"), [SD_ALL])
    _grant_role(page, holder.id, role_id)  # держатель права «Все заявки», не участник команды
    badge_head, badge_holder = _badge(head.page), _badge(holder.page)
    with _default_queue(page, old_id, team_id):
        tab_worker, tab_head, tab_holder = helpers_notify.open_watchers(new_context, [worker, head, holder])
        base_worker, base_head, base_holder = (helpers_notify.bell_count(p) for p in (tab_worker, tab_head, tab_holder))
        word, subject = _new_mail()
        _wait_plus(tab_worker, base_worker)  # контроль: участник команды получил
        number = _number(page, word)
        _expect_text(tab_worker, word, _text_new(number, team_name, subject))
        # п. 11: у руководителя вышестоящего узла и держателя «Все заявки» уведомления нет
        assert helpers_notify.bell_count(tab_head) == base_head
        assert helpers_notify.bell_count(tab_holder) == base_holder
        _expect_none(tab_head, word)
        _expect_none(tab_holder, word)
        # п. 11: заявка видна обоим в списке «Без ответственного» и в счётчике пункта «Заявки»
        for account, badge_before in ((head, badge_head), (holder, badge_holder)):
            account.page.goto(f"/tickets/?preset=unassigned&q={word}")
            expect(account.page.locator(f'#tickets-grid tr[data-ticket="{number}"]')).to_have_count(1)
            assert _badge(account.page) >= badge_before + 1


def test_e01_ticket_taken_by_other_or_access_lost_before_term_sends_no_email_and_portal_notification_stays(
        admin_page, employee, new_context, mailpit):
    """Сценарий 1, п. 12: уведомление не прочитано, а за срок письма заявку взял другой участник очереди или
    сотрудник потерял доступ — письмо не уходит: портал перед отправкой заново проверяет, что у заявки нет
    ответственного и сотрудник её видит; на портале уведомление остаётся (FR-327)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    loses, taker, stays = (_staff(employee, tag, i) for i in (1, 2, 3))
    queue_id, queue_name = _queue(page)
    _members(page, queue_id, [loses, taker, stays], tag)
    _prefs(loses.page, email=True)
    _prefs(taker.page, email=False)  # взявший письмо не получает ни в каком случае: не мешает проверке
    _prefs(stays.page, email=True)
    with _default_queue(page, old_id, queue_id):
        tab_loses, tab_stays = helpers_notify.open_watchers(new_context, [loses, stays])
        base_loses, base_stays = helpers_notify.bell_count(tab_loses), helpers_notify.bell_count(tab_stays)
        # заявка 1: участники получили уведомление, её берёт другой участник очереди
        word_taken, subject_taken = _new_mail()
        _wait_plus(tab_loses, base_loses)
        _wait_plus(tab_stays, base_stays)
        number_taken = _number(page, word_taken)
        card = helpers_sd.open_ticket(taker.page, number_taken)
        card.locator('form[data-form="ticket-take"] button[data-action="ticket-take"]').click()
        expect(card).to_have_attribute("data-kind", "in_progress")
        # заявка 2: остаётся без ответственного, но первый участник теряет доступ (удалён из очереди)
        word_lost, subject_lost = _new_mail()
        _wait_plus(tab_loses, base_loses, 2)
        _wait_plus(tab_stays, base_stays, 2)
        number_lost = _number(page, word_lost)
        _remove(page, queue_id, loses)
        # заявка 3 (контроль): без ответственного, её видит оставшийся участник
        word_open, subject_open = _new_mail()
        _wait_plus(tab_stays, base_stays, 3)
        number_open = _number(page, word_open)
        # когда: проходит срок письма
        _tick()
        # п. 12: оставшийся участник получил письма только по заявкам без ответственного (2 и 3), по взятой (1) нет
        first = helpers_notify.wait_item_mail(mailpit, stays.email)
        second = helpers_notify.wait_item_mail(mailpit, stays.email, seen=[first["ID"]])
        bodies = [_norm(first["Text"]), _norm(second["Text"])]
        assert sum(word_lost in b for b in bodies) == 1 and sum(word_open in b for b in bodies) == 1, bodies
        assert not any(word_taken in b for b in bodies), bodies
        assert helpers_notify.no_item_mail(mailpit, stays.email, seen=[first["ID"], second["ID"]], wait=6)
        # п. 12: потерявший доступ писем не получил (ни по взятой, ни по оставшейся без ответственного)
        assert helpers_notify.no_item_mail(mailpit, loses.email, wait=10), "письмо после потери доступа"
        # п. 12: на портале уведомления остались непрочитанными — у потерявшего доступ и у не получившего письма
        _expect_text(tab_loses, word_taken, _text_new(number_taken, queue_name, subject_taken))
        _expect_text(tab_loses, word_lost, _text_new(number_lost, queue_name, subject_lost))
        _expect_text(tab_stays, word_taken, _text_new(number_taken, queue_name, subject_taken))
        _expect_text(tab_stays, word_open, _text_new(number_open, queue_name, subject_open))
