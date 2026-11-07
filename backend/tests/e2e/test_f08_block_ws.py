"""T-7261/T-7262: регрессия контракта `block_ws` (CONTRACT-007: строка `block_ws`, решение 55 задач с поправками v7/v9; FR-628).

Сценарий приёмки f08 остаётся в `test_f08_live.py`; здесь проверяется только сам помощник:
- callback `BrowserContext.route_web_socket` завершается и не запирает dispatcher Playwright: прежний helper
  звал синхронный `ws.close()` прямо в callback — callback исполняется на event loop диспетчера и ждёт ответ
  `closePage`, который этот же loop должен доставить, — воспроизводимый тупик (диагностика
  `crm-work/slice007/stage3/browser-gate/focused-f08-no-ws-20261105-zItUEU/diagnosis.md`). Здесь после
  `block_ws` идут обычные синхронные вызовы Playwright, и тест доходит до конца (зависание — это RED);
- серверного соединения нет: маршрут без `connect_to_server()` на сервер не ходит, кадры сервера не приходят —
  `data-ws` ленты и колокольчика ни разу не становится «open»; изменения атрибута собирает MutationObserver
  со старта страницы (init-скрипт контекста), чтобы не пропустить и краткое состояние;
- страница видит закрытие: `#feed-live[data-ws="closed"]` — лента шлёт sync-кадр сразу после открытия
  (`htmx:wsOpen` в feed.js), закрытие доходит не позже ожидания; то же после перезагрузки — маршрут
  действует и на новые соединения;
- молчащий `/ws/notify/` остаётся page-side mock-open без серверных кадров: колокольчик сохраняет
  `data-ws="connecting"`, не `open` и не `closed`, до и после перезагрузки;
- полная главная содержит ровно один скрытый `#feed-new` с начальным счётчиком 0.
"""
from playwright.sync_api import expect

from tests.e2e import helpers_feed, helpers_org

_WS_STATES = """
window.__ws_states = [];
new MutationObserver(function (records) {
  for (var i = 0; i < records.length; i++) {
    var el = records[i].target;
    window.__ws_states.push((el.id || '') + '=' + (el.getAttribute('data-ws') || ''));
  }
}).observe(document, {childList: false, subtree: true, attributes: true,
                      attributeFilter: ['data-ws']});
"""


def test_block_ws_closes_socket_without_blocking_dispatcher_or_server_connection(employee, new_context):
    """Контракт `block_ws` (T-7261, FR-628): `/ws/feed/` и `/ws/notify/` перехватываются до соединения с
    сервером; соединение ленты закрывается на стороне страницы (`data-ws="closed"` не позже 5 с, «open» не
    бывает ни разу), dispatcher остаётся жив — страница отвечает обычными запросами и после перезагрузки."""
    account = employee(full_name=f"Безсокетов{helpers_org.unique_name('б')[2:]} Иван Иванович")
    context = new_context()
    helpers_feed.block_ws(context)          # до создания страниц (решение 55 задач)
    context.add_init_script(_WS_STATES)     # наблюдение data-ws с первой же страницы
    page = helpers_feed.open_feed(context, account, live=False)

    expect(page.locator("#feed-live")).to_have_attribute("data-ws", "closed", timeout=5_000)
    expect(page.locator("#notify-bell")).to_have_attribute("data-ws", "connecting")
    states = page.evaluate("() => window.__ws_states")
    assert "feed-live=closed" in states, f"закрытие соединения не дошло до страницы: {states!r}"
    assert not [s for s in states if s.endswith("=open")], f"было живое соединение с сервером: {states!r}"
    assert not [s for s in states if s.startswith("notify-bell=") and s != "notify-bell=connecting"], \
        f"перехваченный notify не остался connecting: {states!r}"
    # htmx ws events identify their owning ws-connect element in detail.elt.
    # Feed events must not touch the bell; notify events must retain its open/closed lifecycle.
    result = page.evaluate("""() => {
      const feed = document.getElementById('feed-live');
      const bell = document.getElementById('notify-bell');
      const emit = (name, elt) => document.dispatchEvent(new CustomEvent(name, {detail: {elt}}));
      emit('htmx:wsAfterMessage', feed);
      const afterFeedMessage = bell.getAttribute('data-ws');
      emit('htmx:wsClose', feed);
      const afterFeedClose = bell.getAttribute('data-ws');
      emit('htmx:wsAfterMessage', bell);
      const afterNotifyMessage = bell.getAttribute('data-ws');
      emit('htmx:wsClose', bell);
      const afterNotifyClose = bell.getAttribute('data-ws');
      return [afterFeedMessage, afterFeedClose, afterNotifyMessage, afterNotifyClose];
    }""")
    assert result == ["connecting", "connecting", "open", "closed"], \
        f"неверная фильтрация/lifecycle событий WebSocket: {result!r}"

    expect(page.locator("#feed-new")).to_have_count(1)
    expect(page.locator("#feed-new")).to_have_attribute("data-count", "0")
    expect(page.locator("#feed-new")).to_be_hidden()

    page.reload()  # новые соединения тоже перехватываются, dispatcher не заперт
    page.wait_for_load_state()
    expect(page.locator("#feed-live")).to_have_attribute("data-ws", "closed", timeout=5_000)
    expect(page.locator("#notify-bell")).to_have_attribute("data-ws", "connecting")
    assert not [s for s in page.evaluate("() => window.__ws_states") if s.endswith("=open")], \
        f"после перезагрузки пришёл кадр сервера: {page.evaluate('() => window.__ws_states')!r}"
    states = page.evaluate("() => window.__ws_states")
    assert not [s for s in states if s.startswith("notify-bell=") and s != "notify-bell=connecting"], \
        f"после перезагрузки notify не остался connecting: {states!r}"
    expect(page.locator("#feed-new")).to_have_count(1)
    expect(page.locator("#feed-new")).to_have_attribute("data-count", "0")
    expect(page.locator("#feed-new")).to_be_hidden()
