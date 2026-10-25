# Контракт имён тестов Этапа 2 среза 006 (T-6100…T-6153)

Тесты пишутся до кода и задают имена, которых нет в PLAN-006. Реализация (Этап 3) берёт их отсюда дословно (решение 50
задач). Имена плана (модели и поля раздела «Модель данных», маршруты «Контрактов», коды журнала, право `lists.manage`,
приложение `lists`, задание `remind_deadlines` и запись cron `lists_reminders`, команда `e2e_lists_shift`, вид
`lists.deadline`, поля `ParsedQuery.text` и `NotificationKind.external_text_of`, функции `role_ids`, `unit_chain_ids`,
`all_units`, `unit_refs`) здесь повторяются только там, где тест уточняет их форму. Имена срезов 001–005
(`tests/CONTRACT.md`, `CONTRACT-002.md` … `CONTRACT-005.md`) не меняются; что в этих файлах устаревает со срезом 006,
перечислено в разделе 14 (решение 4 задач).

Происхождение каждой строки видно из текста: «план» — PLAN-006; «решение N задач» — раздел «Решения Opus по задачам»
TASKS-006 (решения Opus, принятые владельцем подписью TASKS-006); «И1», «И2» — «Решения Opus при исполнении» отчёта
`docs/reviews/TASKS-006.md` (И2 — по ответу владельца 2026-10-25 «Фоном»); «решение владельца 2026-10-25» — так и
названо; «факт» — файл репозитория, названный в строке; «решение контракта» — выбор автора контракта там, где план и
решения оставили выбор; причина каждого такого выбора — в той же строке и сводно в разделе 15. Решения контракта ничьим
решением владельца не являются: их проверяет Opus до запуска T-6101 (решение 2 задач).

Помощники тестов: `tests/support_lists.py` (пишет только T-6101, раздел 5.9) и `tests/e2e/helpers_lists.py` (пишет только
T-6140, раздел 13.3). В колонке «Тесты» стоят задачи T-61NN, которые берут имя.

Правила для всех тестов среза:
- время (решение 5 задач): службы берут время из `django.utils.timezone.now()` и дату из `apps.core.widgets.moscow_today()`
  (факт); тесты ставят часы фикстурой `clock` (`Clock` из `tests/factories.py`); проверки «по Москве» ставят часы на
  полночь UTC (дата по Москве уже следующая);
- задания выполняются синхронно: обход сроков — `support_lists.run_reminders(today)` (раздел 5.9); задания очереди
  `maintenance` (пересчёт векторов, И2) — прежним помощником `support_notify.run_jobs("maintenance")` внутри
  `with django_capture_on_commit_callbacks(execute=True):`; приёмка сдвигает сроки командой `e2e_lists_shift --days N`
  через обёртку `shift(days)` (раздел 13);
- всё, что идёт «после фиксации» (стирание файлов с диска, постановка проверки файла и пересчёта векторов), проверяется
  внутри `django_capture_on_commit_callbacks(execute=True)` (решение 6 задач, п. г);
- гонки — без потоков (решение 6 задач): по SQL (`support_lists.list_locks`, `assert_for_update`), последовательно в обеих
  очерёдностях, подменой предварительной проверки уникальности (решение 28) и подменой «между выборкой и замком» (решение
  45); `django_db(transaction=True)` не используется;
- ClamAV (решение 44 задач): подмена строкой `apps.integrations.clamav.services.scan` помощниками `support_org.scan_clean`,
  `scan_found`, `scan_unavailable`;
- код среза тесты импортируют внутри функций теста (или через `support.model("lists.Record")`), а не на уровне модуля:
  сбор `pytest --collect-only` проходит до появления кода; `support_lists.py` на уровне модуля `apps.lists` не импортирует;
- тексты отказов в тестах — литералы раздела 12, а не импорт `lists/texts.py` (решение 25 задач); один тест сверяет, что
  словарь `apps.lists.texts.TEXTS` содержит каждый текст раздела 12.1–12.3;
- секреты и ПДн в тестовых данных (решение 12 задач): почта и телефоны — `support_lists.email_of`, `phone_of`; имена
  переменных — без `secret`, `token`, `key`, `password`; номер лицензии в данных — условный номер договора; строка EICAR
  собирается из частей; в файлах и ответах — только `***`;
- разметка блоков среза (решение 13 задач): без `role="status"`, `role="alert"`, `data-error`, `data-warning`, кроме
  сообщений об отказах формы (раздел 10.1); строка поиска внутри списка — в `form[data-lists-search]`, вне
  `form#staff-filter` и `#notify-bell`;
- подписчик `lists` на `core.user_dismissed` (решение 14 задач): тесты среза проверяют, что в журнале приложения нет
  записей уровня `ERROR` логгера `apps.core.events`;
- тесты ходят по путям плана (раздел «Контракты»), а не по именам маршрутов; маршруты среза не содержат `regist`, `signup`
  (решение 15 задач);
- SQL — только параметры (NFR-509): `cursor.execute(sql, [list_no])`; код поля — только из `Field.code` схемы.

Разделы:
1. Среда запуска и числа среза.
2. Модели и поля, данные установки.
3. Ядро и записи точек `lists`.
4. Прежние модули: `org`, `servicedesk`, `notify`, `search`.
5. Службы `lists`, исключения, подмены и помощники `support_lists.py`.
6. Перечень мест `visible_fields` и мест «все поля» (решение 27 задач).
7. Вид уведомления `lists.deadline` и таблица «код вида → модуль».
8. Журнал.
9. Поиск.
10. Маршруты, поля форм, ответы, «адрес × кто».
11. Зацепки `data-*` для приёмки.
12. Тексты, которые проверяют тесты.
13. Команды стенда, нагрузка, помощники приёмки.
14. Что меняется в прежних контрактах (для T-6138).
15. Вопросы и решения.

## 1. Среда запуска и числа среза

### 1.1. Приложение, каркас, статика

| Что | Требование | Тесты |
|---|---|---|
| `INSTALLED_APPS` | `"apps.lists"` стоит после `"apps.knowledge"` и перед `"apps.search"` (решение плана; факт после T-6001): хвост списка — `"apps.servicedesk"`, `"apps.notify"`, `"apps.knowledge"`, `"apps.lists"`, `"apps.search"`; метка `lists`, класс `ListsConfig`, `verbose_name = "Списки"` (решение контракта: как `"База знаний"` у `knowledge`) | T-6125 test_lists_is_in_installed_apps_after_knowledge_and_before_search |
| `ListsConfig.ready()` | зовёт `apps.lists.extensions.register_all()` (регистрации точек, раздел 3.3), затем подписку шины `core.user_dismissed` (раздел 3.4); `dispatch.subscribe_all()` не зовёт (план) | T-6126 |
| Каркас (факт T-6001) | `apps/lists/`: `models.py`, `texts.py`, `notify_kinds.py`, `audit_labels.py`, `card.py`, `ticket_parts.py`, `extensions.py`, `stand.py`, `tasks.py`, `urls.py`; `views/` (`home`, `settings`, `records`, `grid`, `files`, `imports`, `labels`, `pickers`, `tickets`); `services/` (`schema`, `values`, `records`, `access`, `history`, `unique`, `archive`, `links`, `tickets`, `grid`, `reminders`, `export`, `imports`, `labels`, `search`, `vectors`, `files`); `management/commands/e2e_lists_shift.py`; миграции `0001_initial.py`, `0002_initial_data.py`; шаблоны — `templates/lists/`; иконка — `templates/icons/lists.html` | T-6126 (обход `ast` по этим путям) |
| Статика (решение 59 задач) | `static/lists/lists.js` — `<script defer src=…>` в шаблонах страниц списков; `static/lists/lists.css` — `<link rel="stylesheet">` в шаблонах страниц списков; `static/lists/labels.css` — `<link>` только в шаблонах этикеток (`/label/`, `/labels/`); в файлах `.js` нет `eval(` и `new Function`; в `_assets.html` файлы среза не подключаются | T-6125 test_lists_scripts_are_external_files_in_static_lists; T-6120 test_label_pages_link_labels_css_and_other_list_pages_do_not |
| Файл теста развёртывания | `tests/test_lists_deploy.py` (по образцу `test_kb_deploy.py`; решение 18 задач) | T-6125 |
| Шаблоны | в `templates/lists/` нет атрибута `style=` и атрибутов `on…=` (регулярное выражение, как в `test_shell.py`) | T-6125 test_lists_templates_have_no_style_attribute, test_lists_templates_have_no_inline_event_handlers; T-6120 test_label_pages_have_no_inline_style_or_event_attributes |
| CSP | страницы `/lists/…` отдают `Content-Security-Policy` с `script-src 'self'` без `'unsafe-inline'` и `'unsafe-eval'`; `img-src 'self' data:` без `http:`, `https:`, `*` (QR — `data:`); тест читает заголовок у `/lists/`, `/lists/<id>/`, `/lists/<id>/<n>/`, `/lists/<id>/<n>/label/` | T-6125 test_lists_pages_send_csp_without_unsafe_inline_in_script_src, test_csp_img_src_on_lists_pages_allows_data_and_no_external_addresses |
| Язык и время | тексты страниц среза по-русски (страницы — `support_lists.list_pages(lst, record)`, раздел 5.9); время — по Москве: тест ставит `Clock` на полночь UTC и находит дату и время по Москве в значении «дата и время», в истории (`time[data-at]`) и в итоге загрузки | T-6125 test_lists_pages_texts_are_russian, test_lists_times_are_shown_in_moscow_at_utc_midnight_in_dates_history_and_import_summary |

### 1.2. Задание сроков, nginx, том файлов

| Что | Требование | Тесты |
|---|---|---|
| Запись cron (план) | восемнадцатая запись в `config/cron.py`: `register(remind_deadlines, queue_name="maintenance", cron="0 5 * * *", name="lists_reminders", job_timeout=600)`; импорт `from apps.lists.tasks import remind_deadlines` в начале модуля рядом с прочими; других записей очереди `maintenance` на `0 5 * * *` нет (ежечасное `requeue_pending_scans` — очередь `mail`, это не нарушение); заданий очистки записей списков в cron нет (FR-544) | T-6125 test_lists_reminders_cron_entry_runs_remind_deadlines_at_0_5_in_maintenance_with_timeout_600, test_cron_has_no_other_maintenance_entry_at_0_5, test_cron_module_has_eighteen_register_calls, test_cron_has_no_cleanup_job_for_list_records |
| Задание пересчёта векторов (И2) | не запись cron, а задание очереди `maintenance`, поставленное после фиксации скрытия или показа поля (раздел 5.6); тест cron его не ищет | T-6104, T-6122 |
| `location` nginx (план) | в `deploy/nginx.conf` и `deploy/nginx.prod.conf`: `location ~ ^/lists/[0-9]+/[0-9]+/files/$ { … }` с `client_max_body_size 55m;`; скачивание `/lists/<id>/<n>/files/<file_id>/` под шаблон не подпадает; общий предел 6 МБ не меняется | T-6125 test_nginx_dev_config_has_lists_files_location_with_55m_limit, test_nginx_prod_config_has_lists_files_location_with_55m_limit |
| Директивы `proxy_*` | повторены в новом блоке; набор имён директив совпадает с блоком `tickets` того же файла (как у блока `kb` в CONTRACT-005, 1.2) | T-6125 test_lists_files_location_repeats_proxy_directives_in_both_configs |
| Том файлов, копия | файлы записей лежат в томе `protected` (`incoming/`, `attachments/`, `quarantine/`) через `core.uploads.store(…, "lists")`; `deploy/backup.sh` и `RESTORE.md` не меняются: слов `lists` в них нет | T-6125 test_record_files_live_in_protected_volume_and_backup_script_and_restore_guide_are_unchanged |
| ClamAV | файлы записей проверяет прежнее задание ядра `scan_file` (очередь `files`) через атрибут модуля `apps.integrations.clamav.services.scan` (факт CONTRACT-005, 1.2); подмена строкой действует и для файлов записей | T-6121 |

### 1.3. Сброс стенда: точка `stand_reset` модуля `lists`

Функция — `apps.lists.stand.stand_reset()` без аргументов, регистрируется в `apps/lists/extensions.py` последней из
регистраций `register_all()` (решение контракта: как у `knowledge`). Приложения регистрируют точку в порядке
`INSTALLED_APPS`, команда `e2e_reset_stand` зовёт функции в обратном порядке, поэтому функция `lists` идёт первой,
раньше `knowledge` (план). Работает через соединение `migrate`, если оно настроено, иначе `default`.

| Что | Требование | Тесты |
|---|---|---|
| Транзакция | всё стирание и `seed` — в одной `transaction.atomic(using=<алиас>)` | T-6124 test_lists_stand_reset_runs_in_transaction_under_migrate_alias |
| Файлы | пути файлов по строкам `RecordFile` (по всем состояниям: `incoming/`, `attachments/`, `quarantine/`) собираются до удаления; затем удаляются строки `RecordFile` и их `StoredFile`; диск — `core_files.remove_paths(paths)` в `transaction.on_commit` | T-6124 test_lists_stand_reset_wipes_record_files_rows_stored_files_and_disk_after_commit |
| Порядок стирания (план) | `TicketLink`, `ReminderSent`, `Change`, `UniqueValue`, `Record`, `UserView`, `ImportJob`, `Access`, `Choice`, `Field`, `List` (после `RecordFile`); у `Field.target` RESTRICT, поэтому поля стираются до списков | T-6124 test_lists_stand_reset_wipes_links_reminders_history_unique_values_records_views_imports_access_choices_fields_lists |
| Восстановление | вызов `seed(django.apps.apps, SimpleNamespace(connection=connections[<алиас>]))` миграции `0002` (как `knowledge`, CONTRACT-005, 1.3); на время вызова отключается обработчик `m2m_changed` прав ядра (план); итог — шесть стартовых списков, право `lists.manage` у «Администратора портала», строки `Access` у «Сотрудника ИТ» | T-6124 test_lists_stand_reset_then_seeds_six_starting_lists_with_fields_permission_and_access, test_lists_stand_reset_returns_deleted_and_renamed_starting_list |
| Не трогается | `StoredFile` с `purpose="attachment"` и `purpose="knowledge"` и их файлы | T-6124 test_lists_stand_reset_keeps_ticket_and_article_files |
| Порядок | в `extensions.registered("stand_reset")` функция `apps.lists.stand.stand_reset` стоит сразу после `apps.knowledge.stand.stand_reset` и последней | T-6124 test_lists_stand_reset_is_registered_after_knowledge_and_runs_before_it |
| Проверка стенда | `apps.lists.stand.require_stand()` и `apps.lists.stand.REFUSAL` — своя копия (план): `REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."`; без `os.environ.get("E2E_STAND") == "1"` — `CommandError(REFUSAL)` раньше любого чтения базы | T-6124 test_lists_require_stand_refuses_without_e2e_stand_flag |

Тесты сброса помечаются `pytest.mark.django_db(databases=["default", "migrate"])`, данные создают и читают через
`using("migrate")`, функцию `stand_reset()` вызывают напрямую (как в CONTRACT-005, 1.3).

### 1.4. Числа среза (план, «Контракты»; решение 62 задач)

| Число | Значение | Кто сверяет |
|---|---|---|
| Точек расширения | семнадцать, состав `POINTS` не меняется | T-6126 test_points_still_have_seventeen_names |
| Видов уведомлений | двенадцать (новый `lists.deadline`), таблица — раздел 7.3 | T-6138, T-6116 |
| Прав в портале | шестнадцать (новое `lists.manage` «Управление списками», последним) | T-6105 test_portal_has_sixteen_permissions_after_seed; T-6138 |
| Вызовов `register` в `config/cron.py` | восемнадцать (`lists_reminders`) | T-6125; T-6138 |
| Пунктов меню администратора | двенадцать; «Списки» (`/lists/`, `order` 8, значок `icons/lists.html`) — между «Базой знаний» (7) и «Сотрудниками» (10) | T-6102; T-6138 |
| `location` с `client_max_body_size 55m` | на один больше, чем после среза 005 (четыре шаблона) | T-6125; T-6138 |
| Полей `NotificationKind` | тринадцать после `external_text_of` (последним) | T-6116; T-6138 |
| `apps.lists` в `INSTALLED_APPS` | перед `apps.search`, после `apps.knowledge` | T-6125; T-6138 |

## 2. Модели и поля, данные установки

Модели берутся через `support.model("lists.List")` и так далее. Типы, длины и связи — план («Модель данных»); здесь —
то, что план оставил выбору: имена классов вариантов, имена ограничений (образец — CONTRACT-005, 2.2:
`<приложение>_<модель>_<поля>_<вид>`; тест ловит `IntegrityError`, имя по тексту ошибки не сверяет), значения по
умолчанию и два отступления от таблицы моделей плана (решение 34 задач и И2).

### 2.1. Ядро

| Что | Требование | Тесты |
|---|---|---|
| `StoredFile.Purpose.LISTS` | значение `"lists"`, подпись `"файл записи списка"` (план — «Файл записи списка»; регистр подписей `Purpose` прежний — строчные, как `"файл статьи"`, решение контракта); миграция ядра `0009` — только `AlterField` вариантов | T-6121 test_attach_stores_file_through_uploads_store_with_lists_purpose |
| `ParsedQuery.text` | `text: str = ""` — последнее поле записи, после `hint` (план); заполняет `search.parse` (раздел 4.4) | T-6122 test_parse_fills_text_stripped_of_edge_spaces_and_empty_for_short_and_long_hints |
| `NotificationKind.external_text_of` | `external_text_of: Callable[[str], str] \| None = None` — последнее, тринадцатое поле, после `coalesce` (план) | T-6116 test_notify_kinds_external_text_uses_external_text_of_and_falls_back_to_former_external_text |

### 2.2. Приложение `lists`

| Модель.поле | Требование | Тесты |
|---|---|---|
| `List` | поля плана; `code` — `CharField(40, blank=True, default="")`; `next_number` — `PositiveIntegerField(default=1)`; `next_field_no` — `PositiveIntegerField(default=1)`; `created_by` — `ForeignKey("core.User", PROTECT, null=True, blank=True)` (решение 34 задач, отступление от PLAN-006: у стартовых списков пусто) | T-6103, T-6105 test_seed_lists_have_empty_created_by |
| `List.vectors_stale_since` | `DateTimeField(null=True, blank=True)` — признак незавершённого пересчёта векторов (И2, отступление от таблицы моделей плана, оговорённое его запасным ходом; имя закрепляет контракт по предложению Opus); ставится `timezone.now()` в транзакции «Скрыть»/«Показать»; задание `refresh_vectors` снимает его в `None` в конце (раздел 5.6); пока не пусто — страница списка показывает «Поиск по списку обновляется» (раздел 12.1) | T-6104 test_hide_and_show_set_flag_write_field_hidden_and_field_shown_and_recompute_vectors; T-6122 |
| `List`, ограничения | `UniqueConstraint(Lower("name"), name="lists_list_name_ci_uniq")`; `UniqueConstraint(fields=["code"], condition=~Q(code=""), name="lists_list_code_uniq")` | T-6103 test_list_name_in_other_case_rejected_at_field_and_lower_name_integrity_error_gives_same_error |
| `Field` | поля плана; `type` — `CharField(16, choices=Field.Type.choices)`; `code` — `CharField(40)`; `default` — `JSONField(null=True, blank=True)`; `order` — `PositiveIntegerField`; `target` — `ForeignKey("lists.List", RESTRICT, null=True, blank=True, related_name="referring_fields")`; `settings` — `JSONField(default=dict)` с ключами `currency`, `deadline`, `thresholds` (план); логические признаки — `BooleanField(default=False)` | T-6103, T-6104 |
| `Field.Type` | `TextChoices`: `STRING = "string", "Строка"`; `TEXT = "text", "Многострочный текст"`; `NUMBER = "number", "Число"`; `MONEY = "money", "Деньги"`; `DATE = "date", "Дата"`; `DATETIME = "datetime", "Дата и время"`; `BOOL = "bool", "Да/нет"`; `CHOICE = "choice", "Список значений"`; `PERSON = "person", "Сотрудник"`; `UNIT = "unit", "Подразделение"`; `RECORD = "record", "Запись другого списка"`; `FILE = "file", "Файл"` (значения — план; подписи — решение контракта по названиям типов SPEC-006) | T-6103 test_service_rejects_property_not_of_its_type_for_each_of_12_types |
| `Field`, ограничения | `UniqueConstraint(fields=["list", "code"], name="lists_field_list_code_uniq")`; `UniqueConstraint("list", Lower("name"), name="lists_field_list_name_ci_uniq")`; `CheckConstraint(condition=Q(type="record", target__isnull=False) \| (~Q(type="record") & Q(target__isnull=True)), name="lists_field_target_iff_record")`; индекс (`list`, `order`) | T-6103 test_record_field_without_target_rejected_and_target_own_list_allowed |
| Код поля | у созданных вручную — `f<next_field_no>` под исключительным замком списка, `next_field_no` растёт и не возвращается после удаления; регулярное выражение `^[a-z][a-z0-9_]*$`, длина до 40; запрещены `title`, `number`, `new`, `order` (план) | T-6103 test_field_code_f_next_field_no_not_reused_after_delete_and_reserved_or_invalid_codes_rejected, test_literal_fields_new_and_order_urls_are_not_taken_for_field_code; T-6106 test_field_code_is_f_number_so_values_key_never_consists_of_digits |
| `Field.default` | строка — строка; число — каноническая строка («12.5»); деньги — строка с двумя знаками; дата — `{"today": true}` или `"YYYY-MM-DD"`; да/нет — `true`; список значений — `[id]`; у прочих типов — `None` (план) | T-6103 test_default_value_only_for_six_types_and_date_today_stored_as_today_true |
| `Choice` | `title` (`CharField(100)`), `order` (`PositiveIntegerField`), `archived` (`BooleanField(default=False)`); `UniqueConstraint("field", Lower("title"), name="lists_choice_field_title_ci_uniq")` | T-6104 |
| `Record` | поля плана; `number`, `version` — `PositiveIntegerField` (`version` с 1); `values` — `JSONField(default=dict)`; `search` — `SearchVectorField(null=True)`; `archived_by` — `ForeignKey("core.User", PROTECT, null=True, blank=True, related_name="+")`; `created_by`, `updated_by` — PROTECT, `related_name="+"` (решение контракта: без обратных имён у `User`) | T-6108a |
| `Record`, ограничения | `UniqueConstraint(fields=["list", "number"], name="lists_record_list_number_uniq")`; `CheckConstraint(condition=Q(archived=True, archived_at__isnull=False) \| Q(archived=False, archived_at__isnull=True), name="lists_record_archived_iff_archived_at")`; индексы (`list`, `archived`), `GinIndex(fields=["search"])` | T-6108a, T-6110 |
| `UniqueValue` | `norm_value` — `CharField(500)`; `UniqueConstraint(fields=["list", "field", "norm_value"], name="lists_uniquevalue_list_field_norm_uniq")`; индекс (`record`) | T-6107 |
| `Change` | `kind` — `CharField(16, choices=Change.Kind.choices)`: `created`, `changed`, `imported`, `archived`, `restored`, `file_added`, `file_removed` (план); `changes` — `JSONField(default=list)`; `via_import` — `BooleanField(default=False)`; `at` — `DateTimeField(default=timezone.now)`; `actor` — PROTECT, `null=True`; индекс (`record`, `at`, `id`) | T-6109 |
| `Access` | `level` — `CharField(8, choices=Access.Level.choices)`: `READ = "read", "Читают"`, `EDIT = "edit", "Правят"`; `role` — `ForeignKey("core.Role", PROTECT, null=True, blank=True)`; `unit_id` — `PositiveIntegerField(null=True, blank=True)` без внешнего ключа; ограничения: `CheckConstraint(condition=Q(role__isnull=False, unit_id__isnull=True) \| Q(role__isnull=True, unit_id__isnull=False), name="lists_access_one_subject")`, `UniqueConstraint(fields=["list", "level", "role"], condition=Q(role__isnull=False), name="lists_access_list_level_role_uniq")`, `UniqueConstraint(fields=["list", "level", "unit_id"], condition=Q(unit_id__isnull=False), name="lists_access_list_level_unit_uniq")` | T-6102, T-6113 test_access_role_foreign_key_protects_role_from_delete; T-6126 test_access_unit_id_and_ticket_link_ticket_number_are_plain_integers |
| `UserView` | `columns` — `JSONField(default=list)`; `UniqueConstraint(fields=["user", "list"], name="lists_userview_user_list_uniq")` | T-6112 |
| `TicketLink` | `ticket_number` — `PositiveIntegerField` без внешнего ключа; `linked_at` — `DateTimeField(default=timezone.now)`; `UniqueConstraint(fields=["record", "ticket_number"], name="lists_ticketlink_record_ticket_uniq")`; индекс (`ticket_number`) | T-6114, T-6126 |
| `ReminderSent` | `threshold_days` — `PositiveSmallIntegerField` (0 — «срок наступил»); `due_date` — `DateField`; `notified` — `BooleanField`; `created_at` — `DateTimeField(default=timezone.now)`; `UniqueConstraint(fields=["record", "field", "threshold_days", "due_date"], name="lists_remindersent_uniq")` | T-6115, T-6116 |
| `ImportJob` | `state` — `CharField(8, choices=ImportJob.State.choices)`: `mapping`, `preview`, `done`; `file_format` — `csv`, `xlsx`; `header`, `rows` — `JSONField(default=list)`; `mapping`, `summary` — `JSONField(default=dict)`; `created_at` — `DateTimeField(default=timezone.now)`; индекс (`state`, `created_at`); после подтверждения `rows == []`, `summary == {"created": N, "updated": M, "errors": K}` | T-6118, T-6119 test_confirm_clears_rows_keeps_summary_and_sets_done |
| `ImportJob.rows` | элемент — словарь `{"row": <номер строки файла, заголовок — 1, первая строка данных — 2>, "cells": [<строки как прочитаны>], "result": "will_create" \| "will_update" \| "error", "reason": <текст отказа или "">, "number": <номер записи или null>}` (план: «исходные строки и итог проверки»; ключи и нумерация строк — решение контракта: номер строки совпадает с номером строки в программе таблиц) | T-6118 test_preview_each_record_rule_violation_has_reason_and_row_number |
| `RecordFile` | поля плана; `field` — PROTECT; `file` — `OneToOneField("core.StoredFile", PROTECT)`; `uploaded_at` — `DateTimeField(default=timezone.now)`; индекс (`record`, `uploaded_at`) | T-6121 test_field_with_files_cannot_be_deleted_protect |
| Внешние ключи | у моделей `lists` нет внешних ключей на модели `org` и `servicedesk` | T-6126 test_lists_models_have_no_foreign_keys_to_org_and_servicedesk_models |

### 2.3. Хранение значений (план, «Значения по типам»)

| Тип | Ключ в `values` | Нормализация `UniqueValue` |
|---|---|---|
| `string` | строка без переносов | `strip().lower()` |
| `text` | строка, переносы `\n` (ввод `\r\n` и `\r` приводится к `\n` — решение контракта, иначе длина считалась бы по-разному в форме и загрузке) | — |
| `number` | каноническая десятичная строка: без ведущих нулей и без нулей в конце дробной части, без точки у целого («12.5», «100», «-3»); «100.0» → «100» | та же каноническая строка |
| `money` | строка с двумя знаками («1234.50») | — |
| `date` | `YYYY-MM-DD` | — |
| `datetime` | `YYYY-MM-DDTHH:MM:00Z` (UTC) | — |
| `bool` | только `true`; снятый — ключа нет | — |
| `choice`, `person`, `unit`, `record` | массив целых id без повторов, в порядке выбора; без «несколько» — не больше одного id | — |
| `file` | в `values` нет (`RecordFile`) | — |

### 2.4. Миграция данных `lists 0002` (план, «Данные установки и стенд»)

Функции `seed(apps, schema_editor)` и `unseed(apps, schema_editor)` модуля `apps.lists.migrations.0002_initial_data`
(модуль берётся через `importlib`, решение 20 задач); `schema_editor` читается только как `.connection.alias`.

| Что | Требование | Тесты |
|---|---|---|
| Право | `Permission(code="lists.manage", title="Управление списками")` через `get_or_create`; выдача роли «Администратор портала» (`is_builtin=True`, `filter().first()`, нет роли — пропуск); прежние права роли остаются | T-6105 test_seed_on_slice_005_base_creates_lists_manage_and_grants_it_to_admin_role_only, test_seed_adds_lists_manage_to_existing_admin_role_and_keeps_its_prior_rights |
| Списки | шесть, по устойчивым кодам; создаётся только отсутствующий код (решение 51 задач): повторный вызов не дублирует, не трогает переименования, удалённый — создаёт заново | T-6105 test_second_seed_call_does_not_duplicate_and_keeps_admin_renamed_list_and_field, test_second_seed_call_recreates_deleted_seed_list_by_code_as_stand_reset_needs |
| Поля | коды — из таблицы ниже (не `f<n>`); `order` — 1, 2, 3 … по порядку таблицы; `next_field_no = 1` (решение контракта: стартовые коды не имеют вида `f<n>`, поэтому новые поля `f1`, `f2` … с ними не совпадают); `created_by` пусто | T-6105 test_seed_list_fields_have_codes_types_and_names_from_plan_table |
| «Показывать в таблице» (решение 52 задач) | у первых четырёх полей после «Названия», кроме `text` и `file`: `equipment` — `kind`, `inventory_number`, `serial_number`, `model`; `licenses` — `product`, `kind`, `seats`, `license_number`; `consumables` — `kind`, `model`, `printers`, `stock`; `signatures` — `holder`, `issuer`, `serial_number`, `medium`; `contracts` — `counterparty`, `contract_number`, `signed`, `valid_until`; `sims` — `phone`, `operator`, `tariff`, `assignee`; у прочих полей — нет | T-6105 test_seed_show_in_table_on_first_four_fields_after_title_except_text_and_file |
| Права | строки `Access(level="read")` и `Access(level="edit")` роли «Сотрудник ИТ» на каждом из шести списков; нет роли — пропуск без ошибки; «Руководитель» ничего не получает | T-6105 test_seed_gives_it_staff_read_and_edit_access_rows_on_each_of_six_lists, test_seed_without_it_staff_or_admin_role_passes_without_error |
| `unseed` (решение 35 задач) | снимает `lists.manage` и его выдачу; удаляет стартовые списки по кодам, у которых нет записей (в том числе в архиве); списки с записями остаются без ошибки | T-6105 test_unseed_removes_lists_manage_and_seed_lists_without_records_and_keeps_lists_with_records |

Стартовые списки (коды и типы — план; названия списков и полей — SPEC-006 FR-505; деньги — `RUB`; пороги — в порядке
убывания; признаки, не названные в строке, ложны; поле «Название» у всех системное):

| Код списка | Название | Поля: код — название — тип; признаки |
|---|---|---|
| `equipment` | Оборудование | `kind` — Вид — `choice` (Компьютер, Ноутбук, Монитор, Принтер/МФУ, Сетевое оборудование, Телефон, Прочее); `inventory_number` — Инвентарный номер — `string`, уникальное; `serial_number` — Серийный номер — `string`, уникальное; `model` — Модель — `string`; `state` — Состояние — `choice` (В работе, На складе, В ремонте); `assignee` — За кем закреплено — `person`; `unit` — Подразделение — `unit`; `place` — Место — `string`; `purchased` — Дата покупки — `date`; `warranty` — Гарантия до — `date`, срок, пороги `[30]`; `cost` — Стоимость — `money`; `note` — Примечание — `text`; `files` — Файлы — `file`, несколько |
| `licenses` | Лицензии | `product` — Продукт — `string`; `kind` — Вид — `choice` (Бессрочная, Подписка); `seats` — Количество мест — `number`; `license_number` — Номер лицензии или договора — `string`, подсказка «Ключи активации здесь не храните: секреты хранятся вне портала»; `valid_until` — Действует до — `date`, срок, пороги `[30, 7]`; `installed_on` — Установлена на — `record` → `equipment`, несколько; `owner` — Ответственный — `person`; `cost` — Стоимость — `money`; `files` — Файлы — `file`, несколько |
| `consumables` | Картриджи и расходники | `kind` — Вид — `choice` (Картридж, Тонер, Барабан, Прочее); `model` — Модель — `string`; `printers` — Для принтера — `record` → `equipment`, несколько; `stock` — Количество на складе — `number`; `note` — Примечание — `text` |
| `signatures` | Сертификаты ЭП | `holder` — Владелец — `person`; `issuer` — Удостоверяющий центр — `string`; `serial_number` — Серийный номер — `string`, уникальное; `medium` — Носитель — `choice` (Токен, Реестр, Облако); `valid_until` — Действует до — `date`, срок, пороги `[30, 7]`; `files` — Файлы — `file`, несколько |
| `contracts` | Договоры | `counterparty` — Контрагент — `string`; `contract_number` — Номер договора — `string`, уникальное; `subject` — Предмет — `text`; `signed` — Дата заключения — `date`; `valid_until` — Действует до — `date`, срок, пороги `[30]`; `amount` — Сумма — `money`; `owner` — Ответственный — `person`; `files` — Файлы — `file`, несколько |
| `sims` | SIM-карты и телефоны | `phone` — Номер телефона — `string`, уникальное; `operator` — Оператор — `choice` без значений; `tariff` — Тариф — `string`; `assignee` — За кем закреплено — `person`; `device` — Устройство — `record` → `equipment`; `iccid` — ICCID — `string`; `note` — Примечание — `text` |

Порядок значений `Choice` — порядок в строке, `order` с 1. Тесты T-6105 test_seed_creates_six_lists_with_codes_and_names_from_plan_table,
test_seed_unique_fields_and_deadline_thresholds_30_or_30_and_7, test_seed_multiple_fields_record_target_equipment_and_money_in_rubles,
test_seed_license_number_field_has_hint_text_from_plan_table, test_seed_choice_values_per_plan_table_and_operator_without_values.

## 3. Ядро и записи точек `lists`

### 3.1. Новые и используемые функции ядра

| Что | Требование | Тесты |
|---|---|---|
| `core.services.permissions.role_ids(user) -> frozenset[int]` | публичная обёртка над закрытой `_role_ids` (факт): личные роли и роли из точки `role_sources` (роли узлов от `org`); у пользователя без ролей — пустое множество (план) | T-6102 test_unit_role_from_role_sources_grants_list_access_via_role_ids |
| Используемые службы ядра (факт, без изменений) | `apps.core.widgets.moscow_today()`, `parse_date`, `PortalDateInput`; `apps.core.services.accounts.pickable(query)`; `apps.core.services.uploads.reject_reason(name, data, size, max_file)` (возвращает `"too_big"`, `"executable"`, `"encrypted"` или `""`) и `uploads.store(data, name, "lists") -> StoredFile`; `apps.core.services.files.remove_paths(paths)`; `apps.core.services.file_response.download(stored, filename)`; `apps.core.services.audit.record(action, *, actor, object_type, object_id, before, after)`; `apps.core.services.table_file.read(content, *, max_bytes, max_rows, max_parts, max_unpacked, texts)` (восемь ключей `texts`, раздел 12.2); `apps.core.services.audit_search` — правило `FORMULA_START` и защита ячеек; шаблонный тег `{% person_name %}` (пометка «(уволен)», `span[data-dismissed="true"]`) | T-6106, T-6117, T-6118, T-6121 |
| `core.uploads.write_file` | единственная точка подмены сбоя записи файла (как CONTRACT-005, 5.8); помощник `support_lists.fail_file_write(monkeypatch)` | T-6121 test_storage_write_failure_rolls_back_removes_paths_and_does_not_return_500 |

### 3.2. Записи точек `lists` (`apps/lists/extensions.py`, план «Точки расширения»)

Функция `register_all()` регистрирует в таком порядке (решение контракта: порядок строк таблицы плана; `stand_reset`
последней): `menu_items`, `search_providers`, `card_sections`, `ticket_card_parts`, `notification_kinds`,
`file_purposes`, `audit_labels`, `unit_usage`, `role_usage`, `stand_reset`. Каждая регистрируемая функция определена в
модуле `apps.lists.*` (по `__module__` её снимает `without_lists()`).

| Точка | Регистрируемая функция и запись | Тесты |
|---|---|---|
| `menu_items` | `apps.lists.extensions.menu_items() -> list[dict]`: `[{"permissions": (), "url": "/lists/", "title": "Списки", "icon": "icons/lists.html", "order": 8, "visible": access.sees_section}]` (без `badge`) | T-6102 test_menu_item_lists_has_order_8_empty_permissions_and_is_visible_by_sees_section; T-6126 test_lists_registers_menu_8_search_50_card_70_ticket_part_20 |
| `search_providers` | `apps.lists.services.search.search_providers() -> list[SearchProvider]`: `[SearchProvider(key="lists", title="Списки", order=50, search=search, count=count, available=access.sees_section)]` | T-6122 test_lists_provider_is_registered_with_key_title_order_50_after_units |
| `card_sections` | `apps.lists.card.card_sections(viewer, person) -> list[CardSection]`: нет строк — `[]`; иначе `[CardSection("lists-pinned", "profile", 70, "lists/_card_pinned.html", {"rows": rows})]` | T-6113 test_pinned_section_is_card_section_on_profile_tab_with_order_70_and_lists_pinned_anchor |
| `ticket_card_parts` | `apps.lists.ticket_parts.ticket_card_parts() -> list[TicketCardPart]`: `[TicketCardPart("lists-records", "section", 20, render)]`; `render(request, ref: TicketRef) -> str \| None` (раздел 5.7) | T-6114 test_ticket_card_part_registered_as_lists_records_section_20_after_knowledge_parts |
| `notification_kinds` | `apps.lists.notify_kinds.notification_kinds() -> list[NotificationKind]` — один вид (раздел 7) | T-6116 |
| `file_purposes` | `apps.lists.services.files.file_purposes() -> list[FilePurpose]`: `[FilePurpose("lists", still_waiting, clean, found)]` | T-6121 |
| `audit_labels` | `apps.lists.audit_labels.audit_labels()` в той же форме, что функция `audit_labels` модуля `knowledge` (факт): подписи действий, типов объектов и ключей раздела 8 | T-6123 test_audit_labels_cover_every_action_object_type_and_written_key |
| `unit_usage` | `apps.lists.services.links.unit_usage(unit_id: int) -> str \| None` (текст — раздел 12.1) | T-6113 |
| `role_usage` | `apps.lists.services.links.role_usage(role) -> str \| None` (текст — раздел 12.1) | T-6113 |
| `stand_reset` | `apps.lists.stand.stand_reset` (раздел 1.3) | T-6124 |

Своих событий шины `lists` не публикует; `role_sources`, `staff_directory`, `day_marks`, `home_notices`,
`mail_renderers`, `login_links`, `top_bar_items` не использует (T-6126 test_lists_publishes_no_bus_events_and_subscribes_only_to_user_dismissed,
test_lists_registers_notification_kind_file_purpose_audit_labels_unit_and_role_usage_stand_reset).

### 3.3. Подписка шины

| Что | Требование | Тесты |
|---|---|---|
| `core.user_dismissed` | обработчик `apps.lists.services.links.on_user_dismissed(**data)` (имя — решение контракта); удаляет строки `UserView` уволенного (`data["user_id"]`, как у прежних подписчиков); записи, где он указан, не трогает | T-6113 test_user_dismissed_removes_user_views_of_dismissed_and_keeps_records |

### 3.4. Выключение модулей в тестах (решение 21 задач)

| Что | Требование | Тесты |
|---|---|---|
| «Без `lists`» | `support_lists.without_lists()` — контекст: на время блока из всех точек реестра снимаются функции, у которых `__module__` начинается с `apps.lists`; `INSTALLED_APPS` не перезагружается (как `support_kb.without_knowledge`) | T-6102 test_without_lists_menu_has_no_lists_item; T-6122; T-6126; T-6138 |
| «Без `servicedesk`/`notify`/`org`» | `support_lists.without_app(monkeypatch, name)` — `name` из `"apps.servicedesk"`, `"apps.notify"`, `"apps.org"`; подменяет `django.apps.apps.is_installed` так, что для `name` он ложен, для прочих — как был; код `lists` спрашивает `apps.is_installed("apps.<имя>")` в момент вызова, а не при импорте | T-6102 test_without_org_unit_rights_do_not_apply_and_role_rights_stay; T-6114 test_without_servicedesk_record_card_has_no_related_tickets_and_link_urls_return_404; T-6115 test_reminder_without_notify_creates_no_notifications_and_still_cleans_up |
| Охрана `is_installed` (решение 55 задач) | для каждого из `servicedesk`, `notify`, `org`, который `lists` импортирует, в пакете `apps/lists` есть строка `apps.is_installed("apps.<имя>")` | T-6126 test_lists_has_is_installed_guard_for_each_of_servicedesk_notify_org_it_imports |

## 4. Прежние модули

### 4.1. `org.services.structure` (план)

| Функция | Требование | Тесты |
|---|---|---|
| `unit_chain_ids(user) -> frozenset[int]` | id узлов, где сотрудник состоит (строки `Membership`), и всех их предков по `Unit.path` (включая корень); без членства — пустое множество | T-6102 test_unit_chain_ids_contains_unit_and_ancestors_so_unit_right_covers_nested_units |
| `all_units() -> list[UnitRef]` | все узлы, по `path` | T-6113 test_people_and_units_pickers_return_up_to_20_rows_and_units_match_name_or_path |
| `unit_refs(ids) -> dict[int, UnitRef]` | id → `UnitRef(id, name, kind, path)` (факт `apps.org.services.refs`); несуществующих id в словаре нет | T-6106 test_unit_nonexistent_node_rejected |
| «Путь» узла в подсказке и загрузке | названия узлов цепочки от корня до узла включительно через « / » (решение контракта: `UnitRef.path` — цепочка номеров «/1/5/9/», а сотруднику нужен путь словами; корень включается, чтобы путь был однозначен) | T-6113, T-6118 test_preview_unit_by_name_or_path_ambiguous_is_row_error |
| Без `org` | права подразделений не действуют (`units` пусто), поле «подразделение» показывает «узел №<id>» (решение контракта: план говорит «показывает номер узла»), подсказка `/lists/units/` — 404 | T-6102 test_without_org_unit_rights_do_not_apply_and_role_rights_stay |

### 4.2. `servicedesk.services.public` (факт, без изменений)

`ticket_brief(user, number) -> TicketBrief | None` и `briefs(user, numbers) -> dict[int, TicketBrief]`;
`TicketBrief(number, subject, state, closed_with_resolution, resolution)`. Невидимые заявки `briefs` пропускает.
Строка «Связанные заявки» в карточке записи — «#<номер> <тема>, <состояние>» (план). Тесты T-6114.

### 4.3. `notify` (план)

| Что | Требование | Тесты |
|---|---|---|
| `apps.notify.services.kinds.external_text(kind, object_ref: str) -> str` | `kind.external_text_of(object_ref)`, если `external_text_of` задано, иначе `kind.external_text` | T-6116 test_notify_kinds_external_text_uses_external_text_of_and_falls_back_to_former_external_text |
| Два места чтения | `apps.notify.services.delivery.external_text(delivery)` (Telegram, MAX, Web Push) и тема письма в `apps.notify.services.mail.queue_item(delivery)` зовут `kinds.external_text(kind, delivery.notification.object_ref)`; пустая строка — прежний `FALLBACK_TEXT` | T-6116 test_delivery_external_text_and_mail_subject_have_no_record_or_list_name, test_telegram_max_and_webpush_send_generic_text_without_record_or_list_name |
| Создание уведомлений | `apps.notify.services.dispatch.create(kind_code, drafts) -> list[int]` (факт) — единственный вызов `notify` из `lists` | T-6116 test_deadline_dispatch_create_called_separately_for_readers_and_others |

### 4.4. `search.parse` (план)

`parse(q)` заполняет `ParsedQuery.text` — строку запроса без крайних пробелов; при `hint` `"short"` или `"long"` —
`text == ""` (как `words` и `raw`). Прочие поля и правила не меняются. Тесты T-6122 test_parse_fills_text_stripped_of_edge_spaces_and_empty_for_short_and_long_hints.

### 4.5. Границы (план, «Модуль и выключение»; T-6126)

`lists` импортирует из `servicedesk` только `apps.servicedesk.services.public`, из `notify` — только
`apps.notify.services.dispatch` (и `apps.core.extensions.NotificationKind`, `Draft` из ядра), из `org` — только
`apps.org.services` (модули `structure`, `refs`); моделей `org`, `servicedesk`, `notify`, `knowledge`, `search` не
импортирует. `core`, `org`, `servicedesk`, `notify`, `knowledge`, `search` не импортируют `lists`. Тесты
test_lists_does_not_import_models_of_org_servicedesk_notify_knowledge_search, test_lists_imports_servicedesk_only_through_services_public,
test_lists_imports_notify_only_through_services_dispatch, test_lists_imports_org_only_through_services,
test_core_org_servicedesk_notify_knowledge_search_do_not_import_lists.

## 5. Службы `lists`, исключения, подмены и помощники

Модули — `apps/lists/services/<модуль>.py`. Аргумент `lst` — объект `List`, `actor`, `user`, `viewer` — `core.User`.
Сигнатуры — решение контракта там, где план назвал только имя функции; отступления от формы плана оговорены в строке.

### 5.1. Исключения и общие типы (`apps/lists/services/errors.py`; модуль — решение контракта)

| Имя | Требование | Тесты |
|---|---|---|
| `ListsError(code, *, field="", params=None)` | отказ службы; `code` — ключ словаря `texts.TEXTS` (раздел 12); `field` — код поля (`"title"` у названия записи, `"name"`, `"description"` у списка и поля); `params` — словарь подстановок текста; `.message` — готовый текст | все тесты отказов |
| `ValuesInvalid(errors: dict[str, ListsError])` | подкласс `ListsError` (`code="values_invalid"` — контейнер отказов полей, своего текста в `TEXTS` нет): отказы нескольких полей формы записи сразу, ключ — код поля или `"title"` | T-6106, T-6108a |
| `RecordGone` | подкласс `ListsError`, `code="record_gone"` («Запись удалена», план) | T-6108a test_save_of_record_purged_during_edit_gives_200_form_with_record_deleted_not_404 |
| `RecordArchived` | подкласс `ListsError`, `code="record_archived"` («Запись в архиве») | T-6108a, T-6110, T-6121 |
| `VersionConflict(who, when)` | подкласс `ListsError`, `code="version_conflict"`; `who` — `User` (`updated_by`), `when` — `updated_at` (план) | T-6108a test_second_save_from_same_base_version_is_refused_with_who_and_moscow_time_as_200_form_with_input |

### 5.2. Замок списка (И1; решение плана о замке)

| Что | Требование | Тесты |
|---|---|---|
| `apps.lists.services.records.lock_list(list_id: int, *, shared: bool) -> None` | единственная функция замка списка (И1; имя — предложение Opus, закреплено контрактом); выполняет `cursor.execute("SELECT pg_advisory_xact_lock_shared(hashtext('lists.list'), %s)", [list_id % 2147483648])` при `shared=True` и `SELECT pg_advisory_xact_lock(hashtext('lists.list'), %s)` при `shared=False`; вызывается только внутри транзакции; зовут её все службы (`schema`, `records`, `archive`, `imports`, `files`, `reminders`, задание `refresh_vectors`) | T-6103, T-6104, T-6108a, T-6110, T-6112, T-6115, T-6119, T-6121 |
| Разделяемый | `records.create`, `records.save`, `archive.archive`, `archive.restore`, `archive.bulk_archive` (на каждую запись), `archive.purge`, `imports.confirm`, `files.attach`, `files.remove`, `reminders.run` (на каждую запись), порция задания `refresh_vectors` | те же |
| Исключительный | `schema.add_field`, `update_field`, `hide_field`, `show_field`, `delete_field`, `move_field`, `set_order`, `save_choices`, `save_access`, `delete_list` | T-6104 test_schema_and_access_changes_take_exclusive_list_lock_and_record_save_shared_lock_before_schema_read |
| Порядок замков | замок списка → `SELECT … FOR UPDATE` строки `lists_list` (только `create`, `imports.confirm`, `delete_list`) → `SELECT … FOR UPDATE` строки `lists_record`; у `imports.confirm`: замок списка → `FOR UPDATE` `lists_importjob` → `FOR UPDATE` `lists_list`; схема (`lists_field`) читается после замка | T-6108a test_create_takes_shared_list_lock_before_for_update_of_list_row_and_reads_schema_after_lock, test_save_takes_shared_list_lock_then_for_update_of_record_in_that_order; T-6119 test_confirm_lock_order_shared_list_lock_then_job_then_list_row_for_update |

### 5.3. `schema`

| Функция | Требование | Тесты |
|---|---|---|
| `create_list(*, name, description, actor) -> List` | пределы 100 и 500; дубль без учёта регистра — `ListsError("name_taken", field="name")`; `IntegrityError` ограничения `lists_list_name_ci_uniq` даёт тот же отказ; журнал `lists.list_created` | T-6103 |
| `update_list(lst, *, name, description, actor) -> List` | журнал `lists.list_changed` с «было / стало» (`name`, `description`) | T-6103, T-6123 |
| `delete_list(lst, *, actor) -> None` | исключительный замок, `FOR UPDATE` строки списка; отказы `list_has_records`, `list_referenced` (раздел 12.1); журнал `lists.list_deleted` | T-6103 |
| `can_delete_list(lst) -> ListsError \| None` | та же проверка без изменений — для доступности кнопки и пояснения (имя — решение контракта) | T-6103 test_delete_list_with_records_or_only_archived_records_rejected_and_button_unavailable_with_reason |
| `add_field(lst, *, name, type, actor, hint="", required=False, multiple=False, unique=False, show_in_table=False, default=None, currency=None, target=None, deadline=False, thresholds=()) -> Field` | свойство не своего типа — `ListsError("property_not_allowed", field=<свойство>)`; 51-е поле — `fields_limit`; новое обязательное в списке с записями — `required_new_with_records`; `currency` по умолчанию `RUB`; журнал `lists.field_created` | T-6103 |
| `update_field(field, *, actor, **changes) -> Field` | ключи `changes` — имена параметров `add_field`; правила поля с данными и пустого поля — план; журнал `lists.field_changed` | T-6104 |
| `hide_field(field, *, actor)`, `show_field(field, *, actor)` | признак `hidden`, `List.vectors_stale_since = now`, постановка `refresh_vectors` после фиксации (И2), журнал `lists.field_hidden` / `lists.field_shown`; у системного «Названия» строки `Field` нет — скрыть нечего | T-6104 |
| `delete_field(field, *, actor)` | только пустое поле (`has_data` ложно) — иначе `field_has_data`; журнал `lists.field_deleted` | T-6104 |
| `move_field(field, direction, *, actor)` | `direction` — `"up"` или `"down"`; меняет `order` с соседом | T-6103 test_up_down_arrows_and_order_post_change_order_of_form_card_and_default_columns |
| `set_order(lst, codes: list[str], *, actor)` | новый порядок по списку кодов; чужие и пропущенные коды — `ListsError("bad_order")` без изменений | T-6103 |
| `save_choices(field, items: list[tuple[int \| None, str]], *, actor) -> list[Choice]` | `items` — пары (id существующего или `None` у нового, название) в новом порядке; id, которых нет в `items`, удаляются (использованные — `archived=True`); архивный id в `items` возвращается из архива; журнал `lists.choices_changed` (`choices` — перечень названий не в архиве) | T-6104 |
| `save_access(lst, *, readers, editors, actor)` | `readers`, `editors` — списки пар `("role", id)` / `("unit", id)`; журнал `lists.access_changed` (`readers`, `editors` — названия ролей и подразделений) | T-6103, T-6123 |
| `visible_fields(lst) -> list[Field]` | поля с `hidden=False` по `order` (план) | раздел 6 |
| `all_fields(lst) -> list[Field]` | все поля по `order`, со скрытыми (имя места «явно через все поля» плана — решение контракта) | раздел 6 |
| `has_data(field) -> bool` | формула плана: ключ в `values` записей этого списка (в том числе в архиве), или строка `RecordFile` поля, или `Change.changes` с `{"field": код}` у записей этого списка | T-6104 test_field_with_data_in_record_archived_record_history_only_removed_file_in_history_or_file_only_is_not_deleted_or_retyped |

### 5.4. `values`, `unique`, `records`, `history`

| Функция | Требование | Тесты |
|---|---|---|
| `values.parse(field, raw, *, old=None, viewer, source="form") -> Parsed` | `Parsed(value, error)`: `value` — значение в форме хранения раздела 2.3 или `None` (пусто); `error` — `ListsError` или `None`; `raw` — строка или список строк (многозначные); `old` — сохранённое значение поля (правило «старое остаётся»); `source` — `"form"` или `"import"` (правила загрузки: сотрудник по почте или ФИО, подразделение по названию или пути, значение по названию, запись по названию или номеру, «Да»/«Нет», значения через «;») | T-6106, T-6118 |
| `values.display(field, value, viewer) -> str` | строка показа: сотрудник — ФИО и « (уволен)» у уволенного; значение из архива значений — его название; запись — «Название — №N», у записи в архиве — с « (в архиве)», у записи нечитаемого списка — «запись недоступного списка»; деньги — «1 234,50 ₽» (раздел 12.4); дата — «ДД.ММ.ГГГГ»; дата и время — «ДД.ММ.ГГГГ ЧЧ:ММ» по Москве; да/нет — «Да» / «Нет»; несколько значений — через «; » | T-6106 test_display_* |
| `unique.normalize(field, value) -> str \| None` | раздел 2.3; пусто — `None` | T-6107 test_number_100_0_and_100_are_the_same_unique_value |
| `unique.find_owners(lst, field, norm_values) -> dict[str, Record]` | предварительная проверка до вставки (решения 28 и 45): нормализованное значение → запись-владелец (в том числе в архиве); точка подмены теста гонки; ею же пользуется предпросмотр загрузки | T-6107 test_race_with_bypassed_precheck_hits_db_constraint_in_savepoint_and_gives_field_refusal, test_precheck_reports_owner_record_including_archived_for_import_preview |
| `unique.sync(record, fields) -> None` | для каждого уникального поля из `fields` (видимого и скрытого) строки `UniqueValue` записи удаляются и вставляются во вложенной точке сохранения; `IntegrityError` — `ListsError("unique_taken", field=<код>, params={"number": <номер владельца>, "url": "/lists/<id>/<n>/"})`; внешняя транзакция остаётся рабочей | T-6107 test_every_value_write_path_calls_unique_sync, test_race_refusal_leaves_no_duplicate_row_and_outer_save_transaction_usable |
| `records.create(lst, data, actor, *, via_import=False) -> Record` | `data` — словарь «код → строка или список строк» и `"title"`; порядок — раздел 5.2; `vectors.refresh`, `history.write(created)`; отказы полей — `ValuesInvalid` | T-6108a |
| `records.save(lst, number, data, *, base_version, actor) -> SaveResult` | `SaveResult(record, changed: bool)`; первым аргументом — список и номер, а не запись (решение контракта: план требует, чтобы запись искала служба под замком, иначе «Запись удалена» недостижима); нет строки при `number < next_number` — `RecordGone`; в архиве — `RecordArchived`; версия — `VersionConflict`; скрытое за время правки поле с непустым значением — `ValuesInvalid` с кодом `field_hidden_meanwhile` у поля; без изменений — `changed=False`, ни версии, ни события | T-6108a |
| `history.write(record, kind, changes, actor, *, via_import=False) -> Change` | только `INSERT` строки `Change`; других функций изменения истории в `history` нет | T-6109 test_history_service_only_appends_rows |
| `history.page(record, offset) -> HistoryPage` | `HistoryPage(rows, next_offset)`: 50 строк новыми сверху (`at`, `id` по убыванию), `next_offset` — `offset + 50` или `None` | T-6109 test_history_fragment_pages_by_50_newest_first_with_show_more_offset |

### 5.5. `access`, `archive`, `links`, `tickets`

| Функция | Требование | Тесты |
|---|---|---|
| `access.scope(user) -> Scope` | `Scope(manage: bool, readable: frozenset[int], editable: frozenset[int])`; хранится в `user._lists_scope` на время запроса; не `active` — `Scope(False, frozenset(), frozenset())` | T-6102 |
| `access.can_read(user, lst)`, `can_edit(user, lst)`, `can_manage(user)`, `in_edit_set(user, lst)`, `sees_section(user)` | план; `in_edit_set` — только набор «Правят», без права управляющего | T-6102 test_in_edit_set_ignores_manager_right |
| `access.edits_any(user) -> bool` | правит хотя бы один список или управляет — для подсказок `/lists/people/` и `/lists/units/` (имя — решение контракта) | T-6102 test_people_and_units_pickers_are_404_for_who_neither_edits_nor_manages |
| `access.get_list(user, list_id) -> List`, `access.get_record(user, list_id, number) -> Record` | `Http404`, если нет или список не читается | T-6102 |
| `archive.archive(lst, number, *, actor) -> Record`, `archive.restore(…)` | разделяемый замок, `FOR UPDATE` записи, событие истории, `vectors.refresh`, журнал; уже в архиве при `archive` (или не в архиве при `restore`) — без изменений и без журнала | T-6110 |
| `archive.bulk_archive(lst, numbers: list[int], *, actor) -> BulkResult` | `BulkResult(archived: int, skipped: int)`; больше 50 номеров — `ListsError("bulk_too_many")` до любых изменений (решение 33 задач); каждая запись — своя транзакция; пропуск — «уже в архиве» и «удалена навсегда» | T-6112 |
| `archive.purge(lst, number, *, actor) -> None` | только запись в архиве (иначе `PermissionDenied` — ответ 403); ссылки — `ListsError("record_referenced", params={"links": [...], "hidden": K})`; одна транзакция, файлы с диска после фиксации; журнал `lists.record_purged` | T-6110 |
| `links.referrers(record, viewer) -> Referrers` | `Referrers(rows: list[Record], hidden: int)`: `rows` — ссылающиеся записи читаемых смотрящим списков (в том числе в архиве, в том числе из скрытых полей), `hidden` — число остальных; `viewer=None` — все без фильтра чтения (запрет удаления) | T-6113, T-6110 test_purge_refusal_links_referrers_of_readable_lists_and_counts_the_rest (подмена `access.can_read` — решение 37 задач) |
| `links.pinned(person, viewer) -> list[PinnedRow]` | `PinnedRow(record, list, field, link: bool)`; правила плана «Закреплённое» | T-6113 |
| `tickets.render(request, ref) -> str \| None` | раздел 5.7 | T-6114 |
| `tickets.pick(user, ticket_number, q) -> list[Record]` | до 10; план «Привязать» | T-6114 |
| `tickets.link(user, ticket_number, record_id) -> TicketLink`, `tickets.unlink(user, link_id) -> int` | `Http404` — нет записи, список не читается, заявка не видна; запись в архиве — `RecordArchived`; повтор — без второй строки; `unlink` возвращает номер заявки | T-6114 |
| `tickets.related(user, record) -> list[TicketBrief]` | `public.briefs` по номерам связей; без `servicedesk` — `[]` | T-6114 |

### 5.6. `grid`, `reminders`, `vectors`, задания

| Функция | Требование | Тесты |
|---|---|---|
| `grid.read(params, lst, viewer) -> GridParams` | `params` — `QueryDict` запроса; разбор раздела 10.3; коды — только из `visible_fields`; чужое — отбрасывается молча | T-6111 |
| `grid.records(lst, viewer, gp) -> QuerySet[Record]` | отбор, фильтры, поиск, сортировка с последним ключом `number`; без среза страницы; код поля — только параметр SQL: `qs.query.sql_with_params()` — кода нет в тексте, он в параметрах (решение 30 задач) | T-6111 test_grid_queryset_sql_has_field_code_only_among_params_not_in_query_text |
| `grid.columns(lst, viewer) -> list[str]` | коды столбцов: `UserView.columns` без скрытых и удалённых; нет строки — `["title", <видимые с show_in_table по order>]` | T-6112 |
| `reminders.select_candidates(today) -> list[Candidate]` | шаг 1 плана; `Candidate(record_id, list_id, field_id, due_date)`; точка подмены «между выборкой и замком» (решение 45 задач) | T-6115 |
| `reminders.run(today) -> RunResult` | шаги 1–5 плана (уборка — в конце); `RunResult(notified: int, failed: list[int])` — число созданных уведомлений и номера записей со сбоем; сбой записи — `logger.error` логгера `apps.lists.reminders` с номером записи и именем класса исключения, обход продолжается (имя функции — решение контракта: тесту нужен вызов с датой, команде — число уведомлений) | T-6115, T-6116, T-6124 |
| `apps.lists.tasks.remind_deadlines() -> None` | `reminders.run(moscow_today())`; если `failed` не пусто — после обхода `RuntimeError` с номерами записей | T-6115 test_reminder_failure_of_one_record_logged_with_number_and_class_loop_continues_and_task_fails_at_end; T-6125 |
| `vectors.refresh(record_ids) -> None` | единственное место расчёта вектора (план); литерал SQL с `unnest(%s::bigint[], %s::text[], %s::text[])`; текст — `title` (A) и видимые `string`/`text` (C, первые 100 000 знаков) | T-6122 test_vector_has_title_weight_a_and_visible_text_fields_weight_c_capped_at_100000_chars |
| `apps.lists.tasks.refresh_vectors(list_id: int, field_id: int) -> None` (И2) | задание очереди `maintenance`; ставится в `transaction.on_commit` вызовом `django_rq.get_queue("maintenance").enqueue(refresh_vectors, list_id, field_id, job_timeout=600)`; запоминает `vectors_stale_since` в начале; пересчитывает записи списка, у которых поле заполнено (`values__has_key=<код>`; у поля «файл» — есть `RecordFile`), порциями по 500 по возрастанию `id`, каждая порция — своя транзакция под разделяемым `lock_list`; в конце снимает признак, только если он не изменился с начала (`filter(pk=…, vectors_stale_since=<запомненное>).update(vectors_stale_since=None)`), иначе его снимет следующее задание; нет списка или поля — выходит без ошибки | T-6104, T-6122 test_vector_is_refreshed_on_create_save_archive_restore_import_hide_and_show |

### 5.7. Карточка заявки, этикетки, выгрузка, загрузка, файлы, поиск

| Функция | Требование | Тесты |
|---|---|---|
| `ticket_parts.render(request, ref)` (= `tickets.render`) | `None`, если `ticket_brief(user, ref.number)` пусто, сотрудник не читает ни одного списка или нет `servicedesk`; иначе фрагмент раздела (раздел 11.8) | T-6114 test_ticket_section_render_returns_none_when_viewer_reads_no_list, test_ticket_section_render_returns_none_for_invisible_ticket |
| `labels.qr_data_uri(url) -> str` | `"data:image/svg+xml;base64," + base64(qrcode.make(url, image_factory=SvgPathImage, box_size=10, border=4) в байтах SVG)`; сравнение — побайтно (решение 10 задач, факт T-6006) | T-6120 test_qr_matches_qrcode_generation_of_portal_url_card_address |
| `labels.card_url(record) -> str` | `settings.PORTAL_URL` без завершающей «/» + `/lists/<id>/<n>/`; без строки запроса | T-6120 test_qr_address_has_no_query_or_session_data |
| `export.build(lst, viewer, params) -> HttpResponse` | `export.LIMIT = 10000`; `count() > LIMIT` — `ListsError("export_too_many")`; иначе XLSX плана | T-6117 |
| `imports.upload(lst, actor, *, name, content) -> ImportJob` | `table_file.read` с пределами плана; отказ — `ListsError` с кодом раздела 12.2 | T-6118 |
| `imports.get_job(user, lst, job_id) -> ImportJob` | `Http404`: нет, другой список, другой автор, старше суток (`created_at < now - 1 день`) | T-6118 test_job_of_other_author_or_other_list_returns_404, test_job_older_than_one_day_is_404_and_edit_right_rechecked_on_each_step |
| `imports.auto_mapping(lst, header) -> dict[str, str]` | номер столбца (строкой) → код поля или `"title"` по названию без учёта регистра и крайних пробелов; поле «файл» не сопоставляется | T-6118 test_mapping_matches_columns_by_name_ignoring_case_and_edge_spaces |
| `imports.preview(job, mapping, actor) -> ImportJob` | заполняет `rows` и `state="preview"`; в базе записей не меняет; счётчики — `imports.counts(job) -> dict` с ключами `will_create`, `will_update`, `error` | T-6118 test_preview_changes_nothing_in_database_before_confirm, test_preview_shows_counts_will_create_will_update_with_errors |
| `imports.confirm(lst, job_id, actor) -> dict` | итог `{"created", "updated", "errors"}`; повтор при `state="done"` — прежний итог; журнал `lists.import_done` | T-6119 |
| `imports.sample(lst) -> bytes` | XLSX: первый лист — заголовки, второй — «Подсказки» (план) | T-6119 |
| `files.attach(lst, number, *, field_code, name, data, actor) -> RecordFile` | порядок проверок: запись (нет — `Http404`, в архиве — `RecordArchived`), поле «файл» видимое (иначе `Http404`), 20 файлов — `files_limit`, одиночное поле занято — `field_has_file`, `reject_reason` — `file_too_big` / `file_type_refused`; затем `uploads.store`, событие `file_added` | T-6121 |
| `files.remove(lst, number, file_id, *, actor) -> None` | `Http404` — файл не этой записи; в архиве — `RecordArchived`; событие `file_removed`; диск после фиксации | T-6121 |
| `files.still_waiting(stored)`, `files.clean(stored)`, `files.found(stored, signature)` | функции `FilePurpose` по образцу `knowledge/services/files.py`; `Heuristics.Encrypted.*` — строка `RecordFile` удаляется | T-6121 test_encrypted_heuristic_scan_removes_record_file_row |
| `search.search(user, parsed, limit, offset)`, `search.count(user, parsed)`, `search.parse_local(q) -> ParsedQuery` | раздел 9 | T-6122 |

### 5.8. Точки подмены для тестов гонок и сбоев (решения 6, 28, 37, 45 задач)

| Подмена | Что подменяется | Тесты |
|---|---|---|
| Обход предварительной проверки уникальности | `monkeypatch.setattr("apps.lists.services.unique.find_owners", lambda *a, **k: {})` — служба вставляет строку и упирается в ограничение базы | T-6107 |
| Между выборкой и замком | `support_lists.act_between_select_and_lock(monkeypatch, action)` оборачивает `reminders.select_candidates`: после настоящей выборки зовёт `action(candidates)` и возвращает выборку как была | T-6115 test_reminder_mark_inserted_by_other_run_between_select_and_lock_gives_no_duplicate_or_error и соседние |
| Сбой одной записи обхода | `monkeypatch` функции `apps.lists.services.reminders.notify_record(candidate, today)` (обработка одной пары «запись, поле» в своей транзакции под замком; имя — решение контракта) так, что для выбранной записи она поднимает исключение | T-6115 test_reminder_failure_of_one_record_logged_with_number_and_class_loop_continues_and_task_fails_at_end |
| Нечитаемый ссылающийся список | `monkeypatch.setattr("apps.lists.services.access.can_read", …)` ложно для одного списка (решение 37 задач); `links.referrers` зовёт `access.can_read` атрибутом модуля | T-6110 |
| Сбой записи файла | `support_lists.fail_file_write(monkeypatch)` — `core.uploads.write_file` поднимает `OSError` | T-6121 |
| ClamAV | `support_org.scan_clean`, `scan_found`, `scan_unavailable` | T-6121 |

### 5.9. Помощники `tests/support_lists.py` (пишет T-6101; без `@pytest.fixture`, код среза — внутри функций)

| Имя | Сигнатура и поведение | Кто зовёт |
|---|---|---|
| `PERMISSIONS_006` | `("lists.manage",)`; `TITLES_006 = {"lists.manage": "Управление списками"}` (решение 24 задач) | T-6105, T-6138 |
| `Session` | `NamedTuple(user, client)` (как `support_kb.Session`) | все |
| `as_reader(lst, **extra) -> Session` | сотрудник (`support.make_employee(**extra)`) с новой ролью `make_role`, которой выдан `grant_list(lst, role, "read")`; вошёл | все |
| `as_editor(lst, **extra) -> Session` | то же с `"edit"` | все |
| `as_manager(**extra) -> Session` | сотрудник с ролью, у которой право `lists.manage`; наборов списков нет | все |
| `make_list(name=None, *, description="", code="", created_by=None) -> List` | прямой записью; имя по умолчанию — «Список <n>» с уникальным n | все |
| `add_field(lst, type, name=None, *, required=False, multiple=False, unique=False, show_in_table=False, hidden=False, default=None, hint="", currency=None, target=None, deadline=False, thresholds=(), choices=(), code=None) -> Field` | прямой записью; `code` по умолчанию `f<next_field_no>` (счётчик растёт); `currency` у `money` по умолчанию `"RUB"`; `choices` — названия значений, `Choice.order` с 1; `settings` собирается из `currency`, `deadline`, `thresholds` | все |
| `choice_id(field, title) -> int` | id значения по названию | T-6106, T-6111 |
| `make_record(lst, title="Запись", values=None, *, archived=False, created_by=None, updated_by=None, version=1) -> Record` | прямой записью: номер из `next_number` (счётчик растёт), `values` как есть (форма хранения раздела 2.3); строки `UniqueValue` уникальных полей — своей нормализацией помощника по разделу 2.3; вектор — своим SQL помощника `set_vectors(record)` (как `support_kb.set_vectors`) | все |
| `archive(record, *, by=None) -> Record` | прямой записью `archived=True`, `archived_at=now`, `archived_by` | T-6110, T-6112 |
| `attach_file(record, field, name="акт.pdf", data=None, *, status="clean", uploaded_by=None, write=False) -> RecordFile` | строки `StoredFile(purpose="lists")` и `RecordFile`; `status` — `"pending"` («проверяется»), `"clean"` («чистый»), `"quarantine"` («карантин»); `write=True` пишет байты на диск (фикстура `protected_root`) | T-6110, T-6121 |
| `grant_list(lst, who, level) -> Access` | `who` — `core.Role` или `org.Unit`; `level` — `"read"` или `"edit"` | все |
| `without_lists()`, `without_app(monkeypatch, name)` | раздел 3.4 | T-6102, T-6114, T-6115, T-6122, T-6126 |
| `run_seed(using=None)`, `run_unseed(using=None)` | функции `seed`/`unseed` миграции `lists 0002` (решение 20 задач; как `support_kb.run_seed`) | T-6105, T-6124 |
| `clear_seed()` (`support_lists.clear_seed()`) | снимает строки `Access` стартовых списков, стартовые списки без записей (по кодам) и право `lists.manage` с его выдачей (решение 35 задач) | T-6103, T-6105 |
| `run_reminders(today) -> RunResult` | `apps.lists.services.reminders.run(today)` | T-6115, T-6116 |
| `capture_sql()`, `sql_of(func, *args, **kwargs)`, `assert_for_update(sqls, table)` | как в `support_kb` (повторный экспорт); таблицы — `lists_list`, `lists_record`, `lists_importjob` | все тесты замков |
| `ListLock` | `NamedTuple(kind, list_no)`: `kind` — `"shared"` или `"exclusive"`, `list_no` — второе число ключа | те же |
| `list_locks(sqls) -> list[ListLock]` | разбирает вызовы `pg_advisory_xact_lock[_shared](hashtext('lists.list'), N)` по порядку; `list_no(list_id) -> int` — `list_id % 2147483648` (И1: номер 3 000 000 000 даёт 852516352) | те же |
| `act_between_select_and_lock(monkeypatch, action) -> list` | раздел 5.8; возвращает список выданных выборок | T-6115 |
| `fail_file_write(monkeypatch, message="disk error") -> list` | раздел 5.8 | T-6121 |
| `moscow(year, month, day, hour=0, minute=0) -> datetime`, `moscow_text(moment) -> str` | время по Москве; текст «ДД.ММ.ГГГГ ЧЧ:ММ» | все |
| `xlsx_of(header, rows, *, sheet_title="Лист1") -> bytes`, `csv_of(header, rows, *, delimiter=";") -> bytes` | таблицы загрузки в памяти (XLSX — `openpyxl`, CSV — UTF-8) | T-6117, T-6118, T-6119 |
| `read_xlsx(content) -> list[list]`, `read_back(content) -> TableFile` | значения первого листа через `openpyxl.load_workbook`; то же через `core.table_file.read` с пределами плана | T-6117, T-6119 |
| `email_of(local="ivanov", domain="example.test")`, `phone_of(*groups)` | как в `support_kb` (решение 12 задач) | T-6113, T-6118 |
| `list_pages(lst, record) -> tuple[str, ...]` | адреса страниц среза для проверок «по-русски» и «без `style=`»: `/lists/`, `/lists/<id>/`, `/lists/<id>/settings/`, `/lists/<id>/settings/fields/`, `/lists/<id>/settings/access/`, `/lists/<id>/add/`, `/lists/<id>/<n>/`, `/lists/<id>/<n>/edit/`, `/lists/<id>/<n>/history/`, `/lists/<id>/import/`, `/lists/<id>/<n>/label/`, `/lists/<id>/labels/?n=<n>` | T-6125, T-6120 |

Факты T-6005 для тестов выгрузки и загрузки: текст, начинавшийся с `\r`, после обратного чтения начинается с `\n`
(ожидаемое значение пробы `\r` после чтения — с `\n`); `core.table_file.read` отбрасывает пустые ячейки в конце строки —
сопоставление столбцов и сравнение строк учитывают обрезку.

## 6. Перечень мест `visible_fields` и мест «все поля» (решение 27 задач)

Параметризованные тесты T-6104 test_visible_fields_places_from_contract_skip_hidden_field и
test_all_fields_places_from_contract_include_hidden_field идут по строкам этих таблиц: у списка есть видимое и скрытое
поле подходящего типа с непустыми значениями; тест вызывает место и проверяет наблюдаемое. Код каждого места берёт поля
только через `schema.visible_fields(lst)` или `schema.all_fields(lst)` (план).

### 6.1. Места `visible_fields` (скрытое поле не участвует)

| № | Место | Как тест вызывает | Что видит тест у скрытого поля |
|---|---|---|---|
| V1 | форма новой записи | GET `/lists/<id>/add/` | нет `[data-lists-field="<код>"]`, умолчание не подставлено |
| V2 | форма правки | GET `/lists/<id>/<n>/edit/` | нет поля ввода |
| V3 | проверка обязательности | `records.create` без значения скрытого обязательного | запись создана |
| V4 | карточка записи | GET `/lists/<id>/<n>/` | нет `[data-lists-value="<код>"]` (решение владельца 2026-10-25) |
| V5 | столбцы по умолчанию и сохранённые | `grid.columns` | кода нет |
| V6 | выбор столбцов и фильтров | GET `/lists/<id>/` | нет `[data-lists-column-choice="<код>"]` и `[data-lists-filter="<код>"]` |
| V7 | разбор параметров таблицы | `grid.read` с `f.<код>`, `sort=<код>` | параметр отброшен |
| V8 | значения фильтра | GET `/lists/<id>/filter-values/<код>/` | 404 |
| V9 | отбор «Истекает» и его показ | GET `/lists/<id>/?preset=expiring` | скрытое поле-срок не учитывается; без видимого поля-срока ссылки отбора нет |
| V10 | отбор «Закреплено за мной» и его показ | GET `/lists/<id>/?preset=mine` | то же для поля «сотрудник» |
| V11 | выгрузка | `export.build` | нет столбца, даже если код в `UserView.columns` |
| V12 | образец загрузки | `imports.sample` | нет заголовка и строки подсказки |
| V13 | сопоставление загрузки | `imports.auto_mapping` | столбец с названием скрытого поля не сопоставлен |
| V14 | вектор поиска | `vectors.refresh` | слово только из скрытого текстового поля не находит запись |
| V15 | точное совпадение поиска и привязки к заявке | `search.search`, `tickets.pick` | значение скрытого уникального поля не находит запись |
| V16 | этикетка | GET `/lists/<id>/<n>/label/` | значение скрытого уникального поля не показано; берётся следующее уникальное или «№ N» |
| V17 | «Закреплённое» | `links.pinned` | строки по скрытому полю «сотрудник» нет |
| V18 | напоминания: поля-сроки | `reminders.select_candidates` | пары со скрытым полем-сроком нет |
| V19 | напоминания: получатели из полей | `reminders.run` | сотрудник только из скрытого поля не получает |
| V20 | сохранение: присланное скрытое поле | `records.save` с непустым значением скрытого поля | `ValuesInvalid` с кодом `field_hidden_meanwhile` у поля |

### 6.2. Места «все поля» (скрытое поле участвует)

| № | Место | Как тест вызывает | Что видит тест у скрытого поля |
|---|---|---|---|
| A1 | уникальность | `unique.sync` | строки `UniqueValue` скрытого уникального поля есть, повтор — отказ |
| A2 | включение «Уникального» и «Обязательного», выключение «несколько» | `schema.update_field` | проверка идёт по всем записям, в том числе в архиве |
| A3 | «поле с данными» | `schema.has_data` | истинно по скрытому полю с данными |
| A4 | предел 50 полей | `schema.add_field` | скрытые считаются |
| A5 | «Ссылаются на эту запись» и запрет удаления навсегда | `links.referrers`, `archive.purge` | ссылка из скрытого поля учитывается |
| A6 | `unit_usage` | `links.unit_usage` | записи со скрытым полем «подразделение» считаются |
| A7 | история записи | GET `/lists/<id>/<n>/history/` | строки по скрытому полю показаны |
| A8 | вкладка «Поля» | GET `/lists/<id>/settings/fields/` | скрытое поле в сетке с кнопкой «Показать» |
| A9 | удаление списка | `schema.delete_list` | скрытое поле другого списка с `target` на этот запрещает удаление |

## 7. Вид уведомления `lists.deadline` и таблица «код вида → модуль»

### 7.1. Запись вида (`apps/lists/notify_kinds.py`; план)

| Поле | Значение | Тесты |
|---|---|---|
| `code` | `"lists.deadline"` | T-6116 test_deadline_kind_registered_with_title_module_default_channels_order_60_and_no_coalesce |
| `title`, `module` | `"Срок в записи списка"`, `"Списки"` | то же |
| `events`, `build` | `()`, прежнее значение по умолчанию (вид создаёт задание прямым `dispatch.create`) | то же |
| `external_text` | `"Истекает срок в записи списка"` (решение контракта: запасной текст на случай чтения без `external_text_of`) | T-6116 |
| `external_text_of` | `deadline_external_text(object_ref) -> str`: порог 0 — «Срок в записи списка наступил», иначе — «Истекает срок в записи списка» | T-6116 test_deadline_external_text_of_reached_for_zero_threshold_and_expiring_otherwise |
| `default_channels`, `mandatory`, `available` | `("portal", "email")`, `False`, `lambda user: True` | T-6116 test_deadline_kind_available_and_shown_in_my_notifications_to_employee_without_list_rights |
| `still_relevant` | `deadline_still_relevant(user_id, object_ref) -> bool`: получатель не уволен (`state != "dismissed"`) и запись существует; доступ к списку не проверяется | T-6116 test_still_relevant_false_for_dismissed_recipient_or_deleted_record, test_still_relevant_true_for_recipient_without_list_access |
| `order`, `coalesce` | `60`, `False` | T-6116 |

### 7.2. Черновик уведомления (план; решение 53 задач)

| Что | Требование | Тесты |
|---|---|---|
| `object_ref` | `"lists.record:<id записи>:<id поля>:<порог>"`; при id до 10 цифр и пороге до 3 цифр — не длиннее 38 знаков (решение 38 задач) | T-6116 test_deadline_object_ref_has_record_field_threshold_and_fits_38_chars_with_10_digit_ids |
| `Draft.text` | «Истекает срок: <список> — <название>: <поле> <ДД.ММ.ГГГГ>» при пороге больше 0; «Срок наступил: <список> — <название>: <поле> <ДД.ММ.ГГГГ>» при пороге 0; дата — дата срока | T-6116 test_deadline_portal_text_expiring_has_list_record_field_and_date_dd_mm_yyyy, test_deadline_portal_text_reached_on_threshold_zero |
| Обрезка | каждое из трёх названий длиннее 100 знаков — первые 99 знаков и «…» (итого 100); затем строка длиннее 300 — первые 299 знаков и «…» (решение 53 задач, решение Opus) | T-6116 test_deadline_text_with_list_record_and_field_names_of_max_length_cuts_each_to_100_with_ellipsis_and_whole_text_to_300 |
| `Draft.url` | читающему список — `/lists/<id>/<n>/`; остальным — `/me/#lists-pinned`; `dispatch.create` зовётся отдельно для каждой группы (одна группа пуста — вызова нет) | T-6116 test_deadline_link_to_record_card_for_list_reader_and_to_pinned_section_for_others, test_deadline_dispatch_create_called_separately_for_readers_and_others |
| Тема письма и внешние каналы | `kinds.external_text(kind, object_ref)` — без названий записи и списка | T-6116 |

### 7.3. Таблица «код вида → модуль» (решение 62 задач; порядок каталога — по `order`)

| `order` | Код | Название | Модуль |
|---|---|---|---|
| 10 | `servicedesk.new_in_queue` | Новая заявка в моей очереди | Сервис-деск |
| 20 | `servicedesk.assigned` | Мне назначили заявку | Сервис-деск |
| 30 | `servicedesk.requester_replied` | Заявитель ответил | Сервис-деск |
| 40 | `servicedesk.reply_failed` | Ответ заявителю не ушёл | Сервис-деск |
| 50 | `knowledge.comment_on_my_article` | Новый комментарий к моей статье | База знаний |
| 51 | `knowledge.my_article_changed` | Мою статью изменили | База знаний |
| 52 | `knowledge.rubric_subscription` | Статья в рубрике по подписке | База знаний |
| 60 | `lists.deadline` | Срок в записи списка | Списки |
| 110 | `core.new_device` | Вход с нового устройства | Ядро |
| 120 | `core.password_changed` | Пароль изменён | Ядро |
| 130 | `core.second_factor_reset` | Второй фактор сброшен | Ядро |
| 200 | `notify.channel_unbound` | Канал отвязан | Уведомления |

Строки 1–7 и 9–12 — факт кода после среза 005; строка `lists.deadline` — план. «Мои уведомления» показывают строку
«Срок в записи списка» каждому сотруднику (`available` истинно, вид не обязательный) с отметками «на портале» и
«почта» по умолчанию; Push — по прежним правилам каналов среза 004 (T-6138, решение 57 задач).

## 8. Журнал (план, «Журнал»)

### 8.1. Коды, типы, ключи

| Действие | Код | `object_type`, `object_id` | Ключи `before` / `after` |
|---|---|---|---|
| Создание списка | `lists.list_created` | `lists.list`, id списка | `after`: `name`, `description` |
| Переименование, описание | `lists.list_changed` | `lists.list` | изменённые из `name`, `description` |
| Удаление списка | `lists.list_deleted` | `lists.list` | `before`: `name` |
| Права | `lists.access_changed` | `lists.list` | `list`; `readers`, `editors` — названия ролей и подразделений через «, » по алфавиту (подразделение без `org` — «узел №<id>») |
| Поле: добавление | `lists.field_created` | `lists.field`, id поля | `after`: `list`, `field` (название), `type` (подпись типа) и заданные свойства из `required`, `multiple`, `unique`, `show_in_table`, `default`, `hint`, `currency`, `target` (название списка), `thresholds` |
| Поле: изменение | `lists.field_changed` | `lists.field` | `list`, `field` и изменённые из `field`, `type`, `required`, `multiple`, `unique`, `show_in_table`, `default`, `hint`, `currency`, `target`, `thresholds` |
| Поле: скрыть, показать | `lists.field_hidden`, `lists.field_shown` | `lists.field` | `list`, `field`, `hidden` (`false`/`true`) |
| Поле: удаление | `lists.field_deleted` | `lists.field` | `before`: `list`, `field`, `type` |
| Значения списка значений | `lists.choices_changed` | `lists.field` | `list`, `field`, `choices` — названия значений не в архиве по порядку через «, » |
| Запись: в архив, вернуть, удалить навсегда | `lists.record_archived`, `lists.record_restored`, `lists.record_purged` | `lists.record`, id записи | `list`, `number`, `title` (без значений полей) |
| Итог загрузки | `lists.import_done` | `lists.import`, id задания | `after`: `list`, `file`, `created`, `updated`, `errors` |

Ключи — только из набора плана: `list`, `name`, `description`, `field`, `type`, `required`, `multiple`, `unique`,
`show_in_table`, `hidden`, `default`, `hint`, `currency`, `target`, `thresholds`, `choices`, `readers`, `editors`,
`number`, `title`, `created`, `updated`, `errors`, `file`; ключей `url`, `link`, `key`, `code` нет. Распределение ключей
по действиям — решение контракта по таблице плана. Правка записи, файлы, связь с заявкой, выгрузка, этикетка и поиск в
журнал не пишутся. Тесты T-6123, T-6103, T-6104, T-6110, T-6119.

### 8.2. Подписи (`apps/lists/audit_labels.py`)

Действия: «Создан список», «Изменён список», «Удалён список», «Изменены права списка», «Добавлено поле списка»,
«Изменено поле списка», «Скрыто поле списка», «Показано поле списка», «Удалено поле списка», «Изменены значения поля
списка», «Запись перенесена в архив», «Запись возвращена из архива», «Запись удалена навсегда», «Загрузка в список».
Типы объектов: `lists.list` — «Список», `lists.field` — «Поле списка», `lists.record` — «Запись списка»,
`lists.import` — «Загрузка в список». Ключи: `list` «Список», `name` «Название», `description` «Описание», `field`
«Поле», `type` «Тип», `required` «Обязательное», `multiple` «Несколько значений», `unique` «Уникальное»,
`show_in_table` «Показывать в таблице», `hidden` «Скрыто», `default` «Значение по умолчанию», `hint` «Подсказка»,
`currency` «Валюта», `target` «Целевой список», `thresholds` «Пороги срока», `choices` «Значения», `readers` «Читают»,
`editors` «Правят», `number` «Номер», `title` «Название записи», `created` «Создано», `updated` «Обновлено», `errors`
«С ошибками», `file` «Файл». Слова подписей — решение контракта; тест проверяет, что подпись есть у каждого кода, типа и
записанного ключа (T-6123 test_audit_labels_cover_every_action_object_type_and_written_key).

## 9. Поиск (план, «Поиск»)

| Что | Требование | Тесты |
|---|---|---|
| Поставщик | `SearchProvider("lists", "Списки", 50, search, count, available)`; `available` — `access.sees_section`; группа идёт после «Подразделений» (40) | T-6122 test_lists_provider_is_registered_with_key_title_order_50_after_units |
| `search(user, parsed, limit, offset) -> list[SearchRow]` | до `limit + 1` строк; сначала точные совпадения (`UniqueValue` видимых уникальных полей читаемых списков, записи не в архиве, `norm_value == unique-нормализация parsed.text`), затем без повторов записей `search @@ to_tsquery('russian', parsed.raw)` (`SearchQuery(parsed.raw, config="russian", search_type="raw")`), ранг по убыванию, затем `number`; `list_id__in=readable`, `archived=False`; у `parsed.hint` — `[]` | T-6122 test_results_order_exact_matches_first_then_rank_then_number, test_provider_returns_limit_plus_one_rows_and_exact_uncapped_count |
| Строка выдачи | `SearchRow(title=<название записи>, subtitle=<название списка>, url="/lists/<id>/<n>/")`; на странице поиска строка читается как «<название> — <список>» (решение контракта: поля `title`/`subtitle` записи ядра, как у прежних поставщиков) | T-6122 test_query_dell_finds_row_laptop_dell_dash_equipment_with_card_link |
| `count(user, parsed) -> tuple[int, bool]` | `(число, False)` — точное, без потолка; запись из точного совпадения и из `tsquery` считается один раз | T-6122 test_record_matched_exactly_and_by_tsquery_appears_once_in_results_and_count |
| Текст запроса | не пишется ни в базу, ни в журнал портала, ни в журнал приложения | T-6122 test_query_text_marker_is_absent_in_database_audit_and_app_log |
| `parse_local(q) -> ParsedQuery` | своя копия правил `search.parse` (2…200 знаков, слова `\w+` от 2 знаков, первые 8 слов, номер, `raw` вида `слово:* & …`, `text` без крайних пробелов, `hint` `"short"` / `"long"`); возвращает ту же запись ядра `apps.core.extensions.ParsedQuery` (решение контракта: так тест сравнивает её с `search.parse` на одной таблице запросов, а `lists` не импортирует `apps.search`) | T-6122 test_parse_local_matches_search_parse_on_query_table |
| Таблица запросов сверки | `"dell"`, `"  Dell  "`, `"д"`, `""`, `"ин-100"`, `"ИН-100"`, `"#42"`, `"42"`, `"5CD1234XYZ"`, `"один два три четыре пять шесть семь восемь девять"`, строка из 201 знака, строка из 200 знаков, `"a'b & c | !d :* (e)"` | T-6122 |
| Подсказки поиска внутри списка | `hint == "short"` — «Введите не меньше 2 знаков»; `hint == "long"` — «Запрос не длиннее 200 знаков» (тексты — те же, что `HINTS` страницы поиска, факт `apps/search/views.py`); показываются в `[data-lists-search-hint]`, условие поиска не применяется | T-6122 test_single_character_local_query_shows_enter_at_least_two_chars, test_local_query_longer_than_200_chars_shows_hint |
| Условие поиска в таблице | вектор (`search @@ …`) или точное совпадение, по «и» с отбором и фильтрами; при `preset=archive` — по записям архива | T-6122 test_local_query_combines_with_preset_and_state_in_repair_filter, test_local_query_with_archive_preset_searches_archived_records |
| Спецсимволы | `'`, `&`, `|`, `!`, `:`, `*`, `(` в запросе не дают ошибки | T-6122 test_tsquery_special_characters_in_query_do_not_raise |

## 10. Маршруты, поля форм, ответы, «адрес × кто»

Адреса, методы и «кто» — план («Контракты»); здесь — поля форм, параметры, форма ответа и коды. Имена маршрутов:
`app_name = "lists"`, имена — по последнему слову пути (`home`, `new`, `grid`, `columns`, `filter_values`, `export`,
`settings`, `fields`, `field_new`, `field_order`, `field_edit`, `field_hide`, `field_show`, `field_delete`, `field_up`,
`field_down`, `field_choices`, `access`, `delete`, `add`, `record`, `edit`, `history`, `archive`, `restore`,
`bulk_archive`, `purge`, `files`, `file`, `file_delete`, `label`, `labels`, `import`, `import_job`, `import_confirm`,
`sample`, `pick`, `people`, `units`, `ticket_pick`, `ticket_links`, `ticket_link_delete`) — решение контракта; тесты
ходят по путям.

### 10.1. Общие правила

| Что | Требование | Тесты |
|---|---|---|
| Вход | все адреса — `@login_required`: без входа GET и POST — 302 на `/login/?next=<путь>` | T-6102 test_anonymous_is_redirected_to_login_with_next_on_all_list_urls; T-6120 test_card_address_redirects_anonymous_to_login_and_back |
| Запрос HTMX | заголовок `HX-Request: true`; ответ — фрагмент без `<html>`; таблица — фрагмент сетки при `HX-Target: lists-grid` и заголовок `Vary: HX-Request` у ответа `/lists/<id>/` | T-6111 test_hx_target_lists_grid_returns_grid_fragment_with_vary_hx_request |
| Отказ службы на POST | всегда 200 (и на НХ) с формой или фрагментом, введённое остаётся; отказ у поля — `[data-error="<поле>"][data-code="<код>"]` рядом с полем (`<поле>` — код поля, `title`, `name`, `description`, `hint`, `thresholds`, `file`), общий отказ — `[role=alert][data-code="<код>"]` (соглашение срезов 001–005, CONTRACT-004, раздел 13); коды — ключи раздела 12 | все тесты отказов |
| Успех POST | обычный POST — 302 на адрес из 10.2; НХ-POST — 200 с заголовком `HX-Redirect: <тот же адрес>`, кроме адресов, у которых в 10.2 назван фрагмент | T-6103, T-6108a |
| 403, 404 | список не читается, запись, файл, связь, задание загрузки не существуют — 404, тело без данных объекта (как у несуществующего); список читается, действие не разрешено — 403 (план) | T-6102 |
| Карточка удалённой записи | номер меньше `next_number`, строки нет — 404 с текстом «Запись удалена» в теле (план) | T-6108b test_card_of_missing_record_with_number_below_next_number_is_404_record_deleted |
| Числа | `<int:…>` в путях; `page` — целое от 1 (иное — 1); `offset` — целое от 0 (иное — 0) | T-6109, T-6111 |

### 10.2. Поля форм и ответы по адресам (решение контракта, где не сказано иное)

| Путь | Поля и параметры | Успех; особые ответы |
|---|---|---|
| `/lists/new/` POST | `name`, `description` | 302 на `/lists/<id>/settings/` |
| `/lists/<id>/` GET | `preset`, `sort`, `dir`, `q`, `page`, `f.<код>`, `f.<код>.from`, `f.<код>.to`, `f.<код>.files` (план; разбор — 10.3) | 200 страница или фрагмент сетки |
| `/lists/<id>/columns/` POST | `columns` — повторяющееся, коды по порядку показа (`title` — системное) | 302 на `/lists/<id>/`; НХ — фрагмент сетки |
| `/lists/<id>/filter-values/<код>/` GET | `q` | 200 фрагмент `ul[data-lists-pick]`, до 20 строк; скрытое поле, поле не ссылочного типа (`choice`, `person`, `unit`, `record` — ссылочные) или нечитаемый целевой список — 404 |
| `/lists/<id>/export/` GET | параметры таблицы | 200 XLSX, `Content-Disposition: attachment; filename*=UTF-8''<название списка в процентной записи>.xlsx`; больше 10 000 — 200 страница таблицы с `[role=alert][data-code="export_too_many"]` |
| `/lists/<id>/settings/` POST | `name`, `description` | 302 на тот же адрес |
| `/lists/<id>/settings/fields/new/` POST и `…/<код>/` POST | `name`, `hint`, `type` (только при создании и у пустого поля), `required`, `multiple`, `unique`, `show_in_table`, `deadline` (флажки, значение `on`), `default` (строка; у даты — `today` или дата ДД.ММ.ГГГГ; у списка значений — id значения; у да/нет — `on`), `currency` (`RUB`, `USD`, `EUR`), `target` (id списка), `thresholds` — повторяющееся, до трёх целых, пустые отбрасываются | 302 на `/lists/<id>/settings/fields/` |
| `…/<код>/hide/`, `…/show/`, `…/delete/`, `…/up/`, `…/down/` POST | — | 302 на вкладку «Поля» |
| `…/fields/order/` POST | `codes` — повторяющееся, все коды полей в новом порядке | 302; НХ — 204 |
| `…/<код>/choices/` POST | пары повторяющихся `id` и `title` в новом порядке; у нового значения `id` пусто; архивный id среди `id` — возврат из архива | 302 на `/lists/<id>/settings/fields/<код>/` |
| `/lists/<id>/settings/access/` POST | `readers`, `editors` — повторяющиеся значения `role:<id>` или `unit:<id>` | 302 на тот же адрес |
| `/lists/<id>/delete/` POST | — | 302 на `/lists/` |
| `/lists/<id>/add/` POST и `/lists/<id>/<n>/edit/` POST | `title`; по полю — имя `<код>`: строка, текст, число, деньги — одно значение; дата — «ДД.ММ.ГГГГ» или ISO; дата и время — «ДД.ММ.ГГГГ ЧЧ:ММ» по Москве; да/нет — `on`; `choice`, `person`, `unit`, `record` — повторяющиеся id; у правки — скрытое `base_version` (план); поля «файл» в форме нет | 302 на `/lists/<id>/<n>/`; отказ — 200 с формой; GET правки записи в архиве — 200 страница с «Запись в архиве» без формы, POST правки записи в архиве — 200 с отказом «Запись в архиве» (решение 31 задач); POST правки удалённой — 200 с формой и «Запись удалена» |
| `/lists/<id>/<n>/history/` GET | `offset` | 200 фрагмент: строки и кнопка «Показать ещё» (11.6) |
| `/lists/<id>/<n>/archive/`, `…/restore/` POST | — | 302 на карточку |
| `/lists/<id>/bulk-archive/` POST | `n` — повторяющееся, номера | 200 страница (НХ — фрагмент) таблицы с итогом «В архив: N, пропущено: M» в `[data-lists-notice="bulk-result"]`; больше 50 — 200 с `[role=alert][data-code="bulk_too_many"]`, ничего не изменено |
| `/lists/<id>/<n>/purge/` POST | — | 302 на `/lists/<id>/?preset=archive`; ссылки — 200 карточка с `[role=alert][data-code="record_referenced"]`; не в архиве — 403 |
| `/lists/<id>/<n>/files/` POST (multipart) | `field` — код поля «файл», `file` — файл | 302 на карточку; НХ — фрагмент блока файлов (11.7); отказ — 200 с `[data-error="file"][data-code=…]` |
| `/lists/<id>/<n>/files/<file_id>/` GET | — | «чистый» — `X-Accel-Redirect`, `Content-Disposition: attachment; filename*=…`, `X-Content-Type-Options: nosniff` (`file_response.download`); «проверяется», «карантин», файл не этой записи — 404 |
| `/lists/<id>/<n>/files/<file_id>/delete/` POST | — | 302 на карточку; НХ — фрагмент блока файлов |
| `/lists/<id>/<n>/label/` GET; `/lists/<id>/labels/` GET | `n` — повторяющееся | 200; больше 100 номеров — 200 с `[role=alert][data-code="labels_too_many"]` без этикеток; несуществующие и удалённые навсегда номера пропускаются молча, записи в архиве печатаются (решение 39 задач) |
| `/lists/<id>/import/` POST (multipart) | `file` | 302 на `/lists/<id>/import/<job>/`; отказ — 200 с `[data-error="file"][data-code=…]`, задание не создаётся |
| `/lists/<id>/import/<job>/` POST | `map.<номер столбца с 0>` — код поля, `title` или пусто (не загружать) | 200 страница предпросмотра (11.9); задание не своё, другой список, старше суток — 404 (решение 31 задач) |
| `/lists/<id>/import/<job>/confirm/` POST | — | 200 страница итога; повтор — тот же итог; чужое задание, старше суток — 404 |
| `/lists/<id>/sample/` GET | — | 200 XLSX `filename*=UTF-8''<название списка> — образец.xlsx` |
| `/lists/<id>/pick/`, `/lists/people/`, `/lists/units/` GET | `q` | 200 фрагмент `ul[data-lists-pick]` > `li[data-pick-id="<id>"]`, до 20 строк; запись — «Название — №N», сотрудник — ФИО и должность (без почты), узел — название и путь |
| `/lists/ticket-pick/` GET | `ticket`, `q` | 200 фрагмент, до 10 `li[data-pick-id]`; заявка не видна — 404 |
| `/lists/ticket-links/` POST | `ticket`, `record` (id записи) | 200 фрагмент раздела целиком (`hx-swap="outerHTML"`); запись в архиве — 200 фрагмент с `[role=alert][data-code="record_archived"]`; нет записи, список не читается, заявка не видна — 404 |
| `/lists/ticket-links/<id>/delete/` POST | — | 200 фрагмент раздела; без видимости заявки или чтения списка — 404 (решение 31 задач) |

### 10.3. Разбор параметров таблицы (план; решение контракта — форма значений)

| Параметр | Значения | Тесты |
|---|---|---|
| `preset` | `all` (по умолчанию), `expiring`, `mine`, `archive`; иное — `all`; недоступный списку отбор — `all` | T-6112 |
| `sort` | код видимого поля, `title`, `number`; иное, поле «файл» и поле-ссылка на нечитаемый список — отбрасывается (порядок по `number`) | T-6111 |
| `dir` | `asc` (по умолчанию), `desc` | T-6111 test_column_header_link_toggles_dir_for_current_sort_column |
| `f.<код>` | `string`, `text` и `f.title` — подстрока без учёта регистра; `choice`, `person`, `unit`, `record` — id (повторяющееся — все значения по «и»); `bool` — `yes` или `no` | T-6111 |
| `f.<код>.from`, `f.<код>.to` | `number`, `money` — число с точкой или запятой; `date` — ДД.ММ.ГГГГ или ISO; `datetime` — «ДД.ММ.ГГГГ ЧЧ:ММ» по Москве, «до» включительно по минуте; неверное значение отбрасывается | T-6111 test_invalid_date_number_and_id_filter_values_are_dropped_without_server_error |
| `f.<код>.files` | `yes`, `no` (у поля «файл») | T-6111 test_file_filter_yes_and_no_by_presence_of_record_files |
| `q` | раздел 9 | T-6122 |
| `page` | 50 строк на странице, 51-я — признак следующей | T-6111 test_page_holds_50_rows_51st_row_marks_next_page_and_page_param_opens_it |

### 10.4. «Адрес × кто» (решение 31 задач; без адресов заявок — их проверяет T-6114)

Кто: «нет» — действующий сотрудник без прав на списки; «читает» — через роль или подразделение (в том числе
вложенное); «правит»; «управляет» — право `lists.manage` вне наборов списка. Уволенный, заблокированный, приглашённый
в наборах не входят в портал: для них тест проверяет `access.scope(user)` (пусто) и `access.get_list` (`Http404`).
Успех POST — «302». Адреса `…/settings/fields/<код>/…` — с кодом существующего поля.

| Адрес | нет | читает | правит | управляет |
|---|---|---|---|---|
| GET `/lists/` | 404 | 200 | 200 | 200 |
| GET, POST `/lists/new/` | 404 | 403 | 403 | 200 / 302 |
| GET `/lists/<id>/`, `…/filter-values/<код>/`, `…/export/` | 404 | 200 | 200 | 200 |
| POST `/lists/<id>/columns/` | 404 | 302 | 302 | 302 |
| GET, POST `/lists/<id>/settings/`, `…/settings/fields/…`, `…/settings/access/`; POST `/lists/<id>/delete/` | 404 | 403 | 403 | 200 / 302 |
| GET, POST `/lists/<id>/add/` | 404 | 403 | 200 / 302 | 200 / 302 |
| GET `/lists/<id>/<n>/`, `…/history/`, `…/label/`, `/lists/<id>/labels/?n=…`, GET файла | 404 | 200 | 200 | 200 |
| GET, POST `/lists/<id>/<n>/edit/`; POST `…/archive/`, `…/restore/`, `/lists/<id>/bulk-archive/`, `…/files/`, `…/files/<file_id>/delete/` | 404 | 403 | 200 / 302 | 200 / 302 |
| POST `/lists/<id>/<n>/purge/` (запись в архиве) | 404 | 403 | 403 | 302 |
| GET, POST `/lists/<id>/import/`, `…/import/<job>/`, POST `…/confirm/` (своё задание), GET `…/sample/` | 404 | 403 | 200 / 302 | 200 / 302 |
| GET `/lists/<id>/pick/` | 404 | 200 | 200 | 200 |
| GET `/lists/people/`, `/lists/units/` | 404 | 404 | 200 | 200 |

`/lists/new/` у «читает» и «правит» — 403, потому что раздел ему открыт, а действие нет; у «нет» — 404, потому что раздела
нет (решение контракта по общему правилу плана). Тесты T-6102 test_access_matrix_contract_urls_by_actor_return_200_403_404_per_table и соседние.

## 11. Зацепки `data-*` для приёмки (решение контракта, кроме названных планом и задачами)

Правила: только `data-*`, `id` и классы, которых нет у прежних блоков; без `role="status"`, `role="alert"`,
`data-error`, `data-warning` вне сообщений об отказах форм (решение 13 задач; 10.1); без `style=` и `on…=`. Названы
планом или задачами: `#lists-grid`, `.lists-grid`, `data-narrow="cards"`, `form[data-lists-search]`, `#lists-pinned`,
`data-qr-url` (решение 50 задач), `data-card-part` оболочки сервис-деска.

### 11.1. Общие

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `[data-lists-page="<имя>"]` | корень содержимого страницы: `home`, `new`, `grid`, `settings`, `fields`, `field`, `access`, `add`, `record`, `edit`, `archived-edit` (GET правки записи в архиве), `import`, `mapping`, `preview`, `summary`, `label`, `labels`, `gone` (404 «Запись удалена») | T-6140…T-6153 |
| `time[data-at]` | время по Москве, `datetime` — ISO, текст «ДД.ММ.ГГГГ ЧЧ:ММ» | T-6125, T-6109 |
| Пометка «уволен» | `{% person_name %}`: `span[data-dismissed="true"]` «ФИО (уволен)» | T-6106, T-6109, T-6141 |
| Пометка «в архиве» | `[data-lists-archived]` с текстом «в архиве» — у карточки, значения-ссылки, строки «Ссылаются», строки раздела заявки | T-6110, T-6113, T-6114 |
| «Запись недоступного списка» | `[data-lists-unavailable]` без ссылки и названия | T-6113, T-6117 |
| Отказы | `[data-error="<поле>"][data-code="<код>"]`, `[role=alert][data-code="<код>"]` | все |
| Пустые состояния | `[data-empty-state="lists"]` — пустая главная; `[data-empty-state="lists-grid"]` — пустая таблица | T-6103, T-6112 |
| Сообщения не об отказах | `[data-lists-notice="<имя>"]`: `bulk-result` (итог группового «В архив»), `vectors-stale` («Поиск по списку обновляется», И2), `import-summary` | T-6112, T-6104 |

### 11.2. Главная и настройка списка

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `li[data-list-id="<id>"]` | строка главной: `a[data-field="name"]` (адрес `/lists/<id>/`), `[data-field="description"]`, `[data-field="count"]` — число записей не в архиве цифрами | T-6102 test_home_shows_only_readable_lists_with_description_and_count_without_archive_manager_sees_all |
| `a[data-action="lists-create"]` | «Создать список» (`/lists/new/`), только управляющему | T-6103, T-6140 |
| `nav[data-lists-tabs] a[data-tab="main"\|"fields"\|"access"]` | вкладки «Основное», «Поля», «Права»; у текущей `aria-current="page"` | T-6103 test_create_list_opens_settings_with_tabs_main_fields_access_and_system_title |
| `[data-lists-fields-grid]` | сетка полей в блоке прокрутки `.lists-scroll`; строки `tr[data-field-code="<код>"]`, у системного «Названия» `tr[data-field-code="title"][data-system]` без кнопок; у поля — `[data-field="name"]`, `[data-field="type"]`, `[data-hidden="true"\|"false"]`, `[data-has-data="true"\|"false"]` | T-6103, T-6104 test_fields_tab_shows_hide_without_delete_and_type_for_field_with_data |
| Кнопки поля по состоянию | `button[data-action="field-up"\|"field-down"\|"field-hide"\|"field-show"\|"field-delete"]`, `a[data-action="field-edit"]`; у поля с данными нет `field-delete`, в форме поля нет выбора `type`; у скрытого — `field-show` вместо `field-hide`; `field-delete` открывает диалог подтверждения `dialog[data-lists-confirm]` | T-6104, T-6153 |
| `[data-lists-drag]` | ручка перетаскивания строки (скрипт `lists.js`, POST `…/fields/order/`) | T-6140 |
| Форма поля | `form[data-lists-field-form]`; свойства — `[data-prop="required"\|"multiple"\|"unique"\|"show_in_table"\|"default"\|"currency"\|"target"\|"deadline"\|"thresholds"]`; недоступных типу свойств в разметке нет | T-6103 test_field_form_shows_only_properties_of_its_type_and_file_has_no_required |
| Значения списка значений | `[data-lists-choices]`: `li[data-choice-id]`, архивные — `li[data-choice-id][data-archived]` с кнопкой `button[data-action="choice-restore"]` | T-6104, T-6153 |
| Права | `[data-lists-access="read"]`, `[data-lists-access="edit"]`: `li[data-subject="role:<id>"\|"unit:<id>"]` | T-6103, T-6152 |
| Удаление списка | `button[data-action="list-delete"]`; недоступна — атрибут `disabled` и пояснение `[data-lists-delete-reason]` с текстом отказа | T-6103 test_delete_list_with_records_or_only_archived_records_rejected_and_button_unavailable_with_reason |

### 11.3. Таблица записей

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `#lists-grid.lists-grid[data-narrow="cards"]` | контейнер сетки (цель `HX-Target`); строки `tr[data-record-number="<n>"]`, название — `a[data-field="title"]` на `/lists/<id>/<n>/`; ячейки `td[data-col="<код>"]` | T-6112 test_grid_markup_has_narrow_cards_container_and_lists_grid_class, test_grid_row_title_links_to_record_card_address_of_that_record |
| `[data-lists-presets] a[data-preset="all"\|"expiring"\|"mine"\|"archive"]` | ссылки отборов; у текущего `aria-current="page"` | T-6112 |
| `th[data-sort="<код>"] a` | заголовок со ссылкой сортировки; `[data-dir="asc"\|"desc"]` у текущего | T-6111 |
| `[data-lists-found]` | «Найдено: N» | T-6111 test_found_count_equals_count_of_same_filtered_queryset_and_is_always_shown |
| `[data-lists-filters]` | фильтры: `[data-lists-filter="<код>"]` | T-6112 test_hidden_field_is_absent_from_column_and_filter_choices |
| `dialog[data-lists-columns]` | выбор столбцов: `input[name="columns"][data-lists-column-choice="<код>"]` | T-6112 |
| `form[data-lists-search]` | строка поиска (`input[name="q"]`), подсказка `[data-lists-search-hint]` | T-6122, T-6151 |
| Флажки строк | `input[type="checkbox"][name="n"][value="<n>"][data-lists-row-check]` | T-6112, T-6142 |
| Групповые действия | `button[data-action="bulk-archive"]` (правящим), `button[data-action="bulk-labels"]` (читающим; ведёт на `/lists/<id>/labels/?n=…`) | T-6112 test_labels_action_is_offered_to_reader_and_leads_to_labels_page_with_checked_numbers |
| Кнопки таблицы | `a[data-action="record-add"]`, `a[data-action="import"]` (правящим), `a[data-action="export"]` (читающим) | T-6112 test_empty_list_shows_no_records_text_and_add_and_import_buttons_to_editor |
| Страницы | `a[data-action="next-page"]` с `page=N+1` | T-6111 |

### 11.4. Форма записи

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `form[data-lists-record-form]` | поля по `order`: `[data-lists-field="<код>"]`, у обязательных `[data-required]`; «Название» — `[data-lists-field="title"]`; скрытое `input[name="base_version"]` | T-6106, T-6141 |
| Скрытое за время правки | у поля `[data-lists-field="<код>"][data-hidden-meanwhile]` только для чтения и отказ `[data-error="<код>"][data-code="field_hidden_meanwhile"]` | T-6108a test_field_hidden_during_edit_with_nonempty_value_is_refused_with_hidden_mark_and_shown_read_only |
| Подсказки выбора | `input[data-lists-picker="people"\|"units"\|"record"]` с `hx-get` и паузой 300 мс; ответ — `ul[data-lists-pick]` | T-6113, T-6141 |

### 11.5. Карточка записи

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `[data-lists-record]` | корень карточки; `[data-lists-value="<код>"]` — значение видимого поля (многострочное — с `<br>`) | T-6108b |
| Кнопки | `a[data-action="record-edit"]`, `button[data-action="record-archive"]`, `button[data-action="record-restore"]`, `a[data-action="record-label"]`, `button[data-action="record-purge"]` (управляющему, только запись в архиве; подтверждение `dialog[data-lists-confirm]`) | T-6108b test_card_buttons_edit_archive_label_by_right_and_purge_only_for_manager_on_archived_record |
| `[data-lists-referrers]` | «Ссылаются на эту запись»: `li[data-record-ref="<id списка>:<n>"]` | T-6113 |
| `[data-lists-related-tickets]` | «Связанные заявки»: `li[data-ticket-number="<номер>"]` с текстом «#N Тема, состояние» | T-6114 |
| `[data-lists-history]` | место фрагмента истории | T-6109 |

### 11.6. История

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `li[data-change-kind="<kind>"]` | строка: `created`, `changed`, `imported`, `archived`, `restored`, `file_added`, `file_removed`; у `created` с `via_import` — `[data-via-import]`; автор, `time[data-at]`; изменения — `[data-change-field="<код>"]` с `[data-field="before"]` и `[data-field="after"]` | T-6109 |
| `button[data-action="more"][data-next-offset="<N>"]` | «Показать ещё»: `hx-get` на `…/history/?offset=N`, `hx-swap="outerHTML"` | T-6109 test_history_fragment_pages_by_50_newest_first_with_show_more_offset |

### 11.7. Файлы

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `[data-lists-files="<код поля>"]` | блок файлов поля: `li[data-file-id="<id>"][data-scan="pending"\|"clean"\|"quarantine"]`; у «чистого» — `a[data-action="file-download"]`; у остальных — пометка «проверяется» или «в карантине» без ссылки | T-6121, T-6149 |
| Кнопки | `form[data-action="file-attach"]` (`input[name="file"]`, `input[name="field"]`), `button[data-action="file-delete"]` (правящим, запись не в архиве) | T-6121 |

### 11.8. Карточка заявки и «Закреплённое»

| Зацепка | Где и значение | Тесты |
|---|---|---|
| Раздел заявки | оболочка сервис-деска `[data-card-part="lists-records"]`; внутри — `[data-lists-ticket-section]`, строки `li[data-ticket-link-id="<id>"]` с `a` на карточку записи и текстом «Название — Список», `button[data-action="ticket-unlink"]`; поле поиска `input[data-lists-picker="ticket"]` и кнопка `button[data-action="ticket-link"]` | T-6114, T-6146 |
| «Закреплённое» | `#lists-pinned[data-lists-pinned]` в `lists/_card_pinned.html`; строки `li[data-pinned-record]` «Название — Список — Поле»; ссылка только у списков, которые смотрящий читает | T-6113, T-6145 |

### 11.9. Загрузка, этикетки, поиск

| Зацепка | Где и значение | Тесты |
|---|---|---|
| Сопоставление | `select[name="map.<N>"][data-lists-map-column="<N>"]`; поля «файл» среди вариантов нет | T-6118 test_mapping_file_field_not_offered_and_not_accepted |
| Предпросмотр | `tr[data-import-row="<номер строки>"][data-result="will_create"\|"will_update"\|"error"]`, причина — `[data-field="reason"]`, номер записи — `[data-field="number"]`; счётчики `[data-import-count="will_create"\|"will_update"\|"error"]`; кнопка `button[data-action="import-confirm"]` | T-6118 |
| Итог | `[data-lists-notice="import-summary"]` с `[data-import-summary="created"\|"updated"\|"errors"]` | T-6119 |
| Этикетка | `[data-lists-label]` с `[data-field="list"]`, `[data-field="title"]`, `[data-field="value"]` (значение уникального поля или «№ N»); QR — `img[data-lists-qr][data-qr-url="<адрес карточки>"]` с `src="data:image/svg+xml;base64,…"` | T-6120 test_qr_is_img_with_svg_base64_data_uri_and_data_qr_url_attribute_holding_card_address |
| Лист этикеток | `[data-lists-labels-sheet]` — по одной `[data-lists-label]` на номер; класс печати `lists-labels`; `labels.css`: `@page { size: A4; margin: 10mm 9mm }`, сетка 3 × 7 (63,5 × 38,1 мм), `@media print` скрывает `#top-bar`, `.app-top-bar`, `#main-menu`, `.app-menu` (решение 59 задач) | T-6120 test_labels_css_a4_page_margins_3x7_grid_and_print_media_hides_app_top_bar_and_app_menu |
| Сквозной поиск | группа выдачи с ключом `lists` (разметка группы — прежняя страница поиска среза 005) | T-6122, T-6151 |

## 12. Тексты, которые проверяют тесты

Тексты — словарь `TEXTS` модуля `apps/lists/texts.py` (план: «одним словарём»); ключ словаря — код отказа
(`data-code`, `ListsError.code`). Подстановки — `str.format` с именами из фигурных скобок. Тест ищет текст в разметке
подстрокой, регистр как здесь. Числа с разрядами — с обычным пробелом U+0020 («10 000», «5 000»), как в CONTRACT-005
(раздел 12). Один тест среза (решение 25 задач) проверяет, что `TEXTS` содержит каждый ключ и текст разделов 12.1–12.3.

### 12.1. Дословно из SPEC-006 FR-546 и плана

| Код | Текст | Источник | Тесты |
|---|---|---|---|
| `unique_taken` | «Такое значение уже есть в списке» и рядом ссылка `a[href="/lists/<id>/<n>/"]` на запись-владельца | FR-546 | T-6107, T-6141 |
| `required` | «Обязательное поле» | FR-546 | T-6106, T-6141 |
| `too_long` | «Предел: {limit} знаков» (например «Предел: 500 знаков», «Предел: 10 000 знаков») | FR-546 | T-6103, T-6106, T-6108a |
| `required_new_with_records` | «Сначала заполните поле у всех записей» | FR-546 | T-6103, T-6153 |
| `unique_repeats` | «Значения повторяются: {items}»; `items` — до 10 пар «№<номер> — <значение>» через «; » (форма пары — решение контракта) | FR-546, план | T-6104, T-6153 |
| `required_missing` | «Не заполнено у записей: {items}»; `items` — до 10 «№<номер>» через «, » | FR-546, план | T-6104, T-6153 |
| `list_has_records` | «Нельзя удалить: есть записи» | FR-546 | T-6103 |
| `list_referenced` | «Нельзя удалить: на список ссылается поле {field} списка {list}» (первое такое поле по названию списка и полю) | FR-546 | T-6103, T-6153 |
| `unit_in_records` | «подразделение указано в {count} записях списков» — фраза `unit_usage`; ядро выводит «Узел нельзя удалить: <фраза>.» (план: слова уточнены под рамку ядра; числительное не склоняется — слова плана) | план, FR-546 | T-6113 |
| `unit_in_access` | «указано в правах списков: {names}»; при записях — через «; » после фразы `unit_in_records`; без записей — одна эта фраза; `names` — названия списков по алфавиту через «, » | план | T-6113 |
| `role_in_access` | «Нельзя удалить: указано в правах списков: {names}.» — фраза `role_usage`, ядро выводит её как есть | FR-546, план | T-6113, T-6153 |
| `record_referenced` | «Нельзя удалить: на запись ссылаются записи: {links}»; `links` — ссылки «Название — №N» на записи читаемых списков через «, »; остальные — числом: «и ещё {hidden}» после ссылок или одно число, если ссылок нет (форма числа — решение контракта) | FR-546, план | T-6110, T-6144 |
| `files_limit` | «У записи уже 20 файлов» | FR-546 | T-6121 |
| `file_too_big` | «Файл больше 20 МБ» | FR-546 | T-6121 |
| `file_type_refused` | «Файл такого типа не принимается» (и исполняемый, и архив с паролем) | FR-546 | T-6121 |
| `labels_too_many` | «Не больше 100 записей» | FR-546 | T-6120, T-6150 |
| `export_too_many` | «Уточните отбор: записей больше 10 000» | FR-546 | T-6117 |
| `import_too_big` | «Файл больше 5 МБ» | FR-546 | T-6118 |
| `import_too_many_rows` | «Строк больше 5 000» | FR-546 | T-6118 |
| `import_bad_format` | «Формат не поддерживается» | FR-546 | T-6118 |
| `version_conflict` | «Запись уже изменил {who} в {when}»; `who` — ФИО (`full_name`) сохранившего, `when` — «ДД.ММ.ГГГГ ЧЧ:ММ» по Москве (решение контракта: правки записей бывают в разные дни, одного времени мало) | FR-546, план | T-6108a, T-6141 |
| `record_archived` | «Запись в архиве» | FR-546 | T-6108a, T-6110, T-6114, T-6121 |
| `record_gone` | «Запись удалена» | FR-546 | T-6108a, T-6108b, T-6116 |
| `query_short` | «Введите не меньше 2 знаков» | FR-546 | T-6122, T-6151 |
| `home_empty` | «Списков пока нет. Список — это ваш реестр: оборудование, лицензии, договоры. Создайте первый» и кнопка «Создать список» управляющему | FR-546 | T-6103, T-6105 |
| `home_empty_reader` | «Вам пока не открыт ни один список» — хранится, недостижим, теста показа нет (решение плана, решение 31 задач) | FR-546 | — (только сверка словаря) |
| `grid_empty` | «В списке пока нет записей» | FR-546 | T-6112 |

### 12.2. Тексты плана, решений задач и И2, которых нет в FR-546

| Код | Текст | Источник | Тесты |
|---|---|---|---|
| `field_has_file` | «В поле уже есть файл» | план, «Файлы записи» | T-6121 |
| `import_repeat_in_file` | «Значение повторяется в строке {row}» | план, «Загрузка» | T-6118 |
| `import_no_title` | «Не указано название» | план, «Загрузка» | T-6118 |
| `choice_archived_exists` | «Такое значение есть в архиве значений — верните его» | план, «Поля» | T-6104 |
| `field_hidden_meanwhile` | «Поле скрыто администратором, значение не сохранится» | план, «Значения и форма записи» | T-6108a |
| `bulk_result` | «В архив: {archived}, пропущено: {skipped}» | план, «Таблица записей» | T-6112 |
| `bulk_too_many` | «Не больше 50 записей за раз» | решение 33 задач | T-6112 |
| `vectors_stale` | «Поиск по списку обновляется» | И2 | T-6104, T-6122 |
| `query_long` | «Запрос не длиннее 200 знаков» | план (правила SPEC-005 FR-443), текст — `HINTS` страницы поиска (факт) | T-6122 |
| Ключи `texts` для `table_file.read` | `too_big` → «Файл больше 5 МБ»; `too_many_rows` → «Строк больше 5 000»; `bad_format`, `bad_format_archive`, `bad_format_csv`, `not_utf8`, `xml_bomb`, `zip_bomb` → «Формат не поддерживается» (решение контракта: «бомба» — тоже неподдерживаемый файл, без ошибки 500) | план, факт восьми ключей | T-6118 test_upload_xlsx_bomb_unpacked_size_or_parts_refused_not_500 |

### 12.3. Тексты отказов, которых нет ни в спеке, ни в плане (решение контракта)

| Код | Где | Текст |
|---|---|---|
| `name_taken` | `name` списка | «Список с таким названием уже есть» |
| `field_name_taken` | `name` поля | «Поле с таким названием уже есть» |
| `choice_name_taken` | значение списка значений | «Такое значение уже есть» |
| `fields_limit` | общий | «Не больше 50 полей» |
| `choices_limit` | общий | «Не больше 200 значений» |
| `property_not_allowed` | свойство | «Это свойство недоступно для такого типа поля» |
| `thresholds_bad` | `thresholds` | «Порог — целое число от 1 до 365, не больше трёх порогов, без повторов» |
| `currency_bad` | `currency` | «Валюта: RUB, USD или EUR» |
| `target_required` | `target` | «Выберите список» |
| `field_has_data` | общий (удаление поля) | «Нельзя удалить: в поле есть данные» |
| `field_locked` | `type`, `currency`, `target` | «У поля с данными это не меняется» |
| `multiple_in_use` | `multiple` | «Нельзя выключить: есть записи с несколькими значениями» |
| `bad_order` | общий | «Порядок полей изменился, обновите страницу» |
| `line_break` | строка | «Без переносов строк» |
| `bad_number` | число, деньги | «Введите число» |
| `number_digits` | число | «Не больше 15 значащих цифр, до и после запятой — не больше 15» |
| `money_digits` | деньги | «Не больше 13 цифр до запятой и двух после» |
| `bad_date` | дата | «Введите дату ДД.ММ.ГГГГ» |
| `bad_datetime` | дата и время | «Введите дату и время ДД.ММ.ГГГГ ЧЧ:ММ» |
| `value_unavailable` | поле выбора | «Это значение выбрать нельзя» (уволенный, заблокированный, приглашённый, значение в архиве значений, запись в архиве, запись нечитаемого списка, запись не из целевого списка, значение другого поля, несуществующий узел) |
| `import_not_found` | строка загрузки | «Не найдено: {value}» |
| `import_ambiguous` | строка загрузки | «Неоднозначно: {value}» |
| `import_two_records` | строка загрузки | «Уникальные поля указывают на разные записи» |
| `import_time_missing` | строка загрузки | «Укажите время: ДД.ММ.ГГГГ ЧЧ:ММ» |
| `bad_file_field` | `field` загрузки файла | «Выберите поле для файла» |

В итоге строки предпросмотра причина — текст отказа с названием поля впереди: «<Поле>: <текст>»; у записи в архиве —
`record_archived` («Запись в архиве»), у повтора в файле — `import_repeat_in_file`.

### 12.4. Надписи (решение контракта, кроме названных планом и задачами)

| Что | Текст |
|---|---|
| Пункт меню, раздел | «Списки» (план) |
| Главная, настройка | «Создать список» (план); вкладки «Основное», «Поля», «Права» (план); «Добавить поле»; «Показать», «Скрыть», «Удалить», «Изменить»; наборы «Читают», «Правят» (план) |
| Таблица | отборы «Все», «Истекает», «Закреплено за мной», «Архив» (план); «Найдено: N»; «Добавить запись», «Загрузить из таблицы» (план); «Выгрузить в Excel» (решение 60 задач); «В архив», «Этикетки» (план); «Выбрать столбцы» |
| Карточка | «Изменить», «В архив», «Вернуть из архива», «Этикетка», «Удалить навсегда»; разделы «Файлы», «Связанные заявки», «Ссылаются на эту запись», «История» (план) |
| Пометки | «(уволен)» (`person_name`); «в архиве»; «запись недоступного списка» (план); «узел №<id>» (без `org`); у файлов — «проверяется», «в карантине» |
| Деньги | «1 234,50 ₽», «1 234,50 $», «1 234,50 €»: разряды — обычный пробел, запятая, знак валюты после пробела (план — «1 234,50 ₽») |
| Число | каноническое значение с запятой вместо точки, без разрядов: «12,5» |
| Да/нет | «Да», «Нет» (план) |
| Запись в значении и истории | «Название — №N» (план) |
| Этикетка без уникального значения | «№ N» (план) |
| История | `created` — «Создана»; `created` с `via_import` — «Создана загрузкой» (план); `changed` — «Изменена»; `imported` — «Изменено загрузкой» (план); `archived` — «Перенесена в архив»; `restored` — «Возвращена из архива»; `file_added` — «Добавлен файл <имя>» (план); `file_removed` — «Удалён файл <имя>» (план); «Показать ещё» (план) |
| Карточка заявки | заголовок раздела «Записи списков» (T-6100); «Привязать запись», «Отвязать» (план) |
| Загрузка | «Проверить» (план), «Загрузить»; счётчики «Будет создано: N», «Будет обновлено: N», «С ошибками: N»; итог «Создано: N, обновлено: M, с ошибками: K» (план — «создано N, обновлено M, с ошибками K») |
| Файлы | «Прикрепить», «Скачать», «Удалить» (решение 60 задач) |
| Образец | второй лист «Подсказки» (план); столбцы листа подсказок: «Поле», «Тип», «Обязательное», «Уникальное», «Значения», «Формат» |

## 13. Команды стенда, нагрузка, помощники приёмки

Образец — `e2e_kb_trash_shift` и `e2e_notify_tick` (CONTRACT-005, 13): проверка стенда — первым действием, до любого
чтения базы; вывод — одна строка `имя: ключ=значение …`.

### 13.1. `e2e_lists_shift --days N` (план)

| Что | Требование | Тесты |
|---|---|---|
| Модуль | `apps/lists/management/commands/e2e_lists_shift.py` | T-6124 |
| Стенд | `require_stand()` из `apps.lists.stand` — первой строкой `handle`; без `E2E_STAND=1` — `CommandError(REFUSAL)`, ничего не изменено | T-6124 test_e2e_lists_shift_refuses_without_e2e_stand_flag |
| `--days` | обязателен, целое 1…3650; вне пределов — `CommandError("Число вне пределов от 1 до 3650: N")` (форма текста — как у `e2e_kb_trash_shift`); не число — ошибка разбора argparse | T-6124 test_e2e_lists_shift_accepts_1_and_3650_days, test_e2e_lists_shift_rejects_0_and_3651_days_with_command_error |
| Сдвиг | значения всех полей-сроков (`type="date"`, `settings.deadline` истинно, в том числе скрытых) всех записей и `ReminderSent.due_date` — на N дней назад прямой записью (`queryset.update`) без `save()`: `version`, `updated_at`, история и журнал не меняются | T-6124 test_e2e_lists_shift_moves_deadline_values_and_reminder_due_dates_back_without_save, test_e2e_lists_shift_keeps_history_audit_and_version_untouched |
| Обход | затем `reminders.run(moscow_today())` в процессе команды | T-6124 test_e2e_lists_shift_runs_remind_deadlines_after_shift |
| Вывод | одна строка `lists_shift: days=<N> shifted=<число записей, у которых изменено хотя бы одно значение> notified=<RunResult.notified>` | T-6124 test_e2e_lists_shift_prints_single_line_with_days_shifted_and_notified; T-6140 |

### 13.2. Нагрузка (план, «Нагрузка»)

| Что | Требование | Тесты |
|---|---|---|
| `fill_lists.py` | `backend/tests/load/fill_lists.py`; без `E2E_STAND=1` — `sys.exit("Скрипт работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено.")` до импорта моделей; шесть списков, 10 000 записей в «Оборудовании», всего 50 000, добор до цели; строка итога `fill_lists: lists=<число> records=<число>` | T-6125 test_load_suite_has_fill_lists_script_requiring_stand_flag_and_lists_user_class |
| `ListsUser` | класс в `backend/tests/load/locustfile.py` рядом с `KnowledgeUser`; тест проверяет наличие по тексту файла | то же |

### 13.3. Помощники приёмки `tests/e2e/helpers_lists.py` (пишет T-6140)

Имена из строки T-6140: `make_list_reader`, `make_list_editor`, `make_list_manager` (роли), `shift(days)` — обёртка над
`e2e_lists_shift` через `helpers_sd._stand_command`, разбирает строку вывода 13.1 и возвращает словарь
`{"days": N, "shifted": …, "notified": …}`. Остальные имена (создание списка, полей и записей через интерфейс, загрузка
файла и ожидание «чистый», EICAR из частей, Mailpit, `fakebots`, сверка QR по `data-qr-url`, ширина 360 px) называет
T-6140 в своём отчёте; прежние помощники — `helpers.py`, `helpers_sd.py`, `helpers_org.py`, `helpers_notify.py`,
`helpers_kb.py`. Сброс стенда перед кругом — `helpers_sd.reset_stand_and_relogin()` (CONTRACT-003, 8.3).

## 14. Что меняется в прежних контрактах (для T-6138)

Сами `CONTRACT.md`, `CONTRACT-002.md` … `CONTRACT-005.md` не правятся (решение 4 задач; план). Здесь — какие их строки
устаревают со срезом 006 и чем заменяются. Номера строк — по деревьям на 2026-10-25 (после среза 005); «Было» —
сокращённый текст строки. Точные правки тестов — `crm-work/slice006/tasks/impact.md` и строка T-6138.

### 14.1. `CONTRACT-005.md`

| Строка | Было | Стало |
|---|---|---|
| 96 | `INSTALLED_APPS` … в конце списка: `"apps.notify"`, затем `"apps.knowledge"`, затем `"apps.search"`; сброс стенда сначала `knowledge` | в конце: `"apps.notify"`, `"apps.knowledge"`, `"apps.lists"`, `"apps.search"`; сброс стенда — сначала `lists`, затем `knowledge` (раздел 1.1, 1.3) |
| 104 | `purge_trash` — семнадцатая запись `register(...)` | `purge_trash` — семнадцатая, `lists_reminders` — восемнадцатая (раздел 1.2) |
| 105 | новый `location` `^/kb/[0-9]+/files/$` с `55m` (третий шаблон с `55m`) | плюс четвёртый — `^/lists/[0-9]+/[0-9]+/files/$` (раздел 1.2) |
| 116–117 | функция `knowledge` в `stand_reset` идёт первой | первой идёт `apps.lists.stand.stand_reset`, второй — `knowledge` (раздел 1.3) |
| 206 | `knowledge` — единственный, кто регистрируется в `ticket_card_parts` | в `ticket_card_parts` регистрируются `knowledge` (порядок 10) и `lists` (`lists-records`, порядок 20) (раздел 3.2) |
| 219 | `ParsedQuery` — `words`, `number`, `raw`, `hint` | плюс `text: str = ""` последним (раздел 2.1) |
| 223 | `NotificationKind.coalesce` — последнее поле записи | `coalesce` — двенадцатое, последнее — `external_text_of` (тринадцатое) (раздел 2.1) |
| 547 | порядок каталога: после видов сервис-деска (10–40) и до видов ядра (110–130) и `notify` (200) | то же для видов базы знаний; между ними и ядром — `lists.deadline` (60) (раздел 7.3) |
| 960–961 | числа среза 005: семнадцать точек, одиннадцать видов, пятнадцать прав, семнадцать заданий cron; пункт меню «База знаний» `order` 7; поле `NotificationKind.coalesce` | числа среза 006: семнадцать точек, двенадцать видов, шестнадцать прав, восемнадцать заданий cron, двенадцать пунктов меню администратора («Списки» `order` 8), тринадцать полей `NotificationKind` (раздел 1.4) |

### 14.2. `CONTRACT-004.md`, `CONTRACT-003.md`, `CONTRACT-002.md`, `CONTRACT.md`

| Файл и строка | Было | Стало |
|---|---|---|
| `CONTRACT-004.md` 201 | число прав после установки — 13 (в CONTRACT-005 уточнено до 15) | шестнадцать: прежние пятнадцать и `lists.manage` (раздел 1.4) |
| `CONTRACT-004.md` 215 | `NotificationKind`: поля по порядку … `order: int = 0` (в CONTRACT-005 добавлено `coalesce`) | плюс `coalesce`, затем `external_text_of: Callable[[str], str] \| None = None` последним |
| `CONTRACT-004.md` 241 и далее (таблица видов) | восемь видов (в CONTRACT-005 — одиннадцать) | двенадцать видов, таблица — раздел 7.3 |
| `CONTRACT-003.md` 108 | `location` с `55m` — `location = /request/` и `location ~ ^/tickets/(new/\|[0-9]+/reply/)$` (в CONTRACT-005 добавлен `kb`) | плюс `^/lists/[0-9]+/[0-9]+/files/$` |
| `CONTRACT-002.md` 127 | элементы `permissions.menu_for` и порядки пунктов | форма элемента та же; у администратора двенадцать пунктов, «Списки» (`/lists/`, `icons/lists.html`, `order` 8) между «Базой знаний» и «Сотрудниками» |
| `CONTRACT.md` 103 | меню: ссылки ядра видны по праву | без изменений для адресов ядра; пункт «Списки» виден по `access.sees_section` (раздел 3.2), тесты среза 001 пунктов по праву не считают |

### 14.3. Перечень правок прежних тестов T-6138 (по строке T-6138 и `impact.md`; строки — по коммиту e33b7d4, при сдвиге искать по утверждению — решение 49 задач)

| № | Тест (файл:строка) | Было | Стало |
|---|---|---|---|
| 1 | `tests/test_kb_deploy.py:117` | `INSTALLED_APPS[-3:] == [notify, knowledge, search]` | `[-4:] == ["apps.notify", "apps.knowledge", "apps.lists", "apps.search"]` |
| 2 | `tests/test_kb_deploy.py:575-579` | `apps.knowledge.stand` последний в `stand_reset` | `apps.lists.stand` последний, `apps.knowledge.stand` предпоследний |
| 3 | `tests/test_notify_deploy.py:353-354` | `INSTALLED_APPS[-4:]` | `[-5:] == ["apps.servicedesk", "apps.notify", "apps.knowledge", "apps.lists", "apps.search"]` |
| 4–6 | `tests/test_kb_deploy.py:127`, `tests/test_notify_deploy.py:321`, `tests/test_sd_deploy.py:402` | 17 вызовов `register` | 18; в `tests/test_sd_deploy.py:391-396` задание `lists_reminders` сверяется отдельной строкой (`remind_deadlines`, `maintenance`, `0 5 * * *`, 600), не в цикле «имя = функция» |
| 7 | `tests/test_deploy_files.py:359-370` | три шаблона `location` с `55m` | четыре, четвёртый `^/lists/[0-9]+/[0-9]+/files/$` |
| 8 | `tests/test_permissions.py:33-34` | права администратора — `PERMISSIONS…PERMISSIONS_005` | плюс `PERMISSIONS_006` последним; строки 35–36 не меняются |
| 9 | `tests/test_sd_access.py:536-538` | 15 прав | 16 |
| 10 | `tests/test_org_permissions.py:137-150` | перечень и названия прав | плюс «Управление списками» только у администратора |
| 11 | `tests/test_org_permissions.py:676-686` | одиннадцать пунктов меню администратора | двенадцать: `"/lists/"` после `"/kb/"`, `order` 8, название «Списки», значок `icons/lists.html` |
| 12–13 | `tests/test_notify_catalog.py:23-42`, `:104-111`, `:142-143`, `:153` | `TABLE` — одиннадцать видов; поля `NotificationKind` — двенадцать | двенадцать видов (строка `lists.deadline`, модуль «Списки», `order` 60, каналы `("portal", "email")`); поле `external_text_of` последним, по умолчанию `None` |
| 14–20 | `tests/test_notify_catalog_2.py:226`, `:233`, `:302`, `:329`, `:474`, `:488-491`, `:505`, `:547` | строки таблицы видов у сотрудников | строка «Срок в записи списка» у каждого сотрудника, модуль «Списки», шесть ячеек Push |
| 21–23 | `tests/test_notify_prefs.py:207-211`, `:236`, `:495-496` | строки «Мои уведомления» | плюс строка «Срок в записи списка» |
| 24 | `tests/e2e/test_e04_my_settings.py` (строки 46–52, 278) | строки видов в `ROWS` | строка `lists.deadline` в `ROWS` последней, модуль — по таблице 7.3 |
| 25 | `tests/e2e/test_e12_criteria.py:54-62`, `:917-938` | `EXPECTED_CATALOG` — одиннадцать видов | двенадцать видов, обе таблицы (вариант выбирает Opus при показе диффа) |
| 26 | `tests/test_kb_boundaries.py:228-229` | `registered("ticket_card_parts") == []` при `without_knowledge()` | `support_lists.without_lists()` внутри `support_kb.without_knowledge()`, а не `without_registrations("apps.lists")` |
| 27 | `tests/test_kb_boundaries.py:272-274` | каталог без `knowledge` | каталог без `knowledge` содержит `lists.deadline` (или блок без `lists`; вариант выбирает Opus при показе диффа) |
| 28 | `tests/test_kb_boundaries.py:366-369` | все регистрации `ticket_card_parts` — `apps.knowledge` | регистрации — `apps.knowledge` и `apps.lists` |

Условные пункты (строка T-6138) заранее не правятся и проверяются после реализации: У1 `test_kb_tickets.py:376`, `:382`, `test_kb_boundaries.py:249`; У2 `test_sd_stand_restore.py`, `e2e_reset_stand`, `tests/e2e/test_s18_reset.py`; У3 `test_stack.py`, `test_date_field.py`; У4 `test_audit.py`, `test_accounts.py`, `test_notify_deploy.py`; У5 `test_core_uploads.py:438-449`; У6 `test_kb_boundaries.py:453-485`, `test_search_providers*.py`; У7 `test_notify_digest.py`, `test_notify_texts.py`, `test_kb_notify_2.py`, `test_notify_bots_2.py`, `test_notify_retention.py:518`; У8 `test_shell.py`, `tests/e2e/helpers.py`, `test_notify_pages.py`, `test_notify_boundaries.py`. Не правятся (план и `impact.md`): `test_kb_boundaries.py:478`, `test_kb_tickets.py:346-360`, `tests/e2e/test_o04_find_colleague.py`, `test_o_success_criteria.py`, `test_k10_search.py`, тесты `ParsedQuery` в `test_search_*`, `test_extensions.py`, `test_sd_boundaries.py` по составу `POINTS`; `tools/` не правится. Правило: каждая правка — только с разрешения владельца, по
одному тесту, с диффом; разрешение спрашивает Opus.

## 15. Вопросы и решения

Открытых вопросов к Opus у контракта нет: каждое место, где план и решения оставили выбор, закрыто решением контракта
ниже. Решения контракта — выбор автора контракта (исполнитель T-6100), ничьим решением владельца не являются; Opus
подтверждает их или меняет при проверке контракта до T-6101 (решение 2 задач).

### 15.1. Принятые чужие решения (не решения контракта)

| № | Что | Чьё |
|---|---|---|
| П1 | `records.lock_list(list_id, *, shared)`; ключ `list_id % 2147483648` параметром | И1 — решение Opus; имя предложил Opus, контракт его закрепил |
| П2 | `List.vectors_stale_since`, задание `refresh_vectors(list_id, field_id)` очереди `maintenance`, текст «Поиск по списку обновляется» | И2 — решение Opus по ответу владельца 2026-10-25 «Фоном»; имя поля предложил Opus |
| П3 | значения скрытого поля в карточке не видны | решение владельца 2026-10-25 |
| П4 | `created_by` стартовых списков пусто; QR сверяется побайтно; групповое «В архив» до 50 номеров; обрезка текста напоминания до 100 и 300 | решения 34, 10, 33, 53 задач (решения Opus, принятые подписью TASKS-006) |

### 15.2. Решения контракта

| № | Решение | Причина |
|---|---|---|
| К1 | общее исключение `ListsError(code, field, params)`, подклассы `ValuesInvalid`, `RecordGone`, `RecordArchived`, `VersionConflict` в `services/errors.py`; `code` — ключ `TEXTS` и `data-code` | одно соответствие «отказ службы → текст → разметка» для тестов и кода; так устроены прежние срезы |
| К2 | `records.save(lst, number, data, *, base_version, actor)` вместо `save(record, …)` | план требует, чтобы запись искала служба под замком: иначе «Запись удалена» недостижима |
| К3 | `schema.all_fields(lst)` — имя места «явно через все поля»; перечни мест V1–V20 и A1–A9 | решение 27 задач требует перечня; без имени функции тест не отличит место |
| К4 | `access.edits_any(user)` для подсказок людей и узлов | план задаёт правило «правит хотя бы один список или управляет», но не имя |
| К5 | `reminders.run(today) -> RunResult(notified, failed)`, `reminders.notify_record(candidate, today)`; задание зовёт `run(moscow_today())` и падает после обхода при сбоях | тесту нужен вызов с датой и точка подмены сбоя одной записи; команде стенда — число уведомлений |
| К6 | `search.parse_local(q)` возвращает `core.extensions.ParsedQuery` | тест сравнивает с `search.parse` на одной таблице; `lists` не импортирует `apps.search` |
| К7 | `SearchRow(title=<запись>, subtitle=<список>)` | строка плана «Название — Список» ложится на поля записи ядра без новых полей |
| К8 | имена `TextChoices`, ограничений и `related_name="+"` у ссылок записи на `User` | план не называет; образец имён — CONTRACT-005 |
| К9 | `next_field_no = 1` и `order` с 1 у стартовых списков | стартовые коды не вида `f<n>`, совпадения с новыми полями нет |
| К10 | путь узла — названия от корня через « / »; без `org` — «узел №<id>» | `UnitRef.path` — номера, сотруднику нужен путь словами; план говорит «показывает номер узла» |
| К11 | форма `ImportJob.rows` и нумерация строк файла с 2 | план называет состав строки, но не ключи; номер строки совпадает с программой таблиц |
| К12 | `\r\n` и `\r` в многострочном тексте хранятся как `\n` | план хранит переносы как `\n`; иначе длина считалась бы по-разному в форме и загрузке (факт T-6005 о `\r`) |
| К13 | поля форм, параметры, имена маршрутов, ответы НХ (раздел 10) | план задаёт адреса и часть параметров; тестам и коду нужен один выбор |
| К14 | `/lists/new/`: «нет» — 404, «читает»/«правит» — 403 | общее правило плана: раздел недоступен — 404, доступен, действие нет — 403 |
| К15 | зацепки `data-*` раздела 11, кроме названных планом и задачами | приёмка читает зацепки из разметки (решение 50 задач) |
| К16 | `unique_repeats` — «№N — значение» через «; »; `required_missing` — «№N» через «, »; `record_referenced` — «и ещё K» | план говорит «первые 10 — номер записи и значение» и «остальные числом», но не форму |
| К17 | `version_conflict` — время «ДД.ММ.ГГГГ ЧЧ:ММ» | правки записей бывают в разные дни |
| К18 | тексты раздела 12.3 и надписи 12.4 | в спеке и плане их нет, а тесты проверяют наличие причины у поля |
| К19 | ключи `table_file` для «бомб» и не UTF-8 — «Формат не поддерживается» | плану нужен отказ без 500, отдельного текста FR-546 не даёт |
| К20 | `refresh_vectors` снимает признак, только если он не менялся с начала задания; пересчитывает записи с заполненным полем, у поля «файл» — с файлом | второе скрытие во время пересчёта не должно снять признак раньше своего задания; И2 говорит «только у записей, где поле заполнено» |
| К21 | подписи журнала (8.2) и распределение ключей по действиям (8.1) | план даёт набор ключей и коды, но не подписи |
| К22 | `external_text` вида — «Истекает срок в записи списка» | запасной текст на случай чтения без `external_text_of`; во внешний канал названия не попадают |
| К23 | порядок регистраций `register_all()` — порядок таблицы плана, `stand_reset` последней; обработчик `links.on_user_dismissed` | план не задаёт порядок и имя обработчика |
| К24 | помощники `support_lists.py` с сигнатурами раздела 5.9, в том числе `choice_id`, `run_unseed`, `read_xlsx`, `read_back`, `list_pages`, `ListLock`, `list_no`, `set_vectors`, `TITLES_006` сверх перечня строки T-6101 | писатели тестов не придумывают имён (решение 2 задач); перечисленные имена нужны нескольким файлам тестов |
| К25 | `as_reader(lst)`, `as_editor(lst)` получают список | в срезе 006 «читает» и «правит» — свойство пары «сотрудник, список», а не право роли |
