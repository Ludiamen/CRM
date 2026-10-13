"""Помощники приёмки среза 004 «Уведомления» (T-4140, CONTRACT-004.md § 1.1, § 8, § 14.1, решения E21–E23).

Что здесь есть:
- клиент учебной службы ботов `fakebots` (§ 1.1, § 1.2, решение E23): `FakeBots`, `fakebots`, `wait_sent`, `sent_to`;
- команды стенда `e2e_notify_tick` и `e2e_notify_fill` (§ 8.1, § 8.2): `tick`, `parse_tick`, `fill`, `parse_fill`;
- готовность соединения и число колокольчика (§ 14.1, решение E21): `wait_ws_open`, `bell_count`, `wait_bell_count`;
- системные уведомления вкладки (§ 14.1, решение E22): `NOTIFICATION_SPY`, `install_notification_spy`,
  `install_notification_spy_now`, `notifications`, `wait_notifications`, `no_notifications`, `click_notification`,
  `grant_notifications`, `notification_permission`;
- push при закрытой вкладке (§ 14.1, решение E22, доп. 23): `service_worker_notifications`,
  `wait_service_worker_notifications`, `no_service_worker_notifications`, `close_service_worker_notifications`,
  `has_push_subscription`, `has_push_subscription_ctx`;
- несколько контекстов браузера и постоянный профиль `webpush_context()` (строка T-4140, доп. 23): `session_state`,
  `adopt_session`, `open_tab`, `open_watcher`, `open_watchers`;
- Web Push только в кругах Chromium и Edge (решение 8 задач): `webpush_only`, `is_webpush_circle`;
- письма уведомлений в Mailpit по поиску адреса получателя (§ 10.1, § 10.2): `find_mails`, `wait_template_mail`,
  `no_template_mail`, `wait_item_mail`, `no_item_mail`, `wait_digest_mail`, `no_digest_mail`, `open_link_in`;
- каналы и привязки для тестов внешних каналов (§ 13.2, § 13.3, § 14.3, § 14.4, § 15.3): `channels_on` (администратор
  включает Telegram, MAX, Web Push на время блока), `bind_channel` (привязка бота кодом через `fakebots`),
  `enable_push_on_device` (подписка устройства на Web Push в постоянном профиле).

Правила: код приложения (`apps.*`, `django`) и `tests.support_notify` не импортируются — тесты идут с хоста против
стенда; свой запуск браузера не заводится (§ 8.1, решение E23: круги Chromium и Edge запускает `conftest.browser`);
токены и ключи не читаются и не печатаются (в сообщениях об ошибках — только `***`). Файл правит только T-4140.
"""
import contextlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import expect

from tests.e2e import conftest, helpers, helpers_sd

# --- Адреса и имена приёмки ----------------------------------------------------------------------

FAKEBOTS_URL = os.environ.get("E2E_FAKEBOTS_URL") or "http://127.0.0.1:8099"  # § 1.1, решение E23 (пустое значение = по умолчанию)
BOT_CHANNELS = ("telegram", "max")  # каналы fakebots (§ 1.2); не путать с `conftest.CHANNELS` (круги браузеров)
ADMIN_CHANNELS = ("webpush", "telegram", "max")  # переключатели страницы администратора (§ 14.4)
_PORTAL = urllib.parse.urlsplit(conftest.PORTAL_URL)
PORTAL_ORIGIN = f"{_PORTAL.scheme}://{_PORTAL.netloc}"  # источник для разрешений браузера: https://127.0.0.1:8031
TEMPLATE_ITEM = "notify.item"  # X-Portal-Template письма об одном уведомлении (§ 10.1)
TEMPLATE_DIGEST = "notify.digest"  # то же у сводки
SW_PATH = "/sw.js"  # сервис-воркер Web Push; открывается без входа (§ 13: «кроме `/sw.js`»)


# --- Клиент учебной службы ботов (§ 1.1, § 1.2; решение E23) ------------------------------------------

class FakeBots:
    """Клиент `fakebots` для приёмки: те же методы, что у `support_notify.FakeBots` (§ 1.1), без Django.

    Адрес — `E2E_FAKEBOTS_URL` (по умолчанию, в том числе при пустом значении, `http://127.0.0.1:8099`). Адрес,
    оканчивающийся на `telegram.org` (с точкой в конце или без), отвергается (`RuntimeError`): приёмка не может уйти
    в настоящий Telegram (дополнение 3 раздела 17). Токены службе не нужны (§ 1.2: проверяются только служебные
    адреса `/_test/*`); их клиент не знает. Запросы идут мимо прокси окружения (как у `support_notify.FakeBots`)."""

    _opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def __init__(self, base_url: str | None = None):
        base = (base_url or FAKEBOTS_URL).rstrip("/")
        host = (urllib.parse.urlsplit(base).hostname or base).rstrip(".")
        if base.rstrip(".").endswith("telegram.org") or host.endswith("telegram.org"):
            raise RuntimeError("адрес учебной службы ботов оканчивается на telegram.org: приёмка не ходит в настоящий "
                               "Telegram")
        self.base_url = base

    def _call(self, method: str, path: str, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.base_url + path, data=data, method=method,
                                         headers={"Content-Type": "application/json"} if data is not None else {})
        try:
            with self._opener.open(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise AssertionError(f"fakebots {method} {path}: ответ {e.code}") from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise AssertionError(f"fakebots {method} {path} недоступна: {type(e).__name__}") from None

    @staticmethod
    def _channel(channel: str) -> str:
        if channel not in BOT_CHANNELS:
            raise ValueError(f"канал {channel!r}: нужен один из {BOT_CHANNELS}")
        return channel

    def health(self) -> dict:
        """`GET /_test/health` → `{"ok": true}`."""
        return self._call("GET", "/_test/health")

    def put_telegram(self, event_or_list) -> list:
        """`POST /_test/telegram/updates`: одно событие (словарь) или список; возвращает `update_ids` по порядку
        (формы событий — § 1.2, «Форма входящих событий»)."""
        return self._call("POST", "/_test/telegram/updates", event_or_list)["update_ids"]

    def put_max(self, event_or_list) -> int:
        """`POST /_test/max/updates`: одно событие или список; возвращает `marker` (номер следующего события)."""
        return self._call("POST", "/_test/max/updates", event_or_list)["marker"]

    def sent(self, channel: str) -> list:
        """`GET /_test/sent?channel=…`: все сообщения бота канала по порядку отправки (ключи — § 1.2: Telegram —
        `message_id`, `chat_id`, `text`, `parse_mode`, `reply_markup`, `link_preview_options`, `time`; MAX —
        `message_id`, `chat_id`, `user_id`, `text`, `format`, `attachments`, `notify`, `disable_link_preview`, `time`)."""
        return self._call("GET", f"/_test/sent?channel={self._channel(channel)}")["messages"]

    def fail(self, channel: str, status: int, *, method: str = "*", count: int = 1, retry_after: int = 1) -> None:
        """`POST /_test/fail`: следующие `count` запросов к методу получают ошибку `status` (401, 403, 409, 429, 500);
        `method` — `getMe`, `getUpdates`, `sendMessage`, `deleteWebhook` или `me`, `updates`, `messages`, `*`."""
        self._call("POST", "/_test/fail", {"channel": self._channel(channel), "status": status, "method": method,
                                           "count": count, "retry_after": retry_after})

    def reset(self) -> None:
        """`POST /_test/reset`: события, отправленные сообщения, заказанные сбои и счётчики стираются."""
        self._call("POST", "/_test/reset")


def fakebots() -> FakeBots:
    """Клиент по `E2E_FAKEBOTS_URL` **без сброса** учебной службы. Сброс посреди круга обнулил бы номера событий
    `fakebots`, а курсор опроса портала (`BotState.cursor`) остался бы прежним, и новые события портал бы не увидел.
    Службу и курсоры сбрасывает только сброс стенда (`helpers_sd.reset_stand_and_relogin`, точка `notify`, § 8.3).
    Поэтому в журнале `sent` есть сообщения прежних тестов круга: сообщения своего теста выбирать по своему `chat_id`
    (`sent_to`, `wait_sent(..., chat_id=…)`)."""
    return FakeBots()


def wait_sent(bots: FakeBots, channel: str, *, count: int = 1, timeout: float = 30.0, text_has: str | None = None,
              chat_id=None) -> list:
    """Ждёт (до `timeout` с), пока в `sent(channel)` появится не меньше `count` сообщений (с подстрокой `text_has` в
    `text`, если задана; только в чат `chat_id`, если задан — `sent_to`); возвращает подходящие сообщения по порядку
    отправки. Не пришло — `AssertionError`."""
    deadline = time.monotonic() + timeout
    while True:
        messages = bots.sent(channel) if chat_id is None else sent_to(bots, channel, chat_id)
        found = [m for m in messages if text_has is None or text_has in (m.get("text") or "")]
        if len(found) >= count:
            return found
        if time.monotonic() >= deadline:
            raise AssertionError(f"в {channel} за {timeout:.0f} с пришло {len(found)} сообщений из {count}")
        time.sleep(0.5)


def sent_to(bots: FakeBots, channel: str, chat_id) -> list:
    """Сообщения бота канала в чат `chat_id` (по порядку отправки): `[m for m in bots.sent(channel) if m["chat_id"] ==
    chat_id]`; `chat_id` сравнивается как строка (в службе он целое). `fakebots` у всего круга одна и общая, поэтому
    сообщения тест выбирает по своему уникальному `chat_id`, а не «последнее»."""
    return [m for m in bots.sent(channel) if str(m.get("chat_id")) == str(chat_id)]


# --- Команды стенда (§ 8.1 «Запуск с хоста», § 8.2) ----------------------------------------------------

TICK_KEYS = ("shifted", "aged_codes", "aged_rows", "emails", "released", "requeued", "digests", "codes")
TICK_RETENTION_KEYS = ("retention_notifications", "retention_digests", "retention_codes", "retention_botchats")
FILL_KEYS = ("created", "read", "unread")


def _parse_line(line: str, prefix: str) -> dict:
    """Строка `<prefix>: ключ=число …` → словарь `{ключ: int}`; другая форма — `AssertionError`."""
    if not line.startswith(prefix + ":"):
        raise AssertionError(f"ожидалась строка «{prefix}: …», получено: {line[:200]!r}")
    result = {}
    for part in line[len(prefix) + 1:].split():
        key, sep, value = part.partition("=")
        if not sep or not re.fullmatch(r"[a-z_]+", key) or not re.fullmatch(r"\d+", value):
            raise AssertionError(f"в строке «{prefix}» часть {part[:80]!r} не вида ключ=число")
        result[key] = int(value)
    return result


def parse_tick(line: str) -> dict:
    """Строка вывода `e2e_notify_tick` (§ 8.2) → словарь целых: `shifted`, `aged_codes`, `aged_rows`, `emails`,
    `released`, `requeued`, `digests`, `codes`, а при `--retention` ещё `retention_notifications`, `retention_digests`,
    `retention_codes`, `retention_botchats`. Нет ключа из первой восьмёрки или лишний ключ — `AssertionError`."""
    result = _parse_line(line, "notify_tick")
    missing = [k for k in TICK_KEYS if k not in result]
    extra = [k for k in result if k not in TICK_KEYS + TICK_RETENTION_KEYS]
    retention = [k for k in TICK_RETENTION_KEYS if k in result]
    if missing or extra or (retention and len(retention) != len(TICK_RETENTION_KEYS)):
        raise AssertionError(f"строка notify_tick не по § 8.2: нет {missing}, лишние {extra}, retention {retention}")
    return result


def parse_fill(line: str) -> dict:
    """Строка вывода `e2e_notify_fill` (§ 8.2) `notify_fill: created=N read=K unread=N-K` → словарь целых."""
    result = _parse_line(line, "notify_fill")
    if sorted(result) != sorted(FILL_KEYS):
        raise AssertionError(f"строка notify_fill не по § 8.2: ключи {sorted(result)}")
    return result


def tick(*, shift: int | None = None, age_codes: int | None = None, age_days: int | None = None,
         retention: bool = False) -> dict:
    """`e2e_notify_tick` (§ 8.2) в службе `standtools`: сначала сдвиги (в порядке `age_days`, `age_codes`, `shift`),
    затем всегда один обход, затем при `retention=True` ночное удаление. Сдвиги — по **всем** строкам стенда.
    - `shift=N` (минуты, 1…525600): `due_at` ожидающих доставок назад на N минут (срок письма, повторы); `held` и
      `digest_due_at` не трогает (срок сводки — решения C1, E23: смена режима на «Без тихих часов» или свои часы
      вокруг текущего времени, значение читает `helpers.stand_shell`);
    - `age_codes=M` (минуты, 1…525600): коды привязки назад на M минут;
    - `age_days=D` (сутки, 1…36500): уведомления, сводки и сроки доставок назад на D суток (хранение).
    Поставленные обходом задания (`send_delivery`, `build_digest`) команда сама не выполняет — их берёт
    `worker-notify` стенда, письма шлёт `worker-mail`: результат тест ждёт в интерфейсе, Mailpit и `fakebots`.
    Возвращает словарь `parse_tick`. Аргумент вне диапазона — `ValueError` (команда ответила бы кодом 2)."""
    args = ["e2e_notify_tick"]
    for flag, value, limit in (("--age-days", age_days, 36500), ("--age-codes", age_codes, 525600),
                               ("--shift", shift, 525600)):
        if value is not None:
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= limit:
                raise ValueError(f"{flag}: нужно целое от 1 до {limit}, получено {value!r}")
            args += [flag, value]
    if retention:
        args.append("--retention")
    result = parse_tick(helpers_sd._stand_command(*args))
    if retention and "retention_notifications" not in result:
        raise AssertionError("с --retention в строке notify_tick нет ключей retention_*")
    return result


def fill(email: str, count: int, *, read: int = 0) -> dict:
    """`e2e_notify_fill ПОЧТА N [--read K]` (§ 8.2): сотруднику создаётся `count` уведомлений «Тестовое уведомление i»
    (вид `core.password_changed`, ссылка `/notifications/`), `read` самых старых — прочитанными; без доставок, без
    событий шины и без записи в журнал; открытые вкладки получают новое число (`live.push`). `count` — 1…1000,
    `read` — 0…`count`. Возвращает `{"created": N, "read": K, "unread": N-K}`; несовпадение с запрошенным —
    `AssertionError`."""
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 1000:
        raise ValueError(f"count: нужно целое от 1 до 1000, получено {count!r}")
    if not isinstance(read, int) or isinstance(read, bool) or not 0 <= read <= count:
        raise ValueError(f"read: нужно целое от 0 до {count}, получено {read!r}")
    args = ["e2e_notify_fill", email, count]
    if read:
        args += ["--read", read]
    result = parse_fill(helpers_sd._stand_command(*args))
    if result != {"created": count, "read": read, "unread": count - read}:
        raise AssertionError(f"e2e_notify_fill вернула {result}, ожидалось created={count} read={read} "
                             f"unread={count - read}")
    return result


# --- Колокольчик: готовность соединения и число (§ 14.1, решение E21) ----------------------------------

def wait_ws_open(page, *, timeout_ms: int = 15_000) -> None:
    """Ждёт `#notify-bell[data-ws="open"]`: `notify.js` ставит `open` после первого кадра сервера, когда присутствие
    уже записано (решение E21). Звать перед событием, которое проверяет живое обновление, и перед проверкой
    «открытая вкладка → Web Push пропущен». У гостя колокольчика нет — ожидание упадёт по времени."""
    expect(page.locator("#notify-bell")).to_have_attribute("data-ws", "open", timeout=timeout_ms)


def bell_count(page) -> int:
    """Число непрочитанных со страницы: `#notify-count[data-count]` (точное, целое, `0` включительно). Нет элемента
    или атрибута (страница без колокольчика: гость, `/sw.js`, страница ошибки) — `AssertionError`."""
    count = page.locator("#notify-count")
    value = count.get_attribute("data-count") if count.count() else None
    if value is None:
        raise AssertionError(f"на странице {page.url} нет #notify-count[data-count]: колокольчика нет (страница без "
                             f"верхней панели или гость)")
    return int(value)


def wait_bell_count(page, expected: int, *, timeout_ms: int = 2_000) -> None:
    """Ждёт `#notify-count[data-count="<expected>"]`; по умолчанию 2 с (NFR-301: число на колокольчике у участника
    растёт за 2 с). Страницу не перезагружает — число приходит кадром `/ws/notify/`."""
    expect(page.locator("#notify-count")).to_have_attribute("data-count", str(int(expected)), timeout=timeout_ms)


# --- Системные уведомления вкладки (§ 14.1 `#notify-toast`, решение E22) ------------------------------

NOTIFICATION_SPY = """
(() => {
  const Native = window.Notification;
  if (!Native || window.__e2eNotificationsInstalled) { return; }
  window.__e2eNotificationsInstalled = true;
  window.__e2eNotifications = [];
  function Wrapped(title, options) {
    const opts = options || {};
    const record = {
      title: String(title),
      tag: opts.tag === undefined ? '' : String(opts.tag),
      data: opts.data === undefined ? null : opts.data,
      object: null,
    };
    window.__e2eNotifications.push(record);
    record.object = new Native(title, options);
    return record.object;
  }
  // Прототип настоящего `Notification` не трогаем (решение R-e0-a п. 5): `n instanceof Notification` верно, а
  // `n.constructor` у записанного объекта остаётся настоящим конструктором, не обёрткой.
  Wrapped.prototype = Native.prototype;
  Object.defineProperty(Wrapped, 'permission', { get: () => Native.permission });
  Object.defineProperty(Wrapped, 'maxActions', { get: () => Native.maxActions });
  Wrapped.requestPermission = function () { return Native.requestPermission.apply(Native, arguments); };
  window.Notification = Wrapped;
})();
"""  # init-скрипт: обёртка `window.Notification` пишет вызовы в `window.__e2eNotifications` и зовёт настоящий конструктор


def install_notification_spy(context) -> None:
    """`context.add_init_script(NOTIFICATION_SPY)`: в каждом документе каждой вкладки контекста `window.Notification`
    заменена обёрткой (решение E22). Звать **до** первого перехода вкладок контекста (страницы, открытые раньше, —
    например `Account.page` из `employee(activate=True)` — обёртки не получат: для них `install_notification_spy_now`).
    Запись живёт, пока жив документ: переход на другую страницу начинает список заново."""
    context.add_init_script(NOTIFICATION_SPY)


def install_notification_spy_now(page) -> None:
    """Обёртка `Notification` для страницы, уже открытой в контексте: ставится в текущий документ (`page.evaluate`) и
    в init-скрипт контекста для следующих переходов. Записи с начала документа не восстанавливаются — звать до
    события, которое проверяется."""
    page.evaluate("() => {" + NOTIFICATION_SPY + "}")
    page.context.add_init_script(NOTIFICATION_SPY)


def _require_spy(page) -> None:
    """Без обёртки «нет уведомлений» проходило бы вхолостую: поэтому её отсутствие — `AssertionError`."""
    if not page.evaluate("() => window.__e2eNotificationsInstalled === true"):
        raise AssertionError("обёртка Notification не установлена: install_notification_spy(context) до перехода или "
                             "install_notification_spy_now(page); в круге без Notification проверка невозможна")


def notifications(page) -> list:
    """Записи конструктора `Notification` текущего документа по порядку: `[{"title", "tag", "data"}]`
    (`data` — `{"url": …}`, как передала вкладка). Обёртка не установлена — `AssertionError`."""
    _require_spy(page)
    return page.evaluate("() => (window.__e2eNotifications || []).map(r => ({title: r.title, tag: r.tag, data: r.data}))")


def wait_notifications(page, *, count: int = 1, timeout_ms: int = 15_000) -> list:
    """Ждёт, пока в документе окажется не меньше `count` записей `Notification`, и возвращает все (`notifications`).
    Не пришло — `AssertionError`. Обёртка обязательна (`install_notification_spy`), иначе `AssertionError`."""
    _require_spy(page)
    try:
        page.wait_for_function("n => (window.__e2eNotifications || []).length >= n", arg=int(count), timeout=timeout_ms)
    except PlaywrightTimeout:
        raise AssertionError(f"вкладка не показала {count} системных уведомлений за {timeout_ms / 1000:.0f} с "
                             f"(показано {len(notifications(page))})") from None
    return notifications(page)


def no_notifications(page, *, observe_ms: int = 5_000) -> bool:
    """True, если за `observe_ms` мс в документе нет ни одной записи `Notification` (ожидание без `time.sleep`:
    `wait_for_function` по условию «есть запись» и его таймаут). Обёртка не установлена — `AssertionError` (иначе
    проверка проходила бы вхолостую); положительный контроль — другой получатель, у которого запись есть."""
    _require_spy(page)
    try:
        page.wait_for_function("() => (window.__e2eNotifications || []).length > 0", timeout=observe_ms)
    except PlaywrightTimeout:
        return True
    return False


def click_notification(page, index: int = -1) -> None:
    """«Нажимает» записанное уведомление: `dispatchEvent(new Event("click"))` у настоящего объекта (решение E22);
    `onclick` вкладки открывает `data-url` в этой же вкладке и закрывает уведомление. Событие уходит со следующего
    такта, поэтому вызов возвращается до перехода страницы; результат тест ждёт `page.wait_for_url(...)`.
    `index` — номер записи (по умолчанию последняя)."""
    page.evaluate("""i => {
        const list = window.__e2eNotifications || [];
        const record = list[i < 0 ? list.length + i : i];
        if (!record || !record.object) { throw new Error('нет записанного уведомления №' + i); }
        setTimeout(() => record.object.dispatchEvent(new Event('click')), 0);
    }""", int(index))


def grant_notifications(context, origin: str | None = None) -> None:
    """Разрешение браузера на уведомления источнику стенда: `context.grant_permissions(["notifications"], origin=…)`.
    Только где сценарий говорит «разрешение дано»; запрос разрешения кнопкой — решение 34 задач (кнопка, а не
    открытие страницы)."""
    context.grant_permissions(["notifications"], origin=origin or PORTAL_ORIGIN)


def notification_permission(page) -> str:
    """`Notification.permission` вкладки: `default`, `granted` или `denied`."""
    return page.evaluate("() => Notification.permission")


# --- Push при закрытой вкладке (§ 14.1, решение E22) -----------------------------------------------------

_SW_COUNT = """async n => {
    const registration = await navigator.serviceWorker.getRegistration();
    if (!registration) { return false; }
    return (await registration.getNotifications()).length >= n;
}"""  # разовая проверка для `page.evaluate`; в `wait_for_function` async-предикат НЕ годится (промис не ждётся)
_SW_WAIT = """async ({n, ms}) => {
    const end = Date.now() + ms;
    for (;;) {
        const registration = await navigator.serviceWorker.getRegistration();
        if (registration && (await registration.getNotifications()).length >= n) { return true; }
        if (Date.now() >= end) { return false; }
        await new Promise(resolve => setTimeout(resolve, 500));
    }
}"""  # цикл внутри одного `evaluate`: Playwright дожидается промиса `evaluate`, а у `wait_for_function` — нет
_SW_LIST = """async () => {
    const registration = await navigator.serviceWorker.getRegistration();
    if (!registration) { return []; }
    return (await registration.getNotifications()).map(n => ({title: n.title, tag: n.tag, body: n.body, data: n.data}));
}"""
_SW_HAS_SUBSCRIPTION = """async () => {
    const registration = await navigator.serviceWorker.getRegistration();
    if (!registration) { return false; }
    return (await registration.pushManager.getSubscription()) !== null;
}"""


def _with_sw_page(context, action, *, url: str):
    """Открывает в контексте **новую** вкладку на `url` (по умолчанию `SW_PATH`: страница без колокольчика, без
    соединения `/ws/notify/` и без отметки присутствия — иначе открытая вкладка заставила бы пропустить Web Push,
    FR-331), выполняет `action(page)` и закрывает вкладку."""
    page = context.new_page()
    try:
        page.goto(url)
        return action(page)
    finally:
        page.close()


def _sw_wait(page, count: int, seconds: float) -> bool:
    """True, если за `seconds` с у воркера появилось не меньше `count` показанных уведомлений."""
    return bool(page.evaluate(_SW_WAIT, {"n": int(count), "ms": int(seconds * 1000)}))


def service_worker_notifications(context, *, url: str = SW_PATH) -> list:
    """Уведомления сервис-воркера, показанные `showNotification` (push при закрытой вкладке): новая вкладка того же
    контекста читает `registration.getNotifications()` → `[{"title", "tag", "body", "data"}]` (`data.url` — ссылка).
    Регистрации нет — пустой список. `getNotifications()` не показывает два уведомления с одним `tag` (второе заменяет
    первое)."""
    return _with_sw_page(context, lambda page: page.evaluate(_SW_LIST), url=url)


def wait_service_worker_notifications(context, *, count: int = 1, timeout: float = 60.0, url: str = SW_PATH) -> list:
    """Ждёт (до `timeout` с; NFR-302 — не дольше минуты) не меньше `count` уведомлений сервис-воркера и возвращает
    все. Не пришло — `AssertionError` с числом показанных. Если безголовый браузер уведомлений воркера не отдаёт —
    вопрос Opus (E22). Учтите: `getNotifications()` не показывает два уведомления с одним `tag` (второе заменяет
    первое), поэтому `count` работает по разным `tag`."""
    def action(page):
        if not _sw_wait(page, count, timeout):
            shown = len(page.evaluate(_SW_LIST))
            raise AssertionError(f"push не показан воркером: ждали {count} шт. за {timeout:.0f} с, показано {shown}")
        return page.evaluate(_SW_LIST)
    return _with_sw_page(context, action, url=url)


def no_service_worker_notifications(context, *, observe: float = 10.0, url: str = SW_PATH) -> bool:
    """True, если за `observe` с воркер не показал ни одного уведомления (проверка «push не пришёл»; ожидание без
    `time.sleep`, цикл в одном `evaluate`). Чем больше `observe`, тем увереннее ответ: доставка идёт обходом, до 90 с на
    подписку. Положительный контроль — другой push в том же тесте."""
    return _with_sw_page(context, lambda page: not _sw_wait(page, 1, observe), url=url)


def close_service_worker_notifications(context, *, url: str = SW_PATH) -> int:
    """Закрывает все показанные воркером уведомления (между шагами теста); возвращает, сколько закрыто."""
    return _with_sw_page(context, lambda page: page.evaluate("""async () => {
        const registration = await navigator.serviceWorker.getRegistration();
        if (!registration) { return 0; }
        const shown = await registration.getNotifications();
        shown.forEach(n => n.close());
        return shown.length;
    }"""), url=url)


def has_push_subscription(page) -> bool:
    """Есть ли у вкладки подписка браузера на push (`registration.pushManager.getSubscription()`); адрес и ключи
    подписки не возвращаются и не печатаются. Страница портала с колокольчиком подключает `/ws/notify/` и ставит
    присутствие (FR-331): тест, который после проверки ждёт push, закрывает эту вкладку — или зовёт
    `has_push_subscription_ctx`."""
    return page.evaluate(_SW_HAS_SUBSCRIPTION)


def has_push_subscription_ctx(context, url: str = SW_PATH) -> bool:
    """То же, что `has_push_subscription`, но в новой вкладке на `url` (по умолчанию `/sw.js`: без колокольчика и
    присутствия), которая закрывается сама — отметка присутствия не появляется и Web Push не пропускается."""
    return _with_sw_page(context, lambda page: page.evaluate(_SW_HAS_SUBSCRIPTION), url=url)


# --- Несколько контекстов браузера: колокольчик у разных сотрудников (строка T-4140) ---------------------

def session_state(account) -> dict:
    """Сессия сотрудника для нового контекста: `storage_state` контекста его страницы (`Account.page`, она есть у
    `employee(activate=True)`), иначе сохранённый `Account.storage_state`. Нет ни того ни другого — `AssertionError`."""
    page = getattr(account, "page", None)
    if page is not None:
        return page.context.storage_state()
    if getattr(account, "storage_state", None):
        return account.storage_state
    raise AssertionError("у сотрудника нет открытой сессии: нужен activate=True или storage_state")


def adopt_session(context, account) -> None:
    """Переносит сессию сотрудника в готовый контекст — в том числе в постоянный профиль `webpush_context()`, у которого
    нет параметра `storage_state`: `context.add_cookies(session_state(account)["cookies"])`. Портал держит сессию в
    cookie, `localStorage` переносить не нужно.

    Оговорка: перенос cookie даёт **ту же сессию и то же устройство** (cookie `portal_device` привязана к сессии), и
    выход в одном контексте закрывает сессию в другом. Поэтому так заводят «того же сотрудника на том же устройстве» и
    наблюдателей, а «второе устройство» (сценарий 5) — это настоящий вход во втором профиле (`helpers.sign_in`; ожидание
    шага TOTP до 30 с неизбежно)."""
    context.add_cookies(session_state(account)["cookies"])


def open_tab(context, account=None, *, url: str = "/", spy: bool = False, grant: bool = False, wait_ws: bool = True):
    """Новая вкладка в готовом контексте (обычном или постоянном профиле `webpush_context()`). Порядок: сессия
    сотрудника `account` переносится (`adopt_session`, если задан), ставится обёртка `Notification` (`spy=True`) и
    выдаётся разрешение браузера (`grant=True`) — всё до перехода; затем `new_page`, `goto(url)` и, при `wait_ws=True`,
    ожидание `#notify-bell[data-ws="open"]` (у страницы без колокольчика — `wait_ws=False`). Возвращает страницу.
    Оговорка о переносе сессии — в `adopt_session`."""
    if account is not None:
        adopt_session(context, account)
    if spy:
        install_notification_spy(context)
    if grant:
        grant_notifications(context)
    page = context.new_page()
    page.goto(url)
    if wait_ws:
        wait_ws_open(page)
    return page


def open_watcher(new_context, account, *, grant: bool = False, spy: bool = True, url: str = "/", context=None):
    """Вкладка-наблюдатель сотрудника `account`: по умолчанию — отдельный контекст браузера (через фикстуру
    `new_context`: закрывается сам) с его сессией; открывает `url` и ждёт `#notify-bell[data-ws="open"]`. `context` —
    готовый контекст (например `webpush_context()`): тогда сессия переносится в него (`adopt_session`), `new_context`
    не используется (можно передать `None`). `grant=True` — разрешение браузера на уведомления источнику стенда;
    `spy=True` — подмена `window.Notification` (`install_notification_spy`). Возвращает страницу; контекст —
    `page.context`. Вкладка остаётся открытой: сотрудник «в сети», Web Push ему пропускается (FR-331). Оговорка о
    переносе сессии (то же устройство) — в `adopt_session`."""
    if context is None:
        context = new_context(storage_state=session_state(account))
        account = None  # сессия уже в контексте
    return open_tab(context, account, url=url, spy=spy, grant=grant, wait_ws=True)


def open_watchers(new_context, accounts, **kwargs) -> list:
    """`open_watcher` для каждого сотрудника из `accounts`: свой контекст у каждого (два контекста — проверка
    колокольчика у двух участников за 2 с, NFR-301). Все соединения готовы к моменту возврата, значит событие можно
    вызывать сразу. Возвращает страницы в порядке `accounts`."""
    return [open_watcher(new_context, account, **kwargs) for account in accounts]


# --- Web Push только в кругах Chromium и Edge (решение 8 задач; план «Проход в браузере») ---------------

WEBPUSH_PROJECTS = ("chromium", "edge")

webpush_only = pytest.mark.webpush
"""Метка для тестов Web Push (`@helpers_notify.webpush_only`, то же, что `@pytest.mark.webpush`): в круге `firefox` тест
снимается со сбора хуком `conftest.pytest_collection_modifyitems` — его там нет вовсе, это не пропуск по условию
(решение 8 задач; T-4138 п. 17). Круги `chromium` и `edge` и их порядок прежние; тест берёт фикстуру `browser` как
обычно."""


def is_webpush_circle(browser) -> bool:
    """True, если круг браузера (`browser.e2e_project`) — Chromium или Edge."""
    return browser.e2e_project in WEBPUSH_PROJECTS


# --- Письма уведомлений в Mailpit (§ 10.1, § 10.2) -------------------------------------------------------

MAIL_SEARCH_LIMIT = 500  # запас: запрос уже отфильтрован по адресу; список без `limit` отдаёт 50 последних (Mailpit v1.31.3)


def mail_search_path(to: str, limit: int = MAIL_SEARCH_LIMIT) -> str:
    """Путь запроса поиска Mailpit по адресу получателя: `/api/v1/search?query=to%3A%22<адрес>%22&limit=<limit>`.
    Адрес с кавычкой или переводом строки — `ValueError`."""
    if not to or '"' in to or "\n" in to or "\r" in to:
        raise ValueError(f"адрес получателя для поиска писем: {to!r}")
    return "/api/v1/search?" + urllib.parse.urlencode({"query": f'to:"{to}"', "limit": int(limit)})


def _mailpit_json(mailpit, path: str):
    with urllib.request.urlopen(mailpit.base_url + path, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def find_mails(mailpit, to: str, template: str | None = None, *, seen=()) -> list:
    """Короткие записи писем на адрес `to` (поиск Mailpit по адресу, не список: список по умолчанию — 50 последних, а
    общий стенд за круг копит больше), новые первыми. `template` — отбор по заголовку `X-Portal-Template`
    (`helpers.template_of`; `None` — любой шаблон); письма с `ID` из `seen` пропускаются. Адрес в `To` сверяется
    точно, без учёта регистра (копии и скрытые копии не считаются)."""
    found = []
    for short in _mailpit_json(mailpit, mail_search_path(to)).get("messages") or []:
        if short["ID"] in seen or not any(a["Address"].lower() == to.lower() for a in short.get("To") or []):
            continue
        if template is not None and helpers.template_of(mailpit, short["ID"]) != template:
            continue
        found.append(short)
    return found


def wait_template_mail(mailpit, to: str, template: str, *, seen=(), timeout: float = 60.0) -> dict:
    """Новое (не из `seen`) письмо с шаблоном `template` на адрес `to`: полный текст Mailpit (`Subject`, `Text`, `ID`…).
    Не пришло за `timeout` с — `AssertionError`."""
    deadline = time.monotonic() + timeout
    while True:
        found = find_mails(mailpit, to, template, seen=seen)
        if found:
            return mailpit.message(found[0]["ID"])
        if time.monotonic() >= deadline:
            raise AssertionError(f"письмо «{template}» на {to} не пришло за {timeout:.0f} с")
        time.sleep(0.5)


def no_template_mail(mailpit, to: str, template: str, *, seen=(), wait: float = 4.0) -> bool:
    """True, если за `wait` с нового письма с шаблоном `template` на `to` нет (опрос каждые полсекунды; письмо
    найдено — False сразу). Звать **после** `tick(...)` и ожидания результата другого канала: письмо, которое уже
    поставлено, дойдёт за секунды, поэтому положительный контроль — письмо другому получателю."""
    deadline = time.monotonic() + wait
    while True:
        if find_mails(mailpit, to, template, seen=seen):
            return False
        if time.monotonic() >= deadline:
            return True
        time.sleep(0.5)


def wait_item_mail(mailpit, to: str, *, seen=(), timeout: float = 60.0) -> dict:
    """Новое письмо `notify.item` (одно уведомление) на рабочий адрес `to`: полный текст Mailpit. Письма уходят
    очередью `mail`; срок письма сдвигает `tick(shift=N)`. Не пришло — `AssertionError`."""
    return wait_template_mail(mailpit, to, TEMPLATE_ITEM, seen=seen, timeout=timeout)


def no_item_mail(mailpit, to: str, *, seen=(), wait: float = 4.0) -> bool:
    """True, если за `wait` секунд нового письма `notify.item` на `to` нет. Звать **после** `tick(...)` и ожидания
    результата другого канала: письмо, которое уже поставлено, дойдёт за секунды."""
    return no_template_mail(mailpit, to, TEMPLATE_ITEM, seen=seen, wait=wait)


def wait_digest_mail(mailpit, to: str, *, seen=(), timeout: float = 60.0) -> dict:
    """Новое письмо `notify.digest` (сводка за нерабочее время) на `to`: полный текст Mailpit. Не пришло —
    `AssertionError`."""
    return wait_template_mail(mailpit, to, TEMPLATE_DIGEST, seen=seen, timeout=timeout)


def no_digest_mail(mailpit, to: str, *, seen=(), wait: float = 4.0) -> bool:
    """True, если за `wait` секунд нового письма `notify.digest` на `to` нет."""
    return no_template_mail(mailpit, to, TEMPLATE_DIGEST, seen=seen, wait=wait)


def open_link_in(message: dict) -> str:
    """Ссылка «Открыть: <PORTAL_URL>/notifications/<id>/open/» из текста письма `notify.item` (§ 10.2, строка 5).
    Нет ссылки — `AssertionError`."""
    found = re.search(r"https?://[^\s\"'<>]+/notifications/\d+/open/", message["Text"])
    if not found:
        raise AssertionError("в письме нет ссылки вида …/notifications/<номер>/open/")
    return found.group(0)


# --- Каналы и привязки для тестов внешних каналов (§ 13.2, § 13.3, § 14.3, § 14.4, § 15.3) -----------------

SETTINGS_SAVED = "Настройки уведомлений сохранены."  # [role=status] после сохранения страницы администратора (§ 15.4)
BOUND_REPLY = {"telegram": "Telegram привязан", "max": "MAX привязан"}  # начало ответа бота «bound» (§ 15.3)


def _settings_form(page):
    page.goto("/settings/notifications/")
    form = page.locator('form[data-form="notify-settings"]')
    expect(form).to_be_visible()
    return form


def _channel_switch(form, channel: str):
    return form.locator(f'input[type=checkbox][name="{channel}_enabled"]')


def _save_channels(page, states: dict) -> None:
    """Страница администратора: переключатели из `states` (`{канал: bool}`) ставятся, остальные не трогаются; кнопка
    сохранения (§ 14.4). Отказ (`[data-error][data-code]`, § 13.3 — например `keys_missing`) — `AssertionError` с
    кодом (значений ключей на странице нет); успех — `[role=status]` «Настройки уведомлений сохранены.» и сохранённые
    значения переключателей."""
    form = _settings_form(page)
    for channel, state in states.items():
        _channel_switch(form, channel).set_checked(state)
    with page.expect_navigation():
        form.locator('button[type=submit][data-action="save-settings"]').click()
    page.wait_for_load_state()
    refusals = page.locator("[data-error][data-code]")
    if refusals.count():
        codes = [f'{r.get_attribute("data-error")}={r.get_attribute("data-code")}' for r in refusals.all()]
        raise AssertionError(f"настройки каналов не сохранены, отказ: {', '.join(codes)}")
    expect(page.locator("[role=status]").filter(has_text=SETTINGS_SAVED).first).to_be_visible()
    form = page.locator('form[data-form="notify-settings"]')
    for channel, state in states.items():
        expect(_channel_switch(form, channel)).to_be_checked(checked=state)


@contextlib.contextmanager
def channels_on(admin_page, *channels):
    """Администратор включает каналы `channels` (из `telegram`, `max`, `webpush`) на время блока `with`; на выходе
    (`finally`) переключатели возвращаются к прежним значениям, прочитанным до изменения. Страница
    `/settings/notifications/`, форма `notify-settings`, кнопка `save-settings` (§ 13.3, § 14.4); ждёт «Настройки
    уведомлений сохранены.». Отказ `keys_missing` (ключей канала на стенде нет, § 13.3) — `AssertionError` с кодом.
    Уже включённый канал не трогается. Страница `admin_page` на время блока используется помощником; внутри блока её
    можно использовать как обычно."""
    wanted = list(dict.fromkeys(channels))
    unknown = [c for c in wanted if c not in ADMIN_CHANNELS]
    if unknown or not wanted:
        raise ValueError(f"channels_on: нужны каналы из {ADMIN_CHANNELS}, получено {channels!r}")
    form = _settings_form(admin_page)
    before = {c: _channel_switch(form, c).is_checked() for c in wanted}
    to_switch = [c for c in wanted if not before[c]]
    try:
        if to_switch:
            _save_channels(admin_page, {c: True for c in to_switch})
        yield
    finally:
        if to_switch:
            _save_channels(admin_page, {c: False for c in to_switch})


def bind_channel(page, bots: FakeBots, channel: str, chat_id, *, timeout: float = 120.0) -> None:
    """Привязывает бота `channel` (`telegram` или `max`) к сотруднику страницы `page` кодом, как делает человек (§ 13.2,
    § 14.3, § 6.14, § 15.3): на `/me/notifications/` нажимает «Привязать» в `#notify-binding-<канал>`, читает
    `[data-bind-code]`, кладёт в `fakebots` события (Telegram: `/start` из личного чата, затем сообщение с кодом; MAX:
    `bot_started`, затем `message_created` с кодом, § 1.2), ждёт ответа бота «… привязан …» в `sent(channel)` по своему
    `chat_id` и блока `[data-state="bound"]` после перезагрузки. `chat_id` — уникальное целое теста (то же значение —
    `from.id` и `user_id`); потом сообщения выбирают по нему (`sent_to`). Канал должен быть включён администратором
    (`channels_on`) и не привязан. Предел `timeout` — не меньше 120 с: цикл опроса выключенного канала спит `PAUSE_IDLE`
    = 60 с (§ 5.4), после включения канал начинает опрос не сразу. `fakebots()` внутри не сбрасывается: звать его до
    привязки. Код в сообщениях ошибок не печатается."""
    if channel not in BOT_CHANNELS:
        raise ValueError(f"канал {channel!r}: нужен один из {BOT_CHANNELS}")
    deadline = time.monotonic() + timeout
    page.goto("/me/notifications/")
    block = page.locator(f"#notify-binding-{channel}")
    expect(block).to_be_visible()
    state = block.get_attribute("data-state")
    if state != "unbound":
        raise AssertionError(f"блок привязки {channel}: состояние {state!r}, нужно 'unbound' "
                             f"(канал выключен администратором — channels_on; уже привязан — привязка не нужна)")
    block.locator('form[data-form="bind"] button[data-action="bind"]').click()
    code_node = page.locator(f"#notify-binding-{channel} [data-bind-code]")
    expect(code_node).to_have_count(1)
    code = code_node.inner_text().strip()
    if not re.fullmatch(r"\d{8}", code):
        raise AssertionError(f"код привязки {channel} не из восьми цифр")
    chat = int(chat_id)
    if channel == "telegram":
        chat_ref = {"id": chat, "type": "private"}
        bots.put_telegram([
            {"message": {"chat": chat_ref, "from": {"id": chat}, "text": "/start"}},
            {"message": {"chat": chat_ref, "from": {"id": chat}, "text": code}},
        ])
    else:
        bots.put_max([
            {"update_type": "bot_started", "chat_id": chat, "user": {"user_id": chat}},
            {"update_type": "message_created",
             "message": {"sender": {"user_id": chat}, "recipient": {"chat_id": chat, "chat_type": "dialog"},
                         "body": {"text": code}}},
        ])
    while not [m for m in sent_to(bots, channel, chat) if BOUND_REPLY[channel] in (m.get("text") or "")]:
        if time.monotonic() >= deadline:
            raise AssertionError(f"бот {channel} не ответил «{BOUND_REPLY[channel]} …» за {timeout:.0f} с "
                                 f"(получено сообщений в чат: {len(sent_to(bots, channel, chat))})")
        time.sleep(0.5)
    page.goto("/me/notifications/")
    expect(page.locator(f"#notify-binding-{channel}")).to_have_attribute("data-state", "bound", timeout=15_000)


def enable_push_on_device(page, *, timeout: float = 30.0) -> str:
    """Подписывает устройство на Web Push: на `/me/notifications/` нажимает `button[data-action="push-subscribe"]`
    (§ 14.3), ждёт нового `li[data-device]` в списке устройств и возвращает его номер (атрибут `data-device`, строка).
    Только в постоянном профиле `webpush_context()` (доп. 23 (б): в обычном контексте браузер подписку не выдаёт);
    до вызова — `grant_notifications(context)` (иначе `AssertionError`), Web Push включён (`channels_on("webpush")`)
    и у этого устройства ещё нет подписки (кнопка видна). Подписка нового профиля — первый push не раньше чем через
    несколько секунд (доп. 23 (г))."""
    page.goto("/me/notifications/")
    if notification_permission(page) != "granted":
        raise AssertionError("разрешение браузера на уведомления не выдано: grant_notifications(context) до подписки")
    devices = 'ul[data-devices] li[data-device]'
    known = page.eval_on_selector_all(devices, "nodes => nodes.map(n => n.dataset.device)")
    button = page.locator('button[type=button][data-action="push-subscribe"]')
    expect(button).to_be_visible()
    # ответ скрипту — JSON POST /me/notifications/push/ (§ 13.2); живого обновления списка контракт не обещает
    try:
        with page.expect_response(lambda r: r.request.method == "POST" and
                                  r.url.split("?")[0].endswith("/me/notifications/push/"),
                                  timeout=timeout * 1000) as info:
            button.click()
    except PlaywrightTimeout:
        raise AssertionError(f"подписка устройства не отправлена на портал за {timeout:.0f} с") from None
    response = info.value
    body = response.json() if response.status in (200, 400) else {}
    if response.status != 200 or body.get("ok") is not True or "id" not in body:
        raise AssertionError(f"портал не сохранил подписку: статус {response.status}, код {body.get('code')!r}")
    device = str(body["id"])
    if device in known:
        raise AssertionError("портал вернул номер уже известной подписки")
    page.goto("/me/notifications/")
    expect(page.locator(f'ul[data-devices] li[data-device="{device}"]')).to_have_count(1)
    return device
