"""T-4150: сценарий 11 — сбои каналов: портал работает, на портале всё видно (приоритет P2)
(FR-332, FR-333, FR-340, FR-341, FR-344, NFR-304, NFR-306).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-004.md § 1.2, § 6.9, § 6.13, § 9.2, § 15.1, § 15.2, доп. 23, 26):
- каналы включает администратор на время теста (`helpers_notify.channels_on`, возврат в `finally`); очередь по умолчанию
  на время теста — своя (возврат в `finally`); `fakebots` одна на круг и без сброса, у каждой роли свой `chat_id`;
- у получателя режим «Без тихих часов» (иначе вне рабочего времени доставка стала бы `held`, а не `waiting`);
- сбой бота заказывается `fakebots.fail(...)` **после** привязки (ответы бота «Отправьте код…» и «… привязан …» тоже идут
  методом `sendMessage` и «съели» бы заказанные сбои), число сбоев `count` равно числу попыток теста, чтобы заказ не
  остался на следующие тесты круга (сброса `fakebots` посреди круга нет);
- «запись «Доставка» уведомления» (`Delivery`: состояние, причина, число попыток, срок, `log`) в интерфейсе контракта не
  показана, поэтому читается `helpers.stand_shell` (каждый вызов назван в отчёте); письма — журнал `/settings/mail-log/`;
- повторы: срок следующей попытки — пауза 1, 5, 15 минут, 1 час, затем 3 часа (§ 6.9, `RETRY_DELAYS`); минуты приёмка не
  ждёт, а сдвигает срок `helpers_notify.tick(shift=N)` с запасом над паузой; сутки — `tick(age_days=1)`.
"""
import contextlib
import json
import re
import secrets
import time
from datetime import datetime

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers, helpers_notify, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_servicedesk import build_mail

NEW_IN_QUEUE = "servicedesk.new_in_queue"
EXTERNAL = "Новая заявка в вашей очереди"  # внешний текст вида (§ 15.2, FR-317)
UNBOUND_TEXT = "Telegram отвязан: бот недоступен"  # § 15.1, FR-316
UNBOUND_ACTION = "notify.channel_unbound"
REMOVED_ACTION = "notify.push_removed"
NOTIFY_ACTIONS = ("notify.settings_changed", "notify.user_settings_changed", "notify.channel_bound",
                  "notify.channel_unbound", "notify.push_subscribed", "notify.push_removed")  # § 9.2
_RQ_CONN = "import redis; from django.conf import settings; r = redis.Redis.from_url(settings.VALKEY_URL); "
DELIVERY_WAIT = 90.0  # с: запас над нормой NFR-302 (60 с) для внешних каналов


# --- Общие помощники файла ----------------------------------------------------------------------------

def _word() -> str:
    return f"t{secrets.token_hex(3)}"


def _tag() -> str:
    return "Очередь" + secrets.token_hex(3)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _staff(employee, tag: str, index: int):
    return employee(full_name=f"{tag}{index} Петр Петрович")


def _chat_id() -> int:
    """Уникальный номер чата `fakebots` для роли теста."""
    return secrets.randbelow(900_000_000) + 100_000_000


def _queue(page, prefix: str = "Поддержка") -> tuple:
    name = helpers_org.unique_name(prefix)
    unit_id = helpers_org.create_unit(page, name, kind="department")
    helpers_sd.mark_queue(page, unit_id)
    return unit_id, name


def _members(page, queue_id, accounts, tag: str) -> None:
    page.goto(f"/structure/{queue_id}/")
    mode = "concurrent" if page.locator("#unit-card select[name=mode]").count() else None
    note = helpers_org.add_members(page, queue_id, [a.id for a in accounts], q=tag, mode=mode)
    assert "уже участник" not in note, note
    helpers_org.open_structure(page, queue_id)
    for account in accounts:
        expect(helpers_org.member_row(page, account.id)).to_have_count(1)


@contextlib.contextmanager
def _default_queue(page, old_id, queue_id):
    """Очередь по умолчанию на время теста — своя; прежняя возвращается в `finally`."""
    helpers_sd.set_default_queue(page, queue_id)
    try:
        yield
    finally:
        helpers_sd.set_default_queue(page, old_id)


def _prefs(page, channels) -> None:
    """«Мои уведомления» сотрудника: у вида «Новая заявка в моей очереди» ячейки `channels` включены, режим «Без тихих
    часов»; значение сохранено (§ 13.2, § 14.3). Ячейки telegram/max доступны только после привязки."""
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
    expect(page.locator("[role=status]").filter(has_text="Настройки уведомлений сохранены.")).to_be_visible()
    for channel in channels:
        cell = page.locator(f'tr[data-notify-kind="{NEW_IN_QUEUE}"] td[data-channel="{channel}"] '
                            f'input[type=checkbox][name="cell"][value="{NEW_IN_QUEUE}:{channel}"]')
        expect(cell).to_be_checked()


def _new_ticket() -> tuple:
    """Письмо заявителя в ящик заявок и сразу разбор: заявка в очереди по умолчанию. Возвращает `(слово, тема)`."""
    word = _word()
    subject = f"Не работает принтер {word}"
    helpers_sd.deliver(build_mail(from_addr=helpers_sd.requester_email(), to=[MAILBOX], subject=subject,
                                  text=f"Нужна помощь {word}", message_id=f"<{secrets.token_hex(8)}@client.test>"))
    return word, subject


def _rows(page, text: str):
    """Строки списка `/notifications/`, в тексте которых есть `text`; список только читается."""
    page.goto("/notifications/")
    expect(page.locator("[data-notify-list]")).to_be_visible()
    return page.locator("ul[data-notifications] li[data-notification]").filter(has_text=text)


def _all_rows(page) -> int:
    page.goto("/notifications/")
    expect(page.locator("[data-notify-list]")).to_be_visible()
    return page.locator("ul[data-notifications] li[data-notification]").count()


def _delivery(email: str, channel: str, word: str):
    """Запись «Доставка» уведомления со словом темы (чтение базы, `helpers.stand_shell`): состояние, причина, число
    попыток, срок, записи `log` (время, итог, код ответа, причина; адресов и чатов в `log` нет, § 2.2)."""
    code = ("import json; from django.apps import apps; "
            "D = apps.get_model('notify.Delivery'); "
            f"d = D.objects.filter(channel='{channel}', notification__user__email__iexact='{email}', "
            f"notification__text__contains='{word}').order_by('-id').first(); "
            "out = None if d is None else {'id': d.pk, 'state': d.state, 'reason': d.reason, 'attempts': d.attempts, "
            "'due': d.due_at.isoformat() if d.due_at else None, "
            "'log': [{k: e.get(k) for k in ('at', 'outcome', 'code', 'reason')} for e in d.log]}; "
            "print('delivery ' + json.dumps(out))")
    lines = [ln for ln in helpers.stand_shell(code).splitlines() if ln.startswith("delivery ")]
    assert lines, "stand_shell не вернула строку delivery"
    return json.loads(lines[-1][len("delivery "):])


def _wait_delivery(page, email: str, channel: str, word: str, predicate, what: str, *, timeout: float = DELIVERY_WAIT):
    """Ждёт (до `timeout` с), пока запись «Доставка» удовлетворит `predicate`; возвращает её."""
    deadline = time.monotonic() + timeout
    while True:
        found = _delivery(email, channel, word)
        if found is not None and predicate(found):
            return found
        if time.monotonic() >= deadline:
            raise AssertionError(f"за {timeout:.0f} с доставка {channel} не достигла состояния «{what}»: {found}")
        page.wait_for_timeout(1000)


def _pause_seconds(delivery: dict) -> float:
    """Пауза до следующей попытки: срок `due_at` минус время последней записи `log`."""
    return (datetime.fromisoformat(delivery["due"]) - datetime.fromisoformat(delivery["log"][-1]["at"])).total_seconds()


def _bound(page, bots, channel: str, chat, channels=("telegram",)) -> None:
    helpers_notify.bind_channel(page, bots, channel, chat)
    _prefs(page, list(channels))


def _pause_jobs() -> None:
    """Пауза RQ стенда (CONTRACT-004, доп. 26): обработчики не берут новые задания, ttl 120 с снимет паузу сам."""
    helpers.stand_shell(_RQ_CONN + "from rq import suspension; suspension.suspend(r, ttl=120)")


def _resume_jobs() -> None:
    """Снимает паузу RQ (доп. 26); повторный вызов безвреден."""
    helpers.stand_shell(_RQ_CONN + "from rq import suspension; suspension.resume(r)")


def _send_jobs(delivery_id: int) -> int:
    """Сколько заданий `send_delivery` **этой доставки** (`job.args == (delivery_id,)`, § 7.2, доп. 28 (в)) стоит в очереди
    `notify` или выполняется (чтение Valkey, `helpers.stand_shell`)."""
    code = ("import django_rq; from rq.registry import StartedJobRegistry; q = django_rq.get_queue('notify'); "
            "jobs = list(q.jobs) + [q.fetch_job(i) for i in StartedJobRegistry(queue=q).get_job_ids()]; "
            "print('sendjobs', sum(1 for j in jobs if j is not None and j.func_name.endswith('send_delivery') "
            f"and tuple(j.args) == ({int(delivery_id)},)))")
    lines = [ln for ln in helpers.stand_shell(code).splitlines() if ln.startswith("sendjobs ")]
    assert lines, "stand_shell не вернула строку sendjobs"
    return int(lines[-1].split()[1])


@contextlib.contextmanager
def _clear_fails_at_exit(bots, channel: str):
    """Снимает остаток заказанных сбоев канала при выходе из блока, в том числе при падении теста (доп. 28 (а))."""
    try:
        yield
    finally:
        bots.clear_fails(channel)


def _delivery_count(email: str, text: str) -> int:
    """Число записей «Доставка» уведомлений сотрудника с текстом `text` (чтение базы, `helpers.stand_shell`)."""
    out = helpers.stand_shell("from django.apps import apps; "
                              "print('deliveries', apps.get_model('notify.Delivery').objects.filter("
                              f"notification__text={text!r}, notification__user__email__iexact={email!r}).count())")
    lines = [ln for ln in out.splitlines() if ln.startswith("deliveries ")]
    assert lines, "stand_shell не вернула строку deliveries"
    return int(lines[-1].split()[1])


def _audit_rows(page, action: str, user_id) -> list:
    """Строки `/audit/?action=…` об объекте «сотрудник № user_id»: словари `{actor, object, before, after, text}`
    (ячейки по порядку: время, кто, событие, объект, было, стало, адрес)."""
    page.goto(f"/audit/?action={action}")
    out = []
    for row in page.locator(f'tr[data-event-id][data-action="{action}"]').all():
        cells = [_norm(c).lower() for c in row.locator("td").all_inner_texts()]
        if re.search(rf"№\s*{user_id}(?!\d)", cells[3]):
            out.append({"actor": cells[1], "object": cells[3], "before": cells[4], "after": cells[5],
                        "text": " ".join(cells)})
    return out


def _is_online(user_id) -> bool:
    out = helpers.stand_shell("from apps.notify.services import live; "
                              f"print('online', live.is_online({int(user_id)}))")
    lines = [ln for ln in out.splitlines() if ln.startswith("online ")]
    assert lines, "stand_shell не вернула строку online"
    return lines[-1].split()[1] == "True"


def _push_count(email: str) -> int:
    out = helpers.stand_shell("from django.apps import apps; "
                              "print('push', apps.get_model('notify.PushSubscription').objects"
                              f".filter(user__email__iexact='{email}').count())")
    lines = [ln for ln in out.splitlines() if ln.startswith("push ")]
    assert lines, "stand_shell не вернула строку push"
    return int(lines[-1].split()[1])


def _db_counts(email: str) -> dict:
    """Строки базы сотрудника: подписки Web Push, привязки, все и неиспользованные коды (`helpers.stand_shell`)."""
    out = helpers.stand_shell(
        "from django.apps import apps; m = apps.get_model; "
        f"f = {{'user__email__iexact': '{email}'}}; "
        "print('counts', m('notify.PushSubscription').objects.filter(**f).count(), "
        "m('notify.ChatBinding').objects.filter(**f).count(), m('notify.BindCode').objects.filter(**f).count(), "
        "m('notify.BindCode').objects.filter(used_at__isnull=True, **f).count())")
    lines = [ln for ln in out.splitlines() if ln.startswith("counts ")]
    assert lines, "stand_shell не вернула строку counts"
    push, bindings, codes, unused = (int(n) for n in lines[-1].split()[1:])
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


def _push_not_gone(email: str, word: str) -> None:
    """Подписка не удалена за предел ожидания: правило решения 26 по записи «Доставка» (`log`: `code`, `outcome`).
    404/410 и подписка осталась — ошибка портала; 2xx — наблюдение (`xfail`); иное — ошибка с записанным."""
    record = _delivery(email, "webpush", word)
    codes = [e.get("code") for e in (record or {}).get("log", [])]
    state = None if record is None else (record["state"], record["reason"], codes)
    if any(c in (404, 410) for c in codes):
        raise AssertionError(f"push-сервис ответил 404/410, но подписка не удалена за {DELIVERY_WAIT:.0f} с: {state}")
    if any(isinstance(c, int) and 200 <= c < 300 for c in codes):
        pytest.xfail(f"наблюдение по решению 26: push-сервис не ответил 404/410 за {DELIVERY_WAIT:.0f} с (принял push)")
    raise AssertionError(f"подписка не удалена за {DELIVERY_WAIT:.0f} с; запись «Доставка»: {state}")


# --- Тесты --------------------------------------------------------------------------------------------------

def test_e11_telegram_unavailable_portal_notification_at_once_sending_retried_with_growing_pause_portal_not_slowed(
        admin_page, employee, new_context):
    """Сценарий 11, п. 1: Telegram недоступен (ответ 500 на `sendMessage`) — когда наступает событие, уведомление на
    колокольчике появилось за 2 с (портал не замедлен), запись «Доставка» осталась `waiting` с каждой неудачной попыткой
    в `log`, а пауза до следующей попытки растёт (около 1, затем около 5 минут); когда Telegram отвечает снова, то же
    сообщение приходит один раз (FR-333, NFR-304)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [member], tag)
    bots = helpers_notify.fakebots()
    chat = _chat_id()
    with helpers_notify.channels_on(page, "telegram"), _clear_fails_at_exit(bots, "telegram"):
        _bound(member.page, bots, "telegram", chat)
        with _default_queue(page, old_id, queue_id):
            tab = helpers_notify.open_watcher(new_context, member)
            base = helpers_notify.bell_count(tab)
            # дано: Telegram недоступен — две ближайшие отправки получат 500
            bots.fail("telegram", 500, method="sendMessage", count=2)
            # когда: наступает событие
            word, _subject = _new_ticket()
            # п. 1: уведомление на портале появилось сразу (за 2 с), портал не замедлен
            helpers_notify.wait_bell_count(tab, base + 1, timeout_ms=2_000)
            expect(_rows(tab, word)).to_have_count(1)
            # п. 1: первая отправка не удалась — запись «Доставка» ждёт повтора, в `log` одна неудача с кодом 500
            first = _wait_delivery(tab, member.email, "telegram", word,
                                   lambda d: d["attempts"] >= 1, "одна попытка")
            assert first["state"] == "waiting" and first["attempts"] == 1, first
            assert len(first["log"]) == 1 and first["log"][0]["outcome"] == "retry" \
                and first["log"][0]["code"] == 500, first
            assert 45 <= _pause_seconds(first) <= 90, f"пауза после первой неудачи {_pause_seconds(first)} с, ждали около 60"
            # п. 1: срок прошёл — вторая попытка тоже неудачна, пауза выросла (около 5 минут)
            assert helpers_notify.tick(shift=3)["shifted"] >= 1
            second = _wait_delivery(tab, member.email, "telegram", word,
                                    lambda d: d["attempts"] >= 2, "две попытки")
            assert second["state"] == "waiting" and len(second["log"]) == 2, second
            assert 240 <= _pause_seconds(second) <= 360, f"пауза после второй неудачи {_pause_seconds(second)} с, ждали около 300"
            assert _pause_seconds(second) > _pause_seconds(first) * 2
            assert not helpers_notify.sent_to(bots, "telegram", chat) or all(
                EXTERNAL not in (m.get("text") or "") for m in helpers_notify.sent_to(bots, "telegram", chat))
            # п. 1: Telegram снова отвечает — третья попытка доходит, сообщение одно (контроль того же пути)
            helpers_notify.tick(shift=10)
            helpers_notify.wait_sent(bots, "telegram", chat_id=chat, text_has=EXTERNAL, timeout=DELIVERY_WAIT)
            done = _wait_delivery(tab, member.email, "telegram", word, lambda d: d["state"] == "sent", "отправлено")
            assert done["attempts"] == 3, done
            # «ровно одно» — повторной проверкой в конце
            tab.wait_for_timeout(3000)
            found = [m for m in helpers_notify.sent_to(bots, "telegram", chat) if EXTERNAL in (m.get("text") or "")]
            assert len(found) == 1, f"сообщений «{EXTERNAL}» в свой чат: {len(found)}"
            # уведомление на портале одно и осталось непрочитанным
            expect(_rows(tab, word)).to_have_count(1)
            assert helpers_notify.bell_count(tab) == base + 1


def test_e11_blocked_bot_unbinds_channel_creates_channel_unlinked_notification_and_system_journal_entry_without_chat_id(
        admin_page, employee, new_context):
    """Сценарий 11, п. 2: сотрудник заблокировал бота (ответ 403 на `sendMessage`) — привязка снята, на портале появилось
    уведомление «Telegram отвязан: бот недоступен», в журнале `/audit/` запись «Канал уведомлений отвязан» от имени
    системы с причиной «бот недоступен» и без идентификатора чата; в Telegram по нему сообщений нет (FR-332, FR-344,
    FR-341)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [member], tag)
    bots = helpers_notify.fakebots()
    chat = _chat_id()
    with helpers_notify.channels_on(page, "telegram"), _clear_fails_at_exit(bots, "telegram"):
        _bound(member.page, bots, "telegram", chat)
        with _default_queue(page, old_id, queue_id):
            tab = helpers_notify.open_watcher(new_context, member)
            base = helpers_notify.bell_count(tab)
            # дано: бот заблокирован — ближайшая отправка получит 403
            bots.fail("telegram", 403, method="sendMessage", count=1)
            # когда: наступает событие
            word, _subject = _new_ticket()
            # п. 2: на колокольчике два новых — о заявке и «Канал отвязан»
            helpers_notify.wait_bell_count(tab, base + 2, timeout_ms=int(DELIVERY_WAIT * 1000))
            expect(_rows(tab, word)).to_have_count(1)
            unbound = _rows(tab, UNBOUND_TEXT)
            expect(unbound).to_have_count(1)
            assert _norm(unbound.locator('[data-field="text"]').inner_text()) == UNBOUND_TEXT
            expect(unbound).to_have_attribute("data-unread", "1")
            # п. 2: привязка снята
            tab.goto("/me/notifications/")
            expect(tab.locator("#notify-binding-telegram")).to_have_attribute("data-state", "unbound")
            # п. 2: в журнале запись от имени системы, причина «бот недоступен», идентификатора чата нет
            rows = _audit_rows(page, UNBOUND_ACTION, member.id)
            assert len(rows) == 1, f"записей «Канал уведомлений отвязан» о сотруднике: {len(rows)}"
            row = rows[0]
            assert "система" in row["actor"], row["actor"]
            assert "бот недоступен" in row["after"], row["after"]
            assert "telegram" in row["before"], row["before"]
            assert str(chat) not in row["text"], "в записи журнала есть идентификатор чата"
            # п. 2: по этому уведомлению сообщений в мессенджер нет (положительный контроль — привязка была рабочей)
            tab.wait_for_timeout(3000)
            texts = [m.get("text") or "" for m in helpers_notify.sent_to(bots, "telegram", chat)]
            assert any("привязан" in t for t in texts), "ответ бота о привязке не найден (контроль)"
            assert not [t for t in texts if "отвязан" in t or EXTERNAL in t], texts
            # п. 2: почта, push и мессенджеры по «Канал отвязан» не используются (вид обязательный): доставок нет
            assert _delivery_count(member.email, UNBOUND_TEXT) == 0, "у уведомления «Канал отвязан» есть доставки"
            assert helpers_notify.bell_count(tab) == base + 2


@helpers_notify.webpush_only
def test_e11_push_service_subscription_gone_removes_subscription(admin_page, employee, webpush_context):
    """Сценарий 11, п. 3: push-сервис отвечает «подписка не существует» (подписка отменена в браузере — способ
    тот же, что в test_e05 (решение 26 задач)), когда портал отправляет Web Push, подписка удалена: пропала из списка устройств,
    в журнале «Подписка push удалена» от имени системы, доставка `failed` с причиной «нет подписок» (FR-332). Если
    настоящий push-сервис не ответил 404/410, а принял push (2xx), это наблюдение решения 26 (`xfail`), а не ошибка
    портала; 404/410 при оставшейся подписке или иной итог — ошибка."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [member], tag)
    with helpers_notify.channels_on(page, "webpush"):
        # дано: подписка устройства в постоянном профиле
        context = webpush_context()
        tab = helpers_notify.open_tab(context, member, url="/me/notifications/", grant=True)
        device = helpers_notify.enable_push_on_device(tab)
        _prefs(member.page, ["push"])
        assert _push_count(member.email) == 1
        # дано: подписка отменена в браузере — push-сервис её больше не знает
        removed = tab.evaluate("""async () => {
            const registration = await navigator.serviceWorker.ready;
            const subscription = await registration.pushManager.getSubscription();
            return subscription ? await subscription.unsubscribe() : false;
        }""")
        assert removed is True, "подписка в браузере не отменена"
        # вкладок сотрудника не остаётся: при открытой вкладке Web Push пропускается (FR-331)
        tab.close()
        member.page.goto("about:blank")
        deadline = time.monotonic() + 75  # запись присутствия живёт до 60 с (§ 6.8)
        while _is_online(member.id):
            assert time.monotonic() < deadline, "присутствие сотрудника не погасло за 75 с"
            page.wait_for_timeout(1000)
        with _default_queue(page, old_id, queue_id):
            # когда: наступает событие и портал отправляет Web Push
            word, _subject = _new_ticket()
            # п. 3: подписка удалена после отказа push-сервиса
            deadline = time.monotonic() + DELIVERY_WAIT
            while _push_count(member.email) != 0:
                if time.monotonic() >= deadline:
                    _push_not_gone(member.email, word)
                page.wait_for_timeout(1000)
            failed = _wait_delivery(page, member.email, "webpush", word, lambda d: d["state"] in ("failed", "sent"),
                                    "итог доставки")
            assert failed["state"] == "failed" and failed["reason"] == "no_subscriptions", failed
            assert any(e["outcome"] == "gone" for e in failed["log"]), failed
        # п. 3: устройство пропало из списка «Мои уведомления»
        member.page.goto("/me/notifications/")
        expect(member.page.locator(f'ul[data-devices] li[data-device="{device}"]')).to_have_count(0)
        # п. 3: в журнале запись от имени системы
        rows = _audit_rows(page, REMOVED_ACTION, member.id)
        assert len(rows) == 1, f"записей «Подписка push удалена» о сотруднике: {len(rows)}"
        assert "система" in rows[0]["actor"] and "недействительна" in rows[0]["after"], rows[0]
        # уведомление на портале осталось
        expect(_rows(member.page, word)).to_have_count(1)


def test_e11_after_24_hours_delivery_marked_not_delivered_portal_notification_stays_and_no_new_notification(
        admin_page, employee, new_context):
    """Сценарий 11, п. 4: все попытки отправки в Telegram не удались, прошли 24 часа (`e2e_notify_tick --age-days 1`) —
    доставка `failed` с причиной «срок вышел» (`expired`), уведомление на портале остаётся непрочитанным, новых уведомлений
    (в том числе «Канал отвязан») не создано (FR-333)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [member], tag)
    bots = helpers_notify.fakebots()
    chat = _chat_id()
    with helpers_notify.channels_on(page, "telegram"), _clear_fails_at_exit(bots, "telegram"):
        _bound(member.page, bots, "telegram", chat)
        with _default_queue(page, old_id, queue_id):
            tab = helpers_notify.open_watcher(new_context, member)
            base = helpers_notify.bell_count(tab)
            # дано: Telegram недоступен для двух попыток теста (обе будут отвечены 500)
            bots.fail("telegram", 500, method="sendMessage", count=2)
            word, _subject = _new_ticket()
            helpers_notify.wait_bell_count(tab, base + 1, timeout_ms=15_000)
            first = _wait_delivery(tab, member.email, "telegram", word, lambda d: d["attempts"] >= 1, "одна попытка")
            assert first["state"] == "waiting", first
            total = _all_rows(tab)
            # когда: проходит 24 часа с создания, обход ставит повтор, вторая попытка тоже неудачна
            tick = helpers_notify.tick(age_days=1)
            assert tick["aged_rows"] >= 1 and tick["requeued"] >= 1, tick
            # п. 4: доставка помечена «не доставлено» (`failed`, `expired`)
            done = _wait_delivery(tab, member.email, "telegram", word, lambda d: d["state"] != "waiting",
                                  "итог доставки")
            assert done["state"] == "failed" and done["reason"] == "expired", done
            assert done["attempts"] == 2 and [e["outcome"] for e in done["log"]][-1] in ("retry", "failed"), done
            # п. 4: уведомление на портале осталось, непрочитанное; новых уведомлений нет — проверка в конце, после паузы
            tab.wait_for_timeout(3000)
            rows = _rows(tab, word)
            expect(rows).to_have_count(1)
            expect(rows).to_have_attribute("data-unread", "1")
            assert _all_rows(tab) == total, "после истечения срока на портале появились новые уведомления"
            expect(_rows(tab, UNBOUND_TEXT)).to_have_count(0)
            assert helpers_notify.bell_count(tab) == base + 1
            # привязка Telegram на месте (отказ 500 её не снимает), сообщения о заявке в чате нет
            tab.goto("/me/notifications/")
            expect(tab.locator("#notify-binding-telegram")).to_have_attribute("data-state", "bound")
            assert not [m for m in helpers_notify.sent_to(bots, "telegram", chat) if EXTERNAL in (m.get("text") or "")]


def test_e11_send_job_run_twice_after_failure_gives_single_message(admin_page, employee, new_context):
    """Сценарий 11, п. 6: задание отправки выполнилось дважды (повтор после сбоя) — первая отправка не удалась, два
    задания `send_delivery` на одну доставку удерживаются паузой RQ (доп. 26) и выполняются подряд: сообщение в Telegram
    одно, второе задание выходит без отправки (число попыток 2: неудача и успех) (NFR-306). Способ: `e2e_notify_tick
    --shift N` сбрасывает `enqueued_at`, поэтому обход ставит задание повторно; аренда `lease_until` (§ 6.9) командой
    стенда не задаётся."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [member], tag)
    bots = helpers_notify.fakebots()
    chat = _chat_id()
    with helpers_notify.channels_on(page, "telegram"), _clear_fails_at_exit(bots, "telegram"):
        _bound(member.page, bots, "telegram", chat)
        with _default_queue(page, old_id, queue_id):
            tab = helpers_notify.open_watcher(new_context, member)
            bots.fail("telegram", 500, method="sendMessage", count=1)
            word, _subject = _new_ticket()
            first = _wait_delivery(tab, member.email, "telegram", word, lambda d: d["attempts"] >= 1, "одна попытка")
            assert first["state"] == "waiting" and first["attempts"] == 1, first
            delivery_id = first["id"]
            try:
                _pause_jobs()
                # два обхода подряд при паузе: каждый сбрасывает `enqueued_at` и ставит задание на ту же доставку
                for shift in (2, 1):
                    result = helpers_notify.tick(shift=shift)
                    assert result["shifted"] >= 1 and result["requeued"] >= 1, result
                assert _send_jobs(delivery_id) == 2, "два задания send_delivery этой доставки не стоят в очереди"
                assert not helpers_notify.sent_to(bots, "telegram", chat) or all(
                    EXTERNAL not in (m.get("text") or "") for m in helpers_notify.sent_to(bots, "telegram", chat))
            finally:
                _resume_jobs()
            # когда: оба задания выполнены
            helpers_notify.wait_sent(bots, "telegram", chat_id=chat, text_has=EXTERNAL, timeout=DELIVERY_WAIT)
            deadline = time.monotonic() + DELIVERY_WAIT
            while _send_jobs(delivery_id) != 0:
                assert time.monotonic() < deadline, "задания send_delivery не выполнены за 90 с"
                tab.wait_for_timeout(1000)
            # п. 6: сообщение одно (проверка в конце, когда очередь пуста), доставка отправлена, попыток две
            tab.wait_for_timeout(3000)
            found = [m for m in helpers_notify.sent_to(bots, "telegram", chat) if EXTERNAL in (m.get("text") or "")]
            assert len(found) == 1, f"сообщений «{EXTERNAL}» в свой чат: {len(found)}"
            done = _delivery(member.email, "telegram", word)
            assert done["state"] == "sent" and done["attempts"] == 2, done


@helpers_notify.webpush_only
def test_e11_dismissed_employee_loses_subscriptions_bindings_codes_gets_no_messages_and_journal_has_was_became_without_chat_id(
        admin_page, employee, webpush_context):
    """Сценарий 11, п. 7: у сотрудника есть подписка Web Push, привязки Telegram и MAX и неиспользованный код — его
    увольняют: подписки, привязки и коды удалены (строки базы), сообщения в бывшие чаты не приходят (контроль — привязанный
    коллега по очереди получает то же событие), в журнале записи «было / стало» об отвязке (причина «увольнение») и об
    удалении подписки от имени системы, без идентификатора чата (FR-340, FR-341)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    leaver, keeper = (_staff(employee, tag, i) for i in (1, 2))
    queue_id, _name = _queue(page)
    _members(page, queue_id, [leaver, keeper], tag)
    bots = helpers_notify.fakebots()
    chat_tg, chat_max, chat_keeper = _chat_id(), _chat_id(), _chat_id()
    with helpers_notify.channels_on(page, "webpush", "telegram", "max"):
        context = webpush_context()
        tab = helpers_notify.open_tab(context, leaver, url="/me/notifications/", grant=True)
        helpers_notify.enable_push_on_device(tab)
        helpers_notify.bind_channel(leaver.page, bots, "telegram", chat_tg)
        helpers_notify.bind_channel(leaver.page, bots, "max", chat_max)
        helpers_notify.bind_channel(keeper.page, bots, "telegram", chat_keeper)
        _prefs(keeper.page, ["telegram"])
        _prefs(leaver.page, ["telegram"])
        issued = helpers_org.direct_post(leaver.page, "/me/notifications/bind/telegram/")
        assert issued.status == 200, f"новый код не выдан: статус {issued.status}"
        before = _db_counts(leaver.email)
        assert before["push"] >= 1 and before["bindings"] == 2 and before["unused_codes"] >= 1, before
        known_tg = len(helpers_notify.sent_to(bots, "telegram", chat_tg))
        known_max = len(helpers_notify.sent_to(bots, "max", chat_max))
        # дано: событие наступило до увольнения, задания отправки удержаны паузой RQ (доп. 26) — у обоих доставка ждёт
        with _default_queue(page, old_id, queue_id):
            try:
                _pause_jobs()
                word, _subject = _new_ticket()
                assert _delivery(leaver.email, "telegram", word)["state"] == "waiting", "у уволенного нет ждущей доставки"
                assert _delivery(keeper.email, "telegram", word)["state"] == "waiting", "у коллеги нет ждущей доставки"
                # когда: сотрудника увольняют
                _dismiss(page, leaver.id)
            finally:
                _resume_jobs()
        # п. 7: подписки, привязки и неиспользованные коды удалены (использованные уйдут обходом хранения, доп. 28 (б))
        counts = _db_counts(leaver.email)
        assert (counts["push"], counts["bindings"], counts["unused_codes"]) == (0, 0, 0), counts
        # п. 7: в журнале — отвязка Telegram и MAX от имени системы с причиной «увольнение», без идентификатора чата
        unbound = _audit_rows(page, UNBOUND_ACTION, leaver.id)
        assert len(unbound) == 2, f"записей об отвязке уволенного: {len(unbound)}"
        for row in unbound:
            assert "система" in row["actor"] and "увольнение" in row["after"], row
            assert str(chat_tg) not in row["text"] and str(chat_max) not in row["text"], "в записи есть идентификатор чата"
        assert sorted("telegram" if "telegram" in r["before"] else "max" for r in unbound) == ["max", "telegram"]
        removed = _audit_rows(page, REMOVED_ACTION, leaver.id)
        assert len(removed) >= 1 and all("система" in r["actor"] and "увольнение" in r["after"] for r in removed), removed
        # п. 7: ожидавшая доставка уволенного пропущена с причиной увольнения (§ 6.15), у коллеги (контроль) сообщение есть
        skipped = _wait_delivery(page, leaver.email, "telegram", word, lambda d: d["state"] != "waiting",
                                 "доставка пропущена", timeout=30.0)
        assert skipped["state"] == "skipped" and skipped["reason"] == "user_dismissed", skipped
        helpers_notify.wait_sent(bots, "telegram", chat_id=chat_keeper, text_has=EXTERNAL, timeout=DELIVERY_WAIT)
        helpers_notify.tick(shift=3)
        page.wait_for_timeout(5000)
        assert len(helpers_notify.sent_to(bots, "telegram", chat_tg)) == known_tg
        assert len(helpers_notify.sent_to(bots, "max", chat_max)) == known_max
        assert len([m for m in helpers_notify.sent_to(bots, "telegram", chat_keeper)
                    if EXTERNAL in (m.get("text") or "")]) == 1


def test_e11_mail_attempts_in_mail_module_delivery_journal_other_channels_in_notification_delivery_record_and_not_in_audit(
        admin_page, employee, new_context, mailpit):
    """Сценарий 11, п. 8: письмо уведомления видно в журнале доставки почтового модуля `/settings/mail-log/` (адресат,
    шаблон `notify.item`, состояние «отправлено»), попытки в Telegram — в записи «Доставка» уведомления (`log`, без
    чата), а в журнале событий `/audit/` самих уведомлений нет (FR-333, FR-341)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [member], tag)
    bots = helpers_notify.fakebots()
    chat = _chat_id()
    with helpers_notify.channels_on(page, "telegram"):
        helpers_notify.bind_channel(member.page, bots, "telegram", chat)
        _prefs(member.page, ["telegram"])
        member.page.goto("/me/notifications/")
        email_cell = member.page.locator(f'tr[data-notify-kind="{NEW_IN_QUEUE}"] td[data-channel="email"] '
                                         f'input[type=checkbox][name="cell"][value="{NEW_IN_QUEUE}:email"]')
        expect(email_cell).to_be_checked()  # по умолчанию вид включён в почте (§ 3.2)
        with _default_queue(page, old_id, queue_id):
            tab = helpers_notify.open_watcher(new_context, member)
            base = helpers_notify.bell_count(tab)
            word, subject = _new_ticket()
            helpers_notify.wait_bell_count(tab, base + 1, timeout_ms=15_000)
            helpers_notify.wait_sent(bots, "telegram", chat_id=chat, text_has=EXTERNAL, timeout=DELIVERY_WAIT)
            # когда: проходит срок письма
            helpers_notify.tick(shift=121)
            helpers_notify.wait_item_mail(mailpit, member.email, timeout=DELIVERY_WAIT)
            # п. 8: письмо — в журнале доставки почтового модуля
            # журнал показывает 50 последних писем стенда: строку ищем по адресату, шаблону и подписи «отправлено»,
            # при необходимости — на следующих страницах (до трёх)
            deadline = time.monotonic() + 30
            while True:
                page.goto("/settings/mail-log/")
                for _page_no in range(3):
                    rows = page.locator("table tbody tr").filter(has_text=member.email) \
                        .filter(has_text=helpers_notify.TEMPLATE_ITEM).filter(has_text="отправлено")
                    forward = page.locator('nav[aria-label="Страницы журнала"] a').filter(has_text="Вперёд")
                    if rows.count() >= 1 or forward.count() == 0:
                        break
                    forward.first.click()
                    page.wait_for_load_state()
                if rows.count() >= 1:
                    break
                assert time.monotonic() < deadline, "письма notify.item нет в журнале доставки почтового модуля"
                page.wait_for_timeout(1000)
            expect(rows).to_have_count(1)
            # п. 8: попытка в Telegram — в записи «Доставка» уведомления: удача, без чата
            record = _delivery(member.email, "telegram", word)
            assert record["state"] == "sent" and [e["outcome"] for e in record["log"]] == ["ok"], record
            assert str(chat) not in json.dumps(record), "в записи «Доставка» есть идентификатор чата"
            # п. 8: в журнале событий самих уведомлений нет — ни записей, кроме шести кодов § 9.2, ни текста уведомления
            actions = helpers.audit_actions(page)
            foreign = [a for a in actions if a.startswith("notify.") and a not in NOTIFY_ACTIONS]
            assert not foreign, f"в журнале события уведомлений: {foreign}"
            text = helpers.audit_text(page)
            assert word not in text and subject not in text, "текст уведомления или тема заявки попали в журнал"
            assert str(chat) not in text, "идентификатор чата попал в журнал"
