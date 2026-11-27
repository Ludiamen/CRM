---
id: TASKS-014
вид: задачи
статус: утверждён
версия: 2
зависит_от: PLAN-014
основан_на: PLAN-014 sha256:4ef6cf1db5437cbe8c878972b7c2d57de29d8843709f5d4aa1e39812944eaee2
подпись: Максим | 2026-11-27T15:16+03:00 | sha256:70c79e93627c3bae4d6dc9510b71c4095214896d1f0c5909c40947ff62384315
подпись: Максим | 2026-11-27T15:17+03:00 | sha256:70c79e93627c3bae4d6dc9510b71c4095214896d1f0c5909c40947ff62384315
---

# Задачи среза 014: Согласования

Формат строки: `- [ ] T-NNNNN [P] [исполнитель] описание — файлы или тест — (FR-NNN / NFR-NNN)`.
`[P]` означает, что задача не правит общий файл соседней задачи и может идти параллельно.
Исполнители: `code` — код и тесты, `arch` — контракт, стенд, прогоны и сверка, `человек` — ручной проход.

## Правила выполнения

- Этапы идут последовательно: этап 2 начинается после T-14006 (красные тесты зафиксированы), этап 3 — после
  T-14015, этап 4 — после T-14025, этап 5 — после T-14035, этап 6 — после T-14044.
- Один автор на общий файл: `backend/apps/approvals/models.py` и миграция — T-14003;
  `backend/apps/core/extensions.py`, `automation/services/validation.py`, `automation/services/actions/__init__.py`,
  `automation/forms.py`, `servicedesk/automation.py`, `tasks/automation.py` — T-14002;
  `servicedesk/approval.py`, `servicedesk/extensions.py`, `tasks/approval.py`, `tasks/extensions.py` — T-14011;
  `backend/apps/org/services/structure.py` — T-14012;
  `approvals/extensions.py` — T-14014 (T-14041 дополняет);
  `tasks/services/card.py`, `tasks/views/pages.py`, `tasks/views/actions.py`, `tasks/views/comments.py`,
  `templates/tasks/_card.html` — T-14014 (T-14041 только добавляет e2e и проверку);
  `approvals/apps.py` — T-14003 (T-14030, T-14032, T-14033, T-14034 и T-14042 добавляют свои регистрации
  последовательно); `approvals/urls.py` — T-14013 (T-14024 и T-14030 добавляют маршруты последовательно);
  `approvals/services/routes.py` — T-14012 (T-14021, T-14022 и T-14031 дополняют последовательно);
  `approvals/services/stages.py` — T-14020 (T-14031 дополняет);
  `approvals/services/access.py` — T-14023 (T-14040 дополняет); `config/cron.py` — T-14031;
  `approvals/stand.py` — T-14003 (T-14042 заполняет);
  `approvals/views/templates.py` — T-14013 (T-14040 дополняет); `approvals/views/routes.py` — T-14024
  (T-14040 дополняет); `approvals/templates/approvals/**` — T-14013, T-14024, T-14030 и T-14044 по порядку
  этапов.
- Тесты одной базы — строго последовательно; красные тесты T-14004…T-14006 запускаются по одному.
- Общие тестовые файлы: `test_approvals_templates.py`, `test_approvals_route.py`,
  `test_approvals_snapshot.py` — T-14004; `test_approvals_stages.py`, `test_approvals_parallel.py`,
  `test_approvals_decisions.py`, `test_approvals_cancel.py` — T-14005; `test_approvals_queue.py`,
  `test_approvals_deadlines.py`, `test_approvals_notify.py`, `test_approvals_events.py`,
  `test_approvals_automation.py`, `test_approvals_access.py`, `test_approvals_journal.py` — T-14006.
  T-14015, T-14025 и T-14035 только запускают их и правят код, а не чужие тестовые файлы.
- Регрессионные ожидания чужих срезов: `test_extensions.py`, `test_feed_boundaries.py`,
  `test_feed_core_changes.py`, `test_instructions_core_changes.py`, `test_kb_boundaries.py`,
  `test_lists_boundaries.py`, `test_messenger_boundaries.py`, `test_messenger_core_changes.py`,
  `test_messenger_deploy.py`, `test_sd_boundaries.py`, `test_tasks_core_changes.py` — T-14002 (POINTS);
  `test_notify_catalog.py`, `test_notify_catalog_2.py`, `test_notify_prefs.py`,
  `e2e/test_e04_my_settings.py`, `e2e/test_e12_criteria.py` — T-14032; `test_automation_rules.py` — T-14033;
  `test_tasks_deploy.py`, `test_tasks_core_changes.py`, `test_lists_access.py`,
  `test_instructions_deploy.py`, `test_messenger_deploy.py` — T-14030 (пункты меню);
  `test_lists_deploy.py`, `test_tasks_deploy.py`, `test_notify_deploy.py`, `test_kb_deploy.py`,
  `test_sd_deploy.py`, `test_instructions_deploy.py`, `test_instructions_core_changes.py`,
  `test_feed_deploy.py`, `test_messenger_deploy.py` — T-14031 (число заданий `cron`). Файлы, названные в
  двух задачах, правятся последовательно: сначала T-14030, затем T-14031. Хвостовые проверки
  `INSTALLED_APPS` и `stand_reset` не правятся: `apps.approvals` вставляется после `apps.org`, сброс
  регистрируется до `apps.servicedesk`.
- Шаблоны по умолчанию не создаются; данные стенда не сбрасываются без решения владельца.
- Секреты — только `***`; ПДн в тесты и отчёты не попадают, используются синтетические `client.example`.

## Этап 1 — контракт, каркас, модели и красные тесты

- [x] T-14001 [arch] Контракт CONTRACT-014: модели, типы и nullability, статусы и `decision`, коды ошибок,
  idempotency key решения, `event_id`/`dedupe_key` и payload шести событий, правила этапов, выбывание, сроки,
  маркеры, точки расширения, URL — `backend/tests/CONTRACT-014.md` — (FR-820–850, NFR-746–749)
- [x] T-14002 [code] Точки расширения и открытый реестр действий: `approval_subjects`, `task_card_parts`,
  `TaskRef`, `TaskCardPart`; динамические схемы действий и обработчики из `Action`; шесть триггеров
  `approval_*` для `ticket`/`task`; подписи формы правила — `backend/apps/core/extensions.py`,
  `backend/apps/automation/services/validation.py`, `backend/apps/automation/services/actions/__init__.py`,
  `backend/apps/automation/forms.py`, `backend/apps/servicedesk/automation.py`, `backend/apps/tasks/automation.py`;
  ожидания `POINTS` (два новых имени в конце) — `backend/tests/test_extensions.py`,
  `test_feed_boundaries.py`, `test_feed_core_changes.py`, `test_instructions_core_changes.py`,
  `test_kb_boundaries.py`, `test_lists_boundaries.py`, `test_messenger_boundaries.py`,
  `test_messenger_core_changes.py`, `test_messenger_deploy.py`, `test_sd_boundaries.py`,
  `test_tasks_core_changes.py` — (FR-824, FR-843)
- [x] T-14003 [code] Каркас `approvals`, `INSTALLED_APPS` (вставить `apps.approvals` после `apps.org`, вне
  хвоста — хвостовые проверки не меняются), маршруты, модели `ApprovalTemplate`,
  `ApprovalStage`, `ApprovalStageParticipant`, `ApprovalRoute`, `ApprovalStageRun`,
  `ApprovalAssignment`, `ApprovalNotice`, `ApprovalEvent`, ограничения и индексы, миграция `approvals 0001`;
  заготовка `stand.py` — `backend/apps/approvals/**`, `backend/config/settings.py`, `backend/config/urls.py` —
  (FR-821, FR-825, FR-826, FR-850)
- [x] T-14004 [code] Красные тесты шаблонов, запуска и снимка, включая неизменность статуса и отсутствие
  новых задач — `backend/tests/test_approvals_templates.py`, `test_approvals_route.py`,
  `test_approvals_snapshot.py` — (FR-820–823, FR-825–826, FR-849)
- [x] T-14005 [code] Красные тесты этапов, решений и отмены, включая выбывание текущего участника
  `sequential` — `backend/tests/test_approvals_stages.py`, `test_approvals_parallel.py`,
  `test_approvals_decisions.py`, `test_approvals_cancel.py` — (FR-827–834, FR-838)
- [x] T-14006 [code] Красные тесты заданий, сроков, уведомлений, событий, автоматики, доступа и журнала —
  `backend/tests/test_approvals_queue.py`, `test_approvals_deadlines.py`, `test_approvals_notify.py`,
  `test_approvals_events.py`, `test_approvals_automation.py`, `test_approvals_access.py`,
  `test_approvals_journal.py` — (FR-835–846, NFR-747, NFR-748)

## Этап 2 — шаблоны и запуск

- [x] T-14010 [code] Служба шаблонов: проверка названия, этапов, режимов, сроков и участников, запрет `any`
  для `sequential`, запрет пустого этапа и дублей, сохранение и выключение; повторная проверка при запуске —
  `backend/apps/approvals/services/templates.py` — (FR-820–822)
- [x] T-14011 [code] Адаптеры субъектов: заявка и задача — загрузка, блокировка, краткая справка без ФИО,
  адреса и текста переписки заявителя, `can_view`/`can_work` (для задачи — `tasks.can_change_status`),
  ссылка; регистрация `approval_subjects` —
  `backend/apps/servicedesk/approval.py`, `backend/apps/servicedesk/extensions.py`,
  `backend/apps/tasks/approval.py`, `backend/apps/tasks/extensions.py` — (FR-823, FR-839–841)
- [x] T-14012 [code] Запуск и снимок: проверка субъекта (закрытая заявка, удалённая или завершённая задача)
  и шаблона, разрешение `employee`/`unit_head`/`queue_head` через `unit_heads`/`heads_of_unit`, исключение
  неактивных, схлопывание дублей, создание маршрута и заданий, `route_exists` по частичному индексу —
  `backend/apps/approvals/services/routes.py`, `backend/apps/org/services/structure.py` —
  (FR-823–826, FR-833)
- [x] T-14013 [code] Страница шаблонов: список, форма этапов и участников, создание, правка, выключение,
  маршруты в `urls.py` — `backend/apps/approvals/forms.py`, `views/templates.py`, `views/__init__.py`,
  `urls.py`, `templates/approvals/templates/` — (FR-820–822, FR-846)
- [x] T-14014 [code] Блок «Согласования»: часть карточки заявки, точка `task_card_parts`, общий контекст
  карточки задачи, кнопка запуска и активный маршрут —
  `backend/apps/approvals/extensions.py`, `backend/apps/tasks/services/card.py`,
  `backend/apps/tasks/views/pages.py`, `backend/apps/tasks/views/actions.py`,
  `backend/apps/tasks/views/comments.py`, `backend/templates/tasks/_card.html`,
  `backend/apps/approvals/templates/approvals/_start.html` — (FR-823, FR-847)
- [x] T-14015 [code] Зелёные тесты шаблонов, запуска и снимка; e2e запуска из карточки —
  прогон `test_approvals_templates.py`, `test_approvals_route.py`, `test_approvals_snapshot.py`,
  `backend/tests/e2e/test_t14_start.py` — (FR-820–823, FR-825–826, FR-846, FR-847, FR-849)

## Этап 3 — этапы и решения

- [x] T-14020 [code] Переходы этапов: последовательный этап по одному участнику (включая передачу задания
  следующему при выбывании текущего), параллельный `all`/`any`, отмена остальных, завершение маршрута и
  история; маршрут не меняет статус и не создаёт задачи —
  `backend/apps/approvals/services/stages.py` — (FR-827, FR-828, FR-831, FR-832, FR-849)
- [x] T-14021 [code] Решения: порядок «блокировка маршрута → задания», идемпотентность до проверки
  завершённости, комментарии, проверка участника, `200`/`409`, `assignment_cancelled`, ровно одно решение и
  один журнал; отказ/возврат — `stage_completed` → `rejected`/`returned` без `completed` —
  `backend/apps/approvals/services/routes.py` — (FR-829–831, FR-838, NFR-747)
- [x] T-14022 [code] Отмена инициатором и администратором, идемпотентный повтор, запрет отмены завершённого
  маршрута — `backend/apps/approvals/services/routes.py` — (FR-834)
- [x] T-14023 [code] Доступ: видимость маршрута для инициатора, участника, ответственного, руководителя и
  наблюдателя; краткая справка; право решения — `backend/apps/approvals/services/access.py` —
  (FR-830, FR-839–841)
- [x] T-14024 [code] Страница маршрута: этапы, задания, история, форма решения, кнопка отмены, режим
  наблюдателя; маршруты в `urls.py` — `backend/apps/approvals/views/routes.py`, `urls.py`,
  `templates/approvals/routes/` — (FR-829–834, FR-841)
- [x] T-14025 [code] Зелёные тесты этапов, решений, гонки 20 POST и доступа; e2e маршрута —
  прогон `test_approvals_stages.py`, `test_approvals_parallel.py`, `test_approvals_decisions.py`,
  `test_approvals_cancel.py`, `test_approvals_access.py`, `backend/tests/e2e/test_t14_route.py` —
  (FR-827–834, FR-838–841, NFR-747)

## Этап 4 — задания, сроки, уведомления, события, журнал

- [x] T-14030 [code] «Мои задания»: служба ожидающих и просроченных, страница, меню (пункт «Мои задания»,
  порядок 4, без отдельного права), сортировка и пустое состояние; e2e списка; регрессия числа пунктов
  меню — `backend/apps/approvals/services/queue.py`, `views/my.py`, `urls.py`, `apps.py`,
  `templates/approvals/my/`, `backend/tests/e2e/test_t14_my.py`,
  `backend/tests/test_tasks_deploy.py`, `test_tasks_core_changes.py`, `test_lists_access.py`,
  `test_instructions_deploy.py`, `test_messenger_deploy.py` — (FR-835, FR-837, FR-848)
- [x] T-14031 [code] Сроки: `due_at` от старта этапа, напоминание только при сроке дальше 24 часов, маркеры
  `reminder`/`overdue`, `approvals_tick` раз в минуту, догон после простоя, выбывание с блокировкой
  маршрутов по `id` и пересчётом `sequential` (следующий участник или завершение по уже полученным
  согласованиям) и `parallel` через `stages` —
  `backend/apps/approvals/services/notices.py`, `backend/apps/approvals/services/routes.py`,
  `backend/apps/approvals/services/stages.py`, `backend/apps/approvals/tasks.py`, `backend/config/cron.py`;
  регрессия числа заданий `cron` — `backend/tests/test_lists_deploy.py`, `test_tasks_deploy.py`,
  `test_notify_deploy.py`, `test_kb_deploy.py`, `test_sd_deploy.py`, `test_tasks_core_changes.py`,
  `test_instructions_deploy.py`, `test_instructions_core_changes.py`, `test_feed_deploy.py`,
  `test_messenger_deploy.py` — (FR-836, FR-837, NFR-748)
- [x] T-14032 [code] Пять видов уведомлений (`available` по праву/участию, не `mandatory`) и получатели
  (участник, инициатор), внешний текст без ПДн и комментария; каталог 43 → 48 видов и таблицы умолчаний —
  `backend/apps/approvals/notify_kinds.py`, `backend/apps/approvals/apps.py`,
  `backend/tests/test_notify_catalog.py`, `test_notify_catalog_2.py`, `test_notify_prefs.py`,
  `backend/tests/e2e/test_e04_my_settings.py`, `backend/tests/e2e/test_e12_criteria.py` —
  (FR-842, FR-845, NFR-749)
- [x] T-14033 [code] События шести видов, `event_id`/`dedupe_key`, публикация после commit, подписки
  автоматики, действие `start_approval` с пропусками `author_inactive`, `template_absent`,
  `template_disabled`, `subject_mismatch`, `subject_closed`, `route_exists`, `no_participants` через
  `ActionSkip`; регрессия числа действий в правиле —
  `backend/apps/approvals/services/events.py`, `backend/apps/approvals/subscriptions.py`,
  `backend/apps/approvals/action.py`, `backend/apps/approvals/apps.py`,
  `backend/tests/test_automation_rules.py` — (FR-824, FR-843)
- [x] T-14034 [code] Журнал: коды запуска, этапа, решения, возврата, отмены и шаблона; русские подписи;
  отсутствие комментария и ПДн — `backend/apps/approvals/services/journal.py`,
  `backend/apps/approvals/audit_labels.py`, `backend/apps/approvals/apps.py` — (FR-844, FR-845, NFR-749)
- [x] T-14035 [code] Зелёные тесты заданий, сроков, уведомлений, событий, автоматики, журнала; прогон
  каталога уведомлений и e2e списка — прогон `test_approvals_queue.py`, `test_approvals_deadlines.py`,
  `test_approvals_notify.py`, `test_approvals_events.py`, `test_approvals_automation.py`,
  `test_approvals_journal.py`, `test_notify_catalog.py`, `backend/tests/e2e/test_t14_my.py` —
  (FR-824, FR-835–845, NFR-748, NFR-749)

## Этап 5 — права, карточки, стенд, 360 px

- [x] T-14040 [code] Полная проверка прав: шаблоны только `automation.manage`, запуск `can_work`, решение
  только участник, наблюдатель без кнопок, административная отмена — `backend/apps/approvals/services/access.py`,
  `views/templates.py`, `views/routes.py` — (FR-840, FR-841, FR-846)
- [x] T-14041 [code] Блоки карточек: активный маршрут, этап, срок и ссылка на историю на странице заявки и
  задачи; e2e карточки — `backend/apps/approvals/extensions.py`,
  `backend/tests/e2e/test_t14_card.py` — (FR-847)
- [x] T-14042 [code] Сброс стенда `approvals.stand_reset`: регистрация после `core`/`org`, до `servicedesk`,
  чтобы хвостовые позиции не менялись; очистка e2e-данных — `backend/apps/approvals/stand.py`,
  `backend/apps/approvals/apps.py` — (FR-850)
- [x] T-14043 [arch] Миграции и регрессия на базе среза 013: `approvals 0001`, старые заявки, задачи, правила
  и уведомления; маршрут не меняет статус и не создаёт задачи; без reset; отчёт о прогоне —
  `crm-work/slice014/stage5/migrations/` — (FR-849, FR-850)
- [x] T-14044 [code] 360×640: «Мои задания», маршрут, форма шаблона и карточка с блоком «Согласования» без
  горизонтальной прокрутки страницы, внутренняя прокрутка блоков; стили, e2e mobile —
  `backend/apps/approvals/templates/approvals/`, `backend/static/approvals/`,
  `backend/tests/e2e/test_t14_mobile.py` — (FR-848, NFR-749)

## Этап 6 — приёмка

- [x] T-14050 [arch] Полный серверный прогон `systemd-run --user` с `*.status`/`*.log`/`*.exit` —
  все тесты — (FR-820–850)
- [x] T-14051 [arch] Браузеры `test_t14_*`: Chromium, Firefox, Edge, Яндекс.Браузер — (FR-820–850,
  NFR-749)
- [x] T-14052 [arch] Нагрузка NFR-746/747: Locust 100 пользователей, 6 минут, прогрев 1 минута; 110 000 заявок,
  20 000 задач, 2 000 сотрудников, 300 шаблонов, 5 000 маршрутов (1 000 активных), 25 000 заданий
  (10 000 ожидающих, 200 со сроками); p95 «Мои задания»/маршрут ≤500 мс, решение ≤300 мс, ошибок <1%;
  гонка запуска и решения; `assertNumQueries` ≤10/≤15 и `EXPLAIN` индексов —
  `crm-work/slice014/stage6/load/` — (NFR-746, NFR-747)
- [x] T-14053 [человек] Ручной проход: шаблон, запуск, решения, возврат, отмена, «Мои задания», карточки,
  360 px — `crm-work/slice014/stage6/manual/checklist.md` — (FR-820–850)
- [x] T-14054 [code] Исправления находок приёмки — по отчёту T-14053 — (все)
- [x] T-14055 [arch] Финальный прогон и отчёт `docs/reviews/TASKS-014.md` — (все)
