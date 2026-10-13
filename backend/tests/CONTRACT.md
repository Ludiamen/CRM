# Контракт имён тестов Этапа 2 (T-100…T-110)

Тесты написаны до кода и задают имена, которых нет в PLAN-001. Реализация (Этап 3)
берёт их отсюда; исполнитель T-111…T-119 дополняет таблицы своими именами, указывая
тест. Имена из плана (модели и поля «Модели данных», маршруты «Контрактов»,
`core.services.audit.record`, `integrations.mail.services.send`, `create_first_admin`,
`rotate_field_keys`, ключи Valkey) здесь не повторяются, кроме случаев, когда тест
уточняет их форму. Помощники тестов — `tests/support.py`.

## Среда запуска

| Что | Требование | Тесты |
|---|---|---|
| Корень репозитория в контейнере тестов | сервис `test` монтирует только `../backend`; тестам нужен ещё `../deploy` (в `/app/deploy`), а T-118 и `docs/` — по надобности. Без этого `repo_file()` падает с понятным сообщением. Для проверки вручную: `docker compose ... run --rm -v "$PWD/deploy:/app/deploy:ro" test` | test_stack (layout, env_example, forbidden_words) |
| Настройки pytest | после T-200 `pytest.ini` переключается на `config.settings`; тесты проверяют это через `settings.INSTALLED_APPS` | test_stack::test_admin_not_installed |
| Файлы | `config/cron.py`, `apps/core/management/commands/{create_first_admin,rotate_field_keys}.py`, `deploy/{Dockerfile,nginx.conf}`, `templates/` с подключением `vendor/bootstrap-*`, `vendor/htmx-*`, `vendor/alpine-*` через `{% static %}`; файлы среза 003 (`apps/servicedesk/`, `deploy/dovecot/`, `deploy/backup/`) описывает `CONTRACT-003.md` | test_stack::test_project_layout_matches_plan, test_vendor_assets_present_with_licenses |
| Куки | `CSRF_COOKIE_HTTPONLY = True` (NFR-007 требует HttpOnly для куки; в settings.py сейчас нет) | test_config::test_settings_cookie_flags |

## Модели и поля сверх плана

Метки приложений: `core.*`, а письма — `mail.MailMessage`, `mail.MailAttempt`
(`apps.integrations.mail` получает метку `mail`).

| Имя | Что | Тесты |
|---|---|---|
| `User.blocked_reason` | текст причины блокировки (сценарий 15.5) | test_accounts |
| у `User` нет `is_superuser`, `is_staff`, `groups`, `user_permissions` | права только через `roles` | test_permissions::test_permissions_only_through_roles… |
| `OneTimeLink.code_encrypted` | строка Fernet-токена (`str`); при использовании, гашении и истечении очищается (пустая строка) | support.link_code, test_links |
| `EncryptedTOTPDevice.key_encrypted` | строка Fernet-токена (`str`, TextField), открытый ключ — сырые байты (20 байт) | support.make_totp_device, device_key |
| `EncryptedTOTPDevice` (`confirmed=False`) | создаётся при открытии страницы подключения; подтверждается верным кодом | support.enroll_totp |
| `BackupCode.device` | внешний ключ на `BackupCodeDevice` | test_totp |
| `BackupCode.code_hash` | hex от `HMAC-SHA256(BACKUP_CODE_PEPPER.encode(), код.encode())`; код хешируется ровно в том виде, в каком показан | test_totp::test_backup_codes_ten_hashed… |
| `KnownDevice.browser`, `LoginAttempt.browser/platform` | строки из ua-parser: содержат `Firefox` и `Linux` для `FIREFOX_UA` из support | test_login |
| `LoginAttempt.device` | пусто у неудачной попытки с незнакомого устройства, заполнено при успехе | test_login |
| `SecuritySettings` | одна строка со значениями по умолчанию создаётся миграцией; поля формы `/settings/security/` называются как поля модели; значения читаются из базы при каждом запросе (без кэша) | support.set_security, post_security_settings |
| `LoginAttempt.result` | `success`, `bad_password`, `bad_code`, `locked`, `ip_locked`, `backup_code` (поле `choices`) | test_login |
| шаг пароля без ошибки | записи в `LoginAttempt` не создаёт; запись — по итогу шага кода | test_login::test_every_attempt_recorded… |

## Службы и команды

| Имя | Что | Тесты |
|---|---|---|
| `apps.core.services.audit.record(action, *, actor=None, object_type="", object_id="", before=None, after=None, ip=None)` | запись события; `object_id` — строка | test_db_roles, test_audit |
| `apps.core.services.accounts` | модуль учётных записей; в нём нет функций `delete_*`, `remove_*`, `destroy_*` | test_accounts::test_no_delete_user_route_or_service |
| `apps.core.services.second_factor.issue_backup_codes(user) -> list[str]` | выпускает новый набор из 10 открытых кодов, гасит прежний, создаёт и подтверждает `BackupCodeDevice` при его отсутствии | test_totp |
| `apps.core.services.lockout.Limits(account_lock_limit=5, account_lock_minutes=15, ip_lock_limit=20, ip_lock_min_accounts=3, ip_lock_window_minutes=15, ip_lock_minutes=15)` | параметры блокировки (dataclass) | test_lockout::test_parallel_failures… |
| `lockout.register_failure(*, account_key: str, ip: str, limits: Limits) -> Outcome` | атомарно регистрирует неудачу в Valkey; **к базе не обращается** (запись журнала и письмо делает вызывающий по исходу). `Outcome.counted` — неудача засчитана (False, если запись уже заблокирована), `.account_locked_now`, `.ip_locked_now` — True ровно у одного вызова, объявившего блокировку | test_lockout::test_parallel_failures_counted_atomically |
| `account_key` | для существующей записи — `str(user.pk)`, для несуществующей — хеш логина; ключи `fail:acct:<account_key>`, `lock:acct:<account_key>` | test_lockout |
| при блокировке записи | `fail:acct:<id>` удаляется (серия начинается заново), `lock:acct:<id>` живёт `account_lock_minutes` | test_lockout::test_lock_expires… |
| `fail:ip:<ip>` | целое число (INCR), срок — `ip_lock_window_minutes` от первой неудачи окна; `accts:ip:<ip>` — множество хешей логинов (SCARD), в Valkey не лежит ни адрес почты, ни её локальная часть | test_lockout |
| `perms:<id>` | ключ кэша прав в Valkey (проверяется по окончанию имени, приставка Django-кэша допустима) | test_permissions |
| `integrations.mail.services.send(template, to, context)` | создаёт `MailMessage(status="queued", related_user=…)` и по `on_commit` ставит задание в очередь `mail` с единственным позиционным аргументом — номером письма | test_links |
| шаблоны писем (`MailMessage.template`) | `invitation`, `password_reset`, `account_locked`, `new_device`, `second_factor_reset`, `password_changed` | test_links, test_totp, test_passwords, test_lockout |
| адрес клиента | если `REMOTE_ADDR` входит в `settings.TRUSTED_PROXIES` (читается при запросе, не при импорте) — последний адрес из `X-Forwarded-For`, не входящий в список доверенных; иначе — `REMOTE_ADDR` | test_lockout::test_real_ip_taken_from_forwarded_header… |

## Коды событий журнала (`AuditEvent.action`)

`login.success`, `login.failed`, `logout`, `account.locked`, `account.unlocked`,
`ip.locked`, `ip.unlocked` (`object_type="ip"`, `object_id` — адрес),
`password.reset_requested`, `user.created`, `user.updated`, `user.blocked`,
`user.unblocked`, `invitation.sent`, `link.revealed` (показ ссылки администратору;
`object_id` — номер ссылки, кода в `before/after` нет), `user.activated`,
`totp.enrolled`, `totp.reset`, `backup_code.used`, `backup_codes.issued`,
`password.changed`, `sessions.closed` (после восстановления пароля),
`sessions.logout_everywhere`, `role.created`, `role.updated`, `role.deleted`,
`role.assigned`, `security_settings.updated`, `portal_settings.updated`,
`mail.status_changed`. Для действий над записью `object_id` — `str(user.pk)`,
`actor` — выполнивший (для команды установки и блокировок — пусто).
`before`/`after` у `user.updated` — словари с ключами полей; у
`security_settings.updated` — со всеми полями политики.

## Маршруты и поля форм

| Путь | Метод и поля | Что ожидают тесты |
|---|---|---|
| `/` | GET | стартовая страница для вошедшего (в плане маршрута нет) |
| `/login/` | POST `email`, `password`; `?next=` | успех шага — 302 на `/login/code/`; отказ — 200 с общим сообщением; `next` с чужим хостом игнорируется |
| `/login/code/` | POST `code` (TOTP) или `backup_code` | успех — 302 на `next` или `/`; отказ — 200 |
| `/logout/` | POST | 302 |
| `/password/forgot/` | POST `email` | ответ одинаков для любого адреса |
| `/password/reset/exchange/`, `/activate/exchange/` | POST `code` (только тело) | успех — 302 на `/password/reset/` и `/activate/profile/`; GET — 405; отказ — не 302, одинаковый ответ |
| `/password/reset/` | POST `password1`, `password2` | успех — 302 на `/login/` |
| `/activate/<profile|password|totp|codes>/` | `profile`: `phone`, `contacts`; `password`: `password1`, `password2`; `totp`: GET создаёт устройство, POST `code`; `codes`: GET показывает 10 кодов, POST `confirm=1` завершает | порядок шагов принудительный (переход назад на пропущенный шаг), после последнего — 302 на `/` |
| `/me/` | GET, POST `phone`, `contacts` (по строке на контакт) | меняются только эти поля |
| `/me/security/` | GET | блок «Безопасность»; остаток резервных кодов в атрибуте `data-backup-remaining="N"` |
| `/me/security/password/` | GET, POST `current_password`, `password1`, `password2` | смена; страница принудительной смены при истёкшем сроке пароля |
| `/me/security/logout-everywhere/` | POST | закрывает остальные сессии |
| `/me/security/totp/` | GET, POST `code` | подключение фактора; сюда ведёт ограниченная сессия |
| `/me/security/backup-codes/` | GET, POST `confirm=1` | показ и подтверждение сохранения кодов (коды показываются один раз) |
| `/me/security/backup-codes/new/` | POST | новый набор: ответ 200 с 10 кодами |
| `/me/security/devices/` | GET | (упоминается в test_activation как закрытая для ограниченной сессии) |
| `/staff/` | GET `state`, `role` (id), `q`, `sort` (`full_name`, `-full_name`, `email`, …), `page` (25 строк) | список; HTMX — фрагмент |
| `/staff/new/` | POST `email`, `full_name`, `position`, `phone`, `roles` (список id) | 302 на `/staff/<id>/` |
| `/staff/<id>/` | GET | карточка; HTMX — фрагмент без `<html>`; для приглашённого — `PORTAL_URL/activate/#<код>` и состояние письма; форма сброса `…/reset-2fa/` есть только при праве и не для себя |
| `/staff/<id>/edit/` | POST `full_name`, `position`, `phone`, `email`, `contacts` | |
| `/staff/<id>/roles/` | POST `roles` (список id) | право `accounts.manage` |
| `/staff/<id>/block/` | POST `reason` | |
| `/staff/<id>/unblock/`, `/invite/`, `/unlock/`, `/reset-2fa/` | POST | `unlock` — снять блокировку входа записи |
| `/staff/<id>/logins/` | GET | устройства и входы, право `accounts.view_logins` |
| `/staff/locks/` | GET; POST `kind` (`account`/`ip`), `target` (id записи / адрес) | |
| `/roles/new/`, `/roles/<id>/`, `/roles/<id>/delete/` | POST `name`, `permissions` (список кодов) | |
| `/settings/security/` | POST — все поля `SecuritySettings`; пустое значение у `password_max_age_days` = «нет» | 302 при успехе |
| Меню | ссылки `href="/staff/"`, `/roles/`, `/audit/`, `/settings/portal/`, `/settings/security/` | видны только по праву (`accounts.manage`, `roles.manage`, `audit.view`, `settings.portal`, `settings.security`) |
| Резервные коды на странице | `<code class="backup-code">КОД</code>` | support.backup_code_values |
| Сообщения политики | о длине — слово «символ» и число; о повторе — «последн» и число; о бездействии на странице входа — «бездейств» | test_passwords, test_activation |
| Ограниченная сессия | все страницы, кроме `/me/security/totp/`, `/me/security/backup-codes/`, `/logout/`, отвечают 302 на `/me/security/totp/` | test_activation |

## Что не удалось проверить напрямую

- Настоящая гонка двух потоков на резервном коде: у `crm_app` нет `TRUNCATE`,
  данные теста не фиксируются и потоки их не видят. Проверены `select_for_update`
  в запросе и повторная проверка устаревшим объектом устройства.
- Истечение срока ключа Valkey: проверяется TTL ключа, а истечение имитируется
  удалением (Valkey и RQ живут по настоящему времени).

## Решения Opus по вопросам этапа 2а (2026-10-01)

Решения плана, которые план не задал; войдут в следующую версию PLAN-001
(записаны в docs/reviews/TASKS-001.md, «Ход выполнения»).

**Границы настроек безопасности (сценарий 17.2 спеки).** Администратор
может только ужесточать относительно утверждённых значений (TGT-NFR,
ADR-0006, решения владельца), но не ослаблять. Значение вне границ —
отказ формы с объяснением, какая граница нарушена.

| Поле `SecuritySettings` | По умолчанию | Допустимо |
|---|---|---|
| `password_min_length` | 12 | 12…128 |
| `password_history` | 5 | 5…24 |
| `password_max_age_days` | выключено | выключено или 30…365 |
| `idle_timeout_minutes` | 60 | 5…60 |
| `account_lock_limit` | 5 | 3…5 |
| `account_lock_minutes` | 15 | 15…1440 |
| `ip_lock_limit` | 20 | 5…100 |
| `ip_lock_min_accounts` | 3 | 2…20 |
| `ip_lock_window_minutes` | 15 | 5…60 |
| `ip_lock_minutes` | 15 | 15…1440 |
| `login_history_days` | 365 | 30…365 |

**Порог адреса при значениях по умолчанию.** Отказы по уже заблокированной
записи в счёт адреса не идут (план), поэтому при `account_lock_limit=5` и
`ip_lock_limit=20` адрес блокируется только при переборе четырёх и более
записей; `ip_lock_min_accounts=3` при этих значениях не ограничивает. Это
допустимо: каждая запись защищена своей блокировкой. Тесты проверяют правило
адреса отдельно, поднимая `account_lock_limit`.

**Адрес клиента.** Определяет Django (промежуточное ПО ядра), потому что
блокировка и история входов работают в Django: если `REMOTE_ADDR` входит в
`TRUSTED_PROXIES`, адрес клиента — последний недоверенный адрес из
`X-Forwarded-For`, иначе — `REMOTE_ADDR`. Заголовок от недоверенного
источника игнорируется.

**Резервный код при вводе.** Дефисы и пробелы отбрасываются, регистр не
важен: код сравнивается после нормализации.

**Разблокировка неактивированной записи.** Запись возвращается в то
состояние, из которого её заблокировали: `invited` остаётся `invited`
(ссылка активации при блокировке погашена — нужна новая), `active` —
`active`.

## Дополнения исполнителя T-111…T-119 (новые имена)

Имён плана и прежнего контракта не меняли; ниже — только то, чего в них не было.

### Маршруты, параметры, разметка

| Имя | Что | Тест |
|---|---|---|
| `/me/security/devices/<id>/close/`, `/me/security/devices/<id>/forget/` | POST: закрыть сессии устройства (следующий вход с него — снова новое устройство) и «забыть» устройство; чужое устройство — 403/404 без изменений | test_devices |
| `/me/security/history/` | GET: история входов своя, по убыванию времени, с неудачами; время по Москве (`ЧЧ:ММ`, дата `ДД.ММ.ГГГГ` или «2 октября 2026») | test_devices, test_shell, test_security_headers |
| кука устройства | имя не фиксируется: единственная кука кроме сессии и CSRF; `HttpOnly`, `Secure`, `SameSite=Lax`, `max-age` ≥ 30 дней; `KnownDevice.device_key_hash` — 64 hex, значение куки в базе не лежит | test_devices, test_security_headers |
| параметры `/audit/` и `/audit/export.csv` | `date_from`, `date_to` (ГГГГ-ММ-ДД, по Москве), `user` (id), `action`, `object_type`, `object_id`, `preset` (`today`, `access`, `roles`, `settings`), `sort` (`at`, `-at`, `action`, `-action`; по умолчанию `-at`), `page` (номер страницы с 1, по 50 строк; номер за концом выборки или неверный — первая страница; только `/audit/`), `count` (`1` — вывести «Всего: N»; без него число событий не считается; только `/audit/`); строка таблицы — `data-event-id="<id>"`; выгрузка — `text/csv`, `Content-Disposition: attachment`, ячейки на `=+-@` с апострофом; колонки файла: Номер, Время (Москва), Кто, Событие, Код события, Вид объекта, Номер объекта, Было, Стало, Адрес — как на экране по-русски, «Было/Стало» — только изменившиеся поля парами «поле: значение» через «; » | test_audit |
| `/settings/portal/` | POST `name`, файл `logo`, `reset=1` («Вернуть по умолчанию»); отказ — 200 с текстом о логотипе (граница 512 px / 1 МБ называется), успех — 302; `PortalSettings.logo.url` начинается с `/media/`, отдаётся с `nosniff` и типом `image/png` или `image/jpeg`, выводится только `<img>` | test_portal_settings |
| событие `portal_settings.updated` | `before`/`after` с ключами `name` и `logo`; у логотипа значение содержит «заменён» | test_portal_settings |
| оболочка | левое меню `<nav id="main-menu">`, пункт — `<span class="menu-icon">` и `<span class="menu-label">`; кнопка режима `data-menu-toggle`; ключ `localStorage` — `menu-icons-only` (скрипт — внешний файл в `static/`, не vendor); верхняя панель `<header id="top-bar">` (название, `<img>` логотипа, ссылки `/me/`, `/me/security/`, форма POST `/logout/`); inline-скриптов, `on*=` и `style=` нет | test_shell |
| `/health/` | GET без входа: 200, тело короче 120 байт, без версий и названий служб; POST — 405 | test_shell |
| `<meta name="htmx-config">` | JSON с `allowEval: false`, `includeIndicatorStyles: false` | test_security_headers |
| заголовки | CSP: `script-src`/`default-src` без `'unsafe-inline'`, `'unsafe-eval'`, `*`, `data:`, внешних адресов; `style-src` без `'unsafe-inline'`; `object-src 'none'`; HSTS ≥ 31536000 (для запроса с `X-Forwarded-Proto: https`); `Referrer-Policy: same-origin` на всех страницах (см. «Дополнения… проход 2»); `Cache-Control: no-store` на защищённых страницах и страницах ввода секретов | test_security_headers |
| `/settings/mail-log/` | показывает адресата, шаблон, статус и текст `MailAttempt.error` (без секретов) | test_mail |

### Службы, команды, письма

| Имя | Что | Тест |
|---|---|---|
| `apps.core.services.retention.purge_login_history() -> int`, `purge_expired_links()`, `purge_expired_sessions()` | ночные очистки; первая удаляет `LoginAttempt` старше `login_history_days` и возвращает число; журнал событий не трогают ни они, ни что-либо иное; зарегистрированы в `config/cron.py` вызовами `register(<функция>, …)` | test_devices, test_audit, test_deploy_files |
| задание очереди `mail` | `Retry(max=11, interval=[60, 300, 900, 3600] + [10800]*7)` (`job.retries_left == 11`, `job.retry_intervals`), `failure_callback` задан; единственный аргумент — номер письма, `kwargs` пусты; первая попытка — сразу, не отложена; `MailMessage.attempts` растёт на каждой попытке, `last_error` — текст ошибки без секретов; смена статуса пишет `mail.status_changed` (`object_id` — номер письма, `before["status"]`, `after["status"]`) | test_mail, test_mail_live |
| письма | текст и `Subject` по-русски, название портала в теме или тексте; время письма «о новом устройстве» — Москва, `ЧЧ:ММ` и дата, браузер, платформа, адрес, указание «закрыть сессию» и «сменить пароль», ссылок нет; ссылка активации `PORTAL_URL/activate/#<код>` — только в приглашении, `PORTAL_URL/password/reset/#<код>` — только в восстановлении | test_mail, test_devices |
| рабочий процесс тестов | `tests/support_mail.py`: `deliver()` — `rq.SimpleWorker` в процессе теста (отдельный процесс не видит данных теста), `break_smtp(settings)`, `run_scheduler_step()`, `make_due(job)` | test_mail, test_mail_live |
| `rotate_field_keys` | читает `settings.FIELD_ENCRYPTION_KEYS` при вызове; при шифротексте, не открывающемся ни одним ключом, — `CommandError` и ни одна строка не меняется (одна транзакция); вывод не содержит ключей и кодов | test_field_keys |
| ключи настроек безопасности | таблица границ из «Решений Opus»: при отказе в ответе (200) названа нарушенная граница числом, значения и журнал не меняются; форма сохраняется целиком или не сохраняется; нечисловое и дробное — отказ | test_security_settings_bounds |

### Файлы развёртывания (test_deploy_files)

| Имя | Что |
|---|---|
| `deploy/nginx.conf` | `set_real_ip_from` с `${TRUSTED_PROXIES}` или адресами (не `0.0.0.0/0`, не `all`), `real_ip_header X-Forwarded-For`, `real_ip_recursive on`; в Django `X-Forwarded-For $remote_addr`; `X-Forwarded-Proto` только значением-переменной (`$scheme`…), не константой; `location /media/` с `add_header X-Content-Type-Options "nosniff" always;`; свой `log_format` без `$request`, `$request_uri`, `$args`, `$query_string`, `$http_cookie`, `$http_authorization`, `$request_body`, `$http_referer` (путь — `$uri`), `access_log` использует его; `listen … ssl`, `ssl_certificate` и `ssl_certificate_key` в `/etc/nginx/certs/`, `ssl_protocols` только TLSv1.2/1.3, `return 301 https://` для HTTP |
| `deploy/dev-cert.sh` | исполняемый, `set -e…`, `openssl req -x509`, `subjectAltName` с `127.0.0.1`, пишет в `deploy/certs/` |
| `deploy/.gitignore` | строка `certs/` |
| `deploy/docker-compose.yml` | сервисы `web`, `worker`, `worker-mail`, `worker-inbox`, `worker-notify`, `notify-poller`, `scheduler`, `backup`, `nginx`, `postgres`, `valkey`, `mailpit`, `dovecot`, `fakebots`; `profiles: ["dev"]` только у `mailpit`, `profiles: ["dev", "test"]` у `dovecot` и у `fakebots`; `worker`: `rq worker -c config.rq_settings --with-scheduler files`, `worker-mail`: то же с очередями `mail maintenance`, `worker-inbox`: то же с очередью `inbox` (раздел 1 CONTRACT-003); `worker-notify`: то же без `--with-scheduler` с очередью `notify`, две копии; `notify-poller`: `python manage.py notify_poll`, одна копия (раздел 1.3 CONTRACT-004); `scheduler`: `rq cron config.cron` без `--with-scheduler`; `web`: `gunicorn` + `uvicorn_worker.UvicornWorker` + `config.asgi` (compose или `Dockerfile`); у `nginx` — `./certs:/etc/nginx/certs` и `127.0.0.1:8031:`; порты postgres и valkey наружу не публикуются; `location /ws/` в `nginx.conf` и `nginx.prod.conf` (раздел 1.3 CONTRACT-004); служба `test` ждёт `fakebots` |
| закрытые ключи | в `deploy/` и `backend/` нет `*.key`, `*.pem`, `*.p12` и текста `-----BEGIN … PRIVATE KEY-----` вне `deploy/certs/` |

## Решения Opus по вопросам этапа 2б (2026-10-01)

**Цепочка прокси: прокси администратора → наш nginx → Django.** Один список
`TRUSTED_PROXIES` (адреса и сети CIDR через запятую) содержит адреса прокси
администратора и внутреннюю сеть docker compose, в которой стоит наш nginx.
- nginx: `set_real_ip_from` по каждому элементу списка, `real_ip_header
  X-Forwarded-For`, `real_ip_recursive on`; в Django передаёт
  `X-Forwarded-For $remote_addr` — один, уже восстановленный адрес клиента.
- Django: если `REMOTE_ADDR` (наш nginx) входит в список, адрес клиента —
  последний недоверенный адрес из `X-Forwarded-For`; иначе — `REMOTE_ADDR`.
  Список понимает и адреса, и сети CIDR.
- Без внутренней сети в списке Django увидел бы адрес nginx у всех клиентов,
  без адреса прокси администратора — его адрес у всех клиентов; оба случая
  сломали бы блокировку по адресу. Тест развёртывания проверяет, что в
  `.env.example` и в nginx список не пуст и не `0.0.0.0/0`.

**Остальное из итога исполнителя T-111…T-119 принимается:** имена
маршрутов устройств и параметров журнала; «Закрыть сессию» и «Забыть
устройство» оба делают следующий вход с него «новым»; почтовые тесты на
`SimpleWorker` в процессе теста (настоящий рабочий процесс — Playwright и
T-304); структурная проверка «журнал пишется из сервисов, не из
представлений»; каталог `deploy/certs/` в `.gitignore`.

## Дополнения исполнителя T-140…T-151 (проход в браузере)

Имён плана и прежнего контракта не меняли. Ниже — разметка и служебные имена, которых e2e-тестам не
хватало; их реализует Этап 3 (шаблоны T-24x, письма, сервис блокировки). Помощники — `tests/e2e/helpers.py`,
общие фикстуры — `tests/e2e/conftest.py`.

### Общая разметка и сообщения

| Имя | Что | Тест |
|---|---|---|
| `[role=alert]` / `[role=status]` | ошибки форм и отказы (включая «ссылка просрочена / недействительна / уже использована») — `role="alert"`; подтверждения и «если такая запись есть, письмо отправлено» — `role="status"` | все e2e |
| `[data-portal-name]`, `img[data-portal-logo]` | название и логотип портала на странице входа и в `#top-bar`; `<title>` содержит название; без загруженного логотипа `<img>` показывает знак по умолчанию | test_s14 |
| сообщения мёртвых ссылок | просроченная и выдуманная — одно и то же сообщение со словами «просроч» и «администратор»; использованная — со словом «использован» и ссылкой `a[href="/login/"]`; ссылка восстановления — «недействит…»; после открытия адрес без `#…` | test_s08, test_s18 |
| подтверждение в формах | если у меняющей формы есть `input[name=confirm]` (флажок), тесты отмечают его перед отправкой | helpers.submit |
| `<html lang="ru">` | язык страниц | test_cross_cutting |
| письмо | заголовок `X-Portal-Template: <MailMessage.template>` (`invitation`, `password_reset`, `account_locked`, `new_device`, `second_factor_reset`, `password_changed`); читается Mailpit по `/api/v1/message/<id>/headers` | helpers.template_of |

### Вход и мастер

| Имя | Что | Тест |
|---|---|---|
| `/login/` | ссылка «Забыли пароль?» (`a[href="/password/forgot/"]`); при выходе по бездействию в тексте страницы слово «бездейств» | test_s18, test_s10 |
| `/login/code/` | поле `input[name=code]`; ссылка «Войти по резервному коду» показывает `input[name=backup_code]` (оба поля в формах с `button[type=submit]`) | helpers.use_backup_code |
| `/activate/totp/`, `/me/security/totp/` | ключ в base32 — текст элемента `<code id="totp-secret">` (пробелы допустимы), QR — `<img id="totp-qr">`; поле `input[name=code]` | test_s03, test_s07 |
| `/activate/codes/`, `/me/security/backup-codes/` | десять `<code class="backup-code">`; флажок `input[name=confirm]` и `button[type=submit]` («Я сохранил коды»): без флажка дальше не пускает | test_s03, test_s07 |
| `/activate/profile/` | поле `phone`; `contacts` — `textarea`/поле; `button[type=submit]` | helpers.walk_activation |
| ограниченная сессия после пароля без второго фактора | вход ведёт на `/me/security/totp/`; `/`, `/me/`, `/staff/` отвечают 302 туда же | test_s03, test_s07 |
| `/staff/new/` | GET — страница формы (для рядового сотрудника — 403); поля `email`, `full_name`, `position`, `phone` (не обязательное), роли — флажки `roles`, у каждого `<label>` с названием роли; кнопка «Создать и пригласить»; не больше шести видимых полей | test_s02 |

### Сотрудники, блокировки, роли

| Имя | Что | Тест |
|---|---|---|
| `/staff/` | строка — `<tr data-user-id="<id>" data-user-email="<почта>" data-state="invited\|active\|blocked">` со ссылкой `a[href="/staff/<id>/"]`; фильтр `?state=blocked` | test_s01, test_s02, test_s15 |
| `/staff/<id>/` | ссылка приглашения — текст элемента `[data-invitation-link]`; состояние письма — `[data-mail-status="queued\|sent\|failed"]`; формы `…/invite/`, `…/reset-2fa/`, `…/block/` (поле `reason`), `…/unblock/`, `…/roles/` (флажки `roles`, значение — id роли, `<label>` — название) с `button[type=submit]` | test_s02, test_s07, test_s12, test_s15 |
| `/staff/<id>/logins/`, `/me/security/history/` | строки истории — `[data-history-row][data-result="success\|bad_password\|bad_code\|locked\|ip_locked\|backup_code"][data-at="<ISO 8601>"]` по убыванию времени, время в тексте строки по Москве `ЧЧ:ММ` | test_s09, test_s11, test_cross_cutting |
| `/me/security/devices/`, `/staff/<id>/logins/` | строки устройств — `[data-device-id][data-current="true\|false"]`; формы `form[action$="/close/"]`, `form[action$="/forget/"]` | test_s05, test_s11 |
| `/staff/locks/` | строка — `[data-lock-kind="account\|ip"][data-lock-target="<id записи \| адрес>"]` с формой POST и кнопкой «Снять блокировку входа» | test_s09 |
| `/roles/` | строка — `[data-role-id="<id>"][data-role-name="<название>"]`; форма `/roles/new/` и страница роли: `name`, флажки `permissions` (значение — код права, `audit.view` и т. д.), у страницы роли форма удаления `form[action$="/delete/"]` | test_s12, test_s13 |
| `/me/security/` | ссылки на пароль, устройства, историю, резервные коды; формы `/me/security/logout-everywhere/` и `/me/security/backup-codes/new/`; `data-backup-remaining` | test_s06, test_s10 |

### Журнал, настройки

| Имя | Что | Тест |
|---|---|---|
| `/audit/` | форма фильтра `form#audit-filter` (поля `date_from`, `date_to`, `user`, `action`, `object_type`, `object_id`, кнопка «Найти»; `object_type` — выпадающий список `select#id_object_type`, значения параметра прежние: `user`, `link`, `mail`, `role`, `ip`, `security_settings`, `portal_settings`; время в колонке «Время» — `ДД.ММ.ГГГГ ЧЧ:ММ:СС` по Москве); «Найти» и пресеты через HTMX обновляют только таблицу — элемент `#audit-filter` остаётся тем же; ссылки пресетов `a[href*="preset=access"]` (и `today`, `roles`, `settings`); заголовок сортировки — `?sort=at\|-at`; строка — `tr[data-event-id][data-action="<код>"][data-at="<ISO 8601>"]` с текстом «было» и «стало»; выгрузка — `a[href*="/audit/export.csv"]` («Выгрузить выбранное», с текущими параметрами); внизу — `nav[aria-label="Страницы журнала"]`: «Всего: показать количество» — `a[href*="count=1"]` (по HTMX обновляет только таблицу), после щелчка «Всего: N.»; «Страница N.» без общего числа страниц, «Назад» и «Вперёд» — `?page=N`; кнопок «Удалить/Изменить» нет, у `/audit/<id>/…` ответ 403/404/405 на POST и DELETE | test_s13 |
| пресет «Вход и доступ» | события с кодами `login.*`, `logout`, `account.*`, `ip.*`, `totp.*`, `backup_code*`, `invitation.*`, `password.*`, `link.*`, `sessions.*`, `user.*`; ролей, настроек и писем (`role.*`, `security_settings.*`, `portal_settings.*`, `mail.*`) в нём нет; пресет «Права и роли» — `role.*` | test_s13 |
| `/settings/portal/` | форма `form[action="/settings/portal/"]`: `name`, `logo`, кнопка «Вернуть по умолчанию» — `button[name=reset][value="1"]`; отказ — `[role=alert]` со словами «логотип» или «изображен», для размера — с числом `512` или `1 МБ` | test_s14 |
| `/settings/security/` | форма `form[action="/settings/security/"]` с полями модели, кнопка `button[type=submit]`; при отказе по границе в `[role=alert]` названа граница числом (длина — 12, бездействие — 5…60) | test_s17 |

### Ключи Valkey и команды стенда

| Имя | Что | Тест |
|---|---|---|
| `lock:ip:<ip>` | ключ блокировки адреса (парный `lock:acct:<id>`); вместе с `fail:ip:<ip>` и `accts:ip:<ip>` e2e-фикстура `fresh_counters` удаляет их перед каждым тестом (все проходы идут с одного адреса, неудачи соседних тестов иначе заблокировали бы его) | conftest |
| `forgot:email:<хеш адреса>`, `forgot:ip:<ip>` | счётчики запросов восстановления (3 письма в час на адрес, 10 в час на IP); имена содержат `forgot:`, фикстура удаляет `*forgot:*`; приставка Django-кэша допустима | test_s18, conftest |
| `manage.py shell` в контейнере `web` | e2e состаривает ссылку активации (`core.OneTimeLink.expires_at`) и ставит порог бездействия (`core.SecuritySettings.idle_timeout_minutes`, форма не даёт меньше 5 минут); переопределяется `E2E_SHELL_CMD` | helpers.stand_shell |
| журнал nginx | `docker compose logs --no-color --no-log-prefix nginx` (access_log в stdout) или файл из `E2E_NGINX_LOG_FILE`; в формате `$uri` — в журнале видны пути `/activate…` и `/password/reset…` | test_cross_cutting |
| круг по браузеру | `create_first_admin` отказывает на непустой базе, поэтому проход идёт кругами chromium → firefox → edge, в начале круга база должна быть пуста (`E2E_RESET_CMD` — команда сброса данных стенда, выполняется один раз на круг); внутри круга первым идёт `test_s01_first_admin.py`; остальные тесты берут администратора круга фикстурой `stand_admin` | conftest |

Идёт вне e2e: «письмо ждёт в очереди при недоступном SMTP» (сценарий 2, п. 3) и нагрузка 500 мс при 100
пользователях — test_mail/test_mail_live и tests/load; порог бездействия формой — test_s17 (форма) и
test_s10 (механика, 1 минута через базу).

## Решения Opus по вопросам этапа 2в (2026-10-01)

- **Сброс стенда для кругов по браузерам** (`E2E_RESET_CMD`): команда
  `python manage.py e2e_reset_stand` очищает базу стенда и счётчики Valkey и
  работает ТОЛЬКО при `E2E_STAND=1` в окружении (задаётся лишь профилем dev
  compose); без флага отказывает с ненулевым кодом и ничего не трогает.
  Тест сервера проверяет отказ без флага.
- **Журнал доступа nginx** — в stdout контейнера (NFR-23), читается
  `docker compose logs nginx`.
- Правка сроков ссылок и порога бездействия через `manage.py shell` в
  контейнере `web` — допустима только в приёмочных тестах стенда.
- Заголовок письма `X-Portal-Template` (имя шаблона, без персональных
  данных) и ключи Valkey `lock:ip:`, `forgot:email:<хеш>`, `forgot:ip:` —
  принимаются как контракт этапа 3.

## Дополнения по итогам этапа 3, проход 2 (Opus, 2026-10-01)

- **Политика реферера везде `same-origin`**, отдельного `no-referrer` для
  страниц ссылок нет: код живёт только во фрагменте `#…`, а фрагмент в
  Referer не уходит. Проверка CSRF — стандартная Django без исключений,
  `Origin: null` отвергается всегда.
- **RQ:** `config/rq_settings.py` (поднимает Django, отдаёт адрес Valkey).
  Рабочие процессы: `rq worker -c config.rq_settings --with-scheduler` с очередями `files` (`worker`), `mail maintenance` (`worker-mail`) и `inbox` (`worker-inbox`), `rq worker -c config.rq_settings notify` (`worker-notify`, без `--with-scheduler`), опрос ботов — `python manage.py notify_poll` (`notify-poller`),
  ночные задания: `rq cron config.cron -c config.rq_settings` (задания среза 001 — очередь `mail`,
  03:10, 03:20, 03:30).
- **Письма:** код ссылки в задание не передаётся — рабочий процесс берёт его
  из `OneTimeLink`; погашенная до отправки ссылка — письмо `failed` без
  повторов; отправка всегда SMTP (`EmailBackend`), `failed` только при
  `retries_left == 0`.
- **`/media/`** отдаёт только PNG и JPEG с `nosniff`, остальное — 404.
- **Резервные коды** выпускаются при показе страницы кодов; до «Я сохранил»
  перезагрузка выпускает новый набор, после — повторный показ невозможен.
- **Страница входа не повторяет введённую почту** (одинаковый ответ на любой
  отказ, FR-034). Верхняя панель — ссылки и кнопка «Выйти» без выпадающего
  меню; кнопки, не отправляющие форму, — без `type="submit"`.

## Дополнения по проверке PLAN-001 версии 3 (Opus, 2026-10-02)

- **`/media/` в nginx** (`nginx.conf` и `nginx.prod.conf`): regex-location
  отдаёт только `.png`, `.jpg`, `.jpeg` с типом по расширению и `nosniff`;
  prefix-location `/media/` — `return 404`. Каталог целиком не отдаётся.
- **Учётные данные владельца схемы**: миграции выполняет разовая служба
  compose `migrate` (`RUN_MIGRATIONS=1`, `restart: "no"`), web ждёт её через
  `service_completed_successfully`; у web, worker, worker-mail, worker-inbox, worker-notify, notify-poller и scheduler
  `DATABASE_MIGRATE_URL: ""`. `DATABASE_MIGRATE_URL` есть у `migrate`,
  `standtools` и `test`; служба `backup` получает только `DATABASE_MIGRATE_URL` из `.env` через `environment`, без `env_file` (решение Opus C9); у `worker-mail` и `worker-inbox`, `worker-notify` и `notify-poller` — `DATABASE_MIGRATE_URL: ""`, как у `worker`. Тест — test_deploy_files::test_owner_credentials_only_in_one_shot_migrate_service (перечень служб в теле теста не меняется: он проверяет только `web`, `worker`, `scheduler`).
