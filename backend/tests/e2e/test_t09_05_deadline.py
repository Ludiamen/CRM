"""T-9301: сценарий 5 — доска «Сроки», переносы и запрет «Просрочены» (FR-681, FR-684, NFR-711).

Общее для файла (CONTRACT-009, разделы 6.3, 7, 12.1, 13.3; SPEC-009, сценарий 5; шаблон `e2e/template.md`):
- учётки — `helpers_tasks.tasks_cast` один раз на круг браузера; задачи — `create_task`; доска —
  `open_tasks(new_context(), account, preset="board:deadline")`;
- группы `[data-column="overdue|today|week|none"]` в порядке раздела 7, названия `[data-column-title]`;
- «сегодня» — по Москве (`datetime.now(tz(+03:00)).date()`; Москва без перехода на летнее время);
- «Просрочены» в браузере не наполняются: срок раньше сегодняшнего форма не принимает (`deadline_past`, 12.1),
  поэтому у группы проверяется наличие и запрет переноса, а не состав;
- перенос «на неделе» — ближайшая пятница **строго после** сегодня (сегодня пятница — следующая, FR-681);
  перенос «без срока» снимает срок; отказ «Просрочены» — `[data-code="overdue_move"]` с текстом 12.1;
- дата в строке списка — текст ДД.ММ.ГГГГ (NFR-717); `sleep` нет.
"""
import re
from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_org
from tests.e2e.helpers_tasks import board_titles, create_task, move_card, open_card, open_tasks, tasks_cast

pytestmark = pytest.mark.e2e

MOSCOW = timezone(timedelta(hours=3))
DATE_TEXT = re.compile(r"\d{2}\.\d{2}\.\d{4}")
_CIRCLES: dict = {}


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    """Круг сценария 5: учётки и узлы собираются при первом обращении в круге браузера."""
    key = browser.e2e_project
    if key not in _CIRCLES:
        _CIRCLES[key] = tasks_cast(admin_page, mailpit, new_context)
    return _CIRCLES[key]


def _today():
    return datetime.now(MOSCOW).date()


def _day(offset: int = 0) -> str:
    """Дата «сегодня по Москве» плюс `offset` дней в виде ДД.ММ.ГГГГ."""
    return (_today() + timedelta(days=offset)).strftime("%d.%m.%Y")


def _friday_after_today() -> str:
    """Ближайшая пятница строго после сегодня (сегодня пятница — пятница следующей недели)."""
    today = _today()
    delta = (4 - today.weekday()) % 7
    return (today + timedelta(days=delta or 7)).strftime("%d.%m.%Y")


def _status(page, task_id):
    """Элемент со статусом задачи в карточке (6.3)."""
    return page.locator(f'[data-task-id="{task_id}"][data-task-status], '
                        f'[data-task-id="{task_id}"] [data-task-status]').first


def _set_status(page, task_id, value: str) -> None:
    """Меняет статус запасным путём карточки (FR-684)."""
    form = page.locator('form[data-task-field="status"]')
    expect(form).to_be_visible()
    form.locator('[data-task-field="status"]').select_option(value)
    form.locator("button[type=submit]").first.click()
    expect(_status(page, task_id)).to_have_attribute("data-task-status", value)


def _row(page, task_id):
    """Строка списка по номеру задачи (только `#tasks-list`)."""
    return page.locator(f'#tasks-list [data-task-id="{task_id}"]')


def test_t09_05_board_groups_deadlines_and_hides_done_and_far_tasks(cast, new_context):
    """Сценарий 5, п. 1 (FR-681): задачи со сроком сегодня, на неделе и без срока стоят в своих группах;
    задача со сроком дальше 7 дней и завершённая на доске не показываются."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    title_today = helpers_org.unique_name("Сегодня")
    title_week = helpers_org.unique_name("Неделя")
    title_none = helpers_org.unique_name("Без срока")
    title_far = helpers_org.unique_name("Далёкий")
    title_done = helpers_org.unique_name("Готово")
    create_task(page, title_today, deadline=_day(0), assignee=employee)
    create_task(page, title_week, deadline=_day(3), assignee=employee)
    create_task(page, title_none, assignee=employee)
    create_task(page, title_far, deadline=_day(10), assignee=employee)
    task_done = create_task(page, title_done, deadline=_day(0), assignee=employee)
    card = open_card(new_context(), employee, task_done)
    _set_status(card, task_done, "done")

    board = open_tasks(new_context(), employee, preset="board:deadline")
    expect(board.locator('[data-board="deadline"]')).to_be_visible()
    keys = board.locator("[data-column]").evaluate_all("els => els.map(e => e.getAttribute('data-column'))")
    assert keys == ["overdue", "today", "week", "none"], f"колонки доски «Сроки»: {keys}"
    titles = [text.strip() for text in board.locator("[data-column-title]").all_inner_texts()]
    assert titles == ["Просрочены", "Сегодня", "На неделе", "Без срока"], f"названия групп: {titles}"

    columns = board_titles(board)
    assert title_today in columns["today"], f"задача со сроком сегодня не в «Сегодня»: {columns}"
    assert title_week in columns["week"], f"задача на неделе не в «На неделе»: {columns}"
    assert title_none in columns["none"], f"задача без срока не в «Без срока»: {columns}"
    shown = [title for titles in columns.values() for title in titles]
    assert title_far not in shown, "задача со сроком дальше 7 дней показана на доске"
    assert title_done not in shown, "завершённая задача показана на доске"


def test_t09_05_move_to_today_sets_today_and_to_none_clears_deadline(cast, new_context):
    """Сценарий 5, п. 2 (FR-681): перенос в «Сегодня» ставит сегодняшний срок (виден в строке списка), перенос
    в «Без срока» снимает его — даты в строке больше нет."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    title = helpers_org.unique_name("Срок")
    task_id = create_task(page, title, assignee=employee)

    board = open_tasks(new_context(), employee, preset="board:deadline")
    move_card(board, task_id, "deadline", "today")
    assert title in board_titles(board)["today"], "карточка не встала в «Сегодня»"

    listing = open_tasks(new_context(), employee, preset="mine")
    text = _row(listing, task_id).inner_text()
    expect(_row(listing, task_id)).to_contain_text(_day(0))
    assert len(DATE_TEXT.findall(text)) == 1, f"в строке больше одной даты: {text!r}"

    board = open_tasks(new_context(), employee, preset="board:deadline")
    move_card(board, task_id, "deadline", "none")
    assert title in board_titles(board)["none"], "карточка не встала в «Без срока»"

    listing = open_tasks(new_context(), employee, preset="mine")
    assert not DATE_TEXT.search(_row(listing, task_id).inner_text()), "после снятия срока дата осталась"


def test_t09_05_move_to_week_sets_nearest_friday_strictly_after_today(cast, new_context):
    """Сценарий 5, п. 2 (FR-681): перенос в «На неделе» ставит ближайшую пятницу строго после сегодня; если
    сегодня пятница — пятницу следующей недели."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    title = helpers_org.unique_name("Пятница")
    task_id = create_task(page, title, assignee=employee)

    expected = _friday_after_today()
    board = open_tasks(new_context(), employee, preset="board:deadline")
    move_card(board, task_id, "deadline", "week")
    assert title in board_titles(board)["week"], "карточка не встала в «На неделе»"

    listing = open_tasks(new_context(), employee, preset="mine")
    expect(_row(listing, task_id)).to_contain_text(expected)


def test_t09_05_move_into_overdue_is_refused_with_reason_and_card_stays(cast, new_context):
    """Сценарий 5, п. 3 (FR-681): карточку из «Сегодня» пытаются перетащить в «Просрочены» — переноса нет,
    причина `overdue_move` показана, карточка остаётся в «Сегодня»."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    title = helpers_org.unique_name("Нельзя")
    task_id = create_task(page, title, deadline=_day(0), assignee=employee)

    board = open_tasks(new_context(), employee, preset="board:deadline")
    move_card(board, task_id, "deadline", "overdue")

    expect(board.locator('[data-code="overdue_move"]').first).to_contain_text("Из «Просрочены» переносить нельзя")
    assert title in board_titles(board)["today"], "карточка ушла из «Сегодня» после запрещённого переноса"
    assert title not in board_titles(board)["overdue"], "карточка попала в «Просрочены»"