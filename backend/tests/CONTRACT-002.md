# Контракт имён тестов Этапа 2 среза 002 (T-2101…T-2150)

Тесты написаны до кода и задают имена, которых нет в PLAN-002. Реализация (Этап 3) берёт их
отсюда. Имена плана (модели и поля раздела «Модель данных», маршруты «Контрактов», коды событий
таблицы «Журнал», `perms:<id>`, очередь `files`, девять точек расширения (в срезе 003 их тринадцать, CONTRACT-003 § 3.2), `Unit`, `Membership`,
`UnitRole`, `WorkCalendar`, `CalendarYear`, `SpecialDay`, `CalendarUpload`, `StaffImport`,
`StoredFile`) здесь не повторяются и не меняются, кроме случаев, когда тест уточняет их форму
(такие строки помечены «уточнение»). Имена среза 001 из `tests/CONTRACT.md` не меняются.

Помощники тестов: `tests/support_org.py` (пишет T-2100b) и `tests/e2e/helpers_org.py` (пишет
T-2140). В колонке «Тесты» стоят файлы или задачи, которые берут имя. Рабочая запись автора
контракта лежит вне репозитория.

Правила для всех тестов среза:
- пароли — только `secrets.token_urlsafe()` (помощник `factories.new_password()`), секреты в
  файлах и ответах — только `***`;
- строка EICAR собирается из частей при запуске (помощник `support_org.eicar_bytes()`), целиком
  в репозитории не лежит;
- проверки сброса ключей `perms:<id>` и номера версии календаря идут внутри
  `with django_capture_on_commit_callbacks(execute=True):` (решение 11 задач); фикстура
  подключается параметром теста;
- тесты ходят по путям из плана, а не по именам маршрутов;
- постановка заданий в очередь (`scan_file`, `requeue_pending_scans`, письма приглашений) тоже
  проверяется внутри `with django_capture_on_commit_callbacks(execute=True):`;
- имена кода среза 002 тесты импортируют внутри функций теста (или через `support.model`), а не
  на уровне модуля: сбор (`--collect-only`) должен проходить до появления кода;
- подменяются только названные здесь точки: `clamav.services.scan` (раздел 3),
  `socket.create_connection` в `apps.integrations.clamav.client` (только T-2109) и
  `apps.core.services.accounts.create_user` (только тесты загрузки сотрудников: `staff_import`
  вызывает службу через модуль, дополнение 31); время —
  фикстурой `clock` из `tests/conftest.py` или явными аргументами `today=`, `now=`.

## 1. Среда запуска

| Что | Требование | Тесты |
|---|---|---|
| Служба `clamav` | в `deploy/docker-compose.yml` в основном наборе (без профиля); у `test` в `depends_on`: `clamav` с `condition: service_healthy`, без `required: false` (решение 3); образ `clamav/clamav:1.4.6`; порт 3310 только внутри сети; том `clamav-db` смонтирован на `/var/lib/clamav` (каталог баз образа, дополнение 40); проверка здоровья `["CMD", "clamdcheck.sh"]`, `interval: 10s`, `timeout: 5s`, `retries: 6`, `start_period: 120s` (источник — docs/reviews/TASKS-002.md, «Решения Opus по итогам T-2001», п. 1, 3, 4) | test_deploy_files::test_clamav_service_pinned_internal_port_healthcheck_and_volume, test_test_service_waits_for_healthy_clamav; test_clamav_live |
| `CLAMAV_HOST`, `CLAMAV_PORT`, `CLAMAV_TIMEOUT` | значения по умолчанию: `clamav`, `3310`, `120` (секунд); задаются в `environment` служб `web`, `worker`, `worker-mail`, `worker-inbox`, `test` в compose; в `deploy/.env.example` перечислены закомментированными (`# CLAMAV_HOST=clamav`, `# CLAMAV_PORT=3310`, `# CLAMAV_TIMEOUT=120`; тест среза 001 `test_env_example_has_only_placeholders` принимает такие строки (правка T-2119, п. 10 — решение Opus): имена, которые читает `settings.py`, считаются описанными и в виде закомментированной строки `# ИМЯ=значение`, а `PLAN_ENV_NAMES` и `SECRET_ENV_NAMES` по-прежнему должны стоять незакомментированными; правку теста делает исполнитель T-2119); `config/settings.py` читает их в `settings.CLAMAV_HOST` (str), `settings.CLAMAV_PORT` (int), `settings.CLAMAV_TIMEOUT` (int) при запуске; адаптер читает `settings` при каждом вызове, а не при импорте (CONTRACT-003 § 1) | test_deploy_files::test_clamav_env_defaults_in_compose_commented_in_env_example; test_clamav_adapter::test_host_port_timeout_from_environment_with_defaults |
| `deploy/clamav/freshclam.conf` | файл смонтирован bind-ом только для чтения (`:ro`) на `/etc/clamav/freshclam.conf` в контейнер `clamav`; в нём ровно пять действующих строк файла образа 1.4.6 (решение 4 по T-2001, docs/reviews/TASKS-002.md, «Решения Opus по итогам T-2001»): `UpdateLogFile /var/log/clamav/freshclam.log`, `DatabaseOwner clamav`, `DatabaseMirror database.clamav.net`, `ScriptedUpdates yes`, `NotifyClamd /etc/clamav/clamd.conf`; ниже — закомментированный пример `PrivateMirror`; переменных `FRESHCLAM_CONF_*` в compose нет; из `CLAMD_CONF_*` есть только `CLAMD_CONF_AlertEncryptedArchive: "yes"` в `environment` службы `clamav` (CONTRACT-003 § 1) | test_deploy_files::test_freshclam_conf_mounted_with_default_mirror (правка — п. (9) T-3138) |
| worker | команда `rq worker -c config.rq_settings --with-scheduler files` (только очередь `files`), `deploy: replicas: 2`; том `protected` на тот же путь, что у `web` (`/app/protected`); очереди `mail maintenance` и `inbox` — службы `worker-mail` и `worker-inbox` с тем же томом | test_deploy_files::test_worker_listens_files_before_mail_and_mounts_protected (правка — п. (6) T-3138) |
| nginx | в `nginx.conf` и `nginx.prod.conf`: `client_max_body_size 6m;`; `location /protected/` с `internal;`, `alias /srv/protected/;` и заголовками `X-Content-Type-Options "nosniff"`, `Cache-Control "private, max-age=86400"` (с `always` или без), тип `image/jpeg` — любым способом: `default_type`, `types` или `add_header Content-Type` (дополнение 41); `client_max_body_size 6m;` остаётся общим в `http`; `55m` — только в двух `location` формы и ответа (`= /request/`, `~ ^/tickets/(new/\|[0-9]+/reply/)$`); общий `location /protected/` для фото не меняется; перед ним — `/protected/attachments/` и `/protected/inbound/` (CONTRACT-003 § 1) | test_deploy_files::test_nginx_body_size_6m_and_protected_location_internal_with_headers (правка — п. (10) T-3138) |
| cron | `config/cron.py` регистрирует три новых задания, очередь `mail`: `purge_import_previews` (`40 3 * * *`), `purge_quarantine` (`50 3 * * *`), `requeue_pending_scans` (`0 * * * *`); имя задания — `name=` в `register`; функции — раздел 3; три прежних задания среза 001 и эти три остаются; срез 003 добавляет восемь заданий (CONTRACT-003 § 1 и 7), всего в файле четырнадцать вызовов `register`; шесть прежних — без изменений | test_deploy_files::test_cron_registers_preview_purge_quarantine_cleanup_and_scan_requeue (правка — п. (11) T-3138; владелец её не разрешил 2026-10-06, тест пока ждёт шесть вызовов — решение до Этапа 3) |
| Что монтирует `test` | как в срезе 001: `../backend` в `/app/backend`, `../deploy` в `/app/deploy:ro`. Репозиторий целиком не монтируется: тестам развёртывания нужны только `deploy/` и `backend/` (`repo_file("deploy", ...)`, `repo_file("backend", ...)`) | test_deploy_files, test_stack |
| Фикстуры календаря | `backend/tests/fixtures/calendar/`: `cal2024.csv`, `cal2025.csv`, `cal2026.csv`, `cal2027.csv` (по одному году, настоящие), `years_2024_2027.csv` (все четыре года в одном файле), `bad_totals_2026.csv` (итоги не сходятся), `cp1251_2026.csv` (не UTF-8), `extra_column_2026.csv` (19 колонок), `missing_column_2026.csv` (17 колонок); описание и итоги — `SOURCE.md` там же. Помощник `support_org.calendar_fixture(name) -> bytes` читает файл по имени | test_calendar_file |
| Каталог тома `protected` | настройка `settings.PROTECTED_ROOT` (`pathlib.Path`, по умолчанию `BASE_DIR.parent / "protected"`, то есть `/app/protected`); тесты подменяют её на `tmp_path` фикстурой `protected_root` (пишет T-2100b, лежит в `tests/conftest.py`) | test_photo, test_org_dismissal, test_deploy_files |
| Очередь `files` | `RQ_QUEUES["files"]` в `config/settings.py` (как `mail`: `URL: VALKEY_URL`, `DEFAULT_TIMEOUT: 120`); Valkey тестов — база 15, чистится автоматически (`valkey_clean`), поэтому очередь между тестами пуста | test_photo |
| Сторонние пакеты | `requirements*.txt` содержит `openpyxl` и `defusedxml` (Pillow уже есть с среза 001) | test_stack::test_requirements_include_slice_002_packages, test_openpyxl_uses_defusedxml |

## 2. Модели и поля сверх плана

Метки приложений: `core.*` и `org.*` (`apps.org` получает метку `org`). Значения `choices`
сравниваются тестами как строки; в модели они объявлены вложенными `TextChoices` с теми же
значениями (`UserState.DISMISSED`, `Unit.Kind`, `Membership.Mark`, `StoredFile.Status`,
`StoredFile.Purpose`, `SpecialDay.Kind`, `SpecialDay.Origin`, `CalendarUpload.State`,
`StaffImport.State`, `StaffImport.FileFormat`).

| Имя | Что | Тесты |
|---|---|---|
| `UserState.DISMISSED` | значение `"dismissed"`, название «уволен»; `STATE_TITLES["dismissed"] == "уволен"` в `audit_labels` (уточнение) | test_accounts::test_user_states_invited_active_blocked_only, test_org_dismissal |
| `User.is_active` | ложно при `state` равном `"blocked"` или `"dismissed"` (уточнение) | test_org_dismissal |
| `User.dismissed_by` | `related_name="dismissed_users"` | test_org_dismissal |
| `User.photo`, `User.photo_pending` | `related_name="+"`; у нового пользователя `None` | test_photo, test_staff_card |
| `User.birth_date` | `datetime.date` или `None`; хранится полностью | test_staff_card |
| `StoredFile.owner` | `related_name="stored_files"`; `null=True`: у назначения `attachment` владельца нет (CONTRACT-003 § 2.2) | test_photo |
| `StoredFile.purpose` | `"photo"` или `"attachment"` (CONTRACT-003 § 2.2) | test_photo |
| `StoredFile.status` | `"pending"`, `"clean"`, `"quarantine"` | test_photo |
| `StoredFile.id` | `uuid.UUID`; в адресах, именах файлов и аргументах задания — `str(id)` в обычном виде с дефисами | test_photo |
| `StoredFile.content_type` | до 255 знаков: у фото `"image/png"` или `"image/jpeg"` (по содержимому), у вложения — тип из письма или загрузки | test_photo |
| `StoredFile.attempts` | число попыток проверки; растёт на 1 при каждом `ScanUnavailable` | test_photo::test_unavailable_clamd_retries_24_times_with_plan_intervals_portal_keeps_working |
| `Unit.kind` | `"department"`, `"team"` | test_org_structure |
| `Unit.parent` | `related_name="children"`; у корня `None` | test_org_structure, test_org_heads |
| `Unit.name_key` | `name` без крайних и повторных пробелов, в нижнем регистре, «ё» заменена на «е»; обновляется сервисом при каждой смене `name` | test_org_structure::test_unit_name_required_and_unique_per_parent_case_and_yo_insensitive |
| `Unit.path` | `"/1/5/9/"`: номера от корня до узла, с ведущим и замыкающим `/`; `depth` корня 0; поле объявлено с `db_collation="C"`, порядок «по `path`» везде — байтовый, как `sorted()` (дополнение 1) | test_org_structure::test_move_subtree_paths_depths_members_and_heads_kept |
| `Membership.user` | `related_name="memberships"` | test_org_membership, test_org_heads |
| `Membership.unit` | `related_name="memberships"` | test_org_membership |
| `Membership.created_by` | `related_name="+"` | test_org_membership |
| `Membership.mark` | `""` (нет), `"head"`, `"deputy"`; пустая строка, не `None` | test_org_membership, test_org_heads |
| `UnitRole.unit`, `UnitRole.role` | `related_name="unit_roles"` у обоих | test_org_permissions |
| `WorkCalendar.work_weekdays` | `list[int]`, по возрастанию, без повторов, значения 0…6; по умолчанию `[0, 1, 2, 3, 4]` | test_calendar |
| `WorkCalendar.day_start`, `day_end` | `datetime.time`; по умолчанию `time(9, 0)` и `time(18, 0)` | test_calendar |
| `WorkCalendar.objects.get()` | строка одна всегда; вторую создать нельзя: ограничение базы, попытка даёт `IntegrityError` (`WorkCalendar.objects.count() == 1`; дополнение 28) | test_calendar::test_one_calendar_defaults_mon_fri_9_to_18_monday_first |
| `CalendarYear.totals` | словарь с пятью ключами `holidays_on_weekdays`, `moved_days_off`, `moved_workdays`, `short_days`, `work_days` (целые) | test_calendar_file, test_calendar |
| `CalendarYear.loaded_by` | `related_name="+"` | test_calendar_file |
| `SpecialDay.kind` | `"holiday"`, `"day_off"`, `"workday"`, `"short"` | test_calendar, test_calendar_file |
| `SpecialDay.origin` | `"file"`, `"manual"` | test_calendar_file::test_preview_counts_warns_about_manual_days_and_changes_nothing |
| `CalendarUpload.state` | `"preview"`, `"applied"` | test_calendar_file |
| `CalendarUpload.days` | список словарей `{"date": "ГГГГ-ММ-ДД", "kind": "<SpecialDay.kind>"}` по возрастанию даты | test_calendar_file |
| `CalendarUpload.totals` | те же пять ключей, что у `CalendarYear.totals` | test_calendar_file |
| `StaffImport.state` | `"preview"`, `"done"` | test_staff_import_run |
| `StaffImport.file_format` | `"csv"`, `"xlsx"` | test_staff_import_file |
| `StaffImport.rows` до выполнения | список словарей, по порядку строк файла (без заголовка); ключи: `number` (номер строки данных, с 1), `email` (после обрезки пробелов, в нижнем регистре), `last_name`, `first_name`, `middle_name`, `position`, `phone`, `internal_phone`, `workplace`, `unit_path` (строка, как в файле), `head` (`True`/`False`), `result` (`"will_create"`, `"skipped"`, `"error"`), `code` (код причины, пустая строка у `will_create`), `reason` (текст по-русски, пустая строка у `will_create`), `hint` (`""` или `"dismissed"`) | test_staff_import_run |
| `StaffImport.rows` после выполнения | остаются только ключи `number`, `email`, `result` (`"created"`, `"skipped"`, `"error"`), `reason` (у `created` — пустая строка, дополнение 27; без `code`, как plan.md:200) | test_staff_import_run::test_rows_trimmed_after_done_unconfirmed_preview_purged_after_day |
| `StaffImport.summary` | ключи `created`, `skipped`, `errors`, `units_created` (целые; до выполнения — ожидаемые числа), `not_loaded` (список названий лишних колонок), `new_units` (список путей «ИТ-отдел / Сеть», каждый один раз; только до выполнения, после выполнения ключа нет) | test_staff_import_run, test_staff_import_file |
| `CalendarUpload.created_by`, `StaffImport.created_by` | `related_name="+"` | test_calendar_file, test_staff_import_run |

Контактные значения структуры данных вне БД:
- `PersonRef` — `dataclass(frozen=True)` с полями `id: int`, `full_name: str`, `position: str`;
- `UnitRef` — `dataclass(frozen=True)` с полями `id: int`, `name: str`, `kind: str`, `path: str`
  (`Unit.path`, «/1/5/9/»; название пути через « / » в `UnitRef` не хранится);
- `HeadsOf` — `dataclass(frozen=True)`: `unit: UnitRef`, `heads: list[PersonRef]` (по `full_name`,
  затем `id`, без повторов),
  `source: UnitRef | None` (узел, где руководители найдены; `None`, если не найдены);
- все три лежат в `apps/org/services/refs.py` и доступны как `apps.org.services.PersonRef` и т. д.

## 3. Службы ядра (новые и изменённые)

Новые аргументы `actor` и `ip` везде именованные (`*, actor, ip=None`), как у служб среза 001.
Службы прав не проверяют: право проверяет представление.

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `accounts.dismiss` | `dismiss(user, *, actor, ip=None) -> None`, в одной транзакции: состояние `dismissed`, `dismissed_at`, `dismissed_by=actor`, `blocked_from=""`, `blocked_reason=""`; гасит все ссылки (`links.revoke(user)`); закрывает все сессии (`sessions.close_all(user)`); снимает личные роли (`user.roles.clear()`); письма нет; событие `user.dismissed`. Порядок отказов: себя (`AccountError`) → уже уволенного (`AccountError`) → последнего администратора (`RoleError`, через `guard_last_admin(user, action="уволить его")`) | test_org_dismissal |
| `accounts.rehire` | `rehire(user, *, actor, ip=None) -> None`: только из `dismissed`, иначе `AccountError`; состояние `invited`; `set_unusable_password()`; удаляет `EncryptedTOTPDevice`, `BackupCodeDevice` (с кодами) и `KnownDevice` записи; `dismissed_at=None`, `dismissed_by=None`; роли — ровно `[roles.staff_role()]`; затем `links.send_invitation(user, created_by=actor, ip=ip)`. История паролей остаётся. События по порядку: `user.rehired`, `invitation.sent` | test_org_dismissal::test_rehire_* |
| `accounts.pickable` | `pickable(query: str = "") -> QuerySet[User]`: записи в состояниях `invited`, `active`, `blocked` (не `dismissed`), сортировка по `full_name`, `id`; пустой `query` — все; иначе вхождение `query` без учёта регистра и «е/ё» в `full_name`, `position`, `email`; срез по числу делает вызывающий | test_org_membership::test_candidates_exclude_dismissed, test_org_dismissal::test_dismissed_not_offered_in_any_person_picker |
| `roles.staff_role` | `staff_role() -> Role`: начальная роль (`is_builtin=True`) с названием `roles.STAFF_ROLE_NAME == "Сотрудник ИТ"`; нет роли — `RoleError`. `STAFF_ROLE_NAME` — новая константа рядом с `ADMIN_ROLE_NAME` | test_org_dismissal, test_staff_import_run |
| `roles.guard_last_admin` | уточнение: берёт `select_for_update()` строк действующих администраторов (в запросе есть `FOR UPDATE`); сигнатура и текст отказа не меняются | test_org_dismissal::test_guard_last_admin_locks_active_admin_rows |
| `roles.delete_role` | уточнение: перед удалением вызывает зарегистрированные `role_usage`; `role_usage` вызывается после проверки среза 001 `role.users.exists()` («роль назначена сотрудникам»); первая непустая причина становится текстом `RoleError`; без `org` поведение среза 001 | test_org_permissions::test_role_assigned_to_unit_cannot_be_deleted |
| `roles.set_user_roles`, `accounts.update_profile`, `accounts.block`, `accounts.reset_second_factor` | уточнение: над записью в состоянии `dismissed` бросают `AccountError` (у `set_user_roles` — `RoleError`) и ничего не меняют; `block` уволенной тоже (`unblock` — поведение среза 001: над незаблокированной записью тихо ничего) | test_org_dismissal::test_dismissed_card_read_only_except_rehire_and_photo_delete |
| `accounts.update_profile` | уточнение: допустимые поля `PROFILE_FIELDS` дополняются `internal_phone` и `workplace`; поле `birth_date` — `AccountError` («Дату рождения меняет только сам сотрудник.»); новые поля пишут `user.updated` с ключами этих полей | test_staff_card::test_admin_form_has_no_birth_date_and_direct_post_refused |
| `accounts.update_own_profile` | `update_own_profile(user, *, phone, contacts, internal_phone, workplace, birth_date, ip=None) -> User`: сотрудник правит свои поля; `birth_date` — `date` или `None` (стереть); событие `user.updated` по правилам раздела 6: событие пишется только при изменении; `phone` и `contacts` — всегда оба (как в срезе 001); `internal_phone`, `workplace`, `birth_date` — только если изменились; `update_own_contacts` остаётся (уточнение: вызывает `update_own_profile`, передаёт текущие значения остальных полей); то же правило ключей у шага «профиль» активации: `test_activation.py::test_profile_step_change_written_to_audit_unchanged_not` не меняется | test_staff_card |
| `accounts.create_user` | уточнение: новые необязательные именованные `internal_phone: str = ""` и `workplace: str = ""`; остальное как в срезе 001 | test_staff_import_run |
| `login` и обмен ссылок | уточнение: условие «запись заблокирована» везде означает `state in (BLOCKED, DISMISSED)`; общий отказ тот же, что для заблокированной | test_org_dismissal::test_dismissed_login_refused_at_password_and_code_with_common_message |
| `permissions.require_any_permission` | `require_any_permission(*codes)` — декоратор; без входа — редирект на вход, ни одного из прав — `PermissionDenied` (403); ровно как `require_permission`, но «хотя бы одно» | test_org_permissions, test_permissions |
| `permissions.AnyPermissionRequiredMixin` | миксин для классов: `required_permissions: tuple[str, ...]`; поведение то же. Ядро представлений-классов не использует: нужен только как пара декоратору | test_org_permissions |
| `permissions.forget_users` | уточнение: сигнатура та же, но удаление ключей откладывается на `transaction.on_commit`; вне транзакции — сразу | test_org_permissions::test_permission_keys_dropped_on_commit_* |
| `permissions.forget_all` | `forget_all() -> None`: удаляет ключи `perms:<id>` всех записей (на фиксации); вызывается при изменении набора прав роли (сигнал `m2m_changed` на `Role.permissions.through`) | test_org_permissions::test_role_permission_change_drops_all_permission_keys |
| `permissions.menu_for` | уточнение: элемент — словарь с ключами `url`, `title`, `icon`, `order` и, только если у описания пункта есть функция `badge`, ещё `badge` (CONTRACT-003 § 3.2) (ключа `permission` больше нет ни у одного пункта; тесты среза 001 его не читают); `icon` — путь шаблона значка `icons/<имя>.html`, новые файлы `templates/icons/structure.html` и `templates/icons/calendar.html`; порядок по `order`, затем по `title`; ядро: `/staff/` (10, право `staff.view` или `accounts.manage`), `/roles/` (40), `/audit/` (50), `/settings/portal/` (60), `/settings/security/` (70); `org` добавляет «Структура» `/structure/` (20, `staff.view`) и «Календарь» `/calendar/` (30, `staff.view` или `calendar.manage`). Порядок: «Заявки» 5, «Сотрудники» 10, «Структура» 20, «Календарь» 30, «Роли и права» 40, «Журнал событий» 50, «Настройки портала» 60, «Сервис-деск» 65, «Безопасность и политика» 70 — названия пунктов среза 001 прежние (permissions.py:20–26) | test_permissions::test_menu_hides_sections_without_permission, test_org_permissions::test_menu_staff_structure_calendar_items_by_permission |
| `permissions.roles_by_source` | `roles_by_source(user) -> list[tuple[str, list[Role]]]`: первая группа `("лично", [личные роли по названию])`, затем по одной группе на источник `("от подразделения <название узла>", [роли])`, по названию узла; пустые группы не возвращаются | test_org_permissions::test_card_roles_grouped_personal_and_by_unit_source |
| `permissions.permissions_of` | уточнение: объединяет личные роли и роли из `role_sources`; ключ кэша `perms:<id>` | test_org_permissions |
| `core.services.files` | модуль сервиса файлов ядра. `upload_photo(user, uploaded, *, actor, ip=None) -> StoredFile`: проверяет Pillow (формат по содержимому PNG или JPEG, не более 5 242 880 байт (5·1024·1024, как `MAX_LOGO_BYTES = 1024 * 1024` у логотипа; ровно 5 242 880 принимается, на байт больше — `too_big`), не более 40 000 000 точек), кладёт `PROTECTED_ROOT/incoming/<id>`, создаёт `StoredFile(status="pending")`, ставит `user.photo_pending`, прежний ожидающий файл удаляет (с диска и из `StoredFile`; файл в карантине остаётся), событие `photo.uploaded`, после фиксации ставит `core.tasks.scan_file(str(id))` в очередь `files`; отказ — `files.PhotoError` (`code`: `bad_format`, `too_big`, `too_many_pixels`) | test_photo |
| `files.delete_photo` | `delete_photo(user, *, actor, ip=None) -> None`: обнуляет `photo` и `photo_pending`, удаляет их файлы и записи (кроме `quarantine`), событие `photo.deleted`; без фото — тихо ничего | test_photo::test_photo_delete_by_self_or_accounts_manage_quarantine_kept |
| `files.photo_path` | `photo_path(stored: StoredFile, size: int \| None = None) -> pathlib.Path`: `photos/<id>-512.jpg` или `photos/<id>-96.jpg` (`size` 512 или 96); при `size=None` путь выбирается по статусу: `pending` — `incoming/<id>`, `quarantine` — `quarantine/<id>`; для `clean` без размера — `ValueError`; все под `settings.PROTECTED_ROOT` | test_photo |
| `files.photo_url` | `photo_url(user, size: int) -> str \| None`: `/staff/<user.id>/photo/<photo.id>/<size>/` для чистого `photo`, иначе `None`; `size` — 512 или 96 | test_photo::test_photo_url_changes_with_photo_old_url_404 |
| `files.PhotoError` | наследует `Exception`; атрибут `code`; текст по-русски | test_photo |
| `core.tasks.scan_file` | `apps.core.tasks.scan_file(file_id: str) -> None`. Берёт `StoredFile` и владельца под `select_for_update`; если не `pending` или не `photo_pending` владельца — выходит без изменений и без событий. Если самой строки `StoredFile` нет (файл удалён новой загрузкой или удалением фото, а задание осталось в очереди) — задание тоже завершается без изменений, без событий и без исключения (дополнение 19). Вызывает `clamav.scan(path)` через модуль: `from apps.integrations.clamav import services as clamav` (тесты подменяют `apps.integrations.clamav.services.scan`). «Чисто» — `photos/<id>-512.jpg`, `-96.jpg`, исходник удалён, `photo` переключён, прежнее фото удалено с диска и из `StoredFile`, `photo_pending=None`, статус `clean`, `scanned_at`, `photo.checked` с `after={"result": "clean"}`. «Найдено» — файл в `quarantine/<id>`, статус `quarantine`, `signature`, `scanned_at` = текущее время, `photo` не меняется, `photo_pending` остаётся ссылкой на карантинный файл, событие `photo.checked` с `result` `quarantine` и `signature`. `ScanUnavailable` — `attempts += 1`, `last_error` (без пути и содержимого), исключение поднимается дальше (RQ повторяет); `attempts` и `last_error` сохраняются и фиксируются до того, как исключение вылетает из задания (исключение поднимается после выхода из `atomic`) | test_photo |
| задание `scan_file` в очереди | `queue = django_rq.get_queue("files")`; `job.func_name == "apps.core.tasks.scan_file"`; `job.args == (str(stored.id),)`; `job.kwargs == {}`; `Retry(max=24, interval=[60, 300, 900] + [3600] * 21)` (`job.retries_left == 24`, `job.retry_intervals`); `commit_mode="on_db_commit"` | test_photo::test_upload_creates_pending_file_enqueues_scan_after_commit_previous_clean_photo_still_shown |
| `core.tasks.requeue_pending_scans` | `() -> int`: ставит `scan_file` для `StoredFile(status="pending")` с `created_at` старше часа, у которых нет задания в `files` (ищется по `job.args[0]` в очереди, в реестрах `scheduled_job_registry` и `started_job_registry`); возвращает число поставленных | test_photo::test_hourly_job_requeues_pending_scans_without_job |
| `core.tasks.purge_quarantine` | `() -> int`: стирает с диска файлы `quarantine/<id>` для записей, у которых `scanned_at` старше 30 суток; строка `StoredFile` остаётся (статус `quarantine`, `signature`, `sha256` нужны для разбора случая); если строка всё ещё `photo_pending` владельца — `photo_pending` обнуляется; событий нет; возвращает число стёртых файлов | test_photo::test_quarantine_files_purged_after_30_days (файла нет, строка есть, `photo_pending is None`) |
| `org.tasks.purge_previews` | `apps.org.tasks.purge_previews() -> int`: удаляет `StaffImport(state="preview")` и `CalendarUpload(state="preview")` с `created_at` старше суток; возвращает число удалённых строк; зарегистрировано в `cron.py` как `purge_import_previews` | test_staff_import_run::test_rows_trimmed_after_done_unconfirmed_preview_purged_after_day, test_calendar_file::test_unconfirmed_calendar_preview_purged_after_day |
| `PortalDateInput` | `apps.core.widgets.PortalDateInput` (наследник `forms.DateInput`); `template_name = "widgets/date_field.html"`; формат вывода `%d.%m.%Y`. Там же `DATE_INPUT_FORMATS = ("%d.%m.%Y", "%Y-%m-%d")` и `parse_date(value: str) -> datetime.date \| None` (пустая или неразборная строка — `None`; формат ДД.ММ.ГГГГ и ГГГГ-ММ-ДД) | test_date_field |
| `audit_search.parse` | уточнение: `date_from` и `date_to` принимают оба формата через `widgets.parse_date`; неверная дата — как в срезе 001 (игнорируется) | test_date_field::test_audit_filter_accepts_dd_mm_yyyy |
| `clamav.services.scan` | `apps.integrations.clamav.services.scan(path) -> ScanResult`; `ScanResult = NamedTuple("ScanResult", clean=bool, signature=str)`; чисто — `ScanResult(True, "")`; найдено — `ScanResult(False, "<сигнатура>")` (например, `"Eicar-Signature"`, без слова FOUND и без префикса `stream:`); `path` — `str` или `Path` | test_clamav_adapter::test_ok_is_clean_found_returns_signature, test_clamav_live |
| `ScanUnavailable` | `class ScanUnavailable(Exception)`, определён в `apps/integrations/clamav/client.py`, доступен и как `apps.integrations.clamav.services.ScanUnavailable`; поднимается при сбое связи, тайм-ауте, ответе `... ERROR` и неожиданном ответе | test_clamav_adapter::test_connection_error_timeout_and_error_reply_raise_scan_unavailable |
| `clamav.client.ping` | `ping(*, host=None, port=None, timeout=None) -> bool`: отправляет `b"zPING\0"`, ответ (чтение — как у `instream`: `recv` до `\0` или закрытия, дополнения 25, 32) `PONG` — `True`; иначе `ScanUnavailable`. Незаданные аргументы берутся из `settings.CLAMAV_*` при вызове | test_clamav_adapter::test_ping |
| `clamav.client.instream` | `instream(path, *, host=None, port=None, timeout=None) -> str`: отправляет `b"zINSTREAM\0"`, затем части не более `CHUNK_SIZE = 65536` байт, каждая с длиной 4 байта big-endian перед данными, в конце `b"\0\0\0\0"`; возвращает ответ clamd без завершающего `\0` и пробелов (`stream: OK`, `stream: <сигнатура> FOUND`, `... ERROR`). Соединение — `socket.create_connection((host, port), timeout=timeout)` через модуль `socket` (тесты подменяют `apps.integrations.clamav.client.socket.create_connection`); отправка — `sendall`, ответ clamd читается `sock.recv(...)` до завершающего `\0` или закрытия соединения, без `makefile`; так же у `ping` (дополнения 25, 32) | test_clamav_adapter::test_instream_sends_64k_chunks_with_length_and_zero_terminator |
| адаптер и журнал | ни `client`, ни `services`, ни задание не пишут в журнал событий и в логи содержимое файла и путь на диске; в логах допустимо имя сигнатуры и номер `StoredFile` | test_clamav_adapter::test_adapter_logs_no_content_or_path, test_photo::test_photo_events_signature_without_path_or_content |

## 4. Сервисы `org.services.*`

Модулей ровно семь: `structure`, `membership`, `people`, `unit_roles`, `calendar`,
`calendar_file`, `staff_import` (пакет `apps/org/services/`). Все имена ниже доступны как
`apps.org.services.<модуль>.<функция>`. Прав службы не проверяют (это делают представления).
Пустая правка (то же значение) у `update_settings`, `set_day`, `update_unit`, `move_unit`,
`set_marks`, `set_unit_roles` — ни события, ни роста версии календаря (как `update_profile` среза
001, accounts.py:140–146).

**Ошибка одна на весь `org`:** `apps.org.services.OrgError(Exception)` (определён в
`apps/org/services/errors.py`, экспортируется из пакета). Атрибуты: `code` (строка из таблицы
ниже), `str(error)` — текст для человека по-русски. Тест узнаёт причину по `error.code`; текст
проверяется только там, где раздел 10 даёт дословную подпись. Ошибки ядра, которые пропускают
сервисы `org` (`AccountError`, `RoleError`), не оборачиваются.

| Код причины `OrgError.code` | Когда | Тесты |
|---|---|---|
| `kind_rules` | нарушено правило видов: отдел только под отделом, команда под отделом или командой, корень — отдел | test_org_structure |
| `name_required` | название пустое после обрезки пробелов | test_org_structure |
| `name_too_long` | название длиннее 150 знаков | test_org_structure |
| `name_taken` | у родителя уже есть другой узел с тем же `name_key`; сам переименовываемый узел не конфликтует с собой, поэтому смена только регистра или «ё/е» допустима (дополнение 6) | test_org_structure |
| `bad_mode` | для отдела `mode` — любое значение, кроме `transfer` и `concurrent`, включая `None` | test_org_membership |
| `root_protected` | удалить или перенести корень (в том числе прямым вызовом) | test_org_structure::test_root_rename_allowed_delete_and_move_refused_even_direct |
| `cycle` | новый родитель — сам узел или его потомок | test_org_structure::test_move_into_self_or_descendant_refused |
| `not_empty` | удаление узла с участниками или вложенными узлами | test_org_structure::test_delete_only_empty_unit_with_confirmation_roles_removed_and_audited |
| `kind_mismatch` | перевод участника в узел другого вида | test_org_membership::test_member_menu_transfer_same_kind_remove_and_dismiss_items |
| `not_member` | удаление из узла, где человека нет; отметка не участника | test_org_membership |
| `head_and_deputy` | итоговые наборы `set_marks` пересекаются, или человек из нового `heads` сейчас (в сохранённом состоянии) заместитель этого узла, или человек из нового `deputies` сейчас руководитель — даже если тот же вызов снимает прежнюю отметку (сменить можно только двумя вызовами: снять, затем поставить) | test_org_membership::test_head_then_deputy_in_same_unit_refused_not_replaced |
| `dismissed_user` | членство или отметка для уволенного (в `add_members` — отказ всей пачки, ничего не добавляется; в `set_marks` проверяется раньше `not_member`) | test_org_dismissal::test_dismissed_card_read_only_except_rehire_and_photo_delete |
| `admin_role_forbidden` | роль «Администратор портала» узлу | test_org_permissions::test_admin_role_cannot_be_assigned_to_unit |
| `role_missing` | несуществующая роль у узла | test_org_permissions |
| `bad_weekday` | значение `work_weekdays` вне 0…6 | test_calendar |
| `no_weekday` | не выбран ни один рабочий день | test_calendar::test_week_needs_one_day_and_day_end_two_hours_after_start |
| `day_too_short` | конец дня меньше чем на 2 часа позже начала | test_calendar::test_week_needs_one_day_and_day_end_two_hours_after_start |
| `year_not_loaded` | правка дня в году без `CalendarYear` | test_calendar::test_day_edit_only_in_loaded_year_all_kinds |
| `bad_kind` | неизвестный вид дня | test_calendar |
| `too_big` | файл больше предела (файл сотрудников и календаря — не более 1 048 576 байт; ровно столько принимается, на байт больше — `too_big`) | test_staff_import_file, test_calendar_file |
| `not_utf8` | содержимое не в строгом UTF-8 или с нулевым байтом, в том числе любой файл, который не ZIP и не строгий UTF-8 (дополнение 11); пустой файл календаря и файл календаря без заголовков формата — не `not_utf8`, а `bad_format` (дополнение 26) | test_staff_import_file, test_calendar_file |
| `bad_format` | сотрудники: архив ZIP без `[Content_Types].xml` и `xl/workbook.xml` (с ними — XLSX; не ZIP и не UTF-8 — `not_utf8`); календарь: пустой файл, файл в строгом UTF-8 без заголовков формата (например, 1 048 576 байт «x»), колонки не те (дополнения 11, 26) | test_staff_import_file, test_calendar_file |
| `missing_columns` | нет обязательных колонок; текст называет их | test_staff_import_file::test_refused_over_1mb_over_1000_rows_not_csv_or_xlsx_not_utf8_missing_columns |
| `too_many_rows` | больше 1000 строк данных | test_staff_import_file |
| `zip_bomb` | в XLSX больше 100 частей или больше 20 МБ в распакованном виде | test_staff_import_file::test_xlsx_zip_bomb_and_xml_bomb_refused |
| `xml_bomb` | defusedxml отверг XML внутри XLSX | test_staff_import_file::test_xlsx_zip_bomb_and_xml_bomb_refused |
| `year_missing` | в файле календаря нет строки запрошенного года | test_calendar_file::test_file_without_requested_year_refused |
| `totals_mismatch` | пересчёт не сходится с итоговыми колонками строки года | test_calendar_file::test_corrupted_totals_refused |

Порядок проверок при нескольких нарушениях сразу: `root_protected`, затем `cycle`, затем
`kind_rules`, затем `name_taken`, затем `not_empty`; для `create_unit` и `update_unit`:
`name_required`, `name_too_long`, `kind_rules`, `name_taken`.

### 4.1 `structure`

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `lock_root` | `lock_root() -> Unit`: `Unit.objects.select_for_update().get(is_root=True)`. Все функции `structure`, `membership` и `people`, меняющие структуру, членства или состояние, вызывают её в своей транзакции; тест узнаёт замок по SQL с `FOR UPDATE`, таблицей `"org_unit"` и условием `WHERE "org_unit"."is_root"` (не по слову `is_root`, оно есть в списке колонок любого запроса к узлам; дополнение 16) | test_org_structure::test_structure_changes_lock_root_row, test_org_membership::test_membership_changes_lock_root_row |
| `root` | `root() -> Unit` | test_org_structure |
| `create_unit` | `create_unit(*, kind, name, parent, description="", actor, ip=None) -> Unit`; `parent` — `Unit` (корень создаёт только миграция; `parent=None` — `OrgError(code="kind_rules")`); событие `unit.created` | test_org_structure |
| `update_unit` | `update_unit(unit, *, name, description, actor, ip=None) -> Unit`; вид не меняется; корень переименовать можно; событие `unit.updated` только если что-то изменилось | test_org_structure |
| `move_unit` | `move_unit(unit, new_parent, *, actor, ip=None) -> Unit`; пути и глубины поддерева — одним `UPDATE`; сбрасывает ключи `perms:<id>` участников поддерева на фиксации; событие `unit.moved`; тот же родитель — тихо ничего | test_org_structure |
| `delete_unit` | `delete_unit(unit, *, actor, ip=None) -> None`; роли узла уходят с ним; событие `unit.deleted` с `before["roles"]`; ключи `perms:<id>` не сбрасываются: у удаляемого узла нет участников | test_org_structure |
| `descendants` | `descendants(unit, *, include_self=True) -> QuerySet[Unit]` по началу `path`, порядок по `path` — байтовый, как `sorted()` (поле `Unit.path` с `db_collation="C"`); тесты сравнивают с `sorted()` по `path` узлов, а не с порядком создания (дополнения 1, 18) | test_org_structure, test_staff_search |
| `units_of` | `units_of(user) -> list[UnitRef]`: узлы, где `user` состоит, по возрастанию `path`; уволенный и не участник — `[]`; заблокированный — его узлы (блокировка членств не снимает) | test_org_heads::test_heads_and_units_public_services_for_other_slices |
| `heads_of` | `heads_of(user) -> list[HeadsOf]`: по одному элементу на каждое членство `user`, по возрастанию `path` узла; правило FR-115: если `user` не руководитель узла и у узла есть руководители — это они (`source` — сам узел); иначе берутся руководители ближайшего вышестоящего узла, где они есть; «первый уровень» — собственный узел членства: там `user` не исключается и там он лишь не-руководитель; в каждом вышестоящем узле из набора руководителей исключается сам `user`, и если набор после исключения пуст, поиск идёт ещё выше; `source` — узел, где найден непустой набор; заместители (`mark="deputy"`) руководителями не считаются; руководитель корня без вышестоящих узлов получает `heads=[]`, `source=None`; руководитель — в любом неуволенном состоянии (блокировка структуру не меняет, FR-124); `heads` по `full_name`, затем `id`, без повторов. Совместитель получает несколько элементов | test_org_heads |
| `subordinates_of` | `subordinates_of(user) -> list[PersonRef]`: участники узлов, где `user` руководитель, и вложенных узлов, без самого `user` и без повторов, по `full_name`, затем `id` | test_org_heads::test_card_units_by_comma_and_subordinates_without_self_or_repeats |

### 4.2 `membership`

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| константы режимов | `membership.TRANSFER = "transfer"`, `membership.CONCURRENT = "concurrent"` | test_org_membership |
| `add_members` | `add_members(unit, users, *, mode=None, actor, ip=None) -> AddResult`; `AddResult` — `dataclass` с `added: list[User]`, `already: list[User]`. Отдел: `mode=TRANSFER` удаляет членства человека в других отделах (команды остаются), `CONCURRENT` ничего не трогает; любое значение, кроме `TRANSFER` и `CONCURRENT`, включая `None`, для отдела — `OrgError(code="bad_mode")`; уволенный в `users` — `OrgError(code="dismissed_user")` для всей пачки, ничего не добавляется (одна транзакция). Команда: `mode` игнорируется. Уже участник — попадает в `already`, ничего не меняется. Сбрасывает `perms:<id>` добавленных на фиксации. События: отдел, `TRANSFER` — по каждому человеку `membership.removed` (`reason="transfer"`) на каждое снятое членство в отделах по возрастанию `path`, затем `membership.added` (`mode="transfer"`), затем одно `membership.transferred`, только если хоть одно членство снято (спека, сценарий 2, п. 1); отдел, `CONCURRENT` — только `membership.added` (`mode="concurrent"`); команда — только `membership.added` (`mode=""`) | test_org_membership |
| `transfer_member` | `transfer_member(user, unit, target, *, actor, ip=None) -> bool`: `True` — перевёл: снимает членство в `unit` (с отметкой) и добавляет в `target` того же вида; прочие членства не трогает; события по порядку `membership.removed` (`reason="transfer"`), `membership.added` (`mode="transfer"`), `membership.transferred`; сбрасывает `perms:<id>` этого человека на фиксации; `False` — человек уже участник цели, ничего не меняется и событий нет | test_org_membership, test_org_heads::test_heads_follow_new_position_after_move |
| `remove_member` | `remove_member(user, unit, *, actor, ip=None) -> None`: событие `membership.removed` с причиной `manual`; отметка уходит с членством; сбрасывает `perms:<id>` этого человека на фиксации | test_org_membership |
| `set_marks` | `set_marks(unit, *, heads=None, deputies=None, actor, ip=None) -> None`: `None` — этот набор не меняется, итерируемое `User` — заменяет этот набор; порядок проверок: `dismissed_user`, `not_member` (не участник), `head_and_deputy` (условия — в таблице кодов); событие `unit.marks_changed` только если набор изменился; отметка не меняет права и роли | test_org_membership, test_org_heads::test_head_mark_gives_no_permissions_and_no_manager_role |

### 4.3 `people`

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `dismiss` | `dismiss(user, *, actor, ip=None) -> None`: в одной транзакции `lock_root()`, `accounts.dismiss(user, actor=actor, ip=ip)`, затем удаляет все членства (с отметками) событиями `membership.removed` с причиной `dismissal`, по одному на узел, по возрастанию `path`; сбрасывает `perms:<id>`. Исключения ядра (`AccountError`, `RoleError`) идут наружу как есть | test_org_dismissal |
| `rehire` | `rehire(user, *, actor, ip=None) -> None`: `accounts.rehire(...)` в транзакции; подразделений у возвращённого нет | test_org_dismissal |

### 4.4 `unit_roles`

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `set_unit_roles` | `set_unit_roles(unit, roles, *, actor, ip=None) -> None`: заменяет набор ролей узла целиком; `roles` — итерируемые `Role` или id; события `unit.roles_changed` только при изменении; сбрасывает `perms:<id>` всех участников поддерева на фиксации | test_org_permissions |
| `roles_of` | `roles_of(unit) -> list[Role]` по названию | test_org_permissions |

### 4.5 `calendar`

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `day_kind` | `day_kind(day: datetime.date) -> str`: `"holiday"`, `"day_off"`, `"workday"`, `"short"` (запись `SpecialDay`, год загружен); иначе `"work"` (рабочий день недели) или `"off"` (выходной по `work_weekdays`); для незагруженного года — только `"work"` и `"off"`. Значения `"work"` и `"off"` — не значения `SpecialDay.kind` | test_calendar::test_day_kind_special_then_weekdays_unloaded_year_weekdays_only |
| `is_working_time` | `is_working_time(moment: datetime.datetime) -> bool`: `moment` с часовым поясом (без пояса — `ValueError`), приводится к `Europe/Moscow`; `day_kind` не `"off"`/`"holiday"`/`"day_off"`; время от `day_start` (включительно) до `day_end` (не включительно), у `"short"` конец на час раньше, и `short` считается рабочим днём и в субботу | test_calendar::test_is_working_time_holiday_day_off_workday_short_day_saturday_utc_input |
| `next_working_start` | `next_working_start(moment: datetime.datetime) -> datetime.datetime \| None`: с поясом (иначе `ValueError`), результат в `Europe/Moscow`; если `moment` уже рабочее время — сам `moment`; иначе ближайшее начало рабочего дня после него; ищет не дальше 400 суток вперёд, дальше — `None` | test_calendar::test_next_working_start_and_400_days_limit |
| `update_settings` | `update_settings(*, work_weekdays, day_start, day_end, actor, ip=None) -> WorkCalendar`; `work_weekdays` — итерируемые целые 0…6 (хранится отсортированным списком без повторов); `day_start`, `day_end` — `datetime.time`; события `calendar.settings_changed` только при изменении; увеличивает номер версии | test_calendar |
| `set_day` | `set_day(day, kind, *, actor, ip=None) -> None`; `kind` — значение `SpecialDay.kind` или `""` (обычный день, запись снимается); `SpecialDay.origin="manual"`, `changed_by=actor`; год без `CalendarYear` — `year_not_loaded`; событие `calendar.day_changed` (для дня без записи `before.kind == ""`; числа в `before`/`after` — целые JSON, дополнения 7, 28); тот же вид — тихо ничего; увеличивает номер версии | test_calendar::test_day_edit_only_in_loaded_year_all_kinds, test_calendar::test_calendar_events_settings_year_loaded_day_changed |
| `month_marks` | `month_marks(year: int, month: int) -> dict[datetime.date, str]`: только дни, у которых `day_kind` не `"work"`, значение — результат `day_kind`; результат кэшируется (раздел 7) | test_calendar::test_month_marks_cached_by_calendar_version_bumped_by_settings_day_edit_and_file_apply, test_date_field |
| `version` | `version() -> int`: номер версии календаря, целое ≥ 0: отсутствующий ключ читается как 0; каждое изменение — `INCR` на фиксации (первое даёт 1); растёт на 1 при `update_settings`, `set_day`, `calendar_file.apply` (на фиксации) | то же |
| `loaded_years` | `loaded_years() -> list[int]` по возрастанию | test_calendar |
| `missing_years` | `missing_years(today: datetime.date \| None = None) -> list[int]`: текущий год, если не загружен, и следующий год, если `today` с 1 декабря и он не загружен; `today` по умолчанию — сегодня по Москве | test_calendar::test_reminder_whole_year_when_current_missing_and_from_december_for_next |

### 4.6 `calendar_file`

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `parse` | `parse(content: bytes, *, year: int) -> ParsedYear`; `ParsedYear` — `dataclass`: `year: int`, `days: list[tuple[datetime.date, str]]` (по возрастанию даты, значения — `SpecialDay.kind`), `totals: dict` (пять ключей раздела 2). Порядок проверок: размер, строгий UTF-8, заголовки и число колонок, строка года, перевод и сверка итогов. Пустой файл и файл в строгом UTF-8 без заголовков формата — `bad_format` (дополнение 26). Правила перевода: число без пометки на будний день — `holiday`; с «+» — `day_off`; с «*» — `short` (в том числе в субботу и воскресенье); суббота или воскресенье вне списка месяца — `workday`; суббота и воскресенье без пометки — не особые дни; рабочая суббота с «*» — одна запись `short`, в `totals` только `short_days` (тест сверяет `work_days` с итоговой колонкой файла, а сумму видов — с числом `SpecialDay` года). Перевод не зависит от `WorkCalendar.work_weekdays` | test_calendar_file |
| `make_preview` | `make_preview(content: bytes, *, year: int, file_name: str, actor, ip=None) -> CalendarUpload`: `parse` и запись `state="preview"`; календарь и `SpecialDay` не меняются, событий журнала нет, номер версии календаря не растёт (дополнение 26) | test_calendar_file::test_preview_counts_warns_about_manual_days_and_changes_nothing |
| `preview_warnings` | `preview_warnings(upload) -> dict`: `manual_days` (число `SpecialDay` года с `origin="manual"`, которые будут заменены), `existing_days` (число всех `SpecialDay` года), `year_loaded` (`bool`), `weekend_work` (`bool`: в `WorkCalendar.work_weekdays` есть 5 или 6, поэтому праздник на выходной, показанный в файле обычным выходным, станет рабочим днём; страница предупреждает) | test_calendar_file::test_preview_counts_warns_about_manual_days_and_changes_nothing, test_holiday_on_weekend_shown_as_day_off_upload_page_warns |
| `apply` | `apply(upload, *, actor, ip=None) -> CalendarYear`: если `state="applied"` — возвращает `CalendarYear` года, ничего не меняя; иначе удаляет `SpecialDay` года и вставляет новые с `origin="file"`, `changed_by` — загрузивший (`actor`), `changed_at` — момент применения (дополнение 26), создаёт или обновляет `CalendarYear` (`loaded_at`, `loaded_by`, `file_name`, `totals`), `upload.state="applied"`; другие годы не трогает; событие `calendar.year_loaded` (при первой загрузке года `before == {"year": <год>, "totals": {}}`, дополнение 34; итоги — целые JSON, дополнение 7); увеличивает номер версии | test_calendar_file::test_apply_replaces_year_keeps_other_years |

### 4.7 `staff_import`

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `REQUIRED_COLUMNS`, `OPTIONAL_COLUMNS` | кортежи названий: `("Почта", "Фамилия", "Имя", "Должность")` и `("Отчество", "Телефон", "Внутренний телефон", "Место работы", "Подразделение", "Руководитель")` | test_staff_import_file |
| `parse_file` | `parse_file(content: bytes) -> ParsedFile`: `ParsedFile` — `dataclass`: `file_format: str` (`"csv"` или `"xlsx"`, по содержимому), `rows: list[dict]` (ключи словаря строки — латинские имена из раздела 2 до проверки: `email`, `last_name`, `first_name`, `middle_name`, `position`, `phone`, `internal_phone`, `workplace`, `unit_path`, `head_raw`), `not_loaded: list[str]` (названия лишних колонок как в файле, в порядке файла); заголовки сравниваются после удаления всех пробельных знаков (и внутри слова), в нижнем регистре, «ё» как «е»: «Место  работы», «местоработы» и «МЕСТО РАБОТЫ» совпадают (дополнение 10). Форматы: CSV `;` или `,`, UTF-8 с BOM или без; формат определяется по содержимому: ZIP с `[Content_Types].xml` и `xl/workbook.xml` — XLSX, ZIP без них — `bad_format`, не ZIP и не строгий UTF-8 или с нулевым байтом — `not_utf8`, UTF-8 без обязательных колонок — `missing_columns`. Порядок: размер (`too_big`) → формат → для XLSX оглавление (`zip_bomb`) → разбор (`xml_bomb`) → колонки → число строк (`too_many_rows`; дополнение 11); XLSX — формулы не вычисляются (`data_only=True`: ячейка с формулой без сохранённого значения — пустая строка, с сохранённым — это значение текстом; текст формулы не читается, дополнение 8); дата или дата-время — `ДД.ММ.ГГГГ` (время отбрасывается); целое число — без «.0» и экспоненты (`89001234567`); дробное — `str()` без экспоненты (дополнение 9) | test_staff_import_file |
| `make_preview` | `make_preview(content: bytes, *, file_name: str, actor, ip=None) -> StaffImport`: `parse_file`, проверка строк (раздел 2, `rows` и `code` ниже; у строки `will_create` `reason == ""`, дополнение 27), `state="preview"`, `summary`; ничего не создаёт | test_staff_import_run::test_preview_creates_nothing |
| `confirm` | `confirm(item: StaffImport, *, send_invites: bool, actor, ip=None) -> StaffImport`: `select_for_update` строки; `state="done"` — возвращает как есть, без событий; иначе перепроверка почты, строки в точках сохранения (годные строки выполняются и при наличии строк `error`, они остаются ошибками, дополнение 29; службы ядра вызываются через модуль: `accounts.create_user(...)`, чтобы тест мог подменить `apps.core.services.accounts.create_user`, дополнение 31; у `created` `reason == ""`, членство из загрузки — `membership.added` с `mode=""` и `mark`, `"head"` при «да», дополнение 27), письма после фиксации только при `send_invites=True`, события, `rows` обрезаются до `number`, `email`, `result`, `reason` (без `code`, § 11, решение Opus A14), `state="done"` | test_staff_import_run |
| `sample_csv`, `sample_xlsx` | `() -> bytes`: заголовки `REQUIRED_COLUMNS + OPTIONAL_COLUMNS` в этом порядке и две вымышленные строки; CSV — UTF-8 с BOM, разделитель `;` | test_staff_import_file::test_samples_csv_and_xlsx_headers_and_two_fake_rows |

Коды причин строки (`rows[i]["code"]`, `result` в скобках): `email_missing` (`error`),
`email_invalid` (`error`), `email_taken` (`skipped`), `email_taken_dismissed` (`skipped`,
`hint="dismissed"`; решено спекой, сценарий 5, п. 2, и планом), `email_repeated` (`skipped`),
`last_name_missing`, `first_name_missing`, `position_missing`, `too_long` (длина поля; часть пути длиннее 150 знаков; ФИО — по собранному `full_name` «Фамилия Имя Отчество» через один пробел, без пустого отчества, больше 255 знаков; остальные поля — по длинам полей `User`: должность и место работы 255, телефон 64, внутренний телефон 32; почта до 254, дополнение 27), `path_invalid` (пустая часть пути, например «ИТ-отдел //Сеть»),
`head_invalid` (колонка «Руководитель» не «да», не «нет» и не пусто), `head_without_unit`,
`path_root_mismatch`, `path_team`, `unexpected` (все — `error`). Тесты: test_staff_import_run.

## 5. Точки расширения `apps/core/extensions.py`

Реестр — модуль `apps.core.extensions`. Реестры хранят списки функций в порядке регистрации.

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `POINTS` | кортеж из тринадцати имён (девять прежних по порядку: `menu_items`, `role_sources`, `role_usage`, `audit_labels`, `staff_directory`, `card_sections`, `day_marks`, `home_notices`, `stand_reset` — и `unit_usage`, `file_purposes`, `mail_renderers`, `login_links`, CONTRACT-003 § 3.2); `org` регистрирует обычные функции модулей `apps.org…` (`func.__module__` начинается с `apps.org`, дополнение 39) в первых девяти точках; остальные четыре — `servicedesk` | test_extensions::test_org_registers_all_nine_extension_points (п. (1) T-3138) |
| `register` | `register(point: str, func) -> None`; неизвестная точка — `ValueError`; та же функция второй раз — игнорируется (повторный `ready()`) | test_extensions |
| `registered` | `registered(point: str) -> list`: копия списка функций; неизвестная точка — `ValueError`, как у `register` (дополнение 38) | test_extensions, test_org_permissions |
| `clear` | `clear() -> None`: очищает все тринадцать реестров | test_extensions |
| `empty` | `empty()` — контекстный менеджер: запоминает все реестры, очищает их на время блока, возвращает прежние; фикстура `no_extensions` в `tests/conftest.py` (pytest находит фикстуры только там; пишет T-2100b) оборачивает им тело теста | test_extensions::test_core_without_registered_extensions_behaves_as_slice_001 |
| `menu_items` | `func() -> list[dict]` (описание пунктов для ядра): ключи `permissions` (кортеж кодов, достаточно любого), `url`, `title`, `icon` (путь шаблона значка `icons/<имя>.html`), `order` (целое); ядро описывает свои пункты так же; `permissions.menu_for(user)` отдаёт доступные пункты без ключа `permissions`: `url`, `title`, `icon`, `order` и, только у пункта с функцией `badge`, ещё `badge` (§ 11, A8; дополнение 33); необязательные ключи описания `visible` и `badge` (CONTRACT-003 § 3.2) | test_org_permissions |
| `role_sources` | `func(user) -> list[tuple[Role, str]]`: пары (роль, `"от подразделения <название узла, которому роль назначена>"`, например `"от подразделения Сеть"`) для всех узлов членств `user` и всех их вышестоящих; роль отдела действует на членов вложенных узлов и команд; одна роль из двух источников — две пары | test_org_permissions |
| `role_usage` | `func(role) -> str \| None`: текст причины отказа или `None`; текст «Роль назначена узлу структуры: сначала снимите её.» | test_org_permissions::test_role_assigned_to_unit_cannot_be_deleted |
| `audit_labels` | `func() -> dict` с необязательными ключами `actions` (код события → название), `fields` (поле → название), `object_types` (вид → название), `values` (поле → словарь значение → название); ядро сливает словари (поздние побеждают); `audit_labels` модуля `org` даёт названия и вложенных ключей (`holidays_on_weekdays` и др. из `totals` календаря и итогов загрузки): вложенный словарь в `before`/`after` показывается как «название: число; …», латинских ключей в тексте нет (дополнение 29) в `audit_search.known_actions()` и `audit_labels.label/text/object_title` | test_org_audit |
| `staff_directory` | `func(viewer) -> StaffDirectory`; `StaffDirectory` — `dataclass` из `apps.core.extensions` с полями `presets: list[Preset]`, `filters: list[Filter]`, `search: Callable[[str], Q] \| None`, `columns: list[Column]`, `buttons: list[Button]`. `Preset(key: str, title: str, apply: Callable[[QuerySet], QuerySet], order: int)`; `Filter(name: str, label: str, choices: Callable[[], list[tuple[str, str]]], apply: Callable[[QuerySet, str], QuerySet])`; `Column(key: str, title: str, template: str, order: int)`; `Button(title: str, url: str, permissions_all: tuple[str, ...], key: str)`; `search(text)` возвращает `Q`, который ядро добавляет через ИЛИ к условиям своих полей | test_staff_search |
| `card_sections` | `func(viewer, person) -> list[CardSection]`; `CardSection(key: str, tab: str, order: int, template: str, context: dict)`, `tab` — `"profile"` или `"security"`; пустой список — раздела нет | test_staff_card, test_org_heads |
| `day_marks` | `func(year: int, month: int) -> dict[datetime.date, str]`: значения — результат `day_kind` (раздел 4.5); ядро берёт дни, отсутствующие в словаре, обычными; без зарегистрированных функций выходными считаются суббота и воскресенье (`"off"`) | test_date_field |
| `home_notices` | `func(viewer) -> list[dict]`: ключи `key` (строка, например `calendar-year`), `year` (целое или `None`), `text`, `url`, `level` (`"warning"`) и необязательный `link` — подпись ссылки на `url` (у напоминания календаря «Загрузить файл»); без `link` ядро подписывает ссылку «Перейти» (дополнение 64) | test_calendar::test_reminder_*, test_org_pages |
| `stand_reset` | `func() -> None`: удаляет данные модуля до исходных; вызывается командой `e2e_reset_stand` | test_extensions |

Сброс реестров для T-2116: `with extensions.empty():` (или фикстура `no_extensions`); внутри
проверяются: `menu_for(user)` даёт только пункты ядра, `permissions_of(user)` не видит ролей узлов,
`/staff/` показывает пресеты ядра — у администратора ровно `a[data-preset]` со значениями `""`, `dismissed`, `all`, `invited`, `active`, `blocked`, без `no_unit` (дополнение 48) — с `state=` пустым (все записи, как в срезе 001, потому что
уволенных нет), карточка без разделов `org`. Импорт: `test_core_does_not_import_org` ищет в файлах
`apps/core/**/*.py` текст `apps.org` и `from apps import org`.

## 6. Коды событий журнала

Все события: `before` и `after` — словари (пустая сторона — `{}`, кроме сторон, у которых в таблице есть ключи, дополнение 37; тест её не читает). `actor` —
выполнивший действие, кроме `photo.checked` (`actor is None`, на странице «система»).
Вид объекта в фильтре: `unit` — «узел», `staff_import` — «загрузка», `calendar` — «календарь»,
`user` — «сотрудник» (как в срезе 001). Названия кодов — на русском в `audit_labels` модуля
`org` (проверка: `audit_search.known_actions()` содержит код, название не равно коду и
содержит кириллицу).

| Код | `object_type`, `object_id` | Ключи `before` / `after` | Тесты |
|---|---|---|---|
| `unit.created` | `unit`, `str(unit.pk)` | `after`: `kind`, `name`, `description`, `parent` (название родителя) | test_org_structure::test_unit_events_created_updated_moved_deleted_before_after |
| `unit.updated` | `unit`, id | `before`/`after`: только изменённые из `name`, `description` | то же |
| `unit.moved` | `unit`, id | `before`: `parent` (название); `after`: `parent`; плюс `parent_id` с обеих сторон | то же, test_org_heads |
| `unit.deleted` | `unit`, id | `before`: `kind`, `name`, `parent`, `roles` (список названий снятых ролей по возрастанию) | то же |
| `unit.marks_changed` | `unit`, id | `before`/`after`: `heads` и `deputies` — списки `full_name` по возрастанию; пишется только вызовом `set_marks`; снятие отметки вместе с членством `unit.marks_changed` не пишет (отметка видна в `membership.removed.before.mark`); отметка руководителя из загрузки — `membership.added` с `mark="head"` без `unit.marks_changed` | test_org_membership |
| `unit.roles_changed` | `unit`, id | `before`/`after`: `roles` — список названий по возрастанию (при первом назначении `before == {"roles": []}`, дополнение 37) | test_org_permissions::test_unit_roles_events_before_after |
| `membership.added` | `user`, `str(user.pk)` | `after`: `unit` (название), `unit_id`, `mode` (`"transfer"`, `"concurrent"` или `""` — команда и `transfer_member` пишут свои значения, см. 4.2), `mark` (`""`, `"head"`, `"deputy"`) | test_org_membership::test_membership_events_with_mode_reason_and_mark |
| `membership.removed` | `user`, id | `before`: `unit`, `unit_id`, `mark`, `reason` (`"manual"`, `"transfer"`, `"dismissal"`) | то же, test_org_dismissal |
| `membership.transferred` | `user`, id | `before.units` / `after.units` — названия всех узлов человека до и после операции, по `path`; пишется в `add_members(TRANSFER)` только если снято хоть одно членство, и в `transfer_member` | test_org_membership, test_org_heads |
| `user.dismissed` | `user`, id | `before`: `state`, `roles` (названия личных ролей по возрастанию); `after`: `state="dismissed"` | test_org_dismissal::test_dismiss_and_rehire_events |
| `user.rehired` | `user`, id | `before`: `state="dismissed"`; `after`: `state="invited"`, `roles=["Сотрудник ИТ"]` | то же |
| `user.updated` (новые поля) | `user`, id | событие только при изменении; `phone` и `contacts` пишутся оба, если изменилось хоть одно (как в срезе 001); `internal_phone`, `workplace` — только изменённые; `birth_date` — только в `after` (`"изменено"` / `"очищено"`); изменилась одна дата рождения — `before == {}`, `after == {"birth_date": "изменено"}`; у `update_profile` (администратор) — только изменённые ключи, как в срезе 001 | test_staff_card::test_card_fields_events_birth_date_as_changed_or_cleared_only |
| `photo.uploaded` | `user`, id | `after`: `file_id` (`str(uuid)`), `size`, `content_type` | test_photo::test_photo_events_signature_without_path_or_content |
| `photo.checked` | `user`, id; `actor=None` | `after`: `file_id`, `result` (`"clean"` или `"quarantine"`), `signature` (только при карантине) | то же |
| `photo.deleted` | `user`, id | `before`: `files` — список `str(uuid)` удалённых файлов `photo` и `photo_pending` (без файла в карантине), без пустых значений; при отсутствии фото событие не пишется | test_photo::test_photo_delete_by_self_or_accounts_manage_quarantine_kept |
| `staff_import.completed` | `staff_import`, `str(item.pk)` | `after`: `file_name`, `send_invites`, `created`, `skipped`, `errors`, `units_created`; содержимого файла нет | test_staff_import_run::test_import_completed_event_and_per_object_events_without_file_content |
| `calendar.settings_changed` | `calendar`, `str(WorkCalendar.pk)` | `before`/`after`: `work_weekdays` (список целых 0…6; на странице журнала — «Пн, Вт, …», дополнение 62), `day_start`, `day_end` (`"ЧЧ:ММ"`) | test_calendar::test_calendar_events_settings_year_loaded_day_changed |
| `calendar.year_loaded` | `calendar`, `str(year)` | `before`: `year`, `totals` (год не был загружен — `{"year": <год>, "totals": {}}`, дополнение 34); `after`: `year`, `totals`, `file_name` | то же |
| `calendar.day_changed` | `calendar`, дата `ГГГГ-ММ-ДД` | `before`: `date`, `kind`; `after`: `date`, `kind` (`""` — обычный день; для дня без записи `before.kind == ""`, дополнение 28) | то же |

Прочее: события `user.created`, `invitation.sent` от загрузки и возврата — коды среза 001;
значения `birth_date` (ни `ГГГГ-ММ-ДД`, ни `ДД.ММ.ГГГГ`) не встречаются ни в одном
событии (`test_org_audit::test_birth_date_value_absent_in_all_events`); ни одно событие не
содержит текста из файлов загрузки и календаря и пути на диске
(`test_file_contents_absent_in_all_events`). `audit_search.actor_text` для
актора в состоянии `dismissed` (в журнале и в истории входов) даёт `"<full_name> (уволен) <email>"`
(пометка сразу после ФИО; остальное как в срезе 001).

`audit_labels` модуля `org` даёт `fields` для каждого ключа таблицы (название по-русски, не равно ключу) и для вложенных ключей словарей `totals` календаря и итогов загрузки, например `holidays_on_weekdays` (дополнение 29: вложенный словарь на странице журнала и в CSV — «название: число; …», латинских ключей в тексте нет), `values` для `kind`, `mode`, `mark`, `reason`, `result`, `state` (значение `dismissed` —
«уволен»); ядро сливает `values` по полям, внутренние словари объединяются; слияние учитывает
`state` и `OBJECT_TYPES` (фильтр вида объекта).

## 7. Ключи Valkey и очереди

| Имя | Что | Тесты |
|---|---|---|
| `perms:<id>` | как в срезе 001, проверка по окончанию имени; удаление идёт после фиксации: проверка — внутри `django_capture_on_commit_callbacks(execute=True)`; ключи сбрасываются при добавлении, переводе, удалении, увольнении (ключ человека); при переносе узла и смене ролей узла (ключи участников поддерева; удаляется только пустой узел — сбрасывать нечего); при смене прав роли (ключи всех записей) | test_org_permissions::test_permission_keys_dropped_on_commit_for_membership_move_delete_and_unit_roles, test_role_permission_change_drops_all_permission_keys; test_permissions (T-2119, п. 7) |
| ключ номера версии календаря | имя оканчивается на `calendar:version` (значение — целое ≥ 0; отсутствующий ключ читается как 0; каждое изменение — `INCR` на фиксации, первое даёт 1) | test_calendar::test_month_marks_cached_by_calendar_version_bumped_by_settings_day_edit_and_file_apply |
| ключ кэша отметок месяца | имя оканчивается на `calendar:marks:<version>:<ГГГГ-ММ>`, например `calendar:marks:3:2027-03`; хранится результат `month_marks`; после смены версии старый ключ не читается | то же, test_date_field |
| очередь `files` | `django_rq.get_queue("files")`; задание `apps.core.tasks.scan_file`, аргумент `str(stored.id)` (раздел 3); тест находит задание так: `[j for j in queue.jobs if j.func_name == "apps.core.tasks.scan_file" and j.args == (str(stored.id),)]`; помощник `support_org.files_jobs()` возвращает `list(queue.jobs)`; повтор после `ScanUnavailable` ждёт в `queue.scheduled_job_registry` | test_photo |
| рабочий процесс | помощник `support_org.run_files_worker()`: `SimpleWorker` на очереди `files`, `burst=True` (как `support_mail.deliver`) | test_photo |

## 8. Маршруты и поля форм

Общие правила (как в срезе 001): все формы — POST с CSRF; без входа — 302 на `/login/`; нет права —
403 (до проверки существования объекта); неизвестный объект или неверный формат адреса — 404. Страницы 403 и 404 — без подробностей: в теле нет `Traceback`, `DoesNotExist`, `matching query`, имён таблиц, SQL, слова `CSRF` и кодов прав (дополнение 42).
Запрос HTMX (`HX`) получает фрагмент без `<html>`, обычный — полную страницу. Отказ службы
(`OrgError`, `AccountError`, `RoleError`, `PhotoError`) на POST — ответ 200 с тем же шаблоном и
`[role=alert]` с текстом, база не меняется; успех — 302 на страницу, указанную в таблице. Успешное сообщение показывается в `[role=status]` страницы, на которую ведёт 302; у форм среза оно есть после каждого успешного POST, текст непустой (дополнение 51); это `[role=status]` вне `[data-notice]` — напоминание календаря тоже `role="status"` (дополнение 56). Статус отказа — 200, как
в срезе 001 (CONTRACT.md:77–78); прямой POST на удаление или перенос корня — 200 с `[role=alert]`
(`root_protected`); присланное `birth_date` в форме администратора — 200 (`AccountError`).

### 8.1 Список и карточка ядра

| Путь | Метод, параметры, поля | Что ожидают тесты | Тесты |
|---|---|---|---|
| `/staff/` | GET `q`, `state`, `role`, `unit`, `sort`, `page` | 200; `state` пустой — «В компании» (все, кроме `dismissed`); `state=dismissed` — «Уволены»; `state=no_unit` — не уволенные без членств; `state=all` — все; для `accounts.manage` ещё `invited`, `active`, `blocked` и `role` (id) — как в срезе 001; `unit` — id узла (члены узла и вложенных); `q` — вхождение в ФИО, должность, почту, телефон, внутренний телефон, место работы, название узла (без учёта регистра и «е/ё»). Значение `state` вне разрешённых смотрящему и неизвестное — как пустое; `role` без `accounts.manage` игнорируется | test_staff_search, test_permissions, test_org_permissions |
| `/staff/<id>/` | GET | 200 по `staff.view` или `accounts.manage`, иначе 403; обе вкладки в одном ответе (решение 9; вкладка «Безопасность» делится на части `[data-security-part="account"]` — у `accounts.manage` — и `[data-security-part="logins"]` — у `accounts.view_logins`; части без права в ответе нет, `[data-field="state"]` лежит только в первой, дополнение 4); у смотрящего без `accounts.manage` и `accounts.view_logins` вкладки «Безопасность» и её данных в ответе нет; `/staff/<id>/logins/` и действия карточки среза 001 — 403 прежним правам; `/staff/<свой id>/` — по правилам смотрящего, как любая карточка (без `staff.view` и `accounts.manage` — 403, дополнение 67; вкладки по правам, дата рождения — день и месяц); полная карточка с обеими вкладками и полной датой — только `/me/` | test_staff_card, test_org_permissions::test_colleague_sees_no_service_fields_security_tab_absent_and_403 |
| `/staff/<id>/edit/` | POST `full_name`, `position`, `phone`, `email`, `contacts`, `internal_phone`, `workplace` | 302 на `/staff/<id>/`; присланное `birth_date` (в том числе пустое) — 200 с `[role=alert]`, ничего не меняется (дополнение 61); над уволенным — 200 с `[role=alert]` | test_staff_card, test_org_dismissal |
| `/staff/<id>/photo/<uuid>/<512\|96>/` | GET | см. 8.2 | test_photo |
| `/staff/<id>/photo/delete/` | POST (без полей) | 302 на `/staff/<id>/`; только `accounts.manage`, иначе 403; фото нет — тоже 302, без события (дополнение 49) | test_photo |
| `/me/` | GET; POST `phone`, `contacts`, `internal_phone`, `workplace`, `birth_date` (ДД.ММ.ГГГГ или ГГГГ-ММ-ДД; пустое — стереть) | свой профиль с обеими вкладками (вкладка «Безопасность» содержит тот же блок, что `/me/security/`: `data-backup-remaining` и т. д.; `/me/security/*` среза 001 не меняются); успех — 302 на `/me/`; неверная дата — 200 с `[role=alert]` | test_staff_card |
| `/me/photo/` | POST multipart, поле файла `photo` | успех — 302 на `/me/`; отказ — 200 с `[role=alert]`, `StoredFile` не создан; прежнее чистое фото остаётся | test_photo |
| `/me/photo/delete/` | POST | 302 на `/me/`; фото нет — тоже 302, ничего не меняется, события нет (дополнение 49) | test_photo |
| `/ui/date-picker/` | GET `month=ГГГГ-ММ` | 200 фрагмент (всегда без `<html>`, даже без `HX`), любому вошедшему, право не нужно; без входа 302; `month` пустой или неверный (в том числе год вне 1900…2100) — текущий месяц по Москве (дополнение 24); фрагмент — раздел 9.6 | test_date_field |

### 8.2 Выдача фото

`GET /staff/<id>/photo/<uuid>/<size>/`, `size` — строка маршрута, только `512` или `96` (неверный —
404 после входа и права). Порядок:
вход (иначе 302), право (`staff.view`, `accounts.manage` или `id` смотрящего; иначе 403), затем
проверки 404: пользователь есть, `uuid` равен `user.photo_id` и `StoredFile.status == "clean"`.
Успех — 200, пустое тело, заголовки: `X-Accel-Redirect: /protected/photos/<uuid>-<size>.jpg`,
`Content-Type: image/jpeg`, `X-Content-Type-Options: nosniff`, `Cache-Control: private,
max-age=86400` (исключение из `no-store` — только этот маршрут). Тесты: test_photo, test_org_pages.

### 8.3 Структура

| Путь | Метод, параметры, поля | Что ожидают тесты | Тесты |
|---|---|---|---|
| `/structure/` | GET | 200, дерево и карточка: есть свои узлы — первого из них по `path` (из `units_of`); нет — корня | test_org_structure |
| `/structure/<id>/` | GET `q` | `HX` — фрагмент карточки `[data-unit-card]`; обычный — страница целиком с деревом; `q` — фильтр участников по ФИО и должности без учёта регистра и «е/ё» | test_org_structure, test_org_pages |
| `/structure/new/` | GET `parent` (id, подставляет «Подчиняется»); POST `kind` (`department`/`team`), `name`, `description`, `parent` (id) | 302 на `/structure/<новый id>/`; отказ — 200 с `[role=alert]`; без `org.manage` — 403 | test_org_structure |
| `/structure/<id>/edit/` | GET; POST `name`, `description`, `parent` | 302 на `/structure/<id>/`; для корня поля `parent` в форме нет, присланное `parent` — 200 с `[role=alert]` (`root_protected`) | test_org_structure |
| `/structure/<id>/delete/` | GET — диалог; POST `confirm=1` (без `confirm=1` — 200 с `[role=alert]` «Подтвердите удаление», узел не удаляется, событий нет, дополнение 21) | GET показывает подтверждение и ничего не меняет; POST — 302 на `/structure/`; корень и непустой узел — 200 с `[role=alert]` | test_org_structure |
| `/structure/<id>/candidates/` | GET `q` | всегда фрагмент: не более 20 (число — решение Opus; первые 20 из `accounts.pickable(q)` по `full_name`, затем `id`; подходящих больше — ровно 20, дополнение 2) элементов `[data-candidate][data-user-id]` из `accounts.pickable(q)`; уволенных нет | test_org_membership::test_candidates_exclude_dismissed |
| `/structure/<id>/members/` | POST `users` (повторяющееся поле, id), `mode` (`transfer`/`concurrent`; у команды поля нет) | 302 на `/structure/<id>/`; уже участники — `[role=status]` со словами «уже участник» | test_org_membership |
| `/structure/<id>/members/<user_id>/transfer/` | POST `target` (id узла) | 302 на `/structure/<id>/`; другой вид — 200 с `[role=alert]`; цель — узел, где человек уже участник: 302 и `[role=status]` «уже участник», членства не меняются | test_org_membership |
| `/structure/<id>/members/<user_id>/remove/` | POST | 302 на `/structure/<id>/` | test_org_membership |
| `/structure/<id>/marks/` | POST `part` (`heads` или `deputies`; в форме — скрытое поле `input[type=hidden][name=part]` внутри `form[data-form="marks-heads"]` или `form[data-form="marks-deputies"]`, дополнение 3) и повторяющееся `users` (id участников; нет ни одного — набор пуст); форма «Руководители» шлёт `part=heads`, «Заместители» — `part=deputies`; другой набор не меняется | 302 на `/structure/<id>/`; отказ — 200 с `[role=alert]` | test_org_membership |
| `/structure/<id>/roles/` | POST `roles` (повторяющееся поле, id ролей) | 302 на `/structure/<id>/`; право `roles.manage` (не `org.manage`) | test_org_permissions::test_unit_roles_need_roles_manage_not_org_manage |
| `/structure/people/<user_id>/dismiss/` | GET — диалог; POST (необязательное `next`, относительный путь; чужой хост игнорируется) | GET — фрагмент `[data-dialog="dismiss"]`, ничего не меняет, журнал не пополняется; POST — 302 на `next` или `/staff/<id>/` | test_org_dismissal |
| `/structure/people/<user_id>/rehire/` | GET — диалог `[data-dialog="rehire"]`; POST | POST для не уволенного — 200 с `[role=alert]`; успех — 302 на `/staff/<id>/` | test_org_dismissal |
| `/structure/import/` | GET; POST multipart `file` | успех — 302 на `/structure/import/<id>/`; отказ — 200 с `[role=alert]`; нужны оба права `accounts.manage` и `org.manage`, иначе 403 | test_staff_import_file |
| `/structure/import/<id>/` | GET; POST `send_invites` (`1` или нет поля) | GET `state="preview"` — предпросмотр, `done` — итог; POST — 302 на `/structure/import/<id>/`; повторный POST по `done` — тот же 302, ничего не выполняется и нового события нет; стёртый или несуществующий предпросмотр — 404 (дополнение 31) | test_staff_import_run::test_confirm_twice_shows_same_result_does_nothing |
| `/structure/import/sample.csv`, `/structure/import/sample.xlsx` | GET | 200; `Content-Type` `text/csv; charset=utf-8` и `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`; `Content-Disposition: attachment`; оба права нужны | test_staff_import_file::test_import_and_samples_need_both_permissions |

### 8.4 Календарь

| Путь | Метод, параметры, поля | Что ожидают тесты | Тесты |
|---|---|---|---|
| `/calendar/` | GET `year` (по умолчанию текущий по Москве; нечисловой или вне 2000…2100 — как по умолчанию) | 200 по `staff.view` или `calendar.manage`, иначе 403; 12 месяцев | test_calendar |
| `/calendar/settings/` | POST `work_weekdays` (повторяющееся поле, значения `0`…`6`), `day_start`, `day_end` (`ЧЧ:ММ`) | 302 на `/calendar/`; отказ — 200 с `[role=alert]` | test_calendar |
| `/calendar/upload/` | GET; POST multipart `year` (целое), `file` | успех — 302 на `/calendar/upload/<id>/`; отказ — 200 с `[role=alert]` | test_calendar_file |
| `/calendar/upload/<id>/` | GET; POST `confirm=1` | GET — предпросмотр (9.5); POST — 302 на `/calendar/?year=<год>`; повторный POST по `applied` — тот же 302, без действия; стёртый или несуществующий предпросмотр — 404 (дополнение 31) | test_calendar_file |
| `/calendar/days/<ГГГГ-ММ-ДД>/` | GET — форма; POST `kind` (`""`, `holiday`, `day_off`, `workday`, `short`) | 302 на `/calendar/?year=<год>`; год не загружен — 200 с `[role=alert]`; неверная дата в адресе (например, `2027-02-30`) — 404 | test_calendar |

## 9. Зацепки разметки

Тесты ищут элементы по атрибутам `data-*` и `role`, не по классам и не по тексту, кроме случаев,
где подпись названа дословно. В разметке нет встроенных скриптов и обработчиков (CSP).

### 9.1 Дерево и карточка узла (`/structure/`)

| Зацепка | Что | Тесты |
|---|---|---|
| `[data-unit-tree]` | корневой `<ul>` дерева; узел — `<li data-unit-id="<id>" data-kind="department\|team" data-own="true\|false">`; раскрытие — `<details>` внутри `li` (у узла с вложенными: `<details>` → `<summary>` с переключателем `[data-unit-toggle]` и ссылкой `a[data-unit-link]`, затем `<ul>` вложенных; у узла без вложенных `<details>` нет; дополнение 53); `/structure/` отдаёт в разметке всё дерево (все узлы, без догрузки; план: дерево читается одним запросом, дополнение 44) | test_org_structure::test_structure_page_tree_details_and_card_with_own_url_and_fragment, test_org_structure::test_own_units_highlighted_and_search_in_unit_case_and_yo_insensitive |
| свой узел | `data-own="true"` и класс `unit-own`; у остальных `data-own="false"` | то же |
| `<details open>` | у корня и у всех предков выбранного узла; у остальных — закрыт | test_org_structure |
| `a[data-unit-link]` | ссылка узла: `href="/structure/<id>/"`, `hx-get` на тот же адрес, цель `#unit-card`, `hx-push-url="true"` | test_org_pages::test_htmx_request_gets_fragment_plain_request_full_page |
| `#unit-card` | контейнер карточки; внутри `[data-unit-card][data-unit-id][data-kind]` | test_org_structure |
| `[data-unit-name]`, `[data-unit-description]`, `[data-unit-parent]`, `[data-unit-role]` | в карточке: название, описание, «Подчиняется», роли узла (`[data-unit-role]` по одной на роль, текст — название); у `a[data-unit-link]` выбранного узла `aria-current="true"` | test_org_structure, test_org_permissions |
| `[data-structure-layout]` | контейнер раскладки дерева и карточки; серверный тест T-2121 проверяет `meta viewport` и наличие контейнера, а что дерево над карточкой на 360 px, — Playwright (T-2142, `test_o04_structure_at_360px_tree_above_card`) | test_org_pages |
| `[data-section="heads"]`, `[data-section="deputies"]`, `[data-section="members"]` | три раздела карточки | test_org_structure::test_card_lists_heads_deputies_members_with_position_and_photo |
| `[data-member][data-user-id][data-mark="head\|deputy\|"]` | строка участника; `data-mark` пустой, если отметки нет; внутри `[data-member-name]`, `[data-member-position]`, `[data-photo]` (9.4) | то же |
| `[data-mark-label]` | в строке участника с отметкой: текст «Руководитель» или «Заместитель» (дословно); без отметки элемента нет | test_org_membership, test_org_heads |
| `input[name=q]` в карточке | поиск участников: `hx-get` на `/structure/<id>/`, `hx-trigger="input changed delay:300ms"`, цель `#unit-card` | test_org_structure |
| `[data-empty-state="tree\|unit\|search"]` | пустые состояния с непустым пояснением (FR-109): `tree` — в дереве только корень; `unit` — у выбранного узла нет ни одного участника (вложенные узлы могут быть); `search` — задан `q`, совпадений нет; у `tree` и `unit` для `org.manage` внутри своего `[data-empty-state]` кнопка действия (`[data-action="unit-new"]`, `[data-action="members-add"]`; дополнения 5, 30) | test_org_structure::test_empty_tree_unit_and_search_explained |
| действия (только `org.manage`; при отсутствии права элементов нет в ответе; место — дополнение 50: «Создать» `unit-new` — в шапке страницы вне `[data-unit-tree]` и `[data-unit-card]`, действия выбранного узла — внутри `[data-unit-card]`) | `[data-action="unit-new"]`, `[data-action="unit-edit"]`, `[data-action="unit-delete"]` (у корня нет), `[data-action="members-add"]` (у отдела внутри формы `select[name=mode]` с `option` `transfer` и `concurrent`), `[data-action="marks-heads"]`, `[data-action="marks-deputies"]`; `[data-action="unit-roles"]` — по праву `roles.manage`; `members-add`, `marks-heads`, `marks-deputies`, `unit-roles` — каждое `<details data-action="…">` с формой внутри (9.8) | test_org_structure::test_view_needs_staff_view_changes_need_org_manage, test_org_membership |
| перетаскивания нет | в разметке дерева нет `draggable`, `data-drag*`, и нет маршрута `/structure/<id>/move/` | test_org_structure::test_no_drag_and_drop_route_move_only_by_parent_field |

### 9.2 Меню «…» участника

| Зацепка | Что | Тесты |
|---|---|---|
| `[data-member-menu]` | `<details>` в строке участника (только `org.manage`); кнопка раскрытия — `<summary data-member-menu-button aria-label="Действия">…</summary>` | test_org_membership::test_member_menu_transfer_same_kind_remove_and_dismiss_items |
| `[data-menu-item="transfer\|remove\|dismiss"]` | пункты меню; подписи в карточке отдела: «Перевести в другой отдел», «Удалить из отдела», «Уволить»; в карточке команды: «Перевести в другую команду», «Удалить из команды», «Уволить» (дословно) | то же |
| `dismiss` | `a[hx-get="/structure/people/<id>/dismiss/"]` (диалог в `#dialog-root`, 9.8); `transfer` — форма POST на `…/transfer/` с `select[name=target]` (узлы того же вида); `remove` — форма POST на `…/remove/` | то же |

### 9.3 Вкладки карточки сотрудника (решение 9)

| Зацепка | Что | Тесты |
|---|---|---|
| `[data-card][data-user-id]` | корень карточки на `/staff/<id>/` и `/me/` | test_staff_card |
| `[data-tab-button="profile\|security"]` | кнопки переключателя (`<button type="button" role="tab">`); у активной `aria-selected="true"`; на чужой карточке кнопка и панель `security` есть у обладателя `accounts.manage` или `accounts.view_logins` (хотя бы одного), без обоих — нет ни кнопки, ни панели; на `/me/` обе вкладки всегда, панель `security` несёт тот же блок, что `/me/security/` (например, `[data-backup-remaining]`), независимо от прав (§ 11 п. 15, дополнения 4, 35) | test_staff_card::test_card_tabs_profile_and_security_empty_fields_not_filled, test_own_card_has_both_tabs |
| `[data-tab-panel="profile\|security"]` | обе панели лежат в одном ответе (и во фрагменте HTMX); неактивная несёт атрибут `hidden`; по умолчанию открыт `profile` (панель `security` с `hidden`); переключатель — внешний скрипт, без встроенных | то же |
| `[data-tab-panel="security"] [data-security-part="account\|logins"]` | части вкладки «Безопасность»: `account`: состояние `[data-field="state"]`, приглашение, блокировка и разблокировка — у `accounts.manage`, сброс второго фактора — там же, но по праву `accounts.reset_2fa` (дополнение 66); `logins`: устройства и история входов, ссылка на `/staff/<id>/logins/` — у `accounts.view_logins`; части без права в ответе нет (дополнение 4) | test_org_permissions, test_staff_card |
| `[data-field="<имя>"]` | значение поля: `full_name`, `position`, `email`, `phone`, `internal_phone`, `workplace`, `birth_date`, `units`, `head`, `subordinates`, `state`; у каждого `data-empty="true\|false"`; пустое поле — текст «не заполнено» (для `head` — «не назначен»; `head` у человека без членств — `data-empty="true"`; для `units` — «не заполнено»; для `subordinates` — «нет», и поле выводится только у руководителя хотя бы одного узла); `state` — только у смотрящего с `accounts.manage`, у остальных поля нет; лежит только внутри `[data-security-part="account"]` вкладки «Безопасность» (подробно — дополнение 4), у уволенного `[data-field="state"]` нет — состояние показывает `[data-dismissed-badge]` рядом с ФИО; остальные поля выводятся как обычно, `units` у уволенного — `data-empty="true"`, «не заполнено» (дополнения 13, 36) | test_staff_card, test_org_heads, test_org_dismissal |
| `[data-field-label="<имя>"]` | подпись поля рядом со своим `[data-field="<имя>"]`, по-русски: `position` — «Должность», `email` — «Почта», `phone` — «Телефон», `internal_phone` — «Внутренний телефон», `workplace` — «Место работы», `birth_date` — «Дата рождения», `units` — «Подразделение», `head` — «Руководитель», `subordinates` — «Подчинённые», `state` — «Состояние»; подпись `full_name` контракт не задаёт, тесты её не ищут (дополнения 20, 30) | test_org_heads, test_staff_card |
| `[data-field="units"]` | названия узлов через запятую и пробел в порядке `path` — байтовом, как `sorted()` по `path` узлов, не по порядку создания: «Сеть, Поддержка» (дополнения 1, 18) | test_org_membership::test_one_position_many_units_listed_by_comma |
| `[data-field="head"]` | один узел — имена руководителей через запятую; несколько узлов — «Сеть: Иванов; Поддержка: Петров» (названия узла и имена через «: » и «; »); нет руководителей — «не назначен»; имена руководителей внутри узла — через «, » | test_org_heads::test_concurrent_employee_heads_shown_per_unit, test_not_assigned_when_no_heads_up_to_root |
| `[data-field="birth_date"]` | чужая карточка — «5 марта» (день без нуля и месяц в родительном падеже, без года); своя (`/me/`) — `ДД.ММ.ГГГГ` | test_staff_card::test_colleagues_see_day_and_month_year_only_self |
| `[data-dismissed-badge]` | у уволенного рядом с ФИО, текст «уволен» | test_org_dismissal |
| `[data-person-name]` | на `/staff/<id>/logins/` заголовок с именем; у уволенного текст `"<full_name> (уволен)"` (дополнение 12) | test_org_dismissal |
| `[data-roles-group="personal"]`, `[data-roles-group="unit"][data-source-unit="<название>"]` | группы ролей в «Профиле» у `accounts.manage`; заголовок группы «лично» или «от подразделения <название>»; роль — `[data-role-name]` | test_org_permissions::test_card_roles_grouped_personal_and_by_unit_source |
| `[data-action="dismiss"]`, `[data-action="rehire"]` | ссылки с `hx-get` на диалоги (8.3); видит обладатель `org.manage` (решение 8); «Уволить» показывается обладателю `org.manage` у любой неуволенной записи, в том числе у себя и у последнего администратора, отказ даёт POST (200 с `[role=alert]`); «Вернуть на работу» только у уволенного | test_org_dismissal::test_dismiss_and_rehire_need_org_manage_buttons_only_with_it |
| `[data-dialog="dismiss"]`, `[data-dialog="rehire"]` | диалог подтверждения: перечень последствий в `[data-consequence]` (по одному на последствие), форма POST с `button[type=submit]`, кнопка `button[data-dialog-cancel]` с текстом «Отмена» (запросов не шлёт) | test_org_dismissal::test_dismiss_dialog_get_shows_consequences_and_changes_nothing |
| `[data-photo-status="pending\|failed"]` | на своей карточке: «Фото проверяется» (подпись — решение Opus по T-2100a) и «Фото не прошло проверку» (plan.md:408) | test_photo::test_found_scan_quarantines_keeps_previous_photo_user_sees_failed |

### 9.4 Список «Сотрудники», фото и заглушка

| Зацепка | Что | Тесты |
|---|---|---|
| `tr[data-user-id][data-user-email][data-state]` | у обладателя `accounts.manage` — `data-state`, как в срезе 001 (`dismissed` тоже); у смотрящего без `accounts.manage` (коллеги) атрибута `data-state` нет (служебные состояния скрыты, FR-119), а у строки уволенного — `data-dismissed="true"` (дополнение 22) | test_staff_search, test_org_dismissal |
| `[data-cell="photo\|name\|position\|unit\|internal-phone\|email\|state"]` | ячейки строки; `state` только у `accounts.manage`; ячейки с данными для `unit` — названия через запятую | test_staff_search::test_columns_photo_name_position_unit_internal_phone_email |
| `[data-cell="name"] a` | ячейка `name` — `a[href="/staff/<id>/"]` со слайдером, как в срезе 001 (templates/staff/_results.html); колонки — ровно по плану (plan.md:366–368), колонки ролей нет; выбор состояния — ссылками пресетов, параметр `state` прежний | test_staff_search |
| `[data-photo]` | контейнер фото в списке, дереве, карточках: или `<img data-photo-img src="/staff/<id>/photo/<uuid>/96/">`, или заглушка `<span data-photo-placeholder data-initials="ИП">ИП</span>` | test_photo::test_initials_placeholder_until_clean_in_card_list_and_structure |
| инициалы | первые буквы первых двух слов `full_name` в верхнем регистре; слово одно — одна буква | то же |
| `a[data-preset]` | ссылки пресетов; значение равно параметру `state` (`""` — «В компании», `dismissed`, `no_unit`, `all`, `invited`, `active`, `blocked`); активный — `aria-current="true"`; подписи: «В компании», «Уволены», «Без подразделения», «Все», «Приглашены», «Активные», «Заблокированные»; первые четыре («В компании», «Уволены», «Без подразделения», «Все») доступны всем со `staff.view`, `state=all` у коллеги — все записи, включая уволенных; «Приглашены», «Активные», «Заблокированные» и фильтр роли — только `accounts.manage` (дополнение 15) | test_staff_search::test_presets_in_company_default_dismissed_without_unit_all, test_service_presets_role_filter_and_state_column_only_with_accounts_manage |
| `select[name=unit]` | фильтр «Подразделение»: первый `option value=""` («Все подразделения» — решение Opus) и по одной на узел, `value` — id | test_staff_search::test_unit_filter_includes_nested_units |
| `input[name=q]` | строка поиска списка | test_staff_search |
| `a[data-action="staff-import"]` | кнопка «Загрузить из таблицы», `href="/structure/import/"`; только при обоих правах | test_staff_import_file |

### 9.5 Календарь и загрузки

| Зацепка | Что | Тесты |
|---|---|---|
| `[data-calendar-year][data-year][data-loaded="true\|false"]` | контейнер года на `/calendar/` | test_calendar::test_calendar_page_12_months_marks_not_only_color_legend_year_choice |
| `[data-month="1"…"12"]` | двенадцать месяцев; сетка каждого месяца — как у поля даты (9.6, дополнение 23): `table`, `thead th` с текстами «Пн», «Вт», «Ср», «Чт», «Пт», «Сб», «Вс» по порядку, `tbody tr[data-week]` по 7 `td`, дни вне месяца — пустые `td` без кнопки; неделя с понедельника (дополнение 28) | то же |
| `td[data-date="ГГГГ-ММ-ДД"][data-day-kind="work\|off\|holiday\|day_off\|workday\|short"]` | ячейка дня (буквы и подписи — решение Opus, G1); внутри `<span class="cal-letter">` (буква: `off` — «В», `holiday` — «П», `day_off` — «Н», `workday` — «Р», `short` — «С»; у `work` буквы нет) и `<span class="visually-hidden">` с подписью (`off` — «выходной», `holiday` — «праздник», `day_off` — «перенесённый выходной», `workday` — «перенесённый рабочий день», `short` — «сокращённый день»; у `work` подписи нет); класс `cal-<вид>`; у `td` дня вне месяца `data-date` нет (дополнение 60) | то же, test_o13 |
| `[data-legend]` | легенда: по элементу `[data-legend-item="off\|holiday\|day_off\|workday\|short"]` с той же буквой и подписью, что в ячейке | то же |
| выбор года | `select[name=year]` (форма GET на `/calendar/`) со всеми годами от текущего −1 до текущего +1 и всеми загруженными; каждый `option value="<год>"`; `year` вне 2000…2100 и нечисловой — текущий (решения Opus; граница именно для `/calendar/?year=`, у сетки поля даты — 1900…2100, дополнение 24) | то же |
| `a[data-day-edit][href="/calendar/days/<дата>/"]` | у `calendar.manage` в загруженном году: ссылка в ячейке; в незагруженном и без права — нет | test_calendar::test_calendar_page_with_staff_view_or_calendar_manage_settings_and_day_edit_need_calendar_manage |
| `form[action="/calendar/settings/"]` | форма недели и часов (только `calendar.manage`): `input[type=checkbox][name=work_weekdays][value="0".."6"]` (отмечены рабочие), `input[name=day_start]`, `input[name=day_end]`, значение каждого — `ЧЧ:ММ` (дополнение 28) | test_calendar |
| `a[data-action="calendar-upload"]` | ссылка на `/calendar/upload/` (только `calendar.manage`) | test_calendar |
| `[data-format-help]` | на странице загрузки: описание формата и места, где взять файл | test_calendar_file |
| `[data-calendar-preview]` | предпросмотр: `data-holidays`, `data-day-offs`, `data-workdays`, `data-shorts`, `data-work-days` — числа из `totals`; `[data-manual-warning][data-manual-days="<N>"]` при `manual_days > 0`; `[data-weekend-holiday-warning]` при `weekend_work`; форма подтверждения: `input[name=confirm][value="1"]` и кнопка | test_calendar_file |
| `[data-notice="calendar-year"][data-year="<год>"]` | напоминание (`role="status"`) на `/` и `/calendar/` у обладателя `calendar.manage`; на `/` внутри `[data-home-notices]`; текст «Не загружен производственный календарь на <год> год.» и ссылка «Загрузить файл» на `/calendar/upload/`, по одному напоминанию на год из `missing_years` (решение Opus) | test_calendar::test_reminder_whole_year_when_current_missing_and_from_december_for_next, test_org_pages |
| `form[data-form="calendar-day"][action="/calendar/days/<дата>/"]` | форма дня: `select[name=kind]` с `option` `""` («обычный день»), `holiday`, `day_off`, `workday`, `short` (выбран текущий вид), `button[type=submit]` | test_calendar |
| `form[data-form="calendar-upload"]` | форма загрузки на `/calendar/upload/`: `input[name=year]` и `input[type=file][name=file]`, `button[type=submit]` | test_calendar_file |

### 9.6 Поле даты и сетка

| Зацепка | Что | Тесты |
|---|---|---|
| `[data-datefield]` | обёртка виджета; внутри `input[type=text][data-datefield-input]` (`inputmode="numeric"`, `placeholder="ДД.ММ.ГГГГ"`), кнопка `button[type=button][data-datefield-open]` с текстом «Выбрать дату» и контейнер `[data-datefield-picker]` (`hidden`) | test_date_field::test_every_portal_datefield_uses_portal_widget, test_o13_date_field |
| запрос сетки | кнопка открытия несёт `hx-get="/ui/date-picker/?month=ГГГГ-ММ"`, цель — контейнер своего поля; значение поля в адрес не попадает; `month` с годом 1900…2100 принимается, вне этого — текущий месяц (дополнение 24; для `/calendar/?year=` граница прежняя — 2000…2100) | test_date_field::test_field_value_not_in_picker_request |
| `[data-datefield-grid][data-month="ГГГГ-ММ"]` | корень фрагмента сетки; заголовок дней «Пн…Вс» с понедельника; кнопки `[data-datefield-prev]`, `[data-datefield-next]` (`hx-get` на соседний месяц); `select[name=month]` (значения `1`…`12`) и `select[name=year]` — годы от 1900 до текущего +5, год показанной сетки всегда в списке; `table`: `thead th` «Пн»…«Вс» по порядку, `tbody tr[data-week]` по 7 `td`, дни вне месяца — пустые `td` без кнопки (например, 1 ноября 2026, воскресенье, — седьмая ячейка первой недели; дополнения 23, 24) | test_date_field::test_date_picker_grid_monday_first_with_day_marks |
| день | `<button type="button" data-date="ГГГГ-ММ-ДД" data-day-kind="work\|off\|holiday\|day_off\|workday\|short">N</button>`; у `off`, `holiday`, `day_off`, `workday`, `short` — класс `date-day-<вид>` и `<span class="visually-hidden">` с подписью из 9.5; кнопка есть у каждого дня месяца и не `disabled` (выбрать можно любой, в том числе праздник) | test_date_field::test_any_day_selectable_including_holiday, test_date_picker_without_org_marks_saturday_and_sunday |
| скрипт | `static/js/datefield.js` подключён тегом `<script src>` с `{% static %}` (внешний файл); в шаблонах и ответах нет `eval`, `new Function`, `onclick=` и подобных встроенных обработчиков; в `datefield.js` нет `eval(` | test_date_field::test_datefield_script_external_delegated_without_eval |
| выбранный день и фокус | выбранный день — `aria-pressed="true"` у его кнопки; фокус — `:focus` на `button[data-date]`; стрелки влево/вправо — ±1 день, вверх/вниз — ±7 дней (переход через край месяца загружает соседний месяц); PageUp/PageDown — предыдущий/следующий месяц (тот же день или последний день месяца); Home/End — понедельник/воскресенье той же недели; Enter — пишет дату в поле в виде `ДД.ММ.ГГГГ` и закрывает сетку; Esc — закрывает сетку, фокус на кнопку «Выбрать дату»; щелчок по дню — как Enter; при открытии сетка показывает текущий месяц по Москве (дополнение 63), фокус — на выбранном дне, если он в этом месяце, иначе на сегодняшнем; смена `select[name=month]` или `select[name=year]` сразу запрашивает сетку (дополнение 59) | test_date_field, T-2148 |
| контейнер сетки | `id="<id поля ввода>-picker"`; у кнопки открытия `hx-target="#<id поля ввода>-picker"` | test_date_field |
| `type="date"` | ни в одном файле `templates/**/*.html` нет `type="date"`; у каждого `forms.DateField` портала виджет `PortalDateInput` (тест обходит все модули `apps/*/forms.py` и `apps/*/forms/*.py`) | test_date_field::test_no_native_date_inputs_in_templates, test_every_portal_datefield_uses_portal_widget |

### 9.7 Загрузка сотрудников (`/structure/import/`, `/structure/import/<id>/`)

| Зацепка | Что | Тесты |
|---|---|---|
| `form[data-form="import-upload"]` | форма загрузки с `input[type=file][name=file]` | test_staff_import_file |
| `[data-import-preview]` | предпросмотр | test_staff_import_run |
| `tr[data-import-row][data-row-number="<N>"][data-row-result="will_create\|skipped\|error"]` | строка предпросмотра (после выполнения `created`, `skipped`, `error`); внутри `[data-row-reason]`, у почты уволенного ещё `[data-row-hint="dismissed"]` | test_staff_import_run |
| `[data-import-new-units] li` | новые узлы, по пути на элемент | test_staff_import_run |
| `[data-import-not-loaded] li` | лишние колонки («не загружаются») | test_staff_import_file |
| `form[data-form="import-confirm"]` | форма подтверждения: `input[type=checkbox][name=send_invites][value="1"]`, `button[type=submit]` | test_staff_import_run |
| `[data-result-summary]` | итог после выполнения | test_staff_import_run |

### 9.8 Формы и диалоги

- формы `unit-new`, `unit-edit` (поля — дополнение 45: `select[name=kind]` только в `unit-new`, `[name=name]`, `[name=description]`, `select[name=parent]` со всеми узлами дерева по `path`) открываются в `#slider-root` страницы `/structure/` (`hx-get` на
  GET-маршрут; обычный GET — полная страница с формой), как формы карточки среза 001
  (templates/staff/list.html:41, _slider.html);
- диалоги подтверждения `unit-delete`, `dismiss`, `rehire` открываются в `#dialog-root` — новый
  контейнер на страницах `/structure/` и `/staff/` (и `/staff/<id>/`, который рисует список со
  слайдером), рядом с `#slider-root`; диалог —
  `[data-dialog="unit-delete|dismiss|rehire"][role="dialog"][aria-modal="true"]`; «Отмена» —
  `button[data-dialog-cancel]` закрывает диалог внешним скриптом, запросов не шлёт;
- формы в карточке узла (без отдельного GET; обычный POST без `hx-post`, успех — 302 и страница целиком, дополнение 54): `members-add`, `marks-heads`, `marks-deputies`,
  `unit-roles` — каждая внутри `<details data-action="…">` (в `marks-*` — флажок `input[type=checkbox][name=users][value="<id>"]` на каждого участника узла, в `unit-roles` — `input[type=checkbox][name=roles][value="<id>"]` на каждую роль портала, отмечен текущий набор; дополнение 46), сама форма
  `form[data-form="<то же имя>"]` с `button[type=submit]`; в `members-add` — поле `input[name=q]`
  с `hx-get` на `/structure/<id>/candidates/` и целью `[data-candidates]`; кандидат —
  `label[data-candidate][data-user-id]` с `input[type=checkbox][name=users][value="<id>"]`; подсказок не больше 20 — первые 20 из `accounts.pickable(q)` по `full_name`, затем `id` (дополнение 2); у
  отдела — `select[name=mode]`; формы `marks-heads` и `marks-deputies` шлют `part=heads` и `part=deputies` скрытым полем `input[type=hidden][name=part]` внутри своей `form[data-form=…]` (8.3, дополнение 3);
- формы меню «…»: `form[data-form="member-transfer"]` (`select[name=target]`),
  `form[data-form="member-remove"]`;
- в диалоге `unit-delete` форма несёт `input[type=hidden][name=confirm][value="1"]` (дополнение 47);
- у остальных форм — `form[data-form="unit-new|unit-edit|unit-delete|dismiss|rehire|
  calendar-settings|calendar-upload|calendar-day"]`;
- `next` в форме увольнения — скрытое `input[name=next]` с путём страницы, откуда открыт диалог.

## 10. Тексты, которые ищут тесты

Дословно из спеки (`specs/002-org/spec.md`, SPEC-002) или плана (`specs/002-org/plan.md`,
PLAN-002), с адресом источника. Подписи нужны как подстрока видимого текста ответа или значения
`str(error)`; регистр первой буквы не проверяется.

| Подпись | Где | Источник | Тесты |
|---|---|---|---|
| «уже участник» | `[role=status]` после повторного добавления | SPEC-002, сценарий 2, п. 7 | test_org_membership |
| «Руководитель», «Заместитель» | метки участника | SPEC-002, сценарий 3 | test_org_membership, test_org_heads |
| «не назначен» | `[data-field="head"]` | SPEC-002, сценарий 3, п. 5; PLAN-002, «Руководитель в карточке» | test_org_heads |
| «не заполнено» | пустое поле карточки | PLAN-002, «Вкладки»; SPEC-002, сценарий 10, п. 8 | test_staff_card |
| «(уволен)» | имя уволенного в журнале (через `audit_search.actor_text`: `"<full_name> (уволен) <email>"`) и в истории входов (`[data-person-name]`: `"<full_name> (уволен)"`, дополнение 12) | PLAN-002, «Уволенные в интерфейсе» (plan.md:345); SPEC-002, сценарий 7, п. 5 — слово без скобок | test_org_dismissal |
| «уволен» | метка в карточке и пресет «Уволены» | SPEC-002, сценарий 7, п. 3 | test_org_dismissal |
| «такая почта уже есть» | строка предпросмотра («пропущен: такая почта уже есть») | SPEC-002, сценарий 5, п. 2 и п. 8 | test_staff_import_run |
| «уволен: верните его из карточки» | подсказка в строке с почтой уволенного | SPEC-002, сценарий 5, п. 2 | test_staff_import_run |
| «будет создан», «пропущен», «ошибка» | подписи итога строки (`ошибка: <причина>`) | SPEC-002, сценарий 5 | test_staff_import_run |
| «не загружаются» | про лишние колонки | PLAN-002, «Заголовки» | test_staff_import_file |
| «Отправить приглашения сразу» | подпись флажка `send_invites` | SPEC-002, сценарий 5; PLAN-002, «Подтверждение» | test_staff_import_run |
| «создано N, пропущено M, с ошибками K» (числа подставлены) | `[data-result-summary]` итога | SPEC-002, сценарий 5, п. 5; PLAN-002, «Подтверждение» | test_staff_import_run |
| «Загрузить из таблицы» | кнопка списка | PLAN-002, «Точки расширения ядра» | test_staff_import_file |
| «Подразделение», «Руководитель», «Подчинённые» | подписи полей карточки — текст `[data-field-label="<имя>"]` (9.3); также «Должность», «Состояние», «Почта», «Телефон», «Внутренний телефон», «Место работы», «Дата рождения» | SPEC-002, сценарий 3; дополнения 20, 30 | test_org_heads, test_staff_card |
| «лично», «от подразделения <название>» | группы ролей | SPEC-002, сценарий 9; PLAN-002, «Карточка» | test_org_permissions |
| «администратор выдаётся только лично» | текст `admin_role_forbidden` | SPEC-002, сценарий 9, п. 4 | test_org_permissions |
| «роль назначена узлу» | текст отказа удаления роли (в `role_usage`: «Роль назначена узлу структуры: сначала снимите её.») | SPEC-002, сценарий 9, п. 7 | test_org_permissions |
| «отдел подчиняется только отделу» | текст `kind_rules` для отдела под командой | SPEC-002, сценарий 1, п. 3 | test_org_structure |
| «названия узлов под одним родителем не повторяются» | текст `name_taken` | SPEC-002, сценарий 1, п. 4 | test_org_structure |
| «цикл в подчинении» | текст `cycle` | SPEC-002, сценарий 6, п. 2 | test_org_structure |
| «руководителем и заместителем может быть только участник узла» | текст `not_member` при отметках | SPEC-002, сценарий 3, п. 7 | test_org_membership |
| «в одном узле человек либо руководитель, либо заместитель» | текст `head_and_deputy` | SPEC-002, сценарий 3, п. 10 | test_org_membership |
| «в файле нет 2027 года» (год подставляется: «в файле нет <год> года») | текст `year_missing` | PLAN-002, «Формат файла» (plan.md:509); SPEC-002, сценарий 11, п. 3 даёт смысл, не текст | test_calendar_file |
| «вход закрыт», «уйдёт из всех подразделений», «личные роли будут сняты» | последствия в диалоге увольнения | SPEC-002, сценарий 7 (описание) | test_org_dismissal |
| «Отмена» | кнопка диалога | SPEC-002, сценарий 7, п. 10 | test_org_dismissal |
| «Фото проверяется» | `[data-photo-status="pending"]` | решение Opus по T-2100a (в спеке и плане подписи нет) | test_photo |
| «Фото не прошло проверку» | `[data-photo-status="failed"]` | PLAN-002, plan.md:408 | test_photo |
| «Выбрать дату» | кнопка поля даты | PLAN-002, «Поле выбора даты» | test_date_field |
| «Структура», «Календарь», «Сотрудники» | пункты меню | PLAN-002, «Точки расширения ядра» | test_org_permissions |
| «Роли узла» | подпись действия `unit-roles` | SPEC-002, сценарий 9 | test_org_permissions |
| «Создать», «Добавить сотрудников», «Подчиняется», «Удалить», «Руководители», «Заместители» | подписи действий и поля узла | SPEC-002, сценарии 1–3 | test_org_structure, test_org_membership |
| «Подтвердите удаление» | `[role=alert]` при POST удаления узла без `confirm=1` (узел не удаляется, событий нет) | решение Opus (дополнение 21; в спеке и плане подписи нет) | test_org_structure |
| «Узел не пуст: в нём есть участники или вложенные узлы.» | `[role=alert]` при удалении узла с участниками или вложенными (`not_empty`); тест ищет «не пуст» | решение Opus (дополнение 52; спека, сценарий 6 п. 3: «называет причину») | test_o06_move_delete |
| «Уволить», «Вернуть на работу» | подписи действий | SPEC-002, сценарии 7, 8 | test_org_dismissal |
| «Профиль», «Безопасность» | подписи вкладок | SPEC-002, сценарий 10, п. 9 | test_staff_card |
| «Не загружен производственный календарь на <год> год.», «Загрузить файл» | напоминание о календаре (9.5) | решение Opus по T-2100a | test_calendar, test_org_pages |
| «не заполнено» (пустой `units`), «нет» (пустой `subordinates`) | поля карточки | «не заполнено» — FR-135; «нет» — решение Opus по T-2100a | test_staff_card, test_org_heads |
| «В», «П», «Н», «Р», «С» и подписи легенды | как в 9.5 | решение Opus по T-2100a | test_calendar |
| тексты пустых состояний (FR-109) | `[data-empty-state]` | пишет исполнитель Этапа 3; тест проверяет атрибут, непустой текст и (у `tree`, `unit` для `org.manage`) кнопку действия внутри `[data-empty-state]` (дополнения 5, 30) | test_org_structure |

## 11. Решения Opus по вопросам T-2100a (2026-10-04)

Вопросы исполнителя T-2100a решены Opus (не владельцем) 2026-10-04; решения записаны в
разделах 1–10 как факты. Источник — `crm-work/slice002/stage2/t2100a/decisions.md`.

| № | Вопрос | Решение |
|---|---|---|
| 1 | `purge_quarantine`: что остаётся от `StoredFile` | Файл карантина стирается, строка остаётся (статус `quarantine`, `signature`, `sha256` нужны для разбора случая); если строка всё ещё `photo_pending` владельца — `photo_pending` обнуляется; событий нет; тест: файла нет, строка есть, `photo_pending is None` |
| 2 | `next_working_start`, когда `moment` уже рабочее время | Сам `moment` (FR-149: «когда начнётся ближайшее рабочее время») |
| 3 | Дата-время без пояса | `ValueError` |
| 4 | Отказ службы на POST: статус | 200 с `[role=alert]` (прецедент среза 001, CONTRACT.md:77–78) |
| 5 | Прямой POST на корень и `birth_date` в форме администратора | 200 с `[role=alert]`, ничего не меняется (корень — `root_protected`; `birth_date` в форме администратора — `AccountError`) |
| 6 | `?state=` вне разрешённых смотрящему | Как пустое («В компании») |
| 7 | События перевода при добавлении в отдел | Три вида событий: `membership.removed` на каждое снятое членство, `membership.added`, одно `membership.transferred` — только если хоть одно членство снято (подробно — 4.2 и 6) |
| 8 | `mode` для команды | Игнорируется |
| 9 | Пустая правка | Ни события, ни роста версии (как `update_profile` среза 001, accounts.py:140–146) |
| 10 | `accounts.pickable`: заблокированные | Отдаёт `invited`, `active`, `blocked` (не `dismissed`) |
| 11 | Тексты напоминания, пустых состояний, легенды | Решение Opus: напоминание — «Не загружен производственный календарь на <год> год.» и ссылка «Загрузить файл» на `/calendar/upload/` (по одному на год из `missing_years`); `units` пусто — «не заполнено» (FR-135); `subordinates` выводится только у руководителя хотя бы одного узла, пусто — «нет»; подписи легенды — как в 9.5; тексты пустых состояний FR-109 пишет исполнитель Этапа 3, тест проверяет `[data-empty-state]` и непустой текст |
| 12 | Предел файла календаря | 1 048 576 байт (как файлы сотрудников; граница — как у фото) |
| 13 | Рабочая суббота с «*» в `totals` | Только `short` (одна запись `SpecialDay`); `is_working_time` считает `short` рабочим днём и в субботу |
| 14 | `year`, `month` вне допустимых | Как по умолчанию (текущие), см. 8.1, 8.4 |
| 15 | `/staff/<свой id>/` | По правилам смотрящего, как любая карточка: вкладки по правам, дата рождения — день и месяц; полная карточка с обеими вкладками и полной датой — только `/me/` (plan.md:380, 392) |
| 16 | Образец `sample.csv` | UTF-8 с BOM, разделитель `;` |
| 17 | Заблокированный и приглашённый в выборе и в `heads_of` | Не ограничивать: `heads_of` показывает руководителей в любом неуволенном состоянии (блокировка структуру не меняет, FR-124) |
| 18 | Почта уволенного | `skipped` с `hint="dismissed"` — решено спекой (spec.md:228–232) и планом (plan.md:459–461) |

Решения по проверке контракта (находки партий A, B, C; решил Opus):

1. A1: тест среза 001 `test_env_example_has_only_placeholders` принимает закомментированные
   имена `# ИМЯ=значение` (правка T-2119, п. 10 в отчёт TASKS-002).
2. A5: версия календаря — целое ≥ 0, отсутствующий ключ читается как 0, первое изменение даёт 1.
3. A8: элемент меню, который отдаёт `menu_for`, — `url`, `title`, `icon`, `order` и, только у пункта с функцией `badge`, ещё `badge` (у описания из точки `menu_items` есть ещё `permissions`, дополнение 33, и необязательные `visible`, `badge`); значки `icons/structure.html`,
   `icons/calendar.html`; порядок 5, 10, 20, 30, 40, 50, 60, 65, 70.
4. A9: фото — до 5 242 880 байт; файлы сотрудников и календаря — до 1 048 576 байт.
5. A14: после выполнения в `rows` остаются `number`, `email`, `result`, `reason` (без `code`).
6. A15: `role_usage` вызывается после проверки среза 001 «роль назначена сотрудникам».
7. A17: порядок отказов `dismiss`: себя, уже уволенного, последнего администратора.
8. B2: `heads` и `subordinates_of` — по `full_name`, затем `id`; `heads` без повторов.
9. B7: `set_marks` — `None` не меняет набор; отказ `head_and_deputy` и по сохранённому
   состоянию; порядок проверок `dismissed_user`, `not_member`, `head_and_deputy`.
10. B8: порядок проверок при нескольких нарушениях (после таблицы кодов в разделе 4).
11. B9: `bad_mode` для любого значения, кроме `TRANSFER`/`CONCURRENT`, включая `None`;
    уволенный в пачке — `dismissed_user` для всей пачки.
12. B11: `actor_text` уволенного — `"<full_name> (уволен) <email>"`.
13. B13: `unit.marks_changed` пишет только `set_marks`.
14. B17: пустая часть пути — `path_invalid`, длиннее 150 знаков — `too_long`; `bad_weekday`.
15. C2: подпись «Фото проверяется» — решение Opus.
16. C3: буквы и подписи календаря (`day_off` — «Н»), «Все подразделения», годы выбора,
    границы: `/calendar/?year=` — 2000…2100, `month` у `/ui/date-picker/` — 1900…2100 (дополнение 24); не более 20 подсказок кандидатов.
17. C5: формы и диалоги (9.8), контейнер `#dialog-root` вместо `#dialog`.
18. C6: маршрут `/structure/<id>/marks/` — `part` и `users`.
19. C9: клавиши и разметка поля даты (9.6).
20. C11: `transfer_member -> bool`; код `already_member` убран.
21. T-2100b (подтверждено Opus): `support_org.SLICE_002_STAFF_ROUTES` — кортеж троек
    `(метод, шаблон пути, права)`, совместимый с `protected_table` из `test_permissions.py`;
    права — кортеж кодов, достаточно любого; отметки `support_org.LOGIN_ONLY` («вход») и
    `support_org.SELF` («сам»); путь строит `route_path`, сверку с `support.all_routes()` —
    `route_regex`. Маршруты `/me/…` — отдельно, `support_org.SLICE_002_ME_ROUTES`.
    `make_member(..., created_by=None)` — по умолчанию `created_by` сам участник.

## Дополнения Opus по вопросам исполнителей Этапа 2 (2026-10-04)

Уточнения по ответам исполнителей и проверке тестов. Решения Opus; тесты и код берут их
наравне с разделами 1–10.

**Сведение 2026-10-04 (Opus, партии проверки K-a…K-d):** текст разделов 1–11 приведён к
дополнениям; изменённые места помечены «(дополнение N)». Если расхождение всё же найдётся,
действует дополнение, а из двух дополнений — с большим номером. Новое дополнение вносится
вместе с правкой затронутых мест разделов 1–11.

1. **Порядок «по `path`»** — байтовый порядок строк (как `sorted()` в Python). Поле
   `Unit.path` объявляется с `db_collation="C"`, поэтому `order_by("path")` в базе даёт тот
   же порядок; индекс `text_pattern_ops` остаётся (план). Тесты сравнивают с `sorted()`.
   Затрагивает: test_org_membership, test_org_heads, test_org_dismissal.
2. **Подсказки кандидатов** (`/structure/<id>/candidates/`) — первые 20 из
   `accounts.pickable(q)` по `full_name`, затем `id`; подходящих больше — ровно 20.
   Затрагивает: test_org_membership.
3. **Форма отметок** — скрытое поле `input[type=hidden][name=part]` (`heads` или
   `deputies`) внутри `form[data-form="marks-heads"]` и `form[data-form="marks-deputies"]`.
   Затрагивает: test_org_membership.
4. **Части вкладки «Безопасность»** карточки сотрудника — внутри
   `[data-tab-panel="security"]`: `[data-security-part="account"]` (состояние
   `[data-field="state"]`, приглашение, блокировка и разблокировка, сброс второго фактора —
   у `accounts.manage`; сброс — по праву `accounts.reset_2fa`, дополнение 66) и `[data-security-part="logins"]` (устройства и история входов,
   ссылка на `/staff/<id>/logins/` — у `accounts.view_logins`); части без права в ответе нет.
   `[data-field="state"]` лежит только в `[data-security-part="account"]`.
   Затрагивает: test_org_permissions, test_staff_card.
5. **Пустые состояния FR-109:** `[data-empty-state="tree"]` — в дереве только корень;
   `[data-empty-state="unit"]` — у выбранного узла нет ни одного участника (вложенные узлы
   могут быть); `[data-empty-state="search"]` — задан `q`, совпадений нет. Текст пояснения
   непустой; у `tree` и `unit` для `org.manage` — кнопка действия (`unit-new`,
   `members-add`).
   Затрагивает: test_org_structure.
6. **Переименование** узла с изменением только регистра или «ё/е» допустимо: узел не
   конфликтует сам с собой по `name_key`.
   Затрагивает: test_org_structure.
7. **Числа в `before`/`after`** журнала (`unit_id`, `parent_id`, `size`, итоги загрузок и
   календаря) — целые JSON, не строки; `object_id` — строка, как в срезе 001.
   Затрагивает: test_org_structure, test_org_membership, test_photo, test_staff_import_run,
   test_calendar*.
8. **Формулы XLSX** (`data_only=True`, план): ячейка с формулой без сохранённого значения —
   пустая строка; с сохранённым значением — это значение текстом; текст формулы не читается.
   Затрагивает: test_staff_import_file.
9. **Даты и числа из XLSX:** дата или дата-время — `ДД.ММ.ГГГГ` (время отбрасывается); целое число
   — без «.0» и экспоненты (`89001234567`); дробное — `str()` без экспоненты.
   Затрагивает: test_staff_import_file.
10. **Заголовки** сравниваются после удаления всех пробельных знаков (и внутри слова), в нижнем
    регистре, «ё» как «е»: «Место  работы», «местоработы» и «МЕСТО РАБОТЫ» совпадают.
    `not_loaded` — названия лишних колонок как в файле, в порядке файла.
    Затрагивает: test_staff_import_file.
11. **Определение формата и коды:** архив ZIP с `[Content_Types].xml` и `xl/workbook.xml` — XLSX;
    архив ZIP без них — `bad_format`; не ZIP, не строгое UTF-8 или с нулевым байтом — `not_utf8`;
    UTF-8 без обязательных колонок — `missing_columns`. Порядок: размер (`too_big`) → формат → для
    XLSX оглавление (`zip_bomb`) → разбор (`xml_bomb`) → колонки → число строк (`too_many_rows`).
    Затрагивает: test_staff_import_file.
12. **Пометка «(уволен)» в истории входов:** на `/staff/<id>/logins/` заголовок с именем —
    `[data-person-name]`, у уволенного текст `"<full_name> (уволен)"`; в журнале — через
    `audit_search.actor_text` (B11). Затрагивает: test_org_dismissal.
13. **Поле `units` у уволенного** выводится: `data-empty="true"`, текст «не заполнено» (Q11).
    Затрагивает: test_org_dismissal, test_staff_card.
14. **Действия карточки над уволенным** (`/staff/<id>/edit/`, `block/`, `unblock/`, `roles/`,
    `reset-2fa/`, `invite/`, отметки и членство в `org`) — POST даёт 200 с `[role=alert]`, ничего
    не меняется (общее правило § 8 для отказа службы); `unblock` — тоже 200 без изменений (A11:
    служба тихо ничего не делает). Затрагивает: test_org_dismissal.
15. **Пресеты коллеги:** «В компании», «Уволены», «Без подразделения», «Все» доступны всем со
    `staff.view`; `state=all` у коллеги — все записи, включая уволенных; служебные пресеты и
    фильтр роли — только `accounts.manage`. Затрагивает: test_staff_search, test_org_dismissal.
16. **Замок корня в тесте** узнаётся по SQL с `FOR UPDATE`, таблицей `"org_unit"` и условием
    `WHERE "org_unit"."is_root"` (не просто словом `is_root`, которое есть в списке колонок
    любого запроса к узлам). Затрагивает: test_org_structure, test_org_membership.
17. **Удаление узла и ключи прав:** удаляется только пустой узел, участников у него нет —
    сбрасывать нечего; тесты сброс при удалении не проверяют (§ 7 выровнен с § 4.1).
    Затрагивает: test_org_permissions.
18. **Порядок в проверках тестов:** списки, которые контракт упорядочивает «по `path`»,
    тесты сравнивают с `sorted()` по `path` узлов, а не с порядком создания (id узлов могут
    пересечь границу разрядов 9→10). Затрагивает: test_org_membership, test_org_heads,
    test_org_dismissal.
19. **`scan_file` без строки `StoredFile`** (файл удалён новой загрузкой или удалением фото, а
    задание осталось в очереди) — задание завершается без изменений, без событий и без
    исключения. Затрагивает: test_photo.
20. **Подпись поля карточки** — элемент `[data-field-label="<имя>"]` рядом со своим
    `[data-field="<имя>"]`, текст — подпись по-русски («Подразделение», «Руководитель»,
    «Подчинённые», «Внутренний телефон», «Место работы», «Дата рождения» и т. д.).
    Затрагивает: test_org_heads, test_staff_card.
21. **POST удаления узла без `confirm=1`** (`/structure/<id>/delete/`) — 200 с `[role=alert]`
    («Подтвердите удаление»), узел не удаляется, событий нет. Затрагивает: test_org_structure.
22. **Строка списка у коллеги** (смотрящий без `accounts.manage`): атрибута `data-state` нет
    (служебные состояния скрыты, FR-119); у строки уволенного — `data-dismissed="true"`. У
    обладателя `accounts.manage` — `data-state`, как в срезе 001 (`dismissed` тоже).
    Затрагивает: test_staff_search, test_org_dismissal.
23. **Устройство сетки поля даты:** `[data-datefield-grid]` содержит `table`; заголовок —
    `thead th` с текстами «Пн», «Вт», «Ср», «Чт», «Пт», «Сб», «Вс» по порядку; недели —
    `tbody tr[data-week]`, в каждой ровно 7 `td`; дни вне месяца — пустые `td` без кнопки.
    Например, 1 ноября 2026 (воскресенье) — седьмая ячейка первой недели.
    Затрагивает: test_date_field.
24. **Исправление C3 для сетки поля даты** (ошибка Opus: поле даты служит и дате рождения):
    `month` у `/ui/date-picker/` принимается с годом **1900…2100**; вне этого — текущий месяц.
    `select[name=year]` сетки — годы от 1900 до текущего +5 (год сетки всегда в списке).
    Для `/calendar/?year=` граница прежняя: 2000…2100. Затрагивает: test_date_field.
25. **Чтение ответа clamd** — `sock.recv(...)` до завершающего `\0` или закрытия соединения
    (без `makefile`); отправка — `sendall`. Затрагивает: test_clamav_adapter.
26. **Файл календаря:** пустой файл — `bad_format`; файл в строгом UTF-8 без заголовков формата
    (например, 1 048 576 байт «x») — `bad_format`. `calendar_file.apply` пишет в новые
    `SpecialDay` `origin="file"`, `changed_by` — загрузивший (`actor`), `changed_at` — момент
    применения. Предпросмотр (`make_preview`) событий журнала не пишет и номер версии
    календаря не меняет. Затрагивает: test_calendar_file.
27. **Загрузка сотрудников, уточнения:** у строки `created` (и `will_create`) `reason == ""`;
    длина ФИО проверяется по собранному `full_name` («Фамилия Имя Отчество» через один пробел,
    без пустого отчества) — больше 255 знаков — `too_long`; остальные поля — по длинам полей
    `User` (должность и место работы 255, телефон 64, внутренний телефон 32), почта — до 254.
    Членство из загрузки — `membership.added` с `mode=""` и `mark` (`"head"` при «да»).
    Затрагивает: test_staff_import_run.
28. **Календарь, уточнения:** вторую строку `WorkCalendar` не даёт ограничение базы —
    `IntegrityError`; в `calendar.day_changed` для дня без записи `before.kind == ""`; сетка
    каждого месяца на `/calendar/` — как у поля даты (п. 23): `table`, `thead th` «Пн»…«Вс»,
    `tbody tr[data-week]` по 7 `td`, дни вне месяца — пустые `td`; `input[name=day_start]` и
    `day_end` — значение `ЧЧ:ММ`. Затрагивает: test_calendar.
29. **Журнал и загрузки, уточнения:** `staff_import.confirm` выполняет годные строки и при
    наличии строк `error` (они остаются ошибками; SPEC-002, сценарий 5, п. 5). Вложенные
    словари в `before`/`after` (`totals` календаря, итоги загрузки) на странице журнала и в
    CSV показываются по-русски: `audit_labels` модуля `org` даёт названия и вложенных ключей
    (`holidays_on_weekdays` и др.), значение выводится как «название: число; …», латинских
    ключей в тексте нет (FR-150). Затрагивает: test_org_audit, test_staff_import_run.
30. **Уточнения по правкам тестов:** кнопки действий пустых состояний (`[data-action="unit-new"]`,
    `[data-action="members-add"]`, п. 5) лежат внутри своего `[data-empty-state]`; подписи
    полей (п. 20): `position` — «Должность», `state` — «Состояние», `email` — «Почта», `phone`
    — «Телефон». Затрагивает: test_org_structure, test_staff_card.
31. **Решения Opus правщикам, записанные в контракт:** `staff_import` вызывает службы ядра через
    модуль (`from apps.core.services import accounts` → `accounts.create_user(...)`), а не импортом
    имени — тест подменяет `apps.core.services.accounts.create_user`; `calendar.year_loaded` при первой загрузке года — `before == {"year": <год>, "totals": {}}` (исправлено дополнением 34; было `before == {}`); стёртый или несуществующий предпросмотр
    (`/structure/import/<id>/`, `/calendar/upload/<id>/`) — 404. Затрагивает:
    test_staff_import_run, test_calendar_file.
32. **Чтение ответа clamd у `ping`** — как у `instream` (дополнение 25): отправка `sendall`, ответ —
    `sock.recv(...)` до завершающего `\0` или закрытия соединения, без `makefile`.
    Затрагивает: test_clamav_adapter.
33. **`menu_items` и `menu_for`:** описание пункта из точки `menu_items` (и пункты ядра) несёт
    `permissions`, `url`, `title`, `icon`, `order` и необязательные `visible`, `badge`; `permissions.menu_for(user)` отдаёт только
    доступные пункты с ключами `url`, `title`, `icon`, `order` и, только у пункта с функцией `badge`, ещё `badge` (A8 — про результат
    `menu_for`). Затрагивает: test_org_permissions, test_extensions, test_sd_boundaries.
34. **Исправление дополнения 31 (ошибка Opus):** `calendar.year_loaded` при первой загрузке года —
    `before == {"year": <год>, "totals": {}}`, а не `{}`: ключи «было» те же, что при повторной
    загрузке (план: «год, итоги до и после»; § 6). Так проверял test_calendar; проверка
    test_calendar_file исправлена при сведении. Затрагивает: test_calendar, test_calendar_file.
35. **Вкладка «Безопасность»:** на чужой карточке кнопка и панель `security` есть у обладателя
    `accounts.manage` или `accounts.view_logins` (хотя бы одного); без обоих — нет ни кнопки, ни
    панели, ни во фрагменте HTMX. Части панели — по дополнению 4. На `/me/` обе вкладки всегда;
    панель `security` несёт тот же блок, что `/me/security/` (резервные коды
    `[data-backup-remaining]` и прочее среза 001), независимо от прав (§ 11 п. 15).
    Затрагивает: test_staff_card, test_org_permissions.
36. **Карточка уволенного:** `[data-field="state"]` не выводится ни одному смотрящему; состояние
    показывает `[data-dismissed-badge]` рядом с ФИО; остальные поля карточки выводятся как обычно
    (`units` — дополнение 13). Затрагивает: test_org_dismissal, test_staff_card.
37. **`unit.roles_changed` при первом назначении:** `before == {"roles": []}` — ключ `roles` с
    обеих сторон (§ 6). Правило § 6 «пустая сторона — `{}`» — только для сторон, у которых в
    таблице § 6 нет ключей. Затрагивает: test_org_audit.
38. **`extensions.registered` с неизвестной точкой** — `ValueError`, как у `register` (вопрос
    T-2116). Затрагивает: test_extensions.
39. **Функции точек `org`:** во всех девяти точках `org` регистрирует обычные функции модулей
    `apps.org…` (`func.__module__` начинается с `apps.org`), без `lambda` из чужих модулей и
    `functools.partial`. Затрагивает: test_extensions.
40. **Том баз ClamAV** `clamav-db` монтируется в контейнер `clamav` на `/var/lib/clamav`: это
    каталог баз образа `clamav/clamav:1.4.6` (там `main.cvd`, `daily.cvd`, `bytecode.cvd`;
    `DatabaseDirectory` в конфигах образа не переопределён — проверено Opus по образу
    2026-10-04). Затрагивает: test_deploy_files.
41. **nginx `/protected/`:** тип `image/jpeg` задаётся любым способом (`default_type`, `types`,
    `add_header Content-Type`); `nosniff` и `Cache-Control "private, max-age=86400"` — с
    `always` или без (фото отдаётся с 200, на ответ это не влияет). Тест не требует одной
    формы. Затрагивает: test_deploy_files.
42. **Страницы 403 и 404 без подробностей** (FR-123, как в срезе 001: `errors/403.html`,
    `errors/404.html`, отказ CSRF — тот же 403): в теле нет `Traceback`, `DoesNotExist`,
    `matching query`, имён таблиц (`org_unit` и др.), SQL, слова `CSRF` и кодов прав.
    Затрагивает: test_org_pages.
43. **Число запросов страниц среза (NFR-101, NFR-102):** тест сравнивает число запросов на малых
    и больших данных — оно одинаково; абсолютного предела нет (в плане среза 002 его нет; предел
    25 из теста среза 001 сюда не переносится). «До 200 узлов» — вместе с корнем.
    Затрагивает: test_capacity.
44. **`/structure/` отдаёт всё дерево в разметке:** все узлы во вложенных `<ul>`/`<li
    data-unit-id>` с `<details>`, без догрузки по запросу (план: «дерево страницы читается одним
    запросом и собирается в памяти», узлов не больше 200). Затрагивает: test_capacity,
    test_org_structure.
45. **Поля форм `unit-new` и `unit-edit`** (вопрос T-2140): `select[name=kind]` с вариантами
    `department` и `team` — только в `unit-new`; `[name=name]`; `[name=description]` (поле или
    многострочное поле — любое); `select[name=parent]` («Подчиняется») — **все** узлы дерева по
    `path` (значение — id), в том числе команды и, в `unit-edit`, сам узел и его потомки: отказы
    по видам (FR-102, сценарий 1 п. 3) и по циклу (FR-106, сценарий 6 п. 2) даёт сервер — 200 с
    `[role=alert]`, ничего не меняется. У корня в `unit-edit` поля `parent` нет (§ 8.3).
    Затрагивает: helpers_org (T-2140), test_o01_structure, test_o06_move_delete, приёмку
    T-2141…T-2150.
46. **Формы `marks-heads`, `marks-deputies`, `unit-roles`** (вопрос T-2140): в `marks-*` —
    флажок `input[type=checkbox][name=users][value="<id>"]` на каждого участника узла, в
    `unit-roles` — `input[type=checkbox][name=roles][value="<id>"]` на каждую роль портала, в том
    числе «Администратор портала» (отказ по FR-121 даёт сервер — 200 с `[role=alert]`); отмечен
    текущий набор, отправка заменяет набор целиком. Затрагивает: helpers_org, T-2141, T-2145.
47. **Диалог `unit-delete`** (вопрос T-2140): форма `form[data-form="unit-delete"]` несёт
    `input[type=hidden][name=confirm][value="1"]` и `button[type=submit]`; успех — 302 по § 8.3,
    отказ (узел не пуст) — 200 с `[role=alert]` и причиной. Затрагивает: helpers_org,
    test_o06_move_delete, test_org_structure.
48. **Пресеты ядра без расширений** (находка R-4a): пресеты «В компании» (`""`), «Уволены»
    (`dismissed`), «Все» (`all`) и у `accounts.manage` — «Приглашены», «Активные», «Заблокированные»
    принадлежат ядру (plan.md:356–363); `org` через `staff_directory` добавляет только «Без
    подразделения» (`no_unit`), фильтр `select[name=unit]`, колонку «Подразделение», поиск по
    названию узла и кнопку «Загрузить из таблицы» (plan.md:122). Внутри `extensions.empty()` у
    администратора на `/staff/` ровно `a[data-preset]` со значениями `""`, `dismissed`, `all`,
    `invited`, `active`, `blocked`. Затрагивает: test_extensions.
49. **Удаление фото, когда фото нет** (`/me/photo/delete/`, `/staff/<id>/photo/delete/`): 302, как
    обычно, ничего не меняется, событие `photo.deleted` не пишется (§ 6). Затрагивает: test_photo,
    test_org_pages.
50. **Место кнопок раздела «Структура»** (вопрос RE-0): «Создать» `[data-action="unit-new"]` — в
    шапке страницы `/structure/` вне `[data-unit-tree]` и `[data-unit-card]` (ещё одна — внутри
    `[data-empty-state="tree"]`, дополнения 5, 30; приёмка берёт кнопку шапки — первую в порядке
    документа); действия выбранного узла `[data-action="unit-edit"]`, `[data-action="unit-delete"]`
    и `<details data-action="members-add|marks-heads|marks-deputies|unit-roles">` — внутри
    `[data-unit-card]`. Затрагивает: helpers_org, test_o01_structure, test_o06_move_delete, приёмку
    T-2141…T-2150.
51. **Сообщение об успехе:** после каждого успешного POST форм среза (структура, участники,
    отметки, роли узла, увольнение и возврат, календарь, загрузки, фото) страница, на которую ведёт
    302, показывает `[role=status]` с непустым текстом (текст пишет Этап 3; тесты ищут слова
    только из § 10). Приёмка всё равно ждёт сам ответ POST (переход), а не появление сообщения.
    Затрагивает: helpers_org, приёмку T-2140…T-2150.
52. **Текст отказа `not_empty`** при удалении узла: «Узел не пуст: в нём есть участники или
    вложенные узлы.» (решение Opus; спека, сценарий 6 п. 3 — «называет причину»); тест ищет «не
    пуст». Фильтр журнала `object_id` — точное равенство (срез 001, audit_search.py:115), поэтому
    `len(rows) == 1` по `object_id` верно. Затрагивает: test_o06_move_delete, helpers_org.
53. **Разметка узла дерева** (находка VE-0): у узла с вложенными — `<li data-unit-id>` →
    `<details>` (`open` — по § 9.1) → `<summary>` с переключателем `[data-unit-toggle]` (значок,
    `aria-label` «Развернуть»/«Свернуть» или скрытый текст) и ссылкой `a[data-unit-link]`, затем
    `<ul>` вложенных; щелчок по `[data-unit-toggle]` раскрывает или сворачивает узел, щелчок по
    ссылке открывает карточку (HTMX) и `<details>` не переключает. У узла без вложенных `<details>`
    нет: `<li data-unit-id>` со ссылкой. Затрагивает: helpers_org (`select_unit`), test_org_structure
    (совместим: проверяет `<details>` только у узлов с вложенными).
54. **Формы карточки узла** (`members-add`, `marks-heads`, `marks-deputies`, `unit-roles`) и меню «…»
    (`member-transfer`, `member-remove`) — обычный POST без `hx-post`: успех — 302 и страница
    целиком, отказ — 200 с `[role=alert]` (§ 8). Подсказки кандидатов (`hx-get` поля `q`) — HTMX, как
    в § 9.8. Затрагивает: helpers_org (ожидание перехода после отправки), приёмку T-2141…T-2150.
55. **Диалог `rehire`** тоже перечисляет последствия в `[data-consequence]` (§ 9.3 — общая строка
    для `dismiss` и `rehire`): по FR-128 — новое приглашение, прежние пароль, второй фактор,
    резервные коды и устройства недействительны, роль «Сотрудник ИТ», подразделения и остальные
    роли — вручную; тексты пишет Этап 3, тест проверяет не меньше одного `[data-consequence]`.
    Затрагивает: test_o08_rehire, test_org_dismissal.
56. **Сообщение об успехе и напоминание календаря:** напоминание `[data-notice="calendar-year"]`
    размечено `role="status"` (§ 9.5), поэтому сообщение об успехе (доп. 51) тесты читают как
    `[role=status]:not([data-notice])`; на `/` и `/calendar/` у обладателя `calendar.manage`
    напоминаний может быть несколько. Затрагивает: приёмку T-2147, T-2148 и любые проверки
    `[role=status]` на `/` и `/calendar/`.
57. **Имя поля даты** — на самом `input[type=text][data-datefield-input]` (`name="birth_date"` на `/me/`,
    `date_from`/`date_to` в журнале и т. д.; так уже проверяет test_date_field, строки ≈266–330);
    скрытого поля с тем же именем нет. Приёмка заполняет `input[data-datefield-input][name=…]`
    текстом `ДД.ММ.ГГГГ`. Затрагивает: test_o04_find_colleague, test_o10_card_photo, test_o13_date_field.
58. **«Было / стало» в журнале на странице** (находка RE-1a): слова «Было» и «Стало» стоят только в
    шапке таблицы журнала, в строке их нет. Строка события — `tr[data-event-id][data-action]` со
    столбцами по порядку: время, кто, событие, объект, было, стало, адрес (разметка среза 001,
    templates/audit/_results.html); приёмка читает «было» и «стало» как текст 5-й и 6-й ячеек `td`
    строки (помощник `helpers_org.audit_sides`) и проверяет прежнее значение в «было», новое — в
    «стало». Затрагивает: helpers_org, test_o01_structure, test_o03_heads, test_o06_move_delete,
    test_o09_unit_roles, приёмку T-2147 (o12 «было/стало»).
59. **Поведение сетки поля даты** (вопросы T-2148): смена `select[name=month]` или
    `select[name=year]` сразу запрашивает сетку выбранного месяца (`hx-get` по событию `change`,
    `month=ГГГГ-ММ` из обоих списков — или парой `month=М&year=ГГГГ`, дополнение 68) и заменяет её — новый `[data-datefield-grid][data-month]`;
    при открытии сетки фокус — на кнопке выбранного дня (`aria-pressed="true"`), иначе на
    сегодняшнем дне, если он в показанном месяце, иначе на 1-м числе; щелчок по дню — как Enter:
    пишет дату в поле в виде `ДД.ММ.ГГГГ` и закрывает сетку (контейнер снова `hidden`).
    Затрагивает: test_o13_date_field, test_date_field (совместим: щелчок и фокус сервер не проверяет).
60. **Пустые ячейки сетки** (страница календаря и поле даты): `td` дня вне месяца пустой — без
    кнопки и без атрибута `data-date`; `data-date` есть только у дней месяца: на странице календаря —
    у `td[data-date]` дня (§ 9.5), в сетке поля даты — у `button[data-date]` (§ 9.6; уточнено после
    сверки VE-2a). Поэтому число `[data-date]` на странице календаря года — число дней года (365 или
    366). Затрагивает:
    test_o13_date_field, test_calendar, test_date_field.
61. **`birth_date` в форме администратора:** поле `birth_date` в POST `/staff/<id>/edit/` в любом
    виде, в том числе пустой строкой, — 200 с `[role=alert]` (`AccountError`), ничего не меняется
    (дата рождения — только сам сотрудник на `/me/`, FR-134). Затрагивает: test_o10_card_photo,
    test_staff_card.
62. **Рабочая неделя в журнале** (находка VE-2b): событие хранит `work_weekdays` списком целых 0…6
    (§ 6, test_org_audit), а страница журнала и CSV показывают его по-русски: `audit_labels` модуля
    `org` даёт `values["work_weekdays"]` — `0`→«Пн», `1`→«Вт», `2`→«Ср», `3`→«Чт», `4`→«Пт», `5`→«Сб»,
    `6`→«Вс»; ядро (`audit_labels.text`) для списка, у поля которого есть `values`, переводит каждый
    элемент (ключ `values` — `str(элемента)`: в событии целые, ключи — строки) и соединяет через «, » (списки и сейчас выводятся через «, » без скобок, срез 001,
    audit_labels.py:61–62). Пример «стало»: «Рабочие дни: Пн, Вт, Ср, Чт, Пт, Сб». Сброс стенда в
    начале круга очищает журнал (`e2e_reset_stand` чистит таблицы `core_*` с обнулением счётчиков id),
    поэтому внутри круга события одного кода и объекта умещаются на первой странице журнала.
    Затрагивает: test_o12_week, test_org_audit (совместим: проверяет хранимые целые и наличие
    `values` для своих полей), Этап 3 (audit_labels ядра и модуля org).
63. **Месяц при открытии сетки** (находка VE-2a): кнопка «Выбрать дату» всегда несёт
    `hx-get="/ui/date-picker/?month=<текущий месяц по Москве>"` — значение поля (ни при выводе
    страницы, ни после выбора) в адрес не попадает: так уже требует test_date_field
    (test_field_value_not_in_picker_request: в адресе нет года даты рождения), это защищает дату
    рождения от журналов сервера. Повторное открытие после выбора снова показывает текущий месяц;
    выбранный день отмечен `aria-pressed="true"`, только если он в показанном месяце; к нужному
    месяцу пользователь переходит списками месяца и года или кнопками. Фокус при открытии — на
    выбранном дне, если он в показанном месяце, иначе на сегодняшнем (уточняет дополнение 59).
    «Сегодня» и «текущий год» в приёмке считать по Москве: `datetime.now(ZoneInfo("Europe/Moscow"))`.
    Затрагивает: test_o13_date_field, test_date_field (совместим).
64. **Подпись ссылки уведомления на главной** (находка Opus при проверке T-2201): текст
    интерфейса `org` не зашивается в шаблон ядра. У уведомления точки `home_notices` есть
    необязательный ключ `link` — подпись ссылки на `url`; ядро выводит `link`, а без него —
    «Перейти». `org` для напоминания календаря отдаёт `link="Загрузить файл"` (§ 9.5, строка
    `[data-notice="calendar-year"]`). Тесты читают уведомление по ключам, а не сравнением
    словаря целиком, поэтому новый ключ их не ломает. Затрагивает: § 5 (`home_notices`),
    T-2201 (главная), T-2219 (напоминание), test_calendar::test_reminder_* и test_org_pages
    (совместимы).
65. **Фото, которое не перекодировалось после «чисто»** (вопрос проверки R-2216-5): clamd ответил
    «чисто», но Pillow не смог перекодировать файл в JPEG 512 и 96 px (повреждённый или подменённый файл,
    распаковочная бомба). Такой файл уходит в карантин так же, как найденный антивирусом: статус
    `quarantine`, `signature == "image-decode-error"` (не имя сигнатуры clamd), `photo` не меняется,
    `photo_pending` указывает на карантинный файл, событие `photo.checked` с `result="quarantine"` и этой
    сигнатурой. Карточка показывает «фото не прошло проверку», как при находке антивируса. Решение Opus;
    плана не меняет (план: «найдено — карантин»). Затрагивает: § 3 (`core.tasks.scan_file`), T-2216,
    T-2235 (страницы), test_photo (совместим).
66. **Сброс второго фактора в карточке** (вопрос T-2234; ошибка Opus в дополнении 4): форма
    `…/reset-2fa/` лежит в `[data-security-part="account"]`, но показывается по праву своего маршрута
    `accounts.reset_2fa` (срез 001: apps/core/views/staff_actions.py, `require_permission("accounts.reset_2fa")`;
    tests/test_totp.py — у владельца одного `accounts.manage` кнопки сброса нет), а не по
    `accounts.manage`. Правлены § 9.3 и дополнение 4. Затрагивает: test_org_permissions
    (test_security_tab_parts_by_accounts_manage_and_view_logins — ожидания исправлены, добавлена строка с
    `accounts.reset_2fa`), test_staff_card (совместим).
67. **Своя карточка `/staff/<свой id>/`** (вопрос T-2234): права — как у любой карточки по таблице плана
    («Контракты»): `staff.view` или `accounts.manage`, иначе 403; исключения «сам» у этого маршрута нет (оно есть
    только у выдачи фото и у `/me/`). У сотрудника ИТ право `staff.view` даёт начальная роль «Сотрудник ИТ».
    Правлен § 8.1. Затрагивает: test_staff_card (test_colleagues_see_day_and_month_year_only_self — сотруднику
    дано `staff.view`), test_org_permissions (совместим).
68. **Запрос сетки из списков месяца и года** (находка R-2238-2): без скрипта составить `month=ГГГГ-ММ` из двух
    `select` нельзя, поэтому списки шлют пару `month=<1…12>&year=<ГГГГ>` (`hx-include` обоих списков), а
    `/ui/date-picker/` принимает и `month=ГГГГ-ММ`, и эту пару; неверная пара — как неверный `month` (текущий
    месяц по Москве, доп. 24). Кнопки «предыдущий/следующий месяц» и кнопка открытия шлют `month=ГГГГ-ММ`; на
    1900-01 и 2100-12 кнопка выхода за границу недоступна (R-2238-1). Правлено дополнение 59. Затрагивает:
    test_date_field, test_o13_date_field (совместимы: смотрят `[data-month]` новой сетки).
69. **Журнал: создание записи и снятие фото в карантине** (T-2305, находки Н-I2-1 и Н-I2-2; решение Opus 2026-10-05).
    (а) `user.created` из `accounts.create_user` пишет в «стало» и `internal_phone`, `workplace` (снимок
    `_card_snapshot`): загрузка сотрудников задаёт эти поля, а событие создания их не называло. Событие первого
    администратора (`create_first_admin`) не меняется. (б) `files.delete_photo`, снимающий ссылку на файл в карантине
    (`photo_pending` в состоянии «карантин»), пишет `photo.deleted` и тогда, когда удалять нечего: `before` —
    `{"files": [<удалённые>]}`, как в § 6, и список может быть пустым (снята только ссылка на файл в карантине; сам
    файл остаётся до ночной очистки). Нового ключа нет: набор ключей `photo.deleted` закреплён таблицей
    test_org_audit (`KEYS`, `{"files"}`). Без фото — по-прежнему тихо, без события. Затрагивает: новые тесты
    test_photo.py::test_photo_delete_quarantine_only_written_to_audit и
    test_staff_import_run.py::test_created_event_includes_internal_phone_and_workplace; прежние тесты не меняются
    (test_photo_delete_by_self_or_accounts_manage_quarantine_kept и
    test_org_audit::test_every_slice_action_writes_event_with_russian_label совместимы: смешанный случай даёт тот же
    `files`, ключи — `{"files"}`).
70. **Новые тесты по проверке T-2306 и проходу T-2301** (решение Opus 2026-10-05; существующие тесты не меняются).
    (а) FR-101: прямой запрос создания узла с видом не из `department`/`team` (например `kind=box`) отклоняется
    формой страницы сообщением «Выберите вид узла: отдел или команда.» (views/structure_forms.py проверяет вид до
    службы), узел не создан, события нет; вызов службы `structure.create_unit(kind="box", …)` — `OrgError` с текстом
    «Неизвестный вид узла…» — test_org_structure.py::test_unknown_kind_refused_even_direct.
    (б) FR-136: страница `/structure/import/` у владельца обоих прав содержит ссылки на образцы
    `a[data-sample="csv"][href="/structure/import/sample.csv"]` и `a[data-sample="xlsx"][href="/structure/import/sample.xlsx"]`,
    и по каждой ссылке скачивается образец (200, вложение) — test_staff_import_file.py::test_import_page_links_both_samples.
    (в) Журнал (ядро, находка Ф1 прохода T-2301): при фильтре `?action=<известный код>` в списке «Что сделано»
    выбран вариант с русским названием, и варианта, который показывает сам код, нет; для кода, которого нет среди
    `known_actions()`, по-прежнему добавляется скрытый выбранный вариант с кодом — test_audit.py::test_action_filter_shows_title_for_known_code.
    Тесты (а) и (б) подтверждают уже реализованное поведение — красного прогона у них нет; (в) до правки красный.
71. **Правки по проходу T-2301** (решение Opus 2026-10-05; существующие тесты не меняются, к каждой правке — новый тест).
    (а) Ф4: после добавления в отдел в режиме «перевести» сообщение начинается с «Переведено: » (ФИО через запятую);
    в режиме совместительства и при добавлении в команду — по-прежнему «Добавлено: ».
    (б) Ф5: `flash` ядра получает третий вид — сведения (`level` «info», `role` «status», как у успеха); «Уже участник
    узла…» и «… уже участник узла «…»: ничего не изменено» показываются этим видом (тесты читают `[role=status]` и
    подстроку «уже участник» — совместимо).
    (в) Ф8: текст отказа `missing_columns` загрузки сотрудников дополняется фразой «Загрузите таблицу CSV (UTF-8) или
    XLSX по образцу.»; формат по-прежнему определяется по содержимому (доп. 11).
    (г) Ф9: в строке предпросмотра с почтой уволенного подсказка «уволен: верните его из карточки» встречается ровно один
    раз (test_staff_import_run.py:241 ищет эту подстроку — совместимо); причина службы для уволенного не повторяет
    подсказку.
    (д) Ф10: GET диалога `/structure/people/<id>/rehire/` для неуволенного и `/structure/people/<id>/dismiss/` для уже
    уволенного — 200 с причиной в `[role=alert]` внутри диалога («Сотрудник не уволен…» / «Сотрудник уже уволен…») и без
    кнопки действия (`button[type=submit]` формы действия нет); POST — как прежде (отказ, состояние не меняется).
    (е) NFR-104: новый тест приёмки test_o_cross_cutting.py::test_o_narrow_360_remaining_slice_pages — на ширине 360 px
    без горизонтальной прокрутки — каждый маршрут `apps/org/urls.py`, который отвечает на GET страницей или фрагментом
    (кроме образцов `sample.*` и уже обойдённых `/structure/`, `/structure/new/`, `/structure/<id>/edit/`,
    `/structure/import/`, `/calendar/`, `/calendar/upload/`): удаление узла, формы участников, отметок и ролей узла,
    перевод участника, подсказки кандидатов, диалоги увольнения и возврата, `/calendar/settings/`,
    `/calendar/days/<день>/`, предпросмотр загрузки календаря, итог загрузки сотрудников; и страница ядра, которую
    изменил срез: `/staff/new/` (`/staff/<id>/edit/` — только POST, `staff_actions.py`: форма правки показана в карточке,
    уже обойдённой). Маршрут только для POST пропускается — список пропусков в тесте с причиной; фрагмент HTMX
    открывается без заголовка `HX-Request` (полная страница, FR-108).
