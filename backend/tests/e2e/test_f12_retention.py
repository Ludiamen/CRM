"""T-7151: сценарий 12 — срок хранения записей ленты и ночное задание (FR-638, FR-639, FR-642, NFR-606, NFR-610).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-007.md разделы 8, 10.2, 12, 13, 14.2, решения 54 и 57 задач):
- управляющий — администратор круга `admin_page`: у него «Менять настройки портала» и «Писать всем» (миграция данных
  выдаёт его начальной роли), записи ленты он публикует формой `helpers_feed.publish`; читающие, комментирующие и
  отмечающие — сотрудники `employee`, их действия идут прямыми запросами тех же форм (`helpers_org.direct_post` с
  токеном CSRF их страницы): это подготовка данных, а не предмет проверки;
- время на стенде не подменяется. Единственный рычаг — `helpers_feed.age(days, posts=[…])`: `published_at` названных
  записей сдвигается на N суток назад и в той же команде отрабатывает ночное задание (решение 54). Остальные записи
  круга свежие и задание их не трогает; каждый тест называет только свои записи;
- «3 года и 1 день» считается календарно по Москве от сегодняшней даты (замена года, 29 февраля → 28 февраля, как в
  плане «Граница срока»), а не как 365 × 3 + 1;
- «удалена со всем, что к ней относится» проверяется по видимому из браузера: карточка записи, списки отметивших,
  прочитавших и ответивших, список отметивших комментарий и файл записи отвечают 404 (до удаления — 200, это контроль);
  строки таблиц базы проверяют серверные тесты T-7115;
- срок хранения меняет администратор круга; каждый тест, который его меняет, возвращает 3 в `finally`;
- в журнале читается первая строка (`helpers_org.audit_sides`, новые сверху): «было» и «стало» — текст ячеек таблицы
  журнала, подпись ключа — раздел 8.2 контракта («срок хранения, лет», «Удалено по сроку, записей»);
- сброса стенда в файле нет.
"""
import re
import secrets
from datetime import datetime, timedelta, timezone

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_feed as feed, helpers_org

SETTINGS = "/settings/feed/"
TITLE = "Настройки портала → Лента"
LABEL = "Хранить записи ленты, лет"
RANGE_TEXT = "Срок хранения — от 1 до 10 лет"
CONFIRM = "Ближайшее ночное задание удалит записей:"
PURGED_LABEL = "Удалено по сроку, записей"
YEARS_LABEL = re.compile(r"срок хранения, лет:\s*(\d+)", re.IGNORECASE)
MOSCOW = timezone(timedelta(hours=3))
DEFAULT_YEARS = 3


# --- Общие помощники файла ------------------------------------------------------------------------------------

def _marker() -> str:
    """Уникальное слово текста: по нему запись находится в ленте и отсутствует в журнале."""
    return f"Срок{secrets.token_hex(4)}"


def _term_days(years: int) -> int:
    """Сколько суток в `years` календарных годах до сегодняшней даты по Москве (замена года; 29 февраля → 28)."""
    today = datetime.now(MOSCOW).date()
    try:
        past = today.replace(year=today.year - years)
    except ValueError:
        past = today.replace(year=today.year - years, day=28)
    return (today - past).days


def _open_settings(page) -> None:
    page.goto(SETTINGS)
    expect(page.locator('[data-feed-page="settings"]')).to_be_visible()


def _years_form(page):
    return page.locator('[data-feed-page="settings"] form:has(input[name="retention_years"])').first


def _years_value(page) -> str:
    _open_settings(page)
    return page.locator('input[name="retention_years"]').first.input_value()


def _submit_years(page, value) -> None:
    """Вводит `value` в «Хранить записи ленты, лет» и нажимает кнопку формы. Проверку браузера (`min`, `max`, тип
    «число») снимаем: проверяется отказ сервера, а не подсказка поля; ждёт ответ POST."""
    form = _years_form(page)
    field = form.locator('input[name="retention_years"]')
    field.evaluate("el => { el.type = 'text'; el.removeAttribute('min'); el.removeAttribute('max'); }")
    form.evaluate("f => { f.noValidate = true; }")
    field.fill(str(value))
    with page.expect_response(lambda r: r.request.method == "POST" and SETTINGS in r.url):
        form.locator('button:not([type="button"])').first.click()
    page.wait_for_load_state()


def _confirm_years(page) -> None:
    """Второй шаг: «Подтвердить» (`button[name=confirm][value=1]` в `[data-feed-confirm]`); ждёт ответ POST."""
    button = page.locator('[data-feed-confirm] button[name="confirm"][value="1"]')
    expect(button).to_be_visible()
    with page.expect_response(lambda r: r.request.method == "POST" and SETTINGS in r.url):
        button.click()
    page.wait_for_load_state()


def _warning_count(page) -> int:
    """Число из «Ближайшее ночное задание удалит записей: N» второго шага."""
    confirm = page.locator("[data-feed-confirm]")
    expect(confirm).to_be_visible()
    expect(confirm).to_contain_text(CONFIRM)
    found = re.search(re.escape(CONFIRM) + r"\s*(\d+)", confirm.inner_text())
    assert found, f"в предупреждении нет числа записей: {confirm.inner_text()!r}"
    return int(found.group(1))


def _restore_years(page, current: int) -> None:
    """Возвращает срок 3 (в `finally`): уменьшение идёт через «Подтвердить», увеличение — сразу."""
    if current == DEFAULT_YEARS:
        return
    _open_settings(page)
    _submit_years(page, DEFAULT_YEARS)
    if current > DEFAULT_YEARS:
        _confirm_years(page)


def _open_home(page) -> None:
    page.goto("/")
    page.wait_for_load_state()
    expect(page.locator('[data-feed-page="home"]')).to_be_visible()


def _admin_post(page, text: str, **kwargs) -> int:
    """Администратор публикует запись формой (по умолчанию «Всем»; у него есть «Писать всем»); номер записи."""
    _open_home(page)
    return feed.publish(page, text, **kwargs)


def _event(days_ahead: int = 2) -> dict:
    start = datetime.now(MOSCOW).replace(tzinfo=None, second=0, microsecond=0) + timedelta(days=days_ahead)
    return {"title": f"Событие {secrets.token_hex(3)}", "place": "Переговорная", "start": start,
            "end": start + timedelta(hours=1)}


def _status(page, path: str) -> int:
    return helpers_org.direct_get(page, path).status


def _gone(page, path: str) -> None:
    assert _status(page, path) == 404, f"{path}: после удаления по сроку ожидался 404"


def _alive(page, path: str) -> None:
    assert _status(page, path) == 200, f"{path}: до удаления ожидался 200"


def _post_ok(page, path: str, data: dict | None = None) -> None:
    """Подготовка данных запросом формы сотрудника: обычный POST — 302."""
    response = helpers_org.direct_post(page, path, data)
    assert response.status == 302, f"{path}: ожидался 302, получен {response.status}"


def _comment_id(page, post_id: int) -> str:
    page.goto(f"/feed/{post_id}/")
    page.wait_for_load_state()
    node = page.locator(f"#feed-post-{post_id} [data-comment-id]").first
    expect(node).to_be_attached()
    return node.get_attribute("data-comment-id")


# --- Настройка срока (сценарий 12, п. 1–3) -----------------------------------------------------------------------

def test_f12_new_install_feed_settings_page_shows_keep_posts_3_years(admin_page, employee):
    """Сценарий 12, п. 1: новая установка — на странице «Настройки портала → Лента» «Хранить записи ленты, лет» равно
    3; страница — по пункту меню «Настройки ленты» администратора; у сотрудника без права пункта нет (FR-638)."""
    page = admin_page
    page.goto("/")
    item = page.locator('#main-menu a.menu-item[href="/settings/feed/"]')
    expect(item).to_have_count(1)
    expect(item).to_contain_text("Настройки ленты")
    item.click()
    page.wait_for_url(re.compile(r"/settings/feed/$"))
    expect(page.locator('[data-feed-page="settings"]')).to_contain_text(TITLE)
    field = page.get_by_label(LABEL)
    expect(field).to_have_count(1)
    expect(field).to_have_value("3")
    assert _years_value(page) == "3"


def test_f12_retention_0_11_or_not_a_number_is_refused_with_reason_and_value_kept(admin_page):
    """Сценарий 12, п. 2: 0, 11 и не число — отказ «Срок хранения — от 1 до 10 лет» у поля, значение прежнее
    (FR-638, FR-642)."""
    page = admin_page
    for bad in ("0", "11", "три"):
        _open_settings(page)
        _submit_years(page, bad)
        refusal = page.locator('[data-error="retention_years"][data-code="retention_range"]')
        expect(refusal).to_be_visible()
        expect(refusal).to_contain_text(RANGE_TEXT)
        assert _years_value(page) == "3", f"после отказа на {bad!r} срок изменился"


def test_f12_decrease_from_3_to_1_shows_warning_with_number_of_posts_night_job_will_delete_and_confirm(admin_page):
    """Сценарий 12, п. 3: уменьшение 3 → 1 — второй шаг «Ближайшее ночное задание удалит записей: N» с кнопкой
    «Подтвердить»; N вырастает ровно на число записей старше года (две записи состарены на 400 суток; записи моложе
    года и записи старше трёх лет, удалённые заданием, в число не входят), после «Подтвердить» срок — 1 (FR-638)."""
    page = admin_page
    current = 3
    try:
        _open_settings(page)
        _submit_years(page, 1)
        base = _warning_count(page)
        expect(page.locator('[data-feed-confirm] button[name="confirm"][value="1"]')).to_contain_text("Подтвердить")
        old_ids = [_admin_post(page, f"{_marker()} старая {n}") for n in (1, 2)]
        fresh_id = _admin_post(page, f"{_marker()} свежая")
        assert feed.age(400, posts=old_ids)["aged"] == 2  # 400 суток меньше трёх лет: задание их не удаляет
        _open_settings(page)
        _submit_years(page, 1)
        assert _warning_count(page) == base + 2, "в предупреждении не те записи: ждали две состаренные, свежая не входит"
        _confirm_years(page)
        current = 1
        assert _years_value(page) == "1"
        _alive(page, f"/feed/{fresh_id}/")  # свежая запись срок в 1 год не затрагивает
    finally:
        _restore_years(page, current)


def test_f12_decrease_without_confirm_leaves_retention_unchanged(admin_page):
    """Сценарий 12, п. 3: уменьшение без «Подтвердить» значение не меняет и в журнал ничего не пишет (FR-638)."""
    page = admin_page
    before = len(helpers_org.audit_rows(page, "feed.retention_changed", object_id="1"))
    _open_settings(page)
    _submit_years(page, 1)
    _warning_count(page)
    assert _years_value(page) == "3", "срок изменился без подтверждения"
    _open_settings(page)
    _submit_years(page, 2)
    _warning_count(page)
    page.goto("/")  # уход со страницы вместо «Подтвердить»
    assert _years_value(page) == "3", "срок изменился после ухода со второго шага"
    after = len(helpers_org.audit_rows(page, "feed.retention_changed", object_id="1"))
    assert after == before, "без подтверждения в журнале появилась запись об изменении срока"


def test_f12_confirmed_decrease_appears_in_journal_as_years_before_after(admin_page):
    """Сценарий 12, п. 3: подтверждённое уменьшение 3 → 1 — в журнале событие `feed.retention_changed` с «было 3,
    стало 1» (FR-638, FR-639)."""
    page = admin_page
    current = 3
    try:
        _open_settings(page)
        _submit_years(page, 1)
        _warning_count(page)
        _confirm_years(page)
        current = 1
        sides = helpers_org.audit_sides(page, "feed.retention_changed", object_id="1")
        assert sides, "в журнале нет события feed.retention_changed"
        was, became = sides[0]
        assert YEARS_LABEL.search(was) and YEARS_LABEL.search(was).group(1) == "3", f"«было»: {was!r}"
        assert YEARS_LABEL.search(became) and YEARS_LABEL.search(became).group(1) == "1", f"«стало»: {became!r}"
        row = page.locator('tr[data-event-id][data-action="feed.retention_changed"]').first
        expect(row).to_contain_text("Срок хранения ленты изменён")
    finally:
        _restore_years(page, current)


def test_f12_increase_is_saved_at_once_without_confirm(admin_page):
    """Сценарий 12: увеличение срока 3 → 5 сохраняется сразу, без второго шага; в журнале — «было 3, стало 5»
    (FR-638)."""
    page = admin_page
    current = 3
    try:
        _open_settings(page)
        _submit_years(page, 5)
        current = 5
        expect(page.locator("[data-feed-confirm]")).to_have_count(0)
        assert _years_value(page) == "5"
        was, became = helpers_org.audit_sides(page, "feed.retention_changed", object_id="1")[0]
        assert YEARS_LABEL.search(was).group(1) == "3", f"«было»: {was!r}"
        assert YEARS_LABEL.search(became).group(1) == "5", f"«стало»: {became!r}"
    finally:
        _restore_years(page, current)


# --- Ночное задание (сценарий 12, п. 4–5) -------------------------------------------------------------------------

def test_f12_post_aged_3_years_and_1_day_is_deleted_by_night_job_with_comments_files_likes_reads_and_event_answers(
        admin_page, employee, tmp_path):
    """Сценарий 12, п. 4: две записи (важная — с файлом, комментарием, «Нравится» записи и комментарию и «Прочитано»;
    событие — с ответом «Пойду») опубликованы 3 года и 1 день назад; после ночного задания обе удалены, а карточки,
    списки отметивших, прочитавших и ответивших, список отметивших комментарий и файл отвечают 404; до задания — 200
    (FR-638)."""
    page = admin_page
    reader = employee()
    marker = _marker()
    png = tmp_path / "retention.png"
    png.write_bytes(helpers.make_png(64, 64))
    important_id = _admin_post(page, f"{marker} важная", kind="important", term="day", files=(png,))
    event_id = _admin_post(page, f"{marker} событие", kind="event", event=_event())
    file_id = page.locator(f"#feed-post-{important_id}-files [data-feed-file]").first.get_attribute("data-feed-file")
    feed.wait_clean(page, file_id)  # контроль до удаления: чистый файл отдаётся, а не «проверяется»

    _post_ok(reader.page, f"/feed/{important_id}/comments/", {"text": f"{marker} комментарий"})
    comment_id = _comment_id(page, important_id)
    _post_ok(reader.page, f"/feed/{important_id}/like/")
    _post_ok(reader.page, f"/feed/comments/{comment_id}/like/")
    _post_ok(reader.page, f"/feed/{important_id}/read/")
    _post_ok(reader.page, f"/feed/{event_id}/answer/", {"answer": "go"})

    controls = [f"/feed/{important_id}/", f"/feed/{event_id}/", f"/feed/{important_id}/reads/",
                f"/feed/{important_id}/likes/", f"/feed/comments/{comment_id}/likes/",
                f"/feed/{event_id}/answers/", f"/feed/files/{file_id}/"]
    for path in controls:
        _alive(page, path)

    result = feed.age(_term_days(3) + 1, posts=[important_id, event_id])
    assert result["aged"] == 2 and result["deleted"] >= 2, f"ночное задание: {result}"
    for path in controls:
        _gone(page, path)
    _gone(reader.page, f"/feed/{important_id}/")
    _open_home(page)
    expect(page.locator(f"#feed-post-{important_id}")).to_have_count(0)
    expect(page.locator(f"#feed-post-{event_id}")).to_have_count(0)


def test_f12_post_aged_less_than_term_is_kept_by_night_job(admin_page):
    """Сценарий 12: запись, опубликованная на сутки позже границы срока (3 года без 1 дня назад), ночным заданием не
    удаляется; она видна в ленте (FR-638)."""
    page = admin_page
    marker = _marker()
    post_id = _admin_post(page, f"{marker} почти три года")
    result = feed.age(_term_days(3) - 1, posts=[post_id])
    assert result["aged"] == 1, f"ночное задание: {result}"
    _alive(page, f"/feed/{post_id}/")
    _open_home(page)
    expect(page.locator(f"#feed-post-{post_id}")).to_have_count(1)


def test_f12_old_post_edited_and_commented_recently_is_deleted_by_term_from_publication(admin_page, employee):
    """Сценарий 12 (FR-638): правка и новые комментарии срок не продлевают — запись, опубликованная 3 года и 1 день
    назад, но правленая и прокомментированная только что, удаляется (срок считается от публикации)."""
    page = admin_page
    reader = employee()
    marker = _marker()
    post_id = _admin_post(page, f"{marker} исходный текст")
    page.goto(f"/feed/{post_id}/edit/")
    form = page.locator('[data-feed-page="edit"] form').first
    form.locator('textarea[name="text"]').fill(f"{marker} исправленный текст")
    with page.expect_response(lambda r: r.request.method == "POST" and f"/feed/{post_id}/edit/" in r.url):
        form.locator('button:not([type="button"])').first.click()
    page.wait_for_load_state()
    _post_ok(reader.page, f"/feed/{post_id}/comments/", {"text": f"{marker} свежий комментарий"})
    page.goto(f"/feed/{post_id}/")
    expect(page.locator(f"#feed-post-{post_id} [data-feed-edited]")).to_have_count(1)  # контроль: правка записана
    expect(page.locator(f"#feed-post-{post_id} [data-comment-id]")).to_have_count(1)

    result = feed.age(_term_days(3) + 1, posts=[post_id])
    assert result["aged"] == 1 and result["deleted"] >= 1, f"ночное задание: {result}"
    _gone(page, f"/feed/{post_id}/")


def test_f12_old_post_of_dismissed_employee_is_deleted_by_same_term(admin_page, employee, new_context):
    """Сценарий 12 (FR-638): запись уволенного сотрудника удаляется по тому же сроку: до задания она видна в ленте
    с пометкой «уволен» (контроль), после — карточка отвечает 404."""
    page = admin_page
    role = feed.make_role(page, [feed.POST_ALL])
    author = employee(role=role, full_name=f"Уволенов{secrets.token_hex(3)} Пётр Петрович")
    author_page = feed.open_feed(new_context(), author)
    post_id = feed.publish(author_page, f"{_marker()} запись уволенного")

    page.goto(f"/staff/{author.id}/")
    page.locator(f'[data-card][data-user-id="{author.id}"] [data-action="dismiss"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(page.locator(f'[data-card][data-user-id="{author.id}"] [data-dismissed-badge]')).to_be_visible()

    _open_home(page)
    expect(page.locator(f'#feed-post-{post_id} [data-feed-author] span[data-dismissed="true"]')).to_have_count(1)
    result = feed.age(_term_days(3) + 1, posts=[post_id])
    assert result["aged"] == 1 and result["deleted"] >= 1, f"ночное задание: {result}"
    _gone(page, f"/feed/{post_id}/")
    _open_home(page)
    expect(page.locator(f"#feed-post-{post_id}")).to_have_count(0)


def test_f12_night_job_journal_shows_deleted_by_retention_posts_count_without_text(admin_page):
    """Сценарий 12, п. 4: в журнале — «Удалено по сроку, записей: N» (N — число удалённых этим запуском) без текста
    записи; запись события — `feed.retention_purged` без исполнителя («система») (FR-639)."""
    page = admin_page
    marker = _marker()
    post_id = _admin_post(page, f"{marker} секретный текст записи")
    result = feed.age(_term_days(3) + 1, posts=[post_id])
    assert result["deleted"] >= 1, f"ночное задание: {result}"
    sides = helpers_org.audit_sides(page, "feed.retention_purged", object_id="1")
    assert sides, "в журнале нет события feed.retention_purged"
    _, became = sides[0]
    assert re.search(re.escape(PURGED_LABEL) + r":\s*" + str(result["deleted"]) + r"\b", became), f"«стало»: {became!r}"
    row = page.locator('tr[data-event-id][data-action="feed.retention_purged"]').first
    expect(row).to_contain_text("Записи ленты удалены по сроку")
    expect(row).to_contain_text("система")
    assert marker not in row.inner_text(), "в журнале есть текст записи"
    assert marker not in helpers.audit_text(page), "текст записи попал в журнал"


def test_f12_repeated_night_job_deletes_nothing_adds_no_journal_entry_and_gives_no_error(admin_page):
    """Сценарий 12, п. 5: повтор ночного задания (`age(1, posts=[свежая запись теста])`: запись сдвигается на сутки и
    не старше срока) ничего не удаляет, нового события в журнале нет, команда без ошибки (FR-638, FR-639, NFR-610)."""
    page = admin_page
    old_id = _admin_post(page, f"{_marker()} старая")
    fresh_id = _admin_post(page, f"{_marker()} свежая")
    first = feed.age(_term_days(3) + 1, posts=[old_id])
    assert first["deleted"] >= 1
    journal = len(helpers_org.audit_rows(page, "feed.retention_purged", object_id="1"))
    assert journal >= 1, "первый запуск журнала не записал: нечего сравнивать"

    repeated = feed.age(1, posts=[fresh_id])  # ошибка команды — AssertionError помощника `_stand_command`
    assert repeated == {"aged": 1, "deleted": 0}, f"повтор: {repeated}"
    assert len(helpers_org.audit_rows(page, "feed.retention_purged", object_id="1")) == journal, \
        "повтор ночного задания добавил запись в журнал"
    _alive(page, f"/feed/{fresh_id}/")


# --- Права и узкий экран ---------------------------------------------------------------------------------------

def test_f12_feed_settings_page_without_portal_settings_right_is_forbidden(admin_page, employee):
    """Сценарий 12 (FR-638): без права «Менять настройки портала» `/settings/feed/` — 403 на GET и на POST, пункта
    меню нет; срок после запроса прежний; у администратора пункт есть (контроль)."""
    page = admin_page
    staff = employee()
    page.goto("/")
    expect(page.locator('#main-menu a[href="/settings/feed/"]')).to_have_count(1)

    assert staff.page.goto(SETTINGS).status == 403
    staff.page.goto("/")
    expect(staff.page.locator('#main-menu a[href="/settings/feed/"]')).to_have_count(0)
    response = helpers_org.direct_post(staff.page, SETTINGS, {"retention_years": "1", "confirm": "1"})
    assert response.status == 403, f"POST без права: ожидался 403, получен {response.status}"
    assert _years_value(page) == "3", "запрос без права изменил срок"


def test_f12_feed_settings_page_and_decrease_warning_do_not_widen_page_at_360px(admin_page):
    """Сценарий 12, NFR-606: на ширине 360 px страница настройки и второй шаг с предупреждением — без горизонтальной
    прокрутки страницы."""
    page = admin_page
    _open_settings(page)
    assert feed.check_360(page)
    _submit_years(page, 1)
    _warning_count(page)
    assert feed.check_360(page)
    assert _years_value(page) == "3"
