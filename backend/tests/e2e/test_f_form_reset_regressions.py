"""T-7260: reset формы публикации после успешной публикации адресату-узлу (RED-регрессия).

До product-патча `feed.js` общий guard `htmx:oobBeforeSwap` отменяет OOB outerHTML-замену
reset-формы: у новой формы те же `id` полей (`id_feed_text`, `id_feed_to`), что и у старой,
поэтому `shouldSwap = false` и форма не сбрасывается. Патч добавляет узкое исключение для
подключённой `form#feed-form[data-feed-form]`.

Проверка настоящим браузером, только существующими помощниками (`helpers_feed`):
- издатель с правом «Писать всем» (`feed.post_all`);
- `publish(..., to=[("unit", <название>)])` (внутри — `expect_response` на POST `/feed/posts/`,
  то есть ожидание HTTP-ответа и видимой записи);
- старая форма отсоединена (`!isConnected`) после замены, новая `form#feed-form` в состоянии
  по умолчанию: ровно одна таблетка `[data-to-pill="all"]`, пустой `textarea`, без таблетки `unit`;
- вторая публикация другому узлу проходит и снова сбрасывает форму.

RED до патча: `wait_for_function("node => !node.isConnected")` не выполняется (старая форма
остаётся в DOM). Снов нет; моков WebSocket/fetch/Alpine нет; `htmx.process` вручную не вызывается.
"""
import secrets

from playwright.sync_api import expect

from tests.e2e import helpers_org
from tests.e2e.helpers_feed import POST_ALL, make_role, open_feed, publish


def _word() -> str:
    """Уникальное слово из русских букв (поиск ленты работает по словам)."""
    return "".join(secrets.choice("абвгдежзиклмнопрстуф") for _ in range(12))


def _setup(admin_page, employee):
    """Издатель с правом «Писать всем» и два подразделения для публикации."""
    tag = secrets.token_hex(4)
    writer = employee(role=make_role(admin_page, [POST_ALL]), full_name=f"Автор{tag} Иван Иванович")
    helpers_org.open_structure(admin_page)
    root = helpers_org.root_id(admin_page)
    # create_unit возвращает id узла; для подсказки «Кому» нужен label = название.
    unit_a = helpers_org.unique_name("Сброс А")
    unit_b = helpers_org.unique_name("Сброс Б")
    helpers_org.create_unit(admin_page, unit_a, kind="department", parent_id=root)
    helpers_org.create_unit(admin_page, unit_b, kind="department", parent_id=root)
    return writer, unit_a, unit_b


def test_form_resets_after_publish_to_unit_and_second_publish_succeeds(admin_page, employee, new_context):
    """Публикация узлу сбрасывает форму к состоянию по умолчанию; вторая публикация другому узлу проходит."""
    writer, unit_a, unit_b = _setup(admin_page, employee)
    page = open_feed(new_context(), writer)

    form = page.locator("form#feed-form")
    expect(form).to_be_visible()
    expect(form.locator('[data-to-pill="all"]')).to_have_count(1)
    old_form = form.element_handle()
    assert old_form is not None, "форма публикации отсутствует"

    first = publish(page, f"Сброс формы первый {_word()}", to=[("unit", unit_a)])

    # RED до патча: OOB outerHTML-замена reset-формы отменяется, старый узел остаётся в DOM.
    page.wait_for_function("node => !node.isConnected", arg=old_form, timeout=15_000)

    reset = page.locator("form#feed-form")
    expect(reset).to_have_count(1)
    expect(reset.locator('textarea[name="text"]')).to_have_value("")
    expect(reset.locator("[data-to-pill]")).to_have_count(1)
    expect(reset.locator('[data-to-pill="all"]')).to_have_count(1)

    # Вторая публикация другому узлу тоже проходит и снова приводит форму к состоянию по умолчанию.
    second = publish(page, f"Сброс формы второй {_word()}", to=[("unit", unit_b)])
    expect(page.locator(f"#feed-post-{first}").first).to_be_visible()
    expect(page.locator(f"#feed-post-{second}").first).to_be_visible()
    reset_after = page.locator("form#feed-form")
    expect(reset_after).to_have_count(1)
    expect(reset_after.locator('textarea[name="text"]')).to_have_value("")
    expect(reset_after.locator("[data-to-pill]")).to_have_count(1)
    expect(reset_after.locator('[data-to-pill="all"]')).to_have_count(1)
    print(f"f-reset: first={first} second={second} resets=2")
