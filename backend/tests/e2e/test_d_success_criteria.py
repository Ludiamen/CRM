"""T-3152: критерии успеха спеки среза 003, измеряемые временем и сквозными числами (FR-210, FR-215, FR-216, FR-220,
FR-222, FR-231, FR-234, FR-236, FR-244, FR-249, FR-253, FR-263, FR-269, FR-276, FR-278, FR-288, FR-289, NFR-202,
NFR-204, NFR-209).

Каждый тест проходит путь интерфейсом и сравнивает `time.monotonic()` с пределом критерия (plan.md, «Критерии
успеха спеки и чем они проверяются»). Подготовка, не входящая в критерий (письма в ящик, заведение людей), в замер не
входит. Человеческое время (минуты на настройку, на заявку) — ручной проход владельца: здесь проверяется, что путь
есть и не медленный. Нагрузка (500 мс при 100 пользователях) — locust, не e2e. Тесты «всё на стенде» начинаются со
сброса (`reset_stand_and_relogin`, доп. 40 (г)).
"""
import re
import secrets
import time
import urllib.parse

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org, helpers_sd
from tests.e2e.helpers_sd import FOREIGN_DOMAIN, MAILBOX
from tests.support_servicedesk import build_mail


def _word() -> str:
    """Уникальное слово темы: буква и шесть шестнадцатеричных знаков (доп. 41 (в): не из одних цифр)."""
    return f"t{secrets.token_hex(3)}"


def _message_id() -> str:
    return f"<{secrets.token_hex(8)}@client.test>"


def _deliver_ticket(page, *, sender=None, prefix: str = "Не печатает принтер") -> tuple:
    """Письмо корпоративного заявителя → заявка. Возвращает (номер, слово темы, адрес заявителя, тема)."""
    word, sender = _word(), sender or helpers_sd.requester_email()
    subject = f"{prefix} {word}"
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=subject,
                                  text=f"Принтер на втором этаже не печатает {word}", message_id=_message_id()))
    return helpers_sd.ticket_number_by_subject(page, word), word, sender, subject


def _submit_request_form(page, email: str, subject: str, text: str) -> None:
    """Открытая форма `/request/` (12.1, 13.6): обязательные поля, согласие, отправка, ждёт «Заявка принята»."""
    page.goto("/request/")
    form = page.locator('form[data-form="request"]')
    expect(form).to_be_visible()
    form.locator("input[name=email]").fill(email)
    form.locator("input[name=name]").fill("Тестов Тест Тестович")
    values = form.locator("select[name=category] option").evaluate_all(
        "options => options.map(o => o.value).filter(v => v)")
    assert values, "в форме нет ни одной категории (в том числе «Другое»)"
    form.locator("select[name=category]").select_option(values[0])
    form.locator("input[name=subject]").fill(subject)
    form.locator("textarea[name=text]").fill(text)
    form.locator("input[name=consent]").check()
    helpers.submit(form)
    page.wait_for_url(re.compile(r"/request/done/$"))
    expect(page.locator("[data-request-done]")).to_be_visible()


def _card(page, number: int):
    return page.locator(f'[data-ticket-card][data-number="{int(number)}"]')


def _reply(page, number: int, text: str) -> None:
    """Ответ заявителю формой `ticket-reply` открытой карточки; ждёт элемент `reply` с текстом в ленте."""
    card = _card(page, number)
    form = card.locator('form[data-form="ticket-reply"]')
    expect(form).to_be_visible()
    form.locator("textarea[name=text]").fill(text)
    helpers.submit(form)
    reply = _card(page, number).locator('ol[data-feed] li[data-entry][data-kind="reply"]')
    expect(reply.locator("[data-entry-text]")).to_contain_text(text)


def _close(page, number: int, resolution: str) -> None:
    """Закрытие через диалог `ticket-close` (13.1, 13.3): решение, подтверждение; ждёт закрытую карточку."""
    _card(page, number).locator('a[data-action="ticket-close"]').click()
    dialog = page.locator('#dialog-root [data-dialog="ticket-close"]')
    expect(dialog).to_be_visible()
    dialog.locator("textarea[name=resolution]").fill(resolution)
    helpers.submit(dialog.locator("form"))
    expect(_card(page, number)).to_have_attribute("data-kind", "closed")


def _inbound_total(page) -> int:
    """Число писем во «Входящих» по кнопке «показать количество» (12.6, 13.8)."""
    helpers_sd.open_inbound(page)
    page.locator('a[data-action="show-count"]').click()
    total = page.locator("[data-total]")
    expect(total).to_be_visible()
    found = re.search(r"\d+", total.inner_text())
    assert found, "в `[data-total]` нет числа"
    return int(found.group(0))


def test_mail_confirmation_reaches_mailpit_within_one_minute_of_ticket_creation_timed(admin_page, mailpit):
    """Критерий «подтверждение за 1 минуту», NFR-202, FR-253: после создания заявки из письма подтверждение с
    номером в теме приходит заявителю не позже 1 минуты (замер от создания заявки до письма в Mailpit)."""
    helpers_sd.ensure_ready(admin_page)
    word, sender = _word(), helpers_sd.requester_email()
    subject = f"Подтверждение за минуту {word}"
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=subject, text=f"Текст заявки {word}",
                                  message_id=_message_id()))
    started = time.monotonic()  # заявка создана: разбор письма завершён
    number = helpers_sd.ticket_number_by_subject(admin_page, word)
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.confirmation", to=sender, timeout=60)
    elapsed = time.monotonic() - started
    assert elapsed < 60, f"подтверждение пришло через {elapsed:.0f} с после создания заявки (предел 60 с)"
    assert letter["Subject"] == f"[#{number}] {subject}"


def test_form_ticket_submitted_within_two_minutes_timed(admin_page, new_context):
    """Критерий «заявка через форму за 2 минуты», FR-222: заявитель без входа открывает форму, заполняет и
    отправляет заявку — путь не дольше 2 минут машинного прохода (предел 120 с); заявка видна исполнителю,
    страница «Заявка принята» называет адрес (FR-222)."""
    helpers_sd.ensure_ready(admin_page)
    word, email = _word(), helpers_sd.requester_email("form")
    context = new_context()
    try:
        page = context.new_page()
        started = time.monotonic()
        _submit_request_form(page, email, f"Заявка с формы {word}", f"Не открывается почта {word}")
        elapsed = time.monotonic() - started
        assert elapsed < 120, f"заявка через форму отправлена за {elapsed:.0f} с (предел 120 с)"
        expect(page.locator("[data-done-email]")).to_contain_text(email)
    finally:
        context.close()
    number = helpers_sd.ticket_number_by_subject(admin_page, word)
    card = helpers_sd.open_ticket(admin_page, number)
    assert helpers_sd.field_text(card, "source") == "Форма"


def test_new_ticket_visible_within_ten_seconds_to_two_queue_members_in_unassigned_preset(admin_page, employee):
    """Критерий «новая заявка видна за 10 секунд», FR-210, FR-276: после разбора письма заявка без ответственного
    видна двум участникам очереди в пресете «Без ответственного» — у каждого страница с заявкой открывается не
    дольше 10 секунд (замер — от открытия страницы участником до строки заявки)."""
    queue_id, _name = helpers_sd.ensure_ready(admin_page)
    tag = secrets.token_hex(3)
    first = employee(full_name=f"Очередь{tag} Первый Тест")
    second = employee(full_name=f"Очередь{tag} Второй Тест")
    helpers_sd.add_queue_member(admin_page, queue_id, [first.id, second.id], q=f"Очередь{tag}")
    number, word, _sender, _subject = _deliver_ticket(admin_page)
    url = "/tickets/?" + urllib.parse.urlencode({"preset": "unassigned", "q": word})
    for account in (first, second):
        started = time.monotonic()
        account.page.goto(url)
        row = account.page.locator(f'#tickets-grid tr[data-ticket="{number}"]')
        expect(row).to_have_count(1, timeout=10_000)
        elapsed = time.monotonic() - started
        assert elapsed < 10, f"заявка видна участнику через {elapsed:.0f} с (предел 10 с)"
        expect(row).to_have_attribute("data-kind", "new")
        assert "не назначен" in row.locator('[data-cell="assignee"]').inner_text().lower()


def test_search_by_number_or_text_within_ten_seconds_timed(admin_page):
    """Критерий «поиск за 10 секунд», FR-278: заявка находится в списке поиском по номеру (адрес поиска) и поиском
    по слову из темы (поле `q` формы фильтра) — каждый поиск не дольше 10 секунд (замер — от открытия страницы до
    строки заявки)."""
    helpers_sd.ensure_ready(admin_page)
    number, word, _sender, _subject = _deliver_ticket(admin_page)
    # по номеру — готовым адресом поиска; по тексту — шагом интерфейса (поле `q` формы `tickets-filter`, 13.2)
    started = time.monotonic()
    admin_page.goto("/tickets/?" + urllib.parse.urlencode({"preset": "all", "q": str(number)}))
    expect(admin_page.locator(f'#tickets-grid tr[data-ticket="{number}"]')).to_have_count(1, timeout=10_000)
    elapsed = time.monotonic() - started
    assert elapsed < 10, f"поиск по номеру занял {elapsed:.0f} с (предел 10 с)"

    started = time.monotonic()
    admin_page.goto("/tickets/?preset=all")
    form = admin_page.locator("form#tickets-filter")
    expect(form).to_be_visible()
    form.locator("input[name=q]").fill(word)
    helpers.submit(form)
    rows = admin_page.locator("#tickets-grid tr[data-ticket]")
    expect(rows).to_have_count(1, timeout=10_000)  # остаётся одна строка: заявка со словом темы
    expect(rows).to_have_attribute("data-ticket", str(number))
    elapsed = time.monotonic() - started
    assert elapsed < 10, f"поиск по тексту занял {elapsed:.0f} с (предел 10 с)"


def test_reply_and_close_with_resolution_within_one_minute_timed(admin_page, mailpit):
    """Критерий «ответ и закрытие за 1 минуту», FR-244, FR-249: исполнитель отвечает заявителю и закрывает заявку с
    решением — оба действия вместе не дольше 1 минуты (замер от открытия карточки до закрытой карточки);
    заявитель получил письмо ответа и письмо о закрытии; решение видно в карточке (FR-244, FR-249)."""
    helpers_sd.ensure_ready(admin_page)
    number, word, sender, _subject = _deliver_ticket(admin_page)
    reply_text, resolution = f"Ответ исполнителя {_word()}", f"Заменён картридж {_word()}"
    helpers_sd.open_ticket(admin_page, number)
    started = time.monotonic()
    _reply(admin_page, number, reply_text)
    replied = time.monotonic()
    _close(admin_page, number, resolution)
    elapsed = time.monotonic() - started
    assert elapsed < 60, f"ответ и закрытие заняли {elapsed:.0f} с (предел 60 с)"
    card = _card(admin_page, number)
    expect(card.locator('[data-field="resolution"]')).to_contain_text(resolution)
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.reply", to=sender, timeout=60)
    assert time.monotonic() - replied < 60, "письмо ответа пришло позже 1 минуты (NFR-202)"
    assert reply_text in " ".join(letter["Text"].split())
    helpers_sd.wait_letter(mailpit, number, "ticket.closed", to=sender, timeout=60)


def test_setup_five_queues_ten_categories_through_interface_within_fifteen_minutes_timed(admin_page):
    """Критерий «5 очередей и 10 категорий за 15 минут», FR-231, FR-269: администратор интерфейсом заводит 5
    очередей (узел, отметка «очередь») и 10 категорий с очередями — путь не дольше 15 минут (предел 900 с);
    все 10 категорий видны в справочнике со своими очередями (FR-231, FR-269)."""
    helpers_sd.ensure_ready(admin_page)
    suffix = secrets.token_hex(3)
    started = time.monotonic()
    queues = []
    for i in range(5):
        name = helpers_org.unique_name(f"Очередь{i}")
        unit_id = helpers_org.create_unit(admin_page, name)
        helpers_sd.mark_queue(admin_page, unit_id)
        queues.append((unit_id, name))
    categories = []
    for i in range(10):
        unit_id, queue_name = queues[i % 5]
        name = f"Категория{i}-{suffix}"
        admin_page.goto("/servicedesk/dictionaries/categories/new/")
        form = admin_page.locator('form[data-form="dictionary"]')
        expect(form).to_be_visible()
        form.locator("input[name=name]").fill(name)
        form.locator("input[name=order]").fill(str(100 + i))
        helpers_org.set_choice(form, "queue", unit_id)
        helpers.submit(form)
        admin_page.wait_for_url(re.compile(r"/servicedesk/dictionaries/categories/(\?.*)?$"))
        categories.append((name, queue_name))
    elapsed = time.monotonic() - started
    assert elapsed < 900, f"настройка 5 очередей и 10 категорий заняла {elapsed:.0f} с (предел 900 с)"

    # результат виден пользователю: очереди отмечены, категории в справочнике с очередями
    helpers_sd.open_queues(admin_page)
    for unit_id, _name in queues:
        expect(admin_page.locator(f'ul[data-unit-tree] li[data-unit-id="{unit_id}"]')).to_have_attribute(
            "data-queue", "true")
    admin_page.goto("/servicedesk/dictionaries/categories/")
    for name, queue_name in categories:
        row = admin_page.locator("tr[data-dictionary-row]").filter(has=admin_page.locator('[data-cell="name"]',
                                                                                         has_text=name))
        expect(row).to_have_count(1)
        expect(row.locator('[data-cell="queue"]')).to_contain_text(queue_name)


def test_upload_1000_requesters_within_five_minutes_timed(admin_page):
    """Критерий «загрузка 1000 заявителей за 5 минут», FR-263, NFR-204: таблица на 1000 строк загружается
    интерфейсом (выбор файла, предпросмотр, подтверждение) не дольше 5 минут (предел 300 с); предпросмотр строится не
    дольше 10 с; итог «добавлено 1000» без ошибок (FR-263, NFR-204)."""
    helpers_sd.ensure_ready(admin_page)
    tag = secrets.token_hex(3)
    rows = [["Почта", "Фамилия", "Имя", "Отчество", "Подразделение"]]
    emails = []
    for i in range(1000):
        email = helpers_sd.requester_email(f"imp{i}")
        emails.append(email)
        rows.append([email, f"Загрузкин{tag}", "Тест", "Тестович", ""])
    content = helpers_sd.make_table(rows, "csv", ";", bom=True)

    admin_page.goto("/servicedesk/requesters/import/")
    form = admin_page.locator('form[data-form="import-upload"]')
    expect(form).to_be_visible()
    started = time.monotonic()
    helpers_org.upload_file(form, content, name="requesters.csv", mime="text/csv")
    admin_page.wait_for_url(re.compile(r"/servicedesk/requesters/import/\d+/$"), timeout=120_000)
    expect(admin_page.locator("[data-import-preview]")).to_be_visible()
    preview_elapsed = time.monotonic() - started
    assert preview_elapsed < 10, f"предпросмотр 1000 строк построен за {preview_elapsed:.0f} с (предел 10 с)"
    confirm = admin_page.locator('form[data-form="import-confirm"]')
    expect(confirm).to_be_visible()
    confirm.locator("button[type=submit]").click()
    summary = admin_page.locator("[data-result-summary]")
    expect(summary).to_be_visible(timeout=300_000)
    elapsed = time.monotonic() - started
    assert elapsed < 300, f"загрузка 1000 заявителей заняла {elapsed:.0f} с (предел 300 с)"
    expect(summary).to_have_attribute("data-added", "1000")
    expect(summary).to_have_attribute("data-errors", "0")
    # записи видны в списке заявителей
    admin_page.goto("/servicedesk/requesters/?" + urllib.parse.urlencode({"q": emails[-1]}))
    expect(admin_page.locator("tr[data-requester]")).to_have_count(1)


def test_every_appended_mail_has_outcome_in_inbound_count_equals_append_count(
        browser, browser_context_args, stand_admin, admin_page):
    """Критерий «у 100 % писем итог», FR-220, NFR-209: на чистом стенде в ящик кладутся письма разных видов
    (две заявки, ответ в заявку, чужой домен, автоматическое, с адреса ящика, прочитанное другим клиентом) —
    число писем во «Входящих» (по кнопке «показать количество») равно числу `APPEND`, у каждого письма есть итог, а
    заявок по ним ровно столько, сколько создающих писем (FR-220, NFR-209)."""
    helpers_sd.reset_stand_and_relogin(browser, browser_context_args, stand_admin, admin_page)
    helpers_sd.ensure_ready(admin_page)
    page = admin_page
    baseline = _inbound_total(page)

    first_word, second_word, reply_word = _word(), _word(), _word()
    foreign_word, auto_word, box_word = _word(), _word(), _word()
    first, second = helpers_sd.requester_email(), helpers_sd.requester_email()

    def mail(sender, word, **extra):
        return build_mail(from_addr=sender, to=[MAILBOX], subject=extra.pop("subject", f"Письмо {word}"),
                          text=f"Текст письма {word}", message_id=_message_id(), **extra)

    helpers_sd.deliver(mail(first, first_word))
    number = helpers_sd.ticket_number_by_subject(page, first_word)
    helpers_sd.deliver(mail(second, second_word), seen=True)  # прочитано другим клиентом (FR-211)
    helpers_sd.deliver(mail(first, reply_word, subject=f"Re: [#{number}] Письмо {reply_word}"))
    helpers_sd.deliver(mail(f"alien@{FOREIGN_DOMAIN}", foreign_word))
    helpers_sd.deliver(mail(helpers_sd.requester_email("auto"), auto_word,
                            headers={"Auto-Submitted": "auto-generated"}))
    helpers_sd.deliver(mail(MAILBOX, box_word))
    appended = 6

    # итог у каждого письма: код `data-outcome` (CONTRACT-003, строка 216) и подпись (§ 14.3)
    expected = ((first_word, "created", "создана заявка"), (second_word, "created", "создана заявка"),
                (reply_word, "appended", "добавлено в заявку"),
                (foreign_word, "rejected_domain", "отклонено: чужой домен"),
                (auto_word, "auto", "автоматическое письмо"),
                (box_word, "rejected_self", "отклонено: письмо с адреса ящика заявок"))
    helpers_sd.open_inbound(page)
    for word, code, outcome in expected:
        row = helpers_sd.inbound_row(page, subject=word)
        expect(row).to_have_count(1)
        assert row.get_attribute("data-outcome") == code, f"у письма {word} код итога не {code}"
        assert outcome in row.locator('[data-cell="outcome"]').inner_text().lower(), f"итог письма {word}"
    # число писем во «Входящих» равно числу APPEND
    assert _inbound_total(page) == baseline + appended, "число писем во «Входящих» не равно числу APPEND"
    # заявки: ровно две (письма вида «создана заявка»), ответ не создал третью
    page.goto("/tickets/?preset=all")
    expect(page.locator("#tickets-grid tr[data-ticket]")).to_have_count(2)


def test_foreign_domain_and_automatic_mails_create_zero_tickets(
        browser, browser_context_args, stand_admin, admin_page, mailpit):
    """Критерий «чужой домен и автоматические письма — 0 заявок», FR-215, FR-216: на чистом стенде письма с чужого
    домена, автоматические (`Auto-Submitted`, `Precedence: bulk`, пустой `Return-Path`) и с адреса ящика не дают
    заявок и заявителям не отвечают (в Mailpit писем на их адреса нет) и в существующую заявку не дописываются;
    письмо-образец создаёт ровно одну заявку; у каждого лишнего письма на странице «Входящие письма» свой итог
    (FR-215, FR-216)."""
    helpers_sd.reset_stand_and_relogin(browser, browser_context_args, stand_admin, admin_page)
    helpers_sd.ensure_ready(admin_page)
    page = admin_page
    control, foreign, auto, bulk, null_path, box = (_word() for _ in range(6))

    def mail(sender, word, **extra):
        return build_mail(from_addr=sender, to=[MAILBOX], subject=f"Письмо {word}", text=f"Текст письма {word}",
                          message_id=_message_id(), **extra)

    control_sender = helpers_sd.requester_email()
    foreign_sender, auto_sender = f"alien@{FOREIGN_DOMAIN}", helpers_sd.requester_email("auto")
    bulk_sender, null_sender = helpers_sd.requester_email("bulk"), helpers_sd.requester_email("null")
    helpers_sd.deliver(mail(control_sender, control))
    helpers_sd.deliver(mail(foreign_sender, foreign))
    helpers_sd.deliver(mail(auto_sender, auto, headers={"Auto-Submitted": "auto-replied"}))
    helpers_sd.deliver(mail(bulk_sender, bulk, headers={"Precedence": "bulk"}))
    helpers_sd.deliver(mail(null_sender, null_path, headers={"Return-Path": "<>"}))
    helpers_sd.deliver(mail(MAILBOX, box))
    control_number = helpers_sd.ticket_number_by_subject(page, control)
    # в существующую заявку не дописываются: ответы `Re: [#N]` с чужого домена и автоматическое (FR-215, FR-216)
    foreign_reply, auto_reply = _word(), _word()
    helpers_sd.deliver(mail(foreign_sender, foreign_reply, subject=f"Re: [#{control_number}] Письмо {foreign_reply}"))
    helpers_sd.deliver(mail(auto_sender, auto_reply, subject=f"Re: [#{control_number}] Письмо {auto_reply}",
                            headers={"Auto-Submitted": "auto-replied"}))

    # заявок ровно одна — образец; по лишним письмам слова темы ничего не находят
    page.goto("/tickets/?preset=all")
    rows = page.locator("#tickets-grid tr[data-ticket]")
    expect(rows).to_have_count(1)
    expect(rows).to_have_attribute("data-ticket", str(control_number))
    for word in (foreign, auto, bulk, null_path, box, foreign_reply, auto_reply):
        assert helpers_sd.tickets_by_subject(page, word) == [], f"по письму {word} создана заявка"
    # итоги на странице «Входящие письма» (подписи § 14.3)
    expected = ((foreign, "отклонено: чужой домен"), (auto, "автоматическое письмо"),
                (bulk, "автоматическое письмо"), (null_path, "автоматическое письмо"),
                (box, "отклонено: письмо с адреса ящика заявок"),
                (foreign_reply, "отклонено: чужой домен"), (auto_reply, "автоматическое письмо"))
    for word, outcome in expected:
        assert outcome in helpers_sd.inbound_outcome(page, subject=word).lower(), f"итог письма {word}"
    # в ленте образца по-прежнему одно входящее письмо
    helpers_sd.open_ticket(page, control_number)
    expect(_card(page, control_number).locator('ol[data-feed] li[data-kind="incoming"]')).to_have_count(1)

    # заявителям не отвечают: подтверждение получил только образец, на прочие адреса и адрес ящика писем нет
    helpers_sd.wait_letter(mailpit, control_number, "ticket.confirmation", to=control_sender, timeout=60)
    # ответ исполнителя встаёт в очередь почты ПОСЛЕ разбора чужих писем: его приход значит, что все ранее
    # поставленные письма уже отправлены
    _reply(page, control_number, f"Ответ {_word()}")
    helpers_sd.wait_letter(mailpit, control_number, "ticket.reply", to=control_sender, timeout=60)
    page.wait_for_timeout(3_000)  # запас на второй рабочий процесс
    silent = {addr.lower() for addr in (foreign_sender, auto_sender, bulk_sender, null_sender, MAILBOX)}
    for short in mailpit.messages():
        for key in ("To", "Cc", "Bcc"):
            got = {a["Address"].lower() for a in (short.get(key) or [])} & silent
            assert not got, f"письмо «{short.get('Subject')}» ушло на {sorted(got)}"


def test_user_without_queue_access_sees_zero_tickets_in_list_by_link_and_in_search(
        browser, browser_context_args, stand_admin, admin_page, employee):
    """Критерий «без доступа — 0 заявок», FR-234, FR-236: заявка очереди A — у участника другой очереди B в списке
    «Все» и в поиске (по слову и по номеру) её нет и счётчик 0, по ссылке — 404; у сотрудника вне очередей нет
    пункта «Заявки»: список и счётчик — 403, ссылка на заявку и её файл — 404; участник очереди A заявку
    видит (контроль). (FR-234, FR-236)."""
    helpers_sd.reset_stand_and_relogin(browser, browser_context_args, stand_admin, admin_page)
    queue_a, _name = helpers_sd.ensure_ready(admin_page)
    tag = secrets.token_hex(3)
    queue_b = helpers_org.create_unit(admin_page, helpers_org.unique_name("Очередь-B"))
    helpers_sd.mark_queue(admin_page, queue_b)
    other = employee(full_name=f"ДругаяОчередь{tag} Первый Тест")
    outsider = employee(full_name=f"БезОчередей{tag} Второй Тест")
    member = employee(full_name=f"Участник{tag} Третий Тест")
    helpers_sd.add_queue_member(admin_page, queue_b, [other.id], q=f"ДругаяОчередь{tag}")
    helpers_sd.add_queue_member(admin_page, queue_a, [member.id], q=f"Участник{tag}")
    number, word, _sender, _subject = _deliver_ticket(admin_page)  # заявка уходит в очередь по умолчанию — A
    foreign_file = f"/tickets/{number}/files/00000000-0000-4000-8000-{secrets.token_hex(6)}/"

    # контроль: участник очереди A видит заявку
    assert helpers_sd.ticket_number_by_subject(member.page, word) == number

    # участник другой очереди: меню «Заявки» есть, заявок A нет — ни в списке, ни в поиске, ни по ссылке
    page = other.page
    page.goto("/tickets/?preset=all")
    expect(page.locator("[data-tickets-list]")).to_be_visible()
    expect(page.locator("#tickets-grid tr[data-ticket]")).to_have_count(0)
    for query in (word, str(number)):
        page.goto("/tickets/?" + urllib.parse.urlencode({"preset": "all", "q": query}))
        expect(page.locator("[data-tickets-list]")).to_be_visible()
        expect(page.locator("#tickets-grid tr[data-ticket]")).to_have_count(0)
        page.goto("/tickets/count/?" + urllib.parse.urlencode({"preset": "all", "q": query}))
        expect(page.locator("[data-total]")).to_have_text(re.compile(r"^\D*0\D*$"))
    assert helpers_org.direct_get(page, f"/tickets/{number}/").status == 404
    assert helpers_org.direct_get(page, foreign_file).status == 404

    # сотрудник вне очередей: пункта меню нет — список, поиск и счётчик 403, заявка и файл 404
    page = outsider.page
    for path in ("/tickets/", "/tickets/?" + urllib.parse.urlencode({"preset": "all", "q": word}),
                 "/tickets/count/?" + urllib.parse.urlencode({"preset": "all", "q": word})):
        assert helpers_org.direct_get(page, path).status == 403, f"{path}: не 403"
    assert helpers_org.direct_get(page, f"/tickets/{number}/").status == 404
    assert helpers_org.direct_get(page, foreign_file).status == 404


def test_journal_shows_changes_without_mail_texts_addresses_or_names(admin_page):
    """Критерий «100 % изменений в журнале, без текстов, адресов и ФИО», FR-288, FR-289: после создания заявки из
    письма, «взять себе», ответа, комментария, передачи в другую очередь с причиной и закрытия с решением в журнале
    есть событие каждого действия, а текстов письма, ответа, комментария, причины и решения, темы, адреса и
    имени заявителя нет ни в событиях заявки, ни в событии заявителя (FR-288, FR-289)."""
    helpers_sd.ensure_ready(admin_page)
    page = admin_page
    tag = secrets.token_hex(3)
    word, body_word, reply_word, comment_word, reason_word, resolution_word = (_word() for _ in range(6))
    sender = helpers_sd.requester_email("journal")
    display = f"Zayavitel{tag} Testov"
    queue_b_name = helpers_org.unique_name("Очередь-J")
    queue_b = helpers_org.create_unit(page, queue_b_name)
    helpers_sd.mark_queue(page, queue_b)
    helpers_sd.deliver(build_mail(from_addr=f"{display} <{sender}>", to=[MAILBOX], subject=f"Журнал {word}",
                                  text=f"Текст письма {body_word}", message_id=_message_id()))
    number = helpers_sd.ticket_number_by_subject(page, word)

    # действия исполнителя над заявкой
    helpers_sd.open_ticket(page, number)
    card = _card(page, number)
    card.locator('form[data-form="ticket-take"] button[data-action="ticket-take"]').click()
    expect(_card(page, number).locator('[data-field="assignee"]')).to_have_attribute("data-empty", "false")
    form = _card(page, number).locator('form[data-form="ticket-comment"]')
    form.locator("textarea[name=text]").fill(f"Внутренняя заметка {comment_word}")
    helpers.submit(form)
    expect(_card(page, number).locator('li[data-kind="comment"]')).to_have_count(1)
    _reply(page, number, f"Ответ заявителю {reply_word}")
    _card(page, number).locator('a[data-action="ticket-transfer"]').click()
    dialog = page.locator('#dialog-root [data-dialog="ticket-transfer"]')
    expect(dialog).to_be_visible()
    dialog.locator("select[name=queue]").select_option(queue_b)
    dialog.locator("textarea[name=reason]").fill(f"Причина передачи {reason_word}")
    helpers.submit(dialog.locator("form"))
    expect(_card(page, number).locator('[data-field="queue"]')).to_contain_text(queue_b_name)
    _close(page, number, f"Решение {resolution_word}")

    # журнал: событие каждого действия (фильтр по действию и номеру заявки — точное равенство)
    for action in ("ticket.created", "ticket.assigned", "ticket.comment_added", "ticket.reply_sent",
                   "ticket.transferred", "ticket.closed"):
        assert len(helpers_org.audit_rows(page, action, number)) >= 1, f"нет события журнала {action}"
    # в журнале нет текстов, темы, адреса и имени заявителя: ни по заявке, ни по записи заявителя
    forbidden = [word, body_word, reply_word, comment_word, reason_word, resolution_word, sender,
                 sender.split("@", 1)[0], f"Zayavitel{tag}"]
    assert len(helpers_org.audit_rows(page, "queue.marked", queue_b)) >= 1, "нет события журнала queue.marked"
    expect(page.locator("tr[data-event-id]").first).to_be_visible()
    texts = [page.locator("body").inner_text()]  # событие очереди: название узла не запрещено
    page.goto(f"/audit/?object_id={number}")
    expect(page.locator("tr[data-event-id]").first).to_be_visible()
    texts.append(page.locator("body").inner_text())
    page.goto("/audit/?action=requester.created")
    expect(page.locator("tr[data-event-id]").first).to_be_visible()
    texts.append(page.locator("body").inner_text())
    for text in texts:
        for value in forbidden:
            assert value not in text, f"в журнале есть {value!r}"
