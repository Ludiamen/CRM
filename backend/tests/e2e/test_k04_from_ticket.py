"""T-5143: сценарий 4 — статья из решения заявки, связь с заявкой, ссылка во внутреннем комментарии, защита от ПДн
(FR-409, FR-427, FR-428, FR-429, FR-430, FR-431, FR-432, FR-444, FR-448).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-005.md):
- каждый тест заводит свои заявки (письмом в ящик заявок: стандартная библиотека и `helpers_sd.deliver`), своих
  сотрудников (участники очереди по умолчанию: так они видят заявки) и свои статьи; названия уникальны;
- управляющий — администратор круга `admin_page` (он участник любой очереди и держит `servicedesk.all`);
  редактор — «Сотрудник ИТ» (`knowledge.edit`), читатель — «Руководитель» (прав базы знаний нет);
- адреса почты и телефоны для проб ПДн собираются из частей (решение 17 задач);
- общих настроек тесты не меняют: сроки автозакрытия и хранения заявок только читаются, заявки сдвигаются командами
  стенда `e2e_backdate` и `e2e_run_job` (`helpers_sd.backdate`, `helpers_sd.run_job`); `stand_shell` в файле нет.
"""
import re
import secrets
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.e2e.helpers_kb import (
    article_form, article_id_from_url, create_draft, home_ids, make_editor, make_reader, open_article, open_edit,
    open_history, press_publish_in_form, press_save, publish_from_article_page, search_hrefs, unique_word)

HIDDEN = "[скрыто]"
PART = 'div[data-card-part="kb-articles"]'
EDIT_URL = re.compile(r"/kb/\d+/edit/$")
ARTICLE_URL = re.compile(r"/kb/\d+/$")


# --- Свои помощники файла ---------------------------------------------------------------------------------

def _norm(text: str) -> str:
    return " ".join(text.split())


def _mail_address() -> str:
    """Адрес почты для пробы ПДн, собранный из частей (решение 17)."""
    return "ivanov" + secrets.token_hex(2) + "@" + "example" + ".ru"


def _phone_plus7() -> str:
    return "+7 (912) " + "345-67" + "-89"


def _phone_8() -> str:
    return "8 (912) " + "345-67" + "-89"


def _phone_plus7_dashes() -> str:
    return "+7-912-" + "345-67" + "-89"


def _raw_mail(sender: str, subject: str, body: str, *, from_name: str = "") -> bytes:
    """Письмо заявителя (RFC 822) на стандартной библиотеке: тема — через `Header` (не теряет пробелов)."""
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = formataddr((from_name, sender)) if from_name else sender
    msg["To"] = MAILBOX
    msg["Subject"] = Header(subject, "utf-8")
    msg["Date"] = formatdate()
    msg["Message-ID"] = make_msgid(domain="client.test")
    return msg.as_bytes()


def _new_ticket(admin_page, *, subject: str | None = None, word: str | None = None, body: str | None = None,
                from_name: str = "") -> tuple:
    """Заявка письмом корпоративного заявителя; возвращает `(номер, тема, слово, адрес заявителя)`. Слово — буквы без
    цифр (поиск по теме не принимает его за номер); оно входит в тему."""
    word = word or unique_word("tk")
    subject = subject or f"Не работает принтер {word}"
    sender = helpers_sd.requester_email()
    helpers_sd.deliver(_raw_mail(sender, subject, body or f"Описание сбоя {word}", from_name=from_name))
    return helpers_sd.ticket_number_by_subject(admin_page, word), subject, word, sender


def _close(page, number: int, resolution: str) -> None:
    """Закрытие заявки диалогом `ticket-close` с текстом решения; ждёт вид «закрыта»."""
    helpers_sd.open_ticket(page, number)
    page.locator('a[data-action="ticket-close"]').click()
    dialog = page.locator('[data-dialog="ticket-close"]')
    expect(dialog).to_be_visible()
    dialog.locator("textarea[name=resolution]").fill(resolution)
    dialog.locator("button[type=submit]").click()
    expect(page.locator(f'[data-ticket-card][data-number="{number}"]')).to_have_attribute("data-kind", "closed")


def _closed_ticket(admin_page, resolution: str, **kwargs) -> tuple:
    """Заявка, закрытая администратором с решением; возвращает то же, что `_new_ticket`."""
    made = _new_ticket(admin_page, **kwargs)
    _close(admin_page, made[0], resolution)
    return made


def _person(admin_page, employee, queue_id, maker, *, member: bool = True) -> tuple:
    """Сотрудник с уникальной частью ФИО; `member` — участник очереди (видит её заявки). Возвращает `(учётка, часть ФИО)`."""
    mark = secrets.token_hex(3)
    account = maker(employee, full_name=f"Тест{mark} Иванов Иван")
    if member:
        note = helpers_sd.add_queue_member(admin_page, queue_id, [account.id], q=f"Тест{mark}")
        assert "уже участник" not in note, note
    return account, mark


def _published(admin_page) -> tuple:
    """Опубликованная статья в рубрике «Общее» (пишет и публикует управляющий); возвращает `(номер, заголовок, слово)`."""
    word = unique_word("kb")
    title = f"Статья про принтер {word}"
    article_id = create_draft(admin_page, title=title, rubric="Общее")
    publish_from_article_page(admin_page, article_id)
    return article_id, title, word


def _from_solution(page, number: int) -> str:
    """Карточка заявки, «Статья из решения», ждёт редактор черновика; возвращает номер статьи."""
    helpers_sd.open_ticket(page, number)
    page.locator('form[data-form="kb-from-ticket"] button[data-action="kb-from-ticket"]').click()
    page.wait_for_url(EDIT_URL)
    expect(page.locator('[data-kb-page="edit"]')).to_be_visible()
    return article_id_from_url(page.url)


def _link_article(page, number: int, article_id, word: str) -> None:
    """«Привязать статью»: поиск по слову заголовка в разделе «Статьи», выбор строки, ждёт строку связи."""
    helpers_sd.open_ticket(page, number)
    part = page.locator(PART)
    part.locator('form[data-form="kb-link"] input[name="pick"]').fill(word)
    row = part.locator(f'ul[data-kb-pick-results] li[data-article-id="{article_id}"]')
    expect(row).to_have_count(1)
    row.locator('button[data-action="kb-link-add"]').click()
    expect(page.locator(PART).locator(f'li[data-link-id][data-article-id="{article_id}"]')).to_have_count(1)


def _link_row(page, article_id):
    return page.locator(PART).locator(f'li[data-link-id][data-article-id="{article_id}"]')


def _pdn_items(page) -> list:
    """Найденное из предупреждения ПДн: тексты `li[data-pdn-item]` внутри `[data-kb-pdn]`."""
    box = page.locator("[data-kb-pdn]")
    expect(box).to_be_visible()
    return [_norm(li.inner_text()) for li in box.locator("li[data-pdn-item]").all()]


def _article_tickets(page, article_id):
    open_article(page, article_id)
    return page.locator("[data-kb-tickets]")


def _article_state(page, article_id) -> str:
    open_article(page, article_id)
    return page.locator(f'article[data-article-id="{article_id}"]').get_attribute("data-article-state")


# --- Тесты ------------------------------------------------------------------------------------------------

def test_k04_from_solution_creates_draft_with_ticket_subject_solution_text_and_general_rubric_without_requester_linked_to_ticket(
        admin_page, employee):
    """Сценарий 4, п. 1: закрытая с решением заявка, исполнитель с правом «Редактирование» нажимает «Статья из решения»
    — черновик: заголовок — тема, текст — решение, рубрика «Общее», без заявителя, адресов и переписки, связан с
    заявкой, открыт редактор (FR-427)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    editor, _ = _person(admin_page, employee, queue_id, make_editor)
    page = editor.page
    requester_name = f"Заявителев{secrets.token_hex(3)} Пётр Сергеевич"
    body = f"Переписка заявителя {unique_word('mail')}"
    resolution = f"Заменили картридж {unique_word('res')}"
    number, subject, word, sender = _closed_ticket(admin_page, resolution, body=body, from_name=requester_name)
    # когда: исполнитель нажимает «Статья из решения»
    helpers_sd.open_ticket(page, number)
    expect(page.locator('div[data-card-part="kb-from-ticket"]')).to_have_count(1)
    expect(page.locator('form[data-form="kb-from-ticket"] button[data-action="kb-from-ticket"]')).to_contain_text(
        "Статья из решения")
    article_id = _from_solution(page, number)
    # п. 1: открыт редактор черновика; заголовок — тема, текст — решение, рубрика «Общее»
    form = article_form(page)
    assert _norm(form.locator("input[name=title]").input_value()) == _norm(subject)
    text = form.locator("textarea[name=text]").input_value()
    assert _norm(text) == _norm(resolution)
    assert "Общее" in form.locator("select[name=rubric] option:checked").inner_text()
    # п. 1: нет заявителя (адрес, имя) и переписки (текст письма)
    everything = form.locator("input[name=title]").input_value() + " " + text
    for private in (sender, requester_name.split()[0], body):
        assert private not in everything, f"в черновике есть данные заявки: {private}"
    # п. 1: черновик связан с заявкой — на странице статьи и в карточке заявки
    expect(_article_tickets(page, article_id).locator(f'li[data-ticket-number="{number}"]')).to_have_count(1)
    assert _article_state(page, article_id) == "draft"
    helpers_sd.open_ticket(page, number)
    row = _link_row(page, article_id)
    expect(row).to_have_count(1)
    expect(row.locator('[data-field="state"]')).to_contain_text("черновик")
    # версия 1 — с комментарием «Создано из заявки #N» (12.1)
    open_history(page, article_id)
    expect(page.locator('tr[data-version="1"] [data-field="comment"]')).to_contain_text(
        f"Создано из заявки #{number}")
    expect(page.locator("tr[data-version]")).to_have_count(1)
    assert home_ids(page, "my-drafts").count(article_id) == 1


def test_k04_email_and_phone_in_subject_and_solution_are_replaced_with_hidden_mark(admin_page, employee):
    """Сценарий 4, п. 2: в теме и решении почта и телефон — в черновике на их месте «[скрыто]» (FR-428)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    editor, _ = _person(admin_page, employee, queue_id, make_editor)
    page = editor.page
    word = unique_word("tk")
    mail_in_subject, mail_in_text, phone = _mail_address(), _mail_address(), _phone_plus7()
    subject = f"Принтер {word} пишите {mail_in_subject}"
    resolution = f"Позвоните {phone} или напишите {mail_in_text}"
    number, _, _, _ = _closed_ticket(admin_page, resolution, subject=subject, word=word)
    # когда: создаётся черновик
    _from_solution(page, number)
    form = article_form(page)
    title = form.locator("input[name=title]").input_value()
    text = form.locator("textarea[name=text]").input_value()
    # п. 2: вместо найденного — «[скрыто]», остальное на месте
    assert _norm(title) == f"Принтер {word} пишите {HIDDEN}"
    assert _norm(text) == f"Позвоните {HIDDEN} или напишите {HIDDEN}"
    for raw in (mail_in_subject, mail_in_text, phone):
        assert raw not in title + " " + text, "в черновике осталось найденное"
    assert "345-67-89" not in text


def test_k04_from_solution_button_absent_on_open_ticket_and_on_auto_closed_ticket_without_solution(
        admin_page, employee):
    """Сценарий 4, п. 3: в открытой заявке кнопки «Статья из решения» нет; в закрытой автоматически (без решения) её
    тоже нет; в закрытой с решением — есть (FR-427)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    editor, _ = _person(admin_page, employee, queue_id, make_editor)
    page = editor.page
    button = 'button[data-action="kb-from-ticket"]'
    # открытая заявка
    open_number, _, _, _ = _new_ticket(admin_page)
    card = helpers_sd.open_ticket(page, open_number)
    expect(card).to_have_attribute("data-kind", "new")
    expect(page.locator(button)).to_have_count(0)
    # закрытая автоматически: ответ исполнителя «ждём ответа», срок вышел, задание автозакрытия
    auto_number, _, auto_word, _ = _new_ticket(admin_page)
    helpers_sd.open_ticket(admin_page, auto_number)
    admin_page.goto("/servicedesk/")
    form = admin_page.locator('form[data-form="servicedesk-settings"]')
    expect(form).to_be_visible()
    term = int(form.locator("input[name=autoclose_days]").input_value())
    reply = helpers_sd.open_ticket(admin_page, auto_number).locator('form[data-form="ticket-reply"]')
    reply.locator("textarea[name=text]").fill(f"Уточните, пожалуйста {auto_word}")
    reply.locator("input[type=checkbox][name=wait]").check()
    helpers.submit(reply)
    expect(admin_page.locator(f'[data-ticket-card][data-number="{auto_number}"] li[data-entry][data-kind="reply"]')
           ).to_have_count(1)
    helpers_sd.backdate("ticket", auto_number, "waiting_since", term + 1)
    helpers_sd.run_job("autoclose")
    card = helpers_sd.open_ticket(page, auto_number)
    expect(card).to_have_attribute("data-kind", "closed")
    expect(page.locator(button)).to_have_count(0)
    expect(page.locator('form[data-form="kb-from-ticket"]')).to_have_count(0)
    # контроль: закрытая с решением — кнопка есть (иначе «нет кнопки» ничего не доказывает)
    closed_number, _, _, _ = _closed_ticket(admin_page, f"Решено {unique_word('res')}")
    helpers_sd.open_ticket(page, closed_number)
    expect(page.locator(button)).to_have_count(1)


def test_k04_employee_without_edit_right_sees_no_from_solution_button_and_direct_call_is_denied(
        admin_page, employee):
    """Сценарий 4, п. 4: сотрудник без права «Редактирование базы знаний» видит карточку закрытой заявки без кнопки
    «Статья из решения»; прямое обращение — отказ 403 (FR-427, FR-409)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    reader, _ = _person(admin_page, employee, queue_id, make_reader)
    number, _, _, _ = _closed_ticket(admin_page, f"Решено {unique_word('res')}")
    # контроль: управляющему кнопка в той же карточке есть
    helpers_sd.open_ticket(admin_page, number)
    expect(admin_page.locator('button[data-action="kb-from-ticket"]')).to_have_count(1)
    # читатель видит саму карточку (иначе отказ был бы «404 заявки нет», а не отказ по праву), кнопки нет
    card = helpers_sd.open_ticket(reader.page, number)
    expect(card).to_have_attribute("data-kind", "closed")
    expect(reader.page.locator('button[data-action="kb-from-ticket"]')).to_have_count(0)
    expect(reader.page.locator('form[data-form="kb-from-ticket"]')).to_have_count(0)
    # прямое обращение — отказ по праву
    response = helpers_org.direct_post(reader.page, f"/kb/from-ticket/{number}/")
    assert response.status == 403, f"прямой вызов читателем: {response.status}"


def test_k04_ticket_card_articles_section_shows_published_linked_articles_and_draft_only_to_author_and_managers(
        admin_page, employee):
    """Сценарий 4, п. 5: в разделе «Статьи» карточки заявки видны опубликованные связанные статьи; черновик виден
    только автору и управляющим (FR-429)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    author, _ = _person(admin_page, employee, queue_id, make_editor)
    other, _ = _person(admin_page, employee, queue_id, make_editor)
    reader, _ = _person(admin_page, employee, queue_id, make_reader)
    number, _, _, _ = _closed_ticket(admin_page, f"Решено {unique_word('res')}")
    published_id, _, published_word = _published(admin_page)
    _link_article(admin_page, number, published_id, published_word)
    draft_id = _from_solution(author.page, number)
    # автор: оба; черновик с пометкой «черновик», у опубликованной пометки нет (раздел 17, п. 44)
    helpers_sd.open_ticket(author.page, number)
    expect(_link_row(author.page, published_id)).to_have_count(1)
    expect(_link_row(author.page, published_id).locator('[data-field="state"]')).to_have_count(0)
    expect(_link_row(author.page, draft_id)).to_have_count(1)
    expect(_link_row(author.page, draft_id).locator('[data-field="state"]')).to_contain_text("черновик")
    # управляющий: оба
    helpers_sd.open_ticket(admin_page, number)
    expect(_link_row(admin_page, published_id)).to_have_count(1)
    expect(_link_row(admin_page, draft_id)).to_have_count(1)
    # другой редактор и читатель: только опубликованная
    for viewer in (other, reader):
        helpers_sd.open_ticket(viewer.page, number)
        expect(viewer.page.locator(PART)).to_have_count(1)
        expect(_link_row(viewer.page, published_id)).to_have_count(1)
        expect(_link_row(viewer.page, draft_id)).to_have_count(0)
    # читатель без права «Редактирование»: ни «Привязать», ни «Отвязать»
    expect(reader.page.locator(PART + ' form[data-form="kb-link"]')).to_have_count(0)
    expect(reader.page.locator(PART + ' button[data-action="kb-unlink"]')).to_have_count(0)


def test_k04_attach_article_by_title_search_links_both_sides_shows_who_and_when_and_related_ticket_row(
        admin_page, employee):
    """Сценарий 4, п. 6: «Привязать статью», поиск по названию, выбор опубликованной статьи — связь с заявкой (видно, кто
    и когда), а в статье в «Связанных заявках» строка «#N Тема» (FR-429)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    editor, mark = _person(admin_page, employee, queue_id, make_editor)
    other, _ = _person(admin_page, employee, queue_id, make_reader)
    number, subject, _, _ = _new_ticket(admin_page)
    article_id, title, word = _published(admin_page)
    page = editor.page
    # когда: исполнитель ищет по названию и привязывает
    _link_article(page, number, article_id, word)
    # п. 6: в карточке — статья со ссылкой, кто и когда привязал
    row = _link_row(page, article_id)
    expect(row.locator('a[data-field="title"]')).to_contain_text(title)
    expect(row.locator('[data-field="linked-by"]')).to_contain_text(mark)
    expect(row.locator("time[data-at]")).to_have_count(1)
    # обновление страницы: связь не пропала
    helpers_sd.open_ticket(page, number)
    expect(_link_row(page, article_id)).to_have_count(1)
    # п. 6: в статье — строка «#N Тема» у тех, кто видит заявку
    for viewer in (page, other.page):
        line = _article_tickets(viewer, article_id).locator(f'li[data-ticket-number="{number}"]')
        expect(line).to_have_count(1)
        expect(line.locator(f'a[href="/tickets/{number}/"]')).to_have_count(1)
        text = _norm(line.inner_text())
        assert f"#{number}" in text and _norm(subject) in text, text


def test_k04_detach_article_removes_link_on_both_sides_and_keeps_article(admin_page, employee):
    """Сценарий 4, п. 7: «Отвязать» — связи нет с обеих сторон; статья на месте (FR-429)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    editor, _ = _person(admin_page, employee, queue_id, make_editor)
    number, _, _, _ = _new_ticket(admin_page)
    article_id, title, word = _published(admin_page)
    page = editor.page
    _link_article(page, number, article_id, word)
    expect(_article_tickets(page, article_id).locator(f'li[data-ticket-number="{number}"]')).to_have_count(1)
    helpers_sd.open_ticket(page, number)
    page.on("dialog", lambda dialog: dialog.accept())  # подтверждение `hx-confirm`, если оно есть
    # когда: исполнитель нажимает «Отвязать»
    _link_row(page, article_id).locator('button[data-action="kb-unlink"]').click()
    expect(_link_row(page, article_id)).to_have_count(0)
    # п. 7: связи нет с обеих сторон
    helpers_sd.open_ticket(page, number)
    expect(page.locator(PART + " li[data-link-id]")).to_have_count(0)
    expect(_article_tickets(page, article_id).locator(f'li[data-ticket-number="{number}"]')).to_have_count(0)
    # п. 7: статья осталась опубликованной и открывается
    assert _article_state(page, article_id) == "published"
    expect(page.locator('h1[data-field="title"]')).to_contain_text(title)


def test_k04_employee_without_ticket_access_does_not_see_the_ticket_in_article_related_tickets(
        admin_page, employee):
    """Сценарий 4, п. 8: сотрудник без доступа к заявке открывает связанную статью — заявки #N в «Связанных заявках»
    нет (FR-429; SPEC-003 FR-236)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    member, _ = _person(admin_page, employee, queue_id, make_editor)
    outsider, _ = _person(admin_page, employee, queue_id, make_editor, member=False)
    number, _, _, _ = _new_ticket(admin_page)
    article_id, title, word = _published(admin_page)
    _link_article(admin_page, number, article_id, word)
    # контроль: участник очереди заявку видит и строку видит
    expect(_article_tickets(member.page, article_id).locator(f'li[data-ticket-number="{number}"]')).to_have_count(1)
    # заявка недоступна посторонним (404, как у несуществующей)
    assert helpers_org.direct_get(outsider.page, f"/tickets/{number}/").status == 404
    # п. 8: посторонний открывает статью; заявки в списке нет
    open_article(outsider.page, article_id)
    expect(outsider.page.locator('h1[data-field="title"]')).to_contain_text(title)
    expect(outsider.page.locator(f'[data-kb-tickets] li[data-ticket-number="{number}"]')).to_have_count(0)
    assert f"/tickets/{number}/" not in outsider.page.content()


def test_k04_article_link_button_in_internal_comment_form_inserts_article_address_into_comment_text(
        admin_page):
    """Сценарий 4, п. 9: в форме внутреннего комментария «Ссылка на статью», выбор статьи — в тексте комментария
    «Заголовок: полный адрес статьи» (FR-430, FR-432)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    number, _, _, _ = _new_ticket(page)
    article_id, title, word = _published(page)
    draft_id = create_draft(page, title=f"Черновик про принтер {word}", rubric="Общее")
    helpers_sd.open_ticket(page, number)
    form = page.locator('form[data-form="ticket-comment"]')
    # когда: «Ссылка на статью», поиск, выбор
    form.locator('button[data-action="kb-link-tool"]').click()
    form.locator('input[name="pick"]').fill(word)
    row = form.locator(f'ul[data-kb-pick-results] li[data-article-id="{article_id}"]')
    expect(row).to_have_count(1)
    origin = page.evaluate("location.origin")
    assert row.get_attribute("data-title") == title
    url = row.get_attribute("data-url")
    assert url == f"{origin}/kb/{article_id}/", f"адрес в строке подбора: {url}"
    row.click()
    # п. 9: в тексте комментария — «Заголовок: адрес»
    field = form.locator("textarea[name=text]")
    assert f"{title}: {url}" in field.input_value()
    # черновик подбор не выдаёт: общее слово, ждём строку опубликованной, затем нет строки черновика
    form.locator('input[name="pick"]').fill("")
    form.locator('input[name="pick"]').fill(word)
    expect(form.locator(f'ul[data-kb-pick-results] li[data-article-id="{article_id}"]')).to_have_count(1)
    expect(form.locator(f'ul[data-kb-pick-results] li[data-article-id="{draft_id}"]')).to_have_count(0)
    # комментарий отправлен: в ленте — адрес статьи
    form.locator("button[type=submit]").click()
    entry = page.locator('li[data-kind="comment"] [data-entry-text]')
    expect(entry.first).to_contain_text(url)


def test_k04_publish_or_save_of_published_article_with_email_or_phone_warns_with_list_and_two_buttons_and_publishes_after_confirm(
        admin_page, employee):
    """Сценарий 4, п. 10: «Опубликовать» (и «Сохранить» опубликованной) при почте или телефоне в тексте — предупреждение
    со списком найденного и двумя кнопками; публикация после подтверждения (FR-431)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    author, _ = _person(admin_page, employee, queue_id, make_editor, member=False)
    page = author.page
    mail, phone = _mail_address(), _phone_plus7()
    title = f"Контакты принтера {unique_word('kb')}"
    article_id = create_draft(page, title=title, rubric="Общее", text=f"Пишите {mail} или звоните {phone}")
    # когда: «Опубликовать»
    press_publish_in_form(page)
    items = _pdn_items(page)
    # п. 10: список найденного и две кнопки
    assert any(mail in i for i in items) and any(phone in i for i in items), items
    back = page.locator('[data-kb-pdn] button[data-action="kb-pdn-back"]')
    confirm = page.locator('[data-kb-pdn] button[data-action="kb-pdn-confirm"]')
    expect(back).to_contain_text("Вернуться к правке")
    expect(confirm).to_contain_text("Опубликовать всё равно")
    # «Вернуться к правке»: форма без отправки, текст на месте, статья — черновик
    back.click()
    expect(page.locator("[data-kb-pdn]")).to_be_hidden()
    assert mail in article_form(page).locator("textarea[name=text]").input_value()
    assert _article_state(page, article_id) == "draft"
    # «Опубликовать всё равно»: публикация после подтверждения
    open_edit(page, article_id)
    press_publish_in_form(page)
    _pdn_items(page)
    page.locator('[data-kb-pdn] button[data-action="kb-pdn-confirm"]').click()
    page.wait_for_url(ARTICLE_URL)
    expect(page.locator(f'article[data-article-id="{article_id}"][data-article-state="published"]')).to_be_visible()
    # «Сохранить» опубликованной: то же предупреждение, кнопка «Сохранить всё равно»
    open_edit(page, article_id)
    article_form(page).locator("textarea[name=text]").fill(f"Пишите {mail} или звоните {phone}. Дополнено.")
    press_save(page)
    assert any(mail in i for i in _pdn_items(page))
    expect(page.locator('[data-kb-pdn] button[data-action="kb-pdn-back"]')).to_contain_text("Вернуться к правке")
    again = page.locator('[data-kb-pdn] button[data-action="kb-pdn-confirm"]')
    expect(again).to_contain_text("Сохранить всё равно")
    again.click()
    page.wait_for_url(ARTICLE_URL)
    expect(page.locator('[data-field="body"]')).to_contain_text("Дополнено")
    expect(page.locator(f'article[data-article-id="{article_id}"][data-article-state="published"]')).to_be_visible()


def test_k04_pdn_in_title_triggers_the_same_warning_on_publish(admin_page, employee):
    """Сценарий 4, п. 11: ПДн в заголовке — при «Опубликовать» то же предупреждение (FR-431)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    author, _ = _person(admin_page, employee, queue_id, make_editor, member=False)
    page = author.page
    mail = _mail_address()
    title = f"Доступ для {mail} {unique_word('kb')}"
    article_id = create_draft(page, title=title, rubric="Общее", text="Текст без персональных данных.")
    # когда: «Опубликовать»
    press_publish_in_form(page)
    # п. 11: предупреждение с найденным из заголовка и двумя кнопками
    assert any(mail in i for i in _pdn_items(page))
    expect(page.locator('[data-kb-pdn] button[data-action="kb-pdn-back"]')).to_contain_text("Вернуться к правке")
    confirm = page.locator('[data-kb-pdn] button[data-action="kb-pdn-confirm"]')
    expect(confirm).to_contain_text("Опубликовать всё равно")
    assert _article_state(page, article_id) == "draft"
    open_edit(page, article_id)
    press_publish_in_form(page)
    _pdn_items(page)
    page.locator('[data-kb-pdn] button[data-action="kb-pdn-confirm"]').click()
    page.wait_for_url(ARTICLE_URL)
    expect(page.locator(f'article[data-article-id="{article_id}"][data-article-state="published"]')).to_be_visible()


def test_k04_depersonalized_ticket_link_keeps_number_and_subject_and_link_is_not_lost(admin_page):
    """Сценарий 4, п. 12: заявка обезличена по сроку — старая связь на месте, ссылка на заявку работает, номер и тема
    остались (FR-429, FR-448)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    number, subject, _, sender = _new_ticket(page)
    article_id, title, word = _published(page)
    _link_article(page, number, article_id, word)
    _close(page, number, f"Решено {unique_word('res')}")
    page.goto("/servicedesk/")
    form = page.locator('form[data-form="servicedesk-settings"]')
    expect(form).to_be_visible()
    years = int(form.locator("input[name=retention_years]").input_value())
    # когда: срок хранения вышел, ночное обезличивание выполнено
    helpers_sd.backdate("ticket", number, "closed_at", years * 366 + 20)
    helpers_sd.run_job("anonymize_tickets")
    card = helpers_sd.open_ticket(page, number)
    assert "обезличено" in helpers_sd.field_text(card, "requester-email")  # заявка обезличена (контроль)
    assert sender not in card.inner_text()
    # п. 12: связь не пропала, в карточке и в статье; в статье — «#N Тема», ссылка открывает заявку
    expect(_link_row(page, article_id)).to_have_count(1)
    line = _article_tickets(page, article_id).locator(f'li[data-ticket-number="{number}"]')
    expect(line).to_have_count(1)
    text = _norm(line.inner_text())
    assert f"#{number}" in text and _norm(subject) in text, text
    line.locator("a").click()
    page.wait_for_url(re.compile(rf"/tickets/{number}/$"))
    expect(page.locator(f'[data-ticket-card][data-number="{number}"]')).to_be_visible()
    expect(page.locator(f'[data-ticket-card][data-number="{number}"] [data-field="subject"]')).to_contain_text(
        _norm(subject).split()[-1])


def test_k04_ticket_invisible_to_employee_is_not_found_by_subject_or_number_in_global_search(
        admin_page, employee):
    """Сценарий 4, п. 13: заявки, которой сотрудник не видит, нет в сквозном поиске ни по теме, ни по номеру (FR-444)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    member, _ = _person(admin_page, employee, queue_id, make_editor)
    outsider, _ = _person(admin_page, employee, queue_id, make_editor, member=False)
    number, subject, word, _ = _new_ticket(admin_page)
    href = f"/tickets/{number}/"
    # контроль: тому, кто заявку видит, поиск её находит — и по теме, и по номеру
    assert any(href in h for h in search_hrefs(member.page, word)), "участник очереди не нашёл заявку по теме"
    by_number = str(number) if number >= 10 else f"#{number}"  # строка короче двух знаков — подсказка, не поиск
    assert any(href in h for h in search_hrefs(member.page, by_number)), "участник не нашёл заявку по номеру"
    # п. 13: посторонний не находит
    found = search_hrefs(outsider.page, word)
    assert not any(href in h for h in found), "заявка найдена по теме"
    rows = '[data-search-page] section[data-search-group="tickets"] li[data-search-row]'
    expect(outsider.page.locator(rows)).to_have_count(0)
    found = search_hrefs(outsider.page, by_number)
    assert not any(href in h for h in found), "заявка найдена по номеру"
    expect(outsider.page.locator(rows)).to_have_count(0)
    assert helpers_org.direct_get(outsider.page, href).status == 404


def test_k04_address_only_in_code_block_or_inline_code_gives_no_warning_and_same_address_outside_code_does(
        admin_page, employee):
    """Сценарий 4, п. 14: `git@github.com` только в блоке кода и в коде в строке — предупреждения нет; тот же адрес вне
    кода — предупреждение (FR-428, FR-431)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    author, _ = _person(admin_page, employee, queue_id, make_editor, member=False)
    page = author.page
    address = "git" + "@" + "github.com"
    in_code = f"Клонируйте так:\n\n```\ngit clone {address}\n```\n\nили адрес `{address}` в строке."
    article_id = create_draft(page, title=f"Работа с репозиторием {unique_word('kb')}", rubric="Общее",
                              text=in_code)
    # когда: «Опубликовать» — адрес только в коде
    press_publish_in_form(page)
    page.wait_for_url(ARTICLE_URL)
    # п. 14: предупреждения нет, статья опубликована
    expect(page.locator(f'article[data-article-id="{article_id}"][data-article-state="published"]')).to_be_visible()
    expect(page.locator("[data-kb-pdn]")).to_have_count(0)
    # тот же адрес вне кода: «Сохранить» опубликованной — предупреждение с адресом
    open_edit(page, article_id)
    article_form(page).locator("textarea[name=text]").fill(in_code + f"\n\nПишите на {address} за доступом.")
    press_save(page)
    assert any(address in i for i in _pdn_items(page))
    page.locator('[data-kb-pdn] button[data-action="kb-pdn-back"]').click()
    expect(page.locator("[data-kb-pdn]")).to_be_hidden()


def test_k04_phone_variants_8_and_plus7_with_dashes_are_hidden_and_ten_digit_number_stays(admin_page, employee):
    """Сценарий 4, п. 15: «8 (912) …», «+7-912-…» заменены на «[скрыто]», десятизначное число осталось (FR-428)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    editor, _ = _person(admin_page, employee, queue_id, make_editor)
    page = editor.page
    inn = "7707" + "083893"
    resolution = f"Звонить {_phone_8()} либо {_phone_plus7_dashes()} ИНН {inn} конец"
    number, _, _, _ = _closed_ticket(admin_page, resolution)
    # когда: создаётся черновик
    _from_solution(page, number)
    text = article_form(page).locator("textarea[name=text]").input_value()
    # п. 15: оба телефона заменены, число осталось
    assert _norm(text) == f"Звонить {HIDDEN} либо {HIDDEN} ИНН {inn} конец", text
    assert text.count(HIDDEN) == 2
    assert "345-67-89" not in text and inn in text


def test_k04_repeat_from_solution_opens_existing_own_draft_with_message_and_creates_no_new_draft(
        admin_page, employee):
    """Сценарий 4, п. 16: у заявки уже есть свой связанный черновик из решения — повторное «Статья из решения» открывает
    его с сообщением, нового черновика нет (FR-427)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    editor, _ = _person(admin_page, employee, queue_id, make_editor)
    page = editor.page
    number, subject, word, _ = _closed_ticket(admin_page, f"Решено {unique_word('res')}")
    first_id = _from_solution(page, number)
    # когда: нажимает ещё раз
    second_id = _from_solution(page, number)
    # п. 16: открыт тот же черновик, сообщение; нового нет
    assert second_id == first_id
    expect(page.locator("[role=status]").filter(has_text="Черновик по этой заявке уже создан")).to_have_count(1)
    helpers_sd.open_ticket(page, number)
    expect(page.locator(PART + " li[data-link-id]")).to_have_count(1)
    page.goto("/kb/")
    mine = page.locator("[data-kb-my-drafts] li[data-article-id]").filter(has_text=word)
    expect(mine).to_have_count(1)
    assert home_ids(page, "my-drafts").count(first_id) == 1


def test_k04_repeat_from_solution_after_linked_article_published_creates_new_draft(admin_page, employee):
    """Сценарий 4, п. 17: связанная статья из решения уже опубликована — «Статья из решения» ещё раз создаёт новый
    черновик (FR-427)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    editor, _ = _person(admin_page, employee, queue_id, make_editor)
    page = editor.page
    number, _, _, _ = _closed_ticket(admin_page, f"Решено {unique_word('res')}")
    first_id = _from_solution(page, number)
    publish_from_article_page(page, first_id)
    # когда: нажимает ещё раз
    second_id = _from_solution(page, number)
    # п. 17: новый черновик, прежняя статья опубликована и связана
    assert second_id != first_id
    assert _article_state(page, second_id) == "draft"
    assert _article_state(page, first_id) == "published"
    helpers_sd.open_ticket(page, number)
    expect(_link_row(page, first_id)).to_have_count(1)
    expect(_link_row(page, second_id)).to_have_count(1)
    expect(page.locator(PART + " li[data-link-id]")).to_have_count(2)
