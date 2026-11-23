# Контракт имён тестов среза 010 (T-10001…T-10309)

SPEC-010 (подписана 2026-11-23 08:12, `sha256:c86c5fab…`) → PLAN-010 (утверждён, `sha256:0c1d373a…`) →
TASKS-010 v2 (утверждён, подпись 2026-11-23T16:35+03:00, `sha256:ea65fdca…`). Тесты Этапа 2 пишутся до кода и
берут здесь имена, которых нет в PLAN-010; реализация Этапа 3 берёт их дословно (правило срезов 008/009).
Имена плана (модели и поля «Модели данных», адреса «Контрактов», службы «Где живёт код», задания
`instructions_reminders`/`instructions_digest`/`instructions_retention`, команда `e2e_instructions_seed`, десять
видов `instructions.*`, зацепки раздела «Контракты») здесь повторяются только там, где тест уточняет их форму.
Прежние контракты (`CONTRACT.md`, `CONTRACT-002.md` … `CONTRACT-009.md`) не правятся: что устаревает со срезом
010, перечислено в разделе 14 (PLAN-010 «Прежние тесты, которые придётся поправить»; TASKS-010, T-10111).

Происхождение строки видно из текста: «план» — PLAN-010; «спека» — SPEC-010; «задачи» — TASKS-010 и «Решения
Opus по задачам» (1–18); «факт» — файл репозитория (дерево на 2026-11-23, до кода среза 010); «решение
контракта Кn» — выбор автора контракта (T-10004) там, где план и задачи оставили выбор; причина — в той же
строке и сводно в разделе 15. Решения контракта ничьим решением владельца не являются: их проверяет Opus до
запуска Этапа 2.

Помощники тестов: `tests/support_instructions.py` (пишет только T-10005, раздел 5.4) и
`tests/e2e/helpers_instructions.py` (пишет только T-10006, раздел 13.3). Файлы серверных тестов Этапа 2 —
`test_instructions_*.py` по темам задач T-10101…T-10124; приёмка — `tests/e2e/test_t10_*.py` (10 сценариев).

Правила для всех тестов среза:
- время — из `django.utils.timezone.now()` и фикстуры `clock` (`tests/factories.py`); «сегодня» по Москве —
  `apps.core.widgets.moscow_today()` (факт); тесты с датой по Москве ставят часы на полночь UTC (03:00 МСК) и
  на 21:00–23:59 UTC; службы передают время в SQL параметром `%s`, а не `now()` базы (как CONTRACT-009);
- задания выполняются синхронно: `test_instructions_reminders` зовёт `instructions_reminders(now=…)`,
  `test_instructions_digest` — `instructions_digest(now=…)`, `test_instructions_retention` —
  `instructions_retention(now=…)` (все принимают время параметром); приёмка наполняет стенд командой
  `e2e_instructions_seed` (раздел 13.1);
- всё, что идёт «после фиксации» (рассылка, стирание файлов с диска), проверяется внутри
  `django_capture_on_commit_callbacks(execute=True)`;
- гонки — без потоков: по SQL (`support_instructions.capture_sql`), последовательно (два переноса, две уборки),
  подменой «между выборкой и замком»; `django_db(transaction=True)` не используется (conftest);
- ClamAV: подмена `apps.integrations.clamav.services.scan` помощниками `support_org.scan_clean`, `scan_found`,
  `scan_unavailable`; настоящий ClamAV (EICAR) — только в приёмке;
- код среза тесты импортируют внутри функций теста (или через `support.model("instructions.…")`), а не на уровне
  модуля: сбор `pytest --collect-only` проходит до появления кода; `support_instructions.py` на уровне модуля
  `apps.instructions` не импортирует;
- тексты отказов в тестах — литералы раздела 12.1, а не импорт `apps.instructions.texts.TEXTS`; словарь `TEXTS`
  содержит каждый ключ и текст 12.1 (сверка — одна проверка исполнителя T-10203); тесты отказов ищут текст
  подстрокой в разметке;
- ответы: чужие, несуществующие и удалённые поручения, их отчёты, части, переносы и файлы отвечают одинаково —
  404 обычной страницы «Не найдено» без подробностей (сравнение одним клиентом — `support.same_failure`);
  поручение видно, действие не разрешено — 403; отказ с сообщением — 200 с формой или фрагментом и причиной у
  поля (запрос HTMX — фрагмент); не вошедшему — 302 на `/login/?next=<путь>`, без второго фактора — прежние
  слои ядра;
- секреты и ПДн: почта и телефоны — `support_instructions.email_of`, `phone_of`; имена переменных — без `secret`,
  `token`, `key`, `password`; строка EICAR собирается из частей; в файлах, ответах и отчётах — только `***`;
- разметка: без `role="status"`, `role="alert"`, `data-error`, `data-warning`, кроме сообщений об отказах форм
  (раздел 6.1); без `style=` и `on…=` в шаблонах среза; свои скрипты — внешние `static/instructions/instructions.js`
  и `instructions.css`, без `eval(` и `new Function`;
- тесты ходят по путям раздела 6, а не по именам маршрутов; маршруты среза не содержат `regist`, `signup`;
- SQL — только параметры (NFR-721): литерал с `%s` и списком параметров; цепочка узлов — массивом `= ANY(%s)`;
  значения фильтров ищутся в `params` захваченного запроса, а не в тексте SQL до подстановки
  (`support_instructions.queries_with_params` через `capture_sql`).

Разделы:
1. Среда запуска и числа среза.
2. Модели, поля, данные установки.
3. Записи точек `instructions`.
4. Права и видимость.
5. Службы `instructions`, исключения, точки подмены и `support_instructions.py`.
6. Маршруты, поля форм, ответы.
7. Отчётные даты и статусы.
8. Напоминания.
9. Уведомления и сводка.
10. Журнал и история.
11. Реестр, дисциплина и Excel.
12. Коды, поля и тексты отказов.
13. Стенд, нагрузка, помощники приёмки.
14. Что меняется в прежних контрактах и тестах (для T-10111).
15. Решения контракта.

## 1. Среда запуска и числа среза

### 1.1. Приложение, каркас, статика

| Что | Требование | Тесты |
|---|---|---|
| `INSTALLED_APPS` | `"apps.instructions"` — последним, после `"apps.tasks"` (план): хвост — `"apps.servicedesk"`, `"apps.notify"`, `"apps.knowledge"`, `"apps.lists"`, `"apps.search"`, `"apps.feed"`, `"apps.messenger"`, `"apps.tasks"`, `"apps.instructions"`; метка `instructions`, класс `InstructionsConfig`, `verbose_name = "Поручения"` (решение контракта К1) | T-10121; T-10122; T-10001 |
| `InstructionsConfig.ready()` | зовёт `apps.instructions.extensions.register_all()`; подписка на `core.user_dismissed` → `services.instructions.reassign` (план; T-10202) | T-10122 test_instructions_registers_points_and_dismissed_subscription |
| Каркас (план, «Где живёт код») | `apps/instructions/`: `apps.py`, `models.py`, `extensions.py`, `urls.py`, `notify_kinds.py`, `audit_labels.py`, `texts.py`, `stand.py`, `tasks.py`; `services/` (`access`, `basis`, `instructions`, `dates`, `reports`, `files`, `transfers`, `reminders`, `notify_rules`, `digest`, `registry`, `discipline`, `excel`, `retention`, `settings`), `views/` (`pages`, `actions`, `reports`, `files`, `transfers`, `settings`), `templates/instructions/`, `static/instructions/`, миграции `0001_initial.py`, `0002_initial_data.py`; иконки `templates/icons/instructions.html` и `icons/gear.html` (вторая прежняя) (К2) | T-10121 (обход `ast`) |
| Статика | `static/instructions/instructions.js` — `<script defer …>`, `instructions.css` — `<link rel="stylesheet">`; подключаются в `_assets.html` по условию `{% if '/instructions/' in request.path %}`: `/settings/instructions/` содержит подстроку `/instructions/`, потому условие покрывает оба пути (факт) | T-10121 test_instructions_assets_are_wired |
| Шаблоны | `templates/instructions/`: `page.html`, `_list.html`, `_row.html`, `_card.html`, `_dates.html`, `_reports.html`, `_parts.html`, `_transfers.html`, `_history.html`, `_files.html`, `_settings.html`, `_basis.html`, `_discipline.html`, `_confirm.html` (К2); в них нет `style=` и `on…=` | T-10121 |
| CSP | `/instructions/…`, `/settings/instructions/…` отдают `Content-Security-Policy` с `script-src 'self'` без `'unsafe-inline'` и `'unsafe-eval'`; `connect-src 'self'` | T-10121 test_csp_without_unsafe_inline_on_instructions_pages |
| Язык и время | тексты по-русски; даты — «ДД.ММ.ГГГГ» по Москве (ISO в `data-*`/`datetime`); время истории — «ДД.ММ.ГГГГ ЧЧ:ММ» | T-10121 test_texts_are_russian_and_dates_are_moscow |
| Файл развёртывания | `tests/test_instructions_deploy.py` | T-10121 |

### 1.2. Задания, nginx, том файлов

| Что | Требование | Тесты |
|---|---|---|
| Записи cron (план «Запуск») | 25-я, 26-я и 27-я записи `config/cron.py` под `apps.is_installed("apps.instructions") and apps.is_installed("apps.tasks")` (импорт заданий внутри той же проверки): `register(instructions_reminders, queue_name="maintenance", cron="*/5 * * * *", name="instructions_reminders", job_timeout=300)`, `register(instructions_digest, queue_name="maintenance", cron="*/15 * * * *", name="instructions_digest", job_timeout=300)`, `register(instructions_retention, queue_name="maintenance", cron="43 23 * * *", name="instructions_retention", job_timeout=600)`; `43 23` прежде свободна (факт: `42 23` — `tasks_retention`, `55 23` — `messenger_retention`); прежние двадцать четыре записи те же | T-10121 test_cron_has_27_registers_and_three_instructions_jobs; T-10111 |
| `INSTRUCTIONS_JOBS` | `{"instructions_reminders": ("instructions_reminders", "maintenance", "*/5 * * * *", 300), "instructions_digest": ("instructions_digest", "maintenance", "*/15 * * * *", 300), "instructions_retention": ("instructions_retention", "maintenance", "43 23 * * *", 600)}` — формат `TASKS_JOBS` из `test_tasks_deploy.py` | T-10121 |
| Адреса | `config/urls.py`: `include("apps.instructions.urls")` под `apps.is_installed("apps.instructions")` после `tasks` (факт T-10001); без `tasks` приложения нет (решение 4 задач) | T-10122; T-10001 |
| `location` nginx (NFR-722) | в `deploy/nginx.conf` и `deploy/nginx.prod.conf`: ровно один новый `location ~ ^/instructions/files/$ { … }` с `client_max_body_size 25m;` и тем же набором имён директив `proxy_*`, что у блоков `tickets`/`messenger`/`tasks`; всего `25m` — четыре (`^/feed/files/$`, `^/messenger/files/$`, `^/tasks/files/$`, `^/instructions/files/$`); прежние `55m` и общий `6m` не меняются | T-10121 test_nginx_has_four_25m_locations; T-10111 |
| Том файлов | оригиналы — в томе `protected`: `core.services.uploads.store(data, name, "instruction")`; новых томов и пакетов нет | T-10121; T-10116 |

### 1.3. Сброс стенда: точка `stand_reset` модуля `instructions`

Функция — `apps.instructions.stand.stand_reset()` без аргументов, регистрируется в
`apps.instructions.extensions.register_all()` **последней** (план; T-10008). `apps.instructions` последний в
`INSTALLED_APPS`, команда `e2e_reset_stand` зовёт функции в обратном порядке, поэтому функция `instructions`
идёт **первой**, затем `tasks`, `messenger`, `feed`, `lists`, `knowledge` (решение 12 задач). Работает через
соединение `migrate`, если оно настроено, иначе `default` (как `tasks`, `messenger`).

| Что | Требование | Тесты |
|---|---|---|
| Транзакция | всё стирание и восстановление данных установки — в одной `transaction.atomic(using=<алиас>)` | T-10123 test_stand_reset_runs_in_migration_transaction |
| Таблицы | стираются все таблицы `instructions`: `InstructionReminder`, `InstructionTransfer`, `InstructionFile`, `InstructionReportPart`, `InstructionReport`, `InstructionReportDate`, `InstructionMember`, `InstructionTask`, `Instruction`, `InstructionBasisKind`, `InstructionSettings` (зависимые раньше; `InstructionTask` — до задач не трогаем, связь каскадом от поручения); строки `core.StoredFile` с `purpose="instruction"` удаляются с файлами | T-10123 test_stand_reset_wipes_instructions_and_files |
| Файлы | пути оригиналов собираются по строкам `InstructionFile`/`StoredFile` (все состояния) до удаления; диск — `transaction.on_commit(lambda: core_files.remove_paths(paths), using=<алиас>)` | T-10123 |
| Восстановление | данные установки: `InstructionSettings(pk=1, retention_years=3, default_ladder=…)` и четыре вида основания (`get_or_create` по названию, порядок 0–3); повторный запуск не дублирует | T-10123 test_stand_reset_returns_settings_and_basis |
| Порядок | в `extensions.registered("stand_reset")` функция `apps.instructions.stand.stand_reset` — последняя, сразу после `apps.tasks.stand.stand_reset`; в вызове `e2e_reset_stand` — первая | T-10123 test_instructions_stand_reset_is_registered_last_and_runs_first |
| Проверка стенда | `apps.instructions.stand.require_stand()` и `REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."` — своя копия (как `tasks`, `messenger`) | T-10123 test_stand_command_refused_without_e2e_stand |

Тесты сброса помечаются `pytest.mark.django_db(databases=["default", "migrate"])`, данные создают и читают через
`using("migrate")`, `stand_reset()` вызывают напрямую (как CONTRACT-006/007/008/009, 1.3).

### 1.4. Числа среза

| Число | Было (факт до среза) | Стало | Кто сверяет |
|---|---|---|---|
| Точек расширения | девятнадцать (`unit_form_parts` последняя) | девятнадцать (новых нет) | T-10122 |
| Вызовов `register` в `config/cron.py` | двадцать четыре | двадцать семь | T-10121; T-10111 |
| Видов уведомлений | тридцать | сорок (десять `instructions.*`, `order` 220–229) | T-10113; T-10121; T-10111 |
| Прав в портале | двадцать | двадцать две (`instructions.use`, `instructions.assign`) | T-10003; T-10122; T-10111 |
| Значений `StoredFile.Purpose` | семь (`task` последним) | восемь; `instruction` — последним | T-10002; T-10122; T-10111 |
| Меню | «Задачи» — третий (`order` 2); у администратора восемнадцать пунктов | «Поручения» — `order` 3 (право `instructions.use`); «Настройки поручений» — `order` 66 (право `settings.portal`); у администратора двадцать пунктов; пункт 66 идёт после 65 («Настройки задач» и «Сервис-деск» сортируются по названию) | T-10121; T-10111 |
| `location` с `client_max_body_size 25m` | три | четыре | T-10121; T-10111 |
| `apps.instructions` | — (`apps.tasks` последний) | последний в `INSTALLED_APPS` | T-10121; T-10122; T-10111 |
| Запись `stand_reset` | `tasks` — последняя | `instructions` — последняя, `tasks` перед ней | T-10123; T-10111 |
| Нагрузочные классы | `FeedUser`, `MessengerUser`, `NotifyUser`, `TaskUser` | +`InstructionUser` | T-10121; T-10150 |
| Кодов журнала среза | — | `instructions.created`, `.changed`, `.report_submitted`, `.report_accepted`, `.report_returned`, `.part_added`, `.transfer_requested`, `.transfer_decided`, `.closed`, `.reassigned`, `.retention_changed`, `.retention_purged`, `.reminder_failed` (раздел 10) | T-10117; T-10121 |

## 2. Модели, поля, данные установки

### 2.1. Приложение `instructions` (миграция `0001`)

Имена и поля — план, «Модель данных»; тесты берут их через `support.model("instructions.<Модель>")`. Номер
поручения — `pk`; `__str__` — `#<pk> <title>` (К3). Пределы: `title` 1–300, `text` ≤ 10 000,
`basis_number` ≤ 100, `InstructionReport.text`/`InstructionReportPart.text` ≤ 10 000,
`InstructionReport.comment`/`InstructionTransfer.comment` ≤ 2 000, `InstructionTransfer.reason` ≤ 1 000,
`InstructionFile.name` ≤ 255, `InstructionBasisKind.title` ≤ 100, `InstructionSettings.retention_years` 1–10
(по умолчанию 3).

| Модель | Что сверяет тест | Тесты |
|---|---|---|
| `Instruction` | поля и пределы; `original_deadline` при создании = `deadline`; `ladder` JSON (по умолчанию `{}`); `closed_at`/`deleted_at` пусто у живой; индексы `(assignee, deadline)`, `controller`, `author`, `deadline`, `closed_at`, `basis_kind`; `status` не поле (К4) | T-10101 |
| `InstructionBasisKind` | `title` уникальное, `position`, `active=True`; индекс `(position)` | T-10101 |
| `InstructionMember` | роль `coexecutor`, уникальность `(instruction, user)`, индекс `(user)` | T-10101 |
| `InstructionReportDate` | `due_date`, `position`, `state` ∈ `waiting`/`review`/`returned`/`accepted` (по умолчанию `waiting`), `closed_at`; уникальность `(instruction, due_date)`, индекс `(instruction, position)` | T-10101; T-10104 |
| `InstructionReport` | `date` FK `InstructionReportDate` CASCADE, пусто = «к сроку»; `decision` ∈ `pending`/`accepted`/`returned`; `decided_by` SET_NULL; **уникальность `(instruction, author)` при `date IS NULL`**; индекс `(instruction, submitted_at)` | T-10101; T-10105 |
| `InstructionReportPart` | **`date` FK `InstructionReportDate` CASCADE обязателен**; уникальность `(date, author)`; индекс `(date)` | T-10101; T-10105 |
| `InstructionFile` | `kind` ∈ `basis`/`report`/`part`; `report`/`part` SET_NULL; `file` OneToOne `StoredFile` PROTECT; `name`, `uploaded_by`; индексы `(instruction)`, `(report)`, `(part)` | T-10101; T-10116 |
| `InstructionTransfer` | `old_deadline`, `new_deadline`, `reason`, `state` (`pending`/`approved`/`rejected`), `decided_by` SET_NULL, `decided_at`, `comment`; **частичный уникальный `(instruction)` при `state='pending'`**; индекс `(instruction, state)` | T-10101; T-10107 |
| `InstructionReminder` | `date` FK CASCADE (пусто у срока), `user` CASCADE, `kind` (`deadline`/`report`), `stage` ∈ `d30`/`d14`/`d7`/`d3`/`d1`/`due`/`overdue`/`r3`/`r1`, `moment`, `state` (`pending`/`sent`/`cancelled`); **уникальность `(instruction, date, user, kind, stage)` при `state='pending'` с `nulls_distinct=False`**; индекс `(state, moment)` | T-10101; T-10108 |
| `InstructionSettings` | одна строка `pk=1`, `retention_years` 1–10, `default_ladder` JSON, `updated_at`, `updated_by`; `CheckConstraint` 1–10 | T-10101; T-10115 |
| `InstructionTask` | `instruction` CASCADE, `task` FK `tasks.Task` CASCADE, `created_by` PROTECT, `created_at`; уникальность `(instruction, task)`, индекс `(task)` | T-10101; T-10112 |

Число запросов: `test_instructions_models` проверяет только схему и ограничения; SQL — в тематических файлах.

### 2.2. Ядро и права

| Что | Требование | Тесты |
|---|---|---|
| `StoredFile.Purpose.INSTRUCTION` | `"instruction"`, «вложение поручения», последним; `max_length` 16, значение по умолчанию `photo` не менялись; миграция `core 0014_storedfile_instruction_purpose` — один `AlterField`, зависит от `0013_tasks_permissions` | T-10002 test_purpose_instruction_is_last; T-10122 |
| Права (T-10003) | строки `core.Permission`: `instructions.use` — «Работа с поручениями», `instructions.assign` — «Ставить поручения подчинённым»; выданы «Администратору портала» и «Сотруднику ИТ»; миграция `core 0015_instructions_permissions` зависит от `0014`, идемпотентна | T-10003; T-10122 |
| `org.services.structure.managed_units(user)` | узлы с отметкой `head`/`deputy` и все вложенные по `path`, **без обычных членств**; уволенный — `frozenset()` (прежняя функция, срез 009) | T-10102 |
| `org.services.structure.managers_of(user)` | руководители и заместители цепочки узлов (без него, без уволенных), по ФИО (прежняя функция) | T-10102; T-10109 |
| Прежнее поведение | без `apps.instructions` портал работает: меню прежние, поиск без поручений, карточка без раздела, файлы без `instruction`; без `apps.tasks` нет и поручений (решение 4 задач) | T-10122; T-10119 |

## 3. Записи точек `instructions`

`apps/instructions/extensions.py` в `register_all()` регистрирует: `menu_items`, `notification_kinds`,
`audit_labels`, `file_purposes`, `stand_reset` (по одной функции на точку); `role_sources`, `card_sections`,
`search_providers` **не** регистрирует (план, «Точки расширения ядра»; поиск поручений — только в реестре).

| Точка | Запись | Тесты |
|---|---|---|
| `menu_items` | «Поручения»: `url="/instructions/"`, `title="Поручения"`, `icon="icons/instructions.html"`, `order=3`, `permissions=("instructions.use",)`; «Настройки поручений»: `url="/settings/instructions/"`, `title="Настройки поручений"`, `icon="icons/gear.html"`, `order=66`, `permissions=("settings.portal",)` | T-10121; T-10122 |
| `notification_kinds` | десять видов раздела 9.1 (порядок 220–229, после видов задач 210–217) | T-10113; T-10121 |
| `audit_labels` | словарь `actions`/`fields`/`object_types`/`values` раздела 10.2 | T-10117; T-10121 |
| `file_purposes` | `FilePurpose(purpose="instruction", still_waiting=…, clean=…, found=…)` — состояния `pending`/`clean`/`quarantine`, как у вложений ленты, мессенджера и задач | T-10116 |
| `stand_reset` | `apps.instructions.stand.stand_reset` — последняя регистрация | T-10123 |

Подписка приложения: `core.user_dismissed` → `apps.instructions.services.instructions.reassign` (T-10202), как
`messenger`/`tasks` подписываются на события ядра; подписок на шину событий сверх этого нет.

## 4. Права и видимость

Одна функция на правило, все — `apps/instructions/services/access.py` (план, «Права среза»); тесты зовут их
напрямую и через страницы. `viewer` — `core.User`; `instruction` — `instructions.Instruction`.

| Функция | Правило | Тесты |
|---|---|---|
| `managed_units(viewer)` | `org.services.structure.managed_units` (переэкспорт) | T-10102 |
| `units_of(person)` | `org.services.structure.units_of` (переэкспорт) | T-10102 |
| `manages(viewer, person)` | пересечение `managed_units(viewer)` и `units_of(person)` не пусто | T-10102 |
| `can_assign(viewer, assignee)` | `instructions.assign` у `viewer` и `manages(viewer, assignee)` | T-10102; T-10103 |
| `visible(viewer, instruction)` | автор, контролёр, исполнитель, соисполнитель, либо `manages(viewer, instruction.assignee)` или `manages(viewer, instruction.author)`; `deleted_at IS NOT NULL` — невидима; администратор портала чужих не видит (явная проверка роли), **кроме случая, когда он участник** | T-10102 |
| `can_edit_fields(viewer, instruction)` | автор и поручение не снято с контроля | T-10102; T-10103 |
| `can_edit_ladder(viewer, instruction)` | автор или контролёр, не снято с контроля | T-10102; T-10108 |
| `can_decide(viewer, instruction)` | контролёр, не снято с контроля | T-10102; T-10105 |
| `can_report(viewer, instruction, date=None)` | ответственный исполнитель (сводный отчёт), не снято с контроля; `date` открыта (`waiting`/`returned`) | T-10102; T-10105 |
| `can_add_part(viewer, instruction, date)` | соисполнитель или ответственный, `date` не закрыта и сводный отчёт к ней ещё не отправлен | T-10102; T-10105 |
| `can_request_transfer(viewer, instruction)` | ответственный исполнитель, не снято с контроля, нет `pending`-переноса | T-10102; T-10107 |
| `can_decide_transfer(viewer, instruction)` | автор или контролёр, поручение не снято с контроля | T-10102; T-10107 |
| `can_close(viewer, instruction)` | контролёр, есть принятый итоговый отчёт (`date IS NULL`, `decision='accepted'`), нет `pending`-переноса | T-10102; T-10106 |
| `can_view_discipline(viewer)` | `instructions.use` и (`managed_units(viewer)` не пусто или роль администратора без управления); администратор портала отчёт **не получает**, даже если он чей-то руководитель | T-10102; T-10110 |

Заместитель равен руководителю (унаследовано от `managed_units`). Рядовой участник узла управления прав не
получает. Видимость по структуре **дополнительна** к праву `instructions.use` (план). Блокировка
(`state='blocked'`) видимость сохраняет, действия запрещает: каждая `can_*` дополнительно требует
`viewer.state == "active"`.

## 5. Службы `instructions`, исключения, точки подмены и `support_instructions.py`

### 5.1. Службы

Имена модулей — план, «Где живёт код»; имена функций ниже — К4 (тесты берут их дословно).

| Модуль | Публичные функции | Тесты |
|---|---|---|
| `services.access` | раздел 4 | T-10102…T-10107, T-10110 |
| `services.basis` | `all()`, `active()`, `add(actor, title)`, `rename(actor, kind, title)`, `delete(actor, kind)` | T-10103; T-10115 |
| `services.instructions` | `create(actor, *, title, text="", basis_kind, basis_number, basis_date, assignee, deadline, members=(), controller=None, periodicity="", dates=()) -> Instruction`, `update(actor, instruction, **fields) -> Instruction`, `close(actor, instruction) -> Instruction`, `link_task(actor, instruction, *, title, assignee=None, deadline=None) -> Task`, `reassign(user) -> int` | T-10103; T-10106; T-10112; T-10117 |
| `services.dates` | `build(instruction, *, periodicity="", dates=()) -> list[InstructionReportDate]`, `rebuild(instruction, *, deadline=None, periodicity=None, dates=None) -> list`, `next_open(instruction) -> InstructionReportDate | None`, `state_of(instruction) -> str` | T-10104; T-10109 |
| `services.reports` | `submit(actor, instruction, *, date=None, text, files=()) -> InstructionReport`, `add_part(actor, instruction, report_date, *, text, files=()) -> InstructionReportPart`, `decide(actor, report, *, accept, comment="") -> InstructionReport` | T-10105; T-10106 |
| `services.transfers` | `request(actor, instruction, *, new_deadline, reason) -> InstructionTransfer`, `decide(actor, transfer, *, approve, comment="") -> InstructionTransfer` | T-10107 |
| `services.reminders` | `plan(instruction) -> list[InstructionReminder]`, `rebuild(instruction)`, `due(now) -> list`, `cancel_all(instruction, *, reason="")`, `set_ladder(actor, instruction, ladder) -> Instruction` | T-10108 |
| `services.notify_rules` | `recipients(instruction, event, *, actor=None) -> dict[user_id, str]` (при совмещении — один вид с приоритетом), `texts(instruction, kind, **data) -> dict[user_id, str]` | T-10113 |
| `services.digest` | `send(now) -> int` (число уведомлений) | T-10114 |
| `services.registry` | `rows(viewer, *, preset="mine", filters=None, sort="", page=1, per_page=20) -> dict` (ключи `rows`, `total`, `pages`, `page`, `per_page`); `state_of(instruction) -> str` | T-10109 |
| `services.discipline` | `rows(viewer, *, date_from, date_to, unit=None) -> dict` (ключи `rows`, `open_rows`, `totals`); `main_unit(person)` | T-10110 |
| `services.excel` | `build(data) -> bytes` (`.xlsx`, лист «Дисциплина») | T-10110 |
| `services.files` | `store(actor, instruction, upload, *, kind, report=None, part=None) -> InstructionFile`, `bind(report=None, part=None, file_ids=())`, `content(instruction, file, viewer)`, `file_purposes() -> FilePurpose` | T-10116 |
| `services.retention` | `purge(now) -> dict` (ключи `instructions`, `reports`, `parts`, `files`, `transfers`) | T-10118 |
| `services.settings` | `get() -> InstructionSettings`, `save(actor, *, retention_years=None, default_ladder=None) -> InstructionSettings` | T-10115 |
| `tasks.py` (задания) | `instructions_reminders(now=None)`, `instructions_digest(now=None)`, `instructions_retention(now=None)` — в `apps/instructions/tasks.py` | T-10108; T-10114; T-10118 |

### 5.2. Исключения и тексты

`apps/instructions/texts.py` (файл назван планом): `class InstructionsError(Exception)` с `code`, `field`,
`params`; `message` берётся из словаря `TEXTS` того же модуля (К3). Коды и тексты — раздел 12.1. Службы
поднимают `InstructionsError`; представления превращают её в ответ 6.1. Отдельного `services/errors.py` нет —
план называет `texts.py` и не называет `errors.py`.

### 5.3. Точки подмены для тестов

| Что | Точка | Тесты |
|---|---|---|
| Время | `django.utils.timezone.now` (фикстура `clock`) и параметры `now=` у заданий | T-10104, T-10108, T-10114, T-10118 |
| Календарь | `apps.org.services.calendar.day_kind`, `next_working_start`, `is_working_time`, `version` | T-10108 |
| Тихие часы | `next_start(prefs, moment)` возвращает `None` — подмена в `apps.instructions.tasks` (К5: задания зовут `quiet.next_start` через модульное имя, чтобы тест мог подменить) | T-10108 |
| ClamAV | `apps.integrations.clamav.services.scan` (`support_org.scan_clean/found/unavailable`) | T-10116 |
| Очереди | `support_notify.run_jobs("maintenance")` для постановки заданий; сами задания зовутся синхронно | T-10108; T-10114; T-10118 |
| Кэш сводки и «двух None» | `cache` (Valkey база 15) — тест очищает фикстурой `valkey_clean`; ключи `instructions:digest:<ISO-неделя>:<user>` и `instructions:reminder-none:<pk>` | T-10108; T-10114 |
| Увольнение | событие `core.user_dismissed` публикуется помощником `support_org.dismiss(user)` (факт) либо через службу org | T-10102 |

### 5.4. Помощники `tests/support_instructions.py` (пишет только T-10005)

На уровне модуля `apps.instructions` не импортируется; модели — `support.model("instructions.…")`; код служб —
внутри функций.

| Имя | Сигнатура и поведение |
|---|---|
| `PERMISSIONS_010` | `("instructions.use", "instructions.assign")` |
| `staff_user(**extra)` | сотрудник с ролью «Сотрудник ИТ» (`support.make_employee(roles=[support.role_by_name(support.STAFF_ROLE)])`) |
| `viewer(**extra)` | сотрудник с правами `instructions.use` и `instructions.assign` через свою роль |
| `head_of(unit, **extra)` / `deputy_of(unit, **extra)` | сотрудник + членство `mark="head"`/`"deputy"` (`support_org.make_member`) |
| `make_basis(title="Приказ", position=0, active=True)` | строка `InstructionBasisKind` |
| `make_instruction(title="Поручение", *, author=None, controller=None, assignee=None, basis=None, basis_number="12", basis_date=None, deadline=None, text="", members=(), ladder=None, **extra)` | поручение через ORM; по умолчанию автор = контролёр = исполнитель = свежий `staff_user`, основание — `make_basis()` с уникальным названием, срок — `moscow_today() + 30`; возвращает `Instruction` |
| `add_coexecutor(instruction, user)` | строка `InstructionMember` (роль `coexecutor`) |
| `add_report_date(instruction, due_date, position=0, state="waiting")` | строка `InstructionReportDate` |
| `submit_report(client, instruction, *, date=None, text="Отчёт", files=(), **extra)` | `client.post(f"/instructions/{instruction.pk}/reports/", ...)`, по умолчанию обычный запрос; возвращает ответ |
| `add_part(client, instruction, report_date, *, text="Часть", files=(), **extra)` | `client.post(f"/instructions/{instruction.pk}/parts/", ...)` |
| `accept_report(client, report, *, comment="", **extra)` / `return_report(client, report, *, comment="Доработать", **extra)` | `client.post(f"/instructions/reports/{report.pk}/accept/")` и `…/return/` |
| `request_transfer(client, instruction, *, new_deadline, reason="Причина", **extra)` | `client.post(f"/instructions/{instruction.pk}/transfers/", ...)` |
| `decide_transfer(client, transfer, *, approve=True, comment="", **extra)` | `/approve/` или `/reject/` |
| `reminders_of(instruction)` | `list(InstructionReminder.objects.filter(instruction=instruction).order_by("moment", "pk"))` |
| `registry_rows(response_or_html)` | разбор `[data-instruction-id]`: список `{"id", "state", "title"}` в порядке документа |
| `discipline_rows(response_or_html)` | разбор `[data-discipline-row]`: список `{"unit", "person", "in_time", "with_transfer", "overdue"}` |
| `capture_sql(call)` | список SQL вызова (`CaptureQueriesContext`), как `support_tasks` |
| `queries_with_params(call=None)` | пары «SQL, параметры» (контекст, если `call` не передан) — NFR-721 |
| `email_of(user)` / `phone_of(user)` | синтетические контакты без настоящих ПДн |
| `instructions_pages()` | кортеж адресов страниц среза для обходов разметки (К10) |

## 6. Маршруты, поля форм, ответы

Адреса, методы и «кто» — план («Контракты»); здесь — поля форм, параметры, форма ответа и коды. `app_name =
"instructions"`; тесты ходят по путям (К7). Итого 19 HTTP-строк: `GET` и `POST` у `/instructions/new/`,
`/instructions/<id>/` и `/settings/instructions/` — отдельными строками.

### 6.1. Общие правила

| Что | Требование | Тесты |
|---|---|---|
| Вход | все адреса — `@login_required`: без входа GET и POST — 302 на `/login/?next=<путь>`; без второго фактора — прежние слои ядра | T-10103…T-10121 |
| Права страниц | `/instructions/…` — `instructions.use` (403 без него, без обращения к службам); `/settings/instructions/…` — `settings.portal` (403 на GET и POST) | T-10121; T-10115 |
| Запрос HTMX | заголовок `HX-Request: true`; ответ — фрагмент без `<html>` | T-10105; T-10109 |
| Отказ службы на POST | 200 с формой или фрагментом, введённое остаётся; отказ у поля — `[data-error="<поле>"][data-code="<код>"]` рядом с полем, общий отказ — `[role=alert][data-code="<код>"]` (как CONTRACT-006…009, 10.1); `<поле>` — имя из 6.2 | все тесты отказов |
| Успех POST | обычный POST — 302 на адрес из 6.2; HTMX-POST — 200 с фрагментом из 6.2 | T-10103…T-10115 |
| 403, 404 | чужое, несуществующее и удалённое поручение — 404 «Не найдено» (в том числе POST); поручение видно, действие не разрешено — 403 (правка, решения, закрытие, перенос, файл); администратор чужих — 404 | T-10102; T-10105…T-10107 |
| Метод | GET на адрес только для POST — 405 (`require_POST` прежних срезов) | T-10121 |
| Номера | `<int:instruction_id>`, `<int:report_id>`, `<int:transfer_id>`, `<int:kind_id>`, `<uuid:file_id>`; литеральные `list/`, `new/`, `files/`, `reports/`, `transfers/`, `discipline/`, `discipline.xlsx`, `basis/` не путаются с `<id>/` | T-10121 |
| Ключи реестра | `preset`, `basis`, `assignee`, `deadline`, `state`, `q`, `sort`, `page`, `per_page` — белый список; `per_page` — только 20 или 50, иное — 20; `sort` — `deadline` (по умолчанию) или `updated` | T-10109 |
| Период дисциплины | `from`, `to` — даты «ГГГГ-ММ-ДД»; `unit` — номер узла; отсутствие — текущий месяц и свой основной узел | T-10110 |
| Время в адресе | нет (все даты — поля форм и параметры) | — |

### 6.2. Поля форм и ответы по адресам

| Путь | Метод | Кто | Поля | Успех | Отказ и прочее |
|---|---|---|---|---|---|
| `/instructions/` | GET | `instructions.use` | `preset`, `basis`, `assignee`, `deadline`, `state`, `q`, `sort`, `page`, `per_page` | страница: пресеты, фильтры, строки (`[data-instruction-id]`), карточка рядом на широком экране | неверный пресет — «Мои»; пусто — подсказка «Поручений пока нет» |
| `/instructions/list/` | GET | `instructions.use` | те же | фрагмент реестра (`hx-swap` в `#instructions-list`) | пустой — подсказка |
| `/instructions/new/` | GET | `instructions.use`; форма показывает только управляемых | — | форма создания (`[data-instructions-page="new"]`), контролёр по умолчанию — автор | — |
| `/instructions/new/` | POST | `can_assign` | `title`, `text`, `basis_kind`, `basis_number`, `basis_date`, `assignee`, `members`, `deadline`, `controller`, `periodicity`, `dates` | обычный — 302 в `/instructions/<id>/`; HTMX — 200 карточкой | `title_range`, `text_long`, `basis_required` (`basis_kind`/`basis_number`/`basis_date`), `basis_unknown`, `deadline_past`, `deadline_required`, `assignee_required`, `assignee_forbidden`, `assignee_dismissed`, `controller_dismissed`, `member_dismissed`, `member_duplicate`, `member_is_assignee`, `periodicity_invalid`, `date_past`, `date_not_before_deadline` |
| `/instructions/<id>/` | GET | видит поручение | `edit` (1 — форма правки) | карточка (`[data-instructions-page="card"]`): основание, срок, состояние, отчётные даты, отчёты и части, переносы, история, файлы, связанные задачи, лестница | 404 невидимого; удалённое — 404 |
| `/instructions/<id>/` | POST | `can_edit_fields` | `title`, `text`, `basis_kind`, `basis_number`, `basis_date`, `members`, `deadline`, `controller`, `periodicity`, `dates` | обычный — 302 на карточку; HTMX — 200 карточкой; журнал `instructions.changed` | те же коды, что у создания; `deadline` заблокирован при `pending`-переносе; `dates_locked` при смене периодичности с отчётами; нет права — 403 |
| `/instructions/<id>/ladder/` | POST | `can_edit_ladder` | `offsets` (список), `due`, `overdue` | обычный — 302 на карточку; HTMX — 200 блоком лестницы | `ladder_invalid`; пересчёт только будущих `pending` |
| `/instructions/<id>/close/` | POST | `can_close` | `confirm=1` | обычный — 302 на карточку; `closed_at`, отчёты не принимаются, `pending`-напоминания сняты; журнал `instructions.closed` | без `confirm` — 200 второй шаг `[data-instructions-confirm]` с текстом `close_confirm`; не контролёр — `close_forbidden` (200) или 403; нет принятого итогового отчёта — `close_no_report`; есть `pending`-перенос — `close_transfer_pending` |
| `/instructions/<id>/reports/` | POST | `can_report` | `date` (номер отчётной даты; пусто — к сроку), `text`, `files` (номера непривязанных) | обычный — 302 на карточку; HTMX — 200 блоком отчётов; дата → `review`, напоминания даты отменены; журнал `instructions.report_submitted` | `report_forbidden`; `report_empty`; `report_long`; `report_limit` (11-й файл); `report_closed`; `report_date_unknown`; `file_missing` |
| `/instructions/<id>/parts/` | POST | `can_add_part` | `date`, `text`, `files` | обычный — 302 на карточку; HTMX — 200 блоком частей; журнал `instructions.part_added` | `part_forbidden`; `part_duplicate`; `report_empty`; `report_limit`; `report_closed`; `report_date_unknown` |
| `/instructions/reports/<id>/accept/` | POST | `can_decide` | — | обычный — 302 на карточку; дата `accepted`/`closed_at`, поручение → «Ждёт отчёта» по следующей дате; уведомление `report_accepted`; журнал | `decision_forbidden`; `decision_state` (уже рассмотрен); 404 чужого |
| `/instructions/reports/<id>/return/` | POST | `can_decide` | `comment` | обычный — 302; дата `returned`, части остаются; уведомление `report_returned`; журнал | без комментария — `return_comment_required`; `decision_forbidden`; `decision_state` |
| `/instructions/<id>/transfers/` | POST | `can_request_transfer` | `new_deadline`, `reason` | обычный — 302 на карточку; HTMX — 200 блоком переносов; уведомление `transfer` автору и контролёру; журнал `instructions.transfer_requested` | `transfer_forbidden`; `transfer_state` (уже `pending`); `transfer_decided`; `transfer_deadline` (не позже текущего); `transfer_reason`; `transfer_closed` |
| `/instructions/transfers/<id>/approve/` | POST | `can_decide_transfer` | `comment` | обычный — 302; `deadline` = новый, `original_deadline` не меняется, будущие даты и напоминания пересчитаны; уведомление `transfer` исполнителю; журнал `instructions.transfer_decided` | `decision_forbidden`; `transfer_decided` (уже рассмотрен); `transfer_closed` |
| `/instructions/transfers/<id>/reject/` | POST | `can_decide_transfer` | `comment` | обычный — 302; срок не меняется; уведомление `transfer` исполнителю; журнал | комментарий обязателен (`return_comment_required` — общий код причины отказа); прочее как у `approve` |
| `/instructions/files/` | POST | `can_edit_fields` (основание) или `can_report`/`can_add_part` | `file` (multipart), `instruction`, `kind` (`basis`/`report`/`part`), `report`, `part` | 200: «таблетка» `[data-instruction-file="<uuid>"]` со скрытым `input[name="files"][value="<uuid>"]` | `file_too_big` (> 20 МБ), `file_type` (исполняемый/архив с паролем), `report_limit` (11-й к отчёту/части), `file_missing` |
| `/instructions/files/<uuid>/` | GET | видит поручение файла; файл «чистый» | — | оригинал: `X-Accel-Redirect`, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store` | 404: невидимое поручение; текст «Файл ещё проверяется» / «Файл в карантине» |
| `/instructions/discipline/` | GET | `can_view_discipline` | `from`, `to`, `unit` | страница отчёта: две шкалы, разрезы по сотрудникам и отделам, открытые просроченные отдельной строкой, ссылка на Excel | 403 администратору и рядовому; пустой период — нули и подсказка |
| `/instructions/discipline.xlsx` | GET | `can_view_discipline` | `from`, `to`, `unit` | файл `.xlsx`, `Content-Type` книги, те же числа и подписи | те же 403 |
| `/settings/instructions/` | GET, POST | `settings.portal` | `retention_years`, `default_ladder` (`offsets`, `due`, `overdue`), `confirm=1` | сохранение — 302 на `/settings/instructions/`; журнал `instructions.retention_changed` при смене срока | `retention_range`; `ladder_invalid`; уменьшение срока без `confirm` — 200 со вторым шагом и числом к уборке (`retention_decrease`) |
| `/settings/instructions/basis/` | GET, POST | `settings.portal` | `title` | страница справочника; создание — 302 на неё | `basis_title_range`; `basis_title_taken` |
| `/settings/instructions/basis/<id>/` | POST | `settings.portal` | `title`, `position` | 302 на справочник | те же коды |
| `/settings/instructions/basis/<id>/delete/` | POST | `settings.portal` | `confirm=1` | 302; неиспользованный вид удалён, использованный — `active=False` | без `confirm` — 200 второй шаг `basis_delete_confirm` |

### 6.3. Зацепки `data-*` и `id`

Правила: только `data-*`, `id` и классы, которых нет у прежних блоков; без `role="status"`, `role="alert"`,
`data-error`, `data-warning` вне сообщений об отказах форм; без `style=` и `on…=`. Названы планом или задачами и
потому обязательны: `[data-instructions-page]`, `[data-instruction-id]`, `[data-instruction-state]`,
`[data-instructions-preset]`, `[data-report-date]`, `[data-report-state]`, `[data-report-part]`,
`[data-transfer]`, `[data-history]`, `[data-instruction-file]`, `[data-error][data-code]`. Прочие — К9.

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `[data-instructions-page="<имя>"]` | корень содержимого: `registry`, `card`, `discipline`, `settings`, `new` (форма создания) | T-10103…T-10121; e2e |
| `[data-instructions-preset="mine\|control\|subordinate\|overdue"]` | кнопка-пресет реестра; выбранная — `aria-pressed="true"` | T-10109 |
| `[data-instruction-id]` | строка реестра, карточка (номер поручения) | T-10103…T-10110; e2e |
| `[data-instruction-title]` | название в строке и карточке | T-10109; e2e |
| `[data-instruction-state]` | состояние (`control`/`waiting`/`review`/`returned`/`overdue`/`done`), текст по-русски рядом | T-10109; T-10105 |
| `[data-report-date="<id>"]` | блок отчётной даты; `data-report-due="<ISO>"`; внутри `[data-report-state]` ∈ `waiting`/`review`/`returned`/`accepted` | T-10104; T-10105; e2e |
| `[data-report-state]` | состояние отчётной даты (текст «Ждёт отчёта» и т. д.) | T-10105 |
| `[data-report-part="<id>"]` | часть отчёта с автором (`[data-part-author]`) | T-10105 |
| `[data-transfer="<id>"]` | строка переноса; `data-transfer-state` ∈ `pending`/`approved`/`rejected` | T-10107; e2e |
| `[data-history]` | корень истории карточки; записи — строки журнала и переносы | T-10117; e2e |
| `[data-instruction-file="<uuid>"]` | «таблетка» загруженного файла; `data-file-state` ∈ `pending`/`clean`/`quarantine` | T-10116 |
| `[data-instructions-confirm]` | второй шаг снятия с контроля, удаления вида, уменьшения срока хранения | T-10106; T-10115 |
| `[data-ladder]` | блок лестницы; `[data-ladder-offset]` — порог в рабочих днях | T-10108 |
| `[data-discipline-table]` / `[data-discipline-row]` | таблица отчёта и её строка (`data-unit`, `data-person`, `data-in-time`, `data-with-transfer`, `data-overdue`) | T-10110; e2e |
| `[data-form="instruction-new\|instruction-edit\|instruction-report\|instruction-part\|instruction-transfer\|instruction-close\|instructions-filters\|discipline-form\|basis-form"]` | формы среза (для помощников приёмки) | e2e |
| `[data-instruction-field="title\|text\|basis_kind\|basis_number\|basis_date\|assignee\|members\|deadline\|controller\|periodicity\|dates\|date\|new_deadline\|reason\|comment\|ladder\|retention_years"]` | поле формы и карточки (запасной путь без JS) | T-10103…T-10115; e2e |
| `[data-decide="accept\|return"]` | кнопка решения по отчёту | T-10105; e2e |
| `[data-error="<поле>"][data-code="<код>"]` | отказ у поля (раздел 6.1) | все тесты отказов |

## 7. Отчётные даты и статусы

| Что | Требование | Тесты |
|---|---|---|
| Источники дат | периодичность (`weekly`/`monthly`/`quarterly`) или список дат; обе формы допустимы в одной заявке, совпадающие даты схлопываются | T-10104 |
| Хранение периодичности | периодичность не поле модели (план её не перечисляет): она приходит из формы в `build`/`rebuild` вместе со списком дат; ряд строится каждый раз заново, а сохранённые даты с отчётами остаются (К21) | T-10104 |
| Начало ряда | строго после даты постановки: еженедельно — тот же день недели через 7 дней; ежемесячно — то же число следующего месяца; ежеквартально — то же число через 3 месяца | T-10104 |
| 31-е и 29.02 | число больше длины месяца — последний день месяца (31 → 30/28/29); 29.02 в невисокосный год → 28.02 | T-10104 |
| Обрезка | ряд обрезается **строго до** срока; дата, равная сроку, не создаётся (итоговый отчёт «к сроку» один) | T-10104 |
| Прошедшие даты | ручной список с датой `<= moscow_today()` отклоняется (`date_past`); дата `>= deadline` — `date_not_before_deadline` | T-10104 |
| Пересборка | смена срока/периодичности пересобирает только будущие даты без отчётов; даты с отправленным или принятым отчётом сохраняются; смена периодичности при таких датах — `dates_locked`; ранний отчёт к будущей дате сохраняется | T-10104 |
| Состояния даты | `waiting` → `review` (отчёт отправлен) → `returned` (возврат с комментарием) → `waiting`; `accepted` закрывает дату (`closed_at`); отправка заранее сразу даёт `review` | T-10105; T-10107 |
| Статус поручения | `done` при `closed_at`; иначе `overdue`, если `deadline < moscow_today()` или ближайшая незакрытая дата `due_date < moscow_today()`; иначе по ближайшей незакрытой дате: `review` → «Отчёт на проверке», `returned` → «Возвращено», `waiting` и `due_date <= moscow_today()` → «Ждёт отчёта»; иначе «На контроле». Приоритет «Просрочено» выше всех, кроме «Исполнено»; ручной установки нет (К4) | T-10109; T-10105 |
| «Ближайшая» | `next_open` — строка с минимальной `due_date` среди дат без `accepted`; если таких нет — `None`, и `state_of` берёт срок (`deadline`) | T-10104; T-10109 |
| Дата в карточке | даты показаны по возрастанию (`position`), принятые — с пометкой «Принято», просроченные — с пометкой «Просрочено» | T-10105 |

## 8. Напоминания

| Что | Требование | Тесты |
|---|---|---|
| Длина | `deadline − created_at.date()` в календарных днях; границы — календарные месяцы: ≤ 1 месяца, > 1 и ≤ 6, > 6 (К11; без `dateutil`: сравнение с `created + 1/6 месяцев` через последний день месяца) | T-10108 |
| Пороги срока | ≤ 1 месяца — 3 и 1 рабочий день; > 1 и ≤ 6 — ещё 14 и 7; > 6 — ещё 30; `due` — начало рабочего дня срока; `overdue` — начало следующего рабочего дня | T-10108 |
| Пороги отчёта | на каждую отчётную дату — `r3` и `r1` (3 и 1 рабочий день до неё); просрочка отчёта — следующий рабочий день после даты (уведомление контролёру, не напоминание) | T-10108; T-10113 |
| Момент | начало рабочего дня (`calendar.day_kind`/`next_working_start`), по Москве; нерабочая дата — первый рабочий день после; прошедшие пороги при создании и пересборке не создаются | T-10108 |
| Тихие часы | при планировании и **перед отправкой** момент сдвигается `quiet.next_start(prefs, moment)` по настройкам получателя; `None` — остаётся `pending` до следующего цикла; повторный `None` — `cancelled` и запись `instructions.reminder_failed` (ключ `instructions:reminder-none:<pk>`, TTL 24 ч) | T-10108 |
| Получатели | исполнитель и соисполнители; дублей нет (уникальность `(instruction, date, user, kind, stage)` при `pending`) | T-10108 |
| Отмена | отправка отчёта к дате отменяет `pending` этой даты; снятие с контроля — все `pending`; перенос — пересборка будущих | T-10105; T-10106; T-10107 |
| Правка лестницы | `ladder` JSON: `offsets` 1–60 по возрастанию без повторов, `due`/`overdue` — `bool`; пустой — умолчание `InstructionSettings.default_ladder`; правка — только будущие `pending`, `sent` не трогаются; `ladder_invalid` при нарушении | T-10108; T-10115 |
| Идемпотентность | `instructions_reminders` берёт `pending` с `moment <= now`, создаёт уведомление и ставит `sent`; повторный запуск не дублирует | T-10108 |

## 9. Уведомления и сводка

### 9.1. Виды (`apps/instructions/notify_kinds.py`)

| Код | Название | `order` | Каналы по умолчанию | Внешний текст |
|---|---|---|---|---|
| `instructions.assigned` | «Вам поручено» | 220 | портал, почта | «Вам поручено» |
| `instructions.deadline` | «Срок поручения приближается» | 221 | портал, почта | «Срок поручения приближается» |
| `instructions.report_due` | «Нужен отчёт по поручению» | 222 | портал, почта | «Нужен отчёт по поручению» |
| `instructions.report_overdue` | «Отчёт по поручению просрочен» | 223 | портал, почта | «Отчёт по поручению просрочен» |
| `instructions.overdue` | «Поручение просрочено» | 224 | портал, почта | «Поручение просрочено» |
| `instructions.report_submitted` | «Отчёт по поручению пришёл» | 225 | портал, почта | «Отчёт по поручению пришёл» |
| `instructions.report_accepted` | «Отчёт принят» | 226 | портал, почта | «Отчёт принят» |
| `instructions.report_returned` | «Отчёт возвращён» | 227 | портал, почта | «Отчёт возвращён» |
| `instructions.transfer` | «Перенос срока» | 228 | портал, почта | «Перенос срока поручения» |
| `instructions.digest` | «Сводка по поручениям» | 229 | портал, почта | «Сводка по поручениям» |

Ссылка на объект — `instructions.instruction:<номер>` (К12): по ней `still_relevant` находит поручение и
проверяет видимость, закрытие и удаление; на неё же ведёт `url` уведомления (`/instructions/<id>/`). Модуль —
«Поручения»; внешний текст постоянный, без названия, текста поручения и основания (NFR-723).

### 9.2. Получатели (`services.notify_rules.py`)

| Событие | Кому | Тесты |
|---|---|---|
| `assigned` | исполнитель и соисполнители; автору — нет | T-10113 |
| `deadline` (лестница) | исполнитель и соисполнители | T-10113 |
| `report_due` (r3/r1) | исполнитель и соисполнители | T-10113 |
| `report_overdue` | контролёр и автор (без исполнителя) | T-10113 |
| `overdue` | исполнитель, соисполнители, контролёр, автор | T-10113 |
| `report_submitted` | контролёр и автор, кроме отправителя | T-10113 |
| `report_accepted`, `report_returned` | исполнитель и соисполнители, кроме решившего | T-10113 |
| `transfer` (запрос) | контролёр и автор, кроме запросившего | T-10113 |
| `transfer` (решение) | исполнитель, кроме решившего | T-10113 |
| `digest` | контролёр и автор | T-10114 |
| Совмещение ролей | человек получает **одно** сообщение с приоритетом: `overdue` → `report_overdue` → `report_submitted` → `report_accepted` → `report_returned` → `transfer` → `digest` | T-10113 |
| Свои действия | назначил себе — уведомления нет; перенос себе — нет; сводка о своих — есть | T-10113 |
| Письмо | через `email_delay_minutes` (15 по умолчанию, настройка среза 004), не константа; отключённая почта — письма нет, портал есть | T-10113 |

### 9.3. Сводка

`instructions_digest` (каждые 15 минут) в первый рабочий день недели, в начале рабочего дня получателя:
атомарный `cache.add("instructions:digest:<ISO-неделя>:<user>", 1, timeout=…)`; при успехе — одно уведомление
`instructions.digest` со сроками исполнения и отчётными датами на ближайшие 30 дней и просроченными; пустая
сводка не отправляется; повторный запуск не дублирует; отключённые каналы не ошибка (К13).

## 10. Журнал и история

### 10.1. Записи

| Событие | Когда | Что в записи | Тесты |
|---|---|---|---|
| `instructions.created` | создание | номер, название, исполнитель, срок, основание (вид, номер, дата) | T-10117 |
| `instructions.changed` | изменение поля | `before`/`after` по полям: `title`, `text`, `basis`, `deadline`, `controller`, `members`, `periodicity` | T-10117 |
| `instructions.report_submitted` | отправка сводного отчёта или части | номер поручения, отчёт/часть, дата; **без текста** | T-10117; T-10105 |
| `instructions.report_accepted` | принятие | номер отчёта, дата, контролёр | T-10117 |
| `instructions.report_returned` | возврат | номер отчёта, дата, комментарий (до 2 000) | T-10117 |
| `instructions.part_added` | добавление части | номер даты, автор; без текста | T-10117 |
| `instructions.transfer_requested` | запрос переноса | старый и новый срок, причина | T-10117; T-10107 |
| `instructions.transfer_decided` | решение | решение, комментарий, кто решил | T-10117 |
| `instructions.closed` | снятие с контроля | номер, контролёр, дата | T-10117; T-10106 |
| `instructions.reassigned` | увольнение контролёра/исполнителя | поле, было/стало, причина «уволен» | T-10117; T-10102 |
| `instructions.retention_changed` | смена срока хранения | `years` «было / стало» | T-10115; T-10118 |
| `instructions.retention_purged` | ночная уборка удалила > 0 | число поручений/отчётов/файлов; повтор без удаления — записи нет; **без текста** | T-10118 |
| `instructions.reminder_failed` | повторный `None` от тихих часов | номер поручения и получатель; поручение не ломается | T-10108 |

История карточки — записи `core.AuditEvent` по объекту `instructions.instruction` (плюс отчёты и переносы,
связанные по номеру) и строки `InstructionTransfer`; первая строка — «создал поручение». Журнал только
дополняется (NFR-727).

### 10.2. Подписи (`apps/instructions/audit_labels.py`)

| Раздел | Записи |
|---|---|
| `actions` | `instructions.created` — «Поручение создано»; `.changed` — «Поручение изменено»; `.report_submitted` — «Отчёт отправлен»; `.report_accepted` — «Отчёт принят»; `.report_returned` — «Отчёт возвращён»; `.part_added` — «Добавлена часть отчёта»; `.transfer_requested` — «Запрошен перенос срока»; `.transfer_decided` — «Решение по переносу»; `.closed` — «Поручение снято с контроля»; `.reassigned` — «Сменён контролёр или исполнитель»; `.retention_changed` — «Срок хранения поручений изменён»; `.retention_purged` — «Поручения удалены по сроку»; `.reminder_failed` — «Напоминание не создано» |
| `fields` | `title` — «название»; `text` — «текст»; `basis` — «основание»; `deadline` — «срок»; `controller` — «контролёр»; `assignee` — «исполнитель»; `members` — «соисполнители»; `periodicity` — «периодичность»; `years` — «срок хранения, лет»; `instructions` — «Удалено по сроку, поручений» |
| `object_types` | `instructions.instruction` — «поручение»; `instructions.report` — «отчёт по поручению»; `instructions.transfer` — «перенос срока»; `instructions.settings` — «настройки поручений»; `instructions.basis` — «вид основания» |
| `values` | `{}` (службы пишут значения по-русски сами, как в мессенджере и задачах) |

## 11. Реестр, дисциплина и Excel

| Что | Требование | Тесты |
|---|---|---|
| Видимость реестра | `author`/`controller`/`assignee`/соисполнитель или `manages(viewer, assignee)` или `manages(viewer, author)`; администратор чужих не видит | T-10109 |
| Пресеты | `mine` (исполнитель или соисполнитель), `control` (контролёр), `subordinate` (ответственный в управляемых узлах, **кроме собственных**), `overdue` (статус «Просрочено»); неизвестный — `mine` | T-10109 |
| Фильтры | `basis` (номер вида), `assignee`, `deadline` (`overdue`/`today`/`week`/`month`/`none`), `state` (`control`/`waiting`/`review`/`returned`/`overdue`/`done`), `q` (название и номер); «Сбросить» возвращает пресет | T-10109 |
| Порядок и страницы | по умолчанию срок, затем изменение (оба по возрастанию, пустой срок — в конце); `sort=updated` — изменение; страницы 20/50, `total`/`pages`/`page` | T-10109 |
| SQL | фильтры словарём, значения — параметрами; сортировки — из белого списка; поиск — `ILIKE` по названию и номеру; цепочка узлов — массивом `= ANY(%s)` (NFR-721) | T-10109 |
| Дисциплина: население | поручения, снятые с контроля (`closed_at`) в периоде `from…to` включительно, по подразделению (`unit` — узел и вложенные) | T-10110 |
| Дисциплина: шкалы | по исходному сроку: «в срок», «с переносом» (был согласованный перенос и исполнено не позже срока с переносами), «просрочено»; по сроку с переносами: «в срок», «просрочено»; категории внутри разреза взаимоисключающие | T-10110 |
| Последний перенос | срок с переносами — последний согласованный (`approved`) перенос с `decided_at <= closed_at`, иначе `deadline` | T-10110 |
| Открытые просроченные | отдельной строкой, в три категории не входят | T-10110 |
| Разрезы | по сотрудникам (ответственный) и отделам (`main_unit`: первый не-корневой узел по `path`, иначе корень) | T-10110 |
| Администратор | отчёт не получает: 403, даже если он чей-то руководитель | T-10110 |
| Excel | `discipline.xlsx` — книга `openpyxl`, лист «Дисциплина», те же числа и русские подписи | T-10110 |
| Карточка сотрудника | поручения не показываются: `card_sections` не регистрируется (план, «Точки расширения») | T-10122 |

## 12. Коды, поля и тексты отказов

Тексты — словарь `TEXTS` модуля `apps/instructions/texts.py` (К3); ключ — код (`data-code`,
`InstructionsError.code`). Подстановок две: `retention_decrease` (число поручений). Тест ищет текст в разметке
подстрокой; коды — К8.

### 12.1. Отказы

| Код | Поле | Текст | Тесты |
|---|---|---|---|
| `title_range` | `title` | «Название поручения — от 1 до 300 знаков» | T-10103 |
| `text_long` | `text` | «Текст поручения — не длиннее 10 000 знаков» | T-10103 |
| `basis_required` | `basis_kind`, `basis_number`, `basis_date` | «Основание обязательно: вид, номер и дата» | T-10103 |
| `basis_unknown` | `basis_kind` | «Такого вида основания нет в справочнике» | T-10103 |
| `deadline_required` | `deadline` | «Укажите срок исполнения» | T-10103 |
| `deadline_past` | `deadline` | «Срок не может быть раньше сегодняшнего дня» | T-10103 |
| `assignee_required` | `assignee` | «Выберите ответственного исполнителя» | T-10103 |
| `assignee_forbidden` | `assignee` | «Поставить поручение этому сотруднику нельзя» | T-10102 |
| `assignee_dismissed` | `assignee` | «Сотрудник уволен: поручение поставить нельзя» | T-10103 |
| `controller_dismissed` | `controller` | «Сотрудник уволен: контролёром не назначить» | T-10103 |
| `member_dismissed` | `members` | «Сотрудник уволен: в соисполнители не добавить» | T-10103 |
| `member_duplicate` | `members` | «Этот сотрудник уже в составе поручения» | T-10103 |
| `member_is_assignee` | `members` | «Исполнитель уже назначен: в соисполнители его не указывают» | T-10103 |
| `periodicity_invalid` | `periodicity` | «Периодичность — еженедельно, ежемесячно или ежеквартально» | T-10104 |
| `date_past` | `dates` | «Отчётная дата не может быть в прошлом» | T-10104 |
| `date_not_before_deadline` | `dates` | «Отчётная дата — раньше срока исполнения» | T-10104 |
| `dates_locked` | `periodicity` | «Периодичность не сменить: по отчётным датам уже есть отчёты» | T-10104 |
| `edit_forbidden` | `title` | «Нет права менять поручение» | T-10102 |
| `report_forbidden` | `text` | «Отчёт пишет ответственный исполнитель поручения» | T-10105 |
| `report_empty` | `text` | «Напишите текст отчёта» | T-10105 |
| `report_long` | `text` | «Текст отчёта — не длиннее 10 000 знаков» | T-10105 |
| `report_limit` | `file` | «Не больше 10 файлов к отчёту или части» | T-10105; T-10116 |
| `report_closed` | `text` | «Поручение снято с контроля: отчёты не принимаются» | T-10106 |
| `report_date_unknown` | `date` | «Такой отчётной даты в поручении нет» | T-10105 |
| `part_forbidden` | `text` | «Часть отчёта добавляет соисполнитель или ответственный» | T-10105 |
| `part_duplicate` | `text` | «Часть к этой дате уже добавлена» | T-10105 |
| `decision_forbidden` | `comment` | «Принимает и возвращает отчёт только контролёр» | T-10105 |
| `decision_state` | `comment` | «Отчёт уже рассмотрен» | T-10105 |
| `return_comment_required` | `comment` | «Укажите причину возврата или отказа» | T-10105; T-10107 |
| `transfer_forbidden` | `reason` | «Перенос просит ответственный исполнитель» | T-10107 |
| `transfer_state` | `reason` | «По поручению уже есть запрос переноса» | T-10107 |
| `transfer_decided` | `reason` | «Запрос переноса уже рассмотрен» | T-10107 |
| `transfer_deadline` | `new_deadline` | «Новый срок — позже текущего» | T-10107 |
| `transfer_reason` | `reason` | «Причина переноса — от 1 до 1 000 знаков» | T-10107 |
| `transfer_closed` | `reason` | «Поручение снято с контроля: перенос не оформить» | T-10107 |
| `close_forbidden` | `confirm` | «Снять с контроля может только контролёр» | T-10106 |
| `close_no_report` | `confirm` | «Нужен принятый итоговый отчёт» | T-10106 |
| `close_transfer_pending` | `confirm` | «Сначала решите запрос переноса» | T-10106 |
| `close_confirm` | `confirm` | «Снять поручение с контроля?» | T-10106 |
| `ladder_invalid` | `ladder` | «Лестница: от 1 до 60 рабочих дней, по возрастанию, без повторов» | T-10108; T-10115 |
| `file_too_big` | `file` | «Файл больше 20 МБ» | T-10116 |
| `file_type` | `file` | «Файл такого типа не принимается» (исполняемый, архив с паролем) | T-10116 |
| `file_missing` | `file` | «Файл не найден» | T-10116 |
| `retention_range` | `retention_years` | «Срок хранения — от 1 до 10 лет» | T-10115 |
| `retention_decrease` | `confirm` | «Ближайшая уборка удалит поручений: {count}» | T-10115 |
| `basis_title_range` | `title` | «Название вида — от 1 до 100 знаков» | T-10115 |
| `basis_title_taken` | `title` | «Вид с таким названием уже есть» | T-10115 |
| `basis_delete_confirm` | `confirm` | «Удалить вид основания?» | T-10115 |
| `task_forbidden` | `task` | «Создать задачу можно с правом работы с задачами» | T-10112 |
| `task_missing` | `task` | «Задача не найдена или недоступна» | T-10112 |

Отказы службы `tasks` при создании задачи из поручения (срок в прошлом, чужой исполнитель и т. п.) приходят
своими кодами `tasks` и показываются у поля задачи; контракт их не дублирует.

### 12.2. Тексты интерфейса (в `TEXTS` не входят)

«Поручений пока нет»; «Ничего не найдено»; «Мои», «На моём контроле», «Подчинённых», «Просроченные»;
«На контроле», «Ждёт отчёта», «Отчёт на проверке», «Возвращено», «Просрочено», «Исполнено»; «Принято»;
«Снять с контроля», «Отправить отчёт», «Добавить часть», «Принять», «Вернуть», «Просить перенос»,
«Согласовать», «Отклонить»; «Назад»; «Сбросить»; «Показать ещё»; «Файл ещё проверяется»; «Файл в карантине»;
«Скачать»; «История»; «Поручение создано», «Поручение изменено», «Отчёт отправлен», «Отчёт принят»,
«Отчёт возвращён», «Запрошен перенос срока», «Поручение снято с контроля»; «Основание»; «Отчётность»;
«Дисциплина»; «Поручения»; «Настройки поручений»; «Хранить поручения, лет»; «Виды основания»; «Добавить вид».
Время — по Москве. Видимые надписи страниц, которые сверяет T-10121: «Поручения» на `/instructions/`,
«Настройки поручений» на `/settings/instructions/`, «Дисциплина» на `/instructions/discipline/`.

## 13. Стенд, нагрузка, помощники приёмки

### 13.1. Команды стенда

| Команда | Требование | Тесты |
|---|---|---|
| `e2e_instructions_seed` | `apps/instructions/management/commands/e2e_instructions_seed.py`; `require_stand()` первой строкой; создаёт четыре вида основания (`get_or_create` по названию) и три поручения (своё подчинённому, с соисполнителем и отчётной датой, с переносом) для сценариев; строка итога `e2e_instructions_seed: instructions=3 basis=4`; повторный запуск не дублирует | T-10123; e2e |
| Сброс | `helpers_sd.reset_stand_and_relogin()` перед кругом; `instructions` — последний зарегистрированный, зовётся первым (раздел 1.3) | e2e |

Поручения команды создаются через модели (не через форму): стенд нужен до появления прав сценариев; autor —
первый действующий сотрудник, исполнитель — второй, контролёр — первый; даты — от `moscow_today()`.

### 13.2. Нагрузка (NFR-720, NFR-728)

| Что | Требование | Тесты |
|---|---|---|
| `fill_instructions.py` | `backend/tests/load/fill_instructions.py`; только при `E2E_STAND=1`; 1 000 поручений на 100 сотрудников (отчётные даты, отчёты, переносы, напоминания); строка `fill_instructions: instructions=<число>` | T-10121; T-10150 |
| `InstructionUser` | класс в `backend/tests/load/locustfile.py`: реестр с пресетами, карточка, отправка отчёта, решение, дисциплина; рядом прежние `FeedUser`, `MessengerUser`, `NotifyUser`, `TaskUser` | T-10121; T-10150 |
| Замер | NFR-720 — только после отдельного решения владельца (T-10304): p95 ≤ 500 мс при 100 пользователях; ограничение стенда записывается | T-10304 |

### 13.3. Помощники приёмки `tests/e2e/helpers_instructions.py` (пишет только T-10006)

Локаторы — только зацепки раздела 6.3; имена — К10. Прежние помощники — `helpers` (`Account`, `sign_in`,
`make_employee`, `no_horizontal_scroll`), `helpers_org` (`create_unit`, `add_members`, `set_marks`),
`helpers_sd` (`reset_stand_and_relogin`).

| Имя | Сигнатура и поведение |
|---|---|
| `InstructionsCast` | `NamedTuple` учёток `helpers.Account`: `assignee` (рядовой), `peer` (соисполнитель), `head` (руководитель узла assignee), `deputy`, `outsider` (другой узел), `admin` (администратор портала), `dismissed`; узлы `it_unit`, `nested_unit`, `other_unit` — номера строкой |
| `instructions_cast(admin_page, mailpit, new_context) -> InstructionsCast` | роли, узлы и учётки через интерфейс (`helpers.make_employee`, `helpers_org.create_unit`) |
| `open_instructions(context, account, preset="mine", **params) -> Page` | сессия в `context`, вход и `/instructions/`; ждёт `[data-instructions-page="registry"]` |
| `create_instruction(page, title, *, basis=None, basis_number="12", basis_date=None, assignee=None, deadline=None, periodicity=None, dates=()) -> int` | форма «Новое поручение» (`form[data-form="instruction-new"]`, поля `[data-instruction-field]`), возвращает номер из `[data-instruction-id]` |
| `open_card(context, account, instruction_id) -> Page` | сессия в `context`, `/instructions/<id>/`; ждёт `[data-instructions-page="card"]` |
| `submit_report(page, text, *, files=())` | форма отчёта (`form[data-form="instruction-report"]`), ждёт `[data-report-state]` ≠ «Ждёт отчёта» |
| `accept_report(page, report_id)` / `return_report(page, report_id, comment)` | кнопка `[data-decide="accept\|return"]`, ждёт смену `[data-report-state]` |
| `request_transfer(page, new_deadline, reason)` | форма `form[data-form="instruction-transfer"]`, ждёт `[data-transfer][data-transfer-state="pending"]` |
| `decide_transfer(page, transfer_id, approve=True, comment="")` | кнопки `[data-decide="approve\|reject"]`, ждёт новое состояние `[data-transfer]` |
| `close_instruction(page)` | форма `form[data-form="instruction-close"]`, ждёт `[data-instruction-state="done"]` |
| `open_discipline(context, account, **params) -> Page` | `/instructions/discipline/` с `from`/`to`/`unit`; ждёт `[data-discipline-table]` |
| `export_excel(page)` | скачивание `instructions/discipline.xlsx`, возвращает путь временного файла |
| `check_360(page)` | ширина 360 px, `helpers.no_horizontal_scroll(page)` истинно; таблица дисциплины прокручивается внутри `[data-discipline-table]` |

## 14. Что меняется в прежних контрактах и тестах (для T-10111)

Сами `CONTRACT.md`, `CONTRACT-002.md` … `CONTRACT-009.md` не правятся (план). Здесь — какие их строки
устаревают со срезом 010 и чем заменяются; точные правки прежних тестов делает T-10111 по таблице TASKS-010 и
только с разрешения владельца, по одному тесту, диффом «было / стало» (решение 2 задач).

| Что устаревает | Было | Стало |
|---|---|---|
| Перечень `Purpose` | семь значений, `task` последним | восемь, `instruction` последним (T-10002) |
| Число прав | двадцать | двадцать две; «Сотрудник ИТ» получает `instructions.use` и `instructions.assign` (T-10003) |
| Хвост `INSTALLED_APPS` | `apps.tasks` последний | `apps.instructions` последний (T-10001) |
| Число `register` в cron | двадцать четыре | двадцать семь (T-10007) |
| Меню | восемнадцать пунктов у администратора | двадцать; «Поручения» order 3, «Настройки поручений» 66 (T-10121) |
| Виды уведомлений | тридцать | сорок (T-10113) |
| `location` nginx с `25m` | три | четыре (T-10009) |
| `stand_reset` | `tasks` последний | `instructions` последний, вызывается первым (T-10008) |
| «Без задач» | снимается `tasks` | снимаются `tasks` и `instructions` (решение 4 задач) |
| e2e каталога и меню | без видов и пунктов поручений | +10 видов, +2 пункта (T-10111) |

Полная таблица строк T-10111 (1–22 с 18а) — в TASKS-010 и PLAN-010; T-10111 исполняется **после** T-10002,
T-10003, T-10007 и **до** T-10160 (решение 2 задач). Строки 11–16, 18, 18а и 22 правятся партиями Этапа 3, когда
появляется их поведение (решение 18 задач); до этого прежние тесты остаются зелёными.

## 15. Решения контракта

| № | Решение | Почему |
|---|---|---|
| К1 | Метка приложения `instructions`, класс `InstructionsConfig`, `verbose_name = "Поручения"` | как `tasks`/`TasksConfig`; имя метки не пересекается с прежними |
| К2 | Имена шаблонов и иконок раздела 1.1 | план называет только каталог `templates/instructions/`; имена нужны тестам и T-10006 |
| К3 | `InstructionsError` и `TEXTS` — в `apps/instructions/texts.py`; `__str__` поручения — `#<pk> <title>`; отдельного `services/errors.py` нет | план называет `texts.py` и не называет `errors.py` |
| К4 | Состояние поручения вычисляется (`state_of`), поля `status` нет; приоритет «Просрочено» выше всех, кроме «Исполнено» | FR-717; план, «Модель данных» |
| К5 | Задания зовут `quiet.next_start` через модульное имя, чтобы тест мог подменить возврат `None` | план требует проверку `None`; подмена иначе задела бы `notify` |
| К6 | Имена служб и сигнатуры раздела 5.1; все задания — в `apps/instructions/tasks.py`, очередь `maintenance` | «Где живёт код» называет модули, не функции; очередь — как у прежних заданий |
| К7 | `app_name = "instructions"`; тесты ходят по путям, а не по именам маршрутов | как CONTRACT-006…009 |
| К8 | Коды и тексты раздела 12.1 | T-10004; план текстов не задавал (решение 14 задач) |
| К9 | Зацепки раздела 6.3 обязательны; прочие `data-*` — на усмотрение исполнителя, если не ломают приёмку | как К11 CONTRACT-009 |
| К10 | Имена и сигнатуры `helpers_instructions.py` раздела 13.3; `support_instructions.instructions_pages()` — адреса страниц | T-10006/T-10005; локаторы — зацепки контракта |
| К11 | Границы лестницы — календарные месяцы (`created + 1`/`+ 6` месяцев, конец месяца), без `dateutil` | план: «не больше месяца», «не больше полугода»; `openpyxl` есть, `dateutil` в зависимостях нет |
| К12 | Ссылка на объект уведомления — `instructions.instruction:<pk>`; `url` — `/instructions/<pk>/` | по ссылке `still_relevant` проверяет видимость, закрытие и удаление |
| К13 | Redis-ключ сводки — `instructions:digest:<ISO-неделя>:<user>`, значение `1`, срок — до конца недели по Москве | план, «Уведомления и сводка»; NFR-724 |
| К14 | Срок хранения — календарное вычитание лет (29.02 → 28.02), отсчёт от `closed_at` | план, «Хранение»; NFR-729 |
| К15 | «Сегодня» и просрочка — по Москве (`moscow_today`); момент срока — начало рабочего дня срока | как К12 CONTRACT-009; NFR-726 |
| К16 | `deadline_past` проверяется только когда срок задаётся или меняется; ставший прошлым срок не мешает правке других полей | иначе нельзя было бы править просроченное поручение |
| К17 | Пункты меню с `order` 65 сортируются по `(order, title)`: «Настройки поручений» 66 идёт после всех 65 | решение 17 задач среза 009; ядро уже сортирует по `(order, title)` (факт) |
| К18 | Отчёт и часть: текст обязателен, до 10 000; файлов до 10 на отчёт или часть; части переживают возврат | план, «Отчёты и части»; FR-706, FR-723 |
| К19 | Уникальность напоминаний — `(instruction, date, user, kind, stage)` при `pending` с `nulls_distinct=False`; `date` пусто у срока | план, «Модель данных»; FR-709 |
| К20 | `ladder` JSON — `{"offsets": [...], "due": bool, "overdue": bool}`; пустой объект — умолчание настроек | план, «Модель данных»; FR-709 |
| К21 | Периодичность отчётных дат не хранится в модели: `build`/`rebuild` получают её из формы; ряд строится заново, даты с отчётами сохраняются, смена периодичности при таких датах — `dates_locked` | план не перечисляет поле `periodicity`; FR-705, FR-717 |