---
id: PLAN-009
вид: план
статус: черновик
версия: 1
зависит_от: SPEC-009, CONST, ADR-0002, ADR-0004, ADR-0009, ADR-0010, ADR-0011, ADR-0017, ADR-0018, REF-MOD-TASKS, TGT-ARCH, TGT-NFR, SPEC-002, SPEC-004, SPEC-005
основан_на: SPEC-009 sha256:166eed06c9d60f32a8821cc3bdcd77db2ef51d40cef5c5fe79cee25d020b386f
---

# План среза 009: Задачи

## Сверка с конституцией

| Инвариант | Как соблюдается |
|---|---|
| модуль-приложение | Новое приложение `apps.tasks`: собственные модели, службы, шаблоны, статика. Связи с другими модулями — только через точки расширения ядра (`menu_items`, `notification_kinds`, `search_providers`, `card_sections`, `audit_labels`, `file_purposes`) и публичные службы `core`, `org`, `notify`; модели `org`/`notify`/`core` напрямую не импортируются (кроме `core.models.User` по общему правилу). |
| настройка-без-кода | Срок хранения задач, справочник категорий и права постановки/правки — данные: настройка портала, записи справочника, права ролей через `role_sources`. В коде нет порогов и списков «кому можно». |
| интеграции-через-адаптеры | Файлы — общий механизм `core.services.uploads` и ClamAV через точку `file_purposes`; уведомления — `notify.services.dispatch` и виды `notification_kinds`; поиск — `search_providers`. |
| аудит-изменений | Изменения полей задачи — `core.services.audit.record` с «было/стало»; удаление — минимальный снимок по решению владельца (ADR-0018 пп. 15–16); журнал только дополняется. |
| пдн-152фз | Чужие задачи администратору недоступны (404); во внешние каналы только событие и ссылка (`external_text`); срок хранения задач — настройка, 3 года по умолчанию. |
| секреты-в-url | В адресах только номера задач, колонок и категорий; токенов, адресов и текстов в адресах нет. |
| sql-только-параметры | Все запросы — параметрами; ключи сортировок и фильтров — белый список; динамика только в структуре SQL. |
| стек-интерфейс | HTMX без отдельного состояния на клиенте; перетаскивание — SortableJS, прогрессивное улучшение с запасным выбором в карточке; CSP без inline-скриптов и `style=`. |
| бесплатные-компоненты | SortableJS (MIT) кладётся в `static/vendor` с лицензией и записью в `VERSIONS.md`; `tools/verify_vendor.py` расширяется проверкой пакета. |
| тест-на-требование | Каждый FR и NFR — строка в таблице «требование → механизм → тест». |

## Технический контекст

### Новые компоненты и лицензии

- **SortableJS 1.15.6** (MIT) — перетаскивание карточек на досках: `static/vendor/Sortable-1.15.6.min.js`,
  `LICENSE-sortable`, раздел «SortableJS» в `VERSIONS.md`. `tools/verify_vendor.py` получает пакет
  `sortablejs@1.15.6` и сверку хеша/лицензии; своей ветки для «новее» у библиотеки нет — проверка только по
  версии.
- Больше сторонних компонентов нет: графики, календари и списки — свои шаблоны и Bootstrap.

### Где живёт код

```
backend/apps/tasks/
  apps.py            # регистрация точек, подписка на события
  extensions.py      # menu_items, notification_kinds, search_providers, card_sections, audit_labels, file_purposes
  models.py          # Task, TaskMember, TaskCategory, PlanColumn, TaskReminder, TaskFile
  migrations/0001_initial.py
  services/          # access, tasks, list, boards, plan, categories, reminders, notify_rules, feed, retention, search
  views/             # pages (список, доска, карточка), actions (создание/правка/перемещение/удаление),
                     # comments, files, reminders, settings (категории и срок)
  urls.py
  notify_kinds.py    # виды уведомлений задач
  audit_labels.py    # подписи действий и типов объектов
  templates/tasks/   # page, _list, _row, _card, _board, _column, _form, _comment, _file, settings…
  static/tasks/tasks.js, tasks.css
backend/tests/test_tasks_*.py        # серверные тесты среза (≈20 файлов)
backend/tests/e2e/test_t09_*.py      # браузерные сценарии
backend/tests/load/fill_tasks.py     # наполнение стенда для нагрузки
backend/tests/load/locustfile.py     # класс TaskUser
```

### Точки расширения ядра

| Точка | Что регистрирует `tasks` |
|---|---|
| `menu_items` | «Задачи» (order 2, без числа), «Настройки задач» (order 65, право `settings.portal`) |
| `notification_kinds` | `tasks.assigned`, `tasks.due_soon`, `tasks.due`, `tasks.overdue`, `tasks.subordinate_overdue`, `tasks.reminder`, `tasks.comment`, `tasks.subordinate_digest` |
| `search_providers` | группа «Задачи» (order 60): номер, название, описание, комментарии; только видимые |
| `card_sections` | раздел «Задачи» в карточке сотрудника — видимые смотрящему задачи (FR-698) |
| `audit_labels` | подписи `tasks.created`, `tasks.changed`, `tasks.deleted`, `tasks.reminder_set`, `tasks.retention_purged` |
| `file_purposes` | назначение `task` — ожидание/чистый/карантин для вложений комментариев и карточки |

### Изменения ядра и прежних модулей

| Файл | Изменение | Зачем |
|---|---|---|
| `core/models/files.py` + миграция `core 0012` | `Purpose.TASK = "task"` в конце перечня | вложения задач (FR-693) |
| `config/settings.py` | `"apps.tasks"` последним в `INSTALLED_APPS` | приложение среза |
| `config/urls.py` | `include("apps.tasks.urls")` под `apps.is_installed` | адреса `/tasks/…`, `/settings/tasks/…` |
| `config/cron.py` | `tasks_reminders` (`*/5 * * * *`, maintenance), `tasks_digest` (`*/15 * * * *`, maintenance), `tasks_retention` (`45 23 * * *`, maintenance, 600 с) — под проверкой установки | напоминания, сводка, срок хранения |
| `templates/_assets.html` | `tasks.css` и `tasks.js` (defer) для `/tasks/` и `/settings/tasks/` | доски и карточка |
| `static/vendor/` + `VERSIONS.md` + `tools/verify_vendor.py` | SortableJS 1.15.6 и его проверка | перетаскивание |
| `tests/load/locustfile.py` | класс `TaskUser` | профиль нагрузки (NFR-719) |

### Права среза

Отдельных прав ролей у среза нет (как у мессенджера): задачи доступны всем действующим сотрудникам, а
«кому можно ставить и править» — правило по структуре (ADR-0009, ADR-0018 п. 9–12), не набор прав. Категории
и срок хранения — право `settings.portal` (администратор портала). Правило структуры вынесено в службу
`tasks.services.access`, чтобы его можно было заменить правами без правки вьюх.

### Запуск

`docker compose --profile dev`: новых служб нет. Web — страницы и действия, `maintenance` — задания cron,
`notify` — рассылка уведомлений. Миграции — `core 0012`, `tasks 0001`; стенд обновляется по действующей
процедуре (копия → сборка → миграции → перезапуск после разрешения владельца).

## Модель данных

### Приложение `tasks` (миграция 0001)

| Модель | Поля | Индексы и ограничения |
|---|---|---|
| `Task` | `title` (300), `description` (текст), `deadline` (дата, nullable), `author` (FK User, PROTECT), `assignee` (FK User, PROTECT), `status` (`new`/`in_progress`/`waiting`/`done`), `category` (FK TaskCategory, SET_NULL, nullable), `plan_column` (FK PlanColumn, SET_NULL, nullable), `created_at`, `updated_at`, `completed_at` (nullable), `deleted_at` (nullable) | `(assignee, status)`, `(deadline)`, `(author)`, `(plan_column)`, `(category)`, `(deleted_at)`; `title` не пустой (проверка службы), статус из перечня |
| `TaskMember` | `task` (FK, CASCADE), `user` (FK, PROTECT), `role` (`coexecutor`/`observer`) | уникальность `(task, user)`; индекс `(user)` |
| `TaskCategory` | `title` (100), `position` (int) | уникальность `title`; индекс `position` |
| `PlanColumn` | `user` (FK, CASCADE), `title` (100), `position` (int) | уникальность `(user, title)`; индекс `(user, position)` |
| `TaskReminder` | `task` (FK, CASCADE), `user` (FK, CASCADE), `kind` (`auto_soon`/`auto_due`/`auto_overdue`/`manual`), `moment` (datetime), `state` (`pending`/`sent`/`cancelled`), `postponed_to` (nullable), `created_at` | индекс `(state, moment)`; уникальность `(task, user, kind)` для автоматических |
| `TaskFile` | `task` (FK, CASCADE), `comment` (FK core Comment, SET_NULL, nullable), `file` (FK StoredFile, CASCADE), `uploaded_by` (FK User, PROTECT), `created_at` | индекс `(task)` |

Комментарии — общая модель `core.Comment` с `object_ref = "tasks.task:<id>"`; лента карточки — записи
`core.AuditEntry` по объекту `task` плюс комментарии. Отдельной модели событий нет.

### Ядро

`core 0012`: `Purpose.TASK = "task"` (вложение задачи). Больше изменений моделей прежних срезов нет.

## Ключевые механизмы

### Создание, поля и права (FR-674–678)
Служба `tasks.services.tasks.create/update` проверяет текст (`title` 1–300 после обрезки, описание — любой
текст до 10 000), срок (дата), состав (исполнитель — один действующий, соисполнители и наблюдатели — любые
действующие, без повторов и без исполнителя) и права вызывающего. Права — `access.py`: `manages(viewer,
person)` пересекает `org.services.structure.work_units_of(viewer)` с `unit_chain_ids(person)` (обе отметки —
руководитель и заместитель, вся цепочка вышестоящих); `can_set_task(viewer, assignee)` — исполнитель сам или
`manages`; `can_edit_fields(viewer, task)` — автор или `manages(viewer, task.assignee)`;
`can_change_status(viewer, task)` — участник задачи (исполнитель, соисполнитель) или `can_edit_fields`;
`visible(user)` — автор, участник, `manages` (для исполнителя и автора). Создание задачи адресатом себя
разрешено всем; иной адресат — только `can_set_task`. Все изменения полей пишутся в журнал «было/стало» и
событие ленты; `updated_at` обновляется.

### Список, пресеты и фильтры (FR-685–686)
`services.list.rows(user, preset, filters, sort, page)` — один SQL с видимостью (`author`/участник/`manages`),
пресетами (`mine`, `authored`, `subordinate`, `active`, `overdue`) и фильтрами из белого списка (`status`,
`deadline` (`today`/`week`/`overdue`/`none`), `assignee`, `category`); сортировки `deadline`/`updated`;
страницы 20/50. «Просрочены» — дата срока раньше сегодняшней и статус не «Готово». Состав подчинённых — на
момент запроса (`work_units_of` + `subtree_member_ids`/`unit_chains`), без хранения копий.

### Карточка (FR-674…678, 684, 693)
`views/pages.card` отдаёт карточку задачу с лентой (журнал + комментарии), файлами, напоминаниями, выбором
статуса/срока/категории/колонки (запасной путь) и формами правки по правам. `GET /tasks/<id>/` — 404 для
невидимой задачи; `POST /tasks/<id>/` — правка полей; `POST /tasks/<id>/status/` — статус; все — HTMX-ответы
(перерисованный узел) и полные страницы для обычных запросов.

### Доски и перетаскивание (FR-679–684)
`GET /tasks/board/status|deadline|plan|category/` — доска из колонок (по статусам, группам сроков, личным
колонкам, категориям). `POST /tasks/<id>/move/` с `board` и `value`:
- `status` — смена статуса (права статуса);
- `deadline` — «today», «week», «none» (перенос в «Просрочены» запрещён, права полей), срок ставится на
  сегодня / ближайшую пятницу строго после сегодня / снимается;
- `plan` — только владелец плана (текущий сотрудник) на своей доске; меняет `plan_column`, статус не трогает;
- `category` — категория или «Без категории» (права полей).
Ответ — обновлённые колонки доски (HTMX-фрагмент). Клиент: SortableJS в `tasks.js` на `[data-board]`;
`tasks.js` отправляет `POST` с CSRF из формы и без перезагрузки; без JS (и на 360 px) — выбор в карточке.
«Стадии» и «Сроки» показывают задачи без «Готово» на «Сроках»; «Стадии» — с «Готово».

### «Мой план» и категории (FR-682–683)
`PlanColumn` — CRUD владельца (`/tasks/plan/columns/` — добавить, переименовать, удалить, порядок; удалённая
колонка переносит задачи в первую). Доска «Мой план» по умолчанию открывает план текущего сотрудника;
план другого сотрудника (руководителю/заместителю) — только чтение. Категории — `/settings/tasks/categories/`
под `settings.portal` (добавить, переименовать, удалить, порядок); удаление снимает категорию у задач.

### Напоминания (FR-687–690)
Автоматические напоминания создаются и пересчитываются службой `reminders.plan(task)`:
`auto_soon` — момент = начало рабочего дня за 1 рабочий день до момента срока; `auto_due` — начало рабочего
дня даты срока (нерабочая дата — первый рабочий день после); `auto_overdue` — начало следующего рабочего дня
после момента срока. Момент срока считается `org.services.calendar` (`day_kind`, перенос на рабочий день);
функция «предыдущий рабочий день» добавляется в `tasks.services.calendar` (на базе `day_kind`), календарь не
правится. Ручные — «за N рабочих дней до срока» или «на дату», не больше 10 на задачу, ставит себе любой, кто
видит задачу; «Отложить» переносит на 1 рабочий день. `tasks_reminders` (каждые 5 минут) выбирает
`pending` с `moment <= now` (с учётом `postponed_to`), создаёт уведомление через `dispatch.create` и
помечает `sent`; в тихие часы момент сдвигается на `next_working_start` (тихие часы считает `notify` при
доставке — задание не создаёт уведомление ночью, а переносит на утро). Смена срока/исполнителя/состава
вызывает `plan` заново: лишние автоматические напоминания отменяются, новые создаются; завершение и удаление
— `cancel_all`. Идемпотентность — уникальность `(task, user, kind)` и `state`.

### Уведомления и сводка (FR-691–692)
Виды в `tasks.notify_kinds` (каталог `notify`): `tasks.assigned`, `tasks.due_soon`, `tasks.due`,
`tasks.overdue`, `tasks.subordinate_overdue`, `tasks.reminder`, `tasks.comment`, `tasks.subordinate_digest`.
Получатели и приоритет при совмещении ролей — служба `notify_rules.recipients(task, event)`: на просрочку
каждому человеку одно сообщение; руководителю и заместителю — `subordinate_overdue`; себе — ничего. Внешний
текст — постоянный, без названия и описания. Комментарии — `tasks.comment` участникам без автора.
`tasks_digest` (каждые 15 минут): если у руководителя/заместителя идёт рабочий день (`calendar.is_working_time`)
и за сегодня сводка не отправлена (ключ кэша `tasks:digest:<дата>:<user>`), собирает просроченные и «горящие»
задачи подчинённых (срок сегодня или «скоро» в пределах рабочего дня) и создаёт одно уведомление
`tasks.subordinate_digest`. Письмо «если не прочитано за 15 минут», тихие часы и каналы — механизм `notify`.

### Комментарии, файлы и лента (FR-693–694)
Комментарии — `core.services.comments` (`add`/`update`/`delete` по `object_ref`); файлы к комментарию — общий
загрузчик `core.services.files.upload` с назначением `task` и проверкой ClamAV через `file_purposes`
(ожидание → чистый / карантин; до проверки недоступен, исполняемые и архивы с паролем отклоняются).
Лента карточки — журнал задачи (`audit`) + комментарии; правка и удаление комментария пишутся в журнал без
текста. Доступ к файлу — через `views/files` с проверкой видимости задачи (как в мессенджере).

### Удаление, срок хранения (FR-695–696)
`POST /tasks/<id>/delete/` — автор, руководитель или заместитель узла исполнителя, второй шаг подтверждения;
мягкое удаление: `deleted_at`, снятие напоминаний, отмена уведомлений (`still_relevant`), запись журнала
`tasks.deleted` с номером, автором, исполнителем и статусом (без текста). `tasks_retention` (ночью): пачками
по 1 000 удаляет задачи с `deleted_at <= сегодня − retention_years` (настройка `tasks_retention_years`, 1–10,
по умолчанию 3), вместе с файлами (строки и диск после фиксации) и комментариями; одна запись журнала
`tasks.retention_purged`, только если удалено > 0; повтор — без ошибок. Действующие задачи не удаляются.

### Поиск, карточка сотрудника (FR-697–698)
Провайдер поиска `tasks` (order 60): видимость как в списке, слова — параметрами, `ILIKE` по названию и
описанию и `ILIKE` по тексту комментариев (`core.Comment`), потолок 300 строк; строка — номер, название,
исполнитель, срок, статус, отрывок. Раздел карточки сотрудника — `card_sections`: задачи, где сотрудник
исполнитель или соисполнитель и которые видны смотрящему; не себе и без чужих задач.

### 360 px (FR-699)
`tasks.css`: список и карточка — одна колонка до 900 px; доска — горизонтальная прокрутка внутри
`[data-board]`, страница не прокручивается; карточка на телефоне — выбор статуса, срока, категории и колонки
вместо перетаскивания; проверка — `helpers.no_horizontal_scroll` и ширина доски.

## Контракты

Адреса и зацепки (CONTRACT-009 фиксирует то же самое для тестов):

| Метод | Адрес | Что делает |
|---|---|---|
| GET | `/tasks/` | список задач с пресетами и фильтрами |
| GET | `/tasks/list/` | фрагмент списка (HTMX) |
| GET | `/tasks/board/status/` | доска «Стадии» |
| GET | `/tasks/board/deadline/` | доска «Сроки» |
| GET | `/tasks/board/plan/` | «Мой план» (свой; `?user=<id>` — чужой только для чтения) |
| GET | `/tasks/board/category/` | доска «Категории» |
| GET | `/tasks/new/` | форма создания |
| POST | `/tasks/` | создание задачи |
| GET | `/tasks/<id>/` | карточка |
| POST | `/tasks/<id>/` | правка полей |
| POST | `/tasks/<id>/status/` | смена статуса |
| POST | `/tasks/<id>/move/` | перенос на доске (`board`, `value`) |
| POST | `/tasks/<id>/delete/` | удаление (второй шаг — `confirm=1`) |
| POST | `/tasks/<id>/comments/` | комментарий |
| POST | `/tasks/comments/<id>/edit/`, `/delete/` | правка и удаление своего комментария |
| POST | `/tasks/files/` | загрузка файла к комментарию |
| GET | `/tasks/files/<id>/`, `/tasks/files/<id>/thumb/` | файл и эскиз (X-Accel-Redirect) |
| POST | `/tasks/<id>/remind/`, `/tasks/reminders/<id>/postpone/` | ручное напоминание и «отложить» |
| POST | `/tasks/plan/columns/`, `/…/<id>/`, `/…/<id>/delete/` | личные колонки |
| GET | `/settings/tasks/` | срок хранения |
| GET/POST | `/settings/tasks/categories/…` | справочник категорий |

Зацепки для тестов: `[data-tasks-page="list|card|board|settings"]`, `[data-task-id]`, `[data-task-status]`,
`[data-board="status|deadline|plan|category"]`, `[data-column="…"]`, `[data-task-card]`, `[data-move-url]`,
`[data-task-field="…"]`, `[data-error="<поле>"][data-code]`, `[data-tasks-preset]`, `[data-plan-column]`,
`[data-reminder]`, `[data-task-deleted]`.

## Интеграции

- **org** — структура и цепочки узлов (`work_units_of`, `unit_chain_ids`, `subtree_member_ids`), календарь
  (`day_kind`, `next_working_start`, `is_working_time`), карточка сотрудника (`card_sections`).
- **notify** — виды уведомлений, каналы, тихие часы, сводки, отложенная доставка, рассылка через `dispatch`.
- **core** — пользователи, комментарии, файлы и ClamAV, журнал, настройки портала, поиск.
- **search** — поставщик «Задачи» через `search_providers`.
- **Срез 010 (поручения)** — будет раскладываться на эти задачи; в срезе 009 связей нет.

## Проверка

### Серверные тесты (≈20 файлов)
`test_tasks_models` (поля, ограничения, миграции), `test_tasks_access` (правило структуры, заместители,
цепочка, карточка сотрудника), `test_tasks_permissions` (создание, правка полей, статус, чужие), `test_tasks_visibility`
(участники, руководители, администратор, перевод), `test_tasks_create`, `test_tasks_edit` (поля, журнал),
`test_tasks_list` (пресеты, фильтры, сортировки, страницы, SQL параметрами), `test_tasks_boards` (четыре доски,
колонки, числа), `test_tasks_move` (права, «Просрочены», пятница, «Готово» вне «Сроков»),
`test_tasks_plan` (колонки, чужой план, удаление колонки), `test_tasks_categories` (справочник, удаление,
«Без категории»), `test_tasks_reminders` (моменты, пересчёт, отложить, тихие часы, лимит 10),
`test_tasks_notify` (виды, получатели, приоритет, письмо 15 минут), `test_tasks_digest` (сводка, один раз в
день, «горящие»), `test_tasks_comments` (права, серая запись, журнал), `test_tasks_files` (20 МБ, ClamAV,
карантин, exe/архивы, доступ), `test_tasks_audit` (жёлтые записи, минимальный снимок, только дополнение),
`test_tasks_retention` (только удалённые, отсчёт, файлы и комментарии, идемпотентность, настройка),
`test_tasks_search` (видимость, номер, комментарии, потолок), `test_tasks_card_section`, `test_tasks_deploy`
(маршруты, cron, меню, статика, CSP), `test_tasks_boundaries` (импорты), `test_tasks_core_changes` (Purpose,
settings/urls/cron), `test_tasks_seed`, `test_tasks_stand` (сброс стенда).

### Проход в браузере (10 сценариев)
`t01` список и пресеты, `t02` личная задача от создания до «Готово», `t03` задача подчинённому и «Задачи
подчинённых», `t04` доска «Стадии» перетаскиванием, `t05` «Сроки» (пятница, запрет «Просрочены»), `t06`
«Мой план» (колонки, чужой план только для чтения), `t07` категории и доска, `t08` напоминания и уведомления,
`t09` комментарии, файлы, лента, `t10` 360 px и права. Проверки — Chrome и Firefox (общий e2e-механизм).

### Нагрузка (NFR-719)
`fill_tasks.py` (только под `E2E_STAND=1`): 1 000 задач на 100 сотрудников, распределение статусов, сроков,
категорий, комментариев и напоминаний; `TaskUser` — список, пресеты, карточка, доски, перенос, комментарий,
поиск. Порог NFR-710 — p95 500 мс при 100 пользователях; замер по правилам T-7304 на остывшей машине после
отдельного решения владельца, с оговоркой об известных дефектах NFR-612/707 и ограничении стенда.

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
| FR-688 ручные напоминания, отложить, лимит | `TaskReminder`, `views.reminders` | `test_tasks_reminders` |
| FR-689 тихие часы, снятие | `notify.quiet`, `reminders.cancel_all` | `test_tasks_reminders`, `test_tasks_notify` |
| FR-690 пересчёт при смене срока | `tasks.update → reminders.plan` | `test_tasks_reminders` |
| FR-691 виды уведомлений, приоритет | `notify_kinds`, `notify_rules.recipients` | `test_tasks_notify` |
| FR-692 каналы, 15 минут, внешний текст | `notify.dispatch`, `external_text` | `test_tasks_notify` |
| FR-693 комментарии, файлы, лента | `core.comments`, `core.files`, `Purpose.TASK` | `test_tasks_comments`, `test_tasks_files` |
| FR-694 журнал «было/стало» | `core.audit.record` | `test_tasks_audit` |
| FR-695 мягкое удаление, снимок | `tasks.delete`, `audit` | `test_tasks_audit`, `test_tasks_permissions` |
| FR-696 срок хранения и ночное задание | `tasks_retention`, настройка | `test_tasks_retention` |
| FR-697 поиск | `search_providers` (order 60) | `test_tasks_search` |
| FR-698 раздел карточки сотрудника | `card_sections` | `test_tasks_card_section` |
| FR-699 360 px | `tasks.css`, выбор в карточке | e2e `t10` |
| NFR-710 p95 500 мс | `TaskUser`, `fill_tasks.py`, T-7304 | нагрузочный прогон |
| NFR-711 перенос без перезагрузки | `tasks.js`, HTMX | e2e `t04`…`t07` |
| NFR-712 SQL параметрами | службы списка/поиска/доск | `test_tasks_list`, `test_tasks_search` |
| NFR-713 файлы 20 МБ, ClamAV | `core.files`, `file_purposes` | `test_tasks_files` |
| NFR-714 внешний текст без названия | `notify_kinds.external_text` | `test_tasks_notify` |
| NFR-715 идемпотентность | `tasks_reminders`, `tasks_retention` | `test_tasks_reminders`, `test_tasks_retention` |
| NFR-716 360 px, браузеры | `tasks.css` | e2e `t10` |
| NFR-717 русский, Москва | тексты, `Europe/Moscow` | `test_tasks_deploy` |
| NFR-718 журнал только дополняется | `audit` | `test_tasks_audit` |
| NFR-719 профиль `TaskUser` | `locustfile.py`, `fill_tasks.py` | `test_tasks_deploy` |

### Прежние тесты, которые придётся поправить
Каждая правка — только с разрешения владельца, по одному тесту, с диффом «было / стало» (как в срезах
005–008). Список уточняется при написании TASKS-009; ожидаемые места: перечень и порядок пунктов меню
(`test_org_permissions` и тесты меню других срезов — добавляются «Задачи» order 2 и «Настройки задач» order 65),
хвост `INSTALLED_APPS` в тестах развёртывания, число заданий `config/cron.py` в `test_deploy_files`, перечень
назначений `StoredFile.Purpose` в `test_core_uploads` (добавляется `task`), перечень статики в
`test_pages_stage3b` (если перечисляются файлы среза). Отдельно проверяется, что тесты ёмкости и прежние
срезы не меняют поведения без `apps.tasks`.

## Риски

| Риск | Оценка | Что делаем |
|---|---|---|
| SortableJS: лицензия, CSP, проверка vendor | средняя | фиксированная версия 1.15.6, LICENSE, `VERSIONS.md`, `verify_vendor`; никаких inline-скриптов, инициализация в `tasks.js` |
| Порог NFR-710 на стенде 4 потока 1,2 ГГц недостижим | высокая | порог честный (100 пользователей, 1 000 задач), замер по T-7304 после решения владельца; известные дефекты 007–008 записаны |
| Перетаскивание и одновременные правки (двое двигают одну карточку) | средняя | последний перенос побеждает, ответ доски перерисовывает колонки; журнал фиксирует оба изменения |
| Видимость и права по структуре дороги в SQL | средняя | `work_units_of`/`unit_chains` двумя запросами, дальше в памяти; фильтр по `ANY(%s)`; замер в нагрузке |
| Напоминания каждые 5 минут создают нагрузку | низкая | пачки по 1 000, индекс `(state, moment)`, идемпотентность уникальностью |
| Сводка «один раз в день» при нескольких воркерах | средняя | ключ кэша с датой; при сбое — повтор на следующем цикле, дублей нет |
| Ночное удаление по сроку удалит лишнее | высокая | только `deleted_at IS NOT NULL` и истёкший срок от даты удаления; тест «действующие не удаляются» |
| Файлы удалённой задачи остаются на диске | средняя | удаление строк, затем файлов с диска после фиксации (образец мессенджера), тест |
| Поиск по комментариям дорог | средняя | потолок 300, `ILIKE` с параметрами, индекс не нужен на 1 000 задач; замер |
| «Просрочены» и уведомление считаются по-разному | низкая | правило спеки названо явно, тест на субботний срок |
| 360 px: горизонтальная прокрутка страницы | средняя | прокрутка только внутри доски, проверка e2e |
| Правка прежних тестов (меню, cron, Purpose) | средняя | только с разрешения владельца, список в TASKS-009, каждое — диффом |

## Открытые вопросы
Нет. Замер нагрузки — по решению владельца (как T-7304/T-8304 срезов 007–008).