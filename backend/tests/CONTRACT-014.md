# CONTRACT-014: согласования

Контракт среза 014 (SPEC-014, PLAN-014). Коды и формы обязательны для реализации и тестов; русские тексты
могут уточняться, коды — нет.

## 1. Модели

| Модель | Ключевые поля | Ограничения |
|---|---|---|
| `ApprovalTemplate` | name, subject_type `ticket`/`task`, description, enabled, author | имя 1…150; описание ≤2 000 |
| `ApprovalStage` | template, order, title, mode `sequential`/`parallel`, rule `all`/`any`, deadline_hours | order 1…20; deadline 1…720; `sequential` ⇒ `all` |
| `ApprovalStageParticipant` | stage, order, kind `employee`/`unit_head`/`queue_head`, user, unit | employee ⇔ user; unit_head/queue_head ⇔ unit; дубли запрещены |
| `ApprovalRoute` | template PROTECT, template_name, subject_type, subject_id, subject_number, initiator, status, started_at, finished_at, cancelled_by | один `running` на `(subject_type, subject_id)` |
| `ApprovalStageRun` | route, order, title, mode, rule, deadline_hours, status, started_at, finished_at, due_at | unique `(route, order)` |
| `ApprovalAssignment` | stage_run, user, order, status, decision, comment, created_at, due_at, decided_at | unique `(stage_run, user)`; `pending` ⇒ decision null; decision = status; cancelled ⇒ decision null |
| `ApprovalNotice` | assignment, kind `reminder`/`overdue`, sent_at | unique `(assignment, kind)` |
| `ApprovalEvent` | route, kind, actor, data, at | только дописывается |

Статусы маршрута: `running`, `approved`, `rejected`, `returned`, `cancelled`.
Статусы задания: `pending`, `approved`, `rejected`, `returned`, `cancelled`.
Решения: `approved`, `rejected`, `returned`.

## 2. Запуск

`approvals.services.routes.start(actor, subject_type, subject_id, template_id)`.

Ошибки: `subject_closed`, `template_absent`, `template_disabled`, `subject_mismatch`, `no_participants`,
`route_exists`, `forbidden`, `template_invalid`.

Снимок: название шаблона, этапы, режимы, правила, сроки и разрешённые сотрудники. Правка шаблона после запуска
маршрут не меняет. `subject_id` — первичный ключ заявки/задачи, `subject_number` — номер для показа.

## 3. Решение

`approvals.services.routes.decide(actor, assignment_id, decision, comment)`.

Ключ идемпотентности: `(assignment_id, actor_id, decision, comment.strip())`.
Повтор того же ключа — `200` и сохранённый результат, в том числе после завершения маршрута. Другой ключ —
`409 already_decided`; отменённое задание — `409 assignment_cancelled`; чужой актор — `forbidden`;
комментарий для `rejected`/`returned` обязателен (`comment_required`), длина ≤4 000.

## 4. Этапы

- `sequential`: задания выдаются по одному в порядке `order`; следующее видно после согласования предыдущего.
- `parallel`/`all`: этап завершён, когда все оставшиеся задания согласованы.
- `parallel`/`any`: первое «Согласовано» завершает этап, остальные задания получают `cancelled`.
- «Отклонено»/«На доработку» завершают маршрут при любом правиле.
- Выбывший (`dismissed`/`blocked`) участник: задание отменяется; в `sequential` задание переходит следующему,
  в `parallel/any` этап ждёт остальных, в `parallel/all` завершается по оставшимся согласовавшим. Пустой этап
  без согласовавших отменяет маршрут с причиной `no_participants`.

## 5. Сроки

`due_at` — старт этапа + `deadline_hours`; все задания этапа получают этот срок. Напоминание за 24 часа —
только если `due_at - 24h > created_at`; иначе только уведомление в срок. Маркеры `(assignment, kind)`
уникальны, уведомление и маркер создаются в одной транзакции. `approvals_tick` — раз в минуту в очереди
`notify`; простой догоняется одним уведомлением с записью об опоздании.

## 6. События

| Событие | `event_id` | Поля |
|---|---|---|
| `approvals.started` | `approval-start:<route_id>` | route_id, subject_type, subject_id, subject_number, initiator_id, actor_id, template_id, started_at |
| `approvals.stage_completed` | `approval-stage:<stage_run_id>` | stage_run_id, order, result |
| `approvals.completed` | `approval-route:<route_id>:approved` | finished_at |
| `approvals.rejected` | `approval-route:<route_id>:rejected` | finished_at, assignment_id |
| `approvals.returned` | `approval-route:<route_id>:returned` | finished_at, assignment_id |
| `approvals.cancelled` | `approval-route:<route_id>:cancelled` | finished_at, cancelled_by_id |

`dedupe_key` = `event_id`. Публикация — после commit. Согласованный маршрут: `stage_completed` последнего
этапа → `completed`; отклонённый/возвращённый: `stage_completed` → `rejected`/`returned`, без `completed`;
отмена — только `cancelled`. Триггеры автоматики: `approval_started`, `approval_stage_completed`,
`approval_completed`, `approval_rejected`, `approval_returned`, `approval_cancelled` для `ticket` и `task`.

## 7. Точки расширения

- `approval_subjects` — `ApprovalSubject(type, title, load, lock, brief, can_view, can_work, url)`;
  регистрируют `servicedesk` и `tasks`.
- `task_card_parts` — `TaskCardPart(key, order, render)`; регистрирует `approvals`.
- `automation_actions` — действие `start_approval` с параметром `template`.

## 8. Маршруты

`/approvals/`, `/approvals/templates/new/`, `/approvals/templates/<id>/edit/`,
`/approvals/templates/<id>/toggle/`, `/approvals/my/`, `/approvals/routes/<id>/`, `POST /approvals/start/`,
`POST /approvals/routes/<id>/cancel/`, `POST /approvals/assignments/<id>/decide/`.

## 9. Уведомления и журнал

Виды: `approvals.assignment` (250), `approvals.decision` (251), `approvals.returned` (252),
`approvals.reminder` (253), `approvals.overdue` (254); модуль «Согласования», каналы портала и почты.
Получатели: назначение — участник; решение и возврат — инициатор; напоминание и просрочка — участник и
инициатор.

Журнал: `approvals.template_created`, `approvals.template_updated`, `approvals.template_enabled`,
`approvals.template_disabled`, `approvals.route_started`, `approvals.route_completed`,
`approvals.stage_completed`, `approvals.decision`, `approvals.route_rejected`, `approvals.route_returned`,
`approvals.route_cancelled`, `approvals.assignment_cancelled`. Комментарий решения, тема, ФИО и адрес
заявителя в журнал, события и уведомления не попадают.
