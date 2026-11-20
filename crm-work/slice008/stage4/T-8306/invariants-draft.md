# T-8306 — проверка инвариантов по диффу среза 008 (черновик, до отчёта)

Диапазон диффа: `1f216a9..HEAD` (подписанные TASKS-008 → текущее дерево), срез 008.
Работа только на чтение кода и тестов; прогоны — T-8300 (сервер), T-8302 (браузер).

## 1. «Модуль-приложение»

| Проверка | Факт | Чем доказано |
|---|---|---|
| `apps.messenger` не импортирует модели `org`, `notify`, `feed` | нет ни одного импорта `apps.*.models` и `apps.feed` | `grep` по `apps/messenger/**`; `test_messenger_boundaries.py::test_messenger_does_not_import_org_notify_feed_models` |
| из `org` — только публичная служба `structure` | 7 мест, каждое под `apps.is_installed("apps.org")`, локальный импорт | `views/chats.py:251`, `services/{department,mentions,page,members,unread,search,chats,retention}.py` |
| из `notify` — `dispatch.create` и `live.group` | `services/messages.py:112`, `services/live.py:158`, локально под `is_installed` | те же |
| из `notify` — ещё `services.pages` | **новая зависимость** (`views/notifications.py:13`): общая служба потока для вкладки «Уведомления» (`list_context`: фильтр, 50, названия видов) | план, стр. 33 «публичными службами core, org и notify» + стр. 470 (то же тело `notify/_list_body.html`); тест границ явно допускает `NOTIFY_PAGES` (`test_messenger_boundaries.py:26,244`). Отклонение от узкой формулировки плана (стр. 59: только `dispatch.create`/`live.group`) — записать как принятое уточнение |
| прежние приложения не импортируют `apps.messenger` | нет импортов; `org/views/structure_forms.py` только имя журнала строкой, `notify/views/pages.py` — `apps.is_installed("apps.messenger")` | `test_org_and_notify_import_no_messenger` |
| 19 точек, `unit_form_parts` последняя | `POINTS` — 19, последняя `unit_form_parts` | `apps/core/extensions.py:18`; `test_extensions.py`, `test_feed_core_changes*.py` |
| регистрации мессенджера — 8 точек | `menu_items`, `card_sections`, `notification_kinds`, `search_providers`, `file_purposes`, `audit_labels`, `unit_form_parts`, `stand_reset` (последней) | `apps/messenger/extensions.py:37–56` |
| `top_bar_items` мессенджер не регистрирует и не читает | нет | `extensions.py`; колокольчик — `notify` + `bell_link` (`notify/views/pages.py:129`) |
| `is_installed` у маршрутов, ASGI, cron | `config/urls.py:18`, `config/asgi.py:30`, `config/cron.py:79` | чтение |
| миграции: `core/0011`, `messenger/0001`, `messenger/0002` | есть; `Purpose.MESSENGER` в конце | `apps/core/models/files.py`, `apps/core/migrations/0011_*` |

## 2. «Настройка-без-кода»

- Срок хранения — данные: `MessengerSettings.retention_years` (1…10, по умолчанию 3), читается
  `services/retention.py:44` и `services/messenger_settings.py`; в коде нет порога «3 года».
- «Общий чат» — данные: `general_chat_enabled`, читается `services/chats.py:311–314`
  (`_general_enabled()` → параметр SQL `chats.py:234`).
- Каналы уведомлений — данные `notify` (значения по умолчанию `portal`, `email` у двух видов;
  `notify_kinds.py`), не код мессенджера.

## 3. «Интеграции-через-адаптеры»

- ClamAV: в `apps/messenger` нет `clamd`/`clamav` — проверка приходит через точку `file_purposes`
  (`services/files.py` регистрирует назначение, состояние `pending`/`clean`/`quarantine` даёт ядро).
- Слой `publish`: `services/live.py` — через `notify.services.live.group` под `is_installed`; таймаут слоя 2 с,
  сбой — предупреждение (`live.py`, `tasks.publish_event`); запрос отправки не ждёт рассылку.

## 4. «Аудит-изменений»

- Текста сообщений в журнале нет: `audit.record` зовут только `chats.delete` (снимок `chat_title`,
  `chat_members`, `chat_created_at`), `messenger_settings`, `retention`; в `services/messages.py` аудита нет.
- Только дополнение: нет ни одного `AuditEntry.objects.update/delete` в `apps/messenger`.
- Подписи: `apps/messenger/audit_labels.py`, ключ `general_chat_enabled` подписан (правка T-8260).

## 5. «ПДн-152фз»

- Невидимое = несуществующее: `members.get_chat`/`visible_chats` в каждом чтении; чужой чат/файл/сообщение — 404
  (`views/*`), WS — 4404; поиск — по видимым (`services/search.py`).
- Внешние каналы без текста и имён: `notification_kinds.external_text` — «Новое сообщение в чате» /
  «Вас упомянули в чате»; письмо/портал — ФИО автора и название чата без отрывка (`notify_rules.decide`).
- Срок 3 года — данные (`retention_years`), ночная уборка `tasks.retention_night` + cron `messenger_retention`.

## 6. «Секреты-в-url»

- В адресах только номера и ключи: `chat_id`, `message_id`, `file_id`, `?to=`, `f`, `page`, `before`
  (`apps/messenger/urls.py` — 20 адресов + `/ws/messenger/?chat=`); токенов, подписей, адресов почты нет.

## 7. «SQL-только-параметры»

- Все `cursor.execute` — с параметрами: `services/messages.py:155` (`_set_vector`), `services/unread.py:143`,
  `services/search.py:89,113,124`, `services/chats.py:238`; значения не подставляются в текст SQL.
- Динамика в тексте SQL — только структура (`_rows_sql(with_unit_title)`, `_search` c `ANY(%s)`), не данные.

## 8. «Двухфакторная-авторизация» (соединение)

- `/ws/messenger/` — `SessionGuardMixin` (проверка сессии и второй фактор, не «ok» → 4401, цикл 25 с),
  затем видимость чата (4400 до подписки, 4404), предел кадра 4 КБ — 1009, сбой слоя — 1011
  (`apps/messenger/consumers.py`).

## 9. Изменённые файлы прежних срезов ↔ таблица плана ↔ решение 11

Таблица плана «Изменения кода прежних срезов» покрывает: `config/{settings,urls,asgi,cron}.py`,
`core/extensions.py`, `core/models/files.py`+`0011`, `core/services/text.py`, `core/services/thumbs.py`,
`feed/services/{text,thumbs}.py`, `org/views/structure_forms.py`, `templates/org/_slider.html`,
`org/services/structure.py`, `templates/_assets.html`, `notify/urls.py`, `notify/views/pages.py`,
`templates/notify/{bell,_bell_panel}.html`, `deploy/nginx{,.prod}.conf`, `tests/load/locustfile.py`.

Вне таблицы (проверить и записать):

| Файл | Изменение | Почему | Тест прежнего поведения |
|---|---|---|---|
| `apps/core/events.py` | `publish(name=…)` → `publish(event=…)` | конфликт имени параметра с payload `name` события `unit.deleted` (`org/services/structure.py:174`) | `test_core_events.py`, `test_org_structure*` |
| `apps/notify/services/pages.py` | новый файл общей службы потока | вкладка «Уведомления» рисует то же тело (`plan`, 470) | `test_notify_pages*.py`, `test_messenger_tab*.py` |
| `templates/notify/_list_body.html`, `templates/notify/list.html` | общее тело списка | 302 и фрагмент | `test_notify_pages*.py` |
| `templates/search/rows/_messenger.html` | новая строка результата поиска | поставщик «Мессенджер» (`search_providers`) | `test_messenger_search.py`, `test_search*` |
| `templates/icons/chat.html` | иконка пункта меню | план, раздел «Приложение» | `test_messenger_deploy.py` |
| `CLAUDE.md`, `HANDOFF.md` | правило «Без простоев» | решение владельца 2026-11-19 | — (документы) |

Решение 11 (общие файлы кода) — авторы по порядку совпадают с историей коммитов: `extensions.py` T-8205,
T-8211, T-8214, T-8216, T-8217, T-8219, T-8221, T-8224; `apps.py` T-8205, T-8211; `views/chats.py` T-8203,
T-8204, T-8211; `views/messages.py` T-8209, T-8219; `page.html` T-8203, T-8207; `_form.html` T-8203, T-8208,
T-8210; `messenger.js` T-8208, T-8210, T-8213, T-8222; `messenger.css` T-8208, T-8222; `services/files.py`,
`views/files.py` T-8215, T-8216. Параллельно шли только T-8223 и T-8224.

## Находки к записи

0. **Правки по итогам приёмки T-8302 (2026-11-20, решение владельца).** К диффу среза добавляются:
   `templates/notify/_list_body.html` (hx-target/hx-push-url), `apps/notify/services/pages.py` (`push_base`),
   `apps/messenger/views/pages.py` (первая беседа списка), `templates/messenger/page.html` (`_chat.html`),
   `templates/messenger/_form.html` (убран лишний `data-chat-id`, добавлено поле файла и таблетки),
   `templates/messenger/_card_write.html` (зацепка на ссылке), `static/messenger/messenger.js` (узел соединения
   по `ws-connect` мессенджера, `sync` из `ws-connect`, загрузка и «убрать» для вложений),
   `static/messenger/messenger.css` (скрытие второй колонки до 900 px, таблетки), `tests/e2e/helpers_messenger.py`,
   `tests/e2e/test_m01_personal.py`, `tests/e2e/test_m07_files.py`. Повод — дефекты приёмки (соединение с чужим
   сокетом, FR-662/673, зацепки тестов), а не расширение среза; тесты прежнего поведения — `test_notify_pages*`,
   `test_messenger_page`, `test_messenger_unread`, `test_messenger_personal` (повтор — после правок).

1. **Зависимость от `notify.services.pages`** — вне узкой формулировки плана (стр. 59), допущена подписанным
   тестом границ и общей формулировкой стр. 33; данных `notify` не раскрывает (только фильтр/страницы/названия видов).
2. **`core/events.py`** — переименование параметра вне таблицы плана; причина — payload `name`; тесты ядра и узла
   покрывают прежнее поведение.
3. **Устаревшая докстрока** `services/chats.py::rows` (строки 216–219): «у чата отдела и „Общего чата“ — только
   после отметки, без неё 0»; фактическое поведение и решение владельца 2026-11-17 — от создания чата
   (`COALESCE(last_read_at, '-infinity')`). Только текст, поведение верное; предлагается правка докстроки в T-8306.
4. **Устаревшие комментарии каркаса T-8001** (только текст, поведение верное): `config/urls.py` — «список адресов
   мессенджера пуст», `config/asgi.py` — «маршрутов мессенджера ещё нет, его список пуст»; после Этапа 3 маршруты
   есть (20 HTTP-адресов и `/ws/messenger/`). Предлагается поправить комментарии в T-8306.
5. **Проверено по диффу прежних файлов** (`config/{settings,urls,asgi,cron}.py`, `core/extensions.py`): изменения —
   ровно строки таблицы плана (последняя запись `INSTALLED_APPS`, `include` под `is_installed`, маршруты ASGI под
   `is_installed`, одна cron-запись, 19-я точка и датакласс `UnitFormPart`); посторонних правок нет.