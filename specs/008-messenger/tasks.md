---
id: TASKS-008
вид: задачи
статус: утверждён
версия: 1
зависит_от: PLAN-008
основан_на: PLAN-008 sha256:df9fcb0db0b7883ac00f2806291ea0b713b6e45a561ce66f1efce91ad75a22fa
подпись: Максим | 2026-11-16T20:51+03:00 | sha256:767e02f8fbccd724ec331cd0fdb6c5e5a948231d5075d643d759a1bf3fc5bfd2
---

# Задачи среза 008

Формат строки: `- [ ] T-NNNN [P] [исполнитель] описание — файлы или тест — (FR-NNN / NFR-NNN)`.
`[P]` — можно делать параллельно с соседними задачами (нет общих файлов). Исполнитель — sonnet (код и тесты), opus
(архитектурные и финальные), человек (подписи и ручные проходы); haiku в срезе не нужен. Задачи собраны только из
SPEC-008 (13 сценариев, FR-643…673, NFR-701…709) и PLAN-008 (модель данных, механизмы, контракты, интеграции,
проверка, «Изменения кода прежних срезов», «Прежние тесты, которые придётся поправить», риски). Задач вне плана
здесь нет. Решения, которых план не принимал, собраны в разделе «Решения Opus по задачам»; решения плана названы
решениями плана, решения владельца — с датой.

Как читать и исполнять:
- **Нумерация.** Четырёхзначные номера среза 008: Этап 1 — T-8001…, Этап 2 — T-8102…, Этап 3 — T-8200…, Этап 4 — T-8300…. Номера 8100–8101, 8128–8129,
  8144–8149, 8151–8158 не используются (резерв). Требования — FR-643…FR-673 и NFR-701…NFR-709 спеки. Задачи T-8159 (стенд) и T-8160 (красный прогон) закрывают Этап 2 и идут до первой задачи Этапа 3; T-8260 собирает зелёный
  прогон до Этапа 4.
- **Порядок.** Этапы идут подряд. Внутри этапа задача без `[P]` начинается, когда закончены все предыдущие; задачи с `[P]` не зависят от соседей и не
  правят общих с ними файлов. Этап 3 идёт партиями (заголовки жирным); после каждой партии — весь серверный набор тестов.
- **Тест-на-требование.** В Этапе 2 у каждого теста в скобках стоит FR или NFR, который он закрывает; запись `файл::имя_теста` и есть связь T-NNNN →
  требование → тест. Сценарии 1–13 спеки закрывают файлы Playwright `backend/tests/e2e/test_mNN_*.py` (по сценарию на файл). У каждой задачи Этапа 3
  названы файлы и тесты Этапа 2, которые она делает зелёными; файл зеленеет целиком с последней названной задачей.
- **Красный прежде зелёного.** Этап 3 не начинается, пока не выполнен T-8160: тесты сначала падают, причина падения записана. Тест не ослабляют, чтобы
  он прошёл; правят код. Правка теста — только по правилам ниже.
- **Правки прежних тестов — одна задача.** Тесты и помощники срезов 001–007 меняет только T-8007, по точному «было / стало» из таблицы этой задачи
  (источник — раздел плана «Прежние тесты, которые придётся поправить»). Каждая правка — с разрешения владельца, по одному тесту, с диффом; разрешение
  спрашивает Opus, исполнитель правит только после ответа. Если в Этапе 3 упадёт прежний тест, которого нет в перечне T-8007, его не ослабляют:
  исполнитель останавливается, решение принимает Opus и вписывает в раздел решений.
- **Один автор на общий файл.** `backend/tests/CONTRACT-008.md` пишет только T-8002, `tests/support_messenger.py` — только T-8003,
  `tests/e2e/helpers_messenger.py` — только T-8130. В Этапе 3 общие файлы кода (`extensions.py`, `messenger.js`, `messenger.css`, `views/chats.py`,
  `services/*`, `config/*`) правит одна задача за раз; перечень — решение 11. Параллельные исполнители держат свои помощники внутри своего файла и
  общих файлов не правят.
- **Размер.** Одна задача — не больше полудня одного исполнителя; задание агенту — не больше ~50 вызовов; файл тестов — не больше ~25 тестов (больше —
  второй файл `_2`, `_3` и отдельная строка задачи).
- **Изменения кода прежних срезов** — только строки таблицы плана «Изменения кода прежних срезов»; каждая задача Этапа 3 идёт вместе с тестом прежнего
  поведения, названным в столбце «Что не меняется». Других правок нет: при необходимости исполнитель останавливается, Opus решает и вписывает решение
  до правки кода. Исключение — каркас T-8001 (строка `apps.messenger` в `INSTALLED_APPS` и пустое подключение адресов под `apps.is_installed`, решение
  3).
- **Границы модуля** (план: «Сверка с конституцией», «Где живёт код»). `messenger` не импортирует модели `org`, `notify`, `feed`; из `org` зовёт
  только `apps.org.services.structure` (`subtree_member_ids`, `unit_chain_ids`, `unit_refs`), из `notify` — только `dispatch.create` и `live.group`,
  каждый вызов под `apps.is_installed`. Прежние модули не импортируют `apps.messenger`. Точка `top_bar_items` остаётся за `notify`; колокольчик
  получает признак `bell_link` (решение плана, раздел «Вкладка „Уведомления“»).
- **Секреты — только `***`** в коде, документах, отчётах и выводе команд; правило ставится в задание каждому исполнителю. Новых секретов и переменных
  срез не вводит; `.env`, `deploy/.env`, `state/`, `creds*.csv`, `activation.txt` не открываются; переписка и данные сотрудников в задания не
  копируются.
- **SQL — только параметры** (NFR-703): литерал с `%s` и списком параметров, никаких f-строк и склейки с вводом; ключи `q`, `to`, `before`, `f`,
  `page`, `chat` — белый список; цепочка узлов — массивом `= ANY(%s)`; время — только параметром из `timezone.now()`.
- **Отчёты подагентов** — в `crm-work/slice008/…` через Bash heredoc (Write подагенту для отчётов запрещён); в репозитории — только код, тесты и
  документы среза.
- **Тесты и контейнер.** Серверные тесты — `docker compose -f deploy/docker-compose.yml --profile test run --rm test`; прогоны длиннее нескольких
  минут (полный набор, приёмка, нагрузка) — через `systemd-run --user`. Временные пробы — вне репозитория; в `backend/` контейнера ничего не
  монтируется. Запущенный стенд исполнители не останавливают и не пересоздают: копию, сброс, пересборку и обновление стенда делает Opus с разрешения
  владельца после `backup-stand.sh`.
- **Зависимости.** Новых пакетов нет (план: «Новые компоненты и лицензии»); `requirements.txt` не меняется, строки «Срез 008» нет. Нужен новый пакет —
  исполнитель останавливается и спрашивает Opus.
- **Расхождение с планом** — остановка и вопрос Opus; решение сначала вписывается в раздел «Решения Opus по задачам», потом меняется код. Ссылки на
  разделы плана — в тексте задачи.

## Этап 1 — подготовка

- [x] T-8001 [sonnet] каркас по блоку «Где живёт код» плана; сверх блока — ничего: `backend/apps/messenger/` (`apps.py`
  с `MessengerConfig`, меткой `messenger` и `ready()`, вызывающим `extensions.register_all()`; пустые `models.py`,
  `texts.py`, `notify_kinds.py`, `audit_labels.py`, `unit_form.py`, `stand.py`, `tasks.py`, `consumers.py`, `routing.py`
  с пустым `websocket_urlpatterns`, `urls.py` с пустым `urlpatterns`; пакеты `migrations/`, `management/commands/`,
  `views/` с пустыми `pages.py`, `chats.py`, `messages.py`, `files.py`, `mentions.py`, `settings.py`,
  `notifications.py`; пакет `services/` с пустыми `chats.py`, `members.py`, `department.py`, `messages.py`,
  `mentions.py`, `text.py`, `read.py`, `unread.py`, `live.py`, `notify_rules.py`, `files.py`, `search.py`,
  `retention.py`, `messenger_settings.py`, `page.py`, `errors.py`), `backend/templates/messenger/`, пустые
  `backend/static/messenger/messenger.js` и `messenger.css`; `backend/templates/icons/chat.html` — своя иконка
  пункта меню (иначе `base.html` упадёт на `{% include item.icon %}`); в `config/settings.py` — `apps.messenger` последним, после
  `apps.feed`; в `config/urls.py` — `include("apps.messenger.urls")` под `apps.is_installed("apps.messenger")` (пустой
  список, поведение портала не меняется), в `config/asgi.py` — подключение `messenger.routing` под тем же условием, в
  `config/cron.py` — импорт и вызов `register` под проверкой установки добавляет T-8220 (здесь только место).
  Модели, миграции и данные установки — T-8200/T-8201 (решение 3). После каркаса сервер и тесты 001–007 зелёные,
  кроме проверок хвоста `INSTALLED_APPS` из перечня T-8007 — backend/apps/messenger/, backend/templates/messenger/,
  backend/static/messenger/, backend/config/settings.py, backend/config/urls.py, backend/config/asgi.py —
  (FR-643; план: «Где живёт код», «Изменения кода прежних срезов»)
- [x] T-8002 [sonnet] контракт имён среза `backend/tests/CONTRACT-008.md` по структуре CONTRACT-007 (среда и числа,
  модели и данные установки, ядро и записи точек, прежние модули `org`/`notify`/`feed`, службы `messenger` и точки
  подмены — слой `publish`, ClamAV, время и часы, помощники, виды уведомлений, журнал, поиск, маршруты, сообщения слоя
  и кадры, зацепки `data-*`, тексты, команды стенда, правки прежних контрактов, вопросы и решения). Числа дословно по
  плану: точек расширения — 19 (`unit_form_parts` последней); видов уведомлений — 22 (два `messenger.*`, `order` 80 и
  81); прав — 18 (новых нет); вызовов `register` в `config/cron.py` — 21 (`messenger_retention` `55 23 * * *` в
  `maintenance`); значений `StoredFile.Purpose` — 6 (`messenger` последним); порядок группы поиска — 61; пункт
  «Мессенджер» — второй (`order` 1), «Настройки мессенджера» — `order` 64; `location` с `client_max_body_size 25m` —
  два (`^/feed/files/$`, `^/messenger/files/$`); `apps.messenger` — последний в `INSTALLED_APPS`; ключей
  `CHANNEL_LAYERS` — два; нагрузочные классы — `FeedUser`, `NotifyUser`, `MessengerUser`. Там же: модели и поля
  (таблица «Приложение `messenger`»), зависимости миграций (`messenger 0001` → `core 0011`; `messenger 0002` →
  `core 0002_initial_data` и `messenger 0001`), данные установки (`MessengerSettings(pk=1)`, «Общий чат»), маршруты
  «Контрактов» дословно, сообщение слоя `messenger.event` и `notify.html`, коды закрытия 4400/4401/4404/1009/1011/1013,
  группы `messenger.u.{id}` и `notify.u.{id}`, зацепки `#m<id>`, `#chat-<id>-unread`, `#chat-<id>-preview`,
  `#menu-badge-messenger[data-count]`, `#messenger-messages`, `#messenger-read`, `#messenger-synced`, `[data-ws]`,
  `[data-mention]`, `[data-bell-link]`, `data-message-id`, тексты `messenger/texts.py` дословно, команда
  `e2e_messenger_age --days N` со строкой `messenger_age: aged=<N>`, имена помощников `support_messenger.py` по строке
  T-8003 и `helpers_messenger.py` по строке T-8130. Правки прежних контрактов — таблицей «было / стало» (сам
  `CONTRACT.md` и `CONTRACT-002…007` не правятся). Контракт проверяет Opus до запуска T-8003 —
  backend/tests/CONTRACT-008.md — (FR-643…673, NFR-701…709; план: «Контракты», «Проверка»)
- [x] T-8003 [sonnet] общие помощники тестов по принятому контракту: `backend/tests/support_messenger.py` по образцу
  `support_feed.py` (без `@pytest.fixture`, без импорта `apps.messenger` на уровне модуля — модели и код среза внутри
  функций, чтобы сбор тестов проходил до появления кода): константы `POINTS_008 = ("unit_form_parts",)`,
  `PURPOSES_008`, `CHAT_KINDS = ("personal", "group", "department", "general")`, `MESSENGER_KINDS` (две строки
  формата `TABLE` из `test_notify_catalog.py`: код, название, модуль «Мессенджер», `order` 80/81, обязательность,
  каналы по умолчанию — портал и почта, события, внешний текст), `MESSENGER_CODES`, `MESSENGER_TITLES`,
  `AUDIT_CODES` (шесть кодов плана), `MENU_008` (два пункта с `order` 1 и 64), `JOBS_008` (формат `FEED_JOBS`);
  функции `make_user(state=…)`, `unit(name, parent=…)`, `personal(a, b)`, `group(creator, members, title=…)`,
  `department_chat(unit)`, `general()`, `post(chat, author, text, quote=None, files=())`, `read(chat, user, at)`,
  `attach(chat)` (подмена ClamAV, состояния «проверяется»/«чистый»/«карантин»), `as_admin()`, `without_messenger()`
  (снятие регистраций `apps.messenger` и подмена `apps.is_installed`), `run_seed()`, `run_retention(now)`,
  `ws_client(user, query)` (`WebsocketCommunicator` с `query_string`), `layer_down()`, `layer_spy()`, `capture_sql`,
  `run_jobs(queue)` (`support_notify.run_jobs`), сбор картинок в памяти (JPEG с EXIF, PNG с прозрачностью, GIF из
  кадров, картинка больше 40 Мп), `email_of`/`phone_of`, список страниц среза для проверок «по-русски» и «без
  `style=`». Писатели T-8102… стартуют после неё — backend/tests/support_messenger.py — (план: «Проверка» →
  «Серверные тесты»)
- [x] T-8004 [P] [sonnet] перенос вывода текста и эскизов в ядро (план: «Модель данных» → `core.services.text`,
  `core.services.thumbs`; «Изменения кода прежних срезов» — строки `core/services/text.py`, `core/services/thumbs.py`,
  `feed/services/text.py`, `feed/services/thumbs.py`): новый `core/services/text.py` — `render_plain(text, pieces, *,
  link_staff)` (единственное место `mark_safe`: экранирование, ссылки `http`/`https`/`mailto`, абзацы и переносы,
  шаблоны `pieces`) и `snippet(text, limit, *, expand=None)`; новый `core/services/thumbs.py` — `build(source_path,
  stored_id)` и `MAX_SIDE`; выражения переносятся из ленты без изменения поведения; `feed/services/text.py` остаётся
  обёрткой со своим шаблоном `@[id]` и прежними именами, `feed/services/thumbs.py` — обёрткой над ядром. Тесты —
  T-8126a (`test_messenger_core_changes.py`); прежние `test_feed_text.py` и `test_feed_files.py` — без правок и зелёные — backend/apps/core/services/text.py,
  backend/apps/core/services/thumbs.py, backend/apps/feed/services/text.py, backend/apps/feed/services/thumbs.py —
  (FR-653, FR-662; NFR-703)
- [x] T-8005 [sonnet] (после T-8004) ядро: девятнадцатая точка и датакласс (план: «Точки расширения ядра и шина событий»,
  «Модель данных» → `core.extensions`): `"unit_form_parts"` в конце `POINTS` (19 точек, прежние 18 в прежнем
  порядке) и датакласс `UnitFormPart` с полями `key`, `order`, `render(request, unit)`, `on_saved(unit, post, actor,
  ip=None)` по описанию плана. Тесты — T-8126a (`test_point_unit_form_parts_is_nineteenth_and_dataclass_fields`);
  прежние `test_extensions.py`, `test_kb_boundaries.py`, `test_lists_boundaries.py`, `test_sd_boundaries.py`,
  `test_feed_core_changes.py`, `test_feed_boundaries.py` зеленеют после T-8007 — backend/apps/core/extensions.py — (FR-649)
- [x] T-8006 [sonnet] (после T-8005) `org`: поля формы узла и событие удаления (план: «Точки расширения ядра и шина
  событий», «Состав чата отдела и перевод/приём», «Изменения кода прежних срезов» — строки
  `org/views/structure_forms.py`, `templates/org/_slider.html`, `org/services/structure.py`): `structure_forms`
  рендерит записи `unit_form_parts` в порядке `order` и зовёт `on_saved` после `create_unit`/`update_unit`, каждый
  обработчик — в собственном `transaction.atomic()` (savepoint), ошибка обработчика откатывает только его работу,
  пишется предупреждением в журнал и не отменяет сохранение узла; `unit_new` и `on_saved` — в `atomic`;
  `_slider.html` — цикл по полям; `structure.delete_unit` публикует `unit.deleted` (`unit_id`, `name`, `actor_id`)
  после удаления узла до конца транзакции. Тесты — T-8126b (`test_messenger_core_changes_2.py`); прежние
  `test_org_structure*`, e2e `test_o_*` —
  backend/apps/org/views/structure_forms.py, backend/templates/org/_slider.html, backend/apps/org/services/structure.py
  — (FR-649, FR-650)
- [x] T-8007 [sonnet] (после T-8001, T-8003 и T-8005; без `[P]` — решение 4) правка прежних тестов срезов 001–007
  одной задачей: каждый пункт — с разрешения владельца, по одному тесту, с диффом; разрешение спрашивает Opus,
  исполнитель правит только после ответа. Точное «было / стало»:
  1. `test_extensions.py::test_org_registers_all_nine_extension_points` — `… + POINTS_007` → `… + POINTS_007 +
     POINTS_008` (`from tests.support_messenger import POINTS_008`), «восемнадцать» → «девятнадцать»;
  2. `test_feed_core_changes.py::test_points_end_with_home_body_as_eighteenth_point` — `len(POINTS) == 18` → `== 19`;
     `POINTS[-1] == "home_body"` → `== "unit_form_parts"`; `POINTS[17:] == POINTS_007` → `POINTS[18:] == POINTS_008`;
     отдельной строкой `test_previous_seventeen_points_keep_their_order` — `POINTS[:17]` → `POINTS[:18]`;
  3. `test_kb_boundaries.py`: `POINTS_18 = POINTS_17 + ("home_body",)` → `POINTS_19 = POINTS_18 + ("unit_form_parts",)`,
     `len == 18` → `19`, `POINTS[-1] == "home_body"` → `== "unit_form_parts"`,
     `POINTS[-3:-1] == ("search_providers", "ticket_card_parts")` → `POINTS[-4:-2] == (...)`;
  4. `test_lists_boundaries.py` — то же, что п. 3 (`POINTS_18` → 19);
  5. `test_sd_boundaries.py`: `POINTS_17 + ("home_body",)` → `POINTS_17 + ("home_body", "unit_form_parts")`;
  6. `test_feed_core_changes.py::test_stored_file_purpose_feed_is_last_and_previous_values_unchanged` — в списке
     `Purpose.choices` пять значений → шесть, `("messenger", "вложение сообщения чата")` последним,
     `values[-1] == "feed"` → `== "messenger"`; проверка миграции `core 0011` и зависимости от `0010` — новые
     утверждения T-8126a, не «стало» прежнего теста;
  7. `test_kb_boundaries.py`: `len(rest) == 17` → `19` (два вида `messenger.*`);
  8. `test_notify_catalog.py::test_catalog_contains_eight_kinds_from_three_modules` — «двадцать видов» → «двадцать
     два», `{kind.module}` + «Мессенджер», счётчики модулей + 2, `TABLE` + две строки, `order` 80/81;
  9. `test_notify_catalog_2.py`: `+ MESSENGER_CODES`, названия, модуль «Мессенджер», `len(push_cells(root)) == 14`
     → `16` (две строки мессенджера), `push`-строка 13 → 15, общий счётчик «двадцать» → «двадцать два»;
  10. `test_notify_prefs.py`, `test_notify_prefs_2.py`, `test_notify_admin.py`: `tr[data-notify-fixed]` остаётся 2
      (две сводные строки не меняются); строки видов в простом режиме 14 → 16, в таблице администратора — +2;
      точные коды `messenger.message` и `messenger.mention` (модуль «Мессенджер», портал и почта), прежние строки
      не меняются;
  11. `test_notify_pages.py`: колокольчик — `a[data-bell-link][href="/messenger/notifications/"]` вместо
      `button[data-bell-toggle]` с `hx-get="/notifications/bell/"`; `#notify-count`, `#notify-toast`,
      `#notify-bell-panel` остаются; помощник `_get_list` (строки 151–154) и тесты фильтров (436, 455) читают
      `/messenger/notifications/` вместо `/notifications/`; адреса фильтра и страниц во вкладке ведут на
      `/notifications/list/` (через `hx-get` у кнопок фильтра и страниц, `href` прежних ссылок не меняется);
      отдельная проверка «`/notifications/` — 302 с `f` и `page`, а строки уведомлений
      есть в конечном ответе вкладки» — в `test_messenger_core_changes_2.py`;
  12. `test_notify_texts.py` — точечная проверка (строка 321) `get("/notifications/")` → `get("/notifications/list/")`
      с теми же `status_code == 200` и строкой `_rows`; цикл `for path in ("/notifications/", "/notifications/bell/")`
      (строки 486–495) заменяется на `("/messenger/notifications/", "/notifications/bell/")` с теми же проверками;
      `test_notify_delivery.py` (два места) и `test_notify_email.py` — `client.get("/notifications/")` →
      `client.get("/notifications/list/")` для фрагмента, плюс строка 302 на старый адрес;
  13. `tests/support_feed.py`: `APPS_TAIL` + `"apps.messenger"` (семь имён);
  14. `test_notify_deploy.py`: `settings.INSTALLED_APPS[-6:] == APPS_TAIL` → `[-7:]`; `len(registrations) == 20` → `21`
      (`messenger_retention`, `55 23 * * *`, `maintenance`, 600);
  15. `test_lists_deploy.py`: `[-6:]` → `[-7:]`, 20 → 21; `test_kb_deploy.py`: `[-5:] == APPS_TAIL[1:]` →
      `[-6:] == APPS_TAIL[1:]` (семь имён хвоста) и литерал `…, "apps.search", "apps.feed", "apps.messenger"`,
      20 → 21; индексы `stand_reset`: `apps.feed.stand` — `len - 2`, `apps.messenger.stand` — `len - 1`;
  16. `test_sd_deploy.py`: 20 → 21; `test_feed_deploy.py` — `[-6:] == APPS_TAIL` → `[-7:] == APPS_TAIL`,
      `[-1] == "apps.feed"` → `[-2] == "apps.feed"` и `[-1] == "apps.messenger"`, число вызовов 20 → 21;
  17. `test_lists_stand.py`: `registered[-2] is stand_reset` → `[-3]`, `names[-1] == "apps.feed.stand"` →
      `names[-2]`, `names[-3] == "apps.knowledge.stand"` → `names[-4]`, `call_order[0]` → `apps.messenger.stand`,
      `call_order[1] == "apps.feed.stand"`; `test_kb_deploy.py` — `names.index(feed) == len-2`, `messenger == len-1`,
      `lists == len-3`, `knowledge == len-4`; `test_feed_stand.py` — `registered[-1]` → `[-2]`, `names[-2]` → `[-3]`,
      `call_order[0] == "apps.feed.stand"` → `[0] == "apps.messenger.stand"` и `[1] == "apps.feed.stand"`;
  18. `test_org_permissions.py`: `urls` + `/messenger/` после `/` и `/settings/messenger/` после `/settings/feed/`;
      `orders` + 1 после 0 и + 64 после 63; `titles` + «Мессенджер» и «Настройки мессенджера»; `items[1]` — набор
      `url/title/icon/order/badge/live_badge`, `items[2]` — прежний набор «Заявок», `items[3:]` — четыре ключа;
      `icons["/messenger/"] == "icons/chat.html"`;
  19. `test_lists_access.py`: `len(titles) == 14` → `16` (два пункта), порядок «База знаний < Списки < Сотрудники»
      не меняется; `test_sd_boundaries.py` — пункты и наборы ключей с «Мессенджером» и «Настройками мессенджера»;
  20. `test_search_providers_2.py`: `["articles","staff","units","feed"]` → `+ ["messenger"]`, без базы знаний
      `["staff","units","feed"]` → `+ ["messenger"]`, без прав `["articles","feed"]` → `+ ["messenger"]`;
      `test_kb_boundaries.py`: `providers` и `titles` + `["messenger"]` / «Мессенджер» последними;
  21. `test_deploy_files.py` — пять шаблонов → шесть: четыре `55m` и два `25m` (`^/feed/files/$`,
      `^/messenger/files/$`), вне их — один `6m`;
  22. приёмка: `tests/e2e/test_e10_page.py`, `test_e06_bots.py`, `test_f05_likes.py`, `test_e12_criteria.py` —
      нажатие `button[data-bell-toggle]` → `a[data-bell-link]`, после нажатия адрес `/messenger/notifications/` и
      вкладка «Уведомления»; `test_e04_my_settings.py`, `test_e12_criteria.py` — каталог с разделом «Мессенджер»;
  23. `test_feed_boundaries.py::test_points_tuple_has_eighteen_names_and_feed_uses_home_body_last` — `len == 18` → `19`,
      `POINTS[-1] == "home_body"` → `== "unit_form_parts"`, `POINTS_17 + feed.POINTS_007` → `+ ("unit_form_parts",)`,
      `_own("home_body")` не меняется.
  Пункты, которые зеленеют только в Этапе 3 (точки, назначение, хвост `INSTALLED_APPS`, cron, nginx, колокольчик,
  302, стенд), в T-8160 идут отдельной строкой (решение 12). «Проверить после реализации» (план) — T-8300:
  `test_permissions.py`, `test_sd_access.py`, `test_org_permissions.py` (права), `test_feed_home.py`, e2e `test_o_*`,
  `test_notify_admin.py`, e2e `test_d09_settings.py`; `tests/e2e/test_k09_notify.py` тоже нажимает колокольчик, хотя
  план его не называет — при падении остановка и решение Opus (решение 14) — backend/tests/, backend/tests/e2e/;
  отчёт docs/reviews/TASKS-008.md, раздел «Правки прежних тестов» — (план: «Прежние тесты, которые придётся
  поправить»)
- [x] T-8008 [P] [sonnet] стенд: команда и договор сброса (план: «Проверка» → «данные установки и стенд», «Запуск»;
  реализация сброса — T-8224, решение 5): `management/commands/e2e_messenger_age.py` — `--days N`, проверка
  `E2E_STAND=1` и диапазона, прямой сдвиг `Message.created_at` через `F()` и одна строка
  `messenger_age: aged=<N>`; `services/…` не трогает; в `stand.py` — только `require_stand()` и перечень таблиц
  сброса по контракту (функция `stand_reset` и регистрация точки — T-8224). Тесты Этапа 2: `test_messenger_stand.py`
  (после T-8003). Стенд не сбрасывается, службы не перезапускаются; копия и обновление — T-8159 (разрешение
  владельца) — backend/apps/messenger/management/commands/e2e_messenger_age.py,
  backend/apps/messenger/stand.py — (FR-670; план: «Проверка»)

## Этап 2 — тесты (пишутся до кода и падают)

Общие правила тестов — решения 1, 2, 6–10, 14. Тесты пишутся после T-8002 (`CONTRACT-008.md`) и T-8003
(`support_messenger.py`); писатели T-8102… стартуют после T-8003. Номера требований у тестов — в скобках по строке.

- [x] T-8102 [P] [sonnet] тесты моделей и миграций (план: «Модель данных») —
  `test_messenger_models.py::test_chat_kind_checks_title_unit_pair_key_and_general_single_row` (FR-643, 645, 646,
  649, 650, 651); `::test_personal_pair_key_unique_partial_and_duplicate_raises` (FR-645);
  `::test_department_unit_unique_and_general_unique_constraints` (FR-650, 651);
  `::test_chat_member_unique_chat_user_and_partial_active_index` (FR-646, 647);
  `::test_chat_read_unique_chat_user_and_index_for_counts` (FR-659, 660);
  `::test_message_system_requires_no_author_and_deleted_requires_empty_text` (FR-649, 657);
  `::test_message_quote_set_null_and_indexes_chat_created_search_gin` (FR-654, 658, 668);
  `::test_message_attachment_unbound_partial_index_and_protect_on_stored_file` (FR-662);
  `::test_messenger_settings_retention_bounds_and_general_default_on` (FR-651, 670);
  `::test_migrations_depend_on_core_0011_and_core_0002_initial_data` (FR-643)
- [x] T-8103 [P] [sonnet] тесты прав и одной функции видимости (план: «Права и неприкосновенность») —
  `test_messenger_chats.py::test_get_chat_same_http404_for_missing_foreign_and_deleted` (FR-669);
  `::test_every_endpoint_of_chat_uses_one_visibility_function` (FR-669);
  `::test_admin_of_portal_gets_404_on_foreign_personal_dialog` (FR-669, 643);
  `::test_dismissed_employee_has_no_access_to_portal_and_chats` (FR-643);
  `::test_employee_outside_chat_cannot_open_message_edit_delete_read_or_search` (FR-669);
  `::test_foreign_chat_file_and_thumb_answer_like_missing` (FR-669);
  `::test_search_does_not_show_foreign_chat_and_does_not_count_it` (FR-668, 669);
  `::test_live_recipients_and_still_relevant_use_same_membership` (FR-661, 663);
  `::test_visible_chats_for_employee_personal_group_department_chain_and_general` (FR-643, 650, 651);
  `::test_members_of_department_chat_are_subtree_without_dismissed` (FR-650);
  `::test_general_members_are_active_employees_with_one_query` (FR-651);
  `::test_blocked_member_counted_but_gets_no_frames_or_notifications` (FR-660, 663)
- [x] T-8104 [P] [sonnet] тесты личного диалога и «Написать» (план: «Виды чатов и создание», «Написать из карточки
  сотрудника») — `test_messenger_personal.py::test_first_message_creates_single_dialog_and_second_goes_there`
  (FR-645); `::test_dialog_from_card_and_from_messenger_is_same_chat` (FR-645);
  `::test_race_of_two_creations_leaves_one_row` (FR-645);
  `::test_dialog_with_dismissed_not_created_and_existing_send_refused` (FR-645, 643);
  `::test_opening_to_page_creates_no_empty_dialog` (FR-645); `::test_list_shows_peer_name_preview_time_and_order`
  (FR-644); `::test_first_message_in_new_dialog_gives_one_unread` (FR-660);
  `::test_people_search_returns_20_active_and_hides_dismissed` (FR-645);
  `::test_card_write_button_hidden_for_self_and_dismissed` (FR-645)
- [x] T-8105 [P] [sonnet] тесты группового чата (план: «Виды чатов и создание», «Журнал») —
  `test_messenger_group.py::test_creator_creates_group_with_title_and_two_members` (FR-646);
  `::test_title_empty_and_201_chars_refused_with_reason` (FR-646); `::test_group_without_members_or_with_dismissed_member_refused`
  (FR-646); `::test_creator_included_and_any_active_employee_may_create` (FR-646);
  `::test_creator_adds_and_removes_members_while_in_chat` (FR-646);
  `::test_member_leaves_and_stops_seeing_chat_and_messages` (FR-647);
  `::test_creator_leaves_and_composition_frozen_403` (FR-646);
  `::test_creator_deletes_chat_with_confirm_history_gone_and_audit_without_text` (FR-648, 671);
  `::test_last_member_leaves_with_confirm_deletes_chat_and_history` (FR-647);
  `::test_non_creator_delete_forbidden_and_missing_confirm_keeps_chat` (FR-648);
  `::test_removed_member_added_again_gets_joined_at_updated` (FR-647, 660)
- [x] T-8106 [P] [sonnet] тесты чата отдела (план: «Состав чата отдела и перевод/приём», «Системные записи чата
  отдела») — `test_messenger_department.py::test_checkbox_on_unit_creation_makes_chat_with_title_and_two_system_messages`
  (FR-649); `::test_department_chat_includes_subtree_members_and_not_foreign` (FR-650);
  `::test_no_checkbox_no_chat_and_repeat_save_makes_no_second_chat` (FR-649);
  `::test_renaming_unit_changes_chat_title_without_new_row` (FR-649);
  `::test_newcomer_sees_chat_history_and_zero_unread` (FR-650, 660);
  `::test_transferred_employee_loses_old_department_chat_and_sees_new` (FR-650);
  `::test_deleted_unit_deletes_chat_and_audits_without_text` (FR-650, 671);
  `::test_portal_admin_deletes_department_chat_with_confirm_and_audit` (FR-672, 671);
  `::test_member_cannot_delete_department_chat_403` (FR-672, 669);
  `::test_department_chat_not_registered_in_unit_usage_so_unit_deleted` (FR-650);
  `::test_system_messages_do_not_count_as_unread_and_are_not_editable` (FR-649, 660)
- [x] T-8107 [P] [sonnet] тесты «Общего чата» (план: «Виды чатов и создание» — «Общий чат») —
  `test_messenger_general.py::test_seed_creates_single_general_chat_and_employee_may_write` (FR-651);
  `::test_disabled_general_chat_absent_from_list_and_search_and_404_on_direct_address` (FR-651);
  `::test_disabled_general_chat_refuses_send_plain_404_and_htmx_reason` (FR-651, 652);
  `::test_enable_again_restores_history_and_writes_two_audit_records` (FR-651, 671);
  `::test_any_active_employee_writes_to_general_chat` (FR-651);
  `::test_general_chat_visible_to_employee_without_roles` (FR-651)
- [x] T-8108 [P] [sonnet] тесты списка, беседы и истории (план: «Список чатов и порядок», «Беседа и история
  порциями») — `test_messenger_page.py::test_list_orders_by_last_message_and_puts_empty_chats_last` (FR-644);
  `::test_each_row_has_title_preview_time_and_unread_count` (FR-644, 660);
  `::test_personal_row_shows_peer_name_instead_of_title` (FR-644, 645);
  `::test_empty_list_shows_hint_to_write_colleague` (FR-644);
  `::test_list_sql_count_does_not_grow_with_number_of_chats` (FR-644, NFR-703);
  `::test_filter_q_by_title_and_peer_name_passes_values_as_parameters` (FR-644, NFR-703);
  `::test_history_returns_50_then_50_then_20_by_cursor_without_gaps` (FR-658);
  `::test_hundred_messages_with_same_created_at_cursor_has_no_loss_or_repeat` (FR-658);
  `::test_history_reaches_first_message` (FR-658);
  `::test_chat_page_has_header_input_and_ws_node_with_chat_id` (FR-658, 673);
  `::test_invisible_chat_page_is_404_like_missing` (FR-669)
- [x] T-8109a [P] [sonnet] тесты отправки, правки и удаления (план: «Отправка, правка, удаление, цитата») —
  `test_messenger_messages.py::test_empty_and_spaces_only_refused_with_reason` (FR-652);
  `::test_4000_accepted_4001_refused_and_nul_removed` (FR-652);
  `::test_text_stored_as_is_with_paragraphs_and_breaks` (FR-652, 653);
  `::test_author_edits_text_gets_edited_mark_and_old_text_gone` (FR-656);
  `::test_foreign_message_edit_and_delete_403_or_404` (FR-656, 657, 669);
  `::test_author_deletes_message_leaves_grey_record_with_time` (FR-657);
  `::test_delete_recalculates_last_message_at` (FR-657, 644);
  `::test_message_deleted_by_retention_cannot_be_edited_404` (FR-670);
  `::test_send_updates_last_message_at_and_list_order` (FR-644)
- [x] T-8109b [P] [sonnet] тесты цитаты и пределов (план: «Отправка, правка, удаление, цитата») —
  `test_messenger_messages_2.py::test_quote_one_level_and_quote_of_other_chat_refused` (FR-654);
  `::test_quote_of_deleted_message_shown_as_deleted` (FR-654, 657);
  `::test_quote_cannot_be_nested_second_level` (FR-654);
  `::test_sending_and_editing_create_no_notifications` (FR-656, 666);
  `::test_mentions_limit_on_edit_same_as_on_send` (FR-652, 655);
  `::test_delete_message_removes_attachments_rows_and_files_after_commit` (FR-657, 662);
  `::test_quote_to_message_of_invisible_chat_returns_404` (FR-669)
- [x] T-8110 [P] [sonnet] тесты вывода текста (план: «Отправка» — «Вывод», «Безопасный вывод») —
  `test_messenger_text.py::test_plain_text_escaped_and_script_not_executed` (FR-653, NFR-703);
  `::test_only_http_https_mailto_become_links_and_javascript_stays_text` (FR-653);
  `::test_paragraphs_and_line_breaks_kept` (FR-653);
  `::test_mention_markers_render_name_link_and_chat_link` (FR-653, 655);
  `::test_unknown_marker_stays_text` (FR-655);
  `::test_bidi_and_control_characters_removed` (NFR-703);
  `::test_snippet_100_without_markup_and_with_mention_expand` (FR-653);
  `::test_same_output_on_page_frame_and_notification_text` (FR-653, NFR-705)
- [x] T-8111 [P] [sonnet] тесты упоминаний «@» (план: «Упоминания „@“») —
  `test_messenger_mentions.py::test_suggestion_lists_active_chat_members_and_own_chats` (FR-655);
  `::test_suggestion_hides_strangers_and_foreign_chats` (FR-655, 669);
  `::test_personal_dialog_suggestion_empty_and_form_has_no_suggest` (FR-655);
  `::test_empty_or_one_char_query_returns_nothing` (FR-655);
  `::test_extract_returns_people_and_chats_sets` (FR-655);
  `::test_mention_outside_suggestion_unknown_word_is_no_mention` (FR-655);
  `::test_mention_of_non_member_kept_as_text_and_sends_no_notification` (FR-655);
  `::test_chat_mention_inserts_link_and_notifies_only_mentioned_people` (FR-655, 664);
  `::test_21_distinct_mentions_refused_and_20_allowed` (FR-655);
  `::test_repeated_mention_does_not_consume_limit` (FR-655)
- [x] T-8112 [P] [sonnet] тесты прочтения (план: «Прочтение и счётчики», «Открытая беседа») —
  `test_messenger_read.py::test_opening_chat_creates_read_mark` (FR-659);
  `::test_repeat_read_keeps_max_and_does_not_decrease` (FR-659);
  `::test_future_at_clamped_to_now_and_does_not_suppress_next_messages` (FR-659, 660);
  `::test_author_sees_read_12_of_40_only_under_last_own_message` (FR-659);
  `::test_dismissed_and_left_members_not_in_m` (FR-659);
  `::test_message_in_opened_chat_is_marked_read_and_leaves_notification_flow` (FR-666);
  `::test_object_viewed_event_silences_chat_notifications` (FR-666);
  `::test_read_answer_carries_chat_count_total_and_read_line` (FR-659, 660)
- [x] T-8113 [P] [sonnet] тесты чисел непрочитанного (план: «Прочтение и счётчики») —
  `test_messenger_unread.py::test_chat_count_and_total_grow_by_new_message` (FR-660);
  `::test_own_and_deleted_messages_not_counted` (FR-660);
  `::test_120_unread_shown_as_99_plus` (FR-660);
  `::test_newcomer_of_department_has_zero_and_history_available` (FR-650, 660);
  `::test_new_group_member_counts_only_messages_after_join` (FR-660);
  `::test_personal_first_message_counts_one` (FR-660);
  `::test_cache_invalidated_by_send_read_and_membership_change` (FR-660);
  `::test_access_changed_event_invalidates_counts_of_affected_employees` (FR-650, 660)
- [x] T-8114 [P] [sonnet] тесты рассылки (план: «Живые обновления и рассылка») —
  `test_messenger_live.py::test_send_enqueues_publish_event_to_notify_queue_on_commit` (FR-661);
  `::test_recipients_snapshot_excludes_author_and_uses_current_members` (FR-661, 669);
  `::test_fragment_rendered_once_per_role_and_link_staff_variant` (FR-661);
  `::test_one_layer_message_contains_counts_total_and_variants` (FR-660, 661);
  `::test_layer_down_send_succeeds_fast_and_logs_warning` (FR-661);
  `::test_queue_failure_keeps_message_and_logs_warning` (FR-661);
  `::test_chat_delete_recipients_collected_before_cascade` (FR-648, 661);
  `::test_transferred_employee_gets_no_next_frame` (FR-650, 661);
  `::test_third_employee_outside_chat_gets_no_frame` (FR-661, 669);
  `::test_badge_and_row_fragments_go_to_personal_notify_group` (FR-660)
- [x] T-8115 [P] [sonnet] тесты соединения (план: «Живые обновления и рассылка» → `MessengerConsumer`) —
  `test_messenger_consumers.py::test_connect_without_chat_zero_negative_or_text_closes_4400` (FR-661);
  `::test_foreign_and_missing_chat_close_4404` (FR-661, 669);
  `::test_anonymous_no_second_factor_or_expired_session_close_4401` (FR-643, 661);
  `::test_ws_state_error_in_loop_closes_1013` (FR-661);
  `::test_new_edit_delete_frames_swapped_by_message_id` (FR-656, 657, 661);
  `::test_chat_delete_frame_sends_hx_redirect_to_list` (FR-648, 661);
  `::test_read_message_updates_read_line_for_author` (FR-659, 661);
  `::test_client_message_over_4kb_closes_1009_and_other_frames_ignored` (FR-661);
  `::test_frame_has_no_csrf_token` (FR-661);
  `::test_layer_error_in_consumer_closes_1011` (FR-661)
- [x] T-8116a [P] [sonnet] тесты видов и правил уведомлений (план: «Уведомления») —
  `test_messenger_notify.py::test_two_kinds_with_titles_orders_channels_and_module` (FR-663, 664);
  `::test_message_kind_goes_to_every_member_except_author` (FR-663, 666);
  `::test_mention_kind_goes_only_to_mentioned_member` (FR-664);
  `::test_texts_of_message_and_mention_are_russian` (FR-663, 664, NFR-708);
  `::test_own_message_and_self_mention_give_no_notification` (FR-666);
  `::test_three_messages_coalesce_into_one_with_count` (FR-666);
  `::test_mentioned_gets_only_mention_not_message` (FR-664, 666);
  `::test_edit_and_delete_create_no_notifications` (FR-656, 657)
- [x] T-8116b [P] [sonnet] тесты каталога, настроек каналов и `still_relevant` (план: «Уведомления», «Вкладка
  „Уведомления“») — `test_messenger_notify_2.py::test_catalog_has_22_kinds_and_two_messenger_rows` (FR-663, 664);
  `::test_my_notifications_lists_two_rows_with_email_and_external_channels` (FR-665);
  `::test_employee_turns_off_email_and_gets_portal_only` (FR-665);
  `::test_still_relevant_false_for_left_transferred_deleted_message_and_read_chat` (FR-663, 666);
  `::test_viewing_chat_silences_unread_notifications` (FR-666);
  `::test_general_chat_disabled_makes_still_relevant_false` (FR-651, 663)
- [x] T-8116c [P] [sonnet] тесты внешних текстов, письма и тихих часов (план: «Уведомления», «Почта и тихие
  часы») — `test_messenger_notify_3.py::test_external_text_has_no_names_or_message_text_in_telegram_max_and_push`
  (FR-664, NFR-705); `::test_email_sent_after_fifteen_minutes_if_unread` (FR-663);
  `::test_quiet_hours_hold_email_and_send_digest_at_workday_start` (FR-663);
  `::test_message_in_open_chat_not_unread_in_flow` (FR-666);
  `::test_notification_links_to_chat_message_and_deleted_chat_gives_404` (FR-663, 671);
  `::test_portal_always_on_even_with_all_channels_off` (FR-665)
- [x] T-8117a [P] [sonnet] тесты загрузки и привязки файлов (план: «Файлы и эскизы») —
  `test_messenger_files.py::test_upload_20mb_ok_and_20mb_plus_byte_refused` (FR-662, NFR-704);
  `::test_executable_and_password_archive_refused_with_reason` (FR-662);
  `::test_image_over_40_megapixels_refused_as_type` (FR-662);
  `::test_eleventh_file_refused_including_already_attached` (FR-662);
  `::test_foreign_unbound_file_id_refused_on_send` (FR-662, 669);
  `::test_31st_unbound_upload_refused` (FR-662);
  `::test_bind_uses_conditional_update_and_rolls_back_on_short_count` (FR-662);
  `::test_remove_unbound_file_deletes_row_and_file_after_commit` (FR-662)
- [x] T-8117b [P] [sonnet] тесты выдачи, эскизов и карантина (план: «Файлы и эскизы») —
  `test_messenger_files_2.py::test_clean_image_shown_thumbnail_and_full_on_click` (FR-662);
  `::test_pending_and_quarantine_not_downloadable_with_texts` (FR-662, NFR-704);
  `::test_clamav_down_keeps_message_and_file_pending_for_retry` (FR-662);
  `::test_thumb_1280_without_exif_and_gif_first_frame` (FR-662);
  `::test_thumb_path_under_protected_attachments_thumbs` (FR-662);
  `::test_foreign_chat_original_and_thumb_404` (FR-669);
  `::test_unbound_file_visible_only_to_uploader` (FR-662, 669);
  `::test_night_purge_removes_unbound_older_than_day` (FR-662, 670)
- [x] T-8118 [P] [sonnet] тесты поиска (план: «Поиск») —
  `test_messenger_search.py::test_word_in_own_chat_found_with_chat_author_time_and_snippet` (FR-668);
  `::test_word_in_foreign_chat_absent_and_not_counted` (FR-668, 669);
  `::test_provider_order_61_after_feed_and_group_title` (FR-668);
  `::test_chat_search_returns_only_its_messages_available_to_member` (FR-668);
  `::test_deleted_and_old_edited_text_not_found` (FR-657, 668);
  `::test_stop_word_gives_empty_without_error` (FR-668);
  `::test_without_messenger_no_group` (FR-668);
  `::test_search_sql_passes_words_and_unit_chain_as_parameters` (NFR-703);
  `::test_count_ceiling_300` (FR-668);
  `::test_mention_markers_do_not_break_search` (FR-668)
- [x] T-8119 [P] [sonnet] тесты срока и ночного задания (план: «Срок хранения и ночное задание») —
  `test_messenger_retention.py::test_setting_zero_eleven_and_abc_refused` (FR-670);
  `::test_message_three_years_and_one_day_deleted_with_files_and_audit_count` (FR-670, 671);
  `::test_exactly_three_years_kept` (FR-670);
  `::test_second_run_writes_no_audit_and_no_errors` (NFR-706);
  `::test_calendar_boundary_february_29_becomes_28` (FR-670);
  `::test_batches_of_1000_and_last_message_at_recalculated` (FR-670);
  `::test_unbound_attachment_older_than_24h_removed` (FR-662, 670);
  `::test_department_chat_with_missing_unit_removed_by_night_job` (FR-650, 670);
  `::test_retention_not_extended_by_edit` (FR-670);
  `::test_cron_entry_55_23_maintenance` (FR-670, NFR-706)
- [x] T-8120 [P] [sonnet] тесты настроек портала (план: «Срок хранения и ночное задание» → «Настройка»,
  «Права среза») — `test_messenger_settings.py::test_page_requires_settings_portal_403` (FR-670);
  `::test_form_shows_retention_and_general_checkbox` (FR-651, 670);
  `::test_increase_saves_immediately_and_audits_before_after` (FR-670, 671);
  `::test_decrease_needs_second_step_with_count_and_keeps_value_without_confirm` (FR-670);
  `::test_general_toggle_writes_audit_enabled_disabled` (FR-651, 671);
  `::test_out_of_range_shows_reason_and_keeps_value` (FR-670);
  `::test_settings_updated_at_and_by_saved` (FR-670)
- [x] T-8121 [P] [sonnet] тесты журнала (план: «Журнал») —
  `test_messenger_audit.py::test_six_codes_written_without_message_text` (FR-671);
  `::test_labels_of_actions_and_object_types_are_russian` (FR-671, NFR-708);
  `::test_ordinary_send_edit_delete_are_not_audited` (FR-671);
  `::test_application_role_has_no_update_or_delete_on_audit_table` (NFR-709);
  `::test_chat_deleted_records_title_members_and_created_at_only` (FR-648, 671);
  `::test_retention_purged_records_count_only` (FR-670, 671)
- [x] T-8122 [P] [sonnet] тесты данных установки (план: «Модель данных», «Риски» — миграция данных установки) —
  `test_messenger_seed.py::test_migration_creates_settings_three_years_and_general_on` (FR-651, 670);
  `::test_seed_twice_does_not_duplicate` (FR-651);
  `::test_general_chat_title_and_single_row` (FR-651);
  `::test_settings_get_creates_row_when_missing` (FR-670)
- [x] T-8123 [P] [sonnet] тесты стенда и сброса (план: «Проверка» → «данные установки и стенд») —
  `test_messenger_stand.py::test_stand_reset_returns_retention_and_general_on` (FR-651, 670);
  `::test_stand_reset_wipes_chats_messages_files_and_thumbs_after_commit` (FR-662);
  `::test_stand_reset_runs_in_migration_transaction` (FR-670);
  `::test_e2e_messenger_age_shifts_by_days_and_prints_line` (FR-670);
  `::test_stand_command_refused_without_e2e_stand` (FR-670);
  `::test_stand_reset_runs_last_and_before_feed` (FR-651)
- [x] T-8124 [P] [sonnet] тесты развёртывания (план: «Запуск», «Изменения кода прежних срезов») —
  `test_messenger_deploy.py::test_messenger_is_last_in_installed_apps` (FR-643);
  `::test_cron_has_21_registers_and_messenger_retention_55_23_maintenance` (FR-670);
  `::test_nginx_has_two_25m_locations_and_repeated_proxy_directives` (FR-662, NFR-704);
  `::test_ws_location_and_backup_script_unchanged` (FR-661);
  `::test_no_new_packages_and_no_slice_line_in_requirements` (NFR-707);
  `::test_csp_without_unsafe_inline_on_messenger_pages` (FR-673, NFR-702);
  `::test_templates_have_no_style_or_event_attributes` (NFR-702);
  `::test_texts_are_russian_and_time_is_moscow_at_utc_midnight` (NFR-708);
  `::test_load_profile_files_exist_with_three_classes` (NFR-707)
- [x] T-8125 [P] [sonnet] тесты границ модуля (план: «Сверка с конституцией», «Модуль и выключение») —
  `test_messenger_boundaries.py::test_no_previous_module_imports_apps_messenger` (FR-643);
  `::test_messenger_does_not_import_org_notify_feed_models` (FR-643, 650, 663);
  `::test_messenger_registers_points_and_no_top_bar_items` (FR-643, 667);
  `::test_without_messenger_menu_search_catalog_card_and_unit_form_have_no_trace` (FR-643, 645, 649, 667);
  `::test_asgi_without_messenger_has_no_ws_messenger` (FR-661);
  `::test_points_are_19_and_unit_form_parts_last` (FR-649);
  `::test_purposes_are_6_and_messenger_last` (FR-662);
  `::test_org_and_notify_import_no_messenger` (FR-650, 667)
- [x] T-8126a [P] [sonnet] тесты изменений ядра (план: «Изменения кода прежних срезов») —
  `test_messenger_core_changes.py::test_point_unit_form_parts_is_nineteenth_and_dataclass_fields` (FR-649);
  `::test_purpose_messenger_choice_last_and_migration_0011_depends_on_0010` (FR-662);
  `::test_core_render_plain_matches_feed_output_for_same_input` (FR-653);
  `::test_core_snippet_matches_feed_snippet_and_expand_hook` (FR-653);
  `::test_core_thumbs_build_matches_feed_path_and_size` (FR-662);
  `::test_feed_wrappers_keep_names_signatures_and_behavior` (FR-653, 662)
- [x] T-8126b [P] [sonnet] тесты изменений `org` и `notify` (план: «Изменения кода прежних срезов», «Вкладка
  „Уведомления“») — `test_messenger_core_changes_2.py::test_unit_form_renders_registered_fields_and_calls_on_saved_after_save`
  (FR-649); `::test_on_saved_own_savepoint_failure_does_not_cancel_unit_save_and_logs` (FR-649);
  `::test_unit_new_wrapped_in_atomic` (FR-649);
  `::test_structure_delete_unit_publishes_unit_deleted_after_delete` (FR-650);
  `::test_notify_bell_link_present_only_with_messenger` (FR-667);
  `::test_notify_list_fragment_50_per_page_filter_and_pages` (FR-667);
  `::test_old_notifications_address_redirects_with_f_and_page` (FR-667)
- [x] T-8127 [P] [sonnet] тесты галочки формы узла (план: «Точки расширения ядра», «Виды чатов и создание» — чат
  отдела) — `test_messenger_unit_form.py::test_checkbox_only_for_department_not_team_or_root` (FR-649);
  `::test_checkbox_checked_creates_chat_after_save` (FR-649);
  `::test_second_save_shows_chat_created_instead_of_checkbox` (FR-649);
  `::test_unchecked_keeps_no_chat` (FR-649);
  `::test_handler_error_logged_and_unit_saved` (FR-649);
  `::test_without_messenger_form_has_no_field` (FR-643, 649)
- [x] T-8130 [sonnet] обвязка приёмки `backend/tests/e2e/helpers_messenger.py` (единственный автор): роли и учётки
  13 сценариев (два сотрудника, третий вне чата, создатель группы, администратор портала, уволенный, отдел с
  вложенным и другой отдел) через `helpers.py` и `helpers_org.py`; `open_messenger(context, account)`,
  `open_chat(context, account, chat_id)`, `write(chat, text)` и `try_write`, загрузка файла и ожидание
  «проверяется → чистый», EICAR из частей, `mention(context, name)` и `chat_mention(name)`, цитата, чтение
  `#chat-<id>-unread[data-count]` и `#menu-badge-messenger[data-count]` с ожиданием значения, ожидание кадра по
  `data-message-id`, `age(days)` над `e2e_messenger_age --days N` через `helpers_sd._stand_command` с разбором
  `messenger_age: aged=<N>`, `block_ws(context)` для `/ws/messenger/` и `/ws/notify/` (`route_web_socket`,
  Playwright 1.63), проверка ширины 360 px. Имена одни для T-8131…T-8143 — backend/tests/e2e/helpers_messenger.py —
  (план: «Проход в браузере»)
- [x] T-8131 [P] [sonnet] приёмка сценария 1 (личный диалог): `test_m01_personal.py` — диалог один из мессенджера и
  из карточки, новое сообщение у собеседника ≤ 2 с, счётчик обнуляется и автор видит «Прочитали N из M», порядок
  трёх чатов, история 60 порциями без потери места, пустое поле и 4 001 знак отклонены — (FR-644, 645, 652, 658, 659, 660)
- [x] T-8132 [P] [sonnet] приёмка сценария 2 (групповой чат): `test_m02_group.py` — создание с двумя участниками,
  пустое и 201-значное название, выход участника, выход создателя, удаление с подтверждением и журнал без текста,
  выход последнего — (FR-646, 647, 648, 671)
- [x] T-8133 [P] [sonnet] приёмка сценария 3 (чат отдела): `test_m03_department.py` — галочка при создании узла,
  системные записи, состав с вложенным отделом, перевод сотрудника, приём новичка и история, удаление узла и
  администратором — (FR-649, 650, 671, 672)
- [x] T-8134 [P] [sonnet] приёмка сценария 4 («Общий чат»): `test_m04_general.py` — есть после установки, выключение
  убирает из списка и поиска, прямой адрес 404, включение возвращает историю, две записи журнала — (FR-651, 671)
- [x] T-8135 [P] [sonnet] приёмка сценария 5 (правка, удаление, цитата): `test_m05_edit_delete.py` — «изменено» у
  автора и собеседника ≤ 2 с, «Сообщение удалено» со временем, у чужого нет меню и прямой запрос отклонён, цитата в
  поле ввода и без второго уровня, ссылки и экранирование — (FR-653, 654, 656, 657, 661)
- [x] T-8136 [P] [sonnet] приёмка сценария 6 (упоминания): `test_m06_mentions.py` — «@» показывает только участников
  и свои чаты, выбранный виден как `@ФИО`/`#название`, на сервер уходит маркер, в личном подсказки нет, упоминание
  чата ссылкой, уведомление только упомянутому — (FR-655, 664)
- [x] T-8137 [P] [sonnet] приёмка сценария 7 (файлы): `test_m07_files.py` — картинка эскизом и полная по нажатию,
  11-й файл отклонён, EICAR в карантине и помечен, исполняемый и архив с паролем отклонены, «проверяется» без
  скачивания, ClamAV стенда ≤ 1 минуты — (FR-662, NFR-704)
- [x] T-8138 [P] [sonnet] приёмка сценария 8 (непрочитанное и живые обновления): `test_m08_unread.py` — две вкладки,
  `time.monotonic()` до появления сообщения и чисел, `elapsed ≤ 2 с`, `#chat-<id>-unread` и `#chat-<id>-preview`
  обновляются, общий счётчик, «Прочитали N из M» у последнего своего — (FR-659, 660, 661, 666, NFR-701)
- [x] T-8139 [P] [sonnet] приёмка сценария 9 (колокольчик и уведомления): `test_m09_notify.py` — колокольчик ведёт на
  вкладку «Уведомления», старый адрес открывает её же, отключённая почта не мешает порталу, тихие часы и сводка,
  склейка, открытая беседа не копит непрочитанное, внешний канал без текста и имён — (FR-663, 664, 665, 666, 667)
- [x] T-8140 [P] [sonnet] приёмка сценария 10 (поиск): `test_m10_search.py` — группа «Мессенджер» только по своим
  чатам, чат, автор, время и строка, поиск по беседе, чужое не находится — (FR-668, 669)
- [x] T-8141 [P] [sonnet] приёмка сценария 11 (срок хранения): `test_m11_retention.py` — `age`, удаление с файлами,
  запись журнала без текста, повтор без записей, уменьшение срока с подтверждением, правка удалённого отклонена —
  (FR-670, 671, NFR-706)
- [x] T-8142 [P] [sonnet] приёмка сценария 12 (телефон 360 px): `test_m12_phone.py` — одна колонка без
  горизонтальной прокрутки, переход в беседу и «Назад» к списку, две колонки на широком окне — (FR-673, NFR-702)
- [x] T-8143 [P] [sonnet] приёмка сценария 13 (неприкосновенность): `test_m13_rights.py` — администратор получает 404
  на чужой диалог, не находит его поиском, файл чужого чата 404, уволенный не входит — (FR-643, 669)
- [x] T-8150 [P] [sonnet] нагрузочный профиль (план: «Нагрузка»; замер — T-8304 после решения владельца):
  `backend/tests/load/fill_messenger.py` (только при `E2E_STAND=1`): 200 чатов, 50 000 сообщений, распределение
  участников и вложений, строка итога `fill_messenger: chats=… messages=… files=…`; в `tests/load/locustfile.py` —
  класс `MessengerUser` (100 вошедших, два соединения на вкладку, список, история курсором, беседа, поиск по беседе
  и сквозной, подсказка «@», отправка короткая и 4 000 знаков, правка, удаление, прочтение, файл; один поток
  публикует и запоминает `{номер: monotonic}`; событие `WS messenger frame`); `FeedUser` и `NotifyUser` не меняются.
  Генераторы и locust не запускаются — backend/tests/load/fill_messenger.py, backend/tests/load/locustfile.py —
  (NFR-701, NFR-707)
- [x] T-8159 [opus] подготовка стенда к прогонам среза (после T-8007, до T-8160; решения 5, 16): с разрешения
  владельца — копия стенда `backup-stand.sh` до первого сброса; проверка служб `clamav` (сигнатуры загружены),
  `fakebots`, Mailpit, worker-ов RQ (после сна ноутбука — перезапуск); новых зависимостей и переменных нет; образ
  пересобирается только с кодом среза (T-8260) — отчёт docs/reviews/TASKS-008.md, раздел «Стенд» — (план: «Запуск»)
- [x] T-8160 [opus] красный прогон (после T-8102…T-8150 и T-8159): весь серверный набор и приёмка среза на стенде
  (сброс перед кругом, `systemd-run --user`): новые тесты падают по ожидаемой причине (нет кода среза); тесты
  001–007 зелёные, кроме перечня T-8007 — он исправлен под 008 и падает по той же причине (отдельной строкой);
  отдельной строкой — тесты перечня, зеленеющие только в Этапе 3 (точки, назначение, хвост `INSTALLED_APPS`, cron,
  nginx, колокольчик, 302, стенд; решение 12); отдельной строкой — «Проверить после реализации» плана; приёмка
  прежних срезов — Chromium и Яндекс Браузер (`-k`); сводка «тест → причина» и эталон для регрессии — отчёт
  docs/reviews/TASKS-008.md, раздел «Красный прогон» — (FR-643…673, NFR-701…709)

## Этап 3 — реализация

Партии по механизмам плана и зависимостям (решение 11). После каждой партии — весь серверный набор; падение теста
прежнего среза останавливает партию (решение 12). Код — только SQL с параметрами; тексты отказов, адреса, зацепки
`data-*`, коды закрытия и сообщения слоя — дословно из `CONTRACT-008.md`. Общие файлы — один автор за раз.

**Партия 1 — модели, назначение файла, данные установки**

- [x] T-8200 [sonnet] назначение файла ядра и модели (план: «Модель данных» → «Ядро и прежние модули», «Приложение `messenger`»; «Изменения кода прежних
  срезов»): `StoredFile.Purpose.MESSENGER = "messenger"` («вложение сообщения чата») в конце и миграция `core/0011_storedfile_messenger_purpose.py`
  (`AlterField`, как `0010`); все модели таблицы плана с проверками и индексами (`Chat` — проверки вида, `UniqueConstraint(pair_key)` и `(unit_id)`
  частичные, `(kind)` для общего, индексы `(-last_message_at, -id)` и `created_by`; `ChatMember` — уникальность (`chat`, `user`), частичный индекс (`user`,
  `chat`) без выхода; `ChatRead` — уникальность и индекс; `Message` — проверки «системная ⇔ без автора» и «удалено ⇒ текст пуст», `quote` SET_NULL, индексы
  (`chat`, `-created_at`, `-id`), (`created_at`), GIN по `search`; `MessageAttachment` — OneToOne на `StoredFile` PROTECT, частичный индекс непривязанных;
  `MessengerSettings` — проверка 1…10) и миграция `messenger/0001_initial.py` (зависит от `core 0011`, имена индексов ≤ 30 знаков). Сначала обе миграции на
  PostgreSQL 17 тестового контейнера. Тесты: `test_messenger_models.py`, `test_messenger_core_changes.py` (назначение), прежний `test_core_uploads.py` —
  backend/apps/core/models/files.py, backend/apps/core/migrations/0011_*, backend/apps/messenger/models.py,
  backend/apps/messenger/migrations/0001_initial.py — (FR-643, 645–651, 654, 657–662, 670)
- [x] T-8201 [sonnet] данные установки и тексты (план: «Модель данных», «Тексты отказов»): `messenger/migrations/0002_initial_data.py` (зависит от `core
  0002_initial_data` и `messenger 0001`) — строка `MessengerSettings(pk=1, retention_years=3, general_chat_enabled=True)`, если её нет, и «Общий чат»
  (`kind="general"`) через `get_or_create` под уникальным индексом; повторный запуск ничего не дублирует; `messenger_settings.get()` создаёт строку при
  отсутствии; `messenger/texts.py` — все тексты раздела дословно одним словарём. Тесты: `test_messenger_seed.py`, `test_messenger_models.py` (часть) —
  backend/apps/messenger/migrations/0002_initial_data.py, backend/apps/messenger/services/messenger_settings.py,
  backend/apps/messenger/texts.py —
  (FR-651, 670)

**Партия 2 — службы чатов, личные, групповые, отдел, общий**

- [x] T-8202 [sonnet] службы участия и видимости (план: «Состав чата», «Права и неприкосновенность»): `services/errors.py` (`MessengerError`),
  `services/members.py` — `members(chat)`, `is_member`, `can_write`, `visible_chats(user)`, `get_chat(user, chat_id)` (невидимый, несуществующий и
  удалённый — одинаковый `Http404`), `services/chats.py` — создание личного (`pair_key`, `get_or_create` с перехватом `IntegrityError`), группового,
  выборка списка одним запросом `LATERAL` с порядком `COALESCE(last_message_at, created_at) DESC, id DESC`. Тесты: `test_messenger_chats.py`,
  `test_messenger_personal.py` (часть), `test_messenger_page.py` (часть) — backend/apps/messenger/services/members.py,
  backend/apps/messenger/services/chats.py, backend/apps/messenger/services/errors.py — (FR-643, 644, 645, 646, 650, 651, 669, NFR-703)
- [x] T-8203 [sonnet] личный диалог, поиск людей, «?to» (план: «Виды чатов и создание», «Список чатов и порядок»): `POST /messenger/chats/` с
  `kind=personal&user=<id>`, `GET /messenger/people/?q=` (до 20 действующих, ФИО и подразделение, без уволенных), `GET /messenger/?to=<id>` без записи в
  базу, `views/chats.py`, шаблон поля ввода с адресатом; диалог с уволенным не создаётся, существующий — только чтение. Тесты:
  `test_messenger_personal.py`, `test_messenger_chats.py` (часть) — backend/apps/messenger/views/chats.py, backend/apps/messenger/urls.py,
  backend/templates/messenger/_form.html, backend/templates/messenger/page.html — (FR-644, 645)
- [x] T-8204 [sonnet] групповой чат и выход (план: «Виды чатов и создание» — групповой; «Журнал»): `POST /messenger/chats/` с `kind=group` (название 1–200
  после среза пробелов, участники — действующие, создатель входит), `POST /messenger/chats/<id>/members/` (`add`, `remove`; после выхода создателя — 403),
  `/leave/` с `confirm=1` (последний участник — удаление чата), `/delete/` создателем с подтверждением и журналом `messenger.chat_deleted` без текста,
  удаление файлов и эскизов после фиксации. Тесты: `test_messenger_group.py`, `test_messenger_audit.py` (часть) — backend/apps/messenger/views/chats.py,
  backend/apps/messenger/services/chats.py — (FR-646, 647, 648, 671)
- [x] T-8205 [sonnet] чат отдела (план: «Состав чата отдела и перевод/приём», «Системные записи чата отдела», «Точки расширения ядра»):
  `services/department.py` — создание по галочке (название из узла через `unit_refs`, две системные записи, повторно не создаётся), состав
  `subtree_member_ids`, удаление через обработчик `unit.deleted` с журналом `messenger.unit_chat_deleted`, удаление администратором портала
  (`settings.portal`) с журналом `messenger.department_chat_deleted`, в `unit_usage` не регистрируется; `unit_form.py` — запись `UnitFormPart` («Создадим
  чат для всего отдела») и её регистрация в `extensions.py`, подписка на `unit.deleted` в `apps.py`; страховка — шаг (4) ночного задания (T-8220).
  Тесты: `test_messenger_department.py`, `test_messenger_unit_form.py`, `test_messenger_core_changes_2.py` (часть),
  `test_messenger_audit.py` (часть) — backend/apps/messenger/services/department.py, backend/apps/messenger/unit_form.py,
  backend/apps/messenger/extensions.py, backend/apps/messenger/apps.py,
  backend/templates/messenger/_unit_form_field.html — (FR-649, 650, 671, 672)
- [x] T-8206 [sonnet] «Общий чат» и настройки портала (план: «Виды чатов и создание» — «Общий чат», «Срок хранения и ночное задание» → «Настройка»):
  `GET/POST /settings/messenger/` под `settings.portal` (поле срока хранения — T-8220; здесь галочка «Общий чат включён» и сохранение), выключение убирает
  чат из списка и поиска, прямой адрес — 404, обычный POST отправки — 404, HTMX — 200 с причиной «Чат отключён», история сохраняется; журнал
  `messenger.general_changed`; записи меню (`order` 1 с `badge` и `live_badge`, `order` 64) — в T-8211, когда есть
  `unread.badge`. Тесты: `test_messenger_general.py`, `test_messenger_settings.py` (часть) —
  backend/apps/messenger/views/settings.py, backend/apps/messenger/services/chats.py,
  backend/templates/messenger/settings.html — (FR-651, 671)

**Партия 3 — беседа, история, отправка, правка, удаление, цитата, «@»**

- [x] T-8207 [sonnet] страница и список (план: «Список чатов и порядок», «Беседа и история порциями»): `GET /messenger/` и `GET /messenger/list/`
  (название, превью `snippet` 100, время, число непрочитанных, `q` по названиям и ФИО), `services/page.py` (`chat_title`), шаблоны `page.html`,
  `_list.html`, `_search.html`; пустой список — подсказка; вкладки «Чаты»/«Уведомления» (вторая — T-8218). Тесты: `test_messenger_page.py` (часть),
  `test_messenger_personal.py` (часть) — backend/apps/messenger/views/pages.py, backend/apps/messenger/services/page.py,
  backend/templates/messenger/page.html, _list.html — (FR-644, 658, NFR-708)
- [x] T-8208 [sonnet] беседа и история курсором (план: «Беседа и история порциями», «360 px и две колонки»): `GET /messenger/chats/<id>/` (шапка, история
  50, поле ввода, узел `/ws/messenger/?chat=<id>`), `GET /messenger/chats/<id>/messages/?before=<ISO>,<id>` (`WHERE (created_at, id) < (%s, %s) LIMIT 50`,
  без `OFFSET`), шаблоны `_chat.html`, `_message.html`, `_files.html`, `_mention_suggest.html`; `messenger.css` — две колонки от 900 px и одна до 900 px;
  `_assets.html` подключает статику среза. Тесты: `test_messenger_page.py`, `test_messenger_consumers.py` (часть), e2e `m01`, `m12` —
  backend/apps/messenger/views/pages.py, backend/templates/messenger/_chat.html, _message.html, backend/static/messenger/messenger.css,
  backend/templates/_assets.html — (FR-658, 673)
- [x] T-8209 [sonnet] отправка, правка, удаление, цитата (план: «Отправка, правка, удаление, цитата»): `services/messages.py` — участие, текст после среза
  пробелов, NUL, предел 4 000, цитата только этого чата и один уровень, правка только автором и только живого сообщения, удаление с `deleted_at`,
  `text=''`, пустым вектором, удалением вложений и пересчётом `last_message_at`, всё в одной транзакции с `select_for_update`; `services/text.py` — обёртка
  над `core.services.text` с шаблонами `@[u<id>]`/`@[c<id>]`; `views/messages.py`; после фиксации — постановка рассылки (T-8212). Тесты:
  `test_messenger_messages.py`, `test_messenger_messages_2.py`, `test_messenger_text.py` (часть) — backend/apps/messenger/services/messages.py,
  backend/apps/messenger/services/text.py, backend/apps/messenger/views/messages.py — (FR-652, 653, 654, 656, 657, NFR-703)
- [x] T-8210 [sonnet] упоминания «@» (план: «Упоминания „@“»): `services/mentions.py` (`extract`, проверка участия, предел 20 разных людей), `GET
  /messenger/mentions/?chat=<id>&q=` (до 20 участников и своих чатов, в личном — пусто, пустой запрос — пусто), `views/mentions.py`, разметка
  `[data-mention]` и ссылка на чат; `messenger.js` — выбор из подсказки как `@ФИО`/`#название` с подстановкой маркеров перед отправкой. Тесты:
  `test_messenger_mentions.py`, `test_messenger_text.py` (часть), e2e `m06` — backend/apps/messenger/services/mentions.py,
  backend/apps/messenger/views/mentions.py, backend/templates/messenger/_mention_suggest.html, backend/static/messenger/messenger.js — (FR-655)

**Партия 4 — прочтение, счётчики, живые обновления**

- [x] T-8211 [sonnet] прочтение и числа (план: «Прочтение и счётчики»): `services/read.py` (отметка `min(max(прежняя, at), now())`, «Прочитали N из M»
  только у последнего своего сообщения), `services/unread.py` (числа по чатам и общее, кэш 5 с с версией, сброс при отправке, прочтении и смене состава),
  `POST /messenger/chats/<id>/read/` (узел числа чата, общее число, строка прочитавших), `object.viewed` при открытии и отметке, сброс кэша по
  `access.changed` (подписка — в `apps.py`); записи `menu_items` («Мессенджер» `order` 1 с `badge=unread.badge`, `live_badge="messenger"`,
  «Настройки мессенджера» `order` 64, `settings.portal`) в `extensions.py`; узел числа пункта меню `#menu-badge-messenger` («99+»). Тесты:
  `test_messenger_read.py`, `test_messenger_unread.py`, e2e `m08` — backend/apps/messenger/services/read.py,
  backend/apps/messenger/services/unread.py, backend/apps/messenger/views/chats.py, backend/apps/messenger/extensions.py,
  backend/apps/messenger/apps.py — (FR-659, 660, 666)
- [x] T-8212 [sonnet] рассылка заданием (план: «Живые обновления и рассылка»): `services/live.py` — получатели `members(chat)` на момент рассылки, один
  рендер на роль (`author`/`reader` × `link_staff`), одно сообщение слоя `messenger.event` с `counts`, `total`, `variants`, `meta`, группы
  `messenger.u.{id}` через `publish` (таймаут 2 с), ошибки — предупреждением; `tasks.publish_event` в очередь `notify` через `transaction.on_commit`; кадр
  `notify.html` в `notify.u.{id}` с числом пункта меню и OOB-строками списка. Тесты: `test_messenger_live.py`, `test_messenger_unread.py` (часть) —
  backend/apps/messenger/services/live.py, backend/apps/messenger/tasks.py, backend/templates/messenger/_badge.html — (FR-660, 661, NFR-701)
- [x] T-8213 [sonnet] соединение и клиент (план: «Живые обновления и рассылка» → `MessengerConsumer`, «Без WebSocket»): `MessengerConsumer`
  (`SessionGuardMixin`, `CHECK_INTERVAL = 25`, группа `messenger.u.{id}`, `chat` обязателен, 4400/4404/4401/1009/1011/1013, кадры
  `new`/`edit`/`delete`/`read`/`chat_delete`, `HX-Redirect`), `routing.py`, `config/asgi.py`, `messenger.js` — `sync` и `read`, вставка кадров, сохранение
  места при догрузке, `data-ws="open"` по `#messenger-synced`; страница работает и без соединения. Тесты: `test_messenger_consumers.py`,
  `test_messenger_live.py` (часть), e2e `m08` — backend/apps/messenger/consumers.py, backend/apps/messenger/routing.py, backend/config/asgi.py,
  backend/static/messenger/messenger.js — (FR-656, 657, 659, 660, 661, NFR-701)
- [x] T-8214 [sonnet] «Написать» из карточки сотрудника (план: «Написать из карточки сотрудника»): запись `card_sections`
  (`template="messenger/_card_write.html"`, раздел «Переписка»), кнопка ведёт на `/messenger/?to=<id>`, скрыта для себя и уволенного; запись в
  `extensions.py`. Тесты: `test_messenger_personal.py` (часть), e2e `m01` — backend/apps/messenger/extensions.py,
  backend/templates/messenger/_card_write.html — (FR-645)

**Партия 5 — файлы**

- [x] T-8215 [sonnet] загрузка и привязка (план: «Файлы и эскизы»): `POST /messenger/files/` (multipart, поля `chat`, `have`, отказы 20 МБ, тип, 10 к
  сообщению, 30 непривязанных), `core.uploads.reject_reason` и `core.uploads.store(..., "messenger")`, строка `MessageAttachment(message=NULL)`, привязка
  условным `UPDATE … WHERE message_id IS NULL AND uploaded_by = <я>` с проверкой числа строк и откатом, предел 10 под `select_for_update`; `POST
  /messenger/files/<id>/delete/`; шаблон «таблетки». Тесты: `test_messenger_files.py` (часть) — backend/apps/messenger/services/files.py,
  backend/apps/messenger/views/files.py, backend/templates/messenger/_files.html — (FR-662, 669, NFR-704)
- [x] T-8216 [sonnet] назначение, эскизы, выдача и карантин (план: «Файлы и эскизы»): регистрация `FilePurpose` `messenger` в `extensions.py` (ожидание,
  «чистый» — перенос в `attachments/` и эскиз `core.services.thumbs.build`, «карантин»), `GET /messenger/files/<id>/` и `/thumb/` (сначала участие через
  `get_chat`, потом состояние, `X-Accel-Redirect`, `nosniff`, `no-store`), показ состояний «проверяется»/«карантин»/«чистый», сбой ClamAV — файл ждёт
  повтора. Тесты: `test_messenger_files.py`, `test_messenger_files_2.py`, e2e `m07` — backend/apps/messenger/services/files.py,
  backend/apps/messenger/views/files.py, backend/apps/messenger/extensions.py — (FR-662, 669, NFR-704)

**Партия 6 — уведомления и вкладка**

- [x] T-8217 [sonnet] виды, правила, склейка, `still_relevant` (план: «Уведомления»): `notify_kinds.py` (два вида, `order` 80/81, каналы портал и почта,
  постоянный внешний текст, `coalesce`/`coalesce_text` только у `messenger.message`), `services/notify_rules.py` (`decide`: все участники без автора,
  упомянутый — только mention), тексты без отрывка, ссылка `/messenger/chats/<id>/#m<id>`, `object_ref = "messenger.chat:<id>"`, `still_relevant` перед
  письмом и сводкой; регистрация `notification_kinds`. Тесты: `test_messenger_notify.py`, `test_messenger_notify_2.py`, `test_messenger_notify_3.py`, e2e
  `m06`, `m09` — backend/apps/messenger/notify_kinds.py, backend/apps/messenger/services/notify_rules.py, backend/apps/messenger/extensions.py — (FR-663,
  664, 665, 666, NFR-705, NFR-708)
- [x] T-8218 [sonnet] вкладка «Уведомления» и адреса (план: «Вкладка „Уведомления“ и совместимость адресов»): `GET /messenger/notifications/` (серверный
  рендер первой страницы тем же шаблоном `notify/_list_body.html`, вкладки), `templates/messenger/_notifications.html`; в `notify` — выделение
  `notify/_list_body.html` из `list.html` (include, поведение прежнее) и фрагмент `GET
  /notifications/list/` (50 на страницу, `f`, `page`), признак `bell_link` в `top_bar_context`, 302 `/notifications/` при установленном мессенджере с
  сохранением `f` и `page`, шаблоны `bell.html` (ссылка `[data-bell-link]`) и `_bell_panel.html`. Тесты: `test_messenger_core_changes_2.py` (часть),
  `test_messenger_notify_2.py` (часть), e2e `m09` — backend/apps/messenger/views/notifications.py, backend/apps/notify/urls.py,
  backend/apps/notify/views/pages.py, backend/templates/notify/bell.html — (FR-667)

**Партия 7 — поиск**

- [x] T-8219 [sonnet] поиск (план: «Поиск»): `services/search.py` — векторы `to_tsvector('russian', …)` с `regexp_replace` маркеров, пересчёт в отправке,
  правке и удалении, `SearchProvider(key="messenger", title="Мессенджер", order=61)` с видимостью в том же SQL (участие, цепочка узлов, включённый общий
  чат), строка выдачи с датой по Москве, `ts_headline` для беседы, `count` с потолком 300; `GET /messenger/chats/<id>/search/?q=`; регистрация
  `search_providers`. Тесты: `test_messenger_search.py`, e2e `m10` — backend/apps/messenger/services/search.py, backend/apps/messenger/views/messages.py,
  backend/apps/messenger/extensions.py — (FR-668, 669, NFR-703)

**Партия 8 — журнал и срок**

- [x] T-8220 [sonnet] срок и ночное задание (план: «Срок хранения и ночное задание»): поле срока на странице настроек (1–10, при уменьшении — число к
  удалению и «Подтвердить»), журнал «было / стало», `services/retention.py` (календарная граница, пачки 1 000, непривязанные старше 24 часов, пересчёт
  `last_message_at`, сброс кэша, чаты отдела с несуществующим узлом, журнал только при N > 0), `tasks.retention_night` и запись `register(...,
  queue_name="maintenance", cron="55 23 * * *", name="messenger_retention", job_timeout=600)` в `config/cron.py` под проверкой установки. Тесты:
  `test_messenger_retention.py`, `test_messenger_settings.py`, `test_messenger_deploy.py` (часть), e2e `m11` —
  backend/apps/messenger/services/retention.py, backend/apps/messenger/tasks.py, backend/apps/messenger/views/settings.py, backend/config/cron.py —
  (FR-670, 671, NFR-706)
- [x] T-8221 [sonnet] подписи журнала и проверка шести кодов (план: «Журнал»): `audit_labels.py` — подписи действий и типов объектов `messenger.*`; сверка
  всех шести кодов (удаление группового, удаление чата отдела, удаление узла, включение/выключение общего чата, срок, удаление по сроку) и отсутствия
  текста сообщений; регистрация `audit_labels` в `extensions.py`. Тесты: `test_messenger_audit.py`, `test_messenger_deploy.py` (часть) —
  backend/apps/messenger/audit_labels.py, backend/apps/messenger/extensions.py — (FR-648, 671, NFR-708, NFR-709)

**Партия 9 — 360 px и клиентские решения**

- [x] T-8222 [sonnet] узкий экран и поведение страницы (план: «360 px и две колонки»): `messenger.css` — `overflow-wrap: anywhere` у текста и имён файлов,
  `max-width: 100%` у эскизов, перенос поля ввода и файлов, одна колонка до 900 px; `messenger.js` — кнопка «Назад» на `/messenger/`, сохранение места при
  догрузке истории, счёт знаков, цитата в поле ввода, возврат к списку на телефоне; шаблоны без `style=` и `on…=`. Тесты: e2e `m05`, `m12`,
  `test_messenger_deploy.py` (часть) — backend/static/messenger/messenger.css, backend/static/messenger/messenger.js,
  backend/templates/messenger/_chat.html — (FR-654, 673, NFR-702)

**Партия 10 — развёртывание, стенд, сборка**

- [x] T-8223 [P] [sonnet] развёртывание (план: «Запуск»): `location ~ ^/messenger/files/$` с `client_max_body_size 25m` и повтором `proxy_*` в
  `deploy/nginx.conf` и `deploy/nginx.prod.conf` (общий предел 6m не меняется, `/ws/` прежний, `backup.sh` без правок). Тесты: `test_messenger_deploy.py`,
  прежний `test_deploy_files.py` (в виде после T-8007) — deploy/nginx.conf, deploy/nginx.prod.conf — (FR-662, NFR-704)
- [x] T-8224 [P] [sonnet] стенд и сброс (план: «Проверка» → «данные установки и стенд»; решения 5, 16): `stand_reset()` — строки `messenger`,
  `core.StoredFile` назначения `messenger`, файлы и эскизы после фиксации, срок 3, общий чат включён; регистрация последней записью `stand_reset` в
  `extensions.py` (сброс зовёт функции в обратном порядке); команда `e2e_messenger_age` из T-8008 доводится до работы с моделями. Тесты:
  `test_messenger_stand.py`, прежние тесты порядка сброса (T-8007) — backend/apps/messenger/stand.py, backend/apps/messenger/extensions.py — (FR-651, 662,
  670)
- [x] T-8260 [opus] сборка зелёного прогона (после T-8200…T-8224): довести до зелёного все тесты Этапа 2 и весь набор срезов 001–007; ни один тест не
  ослаблен; расхождения с планом — в раздел решений до правки кода; отчёт docs/reviews/TASKS-008.md, раздел «Сборка зелёного» — (FR-643…673, NFR-701…709)

## Этап 4 — финальная проверка

- [x] T-8300 [opus] полный прогон сервера на PostgreSQL в контейнере (вместе со срезами 001–007; `systemd-run --user`): сверить красный прогон T-8160 с
  зелёным, ни одного пропущенного и ослабленного теста; отдельной строкой — «Проверить после реализации» плана (`test_permissions.py`, `test_sd_access.py`,
  `test_feed_home.py`, e2e `test_o_*`, `test_notify_admin.py`, e2e `test_d09_settings.py`, `test_k09_notify.py` — при падении остановка, решение 14);
  сводка по FR и NFR — docs/reviews/TASKS-008.md, раздел «Прогон тестов» — (FR-643…673, NFR-701…709)
- [x] T-8301 [opus] проход в браузере руками по 13 сценариям спеки (после T-8260; при изменениях кода после T-8260 стенд обновляет Opus с разрешения
  владельца, после копии): личный диалог, группа, отдел, общий чат, правка и удаление, «@», файлы, счётчики в двух окнах, колокольчик и вкладка, поиск,
  срок, 360 px, права; в консоли нет ошибок CSP и `htmx:oobErrorNoTarget`; кадры — вне git — docs/reviews/TASKS-008.md, раздел «Проход в браузере» —
  (FR-643…673, NFR-702, NFR-708)
- [x] T-8302 [opus] приёмка Playwright из `CRM/.venv` со сбросом стенда перед каждым кругом (пустой стенд; после сна ноутбука — перезапуск worker-ов RQ;
  `systemd-run --user`): срез 008 (`test_m01…m13`) кругами Chromium, Firefox, Edge и Яндекс Браузер (в том числе замер `m08` ≤ 2 с в каждом браузере);
  срезы 001–007 — Chromium и Яндекс Браузер (`-k`, правило владельца 2026-10-21); `tests/e2e/conftest.py` не правится — docs/reviews/TASKS-008.md, раздел
  «Приёмка» — (NFR-701, NFR-702)
- [x] T-8303 [P] [opus] `python3 tools/sdd.py проверить`, `python3 -m unittest discover -s tools -p "test_*.py"`, `tools/test_constitution.py` по
  `backend/` и `deploy/`, `tools/check_secrets.py` по дереву, `tools/verify_vendor.py` (новой сторонней статики нет), `git diff --check` — вывод в
  docs/reviews/TASKS-008.md — (конституция: «стек», «модуль-приложение», «секреты-вне-кода», «sql-только-параметры»; NFR-703)
- [ ] T-8304 [opus] нагрузка NFR-707 — только после отдельного решения владельца, на остывшей машине по правилам T-7304 (`run4.sh`: копия стенда и сброс,
  `vmstat`/`mpstat`/`pidstat`, стенд на потоках 0–2, locust на потоке 3): `fill_messenger.py`, прогон `MessengerUser` и смешанный со всеми классами;
  пороги: страницы и фрагменты p95 ≤ 500 мс, кадр до последнего получателя p95 ≤ 2 с, поиск ≤ 1 с, 5xx нет; заодно время отправки, CPU и память `web`,
  очереди Valkey, пачка ночного задания; NFR-612 среза 007 остаётся известным дефектом — docs/reviews/TASKS-008.md, раздел «Нагрузка» — (NFR-701, NFR-707)
- [x] T-8305 [opus] наблюдения на стенде (с разрешения владельца, после копии): (1) адрес слоя `publish` — закрытый порт: отправка быстрее 3 с, сообщение
  цело, предупреждение в журнале, вкладки работают обычными запросами; (2) пауза Valkey на 60 с — время ответа, поведение очередей, возврат вкладок; (3)
  код закрытия соединений при обновлении службы `web` (`up -d --no-deps web`) — вкладки мессенджера и колокольчик возвращаются сами; иной код, чем
  1012/1006, — остановка и вопрос Opus — docs/reviews/TASKS-008.md, раздел «Наблюдения на стенде» — (FR-661, NFR-701)
- [x] T-8306 [opus] (после T-8304 и T-8305) смысловая проверка инвариантов по диффу среза: «модуль-приложение» (границы импорта, 19 точек, `is_installed` у
  `org`, `notify`, маршрутов, cron; `top_bar_items` без мессенджера), «настройка-без-кода» (срок, общий чат, каналы — данные), «интеграции-через-адаптеры»
  (ClamAV, слой `publish`), «аудит-изменений» (без текста сообщений, только дополнение), «пдн-152фз» (невидимое = несуществующее, внешние каналы без текста
  и имён, срок 3 года), «секреты-в-url» (только номера и ключи), «sql-только-параметры», «двухфакторная-авторизация» (соединение); каждый изменённый файл
  прежних срезов есть в таблице плана и в решении 11, у каждого — тест прежнего поведения; лишних правок нет — docs/reviews/TASKS-008.md, раздел
  «Инварианты» — (конституция; FR-643, 649, 650, 661, 667, 669, 671, NFR-703, NFR-705, NFR-709)
- [x] T-8307 [opus] прохождение требований спеки: таблица FR-643…673 и NFR-701…709 → тест → результат → ссылка на реализацию; NFR-707 считается выполненным
  только после T-8304 (замер с согласия владельца); отметить `[x]` в этом файле, отчёт docs/reviews/TASKS-008.md и перевод в «на-проверке» (`sdd.py
  на-проверку`); подпись ставит человек — docs/reviews/TASKS-008.md — (FR-643…673, NFR-701…709)
- [ ] T-8308 [человек] ручной проход критерия успеха «личный диалог от „Написать“ до первого сообщения — не дольше 1 минуты» с замером; отметка в отчёте —
  docs/reviews/TASKS-008.md, раздел «Ручной проход» — (FR-645)
- [ ] T-8309 [человек] принять срез по отчёту T-8307 и проходам T-8301, T-8308; если после подписи менялся текст задач — подписать заново; `git push`
  делает владелец — docs/reviews/TASKS-008.md — (инвариант «спека-прежде-кода»)

## Решения Opus по задачам

План этих деталей не задал; ниже — решения, принятые при сборке задач. Владелец принимает их подписью под задачами
(после ревью). Решения плана и владельца здесь только называются со ссылкой.

1. **Номера и имена файлов.** Задачи — T-8001…, T-8102…, T-8200…, T-8300…. Серверные тесты — `test_messenger_<тема>.py` по 26 темам раздела плана
   «Серверные тесты»; заранее поделены пять: `messages` (`_2`), `notify` (`_2`, `_3`), `files` (`_2`), `core_changes` (`_2`) — итого 31 файл на
   T-8102…T-8127. Приёмка — `test_m01_personal.py` … `test_m13_rights.py` (буква `m` свободна); нагрузка — `fill_messenger.py` и `MessengerUser`.
   Имена тестов — английские `snake_case`; файл тестов — у одной задачи; больше ~25 тестов — второй файл и строка `T-81NNa`/`b`. Причина: план
   называет темы и буквы `m`, а окончания не смешиваются с `s/o/d/e/k/l/f` прежних срезов.
2. **Контракт и общие помощники.** `CONTRACT-008.md` — одна задача (T-8002), `support_messenger.py` — одна задача (T-8003),
   `helpers_messenger.py` — T-8130. Opus проверяет контракт до T-8003. Тесты проверяют только SPEC-008, PLAN-008 и решения этого раздела. Причина: все
   тесты среза опираются на одни имена; так было в срезах 005–007.
3. **Каркас и состав Этапа 1.** T-8001 добавляет только строку `apps.messenger` и пустые подключения под `apps.is_installed` — это единственное
   исключение из правила «код прежних срезов правит задача Этапа 3». Перенос `core.services.text`/`thumbs` (T-8004), точка `unit_form_parts` (T-8005),
   интеграция `org` (T-8006), правки прежних тестов (T-8007) и команда стенда T-8008 — в Этапе 1, как требует задание на сборку;
   модели, миграции и данные установки остаются
   в Этапе 3 (T-8200, T-8201), потому что до них тесты среза должны падать, а не ломать сборку. Причина: так же сделан каркас срезов 006–007;
   `CONTRACT-008` заранее фиксирует имена миграций и зависимости.
4. **Точные «было / стало».** Единственный источник правок прежних тестов — таблица в T-8007; она составлена по разделу плана «Прежние тесты, которые
   придётся поправить» и чтению утверждений. Правка сверх перечня запрещена: падение не названного теста — остановка и решение Opus. Причина: одна
   точка правды для правок и красного прогона; правило срезов 005–007.
5. **Сброс стенда.** Реализация `stand_reset` и регистрация точки — T-8224, а не Этап 1: до появления таблиц сброс нечего удалять. T-8008 готовит
   команду `e2e_messenger_age` и договор сброса; проверки порядка `stand_reset`, исправленные в T-8007, зеленеют в T-8224 и в T-8160 идут отдельной
   строкой. Причина: план называет сброс последней записью, а `unit_usage` мессенджер не регистрирует; тот же порядок был у ленты (T-7138 → T-7232).
6. **Колокольчик при установленном мессенджере.** `#notify-bell` сохраняет `#notify-count`, `#notify-toast` и контейнер `#notify-bell-panel`, но
   вместо `button[data-bell-toggle]` рисует ссылку `a[data-bell-link][href="/messenger/notifications/"]`; панель остаётся пустой, адрес
   `/notifications/bell/` работает без мессенджера. Причина: минимально ломает прежние тесты (перечень T-8007 фиксирует только форму элемента) и
   сохраняет число и системное уведомление как были.
7. **Возврат после «прочитано».** `notify` оставляет `Location: /notifications/` (302) — `test_notify_pages_2.py` не правится; закладка и старая
   ссылка работают, а сам список открывается по 302. Причина: план допускает прежний адрес с 302, а лишняя правка теста без нужды запрещена.
8. **`chat` в соединении: 0, −1, текст.** Порядок проверок — сессия (`guard_connect`: не «ok» — 4401), затем `chat`: нет параметра, не положительное
   целое (0, −1, `abc`, `01`, число с плавающей точкой) — `accept()` и `close(4400)` до `group_add`; невидимый или несуществующий — 4404. Тесты
   `WebsocketCommunicator` проверяют `connect()` и первый кадр `websocket.close` с кодом. Причина: так делает `FeedConsumer`, а браузер видит код и не
   переподключается; коды закрытия — часть контракта.
9. **Отказ HTMX и обычный запрос.** Отказ у поля (пустой текст, предел, название, файлы, срок, «Чат отключён») — 200 с фрагментом и причиной; обычный
   POST — переход или 404 (невидимый чат). Значения и зацепки — в `CONTRACT-008`; тесты обеих ветвей названы в задачах Этапа 2. Причина: урок
   PLAN-003, введённое не теряется.
10. **Помощники внутри файлов.** Общих помощников сверх `support_messenger.py` и `helpers_messenger.py` нет; локальные помощники — с префиксом `_` в
   своём файле, общие файлы не правятся. Недостающее имя — вопрос Opus. Причина: правило одного автора на общий файл и параллельные писатели Этапа 2.
11. **Партии и общие файлы кода.** Порядок партий — заголовки Этапа 3: модели → чаты → беседа и сообщения → прочтение и живые → файлы → уведомления →
   поиск → журнал и срок → 360 px → деплой и стенд. Общие файлы и их авторы по порядку: `extensions.py` — T-8205, T-8211, T-8214, T-8216, T-8217,
   T-8219, T-8221, T-8224; `apps.py` — T-8205, T-8211; `views/chats.py` — T-8203, T-8204, T-8211; `views/messages.py` — T-8209, T-8219;
   `page.html` — T-8203, T-8207; `_form.html` — T-8203, T-8208, T-8210; `urls.py` — задачи партий 2–10 по одной, правки
   последовательны; `messenger.js` — T-8208, T-8210, T-8213, T-8222; `messenger.css` — T-8208, T-8222;
   `services/files.py`, `views/files.py` — T-8215, T-8216. Задачи, правящие общий файл, идут без `[P]`; параллельны только T-8223 и T-8224.
   Отчёт `docs/reviews/TASKS-008.md` пишут T-8300…T-8307 в разные разделы, поэтому `[P]` у T-8303 допустим (файл общий, разделы разные).
   Причина: один автор за раз и предсказуемый зелёный прогон после партии.
12. **Красный прогон и заранее исправленные тесты.** После T-8007 часть прежних тестов красная намеренно: она ждёт кода Этапа 3. T-8160 перечисляет их
   отдельной строкой с задачей, которая их зеленеет; это не регрессия и не повод ослаблять тесты. Тесты T-8126a/T-8126b к коду Этапа 1 (T-8004,
   T-8005, T-8006) зелёные с первого запуска — это записывается в красном прогоне отдельной строкой. Падение иного прежнего теста — остановка и
   решение Opus. Причина: порядок «тесты прежде кода» без скрытых правок.
13. **Нагрузка.** T-8150 готовит профиль и наполнение; замер — T-8304 только после отдельного решения владельца (NFR-707). До замера NFR-707 закрыт
   наличием профиля и проверкой `test_messenger_deploy.py`; NFR-612 среза 007 остаётся известным дефектом и порогом для 008 не становится. Причина:
   прямое указание спеки и плана.
14. **Проверки после реализации.** T-8300 отдельной строкой проверяет тесты, которые план называет «вероятно, но по тексту не падают»
   (`test_permissions.py`, `test_sd_access.py`, `test_org_permissions.py` — права, `test_feed_home.py`, e2e `test_o_*`, `test_notify_admin.py`, e2e
   `test_d09_settings.py`). `test_k09_notify.py` тоже нажимает колокольчик, хотя план его не называет: при падении — остановка, решение Opus, правка
   по общему правилу. Причина: не расширять перечень правок T-8007 задним числом.
15. **Объём двух задач.** T-8007 (23 правки прежних тестов, каждая с отдельным разрешением) и T-8200 (шесть моделей, две
   миграции, тесты) идут несколькими сеансами одного исполнителя; дробление на буквы не вводится, порядок правок —
   номера 1–23 T-8007. Причина: правки тестов нельзя параллелить (одно разрешение на тест), а миграции и модели
   связаны одной транзакцией схемы.
16. **Что требует разрешения владельца.** (а) каждая правка прежнего теста — по одному тесту, с диффом (T-8007); (б) копия стенда, сброс, пересборка,
   обновление и перезапуск служб (T-8159, T-8301, T-8305); (в) нагрузочный прогон NFR-707 (T-8304); (г) ручной проход и приёмка среза (T-8308,
   T-8309); (д) подписи документов и `git push`. Коммиты агент делает сам (решение владельца 2026-11-14), push — только владелец.

## Покрытие FR/NFR → задачи

Столбец «Этап 2» — задачи тестов, у которых хотя бы один тест помечен требованием; контракт T-8002 и помощники
T-8003, T-8130, T-8159, T-8160 не засчитываются (решение 2). Столбец «Этапы 1, 3, 4» — задачи подготовки, реализации и
проверки с явным номером в перечне в конце строки.

| Требование | Этап 2 (тесты) | Этапы 1, 3, 4 |
|---|---|---|
| FR-643 | T-8102, T-8103, T-8104, T-8125, T-8127, T-8143 | T-8001, T-8200, T-8202, T-8306 |
| FR-644 | T-8104, T-8108, T-8109a, T-8131 | T-8202, T-8203, T-8207 |
| FR-645 | T-8103, T-8104, T-8125, T-8131 | T-8202, T-8203, T-8214, T-8308 |
| FR-646 | T-8102, T-8105, T-8132 | T-8202, T-8204 |
| FR-647 | T-8105, T-8132 | T-8204 |
| FR-648 | T-8105, T-8114, T-8115, T-8121, T-8132 | T-8204, T-8221 |
| FR-649 | T-8102, T-8106, T-8125, T-8126a, T-8126b, T-8127, T-8133 | T-8005, T-8006, T-8205, T-8306 |
| FR-650 | T-8102, T-8103, T-8106, T-8113, T-8114, T-8119, T-8125, T-8126b, T-8133 | T-8205, T-8306 |
| FR-651 | T-8102, T-8103, T-8106, T-8107, T-8113, T-8116b, T-8120, T-8122, T-8123, T-8134 | T-8201, T-8206, T-8224 |
| FR-652 | T-8107, T-8109a, T-8109b, T-8131, T-8135 | T-8209 |
| FR-653 | T-8104, T-8109a, T-8110, T-8126a, T-8135 | T-8004, T-8209 |
| FR-654 | T-8102, T-8109b, T-8135 | T-8209, T-8222 |
| FR-655 | T-8109b, T-8110, T-8111, T-8136 | T-8210 |
| FR-656 | T-8109a, T-8109b, T-8115, T-8116a, T-8135 | T-8209, T-8213 |
| FR-657 | T-8102, T-8109a, T-8109b, T-8115, T-8116a, T-8118, T-8135 | T-8200, T-8209 |
| FR-658 | T-8102, T-8108, T-8131 | T-8207, T-8208 |
| FR-659 | T-8102, T-8112, T-8115, T-8131, T-8138 | T-8211, T-8213 |
| FR-660 | T-8103, T-8104, T-8105, T-8106, T-8108, T-8112, T-8113, T-8114, T-8138 | T-8211, T-8212, T-8213 |
| FR-661 | T-8103, T-8114, T-8115, T-8124, T-8131, T-8135, T-8138 | T-8212, T-8213, T-8305 |
| FR-662 | T-8102, T-8109b, T-8117a, T-8117b, T-8119, T-8123, T-8124, T-8125, T-8126a, T-8137 | T-8004, T-8200, T-8215, T-8216, T-8223, T-8224 |
| FR-663 | T-8103, T-8116a, T-8116b, T-8116c, T-8139 | T-8217 |
| FR-664 | T-8111, T-8116a, T-8116b, T-8116c, T-8136, T-8139 | T-8217 |
| FR-665 | T-8116b, T-8116c, T-8139 | T-8217 |
| FR-666 | T-8109b, T-8112, T-8116a, T-8116b, T-8116c, T-8139 | T-8211, T-8217 |
| FR-667 | T-8125, T-8126b, T-8139 | T-8218 |
| FR-668 | T-8103, T-8118, T-8140, T-8143 | T-8219 |
| FR-669 | T-8103, T-8106, T-8109a, T-8109b, T-8111, T-8114, T-8115, T-8117a, T-8117b, T-8118, T-8143 | T-8202, T-8215, T-8216, T-8219, T-8306 |
| FR-670 | T-8102, T-8109a, T-8117b, T-8119, T-8120, T-8121, T-8122, T-8123, T-8124, T-8141 | T-8200, T-8201, T-8220, T-8224 |
| FR-671 | T-8105, T-8106, T-8107, T-8116c, T-8119, T-8120, T-8121, T-8132, T-8133, T-8134, T-8141 | T-8204, T-8205, T-8206, T-8220, T-8221 |
| FR-672 | T-8106, T-8133 | T-8205 |
| FR-673 | T-8108, T-8124, T-8142 | T-8208, T-8222 |
| NFR-701 | T-8138, T-8150 | T-8212, T-8213, T-8302, T-8304, T-8305 |
| NFR-702 | T-8124, T-8142 | T-8222, T-8301, T-8302 |
| NFR-703 | T-8108, T-8110, T-8118 | T-8004, T-8202, T-8209, T-8219, T-8303, T-8306 |
| NFR-704 | T-8117a, T-8117b, T-8124, T-8137 | T-8215, T-8216, T-8223 |
| NFR-705 | T-8110, T-8116c, T-8139 | T-8217, T-8306 |
| NFR-706 | T-8119, T-8141 | T-8220 |
| NFR-707 | T-8124, T-8150 | T-8304 |
| NFR-708 | T-8116a, T-8121, T-8124, T-8139 | T-8207, T-8217, T-8221, T-8301 |
| NFR-709 | T-8121 | T-8221, T-8306 |

Итог: у каждого FR-643…673 и NFR-701…709 есть задача Этапа 2 и задача Этапов 1, 3, 4; пропусков нет. Только
наличием профиля нагрузки (без своего замера в Этапе 2) закрыт NFR-707 — его проверяет T-8304 после решения
владельца.