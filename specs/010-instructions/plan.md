---
id: PLAN-010
вид: план
статус: черновик
версия: 1
зависит_от: SPEC-010, CONST, ADR-0002, ADR-0004, ADR-0009, ADR-0010, ADR-0013, ADR-0017, ADR-0018, REF-MOD-INST, REF-SRC, REF-UX, TGT-ARCH, TGT-NFR, SPEC-002, SPEC-004, SPEC-007, SPEC-009
основан_на: SPEC-010 sha256:c86c5fabb7ea017d6043b5590c961d7332c16f275c6420ccee264d8b7da8d42e
---

# План среза 010: Поручения и контроль исполнения

## Сверка с конституцией

- **модуль-приложение** — новое приложение `apps.instructions`; связи с ядром через точки расширения
  (`menu_items`, `notification_kinds`, `audit_labels`, `file_purposes`, `stand_reset`), с `org` — публичные
  службы структуры и календаря, с `notify` — `dispatch`/`quiet`, с `tasks` — публичная служба создания задач и
  связь через собственную таблицу `InstructionTask`.
- **настройка-без-кода** — виды основания, лестница напоминаний, срок хранения и права постановки — данные
  (`core.Permission`, `InstructionBasisKind`, `InstructionSettings`, `Instruction.ladder`).
- **пдн-152фз** — администратор не читает чужие поручения; внешние каналы получают только событие и ссылку;
  срок хранения после снятия с контроля — 3 года.
- **sql-только-параметры** — реестр, дисциплина и поиск — параметрами, ключи из белого списка.
- **аудит-изменений** — журнал только дополняется; все поля, отчёты и переносы пишутся «было/стало».
- **стек-интерфейс** — страницы на HTMX, без отдельного состояния на клиенте; Excel — серверная выгрузка.
- **эталон-не-копия** — берём контроль после завершения и выгрузку, но не вёрстку и тексты эталона.

## Технический контекст

### Новые компоненты и лицензии

Новых пакетов нет: Excel — `openpyxl==3.1.5` (уже в `requirements.txt`), файлы — `core.services.uploads`,
ClamAV — существующий. Новых сторонних JS нет: перетаскивания в срезе нет, страницы на HTMX и Bootstrap.

### Где живёт код

```
backend/apps/instructions/
  apps.py, models.py, extensions.py, urls.py, notify_kinds.py, audit_labels.py, texts.py, stand.py, tasks.py
  migrations/0001_initial.py, 0002_initial_data.py
  services/   access, basis, instructions, dates, reports, transfers, reminders, notify_rules, digest,
              registry, discipline, excel, retention, settings
  views/      pages (реестр, карточка, дисциплина), actions (создание/правка/снятие), reports, transfers,
              settings
  templates/instructions/…   static/instructions/{instructions.js,instructions.css}
backend/tests/test_instructions_*.py, tests/e2e/test_t10_*.py, tests/CONTRACT-010.md
backend/tests/load/fill_instructions.py, класс InstructionUser в locustfile.py
```

### Изменения ядра и прежних модулей

| Файл | Изменение | Зачем |
|---|---|---|
| `core/models/files.py` + миграция `core 0014` | `Purpose.INSTRUCTION = "instruction"` в конце перечня | файлы основания и отчётов (NFR-722) |
| данные установки `core 0015` | права `instructions.use`, `instructions.assign` — строки `core.Permission`, выданы «Администратору портала» и «Сотруднику ИТ» | права-данные (FR-702, FR-703) |
| `config/settings.py` | `"apps.instructions"` последним в `INSTALLED_APPS` | приложение среза |
| `config/urls.py` | `include("apps.instructions.urls")` под `apps.is_installed` | адреса `/instructions/…`, `/settings/instructions/…` |
| `config/cron.py` | `instructions_reminders` (`*/5`, 300 с), `instructions_digest` (`*/15`, 300 с), `instructions_retention` (`43 23 * * *`, 600 с) под `is_installed` | напоминания, сводка, хранение |
| `deploy/nginx.conf`, `deploy/nginx.prod.conf` | `location ~ ^/instructions/files/$` с `client_max_body_size 25m` | файлы 20 МБ |
| `templates/_assets.html` | `instructions.css`, `instructions.js` для `/instructions/` и `/settings/instructions/` | страницы среза |

### Права среза

`instructions.use` (открыть раздел, видеть свои поручения, писать отчёт) и `instructions.assign` (ставить
поручения подчинённым) — строки `core.Permission`, выданы «Администратору портала» и «Сотруднику ИТ» при
установке. Правило структуры — `org.services.structure.managed_units`, как у задач. Право на дисциплину —
не отдельное право, а роль руководителя/заместителя по структуре (FR-714).

### Запуск

Новых служб нет: web — страницы и действия, `maintenance` — задания cron. Миграции — `core 0014`, `core 0015`,
`instructions 0001/0002`; стенд обновляется по действующей процедуре после разрешения владельца.

## Модель данных

### Приложение `instructions` (миграция 0001)

| Модель | Поля | Индексы и ограничения |
|---|---|---|
| `Instruction` | `title` (300), `text` (10 000), `basis_kind` (FK, PROTECT), `basis_number` (100), `basis_date` (дата), `basis_file` (FK `core.StoredFile`, SET_NULL, пусто), `author` (FK User, PROTECT), `controller` (FK User, PROTECT), `assignee` (FK User, PROTECT), `deadline` (дата), `original_deadline` (дата), `ladder` (JSON, пусто — умолчание), `created_at`, `updated_at`, `closed_at` (пусто), `deleted_at` (пусто) | индексы `(assignee, deadline)`, `(controller)`, `(author)`, `(deadline)`, `(closed_at)`, `(basis_kind)` |
| `InstructionBasisKind` | `title` (100), `position` | уникальность `title`; индекс `position` |
| `InstructionMember` | `instruction` (FK, CASCADE), `user` (FK User, PROTECT), `role` (`coexecutor`) | уникальность `(instruction, user)`; индекс `(user)` |
| `InstructionReportDate` | `instruction` (FK, CASCADE), `due_date` (дата), `position`, `state` (`waiting`/`review`/`returned`/`accepted`), `closed_at` | уникальность `(instruction, due_date)`; индекс `(instruction, position)` |
| `InstructionReport` | `date` (FK `InstructionReportDate`, CASCADE, пусто — отчёт к сроку), `instruction` (FK, CASCADE), `author` (FK User, PROTECT), `text` (10 000), `submitted_at`, `decision` (`pending`/`accepted`/`returned`), `decided_by` (FK User, SET_NULL), `decided_at`, `comment` (2 000) | уникальность `(date, author)` при `date` не пусто; индекс `(instruction, submitted_at)` |
| `InstructionReportPart` | `report` (FK, CASCADE), `author` (FK User, PROTECT), `text` (10 000), `created_at` | уникальность `(report, author)`; индекс `(report)` |
| `InstructionFile` | `instruction` (FK, CASCADE), `report` (FK, SET_NULL, пусто), `part` (FK `InstructionReportPart`, SET_NULL, пусто), `file` (OneToOne StoredFile, PROTECT), `name` (255), `uploaded_by` (FK User, PROTECT), `created_at` | индексы `(instruction)`, `(report)`, `(part)` |
| `InstructionTransfer` | `instruction` (FK, CASCADE), `old_deadline`, `new_deadline`, `reason` (1 000), `requested_by` (FK User, PROTECT), `state` (`pending`/`approved`/`rejected`), `decided_by` (FK User, SET_NULL), `decided_at`, `comment` (1 000), `created_at` | индекс `(instruction, state)`; частичный уникальный `(instruction)` при `state='pending'` |
| `InstructionReminder` | `instruction` (FK, CASCADE), `date` (FK `InstructionReportDate`, SET_NULL, пусто), `user` (FK User, CASCADE), `kind` (`deadline`/`report`), `moment`, `state` (`pending`/`sent`/`cancelled`), `created_at` | частичный уникальный `(instruction, date, user, kind)` при `state != 'cancelled'`; индекс `(state, moment)` |
| `InstructionSettings` | `retention_years` (1–10, 3), `default_ladder` (JSON), `updated_at`, `updated_by` | `pk=1` |
| `InstructionTask` | `instruction` (FK, CASCADE), `task` (FK `tasks.Task`, CASCADE), `created_by` (FK User, PROTECT), `created_at` | уникальность `(instruction, task)`; индекс `(task)` |

Номер поручения — `pk`. Статус в реестре не хранится отдельным полем: вычисляется из `closed_at`, ближайшей
незакрытой `InstructionReportDate` и решений отчётов; в запросах — `Case/When` по этим данным (FR-717).

### Ядро

`core 0014`: `Purpose.INSTRUCTION = "instruction"` в конце перечня. `core 0015`: права `instructions.use` и
`instructions.assign` (данные установки, идемпотентны).

## Ключевые механизмы

### Создание, поля и права (FR-700–704, 721–722)
`services.instructions.create/update`: название 1–300 после обрезки, текст до 10 000, основание обязательно
(вид, номер, дата; файл необязателен), срок — дата не раньше сегодняшней, исполнитель — один действующий,
соисполнители — любые действующие без повторов, контролёр — действующий (по умолчанию автор). Создавать может
руководитель/заместитель узла исполнителя (по `managed_units`); сменить контролёра может автор; при увольнении
контролёра контроль возвращается автору, при увольнении исполнителя автор назначает нового (FR-722). Смена
полей пишется в журнал и историю.

### Отчётные даты (FR-705)
`services.dates.build(instruction, kind, start=None, dates=None)`: еженедельно — тот же день недели от даты
постановки, ежемесячно — то же число (31 → последний день месяца), ежеквартально — каждые 3 месяца; ряд
обрезается сроком, дубликаты схлопываются, прошедшие даты отклоняются; дата, равная сроку, — одна. Список дат
проверяется так же. Смена срока/периодичности пересобирает только будущие незакрытые даты, закрытые не трогает.

### Отчёты и части (FR-706, 723)
`services.reports`: соисполнитель добавляет часть (`text`, файлы) к отчётной дате; ответственный отправляет
сводный отчёт к дате или к сроку (текст обязателен, файлы — нет); отчёт заранее разрешён. Контролёр видит части
с авторами, сводный текст и файлы. Решение — одно на отчёт: `accepted` закрывает дату и снимает её напоминания,
`returned` требует комментарий и возвращает дату в `waiting`. Отчёт «к сроку» — итоговый.

### Снятие с контроля (FR-707)
Только контролёр; требуется принятый итоговый отчёт «к сроку»; `closed_at`, снятие всех напоминаний, журнал
`instructions.closed`. После снятия отчёты не принимаются, карточка остаётся для чтения.

### Перенос срока (FR-708)
`services.transfers.request`: исполнитель указывает новую дату и причину; один `pending` на поручение. Решает
автор или контролёр; при согласовании `deadline` меняется, `original_deadline` не меняется, будущие отчётные
даты и напоминания пересчитываются; при отказе причина обязательна. Все решения — в истории и журнале.

### Лестница напоминаний (FR-709–710)
Длина срока — `deadline − created_at.date()` (дата постановки), фиксируется и пересчитывается при переносе.
Пороги: ≤ 1 месяца — 3 и 1 рабочий день; > 1 и ≤ 6 месяцев — плюс 14 и 7; > 6 месяцев — плюс 30; момент срока —
начало рабочего дня даты срока; просрочка — с начала следующего рабочего дня. Отчётные даты — 3 и 1 рабочий день.
Каждый момент сдвигается `notify.services.quiet.next_start` по настройкам получателя. Лестница поручения
(`ladder` JSON) заменяет умолчание `InstructionSettings.default_ladder`; правка и перенос пересчитывают только
будущие напоминания. `instructions_reminders` каждые 5 минут выбирает `pending` с `moment <= now`, создаёт
уведомление `dispatch.create`, помечает `sent`; повторный запуск не дублирует.

### Уведомления и сводка (FR-711–712)
Восемь видов `instructions.*`: назначено, срок (лестница), отчёт скоро, отчёт просрочен, срок просрочен, отчёт
пришёл, запрос переноса, недельная сводка. Получатели: исполнитель и соисполнители — лестница и отчёты;
контролёр и автор — просрочка срока/отчёта, пришедший отчёт, запрос переноса; при совмещении ролей — одно
сообщение с приоритетом: срок просрочен → отчёт просрочен → отчёт пришёл → запрос переноса → сводка. Сводка —
первый рабочий день недели в начале рабочего дня, атомарный `cache.add("instructions:digest:<неделя>:<user>")`,
пустая не отправляется. Внешние каналы (Telegram, MAX, Web Push) — только событие и ссылка; портал и почта —
полный текст (NFR-723).

### Реестр и дисциплина (FR-713–715)
`services.registry.rows` — один SQL с видимостью (участники + цепочка руководителей, FR-721), пресетами `mine`,
`control`, `subordinate`, `overdue` и фильтрами `basis`, `assignee`, `deadline`, `state`, `q`; сортировки
`deadline`/`updated`; страницы 20/50. `services.discipline` считает по снятым с контроля в периоде два разреза:
по исходному сроку — «в срок», «с переносом», «просрочено»; по сроку с переносами — «в срок», «просрочено»;
открытые просроченные — отдельной строкой; ответственный и его основной узел. Excel — `openpyxl`, те же числа и
русские подписи.

### Связь с задачами (FR-716)
`services.instructions.link_task`: исполнитель создаёт задачу через `tasks.services.tasks.create` (правила среза
009) и связывает `InstructionTask`; связать можно только задачу, которую смотрящий видит. В карточке поручения
задачи показываются только тем, кому видна сама задача; завершение задач не закрывает поручение.

### Хранение (NFR-729)
`instructions_retention` раз в сутки: только поручения с `closed_at` старше `retention_years`
(календарное вычитание, 29.02 → 28.02), удаляет отчёты, части, файлы, переносы и напоминания; строки
`core.StoredFile` назначения `instruction` — вместе с файлами, диск — после фиксации. В журнале остаётся запись
`instructions.retention_purged` без текста. Неснятые с контроля поручения не удаляются.

### 360 px и телефон (NFR-725)
`instructions.css`: до 900 px — одна колонка, карточка открывается с «Назад»; таблица дисциплины прокручивается
внутри себя; реестр без горизонтальной прокрутки страницы.

## Контракты

| Метод | Адрес | Что делает |
|---|---|---|
| GET | `/instructions/` | реестр с пресетами и фильтрами |
| GET | `/instructions/list/` | фрагмент реестра (HTMX) |
| GET | `/instructions/new/` | форма создания |
| POST | `/instructions/new/` | создание |
| GET | `/instructions/<id>/` | карточка |
| POST | `/instructions/<id>/` | правка полей |
| POST | `/instructions/<id>/close/` | снятие с контроля (контролёр) |
| POST | `/instructions/<id>/reports/` | отчёт к дате/сроку |
| POST | `/instructions/<id>/parts/` | часть отчёта соисполнителя |
| POST | `/instructions/reports/<id>/accept/`, `/return/` | решение контролёра |
| POST | `/instructions/<id>/transfers/` | запрос переноса |
| POST | `/instructions/transfers/<id>/approve/`, `/reject/` | решение по переносу |
| POST | `/instructions/files/` | загрузка файла (основание/отчёт/часть) |
| GET | `/instructions/files/<uuid>/` | файл (X-Accel-Redirect) |
| GET | `/instructions/discipline/` | отчёт по дисциплине |
| GET | `/instructions/discipline.xlsx` | выгрузка Excel |
| GET/POST | `/settings/instructions/` | умолчания лестницы и срок хранения |
| GET/POST | `/settings/instructions/basis/…` | справочник видов основания |

Зацепки: `[data-instructions-page="registry|card|discipline|settings"]`, `[data-instruction-id]`,
`[data-instruction-state]`, `[data-instructions-preset]`, `[data-report-date]`, `[data-report-state]`,
`[data-error][data-code]`, `[data-transfer]`, `[data-discipline-row]`, `[data-instruction-file]`.

## Интеграции

- **org** — `managed_units`, `units_of`, `unit_chains`, `subtree_member_ids`, календарь (`day_kind`,
  `next_working_start`).
- **notify** — виды, каналы, `quiet.next_start`, `dispatch.create`, письмо через 15 минут.
- **core** — пользователи, файлы/ClamAV (`uploads.store`), журнал (`AuditEvent`), права и роли.
- **tasks** — `services.tasks.create`, `access.visible` для связанных задач.
- **search** — срез 010 поиск не добавляет: поиск только в реестре (вне рамок спеки).

## Проверка

### Серверные тесты (19 файлов)
`test_instructions_models`, `test_instructions_access` (кто ставит, контролёр, видимость, руководители только
чтение), `test_instructions_create`, `test_instructions_dates` (периодичность, 31-е, обрезка сроком),
`test_instructions_reports` (даты, части, ранний отчёт, приёмка/возврат, итоговый), `test_instructions_close`,
`test_instructions_transfers` (запрос, согласование, отказ, один pending, пересчёт), `test_instructions_reminders`
(лестница, границы, тихие часы, идемпотентность), `test_instructions_notify` (виды, получатели, приоритет,
внешний текст), `test_instructions_digest`, `test_instructions_registry` (пресеты, фильтры, страницы, SQL),
`test_instructions_discipline` (два разреза, пример, Excel), `test_instructions_tasks` (связь и видимость),
`test_instructions_files` (20 МБ, ClamAV, карантин), `test_instructions_audit`, `test_instructions_retention`,
`test_instructions_deploy` (маршруты, cron, меню, статика, nginx, CSP), `test_instructions_seed`,
`test_instructions_stand`, `test_instructions_core_changes` (Purpose, права, settings/urls/cron), при
необходимости `test_instructions_boundaries`.

### Проход в браузере (10 сценариев)
`t10_01` реестр и пресеты, `t10_02` создание с основанием, `t10_03` отчёт и принятие, `t10_04` возврат и
повторный отчёт, `t10_05` перенос срока, `t10_06` напоминания и уведомления, `t10_07` дисциплина и Excel,
`t10_08` задачи из поручения, `t10_09` права (руководитель только чтение, чужое 404), `t10_10` 360 px.

### Нагрузка (NFR-720)
`fill_instructions.py`: 1 000 поручений на 100 сотрудников (основания, отчётные даты, отчёты, переносы);
`InstructionUser` — реестр, карточка, отчёт, решение, дисциплина. Порог p95 500 мс при 100 пользователях; замер —
T-10304 после решения владельца, с оговоркой об ограничении стенда.

### Требование → механизм → тест

| Требование | Механизм | Тест |
|---|---|---|
| FR-700 поля и основание | `Instruction`, `services.instructions` | `test_instructions_models`, `test_instructions_create` |
| FR-701 справочник видов | `InstructionBasisKind`, `services.basis` | `test_instructions_create` |
| FR-702 кто ставит | `access.can_assign` | `test_instructions_access` |
| FR-703 контролёр | `Instruction.controller`, смена | `test_instructions_access` |
| FR-704 исполнитель и соисполнители | `InstructionMember` | `test_instructions_create` |
| FR-705 отчётные даты | `services.dates` | `test_instructions_dates` |
| FR-706 отчёт к дате/сроку | `InstructionReport`, `services.reports` | `test_instructions_reports` |
| FR-707 снятие с контроля | `services.instructions.close` | `test_instructions_close` |
| FR-708 перенос | `InstructionTransfer` | `test_instructions_transfers` |
| FR-709 лестница | `services.reminders` | `test_instructions_reminders` |
| FR-710 тихие часы | `quiet.next_start` | `test_instructions_reminders` |
| FR-711 уведомления | `notify_rules` | `test_instructions_notify` |
| FR-712 сводка | `services.digest` | `test_instructions_digest` |
| FR-713 реестр | `services.registry` | `test_instructions_registry` |
| FR-714 дисциплина | `services.discipline` | `test_instructions_discipline` |
| FR-715 Excel | `services.excel` | `test_instructions_discipline` |
| FR-716 задачи | `InstructionTask`, `services.instructions.link_task` | `test_instructions_tasks` |
| FR-717 статусы | `Case/When`, `InstructionReportDate.state` | `test_instructions_registry`, `test_instructions_reports` |
| FR-718 журнал | `core.audit.record` | `test_instructions_audit` |
| FR-719 404 | `access.visible` | `test_instructions_access` |
| FR-720 360 px | `instructions.css` | e2e `t10_10` |
| FR-721 видимость цепочки | `access.visible`, `managed_units` | `test_instructions_access` |
| FR-722 увольнение/смена | `services.instructions.reassign` | `test_instructions_access` |
| FR-723 части отчёта | `InstructionReportPart` | `test_instructions_reports` |
| NFR-720 p95 | `InstructionUser`, `fill_instructions.py` | нагрузочный прогон |
| NFR-721 SQL | `registry`, `discipline` | `test_instructions_registry`, `test_instructions_discipline` |
| NFR-722 файлы | `services.files`, `file_purposes` | `test_instructions_files` |
| NFR-723 внешний текст | `notify_kinds` | `test_instructions_notify` |
| NFR-724 идемпотентность | задания | `test_instructions_reminders`, `test_instructions_retention` |
| NFR-725 360 px/браузеры | `instructions.css` | e2e `t10_10` |
| NFR-726 русский/Москва | тексты, `Europe/Moscow` | `test_instructions_deploy` |
| NFR-727 журнал | права `crm_app` | `test_instructions_audit` |
| NFR-728 профиль | `locustfile.py` | `test_instructions_deploy` |
| NFR-729 хранение | `services.retention` | `test_instructions_retention` |

## Риски

| Риск | Оценка | Что делаем |
|---|---|---|
| Много сущностей и статусов | высокая | сначала модели и служба статусов, затем экраны; каждый статус — тест |
| Отчётные даты и часовые пояса | средняя | даты без времени, Москва, тесты на 31-е и 29.02 |
| Лестница и пересчёт напоминаний | высокая | чистая функция моментов, тесты границ и переноса |
| Дисциплина: две шкалы | высокая | два разреза, пример с числами в тесте |
| Excel и формулы | средняя | `openpyxl`, только значения, тест чтения файла |
| Права руководителей только чтение | средняя | отдельные `can_view`/`can_decide`, e2e |
| Связь с задачами | средняя | публичная служба `tasks`, видимость по задаче |
| Хранение и файлы | средняя | удаление после фиксации, тест диска |
| Новые права и меню ломают прежние тесты | низкая | таблица правок в TASKS, как в 009 |
| Нагрузка на стенде | высокая | честный замер после решения владельца |

## Открытые вопросы

Нет: спорные правила разрешены в SPEC-010 «Решения уровня этой спеки»; владелец подписал SPEC-010.