# Контракт имён тестов Этапа 2 среза 005 (T-5100…T-5151)

Тесты пишутся до кода и задают имена, которых нет в PLAN-005. Реализация (Этап 3) берёт их отсюда.
Имена плана (модели и поля раздела «Модель данных», маршруты «Контрактов», коды журнала, права
`knowledge.edit` и `knowledge.manage`, приложения `knowledge` и `search`, точки `search_providers` и
`ticket_card_parts`, записи `SearchProvider`, `ParsedQuery`, `SearchRow`, `TicketCardPart`, `TicketRef`,
поле `NotificationKind.coalesce`, службы `core.comments`, `core.uploads`, `servicedesk.public`, задание
`purge_trash`, команды `e2e_kb_trash_shift`, `e2e_kb_purge`, `kb_rerender`) здесь не повторяются и не
меняются, кроме случаев, когда тест уточняет их форму. Имена срезов 001-004 (`tests/CONTRACT.md`,
`CONTRACT-002.md`, `CONTRACT-003.md`, `CONTRACT-004.md`) не меняются; что меняется в этих файлах вместе со
срезом 005, перечислено в разделе 14 (перечень T-5138; решение 4 задач). Происхождение каждой строки видно
из текста: «план» — PLAN-005; «решение N задач» — раздел «Решения Opus по задачам» TASKS-005; «факт» — файл
репозитория, названный в строке; «вопрос A-N» — предложение автора контракта, которого нет ни в плане, ни в
решениях; его подтверждает или меняет Opus при проверке контракта (раздел 15, подраздел «Часть a»). Кто
решил: решения Opus по задачам — решения Opus, подписанные владельцем подписью TASKS-005; предложения «вопрос
A-N» — предложения исполнителя, ничьим решением пока не являются.

Помощники тестов: `tests/support_kb.py` (пишет T-5101, отдельной задачей после проверки контракта; фикстуры из
него подключаются через `tests/conftest.py`, который правит та же задача) и `tests/e2e/helpers_kb.py` (пишет
T-5140). В колонке «Тесты» стоят задачи T-51NN или файлы, которые берут имя.

Части этого файла: шапка и разделы 1-4 и подраздел «Часть a» раздела 15 — часть a; разделы 5-9 — часть b;
разделы 10-14 — часть c. Подразделы «Часть b» и «Часть c» раздела 15 дописывают свои части.

Правила для всех тестов среза:
- время (решение 5 задач): службы берут время из `django.utils.timezone.now()`; тесты корзины, версий, срока
  и очистки ставят часы фикстурой `clock` (класс `Clock` из `tests/factories.py`: `.set(moment)`,
  `.advance(**kwargs)`); Valkey и RQ живут по настоящему времени, поэтому тесты, где участвует очередь,
  сдвигают отметки базы прямой записью в поле;
- ночная очистка корзины (решение 5 задач) выполняется помощником синхронно, без рабочего процесса и без
  ожидания расписания (помощник `support_kb` вызывает `apps.knowledge.tasks.purge_trash()` и не ставит его в
  очередь); приёмка сдвигает `deleted_at` командой `e2e_kb_trash_shift --days N` и запускает очистку командой
  `e2e_kb_purge` (раздел 1.4);
- всё, что идёт «после фиксации» (события шины, постановка проверки файла, стирание файла с диска),
  проверяется внутри `with django_capture_on_commit_callbacks(execute=True):` (решение 18 задач; фикстура
  подключается параметром теста);
- гонки (решение 18 задач с поправкой Opus, раздел 16): `django_db(transaction=True)` в проекте не работает
  (`tests/conftest.py`: сброс таблиц требует прав владельца), а второй поток не видит незафиксированных данных теста;
  поэтому гонки проверяются без потоков — последовательно (второй вызов с прежним `base_version` получает отказ),
  ограничениями базы и по SQL через помощники `support_kb` на `CaptureQueriesContext`: `sql_of`, `assert_for_update`,
  `assert_skip_locked`, `advisory_locks` (порядок и вид замков `pg_advisory_xact_lock[_shared]`);
- ClamAV (решения 6 и 30 задач): тесты подменяют проверку строкой `apps.integrations.clamav.services.scan`
  (`monkeypatch.setattr("apps.integrations.clamav.services.scan", fake)`); подмен `monkeypatch` на
  `attachments` нет, на `uploads` — только одна точка подмены `uploads.write_file` (раздел 5.8, решение Opus по B-10); почему подмена строкой работает — раздел 1.2;
- имена кода среза 005 тесты импортируют внутри функций теста (или через `support.model("knowledge.Article")`),
  а не на уровне модуля: сбор (`pytest --collect-only`) должен проходить до появления кода;
  `tests/support_kb.py` на уровне модуля тоже не импортирует `apps.knowledge` и `apps.search`;
- секреты и персональные данные в тестовых данных (решение 17 задач): тестовые адреса почты и телефоны для
  проб ПДн собираются из частей в коде теста (`"ivanov" + "@" + "example.test"`), имена переменных — без слов
  `secret`, `token`, `key`, `password`; строка EICAR для вложения собирается из частей; в файлах, ответах и
  сообщениях об ошибках только `***`;
- подписчики `knowledge` (решение 19 задач): тесты прежних срезов с `bus_spy` и `execute=True` теперь запускают
  и подписчика `core.user_dismissed` модуля `knowledge`; его сбой шина пишет в лог и не роняет тест; тесты
  среза проверяют, что в журнале приложения нет ошибок подписчиков: `caplog`, логгер `apps.core.events`, нет
  записей уровня `ERROR`;
- разметка блоков среза (решение 16 задач): без `role="status"`, `role="alert"`, `data-error`, `data-warning`
  — кроме сообщений об отказах формы (раздел 11, пишет часть c); поэтому в блоках среза тесты их не ищут и не
  ждут;
- подмены для тестов сбоев (решение 32 задач) даёт `support_kb.py`, а не сам тест: сбой удаления одной статьи
  в ночной очистке, действие между выборкой порции и замком строки, занятый замок предпросмотра
  `kb:preview:<user_id>`, «модуль выключен» — снятие регистраций `knowledge` из реестра точек на время теста
  (как `no_extensions` прежних срезов; без перезагрузки `INSTALLED_APPS`);
- блокировки (решение 31 задач): `pg_advisory_xact_lock(hashtextextended(%s, 0))` — только параметром
  (`cursor.execute(sql, [key])`), без f-строк и `%`-подстановки;
- тесты ходят по путям плана (раздел «Контракты»), а не по именам маршрутов; маршруты среза не содержат
  `regist`, `signup` (решение 20 задач); модели берутся через `support.model("knowledge.Article")` и так далее;
- пропусков в тестах среза нет; сбой ClamAV и «модуль выключен» в приёмке не воспроизводятся (решения 12 и 36
  задач), их закрывают серверные тесты и ручной проход T-5301.

Разделы:
1. Среда запуска.
2. Модели и поля.
3. Ядро: точки расширения, записи, `core.comments`, `core.uploads`, `file_response`, `person_name`, поставщик
   «Сотрудники», права.
4. Прежние модули: `notify` (склейка), `servicedesk` (`public`, `ticket_card_parts`, поставщик «Заявки»,
   вложения), `org` (поставщик «Подразделения»).
5. Службы `knowledge` — пишет часть b.
6. Рендер и ПДн, перечень 36 проб — пишет часть b.
7. События шины `knowledge.*` и виды уведомлений — пишет часть b.
8. Журнал — пишет часть b.
9. Поиск — пишет часть b.
10. Маршруты и поля форм — пишет часть c.
11. Зацепки `data-*` для приёмки — пишет часть c.
12. Тексты, которые проверяют тесты — пишет часть c.
13. Команды стенда и нагрузки — пишет часть c.
14. Что меняется в прежних контрактах — пишет часть c.
15. Вопросы к Opus (подразделы по частям: «Часть a», «Часть b», «Часть c»).

## 1. Среда запуска

### 1.1. Зависимости и приложения

| Что | Требование | Тесты |
|---|---|---|
| Зависимости (факт `backend/requirements.txt`, T-5001) | блок «Срез 005» с комментарием-ссылкой на PLAN-005 и тремя строками `пакет==версия`: `markdown-it-py==4.2.0`, `mdurl==0.1.2`, `nh3==0.3.7`; других новых строк нет; тест читает файл и сравнивает версии точно (знак `==`, без `>=` и `~=`); лицензии — MIT (план, «Новые компоненты и лицензии»); записи в `static/vendor/VERSIONS.md` у среза нет | T-5129 test_requirements_pin_markdown_it_py_mdurl_nh3_exact_versions, test_new_packages_have_open_licenses_and_no_vendor_static_entry; прежний `test_stack.py::test_requirements_pinned_and_licensed` (T-5138) |
| `INSTALLED_APPS` (факт `config/settings.py`, T-5002) | в конце списка: `"apps.notify"`, затем `"apps.knowledge"`, затем `"apps.search"` (решение 3 задач); порядок важен: срез регистрируется в точках позже прежних, сброс стенда идёт в обратном порядке (сначала `knowledge`); у приложений метки `knowledge` и `search` (`AppConfig.label`), у `knowledge` `verbose_name = "База знаний"` | T-5129 test_knowledge_and_search_are_in_installed_apps_after_notify |
| Каркас `apps/knowledge/` (факт T-5002) | модули `models.py`, `tasks.py`, `extensions.py`, `notify_kinds.py`, `audit_labels.py`, `stand.py`, `urls.py`, пакеты `views/`, `migrations/`, `management/commands/`, `services/` с модулями `access`, `articles`, `files`, `links`, `pdn`, `render`, `retention`, `rubrics`, `search`, `settings`, `subscriptions`, `tags`, `versions`; у `apps/search/` — `parse.py`, `services.py`, `views.py`, `extensions.py`, `urls.py`; шаблоны — в `backend/templates/knowledge/` и `backend/templates/search/`; тест границ (T-5130) читает именно эти пути | T-5130, T-5129 |
| Скрипты среза | `static/js/kb-editor.js`, `static/js/kb-link.js`, `static/js/search.js` — внешние файлы без встроенного кода; в файлах нет `eval(` и `new Function`, имена не `js/notify…` (`test_shell.py`, impact У2); подключаются в `templates/_assets.html` (решение 9 задач: `kb-link.js`, затем `kb-editor.js`, затем `search.js`); тест находит каждое имя в разметке `_assets.html` | T-5129 test_slice_scripts_are_external_files_listed_in_assets_partial |

### 1.2. Задание очистки корзины, nginx, CSP, ClamAV

| Что | Требование | Тесты |
|---|---|---|
| Задание `purge_trash` в `config/cron.py` | семнадцатая запись `register(...)` (до среза 005 их 16 — факт `config/cron.py`): `register(purge_trash, queue_name="maintenance", cron="45 23 * * *", name="purge_trash", job_timeout=600)`; функция — `apps.knowledge.tasks.purge_trash`, импортируется в начале модуля `config/cron.py` рядом с прочими (`from apps.knowledge.tasks import purge_trash`); минута 45 часа 23 больше ни у одной записи не занята (рядом 23:40 `notify_retention`, 23:50 `purge_orphan_files`); службу `scheduler` при обновлении перезапускают (решение 44 задач) | T-5129 test_purge_trash_is_registered_in_cron_with_45_23_maintenance_timeout_600, test_cron_has_no_other_entry_on_minute_45_of_hour_23; число вызовов 16 → 17 — T-5138 (`test_sd_deploy.py`, `test_notify_deploy.py`) |
| Новый `location` nginx | в `deploy/nginx.conf` и `deploy/nginx.prod.conf`: `location ~ ^/kb/[0-9]+/files/$ { … }` с `client_max_body_size 55m;`; шаблон адреса — только вложение (POST `/kb/<id>/files/`), скачивание `/kb/<id>/files/<N>/` под него не подпадает и идёт общим `location /`; блок стоит рядом с `location ~ ^/tickets/(new/|[0-9]+/reply/)$`; общий предел тела (6 МБ) не меняется | T-5129 test_nginx_dev_config_has_kb_files_location_with_55m_limit, test_nginx_prod_config_has_kb_files_location_with_55m_limit |
| Директивы `proxy_*` в новом `location` | повторены, потому что из `location /` не наследуются; набор — как в блоке `tickets` того же файла (факт): `proxy_pass http://portal_web;`, `proxy_http_version 1.1;`, `proxy_set_header Host $http_host;`, `proxy_set_header X-Forwarded-For $remote_addr;`, `proxy_set_header X-Forwarded-Proto …;` (в `nginx.conf` — `$scheme`, в `nginx.prod.conf` — `$portal_proto`), `proxy_set_header Upgrade $http_upgrade;`, `proxy_set_header Connection $connection_upgrade;`, `proxy_read_timeout 75s;`; тест сверяет не значения чужого блока, а наличие каждой директивы в новом блоке и совпадение набора имён директив с блоком `tickets` | T-5129 test_kb_files_location_repeats_proxy_directives_in_both_configs |
| Выдача файлов статей | через прежний внутренний `location /protected/attachments/` (факт `nginx.conf`): новых томов и новых внутренних `location` нет; файлы лежат в томе `protected` (`incoming/`, `attachments/`, `quarantine/`); `deploy/backup.sh` и `RESTORE.md` не меняются (тест сравнивает отсутствие слов `knowledge`, `kb` в обоих файлах) | T-5129 test_article_files_live_in_protected_volume_and_backup_script_is_unchanged |
| CSP (факт `settings.CONTENT_SECURITY_POLICY`) | страницы `/kb/…` и `/search/` отдают заголовок `Content-Security-Policy`; в нём `script-src 'self'` без `'unsafe-inline'` и `'unsafe-eval'`; `img-src 'self' data:` — без внешних адресов (ни `http:`, ни `https:`, ни `*`); новых директив срез не вводит; тест читает заголовок ответа вошедшего сотрудника (страницы `/kb/`, `/kb/<id>/`, `/kb/new/`, `/search/?q=…`) | T-5129 test_kb_pages_send_csp_without_unsafe_inline_in_script_src, test_search_pages_send_csp_without_unsafe_inline_in_script_src, test_csp_img_src_on_kb_and_search_has_no_external_addresses |
| Шаблоны среза | в `templates/knowledge/` и `templates/search/` нет атрибута `style=` и атрибутов `on…=` (разбор файлов по регулярному выражению, как в `test_shell.py`); выравнивание таблицы статьи — классами `kb-al-left`, `kb-al-center`, `kb-al-right` | T-5129 test_knowledge_and_search_templates_have_no_style_attribute, test_knowledge_and_search_templates_have_no_inline_event_handlers; T-5102 |
| Язык и время | тексты страниц среза по-русски; время в статьях, версиях, корзине и комментариях — по Москве: тест ставит `Clock` на полночь UTC и проверяет день и час в разметке | T-5129 test_kb_pages_and_search_page_texts_are_russian, test_kb_times_are_shown_in_moscow_at_utc_midnight |
| ClamAV: подмена строкой | факт `apps/core/tasks.py`: модуль делает `from apps.integrations.clamav import services as clamav` и зовёт `clamav.scan(...)` атрибутом модуля, поэтому подмена атрибута `apps.integrations.clamav.services.scan` действует и для вложений заявок, и для файлов статей; `core.uploads` `scan` не вызывает, а только ставит проверку (`enqueue_scan` после фиксации) и возвращает прежний путь (решение 30 задач); если вызов `scan` появится в другом модуле, он идёт через атрибут модуля, а не через `from … import scan` | T-5113 test_scan_task_calls_clamav_through_module_attribute_so_scan_patch_applies; все тесты вложений |

### 1.3. Сброс стенда: точка `stand_reset` модуля `knowledge`

Команда ядра `e2e_reset_stand` зовёт функции точки `stand_reset` в обратном порядке регистрации (CONTRACT-003,
8.3; CONTRACT-004, 8.3). Приложения регистрируют точку в порядке `INSTALLED_APPS`, поэтому функция `knowledge`
идёт первой, раньше `notify`, `servicedesk`, `org`. Функция среза — `apps.knowledge.stand.stand_reset()`, без
аргументов, регистрируется в `apps/knowledge/extensions.py` (решение 27 задач); работает через соединение
`migrate`, если оно настроено, иначе через `default` (как `apps.notify.stand.stand_reset`, факт).

| Что | Требование | Тесты |
|---|---|---|
| Что стирается (решение 27 задач, план «Проход в браузере») | таблицы среза через соединение `migrate`: статьи, версии, рубрики (кроме «Общее»), теги, связи со статьями (`ArticleFile`, `TicketLink`), подписки `RubricSubscription`; комментарии ядра, у которых `object_ref` начинается с `knowledge.article:`; файлы статей — по строкам `ArticleFile` (строка и `StoredFile`, затем файл в `incoming/`, `attachments/`, `quarantine/`); общая очистка таблиц ядра (`TRUNCATE … CASCADE`) уже могла стереть часть таблиц среза, поэтому функция не рассчитывает на их строки | T-5129 test_stand_reset_knowledge_wipes_slice_data_and_prefixed_comments |
| Что не трогается | файлы и `StoredFile` вложений заявок (`purpose="attachment"`); комментарии ядра с другим префиксом `object_ref`; очередь `files` (общая, не чистится): задания проверки удалённых файлов выходят тихо (`still_waiting` ложно, решение 27 задач) | T-5129 test_stand_reset_knowledge_keeps_ticket_files_and_other_comments |
| Что восстанавливается | после `TRUNCATE … CASCADE` ядра: рубрика «Общее» (`parent=None`, `depth=1`, `is_default=True`), строка `KnowledgeSettings(pk=1, trash_days=90)`, права `knowledge.edit` и `knowledge.manage` и их выдача встроенным ролям — вызовом функции данных `seed(apps, schema_editor)` миграции `knowledge 0002` (2.3) с реестром `django.apps.apps` и алиасом базы `migrate`; как передать «`schema_editor`» функции, которая читает только `.connection.alias` — вопрос A-4 | T-5129 test_stand_reset_knowledge_restores_general_rubric_and_role_permissions |
| Приёмка | круг начинается с `helpers_sd.reset_stand_and_relogin()` (CONTRACT-003, 8.3), которая зовёт `e2e_reset_stand` и тем самым точку `knowledge` | T-5140…T-5151 |

Тесты сброса помечаются `pytest.mark.django_db(databases=["default", "migrate"])`; данные тест создаёт через
соединение `migrate` (`Model.objects.using("migrate")`), результат читает так же; вызывает функцию `stand_reset()` напрямую (тесты «стирает» и «не трогает» — только так: команда `e2e_reset_stand` чистит все таблицы `core_*`, включая `core_comment` и `core_storedfile`) и команду (только тест «восстанавливает» и стирание данных `knowledge`; права и роли команда оставляет — `KEEP_TABLES`)
(`monkeypatch.setenv("E2E_STAND", "1")`, `call_command("e2e_reset_stand")`).

### 1.4. Команды стенда и нагрузка (как их проверяет тест развёртывания)

Полное описание команд (аргументы, тексты, вывод) — раздел 13 (часть c). Здесь — только то, что сверяет
`test_kb_deploy.py`.

| Что | Требование | Тесты |
|---|---|---|
| `e2e_kb_trash_shift --days N` и `e2e_kb_purge` | модули `apps/knowledge/management/commands/e2e_kb_trash_shift.py` и `e2e_kb_purge.py` (решение 5 задач); без `E2E_STAND=1` обе команды падают `CommandError` до любого чтения базы и ничего не меняют (образец — факт `e2e_notify_tick.py`: функция проверки зовётся первой, текст отказа — как у `REFUSAL` прежних команд «Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено.»); с `E2E_STAND=1` `e2e_kb_trash_shift --days N` сдвигает `deleted_at` статей в корзине на N суток назад, `e2e_kb_purge` выполняет ночную очистку сразу (то же, что `tasks.purge_trash()`) | T-5129 test_e2e_kb_trash_shift_and_e2e_kb_purge_refuse_without_stand_flag, test_e2e_kb_trash_shift_and_e2e_kb_purge_work_with_stand_flag |
| `kb_rerender` | команда `apps/knowledge/management/commands/kb_rerender.py`: перерисовывает `html` и `plain` всех статей и `html` всех версий порциями; запускается и без `E2E_STAND` (это команда обновления, не приёмки); подробности — раздел 13 | тест не назначен (решение Opus по A-2: задачи подписаны, план теста не требует; поведение проверяет проход T-5301 при смене правил вывода) |
| `fill_articles.py` и `KnowledgeUser` | файл `backend/tests/load/fill_articles.py` (рядом с `fill_tickets.py`); в `backend/tests/load/locustfile.py` класс `KnowledgeUser`; тест только проверяет, что файл и класс есть (по тексту файла), не запускает нагрузку (решения 13 и 38 задач) | T-5129 test_load_suite_has_fill_articles_script_and_knowledge_user_class |

## 2. Модели и поля

Модели берутся через `support.model("knowledge.Article")` и так далее. Порядок объявления полей в таблицах — как
в плане («Модель данных»). Типы и длины — план; названия классов `TextChoices` и ограничений — «вопрос A-5»
(в плане классов и имён ограничений нет; образец — факт `org_unit_parent_name_key_uniq`: `<приложение>_<модель>_<поля>_<вид>`).

### 2.1. Ядро

| Что | Требование | Тесты |
|---|---|---|
| `StoredFile.Purpose.KNOWLEDGE` | значение `"knowledge"`, подпись `"файл статьи"` (в плане — «Файл статьи»; регистр подписей `Purpose` прежний — строчные: `"фото"`, `"вложение"`, поэтому подпись `"файл статьи"`, вопрос A-5); длина 9 ≤ 16 (`max_length` поля `purpose` не меняется); в базе ограничения на значение нет — миграция только `AlterField` вариантов | T-5113 test_stored_file_purpose_knowledge_value_exists |
| `core.Comment` | поля: `object_ref` (`CharField(max_length=64)`, формат `<приложение>.<объект>:<pk>`, у статьи `knowledge.article:<id>`); `author` (`ForeignKey("core.User", on_delete=PROTECT)`); `text` (`TextField`, длину до 4000 проверяет служба, а не база); `created_at` (`DateTimeField`, значение по умолчанию `django.utils.timezone.now`, как `StoredFile.created_at`); внешнего ключа на объект модуля нет; пометки «удалён» нет; индекс (`object_ref`, `created_at`, `id`) в `Meta.indexes`; `default_permissions = ()` (как у прочих моделей ядра, факт) | T-5130 test_core_comment_has_no_foreign_key_to_module_objects, test_core_comment_object_ref_is_string_in_app_object_pk_format; T-5116 |
| Миграция ядра | `apps/core/migrations/0008_…` (последняя прежняя — `0007_storedfile_attachment`, факт); содержит `CreateModel Comment` и `AlterField StoredFile.purpose` (варианты); других изменений в ядре нет (план: «Модель данных»); имя файла миграции тест не проверяет | T-5113, T-5116 |

### 2.2. Приложение `knowledge`

| Модель.поле | Требование (тип, значения, по умолчанию) | Тесты |
|---|---|---|
| `Rubric` | `name` (`CharField(100)`); `parent` (`ForeignKey("self", PROTECT, null=True, blank=True, related_name="children")`); `depth` (`PositiveSmallIntegerField`, 1–3; значение ставит служба при создании и переносе); `is_default` (`BooleanField(default=False)`) | T-5110, T-5111 |
| `Rubric`, ограничения | `UniqueConstraint(Lower("name"), "parent", nulls_distinct=False, name="knowledge_rubric_parent_name_ci_uniq")` (выражение позиционно, не через `fields=`; имя — вопрос A-5); `UniqueConstraint(fields=["is_default"], condition=Q(is_default=True), name="knowledge_rubric_single_default")`; `CheckConstraint(condition=Q(depth__gte=1, depth__lte=3), name="knowledge_rubric_depth_1_3")`; тест прямой записи ловит `IntegrityError` (имя ограничения тест не сверяет по тексту ошибки, только ловит исключение); служба до записи превращает нарушение в отказ у поля (раздел 5) | T-5110 / T-5111 test_db_constraint_rejects_duplicate_siblings_nulls_not_distinct |
| `Article` | `title` (`CharField(200)`); `text` (`TextField`, до 200 000 проверяет служба); `html` (`TextField`); `plain` (`TextField`, первые 100 000 знаков); `rubric` (`ForeignKey(Rubric, PROTECT)`); `tags` (`ManyToManyField(Tag, blank=True)`); `state` (`CharField`, `choices` — 2.3, по умолчанию `draft`); `state_before_trash` (`CharField`, `blank=True`, значения `draft`, `published` или пустая строка); `author` (`ForeignKey("core.User", PROTECT)`); `created_at`; `updated_by` (`ForeignKey("core.User", PROTECT)`); `updated_at`; `version_no` (`PositiveIntegerField`); `published_at` (`DateTimeField(null=True, blank=True)`); `deleted_at` (`null=True, blank=True`); `deleted_by` (`ForeignKey("core.User", PROTECT, null=True, blank=True)`); `from_ticket` (`PositiveIntegerField(null=True, blank=True)` — номер заявки или пусто; `null`, а не 0, по плану: «номер заявки или пусто»); `search_full`, `search_head` (`SearchVectorField(null=True, blank=True)`: «пусто, пока статья не опубликована» — `NULL`) | T-5103, T-5104, T-5107, T-5126 |
| `Article`, ограничения и индексы | GIN по `search_full` и по `search_head`; индексы (`state`, `-updated_at`), (`rubric`, `state`), (`author`, `state`), (`state`, `deleted_at`); `CheckConstraint`: `state = trash` ⇔ `deleted_at` не пусто — `Q(state="trash", deleted_at__isnull=False) \| (~Q(state="trash") & Q(deleted_at__isnull=True))`, имя `knowledge_article_trash_has_deleted_at`; прямая запись `state="trash"` без `deleted_at` (и наоборот) — `IntegrityError` | T-5107 |
| `ArticleVersion` | `article` (`ForeignKey(Article, CASCADE, related_name="versions")`); `number` (`PositiveIntegerField`); `author` (`PROTECT`); `created_at`; `comment` (`CharField(200, blank=True)`); снимок: `title`, `text`, `html`, `rubric` (`ForeignKey(Rubric, SET_NULL, null=True)`), `rubric_name` (`CharField(100)`), `tags` (`JSONField`, список строк); уникальность (`article`, `number`) — `knowledge_articleversion_article_number_uniq`; индекс (`article`, `-number`); номера не переиспользуются: следующий — `Article.version_no + 1`, удаление версии `version_no` не трогает (FR-449) | T-5104 (гонка: одна версия на номер), T-5105, T-5106 |
| `Tag` | `name` (`CharField(40)`, строчные — приводит служба `tags.normalize`); уникальность `name` (`unique=True`) | T-5112 |
| `ArticleFile` | `article` (`ForeignKey(Article, CASCADE, related_name="files")`); `file` (`OneToOneField("core.StoredFile", PROTECT)`); `name` (`CharField(255)`); `image_format` (`CharField`, `choices` — 2.3, `blank=True`); `uploaded_by` (`PROTECT`); `uploaded_at`; индекс (`article`, `uploaded_at`) | T-5114, T-5115 |
| `TicketLink` | `article` (`ForeignKey(Article, CASCADE, related_name="ticket_links")`); `ticket_number` (`PositiveIntegerField`, без внешнего ключа — инвариант «модуль-приложение»); `linked_by` (`PROTECT`); `linked_at`; `from_resolution` (`BooleanField(default=False)`); уникальность (`article`, `ticket_number`) — `knowledge_ticketlink_article_ticket_uniq`; индекс по `ticket_number` | T-5119, T-5120, T-5130 |
| `RubricSubscription` | `user` (`ForeignKey("core.User", CASCADE)`); `rubric` (`ForeignKey(Rubric, CASCADE)`); `created_at`; уникальность (`user`, `rubric`) — `knowledge_rubricsubscription_user_rubric_uniq` | T-5111, T-5122 |
| `KnowledgeSettings` | одна строка `pk=1`, создаёт миграция данных; `trash_days` (`PositiveSmallIntegerField(default=90)`); границы 7–365 проверяет служба `settings`, а не база | T-5108 |

Сообщения нарушения ограничений до службы не доходят: тесты моделей ловят `django.db.IntegrityError`, тесты
служб и страниц — отказ у поля (раздел 5, часть b; раздел 12, часть c).

### 2.3. `choices`: ровно в том виде, как тест их сравнивает

Тест сравнивает `[value for value, _ in Field.choices]` (значения и порядок), подписи читает только там, где они
выведены на странице (раздел 12). Названия внутренних классов — выбор контракта (вопрос A-5).

| Поле | `choices` (значения по порядку) | Тесты |
|---|---|---|
| `Article.state` | `Article.State`: `draft` («черновик»), `published` («опубликована»), `trash` («в корзине»); по умолчанию `draft` | T-5103, T-5107 |
| `Article.state_before_trash` | пустая строка, `draft`, `published`; `choices` у поля не задаются (проверяет служба и ограничение на значения не навешивается); допустимые записи — только `""`, `"draft"`, `"published"` | T-5107 |
| `ArticleFile.image_format` | `ArticleFile.ImageFormat`: `png`, `jpeg`, `gif`, `webp`; пустая строка — «не картинка» (`blank=True`); ровно эти четыре значения возвращает `uploads.detect_image` (3.4) | T-5113, T-5114 |

### 2.4. Миграции и данные установки

| Что | Требование | Тесты |
|---|---|---|
| `knowledge 0001_initial` | создаёт все таблицы 2.2; зависит от `core 0008` (модель `core.User`, `core.StoredFile`) и ничего не знает о `servicedesk`, `org`, `notify` (граница модулей); первое, что проверяет T-5206, — применение с `UniqueConstraint(Lower("name"), "parent", nulls_distinct=False)` на PostgreSQL 17 (решение 7 задач) | T-5110 (ограничение), T-5130 |
| `knowledge 0002_initial_data` | модуль миграции содержит функцию `seed(apps, schema_editor)` на уровне модуля (решения 27 и 40 задач; образец формы — факт `notify/migrations/0002_initial_data.py`, но функция идемпотентна: её зовут и при установке, и в тесте на уже выданных ролях, и при каждом сбросе стенда); `unseed` — как у образца; `RunPython(seed, unseed)`; зависимости: `("knowledge", "0001_initial")` и миграция ядра с встроенными ролями (`core 0002_initial_data`, факт: роли создаёт она) | T-5109 test_migration_0002_* |
| Что создаёт `seed` | работает через `db = schema_editor.connection.alias`, модели — из `apps.get_model(...)` (реестр миграции или `django.apps.apps`); создаёт или находит: права `Permission(code="knowledge.edit", title="Редактирование базы знаний")` и `Permission(code="knowledge.manage", title="Управление базой знаний")` (`get_or_create` по `code`; существующий `title` не перезаписывается); рубрику «Общее» (`name="Общее"`, `parent=None`, `depth=1`, `is_default=True`) — только если рубрики с `is_default=True` нет; `KnowledgeSettings(pk=1, trash_days=90)` — только если строки нет; повторный вызов ничего не меняет и не падает | T-5109 test_migration_0002_creates_permissions_general_rubric_and_settings_and_grants_builtin_roles_chief_gets_none |
| Выдача прав встроенным ролям | роль ищется по названию и `is_builtin=True` через `Role.objects.using(db).filter(name=…, is_builtin=True).first()` (в отличие от `.get()` у `notify 0002`: нет роли — пропуск без ошибки, план «Права среза»); «Администратор портала» получает `knowledge.edit` и `knowledge.manage`; «Сотрудник ИТ» — `knowledge.edit`; «Руководитель» и «Сотрудник» ничего не получают; права, которые у ролей уже были, остаются (`permissions.add`, не `set`) | T-5109 test_migration_0002_adds_rights_to_existing_roles_keeps_prior, test_migration_0002_without_it_role_passes |
| Вызов функции в тесте (решение 40 задач) | тест загружает модуль через `importlib.import_module("apps.knowledge.migrations.0002_initial_data")` (имя файла — вопрос A-5), берёт `seed`, вызывает `seed(django.apps.apps, schema_editor)` на базе, где роли уже выданы; `schema_editor` — объект с атрибутом `connection` (вопрос A-4) | T-5109 |
| Права роли приложения в базе | новые таблицы получают права через `ALTER DEFAULT PRIVILEGES` (как в срезе 004): своих `GRANT` в миграциях нет; ночная очистка идёт под `crm_app` | T-5108 (очистка под ролью `crm_app`) |
| Число прав | после установки 15: семь среза 001, три среза 002, два среза 003, одно среза 004 (`notify.manage`) и два среза 005 (решение 4 задач); константы — 3.6 | T-5138 (пункты о правах), T-5109 |

## 3. Ядро

### 3.1. `POINTS` и функции регистрации

| Что | Требование | Тесты |
|---|---|---|
| Полный `POINTS` (факт `apps/core/extensions.py` + решение 23 задач) | кортеж из 17 имён в таком порядке: `"menu_items"`, `"role_sources"`, `"role_usage"`, `"audit_labels"`, `"staff_directory"`, `"card_sections"`, `"day_marks"`, `"home_notices"`, `"stand_reset"`, `"unit_usage"`, `"file_purposes"`, `"mail_renderers"`, `"login_links"`, `"notification_kinds"`, `"top_bar_items"`, `"search_providers"`, `"ticket_card_parts"`; прежние 15 имён и их порядок не меняются, новые два — в конце, `search_providers` перед `ticket_card_parts`; `_registry` содержит ключ на каждое имя | T-5130 test_points_has_seventeen_names, test_points_new_names_search_providers_and_ticket_card_parts_are_last_two; T-5138 (`test_extensions.py`, `test_sd_boundaries.py`) |
| Подпись функции регистрации | `extensions.register("search_providers", func)`, где `func() -> list[SearchProvider]` — без аргументов, возвращает список записей, как `top_bar_items() -> list[TopBarItem]` (факт `notify/extensions.py`); то же для `ticket_card_parts`: `func() -> list[TicketCardPart]`; потребитель (`search.services`, карточка заявки) собирает записи, обходя `extensions.registered(point)` и вызывая каждую функцию; порядок вывода — по полю `order` записи (при равенстве — порядок регистрации, устойчивая сортировка) | T-5126 test_assembler_runs_extra_registered_provider_without_changes; T-5119 |
| Порядок регистраций | `knowledge` регистрирует `search_providers` с группой «Статьи» (порядок 20) и `ticket_card_parts` — единственный, кто регистрируется в этой точке (решение 26 задач: `servicedesk` её только вызывает); в `SERVICEDESK_POINTS` теста границ добавляется только `search_providers` (решение 26 задач) | T-5130 test_search_providers_registered_by_servicedesk_knowledge_core_org_in_order |
| «Модуль выключен» | `extensions.empty()` и `support_kb` (снятие регистраций `knowledge` на время теста, решение 32 задач): карточка заявки без частей, каталог уведомлений без видов `knowledge`, поиск без группы «Статьи», меню без «База знаний»; ядро и прежние модули при этом не падают | T-5130 test_ticket_card_without_knowledge_*, test_search_without_knowledge_*, test_menu_without_knowledge_has_no_knowledge_item, test_notification_catalog_without_knowledge_has_no_knowledge_kinds; T-5127 |

### 3.2. Записи точек (`apps/core/extensions.py`)

Все новые записи — `@dataclass(frozen=True)`, как `Draft`, `NotificationKind`, `TopBarItem` (вопрос A-6: в плане
`frozen` не сказано; без него тест не может положиться на неизменность записи, которую хранит реестр). Тип
функции в аннотации — `Callable[...]` из `typing`, как в прежних записях. Подписи — план («Контракты»), где
раздел «Точки расширения» плана и «Контракты» расходятся, берётся «Контракты» (вопрос A-7).

| Запись | Поля по порядку | Требование | Тесты |
|---|---|---|---|
| `SearchProvider` | `key: str`, `title: str`, `order: int`, `search: Callable[[User, ParsedQuery, int, int], list[SearchRow]]`, `count: Callable[[User, ParsedQuery], tuple[int, bool]]`, `available: Callable[[User], bool]` | значений по умолчанию нет, все поля обязательны (план их не даёт; вопрос A-6); `search(user, parsed, limit, offset)` отдаёт не больше `limit` строк, пропустив `offset` строк группы; `available(user)` — показывать ли группу этому пользователю (право, выключенный модуль); `count(user, parsed)` — отдельный дешёвый запрос подсчёта: возвращает `(число, больше_потолка)`; соглашение о подсчёте общее для всех групп: если результат упёрся в потолок, возвращается `(потолок, True)` и страница пишет `f"{число}+"`; иначе `(точное_число, False)` и страница пишет число; у «Заявок» потолок 1000 (читают 1001 строку), поэтому `(1000, True)` → «1000+»; у «Статей» потолок — сумма точного счёта шага 1 и 300 кандидатов шага 2 (подробности — раздел 9, часть b); у «Сотрудников» и «Подразделений» всегда `(точное, False)`; текст `f"{n}+"` без пробела | T-5126, T-5127, T-5128 |
| `ParsedQuery` | `words: list[str]`, `number: int \| None`, `raw: str`, `hint: str` | поля как в плане; значения по умолчанию: `number=None`, `raw=""`, `hint=""` (`words` обязателен; выбор контракта, вопрос A-6); значения `hint`: `""` (разбор удался), `"short"`, `"long"` (план «Сквозной поиск», разбор, п. 1 и 4); `raw` — строка `to_tsquery` вида `"слово1:* & слово2:*"` (`" & ".join(f"{w}:*")`); создаёт `search.parse.parse(q)`; запись определена в ядре, `search.parse` её импортирует (ядро приложений среза не знает) | T-5125, T-5126 |
| `SearchRow` | `title: str`, `subtitle: str`, `url: str`, `template: str = ""`, `context: dict \| None = None` | поля как в плане; пустой `template` — общая разметка строки; непустой — имя шаблона строки (фото сотрудника, состояние заявки), `context` — его контекст; `url` — адрес внутри портала (начинается с `/`) | T-5126, T-5127, T-5128 |
| `TicketCardPart` | `key: str`, `kind: str`, `order: int`, `render: Callable[[HttpRequest, TicketRef], str \| None]` | `kind` — одна из строк `"section"`, `"closed_action"`, `"comment_tool"` (аннотация `Literal[…]`); `render` возвращает готовый фрагмент HTML (строка) или `None`/пустую строку — «ничего»; ключи записей `knowledge` — 4.3 | T-5119, T-5120, T-5130 |
| `TicketRef` | `number: int`, `closed: bool`, `has_resolution: bool` | значений по умолчанию нет; модели `Ticket` не содержит; `closed` — признак «заявка закрыта» (то же значение, что у `_closed(ticket)` в `ticket_card.py`, факт); `has_resolution` — `bool(ticket.resolution.strip())` (A-8) | T-5119, T-5120 |
| `NotificationKind.coalesce` | `coalesce: bool = False` | последнее поле записи, после `order` (решение 24 задач); значение по умолчанию ложно: прежние вызовы с именованными аргументами не меняются; прежние виды (сервис-деск, безопасность ядра, `notify`) его не ставят; виды `knowledge` ставят истину | T-5123, T-5121 test_kinds_*; T-5138 (`test_notify_catalog*.py`: набор полей) |

### 3.3. Поставщик «Сотрудники» (`apps/core/services/staff_search.py`)

| Что | Требование | Тесты |
|---|---|---|
| Регистрация | в `CoreConfig.ready()` (`apps/core/apps.py`, решение 9 задач: T-5202) рядом с `notification_kinds`: `extensions.register("search_providers", staff_search.search_providers)`; функция возвращает одну запись `SearchProvider(key="staff", title="Сотрудники", order=30, search=…, count=…, available=…)`; ключ группы — вопрос A-1 | T-5127, T-5130 test_search_providers_registered_by_servicedesk_knowledge_core_org_in_order |
| `available(user)` | `permissions.has(user, "staff.view")`-эквивалент: право `staff.view`; одно право `accounts.manage` группу не даёт | T-5127 test_staff_group_requires_staff_view, test_accounts_manage_alone_does_not_give_staff_group |
| Отбор | `state = active` (приглашённые, заблокированные и уволенные не видны); каждое слово запроса — отдельное условие: вектор полей справочника ядра `accounts.SEARCH_FIELDS` (факт: `full_name`, `position`, `email`, `phone`, `internal_phone`, `workplace`) `@@ слово:*` или условие записи `staff_directory.search(слово)` (названия подразделений); все слова — И; слова, дающие пустой запрос (стоп-слова), отбрасываются заранее одним запросом `numnode(to_tsquery('russian', слово:*)) = 0`; почта ищется целиком и по частям (вектор содержит её как есть и с заменой `@ . _ / -` на пробелы), телефон — как есть и только цифрами; без `org` — только поля ядра | T-5127 |
| Порядок и точность | сортировка `full_name`, затем `pk`; `count` точный (`(число, False)`) | T-5127 test_staff_ordered_by_full_name |
| Строка выдачи | `SearchRow(title=ФИО, subtitle=должность, url="/staff/<id>/", template=…, context=…)`; в контексте шаблона строки `search/rows/_staff.html` (A-9) — ключи `unit` (результат колонки `unit` записи `staff_directory`) и `photo` (`files.photo_url(user, 96)`) | T-5127 test_staff_row_has_name_position_unit_photo_and_card_url |

### 3.4. `core.comments`

Модуль `apps/core/services/comments.py`. Ядро не знает, что такое статья (тест `test_core_comments_service_knows_nothing_about_articles`
читает файл: нет слов `knowledge`, `Article`, `article`). Можно ли комментировать и видеть — решает модуль.

| Что | Требование | Тесты |
|---|---|---|
| Исключение | `comments.CommentError(Exception)` с атрибутами `.code` (`"empty"` или `"too_long"`) и `.message` (русский текст отказа; сам текст — раздел 12); код `empty` — текст пуст или из одних пробелов; `too_long` — после обрезки пробелов по краям длиннее 4000 знаков (вопрос A-10: плана имя исключения не даёт) | T-5116 test_core_comment_add_empty_or_blank_refused, test_core_comment_add_4000_accepted_and_4001_refused |
| `add(author, object_ref, text) -> Comment` | порядок аргументов — план; пробелы по краям убираются (`str.strip()`), внутренний текст и переводы строк не меняются; длина 1–4000 знаков после обрезки: 4000 принимается, 4001 — `CommentError("too_long")`, пустая строка и строка из пробелов — `CommentError("empty")`; ничего не пишет при отказе; `object_ref` служба не разбирает и не проверяет (любая непустая строка до 64 знаков); события шины сам не публикует (событие `knowledge.comment_added` публикует `knowledge`) | T-5116, T-5130 test_comment_attaches_to_object_of_any_module_by_ref |
| `list_for(object_ref) -> list[Comment]` | порядок `created_at`, затем `id` (старые первыми, новый внизу); автор вычитывается одним запросом вместе со списком (`select_related("author")`), фото автора — без дополнительного запроса на каждого автора (число запросов не зависит от числа комментариев; тест считает запросы `django_assert_num_queries` на 1 и на 10 комментариев и сверяет равенство; точное число — выбор тестов, не контракта) | T-5116 test_core_comment_list_for_oldest_first_newest_last_with_author, test_core_comment_list_for_loads_author_and_photo_in_one_query |
| `delete(comment) -> None` | удаляет одну строку физически (пометки «удалён» нет); журнал сам не пишет (журнал удаления чужого комментария пишет `knowledge`, раздел 8) | T-5116 test_core_comment_delete_removes_one |
| `delete_for(object_ref) -> int` | удаляет все комментарии этого `object_ref` (и только его: `knowledge.article:1` не задевает `knowledge.article:10`) и возвращает их число; зовётся в той же транзакции, что удаление объекта | T-5116 test_core_comment_delete_for_removes_only_that_objects_comments, T-5130 test_comment_is_deleted_with_object_by_delete_for_ref |

### 3.5. `core.uploads` и `core.file_response`

Модуль `apps/core/services/uploads.py` берёт из `servicedesk/services/attachments.py` части без моделей
сервис-деска (план «Вложения…»); имена и поведение прежних функций сохраняются (4.4).

| Что | Требование | Тесты |
|---|---|---|
| `is_executable(name, data) -> bool` | то же, что `servicedesk.attachments.is_executable` (факт): по последнему расширению из `EXECUTABLE_EXTENSIONS` или по содержимому (PE, ELF, Mach-O, `#!`, MSI, JAR); имя `EXECUTABLE_EXTENSIONS` определено в `uploads` и реэкспортируется в `attachments` (4.4) | T-5113 test_reject_reason_executable_* |
| `is_encrypted_archive(data) -> bool` | то же, что прежняя функция (ZIP, RAR4, RAR5, 7z) | T-5113 test_reject_reason_encrypted_* |
| `reject_reason(name, data, size, max_file) -> str` | возвращает одну из строк `"too_big"`, `"executable"`, `"encrypted"` или `""` (чисто); порядок проверок: сначала размер (`size > max_file` → `"too_big"`; ровно `max_file` принимается), затем `is_executable` → `"executable"`, затем `is_encrypted_archive` → `"encrypted"`; `max_file` передаёт вызывающий (20 МБ у статей, `attachments.MAX_FILE` у заявок) | T-5113 test_reject_reason_too_big_over_limit, test_reject_reason_file_exactly_at_limit_accepted, test_reject_reason_clean_file_returns_empty |
| `detect_image(data) -> str` | формат по содержимому (Pillow, `Image.open(...).verify()`), не по расширению и не по типу из браузера: `"png"`, `"jpeg"`, `"gif"`, `"webp"` или `""` (не картинка, в том числе повреждённая и неподдерживаемого формата); значения совпадают с `ArticleFile.ImageFormat` (2.3); картинка с чужим расширением определяется по содержимому | T-5113 test_detect_image_* |
| `ImageTooLarge` | `uploads.ImageTooLarge(Exception)` (решение 42 задач); `detect_image` поднимает её, когда Pillow поднял `Image.DecompressionBombError` или число точек больше предела фото (тот же предел, что у `files._check` для фото, факт); для не-картинки исключения нет (возврат пустой строки); исключение — не ошибка сервера: `attach` превращает его в отказ «Картинка слишком большая» (раздел 12) | T-5113 test_detect_image_pixel_bomb_raises_image_too_large_without_server_error, T-5114 |
| `store(data, name, purpose) -> StoredFile` | создаёт строку `StoredFile` (`owner=None`, как вложения заявок, `purpose` — переданное значение, `status=pending`, `size`, `sha256`, `content_type` по `detect_image` или `application/octet-stream`), записывает файл через `uploads.write_file(path, data)` в `incoming/<id>` (`files.attachment_path`), ставит `enqueue_scan(stored.pk)` после фиксации транзакции (`transaction.on_commit`); до фиксации в очереди ничего нет | T-5113 test_store_creates_stored_file_with_empty_owner_in_incoming, test_store_enqueues_scan_only_after_commit |
| `move(stored, status, signature="") -> list` | переносит файл между `incoming/`, `attachments/`, `quarantine/` по `files.attachment_path` (копия во временный файл и `os.replace`, как `_move` в `servicedesk`, факт), меняет `status`, `scanned_at` (и `signature`, если передана), сохраняет строку; возвращает список прежних путей для стирания после фиксации (`[source]`); сам ничего не стирает | T-5113 test_move_clean_to_attachments_returns_old_path_for_erasure, test_move_found_to_quarantine_returns_old_path, test_scan_task_erases_old_path_returned_by_move_only_after_commit |
| `file_response` | модуль `apps/core/services/file_response.py`; функции: `download(stored, filename) -> HttpResponse` — пустое тело, `X-Accel-Redirect: /protected/attachments/<…>`, `Content-Disposition: attachment; filename*=UTF-8''<имя>` (имя в процентной записи), `Content-Type: application/octet-stream`; `inline_image(stored, image_format) -> HttpResponse` — пустое тело, `X-Accel-Redirect`, тип из `image_format` (`image/png`, `image/jpeg`, `image/gif`, `image/webp`), без `Content-Disposition`; у обеих: `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`; имена функций и подписи — вопрос A-11 (план даёт модуль и заголовки, не имена); путь `X-Accel-Redirect` берётся из `files.attachment_path(stored)` относительно тома `protected` | T-5115 (выдача), T-5114 |

### 3.6. `{% person_name %}`, права и помощники

| Что | Требование | Тесты |
|---|---|---|
| Тег `{% person_name user %}` | простой тег (`simple_tag`) в существующей библиотеке `apps/core/templatetags/portal.py` (факт: каталог `templatetags/` содержит `portal.py`; подключение `{% load portal %}`; вопрос A-12); принимает пользователя; для активного выводит `ФИО` (экранированное); для уволенного (`state == "dismissed"`) — `ФИО (уволен)` внутри `<span data-dismissed="true">` (как в карточке заявки, факт `_card.html`); пустого пользователя (`None`) не выводит | T-5116 test_fired_author_comment_signed_with_name_and_fired_mark, T-5105 test_history_marks_dismissed_author_with_fired_label, T-5102 |
| Права среза | `knowledge.edit` — «Редактирование базы знаний», `knowledge.manage` — «Управление базой знаний» (план «Права среза»); управление включает всё, что даёт редактирование (план «Уведомления…», `available`) | T-5109 |
| `PERMISSIONS_005`, `TITLES_005`, `POINTS_005` | в `tests/support_kb.py` (по образцу `support_notify.PERMISSIONS_004`): `PERMISSIONS_005 = ("knowledge.edit", "knowledge.manage")`; `TITLES_005 = {"knowledge.edit": "Редактирование базы знаний", "knowledge.manage": "Управление базой знаний"}`; `POINTS_005 = ("search_providers", "ticket_card_parts")`; `support.PERMISSIONS`, `support.PERMISSIONS_002`, `support_servicedesk.PERMISSIONS_003`, `support_notify.PERMISSIONS_004` не меняются | T-5138 (пункты о правах и точках), T-5109 |
| Помощник «выдать право» | `support_kb.grant(user, *codes)` — выдаёт сотруднику права через отдельную роль (как `support_notify`), не меняя встроенные роли; решение — на T-5101 | T-5101 |

## 4. Прежние модули

### 4.1. `notify.dispatch.create`: ветка «склеивать»

Правка `apps/notify/services/dispatch.py: create` (план «Уведомления базы знаний»; решение 9 задач: T-5203).
Подпись `create(kind_code, drafts) -> list[int]` не меняется (факт).

| Что | Требование | Тесты |
|---|---|---|
| Кого касается | только вид с `kind.coalesce` истинным; для прочих видов `create` работает так же, как в срезе 004 (два события — две записи) | T-5123 test_kinds_without_coalesce_create_two_records_for_two_events |
| Ключ замка | строка `f"{user_id}:{kind.code}:{object_ref}"` — `'<user_id>:<код вида>:<object_ref>'`, например `"7:knowledge.comment_on_my_article:knowledge.article:15"`; строится функцией `dispatch.coalesce_key(user_id, kind_code, object_ref) -> str` (имя функции — вопрос A-13: без неё тест не может сверить ключ с независимым вычислением) | T-5123 test_lock_key_uses_hashtextextended_and_is_equal_across_processes |
| Замок | в SQL ровно `SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))`, ключ — единственный параметр (`cursor.execute(sql, [key])`; решение 31 задач); тест ловит запросы `CaptureQueriesContext` и сверяет текст SQL и параметры; «одинаков в разных процессах» тест проверяет так: берёт ключ из перехваченных параметров, выполняет `SELECT hashtextextended(%s, 0)` в двух разных соединениях и сравнивает результаты | T-5123 test_lock_key_uses_hashtextextended_and_is_equal_across_processes |
| Порядок взятия | один проход перед циклом черновиков (до создания первой записи): ключи (только для черновиков получателей в допустимом состоянии — `RECIPIENT_STATES`, факт) собираются в множество и берутся по возрастанию строки ключа (`sorted(keys)`, обычное сравнение строк Python; вопрос A-13: план говорит «по возрастанию ключа» и не уточняет, ключ — строка или её хэш; строка выбрана потому, что она видна тесту); замки живут до конца транзакции `create` | T-5123 test_opposite_recipient_order_in_two_events_does_not_deadlock_and_both_handled, test_two_simultaneous_events_create_single_notification |
| Что узнаёт тест как «пропуск» | у получателя есть `Notification` того же `kind` с тем же `object_ref` и `read_at` пусто: нет новой записи `Notification`, номера в возвращаемом списке нет, нет записей `Delivery` по этому черновику, получателя нет в карте всплывающего окна (после фиксации не уходит сообщение живого канала `/ws/notify/` о нём) и не добавлен в `recipients` (счётчик непрочитанного не меняется); получатель, у которого записи нет, получает уведомление как обычно, даже если пропущен другой в том же вызове; «Прочитано» — `read_at` не пусто (после прочтения новая запись создаётся) | T-5123 test_coalesce_kind_skips_new_notification_while_same_kind_same_object_unread, test_coalesce_skip_creates_no_deliveries_and_no_popup, test_coalesce_kind_creates_notification_after_previous_was_read |
| Область склейки | по получателю и по `object_ref` отдельно: тот же вид и тот же объект у другого получателя — запись создаётся; тот же получатель и тот же вид, но другой `object_ref` — создаётся | T-5123 test_coalesce_is_per_object_and_per_recipient |
| Повтор внутри одного вызова | следует из текста плана (проверка идёт в цикле после создания предыдущих записей): два черновика одному получателю, виду и объекту в одном вызове дают одну запись (вопрос A-14: плана о таком вызове не говорит; тесты его не требуют) | — |
| Порядок записей | порядок записей и доставок остаётся порядком черновиков; `held_users` для `plan_digest` обходятся по возрастанию `user_id` (план) | T-5123 test_records_and_deliveries_keep_drafts_order_with_coalesce_enabled |
| Пустой `object_ref` | если у черновика `object_ref=""`, склейка к нему не применяется (замка и пропуска нет): склеивать «по пустому объекту» значило бы заглушать все уведомления вида — вопрос A-14 | — |
| «Прочитано» по статье | ставит прежнее событие `object.viewed` (факт: подписчик `reading.on_object_viewed` в `notify/extensions.py`); для статьи ссылка объекта — `knowledge.article:<id>`; публикует показ статьи `knowledge` (раздел 7, часть b); `notify` изменений здесь не получает, кроме ветки `create` | T-5123 test_object_viewed_for_article_marks_unread_notification_read |

### 4.2. `servicedesk.services.public`

Новый модуль `apps/servicedesk/services/public.py` — единственное, что `knowledge` вызывает у сервис-деска
(решение 9 задач: T-5204; тест границ T-5130).

| Что | Требование | Тесты |
|---|---|---|
| `TicketBrief` | `NamedTuple` с полями по порядку: `number: int`, `subject: str`, `state: str`, `closed_with_resolution: bool`, `resolution: str`; `state` — название состояния (`Ticket.status.name`); `closed_with_resolution` — заявка закрыта и решение не пусто после `strip()`; `resolution` — текст решения (`Ticket.resolution`, пустая строка, если решения нет); других полей нет: тест сверяет `TicketBrief._fields` точно — в нём нет адреса и имени заявителя, переписки, вложений (вопрос A-8: плана нет перечня имён полей, есть только содержимое) | T-5119 test_ticket_brief_returns_number_subject_state_and_resolution_for_visible_ticket, test_ticket_brief_has_no_requester_address_or_correspondence_fields |
| `ticket_brief(user, number) -> TicketBrief \| None` | заявку видит `user` по `access.visible_tickets(user)` (факт) — возвращается `TicketBrief`; невидимая или несуществующая — `None` | T-5119 test_ticket_brief_returns_none_for_invisible_ticket |
| `briefs(user, numbers) -> dict[int, TicketBrief]` | один запрос на список (тест считает запросы); в словаре только видимые `user` заявки, ключ — номер; невидимые и несуществующие номера отсутствуют; пустой список — пустой словарь без запроса | T-5119 test_briefs_returns_only_visible_tickets_in_one_query |
| Граница | `knowledge` импортирует у `servicedesk` только `apps.servicedesk.services.public`, и только если приложение установлено (`apps.is_installed("apps.servicedesk")`); `servicedesk`, `org`, `core` не импортируют `knowledge` и `search` | T-5130 test_knowledge_calls_servicedesk_only_through_services_public, test_servicedesk_org_core_do_not_import_knowledge_or_search |

### 4.3. Вызов `ticket_card_parts` в карточке заявки

Правка `apps/servicedesk/views/ticket_card.py` (`_context`) и `templates/servicedesk/card/_card.html` (решение 9
задач: T-5204). Карточка вызывает записи точки; `servicedesk` их не регистрирует и `knowledge` не импортирует.

| Что | Требование | Тесты |
|---|---|---|
| `TicketRef` для карточки | `TicketRef(number=ticket.number, closed=_closed(ticket), has_resolution=bool(ticket.resolution.strip()))`; собирается один раз на отрисовку карточки в `_context` | T-5119 |
| Вызов | для каждой записи `ticket_card_parts` (порядок — по `order`) вызывается `render(request, ref)`; результат `None` или пустая строка — части нет; исключение записи пишется в журнал приложения (логгер `apps.servicedesk`, без текста исключения заявки — только ключ записи и класс исключения, по образцу поиска; вопрос A-15), карточка рисуется без этой части | T-5119 test_card_part_raising_exception_is_logged_and_card_renders_without_that_part |
| Три места в разметке (план «Встраивание в карточку») | `section` — в блоке полей и разделов (`data-card-fields`), сразу после блока «Вложения» и после его закрывающего `{% endif %}`: раздел показывается независимо от того, есть ли у заявки вложения (блок «Вложения» сам стоит внутри `{% if all_attachments or all_rejected %}`); `closed_action` — внутри `div.card-actions` закрытой заявки (ветка `{% else %}` после формы `data-form="ticket-reopen"`), рядом с кнопкой `data-action="ticket-reopen"`; `comment_tool` — внутри формы `data-form="ticket-comment"` сразу после `textarea` поля «Внутренний комментарий» | T-5119 test_articles_section_follows_attachments_block_and_shown_for_ticket_without_attachments, T-5120 |
| Оболочка частей | каждая непустая часть выводится в оболочке `<div data-card-part="<key>" data-part-kind="<kind>">…</div>` (вопрос A-16: `data-*` для частей плана нет; раздел 11, часть c, их подтверждает или заменяет); пустой результат — ни оболочки, ни пробелов, ни комментария шаблона | T-5119, T-5120, T-5143 |
| Нет записей | точка пуста (модуль выключен или не установлен) — карточка и лента выводятся так же, как в срезе 003: разметка совпадает со снимком `tests/fixtures/ticket_card_slice003.html`, который T-5119 снимает с карточки до правки `_card.html` (T-5204; нормализация: без номера заявки и времени); нет раздела «Статьи», нет кнопки «Статья из решения», нет «Ссылка на статью»; карточка закрытой и открытой заявки работает | T-5119 test_card_without_kb_records_in_ticket_card_parts_matches_slice003_markup, test_card_with_module_disabled_has_no_articles_section_and_no_kb_buttons; T-5130 test_ticket_card_without_knowledge_has_no_parts_and_renders, test_ticket_card_without_knowledge_has_no_article_button_section_or_link_tool |
| Записи `knowledge` | ключи (вопрос A-16): `kb-articles` (`kind="section"`, `order=10`), `kb-from-ticket` (`kind="closed_action"`, `order=10`), `kb-link-tool` (`kind="comment_tool"`, `order=10`); подробно — раздел 11 (часть c) | T-5119, T-5120 |

### 4.4. Поставщик «Заявки» и вложения `servicedesk`

| Что | Требование | Тесты |
|---|---|---|
| Поставщик «Заявки» | файл `apps/servicedesk/services/search_provider.py` поверх существующего `services/search.py` (план); регистрация в `apps/servicedesk/extensions.py` (решение 9 задач: T-5204); запись `SearchProvider(key="tickets", title="Заявки", order=10, …)` (ключ — вопрос A-1) | T-5126, T-5130 |
| `available(user)` | истина, если пользователь может видеть какие-то заявки (меню «Заявки» доступно ему — `access.menu_visible(user)`, факт; вопрос A-17: план говорит «видимость заявок (SPEC-003)») | T-5127 test_provider_available_false_hides_group |
| Отбор и порядок | `access.visible_tickets(user)`; заявка по номеру (`ParsedQuery.number`) — отдельный запрос по уникальному индексу номера, строка первой на первой странице (`offset == 0`) сверх `limit` основных строк; затем `search @@ to_tsquery('russian', raw)` без этого номера; порядок номер вниз; невидимая заявка по номеру строки не даёт; смещение `offset` считается по основному запросу без строки номера | T-5126 test_tickets_only_visible_to_user, test_invisible_ticket_number_gives_no_row, test_ticket_by_number_is_first_without_duplicate_in_main_selection, test_ticket_number_row_sits_above_twenty_main_rows_on_first_page, test_ticket_show_more_keeps_number_row_out_and_loses_no_row |
| `count(user, parsed)` | счёт с потолком: читается `LIMIT 1001` видимых заявок; при `>= 1001` → `(1000, True)`, иначе `(точное, False)` (`True` означает «больше потолка», страница пишет «1000+», раздел 3.2) | T-5126 test_ticket_count_capped_at_1001_shows_1000_plus, test_ticket_count_below_cap_is_exact |
| Строка | `SearchRow(title="#<номер> <тема>", subtitle=…, url="/tickets/<номер>/", template=…, context=…)`; в строке — номер, тема, состояние, очередь (как в списке заявок); `subtitle` — состояние и очередь одной строкой; шаблон `search/rows/_ticket.html` (A-9), ключи `context`: `state` (название состояния), `queue` (название очереди) | T-5126 test_ticket_row_has_number_subject_state_queue_and_url |
| Вложения заявок (решения 6 и 30 задач) | `servicedesk/services/attachments.py` пользуется проверками ядра; доступны под прежними именами: `is_executable`, `is_encrypted_archive`, `EXECUTABLE_EXTENSIONS`, `reason_of`, `MAX_FILE`, `MAX_MAIL`, `still_waiting`, `on_clean`, `on_found`, а также `MAX_FILES` (10) и `MAX_TOTAL` (50 МБ) (факт: константы есть в модуле, и тест пределов их читает: «10 файлов и 50 МБ на письмо без изменений»); `reason_of(name, data)` по-прежнему возвращает значение `Attachment.Rejected` (`executable`, `encrypted` или пустую строку) — коды ядра `"executable"` и `"encrypted"` переводятся в них; пределы `servicedesk` остаются своими (10 файлов, 50 МБ на письмо), `Attachment.Rejected` и `ServiceDeskError` не меняются; подмен `monkeypatch` на `attachments` и `uploads` в тестах нет (решение 30 задач) | T-5113 test_servicedesk_attachments_old_names_still_exported, test_servicedesk_rejected_codes_translated_from_core_reasons, test_servicedesk_limits_10_files_and_50_mb_unchanged; все тесты среза 003 на вложения — без правок |

### 4.5. `org`: поставщик «Подразделения»

| Что | Требование | Тесты |
|---|---|---|
| Файл и регистрация | `apps/org/services/search_provider.py`; регистрация в `apps/org/extensions.py` (решение 9 задач: T-5205); `SearchProvider(key="units", title="Подразделения", order=40, …)` (ключ — вопрос A-1) | T-5127, T-5130 |
| `available(user)` | право `staff.view` | T-5127 test_units_group_requires_staff_view |
| Отбор и порядок | `to_tsvector('russian', name) @@ to_tsquery('russian', raw)`; порядок `name`, затем `id`; `count` точный (`(число, False)`); «ё» и «е» равны (конфигурация `russian`) | T-5127 test_units_found_by_name_and_ordered_by_name, test_unit_e_yo_equivalence |
| Строка | `SearchRow(title=название, subtitle=путь, url="/structure/<id>/", …)`; путь — названия предков через « / » (`Unit.path` хранит цепочку номеров; названия предков собираются одним запросом на страницу, факт: `path` — текст с цепочкой номеров); у корня путь — пустая строка (A-18, принято) | T-5127 test_unit_row_has_name_ancestor_path_and_structure_url |
| Поиск сотрудника по подразделению | прежняя запись `staff_directory` (`directory._unit_search(text)`, факт: условие `Exists` по названиям узлов человека; `text` приведён — нижний регистр, «ё» → «е») без правок | T-5127 test_staff_found_by_unit_name_via_staff_directory |

## 5. Службы `knowledge`

Модули — `apps/knowledge/services/` (раздел 1.1). Службы вызывают представления и тесты; представления только разбирают
форму (план, «Создание, сохранение и публикация»). Все записи — в транзакции с `select_for_update` строки статьи.
Имена, которых нет в плане, помечены «вопрос B-N» (раздел 15, подраздел «Часть b»); до решения Opus они ничьим
решением не являются. Тексты отказов — раздел 12 (часть c); здесь только коды и поля.

### 5.1. Исключения и общие типы

| Что | Требование | Тесты |
|---|---|---|
| `KnowledgeError` | `apps/knowledge/services/__init__.py`: `class KnowledgeError(Exception)` с атрибутами `.code` (строка), `.field` (имя поля формы или `""`) — отказ формы: представление отвечает 200 с формой и сообщением (план, «Контракты»), введённое остаётся; сервис при отказе ничего не пишет (ни статьи, ни версии, ни журнала, ни события); модуля `errors.py` нет — в перечне модулей плана его нет (вопрос B-1) | T-5103, T-5104, T-5110, T-5112 |
| Подклассы | `ArticleError`, `RubricError`, `TagError`, `VersionError`, `FileRefused`, `SettingsError` (все от `KnowledgeError`), `VersionConflict(ArticleError)`; коды — в таблицах 5.2–5.8 | T-5103…T-5114 |
| `access.ArticleGone` | отдельное исключение (план: «своё исключение `ArticleGone`»), не от `KnowledgeError`; поднимают `access.get_for` (статья в корзине и смотрящий не управляющий) и службы записи (статья в корзине — отказ «Статья удалена», решения 43 и план, шаг 1); представление страницы превращает его в 410, представление POST-действия — в ответ 200 с текстом «Статья удалена» (раздел 12) и текстом формы | T-5107, T-5104 test_save_of_trash_article_gives_200_article_deleted_and_keeps_text_in_form, T-5109 |
| Нет права, невидимая статья | нет права на действие — `django.core.exceptions.PermissionDenied` (ответ 403, как прежние срезы); статья нет или не видна — `django.http.Http404` (ответ несуществующего, FR-409); новых классов для них нет | T-5109 test_stale_button_recheck_in_service, test_direct_post_without_button_checked_on_server |
| `ArticleForm` | `NamedTuple` в `articles.py`: `title: str`, `text: str`, `rubric_id: int \| None`, `tags: str` (как введено, через запятую), `comment: str = ""` (комментарий к правке); «после приведения» (план): перевод строк `\r\n` и `\r` → `\n`, пробелы по краям заголовка убираются, теги — `tags.normalize` (вопрос B-2: плана о типе `form` нет) | T-5103, T-5104 |
| `SaveResult` | `NamedTuple` в `articles.py`: `kind: str` (`"saved"`, `"no_changes"`, `"pdn_warning"`), `article: Article`, `version: ArticleVersion \| None` (новая версия при `saved`, иначе `None`), `pdn: list[str]` (найденное, пусто, если не `pdn_warning`); `no_changes` и `pdn_warning` — не исключения (это ответы формы, а не отказ); при `pdn_warning` и `no_changes` в базе ничего не меняется и журнал не пишется (вопрос B-2) | T-5103, T-5104, T-5117, T-5118 |
| `VersionConflict` | `.code == "stale_version"`, `.field == ""`; атрибуты: `.who` (строка — `core.person_name`-совместимое ФИО последнего сохранившего, `article.updated_by.full_name`), `.when` (`datetime` с часовым поясом — `article.updated_at`, текст ЧЧ:ММ по Москве строит шаблон), `.current_version` (`article.version_no` на момент отказа), `.base_version` (то, что прислала форма); из них представление строит «Статью уже изменил Имя Фамилия в ЧЧ:ММ» и ссылку `/kb/<id>/compare/?v=<base>&v=<current>`; текст формы остаётся, скрытое поле получает `current_version` | T-5104 test_save_with_stale_base_version_is_refused_with_who_and_when_and_compare_link, test_rejected_stale_save_keeps_typed_text_and_does_not_overwrite_newer_version, test_retry_after_rejection_with_updated_hidden_base_version_creates_next_version |

### 5.2. `articles`

Порядок шагов `save`, `publish`, `versions.restore` — план («Создание, сохранение и публикация»), шаги 1–7; здесь — подписи и что каждая отдаёт.

| Функция | Подпись и возврат | Отказы (код, поле) | Тесты |
|---|---|---|---|
| `articles.create` | `create(user, form: ArticleForm, *, from_ticket: int \| None = None) -> Article`; право `knowledge.edit` или `knowledge.manage` (иначе `PermissionDenied`); создаёт статью `draft`, `version_no=1`, версию 1 (`comment` — из формы), теги, `html`, `plain`, `author=updated_by=user`, журнал `knowledge.article_created`; всё одной транзакцией (сбой версии откатывает статью); векторов нет (`search_full` и `search_head` равны `NULL`); событий нет; `from_ticket` — только для «Статьи из решения» (`links.from_ticket`), у обычной формы `None` | `title_empty`, `title_too_long` (>200), поле `title`; `text_too_long` (>200 000), `text`; `rubric_missing` (рубрики нет), `rubric`; `comment_too_long` (>200), `comment`; `tags_too_many`, `tag_too_long`, поле `tags` (из `tags.normalize`) | T-5103 |
| `articles.save` | `save(user, article_id: int, base_version: int, form: ArticleForm, confirm_pdn: bool = False) -> SaveResult`; порядок отказов — как шаги плана: корзина (`ArticleGone`) → нет права (`PermissionDenied`; чужой черновик у не-управляющего — `Http404` из `get_for`) → рубрика (`rubric_missing`) → `VersionConflict` → «Изменений нет» (`kind="no_changes"`) → ПДн без `confirm_pdn` у опубликованной (`kind="pdn_warning"`) → запись; запись: версия `version_no + 1`, поля статьи, `updated_by/at`, векторы (только у опубликованной), событие `knowledge.article_changed` после фиксации (только у опубликованной, раздел 7) | те же `title_*`, `text_too_long`, `comment_too_long`, `tags_*`; проверка формы идёт до шага 1 (поле формы не зависит от состояния статьи) — вопрос B-3 | T-5104, T-5117, T-5118 |
| `articles.publish` | `publish(user, article_id: int, base_version: int, form: ArticleForm \| None = None, confirm_pdn: bool = False) -> SaveResult`; без `form` (кнопка на странице черновика) — публикация без версии; с `form` — шаги 1–5 `save`, затем публикация: изменён — новая версия и публикация, не изменён — публикация без версии; ПДн-проверка для черновика действует (шаг 6); `published_at` ставится только при первой публикации; `updated_at` и `updated_by` — время и тот, кто опубликовал (и при публикации без версии); векторы считаются; журнал `knowledge.article_published`; событие `knowledge.article_published` после фиксации; в `SaveResult.kind` — `"saved"` (публикация состоялась, в том числе без версии, `version=None`) или `"pdn_warning"`; право — `can_change` (`PermissionDenied` иначе; решение Opus по проверке контракта З10) | порядок отказов `publish`: `ArticleGone`; `PermissionDenied` по `can_change` (опубликованная — любой с `knowledge.edit`; черновик — автор с `knowledge.edit` или управляющий); затем `already_published` (код `ArticleError`, поле пусто) — повторная публикация опубликованной (вопрос B-4); `VersionConflict`, `ArticleGone`, поля формы — как у `save`; «Изменений нет» у публикации не бывает: публикация сама меняет состояние | T-5103 |
| Обратного перехода нет | у модуля `articles` нет функции, возвращающей статью в черновик (тест ищет в `dir(articles)` имена `unpublish`, `to_draft`, `revert`) | T-5103 test_published_article_has_no_return_to_draft_button_and_service_has_no_such_action |
| `articles.trash` | `trash(user, article_id: int) -> Article`; право `knowledge.manage` (`PermissionDenied`); `state_before_trash=state`, `state="trash"`, `deleted_at=timezone.now()`, `deleted_by=user`, векторы `NULL`, журнал `knowledge.article_trashed`; событий нет; статья уже в корзине — `ArticleGone` (двойное нажатие; вопрос B-4) | — | T-5107 |
| `articles.restore` | `restore(user, article_id: int) -> Article`; право `knowledge.manage`; `state=state_before_trash`, поля удаления и `state_before_trash` очищаются (`""`), у опубликованной векторы считаются заново, журнал `knowledge.article_restored`; событий нет; статья не в корзине — `ArticleError("not_in_trash")` | `not_in_trash` | T-5107 |
| `articles.purge` | `purge(article: Article, actor: User \| None, by_term: bool = False) -> None`; одна транзакция (план): `comments.delete_for("knowledge.article:<id>")`, строки `ArticleFile` и `StoredFile`, версии, связи, статья; журнал `knowledge.article_purged` (`before`: `number`, `title`, `by_term`; `actor` пусто у срока); файлы стираются с диска после фиксации (`transaction.on_commit`), отсутствующий файл — не ошибка (запись в журнал приложения без имени файла); строки `Tag` не удаляются; права не проверяет (проверяют `retention` и представление: ручное удаление — `knowledge.manage`) | — | T-5108 |
| Комментарии | `articles.add_comment(user, article_id: int, text: str) -> Comment` и `articles.delete_comment(user, comment_id: int) -> None`; плана имён нет (вопрос B-5); `add_comment`: статья опубликована (черновик — `Http404`; корзина — `ArticleGone`), текст — `core.comments.add` (`CommentError` пробрасывается), событие `knowledge.comment_added` после фиксации; `delete_comment`: автор комментария или управляющий (иначе `PermissionDenied`), `core.comments.delete`; чужой комментарий (удаляет управляющий) — журнал `knowledge.comment_deleted`, свой — журнала нет | `CommentError` ядра (раздел 3.4) | T-5116 |
| Показ статьи | `articles.viewed(user, article) -> None` публикует `object.viewed` (раздел 7.2); вызывает представление страницы после проверки доступа (не при 404 и 410) | — | T-5103 test_viewing_article_publishes_object_viewed_with_knowledge_article_ref |

### 5.3. `versions`

| Функция | Подпись и возврат | Отказы | Тесты |
|---|---|---|---|
| `versions.restore` | `restore(user, article_id: int, number: int, confirm_pdn: bool = False) -> SaveResult`; та же цепочка, что у `save` (шаги 1, 2, 5–7), поля берутся из версии `number`; рубрика версии пуста (удалена) — остаётся текущая; `comment="Восстановлено из версии N"`; версия, равная по содержимому текущей, — `kind="no_changes"`; опубликованная и ПДн без подтверждения — `pdn_warning`; прежние версии не меняются; версия `number` нет — `Http404` | `ArticleGone`, `PermissionDenied`, `VersionConflict` не бывает (базовой версии у восстановления нет) | T-5106, T-5118 |
| `versions.delete` | `delete(user, article_id: int, number: int) -> None`; право `knowledge.manage`; номер текущей версии (`number == version_no`) — `VersionError("current_version")`; строка версии удаляется, `version_no` и номера прочих не меняются, журнал `knowledge.version_deleted`; версии нет — `Http404` | `current_version` | T-5106 |
| `versions.compare` | `compare(article: Article, a: int, b: int) -> Comparison`; в плане написано `diff.compare(old, new)`, а модуля `diff` в перечне нет — функция живёт в `versions` (вопрос B-6); обе версии нужны: одной из них нет (удалена) — `VersionError("deleted")` (подсказка «Версия удалена»); старший номер — «стало» независимо от порядка `a`, `b`; `Comparison` — `NamedTuple`: `old: int`, `new: int` (номера, `new > old`), `fields: list[FieldDiff]` (`FieldDiff(name, before, after)`, `name` из `"title"`, `"rubric"`, `"tags"`, только изменённые; рубрика — по снимку `rubric_name`), `lines: list[DiffLine]` (`DiffLine(kind, text)`, `kind` — `"same"`, `"add"`, `"del"`; свёртка контекста и первые 2 000 изменений — часть вида, а не данных), `more: int` (сколько изменений сверх 2 000 не показано, иначе 0); текст строк не экранируется службой — экранирует шаблон | `deleted` | T-5105 |

### 5.4. `rubrics`, `tags`, `subscriptions`

| Функция | Подпись и возврат | Отказы (код, поле) | Тесты |
|---|---|---|---|
| `rubrics.create` | `create(user, name: str, parent_id: int \| None) -> Rubric`; право `knowledge.manage`; замок `pg_advisory_xact_lock(hashtextextended(%s, 0))` с ключом `knowledge.rubrics` (параметром, решение 31); `depth = родитель.depth + 1`; название после `strip()`; журнал `knowledge.rubric_created` | `name_empty`, `name_too_long` (>100), `name_duplicate` (сосед без учёта регистра, среди корневых тоже), поле `name`; `too_deep` (родитель на третьем уровне), `parent_missing`, поле `parent` | T-5110 |
| `rubrics.rename` | `rename(user, rubric_id: int, name: str) -> Rubric`; «Общее» переименовывается; журнал `knowledge.rubric_renamed` | `name_*` как выше | T-5110, T-5111 |
| `rubrics.move` | `move(user, rubric_id: int, parent_id: int \| None) -> Rubric`; пересчёт `depth` поддерева в той же транзакции; журнал `knowledge.rubric_moved` | `parent_self`, `parent_descendant`, `depth_exceeded` (глубина места + высота поддерева > 3), `default_immovable` («Общее» под другую рубрику), `name_duplicate` (сосед с тем же названием, решение 34), поле `parent`; последнее — поле `name` | T-5111 |
| `rubrics.delete` | `delete(user, rubric_id: int) -> None`; журнал `knowledge.rubric_deleted`; подписки уходят каскадом | `not_empty` (подрубрики или статьи, в том числе в корзине — «Сначала перенесите»), `default_undeletable` («Общее»), поле пусто | T-5111 |
| `rubrics.tree` | `tree() -> list[RubricNode]`; `RubricNode(rubric: Rubric, children: list[RubricNode])`; порядок среди соседей — `Lower(name)`; один запрос, дерево собирается в памяти; им пользуется выбор рубрики в форме статьи (план: отдельного адреса нет) — имя функции вопрос B-7 | — | T-5110, T-5112 (число запросов главной не растёт) |
| `tags.normalize` | `normalize(raw: str) -> list[str]`; каждый тег — `strip()`, внутренние пробелы в один, `lower()`; пустые выброшены, повторы склеены (остаётся первое вхождение, порядок ввода сохраняется; сравнение «изменилось ли» берёт отсортированный набор — `sorted(...)` вызывающий); в базу не ходит; больше 10 тегов — `TagError("tags_too_many")`, тег длиннее 40 — `TagError("tag_too_long")`, поле `tags` (проверка после обрезки и склейки повторов; «VPN, vpn, Vpn» — один тег) | `tags_too_many`, `tag_too_long` | T-5112 |
| `tags.suggest` | `suggest(q: str) -> list[str]`; до 10 имён тегов опубликованных статей по `istartswith`, параметром ORM; право `knowledge.edit` проверяет представление (имя функции — вопрос B-7) | — | T-5112 |
| `subscriptions.toggle` | `toggle(user, rubric_id: int) -> bool`; `True` — теперь подписан, `False` — подписка снята; только на себя (чужого пользователя функция не принимает); журнала нет; рубрики нет — `Http404` | — | T-5111, T-5122 |
| Увольнение | `subscriptions.on_user_dismissed(*, user_id: int, actor_id: int \| None = None) -> None` — подписчик события ядра `core.user_dismissed` (ключи — факт `apps/core/services/accounts.py`: `user_id`, `actor_id`), удаляет подписки уволенного; подключается в `KnowledgeConfig.ready()` (`events.subscribe`); сбой шина пишет в журнал и не роняет (правила среза) | — | T-5122 test_dismissal_event_deletes_dismissed_employee_subscriptions |

### 5.5. `files` (файлы статьи)

Модуль `knowledge/services/files.py`; ядро — `core.uploads` (3.5).

| Функция | Подпись и возврат | Отказы | Тесты |
|---|---|---|---|
| `files.attach` | `attach(user, article_id: int, upload) -> ArticleFile`; `upload` — загруженный файл Django (`.name`, `.size`, `.read()`); под замком статьи: статья сохранена (нет — `Http404`), не в корзине (`ArticleGone`), право править (`can_change`, `PermissionDenied`); затем файлов меньше 20, размер ≤ 20 МБ (ровно 20 МБ принимается), `uploads.reject_reason(name, data, size, 20 * 1024 * 1024)`; `image_format = uploads.detect_image(data)`; `uploads.store(data, name, "knowledge")`; строка `ArticleFile(name=upload.name)`; журнала нет | `FileRefused` с `.code`: `too_big`, `executable`, `encrypted` (коды ядра), `limit_20` («У статьи уже 20 файлов»), `image_too_large` (из `uploads.ImageTooLarge`, решение 42), `write_failed` (`OSError` хранилища, решение 41); поле `""`; транзакция откатывается, статья и её текст целы, ответ не 500 | T-5114 |
| `files.remove` | `remove(user, file_id: int) -> None`; то же право; строки `ArticleFile` и `StoredFile` удаляются, файл с диска — после фиксации; в тексте остаётся `att:N` (даёт заглушку); журнала нет; файла нет — `Http404` | — | T-5114 |
| `files.list_for` | `list_for(article) -> list[ArticleFile]`; порядок `uploaded_at`, `id`; с `select_related("file")` (состояние проверки читается без запроса на строку) — имя функции вопрос B-7 | — | T-5114, T-5115 |
| `files.files_map` | `files_map(article) -> dict[int, tuple[str, str]]`: `{N: (имя, image_format)}` для `render.render` (6.1); один запрос; имя функции — вопрос B-7 | — | T-5102, T-5115 |
| Запись `FilePurpose("knowledge", …)` | точка `file_purposes` (CONTRACT-003/004); `still_waiting(stored)` — строка `ArticleFile` есть и `stored.status == pending`; `clean(stored)` — `uploads.move(stored, clean)`, возвращает список старых путей; `found(stored, signature)` — подпись с началом `Heuristics.Encrypted.` — строки `ArticleFile` и `StoredFile` удаляются, иначе `uploads.move(stored, quarantine, signature)`; функции и порядок аргументов — как у `servicedesk` (факт `attachments.on_clean`, `on_found`) | — | T-5114 test_purpose_knowledge_* |

### 5.6. `links` (связь с заявками)

| Функция | Подпись и возврат | Отказы | Тесты |
|---|---|---|---|
| `links.link` | `link(user, article_id: int, ticket_number: int) -> TicketLink`; право `can_edit`; статья опубликована (иначе `Http404`); заявку видит `user` (`servicedesk.public.ticket_brief`, нет — `Http404`); повторная привязка того же — возвращает существующую строку без ошибки (уникальность `article`, `ticket_number`); журнала нет | — | T-5119 |
| `links.unlink` | `unlink(user, link_id: int) -> None`; право `can_edit` и заявку видит; связи нет — `Http404`; журнала нет | — | T-5119 |
| `links.from_ticket` | `from_ticket(user, number: int) -> FromTicketResult`; `FromTicketResult(article: Article, created: bool)`; право `can_edit`; `ticket_brief(user, number)` нет или не видна — `Http404`; не закрыта с решением — `ArticleError("not_closed_with_resolution")`; замок `knowledge.from_ticket:<номер>:<id сотрудника>` (параметром, решение 31); есть черновик этого сотрудника с `Article.from_ticket == number` и связью `from_resolution=True` — `created=False`, он же; иначе создаётся: `title=pdn.mask_plain(тема)[:200]`, `text=pdn.mask_resolution(решение)`, рубрика «Общее», `TicketLink(from_resolution=True)`, версия 1 с комментарием «Создано из заявки #N», журнал `knowledge.article_created`; данных заявителя, адресов и переписки не берёт | `not_closed_with_resolution` | T-5120 |
| `links.tickets_for` | `tickets_for(user, article) -> list[TicketLinkView]`; `TicketLinkView(link: TicketLink, brief: TicketBrief)`; номера из `TicketLink`, затем `servicedesk.public.briefs`; только видимые `user`; статья в корзине — пустой список; порядок `linked_at`, `id`; без `servicedesk` — пусто | — | T-5120 |

### 5.7. `retention`, `settings`, `access`

| Функция | Подпись и возврат | Тесты |
|---|---|---|
| `retention.next_batch` | `next_batch(after_id: int, cutoff: datetime) -> list[int]`: до 100 номеров статей `state="trash"` и `deleted_at < cutoff` с номером больше `after_id`, по возрастанию; через неё идёт выборка порции — это точка подмены «действие между выборкой порции и замком строки» (решение 32; имя — вопрос B-8) | T-5108 test_nightly_processes_articles_in_ascending_number_in_batches_of_100, test_nightly_rechecks_state_and_term_under_lock_before_purge |
| `retention.purge_trash` | `purge_trash(now: datetime \| None = None) -> PurgeResult`; `PurgeResult(purged: int, skipped: int, failed: list[int])`; `cutoff = now − trash_days`; каждая статья — отдельная транзакция с `select_for_update(skip_locked=True)` и повторной проверкой состояния и срока (не в корзине, срок не вышел или строка занята — `skipped`); удаление — вызовом `articles.purge(article, None, by_term=True)` **атрибутом модуля** (`articles.purge(...)`, а не `from … import purge`), чтобы подмена `purge` из `support_kb` действовала; сбой одной статьи — `ERROR` в логгер `apps.knowledge.services.retention` с номером и классом исключения (без текста исключения), обход продолжается; в конце теги без единой статьи удаляются под исключительным замком `knowledge.tags` (параметром) | T-5108 |
| `tasks.purge_trash` | `apps.knowledge.tasks.purge_trash() -> None` — задание cron (1.2): вызывает `retention.purge_trash()`; если `failed` не пуст, после обхода поднимает `retention.PurgeFailed(RuntimeError)` с атрибутом `.numbers`; повторный запуск уже удалённых не находит, журнал не пишет; помощник `support_kb` вызывает именно её синхронно | T-5108 test_nightly_failure_of_one_article_does_not_stop_the_loop_and_job_fails_at_the_end |
| `settings.get` | `get() -> KnowledgeSettings` (строка `pk=1`; нет — создаёт с `trash_days=90`) | T-5108 test_settings_default_term_is_90_days |
| `settings.update` | `update(user, trash_days: int) -> KnowledgeSettings`; право `knowledge.manage`; 7–365 включительно, иначе `SettingsError("out_of_range")` с полем `trash_days` (6 и 366 — отказ; 7 и 365 — принимаются); журнал `knowledge.trash_days_changed` только если значение изменилось (`before`/`after` — раздел 8); то же значение — без записи и без журнала, без ошибки (вопрос B-9) | T-5108 |
| `access.can_edit`, `access.can_manage` | `can_edit(user) -> bool` — `permissions.has_permission(user, "knowledge.edit") or can_manage(user)`; `can_manage(user) -> bool` — `permissions.has_permission(user, "knowledge.manage")` (факт: имя функции ядра `has_permission`, не `has`; кэш прав ядра) | T-5109 |
| `access.visible_articles` | `visible_articles(user) -> QuerySet[Article]`: опубликованные; плюс свои черновики при `can_edit`; плюс все черновики при `can_manage` (в том числе уволенного автора); корзина не входит ни у кого | T-5109 test_visible_articles_set_per_role |
| `access.get_for` | `get_for(user, article_id: int) -> Article`; нет или не видна — `Http404`; в корзине: управляющему — статья, остальным `ArticleGone`; несуществующий номер — всегда `Http404` (не `ArticleGone`) | T-5109, T-5107 |
| `access.can_change`, `access.can_publish` | `can_change(user, article) -> bool`, `can_publish(user, article) -> bool` — по таблице FR-407: черновик — автор с `knowledge.edit` или управляющий; опубликованная — любой с `knowledge.edit` (управляющий включён); в корзине обе ложны (правит только возврат); `can_publish` — только для черновика и только признак показа кнопки «Опубликовать», а не проверка службы | T-5109 |

### 5.8. Подмены для тестов сбоев (решения 32 и 41; даёт `support_kb.py`, а не тест)

| Что | Какую точку кода подменяет | Тесты |
|---|---|---|
| Сбой удаления одной статьи в ночной очистке | фикстура подменяет **атрибут модуля** `apps.knowledge.services.articles.purge`: обёртка поднимает исключение для заданных номеров статей и вызывает настоящую функцию для остальных; работает потому, что `retention` обращается к ней атрибутом модуля | T-5108 test_nightly_failure_* |
| Действие между выборкой порции и замком строки | подмена `apps.knowledge.services.retention.next_batch`: обёртка вызывает настоящую, затем выполняет переданное действие (вернуть статью из корзины, удалить её, сдвинуть `deleted_at`) и возвращает порцию как была | T-5108 test_nightly_rechecks_*, test_nightly_skips_article_restored_in_the_meantime |
| Занятый замок предпросмотра | фикстура ставит в Valkey ключ `kb:preview:<user_id>` (клиент — тот же, что `apps/core/services/valkey.py`) на 10 секунд; никакой код подменять не надо | T-5102 |
| Сбой версии при первом сохранении (а) | `monkeypatch.setattr("apps.knowledge.services.articles._create_version", …)` (решение Opus по З21) | T-5103 test_first_save_rolls_back_article_when_version_creation_fails |
| Сбой рендера при предпросмотре (б) | представление вызывает `render.render` атрибутом модуля; тест подменяет `apps.knowledge.services.render.render` | T-5102 test_preview_lock_is_released_when_render_raises |
| Замок строки статьи, занятый другой транзакцией (в) | без второго соединения (раздел 16): тест проверяет, что выборка статьи ночной очисткой идёт `SELECT … FOR UPDATE SKIP LOCKED` (`support_kb.assert_skip_locked`), и что после выборки повторно проверяются состояние и срок | T-5108 test_nightly_skips_article_locked_by_another_transaction_skip_locked |
| Выключена только запись `staff_directory` (г) | помощник `support_kb.without_registrations("staff_directory")`; прочие регистрации остаются | T-5127 test_staff_without_org_uses_core_fields_only |
| «Модуль выключен» | снятие регистраций `knowledge` из реестра точек на время теста (раздел 3.1); `INSTALLED_APPS` не перезагружается | T-5127, T-5130 |
| Сбой записи файла при вложении (решение 41) | `uploads.store` пишет файл через функцию модуля `uploads.write_file(path, data)`; тест подменяет `apps.core.services.uploads.write_file` функцией, которая поднимает `OSError` (решение Opus по B-10: запрет решения 30 касается прежних тестов среза 003, а не новой точки подмены) | T-5114 test_attach_storage_write_error_keeps_article_and_shows_message_not_500 |

## 6. Рендер и ПДн

### 6.1. `render`

| Что | Требование | Тесты |
|---|---|---|
| Подпись | `render.render(text: str, files: dict[int, tuple[str, str]], article_id: int \| None = None) -> Rendered`; `files` — `{N: (имя, image_format)}` вложений этой статьи (получен до вызова: рендер в базу не ходит; строится `files.files_map`); адрес `/kb/<id>/…` нужен номер статьи, а в подписи плана его нет — третий параметр `article_id` (без него адресов не построить; до первого сохранения статьи номера нет, и `att:N` даёт заглушку — вопрос B-11) | T-5102 |
| `Rendered` | `NamedTuple("Rendered", [("html", str), ("plain", str)])` (неизменяемый, как прочие результаты; вопрос B-11) | T-5102 |
| Адреса | `att:N` у картинки (`![имя](att:N)`) своей статьи → `<img src="/kb/<id>/images/N/" alt="имя" loading="lazy">`; `att:N` у ссылки (`[имя](att:N)`) своей статьи → `<a href="/kb/<id>/files/N/">имя</a>` (внутренняя ссылка: без `rel` и `target`); адрес картинки от состояния проверки не зависит (HTML остаётся одним и тем же при `pending`, `clean`, `quarantine`); «своя» — номер N есть в `files` | T-5102, T-5115 test_rendered_html_img_src_does_not_depend_on_scan_state |
| Заглушка | картинка не своя (`att:N` нет в `files`), прямой путь `/kb/…`, внешний адрес → `<span class="kb-noimg">[вложение недоступно: имя]</span>`, где имя — подпись картинки (экранированная); картинка с адресом, не прошедшим `validateLink` (`data:`, `javascript:`, `//хост`, `/\хост`), остаётся буквальным текстом `![подпись](адрес)` (проба 25), без `img` и без заглушки; ссылка `att:N` чужая или удалённая → тот же текст `[вложение недоступно: имя]` в `span.kb-noimg`; текст по плану («[вложение недоступно: имя]»), а не «изображение недоступно» из выборки F1 Ф5 (проба проверена на прежнем тексте); класс `kb-noimg` — из выборки F1 Ф5, имя класса в плане не названо (вопрос B-12) | T-5102 test_render_att_of_foreign_article_gives_unavailable_placeholder, test_render_direct_kb_path_and_external_image_give_unavailable_placeholder |
| Ссылки | белый список адресов: `http`, `https`, `mailto`, путь от корня (`/…`, но не `//…` и не `/\…`, без пробелов и управляющих знаков), `att:N`; внешняя ссылка получает `rel="noopener noreferrer"` и `target="_blank"`; внутренняя (путь от корня, `att:N`) — без них; недопустимая ссылка остаётся в выводе буквальным текстом `[подпись](адрес)` (поведение markdown-it без `validateLink`), ссылки нет | T-5102 |
| Выравнивание таблицы | столбцы — классами `kb-al-left`, `kb-al-center`, `kb-al-right` на `th` и `td`; атрибута `style` в выводе нет нигде | T-5102 test_render_table_alignment_uses_kb_al_class_and_no_style_attribute; T-5129 |
| Прокрутка | таблица и блок кода (`pre`) оборачиваются в `<div class="kb-scroll">…</div>`; прочий вывод — без оболочки | T-5102 test_render_table_and_code_block_are_wrapped_in_kb_scroll |
| Белый список после `nh3` | теги: `p`, `br`, `strong`, `em`, `del`, `code`, `pre`, `blockquote`, `ul`, `ol`, `li`, `h1`…`h6`, `hr`, `a`, `img`, `table`, `thead`, `tbody`, `tr`, `th`, `td`, `div`, `span`; атрибуты: `a` — `href`, `title`, `rel`, `target`; `img` — `src`, `alt`, `loading`; `div`, `span`, `th`, `td` — `class`; значение `class` — только слова `kb-*`; `src` — только `^/kb/<id статьи>/images/\d+/$`; `href` — `http`, `https`, `mailto`, путь от корня (не `//`, не `/\`) или `^/kb/<id статьи>/files/\d+/$`; перечень белого списка тест берёт из этой строки (план даёт «белый список тегов и атрибутов», не перечисляя его — вопрос B-12) | T-5102 test_render_36_probes_output_has_no_tags_or_attributes_outside_whitelist, test_render_second_nh3_filter_strips_foreign_src_href_and_non_kb_class |
| Вложенность | `maxNesting=20`: 200 вложенных цитат или скобок не роняют рендер и не дают небезопасного вывода (исключения наружу нет) | T-5102 test_render_deep_nesting_does_not_crash_and_output_stays_safe |
| `plain` | текст из токенов того же разбора: текст, код, подписи картинок; без адресов ссылок, без `title`, без заголовка статьи; блоки и ячейки разделены переводом строки; обрезка до 100 000 знаков (ровно 100 000 остаётся, 100 001 → 100 000) | T-5102 test_render_plain_has_no_link_urls_no_title_and_keeps_code_and_image_captions, test_render_plain_is_truncated_to_100000_characters |
| Комментарии | не рендерятся (шаблон: экранирование и `linebreaksbr`); ссылки остаются текстом | T-5102 test_comment_text_is_escaped_with_line_breaks_and_links_stay_plain_text |
| Предпросмотр и `kb_rerender` | `html` предпросмотра для того же текста и тех же `files` равен `html` сохранённой статьи (одна функция); `kb_rerender` (1.4) вызывает ту же `render.render` | T-5102 test_preview_html_equals_html_of_saved_article_for_same_text_and_files |

### 6.2. Перечень 36 проб рендера (решение 39)

Основа — 36 проб F1 Ф5 (`crm-work/slice005/plan/facts/F1-markdown.md`, полный вывод — `/tmp/facts005-md/probes.out`, число строк с пробами 36, нарушений 0). Условия: статья № 7; `files = {1: ("схема", "png"), 2: ("рисунок", "jpeg"), 3: ("инструкция.pdf", "")}`. Пробы перенесены в термины плана: `вложение:N` → `att:N`; адрес картинки `/kb/7/files/N/` → `/kb/7/images/N/`; выравнивание — классами, а не `style`; заглушка — текст `[вложение недоступно: подпись]`; ссылка `att:N` оживает адресом файла (в выборке F1 она теряла `href`). Тест `test_render_36_probes_output_has_no_tags_or_attributes_outside_whitelist` прогоняет все 36 строк, разбирает вывод `html.parser`, проверяет общие запреты и условия строки; адреса почты и телефоны в пробах не использованы (в пробах с адресом почты она собирается в коде теста из частей, правило среза). Общие запреты для каждой пробы: в выводе нет тегов вне белого списка (6.1), нет атрибутов `on…`, `style`, `srcset`, нет `href` и `src` вне правил, нет внешней ссылки без `rel="noopener noreferrer"`; в столбце «Запрещено» — то, что сверх общего.

| № | Вход Markdown | Запрещено в выводе | Обязано остаться |
|---|---|---|---|
| 1 | `<script>alert(1)</script>` | тег `script` | текст `&lt;script&gt;alert(1)&lt;/script&gt;` в `p` |
| 2 | `<img src=x onerror=alert(1)>` | тег `img`, атрибут `onerror` | экранированный текст разметки |
| 3 | `<svg onload=alert(1)></svg>` | тег `svg`, `onload` | экранированный текст |
| 4 | `<iframe src=//evil></iframe>` | тег `iframe` | экранированный текст |
| 5 | `<div style="x" onclick="y">hi</div>` и после пустой строки `text` | тег `div` из текста пользователя, `style`, `onclick` | экранированный текст блока, абзац `text` |
| 6 | `<!-- x --> a` | комментарий HTML в выводе | экранированный текст `&lt;!-- x --&gt; a` |
| 7 | `[x](javascript:alert(1))` | `href` со схемой `javascript` | буквальный текст `[x](javascript:alert(1))`, тега `a` нет |
| 8 | `[x](JaVaScRiPt:alert(1))` | то же в любом регистре | буквальный текст, тега `a` нет |
| 9 | `[x](jav&#x61;script:alert(1))` (сущность внутри схемы) | `href` со схемой `javascript` после раскрытия сущности | текст, тега `a` нет |
| 10 | `[x](java` + табуляция + `script:alert(1))` | `href` с табуляцией внутри схемы | текст, тега `a` нет |
| 11 | `[x](vbscript:msgbox(1))` | `href` со схемой `vbscript` | текст, тега `a` нет |
| 12 | `[x](data:text/html;base64,PHNjcmlwdD4=)` | `href` со схемой `data` | текст, тега `a` нет |
| 13 | `[x](//evil.com/a)` | `href`, начинающийся с `//` | буквальный текст, тега `a` нет |
| 14 | `[x](/\evil.com)` (обратная косая после `/`) | `href`, в котором обратная косая стоит «сырой» (после браузерного разбора адрес ушёл бы на чужой сайт) | либо буквальный текст, либо `href` со знаком `%5C` и без чужого узла: путь своего сайта (выборка F1: `href="/%5Cevil.com"`); тест принимает любую из двух форм, но требует отсутствия `/\` в значении |
| 15 | `<javascript:alert(1)>` (автоссылка) | `href` со схемой `javascript` | экранированный текст, тега `a` нет |
| 16 | `<http://ok.example/a?b=1>` | `href` без `rel`, `target` | `<a href="http://ok.example/a?b=1" rel="noopener noreferrer" target="_blank">` |
| 17 | автоссылка на адрес почты в угловых скобках (собирается в коде теста) | `href` без `mailto:` | `<a href="mailto:…" rel="noopener noreferrer" target="_blank">` |
| 18 | `http://bare.example/x` (голый адрес) | тег `a` (автоссылок без `<…>` нет) | простой текст адреса |
| 19 | `[x](http://a.example "t\" onmouseover=\"alert(1)")` (кавычка в `title`) | отдельный атрибут `onmouseover`; закрытие `title` раньше срока | `title="t&quot; onmouseover=&quot;alert(1)"` целиком внутри значения |
| 20 | `[x](http://a.example/"onmouseover="alert(1))` (кавычка в адресе) | отдельный атрибут `onmouseover` | кавычка в `href` закодирована `%22` |
| 21 | `&lt;script&gt;alert(1)&lt;/script&gt; &#60;b&#62;` (сущности) | тег `script` и `b` после раскрытия сущностей | текст `&lt;script&gt;…&lt;b&gt;` (остаётся текстом, не становится тегом) |
| 22 | таблица `\| a \| <b onclick=x>b</b> \|`, строка-разделитель, `\| <script>1</script> \| [y](javascript:1) \|` (разметка в ячейках) | `b`, `script`, `onclick`, ссылка `javascript` в ячейках | таблица `table/thead/tbody/tr/th/td` в оболочке `kb-scroll`; содержимое ячеек — текстом |
| 23 | `[x][1]`, пустая строка, `[1]: javascript:alert(1)` (ссылка-определение) | `href` со схемой `javascript` | `[x][1]` и строка определения — текстом, тега `a` нет |
| 24 | `![x](http://evil.example/p.png)` (внешняя картинка) | тег `img`, любой внешний `src` | `<span class="kb-noimg">[вложение недоступно: x]</span>` |
| 25 | `![x](data:image/svg+xml;base64,PHN2Zz4=)` (картинка `data:`) | тег `img`, `src` со схемой `data` | буквальный текст `![x](data:…)` (ссылка не прошла проверку адреса), `img` нет |
| 26 | `![x](/kb/8/files/1/)` (прямой путь чужой статьи) | тег `img` | заглушка `kb-noimg` |
| 27 | `![x](/kb/7/files/2/)` (прямой путь своей статьи, не форма `att:`) | тег `img` (только форма `att:N`) | заглушка `kb-noimg` |
| 28 | `![x](att:99)` (чужое или несуществующее вложение) | тег `img` | заглушка `kb-noimg` |
| 29 | `![схема](att:1)` (своё вложение) | `src`, не равный адресу картинки этой статьи | `<img src="/kb/7/images/1/" alt="схема" loading="lazy">` |
| 30 | `![рисунок](att:2)` | то же | `<img src="/kb/7/images/2/" alt="рисунок" loading="lazy">` |
| 31 | `![a" onerror="x](att:1)` (кавычки в `alt`) | отдельный атрибут `onerror` | `alt="a&quot; onerror=&quot;x"` целиком в значении, `src` картинки статьи |
| 32 | `[f](att:3)` (вложение как ссылка) | ссылка без `href` (выборка F1: `<a rel target>` без `href`); `rel` и `target` у внутренней ссылки | `<a href="/kb/7/files/3/">f</a>` |
| 33 | `[ok](/kb/3/) [m](mailto:…) [h](https://e.example/)` | внешним — отсутствие `rel`/`target`; внутренней — их наличие | `<a href="/kb/3/">` без `rel` и `target`; `mailto` и `https` с `rel="noopener noreferrer" target="_blank"` |
| 34 | `` `<b>` and `` и блок из трёх обратных кавычек с `<script>x</script>` | теги `b` и `script` | `<code>&lt;b&gt;</code>`, `<pre><code>…&lt;script&gt;x&lt;/script&gt;…</code></pre>` в оболочке `kb-scroll` |
| 35 | таблица с выравниванием `\|a\|b\|`, `\|:-\|-:\|`, `\|1\|2\|` | атрибут `style`, `text-align` в любом виде | у `th` и `td` первого столбца класс `kb-al-left`, второго — `kb-al-right` |
| 36 | `> **q**`, `# H`, список `1. a`, `2. b`, `- c` | теги вне белого списка | `blockquote`, `strong`, `h1`, `ol`, `ul`, `li` (допустимая разметка не теряется) |

Выборка F1 Ф5 даёт 36 проб (в нумерации выборки две из них — `own img` с `вложение:1` и `own img ascii` с `att:2` — теперь обе в форме `att:N`: № 29 и 30; проба `att as link` — № 32). Число строк таблицы — ровно 36; выравнивание в форме `center` отдельной пробой не стоит (его проверяет `test_render_table_alignment_uses_kb_al_class_and_no_style_attribute`). Всё, что в плане сверх выборки F1 (`kb-scroll`, `maxNesting`, фильтр `class`, `att:N` у ссылок, `images`/`files`), тест 36 проб проверяет только общими запретами и строками 22, 32, 34, 35; остальное — отдельные тесты T-5102.

### 6.3. `pdn`

Шаблоны плана («Защита от ПДн») не повторяются; ниже — подписи и форма результата.

| Что | Требование | Тесты |
|---|---|---|
| `pdn.find(title, text) -> list[str]` | обход токенов markdown-it (как у `plain`) с пропуском `code_inline`, `fence`, `code_block`; между токенами, блоками, ячейками и строками — перевод строки; к склейке добавляются адреса ссылок `mailto:…`; заголовок проверяется целиком; найденное — **найденные подстроки** (совпадение шаблона как есть), без повторов, в порядке первого вхождения, не больше 20; ничего не найдено — пустой список; в базу не ходит и ничего не пишет | T-5117 |
| Что находит и что нет | почта (в том числе в зоне `.рф`, буквы любого алфавита); телефон: `+7` или `8` и ещё 10 цифр (пробелы, табуляция, дефисы, скобки между ними допустимы; без разделителей — `8` и 10 цифр находится); не находит: телефон с точками, 10 цифр без `+7` и `8` (ИНН), телефон, разорванный переводом строки, адрес в блоке и во встроенном коде; адрес сразу после заголовка не склеивается с заголовком; адрес в ячейке таблицы находится | T-5117 test_email_pattern_*, test_phone_pattern_*, test_find_* |
| Тестовые данные | адреса и телефоны собираются из частей в коде теста (правила среза, решение 17); в этом файле и в ответах — без настоящих значений | все T-5117, T-5118 |
| `pdn.mask_plain(text: str) -> str` | `\r\n` → `\n`, затем `re.sub` шаблонов почты и телефона по всему тексту; найденное заменяется постоянной строкой `[скрыто]` (вопрос B-13: в плане сказано «скрывает», не чем); тема заявки целиком простой текст | T-5118 |
| `pdn.mask_resolution(text: str) -> str` | то же, но строки внутри ограждений из трёх обратных кавычек и из трёх `~` и участки в обратных кавычках на остальных строках не меняются; построчный проход; отступ в 4 пробела кодом не считается (скрывается); телефон, разорванный `\r\n` (после приведения `\n`), не скрывается — как и не находится `find` | T-5118 |
| Журнал и ответ | найденное в журнал не пишется; ответ при `pdn_warning` — список (до 20 строк) и две кнопки (раздел 11, часть c) | T-5118 test_found_pdn_not_written_to_journal |

## 7. События шины `knowledge.*` и виды уведомлений

### 7.1. События шины

Шина — `apps/core/events.py` (`publish(name, **data)`). Ключи данных названы в плане («Точки расширения ядра и шина событий»); добавлено только то, что плану не противоречит (данные — идентификаторы, а не объекты, по образцу `servicedesk/services/events.py`; обработчик читает остальное из базы) — вопрос B-14. Публикуются **после фиксации** транзакции (`transaction.on_commit`), поэтому тесты берут `django_capture_on_commit_callbacks(execute=True)` (правила среза); откат транзакции события не оставляет; черновик, корзина, возврат, удаление событий не дают.

| Событие | Когда | Ключи данных | Тесты |
|---|---|---|---|
| `knowledge.article_published` | `articles.publish` состоялась | `article_id: int`, `actor_id: int` (кто опубликовал), `rubric_id: int` | T-5103 test_publish_makes_article_visible_to_all_writes_journal_publication_and_event_article_published, T-5121 |
| `knowledge.article_changed` | `articles.save` или `versions.restore` у **опубликованной** статьи создали версию | `article_id: int`, `actor_id: int` (кто сохранил), `rubric_id: int`; ключа `version` нет (решение Opus: ровно по плану, тест сверяет множество ключей точно) | T-5104 test_article_changed_event_is_published_only_for_published_article_not_for_draft, T-5121 |
| `knowledge.comment_added` | `articles.add_comment` | `article_id: int`, `comment_id: int`, `actor_id: int` (автор комментария) | T-5116 test_comment_added_event_published_after_commit_with_article_and_comment, T-5121 |
| Что события не несут | текст статьи, текст комментария, заголовок, ФИО (обработчик читает из базы); ключей `url`, `link`, `key`, `code`, `secret`, `token`, `password` нет | T-5116, T-5121 |
| `object.viewed` | `articles.viewed` при показе страницы статьи: `bus.publish("object.viewed", object_ref=f"knowledge.article:{article.pk}", user_id=user.pk)` (ключи — факт `servicedesk/services/events.py` и `reading.on_object_viewed(*, object_ref, user_id)`); публикуется сразу (GET, не `on_commit`); при 404 и 410 не публикуется | T-5103, T-5123 test_object_viewed_for_article_marks_unread_notification_read |

### 7.2. Виды уведомлений (`knowledge/notify_kinds.py`, точка `notification_kinds`)

Функция точки `notification_kinds() -> list[NotificationKind]` (образец — факт `servicedesk/notify_kinds.py`: свежие объекты при каждом вызове); у всех трёх: `module="База знаний"`, `default_channels=("portal", "email")` (план: «На портале» и «Почта»; остальные каналы по умолчанию выключены, включаются данными), `coalesce=True`, `mandatory=False`.

| Код | Название (`title`) | `events` | `order` | Тесты |
|---|---|---|---|---|
| `knowledge.comment_on_my_article` | «Новый комментарий к моей статье» | `("knowledge.comment_added",)` | 50 | T-5121 test_catalog_contains_three_knowledge_kinds_with_codes_titles_and_module, test_knowledge_kinds_events_and_coalesce_flag_match_plan_table |
| `knowledge.my_article_changed` | «Мою статью изменили» | `("knowledge.article_changed",)` | 51 | T-5121 |
| `knowledge.rubric_subscription` | «Статья в рубрике по подписке» | `("knowledge.article_published", "knowledge.article_changed")` | 52 | T-5121 |

Порядок в каталоге: после видов сервис-деска (10–40) и до видов ядра (110–130) и `notify` (200) (решение 25).

| Что | Требование | Тесты |
|---|---|---|
| Текст на портале и в письме (`Draft.text`; дословно) | `knowledge.comment_on_my_article` — «Новый комментарий к вашей статье «{заголовок}»»; `knowledge.my_article_changed` — «Вашу статью «{заголовок}» изменил {Имя Фамилия}»; `knowledge.rubric_subscription` — «Статья в рубрике «{рубрика}»: {заголовок}» (одинаков для `article_published` и `article_changed`); кавычки — «ёлочки», как в плане; `{Имя Фамилия}` — `full_name` того, кто сохранил; `{рубрика}` — название рубрики подписки получателя, ближайшей к статье (раздел 17 п. 51; B-15 отменён) | T-5122 test_portal_and_mail_texts_for_* |
| Текст внешних каналов (`external_text`; дословно) | «Новый комментарий к вашей статье»; «Вашу статью изменили»; «Новая статья в рубрике по подписке»; заголовка статьи, рубрики и имени в них нет | T-5122 test_external_channels_text_for_all_three_kinds_has_no_article_title, test_external_channels_carry_only_event_text_and_link |
| Обрезка | заголовок статьи, название рубрики и имя сохранившего — каждое по отдельности: длиннее 100 знаков (по символам) — первые 99 и «…» (итого 100), ровно 100 — без изменений (факт: `servicedesk/notify_kinds._subject`, `SUBJECT_LIMIT = 100`); итоговый текст не длиннее 300 (`Notification.text`) при заголовке 200, рубрике 100 и имени 255 знаков | T-5122 test_title_of_200_chars_*, test_rubric_name_of_100_chars_*, test_editor_name_of_255_chars_*, test_notification_text_never_exceeds_300_chars_* |
| `object_ref` и ссылка | `object_ref = "knowledge.article:<id>"` у всех трёх; `url = "/kb/<id>/"`, у «Нового комментария» — `"/kb/<id>/#comments"` | T-5122 test_notification_object_ref_and_link_point_to_article_and_comment_anchor |
| Получатели `build` | комментарий — автор статьи, если он не автор комментария; изменение — автор статьи, если сохранил другой; подписка — подписчики рубрики статьи и её предков (множество пользователей, подписка на рубрику и подрубрику даёт одного), без исполнителя (`actor_id`), на `article_changed` — ещё без автора статьи; на `article_published` автора уведомляет только его подписка; статья не опубликована или нет статьи — пустой список; уволенных отбрасывает `notify` (`RECIPIENT_STATES`), право автора не проверяется | T-5121 |
| `available(user)` | «Новый комментарий» и «Мою статью изменили» — есть `knowledge.edit` или `knowledge.manage`, либо автор хотя бы одной статьи (`exists`); «По подписке» — всем | T-5121 test_available_* |
| `still_relevant(user_id, object_ref)` | статья существует и опубликована, получатель не уволен; `object_ref` не вида `knowledge.article:<id>` — ложь | T-5122 test_still_relevant_* |
| Склейка | вид с `coalesce=True`: пока есть непрочитанное уведомление того же вида по той же статье, новое не создаётся (раздел 4.1); три вида склеиваются каждый отдельно | T-5121 test_second_comment_not_notified_while_first_unread_and_new_one_after_reading, T-5123 |

## 8. Журнал

Запись — `audit.record(action, *, actor, object_type, object_id, before, after)` (факт: `apps/core/services/audit.py`); `object_id` — строка (идентификатор объекта), `actor` пуст у «системы». Ядро скрывает значения ключей `password`, `token`, `secret`, `key`, `code`, `link`, `url` и подобных (`audit._scrub`, факт); ключи среза их не используют. Набор ключей по действиям плану неизвестен (план даёт общий перечень ключей) — предложен ниже (вопрос B-16).

### 8.1. Коды, типы, ключи

| Код действия | `object_type`, `object_id` | `actor` | `before` | `after` | Тесты |
|---|---|---|---|---|---|
| `knowledge.article_created` | `knowledge.article`, номер статьи | автор | `{}` | `number`, `title`, `version` (=1) | T-5124 test_creating_article_writes_article_created_with_author_actor |
| `knowledge.article_published` | `knowledge.article`, номер | кто опубликовал | `{}` | `number`, `title`, `version` (текущий номер версии) | T-5124 |
| `knowledge.article_trashed` | `knowledge.article`, номер | управляющий | `{}` | `number`, `title` | T-5124 |
| `knowledge.article_restored` | `knowledge.article`, номер | управляющий | `{}` | `number`, `title` | T-5124 |
| `knowledge.article_purged` | `knowledge.article`, номер (удалённой статьи) | управляющий; у срока — пусто | `number`, `title`, `by_term` (логическое: `false` вручную, `true` по сроку) | `{}` | T-5124 test_manual_purge_*, test_purge_by_term_* |
| `knowledge.version_deleted` | `knowledge.article`, номер статьи | управляющий | `number`, `title`, `version` (номер удалённой версии) | `{}` | T-5124 |
| `knowledge.comment_deleted` | `knowledge.article`, номер статьи | управляющий | `number`, `title` (текста комментария нет) | `{}` | T-5124 |
| `knowledge.rubric_created` | `knowledge.rubric`, номер рубрики | управляющий | `{}` | `name`, `path` | T-5110, T-5124 |
| `knowledge.rubric_renamed` | `knowledge.rubric`, номер | управляющий | `name`, `path` | `name`, `path` | T-5110, T-5124 |
| `knowledge.rubric_moved` | `knowledge.rubric`, номер | управляющий | `name`, `path` | `name`, `path` | T-5111, T-5124 |
| `knowledge.rubric_deleted` | `knowledge.rubric`, номер (удалённой) | управляющий | `name`, `path` | `{}` | T-5111, T-5124 |
| `knowledge.trash_days_changed` | `knowledge.article`, пустой `object_id` (у срока своего вида объекта нет — вопрос B-17) | управляющий | `days` | `days` | T-5108, T-5124 test_trash_days_change_writes_was_and_became_days_in_before_and_after |

`path` — названия рубрик от корня до этой через « / » (например, «Общее / Сети»); `days` — целое; `by_term` — логическое; `number` — номер статьи (тот же, что в адресе `/kb/<id>/`); `version` — целое. В `before` и `after` нет ключей, кроме `number`, `title`, `version`, `name`, `path`, `days`, `by_term` (тест читает все записи среза и сверяет множество ключей); текста статьи, комментария, имён вложений и ФИО в записях нет. Правки текста, подписка, привязка к заявке, вложения и поисковые запросы в журнал не идут; журнал только дополняется, ни одно задание его не чистит (решение 14).

### 8.2. Подписи (`knowledge/audit_labels.py`)

Функция точки `audit_labels() -> dict` с ключами `"actions"`, `"fields"`, `"object_types"`, `"values"` (факт: `servicedesk/audit_labels.py`); ядро сливает словари, поздние побеждают, поэтому общие ключи `number` и `name` получают **те же подписи, что у сервис-деска** (иначе подпись у записей сервис-деска изменилась бы).

| Что | Содержание | Тесты |
|---|---|---|
| `actions` | двенадцать кодов раздела 8.1: «Статья создана», «Статья опубликована», «Статья перенесена в корзину», «Статья возвращена из корзины», «Статья удалена навсегда», «Версия статьи удалена», «Чужой комментарий удалён», «Рубрика создана», «Рубрика переименована», «Рубрика перенесена», «Рубрика удалена», «Срок корзины изменён» | T-5124 test_audit_labels_cover_all_actions_object_types_and_fields |
| `fields` | `number` — «номер», `name` — «название» (как у сервис-деска), `title` — «заголовок», `version` — «номер версии», `path` — «путь», `days` — «срок, дней», `by_term` — «по сроку»; каждый ключ из 8.1 имеет подпись (решение 20 задач: `test_audit_every_written_key_has_russian_label`) | T-5124, T-5129 |
| `object_types` | `knowledge.article` — «статья», `knowledge.rubric` — «рубрика» | T-5124 |
| `values` | пустой словарь (`{}`) — значений, требующих перевода, нет | T-5124 |

## 9. Поиск

### 9.1. `search.parse.parse(q) -> ParsedQuery`

Запись `ParsedQuery` — раздел 3.2 (поля `words`, `number`, `raw`, `hint`).

| Что | Требование | Тесты |
|---|---|---|
| Порядок разбора | (1) `q.strip()`; длина больше 200 → `hint="long"`; длина меньше 2 → `hint="short"`; (2) слова — `\w+` в нижнем регистре; (3) число: вся строка равна `#\d+` или `\d{2,}` и значение ≤ 2 147 483 647 (`_MAX_NUMBER` в `servicedesk/services/search.py`, факт) → `number`; (4) слова короче 2 знаков отбрасываются, остаются первые 8; (5) нет слов и нет `number` → `hint="short"`; (6) `raw = " & ".join(f"{w}:*" for w in words)` | T-5125 |
| Значения `hint` | `""` — разбор удался; `"short"`; `"long"`; при непустом `hint` остальные поля пусты: `words=[]`, `number=None`, `raw=""`; `hint="long"` побеждает остальное (запрос длиннее 200 знаков не разбирается на слова); ровно 200 знаков принимается | T-5125 test_query_over_200_chars_gives_long_hint, test_query_of_exactly_200_chars_is_accepted, test_long_query_hint_wins_over_word_parsing |
| Примеры | `""`, `"   "`, `"а"`, `"5"`, `"а б"` — `hint="short"`; `"#5"` — `number=5`, `words=[]`, `raw=""`, `hint=""` (слово «5» короче двух знаков отбрасывается, номер остаётся); `"15"` — `number=15`, `words=["15"]`, `raw="15:*"`; `"#42"` — `number=42`, `words=["42"]`; число выше 2 147 483 647 — `number=None`, слово остаётся, ошибки нет; девять слов — первые восемь; `"  сеть "` — после `strip` | T-5125 (вопрос B-18 о словах у числовых запросов) |
| `raw` | в словах только `\w+`, поэтому служебных знаков `tsquery` (`& \| ! ( ) : * < > '`) в `raw` нет, кроме добавленных `:*` и ` & `; знаки в запросе (кавычки, `%`, `_`, обратная косая, `;`, `--`) — обычный текст без ошибки | T-5125 test_raw_has_no_tsquery_operators_for_any_word, test_special_characters_* |
| Сервер | порог 2 знака сервер проверяет сам, независимо от браузера (`maxlength` поля — только для удобства) | T-5125 test_server_rejects_short_query_regardless_of_browser |

### 9.2. `search.services`

Модуль `apps/search/services.py` (вызывает только `extensions.registered("search_providers")`; ничего не знает о приложениях-поставщиках).

| Что | Требование | Тесты |
|---|---|---|
| Константы | `POPUP_LIMIT = 5`, `PAGE_LIMIT = 20` (имена — вопрос B-19) | T-5128 |
| `providers(user) -> list[SearchProvider]` | записи из всех зарегистрированных функций точки; без `available(user)` — отброшены; порядок по `order`, при равенстве — порядок регистрации; функция регистрации, которая упала, группу не показывает (остальные работают) | T-5126 test_assembler_runs_extra_registered_provider_without_changes, T-5127 test_provider_available_false_hides_group |
| `popup(user, parsed) -> list[Group]` | `Group = NamedTuple(key: str, title: str, rows: list[SearchRow])`; `search(user, parsed, POPUP_LIMIT, 0)`; пустые группы не возвращаются; при непустом `parsed.hint` — пустой список, поставщики не вызываются | T-5128 test_popup_shows_at_most_five_rows_per_group, test_popup_short_query_is_empty_without_hint |
| `page(user, parsed) -> list[Group]` | `search(user, parsed, PAGE_LIMIT, 0)`; пустые группы не возвращаются («Ничего не найдено» — когда список пуст); при непустом `hint` — пустой список без вызова поставщиков (подсказку пишет представление по `parsed.hint`) | T-5128 test_results_page_* |
| `more(user, parsed, key, offset) -> list[SearchRow]` | `search(user, parsed, PAGE_LIMIT, offset)` одной группы; неизвестный или недоступный ключ — пустой список без исключения; `offset` за концом — пустой список; отрицательный или нечисловой `offset` приводит представление (не меньше 0) | T-5128 test_more_endpoint_* |
| `count(user, parsed, key) -> Count \| None` | `Count = NamedTuple(number: int, capped: bool, text: str)`; `text` — `str(number)` или `f"{number}+"`; неизвестный, недоступный или упавший поставщик — `None` (пустой ответ) | T-5128 test_count_endpoint_* |
| Признак «есть ещё» | кнопка «Показать ещё» нужна группе, если основных строк больше `limit` (поставщик выбирает `limit + 1`; ровно `limit` — кнопки нет; раздел 17 п. 49) (у заявок строка по номеру считается сверх `limit`, поэтому на первой странице заявок бывает `limit + 1` строк); следующий `offset` = число основных строк, уже показанных (20, 40, …) | T-5128 test_results_page_twenty_rows_per_group_and_show_more_button (вопрос B-19) |
| Ошибка поставщика | исключение из `search` или `count` пишется в журнал **приложения** (не в журнал событий): логгер `apps.search.services` (имя модуля, `logging.getLogger(__name__)`), уровень `ERROR`, в записи только ключ группы и класс исключения (`log.error("search provider failed: key=%s error=%s", key, type(exc).__name__)`), без `exc_info`, без текста исключения и без запроса; группа не показывается, остальные работают; в журнал событий (`audit`) ничего не пишется (вопрос B-20: логгер плана не называет) | T-5128 test_provider_error_hides_group_and_others_work, test_provider_error_logs_only_key_and_exception_class |
| Запрос не сохраняется | строки запроса нет ни в одной таблице, ни в журнале событий, ни в журнале приложения (тест ищет метку-слово в записях `caplog` всех логгеров) | T-5128 test_query_not_stored_in_any_database_table, test_query_not_in_audit_log, test_query_not_in_application_log_marker_word |

### 9.3. Группы, порядок, лимиты, подсчёт

| Ключ (`SearchProvider.key`, вопрос A-1) | Название | `order` | `available(user)` | Подсчёт `count` | Тесты |
|---|---|---|---|---|---|
| `tickets` | «Заявки» | 10 | `access.menu_visible(user)` (4.4) | потолок 1000: читается `LIMIT 1001`; `>= 1001` → `(1000, True)`, иначе `(точное, False)` | T-5126 |
| `articles` | «Статьи» | 20 | всем вошедшим (читать статьи прав не требует): всегда истина | `(шаг 1 + шаг 2, capped)` — ниже | T-5126 |
| `staff` | «Сотрудники» | 30 | право `staff.view` (3.3) | `(точное, False)` | T-5127 |
| `units` | «Подразделения» | 40 | право `staff.view` (4.5) | `(точное, False)` | T-5127 |

Лимиты: всплывающее окно — 5 строк в группе, без подсчёта, внизу «Все результаты»; страница — 20 строк, число группы подгружается отдельным запросом `/search/count/?q=&group=<key>`; «Показать ещё» — следующие 20 (`/search/more/`). Пустые группы не показываются; порядок групп — по `order` (10, 20, 30, 40) и в окне, и на странице.

### 9.4. «Статьи»: два шага (`knowledge/services/search.py`)

| Что | Требование | Тесты |
|---|---|---|
| Функции | `search(user, parsed, limit, offset) -> list[SearchRow]`, `count(user, parsed) -> tuple[int, bool]`, `available(user) -> bool`, `head_count(parsed) -> int` (точный счёт шага 1 — отдельный дешёвый запрос по `search_head`; имя — вопрос B-21), `search_providers() -> list[SearchProvider]` (регистрация в `apps/knowledge/extensions.py`, ключ `articles`) | T-5126 |
| Отбор | только `state="published"` и векторы не пусты; черновики и корзина не выдаются никому, в том числе автору и управляющему (держит индекс, а не фильтр); `search_head`/`search_full` строятся по плану (заголовок вес A, теги B, текст `plain` вес C, `russian`); запрос — `to_tsquery('russian', raw)` параметром (`search_type="raw"`) | T-5126 test_articles_only_published_in_results, test_draft_and_trashed_articles_hidden_from_author_and_manager |
| Шаг 1 | `search_head @@ q` (все слова в заголовке и тегах); порядок: `ts_rank_cd(search_head, q)` вниз, затем `updated_at` вниз, затем `id` вниз (последнее — выбор контракта, чтобы порядок был определённым; вопрос B-22) | T-5126 test_article_step1_all_words_in_head_ranks_above_step2 |
| Шаг 2 | `search_full @@ q` и не `search_head @@ q`; не больше 300 кандидатов (`LIMIT 300` по `id`, потом порядок); порядок `updated_at` вниз (затем `id` вниз); статья с одним словом в заголовке и другим в тексте идёт в шаг 2 | T-5126 test_article_split_words_head_and_body_goes_to_step2, test_article_step2_ordered_by_recency, test_article_step2_capped_at_300_candidates |
| Склейка шагов и `offset` | выдача — шаг 1, затем шаг 2; граница `h = head_count(parsed)`; при `offset < h` строки шага 1 с `offset`, и если место осталось — шаг 2 с нуля; при `offset >= h` — шаг 2 со смещением `offset − h`; ни потери, ни повтора на границе | T-5126 test_article_offset_crosses_step_boundary_without_loss_or_repeat |
| Подсчёт | `h` — точное; шаг 2 считается запросом с `LIMIT 301`; `>= 301` → `(h + 300, True)` (страница пишет `f"{n}+"`), иначе `(h + число шага 2, False)` | T-5126 test_article_count_has_plus_when_step2_hits_cap, test_article_count_exact_when_step2_below_cap |
| Строка | `SearchRow(title=заголовок, subtitle=название рубрики, url="/kb/<id>/")`, `template=""`; рубрика читается тем же запросом (без запроса на строку) | T-5126 test_article_row_has_title_rubric_and_kb_url |
| Векторы | пересчитываются при публикации, сохранении опубликованной, возврате опубликованной из корзины, восстановлении версии у опубликованной; у черновика и статьи в корзине — `NULL`; текст — только первые 100 000 знаков `plain` | T-5126 test_article_vectors_updated_on_save_publish_trash_restore, test_article_body_indexed_only_first_100000_chars; T-5103, T-5107 |

## 10. Маршруты и поля форм

Адреса, методы и «кто» — раздел «Контракты» плана; здесь — поля форм, параметры, форма ответа и то, как тест отличает
запрос HTMX. Тесты ходят по путям (правило среза), поэтому имена маршрутов для `reverse` (10.2–10.6) нужны помощнику
`support_kb` и шаблонам, а не самим тестам; вся схема имён — вопрос C-1. Имена полей форм — выбор контракта (план называет
только `base_version`, `confirm_pdn`, `comment`, `v`, `name`, `offset`, `q`, `group`; остальные — вопрос C-9). Тексты
отказов — раздел 12; коды отказов — раздел 5 (часть b).

### 10.1. Общие правила маршрутов

| Что | Требование | Тесты |
|---|---|---|
| Запрос HTMX («НХ») | заголовок `HX-Request: true` (клиент теста: `client.post(path, data, headers={"HX-Request": "true"})`); в прежних контрактах это тоже «НХ» (CONTRACT-004, раздел 13); ответ на НХ — фрагмент без `<html>`, на обычный запрос — полная страница; GET-страницы `/kb/…` и `/search/` отдают полную страницу на любой запрос, кроме списков с параметром `offset` и адресов-фрагментов (`/search/popup/`, `/search/count/`, `/search/more/`, `/kb/pick/`, `/kb/tags/suggest/`, `/kb/preview/`): им нужен только фрагмент (вопрос C-19) | все тесты страниц |
| Вход | все адреса — `@login_required`: без входа GET и POST — 302 на `/login/` (с `next`); заявитель и участник копии не входят в портал (у них нет входа), поэтому для них адреса недоступны так же, как анониму; другой метод, чем в таблице, — 405 | T-5109 test_anonymous_redirected_to_login_on_all_kb_urls, test_requester_cannot_enter_portal_or_open_kb_urls; T-5115, T-5128 |
| CSRF | все POST — с `csrfmiddlewaretoken`; без него — 403 (общий порядок прежних срезов) | T-5109 |
| Отказ службы на POST | всегда **200** (и на НХ: HTMX не вставляет 4xx) с формой или фрагментом и сообщением; в базе ничего не меняется; введённое остаётся в форме; отказ у поля — `[data-error="<поле>"][data-code="<код>"]` рядом с полем, общий отказ — `[role=alert][data-code="<код>"]`. Это соглашение срезов 001-004 для форм (CONTRACT-004, раздел 13): запрет решения 16 задач (`role="status"`, `role="alert"`, `data-error`, `data-warning`) на сообщения об отказах форм не распространяется, а на остальные блоки среза распространяется (отказ-конфликт и «Статья удалена» тоже общие отказы с `role=alert`: вопрос C-18) | T-5103, T-5104, T-5110, T-5114, T-5116 |
| Не отказ формы | «Изменений нет» (`SaveResult.kind == "no_changes"`) и предупреждение ПДн (`pdn_warning`) — тоже 200 с формой, но без `role` и без `data-error`: маркеры `[data-kb-notice="no-changes"]` и `[data-kb-pdn]` (раздел 11) | T-5104, T-5118 |
| Успех | обычный POST — 302 на адрес из таблицы и сообщение `[role=status]` на странице назначения (флеш ядра `_flashes.html`); НХ-POST — 200 с пустым телом и заголовком `HX-Redirect: <тот же адрес>` либо 200 с фрагментом, названным в таблице; тексты флеша — 12.3 (вопрос C-2) | T-5103, T-5110, T-5112 |
| 403, 404, 410 | нет права на действие (`PermissionDenied`) — 403, в том числе на НХ (4xx без вставки — ожидаемо); статья, версия, вложение, связь, комментарий не существует или недоступна смотрящему (`Http404`) — 404, ответ тот же, что у несуществующего (FR-409; тест сравнивает код и отсутствие данных в теле); 410 — только **GET страниц статьи** (`/kb/<id>/`, `edit/`, `history/`, `versions/<N>/`, `compare/`) статьи в корзине у не-управляющего (решение 43 задач), страница «Статья удалена» без заголовка и текста; выдача файлов и картинок такой статьи — 404; несуществующий номер — всегда 404, не 410; **любой POST** над статьёй в корзине (правка, публикация, восстановление версии, комментарий, вложение, удаление вложения) — 200 с «Статья удалена» и текстом формы, от имени любого сотрудника (решение 43 задач); представление не обрывает POST над статьёй в корзине предпроверкой права: порядок отказов — шаги плана (корзина, затем право) | T-5107, T-5109, T-5104, T-5116 |
| Числа в пути и параметры | `<int:…>` в путях; `offset` — целое не меньше 0, по умолчанию 0 (отрицательное, не число и пустое значение дают 0; ошибки нет); шаг списков: рубрика, тег — 20, корзина — 50, главная «Новые и изменённые» — 10, поиск — 20 (раздел 9); `v` читается списком (`request.GET.getlist("v")`); `name` — одно значение, любые знаки в процентной записи; `group` — ключ группы поиска (9.3), неизвестный — пустой ответ, не ошибка | T-5111, T-5112, T-5105, T-5128 |
| Имена маршрутов | `app_name = "knowledge"` у `apps/knowledge/urls.py` и `app_name = "search"` у `apps/search/urls.py`; имена из 10.2–10.6; в именах и путях нет `regist`, `signup` (решение 20 задач), `hook`, `updates`, слова `bot` (проверки прежних срезов по `config/urls.py` и `apps/`: `test_accounts.py`, `test_notify_deploy.py`) и нет `delete`/`remove`/`destroy` под `staff/`; слово `delete` в путях `/kb/…/delete/` допустимо: их проверка касается только `staff/`; вопрос C-1 | T-5130, T-5129 |

### 10.2. Статья: главная, создание, чтение, правка, публикация, предпросмотр

| Путь (имя) | Метод; поля и параметры | Ответы | 403, 404, 410 | Тесты |
|---|---|---|---|---|
| `/kb/` (`knowledge:home`) | GET без параметров | 200 страница главной (зацепки 11.2) | — | T-5112 |
| `/kb/new/` (`knowledge:new`) | GET; POST `title` (текст, обязательное, до 200), `text` (многострочное, до 200 000, может быть пустым), `rubric` (номер рубрики, обязательное), `tags` (строка: теги через запятую, до 10, каждый до 40), `comment` (до 200, необязательное), `action` (значение кнопки: `save`; поле отсутствует — как `save`) | GET 200 форма; POST успех — статья `draft`, версия 1, 302 на `/kb/<id>/edit/` (решение Opus по C-2: после первого сохранения автор сразу вкладывает файлы), НХ — `HX-Redirect`; отказ — 200 форма с `[data-error]` у поля (`title`, `text`, `rubric`, `comment`, `tags`) и введённым | 403 без `knowledge.edit` и `knowledge.manage` (на GET и POST); 404 нет | T-5103 |
| `/kb/<id>/` (`knowledge:article`) | GET | 200 страница (11.3); показ публикует `object.viewed` (раздел 7.1); у статьи в корзине управляющему — страница с пометкой «в корзине» и кнопками «Вернуть», «Удалить навсегда» без комментариев, вложений и связанных заявок | 404 несуществующая и чужой черновик; 410 корзина — не-управляющему | T-5103, T-5107, T-5109 |
| `/kb/<id>/edit/` (`knowledge:edit`) | GET; POST `title`, `text`, `rubric`, `tags`, `comment` (как у `/kb/new/`), `base_version` (целое, скрытое, обязательное — номер версии, на которой открыта форма), `confirm_pdn` (скрытое, `1` — подтверждено; пусто — нет), `action` (`save` или `publish`: кнопка «Сохранить» или «Опубликовать»; пусто — `save`) | GET 200 форма; успех — 302 на `/kb/<id>/` (+флеш), НХ — `HX-Redirect`; «Изменений нет» — 200 форма + `[data-kb-notice="no-changes"]`; предупреждение ПДн — 200 форма + `[data-kb-pdn]`; конфликт — 200 форма + `[role=alert][data-code="stale_version"]`, скрытое `base_version` получает текущий номер, введённое остаётся; корзина — 200 + `[role=alert][data-code="article_gone"]` «Статья удалена» и введённое; отказ у поля — `[data-error]`; НХ-отказ и НХ-предупреждение — фрагмент `form[data-form="kb-article"]` (замена формы) | 403 нет права править (`can_change`; после проверки корзины); 404 нет, чужой черновик у не-управляющего; 410 GET корзины у не-управляющего; GET корзины у управляющего — 302 на `/kb/<id>/` (правит только «Вернуть»; вопрос C-4) | T-5103, T-5104, T-5118 |
| `/kb/<id>/publish/` (`knowledge:publish`) | POST `base_version`, `confirm_pdn`; GET — 405 | успех — 302 на `/kb/<id>/`, НХ `HX-Redirect`; предупреждение ПДн — 200 страница статьи (форма публикации с `[data-kb-pdn]`), НХ — тот же фрагмент; `already_published` — 200 `[role=alert][data-code="already_published"]`; конфликт и корзина — как у правки | 403 нет права править (`can_change`; после проверки корзины); 404; корзина — 200 «Статья удалена» | T-5103, T-5118 |
| `/kb/preview/` (`knowledge:preview`) | POST `text` (многострочное, до 200 000), `article` (номер статьи; пусто или нет — предпросмотр без вложений; имена полей — вопрос C-3); GET — 405 | 200 фрагмент `[data-kb-preview]` с `html` из `render.render`; замок `kb:preview:<user_id>` занят — 200 фрагмент `[data-kb-preview-busy]` «Предпросмотр уже готовится» (не 4xx); текст длиннее 200 000 — 200 фрагмент `[data-error="text"][data-code="text_too_long"]`; вложения берутся только у статьи, которую смотрящий видит; ничего не сохраняется, версий нет | 403 без права `can_edit` (в том числе у автора чужой статьи без права) | T-5102 |
| `/kb/from-ticket/<number>/` (`knowledge:from_ticket`) | POST без полей; GET — 405 | успех и «уже создан» — 302 на `/kb/<id>/edit/` (редактор открывается, план: «Затем открывается редактор»); НХ — 200 пустое тело и `HX-Redirect: /kb/<id>/edit/`; повтор — тот же адрес и флеш «Черновик по этой заявке уже создан»; отказ `not_closed_with_resolution` — 200 `[role=alert][data-code="not_closed_with_resolution"]` (вопрос C-17) | 403 нет `can_edit`; 404 заявки нет или не видна | T-5120 |

### 10.3. История, версии, корзина, срок корзины

| Путь (имя) | Метод; поля и параметры | Ответы | 403, 404, 410 | Тесты |
|---|---|---|---|---|
| `/kb/<id>/history/` (`knowledge:history`) | GET | 200 список версий по номеру вниз, форма сравнения (11.6) | 404; 410 корзина — не-управляющему | T-5105 |
| `/kb/<id>/compare/` (`knowledge:compare`) | GET `v` (повторяется, ровно две номера версий: `?v=N&v=M`) | 200 страница сравнения; не две отметки (ноль, одна, три и более), не числа или повтор одного номера — 200 страница сравнения (`data-kb-page="compare"`) с `[data-kb-hint="pick-two"]` «Отметьте две версии» и без разницы; одной из версий нет — 200 с `[data-kb-hint="deleted"]` «Версия удалена»; старший номер — «стало» при любом порядке `v` | 404 нет статьи или чужой черновик; 410 корзина — не-управляющему | T-5105 |
| `/kb/<id>/versions/<N>/` (`knowledge:version`) | GET | 200 просмотр версии: готовый `html` версии (рендер не вызывается), заголовок, рубрика, теги; кнопки по правилам 11.6 | 404 версии нет (удалена) или статьи нет; 410 корзина — не-управляющему | T-5106 |
| `/kb/<id>/versions/<N>/restore/` (`knowledge:version_restore`) | POST `confirm_pdn` (необязательно); GET — 405 | успех — 302 на `/kb/<id>/` + флеш; «Изменений нет» — 200 `[data-kb-notice="no-changes"]`; предупреждение ПДн — 200 `[data-kb-pdn]` с кнопками; корзина — 200 «Статья удалена» | 403 нет `can_change`; 404 версии нет | T-5106, T-5118 |
| `/kb/<id>/versions/<N>/delete/` (`knowledge:version_delete`) | POST без полей; GET — 405 | успех — 302 на `/kb/<id>/history/` + флеш; текущая версия — 200 `[role=alert][data-code="current_version"]` | 403 без `knowledge.manage`; 404 | T-5106 |
| `/kb/<id>/trash/`, `/kb/<id>/restore/`, `/kb/<id>/purge/` (`knowledge:article_trash`, `knowledge:article_restore`, `knowledge:article_purge`) | POST без полей; подтверждение — на стороне браузера: `hx-confirm` на форме (вопрос C-5), сервер полем не требует | в корзину и «вернуть» — 302 на `/kb/<id>/` + флеш; «удалить навсегда» — 302 на `/kb/trash/` + флеш; «вернуть» не из корзины — 200 `[role=alert][data-code="not_in_trash"]`; «в корзину» из корзины — 200 «Статья удалена» | 403 без `knowledge.manage`; 404 нет статьи | T-5107, T-5108 |
| `/kb/trash/` (`knowledge:trash_list`) | GET `offset` | 200 страница: по 50 строк по `deleted_at` вниз, «Показать ещё» (11.7); НХ с `offset` — фрагмент строк | 403 без `knowledge.manage` | T-5107 |
| `/kb/settings/` (`knowledge:settings`) | GET; POST `trash_days` (целое, обязательное) | GET 200 форма с текущим значением; успех — 302 на `/kb/settings/` + флеш; отказ — 200 `[data-error="trash_days"][data-code="out_of_range"]` и введённое значение | 403 без `knowledge.manage` (на GET и POST) | T-5108 |

### 10.4. Рубрики, теги, подписка

| Путь (имя) | Метод; поля и параметры | Ответы | 403, 404, 410 | Тесты |
|---|---|---|---|---|
| `/kb/rubrics/` (`knowledge:rubrics`) | GET | 200 дерево с действиями (11.7) | 403 без `knowledge.manage` | T-5110 |
| `/kb/rubrics/new/` (`knowledge:rubric_new`) | POST `name` (до 100, обязательное), `parent` (номер рубрики; пусто — корневая) | успех — 302 на `/kb/rubrics/` + флеш; НХ — `HX-Redirect`; отказ — 200 `/kb/rubrics/` (НХ — фрагмент формы) с `[data-error="name"]` или `[data-error="parent"]` + `data-code` | 403 без `knowledge.manage`; GET — 405 | T-5110 |
| `/kb/rubrics/<id>/rename/` (`knowledge:rubric_rename`) | POST `name` | как выше | 403; 404 рубрики нет | T-5110, T-5111 |
| `/kb/rubrics/<id>/move/` (`knowledge:rubric_move`) | POST `parent` (номер или пусто — в корень) | как выше; отказы `parent_self`, `parent_descendant`, `depth_exceeded`, `default_immovable` — у `[data-error="parent"]`, `name_duplicate` — у `[data-error="name"]` | 403; 404 | T-5111 |
| `/kb/rubrics/<id>/delete/` (`knowledge:rubric_delete`) | POST без полей | успех — 302 на `/kb/rubrics/` + флеш; отказ (`not_empty`, `default_undeletable`) — 200 с `[role=alert][data-code]` в строке этой рубрики | 403; 404 | T-5111 |
| `/kb/rubrics/<id>/` (`knowledge:rubric_page`) | GET `offset` | 200 страница: опубликованные статьи рубрики и подрубрик по `updated_at` вниз, по 20, кнопка подписки, «Показать ещё»; НХ с `offset` — фрагмент строк | 404 рубрики нет | T-5111 |
| `/kb/rubrics/<id>/subscribe/` (`knowledge:rubric_subscribe`) | POST без полей (переключатель; чужого пользователя нет) | обычный — 302 на `/kb/rubrics/<id>/`; НХ — 200 фрагмент кнопки `button[data-action="kb-subscribe"]` с новым `data-subscribed`; журнал не пишется | 404 рубрики нет; 403 нет (право не нужно) | T-5111, T-5122 |
| `/kb/tags/` (`knowledge:tag_page`) | GET `name` (обязательное, любые знаки), `offset` | 200 страница: опубликованные статьи тега по `updated_at` вниз, по 20, «Показать ещё» | 404 `name` пусто или не задано; 404 у тега нет опубликованных статей | T-5112 |
| `/kb/tags/suggest/` (`knowledge:tag_suggest`) | GET `q` (начало тега; пусто — пустой список) | 200 фрагмент `ul[data-kb-tag-suggest]`: до 10 `li[data-tag="<имя>"]`, только теги опубликованных статей | 403 без `can_edit` | T-5112 |

### 10.5. Файлы, комментарии, привязка к заявкам, подбор статьи

| Путь (имя) | Метод; поля и параметры | Ответы | 403, 404, 410 | Тесты |
|---|---|---|---|---|
| `/kb/<id>/files/` (`knowledge:file_attach`) | POST multipart: `file` (один файл за запрос; поле без `multiple`, вопрос C-8); GET — 405; предел тела 55m — `location` nginx (1.2) | НХ — 200 фрагмент `[data-kb-files]` (список с новой строкой); отказ (`too_big`, `executable`, `encrypted`, `limit_20`, `image_too_large`, `write_failed`) — 200 тот же фрагмент с `[role=alert][data-code="<код>"]` над списком, список прежний; обычный — 302 на `/kb/<id>/edit/` (отказ — 200 страница правки); корзина — 200 «Статья удалена» | 403 нет `can_change`; 404 статьи нет или чужой черновик | T-5114 |
| `/kb/<id>/files/<N>/` (`knowledge:file_download`) | GET | файл `clean` — 200 без тела, `X-Accel-Redirect`, `attachment; filename*=UTF-8''…`, `nosniff`, `no-store` (3.5); `pending`, `quarantine`, удалённый и чужой — 404 (тот же ответ, что у несуществующего) | 404 статьи нет, чужой черновик, корзина у не-управляющего | T-5115 |
| `/kb/<id>/files/<N>/delete/` (`knowledge:file_delete`) | POST без полей | НХ — 200 фрагмент `[data-kb-files]`; обычный — 302 на `/kb/<id>/edit/`; корзина — 200 «Статья удалена» | 403 нет `can_change`; 404 файла нет | T-5114 |
| `/kb/<id>/images/<N>/` (`knowledge:image`) | GET | `clean` и картинка — 200 без тела, `X-Accel-Redirect`, тип по `image_format`, без `Content-Disposition`; `pending`, нет строки, карантин, не картинка — 200 `image/svg+xml` — файл-заглушка из статики и заголовок `X-KB-Placeholder: checking`, `removed` или `unavailable` (вопрос C-7) | 404 статьи нет, чужой черновик, корзина у не-управляющего | T-5115 |
| `/kb/<id>/comments/` (`knowledge:comment_add`) | POST `text` (до 4000 после обрезки пробелов, обязательное) | НХ — 200 фрагмент: один `li[data-comment-id]` нового комментария (клиент добавляет его в конец списка, `hx-swap="beforeend"`) и `form[data-form="kb-comment"]` с `id="kb-comment-form"` и очищенным полем (`hx-swap-oob="true"`; и при отказе — с введённым текстом); отказ — 200 фрагмент: форма с введённым и `[data-error="text"][data-code="empty"` или `"too_long"]`; обычный — 302 на `/kb/<id>/#comments`; корзина — 200 «Статья удалена»; событие `knowledge.comment_added` после фиксации | 404 черновик (комментариев у черновика нет), статьи нет | T-5116 |
| `/kb/comments/<id>/delete/` (`knowledge:comment_delete`) | POST без полей | НХ — 200 пустое тело (клиент убирает строку, `hx-swap="outerHTML"`); обычный — 302 на `/kb/<статья>/#comments`; чужой комментарий удаляет только управляющий | 403 чужой комментарий, не управляющий (решение 35 задач); 404 комментария нет | T-5116 |
| `/kb/pick/` (`knowledge:pick`) | GET `q` (до 200; короче 2 знаков — пустой список), `ticket` (номер заявки, необязательное: есть — строки несут кнопку привязки, нет — данные для вставки ссылки; вопрос C-6) | 200 фрагмент `ul[data-kb-pick-results]`: до 10 `li[data-article-id]` опубликованных статей (по заголовкам, тем же поиском, что у группы «Статьи»), у каждой `data-title` и `data-url` (полный адрес `request.build_absolute_uri("/kb/<id>/")`); черновики, корзина не выдаются; запрос не сохраняется | — (любой вошедший, права не нужно) | T-5119, T-5120 |
| `/kb/links/` (`knowledge:link_add`) | POST `article` (номер), `ticket` (номер заявки) | НХ — 200 фрагмент раздела «Статьи» (`div[data-card-part="kb-articles"]`); обычный — 302 на `/tickets/<ticket>/`; повтор той же связи — тот же ответ без ошибки | 403 нет `can_edit`; 404 статья не опубликована или нет, заявки нет или не видна | T-5119 |
| `/kb/links/<id>/delete/` (`knowledge:link_delete`) | POST без полей | то же | 403 нет `can_edit`; 404 связи нет, заявка не видна | T-5119 |

### 10.6. Поиск

| Путь (имя) | Метод; поля и параметры | Ответы | 403, 404, 410 | Тесты |
|---|---|---|---|---|
| `/search/popup/` (`search:popup`) | GET `q` | 200 фрагмент `[data-search-popup]` на любой запрос: по 5 строк в группе, без чисел, внизу `a[data-action="search-all"]` «Все результаты»; запрос с `hint` (короче 2 знаков и длиннее 200) — 200 пустой фрагмент без подсказки (решение 45 задач); пустые группы нет | — | T-5128 |
| `/search/` (`search:results`) | GET `q` | 200 страница на любой запрос: по 20 строк в группе; `hint` — подсказка и ни одного вызова поставщика; нет строк — «Ничего не найдено»; число группы подгружается отдельно | — | T-5128 |
| `/search/count/` (`search:count`) | GET `q`, `group` | 200 фрагмент `span[data-search-count-value][data-count="<число>"][data-capped="true"` или `"false"]` с текстом `N` или `N+`; неизвестная, недоступная или упавшая группа — 200 с пустым телом | — | T-5128 |
| `/search/more/` (`search:more`) | GET `q`, `group`, `offset` (по 20) | 200 фрагмент: строки группы и, если есть ещё, новая `button[data-action="more"]` с `data-next-offset`; `offset` за концом, неизвестная группа — 200 пустой | — | T-5128 |

### 10.7. Действие × роль (сводка для тестов прав)

Роли: «читатель» — сотрудник без `knowledge.edit` и `knowledge.manage`; «редактор» — с `knowledge.edit`; «менеджер» — с
`knowledge.manage`; «аноним» — без входа (302 на `/login/`). «Автор без права» — автор черновика, потерявший `knowledge.edit`:
для него черновик недоступен так же, как читателю (404; видит и правит менеджер). Код — ответ на обычный запрос; НХ — тот же
код (отказ формы — 200).

| Действие | Аноним | Читатель | Редактор | Менеджер | Тесты |
|---|---|---|---|---|---|
| GET `/kb/`, `/kb/rubrics/<id>/`, `/kb/tags/?name=`, `/kb/pick/`, `/search/…` | 302 | 200 | 200 | 200 | T-5109 |
| GET и POST `/kb/new/` | 302 | 403 | 200 или 302 | 200 или 302 | T-5109 |
| GET опубликованной `/kb/<id>/`, `history/`, `compare/`, `versions/<N>/` | 302 | 200 | 200 | 200 | T-5109 |
| GET чужого черновика (любой адрес страницы) | 302 | 404 | 404 | 200 | T-5109 |
| GET своего черновика | 302 | 404 (автор без права) | 200 | 200 | T-5109 |
| GET статьи в корзине (любой адрес страницы) | 302 | 410 | 410 | 200 (`edit/` — 302 на `/kb/<id>/`) | T-5107, T-5109 |
| GET несуществующей статьи | 302 | 404 | 404 | 404 | T-5107 |
| GET и POST `edit/`, POST `publish/`, `versions/<N>/restore/`, `files/`, `files/<N>/delete/` опубликованной | 302 | 403 | 200 или 302 | 200 или 302 | T-5109 |
| то же, чужой черновик | 302 | 404 | 404 | 200 или 302 | T-5109 |
| то же POST, статья в корзине | 302 | 200 «Статья удалена» | 200 «Статья удалена» | 200 «Статья удалена» | T-5107, T-5109 |
| POST `/kb/preview/` | 302 | 403 | 200 | 200 | T-5102 |
| GET `/kb/tags/suggest/` | 302 | 403 | 200 | 200 | T-5112 |
| POST `trash/`, `restore/`, `purge/`, `versions/<N>/delete/`; GET `/kb/trash/`, `/kb/settings/`, `/kb/rubrics/`; POST рубрик и срока | 302 | 403 (над статьёй в корзине — 200 «Статья удалена», раздел 17 п. 5, 10) | 403 (то же) | 200 или 302 | T-5107, T-5109 |
| POST `rubrics/<id>/subscribe/` | 302 | 200 или 302 | 200 или 302 | 200 или 302 | T-5111 |
| GET `files/<N>/`, `images/<N>/` опубликованной (файл `clean`) | 302 | 200 | 200 | 200 | T-5115 |
| то же, чужой черновик или корзина (не менеджеру) | 302 | 404 | 404 | 200 | T-5115 |
| POST `comments/` опубликованной | 302 | 200 или 302 | 200 или 302 | 200 или 302 | T-5116 |
| POST `comments/` черновика | 302 | 404 | 404 | 404 (комментариев у черновика нет) | T-5116 |
| POST `comments/<id>/delete/` своего | 302 | 200 или 302 | 200 или 302 | 200 или 302 | T-5116 |
| POST `comments/<id>/delete/` чужого | 302 | 403 | 403 | 200 или 302 | T-5116 |
| POST `links/`, `links/<id>/delete/`, `from-ticket/<N>/` | 302 | 403 | 200 или 302 (404, если заявка не видна) | то же | T-5119, T-5120 |

## 11. Зацепки `data-*` для приёмки

Правила: только `data-*`, `id` и классы, которых нет у прежних блоков; без `role="status"`, `role="alert"`, `data-error`,
`data-warning` вне сообщений об отказах форм (решение 16 задач; 10.1), без `ws-connect`, `hx-ext`, `style=`, `on…=`.
Названия полей и кнопок — выбор контракта (вопрос C-9), кроме `data-md=…`, `kb-diff-add/del`, `kb-noimg`, `kb-al-*`,
`kb-scroll`, `input[name=q]`, `data-card-part`/`data-part-kind`, названных планом или частями a и b. Подписи кнопок — раздел 12.

### 11.1. Общие

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `[data-kb-page="<имя>"]` | корень содержимого страницы: `home`, `article`, `new`, `edit`, `history`, `compare`, `version`, `trash`, `settings`, `rubrics`, `rubric`, `tag`, `gone` (страница 410) | T-5140…T-5151 |
| `[data-action="more"][data-next-offset="<N>"]` | кнопка «Показать ещё»: `button` с `hx-get` на тот же адрес с `offset=N`, `hx-target="this"`, `hx-swap="outerHTML"`; ответ — строки и (если есть ещё) новая кнопка; нет следующей порции — кнопки нет | T-5111, T-5112, T-5107, T-5128 |
| `[data-empty-state="<имя>"]` | пустые состояния (как в CONTRACT-004): `kb` — пустая база, `search` — «Ничего не найдено», `kb-trash` — корзина пуста, `kb-comments`, `kb-history` не нужны (всегда есть версия) | T-5112, T-5128 |
| `time[data-at]` | время (Москва, раздел 1.2), `datetime` — ISO, текст — «ДД.ММ.ГГГГ ЧЧ:ММ» (как в прежних срезах) | T-5129, T-5105 |
| Пометка «уволен» | `{% person_name %}` (3.6): `span[data-dismissed="true"]` «ФИО (уволен)» в истории, комментариях, авторе статьи, корзине | T-5105, T-5116 |
| Отказ у поля, общий отказ | `[data-error="<поле>"][data-code="<код>"]`, `[role=alert][data-code="<код>"]` (10.1) | все тесты отказов |

### 11.2. Главная, рубрика, тег

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `[data-kb-tree]` | дерево рубрик главной: `li[data-rubric-id="<id>"][data-depth="<1-3>"]`; в строке `a[data-field="name"]` (адрес `/kb/rubrics/<id>/`) и `[data-field="count"]` — число опубликованных статей рубрики вместе с подрубриками словом: «1 статья», «2 статьи», «5 статей» (12.3); корзины и черновиков в числе нет | T-5112 test_home_tree_counts_published_with_subrubrics_in_three_russian_forms |
| `[data-kb-new-and-changed]` | «Новые и изменённые»: до 10 `li[data-article-id]` по `updated_at` вниз, в строке `a[data-field="title"]`, `[data-field="rubric"]`, `time[data-at]` | T-5112 |
| `[data-kb-my-drafts]`, `[data-kb-all-drafts]` | «Мои черновики» (у `can_edit`: только свои) и «Черновики» (у менеджера: все); строки `li[data-article-id]`; читателю блоков нет | T-5112 |
| `a[data-action="kb-new-article"]`, `a[data-action="kb-trash-link"]` | «Новая статья» (`/kb/new/`; видна при `can_edit`) и «Корзина» (`/kb/trash/`; видна менеджеру) | T-5112, T-5109 |
| `[data-empty-state="kb"]` | пустая база: пояснение и, по праву, ссылка «Новая статья» | T-5112 |
| `[data-kb-list]` | список статей страницы рубрики и тега: `li[data-article-id]`; кнопка «Показать ещё» (11.1) — последний элемент после строк; на странице рубрики — `button[data-action="kb-subscribe"][data-subscribed="true"` или `"false"]` с текстом «Подписаться»/«Отписаться»; облака тегов нет | T-5111, T-5112 |

### 11.3. Страница статьи и редактор

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `article[data-article-id="<id>"][data-article-state="draft"` или `"published"` или `"trash"]` | корень страницы статьи; внутри `h1[data-field="title"]`, `[data-field="body"]` (готовый `html`), `[data-field="rubric"]` (путь рубрик со ссылками), `a[data-tag="<имя>"]` (адрес `/kb/tags/?name=<имя в процентной записи>`), `[data-field="author"]`, `[data-field="updated"]` («изменено» с `time[data-at]` и автором правки) | T-5103, T-5112 |
| Кнопки статьи | `a[data-action="kb-edit"]` (`can_change`), `form[data-form="kb-publish"]` с `button[data-action="kb-publish"]` (черновик, `can_publish`), `a[data-action="kb-history"]`, `form[data-form="kb-trash"]` (менеджер), у статьи в корзине — `form[data-form="kb-restore"]`, `form[data-form="kb-purge"]` и `[data-kb-trash-mark]` «В корзине»; кнопки «Вернуть в черновик» нет ни у кого | T-5103, T-5107 |
| `[data-kb-page="gone"]` | страница 410: текст «Статья удалена», без заголовка и текста статьи | T-5107 |
| `form[data-form="kb-article"]` | форма новой статьи и правки (на странице новой статьи кнопки `kb-publish` нет — публикуют после первого сохранения): поля `input[name=title]`, `textarea[name=text]`, `select[name=rubric]` (дерево службы `rubrics`; в подписи отступ по глубине), `input[name=tags]`, `input[name=comment]`, скрытые `input[name=base_version]`, `input[name=confirm_pdn]`; кнопки `button[data-action="kb-save"][name="action"][value="save"]` («Сохранить» / на новой статье «Сохранить черновик») и `button[data-action="kb-publish"][name="action"][value="publish"]` («Опубликовать»); у `<form>` — `hx-post` на тот же адрес, `hx-target="this"`, `hx-swap="outerHTML"` | T-5103, T-5104, T-5140 |
| `[data-kb-editor]` и панель | `[data-kb-toolbar]` с кнопками `button[data-md="bold"]`, `italic`, `heading`, `list`, `olist`, `code`, `link`, `table`, `image` (вставка разметки в позицию курсора `textarea[name=text]`, выделенный текст оборачивается: `bold` — `**текст**`, `italic` — `*текст*`, `heading` — `# ` в начале строки, `list` — `- `, `olist` — `1. `, `code` — `` `текст` ``, `link` — `[текст](https://)`, `table` — шаблон из двух столбцов `\| a \| b \|` с разделителем, `image` — `![](att:N)` после выбора вложения; точные строки — решение Opus, тест сверяет их подстрокой; `kb-editor.js`); вкладки `button[data-kb-tab="text"]` «Текст» и `button[data-kb-tab="preview"]` «Предпросмотр» (у второй `hx-post="/kb/preview/"`, `hx-sync="this:replace"`, `hx-target="[data-kb-panel=preview]"`, значения — `text` и `article`); панели `[data-kb-panel="text"]` и `[data-kb-panel="preview"]` (скрытая неактивная имеет `hidden`); возврат на «Текст» не трогает введённое | T-5140 |
| Неактивные кнопки до первого сохранения | у новой статьи: `button[data-action="kb-attach"][disabled]` «Вложить» и `button[data-md="image"][disabled]` «Картинка» с `title="Сохраните черновик"` и видимой подсказкой `[data-kb-hint="save-draft"]` «Сохраните черновик»; после первого сохранения (форма правки существующей статьи) обе активны, подсказки нет; что делает «Картинка» панели — вопрос C-16 | T-5103, T-5114, T-5140 |
| `[data-kb-notice="no-changes"]` | «Изменений нет» над формой (без `role`) | T-5104 |
| Конфликт правки | `[role=alert][data-code="stale_version"]`: текст «Статью уже изменил Имя Фамилия в ЧЧ:ММ» и `a[data-action="kb-compare-link"]` (адрес `/kb/<id>/compare/?v=<base>&v=<текущая>`); скрытое `base_version` в той же форме равно текущему номеру; введённый текст остаётся | T-5104, T-5142 |
| Предупреждение ПДн | `[data-kb-pdn]`: список `li[data-pdn-item]` (найденные подстроки, до 20) и две кнопки: `button[data-action="kb-pdn-back"]` «Вернуться к правке» (возвращает форму без отправки) и `button[type=submit][data-action="kb-pdn-confirm"][name="confirm_pdn"][value="1"]` («Опубликовать всё равно», у опубликованной — «Сохранить всё равно»); скрытое `input[name=action]` хранит значение нажатой кнопки; текст формы остаётся; без `role` и `data-warning` | T-5118, T-5143 |
| Подсказка тегов | поле `input[name=tags]` с подсказкой `ul[data-kb-tag-suggest]` (10.4); запрос `q` — последний сегмент после запятой — шлёт `kb-editor.js` (имя поля `tags`, а не `q`) | T-5112, T-5146 |
| `[data-kb-preview]`, `[data-kb-preview-busy]` | содержимое панели предпросмотра: тот же вид, что у опубликованной статьи (`.kb-body`), или «Предпросмотр уже готовится» | T-5102, T-5140 |
| Рендер | таблица и блок кода в `div.kb-scroll`; выравнивание `kb-al-*`; заглушка `span.kb-noimg` с текстом `[вложение недоступно: имя]`; у `img` — `loading="lazy"` | T-5102, T-5140 |

### 11.4. Вложения и картинки

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `[data-kb-files]` | список вложений под формой правки и на странице статьи: `li[data-file-id="<N>"][data-file-state="pending"` или `"clean"` или `"quarantine"`][data-image="png"` или `"jpeg"` или `"gif"` или `"webp"` или `""`]; в строке `[data-field="name"]`, `[data-field="size"]` (`filesizeformat`), `[data-field="state"]` — «проверяется» у `pending`, «в карантине» у `quarantine`, у `clean` пусто | T-5114, T-5115 |
| Ссылка и кнопки строки | у `clean` — `a[data-action="kb-download"]` (`/kb/<id>/files/<N>/`); у `pending` и `quarantine` ссылки нет; в форме правки: `button[data-action="kb-insert-link"]` «Вставить ссылку» (у всех, кроме `quarantine`; вставляет `[имя](att:N)`), `button[data-action="kb-insert-image"]` «Картинка» (только при `data-image` не пустом; вставляет `![имя](att:N)`), `button[data-action="kb-file-delete"]` «Удалить»; разметка вставки — в `data-insert="<текст>"` кнопки | T-5114, T-5115 |
| Загрузка | `form[data-form="kb-attach"]` рядом с формой статьи (отдельная форма: вложенных нет), `input[type=file][name=file]`, `hx-post="/kb/<id>/files/"`, `hx-encoding="multipart/form-data"`, `hx-target="[data-kb-files]"`, `hx-swap="outerHTML"`; отказ — `[role=alert][data-code]` внутри заменяемого `[data-kb-files]`, над списком | T-5114, T-5144 |
| Заглушки картинок | в тексте картинка всегда `img[src="/kb/<id>/images/<N>/"]`; состояние различает ответ адреса (10.5): заголовок `X-KB-Placeholder` и текст SVG («проверяется», «вложение удалено», «недоступно») | T-5115, T-5144 |

### 11.5. Комментарии

| Зацепка | Где и значение | Тесты |
|---|---|---|
| `section#comments[data-kb-comments]` | блок под опубликованной статьёй (у черновика и статьи в корзине блока нет); `ul[data-kb-comment-list]`, `li[data-comment-id="<id>"]` по порядку «старые первыми» | T-5116 |
| Строка | `[data-field="author"]` (`{% person_name %}`), `img[data-field="photo"]`, `time[data-at]`, `[data-field="text"]` (экранированный текст, `linebreaksbr`; ссылки — текстом), `button[data-action="kb-comment-delete"]` («Удалить»; у автора и менеджера; у остальных нет) | T-5116, T-5145 |
| Форма | `form[data-form="kb-comment"]`: `textarea[name=text]`, `button[data-action="kb-comment-add"]` («Отправить»), `hx-post="/kb/<id>/comments/"`, `hx-target="[data-kb-comment-list]"`, `hx-swap="beforeend"`; вложений и упоминаний в форме нет | T-5116 |

### 11.6. История, версии, сравнение

| Зацепка | Где и значение | Тесты |
|---|---|---|
| История | `form[data-form="kb-compare"]` (`method="get"`, `action="/kb/<id>/compare/"`), строки `tr[data-version="<N>"]` по номеру вниз: `input[type=checkbox][name="v"][value="<N>"]`, `[data-field="author"]`, `time[data-at]`, `[data-field="comment"]`, `a[data-action="kb-version-open"]`; кнопка `button[data-action="kb-compare"]` «Сравнить выбранные версии» | T-5105 |
| Сравнение | `[data-kb-diff]`: строки полей `[data-kb-diff-field="title"` или `"rubric"` или `"tags"]` с `[data-side="before"]` и `[data-side="after"]` (только изменённые); текст — `div.kb-diff-del` («− », `<del>`) и `div.kb-diff-add` («+ »); свёртка — `details[data-kb-fold]` с `summary` «Показать N строк» (скрытые строки уже в разметке); `[data-kb-diff-more]` «Ещё N изменений не показано»; подсказки `[data-kb-hint="pick-two"]`, `[data-kb-hint="deleted"]` (10.3); текст строк экранирован | T-5105, T-5142 |
| Просмотр версии | `[data-kb-page="version"]`: `[data-field="title"]`, `[data-field="body"]`, `[data-field="rubric"]`, `a[data-tag]`; `form[data-form="kb-version-restore"]` (кнопка `button[data-action="kb-restore-version"]` «Восстановить эту версию»: `can_change`, статья не в корзине, версия не текущая) и `form[data-form="kb-version-delete"]` (`button[data-action="kb-delete-version"]` «Удалить версию»: менеджер, версия не текущая) | T-5106 |

### 11.7. Корзина, срок, рубрики

| Зацепка | Где и значение | Тесты |
|---|---|---|
| Корзина | `[data-kb-trash-list]`: `tr[data-article-id]` по `deleted_at` вниз: `a[data-field="title"]`, `[data-field="rubric"]`, `time[data-at]` (дата удаления), `[data-field="deleted-by"]` (`{% person_name %}`); кнопка «Показать ещё» (11.1); `[data-empty-state="kb-trash"]` | T-5107, T-5147 |
| Срок | `form[data-form="kb-settings"]`: `input[name=trash_days][type=number]` и `button[data-action="kb-settings-save"]`; отказ — `[data-error="trash_days"][data-code="out_of_range"]` | T-5108, T-5147 |
| Управление рубриками | `[data-kb-rubrics]`: `li[data-rubric-id][data-depth]` с `[data-field="name"]`, `form[data-form="kb-rubric-rename"]` (`input[name=name]`), `form[data-form="kb-rubric-move"]` (`select[name=parent]`, первый пункт — «В корень»), `form[data-form="kb-rubric-delete"]` (с `hx-confirm`); сверху `form[data-form="kb-rubric-new"]` (`input[name=name]`, `select[name=parent]`); у «Общее» кнопка «Удалить» тоже есть, отказ даёт служба (`default_undeletable`) | T-5110, T-5111, T-5146 |
| Подтверждение | формы «в корзину», «удалить навсегда», «удалить версию», «удалить рубрику» несут `hx-confirm="<текст>"` (12.3, вопрос C-5); тест читает атрибут, а Playwright принимает окно `dialog` | T-5107, T-5147 |

### 11.8. Карточка заявки

| Зацепка | Где и значение | Тесты |
|---|---|---|
| Оболочка части (подтверждает A-16) | `<div data-card-part="<ключ>" data-part-kind="<вид>">`: `kb-articles` (`section`, `order=10`; правило вывода: часть возвращает `None` (оболочки нет), когда у смотрящего нет `can_edit` и нет ни одной видимой связи; при `can_edit` раздел с формой привязки выводится всегда, в том числе без связей), `kb-from-ticket` (`closed_action`, `order=10`), `kb-link-tool` (`comment_tool`, `order=10`); пустая часть — без оболочки; разделу «Статьи» **нельзя** давать `data-section="attachments"` (прежний тест ждёт ровно один такой раздел) — у него `section.card-section[data-section="kb-articles"]` внутри оболочки | T-5119, T-5120, T-5143 |
| Раздел «Статьи» | `li[data-link-id="<id>"][data-article-id="<id>"]` с `a[data-field="title"]`, `[data-field="state"]` («черновик» у черновика, виден автору и менеджеру), `[data-field="linked-by"]` (кто привязал) и `time[data-at]`; `button[data-action="kb-unlink"]` «Отвязать» (`hx-post` на `/kb/links/<id>/delete/`, `hx-target="closest [data-card-part]"`, `hx-swap="outerHTML"`) — при `can_edit` | T-5119, T-5143 |
| Привязка | при `can_edit`: `form[data-form="kb-link"]` с полем поиска `input[type=search][name="pick"]` (не `q`: в шапке уже есть `input[name=q]`, второе такое поле на странице нарушило бы строгий режим Playwright; запрос `q` к `/kb/pick/?ticket=<номер>` шлёт `kb-link.js`) и список `ul[data-kb-pick-results]`; в строке результата `button[data-action="kb-link-add"][data-article-id]` (`hx-post="/kb/links/"`, значения `article`, `ticket`) «Привязать статью» | T-5119, T-5143 |
| «Статья из решения» | `form[data-form="kb-from-ticket"]` с `button[data-action="kb-from-ticket"]` «Статья из решения» (`hx-post="/kb/from-ticket/<номер>/"`); рядом с кнопкой `data-action="ticket-reopen"`; только при `closed` и `has_resolution` и `can_edit` | T-5120, T-5143 |
| «Ссылка на статью» | под полем «Внутренний комментарий»: `button[data-action="kb-link-tool"]` «Ссылка на статью», поле `input[type=search][name="pick"]`, `ul[data-kb-pick-results]` (без `ticket`); у строки `data-title` и `data-url`; выбор вставляет в поле комментария `Заголовок: <полный адрес>` | T-5120, T-5143 |
| Связанные заявки на странице статьи | `[data-kb-tickets]`: `li[data-ticket-number="<N>"]` с `a` (`/tickets/<N>/`, текст «#N Тема»); невидимых нет; у статьи в корзине блока нет (даже у менеджера) | T-5120 |

### 11.9. Поиск

| Зацепка | Где и значение | Тесты |
|---|---|---|
| Строка в шапке | `TopBarItem(key="search", order=5, template="search/_bar.html", context=lambda request: {})`; `[data-search-bar]` содержит `input[type=search][name="q"][maxlength="200"][hx-get="/search/popup/"][hx-trigger="input changed delay:300ms, search"][hx-sync="this:replace"]` и `[data-search-popup]` (`hx-target`); вне `#notify-bell`; без `role`, `data-error`, `data-warning`, `ws-connect`, `hx-ext`; страница без `search` в шапке — только для анонима | T-5128, T-5149 |
| Выдача | `[data-search-popup]` и `[data-search-page]` содержат `section[data-search-group="<ключ>"]` (`tickets`, `articles`, `staff`, `units`; порядок 10–40), заголовок `[data-field="title"]`, строки `li[data-search-row]` с `a[href]` (адрес строки), `[data-field="title"]`, `[data-field="subtitle"]`; выбранная стрелками строка — `data-selected="true"` (ставит `search.js`); Enter открывает выбранную, Esc закрывает окно (`stopPropagation`, слайдер не закрывается) | T-5128, T-5149 |
| Всплывающая выдача | не более 5 строк в группе, чисел нет, `a[data-action="search-all"]` «Все результаты» (`/search/?q=<q в процентной записи>`); на короткий запрос окна нет, подсказки нет | T-5128, T-5149 |
| Страница результатов | у группы `[data-search-count][hx-get="/search/count/?q=…&group=<ключ>"][hx-trigger="load"]` (заполняется `span[data-search-count-value]` с `N` или `N+`), до 20 строк, `button[data-action="more"][data-next-offset="20"]` с `hx-get="/search/more/?q=…&group=<ключ>&offset=20"`; `[data-search-hint="short"` или `"long"]` — подсказка; `[data-empty-state="search"]` «Ничего не найдено» | T-5128, T-5149 |

## 12. Тексты, которые проверяют тесты

Если не сказано иное, тест ищет текст в разметке целиком (подстрока, регистр как здесь). Числа с разрядами — с обычным пробелом
(U+0020): «200 000», не с неразрывным (вопрос C-10). Где в тесте стоит «limit_shown», число предела обязательно есть в тексте.

### 12.1. Дословно из плана и решений

| Что | Текст | Источник | Тесты |
|---|---|---|---|
| Подсказка кнопок до первого сохранения | «Сохраните черновик» | план, «Создание…» | T-5103, T-5114, T-5140 |
| Страница 410 и POST над статьёй в корзине | «Статья удалена» | план, «Контракты», решение 43 | T-5104, T-5107, T-5116 |
| Конфликт правки | «Статью уже изменил Имя Фамилия в ЧЧ:ММ» (ФИО — `full_name` последнего сохранившего, время по Москве; ссылка «Сравнить версии» на `compare/?v=<base>&v=<текущая>` (текст — «Сравнить версии», C-11 принято)) | план, шаг 4 | T-5104, T-5142 |
| Нет изменений | «Изменений нет» | план, шаг 5 | T-5104, T-5142 |
| Предупреждение ПДн | кнопки «Вернуться к правке», «Опубликовать всё равно», «Сохранить всё равно» (у опубликованной) | план, «Защита от ПДн» | T-5118, T-5143 |
| Сравнение | «Отметьте две версии»; «Версия удалена»; «Показать N строк» (у `summary` вместо N число); «Ещё N изменений не показано» | план, «История…» | T-5105, T-5142 |
| Версия | «Восстановить эту версию»; «Удалить версию»; «Сравнить выбранные версии»; комментарий восстановления «Восстановлено из версии N» | план | T-5106 |
| Предпросмотр | «Предпросмотр уже готовится»; вкладки «Текст» и «Предпросмотр» | план | T-5102, T-5140 |
| Рубрики | «Не глубже трёх уровней» (создание и перенос); «Сначала перенесите» | план, «Рубрики, теги, главная» | T-5110, T-5111 |
| Вложения | «Файл больше 20 МБ»; «Исполняемые файлы не принимаются»; «Архивы с паролем не принимаются»; «У статьи уже 20 файлов» | план, «Файлы статьи» | T-5114 |
| Решения 41 и 42 | «Не удалось сохранить файл» (`write_failed`); «Картинка слишком большая» (`image_too_large`) | решения 41 и 42 задач | T-5114 |
| Состояния вложения | «проверяется», «в карантине» (без ссылки); заглушки картинки: «проверяется», «вложение удалено», «недоступно» | план, «Файлы статьи», «Как статья ссылается» | T-5114, T-5115 |
| Заглушка в тексте | `[вложение недоступно: имя]` | план | T-5102, T-5115 |
| «Статья из решения» | «Статья из решения»; «Черновик по этой заявке уже создан»; комментарий версии 1 «Создано из заявки #N» | план | T-5120 |
| Карточка заявки | «Статьи», «Привязать статью», «Отвязать», «Ссылка на статью» | план | T-5119, T-5120 |
| Подписка | «Подписаться», «Отписаться» | план | T-5111, T-5122 |
| Поиск | «Все результаты», «Показать ещё», «Ничего не найдено»; длинный запрос: «Запрос не длиннее 200 знаков»; число группы `N` или `N+` (раздел 9) | план, «Сквозной поиск» | T-5128, T-5149 |
| Главная | заголовки «Новые и изменённые», «Мои черновики», «Черновики», ссылки «Корзина», «Новая статья»; пункт меню «База знаний» | план | T-5112, T-5109 |
| Склонение (решение 15) | 1 — «статья», 2–4 — «статьи», 5–20 и 0 — «статей», далее по последней цифре (21 — «статья», 22 — «статьи», 25 — «статей», 111 — «статей»); в форме «N статья» | решение 15 | T-5112 test_home_tree_counts_published_with_subrubrics_in_three_russian_forms |
| Пометка уволенного | «(уволен)» после ФИО | план, `{% person_name %}` | T-5105, T-5116 |
| Уведомления | тексты и названия видов — раздел 7.2 (часть b) | план | T-5122 |

### 12.2. Тексты отказов, которых в плане нет (предложены; вопрос C-10)

Каждый отказ показывается так, как сказано в 10.1; код — `data-code`. Тест сверяет подстроку.

| Код | Где | Текст |
|---|---|---|
| `title_empty` | `title` | «Введите заголовок» |
| `title_too_long` | `title` | «Заголовок не длиннее 200 знаков» |
| `text_too_long` | `text` | «Текст не длиннее 200 000 знаков» |
| `rubric_missing` | `rubric` | «Выберите рубрику: такой рубрики нет» |
| `comment_too_long` | `comment` | «Комментарий к правке не длиннее 200 знаков» |
| `tags_too_many` | `tags` | «Не больше 10 тегов» |
| `tag_too_long` | `tags` | «Тег не длиннее 40 знаков» |
| `already_published` | общий | «Статья уже опубликована» |
| `not_in_trash` | общий | «Статья не в корзине» |
| `current_version` | общий | «Текущую версию удалить нельзя» |
| `name_empty` | `name` | «Введите название рубрики» |
| `name_too_long` | `name` | «Название не длиннее 100 знаков» |
| `name_duplicate` | `name` | «Рубрика с таким названием уже есть на этом уровне» |
| `too_deep`, `depth_exceeded` | `parent` | «Не глубже трёх уровней» (план) |
| `parent_missing` | `parent` | «Выбранной рубрики больше нет» |
| `parent_self` | `parent` | «Нельзя перенести рубрику в саму себя» |
| `parent_descendant` | `parent` | «Нельзя перенести рубрику в её подрубрику» |
| `default_immovable` | `parent` | «Рубрику «Общее» нельзя перенести» |
| `not_empty` | общий | «Сначала перенесите» (план; дополнение после точки: «подрубрики и статьи, в том числе из корзины») |
| `default_undeletable` | общий | «Рубрику «Общее» нельзя удалить» |
| `out_of_range` | `trash_days` | «Срок корзины — от 7 до 365 суток» |
| `empty` (комментарий) | `text` | «Введите текст комментария» |
| `too_long` (комментарий) | `text` | «Комментарий не длиннее 4000 знаков» |
| `not_closed_with_resolution` | общий | «Заявка не закрыта с решением» |
| `article_gone` | общий | «Статья удалена» (план) |
| `stale_version` | общий | по 12.1 |
| Короткий запрос (`hint="short"`, страница результатов) | подсказка `[data-search-hint="short"]` | «Введите не меньше 2 знаков» (дословно спека, цифрой) |

### 12.3. Прочие надписи (предложены; вопрос C-11)

| Что | Текст |
|---|---|
| Флеш после действий (`[role=status]`) | «Черновик сохранён» (создание и сохранение черновика); «Статья сохранена» (версия создана); «Статья опубликована»; «Версия восстановлена»; «Версия удалена»; «Статья перенесена в корзину»; «Статья возвращена из корзины»; «Статья удалена навсегда»; «Рубрика создана», «Рубрика переименована», «Рубрика перенесена», «Рубрика удалена»; «Срок корзины сохранён» |
| `hx-confirm` (вопрос C-5) | «Перенести статью в корзину?»; «Удалить статью навсегда? Это нельзя отменить.»; «Удалить версию N?»; «Удалить рубрику?» |
| Кнопки | «Сравнить версии», «Сохранить», «Сохранить черновик» (новая статья), «Опубликовать», «Править», «История», «Вернуть», «Удалить навсегда», «Отправить» (комментарий), «Удалить», «Вложить», «Картинка», «Вставить ссылку», «Сохранить» (срок корзины), «В корзину» |
| Пустая база | «В базе знаний пока нет статей» и, по праву, ссылка «Новая статья» |
| Пустая корзина | «Корзина пуста» |
| Пометка корзины | «В корзине»; «Удалил: Имя Фамилия» |
| Раздел комментариев | «Комментарии» |

## 13. Команды стенда и нагрузки

Образец — `apps/notify/management/commands/e2e_notify_tick.py` (CONTRACT-004, 8.1): проверка стенда — первым действием, до
любого чтения базы; один вывод в одну строку вида `имя: ключ=значение …`. Команды и скрипт — без новых зависимостей.

| Что | Требование | Тесты |
|---|---|---|
| Проверка стенда | функция `require_stand()` и константа `REFUSAL` — **в `apps/knowledge/stand.py`** (копия образца: `knowledge` не импортирует `notify`, раздел 4); `REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."`; без `os.environ.get("E2E_STAND") == "1"` — `CommandError(REFUSAL)` раньше любого обращения к базе; вопрос C-12 | T-5129 test_e2e_kb_trash_shift_and_e2e_kb_purge_refuse_without_stand_flag |
| `e2e_kb_trash_shift --days N` | `--days` обязателен, целое от 1 до 36500 (вне пределов — `CommandError("Число вне пределов от 1 до 36500: N")`; не число — ошибка разбора argparse, код 2, как у `e2e_notify_tick`); сдвигает назад на N суток `deleted_at` **всех** статей с `state="trash"` прямой записью `update(deleted_at=F("deleted_at") - timedelta(days=N))` без `save()` (журнал и события не затрагиваются); вывод одной строкой: `kb_trash_shift: days=N shifted=<число статей>`; корзина пуста — `shifted=0`, не ошибка; других аргументов нет (выбор одной статьи — вопрос C-12) | T-5129 test_e2e_kb_trash_shift_and_e2e_kb_purge_work_with_stand_flag; T-5147 |
| `e2e_kb_purge` | без аргументов; вызывает `retention.purge_trash()` (раздел 5.7) и печатает `kb_purge: purged=<n> skipped=<n> failed=<число>`; если `failed` не пусто — после вывода `CommandError` с номерами статей без текста исключений (код выхода не нуль); срок берётся из `KnowledgeSettings.trash_days` | T-5129; T-5108; T-5147 |
| `kb_rerender` | `apps/knowledge/management/commands/kb_rerender.py`; запускается и без `E2E_STAND`; аргумент `--batch-size N` (целое от 1 до 1000, по умолчанию 200); порциями по возрастанию номера, каждая порция — своя транзакция: `render.render(text, files.files_map(article), article.pk)` и запись `html`, `plain` статьи и `html` её версий (`queryset.update`, поля `updated_at`, `updated_by`, `version_no`, `text` не меняются: версии неизменяемы, FR-414); у опубликованных статей векторы пересчитываются (меняется `plain`; вопрос C-13); журнал и события не пишутся; вывод: `kb_rerender: articles=<n> versions=<n>`; повторный запуск даёт то же; номер статьи с ошибкой рендера — предупреждение в журнал приложения с номером и классом исключения, обход продолжается | тест не назначен (решение Opus по A-2); T-5129 по тексту файла не проверяет |
| `fill_articles.py` | `backend/tests/load/fill_articles.py` (рядом с `fill_tickets.py`); без `E2E_STAND=1` — `sys.exit("Скрипт работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено.")` до импорта моделей; запуск как у `fill_tickets.py`: `docker compose -f deploy/docker-compose.yml --profile dev exec -T -e LOAD_ARTICLES=5000 standtools python manage.py shell --no-imports < backend/tests/load/fill_articles.py`; переменные: `LOAD_ARTICLES` (по умолчанию 5000, добирает до цели при повторе), `LOAD_RUBRICS` (по умолчанию 60, три уровня; создаются, если нет), `LOAD_TAGS` (по умолчанию 200); тексты — из словаря настоящих русских слов ИТ-тематики, встроенного в скрипт (источник словаря — вопрос C-14); 90 % статей опубликованы, 10 % черновики; у части статей по 2–5 версий (для истории и сравнения) и 0–5 комментариев; авторы — существующие сотрудники с правом править (нет — любые действующие); векторы считает скрипт тем же SQL, что служба; SQL — только с параметрами; вывод: `fill_articles: articles=<n> published=<n> drafts=<n> versions=<n> comments=<n>`; данные убирает следующий сброс приёмки | T-5129 test_load_suite_has_fill_articles_script_and_knowledge_user_class (только наличие файла) |
| `KnowledgeUser` | класс в `backend/tests/load/locustfile.py` рядом с `NotifyUser`; докстринг с командой запуска (имя класса — последним аргументом, как у прежних); `wait_time = between(*(float(x) for x in os.environ.get("LOAD_WAIT", "5,15").split(",")))`; задачи по плану: главная, рубрика, статья, история, сравнение, комментарий, всплывающая выдача, страница результатов и подсчёт групп на частых, редких и смешанных словах; номера статей и рубрик берутся из разметки главной (`data-article-id`, `data-rubric-id`); пределы: p95 страниц — 500 мс (`P95_LIMIT_MS`), `/search/…` — 1000 мс, ошибок нет — проверка в `events.quitting` как у `_check_p95`; прогон только на свободной машине и по согласию владельца (решение 13 задач) | T-5129 (по тексту файла); T-5304 |
| Учётки нагрузки без прав | план требует часть пользователей без прав базы знаний и без «Все заявки», а `prepare_users.py` создаёт только администраторов: предложено `LOAD_PLAIN=N` в `prepare_users.py` (ещё N сотрудников с ролью «Сотрудник», строки того же `creds.csv` с четвёртым столбцом `plain`); `KnowledgeUser` берёт любую строку, `plain` — для проверки фильтров видимости; вопрос C-15 | T-5242 |

## 14. Что меняется в прежних контрактах

Сами `CONTRACT.md`, `CONTRACT-002.md`, `CONTRACT-003.md`, `CONTRACT-004.md` не правятся (решение 4 задач); как
CONTRACT-004 в разделе 12 уточнял прежние, так здесь перечислено, что в их строках устаревает со срезом 005 и чем
заменяется. Номера строк — по деревьям на 2026-10-19 (после среза 004); «Было» — текущий текст. Числа среза 005: семнадцать
точек, одиннадцать видов, пятнадцать прав, семнадцать заданий cron; `apps.notify` перестаёт быть последним; пункт меню
«База знаний» с `order` 7; поле `NotificationKind.coalesce`.

### 14.1. `CONTRACT.md`

| Строка | Было | Стало |
|---|---|---|
| 103 | `\| Меню \| ссылки href="/staff/", /roles/, /audit/, /settings/portal/, /settings/security/ \| видны только по праву (accounts.manage, roles.manage, audit.view, settings.portal, settings.security) \|` | то же для пяти адресов ядра; пункт «База знаний» (`/kb/`, `order` 7, решение 10 задач) виден каждому вошедшему без права, тест среза 001 `test_shell` пунктов по праву не затрагивает |
| 15 | `\| Настройки pytest \| … проверяют это через settings.INSTALLED_APPS \|` | без изменений: состав списка проверяют тесты срезов, а не этот контракт |

Прочие строки (права `accounts.manage`… среза 001, список из семи прав) не меняются: два новых права — в `PERMISSIONS_005`
(3.6).

### 14.2. `CONTRACT-002.md`

| Строка | Было | Стало |
|---|---|---|
| 5 | `… девять точек расширения (в срезе 003 их тринадцать, CONTRACT-003 § 3.2; в срезе 004 — пятнадцать, CONTRACT-004 § 3.1) …` | `… ; в срезе 005 — семнадцать, CONTRACT-005, раздел 3.1` |
| 42 | `… срез 004 — два (notify_tick, notify_retention, CONTRACT-004 § 1.3), всего в файле шестнадцать вызовов register …` | `… срез 005 — одно (purge_trash, 45 23 * * *, очередь maintenance, job_timeout=600, CONTRACT-005, раздел 1.2), всего в файле семнадцать вызовов register`; правка `== 16` → `== 17` в `test_sd_deploy.py` и `test_notify_deploy.py` — T-5138 пп. 15–16 |
| 127 | `… «Настройки портала» 60, «Уведомления» 62, «Сервис-деск» 65, «Безопасность и политика» 70 …` | `… «Сотрудники» 10 …`: перед ним — «База знаний» 7 (`/kb/`, `menu_items` модуля `knowledge`, без права и без `badge`, `visible` — истина; решение 10 задач); порядок `5, 7, 10, 20, 30, 40, 50, 60, 62, 65, 70`; `test_org_permissions::test_menu_staff_structure_calendar_items_by_permission` — T-5138 п. 6 (меню администратора — одиннадцать пунктов) |
| 283 | `кортеж из пятнадцати имён (тринадцать прежних по порядку и notification_kinds, top_bar_items, CONTRACT-004 § 3.1); org регистрирует … в первых девяти точках …` | `кортеж из семнадцати имён: пятнадцать прежних по порядку и search_providers, ticket_card_parts в конце (решение 23 задач)`; `org` — теперь и в `search_providers` (одна функция, «Подразделения», порядок 40); в `ticket_card_parts` регистрируется только `knowledge` (решение 26 задач); `test_extensions::test_org_registers_all_nine_extension_points` — T-5138 п. 1 (`POINTS_005`) |
| 286 | `clear() -> None: очищает все пятнадцать реестров` | `… все семнадцать реестров` |
| 633 | `3. A8: элемент меню … порядок …` (строка перечня порядка, 5…70 с «Уведомлениями» 62) | порядок в перечне — как в строке 127; новый пункт не вводит ключей описания (`permissions=()`, `visible`) |

Строки 288 и 797-800 (`menu_items`, `menu_for`) не меняются: пункт «База знаний» использует прежние ключи `visible` и пустые `permissions`.

### 14.3. `CONTRACT-003.md`

| Строка | Было | Стало |
|---|---|---|
| 108 | `\| nginx, форма и ответ \| … location = /request/ и location ~ ^/tickets/(new/\|[0-9]+/reply/)$ … каждый с client_max_body_size 55m; … \|` | то же, и третий `location ~ ^/kb/[0-9]+/files/$` с `client_max_body_size 55m;` и повторёнными `proxy_*` (CONTRACT-005, раздел 1.2); `test_deploy_files::test_nginx_body_size_6m_and_protected_location_internal_with_headers`: в `form_locations` добавлен третий шаблон `location ~ ^/kb/[0-9]+/files/$`, у каждого из трёх `55m`, оставшееся значение по-прежнему `["6m"]` (T-5138 п. 18) |
| 112 | `… в срезе 004 число вызовов register — шестнадцать (два новых: notify_tick, notify_retention …); правка п. (12) T-4138 …: «ровно 14» → 16 …` | в срезе 005 — семнадцать (`purge_trash`); правка T-5138 п. 15 `test_sd_deploy.py`: «ровно 16» → 17, таблица `KNOWLEDGE_JOBS` по образцу `NOTIFY_JOBS` |
| 244 | `POINTS … кортеж из пятнадцати имён: тринадцать прежних … и notification_kinds, top_bar_items в конце …; servicedesk — … и ещё в notification_kinds …; T-4138, п. (2): … POINTS_13 → 15 имён` | кортеж из семнадцати имён; `servicedesk` — ещё в `search_providers` («Заявки», порядок 10), точку `ticket_card_parts` только вызывает (решение 26 задач); `SERVICEDESK_POINTS` в `test_sd_boundaries.py` получает только `search_providers`; `POINTS_15` → `POINTS_17`, срез «нет `org`» — по точкам срезов 003-004 (T-5138 п. 2) |
| 249 | `… «Заявки» — order 5; «Уведомления» — order 62 (решение 10 задач среза 004); «Сервис-деск» — order 65 …` | дописано: «База знаний» — `order` 7 (решение 10 задач среза 005) |
| 264 | `PERMISSIONS_003 … в срезе 004 — тринадцать кодов: PERMISSIONS + PERMISSIONS_002 + PERMISSIONS_003 + PERMISSIONS_004 …; у «Руководителя» и «Сотрудника» нового права нет` | в срезе 005 — пятнадцать кодов: плюс `PERMISSIONS_005 = ("knowledge.edit", "knowledge.manage")` в `tests/support_kb.py`; у «Сотрудника ИТ» — `knowledge.edit` (кроме `staff.view`); у «Руководителя» — только `staff.view` (T-5138 пп. 3–5) |
| 1091 | `шестнадцать вызовов register (шесть прежних, восемь новых среза 003 и два среза 004).` | `семнадцать вызовов register (шесть прежних, восемь новых среза 003, два среза 004 и один среза 005).` |
| 1136 (8.3) | `### 8.3. Сброс стенда: точка stand_reset среза …` порядок вызова — обратный порядку регистрации | порядок регистрации в срезе 005 — `org`, `servicedesk`, `notify`, `knowledge`; при сбросе — `knowledge`, `notify`, `servicedesk`, `org`; данные `knowledge` не держат `PROTECT`-ссылок на узлы `org` (CONTRACT-005, 1.3) |
| вложения `attachments` (разделы о `is_executable`, `EXECUTABLE_EXTENSIONS`, `reason_of`, `MAX_FILE`) | функции и константы определены в `apps/servicedesk/services/attachments.py` | остаются доступными под теми же именами реэкспортом: проверки перенесены в `core.uploads` (CONTRACT-005, 3.5 и 4.4); тесты среза 003 на вложения не правятся (решения 6 и 30 задач) |

### 14.4. `CONTRACT-004.md`

| Строка | Было | Стало |
|---|---|---|
| 133 | `\| INSTALLED_APPS \| есть \| apps.notify — последний элемент, после apps.servicedesk \| T-4130 test_notify_is_last_in_installed_apps \|` | `apps.notify` стоит после `apps.servicedesk`; за ним — `apps.knowledge`, затем `apps.search` (решение 3 задач); `test_notify_deploy.py::test_notify_is_last_in_installed_apps` переименовывается и проверяет порядок (T-5138 п. 17) |
| 201 | `PERMISSIONS_004 … число прав после установки — 13: семь среза 001, три среза 002, два среза 003 и это; …` | после установки пятнадцать: те же тринадцать и два среза 005 (`PERMISSIONS_005`); `PERMISSIONS_004`, `TITLES_004`, `POINTS_004` не меняются |
| 212 | `POINTS … кортеж из пятнадцати имён … org регистрируется только в первых девяти (в двух новых не регистрируется); servicedesk — в notification_kinds …` | кортеж из семнадцати: `search_providers`, `ticket_card_parts` — шестнадцатое и семнадцатое имена; `org` — в первых девяти и в `search_providers`; `servicedesk` — ещё в `search_providers`; ядро — ещё в `search_providers` («Сотрудники», порядок 30); `knowledge` — в `menu_items`, `audit_labels`, `file_purposes`, `stand_reset`, `notification_kinds`, `search_providers`, `ticket_card_parts`; `search` — в `top_bar_items` (строка поиска, `order` 5) |
| 215 | `NotificationKind … поля по порядку: code, title, module; events; build; external_text; default_channels; mandatory; available; still_relevant; order: int = 0` | добавлено последнее поле `coalesce: bool = False` после `order` (решение 24 задач); прежние вызовы с именованными аргументами не меняются; `test_notify_catalog::test_kind_has_code_title_module_default_channels_mandatory_and_order` — T-5138 п. 8 |
| 218 | `Сброс реестров … на время блока все пятнадцать реестров пусты …` | все семнадцать; внутри блока `kinds.catalog() == []`, меню без «База знаний», поиск без групп, карточка заявки без частей |
| 241 (таблица видов) | четыре вида сервис-деска, три вида безопасности, «Канал отвязан» — восемь видов, модулей три | одиннадцать видов, модулей четыре: к ним добавляются три вида модуля «База знаний» (`order` 50, 51, 52; решение 25 задач), `default_channels == ("portal", "email")`, `coalesce=True`; `test_notify_catalog.py::TABLE` и счёт по модулям (4/3/1) → 4/3/1/3 (T-5138 п. 7) |
| 337 | `Функция точки notification_kinds() … возвращает четыре вида …` (сервис-деск) | без изменений для `servicedesk`; виды `knowledge` — своя функция `apps.knowledge.notify_kinds.notification_kinds` (CONTRACT-005, 7.2) |
| 431 | `Подписки шины \| NotifyConfig.ready() (последним среди приложений) вызывает dispatch.subscribe_all() …` | `NotifyConfig.ready()` — уже не последним: после него `ready()` у `knowledge` и `search`; подписчики `notify` те же; `knowledge` подписывает `core.user_dismissed` (`subscriptions.on_user_dismissed`), раздел 5.4 |
| 467, 481 | `catalog` — сортирует по `(order, порядок регистрации)`; `Table.rows` — виды, у которых `available(user)` истина и не `mandatory` | форма та же; в каталоге одиннадцать видов, у сотрудника без прав строки таблицы — четыре вида сервис-деска (если доступны) и «Статья в рубрике по подписке»; `test_notify_catalog_2.py`, `test_notify_prefs.py` — T-5138 пп. 10–12 |
| 136 (cron) | `\| Задание notify_tick \| … \|` и перечень заданий среза 004 | задания среза 004 не меняются; после них добавляется `purge_trash` (CONTRACT-005, 1.2), 17-й вызов |
| поле поиска в шапке (вне таблиц контракта, факт `test_shell.py`) | в шапке до среза 005 поля поиска не было | `input[name=q]` есть на каждой странице вошедшего (решение 28 задач); два локатора на `/staff/` сужаются областью формы списка (T-5138 пп. 19–20) |

Без изменений остаются: коды и тексты журнала срезов 001-004, формы «Мои уведомления» (добавляется строка вида «Статья в
рубрике по подписке», T-5138 пп. 13–14), поведение `dispatch.create` для видов без `coalesce` (4.1).

### 14.5. Перечень файлов тестов T-5138 (по `crm-work/slice005/tasks/impact.md`)

Правит только T-5138, по одному тесту, с разрешения владельца и с диффом (решения 29 задач). Задание 1 — серверные пункты 1–12 и
15–18, задание 2 — приёмка 13, 14, 19, 20.

| № | Файл | Что меняется |
|---|---|---|
| 1 | `backend/tests/test_extensions.py` | семнадцать точек, `POINTS_005`, `org` в `search_providers`; «пятнадцать» → «семнадцать» |
| 2 | `backend/tests/test_sd_boundaries.py` | `POINTS_17`; срез «нет `org`» по точкам срезов 003-004; `SERVICEDESK_POINTS` + `search_providers` (без `ticket_card_parts`, решение 26); проверка записи «Заявки» |
| 3 | `backend/tests/test_permissions.py` | админ — плюс `PERMISSIONS_005`; «Сотрудник ИТ» — `{"staff.view", "knowledge.edit"}` |
| 4 | `backend/tests/test_sd_access.py` | `len(permission_codes(admin)) == 15` |
| 5 | `backend/tests/test_org_permissions.py` | права и названия; роль «Сотрудник ИТ» (`STAFF_ROLE`); `knowledge.manage` — только у администратора; два новых права добавлены в проверку набора, меняемого в интерфейсе без кода (создание роли через `/roles/new/`) |
| 6 | `backend/tests/test_org_permissions.py` | меню администратора — одиннадцать пунктов, «База знаний» `order` 7 без `badge` |
| 7 | `backend/tests/test_notify_catalog.py` | `TABLE` — одиннадцать строк, модули, каналы по умолчанию видов `knowledge` |
| 8 | `backend/tests/test_notify_catalog.py` | список полей `NotificationKind` — плюс `coalesce`, значение по умолчанию ложь |
| 9 | `backend/tests/test_notify_catalog.py` | ожидание таблицы участника очереди — по `kind.available(user)` |
| 10 | `backend/tests/test_notify_catalog_2.py` | `SD_CODES + ["knowledge.rubric_subscription"]`; у постороннего одна строка |
| 11 | `backend/tests/test_notify_catalog_2.py` | то же для члена неотмеченного узла |
| 12 | `backend/tests/test_notify_prefs.py` | пятая строка таблицы («По подписке») |
| 13 | `backend/tests/e2e/test_e04_my_settings.py` | пять строк видов у сотрудника |
| 14 | `backend/tests/e2e/test_e12_criteria.py` | `EXPECTED_CATALOG` — три вида «База знаний»; счёт строк |
| 15 | `backend/tests/test_sd_deploy.py` | 17 вызовов `register`, `KNOWLEDGE_JOBS` |
| 16 | `backend/tests/test_notify_deploy.py` | 17 вызовов (проверка «то же время у других» на 23:40 не затрагивается: у `purge_trash` минута 45) |
| 17 | `backend/tests/test_notify_deploy.py` | `test_notify_is_last_in_installed_apps` — порядок `notify`, `knowledge` |
| 18 | `backend/tests/test_deploy_files.py` (+ новые проверки в `test_sd_deploy.py`) | третий шаблон в `form_locations` (три `location` с `55m`, `sizes == ["6m"]`); `KB_FILES_LOCATION` в `test_sd_deploy.py` |
| 19 | `backend/tests/e2e/test_o04_find_colleague.py` | локатор `input[name=q]` — областью формы списка |
| 20 | `backend/tests/e2e/test_o_success_criteria.py` | то же |

Не правятся: `tools/*.py`, `tools/test_*.py`, `docs/constitution.json`, `backend/tests/CONTRACT*.md`,
`backend/tests/e2e/helpers*.py`, `backend/tests/e2e/conftest.py`, тесты, которые анализ влияния признал не ломающимися
(`test_harness.py`, `test_notify_admin.py`, `test_notify_recipients_2.py`, `test_shell.py`, тесты карточки заявки).

## 15. Вопросы к Opus

### Часть a

Каждый вопрос — предложение исполнителя и довод; в таблицах разделов 1-4 предложение уже использовано, чтобы
таблица не оставалась с пустой ячейкой; до решения Opus оно ничьим решением не является.

| № | Вопрос | Предложение и довод |
|---|---|---|
| A-1 | Ключи групп поиска (`SearchProvider.key`; нужны для `/search/count/?group=<key>` и `/search/more/?group=`): план их не называет | `tickets`, `articles`, `staff`, `units` — латиница, по префиксам адресов групп (`/tickets/`, `/kb/`, `/staff/`, `/structure/`); ключ «Статей» (`articles`) часть b берёт отсюда. Довод: ключ идёт в адрес и в журнал приложения, поэтому нужен короткий и стабильный |
| A-2 | Тестов команды `kb_rerender` в списке имён TASKS-005 нет (есть тесты `e2e_kb_*` и `fill_articles.py` в `test_kb_deploy.py`) | Добавить один тест в `test_kb_deploy.py` или `test_kb_render.py`: команда перерисовывает `html` и `plain` статей и `html` версий, порциями, и после смены правил вывода страница показывает новый HTML. Довод: команда названа в плане («Модель данных») и в T-5100, а тест на неё не назначен; решение — за Opus (список имён подписан, правка — через решение по задачам) |
| A-3 | Как тест узнаёт «пропуск» при склейке, если у `create` нет возвращаемого признака | Предложено 4.1: нет записи, нет номера в возвращаемом списке, нет `Delivery`, нет сообщения живого канала; дополнительный возврат не нужен |
| A-4 | Что передавать в `seed(apps, schema_editor)` из `stand.py` и теста (`schema_editor` у вызывающего вне миграции нет; функция читает только `.connection.alias`) | Объект с атрибутом `connection`: `types.SimpleNamespace(connection=connections[db])`, где `db = "migrate"` если соединение настроено, иначе `"default"`. Довод: не открывать настоящий `schema_editor` (он начинает транзакцию и держит блокировки схемы); решение 27 задач говорит «реестр `django.apps.apps` и алиас базы `migrate`», но не форму второго аргумента |
| A-5 | Имена, которых нет в плане: ограничения БД (2.2), классы `TextChoices` `Article.State` и `ArticleFile.ImageFormat`, подпись `Purpose.KNOWLEDGE` («файл статьи» строчными по образцу прежних подписей), имя файла миграции `0002_initial_data` | Предложены в 2.2-2.4 по образцу факта (`org_unit_parent_name_key_uniq`, `notify/migrations/0002_initial_data.py`, `Purpose.PHOTO = "фото"`). Довод: тесты ловят исключение, а не имя ограничения; имя файла `0002_initial_data` совпадает с названием файла у `core`, `org`, `notify`, `servicedesk 0003_initial_data` |
| A-6 | Неизменяемость и значения по умолчанию новых записей точек | `frozen=True` у всех пяти; у `SearchProvider`, `TicketCardPart`, `TicketRef` значений по умолчанию нет; у `ParsedQuery` — `number=None`, `raw=""`, `hint=""`; у `SearchRow` — как в плане. Довод: запись лежит в реестре и не должна меняться; по умолчанию у `ParsedQuery` — чтобы тест создавал его одним словом |
| A-7 | Порядок полей `SearchProvider`: в плане два перечня — «Точки расширения» (`key, title, order, search, available`, без `count`) и «Контракты» (`key, title, order, search, count, available`) | Взят перечень «Контрактов» (полный, он же написан «как у `top_bar_items`»); раздел «Точки расширения» плана этим не противоречит, но неполон |
| A-8 | Поля `TicketBrief` (`number`, `subject`, `state`, `closed_with_resolution`, `resolution`) и вычисление `TicketRef.has_resolution` | План называет содержимое без имён; предложено `closed_with_resolution` по формулировке плана «признак «закрыта с решением»»; `has_resolution = bool(ticket.resolution.strip())`; `TicketRef.closed` — как `_closed(ticket)` |
| A-9 | Имена шаблонов строк выдачи для «Заявок» и «Сотрудников» (`SearchRow.template`) | `search/rows/_ticket.html`, `search/rows/_staff.html` — в каталоге `templates/search/`; общая строка — пустой `template`. Довод: шаблоны поиска живут в `templates/search/`; поставщик отдаёт имя, а не разметку |
| A-10 | Имя исключения и коды `core.comments` | `comments.CommentError` с `.code` `"empty"`/`"too_long"`; довод: образец — `files.PhotoError` ядра (одно исключение службы, причина — атрибутом) |
| A-11 | Имена и подписи `core.file_response` | `download(stored, filename)` и `inline_image(stored, image_format)`; довод: план называет только модуль и заголовки; два вызова — два режима выдачи (скачивание и показ картинки) |
| A-12 | В какой библиотеке тегов живёт `{% person_name %}` и как выглядит пометка | Существующая `apps/core/templatetags/portal.py` (`{% load portal %}`); пометка — `<span data-dismissed="true">ФИО (уволен)</span>`, как в карточке заявки. Довод: не заводить вторую библиотеку и не вводить новый признак |
| A-13 | Ключ замка склейки: имя функции построения и порядок взятия | `dispatch.coalesce_key(user_id, kind_code, object_ref)`; сортировка по строке ключа. План: «по возрастанию ключа», строка или хэш не названы |
| A-14 | Склейка внутри одного вызова `create` и при пустом `object_ref` | Повтор в одном вызове склеивается (следствие цикла плана); при `object_ref=""` склейки нет. Тестов на эти два случая в списке имён нет; предложение — зафиксировать поведение, чтобы код не удивил |
| A-15 | Логгер и содержимое записи при исключении части карточки | Логгер `apps.servicedesk`, запись уровня `ERROR` с ключом части и классом исключения, без текста исключения (текст может содержать данные заявки); довод: как в поиске (план «Сквозной поиск», сборка) |
| A-16 | Оболочка частей карточки и ключи записей `knowledge` | `data-card-part="<key>"` и `data-part-kind="<kind>"`; ключи `kb-articles`, `kb-from-ticket`, `kb-link-tool`; порядок 10 у каждой. Довод: приёмке нужна зацепка на место, но без части оболочки быть не должно (снимок T-5119); окончательный перечень `data-*` — раздел 11 части c |
| A-17 | `available(user)` у «Заявок» | `access.menu_visible(user)`; довод: план говорит «видимость заявок (SPEC-003)», готовой функции «может видеть хоть одну заявку» кроме этой нет |
| A-18 | Путь подразделения у корня | У корня структуры путь пустой строкой (подразделение верхнего уровня без предков); довод: путь — названия предков, а не собственное название |

### Часть b

Предложения исполнителя части b (разделы 5–9); в таблицах они уже использованы. До решения Opus ничьим решением не являются.

| № | Вопрос | Предложение и довод |
|---|---|---|
| B-1 | Базовое исключение отказов формы: плана имён нет; модуль `errors.py` в перечне модулей плана отсутствует (тест границ T-5130 читает перечень путей) | `KnowledgeError(code, field)` в `services/__init__.py` и подклассы (5.1); довод: не добавлять модуль сверх плана |
| B-2 | Тип `form` у `save/publish/create` и результат `save` | `ArticleForm` (NamedTuple) и `SaveResult(kind, article, version, pdn)`; «Изменений нет» и предупреждение ПДн — не исключения. Довод: это ответы формы, а не отказы; тест читает `kind` |
| B-3 | Порядок проверки полей формы и шагов цепочки (плана: «Проверки формы», затем шаги 1–7) | Поля формы проверяются до шага 1, поэтому статья в корзине с пустым заголовком даёт отказ у поля; довод: форма не зависит от состояния. Альтернатива — шаг 1 первым; тесты T-5104 корзину проверяют с корректной формой |
| B-4 | Повторные действия: публикация опубликованной, корзина статьи в корзине, возврат не из корзины | `already_published` (`ArticleError`), `ArticleGone`, `not_in_trash`; довод: двойное нажатие не должно давать 500; плана нет |
| B-5 | Служба комментариев `knowledge` (`add_comment`, `delete_comment`) и место публикации события и журнала; модуля `comments` в перечне нет | Функции в `articles.py`; довод: журнал и событие должны идти в той же службе, что и проверки статьи |
| B-6 | План: `diff.compare(old, new)`; модуля `diff` нет, `versions` есть | `versions.compare(article, a, b)` и `Comparison`/`FieldDiff`/`DiffLine`; довод: перечень модулей плана подписан |
| B-7 | Имена вспомогательных функций: `rubrics.tree`, `tags.suggest`, `files.list_for`, `files.files_map` | Предложены как есть; довод: нужны страницам и тестам, планом не названы |
| B-8 | Имя функции выборки порции ночной очистки (решение 32 требует точку подмены) | `retention.next_batch(after_id, cutoff)`; довод: подмена должна быть атрибутом модуля, как у `purge` |
| B-9 | `settings.update` с тем же значением | Без записи, без журнала, без ошибки; довод: журнал «было / стало» без изменения бессмыслен |
| B-10 | Решения 41 и 30 расходятся: подмена записи файла нужна, а подмен `monkeypatch` на `uploads` и `attachments` нет | Подмена стандартного `pathlib.Path.write_bytes` для путей под `PROTECTED_ROOT/incoming`; `uploads` не подменяется. Альтернатива — уточнить решение 30: «кроме записи файла» |
| B-11 | `render.render` в плане без номера статьи, а адреса `/kb/<id>/…` его требуют; тип `Rendered` | Третий параметр `article_id=None` (без номера `att:N` даёт заглушку); `Rendered` — `NamedTuple`; довод: иначе адреса не построить |
| B-12 | Белый список тегов и атрибутов, класс и текст заглушки | Перечень из 6.1; заглушка `span.kb-noimg` с текстом «[вложение недоступно: имя]» (текст плана; в F1 был «изображение»); довод: план называет белый список, но не перечисляет |
| B-13 | Чем заменяется найденное в `mask_plain` и `mask_resolution` | Постоянная строка `[скрыто]`; довод: план говорит «скрывает» |
| B-14 | Ключи данных событий `knowledge.*` | ключи ровно по плану: `knowledge.article_published` и `knowledge.article_changed` — `article_id`, `actor_id`, `rubric_id`; `knowledge.comment_added` — `article_id`, `comment_id`, `actor_id` (ключа `version` нет; решение Opus по проверке контракта З4) |
| B-15 | «Рубрика» в тексте подписки | **Отменено разделом 17 п. 51** (рубрика подписки получателя). Было: рубрика самой статьи, не предка, на которого подписан |
| B-16 | Набор ключей `before`/`after` по действиям (план даёт общий перечень) | Таблица 8.1; довод: удаление — в `before`, остальные — в `after`, как в плане |
| B-17 | `object_type` у `knowledge.trash_days_changed` (плана: только `knowledge.article` и `knowledge.rubric`) | `knowledge.article` с пустым `object_id`; довод: два вида объекта подписаны планом. Альтернатива — третий вид `knowledge.settings` |
| B-18 | Слова числовых запросов: `"15"` даёт `words=["15"]` и `number=15`, `"#5"` — `words=[]` | Буквально по тексту плана; довод: пункт 2 берёт `\w+`, пункт 3 отбрасывает короткие |
| B-19 | Имена `POPUP_LIMIT`, `PAGE_LIMIT`, `Group`, `Count`; признак «есть ещё» (`len(rows) >= limit`) | Предложены; довод: план даёт числа 5 и 20, но не имена и не признак |
| B-20 | Логгер ошибки поставщика | `apps.search.services` (имя модуля), `ERROR`, ключ и класс исключения; довод: план говорит «журнал приложения» без имени |
| B-21 | `head_count(parsed)` — имя функции точного счёта шага 1 | Предложено; довод: план называет «отдельный дешёвый счёт по `search_head`» без имени |
| B-22 | Добавочная сортировка по `id` вниз в шагах 1 и 2 | Добавлена; довод: без неё порядок равных по времени статей не определён |
| B-23 | Перечень 36 проб: выборка F1 Ф5 переписана под план (`att:N`, `images`, классы `kb-al-*`, текст заглушки) | Таблица 6.2; пробы проверены на выборке F1 (36 строк `probes.out`), но не запускались на коде плана; Opus сверяет (решение 39) |

### Часть c

Предложения исполнителя части c (разделы 10-14); в таблицах они уже использованы. До решения Opus ничьим решением не являются
(решения Opus по задачам 1-45 помечены «решение N задач» в самих таблицах и здесь не повторяются).

| № | Вопрос | Предложение и довод |
|---|---|---|
| C-1 | Имена маршрутов для `reverse` и пространства имён (план даёт пути, не имена; тесты ходят по путям) | `app_name = "knowledge"` и `"search"`, имена из 10.2-10.6 (`home`, `new`, `article`, `edit`, `publish`, `preview`, `history`, `compare`, `version`, `version_restore`, `version_delete`, `article_trash`, `article_restore`, `article_purge`, `trash_list`, `settings`, `rubrics`, `rubric_new`, `rubric_rename`, `rubric_move`, `rubric_delete`, `rubric_page`, `rubric_subscribe`, `tag_page`, `tag_suggest`, `file_attach`, `file_download`, `file_delete`, `image`, `comment_add`, `comment_delete`, `pick`, `link_add`, `link_delete`, `from_ticket`; `search:popup`, `results`, `count`, `more`). Довод: без имён шаблоны и помощник `support_kb` придумают их по-разному. Отдельно: пути `/kb/…/delete/` содержат слово `delete`; проверки `test_accounts.py` и `test_notify_deploy.py` ищут `regist`, `signup`, `hook`, `updates`, `bot`; ограничение на `delete` касается только `staff/` (анализ влияния, У8) — Opus подтверждает |
| C-2 | Куда ведёт успех и какие флеш-сообщения | Единое правило: успех сохранения, публикации и восстановления версии — 302 на `/kb/<id>/` (в том числе первое сохранение черновика), НХ — `HX-Redirect`; флеш ядра `_flashes.html` (`[role=status]`) с текстами из 12.3. Довод: единый адрес проще для тестов; альтернатива — после первого сохранения вести на `/kb/<id>/edit/`, чтобы сразу вложить файл (тест k01 «после первого сохранения кнопки работают»); плана нет |
| C-3 | Поля `/kb/preview/` | `text` и `article` (необязательный номер статьи, нужен для `att:N`); предпросмотр чужой невидимой статьи не берёт её вложения. Довод: план говорит «текст и номер статьи, если есть», имён не даёт |
| C-4 | GET `/kb/<id>/edit/` статьи в корзине у управляющего | 302 на `/kb/<id>/` (правит только «Вернуть»; `can_change` ложно, раздел 5.7). Альтернатива — 200 страница правки с отключёнными кнопками. Довод: план: «управляющему — статья с пометкой»; формы правки в корзине нет |
| C-5 | Как подтверждаются «в корзину», «удалить навсегда», «удалить версию», «удалить рубрику» | `hx-confirm="<текст>"` на форме (окно браузера), сервер поля подтверждения не требует (прямой POST без окна проходит, права проверяются на сервере); тест читает атрибут, Playwright принимает `dialog`. Довод: план говорит «с подтверждением» без механизма; страница подтверждения добавила бы адреса и тесты. Альтернатива — поле `confirm=1` и промежуточная страница |
| C-6 | Подбор статьи: параметр `ticket` у `/kb/pick/` и имя поля поиска в карточке заявки | Параметр `ticket` (номер заявки) делает строки кнопками привязки, без него строки несут `data-title` и `data-url` для вставки в комментарий; поле поиска карточки названо `pick`, а не `q`, запрос `q` шлёт `kb-link.js`. Довод: в шапке на каждой странице уже `input[name=q]` (решение 28 задач); второе поле `name=q` в карточке нарушило бы строгий режим локаторов; план называет только `/kb/pick/?q=` |
| C-7 | Как адрес картинки отдаёт заглушки («проверяется», «вложение удалено», «недоступно») | 200 `image/svg+xml` с файлом из статики и заголовком `X-KB-Placeholder: checking`/`removed`/`unavailable`, `Cache-Control: no-store`; тест различает по заголовку и тексту SVG. Довод: HTML картинки не зависит от состояния (план), поэтому различать приходится по ответу адреса; план говорит только «заглушка… SVG из статики». Альтернатива — 302 на статический файл (тест читает `Location`) |
| C-8 | Загрузка файла: один файл за запрос, форма отдельная | `form[data-form="kb-attach"]` рядом с формой статьи (вложенных форм нет), `input[type=file][name=file]` без `multiple`; несколько файлов — несколько запросов. Довод: `files.attach(user, article_id, upload)` принимает один файл (раздел 5.5) |
| C-9 | Имена полей форм и зацепок `data-*`, которых нет в плане | Поля: `title`, `text`, `rubric`, `tags`, `comment`, `action`, `file`, `article`, `ticket`, `trash_days`, `parent`, `name`, `pick`; зацепки — разделы 10-11 целиком (в плане есть только `data-md=…`, `kb-diff-add/del`, `kb-noimg`, `kb-al-*`, `kb-scroll`, `input[name=q]`). Довод: приёмке и тестам нужны единые имена, образцы — `data-form`, `data-action`, `data-field`, `data-empty-state` прежних срезов |
| C-10 | Тексты отказов, которых в плане нет, и форма записи чисел | Таблица 12.2; числа с разрядами — с обычным пробелом («200 000»); тест сверяет подстроку. Довод: тесты «…limit_shown» требуют число предела в тексте; план текстов не даёт (кроме «Не глубже трёх уровней», «Сначала перенесите», четырёх текстов вложений) |
| C-11 | Флеш-сообщения, подтверждения, названия кнопок и блоков, подсказка короткого запроса, текст ссылки «Сравнить версии» | Таблицы 12.2 и 12.3. Довод: приёмка находит элементы по тексту; в плане этих надписей нет |
| C-12 | Команды стенда: где живёт `require_stand()` и можно ли сдвинуть одну статью | `require_stand()` и `REFUSAL` в `apps/knowledge/stand.py` (копия образца `e2e_notify_tick`, не импорт: `knowledge` не знает `notify`); `e2e_kb_trash_shift --days N` сдвигает все статьи в корзине, выбора одной статьи нет. Довод: план называет только `--days N` и «сдвигает `deleted_at`»; сценарий 8 («91 день удалена, 89 — остаётся») решается порядком действий (сдвиг, затем новая статья в корзину). Альтернатива — `--article N` |
| C-13 | Что делает `kb_rerender` с векторами и ошибкой рендера | Пересчитывает `html`, `plain` статей и `html` версий порциями (`--batch-size`, 200), векторы опубликованных — заново (меняется `plain`), журнала и событий нет, ошибка рендера одной статьи — запись в журнал приложения с номером и классом, обход продолжается. Довод: без пересчёта вектора поиск остался бы по прежнему `plain`; план называет команду («Модель данных»), но не поведение |
| C-14 | Откуда «словарь настоящих слов» для `fill_articles.py` | Список слов ИТ-тематики (несколько сотен) встроен в скрипт или лежит рядом файлом `backend/tests/load/words_ru.txt`; частые, редкие и смешанные слова для `KnowledgeUser` берутся из него же. Довод: у ранних замеров (T-5003) словарь есть, но в репозиторий не входит; скрипт подаётся на вход `manage.py shell`, поэтому внешних файлов лучше не требовать; слова проходят проверку запретных слов (`test_stack.py`) |
| C-15 | Учётки без прав базы знаний для `KnowledgeUser` | `LOAD_PLAIN=N` в `prepare_users.py`: ещё N сотрудников с ролью «Сотрудник» (четвёртый столбец `plain` в `creds.csv`); без него класс работает как прежние (все учётки — администраторы). Довод: план требует часть пользователей без прав и без «Все заявки», а `prepare_users.py` создаёт только администраторов; правка скрипта нагрузки — T-5242, `tools/` не затрагивается |
| C-16 | Что делают кнопки «Вложить» и «Картинка» панели после первого сохранения | «Вложить» — выбор файла и загрузка (форма `kb-attach`, текст не меняется); «Картинка» панели — выбор картинки и загрузка, после успешной загрузки вставляется `![имя](att:N)`; кнопки «Картинка»/«Вставить ссылку» в строках списка (11.4) вставляют разметку уже загруженного файла. Довод: план задаёт «Вложить» и «Картинка» как кнопки с подсказкой «Сохраните черновик», но не их действие после сохранения |
| C-17 | Ответ «Статья из решения» на отказ и повтор | Успех и «уже создан» — 302 на `/kb/<id>/edit/` (НХ — `HX-Redirect`), повтор показывает флеш «Черновик по этой заявке уже создан»; `not_closed_with_resolution` — 200 с `[role=alert][data-code="not_closed_with_resolution"]`. Довод: план: «Затем открывается редактор», «открывается он с сообщением»; отказ — «отказ» без формы |
| C-18 | Конфликт правки и «Статья удалена» — общие отказы формы с `role="alert"` (исключение решения 16) | Да: `[role=alert][data-code="stale_version"]` и `[role=alert][data-code="article_gone"]`, как общие отказы форм срезов 001-004; а «Изменений нет» и предупреждение ПДн — не отказы, они без `role` (`[data-kb-notice]`, `[data-kb-pdn]`). Довод: приёмка прежних срезов ищет отказы формы по `[role=alert]`; решение 16 запрещает его в прочих блоках среза |
| C-19 | Что отдают GET-страницы на запрос НХ | Страницы `/kb/…` и `/search/` — полную страницу на любой запрос; только списки с `offset` и адреса-фрагменты отдают фрагмент. Довод: слайдера у страниц базы знаний нет, а прежний соглашение «НХ — фрагмент» относится к формам и слайдеру заявок |


## 16. Решения Opus по вопросам (проверка контракта, решение 2 задач)

Все предложения исполнителей частей a, b, c (A-1…A-18, B-1…B-23, C-1…C-19) **приняты** и действуют как написаны в
таблицах разделов 1–14, кроме трёх:
- **A-2** — отдельного теста команды `kb_rerender` нет: задачи подписаны (правка списка тестов потребовала бы новой подписи),
  а план теста команды не требует; поведение команды (раздел 13) проверяет Opus в проходе T-5301 при смене правил вывода.
- **B-10** — сбой записи файла подменяется не в стандартной библиотеке, а в точке модуля: `uploads.store` пишет файл через
  `uploads.write_file(path, data)`, тест подменяет `apps.core.services.uploads.write_file` (раздел 5). Запрет подмен решения
  30 касается прежних тестов среза 003, а не новой точки.
- **C-2** — успех первого сохранения новой статьи ведёт на `/kb/<id>/edit/` (автор сразу вкладывает файлы, сценарий 1); успех
  остальных сохранений, публикации и восстановления версии — на `/kb/<id>/`.

Уточнения к принятым:
- **A-4** — `seed(apps, schema_editor)` читает только `schema_editor.connection.alias`; `stand.py` и тест передают
  `SimpleNamespace(connection=connections[alias])`, алиас `migrate` при наличии, иначе `default`.
- **A-13** — порядок замков — по строке ключа `'<user_id>:<код>:<object_ref>'` (детерминирован в любом процессе).
- **B-17** — смена срока корзины пишется с `object_type="knowledge.article"` и пустым `object_id`: план знает два вида
  объекта журнала.
- **C-1** — слово `delete` в путях `/kb/…/delete/` допустимо: ограничение на `delete` в прежних тестах касается только `staff/`.
- **C-14** — словарь `backend/tests/load/words_ru.txt` проходит проверку запретных слов `test_stack.py`.
- **C-15** — `prepare_users.py` получает режим `LOAD_PLAIN=N`; файл учёток нагрузки читает только скрипт нагрузки, в отчёты
  и вывод его содержимое не попадает.

### Правки по проверке контракта (review.md)

З1–З24 внесены (отчёт проверки `crm-work/slice005/stage2/t5100/review.md`); решения Opus по З3, З4, З9, З10, З11, З13, З21, З22 — как в этом подразделе (не решения владельца):
- З3 — читатель при POST над статьёй в корзине получает 200 «Статья удалена»; представление не обрывает такой POST предпроверкой права: порядок отказов — шаги плана (корзина, затем право); у `edit/` и `publish/` «403 нет права править» действует после проверки корзины.
- З4 — ключи событий ровно по плану: `article_published` и `article_changed` — `article_id`, `actor_id`, `rubric_id` (ключа `version` нет); `comment_added` — `article_id`, `comment_id`, `actor_id`.
- З9 — часть `kb-articles` возвращает `None`, когда нет `can_edit` и нет видимых связей; при `can_edit` раздел с формой привязки выводится всегда.
- З10 — порядок отказов `publish`: `ArticleGone` → `PermissionDenied` по `can_change` → `already_published`; `can_publish` — только признак показа кнопки.
- З11 — строки вставки кнопок панели редактора названы в 11.3 (тест сверяет подстрокой).
- З13 — `uploads.write_file(path, data)` назван у `store` (3.5); единственная точка подмены на `uploads` — шапка и 5.8 согласованы.
- З21 — сбой версии подменяется в `apps.knowledge.services.articles._create_version`; рендер предпросмотра, замок строки и выключение записи `staff_directory` — по строкам 5.8.
- З22 — снимок `tests/fixtures/ticket_card_slice003.html` снимает T-5119 до правки `_card.html`.

### Поправка Opus к решению 18 задач (гонки без потоков), 2026-10-19
Решение 18 TASKS-005 («два потока с `django_db(transaction=True)`») невыполнимо в проекте: `tests/conftest.py` создаёт
базу под владельцем, а тесты идут под ролью приложения, поэтому `transaction=True` не работает (тот же вывод — в
CONTRACT-004), а второй поток со своим соединением не видит незафиксированных данных теста. Тесты гонок среза 005
пишутся так: последовательные вызовы (устаревшая `base_version`, повторное нажатие), ограничения базы (уникальность
(`article`, `number`)), и проверка SQL помощниками `support_kb` (`FOR UPDATE`, `SKIP LOCKED`, порядок и вид advisory-замков
по строке ключа). Имена тестов не меняются; «две одновременные …» в имени теста читается как «два вызова, которые
пересеклись бы во времени», и тест доказывает механизм, который это исключает. Отступление записывается в отчёт
TASKS-005 (как отступления среза 004).

## 17. Дополнения Opus по вопросам писателей тестов Этапа 2

Действуют поверх разделов 1–16 (позднее дополнение главнее раннего). «Затрагивает» — файлы, которые должны соответствовать.

| № | Вопрос (кто) | Решение | Затрагивает |
|---|---|---|---|
| 1 | Тип `number` в `before`/`after` журнала (T-5103) | целое число — номер статьи (`article.pk`); тесты могут сравнивать через `int(...)` | test_kb_articles.py, test_kb_audit.py |
| 2 | Что такое N в «Показать N строк» и сколько строк контекста (T-5105) | N — число скрытых в этом `<details>` неизменённых строк; вокруг каждого изменения видно ровно по 3 неизменённые строки с каждой стороны (если столько есть), остальное в блоке уходит в `<details>` | test_kb_history.py |
| 3 | Что считать «изменённой строкой» для предела 2 000 (T-5105) | каждая строка, выведенная с «+» или «−» (замена k строк — 2k изменённых строк) | test_kb_history.py |
| 4 | Где `[data-side]` в сравнении полей (T-5105) | потомок строки поля `[data-kb-diff-field]` | test_kb_history.py |
| 5 | «Вернуть» и «Удалить навсегда» не-управляющим над статьёй в корзине (T-5107) | 200 «Статья удалена» (`[role=alert][data-code="article_gone"]`), служба поднимает `ArticleGone` — порядок отказов: корзина, затем право; над статьёй НЕ в корзине «Вернуть»/«Удалить навсегда» не-управляющим — 403 (`PermissionDenied`). Строка «POST `trash/`, `restore/`, `purge/` …» таблицы 10.7 читается с этой оговоркой | test_kb_trash.py, test_kb_access.py |
| 6 | Номер `<N>` в `/kb/<id>/images/<N>/` и `/files/<N>/` (T-5107) | `ArticleFile.pk` | test_kb_trash.py, test_kb_files*.py |
| 7 | Колонка рубрики в списке корзины (T-5107) | название рубрики (не путь) в `[data-field=rubric]` | test_kb_trash.py |
| 8 | Запись «файл на диске отсутствует» при удалении навсегда (T-5108) | одна запись уровня `WARNING` логгера `apps.knowledge.services.articles` с номером статьи, без имени и пути файла; ошибок (`ERROR`) нет | test_kb_trash_2.py |
| 9 | Поле срока корзины при отказе (T-5108) | `input[name=trash_days]` с `value` введённого значения (как ввёл сотрудник) | test_kb_trash_2.py |
| 10 | `data-code="article_gone"` у POST над статьёй в корзине (T-5109) | у всех POST-действий над статьёй в корзине (`edit/`, `publish/`, `restore/`, `purge/`, `trash/`, `versions/<N>/restore/`, `versions/<N>/delete/`, `comments/`, `files/`) — один и тот же отказ `[role=alert][data-code="article_gone"]` с текстом «Статья удалена» (кроме управляющего на `restore/` и `purge/` — для него это обычные действия корзины) | test_kb_access.py, test_kb_trash.py, test_kb_comments.py, test_kb_files.py |
| 11 | Номер `<N>` в `files/<N>/delete/` (T-5109) | `ArticleFile.pk` (как п. 6) | test_kb_access.py, test_kb_files*.py |
| 12 | Строки списка на странице тега (T-5112) | строка `li[data-article-id]` показывает заголовок, рубрику и теги статьи ссылками `a[data-tag]`; облака тегов (отдельного списка тегов) нет ни на главной, ни на странице тега | test_kb_tags_home.py |
| 13 | Ссылка «Новая статья» в пустой базе (T-5112) | `a[data-action="kb-new-article"]` внутри `[data-empty-state=kb]` (у того, у кого есть право) | test_kb_tags_home.py |
| 14 | «Мои черновики» у управляющего (T-5112) | управляющий видит оба блока: `[data-kb-my-drafts]` (свои) и `[data-kb-all-drafts]` (все) | test_kb_tags_home.py |
| 15 | Что такое «пустая база» (T-5112) | нет ни одной опубликованной статьи (черновики и корзина не считаются); пояснение показывается и тогда, когда есть только черновики | test_kb_tags_home.py |
| 16 | `StoredFile.content_type` вложения статьи (T-5113, T-5114) | для картинки — `image/<формат>` (`image/png`, `image/jpeg`, `image/gif`, `image/webp`), для прочего — `application/octet-stream` | test_core_uploads.py, test_kb_files*.py |
| 17 | «Стирание прежнего пути только после фиксации» (T-5113) | достаточно доказательства по результату: `move` сам не стирает, после выполнения задания проверки прежнего пути нет; момент «внутри транзакции» не проверяется | test_core_uploads.py |
| 18 | Отказ вложения на обычном (не HTMX) запросе (T-5114) | 200 страница правки `[data-kb-page="edit"]`, отказ `[role=alert][data-code=<код>]` внутри `[data-kb-files]` | test_kb_files.py |
| 19 | Текст в SVG заглушек (T-5115) | SVG содержит элемент `<text>` с буквальным словом: «проверяется», «вложение удалено» или «недоступно» (UTF-8); заголовок `X-KB-Placeholder` — `checking`, `removed`, `unavailable` | test_kb_files_2.py |
| 20 | Кнопки в строке вложения (T-5115) | «Картинка» — только у чистой картинки (`image_format` не пуст и файл `clean`); «Вставить ссылку» — у `clean` и `pending`, у карантина нет ни одной | test_kb_files_2.py |
| 21 | Имя `test_external_image_url_renders_link_text_not_img` (T-5115) | **имя неточно**: тест проверяет поведение раздела 6.1 — внешней картинки нет (`img` отсутствует, внешнего адреса в выводе нет), на её месте заглушка `span.kb-noimg` «[вложение недоступно: подпись]» | test_kb_files_2.py |
| 22 | Скрытое поле `action` и кнопки предупреждения ПДн (T-5118) | обе кнопки лежат внутри `[data-kb-pdn]`; скрытое `input[name=action]` — одно на странице, внутри формы `form[data-form="kb-article"]` (или формы публикации), не внутри `[data-kb-pdn]` | test_kb_pdn_2.py |
| 23 | Вставка «Заголовок: адрес» в комментарий (T-5120) | вставку в поле делает `kb-link.js`; серверный тест проверяет разметку инструмента и данные `data-title`, `data-url`; саму вставку — приёмка T-5143 | test_kb_tickets_2.py |
| 24 | Кому виден инструмент `kb-link-tool` (T-5120) | всем, кто видит заявку (подсказка `/kb/pick/` — любому вошедшему, решение 9 по задачам ПД9); права «Редактирование» не требует | test_kb_tickets_2.py, test_kb_tickets.py |
| 25 | Текст подсказки короткого запроса (T-5128, T-5125) | дословно спека: «Введите не меньше 2 знаков» — цифрой (таблица 12.2 исправлена); тесты сверяют этот текст, без альтернатив | test_search_parse.py, test_search_pages.py |
| 26 | Имя `test_rubric_name_of_100_chars_is_cut_to_100_with_ellipsis_in_text` (T-5122) | **имя неточно**: название рубрики не длиннее 100 знаков (FR-418), правило обрезки «первые 99 знаков и «…»» срабатывает только сверх 100; тест проверяет, что название ровно из 100 знаков входит в текст уведомления целиком, без «…» | test_kb_notify_2.py |
| 27 | Заблокированный получатель в `still_relevant` (T-5122) | `still_relevant` истинно для заблокированного (план отсекает только уволенного; доставки наружу заблокированному не создаёт сам `notify`, срез 004) | test_kb_notify_2.py |
| 28 | Какие 300 кандидатов берёт шаг 2 поиска статей (T-5126) | 300 самых новых совпадений по `updated_at DESC, id DESC` (вариант B раннего замера T-5003): выдача, «Показать ещё» и счёт `LIMIT 301` идут по одному порядку; тест предела проверяет число строк, признак «N+» и что в шаг 2 попали самые новые | test_search_providers.py |
| 29 | Путь скрипта резервной копии (T-5129) | фактический путь `deploy/backup/backup.sh` (раздел 1.2 читается так); файл не правится (план: «Запуск») | test_kb_deploy.py |
| 30 | Формат `datetime` у `time[data-at]` (T-5129) | ISO 8601 с поясом Москвы, до секунд: `2026-10-19T08:57:00+03:00`; видимый текст — `ДД.ММ.ГГГГ ЧЧ:ММ` по Москве | test_kb_deploy.py, тесты страниц |
| 31 | Состав проверки «тексты по-русски» (T-5129) | надписи разделов 12.1 и 12.3 на страницах `support_kb.RUSSIAN_PAGES` и отсутствие английских слов интерфейса из короткого списка (`Save`, `Delete`, `Cancel`, `Search`, `Submit`, `Edit`, `Back`) | test_kb_deploy.py |
| 32 | Проверка второго фильтра `nh3` (R-1-a) | шаг белого списка — отдельная функция `render.sanitize(html: str, article_id: int \| None) -> str`, которую `render.render` вызывает последней; тест второго фильтра подаёт ей готовый HTML с чужими `src`, `href`, `class` и проверяет, что они вырезаны | test_kb_render.py |
| 33 | Где приводится форма (R-1-a) | в службе: `articles.create/save/publish` сами приводят `\r\n` и `\r` к `\n`, обрезают пробелы по краям заголовка и нормализуют теги `tags.normalize`; представление передаёт `ArticleForm` как введено | test_kb_articles*.py |
| 34 | Кнопки страницы версии статьи в корзине (R-1-a) | у статьи в корзине на странице версии нет ни «Восстановить эту версию», ни «Удалить версию» (у управляющего — только действия корзины на странице статьи) | test_kb_history_2.py |
| 35 | Порядок отказов `rubrics.move` (R-1-b) | `parent_self` → `parent_descendant` → `default_immovable` → `depth_exceeded` → `name_duplicate` | test_kb_rubrics*.py |
| 36 | Модуль исключений (R-1-b) | `KnowledgeError` и подклассы (`ArticleError`, `RubricError`, `TagError`, `FileError`, `CommentError` и др.) — в `apps/knowledge/services/__init__.py` (B-1) | все тесты `knowledge` |
| 37 | Соединение тестов миграции `seed` (R-1-b) | тесты вызывают `seed` на соединении `default` (соединение `migrate` не видит данных транзакции теста; у `crm_app` есть нужные права по умолчанию); сброс стенда — на `migrate` (A-4 для стенда в силе) | test_kb_access.py, test_kb_deploy.py |
| 38 | Где текст отказа поля (R-1-b) | внутри элемента `[data-error="<поле>"]` (элемент содержит текст сообщения) | все тесты форм |
| 39 | Проверка «нет ошибок подписчика» (R-2-a) | обязательна в тестах, которые выполняют обработчики шины событий `knowledge.*` (`comment_added`, `article_published`, `article_changed`): `caplog` без записей `ERROR` логгера `apps.core.events` | test_kb_comments.py, test_kb_articles.py, test_kb_notify*.py |
| 40 | Число запросов `list_for` (R-2-a) | `select_related("author", "author__photo")` — фото автора без запроса на каждого | test_kb_comments.py |
| 41 | Время новых записей (R-2-a) | службы ставят поля времени явно `timezone.now()` (`core.comments.add` — `created_at`, статьи, версии, вложения, связи, удаление в корзину); `default=` модели тестам не опора | test_kb_comments.py и др. |
| 42 | `store` и «после фиксации» (R-2-a) | `store` зовёт `core.tasks.enqueue_scan` напрямую (тот сам ставит задание после фиксации, `commit_mode="on_db_commit"`); тест: внутри `django_capture_on_commit_callbacks(execute=True)` до выхода задания в очереди нет, после выхода — есть | test_core_uploads.py |
| 43 | Строки главной (R-2-a) | строка «Новые и изменённые» и черновиков на главной — заголовок, рубрика, время правки; тегов на главной нет | test_kb_tags_home.py |
| 44 | `[data-field="state"]` в разделе «Статьи» карточки (R-2-b) | есть только у черновика (пометка «черновик»); у опубликованной статьи элемента нет | test_kb_tickets.py |
| 45 | Запись журнала при сбое части карточки (R-2-b) | одна запись `ERROR` логгера `apps.servicedesk`; `record.getMessage()` содержит ключ части и имя класса исключения, текста исключения нет | test_kb_tickets.py |
| 46 | Строка сотрудника и путь подразделения (T-5127) | `context["unit"]` — названия подразделений сотрудника через запятую (как колонка `unit` справочника); путь подразделения — названия всех предков от корня структуры через « / », без собственного названия (у узла верхнего уровня — пусто, A-18) | test_search_providers_2.py |
| 47 | Телефон «с +7 или 8» (T-5127) | в векторе сотрудника телефон есть как цифры (`79123456789`) и как цифры с ведущей `8` вместо `7` (`89123456789`); запросы `+79123456789`, `79123456789`, `89123456789` и начало номера находят сотрудника | test_search_providers_2.py |
| 48 | `/search/count/` на короткий или длинный запрос (R-3-b) | 200 с пустым фрагментом: поставщики не вызываются (как страница результатов, раздел 9.2); числа группы нет | test_search_pages.py |
| 49 | Граница «Показать ещё» (R-3-b) | поставщик выбирает `limit + 1` строк; кнопка «Показать ещё» (и признак «есть ещё») — только если строк больше `limit` (ровно 20 — кнопки нет); B-19 читается так | test_search_pages.py, test_search_providers*.py |
| 50 | Абзац 1.3 и З8 (R-3-b) | действует З8: тесты «стирает» и «не трогает» вызывают `apps.knowledge.stand.stand_reset()` напрямую; команду `e2e_reset_stand` — только тест «восстанавливает» (права и «Общее»); строка абзаца 1.3 «вызывает и функцию, и команду» читается с этой оговоркой | test_kb_deploy.py |
| 51 | Какая рубрика в тексте «Статья в рубрике «…»: Заголовок» (T-5148; **отменяет B-15**) | рубрика **подписки** получателя, через которую пришло уведомление (сценарий 9 п. 6 спеки: подписчик «Сети» при статье в подрубрике получает «Статья в рубрике «Сеть»»); если подписок на цепочке несколько — ближайшая к статье (самая глубокая); текст строится на каждого получателя отдельно | test_kb_notify.py, test_kb_notify_2.py, e2e/test_k09_notify.py |
| 52 | Проверка диффов T-5138 (t5138/review.md) | перечень T-5138 (раздел 14.5) дополняется: вид «Статья в рубрике по подписке» доступен всем (7.2), а `prefs.save` пишет снимок всех строк таблицы, поэтому правятся ещё `test_notify_prefs.py` (у сотрудника без прав в таблице — одна строка «по подписке», не ноль; снимок `matrix` в тесте сохранения — плюс `knowledge.rubric_subscription` с действующими значениями) и `test_notify_catalog_2.py` (снимок `matrix` — коды сервис-деска и `knowledge.rubric_subscription`; страница «Мои уведомления» — пять строк, у пятой название «Статья в рубрике по подписке» и модуль «База знаний»; флажков и ячеек push — пять). Сужения: в `test_sd_boundaries` проверяется только запись «Заявки» (`tickets`) servicedesk, записи `units`/`staff` — T-5130; имя `test_catalog_contains_eight_kinds_from_three_modules` не меняется (оно в подписанном TASKS-004); `coalesce` у видов `knowledge.*` в `test_notify_catalog.py` не проверяется (T-5121) | test_notify_prefs.py, test_notify_catalog_2.py, test_sd_boundaries.py, test_notify_catalog.py |
| 53 | Вложенность строк рубрик (R-A Q5, R-C В1, В3) | `[data-kb-tree]` (главная) и `[data-kb-rubrics]` (управление) — **плоский** список `li[data-rubric-id][data-depth]` в порядке обхода дерева (предок раньше потомков, братья — по названию без учёта регистра); `li` друг в друга не вкладываются; `data-depth` в обоих — 1–3 (корень — 1) | helpers_kb.py, test_k02, test_k07, test_k08, test_kb_rubrics*.py, test_kb_tags_home.py |
| 54 | Блоки «Мои черновики» и «Черновики» главной (R-A Q2, R-D 8, R-E 3) | порядок `updated_at DESC, id DESC`, не больше 20 строк, без «Показать ещё»; только что сохранённый черновик всегда в блоке | test_k01, test_k08, test_k11, test_kb_tags_home.py |
| 55 | Пустая рубрика в форме (R-A Q3; спека, сценарий 1 п. 2) | в `select[name=rubric]` первый пункт — пустой (`value=""`), на новой статье выбран он; пустое или несуществующее значение — отказ `rubric_missing` у поля `rubric` | helpers_kb.clear_rubric, test_k01, test_kb_articles*.py |
| 56 | Текст 404 статьи (R-A Q4; спека, сценарий 2 п. 7, FR-409) | ответ 404 на `/kb/<id>/` (нет статьи или чужой черновик) — страница с заголовком `h1` «Статья не найдена», одинаковая для обоих случаев (статья в корзине не-управляющему — 410 «Статья удалена», план) | test_k02 |
| 57 | Сброс стенда в круге (R-A Q1) | п. «Приёмка» раздела 1.3 выполняется прежними файлами круга (`test_d*`, `test_o01…` зовут `reset_stand_and_relogin`); `test_k01` своего сброса не делает; сброс внутри k-файлов — только где тест требует пустой базы (последний тест k02) | test_k01, test_k02 |
| 58 | Ссылка во внешнем сообщении (R-D Q4) | кнопка сообщения Telegram/MAX и адрес Web Push — только `/notifications/` (CONTRACT-004; `test_kb_notify_2.py` проверяет `PORTAL_URL + "/notifications/"`); адреса `/kb/<id>/` во внешнем канале нет | test_k09 |
| 59 | Замер предпросмотра 200 000 знаков в браузере (R-E Q1; решение 38 задач) | в приёмке меряется время от отправки запроса предпросмотра до получения ответа (`page.expect_response`), предел 1 с; появление метки в DOM — обычным ожиданием без отдельного предела; строгий замер рендера — серверный тест и T-5304 | test_k12 |
| 60 | Прямые вызовы читателем (R-E Q2, находки 2–3) | `POST /kb/links/`, `POST /kb/links/<id>/delete/`, `POST /kb/from-ticket/<N>/` читателю — 403 (10.7); `GET /kb/from-ticket/<N>/` — 405 любому (10.2: метод проверяется раньше права); тест зовёт их с существующей закрытой заявкой с решением и существующей связью (заводит редактор), чтобы порядок проверок не влиял; после всех отказов статьи с заголовком из попытки `POST /kb/new/` нет (проверка управляющим) | test_k11 |
| 61 | Состояние «проверяется» в приёмке (R-C находка 4, В4; решения 12, 36 задач) | удержать файл `pending` на стенде нечем: ветвь «проверяется» проверяется, если наблюдается (сразу после прикрепления, до следующего действия, состояние читать в момент проверки); обязательны конечное «чистый» и выдача после проверки; невыдачу `pending` строго проверяют серверные тесты (T-5113, T-5114) | test_k05 |
| 62 | Значение «по сроку» в журнале (R-D находка 6, Q2) | логическое `by_term` показывается журналом ядра как «да»/«нет» (факт `apps/core/services/audit_labels.py`); тест ночной очистки ждёт `по сроку:\s*да`, тест удаления навсегда — `по сроку:\s*нет` | test_k08 |
| 63 | CSP `img-src` (R-E Q4) | действует 1.2 (факт `settings`): `img-src 'self' data:` — внешних адресов нет, что и требует план (NFR-405 «без внешних адресов»); `data:` в разметке статьи не появляется — его убирает `render.sanitize` | test_kb_render.py, test_k12 |
| 64 | Выбор строки в подборе «Ссылка на статью» (R-B Q1; вопрос T-5143) | в `ul[data-kb-pick-results]` без `ticket` выбирается сама строка `li[data-article-id][data-title][data-url]` (клик по строке или Enter на ней); ссылок и кнопок внутри строки нет | test_k04, test_kb_tickets_2.py |
| 65 | `[data-field="linked-by"]` (R-B Q2) | `full_name` того, кто привязал, целиком (уволенный — с пометкой «(уволен)», как `person_name` ядра) | test_k04 |
| 66 | ПДн при сохранении черновика (R-B Q3) | предупреждения нет: шаг 6 плана действует для опубликованной статьи и для публикации; черновик сохраняется без проверки ПДн | test_k04, test_kb_pdn*.py |
| 67 | Подпись строки поиска (R-F, вопрос 3 T-5149; FR-439) | `input[name=q]` в шапке — `type="search"`, `aria-label="Поиск"` и `placeholder="Поиск"` | test_k10, test_search_pages.py |
| 68 | Стрелки в выдаче (R-F) | первая «стрелка вниз» выбирает первую строку окна (порядок документа, через группы); выбранная строка одна — `li[data-search-row][data-selected="true"]`; «вверх» на первой строке снимает выбор | test_k10 |
| 69 | Номера заявок №5, №15 сценария 10 п. 17 (R-F, вопрос 1 T-5149) | на общем стенде номер не выбрать: приёмка проверяет разбор `#N`, `N` на своих номерах и факт ответа `/tickets/N/` администратору для малых; буквальный пункт — в ручном проходе T-5301 | test_k10 |
| 70 | Когда уходит загрузка вложения (R-A находка 5; C-16) | `form[data-form="kb-attach"]` отправляется сама при выборе файла (`hx-trigger="change"`), кнопки отправки у формы нет; `button[data-action="kb-attach"]` «Вложить» (`type="button"`) открывает выбор файла (`input[name=file]`); приёмка ставит файл в поле и ждёт ответ `POST /kb/<id>/files/` | helpers_kb.try_attach_file, test_k05 |
| 71 | Где считаются векторы поиска (R-5207-1) | одна функция `apps/knowledge/services/vectors.py: refresh(article_ids) -> None` — одним `UPDATE` с параметрами: `search_head = setweight(to_tsvector('russian', title), 'A') || setweight(to_tsvector('russian', <теги через пробел>), 'B')`, `search_full = то же || setweight(to_tsvector('russian', left(plain, 100000)), 'C')` для опубликованных из списка, `NULL` — для черновиков и корзины; её зовут `kb_rerender` (T-5207), `articles.save/publish/restore`, переименование и слияние тегов (T-5208, T-5209); своего расчёта векторов в службах нет | T-5207, T-5208, T-5209 |
| 72 | `class` после второго фильтра `nh3` (R-5207-3; тест `test_render_second_nh3_filter…`) | атрибут `class` допустим на любом теге белого списка, но значение — только слова `kb-[a-z0-9-]+` (латиница), прочие слова удаляются, пустой `class` снимается; строка 6.1 о «`class` только на `div`, `span`, `th`, `td`» уточняется этим пунктом | T-5207 |
| 73 | Строка по номеру и «Показать ещё» у «Заявок» (T-5204, T-5202; уточняет п. 49 и 9.2) | у `SearchRow` последнее поле `pinned: bool = False`; поставщик выбирает `limit + 1` **основных** строк (`offset` считает только основные) и при `offset=0` и номере в запросе ставит над ними строку по номеру с `pinned=True` (на первой странице заявок у поставщика до `limit + 2` строк); сборка (`search.services`) делит строки на закреплённые и основные: показывает закреплённые и первые `limit` основных, «есть ещё» — если основных больше `limit`, следующий `offset` = `offset + limit`; тесты поставщиков (`test_search_providers*.py`) поправлены под п. 49 | T-5200, T-5202, T-5204, T-5205, T-5215, T-5217 |
| 74 | Уточнения пп. 36 и 71 (вопросы T-5209) | имена исключений — по таблице 5.1 (`ArticleError`, `RubricError`, `TagError`, `VersionError`, `FileRefused`, `SettingsError`); перечень п. 36 — пример, `FileError` и `CommentError` не нужны; в п. 71 «переименование и слияние тегов» — ошибка Opus: таких служб в плане нет, `vectors.refresh` зовут только `kb_rerender` и `articles.save/publish/restore` (T-5208) | T-5208, T-5209 |
| 75 | Подписка шины для видов `knowledge.*` (находка T-5208; строка 431 раздела 14.4) | `NotifyConfig.ready()` идёт раньше `KnowledgeConfig.ready()` (решение 3) и видов `knowledge.*` не видит; в конце `KnowledgeConfig.ready()` при `apps.is_installed("apps.notify")` вызывается `apps.notify.services.dispatch.subscribe_all()` (повторная подписка шиной игнорируется); импорт только служб `notify`, не моделей | T-5208, T-5213 |
| 76 | «Показать ещё» в списках базы знаний (T-5218) | кнопка стоит в последней строке списка (`li` или `tr`) с `hx-target="closest li"` / `"closest tr"` и `hx-swap="outerHTML"`: ответ подменяет эту строку строками следующей порции (и новой строкой с кнопкой, если есть ещё) — разметка списка остаётся верной; в выдаче поиска — по-прежнему `hx-target="this"` (тесты `test_search_pages.py`) | T-5218 |
| 77 | Учётки `LOAD_PLAIN` (C-15; находка T-5242) | роли «Сотрудник» в портале нет (встроенные — «Администратор портала», «Руководитель», «Сотрудник ИТ»); учётки без прав базы знаний и без «Все заявки» получают роль «Руководитель» (только `staff.view`) | T-5242 |
