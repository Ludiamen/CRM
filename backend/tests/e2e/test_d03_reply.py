"""T-3142: сценарий 3 — исполнитель берёт заявку и ведёт переписку (FR-208, FR-214, FR-217, FR-237, FR-242…FR-246,
FR-255, FR-257, FR-283)."""
import re
import secrets
import time
import urllib.parse
from datetime import datetime

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_org import eicar_bytes
from tests.support_servicedesk import build_mail

_FEED = "ol[data-feed]"


def _word() -> str:
    """Уникальное слово темы: буква и шесть шестнадцатеричных знаков (доп. 41 (в); одни цифры поиск принял бы за номер)."""
    return f"t{secrets.token_hex(3)}"


def _message_id() -> str:
    return f"<{secrets.token_hex(8)}@client.test>"


def _norm(text: str) -> str:
    """Текст письма с пробелами и переводами строк, сжатыми в один пробел."""
    return " ".join(text.split())


def _header(headers: dict, name: str) -> list:
    """Значения заголовка из ответа Mailpit без учёта регистра имени (значения — списки)."""
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return []


def _addresses(entries) -> list:
    """Адреса строчными из поля `To`/`Cc` письма Mailpit."""
    return [str(item.get("Address", "")).lower() for item in (entries or [])]


def _executor(admin_page, employee, queue_id):
    """Исполнитель — сотрудник, добавленный в узел очереди (взять заявку может участник очереди, 6.1).
    Возвращает (учётная запись, фамилия с уникальной частью, подпись «Имя Фамилия» по правилу C5, § 10.3)."""
    surname = f"Тест{secrets.token_hex(3)}"
    account = employee(full_name=f"{surname} Иванов Иван")
    helpers_sd.add_queue_member(admin_page, queue_id, [account.id], q=surname)
    return account, surname, f"Иванов {surname}"


def _new_ticket(page, *, cc=()):
    """Письмо заявителя на ящик заявок -> заявка. Возвращает (номер, слово темы, тема, адрес заявителя)."""
    word, sender = _word(), helpers_sd.requester_email()
    subject = f"Переписка по заявке {word}"
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], cc=list(cc), subject=subject,
                                  text=f"Не работает принтер {word}", message_id=_message_id()))
    return helpers_sd.ticket_number_by_subject(page, word), word, subject, sender


def _mail_in(sender: str, number: int, subject: str, text: str):
    """Письмо `Re: [#N] …` в ящик заявок от `sender`."""
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=f"Re: [#{number}] {subject}", text=text,
                                  message_id=_message_id()))


def _reply(page, number: int, text: str, *, wait: bool = False, files=None):
    """Ответ исполнителя из карточки (форма `ticket-reply`, 13.3); ждёт появления элемента `reply` в ленте.
    Возвращает локатор корня карточки."""
    card = helpers_sd.open_ticket(page, number)
    form = card.locator('form[data-form="ticket-reply"]')
    form.locator("textarea[name=text]").fill(text)
    if wait:
        form.locator("input[name=wait]").check()
    if files:
        form.locator("input[name=files]").set_input_files(files)
    helpers.submit(form)
    expect(card.locator(f'{_FEED} li[data-kind="reply"]').filter(has_text=text)).to_have_count(1)
    return card


def _comment(page, number: int, text: str):
    """Внутренний комментарий из карточки (форма `ticket-comment`); ждёт элемента `comment` в ленте."""
    card = helpers_sd.open_ticket(page, number)
    form = card.locator('form[data-form="ticket-comment"]')
    form.locator("textarea[name=text]").fill(text)
    helpers.submit(form)
    expect(card.locator(f'{_FEED} li[data-kind="comment"]').filter(has_text=text)).to_have_count(1)
    return card


def _take(page, number: int):
    """«Взять себе» со страницы карточки; ждёт вид «в работе»."""
    card = helpers_sd.open_ticket(page, number)
    card.locator('form[data-form="ticket-take"] button[data-action="ticket-take"]').click()
    expect(card).to_have_attribute("data-kind", "in_progress")
    return card


def _wait_feed(page, number: int, selector: str, *, timeout: float = 60.0):
    """Опрашивает карточку (перезагрузка) до появления `selector` внутри неё; предел — `timeout` с (проверку вложения
    делает настоящий clamd стенда). Возвращает локатор корня карточки."""
    deadline = time.monotonic() + timeout
    while True:
        card = helpers_sd.open_ticket(page, number)
        if card.locator(selector).count():
            return card
        if time.monotonic() >= deadline:
            raise AssertionError(f"в карточке заявки #{number} за {timeout:.0f} с не появилось: {selector}")
        page.wait_for_timeout(1500)


def _incoming(card):
    return card.locator(f'{_FEED} li[data-entry][data-kind="incoming"]')


def _event(card, code: str):
    return card.locator(f'{_FEED} li[data-kind="event"][data-event="{code}"]')


def test_d03_take_ticket_makes_assignee_in_progress_sends_taken_letter_with_name_and_feed_event(
        admin_page, employee, mailpit):
    """Сценарий 3, п. 1: исполнитель открывает пресет «Без ответственного», слайдер заявки, нажимает «Взять себе» —
    он ответственный, статус «В работе», заявитель получил письмо «взята в работу» с именем и фамилией
    ответственного, в ленте событие (FR-237, FR-208, FR-255)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    account, surname, signature = _executor(admin_page, employee, queue_id)
    number, word, _, sender = _new_ticket(admin_page)
    page = account.page
    page.set_viewport_size({"width": 1280, "height": 800})
    # дано: заявка без ответственного в очереди исполнителя; он открывает «Без ответственного» и щёлкает заявку
    page.goto("/tickets/?" + urllib.parse.urlencode({"preset": "unassigned", "q": word}))
    row = page.locator(f'#tickets-grid tr[data-ticket="{number}"]')
    expect(row).to_be_visible()
    row.locator('[data-cell="number"] a').click()
    card = page.locator("#slider-root [data-ticket-card]")
    expect(card).to_have_attribute("data-number", str(number))
    expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "true")
    # когда: «Взять себе»
    card.locator('form[data-form="ticket-take"] button[data-action="ticket-take"]').click()
    # п. 1: он ответственный, статус «В работе» (вид in_progress), кнопки «взять» больше нет
    expect(card).to_have_attribute("data-kind", "in_progress")
    expect(card.locator('[data-field="assignee"]')).to_contain_text(surname)
    assert helpers_sd.field_text(card, "status").lower() == "в работе"
    expect(card.locator('form[data-form="ticket-take"]')).to_have_count(0)
    # в ленте событие смены ответственного: «ответственный: не назначен → …»
    event = _event(card, "assignee_changed")
    expect(event).to_have_count(1)
    expect(event).to_contain_text("ответственный")
    expect(event).to_contain_text(surname)
    # заявитель получил письмо «взята в работу» с «Имя Фамилия» (§ 10.3 C5, § 10.4)
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.assigned", to=sender)
    assert f"Ваша заявка № {number} взята в работу. Ответственный: {signature}." in _norm(letter["Text"])
    assert letter["Subject"].startswith(f"[#{number}]")
    headers = helpers_sd.letter_headers(mailpit, letter["ID"])
    assert [value.lower() for value in _header(headers, "Auto-Submitted")] == ["auto-generated"]


def test_d03_reassign_to_other_assignee_sends_no_taken_letter(admin_page, employee, mailpit):
    """Сценарий 3, п. 2: у заявки уже был ответственный; её передают другому ответственному — второго письма
    «взята в работу» нет (FR-255)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    first, first_surname, first_signature = _executor(admin_page, employee, queue_id)
    second, second_surname, _ = _executor(admin_page, employee, queue_id)
    number, _, _, sender = _new_ticket(admin_page)
    # дано: первый исполнитель взял заявку — письмо «взята в работу» одно, с его именем
    _take(first.page, number)
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.assigned", to=sender)
    assert f"Ответственный: {first_signature}." in _norm(letter["Text"])
    # когда: администратор назначает другого ответственного (форма `ticket-assign`, подсказка по началу имени)
    card = helpers_sd.open_ticket(admin_page, number)
    form = card.locator('form[data-form="ticket-assign"]')
    form.locator("input[name=q]").fill(second_surname)
    candidate = form.locator(f'label[data-candidate][data-user-id="{second.id}"]')
    expect(candidate).to_have_count(1)
    candidate.locator("input[type=radio][name=assignee]").check()
    form.locator("button[type=submit]").click()
    # ответственный сменился, в ленте второе событие смены
    expect(card.locator('[data-field="assignee"]')).to_contain_text(second_surname)
    expect(_event(card, "assignee_changed")).to_have_count(2)
    # п. 2: письма «взята в работу» больше нет; доказательство — более позднее письмо (ответ) уже доставлено
    _reply(admin_page, number, f"Ответ после передачи {secrets.token_hex(3)}")
    helpers_sd.wait_letter(mailpit, number, "ticket.reply", to=sender)
    assigned = helpers_sd.ticket_letters(mailpit, number, template="ticket.assigned")
    assert len(assigned) == 1
    assert helpers_sd.ticket_letters(mailpit, number, template="ticket.assigned", recipient=sender)[0]["ID"] == (
        letter["ID"])


def test_d03_reply_with_waiting_flag_sets_waiting_status_mails_requester_and_cc_reply_to_mailbox(
        admin_page, employee, mailpit):
    """Сценарий 3, п. 3: ответ исполнителя с флажком «Ждём ответа заявителя» — статус вида «ждёт ответа заявителя»,
    письмо ушло заявителю и участнику в копии с темой `[#N] Тема`, адрес для ответа — ящик заявок (FR-208, FR-244,
    FR-257)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    account, surname, signature = _executor(admin_page, employee, queue_id)
    corp_cc = helpers_sd.requester_email("cc")
    number, _, subject, sender = _new_ticket(admin_page, cc=[corp_cc])
    _take(account.page, number)
    # когда: ответ с флажком «Ждём ответа заявителя»
    reply_text = f"Проверьте кабель питания {secrets.token_hex(3)}"
    card = _reply(account.page, number, reply_text, wait=True)
    # п. 3: статус вида «ждёт ответа заявителя»; в ленте ответ с отметкой «ответ исполнителя»
    expect(card).to_have_attribute("data-kind", "waiting")
    assert helpers_sd.field_text(card, "status").lower() == "ждёт ответа заявителя"
    reply_item = card.locator(f'{_FEED} li[data-kind="reply"]').filter(has_text=reply_text)
    expect(reply_item.locator("[data-reply-label]")).to_contain_text("ответ исполнителя")
    # письмо ответа: тема `[#N] Тема`, `To` — заявитель, `Cc` — участник, `Reply-To` — ящик заявок
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.reply", to=sender)
    assert letter["Subject"] == f"[#{number}] {subject}"
    assert _addresses(letter.get("To")) == [sender]
    assert _addresses(letter.get("Cc")) == [corp_cc]
    headers = helpers_sd.letter_headers(mailpit, letter["ID"])
    assert MAILBOX.lower() in " ".join(_header(headers, "Reply-To")).lower()
    assert _header(headers, "Auto-Submitted") == []  # у письма ответа заголовка нет (10.1)
    text = _norm(letter["Text"])
    assert reply_text in text
    assert signature in text


def test_d03_requester_or_participant_mail_with_number_appended_status_back_to_in_progress(admin_page):
    """Сценарий 3, п. 4: заявка вида «ждёт ответа заявителя»; письмо заявителя, а затем письмо участника с `[#N]` в
    теме дописаны в ленту, статус снова вида «в работе», новых заявок нет (FR-208, FR-214)."""
    helpers_sd.ensure_ready(admin_page)
    corp_cc = helpers_sd.requester_email("cc")
    number, word, subject, sender = _new_ticket(admin_page, cc=[corp_cc])
    # дано: ответ с флажком «Ждём ответа заявителя» — вид «ждёт ответа»
    card = _reply(admin_page, number, f"Уточните модель {secrets.token_hex(3)}", wait=True)
    expect(card).to_have_attribute("data-kind", "waiting")
    # когда: пишет заявитель
    requester_text = f"Модель принтера HP {secrets.token_hex(3)}"
    _mail_in(sender, number, subject, requester_text)
    # п. 4: письмо дописано в ленту, статус снова «в работе», заявка по-прежнему одна
    assert helpers_sd.tickets_by_subject(admin_page, word) == [number]
    card = helpers_sd.open_ticket(admin_page, number)
    expect(card).to_have_attribute("data-kind", "in_progress")
    assert helpers_sd.field_text(card, "status").lower() == "в работе"
    expect(_incoming(card)).to_have_count(2)
    expect(_incoming(card).filter(has_text=requester_text)).to_have_count(1)
    # снова ждём ответа; теперь пишет участник из копии
    card = _reply(admin_page, number, f"Ещё вопрос {secrets.token_hex(3)}", wait=True)
    expect(card).to_have_attribute("data-kind", "waiting")
    participant_text = f"Добавлю от коллеги {secrets.token_hex(3)}"
    _mail_in(corp_cc, number, subject, participant_text)
    assert helpers_sd.tickets_by_subject(admin_page, word) == [number]
    card = helpers_sd.open_ticket(admin_page, number)
    expect(card).to_have_attribute("data-kind", "in_progress")
    expect(_incoming(card)).to_have_count(3)
    mine = _incoming(card).filter(has_text=participant_text)
    expect(mine).to_have_count(1)
    expect(mine.locator('[data-author][data-author-kind="participant"]')).to_contain_text(corp_cc)


def test_d03_participant_reply_appended_corporate_stranger_with_number_creates_new_ticket(admin_page):
    """Сценарий 3, п. 5: участник из копии отвечает письмом — оно дописано; письмо с номером этой заявки от
    корпоративного адреса, который не заявитель и не участник, в неё не дописывается и создаёт новую заявку
    (FR-214)."""
    helpers_sd.ensure_ready(admin_page)
    corp_cc = helpers_sd.requester_email("cc")
    number, word, subject, _ = _new_ticket(admin_page, cc=[corp_cc])
    # участник отвечает: письмо дописано
    participant_text = f"Ответ участника {secrets.token_hex(3)}"
    _mail_in(corp_cc, number, subject, participant_text)
    assert helpers_sd.tickets_by_subject(admin_page, word) == [number]
    card = helpers_sd.open_ticket(admin_page, number)
    expect(_incoming(card)).to_have_count(2)
    expect(_incoming(card).filter(has_text=participant_text).locator('[data-author-kind="participant"]')) \
        .to_have_count(1)
    # посторонний корпоративный адрес с номером в теме: в заявку не дописано, новая заявка
    stranger, word2 = helpers_sd.requester_email("stranger"), _word()
    stranger_text = f"Пишу с номером чужой заявки {word2}"
    helpers_sd.deliver(build_mail(from_addr=stranger, to=[MAILBOX], subject=f"Re: [#{number}] Вопрос {word2}",
                                  text=stranger_text, message_id=_message_id()))
    new_number = helpers_sd.ticket_number_by_subject(admin_page, word2)
    assert new_number != number
    new_card = helpers_sd.open_ticket(admin_page, new_number)
    assert stranger in helpers_sd.field_text(new_card, "requester-email").lower()
    expect(_incoming(new_card).filter(has_text=stranger_text)).to_have_count(1)
    old_card = helpers_sd.open_ticket(admin_page, number)
    expect(_incoming(old_card)).to_have_count(2)
    expect(old_card.locator(_FEED)).not_to_contain_text(stranger_text)


def test_d03_internal_comment_marked_visible_to_staff_only_and_not_mailed(admin_page, employee, mailpit):
    """Сценарий 3, п. 6: внутренний комментарий помечен в ленте «внутренний», виден сотруднику с доступом к заявке,
    не виден сотруднику без доступа и письмом не уходит ни заявителю, ни участнику (FR-245)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    author, _, _ = _executor(admin_page, employee, queue_id)
    viewer, _, _ = _executor(admin_page, employee, queue_id)
    outsider = employee(full_name=f"Тест{secrets.token_hex(3)} Петров Пётр")  # не в очереди заявки
    corp_cc = helpers_sd.requester_email("cc")
    number, _, _, sender = _new_ticket(admin_page, cc=[corp_cc])
    comment_text = f"Служебная заметка {secrets.token_hex(3)}"
    # когда: исполнитель добавляет внутренний комментарий
    card = _comment(author.page, number, comment_text)
    # п. 6: помечен в ленте
    item = card.locator(f'{_FEED} li[data-kind="comment"]').filter(has_text=comment_text)
    expect(item.locator("[data-internal]")).to_contain_text("внутренний")
    # виден другому сотруднику с доступом
    seen = helpers_sd.open_ticket(viewer.page, number)
    expect(seen.locator(f'{_FEED} li[data-kind="comment"]').filter(has_text=comment_text)).to_have_count(1)
    # не виден сотруднику без доступа к заявке: карточки нет вовсе (404 по 12.4)
    response = helpers_org.direct_get(outsider.page, f"/tickets/{number}/")
    assert response.status == 404
    assert comment_text not in response.text()
    # письмом не уходит: ждём подтверждение (оно уходит первым), затем окно, в котором письма с комментарием нет
    helpers_sd.wait_letter(mailpit, number, "ticket.confirmation", to=sender)
    assert helpers_sd.no_letter(mailpit, number, "ticket.reply", wait=15)
    assert helpers_sd.ticket_letters(mailpit, number, recipient=corp_cc) == []
    # усиление: после комментария исполнитель отвечает, письмо ответа доставлено — очередь писем разобрана, в письмах
    # (и в ответе, и во всех прочих) текста комментария нет
    _reply(author.page, number, f"Ответ после заметки {secrets.token_hex(3)}")
    helpers_sd.wait_letter(mailpit, number, "ticket.reply", to=sender)
    for short in helpers_sd.ticket_letters(mailpit, number):
        assert comment_text not in mailpit.message(short["ID"])["Text"]


def test_d03_reply_with_quarantined_attachment_not_sent_note_in_feed(admin_page, mailpit):
    """Сценарий 3, п. 7: вложение ответа (EICAR, настоящий clamd стенда) ушло в карантин — письмо не уходит, в
    заявке «ответ не отправлен: вложение «…» в карантине», в ленте отметка вложения (FR-244, FR-283)."""
    helpers_sd.ensure_ready(admin_page)
    number, _, _, sender = _new_ticket(admin_page)
    helpers_sd.wait_letter(mailpit, number, "ticket.confirmation", to=sender)
    file_name = f"virus{secrets.token_hex(3)}.txt"
    reply_text = f"Во вложении инструкция {secrets.token_hex(3)}"
    # когда: исполнитель отправляет ответ с заражённым файлом
    _reply(admin_page, number, reply_text,
           files={"name": file_name, "mimeType": "text/plain", "buffer": eicar_bytes()})
    # п. 7: проверка завершилась (до 60 с) — в ленте «ответ не отправлен», вложение в карантине
    card = _wait_feed(admin_page, number, 'li[data-kind="event"][data-event="reply_not_sent"]')
    note = _event(card, "reply_not_sent")
    expect(note).to_have_count(1)
    assert f"ответ не отправлен: вложение «{file_name}» в карантине" in _norm(note.inner_text())  # 14.5
    expect(_event(card, "attachment_quarantined")).to_have_count(1)
    reply_item = card.locator(f'{_FEED} li[data-kind="reply"]').filter(has_text=reply_text)
    attachment = reply_item.locator('ul[data-attachments] [data-attachment][data-state="quarantine"]')
    expect(attachment).to_have_count(1)
    expect(attachment).to_contain_text(file_name)
    expect(attachment.locator("a")).to_have_count(0)
    expect(card.locator(f'{_FEED} li[data-entry-id] [data-send-state="not_sent"]')).to_have_count(1)  # доп. 42 (в)
    # письмо ответа не ушло
    assert helpers_sd.no_letter(mailpit, number, "ticket.reply", wait=10)


def test_d03_feed_messages_have_no_edit_or_delete(admin_page):
    """Сценарий 3, п. 9: у сообщений и событий ленты нет возможности изменить или удалить: в разметке нет форм и
    ссылок правки и удаления, а маршруты правки и удаления отвечают 404, текст не меняется (FR-246)."""
    helpers_sd.ensure_ready(admin_page)
    number, _, _, _ = _new_ticket(admin_page)
    reply_text, comment_text = f"Ответ {secrets.token_hex(3)}", f"Заметка {secrets.token_hex(3)}"
    _reply(admin_page, number, reply_text)
    card = _comment(admin_page, number, comment_text)
    feed = card.locator(_FEED)
    expect(card.locator(f'{_FEED} li[data-entry]')).not_to_have_count(0)
    # п. 9: в элементах ленты нет форм, кнопок и ссылок правки и удаления
    expect(feed.locator("form")).to_have_count(0)
    expect(feed.locator("button")).to_have_count(0)
    expect(feed.locator('a[href*="edit"], a[href*="delete"], [data-action*="edit"], [data-action*="delete"]')) \
        .to_have_count(0)
    # прямые маршруты правки и удаления (12.4): 404 и на GET, и на POST
    entry_id = card.locator(f'{_FEED} li[data-kind="reply"]').first.get_attribute("data-entry-id")
    for path in (f"/tickets/{number}/entries/{entry_id}/", f"/tickets/{number}/reply/{entry_id}/edit/",
                 f"/tickets/{number}/reply/{entry_id}/delete/"):
        assert helpers_org.direct_get(admin_page, path).status == 404, path
        assert helpers_org.direct_post(admin_page, path, {"text": "правка"}).status == 404, path
    after = helpers_sd.open_ticket(admin_page, number)
    expect(after.locator(f'{_FEED} li[data-kind="reply"]').filter(has_text=reply_text)).to_have_count(1)
    expect(after.locator(f'{_FEED} li[data-kind="comment"]').filter(has_text=comment_text)).to_have_count(1)


def test_d03_remove_participant_stops_mail_and_incoming_not_appended_event_in_feed(admin_page, mailpit):
    """Сценарий 3, п. 10: исполнитель убирает участника и подтверждает — в ленте событие, участник больше не
    получает писем, его письмо в заявку не дописывается (создаётся новая заявка) (FR-217)."""
    helpers_sd.ensure_ready(admin_page)
    removed, kept = helpers_sd.requester_email("gone"), helpers_sd.requester_email("kept")
    number, _, _, sender = _new_ticket(admin_page, cc=[removed, kept])
    card = helpers_sd.open_ticket(admin_page, number)
    expect(card.locator('[data-section="participants"] [data-participant]')).to_have_count(2)
    # когда: «убрать» участника и подтвердить в диалоге
    row = card.locator('[data-section="participants"] [data-participant]').filter(has_text=removed)
    expect(row).to_have_count(1)
    row.locator('a[data-action="participant-remove"]').click()
    dialog = admin_page.locator('#dialog-root [data-dialog="participant-remove"]')
    expect(dialog).to_be_visible()
    dialog.locator("form button[type=submit]").click()
    # п. 10: участник помечен снятым, у него нет действия «убрать», в ленте событие
    gone = card.locator('[data-section="participants"] [data-participant][data-removed="true"]')
    expect(gone).to_have_count(1)
    expect(gone).to_contain_text(removed)
    expect(gone.locator('a[data-action="participant-remove"]')).to_have_count(0)
    expect(_event(card, "participant_removed")).to_have_count(1)
    expect(_event(card, "participant_removed")).to_contain_text("участник снят")
    # письма: ответ исполнителя идёт заявителю и оставшемуся участнику, снятому — нет ни в `To`, ни в `Cc`
    _reply(admin_page, number, f"Ответ после снятия {secrets.token_hex(3)}")
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.reply", to=sender)
    assert _addresses(letter.get("To")) == [sender]
    assert _addresses(letter.get("Cc")) == [kept]
    assert helpers_sd.ticket_letters(mailpit, number, recipient=removed) == []
    # его письмо с номером заявки в неё не дописано: новая заявка, в старой входящее одно
    word2 = _word()
    helpers_sd.deliver(build_mail(from_addr=removed, to=[MAILBOX], subject=f"Re: [#{number}] Вопрос {word2}",
                                  text=f"Пишу после снятия {word2}", message_id=_message_id()))
    new_number = helpers_sd.ticket_number_by_subject(admin_page, word2)
    assert new_number != number
    old_card = helpers_sd.open_ticket(admin_page, number)
    expect(_incoming(old_card)).to_have_count(1)
    expect(old_card.locator(_FEED)).not_to_contain_text(word2)


def test_d03_card_slider_over_600px_list_and_separate_page_up_to_600px(admin_page):
    """Сценарий 3, п. 11: при ширине больше 600 px щелчок по заявке в списке открывает слайдер поверх списка (слева
    поля, справа лента), при ширине до 600 px — отдельную страницу с перепиской под полями (FR-242)."""
    helpers_sd.ensure_ready(admin_page)
    number, word, _, _ = _new_ticket(admin_page)
    page = admin_page
    list_url = "/tickets/?" + urllib.parse.urlencode({"preset": "all", "q": word})
    link = page.locator(f'#tickets-grid tr[data-ticket="{number}"] [data-cell="number"] a')
    # ширина больше 600 px: слайдер поверх списка
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(list_url)
    expect(link).to_have_attribute("href", f"/tickets/{number}/")
    link.click()
    card = page.locator("#slider-root .slider-panel [data-ticket-card]")
    # «своя ссылка» слайдера (доп. 42 (и)): адрес страницы сменился на адрес карточки
    page.wait_for_url(re.compile(rf"/tickets/{number}/$"))
    expect(card).to_have_attribute("data-layout", "slider")
    expect(card).to_have_attribute("data-number", str(number))
    expect(page.locator("#slider-root [data-slider-close]")).to_be_visible()
    expect(page.locator("#tickets-grid")).to_be_visible()  # список остался под слайдером
    fields, feed = card.locator("[data-card-fields]"), card.locator("[data-card-feed]")
    expect(fields).to_be_visible()
    expect(feed).to_be_visible()
    left, right = fields.bounding_box(), feed.bounding_box()
    assert left["x"] < right["x"]  # слева поля, справа лента
    assert left["x"] + left["width"] <= right["x"] + 2
    # этот адрес, открытый заново, показывает ту же карточку страницей
    page.goto(f"/tickets/{number}/")
    own = page.locator(f'[data-ticket-card][data-number="{number}"]')
    expect(own).to_have_attribute("data-layout", "page")
    expect(page.locator("#slider-root [data-ticket-card]")).to_have_count(0)
    # ширина до 600 px: отдельная страница, лента под полями
    page.set_viewport_size({"width": 500, "height": 800})
    page.goto(list_url)
    expect(link).to_be_visible()
    link.click()
    page.wait_for_url(re.compile(rf"/tickets/{number}/$"))
    card = page.locator(f'[data-ticket-card][data-number="{number}"]')
    expect(card).to_have_attribute("data-layout", "page")
    expect(page.locator("#slider-root [data-ticket-card]")).to_have_count(0)
    fields, feed = card.locator("[data-card-fields]"), card.locator("[data-card-feed]")
    expect(fields).to_be_visible()
    expect(feed).to_be_visible()
    top, bottom = fields.bounding_box(), feed.bounding_box()
    assert bottom["y"] >= top["y"] + top["height"] - 2  # переписка под полями


def test_d03_feed_shows_all_item_kinds_in_time_order_with_author_and_comment_mark(admin_page, employee):
    """Сценарий 3, п. 12: в ленте письмо заявителя, письмо участника, событие, ответ исполнителя и внутренний
    комментарий — всё по времени; у каждого элемента время и автор (имя сотрудника, «заявитель» или «участник» с
    адресом), комментарий помечен (FR-243)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    account, surname, _ = _executor(admin_page, employee, queue_id)
    corp_cc = helpers_sd.requester_email("cc")
    number, _, subject, sender = _new_ticket(admin_page, cc=[corp_cc])
    participant_text = f"Письмо участника {secrets.token_hex(3)}"
    _mail_in(corp_cc, number, subject, participant_text)
    _take(account.page, number)  # событие смены ответственного
    reply_text, comment_text = f"Ответ исполнителя {secrets.token_hex(3)}", f"Заметка {secrets.token_hex(3)}"
    _reply(account.page, number, reply_text)
    card = _comment(account.page, number, comment_text)
    # элементы ленты по порядку разметки: вид, код события, время, автор, пометки
    items = card.locator(f"{_FEED} li[data-entry]").evaluate_all("""els => els.map(e => {
        const time = e.querySelector('time[data-at]');
        const author = e.querySelector('[data-author]');
        const label = e.querySelector('[data-reply-label]');
        return {kind: e.dataset.kind, event: e.dataset.event || '',
                at: time ? time.dataset.at : '', shown: time ? time.textContent.trim() : '',
                author_kind: author ? author.dataset.authorKind : '', author: author ? author.textContent : '',
                internal: !!e.querySelector('[data-internal]'), label: label ? label.textContent : '',
                text: e.textContent};
    })""")
    # п. 12: у каждого элемента есть время `ДД.ММ.ГГГГ ЧЧ:ММ` по Москве, и порядок разметки — порядок времени
    stamps = []
    for item in items:
        assert item["at"], item
        assert re.fullmatch(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}", item["shown"]), item["shown"]
        stamps.append(datetime.fromisoformat(item["at"]))
    assert stamps == sorted(stamps)
    # виды: два входящих, ответ, комментарий и события; порядок вида — как происходило
    people = [item for item in items if item["kind"] != "event"]
    assert [item["kind"] for item in people] == ["incoming", "incoming", "reply", "comment"]
    kinds = [item["kind"] for item in items]
    taken = [i for i, item in enumerate(items) if item["event"] == "assignee_changed"]
    assert len(taken) == 1
    incoming_at = [i for i, kind in enumerate(kinds) if kind == "incoming"]
    assert incoming_at[1] < taken[0] < kinds.index("reply")
    # авторы у событий (доп. 42 (а)): у события смены ответственного автор — исполнитель, взявший заявку
    event = items[taken[0]]
    assert event["author_kind"] == "staff" and surname in event["author"], event
    # авторы: заявитель и участник — с адресом, сотрудник — с именем; комментарий помечен «внутренний»
    first, second, reply, comment = people
    assert first["author_kind"] == "requester" and sender in first["author"].lower()
    assert second["author_kind"] == "participant" and corp_cc in second["author"].lower()
    assert reply["author_kind"] == "staff" and surname in reply["author"]
    assert comment["author_kind"] == "staff" and surname in comment["author"]
    assert "ответ исполнителя" in reply["label"] and not reply["internal"]
    assert comment["internal"] and "внутренний" in comment["text"]
    assert not any(item["internal"] for item in people if item["kind"] != "comment")
