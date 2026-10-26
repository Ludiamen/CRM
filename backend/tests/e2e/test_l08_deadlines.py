"""T-6147: сценарий 8 — сроки и напоминания: поле-срок с порогами, ночное задание (через `e2e_lists_shift`), получатели,
ссылки, «Мои уведомления», письмо и Telegram, отбор «Истекает» (FR-509, FR-520, FR-523, FR-525, FR-529, FR-530, FR-531,
NFR-511).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-006.md разделы 7, 10–13, 15.3–15.4):
- управляющий — администратор круга `admin_page` (в наборе «Правят» и в полях записей его нет); читающие и правящие —
  `helpers_lists.make_list_reader` / `make_list_editor`; сотрудник без права на списки — сотрудник с новой ролью без прав;
- время на стенде не подменяется. Единственный рычаг — `helpers_lists.shift(N)`: значения полей-сроков всех записей
  стенда и отметки `ReminderSent` сдвигаются на N дней назад, затем в той же команде отрабатывает обход (решения 19, 56).
  Запись заводится со сроком «сегодня по Москве + K»; после `shift(N)` в базе срок «сегодня + K − N», до срока осталось
  K − N дней, а в тексте уведомления стоит именно эта (сдвинутая) дата. «Сегодня по Москве» считается на хосте по
  смещению +03:00 (в Москве нет перехода на летнее время);
- `shift()["notified"]` не проверяется: он считает уведомления по всем записям стенда, в том числе по записям прежних
  тестов этого файла, которые при сдвигах тоже доходят до своих порогов. Все утверждения — по строкам `/notifications/`
  с уникальным названием своей записи; везде, где проверяется отсутствие, в том же тесте есть положительный контроль;
- обход в команде синхронный: уведомления на портале есть сразу после возврата `shift`, опрос списка — запас;
- письма (тесты 9 и 16): у получателя «Без тихих часов» до события, после события — `helpers_notify.tick(shift=121)`
  (срок письма), письмо ищется по адресу получателя; внешний канал — только Telegram учебной службы `fakebots`, включается
  администратором на время блока `channels_on` и возвращается;
- пункты сценария 8, которые приёмка не проходит (решение 19): п. 5 «дважды за день» — серверный T-6115, здесь повтор
  обхода внутри окна уже отработанного порога (`shift(1)`); п. 13 (расписание 08:00) — T-6125; внешние каналы MAX и Web
  Push — серверный T-6116;
- общих настроек тесты не меняют (канал Telegram возвращает `channels_on`); сброса стенда в файле нет.
"""
import json
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_lists, helpers_notify, helpers_org
from tests.e2e.helpers_lists import (
    add_field, archive_record, create_list, field_code_by_name, field_codes, field_form, make_list_editor,
    make_list_reader, make_list_role, open_add_record, open_edit_record, open_field, open_new_field, pick,
    refusal_codes, shift, status_of, submit_field_form, submit_record, unique_list_name)

KIND = "lists.deadline"
KIND_TITLE = "Срок в записи списка"
MODULE = "Списки"
EXPIRING = "Истекает срок"
REACHED = "Срок наступил"
EXTERNAL_EXPIRING = "Истекает срок в записи списка"  # 7.1: внешний текст вида (без названий)
THRESHOLDS_BAD = "Порог — целое число от 1 до 365, не больше трёх порогов, без повторов"  # 12.3
FIELD_OWNER = "Ответственный"
FIELD_DUE = "Действует до"
FIELD_WARRANTY = "Гарантия до"
PAST_ANY_TERM = 121     # минут: больше верхней границы срока письма (120 минут)
LIST_WAIT_S = 15.0      # предел опроса списка уведомлений
SETTLE_MS = 1500        # пауза «не придёт ли лишнее»: только там, где доказывается отсутствие нового
MOSCOW = timezone(timedelta(hours=3))


# --- Общие помощники файла ------------------------------------------------------------------------------------

def _today() -> date:
    """Сегодня по Москве (служба берёт `moscow_today()`; хостовая дата могла бы отличаться в первые часы суток)."""
    return datetime.now(MOSCOW).date()


def _fmt(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def _chat_id() -> int:
    """Уникальный номер чата `fakebots` для теста."""
    return secrets.randbelow(900_000_000) + 100_000_000


def _name(prefix: str) -> str:
    """Уникальное ФИО: первое слово (фамилия с уникальной частью) годится для подсказки выбора."""
    return f"{prefix}{secrets.token_hex(3)} Пётр Петрович"


def _surname(account) -> str:
    return account.full_name.split()[0]


def _text(prefix: str, list_name: str, title: str, field: str, due: date) -> str:
    """Текст уведомления на портале (7.2): «<Истекает срок|Срок наступил>: <список> — <название>: <поле> <дата>»."""
    return f"{prefix}: {list_name} — {title}: {field} {_fmt(due)}"


def _deadline_list(page, *, thresholds=(30, 7), owner_multiple: bool = True) -> tuple:
    """Новый список с полями «Ответственный» (сотрудник) и «Действует до» (дата, срок с порогами). Возвращает
    `(номер списка, название, код «Ответственного», код «Действует до»)`."""
    name = unique_list_name("Лицензии")
    list_id = create_list(page, name)
    owner = add_field(page, list_id, FIELD_OWNER, "person", multiple=owner_multiple)
    due = add_field(page, list_id, FIELD_DUE, "date", deadline=True, thresholds=list(thresholds))
    return list_id, name, owner, due


def _new_record(page, list_id, owner_code, dues: dict, title: str, owners=()) -> int:
    """Запись формой: «Название», даты по кодам полей (`dues` — код → дата), сотрудники подсказкой по фамилии."""
    open_add_record(page, list_id)
    helpers_lists.fill_record(page, {"title": title, **{code: _fmt(day) for code, day in dues.items()}})
    for query in owners:
        pick(page, owner_code, query)
    number = submit_record(page)
    assert number, f"запись «{title}» не создана: {refusal_codes(page)}"
    return number


def _rows(page, title: str):
    """Строки списка `/notifications/`, в тексте которых есть название записи (страница только читается)."""
    page.goto("/notifications/")
    expect(page.locator("[data-notify-list]")).to_be_visible()
    return page.locator("ul[data-notifications] li[data-notification]").filter(has_text=title)


def _texts_of(rows) -> list:
    return [" ".join(row.locator('[data-field="text"]').inner_text().split()) for row in rows.all()]


def _wait_rows(page, title: str, count: int, settle: bool = False):
    """Ждёт (до `LIST_WAIT_S` с, опросом с перезагрузкой), что строк по названию не меньше `count`; затем проверяет, что
    их ровно `count`. С `settle=True` перед последней проверкой ждёт `SETTLE_MS` (проверки «нового нет»)."""
    rows = _rows(page, title)
    for _ in range(int(LIST_WAIT_S * 2)):
        if rows.count() >= count:
            break
        page.wait_for_timeout(500)
        rows = _rows(page, title)
    assert rows.count() >= count, f"уведомлений по «{title}»: {rows.count()}, ждали {count}"
    if settle:
        page.wait_for_timeout(SETTLE_MS)
    rows = _rows(page, title)
    assert rows.count() == count, f"уведомлений по «{title}»: {rows.count()}, ждали ровно {count}"
    return rows


def _no_rows(page, title: str) -> None:
    """Уведомлений по названию нет (звать после положительного контроля того же события у другого получателя)."""
    expect(_rows(page, title)).to_have_count(0)


def _open_target(page, row) -> tuple:
    """Куда ведёт уведомление: прямой GET адреса открытия `a[data-open]` без перехода по редиректу; возвращает
    `(путь, фрагмент)` из заголовка `Location`."""
    href = row.locator('[data-field="text"] a[data-open]').get_attribute("href")
    response = helpers_org.direct_get(page, href)
    assert response.status == 302, f"адрес открытия {href} ответил {response.status}"
    parts = urlsplit(response.headers.get("location", ""))
    return parts.path, parts.fragment


def _cell(page, kind: str, channel: str):
    """Флажок ячейки таблицы `/me/notifications/`."""
    return page.locator(f'table[data-notify-table] tr[data-notify-kind="{kind}"] td[data-channel="{channel}"] '
                        f'input[type=checkbox][name="cell"][value="{kind}:{channel}"]')


def _save_prefs(page, *, cells=None, quiet: str | None = None) -> None:
    """«Мои уведомления»: ставит ячейки `{(вид, канал): состояние}` и режим тихих часов, сохраняет; успех — переход на
    `/me/notifications/` без отказов."""
    page.goto("/me/notifications/")
    form = page.locator('form[data-form="notify-prefs"]')
    expect(form).to_be_visible()
    for (kind, channel), state in (cells or {}).items():
        _cell(page, kind, channel).set_checked(state)
    if quiet is not None:
        form.locator(f'fieldset[data-quiet] input[type=radio][name="quiet_mode"][value="{quiet}"]').check()
    with page.expect_navigation():
        form.locator('button[type=submit][data-action="save-prefs"]').click()
    page.wait_for_load_state()
    assert not helpers.alert_text(page), f"настройки не сохранены: {helpers.alert_text(page)}"


def _dismiss(admin_page, user_id) -> None:
    """Увольняет из карточки: диалог → подтверждение; ждёт отметку `[data-dismissed-badge]`."""
    admin_page.goto(f"/staff/{user_id}/")
    card = admin_page.locator(f'[data-card][data-user-id="{user_id}"]')
    card.locator('[data-action="dismiss"]').click()
    dialog = admin_page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(card.locator("[data-dismissed-badge]")).to_be_visible()


def _field_row(page, code):
    return page.locator(f'[data-lists-fields-grid] tr[data-field-code="{code}"]')


def _threshold_boxes(form):
    return form.locator('[data-prop="thresholds"] input[name="thresholds"]')


def _lift_number_limits(form) -> None:
    """Снимает с входов порогов `min`, `max`, `step` (если входы числовые, браузер не отправил бы 0 и 366: проверку
    делает сервер, как при отправке формы обходом браузера)."""
    form.evaluate("el => el.querySelectorAll('[data-prop=\"thresholds\"] input').forEach(i => "
                  "['min', 'max', 'step'].forEach(a => i.removeAttribute(a)))")


def _saved_thresholds(form) -> list:
    return sorted(int(v) for v in _threshold_boxes(form).evaluate_all("els => els.map(e => e.value)") if v.strip())


def _item_mail_with(mailpit, to: str, needle: str, *, seen=(), timeout: float = 60.0) -> dict:
    """Новое письмо `notify.item` на `to`, в тексте которого (с пробелами, сжатыми до одного) есть `needle`: другие
    новые письма того же шаблона (например, иные уведомления этого получателя, выпущенные тем же `tick`) пропускаются.
    Ожидание — помощником `helpers_lists.item_mail` (не пришло за `timeout` — `AssertionError`)."""
    skipped = set(seen)
    while True:
        mail = helpers_lists.item_mail(mailpit, to, seen=skipped, timeout=timeout)
        if needle in " ".join(mail["Text"].split()):
            return mail
        skipped.add(mail["ID"])


def _grid_numbers(page, list_id, preset: str) -> list:
    """Номера записей в таблице списка с отбором `preset` (по адресу; ссылка отбора обязана быть на странице)."""
    page.goto(f"/lists/{list_id}/?preset={preset}")
    link = page.locator(f'[data-lists-presets] a[data-preset="{preset}"]')
    expect(link).to_have_count(1)
    expect(link).to_have_attribute("aria-current", "page")
    expect(page.locator("#lists-grid")).to_be_visible()
    return sorted(int(tr.get_attribute("data-record-number")) for tr in page.locator("#lists-grid tr[data-record-number]").all())


# --- Тесты: поле-срок -----------------------------------------------------------------------------------------

def test_l08_deadline_switch_on_date_field_offers_30_and_7_by_default_and_saves_thresholds(admin_page):
    """Сценарий 8, п. 1: у поля типа «дата» администратор включает «Срок» — по умолчанию предлагаются пороги 30 и 7;
    он вводит «30, 7» — пороги сохранены и видны после перезагрузки; их можно заменить (FR-529)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Лицензии"))
    form = open_new_field(page, list_id, "date")
    # п. 1: включение «Срока» — предложены пороги 30 и 7 значениями входов, не подсказкой (15.5 п. 8): первые два
    # входа — «30» и «7», третий пуст
    form.locator('[data-prop="deadline"] input[name="deadline"]').check()
    expect(_threshold_boxes(form).first).to_be_visible()
    expect(_threshold_boxes(form)).to_have_count(3)
    offered = _threshold_boxes(form).evaluate_all("els => els.map(e => e.value.trim())")
    assert offered == ["30", "7", ""], f"предложены пороги (значения входов): {offered}"
    # п. 1: вводит «30, 7» — поле сохранено
    helpers_lists.fill_field_form(page, thresholds=[30, 7], name=FIELD_DUE)
    assert submit_field_form(page, list_id), f"поле не сохранено: {refusal_codes(page)}"
    code = field_code_by_name(page, list_id, FIELD_DUE, navigate=False)
    # п. 1: пороги сохранены (после перезагрузки формы поля)
    form = open_field(page, list_id, code)
    expect(form.locator('[data-prop="deadline"] input[name="deadline"]')).to_be_checked()
    assert _saved_thresholds(form) == [7, 30], "после сохранения пороги не 30 и 7"
    # п. 1: пороги можно заменить — три порога сохраняются
    helpers_lists.fill_field_form(page, thresholds=[60, 30, 7])
    assert submit_field_form(page, list_id), f"поле не сохранено: {refusal_codes(page)}"
    form = open_field(page, list_id, code)
    assert _saved_thresholds(form) == [7, 30, 60], "после замены пороги не 60, 30 и 7"


def test_l08_fourth_threshold_zero_or_366_is_refused_with_reason_at_field(admin_page):
    """Сценарий 8, п. 1: четвёртый порог, порог 0 и порог 366 отклоняются с причиной у поля «пороги»; границы 1 и 365
    принимаются; отказанные поля не созданы (FR-529)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Лицензии"))
    cases = (("порог 0", [0]), ("порог 366", [366]), ("четвёртый порог", [30, 14, 7, "fourth"]))
    for label, values in cases:
        name = f"Срок {label} {secrets.token_hex(3)}"
        open_new_field(page, list_id, "date")
        fourth = values[-1] == "fourth"
        helpers_lists.fill_field_form(page, deadline=True, thresholds=values[:3] if fourth else values, name=name)
        if fourth:
            # входов порогов в форме три: четвёртый добавляется клоном, как отправил бы форму обход браузера
            _threshold_boxes(field_form(page)).last.evaluate(
                "el => { const c = el.cloneNode(true); c.value = '3'; el.after(c); }")
        _lift_number_limits(field_form(page))
        # п. 1: отказ — страница остаётся, у поля «пороги» код и текст причины
        assert not submit_field_form(page, list_id), f"{label}: поле сохранено"
        error = page.locator('[data-error="thresholds"][data-code="thresholds_bad"]')
        expect(error).to_have_count(1)
        expect(error).to_contain_text(THRESHOLDS_BAD)
        expect(field_form(page).locator("[name=name]")).to_have_value(name)
    # п. 1: границы допустимого — 1 и 365 — принимаются (контроль: отказы выше не из-за формы в целом)
    good = add_field(page, list_id, FIELD_DUE, "date", deadline=True, thresholds=[365, 1])
    open_field(page, list_id, good)
    assert _saved_thresholds(field_form(page)) == [1, 365]
    # п. 1: после отказов в списке только «Название» и поле с допустимыми порогами
    assert field_codes(page, list_id) == ["title", good]


# --- Тесты: обход и уведомления -------------------------------------------------------------------------------

def test_l08_due_in_30_days_after_shift_gives_expiring_notification_to_record_employee_and_editors_with_text_and_card_link(
        admin_page, employee):
    """Сценарий 8, п. 2: запись со сроком через 30 дней — сотрудник из поля записи (читающий список) и правящий список
    получают «Истекает срок: <список> — <название>: <поле> <дата>» со ссылкой на карточку записи; читающий, которого нет
    ни в записи, ни среди правящих, уведомления не получает (FR-530, FR-531)."""
    page = admin_page
    list_id, list_name, owner_code, due_code = _deadline_list(page)
    worker = make_list_reader(employee, page, list_id, full_name=_name("Исполнитель"))
    editor = make_list_editor(employee, page, list_id, full_name=_name("Правящий"))
    bystander = make_list_reader(employee, page, list_id, full_name=_name("Читающий"))
    title = f"Лицензия {helpers_lists.unique_word()}"
    today = _today()
    number = _new_record(page, list_id, owner_code, {due_code: today + timedelta(days=31)}, title,
                         owners=[_surname(worker)])
    # когда: ночное задание отрабатывает, до срока 30 дней
    shift(1)
    due = today + timedelta(days=30)
    expected = _text(EXPIRING, list_name, title, FIELD_DUE, due)
    card = f"/lists/{list_id}/{number}/"
    for account in (worker, editor):
        # п. 2: уведомление вида «Срок в записи списка» с текстом по образцу
        rows = _wait_rows(account.page, title, 1)
        assert _texts_of(rows) == [expected]
        expect(rows.first.locator('[data-field="kind"]')).to_have_text(KIND_TITLE)
        # п. 2: ссылка уведомления — карточка записи (оба читают список)
        assert _open_target(account.page, rows.first) == (card, "")
    # п. 2: ссылка действительно открывает карточку записи
    rows = _rows(worker.page, title)
    rows.first.locator('[data-field="text"] a[data-open]').click()
    worker.page.wait_for_url(re.compile(rf"{re.escape(card)}$"))
    expect(worker.page.locator("[data-lists-record]")).to_be_visible()
    # п. 2: читающий вне записи и вне правящих уведомления не получил (контроль — оба получателя выше уже видят своё)
    _no_rows(bystander.page, title)


def test_l08_due_in_7_days_gives_second_notification_by_threshold_7_and_none_repeated_by_30(admin_page, employee):
    """Сценарий 8, п. 3: после уведомления по порогу 30 срок подходит к 7 дням — второе уведомление по порогу 7; по
    порогу 30 повторно не создаётся (FR-530)."""
    page = admin_page
    list_id, list_name, owner_code, due_code = _deadline_list(page)
    worker = make_list_reader(employee, page, list_id, full_name=_name("Исполнитель"))
    title = f"Лицензия {helpers_lists.unique_word()}"
    today = _today()
    _new_record(page, list_id, owner_code, {due_code: today + timedelta(days=31)}, title, owners=[_surname(worker)])
    shift(1)   # до срока 30 дней
    first = _text(EXPIRING, list_name, title, FIELD_DUE, today + timedelta(days=30))
    assert _texts_of(_wait_rows(worker.page, title, 1)) == [first]
    shift(23)  # до срока 7 дней
    # п. 3: второе уведомление — по порогу 7, с новой датой срока в тексте
    second = _text(EXPIRING, list_name, title, FIELD_DUE, today + timedelta(days=7))
    # п. 3: всего два, повтора порога 30 нет
    rows = _wait_rows(worker.page, title, 2, settle=True)
    assert sorted(_texts_of(rows)) == sorted([first, second])


def test_l08_due_day_gives_deadline_reached_notification(admin_page, employee):
    """Сценарий 8, п. 4: наступил день срока — «Срок наступил: <список> — <название>: <поле> <дата>» (FR-530)."""
    page = admin_page
    list_id, list_name, owner_code, due_code = _deadline_list(page)
    worker = make_list_reader(employee, page, list_id, full_name=_name("Исполнитель"))
    title = f"Лицензия {helpers_lists.unique_word()}"
    today = _today()
    _new_record(page, list_id, owner_code, {due_code: today + timedelta(days=31)}, title, owners=[_surname(worker)])
    # когда: до дня срока (по порогу 0 — единственное уведомление: пороги 30 и 7 пропущены одним запуском)
    shift(31)
    # п. 4: «Срок наступил» с датой срока (сегодня)
    rows = _wait_rows(worker.page, title, 1, settle=True)
    assert _texts_of(rows) == [_text(REACHED, list_name, title, FIELD_DUE, today)]


def test_l08_repeated_run_inside_notified_threshold_window_creates_no_duplicates(admin_page, employee):
    """Сценарий 8, п. 5 (решение 19: приёмка проверяет повтор обхода внутри окна уже отработанного порога): после
    уведомления по порогу 30 повторный обход на следующий день дублей не создаёт (FR-530, NFR-511)."""
    page = admin_page
    list_id, list_name, owner_code, due_code = _deadline_list(page)
    worker = make_list_reader(employee, page, list_id, full_name=_name("Исполнитель"))
    editor = make_list_editor(employee, page, list_id, full_name=_name("Правящий"))
    title = f"Лицензия {helpers_lists.unique_word()}"
    today = _today()
    _new_record(page, list_id, owner_code, {due_code: today + timedelta(days=31)}, title, owners=[_surname(worker)])
    shift(1)
    expected = _text(EXPIRING, list_name, title, FIELD_DUE, today + timedelta(days=30))
    for account in (worker, editor):
        assert _texts_of(_wait_rows(account.page, title, 1)) == [expected]
    # когда: обход повторяется, срок через 29 дней — порог 30 уже отработан
    shift(1)
    # п. 5: у обоих получателей по-прежнему одно уведомление
    for account in (worker, editor):
        assert _wait_rows(account.page, title, 1, settle=True).count() == 1


def test_l08_moved_due_date_recounts_thresholds_from_new_date_and_old_date_notifications_do_not_repeat(
        admin_page, employee):
    """Сценарий 8, п. 6: срок перенесли на более позднюю дату — пороги считаются заново от новой даты (уведомление по
    порогу 7 с новой датой); уведомление о старой дате заново не идёт (FR-530)."""
    page = admin_page
    list_id, list_name, owner_code, due_code = _deadline_list(page)
    worker = make_list_reader(employee, page, list_id, full_name=_name("Исполнитель"))
    title = f"Лицензия {helpers_lists.unique_word()}"
    today = _today()
    number = _new_record(page, list_id, owner_code, {due_code: today + timedelta(days=31)}, title,
                         owners=[_surname(worker)])
    shift(1)  # в базе срок «сегодня + 30»: уведомление по порогу 30 со старой датой
    old = _text(EXPIRING, list_name, title, FIELD_DUE, today + timedelta(days=30))
    assert _texts_of(_wait_rows(worker.page, title, 1)) == [old]
    # п. 6: срок перенесён на 60 дней вперёд (правка записи формой)
    open_edit_record(page, list_id, number)
    helpers_lists.fill_record(page, {due_code: _fmt(today + timedelta(days=60))})
    assert submit_record(page) == number
    # когда: подходят даты — до нового срока 7 дней
    shift(53)
    # п. 6: пороги от новой даты: уведомление по порогу 7 с новой датой; о старой дате — только прежнее, одно
    new = _text(EXPIRING, list_name, title, FIELD_DUE, today + timedelta(days=7))
    rows = _wait_rows(worker.page, title, 2, settle=True)
    texts = _texts_of(rows)
    assert sorted(texts) == sorted([old, new]), f"тексты уведомлений: {texts}"
    assert texts.count(old) == 1, "уведомление о старой дате создано повторно"


def test_l08_archived_record_and_hidden_deadline_field_get_no_notifications(admin_page, employee):
    """Сценарий 8, п. 7: запись в архиве и скрытое поле-срок уведомлений не дают; живая запись по видимому полю-сроку
    получает уведомление (контроль) (FR-509, FR-523, FR-530)."""
    page = admin_page
    list_id, list_name, _owner, due_code = _deadline_list(page)
    warranty_code = add_field(page, list_id, FIELD_WARRANTY, "date", deadline=True, thresholds=[30, 7])
    editor = make_list_editor(employee, page, list_id, full_name=_name("Правящий"))
    today = _today()
    dues = {due_code: today + timedelta(days=31), warranty_code: today + timedelta(days=31)}
    alive_title = f"Лицензия живая {helpers_lists.unique_word()}"
    archived_title = f"Лицензия архивная {helpers_lists.unique_word()}"
    _new_record(page, list_id, _owner, dues, alive_title)
    archived_number = _new_record(page, list_id, _owner, dues, archived_title)
    # дано: запись в архиве; поле «Гарантия до» скрыто
    archive_record(page, list_id, archived_number)
    helpers_lists.open_settings(page, list_id, "fields")
    _field_row(page, warranty_code).locator('button[data-action="field-hide"]').click()
    expect(_field_row(page, warranty_code).locator('[data-hidden="true"]')).to_have_count(1)
    # когда: ночное задание отрабатывает
    shift(1)
    # контроль: живая запись — одно уведомление, и только по видимому полю «Действует до»
    rows = _wait_rows(editor.page, alive_title, 1, settle=True)
    assert _texts_of(rows) == [_text(EXPIRING, list_name, alive_title, FIELD_DUE, today + timedelta(days=30))]
    # п. 7: по скрытому полю уведомлений нет (в тексте единственного уведомления живой записи названия поля нет)
    assert FIELD_WARRANTY not in _texts_of(rows)[0]
    # п. 7: по записи в архиве уведомлений нет
    _no_rows(editor.page, archived_title)


def test_l08_run_after_two_skipped_days_sends_missed_threshold_once(admin_page, employee):
    """Сценарий 8, п. 8: задание не работало два дня (день порога 30 пропущен) — при следующем запуске пропущенный
    порог исполнен один раз, дальше не повторяется (FR-530)."""
    page = admin_page
    list_id, list_name, owner_code, due_code = _deadline_list(page)
    worker = make_list_reader(employee, page, list_id, full_name=_name("Исполнитель"))
    title = f"Лицензия {helpers_lists.unique_word()}"
    today = _today()
    _new_record(page, list_id, owner_code, {due_code: today + timedelta(days=32)}, title, owners=[_surname(worker)])
    # когда: прошло три дня подряд без обхода (до срока было 32, 31, 30 — порог 30 пропущен), обход при сроке через 29
    shift(3)
    # п. 8: пропущенный порог исполнен — одно уведомление, с датой срока
    rows = _wait_rows(worker.page, title, 1, settle=True)
    assert _texts_of(rows) == [_text(EXPIRING, list_name, title, FIELD_DUE, today + timedelta(days=29))]
    # п. 8: следующий обход порог 30 не повторяет
    shift(1)
    assert _wait_rows(worker.page, title, 1, settle=True).count() == 1


def test_l08_run_after_skip_over_two_thresholds_sends_one_notification_by_nearest_threshold(admin_page, employee):
    """Сценарий 8, п. 8: обход пропустил сразу два порога (30 и 7) — создано одно уведомление, по ближайшему порогу;
    по двум порогам сразу уведомление не создаётся, пропущенный порог 30 позже не нагоняется (FR-530). Номер порога в
    интерфейсе не виден — его держит серверный T-6115 (по `object_ref`)."""
    page = admin_page
    list_id, list_name, owner_code, due_code = _deadline_list(page)
    worker = make_list_reader(employee, page, list_id, full_name=_name("Исполнитель"))
    title = f"Лицензия {helpers_lists.unique_word()}"
    today = _today()
    _new_record(page, list_id, owner_code, {due_code: today + timedelta(days=31)}, title, owners=[_surname(worker)])
    # когда: обход запускается, когда до срока уже 5 дней (пороги 30 и 7 позади)
    shift(26)
    # п. 8: ровно одно уведомление
    rows = _wait_rows(worker.page, title, 1, settle=True)
    assert _texts_of(rows) == [_text(EXPIRING, list_name, title, FIELD_DUE, today + timedelta(days=5))]
    # п. 8: следующий обход пропущенное не нагоняет
    shift(1)
    assert _wait_rows(worker.page, title, 1, settle=True).count() == 1


def test_l08_dismissed_employee_named_in_record_gets_no_notification(admin_page, employee, mailpit):
    """Сценарий 8, п. 9: сотрудник, указанный в записи, уволен — ни уведомления, ни письма он не получает; действующий
    сотрудник из той же записи получает оба (контроль) (FR-530). Уволенный в портал не входит, поэтому его проверка —
    письмо (срок письма сдвигается командой стенда)."""
    page = admin_page
    list_id, list_name, owner_code, due_code = _deadline_list(page)
    active = employee(full_name=_name("Действующий"))
    leaving = employee(full_name=_name("Увольняемый"))
    # дано: письма приходят в любое время суток
    _save_prefs(active.page, quiet="none")
    _save_prefs(leaving.page, quiet="none")
    seen_active = helpers_lists.mail_ids(mailpit, active.email)
    seen_leaving = helpers_lists.mail_ids(mailpit, leaving.email)
    title = f"Лицензия {helpers_lists.unique_word()}"
    today = _today()
    _new_record(page, list_id, owner_code, {due_code: today + timedelta(days=31)}, title,
                owners=[_surname(active), _surname(leaving)])
    # дано: один из названных в записи сотрудников уволен
    _dismiss(page, leaving.id)
    # когда: ночное задание отрабатывает
    shift(1)
    # п. 9: действующий получил уведомление на портале и письмо
    rows = _wait_rows(active.page, title, 1)
    expected = _text(EXPIRING, list_name, title, FIELD_DUE, today + timedelta(days=30))
    assert _texts_of(rows) == [expected]
    helpers_notify.tick(shift=PAST_ANY_TERM)
    _item_mail_with(mailpit, active.email, expected, seen=seen_active)
    # п. 9: уволенному письма нет (контроль — письмо действующему после того же сдвига срока получено)
    assert helpers_lists.no_item_mail(mailpit, leaving.email, seen=seen_leaving, wait=10), \
        "уволенному ушло письмо о сроке"


def test_l08_my_notifications_shows_list_deadline_kind_to_any_employee_with_portal_and_mail_on_by_default(
        admin_page, employee):
    """Сценарий 8, п. 10: «Мои уведомления» любого сотрудника — с правом на списки и без него — показывают вид «Срок в
    записи списка» (модуль «Списки»); каналы по умолчанию «На портале» (закреплён) и «Почта» (FR-531)."""
    plain = employee(full_name=_name("Сотрудник"))
    _role_id, role_name = make_list_role(admin_page)
    rightless = employee(role=role_name, full_name=_name("Безправный"))
    for account in (plain, rightless):
        account.page.goto("/me/notifications/")
        table = account.page.locator("table[data-notify-table]")
        expect(table).to_be_visible()
        row = table.locator(f'tr[data-notify-kind="{KIND}"]')
        # п. 10: вид показан сотруднику
        expect(row).to_have_count(1)
        expect(row.locator('[data-field="title"]')).to_have_text(KIND_TITLE)
        expect(row.locator('[data-field="module"]')).to_have_text(MODULE)
        # п. 10: «На портале» отмечено и закреплено, «Почта» отмечена по умолчанию
        expect(row.locator('td[data-channel="portal"][data-locked="1"] input[type=checkbox]')).to_be_checked()
        expect(_cell(account.page, KIND, "email")).to_be_checked()


def test_l08_employee_in_record_without_read_right_gets_reminder_linking_to_pinned_section_of_own_card(
        admin_page, employee):
    """Сценарий 8, п. 11: сотрудник указан в записи, но список не читает — получает напоминание, его ссылка ведёт в
    раздел «Закреплённое» его карточки (`/me/#lists-pinned`), без перехода в запись (FR-525, FR-530, FR-531)."""
    page = admin_page
    list_id, list_name, owner_code, due_code = _deadline_list(page)
    _role_id, role_name = make_list_role(page)
    outsider = employee(role=role_name, full_name=_name("Закреплённый"))
    title = f"Лицензия {helpers_lists.unique_word()}"
    today = _today()
    number = _new_record(page, list_id, owner_code, {due_code: today + timedelta(days=31)}, title,
                         owners=[_surname(outsider)])
    shift(1)
    # п. 11: напоминание получено
    rows = _wait_rows(outsider.page, title, 1)
    assert _texts_of(rows) == [_text(EXPIRING, list_name, title, FIELD_DUE, today + timedelta(days=30))]
    # п. 11: ссылка — раздел «Закреплённое» его карточки, не запись
    assert _open_target(outsider.page, rows.first) == ("/me/", "lists-pinned")
    rows.first.locator('[data-field="text"] a[data-open]').click()
    expect(outsider.page).to_have_url(re.compile(r"/me/#lists-pinned$"))
    pinned = outsider.page.locator("#lists-pinned[data-lists-pinned]")
    expect(pinned).to_be_visible()
    line = pinned.locator("li[data-pinned-record]").filter(has_text=title)
    expect(line).to_have_count(1)
    for part in (list_name, FIELD_OWNER):
        expect(line).to_contain_text(part)
    # п. 11: список он не читает — ссылки на запись в строке нет, запись ему недоступна
    expect(line.locator("a")).to_have_count(0)
    assert status_of(outsider.page, f"/lists/{list_id}/{number}/") == 404


def test_l08_manager_outside_edit_set_and_record_fields_gets_no_reminder(admin_page, employee):
    """Сценарий 8, п. 12: управляющий, которого нет ни в наборе «Правят», ни в полях записи, напоминания не получает;
    сотрудник из поля записи получает (контроль) (FR-530)."""
    page = admin_page
    list_id, list_name, owner_code, due_code = _deadline_list(page)
    worker = make_list_reader(employee, page, list_id, full_name=_name("Исполнитель"))
    title = f"Лицензия {helpers_lists.unique_word()}"
    today = _today()
    _new_record(page, list_id, owner_code, {due_code: today + timedelta(days=31)}, title, owners=[_surname(worker)])
    shift(1)
    # контроль: сотрудник из записи получил уведомление
    rows = _wait_rows(worker.page, title, 1)
    assert _texts_of(rows) == [_text(EXPIRING, list_name, title, FIELD_DUE, today + timedelta(days=30))]
    # п. 12: управляющий (администратор круга) создал список и запись, но напоминания по ней не получил
    _no_rows(page, title)


def test_l08_telegram_gets_only_expiring_text_and_link_without_record_and_list_names(admin_page, employee):
    """Сценарий 8, п. 14: у получателя включён Telegram — приходит «Истекает срок в записи списка» и ссылка, без названий
    записи, списка и поля, без имени и почты (FR-531; SPEC-004 FR-317). MAX и Web Push приёмка не проверяет (решение 19)."""
    page = admin_page
    list_id, list_name, owner_code, due_code = _deadline_list(page)
    worker = make_list_reader(employee, page, list_id, full_name=_name("Исполнитель"))
    title = f"Лицензия {helpers_lists.unique_word()}"
    today = _today()
    _new_record(page, list_id, owner_code, {due_code: today + timedelta(days=31)}, title, owners=[_surname(worker)])
    bots = helpers_lists.bots()
    chat = _chat_id()
    with helpers_notify.channels_on(page, "telegram"):
        # дано: Telegram привязан, ячейка «Telegram» вида включена, тихих часов нет
        helpers_lists.bind_telegram(worker.page, bots, chat)
        _save_prefs(worker.page, cells={(KIND, "telegram"): True}, quiet="none")
        expect(_cell(worker.page, KIND, "telegram")).to_be_checked()
        # когда: приходит уведомление о сроке
        shift(1)
        # п. 14: в Telegram — текст вида без названий
        found = helpers_lists.wait_telegram(bots, chat, text_has=EXTERNAL_EXPIRING, timeout=60.0)
        assert len(found) == 1, f"сообщений о сроке в свой чат: {len(found)}"
        message = found[0]
        assert message["text"] == EXTERNAL_EXPIRING, "внешний текст не равен тексту вида"
        dump = json.dumps(message, ensure_ascii=False)
        for forbidden in (title, list_name, FIELD_DUE, worker.full_name, worker.email):
            assert forbidden not in dump, "во внешнем сообщении есть данные записи, списка или человека"
        # п. 14: ссылка — на портал (адрес страницы уведомлений)
        markup = message["reply_markup"]
        markup = json.loads(markup) if isinstance(markup, str) else markup
        path = urlsplit(markup["inline_keyboard"][0][0]["url"]).path
        assert path.startswith("/notifications/"), f"ссылка внешнего сообщения: {path}"


def test_l08_deadline_mail_comes_by_default_with_list_record_field_and_date_text(admin_page, employee, mailpit):
    """Сценарий 8, п. 10 и FR-531: письмо о сроке приходит по умолчанию (ячейка «Почта» вида не менялась); в тексте
    письма — список, запись, поле и дата срока, в теме названий записи и списка нет (FR-530, FR-531)."""
    page = admin_page
    list_id, list_name, owner_code, due_code = _deadline_list(page)
    worker = make_list_reader(employee, page, list_id, full_name=_name("Исполнитель"))
    # дано: письмо приходит в любое время суток; ячейка «Почта» вида — по умолчанию (не менялась)
    _save_prefs(worker.page, quiet="none")
    expect(_cell(worker.page, KIND, "email")).to_be_checked()
    seen = helpers_lists.mail_ids(mailpit, worker.email)
    title = f"Лицензия {helpers_lists.unique_word()}"
    today = _today()
    _new_record(page, list_id, owner_code, {due_code: today + timedelta(days=31)}, title, owners=[_surname(worker)])
    shift(1)
    expected = _text(EXPIRING, list_name, title, FIELD_DUE, today + timedelta(days=30))
    assert _texts_of(_wait_rows(worker.page, title, 1)) == [expected]
    # когда: срок письма прошёл
    helpers_notify.tick(shift=PAST_ANY_TERM)
    # п. 10: в тексте письма — полный текст уведомления: список, запись, поле, дата срока (письмо ищется по этому
    # тексту среди новых писем `notify.item` получателя; нет такого за минуту — `AssertionError`)
    mail = _item_mail_with(mailpit, worker.email, expected, seen=seen)
    # в теме письма названий записи и списка нет (внешний текст вида)
    for forbidden in (title, list_name):
        assert forbidden not in mail["Subject"], "в теме письма есть название записи или списка"


# --- Тесты: отбор «Истекает» ----------------------------------------------------------------------------------

def test_l08_expiring_preset_shows_records_due_within_largest_threshold_90_days_or_overdue(admin_page):
    """Сценарий 8, п. 15: отбор «Истекает» при поле-сроке с наибольшим порогом 90 дней — записи со сроком в ближайшие 90
    дней или просроченные; дальше 90 дней не показаны (FR-520). Границу «ровно 90» тест не берёт (+89 и +91)."""
    page = admin_page
    list_id, _name_, owner_code, due_code = _deadline_list(page, thresholds=(90, 7))
    today = _today()
    plan = {"в 60 днях": 60, "в 89 днях": 89, "просрочена": -1, "в 91 дне": 91, "в 120 днях": 120}
    numbers = {}
    for label, days in plan.items():
        numbers[label] = _new_record(page, list_id, owner_code, {due_code: today + timedelta(days=days)},
                                     f"Лицензия {label} {helpers_lists.unique_word()}")
    # п. 15: показаны ближайшие 90 дней и просроченная
    shown = _grid_numbers(page, list_id, "expiring")
    assert shown == sorted(numbers[k] for k in ("в 60 днях", "в 89 днях", "просрочена")), f"отбор «Истекает»: {shown}"
    # контроль: отбор «Все» показывает все пять записей
    assert _grid_numbers(page, list_id, "all") == sorted(numbers.values())


def test_l08_expiring_preset_of_deadline_field_without_thresholds_uses_30_days(admin_page):
    """Сценарий 8, п. 15: у поля-срока без заданных порогов отбор «Истекает» берёт 30 дней: записи со сроком в ближайшие
    30 дней или просроченные (FR-520). Границу «ровно 30» тест не берёт (+29 и +31)."""
    page = admin_page
    # дано: у поля-срока порогов нет (входы порогов очищены при заведении поля, `_deadline_list(thresholds=())`);
    # повторный показ формы поля не проверяется: «30 и 7» подставляются только при первом включении «срока»
    # (решение Opus, review-decisions-1, E2)
    list_id, _name_, owner_code, due_code = _deadline_list(page, thresholds=())
    today = _today()
    plan = {"в 29 днях": 29, "просрочена": -1, "в 31 дне": 31, "в 60 днях": 60}
    numbers = {}
    for label, days in plan.items():
        numbers[label] = _new_record(page, list_id, owner_code, {due_code: today + timedelta(days=days)},
                                     f"Лицензия {label} {helpers_lists.unique_word()}")
    # п. 15: показаны ближайшие 30 дней и просроченная
    shown = _grid_numbers(page, list_id, "expiring")
    assert shown == sorted(numbers[k] for k in ("в 29 днях", "просрочена")), f"отбор «Истекает»: {shown}"
    assert _grid_numbers(page, list_id, "all") == sorted(numbers.values())
