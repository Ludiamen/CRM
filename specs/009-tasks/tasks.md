---
id: TASKS-009
вид: задачи
статус: утверждён
версия: 4
зависит_от: PLAN-009
основан_на: PLAN-009 sha256:9e1d9e7b218b04e99240a70b006b83c8b01c1b4c0e2c3c3c46848eafdf8bb519
подпись: Максим | 2026-11-22T09:39+03:00 | sha256:4e3b83c223f01934bd14589c5f8dcfa1bb3cea336f8f9cfd9879272e153ac057
---

# Задачи среза 009

Формат строки: `- [ ] T-NNNN [P] [исполнитель] описание — файлы или тест — (FR-NNN / NFR-NNN)`.
`[P]` — можно делать параллельно с соседними задачами (нет общих файлов). Исполнитель — sonnet (код и тесты),
opus (архитектурные и финальные), человек (подписи и ручные проходы). Модель под каждую роль выбирается по
действующему порядку владельца (`~/.config/opencode/AGENTS.md`, `go-plus-routing.md`), а не по этим ярлыкам.
Задачи собраны только из SPEC-009 (14 сценариев, FR-674…699, NFR-710…719) и PLAN-009. Решения, которых план
не принимал, собраны в разделе «Решения Opus по задачам».

Как читать и исполнять:
- **Нумерация.** Этап 1 — T-9001…T-9012, Этап 2 — T-9101…T-9125 (плюс профиль нагрузки T-9150, стенд T-9159 и красный прогон T-9160),
  Этап 3 — T-9201…T-9217 и зелёная сборка T-9260, Этап 4 — T-9300…T-9309.
- **Порядок.** Этапы идут подряд. Внутри этапа задача без `[P]` начинается, когда закончены все предыдущие;
  `[P]` не зависит от соседей и не правит с ними общих файлов (решение 11 и таблица общих файлов Этапа 1).
  Этап 3 идёт партиями; после каждой партии — весь серверный набор тестов.
- **Тест-на-требование.** В Этапе 2 у каждого теста в скобках стоит FR или NFR; запись `файл::имя_теста` и
  есть связь T-NNNN → требование → тест. Сценарии 1–10 браузерного прохода — `backend/tests/e2e/test_t09_*.py`.
  У каждой задачи Этапа 3 названы файлы и тесты Этапа 2, которые она делает зелёными; файл зеленеет целиком с
  **последней** названной задачей.
- **Красный прежде зелёного.** Этап 3 не начинается, пока не выполнен T-9160: тесты падают, причина записана.
  Тест не ослабляют; правят код. Правка теста — только по правилам ниже.
- **Правки прежних тестов — одна задача.** Тесты и помощники срезов 001–008 меняет только T-9011, по точному
  «было / стало» из таблицы этой задачи. Каждая правка — с разрешения владельца, по одному тесту, с диффом;
  разрешение спрашивает Opus, исполнитель правит после ответа. Если в Этапе 3 упадёт прежний тест вне
  перечня, его не ослабляют: остановка, решение Opus, запись в раздел решений.
- **Один автор на общий файл.** `backend/tests/CONTRACT-009.md` пишет только T-9005, `tests/support_tasks.py` —
  T-9006, `tests/e2e/helpers_tasks.py` — T-9007. В Этапе 1 общие файлы: `apps/tasks/urls.py` — T-9001 создаёт,
  T-9009 наполняет (последовательно); `apps/tasks/{apps,extensions}.py` — T-9001, T-9010 (последовательно);
  данные установки — только T-9004. В Этапе 3 общие файлы кода правит одна задача за раз (решение 11).
- **Размер.** Задача — не больше полудня одного исполнителя; задание агенту — не больше ~50 вызовов; файл
  тестов — не больше ~25 тестов (больше — `_2`).
- **Секреты.** В отчётах, логах и сообщениях — только `***`; ПДн и пароли в задачи не попадают.

## Этап 1 — каркас, контракт, помощники, правки ядра

- [x] T-9001 [opus] каркас `apps.tasks` по PLAN-009 «Где живёт код»: `apps.py` (register_all пустой),
  `extensions.py`, `models.py`, пустые `urls.py`, `notify_kinds.py`, `audit_labels.py`, пакеты `services/`,
  `views/`, `migrations/`, `templates/tasks/`, `static/tasks/`; `"apps.tasks"` последним в `INSTALLED_APPS`;
  пустой `include("apps.tasks.urls")` под `apps.is_installed`; сбор тестов растёт без ошибок —
  `backend/apps/tasks/`, `backend/config/settings.py`, `backend/config/urls.py` — (FR-674…699)
- [x] T-9002 [P] [opus] `Purpose.TASK = "task"` в конце перечня и миграция `core 0012`; тест добавления значения —
  `backend/apps/core/models/files.py`, `backend/apps/core/migrations/0012_storedfile_task_purpose.py`,
  `backend/tests/test_tasks_models.py::test_purpose_task_is_last` — (FR-693)
- [x] T-9003 [P] [opus] `org.services.structure.managed_units(user)` — узлы с отметкой руководителя или
  заместителя и все вложенные, **без обычных членств**; тесты «рядовой участник вышестоящего узла не
  управляет вложенными», «заместитель управляет как руководитель», «уволенный — пусто» —
  `backend/apps/org/services/structure.py`, `backend/tests/test_org_structure.py` (добавление) — (FR-677, FR-678)
- [x] T-9004 [opus] данные установки (после T-9002): права `tasks.use`, `tasks.assign` — строки
  `core.Permission`, выданы роли «Сотрудник ИТ»; миграция `core 0013_tasks_permissions` с зависимостью от
  `0012`; тест «роль без `tasks.assign` не ставит задачу другому» — `backend/apps/core/migrations/0013_tasks_permissions.py`,
  `backend/tests/test_tasks_permissions.py` — (FR-676, FR-678)
- [x] T-9005 [P] [opus] `CONTRACT-009`: адреса, зацепки `data-*`, коды и тексты отказов (`title_range`,
  `deadline_past`, `assignee_forbidden`, `status_forbidden`, `move_forbidden`, `comment_forbidden`,
  `files_limit`, `file_type`, `file_too_big`), ответы HTMX и обычных запросов, подпись
  `tasks.reminder_failed` — `backend/tests/CONTRACT-009.md` — (все FR)
- [x] T-9006 [P] [opus] помощники серверных тестов: `make_task`, `add_member`, `make_column`, `make_category`,
  `move`, `board_rows`, `reminders_of`, `post_comment`, роли для прав-данных; без импорта кода приложения на
  уровне модуля — `backend/tests/support_tasks.py` — (все FR)
- [x] T-9007 [P] [opus] помощники e2e: `open_tasks`, `create_task`, `open_card`, `move_card`, `board_titles`,
  `plan_columns`, `comment`, `upload_task_file`, `check_360`; локаторы — только зацепки CONTRACT-009 —
  `backend/tests/e2e/helpers_tasks.py` — (FR-680…684, FR-699)
- [x] T-9008 [P] [opus] SortableJS 1.15.6 в `static/vendor` с `LICENSE-sortable` и разделом `VERSIONS.md`;
  `tools/verify_vendor.py` — пакет `sortablejs@1.15.6`; подключение `tasks.css`, `tasks.js` и
  `vendor/Sortable-1.15.6.min.js` (defer) для `/tasks/` и `/settings/tasks/` — `backend/static/vendor/`,
  `backend/static/tasks/`, `backend/templates/_assets.html`, `tools/verify_vendor.py` — (NFR-711, NFR-716)
- [x] T-9009 [opus] маршруты и запуск (после T-9001): `urls.py` — адреса контракта; `config/cron.py` —
  `tasks_reminders` (`*/5 * * * *`, 300 с), `tasks_digest` (`*/15 * * * *`, 300 с), `tasks_retention`
  (`42 23 * * *`, 600 с) под `is_installed`; страницы-заглушки списка и настроек —
  `backend/apps/tasks/urls.py`, `backend/apps/tasks/views/`, `backend/config/cron.py` — (FR-685, FR-696)
- [x] T-9010 [opus] стенд (после T-9001 и T-9004): `tasks` в `stand_reset` (задачи, участники, колонки,
  категории, напоминания, комментарии, файлы) регистрацией в `extensions.register_all`; команда
  `e2e_tasks_seed` (категории, три задачи) для сценариев; тест сброса — `backend/apps/tasks/stand.py`,
  `backend/apps/tasks/extensions.py`, `backend/tests/test_tasks_stand.py` — (все FR)
- [x] T-9011 [opus] **правки прежних тестов — только с разрешения владельца**, по одному тесту, диффом
  «было / стало». Перечень (каждая строка — отдельный вопрос; при падении теста вне перечня — остановка):
  | № | Файл::тест | Было | Стало | Почему |
  |---|---|---|---|---|
  | 1 | `test_feed_core_changes.py::test_stored_file_purpose_feed_is_last_and_previous_values_unchanged` | полный перечень `Purpose.choices`, `values[-1] == "messenger"` | семь значений, последнее `"task"` | T-9002 |
  | 2 | `test_messenger_core_changes.py::test_purpose_messenger_choice_last_and_migration_0011_depends_on_0010` и `support_messenger.PURPOSES_008` | `messenger` последним, шесть значений | `task` последним, семь | T-9002 |
  | 3 | `test_sd_deploy.py::test_cron_has_eight_new_jobs_with_expected_queues_and_poll_mailbox_every_minute` | `register` 21 | 24 | T-9009 |
  | 4 | `test_kb_deploy.py::test_purge_trash_is_registered_in_cron_with_45_23_maintenance_timeout_600` | 21 | 24 | T-9009 |
  | 5 | `test_notify_deploy.py::test_cron_notify_tick_interval_30_queue_notify_timeout_120` | 21 | 24 | T-9009 |
  | 6 | `test_lists_deploy.py::test_cron_module_has_eighteen_register_calls` | 21 (имя теста «восемнадцать») | 24, имя теста поправить | T-9009 |
  | 7 | `test_feed_deploy.py::test_cron_module_has_twenty_register_calls` | 21 (имя «двадцать») | 24, имя поправить | T-9009 |
  | 8 | `test_messenger_deploy.py::test_cron_has_21_registers_and_messenger_retention_55_23_maintenance` | 21 | 24, имя поправить | T-9009 |
  | 9 | `test_feed_stand.py::test_feed_stand_reset_is_registered_last_and_runs_first` | feed второй с конца, messenger последний | tasks последний, feed третий с конца; порядок вызова с tasks | T-9010 |
  | 10 | `test_messenger_stand.py::test_stand_reset_runs_last_and_before_feed` | messenger последний | tasks последний | T-9010 |
  | 11 | `test_messenger_deploy.py::test_slice_numbers_nineteen_points_twenty_two_kinds_six_purposes_and_order_61` | 22 вида, шесть назначений | 30 видов, семь назначений, points 19 | T-9002, T-9201, T-9212 |
  | 12 | `test_messenger_notify_2.py::test_catalog_has_22_kinds_and_two_messenger_rows` | 22 | 30 | T-9212 |
  | 13 | `test_notify_catalog.py::test_catalog_contains_eight_kinds_from_three_modules` | «ровно двадцать два вида» | 30, имя поправить | T-9212 |
  | 14 | `test_notify_catalog.py::test_catalog_kind_codes_titles_and_modules_match_plan_table` | таблица видов | +8 видов задач | T-9212 |
  | 15 | `test_notify_prefs.py::test_table_rows_show_kind_title_and_module` | список строк и модулей | +8 строк «Задачи» | T-9212 |
  | 16 | `test_notify_catalog_2.py::test_my_notifications_page_push_column_carries_permission_hint_and_script_hook_server_does_not_read_permission` | `push_cells == 16` | 24 | T-9212 |
  | 17 | `test_permissions.py::test_three_builtin_roles_with_initial_permissions` | «все восемнадцать прав» | 20 прав, состав «Сотрудника ИТ» | T-9004 |
  | 18 | `test_org_permissions.py::test_three_new_permissions_and_initial_distribution` | «всего восемнадцать прав» | 20 | T-9004 |
  | 19 | `test_feed_seed.py::test_seed_on_slice_006_base_creates_post_all_and_moderate_permissions_with_russian_names` | `count() == 16` | 18 | T-9004 |
  | 20 | `test_feed_seed.py::test_portal_has_eighteen_permissions_after_seed` | в тесте 16 до seed и 18 после | 18 и 20, имя поправить | T-9004 |
  | 21 | `test_lists_seed.py::test_portal_has_sixteen_permissions_after_seed` | в тесте 17, после seed 18 | 19 и 20, имя поправить | T-9004 |
  | 22 | `test_org_permissions.py::test_menu_staff_structure_calendar_items_by_permission` | без «Задачи» | +«Задачи» (order 2, право `tasks.use`), +«Настройки задач» (order 65) | T-9217 (меню), T-9004 (право) |
  | 23 | `test_messenger_deploy.py::test_admin_menu_has_16_items_with_messenger_second_and_settings_order_64` | 16 пунктов | 18 | T-9217 |
  | 24 | `test_lists_access.py::test_menu_item_lists_has_order_8_empty_permissions_and_is_visible_by_sees_section` | 16 пунктов | 18 | T-9217 |
  | 25 | `test_search_providers_2.py::test_knowledge_disabled_has_no_articles_group_others_work` (и соседние) | списки провайдеров без «tasks» | +«Задачи» (order 62) | T-9214 |
  | 26 | `test_kb_boundaries.py` (providers/titles) | без «tasks» | +«Задачи» | T-9214 |
  | 27 | `test_messenger_deploy.py::test_nginx_has_two_25m_locations_and_repeated_proxy_directives` | два `25m` | три | T-9012 |
  | 28 | `test_deploy_files.py::test_nginx_body_size_6m_and_protected_location_internal_with_headers` | перечень location и «вне location формы и ответа один 6m» | +`/tasks/files/` 25m, правило перечня | T-9012 |
  | 29 | `tests/support_feed.py` (`APPS_TAIL`), `test_messenger_deploy.py` (локальный `APPS_TAIL`) | `"apps.messenger"` последним | `"apps.tasks"` последним | T-9001 |
  | 29а | `test_feed_deploy.py::test_feed_is_last_in_installed_apps_after_search` | хвост `INSTALLED_APPS` срезом `[-7:]`, последний `apps.messenger` | последний `apps.tasks`, срез расширен | T-9001 |
  | 29б | `test_lists_deploy.py` (индекс), `test_kb_deploy.py` (срез `[-6:]`), `test_notify_deploy.py` (индекс) | хвост без задач | +`apps.tasks` в конце, срезы/индексы поправить | T-9001 |
  | 29в | `test_messenger_deploy.py::test_messenger_is_last_in_installed_apps` | messenger последним | tasks последним | T-9001 |
  | 29г | `test_lists_stand.py`, `test_kb_deploy.py` (порядок `stand_reset`), `test_feed_boundaries.py`, `test_messenger_boundaries.py` | порядок регистрации сброса без задач | tasks регистрируется последним и **вызывается первым** (сброс идёт обратным порядком), feed и messenger сдвигаются | T-9010 |
  | 30 | `test_pages_stage3b.py` — если при исполнении найдётся проверка перечня статики срезов | без задач | +`tasks.js`, `tasks.css` | T-9008; если теста нет — строку снять |
  | 31 | e2e `test_e04_my_settings.py` (строки каталога `SD_KINDS + … + MESSENGER_KINDS_E2E`), `test_e12_criteria.py` (разделы каталога), меню в `test_d08_heads.py`, `test_o04_find_colleague.py` | без видов задач и пунктов «Задачи» | +виды задач и «Задачи»/«Настройки задач» | T-9212 (виды), T-9217 (меню); проверить при исполнении |
  — `backend/tests/` — (FR-674…699)
- [x] T-9012 [P] [opus] nginx: `location ~ ^/tasks/files/$` с `client_max_body_size 25m` и повтором
  `proxy_*` (образец мессенджера) в `deploy/nginx.conf` и `deploy/nginx.prod.conf`; проверка — строка 27–28
  T-9011 — `deploy/nginx.conf`, `deploy/nginx.prod.conf` — (NFR-713)

## Этап 2 — красные серверные тесты

- [x] T-9101 [sonnet] модели и ограничения: поля и пределы, номер = `pk`, статусы, уникальность участников,
  колонок, категорий, частичный уникальный индекс автоматических напоминаний, `TaskSettings` одна строка,
  индексы — `test_tasks_models.py` — (FR-674, FR-675, FR-679, FR-682)
- [x] T-9102 [sonnet] правило структуры: `managed_units` и `manages`; рядовой участник вышестоящего узла не
  управляет вложенными; заместитель равен руководителю; цепочка вышестоящих; уволенный — пусто —
  `test_tasks_access.py` — (FR-677, FR-678)
- [x] T-9103 [sonnet] права: создание себе и другому (право `tasks.assign` + структура), правка полей и
  статуса, цель `manages` — узел **исполнителя** (руководитель узла постановщика чужую задачу не правит),
  **удаление** (автор, руководитель, заместитель узла исполнителя, второй шаг `confirm=1`, посторонний —
  403/404), чужая задача 404, роль без права — отказ — `test_tasks_permissions.py` — (FR-676, FR-678, FR-695)
- [x] T-9104 [sonnet] видимость: автор, участники, руководители и заместители автора и исполнителя по
  цепочке, администратор не видит, `deleted_at` исключает, перевод — на момент просмотра —
  `test_tasks_visibility.py` — (FR-677, FR-686)
- [x] T-9105 [sonnet] создание: название 1–300, описание до 10 000, срок-дата, состав без повторов и без
  исполнителя, категория и колонка по умолчанию, журнал `tasks.created` — `test_tasks_create.py` — (FR-674, FR-675)
- [x] T-9106 [sonnet] правка и статусы: поля по правам, «Начать»/«Завершить»/«Ждёт», возврат из «Готово»
  (исполнитель, соисполнитель, постановщик, руководитель/заместитель), журнал «было/стало», `updated_at` —
  `test_tasks_edit.py` — (FR-678, FR-679)
- [x] T-9107 [sonnet] список: пресеты «Мои», «Поставленные мной», «Задачи подчинённых», «В работе»,
  «Просрочены» (календарная дата, без «Готово»), фильтры и сортировки из белого списка, страницы 20/50,
  постоянное число SQL — `test_tasks_list.py` — (FR-685, FR-686, NFR-712)
- [x] T-9108 [sonnet] доски: «Стадии» (четыре колонки, числа, «Готово»), «Сроки» (группы, дальше 7 дней нет,
  «Готово» нет), «Мой план» (три колонки при первом входе), «Категории» («Без категории») —
  `test_tasks_boards.py` — (FR-680…684)
- [x] T-9109 [sonnet] перенос: права на поле, «Сегодня»/«На неделе» (пятница строго после сегодня)/«Без
  срока», запрет «Просрочены», «Мой план» — только владелец, «Без категории», пересчёт напоминаний при смене
  срока — `test_tasks_move.py` — (FR-681, FR-684, FR-690)
- [x] T-9110 [sonnet] «Мой план»: CRUD колонок владельцем, удаление переносит в первую, чужая доска только
  для чтения (руководитель и заместитель), выбор колонки в карточке — только владельцу — `test_tasks_plan.py`
  — (FR-682)
- [x] T-9111 [sonnet] категории: справочник администратора, удаление снимает категорию, «Без категории»,
  перенос по правам — `test_tasks_categories.py` — (FR-683)
- [x] T-9112 [sonnet] напоминания: моменты (1 рабочий день, начало дня срока, праздник, просрочка со
  следующего рабочего дня), личные тихие часы own/none, лимит 10, «Отложить» от срабатывания, пересчёт при
  смене срока и состава, снятие при завершении/удалении, `None` из `next_start`, идемпотентность —
  `test_tasks_reminders.py` — (FR-687…690, NFR-715)
- [x] T-9113 [sonnet] уведомления: восемь видов, получатели по видам, цепочка вышестоящих, приоритет
  «подчинённого» при совмещении, о собственных действиях нет, внешний текст без названия и описания, письмо
  через 15 минут — `test_tasks_notify.py` — (FR-691, FR-692, NFR-714)
- [x] T-9114 [sonnet] сводка: один раз в день (атомарный `cache.add`), «горящие» (срок сегодня или скоро),
  получатели — руководитель и заместитель, повторный цикл без дублей — `test_tasks_digest.py` — (FR-691)
- [x] T-9115 [sonnet] комментарии: пишут все видящие, правка и мягкое удаление своего, серая запись, чужие
  нельзя, журнал без текста — `test_tasks_comments.py` — (FR-693, FR-694)
- [x] T-9116 [sonnet] файлы: 20 МБ, ClamAV, карантин, exe и архивы с паролем, до проверки недоступен, имя в
  `TaskFile.name`, 10 на комментарий, непривязанные старше 24 часов, чужая ссылка 404 —
  `test_tasks_files.py` — (FR-693, NFR-713)
- [x] T-9117 [sonnet] журнал: создание, изменение полей «было/стало», удаление минимальным снимком, правка и
  удаление комментария без текста, только дополнение — `test_tasks_audit.py` — (FR-694, FR-695, NFR-718)
- [x] T-9118 [sonnet] срок хранения: только удалённые, отсчёт от удаления, календарное вычитание (29 февраля),
  файлы и комментарии, идемпотентность, действующие не удаляются — `test_tasks_retention.py` — (FR-695, FR-696, NFR-715)
- [x] T-9119 [sonnet] поиск: группа «Задачи» (номер, название, описание, комментарии), только видимые, потолок
  300, слова параметрами — `test_tasks_search.py` — (FR-697, NFR-712)
- [x] T-9120 [sonnet] карточка сотрудника: раздел «Задачи» с видимыми смотрящему задачами, пусто для чужих —
  `test_tasks_card_section.py` — (FR-698)
- [x] T-9121 [sonnet] развёртывание: маршруты, cron три задания под `is_installed`, меню с правом
  `tasks.use`, статика и CSP, nginx 25m, права ролей, профиль `TaskUser` и `fill_tasks.py` на месте —
  `test_tasks_deploy.py` — (NFR-713, NFR-717, NFR-719)
- [x] T-9122 [sonnet] границы: `tasks` импортирует только публичные службы и точки, чужие модели напрямую не
  импортируются, приложение отключается без ошибок — `test_tasks_boundaries.py` — (конституция)
- [x] T-9123 [sonnet] изменения ядра: `Purpose.TASK`, `managed_units`, `settings/urls/cron`, права установки,
  прежнее поведение без `apps.tasks` — `test_tasks_core_changes.py` — (FR-674…699)
- [x] T-9124 [sonnet] установка и стенд: данные установки (категории, права), `stand_reset`, `e2e_tasks_seed` —
  `test_tasks_seed.py`, `test_tasks_stand.py` — (все FR)
- [x] T-9125 [sonnet] настройки задач: право `settings.portal`, срок 1–10, второй шаг, журнал
  `tasks.retention_changed`, влияние только на будущие уборки — `test_tasks_settings.py` — (FR-696)
- [x] T-9150 [sonnet] **нагрузочный профиль** (подготовка, не красный тест): `fill_tasks.py` (1 000 задач,
  100 сотрудников, статусы, сроки, категории, комментарии, напоминания; строка итога `fill_tasks: tasks=…`),
  класс `TaskUser` в `locustfile.py` (список, пресеты, карточка, доски, перенос, комментарий, поиск); проверка
  наличия — `test_tasks_deploy` (зеленеет вместе с T-9217) — `backend/tests/load/fill_tasks.py`,
  `backend/tests/load/locustfile.py` — (NFR-710, NFR-719)
- [x] T-9159 [opus] стенд для прогонов (после разрешения владельца): копия, сборка с `tasks`, миграции
  `core 0012` и `tasks 0001`, перезапуск, проверки здоровья — `crm-work/slice009/stage2/stand/` — (все FR)
- [x] T-9160 [opus] **красный прогон**: весь серверный набор; каждый новый тест падает, причина записана;
  прежние тесты зелёные или перечислены в T-9011 — `crm-work/slice009/stage2/red/`, отчёт
  `docs/reviews/TASKS-009.md` — (все FR)

## Этап 3 — партии кода

**Партия 1 — модели и настройки.**
- [x] T-9201 [sonnet] модели и миграция `tasks 0001`: `Task`, `TaskMember`, `TaskCategory`, `PlanColumn`,
  `TaskReminder` (частичный уникальный индекс), `TaskComment`, `TaskFile`, `TaskSettings`; служба настроек —
  `backend/apps/tasks/models.py`, `migrations/0001_initial.py`, `services/settings.py` — зелёные:
  `test_tasks_models`, `test_tasks_settings` (часть; целиком — у T-9213) — (FR-674…679, FR-682, FR-683,
  FR-687…690, FR-693, FR-696)

**Партия 2 — права, создание, правка.**
- [x] T-9202 [sonnet] `services/access.py` (+ `managed_units` из org), права ролей, видимость, права
  удаления — `backend/apps/tasks/services/access.py` — зелёные: `test_tasks_access`, `test_tasks_permissions`,
  `test_tasks_visibility` — (FR-676…678, FR-695)
- [x] T-9203 [sonnet] создание, правка полей и статусы, журнал: `services/tasks.py`, `views/actions.py`,
  формы и шаблоны — `backend/apps/tasks/services/tasks.py`, `views/actions.py`, `templates/tasks/` — зелёные:
  `test_tasks_create`, `test_tasks_edit`, `test_tasks_audit` (часть) — (FR-674, FR-675, FR-678, FR-679, FR-694)

**Партия 3 — список и доски.**
- [x] T-9204 [sonnet] список: пресеты, фильтры, сортировки, страницы, SQL параметрами —
  `services/list.py`, `views/pages.py`, `templates/tasks/_list.html`, `_row.html` — зелёный:
  `test_tasks_list` — (FR-685, FR-686, NFR-712)
- [x] T-9205 [sonnet] доска «Стадии»: колонки, числа, `[data-board]`, SortableJS, перенос статуса —
  `views/pages.py`, `services/boards.py`, `static/tasks/tasks.js`, `templates/tasks/_board.html` — зелёные
  (части): `test_tasks_boards`, `test_tasks_move` — (FR-679, FR-680, NFR-711)
- [x] T-9206 [sonnet] доска «Сроки»: группы, пятница, запрет «Просрочены», «Готово» и дальше 7 дней нет —
  `services/boards.py`, `views/pages.py` — зелёные (части): `test_tasks_boards`, `test_tasks_move` — (FR-681)
- [x] T-9207 [sonnet] «Мой план»: колонки (ленивые три), CRUD, перенос только владельцем, чужой план для
  чтения — `services/plan.py`, `views/plan.py`, `templates/tasks/_plan.html` — зелёный: `test_tasks_plan` —
  (FR-682)
- [x] T-9208 [sonnet] категории и доска категорий: справочник, перенос, «Без категории» —
  `services/categories.py`, `views/settings.py`, `templates/tasks/settings.html` — **зелёные целиком**:
  `test_tasks_boards`, `test_tasks_move`, `test_tasks_categories` — (FR-681…683)

**Партия 4 — карточка, комментарии, файлы.**
- [x] T-9209 [sonnet] карточка задачи: лента (журнал + комментарии), файлы, напоминания, выбор полей
  (запасной путь), права — `views/pages.py`, `templates/tasks/_card.html`, `_comment.html` — зелёные (части):
  `test_tasks_comments`, `test_tasks_edit` — (FR-674…678, FR-684)
- [x] T-9210 [sonnet] комментарии и файлы: `services/comments.py`, `services/files.py`, `views/files.py`,
  `Purpose.TASK`, ClamAV, X-Accel — `backend/apps/tasks/services/comments.py`, `files.py`, `views/files.py` —
  зелёные: `test_tasks_comments`, `test_tasks_files` — (FR-693, NFR-713)

**Партия 5 — напоминания, уведомления, сводка.**
- [x] T-9211 [sonnet] напоминания: `services/reminders.py`, личные тихие часы, задание, пересчёт, отложить,
  подпись `tasks.reminder_failed` — `backend/apps/tasks/services/reminders.py`, `tasks.py` — зелёный:
  `test_tasks_reminders` — (FR-687…690, NFR-715)
- [x] T-9212 [sonnet] виды уведомлений и получатели: `notify_kinds.py`, `services/notify_rules.py`,
  `services/digest.py`, задание сводки — `backend/apps/tasks/notify_kinds.py`, `services/notify_rules.py`,
  `services/digest.py` — зелёные: `test_tasks_notify`, `test_tasks_digest` — (FR-691, FR-692, NFR-714)

**Партия 6 — удаление, хранение, поиск, карточка сотрудника, 360.**
- [x] T-9213 [sonnet] удаление и срок хранения: `services/retention.py`, задание, настройки срока с журналом,
  файлы и комментарии, непривязанные — `backend/apps/tasks/services/retention.py`, `views/settings.py` —
  **зелёные целиком**: `test_tasks_retention`, `test_tasks_settings`, `test_tasks_audit` — (FR-694…696, NFR-715)
- [x] T-9214 [sonnet] поиск и карточка сотрудника: поставщик «Задачи», раздел карточки —
  `backend/apps/tasks/services/search.py`, `extensions.py` — зелёные: `test_tasks_search`,
  `test_tasks_card_section` — (FR-697, FR-698, NFR-712)
- [x] T-9215 [sonnet] 360 px и запасной путь: `tasks.css`, поведение доски и карточки —
  `backend/static/tasks/tasks.css` — зелёный: e2e `t10` — (FR-699, NFR-716)
- [x] T-9216 [sonnet] установка и стенд: данные установки, `stand_reset`, `e2e_tasks_seed` —
  `backend/apps/tasks/stand.py` — зелёные: `test_tasks_seed`, `test_tasks_stand` — (все FR)
- [x] T-9217 [sonnet] развёртывание и границы: маршруты, cron, меню, статика, CSP, nginx, границы импорта —
  `backend/apps/tasks/{urls,extensions}.py`, `config/cron.py` — зелёные: `test_tasks_deploy`,
  `test_tasks_boundaries`, `test_tasks_core_changes` — (NFR-713, NFR-717, NFR-719)
- [x] T-9260 [opus] зелёная сборка: весь серверный набор зелёный, ни один тест не ослаблен; правки прежних
  тестов — только из T-9011 с разрешения; отчёт — `docs/reviews/TASKS-009.md` — (все FR)

## Этап 4 — приёмка

- [x] T-9300 [opus] полный серверный прогон на PostgreSQL в контейнере (`systemd-run --user`): сверка красного
  T-9160 с зелёным, ни одного пропущенного/ослабленного; регрессия правополезных тестов
  (`test_permissions`, `test_sd_access`, `test_org_permissions`, `test_feed_home`, `test_notify_admin`,
  `test_org_structure`, `test_tasks_*`) — повтор после реализации; сводка в `docs/reviews/TASKS-009.md` —
  (FR-674…699, NFR-710…719)
- [x] T-9301 [opus] проход в браузере по 10 сценариям (после стенда): список, личная задача, подчинённый,
  «Стадии», «Сроки», «Мой план», категории, напоминания и уведомления, комментарии и файлы, 360 px и права;
  консоль без CSP и `oobErrorNoTarget`; снимки — вне git — `docs/reviews/TASKS-009.md`, раздел «Проход в
  браузере» — (FR-674…699, NFR-716)
- [x] T-9302 [opus] приёмка Playwright из `CRM/.venv` со сбросом стенда перед кругом: `t09` в четырёх
  браузерах (Chromium, Firefox, Edge, Яндекс) плюс прежние срезы `-k` в Chromium и Яндексе;
  `tests/e2e/conftest.py` не правится — `docs/reviews/TASKS-009.md`, раздел «Приёмка» — (NFR-716)
- [x] T-9303 [P] [opus] ворота: `sdd.py проверить`, `tools` unittest, конституция по `backend/` и `deploy/`,
  `check_secrets`, `verify_vendor` (SortableJS), `git diff --check` — `docs/reviews/TASKS-009.md` —
  (конституция)
- [x] T-9304 [opus] нагрузка NFR-710 — только после отдельного решения владельца, на остывшей машине по
  правилам T-7304: `fill_tasks.py` (1 000 задач, 100 сотрудников), L1 `TaskUser` и L2 все классы; p95 500 мс,
  известные дефекты NFR-612/707 и ограничение стенда — `crm-work/slice009/stage4/load/`,
  `docs/reviews/TASKS-009.md`, раздел «Нагрузка» — (NFR-710, NFR-719)
- [x] T-9305 [opus] наблюдения на стенде (с разрешения владельца, после копии): отказ слоя уведомлений,
  повтор задания напоминаний, ночная уборка на наполнении — `docs/reviews/TASKS-009.md` — (FR-691, FR-696)
- [x] T-9306 [opus] инварианты по диффу среза: модуль-приложение, настройка-без-кода (права-данные,
  категории, срок), интеграции-через-адаптеры (файлы, уведомления, поиск), аудит, ПДн, секреты-в-url, SQL,
  стек-интерфейс; изменённые файлы прежних срезов — по таблице плана — `docs/reviews/TASKS-009.md` —
  (конституция)
- [x] T-9307 [opus] прохождение требований: таблица FR-674…699 и NFR-710…719 → тест → результат → ссылка на
  реализацию; NFR-710 считается выполненным только после T-9304 (с согласия владельца); отметить `[x]` в этом
  файле, отчёт и перевод в «на-проверке» — `docs/reviews/TASKS-009.md` — (все FR)
- [x] T-9308 [человек] ручной проход критерия успеха «сотрудник ставит себе задачу и доводит до „Готово“ не
  дольше 1 минуты» с замером; отметка в отчёте — `docs/reviews/TASKS-009.md` — (FR-674, FR-679)
- [x] T-9309 [человек] принять срез по отчёту T-9307 и проходам T-9301, T-9308; если после подписи менялся
  текст задач — подписать заново; `git push` — владелец — (инвариант «спека-прежде-кода»)

## Решения Opus по задачам

1. **Номера и имена файлов.** T-9001…T-9012, T-9101…T-9125 + T-9150/T-9159/T-9160, T-9201…T-9217 + T-9260,
   T-9300…T-9309. Серверные тесты — `test_tasks_<тема>.py`; настройки — отдельный `test_tasks_settings.py`
   (26-й файл; в плане перечень «25 файлов» примерный, `test_tasks_t7200_regressions` из плана не нужен).
   Сценарии — `test_t09_<тема>.py` (10 файлов).
2. **Порядок T-9011.** Правки прежних тестов — одна задача после T-9002…T-9004; до T-9160, чтобы красный
   прогон не спотыкался о прежние перечни.
3. **Красный прогон.** T-9160 после стенда T-9159; если стенд нельзя обновить, прогон на копии с записью в
   отчёт.
4. **Правки тестов.** Каждая строка таблицы T-9011 — отдельный вопрос владельцу с диффом; без ответа задача
   стоит.
5. **Права-данные.** `tasks.use`/`tasks.assign` — строки `core.Permission` в данных установки, роль
   «Сотрудник ИТ»; структура — второй замок.
6. **Комментарии.** Своя `TaskComment` (правка/мягкое удаление); `core.Comment` не используется.
7. **Напоминания.** Персональный сдвиг `quiet.next_start`; `None` — pending до следующего цикла, при повторе
   отмена с предупреждением и подписью `tasks.reminder_failed`.
8. **Сводка.** Атомарный `cache.add`; «горящие» — срок сегодня или «скоро» в пределах рабочего дня.
9. **Файлы.** `TaskFile.file` — OneToOne; имя в `TaskFile.name`; непривязанные чистятся старше 24 часов.
10. **Срок хранения.** Календарное вычитание, 29.02→28.02; отсчёт от `deleted_at`; смена срока — журнал.
11. **Один автор на общий файл.** Этап 1: `urls.py` — T-9001 затем T-9009; `apps.py`/`extensions.py` —
    T-9001 затем T-9010; данные установки — только T-9004. Этап 3: `config/*`, `_assets.html`,
    `tasks.{js,css}`, `views/*`, `services/*`, `extensions.py` — по одной задаче в порядке партий.
12. **Стенд.** T-9010 готовит данные и сброс; T-9159 обновляет стенд с разрешения владельца; T-9260 —
    зелёная сборка до Этапа 4.
13. **Нагрузка.** Профиль — T-9150 в Этапе 2 (до стенда и красного прогона, как T-8150 среза 008);
    замер — T-9304 после решения владельца.
14. **Регрессия.** Базовая проверка правополезных тестов — перед T-9160 (T-9011 после правок), повтор — в
    T-9300; один и тот же список: `test_permissions`, `test_sd_access`, `test_org_permissions`,
    `test_feed_home`, `test_notify_admin`, `test_org_structure`, `test_tasks_*`.
15. **Модели ролей.** Ярлыки `[opus]`/`[sonnet]` — роли; модель — по порядку владельца; ревью — другой моделью.
16. **Детали, которых план не задал.** Коды отказов и тексты — T-9005; имена помощников — T-9006/T-9007;
    команда `e2e_tasks_seed` — T-9010; подпись `tasks.reminder_failed` — в `audit_labels`.
17. **Меню.** «Настройки задач» — order 65; он занят «Сервис-деском», порядок разрешается по `(order, title)`
    детерминированно («Настройки задач» перед «Сервис-деск»); коллизия записывается в CONTRACT-009 и дифф
    T-9011 (строка 22).
18. **Тесты прежних срезов, зависящие от каталога видов и прав.** Строка 11 ломается уже от T-9002 (шесть
    назначений) и окончательно после T-9212; строки 12–16 — после T-9212 (виды уведомлений); строки 17–21 —
    после T-9004 (права); строки 22–24, 31 (меню) — после T-9217, строка 31 в части видов — после T-9212;
    строки 25–26 — после T-9214; до этого тесты зелёные. Строка 16 (`push_cells == 24`) предполагает доступность всех восьми видов задач
    рядовому сотруднику — подтвердить при T-9212, иначе число иное.
19. **Проверка после реализации.** Отдельного раздела плана нет — проверка названа решением 14 и T-9300.
20. **Статика.** Строка 30 T-9011 условна: если проверки перечня статики не найдётся, строку снять.

## Таблица покрытия требований

| Требование | Тесты и приёмка | Реализация |
|---|---|---|
| FR-674 | T-9101, T-9105, T-9106 | T-9201, T-9203, T-9209 |
| FR-675 | T-9101, T-9105 | T-9201, T-9203 |
| FR-676 | T-9103 | T-9202 |
| FR-677 | T-9102, T-9104 | T-9202 |
| FR-678 | T-9102, T-9103, T-9106 | T-9202, T-9203 |
| FR-679 | T-9101, T-9106 | T-9201, T-9203 |
| FR-680 | T-9108, T-9109 | T-9205, T-9208 |
| FR-681 | T-9108, T-9109 | T-9206, T-9208 |
| FR-682 | T-9101, T-9108, T-9110 | T-9201, T-9207 |
| FR-683 | T-9101, T-9108, T-9111 | T-9201, T-9208 |
| FR-684 | T-9108, T-9109, T-9215 (e2e) | T-9205…T-9209, T-9215 |
| FR-685 | T-9107 | T-9204 |
| FR-686 | T-9104, T-9107 | T-9202, T-9204 |
| FR-687 | T-9112 | T-9211 |
| FR-688 | T-9112 | T-9211 |
| FR-689 | T-9112, T-9113 | T-9211, T-9212 |
| FR-690 | T-9109, T-9112 | T-9203, T-9211 |
| FR-691 | T-9113, T-9114 | T-9212 |
| FR-692 | T-9113 | T-9212 |
| FR-693 | T-9115, T-9116 | T-9209, T-9210 |
| FR-694 | T-9115, T-9117 | T-9203, T-9210 |
| FR-695 | T-9103, T-9117, T-9118 | T-9202, T-9213 |
| FR-696 | T-9118, T-9125 | T-9213, T-9201 |
| FR-697 | T-9119 | T-9214 |
| FR-698 | T-9120 | T-9214 |
| FR-699 | T-9215 (e2e), T-9301 | T-9215 |
| NFR-710 | T-9304 | T-9150 |
| NFR-711 | T-9301, T-9302 | T-9205, T-9215 |
| NFR-712 | T-9107, T-9119 | T-9204, T-9214 |
| NFR-713 | T-9116, T-9121 | T-9210, T-9012, T-9217 |
| NFR-714 | T-9113 | T-9212 |
| NFR-715 | T-9112, T-9118 | T-9211, T-9213 |
| NFR-716 | T-9301, T-9302 | T-9215 |
| NFR-717 | T-9121 | T-9217 |
| NFR-718 | T-9117 | T-9213 |
| NFR-719 | T-9121 | T-9150 |
