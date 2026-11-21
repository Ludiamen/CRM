---
id: PLAN-009
вид: план
статус: черновик
версия: 2
зависит_от: SPEC-009, CONST, ADR-0002, ADR-0004, ADR-0009, ADR-0010, ADR-0011, ADR-0017, ADR-0018, REF-MOD-TASKS, TGT-ARCH, TGT-NFR, SPEC-002, SPEC-004, SPEC-005
основан_на: SPEC-009 sha256:166eed06c9d60f32a8821cc3bdcd77db2ef51d40cef5c5fe79cee25d020b386f
---

# План среза 009: Задачи

## Сверка с конституцией

| Инвариант | Как соблюдается |
|---|---|
| модуль-приложение | Новое приложение `apps.tasks`: собственные модели, службы, шаблоны, статика. Связи с другими модулями — только через точки расширения ядра и публичные службы `core`, `org`, `notify`; модели `org`/`notify` напрямую не импортируются. |
| настройка-без-кода | Срок хранения — строка `TaskSettings`; категории — справочник; права постановки и правки — права ролей через `role_sources` плюс правило структуры. В коде нет порогов и списков «кому можно». |
| интеграции-через-адаптеры | Файлы — `core.services.uploads` и ClamAV через `file_purposes`; уведомления — `notify.services.dispatch` и виды `notification_kinds`; поиск — `search_providers`. |
| аудит-изменений | Изменения полей — `core.services.audit.record` с «было/стало»; удаление — минимальный снимок по решению владельца (ADR-0018 пп. 15–16); журнал только дополняется. |
| пдн-152фз | Чужие задачи администратору недоступны (404); во внешние каналы только событие и ссылка; срок хранения — настройка, 3 года по умолчанию. |
| секреты-в-url | В адресах только номера задач, колонок и категорий; токенов, адресов и текстов нет. |
| sql-только-параметры | Все запросы — параметрами; ключи сортировок и фильтров — белый список. |
| стек-интерфейс | HTMX без состояния на клиенте; SortableJS — прогрессивное улучшение с запасным выбором в карточке; CSP без inline-скриптов и `style=`. |
| бесплатные-компоненты | SortableJS (MIT) в `static/vendor` с лицензией, `VERSIONS.md` и проверкой `tools/verify_vendor.py`. |
| тест-на-требование | Каждый FR и NFR — строка в таблице «требование → механизм → тест». |

## Технический контекст

### Новые компоненты и лицензии

- **SortableJS 1.15.6** (MIT): `static/vendor/Sortable-1.15.6.min.js`, `LICENSE-sortable`, раздел «SortableJS» в
  `VERSIONS.md`; `tools/verify_vendor.py` получает пакет `sortablejs@1.15.6` и сверку хеша и лицензии.
- Больше сторонних компонентов нет.

### Где живёт код

```
backend/apps/tasks/
  apps.py, extensions.py, models.py, urls.py, notify_kinds.py, audit_labels.py
  migrations/0001_initial.py
  services/   access, tasks, list, boards, plan, categories, comments, files, reminders,
              notify_rules, digest, retention, search, settings
  views/      pages (список, доски, карточка), actions (создание/правка/статус/перенос/удаление),
              comments, files, reminders, settings (категории и срок)
  templates/tasks/…   static/tasks/{tasks.js,tasks.css}
backend/tests/test_tasks_*.py, backend/tests/e2e/test_t09_*.py
backend/tests/load/fill_tasks.py, класс TaskUser в locustfile.py
```

### Точки расширения ядра

| Точка | Что регистрирует `tasks` |
|---|---|
| `menu_items` | «Задачи» (order 2), «Настройки задач» (order 65, `settings.portal`) |
| `role_sources` | права модуля `tasks.use`, `tasks.assign` |
| `notification_kinds` | `tasks.assigned`, `tasks.due_soon`, `tasks.due`, `tasks.overdue`, `tasks.subordinate_overdue`, `tasks.reminder`, `tasks.comment`, `tasks.subordinate_digest` |
| `search_providers` | группа «Задачи» (order 62): номер, название, описание, комментарии; только видимые |
| `card_sections` | раздел «Задачи» в карточке сотрудника |
| `audit_labels` | подписи `tasks.created`, `tasks.changed`, `tasks.comment_changed`, `tasks.deleted`, `tasks.reminder_set`, `tasks.retention_purged` |
| `file_purposes` | назначение `task` — ожидание/чистый/карантин |

### Изменения ядра и прежних модулей

| Файл | Изменение | Зачем |
|---|---|---|
| `core/models/files.py` + миграция `core 0012` | `Purpose.TASK = "task"` в конце перечня | вложения задач (FR-693) |
| `org/services/structure.py` | новый публичный `managed_units(user)` — узлы с отметкой руководителя или заместителя и вложенные (без обычных членств) | формула прав `manages` (ADR-0018 п. 10) |
| данные установки | права ролей `tasks.use`, `tasks.assign` через `role_sources`; по умолчанию у «Сотрудника ИТ» оба | права-данные (ADR-0018 п. 13) |
| `config/settings.py` | `"apps.tasks"` последним в `INSTALLED_APPS` | приложение среза |
| `config/urls.py` | `include("apps.tasks.urls")` под `apps.is_installed` | адреса `/tasks/…`, `/settings/tasks/…` |
| `config/cron.py` | `tasks_reminders` (`*/5 * * * *`), `tasks_digest` (`*/15 * * * *`), `tasks_retention` (`42 23 * * *`, 600 с) — под `is_installed` | напоминания, сводка, срок хранения |
| `deploy/nginx.conf`, `deploy/nginx.prod.conf` | `location ~ ^/tasks/files/$` с 25m | файлы задач (NFR-713) |
| `templates/_assets.html` | `tasks.css` и `tasks.js` (defer) для `/tasks/` и `/settings/tasks/` | доски и карточка |
| `static/vendor/` + `VERSIONS.md` + `tools/verify_vendor.py` | SortableJS 1.15.6 и его проверка | перетаскивание |
| `tests/load/locustfile.py` | класс `TaskUser` | профиль нагрузки (NFR-719) |

### Права среза

Два уровня, оба — данные (ADR-0018 п. 13):

- **Права ролей** через `role_sources`: `tasks.use` (открыть «Задачи», создать задачу себе, комментировать) и
  `tasks.assign` (ставить задачи другим — в пределах управляемых узлов). По умолчанию оба у роли «Сотрудник ИТ»;
  администратор может снять их у роли без правки кода. Категории и срок хранения — `settings.portal`.
- **Правило структуры** (ADR-0009): `tasks.services.access`:
  `managed_units(viewer)` — узлы с отметкой **руководителя или заместителя** и все вложенные
  (`org.services.structure.managed_units`, без обычных членств: иначе рядовой участник вышестоящего узла
  получил бы права на вложенные); `manages(viewer, person)` = пересечение `managed_units(viewer)` с
  `{u.id for u in units_of(person)}`; `can_set_task` = сам или (`tasks.assign` и `manages`);
  `can_edit_fields` = автор или `manages`; `can_change_status` = участник (исполнитель, соисполнитель) или
  `can_edit_fields`; `visible` = автор, участник или `manages` для автора и исполнителя. Проверка — до чтения
  записи: чужая задача 404.

### Запуск

Новых служб нет: web — страницы и действия, `maintenance` — задания cron, `notify` — рассылка. Миграции —
`core 0012`, `tasks 0001`; стенд обновляется по действующей процедуре после разрешения владельца.

## Модель данных

### Приложение `tasks` (миграция 0001)

| Модель | Поля | Индексы и ограничения |
|---|---|---|
| `Task` | `title` (300), `description` (10 000), `deadline` (дата, nullable), `author` (FK User, PROTECT), `assignee` (FK User, PROTECT), `status` (`new`/`in_progress`/`waiting`/`done`), `category` (FK TaskCategory, SET_NULL), `plan_column` (FK PlanColumn, SET_NULL), `created_at`, `updated_at`, `completed_at`, `deleted_at` | `(assignee, status)`, `(deadline)`, `(author)`, `(plan_column)`, `(category)`, `(deleted_at)` |
| `TaskMember` | `task` (FK, CASCADE), `user` (FK, PROTECT), `role` (`coexecutor`/`observer`) | уникальность `(task, user)`; индекс `(user)` |
| `TaskCategory` | `title` (100), `position` | уникальность `title`; индекс `position` |
| `PlanColumn` | `user` (FK, CASCADE), `title` (100), `position` | уникальность `(user, title)`; индекс `(user, position)` |
| `TaskReminder` | `task` (FK, CASCADE), `user` (FK, CASCADE), `kind` (`auto_soon`/`auto_due`/`auto_overdue`/`manual`), `moment` (datetime), `state` (`pending`/`sent`/`cancelled`), `postponed_to`, `created_at` | индекс `(state, moment)`; частичный уникальный `(task, user, kind)` при `kind LIKE 'auto%' AND state != 'cancelled'`; ручные не уникальны |
| `TaskComment` | `task` (FK, CASCADE), `author` (FK User, PROTECT), `text` (10 000), `edited_at`, `deleted_at`, `created_at` | индекс `(task, created_at)` |
| `TaskFile` | `task` (FK, CASCADE), `comment` (FK TaskComment, SET_NULL, nullable), `file` (FK StoredFile, PROTECT), `name` (255), `uploaded_by` (FK User, PROTECT), `created_at` | индексы `(task)`, `(comment)` |
| `TaskSettings` | `retention_years` (1–10, 3), `updated_at`, `updated_by` | `pk=1` |

Комментарии — **собственная `TaskComment`**, а не `core.Comment`: нужны признак правки, мягкое удаление
(«удалён — серой записью»), файлы и журнал без текста; `core.Comment` удаляет физически (так же сделано в
ленте — `feed.FeedComment`). Лента карточки — записи `core.AuditEntry` по объекту `task` плюс комментарии.

### Ядро

`core 0012`: `Purpose.TASK = "task"`. Больше изменений моделей прежних срезов нет.

## Ключевые механизмы

### Создание, поля и права (FR-674–678)
`tasks.services.tasks.create/update`: проверка текста (`title` 1–300 после обрезки), срока (дата), состава
(исполнитель — один действующий; соисполнители и наблюдатели — любые действующие, без повторов и без
исполнителя) и прав (`access`). Создание себе — всем с `tasks.use`; иной адресат — `can_set_task`. Изменения
полей пишутся в журнал «было/стало» и событие ленты; `updated_at` обновляется.

### Список, пресеты и фильтры (FR-685–686)
`services.list.rows` — один SQL с видимостью (автор/участник/`manages`), пресетами (`mine`, `authored`,
`subordinate`, `overdue`) и фильтрами из белого списка (`status`, `deadline` (`today`/`week`/`overdue`/`none`),
`assignee`, `category`); сортировки `deadline`/`updated`; страницы 20/50. «Просрочены» — дата срока раньше
сегодняшней и статус не «Готово». Состав подчинённых — на момент запроса (`managed_units` +
`subtree_member_ids`), без копий.

### Карточка (FR-674–678, 684, 693)
`views/pages.card`: карточка с лентой (журнал + комментарии), файлами, напоминаниями, выбором
статуса/срока/категории/колонки (запасной путь) и формами правки по правам. Выбор личной колонки виден только
владельцу плана на своём плане. `GET /tasks/<id>/` — 404 для невидимой; `POST /tasks/<id>/` — поля;
`POST /tasks/<id>/status/` — статус; ответы фрагментом для HTMX и страницей для обычного запроса.

### Доски и перетаскивание (FR-679–684)
`GET /tasks/board/status|deadline|plan|category/` — доски из колонок. `POST /tasks/<id>/move/` с `board` и
`value`: `status` — статус (права статуса); `deadline` — «today», «week», «none» (права полей; срок —
сегодня / ближайшая пятница строго после сегодня / снят; в «Просрочены» нельзя); `plan` — только владелец
плана на своей доске (`plan_column`, статус не меняется); `category` — категория или «Без категории» (права
полей). Ответ — обновлённые колонки. Клиент: SortableJS в `tasks.js` на `[data-board]`, отправка `POST` с CSRF;
без JS и на 360 px — выбор в карточке. «Стадии» показывают все четыре колонки, «Сроки» — без «Готово».

### «Мой план» и категории (FR-682–683)
`PlanColumn` — CRUD владельца (`/tasks/plan/columns/`); три колонки «Сегодня», «На этой неделе», «Потом»
создаются при первом открытии доски (лениво), а не при создании пользователя. Удалённая колонка переносит
задачи в первую. План другого сотрудника виден руководителю и заместителю только на чтение. Категории —
`/settings/tasks/categories/` под `settings.portal`; удаление снимает категорию у задач.

### Комментарии, файлы и лента (FR-693–694)
`services.comments`: добавить (все, кто видит задачу), править и удалить свой (мягко, `deleted_at` — серая
запись), события в ленте, записи журнала без текста. Файлы — `core.services.files` с назначением `task` и
ClamAV через `file_purposes`; до проверки недоступны, исполняемые и архивы с паролем отклоняются; имя файла —
в `TaskFile.name`. Доступ к файлу — с проверкой видимости задачи.

### Напоминания (FR-687–690)
`reminders.plan(task)`: `auto_soon` — начало рабочего дня за 1 рабочий день до момента срока; `auto_due` —
начало рабочего дня даты срока (нерабочая дата — первый рабочий день после); `auto_overdue` — начало
следующего рабочего дня после момента срока. Момент срока — `org.services.calendar` (`day_kind`, перенос на
рабочий день); «предыдущий рабочий день» — своя функция в `tasks.services.calendar` на базе `day_kind`.
Ручные: «за N рабочих дней до срока» или «на дату»; не больше 10 на задачу; ставит себе любой, кто видит
задачу; «на дату» вне рабочего времени сдвигается на `next_working_start` при создании; «Отложить» — на
1 рабочий день. `tasks_reminders` (каждые 5 минут) выбирает `pending` с `moment <= now`/`postponed_to`,
создаёт уведомление `dispatch.create` и помечает `sent`. Личные тихие часы — при доставке почты и push
(`notify.quiet`), портал показывает сразу (ADR-0011). Смена срока вызывает `plan` заново: автоматические и
ручные «за N рабочих дней» пересчитываются, при снятии срока ручные «за N рабочих дней» снимаются (FR-690),
«на дату» остаются; смена исполнителя/состава меняет получателей; завершение и удаление — `cancel_all`.

### Уведомления и сводка (FR-691–692)
Виды в `tasks.notify_kinds` (каталог `notify`). Получатели и приоритет — `notify_rules.recipients`: на
просрочку каждому человеку одно сообщение; руководителю и заместителю — `subordinate_overdue`; себе — ничего;
внешний текст постоянный, без названия и описания. Комментарии — `tasks.comment` участникам без автора.
`tasks_digest` (каждые 15 минут): если идёт рабочий день и за сегодня сводка не отправлена (ключ кэша
`tasks:digest:<дата>:<user>`), собирает просроченные и «горящие» задачи подчинённых (срок сегодня или «скоро» в
пределах рабочего дня) и создаёт одно уведомление `tasks.subordinate_digest`. Каналы, письмо «если не
прочитано за 15 минут» и тихие часы — механизм `notify`.

### Удаление, срок хранения (FR-695–696)
`POST /tasks/<id>/delete/` — автор, руководитель или заместитель узла исполнителя, второй шаг подтверждения;
мягкое удаление, снятие напоминаний, отмена уведомлений (`still_relevant`), журнал `tasks.deleted` с номером,
автором, исполнителем и статусом (без текста). `tasks_retention` (ночью): пачками по 1 000 удаляет задачи с
`deleted_at <= today − retention_years` (`TaskSettings`, 1–10, по умолчанию 3) вместе с файлами (строки и
диск после фиксации) и комментариями; одна запись `tasks.retention_purged`, только если удалено > 0; повтор
без ошибок. Действующие задачи не удаляются.

### Поиск, карточка сотрудника (FR-697–698)
Провайдер `tasks` (order 62): видимость как в списке, слова — параметрами, `ILIKE` по названию, описанию и
тексту комментариев, потолок 300 строк; строка — номер, название, исполнитель, срок, статус, отрывок.
Раздел карточки сотрудника — `card_sections`: задачи, где сотрудник исполнитель или соисполнитель и которые
видны смотрящему; себе и чужих нет.

### 360 px (FR-699)
`tasks.css`: до 900 px — одна колонка, карточка открывается по нажатию с «Назад»; доска прокручивается вбок
внутри `[data-board]`, страница — нет; на телефоне выбор статуса, срока, категории и колонки в карточке.

## Контракты

| Метод | Адрес | Что делает |
|---|---|---|
| GET | `/tasks/` | список с пресетами и фильтрами |
| GET | `/tasks/list/` | фрагмент списка (HTMX) |
| GET | `/tasks/board/status/`, `/deadline/`, `/plan/`, `/category/` | четыре доски |
| GET | `/tasks/new/` | форма создания |
| POST | `/tasks/` | создание |
| GET | `/tasks/<id>/` | карточка |
| POST | `/tasks/<id>/` | правка полей |
| POST | `/tasks/<id>/status/` | статус |
| POST | `/tasks/<id>/move/` | перенос на доске (`board`, `value`) |
| POST | `/tasks/<id>/delete/` | удаление (второй шаг `confirm=1`) |
| POST | `/tasks/<id>/comments/`, `/tasks/comments/<id>/edit/`, `/delete/` | комментарии |
| POST | `/tasks/files/` | загрузка файла к комментарию |
| GET | `/tasks/files/<id>/` | файл (X-Accel-Redirect, проверка видимости) |
| POST | `/tasks/<id>/remind/`, `/tasks/reminders/<id>/postpone/` | ручное напоминание и «отложить» |
| POST | `/tasks/plan/columns/`, `/…/<id>/`, `/…/<id>/delete/` | личные колонки |
| GET/POST | `/settings/tasks/` | срок хранения |
| GET/POST | `/settings/tasks/categories/…` | справочник категорий |

Зацепки: `[data-tasks-page="list|card|board|settings"]`, `[data-task-id]`, `[data-task-status]`,
`[data-board]`, `[data-column]`, `[data-task-card]`, `[data-move-url]`, `[data-task-field]`,
`[data-error][data-code]`, `[data-tasks-preset]`, `[data-plan-column]`, `[data-reminder]`, `[data-task-deleted]`.

## Интеграции

- **org** — `managed_units`, `units_of`, `unit_chain_ids`, `subtree_member_ids`, календарь, карточка сотрудника.
- **notify** — виды, каналы, тихие часы, сводки, рассылка `dispatch`.
- **core** — пользователи, файлы и ClamAV, журнал, настройки портала.
- **search** — поставщик «Задачи».
- **Срез 010 (поручения)** — будет раскладываться на эти задачи; связей в 009 нет.

## Проверка

### Серверные тесты (≈20 файлов)
`test_tasks_models`, `test_tasks_access` (правило `managed_units`: рядовой участник вышестоящего узла прав не
получает; заместители; цепочка; карточка сотрудника), `test_tasks_permissions`, `test_tasks_visibility`,
`test_tasks_create`, `test_tasks_edit`, `test_tasks_list`, `test_tasks_boards`, `test_tasks_move`,
`test_tasks_plan`, `test_tasks_categories`, `test_tasks_reminders`, `test_tasks_notify`, `test_tasks_digest`,
`test_tasks_comments` (TaskComment: права, правка, серая запись, журнал), `test_tasks_files` (20 МБ, ClamAV,
карантин, exe/архивы, доступ), `test_tasks_audit`, `test_tasks_retention`, `test_tasks_search`,
`test_tasks_card_section`, `test_tasks_deploy` (маршруты, cron, меню, статика, CSP, nginx 25m, права ролей),
`test_tasks_boundaries`, `test_tasks_core_changes` (Purpose, settings/urls/cron, `managed_units`, права ролей),
`test_tasks_seed`, `test_tasks_stand`.

### Проход в браузере (10 сценариев)
`t01` список и пресеты, `t02` личная задача от создания до «Готово», `t03` задача подчинённому, `t04` «Стадии»
перетаскиванием, `t05` «Сроки», `t06` «Мой план», `t07` категории, `t08` напоминания и уведомления, `t09`
комментарии и файлы, `t10` 360 px и права; Chrome и Firefox.

### Нагрузка (NFR-719)
`fill_tasks.py`: 1 000 задач на 100 сотрудников (статусы, сроки, категории, комментарии, напоминания);
`TaskUser` — список, пресеты, карточка, доски, перенос, комментарий, поиск. Порог NFR-710 — p95 500 мс при
100 пользователях; замер по T-7304 после решения владельца, с оговоркой об известных дефектах NFR-612/707 и
ограничении стенда.

### Требование → механизм → тест

| Требование | Механизм | Тест |
|---|---|---|
| FR-674 поля, номер, 300 знаков | `Task`, `tasks.create` | `test_tasks_models`, `test_tasks_create` |
| FR-675 исполнитель, соисполнители, наблюдатели | `Task`, `TaskMember`, `tasks.create` | `test_tasks_create`, `test_tasks_permissions` |
| FR-676 кому можно ставить | `access.can_set_task` | `test_tasks_permissions` |
| FR-677 видимость и цепочка | `access.visible/manages` | `test_tasks_visibility` |
| FR-678 права статуса и полей | `access.can_change_status/can_edit_fields` | `test_tasks_permissions`, `test_tasks_edit` |
| FR-679 статусы и возврат | `Task.status`, `views.actions.status` | `test_tasks_models`, `test_tasks_edit` |
| FR-680 доска «Стадии» | `views.pages.board_status`, `tasks.js` | `test_tasks_boards`, e2e `t04` |
| FR-681 доска «Сроки» | `views.boards.deadline`, `tasks.move_deadline` | `test_tasks_move`, e2e `t05` |
| FR-682 «Мой план» | `PlanColumn`, `views.plan`, `tasks.move_plan` | `test_tasks_plan`, e2e `t06` |
| FR-683 категории | `TaskCategory`, `views.settings`, `tasks.move_category` | `test_tasks_categories`, e2e `t07` |
| FR-684 запасной путь | карточка: выбор статуса/срока/категории/колонки | `test_tasks_boards`, e2e `t10` |
| FR-685 список, пресеты, фильтры | `services.list`, `views.pages.list` | `test_tasks_list`, e2e `t01` |
| FR-686 подчинённые на момент просмотра | `access.manages`, `subtree_member_ids` | `test_tasks_list`, e2e `t03` |
| FR-687 моменты напоминаний | `reminders.plan`, `tasks_reminders` | `test_tasks_reminders` |
| FR-688 ручные, отложить, лимит 10 | `TaskReminder`, `views.reminders` | `test_tasks_reminders` |
| FR-689 тихие часы, снятие | `notify.quiet`, `reminders.cancel_all` | `test_tasks_reminders`, `test_tasks_notify` |
| FR-690 пересчёт при смене срока | `tasks.update → reminders.plan` | `test_tasks_reminders` |
| FR-691 виды и приоритет | `notify_kinds`, `notify_rules.recipients` | `test_tasks_notify` |
| FR-692 каналы, 15 минут, внешний текст | `notify.dispatch`, `external_text` | `test_tasks_notify` |
| FR-693 комментарии, файлы, лента | `TaskComment`, `core.files`, `Purpose.TASK` | `test_tasks_comments`, `test_tasks_files` |
| FR-694 журнал «было/стало» | `core.audit.record` | `test_tasks_audit` |
| FR-695 мягкое удаление, снимок | `tasks.delete`, `audit` | `test_tasks_audit`, `test_tasks_permissions` |
| FR-696 срок хранения и ночное задание | `tasks_retention`, `TaskSettings` | `test_tasks_retention` |
| FR-697 поиск | `search_providers` (order 62) | `test_tasks_search` |
| FR-698 раздел карточки сотрудника | `card_sections` | `test_tasks_card_section` |
| FR-699 360 px | `tasks.css`, выбор в карточке | e2e `t10` |
| NFR-710 p95 500 мс | `TaskUser`, `fill_tasks.py`, T-7304 | нагрузочный прогон |
| NFR-711 перенос без перезагрузки | `tasks.js`, HTMX | e2e `t04`…`t07` |
| NFR-712 SQL параметрами | службы списка/поиска/доск | `test_tasks_list`, `test_tasks_search` |
| NFR-713 файлы 20 МБ, ClamAV | `core.files`, `file_purposes`, nginx 25m | `test_tasks_files`, `test_tasks_deploy` |
| NFR-714 внешний текст без названия | `notify_kinds.external_text` | `test_tasks_notify` |
| NFR-715 идемпотентность | `tasks_reminders`, `tasks_retention` | `test_tasks_reminders`, `test_tasks_retention` |
| NFR-716 360 px, браузеры | `tasks.css` | e2e `t10` |
| NFR-717 русский, Москва | тексты, `Europe/Moscow` | `test_tasks_deploy` |
| NFR-718 журнал только дополняется | `audit` | `test_tasks_audit` |
| NFR-719 профиль `TaskUser` | `locustfile.py`, `fill_tasks.py` | `test_tasks_deploy` |

### Прежние тесты, которые придётся поправить
Только с разрешения владельца, по одному тесту, диффом «было / стало»: меню (`test_org_permissions` и тесты
меню других срезов — «Задачи» order 2, «Настройки задач» order 65), хвост `INSTALLED_APPS`, число заданий
`config/cron.py` (`test_deploy_files`), перечень назначений `StoredFile.Purpose` (`test_core_uploads`), перечень
статики (`test_pages_stage3b`), перечень `location` nginx (`test_deploy_files`); `test_org_structure` — новая
функция `managed_units`. Точный «было / стало» — в TASKS-009.

## Риски

| Риск | Оценка | Что делаем |
|---|---|---|
| Права-данные: роль без `tasks.assign` меняет поведение | низкая | тест роли без права; правило структуры — второй замок |
| SortableJS: лицензия, CSP, проверка vendor | средняя | версия 1.15.6, LICENSE, `VERSIONS.md`, `verify_vendor`; без inline-скриптов |
| Порог NFR-710 на стенде 4 потока 1,2 ГГц недостижим | высокая | честный профиль (100 пользователей, 1 000 задач), замер по T-7304 после решения владельца; известные дефекты 007–008 записаны |
| Перетаскивание и одновременные правки | средняя | последний перенос побеждает, ответ доски перерисовывает колонки, журнал фиксирует оба |
| Видимость и права по структуре дороги в SQL | средняя | `managed_units`/`units_of` двумя запросами, `ANY(%s)`; замер в нагрузке |
| Напоминания каждые 5 минут | низкая | индекс `(state, moment)`, пачки по 1 000, частичный уникальный индекс |
| Сводка раз в день при нескольких воркерах | средняя | ключ кэша с датой, повтор на следующем цикле |
| Ночное удаление по сроку удалит лишнее | высокая | только `deleted_at IS NOT NULL`, отсчёт от удаления; тест «действующие не удаляются» |
| Файлы удалённой задачи на диске | средняя | удаление строк, затем файлов после фиксации (образец мессенджера) |
| Комментарии: своя модель вместо ядра | низкая | как `feed.FeedComment`; тесты правки, мягкого удаления, журнала |
| Поиск по комментариям дорог | средняя | потолок 300, `ILIKE` параметрами |
| «Просрочены» и уведомление считаются по-разному | низкая | правило спеки, тест на субботний срок |
| 360 px: горизонтальная прокрутка страницы | средняя | прокрутка только внутри доски, e2e |
| Правка прежних тестов (меню, cron, Purpose, nginx, org) | средняя | только с разрешения владельца, список в TASKS-009 |

## Открытые вопросы
Нет. Замер нагрузки — по решению владельца (как T-7304/T-8304 срезов 007–008).