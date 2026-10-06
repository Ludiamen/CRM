"""T-3152: сквозная приёмка среза 003 — ширина 360 px, выдача файлов через nginx, опрос ящика по расписанию, русский язык
и время по Москве (NFR-201, NFR-207, NFR-208, FR-283).

Серверную разметку (viewport, lang, время по Москве) проверяет T-3133; здесь — настоящий стенд с nginx, Dovecot и
рабочими службами. Подготовка (письма, заявки) идёт через помощники `helpers_sd`.
"""
import re
import secrets
import time
import urllib.parse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_servicedesk import MailPart, build_mail

MOSCOW = ZoneInfo("Europe/Moscow")
TIME_FORMAT = "%d.%m.%Y %H:%M"
FILE_HREF = re.compile(r"^/tickets/(\d+)/files/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/$")
UI_TEXT_SELECTOR = "h1, h2, h3, label, legend, button, th, [data-field-label]"
# пользовательские данные (13.2, 13.3, 13.7, 13.8): значения полей, ячейки строк, элементы ленты, названия узлов
USER_DATA_SELECTOR = ("[data-field], [data-cell], [data-entry-text], [data-author], [data-unit-tree], "
                      "[data-participant], [data-candidate], [data-dictionary-row], [data-requester], "
                      "[data-inbound], [data-ticket], [data-attachment]")
MIN_UI_LETTERS = 20


def _word() -> str:
    """Уникальное слово темы: буква и шесть шестнадцатеричных знаков (доп. 41 (в): не из одних цифр)."""
    return f"t{secrets.token_hex(3)}"


def _message_id() -> str:
    return f"<{secrets.token_hex(8)}@client.test>"


def _cyrillic_share(text: str) -> float:
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text)
    if not letters:
        return 0.0
    return sum(1 for c in letters if re.match(r"[А-Яа-яЁё]", c)) / len(letters)


def _ui_text(page) -> str:
    """Текст элементов интерфейса без пользовательских данных."""
    texts = page.evaluate(
        """([selector, exclude]) => Array.from(document.querySelectorAll(selector))
            .filter(el => !el.closest(exclude))
            .map(el => el.innerText)""",
        [UI_TEXT_SELECTOR, USER_DATA_SELECTOR])
    return " ".join(texts)


def _deliver_ticket(page, *, subject_prefix: str = "Не печатает принтер", attachments=()) -> tuple:
    """Письмо заявителя корпоративного домена → заявка; возвращает (номер, слово темы, адрес заявителя,
    Message-ID, тема)."""
    word, sender, message_id = _word(), helpers_sd.requester_email(), _message_id()
    subject = f"{subject_prefix} {word}"
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=subject,
                                  text=f"Принтер на втором этаже не печатает {word}", message_id=message_id,
                                  attachments=list(attachments)))
    return helpers_sd.ticket_number_by_subject(page, word), word, sender, message_id, subject


def _submit_request_form(page, email: str, subject: str, text: str) -> None:
    """Открытая форма `/request/` (12.1, 13.6): заполняет обязательные поля, ставит согласие, отправляет и ждёт
    страницу «Заявка принята»."""
    page.goto("/request/")
    form = page.locator('form[data-form="request"]')
    expect(form).to_be_visible()
    form.locator("input[name=email]").fill(email)
    form.locator("input[name=name]").fill("Тестов Тест Тестович")
    values = form.locator("select[name=category] option").evaluate_all(
        "options => options.map(o => o.value).filter(v => v)")
    assert values, "в форме нет ни одной категории (в том числе «Другое»)"
    form.locator("select[name=category]").select_option(values[0])
    form.locator("input[name=subject]").fill(subject)
    form.locator("textarea[name=text]").fill(text)
    form.locator("input[name=consent]").check()
    helpers.submit(form)
    page.wait_for_url(re.compile(r"/request/done/$"))
    expect(page.locator("[data-request-done]")).to_be_visible()


def _first_id(page, path: str, row_selector: str):
    """`data-id` первой строки списка по адресу `path`."""
    page.goto(path)
    row = page.locator(row_selector).first
    expect(row).to_be_visible()
    return row.get_attribute("data-id")


def _moscow(iso: str) -> datetime:
    return datetime.fromisoformat(iso).astimezone(MOSCOW)


def _close_to_now(shown: datetime, now: datetime, minutes: int = 15) -> bool:
    return abs(shown - now) < timedelta(minutes=minutes)


def test_slice_pages_no_horizontal_scroll_at_360px(browser, browser_context_args, admin_page):
    """Сквозная приёмка, NFR-208: на ширине 360 px у всех страниц среза нет горизонтальной прокрутки — открытая
    форма и «Заявка принята» (гость), список заявок, карточка и форма «Новая заявка», настройки, очереди,
    справочники и формы значений, заявители, загрузка заявителей и её предпросмотр, «Входящие письма»
    (NFR-208, FR-283)."""
    queue_id, _queue_name = helpers_sd.ensure_ready(admin_page)
    number, word, sender, _mid, _subject = _deliver_ticket(admin_page)
    requester_id = _first_id(admin_page, "/servicedesk/requesters/?" + urllib.parse.urlencode({"q": sender}),
                             "tr[data-requester]")
    # форма правки — у категории, заведённой тестом (системная «Другое» ограничивает правку полей, 13.7)
    category_name = f"Узкая{secrets.token_hex(3)}"
    admin_page.goto("/servicedesk/dictionaries/categories/new/")
    category_form = admin_page.locator('form[data-form="dictionary"]')
    expect(category_form).to_be_visible()
    category_form.locator("input[name=name]").fill(category_name)
    category_form.locator("input[name=order]").fill("900")
    helpers_org.set_choice(category_form, "queue", queue_id)
    helpers.submit(category_form)
    admin_page.wait_for_url(re.compile(r"/servicedesk/dictionaries/categories/$"))
    category_row = admin_page.locator("tr[data-dictionary-row][data-id]").filter(
        has=admin_page.locator('[data-cell="name"]', has_text=category_name))
    expect(category_row).to_have_count(1)
    category_id = category_row.get_attribute("data-id")

    narrow = browser.new_context(**browser_context_args, viewport={"width": 360, "height": 800},
                                 storage_state=admin_page.context.storage_state())
    guest = browser.new_context(**browser_context_args, viewport={"width": 360, "height": 800})
    try:
        # п. 1: открытая форма и страница «Заявка принята» — без входа
        gpage = guest.new_page()
        gpage.goto("/request/")
        expect(gpage.locator('form[data-form="request"]')).to_be_visible()
        assert helpers.no_horizontal_scroll(gpage), "/request/: горизонтальная прокрутка"
        _submit_request_form(gpage, helpers_sd.requester_email("narrow"), f"Узкий экран {_word()}",
                             "Проверка ширины 360 px")
        assert helpers.no_horizontal_scroll(gpage), "/request/done/: горизонтальная прокрутка"

        # п. 2: страницы исполнителя и администратора
        page = narrow.new_page()
        paths = [
            "/tickets/",
            "/tickets/?" + urllib.parse.urlencode({"preset": "all", "q": word}),
            f"/tickets/{number}/",
            "/tickets/new/",
            "/servicedesk/",
            "/servicedesk/queues/",
            "/servicedesk/dictionaries/categories/",
            "/servicedesk/dictionaries/priorities/",
            "/servicedesk/dictionaries/complexities/",
            "/servicedesk/dictionaries/statuses/",
            "/servicedesk/dictionaries/sources/",
            "/servicedesk/dictionaries/client-units/",
            "/servicedesk/dictionaries/categories/new/",
            f"/servicedesk/dictionaries/categories/{category_id}/edit/",
            "/servicedesk/requesters/",
            f"/servicedesk/requesters/{requester_id}/edit/",
            "/servicedesk/requesters/import/",
            "/servicedesk/inbound/",
        ]
        for path in paths:
            page.goto(path)
            expect(page.locator("main, body").first).to_be_visible()
            assert helpers.no_horizontal_scroll(page), f"{path}: горизонтальная прокрутка"

        # п. 3: предпросмотр загрузки заявителей (подтверждения нет — заявители стенда не меняются)
        page.goto("/servicedesk/requesters/import/")
        form = page.locator('form[data-form="import-upload"]')
        expect(form).to_be_visible()
        rows = [["Почта", "Фамилия", "Имя", "Отчество", "Подразделение"],
                [helpers_sd.requester_email("narrow"), "Узкий", "Тест", "Тестович", ""]]
        helpers_org.upload_file(form, helpers_sd.make_table(rows, "csv", ";", bom=True), name="requesters.csv",
                                mime="text/csv")
        page.wait_for_url(re.compile(r"/servicedesk/requesters/import/\d+/$"))
        expect(page.locator("[data-import-preview]")).to_be_visible()
        assert helpers.no_horizontal_scroll(page), "предпросмотр загрузки заявителей: горизонтальная прокрутка"
    finally:
        narrow.close()
        guest.close()


def _wait_attachment_clean(page, number: int, *, seconds: float = 60.0):
    """Опрос карточки с пределом: проверка вложения идёт в фоне, страница сама не обновляется, поэтому карточка
    открывается заново, пока вложение внутри `[data-section="attachments"]` не станет `clean`. Возвращает
    локатор корня карточки."""
    deadline = time.monotonic() + seconds
    while True:
        card = helpers_sd.open_ticket(page, number)
        clean = card.locator('[data-section="attachments"] [data-attachment][data-state="clean"]')
        try:
            expect(clean).to_have_count(1, timeout=3_000)
            return card
        except AssertionError:
            if time.monotonic() > deadline:
                raise AssertionError(f"вложение заявки #{number} не стало чистым за {seconds:.0f} с")


def test_attachment_and_source_mail_headers_from_nginx_and_protected_not_reachable_directly(
        browser, browser_context_args, admin_page, new_context):
    """Сквозная приёмка, FR-283: чистое вложение и исходное письмо `.eml` отдаёт nginx по `X-Accel-Redirect` — с
    типом `application/octet-stream`, `Content-Disposition: attachment` с именем, `nosniff`, `no-store` и настоящим
    телом; без входа — на вход; чужой uuid — 404; прямой адрес `/protected/…` снаружи недоступен ни вошедшему, ни
    гостю (FR-283, § 12.5, § 1)."""
    helpers_sd.ensure_ready(admin_page)
    word = _word()
    name = f"отчёт-{word}.txt"
    payload = f"Содержимое вложения {word}".encode("utf-8")
    sender = helpers_sd.requester_email()
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=f"Report {word}", text=f"Body {word}",
                                  message_id=_message_id(),
                                  attachments=[MailPart(name, payload, "text/plain")]))
    number = helpers_sd.ticket_number_by_subject(admin_page, word)

    # п. 1: вложение проверено (clamd стенда) и стало чистым; исходное письмо предлагается к выдаче (FR-212)
    card = _wait_attachment_clean(admin_page, number)
    link = card.locator('[data-section="attachments"] [data-attachment][data-state="clean"] a[href]').first
    file_href = link.get_attribute("href")
    found = FILE_HREF.match(file_href or "")
    assert found and found.group(1) == str(number), f"адрес вложения не по § 12.5: {file_href}"
    file_uuid = found.group(2)
    source = card.locator('a[data-action="source-mail"]')
    expect(source).to_have_count(1)
    mail_href = source.get_attribute("href")
    mail_found = re.fullmatch(rf"/tickets/{number}/mail/(\d+)\.eml", mail_href or "")
    assert mail_found, f"адрес исходного письма не по § 12.5: {mail_href}"
    mail_id = mail_found.group(1)

    # п. 2: вложение — заголовки nginx и тело (X-Accel-Redirect клиенту не показывается)
    response = admin_page.request.get(file_href, max_redirects=0)
    assert response.status == 200, f"вложение: статус {response.status}"
    headers = {k.lower(): v for k, v in response.headers.items()}
    assert headers.get("content-type", "").split(";")[0].strip() == "application/octet-stream"
    disposition = headers.get("content-disposition", "")
    assert disposition.startswith("attachment; filename*=UTF-8''"), f"Content-Disposition: {disposition!r}"
    assert urllib.parse.unquote(disposition.split("''", 1)[1].split(";")[0]) == name
    assert headers.get("x-content-type-options") == "nosniff"
    assert "no-store" in headers.get("cache-control", "")
    assert "x-accel-redirect" not in headers, "внутренний заголовок X-Accel-Redirect дошёл до клиента"
    assert response.body() == payload, "в теле нет вложения (отдал не nginx?)"

    # п. 3: исходное письмо — имя `mail-<id>.eml`, те же заголовки, в теле письмо
    response = admin_page.request.get(mail_href, max_redirects=0)
    assert response.status == 200, f"исходное письмо: статус {response.status}"
    headers = {k.lower(): v for k, v in response.headers.items()}
    assert headers.get("content-type", "").split(";")[0].strip() == "application/octet-stream"
    disposition = headers.get("content-disposition", "")
    assert disposition.startswith("attachment; filename*=UTF-8''"), f"Content-Disposition: {disposition!r}"
    assert urllib.parse.unquote(disposition.split("''", 1)[1].split(";")[0]) == f"mail-{mail_id}.eml"
    assert headers.get("x-content-type-options") == "nosniff"
    assert "no-store" in headers.get("cache-control", "")
    assert "x-accel-redirect" not in headers
    assert f"Subject: Report {word}".encode() in response.body(), "в теле нет исходного письма"

    # п. 4: чужой uuid той же заявки — 404 после входа; гость — на вход, без байтов
    other = "00000000-0000-4000-8000-" + secrets.token_hex(6)
    assert helpers_org.direct_get(admin_page, f"/tickets/{number}/files/{other}/").status == 404
    guest = new_context().new_page()
    for path in (file_href, mail_href):
        response = guest.request.get(path, max_redirects=0)
        assert response.status == 302 and "/login/" in response.headers.get("location", ""), \
            f"{path}: гость получил {response.status}"
        assert payload not in response.body()

    # п. 5: прямой адрес тома снаружи не отдаётся — ни вошедшему, ни гостю (nginx `internal`)
    for path in (f"/protected/attachments/{file_uuid}", f"/protected/inbound/{mail_id}.eml", "/protected/",
                 "/protected/attachments/", "/protected/inbound/"):
        for who, label in ((admin_page, "вошедший"), (guest, "гость")):
            response = who.request.get(path, max_redirects=0)
            assert response.status == 404, f"{label}: {path} вернул {response.status}"
            assert payload not in response.body() and word.encode() not in response.body(), \
                f"{label}: {path} отдал содержимое файла"


def test_real_scheduled_poll_creates_ticket_within_two_minutes(admin_page):
    """Сквозная приёмка, NFR-201: письмо кладётся в ящик без команды разбора — заявку создаёт настоящий опрос по
    расписанию не позже 2 минут после попадания письма в ящик (замер `time.monotonic()` от возврата `APPEND`);
    заявка с источником «Почта» видна в списке (NFR-201, FR-210)."""
    helpers_sd.ensure_ready(admin_page)
    word, sender = _word(), helpers_sd.requester_email()
    subject = f"Опрос по расписанию {word}"
    helpers_sd.append_mail(build_mail(from_addr=sender, to=[MAILBOX], subject=subject,
                                      text=f"Письмо ждёт опроса ящика {word}", message_id=_message_id()))
    started = time.monotonic()
    # страница списка грузится один раз, поэтому опрос — перезагрузкой с коротким ожиданием строки;
    # предел цикла больше предела критерия, чтобы сообщение показало фактическое время
    url = "/tickets/?" + urllib.parse.urlencode({"preset": "all", "q": word})
    rows = admin_page.locator("#tickets-grid tr[data-ticket]")
    deadline = started + 180
    while True:
        admin_page.goto(url)
        try:
            expect(rows).to_have_count(1, timeout=5_000)
            break
        except AssertionError:
            if time.monotonic() > deadline:
                raise AssertionError("заявка по письму не появилась за 180 с без команды разбора")
    elapsed = time.monotonic() - started
    assert elapsed < 120, f"письмо стало заявкой за {elapsed:.0f} с (предел 120 с)"
    number = int(rows.get_attribute("data-ticket"))
    card = helpers_sd.open_ticket(admin_page, number)
    assert helpers_sd.field_text(card, "source") == "Почта"
    assert subject in helpers_sd.field_text(card, "subject")


def test_slice_pages_russian_and_moscow_time_in_browser(browser, browser_context_args, admin_page, new_context):
    """Сквозная приёмка, NFR-207: страницы среза по-русски (`lang="ru"`, доля кириллицы в подписях, нет английских
    служебных слов, 404 без чужих слов), а время в карточке, ленте, списке, поле согласия и журнале показано по
    Москве даже при часовом поясе браузера America/New_York (NFR-207)."""
    helpers_sd.ensure_ready(admin_page)
    number, word, sender, _mid, _subject = _deliver_ticket(admin_page)
    form_word = _word()
    form_context = new_context()
    try:
        _submit_request_form(form_context.new_page(), helpers_sd.requester_email("form"),
                             f"Заявка с формы {form_word}", f"Проверка времени согласия {form_word}")
    finally:
        form_context.close()
    form_number = helpers_sd.ticket_number_by_subject(admin_page, form_word)

    context = browser.new_context(**{**browser_context_args, "timezone_id": "America/New_York",
                                     "storage_state": admin_page.context.storage_state()})
    try:
        page = context.new_page()
        # п. 1: язык страниц среза
        checked = 0
        for path in ("/tickets/", f"/tickets/{number}/", "/tickets/new/", "/servicedesk/", "/servicedesk/queues/",
                     "/servicedesk/dictionaries/categories/", "/servicedesk/requesters/",
                     "/servicedesk/requesters/import/", "/servicedesk/inbound/", "/request/"):
            page.goto(path)
            expect(page.locator("main, body").first).to_be_visible()
            assert page.locator("html").get_attribute("lang") == "ru", f"{path}: нет lang=ru"
            text = _ui_text(page)
            if len(re.findall(r"[A-Za-zА-Яа-яЁё]", text)) >= MIN_UI_LETTERS:
                checked += 1
                assert _cyrillic_share(text) > 0.6, f"{path}: страница не по-русски"
            assert not re.search(r"\b(Submit|Save|Cancel|Delete|Loading|Traceback|Not Found)\b", text), \
                f"{path}: английские служебные слова"
        assert checked >= 5, f"доля кириллицы проверена только на {checked} страницах"
        response = helpers_org.direct_get(page, "/tickets/999999999/")
        visible = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", response.text(), flags=re.S)
        assert response.status == 404 and _cyrillic_share(visible) > 0.5, "страница 404 не по-русски"

        # п. 2: время по Москве, а не по поясу браузера: значение в `data-at` — с поясом, текст — по Москве
        now = datetime.now(MOSCOW)
        for path in (f"/tickets/{number}/", f"/tickets/{form_number}/",
                     "/tickets/?" + urllib.parse.urlencode({"preset": "all", "q": word})):
            page.goto(path)
            stamps = page.locator("time[data-at]")
            expect(stamps.first).to_be_visible()
            for element in stamps.all():
                if not element.is_visible():  # время внутри свёрнутого блока: текст скрыт
                    continue
                shown = element.inner_text().strip()
                expected = _moscow(element.get_attribute("data-at")).strftime(TIME_FORMAT)
                assert shown == expected, f"{path}: время {shown!r}, по Москве {expected!r}"
                assert _close_to_now(datetime.strptime(shown, TIME_FORMAT).replace(tzinfo=MOSCOW), now), \
                    f"{path}: время {shown} далеко от московского «сейчас» {now:%d.%m.%Y %H:%M}"

        # п. 3: отметка согласия у заявки с формы — дата и время по Москве
        page.goto(f"/tickets/{form_number}/")
        consent = page.locator('[data-ticket-card] [data-field="consent"]')
        expect(consent).to_be_visible()
        stamp = re.search(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}", consent.inner_text())
        assert stamp, "в отметке согласия нет даты и времени"
        assert _close_to_now(datetime.strptime(stamp.group(0), TIME_FORMAT).replace(tzinfo=MOSCOW), now), \
            f"время согласия {stamp.group(0)} не по Москве (сейчас {now:%d.%m.%Y %H:%M})"

        # п. 4: время события журнала — по Москве (сравнение часов и минут; около полуночи — через сутки)
        page.goto(f"/audit/?action=ticket.created&object_id={number}")
        row = page.locator('tr[data-event-id][data-action="ticket.created"]').first
        expect(row).to_be_visible()
        times = re.findall(r"\b(\d{2}):(\d{2})\b", row.inner_text())
        assert times, "в строке журнала нет времени"
        shown = now.replace(hour=int(times[0][0]), minute=int(times[0][1]), second=0, microsecond=0)
        assert abs(shown - now) < timedelta(minutes=20) or abs(shown - now) > timedelta(hours=23, minutes=40), \
            f"время события не по Москве: {times[0][0]}:{times[0][1]}, по Москве сейчас {now:%H:%M}"
    finally:
        context.close()
