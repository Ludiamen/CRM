---
id: TASKS-011
вид: задачи
статус: черновик
версия: 1
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
- **Нумерация.** Этап 1 — T-11001…T-11011, Этап 2 — T-11101…T-11112 плюс T-11150/T-11159/T-11160, Этап 3 —
  T-11201…T-11214 и T-11260, Этап 4 — T-11300…T-11308.
- **Порядок.** Этапы подряд. Внутри этапа задача без `[P]` начинается после предыдущих; `[P]` не зависит от
  соседей и не правит общие файлы.
- **Тест-на-требование.** В Этапе 2 у каждого теста в скобках FR/NFR; `файл::имя` — связь задача → требование →
  тест. Браузерные сценарии — `backend/tests/e2e/test_t11_*.py`.
- **Красный прежде зелёного.** Этап 3 не начинается до T-11160: тесты падают, причина записана.
- **Правки прежних тестов — одна задача T-11010** по точному «было / стало», с разрешения владельца.
- **Один автор на общий файл.** `apps/servicedesk/urls.py` — T-11006; `models.py` — T-11002; `config/cron.py` —
  T-11007; `extensions.py`, `stand.py` — T-11008; данные прав — T-11003; нагрузка — T-11009.
- **Размер.** Задача — не больше полудня одного исполнителя; задание агенту — не больше ~50 вызовов; файл
  тестов — не больше ~25 тестов (больше — `_2`).
- **Партии.** Этап 3 идёт партиями: сроки → уровни и поля → отчёт → шаблоны и уведомления; после каждой партии —
  весь серверный набор.
- **Вне перечня.** Если в Этапе 3 падает прежний тест вне таблицы T-11010 — остановка, решение Opus, запись в
  решения; тест не ослаблять.
- **Секреты.** В отчётах только `***`; ПДн и пароли в задачи не попадают.

## Этап 1 — каркас, контракт, данные, помощники, стенд

- [ ] T-11001 [arch] `CONTRACT-011`: маршруты уровней, отчёта, шаблонов, вставки (`?ticket=`), фильтр `due`,
  счётчики, зацепки `data-*`, коды и тексты отказов (`sla_title_range`, `sla_minutes_range`,
  `sla_reaction_gt_solution`, `sla_days_empty`, `sla_interval_empty`, `sla_assignee_dismissed`,
  `answer_title_range`, `answer_text_range`, `answer_category_personal`, `report_period_range`,
  `report_forbidden`), ответы HTMX и обычных запросов, подписи журнала — `backend/tests/CONTRACT-011.md` —
  (все FR)
- [ ] T-11002 [arch] модели и миграция `servicedesk 0004`: `SlaLevel`, `SlaBinding`, `AnswerTemplate`, `SlaCycle`,
  `SlaNotice`, `SlaDigest`, поля `Ticket` (`sla`, `sla_cycle_started_at`, `sla_reaction_due`,
  `sla_solution_due`, `sla_first_response_at`), `ServiceDeskSettings.sla_reminder_hours`; ограничения и индексы
  плана; `default_permissions = ()`, русские `verbose_name`; `manage.py check` — 0 —
  `backend/apps/servicedesk/models.py`, `backend/apps/servicedesk/migrations/0004_sla_answers.py` — (FR-730…745)
- [ ] T-11003 [P] [arch] права `servicedesk.sla`, `servicedesk.reports`, `servicedesk.answers` и начальные выдачи
  («Администратор портала» — sla+answers, «Руководитель» — reports), миграция `core 0016` от `0015`,
  идемпотентна — `backend/apps/core/migrations/0016_servicedesk_sla_permissions.py` — (FR-756)
- [ ] T-11004 [P] [arch] помощники серверных тестов: `PERMISSIONS_011`, `TITLES_011`, `KINDS_011`,
  `make_level`, `bind_level`, `make_answer`, `make_cycle`, `close_ticket`, `reopen_ticket`, `report_numbers`,
  `notice_rows`; без импорта кода приложения на уровне модуля — `backend/tests/support_servicedesk.py` —
  (все FR)
- [ ] T-11005 [P] [arch] помощники e2e и seed стенда: `open_sla`, `create_level`, `open_report`, `export_xlsx`,
  `insert_answer`, `check_360`; `e2e_sla_seed` (два уровня, привязки, три шаблона, заявки со сроками) —
  `backend/tests/e2e/helpers_sla.py`, `backend/apps/servicedesk/management/commands/e2e_sla_seed.py` —
  (FR-730…754)
- [ ] T-11006 [arch] маршруты, представления-заглушки, пункты меню «Уровни обслуживания» (order 6,
  `servicedesk.sla`) и «Отчёт по заявкам» (order 7, `servicedesk.reports`), подключение `answers.js` для
  `/servicedesk/answers/` и карточки — `backend/apps/servicedesk/urls.py`, `views/sla.py`, `views/reports.py`,
  `views/answers.py`, `extensions.py`, `backend/templates/_assets.html` — (FR-730…757)
- [ ] T-11007 [arch] задания-заглушки и записи cron: `sla_tick` (`*/5 * * * *`, 300) с замком `sla:tick`,
  `sla_digest` (`10 * * * *`, 300) в `maintenance` — `backend/apps/servicedesk/tasks.py`,
  `backend/config/cron.py` — (FR-743, FR-744, NFR-734)
- [ ] T-11008 [arch] стенд: `stand_reset` чистит `SlaCycle`, `SlaNotice`, `SlaDigest`, уровни, привязки,
  шаблоны, поля сроков у заявок, ключи `sla:tick`, `servicedesk:sla:*`, `servicedesk:digest:*`; порядок строк
  сохраняется — `backend/apps/servicedesk/stand.py` — (все FR)
- [ ] T-11009 [arch] нагрузка: `ServiceDeskUser` получает страницы `/servicedesk/reports/?period=week` и
  `/tickets/?due=overdue`, имена в `SD_PAGES`/`_check_sd_p95`; `fill_tickets.py` с `LOAD_TICKETS_SLA=1` создаёт
  уровни, привязки и сроки у 20 % заявок — `backend/tests/load/locustfile.py`,
  `backend/tests/load/fill_tickets.py` — (NFR-730)
- [ ] T-11010 [arch] правки прежних тестов по таблице «Правки прежних тестов» ниже — **только после разрешения
  владельца**, одной задачей, каждая строка «было / стало» — `backend/tests/…` — (FR-755, FR-756, NFR-734)
- [ ] T-11011 [arch] настройки сервис-деска: поле «Часы напоминания» 1–24 в форме и `INT_FIELDS`, служба
  настроек — `backend/apps/servicedesk/services/settings.py`, `views/settings.py`,
  `templates/servicedesk/settings/settings.html` — (FR-743, FR-756)

## Этап 2 — красные серверные тесты, браузер и стенд

- [ ] T-11101 [code] модели и ограничения: `default_permissions`, диапазоны, `reaction_minutes <=
  solution_minutes` отказ, уникальность привязок, `all_day OR day_start < day_end`, уникальность
  `(ticket, number)`, частичный текущий цикл — `test_sd_sla_models.py` (10) — (FR-730…733)
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
  суток, неизменность истории (уровень, календарь, передача, ответственный), 403 — `test_sd_reports.py` (15) —
  (FR-746…750, NFR-735)
- [ ] T-11109 [code] Excel: два листа, те же числа, 20 000 строк ≤ 10 с, нет темы/текста/адреса, чужие очереди
  отсутствуют, запись журнала — `test_sd_reports_excel.py` (8) — (FR-748, NFR-731)
- [ ] T-11110 [code] частые ответы: общие и личные, видимость, архив, категория у общего, вставка `?ticket=`,
  чужой личный и архивный 404 — `test_sd_answers.py` (10) — (FR-751…754)
- [ ] T-11111 [code] задания: обе записи в расписании, замок тика, перезапуск до/во время/после записи, сводка в
  окне `day_start`, один раз в день — `test_sd_sla_cron.py` (8) — (NFR-732, NFR-734)
- [ ] T-11112 [code] изменения ядра: права `core 0016` и выдачи, четыре пункта меню, метки, `stand_reset`,
  хвост `INSTALLED_APPS` не меняется — `test_sd_sla_core_changes.py` (7) — (FR-755, FR-756)
- [ ] T-11150 [code] браузерные сценарии `t11_01`…`t11_06` (уровень, сроки в заявке, просрочка, отчёт и Excel,
  шаблоны, 360 px) — `backend/tests/e2e/test_t11_*.py` — (FR-730…758)
- [ ] T-11159 [arch] обновление стенда образом среза (копия → сборка → миграции → службы) — **с разрешения
  владельца**; `/servicedesk/sla/` отвечает 302 — `crm-work/slice011/…` — (все FR)
- [ ] T-11160 [arch] красный серверный прогон: все новые тесты падают по назначению, артефакты не падают
  неожиданно; артефакты — `crm-work/slice011/stage2/` — (все FR)

## Этап 3 — реализация партиями

- [ ] T-11201 [code] служба сроков: интервалы дня по уровню и календарю, `deadline`, `minutes_between`, снимок
  `schedule.days`, расчёт рабочих минут — `services/sla.py` — (FR-734, FR-735, NFR-733)
- [ ] T-11202 [code] уровни и привязки: служба, формы, страницы, архив, права `servicedesk.sla` — `services/sla.py`,
  `views/sla.py`, шаблоны `sla/` — (FR-730…733, FR-756)
- [ ] T-11203 [code] применение уровня: создание заявки, `transfer` (категория/критичность/очередь), ответственный
  по умолчанию, пересчёт до первого ответа — `services/tickets.py`, `services/transfer.py`,
  `views/ticket_new.py` — (FR-734…737)
- [ ] T-11204 [code] первый ответ: факт и минуты реакции при `queued`-ответе, `waiting_files`, исключения —
  `services/replies.py` — (FR-738)
- [ ] T-11205 [code] закрытие и циклы: ручное и авто-закрытие, `reopen(at)`, вердикты, журнал с номером цикла —
  `services/closing.py`, `services/intake.py`, `audit_labels.py` — (FR-739, FR-740, FR-755)
- [ ] T-11206 [code] очередь и карточка: поле `due` в `Filters` и `_read`, колонка и сортировка по сроку,
  счётчики, блок `_sla.html` — `services/listing.py`, `views/tickets_list.py`, `views/ticket_card.py`,
  `templates/servicedesk/list/{_grid,page}.html`, `card/_sla.html`, `card/_card.html` — (FR-741, FR-742, FR-757)
- [ ] T-11207 [code] уведомления о сроках: виды, `heads_of_unit`, напоминание и просрочка через `SlaNotice` в
  одной транзакции, внешний текст — `notify_kinds.py`, `tasks.py`, `apps/org/services/structure.py` —
  (FR-743, NFR-732, NFR-734)
- [ ] T-11208 [code] отчёт: показатели, область `managed_units`, период ≤370 дней, страница — `services/reports.py`,
  `views/reports.py`, `templates/servicedesk/reports/page.html` — (FR-746…750, NFR-735)
- [ ] T-11209 [code] Excel: два листа, ограничение 20 000 строк, журнал — `services/reports.py`,
  `views/reports.py` — (FR-748, NFR-731)
- [ ] T-11210 [code] частые ответы: служба, страницы, архив, вставка `?ticket=` и `answers.js` —
  `services/answers.py`, `views/answers.py`, шаблоны `answers/`, `static/servicedesk/answers.js` —
  (FR-751…754)
- [ ] T-11211 [code] ежедневная сводка: окно `day_start`, `SlaDigest`, получатели, текст — `tasks.py` — (FR-744)
- [ ] T-11212 [code] настройки: поле часов напоминания в форме и службе — `services/settings.py`,
  `views/settings.py`, `templates/servicedesk/settings/settings.html` — (FR-743, FR-756)
- [ ] T-11213 [code] стенд и статика: `e2e_sla_seed`, `stand_reset`, подключение JS/CSS — `stand.py`, `extensions.py`,
  `templates/_assets.html` — (все FR, NFR-757)
- [ ] T-11214 [code] тексты и раскладка: русские подписи, Москва, 360 px — шаблоны `sla/`, `reports/`,
  `answers/`, `card/_sla.html` — (FR-757, FR-758)
- [ ] T-11260 [arch] полный зелёный серверный прогон после партий; сверка с красным T-11160 — артефакты
  `crm-work/slice011/stage3/` — (все FR)

## Этап 4 — приёмка

- [ ] T-11300 [arch] «Проверить после реализации»: набор прежних тестов сервис-деска, прав, меню, каталога
  уведомлений, cron, стенда — список и числа в отчёте — (регрессия)
- [ ] T-11301 [arch] браузерные круги `t11` в Chromium, Firefox, Edge, Яндекс.Браузере; прежние срезы — `-k` —
  `backend/tests/e2e/` — (NFR-730, NFR-757)
- [ ] T-11302 [arch] ворота `tools/verify.sh --быстро`, `manage.py check`, `git diff --check` — (конституция)
- [ ] T-11303 [arch] нагрузка NFR-730 на холодной машине по правилам T-7304: `fill_tickets.py` с SLA и класс
  `ServiceDeskUser` (страницы отчёта и `due=overdue`), L1 и L2; известные дефекты NFR-612/707 и стенд —
  `crm-work/slice011/stage4/load/` — (NFR-730)
- [ ] T-11304 [arch] наблюдения на стенде (с разрешения владельца): отказ слоя уведомлений при напоминании,
  повтор `sla_tick` после перезапуска, ночная уборка — (FR-743, NFR-732)
- [ ] T-11305 [человек] ручной проход: уровень → заявка со сроком → просрочка → отчёт и Excel → шаблоны; 360 px —
  (FR-730…758)
- [ ] T-11306 [arch] отчёт `docs/reviews/TASKS-011.md`: прохождение FR-730…758 и NFR-730…735, прогоны, ворота,
  известные ограничения — (все)
- [ ] T-11307 [arch] инварианты по диффу среза и правки прежних тестов сверить с T-11010 — (конституция)
- [ ] T-11308 [человек] приёмка среза и `git push` — (все)

## Правки прежних тестов (T-11010, нужно разрешение владельца)

| Файл и строка | Было | Станет | Почему |
|---|---|---|---|
| `backend/tests/test_permissions.py:42` | 22 права | 25 прав | три новых `servicedesk.*` |
| `backend/tests/test_org_permissions.py:140-153` | у «Руководителя» `staff.view`, `feed.post_all`; набор `set(titles)` | плюс `servicedesk.reports`; `set(titles)` из `PERMISSIONS_011` | начальная выдача (FR-756) |
| `backend/tests/test_sd_boundaries.py:472` | ровно 4 вида уведомлений | 7 видов | три новых вида |
| `backend/tests/test_sd_boundaries.py:481` | меню «Заявки», «Сервис-деск» | плюс «Уровни обслуживания», «Отчёт по заявкам» | пункты меню |
| `backend/tests/test_sd_audit.py:120-122` | у `ticket.closed`/`autoclosed` ровно `{"status"}`; точный набор кодов | плюс `cycle`, `level`, `reaction_due`, `solution_due`, `verdicts`; код `ticket.assignee_skipped` | журнал самодостаточен |
| `backend/tests/test_kb_deploy.py:134`, `test_lists_deploy.py:169`, `test_feed_deploy.py:245`, `test_messenger_deploy.py:340`, `test_notify_deploy.py:321`, `test_tasks_deploy.py:243`, `test_instructions_deploy.py:188`, `test_sd_deploy.py:424` | `len(...) == 27` записей cron | 29 записей | `sla_tick`, `sla_digest` |
| `backend/tests/test_sd_stand_restore.py` | сброс чистит только `servicedesk:form:*` | плюс `sla:tick`, `servicedesk:sla:*`, `servicedesk:digest:*` и новые таблицы | `stand_reset` |
| `backend/tests/support_servicedesk.py` | константы прав и видов | `PERMISSIONS_011`, `TITLES_011`, `KINDS_011` | общие помощники |

## Решения Opus по задачам

1. **Цикл создаётся при создании заявки**, если уровень подобран; заявка без уровня цикла не имеет. Появление
   уровня до первого ответа создаёт цикл 1 (план, «Жизненный цикл `SlaCycle`»).
2. **Отчёт считает только текущий цикл** (`is_current=True`); прошлые циклы остаются в журнале (SPEC-011, 5б).
3. **Напоминание различимо по сроку**: ключ `SlaNotice` включает `deadline` и `due_at`; пересчёт срока даёт новое
   напоминание, старое не подавляет.
4. **Сводка** получателям — `heads_of_unit` по узлу и предкам; в `SlaDigest` уникальность `(recipient, day)`.
5. **Меню** — order 6 и 7 (после «Заявок» с order 5 и до «Сервис-деска» с 65).
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

## Покрытие требований

| Требование | Задачи | Тесты |
|---|---|---|
| FR-730 | T-11002, T-11006, T-11202 | `test_sd_sla_models`, `test_sd_sla_views` |
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
| FR-743 | T-11011, T-11207 | `test_sd_sla_notify`, `test_sd_sla_cron` |
| FR-744 | T-11211 | `test_sd_sla_notify`, `test_sd_sla_cron` |
| FR-745 | T-11205, T-11207 | `test_sd_sla_cycles`, `test_sd_sla_cron` |
| FR-746 | T-11208 | `test_sd_reports` |
| FR-747 | T-11208 | `test_sd_reports` |
| FR-748 | T-11209 | `test_sd_reports_excel` |
| FR-749 | T-11208 | `test_sd_reports` |
| FR-750 | T-11208 | `test_sd_reports` |
| FR-751 | T-11210 | `test_sd_answers` |
| FR-752 | T-11210 | `test_sd_answers` |
| FR-753 | T-11210, T-11214 | `test_sd_answers`, `t11_05` |
| FR-754 | T-11210 | `test_sd_answers` |
| FR-755 | T-11003, T-11205, T-11202 | `test_sd_sla_audit`, `test_sd_sla_core_changes` |
| FR-756 | T-11003, T-11011, T-11212 | `test_sd_sla_core_changes`, `test_org_permissions` |
| FR-757 | T-11206, T-11213 | `test_sd_sla_views`, `t11_06` |
| FR-758 | T-11214 | `test_sd_sla_audit`, `t11_06` |
| NFR-730 | T-11009, T-11303 | прогон нагрузки `ServiceDeskUser` |
| NFR-731 | T-11209 | `test_sd_reports_excel` |
| NFR-732 | T-11207, T-11211 | `test_sd_sla_cron`, `test_sd_sla_notify` |
| NFR-733 | T-11201 | `test_sd_sla_deadlines`, `test_sd_reports` |
| NFR-734 | T-11007, T-11207 | `test_sd_sla_cron` |
| NFR-735 | T-11208 | `test_sd_reports` |
