"""T-3147: сценарий 9 — администратор настраивает сервис-деск: очереди, очередь по умолчанию, категории, справочники
и статусы, журнал «было / стало», удаление узла с заявками (FR-206, FR-207, FR-209, FR-210, FR-213, FR-231, FR-236,
FR-238, FR-269, FR-273, FR-274, FR-275, FR-288)."""
import re
import secrets

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org, helpers_sd
from tests.e2e.helpers_sd import CORP_DOMAIN, MAILBOX
from tests.support_servicedesk import build_mail


def _letters(count: int = 8) -> str:
    """Случайные латинские согласные: в названии нет цифр (поиск списка не примет слово за номер, а число открытых
    заявок в тексте диалога нельзя спутать с цифрой из названия)."""
    return "".join(secrets.choice("bcdfghklmnprstvw") for _ in range(count))


def _word() -> str:
    """Уникальное слово темы заявки: буква и шесть знаков, не из одних цифр (доп. 41 (в))."""
    return f"t{secrets.token_hex(3)}"


def _norm(text: str) -> str:
    return " ".join(text.split())


def _message_id() -> str:
    return f"<{secrets.token_hex(8)}@client.test>"


# --- Справочники (12.6, 13.7) -------------------------------------------------------------------------------

def _open_dictionary(page, kind: str) -> None:
    page.goto(f"/servicedesk/dictionaries/{kind}/")
    expect(page.locator("table[data-dictionary]")).to_be_visible()


def _name_of(row) -> str:
    """Название значения из ячейки `name` без меток «системное» и «в архиве» (они могут стоять в той же ячейке)."""
    cell = row.locator('[data-cell="name"]')
    text = cell.inner_text()
    for mark in cell.locator("[data-archived-mark], [data-system-mark]").all():
        text = text.replace(mark.inner_text(), "")
    return _norm(text)


def _ids_by_name(page, name: str) -> list:
    """Номера строк открытого справочника с этим названием (точное сравнение: «Решена» — не «Не может быть
    решена»). Справочник уже открыт `_open_dictionary`."""
    return [row.get_attribute("data-id") for row in page.locator("tr[data-dictionary-row]").all()
            if _name_of(row) == name]


def _row(page, row_id):
    return page.locator(f'tr[data-dictionary-row][data-id="{row_id}"]')


def _alert_code(page) -> str:
    alert = page.locator("[role=alert][data-code], [data-error]").first
    return alert.get_attribute("data-code") or alert.get_attribute("data-error") or ""


def _submit_dictionary_form(page, form) -> None:
    """Отправляет форму значения и ждёт либо список вида, либо отказ (`[role=alert]`); отказ — `AssertionError`."""
    form.locator("button[type=submit]").click()
    outcome = page.locator("[role=alert]").or_(page.locator("table[data-dictionary]"))
    expect(outcome.first).to_be_visible()
    if page.locator("[role=alert]").count():
        raise AssertionError(f"справочник: отказ {_alert_code(page)}: {helpers.alert_text(page)}")


def _create_value(page, kind: str, name: str, *, fields: dict | None = None, checks: tuple = ()) -> str:
    """Добавляет значение справочника формой `dictionary` на `/servicedesk/dictionaries/<вид>/new/`; возвращает
    номер строки в списке вида."""
    page.goto(f"/servicedesk/dictionaries/{kind}/new/")
    form = page.locator('form[data-form="dictionary"]')
    expect(form).to_be_visible()
    form.locator("input[name=name]").fill(name)
    if kind == "categories":  # доп. 42 (г): у категории поле «порядок» есть всегда
        form.locator("input[name=order]").fill("50")
    elif form.locator("input[name=order]").count():
        form.locator("input[name=order]").fill("10")
    for key, value in (fields or {}).items():
        if key in ("queue", "default_assignee"):  # доп. 42 (г): выбор из списка
            form.locator(f"select[name={key}]").select_option(str(value))
        else:
            helpers_org.set_choice(form, key, value)
    for key in checks:
        form.locator(f"input[name={key}]").check()
    _submit_dictionary_form(page, form)
    _open_dictionary(page, kind)
    found = _ids_by_name(page, name)
    assert len(found) == 1, f"значение «{name}» в справочнике {kind}: строк {len(found)}"
    return found[0]


def _new_category(page, name: str, queue_id) -> str:
    """Категория «на форме» с очередью `queue_id` без ответственного по умолчанию."""
    return _create_value(page, "categories", name, fields={"queue": queue_id}, checks=("on_form",))


def _try_dictionary_action(page, kind: str, row_id, action: str):
    """Нажимает кнопку архива в строке списка вида `kind`; возвращает локатор строки."""
    _open_dictionary(page, kind)
    row = _row(page, row_id)
    expect(row).to_have_count(1)
    row.locator(f'form[data-form="{action}"] button[data-action="{action}"]').click()
    return row


def _delete_dialog(page, kind: str, row_id):
    """Диалог удаления значения: `a[data-action="dictionary-delete"]` строки, диалог в `#dialog-root`."""
    _open_dictionary(page, kind)
    _row(page, row_id).locator('a[data-action="dictionary-delete"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dictionary-delete"]')
    expect(dialog).to_be_visible()
    return dialog


# --- Очереди (12.6, 13.7) -------------------------------------------------------------------------------------

def _new_queue(page, prefix: str = "Очередь") -> tuple:
    """Новый узел под корнем, отмеченный очередью (название без цифр): `(id, название)`."""
    name = f"{prefix}-{_letters()}"
    unit_id = helpers_org.create_unit(page, name)
    helpers_sd.mark_queue(page, unit_id)
    return unit_id, name


def _unmark_dialog(page, unit_id):
    """Диалог снятия отметки: `a[data-action="queue-unmark"]` узла (`?unmark=<id>`), диалог в `#dialog-root`."""
    helpers_sd.open_queues(page)
    link = page.locator(f'a[data-action="queue-unmark"]:is([hx-get$="unmark={unit_id}"], [href$="unmark={unit_id}"])')
    expect(link).to_have_count(1)
    link.click()
    dialog = page.locator('#dialog-root [data-dialog="queue-unmark"]')
    expect(dialog).to_be_visible()
    return dialog


def _unmark_queue(page, unit_id) -> None:
    """Снимает отметку очереди через диалог и ждёт, что узел перестал быть очередью."""
    helpers.submit(_unmark_dialog(page, unit_id).locator("form"))
    helpers_sd.open_queues(page)
    expect(helpers_org.unit_li(page, unit_id).first).to_have_attribute("data-queue", "false")


def _queue_flag(page, unit_id) -> str:
    helpers_sd.open_queues(page)
    return helpers_org.unit_li(page, unit_id).first.get_attribute("data-queue")


# --- Настройки и заявки ------------------------------------------------------------------------------------------

def _save_settings(page, **values) -> dict:
    """Меняет поля формы настроек (`input[name=…]`), отправляет форму; возвращает прежние значения полей (строки)."""
    page.goto("/servicedesk/")
    form = page.locator('form[data-form="servicedesk-settings"]')
    expect(form).to_be_visible()
    before = {}
    for name, value in values.items():
        field = form.locator(f"[name={name}]")
        before[name] = field.input_value()
        field.fill(str(value))
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    if page.locator("[role=alert][data-code], [data-error]").count():
        raise AssertionError(f"настройки не приняты: {_alert_code(page)}")
    expect(page.locator("[role=status]").first).to_be_visible()
    return before


def _guest_ticket(new_context, category_name: str) -> str:
    """Заявка с открытой формы `/request/` без входа (новый контекст) в категории `category_name`; адрес заявителя
    корпоративного домена. Возвращает слово темы для поиска заявки."""
    page = new_context().new_page()
    word = _word()
    page.goto("/request/")
    form = page.locator('form[data-form="request"]')
    expect(form).to_be_visible()
    form.locator("input[name=email]").fill(helpers_sd.requester_email())
    form.locator("input[name=name]").fill("Тест Заявитель")
    form.locator("select[name=category]").select_option(label=category_name)
    form.locator("input[name=subject]").fill(f"Тема {word}")
    form.locator("textarea[name=text]").fill(f"Описание {word}")
    form.locator("input[name=consent]").check()
    form.locator("button[type=submit]").click()
    page.wait_for_url(re.compile(r"/request/done/"))
    return word


def _mail_ticket(page) -> int:
    """Заявка из письма корпоративного домена (очередь по умолчанию, без ответственного); возвращает номер."""
    word = _word()
    helpers_sd.deliver(build_mail(from_addr=helpers_sd.requester_email(), to=[MAILBOX], subject=f"Тема {word}",
                                  text=f"Описание {word}", message_id=_message_id()))
    return helpers_sd.ticket_number_by_subject(page, word)


def _journal_entry(admin_page, action: str, needles: tuple, object_id=None) -> tuple:
    """Первая строка журнала по коду `action` (первая страница, новые сверху), в тексте которой есть все `needles`:
    `(текст строки, «было», «стало»)`; нет такой — `AssertionError`."""
    rows = helpers_org.audit_rows(admin_page, action, object_id)
    sides = helpers_org.audit_sides(admin_page, action, object_id)
    for text, (was, became) in zip(rows, sides):
        if all(item in text for item in needles):
            return text, was, became
    raise AssertionError(f"в журнале нет события {action} с {needles}; строк: {len(rows)}")


# --- Тесты ---------------------------------------------------------------------------------------------------------

def test_d09_fresh_install_no_queues_no_domains_mailbox_readonly_other_category_and_intake_closed(
        browser, browser_context_args, stand_admin, admin_page, new_context):
    """Сценарий 9, п. 1: новая установка — очередей нет, список доменов пуст, ящик заявок показан только для чтения,
    есть категория «Другое»; пока нет доменов (и очереди по умолчанию) форма закрыта, а письмо заявку не создаёт
    (FR-210, FR-213, FR-231, FR-269, FR-274)."""
    helpers_sd.reset_stand_and_relogin(browser, browser_context_args, stand_admin, admin_page)  # «после установки»
    page = admin_page
    # п. 1: настройки — домены пусты, ящик только текстом, очередь по умолчанию «не задана»
    page.goto("/servicedesk/")
    form = page.locator('form[data-form="servicedesk-settings"]')
    expect(form).to_be_visible()
    assert form.locator("textarea[name=domains]").input_value().strip() == ""
    address = page.locator('[data-field="mailbox-address"]')
    expect(address).to_contain_text(MAILBOX)
    assert address.evaluate("el => el.tagName.toLowerCase()") not in ("input", "textarea", "select")
    assert address.locator("input, textarea, select").count() == 0
    # у формы настроек нет поля адреса ящика и очереди: только поля из 13.7
    allowed = {"csrfmiddlewaretoken", "domains", "default_priority", "autoclose_days", "reopen_days",
               "form_hourly_limit", "retention_years", "inbound_retention_days"}
    names = {el.get_attribute("name") for el in form.locator("input[name], textarea[name], select[name]").all()}
    assert names <= allowed, names - allowed
    expect(page.locator('[data-field="default-queue"]')).to_contain_text("не задана")
    # п. 1: очередей нет
    helpers_sd.open_queues(page)
    expect(page.locator('ul[data-unit-tree] li[data-queue="true"]')).to_have_count(0)
    # п. 1: начальная категория «Другое» — системная
    _open_dictionary(page, "categories")
    other = _ids_by_name(page, "Другое")
    assert len(other) == 1
    expect(_row(page, other[0]).locator("[data-system-mark]")).to_have_count(1)
    expect(_row(page, other[0])).to_have_attribute("data-archived", "false")
    # п. 1: напоминание на главной у администратора с правом «Настройка сервис-деска» (12.7)
    page.goto("/")
    notice = page.locator('[data-home-notices] [data-notice="servicedesk-setup"]')
    expect(notice).to_be_visible()
    expect(notice).to_contain_text("Сервис-деск не настроен")
    expect(notice.locator('a[href="/servicedesk/"]')).to_have_count(1)
    # п. 1: приём закрыт — форма в состоянии «закрыто» с адресом ящика, самой формы нет
    guest = new_context().new_page()
    guest.goto("/request/")
    closed = guest.locator('[data-closed-notice="request"]')
    expect(closed).to_be_visible()
    expect(closed).to_contain_text(MAILBOX)
    expect(guest.locator('form[data-form="request"]')).to_have_count(0)
    # п. 1: письмо не принимается — заявки нет, во «Входящих» итог «отклонено»/«ждёт настройки»
    domains_before = []  # на новой установке список пуст (проверено выше): его и возвращаем
    try:
        # прогрев: если после сброса строки состояния ящика нет (ящик не отвечал), первый опрос создаёт её сам
        # (6.15), и письмо ниже не потеряется; если строка есть — опрос безвреден (8.3)
        helpers_sd.poll_now()
        word = _word()
        helpers_sd.deliver(build_mail(from_addr=helpers_sd.requester_email(), to=[MAILBOX], subject=f"Тема {word}",
                                      text=f"Описание {word}", message_id=_message_id()))
        assert helpers_sd.tickets_by_subject(page, word) == []
        assert helpers_sd.inbound_outcome(page, subject=word) == "отклонено: чужой домен"  # 6.16: пустой список доменов
        # п. 1: домен внесён, но очереди по умолчанию нет — форма всё ещё закрыта, письмо ждёт настройки
        helpers_sd.set_domains(page, [CORP_DOMAIN])
        guest.goto("/request/")
        expect(guest.locator('[data-closed-notice="request"]')).to_be_visible()
        expect(guest.locator('form[data-form="request"]')).to_have_count(0)
        word2 = _word()
        helpers_sd.deliver(build_mail(from_addr=helpers_sd.requester_email(), to=[MAILBOX], subject=f"Тема {word2}",
                                      text=f"Описание {word2}", message_id=_message_id()))
        assert helpers_sd.tickets_by_subject(page, word2) == []
        assert helpers_sd.inbound_outcome(page, subject=word2) == "ждёт настройки очереди по умолчанию"
    finally:
        helpers_sd.set_domains(page, domains_before)  # стенд снова «без доменов»


def test_d09_default_queue_chosen_among_three_and_other_category_follows_it(admin_page, new_context):
    """Сценарий 9, п. 2: отмечены три очереди; администратор выбирает одну очередью по умолчанию — категория
    «Другое» ведёт в неё, при смене очереди по умолчанию — в новую (FR-231, FR-269)."""
    page = admin_page
    orig_id, _orig_name = helpers_sd.ensure_ready(page)
    try:
        queues = [_new_queue(page) for _ in range(3)]
        (first_id, first_name), (second_id, second_name), _third = queues
        # п. 2: выбираем первую — она единственная по умолчанию, у неё отметка «по умолчанию»
        helpers_sd.set_default_queue(page, first_id)
        helpers_sd.open_queues(page)
        expect(page.locator('ul[data-unit-tree] li[data-default="true"]')).to_have_count(1)
        first_li = helpers_org.unit_li(page, first_id)
        expect(first_li).to_have_attribute("data-default", "true")
        expect(first_li.locator("[data-default-mark]")).to_contain_text("по умолчанию")
        assert helpers_sd.default_queue_name(page) == first_name
        # п. 2: «Другое» ведёт в очередь по умолчанию — заявка из формы в «Другое» попадает в первую очередь
        number = helpers_sd.ticket_number_by_subject(page, _guest_ticket(new_context, "Другое"))
        assert first_name in helpers_sd.field_text(helpers_sd.open_ticket(page, number), "queue")
        # п. 2: выбираем другую — «Другое» следует за ней
        helpers_sd.set_default_queue(page, second_id)
        helpers_sd.open_queues(page)
        expect(page.locator('ul[data-unit-tree] li[data-default="true"]')).to_have_count(1)
        expect(helpers_org.unit_li(page, first_id)).to_have_attribute("data-default", "false")
        number = helpers_sd.ticket_number_by_subject(page, _guest_ticket(new_context, "Другое"))
        assert second_name in helpers_sd.field_text(helpers_sd.open_ticket(page, number), "queue")
    finally:
        if helpers_sd.default_queue_id(page) != orig_id:
            helpers_sd.set_default_queue(page, orig_id)


def test_d09_unmark_queue_with_open_tickets_refused_without_open_tickets_passes(admin_page, new_context):
    """Сценарий 9, п. 3: снятие отметки «очередь» с узла с открытой заявкой — отказ с числом заявок, у узла без
    открытых заявок снятие проходит (FR-231)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    busy_id, busy_name = _new_queue(page)
    free_id, _free_name = _new_queue(page)
    category = f"Категория-{_letters()}"
    _new_category(page, category, busy_id)
    number = helpers_sd.ticket_number_by_subject(page, _guest_ticket(new_context, category))
    assert busy_name in helpers_sd.field_text(helpers_sd.open_ticket(page, number), "queue")
    # п. 3: диалог снятия называет число открытых заявок и категорию, которая перейдёт в очередь по умолчанию
    dialog = _unmark_dialog(page, busy_id)
    assert re.search(r"(?<!\d)1(?!\d)", dialog.inner_text()), dialog.inner_text()
    expect(dialog.locator("[data-consequence]")).to_have_count(1)
    expect(dialog.locator("[data-consequence]")).to_contain_text(category)
    # п. 3: подтверждаем — отказ с объяснением (число открытых заявок), узел остаётся очередью
    helpers.submit(dialog.locator("form"))
    refusal = page.locator('[role=alert][data-code="queue_has_open_tickets"]')
    expect(refusal.first).to_be_visible()
    assert re.search(r"(?<!\d)1(?!\d)", refusal.first.inner_text()), refusal.first.inner_text()
    assert _queue_flag(page, busy_id) == "true"
    # п. 3: у узла без открытых заявок снятие проходит
    _unmark_queue(page, free_id)
    assert _queue_flag(page, free_id) == "false"
    assert _queue_flag(page, busy_id) == "true"


def test_d09_category_default_assignee_not_in_queue_refused(admin_page, employee):
    """Сценарий 9, п. 4: категория с ответственным по умолчанию не из участников своей очереди не сохраняется —
    отказ; после того как сотрудник стал участником очереди, та же категория сохраняется (FR-238, FR-269)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    token = _letters(6)
    person = employee(full_name=f"Тест{token} Иванов Иван")
    queue_id, _queue_name = _new_queue(page)
    name = f"Категория-{_letters()}"
    # п. 4: сотрудник не участник очереди — форма категории отказывает, отказ виден в самой форме
    page.goto("/servicedesk/dictionaries/categories/new/")
    form = page.locator('form[data-form="dictionary"]')
    expect(form).to_be_visible()
    form.locator("input[name=name]").fill(name)
    form.locator("input[name=order]").fill("10")
    form.locator("select[name=queue]").select_option(str(queue_id))
    form.locator("select[name=default_assignee]").select_option(str(person.id))
    form.locator("input[name=on_form]").check()
    form.locator("button[type=submit]").click()
    expect(page.locator('[role=alert][data-code="assignee_not_participant"]').first).to_be_visible()
    expect(page.locator('form[data-form="dictionary"]')).to_be_visible()
    _open_dictionary(page, "categories")
    assert _ids_by_name(page, name) == []
    # п. 4: сотрудник стал участником очереди — та же категория сохраняется, ответственный виден в списке
    helpers_sd.add_queue_member(page, queue_id, [person.id], q=token)
    category_id = _create_value(page, "categories", name, fields={"queue": queue_id, "default_assignee": person.id},
                                checks=("on_form",))
    expect(_row(page, category_id).locator('[data-cell="default-assignee"]')).to_contain_text(token)


def test_d09_new_in_progress_kind_status_available_for_manual_change(admin_page):
    """Сценарий 9, п. 5: добавленный статус «Ждёт запчасть» вида «в работе» предлагается при ручной смене статуса
    заявки, и заявка с ним — вида «в работе» (FR-206, FR-209)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    status_name = f"Ждёт запчасть {_letters()}"
    # п. 5: добавляем статус вида «в работе»
    status_id = _create_value(page, "statuses", status_name, fields={"kind": "in_progress"})
    _open_dictionary(page, "statuses")
    expect(_row(page, status_id).locator('[data-cell="kind"]')).to_contain_text("в работе")
    # п. 5: он есть в списке ручной смены статуса, статусы вида «закрыта» там не предлагаются
    number = _mail_ticket(page)
    card = helpers_sd.open_ticket(page, number)
    form = card.locator('form[data-form="ticket-status"]')
    expect(form).to_be_visible()
    options = [_norm(text) for text in form.locator("select[name=status] option").all_inner_texts()]
    assert status_name in options, options
    assert "Решена" not in options and "Закрыта автоматически" not in options, options
    # п. 5: выбираем его — заявка получает этот статус, портал считает её «в работе»
    form.locator("select[name=status]").select_option(label=status_name)
    form.locator("button[type=submit]").click()
    root = page.locator(f'[data-ticket-card][data-number="{number}"]')
    expect(root).to_have_attribute("data-kind", "in_progress")
    expect(root.locator('[data-field="status"]')).to_contain_text(status_name)


def test_d09_used_value_delete_refused_archive_offered_archived_hidden_in_picker_visible_in_old_tickets(
        admin_page, new_context):
    """Сценарий 9, п. 6: значение справочника, использованное в заявке, не удаляется — отказ со словом «архив»;
    после ухода в архив оно не предлагается при выборе, но в старой заявке видно (FR-273)."""
    page = admin_page
    queue_id, _queue_name = helpers_sd.ensure_ready(page)
    category = f"Категория-{_letters()}"
    category_id = _new_category(page, category, queue_id)
    number = helpers_sd.ticket_number_by_subject(page, _guest_ticket(new_context, category))
    # п. 6: удаление использованного значения — отказ, в тексте предложен архив
    dialog = _delete_dialog(page, "categories", category_id)
    helpers.submit(dialog.locator("form"))
    refusal = page.locator('[role=alert][data-code="in_use"]')
    expect(refusal.first).to_be_visible()
    assert re.search("архив", refusal.first.inner_text(), re.IGNORECASE), refusal.first.inner_text()
    _open_dictionary(page, "categories")
    expect(_row(page, category_id)).to_have_count(1)  # значение осталось
    # п. 6: убираем значение в архив — метка «в архиве»
    row = _try_dictionary_action(page, "categories", category_id, "dictionary-archive")
    expect(row).to_have_attribute("data-archived", "true")
    expect(row.locator("[data-archived-mark]")).to_contain_text("в архиве")
    # п. 6: архивная категория не предлагается ни на открытой форме, ни в форме заявки исполнителя
    guest = new_context().new_page()
    guest.goto("/request/")
    expect(guest.locator('form[data-form="request"] select[name=category]')).to_be_visible()
    assert category not in [_norm(t) for t in guest.locator("select[name=category] option").all_inner_texts()]
    page.goto("/tickets/new/")
    expect(page.locator('form[data-form="ticket-new"] select[name=category]')).to_be_visible()
    assert category not in [_norm(t) for t in page.locator("select[name=category] option").all_inner_texts()]
    # п. 6: в старой заявке категория по-прежнему видна
    card = helpers_sd.open_ticket(page, number)
    assert category in helpers_sd.field_text(card, "category")


def test_d09_only_status_of_kind_cannot_be_archived(admin_page):
    """Сценарий 9, п. 7: единственный действующий статус вида нельзя убрать в архив — отказ (FR-206)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    _open_dictionary(page, "statuses")
    new_rows = [row for row in page.locator("tr[data-dictionary-row]").all()
                if row.get_attribute("data-archived") == "false"
                and "новая" in row.locator('[data-cell="kind"]').inner_text()]
    assert len(new_rows) == 1, "на стенде у вида «новая» должен быть один действующий статус"
    status_id = new_rows[0].get_attribute("data-id")
    # п. 7: пытаемся убрать «Новая» (единственный действующий статус своего вида) в архив
    _try_dictionary_action(page, "statuses", status_id, "dictionary-archive")
    refusal = page.locator("[role=alert][data-code]")
    expect(refusal.first).to_be_visible()
    # порядок проверок 6.5: системное, последний действующий, по умолчанию — «Новая» отмечена по умолчанию
    assert refusal.first.get_attribute("data-code") == "last_active", refusal.first.get_attribute("data-code")
    expect(refusal.first).to_contain_text("последний действующий")
    _open_dictionary(page, "statuses")
    expect(_row(page, status_id)).to_have_attribute("data-archived", "false")


def test_d09_settings_direct_link_without_right_refused(admin_page, employee):
    """Сценарий 9, п. 8: сотрудник без права «Настройка сервис-деска» по прямой ссылке получает отказ на всех
    страницах настройки; пункта меню и напоминания у него нет (FR-275, FR-236)."""
    admin = admin_page
    admin.goto("/")
    expect(admin.locator('#main-menu a.menu-item[href="/servicedesk/"]')).to_have_count(1)  # у администратора есть
    person = employee(full_name=f"Тест{_letters(6)} Иванов Иван")
    page = person.page
    # п. 8: прямые адреса страниц настройки — 403 (одинаково для существующего и несуществующего номера)
    paths = ["/servicedesk/", "/servicedesk/queues/", "/servicedesk/dictionaries/categories/",
             "/servicedesk/dictionaries/statuses/", "/servicedesk/dictionaries/categories/new/",
             "/servicedesk/dictionaries/categories/999999/edit/", "/servicedesk/requesters/",
             "/servicedesk/requesters/import/", "/servicedesk/inbound/"]
    for path in paths:
        assert helpers_org.direct_get(page, path).status == 403, path
    # п. 8: прямая отправка изменений настроек и очередей — тоже отказ
    assert helpers_org.direct_post(page, "/servicedesk/", {"autoclose_days": "5"}).status == 403
    assert helpers_org.direct_post(page, "/servicedesk/queues/", {"action": "mark", "unit": "1"}).status == 403
    # п. 8: в браузере — страница без формы настроек, в меню и на главной нет пункта и напоминания
    page.goto("/servicedesk/")
    expect(page.locator('form[data-form="servicedesk-settings"]')).to_have_count(0)
    page.goto("/")
    expect(page.locator("#main-menu")).to_be_visible()
    expect(page.locator('#main-menu a.menu-item[href="/servicedesk/"]')).to_have_count(0)
    expect(page.locator('[data-notice="servicedesk-setup"]')).to_have_count(0)


def test_d09_every_settings_change_in_journal_as_was_became_in_russian(admin_page):
    """Сценарий 9, п. 9: каждое изменение настроек, очередей и справочников записано в журнал со словами «было» и
    «стало» по-русски (FR-288)."""
    page = admin_page
    queue0_id, queue0_name = helpers_sd.ensure_ready(page)
    page.goto("/servicedesk/")
    old_days = int(page.locator("input[name=autoclose_days]").input_value())
    new_days = old_days + 1 if old_days < 90 else old_days - 1
    restore_days = False
    try:
        # п. 9: настройки — срок автозакрытия
        restore_days = True
        _save_settings(page, autoclose_days=new_days)
        text, was, became = _journal_entry(page, "servicedesk.settings_changed", ("срок автозакрытия",), "1")
        assert "Настройки сервис-деска изменены" in text, text
        assert f"срок автозакрытия, дней: {old_days}" in was, was
        assert f"срок автозакрытия, дней: {new_days}" in became, became
        # п. 9: очередь отмечена, назначена по умолчанию, отметка снята
        unit_id, unit_name = _new_queue(page)
        text, was, became = _journal_entry(page, "queue.marked", (), unit_id)
        assert "Очередь отмечена" in text and unit_name in became, text
        helpers_sd.set_default_queue(page, unit_id)
        text, was, became = _journal_entry(page, "queue.default_changed", (), unit_id)
        assert "Очередь по умолчанию изменена" in text, text
        assert queue0_name in was and unit_name in became, (was, became)
        helpers_sd.set_default_queue(page, queue0_id)
        _unmark_queue(page, unit_id)
        text, was, became = _journal_entry(page, "queue.unmarked", (), unit_id)
        assert "Отметка очереди снята" in text and unit_name in was, text
        # п. 9: справочник — значение добавлено, переименовано, убрано в архив
        old_name, new_name = f"Категория-{_letters()}", f"Категория-{_letters()}"
        category_id = _new_category(page, old_name, queue0_id)
        text, was, became = _journal_entry(page, "sd_dictionary.created", (old_name,))
        assert "Значение справочника добавлено" in text, text
        page.goto(f"/servicedesk/dictionaries/categories/{category_id}/edit/")
        form = page.locator('form[data-form="dictionary"]')
        expect(form).to_be_visible()
        form.locator("input[name=name]").fill(new_name)
        _submit_dictionary_form(page, form)
        text, was, became = _journal_entry(page, "sd_dictionary.updated", (old_name, new_name))
        assert "Значение справочника изменено" in text, text
        assert old_name in was and new_name in became, (was, became)
        _try_dictionary_action(page, "categories", category_id, "dictionary-archive")
        expect(_row(page, category_id)).to_have_attribute("data-archived", "true")
        text, was, became = _journal_entry(page, "sd_dictionary.archived", (new_name,))
        assert "Значение справочника в архиве" in text, text
    finally:
        if helpers_sd.default_queue_id(page) != queue0_id:
            helpers_sd.set_default_queue(page, queue0_id)
        if restore_days:
            _save_settings(page, autoclose_days=old_days)


def test_d09_unit_with_tickets_even_closed_cannot_be_deleted_empty_unit_can(admin_page, new_context):
    """Сценарий 9, п. 10: узел с заявками, в том числе только закрытыми, не удаляется — отказ с причиной; пустой узел
    удаляется (FR-231)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    page.goto("/structure/")
    root = helpers_org.root_id(page)
    busy_id, _busy_name = _new_queue(page)  # без участников и вложенных узлов
    category = f"Категория-{_letters()}"
    _new_category(page, category, busy_id)
    number = helpers_sd.ticket_number_by_subject(page, _guest_ticket(new_context, category))
    # п. 10: узел с открытой заявкой не удаляется, причина — привязанные заявки (3.2, 6.4: `unit_usage`)
    helpers_org.confirm_delete(page, helpers_org.open_delete_dialog(page, busy_id))
    expect(page.locator("[role=alert]").first).to_be_visible()
    assert "Узел нельзя удалить" in helpers.alert_text(page), helpers.alert_text(page)
    assert "к узлу привязаны заявки сервис-деска" in helpers.alert_text(page), helpers.alert_text(page)
    helpers_org.open_structure(page)
    expect(helpers_org.unit_li(page, busy_id)).to_have_count(1)
    # п. 10: заявка закрыта, отметка очереди снята — остались только закрытые заявки узла
    helpers_sd.open_ticket(page, number)
    page.locator('[data-ticket-card] a[data-action="ticket-close"]').click()
    close = page.locator('#dialog-root [data-dialog="ticket-close"]')
    expect(close).to_be_visible()
    close.locator("textarea[name=resolution]").fill("Решено при настройке")
    helpers.submit(close.locator("form"))
    expect(page.locator(f'[data-ticket-card][data-number="{number}"]')).to_have_attribute("data-kind", "closed")
    _unmark_queue(page, busy_id)
    # п. 10: узел с одними закрытыми заявками по-прежнему не удаляется, причина названа
    helpers_org.confirm_delete(page, helpers_org.open_delete_dialog(page, busy_id))
    expect(page.locator("[role=alert]").first).to_be_visible()
    assert "к узлу привязаны заявки сервис-деска" in helpers.alert_text(page), helpers.alert_text(page)
    helpers_org.open_structure(page)
    expect(helpers_org.unit_li(page, busy_id)).to_have_count(1)
    # п. 10: пустой узел удаляется
    empty_id = helpers_org.create_unit(page, f"Пустой-{_letters()}", parent_id=root)
    helpers_org.confirm_delete(page, helpers_org.open_delete_dialog(page, empty_id))
    expect(page.locator('[data-dialog="unit-delete"]')).to_have_count(0)
    helpers_org.open_structure(page)
    expect(helpers_org.unit_li(page, empty_id)).to_have_count(0)


def test_d09_system_auto_closed_status_rename_passes_archive_refused(admin_page):
    """Сценарий 9, п. 11: системный статус «Закрыта автоматически» переименовывается, а попытка убрать его в архив
    отклоняется (FR-206)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    _open_dictionary(page, "statuses")
    system_rows = page.locator("tr[data-dictionary-row]:has([data-system-mark])")
    expect(system_rows).to_have_count(1)  # у статусов системный один: «Закрыта автоматически»
    status_id = system_rows.first.get_attribute("data-id")
    edit_url = f"/servicedesk/dictionaries/statuses/{status_id}/edit/"
    page.goto(edit_url)
    original = page.locator('form[data-form="dictionary"] input[name=name]').input_value()
    renamed = f"Автозакрытие-{_letters()}"
    try:
        # п. 11: переименование проходит
        page.goto(edit_url)
        form = page.locator('form[data-form="dictionary"]')
        expect(form).to_be_visible()
        form.locator("input[name=name]").fill(renamed)
        _submit_dictionary_form(page, form)
        _open_dictionary(page, "statuses")
        assert _ids_by_name(page, renamed) == [status_id]
        # п. 11: убрать в архив нельзя — отказ «системное значение»
        _try_dictionary_action(page, "statuses", status_id, "dictionary-archive")
        expect(page.locator('[role=alert][data-code="system_protected"]').first).to_be_visible()
        _open_dictionary(page, "statuses")
        expect(_row(page, status_id)).to_have_attribute("data-archived", "false")
    finally:
        page.goto(edit_url)
        restore = page.locator('form[data-form="dictionary"]')
        expect(restore).to_be_visible()
        restore.locator("input[name=name]").fill(original)
        _submit_dictionary_form(page, restore)


def test_d09_fresh_install_status_dictionary_kinds_and_defaults(
        browser, browser_context_args, stand_admin, admin_page):
    """Сценарий 9, п. 12: на новой установке справочник статусов содержит шесть начальных статусов с видами; по
    умолчанию своего вида отмечены «Новая», «В работе», «Ждёт ответа заявителя» и «Решена» (FR-207, FR-206)."""
    helpers_sd.reset_stand_and_relogin(browser, browser_context_args, stand_admin, admin_page)  # «после установки»
    page = admin_page
    _open_dictionary(page, "statuses")
    expected = [("Новая", "новая", True), ("В работе", "в работе", True),
                ("Ждёт ответа заявителя", "ждёт ответа заявителя", True), ("Решена", "закрыта", True),
                ("Не может быть решена", "закрыта", False), ("Закрыта автоматически", "закрыта", False)]
    rows = page.locator("tr[data-dictionary-row]")
    expect(rows).to_have_count(len(expected))
    for name, kind, is_default in expected:
        found = _ids_by_name(page, name)
        assert len(found) == 1, (name, found)
        row = _row(page, found[0])
        assert kind in row.locator('[data-cell="kind"]').inner_text().lower(), name
        marked = "по умолчанию" in row.locator('[data-cell="default"]').inner_text()
        assert marked == is_default, (name, marked)
        expect(row).to_have_attribute("data-archived", "false")
    # п. 12: системный среди них один — «Закрыта автоматически»
    system = page.locator("tr[data-dictionary-row]:has([data-system-mark])")
    expect(system).to_have_count(1)
    assert _name_of(system.first) == "Закрыта автоматически"
