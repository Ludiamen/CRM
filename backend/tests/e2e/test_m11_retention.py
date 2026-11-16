"""T-8141: приёмка сценария 11 — срок хранения сообщений (FR-670, FR-671, NFR-706).

Приёмка SPEC-008, сценарий 11: сообщение старше срока после ночного задания удаляется вместе с файлами, в журнале —
запись без текста переписки (п. 1); повтор задания ничего не удаляет, ошибок и лишних записей журнала нет (п. 2);
уменьшение срока сохраняется только после второго шага с подтверждением и пишется в журнал «было / стало» (п. 3);
удалённого по сроку сообщения нет в беседе, а прямой запрос правки отклоняется (п. 4).

Общее для файла (CONTRACT-008.md, разделы 8.1, 8.2, 10.2, 12.1, 12.3, 12.6, 13.2, 13.3, 14.1, 14.3; PLAN-008,
«Срок хранения и ночное задание», «Проход в браузере»; TASKS-008 T-8141; образец — `test_f12_retention.py` среза 007):
- люди — `helpers_messenger.messenger_cast` (фикстура `circle`: девять учёток и три узла один раз на круг браузера,
  дальше берутся сохранённые сессии `Account.storage_state`); нужны двое — `writer` (автор) и `peer` (собеседник);
- время двигает только `helpers_messenger.age(days)` — команда стенда `e2e_messenger_age --days N` (14.1): она
  сдвигает `created_at` всех сообщений стенда на N суток назад и служб не трогает. Поэтому файл идёт в алфавитном
  порядке после m01–m10, а m12/m13 создают свои сообщения заново; контроля «свежее сообщение цело» это не отменяет —
  оно создаётся уже после задания;
- ночное задание в приёмке запускается тем же кодом, что стоит в расписании: `apps.messenger.tasks.retention_night()`
  через `manage.py shell` в контейнере `web` (`helpers.stand_shell`; правка базы и вызов службы в приёмочных тестах
  стенда разрешены решением Opus, CONTRACT.md, «Решения Opus по вопросам этапа 2в»). Ждать 23:55 МСК (cron
  `55 23 * * *`, раздел 1.2) нельзя; сам вызов возвращает число удалённых сообщений — по нему сверяется запись
  журнала. Отдельной команды стенда для ночного задания мессенджера контракт не заводит (14.1 называет только `age`);
- «3 года и 1 день» считается календарно по Москве от сегодняшней даты (замена года, 29 февраля → 28 февраля —
  план, «Граница срока»), а не как 365 × 3 + 1;
- удаление проверяется по видимому из браузера: сообщения нет в истории (`#messenger-messages`, 12.3), оригинал и
  эскиз файла отвечают 404; строки таблиц и стирание диска проверяют серверные тесты T-8119;
- журнал читается страницами портала (`helpers_org.audit_rows`, `audit_sides`, фильтр по коду и объекту
  `messenger.settings`/`1`, 8.1): «Удалено по сроку, сообщений: N» и «срок хранения, лет» — подписи 8.2; текста
  переписки в журнале нет (FR-671) — по уникальному слову сообщения;
- настройки (`/settings/messenger/`, 10.2, 12.6): уменьшение срока — второй шаг `[data-messenger-confirm]`
  («Ближайшее ночное задание удалит сообщений: N», кнопка «Подтвердить» `button[name="confirm"][value="1"]`, скрытое
  `retention_years`), без него значение и журнал прежние; увеличение сохраняется сразу; каждый тест возвращает срок 3
  в `finally`, чтобы не менять условия соседним сценариям;
- отказы прямых запросов — `helpers_org.direct_post` от имени страницы (её сессия и CSRF, без переходов по
  редиректам): 404 удалённого по сроку сообщения — это «не найдено», а не 403;
- секретов и ПДн нет: ФИО вымышленные, файлы — картинка `helpers.make_png`, тексты — вымышленные.
"""
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers, helpers_messenger, helpers_org

SETTINGS_URL = "/settings/messenger/"
DEFAULT_YEARS = 3              # срок по умолчанию, лет (FR-670; CONTRACT-008, 2.3)
PURGED = "messenger.retention_purged"
CHANGED = "messenger.retention_changed"
PURGED_TITLE = "Сообщения удалены по сроку"
CHANGED_TITLE = "Срок хранения сообщений изменён"
PURGED_LABEL = "Удалено по сроку, сообщений"
YEARS_LABEL = re.compile(r"срок хранения, лет:\s*(\d+)", re.IGNORECASE)
CONFIRM_TEXT = "Ближайшее ночное задание удалит сообщений:"
CONFIRM_BUTTON = "Подтвердить"
MOSCOW = timezone(timedelta(hours=3))

# Ночное задание мессенджера в процессе команды стенда: то же, что ставит в очередь cron `55 23 * * *`
# (`messenger_retention`, раздел 1.2). Печатает число удалённых сообщений — из него берётся «стало» журнала.
PURGE_CODE = ("from apps.messenger.tasks import retention_night\n"
              "print('messenger_purge: %s' % (retention_night() or 0))")

_CIRCLES: dict = {}


class Circle(NamedTuple):
    cast: object      # `helpers_messenger.MessengerCast`


@pytest.fixture
def circle(browser, admin_page, mailpit, new_context) -> Circle:
    """Круг сценария: учётки и узлы `messenger_cast` один раз на круг браузера, сессии — сохранённые."""
    key = browser.e2e_project
    if key not in _CIRCLES:
        _CIRCLES[key] = Circle(helpers_messenger.messenger_cast(admin_page, mailpit, new_context))
    return _CIRCLES[key]


# --- Помощники файла -----------------------------------------------------------------------------------------------

def _marker() -> str:
    """Уникальное слово текста: по нему сообщение ищется в беседе и должно отсутствовать в журнале."""
    return f"Срок{secrets.token_hex(4)}"


def _term_days(years: int) -> int:
    """Сколько суток в `years` календарных годах до сегодняшней даты по Москве (замена года; 29 февраля → 28)."""
    today = datetime.now(MOSCOW).date()
    try:
        past = today.replace(year=today.year - years)
    except ValueError:
        past = today.replace(year=today.year - years, day=28)
    return (today - past).days


def _purge() -> int:
    """Ночное задание мессенджера (`retention_night`) в контейнере `web`; возвращает число удалённых сообщений.
    Ошибка команды (ненулевой код) — `subprocess.CalledProcessError` из `helpers.stand_shell`."""
    out = helpers.stand_shell(PURGE_CODE)
    found = re.search(r"messenger_purge:\s*(\d+)", out)
    assert found, f"ночное задание не напечатало число удалённых сообщений: {out[-300:]!r}"
    return int(found.group(1))


def _dialog(context, cast):
    """Личный диалог `writer` ↔ `peer`: страница писателя в беседе и номер чата (`start_dialog` шлёт первое
    сообщение). Повторный вызов на пару открывает ту же переписку (FR-645)."""
    page = helpers_messenger.open_messenger(context, cast.writer)
    return page, helpers_messenger.start_dialog(page, cast.peer)


def _message(page, message_id):
    """Сообщение `article#m<id>[data-message-id]` (12.3)."""
    return page.locator(f'article[data-message-id="{message_id}"]')


def _open_chat(page, chat_id) -> None:
    page.goto(f"/messenger/chats/{chat_id}/")
    page.wait_for_load_state()
    expect(page.locator('[data-messenger-page="chat"]')).to_be_visible()


def _open_settings(page) -> None:
    page.goto(SETTINGS_URL)
    expect(page.locator('[data-messenger-page="settings"]')).to_be_visible()


def _settings_form(page):
    """Форма настроек с видимым полем срока: у второго шага поле `retention_years` скрытое (10.2)."""
    return page.locator('[data-messenger-page="settings"] '
                        'form:has(input[name="retention_years"]:not([type="hidden"]))').first


def _years_value(page) -> int:
    _open_settings(page)
    return int(page.locator('input[name="retention_years"]').first.input_value())


def _submit_years(page, value: int) -> None:
    """Вводит срок и отправляет форму настроек; ждёт ответ POST (уменьшение — 200 со вторым шагом, иначе 302)."""
    form = _settings_form(page)
    expect(form).to_be_visible()
    form.locator('input[name="retention_years"]').first.fill(str(value))
    with page.expect_response(lambda r: r.request.method == "POST"
                              and r.url.split("?")[0].endswith(SETTINGS_URL)) as info:
        form.locator('button:not([type="button"])').first.click()
    page.wait_for_load_state()
    assert info.value.status in (200, 302), f"настройки: ответ {info.value.status}"


def _confirm(page) -> None:
    """Второй шаг уменьшения срока: «Подтвердить» `button[name=confirm][value=1]` (10.2); ждёт ответ POST."""
    button = page.locator('[data-messenger-confirm] button[name="confirm"][value="1"]')
    expect(button).to_be_visible()
    expect(button).to_contain_text(CONFIRM_BUTTON)
    with page.expect_response(lambda r: r.request.method == "POST"
                              and r.url.split("?")[0].endswith(SETTINGS_URL)):
        button.click()
    page.wait_for_load_state()


def _warning_count(page) -> int:
    """Число из «Ближайшее ночное задание удалит сообщений: N» второго шага (13.2, `purge_count`)."""
    confirm = page.locator("[data-messenger-confirm]")
    expect(confirm).to_be_visible()
    expect(confirm).to_contain_text(CONFIRM_TEXT)
    found = re.search(re.escape(CONFIRM_TEXT) + r"\s*(\d+)", confirm.inner_text())
    assert found, f"в предупреждении нет числа сообщений: {confirm.inner_text()!r}"
    return int(found.group(1))


def _ensure_general(page) -> None:
    """«Общий чат» включён: соседние сценарии (m04, m12, m13) ждут его в списке. Если второй шаг настроек снял
    галочку (контракт её для подтверждения не описывает), она возвращается здесь же."""
    _open_settings(page)
    box = page.locator('input[name="general_chat_enabled"]')
    expect(box).to_have_count(1)
    if box.is_checked():
        return
    box.set_checked(True)
    form = _settings_form(page)
    with page.expect_response(lambda r: r.request.method == "POST"
                              and r.url.split("?")[0].endswith(SETTINGS_URL)):
        form.locator('button:not([type="button"])').first.click()
    page.wait_for_load_state()
    expect(page.locator('input[name="general_chat_enabled"]')).to_be_checked(checked=True)


def _restore_years(page, current: int) -> None:
    """Возвращает срок 3: уменьшение идёт через «Подтвердить», увеличение — сразу (10.2)."""
    if current != DEFAULT_YEARS:
        _open_settings(page)
        _submit_years(page, DEFAULT_YEARS)
        if current > DEFAULT_YEARS:
            _confirm(page)
    _ensure_general(page)


def _journal_rows(page, action: str) -> list:
    """Строки журнала с кодом `action` у объекта `messenger.settings`/`1` (8.1)."""
    return helpers_org.audit_rows(page, action, object_id="1")


# --- П. 1: срок, удаление с файлами, журнал без текста (FR-670, FR-671) ------------------------------------------

def test_message_older_than_term_deleted_with_files_and_journal_row_without_text(
        circle, admin_page, new_context, tmp_path):
    """Сценарий 11, п. 1 (FR-670, FR-671): сообщение старше срока (3 года и 1 день) после ночного задания удалено
    вместе с файлом (оригинал и эскиз — 404, до задания оба 200), в журнале запись `messenger.retention_purged`
    с числом удалённых сообщений и без текста переписки; настройка по умолчанию — 3 года."""
    marker = _marker()
    page, chat_id = _dialog(new_context(), circle.cast)
    image = tmp_path / "retention.png"
    image.write_bytes(helpers.make_png(64, 64))
    file_id = helpers_messenger.upload(page, image)
    message_id = helpers_messenger.write(page, f"{marker} текст переписки")
    helpers_messenger.wait_clean(page, file_id)          # контроль до задания: файл чист и отдаётся
    expect(_message(page, message_id)).to_be_visible()
    assert helpers_org.direct_get(page, f"/messenger/files/{file_id}/").status == 200
    assert helpers_org.direct_get(page, f"/messenger/files/{file_id}/thumb/").status == 200
    assert _years_value(admin_page) == DEFAULT_YEARS, "срок по умолчанию не три года"

    assert helpers_messenger.age(_term_days(DEFAULT_YEARS) + 1)["aged"] >= 1, "команда `age` не состарила сообщения"
    deleted = _purge()
    assert deleted >= 1, "ночное задание не удалило сообщение старше срока"

    assert helpers_org.direct_get(page, f"/messenger/files/{file_id}/").status == 404, "оригинал файла не удалён"
    assert helpers_org.direct_get(page, f"/messenger/files/{file_id}/thumb/").status == 404, "эскиз файла не удалён"
    _open_chat(page, chat_id)
    expect(_message(page, message_id)).to_have_count(0)
    assert marker not in page.locator("#messenger-messages").inner_text(), "удалённое сообщение осталось в беседе"

    sides = helpers_org.audit_sides(admin_page, PURGED, object_id="1")
    assert sides, "в журнале нет события messenger.retention_purged"
    _, became = sides[0]
    assert re.search(re.escape(PURGED_LABEL) + r":\s*" + str(deleted) + r"\b", became), f"«стало»: {became!r}"
    row = admin_page.locator(f'tr[data-event-id][data-action="{PURGED}"]').first
    expect(row).to_contain_text(PURGED_TITLE)
    assert marker not in row.inner_text(), "в записи журнала есть текст переписки"
    assert marker not in helpers.audit_text(admin_page), "текст переписки попал в журнал"


# --- П. 2: повтор задания без записей и ошибок (NFR-706) ----------------------------------------------------------

def test_second_night_job_run_deletes_nothing_and_writes_no_journal_row(circle, admin_page, new_context):
    """Сценарий 11, п. 2 (NFR-706): повтор ночного задания ничего не удаляет (возвращает 0), нового события журнала
    нет, команда без ошибки; сообщение, созданное уже после первого задания, цело и видно в беседе (срок считается
    от даты отправки)."""
    marker = _marker()
    page, chat_id = _dialog(new_context(), circle.cast)
    message_id = helpers_messenger.write(page, f"{marker} старое сообщение")
    helpers_messenger.age(_term_days(DEFAULT_YEARS) + 1)
    first = _purge()
    assert first >= 1, "первый запуск ничего не удалил: нечего повторять"
    journal = _journal_rows(admin_page, PURGED)
    assert journal, "первый запуск не записал журнал: нечего сравнивать"

    fresh_id = helpers_messenger.write(page, f"{marker} свежее сообщение")   # после задания — срок не вышел
    second = _purge()
    assert second == 0, f"повтор ночного задания удалил сообщения: {second}"
    assert len(_journal_rows(admin_page, PURGED)) == len(journal), "повтор добавил запись в журнал"

    _open_chat(page, chat_id)
    expect(_message(page, fresh_id)).to_be_visible()
    expect(_message(page, message_id)).to_have_count(0)


# --- П. 3: уменьшение срока с подтверждением и журнал «было / стало» (FR-670, FR-671) -----------------------------

def test_reducing_retention_needs_confirmation_and_is_audited_before_after(circle, admin_page, new_context):
    """Сценарий 11, п. 3 (FR-670, FR-671): уменьшение 3 → 2 без `confirm` — 200 со вторым шагом
    `[data-messenger-confirm]`: «Ближайшее ночное задание удалит сообщений: N», скрытое новое значение и кнопка
    «Подтвердить»; значение и журнал прежние. С подтверждением срок сохраняется, в журнале одна запись
    `messenger.retention_changed` — «было 3, стало 2» без текста переписки."""
    page, _ = _dialog(new_context(), circle.cast)
    marker = f"{_marker()} текст переписки"
    helpers_messenger.write(page, marker)                 # текст есть в базе, но в журнал попасть не должен
    assert _years_value(admin_page) == DEFAULT_YEARS
    before_rows = len(_journal_rows(admin_page, CHANGED))
    current = DEFAULT_YEARS
    try:
        _open_settings(admin_page)
        _submit_years(admin_page, 2)
        count = _warning_count(admin_page)
        hidden = admin_page.locator('[data-messenger-confirm] input[name="retention_years"][type="hidden"]')
        expect(hidden).to_have_value("2")
        assert _years_value(admin_page) == DEFAULT_YEARS, "срок изменился без подтверждения"
        assert len(_journal_rows(admin_page, CHANGED)) == before_rows, "без подтверждения появилась запись журнала"

        _open_settings(admin_page)
        _submit_years(admin_page, 2)
        assert _warning_count(admin_page) == count, "число к удалению изменилось без новых старых сообщений"
        _confirm(admin_page)
        current = 2
        assert _years_value(admin_page) == 2, "подтверждённый срок не сохранён"

        sides = helpers_org.audit_sides(admin_page, CHANGED, object_id="1")
        assert len(sides) == before_rows + 1, f"записей «срок изменён»: {len(sides) - before_rows}"
        was, became = sides[0]
        assert YEARS_LABEL.search(was) and YEARS_LABEL.search(was).group(1) == "3", f"«было»: {was!r}"
        assert YEARS_LABEL.search(became) and YEARS_LABEL.search(became).group(1) == "2", f"«стало»: {became!r}"
        row = admin_page.locator(f'tr[data-event-id][data-action="{CHANGED}"]').first
        expect(row).to_contain_text(CHANGED_TITLE)
        assert marker not in row.inner_text(), "в записи журнала есть текст переписки"
        assert marker not in helpers.audit_text(admin_page), "текст переписки попал в журнал"
    finally:
        _restore_years(admin_page, current)


# --- П. 4: удалённого по сроку нет в беседе, правка отклонена (FR-670) -------------------------------------------

def test_edit_of_message_deleted_by_term_is_rejected(circle, admin_page, new_context):
    """Сценарий 11, п. 4 (FR-670): сообщение, удалённое по сроку, автор в беседе не видит (истории нет), а прямой
    POST на правку `…/messages/<id>/edit/` отвечает 404 — как у несуществующего сообщения."""
    marker = _marker()
    page, chat_id = _dialog(new_context(), circle.cast)
    message_id = helpers_messenger.write(page, f"{marker} будет удалено по сроку")
    helpers_messenger.age(_term_days(DEFAULT_YEARS) + 1)
    assert _purge() >= 1, "ночное задание не удалило сообщение старше срока"

    _open_chat(page, chat_id)
    expect(_message(page, message_id)).to_have_count(0)
    assert marker not in page.locator("#messenger-messages").inner_text(), "удалённое сообщение осталось в беседе"

    response = helpers_org.direct_post(page, f"/messenger/messages/{message_id}/edit/", {"text": "поздняя правка"})
    assert response.status == 404, f"правка удалённого по сроку сообщения: ответ {response.status}"