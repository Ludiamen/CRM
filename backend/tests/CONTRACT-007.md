# Контракт имён тестов Этапа 2 среза 007 (T-7101…T-7154)

Тесты пишутся до кода и задают имена, которых нет в PLAN-007. Реализация (Этап 3) берёт их отсюда дословно (решение 35
задач). Имена плана (модели и поля раздела «Модель данных», адреса «Контрактов», коды журнала, права `feed.post_all` и
`feed.moderate`, приложение `feed`, задания `remind_events` и `retention_night` и записи cron `feed_reminders`,
`feed_retention`, команды `e2e_feed_shift` и `e2e_feed_retention`, восемь видов `feed.*`, поля
`NotificationKind.channels` и `NotificationKind.coalesce_text`, точка `home_body`, функции `subtree_member_ids`,
`unit_chains`, `comments.update`, `pdn_patterns.EMAIL/PHONE`, `pages.collect_notices`, `ws.SessionGuardMixin`) здесь
повторяются только там, где тест уточняет их форму. Имена срезов 001–006 (`tests/CONTRACT.md`, `CONTRACT-002.md` …
`CONTRACT-006.md`) не меняются; что в этих файлах устаревает со срезом 007, перечислено в разделе 15 (решение 4 задач).

Происхождение каждой строки видно из текста: «план» — PLAN-007; «решение N задач» — раздел «Решения Opus по задачам»
TASKS-007 (решения Opus, принятые владельцем подписью TASKS-007; решения 1–59); «решение 60», «решение 61» — решения при
исполнении по ответам владельца 2026-10-30 (так и названы: «ответ владельца»); «решение 62», «решение 63» — решения Opus при
исполнении по ранним фактам T-7005 и T-7006; «факт» — файл репозитория, названный в строке (по дереву на 2026-10-30);
«`impact.md`» — анализ влияния `crm-work/slice007/tasks/impact.md` (вход для T-7138, не решение); «решение контракта Кn» —
выбор автора контракта (исполнитель T-7100) там, где план и решения оставили выбор; причина каждого такого выбора — в
той же строке и сводно в разделе 16.2. Решения контракта ничьим решением владельца не являются: их проверяет Opus до
запуска T-7101 (решение 2 задач).

Помощники тестов: `tests/support_feed.py` (пишет только T-7101, раздел 5.9) и `tests/e2e/helpers_feed.py` (пишет только
T-7140a, раздел 14.4). В колонке «Тесты» стоят задачи T-71NN, которые берут имя (полные имена тестов — в строках задач
Этапа 2 TASKS-007).

Правила для всех тестов среза:
- время (решения 5 и 59 задач): службы берут время из `django.utils.timezone.now()` один раз на действие и передают его в
  SQL параметром `%s`, а не `now()` базы (выборка задания напоминаний, блок важных и конец срока важного, «было важным»,
  граница срока хранения, показы старше 31 дня, окно 30 дней счётчика); дату по Москве — `apps.core.widgets.moscow_today()`
  (факт); тесты ставят часы фикстурой `clock` (`Clock` из `tests/factories.py`); проверки «по Москве» — часы на полночь UTC
  (сценарий 2 п. 9; 03:00 по Москве), дата по Москве, отличная от даты UTC, — часы 21:00–23:59 UTC (как CONTRACT-006,
  ответ О5);
- задания выполняются синхронно: напоминания — `support_feed.run_reminders(now)`, ночное — `support_feed.run_retention(now)`
  (раздел 5.9; `tasks.remind_events(now=None)` и `tasks.retention_night(now=None)` принимают время параметром — решение 59
  задач), задания RQ (`files`, `notify`) — прежним `support_notify.run_jobs(queue_name)`; приёмка сдвигает время командами
  `e2e_feed_shift --minutes N` и `e2e_feed_retention --age-days N [--posts …]` через обёртки `shift(minutes)` и
  `age(days, posts=None)` (раздел 14);
- всё, что идёт «после фиксации» (рассылка `publish`, стирание файлов с диска, постановка проверки файла), проверяется
  внутри `django_capture_on_commit_callbacks(execute=True)` (решение 6 задач, п. г);
- гонки — без потоков (решение 6 задач): по SQL (`support_feed.capture_sql`, `sql_of`, `assert_for_update`,
  `assert_skip_locked`), последовательно (два «Нравится — создать» подряд, две привязки одного файла, два запуска задания
  напоминаний), подменой «между выборкой и замком» и прочими точками раздела 5.8; `django_db(transaction=True)` не
  используется; пачки ночного задания — оба признака решения 9 задач (шпион `retention.purge_batch` вызван 3 раза на 2 500
  записей и три выборки с `LIMIT 1000` в `capture_sql`);
- WebSocket (решение 7 задач): `asgiref.testing.ApplicationCommunicator` через `support_notify.ws_run`, `WsClient` и
  `_application()`, настоящий слой `channels_redis` на Valkey (база 15); подключение к `/ws/feed/` —
  `support_feed.ws_client(user, query)` (свой `scope` по образцу `WsHub.connect`, раздел 5.9); проверка сессии ускоряется
  подменой `apps.feed.consumers.CHECK_INTERVAL`; недоступный слой `publish` — `support_feed.layer_down()`;
  `InMemoryChannelLayer` и подмены `CHANNEL_LAYERS` не используются;
- ClamAV (решение 21 задач): подмена строкой `apps.integrations.clamav.services.scan` помощниками `support_org.scan_clean`,
  `scan_found`, `scan_unavailable`; `support_feed.attach(...)` берёт их же; настоящий ClamAV (EICAR) — только в приёмке;
- код среза тесты импортируют внутри функций теста (или через `support.model("feed.Post")`), а не на уровне модуля: сбор
  `pytest --collect-only` проходит до появления кода; `support_feed.py` на уровне модуля `apps.feed` не импортирует;
- тексты отказов в тестах — литералы раздела 13, а не импорт `feed/texts.py` (решение 19 задач); словарь
  `apps.feed.texts.TEXTS` сверяет с разделами 13.1–13.2 один тест (имя теста — по ответу Opus на В1: T-7135, `test_feed_texts_dictionary_contains_every_key_and_text_of_contract_13_1_and_13_2`);
- ответы (решение 18 задач; план «Контракты»): запись не видна, не существует или удалена, комментарий или файл
  невидимой записи, чужой непривязанный файл — 404 обычной страницы «Не найдено» без подробностей (тот же ответ и текст,
  что у несуществующего; сравнение в пределах одного клиента — `support.same_failure`, как CONTRACT-006 К-10); запись видна,
  действие не разрешено — 403; отказ с сообщением — 200 с формой и введённым (запрос HTMX — фрагмент и причина у поля);
  не вошедшему — 302 на `/login/?next=<путь>`, без второго фактора — прежние промежуточные слои ядра (подключение фактора);
- секреты и ПДн в тестовых данных (решение 23 задач): почта и телефоны — `support_feed.email_of`, `phone_of`; имена
  переменных — без `secret`, `token`, `key`, `password`; строка EICAR собирается из частей; в файлах и ответах — только `***`;
- разметка блоков среза (решение 36 задач): без `role="status"`, `role="alert"`, `data-error`, `data-warning`, кроме
  сообщений об отказах формы (раздел 10.1); узел живого числа «Ленты» — без `data-menu-badge`; форма фильтров ленты —
  своя, вне `form#staff-filter` и `#notify-bell`; атрибутов `data-search-bar`, `data-search-popup` у блоков ленты нет
  (`impact.md`, У5);
- тесты ходят по путям плана (раздел «Контракты»), а не по именам маршрутов; маршруты среза не содержат `regist`, `signup`
  (решение 44 задач);
- SQL — только параметры (NFR-608): литерал с `%s` и списком параметров; цепочка узлов, номера страницы, исключаемые
  номера — массивом `= ANY(%s)` / `<> ALL(%s)`; тесты «значение — параметр» ищут пробное значение в `params` захваченного
  запроса и не находят его в тексте SQL до подстановки (`support_feed.queries_with_params` отдаёт пары «SQL, параметры» (`capture_sql` — строки SQL, как в `support_kb`),
  раздел 5.9).

Разделы:
1. Среда запуска и числа среза.
2. Модели и поля, данные установки.
3. Ядро и записи точек `feed`.
4. Прежние модули: `org`, `notify`, `knowledge`; перечень публичных функций, которые зовёт `feed`.
5. Службы `feed`, исключения, точки подмены и помощники `support_feed.py`.
6. Места одной функции видимости.
7. Виды уведомлений и таблица «код вида → модуль».
8. Журнал.
9. Поиск.
10. Маршруты, поля форм, ответы.
11. Слой каналов: сообщения, кадры, коды закрытия.
12. Зацепки `data-*` для приёмки.
13. Тексты, которые проверяют тесты.
14. Команды стенда, нагрузка, помощники приёмки.
15. Что меняется в прежних контрактах (для T-7138).
16. Вопросы и решения.

## 1. Среда запуска и числа среза

### 1.1. Приложение, каркас, статика

| Что | Требование | Тесты |
|---|---|---|
| `INSTALLED_APPS` | `"apps.feed"` — последним, после `"apps.search"` (план; факт после T-7001): хвост списка — `"apps.servicedesk"`, `"apps.notify"`, `"apps.knowledge"`, `"apps.lists"`, `"apps.search"`, `"apps.feed"` (`support_feed.APPS_TAIL`, `impact.md` «Общее»); метка `feed`, класс `FeedConfig` (факт T-7001), `verbose_name = "Лента"` (решение контракта К1) | T-7135 test_feed_is_last_in_installed_apps_after_search |
| `FeedConfig.ready()` | зовёт `apps.feed.extensions.register_all()` (регистрации точек, раздел 3.3); подписок шины нет, `dispatch.subscribe_all()` не зовёт (план) | T-7136 test_feed_has_no_bus_subscriptions_and_publishes_only_object_viewed |
| Каркас (факт T-7001) | `apps/feed/`: `apps.py`, `models.py`, `texts.py`, `notify_kinds.py`, `audit_labels.py`, `extensions.py`, `stand.py`, `tasks.py`, `consumers.py`, `routing.py`, `urls.py`; `views/` (`home`, `posts`, `comments`, `likes`, `important`, `events`, `files`, `pickers`, `settings`); `services/` (`visibility`, `posts`, `recipients`, `mentions`, `text`, `pdn`, `important`, `events`, `reminders`, `comments`, `likes`, `unread`, `live`, `files`, `thumbs`, `search`, `retention`, `notify_rules`, `feed_settings`, `page`); плюс `services/errors.py` (решение контракта К2, раздел 5.1); `management/commands/e2e_feed_shift.py`, `e2e_feed_retention.py`; миграции `0001_initial.py`, `0002_initial_data.py`; шаблоны — `templates/feed/` (`body.html`, `_post.html`, `_post_head.html`, `_post_body.html`, `_post_to.html`, `_important.html`, `_event.html`, `_likes.html`, `_comments.html`, `_comment.html`, `_files.html`, `_form.html`, `_new_banner.html`, `_badge.html`, `card.html`, `_lists.html`, `settings.html` — план); общий фрагмент ядра `templates/_home_notices.html`; иконка — `templates/icons/feed.html` | T-7136 (обход `ast`) |
| Статика (решение 34 задач) | `static/feed/feed.js` — `<script defer src=…>`, `static/feed/feed.css` — `<link rel="stylesheet">` в шаблонах страниц ленты (тело главной, карточка, настройка срока); в `_assets.html` файлы среза не подключаются; в `.js` нет `eval(` и `new Function`; во фрагментах WebSocket скриптов нет | T-7135 test_feed_scripts_are_external_files_in_static_feed |
| Шаблоны | в `templates/feed/` и `_home_notices.html` нет `style=` и `on…=` (регулярные выражения, как в `test_shell.py`) | T-7135 test_feed_templates_have_no_style_attribute, test_feed_templates_have_no_inline_event_handlers; T-7123 test_frame_fragments_have_no_style_or_on_event_attributes |
| CSP | `/`, `/feed/<id>/`, `/settings/feed/` отдают `Content-Security-Policy` с `script-src 'self'` без `'unsafe-inline'` и `'unsafe-eval'`; `connect-src 'self'` (план «CSP») | T-7135 test_home_and_feed_pages_send_csp_without_unsafe_inline_in_script_src |
| Язык и время | тексты страниц среза по-русски (страницы — `support_feed.feed_pages(post)`, раздел 5.9); время — по Москве (`localtime` шаблонов): тест ставит `Clock` на полночь UTC и находит 03:00 по Москве во времени публикации, «изменено <время>» и в блоке события; формат показа — `time[data-at]` с `datetime` ISO и текстом «ДД.ММ.ГГГГ ЧЧ:ММ» (решение контракта К3: как в CONTRACT-006, 11.1) | T-7135 test_feed_pages_texts_are_russian, test_feed_times_are_shown_in_moscow_at_utc_midnight_for_post_event_and_edited_mark |
| Файл теста развёртывания | `tests/test_feed_deploy.py` (план, по образцу `test_lists_deploy.py`) | T-7135 |

### 1.2. Задания, nginx, слой каналов, том файлов

| Что | Требование | Тесты |
|---|---|---|
| Записи cron (план) | девятнадцатая и двадцатая записи в `config/cron.py`, под `apps.is_installed("apps.feed")` (импорт `from apps.feed.tasks import remind_events, retention_night` внутри той же проверки): `register(remind_events, queue_name="notify", cron="* * * * *", name="feed_reminders", job_timeout=120)` и `register(retention_night, queue_name="maintenance", cron="35 23 * * *", name="feed_retention", job_timeout=600)`; других записей на `35 23 * * *` нет; прежние восемнадцать записей — те же имена и минуты (у `notify_tick` — интервал 30 с) | T-7135 test_feed_reminders_cron_entry_runs_remind_events_every_minute_in_notify_with_timeout_120, test_feed_retention_cron_entry_runs_retention_night_at_23_35_in_maintenance_with_timeout_600, test_feed_cron_entries_are_under_is_installed_guard, test_cron_has_no_other_entry_at_23_35, test_cron_module_has_twenty_register_calls, test_previous_eighteen_cron_entries_keep_names_and_minutes |
| `FEED_JOBS` (`impact.md` «Общее») | `{"feed_reminders": ("remind_events", "notify", None, "* * * * *", 120), "feed_retention": ("retention_night", "maintenance", None, "35 23 * * *", 600)}` — формат `LISTS_JOBS` из `test_sd_deploy.py` (функция, очередь, интервал, cron, тайм-аут; имя ≠ функция) | T-7138 |
| Адреса | `config/urls.py`: `include("apps.feed.urls")` под `apps.is_installed("apps.feed")` (факт T-7001, решение 3 задач) | T-7135 test_feed_urls_are_included_under_is_installed_guard |
| `location` nginx (план) | в `deploy/nginx.conf` и `deploy/nginx.prod.conf`: ровно один `location ~ ^/feed/files/$ { … }` с `client_max_body_size 25m;`; набор имён директив `proxy_*` совпадает с блоком `tickets` того же файла (как блоки `kb` и `lists`); прежние четыре `location` с `55m` и общий предел `6m` не меняются; `location /ws/` не меняется | T-7135 test_nginx_dev_config_has_feed_files_location_with_25m_limit, test_nginx_prod_config_has_feed_files_location_with_25m_limit, test_feed_files_location_repeats_proxy_directives_in_both_configs, test_nginx_previous_four_55m_locations_and_common_6m_limit_unchanged, test_nginx_ws_location_unchanged_in_both_configs |
| `CHANNEL_LAYERS` (план «Запуск») | два ключа: `"default"` прежний (`socket_timeout` 30, `max_connections` 300, `socket_connect_timeout` 2, `prefix` `"crm-asgi"`; факт) и `"publish"` — `{"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [{"address": VALKEY_URL, "socket_timeout": 2, "max_connections": 300, "socket_connect_timeout": 2}], "prefix": "crm-asgi"}}` (форма словаря — `impact.md`, п. 18) | T-7135 test_channel_layers_publish_key_has_same_address_and_prefix_with_2s_timeouts; T-7126a test_publish_layer_has_same_host_and_prefix_2_second_timeouts_and_300_connections, test_default_layer_unchanged_and_channel_layers_have_two_keys |
| `config/asgi.py` (план) | `websocket_urlpatterns = list(notify_routing.websocket_urlpatterns)`; при `apps.is_installed("apps.feed")` — `+= feed_routing.websocket_urlpatterns` (импорт `from apps.feed import routing as feed_routing` внутри проверки); маршрутизатор — `AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(websocket_urlpatterns)))`; тест сверяет включение списка `feed.routing.websocket_urlpatterns`, а не его содержимое (решение 52 задач) | T-7126a test_asgi_websocket_patterns_include_notify_routes_and_feed_routing_list_when_feed_installed, test_asgi_without_feed_has_no_ws_feed_route_and_ws_notify_as_before |
| `apps/feed/routing.py` | `websocket_urlpatterns = [re_path(r"^ws/feed/$", consumers.FeedConsumer.as_asgi())]` (решение контракта К4: как `notify/routing.py`) | T-7124 |
| Том файлов, копия | файлы и эскизы лежат в томе `protected`: оригинал — `incoming/`, `attachments/`, `quarantine/` через `core.services.uploads.store(…, "feed")`; эскиз — `PROTECTED_ROOT/attachments/thumbs/<id StoredFile>.jpg` или `.webp` (план; имя по номеру `StoredFile` — решение контракта К5); `deploy/backup.sh` не меняется | T-7135 test_feed_files_and_thumbs_live_in_protected_volume_and_backup_script_unchanged; T-7130 test_original_and_thumb_paths_under_protected_root_thumb_field_set |
| Зависимости | новых пакетов нет; в `requirements.txt` нет строки «Срез 007» (план) | T-7135 test_no_new_packages_and_no_slice_007_line_in_requirements |
| Индекс `Shown(post_id)` (решение 60, ответ владельца 2026-10-30) | у `Shown.post` — обычный индекс внешнего ключа (вопреки строке плана «индекса нет»); тест проверяет по `pg_indexes`, что у таблицы `feed_shown` есть индекс, первый столбец которого — `post_id` | T-7135 test_shown_post_has_index_so_commit_fk_check_skips_full_scan |

### 1.3. Сброс стенда: точка `stand_reset` модуля `feed`

Функция — `apps.feed.stand.stand_reset()` без аргументов, регистрируется в `apps/feed/extensions.py` последней из
регистраций `register_all()` (решение контракта К6, как у `knowledge` и `lists`). `apps.feed` последний в `INSTALLED_APPS`,
команда `e2e_reset_stand` зовёт функции в обратном порядке, поэтому функция `feed` идёт первой (план). Работает через
соединение `migrate`, если оно настроено, иначе `default` (как `lists`).

| Что | Требование | Тесты |
|---|---|---|
| Транзакция | всё стирание и `seed(stand=True)` — в одной `transaction.atomic(using=<алиас>)` | T-7134 test_feed_stand_reset_runs_in_transaction_under_migrate_alias |
| Таблицы | стираются все таблицы `feed`: `FeedFile`, `CommentLike`, `FeedComment`, `PostLike`, `ReadMark`, `EventAnswer`, `Shown`, `Recipient`, `Post`, `FeedSettings` (порядок — решение контракта К7: сначала зависимые, `FeedSettings` затем создаётся заново); и строки `core.Comment` с `object_ref__startswith="feed.post:"` (решение 53 задач) | T-7134 test_feed_stand_reset_wipes_all_feed_tables, test_feed_stand_reset_deletes_core_comments_with_feed_post_object_ref |
| Файлы | пути оригиналов и эскизов по строкам `FeedFile`/`StoredFile` (все состояния) собираются до удаления; затем удаляются строки `FeedFile` и их `StoredFile`; диск — `transaction.on_commit(lambda: core_files.remove_paths(paths), using=<алиас>)` на том же алиасе (как `lists`, CONTRACT-006 К-9); каталог `PROTECTED_ROOT/attachments/thumbs/` стирается целиком (план) | T-7134 test_feed_stand_reset_wipes_feed_file_rows_stored_files_and_disk_after_commit, test_feed_stand_reset_wipes_whole_thumbs_directory |
| Восстановление | `seed(django.apps.apps, SimpleNamespace(connection=connections[<алиас>]), stand=True)` миграции `0002`: «Писать всем» — всем ролям, «Модерировать ленту» — «Администратору портала», `FeedSettings(pk=1, retention_years=3)`; на время вызова отключается обработчик `m2m_changed` ядра с `dispatch_uid="core-perms-role-permissions"` и возвращается в `finally` (план; как `lists/stand.py`) | T-7134 test_feed_stand_reset_restores_feed_settings_to_three_years, test_feed_stand_reset_returns_post_all_to_all_roles_and_moderate_to_admin_after_removal, test_feed_stand_reset_disconnects_core_role_permissions_m2m_handler_during_seed, test_feed_stand_reset_reconnects_m2m_handler_in_finally_when_seed_raises |
| Порядок | в `extensions.registered("stand_reset")` функция `apps.feed.stand.stand_reset` — последняя, сразу после `apps.lists.stand.stand_reset` | T-7134 test_feed_stand_reset_is_registered_last_and_runs_first |
| Проверка стенда | `apps.feed.stand.require_stand()` и `apps.feed.stand.REFUSAL` — своя копия (план): `REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."` (текст — как у `lists`, факт); без `os.environ.get("E2E_STAND") == "1"` — `CommandError(REFUSAL)` раньше любого чтения базы | T-7134 test_feed_require_stand_refuses_without_e2e_stand_flag |

Тесты сброса помечаются `pytest.mark.django_db(databases=["default", "migrate"])`, данные создают и читают через
`using("migrate")`, функцию `stand_reset()` вызывают напрямую (как CONTRACT-006, 1.3).

### 1.4. Числа среза (план, «Контракты» → «Числа среза для контракта тестов»)

| Число | Значение | Кто сверяет |
|---|---|---|
| Точек расширения | восемнадцать; `home_body` — последней (`support_feed.POINTS_007 = ("home_body",)`) | T-7136 test_points_tuple_has_eighteen_names_and_feed_uses_home_body_last; T-7137; T-7138 |
| Вызовов `register` в `config/cron.py` | двадцать | T-7135; T-7138 |
| Прав в портале | восемнадцать (`feed.post_all` «Писать всем», `feed.moderate` «Модерировать ленту» — последними; `support_feed.PERMISSIONS_007`, `TITLES_007`) | T-7133 test_portal_has_eighteen_permissions_after_seed; T-7138 |
| Видов уведомлений | двадцать (восемь `feed.*`, раздел 7) | T-7128; T-7138 |
| Полей `NotificationKind` | пятнадцать; `channels`, `coalesce_text` — последними (`support_feed.KIND_FIELDS_007`, раздел 2.1) | T-7126b; T-7138 |
| `order` группы поиска «Лента» | 60 (после «Списков», 50) | T-7131; T-7138 |
| Меню | пункт «Лента» — первый, «Главной» нет; у администратора четырнадцать пунктов (+ «Лента» `order` 0, + «Настройки ленты» `order` 63) | T-7104; T-7116; T-7138 |
| `location` с `client_max_body_size 25m` | один (`^/feed/files/$`); с `55m` — прежние четыре | T-7135; T-7138 |
| `apps.feed` | последний в `INSTALLED_APPS` | T-7135; T-7138 |
| Ключей `CHANNEL_LAYERS` | два (`default`, `publish`) | T-7126a; T-7135; T-7138 |

## 2. Модели и поля, данные установки

Модели берутся через `support.model("feed.Post")` и так далее. Типы, длины и связи — план («Модель данных»); здесь — то,
что план оставил выбору: классы вариантов, имена ограничений (решение контракта К8: образец CONTRACT-005/006 —
`<приложение>_<модель>_<поля>_<вид>`; тест ловит `IntegrityError`, имя по тексту ошибки не сверяет), значения по
умолчанию и одно отступление от таблицы моделей плана (решение 60). Имена индексов (не длиннее 30 знаков) выбирает
исполнитель (план). Обратные имена связей тесты не используют: выборки — через менеджеры моделей
(`FeedComment.objects.filter(post=post)`; решение контракта К9).

### 2.1. Ядро

| Что | Требование | Тесты |
|---|---|---|
| `StoredFile.Purpose.FEED` | значение `"feed"`, подпись `"вложение ленты"` (план), последним; миграция ядра `0010_storedfile_feed_purpose.py` — только `AlterField` вариантов; прежние значения и `max_length` (16) не меняются | T-7137 test_stored_file_purpose_feed_is_last_and_previous_values_unchanged |
| `NotificationKind.channels` | `channels: tuple[str, ...] \| None = None` — четырнадцатое поле, после `external_text_of` (план) | T-7126b test_notification_kind_channels_and_coalesce_text_are_last_and_default_to_none |
| `NotificationKind.coalesce_text` | `coalesce_text: Callable[[int, str, datetime], str] \| None = None` — пятнадцатое, последнее поле (план); `support_feed.KIND_FIELDS_007 = ("channels", "coalesce_text")` (`impact.md`) | T-7126b test_notification_kind_has_fifteen_fields_first_thirteen_in_old_order |
| `core.Comment` | без изменений: поля `object_ref`, `author`, `text`, `created_at` (факт) | T-7119 test_core_comment_get_fields_unchanged |

### 2.2. Приложение `feed`

| Модель.поле | Требование | Тесты |
|---|---|---|
| `Post.Kind` | `TextChoices`: `POST = "post", "Сообщение"`; `IMPORTANT = "important", "Важное"`; `EVENT = "event", "Событие"` (значения — план; подписи — названия видов формы плана) | T-7107 |
| `Post` | `author` — `ForeignKey("core.User", PROTECT, related_name="+")`; `kind` — `CharField(16, choices=Post.Kind.choices)`; `text` — `TextField(blank=True, default="")` (10 000 знаков проверяет служба); `to_all` — `BooleanField(default=False)`; `published_at` — `DateTimeField` (ставит служба значением `now` действия); `edited_at`, `important_until`, `event_start`, `event_end`, `remind_at`, `reminded_for_start` — `DateTimeField(null=True, blank=True)`; `event_title`, `event_place` — `CharField(200, null=True, blank=True)`; `search` — `SearchVectorField(null=True)` (решение контракта К10: типы и умолчания, которые план не назвал) | T-7107 test_publish_creates_post_to_rows_mention_rows_file_binding_and_vector |
| `Post`, ограничения (план) | `CheckConstraint(name="feed_post_important_iff_until")`: `kind="important"` ⇔ `important_until` не пусто; `CheckConstraint(name="feed_post_event_fields")`: `kind="event"` ⇔ `event_title`, `event_place`, `event_start`, `event_end` не пусты, `event_title <> ''`, `event_place <> ''` и `event_end > event_start` | T-7112 test_db_check_ties_kind_important_to_non_empty_important_until; T-7113 test_db_check_ties_kind_event_to_filled_event_fields_and_end_after_start |
| `Recipient.Kind`, `Recipient.Via` | `UNIT = "unit", "Подразделение"`, `USER = "user", "Сотрудник"`; `TO = "to", "Кому"`, `MENTION = "mention", "Упоминание"` (значения — план; подписи — решение контракта К10) | T-7102a |
| `Recipient` | `post` — CASCADE; `kind` — `CharField(8)`; `unit_id` — `PositiveIntegerField(null=True, blank=True)` без внешнего ключа (план); `user` — `ForeignKey("core.User", PROTECT, null=True, blank=True, related_name="+")`; `via` — `CharField(8)`; `published_at` — копия `Post.published_at` (план) | T-7107 test_recipient_published_at_copies_post_published_at; T-7136 test_feed_models_have_no_foreign_keys_to_org_or_notify_and_recipient_unit_id_is_plain_integer |
| `Recipient`, ограничения (план) | `CheckConstraint(name="feed_recipient_one_target")` («ровно одно из `unit_id`, `user`, и `kind` ему соответствует»); `UniqueConstraint(fields=["post", "unit_id"], condition=Q(unit_id__isnull=False), name="feed_recipient_post_unit_uniq")`; `UniqueConstraint(fields=["post", "user", "via"], condition=Q(user__isnull=False), name="feed_recipient_post_user_via_uniq")` | T-7110 test_mentioned_already_in_to_gets_separate_mention_row |
| `FeedComment` | `comment` — `OneToOneField("core.Comment", CASCADE, primary_key=True, related_name="+")`; `post` — CASCADE; `edited_at` — `DateTimeField(null=True, blank=True)`; `search` — `SearchVectorField(null=True)` (план) | T-7119 test_viewer_adds_comment_core_comment_and_feed_comment_with_lowercase_object_ref |
| `PostLike`, `CommentLike`, `ReadMark`, `EventAnswer` | `created_at` / `read_at` / `answered_at` — `DateTimeField` (ставит служба); `CommentLike.comment` — `ForeignKey("core.Comment", CASCADE, related_name="+")`, `CommentLike.post` — CASCADE; `EventAnswer.Answer`: `GO = "go", "Пойду"`, `NO = "no", "Не смогу"` (подписи — решение контракта К10); уникальности `feed_postlike_post_user_uniq`, `feed_commentlike_comment_user_uniq`, `feed_readmark_post_user_uniq`, `feed_eventanswer_post_user_uniq` (план; имена — К8) | T-7120 test_one_mark_per_user_unique_constraint_on_post_and_comment_likes; T-7112; T-7113 |
| `Shown` | `user` — CASCADE; `post` — CASCADE; `shown_at` — `DateTimeField`; суррогатный ключ; `UniqueConstraint(fields=["user", "post"], name="feed_shown_user_post_uniq")`; у `post` — обычный индекс внешнего ключа (решение 60, ответ владельца 2026-10-30; отступление от строки плана «индекса (`post_id`) нет») | T-7121; T-7135 test_shown_post_has_index_so_commit_fk_check_skips_full_scan |
| `FeedFile` | `post` — `ForeignKey(Post, CASCADE, null=True, blank=True)`; `comment` — `ForeignKey("core.Comment", CASCADE, null=True, blank=True, related_name="+")`; `file` — `OneToOneField("core.StoredFile", PROTECT, related_name="+")`; `name` — `CharField(255)`; `thumb` — `CharField(255, blank=True, default="")` (путь относительно `PROTECTED_ROOT`, пусто — эскиза нет); `uploaded_by` — PROTECT, `related_name="+"`; `uploaded_at` — `DateTimeField` (план; умолчания — К10) | T-7129 test_upload_stores_feed_purpose_pending_and_unbound_row_of_uploader |
| `FeedFile`, ограничение (план) | `CheckConstraint(condition=Q(comment__isnull=True) \| Q(post__isnull=False), name="feed_feedfile_comment_needs_post")` | T-7129 test_db_check_comment_set_implies_post_set |
| `FeedSettings` | одна строка `pk=1`; `retention_years` — `PositiveSmallIntegerField(default=3)`; `updated_at` — `DateTimeField(null=True, blank=True)`; `updated_by` — `ForeignKey("core.User", PROTECT, null=True, blank=True, related_name="+")`; `CheckConstraint(condition=Q(retention_years__gte=1, retention_years__lte=10), name="feed_feedsettings_years_1_10")` (план) | T-7116 test_db_check_rejects_retention_years_outside_1_to_10 |
| Внешние ключи | у моделей `feed` нет внешних ключей на модели `org` и `notify` (план) | T-7136 |
| `object_ref` | комментарий записи — `core.Comment.object_ref == "feed.post:<id записи>"` строчными (план); «Нравится» к комментарию — `"feed.post:<id>:c<id комментария>"` (план, только для уведомлений, раздел 7.2) | T-7119; T-7127 |

### 2.3. Миграция данных `feed 0002` (план, «Права и данные установки»)

Функция `seed(apps, schema_editor, *, stand=False)` модуля `apps.feed.migrations.0002_initial_data` (модуль берётся через
`importlib`, решение 25 задач); `schema_editor` читается только как `.connection.alias`. Обратная функция миграции —
`migrations.RunPython.noop` (решение контракта К11: план обратного хода не задаёт; права ролей после отката остаются
так же, как у `knowledge`).

| Что | Требование | Тесты |
|---|---|---|
| Права | `Permission.objects.get_or_create(code="feed.post_all", defaults={"title": "Писать всем"})` и `(code="feed.moderate", defaults={"title": "Модерировать ленту"})` | T-7133 test_seed_on_slice_006_base_creates_post_all_and_moderate_permissions_with_russian_names, test_portal_has_eighteen_permissions_after_seed |
| Выдача | при `created` (или `stand=True`): «Писать всем» — всем ролям `Role.objects.all()` (встроенным и созданным администратором до установки); «Модерировать ленту» — роли с названием «Администратор портала» (`filter().first()`, нет — пропуск без ошибки); прежние права ролей остаются | T-7133 test_seed_grants_post_all_to_every_role_existing_at_install_including_admin_created_role, test_seed_grants_moderate_to_portal_admin_role_only, test_seed_adds_feed_rights_and_keeps_prior_permissions_of_roles, test_seed_without_portal_admin_role_passes_without_error |
| Однократность | повторный вызов без `stand` при уже созданных правах снятое право не возвращает; роль, созданная после, права не имеет | T-7133 test_second_seed_call_does_not_return_removed_post_all_or_moderate, test_role_created_after_seed_has_no_post_all_until_checked |
| Настройка | `FeedSettings.objects.get_or_create(pk=1, defaults={"retention_years": 3})` — существующая строка не меняется (при `stand=True` сброс заранее стёр таблицу, раздел 1.3) | T-7133 test_seed_creates_feed_settings_row_with_three_years_when_missing, test_seed_keeps_existing_feed_settings_row_unchanged |
| `feed_settings.get()` | возвращает строку `pk=1`, создаёт её с 3, если её нет (план) | T-7116 test_feed_settings_get_creates_row_with_3_when_missing |

## 3. Ядро и записи точек `feed`

### 3.1. Изменения ядра (план, «Изменения кода прежних срезов»)

| Что | Требование | Тесты |
|---|---|---|
| `POINTS` | `"home_body"` — восемнадцатой, в конце кортежа; прежние семнадцать — в прежнем порядке (план) | T-7137 test_points_end_with_home_body_as_eighteenth_point, test_previous_seventeen_points_keep_their_order |
| Точка `home_body` | регистрируемая функция — `(request) -> HttpResponse`; `core.views.pages.home` отдаёт ответ первой зарегистрированной, прочие пропускает; точка пуста — прежний `home.html` с напоминаниями модулей (план) | T-7137 test_home_body_uses_first_registered_function_and_skips_others, test_home_with_empty_home_body_point_renders_previous_home_template |
| `pages.collect_notices(user) -> list` | тот же список, что строил прежний цикл `home` по `extensions.registered("home_notices")` (факт `core/views/pages.py:23-27`); `home` и `feed.views.home.body` зовут её (план) | T-7137 test_collect_notices_returns_same_as_previous_home_loop |
| `templates/_home_notices.html` | общий фрагмент блока напоминаний с прежней разметкой `data-home-notices` / `data-notice` / `data-year`; включён один раз в `home.html` и в `feed/body.html` (план; `impact.md`, У6) | T-7137 test_home_notices_fragment_keeps_previous_data_home_notices_notice_and_year_markup; T-7104 |
| `context.shell` | если среди пунктов `menu_for` есть пункт с `url="/"`, «Главная» не добавляется, а этот пункт ставится первым; иначе — прежняя «Главная» первой (план) | T-7137 test_shell_omits_home_item_when_menu_has_root_url_item_and_puts_that_item_first, test_shell_without_root_url_item_puts_home_item_first |
| `permissions.menu_for` | элемент — прежние ключи `url`, `title`, `icon`, `order`, `badge` (если объявлен, значение — вызов `badge(user)`), плюс `live_badge` (строка как есть), только если пункт его объявил (план; факт: сейчас ключ не передаётся, функция копирует только пять ключей) | T-7137 test_menu_for_passes_live_badge_only_to_item_declaring_it, test_menu_for_keys_of_other_items_unchanged |
| `templates/base.html` | у пункта с `live_badge` узел всегда: `<span id="menu-badge-<live_badge>" class="badge …" data-menu-live-badge data-count="<N>">`, класс `d-none` при `N == 0`; текст — цифры при `N ≤ 99` (при 0 — «0»), «99+» при `N > 99`; `data-count` — число как есть (0…100, потолок `unread.count`); `data-menu-badge` у этого узла нет; у прочих пунктов — прежний `data-menu-badge` только при числе больше 0, цифрами; `htmx-config` не меняется (`allowScriptTags` по умолчанию) (план; текст при 0 — решение контракта К12) | T-7137 test_base_renders_live_badge_node_always_hidden_at_zero_with_data_count_and_live_marker, test_base_live_badge_shows_99_plus_above_99, test_base_other_items_have_data_menu_badge_only_above_zero_in_digits, test_base_htmx_config_unchanged_with_default_allow_script_tags; T-7104 |
| `core.services.comments.update(comment, text) -> Comment` | те же проверки, что `add`: края обрезаются, 1–4000 знаков, иначе `CommentError("empty")` / `CommentError("too_long")` (коды — факт `add`); сохраняет `text`; в модуле нет слов `knowledge`, `article` (план) | T-7137 test_comments_update_strips_edges_accepts_1_and_4000_chars_and_saves_text, test_comments_update_rejects_empty_and_4001_chars_with_same_error_codes_as_add, test_comments_add_list_for_delete_and_delete_for_behave_as_before, test_comments_module_has_no_knowledge_or_article_words |
| `core.services.pdn_patterns` | `EMAIL`, `PHONE` — те же скомпилированные выражения, что были в `knowledge/services/pdn.py:11-12` (факт); `knowledge/services/pdn.py` импортирует их (`from apps.core.services.pdn_patterns import EMAIL, PHONE`), `find` и `mask_plain` базы знаний прежние | T-7137 test_pdn_patterns_email_and_phone_keep_previous_expressions_and_knowledge_imports_them, test_knowledge_find_and_mask_plain_give_same_results_on_string_set |

### 3.2. Проверка сессии соединений: `apps/core/ws.py` (план; имена методов — решение контракта К13)

| Имя | Требование | Тесты |
|---|---|---|
| `SessionGuardMixin` | примесь для `AsyncWebsocketConsumer`; зовёт `sessions.ws_state(session, user)` атрибутом модуля `apps.core.services.sessions` (импорт модуля, не функции) через `database_sync_to_async` | T-7126a |
| `CLOSE_SESSION = 4401`, `CLOSE_TRY_LATER = 1013` | коды закрытия модуля `apps.core.ws` | T-7126a, T-7124 |
| `async guard_connect(self) -> bool` | `ws_state` при подключении; не `"ok"` — `await self.accept()`, затем `await self.close(code=4401)`, возвращает `False`; `"ok"` — `True` (потребитель сам принимает соединение и зовёт `start_guard()`) | T-7126a test_session_guard_with_bad_ws_state_on_connect_accepts_and_closes_4401 |
| `start_guard(self)` / `stop_guard(self)` | запускает задачу цикла проверки (`asyncio` задача на `guard_loop`) / отменяет её (в `disconnect`) | T-7126a |
| `async guard_loop(self)` | бесконечно: `await asyncio.sleep(self.check_interval())`, `await self.on_check()`, `ws_state`; не `"ok"` — закрыть 4401 и выйти; любое исключение в цикле — предупреждение в журнал приложения и закрытие 1013 (исправление дефекта среза 004, план) | T-7126a test_session_guard_loop_waits_check_interval_then_calls_on_check_and_ws_state, test_notify_consumer_check_loop_error_closes_with_1013; T-7124 test_ws_state_error_in_check_loop_closes_with_1013 |
| `check_interval(self) -> float` | читается при каждом ожидании; у `NotifyConsumer` возвращает модульное `apps.notify.consumers.CHECK_INTERVAL` (25), у `FeedConsumer` — `apps.feed.consumers.CHECK_INTERVAL` (25) (план) | T-7126a test_notify_consumer_check_interval_patch_still_applies; T-7124 test_check_interval_change_applies_on_next_wait, test_feed_check_interval_default_is_25_seconds_not_over_30 |
| `async on_check(self)` | по умолчанию ничего; у `NotifyConsumer` — отметка присутствия `live.mark_online` (план; порядок «сон → `on_check` → `ws_state`» прежний, `impact.md` У19); `FeedConsumer` присутствие не отмечает и `mark_offline` не зовёт (`impact.md` У13) | T-7126a test_notify_consumer_on_check_marks_presence_online |

### 3.3. Записи точек `feed` (`apps/feed/extensions.py`, план «Точки расширения ядра и шина событий»)

Функция `register_all()` регистрирует в порядке строк таблицы плана, `stand_reset` последней (решение контракта К6):
`menu_items`, `home_body`, `search_providers`, `notification_kinds`, `file_purposes`, `audit_labels`, `stand_reset`.
Каждая регистрируемая функция определена в модуле `apps.feed.*` (по `__module__` её снимает `without_feed()`).

| Точка | Регистрируемая функция и запись | Тесты |
|---|---|---|
| `menu_items` | `apps.feed.extensions.menu_items() -> list[dict]`: `{"permissions": (), "url": "/", "title": "Лента", "icon": "icons/feed.html", "order": 0, "visible": <истина для любого вошедшего>, "badge": <функция `unread.count(user)`>, "live_badge": "feed"}` и `{"permissions": ("settings.portal",), "url": "/settings/feed/", "title": "Настройки ленты", "icon": "icons/gear.html", "order": 63}` (план; `support_feed.MENU_FEED`, `MENU_FEED_SETTINGS` — `impact.md`) | T-7104 test_feed_menu_entry_order_0_empty_permissions_badge_unread_count_live_badge_feed; T-7116 test_menu_item_feed_settings_has_url_order_63_and_gear_icon_for_settings_portal; T-7136 test_feed_registers_menu_items_feed_at_root_order_0_with_live_badge_and_feed_settings_order_63 |
| `home_body` | `apps.feed.views.home.body(request) -> HttpResponse` (план) | T-7136 test_feed_registers_home_body_and_search_provider_feed_order_60 |
| `search_providers` | `apps.feed.services.search.search_providers() -> list[SearchProvider]`: `[SearchProvider(key="feed", title="Лента", order=60, search=search, count=count, available=<истина для любого вошедшего>)]` (план; имя функции — К6) | T-7131 test_provider_key_feed_title_order_60_after_lists, test_provider_available_to_every_logged_in_employee |
| `notification_kinds` | `apps.feed.notify_kinds.notification_kinds() -> list[NotificationKind]` — восемь видов (раздел 7) | T-7128; T-7136 test_feed_registers_eight_notification_kinds_file_purpose_audit_labels_and_stand_reset |
| `file_purposes` | `apps.feed.services.files.file_purposes() -> list[FilePurpose]`: `[FilePurpose("feed", still_waiting, clean, found)]` (план; поля — факт `core/extensions.py`) | T-7130 |
| `audit_labels` | `apps.feed.audit_labels.audit_labels() -> dict` в форме модуля `knowledge` (факт: `{"actions", "fields", "object_types", "values"}`; раздел 8.2) | T-7132 test_audit_labels_cover_every_feed_action_object_type_and_written_key |
| `stand_reset` | `apps.feed.stand.stand_reset` (раздел 1.3) | T-7134 |

`home_notices` лента не регистрирует (читает через `pages.collect_notices`); `role_sources`, `role_usage`,
`staff_directory`, `card_sections`, `day_marks`, `unit_usage`, `mail_renderers`, `login_links`, `top_bar_items`,
`ticket_card_parts` не использует (план). Шина: подписок нет; публикуется только `events.publish("object.viewed",
object_ref=…, user_id=…)` (форма вызова — факт `knowledge/services/articles.py:255`) — карточкой для `feed.post:<id>` и для
`feed.post:<id>:c<cid>` каждого своего комментария этой записи (план). Тесты T-7136 test_feed_does_not_register_home_notices,
test_feed_has_no_bus_subscriptions_and_publishes_only_object_viewed; T-7108 test_card_publishes_object_viewed_for_post_and_each_own_comment.

### 3.4. Выключение модулей в тестах (решения 22 и 52 задач)

| Что | Требование | Тесты |
|---|---|---|
| «Без `feed`» | `support_feed.without_feed()` — контекст: на время блока из всех точек реестра снимаются функции, у которых `__module__` начинается с `apps.feed`; `INSTALLED_APPS` не перезагружается (как `support_lists.without_lists`, факт) | T-7104, T-7131, T-7136, T-7138 |
| «Без `org`» | `support_feed.without_org()` — контекст: `django.apps.apps.is_installed("apps.org")` ложен, прочие ответы как были; код `feed` спрашивает `apps.is_installed` в момент вызова, а не при импорте; для `notify` — прежний `support_lists.without_app(monkeypatch, "apps.notify")` | T-7102a test_without_org_chain_is_empty_and_unit_recipients_grant_nothing |
| Маршруты `asgi` | `support_feed.reload_asgi_without_feed()` — контекст: перезагружает `config.asgi` с подменой `django.apps.apps.is_installed` (для `"apps.feed"` ложно) и отдаёт модуль; после блока модуль перезагружается заново без подмены (решение 52 задач) | T-7126a test_asgi_without_feed_has_no_ws_feed_route_and_ws_notify_as_before; T-7136 test_asgi_routes_without_feed_app_have_no_ws_feed_and_keep_ws_notify |
| Адреса и cron без модуля | разбор исходника `config/urls.py` и `config/cron.py` модулем `ast`: подключение адресов и обе записи — внутри `if apps.is_installed("apps.feed"):` (решение 52 задач) | T-7135 |
| Охрана `is_installed` | для `org` и `notify`, которые `feed` импортирует, в пакете `apps/feed` есть строки `apps.is_installed("apps.org")` и `apps.is_installed("apps.notify")` (как CONTRACT-006, 3.4) | T-7136 test_feed_has_is_installed_guard_for_each_org_and_notify_import |

## 4. Прежние модули

### 4.1. `org.services.structure` (план)

| Функция | Требование | Тесты |
|---|---|---|
| `subtree_member_ids(unit_ids) -> frozenset[int]` | номера сотрудников, состоящих (основная работа и совместительство) в этих узлах или во вложенных; уволенных нет (как `units_of`); заблокированные входят — их отсеивает `feed` по `User.state`; пустой вход — пустое множество; несуществующие номера ничего не дают (последнее — решение контракта К14) | T-7137 test_subtree_member_ids_equals_descendants_direct_members_with_secondary_jobs_without_dismissed_with_blocked_and_no_invited_in_data |
| `unit_chains(user_ids) -> dict[int, frozenset[int]]` | для каждого переданного номера — то же, что `unit_chain_ids(user)`; двумя запросами; номер без членства — ключ с пустым множеством (ключ есть всегда — решение контракта К14) | T-7137 test_unit_chains_equals_unit_chain_ids_for_each_user_in_two_queries |
| Прежние (факт) | `unit_chain_ids(user) -> frozenset[int]`, `all_units() -> list[UnitRef]`, `unit_refs(ids) -> dict[int, UnitRef]` (несуществующих номеров в словаре нет), `descendants`, `units_of` — имена, сигнатуры и результаты прежние | T-7137 test_previous_structure_functions_keep_names_signatures_and_results |
| Путь узла в подсказке | названия узлов цепочки от корня до узла через « / » (как CONTRACT-006, 4.1, решение контракта того среза; здесь — принятое, без изменений) | T-7108 test_pick_to_finds_unit_by_name_part_and_path_part_and_shows_path |

### 4.2. `notify` (план)

| Что | Требование | Тесты |
|---|---|---|
| `dispatch.create(kind_code, drafts) -> list[int]` | факт; `feed` зовёт его атрибутом модуля (`dispatch.create(...)`, без `from … import create`) из `feed.services.posts`, `comments`, `likes`, `reminders` — так подмена `monkeypatch.setattr("apps.notify.services.dispatch.create", …)` действует (как CONTRACT-006, 4.3; решение 49 задач) | T-7107 test_dispatch_create_error_rolls_back_post_recipients_and_file_binding; T-7114; T-7127 |
| Склейка с обновлением текста | при склейке (под прежним замком `pg_advisory_xact_lock` ключа склейки) и `kind.coalesce_text` задан — `text` непрочитанного = `kind.coalesce_text(user_id, object_ref, since)`, `since` — `created_at` непрочитанного; `url` не меняется; кадр колокольчику не шлётся; без `coalesce_text` — прежний пропуск (план) | T-7126b test_coalesce_text_updates_unread_text_with_since_as_its_creation_time, test_coalesce_text_update_happens_under_coalesce_key_lock, test_coalesce_text_update_keeps_url_and_sends_no_bell_frame, test_coalesce_without_coalesce_text_keeps_first_text_as_before |
| Фильтр `kind.channels` (шесть мест, план) | `prefs._listed` (и через него `channels_for`), `prefs.effective`, сохранение «Моих уведомлений», `views/me._table_context` (`has_box=False`), `views/admin._rows` и разбор POST, `services/settings._normalized_defaults`; у вида без `channels` — прежнее поведение | T-7126b test_listed_and_channels_for_drop_channel_outside_kind_channels … test_kind_without_channels_keeps_cells_and_channels_as_before |
| Ячейка вне `channels` (решение 43 (в) задач) | в «Моих уведомлениях» и в таблице умолчаний администратора — `td[data-channel="<канал>"]` без флажка, с `data-available="0"`, без подсказки привязки | T-7126b test_my_notifications_table_cell_outside_kind_channels_has_no_box; T-7128 |
| Снимок `matrix` (решение 43 (б) задач) | после первого сохранения содержит все строки каталога; у `feed.like` — пустой список каналов вне портала (`"feed.like": []`) | T-7138 |
| `live.group(user_id) -> str` | `"notify.u.{id}"` (факт) | T-7122, T-7123 |
| `live.push` | слой — `get_channel_layer("publish")` атрибутом модуля `apps.notify.services.live.get_channel_layer` (факт: сейчас `get_channel_layer()`); кадр и порядок частей прежние; сбой слоя — предупреждение в журнале, без исключения (план) | T-7126a test_live_push_takes_publish_channel_layer, test_live_push_frame_and_parts_order_as_before, test_live_push_layer_failure_only_logs_warning |
| `NotifyConsumer` | на `SessionGuardMixin`; обработчик `async notify_html(self, event)` шлёт `event["html"]` как есть (`await self.send(text_data=…)`); число, системное уведомление, привязка, входящие сообщения — прежние (план) | T-7126a test_notify_html_handler_sends_ready_fragment_as_is, test_notify_consumer_count_system_notice_and_group_binding_as_before, test_notify_consumer_ignores_incoming_messages_as_before |
| `still_relevant` видов ленты | `apps.feed.notify_kinds.still_relevant(user_id, object_ref) -> bool`: разбор `feed.post:<id>` или `feed.post:<id>:c<cid>`; запись (и комментарий) существуют и `visibility.can_see(user_id, post_id)`; иначе `False` — письмо и сводка не уходят (план; имя функции — решение контракта К15) | T-7128 test_still_relevant_deleted_post_email_and_digest_not_sent, test_still_relevant_deleted_comment_email_not_sent, test_still_relevant_recipient_stopped_seeing_email_not_sent_link_404; T-7103 |

### 4.3. Публичные функции ядра и прежних модулей, которые зовёт `feed` (решение 46 задач; на этот перечень опирается T-7136)

| Модуль | Что `feed` из него зовёт |
|---|---|
| `apps.core.services.comments` | `add`, `update`, `list_for`, `delete`, `delete_for`, `CommentError` |
| `apps.core.services.pdn_patterns` | `EMAIL`, `PHONE` |
| `apps.core.views.pages` | `collect_notices` |
| `apps.core.ws` | `SessionGuardMixin` |
| `apps.core.services.uploads` (план пишет `core.uploads`; полное имя — решение 46 задач) | `reject_reason(name, data, size, max_file)` (`"too_big"`, `"executable"`, `"encrypted"`, `""` — факт), `store(data, name, "feed") -> StoredFile`, `ImageTooLarge`, `detect_image`, `move` |
| `apps.core.services.files` | `photo_url(user, 96)`, `remove_paths(paths)`, `attachment_path(stored)` |
| `apps.core.services.permissions` | `permissions_of(user, fresh=…)`, `has_permission`, `require_permission` |
| `apps.core.services.audit` | `record(action, *, actor, object_type, object_id, before, after)` |
| `apps.core.services.file_response` | `inline_image(stored, image_format)`, `download(stored, filename)` |
| Ядро, без которого модуль не собирается (решение контракта К16: решение 46 перечисляет службы, а не записи и модели) | `apps.core.extensions` (`register`, `NotificationKind`, `Draft`, `SearchProvider`, `SearchRow`, `ParsedQuery`, `FilePurpose`), `apps.core.models` (`User`, `Comment`, `StoredFile`, `Permission`, `Role` — связи и миграция `0002`), `apps.core.events.publish` (только `object.viewed`), `apps.core.widgets.moscow_today` |
| `apps.org.services.structure` (под `apps.is_installed("apps.org")`) | `unit_chain_ids`, `subtree_member_ids`, `unit_chains`, `all_units`, `unit_refs` |
| `apps.notify.services.dispatch` (под `apps.is_installed("apps.notify")`) | `create` |
| `apps.notify.services.live` (под `apps.is_installed("apps.notify")`) | `group` |

`feed` не импортирует модели `org`, `notify`, `knowledge`, `servicedesk`, `lists`, `search` и ничего из `servicedesk`,
`knowledge`, `lists`, `search`; `core`, `org`, `notify`, `knowledge`, `servicedesk`, `lists`, `search` не импортируют `feed`
(план; в коде ядра нет и строк-путей `apps.feed…` вне докстрингов — `impact.md` У8). Тесты T-7136
test_core_org_notify_knowledge_servicedesk_lists_search_do_not_import_feed,
test_feed_does_not_import_models_of_org_notify_or_other_apps_and_imports_nothing_from_servicedesk_knowledge_lists_search,
test_feed_imports_org_only_through_services_structure, test_feed_imports_notify_only_through_dispatch_and_live_group.

## 5. Службы `feed`, исключения, точки подмены и помощники

Модули — `apps/feed/services/<модуль>.py`. Аргумент `user`, `actor` — `core.User`; `post` — объект `Post`; `post_id`,
`comment_id` — номера. Сигнатуры — решение контракта К17 там, где план назвал только имя функции (имена функций из
строки T-7100 — план и решения задач). Время — параметр `now` (по умолчанию `timezone.now()` один раз на действие,
решение 59 задач).

Права в службах (план, «Видимость и аудитория записи»: «право проверяется в начале представления и повторно в службе
под `select_for_update` строки записи»): служба, которая принимает актора, сама находит запись через
`visibility.get_post` (не видна — `Http404`) и перепроверяет право (нет — `django.core.exceptions.PermissionDenied`).
Отказы с текстом — `FeedError` (5.1).

### 5.1. Исключения и общие типы (`apps/feed/services/errors.py`; модуль — решение контракта К2)

| Имя | Требование | Тесты |
|---|---|---|
| `FeedError(code, field="", params=None)` | `code` — ключ `TEXTS` (раздел 13) и значение `data-code`; `field` — имя поля формы для `[data-error]` («» — общий отказ); `params` — подстановки `str.format` | все тесты отказов |
| `PdnFound(found)` | не отказ, а предупреждение о ПДн: `found` — список найденных строк (не больше 20, без повторов); службы поднимают его до записи, если находки есть, а `pdn_confirmed` ложно | T-7111 |

### 5.2. `visibility` (план)

| Имя | Требование | Тесты |
|---|---|---|
| `Viewer` | `NamedTuple(id, chain, moderator, post_all, link_staff)`: `chain` — `frozenset[int]` узлов и их предков (`unit_chain_ids` под `apps.is_installed("apps.org")`, иначе пусто); `moderator` — право `feed.moderate`; `post_all` — `feed.post_all`; `link_staff` — право `staff.view` или `accounts.manage` (поле `link_staff` — решение контракта К17: оно нужно `render_plain` и ссылке ФИО той же страницы) | T-7102a test_viewer_chain_is_member_units_and_ancestors_from_org_unit_chain_ids |
| `viewer(user) -> Viewer` | один раз на запрос, хранится в `user._feed_viewer` (только у объекта запроса) | T-7102a test_viewer_computed_once_per_request_and_cached_on_request_user |
| `visible_posts(user) -> QuerySet[Post]` | фильтр плана: `author_id = me OR to_all OR EXISTS(… r.unit_id = ANY(%s) OR r.user_id = me)`, цепочка — параметром-массивом; недействующий сотрудник — пустой набор | T-7102a test_visible_posts_passes_chain_as_array_parameter_without_unit_ids_in_sql_text, test_dismissed_or_blocked_viewer_gets_no_posts_from_visible_posts |
| `get_post(user, post_id) -> Post` | запись или `Http404` — одинаково для невидимой и несуществующей | T-7102a test_get_post_raises_same_http404_for_invisible_and_missing_post |
| `can_see(user_id, post_id) -> bool` | одна выборка `visible_posts` | T-7102a test_can_see_agrees_with_visible_posts_for_viewer_and_non_viewer |
| `audience(post) -> frozenset[int]` | действующие сотрудники, которые видят запись: «Всем» — все с `state` не `blocked` и не `dismissed`; узлы — `subtree_member_ids`; люди — `Recipient.user`; плюс автор; затем фильтр состояния одним запросом; без `org` узлы ничего не дают | T-7102a test_audience_to_all_is_every_active_employee_and_author_without_dismissed_or_blocked, test_audience_unions_subtree_members_person_recipients_and_author_then_drops_inactive |
| `can_edit(user, post) -> bool` | только автор | T-7102a test_can_edit_post_only_author_not_moderator_or_addressee |
| `can_delete(user, post) -> bool` | автор или модератор, который видит запись | T-7102a test_can_delete_post_author_or_moderator_who_sees_not_moderator_who_does_not |
| `can_comment(user, post) -> bool` | каждый, кто видит (комментарий, «Нравится», ответ — общее условие видимости; прочие условия ответа — 5.4) | T-7102a test_comment_like_and_answer_allowed_to_every_viewer_and_denied_to_non_viewer |
| `can_edit_comment(user, comment) -> bool`, `can_delete_comment(user, post, comment) -> bool` | править — автор комментария; удалить — автор комментария или модератор, который видит запись; автор записи чужие не удаляет (имена — К17) | T-7102a test_comment_edit_by_its_author_only_delete_by_author_or_moderator_who_sees |

### 5.3. Публикация, адресаты, текст, упоминания, ПДн

| Имя | Требование | Тесты |
|---|---|---|
| `posts.publish(user, data, *, now=None) -> Post` | `data` — `QueryDict` или словарь с ключами полей формы раздела 10.2 (`to`, `files` — списки); одна транзакция: запись, строки `to`, упоминания, привязка файлов, вектор, `dispatch.create`; рассылка — `transaction.on_commit`; отказ — `FeedError`, ПДн без подтверждения — `PdnFound` | T-7107 |
| `posts.edit(user, post_id, data, *, now=None) -> Post` | правка под `select_for_update` записи; вид не меняется; «Кому» только расширяется; `edited_at = now` | T-7117 test_edit_locks_post_row_with_select_for_update |
| `posts.delete(user, post_id) -> None` | одна транзакция по плану («Правка и удаление»); `audience(post)` считается до `post.delete()` и передаётся замыканию `on_commit` | T-7118 test_post_delete_locks_post_row_with_select_for_update |
| `recipients.parse(viewer, values, *, saved=None) -> Targets` | `values` — значения `to` (`"all"`, `"u<id>"`, `"p<id>"`); `Targets` — `NamedTuple(to_all, unit_ids, user_ids)`; `saved` — сохранённые адресаты при правке (проверки «существует» и «действующий» — только для добавленных); отказы — коды `post_all_denied`, `no_recipients`, `too_many_recipients`, `only_add_recipients` (раздел 13); неизвестный узел или недействующий человек — отдельный код `recipient_invalid` с тем же текстом, что у `no_recipients` (решение контракта К18: `recipient_invalid` с текстом «Выберите, кому адресована запись») | T-7107, T-7117 |
| Значения `to` (решение контракта К19) | `u<id>` — узел (unit), `p<id>` — человек (person), `all` — «Всем»; таблетка упомянутого — без поля `to` | T-7107, T-7117, T-7140a |
| `recipients.line(post) -> Line` | `Line(items: list[str], more: int)`: «Всем», названия узлов (`unit_refs`; нет — «Подразделение удалено»), ФИО людей без повторов (строки `to` и `mention` одного человека — один раз), уволенный — «ФИО (уволен)»; первые пять и `more` — остаток | T-7102b |
| `recipients.full(post) -> list[str]` | тот же порядок без обрезки (для `/feed/<id>/to/`; имя — К17) | T-7102b |
| `mentions.extract(text) -> list[int]` | номера маркеров `@\[([1-9]\d{0,8})\]` без повторов, в порядке появления; разных больше 20 — `FeedError("too_many_mentions", "text")` | T-7110 |
| `mentions.sync(post, text, old_text="") -> set[int]` | добавляет строки `Recipient(via="mention")` действующим упомянутым и возвращает множество номеров, которых не было в `old_text` (впервые упомянутые этим текстом; решение 47 задач); недействующий и несуществующий номер — не адресат | T-7110 test_only_id_absent_from_previous_version_of_text_is_new_mention_on_edit; T-7127 |
| `text.render_plain(text, people, link_staff) -> SafeString` | план («Вывод»); `people` — `dict[int, str]` номер → ФИО | T-7109 |
| `text.snippet(text, limit, people=None) -> str` | маркер → «@ФИО» (без `people` — ФИО одним запросом), пробелы схлопнуты, без разметки, обрезка по слову до `limit` с «…» (третий аргумент — К17) | T-7109 test_snippet_cuts_by_word_with_ellipsis_at_100_60_and_300 |
| `pdn.find_plain(*texts) -> list[str]` | `EMAIL`, `PHONE` ядра по всему тексту; без повторов; не больше 20 | T-7111 |

### 5.4. Важное, событие, напоминания, комментарии, отметки, показы

| Имя | Требование | Тесты |
|---|---|---|
| `important.until(term, date, today) -> datetime` | `term` — `day`, `week`, `month`, `date`; полночь Europe/Moscow после последнего дня срока (план); `date` при `term="date"` — `datetime.date`; раньше завтрашнего дня (вчера, сегодня; завтра допустимо) — `FeedError("date_passed", "term")`; позже чем через год — `FeedError("term_too_far", "term")` (отказ — у поля срока `term`, ввод даты — `until`: так в именах тестов T-7112 «…_at_term_field») | T-7112 |
| `important.stats(post) -> ReadStats` | `ReadStats(read: int, total: int)` — N и M плана | T-7112 test_author_sees_read_n_of_m_where_m_is_audience_without_author |
| `important.mark_read(user, post_id, *, now=None) -> None` | `ReadMark` `get_or_create`; автор или срок истёк — `PermissionDenied` (403 с причиной, раздел 10.2) | T-7112 |
| `events.validate(data, *, now, editing=None) -> EventFields` | поля и отказы плана («Событие и напоминания»); `editing` — запись при правке (правила начавшегося события); `EventFields(title, place, start, end)` | T-7113 |
| `events.remind_at(start, now) -> datetime \| None` | `start − 1 ч`, если `start − now ≥ 1 ч`, иначе `None` | T-7114 |
| `events.answer(user, post_id, answer, *, now=None) -> EventAnswer` | `update_or_create`; автор — `PermissionDenied`; событие началось — `FeedError("answers_closed")` | T-7113 |
| `reminders.select_due(now, exclude) -> int \| None` | номер одной записи литералом плана `… remind_at <= %s AND event_start > %s AND reminded_for_start IS DISTINCT FROM event_start AND id <> ALL(%s) ORDER BY remind_at LIMIT 1 FOR UPDATE SKIP LOCKED` (`now` и `exclude` — параметры) | T-7114 test_reminder_selection_sql_takes_one_due_unreminded_future_event_for_update_skip_locked |
| `reminders.remind_one(post_id, now) -> bool` | в той же транзакции: строка записи (нет — `False`, без ошибки), получатели, `dispatch.create("feed.event_reminder", …)`, `reminded_for_start = event_start`, `remind_at = NULL` | T-7114 |
| `reminders.run(now) -> RunResult` | цикл не больше 200 событий; каждое — своя транзакция с перехватом исключения; сбойное — лог `apps.feed.tasks` (номер записи, без текста), номер — в `exclude` до конца запуска; `RunResult(reminded, failed)` | T-7114 test_one_run_reminds_at_most_200_events_and_next_run_takes_the_rest |
| `comments.add(user, post_id, text, *, files=(), pdn_confirmed=False, now=None) -> Comment` | одна транзакция: `core.services.comments.add(user, "feed.post:<id>", text)`, `FeedComment`, упоминания, файлы, уведомления; коды ядра `empty`, `too_long` → `FeedError("empty_text")`, `FeedError("too_long", params={"limit": "4000"})` | T-7119 |
| `comments.post_for_comment(user, post_id) -> Post` | проверка видимости перед вставкой (без замка строки записи — план); `comments.add` зовёт её атрибутом модуля (точка подмены, 5.8) | T-7118 test_comment_on_post_deleted_between_check_and_insert_rolls_back_without_orphan_core_comment |
| `comments.edit(user, comment_id, text, *, files=(), remove=(), pdn_confirmed=False, now=None) -> Comment`, `comments.delete(user, comment_id) -> None` | план; только комментарии с `object_ref` `feed.post:` (иные — `Http404`) | T-7118; T-7119 test_article_comment_edit_like_and_files_via_feed_urls_return_404 |
| `likes.toggle_post(user, post_id) -> bool`, `likes.toggle_comment(user, comment_id) -> bool` | `True` — после нажатия отметка стоит; нарушение уникальности при создании перехватывается и считается «уже есть»; удаление отсутствующей строки — не ошибка | T-7120 |
| `likes.find_mark(kind, target_id, user_id) -> bool` | `kind` — `"post"` или `"comment"`; есть ли отметка; `toggle_*` зовут её атрибутом модуля (точка подмены, 5.8) | T-7120 test_two_post_like_creates_in_a_row_leave_one_mark_duplicate_caught_as_existing |
| `unread.count(user, *, now=None) -> int` | литерал плана с `LIMIT 100`, окно 30 дней — параметром | T-7121 |
| `unread.counts(user_ids, *, now=None) -> dict[int, int]` | один запрос множествами; ключ — каждый переданный номер | T-7121 test_counts_for_many_equals_count_for_each_of_100_employees |
| `unread.mark_shown(user, post_ids) -> None` | один `INSERT … ON CONFLICT DO NOTHING` пачкой; свои записи не пишутся | T-7121 test_shown_written_by_single_insert_on_conflict_do_nothing_repeat_show_no_error |

### 5.5. Рассылка, файлы, поиск, срок хранения, уведомления, страница

| Имя | Требование | Тесты |
|---|---|---|
| `live.publish_event(post_id, action, *, comment_id=None, recipients=None, owner_id=None) -> None` | зовётся из `transaction.on_commit`; `recipients` — заранее снятое множество (удаление записи), иначе `audience(post)` на момент рассылки; одно сообщение `feed.event` (раздел 11) в группы `feed.u.{id}` через `get_channel_layer("publish")` атрибутом модуля `apps.feed.services.live.get_channel_layer`; все исключения — предупреждение в журнал `apps.feed.services.live` | T-7122, T-7123 |
| `live.push_counts(user_ids) -> None` | вторая рассылка: `{"type": "notify.html", "html": <_badge.html с hx-swap-oob>}` в группы `notify.u.{id}` (через `live.group`); без `notify` — ничего | T-7123 test_feed_count_frame_after_publish_is_notify_html_menu_badge_feed_oob_on_notify_socket |
| `files.upload(user, uploaded, *, scope, post_id=None, comment_id=None, have=()) -> FeedFile` | отказы плана; строка `FeedFile(post=None, comment=None, uploaded_by=user)` | T-7129 |
| `files.bind(user, ids, *, post, comment=None) -> None` | условный `UPDATE … WHERE id = ANY(%s) AND post_id IS NULL AND comment_id IS NULL AND uploaded_by_id = %s` с проверкой числа строк; меньше присланного — `FeedError("file_missing", "files")`; пределы — под `select_for_update` записи | T-7129 test_publish_binds_files_by_conditional_update_with_uploader_parameter, test_bind_fewer_rows_than_sent_rolls_back_with_missing_id_refusal |
| `files.remove_unbound(user, file_id) -> None` | только свой непривязанный, иначе `Http404` | T-7129 test_remove_before_publish_only_own_unbound_file |
| `thumbs.build(source_path, stored_id) -> str` | эскиз по плану; возвращает путь относительно `PROTECTED_ROOT` (`attachments/thumbs/<stored_id>.jpg` или `.webp`) или `""`, если тип не картинка; зовётся из `clean` назначения `feed` атрибутом модуля (точка подмены, 5.8) | T-7130 |
| `search.vectors(*, post_ids=(), comment_ids=()) -> None` | литерал SQL с параметрами по образцу `knowledge/services/vectors.py` (план) | T-7131 test_post_vector_event_title_place_weight_a_text_weight_b_without_markers |
| `search.search(user, parsed, limit, offset)`, `search.count(user, parsed)` | раздел 9 | T-7131 |
| `retention.boundary(now, years) -> datetime` | замена года, 29 февраля → 28 февраля (план) | T-7115 test_term_boundary_replaces_year_and_february_29_becomes_february_28 |
| `retention.select_batch(boundary, limit=1000) -> list[int]` | номера записей `published_at < %s ORDER BY published_at, id LIMIT 1000` (лимит — решение 9, время параметром — решение 59, порядок — решение контракта К17) | T-7115 |
| `retention.purge_batch(ids, now) -> int` | одна пачка в своей транзакции: пути файлов, `Comment.objects.filter(object_ref__in=refs).delete()`, записи, строки `StoredFile`; диск — после фиксации; возвращает число действительно удалённых записей (решение 50 задач) | T-7115 test_2500_old_posts_are_deleted_in_three_batches_of_1000_by_batch_spy_and_limit_1000_selects_and_journal_posts_is_2500 |
| `retention.run(now) -> int` | три шага по порядку плана: показы старше 31 дня, пачки, непривязанные старше 24 часов; журнал `feed.retention_purged` при N > 0; `VACUUM` не зовёт | T-7115 |
| `retention.count_older(years, now) -> int` | число записей с `published_at` раньше границы нового срока (второй шаг настройки) | T-7116 |
| `notify_rules.RuleEvent` | `NamedTuple(action, post, actor_id, audience, before=frozenset(), to_people=frozenset(), mentioned=frozenset(), event_changed=False, comment=None, commenters=frozenset(), liked_comment=None)`: `action` — `"publish"`, `"edit"`, `"comment"`, `"like"`; `audience` — `audience(post)` после действия; `before` — до правки; `to_people` — люди строк `to` (при правке — добавленные); `mentioned` — возврат `mentions.sync`; `commenters` — прежние комментаторы записи; `liked_comment` — комментарий при «Нравится» комментария (вход — решение 51 задач; поля — К20) | T-7127 test_notify_rules_decide_applies_full_priority_order |
| `notify_rules.decide(event) -> dict[int, tuple[str, Draft]]` | получатель → (код вида, черновик `Draft(user_id, text, url, object_ref)` ядра); только из `event.audience`, без `actor_id` и недействующих; один вид по `notify_rules.PRIORITY = ("feed.mention", "feed.invite", "feed.event_changed", "feed.important", "feed.for_you", "feed.comment")` (план); `feed.like` — отдельное действие без конкуренции | T-7127 |
| `feed_settings.get() -> FeedSettings`, `feed_settings.save(actor, years, *, confirmed=False, now=None) -> SaveResult` | `SaveResult(saved: bool, to_delete: int \| None)`: уменьшение без `confirmed` — `saved=False`, `to_delete=N`; вне 1–10 — `FeedError("retention_range", "retention_years")`; сохранение пишет журнал (раздел 8) | T-7116 test_settings_feed_without_settings_portal_is_403_on_get_and_post_without_calling_settings_service |
| `page.parse_filter(query) -> FeedFilter` | `FeedFilter(f, author, date_from, date_to)` — белый список плана; неверное отбрасывается | T-7105 |
| `page.build(user, flt, *, before=None, opened=None, now=None) -> FeedPage` | `FeedPage(posts, important, more_cursor, opened)`: страница по курсору плана, блок важных, сборка карточек без N+1 | T-7105, T-7106 |
| `tasks.remind_events(now=None)`, `tasks.retention_night(now=None)` | задания cron; зовут `reminders.run(now or timezone.now())` и `retention.run(…)` (решение 59 задач) | T-7114, T-7115 |

### 5.6. `FeedConsumer` (`apps/feed/consumers.py`, план)

| Что | Требование | Тесты |
|---|---|---|
| `CHECK_INTERVAL = 25` | модульное значение; `check_interval()` читает его при каждом ожидании | T-7124 |
| Подключение | `SessionGuardMixin.guard_connect()`; Origin — `AllowedHostsOriginValidator` (чужой — отказ до `accept`); разбор `query_string` по белому списку (`f`, `author`, `from`, `to` или `post`; прочее отбрасывается); `group_add("feed.u.{id}")` | T-7124 test_connect_adds_socket_to_personal_group_feed_u_id, test_query_keeps_only_filter_keys_or_post_and_drops_foreign_keys |
| Состояние | `ids` (номера записей страницы, не больше 300), `pending` (номер → время публикации), фильтр | T-7125 |
| Обработчик слоя | `async feed_event(self, event)` (имя по типу `feed.event` — правило Channels); ошибка слоя каналов в потребителе — закрыть 1011 | T-7124 test_channel_layer_error_in_consumer_closes_with_1011 |
| Входящие | `sync`, `add` (раздел 11.2); больше 16 КБ (`len(text_data.encode()) > 16384`) — закрыть 1009; иное — игнорировать; сессию не продлевают | T-7125 |

### 5.7. Заметки к службам

- Комментарий во время удаления записи (решение 15 задач): `core.Comment` и `FeedComment` создаются в одной транзакции;
  проверка отката — под `SET CONSTRAINTS ALL IMMEDIATE` (иначе внешний ключ в тесте проверяется только в конце; строка
  T-7101).
- Сбой эскиза не откладывает «чистый»: ошибка `thumbs.build` ловится внутри `clean` отдельно от переноса, пишется в
  журнал без имени файла, `FeedFile.thumb` остаётся пустым, частично записанный файл эскиза стирается (план).
- Рассылка и уведомления после фиксации: тест «только после фиксации» проверяет, что до выхода из
  `django_capture_on_commit_callbacks` сообщений слоя нет, а после — есть.

### 5.8. Точки подмены для тестов гонок и сбоев (решения 6, 9, 12, 15, 49, 51 задач)

| Подмена | Что подменяется | Тесты |
|---|---|---|
| Слой `publish` недоступен | `support_feed.layer_down(delay=0.0)` — контекст: фабрики `apps.feed.services.live.get_channel_layer` и `apps.notify.services.live.get_channel_layer` отдают слой, у которого `group_send` и `send` через `delay` секунд поднимают `TimeoutError` (по умолчанию сразу — как закрытый порт наблюдения T-7305, решение 40 задач; значение по умолчанию — решение контракта К21) | T-7123 test_publish_with_layer_down_saves_post_and_answers_faster_than_3_seconds, test_comment_with_layer_down_is_saved, test_layer_down_writes_warning_to_application_log |
| Шпион слоя `publish` | `support_feed.layer_spy(passthrough=True)` — контекст: оборачивает те же две фабрики; запоминает аргументы фабрики (`aliases`, ожидается `"publish"`) и каждое `group_send(group, message)` (`calls` — список пар, `by_group` — словарь «группа → список сообщений»); при `passthrough=True` отправка идёт в настоящий слой | T-7122 test_broadcast_goes_through_publish_layer_one_message_per_recipient_group; T-7123; T-7126a test_live_push_takes_publish_channel_layer |
| Ошибка слоя в `FeedConsumer` | `monkeypatch.setattr("channels_redis.core.RedisChannelLayer.group_add", <корутина, поднимающая OSError>)` — потребитель принимает соединение и закрывает его кодом 1011; та же реакция на ошибку слоя в `feed_event` и при ответе на `sync` (решение контракта К22: место подмены — метод слоя, который потребитель зовёт сам) | T-7124 test_channel_layer_error_in_consumer_closes_with_1011 |
| Ошибка `ws_state` в цикле | `monkeypatch.setattr("apps.core.services.sessions.ws_state", fake)`: `fake` при первом вызове (подключение) отдаёт `"ok"`, затем поднимает исключение; `CHECK_INTERVAL` подменён на 0,1–0,2 с; ожидание — закрытие 1013 (решение 49 задач) | T-7124 test_ws_state_error_in_check_loop_closes_with_1013; T-7126a test_notify_consumer_check_loop_error_closes_with_1013 |
| Тестовый потребитель на примеси | класс внутри теста: `class Probe(SessionGuardMixin, AsyncWebsocketConsumer)` с `check_interval()` → 0,1 и `on_check()`, записывающим вызов; маршрут — своё `URLRouter([...])` через `ApplicationCommunicator` (решение 49 задач) | T-7126a test_session_guard_loop_waits_check_interval_then_calls_on_check_and_ws_state |
| Создание уведомлений | `monkeypatch.setattr("apps.notify.services.dispatch.create", …)` — сбой (откат публикации, комментария) и шпион; сбой одного события напоминаний — подменная функция поднимает исключение для `object_ref == "feed.post:<номер>"`, для прочих зовёт настоящую (решения 12, 49 задач) | T-7107, T-7114 test_failing_event_is_logged_by_post_id_without_text_other_reminders_are_sent_and_job_does_not_fail, T-7119, T-7127 |
| Лог приложения | логгер `apps.feed.tasks` (сбой события напоминаний: номер записи, без текста записи и названия события; решение 49 задач); логгер `apps.feed.services.live` (сбой рассылки); логгер `apps.feed.services.files` (сбой эскиза, без имени файла) — тесты ловят `caplog` (имена второго и третьего логгеров — решение контракта К23) | T-7114, T-7123, T-7130 |
| Между выборкой и замком: напоминания | `support_feed.act_between_select_and_lock(monkeypatch, "reminders", action)` оборачивает `apps.feed.services.reminders.select_due`: после настоящей выборки зовёт `action(post_id)` (например, удаляет запись) и возвращает номер как был; возвращает список выданных номеров | T-7114 test_event_deleted_after_selection_is_skipped_without_error |
| Между выборкой и замком: ночное задание | то же с `"retention"` — оборачивает `apps.feed.services.retention.select_batch`, `action(ids)` (решения 6 (в), 50 задач) | T-7115 test_post_deleted_between_batch_selection_and_delete_is_skipped_without_error_and_not_counted_in_journal_posts |
| Шпион пачки | `monkeypatch.setattr` на `apps.feed.services.retention.purge_batch` с проходом к настоящей функции (`retention.run` зовёт её атрибутом модуля) — число вызовов; плюс три выборки с `LIMIT 1000` в `capture_sql` (решение 9 задач) | T-7115 |
| Запись удалена между проверкой и вставкой `FeedComment` | `support_feed.delete_post_between_check_and_insert(monkeypatch)` оборачивает `apps.feed.services.comments.post_for_comment`: после настоящей проверки удаляет запись (`Post.objects.filter(pk=…).delete()`) и возвращает объект; затем `SET CONSTRAINTS ALL IMMEDIATE` даёт ошибку внешнего ключа, транзакция откатывается вместе с `core.Comment` (решение 15 задач; имя помощника — К24) | T-7118 test_comment_on_post_deleted_between_check_and_insert_rolls_back_without_orphan_core_comment |
| Отметка уже создана другим запросом | `support_feed.mark_created_between_check_and_insert(monkeypatch)` подменяет `apps.feed.services.likes.find_mark` так, что она отвечает «отметки нет», хотя строка уже есть: вставка упирается в уникальность, служба считает «уже есть» (для записи и комментария; имя помощника — К24) | T-7120 test_two_post_like_creates_in_a_row_leave_one_mark_duplicate_caught_as_existing, test_two_comment_like_creates_in_a_row_leave_one_mark_duplicate_caught_as_existing |
| Сбой эскиза | `monkeypatch.setattr("apps.feed.services.thumbs.build", <поднимает MemoryError или OSError>)` после частичной записи файла эскиза (подменная функция пишет файл и падает) | T-7130 test_thumb_failure_file_clean_without_thumb_log_without_name_partial_removed |
| Сбой записи файла и ClamAV | `support_kb.fail_file_write(monkeypatch)` (`core.services.uploads.write_file` поднимает `OSError`, факт); `support_org.scan_clean`, `scan_found`, `scan_unavailable` (решение 21 задач) | T-7130 |
| Без `org` | `support_feed.without_org()` (3.4) | T-7102a |
| Правило приоритета напрямую | `notify_rules.decide(RuleEvent(...))` без действий (решение 51 задач) | T-7127 test_notify_rules_decide_applies_full_priority_order |
| Снятие права модератора | сменой ролей средствами ядра (`roles.update_role`), отдельного помощника нет (решение 49 задач) | T-7123 test_revoked_moderator_right_makes_next_frame_reader_variant |

### 5.9. Помощники `tests/support_feed.py` (пишет T-7101; без `@pytest.fixture`, код среза — внутри функций)

| Имя | Сигнатура и поведение | Кто зовёт |
|---|---|---|
| `PERMISSIONS_007`, `TITLES_007`, `HOLDERS_007` | `("feed.post_all", "feed.moderate")`; `{"feed.post_all": "Писать всем", "feed.moderate": "Модерировать ленту"}`; `{"feed.post_all": (support.ADMIN_ROLE, support.MANAGER_ROLE, support.STAFF_ROLE), "feed.moderate": (support.ADMIN_ROLE,)}` — держатели после установки: «Писать всем» — три встроенные роли, «Модерировать ленту» — только администратор (`impact.md` «Общее»; кортеж названий ролей — К24) | T-7133, T-7138 |
| `POINTS_007`, `KIND_FIELDS_007`, `APPS_TAIL` | `("home_body",)`; `("channels", "coalesce_text")`; хвост `INSTALLED_APPS` (1.1) | T-7136, T-7137, T-7138 |
| `FEED_KINDS`, `FEED_CODES`, `FEED_TITLES`, `FEED_MODULE`, `FEED_LIKE`, `FEED_BOXED`, `FEED_CHANNELS`, `FEED_COALESCE` | `FEED_KINDS` — кортеж из восьми 8-кортежей ровно формата `TABLE` из `test_notify_catalog.py` (код, название, модуль, `order`, обязательность, каналы по умолчанию, события, внешний текст) по строкам 7.1, без `channels` и склейки (их T-7138 вставляет в `TABLE` как есть); `FEED_CHANNELS = {"feed.like": ("portal",)}` (у прочих видов — `None`); `FEED_COALESCE = frozenset({"feed.comment", "feed.like"})`; `FEED_BOXED` — все коды, кроме `feed.like` (разделение — К24) | T-7128, T-7138 |
| `FEED_JOBS`, `MENU_FEED`, `MENU_FEED_SETTINGS`, `FEED_SEARCH` | 1.2; 3.3; `("feed", "Лента", 60)` | T-7135, T-7104, T-7116, T-7131, T-7138 |
| `Session` | `NamedTuple(user, client)` (как `support_kb.Session`) | все |
| `as_writer(**extra)`, `as_plain(**extra)`, `as_moderator(**extra) -> Session` | сотрудник с ролью с правом `feed.post_all`; сотрудник без ролей (нет «Писать всем»); сотрудник с ролью с правом `feed.moderate`; вошли (имена `as_writer`, `as_plain` — К24; `as_moderator` — план) | все |
| `without_post_all(role) -> None` | снимает `feed.post_all` у роли средствами ядра (`roles.update_role`), кэш прав сбрасывается (план) | T-7107, T-7117, T-7133 |
| `make_post(author, kind="post", *, to=(), mentions=(), text="Текст записи", published_at=None, important_until=None, event=None, edited_at=None) -> Post` | прямой записью, без служб: элементы `to` — `"all"`, объект `core.User`, объект `org.Unit` или строки `"u<id>"`/`"p<id>"`; строки `Recipient(via="to")` с копией `published_at`; `mentions` — сотрудники: маркеры `@[id]` дописываются в текст, строки `via="mention"`; вектор — своим SQL помощника; `event` — словарь `title`, `place`, `start`, `end` | все |
| `make_event(author, *, start, end=None, title="Событие", place="Корпус 1", to=(), **extra) -> Post` | `kind="event"`, `remind_at` по правилу плана от текущего времени `Clock`; `end` по умолчанию — `start + 1 ч` | T-7113, T-7114 |
| `make_important(author, *, until=None, to=(), **extra) -> Post` | `kind="important"`, `important_until` по умолчанию — срок «День» от текущего времени | T-7106, T-7112 |
| `comment(post, author, text="Комментарий", *, created_at=None, mentions=()) -> Comment` | `core.Comment` (`object_ref="feed.post:<id>"`) и `FeedComment` прямой записью, вектор — SQL помощника | все |
| `like(target, user) -> PostLike \| CommentLike` | `target` — `Post` или `core.Comment` | T-7120, T-7128 |
| `attach(target, name="схема.png", data=None, *, status="clean", uploaded_by=None, write=False, thumb=False) -> FeedFile` | `target` — `Post`, `core.Comment` (тогда и `post` его записи) или `None` (непривязанный); строки `StoredFile(purpose="feed")` и `FeedFile`; `status` — `"pending"`, `"clean"`, `"quarantine"`; `write=True` пишет байты на диск (фикстура `protected_root`); `thumb=True` пишет файл эскиза и заполняет `thumb` | T-7118, T-7129, T-7130 |
| `without_feed()`, `without_org()`, `reload_asgi_without_feed()` | раздел 3.4 | T-7104, T-7126a, T-7131, T-7136, T-7138 |
| `run_seed(using=None, *, stand=False)` | функция `seed` миграции `feed 0002` (`importlib`, реестр `django.apps.apps`; решение 25 задач) | T-7133, T-7134 |
| `run_reminders(now) -> RunResult`, `run_retention(now) -> int` | `tasks.remind_events(now)` / `retention.run(now)` синхронно (решение 5 задач) | T-7112, T-7114, T-7115 |
| `ws_client(user, query="", *, hub=None, origin="http://testserver")` | корутина внутри сценария `support_notify.ws_run` (`hub` сценария передаётся, чтобы соединение закрылось по выходу из `ws_run`, как у `WsHub.connect`; параметр `hub` — К24): свой `scope` по образцу `WsHub.connect` (путь `/ws/feed/`, `query_string` из `query`, кука сессии из `client` вошедшего (`user` — `Session`); `user=None` — без входа), `ApplicationCommunicator` над `support_notify._application()`, возвращает `support_notify.WsClient` после ответа на `websocket.connect` (решение 7 задач; строка T-7101) | T-7122…T-7126a |
| `send_sync(client, ids, since)`, `send_add(client, ids, since=None)` | корутины: шлют `{"sync": {"ids": [...], "since": ISO}}` / `{"add": [...], "since": ISO}` (имена — К24) | T-7125 |
| `layer_down`, `layer_spy`, `act_between_select_and_lock`, `delete_post_between_check_and_insert`, `mark_created_between_check_and_insert` | раздел 5.8 | см. 5.8 |
| `capture_sql()`, `sql_of(func, *args, **kwargs)`, `assert_for_update(sqls, table)`, `assert_skip_locked(sqls, table)` | как в `support_kb` (повторный экспорт, факт); дополнительно `queries_with_params()` — контекст, отдающий пары «SQL до подстановки, параметры» (для проверок «значение — параметр»; имя — К24); таблицы — `feed_post`, `feed_feedfile`, `feed_recipient` | все тесты замков и SQL |
| `images()` | словарь картинок в памяти: `"jpeg_exif"` (JPEG с ориентацией EXIF), `"png_alpha"` (PNG с прозрачностью), `"gif_frames"` (GIF из нескольких кадров), `"huge"` (больше 40 Мп — `support_org.huge_pixels_png()`), `"broken"` (повреждённая картинка) (строка T-7101; ключи — К24) | T-7129, T-7130 |
| `email_of(local="ivanov", domain="example.test")`, `phone_of(*groups)` | как в `support_kb` (решение 23 задач) | T-7111, T-7154 |
| `moscow(year, month, day, hour=0, minute=0) -> datetime`, `moscow_text(moment) -> str` | как в `support_kb` | все |
| `feed_pages(post) -> tuple[str, ...]` | адреса страниц среза для проверок «по-русски» и «без `style=`»: `/`, `/feed/<id>/`, `/feed/<id>/edit/`, `/settings/feed/` (строка T-7101) | T-7135 |
| `post_part(html, post_id, part="") -> Fragment \| None` | часть записи по `id` `feed-post-<id>[-<part>]` в разметке (разбор как `support_notify.ws_fragments`; имя — К24) | T-7106, T-7122, T-7123 |

## 6. Места одной функции видимости (план, «Видимость и аудитория записи»)

`visibility` — единственное место решений о видимости; каждое место ниже зовёт его функции, тест на место — T-7103
(`test_feed_visibility_2.py`), тест «тот же ответ» — `support.same_failure`.

| № | Место | Функция | Тест T-7103 |
|---|---|---|---|
| V1 | лента `/` | `visible_posts` | test_invisible_post_absent_from_first_feed_page |
| V2 | «Ещё записи» `/feed/more/` | `visible_posts` | test_invisible_post_absent_from_more_posts |
| V3 | фильтры «Важные», «События», «Автор», период | `visible_posts` | test_invisible_post_absent_under_important_filter, …_events_filter, …_author_filter, …_period_filter |
| V4 | «Упоминают меня» | от `Recipient` `via='mention' AND user_id = me` (видимость выполнена сама, план) | test_mentions_filter_excludes_post_where_i_am_addressee_via_to_but_not_mentioned |
| V5 | карточка `/feed/<id>/` | `get_post` | test_invisible_post_card_returns_404_like_missing, test_invisible_post_response_same_code_page_and_not_found_text_as_missing |
| V6 | поиск (выдача и число) | условие `visible_posts` в SQL поставщика | test_invisible_post_and_its_comments_absent_from_search_without_count |
| V7 | файл и эскиз | `get_post` записи файла | test_file_of_invisible_post_returns_404_like_missing_file, test_thumb_of_invisible_post_returns_404_like_missing_file |
| V8 | списки: адресаты, отметившие записи и комментария, прочитавшие, ответившие, все комментарии | `get_post` | test_recipients_list_of_invisible_post_returns_404 … test_comments_list_of_invisible_post_returns_404 |
| V9 | `still_relevant` уведомлений | `can_see` | test_still_relevant_false_for_transferred_out_recipient_so_mail_not_sent |
| V10 | рассылка и число «Ленты» | `audience` | test_live_broadcast_sends_no_frame_about_invisible_post, test_feed_counter_does_not_grow_for_invisible_post |
| V11 | действия: «Прочитано», ответ, «Нравится», комментарий, правка и удаление записи и комментария | `get_post` | test_read_answer_and_like_on_invisible_post_return_404, test_new_comment_edit_and_delete_on_invisible_post_return_404, test_edit_delete_and_like_of_comment_on_invisible_post_return_404 |
| V12 | задание напоминаний | `audience` | T-7114 test_employee_not_seeing_event_gets_no_reminder |

## 7. Виды уведомлений и таблица «код вида → модуль»

### 7.1. Записи видов (`apps/feed/notify_kinds.py`; план «Уведомления», решение 43 (а) задач, `impact.md` «Общее»)

Общее для восьми видов: `module="Лента"`, `events=()` (уведомления создаёт `notify_rules` прямым вызовом
`dispatch.create`), `mandatory=False`, `available` — истина каждому, `still_relevant` — `notify_kinds.still_relevant`
(4.2). Столбцы `order`, код, название, каналы по умолчанию, `external_text` (с модулем, обязательностью и событиями выше) — строки
`support_feed.FEED_KINDS` в формате `TABLE` из `test_notify_catalog.py`; `channels` и склейка — отдельные константы
`FEED_CHANNELS`, `FEED_COALESCE` (5.9):

| `order` | Код | Название | Каналы по умолчанию | `channels` | `coalesce` / `coalesce_text` | `external_text` |
|---|---|---|---|---|---|---|
| 70 | `feed.for_you` | Запись для вас | `("portal", "email")` | `None` | нет | «Новая запись в ленте для вас» |
| 71 | `feed.mention` | Вас упомянули | `("portal", "email")` | `None` | нет | «Вас упомянули в ленте» |
| 72 | `feed.comment` | Новый комментарий | `("portal", "email")` | `None` | `True` / `comment_coalesce_text` | «Новый комментарий в ленте» |
| 73 | `feed.important` | Важная запись | `("portal", "email")` | `None` | нет | «Новая важная запись в ленте» |
| 74 | `feed.invite` | Приглашение на событие | `("portal", "email")` | `None` | нет | «Приглашение на событие в ленте» |
| 75 | `feed.event_changed` | Событие изменено | `("portal", "email")` | `None` | нет | «Событие в ленте изменено» |
| 76 | `feed.event_reminder` | Напоминание о событии | `("portal", "email")` | `None` | нет | «Скоро событие в ленте» |
| 77 | `feed.like` | Нравится | `("portal",)` | `("portal",)` | `True` / `like_coalesce_text` | `""` (внешних каналов нет; решение 43 (а) задач) |

`order` — по порядку строк таблицы плана (решение 43 (а) задач). Функции склейки — `apps.feed.notify_kinds.comment_coalesce_text(user_id,
object_ref, since) -> str` и `like_coalesce_text(user_id, object_ref, since) -> str` (имена — решение контракта К25).
Тесты T-7128 test_catalog_eight_feed_kinds_codes_titles_module_order_available_events_coalesce,
test_feed_kinds_default_channels_portal_and_email_like_portal_only, test_external_text_of_each_kind_constant_without_name_title_place_snippet.

### 7.2. Черновики уведомлений (план «Тексты», «Ссылки и `object_ref`»)

| Вид | `Draft.text` | `Draft.url` | `Draft.object_ref` |
|---|---|---|---|
| `feed.for_you` | «<ФИО>: запись для вас — «<отрывок>»» | `/feed/<id>/` | `feed.post:<id>` |
| `feed.mention` | «<ФИО> упомянул(а) вас: «<отрывок>»» | `/feed/<id>/` (в комментарии — `/feed/<id>/#c<cid>`) | `feed.post:<id>` |
| `feed.comment` | «<ФИО> прокомментировал(а) запись «<отрывок>»»; при склейке — «Новых комментариев: N к записи «<отрывок>»» (N = комментарии к записи от других после `since` плюс один; при N = 1 — обычный текст) | `/feed/<id>/#c<cid>` (адрес непрочитанного при склейке не меняется — ведёт к первому) | `feed.post:<id>` |
| `feed.important` | «Важная запись от <ФИО>: «<отрывок>»» | `/feed/<id>/` | `feed.post:<id>` |
| `feed.invite` | «<ФИО> приглашает на событие «<название>» <дата, время>» | `/feed/<id>/` | `feed.post:<id>` |
| `feed.event_changed` | «Событие «<название>» изменено: <дата, время, место>» | `/feed/<id>/` | `feed.post:<id>` |
| `feed.event_reminder` | «Через час: «<название>», <место>» | `/feed/<id>/` | `feed.post:<id>` |
| `feed.like` | «Нравится <ФИО последнего отметившего>: «<отрывок>»»; при склейке с N > 0 — «Нравится <ФИО последнего> (и ещё N): «<отрывок>»» (N — отметившие после `since`) | запись — `/feed/<id>/`, комментарий — `/feed/<id>/#c<cid>` | запись — `feed.post:<id>`, комментарий — `feed.post:<id>:c<cid>` |

Подробности (решение контракта К26, где не сказано иное): «<ФИО>» — полное ФИО действующего (`full_name`); «<отрывок>» —
`text.snippet(…, 100)` текста записи, а у упоминания и комментария — текста комментария, если действие — комментарий;
пустой текст события — название события; «<название>» и «<место>» — `text.snippet(…, 60)` (план); «<дата, время>» — начало
события по Москве «ДД.ММ.ГГГГ ЧЧ:ММ»; «<дата, время, место>» — «ДД.ММ.ГГГГ ЧЧ:ММ, <место>» (новые значения); весь текст —
не длиннее 300 знаков (план); при превышении — 299 знаков и «…» (решение контракта К26). Время — Europe/Moscow (NFR-611). Тесты T-7128
test_text_of_each_kind_by_plan_template_with_author_and_snippet, test_event_texts_use_moscow_time_at_utc_midnight,
test_title_and_place_200_cut_to_60_snippet_100_total_at_most_300; T-7127.

### 7.3. Таблица «код вида → модуль» (порядок каталога — по `order`)

| `order` | Код | Название | Модуль |
|---|---|---|---|
| 10 | `servicedesk.new_in_queue` | Новая заявка в моей очереди | Сервис-деск |
| 20 | `servicedesk.assigned` | Мне назначили заявку | Сервис-деск |
| 30 | `servicedesk.requester_replied` | Заявитель ответил | Сервис-деск |
| 40 | `servicedesk.reply_failed` | Ответ заявителю не ушёл | Сервис-деск |
| 50 | `knowledge.comment_on_my_article` | Новый комментарий к моей статье | База знаний |
| 51 | `knowledge.my_article_changed` | Мою статью изменили | База знаний |
| 52 | `knowledge.rubric_subscription` | Статья в рубрике по подписке | База знаний |
| 60 | `lists.deadline` | Срок в записи списка | Списки |
| 70…77 | `feed.for_you` … `feed.like` | раздел 7.1 | Лента |
| 110 | `core.new_device` | Вход с нового устройства | Ядро |
| 120 | `core.password_changed` | Пароль изменён | Ядро |
| 130 | `core.second_factor_reset` | Второй фактор сброшен | Ядро |
| 200 | `notify.channel_unbound` | Канал отвязан | Уведомления |

Строки, кроме `feed.*`, — CONTRACT-006, 7.3 (факт после среза 006); строки `feed.*` — план и решение 43 (а) задач. Итого
двадцать видов шести модулей. «Мои уведомления» показывают восемь строк «Лента» каждому сотруднику; у `feed.like` ячейки
внешних каналов — без флажка (4.2). Тесты T-7128 test_my_notifications_feed_section_eight_kinds_like_without_external_cells,
test_admin_defaults_like_has_no_email_or_messenger_cells; T-7138.

## 8. Журнал (план, «Журнал»)

### 8.1. Коды, типы, ключи

| Действие | Код | `object_type`, `object_id` | Ключи `before` / `after` | Тесты |
|---|---|---|---|---|
| Модератор удалил чужую запись | `feed.post_deleted` | `feed.post`, номер записи | `before`: `author` (ФИО автора), `published_at` (время публикации) | T-7118, T-7132 test_moderator_deleting_others_post_writes_post_deleted_with_actor_author_and_published_at_without_text |
| Модератор удалил чужой комментарий | `feed.comment_deleted` | `feed.comment`, номер комментария | `before`: `author`, `created_at` (время комментария), `post` (номер записи) | T-7118, T-7132 |
| Изменён срок хранения | `feed.retention_changed` | `feed.settings`, `1` | `before`: `{"years": было}`, `after`: `{"years": стало}` | T-7116, T-7132 |
| Ночное задание удалило записи | `feed.retention_purged` | `feed.settings`, `1` | `after`: `{"posts": N}`; `actor` пусто; только при N > 0 | T-7115, T-7132 |

Ключи — только `author`, `published_at`, `created_at`, `post`, `years`, `posts` (имена `years`, `posts` — план; `author`,
`published_at`, `created_at`, `post` и `object_id` строки настройки — решение контракта К27); текста записи и комментария,
названия и места события в журнале нет. Вид значений (К27): ФИО — строка; время — строка по Москве «ДД.ММ.ГГГГ ЧЧ:ММ»;
номера и числа — целые JSON. Публикация, правка и удаление автором своего (даже если автор — модератор), комментарии,
отметки, прочтения, ответы в журнал не пишутся; права ролей пишет прежний журнал ролей ядра (`role.updated`, план).
Журнал только дописывается; роль приложения не имеет `UPDATE` и `DELETE` на таблицу журнала (тот же тест, что SPEC-006
NFR-508; решение 44 задач). Тесты T-7132.

### 8.2. Подписи (`apps/feed/audit_labels.py`)

Действия: `feed.post_deleted` — «Чужая запись ленты удалена», `feed.comment_deleted` — «Чужой комментарий ленты удалён»,
`feed.retention_changed` — «Срок хранения ленты изменён», `feed.retention_purged` — «Записи ленты удалены по сроку».
Типы объектов: `feed.post` — «запись ленты», `feed.comment` — «комментарий ленты», `feed.settings` — «настройки ленты».
Ключи (`fields`): `author` — «автор», `published_at` — «опубликовано», `created_at` — «написано», `post` — «номер записи»,
`years` — «срок хранения, лет», `posts` — «Удалено по сроку, записей» (дословно, план, сценарий 12 п. 4). Словарь
`values` пуст. Ключей `author`, `published_at`, `created_at`, `post`, `years`, `posts` в общем словаре `fields` прежних
модулей и ядра нет (факт: `apps/*/audit_labels.py`, `core/services/audit_labels.py`), слияние чужих подписей не меняет.
Слова подписей, кроме `posts`, — решение контракта К28. Тесты T-7132 test_audit_labels_cover_every_feed_action_object_type_and_written_key,
test_audit_label_of_posts_key_is_deleted_by_retention_posts_count; прежний `test_audit.py::test_audit_every_written_key_has_russian_label`
(`impact.md` У21).

## 9. Поиск (план, «Поиск»)

| Что | Требование | Тесты |
|---|---|---|
| Поставщик | `SearchProvider("feed", "Лента", 60, search, count, available)`; `available` — истина каждому вошедшему; группа после «Списков» (50) | T-7131 test_provider_key_feed_title_order_60_after_lists |
| `search(user, parsed, limit, offset) -> list[SearchRow]` | `UNION ALL` веток записей и комментариев по `LIMIT limit + offset + 1` каждая, снаружи `ORDER BY время DESC, id DESC LIMIT %s OFFSET %s`; до `limit + 1` строк; видимость — в том же SQL; запрос — `слово:*` по словам `parsed.words` с отсевом слов, у которых `numnode(to_tsquery('russian', %s)) = 0`; у `parsed.hint` — `[]`; слова — параметрами | T-7131 test_results_ordered_newest_first_across_posts_and_comments, test_provider_returns_at_most_limit_plus_one_rows, test_query_words_passed_as_parameters_not_in_sql_text, test_stop_word_query_returns_empty_without_error |
| Строка выдачи | `SearchRow(title="<ФИО>, <ДД.ММ.ГГГГ> — <начало текста>", subtitle="Запись" \| "Комментарий", url="/feed/<id>/" \| "/feed/<id>/#c<cid>")`; начало текста — `text.snippet(text, 100)` (маркер → «@ФИО»), у события — название; дата — по Москве (у записи — публикации, у комментария — его `created_at`; формат даты — решение контракта К29) | T-7131 test_row_title_name_date_snippet_and_subtitle_post_or_comment, test_row_snippet_without_markup_marker_as_at_full_name, test_word_prefix_finds_comment_with_anchor_url |
| `count(user, parsed) -> tuple[int, bool]` | две ветки по `LIMIT 301`, сумма; `(min(сумма, 300), сумма > 300)` (план; форма — запись ядра, факт) | T-7131 test_count_two_branches_limit_301_capped_at_300 |
| Векторы | раздел 5.5; маркер `@[id]` в вектор не идёт; пересчёт — в транзакции публикации, правки записи и комментария | T-7131 |
| Текст запроса | не пишется ни в базу, ни в журнал портала, ни в журнал приложения | T-7131 test_search_query_text_not_stored |
| Разметка группы | `section[data-search-group="feed"]` со счётчиком `span[data-search-count-value]` (факт `templates/search/_group.html`, `_count.html`) | T-7150 |

## 10. Маршруты, поля форм, ответы

Адреса, методы и «кто» — план («Контракты»); здесь — поля форм, параметры, форма ответа и коды. Имена маршрутов:
`app_name = "feed"`, имена — `more`, `new`, `publish`, `post`, `edit`, `delete`, `recipients`, `read`, `reads`, `answer`,
`answers`, `like`, `likes`, `comments`, `comment_edit`, `comment_delete`, `comment_like`, `comment_likes`, `upload`,
`file_delete`, `file`, `thumb`, `pick`, `settings` — решение контракта К30; тесты ходят по путям.

### 10.1. Общие правила

| Что | Требование | Тесты |
|---|---|---|
| Вход | все адреса — `@login_required`: без входа GET и POST — 302 на `/login/?next=<путь>`; без второго фактора — прежние промежуточные слои ядра | T-7104 test_anonymous_home_redirects_to_login_with_next_and_shows_no_feed, test_user_without_second_factor_home_redirects_to_factor_setup; T-7108 |
| Запрос HTMX | заголовок `HX-Request: true`; ответ — фрагмент без `<html>` | T-7107 |
| Отказ службы на POST | 200 (и на НХ) с формой или фрагментом, введённое остаётся; отказ у поля — `[data-error="<поле>"][data-code="<код>"]` рядом с полем, общий отказ — `[role=alert][data-code="<код>"]` (соглашение срезов 001–006, CONTRACT-006, 10.1); `<поле>` — имя поля формы 10.2 (`text`, `to`, `term`, `until`, `event_title`, `event_place`, `event_start`, `event_end`, `files`, `file`, `answer`, `retention_years`); коды — ключи раздела 13 (колонка «Где») | все тесты отказов |
| Успех POST | обычный POST — 302 на адрес из 10.2; НХ-POST — 200 с фрагментом из 10.2 | T-7107, T-7119 |
| 403, 404 | раздел «Правила для всех тестов», решение 18 задач; запрос «Прочитано» после срока или автором — 403 с причиной в теле (раздел 13.2) | T-7103, T-7112 |
| Номера | `<int:…>` в путях; литеральные `more/`, `new/`, `posts/`, `files/`, `pick/`, `comments/` не путаются с `<int:id>/` (план) | T-7108 test_literal_paths_not_confused_with_post_id_route |
| Время в адресе (решение контракта К31) | `before=<ISO>,<id>`, `opened=<ISO>`, `since=<ISO>` — `datetime.isoformat()` в UTC (`2026-10-30T09:15:00.123456+00:00`; в адресе `+` кодируется `%2B`); неверное значение — как отсутствующее (первая страница, `since` — время открытия) | T-7105 test_invalid_before_or_opened_returns_first_page_not_500 |
| Омоним `to` | в POST формы записи `to` — адресат (`all`, `u<id>`, `p<id>`); в GET-фильтре `/`, `/feed/more/`, `/feed/new/` и в адресе `/ws/feed/` `to` — дата конца периода (план) | T-7105, T-7107 |

### 10.2. Поля форм и ответы по адресам (решение контракта К32, где не сказано иное)

| Адрес | Поля и параметры | Успех | Отказ и прочее |
|---|---|---|---|
| `/` GET | `f` (`all` по умолчанию, `important`, `events`, `mine`, `mentions`), `author` (номер сотрудника), `from`, `to` (`ДД.ММ.ГГГГ` или `YYYY-MM-DD`, Москва, включительно) — план; форма фильтров — GET | страница: блок напоминаний, форма, фильтры, плашка, блок важных, первые 20 записей, `#feed-live` | неизвестный ключ и неверное значение отбрасываются, 200 |
| `/feed/more/` GET | `before`, `opened` и фильтр | фрагмент следующих 20 записей и кнопка «Ещё записи» с новым курсором (нет следующих — кнопки нет); при `HX-Request` — показы и `#menu-badge-feed` с `hx-swap-oob="true"` | без `HX-Request` — фрагмент без показов и без узла числа |
| `/feed/new/` GET | `since` и фильтр | фрагмент: записи после `since` (до 50) — `hx-swap-oob="afterbegin:#feed-list"`, важные непрочитанные — `afterbegin:#feed-important`, если блок показан; пустая плашка `#feed-new` с новым `since`; при `HX-Request` — показы и число | больше 50 — ссылка «показать все» перезагрузкой (`a[data-feed-reload]`) |
| `/feed/posts/` POST | `kind` (`post` по умолчанию, `important`, `event`; иное — `post`), `text`, `to` (несколько), `term` (`day`, `week`, `month`, `date`; в форме — переключатель `input[type=radio][name=term]`), `until` (дата при `term=date`; в форме — `input[type=date]`), `event_title`, `event_place`, `event_start`, `event_end` (`ДД.ММ.ГГГГ ЧЧ:ММ` или `YYYY-MM-DDTHH:MM`, Москва; в форме — `input[type=datetime-local]`; виды полей — решение контракта К42), `files` (несколько), `pdn_confirmed=1`; сервер берёт поля своего вида | НХ — 200: фрагмент новой записи (`_post.html`) для вставки наверх `#feed-list` и очищенная форма `#feed-form` с `hx-swap-oob="true"`; обычный — 302 на `/` | 200 с формой и причиной у поля; ПДн — 200 с предупреждением (12.4) |
| `/feed/<id>/` GET | — | карточка: запись, все комментарии, `#feed-live` с `ws-connect="/ws/feed/?post=<id>"` | 404 |
| `/feed/<id>/edit/` GET, POST | GET — форма с текстом с маркерами и соответствием «номер → ФИО» в `textarea[name="text"][data-mention-names]` (JSON-объект `{"<номер>": "<ФИО>"}`), сохранённые адресаты таблетками без крестика, файлы с флажком `remove` (значение — номер `FeedFile`), срок — `term=date` и `until` с сохранённой датой, поля события; POST — те же поля, что публикация, плюс `remove` (несколько); `kind` игнорируется | НХ — 200: фрагмент записи `_post.html`; обычный — 302 на `/feed/<id>/` | 200 с формой и причиной; ПДн — «Сохранить всё равно»; не автор — 403 |
| `/feed/<id>/delete/` POST | — | НХ — 200 с `<div id="feed-post-<id>" hx-swap-oob="delete"></div>`; обычный — 302 на `/` | 403 / 404 |
| `/feed/<id>/to/` GET | — | фрагмент `ul[data-feed-list="recipients"]` | 404 |
| `/feed/<id>/read/` POST | — | НХ — 200: фрагмент записи без кнопки «Прочитано»; обычный — 302 на `/` | автор или срок истёк — 403 с причиной (13.2) |
| `/feed/<id>/reads/` GET | — | фрагмент `[data-feed-list="reads"]` с частями `[data-feed-reads="read"]` (ФИО и `time[data-at]`) и `[data-feed-reads="unread"]` | прочим видящим — 403 |
| `/feed/<id>/answer/` POST | `answer` (`go`, `no`) | НХ — 200: фрагмент блока события `#feed-post-<id>-event`; обычный — 302 на `/feed/<id>/` | иное значение — 200 с прежним блоком без изменений; после начала — 200, блок без кнопок и `[role=alert][data-code="answers_closed"]`; автор — 403 |
| `/feed/<id>/answers/` GET | — | фрагмент `[data-feed-list="answers"]` с частями `[data-feed-answers="go"]`, `"no"`, `"none"` | не автор (и модератор) — 403 |
| `/feed/<id>/like/`, `/feed/comments/<cid>/like/` POST | — | НХ — 200: кнопка «Нравится» в своём состоянии (`button[data-feed-like][aria-pressed="true\|false"]`) и строка отметивших; обычный — 302 на карточку | 404 |
| `/feed/<id>/likes/`, `/feed/comments/<cid>/likes/` GET | — | фрагмент `ul[data-feed-list="likers"]` | 404 |
| `/feed/<id>/comments/` GET, POST | GET — без параметров; POST — `text`, `files` (до 3), `pdn_confirmed=1` | GET — фрагмент всех комментариев; POST НХ — 200: фрагмент нового комментария `_comment.html` (`id="c<cid>"`) и очищенное поле; обычный — 302 на `/feed/<id>/#c<cid>` | 200 с причиной и введённым текстом; ПДн — предупреждение |
| `/feed/comments/<cid>/edit/` GET, POST | `text`, `files`, `remove`, `pdn_confirmed=1` | НХ — 200: комментарий (`#c<cid>`) с «изменено»; обычный — 302 на `/feed/<id>/#c<cid>` | не автор — 403; комментарий не ленты — 404 |
| `/feed/comments/<cid>/delete/` POST | — | НХ — 200 с `<div id="c<cid>" hx-swap-oob="delete"></div>`; обычный — 302 на `/feed/<id>/` | 403 / 404 |
| `/feed/files/` POST (multipart) | `file`, `scope` (`post`, `comment`), `post` или `comment` (номер при правке), `have` (несколько — номера своих непривязанных файлов формы) | 200: таблетка `[data-feed-file="<id>"]` со скрытым `input[name="files"][value="<id>"]` и крестиком | 200 с `[data-error="file"][data-code="<код>"]` |
| `/feed/files/<id>/delete/` POST | — | 200 с пустым телом | не свой или привязанный — 404 |
| `/feed/files/<id>/`, `/feed/files/<id>/thumb/` GET | — | оригинал: картинка — `inline_image`, остальное — `download`; эскиз — свой ответ с `X-Accel-Redirect: /protected/attachments/thumbs/<имя>`; везде `X-Content-Type-Options: nosniff`, `Cache-Control: no-store` (план) | 404: невидимая запись — «Не найдено»; «проверяется» — «Файл ещё проверяется»; «карантин» — «Файл в карантине»; «чистый» без эскиза у `/thumb/` — «Не найдено» (решение 51 задач) |
| `/feed/pick/` GET | `scope` (`to`, `mention`, `author`; иное — пусто), `q` | фрагмент до 20 строк `[data-pick-value]` с `data-pick-label` (ФИО или название узла): `to` — `p<id>` и `u<id>`, `mention` — `p<id>`, `author` — `<id>`; меньше двух знаков — пустой фрагмент | — |
| `/settings/feed/` GET, POST | `retention_years`, `confirm=1` | сохранение — 302 на `/settings/feed/`; уменьшение без `confirm` — 200 со вторым шагом `[data-feed-confirm]` («Ближайшее ночное задание удалит записей: N», кнопка «Подтвердить» `button[name="confirm"][value="1"]`, скрытое `retention_years`) | вне 1–10 — 200 с `[data-error="retention_years"][data-code="retention_range"]`; без `settings.portal` — 403 на GET и POST без обращения к `feed_settings` (решение 11 задач) |

## 11. Слой каналов: сообщения, кадры, коды закрытия (план «Живые обновления», «Контракты» → «Сообщения слоя каналов»)

### 11.1. Сообщения слоя и группы

| Что | Требование | Тесты |
|---|---|---|
| Группы | `feed.u.{id}` — личная группа соединений ленты; `notify.u.{id}` — колокольчик (`live.group`) (план) | T-7124 test_connect_adds_socket_to_personal_group_feed_u_id; T-7122 |
| `feed.event` | `{"type": "feed.event", "post": int, "action": "new" \| "post" \| "delete" \| "comment" \| "comment_edit" \| "comment_delete" \| "like" \| "comment_like" \| "read" \| "answer", "owner": int, "comment": int \| None, "moderators": [int], "staff_viewers": [int], "variants": {"<роль>:<0\|1>": str}, "meta": {"kind": str, "author": int, "mentioned": [int], "published_at": ISO}}` (план); `meta` — только у `new` (у прочих ключа нет); `variants` пустой только у `new`; `comment` — номер у `comment`, `comment_edit`, `comment_delete`, `comment_like`, у прочих — `None` (значение `None` — решение контракта К33) | T-7123 test_layer_message_is_feed_event_with_post_action_owner_moderators_staff_viewers_variants, test_meta_only_in_new_message_and_variants_empty_only_in_new_message, test_comment_action_messages_carry_comment_id |
| Ключи `variants` | роль — `reader`, `author`, `moderator`; `0`/`1` — признак `link_staff`; ключей не больше шести, только классы, которые есть среди получателей (план) | T-7123 test_variant_keys_are_role_and_link_staff_pairs_at_most_six, test_variants_hold_only_classes_present_among_recipients |
| Выбор варианта | `owner == я` → `author`, иначе `moderator`, если я в `moderators`, иначе `reader`; признак — я в `staff_viewers` (план) | T-7123 |
| `action` по действию (план; соответствие — решение контракта К33) | публикация — `new`; правка записи — `post`; удаление записи — `delete`; новый комментарий — `comment`; правка комментария — `comment_edit`; удаление комментария — `comment_delete`; «Нравится» записи — `like`; «Нравится» комментария — `comment_like`; «Прочитано» — `read`; ответ на событие — `answer` | T-7122 |
| `notify.html` | `{"type": "notify.html", "html": str}` в `notify.u.{id}` — готовый фрагмент `_badge.html` (`<span id="menu-badge-feed" hx-swap-oob="true" …>`) (план) | T-7123 test_feed_count_frame_after_publish_is_notify_html_menu_badge_feed_oob_on_notify_socket; T-7126a |

### 11.2. Сообщения клиента по `/ws/feed/` (план)

| Сообщение | Требование | Тесты |
|---|---|---|
| `{"sync": {"ids": [int], "since": ISO}}` | на каждое открытие; заменяет `ids`; одним запросом набирает `pending` (видимые, под фильтр, позже `since`, кроме своих); при непустом — плашка; всегда — служебный кадр `#feed-synced` | T-7125 test_sync_replaces_ids_and_always_answers_with_feed_synced_frame, test_sync_collects_pending_in_one_query_visible_filtered_after_since_without_own |
| `{"add": [int], "since": ISO}` | номера добавляются в `ids`; `since` (необязателен) убирает из `pending` записи с временем не позже него | T-7125 test_add_appends_ids_and_its_since_drops_pending_not_later_than_it |
| Пределы | `ids` — не больше 300 (лишнее отбрасывается); сообщение больше 16 КБ — закрытие 1009; неизвестные сообщения, неверные номера и время — игнорируются без ошибки сервера | T-7125 test_client_message_over_16_kb_closes_with_1009, test_ids_over_300_are_dropped, test_unknown_messages_and_bad_ids_are_ignored_without_server_error |

### 11.3. Кадры (готовые фрагменты HTML с `hx-swap-oob`, план «Формат кадров»)

| Кадр | Разметка | Тесты |
|---|---|---|
| Часть записи | элемент с `id` `feed-post-<id>-body`, `-to`, `-likers`, `-imp`, `-event`, `-ccount` и `hx-swap-oob="true"` | T-7122, T-7123 |
| Новый комментарий | `<div hx-swap-oob="beforeend:#feed-post-<id>-comments">` с комментарием `id="c<cid>"`; в сообщении слоя — номер комментария | T-7125 test_new_comment_frame_is_beforeend_into_post_comments_and_carries_comment_id |
| Правка комментария | комментарий `id="c<cid>"` с `hx-swap-oob="outerHTML"` | T-7122 |
| Удаление | `<div id="feed-post-<id>" hx-swap-oob="delete"></div>` или `<div id="c<cid>" hx-swap-oob="delete"></div>` | T-7122 test_post_delete_sends_oob_delete_frame_to_those_who_saw_post_before_delete |
| Плашка | `<div id="feed-new" hx-swap-oob="true" data-count="<N>">` с текстом «Новых записей: N» и ссылкой `a[hx-get="/feed/new/?since=<ISO>&<фильтр>"]`; при 0 — тот же узел с классом `d-none`, без текста и ссылки (вид при 0 — решение контракта К34) | T-7125 test_banner_is_feed_new_with_new_posts_count_text_and_link_to_feed_new, test_deleting_pending_post_updates_banner_and_hides_it_at_zero |
| Служебный | `<div id="feed-synced" hx-swap-oob="true"></div>` (план) | T-7125 |
| Число «Ленты» | `#menu-badge-feed` с `hx-swap-oob="true"` (сообщение `notify.html` по `/ws/notify/`) | T-7123 |
| Запреты | в кадре нет `<form`, `csrfmiddlewaretoken`, `<script`, `style=`, `on…=`; кнопки действий — `hx-post` без формы (токен добавляет `static/js/htmx-glue.js`); значения пользователя экранированы | T-7123 test_frame_has_no_csrfmiddlewaretoken_and_no_forms, test_frame_action_buttons_are_hx_post_without_form, test_frame_escapes_script_bold_javascript_link_and_img_onerror_probe |
| Кадры только о записях из `ids` | о записях вне `ids` кадры не отправляются; карточка (`post=`) плашки не получает; своя запись в плашку не идёт | T-7125 test_frames_are_sent_only_about_posts_in_ids, test_post_card_socket_gets_no_banner, test_own_post_does_not_go_to_banner |

### 11.4. Коды закрытия

| Код | Когда | Тесты |
|---|---|---|
| 4401 | `ws_state` не `"ok"` при подключении (после `accept`) или в цикле проверки (выход, выход со всех устройств, блокировка, увольнение, бездействие, истёкший пароль) | T-7124 |
| 1009 | входящее сообщение больше 16 КБ | T-7125 |
| 1011 | ошибка слоя каналов в потребителе | T-7124 |
| 1013 | ошибка в цикле проверки сессии (`FeedConsumer` и `NotifyConsumer`) | T-7124, T-7126a |

При закрытии сервером кодами 1012 и 1006 (перезапуск, обрыв) htmx-ext-ws переподключается сам; `feed.js` по `htmx:wsClose`
только ставит `data-ws="closed"`, запасного хода для 1000/1001 нет (решение 63, ранний факт T-7006). Повторная вставка
комментария отменяется на `htmx:oobBeforeSwap` (`detail.shouldSwap = false`), только если элемент с тем же `id`, что у
вставляемого, есть на странице и не равен `detail.target` (решение 62, ранний факт T-7005).

## 12. Зацепки `data-*` для приёмки (решение контракта К35, кроме названных планом и задачами)

Правила: только `data-*`, `id` и классы, которых нет у прежних блоков; без `role="status"`, `role="alert"`,
`data-error`, `data-warning` вне сообщений об отказах форм (решение 36 задач; 10.1); без `style=` и `on…=`. Названы планом
или задачами: `data-post-id`, `data-comment-id`, `#menu-badge-feed[data-count]`, `data-menu-live-badge`,
`#feed-live[data-ws]`, `data-opened`, `#feed-new`, `#feed-synced`, `data-file-state`, `data-mention`, части
`feed-post-<id>`, `-to`, `-body`, `-files`, `-imp`, `-event`, `-likers`, `-comments`, `-ccount`, якорь `#c<id>`,
`data-reply-id`, `data-reply-name` (решение 13 задач).

### 12.1. Общие

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `[data-feed-page="<имя>"]` | корень содержимого: `home` (тело главной), `card` (карточка), `edit` (правка записи), `comment-edit` (правка комментария), `settings` (настройка срока) | T-7104, T-7140b…T-7154 |
| `time[data-at]` | время по Москве, `datetime` — ISO, текст «ДД.ММ.ГГГГ ЧЧ:ММ» (1.1, К3) | T-7135, T-7106 |
| Пометка «уволен» | ФИО уволенного — с текстом «(уволен)» и `span[data-dismissed="true"]` (прежний `{% person_name %}`, факт CONTRACT-006 11.1); в строке адресатов — «ФИО (уволен)» | T-7102b, T-7106 |
| Отказы | `[data-error="<поле>"][data-code="<код>"]`, `[role=alert][data-code="<код>"]` (10.1) | все |
| Пустые состояния | `[data-empty-state="feed"]` с текстом «Записей пока нет»; `[data-empty-state="feed-filter"]` — «По фильтру записей нет» | T-7105 |

### 12.2. Главная, меню, форма, «Кому», подсказки, фильтры

| Зацепка | Где и значение | Тесты |
|---|---|---|
| Порядок тела главной | `[data-home-notices]` (общий фрагмент), `form#feed-form[data-feed-form]`, `form#feed-filters[data-feed-filters]` (GET), `#feed-new`, `#feed-important[data-feed-important]` (блок важных; нет блока — узла нет), `ol#feed-list[data-feed-list-main]` (лента) — в этом порядке в разметке | T-7104 test_home_body_order_notices_form_filters_empty_banner_important_block_feed |
| Узел числа | `#menu-badge-feed[data-menu-live-badge][data-count]` у пункта «Лента» (3.1) | T-7104 |
| Вид записи в форме | переключатель `input[name="kind"]` (`post` отмечен по умолчанию, `important`, `event`); блоки полей `[data-kind-fields="important"]`, `[data-kind-fields="event"]` (скрываются классом по виду) | T-7107, T-7140b |
| «Кому» | таблетка `[data-to-pill="<значение>"]` со скрытым `input[name="to"][value="<значение>"]` и крестиком `button[data-action="to-remove"]`; сохранённый адресат при правке — `[data-to-pill][data-saved]` без крестика; упомянутый — `[data-to-pill="m<id>"][data-mentioned]` с текстом «<ФИО> — упомянут», без крестика и без `input[name="to"]` (план) | T-7107, T-7117, T-7145 |
| Подсказки | поле ввода `input[data-feed-picker="to\|author"]`; упоминание набирается «@» прямо в `textarea[name="text"]` (у неё `data-feed-picker="mention"`, решение контракта К41), список `[data-feed-pick-list]`, строка `[data-pick-value][data-pick-label]` (10.2) | T-7108, T-7110, T-7140a |
| Фильтры | в `form#feed-filters`: `select[name="f"]` (или радиокнопки `input[name="f"]`), `input[name="author"]` (скрытое, выбирается подсказкой `author`), `input[name="from"]`, `input[name="to"]`; выбранные значения — отмечены/заполнены | T-7105 test_filter_form_uses_get_and_shows_selected_values |
| «Ещё записи» | `a[data-feed-more]` (или кнопка) с `hx-get="/feed/more/?before=…&opened=…&<фильтр>"`, построенным из разобранных значений | T-7105 test_more_link_and_ws_connect_built_from_parsed_values_without_foreign_key |

### 12.3. Запись, блок важных, событие, комментарии, отметки, списки

| Зацепка | Где и значение | Тесты |
|---|---|---|
| Запись | `article#feed-post-<id>[data-post-id="<id>"]`; части `#feed-post-<id>-to`, `-body`, `-files`, `-imp`, `-event`, `-likers`, `-comments`, `-ccount` (план) | T-7106 test_post_parts_have_stable_ids_and_data_post_id |
| Шапка записи | автор — `[data-feed-author]` (ссылка `a[href="/staff/<id>/"]` только при `link_staff`, иначе текст); время — `time[data-at]`; «изменено» — `[data-feed-edited]` с текстом «изменено» и `time[data-at]` | T-7106 |
| Меню записи | `button[data-action="post-edit"]` (ссылка на `/feed/<id>/edit/`), `button[data-action="post-delete"]` с подтверждением «Удалить запись вместе с комментариями?» (`dialog[data-feed-confirm]`, открытый — `[open]`) | T-7106, T-7146 |
| Строка адресатов | `#feed-post-<id>-to` с элементами `[data-to-item]`; «и ещё N» — `a[data-to-more]` с `hx-get="/feed/<id>/to/"` | T-7102b |
| Важное | блок `#feed-post-<id>-imp[data-feed-imp]`: «Важное, важно до <дата>»; кнопка `button[data-action="read"]` («Прочитано»); после срока — `[data-feed-was-important]` «было важным»; счётчик `[data-feed-reads-count]` «Прочитали N» или «Прочитали N из M» (ссылка на `/feed/<id>/reads/` у автора и модератора) | T-7106, T-7112, T-7141 |
| Событие | блок `#feed-post-<id>-event[data-feed-event]`: название, начало и конец (`time[data-at]`), место; кнопки `button[data-action="answer"][value="go"]` («Пойду»), `[value="no"]` («Не смогу»); числа `[data-feed-answers-count="go"]`, `[data-feed-answers-count="no"]`; ссылка списков у автора — `a[data-feed-answers-link]` | T-7113, T-7142 |
| Комментарий | `#c<cid>[data-comment-id="<cid>"]`; автор, `time[data-at]`, «изменено» `[data-feed-edited]`; «Ответить» — `button[data-action="reply"][data-reply-id="<номер автора>"][data-reply-name="<ФИО, экранировано>"]` (решение 13 задач); меню `button[data-action="comment-edit"]`, `button[data-action="comment-delete"]` по праву; «Показать все N» — `a[data-feed-comments-all]` с `hx-get="/feed/<id>/comments/"`; число — `#feed-post-<id>-ccount` | T-7119, T-7143 |
| Поле комментария | `form[data-feed-comment-form]` с `textarea[name="text"]` | T-7119 |
| «Нравится» | `button[data-feed-like][aria-pressed]`; строка — `[data-feed-likers]` «Нравится: <ФИО>, <ФИО> и ещё N»; «и ещё N» — ссылка на полный список | T-7120, T-7144 |
| Списки | `ul[data-feed-list="likers\|reads\|answers\|recipients"]` (10.2) | T-7102b, T-7112, T-7113, T-7120 |
| Упоминание | `a[data-mention="<id>"][href="/staff/<id>/"]` или `span[data-mention="<id>"]` (план) | T-7109 |

### 12.4. Предупреждение о ПДн

| Зацепка | Где и значение | Тесты |
|---|---|---|
| Блок | `[data-feed-pdn]` в ответе формы (запись, правка, комментарий, правка комментария); найденное — `li[data-feed-pdn-item]` (экранировано) | T-7111, T-7154 |
| Кнопки | «Исправить» — `button[data-action="pdn-fix"]` (действие клиента над тем же ответом, решение 47 задач); «Опубликовать всё равно» (при правке — «Сохранить всё равно») — `button[name="pdn_confirmed"][value="1"]`; введённое — в полях формы того же ответа | T-7111 test_warning_has_fix_and_publish_anyway_with_confirm_field |

### 12.5. Соединение ленты

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `#feed-live` | `<div id="feed-live" hx-ext="ws" ws-connect="/ws/feed/?<фильтр>" data-ws="connecting" data-opened="<ISO>">` внутри тела главной (у карточки — `?post=<id>`); `data-ws`: `connecting` при отрисовке (начальное значение — решение контракта К36), `open` — после `#feed-synced`, `closed` — по `htmx:wsClose` | T-7104 test_home_has_feed_live_node_with_ws_connect_and_data_opened; T-7108 test_card_has_ws_node_with_post_query; T-7140a |
| Два соединения на `/` | ровно два узла с `ws-connect`: колокольчик (`/ws/notify/`) и `#feed-live` (`/ws/feed/`) (решение 43 (г) задач) | T-7104 test_home_has_two_ws_connect_nodes_bell_and_feed_live |

### 12.6. Файлы

| Зацепка | Где и значение | Тесты |
|---|---|---|
| Файл в записи и комментарии | `[data-feed-file="<id>"][data-file-state="pending\|clean\|quarantine"]`; «проверяется» — имя и пометка «проверяется», без ссылки; «карантин» — имя и пометка «карантин», без ссылки; «чистый» картинка с эскизом — `a[href="/feed/files/<id>/"] > img[src="/feed/files/<id>/thumb/"]`; иначе — имя, размер и ссылка «Скачать» `a[href="/feed/files/<id>/"]` | T-7130 test_display_file_state_data_attribute_for_each_state и соседние |
| Таблетка загрузки | `[data-feed-file="<id>"]` со скрытым `input[name="files"]` и крестиком `button[data-action="file-remove"]`; при правке — флажок `input[name="remove"][value="<id>"]` | T-7129, T-7149 |
| Загрузка | `input[type="file"][data-feed-upload="post\|comment"]` | T-7140a |

### 12.7. Настройка срока, поиск

| Зацепка | Где и значение | Тесты |
|---|---|---|
| Настройка | `[data-feed-page="settings"]`, заголовок «Настройки портала → Лента», поле `input[name="retention_years"]` с подписью «Хранить записи ленты, лет»; второй шаг — `[data-feed-confirm]` (10.2) | T-7116, T-7151 |
| Поиск | группа `section[data-search-group="feed"]` (9) | T-7131, T-7150 |

## 13. Тексты, которые проверяют тесты

Тексты — словарь `TEXTS` модуля `apps/feed/texts.py` (план: «одним словарём»; имя словаря — решение контракта К37, как
`lists`); ключ — код отказа (`data-code`, `FeedError.code`). Подстановки — `str.format` с именами из фигурных скобок. Тест
ищет текст в разметке подстрокой, регистр как здесь; числа с разрядами — с обычным пробелом U+0020 («10 000»). Колонка
«Где» — место отказа в разметке (10.1): имя поля (`[data-error="<поле>"]`), «общий» (`[role=alert]`) или «—» (страница
404, не отказ формы). Один тест сверяет, что `TEXTS` содержит каждый ключ и текст разделов 13.1–13.2 (решение 19 задач;
имя теста — ответ на В1 в 16.4: T-7135); тексты с подстановками сверяются после `str.format` с пробными значениями.

### 13.1. Дословно из FR-642 и плана («Тексты отказов»)

| Код | Где | Текст | Источник | Тесты |
|---|---|---|---|---|
| `empty_text` | `text` | «Напишите текст» | FR-642 | T-7107, T-7117, T-7119 |
| `too_long` | `text`, `event_title`, `event_place` | «Предел: {limit} знаков» («Предел: 10 000 знаков», «Предел: 4000 знаков», «Предел: 200 знаков»; `limit` — строкой, разрядный пробел только у 10 000) | FR-642 | T-7107, T-7113, T-7119 |
| `no_recipients` | `to` | «Выберите, кому адресована запись» | FR-642 | T-7107 |
| `recipient_invalid` | `to` | «Выберите, кому адресована запись» (несуществующий узел, недействующий человек — К18) | FR-642, К18 | T-7107, T-7117 |
| `too_many_recipients` | `to` | «Не больше 50 адресатов» | FR-642 | T-7107, T-7117 |
| `too_many_mentions` | `text` | «Не больше 20 упоминаний» | FR-642 | T-7110 |
| `event_title_required` | `event_title` | «Укажите название события» | FR-642 | T-7113 |
| `event_place_required` | `event_place` | «Укажите место события» | FR-642 | T-7113 |
| `event_end_before_start` | `event_end` | «Конец должен быть позже начала» | FR-642 | T-7113 |
| `event_start_passed` | `event_start` | «Начало уже прошло» | FR-642 | T-7113 |
| `event_started` | `event_start` | «Событие началось: время и место не меняются» | FR-642 | T-7113 |
| `term_too_far` | `term` | «Срок — не позже чем через год» | FR-642 | T-7112 |
| `date_passed` | `term` | «Дата уже прошла» | FR-642 | T-7112 |
| `answers_closed` | общий | «Ответы закрыты: событие началось» | FR-642 | T-7113 |
| `post_files_limit` | `files`, `file` | «У записи уже 10 файлов» | FR-642 | T-7129 |
| `comment_files_limit` | `files`, `file` | «У комментария уже 3 файла» | FR-642 | T-7119, T-7129 |
| `file_too_big` | `file` | «Файл больше 20 МБ» | FR-642 | T-7129 |
| `file_type` | `file` | «Файл такого типа не принимается» (исполняемый, архив с паролем, картинка больше 40 Мп — план) | FR-642 | T-7129 |
| `file_pending` | — | «Файл ещё проверяется» (страница 404) | FR-642 | T-7130 |
| `file_quarantine` | — | «Файл в карантине» (страница 404) | FR-642 | T-7130 |
| `retention_range` | `retention_years` | «Срок хранения — от 1 до 10 лет» | FR-642 | T-7116 |
| `post_all_denied` | `to` | «Писать всем вам не разрешено» | решение плана | T-7107, T-7117 |
| `only_add_recipients` | `to` | «Адресатов можно только добавить» | решение плана | T-7117 |
| `too_many_unbound` | `file` | «Слишком много файлов без записи: опубликуйте запись или уберите лишние» | решение плана | T-7129 test_31st_unbound_upload_refused_too_many_files_without_post |

### 13.2. Тексты решений задач и решения контракта, которых нет в FR-642

| Код | Где | Текст | Источник | Тесты |
|---|---|---|---|---|
| `event_time_required` | `event_start` или `event_end` (то поле, что пусто) | «Укажите начало и конец события» | решение 48 задач | T-7113 test_missing_event_start_or_end_is_refused_with_reason_at_field |
| `file_missing` | `files` | «Файл не найден» (чужой, привязанный или несуществующий номер в `files`; «убрать» с чужим номером) | решение контракта К38 (план: «тот же отказ, что у несуществующего номера», текста не даёт) | T-7129 test_bind_fewer_rows_than_sent_rolls_back_with_missing_id_refusal, test_foreign_unbound_file_id_in_files_refused_nothing_bound |
| `read_author` | — (тело 403) | «Автор не отмечает свою запись прочитанной» | решение контракта К38 (план: «403 с причиной», текста не даёт) | T-7112 test_read_by_author_is_403_with_reason_and_author_sees_no_read_button |
| `read_expired` | — (тело 403) | «Срок важного уже истёк» | решение контракта К38 | T-7112 test_read_after_term_expired_is_403_with_reason |

### 13.3. Тексты интерфейса (план и решения задач; в `TEXTS` не входят)

«Записей пока нет»; «По фильтру записей нет»; «Новых записей: N»; «Подразделение удалено»; «уволен» (в строке адресатов —
«ФИО (уволен)»); «и ещё N»; «изменено»; «было важным»; «Прочитали N»; «Прочитали N из M»; «Важное, важно до <ДД.ММ.ГГГГ>»;
«Удалить запись вместе с комментариями?»; «Ближайшее ночное задание удалит записей: N»; «Подтвердить»; «Настройки портала →
Лента»; «Хранить записи ленты, лет»; «Нравится: <ФИО>, <ФИО> и ещё N»; «Показать все N»; «Ещё записи»; «Опубликовать»;
«Исправить»; «Опубликовать всё равно»; «Сохранить всё равно»; «Прочитано»; «Пойдут», «Не смогут», «Не ответили»;
«Прочитали», «Не прочитали»; «<ФИО> — упомянут»; «Всем»; «Лента»; «Настройки ленты»; «проверяется», «карантин»,
«Скачать». Виды формы — «Сообщение», «Важное», «Событие»; сроки — «День», «Неделя», «Месяц», «До даты» (план). Кнопки
ответа — «Пойду», «Не смогу» (решение контракта К10). Время — по Москве.

## 14. Команды стенда, нагрузка, помощники приёмки

Образец — `e2e_lists_shift` (CONTRACT-006, 13.1): проверка стенда — первым действием, до любого чтения базы; вывод — одна
строка `имя: ключ=значение …`.

### 14.1. `e2e_feed_shift --minutes N` (план; решения 10, 54 задач)

| Что | Требование | Тесты |
|---|---|---|
| Модуль | `apps/feed/management/commands/e2e_feed_shift.py` | T-7134 |
| Стенд | `require_stand()` из `apps.feed.stand` — первой строкой `handle`; без `E2E_STAND=1` — `CommandError(REFUSAL)`, ничего не изменено | T-7134 test_e2e_feed_shift_refuses_without_e2e_stand_flag |
| `--minutes` | обязателен, целое 1…10 080 (решение 10 задач); вне пределов — `CommandError("Число вне пределов от 1 до 10080: N")`, ничего не изменено (форма текста — как у `e2e_lists_shift`, факт; решение контракта К40); не число — ошибка разбора argparse | T-7134 test_e2e_feed_shift_accepts_1_and_10080_minutes, test_e2e_feed_shift_rejects_0_and_10081_minutes_without_changes |
| Сдвиг | `event_start`, `event_end`, `remind_at`, `reminded_for_start` всех событий и `important_until` всех важных записей — на N минут раньше прямой записью (`update(F(…) − delta)`) без `save()` (план; `important_until` — решение 54 задач) | T-7134 test_e2e_feed_shift_moves_start_end_remind_at_and_reminded_for_start_of_all_events_back_without_save, test_e2e_feed_shift_moves_important_until_of_important_posts_back |
| Напоминания | затем `reminders.run(timezone.now())` в процессе команды (не через очередь) | T-7134 test_e2e_feed_shift_runs_reminders_job_in_process_after_shift |
| Вывод | одна строка `feed_shift: shifted=<число сдвинутых событий> reminded=<RunResult.reminded> important=<число сдвинутых важных записей>` (решение 54 задач; строка плана без `important` устарела) | T-7134 test_e2e_feed_shift_prints_single_line_with_shifted_reminded_and_important; T-7140a |

### 14.2. `e2e_feed_retention --age-days N [--posts <номера через запятую>]` (план; решения 10, 54 задач)

| Что | Требование | Тесты |
|---|---|---|
| Модуль, стенд | `apps/feed/management/commands/e2e_feed_retention.py`; `require_stand()` первой строкой | T-7134 test_e2e_feed_retention_refuses_without_e2e_stand_flag |
| `--age-days` | обязателен, целое 1…4000 (решение 10 задач); вне пределов — `CommandError("Число вне пределов от 1 до 4000: N")`, ничего не изменено (К40) | T-7134 test_e2e_feed_retention_accepts_1_and_4000_days, test_e2e_feed_retention_rejects_0_and_4001_days_without_changes |
| `--posts` | необязателен: номера записей через запятую без пробелов (`12,15`); стареют только они; без ключа — все записи стенда (решение 54 задач); неверный список (не целые) — `CommandError("Неверный список записей: <значение>")`, ничего не изменено (текст — К40) | T-7134 test_e2e_feed_retention_posts_key_ages_only_listed_posts |
| Сдвиг | `published_at` выбранных записей и копия `Recipient.published_at` — на N дней в прошлое прямой записью (план) | T-7134 test_e2e_feed_retention_ages_published_at_of_posts_and_recipient_copies |
| Задание и вывод | затем `retention.run(timezone.now())` в процессе команды; одна строка `feed_retention: aged=<число состаренных записей> deleted=<число удалённых>` (план) | T-7134 test_e2e_feed_retention_runs_night_job_in_process_and_prints_single_line_with_aged_and_deleted; T-7140a |

### 14.3. Нагрузка (план, «Нагрузка»)

| Что | Требование | Тесты |
|---|---|---|
| `fill_feed.py` | `backend/tests/load/fill_feed.py`; без `E2E_STAND=1` — `sys.exit("Скрипт работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено.")` до импорта моделей (текст — как у `fill_lists.py`, CONTRACT-006 13.2); `LOAD_POSTS=50000`, `LOAD_COMMENTS=200000`; добор до цели; строка итога `fill_feed: posts=<число> comments=<число> likes=<число>`; запуск через `standtools … shell` | T-7135 test_load_suite_has_fill_feed_script_requiring_stand_flag_and_feed_user_class |
| `FeedUser` | класс в `backend/tests/load/locustfile.py` (два соединения: `/ws/notify/` и `/ws/feed/`; событие `WS feed frame`); тест проверяет наличие по тексту файла | то же |

### 14.4. Помощники приёмки `tests/e2e/helpers_feed.py` (пишет T-7140a; решение 8 задач)

Имена — одни для T-7140b…T-7154. Названные строкой T-7140a и решениями 8, 54, 55 задач — `open_feed`, `open_card`,
`publish`, `try_publish`, `shift`, `age`, `block_ws`; прочие имена и сигнатуры — решения контракта К39 и К43 (имена, добавленные T-7140a). Прежние помощники —
`helpers.py` (`Account`, `sign_in`, `make_employee`, `no_horizontal_scroll`, `audit_actions`), `helpers_org.py`
(`create_unit`), `helpers_sd.py` (`_stand_command`, `reset_stand_and_relogin`), `helpers_notify.py` (`tick`, `open_tab`,
колокольчик, `fakebots`), `helpers_lists.py` (образец ролей).

| Имя | Сигнатура и поведение |
|---|---|
| `FeedCast` | `NamedTuple(writer, moderator, plain, it_unit, net_unit, accounting_unit, it_member, net_member, part_timer, accountant, petrov, sidorov)`: учётки `helpers.Account` — `writer` (роль с «Писать всем»), `moderator` (роль с «Модерировать ленту»), `plain` (сотрудник без прав ленты), сотрудники узлов; `it_unit` «Отдел ИТ», `net_unit` «Группа сети» (вложена в «Отдел ИТ»), `accounting_unit` «Бухгалтерия» — номера узлов строкой; `part_timer` — основная работа в «Бухгалтерии», совместительство в «Группе сети»; `petrov`, `sidorov` — сотрудники «Бухгалтерии» |
| `feed_cast(admin_page, mailpit, new_context) -> FeedCast` | создаёт роли, узлы и учётки через интерфейс (`helpers.make_employee`, `helpers_org.create_unit`); имена — уникальные на круг |
| `open_feed(context, account, live=True) -> Page` | вход и `/`; при `live=True` ждёт `#feed-live[data-ws="open"]`, при `live=False` — только загрузки страницы (после `block_ws`) |
| `open_card(context, account, post_id) -> Page` | вход и `/feed/<id>/`, ждёт `#feed-live[data-ws="open"]` |
| `publish(page, text="", *, kind="post", to=(), term=None, until=None, event=None, files=(), mentions=()) -> int` | заполняет форму (вид, текст, «Кому» через подсказку — элементы `to`: `"all"`, `("unit", <название>)`, `("person", <ФИО>)`; срок; поля события — словарь `title`, `place`, `start`, `end`; файлы — пути; упоминания — ФИО через «@»), нажимает «Опубликовать», ждёт новую запись и возвращает её `data-post-id` |
| `try_publish(page, text="", **same) -> list[tuple[str, str]]` | то же без ожидания записи; возвращает пары `(поле или "", data-code)` отказов в ответе |
| `publish_request(page, **fields) -> int` | публикация POST-запросом той же формы (`page.request` с токеном CSRF страницы) для объёмов (45 записей, 120 непрочитанных); поля — раздел 10.2 |
| `pick_to(page, query, label)`, `pick_mention(page, field, query, label)`, `pick_author(page, query, label)` | ввод в подсказку и выбор строки `[data-pick-label="<label>"]` |
| `add_comment(page, post_id, text, *, files=()) -> int`, `like(page, post_id)`, `like_comment(page, comment_id)`, `mark_read(page, post_id)`, `answer(page, post_id, value)` | действия кнопками записи; `add_comment` возвращает `data-comment-id` |
| `badge(page) -> int`, `wait_badge(page, value, timeout=4_000)` | число `#menu-badge-feed[data-count]`; ожидание значения (`expect(...).to_have_attribute("data-count", str(value), timeout=…)`) |
| `wait_banner(page, count, timeout=4_000)` | ожидание `#feed-new[data-count="<count>"]` с текстом «Новых записей: N» |
| `post_ids(page) -> list[int]`, `important_ids(page) -> list[int]` | номера записей ленты (`#feed-list [data-post-id]`) и блока важных (`#feed-important [data-post-id]`) по порядку |
| `upload(page, path, *, scope="post") -> int`, `wait_clean(page, file_id, timeout=60_000)`, `eicar_file(tmp_path) -> Path` | загрузка файла формы; ожидание `[data-file-state="clean"]` после обновления страницы; EICAR из частей |
| `shift(minutes) -> dict` | `helpers_sd._stand_command("e2e_feed_shift", "--minutes", N)`; разбор строки 14.1 → `{"shifted": …, "reminded": …, "important": …}` |
| `age(days, posts=None) -> dict` | `e2e_feed_retention --age-days N [--posts 1,2]`; разбор строки 14.2 → `{"aged": …, "deleted": …}` |
| `block_ws(context)` | `context.route_web_socket` (Playwright 1.63) для `/ws/feed/` и `/ws/notify/`: соединение закрывается (решение 55 задач) |
| `check_360(page)` | ширина окна 360 px и `helpers.no_horizontal_scroll(page)` истинно |

Сброс стенда перед кругом — `helpers_sd.reset_stand_and_relogin()` (CONTRACT-003, 8.3); письма — Mailpit
(`helpers.wait_mail`, `no_mail`), письма через 15 минут — `helpers_notify.tick` (решение 14 задач), Telegram — учебная служба
`fakebots`.

## 15. Что меняется в прежних контрактах (для T-7138)

Сами `CONTRACT.md`, `CONTRACT-002.md` … `CONTRACT-006.md` не правятся (решение 4 задач; план). Здесь — какие их строки
устаревают со срезом 007 и чем заменяются. Номера строк — по деревьям на 2026-10-30 (после среза 006); «Было» —
сокращённый текст строки. Точные правки тестов — `crm-work/slice007/tasks/impact.md` и строка T-7138.

### 15.1. `CONTRACT-006.md`

| Строка | Было | Стало |
|---|---|---|
| 82 | хвост `INSTALLED_APPS`: … `"apps.lists"`, `"apps.search"` | … `"apps.lists"`, `"apps.search"`, `"apps.feed"` (1.1) |
| 95 | `lists_reminders` — восемнадцатая запись `register(...)` | `feed_reminders` и `feed_retention` — девятнадцатая и двадцатая (1.2) |
| 97 | `location` с `55m` — четыре шаблона | прежние четыре с `55m` и один `^/feed/files/$` с `25m` (1.2) |
| 108–110, 120 | функция `lists` в `stand_reset` — последняя и вызывается первой | последняя — `apps.feed.stand.stand_reset`, перед ней `lists`, затем `knowledge` (1.3) |
| 130–137 | числа среза 006: семнадцать точек, двенадцать видов, шестнадцать прав, восемнадцать заданий cron, двенадцать пунктов меню администратора, `location` 55m, тринадцать полей `NotificationKind`, `apps.lists` перед `apps.search` | числа среза 007 (1.4) |
| 152 | `NotificationKind.external_text_of` — последнее, тринадцатое поле | `external_text_of` — тринадцатое; `channels` — четырнадцатое, `coalesce_text` — пятнадцатое, последнее (2.1) |
| 551–570 | таблица «код вида → модуль»: двенадцать видов | двадцать видов шести модулей (7.3) |
| 447 (5.9) | `PERMISSIONS_006` — последний кортеж прав | плюс `support_feed.PERMISSIONS_007` (5.9) |

### 15.2. `CONTRACT-005.md`, `CONTRACT-004.md`, `CONTRACT-002.md`, `CONTRACT.md`

| Файл и строка | Было | Стало |
|---|---|---|
| `CONTRACT-005.md` 204 | полный `POINTS` — кортеж из 17 имён, последние `search_providers`, `ticket_card_parts` | восемнадцать имён, `home_body` — последней; прежние семнадцать — в прежнем порядке (3.1) |
| `CONTRACT-005.md` 959–961 | числа среза 005 | числа среза 007 (1.4) |
| `CONTRACT-004.md` 132 | `CHANNEL_LAYERS` — словарь с одним ключом `default` | два ключа: `default` прежний и `publish` (1.2) |
| `CONTRACT-004.md` (разделы о `NotifyConsumer` и `live.push`) | цикл проверки сессии внутри `NotifyConsumer`; ошибка цикла — молчаливая остановка; `live.push` — слой `default` | проверка — общая примесь `core.ws.SessionGuardMixin` (3.2); ошибка цикла — закрытие 1013; обработчик `notify_html`; `live.push` — слой `publish` (4.2) |
| `CONTRACT-004.md` 1007 | `WsHub.connect` собирает `scope` с `query_string=b""` | без изменений; соединения `/ws/feed/` со строкой запроса — свой помощник `support_feed.ws_client` (5.9) |
| `CONTRACT-002.md` 127 | элемент `permissions.menu_for` — `url`, `title`, `icon`, `order` и `badge` (если есть) | плюс `live_badge`, если пункт его объявил; «Главная» не добавляется, если есть пункт с `url="/"` (3.1) |
| `CONTRACT.md` 103 | меню: ссылки ядра видны по праву | без изменений для адресов ядра; первый пункт — «Лента» (`/`) вместо «Главной», если модуль установлен |

### 15.3. Перечень правок прежних тестов T-7138 (по строке T-7138 и `impact.md`; строки — по коммиту e7ca1db, при сдвиге искать по утверждению)

| № | Тест (файл:строка) | Было | Стало |
|---|---|---|---|
| 1 | `tests/test_extensions.py:74-75, 103` (докстринг 69) | `POINTS + POINTS_003 + POINTS_004 + POINTS_005`, «семнадцать» | `+ POINTS_007`, «восемнадцать» |
| 2 | `tests/test_kb_boundaries.py:23, 357-359` | `POINTS_17`, `len == 17` | `POINTS_18 = POINTS_17 + ("home_body",)`, 18 |
| 3 | `tests/test_kb_boundaries.py:369` | `POINTS[-2:] == ("search_providers", "ticket_card_parts")` | `POINTS[-3:-1]` — точки среза 005, `POINTS[-1] == "home_body"` |
| 4 | `tests/test_lists_boundaries.py:24, 258-260` | как п. 2 | как п. 2 |
| 5 | `tests/test_sd_boundaries.py:434` | `tuple(POINTS) == POINTS_17` | `== POINTS_17 + ("home_body",)`; срезы `[:9]`, `[9:15]` (`:439-445`) остаются |
| 6 | `tests/test_lists_reminders_2.py:405` | 13 полей, последние `coalesce`, `external_text_of` | `len == 15`, `names[11:13] == ["coalesce", "external_text_of"]`, `names[-2:] == ["channels", "coalesce_text"]` |
| 7 | `tests/test_notify_catalog.py:148-149, 160` | список 13 полей; `bare.external_text_of is None` | `+ ["channels", "coalesce_text"]`; `bare.channels is None`, `bare.coalesce_text is None` (план этого теста не называет) |
| 8 | `tests/test_kb_deploy.py:118` | `INSTALLED_APPS[-4:]` кончается `apps.search` | `[-5:] == APPS_TAIL[1:]` (`apps.feed` последним) |
| 9–10 | `tests/test_notify_deploy.py:357`, `tests/test_lists_deploy.py:126-127` | `[-5:]` кончается `apps.search` | `[-6:] == APPS_TAIL` |
| 11 | `tests/test_kb_deploy.py:585-586` | `apps.lists.stand` — `len - 1`, `apps.knowledge.stand` — `len - 2` | `apps.feed.stand` — `len - 1`, `apps.lists.stand` — `len - 2`, `apps.knowledge.stand` — `len - 3` |
| 12 | `tests/test_lists_stand.py:360, 361, 364` | `registered[-1] is stand_reset` (lists), `names[-2] == "apps.knowledge.stand"`, `call_order[0] == "apps.lists.stand"` | `registered[-2]`, `names[-1] == "apps.feed.stand"`, `names[-3] == "apps.knowledge.stand"`, `call_order[0] == "apps.feed.stand"`, `call_order[1] == "apps.lists.stand"` |
| 13–16 | `tests/test_notify_deploy.py:321-322`, `tests/test_kb_deploy.py:129-130`, `tests/test_sd_deploy.py:414`, `tests/test_lists_deploy.py:166` | 18 вызовов `register` | 20; в `test_sd_deploy.py` задания среза 007 — отдельным циклом по `FEED_JOBS`, не в цикле «имя = функция» (400–406) |
| 17 | `tests/test_deploy_files.py:359-371` | четыре шаблона `55m`, вне них `["6m"]` | плюс отдельная вычитка `location ~ ^/feed/files/$` с `["25m"]` (не в цикле `55m`) |
| 18 | `tests/test_notify_deploy.py:384-389` | `CHANNEL_LAYERS == {"default": …}` | `set(CHANNEL_LAYERS) == {"default", "publish"}`, `default` прежний, `publish` — 1.2 |
| 19 | `tests/test_notify_ws.py:638-647` | фабрики слоя без аргументов | `def broken_layer(*args)`, `BrokenLayer.__init__(self, *args)`; проверка, что `push` зовёт фабрику с `"publish"` (тест не падает, но иначе проверял бы `TypeError`) |
| 20 | `tests/test_permissions.py:35-37` | админ — `PERMISSIONS…PERMISSIONS_006`; «Руководитель» `{"staff.view"}`; «Сотрудник ИТ» `{"staff.view", "knowledge.edit"}` | `+ PERMISSIONS_007`; `{"staff.view", "feed.post_all"}`; `{"staff.view", "knowledge.edit", "feed.post_all"}` |
| 21 | `tests/test_sd_access.py:538-541` | 16 прав | `+ PERMISSIONS_007`, 18 |
| 22 | `tests/test_org_permissions.py:137-151` | перечень, названия, держатели до `PERMISSIONS_006` | `+ PERMISSIONS_007`, `TITLES_007`; `feed.post_all` у трёх встроенных ролей, `feed.moderate` — `[ADMIN_ROLE]` |
| 23 | `tests/test_lists_seed.py:173-175` | 15, затем 16 | 17, затем 18 |
| 24 | `tests/test_org_permissions.py:682-691` | двенадцать пунктов, `items[0]` — «Заявки» с `badge` | четырнадцать: `["/", "/tickets/", "/kb/", "/lists/", "/staff/", "/structure/", "/calendar/", "/roles/", "/audit/", "/settings/portal/", "/settings/notifications/", "/settings/feed/", "/servicedesk/", "/settings/security/"]`, порядки `[0, 5, 7, 8, 10, 20, 30, 40, 50, 60, 62, 63, 65, 70]`; `items[0]` — ключи `url, title, icon, order, badge, live_badge`, `live_badge == "feed"`; `items[1]` — «Заявки» с `badge`; `items[2:]` — четыре ключа |
| 25 | `tests/test_lists_access.py:863` | `len(titles) == 12` | 14 |
| 26 | `tests/test_sd_boundaries.py:680-685` | второй вызов возвращает регистрации всех модулей, кроме `servicedesk` | не возвращать и регистрации `apps.feed` (тест о «срезе 002»; проверка ключей 636 не ослабляется — решение 43 (д) задач) |
| 27 | `tests/test_notify_catalog.py:3, 22-53, 106-116` | `TABLE` — двенадцать видов, модули без «Лента» | `TABLE` + восемь строк `FEED_KINDS` после `lists.deadline`; модуль «Лента», `count("Лента") == 8`; сверка `kind.channels` и `coalesce` |
| 28–29 | `tests/test_notify_catalog_2.py:228, 235-236, 304-305` | строки видов без ленты | `+ FEED_CODES`; `TITLES` `+ FEED_TITLES` |
| 30 | `tests/test_notify_catalog_2.py:332` | `set(matrix) == SD_CODES \| {RUBRIC, LISTS_KIND}` | `\| set(FEED_CODES)`: семь видов `FEED_BOXED` и `feed.like: []` (решение 43 (б) задач) |
| 31–32 | `tests/test_notify_catalog_2.py:477, 493-495` | строки и модуль без ленты | `+ FEED_CODES`; модуль «Лента» для `feed.*` |
| 33 | `tests/test_notify_catalog_2.py:510` | `["push"] * 6` | `["push"] * 13` (шесть прежних и семь `FEED_BOXED`; у `feed.like` флажка нет) |
| 34 | `tests/test_notify_catalog_2.py:518-533` | у каждой строки — подсказка привязки и флажок `telegram` после привязки | циклы — по строкам кроме `FEED_LIKE`; у `feed.like` в ячейках `telegram`, `max` нет `input`, `data-available="0"` (решение 43 (в) задач; план этого теста не называет) |
| 35 | `tests/test_notify_catalog_2.py:552, 556` | шесть ячеек `push`; у каждой — флажок | ячеек `push` — 14 (у каждой строки, в том числе `feed.like`), флажков — 13: цикл проверки флажка — без `FEED_LIKE` (строка T-7138 называет это «14 флажков» — уточнение: 14 ячеек, 13 флажков, `impact.md` «Находки» п. 4) |
| 36–38 | `tests/test_notify_prefs.py:208-214, 239-241, 499-501` | строки, названия, модуль, `matrix` без ленты | `+ FEED_CODES`, `FEED_TITLES`, «Лента»; `matrix` `+ {c: ["email"] for c in FEED_BOXED}` и `FEED_LIKE: []` |
| 39 | `tests/test_kb_boundaries.py:277` (строка T-7138 — `:278`, план — `:272-274`) | `len(rest) == 9` | 17 (или блок под `without_feed()` — тогда 9) |
| 40–41 | `tests/test_search_providers_2.py:306, 309, 328-329` | списки ключей без `feed` | `+ "feed"` последним (и под `without_knowledge()`) |
| 42 | `tests/test_kb_boundaries.py:482-483` | ключи и названия поставщиков — четыре | `+ ["feed"]`, `+ ["Лента"]` |
| 43 | `tests/test_notify_pages.py:219` | на `/` единственный `ws-connect` — колокольчик | колокольчик открывается на `/me/` (решение 43 (г) задач); два `ws-connect` на `/` проверяет T-7104 |
| 44 | `tests/e2e/test_e04_my_settings.py:36-56, 277, 279, 283, 352, 585` | `ROWS = KINDS + KB_KINDS + LISTS_KINDS` | `+ FEED_KINDS_E2E` (восемь пар «код, название»; локальная константа файла, строится из `support_feed.FEED_KINDS`, в `support_feed` не входит), модуль «Лента» для `feed.*` |
| 45 | `tests/e2e/test_e12_criteria.py:57-71, 925, 937, 940-941, 946-947` | `EXPECTED_CATALOG` — двенадцать видов | двадцать: восемь видов ленты (у `feed.like` внешний текст `""`), счётчики строк `+ len(FEED_KINDS_E2E)`, модуль «Лента» |

Условные пункты (строка T-7138, `impact.md` «Условно» У1–У21) заранее не правятся и проверяются после реализации; У1
(`test_notify_admin.py:368-377`) и У2 (`tests/e2e/test_e08_admin.py:376-386`) почти наверняка падают — разметка ячеек по
решению 43 (в) задач (4.2). Не правятся (`impact.md` «Не ломается»): `test_sd_boundaries.py:589` (строка плана неверна: тест
идёт под `no_extensions`), `test_kb_boundaries.py:325`, `:383-393`, `test_kb_comments.py:250`, `test_sd_list_2.py:547`,
`test_sd_boundaries.py:122-124`, `test_notify_deploy.py:359-375`, `test_notify_boundaries.py:128`,
`test_core_uploads.py:436-448`; `tools/` не правятся. Правило: каждая правка — только с разрешения владельца, по одному
тесту, с диффом; разрешение спрашивает Opus (решение 31 задач).

## 16. Вопросы и решения

Решения контракта — выбор автора контракта (исполнитель T-7100), ничьим решением владельца не являются; Opus
подтверждает их или меняет при проверке контракта до T-7101 (решение 2 задач). Вопросы к Opus — 16.4; маркеров
неизвестного в контракте нет: где план и решения оставили выбор, стоит решение контракта с причиной.

### 16.1. Принятые чужие решения (не решения контракта)

| № | Что | Чьё |
|---|---|---|
| П1 | `order` видов 70…77 по строкам таблицы плана, у `feed.like` `external_text=""` и `channels=("portal",)`; снимок `matrix` с `feed.like: []`; ячейка вне `channels` — `td[data-channel]` без флажка с `data-available="0"`; колокольчик в прежнем тесте — на `/me/`; второй вызов `test_sd_boundaries.py` без регистраций `apps.feed` | решение 43 (а)–(д) задач (предложения `impact.md`, утверждённые Opus; приняты подписью TASKS-007) |
| П2 | перечень публичных функций, которые зовёт `feed` (4.3), полное имя `core.services.uploads` | решение 46 задач |
| П3 | `mentions.sync(...)` возвращает впервые упомянутые номера; «Исправить» — действие клиента | решение 47 задач |
| П4 | текст «Укажите начало и конец события» | решение 48 задач (показать владельцу при подписи — сделано подписью TASKS-007) |
| П5 | точки подмены: `dispatch.create` из `reminders` и `posts`, логгер `apps.feed.tasks`, `CHECK_INTERVAL`, `ws_state` в цикле, ошибка слоя, тестовый потребитель на примеси; снятие права модератора — `roles.update_role` | решение 49 задач |
| П6 | N журнала ночного задания — действительно удалённые; эскиз «чистого» без эскиза — 404; прямой тест `notify_rules.decide` | решения 50, 51 задач |
| П7 | `reload_asgi_without_feed()`, разбор `ast` для адресов и cron | решение 52 задач |
| П8 | `stand_reset` ленты стирает `core.Comment` с `feed.post:` | решение 53 задач |
| П9 | ключ `--posts`, сдвиг `important_until`, строка `feed_shift: … important=<K>`; границы 1…10 080 и 1…4000 | решения 54 и 10 задач |
| П10 | `block_ws(context)` на `BrowserContext.route_web_socket` | решение 55 задач |
| П11 | время в SQL — параметром из `timezone.now()`; `remind_events(now=None)`, `retention_night(now=None)` | решение 59 задач |
| П12 | индекс `Shown(post_id)` вопреки строке плана | решение 60 (ответ владельца 2026-10-30 «Добавить индекс») |
| П13 | `unread.counts` — как в плане | решение 61 (ответ владельца 2026-10-30 «Как в плане») |
| П14 | условие отмены повторной вставки на `htmx:oobBeforeSwap` | решение 62 (решение Opus по раннему факту T-7005) |
| П15 | по `htmx:wsClose` только `data-ws="closed"`, без запасного хода для 1000/1001 | решение 63 (решение Opus по раннему факту T-7006) |
| П16 | 403 у `/settings/feed/` без `settings.portal` без обращения к службе; зацепки «Ответить» `data-reply-id`, `data-reply-name` | решения 11, 13 задач |

### 16.2. Решения контракта

| № | Решение | Причина |
|---|---|---|
| К1 | `FeedConfig.verbose_name = "Живая лента"` (значение каркаса T-7001; тестом не проверяется) | как `"База знаний"`, `"Списки"` у прежних приложений |
| К2 | модуль `services/errors.py` с `FeedError(code, field, params)` и `PdnFound(found)` | одно соответствие «отказ службы → текст → разметка»; предупреждение о ПДн — не отказ, поэтому отдельный тип |
| К3 | время на страницах — `time[data-at]`, «ДД.ММ.ГГГГ ЧЧ:ММ» | тот же вид, что в срезе 006: приёмка и серверные тесты читают время одинаково |
| К4 | `routing.py` — `re_path(r"^ws/feed/$", FeedConsumer.as_asgi())` | как `notify/routing.py`; строку запроса разбирает потребитель |
| К5 | имя файла эскиза — идентификатор `StoredFile` (UUID) | план называет «`<id файла>`»; номер `StoredFile` уникален и не зависит от строки `FeedFile` |
| К6 | порядок `register_all()` — порядок таблицы плана, `stand_reset` последней; функция поставщика — `services.search.search_providers` | как у `lists`; `stand_reset` последней нужна для порядка сброса |
| К7 | порядок стирания таблиц в `stand_reset` | сначала зависимые строки, чтобы `PROTECT` (`FeedFile.file`) не мешал |
| К8 | имена ограничений `feed_<модель>_<поля>_<вид>` | образец CONTRACT-005/006 |
| К9 | тесты не пользуются обратными именами связей | план обратных имён не задаёт; менеджеры моделей не зависят от выбора исполнителя |
| К10 | типы и умолчания полей, подписи вариантов (`Сообщение`, `Важное`, `Событие`, `Подразделение`, `Сотрудник`, `Кому`, `Упоминание`, `Пойду`, `Не смогу`) | план даёт значения и названия видов формы, но не подписи вариантов и не умолчания |
| К11 | обратный ход миграции `0002` — `RunPython.noop` | план обратного хода не задаёт |
| К12 | текст узла числа при 0 — «0» (узел скрыт) | план задаёт только скрытие и «99+» |
| К13 | имена методов `SessionGuardMixin` и констант кодов закрытия | план описывает поведение примеси, без имён; тестовому потребителю (решение 49) нужны имена |
| К14 | `subtree_member_ids` на несуществующих номерах — пусто; `unit_chains` отдаёт ключ на каждый номер | тесты сверки и `unread.counts` не должны зависеть от пропущенных ключей |
| К15 | `notify_kinds.still_relevant(user_id, object_ref)` | у вида нужна функция поля `still_relevant`; имя — по полю записи ядра |
| К16 | в перечень 4.3 добавлены записи и модели ядра, `events.publish`, `moscow_today` | решение 46 перечисляет службы; без записей ядра модуль не регистрируется, без моделей нет связей |
| К17 | сигнатуры служб 5.2–5.5 (в том числе `Viewer.link_staff`, `can_edit_comment`, `can_delete_comment`, `recipients.full`, третий аргумент `snippet`) | план называет имена функций; тестам нужны аргументы и возвращаемые значения |
| К18 | несуществующий узел и недействующий человек в «Кому» — код `recipient_invalid` с текстом «Выберите, кому адресована запись» | FR-642 и план отдельного текста не дают; текст поля «Кому» из FR-642 подходит по смыслу |
| К19 | `u<id>` — узел, `p<id>` — человек | план пишет `to=u<id>`, `to=p<id>` без расшифровки; `u` — unit (как `Recipient.kind="unit"`), `p` — person (вопрос В2) |
| К20 | поля `notify_rules.RuleEvent` | решение 51 требует закрепить вход `decide` |
| К21 | `layer_down(delay=0.0)`: слой падает сразу | вопрос В4: при задержке 2 с на каждый вызов последовательные рассылка и `live.push` превысили бы 3 с, а наблюдение NFR-614 на стенде идёт закрытым портом (решение 40) |
| К22 | ошибка слоя в потребителе — подмена `RedisChannelLayer.group_add` | потребитель сам зовёт этот метод при подключении; подмена не требует нового кода ради теста |
| К23 | логгеры `apps.feed.services.live` и `apps.feed.services.files` | по модулю, как `apps.feed.tasks` решения 49 |
| К24 | помощники сверх строки T-7101: `FEED_CHANNELS`, `FEED_COALESCE` (`FEED_KINDS` — ровно 8-кортежи `TABLE`), кортеж держателей `HOLDERS_007`, параметр `hub` у `ws_client`, `as_writer`, `as_plain`, `send_sync`, `send_add`, `queries_with_params`, ключи `images()`, `post_part`, `delete_post_between_check_and_insert`, `mark_created_between_check_and_insert`, `moscow`, `moscow_text`, `HOLDERS_007`, `KIND_FIELDS_007`, `MENU_FEED`, `MENU_FEED_SETTINGS`, `FEED_SEARCH` | строка T-7101 называет подмены и роли словами; константы — из `impact.md` «Общее»; без имён параллельные писатели разойдутся |
| К25 | функции склейки `comment_coalesce_text`, `like_coalesce_text` | поле `coalesce_text` — функция (план); имя нужно тесту каталога |
| К26 | подробности текстов уведомлений (ФИО, источник отрывка, формат даты и места) | план даёт шаблоны, но не форму подстановок |
| К27 | ключи журнала `author`, `published_at`, `created_at`, `post`; время — строка по Москве; `object_id` настройки — `1` | план называет состав «автор, время, номер записи»; строка по Москве читается в журнале без перевода |
| К28 | слова подписей журнала, кроме `posts` | план даёт только подпись `posts` |
| К29 | дата в строке поиска — «ДД.ММ.ГГГГ» по Москве | план пишет «<дата>» |
| К30 | имена маршрутов `app_name="feed"` | тесты ходят по путям; имена нужны шаблонам Этапа 3 |
| К31 | время в адресе — `isoformat()` в UTC; неверное — как отсутствующее | план пишет «ISO» без формы |
| К32 | поля форм и ответы 10.2 (`term`, `until`, поля события, `remove`, `confirm`, `post`/`comment` загрузки, ответы НХ и обычных запросов) | план называет поля словами («поля срока важного и события», «убрать», «подтверждение») |
| К33 | `comment: None` у действий без комментария; соответствие «действие → `action`» | план даёт перечень `action`, но не соответствие и не значение у прочих |
| К34 | плашка при 0 — узел с `d-none` | план: «скрыть при 0» |
| К35 | зацепки раздела 12, кроме названных планом и задачами | приёмке нужны устойчивые локаторы |
| К36 | начальное `data-ws="connecting"` | план задаёт `open` и `closed`; приёмка ждёт смены значения |
| К37 | словарь `TEXTS` | как `lists`; тест словаря (решение 19) сверяет ключи |
| К38 | тексты `file_missing` «Файл не найден», `read_author` «Автор не отмечает свою запись прочитанной», `read_expired` «Срок важного уже истёк» | план требует отказ и «403 с причиной», текста не даёт (вопрос В3) |
| К39 | имена и сигнатуры `helpers_feed.py`, кроме названных строкой T-7140a | решение 8: имена приёмки закрепляет контракт |
| К40 | тексты отказов команд стенда («Число вне пределов от 1 до N: …», «Неверный список записей: …») | форма — как у `e2e_lists_shift` (факт) |
| К41 | упоминание «@» набирается в поле текста (`textarea[data-feed-picker="mention"]`), отдельного поля нет | план («Текст и упоминания»): «@» в тексте записи или комментария; ответ Opus на вопрос T-7140a |
| К42 | виды полей формы: срок важного — переключатель `term` и `input[type=date]` для `until`; начало и конец события — `input[type=datetime-local]` (время по Москве) | приёмке нужен один способ заполнения; ответ Opus на вопрос T-7140a |
| К43 | имена `helpers_feed.py` сверх строки T-7140a: `make_role`, `try_comment`, `try_upload`, `wait_file_state`, `wait_quarantine`, `refusals`, `parse_shift_line`, `parse_retention_line`, `feed_mail`, `no_feed_mail`, `tick_mail`, `bell`, `wait_bell`, `my_notifications`, `fakebots`; необязательные параметры `publish(..., confirm_pdn=False)`, `add_comment(..., mentions=())`, `upload(..., post_id=None)`; `block_ws(context)` зовётся до создания страниц; у держателя «Писать всем» таблетка «Всем» стоит в форме по умолчанию, `publish` снимает её крестиком, если в `to` нет `all` | написано T-7140a; закреплено, чтобы писатели f01…f15 брали одни имена |

### 16.3. Расхождения источников, разрешённые в контракте

| № | Расхождение | Как в контракте |
|---|---|---|
| Р1 | план («Стенд и приёмка») — `feed_shift: shifted=<N> reminded=<M>`; решение 54 задач — с `important=<K>` | по решению 54 (14.1) |
| Р2 | план («Модель данных») — у `Shown` индекса `post_id` нет; решение 60 — индекс есть | по решению 60 (2.2, 1.2) |
| Р3 | строка T-7138 — `test_kb_boundaries.py:278`; `impact.md` — падает 277; план — `:272-274` | 277 (15.3, п. 39); при сдвиге — по утверждению |
| Р4 | строка T-7138 — «14 флажков» у `test_notify_catalog_2.py:552, 556`; `impact.md` «Находки» п. 4 — флажков 13 | ячеек `push` — 14, флажков — 13 (15.3, п. 35) |
| Р5 | план называет модуль загрузки `core.uploads`; решение 46 — `core.services.uploads` | полное имя (4.3) |

### 16.4. Вопросы к Opus — ответы (2026-10-30)

- В1: тест словаря текстов пишет T-7135 — `test_feed_deploy.py::test_feed_texts_dictionary_contains_every_key_and_text_of_contract_13_1_and_13_2 (FR-642)`.
- В2: `u<id>` — узел (подразделение), `p<id>` — человек (К19).
- В3: тексты К38 принимаются; показываются владельцу при приёмке среза вместе с прочими текстами решений.
- В4: `layer_down()` — слой падает сразу (К21).

### 16.5. Исходные вопросы (для истории)


| № | Вопрос | Предложение контракта |
|---|---|---|
| В1 | Решение 19 задач требует теста «словарь `texts.py` содержит каждый текст контракта», но ни одна строка Этапа 2 его не называет (в срезе 006 имя дал Opus, П5 CONTRACT-006). Какой задаче и под каким именем его писать? | T-7135, `test_feed_deploy.py::test_feed_texts_dictionary_contains_every_key_and_text_of_contract_13_1_and_13_2` (FR-642) — по образцу среза 006 |
| В2 | Значения «Кому» `u<id>` / `p<id>` — что есть что? | К19: `u` — узел, `p` — человек |
| В3 | Тексты К38 («Файл не найден», «Автор не отмечает свою запись прочитанной», «Срок важного уже истёк») видны сотруднику, а в плане их нет — показывать ли владельцу, как решение 48? | показать при проверке контракта; до ответа тесты T-7112, T-7129 берут литералы К38 |
| В4 | `layer_down()` — «подмена слоя `publish` таймаутом» (план): падать сразу или через 2 с? При 2 с на вызов последовательные рассылка ленты, число «Ленты» и `live.push` дают больше 3 с | К21: сразу (как закрытый порт стенда, решение 40); задержка — параметр `delay` для отдельного теста, если Opus решит иначе |
