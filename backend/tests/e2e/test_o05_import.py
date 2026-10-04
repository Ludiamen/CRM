"""T-2143: сценарий 5 — администратор загружает сотрудников из таблицы (FR-136…142)."""
import io
import re
import secrets
import zipfile
from urllib.parse import quote

from playwright.sync_api import expect

from tests import factories, support_org
from tests.e2e import helpers, helpers_org
from tests.e2e.helpers_org import audit_rows, descendant_li, open_structure, root_id, unique_name

CSV_MIME = "text/csv"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
IMPORT_ID_URL = re.compile(r"/structure/import/(\d+)/$")


# --- помощники файла ---------------------------------------------------------------------------

def _email() -> str:
    """Уникальная почта строки файла (стенд между тестами круга не сбрасывается)."""
    return factories.new_email("imp")


def _root_name(page) -> str:
    """Название корня читается со страницы «Структура» (его могли переименовать другие тесты круга)."""
    open_structure(page)
    rid = root_id(page)
    open_structure(page, rid)
    return helpers_org.card_text(page, "name")


def _user_row(page, email: str):
    """Строка `tr[data-user-email]` списка «Сотрудники» по поиску `q` (все состояния)."""
    page.goto(f"/staff/?q={quote(email)}&state=all")
    return page.locator(f'tr[data-user-email="{email}"]')


def _user_id(page, email: str) -> str:
    """Номер записи по почте: `data-user-id` строки списка."""
    row = _user_row(page, email)
    expect(row).to_have_count(1)
    return row.get_attribute("data-user-id")


def _rows(page, result=None):
    """Строки предпросмотра `tr[data-import-row]` (по результату `data-row-result`, если он назван)."""
    suffix = f'[data-row-result="{result}"]' if result else ""
    return page.locator(f"tr[data-import-row]{suffix}")


def _row(page, number: int):
    """Строка предпросмотра по номеру в файле (с 1, по порядку файла)."""
    return page.locator(f'tr[data-import-row][data-row-number="{number}"]')


def _upload_preview(page, content: bytes, name: str, mime: str = CSV_MIME) -> str:
    """Открывает `/structure/import/`, кладёт файл в `form[data-form="import-upload"]`, ждёт страницу предпросмотра
    `/structure/import/<id>/` и `[data-import-preview]`. Возвращает номер загрузки."""
    page.goto("/structure/import/")
    form = page.locator('form[data-form="import-upload"]')
    expect(form).to_be_visible()
    helpers_org.upload_file(form, content, name=name, mime=mime)
    page.wait_for_url(IMPORT_ID_URL)
    expect(page.locator("[data-import-preview]")).to_be_visible()
    return IMPORT_ID_URL.search(page.url).group(1)


def _confirm(page, *, send_invites: bool) -> str:
    """Подтверждение предпросмотра: флажок «Отправить приглашения сразу» ставится или снимается явно, форма
    `import-confirm` отправляется, ждёт ответ POST и `[data-result-summary]`. Возвращает текст итога."""
    form = page.locator('form[data-form="import-confirm"]')
    box = form.locator('input[type=checkbox][name=send_invites][value="1"]')
    expect(box).to_be_visible()
    if send_invites:
        box.check()
    else:
        box.uncheck()
    with page.expect_response(lambda r: r.request.method == "POST" and IMPORT_ID_URL.search(r.url)):
        form.locator("button[type=submit]").click()
    summary = page.locator("[data-result-summary]")
    expect(summary).to_be_visible()
    return summary.inner_text()


def _summary_text(created: int, skipped: int, errors: int) -> str:
    """Итог дословно по § 10 контракта: «создано N, пропущено M, с ошибками K»."""
    return f"создано {created}, пропущено {skipped}, с ошибками {errors}"


def _dismiss(page, user_id) -> None:
    """Увольняет через интерфейс (диалог `dismiss` в `#dialog-root`, § 9.3 и § 9.8) — подготовка для п. 2."""
    page.goto(f"/staff/{user_id}/")
    page.locator('[data-action="dismiss"]').first.click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    dialog.locator("button[type=submit]").click()
    expect(page.locator("[data-dismissed-badge]").first).to_be_visible()


def _role_with_permission(admin_page, permission: str) -> str:
    """Создаёт роль с одним правом через `/roles/new/` и возвращает её номер."""
    name = unique_name("Только-" + permission.split(".")[0])
    admin_page.goto("/roles/new/")
    form = admin_page.locator('form[action="/roles/new/"]')
    form.locator("[name=name]").fill(name)
    form.locator(f'input[name=permissions][value="{permission}"]').check()
    with admin_page.expect_response(lambda r: r.request.method == "POST" and "/roles/" in r.url):
        form.locator("button[type=submit]").click()
    admin_page.goto("/roles/")
    row = admin_page.locator(f'[data-role-id][data-role-name="{name}"]')
    expect(row).to_have_count(1)
    return row.get_attribute("data-role-id")


def _give_role(admin_page, user_id, role_id) -> None:
    """Добавляет роль записи в форме `…/roles/` карточки (флажок `roles`, значение — номер роли)."""
    admin_page.goto(f"/staff/{user_id}/")
    form = admin_page.locator('form[action$="/roles/"]')
    form.locator(f'input[name=roles][value="{role_id}"]').check()
    with admin_page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/roles/")):
        form.locator("button[type=submit]").click()


# --- тесты -------------------------------------------------------------------------------------

def test_o05_csv_100_rows_preview_then_confirm_result(admin_page):
    """Сценарий 5, п. 1 и 5: CSV (UTF-8, «;») на 100 строк — предпросмотр показывает статус каждой строки, до
    подтверждения ничего не создано; после подтверждения итог «создано 100, пропущено 0, с ошибками 0», записи в
    состоянии «приглашён» с ролью «Сотрудник ИТ» (FR-136, FR-137, FR-139)."""
    page = admin_page
    token = secrets.token_hex(3)
    emails = [_email() for _ in range(100)]
    content = support_org.staff_csv(
        [support_org.staff_row(email=e, last_name=f"Загр{token}{i}", position=f"Инженер {token}")
         for i, e in enumerate(emails)], delimiter=";")

    # п. 1: загрузка и предпросмотр — статус каждой строки
    import_id = _upload_preview(page, content, f"people-{token}.csv")
    assert _rows(page).count() == 100, "в предпросмотре не 100 строк"
    assert _rows(page, "will_create").count() == 100, "не все строки «будет создан»"
    expect(_row(page, 1)).to_contain_text("будет создан")
    expect(_row(page, 100)).to_contain_text("будет создан")
    reason_box = _row(page, 1).locator("[data-row-reason]")
    if reason_box.count():  # у годной строки элемент может не выводиться; если выведен — пуст
        assert reason_box.inner_text().strip() == "", "у годной строки причина не пуста"
    assert page.locator("[data-result-summary]").count() == 0, "итог показан до подтверждения"
    # до подтверждения ничего не создано
    for email in (emails[0], emails[-1]):
        expect(_user_row(page, email)).to_have_count(0)

    # п. 5: подтверждение без приглашений — итог и состояние записей
    page.goto(f"/structure/import/{import_id}/")
    summary = _confirm(page, send_invites=False)
    assert _summary_text(100, 0, 0) in summary, summary
    assert _rows(page, "created").count() == 100
    for email in (emails[0], emails[-1]):
        row = _user_row(page, email)
        expect(row).to_have_count(1)
        expect(row).to_have_attribute("data-state", "invited")
    first_id = _user_id(page, emails[0])
    page.goto(f"/staff/{first_id}/")
    expect(page.locator('[data-roles-group="personal"]')).to_contain_text("Сотрудник ИТ")
    expect(page.locator('[data-field="position"]')).to_contain_text(f"Инженер {token}")


def test_o05_duplicates_dismissed_hint_errors_and_departments_list(admin_page, employee):
    """Сценарий 5, п. 2, 3, 4, 12: повтор почты в файле, почта существующей и уволенной записи, строки без почты
    и с недопустимой почтой, путь с несуществующими отделами, чужой корень и команда в пути — предпросмотр
    помечает каждую, называет новые отделы один раз и «не загружаются» для лишней колонки; после подтверждения
    созданы только годные строки, новые узлы — отделы (FR-138, FR-139)."""
    page = admin_page
    token = secrets.token_hex(3)
    existing = employee(activate=False, full_name=f"Живой{token} Пётр Петрович")
    gone = employee(activate=False, full_name=f"Бывший{token} Иван Иванович")
    _dismiss(page, gone.id)

    root = _root_name(page)
    open_structure(page)
    rid = root_id(page)
    team_name = unique_name("Команда")
    helpers_org.create_unit(page, team_name, kind="team", parent_id=rid)
    net, support = unique_name("Сеть"), unique_name("Поддержка")
    path = f"{root} / {net} / {support}"
    twice, other = _email(), _email()

    def line(**over):
        row = support_org.staff_row(**over)
        row["Роль"] = "Администратор портала"  # лишняя колонка: «не загружается»
        return row

    rows = [
        line(email=twice, last_name=f"Первый{token}"),              # 1: будет создан
        line(email=twice, last_name=f"Повтор{token}"),              # 2: пропущен, почта повторена в файле
        line(email=existing.email),                                  # 3: пропущен, почта есть
        line(email=gone.email),                                      # 4: пропущен, уволен
        line(email=""),                                              # 5: ошибка, нет почты
        line(email="не-почта"),                                      # 6: ошибка, недопустимая почта
        line(email=_email(), unit_path=path),                        # 7: будет создан, новые отделы
        line(email=other, unit_path=path),                           # 8: будет создан, те же отделы
        line(email=_email(), unit_path=f"{unique_name('Чужой')} / Сеть"),  # 9: ошибка, не корень
        line(email=_email(), unit_path=f"{root} / {team_name}"),     # 10: ошибка, команда
    ]
    headers = support_org.STAFF_HEADERS + ("Роль",)
    import_id = _upload_preview(page, support_org.staff_csv(rows, headers=headers), f"mixed-{token}.csv")

    for number, result in ((1, "will_create"), (2, "skipped"), (3, "skipped"), (4, "skipped"), (5, "error"),
                           (6, "error"), (7, "will_create"), (8, "will_create"), (9, "error"), (10, "error")):
        expect(_row(page, number)).to_have_attribute("data-row-result", result)
    # п. 2: повтор, существующая и уволенная почта
    for number in (2, 3, 4):
        expect(_row(page, number)).to_contain_text("пропущен")
        expect(_row(page, number).locator("[data-row-reason]")).to_contain_text("такая почта уже есть")
    expect(_row(page, 4).locator('[data-row-hint="dismissed"]')).to_contain_text("уволен: верните его из карточки")
    assert _row(page, 3).locator('[data-row-hint="dismissed"]').count() == 0, "подсказка «уволен» у живой записи"
    expect(_row(page, 1)).to_contain_text("будет создан")
    # п. 3 и 12: ошибки с причиной по-русски
    for number in (5, 6, 9, 10):
        expect(_row(page, number)).to_contain_text("ошибка")
        reason = _row(page, number).locator("[data-row-reason]").inner_text().strip()
        assert re.search("[А-Яа-яЁё]", reason), f"строка {number}: причина не по-русски: {reason!r}"
    # п. 4: список новых отделов — каждый назван один раз; лишняя колонка названа
    new_units = page.locator("[data-import-new-units]")
    items = new_units.locator("li")
    expect(items).to_have_count(2)  # ровно два новых узла
    for name in (net, support):  # узел может быть выведен полным путём: ищем li, оканчивающийся названием
        ends = [t for t in items.all_inner_texts() if t.strip().endswith(name)]
        assert len(ends) == 1, f"{name}: не один элемент списка новых отделов: {ends}"
    assert team_name not in new_units.inner_text()
    expect(page.locator("[data-import-not-loaded]")).to_contain_text("Роль")
    expect(page.locator("[data-import-not-loaded]")).to_contain_text("не загружаются")
    # до подтверждения отделов нет
    open_structure(page)
    expect(page.locator("[data-unit-tree] a[data-unit-link]", has_text=net)).to_have_count(0)

    # п. 5: подтверждение — итог по строкам
    page.goto(f"/structure/import/{import_id}/")
    summary = _confirm(page, send_invites=False)
    assert _summary_text(3, 3, 4) in summary, summary
    for number, result in ((1, "created"), (2, "skipped"), (3, "skipped"), (4, "skipped"), (5, "error"),
                           (6, "error"), (7, "created"), (8, "created"), (9, "error"), (10, "error")):
        expect(_row(page, number)).to_have_attribute("data-row-result", result)
    expect(_user_row(page, twice)).to_have_count(1)  # дубль не создан второй раз
    expect(_user_row(page, gone.email)).to_have_count(1)
    # п. 4: «Сеть» и «Поддержка» созданы как отделы, «Поддержка» — внутри «Сети», «Сеть» — под корнем
    open_structure(page)
    net_id = helpers_org.unit_id_by_name(page, net)
    support_id = helpers_org.unit_id_by_name(page, support)
    expect(page.locator(f'[data-unit-tree] li[data-unit-id="{net_id}"]')).to_have_attribute("data-kind", "department")
    expect(page.locator(f'[data-unit-tree] li[data-unit-id="{support_id}"]')).to_have_attribute(
        "data-kind", "department")
    expect(descendant_li(page, rid, net_id)).to_have_count(1)
    expect(descendant_li(page, net_id, support_id)).to_have_count(1)
    # члены: человек со строки 8 — участник «Поддержки»
    other_id = _user_id(page, other)
    open_structure(page, support_id)
    expect(helpers_org.member_row(page, other_id)).to_have_count(1)


def test_o05_head_flag_and_invitations_by_checkbox(admin_page, mailpit):
    """Сценарий 5, п. 6 и 7: «да» в колонке «Руководитель» с путём — человек состоит в подразделении и отмечен его
    руководителем, «да» без пути и непонятное значение — ошибки; при снятом флажке «Отправить приглашения сразу»
    писем нет, приглашение уходит позже из карточки; при отмеченном — письма уходят (FR-137, FR-140)."""
    page = admin_page
    token = secrets.token_hex(3)
    root = _root_name(page)
    dept = unique_name("Отдел")
    head_email, member_email, no_unit_email, odd_email = _email(), _email(), _email(), _email()
    rows = [
        support_org.staff_row(email=head_email, last_name=f"Глава{token}", unit_path=f"{root} / {dept}", head="да"),
        support_org.staff_row(email=member_email, last_name=f"Рядовой{token}", unit_path=f"{root} / {dept}",
                              head="нет"),
        support_org.staff_row(email=no_unit_email, head="да"),
        support_org.staff_row(email=odd_email, unit_path=f"{root} / {dept}", head="возможно"),
    ]
    import_id = _upload_preview(page, support_org.staff_csv(rows), f"heads-{token}.csv")
    expect(_row(page, 3)).to_have_attribute("data-row-result", "error")
    expect(_row(page, 4)).to_have_attribute("data-row-result", "error")
    expect(_row(page, 1)).to_have_attribute("data-row-result", "will_create")

    # п. 7: флажок снят — писем нет
    page.goto(f"/structure/import/{import_id}/")
    expect(page.locator('form[data-form="import-confirm"]').get_by_text("Отправить приглашения сразу")).to_be_visible()
    summary = _confirm(page, send_invites=False)
    assert _summary_text(2, 0, 2) in summary, summary
    assert helpers.no_mail(mailpit, head_email, "invitation"), "письмо ушло при снятом флажке"
    assert helpers.no_mail(mailpit, member_email, "invitation"), "письмо ушло при снятом флажке"
    expect(_user_row(page, no_unit_email)).to_have_count(0)  # строки с ошибками не созданы
    expect(_user_row(page, odd_email)).to_have_count(0)

    # п. 6: подразделение создано, руководитель отмечен, второй — участник без отметки
    head_id, member_id = _user_id(page, head_email), _user_id(page, member_email)
    open_structure(page)
    dept_id = helpers_org.unit_id_by_name(page, dept)
    open_structure(page, dept_id)
    head_row = helpers_org.member_row(page, head_id)
    expect(head_row).to_have_attribute("data-mark", "head")
    expect(head_row.locator("[data-mark-label]")).to_have_text("Руководитель")
    expect(helpers_org.member_row(page, head_id, "heads")).to_have_count(1)
    member_row = helpers_org.member_row(page, member_id)
    expect(member_row).to_have_count(1)
    expect(member_row).to_have_attribute("data-mark", "")
    page.goto(f"/staff/{member_id}/")
    expect(page.locator('[data-field="head"]')).to_contain_text(f"Глава{token}")

    # п. 7: приглашение позже — из карточки (срез 001, FR-008)
    page.goto(f"/staff/{member_id}/")
    helpers.open_security_tab(page)
    helpers.submit(page.locator('form[action$="/invite/"]'))
    helpers.wait_mail(mailpit, member_email, "invitation")

    # п. 7: флажок отмечен — письма уходят всем созданным
    first, second = _email(), _email()
    _upload_preview(page, support_org.staff_csv([support_org.staff_row(email=first),
                                                 support_org.staff_row(email=second)]), f"invite-{token}.csv")
    summary = _confirm(page, send_invites=True)
    assert _summary_text(2, 0, 0) in summary, summary
    helpers.wait_mail(mailpit, first, "invitation")
    helpers.wait_mail(mailpit, second, "invitation")


def test_o05_reimport_creates_nothing(admin_page):
    """Сценарий 5, п. 8: тот же файл загружается повторно — все строки «пропущен: такая почта уже есть», итог
    «создано 0», новых записей, отделов и членств нет (FR-139)."""
    page = admin_page
    token = secrets.token_hex(3)
    root = _root_name(page)
    dept = unique_name("Отдел")
    emails = [_email() for _ in range(3)]
    content = support_org.staff_csv([
        support_org.staff_row(email=emails[0], unit_path=f"{root} / {dept}", head="да"),
        support_org.staff_row(email=emails[1], unit_path=f"{root} / {dept}"),
        support_org.staff_row(email=emails[2]),
    ])
    _upload_preview(page, content, f"again-{token}.csv")
    assert _summary_text(3, 0, 0) in _confirm(page, send_invites=False)
    open_structure(page)
    dept_id = helpers_org.unit_id_by_name(page, dept)
    units_before = page.locator("[data-unit-tree] li[data-unit-id]").count()
    open_structure(page, dept_id)
    members_before = helpers_org.unit_card(page).locator("[data-member]").count()
    assert members_before == 2, members_before

    # повторная загрузка того же файла
    _upload_preview(page, content, f"again-{token}.csv")
    assert _rows(page).count() == 3
    assert _rows(page, "skipped").count() == 3, "не все строки «пропущен»"
    for number in (1, 2, 3):
        expect(_row(page, number).locator("[data-row-reason]")).to_contain_text("такая почта уже есть")
    expect(page.locator("[data-import-new-units] li")).to_have_count(0)
    summary = _confirm(page, send_invites=False)
    assert _summary_text(0, 3, 0) in summary, summary
    assert _rows(page, "skipped").count() == 3
    for email in emails:
        expect(_user_row(page, email)).to_have_count(1)
    open_structure(page)
    assert page.locator("[data-unit-tree] li[data-unit-id]").count() == units_before, "появились отделы"
    open_structure(page, dept_id)
    assert helpers_org.unit_card(page).locator("[data-member]").count() == members_before, "появились членства"


def _refused(page, content: bytes, name: str, mime: str, label: str) -> None:
    """Загружает файл и проверяет отказ: страница остаётся `/structure/import/`, `[role=alert]` с русским текстом."""
    page.goto("/structure/import/")
    form = page.locator('form[data-form="import-upload"]')
    expect(form).to_be_visible()
    assert page.locator("[role=alert]").count() == 0
    helpers_org.upload_file(form, content, name=name, mime=mime)
    alert = page.locator("[role=alert]")
    expect(alert.first).to_be_visible()
    assert re.search("[А-Яа-яЁё]", helpers.alert_text(page)), f"{label}: отказ не по-русски"
    assert re.search(r"/structure/import/$", page.url.split("?")[0]), f"{label}: ушли на {page.url}"
    assert page.locator("[data-import-preview]").count() == 0, f"{label}: показан предпросмотр"


def test_o05_xlsx_and_refusals_and_one_permission_refused(admin_page, employee):
    """Сценарий 5, п. 9 и 10: XLSX принимается так же, как CSV; образцы файлов скачиваются; файл больше 1 МБ,
    более 1000 строк, не CSV и не XLSX, не в UTF-8 и без обязательных колонок отказаны сообщением, ничего не
    создано; у администратора только одно из двух прав загрузка и образцы закрыты (FR-136, FR-141)."""
    page = admin_page
    token = secrets.token_hex(3)
    page.goto("/staff/")
    button = page.locator('a[data-action="staff-import"]')
    expect(button).to_have_attribute("href", "/structure/import/")
    expect(button).to_contain_text("Загрузить из таблицы")
    # образцы
    sample = helpers_org.direct_get(page, "/structure/import/sample.csv")
    assert sample.status == 200 and sample.headers["content-type"].startswith("text/csv"), sample.status
    assert "attachment" in sample.headers["content-disposition"]
    body = sample.body()
    assert body.startswith(b"\xef\xbb\xbf"), "образец CSV без BOM (UTF-8 с BOM, § 4.7)"
    first_line = body.decode("utf-8-sig").splitlines()[0]
    assert ";" in first_line and "Почта" in first_line, f"заголовок образца: {first_line!r}"
    sample = helpers_org.direct_get(page, "/structure/import/sample.xlsx")
    assert sample.status == 200 and XLSX_MIME in sample.headers["content-type"], sample.status
    assert "attachment" in sample.headers["content-disposition"]

    # XLSX: предпросмотр и итог
    xlsx_emails = [_email() for _ in range(3)]
    content = support_org.staff_xlsx([support_org.staff_row(email=e) for e in xlsx_emails])
    _upload_preview(page, content, f"people-{token}.xlsx", XLSX_MIME)
    assert _rows(page, "will_create").count() == 3
    assert _summary_text(3, 0, 0) in _confirm(page, send_invites=False)
    for email in xlsx_emails:
        expect(_user_row(page, email)).to_have_count(1)

    # п. 9: отказы
    refused_emails = [_email() for _ in range(6)]
    one = lambda i, **over: support_org.staff_row(email=refused_emails[i], **over)  # noqa: E731
    plain_zip = io.BytesIO()
    with zipfile.ZipFile(plain_zip, "w") as archive:
        archive.writestr("readme.txt", "не таблица")
    cp1251 = support_org.staff_csv([one(4)]).decode("utf-8-sig").encode("cp1251")
    many = support_org.staff_csv([one(1)] + [support_org.staff_row() for _ in range(1000)])
    cases = [
        ("больше 1 МБ", support_org.staff_csv([one(0, position="x" * 1_100_000)]), "big.csv", CSV_MIME),
        ("больше 1000 строк", many, "many.csv", CSV_MIME),
        ("не CSV и не XLSX", b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4, "picture.csv", CSV_MIME),
        ("ZIP, но не XLSX", plain_zip.getvalue(), "archive.xlsx", XLSX_MIME),
        ("не UTF-8", cp1251, "win.csv", CSV_MIME),
        ("без обязательных колонок",
         support_org.staff_csv([[refused_emails[5], "Тестов"]], headers=("Почта", "Фамилия")), "short.csv", CSV_MIME),
    ]
    for label, data, name, mime in cases:
        _refused(page, data, name, mime, label)
    for email in refused_emails:
        expect(_user_row(page, email)).to_have_count(0)

    # п. 10: одно из двух прав — отказ (403) и в загрузке, и в образцах
    for permission in ("accounts.manage", "org.manage"):
        account = employee()
        role_id = _role_with_permission(page, permission)
        _give_role(page, account.id, role_id)
        other = account.page
        assert other.goto("/structure/import/").status == 403, f"{permission}: загрузка открыта"
        for path in ("/structure/import/sample.csv", "/structure/import/sample.xlsx"):
            assert helpers_org.direct_get(other, path).status == 403, f"{permission}: {path}"
        assert helpers_org.direct_post(other, "/structure/import/").status == 403, permission
        other.goto("/staff/")
        expect(other.locator('a[data-action="staff-import"]')).to_have_count(0)


def test_o05_journal_has_import_and_object_events(admin_page, stand_admin):
    """Сценарий 5, п. 11: после загрузки в журнале есть событие загрузки (кто, файл, итоги) без содержимого файла
    и отдельные события создания каждой записи, отдела и членства (FR-142)."""
    page = admin_page
    token = secrets.token_hex(3)
    root = _root_name(page)
    dept = unique_name("Отдел")
    head_email, member_email = _email(), _email()
    marker = f"Метка{token}"
    file_name = f"journal-{token}.csv"
    content = support_org.staff_csv([
        support_org.staff_row(email=head_email, last_name=f"Журнальный{token}", position=marker,
                              unit_path=f"{root} / {dept}", head="да"),
        support_org.staff_row(email=member_email, last_name=f"Участник{token}", position=marker,
                              unit_path=f"{root} / {dept}"),
    ])
    import_id = _upload_preview(page, content, file_name)
    assert _summary_text(2, 0, 0) in _confirm(page, send_invites=False)
    head_id, member_id = _user_id(page, head_email), _user_id(page, member_email)
    open_structure(page)
    dept_id = helpers_org.unit_id_by_name(page, dept)

    # событие загрузки: файл и итоги, без содержимого файла, без латинских ключей
    done = audit_rows(page, "staff_import.completed", import_id)
    assert len(done) == 1, done
    text = done[0]
    for forbidden in (head_email, member_email, marker, f"Журнальный{token}", f"Участник{token}"):
        assert forbidden not in text, f"в событии загрузки лишнее: {forbidden}"
    for key in ("file_name", "send_invites", "created", "skipped", "errors", "units_created"):
        assert not re.search(rf"\b{key}\b", text), f"латинский ключ {key} в тексте строки: {text!r}"
    sides = helpers_org.audit_sides(page, "staff_import.completed", import_id)
    assert len(sides) == 1, sides
    _before, after = sides[0]
    assert file_name in after, f"в «стало» нет имени файла: {after!r}"
    # итоги числами по-русски, «название: число» (доп. 29): создано 2, пропущено 0, ошибок 0, создано отделов 1
    numbers = sorted(int(n) for n in re.findall(r"[А-Яа-яЁё][^:;\n]*:\s*(\d+)(?=\s*(?:;|$))", after, re.M))
    assert numbers == [0, 0, 1, 2], f"итоги загрузки в «стало»: {after!r}"
    who = page.locator('tr[data-event-id][data-action="staff_import.completed"]').first.locator("td").nth(1)
    expect(who).to_contain_text(stand_admin.full_name)
    # отдельные события: запись, отдел, членство
    for user_id in (head_id, member_id):
        assert len(audit_rows(page, "user.created", user_id)) == 1, f"user.created для {user_id}"
        added = audit_rows(page, "membership.added", user_id)
        assert len(added) == 1 and dept in added[0], f"membership.added для {user_id}: {added}"
    created = audit_rows(page, "unit.created", dept_id)
    assert len(created) == 1 and dept in created[0], created
