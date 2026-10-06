"""T-3143: сценарий 4 — участник очереди по умолчанию разбирает её (FR-234, FR-236, FR-237, FR-239, FR-240, FR-241)."""
import re
import secrets
import urllib.parse

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_servicedesk import build_mail


# --- Свои помощники -----------------------------------------------------------------------------

def _word() -> str:
    """Уникальное слово темы: буква и шесть шестнадцатеричных знаков (доп. 41 (в): строку из одних цифр поиск
    списка принял бы за номер заявки)."""
    return f"t{secrets.token_hex(3)}"


def _tag() -> str:
    """Общее начало ФИО сотрудников теста (поиск кандидатов и участников — по началу имени, доп. 40, шаблон)."""
    return f"Тест{secrets.token_hex(3)}"


def _norm(text: str) -> str:
    return " ".join(text.split())


def _message_id() -> str:
    return f"<{secrets.token_hex(8)}@client.test>"


def _new_ticket(page, group: str | None = None) -> int:
    """Заявка письмом корпоративного домена (приходит в очередь по умолчанию); номер — поиском по слову темы.
    `group` — общее слово нескольких заявок теста (в теме рядом с уникальным словом)."""
    word, sender = _word(), helpers_sd.requester_email()
    subject = f"Заявка {group} {word}" if group else f"Заявка {word}"
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=subject, text=f"Текст заявки {word}",
                                  message_id=_message_id()))
    return helpers_sd.ticket_number_by_subject(page, word)


def _make_queue(page) -> tuple:
    """Новая очередь (узел под корнем с уникальным именем, отметка очередью): `(id, название)`."""
    name = helpers_org.unique_name("queue")
    queue_id = helpers_org.create_unit(page, name)
    helpers_sd.mark_queue(page, queue_id)
    return queue_id, name


def _add_to_queue(page, queue_id, accounts, tag: str) -> None:
    """Участники очереди — члены узла. У отдела (`select[name=mode]` есть) — режим «параллельно», чтобы человек
    остался и в другой очереди; у команды выбора режима нет."""
    page.goto(f"/structure/{queue_id}/")
    mode = "concurrent" if page.locator("#unit-card select[name=mode]").count() else None
    helpers_org.add_members(page, queue_id, [a.id for a in accounts], q=tag, mode=mode)


def _make_category(page, name: str, queue_id, default_assignee=None) -> None:
    """Категория на `/servicedesk/dictionaries/categories/new/` (12.6: `queue`, `default_assignee`)."""
    page.goto("/servicedesk/dictionaries/categories/new/")
    form = page.locator('form[data-form="dictionary"]')
    expect(form).to_be_visible()
    form.locator("[name=name]").fill(name)
    form.locator("input[name=order]").fill("500")
    form.locator("select[name=queue]").select_option(str(queue_id))  # доп. 42 (г)
    if default_assignee is not None:
        form.locator("select[name=default_assignee]").select_option(str(default_assignee))
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    assert not helpers.alert_text(page), f"категория не заведена: {helpers.alert_text(page)}"
    expect(page.locator("tr[data-dictionary-row]").filter(has_text=name)).to_have_count(1)


def _candidates_for(card, query: str) -> None:
    """Вводит запрос в поле `q` формы назначения карточки и ждёт, пока подсказки (`hx-get` на `…/assignees/`,
    `hx-trigger="input changed delay:300ms"`) придут: первая подсказка видна (доп. 42 (б))."""
    box = card.locator('form[data-form="ticket-assign"] input[name=q]')
    with card.page.expect_response(lambda r: "/assignees/" in r.url) as info:
        box.fill(query)
    assert info.value.ok, f"подсказки назначения: ответ {info.value.status}"
    expect(card.locator('form[data-form="ticket-assign"] [data-candidates] label[data-candidate]').first).to_be_visible()


def _assign(page, number: int, user) -> None:
    """Назначить ответственного через карточку: подсказки → выбор → кнопка (13.3)."""
    card = helpers_sd.open_ticket(page, number)
    _candidates_for(card, user.full_name.split()[0])
    label = card.locator(f'label[data-candidate][data-user-id="{user.id}"]')
    expect(label).to_have_count(1)
    label.click()
    expect(label.locator("input[type=radio][name=assignee]")).to_be_checked()
    helpers.submit(card.locator('form[data-form="ticket-assign"]'))
    expect(card.locator('[data-field="assignee"]')).to_contain_text(user.full_name.split()[0])


def _transfer(page, number: int, queue_id, queue_name: str, reason: str = ""):
    """«Передать в очередь» из карточки через диалог (13.3, 12.4); заявка остаётся видимой тому, кто передаёт
    (администратор или участник обеих очередей), поэтому ответ — карточка. Возвращает локатор карточки."""
    card = helpers_sd.open_ticket(page, number)
    card.locator('a[data-action="ticket-transfer"]').click()
    dialog = page.locator('#dialog-root [data-dialog="ticket-transfer"]')
    expect(dialog).to_be_visible()
    dialog.locator("select[name=queue]").select_option(str(queue_id))
    if reason:
        dialog.locator("textarea[name=reason]").fill(reason)
    dialog.locator("button[type=submit]").click()
    expect(dialog).to_have_count(0)
    expect(card.locator('[data-field="queue"]')).to_contain_text(queue_name)
    return card


def _pick_category(card, name: str) -> None:
    """Выбирает категорию по названию в форме `ticket-category` карточки и отправляет её."""
    form = card.locator('form[data-form="ticket-category"]')
    select = form.locator("select[name=category]")
    option = select.locator("option").filter(has_text=name)
    expect(option).to_have_count(1)
    select.select_option(option.get_attribute("value"))
    form.locator("button[type=submit]").first.click()


def _events(card, code: str):
    return card.locator(f'ol[data-feed] li[data-kind="event"][data-event="{code}"]')


def _removed_assignee_event(texts: list, person: str) -> bool:
    """Среди текстов событий `assignee_changed` есть «ответственный: <человек> → не назначен» (14.5, доп. 22)."""
    return any(re.search(re.escape(person) + r".*→\s*не назначен", _norm(t)) for t in texts)


def _select_rows(page, group: str, numbers) -> None:
    """Список `?preset=all&q=<слово>` пользователя: ровно `len(numbers)` строк, все отмечены (13.2)."""
    page.goto("/tickets/?" + urllib.parse.urlencode({"preset": "all", "q": group}))
    expect(page.locator("#tickets-grid tr[data-ticket]")).to_have_count(len(numbers))
    for number in numbers:
        page.locator(f'#tickets-grid tr[data-ticket="{number}"] [data-cell="select"] input[name=numbers]').check()


# --- Тесты --------------------------------------------------------------------------------------

def test_d04_category_change_to_other_queue_asks_confirmation_then_queue_changes_with_event(
        admin_page, employee):
    """Сценарий 4, п. 1: участник очереди меняет категорию на категорию другой очереди — портал просит подтвердить
    смену очереди (ничего не меняется, «Отмена» тоже ничего не меняет), после подтверждения очередь новая, в
    ленте события смены категории и очереди (FR-240)."""
    admin = admin_page
    tag = _tag()
    actor = employee(full_name=f"{tag} Иванов Иван")
    q1_id, q1_name = helpers_sd.ensure_ready(admin)
    q2_id, q2_name = _make_queue(admin)
    category = helpers_org.unique_name("Категория1С")
    _make_category(admin, category, q2_id)
    # дано: исполнитель — участник очереди по умолчанию (и новой очереди, чтобы заявка осталась ему видна)
    _add_to_queue(admin, q1_id, [actor], tag)
    _add_to_queue(admin, q2_id, [actor], tag)
    number = _new_ticket(admin)
    page = actor.page
    card = helpers_sd.open_ticket(page, number)
    expect(card.locator('[data-field="queue"]')).to_contain_text(q1_name)
    # когда: меняет категорию на категорию другой очереди → портал просит подтвердить
    _pick_category(card, category)
    dialog = page.locator('#dialog-root [data-dialog="ticket-category"]')
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text(f"Заявка перейдёт в очередь «{q2_name}»")
    expect(card.locator('[data-field="queue"]')).to_contain_text(q1_name)  # до подтверждения ничего не изменилось
    expect(_events(card, "queue_changed")).to_have_count(0)
    # «Отмена» запросов не шлёт: очередь прежняя
    requests = []

    def _remember(request):
        if "/tickets/" in request.url:
            requests.append(request.url)

    page.on("request", _remember)
    dialog.locator("button[data-dialog-cancel]").click()
    expect(dialog).to_have_count(0)
    page.remove_listener("request", _remember)
    assert not requests, requests
    expect(card.locator('[data-field="queue"]')).to_contain_text(q1_name)
    expect(_events(card, "queue_changed")).to_have_count(0)
    # после подтверждения очередь — очередь новой категории
    _pick_category(card, category)
    expect(dialog).to_be_visible()
    dialog.locator("button[type=submit]").click()
    expect(dialog).to_have_count(0)
    expect(card.locator('[data-field="queue"]')).to_contain_text(q2_name)
    expect(card.locator('[data-field="category"]')).to_contain_text(category)
    # в ленте — событие смены очереди «было → стало» и событие смены категории (14.5)
    queue_event = _events(card, "queue_changed")
    expect(queue_event).to_have_count(1)
    text = _norm(queue_event.inner_text())
    assert q1_name in text and q2_name in text and "→" in text, text
    expect(_events(card, "category_changed")).to_have_count(1)
    assert category in _norm(_events(card, "category_changed").inner_text())


def test_d04_new_category_default_assignee_assigned_when_ticket_unassigned(admin_page, employee):
    """Сценарий 4, п. 2: у новой категории есть ответственный по умолчанию, у заявки ответственного нет — после
    смены категории (с подтверждением смены очереди) он назначен, в ленте событие «ответственный» (FR-240)."""
    admin = admin_page
    tag = _tag()
    assignee = employee(full_name=f"{tag} Петров Пётр")
    helpers_sd.ensure_ready(admin)
    q2_id, q2_name = _make_queue(admin)
    # ответственный по умолчанию категории должен быть участником очереди категории (assignee_not_participant)
    _add_to_queue(admin, q2_id, [assignee], tag)
    category = helpers_org.unique_name("Категория")
    _make_category(admin, category, q2_id, default_assignee=assignee.id)
    number = _new_ticket(admin)
    card = helpers_sd.open_ticket(admin, number)
    # дано: заявка без ответственного
    expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "true")
    # когда: категория сменена (очередь меняется — подтверждение)
    _pick_category(card, category)
    dialog = admin.locator('#dialog-root [data-dialog="ticket-category"]')
    expect(dialog).to_be_visible()
    dialog.locator("button[type=submit]").click()
    expect(dialog).to_have_count(0)
    # тогда: очередь новая, ответственный назначен
    expect(card.locator('[data-field="queue"]')).to_contain_text(q2_name)
    expect(card.locator('[data-field="assignee"]')).to_contain_text(assignee.full_name.split()[0])
    expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "false")
    changed = _events(card, "assignee_changed")
    expect(changed).to_have_count(1)
    assert assignee.full_name in _norm(changed.inner_text())


def test_d04_transfer_with_reason_feed_shows_who_from_to_reason_and_unassigns_non_member(
        admin_page, employee, stand_admin):
    """Сценарий 4, п. 3: «Передать в очередь» с причиной — в ленте «кто, откуда, куда, причина»; ответственный,
    не участник новой очереди, снят (FR-239)."""
    admin = admin_page
    tag = _tag()
    assignee = employee(full_name=f"{tag} Сидоров Сидор")
    q1_id, q1_name = helpers_sd.ensure_ready(admin)
    q2_id, q2_name = _make_queue(admin)
    _add_to_queue(admin, q1_id, [assignee], tag)  # участник только прежней очереди
    number = _new_ticket(admin)
    _assign(admin, number, assignee)
    reason = f"причина{secrets.token_hex(3)} нужен специалист по сети"
    # когда: передаём с причиной
    card = _transfer(admin, number, q2_id, q2_name, reason)
    # тогда: «кто, откуда, куда, причина»
    transferred = _events(card, "transferred")
    expect(transferred).to_have_count(1)
    text = _norm(transferred.inner_text())
    assert q1_name in text and q2_name in text and "→" in text and reason in text, text
    expect(transferred.locator("[data-author]")).to_contain_text(stand_admin.full_name)
    # ответственный снят: он не участник новой очереди (в ленте — снятие «имя → не назначен», доп. 22)
    expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "true")
    assert _removed_assignee_event(_events(card, "assignee_changed").all_inner_texts(), assignee.full_name)


def test_d04_transfer_keeps_assignee_who_is_member_of_new_queue(admin_page, employee):
    """Сценарий 4, п. 4: ответственный — участник и новой очереди тоже; при передаче он остаётся ответственным,
    снятия в ленте нет (FR-239)."""
    admin = admin_page
    tag = _tag()
    assignee = employee(full_name=f"{tag} Кузнецов Кузьма")
    q1_id, q1_name = helpers_sd.ensure_ready(admin)
    q2_id, q2_name = _make_queue(admin)
    _add_to_queue(admin, q1_id, [assignee], tag)
    _add_to_queue(admin, q2_id, [assignee], tag)
    number = _new_ticket(admin)
    _assign(admin, number, assignee)
    # когда: заявку передают в очередь, где он тоже участник (без причины)
    card = _transfer(admin, number, q2_id, q2_name)
    # тогда: он остаётся ответственным
    expect(card.locator('[data-field="assignee"]')).to_contain_text(assignee.full_name.split()[0])
    expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "false")
    transferred = _events(card, "transferred")
    expect(transferred).to_have_count(1)
    text = _norm(transferred.inner_text())
    assert q1_name in text and q2_name in text, text
    assert "причина" not in text, text  # части «; причина» без причины нет (14.5)
    assert not _removed_assignee_event(_events(card, "assignee_changed").all_inner_texts(), assignee.full_name)
    expect(_events(card, "assignee_reconciled")).to_have_count(0)


def test_d04_assigning_non_member_refused_and_not_in_picker(admin_page, employee):
    """Сценарий 4, п. 5: кандидат не участник очереди заявки — в списке выбора его нет, прямой запрос назначения
    отказан (`not_participant`), ответственный не появился (FR-237)."""
    admin = admin_page
    tag = _tag()
    member = employee(full_name=f"{tag}м Иванов Иван")
    outsider = employee(full_name=f"{tag}ч Петров Пётр")
    q1_id, _q1_name = helpers_sd.ensure_ready(admin)
    q2_id, _q2_name = _make_queue(admin)
    _add_to_queue(admin, q1_id, [member], tag)
    _add_to_queue(admin, q2_id, [outsider], tag)  # состоит в другой очереди, но не в очереди заявки
    number = _new_ticket(admin)
    card = helpers_sd.open_ticket(admin, number)
    # в списке выбора (по общему началу имён): участник очереди есть, не участника нет
    _candidates_for(card, tag)
    expect(card.locator(f'[data-candidates] label[data-candidate][data-user-id="{member.id}"]')).to_have_count(1)
    expect(card.locator(f'[data-candidates] label[data-candidate][data-user-id="{outsider.id}"]')).to_have_count(0)
    # прямой запрос назначения не участника — отказ по коду, 200 с карточкой
    response = helpers_org.direct_post(admin, f"/tickets/{number}/assign/", {"assignee": outsider.id})
    assert response.status == 200, response.status
    assert re.search(r'data-code=["\']not_participant["\']', response.text()), "нет отказа not_participant"
    # ответственный не назначен
    card = helpers_sd.open_ticket(admin, number)
    expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "true")


def test_d04_bulk_assign_five_tickets_skips_non_member_queues_with_explanation(admin_page, employee):
    """Сценарий 4, п. 6: отмечено 5 заявок, групповое «Назначить ответственного» — 3 заявки очереди, где
    кандидат участник, назначены; 2 заявки другой очереди пропущены с объяснением (FR-241)."""
    admin = admin_page
    tag = _tag()
    actor = employee(full_name=f"{tag}а Иванов Иван")
    candidate = employee(full_name=f"{tag}к Петров Пётр")
    q1_id, _q1_name = helpers_sd.ensure_ready(admin)
    q2_id, q2_name = _make_queue(admin)
    _add_to_queue(admin, q1_id, [actor, candidate], tag)  # кандидат — только в очереди по умолчанию
    _add_to_queue(admin, q2_id, [actor], tag)  # исполнитель видит заявки обеих очередей
    group = _word()
    own = [_new_ticket(admin, group) for _ in range(3)]
    foreign = [_new_ticket(admin, group) for _ in range(2)]
    for number in foreign:
        _transfer(admin, number, q2_id, q2_name)
    # когда: исполнитель отмечает 5 заявок и выбирает «Назначить ответственного»
    page = actor.page
    _select_rows(page, group, own + foreign)
    bulk = page.locator("form#tickets-bulk")
    bulk.locator("select[name=action]").select_option("assign")
    option = bulk.locator('[data-bulk-action="assign"] select[name=user] option').filter(has_text=f"{tag}к")
    expect(option).to_have_count(1)
    bulk.locator('[data-bulk-action="assign"] select[name=user]').select_option(option.get_attribute("value"))
    bulk.locator("button[type=submit]").click()
    # тогда: назначены 3, пропущены 2 с объяснением — «#номер — причина» для каждой
    result = page.locator("[data-bulk-result]")
    expect(result).to_contain_text("Выполнено: 3")
    expect(result).to_contain_text("пропущено: 2")
    skipped = result.locator("li[data-skipped]")
    expect(skipped).to_have_count(2)
    text = _norm(" ".join(skipped.all_inner_texts()))
    for number in foreign:
        assert re.search(rf"#{number}\b", text), text
        assert re.search(rf"#{number}\s*—\s*\S+", text), text  # после номера названа причина
    for number in own:
        assert not re.search(rf"#{number}\b", text), text
    # причина — «ответственный не из очереди заявки», код дополнения 42 (ж); не «нет доступа»: заявки ему видны
    for item in skipped.all():
        assert item.get_attribute("data-code") == "not_participant", item.inner_text()
    assert "нет доступа" not in text, text
    # в списке: у трёх заявок ответственный — кандидат, у двух — не назначен
    page.goto("/tickets/?" + urllib.parse.urlencode({"preset": "all", "q": group}))
    expect(page.locator("#tickets-grid tr[data-ticket]")).to_have_count(5)
    for number in own:
        cell = page.locator(f'#tickets-grid tr[data-ticket="{number}"] [data-cell="assignee"]')
        expect(cell).to_contain_text(candidate.full_name.split()[0])
    for number in foreign:
        cell = page.locator(f'#tickets-grid tr[data-ticket="{number}"] [data-cell="assignee"]')
        expect(cell).not_to_contain_text(candidate.full_name.split()[0])
        expect(cell).to_contain_text("не назначен")


def test_d04_non_member_not_assignee_direct_link_refused(admin_page, employee):
    """Сценарий 4, п. 7: сотрудник, не участник очереди заявки и не ответственный, открывает заявку по прямой
    ссылке — отказ (404, как у несуществующей: наличие заявки не раскрывается); действия над ней тоже отказаны
    (FR-234, FR-236)."""
    admin = admin_page
    tag = _tag()
    outsider = employee(full_name=f"{tag} Иванов Иван")
    helpers_sd.ensure_ready(admin)
    q2_id, _q2_name = _make_queue(admin)
    _add_to_queue(admin, q2_id, [outsider], tag)  # пункт меню «Заявки» есть, но не у очереди заявки
    number = _new_ticket(admin)
    # дано: заявка есть и видна администратору
    helpers_sd.open_ticket(admin, number)
    page = outsider.page
    page.goto("/")  # предпосылка: пункт меню «Заявки» у сотрудника есть (13.5)
    expect(page.locator('#main-menu a.menu-item[href="/tickets/"]')).to_have_count(1)
    # когда: прямая ссылка
    response = page.goto(f"/tickets/{number}/")
    # тогда: отказ, карточки нет
    assert response.status == 404, response.status
    expect(page.locator("[data-ticket-card]")).to_have_count(0)
    title, headings = page.title(), page.locator("h1").all_inner_texts()
    missing = page.goto(f"/tickets/{number + 100000}/")  # несуществующий номер отвечает так же (FR-236)
    assert missing.status == 404, missing.status
    assert page.title() == title and page.locator("h1").all_inner_texts() == headings, "404 различается"
    # прямые запросы действий — отказ того же рода (невидимая заявка: 404 раньше всего остального, доп. 2)
    assert helpers_org.direct_post(page, f"/tickets/{number}/take/").status == 404
    assert helpers_org.direct_post(page, f"/tickets/{number}/assign/", {"assignee": outsider.id}).status == 404
    # заявка осталась без ответственного
    card = helpers_sd.open_ticket(admin, number)
    expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "true")


def test_d04_bulk_transfer_and_criticality_skip_inaccessible_ticket_with_explanation(admin_page, employee):
    """Сценарий 4, п. 8: отмечено три заявки, к одной доступ пропал (администратор передал её в чужую очередь,
    пока список был открыт); «Сменить критичность» и «Передать в очередь» применены к доступным (у переданных
    ответственный снят, если не участник новой очереди), недоступная пропущена с объяснением без номера
    (FR-241, FR-239, FR-236)."""
    admin = admin_page
    tag = _tag()
    viewer = employee(full_name=f"{tag} Иванов Иван")
    q1_id, _q1_name = helpers_sd.ensure_ready(admin)
    q2_id, q2_name = _make_queue(admin)
    q3_id, q3_name = _make_queue(admin)
    _add_to_queue(admin, q1_id, [viewer], tag)  # смотрящий — только в очереди по умолчанию
    page = viewer.page

    # --- Круг 1: «Сменить критичность» -------------------------------------------------------------
    group = _word()
    first = [_new_ticket(admin, group) for _ in range(3)]
    accessible, lost = first[:2], first[2]
    old_priority = _norm(helpers_sd.field_text(helpers_sd.open_ticket(admin, accessible[0]), "priority"))
    _select_rows(page, group, first)  # дано: смотрящий открыл список и отметил все три
    _transfer(admin, lost, q3_id, q3_name)  # доступ к одной пропал
    bulk = page.locator("form#tickets-bulk")
    bulk.locator("select[name=action]").select_option("priority")
    select = bulk.locator('[data-bulk-action="priority"] select[name=priority]')
    options = [(o.get_attribute("value"), _norm(o.inner_text())) for o in select.locator("option").all()]
    new_value, new_name = next((v, n) for v, n in options if v and n != old_priority)
    select.select_option(new_value)
    bulk.locator("button[type=submit]").click()
    result = page.locator("[data-bulk-result]")
    expect(result).to_contain_text("Выполнено: 2")
    expect(result).to_contain_text("пропущено: 1")
    skipped = result.locator("li[data-skipped]")
    expect(skipped).to_have_count(1)
    assert "нет доступа" in _norm(skipped.inner_text())
    expect(skipped).to_have_attribute("data-code", "no_access")  # доп. 42 (ж)
    assert not re.search(r"\d", skipped.inner_text()), skipped.inner_text()  # номер недоступной не раскрыт (доп. 38)
    for number in accessible:
        card = helpers_sd.open_ticket(admin, number)
        assert _norm(helpers_sd.field_text(card, "priority")) == new_name
    assert _norm(helpers_sd.field_text(helpers_sd.open_ticket(admin, lost), "priority")) == old_priority

    # --- Круг 2: «Передать в очередь» ----------------------------------------------------------------
    group = _word()
    second = [_new_ticket(admin, group) for _ in range(3)]
    unassigned, assigned, lost = second
    _assign(admin, assigned, viewer)  # один из отмеченных — на самом смотрящем (не участнике очереди назначения)
    _select_rows(page, group, second)
    _transfer(admin, lost, q3_id, q3_name)
    bulk = page.locator("form#tickets-bulk")
    bulk.locator("select[name=action]").select_option("transfer")
    bulk.locator('[data-bulk-action="transfer"] select[name=queue]').select_option(str(q2_id))
    reason = f"причина{secrets.token_hex(3)} массовая передача"
    bulk.locator('[data-bulk-action="transfer"] textarea[name=reason]').fill(reason)
    bulk.locator("button[type=submit]").click()
    result = page.locator("[data-bulk-result]")
    expect(result).to_contain_text("Выполнено: 2")
    expect(result).to_contain_text("пропущено: 1")
    skipped = result.locator("li[data-skipped]")
    expect(skipped).to_have_count(1)
    assert "нет доступа" in _norm(skipped.inner_text())
    expect(skipped).to_have_attribute("data-code", "no_access")  # доп. 42 (ж)
    assert not re.search(r"\d", skipped.inner_text()), skipped.inner_text()  # номер недоступной не раскрыт
    for number in (unassigned, assigned):
        card = helpers_sd.open_ticket(admin, number)
        expect(card.locator('[data-field="queue"]')).to_contain_text(q2_name)
        transferred = _events(card, "transferred")
        expect(transferred).to_have_count(1)
        assert reason in _norm(transferred.inner_text())
    card = helpers_sd.open_ticket(admin, assigned)
    # ответственный снят: смотрящий не участник очереди назначения (FR-239)
    expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "true")
    assert _removed_assignee_event(_events(card, "assignee_changed").all_inner_texts(), viewer.full_name)
    # недоступная заявка осталась в очереди, куда её передал администратор
    card = helpers_sd.open_ticket(admin, lost)
    expect(card.locator('[data-field="queue"]')).to_contain_text(q3_name)
    expect(card.locator('[data-field="queue"]')).not_to_contain_text(q2_name)
