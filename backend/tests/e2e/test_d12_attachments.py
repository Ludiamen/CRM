"""T-3150: сценарий 12 — вложения: проверка настоящим clamd, карантин, отказы по размеру и типу, выдача файлов,
обезличивание по сроку хранения, журнал, ответ с вложением в карантине (FR-212, FR-244, FR-250, FR-283…FR-286,
FR-289…FR-291)."""
import re
import secrets
import time
import urllib.parse

from playwright.sync_api import expect

from tests.e2e import helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_org import eicar_bytes
from tests.support_servicedesk import MailPart, build_mail, sample

MIB = 1024 * 1024
OCTET = "application/octet-stream"


def _word() -> str:
    """Уникальное слово темы (доп. 41 (в)): буква и шесть шестнадцатеричных знаков."""
    return f"t{secrets.token_hex(3)}"


def _mid() -> str:
    return f"<{secrets.token_hex(8)}@client.test>"


def _norm(text: str) -> str:
    return " ".join(text.split())


def _section(card):
    """Вложения заявки — только внутри `[data-section="attachments"]` (13.3, абзац после таблицы)."""
    return card.locator('[data-section="attachments"]')


def _attachment(card, name: str):
    return _section(card).locator("[data-attachment]").filter(has_text=name)


def _entry_rejected(card):
    """Блок не принятых вложений единственного входящего письма — внутри его `li[data-entry]`, без `ul[data-attachments]`
    (доп. 43 (в): `ul` есть, только если у письма есть принятые вложения)."""
    return card.locator('ol[data-feed] li[data-entry][data-kind="incoming"] [data-rejected-attachments]')


def _card_rejected(card):
    """Блок не принятых вложений карточки — внутри `[data-section="attachments"]` (доп. 43 (в))."""
    return _section(card).locator("[data-rejected-attachments]")


def _reload_until(page, number: int, build, *, timeout: float = 60.0):
    """Перезагружает карточку, пока `build(card)` не найдёт элемент (проверка вложения — до 60 с); возвращает
    (карточка, прошедшие секунды). Не нашёл за `timeout` — AssertionError."""
    start = time.monotonic()
    while True:
        card = helpers_sd.open_ticket(page, number)
        if build(card).count():
            return card, time.monotonic() - start
        if time.monotonic() - start > timeout:
            raise AssertionError(f"за {timeout:.0f} с в заявке #{number} не появился ожидаемый элемент")
        page.wait_for_timeout(1000)


def _wait_attachment(page, number: int, name: str, state: str):
    card, elapsed = _reload_until(
        page, number,
        lambda c: _section(c).locator(f'[data-attachment][data-state="{state}"]').filter(has_text=name))
    return card, elapsed


def _ticket_from_mail(page, *, word: str, attachments=(), text: str | None = None, html: str | None = None,
                      sender: str | None = None, from_name: str = "", subject: str | None = None, cc=()):
    """Кладёт письмо заявителя в ящик, разбирает сразу и возвращает (номер заявки, адрес отправителя)."""
    sender = sender or helpers_sd.requester_email()
    subject = subject or f"Вложения {word}"
    body = text if text is not None or html is not None else f"Текст письма {word}"
    helpers_sd.deliver(build_mail(from_addr=f"{from_name} <{sender}>" if from_name else sender, to=[MAILBOX],
                                  cc=list(cc), subject=subject, text=body, html=html, message_id=_mid(),
                                  attachments=list(attachments)))
    return helpers_sd.ticket_number_by_subject(page, word), sender


def _file_href(card, name: str) -> str:
    link = _attachment(card, name).locator("a[href]")
    expect(link).to_have_count(1)
    return link.get_attribute("href")


def _letter_attachment_names(letter: dict) -> list:
    return [str(a.get("FileName", "")) for a in (letter.get("Attachments") or [])]


def _audit_object_cell(page, action: str, number: int) -> list:
    """Текст ячейки «объект» (4-я `td`, как в `audit_sides`) строк журнала `action` по заявке `number`."""
    helpers_org.audit_rows(page, action, number)  # открывает журнал с фильтром action и object_id
    rows = page.locator(f'tr[data-event-id][data-action="{action}"]').all()
    return [row.locator("td").nth(3).inner_text() for row in rows]


def _submit_request_form(page, *, email: str, subject: str, text: str, files=None) -> None:
    """Заполняет открытую форму `/request/` и отправляет (категория «Другое» есть всегда, 13.6)."""
    page.goto("/request/")
    form = page.locator('form[data-form="request"]')
    expect(form).to_be_visible()
    form.locator("input[name=email]").fill(email)
    form.locator("input[name=name]").fill("Тестов Заявитель")
    form.locator("select[name=category]").select_option(label="Другое")
    form.locator("input[name=subject]").fill(subject)
    form.locator("textarea[name=text]").fill(text)
    if files:
        form.locator("input[type=file][name=files]").set_input_files(files)
    form.locator("input[name=consent]").check()
    form.locator("button[type=submit]").click()


def _expect_form_refused(page, *texts: str) -> None:
    """Отказ формы: адрес остался `/request/` (не `/request/done/`), `[role=alert]` содержит все `texts`."""
    alert = page.locator("[role=alert]")
    for text in texts:
        alert = alert.filter(has_text=text)
    expect(alert.first).to_be_visible()
    assert "/request/done/" not in page.url


def _retention_years(page) -> int:
    page.goto("/servicedesk/")
    form = page.locator('form[data-form="servicedesk-settings"]')
    expect(form).to_be_visible()
    return int(form.locator("input[name=retention_years]").input_value())


def _expired_days(years: int) -> int:
    """Сутки назад для заявки с истёкшим сроком: `years` лет (365 или 366 суток) и ещё 20 суток запаса."""
    return years * 366 + 20


def _fresh_days(years: int) -> int:
    """Сутки назад для заявки внутри срока: до границы `years` лет остаётся не меньше 60 суток."""
    return years * 365 - 60


def _close_ticket(page, number: int, resolution: str) -> None:
    """Закрывает заявку через диалог `ticket-close` (12.4, 13.1) и ждёт вид «закрыта»."""
    helpers_sd.open_ticket(page, number)
    page.locator('a[data-action="ticket-close"]').click()
    dialog = page.locator('[data-dialog="ticket-close"]')
    expect(dialog).to_be_visible()
    dialog.locator("textarea[name=resolution]").fill(resolution)
    dialog.locator("button[type=submit]").click()
    expect(page.locator(f'[data-ticket-card][data-number="{number}"]')).to_have_attribute("data-kind", "closed")


KEPT_FIELDS = ("number", "subject", "status", "queue", "category", "priority", "complexity", "client-unit", "source",
               "created", "closed-by", "resolution")


def _kept(card) -> dict:
    return {name: helpers_sd.field_text(card, name) for name in KEPT_FIELDS}


def test_d12_attachment_clean_within_one_minute_downloadable_by_ticket_member(admin_page, employee):
    """Сценарий 12, п. 1: вложение письма сначала «проверяется» и не скачивается; настоящий clamd признаёт его
    чистым не позже чем через минуту; скачивает тот, у кого есть доступ к заявке — администратор и участник очереди
    (FR-283)."""
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    tag = secrets.token_hex(3)
    member = employee(full_name=f"Участников{tag} Иван Петрович")
    helpers_sd.add_queue_member(page, queue_id, [member.id], q=f"Участников{tag}")
    word, name = _word(), "act.txt"
    data = f"чистое вложение {word}".encode()
    number, _ = _ticket_from_mail(page, word=word, attachments=[MailPart(name, data, "text/plain")])
    start = time.monotonic()
    # п. 1: сразу после получения — «проверяется», ссылки на скачивание нет (если проверка уже кончилась — чисто)
    card = helpers_sd.open_ticket(page, number)
    attachment = _attachment(card, name)
    expect(attachment).to_have_count(1)
    first_state = attachment.get_attribute("data-state")
    assert first_state in ("pending", "clean")
    if first_state == "pending":
        expect(attachment).to_contain_text("проверяется")
        expect(attachment.locator("a[href]")).to_have_count(0)
    # через не более минуты — «чистый»; замер от конца разбора письма
    card, _ = _wait_attachment(page, number, name, "clean")
    assert time.monotonic() - start <= 60, "проверка вложения заняла больше минуты"
    href = _file_href(card, name)
    assert re.fullmatch(rf"/tickets/{number}/files/[0-9a-fA-F-]{{36}}/", href), href
    # администратор скачивает
    response = page.request.get(href)
    assert response.status == 200
    assert response.body() == data
    # участник очереди (без права «Все заявки») тоже
    response = member.page.request.get(href)
    assert response.status == 200
    assert response.body() == data


def test_d12_infected_attachment_quarantined_not_downloadable_feed_event(admin_page):
    """Сценарий 12, п. 2: заражённое вложение (EICAR) после проверки в карантине, ссылки на скачивание нет ни у
    кого, в ленте событие «вложение в карантине», в журнале `ticket.attachment_quarantined` (FR-283)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    word, name = _word(), "eicar-sample.txt"
    number, _ = _ticket_from_mail(page, word=word, attachments=[MailPart(name, eicar_bytes(), "text/plain")])
    # п. 2: проверка завершилась — вложение в карантине
    card, _ = _wait_attachment(page, number, name, "quarantine")
    attachment = _attachment(card, name)
    expect(attachment).to_have_count(1)
    expect(attachment).to_contain_text("в карантине")
    expect(attachment.locator("a[href]")).to_have_count(0)
    expect(_section(card).locator('a[href*="/files/"]')).to_have_count(0)
    expect(card.locator('a[data-action="source-mail"]')).to_have_count(0)  # FR-212: вложение не чистое
    # в ленте — событие «вложение в карантине: «<имя>»»
    event = card.locator('ol[data-feed] li[data-kind="event"][data-event="attachment_quarantined"]')
    expect(event).to_have_count(1)
    expect(event).to_contain_text("вложение в карантине")
    expect(event).to_contain_text(name)
    # в журнале — факт карантина по номеру заявки
    assert len(helpers_org.audit_rows(page, "ticket.attachment_quarantined", number)) == 1


def test_d12_25mb_attachment_ticket_created_card_and_confirmation_list_refused_with_reason(admin_page, mailpit):
    """Сценарий 12, п. 3: вложение 25 МБ — заявка создаётся, а в карточке и в подтверждении перечислено, что не
    принято и почему «<имя> — больше 20 МБ» (FR-284, FR-285)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    word, name = _word(), "big.bin"
    text = f"Письмо с большим файлом {word}"
    number, sender = _ticket_from_mail(page, word=word, text=text,
                                       attachments=[MailPart(name, b"\0" * (25 * MIB))])
    card = helpers_sd.open_ticket(page, number)
    # заявка создана: текст письма в ленте
    expect(card.locator('ol[data-feed] li[data-kind="incoming"] [data-entry-text]')).to_contain_text(text)
    # в карточке — не принятое вложение с причиной (в блоке элемента ленты и в карточке)
    expect(_entry_rejected(card)).to_have_count(1)
    rejected = _entry_rejected(card).locator('li[data-rejected="too_big"]')
    expect(rejected).to_have_count(1)
    assert f"{name} — больше 20 МБ" in _norm(rejected.inner_text())
    expect(_card_rejected(card)).to_have_count(1)
    expect(_card_rejected(card)).to_contain_text(name)
    # в подтверждении — перечень не принятых вложений
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.confirmation", to=sender)
    assert f"Вложения, которые не приняты: {name} — больше 20 МБ" in _norm(letter["Text"])


def test_d12_executable_and_password_archive_refused_in_mail_and_form(admin_page, mailpit, new_context):
    """Сценарий 12, п. 4: исполняемый файл и архив с паролем в письме не принимаются (заявка создана, в карточке и
    подтверждении причины), а форма отказывает целиком и заявки не создаёт (FR-284)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    exe, enc = "tool.bin", "secret.zip"
    word = _word()
    # письмо: заявка есть, оба файла не приняты, причины названы
    number, sender = _ticket_from_mail(page, word=word, attachments=[
        MailPart(exe, sample("exe_pe.bin")), MailPart(enc, sample("enc_zip_zipcrypto.zip"), "application/zip")])
    card = helpers_sd.open_ticket(page, number)
    block = _entry_rejected(card)
    expect(block).to_have_count(1)
    executable = block.locator('li[data-rejected="executable"]')
    expect(executable).to_have_count(1)
    assert f"{exe} — исполняемый файл" in _norm(executable.inner_text())
    encrypted = block.locator('li[data-rejected="encrypted"]')
    expect(encrypted).to_have_count(1)
    assert f"{enc} — архив с паролем" in _norm(encrypted.inner_text())
    expect(_card_rejected(card)).to_have_count(1)  # блок карточки — внутри [data-section="attachments"]
    expect(_card_rejected(card)).to_contain_text(exe)
    expect(_card_rejected(card)).to_contain_text(enc)
    letter = _norm(helpers_sd.wait_letter(mailpit, number, "ticket.confirmation", to=sender)["Text"])
    assert f"{exe} — исполняемый файл" in letter
    assert f"{enc} — архив с паролем" in letter
    # форма: исполняемый по содержимому, исполняемый по расширению, архив с паролем — отказ целиком
    guest = new_context().new_page()
    cases = [("form-exe.bin", sample("exe_pe.bin"), "исполняемый файл"),
             ("run.exe", b"harmless text", "исполняемый файл"),
             ("form-secret.zip", sample("enc_zip_zipcrypto.zip"), "архив с паролем")]
    for file_name, data, title in cases:
        form_word = _word()
        _submit_request_form(guest, email=helpers_sd.requester_email(), subject=f"Форма {form_word}",
                             text=f"Текст формы {form_word}",
                             files=[{"name": file_name, "mimeType": OCTET, "buffer": data}])
        _expect_form_refused(guest, "не принят", file_name, title)
        assert helpers_sd.tickets_by_subject(page, form_word) == []


def test_d12_form_eleven_files_or_over_50mb_refused(admin_page, new_context, tmp_path):
    """Сценарий 12, п. 5: на форме 11 файлов или сумма больше 50 МБ — форма отказывает («Файлов не больше 10»,
    «Файлы вместе не больше 50 МБ») и заявки нет; ровно 10 файлов проходят (FR-284)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    guest = new_context().new_page()
    small = [{"name": f"f{i}.txt", "mimeType": "text/plain", "buffer": f"файл {i}".encode()} for i in range(11)]
    # 11 файлов — отказ
    word = _word()
    _submit_request_form(guest, email=helpers_sd.requester_email(), subject=f"Одиннадцать {word}",
                         text=f"Текст {word}", files=small)
    _expect_form_refused(guest, "Файлов не больше 10")
    assert helpers_sd.tickets_by_subject(page, word) == []
    # сумма больше 50 МБ (три файла по 18 МБ, каждый меньше предела 20 МБ) — отказ
    paths = []
    for i in range(3):
        path = tmp_path / f"part{i}.bin"
        path.write_bytes(b"\0" * (18 * MIB))
        paths.append(str(path))
    word = _word()
    _submit_request_form(guest, email=helpers_sd.requester_email(), subject=f"Много мегабайт {word}",
                         text=f"Текст {word}", files=paths)
    _expect_form_refused(guest, "Файлы вместе не больше 50 МБ")
    assert helpers_sd.tickets_by_subject(page, word) == []
    # контроль: ровно 10 файлов принимаются
    word = _word()
    _submit_request_form(guest, email=helpers_sd.requester_email(), subject=f"Десять {word}",
                         text=f"Текст {word}", files=small[:10])
    guest.wait_for_url("**/request/done/")
    number = helpers_sd.ticket_number_by_subject(page, word)
    card = helpers_sd.open_ticket(page, number)
    expect(_section(card).locator("[data-attachment]")).to_have_count(10)


def test_d12_inline_image_is_attachment_with_same_checks(admin_page):
    """Сценарий 12, п. 6: встроенная в письмо картинка — вложение и проходит те же проверки: чистая — «чистый»,
    с заражённым содержимым — карантин (FR-286)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    # чистая картинка
    word, cid = _word(), "pic1@client.test"
    number, _ = _ticket_from_mail(
        page, word=word, text=f"Смотрите скриншот {word}",
        html=f'<p>Скриншот <img src="cid:{cid}"> {word}</p>',
        attachments=[MailPart("logo.png", sample("image.png"), "image/png", content_id=cid)])
    card = helpers_sd.open_ticket(page, number)
    expect(_attachment(card, "logo.png")).to_have_count(1)  # картинка в списке вложений заявки
    card, _ = _wait_attachment(page, number, "logo.png", "clean")
    expect(_attachment(card, "logo.png").locator("a[href]")).to_have_count(1)
    # картинка с заражённым содержимым — карантин
    word2, cid2 = _word(), "pic2@client.test"
    number2, _ = _ticket_from_mail(
        page, word=word2, text=f"Ещё скриншот {word2}",
        html=f'<p>Скриншот <img src="cid:{cid2}"> {word2}</p>',
        attachments=[MailPart("pic2.png", eicar_bytes(), "image/png", content_id=cid2)])
    card, _ = _wait_attachment(page, number2, "pic2.png", "quarantine")
    expect(_attachment(card, "pic2.png")).to_contain_text("в карантине")
    expect(_attachment(card, "pic2.png").locator("a[href]")).to_have_count(0)
    expect(card.locator('ol[data-feed] li[data-kind="event"][data-event="attachment_quarantined"]')).to_have_count(1)


def test_d12_attachment_link_without_ticket_access_refused(admin_page, employee):
    """Сценарий 12, п. 8: сотрудник без доступа к заявке (не участник очереди, без права «Все заявки»), открыв
    ссылку на вложение, получает отказ — как для несуществующего файла; администратору файл выдаётся (FR-283)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    outsider = employee(full_name=f"Посторонн{secrets.token_hex(3)} Иван Петрович")
    word, name = _word(), "private.txt"
    data = f"закрытое вложение {word}".encode()
    number, _ = _ticket_from_mail(page, word=word, attachments=[MailPart(name, data, "text/plain")])
    card, _ = _wait_attachment(page, number, name, "clean")
    href = _file_href(card, name)
    assert page.request.get(href).status == 200  # у кого есть доступ — файл выдаётся
    # п. 8: у постороннего отказ; несуществующий файл той же заявки отвечает так же
    refused = helpers_org.direct_get(outsider.page, href)
    assert refused.status == 404
    missing = helpers_org.direct_get(outsider.page, f"/tickets/{number}/files/00000000-0000-4000-8000-000000000000/")
    assert missing.status == refused.status
    assert helpers_org.direct_get(outsider.page, f"/tickets/{number}/").status == 404


def test_d12_download_headers_through_nginx_octet_stream_attachment_disposition_nosniff_no_store_and_eml_same(
        admin_page):
    """Сценарий 12, выдача файлов (12.5): вложение и исходное письмо `.eml` приходят через nginx с
    `Content-Type: application/octet-stream`, `Content-Disposition: attachment; filename*=UTF-8''…`,
    `X-Content-Type-Options: nosniff`, `Cache-Control: no-store` (FR-283, FR-212)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    word = _word()
    name = f"отчёт-{word}.txt"
    data = f"содержимое {word}".encode()
    number, _ = _ticket_from_mail(page, word=word, subject=f"Headers check {word}",
                                  attachments=[MailPart(name, data, "text/plain")])
    card, _ = _wait_attachment(page, number, name, "clean")
    href = _file_href(card, name)
    # вложение
    response = page.request.get(href)
    assert response.status == 200
    headers = {k.lower(): v for k, v in response.headers.items()}
    assert headers["content-type"].split(";")[0].strip() == OCTET
    disposition = headers["content-disposition"]
    assert disposition.lower().startswith("attachment")
    assert "filename*=UTF-8''" in disposition
    assert urllib.parse.unquote(disposition.split("filename*=UTF-8''", 1)[1]) == name
    assert headers["x-content-type-options"].lower() == "nosniff"
    assert "no-store" in headers["cache-control"].lower()
    assert response.body() == data
    # исходное письмо: все вложения чистые — ссылка есть
    source = card.locator('a[data-action="source-mail"]')
    expect(source).to_have_count(1)
    eml_href = source.get_attribute("href")
    match = re.fullmatch(rf"/tickets/{number}/mail/(\d+)\.eml", eml_href)
    assert match, eml_href
    eml = page.request.get(eml_href)
    assert eml.status == 200
    headers = {k.lower(): v for k, v in eml.headers.items()}
    assert headers["content-type"].split(";")[0].strip() == OCTET
    assert headers["content-disposition"].lower().startswith("attachment")
    assert f"filename*=UTF-8''mail-{match.group(1)}.eml" in headers["content-disposition"]
    assert headers["x-content-type-options"].lower() == "nosniff"
    assert "no-store" in headers["cache-control"].lower()
    assert f"Headers check {word}" in eml.body().decode("utf-8", errors="replace")


def test_d12_retention_anonymizes_closed_ticket_keeps_listed_fields_open_ticket_untouched(admin_page):
    """Сценарий 12, п. 9: у закрытой заявки с истёкшим сроком хранения ночное задание убирает тексты, вложения,
    исходное письмо, адрес и ФИО заявителя; номер, тема, категория, очередь, критичность, статус, даты, события и
    текст решения остаются; закрытая внутри срока и открытая заявки не тронуты (FR-290, FR-291)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    years = _retention_years(page)
    resolution = f"Решение{secrets.token_hex(3)} заменили картридж"
    # заявка A: закрытая, срок истёк; у неё есть чистое вложение и исходное письмо
    word_a, name_a = _word(), "a-file.txt"
    body_a = f"Текст письма А {_word()}"
    person_a = f"Заявителев{secrets.token_hex(3)} Пётр Сергеевич"
    # участник из копии: адрес корпоративного домена и имя (FR-217); ответ и внутренний комментарий (FR-290)
    part_addr = helpers_sd.requester_email("cc")
    part_name = f"Копиев{secrets.token_hex(3)} Анна Сергеевна"
    number_a, sender_a = _ticket_from_mail(page, word=word_a, text=body_a, from_name=person_a,
                                           cc=[f"{part_name} <{part_addr}>"],
                                           attachments=[MailPart(name_a, b"data a", "text/plain")])
    card, _ = _wait_attachment(page, number_a, name_a, "clean")
    href_a = _file_href(card, name_a)
    eml_a = card.locator('a[data-action="source-mail"]').get_attribute("href")
    reply_a, comment_a = f"Ответ{secrets.token_hex(3)} перезагрузите", f"Заметка{secrets.token_hex(3)} внутри"
    reply = card.locator('form[data-form="ticket-reply"]')
    reply.locator("textarea[name=text]").fill(reply_a)
    reply.locator("button[type=submit]").click()
    expect(page.locator('li[data-kind="reply"] [data-entry-text]')).to_contain_text(reply_a)
    comment = page.locator('form[data-form="ticket-comment"]')
    comment.locator("textarea[name=text]").fill(comment_a)
    comment.locator("button[type=submit]").click()
    expect(page.locator('li[data-kind="comment"] [data-entry-text]')).to_contain_text(comment_a)
    # до задания всё это на странице есть (без этого «нет после» ничего не доказывает)
    card = helpers_sd.open_ticket(page, number_a)
    expect(card.locator('[data-section="participants"] [data-participant]')).to_have_count(1)
    present = card.inner_text()
    for here in (sender_a, person_a, body_a, reply_a, comment_a, part_addr, part_name, name_a):
        assert here in present, f"до обезличивания на странице нет: {here}"
    # заявка B: открытая, но старая по созданию
    word_b, name_b = _word(), "b-file.txt"
    number_b, sender_b = _ticket_from_mail(page, word=word_b, text=f"Текст письма B {_word()}",
                                           attachments=[MailPart(name_b, b"data b", "text/plain")])
    _wait_attachment(page, number_b, name_b, "clean")
    # заявка C: закрытая, но срок ещё не истёк
    word_c = _word()
    number_c, sender_c = _ticket_from_mail(page, word=word_c)
    _close_ticket(page, number_a, resolution)
    _close_ticket(page, number_c, "Закрыта внутри срока")
    before = _kept(helpers_sd.open_ticket(page, number_a))
    assert resolution in before["resolution"]
    helpers_sd.backdate("ticket", number_a, "closed_at", _expired_days(years))
    helpers_sd.backdate("ticket", number_c, "closed_at", _fresh_days(years))
    helpers_sd.backdate("ticket", number_b, "created_at", _expired_days(years))
    helpers_sd.run_job("anonymize_tickets")
    # A: обезличена, перечисленное осталось
    card = helpers_sd.open_ticket(page, number_a)
    assert _kept(card) == before
    assert "обезличено" in helpers_sd.field_text(card, "requester-email")
    assert "обезличено" in helpers_sd.field_text(card, "requester-name")
    text = card.inner_text()
    for gone in (sender_a, person_a, body_a, reply_a, comment_a, part_addr, part_name, name_a):
        assert gone not in text, f"после обезличивания на странице осталось: {gone}"
    expect(card.locator('li[data-kind="event"][data-event="closed"]')).to_have_count(1)
    expect(card.locator('li[data-kind="event"][data-event="closed"]')).to_contain_text(resolution)
    expect(card.locator("[data-participant]")).to_have_count(0)  # участники из копии удалены (6.24, шаг 5)
    expect(_section(card).locator("[data-attachment]")).to_have_count(0)
    expect(card.locator('a[data-action="source-mail"]')).to_have_count(0)
    assert page.request.get(href_a).status == 404  # файл стёрт
    assert page.request.get(eml_a).status == 404  # исходное письмо стёрто
    assert len(helpers_org.audit_rows(page, "ticket.anonymized", number_a)) == 1
    # B: открытая — ничего не изменено
    card = helpers_sd.open_ticket(page, number_b)
    assert sender_b in helpers_sd.field_text(card, "requester-email").lower()
    expect(_attachment(card, name_b)).to_have_count(1)
    expect(_attachment(card, name_b).locator("a[href]")).to_have_count(1)
    assert helpers_org.audit_rows(page, "ticket.anonymized", number_b) == []
    # C: закрытая внутри срока — не тронута
    card = helpers_sd.open_ticket(page, number_c)
    assert sender_c in helpers_sd.field_text(card, "requester-email").lower()
    assert helpers_org.audit_rows(page, "ticket.anonymized", number_c) == []


def test_d12_journal_for_reply_and_comment_has_fact_and_number_without_texts_address_or_name(admin_page):
    """Сценарий 12, п. 10: после ответа исполнителя и внутреннего комментария в журнале есть факт и номер заявки,
    но нет текста письма, ответа, комментария, темы, адреса и ФИО заявителя (FR-289)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    word = _word()
    person = f"Журналов{secrets.token_hex(3)} Олег Иванович"
    subject = f"Тема журнала {word}"
    mail_text = f"Текст письма {_word()}"
    number, sender = _ticket_from_mail(page, word=word, subject=subject, text=mail_text, from_name=person)
    reply_text, comment_text = f"Ответ{secrets.token_hex(3)} перезагрузите", f"Заметка{secrets.token_hex(3)} внутри"
    card = helpers_sd.open_ticket(page, number)
    reply = card.locator('form[data-form="ticket-reply"]')
    reply.locator("textarea[name=text]").fill(reply_text)
    reply.locator("button[type=submit]").click()
    expect(page.locator('li[data-kind="reply"] [data-entry-text]')).to_contain_text(reply_text)
    comment = page.locator('form[data-form="ticket-comment"]')
    comment.locator("textarea[name=text]").fill(comment_text)
    comment.locator("button[type=submit]").click()
    expect(page.locator('li[data-kind="comment"] [data-entry-text]')).to_contain_text(comment_text)
    forbidden = (reply_text, comment_text, mail_text, subject, word, sender, person, "Журналов")
    for action in ("ticket.created", "ticket.reply_sent", "ticket.comment_added"):
        rows = helpers_org.audit_rows(page, action, number)
        assert len(rows) == 1, f"{action}: ожидалась одна строка журнала по заявке #{number}, есть {len(rows)}"
        cells = _audit_object_cell(page, action, number)
        assert len(cells) == 1, f"{action}: ожидалась одна строка журнала по заявке #{number}, есть {len(cells)}"
        assert re.search(rf"(?<!\d){number}(?!\d)", cells[0]), \
            f"{action}: в ячейке «объект» нет номера заявки #{number}: {cells[0]!r}"
        for text in forbidden:
            assert text not in rows[0], f"{action}: в журнале есть «{text}»"


def test_d12_reply_not_sent_for_quarantine_shows_note_and_resend_button_countdown_from_actual_send(
        admin_page, mailpit):
    """Сценарий 12, п. 11: ответ с заражённым вложением не ушёл — у ответа «ответ не отправлен: вложение «…» в
    карантине» и кнопка отправки, письма и отсчёта автозакрытия нет; повторная отправка без заражённого вложения
    отправляет письмо с чистым файлом, и отсчёт идёт с этой отправки (FR-244, FR-250)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    word = _word()
    number, sender = _ticket_from_mail(page, word=word)
    clean_name, bad_name = f"ok-{word}.txt", f"eicar-{word}.txt"
    reply_text = f"Ответ{secrets.token_hex(3)} с файлами"
    card = helpers_sd.open_ticket(page, number)
    reply = card.locator('form[data-form="ticket-reply"]')
    reply.locator("textarea[name=text]").fill(reply_text)
    reply.locator("input[name=wait]").check()
    reply.locator("input[type=file][name=files]").set_input_files([
        {"name": clean_name, "mimeType": "text/plain", "buffer": b"clean content"},
        {"name": bad_name, "mimeType": "text/plain", "buffer": eicar_bytes()}])
    reply.locator("button[type=submit]").click()
    expect(page.locator('li[data-kind="reply"]')).to_have_count(1)
    # п. 11: после проверки — «не отправлен», причина названа в ленте, кнопка отправки есть
    card, _ = _reload_until(page, number, lambda c: c.locator('ol[data-feed] [data-send-state="not_sent"]'))
    event = card.locator('ol[data-feed] li[data-kind="event"][data-event="reply_not_sent"]')
    expect(event).to_have_count(1)
    expect(event).to_contain_text(f"ответ не отправлен: вложение «{bad_name}» в карантине")
    resend = card.locator('form[data-form="reply-resend"] button[data-action="reply-resend"]')
    expect(resend).to_have_count(1)
    # письма заявителю нет, отсчёт автозакрытия не идёт: задание заявку не закрывает
    assert helpers_sd.no_letter(mailpit, number, "ticket.reply", recipient=sender, wait=15)
    expect(card).to_have_attribute("data-kind", "waiting")
    helpers_sd.run_job("autoclose")
    expect(helpers_sd.open_ticket(page, number)).to_have_attribute("data-kind", "waiting")
    # когда: исполнитель отправляет ответ заново — без заражённого вложения
    card = helpers_sd.open_ticket(page, number)
    card.locator('form[data-form="reply-resend"] button[data-action="reply-resend"]').click()
    expect(page.locator('li[data-kind="reply"]')).to_have_count(2)
    expect(page.locator('ol[data-feed] [data-send-state="queued"]')).to_have_count(1)
    # тогда: письмо ушло, в нём чистый файл и нет заражённого
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.reply", to=sender)
    names = _letter_attachment_names(letter)
    assert clean_name in names
    assert bad_name not in names
    # отсчёт идёт с этой отправки: срок сдвигаем после неё, и задание закрывает заявку автоматически
    page.goto("/servicedesk/")
    form = page.locator('form[data-form="servicedesk-settings"]')
    expect(form).to_be_visible()
    autoclose_days = int(form.locator("input[name=autoclose_days]").input_value())
    helpers_sd.backdate("ticket", number, "waiting_since", autoclose_days + 1)
    helpers_sd.run_job("autoclose")
    card = helpers_sd.open_ticket(page, number)
    expect(card).to_have_attribute("data-kind", "closed")
    expect(card.locator('li[data-kind="event"][data-event="autoclosed"]')).to_have_count(1)


def test_d12_retention_keeps_requester_record_in_table_or_with_other_tickets_removes_orphan_ticket_record(
        admin_page):
    """Сценарий 12, п. 12: заявка с истёкшим сроком обезличена, а общая запись заявителя не изменилась, если он в
    таблице заявителей или у него есть другие заявки; запись из заявок, у которой не осталось заявок, удалена
    (FR-290, FR-291)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    years = _retention_years(page)
    tag = secrets.token_hex(3)
    addr_table, addr_other, addr_orphan = (helpers_sd.requester_email(p) for p in ("tbl", "oth", "orp"))
    last, name_table = f"Табличный{tag}", f"Табличный{tag} Игорь Олегович"
    # дано: запись первого заявителя — из таблицы
    page.goto("/servicedesk/requesters/import/")
    upload = page.locator('form[data-form="import-upload"]')
    expect(upload).to_be_visible()
    table = helpers_sd.make_table([["Почта", "Фамилия", "Имя", "Отчество"],
                                   [addr_table, last, "Игорь", "Олегович"]], "csv", bom=True)
    helpers_org.upload_file(upload, table, name="requesters.csv", mime="text/csv")
    expect(page.locator("[data-import-preview]")).to_be_visible()
    page.locator('form[data-form="import-confirm"] button[type=submit]').click()
    expect(page.locator("[data-result-summary]")).to_have_attribute("data-added", "1")
    # заявки: у «таблицы» одна; у «другого» две; у «сироты» одна
    word_t, word_o1, word_o2, word_r = _word(), _word(), _word(), _word()
    number_t, _ = _ticket_from_mail(page, word=word_t, sender=addr_table)
    number_o1, _ = _ticket_from_mail(page, word=word_o1, sender=addr_other)
    number_o2, _ = _ticket_from_mail(page, word=word_o2, sender=addr_other)
    number_r, _ = _ticket_from_mail(page, word=word_r, sender=addr_orphan)

    def row(address: str):
        page.goto("/servicedesk/requesters/?" + urllib.parse.urlencode({"q": address}))
        expect(page.locator('form[data-form="requesters-filter"]')).to_be_visible()
        return page.locator("tr[data-requester]").filter(has=page.locator('[data-cell="email"]', has_text=address))

    # до задания: все три записи есть; у «сироты» отметка «заявка», у «таблицы» — «таблица»
    expect(row(addr_table)).to_have_count(1)
    expect(row(addr_table).locator('[data-cell="origin"]')).to_contain_text("таблица")
    expect(row(addr_other)).to_have_count(1)
    expect(row(addr_other).locator('[data-cell="origin"]')).to_contain_text("заявка")
    expect(row(addr_orphan)).to_have_count(1)
    # закрываем три заявки (вторая заявка «другого» остаётся открытой) и сдвигаем срок
    for number in (number_t, number_o1, number_r):
        _close_ticket(page, number, "Решено")
        helpers_sd.backdate("ticket", number, "closed_at", _expired_days(years))
    helpers_sd.run_job("anonymize_tickets")
    # три заявки обезличены
    for number in (number_t, number_o1, number_r):
        card = helpers_sd.open_ticket(page, number)
        assert "обезличено" in helpers_sd.field_text(card, "requester-email")
        assert len(helpers_org.audit_rows(page, "ticket.anonymized", number)) == 1
    # открытая заявка «другого» не тронута
    card = helpers_sd.open_ticket(page, number_o2)
    assert addr_other in helpers_sd.field_text(card, "requester-email").lower()
    # запись из таблицы не изменилась (отметка и ФИО прежние)
    expect(row(addr_table)).to_have_count(1)
    expect(row(addr_table).locator('[data-cell="origin"]')).to_contain_text("таблица")
    expect(row(addr_table).locator('[data-cell="name"]')).to_contain_text(name_table)
    # запись с другой (открытой) заявкой осталась
    expect(row(addr_other)).to_have_count(1)
    expect(row(addr_other).locator('[data-cell="origin"]')).to_contain_text("заявка")
    # запись из заявок без заявок удалена
    expect(row(addr_orphan)).to_have_count(0)
