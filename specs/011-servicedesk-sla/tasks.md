---
id: TASKS-011
вид: задачи
статус: черновик
версия: 5
зависит_от: PLAN-011
основан_на: PLAN-011 sha256:9a7d6ce930c06e641f142f371904b7776ef3bd94bb2b3381a13750c23dac13e9
---

# Задачи среза 011: Сроки и отчёты заявок

Формат строки: `- [ ] T-NNNN [P] [исполнитель] описание — файлы или тест — (FR-NNN / NFR-NNN)`.
`[P]` — можно делать параллельно с соседними (нет общих файлов). Исполнитель — `code` (код и тесты),
`arch` (архитектура, контракт, финальные), `человек` (подписи и ручные проходы). Модель под роль — по
действующему порядку владельца, не по ярлыку.

Источники: SPEC-011 (FR-730…758, NFR-730…735), PLAN-011 v5. Решения, которых нет в плане, — в разделе
«Решения Opus по задачам».

Как читать и исполнять:
- **Нумерация.** Этап 1 — T-11001…T-11011 и T-11018, Этап 2 — T-11101…T-11112 плюс T-11150/T-11159/T-11160, Этап 3 —
  T-11201…T-11217, T-11260, Этап 4 — T-11300…T-11308.
- **Порядок.** Этапы подряд. Внутри этапа задача без `[P]` начинается после предыдущих; `[P]` не зависит от
  соседей и не правит общие файлы. **Миграции:** `core 0016` (T-11003) идёт до `servicedesk 0004` (T-11002),
  потому что 0004 от неё зависит.
- **Тест-на-требование.** В Этапе 2 у каждого теста в скобках FR/NFR; `файл::имя` — связь задача → требование →
  тест. Браузерные сценарии — `backend/tests/e2e/test_t11_*.py`.
- **Красный прежде зелёного.** Этап 3 не начинается до T-11160: каждый новый тест падает, кроме тестов Этапа 1
  (модели, права, меню, стенд) — их зелёный результат записывается отдельно, как в срезе 010.
- **Правки прежних тестов — три задачи:** T-11010 (права), T-11011 (меню) и T-11018 (каталог уведомлений, cron,
  журнал, стенд), каждая строка «было / стало», **только с разрешения владельца**.
- **Один автор на общий файл.** `apps/servicedesk/urls.py` — T-11006; `models.py` — T-11002; `config/cron.py` —
  T-11007; `extensions.py` — T-11006 (заглушки) и T-11213 (реализация); `stand.py` — T-11008; данные прав —
  T-11003; нагрузка — T-11009.
- **Размер.** Задача — не больше полудня одного исполнителя; задание агенту — не больше ~50 вызовов; файл
  тестов — не больше ~25 тестов (больше — `_2`).
- **Партии Этапа 3** (в перечисленном порядке, он важнее номеров задач): сроки и циклы — T-11201, T-11204,
  T-11205 → уровни, поля и очередь — T-11202, T-11203, T-11206, T-11215 → уведомления и сводка — T-11207,
  T-11211 → отчёт и Excel — T-11208, T-11216, T-11209 → шаблоны — T-11210, T-11217 → настройки, меню, тексты —
  T-11212, T-11213, T-11214. После каждой партии — весь серверный набор.
- **Вне перечня.** Если в Этапе 3 падает прежний тест вне таблиц T-11010/T-11011/T-11018 — остановка, решение Opus,
  запись в решения; тест не ослаблять.
- **Секреты.** В отчётах только `***`; ПДн и пароли в задачи не попадают.

## Этап 1 — каркас, контракт, данные, помощники, стенд

- [ ] T-11001 [arch] `CONTRACT-011`: маршруты уровней, отчёта, шаблонов, вставки (`?ticket=`), фильтр `due`,
  счётчики, зацепки `data-*`, коды и тексты отказов (`sla_title_range`, `sla_minutes_range`,
  `sla_reaction_gt_solution`, `sla_days_empty`, `sla_interval_empty`, `sla_assignee_dismissed`,
  `answer_title_range`, `answer_text_range`, `answer_category_personal`, `report_period_range`,
  `report_forbidden`), ответы HTMX и обычных запросов, подписи журнала — `backend/tests/CONTRACT-011.md` —
  (все FR)
- [ ] T-11003 [arch] права `servicedesk.sla`, `servicedesk.reports`, `servicedesk.answers` и начальные выдачи
  («Администратор портала» — `sla` и `answers`, роль «Руководитель» — `reports`), миграция `core 0016` от
  `0015`, идемпотентна; у администратора **24** права из 25 — `reports` ему не выдан —
  `backend/apps/core/migrations/0016_servicedesk_sla_permissions.py` — (FR-756)
- [ ] T-11002 [arch] модели и миграция `servicedesk 0004` (после T-11003): `SlaLevel`, `SlaBinding`,
  `AnswerTemplate`, `SlaCycle`, `SlaNotice`, `SlaDigest`, поля `Ticket` (`sla`, `sla_cycle_started_at`,
  `sla_reaction_due`, `sla_solution_due`, `sla_first_response_at`), `ServiceDeskSettings.sla_reminder_hours`;
  ограничения и индексы плана; `default_permissions = ()`, русские `verbose_name`; `manage.py check` — 0 —
  `backend/apps/servicedesk/models.py`, `backend/apps/servicedesk/migrations/0004_sla_answers.py` —
  (FR-730…745, FR-751, FR-752)
- [ ] T-11004 [P] [arch] помощники серверных тестов: `PERMISSIONS_011`, `TITLES_011`, `KINDS_011`,
  `make_level`, `bind_level`, `make_answer`, `make_cycle`, `close_ticket`, `reopen_ticket`, `report_numbers`,
  `notice_rows`; без импорта кода приложения на уровне модуля — `backend/tests/support_servicedesk.py` —
  (все FR)
- [ ] T-11005 [P] [arch] помощники e2e и seed стенда: `open_sla`, `create_level`, `open_report`, `export_xlsx`,
  `insert_answer`, `check_360`; `e2e_sla_seed` (два уровня, привязки, три шаблона, заявки со сроками) —
  `backend/tests/e2e/helpers_sla.py`, `backend/apps/servicedesk/management/commands/e2e_sla_seed.py` —
  (FR-730…754)
- [ ] T-11006 [arch] маршруты и **заглушки** представлений, пункты меню «Уровни обслуживания» (order 6,
  `servicedesk.sla`) и «Отчёт по заявкам» (order 7, `servicedesk.reports`; order 7 уже занят «Базой знаний»,
  порядок при равных order решает вторичный ключ названия — «База знаний» раньше «Отчёта»), подключение
  `answers.js` для `/servicedesk/answers/` и карточки — `backend/apps/servicedesk/urls.py`, `views/sla.py`,
  `views/reports.py`, `views/answers.py`, `extensions.py`, `backend/templates/_assets.html` —
  (FR-730…757)
- [ ] T-11007 [arch] задания-заглушки и записи cron: `sla_tick` (`*/5 * * * *`, 300) с замком `sla:tick`,
  `sla_digest` (`10 * * * *`, 300) в `maintenance` — `backend/apps/servicedesk/tasks.py`,
  `backend/config/cron.py` — (FR-743, FR-744, NFR-734)
- [ ] T-11008 [arch] стенд: `stand_reset` чистит `SlaCycle`, `SlaNotice`, `SlaDigest`, уровни, привязки,
  шаблоны, поля сроков у заявок, ключи `sla:tick`, `servicedesk:sla:*`, `servicedesk:digest:*`; порядок строк
  сохраняется; проверка удаления ключей — тест стенда (T-11112) — `backend/apps/servicedesk/stand.py`,
  `backend/tests/test_sd_stand_restore.py` — (все FR)
- [ ] T-11009 [arch] нагрузка: `ServiceDeskUser` получает страницы `/servicedesk/reports/?period=week` и
  `/tickets/?due=overdue`, имена в `SD_PAGES`/`_check_sd_p95`; `fill_tickets.py` с `LOAD_TICKETS_SLA=1` создаёт
  уровни, привязки и сроки у 20 % заявок — `backend/tests/load/locustfile.py`,
  `backend/tests/load/fill_tickets.py` — (NFR-730)
- [ ] T-11010 [arch] правки прежних тестов — **права** (только после разрешения владельца), строки ниже —
  `backend/tests/…` — (FR-756)
- [ ] T-11011 [arch] правки прежних тестов — **меню** (только после разрешения владельца), строки ниже —
  `backend/tests/…` — (FR-730…758)
- [ ] T-11018 [arch] правки прежних тестов — **каталог уведомлений, cron, журнал, стенд** (только после разрешения
  владельца), строки ниже; в сценарий `_everything` добавляется создание `ticket.assignee_skipped`, иначе точный
  набор кодов журнала его не проверяет — `backend/tests/…` — (FR-743, FR-755, NFR-734)

## Этап 2 — красные серверные тесты, браузер и стенд

- [ ] T-11101 [code] модели и ограничения: `default_permissions`, диапазоны, отказ `reaction_minutes >
  solution_minutes`, уникальность привязок, `all_day OR day_start < day_end`, уникальность `(ticket, number)`,
  частичный текущий цикл, **архив уровня**, **ограничения `AnswerTemplate`** (1–100, 1–10 000, личный без
  категории) — `test_sd_sla_models.py` (14) — (FR-730…733, FR-751, FR-752)
- [ ] T-11102 [code] расчёт сроков: вечер пятницы 09:20, суббота уровня при выходном календаре, `short`
  (уровень 09–12 остаётся), `holiday`, `day_off`, `workday`, `all_day`, 28.02/29.02/01.03; `minutes_between` —
  `test_sd_sla_deadlines.py` (14) — (FR-734, FR-735, NFR-733)
- [ ] T-11103 [code] заявка и уровень: подбор по критичности/категории, снимок, пересчёт до первого ответа (и
  обновление цикла), уровень появился после создания, передача до первого ответа, ответственный уровня и
  конфликт с категорией, заявка без уровня — `test_sd_sla_ticket.py` (12) — (FR-734…737)
- [ ] T-11104 [code] циклы: первый ответ (`queued`, `waiting_files`, `not_sent`, комментарий), закрытие ручное и
  авто, reopen вручную и **письмом с `received_at`**, `is_current`, прошлый цикл не в отчёте, вердикты —
  `test_sd_sla_cycles.py` (13) — (FR-738…740)
- [ ] T-11105 [code] очередь и карточка: `due=overdue` (включая закрытую позже срока) и `due=today` с пресетами,
  счётчики, блок `_sla.html`, «срок не задан», права и 403 — `test_sd_sla_views.py` (12) — (FR-741, FR-742, FR-757)
- [ ] T-11106 [code] журнал и язык: записи уровня, привязок, шаблона, выгрузки и `ticket.assignee_skipped` с
  автором и временем; русский и Москва — `test_sd_sla_audit.py` (8) — (FR-755, FR-758)
- [ ] T-11107 [code] уведомления: три вида, получатели (ответственный, `heads_of_unit` с предками), отдельные
  напоминания по реакции и решению, границы 1/24/25 часов, опережение, без повторов, внешний текст без темы —
  `test_sd_sla_notify.py` (12) — (FR-743, FR-744, NFR-732, NFR-734)
- [ ] T-11108 [code] отчёт: период, только текущий цикл, фильтры и нагрузка по снимкам, **просрочки по уровням**,
  **нагрузка «закрыто на исполнителя»**, знаменатель доли в срок, область `managed_units`, 370/371, границы
  суток, неизменность истории (уровень, календарь, передача, ответственный), **пустой отчёт**, **пустая оценка
  заявителей**, 403 — `test_sd_reports.py` (17) — (FR-746…750, NFR-735)
- [ ] T-11109 [code] Excel: два листа, те же числа, 20 000 строк ≤ 10 с, нет темы/текста/адреса, чужие очереди
  отсутствуют, запись журнала — `test_sd_reports_excel.py` (8) — (FR-748, NFR-731)
- [ ] T-11110 [code] частые ответы: общие и личные, видимость, архив, категория у общего, вставка `?ticket=`,
  чужой личный и архивный 404 — `test_sd_answers.py` (10) — (FR-751…754)
- [ ] T-11111 [code] задания: обе записи в расписании, замок тика, перезапуск до/во время/после записи, сводка в
  окне `day_start`, **три раздела сводки** (просроченные, срок сегодня, срок на неделе), один раз в день —
  `test_sd_sla_cron.py` (10) — (FR-744, NFR-732, NFR-734)
- [ ] T-11112 [code] изменения ядра: права `core 0016` и выдачи (у администратора 24, у «Руководителя» плюс
  `reports`), четыре пункта меню, метки, `stand_reset` (включая удаление ключей `sla:tick`, `servicedesk:sla:*`,
  `servicedesk:digest:*`), хвост `INSTALLED_APPS` не меняется — `test_sd_sla_core_changes.py` (7) и
  `test_sd_stand_restore.py` (1 проверка ключей) — (FR-755, FR-756)
- [ ] T-11150 [code] браузерные сценарии `t11_01`…`t11_06` (уровень, сроки в заявке, просрочка, отчёт и Excel,
  шаблоны, 360 px) — `backend/tests/e2e/test_t11_*.py` — (FR-730…758)
- [ ] T-11159 [arch] обновление стенда образом среза (копия → сборка → миграции → службы) — **с разрешения
  владельца**; `/servicedesk/sla/` отвечает 302 — `crm-work/slice011/…` — (все FR)
- [ ] T-11160 [arch] красный серверный прогон: каждый новый тест падает, **кроме тестов Этапа 1** (модели,
  права, меню, стенд), их зелёный результат записывается отдельно; артефакты — `crm-work/slice011/stage2/` —
  (все FR)

## Этап 3 — реализация партиями

- [ ] T-11201 [code] служба сроков: интервалы дня по уровню и календарю, `deadline`, `minutes_between`, снимок
  `schedule.days`, расчёт рабочих минут — `services/sla.py` — (FR-734, FR-735, NFR-733)
- [ ] T-11202 [code] уровни и привязки: служба, формы, страница, привязки; метки журнала уровней —
  `services/sla.py`, `views/sla.py`, `audit_labels.py`, шаблоны `sla/` — (FR-730…733, FR-755)
- [ ] T-11203 [code] применение уровня: создание заявки, `transfer` (категория/критичность/очередь), ответственный
  по умолчанию, пересчёт до первого ответа — `services/tickets.py`, `services/transfer.py`,
  `views/ticket_new.py` — (FR-734…737)
- [ ] T-11204 [code] первый ответ: факт и минуты реакции при `queued`-ответе, `waiting_files`, исключения —
  `services/replies.py` — (FR-738)
- [ ] T-11205 [code] закрытие и циклы: ручное и авто-закрытие, `reopen(at)`, вердикты, журнал с номером цикла —
  `services/closing.py`, `services/intake.py`, `audit_labels.py` — (FR-739, FR-740, FR-755)
- [ ] T-11206 [code] очередь и блок карточки: поле `due` в `Filters` и `_read`, колонка и сортировка по сроку,
  счётчики, блок `_sla.html` — `services/listing.py`, `views/tickets_list.py`, `views/ticket_card.py`,
  `templates/servicedesk/list/{_grid,page}.html`, `card/_sla.html`, `card/_card.html` — (FR-741, FR-742, FR-757)
- [ ] T-11215 [code] архив уровня и права страниц уровней; метки журнала привязок — `services/sla.py`,
  `views/sla.py`, `audit_labels.py` — (FR-730, FR-755)
- [ ] T-11207 [code] уведомления о сроках: виды, `heads_of_unit`, напоминание и просрочка через `SlaNotice` в
  одной транзакции, внешний текст — `notify_kinds.py`, `tasks.py`, `apps/org/services/structure.py` —
  (FR-743, NFR-732, NFR-734)
- [ ] T-11211 [code] ежедневная сводка: окно `day_start`, `SlaDigest`, получатели, три раздела сводки —
  `tasks.py` — (FR-744)
- [ ] T-11208 [code] показатели отчёта: SQL-агрегаты по текущим циклам (создано, закрыто, средние, доля в срок,
  просрочки по уровням, нагрузка, пустая оценка) — `services/reports.py` — (FR-746…750)
- [ ] T-11216 [code] страница отчёта: фильтры, область `managed_units`, период ≤370 дней и границы суток по
  Москве, 403 — `services/reports.py`, `views/reports.py`, `templates/servicedesk/reports/page.html` —
  (FR-746, FR-749, NFR-735)
- [ ] T-11209 [code] Excel: два листа, ограничение 20 000 строк, журнал `servicedesk.report_exported` —
  `services/reports.py`, `views/reports.py`, `audit_labels.py` — (FR-748, NFR-731)
- [ ] T-11210 [code] частые ответы: служба, страницы, архив; метки журнала шаблонов —
  `services/answers.py`, `views/answers.py`, `audit_labels.py`, шаблоны `answers/` — (FR-751, FR-752, FR-754, FR-755)
- [ ] T-11217 [code] вставка шаблона в ответ: форма ответа карточки с выбором шаблона, маршрут `insert?ticket=`,
  `answers.js` — `views/ticket_card.py`, `templates/servicedesk/card/_card.html`, `views/answers.py`,
  `static/servicedesk/answers.js` — (FR-753)
- [ ] T-11212 [code] настройка «Часы напоминания» 1–24: служба, форма, `INT_FIELDS` —
  `services/settings.py`, `views/settings.py`, `templates/servicedesk/settings/settings.html` — (FR-743)
- [ ] T-11213 [code] меню и статика: реализация пунктов «Уровни обслуживания» (6) и «Отчёт по заявкам» (7),
  подключение стилей — `extensions.py`, `templates/_assets.html` — (FR-730…757)
- [ ] T-11214 [code] тексты и раскладка: русские подписи, Москва, 360 px — шаблоны `sla/`, `reports/`,
  `answers/`, `card/_sla.html` — (FR-757, FR-758)
- [ ] T-11260 [arch] полный зелёный серверный прогон после партий; сверка с красным T-11160 — артефакты
  `crm-work/slice011/stage3/` — (все FR)

## Этап 4 — приёмка

- [ ] T-11300 [arch] «Проверить после реализации»: набор прежних тестов сервис-деска, прав, меню, каталога
  уведомлений, cron, стенда — список и числа в отчёте — (FR-741…758, NFR-734)
- [ ] T-11301 [arch] браузерные круги `t11` в Chromium, Firefox, Edge, Яндекс.Браузере; прежние срезы — `-k` —
  `backend/tests/e2e/` — (NFR-730, FR-757)
- [ ] T-11302 [arch] ворота `tools/verify.sh --быстро`, `manage.py check`, `git diff --check` — (NFR-730, NFR-731)
- [ ] T-11303 [arch] нагрузка NFR-730 на холодной машине по правилам T-7304: `fill_tickets.py` с SLA и класс
  `ServiceDeskUser` (страницы отчёта и `due=overdue`), L1 и L2; известные дефекты NFR-612/707 и стенд —
  `crm-work/slice011/stage4/load/` — (NFR-730)
- [ ] T-11304 [arch] наблюдения на стенде (с разрешения владельца): отказ слоя уведомлений при напоминании,
  повтор `sla_tick` после перезапуска, ночная уборка — (FR-743, NFR-732)
- [ ] T-11305 [человек] ручной проход: уровень → заявка со сроком → просрочка → отчёт и Excel → шаблоны; 360 px —
  (FR-730…758)
- [ ] T-11306 [arch] отчёт среза: **дополнить** `docs/reviews/TASKS-011.md` разделами приёмки (прохождение
  FR-730…758 и NFR-730…735, прогоны, ворота, известные ограничения), сохранив отчёт проверки и его отпечаток —
  (все FR, все NFR)
- [ ] T-11307 [arch] инварианты по диффу среза; правки прежних тестов сверить с T-11010/T-11011/T-11018 — (FR-755, FR-756)
- [ ] T-11308 [человек] приёмка среза и `git push` — (все FR, все NFR)

## Правки прежних тестов

### T-11010 — права (разрешение владельца)

| Файл и строка | Было | Станет | Почему |
|---|---|---|---|
| `backend/tests/test_permissions.py:26` | докстринг: у администратора 22 права, у «Руководителя» ровно `staff.view` и `feed.post_all` | 24 права; у «Руководителя» плюс `servicedesk.reports` | `sla` и `answers` администратору, `reports` — руководителю |
| `backend/tests/test_permissions.py:37-39` | набор администратора — объединение `PERMISSIONS_*` срезов 001–010 | объединение плюс `servicedesk.sla` и `servicedesk.answers`; у «Сотрудника ИТ» без изменений | FR-756 |
| `backend/tests/test_permissions.py:40` | у «Руководителя» ровно `staff.view`, `feed.post_all` | плюс `servicedesk.reports` | FR-756 |
| `backend/tests/test_org_permissions.py:129,140-155` | докстринг и наборы: «Руководитель» — `staff.view`, `feed.post_all`; администратор — 22 | «Руководитель» плюс `servicedesk.reports`; администратор 24; `set(titles)` из `PERMISSIONS_011` | FR-756 |
| `backend/tests/test_sd_access.py:527,541-544` | докстринг «двадцать два кода»; равенство набора прав администратора объединению `PERMISSIONS_*`; `len == 22` | объединение плюс `servicedesk.sla` и `servicedesk.answers`; `len == 24` | FR-756 |
| `backend/tests/test_instructions_deploy.py:263` | всего прав `== 22` | 25 | FR-756 |
| `backend/tests/test_feed_seed.py:65,143-146` | 20 прав до и 22 после, «последние два» — `feed.post_all`, `feed.moderate` | 23 и 25; «последние два» остаются правами ленты (срез 011 добавляет права до `seed` ленты) | FR-756 |
| `backend/tests/test_lists_seed.py:174,176-177` | 21 до и 22 после; последнее право — `lists.manage` | 24 и 25; последним остаётся `lists.manage` (права среза 011 идут раньше `seed` списков) | FR-756 |

### T-11011 — меню (разрешение владельца)

| Файл и строка | Было | Станет | Почему |
|---|---|---|---|
| `backend/tests/test_org_permissions.py:701-705` | точный список пунктов меню администратора | плюс «Уровни обслуживания» (order 6, URL `/servicedesk/sla/`); «Отчёт по заявкам» — у держателя `reports`, order 7 вместе с «Базой знаний», «База знаний» раньше по названию | пункты меню |
| `backend/tests/test_tasks_deploy.py:295`, `test_messenger_deploy.py:506`, `test_lists_access.py:864`, `test_instructions_deploy.py:214` | `== 20` пунктов у администратора | 21 | «Уровни обслуживания» |
| `backend/tests/test_tasks_core_changes.py:295,304` | 20 и 16 пунктов | 21 и 17 | то же |
| `backend/tests/test_sd_boundaries.py:481` | меню «Заявки», «Сервис-деск» | плюс «Уровни обслуживания», «Отчёт по заявкам» | пункты меню |

### T-11018 — каталог уведомлений, cron, журнал, стенд (разрешение владельца)

| Файл и строка | Было | Станет | Почему |
|---|---|---|---|
| `backend/tests/test_sd_boundaries.py:472` | ровно 4 вида уведомлений | 7 видов | три новых вида |
| `backend/tests/test_notify_catalog.py:150,153` | точная таблица видов; у «Сервис-деска» 4 вида; докстринг «сорок видов» | плюс `servicedesk.sla_due_soon` (230), `sla_overdue` (231), `sla_digest` (232); 7 видов; «сорок три» | каталог |
| `backend/tests/test_messenger_notify_2.py:48` | `MODULE_COUNTS["Сервис-деск"] == 4` | 7 | каталог |
| `backend/tests/test_notify_prefs.py:29,32,212` | `SD_KINDS` — четыре вида, `TITLES` — их названия; список строк настроек = `SD_KINDS + [RUBRIC_KIND, LISTS_KIND] + FEED_CODES + MESSENGER_CODES` | отдельный `SLA_KINDS` (order 230–232) и `TITLES` для него; он дописывается **после** `MESSENGER_CODES`, а не в `SD_KINDS` — иначе порядок строк не совпадёт с каталогом | каталог и настройки |
| `backend/tests/test_messenger_notify_2.py:248-249`, `test_messenger_deploy.py:486` | `== 40` видов | 43 | каталог |
| `backend/tests/test_notify_prefs.py:212`, `test_notify_catalog_2.py:579` | 16 строк/ячеек | 19 | три новых вида в настройках |
| `backend/tests/test_kb_deploy.py:134`, `test_lists_deploy.py:169`, `test_feed_deploy.py:245`, `test_messenger_deploy.py:340`, `test_notify_deploy.py:321`, `test_tasks_deploy.py:243`, `test_instructions_deploy.py:188`, `test_sd_deploy.py:424` | `len(...) == 27` записей cron | 29 | `sla_tick`, `sla_digest` |
| `backend/tests/test_sd_audit.py:32-60,81-121,149-152` | `CODE_TYPES`, `TITLES`, `FIELD_TITLES`, `KEYS` | плюс `ticket.assignee_skipped` (тип, заголовок, автор) и сценарий в `_everything`, который его создаёт; поля `cycle`, `level`, `reaction_due`, `solution_due`, `verdicts` в `ticket.closed`/`autoclosed` и их русские подписи | журнал самодостаточен |
| `backend/tests/test_sd_stand_restore.py:353-369` | проверяет сохранность `servicedesk:poll`, `servicedesk:formal`, `standcheck:keep` | **правка не нужна**; добавить проверкой удаление `sla:tick`, `servicedesk:sla:*`, `servicedesk:digest:*` (тест T-11112) | дополнительное покрытие |

## Решения Opus по задачам

1. **Цикл создаётся при создании заявки**, если уровень подобран; заявка без уровня цикла не имеет. Появление
   уровня до первого ответа создаёт цикл 1 (план, «Жизненный цикл `SlaCycle`»).
2. **Отчёт считает только текущий цикл** (`is_current=True`); прошлые циклы остаются в журнале (SPEC-011, 5б).
3. **Напоминание различимо по сроку**: ключ `SlaNotice` включает `deadline` и `due_at`; пересчёт срока даёт новое
   напоминание, старое не подавляет.
4. **Сводка** — `heads_of_unit` по узлу и предкам; `SlaDigest` уникален `(recipient, day)`; три раздела.
5. **Меню** — «Уровни обслуживания» order 6; «Отчёт по заявкам» order 7 (делит с «Базой знаний», вторичный
   ключ — название, поэтому «База знаний» раньше); «Сервис-деск» остаётся 65.
6. **Excel** — лист «Показатели» и лист «Заявки» до 20 000 строк без темы, текста, адреса и имени заявителя.
7. **Доля в срок по реакции** — только `True/False`; «закрыто без ответа» — отдельная строка отчёта.
8. **`due=overdue`** включает закрытую позже срока решения заявку.
9. **Ответственный уровня** применяется, если у категории нет своего; не участник очереди — журнал
   `ticket.assignee_skipped`, без назначения.
10. **Первый ответ** — `TicketEntry` вида `reply` в состоянии `queued`; `waiting_files` — после проверки файлов;
    `not_sent` и комментарии не считаются.
11. **`reopen` по письму** начинает цикл от `inbound.received_at`, по кнопке — от «сейчас».
12. **Ограничение периода** — 370 дней включительно, иначе ошибка поля и 400.
13. **`reaction_minutes <= solution_minutes`** — ограничение модели и форма.
14. **Снимок `schedule.days`** — точный JSON плана; при позднем факте даты дописываются, `extended=true`.
15. **У администратора 24 права из 25**: `servicedesk.reports` выдан роли «Руководитель», администратору — нет
    (SPEC-011, решение 10); тесты прав правятся по T-11010.

## Покрытие требований

| Требование | Задачи | Тесты |
|---|---|---|
| FR-730 | T-11002, T-11006, T-11202, T-11215 | `test_sd_sla_models`, `test_sd_sla_views` |
| FR-731 | T-11002, T-11202, T-11203 | `test_sd_sla_models`, `test_sd_sla_ticket` |
| FR-732 | T-11201, T-11202 | `test_sd_sla_deadlines`, `test_sd_sla_views` |
| FR-733 | T-11002, T-11202 | `test_sd_sla_models`, `test_sd_sla_ticket` |
| FR-734 | T-11201, T-11203 | `test_sd_sla_deadlines`, `test_sd_sla_ticket` |
| FR-735 | T-11201 | `test_sd_sla_deadlines` |
| FR-736 | T-11203 | `test_sd_sla_ticket` |
| FR-737 | T-11203 | `test_sd_sla_ticket` |
| FR-738 | T-11204 | `test_sd_sla_cycles` |
| FR-739 | T-11205 | `test_sd_sla_cycles` |
| FR-740 | T-11205 | `test_sd_sla_cycles` |
| FR-741 | T-11206 | `test_sd_sla_views` |
| FR-742 | T-11206 | `test_sd_sla_views` |
| FR-743 | T-11207, T-11212 | `test_sd_sla_notify`, `test_sd_sla_cron` |
| FR-744 | T-11211 | `test_sd_sla_notify`, `test_sd_sla_cron` |
| FR-745 | T-11207, T-11211 | `test_sd_sla_cron`, `test_sd_sla_notify` |
| FR-746 | T-11208, T-11216 | `test_sd_reports` |
| FR-747 | T-11208 | `test_sd_reports` |
| FR-748 | T-11209 | `test_sd_reports_excel` |
| FR-749 | T-11216 | `test_sd_reports` |
| FR-750 | T-11208 | `test_sd_reports` |
| FR-751 | T-11210 | `test_sd_answers`, `test_sd_sla_models` |
| FR-752 | T-11210, T-11002 | `test_sd_answers`, `test_sd_sla_models` |
| FR-753 | T-11217, T-11214 | `test_sd_answers`, `t11_05` |
| FR-754 | T-11210 | `test_sd_answers` |
| FR-755 | T-11202, T-11205, T-11209, T-11210, T-11215 | `test_sd_sla_audit`, `test_sd_sla_core_changes` |
| FR-756 | T-11003, T-11112, T-11010 | `test_sd_sla_core_changes`, `test_org_permissions` |
| FR-757 | T-11206, T-11214, T-11213 | `test_sd_sla_views`, `t11_06` |
| FR-758 | T-11214 | `test_sd_sla_audit`, `t11_06` |
| NFR-730 | T-11009, T-11303 | прогон нагрузки `ServiceDeskUser` |
| NFR-731 | T-11209 | `test_sd_reports_excel` |
| NFR-732 | T-11207, T-11211 | `test_sd_sla_cron`, `test_sd_sla_notify` |
| NFR-733 | T-11201 | `test_sd_sla_deadlines`, `test_sd_reports` |
| NFR-734 | T-11007, T-11207 | `test_sd_sla_cron` |
| NFR-735 | T-11208, T-11209, T-11216 | `test_sd_reports`, `test_sd_reports_excel` |
