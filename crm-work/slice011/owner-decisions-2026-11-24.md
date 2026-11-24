# Срез 011 — решения владельца по задачам (2026-11-24)

## Разрешение на правки прежних тестов

Владелец через форму сессии 2026-11-24 ответил: **«Разрешаю все три задачи»**.

Разрешены строки таблиц TASKS-011:

- **T-11010 — права:** `test_permissions.py:26,37-40` (администратор 24 из 25, «Руководитель» плюс
  `servicedesk.reports`), `test_org_permissions.py:129,140-155`, `test_sd_access.py:527,541-544`,
  `test_instructions_deploy.py:263` (22→25), `test_feed_seed.py:65,143-146` (20→23, 22→25, «последние два» —
  права ленты), `test_lists_seed.py:174,176-177` (21→24, 22→25, последнее — `lists.manage`).
- **T-11011 — меню:** `test_org_permissions.py:701-705`, `test_tasks_deploy.py:295`,
  `test_tasks_core_changes.py:295,304`, `test_messenger_deploy.py:506`, `test_lists_access.py:864`,
  `test_instructions_deploy.py:214` (20→21, 16→17; «Уровни обслуживания»), `test_sd_boundaries.py:481`.
- **T-11018 — каталог, cron, журнал, стенд:** `test_sd_boundaries.py:472` (4→7),
  `test_notify_catalog.py:150,153` (7 видов сервис-деска, 43 всего), `test_messenger_notify_2.py:48,248-249`
  (`MODULE_COUNTS`, 40→43), `test_messenger_deploy.py:486`, `test_notify_prefs.py:29,32,212`
  (отдельный `SLA_KINDS` после `MESSENGER_CODES`), `test_notify_catalog_2.py:579`, восемь deploy-тестов
  `len(...) == 27` → 29, `test_sd_audit.py:32-60,81-121,149-152`, `test_sd_stand_restore.py` (одна проверка
  ключей).

Тесты не ослабляются: каждая строка — «было / стало» с новыми значениями; ожидания поведения не меняются.
