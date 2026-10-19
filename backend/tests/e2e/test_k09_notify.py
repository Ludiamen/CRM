"""T-5148: сценарий 9 — уведомления базы знаний: комментарий и правка (автору), подписка на рубрику, «Мои уведомления»,
внешние каналы, значения по умолчанию (FR-434, FR-435, FR-436, FR-437).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-005.md разделы 7.2, 10, 11, 17):
- каждый тест заводит своих сотрудников (редакторы — «Сотрудник ИТ», читатели — «Руководитель», управляющий — администратор
  круга `admin_page`), свои рубрики и статьи; названия уникальны; люди с проверяемым именем — с уникальным `full_name`;
- уведомления создаются службой в запросе (шина, после фиксации), поэтому «пришло» ждётся опросом списка `/notifications/`
  с перезагрузкой, а «не пришло» проверяется после ожидания и перезагрузки; везде, где проверяется отсутствие, в том же
  тесте есть положительный контроль (то же событие у того, кому уведомление положено);
- склейка (FR-435): пока у получателя есть непрочитанное уведомление того же вида по той же статье, новое не создаётся;
  поэтому между событиями одной статьи получатель «читает» (открывает статью: событие `object.viewed`), либо берутся
  разные статьи; прочитанное остаётся строкой списка с `data-unread="0"`;
- письма: срок письма сдвигает `helpers_notify.tick(shift=PAST_ANY_TERM)` (команда стенда `e2e_notify_tick`), письма
  ищутся по адресу получателя и шаблону `notify.item`; тихие часы у проверяемых — «Без тихих часов»;
- внешний канал — только Telegram учебной службы `fakebots` (решение 37), чат — уникальный номер теста; канал
  включается администратором на время блока `channels_on` и возвращается; MAX и Web Push в приёмке среза 005 не проверяются;
- общие настройки, которые меняет тест: значение по умолчанию «Почта» вида «Новый комментарий к моей статье» (тест 13) —
  возвращается в `finally`; состояние канала Telegram — возвращает `channels_on`; права и роли меняются только у своих
  сотрудников теста.
"""
import json
import re
import secrets
from urllib.parse import urlsplit

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_kb, helpers_notify, helpers_org
from tests.e2e.helpers_kb import (
    create_draft, create_rubric, fill_article_form, open_article, open_edit, press_save,
    publish_from_article_page, unique_title)

KIND_COMMENT = "knowledge.comment_on_my_article"
KIND_CHANGED = "knowledge.my_article_changed"
KIND_RUBRIC = "knowledge.rubric_subscription"
TITLE_COMMENT = "Новый комментарий к моей статье"      # 7.2: название вида
TITLE_CHANGED = "Мою статью изменили"
TITLE_RUBRIC = "Статья в рубрике по подписке"
KINDS = ((KIND_COMMENT, TITLE_COMMENT), (KIND_CHANGED, TITLE_CHANGED), (KIND_RUBRIC, TITLE_RUBRIC))
MODULE = "База знаний"
CHANNEL_ORDER = ["portal", "email", "push", "telegram", "max"]   # CONTRACT-004, 14.3
EXTERNAL_COMMENT = "Новый комментарий к вашей статье"   # 7.2: внешний текст вида (без заголовка)
SAVED = "Настройки уведомлений сохранены."
PAST_ANY_TERM = 121   # минут: больше верхней границы срока письма (120 минут)
LIST_WAIT_S = 15.0    # предел опроса списка уведомлений
SETTLE_MS = 1500      # пауза «не придёт ли лишнее»: только там, где доказывается отсутствие нового (settle=True)
ARTICLE_URL = re.compile(r"/kb/\d+/$")


# --- Общие помощники файла ----------------------------------------------------------------------------------

def _chat_id() -> int:
    """Уникальный номер чата `fakebots` для теста (иначе «чат уже привязан к другой учётной записи»)."""
    return secrets.randbelow(900_000_000) + 100_000_000


def _name(prefix: str) -> str:
    """Уникальное ФИО: фамилия с уникальной частью (текст «изменил Имя Фамилия» сравнивается целиком)."""
    return f"{prefix}{secrets.token_hex(3)} Пётр Петрович"


def _editor(employee, prefix: str = "Редактор"):
    return helpers_kb.make_editor(employee, full_name=_name(prefix))


def _reader(employee, prefix: str = "Читатель"):
    return helpers_kb.make_reader(employee, full_name=_name(prefix))


def _rubric(admin_page, prefix: str = "Сеть", *, parent_name: str | None = None) -> tuple:
    """Новая рубрика (создаёт управляющий): `(номер, название)`."""
    name = helpers_org.unique_name(prefix)
    return create_rubric(admin_page, name, parent_name=parent_name), name


def _published(page, rubric_name: str, text: str = "Текст статьи.") -> tuple:
    """Статья автора, опубликованная кнопкой страницы статьи: `(номер, заголовок)`."""
    title = unique_title()
    article_id = create_draft(page, title=title, text=text, rubric=rubric_name)
    publish_from_article_page(page, article_id)
    return article_id, title


def _edit_text(page, article_id, text: str) -> None:
    """Правка текста статьи и «Сохранить»; успех — страница статьи `/kb/<id>/` (решение C-2)."""
    open_edit(page, article_id)
    fill_article_form(page, text=text)
    press_save(page)
    page.wait_for_url(ARTICLE_URL)
    expect(page.locator(f'article[data-article-id="{article_id}"]')).to_be_visible()


def _subscribe(page, rubric_id) -> None:
    """Сотрудник подписывается на рубрику кнопкой страницы рубрики; ждёт `data-subscribed="true"`."""
    page.goto(f"/kb/rubrics/{rubric_id}/")
    button = page.locator('button[data-action="kb-subscribe"]')
    expect(button).to_be_visible()
    if button.get_attribute("data-subscribed") != "true":
        button.click()
    expect(page.locator('button[data-action="kb-subscribe"]')).to_have_attribute("data-subscribed", "true")


def _rows(page, title: str):
    """Строки списка `/notifications/`, в тексте которых есть заголовок статьи (список только читает)."""
    page.goto("/notifications/")
    expect(page.locator("[data-notify-list]")).to_be_visible()
    return page.locator("ul[data-notifications] li[data-notification]").filter(has_text=title)


def _kinds_of(rows) -> list:
    return [row.locator('[data-field="kind"]').inner_text().strip() for row in rows.all()]


def _unread(rows) -> int:
    """Сколько из строк непрочитанных (`data-unread="1"`)."""
    return rows.evaluate_all("els => els.filter(e => e.dataset.unread === '1').length")


def _texts_of(rows) -> list:
    return [" ".join(row.locator('[data-field="text"]').inner_text().split()) for row in rows.all()]


def _wait_rows(page, title: str, count: int, settle: bool = False):
    """Ждёт (до `LIST_WAIT_S` с, опросом с перезагрузкой), что строк по заголовку не меньше `count`; затем проверяет, что
    их ровно `count`. С `settle=True` перед последней проверкой ждёт `SETTLE_MS` (для проверок «нового нет»: без паузы
    отсутствие не доказать). Возвращает локатор строк (после последней перезагрузки)."""
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
    """Уведомлений по заголовку нет. Вызывается после положительного контроля (событие, пришедшее позже
    проверяемого, уже видно) или сразу после действия: событие обрабатывается в запросе (7.1), паузы не нужно."""
    rows = _rows(page, title)
    expect(rows).to_have_count(0)


def _quote(text: str) -> str:
    return f"«{text}»"


def _comment_text(title: str) -> str:
    return f"Новый комментарий к вашей статье {_quote(title)}"


def _changed_text(title: str, who: str) -> str:
    return f"Вашу статью {_quote(title)} изменил {who}"


def _rubric_text(subscribed: str, title: str) -> str:
    """`subscribed` — рубрика подписки получателя, ближайшая к статье (раздел 17, п. 51)."""
    return f"Статья в рубрике {_quote(subscribed)}: {title}"


def _set_role(admin_page, user_id, role_name: str, state: bool) -> None:
    """Личная роль сотрудника из формы `form[action$="/roles/"]` карточки (срез 001); ждёт ответ POST."""
    admin_page.goto(f"/staff/{user_id}/")
    form = admin_page.locator('form[action$="/roles/"]')
    form.get_by_label(role_name, exact=True).set_checked(state)
    with admin_page.expect_navigation():
        form.locator("button[type=submit]").click()
    admin_page.wait_for_load_state()


def _dismiss(admin_page, user_id) -> None:
    """Увольняет из карточки: диалог → подтверждение; ждёт отметку `[data-dismissed-badge]`."""
    admin_page.goto(f"/staff/{user_id}/")
    card = admin_page.locator(f'[data-card][data-user-id="{user_id}"]')
    card.locator('[data-action="dismiss"]').click()
    dialog = admin_page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(card.locator("[data-dismissed-badge]")).to_be_visible()


def _cell(page, kind: str, channel: str):
    """Флажок ячейки таблицы `/me/notifications/`."""
    return page.locator(f'table[data-notify-table] tr[data-notify-kind="{kind}"] td[data-channel="{channel}"] '
                        f'input[type=checkbox][name="cell"][value="{kind}:{channel}"]')


def _save_prefs(page, *, cells=None, quiet: str | None = None) -> None:
    """«Мои уведомления»: ставит ячейки `{(вид, канал): состояние}` и режим тихих часов, нажимает сохранение; успех —
    переход на `/me/notifications/` с «Настройки уведомлений сохранены.» и без отказов."""
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
    expect(page.locator("[role=status]").filter(has_text=SAVED).first).to_be_visible()


def _mail_ids(mailpit, to: str) -> set:
    """Номера уже имеющихся писем `notify.item` на адрес (чтобы ждать только новое)."""
    return {short["ID"] for short in helpers_notify.find_mails(mailpit, to, helpers_notify.TEMPLATE_ITEM)}


# --- Тесты --------------------------------------------------------------------------------------------------

def test_k09_comment_by_other_employee_gives_author_new_comment_notification_on_bell(
        admin_page, employee, new_context):
    """Сценарий 9, п. 1: другой сотрудник оставил комментарий под статьёй автора — автор получает «Новый комментарий к
    вашей статье «Заголовок»» на колокольчике: число растёт на 1, текст — в панели колокольчика и в списке, строка
    непрочитанная и ведёт на статью (FR-434, FR-435)."""
    _rubric_id, rubric = _rubric(admin_page)
    author, other = _editor(employee, "Автор"), _reader(employee, "Комментатор")
    article_id, title = _published(author.page, rubric)
    # дано: автор в сети (колокольчик открыт), число непрочитанных запомнено
    tab = helpers_notify.open_watcher(new_context, author, spy=False)
    before = helpers_notify.bell_count(tab)
    # п. 1: другой сотрудник оставляет комментарий
    helpers_kb.add_comment(other.page, article_id, "Спасибо, помогло.")
    # п. 1: на колокольчике +1
    helpers_notify.wait_bell_count(tab, before + 1, timeout_ms=15_000)
    expect(tab.locator("#notify-count")).to_have_attribute("data-count", str(before + 1))
    # п. 1: панель колокольчика содержит текст уведомления
    tab.locator("button[data-bell-toggle]").click()
    expect(tab.locator("#notify-bell-panel[data-bell-panel]")).to_contain_text(_comment_text(title))
    # п. 1: в списке — одна строка вида «Новый комментарий к моей статье», непрочитанная, с текстом из раздела 7.2
    rows = _wait_rows(tab, title, 1)
    expect(rows.first).to_have_attribute("data-unread", "1")
    expect(rows.first.locator('[data-field="kind"]')).to_have_text(TITLE_COMMENT)
    expect(rows.first.locator('[data-field="text"]')).to_have_text(_comment_text(title))
    expect(rows.first.locator("a[data-open]")).to_have_count(1)


def test_k09_author_commenting_own_article_gets_no_notification(admin_page, employee):
    """Сценарий 9, п. 2: автор сам комментирует свою статью — уведомления ему нет (FR-435). Положительный контроль:
    комментарий другого сотрудника под той же статьёй автору приходит (а значит, собственный не завёл склейку)."""
    _rubric_id, rubric = _rubric(admin_page)
    author, other = _editor(employee, "Автор"), _reader(employee, "Комментатор")
    article_id, title = _published(author.page, rubric)
    # п. 2: автор комментирует свою статью
    helpers_kb.add_comment(author.page, article_id, "Дополню позже.")
    # п. 2: уведомления нет
    _no_rows(author.page, title)
    before = helpers_notify.bell_count(author.page)
    # контроль: чужой комментарий — уведомление есть, ровно одно
    helpers_kb.add_comment(other.page, article_id, "Вопрос по шагу два.")
    rows = _wait_rows(author.page, title, 1)
    expect(rows.first.locator('[data-field="text"]')).to_have_text(_comment_text(title))
    assert helpers_notify.bell_count(author.page) == before + 1


def test_k09_edit_of_published_article_by_other_employee_gives_author_changed_notification_with_editor_name(
        admin_page, employee):
    """Сценарий 9, п. 3: другой сотрудник сохранил правку опубликованной статьи — автор получает «Вашу статью «Заголовок»
    изменил Имя Фамилия» (имя — того, кто сохранил) (FR-434, FR-435)."""
    _rubric_id, rubric = _rubric(admin_page)
    author, editor = _editor(employee, "Автор"), _editor(employee, "Правщик")
    article_id, title = _published(author.page, rubric)
    # п. 3: другой сотрудник сохраняет правку опубликованной статьи
    _edit_text(editor.page, article_id, "Текст после правки другого сотрудника.")
    # п. 3: автор получает ровно одно уведомление «Мою статью изменили» с именем правщика
    rows = _wait_rows(author.page, title, 1)
    expect(rows.first.locator('[data-field="kind"]')).to_have_text(TITLE_CHANGED)
    expect(rows.first.locator('[data-field="text"]')).to_have_text(_changed_text(title, editor.full_name))
    expect(rows.first).to_have_attribute("data-unread", "1")
    # контроль: автор читает уведомление (открывает статью), чтобы склейка не скрыла лишнее; его собственная правка
    # нового уведомления не даёт — строка одна и прочитанная
    open_article(author.page, article_id)
    expect(_rows(author.page, title).first).to_have_attribute("data-unread", "0")
    _edit_text(author.page, article_id, "Текст после правки автора.")
    rows = _wait_rows(author.page, title, 1, settle=True)
    assert _unread(rows) == 0, "автору пришло уведомление о его собственной правке"


def test_k09_edit_or_comment_on_draft_gives_nobody_notification(admin_page, employee):
    """Сценарий 9, п. 4: черновик правят или комментируют — никто не получает уведомлений (FR-435): ни автор, ни
    подписчик рубрики. Правит управляющий (чужой черновик открыт только ему), комментарий к черновику отвергается (404,
    блока комментариев у черновика нет). Контроль: публикация того же черновика даёт подписчику уведомление."""
    rubric_id, rubric = _rubric(admin_page)
    author, other, subscriber = _editor(employee, "Автор"), _editor(employee, "Другой"), _reader(employee, "Подписчик")
    _subscribe(subscriber.page, rubric_id)
    title = unique_title()
    article_id = create_draft(author.page, title=title, text="Черновик статьи.", rubric=rubric)
    # п. 4: черновик правит другой сотрудник (управляющий)
    _edit_text(admin_page, article_id, "Черновик после правки управляющего.")
    # п. 4: черновик комментируют — отказ 404, на странице черновика блока комментариев нет
    other.page.goto("/kb/")
    response = helpers_org.direct_post(other.page, f"/kb/{article_id}/comments/", {"text": "Комментарий к черновику."})
    assert response.status == 404, f"комментарий к черновику: статус {response.status}"
    admin_page.goto(f"/kb/{article_id}/")
    expect(admin_page.locator("section#comments[data-kb-comments]")).to_have_count(0)
    # п. 4: никто не получил уведомлений. Положительный контроль: новая публикация в той же рубрике доходит до
    # подписчика; когда она пришла, события черновика (если бы они были) уже обработаны
    _control_id, control_title = _published(author.page, rubric)
    _wait_rows(subscriber.page, control_title, 1)
    _no_rows(author.page, title)
    _no_rows(subscriber.page, title)
    # контроль: автор публикует — подписчик получает уведомление, сам автор (исполнитель) — нет
    publish_from_article_page(author.page, article_id)
    rows = _wait_rows(subscriber.page, title, 1)
    expect(rows.first.locator('[data-field="kind"]')).to_have_text(TITLE_RUBRIC)
    _no_rows(author.page, title)


def test_k09_unread_comment_notification_blocks_second_one_and_after_read_next_comment_creates_new(
        admin_page, employee):
    """Сценарий 9, п. 5: у автора есть непрочитанное «Новый комментарий к вашей статье» об этой статье — второй комментарий
    второго уведомления не создаёт; после прочтения (автор открыл статью) следующий комментарий создаёт новое (FR-435)."""
    _rubric_id, rubric = _rubric(admin_page)
    author, other = _editor(employee, "Автор"), _reader(employee, "Комментатор")
    article_id, title = _published(author.page, rubric)
    # п. 5: первый комментарий — одно уведомление
    helpers_kb.add_comment(other.page, article_id, "Первый комментарий.")
    rows = _wait_rows(author.page, title, 1)
    expect(rows.first).to_have_attribute("data-unread", "1")
    # п. 5: приходит новый комментарий, пока первое уведомление не прочитано — второго уведомления нет
    helpers_kb.add_comment(other.page, article_id, "Второй комментарий.")
    rows = _wait_rows(author.page, title, 1)
    expect(rows.first).to_have_attribute("data-unread", "1")
    # п. 5: автор читает (открывает статью) — уведомление прочитано
    open_article(author.page, article_id)
    rows = _rows(author.page, title)
    expect(rows).to_have_count(1)
    expect(rows.first).to_have_attribute("data-unread", "0")
    # п. 5: после прочтения следующий комментарий создаёт новое уведомление
    helpers_kb.add_comment(other.page, article_id, "Третий комментарий.")
    rows = _wait_rows(author.page, title, 2)
    assert _unread(rows) == 1, "непрочитанных строк должно быть одна (новая), прочитанная осталась"


def test_k09_rubric_subscriber_gets_in_rubric_notification_for_publish_or_edit_in_rubric_or_subrubric_unless_actor(
        admin_page, employee):
    """Сценарий 9, п. 6: подписчик рубрики получает «Статья в рубрике «<рубрика статьи>»: Заголовок», когда в рубрике или
    подрубрике публикуется статья или сохраняется правка опубликованной, если он не автор этого действия (FR-434, FR-435,
    FR-437). Название рубрики в тексте — рубрика подписки получателя, ближайшая к статье (раздел 17 п. 51 контракта,
    отменяет B-15: подписчик «Сети» при статье в подрубрике получает «Статья в рубрике «Сеть»»); текст строится на
    каждого получателя отдельно. Склейка: между событиями одной статьи подписчик читает её."""
    root_id, root = _rubric(admin_page, "Сеть")
    child_id, child = _rubric(admin_page, "VPN", parent_name=root)
    author, editor = _editor(employee, "Автор"), _editor(employee, "Правщик")
    subscriber = _editor(employee, "Подписчик")  # правит статьи сам: ветвь «исполнитель — сам подписчик»
    sub_child = _reader(employee, "Подписчик VPN")  # подписан только на подрубрику: п. 51, текст на получателя
    _subscribe(subscriber.page, root_id)
    _subscribe(sub_child.page, child_id)
    # п. 6: публикация в самой рубрике
    first_id, first = _published(author.page, root)
    rows = _wait_rows(subscriber.page, first, 1)
    expect(rows.first.locator('[data-field="kind"]')).to_have_text(TITLE_RUBRIC)
    expect(rows.first.locator('[data-field="text"]')).to_have_text(_rubric_text(root, first))
    # п. 6: публикация в подрубрике (подписка действует на подрубрики), в тексте — название подписанной рубрики
    # (корня), не подрубрики статьи (п. 51)
    second_id, second = _published(author.page, child)
    rows = _wait_rows(subscriber.page, second, 1)
    expect(rows.first.locator('[data-field="kind"]')).to_have_text(TITLE_RUBRIC)
    expect(rows.first.locator('[data-field="text"]')).to_have_text(_rubric_text(root, second))
    # п. 51: у подписчика подрубрики — своя подписка, значит в тексте подрубрика
    sub_rows = _wait_rows(sub_child.page, second, 1)
    expect(sub_rows.first.locator('[data-field="text"]')).to_have_text(_rubric_text(child, second))
    # п. 6: правка опубликованной статьи рубрики: подписчик прочитал первое уведомление, правит другой сотрудник
    open_article(subscriber.page, first_id)
    _edit_text(editor.page, first_id, "Первая статья после правки другого сотрудника.")
    rows = _wait_rows(subscriber.page, first, 2)
    assert _kinds_of(rows) == [TITLE_RUBRIC, TITLE_RUBRIC], _kinds_of(rows)
    assert set(_texts_of(rows)) == {_rubric_text(root, first)}
    assert _unread(rows) == 1
    # п. 6: правка подрубрики — то же; сначала читает
    open_article(subscriber.page, second_id)
    _edit_text(editor.page, second_id, "Вторая статья после правки другого сотрудника.")
    rows = _wait_rows(subscriber.page, second, 2)
    assert set(_texts_of(rows)) == {_rubric_text(root, second)}
    # п. 6: подписчик — автор действия (сам сохраняет правку): ему новой строки нет
    open_article(subscriber.page, second_id)
    _edit_text(subscriber.page, second_id, "Вторая статья после правки самого подписчика.")
    rows = _wait_rows(subscriber.page, second, 2, settle=True)
    assert _unread(rows) == 0, "подписчику пришло уведомление о его собственной правке"
    # контроль: правка другого сотрудника после этого уведомление даёт
    _edit_text(editor.page, second_id, "Вторая статья после повторной правки другого сотрудника.")
    rows = _wait_rows(subscriber.page, second, 3)
    assert _unread(rows) == 1


def test_k09_my_notifications_shows_three_kb_kinds_per_channel_for_editor_or_author(admin_page, employee):
    """Сценарий 9, п. 7: сотрудник с правом «Редактирование базы знаний» или автор хотя бы одной статьи открыл «Мои
    уведомления» — видны три вида модуля «База знаний»; каждый вид выключается по каналам, как у видов других
    модулей (FR-434; SPEC-004 FR-321). Ветви: редактор без статей; автор, потерявший право; выключение «Почты»."""
    editor = _editor(employee, "Редактор")
    # п. 7: редактор без статей — три вида модуля «База знаний», пять столбцов
    editor.page.goto("/me/notifications/")
    table = editor.page.locator("table[data-notify-table]")
    expect(table).to_be_visible()
    for code, title in KINDS:
        row = table.locator(f'tr[data-notify-kind="{code}"]')
        expect(row).to_have_count(1)
        expect(row.locator('[data-field="title"]')).to_have_text(title)
        expect(row.locator('[data-field="module"]')).to_have_text(MODULE)
        cells = row.locator("td[data-channel]")
        expect(cells).to_have_count(5)
        assert cells.evaluate_all("els => els.map(e => e.dataset.channel)") == CHANNEL_ORDER
    # п. 7: вид выключается по каналу, как у видов других модулей: «Почта» снята и сохранена, остальное не тронуто
    expect(_cell(editor.page, KIND_COMMENT, "email")).to_be_checked()
    _save_prefs(editor.page, cells={(KIND_COMMENT, "email"): False})
    expect(_cell(editor.page, KIND_COMMENT, "email")).not_to_be_checked()
    expect(_cell(editor.page, KIND_CHANGED, "email")).to_be_checked()
    expect(_cell(editor.page, KIND_RUBRIC, "email")).to_be_checked()
    expect(_cell(editor.page, KIND_COMMENT, "portal")).to_be_checked()
    # п. 7: автор хотя бы одной статьи, потерявший право, по-прежнему видит три вида
    _rubric_id, rubric = _rubric(admin_page)
    author = _editor(employee, "Автор")
    create_draft(author.page, title=unique_title(), rubric=rubric)
    _set_role(admin_page, author.id, helpers_kb.EDITOR_ROLE, False)
    assert author.page.goto("/kb/new/").status == 403, "право «Редактирование базы знаний» не снято"
    author.page.goto("/me/notifications/")
    for code, title in KINDS:
        row = author.page.locator(f'table[data-notify-table] tr[data-notify-kind="{code}"]')
        expect(row).to_have_count(1)
        expect(row.locator('[data-field="module"]')).to_have_text(MODULE)


def test_k09_telegram_gets_only_comment_text_and_link_without_article_title(admin_page, employee):
    """Сценарий 9, п. 8: у автора включён Telegram — приходит «Новый комментарий к вашей статье» и ссылка, без заголовка
    статьи, рубрики и имени комментатора (FR-436). MAX и Web Push в приёмке среза не проверяются (решение 37)."""
    _rubric_id, rubric = _rubric(admin_page)
    author, other = _editor(employee, "Автор"), _reader(employee, "Комментатор")
    article_id, title = _published(author.page, rubric)
    bots = helpers_kb.bots()
    chat = _chat_id()
    with helpers_notify.channels_on(admin_page, "telegram"):
        # дано: Telegram привязан, ячейка «Telegram» вида включена, тихих часов нет
        helpers_kb.bind_telegram(author.page, bots, chat)
        _save_prefs(author.page, cells={(KIND_COMMENT, "telegram"): True}, quiet="none")
        expect(_cell(author.page, KIND_COMMENT, "telegram")).to_be_checked()
        # когда: приходит «Новый комментарий к вашей статье»
        helpers_kb.add_comment(other.page, article_id, "Комментарий для проверки внешнего канала.")
        # п. 8: в Telegram — событие без заголовка
        found = helpers_kb.wait_telegram(bots, chat, text_has=EXTERNAL_COMMENT, timeout=60.0)
        assert len(found) == 1, f"сообщений «{EXTERNAL_COMMENT}» в свой чат: {len(found)}"
        message = found[0]
        assert message["text"] == EXTERNAL_COMMENT, "внешний текст не равен тексту вида"
        # п. 8: заголовка статьи, рубрики и имён нигде в сообщении нет
        dump = json.dumps(message, ensure_ascii=False)
        for forbidden in (title, rubric, other.full_name, author.full_name, other.email, author.email):
            assert forbidden not in dump, "во внешнем сообщении есть данные статьи или людей"
        # п. 8: ссылка — на портал: в кнопке сообщения адрес страницы уведомлений (раздел 17, п. 58)
        markup = message["reply_markup"]
        markup = json.loads(markup) if isinstance(markup, str) else markup
        url = markup["inline_keyboard"][0][0]["url"]
        path = urlsplit(url).path
        assert path.startswith("/notifications/"), f"ссылка внешнего сообщения: {path}"


def test_k09_dismissed_author_gets_no_notification_and_author_who_lost_edit_right_still_gets(
        admin_page, employee, mailpit):
    """Сценарий 9, п. 9: автор потерял право «Редактирование базы знаний» или уволен — другой сотрудник комментирует его
    статью: уволенный уведомления не получает, потерявший право получает (FR-435). Проверка — портал (у потерявшего
    право) и почта (у обоих, срок письма сдвигается командой стенда)."""
    _rubric_id, rubric = _rubric(admin_page)
    lost, dismissed = _editor(employee, "Потерявший"), _editor(employee, "Уволенный")
    other = _reader(employee, "Комментатор")
    lost_id, lost_title = _published(lost.page, rubric)
    dismissed_id, dismissed_title = _published(dismissed.page, rubric)
    # дано: письмо у обоих приходит в любое время суток (до увольнения: после него сессии закрыты)
    _save_prefs(lost.page, quiet="none")
    _save_prefs(dismissed.page, quiet="none")
    seen_lost, seen_dismissed = _mail_ids(mailpit, lost.email), _mail_ids(mailpit, dismissed.email)
    # дано: один автор потерял право, другой уволен
    _set_role(admin_page, lost.id, helpers_kb.EDITOR_ROLE, False)
    assert lost.page.goto("/kb/new/").status == 403, "право «Редактирование базы знаний» не снято"
    _dismiss(admin_page, dismissed.id)
    # когда: другой сотрудник комментирует обе статьи
    helpers_kb.add_comment(other.page, dismissed_id, "Комментарий к статье уволенного.")
    helpers_kb.add_comment(other.page, lost_id, "Комментарий к статье потерявшего право.")
    # п. 9: потерявший право получает уведомление на портале
    rows = _wait_rows(lost.page, lost_title, 1)
    expect(rows.first.locator('[data-field="text"]')).to_have_text(_comment_text(lost_title))
    # п. 9: и письмо (срок письма прошёл)
    helpers_notify.tick(shift=PAST_ANY_TERM)
    mail = helpers_kb.kb_item_mail(mailpit, lost.email, seen=seen_lost)
    assert lost_title in mail["Text"], "в письме потерявшему право нет заголовка его статьи"
    # п. 9: уволенному письма нет (контроль — письмо потерявшему право уже получено после того же сдвига срока)
    assert helpers_notify.no_item_mail(mailpit, dismissed.email, seen=seen_dismissed, wait=10), \
        "уволенному ушло письмо об уведомлении"


def test_k09_author_subscribed_to_own_rubric_gets_single_changed_notification_not_two(admin_page, employee):
    """Сценарий 9, п. 10: автор подписан на рубрику своей статьи — другой сотрудник сохраняет правку опубликованной
    статьи: автор получает одно уведомление «Мою статью изменили», а не два (FR-435)."""
    rubric_id, rubric = _rubric(admin_page)
    author, editor = _editor(employee, "Автор"), _editor(employee, "Правщик")
    _subscribe(author.page, rubric_id)
    article_id, title = _published(author.page, rubric)
    # публикация — действие самого автора: по подписке ему ничего (исполнитель)
    _no_rows(author.page, title)
    # п. 10: другой сотрудник сохраняет правку опубликованной статьи
    _edit_text(editor.page, article_id, "Текст после правки другого сотрудника.")
    # п. 10: одно уведомление, и это «Мою статью изменили»
    rows = _wait_rows(author.page, title, 1)
    expect(rows.first.locator('[data-field="kind"]')).to_have_text(TITLE_CHANGED)
    expect(rows.first.locator('[data-field="text"]')).to_have_text(_changed_text(title, editor.full_name))


def test_k09_subscriber_of_rubric_and_its_subrubric_gets_single_notification_on_publish(admin_page, employee):
    """Сценарий 9, п. 11: сотрудник подписан на рубрику «Сеть» и на её подрубрику «VPN» — в «VPN» публикуется статья:
    одно уведомление «Статья в рубрике по подписке» (FR-435, FR-437)."""
    root_id, root = _rubric(admin_page, "Сеть")
    child_id, child = _rubric(admin_page, "VPN", parent_name=root)
    author, subscriber = _editor(employee, "Автор"), _reader(employee, "Подписчик")
    _subscribe(subscriber.page, root_id)
    _subscribe(subscriber.page, child_id)
    # п. 11: в подрубрике публикуется статья
    _article_id, title = _published(author.page, child)
    # п. 11: ровно одно уведомление нужного вида, с названием ближайшей к статье рубрики подписки — подрубрики (п. 51)
    rows = _wait_rows(subscriber.page, title, 1)
    expect(rows.first.locator('[data-field="kind"]')).to_have_text(TITLE_RUBRIC)
    expect(rows.first.locator('[data-field="text"]')).to_have_text(_rubric_text(child, title))


def test_k09_employee_without_edit_right_and_own_articles_sees_only_rubric_subscription_kind(admin_page, employee):
    """Сценарий 9, п. 12: сотрудник без права «Редактирование базы знаний» и без своих статей открывает «Мои уведомления» —
    из видов модуля «База знаний» ему виден только «Статья в рубрике по подписке» (FR-434). Контроль: редактору те же три
    вида видны."""
    reader, editor = _reader(employee), _editor(employee)
    # п. 12: у читателя — единственная строка вида базы знаний
    reader.page.goto("/me/notifications/")
    table = reader.page.locator("table[data-notify-table]")
    expect(table).to_be_visible()
    kb_rows = table.locator('tr[data-notify-kind^="knowledge."]')
    expect(kb_rows).to_have_count(1)
    expect(kb_rows.first).to_have_attribute("data-notify-kind", KIND_RUBRIC)
    expect(kb_rows.first.locator('[data-field="title"]')).to_have_text(TITLE_RUBRIC)
    expect(kb_rows.first.locator('[data-field="module"]')).to_have_text(MODULE)
    expect(table.locator(f'tr[data-notify-kind="{KIND_COMMENT}"]')).to_have_count(0)
    expect(table.locator(f'tr[data-notify-kind="{KIND_CHANGED}"]')).to_have_count(0)
    # контроль: у редактора — все три
    editor.page.goto("/me/notifications/")
    expect(editor.page.locator('table[data-notify-table] tr[data-notify-kind^="knowledge."]')).to_have_count(3)


def test_k09_fresh_install_defaults_portal_and_mail_on_for_three_kinds_and_admin_can_change_them(
        admin_page, employee):
    """Сценарий 9, п. 13: у трёх видов по умолчанию включены «На портале» и «Почта» (прочие каналы выключены), и
    администратор может их изменить данными: новое значение видит сотрудник, не менявший таблицу (FR-434; SPEC-004
    FR-322). Значение возвращается в `finally`."""
    editor = _editor(employee, "Редактор")

    def admin_cell(kind: str, channel: str):
        return admin_page.locator(
            f'table[data-defaults-table] tr[data-notify-kind="{kind}"] td[data-channel="{channel}"] '
            f'input[type=checkbox][name="cell"][value="{kind}:{channel}"]')

    def admin_open() -> None:
        admin_page.goto("/settings/notifications/")
        expect(admin_page.locator('form[data-form="notify-settings"]')).to_be_visible()

    def admin_set_comment_email(state: bool) -> None:
        admin_open()
        admin_cell(KIND_COMMENT, "email").set_checked(state)
        with admin_page.expect_navigation():
            admin_page.locator('form[data-form="notify-settings"] button[type=submit][data-action="save-settings"]'
                               ).click()
        admin_page.wait_for_load_state()
        refusals = admin_page.locator("[data-error][data-code]")
        assert not refusals.count(), f"значения не сохранены: {refusals.first.get_attribute('data-code')}"
        expect(admin_page.locator("[role=status]").filter(has_text=SAVED).first).to_be_visible()

    # п. 13: страница администратора — у трёх видов «Почта» включена, остальные внешние выключены
    admin_open()
    for code, _title in KINDS:
        row = admin_page.locator(f'table[data-defaults-table] tr[data-notify-kind="{code}"]')
        expect(row).to_have_count(1)
        expect(admin_cell(code, "email")).to_be_checked()
        for channel in ("push", "telegram", "max"):
            expect(admin_cell(code, channel)).not_to_be_checked()
    original_state = admin_cell(KIND_COMMENT, "email").is_checked()
    # п. 13: «На портале» включён у трёх видов у сотрудника, не менявшего таблицу (столбец закреплён); «Почта» стоит
    editor.page.goto("/me/notifications/")
    for code, _title in KINDS:
        portal = editor.page.locator(f'table[data-notify-table] tr[data-notify-kind="{code}"] td[data-channel="portal"]')
        expect(portal).to_have_attribute("data-locked", "1")
        expect(portal.locator("input[type=checkbox]")).to_be_checked()
        expect(_cell(editor.page, code, "email")).to_be_checked()
        for channel in ("push", "telegram", "max"):
            expect(_cell(editor.page, code, channel)).not_to_be_checked()
    try:
        # п. 13: администратор меняет значение данными (снимает «Почту» у «Нового комментария»)
        admin_set_comment_email(not original_state)
        admin_open()
        expect(admin_cell(KIND_COMMENT, "email")).to_be_checked(checked=not original_state)
        expect(admin_cell(KIND_CHANGED, "email")).to_be_checked()
        # п. 13: сотрудник, не менявший таблицу, видит новое значение; остальные виды не тронуты
        editor.page.goto("/me/notifications/")
        expect(_cell(editor.page, KIND_COMMENT, "email")).to_be_checked(checked=not original_state)
        expect(_cell(editor.page, KIND_CHANGED, "email")).to_be_checked()
        # контроль: сотрудник, заведённый после изменения, видит то же
        newcomer = _editor(employee, "Новичок")
        newcomer.page.goto("/me/notifications/")
        expect(_cell(newcomer.page, KIND_COMMENT, "email")).to_be_checked(checked=not original_state)
    finally:
        admin_set_comment_email(original_state)
