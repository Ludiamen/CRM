"""T-3140: сценарий 1 — письмо становится заявкой (FR-210…FR-219, FR-253, FR-257, NFR-209)."""
import re
import secrets
import urllib.parse

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org, helpers_sd
from tests.e2e.helpers_sd import CORP_DOMAIN, FOREIGN_DOMAIN, MAILBOX
from tests.support_servicedesk import build_mail


def _word() -> str:
    """Уникальное слово темы по доп. 41 (в): буква и шесть шестнадцатеричных знаков, не из одних цифр."""
    return f"t{secrets.token_hex(3)}"


def _message_id() -> str:
    return f"<{secrets.token_hex(8)}@client.test>"


def _norm(text: str) -> str:
    """Текст письма с пробелами и переводами строк, сжатыми в один пробел (переносы строк шаблона не важны)."""
    return " ".join(text.split())


def _default_priority_name(page) -> str:
    """Название критичности по умолчанию — выбранный пункт `select[name=default_priority]` страницы настроек."""
    page.goto("/servicedesk/")
    form = page.locator('form[data-form="servicedesk-settings"]')
    expect(form).to_be_visible()
    return form.locator("select[name=default_priority] option:checked").inner_text().strip()


def _participants(card):
    return card.locator('[data-section="participants"] [data-participant]')


def _incoming(card):
    return card.locator('ol[data-feed] li[data-entry][data-kind="incoming"]')


def _header(headers: dict, name: str) -> list:
    """Значения заголовка из ответа Mailpit без учёта регистра имени (значения — списки)."""
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return []


def _addresses(entries) -> list:
    """Адреса строчными из поля `To`/`Cc` письма Mailpit (список словарей с ключом `Address`)."""
    return [str(item.get("Address", "")).lower() for item in (entries or [])]


def _requester_cell(page, number: int):
    """Ячейка «заявитель» строки заявки в сетке списка (13.2); страница списка уже открыта."""
    return page.locator(f'#tickets-grid tr[data-ticket="{number}"] [data-cell="requester"]')


def test_d01_mail_becomes_ticket_in_default_queue_source_mail_without_assignee(admin_page):
    """Сценарий 1, п. 1: письмо корпоративного домена на ящик заявок становится заявкой: очередь по умолчанию,
    источник «Почта», критичность по умолчанию, статус «Новая», ответственного нет, заявитель — отправитель, в
    ленте — входящее письмо (FR-210, FR-214)."""
    page = admin_page
    # дано: домен корпоративный, очередь по умолчанию есть
    queue_id, queue_name = helpers_sd.ensure_ready(page)
    priority_name = _default_priority_name(page)
    word, sender = _word(), helpers_sd.requester_email()
    subject = f"Не печатает принтер {word}"
    body = f"Принтер на втором этаже не печатает {word}"
    # когда: портал забирает письмо (опрос «не позже 2 минут» проверяет T-3152 — здесь разбор сразу)
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=subject, text=body,
                                  message_id=_message_id()))
    # п. 1: появилась ровно одна заявка с полями по сценарию
    number = helpers_sd.ticket_number_by_subject(page, word)
    card = helpers_sd.open_ticket(page, number)
    assert queue_name in helpers_sd.field_text(card, "queue")
    assert helpers_sd.field_text(card, "source") == "Почта"
    assert priority_name.lower() in helpers_sd.field_text(card, "priority").lower()
    assert helpers_sd.field_text(card, "status").lower() == "новая"
    expect(card).to_have_attribute("data-kind", "new")
    assignee = card.locator('[data-field="assignee"]')
    expect(assignee).to_have_attribute("data-empty", "true")
    assert "не назначен" in helpers_sd.field_text(card, "assignee").lower()
    assert subject in helpers_sd.field_text(card, "subject")
    assert sender in helpers_sd.field_text(card, "requester-email").lower()
    # в ленте — одно входящее письмо с текстом и автором-заявителем
    expect(_incoming(card)).to_have_count(1)
    expect(_incoming(card).locator("[data-entry-text]")).to_contain_text(body)
    expect(_incoming(card).locator('[data-author][data-author-kind="requester"]')).to_contain_text(sender)


def test_d01_confirmation_in_mailpit_has_number_subject_text_pd_line_and_auto_marks(admin_page, mailpit):
    """Сценарий 1, п. 2: заявитель получил подтверждение с номером, темой `[#N] Тема`, текстом заявки и строкой
    о согласии на обработку ПДн (§ 10.4); письмо помечено автоматическим: `Auto-Submitted: auto-replied`
    (§ 10.1, 10.2) (FR-253, FR-257)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    word, sender = _word(), helpers_sd.requester_email()
    subject = f"Подтверждение заявки {word}"
    body = f"Не работает сканер в бухгалтерии {word}"
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=subject, text=body,
                                  message_id=_message_id()))
    number = helpers_sd.ticket_number_by_subject(page, word)
    # п. 2: письмо-подтверждение пришло заявителю (ждём до 60 с: рассылает рабочая служба)
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.confirmation", to=sender)
    assert letter["Subject"] == f"[#{number}] {subject}"
    text = _norm(letter["Text"])
    assert f"Здравствуйте, {sender}!" in text
    assert f"Ваша заявка принята под номером {number}." in text
    assert f"Тема: {subject}" in text
    assert f"Текст заявки: {body}" in text
    assert "Чтобы дополнить заявку, ответьте на это письмо, не меняя тему." in text
    assert ("Отправляя заявку, вы согласны на обработку ваших персональных данных (адрес, ФИО, подразделение и "
            "текст заявки) для работы ИТ-отдела.") in text
    # письмо помечено как автоматическое (заявка из письма — auto-replied)
    headers = helpers_sd.letter_headers(mailpit, letter["ID"])
    assert [value.lower() for value in _header(headers, "Auto-Submitted")] == ["auto-replied"]
    assert [value for value in _header(headers, "X-Portal-Template")] == ["ticket.confirmation"]
    # копии подтверждение не получает (10.2: у подтверждения `Cc` пуст)
    assert _addresses(letter.get("Cc")) == []


def test_d01_cc_corporate_addresses_become_participants_mailbox_address_does_not(admin_page):
    """Сценарий 1, п. 3: в «Копии» письма два адреса корпоративного домена и адрес ящика заявок — участниками
    стали два адреса, адрес ящика участником не стал (FR-217)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    word, sender = _word(), helpers_sd.requester_email()
    first, second = helpers_sd.requester_email("cc1"), helpers_sd.requester_email("cc2")
    assert MAILBOX.split("@", 1)[1] == CORP_DOMAIN  # домен ящика — корпоративный (доп. 40 (в))
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], cc=[first, second, MAILBOX],
                                  subject=f"Копия коллегам {word}", text=f"Просим помочь {word}",
                                  message_id=_message_id()))
    number = helpers_sd.ticket_number_by_subject(page, word)
    card = helpers_sd.open_ticket(page, number)
    # п. 3: участников ровно два — оба адреса из копии; адреса ящика и заявителя среди них нет
    section = card.locator('[data-section="participants"]')
    expect(_participants(card)).to_have_count(2)
    expect(section).to_contain_text(first)
    expect(section).to_contain_text(second)
    text = section.inner_text().lower()
    assert MAILBOX.lower() not in text
    assert sender not in text


def test_d01_cc_foreign_domain_not_participant_and_gets_no_replies(admin_page, mailpit):
    """Сценарий 1, п. 4: адрес не из корпоративного домена в «Копии» участником не становится и ответов не
    получает: ответ исполнителя из карточки уходит заявителю и корпоративному участнику, адреса чужого домена
    нет ни в `To`, ни в `Cc`, ни в `Bcc` писем заявки (FR-217)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    word, sender = _word(), helpers_sd.requester_email()
    corp_cc = helpers_sd.requester_email("cc")
    foreign = f"ext-{secrets.token_hex(4)}@{FOREIGN_DOMAIN}"
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], cc=[corp_cc, foreign],
                                  subject=f"Копия постороннему {word}", text=f"Нужна помощь {word}",
                                  message_id=_message_id()))
    number = helpers_sd.ticket_number_by_subject(page, word)
    card = helpers_sd.open_ticket(page, number)
    # п. 4: участник один (корпоративный), чужой адрес участником не стал
    expect(_participants(card)).to_have_count(1)
    expect(card.locator('[data-section="participants"]')).to_contain_text(corp_cc)
    assert foreign not in card.locator('[data-section="participants"]').inner_text().lower()
    # ответ исполнителя из карточки (администратору членство в очереди не нужно, 12.4)
    helpers_sd.wait_letter(mailpit, number, "ticket.confirmation", to=sender)
    reply_text = f"Ответ исполнителя {word}"
    form = card.locator('form[data-form="ticket-reply"]')
    form.locator("textarea[name=text]").fill(reply_text)
    helpers.submit(form)
    expect(card.locator('li[data-entry][data-kind="reply"]')).to_have_count(1)
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.reply", to=sender)
    # письмо ответа: заявителю, корпоративному участнику — в копию; чужого адреса нет нигде
    assert _addresses(letter.get("To")) == [sender]
    assert corp_cc in _addresses(letter.get("Cc"))
    assert foreign not in _addresses(letter.get("To")) + _addresses(letter.get("Cc")) + _addresses(letter.get("Bcc"))
    assert helpers_sd.ticket_letters(mailpit, number, recipient=foreign) == []


def test_d01_html_only_mail_shown_as_plain_text_and_source_mail_downloadable(admin_page):
    """Сценарий 1, п. 5: письмо только в HTML — в карточке текст без разметки (тег не стал элементом страницы),
    исходное письмо скачивается по `a[data-action="source-mail"]` с заголовками 12.5: `Content-Disposition` с
    `mail-<id>.eml`, `nosniff`, `no-store` (FR-212, FR-218)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    word, sender = _word(), helpers_sd.requester_email()
    message_id = _message_id()
    html = f"<p>Принтер <b>совсем</b> не <u>печатает</u> {word}</p>"
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=f"Письмо в HTML {word}", text=None,
                                  html=html, message_id=message_id))
    number = helpers_sd.ticket_number_by_subject(page, word)
    card = helpers_sd.open_ticket(page, number)
    # п. 5: текст виден без разметки; теги из письма не стали элементами и не показаны буквами
    entry_text = _incoming(card).locator("[data-entry-text]")
    expect(entry_text).to_contain_text(word)
    shown = _norm(entry_text.inner_text())
    assert "Принтер совсем не печатает" in shown
    for tag in ("<p>", "</p>", "<b>", "</b>", "<u>", "</u>"):
        assert tag not in shown
    expect(entry_text.locator("b, u, p, script")).to_have_count(0)
    # исходное письмо скачивается: заголовки выдачи (X-Accel-Redirect клиенту nginx не отдаёт)
    link = _incoming(card).locator('a[data-action="source-mail"]')
    expect(link).to_have_count(1)
    href = link.get_attribute("href")
    found = re.fullmatch(rf"/tickets/{number}/mail/(\d+)\.eml", href)
    assert found, href
    response = helpers_org.direct_get(page, href)
    assert response.status == 200
    headers = {key.lower(): value for key, value in response.headers.items()}
    assert f"mail-{found.group(1)}.eml" in headers["content-disposition"]
    assert headers["content-disposition"].lower().startswith("attachment")
    assert headers["content-type"].lower().startswith("application/octet-stream")
    assert headers["x-content-type-options"].lower() == "nosniff"
    assert "no-store" in headers["cache-control"].lower()
    assert message_id.strip("<>") in response.body().decode("latin-1")


def test_d01_empty_domain_list_rejects_mail_and_inbound_shows_foreign_domain(admin_page):
    """Сценарий 1, п. 6: список корпоративных доменов пуст — письмо корпоративного домена заявкой не стало
    (поиск по слову темы пуст), во «Входящих письмах» итог «отклонено: чужой домен»; ящик при этом подключён
    (FR-213, FR-215)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    word, sender = _word(), helpers_sd.requester_email()
    previous = helpers_sd.read_domains(page)
    try:
        helpers_sd.set_domains(page, [])
        # дано: список доменов пуст
        assert helpers_sd.read_domains(page) == []
        helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=f"Письмо без домена {word}",
                                      text=f"Письмо при пустом списке {word}", message_id=_message_id()))
        # п. 6: заявки нет
        assert helpers_sd.tickets_by_subject(page, word) == []
        # во «Входящих» — письмо с итогом «отклонено: чужой домен»; ящик подключён, причина — домен
        outcome = helpers_sd.inbound_outcome(page, subject=word)
        assert "отклонено: чужой домен" in outcome.lower()
        row = helpers_sd.inbound_row(page, subject=word)
        expect(row).to_have_attribute("data-outcome", "rejected_domain")
        expect(row.locator("a[data-ticket-link]")).to_have_count(0)
        expect(page.locator("[data-mailbox-status]")).to_have_attribute("data-mailbox-state", "connected")
    finally:
        helpers_sd.set_domains(page, previous)


def test_d01_mail_read_by_other_client_still_becomes_ticket(admin_page):
    """Сценарий 1, п. 7: письмо прочитано в почтовом клиенте раньше портала (флаг `\\Seen`) — портал всё равно
    делает из него заявку (FR-211)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    word, sender = _word(), helpers_sd.requester_email()
    # дано: письмо лежит в ящике уже прочитанным
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=f"Уже прочитано {word}",
                                  text=f"Письмо открыли в почтовой программе {word}", message_id=_message_id()),
                       seen=True)
    # п. 7: заявка есть, письмо в ленте
    number = helpers_sd.ticket_number_by_subject(page, word)
    card = helpers_sd.open_ticket(page, number)
    assert sender in helpers_sd.field_text(card, "requester-email").lower()
    expect(_incoming(card)).to_have_count(1)


def test_d01_repeated_poll_of_same_mail_creates_no_second_ticket(admin_page):
    """Сценарий 1, п. 8: повторный опрос и повторный разбор того же письма (`/servicedesk/inbound/<id>/retry/`,
    письмо уже обработано) второй заявки не создают: по слову темы одна заявка, одна строка письма, одно
    входящее письмо в ленте; повтор отвечает «Письмо не ждёт повторного разбора» (FR-211, NFR-209). Сбой
    посреди разбора приёмка не воспроизводит — это серверные тесты."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    word, sender = _word(), helpers_sd.requester_email()
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=f"Повторный разбор {word}",
                                  text=f"Письмо для повторного разбора {word}", message_id=_message_id()))
    number = helpers_sd.ticket_number_by_subject(page, word)
    # второй опрос видит то же письмо ящика — новых заявок нет
    helpers_sd.poll_now()
    assert helpers_sd.tickets_by_subject(page, word) == [number]
    # повтор разбора обработанного письма: маршрут принимает прямой POST (формы у такого письма нет)
    mail_id = helpers_sd.inbound_mail_id(page, subject=word)
    expect(page.locator(f'tr[data-inbound][data-id="{mail_id}"] form[data-form="inbound-retry"]')).to_have_count(0)
    response = helpers_org.direct_post(page, f"/servicedesk/inbound/{mail_id}/retry/")
    assert response.status == 302
    page.goto("/servicedesk/inbound/")
    status = page.locator("[role=status]").filter(has_text="Письмо не ждёт повторного разбора")
    expect(status.first).to_contain_text("Письмо не ждёт повторного разбора")
    # заявка по-прежнему одна, строка письма одна, в ленте одно входящее
    assert helpers_sd.tickets_by_subject(page, word) == [number]
    helpers_sd.open_inbound(page)
    expect(helpers_sd.inbound_row(page, subject=word)).to_have_count(1)
    card = helpers_sd.open_ticket(page, number)
    expect(_incoming(card)).to_have_count(1)


def test_d01_requester_name_from_header_then_record_then_empty_with_address_and_editable(admin_page):
    """Сценарий 1, п. 9: имя в `From` — ФИО заявителя; имени нет, а запись заявителя есть (загружена таблицей) —
    ФИО из записи; нет ни того ни другого — ФИО пусто, в списке показан адрес; исполнитель правит ФИО в заявке
    и в записи заявителя (FR-219, FR-263)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    word_a, word_b, word_c = _word(), _word(), _word()
    addr_a, addr_b, addr_c = (helpers_sd.requester_email("a"), helpers_sd.requester_email("b"),
                              helpers_sd.requester_email("c"))
    name_a = f"Сидоров-{word_a} Павел Игоревич"
    last_b = f"Орлов-{word_b}"
    name_b = f"{last_b} Андрей Львович"

    # дано: запись заявителя B заведена загрузкой таблицы (предпросмотр, затем «Подтвердить»)
    page.goto("/servicedesk/requesters/import/")
    upload = page.locator('form[data-form="import-upload"]')
    expect(upload).to_be_visible()
    table = helpers_sd.make_table([["Почта", "Фамилия", "Имя", "Отчество"],
                                   [addr_b, last_b, "Андрей", "Львович"]], "csv", bom=True)
    helpers_org.upload_file(upload, table, name="requesters.csv", mime="text/csv")
    expect(page.locator("[data-import-preview]")).to_be_visible()
    page.locator('form[data-form="import-confirm"] button[type=submit]').click()
    expect(page.locator("[data-result-summary]")).to_have_attribute("data-added", "1")

    # когда: приходят три письма — с именем в «От», без имени (запись есть), без имени (записи нет)
    helpers_sd.deliver(build_mail(from_addr=f"{name_a} <{addr_a}>", to=[MAILBOX], subject=f"Имя в заголовке {word_a}",
                                  text=f"Первое письмо {word_a}", message_id=_message_id()))
    helpers_sd.deliver(build_mail(from_addr=addr_b, to=[MAILBOX], subject=f"Имя из записи {word_b}",
                                  text=f"Второе письмо {word_b}", message_id=_message_id()))
    helpers_sd.deliver(build_mail(from_addr=addr_c, to=[MAILBOX], subject=f"Имени нет {word_c}",
                                  text=f"Третье письмо {word_c}", message_id=_message_id()))

    # п. 9, случай 1: ФИО — имя из заголовка; в списке — имя
    number_a = helpers_sd.ticket_number_by_subject(page, word_a)
    expect(_requester_cell(page, number_a)).to_contain_text(name_a)
    card = helpers_sd.open_ticket(page, number_a)
    assert helpers_sd.field_text(card, "requester-name") == name_a
    assert addr_a in helpers_sd.field_text(card, "requester-email").lower()

    # случай 2: имени нет — ФИО из записи («Фамилия Имя Отчество»)
    number_b = helpers_sd.ticket_number_by_subject(page, word_b)
    expect(_requester_cell(page, number_b)).to_contain_text(name_b)
    card = helpers_sd.open_ticket(page, number_b)
    assert helpers_sd.field_text(card, "requester-name") == name_b

    # случай 3: нет ни имени, ни записи — ФИО пусто, в списке показан адрес
    number_c = helpers_sd.ticket_number_by_subject(page, word_c)
    expect(_requester_cell(page, number_c)).to_contain_text(addr_c)
    card = helpers_sd.open_ticket(page, number_c)
    expect(card.locator('[data-field="requester-name"]')).to_have_attribute("data-empty", "true")
    assert addr_c in helpers_sd.field_text(card, "requester-email").lower()

    # исполнитель правит ФИО в заявке (случай 3): карточка и список показывают новое имя
    new_c = f"Поправлено-{word_c} Мария Ивановна"
    fields = card.locator('form[data-form="ticket-fields"]')
    fields.locator("input[name=requester_name]").fill(new_c)
    fields.locator('button[type=submit]:not([name="save_to_record"])').click()
    expect(card.locator('[data-field="requester-name"]')).to_contain_text(new_c)
    helpers_sd.ticket_number_by_subject(page, word_c)
    expect(_requester_cell(page, number_c)).to_contain_text(new_c)

    # и в записи заявителя (случай 2): правка на странице `/servicedesk/requesters/<id>/edit/`
    page.goto("/servicedesk/requesters/?" + urllib.parse.urlencode({"q": addr_b}))
    row = page.locator("tr[data-requester]").filter(has=page.locator('[data-cell="email"]', has_text=addr_b))
    expect(row).to_have_count(1)
    expect(row.locator('[data-cell="name"]')).to_contain_text(name_b)
    record_id = row.get_attribute("data-id")
    new_b = f"Исправлено-{word_b} Олег Петрович"
    page.goto(f"/servicedesk/requesters/{record_id}/edit/")
    record_form = page.locator('form[data-form="requester"]')
    expect(record_form).to_be_visible()
    record_form.locator("input[name=name]").fill(new_b)
    record_form.locator("button[type=submit]").click()
    page.wait_for_url(re.compile(r".*/servicedesk/requesters/(\?.*)?$"))
    page.goto("/servicedesk/requesters/?" + urllib.parse.urlencode({"q": addr_b}))
    row = page.locator("tr[data-requester]").filter(has=page.locator('[data-cell="email"]', has_text=addr_b))
    expect(row.locator('[data-cell="name"]')).to_contain_text(new_b)
