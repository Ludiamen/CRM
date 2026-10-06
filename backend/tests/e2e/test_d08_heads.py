"""T-3146: сценарий 8 — руководитель отдела и очереди (FR-232, FR-233, FR-234, FR-235, FR-275)."""
import re
import secrets
from urllib.parse import urlencode

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_servicedesk import build_mail

SD_ALL = "servicedesk.all"
SD_MANAGE = "servicedesk.manage"


def _word() -> str:
    """Уникальное слово темы: буква и шесть знаков (доп. 41 (в): строка из цифр — номер заявки для поиска)."""
    return f"t{secrets.token_hex(3)}"


def _tag() -> str:
    """Общая уникальная часть фамилий сотрудников теста: по ней `add_members(q=...)` находит всех сразу."""
    return "Волков" + secrets.token_hex(3)


def _staff(employee, tag: str, index: int, **kwargs):
    """Сотрудник с ФИО «<тег><n> Петр Петрович»: фамилия несёт уникальную часть (она есть и в полном ФИО, и в
    подписи «Имя Фамилия», доп. 10, 11, 23)."""
    return employee(full_name=f"{tag}{index} Петр Петрович", **kwargs)


def _sur(account) -> str:
    """Фамилия-метка сотрудника (первое слово ФИО): входит в любой показ имени."""
    return account.full_name.split()[0]


def _message_id() -> str:
    return f"<{secrets.token_hex(8)}@client.test>"


_QUEUE_NAMES: dict = {}  # id узла-очереди -> название (заполняет `_queue`): по нему проверяется передача заявки


def _new_ticket(page, default_queue_id, queue_id, shared: str) -> int:
    """Заявка из письма (очередь по умолчанию) и, если нужно, передача в `queue_id` прямым POST администратора
    (подготовка, не проверяемый шаг: передачу проверяют d04 и п. 1 этого файла; решение Opus О5). Сразу после POST —
    проверка поля «очередь» карточки. Тема содержит общее слово `shared` и своё слово."""
    word = _word()
    helpers_sd.deliver(build_mail(from_addr=helpers_sd.requester_email(), to=[MAILBOX],
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


def _assignee(page, number: int):
    """Поле ответственного карточки заявки (открывает карточку)."""
    card = helpers_sd.open_ticket(page, number)
    return card.locator('[data-field="assignee"]')


def _expect_unassigned(page, number: int):
    """Карточка заявки: ответственного нет (`data-empty="true"`), в ленте событие сверки «ответственный снят: больше
    не участник очереди» (14.5, `assignee_reconciled`). Возвращает карточку."""
    card = helpers_sd.open_ticket(page, number)
    expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "true")
    event = card.locator('ol[data-feed] li[data-kind="event"][data-event="assignee_reconciled"]')
    expect(event).to_have_count(1)
    expect(event).to_contain_text("больше не участник")
    return card


def _ui_assign(page, number: int, account) -> None:
    """Назначение из карточки (13.3): `form[data-form="ticket-assign"]`, поиск `q` по началу имени, выбор
    `label[data-candidate]` с радиокнопкой `assignee`, отправка; ждёт имя в поле ответственного."""
    card = helpers_sd.open_ticket(page, number)
    form = card.locator('form[data-form="ticket-assign"]')
    form.locator("input[name=q]").press_sequentially(_sur(account))
    radio = card.locator(f'label[data-candidate][data-user-id="{account.id}"] input[type=radio][name=assignee]')
    expect(radio).to_be_visible()
    radio.check()
    form.locator("button[type=submit]").click()
    expect(page.locator(f'[data-ticket-card][data-number="{number}"] [data-field="assignee"]')
           ).to_contain_text(_sur(account))


def _ui_transfer(page, number: int, queue_id, queue_name: str) -> None:
    """Передача из карточки: ссылка `a[data-action="ticket-transfer"]`, диалог `[data-dialog="ticket-transfer"]`,
    `select[name=queue]`, подтверждение. Заявка перестаёт быть видна передавшему — переход на `/tickets/` и
    `[role=status]` «Заявка #N передана в очередь «…»» (12.4, 14.2)."""
    card = helpers_sd.open_ticket(page, number)
    card.locator('a[data-action="ticket-transfer"]').click()
    dialog = page.locator('#dialog-root [data-dialog="ticket-transfer"]')
    expect(dialog).to_be_visible()
    dialog.locator("select[name=queue]").select_option(value=str(queue_id))
    helpers.submit(dialog.locator("form"))
    page.wait_for_url(re.compile(r"/tickets/(\?.*)?$"))
    expect(page.locator("[role=status]", has_text=f"Заявка #{number} передана в очередь «{queue_name}»")).to_be_visible()


def _list_numbers(page, shared: str) -> list:
    """Номера заявок с общим словом темы, которые пользователь видит в списке `/tickets/?preset=all&q=<слово>`
    (первая страница; чужих заявок в списке нет, 12.2)."""
    response = page.goto("/tickets/?" + urlencode({"preset": "all", "q": shared}))
    assert response.status == 200, f"список заявок: ответ {response.status}"
    expect(page.locator("[data-tickets-list]")).to_be_visible()
    return sorted(int(row.get_attribute("data-ticket")) for row in page.locator("#tickets-grid tr[data-ticket]").all())


def _status(page, path: str) -> int:
    """Код ответа на прямой переход: заявка вне видимости — 404, нет пункта меню «Заявки» — 403 на `/tickets/`."""
    return helpers_org.direct_get(page, path).status


def _menu_tickets(page):
    """Пункт меню «Заявки» (13.5) на главной странице пользователя."""
    page.goto("/")
    expect(page.locator("#main-menu")).to_be_visible()
    return page.locator('#main-menu a.menu-item[href="/tickets/"]')


def _queue(page, name: str, *, kind: str = "department", parent_id=None) -> str:
    """Узел с уникальным названием, отмеченный очередью (интерфейс срезов 002 и 003)."""
    unit_id = helpers_org.create_unit(page, name, kind=kind, parent_id=parent_id)
    helpers_sd.mark_queue(page, unit_id)
    _QUEUE_NAMES[str(unit_id)] = name
    return unit_id


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
    """Включает или снимает право роли на её странице `/roles/<id>/` и сохраняет (без кода, срез 001)."""
    page.goto(f"/roles/{role_id}/")
    box = page.locator(f'input[name=permissions][value="{code}"]')
    expect(box).to_have_count(1)
    box.set_checked(on)
    with page.expect_navigation():
        page.locator("form:has(input[name=permissions]) button[type=submit]").first.click()
    page.wait_for_load_state()


def test_d08_head_and_deputy_of_department_see_nested_queue_and_assign_and_transfer(admin_page, employee):
    """Сценарий 8, п. 1: команда «1С» в отделе «Сопровождение» — очередь; руководитель и заместитель отдела
    видят её заявки (чужой очереди — нет), назначают ответственного и передают заявку в другую очередь
    (FR-232, FR-234)."""
    page = admin_page
    default_id, _default_name = helpers_sd.ensure_ready(page)
    tag = _tag()
    head, deputy = _staff(employee, tag, 1), _staff(employee, tag, 2)
    worker = _staff(employee, tag, 3, activate=False)
    dept = helpers_org.create_unit(page, helpers_org.unique_name("Сопровождение"))
    team = _queue(page, helpers_org.unique_name("1С"), kind="team", parent_id=dept)
    other_name = helpers_org.unique_name("Другая")
    other = _queue(page, other_name)
    helpers_org.add_members(page, dept, [head.id, deputy.id], q=tag, mode="concurrent")
    helpers_org.set_marks(page, dept, "heads", [head.id])
    helpers_org.set_marks(page, dept, "deputies", [deputy.id])
    helpers_org.add_members(page, team, [worker.id], q=tag)
    for actor in (head, deputy):  # п. 1: одно и то же — у руководителя и у заместителя
        shared = _word()
        mine = _new_ticket(page, default_id, team, shared)
        foreign = _new_ticket(page, default_id, other, shared)
        # видит заявки очереди «1С» вложенной команды; заявок чужой очереди в списке нет
        numbers = _list_numbers(actor.page, shared)
        assert mine in numbers and foreign not in numbers, numbers
        assert _status(actor.page, f"/tickets/{foreign}/") == 404
        # назначает ответственного из карточки
        _ui_assign(actor.page, mine, worker)
        # передаёт в другую очередь: заявка уходит из видимости, остаётся сообщение со ссылкой на список
        _ui_transfer(actor.page, mine, other, other_name)
        card = helpers_sd.open_ticket(page, mine)
        assert other_name in helpers_sd.field_text(card, "queue")
        # ответственный не участник новой очереди — с заявки снят (доп. 22)
        expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "true")
        assert _status(actor.page, f"/tickets/{mine}/") == 404


def test_d08_plain_department_member_not_in_nested_queue_sees_only_own_assigned(admin_page, employee):
    """Сценарий 8, п. 2: рядовой участник отдела, не состоящий в команде-очереди, заявок этой очереди не видит:
    пункта «Заявки» у него нет, список закрыт, карточка заявки — 404 (FR-232, FR-234). Ветвь «если только он не
    ответственный» через интерфейс недостижима (FR-235, 6.12: ответственный всегда участник очереди своей заявки,
    при потере участия он снят сразу) — её закрывают серверные тесты 6.3 (test_sd_access)."""
    page = admin_page
    default_id, _default_name = helpers_sd.ensure_ready(page)
    tag = _tag()
    plain = _staff(employee, tag, 1)
    dept = helpers_org.create_unit(page, helpers_org.unique_name("Сопровождение"))
    team = _queue(page, helpers_org.unique_name("1С"), kind="team", parent_id=dept)
    helpers_org.add_members(page, dept, [plain.id], q=tag, mode="concurrent")
    shared = _word()
    number = _new_ticket(page, default_id, team, shared)
    # п. 2: участник отдела — не участник очереди вложенной команды: ни пункта меню, ни списка, ни карточки
    expect(_menu_tickets(plain.page)).to_have_count(0)
    assert _status(plain.page, "/tickets/") == 403
    assert _status(plain.page, f"/tickets/{number}/") == 404
    # «если только он не ответственный»: назначить не участника очереди ответственным нельзя (not_participant) —
    # вне видимости он остаётся и по прямому запросу назначения
    response = helpers_org.direct_post(page, f"/tickets/{number}/assign/", {"assignee": str(plain.id)})
    assert response.status == 200 and helpers_org.has_alert(response)
    assert 'data-code="not_participant"' in response.text()
    card = helpers_sd.open_ticket(page, number)
    expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "true")
    assert _status(plain.page, f"/tickets/{number}/") == 404


def test_d08_member_of_nested_queue_does_not_see_parent_queue(admin_page, employee):
    """Сценарий 8, п. 3: участник команды-очереди не видит заявок очереди отдела-родителя, участник отдела —
    заявок команды: участники вложенных узлов участниками очереди родителя не становятся (FR-232)."""
    page = admin_page
    default_id, _default_name = helpers_sd.ensure_ready(page)
    tag = _tag()
    in_team, in_dept = _staff(employee, tag, 1), _staff(employee, tag, 2)
    dept = _queue(page, helpers_org.unique_name("Сопровождение"))
    team = _queue(page, helpers_org.unique_name("1С"), kind="team", parent_id=dept)
    helpers_org.add_members(page, dept, [in_dept.id], q=tag, mode="concurrent")
    helpers_org.add_members(page, team, [in_team.id], q=tag)
    shared = _word()
    dept_ticket = _new_ticket(page, default_id, dept, shared)
    team_ticket = _new_ticket(page, default_id, team, shared)
    # п. 3: участник команды видит заявку команды и не видит заявку отдела
    assert _list_numbers(in_team.page, shared) == [team_ticket]
    assert _status(in_team.page, f"/tickets/{dept_ticket}/") == 404
    # и наоборот: участник отдела видит очередь отдела, но не вложенной команды
    assert _list_numbers(in_dept.page, shared) == [dept_ticket]
    assert _status(in_dept.page, f"/tickets/{team_ticket}/") == 404


def test_d08_combiner_in_two_queues_sees_both(admin_page, employee):
    """Сценарий 8, п. 4: совместитель, состоящий в двух очередях, видит заявки обеих и не видит третьей
    (FR-232)."""
    page = admin_page
    default_id, _default_name = helpers_sd.ensure_ready(page)
    tag = _tag()
    combiner = _staff(employee, tag, 1)
    first = _queue(page, helpers_org.unique_name("Первая"))
    second = _queue(page, helpers_org.unique_name("Вторая"))
    third = _queue(page, helpers_org.unique_name("Третья"))
    helpers_org.add_members(page, first, [combiner.id], q=tag, mode="concurrent")
    helpers_org.add_members(page, second, [combiner.id], q=tag, mode="concurrent")
    shared = _word()
    in_first = _new_ticket(page, default_id, first, shared)
    in_second = _new_ticket(page, default_id, second, shared)
    in_third = _new_ticket(page, default_id, third, shared)
    # п. 4: заявки обеих очередей видны, третьей — нет
    assert _list_numbers(combiner.page, shared) == sorted([in_first, in_second])
    assert _status(combiner.page, f"/tickets/{in_third}/") == 404


def test_d08_dispatcher_role_with_all_tickets_right_sees_all_queues_and_right_can_be_removed(admin_page, employee):
    """Сценарий 8, п. 5: администратор создаёт роль «Диспетчер» с правом «Все заявки»; сотрудник с ролью —
    участник всех очередей (видит заявки двух чужих очередей, может взять себе); право снимается без кода:
    доступ пропадает на следующем запросе (FR-233)."""
    page = admin_page
    default_id, _default_name = helpers_sd.ensure_ready(page)
    tag = _tag()
    dispatcher = _staff(employee, tag, 1)
    first = _queue(page, helpers_org.unique_name("Первая"))
    second = _queue(page, helpers_org.unique_name("Вторая"))
    shared = _word()
    in_first = _new_ticket(page, default_id, first, shared)
    in_second = _new_ticket(page, default_id, second, shared)
    # до роли: ни одной очереди — пункта «Заявки» нет, список закрыт
    expect(_menu_tickets(dispatcher.page)).to_have_count(0)
    assert _status(dispatcher.page, "/tickets/") == 403
    # п. 5: администратор создаёт роль с одним правом «Все заявки» (роль без прав допустима) и выдаёт её
    role = _make_role(page, helpers_org.unique_name("Диспетчер"), [SD_ALL])
    _grant_role(page, dispatcher.id, role)
    expect(_menu_tickets(dispatcher.page)).to_have_count(1)
    assert _list_numbers(dispatcher.page, shared) == sorted([in_first, in_second])
    card = helpers_sd.open_ticket(dispatcher.page, in_second)  # участник любой очереди: может взять себе
    expect(card.locator('form[data-form="ticket-take"] button[data-action="ticket-take"]')).to_be_visible()
    # право «Все заявки» снимается без кода — доступ пропал на следующем запросе
    _set_role_permission(page, role, SD_ALL, on=False)
    expect(_menu_tickets(dispatcher.page)).to_have_count(0)
    assert _status(dispatcher.page, "/tickets/") == 403
    assert _status(dispatcher.page, f"/tickets/{in_first}/") == 404


def test_d08_after_install_all_tickets_and_settings_rights_only_for_portal_admin(
        browser, browser_context_args, stand_admin, admin_page, employee):
    """Сценарий 8, п. 6: после установки права «Все заявки» и «Настройка сервис-деска» есть только у роли
    «Администратор портала»: у «Руководителя» и «Сотрудника ИТ» их нет, у сотрудника нет пунктов меню «Заявки» и
    «Сервис-деск», у администратора оба (FR-233, FR-275)."""
    helpers_sd.reset_stand_and_relogin(browser, browser_context_args, stand_admin, admin_page)
    page = admin_page
    helpers_sd.ensure_ready(page)  # params.md: после сброса — готовность
    # п. 6: права по ролям на страницах ролей (подписи — раздел 3.3)
    for name in helpers.DEFAULT_ROLES:
        page.goto(f"/roles/{helpers_org.role_id(page, name)}/")
        for code, title in ((SD_ALL, "Все заявки"), (SD_MANAGE, "Настройка сервис-деска")):
            box = page.locator(f'input[name=permissions][value="{code}"]')
            expect(box).to_have_count(1)
            expect(page.get_by_label(title, exact=True)).to_have_attribute("value", code)
            if name == helpers.ADMIN_ROLE:
                expect(box).to_be_checked()
            else:
                expect(box).not_to_be_checked()
    # у администратора — оба пункта меню, у сотрудника без ролей сервис-деска — ни одного и 403 на страницах
    expect(_menu_tickets(page)).to_have_count(1)
    expect(page.locator('#main-menu a.menu-item[href="/servicedesk/"]')).to_have_count(1)
    staff = _staff(employee, _tag(), 1)
    expect(_menu_tickets(staff.page)).to_have_count(0)
    expect(staff.page.locator('#main-menu a.menu-item[href="/servicedesk/"]')).to_have_count(0)
    assert _status(staff.page, "/tickets/") == 403
    assert _status(staff.page, "/servicedesk/") == 403


def test_d08_transfer_to_other_department_changes_queues_and_unassigns_from_lost_queue_tickets(
        admin_page, employee):
    """Сценарий 8, п. 7: перевод сотрудника в другой отдел меняет его очереди без правки списка людей: он видит
    заявки новой очереди, а с его открытых и закрытых заявок прежней очереди снят как ответственный (FR-232,
    FR-235)."""
    page = admin_page
    default_id, _default_name = helpers_sd.ensure_ready(page)
    tag = _tag()
    person = _staff(employee, tag, 1)
    old_name, new_name = helpers_org.unique_name("Старый"), helpers_org.unique_name("Новый")
    old, new = _queue(page, old_name), _queue(page, new_name)
    helpers_org.add_members(page, old, [person.id], q=tag, mode="concurrent")
    shared = _word()
    open_old = _new_ticket(page, default_id, old, shared)
    closed_old = _new_ticket(page, default_id, old, shared)
    in_new = _new_ticket(page, default_id, new, shared)
    for number in (open_old, closed_old):
        _assign_direct(page, number, person)
    # закрывает заявку сам ответственный (закрытая заявка сохраняет ответственного до сверки)
    card = helpers_sd.open_ticket(person.page, closed_old)
    card.locator('a[data-action="ticket-close"]').click()
    dialog = person.page.locator('#dialog-root [data-dialog="ticket-close"]')
    expect(dialog).to_be_visible()
    dialog.locator("textarea[name=resolution]").fill("Решено")
    helpers.submit(dialog.locator("form"))
    expect(person.page.locator(f'[data-ticket-card][data-number="{closed_old}"]')).to_have_attribute("data-kind", "closed")
    # до перевода он ответственный и по открытой, и по закрытой заявке
    for number in (open_old, closed_old):
        card = helpers_sd.open_ticket(page, number)
        expect(card.locator('[data-field="assignee"]')).to_contain_text(_sur(person))
    # до перевода: видит заявки прежней очереди и не видит новой
    assert _list_numbers(person.page, shared) == sorted([open_old, closed_old])
    # перевод в другой отдел из карточки прежнего: список людей очередей не правится
    helpers_org.open_structure(page, old)
    helpers_org.transfer_member(page, person.id, new)
    expect(helpers_org.member_row(page, person.id)).to_have_count(0)
    # п. 7: очереди сменились — видны заявки новой очереди, прежней — нет
    assert _list_numbers(person.page, shared) == [in_new]
    assert _status(person.page, f"/tickets/{open_old}/") == 404
    # с открытой и закрытой заявок прежней очереди он снят как ответственный; заявки остались в очереди
    # (сверка — событие `assignee_reconciled` «больше не участник», 14.5)
    for number in (open_old, closed_old):
        card = _expect_unassigned(page, number)
        assert old_name in helpers_sd.field_text(card, "queue")
