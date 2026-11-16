# Контракт имён тестов среза 008 (T-8102…T-8150)

SPEC-008 (подписана 2026-11-16, `sha256:f486…d10c9`) → PLAN-008 v1 (утверждён, подпись 2026-11-16T20:02+03:00) →
TASKS-008 v1 (утверждён, подпись 2026-11-16T20:51+03:00). Тесты пишутся до кода и задают имена, которых нет в PLAN-008;
реализация (Этап 3) берёт их отсюда дословно (решение 2 задач). Имена плана (модели и поля раздела «Модель данных»,
адреса «Контрактов», коды журнала, приложение `messenger`, задания `publish_event` и `retention_night`, запись cron
`messenger_retention`, команда `e2e_messenger_age`, два вида `messenger.*`, точка `unit_form_parts`, датакласс
`UnitFormPart`, функции `subtree_member_ids`, `unit_chain_ids`, `unit_refs`, `render_plain`, `snippet`, `build`,
`MAX_SIDE`, поля `NotificationKind.channels`/`coalesce_text`, признак `bell_link`) здесь повторяются только там, где
тест уточняет их форму. Прежние контракты (`CONTRACT.md`, `CONTRACT-002.md` … `CONTRACT-007.md`) не правятся: что в них
устаревает со срезом 008, перечислено в разделе 15 (решение 2 задач; план, «Прежние тесты, которые придётся поправить»).

Происхождение каждой строки видно из текста: «план» — PLAN-008; «задачи» — TASKS-008 и её раздел «Решения Opus по
задачам» (решения 1–16); «факт» — файл репозитория, названный в строке (дерево на 2026-11-16, до кода среза 008);
«решение контракта Кn» — выбор автора контракта (исполнитель T-8002) там, где план и задачи оставили выбор; причина
каждого выбора — в той же строке и сводно в разделе 16. Решения контракта ничьим решением владельца не являются: их
проверяет Opus до запуска T-8003 (решение 2 задач).

Помощники тестов: `tests/support_messenger.py` (пишет только T-8003, раздел 5.8) и `tests/e2e/helpers_messenger.py`
(пишет только T-8130, раздел 14.3). В колонке «Тесты» стоят задачи T-81NN, которые берут имя; полные имена тестов — в
строках задач Этапа 2 TASKS-008. Файлы тестов Этапа 2 — `test_messenger_*.py` по 26 темам плана (решение 1 задач);
приёмка — `tests/e2e/test_m01_personal.py` … `test_m13_rights.py`.

Правила для всех тестов среза:
- время (план, «Проверка»; как CONTRACT-007): службы берут время из `django.utils.timezone.now()` один раз на действие
  и передают его в SQL параметром `%s`, а не `now()` базы (отметка прочтения `min(max(прежняя, at), now())`, граница
  срока хранения, `last_message_at`, «Прочитали N из M»); дата по Москве — `apps.core.widgets.moscow_today()` (факт);
  тесты ставят часы фикстурой `clock` (`Clock` из `tests/factories.py`); проверки «по Москве» — часы на полночь UTC
  (03:00 по Москве) и на 21:00–23:59 UTC (дата по Москве отличается от даты UTC);
- задания выполняются синхронно: ночное — `support_messenger.run_retention(now)` (`tasks.retention_night(now=None)`
  принимает время параметром), рассылка — вызов `tasks.publish_event(...)` в тесте или `support_notify.run_jobs("notify")`
  для постановки в очередь; задания RQ `files`/`notify` — прежним `support_notify.run_jobs(queue_name)`; приёмка
  сдвигает время командой `e2e_messenger_age --days N` через обёртку `age(days)` (раздел 14);
- всё, что идёт «после фиксации» (постановка рассылки, стирание файлов с диска, пересчёт вектора вне транзакции),
  проверяется внутри `django_capture_on_commit_callbacks(execute=True)`;
- гонки — без потоков: по SQL (`support_messenger.capture_sql`), последовательно (два `get_or_create` личного диалога,
  отправка и удаление чата), подменой «между выборкой и замком»; `django_db(transaction=True)` не используется;
  `select_for_update` проверяется `support_kb.assert_for_update` (повторный экспорт в `support_messenger`);
- WebSocket: `asgiref.testing.ApplicationCommunicator` через `support_notify.ws_run`, `WsClient` и `_application()`;
  настоящий слой `channels_redis` на Valkey (база 15); подключение к `/ws/messenger/` — `support_messenger.ws_client(user,
  query)`; проверка сессии ускоряется подменой `apps.messenger.consumers.CHECK_INTERVAL`; недоступный слой `publish` —
  `support_messenger.layer_down()`; `InMemoryChannelLayer` и подмены `CHANNEL_LAYERS` не используются;
- ClamAV: подмена строкой `apps.integrations.clamav.services.scan` помощниками `support_org.scan_clean`, `scan_found`,
  `scan_unavailable`; `support_messenger.attach(...)` берёт их же; настоящий ClamAV (EICAR) — только в приёмке;
- код среза тесты импортируют внутри функций теста (или через `support.model("messenger.Chat")`), а не на уровне
  модуля: сбор `pytest --collect-only` проходит до появления кода; `support_messenger.py` на уровне модуля `apps.messenger`
  не импортирует;
- тексты отказов в тестах — литералы раздела 13.1, а не импорт `messenger/texts.py`; словарь `apps.messenger.texts.TEXTS`
  содержит каждый ключ и текст раздела 13.1 (сверка — одна проверка исполнителя T-8201; тесты отказов ищут текст
  подстрокой в разметке);
- ответы (план, «Контракты», «Права и неприкосновенность»): чужой, несуществующий и удалённый чат, его сообщение, файл и
  эскиз отвечают одинаково — 404 обычной страницы «Не найдено» без подробностей (сравнение в пределах одного клиента —
  `support.same_failure`, как CONTRACT-006); чат виден, действие не разрешено — 403; отказ с сообщением — 200 с формой
  или фрагментом и причиной у поля (запрос HTMX — фрагмент); не вошедшему — 302 на `/login/?next=<путь>`, без второго
  фактора — прежние промежуточные слои ядра;
- секреты и ПДн: почта и телефоны — `support_messenger.email_of`, `phone_of`; имена переменных — без `secret`, `token`,
  `key`, `password`; строка EICAR собирается из частей; в файлах, ответах и отчётах — только `***`;
- разметка: без `role="status"`, `role="alert"`, `data-error`, `data-warning`, кроме сообщений об отказах форм
  (раздел 10.1); без `style=` и `on…=` в шаблонах среза; свои скрипты — внешние файлы `static/messenger/messenger.js`,
  `messenger.css`, без `eval(` и `new Function`;
- тесты ходят по путям плана (раздел 10), а не по именам маршрутов; маршруты среза не содержат `regist`, `signup`;
- SQL — только параметры (NFR-703): литерал с `%s` и списком параметров; цепочка узлов — массивом `= ANY(%s)`; значения
  фильтров ищутся в `params` захваченного запроса, а не в тексте SQL до подстановки (`support_feed.queries_with_params`
  через `capture_sql`, как в CONTRACT-007).

Разделы:
1. Среда запуска и числа среза.
2. Модели и поля, данные установки.
3. Ядро, `org`, `notify` и записи точек `messenger`.
4. Прежние модули: `org`, `notify`, `feed`; выключение мессенджера.
5. Службы `messenger`, исключения, точки подмены и помощники `support_messenger.py`.
6. Места одной функции видимости.
7. Виды уведомлений и таблица «код вида → модуль».
8. Журнал.
9. Поиск.
10. Маршруты, поля форм, ответы.
11. Слой каналов: сообщения, кадры, коды закрытия.
12. Зацепки `data-*` и `id` для приёмки.
13. Тексты, которые проверяют тесты.
14. Команды стенда, нагрузка, помощники приёмки.
15. Что меняется в прежних контрактах и тестах (для T-8007).
16. Вопросы и решения.

## 1. Среда запуска и числа среза

### 1.1. Приложение, каркас, статика

| Что | Требование | Тесты |
|---|---|---|
| `INSTALLED_APPS` | `"apps.messenger"` — последним, после `"apps.feed"` (план): хвост списка — `"apps.servicedesk"`, `"apps.notify"`, `"apps.knowledge"`, `"apps.lists"`, `"apps.search"`, `"apps.feed"`, `"apps.messenger"` (факт сейчас: шесть имён без мессенджера); метка `messenger`, класс `MessengerConfig` (план), `verbose_name = "Мессенджер"` (решение контракта К1) | T-8124 test_messenger_is_last_in_installed_apps; T-8125; T-8007 |
| `MessengerConfig.ready()` | зовёт `apps.messenger.extensions.register_all()` и подписывает шину: `unit.deleted` → `department.on_unit_deleted`, `access.changed` → `unread.on_access_changed` (план, «Точки расширения ядра и шина событий»); при выключенном приложении подписок нет | T-8125 test_messenger_registers_points_and_no_top_bar_items |
| Каркас (план, «Где живёт код») | `apps/messenger/`: `apps.py`, `models.py`, `texts.py`, `notify_kinds.py`, `audit_labels.py`, `extensions.py`, `unit_form.py`, `stand.py`, `tasks.py`, `consumers.py`, `routing.py`, `urls.py`; `views/` (`pages`, `chats`, `messages`, `files`, `mentions`, `settings`, `notifications`); `services/` (`chats`, `members`, `department`, `messages`, `mentions`, `text`, `read`, `unread`, `live`, `notify_rules`, `files`, `search`, `retention`, `messenger_settings`, `page`, `errors`); `management/commands/e2e_messenger_age.py`; миграции `0001_initial.py`, `0002_initial_data.py`; шаблоны `templates/messenger/` (`page.html`, `_list.html`, `_chat.html`, `_message.html`, `_form.html`, `_files.html`, `_mention_suggest.html`, `_search.html`, `_notifications.html`, `settings.html`, `_card_write.html`, `_unit_form_field.html`, `_badge.html` — решение контракта К2), иконка `templates/icons/chat.html` | T-8125 (обход `ast`) |
| Статика | `static/messenger/messenger.js` — `<script defer src=…>`, `messenger.css` — `<link rel="stylesheet">` на страницах мессенджера (шаблоны наследуют подключение через `_assets.html`, план); в `_assets.html` файлы среза подключаются для страниц мессенджера; в `.js` нет `eval(` и `new Function`; во фрагментах WebSocket скриптов нет | T-8124 test_templates_have_no_style_or_event_attributes |
| Шаблоны | в `templates/messenger/` нет `style=` и `on…=` (регулярные выражения, как в `test_shell.py`) | T-8124 |
| CSP | `/messenger/…`, `/messenger/chats/<id>/`, `/notifications/` (вкладка), `/settings/messenger/` отдают `Content-Security-Policy` с `script-src 'self'` без `'unsafe-inline'` и `'unsafe-eval'`; `connect-src 'self'` (план, «Сверка с конституцией») | T-8124 test_csp_without_unsafe_inline_on_messenger_pages |
| Язык и время | тексты страниц среза по-русски (страницы — `support_messenger.messenger_pages()`, раздел 5.8); время — по Москве (`localtime` шаблонов): тест ставит `Clock` на полночь UTC и находит 03:00 по Москве у сообщений, превью списка и в поиске; формат показа — `time[data-at]` с `datetime` ISO и текстом «ДД.ММ.ГГГГ ЧЧ:ММ» (как CONTRACT-006/007) | T-8124 test_texts_are_russian_and_time_is_moscow_at_utc_midnight |
| Файл теста развёртывания | `tests/test_messenger_deploy.py` (план, «Проверка») | T-8124 |

### 1.2. Задания, nginx, слой каналов, том файлов, маршрут соединения

| Что | Требование | Тесты |
|---|---|---|
| Запись cron (план «Запуск», «Срок хранения и ночное задание») | двадцать первая запись в `config/cron.py`, под `apps.is_installed("apps.messenger")` (импорт `from apps.messenger.tasks import retention_night` внутри той же проверки): `register(retention_night, queue_name="maintenance", cron="55 23 * * *", name="messenger_retention", job_timeout=600)`; других записей на `55 23 * * *` нет (факт сейчас: двадцать вызовов `register`, `55 23` свободна); прежние двадцать записей — те же имена и минуты (у `notify_tick` — интервал 30 с) | T-8124 test_cron_has_21_registers_and_messenger_retention_55_23_maintenance; T-8119 test_cron_entry_55_23_maintenance; T-8007 |
| `JOBS_008` | `{"messenger_retention": ("retention_night", "maintenance", None, "55 23 * * *", 600)}` — формат `FEED_JOBS`/`LISTS_JOBS` из `test_sd_deploy.py` (функция, очередь, интервал, cron, тайм-аут; имя ≠ функция); правится вместе с T-8007 | T-8124 |
| Адреса | `config/urls.py`: `include("apps.messenger.urls")` под `apps.is_installed("apps.messenger")` после `feed` (план); прежние include и обработчики ошибок не меняются | T-8125 |
| Соединение | `config/asgi.py`: `websocket_urlpatterns = list(notify_routing.websocket_urlpatterns)`, затем `feed`, затем при `apps.is_installed("apps.messenger")` — `list(messenger_routing.websocket_urlpatterns)` (импорт внутри проверки); маршрутизатор — прежний `AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(websocket_urlpatterns)))`; тест сверяет включение списка `messenger.routing.websocket_urlpatterns`, а не его содержимое | T-8125 test_asgi_without_messenger_has_no_ws_messenger |
| `apps/messenger/routing.py` | `websocket_urlpatterns = [re_path(r"^ws/messenger/$", consumers.MessengerConsumer.as_asgi())]` (решение контракта К3: как `notify/routing.py` и `feed/routing.py`); путь без номера чата, чат — в строке запроса | T-8115, T-8124 |
| `location` nginx (план) | в `deploy/nginx.conf` и `deploy/nginx.prod.conf`: ровно один новый `location ~ ^/messenger/files/$ { … }` с `client_max_body_size 25m;`; всего `25m` — два (`^/feed/files/$` и `^/messenger/files/$`; факт сейчас: один); набор имён директив `proxy_*` совпадает с блоком `tickets` того же файла (как блоки `kb`, `lists`, `feed`); прежние четыре `location` с `55m` и общий предел `6m` не меняются; `location /ws/` префиксный и не меняется | T-8124 test_nginx_has_two_25m_locations_and_repeated_proxy_directives; T-8124 test_ws_location_and_backup_script_unchanged; T-8007 |
| `CHANNEL_LAYERS` (план «Запуск») | ключей по-прежнему два: `"default"` (соединения, `socket_timeout` 30) и `"publish"` (рассылка, `socket_timeout` 2), `max_connections` 300, `socket_connect_timeout` 2, `prefix` `"crm-asgi"`; словарь не меняется (факт) | T-8124; T-8125 |
| Том файлов | оригиналы и эскизы — в томе `protected`: `core.services.uploads.store(data, name, "messenger")`; эскиз — `PROTECTED_ROOT/attachments/thumbs/<id StoredFile>.jpg` или `.webp` (план; путь — как у ленты); `deploy/backup/backup.sh` не меняется; новых томов нет | T-8124; T-8117b |
| Зависимости | новых пакетов нет; в `requirements.txt` нет строки «Срез 008» (план) | T-8124 test_no_new_packages_and_no_slice_line_in_requirements |

### 1.3. Сброс стенда: точка `stand_reset` модуля `messenger`

Функция — `apps.messenger.stand.stand_reset()` без аргументов, регистрируется в `apps/messenger/extensions.py` последней
из регистраций `register_all()` (план; как у `knowledge`, `lists`, `feed`). `apps.messenger` последний в `INSTALLED_APPS`,
команда `e2e_reset_stand` зовёт функции в обратном порядке, поэтому функция `messenger` идёт первой, затем `feed`,
`lists`, `knowledge` (задачи, решение 5). Работает через соединение `migrate`, если оно настроено, иначе `default`
(как `lists` и `feed`).

| Что | Требование | Тесты |
|---|---|---|
| Транзакция | всё стирание и `seed(stand=True)` — в одной `transaction.atomic(using=<алиас>)` | T-8123 test_stand_reset_runs_in_migration_transaction |
| Таблицы | стираются все таблицы `messenger`: `MessageAttachment`, `ChatRead`, `ChatMember`, `Message`, `Chat`, `MessengerSettings` (порядок — решение контракта К4: сначала зависимые; `MessengerSettings` затем создаётся заново); строки `core.StoredFile` с `purpose="messenger"` удаляются вместе со вложениями | T-8123 test_stand_reset_wipes_chats_messages_files_and_thumbs_after_commit |
| Файлы | пути оригиналов и эскизов по строкам `MessageAttachment`/`StoredFile` (все состояния) собираются до удаления; диск — `transaction.on_commit(lambda: core_files.remove_paths(paths), using=<алиас>)` на том же алиасе; каталог `PROTECTED_ROOT/attachments/thumbs/` не стирается целиком (в нём эскизы других срезов — решение контракта К4, отличие от `feed`, где каталог принадлежал только ленте) | T-8123 |
| Восстановление | `seed(django.apps.apps, SimpleNamespace(connection=connections[<алиас>]), stand=True)` миграции `0002`: `MessengerSettings(pk=1, retention_years=3, general_chat_enabled=True)` и «Общий чат» (`kind="general"`), если их нет; повторный запуск ничего не дублирует | T-8123 test_stand_reset_returns_retention_and_general_on |
| Порядок | в `extensions.registered("stand_reset")` функция `apps.messenger.stand.stand_reset` — последняя, сразу после `apps.feed.stand.stand_reset` | T-8123 test_stand_reset_runs_last_and_before_feed |
| Проверка стенда | `apps.messenger.stand.require_stand()` и `apps.messenger.stand.REFUSAL` — своя копия (план): `REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."` (текст — как у `lists` и `feed`, факт); без `os.environ.get("E2E_STAND") == "1"` — `CommandError(REFUSAL)` раньше любого чтения базы | T-8123 test_stand_command_refused_without_e2e_stand |

Тесты сброса помечаются `pytest.mark.django_db(databases=["default", "migrate"])`, данные создают и читают через
`using("migrate")`, функцию `stand_reset()` вызывают напрямую (как CONTRACT-006, 1.3, и CONTRACT-007, 1.3).

### 1.4. Числа среза (план, «Контракты» → «Числа среза для контракта тестов»)

| Число | Было (факт до среза) | Стало | Кто сверяет |
|---|---|---|---|
| Точек расширения | восемнадцать (`POINTS[-1] == "home_body"`) | девятнадцать; `unit_form_parts` — последняя (`support_messenger.POINTS_008 = ("unit_form_parts",)`) | T-8125 test_points_are_19_and_unit_form_parts_last; T-8126a; T-8007 |
| Вызовов `register` в `config/cron.py` | двадцать | двадцать один | T-8124; T-8119; T-8007 |
| Видов уведомлений | двадцать | двадцать два (два `messenger.*`, `order` 80 и 81) | T-8116a; T-8116b; T-8124 |
| Прав в портале | восемнадцать | восемнадцать (новых нет; настройки мессенджера и удаление чата отдела — `settings.portal`) | T-8103; T-8120 |
| Значений `StoredFile.Purpose` | пять (`feed` последним) | шесть; `messenger` — последним | T-8126a; T-8125 test_purposes_are_6_and_messenger_last |
| `order` группы поиска | «Лента» — 60 | «Мессенджер» — 61 (после «Ленты») | T-8118 test_provider_order_61_after_feed_and_group_title |
| Меню | «Лента» — первый (`order` 0); у администратора четырнадцать пунктов | «Мессенджер» — второй (`order` 1); пунктов с `settings.portal` на один больше (+«Настройки мессенджера», `order` 64); у администратора шестнадцать пунктов | T-8124; T-8007 |
| `location` с `client_max_body_size 25m` | один (`^/feed/files/$`) | два (`^/feed/files/$`, `^/messenger/files/$`) | T-8124; T-8007 |
| `apps.messenger` | — (`apps.feed` последний) | последний в `INSTALLED_APPS` | T-8124; T-8125; T-8007 |
| Ключей `CHANNEL_LAYERS` | два (`default`, `publish`) | два (не меняются) | T-8124 |
| Запись `stand_reset` | `feed` — последняя | `messenger` — последняя, `feed` перед ней | T-8123; T-8007 |
| Нагрузочные классы | `NotifyUser`, `FeedUser` (`FeedWsUser` в SPEC-007 — это `FeedUser`) | `FeedUser`, `NotifyUser`, `MessengerUser` | T-8124 test_load_profile_files_exist_with_three_classes; T-8150 |
| «Chrome» в NFR-702 | — | проверяется кругом Chromium в `tests/e2e/conftest.py` (четыре круга уже есть), как в прежних срезах | T-8142; T-8302 |
| Шесть кодов журнала | — | `messenger.chat_deleted`, `messenger.department_chat_deleted`, `messenger.unit_chat_deleted`, `messenger.general_changed`, `messenger.retention_changed`, `messenger.retention_purged` (раздел 8) | T-8121 |

`unit.deleted` — имя события шины (`apps.core.events`), а не код журнала; код журнала удаления узла —
`messenger.unit_chat_deleted` (реестр `core.services.audit`). Кода журнала `unit.deleted` нет; это разные реестры, и
тесты их не смешивают.

## 2. Модели и поля, данные установки

Модели берутся через `support.model("messenger.Chat")` и так далее. Типы, длины и связи — план («Модель данных»); здесь —
то, что план оставил выбору: имена ограничений и индексов, значения по умолчанию. Имена ограничений и индексов —
`<приложение>_<модель>_<поля>_<вид>`, не длиннее 30 знаков (решение контракта К5, как CONTRACT-007); тест ловит
`IntegrityError` и имя по тексту ошибки не сверяет. Обратные имена связей тесты не используют: выборки — через менеджеры
моделей (`chat.messages.order_by(...)`), как в CONTRACT-007.

### 2.1. Ядро и прежние модули

| Что | Требование | Тесты |
|---|---|---|
| `StoredFile.Purpose.MESSENGER` | значение `"messenger"`, подпись «вложение сообщения чата» (план), последним; миграция ядра `0011_storedfile_messenger_purpose.py` — только `AlterField` вариантов (как `0010` среза 007); прежние пять значений и `max_length` (16) не меняются | T-8126a test_purpose_messenger_choice_last_and_migration_0011_depends_on_0010 |
| `core.services.text` (новый модуль) | `render_plain(text, pieces, *, link_staff) -> SafeString` — единственное место `mark_safe` для пользовательского текста: экранирование, разбиение по шаблонам `pieces`, ссылки `http`/`https`/`mailto`, абзацы и переносы; `snippet(text, limit, *, expand=None) -> str` — отрывок без разметки, `expand` — преобразователь имён упоминаний (для ленты). Выражения перенесены из `feed/services/text.py` без изменения поведения | T-8126a test_core_render_plain_matches_feed_output_for_same_input, test_core_snippet_matches_feed_snippet_and_expand_hook |
| `core.services.thumbs` (новый модуль) | `build(source_path, stored_id) -> str` — эскиз ≤ 1280 px, JPEG/WebP, без EXIF, GIF первым кадром; `MAX_SIDE`; перенос из `feed/services/thumbs.py` без изменения поведения | T-8126a test_core_thumbs_build_matches_feed_path_and_size |
| `feed/services/text.py`, `feed/services/thumbs.py` | остаются обёртками: `render_plain(text, people, link_staff)` зовёт ядро со своим шаблоном `@[id]`; `build` и `MAX_SIDE` — из ядра; имена и сигнатуры прежние, поведение прежнее | T-8126a test_feed_wrappers_keep_names_signatures_and_behavior |
| `NotificationKind` | полей не прибавляется: `channels` и `coalesce_text` уже есть в срезе 007 (факт); два новых вида используют их | T-8116a |
| `core.Comment` | не используется мессенджером и не меняется | — |

### 2.2. Приложение `messenger` (план, «Приложение `messenger`»)

| Модель.поле | Требование | Тесты |
|---|---|---|
| `Chat.Kind` | `TextChoices`: `PERSONAL = "personal", "Личный"`; `GROUP = "group", "Групповой"`; `DEPARTMENT = "department", "Чат отдела"`; `GENERAL = "general", "Общий чат"` (значения — план; подписи — названия видов, решение контракта К6) | T-8102 test_chat_kind_checks_title_unit_pair_key_and_general_single_row |
| `Chat` | `kind` — `CharField(16, choices=Chat.Kind.choices)`; `title` — `CharField(200, blank=True, default="")` (пусто у личного и чата отдела); `unit_id` — `PositiveIntegerField(null=True, blank=True)` без внешнего ключа (модель `org.Unit` не импортируется, FR-650); `pair_key` — `CharField(32, blank=True, default="")` (`"<меньший id>:<больший id>"`); `created_by` — `ForeignKey("core.User", PROTECT, null=True, blank=True, related_name="+")` (пусто у «Общего чата»); `created_at` — `DateTimeField`; `last_message_at` — `DateTimeField(null=True, blank=True)` (пусто — сообщений нет) | T-8102; T-8103 |
| `Chat`, проверки и уникальности (план) | `CheckConstraint(name="messenger_chat_title_chk")`: `kind="group"` ⇔ `title <> ''`; `CheckConstraint(name="messenger_chat_unit_chk")`: `kind="department"` ⇔ `unit_id` не пусто, у прочих пусто; `CheckConstraint(name="messenger_chat_pair_chk")`: `kind="personal"` ⇔ `pair_key <> ''`; `UniqueConstraint(fields=["pair_key"], condition=Q(kind="personal"), name="messenger_chat_pair_uniq")`; `UniqueConstraint(fields=["unit_id"], condition=Q(kind="department"), name="messenger_chat_unit_uniq")`; `UniqueConstraint(fields=["kind"], condition=Q(kind="general"), name="messenger_chat_general_uniq")` | T-8102 test_department_unit_unique_and_general_unique_constraints |
| `Chat`, индексы | `Index(fields=["-last_message_at", "-id"], name="messenger_chat_last_msg_idx")`, `Index(fields=["created_by"], name="messenger_chat_created_by_idx")` (план) | T-8102 |
| `ChatMember` | `chat` — `ForeignKey(Chat, CASCADE, related_name="members")`; `user` — `ForeignKey("core.User", PROTECT, related_name="+")`; `is_creator` — `BooleanField(default=False)`; `joined_at` — `DateTimeField`; `left_at` — `DateTimeField(null=True, blank=True)` (пусто — в чате); `UniqueConstraint(fields=["chat", "user"], name="messenger_chatmember_uniq")`; `Index(fields=["user", "chat"], condition=Q(left_at__isnull=True), name="messenger_chatmember_user_idx")` (план) | T-8102 test_chat_member_unique_chat_user_and_partial_active_index |
| `ChatRead` | `chat` — `ForeignKey(Chat, CASCADE, related_name="reads")`; `user` — `ForeignKey("core.User", CASCADE, related_name="+")`; `last_read_at` — `DateTimeField`; `UniqueConstraint(fields=["chat", "user"], name="messenger_chatread_uniq")`; `Index(fields=["user", "chat"], name="messenger_chatread_user_idx")` (план; таблица отдельно, потому что строк участников у чата отдела и «Общего чата» нет) | T-8102 test_chat_read_unique_chat_user_and_index_for_counts |
| `Message` | `chat` — `ForeignKey(Chat, CASCADE, related_name="messages")`; `author` — `ForeignKey("core.User", PROTECT, null=True, blank=True, related_name="+")` (пусто у системной записи); `is_system` — `BooleanField(default=False)`; `text` — `TextField(blank=True, default="")` (до 4 000, хранится как есть); `quote` — `ForeignKey("self", SET_NULL, null=True, blank=True, related_name="+")`; `created_at` — `DateTimeField`; `edited_at`, `deleted_at` — `DateTimeField(null=True, blank=True)`; `search` — `SearchVectorField(null=True)` | T-8102; T-8109a |
| `Message`, проверки и индексы | `CheckConstraint(name="messenger_message_system_chk")`: `is_system` ⇔ `author` пуст; `CheckConstraint(name="messenger_message_deleted_chk")`: `deleted_at` не пуст ⇒ `text = ''`; индексы `Index(fields=["chat", "-created_at", "-id"], name="messenger_message_chat_idx")`, `Index(fields=["created_at"], name="messenger_message_created_idx")`, `GinIndex(fields=["search"], name="messenger_message_search_gin")` (план) | T-8102 test_message_system_requires_no_author_and_deleted_requires_empty_text, test_message_quote_set_null_and_indexes_chat_created_search_gin |
| `MessageAttachment` | `message` — `ForeignKey(Message, CASCADE, null=True, blank=True, related_name="files")` (пусто — файл ещё не привязан); `file` — `OneToOneField("core.StoredFile", PROTECT, related_name="+")`; `name` — `CharField(255)`; `thumb` — `CharField(255, blank=True, default="")`; `uploaded_by` — `ForeignKey("core.User", PROTECT, related_name="+")`; `uploaded_at` — `DateTimeField`; индексы `Index(fields=["message"], name="messenger_attach_message_idx")`, `Index(fields=["uploaded_by", "uploaded_at"], condition=Q(message__isnull=True), name="messenger_attach_unbound_idx")` (план) | T-8102 test_message_attachment_unbound_partial_index_and_protect_on_stored_file |
| `MessengerSettings` | одна строка `pk=1`: `retention_years` — `PositiveSmallIntegerField(default=3)`; `general_chat_enabled` — `BooleanField(default=True)`; `updated_at` — `DateTimeField(null=True, blank=True)`; `updated_by` — `ForeignKey("core.User", PROTECT, null=True, blank=True, related_name="+")`; `CheckConstraint(condition=Q(retention_years__gte=1, retention_years__lte=10), name="messenger_settings_years_chk")` (план) | T-8102 test_messenger_settings_retention_bounds_and_general_default_on |
| `on_delete` (план) | `ChatMember.user`, `Message.author`, `MessageAttachment.file`, `MessageAttachment.uploaded_by`, `MessengerSettings.updated_by` — `PROTECT`; `Chat→ChatMember/ChatRead/Message`, `Message→MessageAttachment` — `CASCADE`; `Message.quote` — `SET_NULL`; `ChatRead.user` — `CASCADE` (план) | T-8102 |
| Состав и прочтение (план) | строк `ChatMember` нет у чата отдела и «Общего чата»; состав — `members.members(chat)` на момент просмотра; отметка прочтения — строка `ChatRead`, поля `ChatMember.last_read_at` нет; первый личный диалог даёт 1 непрочитанное, новичок отдела и «Общего чата» без отметки — 0 | T-8103; T-8104; T-8106; T-8113 |
| Внешние ключи | у моделей `messenger` нет внешних ключей на модели `org`, `notify`, `feed`; `unit_id` — число (план) | T-8125 test_messenger_does_not_import_org_notify_feed_models |
| `object_ref` | `"messenger.chat:<id>"` у обоих видов уведомлений и у `object.viewed` (план, «Уведомления») | T-8116a; T-8112 |

### 2.3. Миграции и данные установки (план, «Где живёт код», «Модель данных»)

| Что | Требование | Тесты |
|---|---|---|
| `messenger 0001_initial.py` | все шесть моделей с проверками и индексами; зависимость — `("core", "0011_storedfile_messenger_purpose")`; имена индексов ≤ 30 знаков | T-8102 test_migrations_depend_on_core_0011_and_core_0002_initial_data |
| `messenger 0002_initial_data.py` | зависит от `("core", "0002_initial_data")` и `("messenger", "0001_initial")`; функция `seed(apps, schema_editor, *, stand=False)`; `schema_editor` читается только как `.connection.alias`; обратная функция — `migrations.RunPython.noop` (решение контракта К7: план обратного хода не задаёт) | T-8122 |
| Данные установки | `MessengerSettings.objects.get_or_create(pk=1, defaults={"retention_years": 3, "general_chat_enabled": True})`; «Общий чат» — `Chat.objects.get_or_create(kind="general", defaults={"title": "Общий чат"})` под уникальным индексом; повторный запуск ничего не дублирует | T-8122 test_migration_creates_settings_three_years_and_general_on, test_seed_twice_does_not_duplicate |
| `messenger_settings.get()` | возвращает строку `pk=1`, создаёт её с 3 и включённым «Общим чатом», если её нет (план) | T-8122 test_settings_get_creates_row_when_missing |
| Права | новых прав нет; приложение не создаёт `Permission` и не выдаёт права ролям; права роли приложения в базе — через `ALTER DEFAULT PRIVILEGES`, своих `GRANT` нет (план) | T-8103; T-8121 |

## 3. Ядро, `org`, `notify` и записи точек `messenger`

### 3.1. Изменения ядра (план, «Модель данных» → «Ядро и прежние модули»)

| Что | Требование | Тесты |
|---|---|---|
| `core.extensions.POINTS` | `"unit_form_parts"` — девятнадцатой, в конце кортежа; прежние восемнадцать — в прежнем порядке (план) | T-8126a test_point_unit_form_parts_is_nineteenth_and_dataclass_fields; T-8125; T-8007 |
| `core.extensions.UnitFormPart` | датакласс: `key: str`, `order: int`, `render: Callable[[HttpRequest, Unit], str]` (HTML поля или пустая строка), `on_saved: Callable[[Unit, dict, User, str | None], None]` — вызывается после `create_unit`/`update_unit` (план; сигнатура `on_saved(unit, post, actor, ip=None)`) | T-8126a; T-8127 |
| Чтение точки | `org` читает `extensions.registered("unit_form_parts")` и не знает, кто зарегистрировался (план: «как чтение `unit_usage` перед удалением узла»); мессенджер в `unit_usage` **не** регистрируется, иначе чат запрещал бы удаление узла (план) | T-8106 test_department_chat_not_registered_in_unit_usage_so_unit_deleted; T-8125 |

### 3.2. `org`: поля формы узла и событие удаления (план; T-8006)

| Что | Требование | Тесты |
|---|---|---|
| `org.views.structure_forms` | рендерит записи `unit_form_parts` в порядке `order`; после `create_unit`/`update_unit` зовёт `on_saved(unit, post, actor, ip)`; каждый обработчик — в собственном `transaction.atomic()` (savepoint): ошибка откатывает только его работу, пишется предупреждением в журнал `apps.messenger.unit_form` и не отменяет сохранение узла; `unit_new` и `on_saved` обёрнуты в `atomic` (сейчас транзакции нет) | T-8126b test_unit_form_renders_registered_fields_and_calls_on_saved_after_save, test_on_saved_own_savepoint_failure_does_not_cancel_unit_save_and_logs, test_unit_new_wrapped_in_atomic |
| `templates/org/_slider.html` | цикл по полям точки; без зарегистрированных полей форма прежняя | T-8126b; T-8127 test_without_messenger_form_has_no_field |
| `org.services.structure.delete_unit` | публикует `events.publish("unit.deleted", unit_id=…, name=…, actor_id=…)` после удаления узла, до конца транзакции; шина зовёт обработчик после фиксации, его сбой не откатывает удаление (план) | T-8126b test_structure_delete_unit_publishes_unit_deleted_after_delete; T-8106 |

### 3.3. `notify`: фрагмент потока, `bell_link`, старый адрес (план; T-8218)

| Что | Требование | Тесты |
|---|---|---|
| `GET /notifications/list/` | новый адрес `notify`; фрагмент потока: 50 на страницу, фильтр `f` (`""` — все, `unread` — непрочитанные), `page`, «Прочитать все», страницы; разметка — тот же `_row.html`; поведение прежней страницы не меняется | T-8126b test_notify_list_fragment_50_per_page_filter_and_pages |
| `notify/_list_body.html` | общий фрагмент потока, выделенный из `notify/list.html` (include); `list.html` и вкладка мессенджера рендерят его же (план) | T-8126b; T-8116b |
| `bell_link` в `top_bar_context` | ключ `bell_link` — адрес `/messenger/notifications/`, только при `apps.is_installed("apps.messenger")`; без мессенджера ключа нет (план) | T-8126b test_notify_bell_link_present_only_with_messenger |
| `templates/notify/bell.html` | при `bell_link` вместо `button[data-bell-toggle]` — ссылка `a[data-bell-link][href="/messenger/notifications/"]`; `#notify-count`, `#notify-toast`, контейнер `#notify-bell-panel` и `data-ws`/`ws-connect="/ws/notify/"` остаются; панель пустая; без мессенджера — прежняя кнопка панели (задачи, решение 6) | T-8126b; T-8007 |
| `GET /notifications/` | при установленном мессенджере — 302 на `/messenger/notifications/` с сохранением `f` и `page`; делает `notify.views.pages.notification_list` по `apps.is_installed`; без мессенджера — прежняя страница; `/notifications/<id>/open/`, `/read/`, `/read-all/`, `/notifications/bell/` не меняются | T-8126b test_old_notifications_address_redirects_with_f_and_page |
| `_bell_panel.html` | адрес «Все уведомления» берётся из того же признака `bell_link` (план) | T-8126b |

### 3.4. Записи точек `messenger` (`apps/messenger/extensions.py`, план «Точки расширения ядра и шина событий»)

`register_all()` регистрирует в порядке строк таблицы плана, `stand_reset` последней (решение контракта К8):
`menu_items`, `card_sections`, `notification_kinds`, `search_providers`, `file_purposes`, `audit_labels`, `unit_form_parts`,
`stand_reset`. Каждая регистрируемая функция определена в модуле `apps.messenger.*` (по `__module__` её снимает
`without_messenger()`).

| Точка | Регистрируемая функция и запись | Тесты |
|---|---|---|
| `menu_items` | `apps.messenger.extensions.menu_items() -> list[dict]`: `{"permissions": (), "url": "/messenger/", "title": "Мессенджер", "icon": "icons/chat.html", "order": 1, "visible": lambda user: True, "badge": <функция `unread.badge(user)`>, "live_badge": "messenger"}` и `{"permissions": ("settings.portal",), "url": "/settings/messenger/", "title": "Настройки мессенджера", "icon": "icons/gear.html", "order": 64}` (план; `support_messenger.MENU_008`) | T-8124, T-8120; T-8007 |
| `card_sections` | `apps.messenger.extensions.card_sections(viewer, person) -> list[CardSection]`: `[CardSection("messenger", "profile", 70, "messenger/_card_write.html", {})]`; для себя и уволенного — `[]` (скрыт); кнопка «Написать» ведёт на `/messenger/?to=<id>` (план; `order` и `tab` — решение контракта К9: `profile` — прежняя вкладка карточки, `order` — после «Заявок» 60) | T-8104 test_card_write_button_hidden_for_self_and_dismissed; T-8214 |
| `notification_kinds` | `apps.messenger.notify_kinds.notification_kinds() -> list[NotificationKind]` — два вида (раздел 7) | T-8116a; T-8125 |
| `search_providers` | `apps.messenger.services.search.search_providers() -> list[SearchProvider]`: `[SearchProvider(key="messenger", title="Мессенджер", order=61, search=search, count=count, available=<истина для любого вошедшего>)]` (план; имя функции — К10) | T-8118; T-8125 |
| `file_purposes` | `apps.messenger.services.files.file_purposes() -> list[FilePurpose]`: `[FilePurpose("messenger", still_waiting, clean, found)]` (план; поля — факт `core/extensions.py`; имена функций — как у ленты) | T-8117b; T-8119 |
| `audit_labels` | `apps.messenger.audit_labels.audit_labels() -> dict` в форме модуля `knowledge`/`feed` (факт: `{"actions", "fields", "object_types", "values"}`; раздел 8.2) | T-8121 test_labels_of_actions_and_object_types_are_russian |
| `unit_form_parts` | `apps.messenger.unit_form.form_parts() -> list[UnitFormPart]`: `[UnitFormPart(key="messenger_chat", order=10, render=render, on_saved=on_saved)]` — галочка «Создадим чат для всего отдела» (план; имя функции — К10) | T-8127; T-8125 |
| `stand_reset` | `apps.messenger.stand.stand_reset` (раздел 1.3) | T-8123 |

`top_bar_items` мессенджер не регистрирует и не читает: колокольчик остаётся за `notify`, его адрес получает признак
`bell_link` (план; уточнение к SPEC-008 и ADR-0017, где точка названа в общем перечне связей). Прежние точки
`home_notices`, `home_body`, `role_sources`, `role_usage`, `staff_directory`, `day_marks`, `unit_usage`, `mail_renderers`,
`login_links`, `ticket_card_parts` мессенджер не использует (план). Тесты T-8125
test_messenger_registers_points_and_no_top_bar_items, test_without_messenger_menu_search_catalog_card_and_unit_form_have_no_trace.

### 3.5. Шина событий (план)

| Что | Требование | Тесты |
|---|---|---|
| `unit.deleted` | подписка в `MessengerConfig.ready()`: обработчик `apps.messenger.services.department.on_unit_deleted(unit_id, name, actor_id)` собирает пути файлов, удаляет чат отдела и пишет журнал `messenger.unit_chat_deleted` без текста; повтор идемпотентен; сбой обработчика не откатывает удаление узла (шина зовёт после фиксации) | T-8106 test_deleted_unit_deletes_chat_and_audits_without_text; T-8126b |
| `access.changed` | подписка: `unread.on_access_changed(user_ids)` сбрасывает кэш чисел затронутых сотрудников (`user_ids=None` — всех); состав и видимость считаются на момент запроса, событие нужно только для кэша (план) | T-8113 test_access_changed_event_invalidates_counts_of_affected_employees |
| `object.viewed` | публикуется при открытии беседы и при отметке прочтения: `events.publish("object.viewed", object_ref=f"messenger.chat:{chat.pk}", user_id=user.pk)` (форма — факт `knowledge/services/articles.py`); `notify` гасит уведомления этого чата (FR-666) | T-8112 test_object_viewed_event_silences_chat_notifications |
| Уведомления | создаются не событиями шины, а прямым `notify.services.dispatch.create` (как лента): получателей считает `notify_rules` до вызова (план) | T-8116a |

## 4. Прежние модули: `org`, `notify`, `feed`; выключение мессенджера

### 4.1. `org.services.structure` (план, «Состав чата»)

| Функция | Что даёт | Тесты |
|---|---|---|
| `subtree_member_ids(unit_ids) -> frozenset[int]` | сотрудники узлов и всех вложенных (основная работа и совместительство) без уволенных — состав чата отдела (план) | T-8103 test_members_of_department_chat_are_subtree_without_dismissed; T-8106 |
| `unit_chain_ids(user) -> frozenset[int]` | цепочка узлов сотрудника — видимость чатов отдела и условие поиска (план) | T-8103 test_visible_chats_for_employee_personal_group_department_chain_and_general |
| `unit_refs(ids) -> dict[int, UnitRef]` | имена узлов для названия чата отдела (переименование видно сразу, без события) | T-8106 test_renaming_unit_changes_chat_title_without_new_row |

Других функций `org` мессенджер не зовёт; модели `org` не импортируются (план). Без `apps.org` отдельских чатов не
видно, и `unit_form_parts` не рендерится (как без оргструктуры у ленты нет адресатов-узлов).

### 4.2. `notify` (план, «Живые обновления», «Уведомления»)

| Функция | Что даёт | Тесты |
|---|---|---|
| `notify.services.dispatch.create(kind_code, drafts) -> list[int]` | записи и доставки по черновикам; вызывается под `apps.is_installed("apps.notify")`; модели `notify` не импортируются (план) | T-8116a |
| `notify.services.live.group(user_id) -> str` | имя группы `notify.u.{id}` для кадра числа пункта меню (план) | T-8114 test_badge_and_row_fragments_go_to_personal_notify_group |

15-минутное письмо, тихие часы, сводка с началом рабочего дня и `still_relevant` — прежние правила `notify`; раздел 7
ссылается на CONTRACT-004 (6.3, 6.6, 6.9, 6.11) и не переписывает их.

### 4.3. `feed` и ядро

| Что | Требование | Тесты |
|---|---|---|
| `feed/services/text.py`, `feed/services/thumbs.py` | обёртки над `core.services.text`/`core.services.thumbs`; имена и сигнатуры прежние; тесты ленты без правок | T-8126a |
| Импорты | мессенджер не импортирует `apps.feed`; лента не импортирует `apps.messenger`; общие выражения живут в ядре (план) | T-8125 test_no_previous_module_imports_apps_messenger, test_messenger_does_not_import_org_notify_feed_models |

### 4.4. Выключение модуля в тестах (задачи, решения 10, 12)

`support_messenger.without_messenger()` — контекстный менеджер: снимает регистрации `apps.messenger` из всех точек
(через `extensions.empty()` либо снятие своих функций), снимает подписки шины `unit.deleted`/`access.changed`, подменяет
`apps.is_installed` так, что `apps.messenger` не установлен, и перезагружает маршруты соединений (как
`support_feed.without_feed`, раздел 3.4 CONTRACT-007). Проверки: меню, поиск, каталог уведомлений, карточка сотрудника,
форма узла и `asgi` без следов мессенджера; `/notifications/` — прежняя страница; колокольчик — прежняя кнопка.

## 5. Службы `messenger`, исключения, точки подмены и помощники

Службы — `apps/messenger/services/`; функции с именами плана перечислены дословно, прочие имена — решение контракта К10
(тесты зовут их через `support.model`/ленивый импорт). Все службы участия зовут одну функцию `members.get_chat`
(раздел 6). Исключение — `services/errors.py`: `MessengerError` с полем `code` (ключ раздела 13.1/13.2, как
`FeedError`/`ListsError`).

### 5.1. Участие, видимость, список чатов

| Функция | Сигнатура и поведение | Тесты |
|---|---|---|
| `members.members(chat) -> frozenset[int]` | единственная функция состава: личный и групповой — `ChatMember` с `left_at IS NULL` без уволенных; чат отдела — `subtree_member_ids([chat.unit_id])` без уволенных; «Общий чат» — действующие сотрудники (`state` не `dismissed` и не `invited`) одним запросом; заблокированные входят в состав, но уведомлений и кадров не получают (план) | T-8103 test_blocked_member_counted_but_gets_no_frames_or_notifications; T-8106; T-8107 |
| `members.is_member(user, chat) -> bool` | участие по тому же правилу; зовётся страницами и службами (план) | T-8103 |
| `members.can_write(user, chat) -> bool` | участие и действующий сотрудник; у личного диалога с уволенным — ложь; у выключенного «Общего чата» — ложь (план) | T-8104; T-8107 |
| `members.visible_chats(user)` | видимые чаты: личные и групповые — строки `ChatMember` без выхода; отдельские — `chat.unit_id = ANY(unit_chain_ids(user))`; «Общий чат» — только при `general_chat_enabled` (план) | T-8103 test_visible_chats_for_employee_personal_group_department_chain_and_general |
| `members.get_chat(user, chat_id) -> Chat` | одна точка решения: невидимый, несуществующий и удалённый чат — одинаковый `Http404`; её зовут страница, беседа, история, поиск по беседе, подсказка «@», отправка, правка, удаление, файлы, эскизы, поиск (в SQL — то же правило), рассылка и `still_relevant` (план, FR-669) | T-8103 test_get_chat_same_http404_for_missing_foreign_and_deleted, test_every_endpoint_of_chat_uses_one_visibility_function |
| `chats.personal(user, peer) -> Chat` | `pair_key = "<меньший id>:<больший id>"`, `get_or_create` под уникальным индексом; при гонке `IntegrityError` перехватывается и строка читается заново; диалог с уволенным не создаётся (план) | T-8104 test_first_message_creates_single_dialog_and_second_goes_there, test_race_of_two_creations_leaves_one_row |
| `chats.create_group(creator, title, member_ids) -> Chat` | название 1–200 после среза пробелов; участники — действующие; создатель входит сам; хотя бы один участник (план; имя — К10) | T-8105 |
| `chats.general() -> Chat \| None` | строка `kind="general"`; при выключенной настройке прямой адрес отвечает 404 (план) | T-8107 |
| `chats.rows(user, q="")` | список видимых чатов одним запросом с `LATERAL`: название, превью последнего неудалённого (`snippet` 100), время последнего сообщения, число непрочитанных, признак «есть непрочитанные»; порядок `COALESCE(last_message_at, created_at) DESC, id DESC`; `q` — по названиям и ФИО сервером (план; имя — К10) | T-8108 test_list_orders_by_last_message_and_puts_empty_chats_last, test_list_sql_count_does_not_grow_with_number_of_chats |

### 5.2. Чат отдела, сообщения, упоминания, текст

| Функция | Сигнатура и поведение | Тесты |
|---|---|---|
| `department.create(unit, actor) -> Chat` | по галочке: название из узла через `unit_refs`, две системные записи (`is_system=True, author=NULL`) «Создал чат» и «К чату присоединились сотрудники отдела «<название>»» в одной транзакции, повторно не создаётся (план) | T-8106 test_checkbox_on_unit_creation_makes_chat_with_title_and_two_system_messages, test_no_checkbox_no_chat_and_repeat_save_makes_no_second_chat |
| `department.on_unit_deleted(unit_id, name, actor_id)` | обработчик `unit.deleted`; удаление чата и журнал `messenger.unit_chat_deleted` без текста (раздел 3.5) | T-8106 test_deleted_unit_deletes_chat_and_audits_without_text |
| `department.delete(chat, actor, *, reason)` | удаление чата отдела администратором портала (`settings.portal`) с подтверждением и журналом `messenger.department_chat_deleted`; участнику — 403 (план; имя — К10) | T-8106 test_portal_admin_deletes_department_chat_with_confirm_and_audit, test_member_cannot_delete_department_chat_403 |
| `messages.send(chat, author, text, quote=None, files=()) -> Message` | текст после среза пробелов не пуст; NUL удаляется; длина ≤ 4 000; цитата — сообщение этого чата, один уровень; вложения — до 10 непривязанных файлов автора условным `UPDATE`; в одной транзакции: сообщение, вложения, вектор, `last_message_at`, уведомления; после фиксации — рассылка (план) | T-8109a; T-8109b |
| `messages.edit(message, author, text) -> Message` | только автор и только живое сообщение (удалённое по сроку — 404); тот же предел; `edited_at = now()`; вектор пересчитывается; уведомлений нет, в том числе при новом упоминании (план) | T-8109a; T-8109b |
| `messages.delete(message, author) -> Message` | только автор: `deleted_at`, `text=''`, пустой вектор, удаление вложений и файлов (строки и диск после фиксации), пересчёт `last_message_at`; чужое — 403 при видимом чате, чужой чат — 404 (план) | T-8109a; T-8109b |
| `mentions.extract(text) -> tuple[frozenset[int], frozenset[int]]` | два набора по маркерам `@[u<id>]` и `@[c<id>]`; человек учитывается только как участник чата; чат — только свой; недействительный номер остаётся текстом; предел 20 разных людей на сообщение, повтор не расходует (план) | T-8111 test_extract_returns_people_and_chats_sets, test_21_distinct_mentions_refused_and_20_allowed |
| `mentions.suggest(user, chat, q) -> list` | до 20 строк: участники чата (действующие, ФИО и подразделение) и свои чаты (название); пустой `q` или один знак — пусто; в личном диалоге — пусто (план; имя — К10) | T-8111 |
| `text.render_plain(text, *, link_staff) -> SafeString` | обёртка над `core.services.text.render_plain` с шаблонами мессенджера: `@[u<id>]` → `<a data-mention>` с ФИО, `@[c<id>]` → ссылка `/messenger/chats/<id>/`, `http`/`https`/`mailto` — ссылки, прочее экранировано, абзацы и переносы; разметка не выполняется (план) | T-8110 |
| `text.snippet(text, limit, *, expand=None) -> str` | обёртка над ядром для превью списка и поиска (план) | T-8110 test_snippet_100_without_markup_and_with_mention_expand |

### 5.3. Прочтение, числа, рассылка, уведомления

| Функция | Сигнатура и поведение | Тесты |
|---|---|---|
| `read.mark(chat, user, at) -> ChatRead` | `update_or_create` с `last_read_at = min(max(прежняя, at), now())`; будущее время не принимается; ответ несёт узел числа чата, общее число и «Прочитали N из M» у последнего своего сообщения (план; имя — К10) | T-8112 test_repeat_read_keeps_max_and_does_not_decrease, test_future_at_clamped_to_now_and_does_not_suppress_next_messages |
| `read.line(chat, message) -> tuple[int, int]` | «Прочитали N из M»: M — `members(chat)` без автора (вступление не позже сообщения), N — отметки `last_read_at >= created_at` этого сообщения среди них; только у последнего своего сообщения (план; имя — К10) | T-8112 test_author_sees_read_12_of_40_only_under_last_own_message |
| `unread.counts(user) -> dict[int, int]`, `unread.total(user) -> int`, `unread.badge(user) -> int` | число у чата и общее; свои и удалённые не входят; база — `joined_at` у личного и группового, 0 без отметки у чата отдела и «Общего чата»; кэш 5 с с версией, сбрасывается при отправке, прочтении и смене состава (план) | T-8113 |
| `unread.COUNT_CACHE_SECONDS = 5` | константа кэша (план: «как `feed.services.unread`»; имя — факт ленты) | T-8113 test_cache_invalidated_by_send_read_and_membership_change |
| `unread.invalidate(user_ids)` | сброс кэша затронутых; `None` — всех (план) | T-8113; T-8126b |
| `live.publish(chat, action, message=None, owner=None, recipients=None)` | получатели `members(chat)` на момент рассылки; один рендер на класс (роль `author`/`reader` × `link_staff`) — не больше четырёх вариантов; одно сообщение слоя `messenger.event` в группы `messenger.u.{id}` через `publish` (`asyncio.gather`), ошибки — предупреждением в журнал `apps.messenger.services.live`; кадр `notify.html` в `notify.u.{id}` (план; имя — К10) | T-8114 test_recipients_snapshot_excludes_author_and_uses_current_members, test_fragment_rendered_once_per_role_and_link_staff_variant |
| `tasks.publish_event(chat_id, message_id, action, recipients=None, owner_id=None)` | ставится в очередь `notify` через `transaction.on_commit`; при удалении чата получатели передаются готовым списком; сбой постановки — предупреждение, сообщение сохранено (план) | T-8114 test_send_enqueues_publish_event_to_notify_queue_on_commit |
| `notify_rules.decide(chat, message, action) -> dict[int, tuple[str, Draft]]` | только `members(chat)` без автора и без уволенных; упомянутый человек (маркер, участник) — `messenger.mention`, остальным — `messenger.message`; одно сообщение — одно уведомление; правка и удаление уведомлений не создают (план) | T-8116a |
| `notify_rules.still_relevant(notification) -> bool` | перед письмом и сводкой: получатель всё ещё участник, чат виден (для общего — включён) и у получателя есть непрочитанные этого чата по тому же правилу, что счётчик; иначе письма нет (план; имя — К11) | T-8116b test_still_relevant_false_for_left_transferred_deleted_message_and_read_chat |

### 5.4. Файлы, поиск, срок, страница, настройки

| Функция | Сигнатура и поведение | Тесты |
|---|---|---|
| `files.upload(user, chat, data, name, have=()) -> MessageAttachment` | `core.uploads.reject_reason(name, data, size, max_file=20 МБ)`; `core.uploads.store(data, name, "messenger")`; строка `MessageAttachment(message=NULL)`; ранний отказ: 10 к сообщению (с учётом `have` и прикреплённых), 30 непривязанных у сотрудника (план; имя — К10) | T-8117a test_upload_20mb_ok_and_20mb_plus_byte_refused, test_31st_unbound_upload_refused |
| `files.bind(message, user, ids)` | условный `UPDATE … WHERE message_id IS NULL AND uploaded_by = <я>` с проверкой числа строк; меньше присланного — откат и «Файл не найден»; предел 10 под `select_for_update` (план) | T-8117a test_bind_uses_conditional_update_and_rolls_back_on_short_count |
| `files.remove(attachment, user)` | убрать непривязанный файл: строка и файл после фиксации; чужой или привязанный — 404 (план) | T-8117a test_remove_unbound_file_deletes_row_and_file_after_commit |
| `files.still_waiting(stored)`, `clean(stored)`, `found(stored, signature)` | назначение `messenger`: «ожидание» — строка есть; «чистый» — перенос в `attachments/` и эскиз `core.services.thumbs.build`; «карантин» — пометка, файл не отдаётся (план; имена — как у ленты) | T-8117b |
| `search.vectors(message_ids)` | литерал SQL с параметрами: `to_tsvector('russian', regexp_replace(text, '@\[[uc][0-9]{1,9}\]', ' ', 'g'))`; у удалённого и системного — пусто; пересчёт в транзакциях отправки, правки и удаления (план) | T-8118; T-8109a |
| `search.search(query, user, limit=…)`, `search.count(query, user)` | видимость в том же SQL: `EXISTS` строки `ChatMember` без выхода **или** `c.unit_id = ANY(%s)` (цепочка узлов) **или** (`kind='general'` и включён); стоп-слова отсеиваются `numnode`; `count` — с потолком 300 (план; имена — К10) | T-8118 test_search_sql_passes_words_and_unit_chain_as_parameters, test_count_ceiling_300 |
| `search.chat_search(chat, query)` | фрагмент поиска по беседе: только сообщения этого чата, доступные участнику; подсветка `ts_headline('russian', …)`, переход к `#m<id>`; содержимое файлов не ищется (план; имя — К10) | T-8118 test_chat_search_returns_only_its_messages_available_to_member |
| `retention.boundary(now, years)` | календарная граница `created_at < now − N лет` (год вычитается заменой года, 29 февраля → 28 февраля) (план; имя — К10) | T-8119 test_calendar_boundary_february_29_becomes_28 |
| `retention.run(now) -> int` | четыре идемпотентных шага: сообщения старше срока пачками по 1 000 (файлы, строки, диск после фиксации, пересчёт `last_message_at`); непривязанные `MessageAttachment` старше 24 часов; сброс кэша чисел; чаты отдела с несуществующим `unit_id`; журнал `messenger.retention_purged` — одна запись, только если удалено больше нуля; `VACUUM` не зовётся (план) | T-8119 |
| `page.chat_title(chat) -> str` | личный — ФИО собеседника, групповой — `title`, отдельский — имя узла через `unit_refs`, общий — «Общий чат» (план) | T-8108 test_personal_row_shows_peer_name_instead_of_title |
| `page.history(chat, before=None, limit=50)` | страница беседы и курсор `WHERE (created_at, id) < (%s, %s) ORDER BY created_at DESC, id DESC LIMIT 50`, без `OFFSET` (план; имя — К10) | T-8108 test_history_returns_50_then_50_then_20_by_cursor_without_gaps |
| `messenger_settings.get()` | строка `pk=1` (раздел 2.3) | T-8122 |
| `department`/`page`/`views` | удаление чата и файлов на каждом пути (создатель, администратор портала для отдела, удаление подразделения, выход последнего участника, ночное задание): в одной транзакции собрать пути, удалить строки, после фиксации стереть диск; получатели кадра удаления снимаются до каскада (план) | T-8105; T-8114 test_chat_delete_recipients_collected_before_cascade |

### 5.5. `MessengerConsumer` (`apps/messenger/consumers.py`, план)

| Что | Требование | Тесты |
|---|---|---|
| Примесь | `SessionGuardMixin` из `apps.core.ws`, `CHECK_INTERVAL = 25` (план; модульная константа подменяется тестом) | T-8115 |
| Подключение | проверка сессии (`guard_connect`; не «ok» — 4401); `chat` обязателен: нет параметра или не положительное целое (0, −1, `abc`, `01`, дробное) — `accept()`, затем `close(4400)` до `group_add`; проверка участия `members.get_chat` — чужой, несуществующий или удалённый чат — 4404; затем `group_add` в `messenger.u.{id}` | T-8115 test_connect_without_chat_zero_negative_or_text_closes_4400, test_foreign_and_missing_chat_close_4404, test_anonymous_no_second_factor_or_expired_session_close_4401 |
| Кадры | `messenger.event`: замена `#m<id>` (`outerHTML`), `beforeend:#messenger-messages` для нового, `hx-swap-oob="delete"` для удаления, замена `#messenger-read`, `#chat-<id>-unread`, `#chat-<id>-preview`, `#menu-badge-messenger`; `chat_delete` — `HX-Redirect` на `/messenger/`; кадры только для своего открытого чата | T-8115 test_new_edit_delete_frames_swapped_by_message_id, test_chat_delete_frame_sends_hx_redirect_to_list |
| Входящие | `{"sync": {"chat": id, "at": ISO}}` и `{"read": {"chat": id, "at": ISO}}`; сообщение не больше 4 КБ (больше — 1009); иные кадры игнорируются; ошибка слоя в потребителе — 1011; ошибка цикла проверки — 1013 | T-8115 test_client_message_over_4kb_closes_1009_and_other_frames_ignored, test_ws_state_error_in_loop_closes_1013, test_layer_error_in_consumer_closes_1011 |
| Без соединения | страница работает обычными запросами: список, беседа, отправка, правка, удаление, история, поиск; новое видно после обновления (план) | T-8115; T-8124 |

### 5.6. Точки подмены для тестов времени, слоя, ClamAV и очередей

| Точка | Как подменяется | Тесты |
|---|---|---|
| Часы | фикстура `clock` (`Clock` из `tests/factories.py`); службы берут `timezone.now()` один раз на действие | все с временем |
| Слой `publish` | `support_messenger.layer_down()` — `get_channel_layer("publish")` возвращает `None` либо слой с закрытым портом; `layer_spy()` — запоминает сообщения и группы без отправки | T-8114 test_layer_down_send_succeeds_fast_and_logs_warning |
| Очередь `notify` | `support_notify.run_jobs("notify")`; постановка проверяется `support_notify.queued(...)` (факт) | T-8114 test_queue_failure_keeps_message_and_logs_warning |
| ClamAV | `support_org.scan_clean`, `scan_found`, `scan_unavailable`; `support_messenger.attach(...)` берёт их же | T-8117b test_clamav_down_keeps_message_and_file_pending_for_retry |
| Кэш чисел | константа `COUNT_CACHE_SECONDS` и ключи версии; сброс — `unread.invalidate` | T-8113 |
| Замки и SQL | `capture_sql`, `support_kb.assert_for_update`; `django_db(transaction=True)` не используется | T-8108, T-8118, T-8119 |
| Сессия соединения | `apps.messenger.consumers.CHECK_INTERVAL` = малый интервал; `ws_state` — прежняя подмена `support_notify` | T-8115 |

### 5.7. Помощники `tests/support_messenger.py` (пишет T-8003; без `@pytest.fixture`, код среза — внутри функций)

| Имя | Сигнатура и поведение | Кто зовёт |
|---|---|---|
| `POINTS_008`, `PURPOSES_008`, `CHAT_KINDS` | `("unit_form_parts",)`; `("photo", "attachment", "knowledge", "lists", "feed", "messenger")`; `("personal", "group", "department", "general")` (строка T-8003) | T-8125, T-8126a, T-8102 |
| `MESSENGER_KINDS`, `MESSENGER_CODES`, `MESSENGER_TITLES` | `MESSENGER_KINDS` — кортеж из двух 8-кортежей формата `TABLE` из `test_notify_catalog.py` (код, название, модуль «Мессенджер», `order` 80/81, обязательность, каналы по умолчанию, события, внешний текст) по строкам 7.1; коды `("messenger.message", "messenger.mention")`; названия — по 7.1 | T-8116a, T-8116b |
| `AUDIT_CODES`, `MENU_008`, `JOBS_008` | шесть кодов плана (раздел 8); два пункта меню с `order` 1 и 64 (3.4); `{"messenger_retention": ("retention_night", "maintenance", None, "55 23 * * *", 600)}` (1.2) | T-8121, T-8120, T-8124 |
| `Session` | `NamedTuple(user, client)` (как `support_kb`) | все |
| `make_user(state="active")`, `as_admin() -> Session` | действующий сотрудник с паролем и клиентом; `as_admin` — держатель `settings.portal` (роль «Администратор портала», факт `support.ADMIN_ROLE`) | все |
| `unit(name, parent=None)` | узел `org` через `org.services.structure.create_unit` с актором-администратором (строка T-8003) | T-8106, T-8127 |
| `personal(a, b) -> Chat`, `group(creator, members, title="Группа") -> Chat`, `department_chat(unit) -> Chat`, `general() -> Chat` | прямые строки моделей (или службы, где нужны системные записи): личный — `pair_key`, групповой — участники и создатель, отдельский — `unit_id` и две системные записи, общий — `kind="general"` | все |
| `post(chat, author, text="Текст", quote=None, files=()) -> Message` | сообщение прямой записью; вектор — своим SQL (как `support_feed.make_post`); `files` — готовые `MessageAttachment` | все |
| `read(chat, user, at)` | строка `ChatRead` с указанным временем | T-8112, T-8113 |
| `attach(chat, name="схема.png", data=None, *, status="clean", uploaded_by=None, write=False, thumb=False)` | строки `StoredFile(purpose="messenger")` и `MessageAttachment`; `status` — `"pending"`, `"clean"`, `"quarantine"`; `write=True` пишет байты (фикстура `protected_root`); `thumb=True` пишет эскиз и заполняет `thumb`; ClamAV подменён (строка T-8003: `attach(chat)`) | T-8117a, T-8117b |
| `without_messenger()`, `run_seed(using=None, *, stand=False)` | раздел 4.4; `seed` миграции `messenger 0002` через `importlib` и реестр `django.apps.apps` | T-8122, T-8123, T-8125 |
| `run_retention(now) -> int`, `run_jobs(queue="notify")` | `tasks.retention_night(now)` синхронно; задания RQ — `support_notify.run_jobs` (строка T-8003) | T-8119, T-8114 |
| `ws_client(user, query="chat=<id>", *, hub=None, origin="http://testserver")` | корутина в сценарии `support_notify.ws_run`: свой `scope` (путь `/ws/messenger/`, `query_string` из `query`, кука сессии), `ApplicationCommunicator` над `support_notify._application()`, возвращает `WsClient` после ответа на `websocket.connect` (строка T-8003) | T-8115 |
| `layer_down()`, `layer_spy()` | раздел 5.6 | T-8114 |
| `capture_sql()`, `queries_with_params()` | как в `support_kb`; таблицы `messenger_chat`, `messenger_message`, `messenger_chatmember`, `messenger_chatread` | T-8108, T-8118 |
| `email_of`, `phone_of`, `moscow`, `moscow_text` | повторный экспорт из `support_kb` (как в `support_feed`) | T-8110, T-8111 |
| `images()` | словарь картинок в памяти: `"jpeg_exif"`, `"png_alpha"`, `"gif_frames"`, `"huge"` (> 40 Мп), `"broken"` (строка T-8003) | T-8117a, T-8117b |
| `messenger_pages()` | адреса страниц среза для проверок «по-русски» и «без `style=`»: `/messenger/`, `/messenger/chats/<id>/`, `/messenger/notifications/`, `/settings/messenger/` (строка T-8003; имя — К10) | T-8124 |

## 6. Места одной функции видимости

`members.get_chat` (и её SQL-двойник в поиске) — единственное место решения о доступе; каждое место ниже зовёт её или
то же правило; тест на место — T-8103 (`test_messenger_chats.py`), тест «тот же ответ» — `support.same_failure`
(404 как у несуществующего чата).

| № | Место | Функция / правило | Тест |
|---|---|---|---|
| V1 | список `/messenger/`, `/messenger/list/` | `visible_chats` / `chats.rows` | T-8103 test_visible_chats_for_employee_personal_group_department_chain_and_general |
| V2 | беседа `/messenger/chats/<id>/` | `get_chat` | T-8103 test_employee_outside_chat_cannot_open_message_edit_delete_read_or_search |
| V3 | история `/messenger/chats/<id>/messages/` | `get_chat` | T-8103 test_employee_outside_chat_cannot_open_message_edit_delete_read_or_search |
| V4 | поиск по беседе | `get_chat` | T-8118 test_chat_search_returns_only_its_messages_available_to_member |
| V5 | подсказка «@» | `get_chat` | T-8111 test_suggestion_hides_strangers_and_foreign_chats |
| V6 | отправка, правка, удаление | `get_chat`, затем `author_id` | T-8103 test_employee_outside_chat_cannot_open_message_edit_delete_read_or_search |
| V7 | отметка прочтения | `get_chat` | T-8103 test_get_chat_same_http404_for_missing_foreign_and_deleted |
| V8 | оригинал и эскиз файла | `get_chat` чата файла (непривязанный — только загрузившему) | T-8103 test_foreign_chat_file_and_thumb_answer_like_missing |
| V9 | сквозной поиск (выдача и число) | условие видимости в SQL поставщика | T-8103 test_search_does_not_show_foreign_chat_and_does_not_count_it |
| V10 | рассылка | `members(chat)` на момент рассылки | T-8103 test_live_recipients_and_still_relevant_use_same_membership |
| V11 | `still_relevant` уведомлений | `members` + `visible_chats` + непрочитанные | T-8103 test_live_recipients_and_still_relevant_use_same_membership |
| V12 | состав чата отдела и «Общего чата» | `department.members` / `members` | T-8103 test_members_of_department_chat_are_subtree_without_dismissed |
| V13 | администратор портала | тот же `get_chat`; чужой диалог — 404; удаление чужого сообщения эндпоинта не имеет | T-8103 test_admin_of_portal_gets_404_on_foreign_personal_dialog |

Исключения FR-669 названы явно и проверяют своё право отдельно: удаление группового чата создателем, пока он участник;
удаление чата отдела администратором портала; удаление чата при удалении подразделения; удаление при выходе последнего
участника; удаление по сроку хранения (план). Журнал пишется по FR-671, кроме выхода последнего участника.

## 7. Виды уведомлений и таблица «код вида → модуль»

### 7.1. Записи видов (`apps/messenger/notify_kinds.py`; план «Уведомления»)

Общее для двух видов: `module="Мессенджер"`, `events=()` (уведомления создаёт `notify_rules` прямым вызовом
`dispatch.create`), `mandatory=False`, `available` — истина каждому, `default_channels=("portal", "email")`,
`still_relevant` — `notify_rules.still_relevant` (5.3). Строки:

| `order` | Код | Название | Каналы по умолчанию | `coalesce` / `coalesce_text` | `external_text` |
|---|---|---|---|---|---|
| 80 | `messenger.message` | Новое сообщение в чате | `("portal", "email")` | `True` / `message_coalesce_text` | «Новое сообщение в чате» |
| 81 | `messenger.mention` | Упомянул вас в чате | `("portal", "email")` | нет | «Вас упомянули в чате» |

`order` — 80 и 81, после видов ленты (77) (план). Функция склейки — `apps.messenger.notify_kinds.message_coalesce_text(
user_id, object_ref, since) -> str` (имя — К12). Внешний текст постоянный: ни ФИО, ни названий, ни отрывков (NFR-705);
в системное окно браузера идёт текст портала — прежнее исключение SPEC-004 FR-317. Тесты T-8116a
test_two_kinds_with_titles_orders_channels_and_module; внешний текст каждого вида — T-8116c
test_external_text_has_no_names_or_message_text_in_telegram_max_and_push.

### 7.2. Черновики уведомлений (план, «Уведомления» → «Тексты»)

| Вид | `Draft.text` | `Draft.url` | `Draft.object_ref` |
|---|---|---|---|
| `messenger.message` | «<ФИО>: новое сообщение в чате «<название>»»; при склейке — «Новых сообщений: N в чате «<название>»» | `/messenger/chats/<id>/#m<id>` | `messenger.chat:<id>` |
| `messenger.mention` | «<ФИО> упомянул(а) вас в чате «<название>»» | `/messenger/chats/<id>/#m<id>` | `messenger.chat:<id>` |

Подробности: «<ФИО>» — полное ФИО действующего; «<название>» — `page.chat_title(chat)` (у личного — ФИО собеседника,
поэтому в портале допустимо); отрывок сообщения в уведомление **не** кладётся (план: меньше ПДн, спека отрывка не
требует); при склейке N — сообщения того же чата после `since`; ключ склейки — `(получатель, вид, object_ref)`, поэтому
все сообщения одного чата до прочтения — одно уведомление (FR-666, образец FR-629). Номер сообщения вид не получает:
`object_ref` — только чат, «сообщение живо» проверяется ссылкой (удалённое даёт 404). Тесты T-8116a
test_texts_of_message_and_mention_are_russian, test_three_messages_coalesce_into_one_with_count, test_mentioned_gets_only_mention_not_message.

### 7.3. Почта, тихие часы, `still_relevant`

Портал — сразу; письмо — по `email_delay_minutes` (`notify.models.NotifySettings`, по умолчанию 15); тихие часы
действуют на почту и внешние каналы; накопленное уходит сводкой с началом рабочего дня (ADR-0011 п. 6, FR-663).
Сотрудник отключает почту и внешние каналы в «Моих уведомлениях» (FR-665); портал приходит всегда. `still_relevant` —
5.3. Правила задержки, тихих часов и сводки — CONTRACT-004 (6.6, 6.9, 6.11) без изменений; мессенджер их не переписывает
и проверяет только своими тестами T-8116c test_email_sent_after_fifteen_minutes_if_unread,
test_quiet_hours_hold_email_and_send_digest_at_workday_start, test_portal_always_on_even_with_all_channels_off.

### 7.4. Таблица «код вида → модуль» (порядок каталога — по `order`)

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
| 70…77 | `feed.for_you` … `feed.like` | CONTRACT-007, 7.1 | Лента |
| 80 | `messenger.message` | Новое сообщение в чате | Мессенджер |
| 81 | `messenger.mention` | Упомянул вас в чате | Мессенджер |
| 110 | `core.new_device` | Вход с нового устройства | Ядро |
| 120 | `core.password_changed` | Пароль изменён | Ядро |
| 130 | `core.second_factor_reset` | Второй фактор сброшен | Ядро |
| 200 | `notify.channel_unbound` | Канал отвязан | Уведомления |

Строки, кроме `messenger.*`, — CONTRACT-007, 7.3 (факт после среза 007); строки `messenger.*` — план. Итого двадцать два
вида семи модулей. «Мои уведомления» показывают две строки «Мессенджер» каждому сотруднику, у обеих есть почта и внешние
каналы. Тесты T-8116a, T-8116b test_catalog_has_22_kinds_and_two_messenger_rows, test_my_notifications_lists_two_rows_with_email_and_external_channels.

## 8. Журнал (план, «Журнал»)

### 8.1. Коды, типы, ключи

| Код действия | Когда | Объект | Было / стало |
|---|---|---|---|
| `messenger.chat_deleted` | создатель удалил групповой чат | `messenger.chat`, номер | `chat_title` — название, `chat_members` — число участников, `chat_created_at` — время создания; без текста |
| `messenger.department_chat_deleted` | администратор портала удалил чат отдела | `messenger.chat`, номер | `chat_title` — название отдела, `unit_id` — номер узла; без текста |
| `messenger.unit_chat_deleted` | удалено подразделение с чатом | `messenger.chat`, номер | `chat_title`, `unit_id`; без текста |
| `messenger.general_changed` | включён или выключен «Общий чат» | `messenger.settings` | «включён» / «выключен» |
| `messenger.retention_changed` | изменён срок хранения | `messenger.settings` | `years` — было / стало |
| `messenger.retention_purged` | ночное задание удалило сообщения | `messenger.settings` | `messages` — число, подпись «Удалено по сроку, сообщений» |

Обычные сообщения, правки и удаления автором в журнал не пишутся (это содержимое переписки, FR-671). Ключи «было /
стало» — `chat_title`, `chat_members`, `chat_created_at`, `unit_id`, `years`, `messages` (решение контракта К13:
префикс `chat_` не даёт столкнуться с ключами `feed`; `years` и `messages` — новые либо совпадают по смыслу с прежними и
не меняют чужие подписи). Журнал только дополняется: роль приложения не имеет `UPDATE` и `DELETE` на его таблицу — тот
же тест прав, что SPEC-006 NFR-508 (NFR-709). Тесты T-8121 test_six_codes_written_without_message_text,
test_chat_deleted_records_title_members_and_created_at_only, test_retention_purged_records_count_only,
test_ordinary_send_edit_delete_are_not_audited, test_application_role_has_no_update_or_delete_on_audit_table.

### 8.2. Подписи (`apps/messenger/audit_labels.py`)

| Часть словаря | Значения |
|---|---|
| `actions` | `messenger.chat_deleted` — «Групповой чат удалён»; `messenger.department_chat_deleted` — «Чат отдела удалён администратором»; `messenger.unit_chat_deleted` — «Чат удалён вместе с подразделением»; `messenger.general_changed` — «Общий чат включён или выключен»; `messenger.retention_changed` — «Срок хранения сообщений изменён»; `messenger.retention_purged` — «Сообщения удалены по сроку» (тексты — решение контракта К14) |
| `fields` | `chat_title` — «название чата», `chat_members` — «участников», `chat_created_at` — «создан», `unit_id` — «номер подразделения», `years` — «срок хранения, лет», `messages` — «Удалено по сроку, сообщений» |
| `object_types` | `messenger.chat` — «чат мессенджера», `messenger.settings` — «настройки мессенджера» |
| `values` | пусто: «включён»/«выключен» и числа служба пишет по-русски (как у ленты) |

Словарь сливается ядром с подписями прежних модулей; ключей `chat_title`, `chat_members`, `chat_created_at`, `unit_id`,
`messages` в общем словаре нет (факт после среза 007 — поля `feed` и `lists`), `years` уже есть с тем же смыслом и
подписью «срок хранения, лет» — совпадение не меняет чужую подпись (решение контракта К14). Функция —
`audit_labels() -> {"actions", "fields", "object_types", "values"}`; модели не импортируются. Тесты T-8121
test_labels_of_actions_and_object_types_are_russian; T-8124 test_texts_are_russian_and_time_is_moscow_at_utc_midnight.

## 9. Поиск (план, «Поиск»; FR-668, NFR-703)

| Что | Требование | Тесты |
|---|---|---|
| Провайдер | `SearchProvider(key="messenger", title="Мессенджер", order=61, search=search, count=count, available=<истина>)` — после «Ленты» (60); без мессенджера группы нет | T-8118 test_provider_order_61_after_feed_and_group_title, test_without_messenger_no_group |
| Векторы | `to_tsvector('russian', regexp_replace(text, '@\[[uc][0-9]{1,9}\]', ' ', 'g'))` — литерал SQL с параметрами; у удалённого и системного пусто; пересчёт в отправке, правке и удалении | T-8118 test_deleted_and_old_edited_text_not_found; T-8109a |
| Видимость | в том же SQL: `EXISTS` строки `ChatMember` без выхода **или** `c.unit_id = ANY(%s)` (цепочка узлов параметром-массивом) **или** (`kind='general'` и включён); без `apps.org` отдельских чатов нет | T-8118 test_word_in_foreign_chat_absent_and_not_counted, test_search_sql_passes_words_and_unit_chain_as_parameters |
| Строка выдачи | `<название чата>, <ФИО>, <дата по Москве> — <отрывок 100>`; адрес `/messenger/chats/<id>/#m<id>`; группа разметки — `section[data-search-group="messenger"]` (12.6) | T-8118 test_word_in_own_chat_found_with_chat_author_time_and_snippet |
| Слова и стоп-слова | слова запроса — параметрами; стоп-слова отсеиваются `numnode` (как в ленте); пусто — без ошибки | T-8118 test_stop_word_gives_empty_without_error |
| Потолок | `count` — с потолком 300 | T-8118 test_count_ceiling_300 |
| Поиск по беседе | `GET /messenger/chats/<id>/search/?q=` — фрагмент: только сообщения этого чата и доступные участнику, подсветка `ts_headline('russian', …)`, переход к `#m<id>`; содержимое файлов не ищется | T-8118 test_chat_search_returns_only_its_messages_available_to_member |
| Маркеры | маркеры `@[u…]`/`@[c…]` не ломают поиск (заменяются пробелом до вектора) | T-8118 test_mention_markers_do_not_break_search |

## 10. Маршруты, поля форм, ответы

Адреса, методы и «кто» — план («Контракты»); здесь — поля форм, параметры, форма ответа и коды. Имена маршрутов
(`app_name = "messenger"`) выбирает исполнитель; тесты ходят по путям (план; решение контракта К15). Прежнее имя
`notify-list` сохраняется; новые имена `notify` — на усмотрение исполнителя T-8218.

| Путь | Метод | Кто | Что возвращает | FR |
|---|---|---|---|---|
| `/messenger/` | GET | вошедший; `?to=<id>` — адресат | страница: список чатов (`q`), поле ввода (при `to` — с адресатом), вкладки «Чаты»/«Уведомления»; на широком экране — первый чат или пустая область | 644, 645, 673 |
| `/messenger/list/` | GET | вошедший | фрагмент списка: название, превью, время, счётчик; `q` — поиск по названию и ФИО | 644, 660 |
| `/messenger/chats/` | POST (`kind=personal\|group`, `user`, `title`, `members`) | вошедший | создание личного или группового чата; успех — переход в беседу; отказ — причина у поля | 645, 646 |
| `/messenger/chats/<id>/` | GET | участник | беседа: шапка, история 50, поле ввода, узел соединения `/ws/messenger/?chat=<id>`, «Прочитали N из M» у последнего своего | 644, 658, 659, 673 |
| `/messenger/chats/<id>/messages/` | GET (`before=<ISO>,<id>`) | участник | фрагмент: предыдущие 50 сообщений (курсор), кнопка «Показать более ранние» | 658 |
| `/messenger/chats/<id>/messages/` | POST (`text`, `quote`, `files`) | участник | отправка; успех — сообщение внизу и очищенное поле; отказ — причина у поля | 652, 653, 654, 662 |
| `/messenger/messages/<mid>/edit/` | POST (`text`) | автор, сообщение живо | правка на месте, пометка «изменено» | 656 |
| `/messenger/messages/<mid>/delete/` | POST | автор | «Сообщение удалено» со временем; файлы недоступны | 657 |
| `/messenger/chats/<id>/members/` | POST (`add`, `remove`) | создатель, пока в чате | состав группового чата; после выхода создателя — 403 | 646 |
| `/messenger/chats/<id>/leave/` | POST (`confirm=1`) | участник | выход; последний участник — удаление чата с подтверждением | 647 |
| `/messenger/chats/<id>/delete/` | POST (`confirm=1`) | создатель группового (участник) или `settings.portal` для отдела | удаление чата с историей; журнал без текста | 648, 672, 671 |
| `/messenger/chats/<id>/read/` | POST (`at`) | участник | отметка прочтения; узел числа чата, общее число, «Прочитали N из M» | 659, 660 |
| `/messenger/chats/<id>/search/` | GET (`q`) | участник | фрагмент: сообщения беседы с подсветкой и якорем `#m<id>` | 668 |
| `/messenger/mentions/` | GET (`chat`, `q`) | участник | подсказка «@» до 20 строк: участники чата и свои чаты; в личном — пусто | 655 |
| `/messenger/people/` | GET (`q`) | вошедший | до 20 действующих сотрудников (ФИО, подразделение) с действием «Написать» → `/messenger/?to=<id>`; пустой `q` — подсказка «начните вводить имя» | 645 |
| `/messenger/files/` | POST (multipart, nginx 25m, до 20 МБ) | вошедший | «таблетка» файла со скрытым `files=<id>` или причина отказа (10 к сообщению, 30 непривязанных) | 662 |
| `/messenger/files/<id>/delete/` | POST | загрузивший, файл не привязан | убрать файл до отправки | 662 |
| `/messenger/files/<id>/` | GET | участник чата файла; файл «чистый» | оригинал: картинка — показом, прочее — вложением; `X-Accel-Redirect` | 662, 669 |
| `/messenger/files/<id>/thumb/` | GET | то же; эскиз есть | эскиз ≤ 1280 px; `X-Accel-Redirect` | 662 |
| `/messenger/notifications/` | GET (`f`, `page`) | вошедший | страница с вкладкой «Уведомления»; первая страница потока — серверный рендер, смена страницы и фильтра — фрагмент `/notifications/list/` | 667 |
| `/notifications/` (notify) | GET | вошедший | 302 на `/messenger/notifications/` с `f` и `page` (без мессенджера — прежняя страница) | 667 |
| `/notifications/list/` (notify, новый) | GET (`f`, `page`) | вошедший | фрагмент потока: 50 на страницу, фильтр, «Прочитать все», страницы | 667 |
| `/settings/messenger/` | GET, POST | `settings.portal` | срок хранения 1–10 (при уменьшении — число к удалению и подтверждение), «Общий чат»; журнал «было / стало» | 651, 670, 671 |
| `/ws/messenger/?chat=<id>` | WebSocket | вошедший после второго фактора, Origin из `ALLOWED_HOSTS`, сессия по `ws_state` (раз в 25 с; не «ok» — 4401); `chat` обязателен (нет/не целое — 4400), только участник (чужой/несуществующий — 4404) | кадры `hx-swap-oob`: сообщение (новое/правка/удаление), «Прочитали N из M», число чата, превью, `#menu-badge-messenger`; удаление чата — `HX-Redirect`; от клиента — JSON `{"sync": …}` и `{"read": …}` (≤ 4 КБ, больше — 1009) | 659, 660, 661 |

Итого 24 строки: 23 HTTP-запроса к 22 адресам (у `/messenger/chats/<id>/messages/` — GET и POST) и одно соединение
WebSocket. Двадцать адресов принадлежат `messenger`, два (`/notifications/`, `/notifications/list/`) — `notify`.

### 10.1. Общие правила

| Что | Требование | Тесты |
|---|---|---|
| Вход | все адреса — `@login_required`: без входа GET и POST — 302 на `/login/?next=<путь>`; без второго фактора — прежние промежуточные слои ядра; `/settings/messenger/` — ещё и `settings.portal` (403 без него на GET и POST, без обращения к `messenger_settings`) | T-8103; T-8120 test_page_requires_settings_portal_403 |
| Запрос HTMX | заголовок `HX-Request: true`; ответ — фрагмент без `<html>` | T-8109a, T-8115 |
| Отказ службы на POST | 200 с формой или фрагментом, введённое остаётся; отказ у поля — `[data-error="<поле>"][data-code="<код>"]` рядом с полем, общий отказ — `[role=alert][data-code="<код>"]` (соглашение срезов 001–007, CONTRACT-006/007, 10.1); `<поле>` — имя поля 10.2 (`text`, `title`, `members`, `user`, `quote`, `files`, `file`, `chat`, `retention_years`, `at`); коды — ключи раздела 13 | все тесты отказов |
| Успех POST | обычный POST — 302 на адрес из 10.2; HTMX-POST — 200 с фрагментом из 10.2 | T-8109a, T-8109b |
| 403, 404 | раздел «Правила для всех тестов среза»: чужой, несуществующий и удалённый чат — 404 страницы «Не найдено»; чат виден, действие не разрешено — 403 (состав после выхода создателя, удаление чата отдела участником, правка/удаление чужого сообщения, `settings/messenger/` без права); администратор портала чужой диалог не видит — 404 | T-8103, T-8105, T-8106 |
| Выключенный «Общий чат» | исчезает из списка и поиска; прямой адрес — 404; обычный POST отправки — 404; HTMX — 200 с причиной `chat_disabled` у поля (план) | T-8107 |
| Номера | `<int:…>` в путях; литеральные `list/`, `mentions/`, `people/`, `files/`, `notifications/` не путаются с `<id>/` (план) | T-8108 |
| Метод | GET на адрес только для POST — 405, как `require_POST` прежних срезов | T-8115 |
| Время в адресе | `before=<ISO>,<id>` (UTC, `datetime.isoformat()`; `+` кодируется `%2B`), `at=<ISO>`; неверное значение — как отсутствующее (первая страница, `at` — `now`) | T-8108; T-8112 |
| Ключи списка | `q`, `to`, `before`, `f`, `page`, `chat` — белый список; всё прочее отбрасывается (план) | T-8108 test_filter_q_by_title_and_peer_name_passes_values_as_parameters |

### 10.2. Поля форм и ответы по адресам

| Адрес | Поля и параметры | Успех | Отказ и прочее |
|---|---|---|---|
| `/messenger/` GET | `q`, `to` (номер сотрудника); вкладки — `[data-messenger-tab]` (12.2) | страница: список, поле ввода (при `to` — адресат), вкладки; на широком экране первый чат | `to` не существует/уволен — 200 без адресата; пустой список — подсказка «Чатов пока нет: напишите коллеге из карточки сотрудника» |
| `/messenger/list/` GET | `q` | фрагмент `#messenger-list` строк `#chat-<id>-unread`, `#chat-<id>-preview` | пустой `q` — все; совпадений нет — пустой фрагмент и подсказка «Ничего не найдено» |
| `/messenger/chats/` POST | `kind` (`personal` по умолчанию, `group`), `user` (для личного), `title`, `members` (несколько, для группового) | обычный — 302 в `/messenger/chats/<id>/`; HTMX — 200 с беседой | `title` пуст/201 знак — `[data-error="title"][data-code="title_range"]`; нет участников — `members`, `no_members`; уволенный — `user`/`members`, `dismissed` |
| `/messenger/chats/<id>/` GET | — | беседа: шапка (название, участники), поиск по беседе, история 50, поле ввода, узел `/ws/messenger/?chat=<id>`, `#messenger-read` | 404 невидимого; кнопка «Назад» на `/messenger/` — разметка 12.3 |
| `/messenger/chats/<id>/messages/` GET | `before=<ISO>,<id>`, `chat` | фрагмент предыдущих 50 (`hx-swap="afterbegin"`), кнопка «Показать более ранние»; нет старых — кнопки нет | неверный `before` — первая страница; чужой чат — 404 |
| `/messenger/chats/<id>/messages/` POST | `text`, `quote`, `files` (несколько номеров) | обычный — 302 на `/messenger/chats/<id>/`; HTMX — 200: сообщение `#m<id>` внизу и очищенное поле | `text` пуст/пробелы — `text`, `empty_text`; 4 001 — `text`, `too_long`; цитата другого чата/несуществующая — `quote`, `message_missing`; 21 упоминание — `text`, `mentions_limit`; 11-й файл — `files`, `files_limit`; чужой непривязанный файл — `files`, `file_missing`; чат отключён — `chat`, `chat_disabled` (HTMX) или 404 (обычный POST) |
| `/messenger/messages/<mid>/edit/` POST | `text` | HTMX — 200: сообщение `#m<id>` с `[data-messenger-edited]`; обычный — 302 на беседу | не автор — 403 при видимом чате; удалённое/несуществующее — 404; пусто/4 001 — как отправка |
| `/messenger/messages/<mid>/delete/` POST | — | HTMX — 200: серая запись «Сообщение удалено» на месте `#m<id>` со временем; live-кадр другим — `hx-swap-oob="delete"` (11.3); обычный — 302 на беседу | не автор — 403; чужой чат/удалённое — 404 |
| `/messenger/chats/<id>/members/` POST | `add`, `remove` (несколько номеров) | HTMX — 200: состав чата; обычный — 302 на беседу | создатель вышел — 403; уволенный/неучастник — причина у поля; не групповой чат — 403 |
| `/messenger/chats/<id>/leave/` POST | `confirm=1` | обычный — 302 на `/messenger/`; последний участник — удаление чата после подтверждения | без `confirm` у последнего — 200 со вторым шагом `[data-messenger-confirm]` и текстом «Удалить чат вместе с историей?»; не участник — 404 |
| `/messenger/chats/<id>/delete/` POST | `confirm=1` | обычный — 302 на `/messenger/`; журнал без текста | создатель группового после выхода/не создатель — 403; админ отдела без `settings.portal` — 403; без `confirm` — 200 со вторым шагом; чужой чат — 404 |
| `/messenger/chats/<id>/read/` POST | `at` (ISO) | HTMX — 200: `#chat-<id>-unread` (`hx-swap-oob`), `#menu-badge-messenger`, `#messenger-read`; обычный — 302 на беседу | `at` в будущем — обрезается до `now`; неверный `at` — как отсутствующий; чужой чат — 404 |
| `/messenger/chats/<id>/search/` GET | `q` | фрагмент: сообщения беседы с подсветкой и якорем `#m<id>`; пусто — «Ничего не найдено» | чужой чат — 404 |
| `/messenger/mentions/` GET | `chat`, `q` | фрагмент до 20 строк `[data-mention-value]`; в личном — пусто; `q` короче двух знаков — пусто | чужой чат — 404 |
| `/messenger/people/` GET | `q` | фрагмент до 20 действующих сотрудников `[data-person-id]` с действием «Написать» → `/messenger/?to=<id>` | пустой `q` — подсказка «начните вводить имя»; уволенные не показываются |
| `/messenger/files/` POST | `file` (multipart), `chat`, `have` (несколько номеров своих непривязанных) | 200: таблетка `[data-messenger-file="<id>"]` со скрытым `input[name="files"][value="<id>"]` и крестиком | 200 с `[data-error="file"][data-code="<код>"]`: больше 20 МБ — `file_too_big`; исполняемый/архив с паролем/больше 40 Мп — `file_type`; 10 к сообщению — `files_limit`; 30 непривязанных — `too_many_unbound` |
| `/messenger/files/<id>/delete/` POST | — | 200 с пустым телом | не свой или привязанный — 404 |
| `/messenger/files/<id>/`, `/messenger/files/<id>/thumb/` GET | — | оригинал: картинка — `inline_image`, прочее — `download`; эскиз — `X-Accel-Redirect: /protected/attachments/thumbs/<имя>`; везде `X-Content-Type-Options: nosniff`, `Cache-Control: no-store` | 404: невидимый чат — «Не найдено»; «проверяется» — «Файл ещё проверяется»; «карантин» — «Файл в карантине»; непривязанный — только загрузившему; «чистый» без эскиза у `/thumb/` — «Не найдено» |
| `/messenger/notifications/` GET | `f` (`""` — все, `unread`), `page` | страница с вкладкой «Уведомления»; первая страница потока — серверный рендер `notify/_list_body.html` | неверный `page` — первая или последняя; без JS вкладка работает |
| `/notifications/` GET | `f`, `page` | 302 на `/messenger/notifications/?f=…&page=…` (пустые ключи не добавляются) | без мессенджера — прежняя страница 200 |
| `/notifications/list/` GET | `f`, `page` | фрагмент потока: 50 записей, строки `_row.html`, фильтр, «Прочитать все», страницы | — |
| `/settings/messenger/` GET, POST | `retention_years`, `general_chat_enabled`, `confirm=1` | сохранение — 302 на `/settings/messenger/`; увеличение срока сохраняется сразу; журнал «было / стало» | вне 1–10, не число, пусто — `[data-error="retention_years"][data-code="retention_range"]`; уменьшение без `confirm` — 200 со вторым шагом `[data-messenger-confirm]` («Ближайшее ночное задание удалит сообщений: N», кнопка «Подтвердить» `button[name="confirm"][value="1"]`, скрытое `retention_years`); без `settings.portal` — 403 |
| `/ws/messenger/?chat=<id>` | строка запроса `chat`; входящие `{"sync": …}`, `{"read": …}` | кадры раздела 11.3 | 4400/4404/4401/1009/1011/1013 — раздел 11.4 |

## 11. Слой каналов: сообщения, кадры, коды закрытия (план «Живые обновления и рассылка», «Контракты»)

### 11.1. Сообщения слоя и группы

| Что | Требование | Тесты |
|---|---|---|
| Группы | `messenger.u.{id}` — личная группа соединений беседы; `notify.u.{id}` — колокольчик (`notify.services.live.group`) (план) | T-8115; T-8114 |
| `messenger.event` | `{"type": "messenger.event", "chat": int, "action": "new" \| "edit" \| "delete" \| "read" \| "chat_delete" \| "chat", "message": int \| None, "owner": int \| None, "counts": {int: int}, "total": int, "variants": {"<роль>:<0\|1>": str}, "meta": {"created_at": ISO}}` (план); `owner` — автор действия; `counts` — числа непрочитанных по чатам у каждого получателя, `total` — общее число; `message` пусто у действий без сообщения (решение контракта К16) | T-8114 test_one_layer_message_contains_counts_total_and_variants |
| Ключи `counts` | ключи — номера сотрудников; в JSON-транспорте слоя они становятся строками; тесты приводят ключи к `int`, значения — к `int` (решение контракта К16) | T-8114 |
| Ключи `variants` | роль — `author`, `reader`; `0`/`1` — признак `link_staff`; ключей не больше четырёх, только классы, которые есть среди получателей (план) | T-8114 test_fragment_rendered_once_per_role_and_link_staff_variant |
| Выбор варианта | `owner == я` → `author`, иначе `reader`; признак — показывать ли ссылки на карточки сотрудников (`link_staff`, как у ленты) | T-8114 |
| `action` по действию | отправка — `new`; правка — `edit`; удаление сообщения — `delete`; отметка прочтения — `read`; удаление чата — `chat_delete`; создание/смена состава — `chat` (план) | T-8114; T-8115 |
| `notify.html` | `{"type": "notify.html", "html": str}` в `notify.u.{id}` — готовый фрагмент `_badge.html` (`<span id="menu-badge-messenger" hx-swap-oob="true" …>`) и OOB-фрагменты затронутых строк списка (`#chat-<id>-unread`, `#chat-<id>-preview`), отрендеренные под числа получателя (план) | T-8114 test_badge_and_row_fragments_go_to_personal_notify_group |
| Размер | кадр — единицы КБ; входящее сообщение клиента — не больше 4 КБ (план) | T-8115 |

### 11.2. Сообщения клиента по `/ws/messenger/` (план)

| Сообщение | Требование | Тесты |
|---|---|---|
| `{"sync": {"chat": int, "at": ISO}}` | на каждое открытие, в том числе после переподключения; всегда отвечает служебным кадром `#messenger-synced`, после которого клиент ставит `data-ws="open"` | T-8115 |
| `{"read": {"chat": int, "at": ISO}}` | сервер отмечает прочтение и рассылает автору кадр «Прочитали N из M» (FR-659) | T-8115 test_read_message_updates_read_line_for_author |
| Пределы | сообщение больше 4 КБ — закрытие 1009; неизвестные кадры, неверные номера и время игнорируются без ошибки сервера | T-8115 test_client_message_over_4kb_closes_1009_and_other_frames_ignored |

### 11.3. Кадры (готовые фрагменты HTML с `hx-swap-oob`, план)

| Кадр | Разметка | Тесты |
|---|---|---|
| Новое сообщение | `<div hx-swap-oob="beforeend:#messenger-messages">` с сообщением `id="m<id>"`; в кадре — `data-message-id` и `data-own` (`0`/`1`, решение контракта К17) | T-8115 test_new_edit_delete_frames_swapped_by_message_id |
| Правка | сообщение `id="m<id>"` с `hx-swap-oob="outerHTML"` и пометкой «изменено» | T-8115 |
| Удаление сообщения | `<div id="m<id>" hx-swap-oob="delete"></div>` у получателей живого кадра (план); серая запись «Сообщение удалено» со временем — в ответе автора и при следующем открытии беседы | T-8115 |
| «Прочитали N из M» | `#messenger-read` с `hx-swap-oob="true"` | T-8115 |
| Число чата и превью | `#chat-<id>-unread` и `#chat-<id>-preview` — OOB-замена; `data-count` у числа | T-8114; T-8115 |
| Число пункта меню | `#menu-badge-messenger` с `hx-swap-oob="true"` (сообщение `notify.html` по `/ws/notify/`) | T-8114 |
| Удаление чата | `HX-Redirect: /messenger/` (чат исчез у всех) | T-8115 test_chat_delete_frame_sends_hx_redirect_to_list |
| Служебный | `<div id="messenger-synced" hx-swap-oob="true"></div>` (план) | T-8115 |
| Запреты | в кадре нет `<form`, `csrfmiddlewaretoken`, `<script`, `style=`, `on…=`; кнопки действий — `hx-post` без формы (токен добавляет `static/js/htmx-glue.js`); значения пользователя экранированы | T-8115 test_frame_has_no_csrf_token |

### 11.4. Коды закрытия

| Код | Когда | Тесты |
|---|---|---|
| 4400 | `chat` отсутствует или не положительное целое (0, −1, `abc`, `01`, дробное), после `accept()` и до `group_add` | T-8115 |
| 4404 | чат невидим, не существует или удалён (`get_chat`) | T-8115 |
| 4401 | `ws_state` не «ok» при подключении или в цикле проверки (выход, выход со всех устройств, блокировка, увольнение, бездействие, истёкший пароль) | T-8115 |
| 1009 | входящее сообщение больше 4 КБ | T-8115 |
| 1011 | ошибка слоя каналов в потребителе | T-8115 |
| 1013 | ошибка в цикле проверки сессии | T-8115; T-8126a |

При закрытии сервером кодами 1012 и 1006 (перезапуск, обрыв) htmx-ext-ws переподключается сам; сбой Valkey рвёт
открытые соединения (1006) и они возвращаются сами (до 64 с) (план).

## 12. Зацепки `data-*` и `id` для приёмки

Правила: только `data-*`, `id` и классы, которых нет у прежних блоков; без `role="status"`, `role="alert"`, `data-error`,
`data-warning` вне сообщений об отказах форм; без `style=` и `on…=`. Названы планом или задачами и потому обязательны:
`#m<id>`, `#chat-<id>-unread`, `#chat-<id>-preview`, `#menu-badge-messenger[data-count]`, `#messenger-messages`,
`#messenger-read`, `#messenger-synced`, `[data-ws]`, `[data-mention]`, `[data-bell-link]`, `data-message-id`. Прочие
зацепки — решение контракта К17.

### 12.1. Общие

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `[data-messenger-page="<имя>"]` | корень содержимого: `list` (список и вкладки), `chat` (беседа), `notifications` (вкладка), `settings`, `write` (`?to=`) | T-8130…T-8143 |
| `time[data-at]` | время по Москве, `datetime` — ISO, текст «ДД.ММ.ГГГГ ЧЧ:ММ» | T-8124; T-8118 |
| Пометка «уволен» | ФИО уволенного — с текстом «(уволен)» и `span[data-dismissed="true"]` (прежний `{% person_name %}`) | T-8104; T-8117a |
| Отказы | `[data-error="<поле>"][data-code="<код>"]`, `[role=alert][data-code="<код>"]` (10.1) | все тесты отказов |
| Пустые состояния | `[data-empty-state="messenger"]` — «Чатов пока нет: напишите коллеге из карточки сотрудника»; `[data-empty-state="messenger-search"]` — «Ничего не найдено» | T-8108 |

### 12.2. Список, меню, вкладки

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `#messenger-list` | список чатов (`ol`/`ul`), строки — `[data-chat-id="<id>"]` | T-8108; T-8138 |
| `#chat-<id>-unread[data-count]` | число непрочитанных у чата; текст — цифры при `≤ 99`, «99+» при `> 99`; при 0 узел остаётся с `data-count="0"` и классом `d-none` (решение контракта К18) | T-8113; T-8138 |
| `#chat-<id>-preview` | превью последнего неудалённого сообщения (`snippet` 100) | T-8108; T-8138 |
| `#menu-badge-messenger[data-count]` | число пункта меню; узел всегда, `d-none` при 0, «99+» выше 99; `data-menu-live-badge` (как у ленты) | T-8113; T-8138 |
| `[data-messenger-tab="chats\|notifications"]` | вкладки страницы; выбранная — `aria-selected="true"`; адреса `/messenger/` и `/messenger/notifications/` | T-8116b; T-8139 |
| `[data-chat-kind]` | вид чата у заголовка беседы (`personal`, `group`, `department`, `general`) | T-8108 |

### 12.3. Беседа, сообщения, прочтение

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `#messenger-messages` | контейнер истории; новые — `beforeend`, старые — `afterbegin` | T-8108; T-8131 |
| `article#m<id>[data-message-id="<id>"]` | сообщение; `data-own="0\|1"`; `time[data-at]`; автор; цитата — `[data-quote-id]` с текстом цитаты или «Сообщение удалено» | T-8109a; T-8109b; T-8135 |
| `[data-messenger-edited]` | пометка «изменено» у правленого сообщения | T-8109a |
| `[data-messenger-deleted]` | серая запись «Сообщение удалено» со временем; текста и файлов нет | T-8109a |
| `#messenger-read` | «Прочитали N из M» у последнего своего сообщения; у остальных своих — узла нет | T-8112; T-8138 |
| `#messenger-form` | форма отправки: `textarea[name="text"]`, `input[type="file"][data-messenger-upload]`, скрытое `input[name="quote"]`, скрытые `input[name="files"]` | T-8109a; T-8130 |
| `[data-quote]` | цитата в поле ввода с крестиком `button[data-action="quote-remove"]` | T-8109b; T-8135 |
| `[data-messenger-mention-list]`, `[data-mention-value]` | подсказка «@»: строка значения и подпись; выбор виден в поле как `@ФИО`/`#название`, на сервер уходит маркер | T-8111; T-8136 |
| `[data-messenger-search]` | поиск по беседе (GET, `q`) | T-8118; T-8140 |
| `[data-messenger-back]` | кнопка «Назад» на `/messenger/` (до 900 px) | T-8142 |

### 12.4. Соединение беседы

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `[data-ws]` | узел соединения беседы с `hx-ext="ws"`, `ws-connect="/ws/messenger/?chat=<id>"`; `data-ws`: `connecting` при отрисовке, `open` — после `#messenger-synced`, `closed` — по `htmx:wsClose` (решение контракта К19: отдельного `id` контракт не требует, тесты ищут `[data-ws]` и `#messenger-synced`) | T-8108 test_chat_page_has_header_input_and_ws_node_with_chat_id; T-8138 |
| `#messenger-synced` | служебный кадр после `sync` | T-8115 |
| Соединений на странице | одно `/ws/messenger/` (беседа) и прежний `/ws/notify/` (колокольчик в оболочке); список своего соединения не открывает | T-8108; T-8113 |

### 12.5. Файлы

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `[data-messenger-file="<id>"][data-file-state="pending\|clean\|quarantine"]` | файл сообщения: «проверяется» — имя и пометка без ссылки; «карантин» — имя и пометка без ссылки; «чистый» картинка — `a[href="/messenger/files/<id>/"] > img[src="/messenger/files/<id>/thumb/"]`; иначе имя, размер и «Скачать» | T-8117b |
| `[data-messenger-file="<id>"]` (таблетка) | скрытое `input[name="files"]`, крестик `button[data-action="file-remove"]` | T-8117a; T-8130 |
| `[data-messenger-upload]` | `input[type="file"]` формы | T-8130 |

### 12.6. Уведомления, поиск, карточка, форма узла, настройки

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `[data-bell-link][href="/messenger/notifications/"]` | колокольчик оболочки при установленном мессенджере (3.3) | T-8126b; T-8007 |
| `[data-search-group="messenger"]` | группа сквозного поиска; строка — ссылка `/messenger/chats/<id>/#m<id>` | T-8118; T-8140 |
| `[data-mention="<id>"]` | ФИО упомянутого в тексте — `a[data-mention="<id>"][href="/staff/<id>/"]`; упоминание чата — `a[data-mention="c<id>"][href="/messenger/chats/<id>/"]` (план: `<a data-mention>`; решение контракта К17) | T-8110; T-8136 |
| `[data-messenger-card-write]` | кнопка «Написать» в карточке сотрудника → `/messenger/?to=<id>`; у себя и уволенного раздела нет | T-8104; T-8131 |
| `[data-messenger-unit-field]` | поле галочки в форме узла: `input[name="messenger_chat"][type="checkbox"]`, подпись «Создадим чат для всего отдела»; на правке созданного чата — «Чат отдела создан» без галочки | T-8127; T-8133 |
| `[data-messenger-confirm]` | второй шаг подтверждения (удаление чата, уменьшение срока): текст, `button[name="confirm"][value="1"]`, скрытые значения | T-8120; T-8105; T-8141 |
| `[data-messenger-page="settings"]` | страница «Настройки портала → Мессенджер»: поле `input[name="retention_years"]`, галочка `input[name="general_chat_enabled"]` | T-8120; T-8134 |

## 13. Тексты, которые проверяют тесты

Тексты — словарь `TEXTS` модуля `apps.messenger/texts.py` (план: «одним словарём»); ключ — код отказа (`data-code`,
`MessengerError.code`). Подстановок нет. Тест ищет текст в разметке подстрокой, регистр как здесь. Колонка «Где» —
место отказа в разметке (10.1): имя поля (`[data-error="<поле>"]`), «общий» (`[role=alert]`) или «—» (страница 404, не
отказ формы). Коды — решение контракта К20.

### 13.1. Дословно из плана («Тексты отказов»)

| Код | Где | Текст | Тесты |
|---|---|---|---|
| `empty_text` | `text` | «Напишите текст» | T-8109a |
| `too_long` | `text` | «Предел: 4000 знаков» | T-8109a |
| `title_range` | `title` | «Название чата — от 1 до 200 знаков» | T-8105 |
| `no_members` | `members` | «Выберите хотя бы одного участника» | T-8105 |
| `files_limit` | `files`, `file` | «Не больше 10 файлов к сообщению» | T-8117a |
| `file_too_big` | `file` | «Файл больше 20 МБ» | T-8117a |
| `file_type` | `file` | «Файл такого типа не принимается» (исполняемый, архив с паролем, картинка больше 40 Мп) | T-8117a |
| `file_pending` | — | «Файл ещё проверяется» (страница 404) | T-8117b |
| `file_quarantine` | — | «Файл в карантине» (страница 404) | T-8117b |
| `mentions_limit` | `text` | «Не больше 20 упоминаний» | T-8111 |
| `retention_range` | `retention_years` | «Срок хранения — от 1 до 10 лет» | T-8120 |
| `dismissed` | `user`, `members` | «Сотрудник уволен: написать нельзя» | T-8104 |
| `chat_disabled` | общий (`chat`) | «Чат отключён» | T-8107 |
| `message_missing` | `quote` | «Сообщение не найдено» | T-8109b |
| `delete_confirm` | общий (`confirm`) | «Удалить чат вместе с историей?» | T-8105 |

### 13.2. Тексты механизмов плана, которых нет в разделе «Тексты отказов»

| Код | Где | Текст | Источник | Тесты |
|---|---|---|---|---|
| `file_missing` | `files`, `file` | «Файл не найден» (чужой, привязанный или несуществующий номер; меньше обновлённых строк, чем прислано) | план, «Файлы и эскизы» | T-8117a test_bind_uses_conditional_update_and_rolls_back_on_short_count |
| `too_many_unbound` | `file` | «Слишком много файлов без сообщения: отправьте сообщение или уберите лишние» | план, «Файлы и эскизы» | T-8117a test_31st_unbound_upload_refused |
| `purge_count` | общий (`confirm`) | «Ближайшее ночное задание удалит сообщений: {count}» | план, «Срок хранения и ночное задание» (с подстановкой числа) | T-8120 test_decrease_needs_second_step_with_count_and_keeps_value_without_confirm |

### 13.3. Тексты интерфейса (план и решения задач; в `TEXTS` не входят)

«Чатов пока нет: напишите коллеге из карточки сотрудника»; «Ничего не найдено»; «начните вводить имя»; «Показать
более ранние»; «Сообщение удалено»; «изменено»; «Прочитали N из M»; «Новых сообщений: N в чате «<название>»»;
«<ФИО>: новое сообщение в чате «<название>»»; «<ФИО> упомянул(а) вас в чате «<название>»»; «Упомянул вас в чате»;
«Новое сообщение в чате»; «Вас упомянули в чате»; «Создадим чат для всего отдела»; «Чат отдела создан»; «Создал чат»;
«К чату присоединились сотрудники отдела «<название>»»; «Написать»; «Назад»; «Чаты», «Уведомления»; «Прочитать все»;
«Все», «Непрочитанные»; «Все уведомления»; «Настройки»; «Мессенджер»; «Настройки мессенджера»; «Настройки портала →
Мессенджер»; «Хранить сообщения, лет»; «Общий чат включён»; «Подтвердить»; «Проверяется»/«проверяется», «карантин»,
«Скачать»; «99+». Время — по Москве. Видимые надписи страниц, которые сверяет T-8124: «Мессенджер» на `/messenger/`,
«Хранить сообщения, лет» на `/settings/messenger/`.

## 14. Команды стенда, нагрузка, помощники приёмки

Образец — `e2e_feed_shift`/`e2e_lists_shift` (CONTRACT-006 13.1, CONTRACT-007 14.1): проверка стенда — первым действием, до
любого чтения базы; вывод — одна строка `имя: ключ=значение …`.

### 14.1. `e2e_messenger_age --days N` (план; T-8008, T-8224)

| Что | Требование | Тесты |
|---|---|---|
| Модуль | `apps/messenger/management/commands/e2e_messenger_age.py` | T-8123 |
| Стенд | `require_stand()` из `apps.messenger.stand` — первой строкой `handle`; без `E2E_STAND=1` — `CommandError(REFUSAL)`, ничего не изменено | T-8123 test_stand_command_refused_without_e2e_stand |
| `--days` | обязателен, целое 1…4000 (решение контракта К21: предел как у `e2e_feed_retention`); вне пределов — `CommandError("Число вне пределов от 1 до 4000: N")`, ничего не изменено; не число — ошибка разбора argparse | T-8123 |
| Сдвиг | `Message.created_at` всех сообщений (включая системные и вложения) на N дней раньше прямой записью (`update(created_at=F("created_at") - delta)`) без `save()`; службы не трогаются | T-8123 test_e2e_messenger_age_shifts_by_days_and_prints_line |
| Вывод | одна строка `messenger_age: aged=<N>` (план; N — число состаренных сообщений) | T-8123; T-8130 |

Сброс стенда перед кругом — `helpers_sd.reset_stand_and_relogin()` (CONTRACT-003, 8.3); порядок `stand_reset` —
мессенджер последний зарегистрированный, зовётся первым, затем лента, списки, база знаний (раздел 1.3).

### 14.2. Нагрузка (план, «Нагрузка»; NFR-701, NFR-707)

| Что | Требование | Тесты |
|---|---|---|
| `fill_messenger.py` | `backend/tests/load/fill_messenger.py`; только при `E2E_STAND=1` (иначе `sys.exit` с прежним текстом, как `fill_feed.py`); `LOAD_CHATS=200`, `LOAD_MESSAGES=50000`; распределение участников и вложений; строка итога `fill_messenger: chats=<число> messages=<число> files=<число>` | T-8124 test_load_profile_files_exist_with_three_classes |
| `MessengerUser` | класс в `backend/tests/load/locustfile.py`: 100 вошедших, два соединения на вкладку (`/ws/notify/` и `/ws/messenger/?chat=<id>`), список, история курсором, беседа, поиск по беседе и сквозной, подсказка «@», отправка короткая и 4 000 знаков, правка, удаление, прочтение, файл; один поток публикует и запоминает `{номер: monotonic}`; событие `WS messenger frame` с точной задержкой | T-8124; T-8150 |
| Прежние классы | `FeedUser` и `NotifyUser` не меняются; прежнее обозначение `FeedWsUser` в SPEC-007 — это `FeedUser` (план) | T-8124 |
| Замер | NFR-707 — только после отдельного решения владельца (T-8304): p95 страниц и фрагментов ≤ 500 мс, кадр до последнего получателя p95 ≤ 2 с, поиск ≤ 1 с; NFR-612 среза 007 остаётся известным дефектом | T-8304 |

### 14.3. Помощники приёмки `tests/e2e/helpers_messenger.py` (пишет T-8130)

Имена — одни для T-8131…T-8143. Названные строкой T-8130: `open_messenger(context, account)`,
`open_chat(context, account, chat_id)`, `write(chat, text)`, `try_write`, `mention(context, name)`, `chat_mention(name)`,
`age(days)`, `block_ws(context)`; прочие имена и сигнатуры — решение контракта К22. Прежние помощники — `helpers.py`
(`Account`, `sign_in`, `make_employee`, `no_horizontal_scroll`, `audit_actions`), `helpers_org.py` (`create_unit`),
`helpers_sd.py` (`_stand_command`, `reset_stand_and_relogin`), `helpers_notify.py` (`tick`, `open_tab`, колокольчик,
`fakebots`), `helpers_feed.py` (образец ролей и живых кадров).

| Имя | Сигнатура и поведение |
|---|---|
| `MessengerCast` | `NamedTuple` учёток `helpers.Account`: `writer` (сотрудник, пишущий всем), `peer` (собеседник личного диалога), `third` (сотрудник вне чата), `creator` (создатель группы), `department_member`, `department_newcomer`, `outsider` (другой отдел), `admin` (администратор портала), `dismissed` (уволенный); узлы `it_unit` «Отдел ИТ», `net_unit` «Группа сети» (вложена), `other_unit` «Бухгалтерия» — номера узлов строкой |
| `messenger_cast(admin_page, mailpit, new_context) -> MessengerCast` | создаёт роли, узлы и учётки через интерфейс (`helpers.make_employee`, `helpers_org.create_unit`); имена уникальны на круг |
| `open_messenger(context, account, live=True) -> Page` | вход и `/messenger/`; при `live=True` ждёт `[data-ws]` (у беседы), при `live=False` — только загрузку страницы (после `block_ws`) |
| `open_chat(context, account, chat_id) -> Page` | вход и `/messenger/chats/<id>/`, ждёт `[data-ws="open"]` |
| `start_dialog(page, account) -> int` | «Написать» в карточке или `/messenger/people/`, ввод первого сообщения; возвращает номер чата |
| `write(page, text) -> int` | отправка сообщения формой; ждёт `article[data-message-id]`; возвращает номер сообщения |
| `try_write(page, text) -> list[tuple[str, str]]` | то же без ожидания сообщения; пары `(поле или "", data-code)` |
| `edit_message(page, message_id, text)`, `delete_message(page, message_id)` | правка и удаление своим меню; ждут кадр или перезагрузку |
| `quote(page, message_id)` | «Ответить»: цитата в поле ввода, отправка без второго уровня |
| `mention(page, name)` | «@»: выбор из `[data-mention-value]`; в поле — `@ФИО`, на сервер — маркер |
| `chat_mention(name)` | значение для упоминания чата (`#название`) |
| `upload(page, path) -> int` | загрузка файла формы; возвращает номер `MessageAttachment` |
| `wait_clean(page, file_id, timeout=60_000)` | ожидание `[data-file-state="clean"]` после обновления страницы |
| `eicar_file(tmp_path) -> Path` | файл EICAR из частей |
| `unread(page, chat_id) -> int`, `wait_unread(page, chat_id, value, timeout=2_000)` | чтение и ожидание `#chat-<id>-unread[data-count]` |
| `badge(page) -> int`, `wait_badge(page, value, timeout=2_000)` | число `#menu-badge-messenger[data-count]` и ожидание значения |
| `wait_message(page, message_id, timeout=2_000)` | ожидание кадра по `article[data-message-id="<id>"]` |
| `wait_read_line(page, text, timeout=2_000)` | ожидание `#messenger-read` с «Прочитали N из M» |
| `age(days) -> dict` | `helpers_sd._stand_command("e2e_messenger_age", "--days", N)`, разбор строки `messenger_age: aged=<N>` → `{"aged": …}` |
| `block_ws(context)` | `context.route_web_socket` (Playwright 1.63) для `/ws/messenger/` и `/ws/notify/`: маршруты не соединяются с сервером; страница работает обычными запросами |
| `check_360(page)` | ширина окна 360 px, одна колонка и `helpers.no_horizontal_scroll(page)` истинно |

## 15. Что меняется в прежних контрактах и тестах (для T-8007)

Сами `CONTRACT.md`, `CONTRACT-002.md` … `CONTRACT-007.md` не правятся (план). Здесь — какие их строки устаревают со
срезом 008 и чем заменяются; точные правки прежних тестов делает T-8007 по таблице 15.3 и только с разрешения владельца
(задачи, решение 4).

### 15.1. `CONTRACT-007.md`

| Раздел | Было | Стало |
|---|---|---|
| 1.1 | хвост `INSTALLED_APPS`: … `"apps.search"`, `"apps.feed"` | … `"apps.search"`, `"apps.feed"`, `"apps.messenger"` (1.1) |
| 1.2 | `feed_retention` — двадцатая запись `register(...)` | `messenger_retention` — двадцать первая (1.2) |
| 1.2 | `location` с `25m` — один (`^/feed/files/$`) | два: `^/feed/files/$` и `^/messenger/files/$` (1.2) |
| 1.2 | `location` с `55m` — четыре; общий `6m` | без изменений (1.2) |
| 1.3 | функция `feed` в `stand_reset` — последняя и вызывается первой | последняя — `apps.messenger.stand.stand_reset`, затем `feed`, `lists`, `knowledge` (1.3) |
| 1.4 | числа среза 007: восемнадцать точек, двадцать видов, восемь `Purpose`, `order` 60, один `25m`, двадцать записей cron | числа среза 008: девятнадцать точек, двадцать два вида, шесть `Purpose`, «Мессенджер» 61, два `25m`, двадцать один cron (1.4) |
| 2.1 | `StoredFile.Purpose`: пять значений, `feed` последним | шесть, `messenger` последним (2.1) |
| 3.1 | `POINTS` — восемнадцать, `home_body` последней | девятнадцать, `unit_form_parts` последней (3.1) |
| 7.3 | таблица «код вида → модуль»: двадцать видов | двадцать два вида семи модулей (7.4) |
| 10.1/11 | колокольчик — кнопка панели, `/notifications/` — список | колокольчик — ссылка `[data-bell-link]`, `/notifications/` — 302 на вкладку, поток — `/notifications/list/` (3.3) |
| 12.2 | у пункта «Лента» `#menu-badge-feed` | без изменений; новый `#menu-badge-messenger` (12.2) |
| 14.4 | помощники приёмки ленты | без изменений; новые — `helpers_messenger.py` (14.3) |

### 15.2. `CONTRACT-006.md`, `CONTRACT-005.md`, `CONTRACT-004.md`, `CONTRACT-002.md`, `CONTRACT.md`

| Файл и раздел | Было | Стало |
|---|---|---|
| `CONTRACT-006.md` (1.1, 1.4) | хвост `INSTALLED_APPS` без `feed`; восемнадцать записей cron; четырнадцать пунктов меню администратора | семь имён хвоста; двадцать один cron; шестнадцать пунктов (1.4) |
| `CONTRACT-006.md` (числа) | восемнадцать прав, двенадцать видов | восемнадцать прав (не меняются), двадцать два вида (1.4, 7.4) |
| `CONTRACT-005.md` (3.1) | полный `POINTS` — семнадцать имён, последние `search_providers`, `ticket_card_parts` | девятнадцать имён, `unit_form_parts` последней; прежние восемнадцать — в прежнем порядке (3.1) |
| `CONTRACT-004.md` (1.3, 3.2, 6.3, 6.6, 6.9, 6.11) | `CHANNEL_LAYERS` — два ключа; колокольчик — кнопка панели; каталог — двадцать видов; правила письма, тихих часов и сводки | слой не меняется; колокольчик получает `bell_link`; каталог — двадцать два вида; правила письма/тихих часов/сводки — те же, мессенджер на них ссылается (3.3, 7.3) |
| `CONTRACT-002.md` (элемент `menu_items`) | `url`, `title`, `icon`, `order`, `badge`, `live_badge` | без изменения формы; «Мессенджер» — `order` 1 (второй), «Настройки мессенджера» — `order` 64 (3.4) |
| `CONTRACT.md` (меню, уведомления) | пункты меню — ссылки ядра по праву; колокольчик открывает панель | без изменений для адресов ядра; новый пункт «Мессенджер» виден каждому; колокольчик ведёт на вкладку (3.3, 3.4) |

### 15.3. Перечень правок прежних тестов T-8007 («было / стало»)

Источник — TASKS-008, строка T-8007 (23 пункта) и раздел плана «Прежние тесты, которые придётся поправить». Каждая
правка — по одному тесту, с диффом и разрешением владельца; правка сверх перечня запрещена.

| № | Тест | Было | Стало |
|---|---|---|---|
| 1 | `test_extensions.py::test_org_registers_all_nine_extension_points` | `… + POINTS_007`, «восемнадцать» | `… + POINTS_007 + POINTS_008` (`from tests.support_messenger import POINTS_008`), «девятнадцать» |
| 2 | `test_feed_core_changes.py::test_points_end_with_home_body_as_eighteenth_point` | `len(POINTS) == 18`, `POINTS[-1] == "home_body"`, `POINTS[17:] == POINTS_007` | `19`, `"unit_form_parts"`, `POINTS[18:] == POINTS_008`; в соседнем тесте `POINTS[:17]` → `[:18]` |
| 3 | `test_kb_boundaries.py` | `POINTS_18 = POINTS_17 + ("home_body",)`, `len == 18`, `POINTS[-3:-1]` | `POINTS_19 = POINTS_18 + ("unit_form_parts",)`, `19`, `POINTS[-4:-2]` |
| 4 | `test_lists_boundaries.py` | `POINTS_18`, `len == 18` | `POINTS_19`, `19` |
| 5 | `test_sd_boundaries.py` | `POINTS_17 + ("home_body",)` | `POINTS_17 + ("home_body", "unit_form_parts")` |
| 6 | `test_feed_core_changes.py::test_stored_file_purpose_feed_is_last_and_previous_values_unchanged` | пять значений, `values[-1] == "feed"` | шесть, `("messenger", "вложение сообщения чата")` последним, `values[-1] == "messenger"` |
| 7 | `test_kb_boundaries.py` (число видов без базы знаний) | `len(rest) == 17` | `19` |
| 8 | `test_notify_catalog.py::test_catalog_contains_eight_kinds_from_three_modules` | «двадцать видов», без «Мессенджера» | «двадцать два», счётчики модулей +2, `TABLE` + две строки, `order` 80/81 |
| 9 | `test_notify_catalog_2.py` | `+ MESSENGER_CODES` нет; `len(push_cells(root)) == 14` | `+ MESSENGER_CODES`; `16`; `push`-строка 13 → 15; «двадцать» → «двадцать два» |
| 10 | `test_notify_prefs.py`, `test_notify_prefs_2.py`, `test_notify_admin.py` | строки видов 14, в таблице администратора на 2 меньше | 16; `+2`; `messenger.message` и `messenger.mention` (модуль «Мессенджер», портал и почта); `tr[data-notify-fixed]` — по-прежнему 2 |
| 11 | `test_notify_pages.py` | `button[data-bell-toggle]` с `hx-get="/notifications/bell/"`; `_get_list` и тесты фильтров читают `/notifications/` | `a[data-bell-link][href="/messenger/notifications/"]`; `/messenger/notifications/`; адреса фильтра и страниц — `/notifications/list/` (через `hx-get`); `#notify-count`, `#notify-toast`, `#notify-bell-panel` остаются |
| 12 | `test_notify_texts.py`, `test_notify_delivery.py`, `test_notify_email.py` | `get("/notifications/")` для строк и фрагмента | `get("/notifications/list/")` для фрагмента; отдельно — 302 на старый адрес и строки в конечном ответе вкладки |
| 13 | `tests/support_feed.py` | `APPS_TAIL` — шесть имён | семь имён (+`"apps.messenger"`) |
| 14 | `test_notify_deploy.py` | `[-6:] == APPS_TAIL`; `len(registrations) == 20` | `[-7:]`; `21` (`messenger_retention`, `55 23 * * *`, `maintenance`, 600) |
| 15 | `test_lists_deploy.py`, `test_kb_deploy.py` | `[-6:]`/`[-5:]`, 20 записей; `stand_reset`: `feed` — `len - 2` | `[-7:]`/`[-6:]`, 21; `feed` — `len - 2`, `messenger` — `len - 1` |
| 16 | `test_sd_deploy.py`, `test_feed_deploy.py` | 20 записей; `[-6:] == APPS_TAIL`, `[-1] == "apps.feed"` | 21; `[-7:] == APPS_TAIL`, `[-2] == "apps.feed"`, `[-1] == "apps.messenger"` |
| 17 | `test_lists_stand.py`, `test_feed_stand.py`, `test_kb_deploy.py` | `feed` — последний в `stand_reset`, `call_order[0] == "apps.feed.stand"` | `messenger` — последний, `feed` перед ним; `call_order[0] == "apps.messenger.stand"`, `[1] == "apps.feed.stand"` |
| 18 | `test_org_permissions.py` | меню без мессенджера; `orders` 0…63; `items[1]` — «Заявки» | `urls` + `/messenger/` и `/settings/messenger/`; `orders` +1 и +64; `items[1]` — «Мессенджер» с `url/title/icon/order/badge/live_badge`, `icons["/messenger/"] == "icons/chat.html"` |
| 19 | `test_lists_access.py`, `test_sd_boundaries.py` | `len(titles) == 14`; у пункта сотрудника четыре ключа | `16`; пункт «Мессенджер» с полным набором ключей; порядок «База знаний < Списки < Сотрудники» не меняется |
| 20 | `test_search_providers_2.py`, `test_kb_boundaries.py` | `["articles","staff","units","feed"]` и др. без мессенджера | `+ ["messenger"]` / «Мессенджер» последними (во всех трёх наборах) |
| 21 | `test_deploy_files.py` | пять шаблонов: четыре `55m` и один `25m` | шесть: четыре `55m` и два `25m`; вне их — один `6m` |
| 22 | e2e `test_e10_page.py`, `test_e06_bots.py`, `test_f05_likes.py`, `test_e12_criteria.py`, `test_e04_my_settings.py` | нажатие `button[data-bell-toggle]`; каталог без «Мессенджера» | `a[data-bell-link]`, после нажатия — `/messenger/notifications/` и вкладка; каталог с разделом «Мессенджер» |
| 23 | `test_feed_boundaries.py::test_points_tuple_has_eighteen_names_and_feed_uses_home_body_last` | `len == 18`, `POINTS[-1] == "home_body"`, `POINTS_17 + feed.POINTS_007` | `19`, `"unit_form_parts"`, `+ ("unit_form_parts",)`; `_own("home_body")` не меняется |

Пункты, зеленеющие только в Этапе 3 (точки, назначение, хвост `INSTALLED_APPS`, cron, nginx, колокольчик, 302, стенд), в
T-8160 идут отдельной строкой (решение 12 задач). «Проверить после реализации» (план) — T-8300: `test_permissions.py`,
`test_sd_access.py`, `test_org_permissions.py` (права), `test_feed_home.py`, e2e `test_o_*`, `test_notify_admin.py`, e2e
`test_d09_settings.py`, `tests/e2e/test_k09_notify.py` (тоже нажимает колокольчик — при падении остановка и решение Opus,
решение 14).

## 16. Вопросы и решения

Открытых вопросов нет: контракт готов к проверке Opus до запуска T-8003.

### 16.1. Решения контракта

| № | Решение и причина |
|---|---|
| К1 | `verbose_name = "Мессенджер"`, метка `messenger` — по названию приложения и пункта меню (1.1) |
| К2 | Имена шаблонов и модулей — по блоку «Где живёт код» плана; добавлен `_badge.html` для кадра числа пункта меню (1.1, 11.3) |
| К3 | `routing.py` — `re_path(r"^ws/messenger/$", …)`, как `notify/routing.py`: путь без номера, чат в строке запроса (1.2) |
| К4 | Порядок стирания и каталог эскизов в `stand_reset`: сначала зависимые таблицы; `attachments/thumbs/` не стирается целиком, потому что каталог общий с другими срезами (1.3) |
| К5 | Имена ограничений и индексов — `messenger_*`, не длиннее 30 знаков; тест ловит `IntegrityError` и имя не сверяет (2.2) |
| К6 | Подписи видов чата — «Личный», «Групповой», «Чат отдела», «Общий чат»; значения — плана (2.2) |
| К7 | Обратная функция миграции данных — `RunPython.noop`: план обратного хода не задаёт, как у `knowledge` и `feed` (2.3) |
| К8 | Порядок регистраций — по таблице точек плана, `stand_reset` последней (3.4) |
| К9 | `CardSection`: `key="messenger"`, `tab="profile"`, `order=70` (после «Заявок» 60); для себя и уволенного функция возвращает `[]` — кнопки нет (3.4) |
| К10 | Имена функций служб, которых план не назвал (`chats.rows`, `department.delete`, `read.mark`, `live.publish`, `search.chat_search`, `retention.run`, `unit_form.form_parts`), выбраны по образцу ленты; тесты зовут их лениво (3.4, 5.1–5.4) |
| К11 | `notify_rules.still_relevant(notification)` — одна функция для письма и сводки, как `feed.notify_kinds.still_relevant` (5.3) |
| К12 | Функция склейки — `message_coalesce_text(user_id, object_ref, since)`, по образцу `comment_coalesce_text` ленты (7.1) |
| К13 | Ключи «было / стало» с префиксом `chat_` (`chat_title`, `chat_members`, `chat_created_at`) — чтобы не столкнуться с ключами `feed` при слиянии словарей; `years` и `messages` новых подписей не меняют (8.1) |
| К14 | Русские подписи действий и типов объектов — свои, без ключа `created_at`, чтобы не переписать подпись ленты «написано» (8.2) |
| К15 | Имена маршрутов свободны, тесты ходят по путям; прежнее имя `notify-list` сохраняется (10) |
| К16 | `message` в сообщении слоя пусто у действий без сообщения; ключи `counts` после JSON-транспорта — строки, тесты приводят к `int` (11.1) |
| К17 | Добавочные зацепки (`data-chat-id`, `data-own`, `data-quote-id`, `data-messenger-page`, `data-messenger-confirm`) — по образцу `data-feed-page`/`data-post-id` ленты; названные планом зацепки не переименовываются (11.3, 12) |
| К18 | `#chat-<id>-unread` при 0 остаётся в разметке с `data-count="0"` и `d-none` — как живое число ленты; «99+» выше 99 (12.2) |
| К19 | Узел соединения беседы отдельного `id` не получает: контракт требует `[data-ws]` и `#messenger-synced`, тесты ищут их (12.4) |
| К20 | Ключи текстов (`empty_text`, `too_long`, `title_range`, `no_members`, `files_limit`, `file_too_big`, `file_type`, `file_pending`, `file_quarantine`, `mentions_limit`, `retention_range`, `dismissed`, `chat_disabled`, `message_missing`, `delete_confirm`, `file_missing`, `too_many_unbound`, `purge_count`) — как у ленты и списков; тексты — дословно плана (13) |
| К21 | `--days` — целое 1…4000, текст ошибки — как у `e2e_feed_retention` (14.1) |
| К22 | Имена помощников приёмки сверх строки T-8130 (`start_dialog`, `edit_message`, `wait_message`, `unread`, `wait_unread`, `badge`, `wait_badge`, `wait_read_line`, `check_360`) — по образцу `helpers_feed.py` (14.3) |