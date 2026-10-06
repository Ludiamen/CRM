# Контракт имён тестов Этапа 2 среза 003 (T-3100…T-3152)

Тесты написаны до кода и задают имена, которых нет в PLAN-003. Реализация (Этап 3) берёт их
отсюда. Имена плана (модели и поля раздела «Модель данных», маршруты «Контрактов», коды
событий таблицы «Журнал», очереди `inbox` и `maintenance`, права `servicedesk.all` и
`servicedesk.manage`, шина `apps/core/events.py` и её события, четыре новые точки расширения,
`MailboxUnavailable`, `send_rendered`, `reconcile.for_users`, `tickets.create`,
`tickets.set_status`, `closing.reopen`, `attachments.accept`, задания `poll_mailbox`,
`process_inbound` и остальные из таблицы «Расписание») здесь не повторяются и не меняются,
кроме случаев, когда тест уточняет их форму (такие строки помечены «уточнение»). Имена
срезов 001 и 002 (`tests/CONTRACT.md`, `tests/CONTRACT-002.md`) не меняются: что меняется в
этих файлах вместе со срезом 003, перечислено в разделе 11 (перечень T-3138, п. 13).

Помощники тестов: `tests/support_servicedesk.py` (пишет T-3100, отдельной задачей после
контракта; фикстуры из него подключаются через `tests/conftest.py`, который правит та же
задача) и `tests/e2e/helpers_sd.py` (пишет T-3140; `reset_stand_and_relogin()` вызывает
`e2e_reset_stand` и заново создаёт администратора круга, запись круга в `helpers.ADMINS`
сбрасывается; читает письма в Mailpit по `[#N]` в
`Subject`, берёт `To`, `Cc`, `Reply-To`, `Auto-Submitted` через
`/api/v1/message/<id>/headers`, ищет письмо по шаблону; делает файлы для загрузки
`make_table(rows, fmt, delimiter)`: CSV и XLSX). В колонке «Тесты» стоят задачи T-31xx или
файлы, которые берут имя. Рабочие записи автора контракта лежат вне репозитория.

Части этого файла: шапка и разделы 1-5 и подраздел «A» раздела 15 — часть a; раздел 6 —
части b1 и b2; разделы 7-11 — часть c; разделы 12-14 — часть d.

Правила для всех тестов среза:
- пароли — только `secrets.token_urlsafe()` (помощник `factories.new_password()`, фикстура
  `password`); пароль ящика заявок — только из окружения (`os.environ["IMAP_PASSWORD"]`),
  в файлах, ответах и сообщениях об ошибках — только `***`;
- строка EICAR собирается из частей при запуске (`support_org.eicar_bytes()`), целиком в
  репозитории не лежит;
- постановка заданий в очередь (`scan_file`, `process_inbound`, письма заявки, порции
  периодических заданий) и всё, что идёт «после фиксации» (обработчики шины, стирание файлов,
  сброс кэша прав), проверяется внутри `with django_capture_on_commit_callbacks(execute=True):`
  (фикстура подключается параметром теста); обработчики шины сами запускаются на `on_commit`
  с `robust=True`, поэтому ошибка подписчика в таком блоке не поднимается в тест;
- имена кода среза 003 тесты импортируют внутри функций теста (или через `support.model`),
  а не на уровне модуля: сбор (`pytest --collect-only`) должен проходить до появления кода;
  `tests/support_servicedesk.py` на уровне модуля тоже не импортирует `apps.servicedesk`;
- тесты ходят по путям плана (раздел «Контракты»), а не по именам маршрутов;
- время (решение 5 задач): библиотек подмены часов нет, службы берут время из
  `django.utils.timezone.now()`, а тест сдвигает сохранённые отметки назад помощником
  `backdate(obj, field, days=0, *, hours=0, minutes=0)` (раздел 3.4; поля — перечень 3.4, в том
  числе `RequesterImport.created_at`). Фикстура `clock`
  из `tests/conftest.py` (она подменяет `timezone.now` через `mock.patch`; подтверждено
  чтением `tests/factories.py`, класс `Clock`) остаётся для тестов срезов 001 и 002; тесты среза
  003 её как правило не берут: подмена `now` не сдвигает отметки, записанные раньше, и расходится
  со временем Valkey и RQ. Исключение (решение Opus A1): тесты, где код читает час суток
  (нерабочее время, сценарий 13) и задания RQ не участвуют, задают «сейчас» фикстурой `clock`
  (только серверные тесты). Приёмка на стенде подмены часов не имеет (решение 12 задач,
  tasks.md): время она задаёт настройкой рабочей недели календаря среза 002
  (`WorkCalendar.work_weekdays`, `day_start`, `day_end`): «рабочее время» — все семь дней,
  00:00–23:59; «нерабочее» — сегодняшний день недели по Москве убран из рабочих; «год не
  загружен» — то же условие, но на текущий год нет строки `CalendarYear` (тест
  `test_d13_year_not_loaded_saturday_has_phrase_by_weekdays_only`);
- тесты команд, работающих через соединение `migrate` (`e2e_reset_stand`,
  `servicedesk_after_restore`), и тесты, которые правят таблицы под правами владельца,
  помечаются `pytest.mark.django_db(databases=["default", "migrate"])`, как
  `test_db_roles.py` и `test_org_audit.py`; `transaction=True` в этом наборе не работает
  (сброс таблиц требует прав владельца, `tests/conftest.py`). Данные для такой команды тест
  создаёт через то же соединение, которым команда читает; последовательность номеров заявок
  от транзакции теста не зависит (раздел 2);
- тест подменяет только точки из таблицы «Точки подмены» (раздел 3.5); других подмен нет.
  Разбор письма, отправка почты (Mailpit или локальный бэкенд Django), Valkey, RQ (`django_rq`),
  база и файловый том (`protected_root`) настоящие.

Разделы:
1. Среда запуска.
2. Модели и поля сверх плана.
3. Ядро: шина, точки расширения, файлы, права, помощники, точки подмены (3.5).
4. org: узлы работы, участники очереди, удаление узла, события доступа.
5. Почта: IMAP-адаптер и `FakeMailbox`, письма заявки.
6. Сервисы `servicedesk` — пишут части b1 и b2.
7. Задания RQ и ключи Valkey — пишет часть c.
8. Команды стенда и восстановление — пишет часть c.
9. Журнал и лента — пишет часть c.
10. Письма заявителю — пишет часть c.
11. Что меняется в `CONTRACT.md` и `CONTRACT-002.md` — пишет часть c.
12. Маршруты и поля форм — пишет часть d.
13. Зацепки разметки — пишет часть d.
14. Тексты сообщений — пишет часть d.
15. Вопросы к Opus (подразделы по частям: A, B, C, D).

## 1. Среда запуска

В колонке «Статус»: «есть» — уже сделано на Этапе 1 и описано по файлам (тест проверяет
факт); «Этап 3» — требование, которого в файлах ещё нет; «уточнение» — меняет значение
прежнего контракта; «T-3100» — пишет помощник теста (отдельная задача после контракта);
«есть (описание), код — T-3100» — среда уже есть, а код помощника ещё нет.

| Что | Статус | Требование | Тесты |
|---|---|---|---|
| Служба `dovecot` | есть | в `deploy/docker-compose.yml`: образ `dovecot/dovecot:2.4.5@sha256:43c14def08a57f25107593cbcf64a0a6fbae84a7b9de7aa038513c9b21e91914` (по дайджесту), `profiles: ["dev", "test"]`, порт `127.0.0.1:31143:31143` (внутри сети compose — 31143), `USER_PASSWORD: "{PLAIN}${IMAP_PASSWORD:-}"`, файл `./dovecot/99-test.conf` смонтирован `:ro` на `/etc/dovecot/conf.d/99-test.conf`, содержимое файла — ровно `auth_allow_cleartext = yes` и `ssl = no`; проверки здоровья нет (в образе нет оболочки) | test_sd_deploy::test_dovecot_in_dev_and_test_profiles_pinned_by_digest, test_dovecot_config_mounted_read_only_and_port_set (T-3135) |
| Служба `test` и `dovecot` | есть | `depends_on` службы `test` содержит `dovecot` с `condition: service_started` (не `service_healthy`); службы `worker`, `worker-mail`, `worker-inbox`, `scheduler`, `backup` без ключа `profiles` | test_sd_deploy::test_test_service_depends_on_dovecot_started_and_worker_services_have_no_profile (T-3135) |
| Вход в Dovecot у живых тестов | есть (описание), код — T-3100 | параметры входа живых тестов берутся из `settings.IMAP_HOST`, `IMAP_PORT`, `IMAP_SECURITY`, `IMAP_USER` и из `os.environ["IMAP_PASSWORD"]`: служба `test` читает `deploy/.env` (`env_file`), где `tools/make_dev_env.py` ставит `IMAP_HOST=dovecot`, `IMAP_PORT=31143`, `IMAP_SECURITY=none`, `IMAP_USER=tickets`, `IMAP_FOLDER=INBOX`, `SERVICEDESK_MAILBOX=tickets@stand.test`; тест не читает файл `.env` сам. Помощник `live_mailbox_ready(timeout=30.0) -> None` повторяет вход (`imaplib`, раз в секунду) до 30 с и при неудаче поднимает `AssertionError` с текстом без пароля (решение 3); его же вызывает тест готовности | test_sd_imap_live (T-3109): test_live_mailbox_readiness_waits_by_login_retry_up_to_30_seconds, test_live_login_with_env_password_error_text_has_no_password |
| Вход в Dovecot у приёмки | T-3140 | приёмка идёт с хоста: `imaplib.IMAP4("127.0.0.1", 31143)` без шифрования (`E2E_IMAP_HOST`, `E2E_IMAP_PORT` — переопределение), пользователь `tickets` (`E2E_IMAP_USER`), пароль — `os.environ["IMAP_PASSWORD"]`; `IMAP_HOST` из `deploy/.env` не подставляется (имя `dovecot` с хоста не разрешается); письма кладутся командой `APPEND` в `INBOX` стенда (ту, что опрашивает `poll_mailbox`); помощник `helpers_sd.append_mail(raw) -> None` не читает `settings` и не удаляет чужие письма | T-3140 |
| Своя папка у живых тестов | T-3100 | фикстура `live_mailbox` создаёт на Dovecot папку `live-<token_urlsafe(6)>` (команда `CREATE` под учётной записью ящика), кладёт в `settings.IMAP_FOLDER` это имя на время теста, и по завершении удаляет папку (`DELETE`); папка `INBOX` стенда живыми тестами не трогается (решение 12 задач, п. 11.12). Объект фикстуры: `.folder`, `.append(raw: bytes, *, flags=()) -> int` (команда `APPEND`; UID берётся поиском `UID SEARCH` после неё, а не из `APPENDUID`: у Dovecot `APPENDUID` первого письма даёт неверный UIDVALIDITY), `.recreate() -> None` (закрыть соединения, `DELETE` и `CREATE` папки: UIDVALIDITY меняется), `.uidvalidity() -> int` | test_sd_imap_live: все пять тестов |
| Служба `clamav` | уточнение | как в CONTRACT-002 § 1, плюс в `environment` службы строка `CLAMD_CONF_AlertEncryptedArchive: "yes"`; комментарий о запрете `CLAMD_CONF_*` в compose касается только смонтированных файлов (план, «Интеграции»); `FRESHCLAM_CONF_*` по-прежнему нет | test_sd_deploy::test_clamav_service_enables_alert_encrypted_archive (T-3135); живое подтверждение — T-3120 |
| `CLAMAV_TIMEOUT` | Этап 3, уточнение | значение по умолчанию 120 (сейчас 30): в `environment` служб `web`, `worker`, `worker-mail`, `worker-inbox`, `test` — `"${CLAMAV_TIMEOUT:-120}"`; в `config/settings.py` — `env.int("CLAMAV_TIMEOUT", default=120)`; в `deploy/.env.example` — закомментированная строка `# CLAMAV_TIMEOUT=120` | test_sd_deploy::test_clamav_timeout_120_in_all_services_and_settings_default (T-3135); правка прежних тестов: test_deploy_files::test_clamav_env_defaults_in_compose_commented_in_env_example, test_clamav_adapter::test_host_port_timeout_from_environment_with_defaults (T-3138) |
| Служба `worker` | Этап 3, уточнение | команда `rq worker -c config.rq_settings --with-scheduler files` (только очередь `files`), `deploy: replicas: 2`, том `protected` на тот же путь, что у `web` (`/app/protected`), без `container_name` | test_sd_deploy::test_worker_service_runs_only_files_queue_with_two_replicas, test_all_workers_have_protected_volume_and_with_scheduler, test_workers_have_no_container_name (T-3135); правка test_worker_listens_files_before_mail_and_mounts_protected (T-3138); правка test_worker_runs_with_scheduler_and_cron_service_present (T-3138, п. 5): проверка `mail` переносится на `worker-mail` (`mail`, `maintenance`), `inbox` — на `worker-inbox`, `--with-scheduler` у каждой из трёх |
| Служба `worker-mail` | Этап 3 | та же команда с очередями `mail maintenance` (в таком порядке), том `protected`, без `container_name`, без `profiles` | test_sd_deploy::test_worker_mail_service_runs_mail_and_maintenance_queues (T-3135) |
| Служба `worker-inbox` | Этап 3 | та же команда с очередью `inbox`, том `protected`, без `container_name`, без `profiles` | test_sd_deploy::test_worker_inbox_service_runs_inbox_queue (T-3135) |
| Пароль владельца схемы у новых служб | Этап 3 (решение Opus C9) | в `environment` служб `worker-mail` и `worker-inbox` — `DATABASE_MIGRATE_URL: ""`, как у `worker`; из новых служб значение получает только `backup`; тест `test_owner_credentials_only_in_one_shot_migrate_service` проверяет только `web`, `worker`, `scheduler`, поэтому не ломается и правка T-3138 не нужна | test_sd_deploy (T-3135): проверка дописывается в тест, который выберет исполнитель T-3135 из своих; нового имени теста контракт не задаёт |
| Служба `scheduler` | есть | одна копия (без `replicas`); расписание — `config/cron.py`, таблица ниже | test_sd_deploy::test_cron_has_eight_new_jobs_with_expected_queues_and_poll_mailbox_every_minute (T-3135) |
| Служба `backup` | Этап 3 | образ `postgres:17-alpine`; `entrypoint` и `command` запускают `crond -f`; `TZ: Europe/Moscow`; файл `deploy/backup/crontab` содержит строку `30 1 * * *` и вызов `/backup/backup.sh` (01:30 по Москве); смонтированы: `./backup:/backup:ro`, том `backups` на `/backups`, тома `protected` и `media` только для чтения (`:ro`); из `.env` в `environment` — только `DATABASE_MIGRATE_URL` (без `env_file`, решение Opus C9); без `profiles` | test_sd_deploy::test_backup_service_on_postgres_alpine_with_crond_and_moscow_tz, test_backup_mounts_protected_and_media_read_only (T-3135) |
| Скрипт `deploy/backup/backup.sh` | Этап 3 | содержит `pg_dump -Fc -d "$DATABASE_MIGRATE_URL"` (решение Opus C9; файл `crm-ГГГГ-ММ-ДД.dump` в `/backups`), две упаковки `tar` в `protected-ГГГГ-ММ-ДД.tgz` и `media-ГГГГ-ММ-ДД.tgz` и удаление копий старше 14 дней: в тексте есть и `-mtime +14`, и `-delete` (тест ищет их отдельными подстроками, порядок и остальные ключи `find` не проверяются); пароля в тексте нет | test_sd_deploy::test_backup_script_dumps_archives_volumes_and_deletes_older_than_14_days (T-3135) |
| nginx, форма и ответ | Этап 3, уточнение | в `nginx.conf` и `nginx.prod.conf`: общий `client_max_body_size 6m;` в `http` остаётся; `location = /request/` и `location ~ ^/tickets/(new/\|[0-9]+/reply/)$` (в обоих файлах — обычная вертикальная черта: `\|` в таблице — экранирование Markdown) — каждый с `client_max_body_size 55m;` и повторёнными `proxy_pass`, `proxy_set_header` и `proxy_read_timeout` из `location /` (они не наследуются) | test_sd_deploy::test_nginx_request_form_location_has_55m_and_repeats_proxy_directives, test_nginx_executor_forms_regex_location_has_55m_and_repeats_proxy_directives, test_nginx_prod_config_matches_dev_for_new_locations (T-3135; сравнивает наборы директив и значения новых `location` в двух файлах, кроме значения `X-Forwarded-Proto`: `$scheme` в dev, `$portal_proto` в prod; `location /` там же — образец); правка test_nginx_body_size_6m_and_protected_location_internal_with_headers (T-3138) |
| nginx, выдача файлов | Этап 3 | в обоих файлах перед `location /protected/` — `location /protected/attachments/` с `alias /srv/protected/attachments/;` и `location /protected/inbound/` с `alias /srv/protected/inbound/;`; в каждом: `internal;`, `default_type application/octet-stream;`, `add_header X-Content-Type-Options "nosniff" always;`, директивы `add_header Cache-Control` нет; общий `location /protected/` и фото не меняются | test_sd_deploy::test_nginx_protected_attachments_and_inbound_internal_with_octet_stream_and_nosniff, test_nginx_protected_attachment_locations_have_no_cache_control (T-3135) |
| Переменные `IMAP_*`, `SERVICEDESK_MAILBOX` | есть | `config/settings.py` читает при запуске: `IMAP_HOST` (str, по умолчанию `""`), `IMAP_PORT` (int, по умолчанию 993 — значение выбрал исполнитель T-3001, план его не называет), `IMAP_SECURITY` (str, по умолчанию `"ssl"`; допустимы `ssl`, `starttls`, `none`), `IMAP_USER` (`""`), `IMAP_PASSWORD` (`""`), `IMAP_FOLDER` (`"INBOX"`), `IMAP_TIMEOUT` (int, 30), `SERVICEDESK_MAILBOX` (`""`). Адаптер и службы читают `settings` при каждом вызове, а не при импорте, поэтому тест подменяет их фикстурой `settings`. В `deploy/.env.example`: `IMAP_PASSWORD=***` (незакомментирована), остальные, в том числе `# SERVICEDESK_MAILBOX=tickets@example.com`, — закомментированные строки `# ИМЯ=значение` | test_sd_deploy::test_env_example_has_new_variables_with_placeholders_only (T-3135); правка `test_stack.py` (`SECRET_ENV_NAMES`) — T-3138, п. 12; test_sd_mailbox |
| Очереди RQ | есть | `RQ_QUEUES["inbox"]` и `RQ_QUEUES["maintenance"]` в `config/settings.py` (`URL: VALKEY_URL`, `DEFAULT_TIMEOUT: 120`); Valkey тестов — база 15, чистится `valkey_clean`, очереди между тестами пусты. Тест находит задание так: `[j for j in django_rq.get_queue("inbox").jobs if j.func_name == "apps.servicedesk.tasks.process_inbound"]` | test_sd_deploy::test_rq_queues_include_inbox_and_maintenance (T-3135); test_sd_mailbox, test_sd_inbound |
| `config/cron.py` | Этап 3 | восемь новых заданий через `register(..., name=...)`; строки `cron` — по UTC (время по Москве минус 3 часа), у каждого явный `job_timeout`; прежние шесть строк срезов 001 и 002 не меняются (таблица ниже); правка T-3138, п. 11 (`test_cron_registers_preview_purge_quarantine_cleanup_and_scan_requeue`): `== 6` → `== 14` (`test_deploy_files.py:383`); у восьми новых заданий очередь не `mail`; проверки трёх заданий среза 002 и `apps.org.tasks`/`apps.core.tasks` остаются | test_sd_deploy::test_cron_has_eight_new_jobs_with_expected_queues_and_poll_mailbox_every_minute, test_cron_times_are_utc_for_moscow_schedule, test_cron_every_new_job_has_explicit_job_timeout_from_plan_table_old_six_unchanged (T-3135) |
| `deploy/RESTORE.md` | Этап 3 | шаги по порядку (план, «Восстановление из копии»): остановить `web`, `worker`, `worker-mail`, `worker-inbox`, `scheduler`; `pg_restore --clean --if-exists` от `crm_owner`; тома `protected` и `media` из копий одной ночи; `python manage.py servicedesk_after_restore` через службу `migrate`; запустить службы | test_sd_deploy::test_restore_md_describes_plan_steps_in_order (T-3135) |

Расписание (`config/cron.py`), имя — значение `name=` в `register`; функция — в
`apps/servicedesk/tasks.py`, ставит задание в очередь `queue_name`:

| Имя задания | Очередь | Строка cron (UTC) | По Москве | `job_timeout`, с |
|---|---|---|---|---|
| `poll_mailbox` | `inbox` | `* * * * *` | каждую минуту | 600 |
| `requeue_inbound` | `inbox` | `*/5 * * * *` | каждые 5 минут | 300 |
| `autoclose` | `maintenance` | `5 * * * *` | каждый час в :05 | 600 |
| `reconcile_assignees` | `maintenance` | `25 * * * *` | каждый час в :25 | 600 |
| `purge_inbound` | `maintenance` | `10 23 * * *` | 02:10 | 600 |
| `anonymize_tickets` | `maintenance` | `20 23 * * *` | 02:20 | 600 |
| `purge_requester_previews` | `maintenance` | `30 23 * * *` | 02:30 | 300 |
| `purge_orphan_files` | `maintenance` | `50 23 * * *` | 02:50 | 600 |

Прежние шесть заданий (`purge_login_history`, `purge_expired_links`, `purge_expired_sessions`,
`purge_import_previews`, `purge_quarantine`, `requeue_pending_scans`) тест находит по `name=` и
сравнивает их строки с CONTRACT-002 § 1 и срезом 001. Задание `process_inbound` ставится не по
расписанию: `job_timeout` 300 с и `Retry(max=5, interval=[60, 300, 900, 3600, 10800])`.
Остальное о заданиях (ключи Valkey, порции) — раздел 7.

### Образцы T-3002

Каталог `backend/tests/fixtures/servicedesk/`; описание и контрольные суммы — `SOURCE.md`
там же. Помощник `support_servicedesk.sample(name) -> bytes` читает файл по имени (как
`support_org.calendar_fixture`), неизвестное имя — `FileNotFoundError`. Тест задаёт имя
вложения сам: у файлов нейтральные расширения, чтобы проверялось содержимое. Пароль архивов
нигде не хранится и тестам не нужен.

| Имя образца | Свойство | Тесты |
|---|---|---|
| `enc_zip_zipcrypto.zip` | ZIP с паролем ZipCrypto: `flag_bits & 1` у элемента | T-3119 test_password_protected_zip_flag_bit_and_aes_rejected; T-3120 test_live_clamd_encrypted_zip_reports_heuristics_encrypted_zip |
| `enc_zip_aes.zip` | ZIP с паролем WinZip AES: бит 1 и метод 99 | T-3119 test_password_protected_zip_flag_bit_and_aes_rejected |
| `enc_zip_second_entry.zip` | первый элемент без пароля, второй с паролем | T-3119 test_password_protected_zip_flag_bit_and_aes_rejected (шифрование у любого элемента) |
| `plain.zip` | ZIP без пароля | T-3119 test_archives_without_password_accepted; T-3120 test_live_clamd_plain_zip_is_clean |
| `nested_enc_zip.zip` | обычный ZIP, внутри `inner.zip` с паролем: своя проверка заголовков не видит | T-3119 test_scan_heuristics_encrypted_rejects_as_password_archive_and_erases_file (принят, при подменённом `scan_found("Heuristics.Encrypted.Zip")` отклонён); T-3120 test_live_clamd_nested_encrypted_zip_reports_heuristics_encrypted |
| `enc_rar5_data.rar`, `enc_rar5_headers.rar` | RAR5: зашифрованы данные или заголовки | T-3119 test_password_protected_rar4_rar5_and_7z_rejected |
| `enc_rar4_data.rar`, `enc_rar4_headers.rar` | RAR4 (настоящие файлы библиотеки rarfile): флаги 0x0004 и 0x0080 | T-3119 test_password_protected_rar4_rar5_and_7z_rejected |
| `enc_7z_plain_header.7z`, `enc_7z_encrypted_header.7z` | 7z с паролем; кодек AES виден в заголовке | T-3119 test_password_protected_rar4_rar5_and_7z_rejected |
| `enc_7z_compressed_header.7z` | 7z, пароль на данных, заголовок сжат: своя проверка не видит | T-3119 test_scan_heuristics_encrypted_rejects_as_password_archive_and_erases_file; T-3120 test_live_clamd_encrypted_7z_with_compressed_header_reports_heuristics_encrypted |
| `plain_rar4.rar`, `plain_rar5.rar`, `plain_7z_plain_header.7z`, `plain_7z_compressed_header.7z` | архивы без пароля | T-3119 test_archives_without_password_accepted; T-3120 test_live_clamd_plain_7z_is_clean (`plain_7z_plain_header.7z`) |
| `exe_pe.bin` | Windows PE: `MZ`, по `e_lfanew` `PE\0\0` | T-3119 test_executable_signatures_and_type_by_content_rejected |
| `exe_elf.bin` | ELF64 | T-3119 test_executable_signatures_and_type_by_content_rejected |
| `exe_macho64_le.bin`, `exe_macho32_be.bin` | Mach-O 64 и 32 | T-3119 test_executable_signatures_and_type_by_content_rejected |
| `exe_macho_fat.bin` | универсальный Mach-O (`CAFEBABE`, 2 архитектуры) | T-3119 test_signature_edge_cases_mz_without_pe_cafebabe_ole_doc_and_jar |
| `exe_script.bin` | текст с `#!/bin/sh` в начале | T-3119 test_executable_signatures_and_type_by_content_rejected |
| `exe_msi.bin` | OLE с CLSID установщика `000C1084-0000-0000-C000-000000000046` | T-3119 test_signature_edge_cases_mz_without_pe_cafebabe_ole_doc_and_jar |
| `exe_jar.zip` | ZIP с `META-INF/MANIFEST.MF` | T-3119 test_signature_edge_cases_mz_without_pe_cafebabe_ole_doc_and_jar |
| `not_exe_dos_mz.bin` | DOS `MZ` без `PE\0\0`: не исполняемый | T-3119 test_signature_edge_cases_mz_without_pe_cafebabe_ole_doc_and_jar |
| `not_exe_mz_text.txt` | текст на буквы `MZ`: не исполняемый | T-3119 test_signature_edge_cases_mz_without_pe_cafebabe_ole_doc_and_jar |
| `not_exe_java_class.bin` | класс Java (`CAFEBABE`, версия 52): не Mach-O | T-3119 test_signature_edge_cases_mz_without_pe_cafebabe_ole_doc_and_jar |
| `not_exe_ole_doc.bin` | OLE с CLSID Word: старый `.doc`, не MSI | T-3119 test_signature_edge_cases_mz_without_pe_cafebabe_ole_doc_and_jar |
| `not_exe_odf_manifest.zip` | ZIP документа ODF (`META-INF/manifest.xml`): не JAR | T-3119 test_signature_edge_cases_mz_without_pe_cafebabe_ole_doc_and_jar |
| `image.png`, `image.jpg` | картинки 32 на 24, чистые вложения и встроенные картинки | T-3119 test_inline_image_is_attachment_and_checked; T-3108 |
| собирается тестом | ZIP 20 МБ без сжатия: `zipfile.ZIP_STORED`, содержимое `os.urandom` (помощник `big_zip(megabytes=20) -> bytes`) | T-3120 test_live_clamd_scan_of_20mb_zip_faster_than_clamav_timeout; T-3119 |

## 2. Модели и поля сверх плана

Метка приложения — `servicedesk`; модели берутся через `support.model("servicedesk.Ticket")` и
так далее, таблицы называются по умолчанию (`servicedesk_ticket`, `servicedesk_ticketentry`,
`servicedesk_inboundmail` …). Все внешние ключи на `org.Unit` и `core.User` объявлены с
`related_name="+"` (сервис-деск не добавляет обратных связей к ядру и `org`), поэтому тесты
ищут `Ticket.objects.filter(assignee=user)`, `filter(queue_id=unit.pk)`, а не `user.<имя>_set`.
Значения `choices` тест сравнивает как строки; в модели они объявлены вложенными `TextChoices`
с теми же значениями (имена классов ниже). Русские подписи — из плана и спеки; если там их нет,
подпись выбрана контрактом (помечено «подпись контракта»). Отказ базы в ограничении уникальности
тест ловит как `django.db.IntegrityError` внутри `with transaction.atomic():`; отказ сервиса
(код причины) — раздел 6.

### 2.1. Общие значения справочников

| Имя | Что | Тесты |
|---|---|---|
| `Status.Kind` | `NEW="new"` («новая»), `IN_PROGRESS="in_progress"` («в работе»), `WAITING="waiting"` («ждёт ответа заявителя»), `CLOSED="closed"` («закрыта»); те же значения у `Ticket.kind` | T-3103, T-3110, T-3111, T-3116 и далее везде |
| `name_key` справочников | у `Category`, `Priority`, `Complexity`, `Status`, `Source`, `ClientUnit`: `unique=True`, значение — `support_org.name_key(name)` (без лишних пробелов, строчными, «ё» как «е»); поле заполняет сервис, а модель при `save()` пересчитывает его сама из `name`, если оно пусто | T-3103 test_name_required_and_unique_case_yo_and_spaces_insensitive_in_every_dictionary |
| `order`, `archived` | `order` — целое по умолчанию 0; `archived` — `False` по умолчанию; у `ClientUnit` поля `order` нет | T-3103 |
| `str(obj)` справочников | `name` | T-3103 |

### 2.2. Модели, значения и ограничения

Числа `order` начальных строк выбраны контрактом (в плане и спеке задан только порядок
перечисления).

| Имя | Что | Тесты |
|---|---|---|
| `ServiceDeskSettings` | одна строка, `pk=1`, создаётся миграцией: `domains` (`JSONField`, список строк, по умолчанию `[]`), `default_queue` (`None`), `default_priority` («Средняя»), `autoclose_days=7`, `reopen_days=7`, `form_hourly_limit=10`, `retention_years=3`, `inbound_retention_days=30`, `updated_at`; границы (проверяет сервис настроек, раздел 6): 1-90, 1-90, 1-1000, 1-10, 1-365; адрес ящика в модели не хранится, берётся из `settings.SERVICEDESK_MAILBOX` | T-3102 test_initial_terms_and_limits_defaults_7_7_10_3_30_and_ranges_validated, test_fresh_install_no_queues_no_domains_mail_and_form_not_accepted, test_mailbox_address_readonly_in_settings |
| `Queue` | `unit` (`OneToOneField`, `related_name="+"`), `created_at`, `created_by`; на пустой базе строк нет; `Queue.objects.filter(unit_id=...)` — отметка узла | T-3101, T-3102 |
| `Category` | поля плана; `is_system` и `on_form` по умолчанию `False`; `queue` пустой только у системной «Другое» (начальная строка миграции: `is_system=True`, `on_form=True`, `queue=None`, `order=100`) | T-3103 test_initial_category_other_default_queue_shown_on_form, test_category_other_not_deleted_not_archived_and_has_no_own_queue |
| `Priority` | начальные строки: «Низкая» (`order=10`), «Средняя» (`20`), «Высокая» (`30`); «по умолчанию» хранит `ServiceDeskSettings.default_priority` («Средняя»), отдельного флага у модели нет | T-3103 test_initial_criticalities_low_medium_high_with_default, test_default_criticality_cannot_be_archived_or_deleted |
| `Complexity` | начальные строки: «Лёгкий» (`order=10`, `name_key="легкий"`), «Средний» (`20`), «Высокий» (`30`) | T-3103 test_initial_complexity_levels_easy_medium_high |
| `Status` | поля плана; `is_default=False`, `system_code=""`; `UniqueConstraint(fields=["kind"], condition=Q(is_default=True), name="servicedesk_status_one_default_per_kind")`; начальные строки (имя, вид, по умолчанию, `system_code`, `order`): «Новая» `new` да `""` 10; «В работе» `in_progress` да `""` 20; «Ждёт ответа заявителя» `waiting` да `""` 30; «Решена» `closed` да `""` 40; «Не может быть решена» `closed` нет `""` 50; «Закрыта автоматически» `closed` нет `autoclosed` 60. `system_code` допускает `""` и `"autoclosed"` | T-3103 test_initial_statuses_with_kinds_and_default_marks, test_default_mark_moves_within_kind_in_one_transaction, test_system_auto_closed_status_renamed_but_not_archived_or_deleted_and_any_status_renamable |
| `Source` | `system_code` допускает `""` (ручной источник), `"mail"` («Почта»), `"form"` («Форма»); начальные строки: «Почта» `mail` 10, «Форма» `form` 20, «Телефон» `""` 30, «Лично» `""` 40; системные в ручном выборе не предлагаются | T-3103 test_initial_sources_mail_form_system_phone_in_person_manual, test_system_sources_mail_and_form_not_in_manual_choice_not_archived_not_deleted_but_renamable |
| `ClientUnit` | `name` до 150; пустой на новой базе | T-3103 test_client_units_unique_without_case_archived_not_offered_flat_list |
| `Requester` | `email` хранится строчными (сохраняет сервис; повтор адреса в другом регистре — `IntegrityError`), `Requester.Origin`: `TABLE="table"` («таблица»), `TICKET="ticket"` («заявка»); `related_name` у `Ticket.requester` — `"tickets"` | T-3105, T-3129 test_requester_record_from_ticket_without_other_tickets_deleted_with_audit_reason |
| `RequesterImport` | `RequesterImport.FileFormat`: `CSV="csv"`, `XLSX="xlsx"`; `RequesterImport.State`: `PREVIEW="preview"` («предпросмотр»), `DONE="done"` («выполнена»); `summary` — словарь с ключами `added`, `updated`, `unchanged`, `errors`, `deleted` (целые; сверх этих — ключи 6.23: `origin_changed`, `not_loaded`, в предпросмотре `would_delete`); `new_units` — список строк; ключи строк `rows` — раздел 6 (`requester_import`) | T-3128, T-3129 test_purge_requester_previews (T-3130) |
| `Ticket` | поля плана; `number` — `PositiveIntegerField(unique=True)` без автозначения (его выдаёт `tickets.create` из последовательности); `kind` — `Status.Kind`; `last_message_from` — `Ticket.MessageFrom`: `REQUESTER="requester"` («заявитель»), `STAFF="staff"` («исполнитель»), пусто допустимо (`""` — писем ещё нет); по умолчанию: `assigned_once=False`, `search_len=0`, `waiting_since=None`, `closed_at=None`, `closed_by=None`, `resolution=""`, `anonymized_at=None`, `consent_at=None`; `requester_email`, `requester_name` (до 255), `client_unit` (своё значение заявки, `ForeignKey("servicedesk.ClientUnit", PROTECT, null=True, related_name="+")`); связи: `Ticket.requester` → `related_name="tickets"`, `Ticket.previous` → `related_name="continuations"` (заявка-продолжение, `SET_NULL`); справочники `PROTECT`, `related_name="+"` | T-3105, T-3110, T-3117, T-3129 |
| `Ticket.number`, последовательность | последовательность базы `servicedesk_ticket_number` (`RunSQL`, начало с 1, шаг 1); первая заявка получает номер 1. Тест читает значение через соединение `migrate`: помощник `sequence_state() -> tuple[int, bool]` — `(last_value, is_called)` из `SELECT last_value, is_called FROM servicedesk_ticket_number`; помощник `set_sequence(value: int, *, is_called: bool = True) -> None` — `SELECT setval('servicedesk_ticket_number', %s, %s)` там же (`value`, `is_called`); тест «с 1» зовёт `set_sequence(1, is_called=False)` и затем ждёт номера 1, 2, 3; после сброса стенда состояние — `(1, False)`. Откат транзакции теста последовательность не возвращает | T-3105, T-3136 test_after_restore_shifts_sequence_1000_past_max_of_sequence_and_number, test_after_restore_twice_never_lowers_sequence_and_never_repeats_a_number |
| `Ticket.search`, индекс поиска | `SearchVectorField(null=True)`; индекс GIN `servicedesk_ticket_search_gin` (29 знаков, предел Django — 30); тест находит его так: `with connection.cursor() as cur: constraints = connection.introspection.get_constraints(cur, "servicedesk_ticket")` и среди значений есть запись с `index=True`, `type == "gin"`, `columns == ["search"]` (имя в тесте не сравнивается); план запроса не проверяется (решение 16) | T-3134 test_ticket_search_column_has_gin_index |
| Остальные индексы `Ticket` | имена: `servicedesk_ticket_queue_kind` (`queue`, `kind`), `servicedesk_ticket_asg_kind`, `servicedesk_ticket_unassigned` (частичный `queue` при `assignee IS NULL AND kind <> 'closed'`), `servicedesk_ticket_waiting` (частичный `waiting_since` при `kind = 'waiting'`), `servicedesk_ticket_closed` (частичный `closed_at` при `kind = 'closed' AND anonymized_at IS NULL`), `servicedesk_ticket_created`, `servicedesk_ticket_last_msg`; тесты имена не сравнивают, имена выбраны для миграции | T-3134 (косвенно: число запросов) |
| `TicketParticipant` | `ticket` — `related_name="participants"`; `UniqueConstraint(fields=["ticket", "email"], name="servicedesk_participant_ticket_email_uniq")`; `name=""` по умолчанию; снятый участник — строка с `removed_at` | T-3107 test_removed_participant_mail_creates_new_ticket, T-3108 |
| `TicketEntry` | `ticket` — `related_name="entries"`; `TicketEntry.Kind`: `INCOMING="incoming"` («письмо»), `REPLY="reply"` («ответ»), `COMMENT="comment"` («комментарий»), `EVENT="event"` («событие»); `TicketEntry.SendState`: `WAITING_FILES="waiting_files"` («ждёт проверки файлов», подпись контракта), `QUEUED="queued"` («поставлен в очередь», подпись контракта), `NOT_SENT="not_sent"` («не отправлен», подпись контракта), у остальных видов пусто; `event` — код события (полный перечень кодов — раздел 9, часть c); `data=dict` по умолчанию; `wait_flag=False`; `inbound` — `related_name="entries"` у `InboundMail`; `mail` (`SET_NULL`, `related_name="+"`); `resent_from` — `related_name="resends"`; индекс `servicedesk_entry_ticket_at_id` (`ticket`, `at`, `id`) | T-3114, T-3115, T-3118 |
| `Attachment` | `ticket` — `related_name="attachments"`; `entry` — `related_name="attachments"`; `file` — `SET_NULL`, `related_name="+"`; `inline=False`; `Attachment.Rejected`: `NONE=""` (принято), `TOO_BIG="too_big"` («больше 20 МБ»), `MAIL_TOO_BIG="mail_too_big"` («письмо больше 50 МБ»), `EXECUTABLE="executable"` («исполняемый файл»), `ENCRYPTED="encrypted"` («архив с паролем»); словарь `Attachment.REJECT_TITLES` — код → подпись (в сообщении «файл «…» не принят: <причина>» стоит подпись); у не принятого `file` пуст, остаются `name`, `size`, `rejected`; при `Heuristics.Encrypted.*` строка `StoredFile` удаляется в той же транзакции, `Attachment.file` пуст (решение Opus A2); подписи `REJECT_TITLES` — подписи контракта (решение Opus A7) | T-3119 test_rejected_attachment_keeps_only_name_size_reason_and_is_listed_in_card_and_confirmation |
| `InboundMail` | `InboundMail.Status`: `RECEIVED="received"` («получено», подпись контракта), `PROCESSED="processed"` («обработано», подпись контракта), `WAITING_SETUP="waiting_setup"` («ждёт настройки», подпись контракта), `ERROR="error"` («ошибка»); `InboundMail.Outcome`: `CREATED="created"` («создана заявка»), `APPENDED="appended"` («добавлено в заявку»), `REOPENED="reopened"` («открыта заново»), `REJECTED_DOMAIN="rejected_domain"` («отклонено: чужой домен»), `REJECTED_SELF="rejected_self"` («отклонено: письмо с адреса ящика заявок»), `AUTO="auto"` («автоматическое письмо»), `WAITING_SETUP="waiting_setup"` («ждёт настройки очереди по умолчанию»), `PARSE_ERROR="parse_error"` («ошибка разбора»); пока итога нет — `outcome=""`; `status` по умолчанию `received`; `attempts=0`, `raw_deleted=False`, `last_error=""`; `ticket` — `related_name="inbound_mails"`; `UniqueConstraint(fields=["uidvalidity", "uid"], name="servicedesk_inbound_uidvalidity_uid_uniq")` (повтор пары — `IntegrityError`); `message_id` с индексом; файл письма — `PROTECTED_ROOT / "inbound" / f"{id}.eml"` (тест читает его по этому пути; `id` — номер строки); поля плана (plan.md:351): `internal_date` (`DateTimeField`, `INTERNALDATE` сервера), `received_at` (время забора порталом, `timezone.now()` при записи), `size`, `processed_at` | T-3106, T-3107, T-3130 |
| `MailboxState` | одна строка (`pk=1`), на пустой базе строки нет; строка создаётся при первом удачном подключении или при первой же ошибке опроса (`last_error`, `last_poll_at`; решение Opus RB2-5, к следующей версии плана: у плана «строки нет» — единственный признак первого подключения); `uidvalidity` и `last_uid` — `BigIntegerField(null=True)`, до первого подключения `None`; `connected_at`, `last_poll_at`, `last_ok_at` могут быть пустыми; `last_error=""`; доступ — `MailboxState.objects.get(pk=1)` | T-3106 |
| `StoredFile` (ядро) | уточнение CONTRACT-002 § 2: `StoredFile.Purpose.ATTACHMENT = "attachment"` («вложение») рядом с `PHOTO`; `owner` — `null=True`, `on_delete=PROTECT`, `related_name="stored_files"` (`related_name` и `PROTECT` как раньше; `null=True` — новое); `content_type` — `CharField(max_length=255)`; для вложения `owner=None`, `purpose="attachment"`; значения `status` и остальные поля — как в срезе 002; миграция ядра только схемы | T-3119 test_accepted_file_stored_pending_in_incoming_with_owner_none, test_stored_file_content_type_up_to_255_chars; правка T-3138 (CONTRACT-002 § 2: «`StoredFile.purpose` — единственное значение») |
| `MailMessage` (почта) | новые поля (миграция только схемы, прежние строки получают пустые значения): `cc` (`TextField`, `blank=True`, адреса через запятую), `reply_to` (`CharField(max_length=254, blank=True)`), `message_id` (`CharField(max_length=255, blank=True, db_index=True)`), `references` (`TextField`, `blank=True`, через пробел), `auto_submitted` (`CharField(max_length=16, blank=True)`, значения `""`, `"auto-replied"`, `"auto-generated"`; класс `MailMessage.AutoSubmitted`: `REPLIED`, `GENERATED`), `related_ref` (`CharField(max_length=64, blank=True, db_index=True)`; формат значения — раздел 10), `attachments` (`JSONField`, `default=list`: список `str(StoredFile.id)`); тело письма не хранится | T-3118, T-3129 test_delivery_log_to_cc_attachments_and_attempt_errors_cleared, T-3132 |
| Начальные данные миграции `servicedesk` | порядок: права `servicedesk.all` («Все заявки») и `servicedesk.manage` («Настройка сервис-деска») у «Администратора портала»; статусы, критичности, уровни сложности, источники, категория «Другое» и строка настроек — как в таблицах выше; миграция работает под владельцем схемы (`schema_editor.connection.alias`), как `org/0002_initial_data.py` | T-3103, T-3102, T-3101 test_all_tickets_and_manage_rights_only_for_portal_admin_after_install |
| `ANONYMIZED` | значение «обезличено» для `author_email`, `author_name`, `requester_email`, `requester_name`, `MailMessage.to` после обезличивания; тест сравнивает со строкой-литералом «обезличено» | T-3129 |

## 3. Ядро: шина, точки расширения, файлы, права, помощники

### 3.1. Шина событий `apps/core/events.py`

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `subscribe` | `subscribe(name: str, handler: Callable[..., None]) -> None`: добавляет обработчик события `name`; та же функция второй раз игнорируется (повторный `ready()`); обработчик вызывается как `handler(**data)`, ключи `data` — только имена из таблицы событий ниже | T-3132 |
| `publish` | `publish(name: str, **data) -> None`: для каждого подписчика в порядке подписки регистрирует `transaction.on_commit(..., robust=True)`; обработчик выполняется внутри своего `transaction.atomic()`; имя события не проверяется; без подписчиков ничего не делает; вне транзакции обработчики идут сразу | T-3132 test_publish_runs_handlers_only_after_commit, test_publish_rolled_back_transaction_calls_no_handler, test_publish_without_subscribers_does_nothing, test_each_handler_runs_in_own_transaction |
| ошибка подписчика | исключение обработчика не откатывает действие, опубликовавшее событие, и не мешает остальным подписчикам; запись об ошибке попадает в лог (тест: в `caplog.records` есть запись уровня `ERROR`; логгер не проверяется); записи базы, сделанные упавшим обработчиком, откатываются | T-3132 test_handler_error_is_logged_and_does_not_roll_back_action, test_handler_error_does_not_block_other_handlers |
| `subscribers` | `subscribers(name: str) -> list`: копия списка обработчиков | T-3132 |
| `unsubscribe` | `unsubscribe(name, handler) -> None`: убирает обработчик, повтор безвреден | T-3132 |
| `clear`, `empty` | `clear() -> None` очищает все подписки; `empty()` — контекстный менеджер: на время блока подписок нет, прежние возвращаются при выходе (как `extensions.empty`) | T-3132 |
| фикстура `bus` | в `tests/conftest.py`: тело теста идёт внутри `events.empty()`; объект фикстуры `Bus`: `.listen(*names) -> None` подписывает записывающий обработчик на эти события, `.calls(name) -> list[dict]` — данные каждого вызова по порядку (после выполнения обратных вызовов фиксации), `.all() -> list[tuple[str, dict]]`. Тесты, которым нужны настоящие подписчики `servicedesk`, фикстуру не берут. Фикстура `bus_spy`: те же `.listen`, `.calls`, `.all`, но прежние подписки остаются; записывающие обработчики снимаются при выходе из теста (в ядре — `events.unsubscribe(name, handler)`) | `bus` (подписчиков нет, `events.empty()`) берут тесты, которым подписчики `servicedesk` мешают: публикацию ядром и `org` проверяют без них (T-3132 и такие тесты T-3102, T-3104); `bus_spy` (подписчики остаются, вызовы записываются) — тесты, которым нужны и настоящие подписчики, и `Bus.calls` (в T-3104 — как минимум `test_removed_assignee_leaves_feed_event_journal_entry_and_bus_event` и `test_handler_runs_only_in_on_commit_callbacks`); остальные тесты фикстуру шины не берут — подписчики включены `ready()` |
| `access.changed` | данные `user_ids: list[int] \| None` (`None` — «все»); публикуют `permissions.forget_users(user_ids)` (после регистрации сброса кэша: обратные вызовы `on_commit` идут в порядке регистрации) и `permissions.forget_all()` (`user_ids=None`), а также `org` — раздел 4. `user_ids` в событии — отсортированный список без повторов; пустой список событие не публикует; `forget_all` публикует `user_ids=None`. Уточнение `forget_users`: `forget_users(user_ids, *, publish: bool = True)`; с `publish=False` событие не публикуется (так зовёт `move_unit`, раздел 4; решение Opus A5) | T-3132 test_forget_users_publishes_access_changed_with_user_ids, test_forget_all_publishes_access_changed_with_none, test_access_changed_handler_sees_new_permissions_after_cache_reset |
| `mail.failed` | данные `mail_id: int` (номер `MailMessage`; ключ не называется `message_id`, чтобы не путать с заголовком), `related_ref: str`; публикует `apps.integrations.mail.tasks.on_failure` после последней неудачи, когда статус письма стал `failed`; у писем без `related_ref` (`""`) событие тоже публикуется | T-3118, T-3132 |
| `servicedesk.ticket_created`, `servicedesk.assignee_changed`, `servicedesk.reply_received`, `servicedesk.ticket_closed` | данные у всех четырёх: `number: int`, `queue_id: int`, `assignee_before_id: int \| None`, `assignee_after_id: int \| None` (у `ticket_created` и `reply_received` до и после равны текущему ответственному, `assignee_before_id` у новой заявки — `None`; у `ticket_closed` — ответственный на момент закрытия); публикуют модули `servicedesk` (перечень по 6.13). Подписчиков в срезе нет | T-3132 test_servicedesk_events_carry_ticket_number_queue_and_assignees, test_four_servicedesk_events_are_published_by_ticket_services |

### 3.2. Точки расширения `apps/core/extensions.py`

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `POINTS` | уточнение CONTRACT-002 § 5: кортеж из тринадцати имён в таком порядке: `menu_items`, `role_sources`, `role_usage`, `audit_labels`, `staff_directory`, `card_sections`, `day_marks`, `home_notices`, `stand_reset`, `unit_usage`, `file_purposes`, `mail_renderers`, `login_links`. `org` по-прежнему регистрируется ровно в девяти первых (число и список для `org` не меняются); `servicedesk` — в `menu_items`, `unit_usage`, `file_purposes`, `mail_renderers`, `login_links`, `audit_labels`, `card_sections`, `stand_reset`, `home_notices` (функции модулей `apps.servicedesk…`, `func.__module__` начинается с `apps.servicedesk`) | T-3132 test_extension_points_include_unit_usage_file_purposes_mail_renderers_login_links; T-3138 test_org_registers_all_nine_extension_points (имя прежнее, смысл — «из девяти первых») |
| `unit_usage` | `func(unit_id: int) -> str \| None`: текст причины отказа удалить узел или `None`; `org.delete_unit` зовёт функции по порядку регистрации и берёт первый непустой ответ; `servicedesk` отвечает «к узлу привязаны заявки сервис-деска» (любые, в том числе закрытые), затем «узел — очередь сервис-деска: сначала снимите отметку» | T-3102, T-3132 |
| `file_purposes` | `func() -> list[FilePurpose]`; `FilePurpose` — `dataclass` из `apps.core.extensions` с полями `purpose: str` (значение `StoredFile.purpose`, у среза 003 — `"attachment"`), `still_waiting: Callable[[StoredFile], bool]` («ещё ждёт»: у вложения — есть строка `Attachment` с этим файлом и файл в статусе `pending`), `clean: Callable[[StoredFile], list[pathlib.Path]]` («чисто»: переносит файл `incoming/<id>` → `attachments/<id>`, ставит статус `clean`, `scanned_at`; возвращает пути, которые нужно стереть после фиксации), `found: Callable[[StoredFile, str], list[pathlib.Path]]` («найдено», второй аргумент — сигнатура: карантин `quarantine/<id>` с событием ленты и журналом `ticket.attachment_quarantined`, а для `Heuristics.Encrypted.*` — стирание файла, удаление строки `StoredFile` (`Attachment.file` становится пустым) и `Attachment.rejected="encrypted"` (решение Opus A2); тоже возвращает пути для стирания). Обработчики вызываются внутри транзакции под `select_for_update` строки `StoredFile`; ошибка обработчика откатывает транзакцию и идёт наружу | T-3119, T-3132 |
| `mail_renderers` | `func() -> list[MailRenderer]`; `MailRenderer` — `dataclass` с полями `prefix: str` (у `servicedesk` — `"ticket."`) и `render: Callable[[MailMessage, dict], Rendered]`; `Rendered` — `NamedTuple` из `apps.core.extensions` с полями `body: str` и `attachments: list[tuple[str, pathlib.Path]]` (имя вложения и путь файла в томе `protected`). Рендерер получает строку `MailMessage` и словарь `job.meta["context"]`, зовётся в момент отправки | T-3118 test_deliver_renders_body_from_database_at_send_time, test_send_rendered_queues_deliver_job_and_rejects_unregistered_prefix |
| `login_links` | `func() -> list[dict]`: у каждого элемента ключи `url` и `title`; ядро собирает их в порядке регистрации и кладёт в контекст страницы входа под ключом `login_links` (список; без регистраций — пустой, страница входа такая же, как после среза 002); зацепки разметки — раздел 13 | T-3121 test_request_page_opens_without_login_and_without_menu, T-3132 |
| `menu_items` | уточнение CONTRACT-002 § 5: у описания пункта, кроме `permissions`, `url`, `title`, `icon`, `order`, могут быть необязательные ключи `visible: Callable[[User], bool]` (пункт виден, если есть одно из прав из `permissions` **или** `visible(user)` истинна) и `badge: Callable[[User], int \| None]`; `badge` зовётся только у видимого пункта; каждая из функций зовётся не больше одного раза за вызов `menu_for` (контекст `shell` зовёт `menu_for` один раз за запрос). «Заявки» — `order` 5; «Сервис-деск» — `order` 65 (решение 10 задач) | T-3132 test_menu_item_visible_shows_item_without_permissions, test_menu_item_badge_called_only_for_visible_item_once_per_request, test_menu_item_without_visible_and_badge_behaves_as_before |
| `permissions.menu_for` | уточнение CONTRACT-002 («ровно `url`, `title`, `icon`, `order`»): элемент словаря содержит эти четыре ключа и, только если у описания есть функция `badge`, ещё ключ `badge` (результат функции: целое или `None`). Без `servicedesk` ни у одного пункта ключа `badge` нет, поэтому `test_core_without_registered_extensions_behaves_as_slice_001` не меняется | T-3132, T-3138 |
| `context.shell` | уточнение: элемент `context["menu"]` содержит ключ `badge` тогда и только тогда, когда он есть у элемента `menu_for` (значение передаётся как есть, `None` тоже); остальные ключи — как в срезе 002; зацепка разметки счётчика — раздел 13 | T-3132, T-3114 |
| сброс реестров | как в T-2116 среза 002: `with extensions.empty():` или фикстура `no_extensions`; внутри — меню только из пунктов ядра, `login_links` пусты, `unit_usage` не отказывает, `file_purposes` не знает назначения `attachment` (`scan_file` для вложения выходит без изменений), `mail_renderers` пусты (`send_rendered` с префиксом `ticket.` отказывает `ValueError`); тест берёт также `events.empty()` (фикстура `bus` или `with events.empty():`): подписчики шины фикстура `no_extensions` не снимает | T-3132 test_without_servicedesk_registrations_core_and_org_behave_as_slice_002 |
| границы модулей | тест читает исходники: в `apps/core/**` и `apps/org/**` нет строки `apps.servicedesk`; в `apps/servicedesk/**` нет `from apps.org.models`, `import apps.org.models`, `from apps.org import models` (службы `apps.org.services` разрешены) | T-3132 test_core_and_org_do_not_import_servicedesk, test_servicedesk_does_not_import_org_models |

### 3.3. Файлы, диспетчер итога проверки, права

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `files.attachment_path` | `attachment_path(stored: StoredFile) -> pathlib.Path` в `apps/core/services/files.py`: по статусу `pending` — `PROTECTED_ROOT/"incoming"/str(id)`, `clean` — `PROTECTED_ROOT/"attachments"/str(id)`, `quarantine` — `PROTECTED_ROOT/"quarantine"/str(id)` | T-3119 |
| диспетчер `core.tasks.scan_file` | уточнение CONTRACT-002 § 3: `scan_file(file_id: str) -> None`. Нет строки — выход. Назначение `photo` — прежний путь без изменений. Другое назначение — ищется `FilePurpose` с таким `purpose` в точке `file_purposes`; нет такого или `still_waiting(stored)` ложно — выход без изменений. Затем `clamav.services.scan(path)` (путь — `attachment_path`); `ScanUnavailable` — как у фото (`attempts + 1`, `last_error`, исключение наружу, повтор по тем же `Retry`); результат — в транзакции под `select_for_update` строки, повторная проверка `still_waiting`, затем `clean(stored)` или `found(stored, signature)`; возвращённые пути стираются `files.remove_paths` после выхода из транзакции. Владелец не блокируется (у вложения его нет). Постановка и повторы — как у фото (`enqueue_scan`, `requeue_pending_scans`) | T-3119 test_scan_clean_moves_file_to_attachments_and_makes_it_downloadable, test_scan_infected_goes_to_quarantine_with_feed_event_and_audit, test_clamav_unavailable_ticket_created_attachment_waits_and_job_retries, test_pending_and_quarantined_not_downloadable_requeue_picks_pending |
| `permissions.permissions_of` | уточнение: `permissions_of(user, *, fresh: bool = False)`; при `fresh=True` права считаются из базы заново, кэш `perms:<id>` не читается и не пишется | T-3104 test_rights_read_without_cache_by_fresh_flag |
| `permissions.users_with` | `users_with(code: str) -> list[User]`: неуволенные записи с этим правом (по кэшу прав), по `full_name`, затем `id` | T-3101 test_eligible_assignees_queue_people_plus_all_holders_without_dismissed, test_all_tickets_right_makes_employee_participant_of_every_queue |
| `table_file` | `apps/core/services/table_file.py` — описан в 6.23 (общий для загрузок срезов 002-003) | T-3137, T-3204 |
| `PERMISSIONS_003` | в `tests/support_servicedesk.py`: `PERMISSIONS_003 = ("servicedesk.all", "servicedesk.manage")`; названия в `core.Permission.title`: «Все заявки» и «Настройка сервис-деска»; у «Администратора портала» после установки — `PERMISSIONS + PERMISSIONS_002 + PERMISSIONS_003` (двенадцать кодов), у «Руководителя» и «Сотрудника ИТ» ни одного из двух; прежние `support.PERMISSIONS` и `support.PERMISSIONS_002` не меняются | T-3101 test_all_tickets_and_manage_rights_only_for_portal_admin_after_install; T-3138 test_three_new_permissions_and_initial_distribution, test_three_builtin_roles_with_initial_permissions |

### 3.4. Помощники времени и подмен (общие для тестов среза)

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `backdate` | `backdate(obj, field: str, days: int = 0, *, hours: int = 0, minutes: int = 0) -> None` в `support_servicedesk`: сдвигает сохранённое значение поля назад на этот срок (`getattr(obj, field) - timedelta(...)`; пустое значение — от `timezone.now()`), пишет `type(obj).objects.filter(pk=obj.pk).update(...)` без `save()` (поля `auto_now` и сигналы не трогаются) и обновляет значение в `obj`. Допустимые поля: `Ticket.waiting_since`, `closed_at`, `created_at`, `last_message_at`; `InboundMail.received_at`; `MailboxState.last_ok_at`; `StoredFile.created_at`; `RequesterImport.created_at`; помощник работает с любой моделью и полем даты | T-3110, T-3111, T-3117, T-3129, T-3130, T-3106, T-3128 test_unconfirmed_preview_purged_after_a_day |
| `scan_clean`, `scan_found`, `scan_unavailable` | `scan_clean(monkeypatch) -> list`, `scan_found(monkeypatch, signature="Eicar-Signature") -> list`, `scan_unavailable(monkeypatch) -> list`: подменяют `apps.integrations.clamav.services.scan`; список — вызовы (пути); как `support_org` | T-3119, T-3112… |
| `sample`, `big_zip`, `eicar_bytes` | `sample(name) -> bytes` (образцы T-3002), `big_zip(megabytes: int = 20) -> bytes`; `eicar_bytes` берётся из `support_org` | T-3119, T-3120 |
| `make_queue` | `make_queue(unit=None, *, created_by=None, using: str = "default")`: отметка узла; без `unit` создаётся новый узел (`support_org.make_unit()`; при `using` не по умолчанию — `_unit_on`, см. строку «`using` у помощников»); `unit` — узел или `Queue`; повторный вызов для того же узла возвращает ту же строку; `created_by` по умолчанию — первый пользователь или новый сотрудник; `created_at` — «сейчас». дополнение 1 (T-3100, помощник), 2026-10-06 | T-3101, T-3102, T-3103, T-3104, T-3110 и далее |
| `configure_servicedesk` | `configure_servicedesk(*, domains: Sequence[str] \| None = None, default_queue=None, using: str = "default", **fields)`: правит строку `pk=1` через ORM, не через сервис (без журнала); `domains` приводятся к строчным; `default_queue` — узел или `Queue` (`None` — не менять); прочие поля — как есть. дополнение 1 (T-3100, помощник), 2026-10-06 | T-3102, T-3107, T-3108, T-3110, T-3111 |
| `make_category` | `make_category(name: str \| None = None, *, queue=None, default_assignee=None, on_form: bool = False, order: int = 0, archived: bool = False, using: str = "default")`: несистемная категория; `queue` — узел или `Queue`, без него создаётся очередь; `name_key` ставит помощник. дополнение 1 (T-3100, помощник), 2026-10-06 | T-3103, T-3110, T-3123 |
| `make_requester` | `make_requester(email: str \| None = None, *, full_name: str = "", client_unit=None, origin: str = "ticket", using: str = "default")`: адрес хранится строчными, без адреса — `factories.new_email("req")`; `created_at` — «сейчас». дополнение 1 (T-3100, помощник), 2026-10-06 | T-3105, T-3122, T-3128, T-3129 |
| `make_ticket` | `make_ticket(*, queue=None, requester=None, kind: str = "new", number: int \| None = None, using: str = "default", **over)`: заявка через ORM, не через `tickets.create` (последовательность не расходуется); `number` — следующий за наибольшим; справочники — начальные строки (критичность «Средняя», статус по умолчанию вида `kind`, источник `mail`); `created_at` и `last_message_at` ставятся в «сейчас» (решение Opus V2; тест сдвигает их `backdate`); `over` перекрывает любое поле, при `status` без `kind` вид берётся из статуса. дополнение 1 (T-3100, помощник), 2026-10-06 | T-3105, T-3110, T-3111, T-3117, T-3129 и далее |
| `make_entry` | `make_entry(ticket, kind: str = "comment", *, author=None, text: str = "", using: str = "default", **over)`: элемент ленты через ORM; `at` — «сейчас»; для `incoming` без автора адрес и имя берутся у заявителя заявки. дополнение 1 (T-3100, помощник), 2026-10-06 | T-3114, T-3115, T-3118 |
| `make_participant` | `make_participant(ticket, email: str \| None = None, *, name: str = "", removed_by=None, removed_at=None, using: str = "default")`: участник из копии; с `removed_by` без `removed_at` дата — «сейчас» (снятый); `added_at` — «сейчас». дополнение 1 (T-3100, помощник), 2026-10-06 | T-3107, T-3108, T-3116 |
| `make_inbound` | `make_inbound(*, uidvalidity: int = 1000, uid: int \| None = None, from_email: str \| None = None, using: str = "default", **over)`: строка входящего письма через ORM; файла `protected/inbound/<id>.eml` не создаёт (тест кладёт его сам); `uid` по умолчанию — сквозной счётчик процесса; `received_at` — «сейчас». дополнение 1 (T-3100, помощник), 2026-10-06 | T-3106, T-3112, T-3129, T-3130, T-3136 |
| `ticket_mails` | `ticket_mails(ticket) -> list`: письма заявки по `related_ref == "ticket:<Ticket.id>"` (6.17), по возрастанию `id`. дополнение 1 (T-3100, помощник), 2026-10-06 | T-3118 и тесты писем заявки |
| `mail_text` | `mail_text(message, context: dict \| None = None) -> str`: тело письма, которое отдаёт `letters.render(message, context).body`; контекст по умолчанию — `{"ticket_id", "entry_id": None, "after_hours": None}`; код среза берётся лениво. дополнение 1 (T-3100, помощник), 2026-10-06 | T-3118 |
| `sequence_state`, `set_sequence` | как в строке 210 (`Ticket.number`, последовательность); файл — `support_servicedesk.py`; тест, который их вызывает, помечен `pytest.mark.django_db(databases=["default", "migrate"])`. дополнение 1 (T-3100, помощник), 2026-10-06 | T-3105, T-3136 |
| `using` у помощников | у всех `make_*` и `configure_servicedesk` есть ключ `using` (имя соединения, по умолчанию `"default"`; `"migrate"` — раздел 8.4); `backdate` его не имеет. При `using` не по умолчанию фабрики создают вложенные узлы сами на том же соединении (внутренняя `_unit_on`: `path`, `depth`, `name_key` как у `support_org.make_unit`; корень — строка миграции) и пользователей не создают: `created_by` у `make_queue` и `queue` у `make_category` и `make_ticket` передаёт тест, иначе `ValueError` «через migrate передайте <поле>»; другие поля с пользователем (`author`, `removed_by`, `default_assignee`) — переданный объект. Тесты команд через `migrate` (T-3136) создают данные только фабриками `support_servicedesk` с `using="migrate"`, без `support_org.make_unit` и `support.make_employee`: иначе проверка внешних ключей в конце теста на соединении `migrate` не увидит узлов и пользователей из транзакции `default` и упадёт. дополнение 1 (T-3100, помощник), 2026-10-06 (решение Opus VS-1) | T-3136 |
| `build_mail` (байты) | письмо — переводы строк CRLF, как хранит Dovecot (длина байтов = `RFC822.SIZE`); повтор адресных заголовков (`To`, `Cc`, `Reply-To`, `Bcc`) разрешён. дополнение 1 (T-3100, помощник), 2026-10-06 | T-3109 и тесты размера |
| не интерфейс | `LiveMailbox.create/delete`, `FakeImap.instances`, `Bus.detach`, `SAMPLES_DIR` — внутреннее; одна `FakeImap.factory(...)` на тест. дополнение 1 (T-3100, помощник), 2026-10-06 | - |

### 3.5. Точки подмены

Тест подменяет только точки из этой таблицы (`monkeypatch.setattr`, `monkeypatch.setitem`,
`monkeypatch.delitem`); других
подмен нет. Функции, которые подменяют, зовутся через имя модуля (`imap.connect()`, а не
`from … import connect`), иначе подмена не сработает; шаги разбора письма `process` зовёт через
словарь `intake.STEPS` (решение Opus V-9).

| Точка | Модуль и имя | Чем подменяют | Тесты |
|---|---|---|---|
| проверка файла на вирусы | `apps.integrations.clamav.services.scan` (как в срезе 002) | помощники `scan_clean`, `scan_found(signature)`, `scan_unavailable` из `support_servicedesk` (они вызывают те же `support_org._patch_scan`); живые тесты T-3120 не подменяют ничего | T-3119, T-3112… |
| фабрика соединения IMAP-адаптера | `apps.integrations.mail.imap.connect` (решение 4; раздел 5) | объект `FakeMailbox`; фикстура `fake_mailbox` вызывает `install_fake_mailbox(monkeypatch, settings, fake=None) -> FakeMailbox`; живые тесты T-3109 не подменяют ничего | test_sd_mailbox, T-3107, T-3108, T-3136 (остальные тесты пути письма) |
| классы `imaplib` и контекст защиты | `apps.integrations.mail.imap.imaplib.IMAP4_SSL`, `.IMAP4`, `apps.integrations.mail.imap.ssl.create_default_context` | `monkeypatch.setattr(imap.imaplib, "IMAP4_SSL", FakeImap.factory(...))` (так же `IMAP4`), `monkeypatch.setattr(imap.ssl, "create_default_context", ...)`; двойник `FakeImap` (5.2); настоящий `imap.connect()`; только тесты адаптера | test_sd_mailbox::test_adapter_security_modes_ssl_starttls_with_verifying_context_and_none, test_uidvalidity_taken_from_select_not_status, test_mailbox_opened_read_only_examine_nothing_flagged_or_deleted, ответ не `OK` на выбор папки |
| учётная запись и соединение с clamd | `apps.core.services.accounts.create_user`; `socket.create_connection` в `apps.integrations.clamav.client` | как в срезе 002 (T-2109 и тесты загрузки сотрудников); срез 003 новых мест не добавляет | тесты загрузки сотрудников среза 002 |
| запись файла письма | `apps.servicedesk.services.mailbox.write_raw` (6.15) | `monkeypatch.setattr(mailbox, "write_raw", raising)`, функция поднимает `OSError` | test_sd_mailbox::test_file_write_error_rolls_back_and_same_uid_retried |
| ошибка чтения заголовков | `apps.servicedesk.services.mail_parse.sender_of`, как её видит `mailbox.headers_of` (6.15) | `monkeypatch.setattr(mailbox.mail_parse, "sender_of", raising)`; `headers_of` глотает любую ошибку | test_sd_mailbox::test_header_read_error_does_not_stop_poll_fields_empty |
| шаги разбора письма | `parse` — `apps.servicedesk.services.mail_parse.parse`; `checks` — `intake.classify`; `link` — `intake.find_ticket`; `ticket` — `tickets.create` (письмо без связи; у связанного — `tickets.add_incoming`); `attachments` — `attachments.accept`; `finish` — `intake.STEPS["finish"]` (6.16; `STEPS` — словарь всех шагов) | `monkeypatch.setitem(intake.STEPS, "<шаг>", raising)` для любого шага, по одному шагу за раз (решение Opus V-9: элементы `STEPS` — функции шагов `intake`, которые зовут названные слева функции) | test_sd_intake::test_error_on_any_step_rolls_back_marks_parse_error_last_error_step_and_class_only |
| одна заявка группового действия | `apps.servicedesk.services.assignment.assign` (6.8, `bulk`) | `monkeypatch.setattr(assignment, "assign", writes_then_raises_servicedesk_error)`: пишет часть данных, затем поднимает `ServiceDeskError` | test_sd_assignment_2::test_group_each_ticket_in_own_savepoint |
| соединение с базой `migrate` | `django.db.connections.databases` (8.4) | `monkeypatch.delitem(connections.databases, "migrate")` | T-3136 test_after_restore_uses_migrate_connection |
| недоступный Valkey у порога формы | `apps.core.services.valkey.conn` (6.19; `register_hit` ловит `redis.exceptions.RedisError`) | `monkeypatch.setattr(valkey, "conn", raising)`, функция поднимает `redis.exceptions.ConnectionError`; `caplog` ждёт запись `WARNING` | test_sd_form::test_valkey_down_form_works_without_limit_and_logs_warning |
| `DataError` при записи поиска | `apps.servicedesk.services.search.write_vector(ticket_id, parts)` — запись вектора поиска (6.21) | `monkeypatch.setattr(search, "write_vector", raising)`, функция поднимает `django.db.DataError`; `index` и `rebuild` зовут её через имя модуля `search` | test_sd_search::test_search_dataerror_message_saved_not_in_search_len_set_to_limit |
| сбой строки загрузки заявителей | `apps.servicedesk.services.requester_import.apply_row(row, *, actor)` — запись одной строки подтверждения (6.23) | `monkeypatch.setattr(requester_import, "apply_row", raising_for_one_email)`: поднимает ошибку только для строки с одним адресом (`row["email"]`), для остальных зовёт настоящую функцию; `confirm` зовёт её через имя модуля | T-3128 test_confirm_each_valid_row_in_own_savepoint |
| сбой одной заявки при обезличивании | `apps.servicedesk.services.retention.anonymize_one` (6.24) | `monkeypatch.setattr(retention, "anonymize_one", fails_for_one_id)`; `anonymize_batch` находит функцию через имя модуля, а не через локальную ссылку | T-3129 test_failure_of_one_ticket_does_not_roll_back_others |
| чтение файла таблицы | `apps.core.services.table_file.read` (6.23) | шпион: `monkeypatch.setattr(table_file, "read", spy)`, запись аргументов вызова (`max_bytes`, `max_rows`, `max_parts`, `max_unpacked`, `texts`) и вызов настоящей функции; `org.staff_import` зовёт её через имя модуля | T-3137 test_org_calls_core_reader_with_own_limits_and_texts |

## 4. org: узлы работы, участники очереди, удаление узла, события доступа

Функции живут в `apps/org/services/structure.py`, форма возврата — как у `heads_of` и
`units_of` (классы `PersonRef`, `UnitRef` из `apps/org/services/refs.py`).

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `structure.work_units_of` | `work_units_of(user) -> frozenset[int]`: номера узлов, где человек состоит (в том числе совместителем), и всех узлов, вложенных в узлы, где он руководитель или заместитель; родитель узла, где человек участник, в набор не входит; уволенный и не участник — `frozenset()`; читает дерево и членства не больше чем двумя запросами; работает по текущей структуре без кэша | T-3101 test_work_units_of_*, test_access_changes_with_next_request_after_transfer |
| `structure.queue_people` | `queue_people(unit_id: int) -> list[PersonRef]`: прямые участники узла и руководители и заместители всех вышестоящих узлов, без повторов и без уволенных, по `full_name` (при равных — по `id`); не больше двух запросов; несуществующий узел — `[]` | T-3101 test_queue_people_members_plus_upper_heads_and_deputies_unique_sorted_without_dismissed |
| `structure.delete_unit` | уточнение CONTRACT-002 § 4: после проверок `root_protected` и `not_empty` (порядок — решение Opus A3) зовёт точку `unit_usage`; первый непустой ответ `reason` — `OrgError(code="in_use", message=f"Узел нельзя удалить: {reason}.")`; тест читает `exc.code == "in_use"` и `reason in exc.message`; узел при отказе остаётся, журнал не пишется. Второй рубеж — `PROTECT` у `Ticket.queue` и `Queue.unit` (`django.db.models.ProtectedError`) | T-3102 test_delete_unit_with_tickets_including_only_closed_refused_with_reason, test_delete_queue_unit_without_tickets_refused_unmark_first, test_delete_empty_unit_passes_and_protect_guards_ticket_queue_and_queue_unit |
| тексты отказов | `reason`, который даёт `servicedesk` в `unit_usage`: «к узлу привязаны заявки сервис-деска» и «узел — очередь сервис-деска: сначала снимите отметку» (дословно из плана, без точки) | T-3102 |
| `membership.set_marks` | уточнение: после записи журнала публикует `events.publish("access.changed", user_ids=ids)`, где `ids` — отсортированный список тех, у кого отметка (руководитель или заместитель) появилась или исчезла: `(было_с_отметкой ^ стало_с_отметкой)` по узлу; если такой нет (смена между головой и заместителем или повтор без изменений), событие не публикуется (решение Opus A4); кэш прав не сбрасывается (отметка прав не даёт) | T-3132 test_set_marks_publishes_access_changed; T-3104 test_marks_change_removes_assignee_who_lost_head_or_deputy_mark |
| `structure.move_unit` | уточнение: кэш прав сбрасывается как раньше, но `forget_users(user_ids, publish=False)`, а событие публикует сам `move_unit` одно, после вызова `forget_users` (обратные вызовы `on_commit` идут в порядке регистрации): `user_ids` — отсортированный список участников поддерева (как раньше) плюс руководители и заместители прежних вышестоящих узлов, которые не являются руководителем или заместителем ни одного вышестоящего узла нового места (человек исключается, если отметка у него есть хотя бы в одном узле цепочки от нового родителя до корня; plan.md:173-179); перенос в того же родителя — без события (решение Opus A5) | T-3132 test_move_unit_publishes_access_changed_with_former_upper_heads; T-3104 test_unit_move_removes_assignee_who_was_head_of_former_upper_units |
| `access.changed` от прочих действий | увольнение, перевод, удаление из узла, смена ролей узла, личных ролей и прав роли — через `forget_users` и `forget_all` (раздел 3.1), отдельных вызовов в `org` не добавляется | T-3104 test_transfer_removes_*, test_dismissal_removes_*, test_removal_from_unit_removes_*, test_unit_roles_change_triggers_reconcile, test_personal_roles_change_triggers_reconcile, test_role_rights_change_triggers_reconcile_for_all_with_tickets |

## 5. Почта: IMAP-адаптер и `FakeMailbox`, письма заявки

### 5.1. Адаптер `apps/integrations/mail/imap.py`

Адаптер читает `settings.IMAP_*` при каждом вызове `connect()`, а не при импорте. Исключения
`imaplib` (`IMAP4.error`, `OSError`, `ssl.SSLError`, тайм-аут) он оборачивает в
`MailboxUnavailable` с текстом без пароля: текст пропускается через `tasks.safe_error`, чей
список секретов дополняется `IMAP_PASSWORD` (замена на `***`). Решение Opus (по плану,
plan.md:591-594): служба `poll_mailbox` пропускает текст любой пойманной `MailboxUnavailable`
через `apps.integrations.mail.tasks.safe_error` перед записью в `MailboxState.last_error` и в
лог; адаптер при оборачивании исключений `imaplib` делает то же. `safe_error` в срезе 003
убирает, кроме `EMAIL_HOST_PASSWORD`, ещё `settings.IMAP_PASSWORD` (уточнение: сейчас — только
пароль SMTP, tasks.py:45-51); формат — `"<класс исключения>: <текст>"`, не длиннее 500 знаков.
`safe_error` принимает исключение (не текст); текст `MailboxUnavailable` от адаптера уже со
своей приставкой, `poll` добавляет вторую (`MailboxUnavailable: …`), всё не длиннее 500 знаков;
тесты сверяют только `***` и отсутствие пароля.

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `MailboxUnavailable` | `class MailboxUnavailable(Exception)`: `str(exc)` — текст после `safe_error` (с приставкой `<класс исключения>: `) | T-3106 test_connection_error_saved_in_last_error_without_password_no_retry; T-3109 test_live_login_with_env_password_error_text_has_no_password |
| `FetchedMail` | `NamedTuple`: `uid: int`, `size: int` (`RFC822.SIZE`), `internal_date: datetime` (с часовым поясом, UTC), `raw: bytes` (`BODY.PEEK[]` целиком) | T-3106 |
| `connect` | `connect() -> MailboxConnection` — **фабрика соединения, точка подмены** (решение 4). Служба опроса зовёт её как `imap.connect()` через модуль (не `from … import connect`), чтобы подмена работала. Что делает настоящая: по `IMAP_SECURITY` — `imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=IMAP_TIMEOUT)` для `ssl`; `imaplib.IMAP4(host, port, timeout=IMAP_TIMEOUT)` и затем `starttls(ssl_context=ctx)` для `starttls`; `imaplib.IMAP4(host, port, timeout=IMAP_TIMEOUT)` без шифрования для `none`; `ctx` — результат `ssl.create_default_context()` (тест подменяет `imap.ssl.create_default_context` и проверяет, что именно возвращённый объект передан в `IMAP4_SSL(ssl_context=…)` или `starttls(ssl_context=…)` и что для режима `none` он не создаётся); затем `login(IMAP_USER, IMAP_PASSWORD)`, `select(IMAP_FOLDER, readonly=True)` (команда `EXAMINE`; ответ не `OK` или нет значений UIDVALIDITY и UIDNEXT — `MailboxUnavailable`; на `EXAMINE` проверит живой тест T-3109, в F1 был `SELECT` без `readonly`); `uidvalidity` и `uidnext` берутся из ответа на выбор папки (`response("UIDVALIDITY")`, `response("UIDNEXT")`), не из `STATUS` и не из `APPENDUID`. Другое значение `IMAP_SECURITY` — `MailboxUnavailable` | T-3106 test_adapter_security_modes_ssl_starttls_with_verifying_context_and_none, test_mailbox_opened_read_only_examine_nothing_flagged_or_deleted, test_uidvalidity_taken_from_select_not_status (на `FakeImap`, раздел 5.2); T-3109 |
| `MailboxConnection` | объект, который возвращает `connect()`; контекстный менеджер (`__exit__` зовёт `close()`); атрибуты `uidvalidity: int`, `uidnext: int`; методы ниже; методов, меняющих ящик (`store`, `copy`, `expunge`, `append`), у него нет | T-3106 |
| `MailboxConnection.search_uids` | `search_uids(first_uid: int) -> list[int]`: `UID SEARCH UID <first_uid>:*`; ответ как у сервера, **без фильтрации**: UID по возрастанию; если в диапазоне нет писем, сервер отдаёт последнее письмо ящика (Dovecot), и оно попадает в ответ; пустой ящик — `[]`. Фильтрует `uid > last_uid` служба опроса, а не адаптер | T-3106 test_new_mail_found_by_uid_range_filtered_on_client_for_empty_range, test_mail_read_by_other_client_still_fetched |
| `MailboxConnection.search_since` | `search_since(day: datetime.date) -> list[int]`: `UID SEARCH SINCE <дд-Мес-гггг>`; месяц — английское сокращение (`Jan`…`Dec`) независимо от языка системы (адаптер собирает дату сам, не через `strftime`); UID по возрастанию | T-3106 test_recreated_mailbox_takes_mails_within_10_minutes_before_last_ok_at |
| `MailHead` | `NamedTuple`: `uid: int`, `internal_date: datetime` (с часовым поясом, UTC), `message_id: str` (`""`, если заголовка нет), `size: int` (`RFC822.SIZE`) | T-3106 |
| `MailboxConnection.fetch` | `fetch(uid: int) -> FetchedMail`: `UID FETCH <uid> (RFC822.SIZE INTERNALDATE BODY.PEEK[])`; тело берётся из литерала `imaplib` без разбора; размер и `INTERNALDATE` читаются из служебной строки ответа не по позициям (порядок атрибутов у серверов разный, F1, Ф8); признак «прочитано» не ставится; неизвестный UID — `MailboxUnavailable` | T-3106 test_raw_mail_saved_whole_byte_for_byte_before_parsing, test_mail_read_by_other_client_still_fetched |
| `MailboxConnection.head` | `head(uid: int) -> MailHead`: `UID FETCH <uid> (INTERNALDATE RFC822.SIZE BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])`; тело не скачивается; признак «прочитано» не ставится; неизвестный UID — `MailboxUnavailable` (решение Opus, имя и форма — в пределах plan.md:565-576) | T-3106 test_recreated_mailbox_takes_mails_within_10_minutes_before_last_ok_at, test_recreated_mailbox_last_uid_by_smallest_selected_uid_or_uidnext_minus_one, test_recreated_mailbox_skips_repeated_message_id |
| `MailboxConnection.close` | `close() -> None`: выход из соединения (`logout`), повторный вызов безвреден | T-3106 |

Ящик пересоздан (решение Opus, имена и уточнения — в пределах plan.md:565-576):
- «отобранные» — письма, прошедшие все три отбора: `UID SEARCH SINCE`; `INTERNALDATE` не раньше
  `last_ok_at − 10 мин`; `Message-ID` которого пуст или ещё нет среди непустых во входящих
  (6.15) (дату и `Message-ID` служба берёт методом `head`, тело при отборе не скачивается);
- `last_uid` = наименьший UID отобранных − 1, отобранных нет — `UIDNEXT − 1`; дальше — обычным
  порядком `UID last_uid+1:*`, как в плане;
- вызовы `head` в предел 20 писем за запуск не входят: предел — на полное скачивание (план,
  шаг 4);
- тест `test_recreated_mailbox_skips_repeated_message_id` кладёт письмо с известным `Message-ID`
  с UID меньше, чем у нового письма (перенесённые из старого ящика письма ложатся в новый ящик
  раньше новых);
- граница плана: письмо с известным `Message-ID` и UID больше наименьшего отобранного план
  разбирает обычным порядком, как написано в плане.

### 5.2. `FakeMailbox` (`tests/support_servicedesk.py`) — полный интерфейс

Объект хранит один ящик в памяти. Он **повторяет интерфейс `MailboxConnection`** и сам
является своим соединением: подмена — `monkeypatch.setattr(imap, "connect", fake.connect)`.
Что фальшивка воспроизводит и чего нет: UIDVALIDITY и UIDNEXT; UID по возрастанию без
повторов; `UID SEARCH N:*` с ответом «последнее письмо» на пустой диапазон; `INTERNALDATE`;
байты письма как положены; признак «прочитано», который `fetch` не меняет; пересоздание
ящика. Папок, флагов кроме «прочитано», удаления и SMTP-части нет. Живые тесты T-3109 берут
настоящий Dovecot.

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `FakeMailbox(*, uidvalidity: int = 1000, uidnext: int = 1)` | конструктор; начальное состояние: ящик пуст | T-3106, T-3107, T-3136 |
| `.uidvalidity`, `.uidnext` | `int`: текущее значение; `uidnext` — следующий UID, который получит добавленное письмо (после трёх писем с UID 1, 2, 3 равен 4) | T-3106 |
| `.append(raw: bytes, *, internal_date: datetime \| None = None, seen: bool = False) -> int` | кладёт письмо, возвращает присвоенный UID (прежний `uidnext`), увеличивает `uidnext`; `internal_date` по умолчанию — `timezone.now()`; тест-часть интерфейса (у настоящего соединения этого метода нет) | T-3106 и все тесты пути письма |
| `.recreate(*, uidvalidity: int \| None = None) -> None` | «пересоздать ящик»: стирает все письма, `uidnext = 1`, UIDVALIDITY — заданный или прежний плюс 1 | T-3106 test_recreated_mailbox_*, T-3136 |
| `.mark_seen(uid: int) -> None` | «пометить прочитанным» (как будто письмо прочёл другой клиент); письмо остаётся и по-прежнему находится и скачивается | T-3106 test_mail_read_by_other_client_still_fetched |
| `.seen(uid: int) -> bool` | признак «прочитано» письма; после опроса портала остаётся прежним (проверка «ящик открыт только для чтения»: ни одно письмо не помечено, не удалено) | T-3106 test_mail_read_by_other_client_still_fetched |
| `.messages` | `dict[int, FakeMessage]`: UID → `FakeMessage(raw: bytes, internal_date: datetime, seen: bool)`; доступ только на чтение | T-3106 |
| `.connect() -> FakeMailbox` | «фабрика»: увеличивает `connects`, запоминает `folder = settings.IMAP_FOLDER`; если задан `set_unavailable(...)` — поднимает `MailboxUnavailable(text)`; иначе возвращает сам объект | T-3106 |
| `.set_unavailable(error: str \| None) -> None` | следующие `connect()` поднимают `MailboxUnavailable(error)`; `None` снимает отказ; тест `test_connection_error_saved_in_last_error_without_password_no_retry` подставляет пароль из `settings.IMAP_PASSWORD` в `error` и ждёт `***` в `last_error`; тест проверяет `"***" in last_error` и `password not in last_error`, точную строку не сверяет | T-3106 test_connection_error_saved_in_last_error_without_password_no_retry |
| `.fail_fetch(uid: int, error: str) -> None` | `fetch(uid)` поднимает `MailboxUnavailable(error)` (сбой обмена в середине запуска) | T-3106 |
| `.search_uids(first_uid: int) -> list[int]` | как у `MailboxConnection`: UID `>= first_uid` по возрастанию; если таких нет и ящик не пуст — `[наибольший UID]`; пустой ящик — `[]`; запись в `searches` | T-3106 |
| `.search_since(day: date) -> list[int]` | UID писем, у которых дата `internal_date` в UTC (решение Opus A6) не раньше `day`; по возрастанию | T-3106 |
| `.head(uid: int) -> MailHead` | как у `MailboxConnection`: `MailHead(uid, internal_date, message_id, len(raw))`, `message_id` читается из заголовка письма (`""`, если его нет); запись в `peeked`, а не в `fetched`; признак «прочитано» не меняется | T-3106 |
| `.fetch(uid: int) -> FetchedMail` | `FetchedMail(uid, len(raw), internal_date, raw)`; запись в `fetched`; признак «прочитано» не меняется | T-3106 |
| `.close() -> None`, `__enter__`, `__exit__` | увеличивает `closes`; контекстный менеджер возвращает сам объект | T-3106 |
| `.on_fetch: Callable[[int], None] \| None` | хук, по умолчанию `None`: вызывается в конце `fetch(uid)`, до возврата письма (тест подменяет значение ключа `servicedesk:poll` или читает его `ttl`) | T-3106 test_lock_released_only_by_own_value_in_finally, test_lock_extended_after_each_fetched_mail |
| наблюдаемые поля | `connects: int`, `closes: int`, `folder: str \| None`, `fetched: list[int]` (UID в порядке скачивания), `peeked: list[int]` (UID вызовов `head`, в `fetched` не попадают), `searches: list[tuple[str, object]]` (`("uid", first_uid)` или `("since", day)`) | T-3106 test_empty_imap_host_poll_exits_without_connecting (`connects == 0`), test_at_most_20_mails_per_run_rest_next_run_in_uid_order, test_restored_database_known_pairs_not_downloaded_last_uid_advances (`fetched` без известных пар) |
| `FakeImap` | двойник `imaplib` для тестов адаптера (в `support_servicedesk.py`), решение Opus: тест подменяет `imap.imaplib.IMAP4` и `imap.imaplib.IMAP4_SSL` (`monkeypatch.setattr`); методы `login`, `starttls(ssl_context=...)`, `select(folder, readonly=False)`, `response(code)`, `status(folder, names)`, `uid(command, *args)`, `logout`; `FakeImap.factory(*, uidvalidity, uidnext, status_uidvalidity, select_result="OK") -> Callable`: возвращает фабрику с сигнатурой `imaplib` (`(host, port=…, *, ssl_context=None, timeout=None)`), создающую `FakeImap`; тест ставит `monkeypatch.setattr(imap.imaplib, "IMAP4_SSL", FakeImap.factory(...))` (так же `IMAP4`); `status_uidvalidity` — заведомо другое значение для `STATUS`; в классе поля `ctor: list[tuple[str, tuple, dict]]` (имя класса, позиционные и ключевые аргументы каждого вызова) и `ssl_context` (что передано в конструктор или в `starttls`); поля `calls` (список кортежей «команда, аргументы») и `readonly` (что передано в `select`) | T-3106 test_adapter_security_modes_ssl_starttls_with_verifying_context_and_none, test_uidvalidity_taken_from_select_not_status, test_mailbox_opened_read_only_examine_nothing_flagged_or_deleted |
| `install_fake_mailbox` и фикстура `fake_mailbox` | `install_fake_mailbox(monkeypatch, settings, fake: FakeMailbox \| None = None) -> FakeMailbox`: подменяет `apps.integrations.mail.imap.connect` и ставит `settings.IMAP_HOST="imap.test"`, `IMAP_PORT=993`, `IMAP_SECURITY="ssl"`, `IMAP_USER="tickets"`, `IMAP_PASSWORD` — случайный `secrets.token_urlsafe()`, `IMAP_FOLDER="INBOX"`, `SERVICEDESK_MAILBOX="tickets@stand.test"`; тест «пустой `IMAP_HOST`» после этого ставит `settings.IMAP_HOST = ""` | T-3106, T-3107, T-3108, T-3136 |
| `build_mail` | `build_mail(*, from_addr: str, to: Sequence[str] = (), cc: Sequence[str] = (), subject: str = "", text: str \| None = "", html: str \| None = None, message_id: str \| None = None, in_reply_to: str \| None = None, references: str \| None = None, headers: dict[str, str \| Sequence[str]] \| None = None, attachments: Sequence[MailPart] = (), date: datetime \| None = None, charset: str = "utf-8") -> bytes` на `email.message.EmailMessage` (решение 6); `MailPart` — `NamedTuple(name: str, data: bytes, content_type: str = "application/octet-stream", content_id: str \| None = None)`, у части с `content_id` — `Content-Disposition: inline`; `message_id=None` — генерируется `make_msgid(domain="client.test")`, `message_id=""` — заголовок не пишется; `headers` дописываются как есть (например `Auto-Submitted`); значение-список пишет заголовок несколько раз (например несколько `Cc`); `charset="windows-1251"` и `"koi8-r"` кодируют текст в этой кодировке (T-3108). Остальные варианты письма (вложенное письмо, «сырое» 8-битное имя, ошибка заголовка) тест собирает сам из `email` внутри файла | T-3106, T-3107, T-3108, T-3119 |

### 5.3. Письма заявки через почтовый модуль среза 001

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `services.send_rendered` | `send_rendered(template: str, to: str, *, subject: str, cc: list[str], reply_to: str, message_id: str, references: str, auto_submitted: str, related_ref: str, attachments: list[str], context: dict) -> MailMessage` в `apps/integrations/mail/services.py`: шаблон должен начинаться с префикса, зарегистрированного в `mail_renderers` (иначе `ValueError`); создаёт `MailMessage` (`status="queued"`, `cc` — адреса через запятую, `attachments` — список `str(StoredFile.id)`), ставит `deliver_message` в очередь `mail` с теми же `Retry` и `on_failure`, что у `send` (`RETRY_MAX=11`, интервалы `[60, 300, 900, 3600] + [10800] * 7`); `job.meta` содержит только `{"context": public_context(context)}`; `message_id` — готовый заголовок вида `<…@домен>`, его сохраняет сервис до отправки | T-3118 test_send_rendered_queues_deliver_job_and_rejects_unregistered_prefix, test_mail_body_not_stored_and_job_meta_has_no_texts_or_addresses |
| рендерер точки `mail_renderers` | `render(message: MailMessage, context: dict) -> Rendered` (раздел 3.2); `deliver_message` зовёт его для шаблона с зарегистрированным префиксом вместо `render_to_string("mail/<шаблон>.txt")`; для прежних шаблонов путь не меняется; недоступное вложение (`StoredFile` не `clean` или файла нет на диске) рендерер просто не включает, письмо уходит без него | T-3118 test_deliver_renders_body_from_database_at_send_time |
| `deliver_message` | уточнение: для письма заявки собирает `EmailMessage` с заголовками из полей `MailMessage` (`Cc`, `Reply-To`, `Message-ID`, `References`, `In-Reply-To`, `Auto-Submitted`); `In-Reply-To` — последний идентификатор из `MailMessage.references` (отдельного поля нет); `References` — список идентификаторов первого письма заявителя и предыдущего письма портала по заявке, по порядку, без повторов (plan.md:911-912); пустой список — оба заголовка не пишутся (решение Opus); состав заголовков и текст по видам писем — раздел 10 | T-3118 |
| `services.anonymize_related` | `anonymize_related(related_ref: str) -> int`: у писем с этим `related_ref` `to` — «обезличено», `cc` — `""`, `attachments` — `[]`, `last_error` и `MailAttempt.error` — `""`; `subject`, `reply_to`, `message_id`, `references` не меняются; возвращает число писем | T-3129 test_delivery_log_to_cc_attachments_and_attempt_errors_cleared, test_delivery_log_subject_reply_to_message_id_references_kept |
| `tasks.safe_error` | уточнение: список секретов дополнен `IMAP_PASSWORD` (в тексте он заменяется на `***`), прежний `EMAIL_HOST_PASSWORD` остаётся; формат `"<класс исключения>: <текст>"`, не длиннее 500 знаков; службу опроса `poll_mailbox` и адаптер см. раздел 5, вводный абзац | T-3106 test_connection_error_saved_in_last_error_without_password_no_retry |
| `mail.failed` | публикуется из `tasks.on_failure` после перевода письма в `failed` (данные — раздел 3.1); для писем заявки подписчик `servicedesk` добавляет событие ленты и журнал `ticket.mail_failed` | T-3118 test_*failed*, T-3132 |

## 6. Сервисы servicedesk

Часть b1 (модули `access`, `queues`, `dictionaries`, `settings`, `tickets`, `assignment`,
`transfer`, `replies`, `closing`, `reconcile`, `events`). Остальные модули (`intake`, `mailbox`,
`letters`, `attachments`, `form`, `requesters`, `requester_import`, `search`, `retention`, заявка
от исполнителя) пишет часть b2, подразделы с 6.14. Модули лежат в
`apps/servicedesk/services/<модуль>.py`; тесты зовут `apps.servicedesk.services.<модуль>` внутри
функций теста (правила в шапке).

### 6.1. Общее для всех модулей

| Что | Требование | Тесты |
|---|---|---|
| Ошибка | **Одна на весь `servicedesk`**: `apps.servicedesk.services.ServiceDeskError(Exception)` (файл `apps/servicedesk/services/errors.py`, экспорт из пакета `services/__init__.py`), как `OrgError`: `__init__(self, code: str, message: str)`, атрибуты `code` и `message`, `str(error)` равна `message`. Тест узнаёт причину по `error.code`; текст сверяет только там, где таблица 6.2 даёт дословный. Ошибки ядра (`AccountError`, `RoleError`) не оборачиваются. Недоступная заявка — не `ServiceDeskError`, а `django.http.Http404` из `tickets.get_for` | все `test_sd_*` |
| `Batch` | `apps.servicedesk.services.Batch` — `dataclass(frozen=True)`: `done: int` (сколько обработано в порции; у `anonymize_batch` — сколько обезличено, решение Opus П2; у `reconcile.batch` — число людей порции), `more: bool` (есть ли следующая порция), `last_id: int \| None = None` (где остановились, для следующей порции), `last: str \| tuple \| None = None` (курсор порций с составным ключом: имя файла у `retention.purge_orphan_files`, пара (`closed_at`, `id`) у `retention.anonymize_batch`; пара (`waiting_since`, `id`) у `closing.autoclose_batch`, пара (`received_at`, `id`) у `retention.purge_inbound`; решения Opus C3, RB2-12, RC-3). Возвращают порции `closing.autoclose_batch`, `reconcile.batch`, `retention.anonymize_batch`, `retention.purge_inbound` и `retention.purge_orphan_files` | test_sd_status_autoclose, test_sd_reconcile |
| Порядок проверок | `no_access` (актёр заявку не видит) → `ticket_closed` → остальные; `not_participant` — актёр заявку видит, но не участник очереди (например, ответственный по заявке чужой очереди); порядок кодов в ячейках «Отказ» 6.7–6.11 значения не имеет, порядок — по этой строке | test_sd_assignment, test_sd_assignment_2 |
| Подписи функций | как у `org`: пользовательские действия принимают `actor` (`User`) и `ip=None` **только по ключу**, после позиционных объектов (`ticket`, `entry`); `actor=None` — «система» (автозакрытие, сверка, письмо заявителя): журнал и лента пишутся без автора; объекты `org` сервис получает числом (`queue_id`, `unit_id`), модели `org` не импортирует (раздел 3.2, границы модулей) | все `test_sd_*` |
| Транзакция | каждая функция, меняющая данные, работает в своём `transaction.atomic()`; вложенный вызов становится точкой сохранения (групповые действия, раздел 6.8, опираются на это); заявку меняющие функции блокируют через `select_for_update` и перечитывают состояние | test_sd_assignment_2, test_sd_status_autoclose |
| Закрытая заявка | функции `assignment`, `transfer`, `tickets.update_fields`, `tickets.set_status_manual`, `tickets.remove_participant`, `replies.reply`, `replies.resend`, `closing.close` на заявке вида `closed` отказывают `ticket_closed`; `replies.comment` и `closing.reopen` на закрытой работают | test_sd_assignment_2, test_sd_reply, test_sd_closing |
| Журнал | запись — `apps.core.services.audit.record(action, *, actor=None, object_type="", object_id="", before=None, after=None, ip=None)`; `object_id` — номер заявки строкой; коды событий — по таблице «Журнал» плана, назначения и тексты — раздел 9; адресов, ФИО и текстов писем в журнале нет (FR-289); ключи `code`, `key`, `link`, `url` в `before`/`after` не используются (`audit` прячет их значения как `***`) | test_sd_audit |
| Лента | событие ленты — строка `TicketEntry(kind="event")` с кодом в `event` и словарём `data`; пишется только функцией `replies.add_event` (6.10); коды событий и тексты — раздел 9 | test_sd_card |
| Письма | сервис зовёт `letters.send(ticket, template, *, entry=None, extra=None)` модуля `letters` (часть b2): создаёт `MailMessage` и ставит `deliver_message` **после фиксации**; шаблоны плана: `ticket.confirmation`, `ticket.assigned`, `ticket.closed`, `ticket.autoclosed`, `ticket.reopened`, `ticket.reply`; содержание — раздел 10 | test_sd_assignment, test_sd_closing, test_sd_reply |
| Шина | публикация — только через `events.*` (6.13), внутри транзакции действия; обработчик идёт после фиксации (раздел 3.1) | test_sd_boundaries |
| Текущее время | `django.utils.timezone.now()` (решение 5 задач); аргумента `now` у функций нет, кроме `closing.autoclose_one(ticket_id, *, now=None)` | test_sd_status_autoclose |

### 6.2. Коды причин `ServiceDeskError.code`

Таблица общая для модулей 6.3-6.24 (строки b2 дописаны в конец). «Текст» —
русское сообщение `error.message`; где в плане и спеке дословного текста нет, в ячейке «текст —
раздел 14»: часть d запишет текст в раздел 14, тест такой код сверяет только по `code`.

| Код | Когда | Текст | Адрес текста | Тесты |
|---|---|---|---|---|
| `no_access` | действие над заявкой, которой у `actor` нет в `visible_tickets` (прямой вызов сервиса минуя маршрут) | «нет доступа» (причина пропуска в групповом итоге) | plan.md:807 | test_sd_access, test_sd_assignment_2 |
| `ticket_closed` | действие, недоступное на закрытой заявке (6.1) | «Заявка закрыта: сначала откройте её» | plan.md:795-796 | test_sd_assignment_2::test_closed_ticket_*, test_sd_reply, test_sd_closing |
| `ticket_open` | `closing.reopen` на заявке, которая не закрыта | текст — раздел 14 | - | test_sd_closing_2 |
| `not_participant` | кандидат в ответственные или тот, кто берёт себе, не `is_participant` очереди заявки | текст — раздел 14 | spec.md:240 (смысл) | test_sd_assignment, test_sd_assignment_2 |
| `no_queue` | у заявки не определить очередь: нет очереди по умолчанию и не указана `queue_id` | текст — раздел 14 | - | test_sd_queues, test_sd_create |
| `not_queue` | узел не отмечен очередью (передача, очередь по умолчанию, `create`; у категории — `queue_not_marked`) | текст — раздел 14 | - | test_sd_queues, test_sd_assignment |
| `already_queue` | отметка уже стоит | текст — раздел 14 | - | test_sd_queues |
| `queue_has_open_tickets` | снять отметку с очереди, где есть заявки видов `new`, `in_progress`, `waiting` | текст — раздел 14 («отказ с объяснением») | spec.md:406 | test_sd_queues::test_unmark_queue_with_open_tickets_refused_with_reason |
| `queue_is_default` | снять отметку с очереди по умолчанию | текст — раздел 14 | plan.md:419-421 | test_sd_queues::test_default_queue_cannot_be_unmarked_and_is_chosen_only_among_marked |
| `same_queue` | передача в текущую очередь | текст — раздел 14 | - | test_sd_assignment |
| `queue_required` | передача без очереди | текст — раздел 14 | - | test_sd_assignment |
| `reason_too_long` | причина передачи длиннее 500 знаков | текст — раздел 14 | plan.md:764-765 | test_sd_assignment |
| `name_required` | название справочника пустое после обрезки пробелов | текст — раздел 14 | - | test_sd_dictionaries |
| `name_too_long` | название длиннее 100 знаков (`ClientUnit` — 150) | текст — раздел 14 | plan.md:341-345 (модели) | test_sd_dictionaries |
| `name_taken` | такой `name_key` уже есть в этом справочнике (другая запись) | текст — раздел 14 | plan.md:446-448 | test_sd_dictionaries::test_name_required_and_unique_case_yo_and_spaces_insensitive_in_every_dictionary |
| `in_use` | удаление значения справочника, которое есть в заявках (у `ClientUnit` — ещё и в записях заявителей); в сообщении предложение убрать в архив | текст — раздел 14 («отказ и предложение убрать его в архив») | spec.md:414-415 | test_sd_dictionaries::test_delete_used_value_refused_with_archive_offer |
| `system_protected` | архив или удаление системного значения: категория «Другое», статус `autoclosed`, источники `mail` и `form`; ручное закрытие системным статусом | текст — раздел 14 | spec.md:718-719 | test_sd_dictionaries |
| `default_protected` | архив или удаление статуса по умолчанию своего вида или критичности по умолчанию; у статуса проверяется после `last_active`, поэтому тест статуса по умолчанию берёт вид, где действующих статусов несколько (например `closed`) | текст — раздел 14 | spec.md:716-717 | test_sd_dictionaries |
| `last_active` | архив или удаление последнего действующего статуса вида; проверяется раньше `default_protected`: у единственного действующего статуса вида (он же по умолчанию) отказ с кодом `last_active` | текст — раздел 14 | spec.md:416-417 | test_sd_dictionaries::test_last_active_status_of_kind_cannot_be_archived |
| `queue_not_marked` | у категории очередь — не отмеченный узел | текст — раздел 14 | plan.md:463-465 | test_sd_dictionaries::test_category_queue_only_marked_unit |
| `assignee_not_participant` | ответственный по умолчанию категории не участник её очереди на момент сохранения | текст — раздел 14 | spec.md:407-409 | test_sd_dictionaries::test_category_default_assignee_only_queue_participant_else_refused |
| `archived_value` | выбор архивной критичности, сложности, категории, подразделения там, где архивное не предлагается | текст — раздел 14 | plan.md:451-453 | test_sd_assignment_2::test_archived_criticality_and_complexity_not_offered |
| `bad_status` | ручная смена на статус вида `new` или `closed`, на архивный; закрытие статусом не вида `closed`, системным или архивным | текст — раздел 14 | plan.md:746-750 | test_sd_status, test_sd_closing |
| `source_required` | заявка от исполнителя без ручного источника: системный и архивный дают `source_required`, `archived_value` для источника не используется | текст — раздел 14 | plan.md:460-462 | test_sd_executor (T-3122) |
| `email_required` | `create` без адреса заявителя | текст — раздел 14 | - | test_sd_create |
| `bad_domain` | домен настроек не прошёл проверку вида | текст — раздел 14 | plan.md:470 | test_sd_queues::test_domains_invalid_form_refused |
| `out_of_range` | число настроек вне границ раздела 2.2 (поле названо в сообщении) | текст — раздел 14 | - | test_sd_queues::test_initial_terms_and_limits_defaults_7_7_10_3_30_and_ranges_validated |
| `text_required` | ответ или комментарий без текста после обрезки пробелов | текст — раздел 14 | plan.md:829-830 | test_sd_reply |
| `text_too_long` | ответ длиннее 50 000 знаков | текст — раздел 14 | plan.md:829-830 | test_sd_reply |
| `not_resendable` | повторная отправка не для `reply` в состоянии `not_sent` | текст — раздел 14 | plan.md:845-848 | test_sd_reply::test_resend_button_only_on_not_sent_reply |
| `resolution_required` | закрытие без текста решения | текст — раздел 14 | plan.md:865-866 | test_sd_closing::test_close_without_resolution_refused |
| `resolution_too_long` | решение длиннее 10 000 знаков | текст — раздел 14 | plan.md:865-866 | test_sd_closing::test_close_resolution_up_to_10_thousand |
| `bulk_limit` | групповое действие над более чем 100 заявками | текст — раздел 14 | plan.md:802 | test_sd_assignment_2::test_group_over_hundred_tickets_refused |
| `bad_action` | групповое действие не из трёх (`assign`, `transfer`, `priority`) | текст — раздел 14 | plan.md:800-801 | test_sd_assignment_2 |
| причина `queue_unmarked` | не код отказа, а значение `data["reason"]` события ленты «очередь: было → стало»; подпись в ленте — «причина — очередь снята» (14.5; решение Opus П6, код по RB2-10) | «очередь снята» (подпись, не значение) | plan.md:886 | test_sd_closing_2::test_reopen_by_letter_when_node_not_queue_goes_to_default_queue_with_event |
| причины для `unit_usage` | не коды `ServiceDeskError`: строки, которые `queues.unit_usage` отдаёт точке расширения | «к узлу привязаны заявки сервис-деска»; «узел — очередь сервис-деска: сначала снимите отметку» | plan.md:435-437 | test_sd_queues |
| `intake_closed` | приём закрыт: форма — пуст список доменов или нет очереди по умолчанию (`form.submit`); заявка от исполнителя — пуст список доменов (`executor.create`) | форма: «Приём заявок через форму сейчас закрыт. Напишите письмо на <адрес ящика>»; исполнитель — текст раздел 14 | plan.md:1045-1046 (форма) | test_sd_form::test_post_when_closed_rejected_with_same_text, test_sd_executor::test_empty_domain_list_refuses_creation |
| `invalid_form` | открытая форма с ошибками полей; `errors` — словарь поле → код из строк ниже | текст — раздел 14 (по сообщению на поле) | plan.md:1048-1052 | test_sd_form |
| `bad_email` | адрес не годен по формату или домен не из списка (`requesters.normalize_email`; форма, заявка от исполнителя) | «Укажите рабочую почту на корпоративном домене» | plan.md:1048-1049 | test_sd_form::test_invalid_address_and_foreign_domain_refused, test_sd_executor::test_non_corporate_address_refused |
| `requester_name_required` | форма без ФИО | текст — раздел 14 | plan.md:1050-1051 | test_sd_form::test_required_fields_and_length_limits_refused |
| `subject_required`, `subject_too_long` | тема пустая или длиннее 255 знаков (форма, заявка от исполнителя) | текст — раздел 14 | plan.md:1051, 1095-1096 | test_sd_form, test_sd_executor::test_required_fields_refused_and_name_optional |
| `description_required`, `description_too_long` | описание пустое или длиннее 50 000 знаков (форма, заявка от исполнителя) | текст — раздел 14 | plan.md:1051, 1095-1096 | test_sd_form, test_sd_executor |
| `consent_required` | форма без галочки согласия | текст — раздел 14 | plan.md:1051-1052 | test_sd_form::test_missing_consent_refused |
| `category_required` | заявка от исполнителя без категории | текст — раздел 14 | plan.md:1095-1096 | test_sd_executor::test_required_fields_refused_and_name_optional |
| `category_not_offered`, `unit_not_offered` | категория или подразделение формы не из предлагаемых на форме (архивные, не помеченные «на форме») | текст — раздел 14 | plan.md:1049-1050 | test_sd_form::test_category_or_department_not_offered_refused |
| `rate_limited` | с адреса клиента принято больше `form_hourly_limit` заявок за час | «С вашего адреса отправлено слишком много заявок за час. Напишите письмо на <адрес ящика>» | plan.md:1061-1062 | test_sd_form::test_rate_limit_refuses_over_threshold_with_mailbox_address |
| `file_rejected` | файл формы, ответа или заявки от исполнителя не принят (размер, исполняемый, архив с паролем; `strict=True`) | «файл «<имя>» не принят: <подпись причины>» (подписи — `Attachment.REJECT_TITLES`) | plan.md:990 | test_sd_attachments::test_form_and_reply_with_rejected_file_refused_entirely_with_message |
| `too_many_files`, `total_too_big` | больше 10 файлов; сумма файлов больше 50 МБ (форма, ответ, заявка от исполнителя) | текст — раздел 14 | plan.md:991-993 | test_sd_attachments::test_form_over_10_files_or_over_50mb_total_refused |
| `requester_name_too_long` | ФИО записи заявителя, ФИО на форме и в заявке от исполнителя длиннее 255 знаков | текст — раздел 14 | - | test_sd_requesters::test_edit_name_and_client_unit_saved |
| `requester_has_tickets` | удаление записи заявителя, у которого есть заявки | текст — раздел 14 | plan.md:1194-1195 | test_sd_requesters::test_delete_requester_with_tickets_refused |
| `too_big`, `bad_format`, `not_utf8`, `too_many_rows`, `zip_bomb`, `xml_bomb`, `missing_columns` | отказ чтения файла загрузки заявителей (`requester_import.parse_file`); тот же набор кодов у `table_file` как `TableFileError` | текст — раздел 14 (пределы 2 МБ и 2000 строк; прежние тексты загрузки сотрудников — CONTRACT-002) | plan.md:1206-1209 | test_sd_requester_import (отказы файла), test_table_file |
| коды ошибок строки загрузки | не `ServiceDeskError`: значения `code` в `rows` предпросмотра: `email_missing`, `email_invalid`, `foreign_domain`, `email_repeated`, `unit_archived`, `too_long` | в `reason`: «ошибка: подразделение в архиве», «ошибка: повтор почты»; прочие — «ошибка: …» с причиной (раздел 14) | spec.md:489-490; plan.md:1214 | test_sd_requester_import (6.23) |

### 6.3. `access`

Значение `Scope` — `dataclass(frozen=True)` в `access.py`: `has_all: bool` (держатель
`servicedesk.all`), `work_units: frozenset[int]` (`org.structure.work_units_of`).

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `scope` | `scope(user, *, fresh=False)` | `Scope`; считается один раз на объект пользователя: результат лежит в атрибуте `user._sd_scope`, второй вызов на том же объекте запросов не делает; `fresh=True` пересчитывает мимо атрибута и читает права как `permissions_of(user, fresh=True)` (для `reconcile`); уволенный — `Scope(False, frozenset())` | нет | ничего | test_sd_access, test_sd_reconcile |
| `visible_tickets` | `visible_tickets(user)` | `QuerySet[Ticket]`: все заявки при `has_all`, иначе `Q(queue_id__in=work_units) \| Q(assignee=user)`; для уволенного и без доступа — пустой набор; без сортировки | нет | ничего | test_sd_access::test_visible_tickets_only_own_queues_and_own_assigned, test_assignee_sees_ticket_of_foreign_queue, test_head_and_deputy_see_and_work_with_nested_queue_tickets, test_rank_and_file_of_parent_unit_does_not_see_nested_queue_tickets, test_nested_team_member_does_not_see_parent_queue_tickets |
| `is_participant` | `is_participant(user, unit_id)` | `bool`: `has_all` или `unit_id in work_units`; не зависит от того, отмечен ли узел очередью; уволенный — `False` | нет | ничего | test_sd_access, test_sd_assignment, test_sd_dictionaries |
| `can_work` | `can_work(user, ticket)` | `bool`: `ticket` среди видимых (видеть и работать — одно и то же, план «Что считает access»); без запроса к базе: по `ticket.queue_id` и `ticket.assignee_id` | нет | ничего | test_sd_access, test_sd_closing_2::test_manual_reopen_refused_for_outsider_even_direct_request |
| `eligible_assignees` | `eligible_assignees(unit_id)` | `list[PersonRef]`: `structure.queue_people(unit_id)` и держатели `servicedesk.all` (`permissions.users_with`), без уволенных и повторов, по `full_name`, затем `id` | нет | ничего | test_sd_access::test_eligible_assignees_queue_people_plus_all_holders_without_dismissed |
| `suggest_assignees` | `suggest_assignees(unit_id, prefix)` | `list[PersonRef]`: из `eligible_assignees`, у которых `name_key(full_name)` начинается с `name_key(prefix)` (без регистра и «ё/е»); пустой `prefix` — все | нет | ничего | test_sd_assignment::test_assignee_suggestions_only_queue_members_by_name_start_case_and_yo_insensitive |
| `menu_visible` | `menu_visible(user)` | `bool` для `visible` пункта «Заявки»: `has_all`, или в `work_units` есть узел-очередь (`Queue.objects.filter(unit_id__in=...).exists()`), или `Ticket.objects.filter(assignee=user).exists()`; не больше двух запросов, не зависит от числа заявок и очередей | нет | ничего | test_sd_access::test_menu_item_tickets_visible_to_participant_all_holder_or_assignee_only, test_sd_capacity |
| `can_create` | `can_create(user)` | `bool` для маршрутов `/tickets/new/`: `has_all` или в `work_units` есть узел-очередь (без «только ответственный»); тест `test_non_participant_has_no_new_ticket_button_and_direct_request_refused` берёт сотрудника, который ответственный по заявке чужой очереди (пункт меню виден), и ждёт 200 на `/tickets/` без `a[data-action="ticket-new"]`, 403 на `/tickets/new/` | нет | ничего | test_sd_access::test_non_participant_has_no_new_ticket_button_and_direct_request_refused |

Правила для заявителя и участника из копии: у них нет учётной записи, функций доступа для них нет
(`test_requester_and_copy_participant_have_no_portal_access`): вход на `/login/` с адресом
заявителя (учётной записи нет) даёт тот же общий отказ, что у неизвестного адреса (200 с общим
сообщением, `CONTRACT.md` среза 001, `/login/`), а `/tickets/` без входа — 302 на `/login/`
(раздел 12, общее правило).

### 6.4. `queues`

Узел передаётся числом `unit_id`. Строка `Queue` — отметка узла. Право `servicedesk.manage`
проверяет маршрут, сервис его не читает (как `org`).

`UnmarkPreview` — `dataclass(frozen=True)` в `queues.py`: `open_tickets: int` (виды `new`,
`in_progress`, `waiting`), `categories: list[Category]` (категории, ведущие в этот узел, по
`order`, затем `id`).

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `marked_units` | `marked_units()` | `list[UnitRef]` отмеченных узлов по `path` (`UnitRef` — раздел 4); `Queue.objects.select_related("unit")`, один запрос; `UnitRef` строится из связанного узла | нет | ничего | test_sd_queues, test_sd_assignment |
| `is_queue` | `is_queue(unit_id)` | `bool` | нет | ничего | test_sd_queues |
| `default_unit_id` | `default_unit_id()` | `int \| None` — `ServiceDeskSettings.default_queue_id` | нет | ничего | test_sd_queues, test_sd_create |
| `mark` | `mark(unit_id, *, actor, ip=None)` | `Queue` | `already_queue`; узла нет — `not_queue` не используется, неизвестный `unit_id`: поведение не задано, тесты его не вызывают | журнал `queue.marked` | test_sd_queues::test_mark_any_unit_as_queue_writes_journal_event |
| `unmark_preview` | `unmark_preview(unit_id)` | `UnmarkPreview` для диалога подтверждения; ничего не меняет | `not_queue` | ничего | test_sd_queues::test_unmark_dialog_names_affected_categories_and_journal_gets_update_per_category |
| `unmark` | `unmark(unit_id, *, actor, ip=None)` | `list[Category]` — переведённые в очередь по умолчанию (те же, что в `unmark_preview`); в одной транзакции: категории с `queue_id = unit_id` получают очередь по умолчанию, `default_assignee` снимается, если он не `is_participant` очереди по умолчанию (остаётся, если участник); строка `Queue` удаляется; закрытые заявки узла остаются | `not_queue`, `queue_is_default`, `queue_has_open_tickets` (порядок проверок такой) | журнал `queue.unmarked`; на каждую переведённую категорию `sd_dictionary.updated` | test_sd_queues::test_unmark_queue_*, test_unmark_moves_categories_to_default_queue_and_clears_non_participant_default_assignee, test_unmark_keeps_default_assignee_who_participates_in_default_queue |
| `set_default` | `set_default(unit_id, *, actor, ip=None)` | `None`; пишет `ServiceDeskSettings.default_queue`; категория «Другое» ведёт в новую очередь без своей записи (её `queue` пуст всегда); повторный выбор той же очереди — тихо ничего | `not_queue` | журнал `queue.default_changed`; **после фиксации**: задание `process_inbound` на каждое `InboundMail` в состоянии `waiting_setup` (имя и аргументы — раздел 7) | test_sd_queues::test_default_queue_change_moves_category_other_to_it, test_choosing_default_queue_enqueues_parsing_of_waiting_setup_mails_after_commit |
| `unit_usage` | `unit_usage(unit_id)` | `str \| None` для точки `unit_usage` (раздел 3.2): «к узлу привязаны заявки сервис-деска» (есть любая `Ticket` с `queue_id`), иначе «узел — очередь сервис-деска: сначала снимите отметку» (есть `Queue`), иначе `None`; текст дословно из плана | нет | ничего | test_sd_queues::test_delete_unit_with_tickets_including_only_closed_refused_with_reason, test_delete_queue_unit_without_tickets_refused_unmark_first, test_delete_empty_unit_passes_and_protect_guards_ticket_queue_and_queue_unit |

Снятие отметки у узла с закрытыми заявками проходит, а `closing.reopen` такой заявки идёт в
очередь по умолчанию (6.11;
`test_unmark_queue_with_only_closed_tickets_passes_and_reopen_goes_to_default_queue`).

### 6.5. `dictionaries`

Вид справочника задаётся строкой: `category`, `priority`, `complexity`, `status`, `source`,
`client_unit` (адреса маршрутов — `categories`, `priorities`, `complexities`, `statuses`,
`sources`, `client-units`, раздел 12). Константа `dictionaries.KINDS` — кортеж этих шести строк в
этом порядке; модель вида берёт
`dictionaries.model_of(dictionary)`. События журнала: у `client_unit` —
`client_unit.*`, у остальных — `sd_dictionary.*`; вид объекта у тех и других один —
`sd_dictionary` (в `after["dictionary"]` вид справочника, русские названия — раздел 9);
`object_id` — `"<вид справочника>:<id>"` (9.1). Права `servicedesk.manage` сервис не читает.

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `model_of` | `model_of(dictionary)` | класс модели вида | `KeyError` на неизвестный вид | ничего | test_sd_dictionaries |
| `create` | `create(dictionary, *, name, order=0, actor, ip=None, **extra)` | созданная запись; `name_key` заполняет сервис; `extra`: `category` — `queue_id` (обязателен; `None`, неотмеченный узел или узел-не-очередь — `queue_not_marked`), `default_assignee=None` (`User` или `None`), `on_form=False`; цикл по справочникам создаёт категорию с `queue_id` отмеченного узла; `status` — `kind` (обязателен: `new`, `in_progress`, `waiting`, `closed`), `is_default=False`; прочие виды — без `extra`; у `client_unit` нет `order`; новая запись не архивная и не системная; `is_system` и `system_code` не принимаются (`TypeError`) | `name_required`, `name_too_long`, `name_taken`, `queue_not_marked`, `assignee_not_participant` | журнал `*.created` | test_sd_dictionaries::test_name_required_and_unique_case_yo_and_spaces_insensitive_in_every_dictionary, test_status_kind_set_on_creation_and_not_changeable, test_new_status_of_in_work_kind_treated_as_in_work_and_offered_for_manual_change, test_client_unit_add_rename_archive_journaled |
| `update` | `update(obj, *, name, order=None, actor, ip=None, **extra)` | обновлённая запись; `extra` — те же ключи, что у `create`, кроме `kind` у статуса (передать `kind` — `TypeError`: вид после создания не меняется); `is_default=True` у статуса снимает отметку с прежнего статуса того же вида в той же транзакции; `is_default=False` у статуса по умолчанию не снимает (отметка переносится только выбором другого); у «Другое» ключ `queue_id` не принимается; журнал только если что-то изменилось; переименовать можно любую запись, в том числе системную | `name_required`, `name_too_long`, `name_taken`, `queue_not_marked`, `assignee_not_participant` | журнал `*.updated` (было и стало по названию, порядку, очереди, ответственному, «на форме», «по умолчанию») | test_sd_dictionaries::test_default_mark_moves_within_kind_in_one_transaction, test_system_auto_closed_status_renamed_but_not_archived_or_deleted_and_any_status_renamable, test_system_sources_mail_and_form_not_in_manual_choice_not_archived_not_deleted_but_renamable, test_category_default_assignee_only_queue_participant_else_refused |
| `archive` | `archive(obj, *, actor, ip=None)` | `None`; `archived=True` | `system_protected`, `last_active`, `default_protected` (порядок: системное, последний действующий, по умолчанию; решил Opus, итоговая сверка F1-1) | журнал `*.archived` | test_sd_dictionaries::test_default_status_cannot_be_archived_or_deleted, test_last_active_status_of_kind_cannot_be_archived, test_default_criticality_cannot_be_archived_or_deleted, test_category_other_not_deleted_not_archived_and_has_no_own_queue |
| `restore` | `restore(obj, *, actor, ip=None)` | `None`; `archived=False`; не архивное — тихо ничего | нет | журнал `*.restored` | test_sd_dictionaries::test_archived_value_shown_in_list_filter_with_archive_mark |
| `delete` | `delete(obj, *, actor, ip=None)` | `None`; удаляет строку | `system_protected`, `last_active`, `default_protected`, `in_use` (порядок: системное, последний действующий, по умолчанию, использовано; решил Opus, итоговая сверка F1-1) | журнал `*.deleted` | test_sd_dictionaries::test_delete_unused_value_passes, test_delete_used_value_refused_with_archive_offer, test_client_unit_delete_only_when_unused_by_tickets_and_requester_records |
| `is_used` | `is_used(obj)` | `bool`: одна проверка `exists()` по заявкам (у `Category` — `category`, у `ClientUnit` — ещё `Requester.client_unit`; у статуса — `Ticket.status`, у источника — `Ticket.source`; у критичности — `Ticket.priority` **и** «по умолчанию» в настройках; у сложности — `Ticket.complexity`) | нет | ничего | test_sd_dictionaries |
| `offered` | `offered(dictionary)` | `QuerySet` неархивных записей вида по `order`, затем `name` (у `ClientUnit` — по `name`); для всех выборов формы и карточки | нет | ничего | test_sd_dictionaries::test_archived_value_not_offered_in_choice_but_shown_in_old_ticket, test_client_units_unique_without_case_archived_not_offered_flat_list |
| `manual_statuses` | `manual_statuses()` | неархивные статусы видов `in_progress` и `waiting` по `order`; список ручной смены | нет | ничего | test_sd_status::test_manual_status_list_has_only_in_work_and_waiting_kinds_not_archived |
| `closing_statuses` | `closing_statuses()` | неархивные статусы вида `closed` без системного `autoclosed`, по `order`; в начале — статус по умолчанию вида (форма закрытия) | нет | ничего | test_sd_closing::test_close_form_offers_closed_kind_statuses_default_resolved, test_close_form_excludes_system_autoclosed_and_archived_statuses |
| `manual_sources` | `manual_sources()` | неархивные источники без системных (`system_code=""`), по `order` | нет | ничего | test_sd_dictionaries::test_system_sources_mail_and_form_not_in_manual_choice_not_archived_not_deleted_but_renamable |
| `default_status` | `default_status(kind)` (`kind` — вид статуса, не вид справочника) | запись `Status` с `is_default` этого вида | нет | ничего | test_sd_status |

### 6.6. `settings`

Строка настроек одна (`pk=1`, создана миграцией). Название модуля `settings` не мешает
`django.conf.settings`: внутри модуля `django.conf.settings` импортируется как `dj_settings`.

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `get` | `get()` | `ServiceDeskSettings` (`pk=1`) | нет | ничего | test_sd_queues |
| `parse_domains` | `parse_domains(text)` | `list[str]`: `text` — строка через запятую или перевод строки (или список строк); обрезка пробелов, строчные, кириллический домен — в виде `xn--...` (кодек `idna`), дубликаты убраны с сохранением порядка первых вхождений, пустые части пропущены | `bad_domain`: после кодека `idna` какая-либо метка не соответствует `^[a-z0-9]([a-z0-9-]*[a-z0-9])?$` (без «_», не начинается и не кончается «-», не пуста), меток меньше двух, домен длиннее 253 знаков; «xn--…» на входе принимается без перекодировки | ничего | test_sd_queues::test_domains_lowercased_split_by_comma_and_newline_xn_accepted, test_domains_duplicates_removed, test_domains_invalid_form_refused |
| `update` | `update(*, actor, ip=None, **fields)` | `ServiceDeskSettings`; `fields` — любые из `domains` (строка или список, идёт через `parse_domains`), `default_priority` (`Priority`), `autoclose_days`, `reopen_days`, `form_hourly_limit`, `retention_years`, `inbound_retention_days`; другие ключи (в том числе `default_queue`, адрес ящика) — `TypeError`: очередь по умолчанию меняет только `queues.set_default`, адрес ящика только для чтения; границы — раздел 2.2 | `bad_domain`, `out_of_range`, `archived_value` (архивная критичность по умолчанию) | журнал `servicedesk.settings_changed`: каждое изменённое поле до и после (только изменённые; ничего не изменилось — события нет) | test_sd_queues::test_initial_terms_and_limits_defaults_7_7_10_3_30_and_ranges_validated, test_default_criticality_setting_saved_and_used_for_new_ticket, test_changes_of_queues_dictionaries_and_settings_journaled_was_became_in_russian |
| `mailbox_address` | `mailbox_address()` | `str` — `django.conf.settings.SERVICEDESK_MAILBOX`; изменить через сервис нельзя | нет | ничего | test_sd_queues::test_mailbox_address_readonly_in_settings |
| `is_configured` | `is_configured()` | `bool`: `domains` не пуст и очередь по умолчанию задана; по нему форма и письма «закрыты по умолчанию» и напоминание на главной (`home_notices`) | нет | ничего | test_sd_queues::test_fresh_install_no_queues_no_domains_mail_and_form_not_accepted, test_home_notice_for_manage_holder_until_configured |
| `accepts_domain` | `accepts_domain(domain)` | `bool`: `domain` (после приведения как в `parse_domains`) есть в `domains` на момент вызова; читает базу при каждом вызове (удалённый из списка домен перестаёт приниматься в ответах существующих заявок) | нет | ничего | test_sd_queues::test_domain_removed_from_list_rejects_reply_in_existing_ticket_as_foreign_domain |

### 6.7. `tickets`

Создание общее для трёх каналов (письмо, форма, исполнитель). Каналы — константы `tickets.MAIL =
"mail"`, `tickets.FORM = "form"`, `tickets.STAFF = "staff"`. `Created` — `dataclass(frozen=True)`
в `tickets.py`: `ticket: Ticket`, `entry: TicketEntry` (первый элемент ленты, `kind=incoming`),
`after_hours: str \| None` (`None` — рабочее время или канал `staff`; `""` — нерабочее время, даты
нет; иначе строка «ДД.ММ.ГГГГ ЧЧ:ММ» по Москве без слова «с»). Константа `tickets.UNSET` —
метка «не менять» у `update_fields` (отличает «не передано» от `None`).
Ссылки на продолжение и на предыдущую заявку проверяются по HTML карточки (раздел 13, часть d);
отдельного сервиса нет.

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `next_number` | `next_number()` | `int`: `SELECT nextval('servicedesk_ticket_number')` одним запросом без подстановок; откат транзакции номер не возвращает | нет | ничего | test_sd_create::test_ticket_number_from_sequence_starts_at_one_and_grows, test_ticket_number_not_reused_after_rollback_gap_allowed |
| `create` | `create(*, channel, subject, text, requester_email, requester_name="", client_unit_id=None, category=None, queue_id=None, priority=None, complexity=None, source=None, take_by=None, created_by=None, consent_at=None, previous=None, inbound_id=None, at=None, ip=None)` | `Created`. Порядок плана: номер; адрес строчными; `Requester` под `select_for_update` (нет — создаётся с `origin="ticket"`); ФИО заявки — `requester_name`, иначе имя из записи, иначе пусто; пустое ФИО записи заполняется введённым (непустое не перезаписывается); подразделение: `FORM` — выбранное идёт в заявку, а в запись только если там пусто; «нет в списке» (`None`) и `MAIL` — подразделение записи или пусто; `STAFF` — переданное идёт в заявку и **всегда** в запись (`None` стирает подразделение записи — решение Opus RB1-14); очередь — `category.queue_id`, у «Другое» и у письма без категории — очередь по умолчанию, `queue_id` (только `STAFF`) перекрывает; критичность — `priority` или из настроек (`FORM` и `MAIL` передают `None`); источник — `source` у `STAFF` (ручной), системный `mail` или `form` у остальных; статус «новая» по умолчанию, ответственный: `take_by` (`User`, только `STAFF`), если он `is_participant` очереди, иначе (в том числе у не участника) ответственный по умолчанию категории, если он сейчас `is_participant` очереди; с ответственным — `assigned_once=True`, статус «в работе» по умолчанию, письма «взята в работу» нет; `kind` — копия вида статуса; первый элемент `incoming`: автор — `created_by` у `STAFF` (`last_message_from="staff"`), у `MAIL` и `FORM` — адрес и ФИО заявителя (`last_message_from="requester"`); `last_message_at` — время элемента; `consent_at` только у `FORM`; `previous` — закрытая заявка: у неё в ленте событие «продолжение», у новой `previous` ссылается на прежнюю; `inbound_id` — `InboundMail` у `MAIL`; `at` — время первого элемента (по умолчанию «сейчас»); `after_hours` считается для `MAIL` и `FORM` вызовом `org.calendar.is_working_time` и `next_working_start` в момент создания; типы аргументов: `category`, `priority`, `complexity`, `source` — объекты, `queue_id`, `client_unit_id` — числа | `email_required`, `no_queue`, `not_queue` (очередь не отмечена), `source_required` (`STAFF`), `archived_value` (архивные категория, критичность, сложность, подразделение); `ValueError` на неизвестный `channel` | журнал `ticket.created` (у `FORM` — с `ip`); событие ленты о назначении при ответственном (раздел 9); **в той же транзакции** зов `search.index(ticket)` (b2); **после фиксации** (через `on_commit`): `letters.send(ticket, "ticket.confirmation", entry=entry, extra={"after_hours": after_hours})`, шина `events.ticket_created(ticket)`; вложения `create` не принимает: зовущий вызывает `attachments.accept(entry, parts)` в той же транзакции после `create` | test_sd_create (все), test_sd_assignment::test_category_default_assignee_assigned_on_creation_when_still_queue_member, test_taken_letter_not_sent_on_creation_with_assignee, test_sd_status::test_created_without_assignee_status_is_new, test_sd_closing_2::test_letter_after_term_creates_new_ticket_with_previous_and_confirmation |
| `get_for` | `get_for(user, number)` | `Ticket` из `access.visible_tickets(user)` с `select_related("status", "priority", "category", "assignee")`; очередь — число `queue_id`, узел не загружается (модели `org` не импортируются) | `django.http.Http404` — заявки нет или она не видна (одно и то же) | ничего | test_sd_access::test_foreign_ticket_page_404_same_as_missing_number, test_every_ticket_action_route_404_for_foreign_ticket_same_as_missing |
| `set_status` | `set_status(ticket, status, *, actor, reason, ip=None, start_countdown=True)` («уточнение»: `ip`, `start_countdown`) | `bool` — статус изменился; тот же статус — `False`, ничего не пишется. Меняет `status` и `kind`; `reason` — код причины: `assigned`, `reply`, `letter`, `manual`, `close`, `autoclose`, `reopen`; в `data["reason"]` события ленты идут все семь кодов; отсчёт: вход в вид `waiting` из другого вида ставит `waiting_since = now`, **кроме** случая `start_countdown=False` (ответ с флажком: отсчёт ставит `replies`, 6.10); переход внутри вида `waiting` `waiting_since` не трогает; выход из `waiting` снимает его; вход в `closed` и выход из `closed` — как выход из прежнего вида | нет (проверки допустимости — в вызывающих функциях) | событие ленты «статус: было → стало» (раздел 9) при **каждой** смене статуса, включая закрытие, автозакрытие и открытие заново (plan.md:721-722; решение Opus C1 отменено итоговой сверкой, F4-2); события `closed`, `autoclosed`, `reopened` пишутся сверх него; журнал `ticket.updated` со статусом до и после, **кроме** `reason` `close`, `autoclose`, `reopen`: их журнал пишут `closing.*` своим кодом (решение Opus B1-3) | test_sd_status (все), в том числе `test_every_status_change_writes_feed_event_was_became` (T-3110: все причины, включая закрытие, автозакрытие и открытие заново), test_sd_status_autoclose |
| `set_status_manual` | `set_status_manual(ticket, status, *, actor, ip=None)` | `bool`; ручная смена из карточки (FR-209): только статусы из `dictionaries.manual_statuses()`; из `new` в `in_progress` без ответственного разрешено; смена на `waiting` ставит `waiting_since` сразу, письма нет; вызывает `set_status(..., reason="manual")` | `no_access`, `ticket_closed`, `bad_status` (вид `new` или `closed`, архивный) | как у `set_status` | test_sd_status::test_manual_change_between_in_work_and_waiting_kinds_works, test_manual_change_to_new_or_closed_kind_refused_even_direct_request, test_manual_new_to_in_work_without_assignee_allowed, test_manual_change_to_waiting_sends_no_letter_and_sets_waiting_since, test_change_within_waiting_kind_keeps_waiting_since |
| `add_incoming` | `add_incoming(ticket, *, author_email, author_name="", text, at=None, inbound_id=None, cc=())` | `TicketEntry` вида `incoming` в **открытой** заявке (повторное открытие — `closing.reopen` до вызова, зовёт `intake`); автор — адрес и ФИО из письма; `cc` — пары `(адрес, ФИО)`, уже отобранные `intake` (домены, адрес ящика, заявитель); `add_incoming` создаёт участников из всех переданных пар, из них создаются `TicketParticipant` (у существующего участника ничего, у снятого — не восстанавливаются: письмо от снятого `intake` не дописывает, это решает `intake`); `last_message_at` и `last_message_from` (`requester`; адрес участника — тоже `requester`) обновляются; заявка вида `waiting` переходит в «в работе» по умолчанию и теряет `waiting_since` (`set_status(..., reason="letter", actor=None)`); вид `new` и `in_progress` статус не меняют | `ticket_closed` (дописывать в закрытую нельзя) | в той же транзакции `search.index(ticket, entry)`; **после фиксации** `events.reply_received(ticket)`; журнала нет (письмо не событие журнала) | test_sd_status::test_requester_or_participant_letter_in_waiting_moves_to_in_work, test_requester_letter_in_new_or_in_work_keeps_status, test_sd_card::test_last_message_updated_only_by_letters_and_replies |
| `update_fields` | `update_fields(ticket, *, actor, ip=None, priority=UNSET, complexity=UNSET, client_unit_id=UNSET, requester_name=UNSET, save_name_to_record=False)` | `list[str]` — имена изменённых полей (`priority`, `complexity`, `client_unit`, `requester_name`) по порядку аргументов; типы аргументов: `priority` — объект `Priority` (у заявки критичность есть всегда: `None` — `TypeError`), `complexity` — объект `Complexity` или `None` (очистить), `client_unit_id` — целое или `None`, `requester_name` — строка; групповое действие и маршрут находят объект по номеру (`priority_id`, `priority`) и передают его; `None` у `complexity` и `client_unit_id` очищает поле; подразделение пишется и в заявку, и в запись заявителя **всегда**; `save_name_to_record=True` пишет ФИО ещё и в запись заявителя; темы среди аргументов нет (тема не правится: лишний ключ — `TypeError`); одно событие ленты на каждое изменённое поле, у ФИО заявителя без значений; ничего не изменилось — ничего не пишется | `no_access`, `ticket_closed`, `archived_value` (архивные критичность, сложность, подразделение) | события ленты (раздел 9); журнал `ticket.updated`: критичность, сложность, подразделение до и после; ФИО — только «изменено»; при смене ФИО заявителя зовёт `search.rebuild(ticket)` | test_sd_assignment_2::test_criticality_and_complexity_edit_write_event_per_field, test_department_edit_writes_to_ticket_and_requester_record_always, test_requester_name_edit_event_has_no_values, test_requester_name_save_also_in_record_button, test_subject_not_editable, test_archived_criticality_and_complexity_not_offered, test_closed_ticket_category_and_fields_change_refused_with_200_and_message |
| `remove_participant` | `remove_participant(ticket, participant_id, *, actor, ip=None)` | `None`: `removed_at = now`, `removed_by = actor`; снятый не получает писем и не дописывает в заявку; снятого повторно — тихо ничего; `participant_id` другой заявки — `django.core.exceptions.ObjectDoesNotExist` (на деле `TicketParticipant.DoesNotExist`) | `no_access`, `ticket_closed` | событие ленты без адреса (раздел 9); журнал `ticket.participant_removed` с номером участника | test_sd_assignment_2::test_remove_participant_marks_removed_and_writes_feed_and_journal_without_address, test_removed_participant_gets_no_letters, test_removed_participant_letter_not_appended_to_ticket, test_closed_ticket_participant_removal_refused_with_200_and_message |
| функции добавления участника нет | в модулях `tickets`, `assignment`, `replies` нет имён `add_participant` и им подобных: участники появляются только из копии входящих писем (`add_incoming`, параметр `cc`) | проверка: `not hasattr` у модулей и нет маршрута (раздел 12) | - | - | test_sd_assignment_2::test_no_route_or_service_to_add_participant |
| `require_open` | `require_open(ticket)` | `None`; помощник модулей среза | `ticket_closed` | ничего | test_sd_assignment_2 |

### 6.8. `assignment`

Ответственного ставят и снимают только эти функции (и `reconcile`, 6.12). Первое появление
ответственного (`assigned_once` ложно): `assigned_once=True`, статус «новая» → «в работе» по
умолчанию (`tickets.set_status(..., reason="assigned")`), **после фиксации** `letters.send(ticket,
"ticket.assigned")` (письмо один раз; повторное назначение и снятие писем не дают). Каждое
изменение ответственного пишет событие ленты «ответственный: было → стало» (раздел 9) и событие
шины `events.assignee_changed`. `Skipped` и `BulkResult` — `dataclass(frozen=True)` в
`assignment.py`: `Skipped(number: int \| None, code: str, message: str)` (`number=None` у
недоступной заявки: номер не раскрывается), `BulkResult(done: list[int], skipped: list[Skipped])`
(номера выполненных и пропущенных в порядке входа).

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `take` | `take(ticket, *, actor, ip=None)` | `bool` — ответственный изменился; проверки по порядку `no_access`, `ticket_closed`, `not_participant`; затем ставит `actor`; уже он — `False` | `no_access`, `ticket_closed`, `not_participant` | журнал `ticket.assigned`; событие ленты; шина; письмо при первом появлении | test_sd_assignment::test_take_for_self_by_queue_member_sets_assignee_and_in_work, test_take_for_self_by_non_member_refused_even_direct_request, test_first_assignee_sends_taken_into_work_letter_once_with_name_and_surname, test_taken_letter_not_repeated_on_reassign_or_after_unassign |
| `assign` | `assign(ticket, user, *, actor, ip=None)` | `bool`; `user` — `User`; тот же — `False` | `no_access`, `ticket_closed`, `not_participant` (в том числе уволенный и не из очереди) | как у `take` | test_sd_assignment::test_assign_non_member_of_queue_refused_even_direct_request, test_assignee_changes_write_feed_event_was_became, test_sd_assignment_2::test_closed_ticket_assign_and_transfer_refused_with_200_and_message |
| `unassign` | `unassign(ticket, *, actor, ip=None)` | `bool`; письма нет; `assigned_once` остаётся истинным, статус не меняется | `ticket_closed`, `no_access` | журнал `ticket.assignee_removed` (причина «вручную»); событие ленты; шина | test_sd_assignment::test_unassign_without_letter_writes_feed_event, test_taken_letter_not_repeated_on_reassign_or_after_unassign |
| `apply_default_assignee` | `apply_default_assignee(ticket, *, actor=None, ip=None)` | `bool`: у заявки нет ответственного, у категории `default_assignee` есть и он сейчас `is_participant` очереди заявки — назначает как первое появление (с письмом, если `assigned_once` был ложен); категории нет — `False`; зовёт только `transfer.change_category`; `tickets.create` назначает ответственного сам (6.7): без письма и без события `assignee_changed` | нет | как у `assign` (для вызова из `change_category`) | test_sd_assignment::test_category_default_assignee_not_member_any_more_leaves_ticket_unassigned, test_ticket_without_category_default_assignee_has_no_assignee, test_letter_without_category_gets_no_default_assignee |
| `bulk` | `bulk(numbers, action, *, actor, ip=None, **params)` | `BulkResult`; `numbers` — список номеров (не больше 100, повторы убираются с сохранением порядка); `action` — `"assign"` (`params`: `user` — объект `User`; маршрут по id находит пользователя, неизвестный id — пропуск каждой заявки с кодом `not_participant`), `"transfer"` (`queue_id` — int, `reason=""`), `"priority"` (`priority_id` — int); для каждого номера: `tickets.get_for(actor, number)` (не видна — пропуск `no_access`, `number=None`), затем та же функция, что в карточке (`assign`, `transfer.transfer`, `tickets.update_fields`), каждая в своём `transaction.atomic()` (точка сохранения; функции зовутся через имя модуля, точка подмены — раздел 3.5); отказ отдельной заявки (`not_participant`, `ticket_closed`, `archived_value`) — пропуск с `code` и сообщением ошибки, остальные применяются | `bulk_limit` (до всякой работы), `bad_action` | всё пишут вызванные функции | test_sd_assignment_2::test_group_assign_applies_to_all_when_candidate_is_queue_member, test_group_transfer_unassigns_non_member_of_new_queue, test_group_change_criticality_applies_to_available_tickets, test_group_over_hundred_tickets_refused, test_group_skips_inaccessible_ticket_without_revealing_number, test_group_skips_inapplicable_ticket_with_reason_and_applies_others, test_group_skips_closed_ticket_with_reason, test_group_each_ticket_in_own_savepoint, test_sd_access::test_group_action_checks_access_of_each_ticket_separately |

### 6.9. `transfer`

`TransferResult` — `dataclass(frozen=True)` в `transfer.py`: `queue_changed: bool`,
`assignee_removed: bool`, `visible_after: bool` (видна ли заявка `actor` после передачи; от него
зависит `HX-Redirect`, раздел 12). `CategoryResult`: `needs_confirmation: bool`, `new_queue_id:
int \| None`, `applied: bool`, `queue_changed: bool`, `assignee_removed: bool`, `assignee_set:
bool` (назначен ответственный по умолчанию новой категории).

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `target_queues` | `target_queues(ticket)` | `list[UnitRef]`: отмеченные узлы, кроме текущей очереди заявки (`queues.marked_units()`) | нет | ничего | test_sd_assignment::test_transfer_requires_queue_among_marked_nodes_except_current |
| `transfer` | `transfer(ticket, queue_id, *, reason="", actor, ip=None)` | `TransferResult`; одна транзакция: новая очередь; ответственный снимается, если он не `is_participant` новой очереди (остаётся, если участник); причина обрезается пробелами, пустая допустима | `ticket_closed`, `queue_required`, `not_queue`, `same_queue`, `reason_too_long`, `no_access` | событие ленты «кто, откуда, куда, причина» (раздел 9; причина — текстом в ключе `reason_text`, только в ленте); журнал `ticket.transferred` без текста причины (есть только «указана ли»); при снятии ответственного ещё `ticket.assignee_removed` и шина `assignee_changed` | test_sd_assignment::test_transfer_reason_optional_up_to_500_characters, test_transfer_removes_assignee_not_in_new_queue_keeps_member, test_transfer_event_who_from_to_reason_and_journal_without_reason, test_transfer_to_unavailable_ticket_returns_hx_redirect_with_message |
| `change_category` | `change_category(ticket, category, *, confirmed=False, actor, ip=None)` | `CategoryResult`; очередь новой категории (у «Другое» — по умолчанию) отличается от текущей и `confirmed=False` — ничего не меняется, `needs_confirmation=True`, `new_queue_id` заполнен; тот же узел очереди — подтверждение не нужно, `applied=True`; при смене очереди ответственный снимается, если он не участник новой очереди; ответственного нет — зовётся `assignment.apply_default_assignee` (с письмом «взята в работу», если оно ещё не уходило) | `ticket_closed`, `archived_value`, `no_queue`, `no_access` | одно событие ленты на смену категории и одно на смену очереди (раздел 9); журнал `ticket.updated` (категория до и после), при смене очереди ещё `ticket.transferred` | test_sd_assignment::test_category_change_to_other_queue_asks_confirmation_first, test_category_change_confirmed_changes_queue_with_two_events, test_category_change_assigns_new_default_assignee_with_taken_letter, test_category_change_removes_assignee_not_in_new_queue, test_category_change_within_same_queue_needs_no_confirmation |


### 6.10. `replies`

Все записи ленты делает этот модуль: ленту дополняют, меняют только служебные поля отправки ответа
(`send_state`, `mail`) и тексты при обезличивании (раздел `retention`, b2). Функций изменения и
удаления элементов нет: проверка — у модуля `replies` нет имён `update_*`, `edit_*`, `delete_*`,
`remove_*`. `FeedItem` — `dataclass(frozen=True)`: `entry: TicketEntry`, `author_name: str`,
`author_kind: str` (`staff`, `requester`, `participant`, `system`), `author_dismissed: bool`,
`author_address: str`, `mail_status: str` (`MailMessage.status` для `reply`, иначе пусто).

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `add_event` | `add_event(ticket, event, *, actor=None, data=None)` | `TicketEntry` вида `event` с кодом `event` и `data` (по умолчанию `{}`); `at = now`; `last_message_*` не меняет; единственная точка записи событий для всех модулей среза; `event` — код из раздела 9 | нет | ничего | test_sd_card::test_comment_and_event_do_not_change_last_message, test_feed_service_only_appends |
| `feed` | `feed(ticket)` | `list[FeedItem]` по `(at, id)`: записи с `select_related("author", "mail")` и вложениями; не больше двух запросов независимо от числа элементов (решение Opus B1-2); автор: сотрудник — имя (`author_dismissed` у уволенного), у `incoming` — адрес (`participant`, если адрес в `TicketParticipant`, иначе `requester`), у событий без автора — `system` | нет | ничего | test_sd_card::test_feed_ordered_by_time_with_authors_and_attachments_in_one_query, test_feed_shows_letters_replies_comments_and_events_together, test_feed_authors_staff_name_dismissed_mark_requester_and_participant_address, test_card_shows_mail_state_from_mail_message |
| `reply` | `reply(ticket, *, text, parts=(), wait_flag=False, actor, ip=None)` | `TicketEntry` вида `reply`; `text` обрезается пробелами; `parts` — принятые файлы формы (список, как у `attachments.accept`); одна транзакция: элемент `reply` (`wait_flag` запомнен), `attachments.accept(entry, parts)` (отказ вложений — `ServiceDeskError` из `attachments`, раздел b2, транзакция откатывается целиком), смена статуса по FR-208: с флажком — `set_status(..., "waiting" по умолчанию, reason="reply", start_countdown=False)` из любого открытого вида, без флажка из `new` и `waiting` — в «в работе» по умолчанию, из `in_progress` статус не меняется; `last_message_at` и `last_message_from="staff"`; без вложений или при всех чистых — `send_state="queued"`, письмо `letters.send(ticket, "ticket.reply", entry=entry)`, и при флажке и виде `waiting` `waiting_since = now`; иначе `send_state="waiting_files"` | `ticket_closed`, `text_required`, `text_too_long`, `no_access` | журнал `ticket.reply_sent` (факт и номер элемента); поиск `search.index(ticket, entry)`; после фиксации письмо в очередь | test_sd_reply::test_reply_without_attachments_goes_to_queue_at_once, test_reply_text_required_plain_up_to_50_thousand, test_reply_with_attachments_waits_in_waiting_files, test_reply_without_flag_sets_no_waiting_since, test_reply_to_closed_ticket_refused_with_message, test_sd_status::test_reply_with_flag_moves_to_default_waiting_status, test_reply_without_flag_from_new_or_waiting_moves_to_default_in_work_and_stops_countdown, test_reply_without_flag_in_work_keeps_own_status, test_reply_with_flag_sets_waiting_since_at_queueing_of_letter |
| `on_files_checked` | `on_files_checked(entry_id)` | `None`; **вызывает `attachments`** (b2) из обработчика `file_purposes`, когда проверен последний файл ответа; в транзакции блокирует заявку и элемент; элемент уже не в `waiting_files` — выход; порядок: заявка закрыта — `not_sent` и событие «ответ не отправлен: заявка закрыта»; иначе есть файл в карантине или `Attachment.rejected="encrypted"` — `not_sent` и событие «ответ не отправлен: вложение «…» в карантине» (у архива с паролем — причина «архив с паролем»), письма и отсчёта нет; иначе все чистые: `queued`, `letters.send(ticket, "ticket.reply", entry=entry)`, при `wait_flag` и виде `waiting` `waiting_since = now` | нет | события ленты (раздел 9); при карантине журнал пишет `attachments` (`ticket.attachment_quarantined`) | test_sd_reply::test_reply_waits_while_files_are_checked_then_goes_when_all_clean, test_clean_files_with_flag_set_waiting_since_when_still_waiting_kind, test_reply_with_quarantined_file_not_sent_with_event, test_reply_with_quarantine_sends_no_letter_and_starts_no_countdown, test_reply_with_password_archive_not_sent_with_event, test_reply_with_ticket_closed_during_check_not_sent_ticket_closed, test_sd_status_autoclose::test_autoclose_not_counted_from_unsent_reply_with_quarantine |
| `resend` | `resend(entry, *, actor, ip=None)` | новый `TicketEntry` вида `reply` с тем же текстом, `resent_from=entry` и вложениями-копиями только чистых файлов (связи на те же `StoredFile` со статусом `clean`); `send_state`, письмо, смена статуса по FR-208 и `last_message_*` — как у `reply` (все файлы чисты — сразу `queued`); `wait_flag` берётся из исходного; отсчёт идёт от этой отправки | `ticket_closed`, `not_resendable` (не `reply` или не `not_sent`), `no_access` | журнал `ticket.reply_sent`; событие ленты не пишется | test_sd_reply::test_resend_without_infected_creates_new_item_with_clean_files_only, test_resend_item_keeps_text_and_link_to_original, test_resend_starts_countdown_from_this_sending, test_resend_button_only_on_not_sent_reply |
| `comment` | `comment(ticket, *, text, actor, ip=None)` | `TicketEntry` вида `comment`; без вложений и без письма; работает и на закрытой заявке; статус, `waiting_since`, `last_message_*` не меняет | `text_required`, `no_access` | журнал `ticket.comment_added` (факт и номер элемента); поиск `search.index(ticket, entry)` | test_sd_card::test_internal_comment_marked_internal_in_feed, test_internal_comment_sends_no_mail, test_sd_reply::test_internal_comment_is_not_sent_as_reply, test_sd_status::test_internal_comment_changes_no_status_and_no_waiting_since, test_sd_closing::test_internal_comment_on_closed_ticket_allowed_and_changes_nothing_else |
| `on_mail_failed` | `on_mail_failed(*, mail_id, related_ref)` | `None`; обработчик шины `mail.failed` (раздел 3.1; ключи данных те же); `related_ref` вида заявки читает по разделу 10; чужой `related_ref` (не `ticket.`) — выход; находит заявку и элемент, добавляет событие «письмо не доставлено: вид письма» | нет | событие ленты (раздел 9); журнал `ticket.mail_failed` (вид письма); работает как обработчик на `on_commit` | test_sd_reply::test_failure_after_last_retry_writes_not_delivered_event_in_feed, test_failure_after_last_retry_writes_journal_record, test_mail_server_down_reply_kept_in_ticket |

### 6.11. `closing`

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `close` | `close(ticket, status, resolution, *, actor, ip=None)` | `None`; `status` — `Status` вида `closed`; `resolution` обрезается пробелами; ставит `closed_at = now`, `closed_by = actor`, `resolution`, `waiting_since = None`, статус через `tickets.set_status(..., reason="close")` | `ticket_closed`, `no_access`, `resolution_required`, `resolution_too_long`, `bad_status` | события ленты: «статус: было → стало» (его пишет `tickets.set_status`, 6.7) и сверх него `closed` с `data` — статус и текст решения (раздел 9); журнал `ticket.closed` (статус до и после); шина `events.ticket_closed`; после фиксации `letters.send(ticket, "ticket.closed")` | test_sd_closing::test_close_sets_closed_at_closed_by_resolution_and_clears_waiting_since, test_close_event_has_status_and_resolution_text, test_close_publishes_ticket_closed_to_bus_and_writes_journal, test_close_sends_closed_letter_with_resolution_to_requester_and_participants, test_close_only_by_queue_member_or_assignee, test_close_of_already_closed_ticket_refused_with_message, test_sd_status::test_close_and_reopen_rows_use_chosen_and_default_statuses |
| `reopen` | `reopen(ticket, *, actor, ip=None, via="manual")` («уточнение»: `ip`, `via`) | `None`; `via` — `"manual"` или `"mail"` (`intake`, `actor=None`); если узел `queue_id` больше не очередь — очередь по умолчанию, событие «очередь: было → стало» с `data["reason"] = "queue_unmarked"`; ответственный остаётся, если он `is_participant` итоговой очереди, иначе снимается (обычно сверка уже сняла); статус «в работе» по умолчанию (`reason="reopen"`); `closed_at`, `closed_by`, `resolution` очищаются; ручной вызов у не видящего заявку — отказ | `ticket_open`, `no_access` (только при `actor` не `None`) | события ленты: «статус: было → стало» (`tickets.set_status`, 6.7) и сверх него `reopened` (раздел 9); журнал `ticket.reopened` (статус до и после, способ `manual` или `mail`); шина `events.assignee_changed` не публикуется, если ответственный не менялся; после фиксации `letters.send(ticket, "ticket.reopened")` | test_sd_closing_2::test_manual_reopen_in_any_term_with_reopened_letter, test_manual_reopen_refused_for_outsider_even_direct_request, test_manual_reopen_when_node_not_queue_goes_to_default_queue_with_event, test_reopen_keeps_assignee_who_is_member_of_final_queue, test_reopen_without_assignee_when_assignee_dismissed, test_reopen_clears_closed_at_closed_by_resolution_and_close_event_keeps_resolution, test_reopen_sets_default_in_work_status_with_event_and_journal, test_reopen_by_letter_sends_reopened_letter, test_requester_letter_within_term_reopens_in_work_same_queue_assignee_kept |
| `within_reopen_term` | `within_reopen_term(ticket)` | `bool`: `closed_at + reopen_days >= now`; срок читается из настроек при каждом вызове; для `intake` | нет | ничего | test_sd_closing_2::test_reopen_term_read_from_settings_on_each_letter, test_letter_after_term_creates_new_ticket_with_previous_and_confirmation, test_autoclosed_ticket_reopened_by_requester_within_term |
| `autoclose_one` | `autoclose_one(ticket_id, *, now=None)` | `bool`: в транзакции `select_for_update`, повторная проверка: вид `waiting` и `waiting_since <= now - autoclose_days` (срок читается из настроек при каждом вызове); иначе `False`; закрывает системным статусом `autoclosed` (`reason="autoclose"`), `closed_at = now`, `closed_by = None` | нет | события ленты: «статус: было → стало» (`tickets.set_status`, 6.7) и сверх него `autoclosed` (раздел 9); журнал `ticket.autoclosed` с `actor=None`; шина `events.ticket_closed`; после фиксации `letters.send(ticket, "ticket.autoclosed")` | test_sd_status_autoclose::test_autoclose_on_seventh_day_sets_system_status_closed_at_and_empty_closed_by, test_autoclose_sends_autoclosed_letter_to_requester_and_participants, test_autoclose_recheck_under_lock_skips_ticket_with_letter_between_select_and_close, test_autoclose_days_setting_read_on_each_run |
| `autoclose_batch` | `autoclose_batch(*, limit=50, after=None)` | `Batch` (`done` — сколько обработано): выбирает заявки вида `waiting` с `waiting_since <= now - autoclose_days` по `waiting_since`, затем `id`, не больше `limit`, строго после курсора `after=(waiting_since, id)` последней отобранной заявки прежней порции (решение Opus RC-3); для каждой — `autoclose_one`; `more=True`, если выбрано ровно `limit`; `last` — курсор (`waiting_since`, `id`) последней отобранной заявки; заявка, которую закрыть не удалось, в этом запуске больше не выбирается; вид `in_progress` не закрывается, как бы ни была стара заявка | нет | задание `autoclose` (раздел 7) зовёт функцию и ставит следующую порцию, если `more` | test_sd_status_autoclose::test_autoclose_processes_in_batches_of_fifty, test_autoclose_skips_in_work_kind_of_any_age, test_autoclose_not_on_sixth_day_and_not_after_requester_letter, test_autoclose_after_manual_waiting_change_without_letter |

### 6.12. `reconcile`

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `for_users` | `for_users(user_ids)` | `int` — сколько заявок лишилось ответственного; `user_ids` — итерируемое номеров или `None` (все, у кого есть заявки с ответственным); для каждого человека: сначала, вне `transaction.atomic()`, один запрос `Ticket.objects.filter(assignee_id=...).exists()` — нет — выход без транзакции (одного запроса достаточно); иначе `transaction.atomic()` и `access.scope(user, fresh=True)`; при `has_all` выход; со всех его заявок (открытых и закрытых), чей `queue_id` не в `work_units`, снимается `assignee`; `closed_by` и `author` не трогаются | нет | на каждую заявку: событие ленты «ответственный снят: больше не участник очереди» (раздел 9), журнал `ticket.assignee_removed` с `actor=None` и причиной, шина `events.assignee_changed`; каждый человек в своей транзакции | test_sd_reconcile (все, кроме порционных), test_sd_assignment::test_transfer_removes_assignee_not_in_new_queue_keeps_member |
| `on_access_changed` | `on_access_changed(*, user_ids)` | `None`; обработчик шины `access.changed` (раздел 3.1, ключ данных `user_ids`: список или `None`); зовёт `for_users(user_ids)`; подписывается через `events.register()` (6.13); работает только в обратных вызовах `on_commit`, ошибка не откатывает публиковавшее действие | нет | как `for_users` | test_sd_reconcile::test_handler_runs_only_in_on_commit_callbacks, test_handler_error_does_not_roll_back_publishing_action, test_unit_roles_change_triggers_reconcile, test_personal_roles_change_triggers_reconcile, test_role_rights_change_triggers_reconcile_for_all_with_tickets |
| `batch` | `batch(*, after_id=0, size=50)` | `Batch`: `done` — число людей порции; порция людей, у кого есть заявки с ответственным (`assignee_id` различные), по возрастанию `id` после `after_id`, не больше `size`; для каждой порции `for_users`; `last_id` — последний `id` порции, `more=True`, если порция полная | нет | задание `reconcile_assignees` раз в час (раздел 7) зовёт `batch` и ставит следующую порцию с `after_id=last_id` | test_sd_reconcile::test_hourly_task_reconciles_all_users, test_hourly_task_takes_fifty_people_per_batch_and_enqueues_next_batch |

Проверки без отдельной функции (читают результат): сохранность имён в карточке и списке после
снятия (`closed_by`, `author` —
test_sd_reconcile::test_closed_by_name_kept_in_card_and_list_after_assignee_removed,
test_history_keeps_who_handled_ticket_after_removal,
test_dismissed_name_marked_in_messages_and_closed_tickets); показ в пресете «Без ответственного»
(раздел 12, test_removed_assignee_tickets_listed_in_preset_without_assignee); открытие заново без
ответственного (`closing.reopen`, test_reopened_ticket_of_removed_assignee_has_no_assignee).

### 6.13. `events`

Публикует события `servicedesk.*` шиной ядра (`apps.core.events.publish`, раздел 3.1); ключи
данных — те, что раздел 3.1 даёт для четырёх событий (`number`, `queue_id`, `assignee_before_id`,
`assignee_after_id`). Внутри модуля шина импортируется как `from apps.core import events as bus`
(имя модуля совпадает).

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| константы | `events.TICKET_CREATED = "servicedesk.ticket_created"`, `ASSIGNEE_CHANGED = "servicedesk.assignee_changed"`, `REPLY_RECEIVED = "servicedesk.reply_received"`, `TICKET_CLOSED = "servicedesk.ticket_closed"` | - | - | - | test_sd_boundaries::test_servicedesk_events_carry_ticket_number_queue_and_assignees |
| `ticket_created` | `ticket_created(ticket)` | `None`; до и после — текущий ответственный (у новой заявки `assignee_before_id` — по разделу 3.1) | нет | `publish(TICKET_CREATED, ...)` | test_sd_boundaries |
| `assignee_changed` | `assignee_changed(ticket, *, before_id, after_id)` | `None` | нет | `publish(ASSIGNEE_CHANGED, ...)`; зовут `assignment`, `reconcile`, `transfer` (при снятии), `tickets.create` не зовёт (там `ticket_created`) | test_sd_boundaries, test_sd_reconcile::test_removed_assignee_leaves_feed_event_journal_entry_and_bus_event |
| `reply_received` | `reply_received(ticket)` | `None`; до и после равны текущему ответственному | нет | `publish(REPLY_RECEIVED, ...)`; зовёт `tickets.add_incoming` | test_sd_boundaries |
| `ticket_closed` | `ticket_closed(ticket)` | `None` | нет | `publish(TICKET_CLOSED, ...)`; зовут `closing.close` и `closing.autoclose_one` | test_sd_closing::test_close_publishes_ticket_closed_to_bus_and_writes_journal |
| `register` | `register()` | `None`; вызывается из `AppConfig.ready()` приложения: подписывает `access.changed` -> `reconcile.on_access_changed`, `mail.failed` -> `replies.on_mail_failed`; повторный вызов безвреден (шина игнорирует ту же функцию) | нет | `subscribe` | test_sd_reconcile, test_sd_reply, test_sd_boundaries |

### 6.14. `mail_parse`

Чистые функции без моделей и без базы: `apps/servicedesk/services/mail_parse.py` (задача T-3209; в
плане отдельным модулем не назван, имя дано задачей; решение B2-1). Тесты T-3108 зовут их
напрямую, `intake` берёт из них весь разбор. `Part` — `dataclass(frozen=True)`: `name: str`,
`data: bytes`, `content_type: str = "application/octet-stream"`, `inline: bool = False`; тот же
класс принимает `attachments.accept` (экспорт `attachments.Part`). `ParsedMail` —
`dataclass(frozen=True)`: `sender: str` (строчными, пусто, если адреса нет), `sender_name: str`,
`subject: str`, `text: str`, `parts: list[Part]`, `cc: list[tuple[str, str]]`, `message_id: str`,
`link_ids: list[str]`, `subject_number: int \| None`, `automatic: bool`.

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `load` | `load(raw)` | `email.message.EmailMessage` из `email.message_from_bytes(raw, policy=email.policy.default)` | исключение разбора идёт наружу (шаг `parse` в `intake`) | ничего | test_sd_intake::test_error_on_any_step_rolls_back_marks_parse_error_last_error_step_and_class_only |
| `parse` | `parse(raw)` | `ParsedMail`: собирает результат всех функций ниже; `message_id` — заголовок `Message-ID` как есть (пусто, если его нет) | как у `load` | ничего | test_sd_mail_parse (все) |
| `sender_of` | `sender_of(message)` | `tuple[str, str]`: адрес первого адреса `From` (`addresses[0].addr_spec`) строчными и его имя после `clean_text`; нет адреса или он без `@` и домена — `("", имя)` | нет | ничего | test_sd_mail_parse::test_requester_name_from_from_header_rfc2047, test_raw_8bit_name_surrogates_cleaned_before_saving, test_sd_intake::test_from_without_address_or_domain_treated_as_foreign |
| `clean_text` | `clean_text(value)` | `str`: суррогаты убраны (`value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")`), символ NUL заменён пробелом (решение Opus B2-2); остальное не меняется | нет | ничего | test_sd_mail_parse::test_nul_replaced_in_text_and_subject, test_raw_8bit_name_surrogates_cleaned_before_saving |
| `clean_subject` | `clean_subject(value)` | `str`: `clean_text`, затем переводы строк, табуляции и управляющие знаки заменены пробелом, подряд идущие пробелы сжаты, края обрезаны, не длиннее 255 знаков; его же зовёт `tickets.create` (тема заявки) | нет | ничего | test_sd_mail_parse::test_subject_cleaned_of_line_breaks_and_control_chars, test_sd_letters::test_subject_is_number_and_ticket_subject_with_control_chars_cleaned |
| `body_text` | `body_text(message)` | `str`: `get_body(preferencelist=("plain", "html"))`; текстовая часть берётся как есть, только HTML — `html_to_text`; `LookupError` кодировки или символ U+FFFD в тексте — запасной путь `fallback_decode(part)`; тела нет — `""`; результат после `clean_text`; концы строк приводятся к `\n`, убираются только завершающие переводы строки (`.rstrip("\n")`), начало и середина текста — как есть (решение Opus Д1, итоговая сверка F1-10) | нет | ничего | test_sd_mail_parse::test_plain_only_text_taken_as_is (ждёт текст без завершающего `\n`: `build_mail` через `set_content` его добавляет), test_html_only_converted_to_text_without_markup, test_alternative_prefers_plain_part, test_windows_1251_body_decoded, test_koi8_r_body_decoded, test_unknown_charset_and_replacement_char_use_fallback_path, test_mail_without_body_gives_empty_text |
| `html_to_text` | `html_to_text(html)` | `str`: разбор на `html.parser`; `script` и `style` с содержимым пропущены; `br`, `p`, `div`, `li`, `tr` дают перевод строки; сущности раскрыты; теги не остаются | нет | ничего | test_sd_mail_parse::test_html_script_and_style_dropped_entities_expanded_line_breaks_kept |
| `fallback_decode` | `fallback_decode(part)` | `str`: байты части, пробуются `utf-8`, `cp1251`, `koi8-r` по порядку, последняя попытка — с `errors="replace"` | нет | ничего | test_sd_mail_parse::test_unknown_charset_and_replacement_char_use_fallback_path |
| `attachment_parts` | `attachment_parts(message)` | `list[Part]`: обход `walk()`, не `iter_attachments()`; вложение — каждая конечная часть, кроме выбранного текста и его HTML-пары; часть с `Content-ID` и `Content-Disposition: inline` — с `inline=True`, без `Content-ID` — обычное вложение; `message/rfc822` — одна часть `.eml`, потомки вложенного письма пропускаются; имя — `clean_filename(name, index)`, `index` — номер вложения среди найденных (с 1, считаются все вложения, в том числе именованные); у `message/rfc822` без имени — «вложение-N.eml»; `Part.data` — байты вложенного письма (`part.as_bytes()`), `content_type` `message/rfc822`; порядок обхода | нет | ничего | test_sd_mail_parse::test_attachments_found_by_walk_including_inline_picture_in_nested_related, test_inline_without_content_id_is_attachment, test_inline_picture_with_content_id_marked_inline_attachment, test_nested_mail_is_single_eml_attachment_children_not_entered |
| `clean_filename` | `clean_filename(name, index)` | `str`: имя из `get_filename()` (RFC 2231 и 2047 раскрыты библиотекой); берётся последняя часть пути (разделители `/` и `\`), управляющие знаки убраны, не длиннее 255; пустое — «вложение-N», где N — `index` (с 1) | нет | ничего | test_sd_mail_parse::test_attachment_name_rfc2231_and_rfc2047_decoded, test_attachment_name_path_and_control_chars_cleaned_cut_to_255, test_nameless_attachment_gets_attachment_n_name |
| `link_ids` | `link_ids(message)` | `list[str]`: идентификаторы выражением `<[^<>\s]+>` из `In-Reply-To`, затем из `References` от последнего к первому, без повторов | нет | ничего | test_sd_intake::test_in_reply_to_with_extra_text_extracted_by_regex, test_link_by_in_reply_to_and_references_to_outgoing_and_inbound_ids |
| `subject_number` | `subject_number(subject)` | `int \| None`: первое вхождение `[#N]` в теме (выражение `\[#(\d+)\]`); `N` больше 2147483647 — `None` | нет | ничего | test_sd_intake::test_ticket_number_in_subject_beats_in_reply_to_headers |
| `cc_pairs` | `cc_pairs(message)` | `list[tuple[str, str]]`: пары (адрес строчными, имя после `clean_text`) из всех заголовков `Cc` (`get_all("Cc")`), без повторов, адреса без `@` пропущены; фильтр по домену, ящику, `settings.DEFAULT_FROM_EMAIL` и заявителю делает `intake` | нет | ничего | test_sd_mail_parse::test_cc_addresses_collected_from_all_cc_headers, test_sd_intake::test_cc_corporate_addresses_become_participants_excluding_mailbox_smtp_from_requester_duplicates |
| `is_automatic` | `is_automatic(message)` | `bool`: `Auto-Submitted` не `no` (без учёта регистра, до первой «;»), или `Precedence` равен `bulk`, `junk` или `list`, или `Return-Path` равен `<>` | нет | ничего | test_sd_intake::test_auto_submitted_precedence_and_empty_return_path_are_automatic_no_ticket_no_append_no_confirmation, test_auto_submitted_no_is_not_automatic |

### 6.15. `mailbox`

Опрос ящика: `apps/servicedesk/services/mailbox.py`. Соединение — только `imap.connect()` через
модуль (раздел 5.1). Замок — ключ Valkey `servicedesk:poll`, значение случайное
(`secrets.token_urlsafe()`), `SET NX EX 120`, продление и снятие — сценарием, сверяющим значение.
Константы: `LOCK_KEY`, `LOCK_TTL = 120`, `PER_RUN = 20`, `RECREATE_WINDOW_MINUTES = 10`,
`REQUEUE_AFTER_MINUTES = 3`. `PollResult` — `dataclass(frozen=True)`: `state: str` (`ok`,
`disabled` — `IMAP_HOST` пуст, `locked` — замок занят, `unavailable` — ошибка ящика), `fetched:
int` (скачано и сохранено), `known: int` (известные пары, только продвинули `last_uid`).
`MailboxStatus` — `dataclass(frozen=True)`: `address: str`, `last_ok_at`, `last_poll_at`,
`last_error: str`, `configured: bool` (`bool(settings.IMAP_HOST)`; `False` — единственное
условие «ящик не подключён», решение Opus F4-6), `connected: bool`
(`MailboxState.uidvalidity is not None`: первое подключение состоялось; на «ящик не
подключён» не влияет; решение Opus RB2-5). Задание `poll_mailbox` (раздел
7) зовёт `poll()` и ничего не повторяет сам.

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `poll` | `poll()` | `PollResult`; порядок: `IMAP_HOST` пуст — `disabled` без подключения (`fake.connects == 0`); замок занят — `locked`; соединение; первое подключение (строки `MailboxState` нет или `uidvalidity is None`), смена UIDVALIDITY или обычный порядок; не больше `PER_RUN` скачиваний за запуск, по возрастанию UID; фильтр `uid > last_uid` делает `poll` (адаптер отдаёт ответ сервера как есть); письма, чья пара `(uidvalidity, uid)` уже есть в базе, не скачиваются, а лишь двигают `last_uid`; замок продлевается после каждого забранного письма и снимается в `finally` только своим значением; `MailboxUnavailable` (и ошибка `fetch`) не поднимается: `last_error` и лог получают текст через `tasks.safe_error`, повтора нет; если строки нет, она создаётся при этой первой ошибке (`last_error`, `last_poll_at`, `uidvalidity` и `last_uid` — `None`); удачный запуск ставит `last_poll_at`, `last_ok_at`, очищает `last_error` | нет (ошибки ящика попадают в `PollResult.state` и `MailboxState.last_error`) | журнал `mailbox.connected` (первое подключение: UIDVALIDITY и `last_uid`), `mailbox.recreated` (UIDVALIDITY до и после, сколько писем пропущено); **после фиксации** каждого письма `intake.enqueue(id)`; разбор не идёт в фоне до фиксации | test_sd_mailbox::test_empty_imap_host_poll_exits_without_connecting, test_second_poll_exits_when_lock_held, test_first_connect_sets_last_uid_to_uidnext_minus_one_and_parses_nothing, test_first_connect_writes_mailbox_connected_journal, test_new_mail_found_by_uid_range_filtered_on_client_for_empty_range, test_mail_read_by_other_client_still_fetched, test_at_most_20_mails_per_run_rest_next_run_in_uid_order, test_restored_database_known_pairs_not_downloaded_last_uid_advances, test_restored_database_new_mails_parsed_without_duplicate_tickets, test_connection_error_saved_in_last_error_without_password_no_retry, test_mailbox_opened_read_only_examine_nothing_flagged_or_deleted, test_parse_job_enqueued_only_after_commit, test_header_read_error_does_not_stop_poll_fields_empty, test_lock_released_only_by_own_value_in_finally, test_lock_extended_after_each_fetched_mail |
| ящик пересоздан | в `poll`, ветка «UIDVALIDITY другой» | отбор: `search_since(day)`, где `day` на сутки раньше `last_ok_at`; из них письма с `head(uid).internal_date` не раньше `last_ok_at` минус `RECREATE_WINDOW_MINUTES` и либо с пустым `message_id`, либо с `message_id`, которого нет среди непустых `InboundMail.message_id`; `last_uid` = наименьший UID отобранных минус 1, отобранных нет — `uidnext` минус 1; `last_ok_at` пуст (ящик никогда не отвечал) — отобранных нет (решение контракта: прежний ящик ни разу не опрашивался удачно, отбирать не из чего); вызовы `head` в `PER_RUN` не входят; новый `uidvalidity` записан | нет | журнал `mailbox.recreated` | test_sd_mailbox::test_recreated_mailbox_takes_mails_within_10_minutes_before_last_ok_at, test_recreated_mailbox_skips_repeated_message_id, test_recreated_mailbox_last_uid_by_smallest_selected_uid_or_uidnext_minus_one, test_recreated_mailbox_writes_mailbox_recreated_journal |
| `store` | `store(fetched, uidvalidity)` | `InboundMail`; одна транзакция: строка (`status="received"`; `internal_date` — `FetchedMail.internal_date`, `received_at` — `timezone.now()` (время забора порталом, plan.md:351); из заголовков `message_id`, `from_email`, `subject` — сбой чтения оставляет их пустыми и опрос не останавливает), файл `PROTECTED_ROOT/"inbound"/f"{id}.eml"` с байтами письма без изменений, запись через `write_raw`, затем `MailboxState.last_uid = uid` | ошибка записи файла (`OSError`) откатывает всё, письмо будет скачано в следующем запуске | **после фиксации** `intake.enqueue(id)` | test_sd_mailbox::test_inbound_row_and_last_uid_saved_in_one_transaction, test_file_write_error_rolls_back_and_same_uid_retried, test_raw_mail_saved_whole_byte_for_byte_before_parsing |
| `write_raw` | `write_raw(path, data)` | `None`; запись во временный файл рядом (`<id>.eml.tmp`) и `os.replace`; точка подмены в тесте ошибки записи (`monkeypatch.setattr(mailbox, "write_raw", ...)`) | `OSError` | ничего | test_sd_mailbox::test_file_write_error_rolls_back_and_same_uid_retried |
| `headers_of` | `headers_of(raw)` | `tuple[str, str, str]`: (`message_id`, `from_email` строчными, `subject` после `clean_subject`) из заголовков письма (`headers_of` использует `mail_parse.sender_of(...)[0]` и `clean_subject`); любая ошибка — три пустые строки | нет | ничего | test_sd_mailbox::test_header_read_error_does_not_stop_poll_fields_empty |
| `status` | `status()` | `MailboxStatus` для верха «Входящих писем» | нет | ничего | test_sd_mailbox (через страницу; проверяет и второе поле: `connected` ложно до первого подключения при заданном `IMAP_HOST`, страница при этом не пишет «ящик не подключён»), test_sd_retention_2::test_inbound_list_shows_dash_for_erased_sender_and_subject |
| `reparse` | `reparse(inbound_id, *, actor, ip=None)` | `bool`: письмо в `status="error"` — ставится разбор (`intake.enqueue`) и `True`; обработанное (`processed`) или в другом состоянии — `False`, ничего не меняется; право `servicedesk.manage` проверяет маршрут | `InboundMail.DoesNotExist` ядра, если строки нет | **после фиксации** `intake.enqueue(id)`; журнала нет (в плане для кнопки нет события) | test_sd_mailbox::test_reparse_button_requeues_error_mail_for_manage_holder_only_403_for_others_and_ignores_processed_mail |
| `requeue_inbound` | `requeue_inbound()` | `int`: письма в `received`, полученные раньше `REQUEUE_AFTER_MINUTES` назад и без задания (`not intake.has_job(id)`), получают `intake.enqueue`; свежие и обработанные не трогаются | нет | постановка заданий; задание `requeue_inbound` (раздел 7) зовёт функцию | test_sd_mailbox::test_requeue_inbound_enqueues_parsing_of_received_mails_older_than_3_minutes_without_job_and_skips_fresh_and_processed |

### 6.16. `intake`

Разбор письма: `apps/servicedesk/services/intake.py`. Текст и части берёт из `mail_parse` (6.14),
заявку создаёт `tickets.create(channel=tickets.MAIL, ...)`, дописывает `tickets.add_incoming`,
открывает `closing.reopen(..., via="mail")` после `closing.within_reopen_term`, вложения —
`attachments.accept(entry, parts, strict=False, mail_size=len(raw))` (решение B1-4: в той же
транзакции после `create` или `add_incoming`). Шаги ошибки в `InboundMail.last_error`: `parse`,
`checks`, `link`, `ticket`, `attachments`, `finish`; формат значения — `"<шаг>: <класс
исключения>"` (решение Opus B2-3), текста исключения там нет (FR-289). Чтобы вызвать ошибку на
шаге, тест подменяет функцию шага (раздел 3.5); `process` зовёт каждый шаг через
`intake.STEPS[<шаг>]`, тест подменяет элемент словаря (решение Opus V-9). `intake.STEPS` —
словарь «имя шага → функция» (`dict[str, Callable]`) по шагам
`parse`, `checks`, `link`, `ticket`, `attachments`, `finish`; `process` идёт по нему по
порядку (решение Opus V-3).

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `enqueue` | `enqueue(inbound_id)` | `None`: ставит задание `process_inbound(id)` в очередь `inbox` (имя, ключ задания и повторы — раздел 7); вне транзакции — сразу, внутри — после фиксации | нет | постановка задания | test_sd_mailbox::test_parse_job_enqueued_only_after_commit |
| `has_job` | `has_job(inbound_id)` | `bool`: в очереди `inbox` или в работе есть задание этого письма (по ключу из раздела 7) | нет | ничего | test_sd_mailbox::test_requeue_inbound_enqueues_parsing_of_received_mails_older_than_3_minutes_without_job_and_skips_fresh_and_processed |
| `process` | `process(inbound_id)` | `str \| None` — значение `InboundMail.Outcome` или `None`, если разбирать нечего. Одна транзакция под `select_for_update` строки; письмо в `processed` пропускается, письмо с `raw_deleted` пропускается (файл стёрт, итог остаётся); шаги по плану: отправитель; проверки по порядку FR-214 (адрес ящика или `settings.DEFAULT_FROM_EMAIL` — `rejected_self`; автоматическое — `auto`; домен не из списка или не приводимый к `xn--…` или пустой список — `rejected_domain`; очереди по умолчанию нет — `status="waiting_setup"`, итог `waiting_setup`); связь (`link`); итог; ответственного по умолчанию у письма нет; заявка: связано с открытой — `add_incoming` (итог `appended`), с закрытой и в срок — `reopen(via="mail")` и `add_incoming` (`reopened`), с закрытой после срока — `create(previous=ticket)` (`created`), не связано — `create` (`created`); в конце `ticket`, `entry`, `status="processed"`, `processed_at` | ошибка любого шага: откат, затем отдельной транзакцией `status="error"`, `outcome="parse_error"`, `attempts + 1`, `last_error`; исходное исключение поднимается наружу (повтор делает RQ, раздел 7) | событие шины `servicedesk.reply_received` (внутри `add_incoming`), письма `ticket.confirmation` или `ticket.reopened` и проверка вложений — после фиксации; журнала у разбора нет, кроме событий вызванных служб | test_sd_intake (все) |
| `classify` | `classify(message, sender)` | `str \| None`: первая сработавшая проверка FR-214 — значение `Outcome` (`rejected_self`, `auto`, `rejected_domain`) или `None`; порядок: ящик, автоматическое, домен; письмо с адреса ящика всегда `rejected_self`, даже автоматическое; автоматическое чужого домена — `auto` | нет | ничего | test_sd_intake::test_mailbox_check_precedes_automatic_check, test_automatic_foreign_domain_mail_gets_automatic_outcome_not_foreign, test_mail_from_mailbox_address_rejected_with_own_outcome, test_mail_from_smtp_from_address_rejected_like_mailbox, test_foreign_domain_rejected_no_ticket_no_reply_no_append, test_empty_domain_list_rejects_all_mail, test_cyrillic_domain_matched_via_xn_and_unconvertible_domain_foreign |
| `find_ticket` | `find_ticket(parsed)` | `Ticket \| None`: заявка по `[#N]` в теме (главнее заголовков), иначе по `link_ids` среди `MailMessage.message_id` писем заявок и `InboundMail.message_id` привязанных писем; найдена, но отправитель не `requester_email` и не неснятый участник — `None` (посторонний, снятый участник, несуществующий номер) | нет | ничего | test_sd_intake::test_ticket_number_in_subject_beats_in_reply_to_headers, test_link_by_in_reply_to_and_references_to_outgoing_and_inbound_ids, test_sender_requester_or_participant_appended_to_open_ticket, test_stranger_corporate_sender_with_ticket_number_creates_new_ticket, test_removed_participant_mail_creates_new_ticket, test_nonexistent_ticket_number_creates_new_ticket_in_default_queue |
| `corporate_cc` | `corporate_cc(parsed, requester_email)` | `list[tuple[str, str]]`: из `parsed.cc` только адреса домена из списка настроек, без адреса ящика, `settings.DEFAULT_FROM_EMAIL`, самого заявителя и повторов; адреса из `To` не участвуют | нет | ничего | test_sd_intake::test_cc_corporate_addresses_become_participants_excluding_mailbox_smtp_from_requester_duplicates, test_cc_foreign_domain_not_participant_and_to_addresses_not_participants |
| `add_participants` | `add_participants(ticket, pairs)` | `list[TicketParticipant]`: создаёт участников новой заявки из копии (строка у существующего не меняется, снятый не восстанавливается); при дописывании в заявку то же делает `tickets.add_incoming(cc=...)` | нет | ничего | test_sd_intake::test_cc_corporate_addresses_become_participants_excluding_mailbox_smtp_from_requester_duplicates |

Продолжение письма: `inbound` заявки — `TicketEntry.inbound` проставляют `create` и
`add_incoming` по `inbound_id=inbound.id` (`intake` передаёт его всегда; `at=inbound.received_at`:
лента показывает, когда письмо пришло, а не когда разобрано; `received_at` — часы портала,
а не `internal_date` почтового сервера: порядок ленты не зависит от часов сервера; решение
Opus RB2-7, причина уточнена итоговой сверкой, F4-1), а
`InboundMail.ticket`, `entry`, `outcome`, `status`, `processed_at` — шаг `finish`; карточка и
«Входящие письма» читают их
(`test_inbox_outcomes_for_each_result_and_source_mail_linked_to_entry_and_ticket`). Письма,
ждавшие настройки, после выбора очереди по умолчанию получают `process_inbound` от
`queues.set_default` (6.4); все проверки идут заново.

### 6.17. `letters`

Письма заявителю: `apps/servicedesk/services/letters.py`. Почтовые заголовки и повторы собирает
`deliver_message` и `send_rendered` (раздел 5.3); тексты и тема — раздел 10 (часть c). Шаблоны
плана: `ticket.confirmation`, `ticket.assigned`, `ticket.closed`, `ticket.autoclosed`,
`ticket.reopened`, `ticket.reply`; константа `letters.TEMPLATES` — кортеж этих шести строк в этом
порядке. Контекст письма (то, что уходит в `job.meta["context"]`) — только `ticket_id: int`,
`entry_id: int \| None`, `after_hours: str \| None` (дата и время «ДД.ММ.ГГГГ ЧЧ:ММ» начала
рабочего времени по Москве без слова «с», `""` — даты нет; адресов и текстов нет).
Значение `related_ref` письма заявки — `"ticket:<id заявки>"` (план,
«Хранение»; номер элемента в нём нет, решение Opus B2-4).

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `send` | `send(ticket, template, *, entry=None, extra=None)` | `None`; `extra` — словарь с ключом `after_hours` (остальные ключи отбрасываются); регистрирует `transaction.on_commit`, в нём считает получателей и зовёт `apps.integrations.mail.services.send_rendered(template, to, subject=..., cc=..., reply_to=settings.SERVICEDESK_MAILBOX (при пустом значении `""`, решение Opus C7), message_id=new_message_id(), references=" ".join(references_of(ticket)), auto_submitted=..., related_ref=..., attachments=[...], context=...)`; письмо не создаётся, если шаблон не из `TEMPLATES` (`ValueError`); исполнителям писем нет | `ValueError` на неизвестный шаблон | `MailMessage` (`status="queued"`) и задание `deliver_message` после фиксации; в ленту и журнал ничего не пишет | test_sd_letters::test_send_rendered_queues_deliver_job_and_rejects_unregistered_prefix, test_confirmation_off_hours_line_only_when_given, test_no_ticket_letters_to_executors |
| `recipients` | `recipients(ticket, template)` | `tuple[str, list[str]]`: (`requester_email`, копия); подтверждение — копия пуста; `ticket.assigned`, `ticket.closed`, `ticket.autoclosed`, `ticket.reopened`, `ticket.reply` — адреса неснятых участников; участник с адресом заявителя в копию не попадает | нет | ничего | test_sd_letters::test_to_requester_cc_unremoved_participants_and_no_cc_for_confirmation, test_sd_assignment_2::test_removed_participant_gets_no_letters |
| `auto_submitted` | `auto_submitted(ticket, template)` | `str`: подтверждение заявки из письма (источник `mail`) — `"auto-replied"`; подтверждение заявки с формы и от исполнителя — `"auto-generated"`; `ticket.assigned`, `ticket.closed`, `ticket.autoclosed`, `ticket.reopened` — `"auto-generated"`; `ticket.reply` — `""` (заголовок не пишется) | нет | ничего | test_sd_letters::test_auto_submitted_auto_replied_for_confirmation_of_email_ticket, test_auto_submitted_auto_generated_for_form_and_executor_confirmation, test_auto_submitted_auto_generated_for_assigned_closed_autoclosed_reopened, test_executor_reply_has_no_auto_submitted_header |
| `subject_of` | `subject_of(ticket)` | `str`: `"[#<number>] <тема заявки>"`, тема после `mail_parse.clean_subject`; сохраняется в `MailMessage.subject` | нет | ничего | test_sd_letters::test_subject_is_number_and_ticket_subject_with_control_chars_cleaned |
| `new_message_id` | `new_message_id()` | `str` вида `<...@домен ящика заявок>` (`make_msgid(domain=...)`, домен — часть `SERVICEDESK_MAILBOX` после `@`; при пустом `SERVICEDESK_MAILBOX` — часть `settings.DEFAULT_FROM_EMAIL` после `@`, решение Opus C7) | нет | ничего | test_sd_letters::test_own_message_id_with_mailbox_domain_saved_before_send |
| `references_of` | `references_of(ticket)` | `list[str]`: идентификатор первого письма заявителя (`InboundMail.message_id` первого элемента `incoming`, если он есть) и `message_id` предыдущего письма портала по заявке, по порядку, без повторов; пустой список — заголовки не пишутся | нет | ничего | test_sd_letters::test_in_reply_to_and_references_chain_first_requester_letter_and_previous_portal_letter |
| `attachment_ids` | `attachment_ids(entry)` | `list[str]`: `str(StoredFile.id)` принятых вложений элемента `reply`; другие шаблоны — `[]` | нет | ничего | test_sd_letters::test_deliver_renders_body_from_database_at_send_time |
| `render` | `render(message, context)` | `Rendered` (раздел 3.2): `body` — текст из шаблона `templates/servicedesk/mail/ticket_<вид>.txt` (вид — часть имени шаблона после точки), собранный в момент отправки из базы по `context["ticket_id"]` и `context["entry_id"]`; `attachments` — пары (имя, путь `files.attachment_path`) вложений элемента со статусом `clean`; недоступное и не принятое не включается (не принятые перечисляются в тексте подтверждения); тела нет в `MailMessage` | `ValueError` на чужой шаблон | ничего | test_sd_letters::test_deliver_renders_body_from_database_at_send_time, test_mail_body_not_stored_and_job_meta_has_no_texts_or_addresses, test_confirmation_text_matches_spec, test_executor_reply_text_without_additions_with_signature, test_letters_have_no_passwords_or_login_links |
| `renderers` | `renderers()` | `list[MailRenderer]` для точки `mail_renderers`: один элемент с `prefix="ticket."` и `render=letters.render`; регистрирует `apps/servicedesk/extensions.py` | нет | ничего | test_sd_boundaries::test_extension_points_include_unit_usage_file_purposes_mail_renderers_login_links |
| `unsent` | `unsent(entry)` | `bool`: письмо этого элемента `reply` в `MailMessage.status="failed"`; для маркера «не доставлено» в карточке | нет | ничего | test_sd_reply::test_failure_after_last_retry_writes_not_delivered_event_in_feed |

Недоставку (`mail.failed`) обрабатывает `replies.on_mail_failed` (6.10), своей функции в `letters`
для неё нет. Схема повторов, заголовки и `safe_error` — раздел 5.3 (T-3118:
`test_retry_schedule_about_22_hours_within_24`,
`test_last_failure_publishes_mail_failed_and_adds_feed_event_and_audit`,
`test_safe_error_hides_imap_password`, `test_from_header_has_portal_name_and_smtp_from`,
`test_reply_to_is_servicedesk_mailbox`).

### 6.18. `attachments`

Приём, проверка и выдача вложений: `apps/servicedesk/services/attachments.py`. Класс `Part` — из
`mail_parse` (6.14), реэкспорт `attachments.Part`; для файла формы — `from_upload`. Пределы:
`MAX_FILE = 20 * 1024 * 1024`, `MAX_MAIL = 50 * 1024 * 1024`, `MAX_FILES = 10`, `MAX_TOTAL = 50 *
1024 * 1024`; `EXECUTABLE_EXTENSIONS` — кортеж из двадцати одного расширения плана (`exe`, `com`,
`scr`, `pif`, `bat`, `cmd`, `msi`, `msp`, `vbs`, `vbe`, `js`, `jse`, `wsf`, `wsh`, `ps1`, `hta`,
`cpl`, `jar`, `lnk`, `reg`, `sh`; `docm` и `xlsm` в нём нет). Единая функция приёма для трёх
каналов (решение Opus B2-5): режим `strict` выбирает правило отказа.

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `from_upload` | `from_upload(uploaded)` | `Part`: имя файла после `clean_filename`, байты, тип из загрузки | нет | ничего | test_sd_form::test_file_count_total_size_and_unacceptable_file_refuse_whole_form |
| `reason_of` | `reason_of(name, data)` | `str`: значение `Attachment.Rejected` (`""`, `"executable"`, `"encrypted"`) по содержимому и имени, без учёта размера; сначала исполняемый, затем архив с паролем | нет | ничего | test_sd_attachments::test_executable_signatures_and_type_by_content_rejected, test_every_executable_extension_rejected_by_last_extension_case_insensitive, test_docm_and_xlsm_not_executable, test_password_protected_zip_flag_bit_and_aes_rejected, test_password_protected_rar4_rar5_and_7z_rejected, test_archives_without_password_accepted |
| `is_executable` | `is_executable(name, data)` | `bool`: сигнатуры PE (`MZ` и `PE\0\0` по смещению `e_lfanew`), ELF, Mach-O (кроме `CAFEBABE` без признака fat), скрипт с `#!`, MSI (OLE с CLSID установщика у корня), JAR (ZIP с `META-INF/MANIFEST.MF`) либо последнее расширение из `EXECUTABLE_EXTENSIONS` без учёта регистра; файл `MZ` без `PE\0\0`, OLE старого `.doc` и `CAFEBABE` класса Java исполняемыми не считаются | нет | ничего | test_sd_attachments::test_signature_edge_cases_mz_without_pe_cafebabe_ole_doc_and_jar |
| `is_encrypted_archive` | `is_encrypted_archive(data)` | `bool`: ZIP — бит `flag_bits & 1` или метод 99 у любого элемента; RAR5 — запись шифрования; RAR4 — флаги заголовков; 7z — кодек AES `06F10701`; заголовки читаются без распаковки | нет | ничего | test_sd_attachments::test_password_protected_zip_flag_bit_and_aes_rejected, test_password_protected_rar4_rar5_and_7z_rejected |
| `precheck` | `precheck(parts)` | `None`: проверка без базы для формы и ответа до записи чего-либо; порядок: число (`too_many_files`), сумма (`total_too_big`), затем каждый файл по порядку: размер больше `MAX_FILE` (причина `too_big`), затем `reason_of`; первый же отказ — `file_rejected` с названием файла и подписью `Attachment.REJECT_TITLES[причина]` (порядок «число → сумма → файлы» — выбор контракта, plan.md:991-993 порядка не задаёт) | `too_many_files`, `total_too_big`, `file_rejected` | ничего | test_sd_attachments::test_form_over_10_files_or_over_50mb_total_refused, test_form_and_reply_with_rejected_file_refused_entirely_with_message |
| `accept` | `accept(entry, parts, *, strict=True, mail_size=None)` | `list[Attachment]` в порядке `parts`, в том числе не принятые; по каждому файлу порядок: размер (письмо целиком больше `MAX_MAIL` по `mail_size` — все файлы `mail_too_big`; файл больше `MAX_FILE` — `too_big`), `reason_of`; не принятый — `Attachment` с `name`, `size`, `rejected`, `file` пуст, на диск не пишется; годный — файл в `incoming/<id>`, `StoredFile(purpose="attachment", owner=None, status="pending", content_type=<до 255 знаков>)`, `Attachment(ticket, entry, file, name, size, inline)`; `strict=True` (форма, ответ исполнителя, заявка от исполнителя) — сначала `precheck`, любой отказ откатывает всё и поднимается `ServiceDeskError` до записи файлов; `strict=False` (письмо) — не принятые перечисляются, заявка остаётся (FR-285); вызывается в транзакции зовущего (B1-4) | при `strict=True`: `too_many_files`, `total_too_big`, `file_rejected` | **после фиксации** на каждый принятый файл `apps.core.tasks.enqueue_scan(stored.pk)` (очередь `files`; сама функция ставит задание в режиме `on_db_commit`, как у фото; срок задания 300 с, решение Opus C2); записи в ленту нет (не принятые перечисляют карточка и подтверждение) | test_sd_attachments::test_letter_over_50mb_rejects_all_attachments_but_ticket_created, test_attachment_over_20mb_rejected_with_reason, test_rejected_attachment_keeps_only_name_size_reason_and_is_listed_in_card_and_confirmation, test_inline_image_is_attachment_and_checked, test_accepted_file_stored_pending_in_incoming_with_owner_none, test_stored_file_content_type_up_to_255_chars, test_form_and_reply_with_rejected_file_refused_entirely_with_message, test_sd_reply::test_reply_with_unacceptable_file_refused_as_a_whole |
| `file_purposes` | `file_purposes()` | `list[FilePurpose]` для точки `file_purposes` (раздел 3.2): один элемент `purpose="attachment"` с полями `still_waiting=still_waiting`, `clean=on_clean`, `found=on_found` (`FilePurpose`, раздел 3.2) из строк ниже | нет | ничего | test_sd_boundaries::test_extension_points_include_unit_usage_file_purposes_mail_renderers_login_links |
| `still_waiting` | `still_waiting(stored)` | `bool`: есть `Attachment` с этим файлом и `stored.status == "pending"` | нет | ничего | test_sd_attachments::test_pending_and_quarantined_not_downloadable_requeue_picks_pending |
| `on_clean` | `on_clean(stored)` | `list[pathlib.Path]` для стирания: файл `incoming/<id>` переносится в `attachments/<id>`, статус `clean`, `scanned_at`; затем, если вложение у элемента `reply` и ждущих файлов у него не осталось, зовётся `replies.on_files_checked(entry_id)` | нет | под `select_for_update`; письмо ответа — после фиксации внутри `on_files_checked` | test_sd_attachments::test_scan_clean_moves_file_to_attachments_and_makes_it_downloadable, test_sd_reply::test_reply_waits_while_files_are_checked_then_goes_when_all_clean |
| `on_found` | `on_found(stored, signature)` | `list[pathlib.Path]`: сигнатура `Heuristics.Encrypted.*` — файл стирается, строка `StoredFile` удаляется, `Attachment.file` пуст, `Attachment.rejected="encrypted"`, событие ленты «вложение «…» не принято: архив с паролем» (`replies.add_event`, код `attachment_rejected`, `data`: `name`, `reason`); иная сигнатура — файл в `quarantine/<id>`, статус `quarantine`, событие ленты «вложение в карантине» (код `attachment_quarantined`, `data`: `name`) и журнал `ticket.attachment_quarantined` (номер файла, сигнатура); затем так же `replies.on_files_checked(entry_id)` для ответа | нет | под `select_for_update`; события в той же транзакции | test_sd_attachments::test_scan_infected_goes_to_quarantine_with_feed_event_and_audit, test_scan_heuristics_encrypted_rejects_as_password_archive_and_erases_file, test_sd_reply::test_reply_with_quarantined_file_not_sent_with_event, test_reply_with_password_archive_not_sent_with_event |
| `pending_for` | `pending_for(entry)` | `bool`: у элемента есть вложение, чей файл ещё `pending` | нет | ничего | test_sd_reply::test_reply_with_attachments_waits_in_waiting_files |
| `download` | `download(user, number, file_id)` | `Download` — `NamedTuple`: `accel_path: str` (`"/protected/attachments/<id>"`), `filename: str` (имя вложения), `content_type: str` (всегда `"application/octet-stream"`); заявка через `tickets.get_for` | `django.http.Http404` — заявка не видна, файла нет у этой заявки, файл не `clean`; ожидающий и карантин не выдаются | ничего (заголовки `Content-Disposition`, `X-Content-Type-Options`, `Cache-Control` и `X-Accel-Redirect` ставит маршрут, раздел 12) | test_sd_attachments::test_download_of_invisible_ticket_returns_404, test_download_response_headers_x_accel_redirect_octet_stream_filename_star, test_pending_and_quarantined_not_downloadable_requeue_picks_pending |
| `source_mail` | `source_mail(user, number, inbound_id)` | `Download` для `/tickets/<номер>/mail/<id>.eml`: `accel_path` — `"/protected/inbound/<id>.eml"`; письмо привязано к этой заявке, `raw_deleted` ложно и **все** его вложения `clean` и ни одно не `rejected` (FR-212) | `django.http.Http404` во всех остальных случаях | ничего | test_sd_attachments::test_source_eml_issued_only_when_all_attachments_clean_and_none_rejected, test_source_eml_of_invisible_ticket_returns_404 |
| `rejected_of` | `rejected_of(ticket_or_entry)` | `list[Attachment]`: не принятые вложения заявки или элемента для списка в карточке и в подтверждении; подпись причины — `Attachment.REJECT_TITLES[code]` | нет | ничего | test_sd_attachments::test_rejected_attachment_keeps_only_name_size_reason_and_is_listed_in_card_and_confirmation |

Сообщение отказа `file_rejected` — «файл «<имя>» не принят: <подпись причины>» (подписи —
`Attachment.REJECT_TITLES`, раздел 2.2; решения Opus A7). Для письма (`strict=False`) отказов нет.

### 6.19. `form`

Открытая форма: `apps/servicedesk/services/form.py`. Сессию Django передаёт маршрут; Valkey —
клиент `apps.core.services.valkey.conn()`. Константы: `SESSION_KEY = "servicedesk_form_done"`,
`RATE_PREFIX = "servicedesk:form:"`, `RATE_WINDOW = 3600`. Поля формы в словарях ошибок — `email`,
`name`, `client_unit`, `category`, `subject`, `text`, `consent`. `FormInvalid` —
`ServiceDeskError` с `code="invalid_form"` и атрибутом `errors: dict[str, str]` (поле → код);
текст — раздел 14.

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `is_open` | `is_open()` | `bool`: `settings.is_configured()` (есть домены и очередь по умолчанию) | нет | ничего | test_sd_form::test_closed_page_without_domains_or_default_queue_names_mailbox |
| `closed_text` | `closed_text()` | `str`: «Приём заявок через форму сейчас закрыт. Напишите письмо на <адрес ящика>» (адрес — `settings.mailbox_address()`) | нет | ничего | test_sd_form::test_closed_page_without_domains_or_default_queue_names_mailbox, test_post_when_closed_rejected_with_same_text |
| `choices` | `choices()` | `FormChoices` — `dataclass(frozen=True)`: `client_units: list[ClientUnit]` (неархивные по названию), `categories: list[Category]` (неархивные с `on_form=True` по `order`, затем `id`; «Другое» среди них); критичности и источника в выборе нет | нет | ничего | test_sd_form::test_department_list_unarchived_plus_not_in_list, test_category_list_shown_on_form_only_in_order_with_other, test_form_has_no_criticality_choice_and_ticket_gets_default |
| `validate` | `validate(*, email, name, client_unit_id, category_id, subject, text, consent)` | `dict[str, str]`: поле → код, пустой словарь, если всё верно; адрес — формат и домен из списка (`bad_email`; проверяется `requesters.normalize_email`, её `ServiceDeskError` переводится в `errors["email"] = "bad_email"`; адрес длиннее 254 знаков — тоже `bad_email`); для пустого `name` код — `requester_name_required` (кода `name_required` у формы нет); `name` длиннее 255 знаков — `requester_name_too_long`; `category_id` пусто — `category_not_offered`; `subject_required`, `subject_too_long` (до 255), `description_required`, `description_too_long` (до 50 000), `consent_required`, `category_not_offered`, `unit_not_offered` (только предлагаемое на форме; `client_unit_id=None` — «нет в списке» допустимо); ничего не ищет по адресу в таблице заявителей | нет | ничего | test_sd_form::test_invalid_address_and_foreign_domain_refused, test_required_fields_and_length_limits_refused, test_missing_consent_refused, test_category_or_department_not_offered_refused, test_same_response_for_known_and_unknown_address_and_no_prefill |
| `register_hit` | `register_hit(ip)` | `bool`: `True` — заявка допущена. Сценарий Lua (`register_script`) над упорядоченным множеством `servicedesk:form:<ip>`: `ZADD` с временем и случайным суффиксом, `ZREMRANGEBYSCORE` старше часа, `ZCARD`; число больше `settings.form_hourly_limit` (читается при каждом вызове) — отметка удаляется, `False`; ключ живёт час; `redis.exceptions.RedisError` — `True` и предупреждение в лог | нет | ключ в Valkey | test_sd_form::test_rate_limit_sliding_window_lua_script, test_rate_limit_default_ten_per_hour_and_threshold_read_from_settings, test_rate_limit_client_ip_behind_trusted_proxy, test_valkey_down_form_works_without_limit_and_logs_warning |
| `submit` | `submit(*, email, name, client_unit_id, category_id, subject, text, consent, parts=(), ip)` | `tickets.Created`; порядок: закрыто — `intake_closed`; `validate` (непустые ошибки — `FormInvalid`); `attachments.precheck(parts)`; `register_hit(ip)` (считаются только принятые формы, поэтому после проверок); одна транзакция: `tickets.create(channel=tickets.FORM, source=system «form», consent_at=now, ip=ip, ...)` и `attachments.accept(entry, parts)`; категория и очередь по категории (у «Другое» — по умолчанию); критичность из настроек | `intake_closed`, `invalid_form`, `too_many_files`, `total_too_big`, `file_rejected`, `rate_limited` | журнал `ticket.created` с `ip` (внутри `create`); подтверждение `ticket.confirmation` после фиксации | test_sd_form::test_valid_post_creates_form_ticket_in_category_queue_with_consent_mark_and_confirmation, test_post_when_closed_rejected_with_same_text, test_rate_limit_refuses_over_threshold_with_mailbox_address, test_rate_limit_counts_only_accepted_forms, test_file_count_total_size_and_unacceptable_file_refuse_whole_form, test_not_in_list_department_taken_from_requester_record_or_empty, test_form_department_fills_empty_record_and_keeps_existing_one, test_default_assignee_of_category_gives_in_progress_and_single_confirmation |
| `remember_done` | `remember_done(session, email)` | `None`: адрес — в `session[SESSION_KEY]` | нет | ничего | test_sd_form::test_done_page_shows_address_without_number_taken_from_session_and_removed |
| `pop_done` | `pop_done(session)` | `str \| None`: адрес из сессии с удалением ключа; второй вызов — `None`; в адрес страницы ПДн не попадают | нет | ничего | test_sd_form::test_done_page_shows_address_without_number_taken_from_session_and_removed |
| `login_links` | `login_links()` | `list[dict]` для точки `login_links`: один элемент `{"url": "/request/", "title": "Подать заявку в ИТ-отдел"}` (план, «Открытая форма») | нет | ничего | test_sd_form::test_login_page_has_request_link_from_login_links |

### 6.20. Заявка от исполнителя (`executor`)

Отдельного модуля план не называет (в плане — только маршруты `/tickets/new/` и
`/tickets/new/requester/`); сервисная часть вынесена в `apps/servicedesk/services/executor.py`, по
образцу `form` (решение Opus B2-6). Создание — тот же `tickets.create` (6.7, канал
`tickets.STAFF`). `ExecutorResult` — `dataclass(frozen=True)`: `created: tickets.Created`,
`visible: bool` (заявка видна `actor` после создания; от этого зависит переход в карточку или в
список, раздел 12).

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `can_start` | `can_start(user)` | `bool`: `access.can_create(user)` (кнопка «Новая заявка», FR-228) | нет | ничего | test_sd_executor::test_new_button_visible_to_queue_member, test_new_button_visible_to_all_tickets_holder_without_queue_node, test_new_button_absent_and_route_403_for_non_member |
| `can_take` | `can_take(user, queue_id)` | `bool`: `access.is_participant(user, queue_id)`; для держателя `servicedesk.all` — в любой очереди; по нему перерисовывается флажок «Взять себе» | нет | ничего | test_sd_executor::test_take_to_self_fragment_enabled_only_for_member_of_selected_queue, test_take_to_self_enabled_for_all_tickets_holder_in_any_queue |
| `queue_for_category` | `queue_for_category(category_id)` | `int`: `queue_id` очереди категории, у «Другое» — очередь по умолчанию (подстановка; очередь можно сменить на любую отмеченную) | `no_queue`, `archived_value` | ничего | test_sd_executor::test_category_substitutes_queue_and_queue_can_be_changed_to_any_marked |
| `create` | `create(*, actor, email, name="", client_unit_id=None, category_id, queue_id, priority_id=None, source_id, subject, text, take=False, parts=(), ip=None)` | `ExecutorResult`; порядок: `access.can_create(actor)` (иначе `no_access`); список доменов пуст — `intake_closed`; адрес — `bad_email` (в том числе длиннее 254 знаков); ФИО длиннее 255 знаков — `requester_name_too_long`; тема, описание — `subject_required`, `subject_too_long`, `description_required`, `description_too_long`; категория — `category_required`; очередь — `queue_required`, `not_queue`; `attachments.precheck(parts)`; в одной транзакции `tickets.create(channel=STAFF, created_by=actor, take_by=actor if take else None, ...)` и `attachments.accept(entry, parts)`; ФИО необязательно; `take` у не участника выбранной очереди молча игнорируется (B1-6); критичность — заданная или из настроек | `no_access`, `intake_closed`, `bad_email`, `requester_name_too_long`, `subject_required`, `subject_too_long`, `description_required`, `description_too_long`, `category_required`, `queue_required`, `not_queue`, `source_required`, `archived_value`, `too_many_files`, `total_too_big`, `file_rejected` | журнал `ticket.created` с источником и автором (внутри `create`); подтверждение `ticket.confirmation` после фиксации без фразы о нерабочем времени (`after_hours=None`); один раз, письмо «взята в работу» при `take` не уходит | test_sd_executor (все), test_sd_assignment::test_taken_letter_not_sent_on_creation_with_assignee |

Подстановка по адресу — `requesters.lookup` (6.22); кнопки и поля — разделы 12 и 13.

### 6.21. `search` и `listing` (поиск, список, счётчик)

Два модуля: `apps/servicedesk/services/search.py` (столбец `Ticket.search`, запрос поиска) и
`apps/servicedesk/services/listing.py` (пресеты, фильтр, сортировка, страницы, счётчик); имена
даны задачей T-3221, в плане модуля списка нет (решение B1-9: счётчик и пресеты — b2). Константы
`search`: `MAX_WORDS = 8`, `MIN_WORD = 2`, `LIMIT_MESSAGE = 100_000`, `LIMIT_TICKET = 300_000`.
Модели `org` не импортируются (граница, раздел 3.2): очередь читается как `queue`,
`select_related("queue")` по имени связи.

Результат разбора строки поиска — `search.Parsed`, `dataclass(frozen=True)`: `words: list[str]`,
`number: int \| None`, `raw: str` (`"слово1:* & слово2:*"` либо пусто), `hint: str` (`""` или
`"short"` — в строке остались только слова короче двух знаков; текст подсказки — раздел 14).
`SearchResult` — `dataclass(frozen=True)`: `tickets: list[Ticket]`, `hint: str`.

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `search.parse` | `parse(query)` | `Parsed`: слова — `re.findall(r"\w+", query.lower())`, не короче `MIN_WORD`, не больше `MAX_WORDS` (лишние отброшены); `raw` — слова с суффиксом `:*`, соединённые ` & `; `number` — для строки из `123` или `#123` (целое), слова короче двух знаков при этом не мешают; нет годных слов и нет номера — `hint="short"`, если слова были, иначе пусто | нет | ничего | test_sd_search::test_search_words_shorter_than_two_chars_skipped_with_hint, test_search_more_than_eight_words_cut_to_eight, test_search_hash_number_works_with_short_word, test_search_by_number_and_hash_number |
| `search.apply` | `apply(queryset, query)` | `QuerySet[Ticket]`: к условиям добавляется `Q(search=SearchQuery(raw, config="russian", search_type="raw"))` (запрос идёт параметром, не подстановкой) и `Q(number=number)` через «или» при номере; слова из одних стоп-слов дают пустой список без ошибки; нет годных слов и номера — набор не меняется | нет | ничего | test_sd_search::test_search_stop_words_only_gives_empty_list_without_error, test_search_special_chars_and_quotes_do_not_break_query, test_search_injection_string_passed_as_parameter_raw_type |
| `search.search` | `search(user, query, limit)` | `SearchResult`: `access.visible_tickets(user)` + `apply`, по номеру по убыванию, не больше `limit` строк; «е» и «ё» сводит сама конфигурация `russian`, своих замен нет | нет | ничего | test_sd_search::test_search_yo_and_ye_give_same_tickets, test_search_word_forms_found, test_search_prefix_found, test_search_by_part_of_address, test_search_by_requester_name_case_insensitive, test_search_by_subject_and_message_text, test_search_only_among_visible_tickets |
| `search.index` | `index(ticket, entry=None)` | `None`; без `entry` (после `tickets.create`) — столбец собирается целиком: `to_tsvector('russian', …)` от номера, темы, адреса и ФИО заявителя (адрес и ФИО дважды: как есть и с заменой `@ . _ / -` на пробелы) и текста первого элемента; с `entry` — `search = search \|\| to_tsvector('russian', текст)` запись вектора — через `search.write_vector(ticket_id, parts)` (поле `SearchVectorField`); текст одного сообщения — не больше `LIMIT_MESSAGE` знаков, на заявку — `LIMIT_TICKET` (учитывает `search_len`: достигнут предел — дописывания нет; в `search_len` идут только знаки текстов элементов, а сообщение, не помещающееся в остаток предела, дописывается обрезанным до остатка, после обрезки по `LIMIT_MESSAGE`); дописывание в точке сохранения, `DataError` — сообщение записано, в поиск не попало, `search_len = LIMIT_TICKET` | нет | в той же транзакции, что и запись элемента (зовут `tickets.create`, `tickets.add_incoming`, `replies.reply`, `replies.comment`) | test_sd_search::test_search_column_built_on_create_from_number_subject_requester_first_message, test_search_appended_by_incoming_mail_reply_and_comment, test_search_message_over_100k_chars_tail_not_searchable_but_visible, test_search_ticket_over_300k_chars_stops_appending, test_search_dataerror_message_saved_not_in_search_len_set_to_limit |
| `search.rebuild` | `rebuild(ticket, *, anonymized=False)` | `None`; пересобирает столбец целиком (`search_len` заново; запись — через `write_vector`): из номера, темы, адреса, ФИО и текстов всех элементов; `anonymized=True` — только из номера и темы (обезличивание, `retention`); зовут `tickets.update_fields` при правке ФИО заявителя (решение Opus B2-7; в 6.7 записано) и `retention` | нет | в транзакции зовущего | test_sd_search::test_search_rebuilt_on_requester_name_edit_in_ticket, test_search_rebuilt_on_anonymize_from_number_and_subject |
| `search.write_vector` | `write_vector(ticket_id, parts)` | `None`; выполняет запись вектора поиска заявки (`parts` — тексты, из которых собирается вектор); `index` и `rebuild` зовут её; ошибки базы не ловит: `DataError` ловит `index` (сообщение записано, в поиск не попало, `search_len = LIMIT_TICKET`); точка подмены раздела 3.5 | нет | в транзакции зовущего | test_sd_search::test_search_dataerror_message_saved_not_in_search_len_set_to_limit (подменяется: поднимает `django.db.DataError`) |
| `listing.PRESETS` | константа | кортеж из шести значений в порядке плана: `"mine"` («Мои»), `"unassigned"` («Без ответственного»), `"my_queues"` («Мои очереди»), `"waiting"` («Ждут ответа заявителя»), `"closed"` («Закрытые»), `"all"` («Все»); те же значения — GET-параметр `preset` (раздел 12) | - | - | test_sd_list::test_preset_* |
| `listing.default_preset` | `default_preset(user)` | `str`: `"my_queues"`, если у пользователя есть хотя бы одна очередь среди узлов работы (или он держатель `servicedesk.all`), иначе `"mine"` | нет | ничего | test_sd_list::test_default_preset_my_queues_for_queue_member, test_default_preset_mine_for_user_without_queues |
| `listing.my_queue_ids` | `my_queue_ids(user)` | `frozenset[int]`: отмеченные узлы среди `scope.work_units`; у держателя `servicedesk.all` — все отмеченные (`queues.marked_units()`) | нет | ничего | test_sd_list::test_preset_my_queues_open_tickets_of_marked_work_nodes, test_preset_my_queues_all_marked_nodes_for_all_tickets_holder |
| `listing.OPEN_KINDS` | константа | `("new", "in_progress", "waiting")`: «открытые» | - | - | test_sd_list::test_open_means_new_in_progress_waiting_requester |
| `listing.Filters` | `dataclass(frozen=True)` | поля, все необязательные (`None`): `queue: int`, `category: int`, `priority: int`, `status: int`, `kind: str`, `assignee: int \| str` (число или `"none"` — без ответственного), `client_unit: int`, `source: int`, `created_from: datetime.date`, `created_to: datetime.date` (по поясу портала; условие `created_at >= начало дня created_from` и `created_at < начало дня, следующего за created_to`, обе границы включительны), `q: str`; имена GET-параметров — раздел 12; условия сочетаются через «и» | - | - | test_sd_list::test_filter_by_queue_category_criticality, test_filter_by_status_and_status_kind, test_filter_by_assignee_and_without_assignee, test_filter_by_client_unit_and_source, test_filter_by_created_period_portal_date_field, test_filters_combine_with_and |
| `listing.SORTS` | константа | `("number", "created", "last_message", "priority")`; по умолчанию `"number"` по убыванию | - | - | test_sd_list::test_sort_default_new_on_top_by_number, test_sort_by_created_at_and_last_message, test_sort_by_criticality_dictionary_order_then_number |
| `listing.build` | `build(user, *, preset=None, filters=None, sort="number", descending=True, page=1)` | `Page` — `dataclass(frozen=True)`: `rows: list[Ticket]` (не больше `PAGE_SIZE = 50`), `has_next: bool` (запрос берёт 51-ю строку), `page: int`, `preset: str`, `hint: str`; пресет `None` — `default_preset`; основа — `access.visible_tickets(user)`; условия пресетов: «mine» — `assignee=user` и открытые; «unassigned» — очередь из `my_queue_ids`, без ответственного, открытые; «my_queues» — очередь из `my_queue_ids`, открытые; «waiting» — вид `waiting`; «closed» — вид `closed`; «all» — всё видимое; сортировка `priority` — по `priority__order`, затем номер, направление общее (решение Opus B2-8: по убыванию высшая критичность первой); `q` применяется `search.apply(qs, q)`, `Page.hint` = `search.parse(q).hint`; одна выборка с `select_related("status", "priority", "category", "assignee", "client_unit", "queue")`; общее число не считается | нет (неизвестный пресет или сортировка — значение по умолчанию) | ничего | test_sd_list (все, кроме `test_total_count_only_on_show_count_button` в части кнопки), test_sd_list_2::test_grid_read_with_constant_query_count, test_last_message_shows_time_and_requester_or_executor |
| `listing.count` | `count(user, *, preset=None, filters=None)` | `int`: общее число по тем же условиям (кнопка «показать количество») | нет | ничего | test_sd_list::test_total_count_only_on_show_count_button |
| `listing.badge` | `badge(user)` | `int`: число открытых заявок без ответственного в `my_queue_ids(user)` плюс число своих открытых заявок с `last_message_from="requester"`; два `COUNT` по частичным индексам без кэша; нуль возвращается как `0` (решение Opus B2-9: скрытие нуля — разметка, раздел 13); регистрируется ключом `badge` пункта «Заявки» (`extensions.menu_items`, раздел 3.2; `visible` — `access.menu_visible`) | нет | ничего | test_sd_list_2::test_badge_sums_unassigned_in_my_queues_and_mine_from_requester, test_badge_not_counted_when_menu_item_hidden, test_badge_two_counts_once_per_request, test_badge_updates_on_page_load_without_cache |
| `listing.menu_items` | `menu_items()` | `list[dict]` для точки `menu_items`: «Заявки» (`url="/tickets/"`, `title="Заявки"`, `icon=<шаблон иконки раздела 13>`, `order=5` (число — «Решение Opus по задачам», п. 10, tasks.md; не выбор контракта), `permissions=("servicedesk.all",)`, `visible=access.menu_visible`, `badge=listing.badge`) и «Сервис-деск» (`title="Сервис-деск"`, `icon=<шаблон иконки раздела 13>`, `order=65` (число — «Решение Opus по задачам», п. 10, tasks.md), `permissions=("servicedesk.manage",)`, ссылка — раздел 12) | нет | ничего | test_sd_boundaries::test_menu_item_visible_shows_item_without_permissions, test_sd_list_2::test_badge_not_counted_when_menu_item_hidden |
| `listing.card_link` | `card_link(viewer, employee_id)` | `str \| None`: адрес `/tickets/` с параметрами `preset=all` и `assignee=<employee_id>`, если пункт «Заявки» виден `viewer` (`access.menu_visible`), иначе `None` (раздел `card_sections`, FR-281); список по ссылке строит `build` по правам смотрящего | нет | ничего | test_sd_list_2::test_employee_card_tickets_link_filters_by_assignee, test_employee_card_link_hidden_without_menu_item, test_linked_list_limited_by_viewer_visible_tickets |

### 6.22. `requesters`

Записи заявителей и страница «Заявители» (право `servicedesk.manage` проверяет маршрут):
`apps/servicedesk/services/requesters.py`. Запись создаёт `tickets.create` (6.7), своей функции
создания здесь нет (`test_origin_ticket_for_record_created_by_first_ticket`). `RequesterRow` —
`dataclass(frozen=True)`: `requester: Requester`, `tickets_count: int` (без обезличенных).
`RequesterPage`: `rows: list[RequesterRow]`, `has_next: bool`, `page: int` (`PAGE_SIZE = 50`).

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `normalize_email` | `normalize_email(text)` | `str`: адрес строчными без пробелов; формат и домен из `settings.accepts_domain` проверяются; общий помощник формы и заявки от исполнителя | `bad_email` | ничего | test_sd_form::test_invalid_address_and_foreign_domain_refused, test_sd_executor::test_non_corporate_address_refused |
| `lookup` | `lookup(email)` | `RequesterHint` — `dataclass(frozen=True)`: `found: bool`, `name: str`, `client_unit_id: int \| None`; поиск ровно по одному полному корпоративному адресу, без подсказок и списков; адрес неполный, чужой или записи нет — `found=False`, пустые поля; архивное подразделение в подсказку не подставляется (решение контракта: архивное значение не предлагается, FR-273) | нет | ничего | test_sd_executor::test_requester_lookup_post_fills_name_and_department_for_known_address, test_requester_lookup_empty_for_unknown_incomplete_or_foreign_address, test_requester_lookup_address_in_body_not_in_url_no_suggestions |
| `page` | `page(*, query="", client_unit_id=None, number=1)` | `RequesterPage` по `email`; поиск по адресу и ФИО без учёта регистра и «е/ё» (как `accounts.pickable`, через `name_key`); фильтр по подразделению; `tickets_count` — `Count` заявок без `anonymized_at` | нет | ничего | test_sd_requesters::test_requesters_page_columns, test_requesters_ticket_count_excludes_anonymized, test_search_by_address_case_insensitive, test_search_by_name_yo_ye_insensitive, test_filter_by_client_unit, test_page_has_50_rows |
| `update` | `update(requester, *, name, client_unit_id, actor, ip=None)` | `bool` — что-то изменилось; ФИО (до 255) и подразделение (неархивное или `None`) | `requester_name_too_long`, `archived_value` | журнал `requester.updated` по номеру записи: подразделение «было и стало» (названия), ФИО — только «изменено» (без значений), адреса нет; ничего не изменилось — журнала нет | test_sd_requesters::test_edit_name_and_client_unit_saved, test_edit_unit_audit_was_became_name_only_changed |
| `delete` | `delete(requester, *, actor, ip=None)` | `None`; только запись без заявок (даже обезличенных заявок нет: связь `Ticket.requester` очищена) | `requester_has_tickets` | журнал `requester.deleted` по номеру записи, без адреса и ФИО | test_sd_requesters::test_delete_requester_without_tickets_with_confirmation, test_delete_requester_with_tickets_refused |
| `delete_if_orphan` | `delete_if_orphan(requester, *, reason, actor=None)` | `bool`: запись под `select_for_update`; у неё отметка «заявка» и других заявок нет — удаляется; иначе `False`; зовёт `retention` | нет | журнал `requester.deleted` с причиной `reason` («срок хранения») | test_sd_retention::test_requester_record_from_ticket_without_other_tickets_deleted_with_audit_reason, test_requester_record_kept_when_other_tickets_exist, test_requester_record_from_table_kept |

Остальное проверяется без отдельной функции: уникальность адреса без учёта регистра и «не учётная
запись портала» — модель (раздел 2.2; `test_requester_address_unique_case_insensitive`,
`test_requester_is_not_portal_account`), отказ 403 без права и непопадание в поиск заявок —
маршрут и `search` (`test_page_and_menu_403_without_manage_right`,
`test_ticket_search_does_not_reach_requester_table`,
`test_requester_data_not_visible_outside_accessible_tickets`), запись подразделения в заявку и в
запись заявителя — `tickets.create` и `tickets.update_fields`
(`test_form_remembers_client_unit_only_if_record_empty`,
`test_form_with_other_unit_does_not_change_record_ticket_keeps_form_unit`,
`test_executor_edit_then_import_replaces_unit_always`).

### 6.23. `requester_import` и чтение таблицы

Загрузка таблицы заявителей: `apps/servicedesk/services/requester_import.py`. Чтение CSV и XLSX —
общий модуль ядра `apps/core/services/table_file.py` (план, «Чтение файла таблицы»; в разделах 1-5
части a его нет, решение B2-10 — описан здесь). Исключение ядра — `TableFileError(Exception)` с
`code` и `message`; `org.services.staff_import` оборачивает его в `OrgError` с прежними кодами и
текстами. Структура повторяет `org.services.staff_import` (`make_preview`, `confirm`, образцы).

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `table_file.read` | `read(content, *, max_bytes, max_rows, max_parts, max_unpacked, texts)` | `TableFile` — `dataclass`: `file_format: str` (`"csv"` или `"xlsx"`, по содержимому, не по расширению), `header: list[str]`, `rows: list[list[str]]`; CSV — строгий UTF-8 (с BOM или без), разделитель определяется по строке заголовков (`;` или `,`); XLSX — оглавление архива проверяется до чтения (число частей, распакованный объём, опасный XML), `openpyxl` только для чтения без формул; перенос из `staff_import` без смены поведения: отказы в порядке `too_big`, `bad_format` (архив не XLSX), `zip_bomb`, чтение (`not_utf8`, `bad_format`, `xml_bomb`); чтение останавливается на строке сверх предела: `read` отдаёт прочитанные строки, не больше `max_rows + 1`, и о числе строк сам не судит; обязательные колонки проверяет вызывающий раньше числа строк (порядок `staff_import.parse_file`: колонки, затем `too_many_rows`, который поднимает `table_file.check_rows`); NUL в CSV — `not_utf8`, пустые строки данных не считаются, значения XLSX приводятся как `_cell_text` в `staff_import` (даты ДД.ММ.ГГГГ, целые без «.0»); пределы и тексты отказов — параметры; ключи `texts` (код → текст): `too_big`, `bad_format`, `bad_format_archive`, `bad_format_csv`, `not_utf8`, `too_many_rows`, `zip_bomb`, `xml_bomb` | `TableFileError` с кодами `too_big`, `bad_format`, `not_utf8`, `too_many_rows`, `zip_bomb`, `xml_bomb` | ничего | test_table_file (все) |
| `table_file.check_rows` | `check_rows(rows, max_rows, texts)` | `None`; число строк больше `max_rows` — отказ; зовёт вызывающий после проверки обязательных колонок (одно имя для `org.staff_import` и `servicedesk.requester_import`); `read` останавливается на строке `max_rows + 1` и отдаёт прочитанное, о числе строк не судит (решение Opus П3) | `TableFileError` с кодом `too_many_rows` (текст — `texts["too_many_rows"]`) | ничего | test_table_file (в том числе test_rows_limit_is_parameter_and_stops_on_row_over_limit) |
| `MAX_BYTES`, `MAX_ROWS` | константы | `2 * 1024 * 1024` и `2000` (FR-265); части и распакованный объём — те же `100` и `20 МБ`, что у загрузки сотрудников | - | - | test_sd_requester_import::test_file_over_2mb_refused_nothing_written, test_file_over_2000_rows_refused_nothing_written |
| `parse_file` | `parse_file(content)` | `ParsedFile`: `file_format`, `rows: list[dict]` (ключи `email`, `last_name`, `first_name`, `middle_name`, `unit`), `not_loaded: list[str]` (лишние колонки); заголовки сравниваются без регистра, пробелов и «е/ё»; обязательна «Почта»; необязательны «Фамилия», «Имя», «Отчество», «Подразделение»; после проверки колонок зовёт `table_file.check_rows`; отказы `table_file` переводятся в `ServiceDeskError` с теми же кодами | `too_big`, `bad_format`, `not_utf8`, `too_many_rows`, `zip_bomb`, `xml_bomb`, `missing_columns` | ничего | test_sd_requester_import::test_csv_semicolon_preview, test_csv_comma_preview, test_csv_with_bom_preview, test_xlsx_500_rows_preview, test_file_not_csv_or_xlsx_refused, test_file_not_utf8_refused, test_file_without_email_column_refused, test_only_email_column_required, test_headers_case_space_yo_insensitive_extra_columns_named_not_loaded |
| `make_preview` | `make_preview(content, *, file_name, actor, ip=None)` | `RequesterImport` (`state="preview"`, `delete_missing=False`); строки проверяются без записи заявителей; адреса — одним запросом, справочник подразделений — в памяти; ключи строки `rows`: `number` (с 1), `email`, `last_name`, `first_name`, `middle_name`, `unit` (из файла), `result` (`"will_add"`, `"will_update"`, `"unchanged"`, `"error"`), `code`, `reason` (текст результата), `changes` (словарь: `"name"` и `"unit"` — по `{"before": ..., "after": ...}`, только изменяемое), `origin_change: bool` (отметка записи «заявка» станет «таблица»); пределы `too_long`: почта 254, ФИО 255 (`" ".join` непустых «Фамилия», «Имя», «Отчество»), подразделение 150; формат почты — `django.core.validators.validate_email` (`email_invalid`), домен — `settings.accepts_domain` (`foreign_domain`); ФИО в файле «пустое», если пусты все три колонки, — прежнее значение не стирается (одна пустая часть — не пусто); коды ошибок строки: `email_missing`, `email_invalid`, `foreign_domain`, `email_repeated` (вторая и следующие строки, регистр не важен, даже если первая с ошибкой), `unit_archived`, `too_long`; `reason` ошибки — «ошибка: …», дословно «ошибка: подразделение в архиве» (spec.md:489) и «ошибка: повтор почты» (spec.md:490); у обновления — «будет обновлён: ФИО: было → стало; подразделение: было → стало», у новой — «будет добавлен», у неизменной — «без изменений» (plan.md:1213-1214); пустые ФИО и подразделение в файле прежние значения не стирают; `summary`: `added`, `updated`, `unchanged`, `errors`, `deleted` (0 до выполнения), `would_delete` (сколько удалит флажок), `origin_changed`, `not_loaded`; `new_units` — названия подразделений, которых нет в справочнике (по первому написанию, без повторов) | коды `parse_file` | запись `RequesterImport` в одной транзакции; журнала предпросмотр не пишет; файл не хранится | test_sd_requester_import::test_row_error_email_missing_or_bad_format, test_row_error_foreign_domain, test_row_error_duplicate_email_other_case_second_row, test_duplicate_email_error_even_if_first_row_has_error, test_row_error_unit_in_archive, test_row_error_field_length_exceeded, test_units_missing_in_dictionary_listed_as_to_be_created, test_row_results_added_updated_unchanged_error, test_updated_row_shows_name_and_unit_was_became, test_preview_writes_nothing, test_preview_2000_rows_within_10_seconds, test_preview_counts_rows_with_empty_cells_kept, test_sd_requester_import_2::test_file_not_stored_after_parse |
| `confirm` | `confirm(item, *, delete_missing=False, actor, ip=None)` | `RequesterImport` (`state="done"`); строка загрузки под `select_for_update`; повтор вызова после выполнения возвращает прежний итог и ничего не пишет; строки проверяются заново; недостающие подразделения создаются (`dictionaries.create("client_unit", ...)`); каждая годная строка — в своей точке сохранения, запись строки — `requester_import.apply_row(row, *, actor)` (сбой строки — `result="error"`, остальные идут дальше); у годной строки, чей адрес есть в записях с отметкой «заявка», отметка становится «таблица» (`origin_changed`, обновлением не считается); флажок `delete_missing`: удаляются записи с отметкой «таблица» без заявок, чьих адресов нет среди адресов всех непустых строк файла (в том числе строк с ошибкой); запись с отметкой «таблица» и заявками, которой нет в файле, не удаляется, а получает отметку «заявка»; записи с отметкой «заявка» флажок не трогает; после выполнения в `rows` остаются только `number`, `result` (`"added"`, `"updated"`, `"unchanged"`, `"error"`), `reason`; `summary` — `added`, `updated`, `unchanged`, `errors`, `deleted`, `origin_changed`, `not_loaded`; пустые ячейки значения не стирают | нет (отказы строк — в `rows`) | журнал: `requester.created`, `requester.updated`, `requester.deleted` по номеру записи без адреса и ФИО; `client_unit.created` на созданные подразделения; в конце `requester_import.completed` (имя файла, флажок, итоги) | test_sd_requester_import_2::test_confirm_skips_error_rows_applies_others_with_total, test_confirm_rows_revalidated, test_confirm_each_valid_row_in_own_savepoint, test_confirm_creates_missing_units, test_empty_name_and_unit_cells_do_not_erase_values, test_same_file_again_all_rows_unchanged, test_repeat_confirmation_shows_previous_total_writes_nothing, test_flag_off_deletes_nobody, test_flag_on_deletes_table_records_without_tickets_not_in_file, test_flag_counts_all_nonempty_rows_including_error_rows_as_in_file, test_flag_never_deletes_ticket_origin_records, test_flag_table_record_with_tickets_becomes_ticket_origin_not_deleted, test_import_ticket_origin_record_becomes_table_origin_not_counted_updated, test_preview_and_total_show_deleted_and_origin_changed_counts, test_audit_requester_events_by_record_number_without_address_and_name, test_audit_import_completed_who_and_totals, test_audit_client_unit_created_for_created_units, test_executed_row_keeps_number_total_and_reason_only |
| `apply_row` | `apply_row(row, *, actor)` | результат строки (`"added"`, `"updated"`, `"unchanged"`); записывает одну годную строку подтверждения (создаёт или обновляет заявителя); `confirm` зовёт её в своей точке сохранения на каждую строку; точка подмены раздела 3.5 | сбой — исключение: `confirm` ставит строке `result="error"` и идёт дальше | запись заявителя | T-3128 test_confirm_each_valid_row_in_own_savepoint (подменяется для одной строки) |
| `sample_csv`, `sample_xlsx` | `sample_csv()`, `sample_xlsx()` | `bytes`: заголовки «Почта», «Фамилия», «Имя», «Отчество», «Подразделение» и две вымышленные строки; CSV — UTF-8 с BOM, разделитель `;` (как `staff_import.sample_csv`) | нет | ничего | test_sd_requester_import_2::test_sample_csv_and_xlsx_headers_and_two_fictional_rows |

Страница загрузки (`test_import_page_text_names_data_and_purpose`,
`test_import_pages_403_without_manage_right`) — маршрут и текст (разделы 12 и 14);
неподтверждённые предпросмотры чистит `retention.purge_requester_previews` (6.24,
`test_unconfirmed_preview_purged_after_a_day`).

### 6.24. `retention`

Сроки хранения и обезличивание: `apps/servicedesk/services/retention.py`; расписание, очереди и
ключи заданий — раздел 7. Константа `ANONYMIZED = "обезличено"` (раздел 2.2). Порции возвращают
`Batch` (6.1). Каждая заявка идёт в своей транзакции под `select_for_update` с повторной проверкой
отбора; сбой одной заявки не откатывает остальные порции (ловится, пишется в лог, следующая заявка
идёт дальше). Файлы стираются через `files.remove_paths` после фиксации; отсутствующий файл не
ошибка.

| Имя | Подпись | Возврат | Отказ (код) | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `anonymize_batch` | `anonymize_batch(*, size=50, done_total=0, nightly_limit=2000, after=None)` | `Batch`: отбор — вид `closed`, `anonymized_at` пусто, `closed_at` раньше границы `now.replace(year=now.year - retention_years)` (та же дата и время `retention_years` лет назад; для 29 февраля, если в году назначения такой даты нет (`ValueError`), — `now.replace(year=now.year - retention_years, day=28)`; сторонние библиотеки, `python-dateutil` в том числе, не добавляются; `retention_years` читается из настроек при каждом вызове; тесты берут границы ±2 дня от этой даты, решение Opus RB2-11), по возрастанию (`closed_at`, `id`), не больше `size`, строго после курсора `after=(closed_at, id)` последней отобранной заявки прежней порции (решение Opus RB2-12); `done` — число **обезличенных** (удачных) заявок порции, сбойные не входят (решение Opus П2, пересмотр RB2-12); `more=True`, если выбрано ровно `size` и `done_total + done < nightly_limit`; `last` — курсор (`closed_at`, `id`) последней отобранной заявки; сбойная заявка в эту ночь больше не выбирается (курсор двигается и через неё), в следующую — снова, цепочка порций всегда кончается; `done_total` — сколько обезличено за ночь прежними порциями (сумма `done`), его передаёт задание (раздел 7, решение Opus B2-11); открытые заявки не трогаются | нет | задание `anonymize_tickets` ставит следующую порцию в очередь `maintenance`, если `more` | test_sd_retention::test_selects_closed_by_closed_at_and_retention_years (дополнен прогоном с `clock` на 29.02.2028; исключение A1: заданий RQ в вызове `anonymize_batch` нет; нового имени нет), test_open_tickets_not_touched, test_reopened_ticket_counts_from_new_close, test_batch_of_50_and_next_batch_queued_in_maintenance, test_nightly_limit_2000_rest_next_night, test_failure_of_one_ticket_does_not_roll_back_others |
| `anonymize_one` | `anonymize_one(ticket_id)` | `bool`: `True` — обезличена, `False` — отбор уже не выполняется (заявка открыта заново, обезличена, нет); шаги в одной транзакции: 1) в ленте тексты `incoming`, `reply`, `comment` пусты, `author_email` и `author_name` — `ANONYMIZED`, из `data` событий удаляются ключи: `reason_text` у события передачи, `name` у `attachment_rejected`, `attachment_quarantined` и `reply_not_sent`; остальные ключи (в том числе `reason`-код, `status`, `resolution` события закрытия) остаются; событие закрытия сохраняет статус и текст решения; 2) строки `StoredFile` и `Attachment` удаляются, файлы — после фиксации; 3) входящие письма заявки: `raw_deleted=True`, `from_email`, `subject`, `message_id` очищены, файл письма — после фиксации; 4) `apps.integrations.mail.services.anonymize_related("ticket:<id>")` (раздел 5.3); 5) участники из копии удалены, события об участниках показывают «участник (обезличено)»; 6) `requester_email` и `requester_name` — `ANONYMIZED`, `requester` пусто, `search.rebuild(ticket, anonymized=True)`, `anonymized_at = now`; 7) `requesters.delete_if_orphan(requester, reason="срок хранения")` | нет | журнал `ticket.anonymized` (`actor=None`); при удалении записи заявителя `requester.deleted` с причиной «срок хранения» | test_sd_retention::test_feed_texts_emptied_and_authors_anonymized, test_event_data_texts_and_attachment_names_removed, test_close_event_keeps_status_and_resolution_text, test_kept_fields_number_subject_category_queue_unit_criticality_status_dates, test_requester_fields_anonymized_requester_link_cleared_search_rebuilt, test_attachments_rows_deleted_files_erased_after_commit, test_missing_file_on_repeat_is_not_error, test_inbound_mail_fields_cleared_and_raw_file_erased_after_commit, test_delivery_log_to_cc_attachments_and_attempt_errors_cleared, test_delivery_log_subject_reply_to_message_id_references_kept, test_participants_deleted_and_events_show_anonymized_participant, test_audit_ticket_anonymized_written, test_selection_rechecked_under_lock, test_all_text_fields_of_slice_models_free_of_address_and_name_after_job |
| `purge_inbound` | `purge_inbound(*, size=50, after=None)` | `Batch` (`done` — сколько обработано): письма без заявки (`ticket` пусто, любой итог: отклонённые, автоматические, ждущие настройки, с ошибкой разбора), полученные раньше `inbound_retention_days` назад (из настроек при каждом вызове), с `raw_deleted=False`, по возрастанию (`received_at`, `id`), не больше `size`, строго после курсора `after=(received_at, id)` последнего отобранного письма прежней порции (решение Opus RC-3); у них `raw_deleted=True`, `from_email`, `subject`, `message_id` пусты, итог (`outcome`) остаётся; письмо с заявкой не трогается; `more=True`, если выбрано ровно `size`; `last` — курсор (`received_at`, `id`) последнего отобранного письма; письмо, которое очистить не удалось, в этом запуске больше не выбирается | нет | файл письма стирается после фиксации; задание `purge_inbound` ставит следующую порцию, если `more` | test_sd_retention_2::test_purge_inbound_rejected_auto_waiting_error_mail_cleared, test_purge_inbound_file_sender_subject_message_id_cleared_result_kept, test_purge_inbound_not_before_inbound_retention_days, test_purge_inbound_mail_with_ticket_not_touched, test_purge_inbound_batches_of_50, test_waiting_mail_with_erased_file_not_parsed_again |
| `purge_orphan_files` | `purge_orphan_files(*, size=50, after="")` | `Batch` (решение Opus C3, по плану, «Запуск»: «порциями»): `done` — число стёртых файлов порции; порция — до `size` имён каталога по возрастанию имени строго после `after` (имя файла последней просмотренной порции), `more=True`, если просмотрено ровно `size` имён, `last` — имя последнего просмотренного; в каталоге `PROTECTED_ROOT/"inbound"` файлы `<id>.eml`, у которых нет строки `InboundMail` с этим номером или строка с `raw_deleted=True`; файлы с живой строкой и прочие имена не трогаются; файлы моложе 1 часа по времени изменения файла (`mtime`) не трогаются: опрос (`worker-inbox`) и ночная чистка (`worker-mail`) идут в разных процессах, и файл письма, записанный перед фиксацией, мог бы быть стёрт до неё; тест кладёт сироту и сдвигает её `mtime` на 2 часа назад (`os.utime`) — она стирается, свежая сирота остаётся (решение Opus B2-12, вариант 2) | нет | стирание файлов | test_sd_retention_2::test_purge_orphan_files_without_row_erased, test_purge_orphan_files_of_raw_deleted_rows_erased, test_purge_orphan_files_keeps_files_with_row |
| `purge_requester_previews` | `purge_requester_previews()` | `int`: удаляет `RequesterImport` в состоянии `preview`, созданные раньше суток назад; выполненные строки остаются | нет | удаление строк | test_sd_requester_import_2::test_unconfirmed_preview_purged_after_a_day |

Проверка «запись заявителя хранит только адрес, ФИО и подразделение» —
`test_sd_retention_2::test_requester_record_stores_only_address_name_unit` (читает поля модели,
раздел 2.2). Сводка по ящику для списка «Входящие письма» — `mailbox.status` (6.15).

## 7. Задания RQ и ключи Valkey

Расписание (cron-строки по UTC, `job_timeout`) стоит в разделе 1, таблица «Расписание»; здесь
нет её повтора. Пересчёт «Москва минус 3 часа» сверен скриптом (вывод — в заметках части c,
файл `utc.txt`): `02:10`, `02:20`, `02:30`, `02:50` по Москве дают `23:10`, `23:20`, `23:30`,
`23:50` UTC; строки `5 * * * *`, `25 * * * *`, `*/5 * * * *`, `* * * * *` от часового
пояса не зависят. Расхождений нет.

### 7.1. Функции заданий (`apps/servicedesk/tasks.py`)

Имя функции равно значению `name=` в `register` (у заданий среза 003 нет расхождения, как у
`purge_previews` и `purge_import_previews` в срезе 002). `config/cron.py` импортирует функции
из `apps.servicedesk.tasks` и ставит их по одной строке на задание: `register(<функция>,
queue_name="<очередь>", cron="<строка>", job_timeout=<число>, name="<имя>")`. `job_timeout` и
`cron` — литералы (целое и строка): тест читает файл разбором дерева, как
`test_deploy_files._cron_registrations`, которому T-3135 добавляет ключ `job_timeout`. Cron
зовёт функцию без аргументов, поэтому у всех аргументов есть значения по умолчанию.

| Имя и функция | Очередь | Что зовёт | Аргументы (по умолчанию) | Следующая порция | Тесты |
|---|---|---|---|---|---|
| `poll_mailbox()` | `inbox` | `services.mailbox.poll()` (6.15); результат не возвращается | нет | нет: замок и «каждую минуту» вместо порций | T-3106, T-3135 |
| `requeue_inbound()` | `inbox` | `services.mailbox.requeue_inbound()` (6.15) | нет | нет | T-3106 test_requeue_inbound_*, T-3135 |
| `autoclose(limit=50, after=None)` | `maintenance` | `services.closing.autoclose_batch(limit=limit, after=after)` (6.11) | `limit`, `after` (пара `waiting_since`, `id`; решение Opus RC-3) | при `Batch.more`: `autoclose`, `limit=limit`, `after=batch.last` | T-3111 test_autoclose_processes_in_batches_of_fifty |
| `reconcile_assignees(after_id=0)` | `maintenance` | `services.reconcile.batch(after_id=after_id, size=50)` (6.12) | `after_id` | при `Batch.more`: `reconcile_assignees`, `after_id=batch.last_id` | test_sd_reconcile::test_hourly_task_takes_fifty_people_per_batch_and_enqueues_next_batch |
| `purge_inbound(after=None)` | `maintenance` | `services.retention.purge_inbound(size=50, after=after)` (6.24) | `after` (пара `received_at`, `id`; решение Opus RC-3) | при `Batch.more`: `purge_inbound`, `after=batch.last` | T-3130 test_purge_inbound_batches_of_50 |
| `anonymize_tickets(done_total=0, after=None)` | `maintenance` | `services.retention.anonymize_batch(size=50, done_total=done_total, nightly_limit=2000, after=after)` (6.24) | `done_total` (решение Opus B2-11), `after` (пара `closed_at`, `id`; решение Opus RB2-12) | при `Batch.more`: `anonymize_tickets`, `done_total=done_total + batch.done` (число обезличенных, решение Opus П2), `after=batch.last` | T-3129 test_batch_of_50_and_next_batch_queued_in_maintenance, test_nightly_limit_2000_rest_next_night |
| `purge_requester_previews()` | `maintenance` | `services.retention.purge_requester_previews()` (6.24) | нет | нет | test_sd_requester_import_2::test_unconfirmed_preview_purged_after_a_day |
| `purge_orphan_files(after="")` | `maintenance` | `services.retention.purge_orphan_files(size=50, after=after)` (6.24, не трогает файлы моложе часа, решение Opus B2-12) | `after` (имя файла; решение Opus C3) | при `Batch.more`: `purge_orphan_files`, `after=batch.last` | T-3130 test_purge_orphan_files_* |

Правила порций (план, «Запуск»; 6.1, `Batch`):
- следующая порция ставится только если `Batch.more` истинно, и только после того, как
  обработанные в этой порции записи зафиксированы (каждая заявка идёт в своей транзакции);
- порции идут по возрастанию ключа порядка задания с курсором последней отобранной записи в
  аргументе `after` следующей порции: `autoclose` — (`waiting_since`, `id`), `purge_inbound` —
  (`received_at`, `id`), `reconcile_assignees` — `id` пользователя (`after_id`),
  `anonymize_tickets` — (`closed_at`, `id`), `purge_orphan_files` — имя файла; запись, которую
  обработать не удалось, в этом запуске больше не выбирается; `Batch.more` — выбрано ровно
  `size` записей (у `anonymize_tickets` ещё `done_total + done < 2000`), поэтому цепочка
  порций всегда кончается (решение Opus RC-3); курсор в `job.kwargs` проверяют
  существующие тесты порций (новых имён нет):
  test_sd_reconcile::test_hourly_task_takes_fifty_people_per_batch_and_enqueues_next_batch,
  T-3111 test_autoclose_processes_in_batches_of_fifty,
  T-3130 test_purge_inbound_batches_of_50,
  T-3129 test_batch_of_50_and_next_batch_queued_in_maintenance,
  T-3130 test_purge_orphan_files_*;
- постановка: `django_rq.get_queue("maintenance").enqueue(<та же функция из tasks>, **kwargs,
  job_timeout=600)`; аргументы только по ключам, поэтому тест сверяет `job.kwargs`
  (например, `{"limit": 50, "after": (...)}`, `{"after_id": 150}`, `{"after": (...)}`,
  `{"done_total": 100, "after": (...)}`, `{"after": "<имя файла>"}`);
- порция каждого из пяти заданий с порциями идёт с `job_timeout=600`, даже если у
  самого расписанного задания другой срок (план, «Запуск»: «порции периодических заданий —
  600 с»);
- функция задания не ловит исключения служб: порция, упавшая целиком, уходит в `failed`,
  следующую порцию ставит ночной запуск или следующий час.

### 7.2. Задания не по расписанию

| Задание | Очередь | Постановка | `job_timeout` и повторы | Тесты |
|---|---|---|---|---|
| `process_inbound(inbound_id)` в `apps/servicedesk/tasks.py` | `inbox` | `services.intake.enqueue(inbound_id)` (6.16): `django_rq.get_queue("inbox").enqueue(process_inbound, inbound_id, job_timeout=300, retry=Retry(max=5, interval=[60, 300, 900, 3600, 10800]))`; аргумент один, позиционный; внутри транзакции постановка идёт `transaction.on_commit` (вне транзакции — сразу). Функция зовёт `services.intake.process(inbound_id)`; исключение шага идёт наружу, повтор делает RQ | 300 с; пять повторов (интервалы выше); после последней неудачи строка остаётся в `status="error"` (её ставит `process`, 6.16), задание в `failed` | T-3106 test_parse_job_enqueued_only_after_commit, T-3107, T-3135 |
| порции периодических заданий | `maintenance` | 7.1 | 600 с, повторов нет | T-3111, T-3129, T-3130 |
| `scan_file` для вложений | `files` | ядро: `apps.core.tasks.enqueue_scan(str(StoredFile.id))` (CONTRACT-002 § 3), его зовёт `attachments.accept` после фиксации; задание и повторы — те же, что у фото | как у фото, но `core.tasks.enqueue_scan` ставит задание с `job_timeout=300` (больше `CLAMAV_TIMEOUT` 120 с и времени переноса файла); правка кода ядра в Этапе 3 (решение Opus C2) | T-3119 test_clamav_unavailable_ticket_created_attachment_waits_and_job_retries |
| `deliver_message` | `mail` | `send_rendered` (раздел 5.3) | как в разделе 5.3 | T-3118 |

### 7.3. Как тест находит задание и проверяет срок

- в очереди: `[j for j in django_rq.get_queue("<очередь>").jobs if j.func_name ==
  "apps.servicedesk.tasks.<функция>"]`; номер письма — `job.args == (inbound_id,)`, остальные
  аргументы — `job.kwargs`; срок — `job.timeout` (целое число секунд); повторы —
  `job.retries_left == 5` и `job.retry_intervals == [60, 300, 900, 3600, 10800]`;
- ключевой запуск: тест выполняет `tasks.<функция>(**kwargs)` напрямую (не через рабочий
  процесс), внутри `django_capture_on_commit_callbacks(execute=True)`; следующую порцию он
  берёт из очереди и выполняет `job.perform()`; между тестами очереди чистит `valkey_clean`;
- `intake.has_job(inbound_id)` ищет `job.args[0] == inbound_id` у `process_inbound` в очереди
  `inbox`, в `scheduled_job_registry` (ждущие повтора) и в `started_job_registry` — тем же
  способом, что `core.tasks.requeue_pending_scans` у `scan_file` (CONTRACT-002 § 3); отдельного
  `job_id` у заданий нет;
- расписание: `grep`-подобная проверка по дереву `config/cron.py`: имя, функция (`register(
  poll_mailbox, ...)`), `queue_name`, `cron`, `job_timeout` по таблице раздела 1; всего
  четырнадцать вызовов `register` (шесть прежних и восемь новых).

### 7.4. Ключи Valkey среза 003

Клиент — `apps.core.services.valkey.conn()`; база 15 в тестах, чистится `valkey_clean`.

| Ключ | Тип и значение | Срок | Кто пишет | Тесты |
|---|---|---|---|---|
| `servicedesk:poll` | строка; значение — случайное `secrets.token_urlsafe()`; ставится `SET NX EX` | `EX 120` (`mailbox.LOCK_TTL`); после каждого забранного письма срок продлевается сценарием, сверяющим значение; в `finally` ключ удаляется сценарием только при своём значении | `mailbox.poll` | T-3106 test_second_poll_exits_when_lock_held (тест ставит ключ сам: `conn.set("servicedesk:poll", "other", nx=True, ex=120)`; чужое значение `poll` не удаляет) |
| `servicedesk:form:<ip>` | упорядоченное множество; элемент — `"<время в секундах с долями>:<случайный суффикс>"`, оценка — то же время; `<ip>` — адрес клиента строкой как есть (у IPv6 с двоеточиями) | `EXPIRE 3600` при каждой отметке (`form.RATE_WINDOW`); записи старше часа убирает сценарий | `form.register_hit` | test_sd_form::test_rate_limit_*; сброс — `scan_iter(match="servicedesk:form:*")` и `delete`: так делают автоиспользуемая фикстура T-3140 (`fresh_form_counters`) и `stand_reset` среза (раздел 8); прочие ключи они не трогают |
| кэш счётчика меню | не вводится: `listing.badge` считает два `COUNT` при каждом запросе (6.21, решение Opus B2-9; план) | - | - | test_sd_list_2::test_badge_updates_on_page_load_without_cache |

Ключи прежних срезов (`perms:<id>`, счётчики входа, `rq:*`) не меняются.

## 8. Команды стенда и восстановление

Команды лежат в `apps/servicedesk/management/commands/`: `e2e_poll_mailbox.py`,
`e2e_backdate.py`, `e2e_run_job.py`, `servicedesk_after_restore.py`; `e2e_reset_stand`
остаётся в `apps/core/management/commands/`. Тесты зовут их `call_command(...)`; вывод
читают через `capsys` или `StringIO` (`stdout=`); отказ — `django.core.management.CommandError`
(в консоли — сообщение в `stderr` и код выхода 1; ошибка разбора аргументов — код 2).

### 8.1. Общее для трёх команд `e2e_*`

| Что | Требование | Тесты |
|---|---|---|
| Защита | команда работает только при `E2E_STAND=1` в окружении; иначе `CommandError("Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено.")` — тот же текст, что у `e2e_reset_stand`; до проверки флага команда не читает базу, Valkey и ящик (тест ставит `FakeMailbox` и проверяет `connects == 0`, а в базе ничего не меняется) | T-3136 test_stand_commands_poll_mailbox_backdate_run_job_refused_without_e2e_stand |
| Вывод | одна строка в `stdout`, заканчивается переводом строки; формат — по таблицам ниже; пароли и адреса в строки не попадают | T-3136 |
| Код выхода | 0 — выполнено; `CommandError` — отказ (1) | T-3136 |
| Запуск с хоста | приёмка запускает команды в службе `standtools`: `docker compose -f deploy/docker-compose.yml --profile dev exec -T standtools python manage.py e2e_<имя> <аргументы>`, как `E2E_RESET_CMD`; флаг `E2E_STAND=1` стоит только у `standtools`, в `web` команда `e2e_*` отказывает; шаблон команды помощники берут из переменной окружения `E2E_STAND_CMD` (по образцу `E2E_RESET_CMD`); `CLAMAV_*` этим командам не нужны, каталог `protected` у `standtools` смонтирован | T-3140 `helpers_sd.poll_now()`, `backdate()`, `run_job()` |

### 8.2. Команды

| Команда | Командная строка | Что делает и что выводит | Тесты |
|---|---|---|---|
| `e2e_poll_mailbox` | без аргументов | опрос и разбор сразу: повторяет `mailbox.poll()` (при состоянии `locked` — до 10 раз раз в секунду) до скачивания нуля писем, затем в порядке `id` зовёт `intake.process(id)` для писем в `received`, не дожидаясь рабочего процесса (ошибка разбора считается, команду не останавливает; строка получает `status="error"`, как при задании). Вывод: `poll_mailbox: state=<ok\|disabled\|locked\|unavailable> fetched=<число> parsed=<число> errors=<число>`; состояния `disabled` (нет `IMAP_HOST`), `unavailable` (текст ошибки — `last_error`, он уже прошёл `safe_error`) и `locked` после повторов — `CommandError` | T-3136 test_stand_poll_mailbox_polls_and_parses_at_once; T-3140 `helpers_sd.poll_now()` |
| `e2e_backdate` | `e2e_backdate <kind> <ref> <field> <days>`; `<kind>` — `ticket`, `mail` или `mailbox`; `<ref>` — для `ticket` номер заявки (`Ticket.number`), для `mail` — `Message-ID` письма как в заголовке, вместе с `<` `>` (`InboundMail.message_id`), для `mailbox` — `-`; `<days>` — целое число от 1 | сдвигает сохранённую отметку назад на `<days>` суток так же, как `backdate` (раздел 3.4): `update` без `save()`, пустое значение — от `timezone.now()`. Поля: `ticket` — `waiting_since`, `closed_at`, `created_at`, `last_message_at`; `mail` — `received_at`; `mailbox` — `last_ok_at` (строка `MailboxState`). Вывод: `backdate: <kind> <ref> <field> -<days>d <было ISO UTC> -> <стало ISO UTC>`. Отказ (`CommandError`): неизвестный вид, поле не из списка своего вида, `<days>` не целое или меньше 1, объекта нет, у `mail` найдено несколько писем с одним `Message-ID` (тест использует уникальные). Вид `mailbox` — решение Opus C4 | T-3136 test_stand_backdate_shifts_ticket_and_mail_timestamps_back; T-3140 `helpers_sd.backdate(...)` |
| `e2e_run_job` | `e2e_run_job <job>`; `<job>` — `autoclose`, `anonymize_tickets` или `purge_inbound`; другое значение — ошибка разбора (код 2) | выполняет задание **целиком, прямо в процессе команды**, без очереди: цикл порций по 50 по цепочке, пока `Batch.more` истинно, с курсором `after=batch.last` следующей порции (у `anonymize_tickets` ещё с накоплением `done_total` — суммой `done` — и пределом 2000, как в 7.1); цикл всегда кончается (решение Opus RC-3); следующие порции в очередь не ставятся. Вывод: `run_job: <job> done=<число обработанных записей> batches=<число порций>` | T-3136 test_stand_run_job_runs_autoclose_anonymize_tickets_purge_inbound_now |

Тесты `e2e_*` идут с обычным `django_db` (без соединения `migrate`): команды пишут в базу
через соединение `default`. Задача T-3140 называет виды `e2e_backdate` по-русски («заявка|письмо»);
коды — `ticket|mail|mailbox`. Числа в выводе `e2e_poll_mailbox` (`fetched`, `parsed`) — только этой
команды: плановый `poll_mailbox` мог забрать письмо раньше; приёмка проверяет результат в
интерфейсе (с ожиданием), а не эти числа.

### 8.3. Сброс стенда: точка `stand_reset` среза

Команда ядра `e2e_reset_stand` сохраняется, но (CONTRACT.md и CONTRACT-002.md порядок не закрепляют,
правок строк нет; код — T-3202, tasks.md:230–236; сама функция среза
`apps.servicedesk.stand.stand_reset` — T-3242) зовёт функции точки `stand_reset` в
**обратном порядке регистрации** (`reversed(extensions.registered("stand_reset"))`):
данные среза держат `PROTECT`-ссылки на узлы `org`. С одним `org` порядок прежний. Функция среза —
`apps.servicedesk.stand.stand_reset()`, без аргументов, регистрируется в
`apps/servicedesk/extensions.py`; работает через соединение `migrate`, если оно настроено
(как `apps.org.stand.stand_reset`). Она приводит данные среза к состоянию после миграций:

| Что | Результат | Тесты |
|---|---|---|
| Данные среза | стёрты все строки моделей `servicedesk` (заявки, элементы ленты, вложения, участники, заявители, загрузки, входящие письма, очереди-отметки, справочники); порядок стирания — зависимостей `PROTECT`, раньше узлов `org` | T-3136 test_reset_stand_clears_servicedesk_data_before_org_units, test_reset_stand_calls_stand_reset_points_in_reverse_registration_order |
| Начальные справочники и настройки | пересозданы по разделу 2.2: статусы с видами и отметками, критичности, сложность, источники, категория «Другое»; `ServiceDeskSettings` `pk=1` со значениями 7/7/10/3/30, без доменов и очереди по умолчанию | T-3136 test_reset_stand_recreates_initial_dictionaries_and_settings |
| Последовательность | `servicedesk_ticket_number` установлена так, что `sequence_state() == (1, False)`: следующая заявка получает номер 1 (`setval(…, 1, false)` через `migrate`) | T-3136 test_reset_stand_resets_ticket_number_sequence_via_migrate_connection |
| Файлы | содержимое каталогов `PROTECTED_ROOT/attachments` и `PROTECTED_ROOT/inbound` стёрто, сами каталоги остаются; файлы `incoming/` и `quarantine/` стирает ядро (записи `StoredFile` перед очисткой таблиц) | T-3136 test_reset_stand_clears_attachments_and_inbound_files |
| Очереди | `django_rq.get_queue("inbox").empty()` и то же для `maintenance` | T-3136 test_reset_stand_clears_inbox_and_maintenance_queues |
| Порог формы | удалены ключи `servicedesk:form:*` (это и есть «заявки сверх порога за час», решение 8 задач, T-3242), остальные ключи не тронуты | T-3136 test_reset_stand_clears_form_threshold_keys_only |
| `MailboxState` | `IMAP_HOST` задан и ящик отвечает — строка `pk=1` со значениями на текущий конец ящика: `uidvalidity` ящика, `last_uid = uidnext - 1`, `connected_at`, `last_poll_at`, `last_ok_at` — «сейчас», `last_error=""`; письма прежних кругов разбираться не будут; ящик не отвечает или `IMAP_HOST` пуст — строка удалена (первое подключение создаст её само); соединение — `imap.connect()` через модуль (подменяется `FakeMailbox`) | T-3136 test_reset_stand_sets_mailbox_state_to_current_mailbox_end |
| `org` без среза | при единственной зарегистрированной точке `org` порядок и результат как в срезе 002 | T-3136 test_reset_stand_with_only_org_keeps_slice_002_order |

Тесты `e2e_reset_stand` и `servicedesk_after_restore` помечаются
`pytest.mark.django_db(databases=["default", "migrate"])` (шапка): сброс таблиц требует
прав владельца, `transaction=True` не работает. Данные, которые команда должна увидеть
(заявки, письма, строка последовательности), тест создаёт через то же соединение
`migrate` (`Model.objects.using("migrate")`; помощники `support_servicedesk` принимают
ключ `using="migrate"`); чтение результата — тоже через `migrate`.

Приёмка (T-3140): файлы, которые считают «всё на стенде» — сумму по очереди по умолчанию, число
писем во «Входящих», нулевые права (`test_d08` после установки, `test_d09`, `test_d14`,
`test_d_success_criteria`, `test_d10`) — начинаются с вызова помощника
`helpers_sd.reset_stand_and_relogin()` (T-3140: вызывает
`e2e_reset_stand` и заново создаёт администратора круга; запись круга в `helpers.ADMINS`
сбрасывается); заявки, письма
и домены прежних файлов круга иначе остаются на стенде.

### 8.4. `servicedesk_after_restore`

Команда **не** защищена `E2E_STAND`: её запускает администратор по `deploy/RESTORE.md`
(`docker compose run --rm migrate python manage.py servicedesk_after_restore`). Без аргументов.
Без соединения `migrate` (`"migrate" not in connections.databases`) — `CommandError("Нужен
DATABASE_MIGRATE_URL: команда работает под владельцем схемы.")` (тест
`test_after_restore_uses_migrate_connection` убирает алиас через `monkeypatch.delitem(
connections.databases, "migrate")`). Все чтения и записи базы — через соединение `migrate`.

| Шаг | Что делает | Тесты |
|---|---|---|
| 1. Номера | в одной транзакции: `current` — `last_value` последовательности `servicedesk_ticket_number` при `is_called`, иначе `last_value - 1`; `top` — наибольший `Ticket.number` (0 без заявок); `new = max(current, top) + 1000`; `SELECT setval('servicedesk_ticket_number', new, true)`; следующая заявка получает `new + 1`; значение никогда не уменьшается: повторный запуск даёт ещё `+1000` | T-3136 test_after_restore_shifts_sequence_1000_past_max_of_sequence_and_number, test_after_restore_uses_max_ticket_number_when_greater_than_sequence, test_after_restore_twice_never_lowers_sequence_and_never_repeats_a_number, test_next_ticket_after_restore_gets_number_beyond_lost_range |
| 2. Письма | для каждого `InboundMail` в `status="received"` по `id` — `intake.enqueue(id)` (после фиксации; тест — внутри `django_capture_on_commit_callbacks(execute=True)`); обработанные и с ошибкой не ставятся | T-3136 test_after_restore_queues_parsing_for_received_inbound_mails, test_after_restore_does_not_requeue_already_parsed_mails |
| Вывод | `after_restore: sequence=<new> max_number=<top> requeued=<число>`; код 0 | T-3136 |

## 9. Журнал и лента

### 9.1. Журнал: общие правила

Запись — `apps.core.services.audit.record(action, *, actor=None, object_type="", object_id="",
before=None, after=None, ip=None)` (6.1). Что одинаково для всех кодов:
- `object_type` — латинский код вида объекта (колонка ниже), русское название — в
  `OBJECT_TYPES` файла `apps/servicedesk/audit_labels.py`; `object_id` — строка;
  у вида `sd_dictionary` (события `sd_dictionary.*` и `client_unit.*`) —
  `"<вид справочника>:<id>"` с видом из пути раздела 12 (`categories`, `priorities`,
  `complexities`, `statuses`, `sources`, `client-units`), чтобы номера разных моделей не
  смешивались (решение Opus Ж-1);
- `actor` — сотрудник, выполнивший действие, у действий системы (задания, разбор письма,
  сверка, обезличивание) — `None`; колонка «Кто» ниже;
- `before` и `after` — словари; ключи только из таблицы; пустой словарь допустим;
  значения справочников — названия (строки), не номера, там, где ниже написано «название»;
  у ключей с суффиксом `_id` — целые;
- журнал **не хранит**: тексты писем, ответов, комментариев, решения и причины передачи;
  адреса и ФИО заявителей и участников из копии; темы заявок; имена вложений (FR-289);
  у ФИО заявителя пишется только факт «изменено» (`requester_name_changed`, `name_changed`);
  адреса заявителя нет ни в одном событии; адрес клиента формы — только колонка `ip` у
  `ticket.created` с формы (`ip=None` у заявки из письма и от исполнителя); имена
  сотрудников-исполнителей хранятся (как в журнале `org`);
- ключи `code`, `key`, `link`, `url` не используются (6.1); ключи не пересекаются с
  `FIELDS` модуля `org` (`kind`, `mode`, `mark`, `date`, `year` не берутся для других
  значений); общие по смыслу `unit`, `unit_id`, `signature`, `file_id`, `file_name`,
  `skipped`, `totals`, `created`, `errors` берутся с тем же смыслом;
- русские названия событий, полей, видов объекта и значений — `ACTIONS`, `FIELDS`,
  `OBJECT_TYPES`, `VALUES` файла `audit_labels.py`; функция `audit_labels()` точки
  возвращает `{"actions", "fields", "object_types", "values"}`, как у `org`; слияние с
  `org` — по правилам ядра (внутренние словари `values` объединяются, поздние побеждают);
  значения `values["reason"]` согласованы с `org` (`manual` — «вручную»);
- названия видов объекта (`OBJECT_TYPES`): `ticket` «заявка», `requester` «заявитель»,
  `requester_import` «загрузка» (план, «Журнал»; та же подпись у `staff_import` среза 002 —
  двусмысленность в фильтре журнала решена к следующей версии плана, в контракте не меняется),
  `queue` «очередь», `sd_dictionary` «справочник» (один вид для событий `sd_dictionary.*` и
  `client_unit.*`: одно значение `object_type`, план, «Журнал»; решение Opus П5),
  `servicedesk` «сервис-деск», `mailbox` «ящик заявок»; в фильтре вида объекта журнала
  появляются все семь, проверка по кодам вида (T-3131 test_audit_filter_has_new_object_kinds).

### 9.2. Коды событий журнала

Все тридцать четыре кода таблицы плана «Журнал». Строка таблицы — код; «Объект» — `object_type`
и `object_id`; «Кто» — `actor`. Тесты: T-3131 (`test_sd_audit.py`) для всех строк, плюс те,
что названы в разделе 6.

| Код (русское название в `ACTIONS`) | Объект | Кто | `before` | `after` |
|---|---|---|---|---|
| `ticket.created` («Заявка создана») | `ticket`, номер заявки | у канала `staff` — исполнитель; у `mail` и `form` — `None` | `{}` | `number`, `channel` (`mail`, `form`, `staff`), `queue` (название), `queue_id`, `category` (название или `""`), `priority` (название), `source` (название), у `staff` ещё `created_by` (имя сотрудника), `created_by_id`; у формы `ip` — в колонке |
| `ticket.assigned` («Назначен ответственный») | `ticket`, номер | кто назначил или взял; при создании с `take_by` — он же; при ответственном по умолчанию категории — `None` | `assignee` (имя или `""`), `assignee_id` (или `None`) | `assignee`, `assignee_id` |
| `ticket.assignee_removed` («Ответственный снят») | `ticket`, номер | вручную — исполнитель; сверка и передача в очередь — как у вызвавшей функции (сверка — `None`) | `assignee`, `assignee_id` | `assignee` (`""`), `assignee_id` (`None`), `reason`: `manual` («вручную»), `queue_changed` («смена очереди»), `not_participant` («больше не участник очереди») |
| `ticket.transferred` («Заявка передана в другую очередь») | `ticket`, номер | исполнитель | `queue`, `queue_id` | `queue`, `queue_id`, `reason_given` (`True`, если причина непуста; текста причины нет) |
| `ticket.updated` («Заявка изменена») | `ticket`, номер | исполнитель; у `set_status` по письму — `None` | только изменённые из `category`, `priority`, `complexity`, `client_unit`, `status` (названия, `""` — «не задано») | те же ключи; при смене ФИО заявителя — только `requester_name_changed: True` (и в `before` ничего) |
| `ticket.closed` («Заявка закрыта») | `ticket`, номер | исполнитель | `status` | `status` (текст решения не хранится) |
| `ticket.autoclosed` («Заявка закрыта автоматически») | `ticket`, номер | `None` | `status` | `status` |
| `ticket.reopened` («Заявка открыта заново») | `ticket`, номер | вручную — исполнитель; письмом — `None` | `status` | `status`, `via`: `manual` («вручную») или `mail` («письмом заявителя») |
| `ticket.reply_sent` («Ответ отправлен») | `ticket`, номер | исполнитель | `{}` | `entry_id` (номер элемента ленты; у повторной отправки — номер нового элемента) |
| `ticket.comment_added` («Комментарий добавлен») | `ticket`, номер | исполнитель | `{}` | `entry_id` |
| `ticket.attachment_quarantined` («Вложение в карантине») | `ticket`, номер | `None` | `{}` | `file_id` (`str(StoredFile.id)`), `signature` |
| `ticket.mail_failed` («Письмо не доставлено») | `ticket`, номер | `None` | `{}` | `mail_kind`: `confirmation`, `assigned`, `closed`, `autoclosed`, `reopened`, `reply` (часть имени шаблона после точки) |
| `ticket.participant_removed` («Участник снят») | `ticket`, номер | исполнитель | `{}` | `participant_id` (адреса и имени нет) |
| `ticket.anonymized` («Заявка обезличена») | `ticket`, номер | `None` | `{}` | `number` |
| `requester.created` («Заявитель добавлен») | `requester`, номер записи | вызвавшая заявка или загрузка: у формы и письма `None`, у `staff` — исполнитель, у загрузки — администратор | `{}` | `origin` (`ticket`, `table`), `client_unit` (название или `""`) |
| `requester.updated` («Заявитель изменён») | `requester`, номер записи | администратор или исполнитель (правка подразделения заявки) | `client_unit`; у смены отметки — `origin` | `client_unit`; `name_changed: True`, если ФИО изменено (без значений); у смены отметки — `origin` (`table`); адрес заявителя после создания не меняется, ключа нет |
| `requester.deleted` («Заявитель удалён») | `requester`, номер записи | администратор; обезличивание — `None` | `origin` | пусто; при удалении по сроку — `reason: "срок хранения"` (дословно, строка, как `delete_if_orphan(reason=...)`), при удалении загрузкой — `reason: "загрузка таблицы"` |
| `requester_import.completed` («Загрузка заявителей выполнена») | `requester_import`, номер строки загрузки | администратор | `{}` | `file_name`, `delete_missing` (bool), `totals` (словарь: `added`, `updated`, `unchanged`, `errors`, `deleted`, `origin_changed`) |
| `queue.marked` («Очередь отмечена») | `queue`, номер узла | администратор | `{}` | `unit` (название узла), `unit_id` |
| `queue.unmarked` («Отметка очереди снята») | `queue`, номер узла | администратор | `unit`, `unit_id` | `{}` |
| `queue.default_changed` («Очередь по умолчанию изменена») | `queue`, номер нового узла | администратор | `unit`, `unit_id` (пусто, если не было) | `unit`, `unit_id` |
| `sd_dictionary.created` («Значение справочника добавлено») | `sd_dictionary`, `"<вид>:<id>"` (вид из пути раздела 12, кроме `client-units`) | администратор | `{}` | `dictionary` (`category`, `priority`, `complexity`, `status`, `source`), `name`, `order`; у категории ещё `queue` (название), `default_assignee` (имя или `""`), `on_form` (bool); у статуса ещё `status_kind` (`new`, `in_progress`, `waiting`, `closed`), `is_default` (bool) |
| `sd_dictionary.updated` («Значение справочника изменено») | `sd_dictionary`, `"<вид>:<id>"` (вид из пути раздела 12, кроме `client-units`) | администратор | только изменённые из ключей строки `sd_dictionary.created` | `dictionary` и `name` всегда, и изменённые |
| `sd_dictionary.archived`, `.restored` («Значение справочника в архиве», «Значение справочника возвращено из архива») | `sd_dictionary`, `"<вид>:<id>"` (вид из пути раздела 12, кроме `client-units`) | администратор | `{}` | `dictionary`, `name` |
| `sd_dictionary.deleted` («Значение справочника удалено») | `sd_dictionary`, `"<вид>:<id>"` (вид из пути раздела 12, кроме `client-units`) | администратор | `dictionary`, `name` | `{}` |
| `client_unit.created` («Подразделение-клиент добавлено») | `sd_dictionary`, `"client-units:<id>"` | администратор; при загрузке заявителей — он же | `{}` | `name` |
| `client_unit.updated` («Подразделение-клиент изменено») | `sd_dictionary`, `"client-units:<id>"` | администратор | `name` | `name` |
| `client_unit.archived`, `.restored` («Подразделение-клиент в архиве», «Подразделение-клиент возвращено из архива») | `sd_dictionary`, `"client-units:<id>"` | администратор | `{}` | `name` |
| `client_unit.deleted` («Подразделение-клиент удалено») | `sd_dictionary`, `"client-units:<id>"` | администратор | `name` | `{}` |
| `servicedesk.settings_changed` («Настройки сервис-деска изменены») | `servicedesk`, `"1"` | администратор | каждое изменённое поле из `domains` (список строк), `default_priority` (название), `autoclose_days`, `reopen_days`, `form_hourly_limit`, `retention_years`, `inbound_retention_days` | те же ключи; очередь по умолчанию сюда не входит (её пишет `queue.default_changed`) |
| `mailbox.connected` («Ящик заявок подключён») | `mailbox`, `"1"` | `None` | `{}` | `uidvalidity`, `last_uid` |
| `mailbox.recreated` («Ящик заявок пересоздан») | `mailbox`, `"1"` | `None` | `uidvalidity` | `uidvalidity`, `skipped` (сколько писем пропущено) |

Значения `VALUES` (русские): `channel` — `mail` «письмо», `form` «форма», `staff`
«исполнитель»; `via` — `manual` «вручную», `mail` «письмом заявителя»; `reason` — `manual`
«вручную», `queue_changed` «смена очереди», `not_participant` «больше не участник
очереди»; `origin` — `table` «таблица», `ticket` «заявка»; `dictionary` — `category`
«категория», `priority` «критичность», `complexity` «сложность», `status` «статус», `source`
«источник»; `status_kind` — по разделу 2.1; `mail_kind` — `confirmation` «подтверждение
заявки», `assigned` «взята в работу», `closed` «закрыта с решением», `autoclosed` «закрыта
автоматически», `reopened` «открыта заново», `reply` «ответ исполнителя». Русские названия
`FIELDS` — по смыслу ключа: `number` «номер», `channel` «канал», `queue` «очередь»,
`category` «категория», `priority` «критичность», `complexity` «сложность», `source`
«источник», `status` «статус», `assignee` «ответственный», `created_by` «кто создал»,
`client_unit` «подразделение», `reason_given` «указана причина», `requester_name_changed`
«ФИО заявителя изменено», `name_changed` «ФИО изменено», `entry_id` «номер элемента ленты»,
`participant_id` «номер участника», `mail_kind` «вид письма», `via` «способ», `origin`
«отметка записи», `delete_missing` «удалять отсутствующих», `domains` «домены»,
`default_priority` «критичность по умолчанию», `autoclose_days` «срок автозакрытия, дней»,
`reopen_days` «срок открытия заново, дней», `form_hourly_limit` «порог формы в час»,
`retention_years` «срок хранения заявок, лет», `inbound_retention_days` «срок хранения
писем без заявки, дней», `dictionary` «справочник», `name` «название», `order` «порядок»,
`default_assignee` «ответственный по умолчанию», `on_form` «на форме», `status_kind` «вид
статуса», `is_default` «по умолчанию», `uidvalidity` «UIDVALIDITY», `last_uid` «последний
UID», `added` «добавлено», `updated` «обновлено», `unchanged` «без изменений», `deleted`
«удалено», `origin_changed` «сменили отметку на «заявка»»,
`reason` «причина» (код, решение Opus RB2-10; подпись значения — через `VALUES`, как в `org`),
`queue_id` «номер очереди», `assignee_id` «номер ответственного», `created_by_id` «номер
создавшего»; ключи `*_id` со значением по смыслу `before_id` в ленте в журнал не входят.

### 9.3. Лента: события `TicketEntry` вида «событие»

Запись — только `replies.add_event(ticket, event, *, actor=None, data=None)` (6.10); у
`TicketEntry(kind="event")` `text=""`, `author` — `actor` (у системы пусто), `data` — словарь
ниже. Названия ключей латинские; тексты по-русски собирает карточка из кода и `data`
(тексты сообщений — раздел 14); названия справочников и имена сотрудников в `data` — на
момент события. Колонка «Обезличивание» — что убирает `retention.anonymize_one` (6.24, шаг 1).

| Код `event` | Когда (кто пишет) | Ключи `data` | Обезличивание |
|---|---|---|---|
| `assignee_changed` | любое назначение, взятие себе, смена и ручное снятие; ответственный по умолчанию при создании и смене категории (`assignment`, `tickets.create`, `transfer.change_category`): «ответственный: было → стало» | `before` (имя или `""`), `after` (имя или `""`), `before_id`, `after_id` (или `None`) | остаётся |
| `assignee_reconciled` | сверка: «ответственный снят: больше не участник очереди» (`reconcile.for_users`) | `before`, `before_id` | остаётся |
| `transferred` | передача в очередь: «кто, откуда, куда, причина» (`transfer.transfer`; кто — `author`) | `from`, `to` (названия очередей), `from_id`, `to_id`, `reason_text` (свободный текст причины или `""`; ключ `reason` в `data` — только код, решение Opus RB2-10) | ключ `reason_text` удаляется |
| `queue_changed` | смена очереди при смене категории (`transfer.change_category`) и при открытии заново, если узел больше не очередь (`closing.reopen`): «очередь: было → стало» | `from`, `to`, `from_id`, `to_id`; при открытии заново дополнительно `reason`: `"queue_unmarked"` (код, 6.2; подпись «очередь снята» — в ленте, 14.5) | остаётся |
| `category_changed` | смена категории (`transfer.change_category`) | `before`, `after` (названия), `before_id`, `after_id` | остаётся |
| `priority_changed`, `complexity_changed`, `client_unit_changed` | правка поля из карточки или группового действия (`tickets.update_fields`), по одному на поле | `before`, `after` (названия или `""`), `before_id`, `after_id` (или `None`) | остаётся |
| `requester_name_changed` | правка ФИО заявителя в заявке («ФИО заявителя изменено», `tickets.update_fields`) | `{}` (значений нет) | нечего убирать |
| `status_changed` | любая смена статуса (`tickets.set_status`): «статус: было → стало» | `before`, `after` (названия), `before_id`, `after_id`, `reason`: `assigned`, `reply`, `letter`, `manual`, `close`, `autoclose`, `reopen` (6.7; пишется при каждой смене статуса, в том числе при закрытии, автозакрытии и открытии заново; решение C1 отменено итоговой сверкой, F4-2) | остаётся |
| `closed` | закрытие с решением (`closing.close`) | `status` (название), `status_id`, `resolution` (текст решения) | остаётся целиком (FR-290: статус и текст решения) |
| `autoclosed` | автозакрытие (`closing.autoclose_one`) | `status` (название), `status_id`, `days` (срок автозакрытия на момент закрытия) | остаётся |
| `reopened` | открытие заново (`closing.reopen`) | `via`: `manual` или `mail`; `status` (название), `status_id` | остаётся |
| `continued` | на прежней заявке при создании продолжения (`tickets.create(previous=...)`): «продолжение — заявка #N» | `number` (номер новой заявки) | остаётся |
| `participant_removed` | снятие участника (`tickets.remove_participant`) | `participant_id` (адреса и имени нет) | после удаления участника показывается «участник (обезличено)» |
| `reply_not_sent` | ответ не отправлен (`replies.on_files_checked`): заявка закрыта, вложение в карантине, архив с паролем | `reason`: `ticket_closed`, `quarantine`, `encrypted`; `entry_id` (номер элемента `reply`); у `quarantine` и `encrypted` ещё `name` (имя вложения) | ключ `name` удаляется |
| `mail_failed` | недоставка после последней попытки (`replies.on_mail_failed`): «письмо не доставлено: <вид письма>» | `mail_kind` (как в 9.2), `entry_id` (номер элемента `reply`; ключа нет у писем без элемента) | остаётся |
| `attachment_rejected` | `attachments.on_found` для `Heuristics.Encrypted.*` (решение Opus B2-15): «вложение «…» не принято: архив с паролем» | `name`, `reason`: `encrypted` | ключ `name` удаляется |
| `attachment_quarantined` | `attachments.on_found` для остальных сигнатур: «вложение в карантине» | `name` | ключ `name` удаляется |

Прочие элементы ленты (`incoming`, `reply`, `comment`) `data` не используют: `{}`.
События ленты не хранят адресов и ФИО заявителей (кроме `author_*` у `incoming`, которые
чистит обезличивание). Событие о создании заявки в ленте не пишется: первый элемент — письмо
или текст заявки. Повторная отправка (`replies.resend`) события не пишет (6.10). При
закрытии, автозакрытии и открытии заново пишутся две строки: `status_changed` («статус: было →
стало», его пишет `set_status` при каждой смене статуса) и сверх него `closed`, `autoclosed`
или `reopened` (решение C1 отменено итоговой сверкой, F4-2; по plan.md:721-722).

## 10. Письма заявителю

Письма заявки идут через `letters.send` (6.17) и `send_rendered` (5.3); тексты — рендерер
`letters.render` (раздел 5.3, 6.17). Тексты писем — из спеки, подраздел «Тексты писем»
(`spec.md:1348-1387`): простой текст, по-русски; в спеке они помечены «предложение,
подтверждается подписью» (`spec.md:1350-1351`). Угловые скобки — подстановки.

### 10.1. Виды писем и шаблоны

| Шаблон (`MailMessage.template`) | Файл | Кому (`To`, `Cc`) | `Auto-Submitted` | Когда уходит | Тесты |
|---|---|---|---|---|---|
| `ticket.confirmation` | `templates/servicedesk/mail/ticket_confirmation.txt` | заявителю, копии нет | `auto-replied` у заявки из письма (источник `mail`), `auto-generated` у формы и заявки исполнителя | после создания заявки | T-3118 test_confirmation_*, test_auto_submitted_* |
| `ticket.assigned` | `.../ticket_assigned.txt` | заявителю, в копию — неснятые участники | `auto-generated` | первое появление ответственного после создания | test_assigned_letter_text_and_sent_once_on_first_assignment |
| `ticket.closed` | `.../ticket_closed.txt` | заявителю, в копию — неснятые участники | `auto-generated` | `closing.close` | test_closed_autoclosed_reopened_texts_and_recipients |
| `ticket.autoclosed` | `.../ticket_autoclosed.txt` | то же | `auto-generated` | `closing.autoclose_one` | то же |
| `ticket.reopened` | `.../ticket_reopened.txt` | то же | `auto-generated` | `closing.reopen` | то же |
| `ticket.reply` | `.../ticket_reply.txt` | то же | заголовка нет | ответ исполнителя поставлен в очередь | test_executor_reply_text_without_additions_with_signature |

Видов писем ровно шесть (`letters.TEMPLATES`, 6.17); списка `SUBJECTS` почтового модуля они не
касаются; исполнителям писем о заявках нет (FR-259). Отказа заявителю «письмо отклонено»
(чужой домен, автоответ) нет: письма без заявки ответа не получают (FR-215, FR-216).

### 10.2. Заголовки и поля `MailMessage`

| Что | Значение | Тесты |
|---|---|---|
| `Subject` и `MailMessage.subject` | `"[#<Ticket.number>] <тема>"`, где тема — `mail_parse.clean_subject(ticket.subject)` (переводы строки, табуляции и управляющие знаки заменены пробелом, не длиннее 255; решение 14 задач); пустая тема — `"[#<N>]"` без пробела на конце; при создании заявки тема очищается так же | test_subject_is_number_and_ticket_subject_with_control_chars_cleaned |
| `From` | `formataddr((PortalSettings.name, settings.DEFAULT_FROM_EMAIL))`; `settings.DEFAULT_FROM_EMAIL` — значение переменной окружения `SMTP_FROM` (`config/settings.py:192`), атрибута `settings.SMTP_FROM` нет; тест ставит `settings.DEFAULT_FROM_EMAIL` | test_from_header_has_portal_name_and_smtp_from |
| `To` | `ticket.requester_email` | test_to_requester_cc_unremoved_participants_and_no_cc_for_confirmation |
| `Cc` и `MailMessage.cc` | адреса неснятых участников через запятую; адрес заявителя в копию не попадает; у подтверждения `""` | то же |
| `Reply-To` («адрес для ответа») и `MailMessage.reply_to` | `settings.SERVICEDESK_MAILBOX`; при пустом значении заголовок `Reply-To` не пишется и `MailMessage.reply_to == ""`, домен `Message-ID` — часть `settings.DEFAULT_FROM_EMAIL` после `@`; пустой `SERVICEDESK_MAILBOX` значит только «нет адреса для `Reply-To`»: приём писем он не выключает (`poll` идёт при заданном `IMAP_HOST`) и на «ящик не подключён» не влияет (решение Opus C7, уточнено F4-6) | test_reply_to_is_servicedesk_mailbox |
| `Message-ID` и `MailMessage.message_id` | `letters.new_message_id()`: `make_msgid(domain=<часть SERVICEDESK_MAILBOX после «@»>)`, вид `<…@домен>`; значение сохраняется до отправки | test_own_message_id_with_mailbox_domain_saved_before_send |
| `References` и `MailMessage.references` | идентификаторы первого письма заявителя (`InboundMail.message_id` первого элемента `incoming`, если он есть) и предыдущего письма портала по заявке (`message_id` последней `MailMessage` с тем же `related_ref`), по порядку, без повторов, через пробел; список пуст — заголовок не пишется | test_in_reply_to_and_references_chain_first_requester_letter_and_previous_portal_letter |
| `In-Reply-To` | последний идентификатор из `MailMessage.references` (отдельного поля нет, решение Opus RA2-5); список пуст — заголовок не пишется | то же |
| `Auto-Submitted` и `MailMessage.auto_submitted` | по таблице 10.1: `auto-replied`, `auto-generated` или `""` (заголовок не пишется); `auto-notified` не используется | T-3118 test_auto_submitted_* |
| прочие служебные заголовки | кроме `X-Portal-Template` (значение — `MailMessage.template`, как в срезе 001; `TEMPLATE_HEADER`; по нему приёмка опознаёт письма) других нет: план других не называет, `Precedence`, `X-Auto-Response-Suppress` и подобных нет | T-3118 |
| `related_ref` | `"ticket:<Ticket.id>"` — первичный ключ заявки, не номер (решение Opus B2-4); номера элемента нет; элемент ответа находится по `TicketEntry.mail`; не длиннее 64 знаков | T-3118, T-3129 test_delivery_log_*, test_sd_reply (недоставка) |
| `attachments` | `str(StoredFile.id)` принятых и проверенных вложений элемента `reply` (`letters.attachment_ids`); у остальных шаблонов `[]`; рендерер включает только `clean` | test_deliver_renders_body_from_database_at_send_time |
| `job.meta["context"]` | только `ticket_id`, `entry_id` (или `None`), `after_hours` (6.17); `ticket_id` — решение контракта (по нему тест находит задание; ПДн не несёт) | test_mail_body_not_stored_and_job_meta_has_no_texts_or_addresses |
| тело | в `MailMessage` не хранится, собирается рендерером в момент отправки | то же |
| пароли и ссылки входа | в письмах нет (FR-257) | test_letters_have_no_passwords_or_login_links |

Вид письма для недоставки: `replies.on_mail_failed` читает `MailMessage.template`
(`ticket.reply`), берёт часть после точки (`reply`) и кладёт в `data["mail_kind"]` ленты и
`after["mail_kind"]` журнала (раздел 9). Заявку находит по `related_ref`
(`ticket:<id>`), элемент — по `TicketEntry.objects.filter(mail_id=mail_id)`; у писем без
элемента (`confirmation`, `assigned`, `closed`, `autoclosed`, `reopened`) `entry_id` в `data`
не пишется.

### 10.3. Что рендерер отдаёт для каждого шаблона

`letters.render(message, context) -> Rendered(body, attachments)`; тело — шаблон Django
(`.txt`, автоэкранирования нет). Названия подстановок контекста шаблона:

| Шаблон | Подстановки | `attachments` |
|---|---|---|
| `ticket.confirmation` | `greeting_name` (ФИО заявки, а без него адрес: `ticket.requester_name or ticket.requester_email`), `number`, `subject`, `text` (текст первого элемента `incoming`), `rejected` (список пар «имя», «подпись причины» из `attachments.rejected_of(entry)`; пуст — строки нет), `assignee_name` (есть, только если ответственный назначен при создании; «Имя Фамилия» по правилу C5 ниже), `after_hours` (`None` — строки нет; строка — дата и время «ДД.ММ.ГГГГ ЧЧ:ММ» по Москве, фраза шаблона «…мы рассмотрим её с {after_hours}» дословно по FR-254; `""` — строка «Заявка поступила в нерабочее время, мы рассмотрим её в ближайшее рабочее время.» (plan.md:534–536; дополнение 6 раздела 16, решение C6 отменено)) | `[]` |
| `ticket.assigned` | `number`, `assignee_name` | `[]` |
| `ticket.closed` | `number`, `resolution` (`ticket.resolution`; письмо идёт сразу после закрытия), `reopen_days` (из `ServiceDeskSettings` в момент отправки) | `[]` |
| `ticket.autoclosed` | `number`, `autoclose_days` (из настроек в момент отправки), `reopen_days` | `[]` |
| `ticket.reopened` | `number` | `[]` |
| `ticket.reply` | `text` (текст элемента `reply` без добавлений), `signature` («Имя Фамилия» автора ответа по правилу C5 ниже) | пары (имя вложения, `files.attachment_path`) вложений элемента со статусом `clean`; недоступное не включается |

«Имя Фамилия» (`assignee_name`, `signature`) берётся из
`User.full_name` («Фамилия Имя Отчество»): слов два и больше — второе слово, пробел, первое;
одно слово — как есть; пустое — пусто (решение Opus C5).

### 10.4. Тексты (дословно, `spec.md:1348-1387`)

Подтверждение (`spec.md:1354-1363`):

```
Здравствуйте, <ФИО или адрес>!
Ваша заявка принята под номером <N>.
Тема: <тема>
Текст заявки: <текст>
[Вложения, которые не приняты: <имя, причина>.]
[Исполнитель: <Имя Фамилия>.]
[Заявка поступила в нерабочее время, мы рассмотрим её с {after_hours}.]
Чтобы дополнить заявку, ответьте на это письмо, не меняя тему.
Отправляя заявку, вы согласны на обработку ваших персональных данных (адрес,
ФИО, подразделение и текст заявки) для работы ИТ-отдела.
```

Строки в квадратных скобках — необязательные блоки шаблона (скобок в письме нет): строка
«Исполнитель» есть, только если ответственный назначен при создании заявки (`spec.md:1366`);
строка о согласии есть и в подтверждении заявки от исполнителя (`spec.md:1367`); фраза о
нерабочем времени — только по `after_hours` (FR-254, `spec.md:1096-1102`). Перечень не принятых
вложений: «<имя> — <подпись причины>», через «; » (формат контракта; подписи — `REJECT_TITLES`,
раздел 2.2).

«Взята в работу» (`spec.md:1368-1370`):

```
Ваша заявка № <N> взята в работу. Ответственный: <Имя Фамилия>.
```

«Закрыта с решением» (`spec.md:1373-1375`):

```
Ваша заявка № <N> закрыта. Решение: <текст решения>.
Если проблема не решена, ответьте на это письмо в течение <срок> дней — заявка
откроется заново.
```

«Закрыта автоматически» (`spec.md:1378-1380`):

```
Заявка № <N> закрыта автоматически: мы ждали вашего ответа <число> дней.
Если вопрос остался, ответьте на это письмо в течение <срок> дней — заявка
откроется заново.
```

«Открыта заново» (`spec.md:1383`):

```
Заявка № <N> снова в работе.
```

Ответ исполнителя (`spec.md:1385-1386`): текст ответа без добавлений; подпись — имя и
фамилия исполнителя, отдельной строкой после текста. Здесь `<срок>` — `reopen_days`,
`<число>` — `autoclose_days` из настроек на момент отправки (на закрытой заявке
`waiting_since` уже снят, срок из заявки не вычислить).

## 11. Что меняется в `CONTRACT.md` и `CONTRACT-002.md`

Перечень T-3138, п. 13. Сами файлы не правятся этой частью: их правит T-3138. Номера строк
сверены командами `sed -n` по состоянию на 2026-10-06 (все указанные строки на месте). «Было» —
дословно; «Стало» согласовано с разделами 1-3 этого контракта. Правки CONTRACT*.md идут с
разрешения владельца с диффом (правило T-3138).

### 11.1. `CONTRACT.md`

| Строка | Было | Стало |
|---|---|---|
| 16 | `\| Файлы \| `config/cron.py`, `apps/core/management/commands/{create_first_admin,rotate_field_keys}.py`, `deploy/{Dockerfile,nginx.conf}`, `templates/` с подключением `vendor/bootstrap-*`, `vendor/htmx-*`, `vendor/alpine-*` через `{% static %}` \| test_stack::test_project_layout_matches_plan, test_vendor_assets_present_with_licenses \|` | то же значение ячейки «Требование» и дописано в её конце: «; файлы среза 003 (`apps/servicedesk/`, `deploy/dovecot/`, `deploy/backup/`) описывает `CONTRACT-003.md`»; ячейка «Тесты» не меняется |
| 199 | `\| `deploy/docker-compose.yml` \| сервисы `web`, `worker`, `scheduler`, `nginx`, `postgres`, `valkey`, `mailpit`; `profiles: ["dev"]` только у `mailpit`; `worker`: `rq worker --with-scheduler … mail`; `scheduler`: `rq cron config.cron` без `--with-scheduler`; `web`: `gunicorn` + `uvicorn_worker.UvicornWorker` + `config.asgi` (compose или `Dockerfile`); у `nginx` — `./certs:/etc/nginx/certs` и `127.0.0.1:8031:`; порты postgres и valkey наружу не публикуются \|` | `\| `deploy/docker-compose.yml` \| сервисы `web`, `worker`, `worker-mail`, `worker-inbox`, `scheduler`, `backup`, `nginx`, `postgres`, `valkey`, `mailpit`, `dovecot`; `profiles: ["dev"]` только у `mailpit`, `profiles: ["dev", "test"]` у `dovecot`; `worker`: `rq worker -c config.rq_settings --with-scheduler files`, `worker-mail`: то же с очередями `mail maintenance`, `worker-inbox`: то же с очередью `inbox` (раздел 1 CONTRACT-003); `scheduler`: `rq cron config.cron` без `--with-scheduler`; `web`: `gunicorn` + `uvicorn_worker.UvicornWorker` + `config.asgi` (compose или `Dockerfile`); у `nginx` — `./certs:/etc/nginx/certs` и `127.0.0.1:8031:`; порты postgres и valkey наружу не публикуются \|` |
| 311 | `  Рабочий процесс: `rq worker -c config.rq_settings --with-scheduler mail`,` | `  Рабочие процессы: `rq worker -c config.rq_settings --with-scheduler` с очередями `files` (`worker`), `mail maintenance` (`worker-mail`) и `inbox` (`worker-inbox`),` |
| 312 | `  ночные задания: `rq cron config.cron -c config.rq_settings` (очередь `mail`,` | `  ночные задания: `rq cron config.cron -c config.rq_settings` (задания среза 001 — очередь `mail`,` |
| 313 (продолжение предложения, строка вне перечня T-3138, не меняется) | `  03:10, 03:20, 03:30).` | без изменений: прежние три задания остаются в очереди `mail`, её обслуживает `worker-mail`; задания среза 003 перечислены в разделе 1 CONTRACT-003 |
| 332 | `  `service_completed_successfully`; у web, worker и scheduler` | `  `service_completed_successfully`; у web, worker, worker-mail, worker-inbox и scheduler` |
| 333 | `  `DATABASE_MIGRATE_URL: ""`. `DATABASE_MIGRATE_URL` есть у `migrate`,` | без изменений |
| 334 | `  `standtools` и `test`. Тест — test_deploy_files::test_owner_credentials_only_in_one_shot_migrate_service.` | `  `standtools` и `test`; служба `backup` получает только `DATABASE_MIGRATE_URL` из `.env` через `environment`, без `env_file` (решение Opus C9); у `worker-mail` и `worker-inbox` — `DATABASE_MIGRATE_URL: ""`, как у `worker`. Тест — test_deploy_files::test_owner_credentials_only_in_one_shot_migrate_service (перечень служб в теле теста не меняется: он проверяет только `web`, `worker`, `scheduler`).` |

### 11.2. `CONTRACT-002.md`

| Строка | Было | Стало |
|---|---|---|
| 5 | `таблицы «Журнал», `perms:<id>`, очередь `files`, девять точек расширения, `Unit`, `Membership`,` | `таблицы «Журнал», `perms:<id>`, очередь `files`, девять точек расширения (в срезе 003 их тринадцать, CONTRACT-003 § 3.2), `Unit`, `Membership`,` |
| 38 | `\| `CLAMAV_HOST`, `CLAMAV_PORT`, `CLAMAV_TIMEOUT` \| значения по умолчанию: `clamav`, `3310`, `30` (секунд); задаются в `environment` служб `web`, `worker`, `test` в compose; в `deploy/.env.example` перечислены закомментированными (`# CLAMAV_HOST=clamav`, `# CLAMAV_PORT=3310`, `# CLAMAV_TIMEOUT=30`; … ` (остальной текст ячейки — без изменений) | значения по умолчанию: `clamav`, `3310`, `120` (секунд); задаются в `environment` служб `web`, `worker`, `worker-mail`, `worker-inbox`, `test` в compose; в `deploy/.env.example` — `# CLAMAV_HOST=clamav`, `# CLAMAV_PORT=3310`, `# CLAMAV_TIMEOUT=120`; остальной текст ячейки прежний (CONTRACT-003 § 1) |
| 39 | `… переменных `FRESHCLAM_CONF_*` и `CLAMD_CONF_*` в compose нет \| test_deploy_files::test_freshclam_conf_mounted_with_default_mirror \|` (конец ячейки) | `… переменных `FRESHCLAM_CONF_*` в compose нет; из `CLAMD_CONF_*` есть только `CLAMD_CONF_AlertEncryptedArchive: "yes"` в `environment` службы `clamav` (CONTRACT-003 § 1); тест тот же (п. (9) T-3138)` |
| 40 | `\| worker \| команда содержит `files mail` в таком порядке после `--with-scheduler`; смонтирован том `protected` на тот же путь, что у `web` (`/app/protected`) \| test_deploy_files::test_worker_listens_files_before_mail_and_mounts_protected \|` | `\| worker \| команда `rq worker -c config.rq_settings --with-scheduler files` (только очередь `files`), `deploy: replicas: 2`; том `protected` на тот же путь, что у `web` (`/app/protected`); очереди `mail maintenance` и `inbox` — службы `worker-mail` и `worker-inbox` с тем же томом \| test_deploy_files::test_worker_listens_files_before_mail_and_mounts_protected (правка — п. (6) T-3138) \|` |
| 41 | `\| nginx \| в `nginx.conf` и `nginx.prod.conf`: `client_max_body_size 6m;`; `location /protected/` с `internal;`, `alias /srv/protected/;` и заголовками … (дополнение 41) \| …` | то же, и дописано: «`client_max_body_size 6m;` остаётся общим в `http`; `55m` — только в двух `location` формы и ответа (`= /request/`, `~ ^/tickets/(new/\|[0-9]+/reply/)$`); общий `location /protected/` для фото не меняется; перед ним — `/protected/attachments/` и `/protected/inbound/` (CONTRACT-003 § 1)»; тест тот же (п. (10) T-3138) |
| 42 | `\| cron \| `config/cron.py` регистрирует три новых задания, очередь `mail`: `purge_import_previews` (`40 3 * * *`), `purge_quarantine` (`50 3 * * *`), `requeue_pending_scans` (`0 * * * *`); имя задания — `name=` в `register`; функции — раздел 3 \| test_deploy_files::test_cron_registers_preview_purge_quarantine_cleanup_and_scan_requeue \|` | то же и дописано: «три прежних задания среза 001 и эти три остаются; срез 003 добавляет восемь заданий (CONTRACT-003 § 1 и 7), всего в файле четырнадцать вызовов `register`; шесть прежних — без изменений»; тест тот же (п. (11) T-3138) |
| 64 | `\| `StoredFile.owner` \| `related_name="stored_files"` \| test_photo \|` | `\| `StoredFile.owner` \| `related_name="stored_files"`; `null=True`: у назначения `attachment` владельца нет (CONTRACT-003 § 2.2) \| test_photo \|` |
| 65 | `\| `StoredFile.purpose` \| `"photo"` (единственное значение) \| test_photo \|` | `\| `StoredFile.purpose` \| `"photo"` или `"attachment"` (CONTRACT-003 § 2.2) \| test_photo \|` |
| 66 | `\| `StoredFile.status` \| `"pending"`, `"clean"`, `"quarantine"` \| test_photo \|` | без изменений |
| 67 | `\| `StoredFile.id` \| `uuid.UUID`; в адресах, именах файлов и аргументах задания — `str(id)` в обычном виде с дефисами \| test_photo \|` | без изменений |
| 68 | `\| `StoredFile.content_type` \| `"image/png"` или `"image/jpeg"` (по содержимому) \| test_photo \|` | `\| `StoredFile.content_type` \| до 255 знаков: у фото `"image/png"` или `"image/jpeg"` (по содержимому), у вложения — тип из письма или загрузки \| test_photo \|` |
| 127 | `\| `permissions.menu_for` \| уточнение: элемент — словарь ровно с ключами `url`, `title`, `icon`, `order` (…); … Порядок: «Сотрудники» 10, «Структура» 20, «Календарь» 30, «Роли и права» 40, «Журнал событий» 50, «Настройки портала» 60, «Безопасность и политика» 70 — названия пунктов среза 001 прежние (permissions.py:20–26) \| …` | элемент — словарь с ключами `url`, `title`, `icon`, `order` и, только если у описания пункта есть функция `badge`, ещё `badge` (CONTRACT-003 § 3.2); порядок: «Заявки» 5, «Сотрудники» 10, «Структура» 20, «Календарь» 30, «Роли и права» 40, «Журнал событий» 50, «Настройки портала» 60, «Сервис-деск» 65, «Безопасность и политика» 70; остальной текст ячейки прежний; тесты те же (п. (2) T-3138) |
| 283 | `\| `POINTS` \| кортеж из девяти имён: `menu_items`, `role_sources`, `role_usage`, `audit_labels`, `staff_directory`, `card_sections`, `day_marks`, `home_notices`, `stand_reset`; `org` регистрирует во всех девяти точках обычные функции модулей `apps.org…` (`func.__module__` начинается с `apps.org`, дополнение 39) \| test_extensions::test_org_registers_all_nine_extension_points \|` | `\| `POINTS` \| кортеж из тринадцати имён (девять прежних по порядку и `unit_usage`, `file_purposes`, `mail_renderers`, `login_links`, CONTRACT-003 § 3.2); `org` регистрирует обычные функции модулей `apps.org…` в первых девяти точках (дополнение 39); остальные четыре — `servicedesk` \| test_extensions::test_org_registers_all_nine_extension_points (п. (1) T-3138) \|` |
| 284, 285 | `register`, `registered` (неизвестная точка — `ValueError`) | без изменений |
| 286 | `\| `clear` \| `clear() -> None`: очищает все девять реестров \| test_extensions \|` | `\| `clear` \| `clear() -> None`: очищает все тринадцать реестров \| test_extensions \|` |
| 287 | `\| `empty` \| `empty()` — контекстный менеджер: запоминает все реестры, … \| …` | без изменений (слово «все» теперь охватывает тринадцать) |
| 288 | `\| `menu_items` \| `func() -> list[dict]` (…): ключи `permissions` (кортеж кодов, достаточно любого), `url`, `title`, `icon` (путь шаблона значка `icons/<имя>.html`), `order` (целое); ядро описывает свои пункты так же; `permissions.menu_for(user)` отдаёт доступные пункты без ключа `permissions` — ровно `url`, `title`, `icon`, `order` (§ 11, A8; дополнение 33) \| test_org_permissions \|` | то же, и дописано: «необязательные ключи `visible` и `badge` (CONTRACT-003 § 3.2); `menu_for` отдаёт без ключа `permissions` `url`, `title`, `icon`, `order` и, только у пункта с функцией `badge`, ещё `badge`» |
| 633 | `3. A8: элемент меню, который отдаёт `menu_for`, — ровно `url`, `title`, `icon`, `order` (у описания из точки `menu_items` есть ещё `permissions`, дополнение 33); значки `icons/structure.html`,` | `3. A8: элемент меню, который отдаёт `menu_for`, — `url`, `title`, `icon`, `order` и, только у пункта с функцией `badge`, ещё `badge` (у описания из точки `menu_items` есть ещё `permissions`, дополнение 33, и необязательные `visible`, `badge`); значки `icons/structure.html`,` (следующая строка 634 — порядок «10, 20, 30, 40, 50, 60, 70» — «порядок 5, 10, 20, 30, 40, 50, 60, 65, 70») |
| 797 | `33. **`menu_items` и `menu_for`:** описание пункта из точки `menu_items` (и пункты ядра) несёт` | без изменений |
| 798 | `    `permissions`, `url`, `title`, `icon`, `order`; `permissions.menu_for(user)` отдаёт только` | `    `permissions`, `url`, `title`, `icon`, `order` и необязательные `visible`, `badge`; `permissions.menu_for(user)` отдаёт только` |
| 799 | `    доступные пункты и ровно с ключами `url`, `title`, `icon`, `order` (A8 — про результат` | `    доступные пункты с ключами `url`, `title`, `icon`, `order` и, только у пункта с функцией `badge`, ещё `badge` (A8 — про результат` |
| 800 | `    `menu_for`). Затрагивает: test_org_permissions, test_extensions.` | `    `menu_for`). Затрагивает: test_org_permissions, test_extensions, test_sd_boundaries.` |

Что в «Стало» согласовано с разделами 1-3: тринадцать точек и порядок имён — 3.2; ключи
`visible`, `badge` и условие появления ключа `badge` — 3.2; службы `worker`, `worker-mail`,
`worker-inbox`, очереди и `CLAMAV_TIMEOUT` 120 — раздел 1; четырнадцать заданий — разделы 1
и 7.1; `StoredFile` — 2.2. Строка 313 `CONTRACT.md` и строки 284, 285, 287, 66, 67, 797 в
перечень T-3138 входят, но менять в них нечего; строки перечня, где «Было» дано выдержкой («…»),
T-3138 берёт из файла дословно.

## 12. Маршруты и поля форм

Части d принадлежат разделы 12-14. Колонка «Тесты» называет серверные файлы (`test_sd_*`) и
файлы приёмки (`e2e/test_d01…d15`, `test_d_cross_cutting`, `test_d_success_criteria`).
Сервисы, которые зовёт маршрут, — раздел 6; тексты — раздел 14; зацепки разметки — раздел 13.

Общие правила (как в CONTRACT.md и CONTRACT-002 § 8; «НХ» — запрос HTMX, заголовок
`HX-Request: true`):
- все формы — POST с CSRF; без входа любой путь, кроме `/request/` и `/request/done/`, —
  302 на `/login/` (с `next`);
- ответ на запрос НХ — фрагмент без `<html>`, на обычный — полная страница; фрагменты
  `/tickets/<номер>/…` рисуют карточку (`[data-ticket-card]`, раздел 13); формы действий самой
  карточки целятся в `closest [data-ticket-card]` с `hx-swap="outerHTML"` в обеих раскладках
  (слайдер и страница; решение Opus F3-4), в `#slider-root` целится только ссылка карточки из
  списка (12.2);
- **два правила отказа**. Маршруты заявок `/tickets/<номер>/…` (в том числе файл и письмо):
  недоступная и несуществующая заявка отвечают **одинаково 404** (FR-236) и до проверки
  других прав; 403 здесь не бывает. Маршруты `/tickets/`, `/tickets/count/`, `/tickets/bulk/`,
  `/tickets/new/…` и все `/servicedesk/…` проверяют право **раньше** существования объекта:
  нет права — 403, одинаково для существующего и несуществующего номера (T-3133
  `test_requester_record_without_manage_right_same_403_for_existing_and_missing_id`);
- **отказ сервиса** (`ServiceDeskError`, код — 6.2) на POST — **всегда 200** с тем же
  шаблоном; текст из раздела 14 — в `[data-error="<поле>"]` у поля формы или, у общего отказа
  без поля, в `[role=alert]` (13.6, 14.1); база не меняется. Так и на запрос НХ:
  HTMX не подставляет ответы 4xx, а `static/js/htmx-glue.js` своей обработки ошибок не имеет
  (проверено чтением файла; решение плана, plan.md:795-798), поэтому сообщение приходит
  фрагментом со статусом 200. 403 и 404 на запрос НХ остаются 403 и 404 (прямое обращение,
  подмены нет);
- **успех**: обычный POST — 302 на адрес из таблицы; НХ-POST действий над заявкой — 200 и
  фрагмент карточки; НХ-POST там, где после успеха нужен другой адрес, — 200 с пустым телом и
  заголовком `HX-Redirect` (302 для XHR браузер выполнил бы сам, и в карточку попала бы
  целая страница). Сообщение об успехе — `[role=status]` страницы назначения; где оно названо
  в таблице, тест его ищет, где не названо — не ищет;
- **подтверждение**: `confirm=1` — у диалогов действий над заявками и справочниками
  (скрытое поле формы диалога, как `unit-delete` среза 002); у подтверждения загрузки
  заявителей поля нет (12.6, решение Opus RD1-2); POST без `confirm=1` там, где подтверждение
  обязательно, — 200 с `[role=alert]` «Подтвердите действие», ничего не меняется; смена
  категории — исключение (ниже);
- **файлы**: поле `files` (`input[type=file][name=files][multiple]`), несколько файлов с одним
  именем поля; формы с файлами — `multipart/form-data`; предел тела 55m в nginx (раздел 1);
- **флажки**: значение `1`; нет поля в теле — флажок снят;
- **неверный формат адреса** (номер не число, не `uuid`) — 404 (маршрут не найден; и без входа);
- **неизвестный или нечисловой id в поле**: для `assignee` и `user` — `not_participant`; для
  `status` — `bad_status`; для `priority` — поле игнорируется как отсутствующее; нечисловой номер
  в `numbers` — пропуск без номера с причиной «нет доступа»; для `client_unit` и `category` —
  `archived_value`, для `queue` — `not_queue`, как у архивного значения;
- **успешные сообщения о создании и передаче** (`Заявка #N создана в очереди «…»`, `Заявка #N
  передана в очередь «…»`) передаются через флеш-механизм ядра (`_flashes.html`) и видны на
  странице назначения как `[role=status]`.

### 12.1. Открытая форма (без входа)

| Путь | Метод, параметры, поля | Что ожидают тесты | Тесты |
|---|---|---|---|
| `/request/` | GET | 200 полной страницы без меню (в ответе нет `#main-menu`), `<meta name="viewport">`; приём открыт (`form.is_open`) — форма `form[data-form="request"]` с полями из следующей строки; закрыт — вместо формы `[data-closed-notice]` с текстом `form.closed_text()`; вошедший сотрудник видит то же, что гость (меню нет) | test_sd_form (test_request_page_opens_without_login_and_without_menu, test_form_has_required_fields_and_consent_checkbox, test_closed_page_without_domains_or_default_queue_names_mailbox, test_logged_in_user_sees_form_as_guest_with_csrf_and_no_captcha), test_sd_pages, e2e/test_d02_form |
| `/request/` | POST multipart: `email`, `name`, `client_unit` (id подразделения; пусто — «Нет в списке»), `category` (id), `subject`, `text`, `consent` (флажок), `files` (до 10). Имена полей — ключи `FormInvalid.errors` (6.19): `email`, `name`, `client_unit`, `category`, `subject`, `text`, `consent` | успех (`form.submit`) — 302 на `/request/done/`, адрес положен в сессию (`form.remember_done`), заявка создана; ошибки полей (`invalid_form`) — 200 той же страницы: у каждого неверного поля `[data-error="<поле>"]` с текстом (14.1), введённые значения сохранены (файлы — нет); отказ вложений, порога, закрытый приём — 200 с `[role=alert]` (в закрытом состоянии — тот же текст, что у GET); заявки нет; ответ не зависит от того, есть ли адрес среди заявителей, и ничего не подставляет (FR-224); CSRF — токен в форме | test_sd_form (все POST-тесты), e2e/test_d02_form |
| `/request/done/` | GET | 200: «Заявка принята. Подтверждение с номером придёт на <адрес>» (адрес — `form.pop_done(session)`, ключ из сессии удалён; номера на странице нет, `[data-done-email]` — адрес); сессия без адреса (в том числе второе открытие страницы) — 302 на `/request/` (решение Opus D1) | test_sd_form::test_done_page_shows_address_without_number_taken_from_session_and_removed, e2e/test_d02_form |
| `/login/` | GET (ядро) | в ответе ссылка из точки `login_links`: `a[data-login-link][href="/request/"]` с текстом «Подать заявку в ИТ-отдел» | test_sd_form::test_login_page_has_request_link_from_login_links, e2e/test_d02_form::test_d02_login_page_has_submit_request_link |

### 12.2. Список заявок

Параметры GET одинаковы у `/tickets/` и `/tickets/count/`; неизвестное или неверное значение
игнорируется (как пустое), 404 и 400 не бывает. Имена полей `listing.Filters` (6.21) — имена
параметров.

| Параметр | Значения | Тесты |
|---|---|---|
| `preset` | `mine` «Мои», `unassigned` «Без ответственного», `my_queues` «Мои очереди», `waiting` «Ждут ответа заявителя», `closed` «Закрытые», `all` «Все» (`listing.PRESETS`); нет параметра или неизвестное — `listing.default_preset(user)` | test_sd_list::test_preset_*, test_default_preset_* |
| `queue`, `category`, `priority`, `status`, `client_unit`, `source` | id (целое); `priority` — критичность | test_sd_list::test_filter_by_queue_category_criticality, test_filter_by_client_unit_and_source |
| `kind` | `new`, `in_progress`, `waiting`, `closed` (вид статуса, 2.1) | test_sd_list::test_filter_by_status_and_status_kind |
| `assignee` | id сотрудника или `none` — без ответственного | test_sd_list::test_filter_by_assignee_and_without_assignee, test_sd_list_2::test_employee_card_tickets_link_filters_by_assignee |
| `created_from`, `created_to` | дата `ДД.ММ.ГГГГ` (поле даты портала `[data-datefield]`, раздел 13) или `ГГГГ-ММ-ДД`; обе границы включительны, день по поясу портала | test_sd_list::test_filter_by_created_period_portal_date_field |
| `q` | строка поиска (6.21 `search.parse`); подсказка `hint` показывается в `[data-hint="short"]` | test_sd_search, test_sd_list::test_filters_combine_with_and |
| `sort`, `dir` | `sort` — `number`, `created`, `last_message`, `priority` (`listing.SORTS`), по умолчанию `number`; `dir` — `desc` (по умолчанию) или `asc` | test_sd_list::test_sort_* |
| `page` | целое от 1; нечисловое или меньше 1 — 1; страница за пределами — пустая сетка | test_sd_list::test_page_has_50_rows_and_next_page_by_51st_row |

| Путь | Метод, параметры, поля | Что ожидают тесты | Тесты |
|---|---|---|---|
| `/tickets/` | GET, параметры выше | 403 без пункта меню «Заявки» (`access.menu_visible` ложна); иначе 200: обычный запрос — страница целиком (панель фильтра, пресеты, сетка, групповая панель); запрос НХ с заголовком `HX-Target: tickets-grid` — **только сетка** (`#tickets-grid` с пагинацией и счётчиком, без панели фильтра и пресетов); любой другой НХ-запрос (например, закрытие слайдера) — страница целиком без базового шаблона (`layouts/fragment.html`); адрес с параметрами — прежний для «Назад»: разметка `form#tickets-filter[hx-get="/tickets/"][hx-target="#tickets-grid"][hx-push-url="true"]`, ссылки `a[data-preset]`, `th[data-sort] a`, `a[data-action="page-next"]`, `a[data-action="page-prev"]` — те же `hx-get`, `hx-target`, `hx-push-url="true"`; `visible_tickets` ограничивает строки (чужих нет ни в сетке, ни в счётчике, ни в поиске) | test_sd_list (в том числе test_filter_params_in_url_for_back_and_push_url), test_sd_list_2, test_sd_pages, test_sd_access, e2e/test_d14_find, e2e/test_d07_phone::test_d07_no_new_ticket_button_without_queue_and_direct_request_refused |
| `/tickets/count/` | GET, те же параметры (без `page`, `sort`, `dir`) | 403 без пункта меню; иначе всегда 200 фрагмент (даже без НХ): `[data-total]` с числом строк текущего фильтра (`listing.count`); до нажатия «показать количество» числа в сетке нет | test_sd_list::test_total_count_only_on_show_count_button |
| `/tickets/bulk/` | POST: `action` (`assign`, `transfer`, `priority`), `numbers` (повторяющееся поле, номера отмеченных заявок; не больше 100; повторы убираются, 6.8), параметры: `user` (id; для `assign`), `queue` (id) и `reason` (для `transfer`), `priority` (id; для `priority`) | 403 без пункта меню; вызов `assignment.bulk`; результат — блок `[data-bulk-result]` со словами «Выполнено: N; пропущено: M» и `li[data-skipped]` на каждую пропущенную заявку (в тексте «#номер — причина»; у недоступной номера нет, причина «нет доступа»); НХ — фрагмент блока (200), обычный запрос — 200 страница списка с блоком (решение Opus D2); `bulk_limit` и `bad_action` — 200 с `[role=alert]`; заявок видимых нет — «Выполнено: 0» | test_sd_assignment_2::test_group_*, test_sd_pages::test_bulk_action_skips_inaccessible_tickets_with_explanation_and_applies_to_accessible, test_sd_access::test_group_action_checks_access_of_each_ticket_separately, e2e/test_d04_dispatch |

### 12.3. Заявка от исполнителя

Право на маршруты — `access.can_create` (`executor.can_start`): участник очереди или держатель
`servicedesk.all`; иначе 403 (кнопки «Новая заявка» в разметке тоже нет, раздел 13).

| Путь | Метод, параметры, поля | Что ожидают тесты | Тесты |
|---|---|---|---|
| `/tickets/new/` | GET | 200 форма `form[data-form="ticket-new"]` (страницей; НХ — фрагмент в слайдере); поля — как в следующей строке; `select[name=priority]` выбрана критичность по умолчанию из настроек, `select[name=source]` — только `dictionaries.manual_sources()` | test_sd_executor::test_new_button_*, test_criticality_default_from_settings_and_changeable, test_manual_source_only_non_system_and_unarchived |
| `/tickets/new/` | POST multipart: `email`, `name`, `client_unit` (id или пусто), `category`, `queue`, `priority`, `source`, `subject`, `text`, `take` (флажок «Взять себе»), `files`; поля `email`, `name`, `client_unit`, `category`, `subject`, `text` называются как у открытой формы | вызов `executor.create`; успех, заявка видна заводящему (`visible`) — 302 на `/tickets/<номер>/`; не видна — 302 на `/tickets/` и `[role=status]` «Заявка #N создана в очереди «…»»; НХ-POST — 200 с `HX-Redirect` на тот же адрес; отказ сервиса — 200 с формой; код → поле, текст у поля в `[data-error="<поле>"]` без роли `alert`: `bad_email` → `email`; `requester_name_too_long` → `name`; `subject_required`, `subject_too_long` → `subject`; `description_required`, `description_too_long` → `text`; `category_required` → `category`; `queue_required`, `not_queue` → `queue`; `source_required` → `source`; общие отказы без поля — `[role=alert]`: `intake_closed`, `file_rejected`, `too_many_files`, `total_too_big`, `archived_value` (код не называет поле: какое из `category`, `client_unit`, `priority` архивное, по коду не определить; решение контракта, у Opus по этому месту решения нет); тексты — 14.1, атрибут `data-code` — как у открытой формы; `take` у не участника выбранной очереди молча игнорируется | test_sd_executor (все), test_sd_assignment::test_taken_letter_not_sent_on_creation_with_assignee, e2e/test_d07_phone |
| `/tickets/new/requester/` | POST `email` (в теле, не в адресе) | 200 всегда фрагмент `[data-requester-fields]` с `input[name=name]` и `select[name=client_unit]`, заполненными по `requesters.lookup(email)`, если `found`, иначе пустыми; значения остаются доступными для правки; нет права — 403; в адресе запроса адреса почты нет | test_sd_executor::test_requester_lookup_post_fills_name_and_department_for_known_address, test_requester_lookup_empty_for_unknown_incomplete_or_foreign_address, test_requester_lookup_address_in_body_not_in_url_no_suggestions, test_requester_lookup_forbidden_for_non_member, e2e/test_d07_phone |
| `/tickets/new/queue/` | GET `category` (id), `queue` (id, необязательно) | 200 фрагмент `[data-queue-fields]`: `select[name=queue]` — отмеченные узлы, выбран `queue` из запроса, а без него — очередь категории (`executor.queue_for_category`; у «Другое» — очередь по умолчанию); флажок `input[type=checkbox][name=take]` — включён и доступен, если `executor.can_take(user, queue)`, иначе без `checked` и с `disabled`; нет права — 403 | test_sd_executor::test_take_to_self_fragment_enabled_only_for_member_of_selected_queue, test_take_to_self_enabled_for_all_tickets_holder_in_any_queue, test_category_substitutes_queue_and_queue_can_be_changed_to_any_marked, e2e/test_d07_phone |

### 12.4. Карточка и действия над заявкой

Номер — целое. Действия, кроме отмеченных «видимость и участник», требуют только видимости
(`tickets.get_for`): невидимая — 404. Закрытая заявка: действия, кроме `comment` и `reopen`,
отказывают `ticket_closed` — 200 с карточкой и `[role=alert]` «Заявка закрыта: сначала откройте
её» (plan.md:795-796), в том числе на прямой POST. Успех НХ — 200 фрагмент карточки; обычный
запрос — 302 на `/tickets/<номер>/`. GET диалога или подсказки на закрытой заявке отвечает
так же, как POST: 200 с карточкой и `[role=alert]` «Заявка закрыта: сначала откройте её».

| Путь | Метод, параметры, поля | Что ожидают тесты | Тесты |
|---|---|---|---|
| `/tickets/<номер>/` | GET | запрос НХ (из списка) — фрагмент слайдера `.slider-panel` с `[data-ticket-card][data-layout="slider"]`; прямой адрес — страница целиком с `[data-layout="page"]`; ширину окна читает внешний `static/js/tickets.js` (до 600 px — обычный переход по `href`), сервер отдаёт обе раскладки одной разметкой; 404 для чужой и несуществующей заявки (одно и то же тело); поля, лента, формы — раздел 13 | test_sd_card (все), test_sd_pages, test_sd_access::test_foreign_ticket_page_404_same_as_missing_number, e2e/test_d03_reply::test_d03_card_slider_over_600px_list_and_separate_page_up_to_600px |
| `/tickets/<номер>/take/` | POST (без полей) | видимость, участник очереди, заявка открыта; `assignment.take`; отказ `not_participant` и `ticket_closed` — 200 с карточкой и `[role=alert]`; успех — ответственный я | test_sd_assignment::test_take_*, e2e/test_d03_reply |
| `/tickets/<номер>/assignees/` | GET `q` | 200 фрагмент всегда: `label[data-candidate][data-user-id]` с `input[type=radio][name=assignee]` — `access.suggest_assignees(queue, q)` (участники очереди и держатели `servicedesk.all`, без уволенных и не из очереди) | test_sd_assignment::test_assignee_suggestions_only_queue_members_by_name_start_case_and_yo_insensitive, e2e/test_d04_dispatch::test_d04_assigning_non_member_refused_and_not_in_picker |
| `/tickets/<номер>/assign/` | POST `assignee` (id сотрудника; пустое значение — снять ответственного) | `assignment.assign` или `assignment.unassign`; отказы `not_participant`, `ticket_closed` — 200 с `[role=alert]` | test_sd_assignment::test_assign_non_member_of_queue_refused_even_direct_request, test_unassign_without_letter_writes_feed_event, test_sd_assignment_2::test_closed_ticket_assign_and_transfer_refused_with_200_and_message |
| `/tickets/<номер>/transfer/` | GET — диалог; POST `queue` (id), `reason` (до 500 знаков, необязательно) | GET — фрагмент `[data-dialog="ticket-transfer"]` в `#dialog-root`: `select[name=queue]` (`transfer.target_queues`), `textarea[name=reason]`, `button[data-dialog-cancel]`, ничего не меняет; POST — `transfer.transfer`; успех, заявка видна — карточка (НХ — фрагмент; обычный — 302); **не видна после передачи** (`visible_after` ложно) — НХ: 200 с `HX-Redirect` на `/tickets/`, если `access.menu_visible(user)`, иначе на `/`; обычный запрос: 302 на тот же адрес; оба с `[role=status]` «Заявка #N передана в очередь «…»»; отказ (`same_queue`, `queue_required`, `not_queue`, `reason_too_long`, `ticket_closed`) — 200 с диалогом (НХ) или страницей и `[role=alert]` | test_sd_assignment::test_transfer_* (в том числе test_transfer_to_unavailable_ticket_returns_hx_redirect_with_message), test_sd_assignment_2, e2e/test_d04_dispatch |
| `/tickets/<номер>/category/` | POST `category` (id), `confirm` (`1`) | `transfer.change_category`; без смены очереди или с `confirm=1` — выполняется, 302 (НХ — карточка); со сменой очереди и без `confirm` — **200 фрагмент** `[data-dialog="ticket-category"]` с текстом «Заявка перейдёт в очередь «…»» (14.2), скрытыми `category` и `confirm=1`, кнопкой подтверждения и `button[data-dialog-cancel]`, ничего не меняется; архивная категория — 200 с `[role=alert]` (`archived_value`) | test_sd_assignment::test_category_change_*, test_sd_assignment_2::test_closed_ticket_category_and_fields_change_refused_with_200_and_message (test_sd_assignment_2.py), e2e/test_d04_dispatch::test_d04_category_change_to_other_queue_asks_confirmation_then_queue_changes_with_event |
| `/tickets/<номер>/fields/` | POST: любые из `priority` (id), `complexity` (id или пусто — очистить), `client_unit` (id или пусто), `requester_name`, `save_to_record` (`1`, кнопка «Сохранить и в записи заявителя»: `button[name=save_to_record][value="1"]`) | меняются только поля, чьи имена есть в теле (пустое значение `complexity` и `client_unit` очищает поле); `tickets.update_fields` (`save_name_to_record=True` при `save_to_record=1`); `archived_value` и `ticket_closed` — 200 с `[role=alert]`; тема не принимается: присланный `subject` игнорируется | test_sd_assignment_2::test_criticality_and_complexity_edit_write_event_per_field, test_department_edit_*, test_requester_name_*, test_subject_not_editable, e2e/test_d10_requesters::test_d10_executor_edit_journal_department_was_became_name_only_field_fact_with_record_number |
| `/tickets/<номер>/status/` | POST `status` (id) | `tickets.set_status_manual`; статусы — `dictionaries.manual_statuses()` (виды «в работе» и «ждёт ответа заявителя»); `bad_status`, `ticket_closed` — 200 с `[role=alert]` (закрытой заявке — отказ с объяснением, plan.md:795-796) | test_sd_status::test_manual_*, e2e/test_d06_autoclose, e2e/test_d09_settings::test_d09_new_in_progress_kind_status_available_for_manual_change |
| `/tickets/<номер>/reply/` | POST multipart: `text`, `wait` (флажок «Ждём ответа заявителя»), `files` | `replies.reply`; успех — 302 на карточку (НХ — карточка); `text_required`, `text_too_long`, `file_rejected`, `too_many_files`, `total_too_big`, `ticket_closed` — 200 с карточкой, `[role=alert]` и сохранённым текстом ответа; заявки с ожидающими файлами — элемент ленты с `data-send-state="waiting_files"` | test_sd_reply (все), e2e/test_d03_reply, e2e/test_d12_attachments |
| `/tickets/<номер>/reply/<элемент>/resend/` | POST (без полей) | `replies.resend(entry)`; номер элемента — `TicketEntry.id` этой заявки (элемент другой заявки — 404); `not_resendable`, `ticket_closed` — 200 с `[role=alert]` | test_sd_reply::test_resend_*, e2e/test_d12_attachments::test_d12_reply_not_sent_for_quarantine_shows_note_and_resend_button_countdown_from_actual_send |
| `/tickets/<номер>/comment/` | POST `text` | видимость (`tickets.get_for`); `replies.comment`; работает на закрытой заявке; `text_required` — 200 с `[role=alert]` | test_sd_card::test_internal_comment_*, test_sd_closing::test_internal_comment_on_closed_ticket_allowed_and_changes_nothing_else, e2e/test_d03_reply::test_d03_internal_comment_marked_visible_to_staff_only_and_not_mailed |
| `/tickets/<номер>/close/` | GET — диалог; POST `status` (id), `resolution` | GET — фрагмент `[data-dialog="ticket-close"]`: `select[name=status]` (`dictionaries.closing_statuses()`, первым — статус по умолчанию вида «закрыта»), `textarea[name=resolution]`, `button[data-dialog-cancel]`; POST — `closing.close`; успех — карточка (закрытая); `resolution_required`, `resolution_too_long`, `bad_status`, `ticket_closed` — 200 с диалогом и `[role=alert]` | test_sd_closing::test_close_*, e2e/test_d05_close |
| `/tickets/<номер>/reopen/` | POST (без полей) | видимость, заявка закрыта; `closing.reopen(via="manual")`; `ticket_open` — 200 с `[role=alert]` | test_sd_closing_2::test_manual_reopen_*, e2e/test_d05_close |
| `/tickets/<номер>/participants/<id>/remove/` | GET — диалог; POST `confirm` (`1`) | GET — `[data-dialog="participant-remove"]` с текстом подтверждения (14.2) и `input[type=hidden][name=confirm][value="1"]`; POST без `confirm=1` — 200 с `[role=alert]` «Подтвердите действие»; с ним — `tickets.remove_participant`; участник чужой заявки — 404; закрытая — `ticket_closed`, 200 | test_sd_assignment_2::test_remove_participant_*, test_closed_ticket_participant_removal_refused_with_200_and_message, e2e/test_d03_reply::test_d03_remove_participant_stops_mail_and_incoming_not_appended_event_in_feed |
| маршрута добавления участника нет | любой POST на `/tickets/<номер>/participants/` и `…/participants/add/` | 404 | test_sd_assignment_2::test_no_route_or_service_to_add_participant |
| маршрутов правки и удаления элементов ленты нет | POST и GET на `/tickets/<номер>/entries/…`, `…/reply/<элемент>/edit/`, `…/delete/` | 404 | test_sd_card::test_no_routes_to_edit_or_delete_feed_items |

### 12.5. Выдача файлов

Заголовки ставит маршрут (6.18 `attachments.download`, `source_mail`); тело ответа пустое, 200.

| Путь | Метод, параметры, поля | Что ожидают тесты | Тесты |
|---|---|---|---|
| `/tickets/<номер>/files/<uuid>/` | GET | 404: заявка не видна, файла нет у этой заявки, файл не `clean` (ожидающий и карантин не выдаются); успех — `X-Accel-Redirect: /protected/attachments/<uuid>`, `Content-Type: application/octet-stream`, `Content-Disposition: attachment; filename*=UTF-8''<имя, закодировано>` (имя вложения), `X-Content-Type-Options: nosniff`, `Cache-Control: no-store` (исключение `max-age` среза 002 — только фото) | test_sd_attachments::test_download_*, test_pending_and_quarantined_not_downloadable_requeue_picks_pending, test_sd_pages::test_inaccessible_attachment_and_source_email_return_404_same_as_missing, e2e/test_d12_attachments, e2e/test_d_cross_cutting::test_attachment_and_source_mail_headers_from_nginx_and_protected_not_reachable_directly |
| `/tickets/<номер>/mail/<id>.eml` | GET | 404: заявка не видна, письмо не привязано к этой заявке, `raw_deleted`, любое вложение не `clean` или `rejected` (FR-212); успех — `X-Accel-Redirect: /protected/inbound/<id>.eml`, `Content-Type: application/octet-stream`, `Content-Disposition: attachment; filename*=UTF-8''mail-<id>.eml` (решение Opus D3), `nosniff`, `Cache-Control: no-store` | test_sd_attachments::test_source_eml_*, e2e/test_d01_mail::test_d01_html_only_mail_shown_as_plain_text_and_source_mail_downloadable |

### 12.6. Настройки, очереди, справочники, заявители, входящие

Права на всё — `servicedesk.manage`; нет права — 403 (одинаково для существующего и
несуществующего `<id>`), без входа — 302. Страницы — полные; НХ получает фрагмент (формы
правки открываются в `#slider-root`, диалоги — в `#dialog-root`, как в срезе 002).

| Путь | Метод, параметры, поля | Что ожидают тесты | Тесты |
|---|---|---|---|
| `/servicedesk/` | GET | 200: форма настроек `form[data-form="servicedesk-settings"]`, адрес ящика и состояние опроса — только текстом (без `input`), предупреждение `IMAP_SECURITY=none`, меню разделов `nav[data-servicedesk-nav]` | test_sd_queues::test_mailbox_address_readonly_in_settings, test_initial_terms_and_limits_defaults_7_7_10_3_30_and_ranges_validated, test_sd_pages, e2e/test_d09_settings |
| `/servicedesk/` | POST: `domains` (строка через запятую или с новой строки), `default_priority` (id критичности), `autoclose_days`, `reopen_days`, `form_hourly_limit`, `retention_years`, `inbound_retention_days` | `settings.update`; успех — 302 на `/servicedesk/` и `[role=status]`; `bad_domain`, `out_of_range`, `archived_value` — 200 с `[role=alert]`; поля адреса ящика и очереди по умолчанию в теле игнорируются (очередь — на `/servicedesk/queues/`) | test_sd_queues (settings), e2e/test_d09_settings::test_d09_every_settings_change_in_journal_as_was_became_in_russian, e2e/test_d05_close::test_d05_changed_reopen_term_applies_to_next_reply_and_change_in_journal |
| `/servicedesk/queues/` | GET; необязательный `unmark` (id узла) | 200: дерево узлов с отметками (`[data-unit-tree]`); с `unmark=<id>` (НХ — фрагмент, обычный — страница с диалогом) — диалог `[data-dialog="queue-unmark"]`: число открытых заявок и категории, которые перейдут в очередь по умолчанию (`queues.unmark_preview`), по одному `[data-consequence]`, `input[type=hidden][name=confirm][value="1"]`; ничего не меняет; узел не очередь — 404 (решение Opus D4) | test_sd_queues::test_unmark_dialog_names_affected_categories_and_journal_gets_update_per_category, e2e/test_d09_settings |
| `/servicedesk/queues/` | POST: `action` (`mark`, `unmark`, `default`), `unit` (id узла), `confirm` (`1`, только у `unmark`) | `queues.mark`, `queues.unmark`, `queues.set_default`; успех — 302 на `/servicedesk/queues/` и `[role=status]`; `unmark` без `confirm=1` — 200 с `[role=alert]` «Подтвердите действие»; отказы (`already_queue`, `not_queue`, `queue_is_default`, `queue_has_open_tickets`) — 200 с `[role=alert]`; неизвестное `action` — 200 с `[role=alert]` | test_sd_queues (все), e2e/test_d09_settings::test_d09_unmark_queue_with_open_tickets_refused_without_open_tickets_passes, test_d09_default_queue_chosen_among_three_and_other_category_follows_it |
| `/servicedesk/dictionaries/<вид>/` | GET | `<вид>` — один из `categories`, `priorities`, `complexities`, `statuses`, `sources`, `client-units` (6.5: `category`, `priority`, `complexity`, `status`, `source`, `client_unit`); другое значение — 404 (после проверки права); список всех значений вида по `order`, затем названию (у `client-units` по названию): действующие и архивные с меткой (раздел 13) | test_sd_dictionaries, test_sd_pages::test_manage_routes_return_403_without_permission, e2e/test_d09_settings, e2e/test_d10_requesters::test_d10_client_departments_add_rename_archive_delete_only_unused |
| `/servicedesk/dictionaries/<вид>/new/` | GET — форма в слайдере; POST: `name`, `order` (кроме `client-units`), по виду: `categories` — `queue` (id узла-очереди), `default_assignee` (id или пусто), `on_form` (флажок); `statuses` — `kind` (`new`, `in_progress`, `waiting`, `closed`), `is_default` (флажок) | `dictionaries.create`; успех — 302 на `/servicedesk/dictionaries/<вид>/`; `name_required`, `name_too_long`, `name_taken`, `queue_not_marked`, `assignee_not_participant` — 200 формы с `[role=alert]`; `kind` вне четырёх — 200 с `[role=alert]` | test_sd_dictionaries (create), e2e/test_d09_settings::test_d09_category_default_assignee_not_in_queue_refused |
| `/servicedesk/dictionaries/<вид>/<id>/edit/` | GET — форма; POST: те же поля, что у `new/`, кроме `kind` (у статуса вид после создания не меняется: присланный `kind` маршрут отбрасывает, решение Opus D5) | `dictionaries.update`; успех — 302 на список вида; отказы — как у `new/`; `<id>` другого вида или нет — 404 | test_sd_dictionaries (update, system rename), e2e/test_d09_settings::test_d09_system_auto_closed_status_rename_passes_archive_refused |
| `/servicedesk/dictionaries/<вид>/<id>/archive/`, `…/restore/` | POST (без полей) | `dictionaries.archive`, `dictionaries.restore`; успех — 302 на список вида; `system_protected`, `last_active`, `default_protected` — 200 со списком и `[role=alert]` | test_sd_dictionaries::test_default_status_cannot_be_archived_or_deleted, test_last_active_status_of_kind_cannot_be_archived, e2e/test_d09_settings::test_d09_only_status_of_kind_cannot_be_archived |
| `/servicedesk/dictionaries/<вид>/<id>/delete/` | GET — диалог; POST `confirm` (`1`) | GET — `[data-dialog="dictionary-delete"]` с `input[type=hidden][name=confirm][value="1"]`, ничего не меняет; POST без `confirm=1` — 200 с `[role=alert]` «Подтвердите действие»; с ним — `dictionaries.delete`, 302 на список вида; `in_use`, `system_protected`, `default_protected`, `last_active` — 200 со списком и `[role=alert]` (при `in_use` в тексте слово «архив» и кнопка архива `[data-action="dictionary-archive"]`) | test_sd_dictionaries::test_delete_*, e2e/test_d09_settings::test_d09_used_value_delete_refused_archive_offered_archived_hidden_in_picker_visible_in_old_tickets |
| `/servicedesk/requesters/` | GET `q`, `client_unit` (id), `page` | 200 таблица «Заявители» (`requesters.page`): адрес, ФИО, подразделение, отметка записи, число заявок; поиск по адресу и ФИО без регистра и «е/ё»; 50 строк на странице | test_sd_requesters (все GET-тесты), test_sd_pages, e2e/test_d10_requesters |
| `/servicedesk/requesters/<id>/edit/` | GET — форма в слайдере; POST `name`, `client_unit` (id или пусто) | `requesters.update`; успех — 302 на `/servicedesk/requesters/`; `requester_name_too_long`, `archived_value` — 200 с `[role=alert]`; нет записи — 404 (после проверки права: без права 403 для существующей и несуществующей) | test_sd_requesters::test_edit_*, test_sd_pages::test_requester_record_without_manage_right_same_403_for_existing_and_missing_id |
| `/servicedesk/requesters/<id>/delete/` | GET — диалог; POST `confirm` (`1`) | GET — `[data-dialog="requester-delete"]`; POST без `confirm=1` — 200 с `[role=alert]` «Подтвердите действие»; с ним — `requesters.delete`, 302 на список; `requester_has_tickets` — 200 с `[role=alert]` | test_sd_requesters::test_delete_requester_*, e2e/test_d10_requesters::test_d10_requesters_page_search_filter_edit_journal_and_delete_with_tickets_refused |
| `/servicedesk/requesters/import/` | GET; POST multipart `file` | GET — страница загрузки с описанием формата `[data-format-help]` и текстом о хранимых данных (14.2), ссылками на образцы; POST — `requester_import.make_preview`; успех — 302 на `/servicedesk/requesters/import/<id>/`; отказ файла (`too_big`, `bad_format`, `not_utf8`, `too_many_rows`, `zip_bomb`, `xml_bomb`, `missing_columns`) — 200 с `[role=alert]`, ничего не записано | test_sd_requester_import (все), test_sd_requester_import_2::test_file_not_stored_after_parse, e2e/test_d10_requesters |
| `/servicedesk/requesters/import/<id>/` | GET; POST `delete_missing` (флажок); поля `confirm` нет: подтверждением служит отправка формы кнопкой «Подтвердить» на странице предпросмотра (как у загрузки сотрудников среза 002; решение Opus RD1-2) | GET в состоянии `preview` — предпросмотр, в состоянии `done` — итог; POST — `requester_import.confirm(delete_missing=…)`, успех — 302 на тот же адрес; повторный POST по выполненной загрузке — тот же 302, ничего не пишется; стёртый (`purge_requester_previews`) и несуществующий предпросмотр — 404 | test_sd_requester_import_2::test_confirm_*, test_repeat_confirmation_shows_previous_total_writes_nothing, e2e/test_d10_requesters |
| `/servicedesk/requesters/import/sample.csv`, `…/sample.xlsx` | GET | 200; `Content-Type` `text/csv; charset=utf-8` и `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`; `Content-Disposition: attachment`; тело — `requester_import.sample_csv()` и `sample_xlsx()`; путь не пересекается с `<id>` (маршруты `sample.*` стоят раньше `<id>`) | test_sd_requester_import_2::test_sample_csv_and_xlsx_headers_and_two_fictional_rows |
| `/servicedesk/inbound/` | GET `outcome` (значение `InboundMail.Outcome` или пусто), `date_from`, `date_to` (`ДД.ММ.ГГГГ`), `page`, `count` (`1` — показать общее число, решение Opus D6) | 200: сверху состояние ящика (`mailbox.status`), список по убыванию времени получения; 50 строк на странице, число — только при `count=1` (`[data-total]`) | test_sd_mailbox (через страницу), test_sd_retention_2::test_inbound_list_shows_dash_for_erased_sender_and_subject, test_sd_intake::test_inbox_outcomes_for_each_result_and_source_mail_linked_to_entry_and_ticket, e2e/test_d11_inbound::test_d11_inbound_list_filters_by_outcome_and_period_columns_and_no_right_refused |
| `/servicedesk/inbound/<id>/retry/` | POST (без полей) | `mailbox.reparse`; письмо в `error` — 302 на `/servicedesk/inbound/` и `[role=status]` «Разбор поставлен в очередь»; иное состояние (`False`) — 302 и `[role=status]` «Письмо не ждёт повторного разбора» (14.2, решение Opus D6); нет письма — 404 (после права); без права — 403 | test_sd_mailbox::test_reparse_button_requeues_error_mail_for_manage_holder_only_403_for_others_and_ignores_processed_mail |

### 12.7. Точки ядра, которые видны на страницах

| Что | Требование | Тесты |
|---|---|---|
| Меню | `/` и любая страница с меню: пункт «Заявки» (`a.menu-item[href="/tickets/"]`) виден по `access.menu_visible`, «Сервис-деск» (`a.menu-item[href="/servicedesk/"]`) — по праву `servicedesk.manage`; «Заявки» — первым, «Сервис-деск» между «Настройками портала» и «Безопасностью и политикой»; разметка счётчика — 13.5 | test_sd_list_2, test_sd_boundaries, test_sd_pages |
| Главная | напоминание `servicedesk.settings.is_configured()` ложно и право `servicedesk.manage` — `[data-notice="servicedesk-setup"]` внутри `[data-home-notices]` (точка `home_notices`; текст — 14.2); у остальных нет | test_sd_queues::test_home_notice_for_manage_holder_until_configured, e2e/test_d09_settings |
| Карточка сотрудника | `/staff/<id>/` и `/me/`: раздел `[data-section="tickets"]` на вкладке «Профиль», если `listing.card_link` не `None` (13.5) | test_sd_list_2::test_employee_card_* |
| Страница входа | `/login/` — ссылка из точки `login_links` (12.1) | test_sd_form |

## 13. Зацепки разметки

Тесты ищут элементы по атрибутам `data-*` и `role`, не по классам и не по тексту, кроме
случаев, где подпись названа дословно (14). В разметке нет встроенных скриптов и обработчиков
(CSP); поведение — внешние файлы (`static/js/htmx-glue.js`, новый `static/js/tickets.js`).
Время в ленте и списке — по Москве, формат `ДД.ММ.ГГГГ ЧЧ:ММ`, в атрибуте `data-at` —
`date:'c'`. Идентификаторы контейнеров: `#tickets-grid` (сетка), `#tickets-filter` (форма
фильтра), `#tickets-bulk` (форма групповых действий), `#slider-root`, `#dialog-root`.
Тест ищет поле только внутри `form[data-form=…]` или контейнера (`#tickets-filter`,
`#tickets-bulk`, `[data-ticket-card]`). НХ-POST из диалога в
`#dialog-root` целится в `[data-ticket-card]` (селектор документа, не `closest`: диалог
лежит вне карточки; на странице одна карточка; `hx-swap="outerHTML"`; ответ — карточка), а
`#dialog-root` после успеха очищается. Формы действий самой карточки (13.3) в обеих
раскладках целятся в
`closest [data-ticket-card]` с `hx-swap="outerHTML"`: на странице `/tickets/<номер>/`
`#slider-root` может не быть.

Общие проверки страниц среза (T-3133; имена подписаны в `tasks.md`, не меняются):
- перечень страниц — маршруты GET из таблиц 12.1-12.6, без выдачи файлов;
- `test_slice_pages_use_narrow_width_classes` (в имени «классы», но классов контракт не называет)
  проверяет `[data-narrow="cards"]` у `#tickets-grid`, `details[data-filter-panel]` на списке и
  `<meta name="viewport">` на всех страницах перечня;
- `test_every_slice_page_is_russian` — признак `<html lang="ru">` и отсутствие латинских слов
  в `<title>`, `h1`, подписях `button`;
- `test_slice_pages_show_time_in_moscow` — каждый `time[data-at]` в формате `ДД.ММ.ГГГГ ЧЧ:ММ`
  по Москве;
- `test_slice_pages_have_viewport_meta_for_360px` — `<meta name="viewport">` на каждой странице.

### 13.1. Зацепки срезов 001-002, которые использует срез 003

Список существующих `data-*` — в заметках части d (`d/data-attrs.txt`, 115 имён). Новых имён
для того же смысла не заводится.

| Зацепка | Где в срезе 003 | Тесты |
|---|---|---|
| `[role=alert]`, `[role=status]` | отказы и подтверждения всех форм среза (12); у каждого `[role=alert]` отказа сервиса и у `[data-error]` — атрибут `data-code="<код из 6.2>"`; тесты Playwright сверяют `data-code`, а не текст, кроме строк, где в 14.1 написано «слово» или «подстроку» | все `test_sd_*`, e2e |
| `[data-action="<имя>"]` | кнопки и ссылки действий (названия — в таблицах ниже); у действий без права элемента нет в ответе | test_sd_list_2, test_sd_card, test_sd_executor, e2e |
| `form[data-form="<имя>"]` | формы среза (названия — ниже); у каждой `button[type=submit]` | test_sd_form, test_sd_card, e2e |
| `[data-dialog="<имя>"][role="dialog"][aria-modal="true"]`, `button[data-dialog-cancel]`, `[data-consequence]` | диалоги в `#dialog-root`: `ticket-transfer`, `ticket-close`, `ticket-category`, `participant-remove`, `queue-unmark`, `dictionary-delete`, `requester-delete`; «Отмена» запросов не шлёт; внутри `[data-dialog]` ровно одна `form` (без `data-form`; действие — адрес из 12) с одной `button[type=submit]` подтверждения и скрытыми полями из 12 | test_sd_assignment, test_sd_closing, e2e |
| `[data-field="<имя>"]`, `[data-field-label="<имя>"]`, `[data-empty="true\|false"]` | поля карточки заявки (13.3) и страницы настроек; пустое — текст «не заполнено» (у ответственного «не назначен») | test_sd_card |
| `[data-empty-state="<имя>"]` | пустые состояния среза: значения `tickets`, `requesters`, `inbound`, `dictionary`; непустое пояснение | test_sd_list_2, test_sd_requesters |
| `[data-cell="<имя>"]` | ячейки строк списков: заявок, заявителей, значений справочников, входящих писем | test_sd_list_2, test_sd_requesters |
| `a[data-preset="<код>"]` | пресеты списка заявок: значение равно параметру `preset` (12.2); активный — `aria-current="true"`; тесты ищут их только как `nav[data-presets] a[data-preset=…]` (пустое состояние — `[data-empty-state="tickets"]`, 13.2) | test_sd_list, e2e/test_d14_find |
| `[data-candidates]`, `[data-candidate][data-user-id]` | подсказки ответственного (12.4): `label` с `input[type=radio][name=assignee]` | test_sd_assignment, e2e/test_d04_dispatch |
| `[data-section="<имя>"]` | разделы карточки заявки (`participants`, `attachments`) и карточки сотрудника (`tickets`) | test_sd_card, test_sd_list_2 |
| `[data-notice="<ключ>"]` внутри `[data-home-notices]` | напоминание на главной (13.5) | test_sd_queues |
| `[data-dismissed="true"]`, `[data-dismissed-badge]` | имя уволенного: рядом текст «(уволен)» (14.3) | test_sd_card, test_sd_reconcile, e2e/test_d15_staff_change |
| `[data-mail-status="queued\|sent\|failed"]` | состояние письма ответа в ленте; значения `MailMessage.status` (подписи «в очереди», «отправлено», «не доставлено») | test_sd_card::test_card_shows_mail_state_from_mail_message |
| `[data-at]` | время элемента (`<time data-at="…">`) | test_sd_card::test_feed_item_has_moscow_time_and_author |
| `[data-kind]` | один атрибут на трёх элементах: `tr[data-ticket]` (вид статуса), корень карточки и `li[data-entry]` ленты; тесты ищут `tr[data-ticket=N][data-kind=…]`, `[data-ticket-card][data-kind=…]`, `ol[data-feed] li[data-kind=…]`, никогда `[data-kind=…]` без тега | test_sd_list, test_sd_card, e2e |
| `[data-slider-close]`, `.slider-panel` | карточка в слайдере (как карточка сотрудника) | test_sd_card::test_card_htmx_request_returns_slider_fragment |
| `[data-unit-tree]`, `li[data-unit-id]` | дерево на странице очередей (13.7) | test_sd_queues, e2e/test_d09_settings |
| `[data-import-preview]`, `tr[data-import-row][data-row-number][data-row-result]`, `[data-row-reason]` (только причина, как в `org`: «ошибка: <причина>», при непустой причине), `[data-import-new-units] li`, `[data-import-not-loaded] li`, `form[data-form="import-upload"]`, `form[data-form="import-confirm"]`, `[data-result-summary]`, `[data-format-help]`, `a[data-sample]` | загрузка заявителей (13.8); атрибут `data-row-result` общий по смыслу («итог строки»), значения у заявителей свои (в `org` `will_create`): `will_add`, `will_update`, `unchanged`, `error` (после выполнения `added`, `updated`, `unchanged`, `error`) | test_sd_requester_import_2, e2e/test_d10_requesters |
| `[data-datefield]` | поля периода (`created_from`, `created_to`, `date_from`, `date_to`) — поле даты портала | test_sd_list::test_filter_by_created_period_portal_date_field |

### 13.2. Список заявок (`/tickets/`)

| Зацепка | Что | Тесты |
|---|---|---|
| `[data-tickets-list]` | корень страницы; внутри (по порядку в разметке) `nav[data-presets]`, `details[data-filter-panel]` с `form#tickets-filter[data-form="tickets-filter"]`, `form#tickets-bulk[data-form="tickets-bulk"]` (над сеткой и вне `#tickets-grid`, чтобы подмена сетки её не затрагивала), `#tickets-grid` | test_sd_list::test_htmx_grid_target_returns_grid_only_panel_and_presets_stay, test_sd_list_2::test_bulk_actions_and_row_checkboxes_markup_above_grid |
| пресеты | `nav[data-presets] a[data-preset="mine\|unassigned\|my_queues\|waiting\|closed\|all"]`, подписи — 14.2 (по плану); ссылка ведёт на `/tickets/?preset=<код>`, цель НХ — `#tickets-grid` с заголовком `HX-Target: tickets-grid`; выбранный пресет — `aria-current="true"`; тесты ищут пресеты только как `nav[data-presets] a[data-preset=…]`, пустое состояние — как `[data-empty-state="tickets"]` | test_sd_list::test_default_preset_*, e2e/test_d14_find::test_d14_preset_switch_updates_only_grid_filter_panel_stays |
| фильтр | `form#tickets-filter` method GET: `select[name=queue]`, `select[name=category]`, `select[name=priority]`, `select[name=status]`, `select[name=kind]`, `select[name=assignee]` (первый `option value=""`; `option value="none"` — «без ответственного»), `select[name=client_unit]`, `select[name=source]`, два поля даты `created_from`, `created_to` (`[data-datefield]`), `input[name=q]`, скрытые `preset`, `sort`, `dir`; значения заданного фильтра выбраны; архивные значения справочников в выборе показаны с меткой «в архиве»; форма, ссылки пресетов, заголовки сортируемых столбцов и ссылки страниц несут `hx-get`, `hx-target="#tickets-grid"`, `hx-push-url="true"` (12.2) | test_sd_list::test_filter_*, test_archived_value_shown_in_list_filter_with_archive_mark, test_filter_params_in_url_for_back_and_push_url |
| подсказка поиска | `[data-hint="short"]` с текстом из 14.2, только когда `Page.hint == "short"` | test_sd_search::test_search_words_shorter_than_two_chars_skipped_with_hint |
| сетка | `#tickets-grid[data-tickets-grid][data-narrow="cards"]` (до 576 px строки показываются карточками: CSS; атрибут — признак разметки), внутри `table` с `thead th[data-sort="number\|created\|last_message\|priority"]` у сортируемых столбцов (в `th` ссылка `a[href]` с `sort` и `dir`; текущая сортировка — `aria-sort="ascending\|descending"`); `data-sort` — значение параметра `sort` (с подчёркиванием), `data-cell` — с дефисом | test_sd_list::test_sort_*, test_sd_list_2::test_narrow_width_markup_cards_with_subject_status_assignee, test_narrow_width_filter_panel_in_details_no_horizontal_scroll_markup |
| строка | `tr[data-ticket="<номер>"][data-kind="new\|in_progress\|waiting\|closed"]`; ячейки `[data-cell="select\|number\|subject\|requester\|client-unit\|category\|queue\|priority\|status\|assignee\|created\|last-message"]` ровно в таком порядке (кроме `select` — 11 колонок по FR-277, плюс столбец выбора); `[data-cell="number"] a[href="/tickets/<номер>/"]` с `hx-get` на тот же адрес, `hx-target="#slider-root"`; другие столбцы (например, «ящик», «обезличена») не заводятся | test_sd_list_2::test_grid_has_all_columns_in_order, e2e/test_d14_find::test_d14_grid_columns_are_exactly_the_specified_set |
| значения ячеек | `requester` — ФИО, а при пустом — адрес; `assignee` — имя (у уволенного рядом `[data-dismissed-badge]`), у закрытой без ответственного «Закрыл: Имя Фамилия» (`closed_by`); не назначен — «не назначен»; `last-message` — `time[data-at]` и `[data-last-from="requester\|staff"]` с подписью «заявитель» или «исполнитель»; пустое (писем ещё нет) — «—» | test_sd_list_2::test_last_message_*, test_closed_without_assignee_shows_closed_by_name, test_requester_column_name_or_address_fallback |
| выбор и групповая панель | `[data-cell="select"] input[type=checkbox][name=numbers][value="<номер>"][form="tickets-bulk"]`; в `form#tickets-bulk`: `select[name=action]` (`assign` «Назначить ответственного», `transfer` «Передать в очередь», `priority` «Сменить критичность»), группы параметров `[data-bulk-action="assign"] select[name=user]`, `[data-bulk-action="transfer"] select[name=queue]` и `textarea[name=reason]`, `[data-bulk-action="priority"] select[name=priority]`, `button[type=submit]`; результат — `[data-bulk-result]` с `li[data-skipped]` | test_sd_list_2::test_bulk_actions_and_row_checkboxes_markup_above_grid, test_sd_assignment_2::test_group_*, e2e/test_d04_dispatch |
| страницы и счётчик | `[data-page]` с текстом «Страница N»; `a[data-action="page-next"]` при `Page.has_next`, `a[data-action="page-prev"]` при `page > 1`; `a[data-action="show-count"]` «показать количество» с `hx-get` на `/tickets/count/` и теми же параметрами; после нажатия — `[data-total]` с числом; числа до нажатия нет | test_sd_list::test_page_has_50_rows_and_next_page_by_51st_row, test_total_count_only_on_show_count_button |
| пустое состояние | `[data-empty-state="tickets"][data-preset="<код>"]`: пояснение по пресету (14.2) и, если `executor.can_start`, кнопка «Новая заявка» — `[data-empty-state="tickets"] a[data-action="ticket-new"]`; без права кнопки нет; кнопку шапки страницы тесты ищут как `[data-tickets-list] > header a[data-action="ticket-new"]` | test_sd_list_2::test_empty_preset_has_explanation_and_action_button, test_empty_list_new_ticket_button_only_for_creator_right, test_empty_queue_explains_what_will_be_here, e2e/test_d14_find::test_d14_empty_preset_shows_explanation |
| кнопка «Новая заявка» | `a[data-action="ticket-new"][href="/tickets/new/"]` в шапке страницы, только если `executor.can_start(user)`; у не участника кнопки нет, а прямой адрес даёт 403 | test_sd_executor::test_new_button_*, e2e/test_d07_phone |
| узкая ширина | в `<head>` `<meta name="viewport">`; страница без горизонтальной прокрутки на 360 px (проверка — Playwright, `no_horizontal_scroll`) | test_sd_pages::test_slice_pages_have_viewport_meta_for_360px, e2e/test_d14_find::test_d14_list_at_360px_no_horizontal_scroll, e2e/test_d_cross_cutting |

### 13.3. Карточка заявки (`/tickets/<номер>/`)

| Зацепка | Что | Тесты |
|---|---|---|
| корень | `[data-ticket-card][data-number="<номер>"][data-kind="<вид статуса>"][data-layout="slider\|page"]`; в слайдере — внутри `.slider-panel` с `[data-slider-close]`, на странице — в основном содержимом | test_sd_card::test_card_htmx_request_returns_slider_fragment, test_card_direct_address_returns_full_page |
| две колонки | внутри корня сначала `[data-card-fields]` (поля и действия), затем `[data-card-feed]` (лента); порядок в разметке обязателен: до 600 px лента идёт под полями без дополнительной вёрстки; на широком окне колонки рядом (CSS) | test_sd_card::test_card_has_fields_column_and_feed_column, test_card_markup_for_narrow_width_puts_feed_under_fields |
| поля | `[data-field="number\|subject\|status\|queue\|category\|priority\|complexity\|client-unit\|source\|requester\|requester-name\|requester-email\|assignee\|created\|closed-by\|resolution\|consent\|previous\|continuation"]` с `[data-field-label]`; `closed-by` и `resolution` только у закрытой; пустые — `data-empty="true"`; автор создания заявки от исполнителя — `[data-author]` первого элемента `incoming` ленты (13.4), отдельного `[data-field]` для него нет | test_sd_card, test_sd_reconcile::test_closed_by_name_kept_in_card_and_list_after_assignee_removed, test_source_and_created_by_in_card_and_audit (T-3122) |
| согласие | `[data-field="consent"]`: текст «согласие на обработку ПДн» и дата `ДД.ММ.ГГГГ ЧЧ:ММ`; только у заявки с формы (`consent_at`); у остальных элемента нет | test_sd_card::test_form_ticket_card_shows_consent_mark_with_date_and_time, e2e/test_d02_form::test_d02_ticket_card_shows_pd_consent_with_date |
| связи заявок | `a[data-field="previous"][href="/tickets/<номер>/"]` — «продолжение заявки #N» у новой заявки (spec.md:688, 703); `a[data-field="continuation"]` — «продолжение — заявка #N» у закрытой, если есть продолжение (ссылки только на видимые заявки, иначе текст без ссылки) | test_sd_closing_2::test_letter_after_term_creates_new_ticket_with_previous_and_confirmation, e2e/test_d05_close::test_d05_requester_reply_after_ten_days_creates_continuation_ticket_old_stays_closed |
| участники | `[data-section="participants"]` с `[data-participant][data-participant-id="<id>"]` (адрес, имя, `data-removed="true"` у снятого); `a[data-action="participant-remove"]` с `hx-get` на диалог — только у неснятых, у открытой заявки, у видящего заявку | test_sd_assignment_2::test_remove_participant_*, e2e/test_d03_reply |
| цель форм действий | `hx-target="closest [data-ticket-card]"` и `hx-swap="outerHTML"` у форм действий карточки (взять себе, назначить, ответить, комментарий и прочие) в обеих раскладках, `slider` и `page`; одна разметка, не зависит от наличия `#slider-root` (решение Opus F3-4) | test_sd_card, e2e/test_d03_card |
| вложения заявки | `[data-section="attachments"]` (все файлы заявки); элемент `[data-attachment][data-state="clean\|pending\|quarantine"]`: у `clean` — `a[href="/tickets/<номер>/files/<uuid>/"]` с именем; у `pending` — текст «проверяется»; у `quarantine` — «в карантине» без ссылки | test_sd_attachments::test_scan_clean_moves_file_to_attachments_and_makes_it_downloadable, test_pending_and_quarantined_not_downloadable_requeue_picks_pending |
| не принятые вложения | `[data-rejected-attachments]` (в карточке и в блоке элемента) и `li[data-rejected="too_big\|mail_too_big\|executable\|encrypted"]` с текстом «<имя> — <подпись причины>» (`Attachment.REJECT_TITLES`, 2.2); блок есть, только если такие вложения есть | test_sd_attachments::test_rejected_attachment_keeps_only_name_size_reason_and_is_listed_in_card_and_confirmation, e2e/test_d12_attachments |
| исходное письмо | `a[data-action="source-mail"][href="/tickets/<номер>/mail/<id>.eml"]` у элемента `incoming` из письма — только если `attachments.source_mail` его бы выдал (FR-212: все вложения чистые и ни одно не отклонено) | test_sd_attachments::test_source_eml_issued_only_when_all_attachments_clean_and_none_rejected, e2e/test_d01_mail |

Тест Playwright ищет вложения заявки только внутри `[data-section="attachments"]`, а вложения
элемента — внутри `li[data-entry-id="<id>"] ul[data-attachments]`; общий поиск
`[data-attachment]`, `[data-rejected-attachments]` по всей карточке недопустим (совпадений
будет два).

Кнопки и формы карточки (элемент — только когда условие истинно; без права или в другом
состоянии его нет в ответе, а прямой запрос всё равно получит отказ сервиса):

| Элемент | Условие появления | Тесты |
|---|---|---|
| `form[data-form="ticket-take"]` с `button[type=submit][data-action="ticket-take"]` (POST на `…/take/`, «Взять себе») | заявка открыта, я участник очереди (`access.is_participant`), ответственный не я | test_sd_assignment::test_take_*, e2e/test_d03_reply |
| `form[data-form="ticket-assign"]` с `input[name=q]` (`hx-get` на `…/assignees/`, цель `[data-candidates]`) и `button[type=submit]`; `form[data-form="ticket-unassign"]` с `input[type=hidden][name=assignee][value=""]` и `button[type=submit][data-action="ticket-unassign"]` («Снять ответственного», POST `…/assign/`; отдельная форма: вложенных форм нет, а `ticket-assign` занята полем `q`) | заявка открыта; «снять» — только при ответственном | test_sd_assignment, e2e/test_d04_dispatch |
| `a[data-action="ticket-transfer"]` (`hx-get` на диалог, цель `#dialog-root`) | заявка открыта | test_sd_assignment, e2e/test_d04_dispatch |
| `form[data-form="ticket-category"]` с `select[name=category]` | заявка открыта; в выборе только неархивные (текущая архивная показана, но не выбираема) | test_sd_assignment::test_category_change_* |
| `form[data-form="ticket-fields"]` с `select[name=priority]`, `select[name=complexity]`, `select[name=client_unit]`, `input[name=requester_name]`, `button[name=save_to_record][value="1"]` («Сохранить и в записи заявителя»), обычная кнопка отправки | заявка открыта; в выборе — `dictionaries.offered` | test_sd_assignment_2::test_requester_name_save_also_in_record_button, test_archived_criticality_and_complexity_not_offered |
| `form[data-form="ticket-status"]` с `select[name=status]` (`manual_statuses`) | заявка открыта | test_sd_status::test_manual_status_list_has_only_in_work_and_waiting_kinds_not_archived |
| `form[data-form="ticket-reply"]` (`multipart`): `textarea[name=text]`, `input[type=file][name=files][multiple]`, `input[type=checkbox][name=wait]` с подписью «Ждём ответа заявителя», `button[type=submit]` | заявка открыта | test_sd_reply, e2e/test_d03_reply |
| `form[data-form="ticket-comment"]`: `textarea[name=text]`, `button[type=submit]` | всегда (и на закрытой), если видна заявка | test_sd_card::test_internal_comment_marked_internal_in_feed, test_sd_closing::test_internal_comment_on_closed_ticket_allowed_and_changes_nothing_else |
| `a[data-action="ticket-close"]` (`hx-get` на диалог) | заявка открыта | test_sd_closing, e2e/test_d05_close |
| `form[data-form="ticket-reopen"]` с `button[type=submit][data-action="ticket-reopen"]` (POST на `…/reopen/`, «Открыть заново») | заявка закрыта; видна мне | test_sd_closing_2::test_manual_reopen_*, e2e/test_d05_close |
| `form[data-form="reply-resend"]` с `button[data-action="reply-resend"]` («Отправить заново без заражённых вложений») | у элемента `reply` с `data-send-state="not_sent"` и открытой заявки; у остальных элементов нет | test_sd_reply::test_resend_button_only_on_not_sent_reply, e2e/test_d12_attachments |
| закрытая заявка | форм ответа, назначения, передачи, полей, статуса, категории нет; остаются `ticket-reopen` и `ticket-comment`; атрибут `data-kind="closed"` у корня карточки | test_sd_assignment_2::test_closed_ticket_*, test_sd_card::test_closed_ticket_card_shows_who_closed |
| заявка вне видимости | ни карточки, ни действий: 404 (12.4) | test_sd_pages::test_inaccessible_ticket_card_returns_404_same_as_missing |

### 13.4. Лента

| Зацепка | Что | Тесты |
|---|---|---|
| `ol[data-feed]` | список элементов по `(at, id)`; `li[data-entry][data-entry-id="<id>"][data-kind="incoming\|reply\|comment\|event"]` (значения `TicketEntry.Kind`) | test_sd_card::test_feed_ordered_by_time_with_authors_and_attachments_in_one_query, test_feed_shows_letters_replies_comments_and_events_together, e2e/test_d03_reply::test_d03_feed_shows_all_item_kinds_in_time_order_with_author_and_comment_mark |
| время и автор | `time[data-at]` (по Москве); `[data-author][data-author-kind="staff\|requester\|participant\|system"]`: имя сотрудника, у уволенного `data-dismissed="true"` и текст «<имя> (уволен)»; «заявитель <адрес>», «участник <адрес>» (14.3); у системы текста автора нет, а в строке события нет `[data-author]` | test_sd_card::test_feed_authors_staff_name_dismissed_mark_requester_and_participant_address, test_feed_item_has_moscow_time_and_author |
| текст | `[data-entry-text]` (у `incoming`, `reply`, `comment`): текст экранирован, переводы строк — `<br>`, HTML письма и формы не исполняется (в ответе нет `<script`, `<b>` и тегов из текста письма) | test_sd_card::test_html_*, test_line_breaks_rendered_over_escaping, test_sd_pages::test_mail_html_in_ticket_card_is_escaped_not_rendered |
| комментарий | `li[data-kind="comment"]` с `[data-internal]` и текстом «внутренний» | test_sd_card::test_internal_comment_marked_internal_in_feed, e2e/test_d03_reply |
| ответ | `li[data-kind="reply"]` с `[data-reply-label]` («ответ исполнителя») и `[data-send-state="waiting_files\|queued\|not_sent"]` с подписью состояния (14.2); у отправленного — `[data-mail-status]` из `MailMessage` («в очереди», «отправлено», «не доставлено»); у недоставленного ещё `[data-undelivered]` | test_sd_card::test_card_shows_mail_state_from_mail_message, test_sd_reply::test_failure_after_last_retry_writes_not_delivered_event_in_feed |
| событие | `li[data-kind="event"][data-event="<код>"]` одной строкой текста по 14.5; ключ `data` в разметке не выводится | test_sd_card::test_ticket_field_events_in_russian_for_each_kind, test_delivery_attachment_and_closing_events_in_russian |
| вложения элемента | `ul[data-attachments]` внутри `li`: те же `[data-attachment]` и `[data-rejected-attachments]` (13.3), у `reply` — ссылки на чистые файлы | test_sd_card::test_feed_ordered_by_time_with_authors_and_attachments_in_one_query |
| у элементов нет правки | в разметке элементов нет форм и ссылок правки и удаления | test_sd_card::test_no_routes_to_edit_or_delete_feed_items, e2e/test_d03_reply::test_d03_feed_messages_have_no_edit_or_delete |

### 13.5. Меню, главная, вход и карточка сотрудника

| Зацепка | Что | Тесты |
|---|---|---|
| пункт «Заявки» | `#main-menu a.menu-item[href="/tickets/"]` с подписью «Заявки», есть у видящего (`access.menu_visible`), у остальных нет | test_sd_access::test_menu_item_tickets_visible_to_participant_all_holder_or_assignee_only, test_sd_boundaries::test_menu_item_visible_shows_item_without_permissions |
| счётчик | внутри `a.menu-item` элемент `span[data-menu-badge]` с числом — только если `badge` вернул число больше нуля; при `0` и при `None` элемента нет (решение Opus, decisions-d.md, B2-9; спека молчит; отдельным тестом не закрыто); без `servicedesk` ключа `badge` в `menu_for` нет и разметка меню прежняя | test_sd_list_2::test_badge_*, e2e/test_d14_find::test_d14_menu_counter_shows_six_for_four_unassigned_plus_two_requester_last |
| пункт «Сервис-деск» | `#main-menu a.menu-item[href="/servicedesk/"]`, есть у `servicedesk.manage` | test_sd_boundaries, test_sd_pages |
| ссылка на странице входа | `a[data-login-link][href="/request/"]` с текстом «Подать заявку в ИТ-отдел» (контекст `login_links`, цикл в `templates/auth/login.html`); без регистраций ссылок нет, страница прежняя | test_sd_form::test_login_page_has_request_link_from_login_links, test_sd_boundaries |
| напоминание на главной | `[data-home-notices] [data-notice="servicedesk-setup"][role="status"]` с текстом из 14.2 и ссылкой `a[href="/servicedesk/"]`; только у `servicedesk.manage`, пока сервис-деск не настроен | test_sd_queues::test_home_notice_for_manage_holder_until_configured |
| раздел «Заявки» в карточке сотрудника | `/staff/<id>/` и `/me/`, вкладка «Профиль»: `[data-section="tickets"]` с `a[data-action="employee-tickets"][href="/tickets/?preset=all&assignee=<id>"]` и текстом «Заявки»; если `listing.card_link` вернул `None` — раздела нет; в панели «Безопасность» не выводится | test_sd_list_2::test_employee_card_tickets_link_filters_by_assignee, test_employee_card_link_hidden_without_menu_item, e2e/test_d14_find |

### 13.6. Открытая форма и заявка от исполнителя

| Зацепка | Что | Тесты |
|---|---|---|
| страница `/request/` | базовый шаблон входа без левого меню (нет `#main-menu`); `<meta name="viewport">`; `<html lang="ru">`; заголовок страницы с названием портала | test_sd_form, test_sd_pages::test_open_form_has_viewport_and_narrow_markup |
| форма | `form[data-form="request"][method="post"][enctype="multipart/form-data"]` с `input[name=csrfmiddlewaretoken]`; поля: `input[name=email]`, `input[name=name]`, `select[name=client_unit]` (первый `option value=""` «Нет в списке», затем неархивные по названию), `select[name=category]` (только `on_form`, по `order`, «Другое» среди них), `input[name=subject]`, `textarea[name=text]`, `input[type=file][name=files][multiple]`, `input[type=checkbox][name=consent]` с `[data-consent-text]` (текст о данных и целях, 14.2), `button[type=submit]`; поля критичности и источника нет; капчи нет; атрибуты `required` у обязательных | test_sd_form::test_form_has_required_fields_and_consent_checkbox, test_department_list_unarchived_plus_not_in_list, test_category_list_shown_on_form_only_in_order_with_other, test_form_has_no_criticality_choice_and_ticket_gets_default |
| ошибки полей | у неверного поля `[data-error="email\|name\|client_unit\|category\|subject\|text\|consent"]` с текстом из 14.1 (роли `alert` у него нет); общий отказ без поля (порог, вложения, закрытый приём) — `[role=alert]`; у отказа поля общего `[role=alert]` нет | test_sd_form::test_invalid_address_and_foreign_domain_refused, test_required_fields_and_length_limits_refused, test_missing_consent_refused, e2e/test_d02_form::test_d02_foreign_domain_or_no_consent_refused_with_message_no_ticket |
| закрытое состояние | `[data-closed-notice="request"]` с текстом «Приём заявок через форму сейчас закрыт. Напишите письмо на <адрес ящика>»; формы на странице нет | test_sd_form::test_closed_page_without_domains_or_default_queue_names_mailbox, test_post_when_closed_rejected_with_same_text |
| порог | отказ по порогу — `[role=alert]` с текстом «С вашего адреса отправлено слишком много заявок за час. Напишите письмо на <адрес ящика>» | test_sd_form::test_rate_limit_refuses_over_threshold_with_mailbox_address, e2e/test_d02_form::test_d02_threshold_per_hour_refused_with_mailbox_address_no_ticket |
| «заявка принята» | `/request/done/`: `[data-request-done]` с текстом «Заявка принята. Подтверждение с номером придёт на <адрес>» и `[data-done-email]` (адрес); номера заявки в ответе нет | test_sd_form::test_done_page_shows_address_without_number_taken_from_session_and_removed |
| форма исполнителя | `form[data-form="ticket-new"]` (multipart): `input[name=email]` (`hx-post` на `/tickets/new/requester/`, цель `[data-requester-fields]`, срабатывание `change`), `[data-requester-fields]` с `input[name=name]` и `select[name=client_unit]`, `select[name=category]` (`hx-get` на `/tickets/new/queue/`, цель `[data-queue-fields]`), `[data-queue-fields]` с `select[name=queue]` (`hx-get` на тот же адрес, `hx-include` категории) и `input[type=checkbox][name=take]` «Взять себе» (включён по умолчанию, `disabled` для не участника очереди), `select[name=priority]`, `select[name=source]`, `input[name=subject]`, `textarea[name=text]`, `input[type=file][name=files][multiple]`, `button[type=submit]` | test_sd_executor (все), e2e/test_d07_phone |
| согласие в подтверждении | строка о согласии — в письме (раздел 10), в форме исполнителя отдельного флажка нет | test_sd_executor::test_confirmation_has_consent_line_and_no_off_hours_phrase |

### 13.7. Настройки, очереди, справочники

| Зацепка | Что | Тесты |
|---|---|---|
| меню раздела | `nav[data-servicedesk-nav]` с `a[data-servicedesk-link="settings\|queues\|dictionaries\|requesters\|inbound"]` (ведут на `/servicedesk/`, `/servicedesk/queues/`, `/servicedesk/dictionaries/categories/`, `/servicedesk/requesters/`, `/servicedesk/inbound/`); активный — `aria-current="true"` | test_sd_pages, e2e/test_d09_settings |
| настройки | `form[data-form="servicedesk-settings"]`: `textarea[name=domains]`, `select[name=default_priority]`, `input[name=autoclose_days]`, `input[name=reopen_days]`, `input[name=form_hourly_limit]`, `input[name=retention_years]`, `input[name=inbound_retention_days]`; только для чтения: `[data-field="mailbox-address"]` (адрес ящика), `[data-field="last-ok-at"]`, `[data-field="last-error"]`, `[data-field="default-queue"]` (название очереди по умолчанию или «не задана»), без `input` и без секретов | test_sd_queues::test_mailbox_address_readonly_in_settings, test_initial_terms_and_limits_defaults_7_7_10_3_30_and_ranges_validated, e2e/test_d09_settings::test_d09_fresh_install_no_queues_no_domains_mailbox_readonly_other_category_and_intake_closed |
| предупреждение `none` | `[data-warning="imap-security"]` с текстом из 14.2, только если `settings.IMAP_SECURITY == "none"`; при `ssl` и `starttls` элемента нет | test_sd_queues (страница настроек), e2e/test_d09_settings |
| очереди | `ul[data-unit-tree]` — все узлы; `li[data-unit-id][data-queue="true\|false"][data-default="true\|false"]`; у узла: `form[data-form="queue-mark"]` («Отметить очередью») у неотмеченного, `a[data-action="queue-unmark"]` (`hx-get` на диалог `?unmark=<id>`) у отмеченного, `form[data-form="queue-default"]` («Очередью по умолчанию») у отмеченного не по умолчанию; в каждой форме скрытые `action` и `unit` (12.6); у очереди по умолчанию `[data-default-mark]` с текстом «по умолчанию» | test_sd_queues, e2e/test_d09_settings |
| справочник | `table[data-dictionary="category\|priority\|complexity\|status\|source\|client_unit"]`; строка `tr[data-dictionary-row][data-id="<id>"][data-archived="true\|false"]`, ячейки `[data-cell="name\|order\|queue\|default-assignee\|on-form\|kind\|default\|system"]` (по виду: у категорий `queue`, `default-assignee`, `on-form`; у статусов `kind`, `default`, `system`; у `client_unit` нет `order`); метка архива — `[data-archived-mark]` с текстом «в архиве»; системное — `[data-system-mark]` с текстом «системное» | test_sd_dictionaries::test_archived_value_shown_in_list_filter_with_archive_mark, test_client_units_unique_without_case_archived_not_offered_flat_list, e2e/test_d09_settings |
| действия справочника | `a[data-action="dictionary-new"]` (`/servicedesk/dictionaries/<вид>/new/`), в строке: `a[data-action="dictionary-edit"]`, `form[data-form="dictionary-archive"]` (у неархивных; `button[data-action="dictionary-archive"]`), `form[data-form="dictionary-restore"]` (у архивных), `a[data-action="dictionary-delete"]` (`hx-get` на диалог); форма значения `form[data-form="dictionary"]` с полями 12.6 | test_sd_dictionaries, e2e/test_d09_settings, e2e/test_d10_requesters |
| статусы | у `status` в `[data-cell="kind"]` — подпись вида (2.1): «новая», «в работе», «ждёт ответа заявителя», «закрыта»; `[data-cell="default"]` — «по умолчанию» у отмеченного | test_sd_dictionaries::test_initial_statuses_with_kinds_and_default_marks, e2e/test_d09_settings::test_d09_fresh_install_status_dictionary_kinds_and_defaults |

### 13.8. Заявители, загрузка и «Входящие письма»

| Зацепка | Что | Тесты |
|---|---|---|
| список заявителей | `form[data-form="requesters-filter"]` method GET: `input[name=q]`, `select[name=client_unit]`; строка `tr[data-requester][data-id="<id>"]`, ячейки `[data-cell="email\|name\|client-unit\|origin\|tickets-count"]`; `origin` — «таблица» или «заявка» (2.2); действия `a[data-action="requester-edit"]`, `a[data-action="requester-delete"]`; `[data-empty-state="requesters"]`; форма правки в слайдере: `form[data-form="requester"]` с `input[name=name]`, `select[name=client_unit]` (первый `option value=""`), `button[type=submit]` | test_sd_requesters::test_requesters_page_columns, e2e/test_d10_requesters |
| ссылка на загрузку | `a[data-action="requesters-import"][href="/servicedesk/requesters/import/"]` «Загрузить из таблицы» на странице заявителей | test_sd_requester_import |
| страница загрузки | `form[data-form="import-upload"]` с `input[type=file][name=file]`; `[data-format-help]` — описание формата и текст о хранимых данных (14.2); `a[data-sample="csv"]`, `a[data-sample="xlsx"]` | test_sd_requester_import::test_import_page_text_names_data_and_purpose, e2e/test_d10_requesters::test_d10_upload_page_states_what_data_is_stored_and_why |
| предпросмотр | `[data-import-preview]`; строки `tr[data-import-row][data-row-number][data-row-result]`, у строки с причиной — `[data-row-reason]` (14.2); `[data-import-new-units] li` — подразделения, которых нет в справочнике; `[data-import-not-loaded] li` — лишние колонки; `[data-would-delete]` — число, которое удалит флажок; форма `form[data-form="import-confirm"]` с `input[type=checkbox][name=delete_missing]` («Удалить заявителей без заявок, которых нет в файле») и `button[type=submit]` «Подтвердить»; скрытого поля `confirm` нет (12.6) | test_sd_requester_import (rows, new units, would_delete), e2e/test_d10_requesters |
| итог | `[data-result-summary]` с `data-added`, `data-updated`, `data-unchanged`, `data-errors`, `data-deleted`, `data-origin-changed` (числа) и текстом «добавлено N, обновлено M, без изменений K, с ошибками L» (14.2); строки — `data-row-result` `added`, `updated`, `unchanged`, `error` с `[data-row-reason]` | test_sd_requester_import_2::test_executed_row_keeps_number_total_and_reason_only, test_preview_and_total_show_deleted_and_origin_changed_counts |
| состояние ящика | `[data-mailbox-status][data-mailbox-state="connected\|not-connected"]` над списком писем: `[data-field="mailbox-address"]`, `[data-field="last-ok-at"]` (время последнего удачного опроса), `[data-field="last-error"]` (текст без секретов, пусто при отсутствии); `not-connected` и текст «ящик не подключён» вместо времени — ровно при пустом `IMAP_HOST` (единственное условие, решение Opus F4-6); состояние берётся из `mailbox.status().configured` (6.15): `not-connected` при `False`, `connected` при `True` (значение `connected` атрибута не равно полю `MailboxStatus.connected`), пустой `SERVICEDESK_MAILBOX` на него не влияет (14.1) | test_sd_mailbox (через страницу), e2e/test_d11_inbound |
| фильтр | `form[data-form="inbound-filter"]` GET: `select[name=outcome]` (первый `option value=""`; значения — `InboundMail.Outcome`), `date_from`, `date_to` (`[data-datefield]`); `a[data-action="show-count"]` с `hx-get` на `/servicedesk/inbound/` с теми же параметрами и `count=1`; после нажатия `[data-total]` | e2e/test_d11_inbound::test_d11_inbound_list_filters_by_outcome_and_period_columns_and_no_right_refused |
| строка письма | `tr[data-inbound][data-id="<id>"][data-outcome="<значение Outcome или пусто>"][data-status="<значение Status>"]`, ячейки `[data-cell="received\|sender\|subject\|outcome"]`; у письма со стёртыми данными в `sender` и `subject` текст «—» (FR-221); `outcome` — подпись из 2.2 и, если есть заявка, `a[data-ticket-link][href="/tickets/<номер>/"]` с текстом «#N» | test_sd_intake::test_inbox_outcomes_for_each_result_and_source_mail_linked_to_entry_and_ticket, test_sd_retention_2::test_inbound_list_shows_dash_for_erased_sender_and_subject |
| причина и «разобрать снова» | у письма в `error` — `[data-error-reason]` (шаг из `last_error`, формат «<шаг>: <класс>», без текста исключения) и `form[data-form="inbound-retry"][action="/servicedesk/inbound/<id>/retry/"]` с `button[data-action="inbound-retry"]` «Разобрать снова»; у остальных состояний формы нет | test_sd_mailbox::test_reparse_button_requeues_error_mail_for_manage_holder_only_403_for_others_and_ignores_processed_mail, test_sd_intake::test_error_on_any_step_rolls_back_marks_parse_error_last_error_step_and_class_only |

## 14. Тексты сообщений

Тексты, которые ищут тесты. Правила поиска: текст берётся как подстрока видимого текста ответа
(`[role=alert]`, `[role=status]` или названный элемент) или как `ServiceDeskError.message`;
регистр первой буквы не проверяется; знаки `«»` и `<…>` в таблицах — условное обозначение
подставляемого значения. Колонка «Источник»: адрес строки спеки (`spec.md:N`) или плана
(`plan.md:N`) — текст дословный; «текст контракта» — подпись выбрана автором контракта (решение
Opus по B1-1: тест сверяет такой текст только по коду причины, а читает его владелец на ручном
проходе T-3301). Коды причин и условия отказа — таблица 6.2, здесь не повторяются. Знака
вопроса в текстах нет: подтверждения сформулированы повествовательно.

### 14.1. Отказы сервисов (код → текст)

Тест находит текст так: ошибка поля формы — текст в `[data-error="<поле>"]` рядом с полем (без
роли `alert`); общий отказ без поля — `[role=alert]` страницы или фрагмента содержит текст из
строки (решение Opus RD2-7); у отказа поля общего `[role=alert]` нет; для кодов с пометкой «слово»
тест ищет только названное слово или число.

| Код (6.2) | Текст | Источник | Тест ищет |
|---|---|---|---|
| `no_access` | «нет доступа» | plan.md:807 (причина в итоге группового действия) | подстроку |
| `ticket_closed` | «Заявка закрыта: сначала откройте её» | plan.md:795-796 | подстроку |
| `ticket_open` | «Заявка не закрыта: открывать заново нечего» | текст контракта | код |
| `not_participant` | «Ответственным может быть только участник очереди заявки» | текст контракта (смысл — spec.md:240) | код |
| `no_queue` | «Очередь заявки не определена: задайте очередь по умолчанию в настройках сервис-деска» | текст контракта | код |
| `not_queue` | «Этот узел не отмечен очередью сервис-деска» | текст контракта | код |
| `already_queue` | «Узел уже отмечен очередью» | текст контракта | код |
| `queue_has_open_tickets` | «Отметку снять нельзя: в очереди есть открытые заявки — <число>» | текст контракта (отказ с объяснением — spec.md:406) | число открытых заявок |
| `queue_is_default` | «Отметку снять нельзя: это очередь по умолчанию. Сначала выберите другую» | текст контракта (plan.md:419-421) | код |
| `same_queue` | «Заявка уже в этой очереди» | текст контракта | код |
| `queue_required` | «Выберите очередь» | текст контракта | код |
| `reason_too_long` | «Причина передачи не длиннее 500 знаков» | текст контракта (plan.md:764-765) | код |
| `name_required` | «Укажите название» | текст контракта | код |
| `name_too_long` | «Название не длиннее <100 или 150> знаков» | текст контракта | код |
| `name_taken` | «Такое название уже есть в этом справочнике» | текст контракта | код |
| `in_use` | «Значение используется в заявках, удалить его нельзя. Уберите его в архив» (у подразделения-клиента — «…в заявках или в записях заявителей…») | текст контракта; смысл — spec.md:414-415 | слово «архив» |
| `system_protected` | «Системное значение нельзя убрать в архив или удалить; переименовать его можно» | текст контракта (spec.md:718-719) | код |
| `default_protected` | «Значение по умолчанию нельзя убрать в архив или удалить: сначала отметьте другое» | текст контракта (spec.md:716-717) | код |
| `last_active` | «Это последний действующий статус своего вида: убрать его в архив нельзя» | текст контракта (spec.md:416-417) | код |
| `queue_not_marked` | «Очередью категории может быть только узел, отмеченный очередью» | текст контракта | код |
| `assignee_not_participant` | «Ответственный по умолчанию должен быть участником очереди категории» | текст контракта (spec.md:407-409) | код |
| `archived_value` | «Значение в архиве: выберите другое» | текст контракта (plan.md:451-453) | код |
| `bad_status` | «Этот статус нельзя выбрать здесь» | текст контракта | код |
| `source_required` | «Выберите источник заявки» | текст контракта | код |
| `email_required` | «Укажите адрес заявителя» | текст контракта | код |
| `bad_domain` | «Домен записан неверно: <домен>» | текст контракта | код |
| `out_of_range` | «Значение поля «<название поля>» должно быть от <мин> до <макс>» | текст контракта | название поля |
| `text_required` | «Введите текст» | текст контракта | код |
| `text_too_long` | «Текст ответа не длиннее 50 000 знаков» | текст контракта | код |
| `not_resendable` | «Отправить заново можно только неотправленный ответ» | текст контракта | код |
| `resolution_required` | «Напишите решение» | текст контракта; тест `test_d05_close_without_resolution_text_refused_asks_for_resolution` ищет слово «решение» | слово «решение» |
| `resolution_too_long` | «Решение не длиннее 10 000 знаков» | текст контракта | код |
| `bulk_limit` | «За один раз можно обработать не больше 100 заявок» | текст контракта (plan.md:802) | число 100 |
| `bad_action` | «Неизвестное групповое действие» | текст контракта | код |
| `intake_closed` (форма) | «Приём заявок через форму сейчас закрыт. Напишите письмо на <адрес ящика>» | plan.md:1045-1046 | подстроку и адрес ящика |
| `intake_closed` (исполнитель) | «Приём заявок закрыт: в настройках сервис-деска не заданы почтовые домены» | текст контракта | код |
| `rate_limited` | «С вашего адреса отправлено слишком много заявок за час. Напишите письмо на <адрес ящика>» | plan.md:1061-1062 | подстроку и адрес ящика |
| `bad_email` | «Укажите рабочую почту на корпоративном домене» | plan.md:1048-1049 | подстроку |
| `requester_name_required` | «Укажите ФИО» | текст контракта (plan.md:1050-1051) | код |
| `requester_name_too_long` | «ФИО не длиннее 255 знаков» | текст контракта | код |
| `subject_required`, `subject_too_long` | «Укажите тему» и «Тема не длиннее 255 знаков» | текст контракта (plan.md:1051) | код |
| `description_required`, `description_too_long` | «Опишите проблему» и «Описание не длиннее 50 000 знаков» | текст контракта (plan.md:1051) | код |
| `consent_required` | «Подтвердите согласие на обработку персональных данных» | текст контракта (plan.md:1051-1052) | код |
| `category_required` | «Выберите категорию» | текст контракта | код |
| `category_not_offered`, `unit_not_offered` | «Выберите категорию из списка» и «Выберите подразделение из списка или «Нет в списке»» | текст контракта (plan.md:1049-1050) | код |
| `file_rejected` | «файл «<имя>» не принят: <подпись причины>» (подписи — `Attachment.REJECT_TITLES`: «больше 20 МБ», «письмо больше 50 МБ», «исполняемый файл», «архив с паролем») | plan.md:990; подписи — решение Opus A7 | подстроку «не принят» и имя |
| `too_many_files`, `total_too_big` | «Файлов не больше 10» и «Файлы вместе не больше 50 МБ» | текст контракта (plan.md:991-993) | код |
| `requester_has_tickets` | «У заявителя есть заявки: запись удалить нельзя» | текст контракта (plan.md:1194-1195) | код |
| `too_big` | «Файл больше 2 МБ» | spec.md:459 (смысл), текст контракта | код |
| `too_many_rows` | «В файле больше 2000 строк» | spec.md:459 (смысл), текст контракта | код |
| `bad_format` | «Файл должен быть таблицей CSV или XLSX» | текст контракта | код |
| `not_utf8` | «Файл должен быть в кодировке UTF-8» | текст контракта | код |
| `zip_bomb`, `xml_bomb` | «Файл не принят: после распаковки он слишком велик» и «Файл не принят: небезопасное содержимое» | текст контракта | код |
| `missing_columns` | «В файле нет колонки «Почта»» | spec.md:459 (смысл), текст контракта | слово «Почта» |
| подтверждение не дано | «Подтвердите действие» (POST без `confirm=1`, 12) | текст контракта | подстроку |

Ошибки полей открытой формы (`[data-error="<поле>"]`, соответствие кода полю — 6.19):
`email` — `bad_email`; `name` — `requester_name_required`, `requester_name_too_long`;
`client_unit` — `unit_not_offered`; `category` — `category_not_offered`; `subject` —
`subject_required`, `subject_too_long`; `text` — `description_required`,
`description_too_long`; `consent` — `consent_required`. Тест находит поле по `[data-error]` и
сверяет код через атрибут `data-code="<код>"` у того же элемента.

### 14.2. Сообщения и подписи страниц

| Подпись | Где | Источник | Тесты |
|---|---|---|---|
| «Заявка #N создана в очереди «…»» | `[role=status]` страницы `/tickets/` после создания заявки исполнителем, если заявка ему не видна | plan.md:1101; spec.md:352, 896 | test_sd_executor::test_non_member_redirected_to_list_with_created_message, e2e/test_d07_phone |
| «Заявка #N передана в очередь «…»» | `[role=status]` страницы `/tickets/` (или `/`, если пункта меню «Заявки» нет) после `HX-Redirect` или 302 при передаче, если заявка перестала быть видна | plan.md:769 | test_sd_assignment::test_transfer_to_unavailable_ticket_returns_hx_redirect_with_message |
| «Заявка перейдёт в очередь «…»» | фрагмент подтверждения смены категории (`[data-dialog="ticket-category"]`) | plan.md:771-772 | test_sd_assignment::test_category_change_to_other_queue_asks_confirmation_first |
| «Выполнено: N; пропущено: M» и строки «#номер — причина» | `[data-bulk-result]` | plan.md:805-808; причина недоступной — «нет доступа» | test_sd_assignment_2::test_group_*, e2e/test_d04_dispatch |
| «Заявка принята. Подтверждение с номером придёт на <адрес>» | `/request/done/` | plan.md:1069-1070; spec.md:126, 860 | test_sd_form |
| «Подать заявку в ИТ-отдел» | ссылка на странице входа | plan.md:1073; spec.md:149 | test_sd_form |
| «Нет в списке» | первый вариант `select[name=client_unit]` формы | spec.md:137, 851 | test_sd_form |
| «Ждём ответа заявителя» | подпись флажка `wait` | spec.md:173; plan.md:739 | test_sd_reply, e2e/test_d03_reply |
| «Взять себе» | кнопка и флажок | plan.md:754, 1082 | test_sd_assignment, test_sd_executor |
| «Снять ответственного» | кнопка | plan.md:761-762 | test_sd_assignment |
| «Передать в очередь», «Назначить ответственного», «Сменить критичность» | действия групповой панели | plan.md:800-801 | test_sd_assignment_2 |
| «Сохранить и в записи заявителя» | кнопка `save_to_record` | plan.md:784 | test_sd_assignment_2::test_requester_name_save_also_in_record_button |
| «Открыть заново» | кнопка у закрытой | plan.md:790 | test_sd_closing_2 |
| «Отправить заново без заражённых вложений» | кнопка у неотправленного ответа | plan.md:846; spec.md:318 | test_sd_reply::test_resend_button_only_on_not_sent_reply |
| «Новая заявка» | кнопка списка и пустого состояния | spec.md:323, 886; plan.md:1077 | test_sd_executor |
| «Отмена» | кнопка диалога | CONTRACT-002 § 10 | test_sd_assignment |
| «Мои», «Без ответственного», «Мои очереди», «Ждут ответа заявителя», «Закрытые», «Все» | подписи пресетов | plan.md:1109-1122; spec.md:616-617 | test_sd_list::test_preset_* |
| «Страница N» | `[data-page]` | plan.md:1163 | test_sd_list::test_total_count_only_on_show_count_button |
| «показать количество» | `a[data-action="show-count"]` | plan.md:704, 1163 | test_sd_list::test_total_count_only_on_show_count_button |
| «введите хотя бы 2 буквы» | `[data-hint="short"]` | plan.md:1135 | test_sd_search::test_search_words_shorter_than_two_chars_skipped_with_hint |
| «Закрыл: Имя Фамилия» | колонка «ответственный» списка у закрытой без ответственного и поле `closed-by` карточки; имя — `closed_by.full_name` (правило «Имя Фамилия» — 10.3), у уволенного рядом «(уволен)» | plan.md:1167, 1262; spec.md:667 | test_sd_list_2::test_closed_without_assignee_shows_closed_by_name, test_sd_reconcile |
| «внутренний» | отметка комментария в ленте | plan.md:824 | test_sd_card |
| «ответ исполнителя» | отметка ответа в ленте | plan.md:824-825 | test_sd_card |
| «заявитель <адрес>», «участник <адрес>» | автор элемента `incoming` | plan.md:822-823 | test_sd_card::test_feed_authors_staff_name_dismissed_mark_requester_and_participant_address |
| «согласие на обработку ПДн» и дата | поле `consent` карточки | plan.md:813-814 | test_sd_card |
| текст согласия на форме | `[data-consent-text]`: «Я согласен на обработку моих персональных данных (почта, ФИО, подразделение, текст заявки) для рассмотрения заявки ИТ-отделом» | текст контракта (plan.md:1039-1040 требует «какие данные и зачем»); тест ищет слова «персональных данных» | test_sd_form::test_form_has_required_fields_and_consent_checkbox |
| «ФИО, почта и подразделение работников общества хранятся, чтобы определять подразделение заявителя по адресу письма» | `[data-format-help]` страницы загрузки заявителей | spec.md:479-481 | test_sd_requester_import::test_import_page_text_names_data_and_purpose, e2e/test_d10_requesters |
| «Удалить заявителей без заявок, которых нет в файле» | подпись флажка `delete_missing` | spec.md:454 | test_sd_requester_import_2, e2e/test_d10_requesters |
| «будет добавлен», «будет обновлён: ФИО: было → стало; подразделение: было → стало», «без изменений», «ошибка: …» | текст строки `tr[data-import-row]` предпросмотра; у выполненных строк — «добавлен», «обновлён», «без изменений», «ошибка: …»; `[data-row-reason]` — только у строки с причиной («ошибка: …») | spec.md:444-446; plan.md:1213-1214 | test_sd_requester_import::test_row_results_added_updated_unchanged_error |
| «ошибка: подразделение в архиве» | `[data-row-reason]`, код `unit_archived` | spec.md:489 | test_sd_requester_import::test_row_error_unit_in_archive |
| «ошибка: повтор почты» | `[data-row-reason]`, код `email_repeated` | spec.md:490 | test_sd_requester_import::test_row_error_duplicate_email_other_case_second_row |
| «ошибка: не указана почта», «ошибка: неверный формат почты», «ошибка: почта не из корпоративного домена», «ошибка: значение слишком длинное» | `[data-row-reason]`, коды `email_missing`, `email_invalid`, `foreign_domain`, `too_long` | spec.md:446 (форма «ошибка: …»), причины — текст контракта | test_sd_requester_import::test_row_error_* |
| «добавлено N, обновлено M, без изменений K, с ошибками L» | `[data-result-summary]` (после слов, при ненулевых числах, добавляется «; удалено D; сменили отметку на «заявка»: E») | spec.md:452-453, 1170; plan.md:1230-1231 | test_sd_requester_import_2::test_preview_and_total_show_deleted_and_origin_changed_counts |
| «Разбор поставлен в очередь» | `[role=status]` после «Разобрать снова» письма с ошибкой | текст контракта | test_sd_mailbox |
| «Письмо не ждёт повторного разбора» | `[role=status]` после «Разобрать снова» для обработанного и иного письма | текст контракта | test_sd_mailbox |
| «Сервис-деск не настроен: укажите домены и очередь по умолчанию» (и ссылка «Настроить») | `[data-notice="servicedesk-setup"]` на главной | решение плана (plan.md:480-482, точка `home_notices`), текст контракта | test_sd_queues::test_home_notice_for_manage_holder_until_configured |
| «Соединение с ящиком заявок не защищено (IMAP_SECURITY=none): режим только для стенда» | `[data-warning="imap-security"]` на `/servicedesk/` | plan.md:268, 473-474 (предупреждение; слов в плане нет), текст контракта; тест ищет `IMAP_SECURITY=none` | test_sd_queues (страница настроек), e2e/test_d09_settings |
| «ящик не подключён» | `[data-mailbox-status][data-mailbox-state="not-connected"]`, когда `MailboxStatus.configured` ложно, то есть `IMAP_HOST` пуст (единственное условие, решение Opus F4-6) | plan.md:266 | test_sd_mailbox (через страницу), e2e/test_d01_mail::test_d01_empty_domain_list_rejects_mail_and_inbound_shows_foreign_domain |
| «Заявки» | пункт меню и ссылка карточки сотрудника | plan.md:155, 1180-1183; spec.md:636 | test_sd_list_2 |
| «Сервис-деск» | пункт меню | план «Точки расширения» | test_sd_pages |
| «в архиве» | метка архивного значения справочника | текст контракта | test_sd_dictionaries::test_archived_value_shown_in_list_filter_with_archive_mark |
| «системное» | метка системного значения справочника | текст контракта | test_sd_dictionaries |

### 14.3. Имена и состояния

| Подпись | Где | Источник | Тесты |
|---|---|---|---|
| «<Имя> (уволен)» | автор элемента ленты, ответственный в списке и карточке, закрывший заявку; `data-dismissed="true"` | plan.md:1263-1264 (SPEC-002 FR-127); CONTRACT-002 § 10 | test_sd_reconcile::test_dismissed_name_marked_in_messages_and_closed_tickets, test_sd_card, e2e/test_d15_staff_change |
| «не назначен» | поле ответственного карточки и колонка списка | CONTRACT-002 § 10 (то же слово) | test_sd_card |
| «не заполнено» | пустое поле карточки (подразделение, сложность, категория) | CONTRACT-002 § 10 | test_sd_card |
| «—» | ячейки `sender` и `subject` у письма со стёртыми данными; `last-message` у заявки без писем | plan.md:708-709 | test_sd_retention_2, test_sd_list_2 |
| «ждёт проверки файлов», «поставлен в очередь», «не отправлен» | подписи `TicketEntry.SendState` у ответа (`[data-send-state]`) | подписи контракта (раздел 2.2, решение Opus A7) | test_sd_card, test_sd_reply |
| «в очереди», «отправлено», «не доставлено» | подписи `MailMessage.status` (`[data-mail-status]`) | `apps/integrations/mail/models.py` (проверено чтением, строки 12-14) | test_sd_card::test_card_shows_mail_state_from_mail_message |
| «проверяется», «в карантине» | состояния вложения в карточке (`[data-attachment][data-state]`) | текст контракта (plan.md:1002-1003 — сами состояния) | test_sd_attachments |
| «получено», «обработано», «ждёт настройки», «ошибка» | подписи `InboundMail.Status` | раздел 2.2 | test_sd_intake |
| подписи итога письма | `[data-cell="outcome"]`: «создана заявка», «добавлено в заявку», «открыта заново», «отклонено: чужой домен», «отклонено: письмо с адреса ящика заявок», «автоматическое письмо», «ждёт настройки очереди по умолчанию», «ошибка разбора»; у `created` и других с заявкой — «#N» | раздел 2.2; spec.md:499-531 | test_sd_intake, e2e/test_d11_inbound |
| «новая», «в работе», «ждёт ответа заявителя», «закрыта» | подписи видов статуса | раздел 2.1; spec.md:429-431 | test_sd_dictionaries |
| «заявитель», «исполнитель» | `[data-last-from]` | plan.md:1167-1168; spec.md:640 | test_sd_list_2::test_last_message_shows_time_and_requester_or_executor |
| «таблица», «заявка» | отметка записи заявителя | раздел 2.2; spec.md:482-485 | test_sd_requesters |
| «не задана» | очередь по умолчанию на странице настроек, пока не выбрана | текст контракта | test_sd_queues |
| «по умолчанию» | отметка очереди и статуса по умолчанию | spec.md:431 | test_sd_dictionaries, test_sd_queues |

### 14.4. Пустые состояния (`[data-empty-state]`)

Пояснение непустое; тест проверяет атрибут, непустой текст и (у `tickets`) кнопку. Тексты —
текст контракта (plan.md:1171-1174: «пустой пресет объясняет, что здесь будет и даёт кнопку»).

| `data-empty-state`, `data-preset` | Текст | Кнопка |
|---|---|---|
| `tickets`, `mine` | «Здесь будут заявки, где вы назначены ответственным и которые ещё не закрыты» | «Новая заявка» при праве |
| `tickets`, `unassigned` | «Здесь будут открытые заявки ваших очередей, у которых нет ответственного» | «Новая заявка» при праве |
| `tickets`, `my_queues` | «Здесь будут открытые заявки ваших очередей» | «Новая заявка» при праве |
| `tickets`, `waiting` | «Здесь будут заявки, которые ждут ответа заявителя» | «Новая заявка» при праве |
| `tickets`, `closed` | «Здесь будут закрытые заявки» | «Новая заявка» при праве |
| `tickets`, `all` | «Здесь будут все заявки, которые вам доступны» | «Новая заявка» при праве |
| `tickets` (фильтр или поиск ничего не нашли) | «По вашему запросу заявок нет» | нет |
| `requesters` | «Записей заявителей пока нет: они появятся из заявок или из загрузки таблицы» | `a[data-action="requesters-import"]` |
| `inbound` | «Писем пока нет» | нет |
| `dictionary` | «В справочнике пока нет значений» | `a[data-action="dictionary-new"]` |

### 14.5. Лента: тексты событий

Тексты собирает карточка из кода `event` и `data` (9.3). Значения подставляются на момент
события; «было» и «стало» пусты — «не назначен» у ответственного и «не задано» у прочих.
Тест находит строку по `[data-event="<код>"]` и сверяет подстроки названных слов.

| Код `event` | Текст в ленте | Источник | Тесты |
|---|---|---|---|
| `assignee_changed` | «ответственный: <было> → <стало>» | plan.md:754-755 | test_sd_assignment::test_assignee_changes_write_feed_event_was_became |
| `assignee_reconciled` | «ответственный снят: больше не участник очереди» | plan.md (6.12), spec.md сценарий 15 | test_sd_reconcile::test_removed_assignee_leaves_feed_event_journal_entry_and_bus_event |
| `transferred` | «передана в очередь: <откуда> → <куда>; причина: <текст>» (часть «; причина» — только при непустом `reason_text`; автор — в `[data-author]`) | plan.md:766-767 | test_sd_assignment::test_transfer_event_who_from_to_reason_and_journal_without_reason |
| `queue_changed` | «очередь: <было> → <стало>»; при коде причины `queue_unmarked` — «очередь: <было> → <стало>, причина — очередь снята» | plan.md:885-886; решение Opus П6: код в `data["reason"]` — `queue_unmarked`, подпись «очередь снята» — только здесь и в 6.2 | test_sd_closing_2::test_manual_reopen_when_node_not_queue_goes_to_default_queue_with_event |
| `category_changed` | «категория: <было> → <стало>» | plan.md:776 (одно событие на смену категории); подпись — текст контракта | test_sd_card::test_ticket_field_events_in_russian_for_each_kind |
| `priority_changed`, `complexity_changed`, `client_unit_changed` | «критичность: …», «сложность: …», «подразделение: <было> → <стало>» | plan.md:778-781; подпись — текст контракта | то же |
| `requester_name_changed` | «ФИО заявителя изменено» (значений нет) | plan.md:778-781 | test_sd_assignment_2::test_requester_name_edit_event_has_no_values |
| `status_changed` | «статус: <было> → <стало>» | plan.md (таблица «Статусы и переходы»); spec.md:729-740 | test_sd_status |
| `closed` | «заявка закрыта: <статус>; решение: <текст решения>» | plan.md:889-890 (статус и решение в событии), подпись — текст контракта | test_sd_closing::test_close_event_has_status_and_resolution_text |
| `autoclosed` | «заявка закрыта автоматически: <статус>» | plan.md (6.11); подпись — текст контракта | test_sd_status_autoclose |
| `reopened` | «заявка открыта заново» (способ — «вручную» или «письмом заявителя» в скобках) | plan.md:882-890; подпись — текст контракта | test_sd_closing_2 |
| `continued` | «продолжение — заявка #<N>» | plan.md:521-523; раздел 9.3 | test_sd_closing_2::test_letter_after_term_creates_new_ticket_with_previous_and_confirmation |
| `participant_removed` | «участник снят»; после обезличивания — «участник (обезличено)» | plan.md:788 («событие ленты и журнала»); FR-290 | test_sd_assignment_2, test_sd_retention::test_participants_deleted_and_events_show_anonymized_participant |
| `reply_not_sent` | `ticket_closed` — «ответ не отправлен: заявка закрыта»; `quarantine` — «ответ не отправлен: вложение «<имя>» в карантине»; `encrypted` — «ответ не отправлен: вложение «<имя>» — архив с паролем» (после обезличивания без имени) | plan.md:839-844 | test_sd_reply::test_reply_with_quarantined_file_not_sent_with_event, test_reply_with_password_archive_not_sent_with_event, test_reply_with_ticket_closed_during_check_not_sent_ticket_closed |
| `mail_failed` | «письмо не доставлено: <вид письма>» (виды — `VALUES["mail_kind"]` раздела 9.2) | plan (6.10); подпись — текст контракта | test_sd_reply::test_failure_after_last_retry_writes_not_delivered_event_in_feed |
| `attachment_rejected` | «вложение «<имя>» не принято: архив с паролем» | plan.md:839-841; раздел 6.18 | test_sd_attachments::test_scan_heuristics_encrypted_rejects_as_password_archive_and_erases_file |
| `attachment_quarantined` | «вложение в карантине: «<имя>»» (после обезличивания без имени) | plan.md:1003 | test_sd_attachments::test_scan_infected_goes_to_quarantine_with_feed_event_and_audit |

Событие `queue_changed` при коде `queue_unmarked` — решение Opus П6 (заметки по RB2+C,
2026-10-06): раздел 6.2 (строка «причина «очередь снята»»), 6.11 (`closing.reopen`) и 9.3 в части
значения `data["reason"]` внесены; здесь отображение.

## 15. Вопросы к Opus

Вопросы части a (подраздел A). Все семь решены Opus 2026-10-06 (ниже); в разделах 1-5 принят
вариант автора с пометкой «решение Opus A…».

### A. Среда, модели, ядро, org, почта

| № | Суть | Варианты | Что предлагаю |
|---|---|---|---|
| A1 | Тестам нужно «сейчас» в определённые часы суток (сценарий 13: письмо о нерабочем времени зависит от календаря и часа), а решение 5 разрешает только `backdate` (он сдвигает сохранённые отметки и «сейчас» не задаёт) | 1) только `backdate`, а службы берут час из параметра `now=`; 2) тесты нерабочего времени берут `clock` из `tests/conftest.py` | вариант 2 и только для тестов, где код читает час суток и нет заданий RQ; остальные тесты — `backdate` (раздел «Правила для всех тестов») |
| A2 | Файл «найдено `Heuristics.Encrypted.*`» (архив с паролем, определён антивирусом): что остаётся от строки `StoredFile` | 1) строка удаляется в той же транзакции, `Attachment.file` становится пустым; 2) строка остаётся со статусом `quarantine` | вариант 1: файла на диске нет, статус `quarantine` солгал бы; тест проверяет `Attachment.rejected == "encrypted"`, `Attachment.file is None`, файла нет на диске |
| A3 | Порядок отказов `delete_unit`: узел с участниками и с заявками одновременно | 1) `not_empty` раньше точки `unit_usage`; 2) наоборот | вариант 1 (прежние отказы среза 002 не меняются, новый — последним); на пустом узле разницы нет |
| A4 | `set_marks` публикует `access.changed` только при смене состава отмеченных (`было ^ стало`); смена «руководитель на заместителя» одного человека события не даёт | 1) как предложено; 2) публиковать при любом изменении набора отметок | вариант 1: участие в очередях у руководителя и заместителя одинаково (FR-232), состав очередей не меняется |
| A5 | `move_unit` публикует одно событие с объединённым списком; для этого у `forget_users` появляется ключ `publish=False` | 1) новый необязательный ключ; 2) два события подряд (одно от `forget_users`, второе — лишние руководители) | вариант 1: тест «с прежними руководителями» читает один вызов `Bus.calls("access.changed")`; ключ обратно совместим |
| A6 | `FakeMailbox.search_since(day)` сравнивает дату `INTERNALDATE` в UTC, а как Dovecot считает дату для `SINCE`, в фактах F1 не проверялось; запас «на сутки раньше» из плана покрывает любой пояс, на настоящем сервере это покажет живой тест T-3109 | 1) UTC и запас в сутки у службы (план: «дата на сутки раньше»); 2) учитывать пояс | вариант 1: запас плана покрывает пояса, а уточнение по `INTERNALDATE` делает служба по точному времени |
| A7 | Значение `Attachment.REJECT_TITLES` и подписи статусов `InboundMail`, `TicketEntry.send_state` в плане не названы дословно (взяты русские слова плана, где они были; остальные — «подпись контракта») | 1) оставить как в таблице раздела 2; 2) Opus даёт тексты | вариант 1: подписи видны только во «Входящих письмах» и в карточке; тексты сообщений берёт часть d |

**Решения Opus по A1–A7 (2026-10-06).** Все семь — как предлагает автор; в разделах 1–5 пометки
о вопросах заменены на «решение Opus A…».
- A1 — вариант 2. Это уточнение решения 5 задач, а не отступление: `Clock` — помощник среза 001
  (`tests/factories.py`), а не библиотека подмены часов; службы по-прежнему берут время из
  `timezone.now()`. `clock` — только там, где код читает час суток и заданий RQ нет.
- A2 — вариант 1: план («Вложения», «Итог проверки») — «файл стирается, `Attachment.rejected =
  encrypted`», а непринятый файл «не сохраняется».
- A3 — вариант 1: отказы среза 002 (`root_protected`, `not_empty`) идут первыми, новый — последним.
- A4 — вариант 1: участие в очередях у руководителя и заместителя одинаково (FR-232).
- A5 — вариант 1: необязательный ключ `publish=False` у `forget_users` обратно совместим.
- A6 — вариант 1: запас «на сутки раньше» задаёт план («Путь письма в заявку»).
- A7 — вариант 1: подписи контракта; их увидит владелец на ручном проходе T-3301.

### B1. Сервисы servicedesk, первая половина (раздел 6.1-6.13)

| № | Суть | Варианты | Что предлагаю |
|---|---|---|---|
| B1-1 | В плане и спеке нет дословных текстов отказов для большинства кодов раздела 6.2 (названия, архив, очередь, ответ, решение, групповые действия); дословные есть только у `ticket_closed`, `no_access`, причин `unit_usage` и причины «очередь снята» | 1) часть d пишет тексты в раздел 14, тест сверяет только `code`; 2) Opus даёт тексты сейчас | вариант 1: текст — на странице, читает владелец на проходе T-3301; тесты, где нужен текст (T-3103 «предложение убрать в архив», T-3102 «объяснение»), ищут по слову «архив» и по числу заявок, а не по всей строке |
| B1-2 | T-3114 test_feed_ordered_by_time_with_authors_and_attachments_in_one_query: «одним запросом с авторами и вложениями» (план, «Лента»); вложения в одной выборке с лентой без повторов элементов не получить | 1) не больше двух запросов (записи с `select_related`, затем вложения), число не растёт с числом элементов; 2) один запрос с агрегатом JSON по вложениям | вариант 1: тест считает запросы при 5 и при 50 элементах и требует равенства и не больше двух |
| B1-3 | План: `set_status` пишет и событие ленты, и событие журнала; закрытие, автозакрытие, открытие заново имеют свои коды журнала (`ticket.closed`, `ticket.autoclosed`, `ticket.reopened`) со статусом до и после | 1) `set_status` пишет `ticket.updated` только для причин `assigned`, `reply`, `letter`, `manual`, а для `close`, `autoclose`, `reopen` журнал пишет `closing.*`; 2) всегда оба события | вариант 1: иначе у закрытия две записи журнала с одним содержанием; тест аудита ищет одну запись `ticket.closed` на закрытие |
| B1-4 | `tickets.create` вложения не принимает; план: проверка вложений идёт после фиксации, а `attachments.accept(entry, parts)` создаёт `Attachment` и `StoredFile` | 1) зовущий (`intake`, `form`, заявка исполнителя) вызывает `attachments.accept` в той же транзакции сразу после `create`, отказ вложений откатывает заявку (форма) либо не принимает файл (письмо) по правилам b2; 2) `create(..., parts=...)` | вариант 1: у письма и формы правила отказа разные (раздел «Вложения»), решает b2; ей нужно знать, что `create` возвращает `Created.entry` |
| B1-5 | Обновление заявки входящим письмом (элемент `incoming`, `last_message_*`, переход из «ждёт ответа» в «в работе», участники из копии, событие шины `reply_received`) тесты T-3110 и T-3114 требуют от сервиса, но модуль плана не назван | 1) `tickets.add_incoming`, его зовёт `intake` (b2); 2) пишет `intake` сам | вариант 1: переход статуса и отсчёт — по таблице плана «Статусы и переходы», его место в `tickets`; b2 обязана звать `add_incoming` вместо собственной записи; открытие закрытой заявки письмом — `closing.reopen(..., via="mail")` и `closing.within_reopen_term`, зовёт `intake` |
| B1-6 | `tickets.create(take_by=...)`: «Взять себе» только участник очереди (FR-228); а test_sd_executor::test_post_take_to_self_by_non_member_creates_without_assignee_or_with_category_default требует создать заявку без ответственного | 1) сервис молча не берёт, если `take_by` не участник, и применяет ответственного по умолчанию категории; 2) отказ `not_participant` | вариант 1: так названо в тесте T-3122; отказ нужен только `assignment.take` и `assign` |
| B1-7 | Части b1 нужны функции модулей b2, плана с такими именами нет: `letters.send(ticket, template, *, entry=None, extra=None)`, `search.index(ticket, entry=None)`; в плане есть только `attachments.accept(entry, parts)` | 1) b2 принимает эти имена; 2) b2 называет свои, b1 правит | вариант 1; кроме того b2 обязана звать `replies.on_files_checked(entry_id)` из обработчика `file_purposes`, когда проверен последний файл ответа, и `replies.add_event` для всех событий ленты |
| B1-8 | Отказ `tickets.get_for` — `django.http.Http404`, а не `ServiceDeskError` (план: «заявка по номеру среди видимых или 404»); все остальные отказы — `ServiceDeskError` с `code` | 1) как предложено; 2) `ServiceDeskError(code="not_found")` | вариант 1: маршрут не должен различать «нет» и «чужая» даже по классу ошибки |
| B1-9 | Счётчик пункта меню (FR-280, `badge`) и пресеты списка в b1 не входят; `access.menu_visible` и `access.can_create` я назвал по плану (`visible` пункта, право на `/tickets/new/`) | 1) счётчик пишет b2 в модуле списка и счётчика; 2) в `access` | вариант 1: у счётчика свои запросы и тесты T-3122, T-3124; пересечений с `access` нет |
| B1-10 | При открытии заново ответственный, который не участник итоговой очереди, в плане не описан (сказано: «остаётся, если он участник итоговой очереди») | 1) снимается с событием и шиной; 2) остаётся | вариант 1: иначе нарушается правило FR-235 «ответственный всегда участник очереди»; случай возможен только при смене очереди по умолчанию, тестов на него нет |
| B1-11 | `access.scope(user)` по плану «кладётся на объект запроса»; сервис не знает запроса | 1) кэш в атрибуте `user._sd_scope` объекта пользователя (объект `request.user` живёт один запрос); 2) middleware | вариант 1: у объекта из `request.user` время жизни равно запросу, в тесте новый объект пользователя даёт свежий расчёт |
| B1-12 | Уточнения подписей плана: `set_status` получил `ip=None` и `start_countdown=True`, `closing.reopen` — `ip=None` и `via="manual"`; `reconcile.for_users` возвращает `int` | 1) принять с пометкой «уточнение»; 2) вернуть подписи плана, остальное во внутренние функции | вариант 1: без `start_countdown` ответ с флажком не может отложить отсчёт до постановки письма (план, «Статусы и переходы»); без `via` в журнале нет способа открытия (план, «Журнал») |

**Решения Opus по B1-1…B1-12 (2026-10-06).** Все — как предлагает автор; уточнения:
- B1-1: серверные тесты сверяют `exc.code`; текст отказа для пользователя — раздел 14 (часть d):
  где текст есть в спеке или плане — дословно с адресом строки, иначе «подпись контракта»
  (их увидит владелец на ручном проходе T-3301); в таблице 6.2 — «текст — раздел 14».
- B1-2: «лента одним запросом» (plan.md:821) = «число запросов не растёт с числом элементов»:
  не больше двух (элементы с авторами; вложения — `prefetch_related`); план уточнить в его
  следующей версии.
- B1-3, B1-4, B1-5, B1-8, B1-11, B1-12: как предложено.
- B1-6: подтверждено именем теста
  `test_post_take_to_self_by_non_member_creates_without_assignee_or_with_category_default` (T-3122).
- B1-7: как предложено; имена `letters.send(...)`, `search.index(...)`,
  `replies.on_files_checked(entry_id)` и `replies.add_event(...)` обязательны для части b2.
- B1-9: счётчик меню (`badge`, FR-280) и пресеты списка пишет часть b2 (модуль списка и поиска).
- B1-10: согласуется с FR-235 и тестом
  `test_reopened_ticket_of_removed_assignee_has_no_assignee` (T-3104).

### B2. Сервисы servicedesk, вторая половина (разделы 6.14-6.24)

Решения автора части b2; Opus решил их 2026-10-06 (ниже).

| № | Суть | Варианты | Что предлагаю |
|---|---|---|---|
| B2-1 | Модуль `mail_parse` (чистые функции разбора письма, T-3209, тесты T-3108) в списке модулей задания b2 не назван; без него T-3108 нечего вызывать | 1) отдельный подраздел 6.14 с модулем `mail_parse`; 2) вложить функции в `intake` | вариант 1: так названо задачей T-3209, `tickets.create` зовёт `mail_parse.clean_subject` |
| B2-2 | Чем заменять символ NUL в тексте и теме (план: «заменяется», чем — не сказано; `test_nul_replaced_in_text_and_subject`) | 1) пробел; 2) U+FFFD; 3) удалить | вариант 1: U+FFFD запускает запасной путь разбора текста, удаление склеивает слова |
| B2-3 | Формат `InboundMail.last_error` (план: «только шаг и класс исключения») | 1) `"<шаг>: <класс>"` с шагами `parse`, `checks`, `link`, `ticket`, `attachments`, `finish`; 2) два поля | вариант 1: полей в модели нет |
| B2-4 | `related_ref` письма заявки: план («Хранение», шаг 4) — `ticket:<id>`; `replies.on_mail_failed` (b1) ищет и заявку, и элемент, а `anonymize_related` сверяет значение целиком | 1) `ticket:<id заявки>`, элемент — по `MailMessage` в `TicketEntry.mail`; 2) добавить номер элемента | вариант 1; раздел 10 (часть c) подтверждает формат, `replies.on_mail_failed` находит элемент по `TicketEntry.mail` |
| B2-5 | `attachments.accept(entry, parts)` у письма не отказывает (FR-285), у формы, ответа и заявки от исполнителя — отказывает целиком; b1 зовёт `accept(entry, parts)` без режима | 1) один метод с ключами `strict=True`, `mail_size=None`, а `intake` зовёт `strict=False, mail_size=len(raw)`; 2) две функции | вариант 1: подпись плана и b1 не меняется (по умолчанию `strict=True`); сверка числа и суммы файлов — `attachments.precheck` до записи |
| B2-6 | Модуль для «Заявки от исполнителя» план не называет (в задачах — только view `ticket_new.py`) | 1) `services/executor.py` с `create`, `can_start`, `can_take`, `queue_for_category`; 2) всё в view и `tickets` | вариант 1: проверки (домен, обязательные поля, `take`) нужны сервису, как у `form`; новых функций в `tickets` нет |
| B2-7 | `tickets.update_fields` (6.7, b1) при правке ФИО заявителя не названа среди зовущих `search.rebuild(ticket)`, а T-3125 требует пересборки (`test_search_rebuilt_on_requester_name_edit_in_ticket`); `tickets.create` в 6.7 зовёт только `search.index(ticket)` | 1) дополнить в 6.7 «зовёт `search.rebuild` при смене ФИО»; 2) пересобирает `tickets` сам | вариант 1: правка строки 6.7 за автором b1/Opus; `search.rebuild` объявлена |
| B2-8 | Направление сортировки по критичности (FR-279: «по порядку справочника, затем номер»); у плана направления нет | 1) тот же флаг `descending`, что у остальных, по убыванию высшая критичность первой; 2) всегда по возрастанию `order` | вариант 1: «Высокая» (`order=30`) сверху по умолчанию; переключатель направления един для всех сортировок |
| B2-9 | `listing.badge` при нуле: `0` или `None` (`menu_for` передаёт значение как есть, раздел 3.2) | 1) `0`, скрытие нуля — разметка (раздел 13); 2) `None` | вариант 1: тест счётчика сравнивает число; решение о показе нуля — часть d |
| B2-10 | Модуль ядра `table_file` (T-3137, T-3204) в разделах 1-5 части a не записан | 1) оставить описание в 6.23 (требует `requester_import`); 2) перенести в раздел 3 | вариант 1, перенос в раздел 3 — за Opus: текст готов, меняется только номер раздела |
| B2-11 | Сквозной предел 2000 заявок за ночь у `anonymize_tickets`: порции идут цепочкой заданий | 1) параметр `done_total` у `anonymize_batch`, задание передаёт сумму следующей порции; 2) счётчик в Valkey | вариант 1: состояние в аргументах задания (раздел 7, часть c) |
| B2-12 | `purge_orphan_files`: нужна ли выдержка по возрасту файла, чтобы не стереть файл письма до фиксации записавшей его транзакции | 1) выдержки нет (ночное задание, файл пишется за миллисекунды до фиксации); 2) файл моложе часа не трогать | вариант 1: тесты кладут сироту «сейчас» и ждут стирания (решено иначе: см. блок решений) |
| B2-13 | Итог загрузки заявителей: в разделе 2.2 (часть a) `summary` — пять ключей, план («Подтверждение») требует ещё «сменили отметку на «заявка»: E» | 1) в 6.23 к пяти ключам добавлены `origin_changed`, `not_loaded` и (в предпросмотре) `would_delete`; раздел 2.2 уточняется строкой «сверх этих — ключи 6.23»; 2) убрать лишнее | вариант 1: правку 2.2 делает Opus |
| B2-14 | `tickets.create` (6.7, b1) не принимает копию (`cc`), а участники новой заявки из письма нужны (FR-217, T-3107) | 1) `intake.add_participants` пишет `TicketParticipant` в той же транзакции после `create`; 2) добавить `cc` в `create` | вариант 1: подпись b1 не меняется |
| B2-15 | Коды событий ленты для вложений в разделе 9 (часть c) не названы: `on_found` пишет `attachment_rejected` (архив с паролем) и `attachment_quarantined` | 1) часть c берёт эти имена; 2) часть c называет свои, b2 правит | вариант 1: имена в 6.18 |
| B2-16 | `letters.send` возвращает `None` и создаёт `MailMessage` в `on_commit`: `send_rendered` ставит задание сразу, а запись заявки видна другой транзакции только после фиксации | 1) как записано; 2) вернуть `MailMessage` из внутренней транзакции | вариант 1: тесты ждут `django_capture_on_commit_callbacks(execute=True)` (шапка) |

**Решения Opus по B2-1…B2-16 (2026-10-06).**
- B2-1, B2-6, B2-10 — вариант 1: модули `mail_parse`, `executor`, `listing` и ядро `table_file`
  названы в подписанных задачах; у `table_file` в раздел 3 добавлена ссылка на 6.23.
- B2-2, B2-3, B2-4, B2-5, B2-8, B2-9, B2-11, B2-14, B2-15, B2-16 — вариант 1, как предлагает автор.
- B2-7 — вариант 1: у `tickets.update_fields` (6.7) записано «зовёт `search.rebuild` при смене ФИО».
- B2-12 — вариант 2 (отступление от варианта автора): файлы моложе 1 часа по `mtime` не стираются
  (опрос и ночная чистка идут в разных процессах).
- B2-13 — вариант 1: в 2.2 у `summary` загрузки заявителей дописаны ключи 6.23.

**Что принято без вопроса.** Модуль списка называется `listing` (задача T-3221); имена пресетов в
GET (`mine`, `unassigned`, `my_queues`, `waiting`, `closed`, `all`) часть d берёт в раздел 12 (имя
`all` есть в плане, 1180-1183); код `bad_email` один на формат и домен, как одно сообщение плана
(1048-1049); подсказка поиска «введите хотя бы 2 буквы» — поле `SearchResult.hint`, а не код
отказа; журнал кнопки «Разобрать снова» план не называет, события нет.

### C. Задания, команды стенда, журнал, письма, правки контрактов

Вопросы части c; решены Opus 2026-10-06 (блок под таблицей). Разделы 7-11 приведены в
согласие с решениями; в тексте — пометки «решение Opus C-N».

| № | Суть | Варианты | Что предлагаю |
|---|---|---|---|
| C1 | План (6.7, «Статусы и переходы») велит `set_status` писать событие ленты «статус: было → стало» при любой смене; закрытие, автозакрытие и открытие заново пишут ещё свои события (`closed`, `autoclosed`, `reopened`): в ленте две строки об одном (журнал разведён решением B1-3, лента — нет) | 1) оставить обе (как в 6.7, раздел 9.3); 2) для причин `close`, `autoclose`, `reopen` `status_changed` не писать | вариант 1: записано в 9.3; вариант 2 короче в ленте, но меняет 6.7 и тесты T-3110 «статус: было → стало» у закрытия (решено иначе: отменено итоговой сверкой, F4-2; см. блок решений) |
| C2 | `scan_file` для вложений идёт в очередь `files` без `job_timeout` (`core.tasks.enqueue_scan`), у очереди `DEFAULT_TIMEOUT` 120 с (`config/settings.py`), а `CLAMAV_TIMEOUT` теперь тоже 120 с: задание может быть прервано RQ раньше или одновременно с ответом clamd (вложение до 20 МБ; живой тест T-3120 `test_live_clamd_scan_of_20mb_zip_faster_than_clamav_timeout`) | 1) `enqueue_scan` ставит `job_timeout=300`; 2) `DEFAULT_TIMEOUT` очереди `files` 300; 3) оставить | вариант 1 (одна строка в ядре, срок только у проверки файлов; фото не страдает); решение за Opus, потому что меняет код среза 002 |
| C3 | План («Запуск») называет `purge_orphan_files` «порциями», а 6.24 возвращает число (`int`), `Batch` нет: следующая порция не ставится | 1) один проход, без порций (каталог `inbound/` обходится один раз за ночь); 2) `Batch` и следующая порция | вариант 1: у задания только листинг одного каталога и проверка строк пачками в одном запросе; срок 600 с с запасом (решено иначе: см. блок решений) |
| C4 | Решение 5 задач называет сдвиг `last_ok_at` (`MailboxState`), а у команды `e2e_backdate` в T-3140 только два вида объекта — `<заявка\|письмо>`; без третьего вида приёмке не сдвинуть `last_ok_at` (сценарий пересоздания ящика) | 1) третий вид `mailbox` (`<ref>` — `-`); 2) только `ticket` и `mail`, `last_ok_at` — тест на сервере | вариант 1: записан в 8.2; T-3140 добавляет вид в `helpers_sd.backdate`, прежние два вида не меняются |
| C5 | Спека требует «Имя Фамилия» в письмах «взята в работу», в подтверждении и в подписи ответа; у `core.User` одно поле `full_name`, собираемое «Фамилия Имя Отчество» (`staff_import`, `accounts`) | 1) `letters.short_name(full_name)`: слов два и больше — «второе первое», иначе строка как есть; 2) показывать `full_name` целиком | вариант 1: у учётной записи «Администратор портала» (два слова) выйдет «портала Администратор», на деле у исполнителей ФИО из трёх слов; вариант 2 безопасен, но не по спеке; решение владельца при подписи текстов (решено иначе: см. блок решений) |
| C6 | `Created.after_hours == ""` (6.7): нерабочее время, а даты начала рабочего времени нет (календарь без дней); спека («Заявка поступила в нерабочее время, мы рассмотрим её с <дата и время>») этот случай не называет | 1) строка «Заявка поступила в нерабочее время.» без «мы рассмотрим её с…»; 2) строки нет | вариант 1: заявитель всё же узнаёт, что ответ не придёт сразу; тест `test_confirmation_off_hours_line_only_when_given` проверяет только случай с датой  **Отменено дополнением 6 (раздел 16): действует фраза плана «…в ближайшее рабочее время».** |
| C7 | `SERVICEDESK_MAILBOX` пуст (ящик не настроен), а заявки создаёт исполнитель или форма: что писать в `Reply-To` и в домен `Message-ID` (6.17 берёт домен после «@» адреса ящика) | 1) `Reply-To` не писать, домен `Message-ID` — как даёт `make_msgid` без аргумента; 2) отказывать письму | вариант 1: письма заявителю по заявке исполнителя ходят и без ящика (приём письма не нужен); при пустом ящике форма «закрыта» и так (6.19) |
| C8 | Подписи видов объекта журнала: план называет «справочник» для `sd_dictionary.*` и `client_unit.*` и «загрузка» для `requester_import.completed` (у `org` «загрузка» уже занято `staff_import`); одинаковые подписи у разных кодов делают фильтр журнала неоднозначным | 1) `client_unit` — «подразделение-клиент», `requester_import` — «загрузка заявителей» (раздел 9.1); 2) как в плане, подписи повторяются | вариант 1: разные подписи, код события по-прежнему из плана; видны владельцу на проходе T-3301 (решено иначе: см. блок решений) |
| C9 | `backup` получает пароль владельца схемы «из `.env`, как `migrate`» (план, «Копии»), имя переменной не названо; `test_owner_credentials_only_in_one_shot_migrate_service` проверяет `web`, `worker`, `scheduler` и поэтому новые службы не охватывает; `worker-mail` и `worker-inbox` в тесте тоже не названы | 1) T-3240 выбирает имя (например `PGPASSWORD` из `CRM_OWNER_PASSWORD`) и добавляет `worker-mail`, `worker-inbox` в проверяемый перечень (правка теста в T-3138, п. (5)/(6)); 2) оставить тест как есть | вариант 1 как поправка в T-3138 (пункта нет в перечне 1-12); в 11.1 дана только правка текста CONTRACT.md |

**Решения Opus по C1…C9 (2026-10-06).**
- C1 — отменено итоговой сверкой (F4-2; решение Opus C1 было ошибочным): по plan.md:721-722
  `set_status` при каждой смене статуса, включая закрытие, автозакрытие и открытие заново,
  пишет событие ленты «статус: было → стало»; `closed`, `autoclosed`, `reopened` пишутся сверх
  него (6.7, 6.11, 9.3); журнал по B1-3 остаётся разведённым.
- C2 — принято: `enqueue_scan` ставит задание с `job_timeout=300`; правка кода ядра в Этапе 3.
  Проверяющему контракта: сверить, что ни один тест срезов 001-002 не закрепляет тайм-аут
  задания проверки (если закрепляет — вопрос Opus) (6.18, 7.2).
- C3 — `purge_orphan_files` идёт порциями по 50 файлов в порядке имени с курсором
  `after=<имя файла>`, `Batch(done, more, last)`; выдержка «моложе часа» (B2-12) сохраняется
  (6.24, 7.1).
- C4 — принято: вид `mailbox` у `e2e_backdate` (поле `last_ok_at`) (8.2).
- C5 — «Имя Фамилия» из `User.full_name`: два слова и больше — второе, пробел, первое; одно
  слово — как есть; пустое — пусто (10.3).
- C6 — принято: при пустой дате строка «Заявка поступила в нерабочее время.» (10.3). **Отменено дополнением 6 (раздел 16):**
  план (plan.md:534–536) задаёт фразу «…мы рассмотрим её в ближайшее рабочее время».
- C7 — при пустом `SERVICEDESK_MAILBOX` `Reply-To` не пишется, домен `Message-ID` — домен
  `settings.DEFAULT_FROM_EMAIL` (значение переменной `SMTP_FROM`; уточнено итоговой сверкой,
  F2-1); приём писем это не выключает: «ящик не подключён» — ровно при пустом `IMAP_HOST`
  (6.15, 13.8; уточнено итоговой сверкой, F4-6).
- C8 — по плану: `client_unit` — «справочник», `requester_import` — «загрузка» (9.1).
- C9 — `backup` получает только `DATABASE_MIGRATE_URL` (из `.env`, через `environment`, без
  `env_file`), `backup.sh` зовёт `pg_dump -Fc -d "$DATABASE_MIGRATE_URL"`; у `worker-mail` и
  `worker-inbox` — `DATABASE_MIGRATE_URL: ""`; правка T-3138 не нужна, новые службы закрывает
  тест T-3135 (раздел 1, 11.1).

### D. Маршруты, разметка, тексты (разделы 12-14)

Вопросы части d. Опущенное в плане и спеке, но меняющее поведение страниц; в разделах 12-14
принят вариант автора, пометка — «решение Opus D…». Решения владельца в них не выдаются за
решения Opus. Тексты без источника («текст контракта») — не вопросы: их читает владелец на
ручном проходе T-3301 (решение Opus B1-1).

| № | Суть | Варианты | Что предлагаю |
|---|---|---|---|
| D1 | `/request/done/` без адреса в сессии (второе открытие страницы, прямой заход): план говорит «адрес берётся из сессии и сразу из неё удаляется», что показывать без адреса, не сказано | 1) 302 на `/request/`; 2) 200 «Заявка принята» без адреса; 3) 404 | вариант 1: страница с пустым адресом вводит в заблуждение, а 404 пугает заявителя |
| D2 | Групповое действие (`/tickets/bulk/`) обычным запросом без НХ: план даёт итог «фрагментом», а что отвечать без НХ, не сказано | 1) 200 страница списка с блоком итога; 2) 302 на `/tickets/` и итог через флеш | вариант 1: итог со списком «#номер — причина» не помещается в одно сообщение; тест T-3133 `test_bulk_action_skips_inaccessible_tickets_with_explanation_and_applies_to_accessible` читает его из ответа |
| D3 | Имя файла в `Content-Disposition` при выдаче исходного письма `.eml` (у вложения — имя из заявки) | 1) `mail-<id>.eml`; 2) `ticket-<номер>-<id>.eml` | вариант 1: номер заявки в имени файла не нужен |
| D4 | Диалог снятия отметки очереди: в «Контрактах» плана только `/servicedesk/queues/` (GET, POST) | 1) GET с параметром `unmark=<id узла>` отдаёт диалог, POST с `confirm=1` исполняет; 2) отдельный путь `…/queues/<id>/unmark/` | вариант 1: новых путей нет, строка плана остаётся полной |
| D5 | Правка статуса: вид (`kind`) после создания не меняется (`dictionaries.update` отвечает `TypeError`); как это видно на маршруте | 1) в форме правки поля `kind` нет, присланное маршрут отбрасывает; 2) отказ 200 с `[role=alert]` | вариант 1: серверный тест `test_status_kind_set_on_creation_and_not_changeable` читает сервис, а не маршрут |
| D6 | «Входящие письма»: число по кнопке «показать количество» (в «Контрактах» отдельного маршрута нет) и ответ на «Разобрать снова» для обработанного письма (`mailbox.reparse` возвращает `False`) | 1) параметр `count=1` того же адреса; для обработанного письма — 302 и `[role=status]` «Письмо не ждёт повторного разбора»; 2) отдельный путь `…/inbound/count/` и ответ 200 с `[role=alert]` | вариант 1: у заявок путь `/tickets/count/` есть, у писем план его не называет; повторный разбор обработанного письма не ошибка пользователя |
| D7 | Признак «только сетка» у `/tickets/` (план: «запрос НХ с целью сетки получает только сетку»): как сервер узнаёт цель | 1) заголовок `HX-Target: tickets-grid` (HTMX шлёт идентификатор цели без «#»); 2) отдельный параметр `grid=1` в адресе | вариант 1: адрес со страницы не меняется, «Назад» и ссылка из карточки сотрудника работают (план: параметры фильтра в адресе, `hx-push-url`) |
| D8 | Сообщение об отказе действия, где подтверждение обязательно, но `confirm=1` не пришло (снятие участника, удаление значения справочника, снятие отметки очереди, удаление заявителя) | 1) 200 с `[role=alert]` «Подтвердите действие», как у среза 002 («Подтвердите удаление»); 2) 400 | вариант 1: правило проекта (HTMX не подставляет 4xx) и образец среза 002 (дополнение 21) |

**Решения Opus по D1…D8 (2026-10-06).** Все — как предлагает автор.

## 16. Дополнения Opus по вопросам исполнителей Этапа 2

Ответы Opus на вопросы писателей тестов T-3101…T-3137. Каждый пункт называет, что меняется в разделах 1–15
(«Уточняет»), и тесты, которые он затрагивает («Затрагивает»). При расхождении с разделами 1–15 действует пункт этого
раздела, в том числе над решениями раздела 15; из двух пунктов — с большим номером. Дополнение 1 — в разделе 3.4
(помощник T-3100). Рабочие записи — вне репозитория (crm-work/slice003/stage2/tests/review/: вопросы — questions-*.md,
проверка этого раздела — A-16-*.md).

**Дополнение 2 (волна 1, 2026-10-06). Порядок проверок в маршрутах действий над заявкой.** Маршрут
`/tickets/<номер>/…` (раздел 12.4, в том числе файл и исходное письмо, 12.5) проверяет по порядку: (1) заявку через
`tickets.get_for` — невидимая и несуществующая дают один и тот же 404 раньше всего остального; (2) права, участие и
состояние заявки (`not_participant`, `ticket_closed`, `ticket_open`) — в порядке строки службы раздела 6 (у `take`:
`no_access`, `ticket_closed`, `not_participant`; общее правило — 6.1, «Порядок проверок»); (3) поля формы и `confirm`;
(4) собственный объект маршрута (элемент ленты у `reply/<элемент>/resend/`, вложение у `files/<id>/`) — его 404 идёт
после 404 заявки. Уточняет: 12.4 (вводный абзац), 12.5. Затрагивает: test_sd_access::test_every_ticket_action_route_404_for_foreign_ticket_same_as_missing
и остальные тесты FR-236 в test_sd_access; test_sd_reply::test_resend_*; test_sd_assignment_2::test_closed_ticket_*.

**Дополнение 3 (волна 1, 2026-10-06). `queue_id` у «Другое».** `dictionaries.update(other, …, queue_id=…)` у системной
категории «Другое» поднимает `TypeError` самим наличием ключа, в том числе при `queue_id=None` (как `kind` у статуса и
`is_system` у `create`: «не принимается» в таблице 6.5 значит `TypeError`); у «Другое» `queue` пуст всегда (2.2,
строка `Category`; 6.4 `set_default`). Маршрут `/servicedesk/dictionaries/categories/<id>/edit/` у «Другое» поля выбора
очереди не показывает, присланный ключ `queue` отбрасывает (как `kind`, решение D5) и в `update` не передаёт.
Уточняет: 6.5, строка `update`; 12.6, строка `…/<id>/edit/`. Затрагивает:
test_sd_dictionaries::test_category_other_not_deleted_not_archived_and_has_no_own_queue.

**Дополнение 4 (волна 1, 2026-10-06). Журнал переноса отметки «по умолчанию».** Выбор другого статуса по умолчанию
своего вида (`update(status, is_default=True)`) пишет одно событие `sd_dictionary.updated` — у выбранного статуса, по
общему правилу 9.2: `before` — только изменённые ключи (`{"is_default": false}`, при одновременной смене названия — ещё
`name`), `after` — изменённые ключи плюс `dictionary` и `name`. У статуса, с которого отметка снялась в той же
транзакции, события журнала нет. Уточняет: 6.5, строка `update`; 9.2, строка `sd_dictionary.updated`. Затрагивает:
test_sd_dictionaries::test_default_mark_moves_within_kind_in_one_transaction,
test_sd_audit::test_dictionary_queue_settings_events_were_became_in_russian.

**Дополнение 5 (волна 1, 2026-10-06). Фикстура `settings` — не подмена.** Правило «тест подменяет только точки 3.5»
(строка 64 шапки; вводный абзац 3.5, строка 290) касается кода. Настройки Django тест меняет фикстурой pytest-django
`settings`, как в срезах 001–002: `IMAP_*`, `SERVICEDESK_MAILBOX`, `DEFAULT_FROM_EMAIL`; недоступный почтовый сервер —
`settings.EMAIL_HOST, settings.EMAIL_PORT = "smtp.example.invalid", 2525` (tests/test_mail.py:240,
test_mail_pipeline.py:126–148). Уточняет: шапка (строка 64), 3.5 (строка 290). Затрагивает: test_sd_queues,
test_sd_mailbox, test_sd_reply, test_sd_letters и все тесты, которые меняют настройки.

**Дополнение 6 (волна 1, 2026-10-06). Фраза о нерабочем времени без даты — по плану; решение C6 отменено.** План
(plan.md:534–536, подписан): если `next_working_start` вернул `None`, фраза идёт без даты — «мы рассмотрим её в
ближайшее рабочее время». Решение C6 («Заявка поступила в нерабочее время.» без продолжения) с планом расходится и
отменяется. При `after_hours == ""` строка подтверждения — дословно «Заявка поступила в нерабочее время, мы рассмотрим
её в ближайшее рабочее время.»; при дате — как раньше «…мы рассмотрим её с {after_hours}.» (формат даты — 6.7, строка
593: «ДД.ММ.ГГГГ ЧЧ:ММ» без «с» внутри значения). Уточняет: 10.3, строка `ticket.confirmation` (часть о `""`, исправлена
на месте); 15 C — строка таблицы C6 и строка «C6 — принято» (помечена отменённой). Затрагивает:
test_sd_create::test_after_hours_phrase_unloaded_year_saturday_calendar_change_and_none_date — он проверяет дословную
фразу при `""` (через `mail_text`); T-3118 test_sd_letters::test_confirmation_off_hours_line_only_when_given — случай
`""` по желанию исполнителя. Приёмка e2e/test_d13_night случая без даты не содержит и не меняется.

**Дополнение 7 (волна 1, 2026-10-06). Ответственный при создании: лента и журнал пишутся, шина — нет.** Строка 6.8
`apply_default_assignee` «`tickets.create` назначает ответственного сам: без письма и без события `assignee_changed`»
говорит о событии **шины** `servicedesk.assignee_changed` (3.1; 6.13, строка `assignee_changed`: «`tickets.create` не
зовёт»): при создании шина получает только `ticket_created` (с `assignee_after_id`). При создании с `take_by` или с
ответственным по умолчанию категории `tickets.create` пишет: событие **ленты** `assignee_changed` («ответственный: было
→ стало», `before` `""`, `after` — имя, `before_id` `None`, `after_id`; 9.3), одно, сразу после первого элемента
`incoming`, со временем `at` создания (тесты порядок не проверяют, если имя теста его не называет); журнал
`ticket.assigned` (9.2: `actor` — `take_by`, у ответственного по умолчанию — `None`; `before` `{"assignee": "",
"assignee_id": None}`). Уточняет: 6.7, строка `create` (колонка записи); 6.8, строка `apply_default_assignee`; 6.13, строка
`assignee_changed` (подтверждается: `tickets.create` не зовёт); 9.2, строка `ticket.assigned` (при создании `before` —
`{"assignee": "", "assignee_id": None}`).
Затрагивает: test_sd_create::test_category_default_assignee_set_when_queue_member_status_in_progress_assigned_once;
test_sd_assignment::test_category_default_assignee_assigned_on_creation_when_still_queue_member,
test_taken_letter_not_sent_on_creation_with_assignee; test_sd_letters::test_no_assigned_letter_when_assignee_set_at_creation;
test_sd_form::test_default_assignee_of_category_gives_in_progress_and_single_confirmation;
test_sd_executor::test_take_to_self_makes_assignee_in_progress_and_single_confirmation_with_name;
test_sd_audit::test_assign_transfer_update_events_were_became; test_sd_boundaries; приёмка e2e/test_d02_form,
e2e/test_d07_phone.

**Дополнение 8 (волна 1, 2026-10-06). Решение A1: поставленное задание читать можно.** Тест, которому решение A1
разрешает фикстуру `clock` (час суток), может читать поставленное, но не исполненное задание очереди (`job.meta`,
`job.kwargs`; раздел 7.3): время постановки RQ берёт сам, контекст письма считается при создании. Исполнять задание
(`perform`, рабочий процесс) под `clock` нельзя. Уточняет: шапка (строки 45–51), 15 A, решение A1 (и его
повтор в списке решений). Затрагивает: три
теста FR-254 в test_sd_create, T-3118 test_sd_letters::test_confirmation_off_hours_line_only_when_given, T-3122
test_sd_executor::test_confirmation_has_consent_line_and_no_off_hours_phrase.

**Дополнение 9 (волна 1, 2026-10-06). Связь заявок без доступа к другой заявке.** «Иначе текст без ссылки» (13.3,
строка «связи заявок»): у того, кому другая заявка не видна, остаётся элемент `[data-field="previous"]` (у новой) или
`[data-field="continuation"]` (у закрытой) — не `<a>`, без `href`, с тем же текстом «продолжение заявки #N» или
«продолжение — заявка #N». Тест ищет номер целым числом (`#N` без цифры после). У заявки без связи элементов `previous` и `continuation` нет
вовсе (исключение из правила `data-empty` строки «поля» 13.3, как `closed-by` только у закрытой). Уточняет: 13.3,
строки «поля» и «связи заявок». Затрагивает: test_sd_create::test_continuation_link_hidden_from_user_without_access_to_target,
test_sd_closing_2::test_continuation_link_opens_only_for_those_with_access_to_old_ticket.

**Дополнение 10 (волна 1, 2026-10-06). Имя сотрудника в журнале и данных ленты.** В `before`/`after` журнала (9.2:
`assignee`, `closed_by` и др.) и в `data` событий ленты (9.3: `before`, `after`) имя сотрудника — `User.full_name`
целиком. Правило «Имя Фамилия» (10.3, решение C5) — только в письмах и в подписи «Закрыл: Имя Фамилия» (14.2).
Подпись события в ленте (14.5) показывает те же значения `data`. Уточняет: 9.2, 9.3. Затрагивает: test_sd_create,
test_sd_reconcile, test_sd_assignment, test_sd_card, test_sd_audit.

**Дополнение 11 (волна 1, 2026-10-06). «Закрыл» в карточке; текст событий ленты.** (а) Поле карточки
`[data-field="closed-by"]` показывает подпись `[data-field-label]` «Закрыл:» и имя по правилу «Имя Фамилия» (14.2,
строка «Закрыл: Имя Фамилия»): текст элемента после схлопывания пробелов содержит «Закрыл: <Имя Фамилия>», у
уволенного рядом «(уволен)»; в списке — та же строка в ячейке ответственного. (б) `TicketEntry.text` у элементов вида
`event` тесты не проверяют: подпись события собирает карточка из `event` и `data` (14.5). Уточняет: 13.2 (ячейка «ответственный», строка 1736), 13.3, 14.2 (строка «Закрыл: Имя Фамилия», 1952: имя — из
`closed_by.full_name` по правилу C5).
Затрагивает: test_sd_reconcile::test_closed_by_name_kept_in_card_and_list_after_assignee_removed,
test_removed_assignee_leaves_feed_event_journal_entry_and_bus_event; test_sd_list_2::test_closed_without_assignee_shows_closed_by_name;
test_sd_card::test_closed_ticket_card_shows_who_closed.

**Дополнение 12 (волна 1, 2026-10-06). Диалог снятия отметки очереди.** В `[data-dialog="queue-unmark"]` по одному
`[data-consequence]` на каждую категорию, которая перейдёт в очередь по умолчанию (её название — в тексте элемента);
число открытых заявок — текстом диалога вне `[data-consequence]` (целым числом). Без категорий `[data-consequence]` нет.
Уточняет: 12.6, строка `/servicedesk/queues/` (строка 1709 о `[data-consequence]` диалогов не меняется). Затрагивает:
test_sd_queues::test_unmark_dialog_names_affected_categories_and_journal_gets_update_per_category,
e2e/test_d09_settings.

**Дополнение 13 (волна 1, 2026-10-06). Домены, не приводимые к `xn--`.** `settings.parse_domains` отказывает
`bad_domain` и тогда, когда домен не кодируется в IDNA (метка длиннее 63 знаков, `UnicodeError` кодека `idna`), — как
`intake` считает такой домен чужим (6.16); длина меток проверяется после кодека и у готового `xn--…` (решение Opus).
`settings.accepts_domain` на таком домене возвращает `False` и исключения не поднимает. Уточняет: 6.6, строки
`parse_domains` и `accepts_domain`. Затрагивает:
test_sd_queues::test_domains_invalid_form_refused (добавить такой домен в список плохих).

**Дополнение 14 (волна 2, 2026-10-06). Ошибка записи файла письма при опросе.** План (plan.md:588–590) говорит только
«ошибка записи файла откатывает транзакцию: письмо будет забрано на следующей минуте»; остальное — решение Opus.
`OSError` из `mailbox.write_raw` `poll` не поднимает: транзакция этого письма откатывается (строки `InboundMail` нет, `last_uid` прежний), запуск
заканчивается (следующие письма в этот запуск не берутся), `MailboxState.last_error` и лог получают текст через
`tasks.safe_error`, `PollResult.state == "unavailable"`; следующий запуск берёт тот же UID (plan.md:588–590: «письмо
будет забрано на следующей минуте»). `write_raw` сам создаёт каталог `PROTECTED_ROOT/inbound/`, если его нет. `PollResult.fetched` считает письма,
сохранённые в этом запуске до ошибки (их задания разбора уже поставлены после их фиксации); запуск ставит
`last_poll_at` и `last_error`, `last_ok_at` не трогает. Уточняет: 6.15, строки `poll` (колонка «Отказ»: `OSError` от
`store` ловится), `store`, `write_raw`. Затрагивает: test_sd_mailbox::test_file_write_error_rolls_back_and_same_uid_retried,
test_inbound_row_and_last_uid_saved_in_one_transaction.

**Дополнение 15 (волна 2, 2026-10-06). `skipped` у `mailbox.recreated`.** `after["skipped"]` — число писем, которые
окно по времени отобрало, но отбор отбросил, потому что их `Message-ID` уже есть во входящих (plan.md:570–573); счёт
ведётся при отборе, независимо от того, скачает ли письмо позже обычный порядок (5.1, строка 369: письмо с UID выше
нового `last_uid` будет скачано как новое). Письма старше окна в это число не входят. Тест кладёт «известное» письмо
с UID меньше нового (строка 366) — тогда оно и отброшено, и не скачано. Уточняет: 9.2, строка `mailbox.recreated`. Затрагивает:
test_sd_mailbox::test_recreated_mailbox_writes_mailbox_recreated_journal (точное число), test_sd_imap_live (наличие и
тип).

**Дополнение 16 (волна 2, 2026-10-06). Связь письма с элементом ленты.** Поля `InboundMail.entry` нет: связь — поле
`TicketEntry.inbound` (plan.md:349; 2.2, строка `TicketEntry`: `related_name="entries"` у `InboundMail`). Слова 6.16
«`InboundMail.ticket`, `entry`, … — шаг `finish`» значат: шаг `finish` ставит `InboundMail.ticket` и
`TicketEntry.inbound` у элемента `incoming`, созданного из письма; тест читает элемент как `inbound.entries.get()`
(или `TicketEntry.objects.get(inbound=inbound)`). У отклонённых и автоматических писем элементов нет, `status` —
`processed`; у ждущих настройки — `status="waiting_setup"`. Уточняет: 6.16 (строка `process`, 782: «`entry`» читать как
`TicketEntry.inbound`; абзац о шаге `finish`, 793). Затрагивает: test_sd_intake (`inbound.entry` →
`inbound.entries.get()`, `inbound.entry_id is None` → `not inbound.entries.exists()`),
test_sd_attachments::test_source_eml_*.

**Дополнение 17 (волна 2, 2026-10-06). Адрес с кириллическим доменом.** Домен отправителя сравнивается со списком
доменов в форме IDNA (`xn--…`, 6.6, 6.16); сам адрес в `Requester.email` и `Ticket.requester_email` хранится как пришёл
в письме (строчными), домен не перекодируется. Так же `requesters.normalize_email` (форма, заявка от исполнителя):
формат — `django.core.validators.validate_email` (IDN-домены принимает), домен — после приведения к IDNA в списке,
адрес хранится строчными как введён. Два написания одного домена (`…@пример.рф` и `…@xn--…`) — две записи заявителя
(FR-261 требует уникальности без учёта регистра, не написания домена; решение Opus). Уточняет: 6.16, 6.22
(`normalize_email`). Затрагивает:
test_sd_intake::test_cyrillic_domain_matched_via_xn_and_unconvertible_domain_foreign.

**Дополнение 18 (волна 2, 2026-10-06). Тема в результате разбора.** `mail_parse.parse(raw).subject` — уже
`clean_subject(...)` темы письма (переводы строк, табуляции и управляющие знаки — пробел, пробелы сжаты, края обрезаны,
до 255 знаков): решение 14 задач — очистка темы относится к любой заявке, в том числе из письма. `tickets.create`
зовёт `clean_subject` ещё раз (повторная очистка ничего не меняет). Уточняет: 6.14, строки `ParsedMail`, `parse`.
Затрагивает: test_sd_mail_parse::test_subject_cleaned_of_line_breaks_and_control_chars, test_sd_intake (тема
заявки из письма), test_sd_letters::test_subject_is_number_and_ticket_subject_with_control_chars_cleaned.

**Дополнение 19 (волна 2, 2026-10-06). Шаги разбора зовутся все.** Для письма, прошедшего проверки (`checks` вернул
`None`), `intake.process` зовёт все шаги `STEPS` по порядку (`parse`, `checks`, `link`, `ticket`, `attachments`,
`finish`); `attachments` — и при пустом списке частей. Письмо, отклонённое проверками (`rejected_*`, `auto`), и
письмо, ждущее настройки, после `checks` идут сразу в `finish`. Уточняет: 3.5 (строка «шаги разбора письма»), 6.16
(строка `process`). Затрагивает: test_sd_intake::test_error_on_any_step_rolls_back_marks_parse_error_last_error_step_and_class_only.

**Дополнение 20 (волна 2, 2026-10-06). Повтор адреса в копии.** `mail_parse.cc_pairs` и `intake.corporate_cc` при
повторе адреса (без учёта регистра) оставляют одну пару: адрес — строчными, имя — первое непустое среди повторов
(пустое, если имени нет ни у одного). Уточняет: 6.14, строка `cc_pairs`; 6.16, строка `corporate_cc`. Затрагивает:
test_sd_intake::test_cc_corporate_addresses_become_participants_excluding_mailbox_smtp_from_requester_duplicates,
test_sd_mail_parse::test_cc_addresses_collected_from_all_cc_headers.

**Дополнение 21 (волна 3, 2026-10-06). Одно событие журнала на правку полей.** Один вызов `tickets.update_fields`
(маршрут `fields/`, групповое «критичность») пишет одно событие `ticket.updated` на заявку: `before`/`after` — все
изменённые поля этого вызова (9.2, строка `ticket.updated`); ничего не изменилось — события нет. Уточняет: 6.7, строка
`update_fields`; 9.2. Затрагивает: test_sd_assignment_2::test_criticality_and_complexity_edit_write_event_per_field
(события ленты — по одному на поле, журнал — одно), test_requester_name_edit_event_has_no_values, test_sd_audit.

**Дополнение 22 (волна 3, 2026-10-06). Снятие ответственного передачей, сменой категории и открытием.** План
(plan.md:754–756: «каждое назначение, смена и снятие ответственного — событие ленты») распространяется и на снятие,
которое делают `transfer.transfer`, `transfer.change_category` (ответственный не участник новой очереди) и
`closing.reopen`: событие ленты `assignee_changed` (`before` — имя, `after` `""`, `before_id`, `after_id` `None`)
пишется после события `transferred`, `queue_changed` или `category_changed` того же действия; журнал —
`ticket.assignee_removed` с `reason="queue_changed"`; шина — `assignee_changed`. Сверка (`reconcile`) пишет своё событие
`assignee_reconciled`, не `assignee_changed` (9.3). Уточняет: 9.3, строка `assignee_changed`; 6.9; 6.11, строка
`reopen`. Затрагивает: test_sd_assignment::test_transfer_removes_assignee_not_in_new_queue_keeps_member,
test_category_change_removes_assignee_not_in_new_queue; test_sd_assignment_2::test_group_transfer_unassigns_non_member_of_new_queue;
test_sd_closing_2::test_reopen_without_assignee_when_assignee_dismissed (если ответственный ещё стоит).

**Дополнение 23 (волна 3, 2026-10-06). Имя автора в ленте.** «Имя сотрудника» в `[data-author]` (13.4, строка «время и
автор») — `User.full_name` целиком, как в данных событий (дополнение 10); правило «Имя Фамилия» — только в письмах и
«Закрыл:». Уточняет: 13.4. Затрагивает: test_sd_card::test_feed_authors_staff_name_dismissed_mark_requester_and_participant_address,
test_sd_assignment::test_transfer_event_who_from_to_reason_and_journal_without_reason.
