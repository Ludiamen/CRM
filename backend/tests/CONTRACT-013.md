# Контракт имён тестов среза 013 (T-13001…T-13055)

Основа: SPEC-013 v3, PLAN-013 v4, TASKS-013 v4.

## 1. Объём

FR-783…819, NFR-741…745. Новое приложение `automation`; новое право `automation.manage`; новый вид
уведомления `automation.rule_notice`. Модели `servicedesk.Ticket`, `tasks.Task` не меняются, кроме
индекса доски `servicedesk 0006`.

## 2. Модели

- `Rule`: name, subject_type `ticket|task`, scope `global|queue|task_author`, queue FK, author FK, trigger,
  conditions JSON, priority 1…999, enabled, created_at, updated_at.
- `RuleAction`: rule FK, order 1…n, kind, params JSON, delay_seconds 0…2 592 000; unique `(rule, order)`.
- `RuleRun`: rule FK PROTECT, subject_type, subject_id, event, event_id, chain_id UUID, depth 1…, root_run_id
  UUID, status `running|done|skipped|failed`, reason, created_at, finished_at; unique `(rule, event_id)`.
- `RuleActionRun`: run FK CASCADE, action FK SET_NULL, order, kind, status
  `pending|running|done|skipped|failed`, reason, due_at, started_at, finished_at; unique `(run, order)`.

## 3. События

| Код | `event_id` | Данные |
|---|---|---|
| `servicedesk.ticket_created` | `created:<number>` | number, queue_id, actor_id |
| `servicedesk.reply_received` | `reply:<entry_id>` | number, entry_id, via |
| `servicedesk.ticket_transferred` | `transfer:<entry_id>` | number, from_queue_id, to_queue_id |
| `servicedesk.ticket_closed` | `close:<number>:<closed_at>` | number, closed_at |
| `servicedesk.ticket_status_changed` | `status:<entry_id>` | number, before_id, after_id, reason |
| `servicedesk.ticket_field_changed` | `update:<audit_id>` | number, changed[] |
| `servicedesk.sla_threshold` | `sla:<cycle>:<deadline>:<kind>` | number, cycle_id, deadline, kind |
| `tasks.task_created` | `task-created:<id>` | id, author_id |
| `tasks.task_status_changed` | `task-status:<audit_id>` | id, before, after |
| `tasks.task_field_changed` | `task-update:<audit_id>` | id, changed[] |
| `tasks.task_threshold` | `task:<id>:<kind>:<deadline>` | id, deadline, kind |

Публикация — после записи, шина — после commit. Повторная доставка с тем же `event_id` не создаёт второй
`RuleRun`.

## 4. Маршруты

| Маршрут | Метод | Право | Ответ |
|---|---|---|---|
| `/tickets/?view=board` | GET | `can_view` | доска |
| `/tickets/board/column/<key>/` | GET | `can_view` | фрагмент колонки |
| `/tickets/board/move/` | POST | `can_work` | фрагмент/`board_conflict` |
| `/automation/` | GET | `can_manage` | список правил |
| `/automation/new/` | GET/POST | `can_manage` | форма/redirect |
| `/automation/<id>/edit/` | GET/POST | `can_manage` | форма/redirect |
| `/automation/<id>/toggle/` | POST | `can_manage` | список/redirect |
| `/automation/runs/` | GET | `can_manage` | журнал |

Ошибки: `[data-error="<поле>"][data-code="<код>"]`, общая — `[role="alert"][data-code="<код>"]`.
Коды: `no_access`, `bad_status`, `board_conflict`, `rule_invalid`, `action_skipped`, `delay_range`,
`priority_range`, `archived_value`, `unknown_action`, `unknown_placeholder`.

## 5. Службы

- `automation.services.rules.on_event(subject_type, subject_id, event, event_id, data)`.
- `automation.services.conditions.match(subject, conditions)`.
- `automation.services.validation.validate_rule(rule_data)`.
- `automation.services.actions.run(action_run, subject)`.
- `automation.services.tick.run_due(now)`.
- `automation.services.access.visible_rules(user)`, `can_manage(user, rule)`.
- `servicedesk.services.board.columns(viewer, filters)`, `move(actor, ticket, status, version)`.
- `servicedesk.services.queues.can_manage(user, unit_id)` — источник права руководителя очереди.

## 6. Действия

| Код | Параметры | Пропуск |
|---|---|---|
| `notify` | recipients 1…5, text 1…500 | нет доступа/учётной записи, дубль получателя |
| `assign` | mode employee/queue_head/distribution, employee | уволен, наблюдатель, закрыта, задача+не employee |
| `create_task` | title, description, assignee, due_days 0…365 | нет `tasks.use`, нет прав на исполнителя |
| `change_status` | status | не ручной статус, `closed`/`autoclosed`/`new`, тот же статус |
| `comment` | text 1…2000 | нет активного автора правила для задачи |

Подстановки: `{number}`, `{status}`, `{queue}`, `{assignee}`, `{priority}`, `{url}`. Тема, ФИО, адрес и текст
переписки не подставляются.

## 7. Цепочка и задержка

- `chain_id`, `depth`, `root_run_id`; глубина >3 — стоп; правило не повторяется в цепочке.
- `pending` забирает `tick` под `select_for_update(skip_locked)`; `due_at <= now`; зависшее >10 минут —
  `failed`.
- Выключение правила отменяет `pending` с причиной `rule_disabled`.

## 8. Имена тестов

`test_automation_rules`, `test_automation_conditions`, `test_automation_actions`, `test_automation_chain`,
`test_automation_delayed`, `test_automation_access`, `test_automation_audit`, `test_sd_board`,
`test_sd_sla_triggers`, `test_tasks_automation`, `test_notify_catalog`, e2e `test_t13_board`, `test_t13_rules`.
