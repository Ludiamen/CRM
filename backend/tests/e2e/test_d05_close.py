"""T-3144: сценарий 5 — закрытие с решением, ответ в течение срока и позже, открытие заново (FR-205, FR-206,
FR-214, FR-231, FR-249, FR-251, FR-252, FR-256, FR-274, FR-288)."""
import re
import secrets

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_servicedesk import build_mail

# Арифметика сроков (срок открытия заново — `reopen_days`, по умолчанию 7; 6.11: `within_reopen_term` —
# `closed_at + reopen_days >= now`). Сдвиг `closed_at` назад на d суток: внутри срока при d < срока строго, снаружи при
# d > срока; ровно d = срок не берём — к моменту письма он уже снаружи. «3 дня» и «10 дней» вокруг срока 7 — как в
# сценарии; «год назад» — 400 суток (365+).
THREE_DAYS = 3
TEN_DAYS = 10
YEAR_AGO = 400


def _word() -> str:
    """Уникальное слово темы (доп. 41 (в)): не из одних цифр."""
    return f"t{secrets.token_hex(3)}"


def _message_id() -> str:
    return f"<{secrets.token_hex(8)}@client.test>"


def _norm(text: str) -> str:
    """Текст письма с пробелами и переводами строк, сжатыми в один пробел."""
    return " ".join(text.split())


def _addresses(entries) -> list:
    return [str(item.get("Address", "")).lower() for item in (entries or [])]


def _header(headers: dict, name: str) -> list:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return []


def _card(page, number: int):
    """Корень карточки заявки на открытой странице (13.3); при замене фрагмента HTMX находится заново."""
    return page.locator(f'[data-ticket-card][data-number="{number}"]')


def _form(page):
    form = page.locator('form[data-form="servicedesk-settings"]')
    expect(form).to_be_visible()
    return form


def _read_setting(page, name: str) -> int:
    """Число из поля `input[name=<name>]` формы настроек `/servicedesk/` (13.7)."""
    page.goto("/servicedesk/")
    return int(_form(page).locator(f"input[name={name}]").input_value())


def _set_setting(page, name: str, value: int) -> None:
    """Меняет одно число формы настроек (остальные поля остаются как есть), ждёт 302 и `[role=status]` (12.6)."""
    page.goto("/servicedesk/")
    form = _form(page)
    form.locator(f"input[name={name}]").fill(str(value))
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    assert not page.locator("[data-error], [role=alert][data-code]").count(), "настройка не принята"
    expect(page.locator("[role=status]").first).to_be_visible()


def _status_rows(page) -> list:
    """Справочник статусов (13.7): id, вид, «по умолчанию», «системное», архив, текст ячейки названия."""
    page.goto("/servicedesk/dictionaries/statuses/")
    rows = page.locator('table[data-dictionary="status"] tr[data-dictionary-row]')
    expect(rows.first).to_be_visible()
    found = []
    for row in rows.all():
        found.append({
            "id": row.get_attribute("data-id"),
            "archived": row.get_attribute("data-archived") == "true",
            "kind": row.locator('[data-cell="kind"]').inner_text().strip().lower(),
            "default": "по умолчанию" in row.locator('[data-cell="default"]').inner_text(),
            "system": row.locator("[data-system-mark]").count() > 0,
            "name": row.locator('[data-cell="name"]').inner_text(),
        })
    return found


def _new_ticket(page, mailpit, *, cc=()):
    """Заявка из письма корпоративного заявителя; ждёт подтверждение (чтобы письма по заявке шли по порядку).
    Возвращает (номер, адрес заявителя, тема, слово темы)."""
    word, sender = _word(), helpers_sd.requester_email()
    subject = f"Сбой {word}"
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], cc=list(cc), subject=subject,
                                  text=f"Описание сбоя {word}", message_id=_message_id()))
    number = helpers_sd.ticket_number_by_subject(page, word)
    helpers_sd.wait_letter(mailpit, number, "ticket.confirmation", to=sender)
    return number, sender, subject, word


def _requester_reply(sender: str, number: int, subject: str, text: str, *, extra_word: str = "") -> None:
    """Ответ заявителя в заявку: тема `Re: [#N] <тема>` (6.16, 10.2); `extra_word` — новое слово, по которому тест
    найдёт заявку, если она будет новой (по слову исходной темы нашлись бы две)."""
    tail = f" {extra_word}" if extra_word else ""
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=f"Re: [#{number}] {subject}{tail}",
                                  text=text, message_id=_message_id()))


def _take(page, number: int) -> None:
    """Взять заявку себе (администратор — участник любой очереди, 6.1): заявка «в работе»."""
    helpers_sd.open_ticket(page, number)
    _card(page, number).locator('form[data-form="ticket-take"] button[data-action="ticket-take"]').click()
    expect(_card(page, number)).to_have_attribute("data-kind", "in_progress")


def _open_close_dialog(page, number: int):
    helpers_sd.open_ticket(page, number)
    page.locator('a[data-action="ticket-close"]').click()
    dialog = page.locator('#dialog-root [data-dialog="ticket-close"]')
    expect(dialog).to_be_visible()
    return dialog


def _close(page, number: int, resolution: str) -> None:
    """Закрытие через диалог `ticket-close` со статусом по умолчанию (первый в выборе) и текстом решения."""
    dialog = _open_close_dialog(page, number)
    dialog.locator("textarea[name=resolution]").fill(resolution)
    dialog.locator("button[type=submit]").click()
    expect(_card(page, number)).to_have_attribute("data-kind", "closed")


def _expect_kind(page, number: int, kind: str) -> None:
    """Открывает карточку заново и ждёт её вид статуса."""
    helpers_sd.open_ticket(page, number)
    expect(_card(page, number)).to_have_attribute("data-kind", kind)


def _staff_queue_member(employee, admin_page, queue_id):
    """Сотрудник с уникальной частью ФИО, участник очереди (член узла-очереди, 6.1)."""
    token = secrets.token_hex(3)
    account = employee(full_name=f"Тест{token} Иванов Иван")
    helpers_sd.add_queue_member(admin_page, queue_id, [account.id], q=f"Тест{token}")
    return account, token


def test_d05_close_without_resolution_text_refused_asks_for_resolution(admin_page, mailpit):
    """Сценарий 5, п. 1: заявка в работе, статус вида «закрыта» без текста решения — портал не закрывает и просит
    написать решение (отказ `resolution_required`, слово «решение»); заявка остаётся в работе, письма о закрытии нет
    (FR-249)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    number, sender, subject, word = _new_ticket(page, mailpit)
    _take(page, number)
    # когда: исполнитель открывает диалог закрытия и отправляет решение из одних пробелов (поле `required` в
    # браузере пустым не пропустит, а сервис считает текст после обрезки — доп. 27 (б), 29)
    dialog = _open_close_dialog(page, number)
    dialog.locator("textarea[name=resolution]").fill("   ")
    dialog.locator("button[type=submit]").click()
    # п. 1: отказ с кодом `resolution_required` и словом «решение» (14.1)
    alert = page.locator('[role=alert][data-code="resolution_required"]')
    expect(alert.first).to_be_visible()
    assert "решение" in alert.first.inner_text().lower()
    # заявка не закрыта: вид «в работе», нет ни решения, ни «закрыл»; письма «закрыта» нет
    helpers_sd.open_ticket(page, number)
    expect(_card(page, number)).to_have_attribute("data-kind", "in_progress")
    expect(_card(page, number).locator('[data-field="resolution"]')).to_have_count(0)
    expect(_card(page, number).locator('[data-field="closed-by"]')).to_have_count(0)
    assert helpers_sd.no_letter(mailpit, number, "ticket.closed", wait=15)


def test_d05_close_with_resolution_sets_date_text_and_mails_requester_and_participants(admin_page, mailpit):
    """Сценарий 5, п. 2: закрытие с текстом решения — заявка закрыта (вид «закрыта», в списке закрытых), в карточке
    решение и кто закрыл, в ленте событие закрытия со временем; заявитель и участник получили письмо «закрыта с
    решением» с текстом (§ 10.4) (FR-249, FR-256)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    participant = helpers_sd.requester_email("cc")
    number, sender, subject, word = _new_ticket(page, mailpit, cc=[participant])
    reopen_days = _read_setting(page, "reopen_days")
    _take(page, number)
    resolution = f"Заменили картридж {word}"
    # когда: закрытие с решением подтверждено
    _close(page, number, resolution)
    card = helpers_sd.open_ticket(page, number)
    # п. 2: закрыта; решение и «закрыл» в карточке (зацепки даты закрытия контракт не задаёт — дата видна в ленте)
    expect(card).to_have_attribute("data-kind", "closed")
    expect(card.locator('[data-field="resolution"]')).to_contain_text(resolution)
    expect(card.locator('[data-field="closed-by"]')).to_contain_text("Закрыл:")
    event = card.locator('ol[data-feed] li[data-kind="event"][data-event="closed"]')
    expect(event).to_have_count(1)
    assert resolution in event.inner_text()
    expect(event.locator("time[data-at]")).to_have_count(1)  # время закрытия (по Москве)
    page.goto("/tickets/?preset=closed&q=" + word)
    expect(page.locator(f'#tickets-grid tr[data-ticket="{number}"][data-kind="closed"]')).to_have_count(1)
    # п. 2: письмо заявителю, участник в копии, текст по § 10.4, заголовки § 10.2
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.closed", to=sender)
    text = _norm(letter["Text"])
    assert f"Ваша заявка № {number} закрыта. Решение: {resolution}." in text
    assert f"ответьте на это письмо в течение {reopen_days} дней — заявка откроется заново." in text
    assert participant in _addresses(letter.get("Cc"))
    headers = helpers_sd.letter_headers(mailpit, letter["ID"])
    assert [v.lower() for v in _header(headers, "Auto-Submitted")] == ["auto-generated"]


def test_d05_requester_reply_after_three_days_reopens_with_previous_assignee_or_none_and_reopened_letter(
        admin_page, mailpit, employee):
    """Сценарий 5, п. 3: заявка закрыта 3 дня назад, заявитель отвечает письмом с номером — «в работе», в той же
    очереди; ответственный прежний, если он ещё участник очереди (заявка A), иначе без ответственного (заявка B,
    ответственного убрали из очереди); письмо «открыта заново» (FR-251, FR-256)."""
    page = admin_page
    queue_id, queue_name = helpers_sd.ensure_ready(page)
    staff, token = _staff_queue_member(employee, page, queue_id)
    tickets = []
    for _ in range(2):
        number, sender, subject, word = _new_ticket(page, mailpit)
        helpers_sd.open_ticket(staff.page, number)
        _card(staff.page, number).locator('form[data-form="ticket-take"] button[data-action="ticket-take"]').click()
        expect(_card(staff.page, number)).to_have_attribute("data-kind", "in_progress")
        _close(page, number, f"Решено {word}")
        helpers_sd.backdate("ticket", number, "closed_at", THREE_DAYS)  # 3 < 7: внутри срока
        tickets.append((number, sender, subject))
    # ветвь A: ответственный ещё участник очереди — остаётся прежним
    number, sender, subject = tickets[0]
    _requester_reply(sender, number, subject, "Не помогло")
    card = helpers_sd.open_ticket(page, number)
    expect(card).to_have_attribute("data-kind", "in_progress")
    assert queue_name in helpers_sd.field_text(card, "queue")
    assert token in helpers_sd.field_text(card, "assignee")
    expect(card.locator('ol[data-feed] li[data-entry][data-kind="incoming"]')).to_have_count(2)
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.reopened", to=sender)
    assert f"Заявка № {number} снова в работе." in _norm(letter["Text"])
    # ветвь B: ответственного убрали из очереди — после ответа заявки без ответственного (кто именно снял —
    # сверка или открытие, доп. 22 — тест не различает)
    page.goto(f"/structure/{queue_id}/")
    helpers_org.remove_member(page, staff.id)
    page.wait_for_load_state()
    expect(helpers_org.member_row(page, staff.id)).to_have_count(0)
    number, sender, subject = tickets[1]
    _requester_reply(sender, number, subject, "Не помогло")
    card = helpers_sd.open_ticket(page, number)
    expect(card).to_have_attribute("data-kind", "in_progress")
    assert queue_name in helpers_sd.field_text(card, "queue")
    assert helpers_sd.field_text(card, "assignee") == "не назначен"
    expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "true")
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.reopened", to=sender)
    assert f"Заявка № {number} снова в работе." in _norm(letter["Text"])


def test_d05_requester_reply_after_ten_days_creates_continuation_ticket_old_stays_closed(admin_page, mailpit):
    """Сценарий 5, п. 4: заявка закрыта 10 дней назад при сроке открытия 7 — ответ заявителя создаёт новую заявку
    «продолжение заявки #N» с обычным подтверждением; старая остаётся закрытой (FR-251, FR-205)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    reopen_days = _read_setting(page, "reopen_days")  # по умолчанию 7; 10 суток — снаружи, запас — от срока
    number, sender, subject, word = _new_ticket(page, mailpit)
    _take(page, number)
    _close(page, number, f"Решено {word}")
    helpers_sd.backdate("ticket", number, "closed_at", max(TEN_DAYS, reopen_days + 3))
    # когда: заявитель отвечает
    _requester_reply(sender, number, subject, "Проблема вернулась")
    # старая закрыта, ссылка на продолжение; новую находим по этой ссылке (по слову темы нашлись бы обе)
    old = helpers_sd.open_ticket(page, number)
    link = old.locator('a[data-field="continuation"]')
    expect(link).to_have_count(1)
    new_number = int(re.search(r"/tickets/(\d+)/", link.get_attribute("href")).group(1))
    assert new_number != number
    expect(old).to_have_attribute("data-kind", "closed")
    expect(old.locator('ol[data-feed] li[data-entry][data-kind="incoming"]')).to_have_count(1)  # письмо не дописано
    # новая заявка: «продолжение заявки #N» и обычное подтверждение с номером
    new = helpers_sd.open_ticket(page, new_number)
    previous = new.locator('a[data-field="previous"]')
    expect(previous).to_have_attribute("href", f"/tickets/{number}/")
    assert f"#{number}" in previous.inner_text()
    assert helpers_sd.field_text(new, "requester-email").lower() == sender
    letter = helpers_sd.wait_letter(mailpit, new_number, "ticket.confirmation", to=sender)
    assert f"Ваша заявка принята под номером {new_number}." in _norm(letter["Text"])


def test_d05_corporate_stranger_mail_to_closed_ticket_creates_new_without_reopening(admin_page, mailpit):
    """Сценарий 5, п. 5: письмо в закрытую заявку от корпоративного адреса, не заявителя и не участника, создаёт
    новую заявку, закрытая не открывается (FR-214, FR-251)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    number, sender, subject, word = _new_ticket(page, mailpit)
    _take(page, number)
    _close(page, number, f"Решено {word}")  # закрыта только что: для заявителя это внутри срока
    stranger, word2 = helpers_sd.requester_email("other"), _word()
    # когда: письмо с номером закрытой заявки приходит от постороннего корпоративного адреса
    _requester_reply(stranger, number, subject, f"Тоже не работает {word2}", extra_word=word2)
    new_number = helpers_sd.ticket_number_by_subject(page, word2)  # слово2 есть только у новой заявки
    assert new_number != number
    new = helpers_sd.open_ticket(page, new_number)
    assert helpers_sd.field_text(new, "requester-email").lower() == stranger
    # закрытая не открыта: вид «закрыта», письмо не дописано, события «открыта заново» нет, письма «открыта» нет
    old = helpers_sd.open_ticket(page, number)
    expect(old).to_have_attribute("data-kind", "closed")
    expect(old.locator('ol[data-feed] li[data-entry][data-kind="incoming"]')).to_have_count(1)
    expect(old.locator('li[data-kind="event"][data-event="reopened"]')).to_have_count(0)
    helpers_sd.wait_letter(mailpit, new_number, "ticket.confirmation", to=stranger)  # письмо идёт позже
    assert helpers_sd.no_letter(mailpit, number, "ticket.reopened")


def test_d05_queue_member_reopens_year_old_closed_ticket_requester_gets_reopened_letter(
        admin_page, mailpit, employee):
    """Сценарий 5, п. 6: заявка закрыта год назад, участник очереди (не администратор) нажимает «Открыть заново» —
    она открывается, заявитель получает письмо «открыта заново» (FR-252)."""
    page = admin_page
    queue_id, queue_name = helpers_sd.ensure_ready(page)
    staff, token = _staff_queue_member(employee, page, queue_id)
    number, sender, subject, word = _new_ticket(page, mailpit)
    _close(page, number, f"Решено {word}")
    helpers_sd.backdate("ticket", number, "closed_at", YEAR_AGO)
    # когда: участник очереди открывает карточку закрытой заявки и нажимает «Открыть заново»
    card = helpers_sd.open_ticket(staff.page, number)
    expect(card).to_have_attribute("data-kind", "closed")
    helpers.submit(card.locator('form[data-form="ticket-reopen"]'))
    expect(_card(staff.page, number)).to_have_attribute("data-kind", "in_progress")
    # п. 6: заявка открыта, в ленте событие открытия «вручную», заявитель получил письмо
    helpers_sd.open_ticket(staff.page, number)
    event = _card(staff.page, number).locator('li[data-kind="event"][data-event="reopened"]')
    expect(event).to_have_count(1)
    assert "открыта заново" in event.inner_text()
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.reopened", to=sender)
    assert f"Заявка № {number} снова в работе." in _norm(letter["Text"])


def test_d05_changed_reopen_term_applies_to_next_reply_and_change_in_journal(admin_page, mailpit):
    """Сценарий 5, п. 7: срок открытия заново изменён — следующая закрытая заявка получает ответ по новому сроку
    (закрыта 1 сутки назад — открывается, 4 суток — продолжение), запись об изменении есть в журнале «было/стало»
    (FR-274, FR-288)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    before = _read_setting(page, "reopen_days")  # читаем до try, возвращаем в finally
    new_term = 2 if before != 2 else 3
    inside, outside = new_term - 1, new_term + 2  # 1 < 2 < 4; при прежнем сроке 7 четыре суток были бы внутри
    inside_n, inside_sender, inside_subject, inside_word = _new_ticket(page, mailpit)
    outside_n, outside_sender, outside_subject, outside_word = _new_ticket(page, mailpit)
    for number, days, word in ((inside_n, inside, inside_word), (outside_n, outside, outside_word)):
        _close(page, number, f"Решено {word}")
        helpers_sd.backdate("ticket", number, "closed_at", days)
    try:
        _set_setting(page, "reopen_days", new_term)
        # п. 7: запись об изменении в журнале: было — прежнее число, стало — новое
        # (числа строк не сравниваем: страница журнала — 50 строк; смотрим новейшую запись объекта `servicedesk`, 9.2)
        sides = helpers_org.audit_sides(page, "servicedesk.settings_changed", object_id="1")
        assert sides, "записи об изменении настроек нет"
        was, became = sides[0]
        assert "срок открытия заново" in was and str(before) in was
        assert "срок открытия заново" in became and str(new_term) in became
        # следующие ответы идут по новому сроку
        _requester_reply(inside_sender, inside_n, inside_subject, "Не помогло")
        _expect_kind(page, inside_n, "in_progress")
        _requester_reply(outside_sender, outside_n, outside_subject, "Не помогло")
        old = helpers_sd.open_ticket(page, outside_n)
        expect(old.locator('a[data-field="continuation"]')).to_have_count(1)
        expect(old).to_have_attribute("data-kind", "closed")
    finally:
        _set_setting(page, "reopen_days", before)


def test_d05_manual_close_offers_closed_statuses_default_resolved_without_auto_closed(admin_page, mailpit):
    """Сценарий 5, п. 8: форма ручного закрытия предлагает статусы вида «закрыта» (первым — по умолчанию, «Решена»),
    системного «Закрыта автоматически» нет, статусов других видов нет (FR-206, FR-249)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    rows = _status_rows(page)
    closed_ids = [r["id"] for r in rows if r["kind"] == "закрыта" and not r["archived"]]
    default_id = [r["id"] for r in rows if r["kind"] == "закрыта" and r["default"]][0]
    system_ids = [r["id"] for r in rows if r["system"]]
    assert system_ids, "в справочнике нет системного статуса «Закрыта автоматически»"
    number, sender, subject, word = _new_ticket(page, mailpit)
    dialog = _open_close_dialog(page, number)
    options = dialog.locator("select[name=status] option")
    values = [o.get_attribute("value") for o in options.all()]
    # п. 8: первым — статус по умолчанию вида «закрыта»; только неархивные статусы этого вида; системного нет
    assert values[0] == default_id
    assert set(values) == set(closed_ids) - set(system_ids)  # все неархивные статусы вида «закрыта», кроме системного
    assert "Решена" in options.first.inner_text()  # начальный статус по умолчанию (2.1)
    assert not set(values) & set(system_ids)
    default_name_cell = [r["name"] for r in rows if r["id"] == default_id][0]
    assert options.first.inner_text().strip() in default_name_cell  # первым — название статуса по умолчанию
    # отмена ничего не меняет: заявка осталась открытой
    dialog.locator("button[data-dialog-cancel]").click()
    expect(dialog).to_have_count(0)
    _expect_kind(page, number, "new")


def test_d05_closed_ticket_of_removed_queue_reopens_in_default_queue_with_event(admin_page, mailpit):
    """Сценарий 5, п. 9: закрытая заявка, очередь которой больше не очередь, открывается в очереди по умолчанию
    с событием «очередь: было → стало, причина — очередь снята»: и по ответу заявителя (заявка A), и по кнопке
    «Открыть заново» (заявка B) (FR-251, FR-252, FR-231)."""
    page = admin_page
    default_id, default_name = helpers_sd.ensure_ready(page)
    second_name = helpers_org.unique_name("queue")
    second_id = helpers_org.create_unit(page, second_name)
    helpers_sd.mark_queue(page, second_id)  # очередь не по умолчанию
    made = []
    for _ in range(2):
        number, sender, subject, word = _new_ticket(page, mailpit)
        helpers_sd.open_ticket(page, number)
        page.locator('a[data-action="ticket-transfer"]').click()
        dialog = page.locator('#dialog-root [data-dialog="ticket-transfer"]')
        expect(dialog).to_be_visible()
        dialog.locator("select[name=queue]").select_option(value=str(second_id))
        dialog.locator("button[type=submit]").click()
        expect(_card(page, number).locator('[data-field="queue"]')).to_contain_text(second_name)
        _close(page, number, f"Решено {word}")  # закрыты обе: открытых заявок в очереди не остаётся
        made.append((number, sender, subject))
    # очередь перестаёт быть очередью: диалог снятия отметки (12.6, доп. 12) и подтверждение
    page.goto(f"/servicedesk/queues/?unmark={second_id}")
    unmark = page.locator('[data-dialog="queue-unmark"]')
    expect(unmark).to_be_visible()
    unmark.locator("button[type=submit]").click()
    expect(unmark).to_have_count(0)
    helpers_sd.open_queues(page)
    expect(helpers_org.unit_li(page, second_id).first).to_have_attribute("data-queue", "false")
    # заявка A: ответ заявителя в пределах срока
    number, sender, subject = made[0]
    _requester_reply(sender, number, subject, "Не помогло")
    # заявка B: «Открыть заново» участником (администратором)
    number_b = made[1][0]
    card_b = helpers_sd.open_ticket(page, number_b)
    helpers.submit(card_b.locator('form[data-form="ticket-reopen"]'))
    page.wait_for_load_state()
    for ticket_number in (made[0][0], number_b):
        card = helpers_sd.open_ticket(page, ticket_number)
        expect(card).to_have_attribute("data-kind", "in_progress")
        queue_text = helpers_sd.field_text(card, "queue")
        assert default_name in queue_text and second_name not in queue_text
        event = card.locator('ol[data-feed] li[data-kind="event"][data-event="queue_changed"]')
        expect(event).to_have_count(1)
        text = event.inner_text()
        assert "очередь снята" in text
        assert second_name in text and default_name in text  # «было → стало»
        assert text.index(second_name) < text.index(default_name)
