"""T-3145: сценарий 7 — исполнитель заводит заявку по звонку (FR-203, FR-228…FR-230, FR-233, FR-234, FR-236…FR-239,
FR-253, FR-255, FR-288)."""
import re
import secrets

from playwright.sync_api import expect

from tests.e2e import helpers_org, helpers_sd
from tests.e2e.helpers_sd import FOREIGN_DOMAIN

PD_LINE = ("Отправляя заявку, вы согласны на обработку ваших персональных данных (адрес, ФИО, подразделение и "
           "текст заявки) для работы ИТ-отдела.")
REF_RE = re.compile(r"/tickets/(\d+)/$")      # адрес карточки заявки (не `/tickets/new/`)
LIST_RE = re.compile(r"/tickets/(\?.*)?$")    # адрес списка заявок (не `/tickets/new/`)


# --- Помощники файла ----------------------------------------------------------------------------

def _word() -> str:
    """Уникальное слово темы: буква и шесть шестнадцатеричных знаков (не из одних цифр, иначе поиск списка принял
    бы его за номер заявки; доп. 41 (в))."""
    return f"t{secrets.token_hex(3)}"


def _norm(text: str) -> str:
    """Текст письма: пробелы и переводы строк сжаты в один пробел (переносы строк шаблона не важны)."""
    return " ".join(text.split())


def _header(headers: dict, name: str) -> list:
    """Значения заголовка из ответа Mailpit без учёта регистра имени (значения — списки)."""
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return []


def _person(employee, **kwargs):
    """Сотрудник с уникальной частью в ФИО «Фам<tok> Имя<tok> Отчество»: `(учётная запись, tok, «Имя Фамилия»)`.
    Короткое имя — по правилу C5 контракта 10.3 (второе слово, затем первое): так оно стоит в письмах. В
    интерфейсе имя ищем по `tok` — он есть и в полном, и в коротком виде."""
    tok = secrets.token_hex(3)
    account = employee(full_name=f"Фам{tok} Имя{tok} Отчество", **kwargs)
    return account, tok, f"Имя{tok} Фам{tok}"


def _new_queue(page, prefix: str = "Очередь"):
    """Новый узел, отмеченный очередью: `(id, название)`."""
    name = helpers_org.unique_name(prefix)
    unit_id = helpers_org.create_unit(page, name)
    helpers_sd.mark_queue(page, unit_id)
    return unit_id, name


def _member(page, queue_id, account, tok) -> None:
    """Делает сотрудника участником очереди (член узла) и проверяет, что добавление прошло."""
    note = helpers_sd.add_queue_member(page, queue_id, [account.id], q=tok)
    assert "уже участник" not in note, note
    helpers_org.open_structure(page, queue_id)
    expect(helpers_org.member_row(page, account.id)).to_have_count(1)


def _value(page, kind: str, name: str, **fields) -> str:
    """Значение справочника через `/servicedesk/dictionaries/<вид>/new/` (форма `dictionary`, 12.6, 13.7): `fields` —
    прочие поля формы (`queue`, `default_assignee`); возвращает номер строки `tr[data-dictionary-row][data-id]`."""
    page.goto(f"/servicedesk/dictionaries/{kind}/new/")
    form = page.locator('form[data-form="dictionary"]')
    expect(form).to_be_visible()
    form.locator("[name=name]").fill(name)
    order = form.locator("[name=order]")
    if order.count():  # доп. 42 (г): `order` заполняет сама приёмка
        order.first.fill("100")
    for key, value in fields.items():  # доп. 42 (г): `queue` и `default_assignee` — `select`
        form.locator(f'select[name="{key}"]').select_option(str(value))
    form.locator("button[type=submit]").click()
    page.wait_for_url(re.compile(rf"/servicedesk/dictionaries/{kind}/$"))
    row = page.locator("tr[data-dictionary-row]").filter(has=page.locator('[data-cell="name"]', has_text=name))
    expect(row).to_have_count(1)
    return row.get_attribute("data-id")


def _role_with_permission(admin_page, permission: str) -> str:
    """Создаёт роль с одним правом через `/roles/new/` и возвращает её название."""
    name = helpers_org.unique_name("Только-" + permission.split(".")[0])
    admin_page.goto("/roles/new/")
    form = admin_page.locator('form[action="/roles/new/"]')
    form.locator("[name=name]").fill(name)
    form.locator(f'input[name=permissions][value="{permission}"]').check()
    with admin_page.expect_response(lambda r: r.request.method == "POST" and "/roles/" in r.url):
        form.locator("button[type=submit]").click()
    admin_page.goto("/roles/")
    expect(admin_page.locator(f'[data-role-id][data-role-name="{name}"]')).to_have_count(1)
    return name


def _settings_priority(page, label: str | None = None) -> str:
    """Критичность по умолчанию на `/servicedesk/` (выбранный пункт `select[name=default_priority]`, доп. 41 (д));
    с `label` — сохраняет настройку формой и ждёт `[role=status]`. Возвращает прежнее название."""
    page.goto("/servicedesk/")
    form = page.locator('form[data-form="servicedesk-settings"]')
    expect(form).to_be_visible()
    current = form.locator("select[name=default_priority] option:checked").inner_text().strip()
    if label is not None:
        form.locator("select[name=default_priority]").select_option(label=label)
        with page.expect_navigation():
            form.locator("button[type=submit]").click()
        page.wait_for_load_state()
        expect(page.locator("[role=status]").first).to_be_visible()
    return current


# --- Форма «Новая заявка» исполнителя (12.3, 13.6, доп. 26) --------------------------------------------

def _form(page):
    return page.locator('form[data-form="ticket-new"]')


def _open_form(page):
    """`/tickets/new/` страницей целиком; ждёт форму."""
    page.goto("/tickets/new/")
    expect(_form(page)).to_be_visible()
    return _form(page)


def _enter_email(page, email: str) -> None:
    """Вводит адрес и уходит из поля (`change`): HTMX `POST /tickets/new/requester/` (адрес — в теле, не в
    адресе запроса). Ждёт ответ и замену обёртки `[data-requester-fields]` целиком (`outerHTML`, доп. 42 (д)):
    прежнее поле `name` отсоединено; значения новых полей проверяет вызывающий (`to_have_value`)."""
    form = _form(page)
    old = form.locator("input[name=name]").element_handle()
    with page.expect_response(lambda r: r.request.method == "POST"
                              and r.url.split("?")[0].endswith("/tickets/new/requester/")) as info:
        form.locator("input[name=email]").fill(email)
        form.locator("input[name=email]").press("Tab")
    assert "@" not in info.value.url, "адрес почты попал в адрес запроса"
    info.value.finished()
    page.wait_for_function("el => !el.isConnected", arg=old)


def _swap_queue_fields(page, select_locator, queue_id, **select_args) -> None:
    """Выбор в `select` с `hx-get` на `/tickets/new/queue/`: ждёт ответ и замену обёртки `[data-queue-fields]`
    целиком (доп. 42 (д)): прежнее поле `queue` отсоединено, в новом выбрана очередь `queue_id` — до ввода и
    отправки формы."""
    form = _form(page)
    old = form.locator("select[name=queue]").element_handle()
    with page.expect_response(lambda r: r.request.method == "GET" and "/tickets/new/queue/" in r.url):
        select_locator.select_option(**select_args)
    page.wait_for_function("el => !el.isConnected", arg=old)
    expect(form.locator("select[name=queue]")).to_have_value(str(queue_id))


def _choose_category(page, category_id, queue_id) -> None:
    """Выбирает категорию; `queue_id` — очередь этой категории: после подстановки она выбрана в `select[name=queue]`."""
    _swap_queue_fields(page, _form(page).locator("select[name=category]"), queue_id, value=str(category_id))


def _choose_queue(page, queue_id) -> None:
    """Меняет очередь на другую (не ту, что выбрана)."""
    _swap_queue_fields(page, _form(page).locator("select[name=queue]"), queue_id, value=str(queue_id))


def _fill_text(page, subject: str, text: str, *, source: str | None = None, priority: str | None = None) -> None:
    form = _form(page)
    if source is not None:
        form.locator("select[name=source]").select_option(label=source)
    if priority is not None:
        form.locator("select[name=priority]").select_option(label=priority)
    form.locator("input[name=subject]").fill(subject)
    form.locator("textarea[name=text]").fill(text)


def _create(page, *, email: str, category_id, category_queue, subject: str, text: str, name: str | None = None,
            queue_id=None, source: str | None = None, priority: str | None = None,
            take: bool | None = None) -> None:
    """Заполняет и отправляет форму; `category_queue` — очередь выбранной категории; результат (карточка или
    список) ждёт вызывающий."""
    _open_form(page)
    _enter_email(page, email)
    if name is not None:
        _form(page).locator("input[name=name]").fill(name)
    _choose_category(page, category_id, category_queue)
    if queue_id is not None:
        _choose_queue(page, queue_id)
    if take is not None:
        box = _form(page).locator("input[name=take]")
        expect(box).to_be_enabled()
        box.set_checked(take)
    _fill_text(page, subject, text, source=source, priority=priority)
    _form(page).locator("button[type=submit]").click()


def _created_number(page) -> int:
    """Ждёт переход на карточку созданной заявки (302 на `/tickets/<N>/`) и возвращает номер."""
    page.wait_for_url(REF_RE)
    return int(REF_RE.search(page.url).group(1))


def _card(page, number: int):
    card = page.locator(f'[data-ticket-card][data-number="{number}"]')
    expect(card).to_be_visible()
    return card


def _take_box(page):
    return _form(page).locator("input[name=take]")


# --- Тесты ------------------------------------------------------------------------------------------

def test_d07_known_requester_name_and_department_prefilled_and_editable(admin_page, employee):
    """Сценарий 7, п. 1: адрес есть в справочнике заявителей — после ввода адреса ФИО и подразделение
    подставляются, у неизвестного адреса поля пусты; подставленное исполнитель правит, и в заявке остаётся
    правка (FR-228, FR-229)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    account, tok, _short = _person(employee)
    _member(page, queue_id, account, tok)
    cat_id = _value(page, "categories", helpers_org.unique_name("Звонок"), queue=queue_id)
    word = _word()
    unit_a, unit_b = helpers_org.unique_name("Отдел-А"), helpers_org.unique_name("Отдел-Б")
    _value(page, "client-units", unit_a)
    _value(page, "client-units", unit_b)
    known, unknown = helpers_sd.requester_email("known"), helpers_sd.requester_email("unknown")
    last = f"Орлов-{word}"
    full_name = f"{last} Андрей Львович"

    # дано: запись заявителя заведена загрузкой таблицы (предпросмотр, затем «Подтвердить»), подразделение — А
    page.goto("/servicedesk/requesters/import/")
    upload = page.locator('form[data-form="import-upload"]')
    expect(upload).to_be_visible()
    table = helpers_sd.make_table([["Почта", "Фамилия", "Имя", "Отчество", "Подразделение"],
                                   [known, last, "Андрей", "Львович", unit_a]], "csv", bom=True)
    helpers_org.upload_file(upload, table, name="requesters.csv", mime="text/csv")
    expect(page.locator("[data-import-preview]")).to_be_visible()
    page.locator('form[data-form="import-confirm"] button[type=submit]').click()
    expect(page.locator("[data-result-summary]")).to_have_attribute("data-added", "1")

    # когда исполнитель вводит неизвестный адрес — ничего не подставляется
    ep = account.page
    form = _open_form(ep)
    _enter_email(ep, unknown)
    expect(form.locator("input[name=name]")).to_have_value("")
    expect(form.locator("select[name=client_unit]")).to_have_value("")

    # когда вводит известный адрес — ФИО и подразделение подставлены из записи
    _open_form(ep)
    _enter_email(ep, known)
    expect(_form(ep).locator("input[name=name]")).to_have_value(full_name)
    expect(_form(ep).locator("select[name=client_unit] option:checked")).to_have_text(unit_a)

    # п. 1: подставленное можно изменить — новое ФИО и подразделение Б; заявка хранит правку
    edited = f"Волков-{word} Дмитрий Павлович"
    _form(ep).locator("input[name=name]").fill(edited)
    _form(ep).locator("select[name=client_unit]").select_option(label=unit_b)
    _choose_category(ep, cat_id, queue_id)
    _fill_text(ep, f"Звонок {word}", f"Позвонил по телефону {word}", source="Телефон")
    _form(ep).locator("button[type=submit]").click()
    number = _created_number(ep)
    card = _card(ep, number)
    expect(card.locator('[data-field="requester-name"]')).to_contain_text(edited)
    expect(card.locator('[data-field="client-unit"]')).to_contain_text(unit_b)
    expect(card.locator('[data-field="requester-email"]')).to_contain_text(known)


def test_d07_take_to_self_gives_one_confirmation_with_executor_name_no_taken_letter(admin_page, employee, mailpit):
    """Сценарий 7, п. 2: «Взять себе» включён — исполнитель ответственный, вид статуса «в работе», заявитель
    получает ровно одно письмо (подтверждение со строкой «Исполнитель: Имя Фамилия.»), письма «взята в
    работу» нет (FR-230, FR-253, FR-255)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    account, tok, short = _person(employee)
    _member(page, queue_id, account, tok)
    cat_id = _value(page, "categories", helpers_org.unique_name("Звонок"), queue=queue_id)
    word, requester = _word(), helpers_sd.requester_email("call")
    subject, body = f"Не печатает принтер {word}", f"Принтер на втором этаже {word}"

    ep = account.page
    # кнопка «Новая заявка» у участника очереди есть (13.2)
    ep.goto("/tickets/")
    button = ep.locator('[data-tickets-list] > header a[data-action="ticket-new"]')
    expect(button).to_have_attribute("href", "/tickets/new/")
    _open_form(ep)
    _enter_email(ep, requester)
    _form(ep).locator("input[name=name]").fill(f"Кузнецов-{word} Павел")
    _choose_category(ep, cat_id, queue_id)
    # «Взять себе» включён по умолчанию и доступен участнику очереди
    expect(_take_box(ep)).to_be_enabled()
    expect(_take_box(ep)).to_be_checked()
    _fill_text(ep, subject, body, source="Телефон")
    _form(ep).locator("button[type=submit]").click()
    number = _created_number(ep)

    # п. 2: исполнитель ответственный, заявка «в работе»
    card = _card(ep, number)
    expect(card).to_have_attribute("data-kind", "in_progress")
    assert tok in helpers_sd.field_text(card, "assignee")
    # п. 2: заявитель получил подтверждение с именем исполнителя
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.confirmation", to=requester)
    assert letter["Subject"] == f"[#{number}] {subject}"
    text = _norm(letter["Text"])
    assert f"Ваша заявка принята под номером {number}." in text
    assert f"Тема: {subject}" in text
    assert f"Исполнитель: {short}." in text
    # п. 2: «взята в работу» не уходит; письмо подтверждения — одно
    assert helpers_sd.no_letter(mailpit, number, "ticket.assigned", wait=15), "ушло письмо «взята в работу»"
    assert len(helpers_sd.ticket_letters(mailpit, number)) == 1, "заявитель получил больше одного письма"
    assert len(helpers_sd.ticket_letters(mailpit, number, template="ticket.confirmation")) == 1


def test_d07_foreign_domain_address_refused(admin_page, employee):
    """Сценарий 7, п. 3: адрес не из корпоративного домена — портал отказывает у поля «почта», заявка не
    создаётся (FR-228)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    account, tok, _short = _person(employee)
    _member(page, queue_id, account, tok)
    cat_id = _value(page, "categories", helpers_org.unique_name("Звонок"), queue=queue_id)
    word = _word()
    foreign = f"ext-{secrets.token_hex(4)}@{FOREIGN_DOMAIN}"

    ep = account.page
    _create(ep, email=foreign, category_id=cat_id, category_queue=queue_id,
            subject=f"Чужой адрес {word}", text=f"Текст {word}", source="Телефон")
    # п. 3: отказ у поля адреса, текст — 14.1 (`bad_email`); перехода на карточку нет
    expect(_form(ep).locator('[data-error="email"]')).to_contain_text(
        "Укажите рабочую почту на корпоративном домене")
    assert not REF_RE.search(ep.url), ep.url
    # заявки нет
    assert helpers_sd.tickets_by_subject(page, word) == []


def test_d07_queue_taken_from_category_and_changeable_to_any_queue(admin_page, employee):
    """Сценарий 7, п. 4: выбрана категория другой очереди — очередь подставлена из категории, исполнитель
    меняет её на любую очередь, заявка создаётся в выбранной (FR-228)."""
    page = admin_page
    default_id, _ = helpers_sd.ensure_ready(page)
    q1_id, q1_name = _new_queue(page, "Очередь-1")
    q2_id, q2_name = _new_queue(page, "Очередь-2")
    account, tok, _short = _person(employee)
    _member(page, q1_id, account, tok)
    _member(page, q2_id, account, tok)
    cat_id = _value(page, "categories", helpers_org.unique_name("ВтораяОчередь"), queue=q2_id)
    word = _word()

    ep = account.page
    _open_form(ep)
    _enter_email(ep, helpers_sd.requester_email("call"))
    _choose_category(ep, cat_id, q2_id)
    # п. 4: очередь подставлена из категории
    expect(_form(ep).locator("select[name=queue]")).to_have_value(str(q2_id))
    # п. 4: выбрать можно любую отмеченную очередь, в том числе очередь по умолчанию
    for queue_id in (q1_id, q2_id, default_id):
        expect(_form(ep).locator(f'select[name=queue] option[value="{queue_id}"]')).to_have_count(1)
    _choose_queue(ep, q1_id)
    expect(_form(ep).locator("select[name=queue]")).to_have_value(str(q1_id))
    _fill_text(ep, f"Смена очереди {word}", f"Текст {word}", source="Телефон")
    _form(ep).locator("button[type=submit]").click()
    number = _created_number(ep)
    card = _card(ep, number)
    expect(card.locator('[data-field="queue"]')).to_contain_text(q1_name)
    assert q2_name not in helpers_sd.field_text(card, "queue")


def test_d07_non_member_queue_disables_take_to_self_creates_without_assignee_or_default_assignee(
        admin_page, employee):
    """Сценарий 7, п. 5: исполнитель не участник выбранной очереди — флажок «Взять себе» выключен и недоступен,
    заявка создаётся без ответственного, а у категории с ответственным по умолчанию — с ним (FR-228, FR-237,
    FR-238)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    q1_id, _q1_name = _new_queue(page, "Своя")
    q2_id, q2_name = _new_queue(page, "Чужая")
    account, tok, _short = _person(employee)
    other, tok_other, _short_other = _person(employee)
    _member(page, q1_id, account, tok)
    _member(page, q2_id, other, tok_other)
    own_cat = _value(page, "categories", helpers_org.unique_name("Своя"), queue=q1_id)
    plain_cat = _value(page, "categories", helpers_org.unique_name("БезОтв"), queue=q2_id)
    default_cat = _value(page, "categories", helpers_org.unique_name("СОтв"), queue=q2_id,
                         default_assignee=other.id)
    word_a, word_b = _word(), _word()
    ep = account.page

    # случай 1: категория чужой очереди без ответственного по умолчанию
    _open_form(ep)
    _enter_email(ep, helpers_sd.requester_email("call"))
    _choose_category(ep, own_cat, q1_id)
    expect(_form(ep).locator("select[name=queue]")).to_have_value(str(q1_id))
    expect(_take_box(ep)).to_be_enabled()  # в своей очереди флажок доступен
    _choose_queue(ep, q2_id)  # п. 5: исполнитель выбирает очередь, где он не участник
    expect(_take_box(ep)).to_be_disabled()
    expect(_take_box(ep)).not_to_be_checked()
    _choose_category(ep, plain_cat, q2_id)
    expect(_form(ep).locator("select[name=queue]")).to_have_value(str(q2_id))
    expect(_take_box(ep)).to_be_disabled()
    expect(_take_box(ep)).not_to_be_checked()
    _fill_text(ep, f"Чужая очередь {word_a}", f"Текст {word_a}", source="Телефон")
    _form(ep).locator("button[type=submit]").click()
    ep.wait_for_url(LIST_RE)  # заявка ему не видна: возврат в список (сценарий 7, п. 8)
    number_a = helpers_sd.ticket_number_by_subject(page, word_a)
    card = helpers_sd.open_ticket(page, number_a)
    expect(card.locator('[data-field="queue"]')).to_contain_text(q2_name)
    expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "true")
    assert helpers_sd.field_text(card, "assignee") == "не назначен"

    # случай 2: категория с ответственным по умолчанию (участник той очереди) — заявка у него
    _open_form(ep)
    _enter_email(ep, helpers_sd.requester_email("call"))
    _choose_category(ep, default_cat, q2_id)
    expect(_form(ep).locator("select[name=queue]")).to_have_value(str(q2_id))
    expect(_take_box(ep)).to_be_disabled()
    expect(_take_box(ep)).not_to_be_checked()
    _fill_text(ep, f"Ответственный по умолчанию {word_b}", f"Текст {word_b}", source="Телефон")
    _form(ep).locator("button[type=submit]").click()
    ep.wait_for_url(LIST_RE)
    number_b = helpers_sd.ticket_number_by_subject(page, word_b)
    card = helpers_sd.open_ticket(page, number_b)
    assert tok_other in helpers_sd.field_text(card, "assignee")
    assert tok not in helpers_sd.field_text(card, "assignee")
    expect(card).to_have_attribute("data-kind", "in_progress")


def test_d07_source_phone_or_in_person_kept_and_journal_names_creator(admin_page, employee):
    """Сценарий 7, п. 6: источник заявки — выбранный («Телефон» или «Лично»), в ленте и в журнале указано,
    кто создал заявку (FR-228, FR-288)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    account, tok, _short = _person(employee)
    _member(page, queue_id, account, tok)
    cat_id = _value(page, "categories", helpers_org.unique_name("Звонок"), queue=queue_id)
    ep = account.page
    numbers = {}
    for source in ("Телефон", "Лично"):
        word = _word()
        _create(ep, email=helpers_sd.requester_email("call"), category_id=cat_id, category_queue=queue_id,
                subject=f"Источник {word}",
                text=f"Текст {word}", source=source)
        numbers[source] = _created_number(ep)
        # п. 6: в карточке — выбранный источник
        card = _card(ep, numbers[source])
        expect(card.locator('[data-field="source"]')).to_contain_text(source)
        # п. 6: в ленте у первого элемента — автор, исполнитель
        author = card.locator('ol[data-feed] li[data-entry][data-kind="incoming"] [data-author]').first
        expect(author).to_contain_text(tok)
        expect(author).to_have_attribute("data-author-kind", "staff")

    # п. 6: в журнале — одно событие «Заявка создана» с названием источника и именем создателя (9.2)
    for source, number in numbers.items():
        sides = helpers_org.audit_sides(page, "ticket.created", number)
        assert len(sides) == 1, sides
        assert source in sides[0][1], sides[0]  # источник — в ячейке «стало»
        row = page.locator('tr[data-event-id][data-action="ticket.created"]')
        who = row.locator("td").nth(1).inner_text()  # создатель — в ячейке «Кто» (имя ищем по `tok`)
        assert tok in who, who


def test_d07_no_new_ticket_button_without_queue_and_direct_request_refused(admin_page, employee):
    """Сценарий 7, п. 7: сотрудник не участник ни одной очереди — кнопки «Новая заявка» нет, прямые обращения
    к форме и подстановкам отклоняются, заявка не создаётся (FR-234, FR-236). Проверка кнопки на `/` слабая по
    построению (кнопка бывает только в шапке `/tickets/`, а он отдаёт 403): держат 403 и отсутствие пункта «Заявки»."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    account, _tok, _short = _person(employee)
    ep = account.page
    word = _word()

    # п. 7: у сотрудника без очередей нет пункта «Заявки» и кнопки «Новая заявка»; список — отказ
    ep.goto("/")
    expect(ep.locator("#main-menu")).to_be_attached()
    expect(ep.locator('#main-menu a.menu-item[href="/tickets/"]')).to_have_count(0)
    expect(ep.locator('a[data-action="ticket-new"]')).to_have_count(0)
    assert helpers_org.direct_get(ep, "/tickets/").status == 403
    # п. 7: прямое обращение к форме, отправке и подстановкам — 403
    assert helpers_org.direct_get(ep, "/tickets/new/").status == 403
    assert helpers_org.direct_post(ep, "/tickets/new/", {
        "email": helpers_sd.requester_email("call"), "subject": f"Прямой запрос {word}",
        "text": f"Текст {word}"}).status == 403
    assert helpers_org.direct_post(ep, "/tickets/new/requester/",
                                   {"email": helpers_sd.requester_email("call")}).status == 403
    assert helpers_org.direct_get(ep, "/tickets/new/queue/?category=1").status == 403
    # заявка не создана
    assert helpers_sd.tickets_by_subject(page, word) == []


def test_d07_created_in_foreign_queue_says_created_returns_to_list_ticket_inaccessible(admin_page, employee):
    """Сценарий 7, п. 8: заявка создана в очереди, где исполнитель не участник — после сохранения список со
    словами «Заявка #N создана в очереди «…»», сама заявка ему недоступна (FR-228, FR-236, FR-239)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    q1_id, _q1_name = _new_queue(page, "Своя")
    q2_id, q2_name = _new_queue(page, "Чужая")
    account, tok, _short = _person(employee)
    _member(page, q1_id, account, tok)
    cat_id = _value(page, "categories", helpers_org.unique_name("Своя"), queue=q1_id)
    word = _word()

    ep = account.page
    _create(ep, email=helpers_sd.requester_email("call"), category_id=cat_id, category_queue=q1_id, queue_id=q2_id,
            subject=f"Чужая очередь {word}", text=f"Текст {word}", source="Телефон")
    # п. 8: возврат в список и сообщение о создании в очереди (14.2)
    ep.wait_for_url(LIST_RE)
    status = ep.locator("[role=status]").filter(has_text=re.compile(r"Заявка #\d+ создана в очереди"))
    expect(status.first).to_contain_text(q2_name)
    found = re.search(r"Заявка #(\d+) создана в очереди «([^»]+)»", status.first.inner_text())
    assert found and found.group(2) == q2_name, status.first.inner_text()
    number = int(found.group(1))
    assert number == helpers_sd.ticket_number_by_subject(page, word)  # заявка создана, номер тот же
    # п. 8: сама заявка исполнителю недоступна — в списке нет, карточка — 404
    assert helpers_sd.tickets_by_subject(ep, word) == []
    assert helpers_org.direct_get(ep, f"/tickets/{number}/").status == 404


def test_d07_all_tickets_right_without_queue_node_can_create_in_any_queue_and_take(admin_page, employee):
    """Сценарий 7, п. 9: сотрудник с правом «Все заявки», но без узла-очереди — кнопка «Новая заявка» и флажок
    «Взять себе» доступны в любой очереди, заявка у него (FR-228, FR-233)."""
    page = admin_page
    default_id, _ = helpers_sd.ensure_ready(page)
    q2_id, q2_name = _new_queue(page, "Другая")
    role_name = _role_with_permission(page, "servicedesk.all")
    account, tok, _short = _person(employee, role=role_name)
    cat_id = _value(page, "categories", helpers_org.unique_name("Звонок"), queue=default_id)
    word = _word()

    ep = account.page
    # п. 9: кнопка в шапке списка есть, хотя он не участник ни одной очереди
    ep.goto("/tickets/")
    button = ep.locator('[data-tickets-list] > header a[data-action="ticket-new"]')
    expect(button).to_have_attribute("href", "/tickets/new/")
    _open_form(ep)
    _enter_email(ep, helpers_sd.requester_email("call"))
    _choose_category(ep, cat_id, default_id)
    expect(_form(ep).locator("select[name=queue]")).to_have_value(str(default_id))
    expect(_take_box(ep)).to_be_enabled()
    expect(_take_box(ep)).to_be_checked()
    # п. 9: и в любой другой очереди
    _choose_queue(ep, q2_id)
    expect(_take_box(ep)).to_be_enabled()
    expect(_take_box(ep)).to_be_checked()
    _fill_text(ep, f"Право на все заявки {word}", f"Текст {word}", source="Телефон")
    _form(ep).locator("button[type=submit]").click()
    number = _created_number(ep)  # заявка ему видна: переход на карточку
    card = _card(ep, number)
    expect(card.locator('[data-field="queue"]')).to_contain_text(q2_name)
    assert tok in helpers_sd.field_text(card, "assignee")


def test_d07_criticality_default_medium_from_settings_and_changeable_before_save(admin_page, employee):
    """Сценарий 7, п. 10: критичность по умолчанию — «Средняя», значение из настроек сервис-деска; исполнитель
    меняет её до сохранения (FR-203, FR-228)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    account, tok, _short = _person(employee)
    _member(page, queue_id, account, tok)
    cat_id = _value(page, "categories", helpers_org.unique_name("Звонок"), queue=queue_id)
    word = _word()
    ep = account.page

    before = _settings_priority(page)
    try:
        # п. 10: по умолчанию стоит значение настроек — «Средняя»
        assert before == "Средняя", before
        _open_form(ep)
        expect(_form(ep).locator("select[name=priority] option:checked")).to_have_text(before)
        # п. 10: значение берётся из настроек — после смены настройки форма предлагает новое
        _settings_priority(page, "Высокая")
        _open_form(ep)
        expect(_form(ep).locator("select[name=priority] option:checked")).to_have_text("Высокая")
        # п. 10: до сохранения критичность можно сменить
        _enter_email(ep, helpers_sd.requester_email("call"))
        _choose_category(ep, cat_id, queue_id)
        _fill_text(ep, f"Критичность {word}", f"Текст {word}", source="Телефон", priority="Низкая")
        _form(ep).locator("button[type=submit]").click()
        number = _created_number(ep)
        card = _card(ep, number)
        expect(card.locator('[data-field="priority"]')).to_contain_text("Низкая")
    finally:
        _settings_priority(page, before)
    expect(page.locator("[role=status]").first).to_be_visible()


def test_d07_confirmation_for_executor_ticket_has_same_pd_line(admin_page, employee, mailpit):
    """Сценарий 7, п. 11: подтверждение заявки исполнителя содержит ту же строку о согласии на обработку ПДн,
    что и подтверждение на письмо; флажка согласия в форме нет (FR-253, FR-230)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    account, tok, _short = _person(employee)
    _member(page, queue_id, account, tok)
    cat_id = _value(page, "categories", helpers_org.unique_name("Звонок"), queue=queue_id)
    word, requester = _word(), helpers_sd.requester_email("call")
    subject, body = f"Согласие {word}", f"Текст заявки {word}"

    ep = account.page
    _open_form(ep)
    expect(_form(ep).locator("input[name=consent]")).to_have_count(0)  # в форме исполнителя флажка нет (13.6)
    _create(ep, email=requester, category_id=cat_id, category_queue=queue_id, subject=subject, text=body,
            source="Телефон", take=False)
    number = _created_number(ep)
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.confirmation", to=requester)
    text = _norm(letter["Text"])
    assert f"Здравствуйте, {requester}!" in text
    assert f"Текст заявки: {body}" in text
    # п. 11: та же строка о ПДн, что у подтверждения на письмо (10.4)
    assert PD_LINE in text, text
    # у заявки без ответственного строки об исполнителе нет, фразы о нерабочем времени у исполнителя нет никогда
    assert "Исполнитель:" not in text
    assert "в нерабочее время" not in text
    headers = helpers_sd.letter_headers(mailpit, letter["ID"])
    assert [v.lower() for v in _header(headers, "Auto-Submitted")] == ["auto-generated"]  # заявка исполнителя
    assert _header(headers, "X-Portal-Template") == ["ticket.confirmation"]
