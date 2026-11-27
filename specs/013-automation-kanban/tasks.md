---
id: TASKS-013
вид: задачи
статус: утверждён
версия: 4
зависит_от: PLAN-013
основан_на: PLAN-013 sha256:45922764c6d424a56af1d4af672d8df7e0e83614255cfb1d4026824623fb7172
подпись: Максим | 2026-11-26T20:17+03:00 | sha256:02bc35114d98fe0bff4a5fb07c48fa5082caacf2fb7ed056ead4ae9a77b28d62
---

# Задачи среза 013: Канбан и автоматика

Формат строки: `- [ ] T-NNNNN [P] [исполнитель] описание — файлы или тест — (FR-NNN / NFR-NNN)`.
`[P]` означает, что задача не правит общий файл соседней задачи и может идти параллельно.
Исполнители: `code` — код и тесты, `arch` — контракт, стенд, прогоны и сверка, `человек` — ручной проход.

## Правила выполнения

- Этапы идут последовательно: этап 2 начинается после зелёного T-13003, этап 3 — после T-13013, этап 4 — после
  T-13025, этап 5 — после T-13036, этап 6 — после T-13045.
- Один автор на общий файл: `backend/apps/automation/models.py` и миграция — T-13003;
  `backend/apps/core/extensions.py` и `core/migrations/0018` — T-13002;
  `backend/apps/servicedesk/services/events.py`, `services/tickets.py`, `services/transfer.py` и
  `services/closing.py` — T-13023; `backend/apps/servicedesk/services/queues.py` — T-13041;
  `backend/apps/servicedesk/tasks.py` — T-13025; `backend/apps/tasks/services/events.py`,
  `tasks/services/tasks.py` и `tasks/tasks.py` — T-13024; `backend/config/cron.py` — T-13024 (T-13034 добавляет
  свою строку после T-13024); `backend/apps/automation/services/actions/__init__.py` — T-13030;
  `backend/apps/automation/services/conditions.py` — T-13020; `services/rules.py` — T-13021;
  `services/chain.py` — T-13022; `services/tick.py` — T-13034; `services/access.py` — T-13041;
  `services/validation.py` — T-13020;
  `forms.py`/`views`/`templates/automation/` — T-13040; `notify_kinds.py` — T-13042;
  `audit_labels.py` — T-13043; `stand.py` — T-13045;
  `backend/tests/test_sd_board.py` — T-13005 (T-13013 только запускает и правит e2e);
  `test_automation_actions.py` — T-13036; `test_automation_rules.py`/`test_automation_conditions.py` — T-13004;
  `test_automation_chain.py`/`test_automation_delayed.py`/`test_automation_access.py`/`test_automation_audit.py`
  — T-13006.
- Тесты одной базы — строго последовательно; красные тесты T-13004…T-13006 запускаются по одному.
- Новых правил по умолчанию нет; данные стенда не сбрасываются без решения владельца.
- Секреты — только `***`; ПДн в тесты и отчёты не попадают, используются синтетические `client.example`.

## Этап 1 — контракт, каркас и красные тесты

- [x] T-13001 [arch] Контракт CONTRACT-013: события, `event_id`, схемы правила/условий/действий, коды ошибок,
  точки расширения — `backend/tests/CONTRACT-013.md` — (FR-794–806, NFR-741)
- [x] T-13002 [code] Каркас `automation`, `INSTALLED_APPS`, четыре имени `POINTS`, право `automation.manage`
  и миграция `core 0018` — `backend/apps/automation/apps.py`, `backend/apps/core/extensions.py`,
  `backend/apps/core/migrations/0018_automation_permission.py`, `backend/config/settings.py` — (FR-793, FR-812,
  FR-819)
- [x] T-13003 [code] Модели и миграция: `Rule`, `RuleAction`, `RuleRun` (с `created_at` и индексом
  `(subject_type, subject_id, created_at)`), `RuleActionRun`, ограничения, индексы;
  заготовка `stand.py` — `backend/apps/automation/models.py`, `migrations/0001_initial.py` — (FR-794, FR-805,
  FR-809, FR-815, FR-819)
- [x] T-13004 [code] Красные тесты правил и условий — `backend/tests/test_automation_rules.py`,
  `test_automation_conditions.py` — (FR-795–799)
- [x] T-13005 [code] Красные тесты доски — `backend/tests/test_sd_board.py` — (FR-783–792)
- [x] T-13006 [code] Красные тесты цепочки, задержки, прав, журнала и повторной доставки каждого события —
  `test_automation_chain.py`,
  `test_automation_delayed.py`, `test_automation_access.py`, `test_automation_audit.py` — (FR-805–813, FR-817,
  FR-818)

## Этап 2 — канбан заявок

- [x] T-13010 [code] Служба доски: колонки, сортировка, фильтр по статусу, порция 50, счётчики; миграция
  `servicedesk 0006` с индексом `(queue, kind, sla_solution_due)` —
  `backend/apps/servicedesk/services/board.py` — (FR-784, FR-789, FR-790, FR-791)
- [x] T-13011 [code] Режим «Канбан»: маршруты, представления, шаблоны, HTMX-перетаскивание, меню смены статуса
  — `backend/apps/servicedesk/views/tickets_list.py`, `urls.py`, `backend/templates/servicedesk/board/` —
  (FR-783, FR-785, FR-786, FR-792)
- [x] T-13012 [code] Перенос, форма закрытия, конфликт одновременного изменения — `services/board.py`,
  `views/tickets_list.py` — (FR-787, FR-788)
- [x] T-13013 [code] Прогон зелёных тестов доски и 360 px (файл `test_sd_board.py` принадлежит T-13005),
  e2e `test_t13_board.py` —
  (FR-783–792, NFR-743)

## Этап 3 — движок правил

- [x] T-13020 [code] Условия и валидация: белый список полей, шесть операторов, `changed_field`,
  `sla_deadline`, проверка JSON, лишних полей и параметров, активных ссылок; `task_author` — все задачи
  автора, не одна — `services/conditions.py`, `services/validation.py` — (FR-797, FR-798)
- [x] T-13021 [code] Выбор правил, `RuleRun` по `event_id`, приоритет, один запуск — `services/rules.py` —
  (FR-794, FR-805, FR-809, FR-815)
- [x] T-13022 [code] Контекст цепочки, глубина 3, запрет повтора правила — `services/chain.py` — (FR-806)
- [x] T-13023 [code] События заявок: создание, ответ, передача, закрытие, статус, изменение полей; `event_id`
  во всех существующих событиях, публикация после записи; `entry_id` в передаче, закрытие —
  `close:<number>:<closed_at>` —
  `backend/apps/servicedesk/services/events.py`, `services/tickets.py`, `services/transfer.py`,
  `services/closing.py` — (FR-795, FR-809)
- [x] T-13024 [code] События задач: создание, изменение полей, статус; `tasks_automation_tick` каждые 5 минут,
  регистрация в cron —
  `backend/apps/tasks/services/events.py`, `services/tasks.py`, `tasks.py`, `backend/config/cron.py` — (FR-796,
  FR-816)
- [x] T-13025 [code] Событие порога SLA один раз на цикл/срок/вид — `backend/apps/servicedesk/tasks.py`,
  `test_sd_sla_triggers.py` — (FR-815)

## Этап 4 — действия и задержки

- [x] T-13030 [code] Реестр действий, проверка схемы параметров, «уведомить», закрытый набор подстановок и
  ПДн —
  `backend/apps/automation/services/actions/__init__.py`, `actions/notify.py` — (FR-799, FR-800, FR-811, FR-817)
- [x] T-13031 [code] «Назначить»: сотрудник, руководитель очереди, распределение, выбор нескольких
  руководителей — `actions/assign.py` — (FR-801)
- [x] T-13032 [code] «Поставить задачу»: шаблоны, исполнитель, срок, связь с заявкой —
  `actions/task.py` — (FR-802)
- [x] T-13033 [code] «Сменить статус» и «Добавить комментарий» — `actions/status.py`, `actions/comment.py` —
  (FR-803, FR-804)
- [x] T-13034 [code] Отложенные действия, `tick` раз в минуту, отмена при выключении, строка в cron —
  `backend/apps/automation/services/tick.py`, `backend/config/cron.py` — (FR-807, FR-808)
- [x] T-13035 [code] Изоляция ошибок действий и savepoint — `services/actions/__init__.py` — (FR-818)
- [x] T-13036 [code] Зелёные тесты действий, ПДн и ошибок, дедупликации получателя и выбора руководителя
  очереди — `test_automation_actions.py` — (FR-799–804,
  FR-817, FR-818)

## Этап 5 — права, уведомления, журнал

- [x] T-13040 [code] Страница правил: список, форма, условия/действия, журнал запусков —
  `backend/apps/automation/forms.py`, `views/`, `templates/automation/`, `urls.py` — (FR-793, FR-794, FR-813)
- [x] T-13041 [code] Доступ: публичная `queues.can_manage` (из `_can_manage`) для руководителя/заместителя
  очереди и вышестоящего узла, администратор, автор задачи, наблюдатель; архивная очередь, увольнение автора;
  выключение правил не-очереди — `services/access.py` — (FR-812, FR-813, FR-814)
- [x] T-13042 [code] Вид уведомления «Сообщение правила», каталог и настройки —
  `backend/apps/automation/notify_kinds.py`, `test_notify_catalog.py` — (FR-811)
- [x] T-13043 [code] Русские подписи журнала, коды событий, хранение 3 года и ночная очистка —
  `audit_labels.py`, `services/journal.py`, `config/cron.py` — (FR-809, FR-810, FR-817)
- [x] T-13044 [code] Пункт меню «Автоматизация» и ссылки на правила из карточки — `apps.py`, шаблоны —
  (FR-783, FR-793)
- [x] T-13045 [code] Сброс стенда и проверка миграций на базе со 110 000 заявок —
  `backend/apps/automation/stand.py`, миграционный прогон — (FR-819)

## Этап 6 — приёмка

- [x] T-13050 [arch] Полный серверный прогон `systemd-run --user`, `*.status`/`*.log`/`*.exit` — все тесты —
  (FR-783–819)
- [x] T-13051 [arch] Браузеры `test_t13_*`: Chromium, Firefox, Edge, Яндекс — (FR-783–792, NFR-743)
- [x] T-13052 [arch] Нагрузка: доска 100 пользователей/110 000 заявок, 200 правил, отдельный замер проверки
  правил NFR-741, NFR-742/745 —
  `crm-work/slice013/stage4/load/` — (NFR-741, NFR-742, NFR-745)
- [x] T-13053 [человек] Ручной проход: доска, закрытие, правило, уведомление, журнал, 360 px —
  `crm-work/slice013/stage4/manual/checklist.md` — (FR-783–792, FR-811)
- [x] T-13054 [code] Исправления находок приёмки — по отчёту T-13053 — (все)
- [x] T-13055 [arch] Финальный прогон и отчёт `docs/reviews/TASKS-013.md` — (все)
