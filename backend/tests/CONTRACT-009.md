# Контракт имён тестов среза 009 (T-9001…T-9309)

SPEC-009 v3 (подписана 2026-11-21, `sha256:166eed06…`) → PLAN-009 v4 (утверждён, подпись 2026-11-21T23:54+03:00,
`sha256:9e1d9e7b…`) → TASKS-009 v4 (утверждён, подпись 2026-11-22T09:39+03:00, `sha256:4e3b83c2…`). Тесты Этапа 2
пишутся до кода и берут отсюда имена, которых нет в PLAN-009; реализация Этапа 3 берёт их дословно (решение 2 задач
среза 008, здесь — то же правило). Имена плана (модели и поля раздела «Модель данных», адреса «Контрактов», службы
раздела «Где живёт код», задания `tasks_reminders`/`tasks_digest`/`tasks_retention`, команда `e2e_tasks_seed`, восемь
видов `tasks.*`, функции `managed_units`, `can_set_task`, `manages`, `can_edit_fields`, `can_change_status`, `visible`,
зацепки раздела «Контракты») здесь повторяются только там, где тест уточняет их форму. Прежние контракты
(`CONTRACT.md`, `CONTRACT-002.md` … `CONTRACT-008.md`) не правятся: что в них устаревает со срезом 009, перечислено
в разделе 14 (план, «Прежние тесты, которые придётся поправить»; TASKS-009, T-9011).

Происхождение каждой строки видно из текста: «план» — PLAN-009; «спека» — SPEC-009; «задачи» — TASKS-009 и раздел
«Решения Opus по задачам» (решения 1–20); «факт» — файл репозитория, названный в строке (дерево на 2026-11-22, до кода
среза 009); «решение контракта Кn» — выбор автора контракта (T-9005) там, где план и задачи оставили выбор; причина
каждого выбора — в той же строке и сводно в разделе 15. Решения контракта ничьим решением владельца не являются: их
проверяет Opus до запуска Этапа 2.

Помощники тестов: `tests/support_tasks.py` (пишет только T-9006, раздел 5.6) и `tests/e2e/helpers_tasks.py` (пишет
только T-9007, раздел 13.3). Файлы серверных тестов Этапа 2 — `test_tasks_*.py` по 26 темам (решение 1 задач;
настройки — отдельный `test_tasks_settings.py`); приёмка — `tests/e2e/test_t09_*.py` (10 сценариев, раздел 13.3).

Правила для всех тестов среза:
- время — из `django.utils.timezone.now()`/`Clock` фикстуры `clock` (`tests/factories.py`); «сегодня» по Москве —
  `apps.core.widgets.moscow_today()` (факт); тесты, где важна дата по Москве, ставят часы на полночь UTC (03:00 МСК)
  и на 21:00–23:59 UTC; службы передают время в SQL параметром `%s`, а не `now()` базы (как CONTRACT-007/008);
- задания выполняются синхронно: `test_tasks_reminders` зовёт `tasks_reminders(now=…)`, `test_tasks_digest` —
  `tasks_digest(now=…)`, `test_tasks_retention` — `tasks_retention(now=…)` (все принимают время параметром);
  приёмка наполняет стенд командой `e2e_tasks_seed` (раздел 13.1);
- всё, что идёт «после фиксации» (рассылка, стирание файлов с диска), проверяется внутри
  `django_capture_on_commit_callbacks(execute=True)`;
- гонки — без потоков: по SQL (`support_tasks.capture_sql`), последовательно (два переноса, две уборки), подменой
  «между выборкой и замком»; `django_db(transaction=True)` не используется (conftest);
- ClamAV: подмена `apps.integrations.clamav.services.scan` помощниками `support_org.scan_clean`, `scan_found`,
  `scan_unavailable`; настоящий ClamAV (EICAR) — только в приёмке;
- код среза тесты импортируют внутри функций теста (или через `support.model("tasks.Task")`), а не на уровне модуля:
  сбор `pytest --collect-only` проходит до появления кода; `support_tasks.py` на уровне модуля `apps.tasks` не
  импортирует;
- тексты отказов в тестах — литералы раздела 12.1, а не импорт `apps.tasks.services.errors.TEXTS`; словарь `TEXTS`
  содержит каждый ключ и текст раздела 12.1 (сверка — одна проверка исполнителя T-9203/T-9213; тесты отказов ищут
  текст подстрокой в разметке);
- ответы (план, «Контракты»): чужая, несуществующая и удалённая задача, её комментарий и файл отвечают одинаково —
  404 обычной страницы «Не найдено» без подробностей (сравнение в пределах одного клиента — `support.same_failure`);
  задача видна, действие не разрешено — 403; отказ с сообщением — 200 с формой или фрагментом и причиной у поля
  (запрос HTMX — фрагмент); не вошедшему — 302 на `/login/?next=<путь>`, без второго фактора — прежние слои ядра;
- секреты и ПДн: почта и телефоны — `support_tasks.email_of`, `phone_of`; имена переменных — без `secret`, `token`,
  `key`, `password`; строка EICAR собирается из частей; в файлах, ответах и отчётах — только `***`;
- разметка: без `role="status"`, `role="alert"`, `data-error`, `data-warning`, кроме сообщений об отказах форм
  (раздел 6.1); без `style=` и `on…=` в шаблонах среза; свои скрипты — внешние файлы `static/tasks/tasks.js`,
  `tasks.css`, без `eval(` и `new Function`; перетаскивание — только `static/vendor/Sortable-1.15.6.min.js`;
- тесты ходят по путям плана (раздел 6), а не по именам маршрутов; маршруты среза не содержат `regist`, `signup`;
- SQL — только параметры (NFR-712): литерал с `%s` и списком параметров; цепочка узлов — массивом `= ANY(%s)`;
  значения фильтров ищутся в `params` захваченного запроса, а не в тексте SQL до подстановки (`support_feed.queries_with_params`
  через `capture_sql`).

Разделы:
1. Среда запуска и числа среза.
2. Модели, поля, данные установки.
3. Записи точек `tasks`.
4. Права и видимость.
5. Службы `tasks`, исключения, точки подмены и `support_tasks.py`.
6. Маршруты, поля форм, ответы.
7. Доски и переносы.
8. Напоминания.
9. Уведомления и сводка.
10. Журнал, лента карточки.
11. Поиск и карточка сотрудника.
12. Коды, поля и тексты отказов.
13. Стенд, нагрузка, помощники приёмки.
14. Что меняется в прежних контрактах и тестах (для T-9011).
15. Решения контракта.

## 1. Среда запуска и числа среза

### 1.1. Приложение, каркас, статика

| Что | Требование | Тесты |
|---|---|---|
| `INSTALLED_APPS` | `"apps.tasks"` — последним, после `"apps.messenger"` (план): хвост — `"apps.servicedesk"`, `"apps.notify"`, `"apps.knowledge"`, `"apps.lists"`, `"apps.search"`, `"apps.feed"`, `"apps.messenger"`, `"apps.tasks"`; метка `tasks`, класс `TasksConfig`, `verbose_name = "Задачи"` (решение контракта К1) | T-9121; T-9123; T-9001 |
| `TasksConfig.ready()` | зовёт `apps.tasks.extensions.register_all()`; подписок на шину у среза нет (план) | T-9123 test_tasks_registers_points_and_no_bus_subscriptions |
| Каркас (план, «Где живёт код») | `apps/tasks/`: `apps.py`, `models.py`, `extensions.py`, `urls.py`, `notify_kinds.py`, `audit_labels.py`, `stand.py`; `services/` (`access`, `tasks`, `list`, `boards`, `plan`, `categories`, `comments`, `files`, `reminders`, `notify_rules`, `digest`, `retention`, `search`, `settings`, `errors`), `views/` (`pages`, `actions`, `comments`, `files`, `reminders`, `plan`, `settings`), `templates/tasks/`, `static/tasks/`, миграция `0001_initial.py`; иконка `templates/icons/tasks.html` (решение контракта К2) | T-9121 (обход `ast`) |
| Статика | `static/tasks/tasks.js` — `<script defer …>`, `tasks.css` — `<link rel="stylesheet">`; `static/vendor/Sortable-1.15.6.min.js` — `<script src … defer>`; подключаются в `_assets.html` для `/tasks/` и `/settings/tasks/` (условие `{% if "/tasks/" in request.path %}` покрывает оба пути); `LICENSE-sortable` и строка `SortableJS 1.15.6` в `VERSIONS.md`; `tools/verify_vendor.py` знает пакет `sortablejs@1.15.6` | T-9121 test_tasks_assets_and_sortable_are_wired; T-9008 |
| Шаблоны | `templates/tasks/`: `page.html`, `_list.html`, `_row.html`, `_card.html`, `_comment.html`, `_files.html`, `_reminders.html`, `_board.html`, `_plan.html`, `_settings.html`, `_category_form.html`, `_column_form.html`, `_confirm.html` (К2); в них нет `style=` и `on…=` | T-9121 |
| CSP | `/tasks/…`, `/settings/tasks/…` отдают `Content-Security-Policy` с `script-src 'self'` без `'unsafe-inline'` и `'unsafe-eval'`; `connect-src 'self'` | T-9121 test_csp_without_unsafe_inline_on_tasks_pages |
| Язык и время | тексты страниц по-русски; даты — «ДД.ММ.ГГГГ» по Москве (`data-deadline` с ISO и текст), время ленты — «ДД.ММ.ГГГГ ЧЧ:ММ» | T-9121 test_texts_are_russian_and_dates_are_moscow |
| Файл теста развёртывания | `tests/test_tasks_deploy.py` | T-9121 |

### 1.2. Задания, nginx, том файлов

| Что | Требование | Тесты |
|---|---|---|
| Записи cron (план «Запуск») | 22-я, 23-я и 24-я записи `config/cron.py` под `apps.is_installed("apps.tasks")` (импорт заданий внутри той же проверки): `register(tasks_reminders, queue_name="maintenance", cron="*/5 * * * *", name="tasks_reminders", job_timeout=300)`, `register(tasks_digest, queue_name="maintenance", cron="*/15 * * * *", name="tasks_digest", job_timeout=300)`, `register(tasks_retention, queue_name="maintenance", cron="42 23 * * *", name="tasks_retention", job_timeout=600)`; `42 23` прежде свободна (факт: `55 23` — `messenger_retention`); прежние двадцать одна запись та же | T-9121 test_cron_has_24_registers_and_three_tasks_jobs; T-9011 |
| `TASKS_JOBS` | `{"tasks_reminders": ("tasks_reminders", "maintenance", "*/5 * * * *", 300), "tasks_digest": ("tasks_digest", "maintenance", "*/15 * * * *", 300), "tasks_retention": ("tasks_retention", "maintenance", "42 23 * * *", 600)}` — формат `MESSENGER_JOBS` из `test_messenger_deploy.py` | T-9121 |
| Адреса | `config/urls.py`: `include("apps.tasks.urls")` под `apps.is_installed("apps.tasks")` после `messenger`; прежние include и обработчики ошибок не меняются | T-9123; T-9001 |
| `location` nginx (NFR-713) | в `deploy/nginx.conf` и `deploy/nginx.prod.conf`: ровно один новый `location ~ ^/tasks/files/$ { … }` с `client_max_body_size 25m;` и тем же набором имён директив `proxy_*`, что у блоков `tickets`/`messenger`; всего `25m` — три (`^/feed/files/$`, `^/messenger/files/$`, `^/tasks/files/$`); прежние `55m` и общий `6m` не меняются | T-9121 test_nginx_has_three_25m_locations; T-9011 |
| Том файлов | оригиналы — в томе `protected`: `core.services.uploads.store(data, name, "task")`; `deploy/backup/backup.sh` не меняется; новых томов и пакетов нет | T-9121; T-9116 |

### 1.3. Сброс стенда: точка `stand_reset` модуля `tasks`

Функция — `apps.tasks.stand.stand_reset()` без аргументов, регистрируется в `apps.tasks.extensions.register_all()`
**последней** (план; T-9010). `apps.tasks` последний в `INSTALLED_APPS`, команда `e2e_reset_stand` зовёт функции в
обратном порядке, поэтому функция `tasks` идёт **первой**, затем `messenger`, `feed`, `lists`, `knowledge` (решение 11
задач). Работает через соединение `migrate`, если оно настроено, иначе `default` (как `lists`, `feed`, `messenger`).

| Что | Требование | Тесты |
|---|---|---|
| Транзакция | всё стирание и восстановление данных установки — в одной `transaction.atomic(using=<алиас>)` | T-9124 test_stand_reset_runs_in_migration_transaction |
| Таблицы | стираются все таблицы `tasks`: `TaskFile`, `TaskComment`, `TaskReminder`, `TaskMember`, `Task`, `PlanColumn`, `TaskCategory`, `TaskSettings` (сначала зависимые); строки `core.StoredFile` с `purpose="task"` удаляются вместе с вложениями | T-9124 test_stand_reset_wipes_tasks_and_files |
| Файлы | пути оригиналов собираются по строкам `TaskFile`/`StoredFile` (все состояния) до удаления; диск — `transaction.on_commit(lambda: core_files.remove_paths(paths), using=<алиас>)` на том же алиасе | T-9124 |
| Восстановление | данные установки среза: строка `TaskSettings(pk=1, retention_years=3)`; повторный запуск ничего не дублирует (категории — данные администратора и сбросом не возвращаются) | T-9124 test_stand_reset_returns_settings |
| Порядок | в `extensions.registered("stand_reset")` функция `apps.tasks.stand.stand_reset` — последняя, сразу после `apps.messenger.stand.stand_reset`; в вызове `e2e_reset_stand` — первая | T-9124 test_tasks_stand_reset_is_registered_last_and_runs_first |
| Проверка стенда | `apps.tasks.stand.require_stand()` и `REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."` — своя копия (как `lists`, `feed`, `messenger`) | T-9124 test_stand_command_refused_without_e2e_stand |

Тесты сброса помечаются `pytest.mark.django_db(databases=["default", "migrate"])`, данные создают и читают через
`using("migrate")`, `stand_reset()` вызывают напрямую (как CONTRACT-006 1.3, CONTRACT-007 1.3, CONTRACT-008 1.3).

### 1.4. Числа среза

| Число | Было (факт до среза) | Стало | Кто сверяет |
|---|---|---|---|
| Точек расширения | девятнадцать (`unit_form_parts` последняя) | девятнадцать (новых нет) | T-9123 |
| Вызовов `register` в `config/cron.py` | двадцать один | двадцать четыре | T-9121; T-9011 |
| Видов уведомлений | двадцать два | тридцать (восемь `tasks.*`, `order` 82–89) | T-9113; T-9121; T-9011 |
| Прав в портале | восемнадцать | двадцать (`tasks.use`, `tasks.assign`) | T-9004; T-9123; T-9011 |
| Значений `StoredFile.Purpose` | шесть (`messenger` последним) | семь; `task` — последним | T-9002; T-9123; T-9011 |
| `order` группы поиска | «Мессенджер» — 61 | «Задачи» — 62 (после «Мессенджера») | T-9119; T-9011 |
| Меню | «Мессенджер» — второй (`order` 1); у администратора шестнадцать пунктов | «Задачи» — третий (`order` 2, право `tasks.use`); «Настройки задач» — `order` 65, право `settings.portal`; у администратора восемнадцать пунктов; пункты с `order` 65 сортируются по `(order, title)`: «Настройки задач» **перед** «Сервис-деск» (решение 17 задач) | T-9121; T-9011 |
| `location` с `client_max_body_size 25m` | два | три | T-9121; T-9011 |
| `apps.tasks` | — (`apps.messenger` последний) | последний в `INSTALLED_APPS` | T-9121; T-9123; T-9011 |
| Запись `stand_reset` | `messenger` — последняя | `tasks` — последняя, `messenger` перед ней | T-9124; T-9011 |
| Нагрузочные классы | `FeedUser`, `MessengerUser`, `NotifyUser` | +`TaskUser` | T-9121; T-9150 |
| Кодов журнала среза | — | `tasks.created`, `tasks.changed`, `tasks.comment_changed`, `tasks.deleted`, `tasks.reminder_set`, `tasks.reminder_failed`, `tasks.retention_changed`, `tasks.retention_purged` (раздел 10) | T-9117; T-9121 |

## 2. Модели, поля, данные установки

### 2.1. Приложение `tasks` (миграция `0001`)

Имена и поля — план, «Модель данных»; тесты берут их через `support.model("tasks.<Модель>")`. Номер задачи — `pk`;
`__str__` задачи — `#<pk> <title>` (К3). Пределы: `title` 1–300, `description` ≤ 10 000, `TaskComment.text` 1–10 000,
`TaskFile.name` ≤ 255, `TaskCategory.title`/`PlanColumn.title` 1–100, `TaskSettings.retention_years` 1–10 по
умолчанию 3.

| Модель | Что сверяет тест | Тесты |
|---|---|---|
| `Task` | поля и пределы, `deadline` — дата без времени, четыре статуса (`new`, `in_progress`, `waiting`, `done`), `deleted_at` пусто у живой, `completed_at` ставится при `done` и снимается при возврате, индексы `(assignee, status)`, `deadline`, `author`, `plan_column`, `category`, `deleted_at` | T-9101 |
| `TaskMember` | роль `coexecutor`/`observer`, уникальность `(task, user)`, индекс `(user)` | T-9101 |
| `TaskCategory` | уникальность `title`, `position` | T-9101 |
| `PlanColumn` | уникальность `(user, title)`, порядок `(user, position)` | T-9101 |
| `TaskReminder` | `kind` (`auto_soon`/`auto_due`/`auto_overdue`/`manual`), `moment`, `state` (`pending`/`sent`/`cancelled`), `postponed_to`; частичный уникальный индекс `(task, user, kind)` при `kind LIKE 'auto%' AND state != 'cancelled'`; ручные не уникальны | T-9101; T-9112 |
| `TaskComment` | `edited_at`, `deleted_at`, индекс `(task, created_at)`; **своя модель**, не `core.Comment` | T-9101; T-9115 |
| `TaskFile` | `file` — OneToOne на `StoredFile` (PROTECT), `comment` пусто у непривязанного, имя в `TaskFile.name`, `uploaded_by`; индексы `(task)`, `(comment)` | T-9101; T-9116 |
| `TaskSettings` | одна строка `pk=1`, `retention_years` 1–10, `updated_at`, `updated_by` | T-9101; T-9125 |

Число запросов: `test_tasks_models` проверяет только схему и ограничения; SQL-поведение — в тематических файлах.

### 2.2. Ядро и права

| Что | Требование | Тесты |
|---|---|---|
| `StoredFile.Purpose.TASK` | `"task"`, «вложение задачи», последним; `max_length` 16, значение по умолчанию `photo` не менялись; миграция `core 0012_storedfile_task_purpose` — один `AlterField`, зависит от `0011` | T-9002 test_purpose_task_is_last; T-9123 |
| Права (T-9004) | строки `core.Permission`: `tasks.use` — «Работа с задачами», `tasks.assign` — «Ставить задачи другим сотрудникам»; выданы «Администратору портала» и «Сотруднику ИТ»; миграция `core 0013_tasks_permissions` зависит от `0012`, идемпотентна | T-9004; T-9123 |
| `org.services.structure.managed_units(user)` | узлы с отметкой `head`/`deputy` и все вложенные по `path`, **без обычных членств**; уволенный — `frozenset()`; два запроса | T-9003; T-9102; T-9123 |
| Прежнее поведение | без `apps.tasks` портал работает: меню прежние, поиск без группы «Задачи», карточка без раздела, файлы без `task` | T-9123; T-9122 |

## 3. Записи точек `tasks`

`apps/tasks/extensions.py` в `register_all()` регистрирует: `menu_items`, `notification_kinds`, `search_providers`,
`card_sections`, `audit_labels`, `file_purposes`, `stand_reset` (по одной функции на точку); `role_sources` **не**
регистрирует (план, «Права среза»).

| Точка | Запись | Тесты |
|---|---|---|
| `menu_items` | «Задачи»: `url="/tasks/"`, `title="Задачи"`, `icon="icons/tasks.html"`, `order=2`, `permissions=("tasks.use",)`; «Настройки задач»: `url="/settings/tasks/"`, `title="Настройки задач"`, `icon="icons/gear.html"`, `order=65`, `permissions=("settings.portal",)` | T-9121; T-9123 |
| `notification_kinds` | восемь видов раздела 9.1 (порядок 82–89) | T-9113; T-9121 |
| `search_providers` | одна группа `SearchProvider(key="tasks", title="Задачи", order=62, …)`; `available(user)` — есть `tasks.use` | T-9119; T-9011 |
| `card_sections` | `CardSection("tasks", "profile", 75, "tasks/_card_section.html", {"url": …})` (К4: после «Заявок» 60 и мессенджера 70) | T-9120 |
| `audit_labels` | словарь `actions`/`fields`/`object_types`/`values` раздела 10.2 | T-9117; T-9121 |
| `file_purposes` | `FilePurpose(purpose="task", still_waiting=…, clean=…, found=…)` — состояния `pending`/`clean`/`quarantine` как у вложений ленты и мессенджера | T-9116 |
| `stand_reset` | `apps.tasks.stand.stand_reset` — последняя регистрация | T-9124 |

## 4. Права и видимость

Одна функция на правило, все — `apps/tasks/services/access.py` (план, «Права среза»); тесты зовут их напрямую и через
страницы. `viewer` — `core.User`; `task` — `tasks.Task`.

| Функция | Правило | Тесты |
|---|---|---|
| `managed_units(viewer)` | `org.services.structure.managed_units` (переэкспорт или обёртка) | T-9102; T-9003 |
| `units_of(person)` | `org.services.structure.units_of` | T-9102 |
| `manages(viewer, person)` | пересечение `{u.id for u in units_of(person)}` с `managed_units(viewer)` не пусто | T-9102 |
| `can_set_task(viewer, assignee)` | `viewer.pk == assignee.pk` или (`tasks.assign` и `manages(viewer, assignee)`) | T-9103; T-9004 |
| `visible(viewer, task)` | автор, исполнитель, соисполнитель, наблюдатель, либо `manages(viewer, task.author)` или `manages(viewer, task.assignee)`; `deleted_at IS NOT NULL` — невидима; администратор чужих не видит | T-9104 |
| `can_edit_fields(viewer, task)` | автор или `manages(viewer, task.assignee)` | T-9103; T-9106 |
| `can_change_status(viewer, task)` | исполнитель, соисполнитель, иначе `can_edit_fields(viewer, task)` | T-9103; T-9106 |
| `can_delete(viewer, task)` | автор или `manages(viewer, task.assignee)` | T-9103; T-9117 |
| `can_comment(viewer, task)` | `visible(viewer, task)` | T-9115 |
| `can_edit_comment(viewer, comment)` | автор и комментарий не удалён | T-9115 |
| `can_move(viewer, task, board)` | `status` — `can_change_status`; `deadline`/`category` — `can_edit_fields`; `plan` — только владелец плана (`viewer.pk == plan.user_id`) | T-9109 |

Заместитель равен руководителю во всех правах (ADR-0018 п. 10; T-9102). Рядовой участник узла управления не получает
(ADR-0009; T-9102, T-9003). «Цепочка вышестоящих» — `managed_units` руководителя-предка уже включает вложенные узлы.

## 5. Службы `tasks`, исключения, точки подмены и `support_tasks.py`

### 5.1. Службы

Имена модулей — план, «Где живёт код»; имена функций ниже — К5 (тесты берут их дословно).

| Модуль | Публичные функции | Тесты |
|---|---|---|
| `services.access` | раздел 4 | T-9102…T-9104, T-9109 |
| `services.tasks` | `create(actor, *, title, description="", deadline=None, assignee, members=(), category=None, plan_column=None) -> Task`, `update(actor, task, *, …поля) -> Task`, `change_status(actor, task, status) -> Task`, `soft_delete(actor, task) -> Task` | T-9105, T-9106, T-9108, T-9117 |
| `services.list` | `rows(viewer, *, preset="mine", filters=None, sort="", page=1, per_page=20) -> dict` (ключи `rows`, `total`, `pages`, `page`, `per_page`); белый список фильтров `status`, `deadline`, `assignee`, `category`; сортировки `deadline`, `updated` | T-9107 |
| `services.boards` | `status_columns(viewer, task_filter=None)`, `deadline_columns(viewer)`, `plan_columns(viewer, owner)`, `category_columns(viewer)` — каждая возвращает список колонок `{"key", "title", "tasks", "count"}` в порядке доски | T-9108 |
| `services.plan` | `columns_of(user)`, `ensure_defaults(user) -> list[PlanColumn]`, `add_column(user, title)`, `rename_column(user, column, title)`, `delete_column(user, column)`, `move_task(user, task, column)` | T-9110 |
| `services.categories` | `all()`, `add(actor, title)`, `rename(actor, category, title)`, `delete(actor, category)`, `set_for_task(actor, task, category)` | T-9111 |
| `services.comments` | `add(actor, task, text, files=()) -> TaskComment`, `edit(actor, comment, text)`, `remove(actor, comment)` | T-9115 |
| `services.files` | `store(actor, task, upload) -> TaskFile`, `bind(comment, file_ids)`, `content(task, file, viewer)` (проверка видимости и состояния) | T-9116 |
| `services.reminders` | `plan(task) -> list[TaskReminder]`, `set_manual(actor, task, *, days=None, on=None)`, `postpone(actor, reminder)`, `cancel_all(task, *, reason="")`, `due(now) -> list[TaskReminder]` | T-9112 |
| `services.notify_rules` | `recipients(task, event) -> dict[user_id, kind]` (при совмещении — один вид с приоритетом), `is_own_action(actor, task) -> bool` | T-9113 |
| `services.digest` | `send(now) -> int` (число уведомлений) | T-9114 |
| `services.retention` | `purge(now) -> dict` (ключи `tasks`, `comments`, `files`, `unbound`) | T-9118 |
| `services.search` | `search_providers() -> list[SearchProvider]` | T-9119 |
| `services.settings` | `get() -> TaskSettings`, `save(actor, retention_years) -> TaskSettings` | T-9125 |
| `tasks.py` (задания) | `tasks_reminders(now=None)`, `tasks_digest(now=None)`, `tasks_retention(now=None)` — в `apps/tasks/tasks.py` | T-9112, T-9114, T-9118 |

### 5.2. Исключения

`apps/tasks/services/errors.py`: `class TasksError(Exception)` с `code`, `field`, `params`; `message` берётся из словаря
`TEXTS` того же модуля (К3; отдельного `texts.py` план не задаёт). Коды и тексты — раздел 12.1. Службы поднимают
`TasksError`; представления превращают её в ответ 6.1.

### 5.3. Точки подмены для тестов

| Что | Точка | Тесты |
|---|---|---|
| Время | `django.utils.timezone.now` (фикстура `clock`) и параметры `now=` у заданий | T-9112, T-9114, T-9118 |
| Календарь | `apps.org.services.calendar.day_kind`, `next_working_start`, `version`; `apps.notify.services.quiet.next_start` | T-9112 |
| Тихие часы | `next_start(prefs, moment)` возвращает `None` — подмена в `apps.tasks.services.reminders` (К6: служба зовёт `quiet.next_start` через модульное имя, чтобы тест мог подменить) | T-9112 |
| ClamAV | `apps.integrations.clamav.services.scan` (`support_org.scan_clean/found/unavailable`) | T-9116 |
| Очереди | `support_notify.run_jobs("maintenance")` для постановки заданий; сами задания зовутся синхронно | T-9112, T-9114, T-9118 |
| Кэш сводки | `cache` (Valkey база 15) — тест очищает фикстурой `valkey_clean`; повторный `tasks_digest` не создаёт второго уведомления | T-9114 |

### 5.4. Помощники `tests/support_tasks.py` (пишет только T-9006)

На уровне модуля `apps.tasks` не импортируется; модели — `support.model("tasks.…")`; код служб — внутри функций.

| Имя | Сигнатура и поведение |
|---|---|
| `PERMISSIONS_009` | `("tasks.use", "tasks.assign")` |
| `staff_user(**extra)` | сотрудник с ролью «Сотрудник ИТ» (`support.make_employee(roles=[support.role_by_name(support.STAFF_ROLE)])`) |
| `viewer(**extra)` | сотрудник с правами `tasks.use` и `tasks.assign` через свою роль |
| `head_of(unit, **extra)` / `deputy_of(unit, **extra)` | сотрудник + членство `mark="head"`/`"deputy"` (`support_org.make_member`) |
| `make_task(title="Задача", *, author=None, assignee=None, deadline=None, status="new", description="", category=None, plan_column=None, **extra)` | задача через ORM; по умолчанию автор = исполнитель = свежий `staff_user`; возвращает `Task` |
| `add_member(task, user, role="coexecutor")` | строка `TaskMember` |
| `make_column(user, title="Сегодня", position=0)` / `make_category(title="Работа", position=0)` | строки справочников |
| `move(client, task, board, value, **extra)` | `client.post(f"/tasks/{task.pk}/move/", {"board": board, "value": value}, **extra)` с `HTTP_HX_REQUEST="true"` по умолчанию; возвращает ответ |
| `board_rows(response_or_html, board)` | разбор разметки: `{ключ колонки: [номер задачи, …]}` по `[data-column]`/`[data-task-card]` |
| `reminders_of(task)` | `list(TaskReminder.objects.filter(task=task).order_by("moment", "pk"))` |
| `post_comment(client, task, text="Комментарий", **extra)` | `client.post(f"/tasks/{task.pk}/comments/", {"text": text}, **extra)` |
| `capture_sql(call)` | список SQL вызова (`CaptureQueriesContext`), как `support_messenger`/`support_feed` |
| `email_of(user)` / `phone_of(user)` | синтетические контакты без настоящих ПДн |
| `tasks_pages()` | список адресов страниц среза для обходов разметки (К7) |

## 6. Маршруты, поля форм, ответы

Адреса, методы и «кто» — план («Контракты»); здесь — поля форм, параметры, форма ответа и коды. `app_name = "tasks"`;
тесты ходят по путям (решение контракта К8). Итого 25 HTTP-адресов и 27 строк: у `/tasks/` и `/tasks/<id>/` — GET и POST отдельными строками.

### 6.1. Общие правила

| Что | Требование | Тесты |
|---|---|---|
| Вход | все адреса — `@login_required`: без входа GET и POST — 302 на `/login/?next=<путь>`; без второго фактора — прежние слои ядра | T-9105…T-9125 |
| Права страниц | `/tasks/…` — `tasks.use` (403 без него, без обращения к службам); `/settings/tasks/…` — `settings.portal` (403 на GET и POST) | T-9121; T-9125 |
| Запрос HTMX | заголовок `HX-Request: true`; ответ — фрагмент без `<html>` | T-9106, T-9109 |
| Отказ службы на POST | 200 с формой или фрагментом, введённое остаётся; отказ у поля — `[data-error="<поле>"][data-code="<код>"]` рядом с полем, общий отказ — `[role=alert][data-code="<код>"]` (как CONTRACT-006/007/008, 10.1); `<поле>` — имя поля 6.2 (`title`, `description`, `deadline`, `assignee`, `members`, `category`, `status`, `board`, `text`, `file`, `reminder`, `retention_years`, `confirm`) | все тесты отказов |
| Успех POST | обычный POST — 302 на адрес из 6.2; HTMX-POST — 200 с фрагментом из 6.2 | T-9106, T-9109 |
| 403, 404 | чужая, несуществующая и удалённая задача — 404 «Не найдено» (в том числе `POST`); задача видна, действие не разрешено — 403 (статус, поля, удаление, комментарий, чужие колонки); администратор чужих задач не видит — 404 | T-9103, T-9104, T-9115 |
| Метод | GET на адрес только для POST — 405 (`require_POST` прежних срезов) | T-9121 |
| Номера | `<int:task_id>` для задач, `<uuid:file_id>` для файлов; литеральные `list/`, `board/`, `new/`, `comments/`, `reminders/`, `plan/`, `files/` не путаются с `<id>/` | T-9121 |
| Ключи списка | `preset`, `q`, `status`, `deadline`, `assignee`, `category`, `sort`, `page`, `per_page` — белый список; `per_page` — только 20 или 50, иное — 20 | T-9107 |
| Время в адресе | нет (все даты — поля форм и параметры `board`/`value`) | — |

### 6.2. Поля форм и ответы по адресам

| Путь | Метод | Кто | Поля | Успех | Отказ и прочее |
|---|---|---|---|---|---|
| `/tasks/` | GET | `tasks.use` | `preset`, `q`, `status`, `deadline`, `assignee`, `category`, `sort`, `page`, `per_page`, `card` (номер открытой карточки) | страница: пресеты, фильтры, строки (`[data-task-id]`), карточка рядом на широком экране | неверный пресет — «Мои»; `card` невидимой задачи — без карточки; пусто — подсказка «Задач пока нет» |
| `/tasks/list/` | GET | `tasks.use` | те же, кроме `card` | фрагмент списка (`hx-swap` в `#tasks-list`) | пустой список — подсказка |
| `/tasks/board/status/` | GET | `tasks.use` | `preset`, фильтры | доска «Стадии»: четыре колонки `new`, `in_progress`, `waiting`, `done` с числами | — |
| `/tasks/board/deadline/` | GET | `tasks.use` | те же | доска «Сроки»: `overdue`, `today`, `week`, `none`; без «Готово» и без срока дальше 7 дней | — |
| `/tasks/board/plan/` | GET | `tasks.use` | `user` (по умолчанию — свой) | доска «Мой план»: колонки владельца, лениво создаются три; чужой план — только чтение (`[data-plan-readonly]`) | `user` не существует/уволен — свой план |
| `/tasks/board/category/` | GET | `tasks.use` | `preset`, фильтры | доска «Категории»: категории по `position` и «Без категории» последней | — |
| `/tasks/new/` | GET | `tasks.use` | — | форма создания (`[data-tasks-page="new"]`), исполнитель по умолчанию — сам | — |
| `/tasks/` | POST | `tasks.use` | `title`, `description`, `deadline`, `assignee`, `members`, `category` | обычный — 302 в `/tasks/<id>/`; HTMX — 200 карточкой | `title` пуст/301 — `title`/`title_range`; `description` 10 001 — `description`/`description_long`; `deadline` раньше сегодня — `deadline`/`deadline_past`; чужой исполнитель без права — `assignee`/`assignee_forbidden`; уволенный — `assignee`/`assignee_dismissed`; повтор в составе — `members`/`member_duplicate`; уволенный в составе — `members`/`member_dismissed`; исполнитель в составе — `members`/`member_is_assignee` |
| `/tasks/<id>/` | GET | видит задачу | `edit` (1 — форма правки) | карточка: номер, постановщик, исполнитель, срок, статус, лента, комментарии, файлы, напоминания, выбор полей (запасной путь) | 404 невидимой; удалённая — 404 |
| `/tasks/<id>/` | POST | `can_edit_fields` | `title`, `description`, `deadline`, `assignee`, `members`, `category` | обычный — 302 на карточку; HTMX — 200 карточкой | те же коды, что у создания; `deadline` очищен — срок снят (напоминания пересчитаны); нет права — 403 |
| `/tasks/<id>/status/` | POST | `can_change_status` | `status` (`new`/`in_progress`/`waiting`/`done`) | обычный — 302 на карточку; HTMX — 200 карточкой/строкой | неверный статус — `status`/`status_invalid`; нет права — `status`/`status_forbidden` (видимая) или 403 при HTMX-переносе |
| `/tasks/<id>/move/` | POST | `can_move` | `board` (`status`/`deadline`/`plan`/`category`), `value` | HTMX — 200 обновлёнными колонками (`hx-swap-oob` на `[data-column]`); обычный — 302 на доску | права — `board`/`move_forbidden`; «Просрочены» — `board`/`overdue_move`; чужой план — `board`/`plan_forbidden`; неизвестная доска/значение — `board`/`board_unknown`/`value_invalid` |
| `/tasks/<id>/delete/` | POST | `can_delete` | `confirm=1` | обычный — 302 на `/tasks/`; журнал `tasks.deleted`; мягкое удаление | без `confirm` — 200 со вторым шагом `[data-tasks-confirm]` и текстом `delete_confirm`; невидимая — 404 |
| `/tasks/<id>/comments/` | POST | `can_comment` | `text`, `files` (номера непривязанных) | обычный — 302 на карточку; HTMX — 200 новой записью ленты | пусто — `text`/`comment_empty`; 10 001 — `text`/`comment_too_long`; нет права — `text`/`comment_forbidden`; файл не свой/привязан — `file`/`file_missing` |
| `/tasks/comments/<id>/edit/` | POST | `can_edit_comment` | `text` | HTMX — 200 отредактированным комментарием с `[data-comment-edited]` | чужой — 403; удалённый — 404; пусто/10 001 — как выше |
| `/tasks/comments/<id>/delete/` | POST | `can_edit_comment` | — | HTMX — 200 серой записью «Комментарий удалён» | чужой — 403; удалённый — 404 |
| `/tasks/files/` | POST | `can_comment` | `file` (multipart), `task` | 200: «таблетка» `[data-task-file="<uuid>"]` со скрытым `input[name="files"][value="<uuid>"]` | `file`/`file_too_big` (> 20 МБ), `file_type` (исполняемый/архив с паролем), `files_limit` (11-й к комментарию), `file_missing` |
| `/tasks/files/<uuid>/` | GET | видит задачу файла; файл «чистый» | — | оригинал: `X-Accel-Redirect`, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store` | 404: невидимая задача — «Не найдено»; «проверяется» — «Файл ещё проверяется»; «карантин» — «Файл в карантине» |
| `/tasks/<id>/remind/` | POST | видит задачу; только себе | `days` или `on` (дата) | обычный — 302 на карточку; HTMX — 200 списком напоминаний | срок нужен для `days` — `reminder`/`reminder_deadline_required`; `days` вне 1–30 — `reminder_days_range`; 11-е — `reminders_limit`; чужому — `reminder_forbidden_other` |
| `/tasks/reminders/<id>/postpone/` | POST | получатель напоминания | — | обычный — 302 на карточку; HTMX — 200 списком; `postponed_to` = следующий рабочий день | чужое — 404 |
| `/tasks/plan/columns/` | POST | владелец плана | `title` | обычный — 302 на `/tasks/board/plan/`; HTMX — 200 колонками | `title` пуст/101 — `title`/`column_title_range`; повтор — `title`/`column_title_taken` |
| `/tasks/plan/columns/<id>/` | POST | владелец плана | `title`, `position` | обычный — 302; HTMX — 200 | чужой — 403; `column_title_range`/`column_title_taken` |
| `/tasks/plan/columns/<id>/delete/` | POST | владелец плана | `confirm=1` | обычный — 302; задачи уходят в первую колонку | без `confirm` — 200 второй шаг; последняя — `column`/`column_last` |
| `/settings/tasks/` | GET, POST | `settings.portal` | `retention_years`, `confirm=1` | сохранение — 302 на `/settings/tasks/`; журнал `tasks.retention_changed` | вне 1–10 — `retention_years`/`retention_range`; уменьшение без `confirm` — 200 второй шаг с числом задач к уборке (`retention_decrease`) |
| `/settings/tasks/categories/` | GET, POST | `settings.portal` | `title` | страница справочника; создание — 302 на неё | `title`/`category_title_range`, `category_title_taken` |
| `/settings/tasks/categories/<id>/` | POST | `settings.portal` | `title`, `position` | 302 на справочник | те же коды |
| `/settings/tasks/categories/<id>/delete/` | POST | `settings.portal` | `confirm=1` | 302; категория снята у задач, задачи остались | без `confirm` — 200 второй шаг `category_delete_confirm` |

### 6.3. Зацепки `data-*` и `id`

Правила: только `data-*`, `id` и классы, которых нет у прежних блоков; без `role="status"`, `role="alert"`,
`data-error`, `data-warning` вне сообщений об отказах форм; без `style=` и `on…=`. Названы планом или задачами и
потому обязательны: `[data-tasks-page]`, `[data-task-id]`, `[data-task-title]`, `[data-task-status]`, `[data-board]`, `[data-column]`,
`[data-task-card]`, `[data-move-url]`, `[data-task-field]`, `[data-error][data-code]`, `[data-tasks-preset]`,
`[data-plan-column]`, `[data-reminder]`, `[data-task-deleted]`. Прочие — К11.

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `[data-tasks-page="<имя>"]` | корень содержимого: `list` (список), `card` (карточка), `board` (доска), `new` (форма создания), `settings` (настройки и категории) | T-9105…T-9125; e2e |
| `[data-tasks-preset="mine\|authored\|subordinate\|work\|overdue"]` | кнопка-пресет в списке; выбранная — `aria-pressed="true"` | T-9107 |
| `[data-task-id]` | строка списка, карточка, карточка на доске (номер задачи) | T-9105…T-9110 |
| `[data-task-title]` | название задачи в строке и на карточке доски | T-9107; T-9109; e2e |
| `[data-task-status]` | статус карточки и строки (`new`/`in_progress`/`waiting`/`done`) | T-9106 |
| `[data-task-deleted]` | мягко удалённая задача в ленте/журнале (номер) | T-9117 |
| `[data-board="status\|deadline\|plan\|category"]` | корень доски | T-9108; T-9109 |
| `[data-column="<ключ>"]` | колонка доски; ключи — раздел 7; внутри — `[data-column-title]`, `[data-column-count]` и карточки | T-9108; T-9109 |
| `[data-column-title]` | название колонки доски и личного плана | T-9108; T-9110 |
| `[data-plan-column]` | колонка личного плана с `data-plan-column="<id>"`, `data-column="<id>"` (цель переноса — та же зацепка, что у доски) и `data-plan-readonly="1"` у чужого плана | T-9110; e2e `t06` |
| `[data-task-card]` | карточка на доске (несёт `[data-task-id]`) | T-9108; T-9109 |
| `[data-move-url]` | корень доски: шаблон адреса переноса `/tasks/{id}/move/`; номер подставляется из `[data-task-id]` | T-9109 |
| `[data-task-field="title\|description\|deadline\|status\|assignee\|members\|category\|plan_column"]` | поле в форме создания, правки и в карточке (запасной путь — `select`/`input` с этим признаком) | T-9105; T-9108 |
| `[data-error="<поле>"][data-code="<код>"]` | отказ у поля (раздел 6.1) | все тесты отказов |
| `[data-form="task-new"]`, `[data-form="task-comment"]` | формы создания задачи и комментария (для помощников приёмки) | e2e |
| `[data-tasks-confirm]` | второй шаг удаления задачи и уменьшения срока хранения | T-9117; T-9125 |
| `[data-reminder]` | строка напоминания в карточке (момент в `data-reminder-at`, состояние) | T-9112 |
| `[data-task-file="<uuid>"]` | «таблетка» загруженного файла до отправки комментария | T-9116 |
| `[data-comment-id]`, `[data-comment-edited]` | комментарий ленты и пометка «изменено» | T-9115 |
| `[data-plan-readonly]` | чужой план: карточки не двигаются, колонки не правятся | T-9110 |
| `[data-retention-years]` | поле срока хранения в настройках | T-9125 |

## 7. Доски и переносы

| Что | Требование | Тесты |
|---|---|---|
| «Стадии» | колонки `new`, `in_progress`, `waiting`, `done` в этом порядке; в шапке число `[data-column-count]`; «Готово» сохраняет завершённые | T-9108; T-9109 |
| «Сроки» | группы `overdue`, `today`, `week`, `none`; «Просрочены» — `deadline < moscow_today()` и статус ≠ `done`; «На неделе» — от завтра до `сегодня + 7` включительно; `done` и срок дальше 7 дней не показываются | T-9108; T-9109 |
| Перенос срока | `today` — сегодняшняя дата; `week` — ближайшая пятница **строго после** сегодня (сегодня пятница — следующая); `none` — срок снят; в `overdue` — `overdue_move`; смена срока пересчитывает напоминания | T-9109; T-9112 |
| «Мой план» | колонки владельца; при первом открытии — «Сегодня», «На этой неделе», «Потом»; задача без колонки — в первой; перенос меняет только `plan_column`, статус не меняется; удалённая колонка переносит задачи в первую | T-9110; T-9109 |
| Чужой план | руководитель/заместитель видит колонки и карточки, но `[data-plan-readonly]`, перенос — `plan_forbidden` (200 с причиной), колонки не правятся (403) | T-9110 |
| «Категории» | категории по `position`, «Без категории» (`key="none"`) последней; перенос в неё снимает категорию | T-9111; T-9109 |
| Запасной путь | в карточке `[data-task-field="status|deadline|category|plan_column"]` — формы выбора; работают без JS и на 360 px | T-9108; e2e `t10` |

## 8. Напоминания

| Что | Требование | Тесты |
|---|---|---|
| Момент срока | дата `deadline` в конце рабочего дня по Москве (`WorkCalendar.day_end`); нерабочая дата — конец первого рабочего дня после неё; «предыдущий рабочий день» — последний рабочий день строго до момента срока | T-9112 |
| `auto_soon` | начало рабочего дня предыдущего рабочего дня до момента срока | T-9112 |
| `auto_due` | начало рабочего дня даты срока (нерабочая — первый рабочий день после) | T-9112 |
| `auto_overdue` | начало следующего рабочего дня после момента срока | T-9112 |
| Личные тихие часы | каждый момент сдвигается `notify.services.quiet.next_start(prefs, moment)` по настройкам получателя (режимы calendar/own/none); напоминание создаётся уже в рабочее время получателя | T-9112 |
| `None` из `next_start` | напоминание остаётся `pending` до следующего цикла; повторный `None` — отмена с предупреждением в журнале `tasks.reminder_failed`, задача не ломается | T-9112 |
| Ручные | «за N рабочих дней до срока» (нужен срок) или «на дату»; только себе; не больше 10 на задачу; «Отложить» — от момента срабатывания на 1 рабочий день | T-9112 |
| Пересчёт | смена срока: автоматические и ручные «за N рабочих дней» пересчитываются, при снятии срока ручные «за N» снимаются, «на дату» остаются; смена исполнителя/состава меняет получателей; завершение и удаление — `cancel_all` | T-9112 |
| Идемпотентность | `tasks_reminders` выбирает `pending` с `moment <= now` или `postponed_to <= now`, создаёт уведомление `dispatch.create`, помечает `sent`; повторный запуск не дублирует (частичный уникальный индекс) | T-9112 |

## 9. Уведомления и сводка

### 9.1. Виды (`apps/tasks/notify_kinds.py`)

| Код | Название | `order` | Каналы по умолчанию | Внешний текст |
|---|---|---|---|---|
| `tasks.assigned` | «Назначена задача» | 82 | портал, почта | «Вам назначена задача» |
| `tasks.due_soon` | «Задача скоро просрочена» | 83 | портал, почта | «Срок задачи приближается» |
| `tasks.due` | «Срок наступил» | 84 | портал, почта | «Срок задачи наступил» |
| `tasks.overdue` | «Задача просрочена» | 85 | портал, почта | «Задача просрочена» |
| `tasks.subordinate_overdue` | «Задача подчинённого просрочена» | 86 | портал, почта | «Задача подчинённого просрочена» |
| `tasks.reminder` | «Вы просили напомнить» | 87 | портал, почта | «Напоминание о задаче» |
| `tasks.comment` | «Новый комментарий» | 88 | портал, почта | «Новый комментарий к задаче» |
| `tasks.subordinate_digest` | «Сводка по задачам подчинённых» | 89 | портал, почта | «Сводка по задачам подчинённых» |

Ссылка на объект в уведомлениях задач — `tasks.task:<номер>` (решение контракта К21): по ней `still_relevant`
находит задачу и проверяет видимость, удаление и статус; на неё же ведёт `url` уведомления.

Модуль — «Задачи»; внешний текст постоянный, без названия, описания и ФИО (NFR-714); `still_relevant` — задача видна и
не удалена (для просрочки — ещё и статус ≠ `done`).

### 9.2. Получатели (`services.notify_rules.py`)

| Событие | Кому | Тесты |
|---|---|---|
| `assigned` | исполнитель и соисполнители, автору — нет | T-9113 |
| `due_soon`, `due` | исполнитель и соисполнители | T-9113 |
| `overdue` | исполнитель, соисполнители, постановщик | T-9113 |
| `subordinate_overdue` | руководители и заместители **всей цепочки** вышестоящих узлов исполнителя | T-9113 |
| Совмещение ролей | человек получает **одно** сообщение с приоритетом `subordinate_overdue` | T-9113 |
| `reminder` | сам поставивший | T-9113 |
| `comment` | участники (автор, исполнитель, соисполнители, наблюдатели) без автора комментария | T-9113 |
| Свои действия | назначил себе / напомнил себе — уведомления нет; просрочка постановщику по своей задаче — есть | T-9113 |
| Письмо | через 15 минут, если не прочитано (механизм `notify`); отключённая почта — письма нет, портал есть | T-9113 |

### 9.3. Сводка

`tasks_digest` (каждые 15 минут) в рабочий день: атомарный `cache.add("tasks:digest:<дата>:<user>", 1, timeout=…)`;
при успехе — одно уведомление `tasks.subordinate_digest` с просроченными и «горящими» задачами подчинённых (срок
сегодня или «скоро» в пределах рабочего дня); повторный цикл без дублей (T-9114).

## 10. Журнал, лента карточки

### 10.1. Записи

| Событие | Когда | Что в записи | Тесты |
|---|---|---|---|
| `tasks.created` | создание | номер, название, исполнитель, срок | T-9117 |
| `tasks.changed` | изменение поля | `before`/`after` по полям: `title`, `description`, `deadline`, `status`, `assignee`, `members`, `category`, `plan_column` | T-9117; T-9106 |
| `tasks.comment_changed` | правка/удаление комментария | без текста; номер задачи и комментария | T-9117; T-9115 |
| `tasks.deleted` | мягкое удаление | номер, постановщик, исполнитель, статус — **без** названия, описания и комментариев (минимальный снимок, ADR-0018 п. 15) | T-9117 |
| `tasks.reminder_set` | ручное напоминание | номер задачи, получатель, момент | T-9112 |
| `tasks.reminder_failed` | `next_start` вернул `None` повторно | номер задачи и получатель; задача не ломается | T-9112 |
| `tasks.retention_changed` | смена срока хранения | `years` «было / стало» | T-9125 |
| `tasks.retention_purged` | ночная уборка удалила > 0 | число задач/комментариев/файлов; повтор без удаления — записи нет | T-9118 |

Лента карточки — записи `core.AuditEvent` по объекту `task` плюс `TaskComment`; первая строка — «создал задачу».
Журнал только дополняется (NFR-718); правка и удаление комментария в аудит — без текста.

### 10.2. Подписи (`apps/tasks/audit_labels.py`)

| Раздел | Записи |
|---|---|
| `actions` | `tasks.created` — «Задача создана»; `tasks.changed` — «Задача изменена»; `tasks.comment_changed` — «Комментарий изменён или удалён»; `tasks.deleted` — «Задача удалена»; `tasks.reminder_set` — «Напоминание поставлено»; `tasks.reminder_failed` — «Напоминание не создано»; `tasks.retention_changed` — «Срок хранения задач изменён»; `tasks.retention_purged` — «Задачи удалены по сроку» |
| `fields` | `title` — «название»; `description` — «описание»; `deadline` — «срок»; `status` — «статус»; `assignee` — «исполнитель»; `members` — «состав»; `category` — «категория»; `plan_column` — «колонка плана»; `years` — «срок хранения, лет»; `tasks` — «Удалено по сроку, задач» |
| `object_types` | `tasks.task` — «задача»; `tasks.comment` — «комментарий задачи»; `tasks.settings` — «настройки задач» |
| `values` | `{}` (службы пишут значения по-русски сами, как в мессенджере) |

## 11. Поиск и карточка сотрудника

| Что | Требование | Тесты |
|---|---|---|
| Провайдер | `SearchProvider(key="tasks", title="Задачи", order=62, …)`, `available` — `tasks.use`; слова — параметрами; `ILIKE` по названию, описанию и тексту комментариев; только видимые и не удалённые; потолок 300 | T-9119 |
| Строка | номер, название, исполнитель, срок, статус, отрывок; `url="/tasks/<id>/"` | T-9119 |
| Карточка сотрудника | раздел «Задачи» (`CardSection` order 75) — задачи, где сотрудник автор, исполнитель, соисполнитель или наблюдатель и которые видит смотрящий; пусто — раздела нет или пустой список по правилу ядра (как «Заявки») | T-9120 |

## 12. Коды, поля и тексты отказов

Тексты — словарь `TEXTS` модуля `apps/tasks/services/errors.py` (К3); ключ — код (`data-code`, `TasksError.code`).
Подстановок две: `retention_decrease` (число задач). Тест ищет текст в разметке подстрокой; коды — К9.

### 12.1. Отказы

| Код | Поле | Текст | Тесты |
|---|---|---|---|
| `title_range` | `title` | «Название задачи — от 1 до 300 знаков» | T-9105 |
| `description_long` | `description` | «Описание — не длиннее 10 000 знаков» | T-9105 |
| `deadline_past` | `deadline` | «Срок не может быть раньше сегодняшнего дня» | T-9105 |
| `assignee_dismissed` | `assignee` | «Сотрудник уволен: задачу поставить нельзя» | T-9105 |
| `assignee_forbidden` | `assignee` | «Поставить задачу этому сотруднику нельзя» | T-9103 |
| `member_dismissed` | `members` | «Сотрудник уволен: в состав не добавить» | T-9105 |
| `member_duplicate` | `members` | «Этот сотрудник уже в составе задачи» | T-9105 |
| `member_is_assignee` | `members` | «Исполнитель уже назначен: в составе его не указывают» | T-9105 |
| `edit_forbidden` | `title` | «Нет права менять поля задачи» | T-9103 |
| `status_invalid` | `status` | «Неизвестный статус задачи» | T-9106 |
| `status_forbidden` | `status` | «Нет права менять статус задачи» | T-9103 |
| `move_forbidden` | `board` | «Нет права менять это поле задачи» | T-9109 |
| `plan_forbidden` | `board` | «Двигать карточки в чужом плане нельзя» | T-9110 |
| `overdue_move` | `board` | «Из «Просрочены» переносить нельзя» | T-9109 |
| `board_unknown` | `board` | «Неизвестная доска» | T-9109 |
| `value_invalid` | `board` | «Неизвестное значение переноса» | T-9109 |
| `comment_empty` | `text` | «Напишите комментарий» | T-9115 |
| `comment_too_long` | `text` | «Предел: 10 000 знаков» | T-9115 |
| `comment_forbidden` | `text` | «Комментировать может только тот, кто видит задачу» | T-9115 |
| `files_limit` | `file` | «Не больше 10 файлов к комментарию» | T-9116 |
| `file_too_big` | `file` | «Файл больше 20 МБ» | T-9116 |
| `file_type` | `file` | «Файл такого типа не принимается» (исполняемый, архив с паролем) | T-9116 |
| `file_missing` | `file` | «Файл не найден» | T-9116 |
| `reminders_limit` | `reminder` | «Не больше 10 напоминаний на задачу» | T-9112 |
| `reminder_forbidden_other` | `reminder` | «Напоминание можно поставить только себе» | T-9112 |
| `reminder_deadline_required` | `reminder` | «Для «за N рабочих дней» нужен срок задачи» | T-9112 |
| `reminder_days_range` | `reminder` | «Число рабочих дней — от 1 до 30» | T-9112 |
| `reminder_date_invalid` | `reminder` | «Дата напоминания — ДД.ММ.ГГГГ» | T-9112 |
| `column_title_range` | `title` | «Название колонки — от 1 до 100 знаков» | T-9110 |
| `column_title_taken` | `title` | «Колонка с таким названием уже есть» | T-9110 |
| `column_last` | `column` | «Последнюю колонку удалить нельзя» | T-9110 |
| `category_title_range` | `title` | «Название категории — от 1 до 100 знаков» | T-9111 |
| `category_title_taken` | `title` | «Категория с таким названием уже есть» | T-9111 |
| `retention_range` | `retention_years` | «Срок хранения — от 1 до 10 лет» | T-9125 |
| `delete_confirm` | `confirm` | «Удалить задачу без возможности вернуть?» | T-9117 |
| `retention_decrease` | `confirm` | «Ближайшая уборка удалит задач: {count}» | T-9125 |
| `category_delete_confirm` | `confirm` | «Удалить категорию? Задачи останутся без категории» | T-9111 |

### 12.2. Тексты интерфейса (в `TEXTS` не входят)

«Задач пока нет»; «Ничего не найдено»; «Мои», «Поставленные мной», «Задачи подчинённых», «В работе», «Просрочены»;
«Новая», «В работе», «Ждёт», «Готово»; «Просрочены», «Сегодня», «На неделе», «Без срока»; «На этой неделе», «Потом»;
«Без категории»; «Начать», «Завершить», «Ждёт», «Вернуть в работу»; «Назад»; «Сбросить»; «Показать ещё»;
«Комментарий удалён»; «изменено»; «Файл ещё проверяется»; «Файл в карантине»; «Скачать»; «Создал задачу»;
«Задача создана», «Задача изменена», «Задача удалена», «Срок изменён», «Статус изменён», «Исполнитель изменён»,
«Категория изменена», «Колонка плана изменена»; «Напомнить», «Отложить», «Подтвердить», «Да», «Нет»; «Настройки задач»;
«Хранить задачи, лет»; «Категории задач»; «Добавить колонку». Время — по Москве. Видимые надписи страниц, которые
сверяет T-9121: «Задачи» на `/tasks/`, «Настройки задач» на `/settings/tasks/`.

## 13. Стенд, нагрузка, помощники приёмки

### 13.1. Команды стенда

| Команда | Требование | Тесты |
|---|---|---|
| `e2e_tasks_seed` | `apps/tasks/management/commands/e2e_tasks_seed.py`; `require_stand()` первой строкой; создаёт категории («Работа», «Личное») и три задачи (свою, подчинённому, с соисполнителем и наблюдателем) для сценариев; строка итога `e2e_tasks_seed: tasks=3 categories=2`; повторный запуск не дублирует | T-9124; e2e |
| Сброс | `helpers_sd.reset_stand_and_relogin()` перед кругом; `tasks` — последний зарегистрированный, зовётся первым (раздел 1.3) | e2e |

### 13.2. Нагрузка (NFR-710, NFR-719)

| Что | Требование | Тесты |
|---|---|---|
| `fill_tasks.py` | `backend/tests/load/fill_tasks.py`; только при `E2E_STAND=1`; 1 000 задач на 100 сотрудников (статусы, сроки, категории, комментарии, напоминания); строка `fill_tasks: tasks=<число>` | T-9121; T-9150 |
| `TaskUser` | класс в `backend/tests/load/locustfile.py`: список с пресетами, карточка, четыре доски, перенос, комментарий, поиск; рядом прежние `FeedUser`, `MessengerUser`, `NotifyUser` | T-9121; T-9150 |
| Замер | NFR-710 — только после отдельного решения владельца (T-9304): p95 ≤ 500 мс при 100 пользователях; известные дефекты NFR-612/707 и ограничение стенда записываются | T-9304 |

### 13.3. Помощники приёмки `tests/e2e/helpers_tasks.py` (пишет только T-9007)

Локаторы — только зацепки раздела 6.3; имена — К10. Прежние помощники — `helpers.py` (`Account`,
`sign_in`, `make_employee`, `no_horizontal_scroll`), `helpers_org.py` (`create_unit`), `helpers_sd.py`
(`reset_stand_and_relogin`, `_stand_command`).

| Имя | Сигнатура и поведение |
|---|---|
| `TasksCast` | `NamedTuple` учёток `helpers.Account`: `employee` (рядовой), `peer`, `head` (руководитель узла employee), `deputy`, `outsider` (другой узел), `admin` (администратор портала), `dismissed`; узлы `it_unit`, `nested_unit` (вложен), `other_unit` — номера строкой |
| `tasks_cast(admin_page, mailpit, new_context) -> TasksCast` | роли, узлы и учётки через интерфейс (`helpers.make_employee`, `helpers_org.create_unit`) |
| `open_tasks(context, account, preset="mine", **params) -> Page` | сессия в `context`, вход и `/tasks/` (или `/tasks/board/…` при `preset="board:<доска>"`), ждёт `[data-tasks-page]`; возвращает страницу |
| `create_task(page, title, *, deadline=None, assignee=None, description="", category=None) -> int` | форма «Новая задача», возвращает номер из `[data-task-id]` |
| `open_card(context, account, task_id) -> Page` | сессия в `context`, `/tasks/<id>/`; ждёт `[data-tasks-page="card"]` |
| `move_card(page, task_id, board, column)` | перетаскивание карточки в колонку `[data-column="<column>"]` мышью (`drag_to`) или отправкой формы карточки (запасной путь) |
| `board_titles(page) -> dict[str, list[str]]` | заголовки карточек по колонкам `[data-column]` |
| `plan_columns(page) -> list[str]` | названия колонок `[data-plan-column]` по порядку |
| `comment(page, text) -> None` | комментарий в карточке, ждёт новую запись ленты |
| `upload_task_file(page, path) -> str` | загрузка файла к комментарию, возвращает `uuid` из `[data-task-file]` |
| `check_360(page)` | ширина 360 px, одна колонка, `helpers.no_horizontal_scroll(page)` истинно; доска прокручивается внутри `[data-board]` |

## 14. Что меняется в прежних контрактах и тестах (для T-9011)

Сами `CONTRACT.md`, `CONTRACT-002.md` … `CONTRACT-008.md` не правятся (план). Здесь — какие их строки устаревают со
срезом 009 и чем заменяются; точные правки прежних тестов делает T-9011 по таблице TASKS-009 и только с разрешения
владельца, по одному тесту, диффом «было / стало» (решения 4 и 18 задач).

| Что устаревает | Было | Стало |
|---|---|---|
| Перечень `Purpose` | шесть значений, `messenger` последним | семь, `task` последним (T-9002) |
| Число прав | восемнадцать | двадцать; «Сотрудник ИТ» получает `tasks.use` и `tasks.assign` (T-9004) |
| Хвост `INSTALLED_APPS` | `apps.messenger` последний | `apps.tasks` последний (T-9001) |
| Число `register` в cron | двадцать один | двадцать четыре (T-9009) |
| Меню | шестнадцать пунктов у администратора; «Сервис-деск» order 65 | восемнадцать; «Задачи» order 2, «Настройки задач» order 65 перед «Сервис-деском» (T-9217) |
| Провайдеры поиска | без «Задач» | +«Задачи» order 62 (T-9214) |
| Перечень статики | без `tasks.js`/`tasks.css` | + (T-9008; если проверки нет — строку снять, решение 20 задач) |
| `location` nginx с `25m` | два | три (T-9012) |
| `stand_reset` | `messenger` последний | `tasks` последний, вызывается первым (T-9010) |
| Виды уведомлений | двадцать два | тридцать (T-9212) |

Полный перечень строк таблицы T-9011 (1–31) с точным «было / стало» — в TASKS-009; T-9011 исполняется **после**
T-9002…T-9004 и **до** T-9160 (решение 2 задач). Владелец 2026-11-22 разрешил все 31 строку и пять дополнительных
тестов той же природы (строки 32–36): `test_permissions.py::test_every_protected_view_requires_permission_403`
(таблица прав и перечень разделов без `/tasks/` и `/settings/tasks/`), `test_messenger_boundaries.py::test_purposes_are_7_and_task_last`
(бывшее имя `…_6_and_messenger_last`), `test_feed_deploy.py::test_previous_eighteen_cron_entries_keep_names_and_minutes`
(3 → 6 записей сверх прежних) и два теста `test_feed_deploy.py::test_nginx_{dev,prod}_config_has_feed_files_location_with_25m_limit`
(2 → 3 `25m`). Строка 37 — `test_sd_access.py::test_all_tickets_and_manage_rights_only_for_portal_admin_after_install`
(18 → 20 прав, добавлены `tasks.use`/`tasks.assign`), разрешена владельцем 2026-11-22 отдельно после полного прогона.
Строки 11–16, 22–26 и 31 правятся партиями Этапа 3, когда появляется их поведение (решение 18 задач): до этого
прежние тесты остаются зелёными.

## 15. Решения контракта

| № | Решение | Почему |
|---|---|---|
| К1 | Метка приложения `tasks`, класс `TasksConfig`, `verbose_name = "Задачи"` | как `messenger`/`MessengerConfig`; имя метки не пересекается с прежними |
| К2 | Имена шаблонов и иконки из 1.1; `_card_section.html` — раздел карточки сотрудника | план называет только каталог `templates/tasks/`; имена нужны тестам и T-9007 |
| К3 | `TasksError` и `TEXTS` — в `apps/tasks/services/errors.py`; `__str__` задачи — `#<pk> <title>`; отдельного `texts.py` нет | план не задаёт файл текстов; тесты тексты не импортируют |
| К4 | Раздел карточки сотрудника — `CardSection("tasks", "profile", 75, …)` | после «Заявок» (60) и мессенджера (70); порядок не задан планом |
| К5 | Имена служб и сигнатуры раздела 5.1; все задания — в `apps/tasks/tasks.py`, очередь `maintenance` | «Где живёт код» называет модули, не функции; очередь — `maintenance`, как у прежних cron-заданий |
| К6 | `reminders` зовёт `quiet.next_start` через модульное имя, чтобы тест мог подменить возврат `None` | план требует проверку `None`; подмена иначе задела бы `notify` |
| К7 | `support_tasks.tasks_pages()` — адреса страниц среза (список) | обходы разметки и проверки «нет `style=`/`on…=`» в T-9121 |
| К8 | `app_name = "tasks"`; тесты ходят по путям, а не по именам маршрутов | как CONTRACT-006/007/008 |
| К9 | Коды и тексты раздела 12.1 | T-9005; план текстов не задавал (решение 16 задач) |
| К10 | Имена и сигнатуры `helpers_tasks.py` раздела 13.3 | T-9007; локаторы — зацепки контракта |
| К11 | Зацепки раздела 6.3 обязательны; прочие `data-*` — на усмотрение исполнителя, если не ломают приёмку | как К17 CONTRACT-008 |
| К12 | «Сегодня» и «просрочено» — по Москве (`moscow_today`); момент срока — конец рабочего дня даты срока (или первого рабочего дня после неё) | так сходится пример спеки: срок в субботу → «Просрочены» в понедельник, уведомление во вторник |
| К13 | `deadline_past` проверяется только когда срок задаётся или меняется; ставший прошлым срок не мешает правке других полей | иначе нельзя было бы править просроченную задачу |
| К14 | Пункты меню с `order` 65 сортируются по `(order, title)`: «Настройки задач» перед «Сервис-деском» | решение 17 задач; ядро уже сортирует по `(order, title)` (факт) |
| К15 | При совмещении ролей в просрочке — одно уведомление `tasks.subordinate_overdue` | план, «Уведомления и сводка»; FR-691 |
| К16 | `TaskFile.comment` пусто только между загрузкой и отправкой; непривязанные старше 24 часов чистит `tasks_retention` | план, «Модель данных»; FR-693 |
| К17 | Срок хранения — календарное вычитание лет (29.02 → 28.02), отсчёт от `deleted_at` | план, «Удаление, срок хранения»; FR-696 |
| К18 | Redis-ключ сводки — `tasks:digest:<дата>:<user>`, значение `1`, срок — до конца суток по Москве | план, «Уведомления и сводка»; NFR-715 |
| К19 | Доска «Категории»: «Без категории» — колонка с ключом `none` последней | план, «Мой план и категории»; FR-683 |
| К20 | Все даты в разметке — ISO в `data-deadline`/`datetime` и текст «ДД.ММ.ГГГГ» по Москве | как CONTRACT-006/007/008; NFR-717 |
| К21 | `object_ref` уведомлений задач — `tasks.task:<номер>` | по образцу `messenger.chat:<id>`; единая ссылка для `still_relevant`, письма и сводки |