---
id: TASKS-010
вид: задачи
статус: утверждён
версия: 2
зависит_от: PLAN-010
основан_на: PLAN-010 sha256:0c1d373ab12e0af6dfe439b793dd568d27ab97b33e527193307a0dee2083893e
подпись: Максим | 2026-11-23T16:35+03:00 | sha256:ea65fdca31ca80c2a8895d68c677d044ae54321e35559d40702d6f4fb1b84cb2
---

# Задачи среза 010: Поручения

Формат строки: `- [ ] T-NNNN [P] [исполнитель] описание — файлы или тест — (FR-NNN / NFR-NNN)`.
`[P]` — можно делать параллельно с соседними задачами (нет общих файлов). Исполнитель — `code` (код и тесты),
`arch` (архитектура и финальные), `человек` (подписи и ручные проходы). Модель под роль выбирается по действующему
порядку владельца, а не по ярлыку.

Источники: SPEC-010 (FR-700…723, NFR-720…729), PLAN-010 v2. Решения, которых нет в плане, собраны в разделе
«Решения Opus по задачам».

Как читать и исполнять:
- **Нумерация.** Этап 1 — T-10001…T-10010, Этап 2 — T-10101…T-10124 плюс T-10150/T-10159/T-10160, Этап 3 —
  T-10201…T-10217 и T-10260, Этап 4 — T-10300…T-10309.
- **Порядок.** Этапы идут подряд. Внутри этапа задача без `[P]` начинается после предыдущих; `[P]` не зависит от
  соседей и не правит с ними общих файлов.
- **Тест-на-требование.** В Этапе 2 у каждого теста в скобках FR/NFR; запись `файл::имя` — связь
  T-NNNN → требование → тест. Браузерные сценарии — `backend/tests/e2e/test_t10_*.py`.
- **Красный прежде зелёного.** Этап 3 не начинается до T-10160: тесты падают, причина записана.
- **Правки прежних тестов — одна задача T-10111** по точному «было / стало», каждая с разрешения владельца.
- **Один автор на общий файл.** `apps/instructions/urls.py` — T-10001 создаёт, T-10007 наполняет; `apps.py`/
  `extensions.py` — T-10001, T-10008; данные установки — только T-10003/T-10008.
- **Размер.** Задача — не больше полудня одного исполнителя; задание агенту — не больше ~50 вызовов; файл
  тестов — не больше ~25 тестов (больше — `_2`).
- **Партии.** Этап 3 идёт партиями; после каждой партии — весь серверный набор тестов.
- **Вне перечня.** Если в Этапе 3 падает прежний тест вне таблицы T-10111 — остановка, решение Opus, запись в
  решения; тест не ослаблять.
- **Секреты.** В отчётах только `***`; ПДн и пароли в задачи не попадают.

## Этап 1 — каркас, контракт, помощники, правки ядра

- [x] T-10001 [arch] каркас `apps.instructions` по PLAN-010 «Где живёт код»: `apps.py`, `models.py`, `urls.py`,
  `extensions.py`, `notify_kinds.py`, `audit_labels.py`, `texts.py`, `stand.py`, `tasks.py`, пакеты `services/`,
  `views/`, `migrations/`, `templates/instructions/`, `static/instructions/`; `"apps.instructions"` после
  `"apps.tasks"`; пустой include под `is_installed`; сбор тестов растёт — `backend/apps/instructions/`,
  `backend/config/settings.py`, `backend/config/urls.py` — (FR-700…723)
- [x] T-10002 [P] [arch] `Purpose.INSTRUCTION = "instruction"` в конце перечня и миграция `core 0014`; тест
  «последнее назначение — instruction» — `backend/apps/core/models/files.py`,
  `backend/apps/core/migrations/0014_storedfile_instruction_purpose.py`, `backend/tests/test_instructions_models.py::test_purpose_instruction_is_last` — (NFR-722)
- [x] T-10003 [arch] права `instructions.use`, `instructions.assign` — строки `core.Permission`, выданы
  «Администратору портала» и «Сотруднику ИТ»; миграция `core 0015` от `0014`, идемпотентна; тест роли без
  `instructions.assign` — `backend/apps/core/migrations/0015_instructions_permissions.py`,
  `backend/tests/test_instructions_core_changes.py` — (FR-702, FR-703)
- [x] T-10004 [P] [arch] `CONTRACT-010`: адреса, зацепки `data-*`, коды и тексты отказов (`title_range`,
  `basis_required`, `deadline_past`, `assignee_forbidden`, `report_forbidden`, `report_empty`, `report_limit`,
  `transfer_forbidden`, `transfer_state`, `close_forbidden`, `ladder_invalid`, `file_too_big`, `file_type`,
  `file_missing`, `retention_range`), ответы HTMX и обычных запросов, подпись `instructions.reminder_failed` —
  `backend/tests/CONTRACT-010.md` — (все FR)
- [x] T-10005 [P] [arch] помощники серверных тестов: `make_instruction`, `add_coexecutor`, `make_basis`,
  `add_report_date`, `submit_report`, `add_part`, `accept_report`, `return_report`, `request_transfer`,
  `decide_transfer`, `reminders_of`, `registry_rows`, `discipline_rows`, роли прав-данных; без импорта кода
  приложения на уровне модуля — `backend/tests/support_instructions.py` — (все FR)
- [x] T-10006 [arch] помощники e2e: `open_instructions`, `create_instruction`, `open_card`, `submit_report`,
  `accept_report`, `return_report`, `request_transfer`, `decide_transfer`, `close_instruction`, `open_discipline`, `export_excel`, `check_360`;
  локаторы — только зацепки CONTRACT-010 — `backend/tests/e2e/helpers_instructions.py` — (FR-700…723)
- [x] T-10007 [arch] маршруты и задания (после T-10001): `urls.py` — адреса контракта; `config/cron.py` —
  `instructions_reminders` (`*/5 * * * *`, 300), `instructions_digest` (`*/15 * * * *`, 300),
  `instructions_retention` (`43 23 * * *`, 600) под `is_installed`; страницы-заглушки реестра и настроек —
  `backend/apps/instructions/urls.py`, `views/`, `backend/config/cron.py` — (FR-711, FR-712, NFR-729)
- [x] T-10008 [arch] стенд (после T-10001 и T-10003): `instructions` в `stand_reset` (поручения, участники,
  даты, отчёты, части, файлы, переносы, напоминания, настройки) регистрацией последней; команда
  `e2e_instructions_seed` (виды основания, три поручения); тест сброса —
  `backend/apps/instructions/stand.py`, `extensions.py`, `management/commands/e2e_instructions_seed.py`,
  `backend/tests/test_instructions_stand.py` — (все FR)
- [x] T-10009 [P] [arch] nginx: `location ~ ^/instructions/files/$` с `client_max_body_size 25m` и повтором
  `proxy_*` в `deploy/nginx.conf` и `nginx.prod.conf` — `deploy/nginx.conf`, `deploy/nginx.prod.conf` — (NFR-722)
- [x] T-10010 [arch] статика: `instructions.css`, `instructions.js` и их подключение в `_assets.html` для
  `/instructions/` и `/settings/instructions/`; CSP-заголовки страниц — `backend/static/instructions/`,
  `backend/templates/_assets.html` — (NFR-725)

## Этап 2 — красные серверные тесты и правки прежних тестов

- [x] T-10101 [code] модели и ограничения: поля/пределы, `original_deadline`, уникальность дат и частей,
  один итоговый отчёт, части к дате, один pending-перенос, `stage` напоминаний и `nulls_distinct`,
  `InstructionSettings` — `test_instructions_models.py` — (FR-700, 703…705, 708, 709, 723, NFR-724, NFR-729)
- [x] T-10102 [code] права и видимость: кто ставит, контролёр, руководители только чтение, администратор 404,
  увольнение/блокировка, смена контролёра, увольнение исполнителя и назначение нового — `test_instructions_access.py` — (FR-702, 703, 719, 721, 722)
- [x] T-10103 [code] создание: название, текст, основание, срок, состав, журнал, виды основания — `test_instructions_create.py`, `test_instructions_basis.py` — (FR-700…704)
- [x] T-10104 [code] отчётные даты: неделя/месяц/квартал, 31-е, 29.02, начало ряда, дата = срок, обрезка,
  ранний отчёт и пересборка, схлопывание совпадающих, отказ прошедших дат — `test_instructions_dates.py` — (FR-705)
- [x] T-10105 [code] отчёты и части: часть к дате до сводного отчёта, сохранение при возврате, приёмка/возврат,
  итоговый отчёт, отмена напоминаний, обязательный текст и до 10 файлов — `test_instructions_reports.py` — (FR-706, 707, 723)
- [x] T-10106 [code] снятие с контроля: только контролёр, только с принятым итоговым отчётом, pending-перенос —
  `test_instructions_close.py`, после снятия отчёты не принимаются — (FR-707)
- [x] T-10107 [code] переносы: запрос, один pending, согласование/отказ, история, исходный срок, пересчёт —
  `test_instructions_transfers.py` — после `closed_at` запросы не принимаются, уведомление о решении — (FR-708)
- [ ] T-10108 [code] напоминания: семь порогов, границы длины, прошлые, `None`, проверка тихих часов перед
  отправкой, идемпотентность, отмена при отправке/закрытии; напоминания об отчётных датах r3/r1 и
  просрочка отчёта со следующего рабочего дня; правка лестницы по маршруту `/instructions/<id>/ladder/` (право постановщика/контролёра) — только будущие
  `pending`, `sent` не трогаются — `test_instructions_reminders.py` — (FR-709, 710, 711, NFR-724)
- [ ] T-10109 [code] реестр: пресеты, «кроме собственных», фильтры, поиск, сортировки, страницы, SQL —
  `test_instructions_registry.py` — статус по ближайшей незакрытой дате/сроку, приоритет «Просрочено», нет
  ручной установки, страницы 20/50, порядок «срок, затем изменение» — (FR-713, 717, NFR-721)
- [ ] T-10110 [code] дисциплина и Excel: период, подразделение, две шкалы, последний перенос, открытые
  просроченные, «основной узел», администратор, `.xlsx` — `test_instructions_discipline.py` — те же числа в Excel, SQL параметрами — (FR-714, 715, NFR-721)
- [ ] T-10111 [arch] **правки прежних тестов — только с разрешения владельца**, по одной строке таблицы
  PLAN-010 «Прежние тесты, которые придётся поправить» (cron 24→27, `APPS_TAIL`, меню 18→20, права 20→22,
  Purpose 7→8, каталог 30→40, `stand_reset`, nginx 3→4, «без задач», e2e каталога и меню): каждая с диффом
  «было / стало» — `backend/tests/` — (все FR)

  Полная таблица (каждая строка — отдельный вопрос владельцу, дифф «было / стало»):

  | № | Файл::тест | Было | Стало | Почему |
  |---|---|---|---|---|
  | 1 | `test_feed_deploy.py::test_cron_module_has_twenty_register_calls` | 24 | 27 | cron |
  | 2 | `test_feed_deploy.py::test_previous_eighteen_cron_entries_keep_names_and_minutes` | 6 сверх прежних | 9 | cron |
  | 3 | `test_kb_deploy.py::test_purge_trash_...` | 24 | 27 | cron |
  | 4 | `test_lists_deploy.py::test_cron_module_has_eighteen_register_calls` | 24 | 27, имя | cron |
  | 5 | `test_notify_deploy.py::test_cron_notify_tick_...` | 24 | 27 | cron |
  | 6 | `test_sd_deploy.py::test_cron_has_eight_new_jobs_...` | 24 | 27 | cron |
  | 7 | `test_tasks_deploy.py::test_cron_has_24_registers...` | 24 | 27, имя | cron |
  | 8 | `test_messenger_deploy.py::test_cron_has_24_registers...` | 24 | 27, имя | cron |
  | 9 | `support_feed.APPS_TAIL`, `test_feed_deploy.py::test_feed_is_last...`, `test_kb_deploy.py::test_knowledge_and_search...`, `test_lists_deploy.py::test_lists_is_in...`, `test_notify_deploy.py::test_notify_is_last...`, `test_messenger_deploy.py::APPS_TAIL`/`test_messenger_is_last...` | 8 элементов, tasks последний | 9, instructions последний | INSTALLED_APPS |
  | 10 | `test_tasks_deploy.py::APPS_TAIL`/`test_tasks_is_last...` | tasks последний | instructions последний | INSTALLED_APPS |
  | 11 | `test_org_permissions.py::test_menu_...` | 18 пунктов, order до 70 | 20, «Поручения» 3, «Настройки поручений» 66 | меню |
  | 12 | `test_tasks_deploy.py::test_menu_items...`, `test_messenger_deploy.py::test_admin_menu...` | 18 | 20 | меню |
  | 13 | `test_lists_access.py::test_menu_item_lists...` | 18 | 20 | меню |
  | 14 | `test_permissions.py::test_three_builtin_roles...`, `test_org_permissions.py::test_three_new_permissions...`, `test_sd_access.py::test_all_tickets...` | 20 прав | 22, `PERMISSIONS_010` | права |
  | 15 | `test_feed_seed.py::test_seed_on_slice_006_base...`, `::test_portal_has_twenty_permissions_after_seed` | 18/20 | 20/22 | права |
  | 16 | `test_lists_seed.py::test_portal_has_twenty_permissions_after_seed` | 19/20 | 21/22 | права |
  | 17 | `test_feed_core_changes.py`, `test_messenger_core_changes.py`, `test_messenger_boundaries.py`, `test_messenger_deploy.py`, `test_tasks_core_changes.py`, `test_tasks_models.py` (Purpose) | 7, последнее `task` | 8, последнее `instruction` | Purpose |
  | 18 | `test_notify_catalog.py` (TABLE/счётчики), `test_notify_catalog_2.py`, `test_notify_prefs.py`, `test_messenger_notify_2.py` | 30 видов | 40, десять `instructions.*` | каталог |
  | 18а | `test_messenger_deploy.py::test_slice_numbers_nineteen_points_thirty_kinds_seven_purposes_and_order_61` | `len(catalog) == 30` | 40, имя | каталог |
  | 19 | `test_feed_stand.py::test_feed_stand_reset...`, `test_lists_stand.py::test_lists_stand_reset...`, `test_messenger_stand.py::test_stand_reset_runs...`, `test_tasks_stand.py::test_tasks_stand_reset...`, `test_kb_deploy.py::test_stand_reset_knowledge...` | tasks последний | instructions последний, сдвиг индексов | stand_reset |
  | 20 | `test_feed_deploy.py::test_nginx_dev/prod...`, `test_messenger_deploy.py::test_nginx_has_three_25m...`, `test_deploy_files.py::test_nginx_body_size...` | три 25m | четыре | nginx |
  | 21 | `test_tasks_core_changes.py::test_previous_menu_search_card...`, `test_tasks_boundaries.py::test_without_tasks...`/`test_search_and_card...` | без tasks | «без tasks и instructions», 16 пунктов | зависимость |
  | 22 | e2e `test_e04_my_settings.py`, `test_e12_criteria.py`, `test_d08_heads.py`, `test_o04_find_colleague.py` | без видов/пунктов | +10 видов, +2 пункта | приёмка |

  `backend/tests/` — (все FR)
- [ ] T-10112 [code] связь с задачами: создание задачи (нужно `tasks.use`), видимость связанной задачи,
  уникальность связи, завершение задачи не меняет статус поручения — `test_instructions_tasks.py` — (FR-716)
- [ ] T-10113 [code] уведомления: десять видов, получатели, приоритет, принятие/возврат, внешний текст,
  письмо по настройке, `still_relevant` — `test_instructions_notify.py` — (FR-711, NFR-723)
- [ ] T-10114 [code] сводка: первый рабочий день, содержание, `cache.add`, пустая/повтор, неделя —
  `test_instructions_digest.py` — сроки и отчётные даты на 30 дней и просроченные — (FR-712, NFR-724)
- [ ] T-10115 [code] настройки: умолчания лестницы, срок хранения 1–10, второй шаг, журнал, справочник видов,
  права администратора — `test_instructions_settings.py` — (FR-701, 709, NFR-729)
- [ ] T-10116 [code] файлы: 20 МБ, ClamAV, карантин, exe/архивы, 10 на отчёт/часть, недоступность до проверки,
  чужая ссылка, X-Accel, регистрация `file_purposes` для `instruction` — `test_instructions_files.py` — (NFR-722)
- [ ] T-10117 [code] журнал и история: коды, «было/стало», части и переносы, закрытие, хранение, подписи —
  `test_instructions_audit.py` — включая `instructions.reminder_failed` — (FR-718, NFR-727)
- [ ] T-10118 [code] хранение: только закрытые, календарное вычитание, файлы/части/связи, журнал, идемпотентность,
  неснятые не удаляются — `test_instructions_retention.py` — (NFR-729)
- [ ] T-10119 [code] границы: импорты только публичных служб, модели `core`/`tasks`, отключение вместе с задачами,
  отсутствие прямого импорта `tasks.models` — `test_instructions_boundaries.py` — (конституция)
- [ ] T-10120 [code] данные установки: виды основания, `InstructionSettings`, идемпотентность — `test_instructions_seed.py` — (FR-701, 709, NFR-729)
- [ ] T-10121 [code] развёртывание: маршруты, cron 27, меню 20, статика/CSP, nginx четыре 25m, права, профиль —
  `test_instructions_deploy.py` — меню 3/66, три задания с расписанием, русские тексты и Europe/Moscow — (NFR-722, 723, 725, 726, 728)
- [ ] T-10122 [code] изменения ядра: Purpose, права, settings/urls/cron, `stand_reset`, прежнее поведение без
  приложения — `test_instructions_core_changes.py` — (FR-700…723)
- [ ] T-10123 [code] стенд: `stand_reset`, порядок, `e2e_instructions_seed` — `test_instructions_stand.py` — (все FR; PLAN-010 ссылается на T-10124, читать как T-10123)
- [ ] T-10124 [code] браузерные сценарии: `test_t10_01_registry.py`, `test_t10_02_create.py`, `test_t10_03_report.py`, `test_t10_04_return.py`, `test_t10_05_transfer.py`,
  `test_t10_06_reminders.py`, `test_t10_07_discipline.py`, `test_t10_08_tasks.py`, `test_t10_09_rights.py`, `test_t10_10_mobile.py` —
  `backend/tests/e2e/` — (FR-700…723)
- [ ] T-10150 [code] нагрузочный профиль: `fill_instructions.py` (1 000 поручений/100 сотрудников), `InstructionUser`,
  проверка наличия в deploy-тесте — `backend/tests/load/`, `test_instructions_deploy.py` — (NFR-720, 728)
- [ ] T-10159 [arch] стенд для прогонов (после разрешения владельца): копия, сборка, миграции, перезапуск,
  health — `crm-work/slice010/stage2/stand/` — (все FR)
- [ ] T-10160 [arch] **красный прогон**: весь серверный набор, каждый новый тест падает, кроме тестов Этапа 1 (`Purpose`, права, стенд), причина записана; прежние
  зелёные или перечислены в T-10111 — `crm-work/slice010/stage2/red/`, `docs/reviews/TASKS-010.md` — (все FR)

## Этап 3 — партии кода

**Партия 1 — модели, настройки, права.**
- [ ] T-10201 [code] модели и миграция `instructions 0001` (назначение/права уже в T-10002/T-10003), служба настроек и
  справочника, `views/settings.py` — `backend/apps/instructions/models.py`, `migrations/`, `services/settings.py`,
  `services/basis.py` — зелёные: `test_instructions_models`, `test_instructions_basis`, `test_instructions_settings`
  (часть) — (FR-700…705, 709, NFR-729)
- [ ] T-10202 [code] `services/access.py`: кто ставит, видимость (участники + цепочка), руководители только чтение,
  администратор 404, увольнение/блокировка — `services/access.py`, `services/instructions.reassign`, подписка `core.user_dismissed` в `apps.py` — зелёные: `test_instructions_access`,
  `test_instructions_core_changes` (часть) — (FR-702, 703, 719, 721, 722)

**Партия 2 — создание, даты, отчёты.**
- [ ] T-10203 [code] создание/правка и журнал: `services/instructions.py`, `views/actions.py`, формы и шаблоны —
  зелёные: `test_instructions_create`, `test_instructions_audit` (часть) — (FR-700…704, 718)
- [ ] T-10204 [code] отчётные даты: `services/dates.py`, пересборка, ранний отчёт — зелёный:
  `test_instructions_dates` — (FR-705)
- [ ] T-10205 [code] отчёты и части: `services/reports.py`, `views/reports.py`, карточка, решения — зелёные:
  `test_instructions_reports`, `test_instructions_audit` (часть) — (FR-706, 707, 718, 723)
- [ ] T-10206 [code] переносы и снятие: `services/transfers.py`, `services/instructions.close`, `views/transfers.py` —
  зелёные: `test_instructions_transfers`, `test_instructions_close` — (FR-707, 708)

**Партия 3 — реестр, напоминания, уведомления.**
- [ ] T-10207 [code] реестр и страницы: `services/registry.py`, `views/pages.py`, шаблоны — зелёный:
  `test_instructions_registry` — (FR-713, 717, NFR-721)
- [ ] T-10208 [code] напоминания: `services/reminders.py`, задание, лестница, маршрут `/instructions/<id>/ladder/`, тихие часы — зелёный:
  `test_instructions_reminders` — (FR-709, 710, NFR-724)
- [ ] T-10209 [code] уведомления и сводка: `notify_kinds.py`, `services/notify_rules.py`, `services/digest.py`,
  задание сводки — зелёные: `test_instructions_notify`, `test_instructions_digest` — (FR-711, 712, NFR-723)
- [ ] T-10210 [code] дисциплина и Excel: `services/discipline.py`, `services/excel.py`, `views/pages.py` — зелёный:
  `test_instructions_discipline` — (FR-714, 715)

**Партия 4 — файлы, журнал, хранение, задачи.**
- [ ] T-10211 [code] файлы: `services/files.py`, `views/files.py`, `file_purposes`, X-Accel — зелёный:
  `test_instructions_files` — (NFR-722)
- [ ] T-10212 [code] журнал и история: `audit_labels.py`, блок истории в карточке — зелёные:
  `test_instructions_audit`, `test_instructions_close` (часть) — (FR-718, NFR-727)
- [ ] T-10213 [code] срок хранения: `services/retention.py`, задание, настройки и журнал — зелёные:
  `test_instructions_retention`, `test_instructions_settings` — (FR-701, NFR-729)
- [ ] T-10214 [code] связь с задачами: `services/instructions.link_task`, `InstructionTask`, карточка — зелёный:
  `test_instructions_tasks` — (FR-716)

**Партия 5 — стенд, деплой, границы, 360.**
- [ ] T-10215 [code] 360 px и запасные пути: `instructions.css`, карточка/реестр/дисциплина — e2e `t10_10` —
  (NFR-725)
- [ ] T-10216 [code] стенд: проверка `stand.py`/`extensions.py`/`e2e_instructions_seed` после Stage 1 — зелёные: `test_instructions_seed`, `test_instructions_stand` — (все FR)
- [ ] T-10217 [code] деплой и границы: `urls.py`, `config/cron.py`, `_assets.html`, меню, nginx, `boundaries` —
  зелёные: `test_instructions_deploy`, `test_instructions_boundaries`, `test_instructions_core_changes` —
  (NFR-722, 723, 725, 728)
- [ ] T-10260 [arch] зелёная сборка: весь серверный набор зелёный, ни один тест не ослаблен; правки прежних — только
  T-10111 с разрешения; отчёт `docs/reviews/TASKS-010.md` — (все FR)

## Этап 4 — приёмка

- [ ] T-10300 [arch] полный серверный прогон на PostgreSQL (`systemd-run --user`), сверка с красным, регрессия —
  `docs/reviews/TASKS-010.md` — (все FR)
- [ ] T-10301 [arch] проход в браузере по 10 сценариям (4 круга), консоль без CSP и ошибок —
  `docs/reviews/TASKS-010.md`, раздел «Проход в браузере» — (FR-700…723)
- [ ] T-10302 [arch] приёмка Playwright из `CRM/.venv`, сброс стенда перед кругом, `t10` в 4 браузерах —
  `docs/reviews/TASKS-010.md`, раздел «Приёмка» — (NFR-725)
- [ ] T-10303 [P] [arch] ворота: `sdd.py`, tools, конституция, `check_secrets`, `verify_vendor`, `git diff --check` —
  `docs/reviews/TASKS-010.md`, раздел «Ворота» — (конституция)
- [ ] T-10304 [arch] нагрузка NFR-720 — только после отдельного решения владельца, на остывшей машине: L1
  `InstructionUser`, L2 все классы, p95 500 мс — `crm-work/slice010/stage4/load/`, `docs/reviews/TASKS-010.md`, раздел «Нагрузка» — (NFR-720, 728)
- [ ] T-10305 [arch] наблюдения на стенде (с разрешения владельца): отказ слоя, повтор задания, ночная уборка —
  `docs/reviews/TASKS-010.md`, раздел «Наблюдения» — (FR-711, NFR-729)
- [ ] T-10306 [arch] инварианты по диффу: модуль-приложение (зависимость от tasks), настройка-без-кода, ПДн,
  аудит, SQL, стек, секреты — `docs/reviews/TASKS-010.md`, раздел «Инварианты» — (конституция)
- [ ] T-10307 [arch] прохождение требований: таблица FR-700…723 и NFR-720…729 → тест → результат; NFR-720 только
  после T-10304 — `docs/reviews/TASKS-010.md`, раздел «Требования», `[x]` в этом файле — (все FR)
- [ ] T-10308 [человек] ручной проход критерия «поручение с основанием и отчётом за минуту»; отметка — `docs/reviews/TASKS-010.md`, раздел «Критерий успеха» —
  (FR-700, 706)
- [ ] T-10309 [человек] принять срез, подписать, `git push`; если после подписи менялся текст задач — подписать
  заново — владелец — (инвариант «спека-прежде-кода»)

## Решения Opus по задачам

1. **Номера.** T-10001…T-10010, T-10101…T-10124 + T-10150/T-10159/T-10160, T-10201…T-10217 + T-10260,
   T-10300…T-10309. Имена файлов — `test_instructions_<тема>.py`; e2e — `test_t10_<тема>.py` (10 файлов).
2. **Порядок T-10111.** Правки прежних тестов — одна задача после T-10002/T-10003/T-10007, до T-10160; каждая
   строка таблицы PLAN-010 — отдельный вопрос владельцу с диффом.
3. **Красный прогон.** T-10160 после стенда T-10159; если стенд нельзя обновить — копия с записью в отчёт.
4. **Зависимость.** `instructions` требует `tasks`; тест «без задач» снимает оба приложения; отдельного
   `is_installed` без задач нет.
5. **Части.** `InstructionReportPart.date` — отчётная дата; сводный отчёт ответственного — `InstructionReport`
   (`date=NULL` только итоговый); части переживают возврат.
6. **Напоминания.** `stage`, уникальность только `pending`, `nulls_distinct=False`; `sent` не трогаются; отправка
   отчёта отменяет `pending` этой даты.
7. **Уведомления.** Десять видов; приоритет на запуске; `still_relevant`; сводка по неделе; письмо — настройка.
8. **Дисциплина.** «Основной узел» — первый не-корневой по `path`, иначе корень; последний согласованный перенос
   с `decided_at <= closed_at`; администратор исключён.
9. **Файлы.** Один `InstructionFile` (`kind` basis/report/part), без `Instruction.basis_file`.
10. **Лестница.** JSON `offsets` 1–60, `due`, `overdue`; маршрут `POST /instructions/<id>/ladder/`.
11. **Права.** `instructions.use`/`instructions.assign` — данные; видимость по структуре дополнительна к праву;
    дисциплина — право + структура, администратор исключён.
12. **Стенд.** `stand_reset` поручений — последняя регистрация, вызывается первой, стирает свои таблицы до задач.
13. **Модели ролей.** Ярлыки `[code]`/`[arch]` — роли; модель — по порядку владельца; ревью — другой моделью.
14. **Детали, которых нет в плане.** Коды отказов и тексты — T-10004; имена помощников — T-10005/T-10006; команда
    `e2e_instructions_seed` — T-10008.
15. **Нагрузка.** Профиль — T-10150 в Этапе 2; замер — T-10304 после решения владельца.
16. **Статика.** CSP и `_assets` — T-10010; проверка — T-10121.
17. **Без задач.** Поведение «без задач» в прежних тестах обновляется вместе с `instructions` (T-10111).
18. **Приёмка.** T-10307 заполняет таблицу требований; NFR-720 не считается выполненным до T-10304.

## Таблица покрытия требований

| Требование | Задачи | Тесты |
|---|---|---|
| FR-700 поля и основание | T-10201, T-10203 | models, create |
| FR-701 справочник | T-10008, T-10115, T-10201, T-10213 | basis, settings, seed |
| FR-702 кто ставит | T-10003, T-10202 | access |
| FR-703 контролёр | T-10003, T-10202 | access |
| FR-704 исполнитель/соисполнители | T-10203 | create |
| FR-705 отчётные даты | T-10204 | dates |
| FR-706 отчёт | T-10205 | reports |
| FR-707 снятие | T-10205, T-10206 | close |
| FR-708 перенос | T-10206 | transfers |
| FR-709 лестница | T-10208 | reminders |
| FR-710 тихие часы | T-10208 | reminders |
| FR-711 уведомления | T-10209 | notify |
| FR-712 сводка | T-10209 | digest |
| FR-713 реестр | T-10207 | registry |
| FR-714 дисциплина | T-10210 | discipline |
| FR-715 Excel | T-10210 | discipline |
| FR-716 задачи | T-10214 | tasks |
| FR-717 статусы | T-10205, T-10207 | registry, reports |
| FR-718 журнал/история | T-10203, T-10212 | audit |
| FR-719 404 | T-10202 | access |
| FR-720 360 px | T-10215 | e2e t10_10 |
| FR-721 видимость | T-10202 | access |
| FR-722 увольнение/смена | T-10202, T-10203 | access |
| FR-723 части | T-10205 | reports |
| NFR-720 p95 | T-10150, T-10304 | нагрузка |
| NFR-721 SQL | T-10109, T-10110, T-10207, T-10210 | registry, discipline |
| NFR-722 файлы | T-10009, T-10211 | files, deploy |
| NFR-723 внешний текст | T-10209 | notify |
| NFR-724 идемпотентность | T-10208, T-10209, T-10213 | reminders, digest, retention |
| NFR-725 360/браузеры | T-10010, T-10215, T-10302 | e2e 4 круга |
| NFR-726 русский/Москва | T-10121, T-10217 | deploy (русские тексты, Europe/Moscow) |
| NFR-727 журнал | T-10212 | audit |
| NFR-728 профиль | T-10150, T-10217 | deploy |
| NFR-729 хранение | T-10213 | retention |
