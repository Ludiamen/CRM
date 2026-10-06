"""T-3144: сценарий 6 — заявитель молчит, заявка закрывается сама (FR-208, FR-209, FR-244, FR-250, FR-251, FR-256,
FR-274)."""
import secrets
import time

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_org import eicar_bytes
from tests.support_servicedesk import build_mail

# Арифметика сроков (срок автозакрытия — `autoclose_days`, по умолчанию 7; 6.11: закрывает, если `waiting_since <=
# now - autoclose_days`, то есть при сдвиге d >= срока; на границе d == срок к запуску задания уже «после срока»).
# Поэтому берём `срок - 1` (не закрывает) и `срок + 1` (закрывает): 6 и 8 при сроке 7, 2 и 4 при сроке 3. Сдвиг
# `backdate` накопительный (8.2: назад от сохранённого значения, пустое — от now): «срок - 1», затем ещё 2 суток —
# итого «срок + 1».


def _word() -> str:
    return f"t{secrets.token_hex(3)}"


def _message_id() -> str:
    return f"<{secrets.token_hex(8)}@client.test>"


def _norm(text: str) -> str:
    return " ".join(text.split())


def _addresses(entries) -> list:
    return [str(item.get("Address", "")).lower() for item in (entries or [])]


def _header(headers: dict, name: str) -> list:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return []


def _card(page, number: int):
    return page.locator(f'[data-ticket-card][data-number="{number}"]')


def _form(page):
    form = page.locator('form[data-form="servicedesk-settings"]')
    expect(form).to_be_visible()
    return form


def _read_setting(page, name: str) -> int:
    page.goto("/servicedesk/")
    return int(_form(page).locator(f"input[name={name}]").input_value())


def _set_setting(page, name: str, value: int) -> None:
    page.goto("/servicedesk/")
    form = _form(page)
    form.locator(f"input[name={name}]").fill(str(value))
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    assert not page.locator("[data-error], [role=alert][data-code]").count(), "настройка не принята"
    expect(page.locator("[role=status]").first).to_be_visible()


def _status_rows(page) -> list:
    page.goto("/servicedesk/dictionaries/statuses/")
    rows = page.locator('table[data-dictionary="status"] tr[data-dictionary-row]')
    expect(rows.first).to_be_visible()
    return [{
        "id": row.get_attribute("data-id"),
        "archived": row.get_attribute("data-archived") == "true",
        "kind": row.locator('[data-cell="kind"]').inner_text().strip().lower(),
        "default": "по умолчанию" in row.locator('[data-cell="default"]').inner_text(),
        "system": row.locator("[data-system-mark]").count() > 0,
        "name": row.locator('[data-cell="name"]').inner_text(),
    } for row in rows.all()]


def _waiting_default_id(page) -> str:
    return [r["id"] for r in _status_rows(page) if r["kind"] == "ждёт ответа заявителя" and r["default"]][0]


def _new_ticket(page, mailpit, *, cc=()):
    """Заявка из письма; ждёт подтверждение. Возвращает (номер, адрес заявителя, тема, слово)."""
    word, sender = _word(), helpers_sd.requester_email()
    subject = f"Вопрос {word}"
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], cc=list(cc), subject=subject,
                                  text=f"Описание {word}", message_id=_message_id()))
    number = helpers_sd.ticket_number_by_subject(page, word)
    helpers_sd.wait_letter(mailpit, number, "ticket.confirmation", to=sender)
    return number, sender, subject, word


def _reply(page, number: int, text: str, *, wait: bool, entries: int, files=None) -> None:
    """Ответ исполнителя из карточки (12.4); флажок «Ждём ответа заявителя» — `wait`; ждёт `entries` элементов
    `reply` в ленте (после замены фрагмента или перехода)."""
    card = helpers_sd.open_ticket(page, number)
    form = card.locator('form[data-form="ticket-reply"]')
    form.locator("textarea[name=text]").fill(text)
    if wait:
        form.locator("input[type=checkbox][name=wait]").check()
    if files:
        form.locator("input[type=file][name=files]").set_input_files(files)
    helpers.submit(form)
    expect(_card(page, number).locator('li[data-entry][data-kind="reply"]')).to_have_count(entries)


def _waiting_ticket(page, mailpit, *, cc=()):
    """Заявка вида «ждёт ответа заявителя»: ответ исполнителя с флажком; ждёт письмо ответа (порядок писем)."""
    number, sender, subject, word = _new_ticket(page, mailpit, cc=cc)
    _reply(page, number, f"Уточните, пожалуйста {word}", wait=True, entries=1)
    expect(_card(page, number)).to_have_attribute("data-kind", "waiting")
    helpers_sd.wait_letter(mailpit, number, "ticket.reply", to=sender)
    return number, sender, subject, word


def _expect_kind(page, number: int, kind: str) -> None:
    helpers_sd.open_ticket(page, number)
    expect(_card(page, number)).to_have_attribute("data-kind", kind)


def _autoclose_and_expect(page, number: int, kind: str) -> None:
    """Периодическое задание `autoclose` целиком и проверка вида заявки по её номеру (число обработанных из
    вывода команды не проверяем: задание берёт все подходящие заявки стенда)."""
    helpers_sd.run_job("autoclose")
    _expect_kind(page, number, kind)


def _requester_reply(sender: str, number: int, subject: str, text: str) -> None:
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=f"Re: [#{number}] {subject}",
                                  text=text, message_id=_message_id()))


def test_d06_waiting_ticket_without_replies_for_seven_days_autoclosed_with_letter(admin_page, mailpit):
    """Сценарий 6, п. 1: заявка вида «ждёт ответа заявителя» без писем семь суток (срок из настроек) закрывается
    автоматически: системный статус, закрыл — никто, событие в ленте, заявителю и участнику письмо «закрыта
    автоматически» (§ 10.4) (FR-250, FR-256)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    term, reopen = _read_setting(page, "autoclose_days"), _read_setting(page, "reopen_days")
    participant = helpers_sd.requester_email("cc")
    number, sender, subject, word = _waiting_ticket(page, mailpit, cc=[participant])
    # до срока (срок - 1) проверка заявку не трогает
    helpers_sd.backdate("ticket", number, "waiting_since", term - 1)
    _autoclose_and_expect(page, number, "waiting")
    # за сроком (всего срок + 1) — закрывает
    helpers_sd.backdate("ticket", number, "waiting_since", 2)
    helpers_sd.run_job("autoclose")
    card = helpers_sd.open_ticket(page, number)
    expect(card).to_have_attribute("data-kind", "closed")
    system_name = [r["name"] for r in _status_rows(page) if r["system"]][0]
    helpers_sd.open_ticket(page, number)
    assert helpers_sd.field_text(_card(page, number), "status") in system_name
    expect(_card(page, number).locator('[data-field="closed-by"]')).to_have_attribute("data-empty", "true")
    event = _card(page, number).locator('li[data-kind="event"][data-event="autoclosed"]')
    expect(event).to_have_count(1)
    expect(event.locator("time[data-at]")).to_have_count(1)  # дата закрытия: поля в 13.3 нет, время — у события (13.4)
    # п. 1: письмо «закрыта автоматически» заявителю, участник в копии, числа — из настроек
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.autoclosed", to=sender)
    text = _norm(letter["Text"])
    assert f"Заявка № {number} закрыта автоматически: мы ждали вашего ответа {term} дней." in text
    assert f"ответьте на это письмо в течение {reopen} дней — заявка откроется заново." in text
    assert participant in _addresses(letter.get("Cc"))
    headers = helpers_sd.letter_headers(mailpit, letter["ID"])
    assert [v.lower() for v in _header(headers, "Auto-Submitted")] == ["auto-generated"]


def test_d06_requester_reply_on_day_six_prevents_autoclose(admin_page, mailpit):
    """Сценарий 6, п. 2: заявитель написал на шестой день — заявка «в работе», отсчёта нет; сколько бы суток ни
    прошло дальше, проверка её не закрывает (автозакрытие берёт только вид «ждёт ответа заявителя») (FR-208,
    FR-250)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    term = _read_setting(page, "autoclose_days")
    number, sender, subject, word = _waiting_ticket(page, mailpit)
    helpers_sd.backdate("ticket", number, "waiting_since", term - 1)  # шестой день
    _requester_reply(sender, number, subject, "Вот ответ")
    _expect_kind(page, number, "in_progress")
    _autoclose_and_expect(page, number, "in_progress")
    # ещё сдвиг: отметка отсчёта (от now) за сроком, но вида «ждёт» у заявки уже нет — закрыта быть не должна
    helpers_sd.backdate("ticket", number, "waiting_since", term + 1)
    helpers_sd.backdate("ticket", number, "last_message_at", 2)
    _autoclose_and_expect(page, number, "in_progress")


def test_d06_in_progress_ticket_never_autoclosed(admin_page, mailpit):
    """Сценарий 6, п. 3: заявка вида «в работе» проверкой не закрывается, сколько бы дней ни прошло (FR-250)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    term = _read_setting(page, "autoclose_days")
    number, sender, subject, word = _new_ticket(page, mailpit)
    helpers_sd.open_ticket(page, number)
    _card(page, number).locator('form[data-form="ticket-take"] button[data-action="ticket-take"]').click()
    expect(_card(page, number)).to_have_attribute("data-kind", "in_progress")
    for field in ("created_at", "last_message_at"):
        helpers_sd.backdate("ticket", number, field, 30)
    helpers_sd.backdate("ticket", number, "waiting_since", term + 1)
    _autoclose_and_expect(page, number, "in_progress")


def test_d06_changed_autoclose_term_three_days_applies(admin_page, mailpit):
    """Сценарий 6, п. 4: срок автозакрытия изменён на 3 дня — проверка действует по новому сроку: 2 суток не
    закрывают, 4 закрывают (при прежних 7 не закрыли бы); письмо — с новым числом (срок читается при отправке)
    (FR-274)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    before = _read_setting(page, "autoclose_days")  # читаем до try, возвращаем в finally
    new_term = 3 if before != 3 else 4
    number, sender, subject, word = _waiting_ticket(page, mailpit)
    try:
        _set_setting(page, "autoclose_days", new_term)
        helpers_sd.backdate("ticket", number, "waiting_since", new_term - 1)
        _autoclose_and_expect(page, number, "waiting")
        helpers_sd.backdate("ticket", number, "waiting_since", 2)  # всего новый срок + 1
        _autoclose_and_expect(page, number, "closed")
        letter = helpers_sd.wait_letter(mailpit, number, "ticket.autoclosed", to=sender)  # до возврата настройки
        assert f"мы ждали вашего ответа {new_term} дней." in _norm(letter["Text"])
    finally:
        _set_setting(page, "autoclose_days", before)


def test_d06_autoclosed_ticket_reopens_on_requester_reply_within_term(admin_page, mailpit):
    """Сценарий 6, п. 5: автоматически закрытая заявка открывается заново ответом заявителя в пределах срока
    открытия, как любая закрытая: «в работе», письмо «открыта заново», событие в ленте (FR-251)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    term = _read_setting(page, "autoclose_days")
    number, sender, subject, word = _waiting_ticket(page, mailpit)
    helpers_sd.backdate("ticket", number, "waiting_since", term + 1)
    _autoclose_and_expect(page, number, "closed")  # закрыта только что — внутри срока открытия
    _requester_reply(sender, number, subject, "Всё-таки не получилось")
    card = helpers_sd.open_ticket(page, number)
    expect(card).to_have_attribute("data-kind", "in_progress")
    event = card.locator('li[data-kind="event"][data-event="reopened"]')
    expect(event).to_have_count(1)
    assert "открыта заново" in event.inner_text()
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.reopened", to=sender)
    assert f"Заявка № {number} снова в работе." in _norm(letter["Text"])


def test_d06_manual_waiting_status_autoclosed_though_no_letter_was_sent(admin_page, mailpit):
    """Сценарий 6, п. 6: исполнитель вручную перевёл заявку на «Ждёт ответа заявителя» (письма при этом нет) —
    через срок без писем заявка закрыта автоматически (FR-209, FR-250)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    term = _read_setting(page, "autoclose_days")
    waiting_id = _waiting_default_id(page)
    number, sender, subject, word = _new_ticket(page, mailpit)
    card = helpers_sd.open_ticket(page, number)
    form = card.locator('form[data-form="ticket-status"]')
    form.locator("select[name=status]").select_option(value=waiting_id)
    helpers.submit(form)
    expect(_card(page, number)).to_have_attribute("data-kind", "waiting")
    assert helpers_sd.no_letter(mailpit, number, "ticket.reply", wait=15)  # письма ответа при ручной смене нет
    helpers_sd.backdate("ticket", number, "waiting_since", term + 1)
    _autoclose_and_expect(page, number, "closed")


def test_d06_status_change_within_waiting_kind_keeps_countdown(admin_page, mailpit):
    """Сценарий 6, п. 7: смена статуса на другой статус того же вида «ждёт ответа заявителя» не сбрасывает отсчёт:
    после сдвига «срок - 2», смены статуса и ещё 3 суток (всего срок + 1) заявка закрывается (FR-209, FR-250)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    term = _read_setting(page, "autoclose_days")
    # второй статус вида «ждёт ответа заявителя» (12.6: форма значения справочника статусов)
    status_name = f"Ждём поставщика {_word()}"
    page.goto("/servicedesk/dictionaries/statuses/new/")
    form = page.locator('form[data-form="dictionary"]')
    expect(form).to_be_visible()
    form.locator("input[name=name]").fill(status_name)
    form.locator("input[name=order]").fill("35")
    form.locator("select[name=kind]").select_option(value="waiting")
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    assert not page.locator("[data-error], [role=alert][data-code]").count(), "статус не создан"
    second_id = [r["id"] for r in _status_rows(page) if status_name in r["name"]][0]
    number, sender, subject, word = _waiting_ticket(page, mailpit)
    helpers_sd.backdate("ticket", number, "waiting_since", term - 2)
    card = helpers_sd.open_ticket(page, number)
    form = card.locator('form[data-form="ticket-status"]')
    form.locator("select[name=status]").select_option(value=second_id)
    helpers.submit(form)
    expect(_card(page, number).locator('[data-field="status"]')).to_contain_text(status_name)
    expect(_card(page, number)).to_have_attribute("data-kind", "waiting")
    helpers_sd.backdate("ticket", number, "waiting_since", 3)  # отсчёт не сброшен: (срок - 2) + 3 = срок + 1
    _autoclose_and_expect(page, number, "closed")


def test_d06_reply_without_waiting_flag_returns_in_progress_not_autoclosed(admin_page, mailpit):
    """Сценарий 6, п. 8: заявка «ждёт ответа заявителя», исполнитель отправляет ответ без флажка «Ждём ответа
    заявителя» — заявка вида «в работе» и автозакрытию не подлежит, даже если отсчёт был за сроком (FR-208,
    FR-250)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    term = _read_setting(page, "autoclose_days")
    number, sender, subject, word = _waiting_ticket(page, mailpit)
    helpers_sd.backdate("ticket", number, "waiting_since", term + 1)  # отсчёт уже за сроком
    _reply(page, number, f"Ещё одно уточнение {word}", wait=False, entries=2)
    _expect_kind(page, number, "in_progress")
    _autoclose_and_expect(page, number, "in_progress")


def test_d06_internal_comment_keeps_status_and_countdown(admin_page, mailpit):
    """Сценарий 6, п. 9: внутренний комментарий не меняет статус и не сбрасывает отсчёт: после сдвига «срок - 2»,
    комментария и ещё 3 суток (всего срок + 1) заявка закрывается (FR-208, FR-250)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    term = _read_setting(page, "autoclose_days")
    number, sender, subject, word = _waiting_ticket(page, mailpit)
    helpers_sd.backdate("ticket", number, "waiting_since", term - 2)
    card = helpers_sd.open_ticket(page, number)
    status_before = helpers_sd.field_text(card, "status")
    form = card.locator('form[data-form="ticket-comment"]')
    form.locator("textarea[name=text]").fill(f"Заметка для своих {word}")
    helpers.submit(form)
    expect(_card(page, number).locator('li[data-entry][data-kind="comment"]')).to_have_count(1)
    card = helpers_sd.open_ticket(page, number)
    expect(card).to_have_attribute("data-kind", "waiting")
    assert helpers_sd.field_text(card, "status") == status_before
    helpers_sd.backdate("ticket", number, "waiting_since", 3)  # отсчёт не сброшен: (срок - 2) + 3 = срок + 1
    _autoclose_and_expect(page, number, "closed")


def test_d06_reply_blocked_by_quarantine_has_no_countdown_and_not_autoclosed_countdown_starts_on_actual_send(
        admin_page, mailpit):
    """Сценарий 6, п. 10: ответ с флажком «Ждём ответа» и заражённым вложением не ушёл (карантин) — отсчёта нет,
    заявка не закрывается; после «Отправить заново без заражённых вложений» ответ ушёл, заявка «ждёт ответа», отсчёт
    идёт от этой отправки: сразу проверка её не закрывает, через срок + 1 суток закрывает (FR-244, FR-250)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    term = _read_setting(page, "autoclose_days")
    number, sender, subject, word = _new_ticket(page, mailpit)
    helpers_sd.open_ticket(page, number)
    _card(page, number).locator('form[data-form="ticket-take"] button[data-action="ticket-take"]').click()
    expect(_card(page, number)).to_have_attribute("data-kind", "in_progress")
    infected = [{"name": "eicar.com", "mimeType": "application/octet-stream", "buffer": eicar_bytes()}]
    _reply(page, number, f"Ответ с вложением {word}", wait=True, entries=1, files=infected)
    # настоящий clamd: ждём «не отправлен» опросом карточки до 60 с (карточка сама не обновляется — контракт молчит)
    deadline = time.monotonic() + 60
    while True:
        card = helpers_sd.open_ticket(page, number)
        try:
            expect(card.locator('li[data-entry][data-kind="reply"] [data-send-state="not_sent"]')).to_have_count(
                1, timeout=3000)
            break
        except AssertionError:
            if time.monotonic() > deadline:
                raise
            page.wait_for_timeout(2000)
    # ответ с флажком перевёл заявку в «ждёт» сразу (6.7, start_countdown=False), карантин вид не возвращает:
    # вид «ждёт ответа», отсчёта нет (waiting_since пуст), письма ответа нет
    expect(card).to_have_attribute("data-kind", "waiting")
    expect(card.locator('li[data-kind="event"][data-event="reply_not_sent"]')).to_have_count(1)
    # пустой отсчёт проверка не закрывает (доказуемо в браузере только так; инвариант держит серверный test_sd_reply)
    _autoclose_and_expect(page, number, "waiting")
    # отсчёт от «сейчас» сдвигаем (пустое значение -> now - (срок + 1)) и сразу, без пауз (часовой cron жив),
    # отправляем заново без заражённых вложений: отсчёт должен начаться от этой отправки
    card = helpers_sd.open_ticket(page, number)
    helpers_sd.backdate("ticket", number, "waiting_since", term + 1)
    card.locator('form[data-form="reply-resend"] button[data-action="reply-resend"]').click()
    helpers_sd.wait_letter(mailpit, number, "ticket.reply", to=sender)
    # письмо ответа ровно одно: от неотправленного ответа письма не было
    assert len(helpers_sd.ticket_letters(mailpit, number, template="ticket.reply")) == 1
    _autoclose_and_expect(page, number, "waiting")  # отсчёт сброшен на отправку: сдвиг до неё не действует
    helpers_sd.backdate("ticket", number, "waiting_since", term + 1)
    _autoclose_and_expect(page, number, "closed")
