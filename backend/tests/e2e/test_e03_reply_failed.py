"""T-4142: сценарий 3 — ответ заявителю не ушёл: ответственный узнаёт, что ответ не отправлен из-за вложения в карантине
или архива с паролем; без ответственного, без доступа и при закрытии заявки в ходе проверки уведомления нет
(FR-312, FR-314, FR-316).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-004.md):
- все пять тестов доводят ответ до `reply_not_sent` путями среза 003: ответ исполнителя с вложением идёт на проверку
  заданием (настоящий clamd стенда), по её итогу `replies.on_files_checked` пишет в ленту «ответ не отправлен: …» и
  публикует событие `servicedesk.reply_not_sent` (CONTRACT-004 § 4.2, `actor_id=None`); поэтому ответственный получает
  уведомление, даже если ответ написал он сам (здесь ответы пишет администратор, ответственный — другой сотрудник);
- пути «письмо не доставлено» (`mail_failed`, пп. 1 и 3 сценария) в приёмке нет: способа довести письмо до недоставки
  после всех попыток с хоста контракт не даёт (вопрос к Opus в отчёте); имена тестов сценария — пп. 2, 4, 5, 6, 7;
- текст уведомления не содержит темы заявки (CONTRACT-004 § 15.1), поэтому строки находятся по номеру заявки и словам
  «Ответ по заявке #N» (с границей числа: `#12` не совпадает с `#123`);
- «нет уведомления» всегда доказывается порядком: сначала событие без получателя (оно записано в ленте), затем событие
  того же вида, которое уведомление ответственному даёт, — когда второе пришло, первое уже обработано, и его отсутствие
  в списке не случайность;
- каждый тест заводит свою очередь, своих сотрудников и свои заявки (имена уникальны); очередь по умолчанию на время
  теста меняется на свою и возвращается в `finally` (письмо заявителя попадает в очередь по умолчанию).
"""
import contextlib
import re
import secrets
import time

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_org import eicar_bytes
from tests.support_servicedesk import build_mail, sample

_FEED = "ol[data-feed]"
CHECK_WAIT = 180.0  # с: проверку вложения делает настоящий clamd стенда (CONTRACT-003, 6.6); запас — под нагрузкой
# круга проверка шла дольше 60 с (красный прогон T-4160), отдельно — 4–8 с
NOTE_WAIT = 30.0  # с: уведомление после записи события в ленту
_RQ_CONN = "import redis; from django.conf import settings; r = redis.Redis.from_url(settings.VALKEY_URL); "


# --- Общие помощники файла ----------------------------------------------------------------------------

def _word() -> str:
    """Уникальное слово темы: буква и шесть шестнадцатеричных знаков (не из одних цифр, иначе поиск списка принял бы
    его за номер заявки; CONTRACT-003, доп. 41 (в))."""
    return f"t{secrets.token_hex(3)}"


def _tag() -> str:
    """Общее начало фамилий сотрудников теста: по нему «Добавить сотрудников» находит всех сразу."""
    return "Ответ" + secrets.token_hex(3)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _staff(employee, tag: str, index: int):
    return employee(full_name=f"{tag}{index} Петр Петрович")


def _queue(page, prefix: str = "Поддержка") -> tuple:
    """Новый узел `org`, отмеченный очередью: `(номер, название)`."""
    name = helpers_org.unique_name(prefix)
    unit_id = helpers_org.create_unit(page, name)
    helpers_sd.mark_queue(page, unit_id)
    return unit_id, name


def _members(page, queue_id, accounts, tag: str) -> None:
    """Прямые участники узла-очереди (у отдела — режим «параллельно»)."""
    page.goto(f"/structure/{queue_id}/")
    mode = "concurrent" if page.locator("#unit-card select[name=mode]").count() else None
    note = helpers_org.add_members(page, queue_id, [a.id for a in accounts], q=tag, mode=mode)
    assert "уже участник" not in note, note
    helpers_org.open_structure(page, queue_id)
    for account in accounts:
        expect(helpers_org.member_row(page, account.id)).to_have_count(1)


@contextlib.contextmanager
def _default_queue(page, old_id, queue_id):
    """Очередь по умолчанию на время теста — своя (письмо попадает в неё); прежняя возвращается в `finally`."""
    helpers_sd.set_default_queue(page, queue_id)
    try:
        yield
    finally:
        helpers_sd.set_default_queue(page, old_id)


def _new_ticket(page) -> tuple:
    """Письмо заявителя в ящик заявок и разбор: заявка в очереди по умолчанию без ответственного.
    Возвращает `(номер, слово темы)`."""
    word = _word()
    helpers_sd.deliver(build_mail(from_addr=helpers_sd.requester_email(), to=[MAILBOX],
                                  subject=f"Не работает принтер {word}", text=f"Нужна помощь {word}",
                                  message_id=f"<{secrets.token_hex(8)}@client.test>"))
    return helpers_sd.ticket_number_by_subject(page, word), word


def _take(page, number: int) -> None:
    """«Взять себе» со страницы карточки (страница исполнителя); ждёт вид «в работе»."""
    card = helpers_sd.open_ticket(page, number)
    card.locator('form[data-form="ticket-take"] button[data-action="ticket-take"]').click()
    expect(card).to_have_attribute("data-kind", "in_progress")


def _reply(page, number: int, text: str, files):
    """Ответ исполнителя из карточки (форма `ticket-reply`, CONTRACT-003 § 13.3) с вложениями `files`; ждёт, пока
    элемент `reply` появится в ленте. Возвращает локатор корня карточки."""
    card = helpers_sd.open_ticket(page, number)
    form = card.locator('form[data-form="ticket-reply"]')
    form.locator("textarea[name=text]").fill(text)
    form.locator("input[type=file][name=files]").set_input_files(files)
    helpers.submit(form)
    expect(card.locator(f'{_FEED} li[data-kind="reply"]').filter(has_text=text)).to_have_count(1)
    return card


def _wait_feed(page, number: int, selector: str, *, timeout: float = CHECK_WAIT):
    """Опрашивает карточку (перезагрузка) до появления `selector` внутри неё; предел — `timeout` с. Возвращает локатор
    корня карточки."""
    deadline = time.monotonic() + timeout
    while True:
        card = helpers_sd.open_ticket(page, number)
        if card.locator(selector).count():
            return card
        if time.monotonic() >= deadline:
            raise AssertionError(f"в карточке заявки #{number} за {timeout:.0f} с не появилось: {selector}")
        page.wait_for_timeout(1500)


def _event(card, code: str):
    return card.locator(f'{_FEED} li[data-kind="event"][data-event="{code}"]')


def _failed_rows(page, number: int):
    """Открывает `/notifications/` и возвращает строки вида «Ответ заявителю не ушёл» по заявке `number`: тексты
    «Ответ по заявке #N …» и «Письмо по заявке #N …» (CONTRACT-004 § 15.1; тема в них не стоит). Список только читает.
    Новая заявка в очереди и прочие уведомления с тем же номером в выборку не входят."""
    page.goto("/notifications/")
    expect(page.locator("[data-notify-list]")).to_be_visible()
    pattern = re.compile(rf"(?:Ответ|Письмо)\s+по\s+заявке\s+#{number}(?!\d)")
    return page.locator("ul[data-notifications] li[data-notification]").filter(has_text=pattern)


def _wait_failed(page, number: int, *, timeout: float = NOTE_WAIT):
    """Ждёт (перезагрузкой списка), пока по заявке появится строка вида «Ответ заявителю не ушёл»; возвращает её
    локатор (ровно одна строка: одно событие — одно уведомление)."""
    deadline = time.monotonic() + timeout
    while True:
        rows = _failed_rows(page, number)
        if rows.count():
            expect(rows).to_have_count(1)
            return rows
        if time.monotonic() >= deadline:
            raise AssertionError(f"за {timeout:.0f} с в списке уведомлений нет «Ответ/Письмо по заявке #{number}»")
        page.wait_for_timeout(1000)


def _expect_failed(rows, expected: str) -> None:
    """Строка непрочитана, её текст равен `expected` (текст контракта дословный, § 15.1)."""
    expect(rows).to_have_attribute("data-unread", "1")
    assert _norm(rows.locator('[data-field="text"]').inner_text()) == _norm(expected)


def _quarantined(page, number: int, name: str) -> None:
    """Администратор отвечает с заражённым вложением (EICAR) и ждёт в ленте «ответ не отправлен … в карантине»
    (проверка до 60 с); возвращает локатор карточки."""
    text = f"Ответ {secrets.token_hex(3)} с файлом"
    _reply(page, number, text, {"name": name, "mimeType": "text/plain", "buffer": eicar_bytes()})
    card = _wait_feed(page, number, f'{_FEED} li[data-kind="event"][data-event="reply_not_sent"]')
    expect(_event(card, "reply_not_sent")).to_have_count(1)
    assert f"ответ не отправлен: вложение «{name}» в карантине" in _norm(_event(card, "reply_not_sent").inner_text())
    return card


def _pause_jobs() -> None:
    """Пауза RQ стенда (CONTRACT-004, доп. 26): обработчики не берут новые задания, ttl 120 с снимет паузу сам."""
    helpers.stand_shell(_RQ_CONN + "from rq import suspension; suspension.suspend(r, ttl=120)")


def _resume_jobs() -> None:
    """Снимает паузу RQ (доп. 26); повторный вызов безвреден."""
    helpers.stand_shell(_RQ_CONN + "from rq import suspension; suspension.resume(r)")


# --- Тесты --------------------------------------------------------------------------------------------------

def test_e03_reply_attachment_quarantined_notifies_assignee_reply_not_sent_with_quarantine_reason(
        admin_page, employee):
    """Сценарий 3, п. 2: вложение ответа ушло в карантин и письмо не отправлено — в ленте появилось «ответ не
    отправлен», ответственный получает «Ответ по заявке #N не отправлен: вложение в карантине»; другой участник очереди
    и автор ответа, не ответственные, уведомления не получают (FR-312, FR-316)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    assignee, other = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [assignee, other], tag)
    with _default_queue(page, old_id, queue_id):
        # дано: заявка в очереди, ответственный — первый сотрудник
        number, _ = _new_ticket(page)
        _take(assignee.page, number)
        # когда: администратор отвечает с заражённым вложением; проверка завершилась — в ленте «ответ не отправлен»
        file_name = f"virus{secrets.token_hex(3)}.txt"
        card = _quarantined(page, number, file_name)
        expect(card.locator(f'{_FEED} li[data-entry-id] [data-send-state="not_sent"]')).to_have_count(1)
        # п. 2: ответственный получает уведомление с текстом контракта, оно не прочитано
        rows = _wait_failed(assignee.page, number)
        _expect_failed(rows, f"Ответ по заявке #{number} не отправлен: вложение в карантине")
        # п. 2: нажатие на текст открывает заявку
        rows.locator("a[data-open]").click()
        assignee.page.wait_for_url(re.compile(rf"/tickets/{number}/$"))
        expect(assignee.page.locator(f'[data-ticket-card][data-number="{number}"]')).to_be_visible()
        # п. 2: уведомление получает только ответственный — не другой участник очереди и не автор ответа
        expect(_failed_rows(other.page, number)).to_have_count(0)
        expect(_failed_rows(page, number)).to_have_count(0)


def test_e03_ticket_without_assignee_gives_no_notification_and_event_stays_in_feed(admin_page, employee):
    """Сценарий 3, п. 4: у заявки нет ответственного и ответ не отправлен — уведомления нет, событие остаётся в ленте
    заявки; для сравнения заявка с ответственным в тот же час уведомление даёт (FR-312)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    assignee, other = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [assignee, other], tag)
    with _default_queue(page, old_id, queue_id):
        # дано: заявка без ответственного
        free_number, _ = _new_ticket(page)
        # когда: ответ не отправлен (вложение в карантине) — событие записано в ленту
        _quarantined(page, free_number, f"virus{secrets.token_hex(3)}.txt")
        # сравнение: следом такая же история у заявки с ответственным — его уведомление пришло
        owned_number, _ = _new_ticket(page)
        _take(assignee.page, owned_number)
        _quarantined(page, owned_number, f"virus{secrets.token_hex(3)}.txt")
        rows = _wait_failed(assignee.page, owned_number)
        _expect_failed(rows, f"Ответ по заявке #{owned_number} не отправлен: вложение в карантине")
        # п. 4: по заявке без ответственного уведомления нет ни у кого из участников очереди
        expect(_failed_rows(assignee.page, free_number)).to_have_count(0)
        expect(_failed_rows(other.page, free_number)).to_have_count(0)
        # п. 4: событие осталось в ленте заявки
        card = helpers_sd.open_ticket(page, free_number)
        expect(_event(card, "reply_not_sent")).to_have_count(1)


def test_e03_employee_without_access_to_ticket_gets_no_notification(admin_page, employee):
    """Сценарий 3, п. 5: сотрудник без доступа к заявке (участник другой очереди) при событии «ответ не отправлен»
    уведомления не получает и заявку не открывает, а ответственный получает (FR-314)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    assignee, outsider = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, _name = _queue(page)
    other_id, _other_name = _queue(page, "Другая")
    _members(page, queue_id, [assignee], tag)
    _members(page, other_id, [outsider], tag)
    with _default_queue(page, old_id, queue_id):
        number, _ = _new_ticket(page)
        _take(assignee.page, number)
        # когда: ответ не отправлен (вложение в карантине)
        _quarantined(page, number, f"virus{secrets.token_hex(3)}.txt")
        # сравнение: ответственный получил
        rows = _wait_failed(assignee.page, number)
        _expect_failed(rows, f"Ответ по заявке #{number} не отправлен: вложение в карантине")
        # п. 5: у сотрудника без доступа заявки нет (404 при прямом обращении) и уведомления нет
        response = helpers_org.direct_get(outsider.page, f"/tickets/{number}/")
        assert response.status == 404
        expect(_failed_rows(outsider.page, number)).to_have_count(0)


def test_e03_reply_with_password_protected_archive_notifies_assignee_with_archive_reason(admin_page, employee):
    """Сценарий 3, п. 6: вложение ответа — архив с паролем (вложенный ZIP с паролем: собственная проверка заголовков его
    не видит, находит clamd) и письмо не отправлено — в ленте «ответ не отправлен: вложение … — архив с паролем»,
    ответственный получает «Ответ по заявке #N не отправлен: вложение — архив с паролем» (FR-312, FR-316)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    assignee = _staff(employee, tag, 1)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [assignee], tag)
    with _default_queue(page, old_id, queue_id):
        number, _ = _new_ticket(page)
        _take(assignee.page, number)
        # когда: администратор отвечает с архивом, внутри которого архив с паролем
        archive = f"secret-{secrets.token_hex(3)}.zip"
        text = f"Ответ {secrets.token_hex(3)} с архивом"
        _reply(page, number, text, {"name": archive, "mimeType": "application/zip",
                                    "buffer": sample("nested_enc_zip.zip")})
        # п. 6: проверка завершилась — в ленте «ответ не отправлен … — архив с паролем», письма нет
        card = _wait_feed(page, number, f'{_FEED} li[data-kind="event"][data-event="reply_not_sent"]')
        expect(_event(card, "reply_not_sent")).to_have_count(1)
        assert f"ответ не отправлен: вложение «{archive}» — архив с паролем" in _norm(
            _event(card, "reply_not_sent").inner_text())
        expect(card.locator(f'{_FEED} li[data-entry-id] [data-send-state="not_sent"]')).to_have_count(1)
        # п. 6: ответственный получает уведомление с причиной «архив с паролем», не «карантин»
        rows = _wait_failed(assignee.page, number)
        _expect_failed(rows, f"Ответ по заявке #{number} не отправлен: вложение — архив с паролем")
        assert "карантин" not in rows.locator('[data-field="text"]').inner_text()


def test_e03_ticket_closed_during_attachment_check_gives_no_notification(admin_page, employee):
    """Сценарий 3, п. 7: заявка закрыта, пока шла проверка вложений ответа, и ответ не отправлен — в ленте «ответ не
    отправлен: заявка закрыта», уведомления нет (заявку закрыл сам исполнитель или коллега); для сравнения следующая
    заявка с заражённым вложением уведомление ответственному даёт (FR-312)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    assignee = _staff(employee, tag, 1)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [assignee], tag)
    closer = page.context.new_page()  # вторая страница администратора: диалог закрытия открыт заранее
    try:
        with _default_queue(page, old_id, queue_id):
            number, _ = _new_ticket(page)
            _take(assignee.page, number)
            # дано: диалог закрытия открыт и заполнен — остаётся нажать кнопку
            helpers_sd.open_ticket(closer, number)
            closer.locator('a[data-action="ticket-close"]').click()
            dialog = closer.locator('#dialog-root [data-dialog="ticket-close"]')
            expect(dialog).to_be_visible()
            dialog.locator("textarea[name=resolution]").fill(f"Решено {secrets.token_hex(3)}")
            # когда: задания стоят на паузе (проверка вложения не начнётся), ответ с чистым файлом ушёл на проверку,
            # заявку закрывают, и только затем пауза снимается (доп. 26)
            _pause_jobs()
            try:
                _reply(page, number, f"Ответ {secrets.token_hex(3)} с файлом",
                       {"name": f"clean{secrets.token_hex(3)}.txt", "mimeType": "text/plain",
                        "buffer": b"clean text " + secrets.token_hex(64).encode()})
                dialog.locator("button[type=submit]").click()
                expect(closer.locator(f'[data-ticket-card][data-number="{number}"]')).to_have_attribute(
                    "data-kind", "closed")
            finally:
                _resume_jobs()
            # п. 7: проверка завершилась после закрытия — в ленте «ответ не отправлен: заявка закрыта»
            card = _wait_feed(page, number, f'{_FEED} li[data-kind="event"][data-event="reply_not_sent"]')
            expect(_event(card, "reply_not_sent")).to_have_count(1)
            assert "ответ не отправлен: заявка закрыта" in _norm(_event(card, "reply_not_sent").inner_text())
            # сравнение: следующая заявка того же ответственного с заражённым вложением — уведомление пришло
            second, _ = _new_ticket(page)
            _take(assignee.page, second)
            _quarantined(page, second, f"virus{secrets.token_hex(3)}.txt")
            rows = _wait_failed(assignee.page, second)
            _expect_failed(rows, f"Ответ по заявке #{second} не отправлен: вложение в карантине")
            # п. 7: по закрытой заявке уведомления нет
            expect(_failed_rows(assignee.page, number)).to_have_count(0)
    finally:
        closer.close()
