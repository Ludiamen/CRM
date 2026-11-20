# T-8302 — что нужно поправить по итогам приёмки (предложение, не применено)

Основание: прогон `run-before-T8302-20261119-074843-Pu2fP3` (1836 passed / 254 failed / 5 errors),
разбор по junit — в разделе «Приёмка Playwright (T-8302)» отчёта `docs/reviews/TASKS-008.md`.

## A. Помощник e2e: `start_dialog` читает тело 302 (151 падение)

`backend/tests/e2e/helpers_messenger.py::start_dialog`. Форма «Написать» — обычный POST; по CONTRACT-008 10.2
обычный POST даёт **302** на беседу, HTMX — 200. Помощник ждёт 200 и вызывает `response.text()`, Playwright
отвечает «Response body is unavailable for redirect responses».

```diff
     form.locator('textarea[name="text"]').first.fill(FIRST_TEXT)
-    with page.expect_response(lambda r: r.request.method == "POST"
-                              and r.url.split("?")[0].endswith("/messenger/chats/")) as info:
-        form.locator('button[type="submit"]').first.click()
-    html = info.value.text()
-    try:
-        page.wait_for_url(_CHAT_URL, timeout=PAGE_TIMEOUT)
-    except PlaywrightTimeoutError:
-        found = _CHAT_URL.search(html)
-        assert found, "после первого сообщения страница не перешла в беседу"
-        page.goto(f"/messenger/chats/{found.group(1)}/")
-        page.wait_for_load_state()
+    form.locator('button[type="submit"]').first.click()
+    page.wait_for_url(_CHAT_URL, timeout=PAGE_TIMEOUT)
     return int(_CHAT_URL.search(page.url).group(1))
```

Ожидания не ослабляются: номер чата берётся из адреса, переход в беседу проверяется тем же `wait_for_url`.
Заодно поправить докстроку («200 с фрагментом без смены адреса» → «302 на беседу, как обычный POST»).

## B. Помощник e2e: `[data-ws]` неоднозначен в `open_chat` (80 падений)

На странице беседы два узла с `data-ws`: беседа и колокольчик. Решение владельца 2026-11-18 — считать только
узел мессенджера. `open_messenger` на странице списка узла беседы не имеет (там только колокольчик), поэтому
меняется только `open_chat`:

```diff
-    expect(page.locator("[data-ws]")).to_have_attribute("data-ws", "open", timeout=PAGE_TIMEOUT)
+    expect(page.locator('[data-messenger-page="chat"] [data-ws]')).to_have_attribute(
+        "data-ws", "open", timeout=PAGE_TIMEOUT)
```

## C. Проверка m01: карточка собеседника, а не своя (4 падения)

`test_m01_dialog_is_one_for_pair_started_from_card_and_from_messenger` открывает `/staff/<writer.id>/` (свою
карточку) и ждёт кнопку «Написать», которой по контракту для себя нет.

```diff
-def _card_page(context, account: helpers.Account):
+def _card_page(context, account: helpers.Account, target: helpers.Account | None = None):
     """Страница карточки сотрудника `/staff/<id>/` с сессией `account` (`helpers_notify.adopt_session`)."""
     helpers_notify.adopt_session(context, account)
     page = context.new_page()
-    page.goto(f"/staff/{account.id}/")
+    page.goto(f"/staff/{(target or account).id}/")
     page.wait_for_load_state()
     return page
...
-    card = _card_page(new_context(), c.writer)
+    card = _card_page(new_context(), c.writer, c.peer)
```

## D. Продукт: фильтр и страницы вкладки «Уведомления» (4 падения e10)

`backend/templates/notify/_list_body.html`: у ссылок фильтра и страниц есть `hx-get` без `hx-target` — htmx
подменяет фрагмент **внутри самой ссылки** (на снимке «Все Все Непрочитанные» и список в навигации).
План («Вкладка «Уведомления»») требует HTMX только для смены фильтра и страницы; серверный тест
`test_notify_pages.py` (правка T-8007) ждёт `hx-get`; прежний e2e ждёт смену адреса.

```diff
-    <a data-filter="all" href="/notifications/" hx-get="/notifications/list/"…>Все</a>
-    <a data-filter="unread" href="/notifications/?f=unread" hx-get="/notifications/list/?f=unread"…>Непрочитанные</a>
+    <a data-filter="all" href="/notifications/" hx-get="/notifications/list/"
+       hx-target="[data-notify-list]" hx-swap="innerHTML"
+       hx-push-url="/messenger/notifications/"…>Все</a>
+    <a data-filter="unread" href="/notifications/?f=unread" hx-get="/notifications/list/?f=unread"
+       hx-target="[data-notify-list]" hx-swap="innerHTML"
+       hx-push-url="/messenger/notifications/?f=unread"…>Непрочитанные</a>
```

и то же для `a[data-page-prev]`/`a[data-page-next]` (`hx-push-url` с `page=<номер>`). Форма «Прочитать все» не
меняется: она отвечает `HX-Redirect`.

Риск: Playwright `wait_for_url` должен увидеть `history.pushState`; если нет — минимальная правка ожидания в
прежнем e2e (отдельное разрешение).

## E. Продукт: первая беседа на широком экране (FR-673, латентная проверка m12)

CONTRACT-008 10.1: «`/messenger/` … на широком экране первый чат»; CSS уже содержит сетку двух колонок для
`.messenger-page:not(.messenger-page-chat)`, но `page.html` рисует только список, поэтому вторая колонка пуста, а
`#messenger-messages` на странице списка отсутствует. Проверка `m12_wide_window_shows_list_and_chat_in_two_columns`
(и `open_messenger(live=True)`) этого не увидела только потому, что падала раньше — на A.

Варианты:
1. **Полноценная беседа справа** (рекомендуется): `views/pages.py::page` берёт первую строку списка,
   `members.get_chat` + `page_service.history` (тот же `_chat_context`), `page.html` включает `_chat.html` во
   вторую колонку. Отметку прочтения при показе списка **не ставить** (отклонение от «открытие беседы» —
   записать в решения), иначе любой заход в мессенджер обнулял бы счётчик первой беседы.
2. Только предпросмотр истории без формы и соединения — меньше кода, но это отклонение от «беседа открыта».
3. Принять как известный дефект (по образцу NFR-612 среза 007) и сузить проверку m12 — самое слабое.

## Повтор упавших (24 nodeid)

См. `retry/` — результаты приложены в отчёт после завершения.