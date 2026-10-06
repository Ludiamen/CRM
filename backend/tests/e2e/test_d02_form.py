"""T-3141: сценарий 2 — открытая форма «Подать заявку в ИТ-отдел» (FR-203, FR-204, FR-208, FR-222…FR-227, FR-238,
FR-253, FR-255, FR-261, FR-269, FR-274, FR-283, NFR-208)."""
import re
import secrets
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org, helpers_sd
from tests.e2e.helpers_sd import FOREIGN_DOMAIN, MAILBOX

MOSCOW = ZoneInfo("Europe/Moscow")
DONE_URL = re.compile(r"/request/done/")


# --- Свои помощники файла ---------------------------------------------------------------------------

def _word() -> str:
    """Уникальное слово темы: не из одних цифр (поиск списка считает строку из цифр номером заявки): буква и шесть
    шестнадцатеричных знаков (доп. 41 (в))."""
    return f"t{secrets.token_hex(3)}"


def _tok() -> str:
    return secrets.token_hex(3)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _fake_ip() -> str:
    """Адрес клиента для `X-Forwarded-For` (сеть TEST-NET-3): у каждого теста свой счётчик порога (7.4)."""
    return f"203.0.113.{secrets.randbelow(250) + 2}"


def _guest(new_context, *, ip: str | None = None, **kwargs):
    """Страница без входа: новый контекст без сессии, свой адрес клиента в `X-Forwarded-For` (задание T-3141)."""
    context = new_context(extra_http_headers={"X-Forwarded-For": ip or _fake_ip()}, **kwargs)
    return context.new_page()


def _default_priority_name(page) -> str:
    """Критичность по умолчанию — выбранный пункт `select[name=default_priority]` настроек (доп. 41 (д))."""
    page.goto("/servicedesk/")
    form = page.locator('form[data-form="servicedesk-settings"]')
    expect(form).to_be_visible()
    return form.locator("select[name=default_priority] option:checked").inner_text().strip()


def _read_form_limit(page) -> int:
    """Читает `form_hourly_limit` со страницы настроек; вызывать ДО `try` (урок RE-0b: читать до `try`, менять внутри)."""
    page.goto("/servicedesk/")
    form = page.locator('form[data-form="servicedesk-settings"]')
    expect(form).to_be_visible()
    return int(form.locator("input[name=form_hourly_limit]").input_value())


def _write_form_limit(page, value: int) -> None:
    """Ставит `form_hourly_limit` формой настроек (12.6); зовётся внутри `try`, возврат — в `finally`."""
    page.goto("/servicedesk/")
    form = page.locator('form[data-form="servicedesk-settings"]')
    expect(form).to_be_visible()
    field = form.locator("input[name=form_hourly_limit]")
    field.fill(str(value))
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    refusal = page.locator("[data-error], [role=alert][data-code]")  # доп. 41 (б): [data-warning] — не отказ
    if refusal.count():
        raise AssertionError(f"порог формы не принят: {refusal.first.get_attribute('data-code')}")
    expect(page.locator("[role=status]").first).to_be_visible()


def _new_value(page, kind: str, name: str, *, queue_id=None, on_form: bool = True, default_assignee=None) -> str:
    """Значение справочника формой `form[data-form="dictionary"]` (12.6, 13.7): `kind` — `categories` или
    `client-units`. У категории: `queue`, `on_form`, `default_assignee` (необязательно), `order`. Возвращает `data-id`
    строки нового значения в списке вида."""
    page.goto(f"/servicedesk/dictionaries/{kind}/new/")
    form = page.locator('form[data-form="dictionary"]')
    expect(form).to_be_visible()
    form.locator("input[name=name]").fill(name)
    if kind == "categories":
        form.locator("input[name=order]").fill("50")  # доп. 42 (г): поле заполняет сама приёмка
        form.locator("select[name=queue]").select_option(value=str(queue_id))
        if default_assignee is not None:
            form.locator("select[name=default_assignee]").select_option(value=str(default_assignee))
        form.locator("input[type=checkbox][name=on_form]").set_checked(on_form)
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    refusal = page.locator("[data-error], [role=alert][data-code]")
    if refusal.count():
        raise AssertionError(f"значение справочника не создано: {refusal.first.get_attribute('data-code')}")
    row = page.locator("tr[data-dictionary-row]").filter(has=page.locator('[data-cell="name"]', has_text=name))
    expect(row).to_have_count(1)
    return row.get_attribute("data-id")


def _new_queue(page) -> tuple:
    """Новая очередь: узел `org` под корнем с отметкой очереди (13.7); возвращает `(id, название)`."""
    name = helpers_org.unique_name("queue")
    queue_id = helpers_org.create_unit(page, name)
    helpers_sd.mark_queue(page, queue_id)
    return queue_id, name


def _import_record(page, email: str, *, unit: str = "") -> None:
    """Запись заявителя загрузкой таблицы (13.8): загрузка, предпросмотр, «Подтвердить», итог; подразделение —
    название уже заведённого значения справочника (пусто — подразделение в записи пусто)."""
    rows = [["Почта", "Фамилия", "Имя", "Отчество", "Подразделение"], [email, "Тестов", "Тест", "Тестович", unit]]
    page.goto("/servicedesk/requesters/import/")
    upload = page.locator('form[data-form="import-upload"]')
    expect(upload).to_be_visible()
    helpers_org.upload_file(upload, helpers_sd.make_table(rows, "csv"), name="requesters.csv", mime="text/csv")
    page.wait_for_url(re.compile(r"/servicedesk/requesters/import/\d+/$"))
    confirm = page.locator('form[data-form="import-confirm"]')
    expect(confirm).to_be_visible()
    confirm.locator("button[type=submit]").click()
    summary = page.locator("[data-result-summary]")
    expect(summary).to_be_visible()
    expect(summary).to_have_attribute("data-errors", "0")


def _record_unit(page, email: str) -> str:
    """Подразделение в записи заявителя: ячейка `client-unit` строки по адресу (13.8)."""
    page.goto("/servicedesk/requesters/?q=" + email)
    row = page.locator("tr[data-requester]")
    expect(row).to_have_count(1)
    return row.locator('[data-cell="client-unit"]').inner_text().strip()


def _open_form(page):
    """Открытая форма `/request/` (без входа); возвращает локатор формы."""
    page.goto("/request/")
    form = page.locator('form[data-form="request"]')
    expect(form).to_be_visible()
    return form


def _fill_request(form, *, email: str, word: str, category: str, name: str = "Тестов Тест Тестович",
                  unit: str | None = None, consent: bool = True, files: list | None = None) -> str:
    """Заполняет форму (13.6); `unit=None` — «Нет в списке»; `files` — список словарей Playwright
    (`name`, `mimeType`, `buffer`). Возвращает тему (в ней и в тексте — уникальное слово)."""
    subject = f"Заявка с формы {word}"
    form.locator("input[name=email]").fill(email)
    form.locator("input[name=name]").fill(name)
    if unit is None:
        form.locator("select[name=client_unit]").select_option(value="")
    else:
        form.locator("select[name=client_unit]").select_option(label=unit)
    form.locator("select[name=category]").select_option(label=category)
    form.locator("input[name=subject]").fill(subject)
    form.locator("textarea[name=text]").fill(f"Не работает устройство {word}")
    if files:
        form.locator("input[type=file][name=files]").set_input_files(files)
    form.locator("input[name=consent]").set_checked(consent)
    return subject


def _submit(form, *, skip_validation: bool = False) -> None:
    """Отправляет форму. `skip_validation` снимает проверку браузера (`required` у обязательных полей, 13.6):
    иначе браузер не отправил бы пустое поле и сервер не показал бы свой отказ."""
    if skip_validation:
        form.evaluate("f => { f.noValidate = true; }")
    form.locator("button[type=submit]").click()


def _submit_ok(page, form) -> tuple:
    """Отправляет верно заполненную форму; ждёт `/request/done/` и сразу читает страницу (адрес из сессии
    удаляется при первом показе, решение D1). Возвращает `(текст [data-request-done], адрес [data-done-email])`."""
    _submit(form)
    page.wait_for_url(DONE_URL)
    done = page.locator("[data-request-done]")
    expect(done).to_be_visible()
    return _norm(done.inner_text()), page.locator("[data-done-email]").inner_text().strip()


def _send_form(page, **kwargs) -> tuple:
    """Открывает форму, заполняет (`_fill_request`), отправляет; возвращает `(тема, текст принятия, адрес)`."""
    form = _open_form(page)
    subject = _fill_request(form, **kwargs)
    done_text, done_email = _submit_ok(page, form)
    return subject, done_text, done_email


def _ticket(page, word: str) -> tuple:
    """Номер заявки по слову темы и её карточка (от имени администратора)."""
    number = helpers_sd.ticket_number_by_subject(page, word)
    return number, helpers_sd.open_ticket(page, number)


def _category(page, queue_id, *, on_form: bool = True, default_assignee=None, prefix: str = "Принтер") -> str:
    """Категория с уникальным названием; возвращает название."""
    name = f"{prefix} {_tok()}"
    _new_value(page, "categories", name, queue_id=queue_id, on_form=on_form, default_assignee=default_assignee)
    return name


def _short_name(full_name: str) -> str:
    """«Имя Фамилия» по правилу C5 (10.3): слов два и больше — «второе первое», иначе как есть."""
    words = full_name.split()
    return f"{words[1]} {words[0]}" if len(words) >= 2 else full_name


# --- Тесты ---------------------------------------------------------------------------------------------------

def test_d02_form_creates_ticket_in_category_queue_source_form_number_not_shown_confirmation_sent(
        admin_page, new_context, mailpit):
    """Сценарий 2, п. 1: форма с категорией «Принтер» создаёт заявку в очереди этой категории, источник «Форма»,
    подразделение выбранное, критичность по умолчанию; номер на странице не показан, подтверждение уходит на
    указанный адрес (FR-222, FR-223, FR-253)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    priority_name = _default_priority_name(page)
    # дано: категория «Принтер» в очереди, которая не очередь по умолчанию (так видно, что взята очередь категории)
    queue_id, queue_name = _new_queue(page)
    unit_name = f"Бухгалтерия {_tok()}"
    _new_value(page, "client-units", unit_name)
    category = _category(page, queue_id)
    word, email = _word(), helpers_sd.requester_email()
    guest = _guest(new_context)
    # когда: заявитель без входа заполняет и отправляет форму
    form = _open_form(guest)
    expect(guest.locator("#main-menu")).to_have_count(0)  # страница без меню (12.1)
    subject = _fill_request(form, email=email, word=word, category=category, unit=unit_name, name="Петров Пётр Петрович")
    done_text, done_email = _submit_ok(guest, form)
    # тогда: страница принятия называет адрес и не показывает номер
    assert f"Заявка принята. Подтверждение с номером придёт на {email}" in done_text
    assert done_email == email
    assert "#" not in done_text and "№" not in done_text
    number, card = _ticket(page, word)
    page_text = _norm(guest.locator("body").inner_text()).replace(email, "")  # FR-223: на всей странице, не только в блоке
    assert "#" not in page_text and "№" not in page_text
    assert not re.search(rf"(?<!\d){number}(?!\d)", page_text)
    # заявка: очередь категории, источник «Форма», подразделение выбранное, критичность по умолчанию
    assert queue_name in helpers_sd.field_text(card, "queue")
    assert category in helpers_sd.field_text(card, "category")
    assert unit_name in helpers_sd.field_text(card, "client-unit")
    assert helpers_sd.field_text(card, "source").lower() == "форма"
    assert priority_name.lower() in helpers_sd.field_text(card, "priority").lower()
    assert subject in helpers_sd.field_text(card, "subject")
    assert email in helpers_sd.field_text(card, "requester-email").lower()
    expect(card).to_have_attribute("data-kind", "new")
    # подтверждение с номером ушло на указанный адрес, письмо автоматическое (форма — auto-generated, 10.1)
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.confirmation", to=email)
    assert letter["Subject"] == f"[#{number}] {subject}"
    assert f"Ваша заявка принята под номером {number}." in _norm(letter["Text"])
    headers = helpers_sd.letter_headers(mailpit, letter["ID"])
    values = [v.lower() for key, vals in headers.items() if key.lower() == "auto-submitted" for v in vals]
    assert values == ["auto-generated"]


def test_d02_form_with_screenshot_attachment_attaches_file_to_ticket(admin_page, new_context):
    """Сценарий 2 (введение), FR-283: снимок экрана, приложенный к форме, виден во вложениях заявки: после проверки
    файл чистый и скачивается (FR-222, FR-283)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    category = _category(page, queue_id)
    word, email = _word(), helpers_sd.requester_email()
    file_name = f"screenshot-{word}.png"
    png = helpers.make_png(64, 48)
    guest = _guest(new_context)
    _send_form(guest, email=email, word=word, category=category,
               files=[{"name": file_name, "mimeType": "image/png", "buffer": png}])
    number = helpers_sd.ticket_number_by_subject(page, word)
    # вложения заявки — только внутри раздела `attachments` (13.3: общий поиск находит два элемента)
    deadline = time.monotonic() + 60
    while True:
        card = helpers_sd.open_ticket(page, number)
        item = card.locator('[data-section="attachments"] [data-attachment]')
        expect(item).to_have_count(1)
        state = item.get_attribute("data-state")
        if state == "clean":
            break
        assert state == "pending", f"вложение в состоянии {state}: снимок экрана должен пройти проверку"
        assert time.monotonic() < deadline, "вложение не стало чистым за 60 с"
        page.wait_for_timeout(2000)
    link = card.locator(f'[data-section="attachments"] a[href^="/tickets/{number}/files/"]')
    expect(link).to_have_count(1)
    expect(link).to_contain_text(file_name)
    response = page.request.get(link.get_attribute("href"))
    assert response.status == 200
    assert response.body()[:4] == b"\x89PNG"


def test_d02_foreign_domain_or_no_consent_refused_with_message_no_ticket(admin_page, new_context):
    """Сценарий 2, п. 2: адрес не из корпоративного домена или форма без галочки согласия — отказ понятным
    сообщением у поля, заявка не создаётся (FR-222)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    category = _category(page, queue_id)
    guest = _guest(new_context)
    # а) чужой домен
    word_foreign = _word()
    form = _open_form(guest)
    subject = _fill_request(form, email=f"user-{_tok()}@{FOREIGN_DOMAIN}", word=word_foreign, category=category)
    _submit(form)
    error = guest.locator('[data-error="email"]')
    expect(error).to_be_visible()
    expect(error).to_have_attribute("data-code", "bad_email")
    expect(error).to_contain_text("Укажите рабочую почту на корпоративном домене")
    expect(guest.locator("[data-request-done]")).to_have_count(0)
    expect(form.locator("input[name=subject]")).to_have_value(subject)  # введённое сохранено
    # б) без согласия (проверку браузера снимаем: у флажка `required`, иначе запрос не уйдёт)
    word_consent = _word()
    form = _open_form(guest)
    _fill_request(form, email=helpers_sd.requester_email(), word=word_consent, category=category, consent=False)
    assert form.locator("input[name=consent]").evaluate("e => e.validity.valueMissing")  # `required`: браузер не отправит
    _submit(form)
    expect(guest.locator("[data-request-done]")).to_have_count(0)
    _submit(form, skip_validation=True)  # серверный отказ — отдельная линия защиты
    error = guest.locator('[data-error="consent"]')
    expect(error).to_be_visible()
    expect(error).to_have_attribute("data-code", "consent_required")
    expect(guest.locator("[data-request-done]")).to_have_count(0)
    # заявок нет ни в одном случае
    assert helpers_sd.tickets_by_subject(page, word_foreign) == []
    assert helpers_sd.tickets_by_subject(page, word_consent) == []


def test_d02_department_not_in_list_taken_from_requester_record_or_empty(admin_page, new_context):
    """Сценарий 2, п. 3: «Нет в списке» — подразделение берётся из записи заявителя, если она есть, иначе пусто
    (FR-204, FR-261)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    category = _category(page, queue_id)
    unit_name = f"Склад {_tok()}"
    _new_value(page, "client-units", unit_name)
    email_known, email_unknown = helpers_sd.requester_email("known"), helpers_sd.requester_email("unknown")
    _import_record(page, email_known, unit=unit_name)
    assert unit_name in _record_unit(page, email_known)
    word_known, word_unknown = _word(), _word()
    guest = _guest(new_context)
    _send_form(guest, email=email_known, word=word_known, category=category, unit=None)
    _send_form(guest, email=email_unknown, word=word_unknown, category=category, unit=None)
    # запись есть — подразделение из записи
    _, card = _ticket(page, word_known)
    assert unit_name in helpers_sd.field_text(card, "client-unit")
    expect(card.locator('[data-field="client-unit"]')).to_have_attribute("data-empty", "false")
    # записи нет — подразделение пусто
    _, card = _ticket(page, word_unknown)
    expect(card.locator('[data-field="client-unit"]')).to_have_attribute("data-empty", "true")
    assert helpers_sd.field_text(card, "client-unit") == "не заполнено"


def test_d02_known_and_unknown_address_same_behaviour_no_prefill_no_hint(admin_page, new_context):
    """Сценарий 2, п. 4: известный и неизвестный адрес ведут себя на форме одинаково: ничего не подставляется и
    не подсказывается ни при вводе адреса, ни в ответе на отправку (FR-224)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    category = _category(page, queue_id)
    unit_name = f"Отдел {_tok()}"
    _new_value(page, "client-units", unit_name)
    email_known, email_unknown = helpers_sd.requester_email("known"), helpers_sd.requester_email("unknown")
    _import_record(page, email_known, unit=unit_name)  # у известного адреса есть и ФИО, и подразделение
    seen = {}
    word = _word()  # одно слово у обоих прогонов: введённый текст возвращается в форме и не должен различать прогоны
    for label, email in (("known", email_known), ("unknown", email_unknown)):
        guest = _guest(new_context)
        form = _open_form(guest)
        before_text = _norm(form.inner_text())  # до ввода: форма пуста, текст не зависит от адреса
        field = form.locator("input[name=email]")
        # у поля адреса нет запросов HTMX (они только у формы исполнителя, 13.6)
        assert field.get_attribute("hx-post") is None and field.get_attribute("hx-get") is None
        field.fill(email)
        field.press("Tab")  # событие `change`: подстановку, если бы она была, запустило бы оно
        guest.wait_for_load_state("networkidle")
        expect(form.locator("input[name=name]")).to_have_value("")
        expect(form.locator("select[name=client_unit]")).to_have_value("")
        # отправка без ФИО: ответ не должен подставить имя из записи
        _fill_request(form, email=email, word=word, category=category, name="")
        _submit(form, skip_validation=True)
        name_error = guest.locator('[data-error="name"]')
        expect(name_error).to_be_visible()
        expect(name_error).to_have_attribute("data-code", "requester_name_required")
        expect(form.locator("input[name=name]")).to_have_value("")
        expect(form.locator("select[name=client_unit]")).to_have_value("")
        refusals = sorted((e.get_attribute("data-error"), e.get_attribute("data-code"))
                          for e in guest.locator("[data-error]").all())
        alerts = sorted(e.get_attribute("data-code") for e in guest.locator("[role=alert][data-code]").all())
        error_texts = sorted(_norm(e.inner_text()) for e in guest.locator("[data-error], [role=alert]").all())
        seen[label] = (before_text, _norm(form.inner_text()), error_texts, refusals, alerts, form.locator("input[name=name]").input_value(),
                       form.locator("select[name=client_unit]").input_value())
    assert seen["known"] == seen["unknown"]
    # заявок нет: ФИО из записи не подставилось
    assert helpers_sd.tickets_by_subject(page, word) == []


def test_d02_only_categories_marked_for_form_listed_including_other(admin_page, new_context):
    """Сценарий 2, п. 5: на форме в списке категорий только отмеченные «показывать на форме», среди них «Другое»
    (FR-222, FR-269)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    shown = _category(page, queue_id, on_form=True, prefix="Видна")
    hidden = _category(page, queue_id, on_form=False, prefix="Скрыта")
    guest = _guest(new_context)
    form = _open_form(guest)
    select = form.locator("select[name=category]")
    expect(select).to_be_visible()
    options = [text.strip() for text in select.locator("option").all_inner_texts()]
    assert shown in options
    assert hidden not in options
    assert "Другое" in options


def test_d02_threshold_per_hour_refused_with_mailbox_address_no_ticket(admin_page, new_context):
    """Сценарий 2, п. 6: с одного адреса за час принято порог заявок — следующая получает понятный отказ с адресом
    ящика заявок, заявка не создаётся; считаются только принятые формы (FR-225)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    category = _category(page, queue_id)
    words = [_word() for _ in range(2)]
    word_invalid, word_over = _word(), _word()
    previous = _read_form_limit(page)
    try:
        _write_form_limit(page, 2)
        guest = _guest(new_context)
        # отказ по полю порог не расходует: форма без согласия не считается принятой
        form = _open_form(guest)
        _fill_request(form, email=helpers_sd.requester_email(), word=word_invalid, category=category, consent=False)
        _submit(form, skip_validation=True)
        expect(guest.locator('[data-error="consent"]')).to_be_visible()
        # две принятые формы
        for word in words:
            _send_form(guest, email=helpers_sd.requester_email(), word=word, category=category)
        # третья — отказ с адресом ящика
        form = _open_form(guest)
        _fill_request(form, email=helpers_sd.requester_email(), word=word_over, category=category)
        _submit(form)
        alert = guest.locator("[role=alert][data-code]")
        expect(alert).to_have_attribute("data-code", "rate_limited")
        expect(alert).to_contain_text("слишком много заявок за час")
        expect(alert).to_contain_text(MAILBOX)
        expect(guest.locator("[data-request-done]")).to_have_count(0)
    finally:
        _write_form_limit(page, previous)
    for word in words:
        helpers_sd.ticket_number_by_subject(page, word)
    assert helpers_sd.tickets_by_subject(page, word_over) == []
    assert helpers_sd.tickets_by_subject(page, word_invalid) == []


def test_d02_login_page_has_submit_request_link(admin_page, new_context):
    """Сценарий 2, п. 7: на странице входа без входа есть ссылка «Подать заявку в ИТ-отдел», ведущая на форму
    (FR-226)."""
    helpers_sd.ensure_ready(admin_page)  # приём открыт: по ссылке виден не «закрыто», а форма
    guest = _guest(new_context)
    guest.goto("/login/")
    link = guest.locator('a[data-login-link][href="/request/"]')
    expect(link).to_have_count(1)
    expect(link).to_have_text("Подать заявку в ИТ-отдел")
    link.click()
    expect(guest).to_have_url(re.compile(r"/request/$"))
    expect(guest.locator('form[data-form="request"]')).to_be_visible()
    expect(guest.locator("#main-menu")).to_have_count(0)


def test_d02_ticket_card_shows_pd_consent_with_date(admin_page, new_context):
    """Сценарий 2, п. 8: в карточке заявки с формы отмечено согласие на обработку ПДн с датой и временем по
    Москве (FR-227)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    category = _category(page, queue_id)
    word = _word()
    guest = _guest(new_context)
    before = datetime.now(MOSCOW)
    _send_form(guest, email=helpers_sd.requester_email(), word=word, category=category)
    after = datetime.now(MOSCOW)
    _, card = _ticket(page, word)
    text = helpers_sd.field_text(card, "consent")
    assert "согласие на обработку пдн" in text.lower()
    found = re.search(r"(\d{2})\.(\d{2})\.(\d{4}) (\d{2}):(\d{2})", text)
    assert found, f"в согласии нет даты ДД.ММ.ГГГГ ЧЧ:ММ: {text!r}"
    day, month, year, hour, minute = (int(part) for part in found.groups())
    marked = datetime(year, month, day, hour, minute, tzinfo=MOSCOW)
    assert before - timedelta(minutes=2) <= marked <= after + timedelta(minutes=2)  # граница суток — по Москве


def test_d02_category_default_assignee_assigned_in_progress_one_letter_names_executor(
        admin_page, new_context, employee, mailpit):
    """Сценарий 2, п. 9: категория с ответственным по умолчанию из участников её очереди — ответственный назначен
    сразу, статус «В работе», заявитель получает одно письмо — подтверждение с «Исполнитель: Имя Фамилия»;
    отдельного письма «взята в работу» нет (FR-238, FR-208, FR-253, FR-255)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    tok = _tok()
    surname, first = f"Фам{tok}", f"Имя{tok}"
    account = employee(full_name=f"{surname} {first}")
    queue_id, _ = _new_queue(page)
    helpers_sd.add_queue_member(page, queue_id, [account.id], q=surname)
    category = _category(page, queue_id, default_assignee=account.id)
    word, email = _word(), helpers_sd.requester_email()
    guest = _guest(new_context)
    _send_form(guest, email=email, word=word, category=category)
    number, card = _ticket(page, word)
    # ответственный назначен сразу, статус «В работе»
    assignee = helpers_sd.field_text(card, "assignee")
    assert surname in assignee and first in assignee
    expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "false")
    assert helpers_sd.field_text(card, "status").lower() == "в работе"
    expect(card).to_have_attribute("data-kind", "in_progress")
    expect(card.locator('ol[data-feed] li[data-kind="event"][data-event="assignee_changed"]')).to_have_count(1)
    # одно письмо — подтверждение с исполнителем
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.confirmation", to=email)
    assert f"Исполнитель: {_short_name(account.full_name)}" in _norm(letter["Text"])
    assert helpers_sd.no_letter(mailpit, number, "ticket.assigned", wait=10)  # письма «взята в работу» нет
    assert len(helpers_sd.ticket_letters(mailpit, number)) == 1


def test_d02_empty_requester_department_filled_from_form_in_ticket_and_record(admin_page, new_context):
    """Сценарий 2, п. 10: в записи заявителя подразделение пусто, форма с подразделением «Бухгалтерия» — оно
    попадает и в заявку, и в запись (FR-204, FR-261)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    category = _category(page, queue_id)
    unit_name = f"Бухгалтерия {_tok()}"
    _new_value(page, "client-units", unit_name)
    email, word = helpers_sd.requester_email(), _word()
    _import_record(page, email, unit="")
    assert unit_name not in _record_unit(page, email)  # дано: подразделение в записи пусто
    guest = _guest(new_context)
    _send_form(guest, email=email, word=word, category=category, unit=unit_name)
    _, card = _ticket(page, word)
    assert unit_name in helpers_sd.field_text(card, "client-unit")
    assert unit_name in _record_unit(page, email)


def test_d02_requester_department_kept_ticket_gets_form_department(admin_page, new_context):
    """Сценарий 2, п. 11: в записи заявителя подразделение «Склад», форма с подразделением «Бухгалтерия» — на
    заявке «Бухгалтерия», а в записи остаётся «Склад» (FR-204, FR-261)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    category = _category(page, queue_id)
    tok = _tok()
    stock, accounting = f"Склад {tok}", f"Бухгалтерия {tok}"
    _new_value(page, "client-units", stock)
    _new_value(page, "client-units", accounting)
    email, word = helpers_sd.requester_email(), _word()
    _import_record(page, email, unit=stock)
    assert stock in _record_unit(page, email)
    guest = _guest(new_context)
    _send_form(guest, email=email, word=word, category=category, unit=accounting)
    _, card = _ticket(page, word)
    unit_text = helpers_sd.field_text(card, "client-unit")
    assert accounting in unit_text and stock not in unit_text
    record = _record_unit(page, email)
    assert stock in record and accounting not in record


def test_d02_threshold_counts_client_address_behind_proxy_like_login_lockout(admin_page, new_context):
    """Сценарий 2, п. 12: форма открыта через прокси общества; порог считается по адресу клиента, определённому
    как при блокировке входа: с одного адреса третья заявка отклоняется, с другого — принимается (FR-225;
    SPEC-001 FR-036)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    category = _category(page, queue_id)
    ip_a = _fake_ip()
    ip_b = _fake_ip()
    while ip_b == ip_a:
        ip_b = _fake_ip()
    words_a = [_word() for _ in range(2)]
    word_over, word_other = _word(), _word()
    previous = _read_form_limit(page)
    try:
        _write_form_limit(page, 2)
        guest_a = _guest(new_context, ip=ip_a)
        guest_b = _guest(new_context, ip=ip_b)
        for word in words_a:
            _send_form(guest_a, email=helpers_sd.requester_email(), word=word, category=category)
        # тот же адрес клиента — отказ
        form = _open_form(guest_a)
        _fill_request(form, email=helpers_sd.requester_email(), word=word_over, category=category)
        _submit(form)
        expect(guest_a.locator("[role=alert][data-code]")).to_have_attribute("data-code", "rate_limited")
        expect(guest_a.locator("[data-request-done]")).to_have_count(0)
        # другой адрес клиента — свой счётчик, заявка принята
        _send_form(guest_b, email=helpers_sd.requester_email(), word=word_other, category=category)
    finally:
        _write_form_limit(page, previous)
    for word in words_a + [word_other]:
        helpers_sd.ticket_number_by_subject(page, word)
    assert helpers_sd.tickets_by_subject(page, word_over) == []


def test_d02_form_has_no_criticality_choice_ticket_gets_default_medium(admin_page, new_context):
    """Сценарий 2, п. 13: на форме нет выбора критичности, у заявки критичность по умолчанию из настроек
    (в спеке — «Средняя»; сверяется со значением настроек) (FR-203, FR-222, FR-274)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    category = _category(page, queue_id)
    priority_name = _default_priority_name(page)
    word = _word()
    guest = _guest(new_context)
    form = _open_form(guest)
    expect(form.locator("[name*=priority], [name*=critic], [name*=source]")).to_have_count(0)
    _fill_request(form, email=helpers_sd.requester_email(), word=word, category=category)
    _submit_ok(guest, form)
    _, card = _ticket(page, word)
    assert priority_name.lower() in helpers_sd.field_text(card, "priority").lower()


def test_d02_form_at_360px_no_horizontal_scroll(admin_page, new_context):
    """Сценарий 2 (узкая ширина), NFR-208: на ширине 360 px форма, её отказ и страница принятия без горизонтальной
    прокрутки; форму можно заполнить и отправить (NFR-208)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    category = _category(page, queue_id)
    guest = _guest(new_context, viewport={"width": 360, "height": 800})
    form = _open_form(guest)
    expect(form.locator("button[type=submit]")).to_be_visible()
    assert helpers.no_horizontal_scroll(guest)
    # состояние отказа (длинные тексты ошибок)
    _fill_request(form, email=f"user-{_tok()}@{FOREIGN_DOMAIN}", word=_word(), category=category, consent=False)
    _submit(form, skip_validation=True)
    expect(guest.locator('[data-error="email"]')).to_be_visible()
    assert helpers.no_horizontal_scroll(guest)
    # успешная отправка и страница принятия
    form = _open_form(guest)
    _fill_request(form, email=helpers_sd.requester_email(), word=_word(), category=category)
    _submit_ok(guest, form)
    assert helpers.no_horizontal_scroll(guest)
