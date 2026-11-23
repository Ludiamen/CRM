---
id: PLAN-010
вид: план
статус: утверждён
версия: 2
зависит_от: SPEC-010, CONST, ADR-0002, ADR-0004, ADR-0009, ADR-0010, ADR-0013, ADR-0017, ADR-0018, REF-MOD-INST, REF-SRC, REF-UX, TGT-ARCH, TGT-NFR, SPEC-002, SPEC-004, SPEC-007, SPEC-009
основан_на: SPEC-010 sha256:c86c5fabb7ea017d6043b5590c961d7332c16f275c6420ccee264d8b7da8d42e
подпись: Максим | 2026-11-23T16:08+03:00 | sha256:0c1d373ab12e0af6dfe439b793dd568d27ab97b33e527193307a0dee2083893e
---

# План среза 010: Поручения и контроль исполнения

## Сверка с конституцией

- **модуль-приложение** — новое приложение `apps.instructions`; оно **зависит от `apps.tasks`** (связь
  `InstructionTask.task`), поэтому отключается только вместе с задачами; связи с ядром через точки
  `menu_items`, `notification_kinds`, `audit_labels`, `file_purposes`, `stand_reset`.
- **настройка-без-кода** — виды основания, лестница, срок хранения и права — данные.
- **пдн-152фз** — администратор не читает чужие поручения, во внешних каналах только событие и ссылка,
  хранение 3 года после снятия с контроля.
- **sql-только-параметры** — реестр, дисциплина и Excel — параметрами, ключи из белого списка.
- **аудит-изменений** — журнал только дополняется; все поля, части, отчёты и переносы — «было/стало».
- **стек-интерфейс** — HTMX, без состояния на клиенте; Excel — серверный `openpyxl`.
- **эталон-не-копия** — берём контроль после завершения и выгрузку, не вёрстку.

## Технический контекст

### Новые компоненты и лицензии

Новых пакетов нет: `openpyxl==3.1.5` уже в `requirements.txt`; файлы — `core.services.uploads`, ClamAV —
существующий (таймаут 120 с, NFR-722 понимает «минуту» как типичное сканирование, а не жёсткий предел; тесты
подменяют `scan`). Новых JS нет.

### Где живёт код

```
backend/apps/instructions/
  apps.py, models.py, extensions.py, urls.py, notify_kinds.py, audit_labels.py, texts.py, stand.py, tasks.py
  migrations/0001_initial.py, 0002_initial_data.py
  services/   access, basis, instructions, dates, reports, files, transfers, reminders, notify_rules, digest,
              registry, discipline, excel, retention, settings
  views/      pages, actions, reports, files, transfers, settings
  templates/instructions/…   static/instructions/{instructions.js,instructions.css}
backend/tests/test_instructions_*.py, tests/e2e/test_t10_*.py, tests/CONTRACT-010.md
backend/tests/load/fill_instructions.py, класс InstructionUser в locustfile.py
```

### Изменения ядра и прежних модулей

| Файл | Изменение | Зачем |
|---|---|---|
| `core/models/files.py` + `core 0014` | `Purpose.INSTRUCTION = "instruction"` в конце перечня | файлы основания, отчётов, частей |
| данные установки `core 0015` | права `instructions.use`, `instructions.assign` — «Администратору портала» и «Сотруднику ИТ» | права-данные (FR-702/703) |
| `config/settings.py` | `"apps.instructions"` после `"apps.tasks"` последним; приложение требует `tasks` | связь с задачами |
| `config/urls.py` | `include("apps.instructions.urls")` под `apps.is_installed("apps.instructions")` и `tasks` | адреса |
| `config/cron.py` | `instructions_reminders` (`*/5`, 300), `instructions_digest` (`*/15`, 300), `instructions_retention` (`43 23`, 600) под `is_installed` | задания |
| `deploy/nginx.conf`, `nginx.prod.conf` | `location ~ ^/instructions/files/$` 25m | файлы |
| `templates/_assets.html` | `instructions.css`, `instructions.js` для `/instructions/` и `/settings/instructions/` (условие по обоим префиксам) | страницы |

### Точки расширения ядра

| Точка | Что регистрирует `instructions` | Тест |
|---|---|---|
| `menu_items` | «Поручения» (`/instructions/`, icon `icons/instructions.html`, order **3**, право `instructions.use`) и «Настройки поручений» (`/settings/instructions/`, icon `icons/gear.html`, order **66**, `settings.portal`) | T-10121 |
| `notification_kinds` | десять видов `instructions.*`, order **220–229** | T-10113 |
| `audit_labels` | `instructions.created`, `.changed`, `.report_submitted`, `.report_accepted`, `.report_returned`, `.part_added`, `.transfer_requested`, `.transfer_decided`, `.closed`, `.reassigned`, `.retention_changed`, `.retention_purged` | T-10117 |
| `file_purposes` | назначение `instruction` — ожидание/чистый/карантин | T-10116 |
| `stand_reset` | `apps.instructions.stand.stand_reset` — **последняя** запись, вызывается первой; стирает свои таблицы до задач | T-10124 |

`role_sources` не регистрируется: права выданы ролям данными.

### Права среза

`instructions.use` — открыть раздел, видеть доступные поручения, писать отчёт; `instructions.assign` — ставить
поручения подчинённым. Правило структуры — `managed_units`. Видимость по структуре **дополнительна** к праву:
руководитель цепочки видит карточку, если у него есть `instructions.use` (встроенная роль «Сотрудник ИТ»).
Дисциплина — без отдельного права: маршрут требует `instructions.use` и проверяет структуру; администратор
портала отчёт не получает, даже если он чей-то руководитель (явная проверка `not is_admin_role`).

### Запуск

Новых служб нет: web — страницы, `maintenance` — задания. Миграции: `core 0014` от `0013`, `core 0015` от
`0014`, `instructions 0001` от `core 0015` и `tasks 0001`, `instructions 0002` (данные) от `0001`.

## Модель данных

### Приложение `instructions` (миграция 0001)

| Модель | Поля | Индексы и ограничения |
|---|---|---|
| `Instruction` | `title` 300, `text` 10 000, `basis_kind` FK PROTECT, `basis_number` 100, `basis_date` дата, `author` FK PROTECT, `controller` FK PROTECT, `assignee` FK PROTECT, `deadline` дата, `original_deadline` дата (при создании = `deadline`), `ladder` JSON пусто, `created_at`, `updated_at`, `closed_at` пусто, `deleted_at` пусто (только хранение) | индексы `(assignee, deadline)`, `(controller)`, `(author)`, `(deadline)`, `(closed_at)`, `(basis_kind)` |
| `InstructionBasisKind` | `title` 100 уникальное, `position`, `active` (по умолчанию `True`) | индекс `(position)`; удаление — только неиспользованного, иначе `active=False` |
| `InstructionMember` | `instruction` CASCADE, `user` PROTECT, `role`=`coexecutor` | уникальность `(instruction, user)`; индекс `(user)` |
| `InstructionReportDate` | `instruction` CASCADE, `due_date`, `position`, `state`=`waiting` (`waiting`/`review`/`returned`/`accepted`), `closed_at` пусто | уникальность `(instruction, due_date)`; индекс `(instruction, position)` |
| `InstructionReport` | `instruction` CASCADE, `date` FK `InstructionReportDate` **CASCADE**, пусто = «к сроку», `author` PROTECT, `text` 10 000, `submitted_at`, `decision`=`pending` (`pending`/`accepted`/`returned`), `decided_by` SET_NULL, `decided_at`, `comment` 2 000 | **уникальность `(instruction, author)` при `date IS NULL`** (итоговый отчёт один); индекс `(instruction, submitted_at)` |
| `InstructionReportPart` | **`date` FK `InstructionReportDate` CASCADE** (обязателен), `author` PROTECT, `text` 10 000, `created_at` | уникальность `(date, author)`; индекс `(date)` |
| `InstructionFile` | `instruction` CASCADE, `kind` (`basis`/`report`/`part`), `report` SET_NULL пусто, `part` SET_NULL пусто, `file` OneToOne PROTECT, `name` 255, `uploaded_by` PROTECT, `created_at` | индексы `(instruction)`, `(report)`, `(part)`; файлов на отчёт/часть — до 10 |
| `InstructionTransfer` | `instruction` CASCADE, `old_deadline`, `new_deadline`, `reason` 1 000, `requested_by` PROTECT, `state`=`pending`, `decided_by` SET_NULL, `decided_at`, `comment` 1 000, `created_at` | частичный уникальный `(instruction)` при `state='pending'`; индекс `(instruction, state)` |
| `InstructionReminder` | `instruction` CASCADE, `date` FK `InstructionReportDate` **CASCADE** пусто, `user` CASCADE, `kind` (`deadline`/`report`), `stage` (`d30`/`d14`/`d7`/`d3`/`d1`/`due`/`overdue`/`r3`/`r1`), `moment`, `state`=`pending`, `created_at` | уникальность `(instruction, date, user, kind, stage)` при `state='pending'` с `nulls_distinct=False`; индекс `(state, moment)` |
| `InstructionSettings` | `retention_years` 1–10 = 3, `default_ladder` JSON, `updated_at`, `updated_by` SET_NULL | `pk=1`; `CheckConstraint` 1–10 |
| `InstructionTask` | `instruction` CASCADE, `task` FK `tasks.Task` CASCADE, `created_by` PROTECT, `created_at` | уникальность `(instruction, task)`; индекс `(task)` |

Номер — `pk`. Статус в реестре не хранится: вычисляется `Case/When` из `closed_at`, ближайшей незакрытой даты
(`min` отчётных дат, а если их нет — срок) и решений отчётов; «Просрочено» проверяется первым после «Исполнено».

`ladder` JSON: `{"offsets": [30, 14, 7, 3, 1], "due": true, "overdue": true}` — рабочие дни до срока; допустимы
1–60, по возрастанию, без повторов; пустой объект — умолчание `InstructionSettings.default_ladder`; проверка в
форме.

### Ядро

`core 0014`: `Purpose.INSTRUCTION = "instruction"`; `core 0015`: права `instructions.use`/`instructions.assign`,
идемпотентны.

### Данные установки `instructions 0002`

`InstructionSettings(pk=1, retention_years=3, default_ladder={"offsets":[30,14,7,3,1],"due":true,"overdue":true})`;
виды основания «Приказ», «Протокол совещания», «Письмо», «Устное указание» (`get_or_create` по `title`, порядок
0–3). Повторный запуск не дублирует и не перезаписывает.

## Ключевые механизмы

### Создание и права (FR-700–704, 721–722)
`services.instructions.create/update`: текст, основание (вид/номер/дата обязательны), срок не раньше сегодняшнего,
исполнитель один, соисполнители без повторов, контролёр действующий (по умолчанию автор), смена контролёра
автором. Создавать — руководитель/заместитель узла исполнителя. `apps.py` подписывает `core.user_dismissed` →
`services.instructions.reassign`: контролёр уволен → `controller = author`; исполнитель уволен → автор назначает
нового до действий; блокированный (`state='blocked'`) видит, но не действует; всё в журнале.

### Отчётные даты (FR-705)
`services.dates.build`: еженедельно — тот же день недели, начиная со **следующего** дня после постановки;
ежемесячно/ежеквартально — то же число, начиная со следующего месяца/квартала (31 → последний день месяца);
ряд обрезается **строго до** срока; дата, равная сроку, не создаётся — итоговый отчёт «к сроку» один; прошедшие
даты отклоняются. Смена срока/периодичности пересобирает только будущие даты без отчётов; даты с отправленным
или принятым отчётом сохраняются, при попытке изменить периодичность с такими датами — отказ.

### Отчёты и части (FR-706, 723)
Часть принадлежит отчётной дате (`InstructionReportPart.date`), а не сводному отчёту: соисполнитель добавляет
часть до отправки сводного отчёта; `InstructionReport` — сводная часть ответственного к дате (уникальна
`(date, author)`) или к сроку (`date=NULL`, один итоговый). Отправка отчёта: текст обязателен, файлы до 10;
отменяет `pending`-напоминания этой даты; дата → `review`. Контролёр видит части с авторами; решение одно на
сводный отчёт/дату: `accepted` закрывает дату, `returned` требует комментарий → `waiting`; части остаются.
Итоговый отчёт «к сроку» — `date=NULL`; принятие открывает снятие с контроля.

### Снятие с контроля (FR-707)
Только контролёр, только при принятом итоговом отчёте; `closed_at`, отмена всех `pending`-напоминаний и
`pending`-переноса, журнал. После закрытия отчёты не принимаются.

### Перенос срока (FR-708)
Запрос исполнителя (новая дата позже текущей, причина 1–1000), один `pending`; решает автор/контролёр;
согласование меняет `deadline`, `original_deadline` не меняется, будущие даты/напоминания пересчитываются;
отказ с причиной; уведомление исполнителю о решении; после `closed_at` запросы не принимаются. История — все
строки `InstructionTransfer` на карточке (`[data-transfer]`, `[data-history]`).

### Лестница напоминаний (FR-709–710)
Длина = `deadline − created_at.date()`, при переносе пересчитывается. Пороги ≤1 мес — 3/1; >1 и ≤6 — +14/7;
>6 — +30; `due` — начало рабочего дня срока; `overdue` — следующий рабочий день. Отчётные — r3/r1. Прошлые
пороги при создании не создаются. Момент сдвигается `quiet.next_start` при планировании **и проверяется перед
отправкой**; `None` — `pending` до следующего цикла, повторный `None` — отмена с записью `instructions.reminder_failed`.
Правка лестницы — `POST /instructions/<id>/ladder/` (автор/контролёр), только будущие `pending`; `sent` не
трогаются.

### Уведомления и сводка (FR-711–712)
Десять видов: `assigned`, `deadline`, `report_due`, `report_overdue`, `overdue`, `report_submitted`,
`report_accepted`, `report_returned`, `transfer`, `digest` (order 220–229; `available` — `instructions.use`).
Получатели: исполнитель/соисполнители — лестница, отчёты, решения; контролёр/автор — просрочки, пришедший отчёт,
перенос. При совмещении ролей — одно сообщение с приоритетом: срок просрочен → отчёт просрочен → отчёт пришёл →
принят → возвращён → запрос переноса → сводка. `still_relevant` — поручение не закрыто и не удалено, для отчёта —
дата ещё открыта. Сводка — первый рабочий день недели в начале рабочего дня получателя,
`cache.add("instructions:digest:<ISO-неделя>:<user>")`, содержание: сроки и отчёты на 30 дней и просроченные;
пустая не отправляется; отключённые каналы не ошибка. Письмо — `email_delay_minutes` (15 по умолчанию), не
константа. Внешние каналы — только событие и ссылка.

### Реестр и дисциплина (FR-713–715)
`registry.rows`: видимость `author/controller/assignee/соисполнитель` или `manages(viewer, assignee)` или
`manages(viewer, author)`; пресеты `mine`, `control`, `subordinate` (ответственный в управляемых узлах, кроме
собственных), `overdue`; фильтры `basis`, `assignee`, `deadline`, `state`, `q`; порядок по сроку, затем
изменению; страницы 20/50. `discipline`: параметры `from`, `to`, `unit`; население — закрытые в периоде
поручения; по исходному сроку — «в срок», «с переносом», «просрочено»; по сроку с переносами — «в срок»,
«просрочено»; срока с переносами — последний согласованный перенос с `decided_at <= closed_at` (иначе
`deadline`); открытые просроченные — отдельной строкой; «основной узел» — первый не-корневой узел сотрудника по
`path`, иначе корень; администратор исключён. Excel — те же числа.

### Связь с задачами (FR-716)
`services.instructions.link_task`: исполнитель создаёт задачу через `tasks.services.tasks.create` (нужно
`tasks.use`; если его нет — отказ у поля) и связывает `InstructionTask`; связать можно только видимую задачу.
В карточке задачи показываются только тем, кому видна сама задача; завершение задач не закрывает поручение.

### Хранение (NFR-729)
`instructions_retention`: только `closed_at` старше `retention_years` (календарно, 29.02 → 28.02); удаляет
`Instruction` (каскадом участники, связи с задачами), отчёты, части, файлы, переносы, напоминания; строки
`StoredFile` назначения `instruction` — вместе, диск после фиксации; журнал `instructions.retention_purged` без
текста; неснятые не удаляются; смена срока — `instructions.retention_changed`; повторный запуск без ошибок.

### Файлы (NFR-722)
`services.files` + `views.files`: `uploads.store(data, name, "instruction")`, 20 МБ, не больше 10 на отчёт/часть,
исполняемые и архивы с паролем отклоняются, до проверки файл недоступен, скачивание через X-Accel с проверкой
видимости поручения.

### 360 px (NFR-725)
`instructions.css`: до 900 px одна колонка, карточка с «Назад»; таблица дисциплины прокручивается внутри;
реестр без прокрутки страницы.

## Контракты

| Метод | Адрес | Что делает |
|---|---|---|
| GET | `/instructions/` | реестр (`preset`, `basis`, `assignee`, `deadline`, `state`, `q`, `sort`, `page`, `per_page`) |
| GET | `/instructions/list/` | фрагмент реестра |
| GET | `/instructions/new/` | форма создания |
| POST | `/instructions/new/` | создание |
| GET | `/instructions/<id>/` | карточка, история, части, отчёты |
| POST | `/instructions/<id>/` | правка полей |
| POST | `/instructions/<id>/ladder/` | правка лестницы |
| POST | `/instructions/<id>/close/` | снятие с контроля |
| POST | `/instructions/<id>/reports/` | сводный отчёт к дате/сроку |
| POST | `/instructions/<id>/parts/` | часть отчёта к дате |
| POST | `/instructions/reports/<id>/accept/`, `/return/` | решение контролёра |
| POST | `/instructions/<id>/transfers/` | запрос переноса |
| POST | `/instructions/transfers/<id>/approve/`, `/reject/` | решение |
| POST | `/instructions/files/` | загрузка файла (`kind`, `instruction`, `report`, `part`) |
| GET | `/instructions/files/<uuid>/` | файл (X-Accel) |
| GET | `/instructions/discipline/` | отчёт (`from`, `to`, `unit`) |
| GET | `/instructions/discipline.xlsx` | Excel |
| GET/POST | `/settings/instructions/` | умолчания лестницы и срок хранения |
| GET/POST | `/settings/instructions/basis/`, `/basis/<id>/`, `/basis/<id>/delete/` | справочник |

Зацепки: `[data-instructions-page="registry|card|discipline|settings"]`, `[data-instruction-id]`,
`[data-instruction-state]`, `[data-instructions-preset]`, `[data-report-date]`, `[data-report-state]`,
`[data-report-part]`, `[data-transfer]`, `[data-history]`, `[data-instruction-file]`, `[data-error][data-code]`.

## Интеграции

- **org** — `managed_units`, `units_of`, `managers_of`, календарь (`day_kind`, `next_working_start`).
- **notify** — виды, `quiet.next_start`, `dispatch.create`, `still_relevant`, письмо по настройке.
- **core** — пользователи, `uploads.store`, `audit.record`, права, событие `core.user_dismissed`.
- **tasks** — `tasks.services.tasks.create`, `tasks.services.access.visible`; приложение зависит от `tasks`.

## Проверка

### Серверные тесты (22 файла)
`test_instructions_models`, `test_instructions_access`, `test_instructions_create`, `test_instructions_dates`,
`test_instructions_reports`, `test_instructions_close`, `test_instructions_transfers`, `test_instructions_reminders`,
`test_instructions_notify`, `test_instructions_digest`, `test_instructions_registry`,
`test_instructions_discipline`, `test_instructions_tasks`, `test_instructions_files`, `test_instructions_audit`,
`test_instructions_retention`, `test_instructions_settings`, `test_instructions_basis`,
`test_instructions_deploy`, `test_instructions_seed`, `test_instructions_stand`,
`test_instructions_core_changes`, `test_instructions_boundaries` (23 при отдельном basis; границы обязательны).

### Проход в браузере (10 сценариев, четыре круга)
`t10_01` реестр, `t10_02` создание, `t10_03` отчёт и принятие, `t10_04` возврат, `t10_05` перенос,
`t10_06` напоминания, `t10_07` дисциплина и Excel, `t10_08` задачи из поручения, `t10_09` права (руководитель
только чтение, чужое 404), `t10_10` 360 px. Круги — Chromium, Firefox, Edge, Яндекс Браузер.

### Нагрузка (NFR-720)
`fill_instructions.py`: 1 000 поручений на 100 сотрудников; `InstructionUser` — реестр, карточка, отчёт,
решение, дисциплина. Замер p95 500 мс после решения владельца (T-10304), с ограничением стенда.

### Требование → механизм → тест

| Требование | Механизм | Тест |
|---|---|---|
| FR-700 поля и основание | `Instruction`, `services.instructions` | `models`, `create` |
| FR-701 справочник | `InstructionBasisKind`, `services.basis` | `basis` |
| FR-702 кто ставит | `access.can_assign` | `access` |
| FR-703 контролёр | `Instruction.controller`, смена | `access` |
| FR-704 исполнитель/соисполнители | `InstructionMember` | `create` |
| FR-705 даты | `services.dates` | `dates` |
| FR-706 отчёт к дате/сроку | `InstructionReport`, `services.reports` | `reports` |
| FR-707 снятие | `services.instructions.close` | `close` |
| FR-708 перенос | `InstructionTransfer` | `transfers` |
| FR-709 лестница | `services.reminders` | `reminders` |
| FR-710 тихие часы | `quiet.next_start` | `reminders` |
| FR-711 уведомления | `notify_rules` | `notify`, `digest` |
| FR-712 сводка | `services.digest` | `digest` |
| FR-713 реестр | `services.registry` | `registry` |
| FR-714 дисциплина | `services.discipline` | `discipline` |
| FR-715 Excel | `services.excel` | `discipline` |
| FR-716 задачи | `InstructionTask`, `link_task` | `tasks` |
| FR-717 статусы | `Case/When`, `ReportDate.state` | `registry`, `reports` |
| FR-718 журнал/история | `audit.record`, карточка | `audit` |
| FR-719 404 | `access.visible` | `access` |
| FR-720 360 px | `instructions.css` | e2e `t10_10` |
| FR-721 видимость | `access.visible` | `access` |
| FR-722 увольнение/смена | `reassign`, `core.user_dismissed` | `access` |
| FR-723 части | `InstructionReportPart.date` | `reports` |
| NFR-720 p95 | `InstructionUser` | нагрузка |
| NFR-721 SQL | `registry`, `discipline` | `registry`, `discipline` |
| NFR-722 файлы | `services.files` | `files` |
| NFR-723 внешний текст | `notify_kinds` | `notify` |
| NFR-724 идемпотентность | задания | `reminders`, `digest`, `retention` |
| NFR-725 360/браузеры | `instructions.css` | e2e 4 круга |
| NFR-726 русский/Москва | тексты, `TIME_ZONE` | `deploy` |
| NFR-727 журнал | права `crm_app` | `audit` |
| NFR-728 профиль | `locustfile.py` | `deploy` |
| NFR-729 хранение | `services.retention` | `retention` |

### Прежние тесты, которые придётся поправить

Только с разрешения владельца, по одному тесту, диффом «было / стало» (как T-9011 среза 009):

| № | Файл::тест | Было | Стало | Почему |
|---|---|---|---|---|
| 1 | `test_feed_deploy.py::test_cron_module_has_twenty_four_register_calls` и аналоги в `test_kb_deploy`, `test_lists_deploy`, `test_messenger_deploy`, `test_notify_deploy`, `test_sd_deploy`, `test_tasks_deploy` | 24 | 27, три задания `instructions_*` | cron |
| 2 | `support_feed.APPS_TAIL` и тесты `INSTALLED_APPS` (feed/kb/lists/messenger/notify/tasks) | 8 элементов | 9, `apps.instructions` последний | хвост приложений |
| 3 | `test_org_permissions.py::test_menu_...` | 18 пунктов | 20, «Поручения» order 3, «Настройки поручений» 66 | меню |
| 4 | `test_tasks_deploy.py::test_menu_items...`, `test_messenger_deploy.py::test_admin_menu...` | 18 | 20 | меню |
| 5 | `test_permissions.py`, `test_org_permissions.py`, `test_sd_access.py` | 20 прав | 22, `PERMISSIONS_010` | права |
| 6 | `test_feed_core_changes.py`, `test_messenger_core_changes.py`, `test_messenger_boundaries.py`, `test_messenger_deploy.py`, `test_tasks_core_changes.py`, `test_tasks_models.py` | 7 назначений, последнее `task` | 8, последнее `instruction` | Purpose |
| 7 | `test_notify_catalog.py` (TABLE/счётчики), `test_notify_catalog_2.py`, `test_notify_prefs.py`, `test_messenger_notify_2.py` | 30 видов | 40, десять `instructions.*` | каталог |
| 8 | `test_tasks_core_changes.py`, `test_feed_boundaries.py`, `test_messenger_boundaries.py` | `stand_reset` последний — tasks | последний — instructions | сброс |
| 9 | `test_tasks_deploy.py` (nginx), `test_deploy_files.py` | три 25m | четыре | nginx |
| 10 | `test_tasks_core_changes.py` («без задач») | 16 пунктов/без Purpose | «без задач и поручений»: оба приложения сняты | зависимость |
| 11 | e2e `test_e04_my_settings.py`, `test_e12_criteria.py`, `test_d08_heads.py`, `test_o04_find_colleague.py` | без видов/пунктов поручений | +10 видов, +2 пункта | приёмка |

TASKS-010 включает эти правки одной задачей T-10111 (по одной строке с разрешения владельца).

## Риски

| Риск | Оценка | Что делаем |
|---|---|---|
| Части отчёта и потеря при возврате | высокая | `Part.date`, части не зависят от сводного отчёта, тест возврата |
| Уникальность напоминаний лестницы | высокая | `stage`, `nulls_distinct=False`, условие `pending`, тест 7 порогов |
| Уведомление о решении отчёта | средняя | два вида, приоритет, тест |
| Триггер увольнения | средняя | подписка `core.user_dismissed`, тест |
| Приоритет сообщений | высокая | группировка на запуск, тест совмещения ролей |
| Дисциплина: две шкалы и «основной узел» | высокая | правило последнего переноса, пример с числами |
| Пересборка дат с ранним отчётом | средняя | сохранять даты с отчётами, тест |
| Напоминания в прошлом/`None` | средняя | пропуск прошлых, повторный `None` |
| Зависимость от `tasks` | средняя | явная зависимость приложения и правка «без задач» |
| Excel и openpyxl | низкая | только значения, чтение файла в тесте |
| Файлы и ClamAV | средняя | 20 МБ, 120 с, карантин, X-Accel |
| Хранение и каскады | средняя | порядок удаления, журнал, идемпотентность |
| Правки прежних тестов | высокая | таблица T-10111, разрешение владельца |

## Решения уровня плана

1. Часть отчёта принадлежит отчётной дате, сводный отчёт — ответственный; части переживают возврат.
2. Напоминание имеет `stage`; уникальность только для `pending`, `sent` не мешает пересчёту.
3. Виды `report_accepted`/`report_returned` добавлены; приоритет сообщений — на запуске задания.
4. `instructions` зависит от `tasks`; в тестах «без задач» снимаются оба приложения.
5. «Основной узел» — первый не-корневой узел по `path`, иначе корень.
6. Периодический ряд начинается со следующего дня/месяца/квартала и обрезается строго до срока; дата, равная
   сроку, не создаётся — итоговый отчёт один.
7. `ladder` JSON — `offsets` 1–60, `due`, `overdue`; пустой — умолчание.
8. Файлы основания/отчётов/частей — один `InstructionFile`, без отдельного `basis_file`.
9. История карточки — события `AuditEvent` по объекту и строки переносов; `[data-history]`.
10. ClamAV: таймаут 120 с, «минута» — требование к типичному сканированию; в тестах подмена.

## Открытые вопросы

Нет вопросов, требующих решения владельца: спорные правила закрыты SPEC-010 и решениями уровня этого плана.