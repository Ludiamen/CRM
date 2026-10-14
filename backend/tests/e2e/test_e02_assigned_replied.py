"""T-4141: сценарий 2 — назначение ответственным и ответ заявителя: уведомления «Вам назначена заявка» и «Заявитель
ответил», «Новая заявка» при открытии заново без ответственного (FR-306, FR-309, FR-310, FR-311, FR-315).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-004.md):
- каждый тест заводит свою очередь, своих сотрудников и свои заявки (имена уникальны); очередь по умолчанию на время
  теста меняется на свою и возвращается в `finally` (письмо заявителя попадает в очередь по умолчанию);
- уведомления читаются со страницы `/notifications/` самого сотрудника (его страница `Account.page`), строки
  отбираются по слову темы и по началу текста вида: у сотрудника по одной заявке бывает несколько уведомлений
  («Новая заявка» при создании, «Вам назначена», «Заявитель ответил»), поэтому число строк считается по виду;
- открытие карточки заявки сотрудником отмечает его уведомления о ней прочитанными (событие `object.viewed`, § 13.1),
  число на колокольчике от этого уменьшается, строки списка остаются: тесты опираются на строки, а не на число;
- «уведомления нет» проверяется только после положительного контроля того же вида (другой сотрудник, другая заявка
  или то же событие в другом случае): сначала ждём положительную строку, потом смотрим, что отрицательной нет;
- обработчики событий шины работают после фиксации в том же запросе; положительные строки всё равно ждутся с
  пределом (опрос списка), а не берутся с первого раза;
- настройки, которые тест меняет: только очередь по умолчанию сервис-деска (`_default_queue`), она возвращается в
  `finally`; команд стенда, кроме `helpers_sd.deliver` (разбор ящика), и `helpers.stand_shell` нет.
"""
import contextlib
import re
import secrets
import time
import urllib.parse

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_notify, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_servicedesk import build_mail

SD_ALL = "servicedesk.all"
NEW_PREFIX = "Новая заявка #"  # начало текста вида «Новая заявка в моей очереди» (§ 15.1)
ASSIGNED_PREFIX = "Вам назначена заявка"  # начало текста вида «Мне назначили заявку» (§ 15.1)
REPLIED_PREFIX = "Заявитель ответил в заявке"  # начало текста вида «Заявитель ответил» (§ 15.1)
REF_RE = re.compile(r"/tickets/(\d+)/$")
WAIT_SECONDS = 20.0  # предел ожидания строки в списке уведомлений
LONG_WAIT_MS = 15_000  # предел ожидания числа колокольчика там, где срок 2 с (NFR-301) не проверяется


# --- Общие помощники файла ----------------------------------------------------------------------------

def _word() -> str:
    """Уникальное слово темы: буква и шесть шестнадцатеричных знаков (не из одних цифр, иначе поиск списка принял бы
    его за номер заявки; CONTRACT-003, доп. 41 (в))."""
    return f"t{secrets.token_hex(3)}"


def _tag() -> str:
    """Общее начало фамилий сотрудников теста: по нему «Добавить сотрудников» находит всех сразу."""
    return "Очередь" + secrets.token_hex(3)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _message_id() -> str:
    return f"<{secrets.token_hex(8)}@client.test>"


def _staff(employee, tag: str, index: int):
    return employee(full_name=f"{tag}{index} Петр Петрович")


def _queue(page, prefix: str = "Поддержка", *, kind: str = "department", parent_id=None) -> tuple:
    """Новый узел `org`, отмеченный очередью: `(номер, название)`."""
    name = helpers_org.unique_name(prefix)
    unit_id = helpers_org.create_unit(page, name, kind=kind, parent_id=parent_id)
    helpers_sd.mark_queue(page, unit_id)
    return unit_id, name


def _members(page, queue_id, accounts, tag: str) -> None:
    """Прямые участники узла-очереди. У отдела — режим «параллельно» (человек может состоять в нескольких узлах),
    у команды выбора режима нет."""
    page.goto(f"/structure/{queue_id}/")
    mode = "concurrent" if page.locator("#unit-card select[name=mode]").count() else None
    note = helpers_org.add_members(page, queue_id, [a.id for a in accounts], q=tag, mode=mode)
    assert "уже участник" not in note, note
    helpers_org.open_structure(page, queue_id)
    for account in accounts:
        expect(helpers_org.member_row(page, account.id)).to_have_count(1)


def _remove(page, queue_id, account) -> None:
    """Меню «…» → «Удалить из отдела/команды»: сотрудник перестаёт быть участником очереди."""
    page.goto(f"/structure/{queue_id}/")
    helpers_org.remove_member(page, account.id)
    page.wait_for_load_state()
    expect(helpers_org.member_row(page, account.id)).to_have_count(0)


@contextlib.contextmanager
def _default_queue(page, old_id, queue_id):
    """Очередь по умолчанию на время теста — своя (письмо попадает в неё); прежняя возвращается в `finally`."""
    helpers_sd.set_default_queue(page, queue_id)
    try:
        yield
    finally:
        helpers_sd.set_default_queue(page, old_id)


def _new_ticket(page, *, title: str = "Не работает принтер", group: str | None = None, cc=()) -> tuple:
    """Заявка письмом заявителя в очередь по умолчанию (без ответственного): `(номер, слово, тема, адрес заявителя)`.
    `group` — общее слово нескольких заявок теста (в теме рядом с уникальным словом). Номер — поиском по слову темы
    страницей `page` (администратор)."""
    word, sender = _word(), helpers_sd.requester_email()
    subject = f"{title} {group} {word}" if group else f"{title} {word}"
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], cc=list(cc), subject=subject,
                                  text=f"Нужна помощь {word}", message_id=_message_id()))
    return helpers_sd.ticket_number_by_subject(page, word), word, subject, sender


def _mail_in(sender: str, number: int, subject: str, text: str) -> None:
    """Письмо `Re: [#N] <тема>` в ящик заявок от `sender` и сразу разбор (`helpers_sd.deliver` зовёт разбор сам)."""
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=f"Re: [#{number}] {subject}", text=text,
                                  message_id=_message_id()))


def _text_new(number, queue_name: str, subject: str) -> str:
    """Текст уведомления «Новая заявка в моей очереди» (§ 15.1, FR-316)."""
    return f"Новая заявка #{number} в очереди «{queue_name}»: {subject}"


def _text_assigned(number, subject: str) -> str:
    """Текст уведомления «Вам назначена заявка» (§ 15.1)."""
    return f"Вам назначена заявка #{number}: {subject}"


def _text_replied(number, subject: str) -> str:
    """Текст уведомления «Заявитель ответил» (§ 15.1); тема — тема заявки, не тема письма с «Re:»."""
    return f"Заявитель ответил в заявке #{number}: {subject}"


def _rows(page, word: str):
    """Открывает `/notifications/` и возвращает строки списка, в тексте которых есть слово темы. Список только
    читает (не отмечает прочитанным)."""
    page.goto("/notifications/")
    expect(page.locator("[data-notify-list]")).to_be_visible()
    return page.locator("ul[data-notifications] li[data-notification]").filter(has_text=word)


def _kind_rows(page, word: str, prefix: str):
    """Строки списка со словом темы, текст которых (`[data-field="text"]`) начинается с `prefix` (вид уведомления)."""
    return _rows(page, word).filter(has=page.locator('[data-field="text"]', has_text=prefix))


def _kind_texts(page, word: str, prefix: str) -> list:
    """Тексты строк списка со словом темы и началом текста `prefix`."""
    rows = _kind_rows(page, word, prefix)
    return [_norm(t) for t in rows.locator('[data-field="text"]').all_inner_texts()]


def _wait_kind(page, word: str, prefix: str, count: int, *, timeout: float = WAIT_SECONDS) -> list:
    """Ждёт (опрос с пределом `timeout` с), пока в списке уведомлений будет не меньше `count` строк вида `prefix` по
    слову темы; возвращает их тексты. Сверять число и текст вызывающий должен сам (лишняя строка — ошибка теста)."""
    deadline = time.monotonic() + timeout
    while True:
        texts = _kind_texts(page, word, prefix)
        if len(texts) >= count:
            return texts
        if time.monotonic() >= deadline:
            raise AssertionError(f"за {timeout:.0f} с в списке уведомлений строк «{prefix}…» со словом темы "
                                 f"{len(texts)}, ждали {count}")
        page.wait_for_timeout(500)


def _no_kind(page, word: str, prefix: str, who: str) -> None:
    """В списке уведомлений нет ни одной строки вида `prefix` по слову темы (звать после положительного контроля)."""
    texts = _kind_texts(page, word, prefix)
    assert not texts, f"{who}: лишнее уведомление «{prefix}…»: {texts}"


def _wait_plus(page, base: int, step: int = 1, *, timeout_ms: int = LONG_WAIT_MS) -> int:
    """Ждёт, пока число колокольчика станет `base + step`; возвращает новое число."""
    helpers_notify.wait_bell_count(page, base + step, timeout_ms=timeout_ms)
    return base + step


def _card(page, number: int):
    """Корень карточки заявки на открытой странице (13.3); при замене фрагмента HTMX находится заново."""
    return page.locator(f'[data-ticket-card][data-number="{number}"]')


def _candidates_for(card, query: str) -> None:
    """Вводит запрос в поле `q` формы назначения карточки и ждёт, пока подсказки (`hx-get` на `…/assignees/`) придут:
    первая подсказка видна (CONTRACT-003, доп. 42 (б))."""
    box = card.locator('form[data-form="ticket-assign"] input[name=q]')
    with card.page.expect_response(lambda r: "/assignees/" in r.url) as info:
        box.fill(query)
    assert info.value.ok, f"подсказки назначения: ответ {info.value.status}"
    expect(card.locator('form[data-form="ticket-assign"] [data-candidates] label[data-candidate]').first).to_be_visible()


def _assign(page, number: int, user) -> None:
    """Назначить ответственного через карточку страницей `page`: подсказки → выбор → кнопка (CONTRACT-003, 13.3)."""
    card = helpers_sd.open_ticket(page, number)
    _candidates_for(card, user.full_name.split()[0])
    label = card.locator(f'label[data-candidate][data-user-id="{user.id}"]')
    expect(label).to_have_count(1)
    label.click()
    expect(label.locator("input[type=radio][name=assignee]")).to_be_checked()
    helpers.submit(card.locator('form[data-form="ticket-assign"]'))
    expect(card.locator('[data-field="assignee"]')).to_contain_text(user.full_name.split()[0])


def _take(page, number: int) -> None:
    """«Взять себе» со страницы карточки; ждёт вид «в работе»."""
    card = helpers_sd.open_ticket(page, number)
    card.locator('form[data-form="ticket-take"] button[data-action="ticket-take"]').click()
    expect(card).to_have_attribute("data-kind", "in_progress")


def _close(page, number: int, resolution: str) -> None:
    """Закрытие через диалог `ticket-close` со статусом по умолчанию и текстом решения."""
    helpers_sd.open_ticket(page, number)
    page.locator('a[data-action="ticket-close"]').click()
    dialog = page.locator('#dialog-root [data-dialog="ticket-close"]')
    expect(dialog).to_be_visible()
    dialog.locator("textarea[name=resolution]").fill(resolution)
    dialog.locator("button[type=submit]").click()
    expect(_card(page, number)).to_have_attribute("data-kind", "closed")


def _reopen_manual(page, number: int) -> None:
    """«Открыть заново» из карточки закрытой заявки (форма `ticket-reopen`): заявка снова «в работе»."""
    card = helpers_sd.open_ticket(page, number)
    expect(card).to_have_attribute("data-kind", "closed")
    helpers.submit(card.locator('form[data-form="ticket-reopen"]'))
    expect(_card(page, number)).to_have_attribute("data-kind", "in_progress")


def _reply(page, number: int, text: str) -> None:
    """Ответ исполнителя из карточки (форма `ticket-reply`); ждёт появления элемента `reply` в ленте."""
    card = helpers_sd.open_ticket(page, number)
    form = card.locator('form[data-form="ticket-reply"]')
    form.locator("textarea[name=text]").fill(text)
    helpers.submit(form)
    expect(card.locator('ol[data-feed] li[data-kind="reply"]').filter(has_text=text)).to_have_count(1)


def _incoming(card):
    return card.locator('ol[data-feed] li[data-entry][data-kind="incoming"]')


def _category(page, queue_id, *, default_assignee=None) -> tuple:
    """Категория с уникальным названием, показываемая на открытой форме: `(номер, название)`."""
    name = f"Принтер {secrets.token_hex(3)}"
    page.goto("/servicedesk/dictionaries/categories/new/")
    form = page.locator('form[data-form="dictionary"]')
    expect(form).to_be_visible()
    form.locator("input[name=name]").fill(name)
    form.locator("input[name=order]").fill("50")
    form.locator("select[name=queue]").select_option(value=str(queue_id))
    if default_assignee is not None:
        form.locator("select[name=default_assignee]").select_option(value=str(default_assignee))
    form.locator("input[type=checkbox][name=on_form]").set_checked(True)
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    refusal = page.locator("[data-error], [role=alert][data-code]")
    assert not refusal.count(), f"категория не создана: {refusal.first.get_attribute('data-code')}"
    row = page.locator("tr[data-dictionary-row]").filter(has=page.locator('[data-cell="name"]', has_text=name))
    expect(row).to_have_count(1)
    return row.get_attribute("data-id"), name


def _phone_ticket(page, category_id, queue_id) -> tuple:
    """Заявка по звонку формой `/tickets/new/` без «Взять себе»: `(слово, тема)`, номер — в адресе страницы
    (`REF_RE`). Без ответственного она остаётся, только если у категории нет ответственного по умолчанию
    (CONTRACT-003, 6.7 `create`: с ним ответственным становится он)."""
    word = _word()
    subject = f"Звонок {word}"
    page.goto("/tickets/new/")
    form = page.locator('form[data-form="ticket-new"]')
    expect(form).to_be_visible()
    old_fields = form.locator("input[name=name]").element_handle()
    with page.expect_response(lambda r: r.request.method == "POST"
                              and r.url.split("?")[0].endswith("/tickets/new/requester/")):
        form.locator("input[name=email]").fill(helpers_sd.requester_email("call"))
        form.locator("input[name=email]").press("Tab")
    page.wait_for_function("el => !el.isConnected", arg=old_fields)
    form.locator("input[name=name]").fill(f"Кузнецов-{word} Павел")
    old_queue = form.locator("select[name=queue]").element_handle()
    with page.expect_response(lambda r: r.request.method == "GET" and "/tickets/new/queue/" in r.url):
        form.locator("select[name=category]").select_option(value=str(category_id))
    page.wait_for_function("el => !el.isConnected", arg=old_queue)
    expect(form.locator("select[name=queue]")).to_have_value(str(queue_id))
    take = form.locator("input[name=take]")
    expect(take).to_be_enabled()
    take.set_checked(False)
    form.locator("select[name=source]").select_option(label="Телефон")
    form.locator("input[name=subject]").fill(subject)
    form.locator("textarea[name=text]").fill(f"Позвонили по телефону {word}")
    form.locator("button[type=submit]").click()
    page.wait_for_url(REF_RE)
    return word, subject


def _pick_category(card, name: str) -> None:
    """Выбирает категорию по названию в форме `ticket-category` карточки и отправляет её (категория той же очереди:
    подтверждение смены очереди не нужно, CONTRACT-003, 12)."""
    form = card.locator('form[data-form="ticket-category"]')
    select = form.locator("select[name=category]")
    option = select.locator("option").filter(has_text=name)
    expect(option).to_have_count(1)
    select.select_option(option.get_attribute("value"))
    form.locator("button[type=submit]").first.click()


def _change_category(page, number: int, category_name: str) -> None:
    """Сотрудник `page` меняет категорию заявки на `category_name` (очередь та же) и ждёт новую категорию в карточке."""
    card = helpers_sd.open_ticket(page, number)
    _pick_category(card, category_name)
    expect(_card(page, number).locator('[data-field="category"]')).to_contain_text(category_name)


def _make_role(page, name: str, codes) -> str:
    """Своя роль с правами `codes` (`/roles/new/`); возвращает её номер."""
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
    """Личная роль из формы карточки сотрудника (срез 001)."""
    page.goto(f"/staff/{user_id}/")
    form = page.locator('form[action$="/roles/"]')
    form.locator(f'input[name=roles][value="{role_id}"]').check()
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()


def _tree(page, tag: str, head, holder, workers) -> tuple:
    """Вложенная очередь: отдел-родитель с руководителем `head` (участник отдела, не команды), команда-очередь с
    прямыми участниками `workers`, держатель права «Все заявки» `holder` (не участник): `(номер команды, название)`.
    Руководитель вышестоящего узла и держатель «Все заявки» заявку видят, но уведомлений о ней не получают (4.3)."""
    dept_id = helpers_org.create_unit(page, helpers_org.unique_name("Сопровождение"))
    team_id, team_name = _queue(page, "Поддержка", kind="team", parent_id=dept_id)
    _members(page, dept_id, [head], tag)
    helpers_org.set_marks(page, dept_id, "heads", [head.id])
    _members(page, team_id, workers, tag)
    role_id = _make_role(page, helpers_org.unique_name("Диспетчер"), [SD_ALL])
    _grant_role(page, holder.id, role_id)
    return team_id, team_name


def _sees(account, number: int, word: str) -> None:
    """Заявка видна сотруднику в списке «Без ответственного» и в списке «Все» (по слову темы)."""
    for preset in ("unassigned", "all"):
        account.page.goto("/tickets/?" + urllib.parse.urlencode({"preset": preset, "q": word}))
        expect(account.page.locator(f'#tickets-grid tr[data-ticket="{number}"]')).to_have_count(1)


def _reopened_without_assignee(page, queue_id, former, number: int) -> None:
    """Подготовка закрытой заявки без прежнего ответственного: назначить `former` (администратор), закрыть с решением
    и убрать `former` из очереди (так же, как CONTRACT-003, сценарий 5: у открытой заново заявки ответственного нет)."""
    _assign(page, number, former)
    _close(page, number, f"Решено {secrets.token_hex(3)}")
    _remove(page, queue_id, former)


# --- Тесты --------------------------------------------------------------------------------------------------

def test_e02_assignment_by_other_employee_gives_new_assignee_assigned_notification_with_number_and_subject(
        admin_page, employee, new_context):
    """Сценарий 2, п. 1: другой участник очереди назначил участника ответственным — новый ответственный получает
    «Вам назначена заявка #N: Тема» (живое обновление колокольчика и строка непрочитанная); не назначавший и не
    назначенный участник «Вам назначена» не получают (FR-310, FR-315)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    actor, assignee, colleague = (_staff(employee, tag, i) for i in (1, 2, 3))
    queue_id, queue_name = _queue(page)
    _members(page, queue_id, [actor, assignee, colleague], tag)
    with _default_queue(page, old_id, queue_id):
        # дано: у будущего ответственного открыта вкладка, соединение готово (решение E21)
        tab = helpers_notify.open_watcher(new_context, assignee)
        before = helpers_notify.bell_count(tab)
        number, word, subject, _sender = _new_ticket(page)
        before = _wait_plus(tab, before)  # «Новая заявка в моей очереди» от письма
        for account in (actor, assignee, colleague):
            assert _wait_kind(account.page, word, NEW_PREFIX, 1) == [_norm(_text_new(number, queue_name, subject))]
        # когда: другой участник очереди (не администратор) назначает ответственного через карточку
        _assign(actor.page, number, assignee)
        # п. 1: число колокольчика выросло ещё на 1, в списке — «Вам назначена заявка #N: Тема», непрочитанная
        _wait_plus(tab, before)
        assert _wait_kind(assignee.page, word, ASSIGNED_PREFIX, 1) == [_norm(_text_assigned(number, subject))]
        expect(_kind_rows(assignee.page, word, ASSIGNED_PREFIX)).to_have_attribute("data-unread", "1")
        # контроль принадлежит уже полученному: назначенный получил, остальные участники — нет
        _no_kind(actor.page, word, ASSIGNED_PREFIX, "назначавший")
        _no_kind(colleague.page, word, ASSIGNED_PREFIX, "другой участник очереди")


def test_e02_default_assignee_on_create_or_category_change_gets_assigned_unless_he_is_the_actor(
        admin_page, employee):
    """Сценарий 2, п. 2: у категории ответственный по умолчанию — при создании заявки по звонку и при смене категории
    он получает «Вам назначена заявка #N: Тема», если действие совершил не он сам; когда создал заявку или сменил
    категорию он сам, уведомления нет (FR-310, FR-315)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    default_man, actor, observer = (_staff(employee, tag, i) for i in (1, 2, 3))
    queue_id, queue_name = _queue(page)
    _members(page, queue_id, [default_man, actor, observer], tag)
    category_id, category_name = _category(page, queue_id, default_assignee=default_man.id)
    with _default_queue(page, old_id, queue_id):
        # п. 2 (сам): ответственный по умолчанию сам создал заявку по звонку — «Вам назначена» ему нет
        word_self_create, _subject = _phone_ticket(default_man.page, category_id, queue_id)
        number_self_create = int(REF_RE.search(default_man.page.url).group(1))
        expect(helpers_sd.open_ticket(page, number_self_create).locator('[data-field="assignee"]')) \
            .to_contain_text(default_man.full_name.split()[0])
        # п. 2 (сам): письмо создало заявку без категории, ответственный по умолчанию сам сменил категорию
        number_self, word_self, subject_self, _s = _new_ticket(page)
        _change_category(default_man.page, number_self, category_name)
        expect(helpers_sd.open_ticket(page, number_self).locator('[data-field="assignee"]')) \
            .to_contain_text(default_man.full_name.split()[0])
        # п. 2 (создание): другой участник создал заявку по звонку — ответственный по умолчанию получил
        word_create, subject_create = _phone_ticket(actor.page, category_id, queue_id)
        number_create = int(REF_RE.search(actor.page.url).group(1))
        texts = _wait_kind(default_man.page, word_create, ASSIGNED_PREFIX, 1)
        assert texts == [_norm(_text_assigned(number_create, subject_create))], texts
        # п. 2 (смена категории): другой участник сменил категорию заявки — ответственный по умолчанию получил
        number_change, word_change, subject_change, _s2 = _new_ticket(page)
        _change_category(actor.page, number_change, category_name)
        texts = _wait_kind(default_man.page, word_change, ASSIGNED_PREFIX, 1)
        assert texts == [_norm(_text_assigned(number_change, subject_change))], texts
        # контроль получен: теперь отрицательные случаи — у ответственного по умолчанию ничего про заявки, где действовал он
        assert not _rows(default_man.page, word_self_create).count(), "заявка по звонку, созданная им самим"
        _no_kind(default_man.page, word_self, ASSIGNED_PREFIX, "ответственный по умолчанию (сменил категорию сам)")
        # письмо без категории дало «Новая заявка» всем трём участникам: у каждого одна строка с текстом вида
        for account in (default_man, actor, observer):
            texts = _wait_kind(account.page, word_self, NEW_PREFIX, 1)
            assert texts == [_norm(_text_new(number_self, queue_name, subject_self))], texts
        # остальные участники «Вам назначена» не получают ни по одной из четырёх заявок (ответственный — не они)
        for account in (actor, observer):
            for word in (word_self_create, word_self, word_create, word_change):
                _no_kind(account.page, word, ASSIGNED_PREFIX, "участник очереди, не ответственный")
        # заявки по звонку уже с ответственным: «Новая заявка» по ним не пришла никому
        for account in (default_man, actor, observer):
            for word in (word_self_create, word_create):
                _no_kind(account.page, word, NEW_PREFIX, "участник очереди (у заявки есть ответственный)")


def test_e02_take_to_self_gives_no_assigned_notification(admin_page, employee):
    """Сценарий 2, п. 3: исполнитель нажал «Взять себе» — стал ответственным, уведомления «Вам назначена заявка» ему нет;
    контроль — назначение другой заявки ему администратором даёт уведомление (FR-310, FR-315)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    taker, colleague = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, queue_name = _queue(page)
    _members(page, queue_id, [taker, colleague], tag)
    with _default_queue(page, old_id, queue_id):
        number_taken, word_taken, subject_taken, _s = _new_ticket(page, title="Взятая")
        number_given, word_given, subject_given, _s2 = _new_ticket(page, title="Назначенная")
        for word in (word_taken, word_given):
            for account in (taker, colleague):
                _wait_kind(account.page, word, NEW_PREFIX, 1)
        # когда: исполнитель берёт заявку себе
        _take(taker.page, number_taken)
        expect(helpers_sd.open_ticket(taker.page, number_taken).locator('[data-field="assignee"]')) \
            .to_have_attribute("data-empty", "false")
        # контроль: администратор назначает ему другую заявку — «Вам назначена» приходит
        _assign(page, number_given, taker)
        texts = _wait_kind(taker.page, word_given, ASSIGNED_PREFIX, 1)
        assert texts == [_norm(_text_assigned(number_given, subject_given))], texts
        # п. 3: по взятой себе заявке «Вам назначена» нет; в списке только «Новая заявка» от письма
        _no_kind(taker.page, word_taken, ASSIGNED_PREFIX, "взявший заявку себе")
        assert _kind_texts(taker.page, word_taken, NEW_PREFIX) == [_norm(_text_new(number_taken, queue_name,
                                                                                    subject_taken))]
        expect(_rows(taker.page, word_taken)).to_have_count(1)
        # другой участник очереди «Вам назначена» не получал ни по одной заявке
        for word in (word_taken, word_given):
            _no_kind(colleague.page, word, ASSIGNED_PREFIX, "другой участник очереди")


def test_e02_bulk_assign_five_tickets_gives_five_separate_assigned_notifications(admin_page, employee):
    """Сценарий 2, п. 4: групповое действие «Назначить ответственного» на 5 заявок — назначенный получает пять отдельных
    уведомлений «Вам назначена заявка #N: Тема» (пять разных номеров, по записи на заявку, без группировки); выполнивший
    действие сотрудник «Вам назначена» не получает (FR-306, FR-310, FR-315)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    actor, candidate = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, _queue_name = _queue(page)
    _members(page, queue_id, [actor, candidate], tag)
    group = _word()
    with _default_queue(page, old_id, queue_id):
        tickets = [_new_ticket(page, title="Заявка", group=group) for _ in range(5)]
        numbers = [t[0] for t in tickets]
        expected = {n: _norm(_text_assigned(n, subject)) for n, _w, subject, _s in tickets}
        assert len(set(numbers)) == 5
        # дано: пять заявок без ответственного, кандидат получил пять «Новая заявка» (контроль, что он участник)
        assert len(_wait_kind(candidate.page, group, NEW_PREFIX, 5)) == 5
        # когда: исполнитель отмечает пять заявок и выбирает «Назначить ответственного» (CONTRACT-003, 13.2)
        page_actor = actor.page
        page_actor.goto("/tickets/?" + urllib.parse.urlencode({"preset": "all", "q": group}))
        expect(page_actor.locator("#tickets-grid tr[data-ticket]")).to_have_count(5)
        for number in numbers:
            page_actor.locator(f'#tickets-grid tr[data-ticket="{number}"] [data-cell="select"] '
                               f'input[name=numbers]').check()
        bulk = page_actor.locator("form#tickets-bulk")
        bulk.locator("select[name=action]").select_option("assign")
        option = bulk.locator('[data-bulk-action="assign"] select[name=user] option').filter(has_text=f"{tag}2")
        expect(option).to_have_count(1)
        bulk.locator('[data-bulk-action="assign"] select[name=user]').select_option(option.get_attribute("value"))
        bulk.locator("button[type=submit]").click()
        expect(page_actor.locator("[data-bulk-result]")).to_contain_text("Выполнено: 5")
        # п. 4: пять отдельных строк «Вам назначена заявка #N: Тема» — пять разных номеров, каждая со своей темой
        texts = _wait_kind(candidate.page, group, ASSIGNED_PREFIX, 5)
        assert sorted(texts) == sorted(expected.values()), texts
        rows = _kind_rows(candidate.page, group, ASSIGNED_PREFIX)
        expect(rows).to_have_count(5)
        ids = [row.get_attribute("data-notification") for row in rows.all()]
        assert len(set(ids)) == 5, ids
        assert {int(re.search(r"#(\d+)", t).group(1)) for t in texts} == set(numbers)
        # исполнитель, назначивший заявки, «Вам назначена» не получил
        _no_kind(actor.page, group, ASSIGNED_PREFIX, "выполнивший групповое действие")


def test_e02_requester_or_cc_participant_mail_to_ticket_with_assignee_gives_requester_replied_notification(
        admin_page, employee):
    """Сценарий 2, п. 5: в заявку с ответственным пришло письмо заявителя, а затем письмо участника из копии — каждое
    дописано в ленту, ответственный получает «Заявитель ответил в заявке #N: Тема» за каждое; другой участник очереди
    такого уведомления не получает (FR-311)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    assignee, colleague = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, _queue_name = _queue(page)
    _members(page, queue_id, [assignee, colleague], tag)
    participant = helpers_sd.requester_email("cc")
    with _default_queue(page, old_id, queue_id):
        number, word, subject, sender = _new_ticket(page, cc=[participant])
        _assign(page, number, assignee)
        # когда: пишет заявитель, затем участник из копии (оба письма с номером в теме)
        _mail_in(sender, number, subject, f"Не помогло {secrets.token_hex(3)}")
        _mail_in(participant, number, subject, f"Добавлю от коллеги {secrets.token_hex(3)}")
        # письма дописаны в ленту той же заявки: первое письмо и два ответа, один из них от участника
        card = helpers_sd.open_ticket(page, number)
        expect(_incoming(card)).to_have_count(3)
        expect(_incoming(card).locator('[data-author-kind="participant"]')).to_have_count(1)
        # п. 5: два уведомления «Заявитель ответил в заявке #N: Тема» с темой заявки, а не темой письма
        texts = _wait_kind(assignee.page, word, REPLIED_PREFIX, 2)
        assert texts == [_norm(_text_replied(number, subject))] * 2, texts
        # п. 5: другой участник очереди такого уведомления не получил (контроль — ответственный получил)
        _no_kind(colleague.page, word, REPLIED_PREFIX, "другой участник очереди")


def test_e02_mail_reopening_closed_ticket_with_assignee_gives_him_requester_replied_notification(
        admin_page, employee):
    """Сценарий 2, п. 6: письмо заявителя открыло закрытую заявку заново, у неё есть ответственный — он получает
    «Заявитель ответил в заявке #N: Тема»; «Новая заявка» при открытии никому не приходит, потому что ответственный
    остался (FR-309, FR-311)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    assignee, colleague = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, queue_name = _queue(page)
    _members(page, queue_id, [assignee, colleague], tag)
    with _default_queue(page, old_id, queue_id):
        number, word, subject, sender = _new_ticket(page)
        _assign(page, number, assignee)
        _close(page, number, f"Решено {word}")
        # когда: письмо заявителя в срок открытия заново (заявка закрыта только что)
        _mail_in(sender, number, subject, f"Проблема вернулась {secrets.token_hex(3)}")
        card = helpers_sd.open_ticket(page, number)
        expect(card).to_have_attribute("data-kind", "in_progress")
        expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "false")
        # п. 6: ответственный получил «Заявитель ответил в заявке #N: Тема»
        texts = _wait_kind(assignee.page, word, REPLIED_PREFIX, 1)
        assert texts == [_norm(_text_replied(number, subject))], texts
        # п. 6: «Новая заявка» при открытии не пришла: у каждого участника та, что от создания заявки, одна
        expected_new = [_norm(_text_new(number, queue_name, subject))]
        assert _kind_texts(assignee.page, word, NEW_PREFIX) == expected_new
        assert _kind_texts(colleague.page, word, NEW_PREFIX) == expected_new
        # другой участник очереди «Заявитель ответил» не получил
        _no_kind(colleague.page, word, REPLIED_PREFIX, "другой участник очереди")


def test_e02_mail_reopening_closed_ticket_without_assignee_notifies_direct_queue_members_not_parent_head_or_all_tickets_holder(
        admin_page, employee):
    """Сценарий 2, п. 7: письмо открыло закрытую заявку заново, прежнего ответственного уже нет — прямые участники
    узла-очереди получают «Новая заявка #N в очереди «Очередь»: Тема»; руководитель вышестоящего узла и держатель права
    «Все заявки» уведомления не получают, но заявку видят; «Заявитель ответил» не приходит никому, а убранный из
    очереди прежний ответственный новой «Новая заявка» не получает (FR-309; ADR-0011, п. 10)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    worker_a, worker_b, former, head, holder = (_staff(employee, tag, i) for i in range(1, 6))
    team_id, team_name = _tree(page, tag, head, holder, [worker_a, worker_b, former])
    with _default_queue(page, old_id, team_id):
        number, word, subject, sender = _new_ticket(page)
        expected_new = _norm(_text_new(number, team_name, subject))
        for account in (worker_a, worker_b, former):  # дано: «Новая заявка» от создания у прямых участников
            assert _wait_kind(account.page, word, NEW_PREFIX, 1) == [expected_new]
        # дано: заявка закрыта, прежнего ответственного в очереди больше нет
        _reopened_without_assignee(page, team_id, former, number)
        # когда: письмо заявителя в срок открытия заново
        _mail_in(sender, number, subject, f"Проблема вернулась {secrets.token_hex(3)}")
        card = helpers_sd.open_ticket(page, number)
        expect(card).to_have_attribute("data-kind", "in_progress")
        expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "true")
        # п. 7: прямые участники очереди получили второе «Новая заявка #N в очереди «Очередь»: Тема»
        for account in (worker_a, worker_b):
            assert _wait_kind(account.page, word, NEW_PREFIX, 2) == [expected_new] * 2
        # контроль получен: бывший ответственный (уже не участник), руководитель вышестоящего узла и держатель «Все
        # заявки» нового уведомления не получили
        assert _kind_texts(former.page, word, NEW_PREFIX) == [expected_new]
        for who, account in (("руководитель вышестоящего узла", head), ("держатель «Все заявки»", holder)):
            expect(_rows(account.page, word)).to_have_count(0)
            _no_kind(account.page, word, NEW_PREFIX, who)
        # п. 7: ответственного нет — «Заявитель ответил» не приходит никому
        for account in (worker_a, worker_b, former, head, holder):
            _no_kind(account.page, word, REPLIED_PREFIX, "заявка без ответственного")
        # п. 7: заявку руководитель и держатель «Все заявки» видят
        for account in (head, holder):
            _sees(account, number, word)


def test_e02_requester_mail_to_unassigned_ticket_gives_no_requester_replied_notification(admin_page, employee):
    """Сценарий 2, п. 8: в заявку без ответственного пришло письмо заявителя — письмо дописано, уведомления «Заявитель
    ответил» нет (заявка и так в «Без ответственного»); контроль — то же письмо в заявку с ответственным даёт такое
    уведомление (FR-311)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    assignee, colleague = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, queue_name = _queue(page)
    _members(page, queue_id, [assignee, colleague], tag)
    with _default_queue(page, old_id, queue_id):
        number_free, word_free, subject_free, sender_free = _new_ticket(page, title="Свободная")
        number_owned, word_owned, subject_owned, sender_owned = _new_ticket(page, title="Назначенная")
        _assign(page, number_owned, assignee)
        # когда: заявитель пишет в обе заявки — сначала в заявку без ответственного, потом в заявку с ним
        _mail_in(sender_free, number_free, subject_free, f"Есть новости {secrets.token_hex(3)}")
        _mail_in(sender_owned, number_owned, subject_owned, f"Есть новости {secrets.token_hex(3)}")
        # письмо дописано и в заявку без ответственного: в ленте первое письмо и ответ, заявка одна
        card = helpers_sd.open_ticket(page, number_free)
        expect(_incoming(card)).to_have_count(2)
        expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "true")
        # контроль: ответственный заявки number_owned получил «Заявитель ответил» (то же событие, другой случай)
        texts = _wait_kind(assignee.page, word_owned, REPLIED_PREFIX, 1)
        assert texts == [_norm(_text_replied(number_owned, subject_owned))], texts
        # п. 8: по заявке без ответственного «Заявитель ответил» нет ни у кого; «Новая заявка» от создания осталась одна
        expected_new = [_norm(_text_new(number_free, queue_name, subject_free))]
        for who, account in (("участник очереди", assignee), ("другой участник очереди", colleague)):
            _no_kind(account.page, word_free, REPLIED_PREFIX, who)
            assert _kind_texts(account.page, word_free, NEW_PREFIX) == expected_new
        # другой участник очереди не получил «Заявитель ответил» и по заявке с ответственным
        _no_kind(colleague.page, word_owned, REPLIED_PREFIX, "другой участник очереди")


def test_e02_assignee_own_reply_gives_himself_no_notification(admin_page, employee):
    """Сценарий 2, п. 9: ответственный сам пишет ответ в своей заявке — себе он уведомления не получает; контроль — новое
    письмо заявителя после ответа даёт ровно второе «Заявитель ответил», а не третье (FR-311, FR-315)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    assignee, colleague = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, _queue_name = _queue(page)
    _members(page, queue_id, [assignee, colleague], tag)
    with _default_queue(page, old_id, queue_id):
        number, word, subject, sender = _new_ticket(page)
        _assign(page, number, assignee)
        _mail_in(sender, number, subject, f"Первое сообщение {secrets.token_hex(3)}")
        expected = _norm(_text_replied(number, subject))
        assert _wait_kind(assignee.page, word, REPLIED_PREFIX, 1) == [expected]
        # когда: ответственный отвечает заявителю из карточки своей заявки
        _reply(assignee.page, number, f"Проверьте кабель {secrets.token_hex(3)}")
        # контроль: заявитель отвечает ещё раз — это второе уведомление; от собственного ответа третьего нет
        _mail_in(sender, number, subject, f"Второе сообщение {secrets.token_hex(3)}")
        texts = _wait_kind(assignee.page, word, REPLIED_PREFIX, 2)
        assert texts == [expected] * 2, texts
        # п. 9: других уведомлений вида «Заявитель ответил» у него нет, у другого участника очереди их нет вовсе
        _no_kind(colleague.page, word, REPLIED_PREFIX, "другой участник очереди")


def test_e02_manual_reopen_without_assignee_notifies_direct_queue_members_except_the_one_who_reopened(
        admin_page, employee):
    """Сценарий 2, п. 10: сотрудник вручную открыл закрытую заявку заново, и она осталась без ответственного — прямые
    участники узла-очереди, кроме того, кто её открыл, получают «Новая заявка #N в очереди «Очередь»: Тема»;
    руководитель вышестоящего узла и держатель права «Все заявки» не получают, но заявку видят (FR-309, FR-315)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    opener, member, former, head, holder = (_staff(employee, tag, i) for i in range(1, 6))
    team_id, team_name = _tree(page, tag, head, holder, [opener, member, former])
    with _default_queue(page, old_id, team_id):
        number, word, subject, _sender = _new_ticket(page)
        expected_new = _norm(_text_new(number, team_name, subject))
        for account in (opener, member, former):  # дано: «Новая заявка» от создания у прямых участников
            assert _wait_kind(account.page, word, NEW_PREFIX, 1) == [expected_new]
        # дано: заявка закрыта, прежнего ответственного в очереди больше нет
        _reopened_without_assignee(page, team_id, former, number)
        # когда: участник очереди открывает закрытую заявку вручную
        _reopen_manual(opener.page, number)
        expect(helpers_sd.open_ticket(page, number).locator('[data-field="assignee"]')).to_have_attribute(
            "data-empty", "true")
        # п. 10: другой прямой участник получил второе «Новая заявка» (контроль)
        assert _wait_kind(member.page, word, NEW_PREFIX, 2) == [expected_new] * 2
        # п. 10: открывший заявку нового уведомления не получил: осталось то, что пришло при создании
        assert _kind_texts(opener.page, word, NEW_PREFIX) == [expected_new]
        # бывший ответственный (уже не участник), руководитель вышестоящего узла и держатель «Все заявки» — тоже нет
        assert _kind_texts(former.page, word, NEW_PREFIX) == [expected_new]
        for who, account in (("руководитель вышестоящего узла", head), ("держатель «Все заявки»", holder)):
            expect(_rows(account.page, word)).to_have_count(0)
            _no_kind(account.page, word, NEW_PREFIX, who)
        # ответственного нет — «Заявитель ответил» никому не приходит
        for account in (opener, member, former, head, holder):
            _no_kind(account.page, word, REPLIED_PREFIX, "заявка без ответственного")
        # заявку руководитель и держатель «Все заявки» видят
        for account in (head, holder):
            _sees(account, number, word)
