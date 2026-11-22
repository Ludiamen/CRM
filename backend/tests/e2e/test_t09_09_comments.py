"""T-9301: сценарий 10 — комментарии, правка и удаление, файлы (FR-693, FR-694, NFR-713).

Общее для файла (CONTRACT-009, разделы 6.1–6.3, 10, 12.1, 13.3; SPEC-009, сценарий 10; шаблон
`e2e/template.md`):
- учётки — `helpers_tasks.tasks_cast` один раз на круг браузера; задачи — `create_task`; карточка — `open_card`;
- комментарий — `helpers_tasks.comment` (форма `[data-form="task-comment"]`), записи ленты —
  `[data-comment-id]`; файл — `helpers_tasks.upload_task_file` («таблетка» `[data-task-file="<uuid>"]`);
- правка и удаление своего комментария отправляются прямым POST на адреса 6.2 от сессии автора
  (`helpers_org.direct_post`): отдельных зацепок для кнопок «изменить»/«удалить» контракт не даёт; результат
  проверяется в ленте — `[data-comment-edited]`, «Комментарий удалён»;
- чужой комментарий не правится: ответ 403 (6.1); чужой здесь — руководитель, который задачу видит, но автором
  комментария не является;
- исполняемый файл отклоняется причиной `file_type` (12.1); «до проверки недоступен, после — чистый» требует
  ClamAV и проверяется серверными `test_tasks_files`; здесь — видимая часть: таблетка и ссылка в комментарии.
"""
import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_org
from tests.e2e.helpers_tasks import comment, create_task, open_card, open_tasks, tasks_cast, upload_task_file

pytestmark = pytest.mark.e2e

FILE_TYPE_TEXT = "Файл такого типа не принимается"
_CIRCLES: dict = {}


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    """Круг сценария 10: учётки и узлы собираются при первом обращении в круге браузера."""
    key = browser.e2e_project
    if key not in _CIRCLES:
        _CIRCLES[key] = tasks_cast(admin_page, mailpit, new_context)
    return _CIRCLES[key]


def _comment_row(page, text: str):
    """Запись ленты по тексту комментария."""
    return page.locator("[data-comment-id]").filter(has_text=text).first


def test_t09_09_comment_is_visible_to_all_participants_and_feed_starts_with_creation(cast, new_context):
    """Сценарий 10, п. 1 (FR-693, FR-694): исполнитель пишет комментарий — его видит и постановщик; первая
    строка ленты карточки — «Создал задачу»."""
    head, employee = cast.head, cast.employee
    head_page = open_tasks(new_context(), head)
    task_id = create_task(head_page, helpers_org.unique_name("Комментарий"), assignee=employee)

    author = open_card(new_context(), employee, task_id)
    text = f"Комментарий {helpers_org.unique_name('к')}"
    comment(author, text)
    expect(_comment_row(author, text)).to_contain_text(text)
    expect(author.locator('[data-tasks-page="card"]')).to_contain_text("Создал задачу")

    head_view = open_card(new_context(), head, task_id)
    expect(_comment_row(head_view, text)).to_contain_text(text)


def test_t09_09_own_comment_is_edited_and_deleted_and_foreign_edit_is_forbidden(cast, new_context):
    """Сценарий 10, п. 2 (FR-693, FR-694): автор правит свой комментарий (появляется пометка «изменено») и
    удаляет его (серая запись «Комментарий удалён»); руководитель править чужой комментарий не может — 403."""
    head, employee = cast.head, cast.employee
    page = open_tasks(new_context(), employee)
    task_id = create_task(page, helpers_org.unique_name("Правка"), assignee=employee)
    first = f"Первый вариант {helpers_org.unique_name('к')}"
    comment(page, first)
    row = _comment_row(page, first)
    comment_id = row.get_attribute("data-comment-id")
    assert comment_id, "у записи ленты нет data-comment-id"

    head_page = open_tasks(new_context(), head)
    foreign = helpers_org.direct_post(
        head_page, f"/tasks/comments/{comment_id}/edit/", {"text": "Чужая правка"})
    assert foreign.status == 403, f"чужой комментарий правится: {foreign.status}"

    second = "Второй вариант"
    edited = helpers_org.direct_post(page, f"/tasks/comments/{comment_id}/edit/", {"text": second})
    assert edited.status in (200, 302), f"правка своего комментария ответила {edited.status}"
    page.reload()
    page.wait_for_load_state()
    row = page.locator(f'[data-comment-id="{comment_id}"]')
    expect(row).to_contain_text(second)
    marker = page.locator(f'[data-comment-id="{comment_id}"][data-comment-edited], '
                          f'[data-comment-id="{comment_id}"] [data-comment-edited]')
    expect(marker.first).to_be_visible()

    removed = helpers_org.direct_post(page, f"/tasks/comments/{comment_id}/delete/", {})
    assert removed.status in (200, 302), f"удаление своего комментария ответило {removed.status}"
    page.reload()
    page.wait_for_load_state()
    expect(page.locator('[data-tasks-page="card"]')).to_contain_text("Комментарий удалён")


def test_t09_09_file_tile_is_attached_to_comment_and_executable_is_refused(cast, new_context, tmp_path):
    """Сценарий 10, п. 3 (FR-693, NFR-713): файл прикладывается к комментарию — до отправки видна «таблетка»
    `[data-task-file="<uuid>"]`, после отправки ссылка на файл есть в записи ленты; исполняемый файл отклоняется
    причиной `file_type`."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    task_id = create_task(page, helpers_org.unique_name("Файл"), assignee=employee)
    card = open_card(new_context(), employee, task_id)

    attachment = tmp_path / "протокол.txt"
    attachment.write_text("данные протокола", encoding="utf-8")
    uuid = upload_task_file(card, attachment)
    assert uuid, "таблетка файла не вернула uuid"
    expect(card.locator(f'[data-task-file="{uuid}"]')).to_be_visible()

    text = f"Файл к комментарию {helpers_org.unique_name('ф')}"
    comment(card, text)
    row = _comment_row(card, text)
    expect(row.locator(f'a[href*="{uuid}"]')).to_be_visible()

    executable = tmp_path / "setup.exe"
    executable.write_bytes(b"MZ" + b"\0" * 64)
    card.locator('input[type=file][name="file"]').set_input_files(str(executable))
    expect(card.locator('[data-error="file"][data-code="file_type"]')).to_contain_text(FILE_TYPE_TEXT)