"""T-3149: сценарий 11 — чужой домен, автоответчик, письмо с номером от постороннего (FR-213…FR-216, FR-220, FR-221,
FR-257, FR-275)."""
import re
import secrets
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org, helpers_sd
from tests.e2e.helpers_sd import FOREIGN_DOMAIN, MAILBOX
from tests.support_servicedesk import build_mail

MOSCOW = ZoneInfo("Europe/Moscow")

# подписи итога письма (14.3)
FOREIGN = "отклонено: чужой домен"
SELF = "отклонено: письмо с адреса ящика заявок"
AUTO = "автоматическое письмо"
CREATED = "создана заявка"
APPENDED = "добавлено в заявку"


def _word() -> str:
    """Уникальное слово темы по доп. 41 (в): буква и шесть шестнадцатеричных знаков, не из одних цифр."""
    return f"t{secrets.token_hex(3)}"


def _message_id() -> str:
    return f"<{secrets.token_hex(8)}@client.test>"


def _foreign_email() -> str:
    return f"ext-{secrets.token_hex(4)}@{FOREIGN_DOMAIN}"


def _header(headers: dict, name: str) -> list:
    """Значения заголовка из ответа Mailpit без учёта регистра имени (значения — списки)."""
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return []


def _midnight_guard(page) -> None:
    """Тест, который сверяет «сегодня» по Москве, не начинается за пять минут до полуночи: ждёт, пока наступит новая
    дата (опрос страницы с пределом ~6 минут), и ещё 15 секунд после неё."""
    start = datetime.now(MOSCOW)
    if not (start.hour == 23 and start.minute >= 55):
        return
    deadline = time.monotonic() + 360
    while datetime.now(MOSCOW).date() == start.date() and time.monotonic() < deadline:
        page.wait_for_timeout(2000)
    page.wait_for_timeout(15_000)


def _incoming(card):
    return card.locator('ol[data-feed] li[data-entry][data-kind="incoming"]')


def _row(page, word: str):
    """Строка «Входящих писем» с темой `word`: открывает страницу, ждёт ровно одну строку."""
    helpers_sd.open_inbound(page)
    row = helpers_sd.inbound_row(page, subject=word)
    expect(row).to_have_count(1)
    return row


def _outcome(row) -> str:
    return row.locator('[data-cell="outcome"]').inner_text().strip().lower()


def _no_ticket(page, word: str) -> None:
    """Заявки с этим словом темы нет: страница списка загружена (первая страница), строк с ним нет."""
    assert helpers_sd.tickets_by_subject(page, word) == []


def _mail_to(mailpit, address: str) -> list:
    """Письма Mailpit (последние 50), где адрес среди `To`, `Cc`, `Bcc`."""
    found = []
    for short in mailpit.messages():
        for key in ("To", "Cc", "Bcc"):
            if address.lower() in [str(a.get("Address", "")).lower() for a in (short.get(key) or [])]:
                found.append(short)
    return found


def _new_ticket(page, *, sender: str | None = None, message_id: str | None = None, prefix: str = "Заявка"):
    """Заявка из письма корпоративного заявителя; возвращает (номер, слово темы, адрес, тема, Message-ID)."""
    word, sender = _word(), sender or helpers_sd.requester_email()
    message_id = message_id or _message_id()
    subject = f"{prefix} {word}"
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=subject, text=f"Текст заявки {word}",
                                  message_id=message_id))
    return helpers_sd.ticket_number_by_subject(page, word), word, sender, subject, message_id


def _control_arrived(page, mailpit) -> None:
    """Контрольная заявка: её подтверждение пришло в Mailpit. Письма, которые портал поставил в очередь раньше
    (подтверждение чужой заявки, ответ отклонённому), к этому моменту уже ушли: «письма нет» проверяется после."""
    number, _word_, sender, _subject, _mid = _new_ticket(page, prefix="Контроль")
    helpers_sd.wait_letter(mailpit, number, "ticket.confirmation", to=sender)


def test_d11_foreign_domain_mail_no_ticket_no_reply_outcome_foreign_domain(admin_page, mailpit):
    """Сценарий 11, п. 1: письмо с адреса не из корпоративного домена — заявки нет, ответа нет, итог «отклонено:
    чужой домен» (FR-215, FR-220)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    word, sender = _word(), _foreign_email()
    # когда: портал разобрал письмо чужого домена
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=f"Чужое письмо {word}",
                                  text=f"Помогите {word}", message_id=_message_id()))
    # п. 1: итог во «Входящих письмах»
    row = _row(page, word)
    assert FOREIGN in _outcome(row)
    expect(row).to_have_attribute("data-outcome", "rejected_domain")
    expect(row.locator("a[data-ticket-link]")).to_have_count(0)
    # заявки нет
    _no_ticket(page, word)
    # ответа нет: контрольная заявка отправила своё подтверждение, а чужому адресу писем нет
    _control_arrived(page, mailpit)
    assert _mail_to(mailpit, sender) == []


def test_d11_auto_headers_mail_no_ticket_no_append_no_confirmation_outcome_automatic(admin_page, mailpit):
    """Сценарий 11, п. 2: письмо с `Auto-Submitted` не «no», с `Precedence: bulk` или с пустым `Return-Path` — заявки
    нет, в существующую оно не дописано, подтверждения нет, итог «автоматическое письмо» (FR-216, FR-220)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    number, _w, requester, _subject, _mid = _new_ticket(page)
    helpers_sd.wait_letter(mailpit, number, "ticket.confirmation", to=requester)
    variants = (("Auto-Submitted", {"Auto-Submitted": "auto-replied"}),
                ("Precedence", {"Precedence": "bulk"}),
                ("Return-Path", {"Return-Path": "<>"}))
    sent = []
    for name, headers in variants:
        word, sender = _word(), helpers_sd.requester_email("auto")
        # дано: автоматическое письмо — и в существующую заявку (от её заявителя), и новое от другого адреса
        helpers_sd.deliver(build_mail(from_addr=requester, to=[MAILBOX], subject=f"Re: [#{number}] {word}",
                                      text=f"Автоответ {word}", message_id=_message_id(), headers=headers))
        helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=f"Новое {word}",
                                      text=f"Автоматическое {word}", message_id=_message_id(), headers=headers))
        sent.append((name, word, sender))
    # п. 2: итог каждого письма — «автоматическое письмо», без заявки
    for name, word, sender in sent:
        helpers_sd.open_inbound(page)
        rows = helpers_sd.inbound_row(page, subject=word)
        expect(rows).to_have_count(2)
        for row in rows.all():
            assert AUTO in _outcome(row), name
            expect(row).to_have_attribute("data-outcome", "auto")
            expect(row.locator("a[data-ticket-link]")).to_have_count(0)
        _no_ticket(page, word)
    # в существующую заявку ничего не дописано
    card = helpers_sd.open_ticket(page, number)
    expect(_incoming(card)).to_have_count(1)
    # подтверждения нет: после контрольной заявки автоматическим адресам и заявителю других писем нет
    _control_arrived(page, mailpit)
    for name, word, sender in sent:
        assert _mail_to(mailpit, sender) == [], name
    assert len(helpers_sd.ticket_letters(mailpit, number, template="ticket.confirmation")) == 1


def test_d11_mail_from_mailbox_address_rejected_no_ticket(admin_page):
    """Сценарий 11, п. 3: письмо с адреса самого ящика заявок отклонено, заявки нет (FR-216)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    word = _word()
    helpers_sd.deliver(build_mail(from_addr=MAILBOX, to=[MAILBOX], subject=f"Письмо от ящика {word}",
                                  text=f"Петля {word}", message_id=_message_id()))
    # п. 3: отклонено со своим итогом, заявки нет
    row = _row(page, word)
    assert SELF in _outcome(row)
    expect(row).to_have_attribute("data-outcome", "rejected_self")
    expect(row.locator("a[data-ticket-link]")).to_have_count(0)
    _no_ticket(page, word)


def test_d11_foreign_ticket_number_from_corporate_stranger_creates_new_ticket_nothing_appended(admin_page):
    """Сценарий 11, п. 4: письмо с номером чужой заявки в теме от корпоративного адреса, не заявителя и не участника,
    создаёт новую заявку, итог «создана заявка #N», в чужую заявку ничего не дописано (FR-214)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    owner_number, _, _owner, _subject, _mid = _new_ticket(page)
    stranger, word = helpers_sd.requester_email("stranger"), _word()
    # дано: посторонний корпоративный адрес пишет с номером чужой заявки
    helpers_sd.deliver(build_mail(from_addr=stranger, to=[MAILBOX], subject=f"Re: [#{owner_number}] {word}",
                                  text=f"Чужой номер {word}", message_id=_message_id()))
    # п. 4: новая заявка, итог со ссылкой на неё
    new_number = helpers_sd.ticket_number_by_subject(page, word)
    assert new_number != owner_number
    row = _row(page, word)
    assert CREATED in _outcome(row)
    expect(row).to_have_attribute("data-outcome", "created")
    expect(row.locator("a[data-ticket-link]")).to_have_attribute("href", f"/tickets/{new_number}/")
    expect(row.locator("a[data-ticket-link]")).to_have_text(f"#{new_number}")
    # в чужую заявку ничего не дописано
    card = helpers_sd.open_ticket(page, owner_number)
    expect(_incoming(card)).to_have_count(1)
    assert word not in card.inner_text()
    new_card = helpers_sd.open_ticket(page, new_number)
    expect(_incoming(new_card)).to_have_count(1)


def test_d11_inbound_list_filters_by_outcome_and_period_columns_and_no_right_refused(admin_page, employee):
    """Сценарий 11, п. 6: «Входящие письма» — видны время, отправитель, тема, итог; фильтр по итогу и периоду
    (`ДД.ММ.ГГГГ` по Москве) отбирает письма; без права «Настройка сервис-деска» страница недоступна (FR-220,
    FR-275)."""
    page = admin_page
    _midnight_guard(page)
    helpers_sd.ensure_ready(page)
    foreign_word, foreign_sender = _word(), _foreign_email()
    helpers_sd.deliver(build_mail(from_addr=foreign_sender, to=[MAILBOX], subject=f"Фильтр чужой {foreign_word}",
                                  text=f"Чужой {foreign_word}", message_id=_message_id()))
    number, ok_word, ok_sender, _s, _m = _new_ticket(page, prefix="Фильтр рабочий")
    today = datetime.now(MOSCOW).date()
    fmt = "%d.%m.%Y"

    def listing(**params) -> None:
        query = "&".join(f"{key}={value}" for key, value in params.items())
        page.goto("/servicedesk/inbound/" + (f"?{query}" if query else ""))
        expect(page.locator("[data-mailbox-status]")).to_be_visible()

    # колонки и состояние ящика: время, отправитель, тема, итог
    listing()
    status = page.locator("[data-mailbox-status]")
    expect(status).to_have_attribute("data-mailbox-state", "connected")
    expect(status.locator('[data-field="mailbox-address"]')).to_contain_text(MAILBOX)
    foreign_row = helpers_sd.inbound_row(page, subject=foreign_word)
    ok_row = helpers_sd.inbound_row(page, subject=ok_word)
    expect(foreign_row).to_have_count(1)
    expect(ok_row).to_have_count(1)
    assert foreign_row.locator('[data-cell="received"]').inner_text().strip() != ""
    expect(foreign_row.locator('[data-cell="sender"]')).to_contain_text(foreign_sender)
    expect(foreign_row.locator('[data-cell="subject"]')).to_contain_text(foreign_word)
    assert FOREIGN in _outcome(foreign_row)
    expect(ok_row.locator('[data-cell="sender"]')).to_contain_text(ok_sender)
    expect(ok_row.locator('a[data-ticket-link]')).to_have_attribute("href", f"/tickets/{number}/")
    # общее число — по кнопке «показать число»
    page.locator('a[data-action="show-count"]').click()
    total = page.locator("[data-total]")
    expect(total).to_be_visible()
    assert int(re.search(r"\d+", total.inner_text()).group()) >= 2
    # фильтр по итогу: форма хранит выбранное значение, в списке — только письма с этим итогом
    listing(outcome="rejected_domain")
    expect(page.locator('form[data-form="inbound-filter"] select[name=outcome]')).to_have_value("rejected_domain")
    expect(helpers_sd.inbound_row(page, subject=foreign_word)).to_have_count(1)
    expect(helpers_sd.inbound_row(page, subject=ok_word)).to_have_count(0)
    listing(outcome="created")
    expect(helpers_sd.inbound_row(page, subject=ok_word)).to_have_count(1)
    expect(helpers_sd.inbound_row(page, subject=foreign_word)).to_have_count(0)
    # фильтр по периоду: с сегодня (по Москве) по завтра (верхняя граница включена или нет — всё равно оба письма);
    # с завтра и по вчера — ни одного
    listing(date_from=today.strftime(fmt), date_to=(today + timedelta(days=1)).strftime(fmt))
    expect(helpers_sd.inbound_row(page, subject=foreign_word)).to_have_count(1)
    expect(helpers_sd.inbound_row(page, subject=ok_word)).to_have_count(1)
    listing(date_from=(today + timedelta(days=1)).strftime(fmt))
    expect(helpers_sd.inbound_row(page, subject=foreign_word)).to_have_count(0)
    expect(helpers_sd.inbound_row(page, subject=ok_word)).to_have_count(0)
    listing(date_to=(today - timedelta(days=1)).strftime(fmt))
    expect(helpers_sd.inbound_row(page, subject=foreign_word)).to_have_count(0)
    expect(helpers_sd.inbound_row(page, subject=ok_word)).to_have_count(0)
    # без права «Настройка сервис-деска» страница недоступна
    token = secrets.token_hex(3)
    account = employee(full_name=f"Входящ{token} Иванов Иван")
    assert helpers_org.direct_get(account.page, "/servicedesk/inbound/").status == 403


def test_d11_auto_reply_to_executor_reply_creates_no_ticket(admin_page, mailpit):
    """Сценарий 11, п. 7: ответ исполнителя вызвал автоответ почты заявителя со служебными заголовками — письмо,
    пришедшее в ящик, не создаёт заявку и не дописывается (FR-216, FR-257)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    number, word, requester, subject, _mid = _new_ticket(page)
    card = helpers_sd.open_ticket(page, number)
    # дано: исполнитель ответил, заявителю ушло письмо ответа
    form = card.locator('form[data-form="ticket-reply"]')
    form.locator("textarea[name=text]").fill(f"Ответ исполнителя {word}")
    helpers.submit(form)
    expect(card.locator('li[data-entry][data-kind="reply"]')).to_have_count(1)
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.reply", to=requester)
    reply_id = _header(helpers_sd.letter_headers(mailpit, letter["ID"]), "Message-ID")[0]
    reply_id = reply_id if reply_id.startswith("<") else f"<{reply_id}>"
    # когда: почта заявителя отвечает автоответом на это письмо
    auto_word = _word()
    helpers_sd.deliver(build_mail(from_addr=requester, to=[MAILBOX], subject=f"Re: [#{number}] {subject} {auto_word}",
                                  text=f"Я вне офиса {auto_word}", message_id=_message_id(), in_reply_to=reply_id,
                                  references=reply_id, headers={"Auto-Submitted": "auto-replied"}))
    # п. 7: письмо автоматическое — заявки нет, в ленте заявки нового входящего нет
    row = _row(page, auto_word)
    assert AUTO in _outcome(row)
    expect(row.locator("a[data-ticket-link]")).to_have_count(0)
    _no_ticket(page, auto_word)
    card = helpers_sd.open_ticket(page, number)
    expect(_incoming(card)).to_have_count(1)
    expect(card.locator('li[data-entry][data-kind="reply"]')).to_have_count(1)


def test_d11_mailbox_address_with_auto_headers_outcome_text_and_foreign_auto_not_foreign_domain(admin_page):
    """Сценарий 11, п. 8: письмо с адреса ящика с признаками автоматического — итог «отклонено: письмо с адреса
    ящика заявок»; автоматическое письмо чужого домена — «автоматическое письмо», а не «чужой домен» (FR-214,
    FR-216)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    own_word, foreign_word = _word(), _word()
    helpers_sd.deliver(build_mail(from_addr=MAILBOX, to=[MAILBOX], subject=f"Свой автоответ {own_word}",
                                  text=f"Автоматическое {own_word}", message_id=_message_id(),
                                  headers={"Auto-Submitted": "auto-generated"}))
    helpers_sd.deliver(build_mail(from_addr=_foreign_email(), to=[MAILBOX], subject=f"Чужой автоответ {foreign_word}",
                                  text=f"Автоматическое {foreign_word}", message_id=_message_id(),
                                  headers={"Auto-Submitted": "auto-replied", "Precedence": "bulk"}))
    # п. 8: адрес ящика главнее признаков автоматического
    own = _row(page, own_word)
    assert SELF in _outcome(own)
    expect(own).to_have_attribute("data-outcome", "rejected_self")
    # автоматическое чужого домена — «автоматическое письмо», не «чужой домен»
    foreign = _row(page, foreign_word)
    assert AUTO in _outcome(foreign)
    assert FOREIGN not in _outcome(foreign)
    expect(foreign).to_have_attribute("data-outcome", "auto")
    _no_ticket(page, own_word)
    _no_ticket(page, foreign_word)


def test_d11_subject_number_wins_over_in_reply_to_header(admin_page):
    """Сценарий 11, п. 9: номер `[#N]` в теме указывает на одну заявку, `In-Reply-To` — на другую, отправитель —
    заявитель обеих: письмо дописано в заявку по номеру (FR-214)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    requester = helpers_sd.requester_email()
    first, _, _s1, _t1, _m1 = _new_ticket(page, sender=requester, prefix="Первая")
    second, _, _s2, _t2, second_id = _new_ticket(page, sender=requester, prefix="Вторая")
    assert first != second
    word = _word()
    # когда: тема с номером первой заявки, In-Reply-To — Message-ID письма второй
    helpers_sd.deliver(build_mail(from_addr=requester, to=[MAILBOX], subject=f"Re: [#{first}] Первая {word}",
                                  text=f"Дополнение {word}", message_id=_message_id(), in_reply_to=second_id,
                                  references=second_id))
    # п. 9: дописано в первую заявку, во вторую — нет, новой заявки нет
    row = _row(page, word)
    assert APPENDED in _outcome(row)
    expect(row).to_have_attribute("data-outcome", "appended")
    expect(row.locator("a[data-ticket-link]")).to_have_attribute("href", f"/tickets/{first}/")
    card = helpers_sd.open_ticket(page, first)
    expect(_incoming(card)).to_have_count(2)
    expect(_incoming(card).filter(has_text=word)).to_have_count(1)
    other = helpers_sd.open_ticket(page, second)
    expect(_incoming(other)).to_have_count(1)
    assert word not in other.inner_text()


def test_d11_unknown_ticket_number_from_corporate_address_creates_new_ticket_in_default_queue(admin_page):
    """Сценарий 11, п. 10: номер в теме указывает на несуществующую заявку, письмо с корпоративного адреса — создана
    новая заявка в очереди по умолчанию (FR-214)."""
    page = admin_page
    _queue_id, queue_name = helpers_sd.ensure_ready(page)
    word, sender = _word(), helpers_sd.requester_email()
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=f"Re: [#9999999] {word}",
                                  text=f"Несуществующий номер {word}", message_id=_message_id()))
    # п. 10: новая заявка в очереди по умолчанию, итог со ссылкой на неё
    number = helpers_sd.ticket_number_by_subject(page, word)
    assert number != 9999999
    card = helpers_sd.open_ticket(page, number)
    assert queue_name in helpers_sd.field_text(card, "queue")
    row = _row(page, word)
    assert CREATED in _outcome(row)
    expect(row.locator("a[data-ticket-link]")).to_have_attribute("href", f"/tickets/{number}/")


def test_d11_domain_removed_reply_rejected_as_foreign_domain_not_appended(admin_page):
    """Сценарий 11, п. 13: домен убран из списка корпоративных — ответ с него в существующую заявку отклонён как
    «чужой домен» и в заявку не дописан (FR-213, FR-215)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    number, _w, requester, _subject, _mid = _new_ticket(page)
    word = _word()
    before = helpers_sd.read_domains(page)
    try:
        # дано: корпоративный домен заявителя убран из списка (в списке остаётся другой домен)
        helpers_sd.set_domains(page, ["other-corp.test"])
        helpers_sd.deliver(build_mail(from_addr=requester, to=[MAILBOX], subject=f"Re: [#{number}] {word}",
                                      text=f"Ответ после снятия домена {word}", message_id=_message_id()))
    finally:
        helpers_sd.set_domains(page, before)
    # п. 13: итог «чужой домен», в заявку не дописано
    row = _row(page, word)
    assert FOREIGN in _outcome(row)
    expect(row).to_have_attribute("data-outcome", "rejected_domain")
    card = helpers_sd.open_ticket(page, number)
    expect(_incoming(card)).to_have_count(1)
    assert word not in card.inner_text()
    _no_ticket(page, word)


def test_d11_auto_reply_without_service_headers_appended_as_requester_mail(admin_page):
    """Сценарий 11, п. 14: автоответ без служебных заголовков, пришедший в существующую заявку от заявителя, дописан
    в заявку как письмо заявителя (FR-216)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    number, _w, requester, subject, _mid = _new_ticket(page)
    word = _word()
    # когда: «автоответ» с обычными заголовками (ни Auto-Submitted, ни Precedence, ни пустого Return-Path)
    helpers_sd.deliver(build_mail(from_addr=requester, to=[MAILBOX], subject=f"Re: [#{number}] Автоответ {word}",
                                  text=f"Я в отпуске до понедельника {word}", message_id=_message_id()))
    # п. 14: дописан как входящее письмо заявителя
    row = _row(page, word)
    assert APPENDED in _outcome(row)
    expect(row).to_have_attribute("data-outcome", "appended")
    expect(row.locator("a[data-ticket-link]")).to_have_attribute("href", f"/tickets/{number}/")
    card = helpers_sd.open_ticket(page, number)
    expect(_incoming(card)).to_have_count(2)
    mine = _incoming(card).filter(has_text=word)
    expect(mine).to_have_count(1)
    expect(mine.locator('[data-author][data-author-kind="requester"]')).to_contain_text(requester)
    _no_ticket(page, word)


def test_d11_night_job_deletes_stored_unlinked_mail_keeps_record_without_address_and_subject_keeps_ticket_mail(
        admin_page):
    """Сценарий 11, п. 15: отклонённое и автоматическое письма, не связанные с заявкой, с момента получения которых
    прошёл срок хранения, после ночного задания остаются во «Входящих» без адреса и темы (итог цел); письмо, по
    которому создана заявка, и свежее отклонённое письмо задание не трогает (FR-221).

    Известный пропуск (решение Opus, decisions-2.md, T-3149, п. 2): третий вид писем п. 15 — «ожидающее настройки» —
    на стенде не проверяется: ожидающее письмо и заявку по нему одновременно не получить (назначение очереди по
    умолчанию запускает разбор ожидающих, FR-213). Покрытие — серверные тесты 6.24 (`purge_inbound`: «любой итог …
    ждущие настройки»)."""
    page = admin_page
    _midnight_guard(page)
    helpers_sd.ensure_ready(page)
    page.goto("/servicedesk/")
    retention = int(page.locator('form[data-form="servicedesk-settings"] input[name=inbound_retention_days]')
                    .input_value())
    # срок с запасом в двое суток по обе стороны границы: старые письма — на retention + 2 суток
    days = retention + 2
    old_foreign, old_auto, young, kept = _word(), _word(), _word(), _word()
    ids = {name: _message_id() for name in ("foreign", "auto", "ticket")}
    helpers_sd.deliver(build_mail(from_addr=_foreign_email(), to=[MAILBOX], subject=f"Старое чужое {old_foreign}",
                                  text=f"Чужое {old_foreign}", message_id=ids["foreign"]))
    helpers_sd.deliver(build_mail(from_addr=helpers_sd.requester_email("auto"), to=[MAILBOX],
                                  subject=f"Старое автоматическое {old_auto}", text=f"Авто {old_auto}",
                                  message_id=ids["auto"], headers={"Auto-Submitted": "auto-generated"}))
    young_sender = _foreign_email()
    helpers_sd.deliver(build_mail(from_addr=young_sender, to=[MAILBOX], subject=f"Свежее чужое {young}",
                                  text=f"Свежее {young}", message_id=_message_id()))
    ticket_sender = helpers_sd.requester_email()
    helpers_sd.deliver(build_mail(from_addr=ticket_sender, to=[MAILBOX], subject=f"Старая заявка {kept}",
                                  text=f"Заявка {kept}", message_id=ids["ticket"]))
    number = helpers_sd.ticket_number_by_subject(page, kept)
    row_ids = {"foreign": helpers_sd.inbound_mail_id(page, subject=old_foreign),
               "auto": helpers_sd.inbound_mail_id(page, subject=old_auto),
               "ticket": helpers_sd.inbound_mail_id(page, subject=kept)}
    # когда: три письма получены давно, срок хранения прошёл; выполняется ночное задание
    for key in ids:
        helpers_sd.backdate("mail", ids[key], "received_at", days)
    helpers_sd.run_job("purge_inbound")
    # п. 15: записи старых писем остались, адрес и тема стёрты («—»), итог цел; письмо с заявкой цело
    day = (datetime.now(MOSCOW) - timedelta(days=days)).date()
    fmt = "%d.%m.%Y"
    page.goto(f"/servicedesk/inbound/?date_from={(day - timedelta(days=1)).strftime(fmt)}"
              f"&date_to={(day + timedelta(days=1)).strftime(fmt)}")
    expect(page.locator("[data-mailbox-status]")).to_be_visible()

    def by_id(key: str):
        return page.locator(f'tr[data-inbound][data-id="{row_ids[key]}"]')

    for key, label in (("foreign", FOREIGN), ("auto", AUTO)):
        row = by_id(key)
        expect(row).to_have_count(1)
        expect(row.locator('[data-cell="sender"]')).to_have_text("—")
        expect(row.locator('[data-cell="subject"]')).to_have_text("—")
        assert label in _outcome(row)
    ticket_row = by_id("ticket")
    expect(ticket_row).to_have_count(1)
    expect(ticket_row.locator('[data-cell="sender"]')).to_contain_text(ticket_sender)
    expect(ticket_row.locator('[data-cell="subject"]')).to_contain_text(kept)
    expect(ticket_row.locator("a[data-ticket-link]")).to_have_attribute("href", f"/tickets/{number}/")
    # свежее письмо без заявки срок не прошло — не тронуто
    helpers_sd.open_inbound(page)
    fresh = helpers_sd.inbound_row(page, subject=young)
    expect(fresh).to_have_count(1)
    expect(fresh.locator('[data-cell="sender"]')).to_contain_text(young_sender)
    # заявка по письму и её текст целы
    card = helpers_sd.open_ticket(page, number)
    expect(_incoming(card).locator("[data-entry-text]")).to_contain_text(kept)
