"""T-4145: сценарий 6 — привязка Telegram и MAX кодом, учебная служба ботов `fakebots`
(FR-317, FR-325, FR-326, FR-328, FR-336, FR-339, FR-340).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-004.md § 1.2, § 13.2, § 14.3, § 15.2, § 15.3, доп. 23, 24):
- каналы Telegram и MAX включает администратор страницы `/settings/notifications/` на время теста (помощник
  `helpers_notify.channels_on`, возврат в `finally`); где нужен выключенный канал — `helpers_notify.channels_off` (тоже с возвратом);
- `fakebots` одна на весь круг и без сброса, поэтому у каждой роли в тесте свой уникальный `chat_id`, а сообщения
  выбираются по нему (`helpers_notify.sent_to`, `wait_sent(..., chat_id=…)`); ответы бота сверяются с § 15.3 целиком;
- опрос включённого канала просыпается не сразу (`PAUSE_IDLE` 60 с, § 5.4): первое ожидание ответа бота и имени бота
  в тесте — до 120–150 с;
- код привязки читается со страницы (`[data-bind-code]`), нигде не печатается и в сообщениях проверок не называется;
- «старый или использованный код» шлётся из **нового** чата со своим `/start`: тот же код из того же чата при действующей
  привязке — это `repeat` без ответа (§ 6.14, решение E1), а не отказ;
- событие для сообщения во внешний канал — письмо заявителя в очередь теста (как в test_e01_new_ticket.py); тихих часов
  у получателя нет («Без тихих часов»): иначе вне рабочего времени сообщение ушло бы в сводку.
"""
import contextlib
import json
import os
import re
import secrets
import subprocess
import time
from urllib.parse import urlsplit

from playwright.sync_api import expect

from tests.e2e import conftest, helpers, helpers_notify, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_servicedesk import build_mail

NEW_IN_QUEUE = "servicedesk.new_in_queue"
EXTERNAL = "Новая заявка в вашей очереди"  # внешний текст вида (§ 15.2, FR-317)
CHANNEL_TITLE = {"telegram": "Telegram", "max": "MAX"}
BOT_ENV = {"telegram": "TELEGRAM_BOT_TOKEN", "max": "MAX_BOT_TOKEN"}  # доп. 24
BOT_NAME = "stand_notify_bot"  # имя бота из `getMe`/`me` у `fakebots` (§ 1.2)
BOT_HOST = {"telegram": "t.me", "max": "max.ru"}  # § 14.3: `https://t.me/<имя>` и `https://max.ru/<имя>`
ASK_CODE = "Отправьте код из раздела «Мои уведомления» портала"  # § 15.3
CODE_INVALID = "Код недействителен или просрочен. Получите новый код в портале"
CHAT_TAKEN = "Этот чат уже привязан к другой учётной записи портала"
BOUND = {"telegram": "Telegram привязан к вашей учётной записи портала",
         "max": "MAX привязан к вашей учётной записи портала"}
DISABLED_TEXT = "Канал отключён администратором"  # § 15.5
EXPIRES_TEXT = "действует 10 минут"  # § 15.5: «Код действует 10 минут»
FIRST_REPLY_WAIT = 120.0  # с: опрос только что включённого канала просыпается до 60 с (§ 5.4)
LINK_WAIT = 150.0  # с: имя бота появляется при старте цикла опроса (`start_cycle`, § 5.4)
REPLY_WAIT = 30.0
# инвариант «секреты-в-url» (docs/constitution.md): запрещённые формы адреса
URL_BAN_RES = (re.compile(r"[?&](password|passwd|pwd|pass|token|secret|api_?key)=", re.I),
                  re.compile(r"://[^/\s]+:[^/@\s]+@"))
EIGHT_DIGITS = re.compile(r"(?<!\d)\d{8}(?!\d)")  # любой «код из восьми цифр» в адресе


# --- Общие помощники файла ----------------------------------------------------------------------------

def _word() -> str:
    """Уникальное слово темы (не из одних цифр: поиск списка принял бы его за номер заявки)."""
    return f"t{secrets.token_hex(3)}"


def _tag() -> str:
    """Общее начало фамилий сотрудников теста: по нему «Добавить сотрудников» находит всех сразу."""
    return "Очередь" + secrets.token_hex(3)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _staff(employee, tag: str, index: int):
    return employee(full_name=f"{tag}{index} Петр Петрович")


def _chat_id() -> int:
    """Уникальный номер чата `fakebots` для роли теста (иначе «чат уже привязан к другой учётной записи»)."""
    return secrets.randbelow(900_000_000) + 100_000_000


def _queue(page, prefix: str = "Поддержка") -> tuple:
    """Новый узел `org`, отмеченный очередью: `(номер, название)`."""
    name = helpers_org.unique_name(prefix)
    unit_id = helpers_org.create_unit(page, name, kind="department")
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
    """Очередь по умолчанию на время теста — своя (письмо заявителя попадает в неё); прежняя — в `finally`."""
    helpers_sd.set_default_queue(page, queue_id)
    try:
        yield
    finally:
        helpers_sd.set_default_queue(page, old_id)


def _prefs(page, channels) -> None:
    """«Мои уведомления» сотрудника: у вида «Новая заявка в моей очереди» ячейки `channels` включены, режим тихих часов
    «Без тихих часов»; значение сохранено (§ 13.2, § 14.3). Ячейки telegram/max доступны только после привязки."""
    page.goto("/me/notifications/")
    form = page.locator('form[data-form="notify-prefs"]')
    expect(form).to_be_visible()
    for channel in channels:
        cell = form.locator(f'tr[data-notify-kind="{NEW_IN_QUEUE}"] td[data-channel="{channel}"] '
                            f'input[type=checkbox][name="cell"][value="{NEW_IN_QUEUE}:{channel}"]')
        expect(cell).to_have_count(1)
        cell.set_checked(True)
    form.locator('fieldset[data-quiet] input[type=radio][name="quiet_mode"][value="none"]').check()
    with page.expect_navigation():
        form.locator('button[type=submit][data-action="save-prefs"]').click()
    page.wait_for_load_state()
    assert not helpers.alert_text(page), f"настройки не сохранены: {helpers.alert_text(page)}"
    expect(page.locator("[role=status]").first).to_be_visible()
    for channel in channels:
        cell = page.locator(f'tr[data-notify-kind="{NEW_IN_QUEUE}"] td[data-channel="{channel}"] '
                            f'input[type=checkbox][name="cell"][value="{NEW_IN_QUEUE}:{channel}"]')
        expect(cell).to_be_checked()


def _new_ticket(requester: str | None = None) -> tuple:
    """Письмо заявителя в ящик заявок и сразу разбор: заявка в очереди по умолчанию, без ответственного.
    Возвращает `(слово, тема, адрес заявителя)`."""
    word = _word()
    subject = f"Не работает принтер {word}"
    requester = requester or helpers_sd.requester_email()
    helpers_sd.deliver(build_mail(from_addr=requester, to=[MAILBOX], subject=subject, text=f"Нужна помощь {word}",
                                  message_id=f"<{secrets.token_hex(8)}@client.test>"))
    return word, subject, requester


def _button_url(channel: str, message: dict) -> str:
    """Адрес кнопки внешнего сообщения: Telegram — `reply_markup.inline_keyboard[0][0].url`, MAX —
    `attachments[0].payload.buttons[0][0].url` (§ 5.2, § 15.2)."""
    if channel == "telegram":
        markup = message["reply_markup"]
        markup = json.loads(markup) if isinstance(markup, str) else markup
        return markup["inline_keyboard"][0][0]["url"]
    return message["attachments"][0]["payload"]["buttons"][0][0]["url"]


# --- Бот и страница привязки ---------------------------------------------------------------------------

def _count_text(bots, channel: str, chat, text: str) -> int:
    """Сколько сообщений бота в чат `chat` равны `text` (ответы бота и сообщения уведомлений)."""
    return len([m for m in helpers_notify.sent_to(bots, channel, chat) if m.get("text") == text])


def _expect_reply(bots, channel: str, chat, text: str, before: int, *, timeout: float = REPLY_WAIT) -> None:
    """Ждёт (до `timeout` с), пока число сообщений `text` в чат станет больше `before`, и сверяет текст целиком
    (§ 15.3: ответ равен тексту таблицы)."""
    found = helpers_notify.wait_sent(bots, channel, chat_id=chat, count=before + 1, text_has=text, timeout=timeout)
    assert found[-1]["text"] == text, f"{channel}: ответ бота не равен тексту §15.3"


def _no_new_messages(bots, channel: str, chat, known: int, *, observe: float = 6.0) -> None:
    """В чат `chat` за `observe` с не пришло ни одного сообщения сверх `known` (ожидание — опросом помощника)."""
    try:
        helpers_notify.wait_sent(bots, channel, chat_id=chat, count=known + 1, timeout=observe)
    except AssertionError:
        return
    raise AssertionError(f"{channel}: в чат пришло лишнее сообщение (было {known})")


def _put_start(bots, channel: str, chat) -> None:
    """Сотрудник открыл бота и нажал «Начать»: Telegram — `/start` из личного чата, MAX — `bot_started` (§ 1.2)."""
    chat = int(chat)
    if channel == "telegram":
        bots.put_telegram({"message": {"chat": {"id": chat, "type": "private"}, "from": {"id": chat},
                                       "text": "/start"}})
    else:
        bots.put_max({"update_type": "bot_started", "chat_id": chat, "user": {"user_id": chat}})


def _put_text(bots, channel: str, chat, text: str) -> None:
    """Сотрудник отправил боту сообщение `text` из личного чата (§ 1.2)."""
    chat = int(chat)
    if channel == "telegram":
        bots.put_telegram({"message": {"chat": {"id": chat, "type": "private"}, "from": {"id": chat}, "text": text}})
    else:
        bots.put_max({"update_type": "message_created",
                      "message": {"sender": {"user_id": chat}, "recipient": {"chat_id": chat, "chat_type": "dialog"},
                                  "body": {"text": text}}})


def _start_dialog(bots, channel: str, chat, *, timeout: float = FIRST_REPLY_WAIT) -> None:
    """«Начать» → бот просит код (`ask_code`, § 15.3)."""
    before = _count_text(bots, channel, chat, ASK_CODE)
    _put_start(bots, channel, chat)
    _expect_reply(bots, channel, chat, ASK_CODE, before, timeout=timeout)


def _block(page, channel: str):
    return page.locator(f"#notify-binding-{channel}")


def _open_block(page, channel: str, state: str):
    """Страница «Мои уведомления»: блок привязки канала в состоянии `state` (`unbound`, `bound`, `disabled`)."""
    page.goto("/me/notifications/")
    block = _block(page, channel)
    expect(block).to_have_attribute("data-state", state)
    return block


def _issue(page, channel: str, *, need_link: bool = False) -> tuple:
    """«Привязать»: возвращает `(код, адрес ссылки на бота или None)`. Код — восемь цифр. `need_link=True` — пока имя
    бота не известно (ссылки нет, есть подсказка), кнопка нажимается снова (каждый раз новый код) до `LINK_WAIT` с."""
    deadline = time.monotonic() + LINK_WAIT
    while True:
        block = _open_block(page, channel, "unbound")
        block.locator('form[data-form="bind"] button[data-action="bind"]').click()
        node = _block(page, channel).locator("[data-bind-code]")
        expect(node).to_have_count(1)
        code = node.inner_text().strip()
        assert re.fullmatch(r"\d{8}", code), "код привязки — не восемь цифр"
        link = _block(page, channel).locator("a[data-bot-link]")
        if link.count():
            return code, link.get_attribute("href")
        if not need_link:
            return code, None
        expect(_block(page, channel).locator("[data-bot-link-hint]")).to_have_count(1)
        if time.monotonic() >= deadline:
            raise AssertionError(f"{channel}: ссылка на бота не появилась за {LINK_WAIT:.0f} с (имени бота нет)")
        page.wait_for_timeout(3000)


def _complete(page, bots, channel: str, chat, code: str) -> None:
    """Сотрудник открывает бота, нажимает «Начать» и отправляет `code` в течение срока: бот просит код, затем отвечает
    «<Канал> привязан к вашей учётной записи портала», блок страницы показывает «Привязан» — сразу по соединению, без
    перезагрузки (кадр `notify.update`, § 11.3), и после перезагрузки. `page` — на `/me/notifications/` после `_issue`."""
    helpers_notify.wait_ws_open(page)
    _start_dialog(bots, channel, chat)
    before = _count_text(bots, channel, chat, BOUND[channel])
    _put_text(bots, channel, chat, code)
    _expect_reply(bots, channel, chat, BOUND[channel], before)
    live = _block(page, channel)
    expect(live).to_have_attribute("data-state", "bound", timeout=15_000)
    expect(live.locator("[data-bound]")).to_contain_text("Привязан")
    block = _open_block(page, channel, "bound")
    expect(block.locator("[data-bound]")).to_contain_text("Привязан")
    expect(block.locator('button[data-action="unbind"]')).to_have_count(1)
    expect(block.locator('button[data-action="unbind"]')).to_have_text("Отвязать")
    expect(block.locator('button[data-action="bind"]')).to_have_count(0)
    expect(block.locator("[data-bind-code]")).to_have_count(0)


def _bind(page, bots, channel: str, chat) -> str:
    """Полная привязка по сценарию 6, п. 1–2; возвращает использованный код (для проверок «старого кода»)."""
    code, _link = _issue(page, channel)
    _complete(page, bots, channel, chat, code)
    return code


def _unbind(page, channel: str) -> None:
    """«Отвязать» на странице: блок становится «не привязан» (НХ-ответ, § 13.2) и остаётся таким после перезагрузки."""
    block = _open_block(page, channel, "bound")
    block.locator('form[data-form="unbind"] button[data-action="unbind"]').click()
    expect(_block(page, channel)).to_have_attribute("data-state", "unbound")
    _open_block(page, channel, "unbound")


def _assert_clean_url(url: str, what: str, forbidden=()) -> None:
    """В адресе нет кода привязки, идентификатора чата и форм, запрещённых инвариантом «секреты-в-url». Значения в
    тексте ошибки не печатаются."""
    for value in forbidden:
        assert str(value) not in url, f"{what}: в адресе есть секрет или идентификатор"
    for pattern in URL_BAN_RES:
        assert not pattern.search(url), f"{what}: адрес нарушает инвариант «секреты-в-url»"
    assert not EIGHT_DIGITS.search(url), f"{what}: в адресе число из восьми цифр"


def _session_id(page) -> str:
    """Кука сессии контекста страницы для процесса стенда (доп. 24); значение не печатается."""
    for cookie in page.context.cookies():
        if cookie["name"] == "sessionid":
            return cookie["value"]
    raise AssertionError("у контекста сотрудника нет куки sessionid")


# Код процесса стенда (доп. 24): `django.test.Client` с сессией сотрудника открывает «Мои уведомления» без токена бота
# и печатает одну строку JSON; блок канала режется от своего корня до корня следующего блока.
_NO_BOT_ENV_CODE = (
    "import json, re; from django.test import Client; c = Client(); c.cookies['sessionid'] = @SID@; "
    "r = c.get('/me/notifications/', secure=True, HTTP_HOST=@HOST@); h = r.content.decode(); "
    "m = re.search(r'<[^>]*id=\"notify-binding-@CH@\"[^>]*>', h); "
    "e = h.find('id=\"notify-binding-', m.end()) if m else -1; "
    "b = h[m.start():(e if e > 0 else len(h))] if m else ''; "
    "s = re.search(r'data-state=\"([a-z]+)\"', m.group(0)) if m else None; "
    "print(json.dumps({'status': r.status_code, 'block': bool(m), 'state': s.group(1) if s else None, "
    "'bind_button': 'data-action=\"bind\"' in b, 'bind_form': 'data-form=\"bind\"' in b, "
    "'disabled_hook': 'data-disabled-text' in b, 'disabled_text': '@TEXT@' in b}))"
)


def _page_without_token(page, channel: str) -> dict:
    """Ветка «токен бота не задан» (доп. 24): отдельный процесс `exec -e <ИМЯ>= standtools … shell -c`, в нём
    `django.test.Client` с сессией сотрудника (кука `sessionid` из контекста браузера теста). Возвращает словарь из
    строки JSON процесса. Значения куки и ключей не печатаются."""
    if os.environ.get("E2E_STAND_CMD"):
        raise AssertionError("нужен стандартный префикс standtools")
    prefix = helpers_sd._stand_prefix()
    where = prefix.index("standtools")
    sid = _session_id(page)
    code = (_NO_BOT_ENV_CODE.replace("@SID@", repr(sid)).replace("@HOST@", repr(urlsplit(conftest.PORTAL_URL).hostname))
            .replace("@CH@", channel).replace("@TEXT@", DISABLED_TEXT))
    cmd = prefix[:where] + ["-e", f"{BOT_ENV[channel]}="] + prefix[where:] + ["shell", "-c", code]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise AssertionError("процесс стенда без токена не уложился в 120 с") from None
    if done.returncode != 0:
        raise AssertionError(f"процесс стенда без токена {channel} завершился с кодом {done.returncode}: "
                             f"{done.stderr.replace(sid, '***')[-400:]}")
    lines = [line for line in done.stdout.splitlines() if line.strip().startswith("{")]
    assert lines, "процесс стенда без токена не напечатал строку JSON"
    return json.loads(lines[-1])


def _db_counts(email: str) -> dict:
    """Строки сотрудника в таблицах среза через `manage.py shell` (`helpers.stand_shell`, служба web): подписки Web Push,
    привязки, коды привязки (все и неиспользованные). Подписки браузера из интерфейса уволенного не видны, поэтому
    чтение базы — единственный способ проверить их удаление (FR-340)."""
    code = (f"from django.apps import apps as a; m = lambda n: a.get_model('notify', n); f = {{'user__email__iexact': "
            f"{email!r}}}; print('counts', m('PushSubscription').objects.filter(**f).count(), "
            f"m('ChatBinding').objects.filter(**f).count(), m('BindCode').objects.filter(**f).count(), "
            f"m('BindCode').objects.filter(used_at__isnull=True, **f).count())")
    out = helpers.stand_shell(code).splitlines()
    found = re.search(r"counts (\d+) (\d+) (\d+) (\d+)", out[-1] if out else "")
    assert found, "stand_shell не вернула строку counts"
    push, bindings, codes, unused = (int(n) for n in found.groups())
    return {"push": push, "bindings": bindings, "codes": codes, "unused_codes": unused}


def _dismiss(page, user_id) -> None:
    """Увольняет из карточки (`[data-action="dismiss"]` → диалог → подтверждение); ждёт отметку `[data-dismissed-badge]`."""
    page.goto(f"/staff/{user_id}/")
    card = page.locator(f'[data-card][data-user-id="{user_id}"]')
    card.locator('[data-action="dismiss"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(card.locator("[data-dismissed-badge]")).to_be_visible()


# --- Тесты --------------------------------------------------------------------------------------------------

def test_e06_bind_shows_code_valid_ten_minutes_and_bot_link_without_code_only_to_the_employee(
        admin_page, employee):
    """Сценарий 6, п. 1: канал Telegram включён администратором, сотрудник нажимает «Привязать» — видит код из восьми
    цифр со сроком «действует 10 минут» и ссылку на бота общества без кода в адресе; код и ссылка показаны только ему:
    после перезагрузки их нет, у другого сотрудника и в журнале кода нет (FR-325)."""
    page = admin_page
    member, other = employee(), employee()
    with helpers_notify.channels_on(page, "telegram"):
        # п. 1: «Привязать» → код, срок и ссылка на бота (имени бота может ещё не быть — ждём, пока появится)
        code, href = _issue(member.page, "telegram", need_link=True)
        block = _block(member.page, "telegram")
        expect(block).to_have_attribute("data-state", "unbound")
        expect(block.locator("[data-bind-expires]")).to_contain_text(EXPIRES_TEXT)
        assert href == f"https://{BOT_HOST['telegram']}/{BOT_NAME}", "ссылка на бота — не t.me/<имя бота общества>"
        assert code not in href and "?" not in href and "#" not in href
        _assert_clean_url(href, "ссылка на бота", [code])
        # п. 1: «только ему» — после перезагрузки страницы код и срок не показываются, кнопка «Привязать» прежняя
        again = _open_block(member.page, "telegram", "unbound")
        expect(again.locator("[data-bind-code]")).to_have_count(0)
        expect(again.locator("[data-bind-expires]")).to_have_count(0)
        expect(again.locator('button[data-action="bind"]')).to_have_count(1)
        assert code not in member.page.content(), "повторное открытие страницы показало код"
        # п. 1: у другого сотрудника на странице кода нет, его блок не выдан как привязанный
        foreign = _open_block(other.page, "telegram", "unbound")
        expect(foreign.locator("[data-bind-code]")).to_have_count(0)
        assert code not in other.page.content()
        # п. 1: в журнале портала кода нет
        assert code not in helpers.audit_text(page), "код привязки попал в журнал"


def test_e06_valid_code_sent_to_bot_binds_channel_bot_confirms_and_page_shows_bound(admin_page, employee):
    """Сценарий 6, п. 2: сотрудник открыл бота, нажал «Начать» и отправил верный код в течение 10 минут — бот просит код,
    затем отвечает «Telegram привязан к вашей учётной записи портала», на странице видно «Привязан» (сразу по
    соединению и после перезагрузки), кнопки «Привязать» нет, код не показан (FR-325)."""
    page = admin_page
    member = employee()
    bots = helpers_notify.fakebots()
    chat = _chat_id()
    with helpers_notify.channels_on(page, "telegram"):
        # п. 2: «Привязать» → код; «Начать» → бот просит код; код сообщением → привязка и подтверждение
        code, _link = _issue(member.page, "telegram")
        _complete(member.page, bots, "telegram", chat, code)
        texts = [m["text"] for m in helpers_notify.sent_to(bots, "telegram", chat)]
        # п. 2: в чат пришли ровно просьба кода и подтверждение, текст подтверждения — § 15.3 целиком
        assert texts == [ASK_CODE, BOUND["telegram"]], texts
        assert code not in "".join(texts), "бот повторил код в сообщении"


def test_e06_expired_or_used_code_refused_by_bot_with_hint_to_get_new_code_and_no_binding(admin_page, employee):
    """Сценарий 6, п. 3: код просрочен или уже использован — бот отвечает отказом с подсказкой получить новый код
    (§ 15.3), привязки нет (FR-325, FR-339). Просрочка — `e2e_notify_tick --age-codes 11`; использованный код шлётся
    из нового чата после отвязки."""
    page = admin_page
    member = employee()
    bots = helpers_notify.fakebots()
    chat_expired, chat_first, chat_second = _chat_id(), _chat_id(), _chat_id()
    with helpers_notify.channels_on(page, "telegram"):
        # п. 3: просроченный код — выдан, диалог начат, срок вышел (сдвиг на 11 минут), код отправлен
        code, _link = _issue(member.page, "telegram")
        _start_dialog(bots, "telegram", chat_expired)
        helpers_notify.tick(age_codes=11)
        before = _count_text(bots, "telegram", chat_expired, CODE_INVALID)
        _put_text(bots, "telegram", chat_expired, code)
        _expect_reply(bots, "telegram", chat_expired, CODE_INVALID, before)
        texts = [m["text"] for m in helpers_notify.sent_to(bots, "telegram", chat_expired)]
        assert texts == [ASK_CODE, CODE_INVALID], texts
        _open_block(member.page, "telegram", "unbound")  # п. 3: привязки нет
        # п. 3: использованный код — привязка первым чатом, отвязка, тот же код из второго чата
        used = _bind(member.page, bots, "telegram", chat_first)
        _unbind(member.page, "telegram")
        _start_dialog(bots, "telegram", chat_second)
        before = _count_text(bots, "telegram", chat_second, CODE_INVALID)
        _put_text(bots, "telegram", chat_second, used)
        _expect_reply(bots, "telegram", chat_second, CODE_INVALID, before)
        texts = [m["text"] for m in helpers_notify.sent_to(bots, "telegram", chat_second)]
        assert texts == [ASK_CODE, CODE_INVALID], texts
        _open_block(member.page, "telegram", "unbound")  # п. 3: привязки нет и после использованного кода


def test_e06_bound_telegram_gets_one_message_new_ticket_in_your_queue_with_notifications_link_and_no_number_subject_name_address(
        admin_page, employee, new_context):
    """Сценарий 6, п. 4: Telegram привязан и включён для вида, тихих часов нет — наступает событие (новая заявка в очереди
    сотрудника), в Telegram приходит одно сообщение «Новая заявка в вашей очереди» со ссылкой на страницу уведомлений, без
    номера, темы, ФИО и адресов (FR-317, FR-328)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, queue_name = _queue(page)
    _members(page, queue_id, [member], tag)
    bots = helpers_notify.fakebots()
    chat = _chat_id()
    with helpers_notify.channels_on(page, "telegram"):
        # дано: Telegram привязан кодом, ячейка Telegram вида включена, тихих часов нет
        helpers_notify.bind_channel(member.page, bots, "telegram", chat)
        _prefs(member.page, ["telegram"])
        known = len(helpers_notify.sent_to(bots, "telegram", chat))
        with _default_queue(page, old_id, queue_id):
            tab = helpers_notify.open_watcher(new_context, member)
            before = helpers_notify.bell_count(tab)
            # когда: наступает событие
            word, subject, requester = _new_ticket()
            helpers_notify.wait_bell_count(tab, before + 1, timeout_ms=15_000)
            number = helpers_sd.ticket_number_by_subject(page, word)
        # п. 4: в Telegram пришло ровно одно сообщение уведомления, текст — внешний текст вида (§ 15.2)
        found = helpers_notify.wait_sent(bots, "telegram", chat_id=chat, text_has=EXTERNAL)
        assert len(found) == 1, f"сообщений «{EXTERNAL}» в свой чат: {len(found)}"
        message = found[0]
        assert message["text"] == EXTERNAL
        # п. 4: ни номера, ни темы, ни очереди, ни ФИО, ни адресов нигде в сообщении (ни в тексте, ни в кнопке)
        dump = json.dumps(message, ensure_ascii=False)
        for forbidden in (word, "принтер", f"#{number}", f"/tickets/{number}", queue_name, requester, member.email,
                          member.full_name, tag):
            assert forbidden not in dump, "во внешнем сообщении есть внутренние данные заявки"
        # п. 4: ссылка — страница уведомлений портала (кнопка «Открыть уведомления»)
        url = _button_url("telegram", message)
        assert urlsplit(url).path == "/notifications/" and not urlsplit(url).query, "ссылка — не /notifications/"
        # п. 4: после прихода сообщения других сообщений уведомления нет (одно событие — одно сообщение)
        _no_new_messages(bots, "telegram", chat, known + 1)


def test_e06_unbind_stops_messages_and_bot_ignores_old_codes(admin_page, employee):
    """Сценарий 6, п. 5: сотрудник нажал «Отвязать» — сообщения в Telegram больше не приходят (положительный контроль:
    привязанный коллега по очереди то же событие получает), бот старый код не принимает: отвечает отказом, привязка не
    восстановилась (FR-326)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    leaver, keeper = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, _queue_name = _queue(page)
    _members(page, queue_id, [leaver, keeper], tag)
    bots = helpers_notify.fakebots()
    chat_leaver, chat_keeper = _chat_id(), _chat_id()
    with helpers_notify.channels_on(page, "telegram"):
        # дано: оба привязаны; у обоих ячейка Telegram включена и нет тихих часов
        old_code = _bind(leaver.page, bots, "telegram", chat_leaver)
        helpers_notify.bind_channel(keeper.page, bots, "telegram", chat_keeper)
        _prefs(leaver.page, ["telegram"])
        _prefs(keeper.page, ["telegram"])
        with _default_queue(page, old_id, queue_id):
            # до отвязки событие приходит обоим
            _new_ticket()
            helpers_notify.wait_sent(bots, "telegram", chat_id=chat_leaver, text_has=EXTERNAL)
            helpers_notify.wait_sent(bots, "telegram", chat_id=chat_keeper, text_has=EXTERNAL)
            # когда: сотрудник нажимает «Отвязать»
            _unbind(leaver.page, "telegram")
            known = len(helpers_notify.sent_to(bots, "telegram", chat_leaver))
            word, _subject, _requester = _new_ticket()
            # п. 5: контроль — привязанный коллега получил и второе событие; на портале у отвязавшегося оно тоже есть
            helpers_notify.wait_sent(bots, "telegram", chat_id=chat_keeper, count=2, text_has=EXTERNAL)
            leaver.page.goto("/notifications/")
            expect(leaver.page.locator("ul[data-notifications] li[data-notification]").filter(has_text=word)
                   ).to_have_count(1)
        # п. 5: в отвязанный чат второе событие не пришло
        _no_new_messages(bots, "telegram", chat_leaver, known)
        # п. 5: старый (использованный) код бот не принимает: отказ с подсказкой, привязки нет
        before = _count_text(bots, "telegram", chat_leaver, CODE_INVALID)
        _put_text(bots, "telegram", chat_leaver, old_code)
        _expect_reply(bots, "telegram", chat_leaver, CODE_INVALID, before)
        assert _count_text(bots, "telegram", chat_leaver, BOUND["telegram"]) == 1, "бот повторно привязал чат"
        _open_block(leaver.page, "telegram", "unbound")


def test_e06_channel_off_by_admin_or_token_missing_hides_bind_button_and_shows_disabled_text(admin_page, employee):
    """Сценарий 6, п. 6: канал Telegram или MAX выключен администратором или токен бота не задан в окружении — в «Мои
    уведомления» кнопки «Привязать» нет, показано «Канал отключён администратором» (FR-336). Ветка «выключен» — в
    браузере, с контролем (включённый канал показывает кнопку); ветка «токен не задан» — отдельным процессом стенда
    (доп. 24)."""
    page = admin_page
    member = employee()
    # п. 6: канал выключен администратором — обе ветки каналов в браузере
    with helpers_notify.channels_off(page, "telegram", "max"):
        member.page.goto("/me/notifications/")
        for channel in helpers_notify.BOT_CHANNELS:
            block = _block(member.page, channel)
            expect(block).to_have_attribute("data-state", "disabled")
            expect(block.locator("[data-disabled-text]")).to_contain_text(DISABLED_TEXT)
            expect(block.locator('button[data-action="bind"]')).to_have_count(0)
            expect(block.locator('form[data-form="bind"]')).to_have_count(0)
            expect(block.locator('button[data-action="unbind"]')).to_have_count(0)
    # контроль: включённый администратором канал с токеном показывает кнопку «Привязать»
    with helpers_notify.channels_on(page, "telegram", "max"):
        member.page.goto("/me/notifications/")
        for channel in helpers_notify.BOT_CHANNELS:
            block = _block(member.page, channel)
            expect(block).to_have_attribute("data-state", "unbound")
            expect(block.locator('form[data-form="bind"] button[data-action="bind"]')).to_have_count(1)
            expect(block.locator('form[data-form="bind"] button[data-action="bind"]')).to_have_text("Привязать")
            expect(block.locator("[data-disabled-text]")).to_have_count(0)
        # п. 6: канал включён администратором, токен не задан в окружении процесса — то же «отключён»
        for channel in helpers_notify.BOT_CHANNELS:
            seen = _page_without_token(member.page, channel)
            assert seen["status"] == 200 and seen["block"], f"{channel}: страница без токена не отдана: {seen}"
            assert seen["state"] == "disabled", f"{channel}: без токена состояние {seen['state']!r}, нужно 'disabled'"
            assert seen["disabled_hook"] and seen["disabled_text"], f"{channel}: нет текста «{DISABLED_TEXT}»"
            assert not seen["bind_button"] and not seen["bind_form"], f"{channel}: без токена видна кнопка «Привязать»"


def test_e06_max_channel_binds_and_works_same_way_as_telegram(admin_page, employee, new_context):
    """Сценарий 6, п. 7: тот же сценарий для MAX — код и ссылка на бота (`max.ru`), событие `bot_started`, код сообщением,
    ответ «MAX привязан к вашей учётной записи портала», «Привязан» на странице, затем сообщение «Новая заявка в вашей
    очереди» со ссылкой на уведомления и отвязка (FR-325)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, queue_name = _queue(page)
    _members(page, queue_id, [member], tag)
    bots = helpers_notify.fakebots()
    chat = _chat_id()
    with helpers_notify.channels_on(page, "max"):
        # п. 7: код (восемь цифр, срок) и ссылка на бота MAX без кода в адресе
        code, href = _issue(member.page, "max", need_link=True)
        expect(_block(member.page, "max").locator("[data-bind-expires]")).to_contain_text(EXPIRES_TEXT)
        assert href == f"https://{BOT_HOST['max']}/{BOT_NAME}", "ссылка на бота — не max.ru/<имя бота общества>"
        _assert_clean_url(href, "ссылка на бота MAX", [code])
        # п. 7: «Начать» (`bot_started`) → просьба кода; код сообщением → привязка, подтверждение, «Привязан»
        _complete(member.page, bots, "max", chat, code)
        texts = [m["text"] for m in helpers_notify.sent_to(bots, "max", chat)]
        assert texts == [ASK_CODE, BOUND["max"]], texts
        # п. 7: уведомление приходит в MAX как «событие и ссылка» (п. 4 для MAX)
        _prefs(member.page, ["max"])
        with _default_queue(page, old_id, queue_id):
            tab = helpers_notify.open_watcher(new_context, member)
            before = helpers_notify.bell_count(tab)
            word, subject, requester = _new_ticket()
            helpers_notify.wait_bell_count(tab, before + 1, timeout_ms=15_000)
            number = helpers_sd.ticket_number_by_subject(page, word)
        found = helpers_notify.wait_sent(bots, "max", chat_id=chat, text_has=EXTERNAL)
        assert len(found) == 1 and found[0]["text"] == EXTERNAL
        dump = json.dumps(found[0], ensure_ascii=False)
        for forbidden in (word, "принтер", f"#{number}", queue_name, requester, member.email, member.full_name):
            assert forbidden not in dump, "во внешнем сообщении MAX есть внутренние данные заявки"
        assert urlsplit(_button_url("max", found[0])).path == "/notifications/"
        # п. 7: отвязка MAX работает так же
        _unbind(member.page, "max")


def test_e06_same_chat_for_second_account_refused_with_explanation(admin_page, employee):
    """Сценарий 6, п. 8: один и тот же чат нельзя привязать к двум учётным записям — второй код, отправленный из того же
    чата, отклонён с объяснением «Этот чат уже привязан к другой учётной записи портала»; у второго сотрудника привязки
    нет, у первого она осталась (FR-325)."""
    page = admin_page
    first, second = employee(), employee()
    bots = helpers_notify.fakebots()
    chat = _chat_id()
    with helpers_notify.channels_on(page, "telegram"):
        # дано: чат привязан к первому сотруднику
        helpers_notify.bind_channel(first.page, bots, "telegram", chat)
        # когда: второй сотрудник получает свой код и отправляет его из того же чата
        code, _link = _issue(second.page, "telegram")
        _start_dialog(bots, "telegram", chat)
        before = _count_text(bots, "telegram", chat, CHAT_TAKEN)
        _put_text(bots, "telegram", chat, code)
        # п. 8: отказ с объяснением (§ 15.3), подтверждения привязки не было второй раз
        _expect_reply(bots, "telegram", chat, CHAT_TAKEN, before)
        assert _count_text(bots, "telegram", chat, BOUND["telegram"]) == 1, "бот подтвердил вторую привязку"
        # п. 8: у второго привязки нет, у первого осталась
        _open_block(second.page, "telegram", "unbound")
        _open_block(first.page, "telegram", "bound")


@helpers_notify.webpush_only
def test_e06_dismissal_removes_push_subscriptions_bindings_and_unused_codes_and_no_messages_follow(
        admin_page, employee, webpush_context):
    """Сценарий 6, п. 9: у сотрудника есть подписка Web Push, привязки Telegram и MAX и неиспользованный код привязки — его
    увольняют: подписки, привязки и коды удалены (строки базы; освободившиеся чаты привязываются другим сотрудником
    без отказа «чат уже привязан»), сообщения в эти каналы больше не уходят (положительный контроль — привязанный
    коллега по очереди получает то же событие) (FR-340). Главное доказательство — база (строки подписок, привязок, кодов) и успешная повторная привязка освободившихся
    чатов другим сотрудником; проверки «сообщений в бывшие чаты нет» слабее и лишь дополняют их. Метка Web Push: подписка устройства — только Chromium и Edge,
    постоянный профиль (доп. 23)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    leaver, keeper, taker = (_staff(employee, tag, i) for i in (1, 2, 3))
    queue_id, _queue_name = _queue(page)
    _members(page, queue_id, [leaver, keeper], tag)
    bots = helpers_notify.fakebots()
    chat_tg, chat_max, chat_keeper = _chat_id(), _chat_id(), _chat_id()
    with helpers_notify.channels_on(page, "webpush", "telegram", "max"):
        # дано: подписка устройства (постоянный профиль, разрешение выдано, сессия сотрудника перенесена)
        context = webpush_context()
        tab = helpers_notify.open_tab(context, leaver, grant=True)
        helpers_notify.enable_push_on_device(tab)
        # дано: привязки Telegram и MAX, ячейки включены; коллега по очереди привязан к Telegram (контроль)
        _bind(leaver.page, bots, "telegram", chat_tg)
        _bind(leaver.page, bots, "max", chat_max)
        helpers_notify.bind_channel(keeper.page, bots, "telegram", chat_keeper)
        _prefs(keeper.page, ["telegram"])
        # дано: неиспользованный код привязки (канал привязан, но новый код портал выдаёт: new_code не проверяет привязку)
        issued = helpers_org.direct_post(leaver.page, "/me/notifications/bind/telegram/")
        assert issued.status == 200, f"новый код не выдан: статус {issued.status}"
        before = _db_counts(leaver.email)
        assert before["push"] >= 1 and before["bindings"] == 2 and before["unused_codes"] >= 1, \
            f"подготовка не создала подписку, две привязки и неиспользованный код: {before}"
        # когда: сотрудника увольняют
        _dismiss(page, leaver.id)
        # п. 9: подписки, привязки и коды удалены
        after = _db_counts(leaver.email)
        assert after == {"push": 0, "bindings": 0, "codes": 0, "unused_codes": 0}, after
        # п. 9: чаты уволенного свободны — другой сотрудник привязывает тот же чат Telegram без отказа «чат уже привязан»
        helpers_notify.bind_channel(taker.page, bots, "telegram", chat_tg)
        known_tg = len(helpers_notify.sent_to(bots, "telegram", chat_tg))
        known_max = len(helpers_notify.sent_to(bots, "max", chat_max))
        assert _count_text(bots, "telegram", chat_tg, CHAT_TAKEN) == 0
        # п. 9: событие в очереди — сообщений в бывшие чаты уволенного не приходит, у коллеги (контроль) оно есть
        with _default_queue(page, old_id, queue_id):
            _new_ticket()
        helpers_notify.wait_sent(bots, "telegram", chat_id=chat_keeper, text_has=EXTERNAL)
        _no_new_messages(bots, "telegram", chat_tg, known_tg)
        _no_new_messages(bots, "max", chat_max, known_max)


def test_e06_bot_link_and_notification_links_contain_no_binding_code_or_secrets(admin_page, employee, new_context):
    """Сценарий 6, п. 10: ссылка на бота, показанная на странице, и адреса ссылок уведомлений (страница «Уведомления»,
    панель колокольчика, кнопки сообщений Telegram и MAX) проверяются — в них нет кода привязки, идентификатора чата и
    других секретов (инвариант «секреты-в-url») (FR-325, FR-339)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _queue_name = _queue(page)
    _members(page, queue_id, [member], tag)
    bots = helpers_notify.fakebots()
    chats = {"telegram": _chat_id(), "max": _chat_id()}
    codes = {}
    with helpers_notify.channels_on(page, "telegram", "max"):
        for channel, chat in chats.items():
            # п. 10: ссылка на бота — только имя бота, без кода и секретов; все ссылки страницы с выданным кодом — тоже
            code, href = _issue(member.page, channel, need_link=True)
            codes[channel] = code
            assert href == f"https://{BOT_HOST[channel]}/{BOT_NAME}", \
                f"{channel}: ссылка на бота — не https://{BOT_HOST[channel]}/<имя бота общества>"
            assert not urlsplit(href).query and not urlsplit(href).fragment
            _assert_clean_url(href, f"ссылка на бота {channel}", [code, chat])
            hrefs = member.page.eval_on_selector_all("a[href]", "nodes => nodes.map(n => n.getAttribute('href'))")
            for item in hrefs:
                _assert_clean_url(item, "ссылка страницы «Мои уведомления»", [code])
            _assert_clean_url(member.page.url, "адрес страницы «Мои уведомления»", [code])
            _complete(member.page, bots, channel, chat, code)
        _prefs(member.page, ["telegram", "max"])
        # когда: приходит уведомление — адреса ссылок на портале и в сообщениях бота
        with _default_queue(page, old_id, queue_id):
            tab = helpers_notify.open_watcher(new_context, member)
            before = helpers_notify.bell_count(tab)
            _new_ticket()
            helpers_notify.wait_bell_count(tab, before + 1, timeout_ms=15_000)
        forbidden = list(codes.values()) + list(chats.values())
        tab.goto("/notifications/")
        rows = tab.locator("ul[data-notifications] li[data-notification] a[data-open]")
        assert rows.count() >= 1, "в списке уведомлений нет ссылок"
        for item in rows.evaluate_all("nodes => nodes.map(n => n.getAttribute('href'))"):
            _assert_clean_url(item, "ссылка уведомления в списке", forbidden)
        tab.locator("button[data-bell-toggle]").click()
        expect(tab.locator("[data-bell-panel] [data-bell-list]")).to_be_visible()
        for item in tab.eval_on_selector_all("[data-bell-panel] a[href]", "nodes => nodes.map(n => n.getAttribute('href'))"):
            _assert_clean_url(item, "ссылка панели колокольчика", forbidden)
        for channel, chat in chats.items():
            found = helpers_notify.wait_sent(bots, channel, chat_id=chat, text_has=EXTERNAL)
            url = _button_url(channel, found[-1])
            _assert_clean_url(url, f"ссылка в сообщении {channel}", forbidden)
            assert urlsplit(url).path == "/notifications/"
