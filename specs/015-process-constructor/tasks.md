---
id: TASKS-015
вид: задачи
статус: на-проверке
версия: 1
зависит_от: PLAN-015
основан_на: PLAN-015 sha256:385b34e4fa712b02e1227344e86bf17cc0a8e2c98bb2a102d6de0a372aa597ce
---

# Задачи среза 015: Конструктор процессов

Формат строки: `- [ ] T-NNNNN [P] [исполнитель] описание — файлы или тест — (FR-NNN / NFR-NNN)`.
`[P]` означает, что задача не правит общий файл соседней задачи и может идти параллельно.
Исполнители: `code` — код и тесты, `arch` — контракт, стенд, прогоны и сверка, `человек` — ручной проход.

## Правила выполнения

- Этапы идут последовательно: этап 2 начинается после T-15005, этап 3 — после T-15014, этап 4 — после
  T-15024, этап 5 — после T-15034, этап 6 — после T-15044. Внутри этапа — порядок номеров задач.
- Ворота этапа — зелёный поднабор из PLAN-015, «Ворота этапов»; остальные красные тесты остаются красными
  до своих задач. Если тест будущего этапа стал зелёным раньше задачи, реализация опередила план: задача
  переносится, а результат не выдаётся за выполнение этапа.
- После каждого этапа — независимая проверка OpenAI `gpt-6.1-sol` (правило владельца 2026-11-28); следующий
  этап начинается после устранения находок проверяющего.
- Один автор на общий файл: `backend/apps/lists/models.py` и миграция — T-15002;
  `backend/apps/lists/services/access.py` — T-15005 (T-15020 дополняет последовательно);
  `backend/apps/lists/services/records.py` — T-15022; `backend/apps/lists/services/process.py` — T-15010
  (T-15011, T-15012, T-15013, T-15021, T-15040 дополняют последовательно);
  `backend/apps/lists/services/transitions.py` — T-15021 (T-15022, T-15042 дополняют);
  `backend/apps/lists/services/schedule.py` — T-15040 (T-15042 дополняет);
  `backend/apps/lists/views/settings.py` и `urls.py` — T-15010 (T-15011, T-15030, T-15032 добавляют
  последовательно); `backend/apps/lists/views/grid.py` и `services/grid.py` — T-15032;
  `backend/apps/lists/services/search.py`, `links.py`, `history.py`, `values.py`, `views/pickers.py`,
  `labels.py` — T-15020 (T-15033 дополняет последовательно);
  `backend/apps/lists/services/files.py`, `views/files.py`, `services/archive.py`, `services/imports.py`,
  `views/records.py` — T-15020 (T-15022, T-15023 дополняют последовательно);
  `backend/apps/lists/tasks.py`, `backend/config/cron.py`, `backend/tests/test_lists_deploy.py` — T-15041;
  `backend/apps/lists/audit_labels.py` — T-15042; шаблоны `backend/templates/lists/**` — по этапам.
- Тесты одной базы — строго последовательно; красные тесты T-15003 и T-15004 запускаются по одному.
- Общие тестовые файлы: `test_lists_process.py` — T-15003 (T-15010, T-15012, T-15014 только правят код и
  запускают); `test_lists_process_access.py` — T-15003 (T-15005, T-15020 запускают); `test_lists_process_required.py`
  — T-15003 (T-15013, T-15022, T-15024 запускают); `test_lists_process_move.py` — T-15003 (T-15021, T-15024
  запускают); `test_lists_process_board.py`, `test_lists_process_grid.py`, `test_lists_process_schedule.py`,
  `test_lists_process_journal.py` — T-15004; последующие задачи правят код, а не чужие тестовые файлы, кроме
  добавления недостающих проверок по своей задаче с отметкой в отчёте.
- Регрессионные ожидания чужих срезов: `test_lists_access`, `test_lists_grid`, `test_lists_grid_2`,
  `test_lists_export`, `test_lists_imports`, `test_lists_imports_2`, `test_lists_imports_3`, `test_lists_files`,
  `test_lists_links`, `test_lists_history`, `test_lists_search`, `test_lists_unique`, `test_lists_archive`,
  `test_lists_records`, `test_lists_records_2`, `test_lists_tickets`, `test_lists_deploy`,
  `test_lists_boundaries` — T-15043; `test_lists_deploy` дополнительно T-15041 (счётчик cron и функции
  `apps.lists.tasks`).
- Хвостовые проверки `INSTALLED_APPS` и `stand_reset` не правятся: нового приложения и сброса нет.
- Данные стенда не сбрасываются; шаблоны и процессы по умолчанию не создаются. Секреты — только `***`;
  ПДн в тесты и отчёты не попадают, используются синтетические данные.
- Если владелец ответит на форму 2026-11-28 иначе, чем записанные рекомендации, работа останавливается:
  SPEC-015 и PLAN-015 правятся и подписываются заново, код по старым решениям не пишется.

## Этап 1 — контракт, модели, красные тесты и права

- [ ] T-15001 [arch] Контракт CONTRACT-015: модели, поля и nullability, статусы процесса и стадий, коды
  ошибок (`stage_required`, `stage_forbidden`, `stage_changed`, `version_conflict`, `template_absent`),
  ключ идемпотентности `(record, base_version, to_stage_key)`, итоговое состояние полей, расписание и ключ
  периода, действия журнала, URL, тест-план — `backend/tests/CONTRACT-015.md` — (FR-851–892, NFR-750–753)
- [ ] T-15002 [code] Модели `ListProcess`, `ProcessStage`, `ProcessStageAccess`, `ProcessStageField`,
  `StageMove`, `ProcessLaunch` и поле `Record.stage`; миграция `lists 0003` только добавляющая; ограничения
  и индексы — `backend/apps/lists/models.py`, `backend/apps/lists/migrations/0003_process.py` — (FR-851–856,
  890, 892)
- [ ] T-15003 [code] Красные тесты A: настройка процесса, автор, включение и повторное включение, стадии,
  права стадии, обязательные поля, переход, идемпотентность, удаление стадии и история — `backend/tests/test_lists_process.py`,
  `test_lists_process_access.py`, `test_lists_process_required.py`, `test_lists_process_move.py` — (FR-851–874)
- [ ] T-15004 [code] Красные тесты B: доска, таблица, выгрузка, загрузка, поиск, расписание, журнал —
  `backend/tests/test_lists_process_board.py`, `test_lists_process_grid.py`, `test_lists_process_schedule.py`,
  `test_lists_process_journal.py` — (FR-875–887, NFR-750–752)
- [ ] T-15005 [code] Права стадии: `stage_scope`, `record_condition`, `can_read_record`, `can_edit_record`,
  кэш на запрос; зелёный поднабор `test_lists_process_access` (права и сужение) — `backend/apps/lists/services/access.py`
  — (FR-859–864, 888–889)

## Этап 2 — настройка процесса и стадии

- [ ] T-15010 [code] Служба процесса и вкладка «Процесс»: `get_or_create`, `save_settings` (название,
  режим, расписание, шаблон), страница и маршруты, вкладка в заголовке настройки — `backend/apps/lists/services/process.py`,
  `views/settings.py`, `urls.py`, `templates/lists/_settings_head.html`, `settings_process.html`,
  `texts.py` — (FR-851–853, 857–858)
- [ ] T-15011 [code] Стадии, права и обязательные поля: добавление, правка, порядок, удаление с проверками;
  наборы «Читают»/«Правят»; выбор обязательных полей — `backend/apps/lists/services/process.py`,
  `views/settings.py`, `templates/lists/process_stage.html`, `urls.py` — (FR-853, 859–864)
- [ ] T-15012 [code] Включение и повторное включение: автор, первая стадия только записям без стадии,
  повышение версии без строк истории, число переведённых и автор в журнале; выключение — `backend/apps/lists/services/process.py`,
  `views/settings.py`, `templates/lists/settings_process.html` — (FR-854–856, 865)
- [ ] T-15013 [code] Скрытие поля: `schema._set_hidden` вызывает удаление поля из наборов всех стадий списка
  и пишет журнал; форма стадии больше его не показывает — `backend/apps/lists/services/schema.py`,
  `services/process.py`, `views/settings.py` — (FR-867, 870)
- [ ] T-15014 [code] Зелёные проверки этапа 2: `test_lists_process` (настройка, стадии, включение, автор) и
  конфигурационная часть `test_lists_process_required` (выбор и скрытие полей); поведение создания и
  перехода остаётся красным — тесты, правки кода только по отказам — (FR-851–858, 859–861, 864, 867, 870)

## Этап 3 — права на поверхностях и переходы

- [ ] T-15020 [code] Видимость стадии на всех независимых поверхностях: карточка, GET правки и история —
  404 до контекста; подсказка фильтра, показ ссылочных значений, импорт, поиск (`_readable` и `_exact_ids`),
  связи с заявками, «Закреплённое», история, подсказки выбора, этикетки; `role_usage`/`unit_usage` включают
  права стадий в причину запрета удаления роли или узла и объясняют его текстом, регрессия
  `test_lists_links` — `backend/apps/lists/services/access.py`, `views/records.py`, `views/grid.py`,
  `services/values.py`, `services/search.py`, `services/links.py`, `services/history.py`,
  `services/tickets.py`, `views/pickers.py`, `views/labels.py` — (FR-859, 861, 884)
- [ ] T-15021 [code] Служба перехода: замок, чтение до ответа, повтор по `to_stage_key`, версия, ожидаемая
  стадия, права, итоговые значения, вход/выход обязательных полей, файл, `StageMove`, история, журнал —
  `backend/apps/lists/services/transitions.py`, `services/errors.py`, `services/process.py` — (FR-863,
  867–869, 871–874)
- [ ] T-15022 [code] Создание, правка, загрузка, файлы, архив: стадия при создании и восстановлении; права
  стадии в `save`; обязательные поля на итоговом состоянии; импорт `will_update` без обхода; файлы по праву
  стадии и запрет удалить последний обязательный — `backend/apps/lists/services/records.py`,
  `services/imports.py`, `services/files.py`, `views/files.py`, `services/archive.py`, `views/records.py` —
  (FR-865–870, 883)
- [ ] T-15023 [code] Карточка и форма перехода: текущая стадия, видимые целевые стадии, скрытый
  `base_version`, подсветка обязательных полей, кнопки «Перейти» и «Завершить» — `backend/apps/lists/views/records.py`,
  `templates/lists/record.html`, `record_form.html`, `_record_stage.html`, `texts.py` — (FR-862, 867–869,
  873–874)
- [ ] T-15024 [code] Гонки, версия и идемпотентность: 20 одинаковых POST — один переход, остальные `200`;
  разные цели — `409`; устаревшая форма — `409` без перезаписи; переход из «Без стадии»; удаление пустой
  стадии и повтор по `to_stage_key` — `backend/apps/lists/services/transitions.py`, тесты `test_lists_process_move.py`
  — (FR-872, NFR-751)

## Этап 4 — доска, таблица, выгрузка

- [ ] T-15030 [code] Доска: колонки по порядку, «Без стадии», счётчики, оконная выборка по 50 с сортировкой
  таблицы, без архива, страницы колонок, маршрут переноса — `backend/apps/lists/services/board.py`,
  `views/board.py`, `urls.py`, `templates/lists/board/page.html`, `_board.html`, `_column.html` — (FR-879–881)
- [ ] T-15031 [code] Перетаскивание и мобильная раскладка: HTML5 drag-and-drop, POST `base_version`, замена
  доски/колонки, сообщение об отказе, переключатель «Таблица / Стадии», 360 px — `backend/static/js/lists-board.js`,
  `backend/static/lists/board.css`, шаблоны доски, `grid.html` — (FR-879–881, 891, NFR-753)
- [ ] T-15032 [code] Таблица: системный столбец «Стадия», фильтр по стадиям, сортировка по порядку, «Без
  стадии» первыми — `backend/apps/lists/services/grid.py`, `views/grid.py`, `templates/lists/grid.html` —
  (FR-882)
- [ ] T-15033 [code] Выгрузка, поиск, связи и подсказки: колонка «Стадия» в XLSX; поиск не показывает
  нечитаемые стадии; ссылки, история, «Закреплённое», подсказки выбора и значения фильтра — те же права —
  `backend/apps/lists/services/export.py`, `search.py`, `links.py`, `history.py`, `values.py`,
  `views/pickers.py`, `labels.py` — (FR-883–884)
- [ ] T-15034 [code] Зелёные проверки этапа 4 и SQL: `test_lists_process_board`, `test_lists_process_grid`;
  `assertNumQueries` доски ≤12, таблицы ≤10 и карточки ≤15 (проверку карточки добавить в
  `test_lists_process_move.py` с отметкой в отчёте, файл принадлежит T-15003); `EXPLAIN` по
  `Record(list, stage)`, `ProcessStage(process, order)`, `StageMove(record, base_version, to_stage_key)` —
  тесты, правки кода только по отказам — (FR-879–884, NFR-750)

## Этап 5 — расписание, журнал, стенд

- [ ] T-15040 [code] Расчёт периода и плановый запуск: `due`, `period_start` по Москве, строка
  `ProcessLaunch` первой в точке сохранения, `created/skipped/failed`, значения по умолчанию, автор,
  простой без нагона — `backend/apps/lists/services/schedule.py`, `services/process.py` — (FR-875–878)
- [ ] T-15041 [code] Минутное задание и cron: `process_launch_tick` в `tasks.py`, регистрация в
  `config/cron.py` (очередь `maintenance`, `* * * * *`, имя `lists_process_launch`, `job_timeout=300`);
  правка `test_lists_deploy` — 33 регистрации, две функции `apps.lists.tasks`, имя/очередь/cron/timeout —
  `backend/apps/lists/tasks.py`, `backend/config/cron.py`, `backend/tests/test_lists_deploy.py` — (FR-875,
  878, NFR-752)
- [ ] T-15042 [code] Журнал и история: подписи действий, ручной автор и пустой системный, отсутствие
  названия записи и значений полей, история перехода с «Без стадии», удалённая стадия по снимку названия —
  `backend/apps/lists/audit_labels.py`, `services/process.py`, `services/transitions.py`,
  `services/schedule.py`, `services/history.py` — (FR-885–887)
- [ ] T-15043 [arch] Миграции, стенд и регрессия: `makemigrations --check` для `lists`, миграция `0003` на
  стенде без сброса, полный набор `test_lists_*` и `test_lists_deploy` — команды и сводка — (FR-888–892)
- [ ] T-15044 [code] Зелёные проверки этапа 5: `test_lists_process_schedule`, `test_lists_process_journal`;
  `created/skipped/failed`, простой, параллельные тики, ПДн; `EXPLAIN` по
  `ProcessLaunch(process, period_start)` (проверку добавить в `test_lists_process_schedule.py` с отметкой в
  отчёте, файл принадлежит T-15004) — тесты, правки кода только по отказам — (FR-875–878, 885–887,
  NFR-752)

## Этап 6 — приёмка

- [ ] T-15050 [arch] Полный серверный прогон: `systemd-run --user`, файлы `*.status`/`*.log`/`*.exit`;
  ожидание события, разбор первичных логов — (все FR/NFR)
- [ ] T-15051 [arch] Браузеры: Chromium, Firefox, Edge, Яндекс; доска, карточка, форма стадии, 360 px —
  `backend/tests/e2e/test_t15_board.py`, `test_t15_stage.py`, `test_t15_mobile.py` — (FR-891, NFR-753)
- [ ] T-15052 [arch] Нагрузка и гонки: `fill_lists_process.py`, класс `ListsUser`, Locust 100×6 минут;
  отдельный прогон 20 параллельных переходов — `backend/tests/load/` — (NFR-750–752)
- [ ] T-15053 [человек] Ручной проход по чек-листу: включение процесса, стадии, права, обязательные поля,
  доска, расписание, 360 px — `crm-work/slice015/stage6/manual/checklist.md` — (FR-891, NFR-753)
- [ ] T-15054 [code] Исправления приёмки: дефекты полного прогона, браузеров, нагрузки и ручного прохода;
  повторная проверка исправленного — файлы по находкам — (по находкам)
- [ ] T-15055 [arch] Финальный прогон и отчёт: повторный полный прогон после исправлений, отчёт
  `docs/reviews/TASKS-015.md`, обновление HANDOFF; закрытие задач — (все FR/NFR)

## Трассировка задач к требованиям

| Требования | Задачи |
|---|---|
| FR-851–858 | T-15001, T-15002, T-15010, T-15011, T-15012, T-15013, T-15014 |
| FR-859–864 | T-15003, T-15005, T-15011, T-15020, T-15021, T-15023 |
| FR-865–870 | T-15003, T-15011, T-15013, T-15021, T-15022, T-15023 |
| FR-871–874 | T-15003, T-15021, T-15023, T-15024 |
| FR-875–878 | T-15004, T-15040, T-15041, T-15044 |
| FR-879–884 | T-15004, T-15020, T-15030, T-15031, T-15032, T-15033, T-15034 |
| FR-885–887 | T-15004, T-15042, T-15044 |
| FR-888–889 | T-15005, T-15020, T-15043 |
| FR-890, 892 | T-15043 |
| FR-891 | T-15031, T-15051, T-15053 |
| NFR-750 | T-15004, T-15034, T-15052 |
| NFR-751 | T-15003, T-15024, T-15052 |
| NFR-752 | T-15004, T-15041, T-15044, T-15052 |
| NFR-753 | T-15031, T-15042, T-15051, T-15053 |

Обеспечивающие задачи: T-15001 — контракт для всех FR/NFR; T-15003/T-15004 — красные проверки;
T-15014/T-15034/T-15044 — зелёные прогоны этапов; T-15050–T-15055 — приёмка всех FR/NFR.
