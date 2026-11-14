"""T-7301-fixes: регрессии трёх подтверждённых дефектов прохода T-7301 (решение владельца 2026-11-13)
и дефекта формы правки `until`/`term` (решение владельца 2026-11-14, scope-edit-form.md).

Источники: `crm-work/slice007/stage4/t7301-fixes/scope.md`, `crm-work/slice007/stage4/t7301/F/report.md`
(разделы «oobErrorNoTarget», «FR-614», «360 px»), `docs/reviews/TASKS-007.md` → «Проход в браузере (T-7301)».
Версия 2 — по итогам RED-прогона на стенде (red-20261113-170015-AYTcHe, указания оркестратора):
гонки (тесты 1-2) не меняются (честный RED подтверждён), исправлена подготовка трёх остальных (см.
`report-tests-v2.md` в t7301-fixes). Версия 3 — по итогам RED v2 (red-20261113-174112-JDRLyy): тест
360 px переведён на детерминированный viewport 345 px вместо инъекции классической полосы (см.
`report-tests-v3.md`); гонки и OOB-тесты не меняются (честный RED подтверждён в v2). Версия 4 — по
итогам RED v3: viewport 345 в headless дефект не воспроизводит (right=318); замер 360 px переведён на
headed Chrome с окном 360×780 и фото автора — условия зонда оркестратора `tmp_probe_360_headed.py`
(см. `report-tests-v4.md`); остальные четыре теста не меняются (честный RED подтверждён в v2/v3).
Версия 5 — по итогам GREEN-прогона (green-20261113-193900-scu02X): в тестах 1-2 ослаблена ТОЛЬКО проверка
порядка гонки — событие `htmx:oobAfterSwap` приходит по каждому элементу settle (сокет и вставленный узел),
поэтому записей «frame» до «xhr» может быть больше одной; требуется `order.index('frame') < order.index('xhr')`.
Финальные проверки переноса, отсутствия дубля и правила «ниже кромки» не изменены (см.
`report-fix-v2.md`). Версия 6 — малая партия 2026-11-14 (`scope-edit-form.md`): добавлен тест 6 — форма
правки истёкшей важной записи, `input[name=until]` ниже `min` блокирует POST; после переключения term на
«Неделю» поле должно очищаться/выключаться, форма становиться валидной, «Сохранить» — давать POST 200
(см. `report-edit.md`); тесты 1-5 не изменены. Версия 7 — по ревью r2 (`review.md`, «Дополнение:
until»): добавлен тест 7 — переключение вида публикации с «Важное»+«До даты» на «Сообщение» обязано
сбрасывать required у скрытого `until` (иначе невидимое обязательное поле молча блокирует
«Опубликовать»), плюс контроль публикации важной записи с term=date и реальной датой (см.
`report-edit-v2.md`); тесты 1-6 не изменены.

1. **FR-614 (гонка WS/XHR).** Кадр WS `#feed-post-<id>-imp` приходит раньше ответа XHR «Прочитано»: кадр
   заменяет блок важного, кнопка отцепляется от DOM, обработчик переноса в `feed.js` (`htmx:beforeSwap`)
   выходит рано по связанности `source`, и штатная замена возвращает карточку в блок без кнопки. Порядок
   воспроизводится детерминированно: ответ XHR удерживается `page.route` + `route.fetch` + короткая задержка
   до `route.fulfill` — сервер рассылает кадр при фиксации прочтения, и браузер применяет его по своему
   WebSocket независимо от Python-стороны (в обработчике маршрута нет вызовов Page API — урок T-7261);
   фактический порядок «кадр → XHR» доказывает внутристраничный зонд `__raceOrder` (без сна-ожидания
   состояния). Требование scope: запись определяется по номеру из ответа и текущего DOM, правило «ниже
   кромки» (plan.md:462-463) не меняется, карточка не дублируется.
2. **`htmx:oobErrorNoTarget`.** Кадры OOB-delete (запись, комментарий — видимый у инициатора и старый вне
   показанных последних трёх) приходят на страницы, где цели уже нет: htmx 2.0.11 логирует console.error.
   Ловятся счётчиком событий `htmx:oobErrorNoTarget` (init-скрипт контекста, как в
   `test_f_dom_targets_regressions.py`) и слушателем консоли. Порядок кадров по соединению сохраняется,
   поэтому «кадр без цели уже обработан» утверждается после положительного сигнала — следующего кадра с
   целью (плашка, вставка комментария), приём f08, без снов. Штатные OOB (сброс формы, счётчик «Ленты»,
   плашка, liker-list, вставка комментария кадром, удаление кадром с целью) проверяются здесь же как
   контроли — они обязаны работать и до, и после правки. Нюансы разметки: новая запись НЕ вставляется в
   открытую ленту (только плашка — FR-627, f08 п.1), поэтому наблюдатель открывает ленту после публикации
   (узел стоит серверной разметкой); меню комментария с удалением есть только в серверной разметке
   (`_comments.html` → `_comment.html` передают can_edit/can_delete), а HTTP-ответ
   `_comment_response.html` и кадр `_frame_comment_content.html` вставляют комментарий без своего меню —
   удаление выполняется на свежеоткрытой странице (образец f07 `_delete_comment_through_card`).
3. **NFR-606 на 360 px.** В виде автора/модератора шапка записи с кнопками «Править»/«Удалить»
   (`div.feed-post-actions`) не укладывается: в настоящем Chrome (оконный режим) окно 360 px с вертикальной
   полосой даёт клиентскую ширину 345, и scrollWidth 346-356 > 345, правый край «Править» ≈347 (F-отчёт
   «360 px»; зонд оркестратора `tmp_probe_360_headed.py`). Дефект воспроизводится ТОЛЬКО в headed Chrome
   с окном 360 (классическая полоса сужает clientWidth) и при фото автора (3rem в шапке) с длинным ФИО;
   headless-контекст при viewport 345 даёт right=318 — дефекта нет (факты RED v2/v3). Поэтому замер делается
   в headed Chrome (`channel="chrome"`, `headless=False`, под xvfb-run; нет DISPLAY — явное падение, не skip)
   в контексте `viewport 360×780`, с входом `helpers.sign_in` и публикацией в том же окне. Проверяются
   `documentElement.scrollWidth <= clientWidth`, правый край каждого видимого `div.feed-post-actions` и его
   кнопок `<= clientWidth`, плюс precondition «полоса реально сузила clientWidth» — для ленты и карточки
   записи автора/модератора и карточки события автора со списком ответивших (px-01b, px-02b, px-09).
   Firefox-контроль — headed Firefox тем же способом (viewport 360; headed недоступен — headless): замер в
   его естественном clientWidth, требование то же.

RED на текущем коде: (1) и (2) падают в обоих кругах (подтверждено прогоном v2); (3) падает в headed Chrome
(chromium/edge/yandex-круги): scrollWidth 346-356 > clientWidth 345 и/или край «Править» 347 > 345;
firefox-круг — контроль (в Firefox clientWidth остаётся 360, содержимое ≈355 помещается — F-отчёт).
GREEN — после правок `feed.js`/`feed.css` (tests.diff → fix.diff партии): `flex-wrap: wrap` переносит блок
действий на свою строку, содержимое вписывается в 345. Существующие тесты, помощники и шаблоны не меняются;
локаторы — раздел 12 CONTRACT-007.
"""
import os
import re
import secrets
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org
from tests.e2e.helpers_feed import (
    MODERATE, POST_ALL, add_comment, answer, badge, important_ids, like, make_role, open_card, open_feed,
    post_ids, publish, publish_request, wait_badge, wait_banner,
)

WAIT_MS = 10_000        # кадры — норма 2 с (NFR-602), ожидание сигнала с запасом
# Задержка ответа «Прочитано» — механизм создания гонки «кадр раньше XHR», а не ожидание состояния: сервер
# рассылает кадр `#feed-post-<id>-imp` при фиксации прочтения (во время `route.fetch`), браузер применяет его
# по своему WebSocket независимо от Python-стороны, а ответ XHR удерживается до истечения задержки. Запас
# покрывает норму кадра 2 с (NFR-602, факт F-отчёта 0,2–1,5 с). Порядок «кадр → XHR» проверяется зондом
# `_RACE_PROBE`, а не временем, поэтому тест честный: если кадр опоздал, зонд это ловит.
FRAME_HOLD_S = 2.5

_OBSERVE_OOB = """
window.__oobErrors = [];
document.addEventListener('htmx:oobErrorNoTarget', function (event) {
  window.__oobErrors.push(String(event.detail && event.detail.target));
}, true);
"""


# --- Наблюдение консоли и событий (критерий T-7301 — чистая консоль) ------------------------------------------------

def _observe_oob(context):
    """Контекст со счётчиком событий `htmx:oobErrorNoTarget` (init-скрипт действует с первой страницы;
    после навигации счётчик страницы начинается заново — тесты пользуют это: до перезагрузки ошибок нет)."""
    context.add_init_script(_OBSERVE_OOB)
    return context


def _watch_console(page, sink: list):
    """Слушатель страницы (переживает навигацию): в `sink` — тексты console.error про `oobErrorNoTarget`
    и падения скриптов."""

    def on_console(message):
        if message.type == "error" and "oobErrorNoTarget" in message.text:
            sink.append(message.text)

    def on_pageerror(error):
        sink.append(f"pageerror: {error}")

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    return page


def _oob_errors(page) -> list:
    return page.evaluate("() => window.__oobErrors")


def _word(prefix: str = "Слово") -> str:
    return f"{prefix} {secrets.token_hex(4)}"


def _banner_link(page):
    return page.locator("#feed-new a").first


def _reload_live(page, url: str, root: str):
    """Заново открывает живую страницу (образец `open_feed`/`open_card`): серверная разметка, новое
    соединение, счётчики init-скрипта с нуля. Нужна, в частности, чтобы меню комментария (can_delete)
    было отрисовано сервером."""
    page.goto(url)
    page.wait_for_load_state()
    expect(page.locator(root)).to_be_visible()
    expect(page.locator('#feed-live[data-ws="open"]')).to_be_attached(timeout=20_000)
    return page


def _delete_post_via_dialog(page, post_id) -> None:
    """Удаление записи интерфейсом: кнопка меню (12.3), диалог подтверждения `dialog[data-feed-confirm]`
    (образец f07 `_delete_post_through_card`)."""
    card = page.locator(f"#feed-post-{post_id}")
    card.locator('button[data-action="post-delete"]').click()
    dialog = card.locator("dialog[data-feed-confirm]")
    expect(dialog).to_be_visible()
    with page.expect_response(
            lambda r: r.request.method == "POST" and f"/feed/{post_id}/delete/" in r.url) as info:
        dialog.locator('form[data-form="feed-post-delete"] button[type="submit"]').click()
    assert info.value.status == 200, f"удаление записи: статус {info.value.status}"


def _delete_comment(page, comment_id) -> None:
    """Удаление комментария из СЕРВЕРНОЙ разметки: кнопка меню (12.3) `button[data-action="comment-delete"]`
    — submit формы `form[data-form="feed-comment-delete"]` (К53, без подтверждения); образец f07
    `_delete_comment_through_card`. Вставки HTTP-ответом и кадрами своего меню не имеют."""
    button = page.locator(f"#c{comment_id} button[data-action='comment-delete']")
    expect(button).to_be_visible(timeout=WAIT_MS)
    with page.expect_response(
            lambda r: r.request.method == "POST" and f"/feed/comments/{comment_id}/delete/" in r.url) as info:
        button.click()
    assert info.value.status == 200, f"удаление комментария: статус {info.value.status}"


_RACE_PROBE = """
window.__raceOrder = [];
document.addEventListener('htmx:oobAfterSwap', function (event) {
  var target = event.detail && event.detail.target;
  if (target && typeof target.id === 'string' && /-imp$/.test(target.id)) {
    window.__raceOrder.push('frame');
  }
}, true);
document.addEventListener('htmx:beforeSwap', function (event) {
  var detail = event.detail || {};
  var elt = detail.requestConfig && detail.requestConfig.elt;
  if (elt && elt.matches && elt.matches('button[data-action="read"]')) {
    window.__raceOrder.push('xhr');
  }
}, true);
"""


def _hold_read_response(page, post_id):
    """Маршрут, задерживающий ответ `/feed/<post_id>/read/` на FRAME_HOLD_S: `route.fetch` выполняет запрос
    на стенде (сервер отмечает прочтение и рассылает кадр WS), затем ответ освобождается. Кадр приходит в
    браузер по его собственному соединению и применяется страницей во время задержки — порядок «кадр раньше
    XHR» детерминирован. В обработчике маршрута нет вызовов Page API (урок T-7261: вложенный синхронный вызов
    в callback запирает dispatcher Playwright) — только документированные `route.fetch`/`route.fulfill`."""

    def handle(route):
        response = route.fetch()
        time.sleep(FRAME_HOLD_S)
        route.fulfill(response=response)

    page.route(f"**/feed/{post_id}/read/", handle)


# --- 1. FR-614: кадр `#feed-post-<id>-imp` раньше ответа XHR ---------------------------------------------------------

def test_read_race_frame_before_xhr_response_moves_important_card_into_feed(admin_page, employee, new_context):
    """FR-614 (сц. 2 п. 3): «Прочитано» при кадре WS, пришедшем раньше ответа XHR, переносит карточку из
    блока важных в ленту по времени публикации — без перезагрузки, без дубля и без кнопки «Прочитано».

    На текущем коде обработчик `feed.js` выходит рано (кнопка отцеплена кадром, `source.closest(
    '#feed-important')` → null), и штатная замена возвращает карточку в блок — первое ожидание падает (RED)."""
    tag = secrets.token_hex(4)
    writer = employee(role=make_role(admin_page, [POST_ALL]), full_name=f"Автор{tag} Иван Иванович")
    reader = employee(full_name=f"Читатель{tag} Иван Иванович")

    writer_page = open_feed(new_context(), writer, live=False)
    important = publish(writer_page, _word("Важное гонка"), kind="important", term="week",
                        to=[("person", reader.full_name)])
    ordinary = publish(writer_page, _word("Обычная после важной"), to=[("person", reader.full_name)])

    page = open_feed(new_context(), reader)
    page.evaluate("() => { window.__no_reload = 1; }")
    page.evaluate(_RACE_PROBE)
    assert important in important_ids(page) and ordinary in post_ids(page), "записи не видны читателю до опыта"
    read_button = page.locator(f'#feed-post-{important}-imp button[data-action="read"]')
    expect(read_button).to_be_visible()

    _hold_read_response(page, important)
    read_button.click()
    expect(page.locator(f"#feed-list #feed-post-{important}")).to_be_visible(timeout=WAIT_MS)
    # Кадров до XHR может быть больше одного: htmx шлёт `htmx:oobAfterSwap` по каждому элементу settle
    # (сокет и вставленный узел), плюс возможен OOB из HTTP-ответа — важен порядок: первый «frame» раньше
    # «xhr» (гонка состоялась).
    race_order = page.evaluate("() => window.__raceOrder")
    assert "frame" in race_order and "xhr" in race_order and race_order.index("frame") < race_order.index("xhr"), (
        f"гонка «кадр раньше XHR» не воспроизведена: {race_order}")

    expect(page.locator(f"#feed-important #feed-post-{important}")).to_have_count(0)
    assert page.locator(f"#feed-post-{important}").count() == 1, "карточка продублирована"
    order = post_ids(page)
    assert order.index(ordinary) < order.index(important), "прочитанная запись встала не по времени публикации"
    expect(page.locator(f'#feed-post-{important}-imp button[data-action="read"]')).to_have_count(0)
    assert page.evaluate("() => window.__no_reload") == 1, "страница перезагружалась"
    print(f"t7301-fr614: post={important} moved=1 duplicates=0 reloads=0")


def test_read_race_below_fold_card_leaves_block_and_is_not_inserted(admin_page, employee, new_context):
    """FR-614, правило «ниже кромки» (plan.md:462-463) в условиях той же гонки: запись старее показанных в
    ленте — карточка уходит из блока важных и НЕ вставляется в ленту (её принесёт «Ещё записи»), дубля нет.
    Правило правкой не меняется; тест фиксирует его сохранность при кадре раньше ответа."""
    tag = secrets.token_hex(4)
    writer = employee(role=make_role(admin_page, [POST_ALL]), full_name=f"Автор{tag} Иван Иванович")
    reader = employee(full_name=f"Читатель{tag} Иван Иванович")

    writer_page = open_feed(new_context(), writer, live=False)
    important = publish(writer_page, _word("Важное ниже кромки"), kind="important", term="week",
                        to=[("person", reader.full_name)])
    # 21 запись новее важной: у читателя есть «Ещё записи», важная старее показанного края
    for n in range(21):
        publish_request(writer_page, kind="post", text=_word(f"Наполнитель {n}"), to=f"p{reader.id}")

    page = open_feed(new_context(), reader)
    page.evaluate(_RACE_PROBE)
    assert important in important_ids(page), "важная запись не в блоке до опыта"
    assert page.locator("a[data-feed-more]").count() == 1, "нет «Ещё записи» — кромка не воспроизведена"

    _hold_read_response(page, important)
    page.locator(f'#feed-post-{important}-imp button[data-action="read"]').click()
    expect(page.locator(f"#feed-important #feed-post-{important}")).to_have_count(0, timeout=WAIT_MS)
    # Порядок, как в тесте выше: кадров до XHR может быть несколько, важен первый «frame» раньше «xhr».
    race_order = page.evaluate("() => window.__raceOrder")
    assert "frame" in race_order and "xhr" in race_order and race_order.index("frame") < race_order.index("xhr"), (
        f"гонка «кадр раньше XHR» не воспроизведена: {race_order}")
    assert page.locator(f"#feed-post-{important}").count() == 0, (
        "запись старее показанных вставлена в ленту — правило «ниже кромки» нарушено")
    print(f"t7301-fr614-fold: post={important} left_block=1 inserted=0")


# --- 2. `htmx:oobErrorNoTarget`: кадры без цели ---------------------------------------------------------------------

def test_post_delete_by_initiator_logs_no_oob_error_while_regular_oob_keeps_working(admin_page, employee,
                                                                                    new_context):
    """Удаление записи инициатором: HTTP-ответ уже снял узел, кадр WS с тем же OOB-delete приходит на ту же
    страницу — на текущем коде htmx логирует `htmx:oobErrorNoTarget` (RED). Порядок кадров по соединению
    сохраняется, поэтому после сигналов (плашка и liker-list следующих записей) ошибок быть не должно.
    Наблюдатель открывает ленту ПОСЛЕ публикации (новая запись в открытую ленту не вставляется — только
    плашка, FR-627/f08 п.1): у него кадр удаления имеет цель и снимает узел штатно (контроль).
    Контроли штатных OOB (обязаны работать до и после правки): сброс формы публикации, счётчик «Ленты»,
    плашка «Новых записей», liker-list кадру с целью."""
    tag = secrets.token_hex(4)
    role = make_role(admin_page, [POST_ALL])
    deleter = employee(role=role, full_name=f"Удаляющий{tag} Иван Иванович")
    publisher = employee(role=role, full_name=f"Публикатор{tag} Иван Иванович")
    watcher = employee(full_name=f"Наблюдатель{tag} Иван Иванович")

    deleter_console, watcher_console = [], []
    deleter_page = _watch_console(open_feed(_observe_oob(new_context()), deleter), deleter_console)

    # Контроль: сброс формы публикации (OOB HTTP-ответа `#feed-form`)
    p1 = publish(deleter_page, _word("Запись под удаление"), to=[("person", watcher.full_name)])
    expect(deleter_page.locator('#feed-form textarea[name="text"]')).to_have_value("")

    # Наблюдатель открывает ленту после p1 — узел стоит серверной разметкой, кадр удаления придёт с целью
    watcher_page = _watch_console(open_feed(_observe_oob(new_context()), watcher), watcher_console)
    expect(watcher_page.locator(f"#feed-post-{p1}")).to_be_visible(timeout=WAIT_MS)

    _delete_post_via_dialog(deleter_page, p1)
    expect(deleter_page.locator(f"#feed-post-{p1}")).to_have_count(0)

    # Сигналы порядка кадров на сокете инициатора: плашка и счётчик p2, затем liker-list p3
    publisher_page = open_feed(new_context(), publisher, live=False)
    base_badge = badge(deleter_page)
    p2 = publish_request(publisher_page, kind="post", text=_word("Сигнальная первая"), to=f"p{deleter.id}")
    wait_banner(deleter_page, 1, timeout=WAIT_MS)                 # контроль: плашка (кадр с целью)
    wait_badge(deleter_page, base_badge + 1, timeout=WAIT_MS)     # контроль: счётчик «Ленты» (notify-сокет)
    p3 = publish_request(publisher_page, kind="post", text=_word("Сигнальная вторая"),
                         to=[f"p{deleter.id}", f"p{watcher.id}"])
    wait_banner(deleter_page, 2, timeout=WAIT_MS)
    _banner_link(deleter_page).click()
    expect(deleter_page.locator(f"#feed-post-{p3}")).to_be_visible()

    watcher_card = open_card(new_context(), watcher, p3)
    assert like(watcher_card, p3) is True
    expect(deleter_page.locator(f"#feed-post-{p3}-likers")).to_contain_text(
        watcher.full_name.split()[0], timeout=WAIT_MS)            # контроль: liker-list (кадр с целью)

    # К этому моменту кадр удаления p1 обработан на странице инициатора (порядок по соединению);
    # у наблюдателя тот же кадр пришёл с целью на месте — узел снят штатно (контроль).
    expect(watcher_page.locator(f"#feed-post-{p1}")).to_have_count(0)
    assert _oob_errors(deleter_page) == [], f"oobErrorNoTarget у инициатора: {_oob_errors(deleter_page)}"
    assert _oob_errors(watcher_page) == [], f"oobErrorNoTarget у наблюдателя: {_oob_errors(watcher_page)}"
    assert deleter_console == [], f"console.error у инициатора: {deleter_console}"
    assert watcher_console == [], f"console.error у наблюдателя: {watcher_console}"
    print(f"t7301-oob-post: deleted={p1} signals={p2},{p3} errors=0")


def test_comment_delete_visible_and_old_frames_log_no_oob_error_and_comment_oob_keeps_working(
        admin_page, employee, new_context):
    """Удаление комментария: (а) видимого у инициатора — HTTP-ответ снял `#c<id>`, кадр WS приходит без цели
    (карточка автора: c1; карточка коллеги: c2); (б) старого вне показанных последних трёх — у читателя узла
    не было вовсе (c1). На текущем коде оба случая дают `htmx:oobErrorNoTarget` (RED). Удаление — только из
    серверной разметки (свежеоткрытая/перезагруженная страница): HTTP-ответ `_comment_response.html` и кадр
    `_frame_comment_content.html` вставляют комментарий без своего меню (can_edit/can_delete передаёт лишь
    `_comments.html`), образец — f07 `_delete_comment_through_card`. Сигналы порядка кадров по соединению —
    последующие кадры с целью (вставка c5/c6/c7, снятие c2), приём f08. Контроли штатных OOB: снятие c1/c2
    кадрами у страниц, где цель есть; вставка комментариев кадрами; отсутствие дублей своих комментариев
    (решение 62 — `htmx:oobBeforeSwap` в feed.js: c5/c7 у автора, c6 у коллеги)."""
    tag = secrets.token_hex(4)
    author = employee(role=make_role(admin_page, [POST_ALL]), full_name=f"Комментатор{tag} Иван Иванович")
    colleague = employee(full_name=f"Коллега{tag} Иван Иванович")
    reader = employee(full_name=f"Читатель{tag} Иван Иванович")

    sinks = {"author": [], "colleague": [], "reader": []}
    author_ctx = _observe_oob(new_context())
    author_feed = _watch_console(open_feed(author_ctx, author), sinks["author"])
    post = publish(author_feed, _word("Запись с комментариями"),
                   to=[("person", colleague.full_name), ("person", reader.full_name)])

    # c1 — автор (на карточке); c2–c4 — коллега (в своей ленте). У вставленных ответом/кадрами
    # комментариев своего меню нет — удаления ниже делаются со свежей серверной разметки.
    card = _watch_console(open_card(author_ctx, author, post), sinks["author"])
    c1 = add_comment(card, post, _word("Комментарий 1"))
    colleague_ctx = _observe_oob(new_context())
    colleague_feed = _watch_console(open_feed(colleague_ctx, colleague), sinks["colleague"])
    expect(colleague_feed.locator(f"#c{c1}")).to_be_visible(timeout=WAIT_MS)
    c2, c3, c4 = (add_comment(colleague_feed, post, _word(f"Комментарий {n}")) for n in (2, 3, 4))

    # Лента читателя открывается после всех комментариев: показаны последние три (c2–c4), c1 на странице нет
    reader_page = _watch_console(open_feed(_observe_oob(new_context()), reader), sinks["reader"])
    expect(reader_page.locator(f"#c{c4}")).to_be_visible(timeout=WAIT_MS)
    expect(reader_page.locator(f"#c{c1}")).to_have_count(0)

    # (б) старый комментарий: автор удаляет c1 на СВЕЖЕЙ карточке (серверное меню). Кадр без цели — у
    # карточки автора и у читателя; лента автора и лента коллеги цель имеют — штатное снятие (контроль).
    card = _reload_live(card, f"/feed/{post}/", '[data-feed-page="card"]')
    _delete_comment(card, c1)
    expect(card.locator(f"#c{c1}")).to_have_count(0)
    c5 = add_comment(card, post, _word("Комментарий 5"))
    expect(colleague_feed.locator(f"#c{c5}")).to_be_visible(timeout=WAIT_MS)
    expect(reader_page.locator(f"#c{c5}")).to_be_visible(timeout=WAIT_MS)   # сигнал: читатель обработал c1-кадр
    expect(author_feed.locator(f"#c{c5}")).to_be_visible(timeout=WAIT_MS)
    expect(colleague_feed.locator(f"#c{c1}")).to_have_count(0)              # контроль: снятие кадром с целью
    expect(author_feed.locator(f"#c{c1}")).to_have_count(0)

    # (а) видимый комментарий: коллега удаляет свой c2 на СВОЕЙ свежей карточке — кадр без цели у неё;
    # лента коллеги, карточка и лента автора цель имеют — штатное снятие (контроль)
    colleague_card = _watch_console(open_card(colleague_ctx, colleague, post), sinks["colleague"])
    _delete_comment(colleague_card, c2)
    expect(colleague_card.locator(f"#c{c2}")).to_have_count(0)
    c6 = add_comment(colleague_card, post, _word("Комментарий 6"))          # своя — на карточке один раз (решение 62)
    expect(card.locator(f"#c{c6}")).to_be_visible(timeout=WAIT_MS)          # сигнал: карточка автора обработала c2-кадр
    expect(card.locator(f"#c{c2}")).to_have_count(0)                        # контроль: снятие кадром с целью
    expect(author_feed.locator(f"#c{c6}")).to_be_visible(timeout=WAIT_MS)
    expect(colleague_feed.locator(f"#c{c6}")).to_be_visible(timeout=WAIT_MS)
    expect(colleague_feed.locator(f"#c{c2}")).to_have_count(0)              # контроль
    expect(reader_page.locator(f"#c{c6}")).to_be_visible(timeout=WAIT_MS)
    expect(reader_page.locator(f"#c{c2}")).to_have_count(0)                 # контроль
    c7 = add_comment(card, post, _word("Комментарий 7"))                    # сигнал: карточка коллеги после c2-кадра
    expect(colleague_card.locator(f"#c{c7}")).to_be_visible(timeout=WAIT_MS)
    expect(reader_page.locator(f"#c{c7}")).to_be_visible(timeout=WAIT_MS)

    pages = ((card, "карточка автора"), (author_feed, "лента автора"),
             (colleague_card, "карточка коллеги"), (colleague_feed, "лента коллеги"),
             (reader_page, "лента читателя"))
    for page_, label in pages:
        assert _oob_errors(page_) == [], f"oobErrorNoTarget ({label}): {_oob_errors(page_)}"
    for name, sink in sinks.items():
        assert sink == [], f"console.error ({name}): {sink}"
    # Нет дублей: свои комментарии вставлены ответом, повторный кадр отменён решением 62; чужие приходят
    # кадрами ровно один раз. Проверка заодно фиксирует: все кадры (включая удалительные) дошли до страниц.
    for page_, label in pages:
        for cid in (c3, c4, c5, c6, c7):
            assert page_.locator(f"#c{cid}").count() == 1, f"{label}: #c{cid} не один раз"
    print(f"t7301-oob-comment: post={post} deleted={c1},{c2} errors=0 duplicates=0")


# --- 3. NFR-606: 360 px в виде автора и модератора -------------------------------------------------------------------

def _moscow_now() -> datetime:
    return datetime.now(ZoneInfo("Europe/Moscow"))


# Условия воспроизведения дефекта (F-отчёт «360 px» + зонд оркестратора tmp_probe_360_headed.py):
# НАСТОЯЩИЙ headed Chrome, окно 360×780 — классическая вертикальная полоса сужает clientWidth до 345;
# автор с фото (3rem в шапке записи) и длинным ФИО. Замер зонда: clientWidth=345, scrollWidth=346/347,
# правый край «Править» 347 > 345. Headless-контекст при viewport 345 даёт right=318 — дефект не
# воспроизводится (факт RED v3), поэтому v4 меряет только в headed-браузере (запуск под xvfb-run).
_WINDOW_360 = {"width": 360, "height": 780}

_MEASURE_360 = """() => {
  const de = document.documentElement;
  let actionsRight = 0;
  let buttonRight = 0;
  for (const el of document.querySelectorAll('div.feed-post-actions')) {
    const rect = el.getBoundingClientRect();
    if (rect.width > 0) { actionsRight = Math.max(actionsRight, Math.ceil(rect.right + window.scrollX)); }
    for (const button of el.querySelectorAll('button')) {
      const rb = button.getBoundingClientRect();
      if (rb.width > 0 && rb.height > 0) {
        buttonRight = Math.max(buttonRight, Math.ceil(rb.right + window.scrollX));
      }
    }
  }
  return {scrollWidth: de.scrollWidth, clientWidth: de.clientWidth, innerWidth: window.innerWidth,
          actionsRight: actionsRight, buttonRight: buttonRight};
}"""


def _launch_headed_browser(playwright, project: str):
    """Headed-браузер замера 360 px. Firefox-круг — headed Firefox (контроль; headed недоступен — headless,
    роль контроля это допускает). Прочие круги — настоящий Chrome (`channel="chrome"`, headed): именно он
    воспроизводит дефект (окно 360 → классическая полоса → clientWidth 345); headless Chromium дефект не
    показывает (факт RED v3), поэтому запасного headless-хода для Chrome нет — сбой запуска означает явное
    падение теста, не тихий пропуск."""
    if project == "firefox":
        try:
            return playwright.firefox.launch(headless=False), "firefox-headed"
        except Exception:
            return playwright.firefox.launch(headless=True), "firefox-headless"
    try:
        return playwright.chromium.launch(channel="chrome", headless=False), "chrome-headed"
    except Exception as exc:
        pytest.fail(f"headed Chrome (channel='chrome') не запустился: {exc}. Нужны настоящий Chrome и "
                    f"X-дисплей (запуск под xvfb-run) — без них дефект NFR-606 не воспроизводится")


def _measure_no_hscroll(page, what: str, *, classic_scrollbar: bool) -> dict:
    """Замер в окне 360×780 (NFR-606): горизонтальной прокрутки нет — `documentElement.scrollWidth <=
    clientWidth` (формула `helpers.no_horizontal_scroll`) и правый край каждого видимого
    `div.feed-post-actions` и его кнопок `<= clientWidth` (корень дефекта: «Править»/«Удалить» доходят до
    x=347-355 при clientWidth 345). `classic_scrollbar` (круги chromium/edge/yandex, headed Chrome) —
    precondition: вертикальная полоса реально сузила clientWidth (345 < 360), иначе условие дефекта не
    воспроизведено; Firefox меряется в своём естественном clientWidth (F-отчёт: остаётся 360)."""
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    m = page.evaluate(_MEASURE_360)
    assert m["innerWidth"] == _WINDOW_360["width"], (
        f"{what}: ширина окна не 360 (innerWidth {m['innerWidth']})")
    if classic_scrollbar:
        assert m["clientWidth"] < m["innerWidth"], (
            f"{what}: вертикальная полоса не сузила clientWidth (clientWidth == innerWidth == "
            f"{m['innerWidth']}) — условие дефекта (окно 360 настоящего Chrome) не воспроизведено: "
            "нужны headed Chrome под xvfb-run и страница выше окна 780")
    assert m["scrollWidth"] <= m["clientWidth"], (
        f"{what}: горизонтальная прокрутка — scrollWidth {m['scrollWidth']} > clientWidth "
        f"{m['clientWidth']} (NFR-606)")
    assert m["actionsRight"] <= m["clientWidth"], (
        f"{what}: правый край div.feed-post-actions {m['actionsRight']} px > clientWidth "
        f"{m['clientWidth']} px (NFR-606)")
    assert m["buttonRight"] <= m["clientWidth"], (
        f"{what}: правый край кнопки «Править»/«Удалить» {m['buttonRight']} px > clientWidth "
        f"{m['clientWidth']} px (NFR-606, дефект шапки записи в виде автора/модератора)")
    return m


def test_feed_and_card_author_and_moderator_views_have_no_horizontal_scroll_at_360(
        admin_page, employee, new_context, playwright, browser, browser_context_args):
    """NFR-606 (сц. 14 п. 3, перечень плана): лента и карточка записи в виде автора/модератора на 360 px без
    горизонтальной прокрутки. Замер — в настоящем headed Chrome с окном 360×780 (firefox-круг — headed
    Firefox, контроль): только там классическая полоса сужает clientWidth до 345 и дефект воспроизводится
    (зонд оркестратора: scrollWidth 346/347, «Править» right=347 > 345; headless при viewport 345 даёт
    right=318 — PASS v3 был ложным). Условие воспроизведения — фото автора (3rem в шапке) и длинное ФИО;
    страницы выше окна (комментарии) — полоса присутствует. Проверяются: лента автора, карточка записи
    автора, лента и карточка модератора, карточка события автора со списком ответивших (px-01b, px-02b,
    px-09). Вид автора/модератора подтверждается наличием `div.feed-post-actions` до замера. Нет DISPLAY —
    явное падение «нужен xvfb», не skip."""
    headed_firefox = browser.e2e_project == "firefox"
    if not headed_firefox and sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        pytest.fail("нужен xvfb: headed Chrome для замера 360 px требует X-дисплей — DISPLAY не задан "
                    "(запускайте e2e под xvfb-run)")

    tag = secrets.token_hex(4)
    writer = employee(role=make_role(admin_page, [POST_ALL]), full_name=f"Узкописец{tag} Иван Иванович")
    moderator = employee(role=make_role(admin_page, [MODERATE]), full_name=f"Узкомодер{tag} Иван Иванович")

    # Фото автора — часть условия воспроизведения (3rem в шапке записи): форма /me/photo/ на своей странице,
    # проверка ClamAV стенда обязательна (иначе фото в шапке не появится)
    me = writer.page
    me.goto("/me/")
    with me.expect_response(lambda r: r.request.method == "POST" and r.url.rstrip("/").endswith("/me/photo")):
        helpers_org.upload_file(me.locator('form[action="/me/photo/"]'), helpers.make_png(300, 300),
                                field="photo", name="photo.png", mime="image/png")
    assert helpers_org.wait_photo_checked(me, "/me/") == "clean", (
        "фото автора не принято стендом — условие воспроизведения NFR-606 не собрано")

    headed, flavor = _launch_headed_browser(playwright, browser.e2e_project)
    classic = not headed_firefox
    try:
        # Автор: вход и публикация в том же headed-окне 360×780 (условия зонда оркестратора)
        context = headed.new_context(**{**browser_context_args, "viewport": _WINDOW_360})
        page = context.new_page()
        helpers.sign_in(page, writer)
        page.goto("/")
        page.wait_for_load_state()
        expect(page.locator('[data-feed-page="home"]')).to_be_visible()

        long_text = "Узкая лента " + "ж" * 80 + " " + _word()
        post = publish(page, long_text, to=[("person", moderator.full_name)])
        start = _moscow_now() + timedelta(minutes=180)
        event = publish(page, _word("Событие узкое"), kind="event", to=[("person", moderator.full_name)],
                        event={"title": "Название события " + "ж" * 40, "place": "Место " + "м" * 40,
                               "start": start, "end": start + timedelta(minutes=120)})
        # Страницы выше окна 780 — вертикальная полоса (в headed Chrome она сужает clientWidth до 345)
        for n in range(6):
            add_comment(page, post, _word(f"Комментарий узкий {n}"))
        for n in range(4):
            add_comment(page, event, _word(f"Комментарий события {n}"))

        # Вид автора: лента и карточка записи
        expect(page.locator(f"#feed-post-{post} div.feed-post-actions")).to_have_count(1)
        _measure_no_hscroll(page, f"лента, вид автора ({flavor})", classic_scrollbar=classic)
        page.goto(f"/feed/{post}/")
        page.wait_for_load_state()
        expect(page.locator('[data-feed-page="card"]')).to_be_visible()
        expect(page.locator(f"#feed-post-{post} div.feed-post-actions")).to_have_count(1)
        _measure_no_hscroll(page, f"карточка записи, вид автора ({flavor})", classic_scrollbar=classic)

        # Вид модератора: отдельная сессия в том же headed-браузере
        mod_context = headed.new_context(**{**browser_context_args, "viewport": _WINDOW_360})
        mod_page = mod_context.new_page()
        helpers.sign_in(mod_page, moderator)
        mod_page.goto("/")
        mod_page.wait_for_load_state()
        expect(mod_page.locator(f"#feed-post-{post} div.feed-post-actions")).to_have_count(1)
        _measure_no_hscroll(mod_page, f"лента, вид модератора ({flavor})", classic_scrollbar=classic)
        mod_page.goto(f"/feed/{post}/")
        mod_page.wait_for_load_state()
        expect(mod_page.locator(f"#feed-post-{post} div.feed-post-actions")).to_have_count(1)
        _measure_no_hscroll(mod_page, f"карточка записи, вид модератора ({flavor})", classic_scrollbar=classic)

        # Карточка события автора со списком ответивших (px-09): модератор отвечает «Пойду»
        mod_page.goto(f"/feed/{event}/")
        mod_page.wait_for_load_state()
        answer(mod_page, event, "go")
        page.goto(f"/feed/{event}/")
        page.wait_for_load_state()
        expect(page.locator('[data-feed-answers-count="go"]')).to_contain_text("1")
        page.locator("a[data-feed-answers-link]").click()
        expect(page.locator('[data-feed-list="answers"]')).to_be_visible()
        expect(page.locator(f"#feed-post-{event} div.feed-post-actions")).to_have_count(1)
        _measure_no_hscroll(page, f"карточка события со списком ответивших, вид автора ({flavor})",
                            classic_scrollbar=classic)
        print(f"t7301-360: browser={flavor} checks=5 views=author,moderator,event scroll=0")
    finally:
        headed.close()


# --- 4. Форма правки: устаревший `until` ниже `min` блокирует POST (scope-edit-form.md) --------------------------------

def test_edit_form_stale_until_below_min_is_cleared_on_term_switch_and_post_succeeds(admin_page, employee,
                                                                                     new_context):
    """Дефект перед закрытием T-7301 (решение владельца 2026-11-14, scope-edit-form.md): форма правки
    важной записи оставляет `input[name=until]` со значением ниже `min`, и при переключении срока на
    «Неделю» поле не очищается — HTML5-валидация блокирует POST («Сохранить» не работает; сервер при
    term != date `until` не читает). Воспроизведение детерминированное, без shift/age: устаревшая дата
    ставится page.evaluate (для браузерной проверки этого достаточно — значение ниже min делает форму
    невалидной). После правки (feed.js синхронизирует поле с term): term != date → значение очищено, disabled, не
    required; форма валидна; «Сохранить» даёт POST 200 без отказов. На текущем коде RED падает уже на
    состоянии поля (POST не ушёл бы — нативная валидация не пускает submit)."""
    tag = secrets.token_hex(4)
    writer = employee(role=make_role(admin_page, [POST_ALL]), full_name=f"Правщик{tag} Иван Иванович")
    page = open_feed(new_context(), writer, live=False)
    post = publish(page, _word("Важное на неделю правка"), kind="important", term="week")

    page.goto(f"/feed/{post}/edit/")
    page.wait_for_load_state()
    expect(page.locator('[data-feed-page="edit"]')).to_be_visible()
    form = page.locator('form[data-form="feed-post-edit"]')
    expect(form).to_have_count(1)
    until = form.locator('input[name="until"]')
    expect(until).to_have_count(1)

    # Форма правки важной записи: term=date, until ≈ +6 дней (валидно). Имитируем истёкший срок —
    # значение ниже min (как после shift/age в профиле f02, только детерминированно):
    until.evaluate("el => { el.value = '2020-01-01'; }")
    assert form.evaluate("el => el.checkValidity()") is False, (
        "форма с until ниже min ожидалась невалидной — условие воспроизведения не собрано")

    # Переключение «До даты» → «Неделя»: поле очищено и выключено, форма валидна
    helpers_org.set_choice(form, "term", "week")
    state_after = until.evaluate("el => ({value: el.value, disabled: el.disabled, required: el.required})")
    assert state_after == {"value": "", "disabled": True, "required": False}, (
        f"ДЕФЕКТ r2: until не синхронизировано после переключения term: {state_after}")
    assert form.evaluate("el => el.checkValidity()") is True, "форма осталась невалидной после переключения term"

    # «Сохранить»: POST уходит и завершается успешно (на текущем коде до этого не доходит — валидация блокирует)
    with page.expect_response(
            lambda r: r.request.method == "POST" and f"/feed/{post}/edit/" in r.url, timeout=WAIT_MS) as info:
        form.locator('button[type="submit"]').first.click()
    assert info.value.status == 200, f"сохранение: статус {info.value.status}"
    body = info.value.text()
    assert "data-code=" not in body, f"сохранение отклонено: {body[:200]}"
    assert f'data-post-id="{post}"' in body, "в ответе нет исправленной записи"
    print(f"t7301-edit-form: post={post} cleared=1 disabled=1 post=200")


def test_publish_form_kind_switch_from_important_date_clears_required_until_and_post_succeeds(
        admin_page, employee, new_context):
    """Ревью r2 (`review.md`, «Дополнение: until»): невидимое required-поле не должно блокировать
    публикацию. Поток: «Важное» → срок «До даты» (until enabled+required, пусто) → вид переключён на
    «Сообщение» (блок полей вида скрыт d-none) → текст → «Опубликовать». На коде r2 until остаётся
    required — нативная валидация молча блокирует submit и POST не уходит (RED); после правки
    (`syncUntilField` учитывает kind) поле очищено/disabled, POST 200 создаёт запись. Контроль: важная
    запись с term=date и реальной датой публикуется штатно."""
    tag = secrets.token_hex(4)
    writer = employee(role=make_role(admin_page, [POST_ALL]), full_name=f"Видовик{tag} Иван Иванович")
    page = open_feed(new_context(), writer, live=False)
    form = page.locator("form#feed-form")
    expect(form).to_be_visible()
    until = form.locator('input[name="until"]')

    # «Важное» → «До даты»: поле включено и обязательно (пусто)
    form.locator('label:has(input[name="kind"][value="important"])').click()
    helpers_org.set_choice(form, "term", "date")
    state_date = until.evaluate("el => ({disabled: el.disabled, required: el.required})")
    assert state_date == {"disabled": False, "required": True}, (
        f"kind=important+term=date: неожиданное состояние until: {state_date}")

    # Вид «Сообщение»: until очищено и выключено — невидимого required-поля больше нет
    form.locator('label:has(input[name="kind"][value="post"])').click()
    state_post = until.evaluate("el => ({value: el.value, disabled: el.disabled, required: el.required})")
    assert state_post == {"value": "", "disabled": True, "required": False}, (
        f"ДЕФЕКТ r3: после переключения вида на «Сообщение» required until не сброшен: {state_post}")
    assert form.evaluate("el => el.checkValidity()") is True, (
        "форма невалидна: невидимое обязательное поле блокирует отправку")

    # «Опубликовать»: POST уходит и создаёт запись (на коде r2 до POST не доходит — валидация блокирует)
    form.locator('textarea[name="text"]').fill(_word("Обычная после важного черновика"))
    with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.rstrip("/").endswith("/feed/posts"),
            timeout=WAIT_MS) as info:
        form.locator('button[type="submit"]').click()
    assert info.value.status == 200, f"публикация: статус {info.value.status}"
    body = info.value.text()
    assert "data-code=" not in body, f"публикация отклонена: {body[:200]}"
    created = re.search(r'data-post-id="(\d+)"', body)
    assert created, "в ответе нет созданной записи"
    expect(page.locator(f"#feed-post-{created.group(1)}").first).to_be_visible()

    # Контроль: важная запись с term=date и реальной датой (завтра) публикуется штатно
    tomorrow = (_moscow_now() + timedelta(days=1)).date()
    important = publish(page, _word("Важное до даты контроль"), kind="important", term="date",
                        until=tomorrow)
    expect(page.locator(f"#feed-post-{important}-imp")).to_be_visible()
    print(f"t7301-kind-switch: post={created.group(1)} important={important} blocked=0")
