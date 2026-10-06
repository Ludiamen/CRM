"""T-3146: сценарий 15 — ответственного переводят или увольняют (FR-232, FR-233, FR-235, FR-251, FR-276)."""
import secrets
from urllib.parse import urlencode

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_servicedesk import build_mail

SD_ALL = "servicedesk.all"


def _word() -> str:
    """Уникальное слово темы: буква и шесть знаков (доп. 41 (в): строка из цифр — номер заявки для поиска)."""
    return f"t{secrets.token_hex(3)}"


def _tag() -> str:
    """Общая уникальная часть фамилий сотрудников теста: по ней `add_members(q=...)` находит всех сразу."""
    return "Соколов" + secrets.token_hex(3)


def _staff(employee, tag: str, index: int, **kwargs):
    """Сотрудник с ФИО «<тег><n> Петр Петрович»: фамилия несёт уникальную часть (она есть и в полном ФИО, и в
    подписи «Имя Фамилия», доп. 10, 11, 23). Кто не входит в портал сам, заводится без активации."""
    return employee(full_name=f"{tag}{index} Петр Петрович", **kwargs)


def _sur(account) -> str:
    return account.full_name.split()[0]


def _message_id() -> str:
    return f"<{secrets.token_hex(8)}@client.test>"


_QUEUE_NAMES: dict = {}  # id узла-очереди -> название (заполняет `_queue`): по нему проверяется передача заявки


def _new_ticket(page, default_queue_id, queue_id, shared: str, requester: str | None = None) -> int:
    """Заявка из письма (очередь по умолчанию) и, если нужно, передача в `queue_id` прямым POST администратора
    (подготовка, не проверяемый шаг: передачу проверяют d04 и п. 1 этого файла; решение Opus О5). Сразу после POST —
    проверка поля «очередь» карточки. Тема содержит общее слово `shared` и своё слово."""
    word = _word()
    helpers_sd.deliver(build_mail(from_addr=requester or helpers_sd.requester_email(), to=[MAILBOX],
                                  subject=f"Заявка {shared} {word}", text=f"Нужна помощь {word}",
                                  message_id=_message_id()))
    number = helpers_sd.ticket_number_by_subject(page, word)
    if str(queue_id) != str(default_queue_id):
        response = helpers_org.direct_post(page, f"/tickets/{number}/transfer/", {"queue": str(queue_id)})
        assert response.status == 302, f"передача заявки #{number} не удалась: {response.status}"
        card = helpers_sd.open_ticket(page, number)
        expect(card.locator('[data-field="queue"]')).to_contain_text(_QUEUE_NAMES[str(queue_id)])
    return number


def _assign_direct(page, number: int, account) -> None:
    """Подготовка (не проверяемый шаг, решение Opus О5): администратор назначает ответственного прямым POST
    `/tickets/<N>/assign/` (ждёт 302); сразу после — проверка поля «ответственный» карточки."""
    response = helpers_org.direct_post(page, f"/tickets/{number}/assign/", {"assignee": str(account.id)})
    assert response.status == 302, f"назначение заявки #{number} не удалось: {response.status}"
    card = helpers_sd.open_ticket(page, number)
    expect(card.locator('[data-field="assignee"]')).to_contain_text(_sur(account))


def _close(page, number: int, resolution: str = "Решено") -> None:
    """Закрытие из карточки: ссылка `a[data-action="ticket-close"]`, диалог `[data-dialog="ticket-close"]`
    (статус по умолчанию — первый пункт), решение, подтверждение; ждёт `data-kind="closed"` карточки."""
    card = helpers_sd.open_ticket(page, number)
    card.locator('a[data-action="ticket-close"]').click()
    dialog = page.locator('#dialog-root [data-dialog="ticket-close"]')
    expect(dialog).to_be_visible()
    dialog.locator("textarea[name=resolution]").fill(resolution)
    helpers.submit(dialog.locator("form"))
    expect(page.locator(f'[data-ticket-card][data-number="{number}"]')).to_have_attribute("data-kind", "closed")


def _dismiss(page, user_id) -> None:
    """Увольнение из карточки сотрудника (срез 002): `[data-action="dismiss"]`, диалог, подтверждение; ждёт отметку
    `[data-dismissed-badge]` рядом с ФИО."""
    page.goto(f"/staff/{user_id}/")
    card = page.locator(f'[data-card][data-user-id="{user_id}"]')
    card.locator('[data-action="dismiss"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(card.locator("[data-dismissed-badge]")).to_be_visible()


def _list_numbers(page, shared: str, preset: str = "all") -> list:
    """Номера заявок с общим словом темы в списке пользователя `/tickets/?preset=<пресет>&q=<слово>` (первая
    страница)."""
    response = page.goto("/tickets/?" + urlencode({"preset": preset, "q": shared}))
    assert response.status == 200, f"список заявок: ответ {response.status}"
    expect(page.locator("[data-tickets-list]")).to_be_visible()
    return sorted(int(row.get_attribute("data-ticket")) for row in page.locator("#tickets-grid tr[data-ticket]").all())


def _status(page, path: str) -> int:
    """Код ответа на прямой переход (заявка вне видимости — 404, закрытый список — 403)."""
    return helpers_org.direct_get(page, path).status


def _queue(page, name: str, *, kind: str = "department", parent_id=None) -> str:
    """Узел с уникальным названием, отмеченный очередью."""
    unit_id = helpers_org.create_unit(page, name, kind=kind, parent_id=parent_id)
    helpers_sd.mark_queue(page, unit_id)
    _QUEUE_NAMES[str(unit_id)] = name
    return unit_id


def _expect_unassigned(page, number: int, *, reconciled: bool = True):
    """Карточка заявки: ответственного нет (`data-empty="true"`); при `reconciled` — в ленте событие сверки
    «ответственный снят: больше не участник очереди» (14.5, `assignee_reconciled`). Возвращает карточку."""
    card = helpers_sd.open_ticket(page, number)
    expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "true")
    if reconciled:
        event = card.locator('ol[data-feed] li[data-kind="event"][data-event="assignee_reconciled"]')
        expect(event).to_have_count(1)
        expect(event).to_contain_text("больше не участник")
    return card


def _make_role(page, name: str, codes) -> str:
    """Своя роль с правами `codes` (форма `/roles/new/`, флажки `permissions`); возвращает номер роли."""
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
    """Личная роль из формы `form[action$="/roles/"]` карточки сотрудника (срез 001); ждёт ответ POST."""
    page.goto(f"/staff/{user_id}/")
    form = page.locator('form[action$="/roles/"]')
    form.locator(f'input[name=roles][value="{role_id}"]').check()
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()


def _set_role_permission(page, role_id, code: str, *, on: bool) -> None:
    """Включает или снимает право роли на её странице `/roles/<id>/` и сохраняет."""
    page.goto(f"/roles/{role_id}/")
    box = page.locator(f'input[name=permissions][value="{code}"]')
    expect(box).to_have_count(1)
    box.set_checked(on)
    with page.expect_navigation():
        page.locator("form:has(input[name=permissions]) button[type=submit]").first.click()
    page.wait_for_load_state()


def test_d15_transfer_or_dismissal_unassigns_open_and_closed_tickets_of_lost_queue_with_feed_event(
        admin_page, employee):
    """Сценарий 15, п. 1: после перевода в другой отдел и после увольнения открытые и закрытые заявки очереди,
    которой человек больше не участник, остались в очереди без ответственного, в ленте — событие (FR-235)."""
    page = admin_page
    default_id, _default_name = helpers_sd.ensure_ready(page)
    tag = _tag()
    moved, dismissed = _staff(employee, tag, 1, activate=False), _staff(employee, tag, 2, activate=False)
    queue_name = helpers_org.unique_name("Очередь")
    queue = _queue(page, queue_name)
    target = helpers_org.create_unit(page, helpers_org.unique_name("Другой"))  # отдел без очереди
    helpers_org.add_members(page, queue, [moved.id, dismissed.id], q=tag, mode="concurrent")
    shared = _word()
    tickets = {}
    for who in (moved, dismissed):
        opened = _new_ticket(page, default_id, queue, shared)
        closed = _new_ticket(page, default_id, queue, shared)
        for number in (opened, closed):
            _assign_direct(page, number, who)
        _close(page, closed)
        tickets[who.id] = (opened, closed)
        for number in (opened, closed):  # до изменения ответственный на месте
            card = helpers_sd.open_ticket(page, number)
            expect(card.locator('[data-field="assignee"]')).to_contain_text(_sur(who))
    # п. 1: перевод одного и увольнение другого
    helpers_org.open_structure(page, queue)
    helpers_org.transfer_member(page, moved.id, target)
    expect(helpers_org.member_row(page, moved.id)).to_have_count(0)
    _dismiss(page, dismissed.id)
    for numbers in tickets.values():
        for number in numbers:
            card = _expect_unassigned(page, number)
            assert queue_name in helpers_sd.field_text(card, "queue")  # заявка осталась в своей очереди


def test_d15_combiner_or_upper_head_keeps_tickets_after_transfer(admin_page, employee):
    """Сценарий 15, п. 2: совместитель (остаётся в команде-очереди) и руководитель вышестоящего узла (остаётся
    руководителем отдела-родителя очереди) после перевода из другого отдела сохраняют свои заявки (FR-235)."""
    page = admin_page
    default_id, _default_name = helpers_sd.ensure_ready(page)
    tag = _tag()
    combiner, head = _staff(employee, tag, 1), _staff(employee, tag, 2)
    parent = helpers_org.create_unit(page, helpers_org.unique_name("Отдел"))
    team = _queue(page, helpers_org.unique_name("Команда"), kind="team", parent_id=parent)
    side = helpers_org.create_unit(page, helpers_org.unique_name("Побочный"))
    target = helpers_org.create_unit(page, helpers_org.unique_name("Новый"))
    # совместитель: состоит в отделе и в команде-очереди; руководитель: возглавляет отдел-родитель, состоит ещё и в другом
    helpers_org.add_members(page, parent, [combiner.id, head.id], q=tag, mode="concurrent")
    helpers_org.add_members(page, team, [combiner.id], q=tag)
    helpers_org.set_marks(page, parent, "heads", [head.id])
    helpers_org.add_members(page, side, [head.id], q=tag, mode="concurrent")
    shared = _word()
    by_combiner = _new_ticket(page, default_id, team, shared)
    by_head = _new_ticket(page, default_id, team, shared)
    _assign_direct(page, by_combiner, combiner)
    _assign_direct(page, by_head, head)
    # п. 2: совместитель переведён из отдела-родителя (команда остаётся), руководитель — из побочного отдела
    helpers_org.open_structure(page, parent)
    helpers_org.transfer_member(page, combiner.id, target)
    expect(helpers_org.member_row(page, combiner.id)).to_have_count(0)
    helpers_org.open_structure(page, side)
    helpers_org.transfer_member(page, head.id, target)
    expect(helpers_org.member_row(page, head.id)).to_have_count(0)
    for number, who in ((by_combiner, combiner), (by_head, head)):
        card = helpers_sd.open_ticket(page, number)
        expect(card.locator('[data-field="assignee"]')).to_contain_text(_sur(who))
        expect(card.locator('li[data-event="assignee_reconciled"]')).to_have_count(0)  # после положительной проверки
        assert number in _list_numbers(who.page, shared, "mine")


def test_d15_dismissed_signed_by_name_with_dismissed_mark_on_closed_tickets_and_messages(admin_page, employee):
    """Сценарий 15, п. 3: у уволенного закрытые заявки и сообщения подписаны его именем с пометкой «уволен»:
    «Закрыл: Имя Фамилия (уволен)» в карточке и списке, автор ответа в ленте — полное имя и «(уволен)»
    (FR-235; SPEC-002 FR-125)."""
    page = admin_page
    default_id, _default_name = helpers_sd.ensure_ready(page)
    tag = _tag()
    person = _staff(employee, tag, 1)
    queue = _queue(page, helpers_org.unique_name("Очередь"))
    helpers_org.add_members(page, queue, [person.id], q=tag, mode="concurrent")
    shared = _word()
    number = _new_ticket(page, default_id, queue, shared)
    _assign_direct(page, number, person)
    # сотрудник отвечает заявителю и сам закрывает заявку: он — автор ответа и «закрыл»
    card = helpers_sd.open_ticket(person.page, number)
    form = card.locator('form[data-form="ticket-reply"]')
    form.locator("textarea[name=text]").fill(f"Ответ исполнителя {shared}")
    helpers.submit(form)
    expect(person.page.locator('ol[data-feed] li[data-kind="reply"]')).to_have_count(1)
    _close(person.page, number)
    _dismiss(page, person.id)
    # п. 3: карточка — закрыл уволенный, автор ответа подписан полным именем с пометкой
    card = _expect_unassigned(page, number)
    closed_by = card.locator('[data-field="closed-by"]')
    expect(closed_by).to_contain_text("Закрыл:")
    expect(closed_by).to_contain_text(_sur(person))
    expect(closed_by).to_contain_text("(уволен)")
    author = card.locator('ol[data-feed] li[data-kind="reply"] [data-author][data-dismissed="true"]')
    expect(author).to_have_count(1)
    expect(author).to_contain_text(person.full_name)
    expect(author).to_contain_text("(уволен)")
    # список: у закрытой заявки без ответственного в колонке «ответственный» — «Закрыл: …» с отметкой
    page.goto("/tickets/?" + urlencode({"preset": "all", "q": shared}))
    cell = page.locator(f'#tickets-grid tr[data-ticket="{number}"] [data-cell="assignee"]')
    expect(cell).to_contain_text("Закрыл:")
    expect(cell).to_contain_text(_sur(person))
    expect(cell).to_contain_text("(уволен)")


def test_d15_unassigned_after_dismissal_appear_in_unassigned_preset_of_queue_member(admin_page, employee):
    """Сценарий 15, п. 4: открытые заявки уволенного без ответственного появились в пресете «Без ответственного»
    у участника очереди (закрытая — нет: пресет только про открытые) (FR-235, FR-276)."""
    page = admin_page
    default_id, _default_name = helpers_sd.ensure_ready(page)
    tag = _tag()
    leaver, colleague = _staff(employee, tag, 1, activate=False), _staff(employee, tag, 2)
    queue = _queue(page, helpers_org.unique_name("Очередь"))
    helpers_org.add_members(page, queue, [leaver.id, colleague.id], q=tag, mode="concurrent")
    shared = _word()
    first, second, closed = (_new_ticket(page, default_id, queue, shared) for _ in range(3))
    for number in (first, second, closed):
        _assign_direct(page, number, leaver)
    _close(page, closed)
    # до увольнения в пресете этих заявок нет: они за уволенным
    assert _list_numbers(colleague.page, shared, "unassigned") == []
    _dismiss(page, leaver.id)
    # п. 4: участник очереди открывает «Без ответственного» — там обе открытые заявки
    assert _list_numbers(colleague.page, shared, "unassigned") == sorted([first, second])
    expect(colleague.page.locator('nav[data-presets] a[data-preset="unassigned"]')).to_have_attribute(
        "aria-current", "true")
    assert _list_numbers(colleague.page, shared, "all") == sorted([first, second, closed])


def test_d15_reopened_closed_ticket_with_dismissed_assignee_has_no_assignee(admin_page, employee):
    """Сценарий 15, п. 5: закрытая заявка уволенного ответственного при открытии заново остаётся без
    ответственного (FR-251): и при ручном открытии кнопкой (FR-252), и при открытии письмом заявителя `Re: [#N]`
    (FR-251, открытие по сроку, ответственный прежний — только если он участник)."""
    page = admin_page
    default_id, _default_name = helpers_sd.ensure_ready(page)
    tag = _tag()
    manual, by_mail = _staff(employee, tag, 1, activate=False), _staff(employee, tag, 2, activate=False)
    queue_name = helpers_org.unique_name("Очередь")
    queue = _queue(page, queue_name)
    helpers_org.add_members(page, queue, [manual.id, by_mail.id], q=tag, mode="concurrent")
    shared = _word()
    requester = helpers_sd.requester_email()
    first = _new_ticket(page, default_id, queue, shared)
    second = _new_ticket(page, default_id, queue, shared, requester=requester)
    _assign_direct(page, first, manual)
    _assign_direct(page, second, by_mail)
    _close(page, first)
    _close(page, second)
    _dismiss(page, manual.id)
    _dismiss(page, by_mail.id)
    _expect_unassigned(page, first)
    _expect_unassigned(page, second)
    # п. 5, случай 1: открываем заново из карточки («Открыть заново»)
    card = helpers_sd.open_ticket(page, first)
    card.locator('form[data-form="ticket-reopen"] button[data-action="ticket-reopen"]').click()
    root = page.locator(f'[data-ticket-card][data-number="{first}"]')
    expect(root).not_to_have_attribute("data-kind", "closed")
    expect(root.locator('li[data-kind="event"][data-event="reopened"]')).to_have_count(1)
    expect(root.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "true")
    assert queue_name in helpers_sd.field_text(root, "queue")
    # п. 5, случай 2: заявитель отвечает письмом `Re: [#N]` на закрытую заявку (в пределах срока открытия)
    helpers_sd.deliver(build_mail(from_addr=requester, to=[MAILBOX], subject=f"Re: [#{second}] Заявка {shared}",
                                  text="Вопрос остался, откройте заявку снова", message_id=_message_id()))
    card = helpers_sd.open_ticket(page, second)
    expect(card).not_to_have_attribute("data-kind", "closed")
    expect(card.locator('li[data-kind="event"][data-event="reopened"]')).to_have_count(1)
    expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "true")
    assert queue_name in helpers_sd.field_text(card, "queue")


def test_d15_queue_unit_moved_or_heads_changed_access_changes_at_once(admin_page, employee):
    """Сценарий 15, п. 6: когда узел-очередь перенесён под другой отдел или сменились руководитель и
    заместитель, доступ к заявкам очереди меняется сразу, на следующем запросе (FR-232)."""
    page = admin_page
    default_id, _default_name = helpers_sd.ensure_ready(page)
    tag = _tag()
    chief, deputy, old_head, new_head = (_staff(employee, tag, i) for i in (1, 2, 3, 4))
    shared = _word()
    # часть 1: отметки руководителя и заместителя
    parent = helpers_org.create_unit(page, helpers_org.unique_name("Отдел"))
    team = _queue(page, helpers_org.unique_name("Команда"), kind="team", parent_id=parent)
    helpers_org.add_members(page, parent, [chief.id, deputy.id], q=tag, mode="concurrent")
    ticket = _new_ticket(page, default_id, team, shared)
    assert _status(chief.page, f"/tickets/{ticket}/") == 404  # рядовой участник отдела очереди не видит
    helpers_org.set_marks(page, parent, "heads", [chief.id])
    assert _status(chief.page, f"/tickets/{ticket}/") == 200  # руководителем стал — видит сразу
    assert _status(deputy.page, f"/tickets/{ticket}/") == 404
    helpers_org.set_marks(page, parent, "heads", [])
    helpers_org.set_marks(page, parent, "deputies", [deputy.id])
    assert _status(chief.page, f"/tickets/{ticket}/") == 404  # отметка снята — доступ пропал сразу
    assert _status(deputy.page, f"/tickets/{ticket}/") == 200  # заместитель — видит
    helpers_org.set_marks(page, parent, "deputies", [])
    assert _status(deputy.page, f"/tickets/{ticket}/") == 404
    # часть 2: очередь переносится под другой отдел
    old_parent = helpers_org.create_unit(page, helpers_org.unique_name("Старый"))
    new_parent = helpers_org.create_unit(page, helpers_org.unique_name("Новый"))
    moving = _queue(page, helpers_org.unique_name("Переезд"), kind="team", parent_id=old_parent)
    helpers_org.add_members(page, old_parent, [old_head.id], q=tag, mode="concurrent")
    helpers_org.add_members(page, new_parent, [new_head.id], q=tag, mode="concurrent")
    helpers_org.set_marks(page, old_parent, "heads", [old_head.id])
    helpers_org.set_marks(page, new_parent, "heads", [new_head.id])
    moved_ticket = _new_ticket(page, default_id, moving, shared)
    assert _status(old_head.page, f"/tickets/{moved_ticket}/") == 200
    assert _status(new_head.page, f"/tickets/{moved_ticket}/") == 404
    helpers_org.edit_unit(page, moving, parent_id=new_parent)
    assert _status(old_head.page, f"/tickets/{moved_ticket}/") == 404  # прежний руководитель потерял доступ сразу
    assert _status(new_head.page, f"/tickets/{moved_ticket}/") == 200  # руководитель нового места получил
    assert moved_ticket in _list_numbers(new_head.page, shared)


def test_d15_closed_ticket_shows_closed_by_after_assignee_lost_queue_and_history_keeps_assignee(
        admin_page, employee):
    """Сценарий 15, п. 7: закрытая заявка, ответственный по которой перестал быть участником очереди, без
    ответственного, но с «Закрыл: Имя Фамилия» в карточке и списке; в истории ленты остаётся, кто вёл заявку
    (FR-235)."""
    page = admin_page
    default_id, _default_name = helpers_sd.ensure_ready(page)
    tag = _tag()
    person = _staff(employee, tag, 1)
    queue = _queue(page, helpers_org.unique_name("Очередь"))
    target = helpers_org.create_unit(page, helpers_org.unique_name("Другой"))
    helpers_org.add_members(page, queue, [person.id], q=tag, mode="concurrent")
    shared = _word()
    number = _new_ticket(page, default_id, queue, shared)
    _assign_direct(page, number, person)
    _close(person.page, number)  # закрыл сам: closed_by — он
    helpers_org.open_structure(page, queue)
    helpers_org.transfer_member(page, person.id, target)
    expect(helpers_org.member_row(page, person.id)).to_have_count(0)
    # п. 7: карточка — ответственного нет, «Закрыл: …» (без «уволен»: человек работает)
    card = _expect_unassigned(page, number)
    closed_by = card.locator('[data-field="closed-by"]')
    expect(closed_by).to_contain_text("Закрыл:")
    expect(closed_by).to_contain_text(_sur(person))
    expect(closed_by).not_to_contain_text("(уволен)")
    # история: событие назначения с именем ответственного осталось в ленте
    expect(card.locator('li[data-kind="event"][data-event="assignee_changed"]', has_text=_sur(person)).first
           ).to_be_visible()
    # список: в колонке «ответственный» — «Закрыл: …»
    page.goto("/tickets/?" + urlencode({"preset": "all", "q": shared}))
    cell = page.locator(f'#tickets-grid tr[data-ticket="{number}"] [data-cell="assignee"]')
    expect(cell).to_contain_text("Закрыл:")
    expect(cell).to_contain_text(_sur(person))


def test_d15_all_tickets_right_removed_unassigns_tickets_of_foreign_queues_with_event(admin_page, employee):
    """Сценарий 15, п. 8: у держателя права «Все заявки», ответственного по заявкам чужих очередей, право снято:
    с заявок очередей, где он не участник, он снят (в ленте событие), заявка его очереди осталась за ним
    (FR-235, FR-233)."""
    page = admin_page
    default_id, _default_name = helpers_sd.ensure_ready(page)
    tag = _tag()
    holder = _staff(employee, tag, 1)
    first = _queue(page, helpers_org.unique_name("Первая"))
    second = _queue(page, helpers_org.unique_name("Вторая"))
    own = _queue(page, helpers_org.unique_name("Своя"))
    helpers_org.add_members(page, own, [holder.id], q=tag, mode="concurrent")
    role = _make_role(page, helpers_org.unique_name("Диспетчер"), [SD_ALL])
    _grant_role(page, holder.id, role)
    shared = _word()
    foreign_a = _new_ticket(page, default_id, first, shared)
    foreign_b = _new_ticket(page, default_id, second, shared)
    own_ticket = _new_ticket(page, default_id, own, shared)
    for number in (foreign_a, foreign_b, own_ticket):
        _assign_direct(page, number, holder)
    assert _list_numbers(holder.page, shared) == sorted([foreign_a, foreign_b, own_ticket])
    # п. 8: право снято
    _set_role_permission(page, role, SD_ALL, on=False)
    for number in (foreign_a, foreign_b):
        _expect_unassigned(page, number)
        assert _status(holder.page, f"/tickets/{number}/") == 404
    card = helpers_sd.open_ticket(page, own_ticket)
    expect(card.locator('[data-field="assignee"]')).to_contain_text(_sur(holder))
    expect(card.locator('li[data-event="assignee_reconciled"]')).to_have_count(0)  # после положительной проверки
    assert _list_numbers(holder.page, shared) == [own_ticket]
