---
id: PLAN-012
вид: план
статус: утверждён
версия: 4
зависит_от: SPEC-012, CONST, ADR-0002, ADR-0004, ADR-0009, ADR-0013, ADR-0019, ADR-0020, ADR-0021, REF-CAP, REF-UX, REF-SRC, TGT-ARCH, TGT-NFR, SPEC-002, SPEC-003, SPEC-004, SPEC-009, SPEC-010, SPEC-011
основан_на: SPEC-012 sha256:c3c24f253fffa0c1a5c16be19b93e6f8421d6c02eb798cf7d6f96eaaf62788d6
подпись: Максим | 2026-11-25T21:46+03:00 | sha256:dae37607295697e411bf3c64de1ecd0a279029c4db561a16e2867d757503d5a0
---

# План среза 012: Заявки: очередь и связи

## Сверка с конституцией

- **модуль-приложение.** Нового приложения нет. `servicedesk` расширяется собственными моделями и службами;
  связь с `tasks` хранится номером заявки без FK и читается только через публичные службы обоих приложений.
- **настройка-без-кода.** Режим очереди и список наблюдателей являются данными `servicedesk`, а недоступность
  сотрудника — данными `core.User`; глобальные права и их начальные выдачи не меняются.
- **права и минимум доступа.** `can_view` отвечает за чтение, `can_work` — за мутации. Наблюдатель имеет
  `can_view`, но не `can_work`; все маршруты и публичные службы применяют это разделение.
- **аудит-изменений.** Смена режима, наблюдатели, недоступность, автораспределение, оценка и создание задачи
  пишутся в дописываемый журнал; системные действия имеют пустого автора.
- **пдн-152фз.** Оценка не раскрывает заявителю тему, переписку или данные; внешние уведомления содержат
  только событие и ссылку. Заявитель не видит связь заявки с задачами.
- **секреты-в-url.** Код оценки не попадает в URL, журнал или интерфейс: он принимается только POST и после
  проверки заменяется короткой сессией.
- **sql-только-параметры.** Фильтры, сортировки, отчёт и выборки задач используют ORM и белые списки.
- **стек-интерфейс и бэкенд.** Django 5.2, PostgreSQL, серверные шаблоны и HTMX; новых фреймворков и
  глобальных прав нет, cron для автораспределения и истечения недоступности не нужен.
- **тест-на-требование.** Каждое FR/NFR получает тест — серверный или браузерный; у визуального FR-781
  проверка только браузерная, остальные — серверные и приёмочные. Семь сценариев `test_t12_*` проходят в
  настоящем браузере, включая ширину 360 px.
- **эталон-не-копия.** Используются только подтверждённые поведенческие решения SPEC-012/ADR-0021 и
  собственные контракты портала, без копирования чужого кода, разметки или текстов.

## Технический контекст

Сейчас `access.visible_tickets` и `can_work` смешивают чтение и действие
(`backend/apps/servicedesk/services/access.py:54-76`), `menu_visible` опирается на узлы работы
(`backend/apps/servicedesk/services/access.py:93-105`), а `public.briefs` вызывает видимость
(`backend/apps/servicedesk/services/public.py:29-40`). Создание проходит через
`tickets.create` (`backend/apps/servicedesk/services/tickets.py:162-246`), где уже применяются
`take_by`, категория и уровень SLA. Снятие ответственного выполняют `assignment` и `reconcile`
(`backend/apps/servicedesk/services/assignment.py:78-99`,
`backend/apps/servicedesk/services/reconcile.py:17-42`), передача и смена категории — `transfer`
(`backend/apps/servicedesk/services/transfer.py:56-137`), закрытие и циклы — `closing`
(`backend/apps/servicedesk/services/closing.py:80-183`).

Очередь сейчас является отметкой `Queue` узла структуры (`backend/apps/servicedesk/models.py:140-152`),
  а кандидаты строятся через `structure.queue_people` (`backend/apps/org/services/structure.py:381-421`).
Отчёт 011 уже оставил показатель оценки пустым (`backend/apps/servicedesk/services/reports.py:141-169`).
Письма проходят через `letters.send`/`render` (`backend/apps/servicedesk/services/letters.py:105-184`).
Задача имеет мягкое удаление (`backend/apps/tasks/models.py:39-66`), а её видимость проверяется
`tasks.services.access.visible` (`backend/apps/tasks/services/access.py:45-86`).

## Новые компоненты и лицензии

Новых пакетов и лицензий нет. Crockford base32, rate limit, короткая сессия и генерация Excel
реализуются существующими средствами проекта; Excel продолжает использовать уже установленный `openpyxl`.

## Где живёт код

```text
backend/apps/core/models/accounts.py
  User.unavailable_until и снимок причины/кто/когда
backend/apps/core/services/accounts.py
  set_availability: запись полей, проверки и аудит
backend/apps/core/views/me.py, views/staff_actions.py
  своя доступность и карточка сотрудника для администратора
backend/apps/core/migrations/0017_user_unavailability.py
backend/apps/org/services/availability.py
  проверка руководителя узла и вызов set_availability
backend/apps/org/views/members.py
  форма доступности для руководителя узла
backend/apps/servicedesk/models.py
  QueueRule, QueueObserver, TicketRating; связи и ограничения
backend/apps/servicedesk/migrations/0005_queue_links.py
  правила, наблюдатели, оценки
backend/apps/servicedesk/services/access.py
  can_view/can_work, наблюдатель, видимые списки и кандидаты
backend/apps/servicedesk/services/distribution.py
  off/evenly/strictly/all, блокировки, возврат и идемпотентность
backend/apps/servicedesk/services/rating.py
  циклы оценки, Crockford-код, POST-сессия, срок и rate limit
backend/apps/servicedesk/services/task_links.py
  публичные справки задач и создание задачи из видимой заявки
backend/apps/servicedesk/notify_kinds.py
  расширение существующих видов уведомлений и получателей
backend/apps/servicedesk/audit_labels.py
  русские подписи новых событий и полей
backend/apps/servicedesk/services/{tickets,assignment,reconcile,transfer,closing,replies,letters,reports,public,queues}.py
  точки вызова распределения, оценки, видимости, писем, отчёта и связи
backend/apps/servicedesk/views/{settings,ticket_card,tickets_list,reports,rating}.py
  настройка очереди, карточка, список, отчёт и открытая оценка
backend/apps/servicedesk/urls.py, extensions.py, stand.py
  маршруты, меню/части карточки и сброс стенда
backend/apps/tasks/models.py
  Task.ticket_number
backend/apps/tasks/migrations/0002_ticket_number.py
backend/apps/tasks/services/{tasks,access}.py, views/pages.py, urls.py
  связь, предзаполнение, блок заявки и маршруты задачи
backend/apps/tasks/services/task_links.py
  create_from_ticket: узкая точка исключения tasks.assign и ticket_number
backend/apps/tasks/stand.py
  очистка Task и Task.ticket_number вместе с задачами
backend/templates/servicedesk/{queues,card,rating,reports}/
backend/templates/tasks/
backend/tests/test_sd_012_*.py, backend/tests/test_tasks_ticket_links.py
backend/tests/e2e/test_t12_*.py
```

## Изменения ядра и прежних модулей

| Область | Изменение | Причина |
|---|---|---|
| `core.User` | `unavailable_until` включительно, примечание, `unavailable_by`, `unavailable_at`; миграция `core 0017` | свойство сотрудника, доступное профилю и ядру без зависимости от очереди |
| `servicedesk.Queue` | `QueueRule` one-to-one с режимом `off/evenly/strictly/all` и указателем; `QueueObserver` | настройки очереди и read-only область |
| `servicedesk.Ticket`/новая модель | `TicketRating` с циклом, токеном-хешем, сроком, снимками и `is_current` | оценка не меняет SLA-цикл и сохраняет историю |
| `tasks.Task` | nullable indexed `ticket_number`, без FK; миграция `tasks 0002` после `servicedesk 0005` | слабая связь между выключаемыми приложениями |
| `access`, список, поиск, `get_for`, `public.briefs` | использовать `can_view`; мутации и `_guard` использовать `can_work` | наблюдатель читает полную карточку, но не действует |
| `notify_kinds.py` | новых кодов не добавлять; расширить существующие уведомления новыми режимами получателей | FR-768, NFR-739 и идемпотентность |
| `reports.py` | заполнять «Оценка заявителей» средним по текущим оценкам и числом, Excel | продолжение отчёта 011, снимки не дают истории «плыть» |
| `extensions.py`, шаблоны | пункт настройки очередей/наблюдателей и части карточки «Задачи»/«Оценка» | навигация и серверная композиция |

Порядок миграций: сначала `core 0017` от `0016`; затем `servicedesk 0005` от
`servicedesk 0004` (она уже зависит от `core 0016`, `org 0002` и `servicedesk 0003`); затем
`tasks 0002` от `tasks 0001` (без зависимости на модель `servicedesk`, поскольку номер связи не FK).
Существующие начальные выдачи `core 0013` и `0016`, а также `servicedesk 0003` не изменяются.

## Модель данных, ограничения и индексы

### Недоступность сотрудника

Поле живёт в `core.User`: недоступность — атрибут человека, ставится из профиля и может быть
проверена всеми модулями; размещение в `org` связало бы общий атрибут с конкретным организационным
расширением. `unavailable_until` — дата включительно; `unavailable_note` допускает пустое значение,
`unavailable_by` — SET_NULL, `unavailable_at` — время. Доступность вычисляется как
`unavailable_until >= localdate`; после даты сотрудник снова доступен без задания. Изменение
разрешено самому сотруднику, администратору и руководителю узла его членства; проверку руководителя
выполняет служба `org` (ядро не импортирует `org`), изменение пишется в аудит.
Открытые заявки недоступного возвращаются в очередь, ручное назначение ему разрешено.

### Очередь и наблюдатели

`QueueRule(queue OneToOne, mode, last_assignee SET_NULL, updated_by SET_NULL, created_at, updated_at)`;
режим по умолчанию `off`. `QueueObserver(queue, user, added_by SET_NULL, added_at, removed_at)` хранит
историю снятия; активная уникальность `(queue,user)` не допускает дублей. Наблюдатель не считается
участником, кандидатом, ответственным или счётчиком. Владелец `servicedesk.manage` либо руководитель
очереди (узел очереди в `structure.managed_units(user)`) меняет правило и список.

Для `evenly` индекс/выборка опирается на `Ticket(queue, kind)` и считает только `new`,
`in_progress`, `waiting`; tie-break — `full_name`, `id`. Для `strictly` постоянный порядок —
ФИО и id, указатель `last_assignee`; выбывшие и недоступные пропускаются. `all` оставляет
ответственного пустым и уведомляет кандидатов и наблюдателей.

### Оценка

`TicketRating(ticket CASCADE, cycle_number, closed_at_snapshot, token_hash, score 1..5,
expires_at, is_current, created_at, updated_at, rated_at, queue_id, queue_name, category_id,
category_name, assignee_id, assignee_name, level_id, level_title)`. `cycle_number` — номер
закрытия заявки (1, 2, …); уникальность `(ticket, cycle_number)`, уникальность `token_hash` и
частичная уникальность текущей оценки обеспечивают одну текущую оценку на цикл; индекс
`(expires_at,is_current)` и `(queue_id,closed_at_snapshot)` поддерживают отчёт и фильтры. В хеше
нет исходного кода. Код — 12 знаков Crockford base32, генерируется криптографически; при
столкновении `token_hash` вставка повторяется (не больше трёх попыток), код не журналируется.
При reopen текущая оценка становится неактуальной, поставленная остаётся историей; следующее
ручное закрытие создаёт новый цикл.

### Связь задач

`Task.ticket_number` nullable, положительный integer, индекс `(ticket_number,deleted_at)`;
FK и каскада нет. Несколько задач могут иметь один номер заявки. Обратная связь запрашивает
`servicedesk.public.ticket_brief` только после `can_view`; мягко удалённые задачи отфильтровываются.

## Маршруты и контракты

| Маршрут | Право и результат |
|---|---|
| `GET /servicedesk/queues/` | видимые очереди; настройка доступна `servicedesk.manage`/руководителю |
| `GET/POST /servicedesk/queues/<id>/rule/` | режим `off/evenly/strictly/all`, журнал и HTMX/обычный ответ |
| `GET/POST /servicedesk/queues/<id>/observers/` | добавить/снять сотрудника, активный список и журнал |
| `GET /rate/?ticket=N` | открытая форма номера заявки без темы и кода в URL |
| `POST /rate/?ticket=N` | код и балл; CSRF, 5 ошибок за 15 минут на адрес+заявку, короткая сессия |
| `GET/POST /tasks/new/?ticket=N` | участник очереди с `tasks.use`; предзаполненная форма, `tasks.assign` обходится только для ответственного заявки |
| `GET /tickets/<number>/` | полный просмотр для `can_view`; наблюдателю скрыты все мутации и кнопка задачи |
| `GET /servicedesk/reports/` и `/export/` | существующее право отчёта; среднее с одним знаком и число, «—» без оценок; Excel с теми же фильтрами |

Все отказа мутаций используют существующий безопасный ответ «нет доступа»/403; открытая
страница оценки не раскрывает персональные данные и не сообщает, правильный ли код до успешной
проверки. `public.briefs` возвращает только видимые заявки, а задачи получают актуальные
тему/статус при открытии, не снимок.

## Службы и порядок вызовов

`distribution.py` — единственная точка автораспределения. При создании порядок:
`take_by` → ответственный категории → ответственный SLA → `distribution.assign_or_notify`.
Недоступные, уволенные и отсутствующие в `structure.queue_people` исключаются; наблюдатели
исключаются всегда. При `all` уведомление создаётся один раз, а первый `take` под блокировкой
становится ответственным. Для `evenly` и `strictly` транзакция блокирует `QueueRule` и очередь
через `select_for_update`; повторный вызов идемпотентен по состоянию и событию.

Возврат в очередь вызывается после ручного снятия, `reconcile`, изменения доступности,
передачи или смены категории без ответственного. Закрытые заявки не распределяются. После
изменения очереди/категории сначала сохраняется новая очередь, затем вызывается распределение.
Один переход пишет одно событие причины `manual`, `reconcile`, `unavailable`, `transfer`,
`category` и одну запись аудита.

`access.can_view` объединяет держателя `servicedesk.all`, узлы работы, ответственного и активного
наблюдателя; `can_work` сохраняет рабочую область и ответственного, но не наблюдателя. `visible_tickets`,
`menu_visible`, `get_for`, `listing`, поиск и `public.briefs` используют `can_view`; `take`,
`assign`, `reply`, `comment`, `close`, `transfer`, изменение полей и массовые действия — `can_work`.
Это правило применяется и к уведомлениям: «новая заявка в моей очереди» (включая уже назначенные)
и «просрочена» получают все `can_view` наблюдатели, остальные события — прежние рабочие получатели.

`rating.py` вызывается из ручного `closing.close` только если в текущем цикле есть фактический
ответ исполнителя; `autoclose_one` его не вызывает. `reopen` гасит текущую ссылку. Письмо
рендерит номер и ссылку отдельно от кода; rate limit и сессия не записывают код в журнал.

`services/task_links.py` создаёт задачу из видимой заявки. Предзаполнение и проверка идут через
`servicedesk.public.task_seed(actor, number)` (только `can_work`): тема, ссылка, последнее сообщение
заявителя, активный ответственный. Затем вызывается новая узкая служба задач
`apps.tasks.services.task_links.create_from_ticket(actor, number, ...)`, которая проверяет
seed ещё раз и вызывает `apps.tasks.services.tasks.create(..., assignee_authorized=True)`.
`task_seed` требует **`can_work`** заявки, а не только `can_view`: наблюдатель, не участник очереди и
сотрудник без `tasks.use` получают отказ ещё в публичной службе; `tasks.services.task_links`
дополнительно проверяет `tasks.use`. Флаг `assignee_authorized` — внутренний параметр службы задач:
он разрешает назначить **только** активного ответственного этой заявки; любой другой исполнитель идёт
через обычный `access.can_set_task`/`tasks.assign`. Представление `/tasks/new/?ticket=N` не вызывает
`create` напрямую и не обходит проверки. В карточку заявки добавляется блок только для видимых не удалённых
задач; в карточке задачи блок заявки появляется только при `can_view`. Новых событий или обратного
создания заявки нет.

## Шаблоны и интерфейс

Настройка очереди — отдельная страница/форма на очередь со ссылками из `/servicedesk/queues/`,
режимом, активными наблюдателями и действиями только для управляющего. Карточка наблюдателя
полная: переписка, заявитель, вложения, оценка; кнопки взять, назначить, ответить, закрыть,
изменить поля и «Поставить задачу» отсутствуют, прямые POST отклоняются.

В карточке участника с `tasks.use` показывается «Поставить задачу», блок задач содержит номер,
название и статус. На странице задачи блок «Заявка» содержит номер, тему и статус. Страница
оценки показывает только номер, выбор 1–5, поле кода и общее состояние успеха/истечения.
Все строки по-русски, время — Europe/Moscow; сетки очереди, карточки, формы и отчёта не создают
горизонтальную прокрутку страницы на 360 px.

## Уведомления

Новые виды не вводятся. Расширяются существующие виды «новая заявка» и «просрочена»: их
получатели-наблюдатели вычисляются режимом `can_view`; письмо закрытия остаётся письмом заявителю,
отдельно от уведомлений портала. Для `all` кандидаты и
наблюдатели получают одну запись на заявку/получателя/срок; ручной `take` не создаёт второе
уведомление. Закрытие с правом оценки ставит письмо с номером и ссылкой `/rate/?ticket=N`,
код находится только в тексте письма. Повторные задания используют уникальности и не создают
вторые записи или письма.

## Отчёт

`reports.build` сохраняет область `managed_units` и существующие фильтры, добавляя агрегат
`Avg(score)` и `Count` по `TicketRating(is_current=True, closed_at_snapshot в периоде)`; округление —
один знак после запятой, при нуле — «—». Фильтры очереди, уровня, категории и исполнителя используют
снимки оценки (`queue_id`, `level_id`, `category_id`, `assignee_id`), чтобы последующая передача не
меняла историю. Excel получает тот же показатель
и число на листе «Показатели»; персональные данные, тема и переписка в выгрузку не попадают.

## Стенд

`servicedesk/stand.py` удаляет **только свои** новые модели (`TicketRating`, `QueueObserver`,
`QueueRule`) и чистит rate-limit/короткие сессии оценки. Задачи и `Task.ticket_number` очищает
`tasks/stand.py` (его `stand_reset` уже удаляет `Task`), а `core.User`-недоступность снимается общим
`e2e_reset_stand` при очистке `core_*`; `servicedesk` чужие таблицы не трогает. Общий порядок —
`e2e_reset_stand` → зарегистрированные `stand_reset` (servicedesk, затем tasks, как в extensions).
E2E-seed создаёт участников очередей, все четыре режима, наблюдателя, недоступного сотрудника,
заявку для оценки и задачу из заявки; данные синтетические, без ПДн. Распределение вызывается
сразу при создании/возврате, cron и фоновая проверка даты недоступности не добавляются.

## Трассировка требований

Каждое требование SPEC-012 имеет место реализации и конкретный тест; E2E-сценарии — `backend/tests/e2e/test_t12_01…07.py`.

| Требование | Реализация | Серверный тест | E2E |
|---|---|---|---|
| FR-759 | `QueueRule`, `views/settings.py`, `audit_labels.py` | `test_sd_012_distribution.py::test_rule_change_and_audit` | `test_t12_01` |
| FR-760 | `distribution.assign_or_notify`, вызов в `tickets.create` | `test_sd_012_distribution.py::test_create_priority` | `test_t12_01` |
| FR-761 | `distribution.choose_evenly` | `test_sd_012_distribution.py::test_evenly` | `test_t12_01` |
| FR-762 | `distribution.choose_strictly`, указатель `QueueRule.last_assignee` | `test_sd_012_distribution.py::test_strictly` | `test_t12_01` |
| FR-763 | `distribution.assign_or_notify` (all), `notify_kinds` | `test_sd_012_distribution.py::test_all_notify`, `test_sd_012_notify_audit.py::test_all` | `test_t12_01` |
| FR-764 | `distribution.return_ticket`, вызовы из `assignment`, `reconcile`, `transfer`, `tickets` | `test_sd_012_distribution.py::test_return_paths` | `test_t12_03` |
| FR-765 | `core.User.unavailable_*`, `core/services/accounts.set_availability`, `org/services/availability`, `distribution`, `views/me.py`, `views/staff_actions.py`, `org/views/members.py` | `test_sd_012_access.py::test_unavailable`, `test_sd_012_distribution.py::test_unavailable_skipped` | `test_t12_03` |
| FR-766 | `QueueObserver`, `views/settings.py`, `audit_labels.py` | `test_sd_012_access.py::test_observer_manage` | `test_t12_02` |
| FR-767 | `access.can_view`, `can_work`, `visible_tickets`, `menu_visible`, `views/ticket_card.py` | `test_sd_012_access.py::test_observer_readonly` | `test_t12_02` |
| FR-768 | `notify_kinds._new_in_queue`, `_sla`, `_drafts` | `test_sd_012_notify_audit.py::test_observer_notify` | `test_t12_02` |
| FR-769 | `closing.close`, `rating.create_link`, `letters` | `test_sd_012_rating.py::test_manual_close_sends` | `test_t12_04` |
| FR-770 | `rating.verify_code`, `views/rating.py`, `templates/servicedesk/rating/` | `test_sd_012_rating.py::test_code_post`, `test_rate_limit`, `test_expired` | `test_t12_04` |
| FR-771 | `rating.on_reopen`, `TicketRating.is_current` | `test_sd_012_rating.py::test_reopen` | `test_t12_04` |
| FR-772 | `reports.build`, `reports.export_xlsx`, `templates/servicedesk/reports/` | `test_sd_012_reports.py::test_rating_average`, `test_sd_012_reports.py::test_excel` | `test_t12_04` |
| FR-773 | `views/ticket_card.py`, `services/task_links.py`, `tasks/services/task_links.py`, `tasks/views/pages.py`, `task_seed` с `can_work` | `test_sd_012_tasks.py::test_button_and_rights`, `test_direct_service_rejects_observer` | `test_t12_05` |
| FR-774 | `services/task_links.py`, `tasks/services/task_links.py`, шаблон формы | `test_sd_012_tasks.py::test_prefill` | `test_t12_05` |
| FR-775 | `tasks/services/tasks.create(assignee_authorized=…)`, `task_links` | `test_sd_012_tasks.py::test_assignee_exception` | `test_t12_05` |
| FR-776 | `Task.ticket_number`, публичные справки, части карточек | `test_sd_012_tasks.py::test_both_sides`, `test_soft_delete` | `test_t12_05` |
| FR-777 | `tasks.services.access.visible`, `servicedesk.public.briefs` | `test_sd_012_tasks.py::test_visibility`, `test_sd_012_access.py::test_observer_no_task` | `test_t12_05` |
| FR-778 | отсутствие обратного создания и синхронизации | `test_sd_012_tasks.py::test_no_reverse_sync` | `test_t12_05` |
| FR-779 | `audit_labels.py`, службы среза | `test_sd_012_notify_audit.py::test_audit_events` | `test_t12_06` |
| FR-780 | отсутствие новых глобальных прав, проверки `managed_units` | `test_sd_012_access.py::test_queue_head_scope`, `test_sd_012_stand.py` | `test_t12_06` |
| FR-781 | шаблоны очереди, карточки, настроек и оценки | — (визуальное требование) | `test_t12_07` |
| FR-782 | тексты и `Europe/Moscow` в шаблонах и письмах | `test_sd_012_notify_audit.py::test_texts_moscow` | `test_t12_07` |
| NFR-736 | `distribution` с `select_for_update`, атомарные вставки | `test_sd_012_concurrency.py::test_parallel_create`, `test_parallel_take` | — |
| NFR-737 | выборки `visible_tickets`, `listing`, карточка, блок задач | `test_sd_012_performance.py::test_queue_card_p95` | — |
| NFR-738 | `views/rating.py`, rate limit, короткая сессия | `test_sd_012_performance.py::test_rating_page`, `test_sd_012_rating.py::test_rate_limit` | `test_t12_04` |
| NFR-739 | `notify_kinds`, уникальности уведомлений | `test_sd_012_notify_audit.py::test_idempotent_new_overdue_rating` (три вида, ключ заявка+получатель+срок, повтор до/во время/после) | `test_t12_02` |
| NFR-740 | публичные справки связи при каждом чтении | `test_sd_012_tasks.py::test_fresh_status`, `test_soft_delete` | `test_t12_05` |

## Тесты

| Набор | Покрытие (требования) |
|---|---|
| `test_sd_012_models.py` | ограничения правил, наблюдателей, недоступности, рейтинга, хеша, срока и `ticket_number` — FR-759, FR-765, FR-766, FR-771, FR-776 |
| `test_sd_012_access.py` | `can_view/can_work`, observer read-only, меню, список, поиск, `get_for`, briefs, 403 мутаций — FR-765…768, FR-777, FR-780 |
| `test_sd_012_distribution.py` | приоритеты создания, evenly/strictly/all, кандидаты, возвраты, причины, отсутствие дублей — FR-759…765, NFR-736 |
| `test_sd_012_rating.py` | manual/autoclose, ответ в цикле, POST, CSRF, rate limit, 7 дней, reopen, история и коллизия `token_hash` — FR-769…771, NFR-738 |
| `test_sd_012_tasks.py` | предзаполнение, исключение `tasks.assign` только для ответственного заявки, отказ другому, обе стороны связи, видимость, soft delete и свежесть статуса — FR-773…778, NFR-740 |
| `test_sd_012_notify_audit.py` | наблюдательские уведомления, идемпотентность новой заявки/просрочки/оценки с ключом (заявка, получатель, срок), все новые записи журнала и русский текст — FR-763, FR-768, FR-779, FR-782, NFR-739 |
| `test_sd_012_reports.py` | среднее/число, «—», снимки, область, фильтры и Excel — FR-772 |
| `test_sd_012_concurrency.py` | NFR-736: параллельные create/take для evenly и strictly, один ответственный/событие |
| `test_sd_012_performance.py` | NFR-737/738: p95 500 мс, 100 сотрудников/110 тыс. заявок и 50 заявителей |
| `test_t12_01`…`test_t12_07` | очередь и режимы; наблюдатель; недоступность; оценка; задача; права/журнал; 360 px и Москва |

Правки прежних тестов требуют отдельного разрешения владельца:

| Файл/область | Было | Станет | Почему |
|---|---|---|---|
| `test_sd_access.py`, `test_sd_boundaries.py` | `visible_tickets` и `can_work` совпадают; наблюдатель отсутствует | отдельные `can_view/can_work`, наблюдатель только читает; старые ожидания прав доступа обновлены | FR-766…768 |
| `test_sd_boundaries.py`, `test_notify_catalog.py`, `test_notify_prefs.py` | каталог и получатели покрывают прежние виды/рабочих получателей | те же виды получают режим `can_view`; количество видов не увеличивается | FR-768, NFR-739 |
| `test_sd_audit.py` | точный набор старых событий и полей | плюс `queue.rule_changed`, observer, unavailable, distribution, rating, task link | FR-779 |
| `test_sd_reports.py`, `test_sd_reports_excel.py` | «Оценка заявителей» пуста | один знак, число оценок, «—» без оценок | FR-772 |
| `test_sd_stand_restore.py`, deploy/меню tests | нет новых таблиц/частей карточки/маршрута | сброс и контракты включают `0005/0017/0002`, меню и seed | стенд и миграции |
| `test_tasks_*.py` | у `Task` нет номера заявки | поле nullable/indexed и блок заявки с правами | FR-773…777 |

До разрешения владельца эти правки не переписываются и не маскируются ослаблением тестов.

## Этапы и партии

1. **Каркас и контракты:** миграции `core 0017`, `servicedesk 0005`, `tasks 0002`, модели,
   `can_view/can_work`, маршруты-заглушки, части карточки, audit labels, seed/reset и тестовые
   помощники. Сначала проверить схему и миграции.
2. **Красные тесты:** ограничения и доступ; распределение и конкуренция; rating и публичная
   страница; связь tasks; уведомления, аудит, отчёт; e2e и нагрузочный профиль.
3. **Реализация партиями:** (а) доступ/наблюдатель; (б) недоступность/распределение; (в) оценка
   и письмо; (г) задачи и публичные контракты; (д) уведомления/аудит/отчёт; (е) шаблоны,
   меню, стенд и 360 px. Общие файлы имеют одного автора за партию.
4. **Проверка:** полный серверный набор после каждой партии, затем `manage.py check`,
   `tools/verify.sh --быстро`, `git diff --check`, браузерные круги и NFR-профили.
   Подпись плана, задачи и правки прежних тестов остаются за владельцем.

## Риски и открытые вопросы

Риск гонки в `evenly/strictly` снижается блокировкой правила и очереди, повторной проверкой
состояния и уникальным аудитом. Риск расширения видимости наблюдателю снижается единым
`can_view` и запретом его использования в мутациях. Риск утечки кода оценки снижается хешем,
POST, CSRF, короткой сессией, rate limit и отсутствием кода в URL/журнале. Риск исторического
дрейфа отчёта снижается снимками очереди, категории, исполнителя и уровня и фильтрацией
`is_current`. Риск циклического импорта `servicedesk`/`tasks` снижается сервисными контрактами
и отсутствием FK. Риск регрессии высок: меняется базовая семантика видимости и каталог
ожиданий; поэтому прежние тесты перечислены отдельно и требуют разрешения владельца.

Открытых вопросов владельцу нет: режимы, права, получатели, шкала и срок оценки, слабая связь,
миграции и отсутствие cron заданы SPEC-012 и ADR-0021. Детали реализации закреплены ниже.

## Решения плана

1. Недоступность хранится в `core.User`, а не в `org`: это атрибут сотрудника, нужен профилю,
   ядру и распределителю, имеет единую дату окончания и не дублируется по очередям.
2. Для правила используется отдельная `QueueRule`, а не поля `Queue`: one-to-one отделяет
   изменяемую настройку и блокировку распределения от идентичности отметки очереди, при этом
   режим `off` существует явно и стабильно блокируется.
3. Наблюдатели хранятся с `removed_at`, чтобы аудит и история были неизменяемыми; активная
   уникальность не допускает повторного получателя.
4. Оценка связана с номером SLA-цикла и снимками, но не FK на цикл: рейтинг остаётся
   независимым от очистки/архивирования SLA и сохраняет отчётную историю.
5. Связь задачи хранится только `ticket_number`, как у существующих межмодульных ссылок:
   приложения можно выключать независимо, а актуальность и права проверяются при каждом чтении.
6. Автораспределение вызывается синхронно в общей транзакции создания/возврата; cron не нужен,
   потому что SPEC-012 не вводит таймер рабочего присутствия или автоматический переход по дате.
