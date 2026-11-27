---
id: PLAN-014
вид: план
статус: утверждён
версия: 2
зависит_от: SPEC-014, CONST, ADR-0002, ADR-0004, ADR-0009, ADR-0018, ADR-0020, ADR-0022, REF-CAP, REF-UX, REF-SRC, TGT-ARCH, TGT-NFR, SPEC-002, SPEC-003, SPEC-004, SPEC-009, SPEC-013
основан_на: SPEC-014 sha256:f8881c12200cd3637fcf85dbb844caa5c217374a87189b8bb57f7d2f877dfad6
подпись: Максим | 2026-11-27T15:16+03:00 | sha256:4ef6cf1db5437cbe8c878972b7c2d57de29d8843709f5d4aa1e39812944eaee2
подпись: Максим | 2026-11-27T15:17+03:00 | sha256:4ef6cf1db5437cbe8c878972b7c2d57de29d8843709f5d4aa1e39812944eaee2
---

# План среза 014: Согласования

## Сверка с конституцией

- **модуль-приложение.** Новое приложение `approvals`; заявки, задачи, автоматика и уведомления не импортируются
  им напрямую — только через точки расширения и публичные службы. `servicedesk` и `tasks` регистрируют адаптеры
  субъекта, `automation` предоставляет реестр действий и шину событий.
- **настройка-без-кода.** Шаблоны, этапы, режимы, правила, сроки и участники — данные; новых констант процесса
  в коде нет. Начальных шаблонов нет, администратор создаёт их в интерфейсе.
- **права и минимум доступа.** Новых глобальных прав нет: шаблоны и отмена администратором — `automation.manage`,
  запуск — `can_work` субъекта, решение — только назначенный участник. Участник видит краткую справку, не полную
  карточку заявителя.
- **аудит-изменений.** `ApprovalEvent` — только дописываемые строки; изменения шаблона, запуск, этапы, решения,
  возврат и отмена пишутся в `core.audit.record`; системные записи — с пустым автором.
- **пдн-152фз.** В журнал, события, шаблоны и уведомления не попадают тема, ФИО, адрес, текст переписки и
  комментарий решения; только номер, статус, очередь, ответственный и ссылка.
- **секреты-в-url.** Новых секретов и адресов с секретами нет; одноразовые ссылки не вводятся.
- **sql-только-параметры.** Все выборки — ORM; поля сортировки и фильтры — из белого списка; сырого SQL нет.
- **стек-интерфейс и бэкенд.** Django 5.2, PostgreSQL 17, HTMX, Alpine.js, RQ; новых пакетов нет. Минутное
  задание — `rq cron`.
- **тест-на-требование.** Каждый FR-820…850 и NFR-746…749 получает серверный, браузерный или нагрузочный тест;
  трассировка — в SPEC-014 и разделе «Трассировка требований» ниже.
- **эталон-не-копия.** Берём поведение этапа, задания и истории, но не вёрстку, тексты и названия эталона.

## Технический контекст

- Заявка: номер, тема, статус, очередь, ответственный, `kind` статуса и признак закрытия
  (`backend/apps/servicedesk/models.py`). Видимость и работа — `servicedesk.services.access.can_view` /
  `can_work`; состав руководителей очереди для этапа — `org.services.structure.heads_of_unit`, а
  `servicedesk.services.queues.can_manage` остаётся правом настройки правил и участников не разрешает.
- Задача: `Task` с четырьмя статусами, `deleted_at`, автором и исполнителем
  (`backend/apps/tasks/models.py`); видимость — `tasks.services.access.visible`, работа —
  `can_change_status`; удалённая задача не видна. Карточка задачи собирается в трёх местах
  (`tasks/views/pages.py`, `actions.py`, `comments.py`), поэтому общий контекст карточки выносится в службу.
- Шина событий — `core.events.publish`: обработчики вызываются после фиксации транзакции, ошибка обработчика не
  откатывает действие (`backend/apps/core/events.py`). Точки расширения — статический `POINTS`
  (`backend/apps/core/extensions.py`).
- Автоматика 013: реестр действий `automation.extensions.Action` и `automation.services.actions`, проверка
  `automation.services.validation.ACTION_SCHEMAS`, подписки `automation.subscriptions`, триггеры субъектов в
  `servicedesk/automation.py` и `tasks/automation.py`. Сейчас реестр действий закрыт статическим словарём —
  T-14002 открывает его для `start_approval`.
- Уведомления — `notify.services.dispatch.create` и каталог `notification_kinds`
  (`backend/apps/notify/services/kinds.py`); журнал — `core.services.audit.record`; минутные задания — `rq cron`
  (`backend/config/cron.py`, образец `automation_tick`).
- Карточка заявки уже принимает части точки `ticket_card_parts` (`servicedesk/views/ticket_card.py`); у задачи
  такой точки нет — T-14002 добавляет `task_card_parts` аддитивно.
- Стенд среза 013, `E2E_STAND=1` в `standtools`; сброс — только по решению владельца. E2E-сценарии создают свои
  шаблоны и убирают их после.

## Новые компоненты и лицензии

Новых пакетов и лицензий нет. HTMX, Alpine.js, Bootstrap и SortableJS уже в проекте; отдельных графиков и
внешних сервисов срез не требует.

## Где живёт код

```text
backend/apps/approvals/apps.py                   приложение, регистрации, точка сброса стенда
backend/apps/approvals/models.py                 шаблон, этап, участник, маршрут, этап-экземпляр, задание,
                                                 маркер уведомления, событие
backend/apps/approvals/migrations/0001_initial.py
backend/apps/approvals/extensions.py             ApprovalSubject, регистрации approval_subjects/task_card_parts
backend/apps/approvals/services/templates.py     проверка и сохранение шаблона
backend/apps/approvals/services/routes.py        запуск, снимок, решения, отмена
backend/apps/approvals/services/stages.py       переходы этапов, sequential/parallel, выбытие
backend/apps/approvals/services/queue.py         «Мои задания», просрочка, выборка заданий
backend/apps/approvals/services/access.py        видимость маршрута, право решения, права шаблонов
backend/apps/approvals/services/journal.py       коды журнала без ПДн
backend/apps/approvals/services/notices.py       маркеры напоминаний и уведомлений
backend/apps/approvals/services/events.py        публикация шести событий
backend/apps/approvals/subscriptions.py          подписки автоматики на события согласований
backend/apps/approvals/action.py                 действие `start_approval` для реестра 013
backend/apps/approvals/notify_kinds.py           пять видов уведомлений
backend/apps/approvals/audit_labels.py
backend/apps/approvals/tasks.py                  approvals_tick
backend/apps/approvals/forms.py, views/, urls.py, templates/approvals/
backend/static/approvals/                      стили страниц и блока (образ nginx пересобирается)
backend/apps/approvals/stand.py
backend/apps/core/extensions.py                  POINTS: approval_subjects, task_card_parts; TaskRef, TaskCardPart
backend/apps/servicedesk/approval.py             адаптер заявки для согласований
backend/apps/servicedesk/extensions.py           регистрация approval_subjects
backend/apps/tasks/approval.py                   адаптер задачи для согласований
backend/apps/tasks/extensions.py                 регистрация approval_subjects
backend/apps/tasks/services/card.py              общий контекст карточки и части task_card_parts
backend/apps/tasks/views/pages.py, actions.py, comments.py  использование общего контекста
backend/templates/tasks/_card.html               раздел «Согласования»
backend/apps/automation/services/validation.py   динамические схемы действий и шесть триггеров
backend/apps/automation/services/actions/__init__.py  объединение статических и зарегистрированных обработчиков
backend/apps/automation/forms.py                 действия и события из реестра, подписи шести триггеров
backend/config/settings.py                       приложение approvals
backend/config/urls.py                           /approvals/…
backend/config/cron.py                           approvals_tick раз в минуту
backend/tests/test_approvals_*.py, test_notify_catalog.py
backend/tests/e2e/test_t14_*.py
backend/tests/CONTRACT-014.md
```

## Изменения ядра и прежних модулей

| Область | Изменение | Причина |
|---|---|---|
| `core.extensions.POINTS` | добавить `approval_subjects`, `task_card_parts` | адаптеры субъекта и блок в карточке задачи без импорта `approvals` |
| `core.extensions` | добавить `TaskRef` и `TaskCardPart` по образцу `TicketRef`/`TicketCardPart` | контракт части карточки задачи |
| `org.services.structure` | публичная `unit_heads(unit_id)`: руководитель и заместители **только этого** узла | `unit_head` не должен захватывать предков, как `heads_of_unit` |
| `servicedesk.approval` + `servicedesk/extensions.py` | адаптер заявки: загрузка, блокировка, краткая справка, `can_view`/`can_work`, ссылка | `approvals` не импортирует модель заявки |
| `tasks.approval` + `tasks/extensions.py` | адаптер задачи: те же поля, `deleted_at` и `status=done` как закрытый субъект | `approvals` не импортирует модель задачи |
| `tasks/services/card.py` + три вида карточки | общий контекст и `task_card_parts` | блок «Согласования» в карточке задачи |
| `automation.services.validation` | схемы действий берутся из зарегистрированных `Action`, а не только из `ACTION_SCHEMAS`; шесть триггеров `approval_*` для `ticket`/`task` | открытый реестр и правила на события 014 |
| `automation.services.actions` | `_handlers` дополняется обработчиками зарегистрированных действий | `start_approval` без импорта `approvals` из `automation` |
| `automation/forms.py` | список действий и событий строится из реестра; шесть русских подписей триггеров | форма правила предлагает `start_approval` и события согласования |
| `servicedesk/automation.py`, `tasks/automation.py` | шесть кодов триггеров в `TRIGGERS` | форма правила предлагает события согласования |
| `config/settings.py`, `config/urls.py`, `config/cron.py` | приложение, маршруты, минутное задание | включение среза |
| `notify` каталог | пять видов `approvals.*` через точку расширения | уведомления задания и срока |

Миграций `core`, `servicedesk`, `tasks` и `automation` нет: новых прав и полей у прежних моделей не появляется.
Порядок миграций: `approvals 0001` после `core 0018` и `automation 0001` (срез 013).

## Модель данных, ограничения и индексы

| Модель | Поля | Ограничения и индексы |
|---|---|---|
| `ApprovalTemplate` | name 150, subject_type, description 2000, enabled, author FK PROTECT, created_at, updated_at | check subject_type `ticket`/`task`; index `(subject_type, enabled)` |
| `ApprovalStage` | template FK CASCADE, order, title 100, mode `sequential`/`parallel`, rule `all`/`any`, deadline_hours null | unique `(template, order)`; check deadline 1…720; check `sequential` ⇒ `rule='all'`; check order 1…20 |
| `ApprovalStageParticipant` | stage FK CASCADE, order, kind `employee`/`unit_head`/`queue_head`, user FK PROTECT null, unit FK PROTECT null | check поля по виду; partial unique `(stage, user)` при `kind='employee'`, `(stage, unit)` при `kind in ('unit_head','queue_head')`; index `(stage, order)` |
| `ApprovalRoute` | template FK PROTECT, template_name 150, subject_type, subject_id positive, subject_number positive, initiator FK PROTECT, status `running`/`approved`/`rejected`/`returned`/`cancelled`, started_at, finished_at null, cancelled_by FK SET_NULL null | partial unique `(subject_type, subject_id)` при `status='running'`; index `(subject_type, subject_id, started_at)`, `(subject_type, subject_number, started_at)`, `(status, finished_at)` |
| `ApprovalStageRun` | route FK CASCADE, order, title, mode, rule, deadline_hours null, status `waiting`/`running`/`done`/`cancelled`, started_at null, finished_at null, due_at null | unique `(route, order)`; index `(route, status)` |
| `ApprovalAssignment` | stage_run FK CASCADE, user FK PROTECT, order, status `pending`/`approved`/`rejected`/`returned`/`cancelled`, decision `approved`/`rejected`/`returned` null, comment text 4000 blank, created_at, due_at null, decided_at null | unique `(stage_run, user)`; check `pending` ⇒ `decision IS NULL`; check `approved/rejected/returned` ⇒ `decision` совпадает со `status` и `decided_at` заполнен; check `cancelled` ⇒ `decision IS NULL`; index `(user, status, due_at)`, `(stage_run, status)` |
| `ApprovalNotice` | assignment FK CASCADE, kind `reminder`/`overdue`, sent_at | unique `(assignment, kind)`; index `(kind, sent_at)` |
| `ApprovalEvent` | route FK CASCADE, kind (`started`/`stage_completed`/`decision`/`rejected`/`returned`/`cancelled`/`assignment_cancelled`), actor FK SET_NULL null, data JSON, at | только дописывается; index `(route, at)`, `(kind, at)` |

Снимок хранит разрешённых сотрудников в `ApprovalAssignment`, а параметры этапа — в `ApprovalStageRun`;
`ApprovalRoute.template` нужен только для истории и защищён `PROTECT`. Шаблон не удаляется, только выключается.
Задания одного этапа имеют общий `due_at`; последовательный этап создаёт следующее задание с тем же сроком.

## Валидация шаблона

`approvals.services.templates.validate` — единственная проверка перед сохранением и повторная — при запуске:

- название 1…150, описание до 2 000, субъект `ticket`/`task`;
- этапов 1…20, порядок 1…N без пропусков и дублей, название 1…100;
- режим и правило из допустимых; у `sequential` правило только `all`, иначе ошибка «для последовательного
  этапа доступно только „ждут всех“»;
- срок — `null` или целое 1…720;
- у этапа 1…50 участников; `employee` — активный сотрудник (уволенный, приглашённый и заблокированный
  отклоняются); `unit_head` — существующее подразделение, состав — руководитель и заместители только этого узла;
  `queue_head` — только для субъекта «заявка», состав — `structure.heads_of_unit` очереди;
- дубль участника в этапе отклоняется; сотрудник, совпавший после разрешения руководителей, схлопывается в одно
  задание при запуске, а не при сохранении;
- выключенный шаблон сохраняется, но форма и служба запуска его не предлагают.

## Маршруты и контракты

| Маршрут | Метод | Что делает | Права |
|---|---|---|---|
| `/approvals/` | GET | список шаблонов по субъектам | `automation.manage` |
| `/approvals/templates/new/` | GET/POST | создание шаблона | `automation.manage` |
| `/approvals/templates/<id>/edit/` | GET/POST | правка шаблона | `automation.manage` |
| `/approvals/templates/<id>/toggle/` | POST | включение/выключение | `automation.manage` |
| `/approvals/my/` | GET | «Мои задания», ожидающие и просроченные | вход |
| `/approvals/routes/<id>/` | GET | маршрут, этапы, история, форма решения | видимость маршрута |
| `/approvals/start/` | POST | запуск из карточки | `can_work` субъекта |
| `/approvals/routes/<id>/cancel/` | POST | отмена | инициатор или `automation.manage` |
| `/approvals/assignments/<id>/decide/` | POST | решение участника | назначенный участник |

Общие ответы ошибок: `no_access`, `template_invalid`, `template_absent`, `template_disabled`,
`subject_mismatch`, `subject_closed`, `route_exists`, `no_participants`, `assignment_forbidden`,
`assignment_cancelled`, `already_decided`, `route_finished`, `comment_required`, `author_inactive`. Коды и русские
тексты — в `CONTRACT-014`.

## Службы и порядок вызовов

1. **Запуск.** `routes.start(actor, subject, template)`:
   - адаптер субъекта загружает объект под `select_for_update` (заявка или задача) и проверяет
     существование, закрытость заявки, удалённость или `status=done` задачи и `can_work`;
   - шаблон проверяется заново; участники разрешаются (`employee`, `unit_head`, `queue_head`), неактивные
     исключаются, дубли схлопываются;
   - в одной транзакции создаются `ApprovalRoute`, `ApprovalStageRun`, `ApprovalAssignment`, событие
     `started` и журнал; событие публикуется после commit;
   - частичный уникальный индекс ловит второй запуск; служба возвращает `route_exists`, форма показывает
     сообщение, правило пишет пропуск.
2. **Решение.** `routes.decide(actor, assignment_id, decision, comment)`:
   - сначала блокируется маршрут, затем задание (`select_for_update`); ключ идемпотентности —
     `(assignment_id, actor_id, decision, comment.strip())`;
   - если задание уже решено или отменено, ключ сравнивается с сохранённым `decision` и комментарием: тот же
     ключ — `200` и сохранённый результат без новых записей (в том числе после завершения маршрута); другой —
     `409` `already_decided`; для отменённого задания — `409` `assignment_cancelled`; для незавершённого
     задания на завершённом маршруте — `route_finished`;
   - для `pending` проверяются `running` и актор; чужой — `forbidden`;
   - два одинаковых параллельных запроса дают одно решение; второй ждёт блокировку, видит тот же ключ и
     получает `200`; два разных — один `200`, второй `409`;
   - обновление задания, этапа и маршрута, отмена ненужных заданий, журнал, событие и уведомление — в одной
     транзакции; событие после commit;
   - `sequential`: следующее задание после «Согласовано»; `parallel/all`: этап закрыт, когда все оставшиеся
     задания согласованы; `parallel/any`: первое «Согласовано» закрывает этап и отменяет остальные;
   - «Отклонено» и «На доработку» завершают маршрут при любом правиле и отменяют остальные задания; события —
     `stage_completed` с `result` → `rejected`/`returned`, `completed` не публикуется.
3. **Отмена.** `routes.cancel(actor, route_id)`: блокировка маршрута, проверка инициатора или
   `automation.manage`, отмена ожидающих заданий, событие и журнал; повтор тем же актором идемпотентен,
   завершённый маршрут — `route_finished`.
4. **Сроки.** `notices.run_due(now)`: выборка ожидающих заданий, у которых `due_at <= now` или
   `due_at - 24h <= now`, порциями по 50, `select_for_update(skip_locked)`, уникальный маркер
   `(assignment, kind)` и уведомление в одной транзакции. Напоминание за 24 часа создаётся только при
   `due_at - 24h > created_at`; для срока короче 24 часов отдельного напоминания нет. После решения, отмены
   или выбытия — пропуск. `approvals_tick` вызывает `notices.run_due` и `routes.drop_inactive` раз в минуту.
5. **Выбытие.** `routes.drop_inactive`: сначала выбирает `route_id` ожидающих заданий уволенных и
   заблокированных без блокировки, затем блокирует маршруты по возрастанию `id`, после них — задания, и
   перепроверяет состояние. В `sequential` задание переходит следующему участнику по порядку; если следующих
   нет, этап завершается по уже полученным согласованиям при хотя бы одном согласовавшем. В `parallel/any`
   этап продолжает ждать остальных; в `parallel/all` этап завершается, когда все оставшиеся задания
   согласованы. Пустой этап без согласовавших даёт `cancelled` маршрута с причиной `no_participants`.
6. **События.** `events.publish(route, kind, actor, **data)` формирует `event_id`/`dedupe_key` по контракту
   SPEC-014 и вызывает `core.events.publish`; `approvals/subscriptions.py` передаёт их в
   `automation.services.rules.on_event` как триггеры `approval_*`.
7. **Действие правила.** `action.start_approval` получает `template`, загружает субъект и вызывает
   `routes.start` от имени автора правила; пропуски (`author_inactive`, `template_absent`, `template_disabled`,
   `subject_mismatch`, `subject_closed`, `route_exists`, `no_participants`) поднимают `ActionSkip` с причиной и
   пишутся в журнал действия автоматики.

Порядок блокировок единый: субъект → маршрут → задание. Запуск блокирует субъект, затем вставляет маршрут;
решение и отмена блокируют маршрут, затем задание; минутное задание сначала собирает `route_id` без блокировки,
затем блокирует маршруты по `id` и задания. Обратного порядка нет, поэтому взаимная блокировка с закрытием
заявки и минутным заданием исключена.

## Шаблоны и интерфейс

- `/approvals/` — таблица шаблонов: название, субъект, этапы, состояние, автор; кнопки «Создать», «Изменить»,
  «Выключить».
- Форма шаблона — название, субъект, описание, этапы с порядком, режимом, правилом, сроком и участниками;
  участник выбирается поиском сотрудника или подразделения; для заявки доступен «Руководитель очереди».
- `/approvals/my/` — карточки заданий: субъект, этап, срок, состояние; просроченные выделены, сортировка по
  сроку и номеру; пустое состояние.
- `/approvals/routes/<id>/` — шапка маршрута, этапы, задания, история; форма решения с комментарием; кнопка
  отмены у инициатора и администратора; наблюдателю кнопок нет.
- Карточка заявки — раздел «Согласования» через `ticket_card_parts`; карточка задачи — через
  `task_card_parts`. В блоке активный маршрут, этап, срок и кнопка запуска; после завершения — ссылка на
  историю.
- 360×640: страницы и формы без горизонтальной прокрутки страницы, широкие таблицы прокручиваются внутри
  блока; кнопки доступны с клавиатуры. Проверяются «Мои задания», маршрут, форма шаблона и карточка с блоком
  «Согласования». Стили — `backend/static/approvals/`; после правок CSS пересобирается
  образ `nginx`, иначе статика отдаётся старым слоем.

## Уведомления и журнал

- Виды уведомлений: `approvals.assignment` (250), `approvals.decision` (251), `approvals.returned` (252),
  `approvals.reminder` (253), `approvals.overdue` (254); каналы — настройки среза 004, внешний текст —
  только событие и ссылка.
- Получатели: `assignment` — назначенный участник; `decision` — инициатор; `returned` — инициатор;
  `reminder` и `overdue` — участник и инициатор. Один сотрудник получает одно уведомление вида на событие;
  заявитель без учётной записи и внешние адреса не используются.
- Тексты содержат номер субъекта, этап и ссылку; тема, ФИО, адрес, текст переписки и комментарий решения не
  подставляются.
- Журнал: `approvals.template_created`, `approvals.template_updated`, `approvals.template_enabled`,
  `approvals.template_disabled`, `approvals.route_started`, `approvals.stage_completed`,
  `approvals.decision`, `approvals.route_rejected`, `approvals.route_returned`, `approvals.route_cancelled`,
  `approvals.assignment_cancelled`; русские подписи — `audit_labels.py`.
- Журнал хранит идентификаторы, код решения и причину пропуска; комментарий не копируется. Системные записи —
  с пустым автором.

## Стенд

- `approvals/stand.py` очищает `ApprovalNotice`, `ApprovalEvent`, `ApprovalAssignment`,
  `ApprovalStageRun`, `ApprovalRoute`, `ApprovalStageParticipant`, `ApprovalStage`, `ApprovalTemplate`;
  регистрируется в общей точке сброса.
- E2E создают шаблоны и маршруты через форму и службу, после сценария убирают; сид примеров не нужен.
- Нагрузочный профиль: 110 000 заявок, 20 000 задач, 5 000 маршрутов (1 000 активных), 25 000 заданий
  (10 000 ожидающих), 300 шаблонов, 2 000 сотрудников; данные синтетические.

## Трассировка требований

| FR / NFR | Задачи |
|---|---|
| FR-820–822 | T-14003, T-14010, T-14013 |
| FR-823, FR-825–826 | T-14011, T-14012, T-14014, T-14015 |
| FR-824 | T-14002, T-14033, T-14035 |
| FR-827–828, FR-832 | T-14020, T-14025 |
| FR-829–831, FR-833, FR-838 | T-14021, T-14025 |
| FR-834 | T-14022 |
| FR-835, FR-837 | T-14030, T-14031 |
| FR-836 | T-14031, T-14035 |
| FR-839–841 | T-14011, T-14023, T-14024, T-14040 |
| FR-842, FR-845 | T-14032, T-14034, T-14035 |
| FR-843 | T-14002, T-14033 |
| FR-844 | T-14034 |
| FR-846 | T-14013, T-14040 |
| FR-847 | T-14014, T-14041 |
| FR-848 | T-14030, T-14044 |
| FR-849–850 | T-14003, T-14004, T-14020, T-14042, T-14043 |
| NFR-746 | T-14052 |
| NFR-747 | T-14021, T-14052 |
| NFR-748 | T-14031, T-14035 |
| NFR-749 | T-14032, T-14034, T-14044, T-14051 |

## Тесты

- `test_approvals_templates.py` — проверка шаблона, этапы, участники, выключение, права.
- `test_approvals_route.py` — запуск, один активный маршрут, закрытая заявка, удалённая и завершённая задача.
- `test_approvals_snapshot.py` — снимок этапов и участников, правка и выключение шаблона после запуска.
- `test_approvals_stages.py` — последовательный этап, переходы, выбывание, завершение, история.
- `test_approvals_parallel.py` — `all`/`any`, отмена остальных, отклонение и возврат.
- `test_approvals_decisions.py` — комментарии, чужая попытка, повтор, гонка 20 POST.
- `test_approvals_cancel.py` — инициатор, администратор, завершённый маршрут, идемпотентность.
- `test_approvals_queue.py` — «Мои задания», просрочка, исчезновение после решения.
- `test_approvals_deadlines.py` — 24 часа, срок короче 24 часов, срок, отмена, простой планировщика, маркеры.
- `test_approvals_notify.py` — пять видов, получатели, отсутствие ПДн и комментария.
- `test_approvals_events.py` — `event_id`, `dedupe_key`, `stage_completed` → `completed`, отказ/возврат —
  `stage_completed` → `rejected`/`returned` без `completed`, откат.
- `test_approvals_automation.py` — `start_approval`, шесть триггеров, повторная доставка.
- `test_approvals_access.py` — инициатор, участник, ответственный, руководитель, наблюдатель, чужой.
- `test_approvals_journal.py` — коды, пустой автор, отсутствие комментария и ПДн.
- `test_notify_catalog.py` — пять видов и настройки.
- e2e `test_t14_my.py`, `test_t14_route.py`, `test_t14_card.py`, `test_t14_mobile.py`.
- Нагрузка — NFR-746/747; отдельный прогон гонки запуска и решения.
- SQL: `assertNumQueries` на GET `/approvals/my/` ≤10, на страницу маршрута ≤15, число не зависит от числа
  заданий; `EXPLAIN` подтверждает индексы `ApprovalAssignment(user,status,due_at)`,
  `ApprovalStageRun(route,status)` и частичный уникальный `ApprovalRoute(subject_type,subject_id) WHERE
  status='running'`.

## Этапы и партии

1. **Контракт, каркас, модели.** T-14001 контракт; T-14002 точки расширения и открытый реестр действий;
   T-14003 модели и миграция; T-14004–T-14006 красные тесты (последовательно, общая база).
2. **Шаблоны и запуск.** T-14010 служба шаблонов; T-14011 адаптеры субъектов; T-14012 запуск и снимок;
   T-14013 страница шаблонов; T-14014 блок в карточках; T-14015 зелёные тесты.
3. **Этапы и решения.** T-14020 переходы этапов; T-14021 решения и идемпотентность; T-14022 отмена;
   T-14023 доступ и краткая справка; T-14024 страница маршрута; T-14025 зелёные тесты и гонки.
4. **Задания, сроки, уведомления, события.** T-14030 «Мои задания»; T-14031 сроки и планировщик;
   T-14032 уведомления; T-14033 события и автоматика; T-14034 журнал; T-14035 зелёные тесты.
5. **Права, карточки, стенд.** T-14040 полная проверка прав; T-14041 блоки карточек; T-14042 сброс стенда;
   T-14043 миграции и регрессия; T-14044 360 px.
6. **Приёмка.** T-14050 полный серверный прогон; T-14051 браузеры; T-14052 нагрузка; T-14053 ручной проход;
   T-14054 исправления; T-14055 финальный прогон и отчёт.

## Риски и открытые вопросы

- **Гонка запуска.** Частичный уникальный индекс — единственная защита; служба должна ловить
  `IntegrityError` и возвращать `route_exists`, а не `500`. Тест — 20 параллельных POST.
- **Гонка решения.** Блокировка задания и сравнение ключа; без неё два запроса дадут два события. Тест — 20
  параллельных POST, один журнал и одно уведомление.
- **События и автоматика.** `stage_completed` и `completed` публикуются в одной транзакции, но обработчики
  получают их по очереди; повторная доставка гасится `(rule, event_id)`. Ошибка обработчика не отменяет
  решение.
- **Сроки.** Простой планировщика даёт опоздание, но не повтор; маркер и уведомление в одной транзакции.
  Часовой пояс хранится в UTC, отображение — `Europe/Moscow`.
- **Выбытие участника.** Минутное задание отменяет задания уволенных; при `all` этап может остаться без
  согласовавших — маршрут отменяется с записью, а не зависает.
- **Руководители.** `heads_of_unit` берёт узел и предков (для очереди), `unit_heads` — только выбранный узел
  (для `unit_head`); состав разрешается один раз при запуске и кэшируется по узлу, иначе запуск с несколькими
  этапами даст N+1.
- **Снимок и шаблон.** Правка шаблона не трогает маршрут; удаления шаблона нет, только выключение.
- **Карточка задачи.** Точка `task_card_parts` аддитивна; три места сборки карточки должны использовать общий
  контекст, иначе блок появится не везде.
- **ПДн.** Краткая справка показывает название и описание субъекта участнику; это осознанный доступ по
  назначению. В журнал, события и уведомления название, ФИО, адрес и комментарий не попадают.

## Решения плана

1. Снимок хранит разрешённых сотрудников в заданиях, а не ссылки на участников шаблона; правка шаблона не
   меняет идущий маршрут.
2. У `sequential` правило всегда `all`; ограничение проверяется и формой, и ограничением модели.
3. Ключ идемпотентности решения — `(assignment_id, actor_id, decision, comment.strip())`; повтор с тем же
   ключом — `200`, другой — `409`.
4. Активный маршрут — частичный уникальный индекс `(subject_type, subject_id) WHERE status='running'`; служба
   превращает нарушение в `route_exists`.
5. События публикуются после commit с `event_id`/`dedupe_key`; `approvals` их не повторяет, `automation`
   дедуплицирует по `(rule, event_id)`.
6. `approvals_tick` — каждую минуту в очереди `notify`, как `automation_tick`; маркеры `ApprovalNotice` —
   уникальные `(assignment, kind)`.
7. Реестр действий 013 открывается объединением статических обработчиков и зарегистрированных `Action`;
   `automation` не импортирует `approvals`.
8. Адаптеры субъекта регистрируют `servicedesk` и `tasks`; `approvals` читает их через `approval_subjects` и
   не импортирует чужие модели.
9. `task_card_parts` — аддитивная точка по образцу `ticket_card_parts`; общий контекст карточки задачи
   выносится в `tasks.services.card`.
10. Новых глобальных прав нет: шаблоны и административная отмена — `automation.manage`, запуск — `can_work`,
    решение — назначенный участник.
11. Комментарий решения хранится в задании и показывается на странице маршрута; в журнал, события и
    уведомления он не копируется.
12. Шаблон не удаляется, только выключается; идущие маршруты продолжаются.
13. Маршрут не вызывает `tickets.set_status`, `tasks.change_status` и `tasks.create`: статус субъекта и число
    обычных задач не меняются. Это проверяют T-14020 (переходы) и T-14043 (регрессия).
14. Порядок блокировок — субъект → маршрут → задание; минутное задание собирает `route_id` без блокировки,
    затем блокирует маршруты по `id` и задания. Обратного порядка нет.
15. `unit_head` разрешается новой `org.services.structure.unit_heads(unit_id)` — только руководитель и
    заместители выбранного узла; `queue_head` — `structure.heads_of_unit` очереди. `queues.can_manage` для
    разрешения участников не используется.
16. Часть карточки задачи — `TaskCardPart` с `render(request, TaskRef)`; точки `task_card_parts` и
    `approval_subjects` аддитивны.
