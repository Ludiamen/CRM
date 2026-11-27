---
id: PLAN-013
вид: план
статус: утверждён
версия: 4
зависит_от: SPEC-013, CONST, ADR-0002, ADR-0004, ADR-0009, ADR-0018, ADR-0020, ADR-0021, ADR-0022, REF-CAP, REF-UX, REF-SRC, TGT-ARCH, TGT-NFR, SPEC-002, SPEC-003, SPEC-004, SPEC-006, SPEC-009, SPEC-011, SPEC-012
основан_на: SPEC-013 sha256:69cd7432dfb4fd59e3ec8515fce00c930afa10676fe6f315bc96f672a78e529b
подпись: Максим | 2026-11-26T20:17+03:00 | sha256:45922764c6d424a56af1d4af672d8df7e0e83614255cfb1d4026824623fb7172
---

# План среза 013: Канбан и автоматика

## Сверка с конституцией

- **модуль-приложение.** Новое приложение `automation`; `servicedesk` и `tasks` только публикуют события и
  регистрируют точки расширения. Приложения не импортируют друг друга; ядро не импортирует `automation`.
- **настройка-без-кода.** Правила, условия, действия, области и приоритеты — данные. Статусы заявок и задачи
  остаются прежними справочниками/константами; новых схем стадий нет.
- **права и минимум доступа.** Чтение — `can_view`, работа — `can_work`; правило не расширяет доступ. Настройка
  правил — `automation.manage`, руководитель очереди по структуре, автор задачи по авторству.
- **аудит-изменений.** `RuleRun`/`RuleActionRun` — только дописываемые строки; изменения правил — `audit.record`;
  системные действия с пустым автором.
- **пдн-152фз.** В шаблоны, уведомления и журнал не попадают тема, ФИО, адрес и текст переписки; только номер,
  статус, очередь, ответственный, критичность и ссылка.
- **секреты-в-url.** Новых секретов и адресов с секретами нет.
- **sql-только-параметры.** Выборки — ORM; условия проверяются по белому списку полей, без `eval` и SQL по
  пользовательской строке.
- **стек-интерфейс и бэкенд.** Django 5.2, PostgreSQL, HTMX, RQ; новых пакетов нет. Минутное задание — `rq cron`.
- **тест-на-требование.** Каждый FR-783…819 и NFR-741…745 получает серверный, браузерный или нагрузочный тест;
  таблица трассировки — в SPEC-013 и разделе «Трассировка» ниже.
- **эталон-не-копия.** Берём поведение (стадии, правила, задания, история), не вёрстку и не тексты эталона.

## Технический контекст

- Статус заявки — справочник с видом и порядком (`backend/apps/servicedesk/models.py:77`); ручные статусы —
  `dictionaries.manual_statuses()` (`backend/apps/servicedesk/services/dictionaries.py:276`). Ручная смена —
  `tickets.set_status_manual`/`set_status` (`backend/apps/servicedesk/services/tickets.py:251`), правка полей —
  `update_fields` (`…/tickets.py:348`), закрытие — `closing.close` (`backend/apps/servicedesk/services/closing.py:80`).
- Задача — четыре статуса (`backend/apps/tasks/models.py:15`), доска — `tasks.services.boards`
  (`backend/apps/tasks/services/boards.py:31`), смена статуса — `tasks.change_status`
  (`backend/apps/tasks/services/tasks.py:189`), правка — `update` (`…/tasks.py:126`).
- Шина событий вызывает обработчики после фиксации транзакции, ошибка обработчика не откатывает действие
  (`backend/apps/core/events.py:54`). Точки расширения — статический `POINTS`
  (`backend/apps/core/extensions.py:18`).
- Уведомления — `notify.dispatch.create` (`backend/apps/notify/services/dispatch.py:122`), журнал —
  `core.services.audit.record` (`backend/apps/core/services/audit.py:28`), руководители узла —
  `structure.heads_of_unit` (`backend/apps/org/services/structure.py:397`). Право руководителя очереди —
  `servicedesk.services.queues.can_manage`: руководитель или заместитель узла очереди либо вышестоящего узла;
  сейчас в `backend/apps/servicedesk/services/queues.py:49` эта проверка приватная (`_can_manage`), T-13041
  делает её публичной. `structure.managed_units` даёт тот же набор.
- Списки среза 006 — `List`, `Field`, `Record` (`backend/apps/lists/models.py:36,57,121`); в 013 не меняются,
  нужны срезу 015.
- SLA-циклы и уведомления — `SlaCycle`/`SlaNotice`, задание `sla_tick`; напоминания задач — `tasks_reminders`.
  Новые события порогов добавляются рядом, не меняя расчёт сроков.

## Новые компоненты и лицензии

Новых пакетов и лицензий нет. Перетаскивание — существующие HTMX/SortableJS; графики и внешние сервисы не
нужны.

## Где живёт код

```text
backend/apps/automation/apps.py                 регистрация, подписки, точка сброса стенда
backend/apps/automation/models.py               Rule, RuleAction, RuleRun, RuleActionRun
backend/apps/automation/migrations/0001_initial.py
backend/apps/automation/extensions.py           Subject, Trigger, Action, Recipient и реестры
backend/apps/automation/services/rules.py       on_event, выбор правил, условия, запуск
backend/apps/automation/services/conditions.py  белый список полей, операторы, проверка значений
backend/apps/automation/services/validation.py  проверка правила, условий и параметров действий
backend/apps/automation/services/actions.py     реестр действий, notify/assign/create_task/change_status/comment
backend/apps/automation/services/chain.py       contextvars: chain_id, depth, root_run_id
backend/apps/automation/services/tick.py        отложенные действия, минутное задание
backend/apps/automation/services/access.py      visible_rules, can_manage, область очереди/автора
backend/apps/automation/services/journal.py     запуск, действие, причина, очистка 3 года
backend/apps/automation/forms.py, views/, urls.py, templates/automation/
backend/apps/automation/notify_kinds.py         вид «Сообщение правила»
backend/apps/automation/audit_labels.py
backend/apps/automation/stand.py                очистка правил и запусков на стенде
backend/apps/core/extensions.py                 четыре имени POINTS
backend/apps/core/migrations/0018_automation_permission.py
backend/apps/servicedesk/services/events.py     новые события статуса, полей и порогов SLA
backend/apps/servicedesk/services/tickets.py    вызовы публикации
backend/apps/servicedesk/tasks.py               событие порога SLA
backend/apps/servicedesk/services/queues.py     публичная can_manage для правил очереди
backend/apps/servicedesk/services/board.py      колонки, сортировка, фильтр, порция 50
backend/apps/servicedesk/migrations/0006_board_index.py  индекс сортировки доски
backend/apps/servicedesk/views/tickets_list.py  режим «Канбан» и фрагменты
backend/apps/servicedesk/urls.py                маршруты доски и переноса
backend/templates/servicedesk/board/
backend/apps/tasks/services/events.py           события задачи и порогов
backend/apps/tasks/services/tasks.py            вызовы публикации
backend/apps/tasks/tasks.py                     tasks_automation_tick
backend/config/cron.py                          минутный tick автоматики и порогов задач
backend/config/settings.py                      приложение automation
backend/tests/test_automation_*.py, test_sd_board.py, test_sd_sla_triggers.py, test_tasks_automation.py
backend/tests/e2e/test_t13_*.py
```

## Изменения ядра и прежних модулей

| Область | Изменение | Причина |
|---|---|---|
| `core.extensions.POINTS` | добавить `automation_subjects`, `automation_triggers`, `automation_actions`, `automation_recipients` | точки расширения движка без импорта приложений |
| `core` миграция `0018` | право `automation.manage`, выдача «Администратору портала» | настройка глобальных правил |
| `servicedesk.services.events` | `event_id` во всех существующих событиях; новые `ticket_field_changed`, `ticket_status_changed`, `sla_threshold`; `entry_id` в передаче; закрытие — `close:<number>:<closed_at>` | триггеры создания, ответа, передачи, закрытия, статуса, поля и SLA |
| `tickets.set_status` / `update_fields` / `transfer._move` / `closing.close` | публикация событий после записи; `event_id` из `entry_id`/`audit_id`, закрытие — `close:<number>:<closed_at>` | контракт SPEC-013 |
| `servicedesk.tasks.sla_tick` | одно событие порога на цикл/срок/вид | однократность SLA |
| `tasks.services.events` | `task_created`, `task_field_changed`, `task_status_changed`, `task_threshold` | триггеры задач |
| `tasks.update` / `change_status` / `create` | публикация событий с `audit_id` или номером задачи | контракт SPEC-013 |
| `tasks.tasks` + `config.cron.py` | `tasks_automation_tick` каждые 5 минут | пороги «скоро»/«просрочена» по календарю |
| `servicedesk.Ticket` Meta + миграция `0006` | индекс `(queue, kind, sla_solution_due)` для сортировки доски | NFR-742/745, без условного «добавить позже» |
| `servicedesk.services.queues` | публичная `can_manage(actor, unit_id)` вместо приватной `_can_manage` | единая проверка прав руководителя очереди |
| `notify` каталог | вид `automation.rule_notice` | уведомление правила |
| тесты каталога/границ | новые строки и точный набор | новый вид и точки расширения |

Порядок миграций: `core 0018` → `automation 0001` → `servicedesk 0006`. Модели `tasks` не меняются.

## Модель данных, ограничения и индексы

| Модель | Поля | Ограничения и индексы |
|---|---|---|
| `Rule` | name, subject_type, scope, queue FK, author FK, trigger, conditions JSON, priority, enabled, created_at, updated_at | check priority 1…999; check очередь есть только при `scope=queue`; check `ticket` не имеет `task_author`, `task` не имеет `queue`; index `(subject_type, trigger, enabled)`, `(scope, queue)` |
| `RuleAction` | rule FK, order, kind, params JSON, delay_seconds | unique `(rule, order)`; check delay 0…2 592 000 |
| `RuleRun` | rule FK PROTECT, subject_type, subject_id, event, event_id, chain_id UUID, depth, root_run_id UUID, status, reason, created_at, finished_at | unique `(rule, event_id)`; index `(subject_type, subject_id, created_at)`, `(status, created_at)` |
| `RuleActionRun` | run FK CASCADE, action FK SET_NULL, order, kind, status, reason, due_at, started_at, finished_at | unique `(run, order)`; index `(status, due_at)` |

Доска получает индекс `(queue, kind, sla_solution_due)` миграцией `servicedesk 0006`; сортировка по критичности, последнему сообщению и номеру идёт по уже выбранной порции, поэтому полный составной индекс не нужен. Существующие индексы `(queue, kind)` и частичный `(closed_at)` остаются.

`RuleRun` создаётся до действий; `event_id` — из контракта SPEC-013. Повторная вставка ловится уникальным
ограничением и даёт пропуск. `RuleActionRun` с `status=pending` — отложенное действие; `tick` забирает строки
через `select_for_update(skip_locked)`.

## Валидация правила

`automation.services.validation.validate_rule` — единственная точка проверки перед сохранением и повторная
проверка при запуске:

- субъект и событие совместимы (`ticket` не получает задачных событий и наоборот); область `queue` требует
  очередь-узел; `task_author` требует активного автора правила и применяется ко всем задачам, где
  `author_id = rule.author_id`, а не к одной задаче;
- очередь существует, отмечена очередью и не архивна; автор активен;
- условие — ровно `field`, `op`, `value`; поле есть в белом списке субъекта и события; оператор допустим для
  типа; значение-ссылка существует, не архивно; `changed_field` и `sla_deadline` допустимы только для своих
  событий;
- действий 1…20; код действия зарегистрирован; параметры — только из схемы действия, обязательные заполнены,
  лишние отклоняются; задержка 0…2 592 000 секунд; приоритет 1…999;
- неизвестное действие при сохранении — ошибка формы; при запуске (приложение 014 не установлено) — пропуск с
  записью;
- JSON, прочитанный из базы, проверяется заново: не список/не словарь, неизвестное поле, лишний параметр или
  архивная ссылка дают пропуск правила/действия с причиной, а не исключение.

Тесты: неизвестные поля и лишние параметры, все операторы, архивные ссылки, несовместимые субъект/область,
задержка 31 день, приоритет 1000, неизвестное действие.

## Маршруты и контракты

| Маршрут | Метод | Что делает | Права |
|---|---|---|---|
| `/tickets/?view=board` | GET | доска заявок с текущими фильтрами | `can_view` |
| `/tickets/board/column/<key>/` | GET | колонка, порция 50 и «Показать ещё» | `can_view` |
| `/tickets/board/move/` | POST | перенос карточки, проверка версии | `can_work` |
| `/automation/` | GET | список правил по доступным областям | `can_manage` |
| `/automation/new/` | GET/POST | создание правила | `can_manage` |
| `/automation/<id>/edit/` | GET/POST | правка правила | `can_manage` |
| `/automation/<id>/toggle/` | POST | включение/выключение | `can_manage` |
| `/automation/runs/` | GET | журнал запусков и действий | `can_manage` |

Общие ответы ошибок: `no_access`, `bad_status`, `board_conflict`, `rule_invalid`, `action_skipped`. Коды и
русские тексты — в `CONTRACT-013`.

## Службы и порядок вызовов

1. **Событие.** `servicedesk` публикует создание, ответ, передачу, закрытие, статус, изменение полей и порог SLA; `tasks` — создание, изменение полей, статус и порог. У каждого события есть `event_id` (номер, entry_id, audit_id, время закрытия или ключ цикла); публикация — после записи, шина вызывает подписчиков после commit.
2. **`automation.services.rules.on_event(subject_type, subject_id, event, event_id, data)`**:
   - выбирает включённые правила субъекта, события и доступной области (глобальные + очередь + автор задачи) по
     приоритету и pk;
   - для каждого создаёт `RuleRun` (unique `(rule,event_id)`), проверяет условия по снимку субъекта;
   - при несовпадении — `skipped` с причиной; при совпадении — действия по порядку.
3. **Условия.** `conditions.match` читает поля из зарегистрированного субъекта; значения-ссылки сверяет с
   активными объектами; архивированное значение даёт несовпадение.
4. **Действия.** `actions.run(action, run, subject)` в своём savepoint; результат — `RuleActionRun`; ошибка
   ловится, следующие действия выполняются. Действия, меняющие субъект, публикуют своё событие; `chain.py`
   передаёт `chain_id`, `depth`, `root_run_id`.
5. **Цепочка.** Глубина >3 или повтор правила в цепочке — пропуск с записью; исходное действие пользователя не
   отменяется.
6. **Задержка.** Действие с `delay_seconds>0` создаёт `RuleActionRun(status=pending, due_at)`; `tick` раз в
   минуту забирает должное, перечитывает субъект и права, выполняет или пишет пропуск. Выключение правила
   отменяет его pending-строки.
7. **Пороги.** `sla_tick` публикует `sla_threshold` один раз на цикл/срок/вид; `tasks_automation_tick` — один
   раз на задачу/порог/срок по рабочему календарю.

## Шаблоны и интерфейс

- Список заявок: переключатель «Список / Канбан»; доска — горизонтальные колонки, карточка, счётчик, пустое
  состояние, «Показать ещё».
- Карточка доски: номер, тема, заявитель, критичность, ответственный, срок SLA; меню «Сменить статус» и
  «Закрыть» для клавиатуры и 360 px.
- Закрытие: существующая форма решения в слайдере; выбор закрытого статуса, решение обязательно.
- Автоматизация: список правил (субъект, область, событие, состояние, автор), форма с динамическими условиями
  и действиями, журнал запусков.
- Ошибки формы — русские, рядом с полем; несовместимые сочетания объясняются текстом.

## Уведомления и журнал

- Новый вид `automation.rule_notice` («Сообщение правила»); каналы — настройки среза 004; текст — шаблон из
  закрытого набора; внешние каналы получают только событие и ссылку.
- Журнал: `automation.rule_created`, `automation.rule_updated`, `automation.rule_enabled`,
  `automation.rule_disabled`, `automation.run`, `automation.action`, `automation.action_skipped`; русские
  подписи — `audit_labels.py`; ПДн не пишутся.
- Запуски и действия хранятся 3 года; ночная очистка `automation_retention` в `maintenance`.

## Стенд

- `automation/stand.py` очищает `RuleActionRun`, `RuleRun`, `RuleAction`, `Rule`; регистрируется в общей точке
  сброса ядра.
- E2E-сценарии создают свои правила через форму/службу и убирают их после; сид примеров не нужен.
- Нагрузочный профиль дополняется 200 правилами и 1000 событиями; данные — синтетические.

## Трассировка требований

| FR / NFR | Задачи |
|---|---|
| FR-783–792 | T-13010…T-13013, T-13050…T-13053 |
| FR-793–794 | T-13002, T-13003, T-13020, T-13040 |
| FR-795–798 | T-13004, T-13020, T-13023…T-13025 (создание, ответ, передача, закрытие, статус, поле, пороги; `event_id` и повторная доставка) |
| FR-799–804 | T-13030…T-13033, T-13036 (дедупликация получателя, выбор руководителя очереди) |
| FR-805–806 | T-13021, T-13022 |
| FR-807–808 | T-13034 |
| FR-809–810 | T-13021, T-13043 |
| FR-811 | T-13030, T-13042 |
| FR-812–814 | T-13041 (`queues.can_manage`, архивная очередь, увольнение автора, выключение при снятии очереди) |
| FR-815 | T-13025 |
| FR-816 | T-13024 |
| FR-817–818 | T-13030, T-13035, T-13043 |
| FR-819 | T-13002, T-13003, T-13045 |
| NFR-741–742, NFR-745 | T-13050…T-13052 (отдельный замер проверки правил, доска, SQL-запросы) |
| NFR-743–744 | T-13013, T-13036, T-13051 |

## Тесты

- `test_automation_rules.py` — выбор правил, приоритет, условия, один запуск, `event_id`.
- `test_automation_conditions.py` — шесть операторов, `changed_field`, `sla_deadline`, архивные значения.
- `test_automation_actions.py` — пять действий, пропуски, права, ПДн, ошибки.
- `test_automation_chain.py` — A→B→A, глубина, повтор правила, 20 действий.
- `test_automation_delayed.py` — pending, tick, закрытая заявка, 30 дней, выключение правила.
- `test_automation_access.py` — администратор, руководитель очереди, автор задачи, наблюдатель, увольнение.
- `test_automation_audit.py` — коды и отсутствие ПДн.
- `test_sd_board.py` — колонки, сортировка, фильтр, 50/ещё, права, закрытие, конфликт.
- `test_sd_sla_triggers.py` — однократность, параллельные tick, новый цикл.
- `test_tasks_automation.py` — статусы, пороги, доска, история.
- `test_notify_catalog.py` — новый вид и настройки.
- e2e `test_t13_board.py`, `test_t13_rules.py` — доска, перетаскивание, закрытие, форма правила.
- Нагрузка — доска 100 пользователей/110 000 заявок, 200 правил; отдельный замер NFR-741: 1000 событий,
  p95 проверки правил ≤100 мс.
- `task_author` применяется ко всем задачам автора, не к одной; чужая задача не попадает под правило.
- Повторная доставка каждого события (`ticket_created`, `reply_received`, `ticket_transferred`,
  `ticket_closed`, `task_created`, `task_status_changed`, `task_field_changed`, SLA/task threshold) — один
  `RuleRun` на `(rule, event_id)`.
- Уведомление одному сотруднику любым числом способов (ответственный, наблюдатель, руководитель, выбранный) —
  одно уведомление за запуск; выбор одного руководителя очереди по нагрузке, ФИО и номеру.
- Публикация `task_created`, передачи и закрытия заявки проверяется отдельными тестами, а не только общим
  прогоном.
- Миграции на базе со 110 000 заявок и старыми ролями — отдельный шаг T-13045; старые тесты остаются
  зелёными.

## Этапы и партии

1. **Контракт и красные тесты.** T-13001 контракт; T-13002 каркас, `POINTS`, право; T-13003 модели и миграции;
   T-13004–T-13006 красные тесты (последовательно, общая база).
2. **Канбан заявок.** T-13010 служба доски; T-13011 вид и шаблоны; T-13012 перенос и закрытие; T-13013 тесты и
   360 px.
3. **Движок правил.** T-13020 условия; T-13021 запуск; T-13022 цепочка; T-13023 события заявок; T-13024
   события задач и пороги; T-13025 пороги SLA.
4. **Действия и задержки.** T-13030 реестр и уведомление; T-13031 назначение; T-13032 задача; T-13033 статус и
   комментарий; T-13034 отложенные; T-13035 ошибки; T-13036 тесты действий.
5. **Права, уведомления, журнал.** T-13040 страница правил; T-13041 доступ и увольнение; T-13042 вид
   уведомления; T-13043 журнал; T-13044 меню и ссылки; T-13045 стенд.
6. **Приёмка.** T-13050 полный серверный прогон; T-13051 браузеры; T-13052 нагрузка; T-13053 ручной проход;
   T-13054 исправления; T-13055 финальный прогон и отчёт.

## Риски и открытые вопросы

- **Цепочки.** Ошибка в контексте даст двойной запуск; закрывается тестами на `event_id` и глубину.
- **Доска на 110 000 заявок.** Колонки по 50 и индексы `(queue, kind)`; если p95 не проходит, ограничить
  колонку и добавить составной индекс по сроку.
- **Пороги SLA.** `sla_tick` идёт по всем циклам; событие публикуется один раз, но нагрузка растёт. При
  необходимости — порция и отдельный индекс по `is_current`.
- **Права руководителя очереди.** Источник истины — `queues.can_manage`; проверка вызывается и при сохранении
  правила, и при отложенном действии, чтобы снятая очередь не дала доступ задним числом.
- **ПДн в шаблонах.** Закрытый набор подстановок; тест с адресом и ФИО в теме.
- **Увольнение автора.** Выключение правил и отмена pending — в службе увольнения; тест на повторный вход.

## Решения плана

1. `event_id` — строка из контракта SPEC-013; `RuleRun` уникален по `(rule, event_id)`. Падение между
   действиями не повторяет запуск: `running` старше 10 минут → `failed`.
2. Все действия независимы; отдельного `on_error` нет. Следующее действие видит результат предыдущих успешных.
3. `RuleActionRun` — и журнал, и очередь отложенных; отдельной таблицы pending нет.
4. Доска — режим списка, не отдельная сущность; порядок колонки не хранится.
5. `automation.manage` — только администратор. Руководитель очереди — публичная `queues.can_manage(user, rule.queue)`
   (T-13041 делает её публичной)
   (руководитель или заместитель узла очереди либо вышестоящего); архивная или снятая очередь запрещена;
   та же проверка выполняется при отложенном действии. Автор задачи — только свои задачи при `tasks.use`;
   наблюдатель правил не настраивает. Новых глобальных прав, кроме `automation.manage`, нет.
6. Шаблоны не подставляют тему, ФИО и адрес; закрытый набор подстановок проверяется формой.
7. `tasks_automation_tick` — каждые 5 минут в `maintenance`; `automation_tick` — каждую минуту в `notify`.
8. Правило с запусками не удаляется; выключение отменяет pending.
9. Заявка закрывается только `closing.close` через форму; правило меняет только ручные статусы.
10. Новый вид уведомления — один на все правила; текст правила задаёт автор в закрытом наборе подстановок.
