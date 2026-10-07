"""T-3148: сценарий 10 — подразделения-клиенты и заявители: справочник, загрузка таблицы, страница «Заявители»,
журнал, права исполнителя (FR-260…FR-268, FR-288, FR-289)."""
import io
import re
import secrets
import urllib.parse
import zipfile

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org, helpers_sd
from tests.e2e.helpers_org import unique_name
from tests.e2e.helpers_sd import FOREIGN_DOMAIN, MAILBOX, requester_email
from tests.support_servicedesk import build_mail

CSV_MIME = "text/csv"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HEAD = ["Почта", "Фамилия", "Имя", "Отчество", "Подразделение"]
UNITS_URL = "/servicedesk/dictionaries/client-units/"
IMPORT_URL = "/servicedesk/requesters/import/"
IMPORT_ID_URL = re.compile(r"/servicedesk/requesters/import/(\d+)/$")
STORED_TEXT = ("ФИО, почта и подразделение работников общества хранятся, чтобы определять подразделение "
               "заявителя по адресу письма")  # § 14.2, spec.md:479-481
# пределы 6.23 (FR-265) — литералами: из apps.servicedesk тесты приёмки не импортируют
OVER_SIZE = 2 * 1024 * 1024 + 1
OVER_ROWS = 2001


# --- помощники файла: слова, письма, справочник ------------------------------------------------------

def _word() -> str:
    """Уникальное слово темы: буква и шесть знаков, не из одних цифр (доп. 41 (в))."""
    return f"t{secrets.token_hex(3)}"


def _norm(text: str) -> str:
    return " ".join(text.split())


def _table(rows, fmt="csv", delimiter=";", *, bom=False) -> bytes:
    """Таблица для загрузки: первая строка — заголовок среза 003 («Почта», «Фамилия», «Имя», «Отчество»,
    «Подразделение»); `rows` — строки данных из пяти ячеек (хвост можно не писать)."""
    full = [list(row) + [""] * (len(HEAD) - len(row)) for row in rows]
    return helpers_sd.make_table([HEAD] + full, fmt, delimiter, bom=bom)


def _mail_ticket(page, sender: str) -> int:
    """Письмо `sender` на ящик заявок -> заявка (опрос сразу); возвращает номер. У отправителя появляется запись
    заявителя с отметкой «заявка» (2.2)."""
    word = _word()
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=f"Заявка {word}",
                                  text=f"Не работает принтер {word}"))
    return helpers_sd.ticket_number_by_subject(page, word)


def _post(page, fragment: str, action) -> None:
    """Выполняет `action` и ждёт ответ POST, в адресе которого есть `fragment` (ответ, а не появление страницы)."""
    with page.expect_response(lambda r: r.request.method == "POST" and fragment in r.url):
        action()
    page.wait_for_load_state()


def _unit_rows(page):
    return page.locator('table[data-dictionary="client_unit"] tr[data-dictionary-row]')


def _unit_row(page, name: str):
    """Строка подразделения по названию (страница списка уже открыта); название уникально."""
    return _unit_rows(page).filter(has=page.locator('[data-cell="name"]', has_text=name))


def _open_units(page) -> None:
    page.goto(UNITS_URL)
    expect(page.locator('table[data-dictionary="client_unit"]')).to_be_visible()


def _create_unit(page, name: str) -> None:
    """Добавление подразделения-клиента через интерфейс (12.6: форма в слайдере, поле `name`; порядка нет)."""
    _open_units(page)
    page.locator('a[data-action="dictionary-new"]').first.click()
    form = page.locator('form[data-form="dictionary"]')
    expect(form).to_be_visible()
    form.locator("input[name=name]").fill(name)
    _post(page, UNITS_URL, lambda: helpers.submit(form))
    _open_units(page)
    expect(_unit_row(page, name)).to_have_count(1)


def _rename_unit(page, old: str, new: str) -> None:
    _open_units(page)
    _unit_row(page, old).locator('a[data-action="dictionary-edit"]').click()
    form = page.locator('form[data-form="dictionary"]')
    expect(form).to_be_visible()
    form.locator("input[name=name]").fill(new)
    _post(page, "/edit/", lambda: helpers.submit(form))
    _open_units(page)


def _archive_unit(page, name: str) -> None:
    _open_units(page)
    button = _unit_row(page, name).locator('form[data-form="dictionary-archive"] button[data-action="dictionary-archive"]')
    _post(page, "/archive/", button.click)
    _open_units(page)
    expect(_unit_row(page, name)).to_have_attribute("data-archived", "true")


def _delete_unit_dialog(page, name: str) -> None:
    """Открывает диалог удаления подразделения и подтверждает его; результат не ждёт (успех — 302 на список,
    отказ — 200 с `[role=alert]`)."""
    _open_units(page)
    _unit_row(page, name).locator('a[data-action="dictionary-delete"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dictionary-delete"]')
    expect(dialog).to_be_visible()
    _post(page, "/delete/", lambda: helpers.submit(dialog.locator("form")))


def _unit_options(page) -> list:
    """Названия подразделений в `select[name=client_unit]` страницы (без пустого пункта)."""
    return [t.strip() for t in page.locator("select[name=client_unit] option").all_inner_texts() if t.strip()]


def _guest_form_units(new_context) -> list:
    """Подразделения в выборе открытой формы `/request/` (гость, без входа)."""
    guest = new_context().new_page()
    guest.goto("/request/")
    expect(guest.locator('form[data-form="request"] select[name=client_unit]')).to_be_visible()
    return _unit_options(guest)


# --- помощники загрузки таблицы -----------------------------------------------------------------------

def _upload_preview(page, content: bytes, name: str, mime: str = CSV_MIME) -> str:
    """`/servicedesk/requesters/import/`, файл в `form[data-form="import-upload"]`, ждёт страницу предпросмотра и
    `[data-import-preview]`; возвращает номер загрузки."""
    page.goto(IMPORT_URL)
    form = page.locator('form[data-form="import-upload"]')
    expect(form).to_be_visible()
    helpers_org.upload_file(form, content, name=name, mime=mime)
    page.wait_for_url(IMPORT_ID_URL)
    expect(page.locator("[data-import-preview]")).to_be_visible()
    return IMPORT_ID_URL.search(page.url).group(1)


def _upload_refused(page, content: bytes, name: str, mime: str = CSV_MIME):
    """Загрузка отклоняемого файла: возвращает локатор отказа `[role=alert]`; адрес страницы остаётся
    `/servicedesk/requesters/import/` (предпросмотра нет)."""
    page.goto(IMPORT_URL)
    form = page.locator('form[data-form="import-upload"]')
    expect(form).to_be_visible()
    helpers_org.upload_file(form, content, name=name, mime=mime)
    alert = page.locator("[role=alert][data-code]").first
    expect(alert).to_be_visible(timeout=30_000)
    assert IMPORT_ID_URL.search(page.url) is None, "предпросмотр открылся у отклонённого файла"
    return alert


def _row(page, number: int):
    """Строка предпросмотра по номеру в файле (с 1)."""
    return page.locator(f'tr[data-import-row][data-row-number="{number}"]')


def _confirm(page, *, delete_missing: bool = False):
    """Подтверждение загрузки: флажок `delete_missing` по параметру, кнопка «Подтвердить»; ждёт итог
    `[data-result-summary]` (до 60 с) и возвращает его локатор."""
    form = page.locator('form[data-form="import-confirm"]')
    expect(form).to_be_visible()
    box = form.locator("input[type=checkbox][name=delete_missing]")
    if delete_missing:
        box.check()
    else:
        expect(box).not_to_be_checked()
    form.locator("button[type=submit]").click()
    summary = page.locator("[data-result-summary]")
    expect(summary).to_be_visible(timeout=60_000)
    return summary


def _load(page, rows, name="table.csv", *, delete_missing: bool = False):
    """Загрузка таблицы целиком (предпросмотр и подтверждение): возвращает `(номер загрузки, итог)`."""
    number = _upload_preview(page, _table(rows), name)
    return number, _confirm(page, delete_missing=delete_missing)


def _expect_totals(summary, *, added=None, updated=None, unchanged=None, errors=None, deleted=None,
                   origin_changed=None) -> None:
    for key, value in (("added", added), ("updated", updated), ("unchanged", unchanged), ("errors", errors),
                       ("deleted", deleted), ("origin-changed", origin_changed)):
        if value is not None:
            expect(summary).to_have_attribute(f"data-{key}", str(value))


# --- помощники страницы «Заявители» -------------------------------------------------------------------

def _open_requesters(page, **params) -> None:
    page.goto("/servicedesk/requesters/" + ("?" + urllib.parse.urlencode(params) if params else ""))
    expect(page.locator('form[data-form="requesters-filter"]')).to_be_visible()


def _requester(page, email: str):
    """Строка заявителя по полному адресу (поиск `q`); ждёт ровно одну строку."""
    _open_requesters(page, q=email)
    row = page.locator("tr[data-requester]")
    expect(row).to_have_count(1)
    return row


def _no_requester(page, email: str) -> None:
    """Записи заявителя с этим адресом нет (страница загружена, строк нет)."""
    _open_requesters(page, q=email)
    expect(page.locator("tr[data-requester]")).to_have_count(0)


def _requester_id(page, email: str) -> str:
    return _requester(page, email).get_attribute("data-id")


def _cell(row, name: str) -> str:
    return row.locator(f'[data-cell="{name}"]').inner_text().strip()


def _journal_text(page, action: str, object_id=None) -> str:
    """Склеенный текст строк журнала по коду события (и номеру объекта)."""
    return "\n".join(helpers_org.audit_rows(page, action, object_id))


def _executor_edit(page, number: int, *, unit=None, name=None) -> None:
    """Исполнитель правит поля заявки (13.3, `form[data-form="ticket-fields"]`): подразделение — обычной кнопкой
    отправки (доп. 41 (г)), ФИО — кнопкой «Сохранить и в записи заявителя»; ждёт ответ POST `…/fields/`."""
    card = helpers_sd.open_ticket(page, number)
    form = card.locator('form[data-form="ticket-fields"]')
    expect(form).to_be_visible()
    if unit is not None:
        form.locator("select[name=client_unit]").select_option(label=unit)
    if name is not None:
        form.locator("input[name=requester_name]").fill(name)
        button = form.locator('button[name="save_to_record"][value="1"]')
    else:
        button = form.locator('button[type=submit]:not([name="save_to_record"])')
    _post(page, f"/tickets/{number}/fields/", button.click)


# --- сценарий 10 -----------------------------------------------------------------------------------------

def test_d10_client_departments_add_rename_archive_delete_only_unused(admin_page, new_context):
    """Сценарий 10, п. 1: подразделения-клиенты добавляются, переименовываются и убираются в архив; архивное не
    предлагается на открытой форме и в выборе формы заявителя; удалить можно только неиспользованное (FR-260)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    old, new = unique_name("Склад"), unique_name("Склад-новый")
    # п. 1: добавление и переименование
    _create_unit(page, old)
    _rename_unit(page, old, new)
    _open_units(page)
    expect(_unit_row(page, new)).to_have_count(1)
    expect(_unit_row(page, old)).to_have_count(0)
    assert new in _guest_form_units(new_context), "действующее подразделение не предложено на открытой форме"
    # используется: запись заявителя с этим подразделением (и вторая запись без подразделения)
    with_unit, without_unit = requester_email(), requester_email()
    _load(page, [[with_unit, "Первов", "Пётр", "", new], [without_unit, "Второв", "Иван", "", ""]],
          f"{secrets.token_hex(3)}.csv")
    # п. 1: используемое не удаляется — отказ со словом «архив» (14.1, `in_use`), строка остаётся
    _delete_unit_dialog(page, new)
    alert = page.locator('[role=alert][data-code="in_use"]').first
    expect(alert).to_be_visible()
    assert "архив" in alert.inner_text().lower()
    _open_units(page)
    expect(_unit_row(page, new)).to_have_count(1)
    # п. 1: в архив — метка «в архиве», не предлагается на форме и в выборе правки заявителя
    _archive_unit(page, new)
    expect(_unit_row(page, new).locator("[data-archived-mark]")).to_contain_text("в архиве")
    assert new not in _guest_form_units(new_context), "архивное подразделение предложено на открытой форме"
    _requester(page, without_unit).locator('a[data-action="requester-edit"]').click()
    form = page.locator('form[data-form="requester"]')
    expect(form).to_be_visible()
    assert new not in _unit_options(form), "архивное подразделение предложено в выборе правки заявителя"
    # п. 1: неиспользованное удаляется
    spare = unique_name("Склад-лишний")
    _create_unit(page, spare)
    _delete_unit_dialog(page, spare)
    _open_units(page)
    expect(_unit_row(page, spare)).to_have_count(0)


def test_d10_csv_both_delimiters_and_xlsx_500_rows_preview_statuses_nothing_written_before_confirm(admin_page):
    """Сценарий 10, п. 2: CSV с «;» и «,» и XLSX на 500 строк — предпросмотр показывает по каждой строке «будет
    добавлен», «будет обновлён», «без изменений» или «ошибка»; до подтверждения ничего не записано (FR-262, FR-263)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    exist, same = requester_email(), requester_email()
    _load(page, [[exist, "Старов", "Иван", "Иванович", ""], [same, "Прежнев", "Пётр", "Петрович", ""]],
          f"{secrets.token_hex(3)}.csv")
    # CSV с «;»: добавлен, обновлён, без изменений, ошибка (нет почты)
    fresh = requester_email()
    rows = [[fresh, "Новиков", "Олег", "", ""], [exist, "Новов", "Иван", "Иванович", ""],
            [same, "Прежнев", "Пётр", "Петрович", ""], ["", "Безпочтов", "Лев", "", ""]]
    _upload_preview(page, _table(rows, "csv", ";"), f"{secrets.token_hex(3)}.csv")
    for number, result, word in ((1, "will_add", "будет добавлен"), (2, "will_update", "будет обновлён"),
                                 (3, "unchanged", "без изменений"), (4, "error", "ошибка")):
        expect(_row(page, number)).to_have_attribute("data-row-result", result)
        expect(_row(page, number)).to_contain_text(word)
    # «будет обновлён: что изменится» (14.2, доп. 30 (а)): строка называет поле «ФИО» и новое значение
    expect(_row(page, 2)).to_contain_text("ФИО")
    expect(_row(page, 2)).to_contain_text("Новов")
    expect(_row(page, 4).locator("[data-row-reason]")).to_be_visible()
    # до подтверждения ничего не записано
    _no_requester(page, fresh)
    assert "Старов" in _cell(_requester(page, exist), "name"), "запись обновлена до подтверждения"
    # CSV с «,» (и BOM): одна новая строка
    comma = requester_email()
    _upload_preview(page, _table([[comma, "Запятов", "Артём", "", ""]], "csv", ",", bom=True),
                    f"{secrets.token_hex(3)}.csv")
    expect(_row(page, 1)).to_have_attribute("data-row-result", "will_add")
    _no_requester(page, comma)
    # XLSX на 500 строк: предпросмотр строится, до подтверждения записей нет, после — все 500 добавлены
    emails = [requester_email() for _ in range(500)]
    big = _table([[e, f"Тысячев{i}", "Иван", "", ""] for i, e in enumerate(emails)], "xlsx")
    number = _upload_preview(page, big, f"{secrets.token_hex(3)}.xlsx", XLSX_MIME)
    expect(_row(page, 1)).to_have_attribute("data-row-result", "will_add")
    _no_requester(page, emails[0])
    _no_requester(page, emails[-1])
    page.goto(f"/servicedesk/requesters/import/{number}/")  # подтверждение — на странице предпросмотра
    summary = _confirm(page)
    _expect_totals(summary, added=500, updated=0, unchanged=0, errors=0)
    expect(_requester(page, emails[-1])).to_have_count(1)


def test_d10_unknown_departments_named_in_preview_list_to_create(admin_page):
    """Сценарий 10, п. 3: подразделение из файла, которого нет в справочнике, названо в списке подразделений,
    которые будут созданы; после подтверждения оно создано (FR-263)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    known, new_a, new_b = unique_name("Известное"), unique_name("Новое-а"), unique_name("Новое-б")
    _create_unit(page, known)
    rows = [[requester_email(), "Один", "Иван", "", known], [requester_email(), "Два", "Пётр", "", new_a],
            [requester_email(), "Три", "Олег", "", new_b]]
    _upload_preview(page, _table(rows), f"{secrets.token_hex(3)}.csv")
    listed = " | ".join(page.locator("[data-import-new-units] li").all_inner_texts())
    assert new_a in listed and new_b in listed, f"новые подразделения не названы: {listed!r}"
    assert known not in listed, "известное подразделение названо среди создаваемых"
    # до подтверждения справочник не изменён
    _open_units(page)
    expect(_unit_row(page, new_a)).to_have_count(0)
    page.go_back()
    expect(page.locator("[data-import-preview]")).to_be_visible()
    _confirm(page)
    _open_units(page)
    expect(_unit_row(page, new_a)).to_have_count(1)
    expect(_unit_row(page, new_b)).to_have_count(1)


def test_d10_error_rows_have_russian_reason_skipped_on_confirm_with_summary(admin_page):
    """Сценарий 10, п. 4: строка без почты, с чужим доменом и повтор почты помечены «ошибка: …» с причиной по-русски;
    при подтверждении они пропущены, остальные применены, итог «добавлено N, обновлено M, без изменений K, с
    ошибками L» (FR-263)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    good_a, good_b, foreign = requester_email(), requester_email(), f"x-{secrets.token_hex(3)}@{FOREIGN_DOMAIN}"
    rows = [[good_a, "Годнов", "Иван", "", ""], [good_b, "Годнова", "Анна", "", ""],
            ["", "Безпочтов", "Лев", "", ""], [foreign, "Чужов", "Олег", "", ""],
            [good_b, "Повторов", "Пётр", "", ""]]
    _upload_preview(page, _table(rows), f"{secrets.token_hex(3)}.csv")
    for number in (1, 2):
        expect(_row(page, number)).to_have_attribute("data-row-result", "will_add")
    for number, reason in ((3, "ошибка: не указана почта"), (4, "ошибка: почта не из корпоративного домена"),
                           (5, "ошибка: повтор почты")):
        expect(_row(page, number)).to_have_attribute("data-row-result", "error")
        expect(_row(page, number).locator("[data-row-reason]")).to_contain_text(reason)
    summary = _confirm(page)
    _expect_totals(summary, added=2, updated=0, unchanged=0, errors=3)
    expect(summary).to_contain_text("добавлено 2, обновлено 0, без изменений 0, с ошибками 3")
    expect(_requester(page, good_a)).to_have_count(1)
    expect(_requester(page, good_b)).to_have_count(1)
    _no_requester(page, foreign)
    assert "Годнова" in _cell(_requester(page, good_b), "name"), "повтор почты перезаписал первую строку"


def test_d10_delete_flag_off_by_default_on_shows_count_and_keeps_requesters_with_tickets(
        browser, browser_context_args, stand_admin, admin_page):
    """Сценарий 10, п. 5: флажок удаления выключен по умолчанию — никто не удалён; включён — в предпросмотре видно,
    сколько будет удалено, а заявитель с заявками не удаляется (FR-264)."""
    helpers_sd.reset_stand_and_relogin(browser, browser_context_args, stand_admin, admin_page)
    page = admin_page
    helpers_sd.ensure_ready(page)
    keep, drop, with_ticket = requester_email(), requester_email(), requester_email()
    _load(page, [[keep, "Остаёнов", "Иван", "", ""], [drop, "Уходов", "Пётр", "", ""],
                 [with_ticket, "Заявков", "Олег", "", ""]], f"{secrets.token_hex(3)}.csv")
    _mail_ticket(page, with_ticket)  # у записи «таблица» появляется заявка
    only_keep = [[keep, "Остаёнов", "Иван", "", ""]]
    # флажок выключен по умолчанию: подтверждение никого не удаляет
    _upload_preview(page, _table(only_keep), f"{secrets.token_hex(3)}.csv")
    expect(page.locator('form[data-form="import-confirm"] input[name=delete_missing]')).not_to_be_checked()
    summary = _confirm(page)
    _expect_totals(summary, deleted=0)
    for email in (keep, drop, with_ticket):
        expect(_requester(page, email)).to_have_count(1)
    drop_id = _requester_id(page, drop)  # номер записи — до загрузки (потом записи не будет)
    # флажок включён: в предпросмотре сколько будет удалено (одна запись: без заявок и вне файла)
    _upload_preview(page, _table(only_keep), f"{secrets.token_hex(3)}.csv")
    assert re.search(r"\b1\b", page.locator("[data-would-delete]").first.inner_text()), \
        "в предпросмотре нет числа удаляемых (ожидается 1)"
    summary = _confirm(page, delete_missing=True)
    _expect_totals(summary, deleted=1)
    _no_requester(page, drop)
    # событие «удалён загрузкой» по номеру записи: причина из 9.2, без адреса и ФИО (FR-264, FR-288, FR-289)
    rows = helpers_org.audit_rows(page, "requester.deleted", drop_id)
    assert len(rows) == 1, f"ожидалось одно событие удаления записи {drop_id}: {rows!r}"
    assert "загрузка таблицы" in rows[0], f"в событии нет причины «загрузка таблицы»: {rows[0]!r}"
    assert drop not in rows[0] and "Уходов" not in rows[0], "в журнале остались адрес или ФИО"
    expect(_requester(page, keep)).to_have_count(1)
    expect(_requester(page, with_ticket)).to_have_count(1)  # с заявкой не удалён


def test_d10_file_refusals_size_rows_type_encoding_missing_email_column_nothing_written(admin_page):
    """Сценарий 10, п. 6: файл больше 2 МБ, больше 2000 строк, не CSV и не XLSX, не в UTF-8 или без колонки «Почта»
    отклоняется понятным сообщением, ничего не записано (FR-265)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    probe = requester_email()
    # больше 2 МБ: любое содержимое, первым проверяется размер
    big = (f"Почта\r\n{probe}\r\n".encode() + b"a" * OVER_SIZE)[:OVER_SIZE]
    assert len(big) == OVER_SIZE
    alert = _upload_refused(page, big, "big.csv")
    expect(alert).to_have_attribute("data-code", "too_big")
    # больше 2000 строк
    many = [requester_email() for _ in range(OVER_ROWS)]
    alert = _upload_refused(page, ("Почта\r\n" + "\r\n".join(many) + "\r\n").encode("utf-8"), "many.csv")
    expect(alert).to_have_attribute("data-code", "too_many_rows")
    # не CSV и не XLSX: архив ZIP без книги
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "это не таблица")
    alert = _upload_refused(page, buffer.getvalue(), "not-table.xlsx", "application/zip")
    expect(alert).to_have_attribute("data-code", "bad_format")
    # не в UTF-8: заголовок и строка в cp1251
    legacy = f"Почта;Фамилия\r\n{probe};Кириллов\r\n".encode("cp1251")
    alert = _upload_refused(page, legacy, "legacy.csv")
    expect(alert).to_have_attribute("data-code", "not_utf8")
    # без колонки «Почта»
    alert = _upload_refused(page, "Фамилия;Имя\r\nИванов;Иван\r\n".encode("utf-8"), "nomail.csv")
    expect(alert).to_have_attribute("data-code", "missing_columns")
    assert "Почта" in alert.inner_text()
    # ничего не записано
    for email in [probe] + many[:2] + many[-1:]:
        _no_requester(page, email)


def test_d10_same_file_again_all_rows_unchanged(admin_page):
    """Сценарий 10, п. 7: тот же файл загружается повторно — все строки «без изменений» (FR-263)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    unit = unique_name("Повтор")
    rows = [[requester_email(), "Первов", "Иван", "Иванович", unit], [requester_email(), "Второв", "Пётр", "", unit],
            [requester_email(), "Третьев", "Олег", "", ""]]
    content = _table(rows)
    _upload_preview(page, content, f"{secrets.token_hex(3)}.csv")
    _confirm(page)
    _upload_preview(page, content, f"{secrets.token_hex(3)}.csv")
    for number in (1, 2, 3):
        expect(_row(page, number)).to_have_attribute("data-row-result", "unchanged")
        expect(_row(page, number)).to_contain_text("без изменений")
    expect(page.locator('tr[data-import-row]:not([data-row-result="unchanged"])')).to_have_count(0)
    summary = _confirm(page)
    _expect_totals(summary, added=0, updated=0, unchanged=3, errors=0)


def test_d10_requesters_page_search_filter_edit_journal_and_delete_with_tickets_refused(admin_page):
    """Сценарий 10, п. 8: на странице «Заявители» администратор ищет по адресу и ФИО (без «е/ё» и регистра),
    фильтрует по подразделению, правит ФИО и подразделение — изменения сохраняются и попадают в журнал; заявителя с
    заявками удалить нельзя (FR-267, FR-288)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    unit_a, unit_b = unique_name("Фильтр-а"), unique_name("Фильтр-б")
    token = secrets.token_hex(3)
    surname = f"Ёжиков{token}"
    mail_a, mail_b, mail_t = requester_email(), requester_email(), requester_email()
    _load(page, [[mail_a, surname, "Иван", "", unit_a], [mail_b, f"Другов{token}", "Пётр", "", unit_b],
                 [mail_t, f"Заявков{token}", "Олег", "", ""]], f"{secrets.token_hex(3)}.csv")
    # поиск по адресу
    expect(_requester(page, mail_a)).to_have_count(1)
    # поиск по ФИО без регистра и «е/ё»: «ежиков…» находит «Ёжиков…»
    _open_requesters(page, q=f"ЕЖИКОВ{token}")
    expect(page.locator("tr[data-requester]")).to_have_count(1)
    expect(page.locator("tr[data-requester] [data-cell=\"email\"]")).to_have_text(mail_a)
    # фильтр по подразделению (значение выбора — по названию пункта)
    _open_requesters(page)
    unit_a_id = page.locator('form[data-form="requesters-filter"] select[name=client_unit] option',
                             has_text=unit_a).get_attribute("value")
    _open_requesters(page, client_unit=unit_a_id)
    rows = page.locator("tr[data-requester]")
    expect(rows).to_have_count(1)
    expect(rows.locator('[data-cell="email"]')).to_have_text(mail_a)
    # правка ФИО и подразделения в слайдере
    record_id = _requester_id(page, mail_a)
    page.locator('a[data-action="requester-edit"]').click()
    form = page.locator('form[data-form="requester"]')
    expect(form).to_be_visible()
    new_surname = f"Правков{token}"
    form.locator("input[name=name]").fill(f"{new_surname} Иван")
    form.locator("select[name=client_unit]").select_option(label=unit_b)
    _post(page, f"/servicedesk/requesters/{record_id}/edit/", lambda: helpers.submit(form))
    row = _requester(page, mail_a)
    expect(row.locator('[data-cell="name"]')).to_contain_text(new_surname)
    expect(row.locator('[data-cell="client-unit"]')).to_contain_text(unit_b)
    # в журнале: подразделение «было → стало» названиями, ФИО — без значений, адреса нет
    sides = helpers_org.audit_sides(page, "requester.updated", record_id)
    assert sides, "правка заявителя не попала в журнал"
    assert unit_a in sides[0][0] and unit_b in sides[0][1], f"было/стало подразделения: {sides[0]!r}"
    text = _journal_text(page, "requester.updated", record_id)
    assert mail_a not in text and new_surname not in text and surname not in text
    # заявителя с заявками удалить нельзя
    _mail_ticket(page, mail_t)
    _requester(page, mail_t).locator('a[data-action="requester-delete"]').click()
    dialog = page.locator('#dialog-root [data-dialog="requester-delete"]')
    expect(dialog).to_be_visible()
    _post(page, "/delete/", lambda: helpers.submit(dialog.locator("form")))
    expect(page.locator('[role=alert][data-code="requester_has_tickets"]').first).to_be_visible()
    expect(_requester(page, mail_t)).to_have_count(1)


def test_d10_upload_journal_events_by_record_number_without_address_or_name_file_not_kept(admin_page):
    """Сценарий 10, п. 9: после загрузки в журнале есть событие загрузки (итоги) и события по каждому добавленному,
    обновлённому и удалённому заявителю — по номеру записи, без адреса и ФИО; файл не хранится (FR-263, FR-288,
    FR-289)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    token = secrets.token_hex(3)
    mail_new, mail_upd, mail_del = requester_email(), requester_email(), requester_email()
    surnames = [f"Журналов{token}", f"Старший{token}", f"Младший{token}", f"Удалёнов{token}"]
    file_name = f"journal-{token}.csv"
    _load(page, [[mail_upd, surnames[1], "Иван", "", ""], [mail_del, surnames[3], "Лев", "", ""]],
          f"seed-{token}.csv")
    number = _upload_preview(page, _table([[mail_new, surnames[0], "Пётр", "", ""],
                                           [mail_upd, surnames[2], "Иван", "", ""]]), file_name)
    summary = _confirm(page)
    _expect_totals(summary, added=1, updated=1)
    # файл не хранится: в браузере проверяем итог выполненной загрузки; хранение файла проверяют серверные тесты
    # (test_file_not_stored_after_parse). Итог выполненной загрузки не содержит ни адресов, ни ФИО строк файла
    page.goto(f"{IMPORT_URL}{number}/")
    expect(page.locator("[data-result-summary]")).to_be_visible()
    body = page.locator("body").inner_text()
    for secret in (mail_new, mail_upd, *surnames):
        assert secret not in body, "в итоге выполненной загрузки остались данные строк файла"
    # удалённый: ручное удаление записи без заявок (флажок удаления у сценария 10 — только в двух тестах со сбросом)
    id_new, id_upd, id_del = (_requester_id(page, m) for m in (mail_new, mail_upd, mail_del))
    _requester(page, mail_del).locator('a[data-action="requester-delete"]').click()
    dialog = page.locator('#dialog-root [data-dialog="requester-delete"]')
    expect(dialog).to_be_visible()
    _post(page, "/delete/", lambda: helpers.submit(dialog.locator("form")))
    _no_requester(page, mail_del)
    # событие загрузки: по номеру загрузки, с именем файла и итогами
    completed = helpers_org.audit_rows(page, "requester_import.completed", number)
    assert len(completed) == 1, "событие загрузки одно по номеру загрузки"
    assert file_name in completed[0]
    # события по записям — по номеру записи; в строках нет ни адресов, ни ФИО
    assert len(helpers_org.audit_rows(page, "requester.created", id_new)) == 1
    assert len(helpers_org.audit_rows(page, "requester.updated", id_upd)) >= 1
    assert len(helpers_org.audit_rows(page, "requester.deleted", id_del)) == 1
    journal = completed + helpers_org.audit_rows(page, "requester.created", id_new) \
        + helpers_org.audit_rows(page, "requester.updated", id_upd) \
        + helpers_org.audit_rows(page, "requester.deleted", id_del)
    for line in journal:
        for secret in (mail_new, mail_upd, mail_del, *surnames):
            assert secret not in line, "в журнале загрузки адрес или ФИО заявителя (FR-289)"


def test_d10_executor_without_settings_right_has_no_page_direct_link_refused_data_only_in_own_tickets(
        admin_page, employee):
    """Сценарий 10, п. 10: исполнитель без права «Настройка сервис-деска» не находит страницу «Заявители», прямая
    ссылка отклоняется (403); данные заявителя он видит только в доступных ему заявках (FR-268)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    token = secrets.token_hex(3)
    account = employee(full_name=f"Тест{token} Иванов Иван")
    sender = requester_email()
    number = _mail_ticket(page, sender)
    record_id = _requester_id(page, sender)
    staff = account.page
    # страницы «Заявители» нет: ни пункта меню «Сервис-деск», ни ссылки раздела
    staff.goto("/")
    expect(staff.locator("#main-menu")).to_be_visible()
    expect(staff.locator('#main-menu a.menu-item[href="/servicedesk/"]')).to_have_count(0)
    # прямые ссылки — 403 (в том числе запись, которая существует)
    for path in ("/servicedesk/requesters/", IMPORT_URL, f"/servicedesk/requesters/{record_id}/edit/",
                 f"/servicedesk/requesters/{record_id}/delete/"):
        assert helpers_org.direct_get(staff, path).status == 403, f"{path}: ожидался отказ 403"
    assert helpers_org.direct_post(staff, IMPORT_URL).status == 403
    # заявка вне его доступа (в очередь он не входит) — 404, данных заявителя нет
    assert helpers_org.direct_get(staff, f"/tickets/{number}/").status == 404
    # участник очереди видит заявителя в карточке своей заявки
    helpers_sd.add_queue_member(page, queue_id, [account.id], q=f"Тест{token}")
    card = helpers_sd.open_ticket(staff, number)
    expect(card.locator('[data-field="requester-email"]')).to_contain_text(sender)
    assert helpers_org.direct_get(staff, "/servicedesk/requesters/").status == 403  # право очередью не заменяется


def test_d10_executor_edit_then_upload_changes_department_in_order_form_does_not_change_record(
        admin_page, employee, new_context):
    """Сценарий 10, п. 11: исполнитель правит подразделение заявителя на «Офис», затем загрузка таблицы приносит
    «Бухгалтерия» — в записи сначала «Офис», затем «Бухгалтерия»; форма с другим подразделением запись не меняет
    (FR-261, FR-263)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    token = secrets.token_hex(3)
    account = employee(full_name=f"Тест{token} Иванов Иван")
    helpers_sd.add_queue_member(page, queue_id, [account.id], q=f"Тест{token}")
    storage, office, accounting = unique_name("Склад"), unique_name("Офис"), unique_name("Бухгалтерия")
    _create_unit(page, office)
    email = requester_email()
    _load(page, [[email, "Перенов", "Иван", "", storage]], f"{secrets.token_hex(3)}.csv")
    assert storage in _cell(_requester(page, email), "client-unit")
    number = _mail_ticket(page, email)
    # исполнитель правит подразделение в заявке -> запись: «Офис»
    _executor_edit(account.page, number, unit=office)
    expect(account.page.locator('[data-field="client-unit"]')).to_contain_text(office)
    expect(_requester(page, email).locator('[data-cell="client-unit"]')).to_contain_text(office)
    # загрузка таблицы приносит «Бухгалтерия» -> запись: «Бухгалтерия»
    _upload_preview(page, _table([[email, "Перенов", "Иван", "", accounting]]), f"{secrets.token_hex(3)}.csv")
    expect(_row(page, 1)).to_have_attribute("data-row-result", "will_update")
    _confirm(page)
    expect(_requester(page, email).locator('[data-cell="client-unit"]')).to_contain_text(accounting)
    # форма заявки с другим подразделением (и тем же адресом) запись не меняет
    guest = new_context().new_page()
    guest.goto("/request/")
    form = guest.locator('form[data-form="request"]')
    expect(form).to_be_visible()
    form.locator("input[name=email]").fill(email)
    form.locator("input[name=name]").fill("Перенов Иван")
    form.locator("select[name=client_unit]").select_option(label=storage)
    form.locator("select[name=category]").select_option(label="Другое")
    form.locator("input[name=subject]").fill(f"Заявка {_word()}")
    form.locator("textarea[name=text]").fill("Не работает монитор")
    form.locator("input[name=consent]").check()
    form.locator("button[type=submit]").click()
    guest.wait_for_url(re.compile(r"/request/done/"))
    row = _requester(page, email)
    expect(row.locator('[data-cell="client-unit"]')).to_contain_text(accounting)
    assert storage not in _cell(row, "client-unit")


def test_d10_upload_page_states_what_data_is_stored_and_why(admin_page):
    """Сценарий 10, п. 12: страница загрузки таблицы заявителей говорит, какие данные хранятся и зачем (FR-266)."""
    page = admin_page
    _open_requesters(page)
    page.locator('a[data-action="requesters-import"]').click()
    page.wait_for_url(re.compile(r"/servicedesk/requesters/import/$"))
    help_text = page.locator("[data-format-help]")
    expect(help_text).to_be_visible()
    assert STORED_TEXT in _norm(help_text.inner_text()), "на странице загрузки нет текста о хранимых данных"
    expect(page.locator('a[data-sample="csv"]')).to_be_visible()
    expect(page.locator('a[data-sample="xlsx"]')).to_be_visible()


def test_d10_mark_ticket_becomes_table_on_upload_and_table_with_tickets_becomes_ticket_on_delete(
        browser, browser_context_args, stand_admin, admin_page):
    """Сценарий 10, п. 13: запись с отметкой «заявка» после загрузки её адреса получает «таблица»; запись «таблица» с
    заявками, чьего адреса нет в файле, при загрузке с флажком удаления не удалена, а получает «заявка» (FR-261,
    FR-263, FR-264)."""
    helpers_sd.reset_stand_and_relogin(browser, browser_context_args, stand_admin, admin_page)
    page = admin_page
    helpers_sd.ensure_ready(page)
    email, other = requester_email(), requester_email()
    _mail_ticket(page, email)
    row = _requester(page, email)
    assert _cell(row, "origin") == "заявка", "запись из письма должна быть с отметкой «заявка»"
    # загрузка приносит адрес -> «таблица»
    _load(page, [[email, "Таблицов", "Иван", "", ""]], f"{secrets.token_hex(3)}.csv")
    assert _cell(_requester(page, email), "origin") == "таблица"
    # загрузка без этого адреса и с флажком: запись с заявкой не удалена, отметка «заявка»
    _upload_preview(page, _table([[other, "Другов", "Пётр", "", ""]]), f"{secrets.token_hex(3)}.csv")
    summary = _confirm(page, delete_missing=True)
    _expect_totals(summary, deleted=0, origin_changed=1)
    row = _requester(page, email)
    assert _cell(row, "origin") == "заявка"
    assert _cell(row, "tickets-count") == "1"
    assert _cell(_requester(page, other), "origin") == "таблица"


def test_d10_archived_department_error_and_duplicate_email_in_other_case_error(admin_page):
    """Сценарий 10, п. 14: строка с подразделением из архива — «ошибка: подразделение в архиве», а повтор той же
    почты в другом регистре — «ошибка: повтор почты» (FR-262, FR-263)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    archived = unique_name("Архивное")
    _create_unit(page, archived)
    _archive_unit(page, archived)
    dup, good = requester_email(), requester_email()
    rows = [[dup, "Первов", "Иван", "", archived], [dup.upper(), "Второв", "Пётр", "", ""],
            [good, "Годнов", "Олег", "", ""]]
    _upload_preview(page, _table(rows), f"{secrets.token_hex(3)}.csv")
    expect(_row(page, 1)).to_have_attribute("data-row-result", "error")
    expect(_row(page, 1).locator("[data-row-reason]")).to_contain_text("ошибка: подразделение в архиве")
    expect(_row(page, 2)).to_have_attribute("data-row-result", "error")
    expect(_row(page, 2).locator("[data-row-reason]")).to_contain_text("ошибка: повтор почты")
    expect(_row(page, 3)).to_have_attribute("data-row-result", "will_add")
    summary = _confirm(page)
    _expect_totals(summary, added=1, errors=2)
    _no_requester(page, dup)
    expect(_requester(page, good)).to_have_count(1)


def test_d10_executor_edit_journal_department_was_became_name_only_field_fact_with_record_number(
        admin_page, employee):
    """Сценарий 10, п. 15: исполнитель правит подразделение и ФИО заявителя — в журнале по подразделению «было /
    стало», по ФИО только факт изменения поля с номером записи, без значений и без адреса (FR-289, FR-288)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    token = secrets.token_hex(3)
    account = employee(full_name=f"Тест{token} Иванов Иван")
    helpers_sd.add_queue_member(page, queue_id, [account.id], q=f"Тест{token}")
    first, second = unique_name("Склад"), unique_name("Офис")
    _create_unit(page, first)
    _create_unit(page, second)
    email = requester_email()
    number = _mail_ticket(page, email)
    record_id = _requester_id(page, email)
    # подразделение: пусто -> первое -> второе
    _executor_edit(account.page, number, unit=first)
    expect(_requester(page, email).locator('[data-cell="client-unit"]')).to_contain_text(first)
    _executor_edit(account.page, number, unit=second)
    expect(_requester(page, email).locator('[data-cell="client-unit"]')).to_contain_text(second)
    sides = helpers_org.audit_sides(page, "requester.updated", record_id)
    assert len(sides) >= 2, f"ожидались события обеих правок подразделения: {sides!r}"
    assert first in sides[0][0] and second in sides[0][1], f"было/стало второй правки: {sides[0]!r}"
    assert first in sides[1][1], f"стало первой правки: {sides[1]!r}"
    # ФИО: «Сохранить и в записи заявителя» — только факт изменения поля
    new_name = f"Исполнителев{token} Иван"
    _executor_edit(account.page, number, name=new_name)
    expect(_requester(page, email).locator('[data-cell="name"]')).to_contain_text(f"Исполнителев{token}")
    sides = helpers_org.audit_sides(page, "requester.updated", record_id)
    assert len(sides) >= 3, f"ожидалось событие правки ФИО: {sides!r}"
    before, after = sides[0]
    assert "ФИО изменено" in after, f"в «стало» нет факта изменения ФИО: {after!r}"
    assert f"Исполнителев{token}" not in before + after and email not in before + after
    assert first not in before + after and second not in before + after, "правка ФИО не меняет подразделение"
    text = _journal_text(page, "requester.updated", record_id)
    assert f"Исполнителев{token}" not in text and email not in text
