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
| Файлы | `config/cron.py`, `apps/core/management/commands/{create_first_admin,rotate_field_keys}.py`, `deploy/{Dockerfile,nginx.conf}`, `templates/` с подключением `vendor/bootstrap-*`, `vendor/htmx-*`, `vendor/alpine-*` через `{% static %}` | test_stack::test_project_layout_matches_plan, test_vendor_assets_present_with_licenses |
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
