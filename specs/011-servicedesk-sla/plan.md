---
id: PLAN-011
вид: план
статус: черновик
версия: 5
зависит_от: SPEC-011, CONST, ADR-0002, ADR-0004, ADR-0008, ADR-0019, REF-CAP, REF-UX, REF-SRC, TGT-ARCH, TGT-NFR, SPEC-002, SPEC-003, SPEC-004, SPEC-009, SPEC-010
основан_на: SPEC-011 sha256:acf75cf54d0ed1c79db2313aba47d7fb6c2cebb4123e8d43c7b5d98de570af8b
---

# План среза 011: Сроки и отчёты заявок

## Сверка с конституцией

- **модуль-приложение** — новых приложений нет: срез расширяет `apps.servicedesk`; связи с ядром — через
  существующие точки `menu_items`, `notification_kinds`, `audit_labels`, `stand_reset`; календарь — через
  `apps.org.services.calendar`, уведомления — через `apps.notify.services.dispatch`.
- **настройка-без-кода** — уровни, привязки, расписание, шаблоны, права, часы напоминания — данные.
- **пдн-152фз** — во внешние каналы только событие и ссылка; в Excel нет темы, текста и адреса заявителя.
- **sql-только-параметры** — отчёт, фильтры и выборки — параметрами; ключи фильтров и периодов — из белого списка.
- **аудит-изменений** — журнал только дополняется, записи уровней и шаблонов — с автором и временем.
- **стек-интерфейс** — HTMX и один небольшой свой `answers.js` (подстановка текста в `textarea`), сторонних
  библиотек нет; Excel — серверный `openpyxl`.
- **стек-бэкенд** — Django 5.2, PostgreSQL, RQ-задания в `maintenance`; новых пакетов нет.
- **эталон-не-копия** — сроки и уровни из эталона, расчёт по рабочему календарю, второй срок и отчёт — решения
  SPEC-011.

## Технический контекст

### Новые компоненты и лицензии

Новых пакетов нет: `openpyxl==3.1.5` уже в `requirements.txt`. Новых сторонних JS нет; `static/servicedesk/answers.js`
— свой файл без зависимостей.

### Где живёт код

```
backend/apps/servicedesk/
  models.py                 + SlaLevel, SlaBinding, AnswerTemplate, SlaCycle, SlaNotice, SlaDigest;
                              поля сроков в Ticket; sla_reminder_hours в ServiceDeskSettings
  migrations/0004_sla_answers.py
  services/sla.py           интервалы дня, расчёт сроков и рабочих минут, применение уровня, циклы, вердикты
  services/answers.py       общие и личные шаблоны, видимость, архивирование, вставка
  services/reports.py       показатели и выгрузка xlsx
  services/settings.py      + sla_reminder_hours (1–24)
  services/listing.py       + колонка и фильтр срока, сортировка по сроку, свои очереди руководителя
  services/transfer.py      + пересчёт уровня и сроков при смене категории/критичности/очереди
  services/replies.py       + факт первого ответа и запись рабочих минут реакции
  services/closing.py       + закрытие и автозакрытие пишут цикл и вердикты; reopen закрывает цикл
  services/tickets.py       + применение уровня при создании и назначение ответственного уровня
  tasks.py                  + sla_tick, sla_digest
  notify_kinds.py           + servicedesk.sla_due_soon, sla_overdue, sla_digest
  audit_labels.py           + метки уровней, шаблонов, выгрузки
  extensions.py             + пункты меню «Уровни обслуживания», «Отчёт по заявкам»
  urls.py                   + маршруты уровней, отчёта и шаблонов
  views/sla.py, views/reports.py, views/answers.py   (новые)
  views/tickets_list.py     + разбор `due` в Filters и счётчики срока
  views/ticket_card.py      + блок сроков и выбор шаблона в форме ответа, пересчёт при правке полей
  views/settings.py         + поле «часы напоминания» в INT_FIELDS
backend/apps/org/services/structure.py   + heads_of_unit(unit_id) — руководитель и заместитель узла и его предков
backend/apps/org/services/calendar.py    используется как есть (day_kind, WorkCalendar.day_start/day_end)
backend/templates/servicedesk/
  sla/{page,_list,_form}.html, reports/page.html, answers/{page,_list,_form}.html,
  card/_sla.html (включается из card/_card.html), list/_grid.html (колонка срока),
  list/page.html (фильтр `due`), settings/settings.html (часы напоминания)
backend/static/servicedesk/answers.js
backend/tests/test_sd_sla_*.py, test_sd_reports_*.py, test_sd_answers_*.py, tests/e2e/test_t11_*.py
```

### Изменения ядра и прежних модулей

| Файл | Изменение | Зачем |
|---|---|---|
| данные установки `core 0016` | права `servicedesk.sla`, `servicedesk.reports`, `servicedesk.answers`; «Администратор портала» — sla и answers, роль «Руководитель» — reports; идемпотентно | FR-756 |
| `apps/servicedesk/models.py` + `servicedesk 0004` | пять моделей и поля сроков в `Ticket`; `sla_reminder_hours` в настройках (одно поле) | FR-730…745 |
| `apps/servicedesk/services/settings.py` | `sla_reminder_hours` 1–24, по умолчанию 1 | FR-743 |
| `apps/servicedesk/services/listing.py` | колонка «Срок», сортировка `due`, фильтр `due` | FR-741 |
| `apps/servicedesk/services/tickets.py` | применение уровня при создании, ответственный уровня (приоритет категории) | FR-734, 731 |
| `apps/servicedesk/services/transfer.py` | пересчёт сроков при смене категории/критичности/очереди (не только `tickets.update_fields`) | FR-736 |
| `apps/servicedesk/services/replies.py` | факт первого ответа и минуты реакции в `SlaCycle` | FR-738 |
| `apps/servicedesk/services/closing.py` | цикл и вердикты при закрытии и автозакрытии; `reopen(at)` закрывает цикл; журнал `ticket.assignee_skipped` | FR-739, 740 |
| `apps/org/services/structure.py` | `heads_of_unit` — руководители и заместители узла и предков | FR-743/744 |
| `apps/servicedesk/views/tickets_list.py` | поле `due` в `Filters`, разбор `?due=overdue|today`, счётчики срока в `count` | FR-741 |
| `apps/servicedesk/views/settings.py` | `sla_reminder_hours` в `INT_FIELDS` | FR-756 |
| `apps/servicedesk/views/ticket_card.py` | блок `_sla.html`, форма ответа с шаблонами, пересчёт при правке полей | FR-742, 753 |
| `templates/servicedesk/list/_grid.html`, `list/page.html`, `card/_card.html`, `settings/settings.html` | колонка, фильтр, включение блока, поле часов | FR-741/742/756 |
| `apps/servicedesk/extensions.py` | пункты меню «Уровни обслуживания» (order 6, `servicedesk.sla`), «Отчёт по заявкам» (order 7, `servicedesk.reports`) | навигация |
| `config/cron.py` | `servicedesk_sla_tick` (`*/5`, 300) и `servicedesk_sla_digest` (`10 * * * *`, 300) в `maintenance` | FR-743/744 |
| `apps/servicedesk/stand.py` | сброс новых таблиц (`SlaCycle`, `SlaNotice`, `SlaDigest`, уровни, шаблоны), полей сроков у заявок, ключей `sla:tick`, `servicedesk:sla:*`, `servicedesk:digest:*` | стенд |
| `templates/_assets.html` | `answers.js` для `/servicedesk/answers/` и карточки заявки | вставка шаблона |

`role_sources` не регистрируется: права — данные. Nginx не меняется: файлов у среза нет.

### Запуск

Новых служб нет. Миграции: `core 0016` от `0015`, `servicedesk 0004` от `0003` и `core 0016`. Данных установки в
`servicedesk` нет (уровни и шаблоны не создаются), поэтому второй миграции не нужно. Очередь `maintenance` читает
только служба `worker-mail` — задания `sla_tick` и `sla_digest` пойдут последовательно с напоминаниями задач и
поручений; `sla_tick` перед работой берёт замок `sla:tick` (Valkey, TTL 4 минуты), чтобы тики не наложились.

## Модель данных

### Приложение `servicedesk` (миграция 0004)

Все новые модели — `default_permissions = ()`, русские `verbose_name`; сроки и числа — целые минуты.

| Модель / поле | Поля | Индексы и ограничения |
|---|---|---|
| `SlaLevel` | `title` 100, `priority` 0–99, `reaction_minutes` 5…43 200, `solution_minutes` 5…43 200, `workdays` JSON (0–6, по умолчанию `[0,1,2,3,4]`), `day_start` 09:00, `day_end` 18:00, `all_day` bool, `default_assignee` FK `core.User` PROTECT пусто, `archived` bool, `created_at`, `updated_at` | `CheckConstraint`: минуты в диапазоне, `reaction_minutes <= solution_minutes`, дни — подмножество 0–6, `all_day OR day_start < day_end`; форма не даёт пустой набор дней и пустой интервал; индекс `(archived, priority)` |
| `SlaBinding` | `level` CASCADE, `kind` (`category`/`priority`), `category` PROTECT пусто, `priority` PROTECT пусто | `CheckConstraint`: ровно одно поле по `kind`; частичные уникальные `(category)` и `(priority)` |
| `AnswerTemplate` | `owner` FK `core.User` CASCADE пусто (пусто — общий), `title` 100, `text` 10 000, `category` PROTECT пусто (только у общего), `archived`, `created_at`, `updated_at` | индексы `(owner, archived)`, `(category)`; `CheckConstraint`: личный шаблон без категории |
| `SlaCycle` | `ticket` CASCADE (related `sla_cycles`), `number` (номер цикла в заявке, с 1), `is_current` bool (истина у одного цикла из `sla_cycles`), `level` FK SET_NULL пусто, `level_title` 100 (снимок), `queue` FK `org.Unit` SET_NULL пусто, `queue_name` 255 (снимок), `category` FK SET_NULL пусто, `category_name` 255 (снимок), `assignee` FK `core.User` SET_NULL пусто, `assignee_name` 255 (снимок: исполнитель на момент закрытия), `schedule` JSON (снимок расписания), `cycle_started_at`, `reaction_due`, `solution_due`, `first_response_at` пусто, `reaction_minutes` пусто, `closed_at` пусто, `solution_minutes` пусто, `closed_kind` (`manual`/`autoclosed`) пусто, `reaction_met` bool пусто, `solution_met` bool пусто, `created_at` | уникальность `(ticket, number)` и `(ticket, cycle_started_at)`; частичный уникальный `(ticket)` при `is_current`; индексы `(closed_at)`, `(cycle_started_at)`, `(level)`, `(queue)`, `(category)` и частичный `(ticket)` при `is_current` и `solution_met = False` |
| `SlaNotice` | `cycle` CASCADE, `deadline` (`reaction`/`solution`), `kind` (`due_soon`/`overdue`), `due_at` (срок, к которому относится напоминание), `recipient` FK `core.User` CASCADE, `sent_at` | уникальность `(cycle, deadline, kind, due_at, recipient)` — пересчёт срока даёт новый ключ |
| `SlaDigest` | `recipient` FK `core.User` CASCADE, `day` дата, `units` JSON (очереди в сводке), `sent_at` | уникальность `(recipient, day)` |
| `Ticket` + | `sla` FK `SlaLevel` SET_NULL пусто, `sla_cycle_started_at`, `sla_reaction_due`, `sla_solution_due`, `sla_first_response_at` — пусто | частичные индексы `(sla_reaction_due)` и `(sla_solution_due)` при `kind != 'closed'` |
| `ServiceDeskSettings` + | `sla_reminder_hours` 1–24 часов, по умолчанию 1 | `CheckConstraint` 1–24 |

Жизненный цикл `SlaCycle` определён так:

1. **Создание заявки.** Есть уровень — создаётся цикл с `number=1`, `is_current=True`; снимки `queue`,
   `category`, `level_title` и `schedule` берутся в этот момент. Уровня нет — нет и цикла, и полей сроков.
2. **Первый ответ.** В текущем цикле пишутся `first_response_at`, `reaction_minutes`, `reaction_met` — один раз,
   по снимку `schedule`.
3. **Закрытие (ручное или авто).** В цикл пишутся `closed_at`, `solution_minutes`, `solution_met`, `closed_kind`,
   `assignee`/`assignee_name` (на кого закрыта заявка — знаменатель «нагрузки»). `is_current` остаётся истиной.
4. **Открытие заново.** `closing.reopen` получает параметр `at` — время ответа заявителя (для письма —
   `inbound.received_at`, `intake.py` передаёт его явно), иначе «сейчас». У прошлого цикла `is_current=False`;
   создаётся новый цикл `number+1` с `is_current=True`,
   новым снимком `queue`/`category`/`schedule` и новыми сроками от `at`. Прошлый цикл не удаляется и в отчёт не
   попадает — он виден в журнале.

Так у каждого цикла ровно один текущий (частичная уникальность `(ticket)` при `is_current`). Снимок `schedule`
цикла — строго такой JSON:

```json
{"workdays": [0, 1, 2, 3, 4],
 "day_start": "09:00",
 "day_end": "18:00",
 "all_day": false,
 "days": {"2026-11-24": "workday", "2026-11-25": "short"},
 "extended": false}
```

`days` — карта «дата → вид дня» на диапазон от начала цикла до `max(reaction_due, solution_due)`; значения — `work`,
`off` (по рабочим дням недели) плюс виды переносов календаря `holiday`, `day_off`, `workday`, `short`
(`org.SpecialDay.Kind`). Если факт выходит за диапазон (позднее закрытие), недостающие даты дописываются в `days`
в момент факта и ставится `extended: true`; минуты считаются по ним, уже посчитанные числа не пересчитываются.
Ограничение уровня: `reaction_minutes <= solution_minutes` (иначе форма не сохраняет). Записи `ticket.closed` / `ticket.autoclosed`
дополняются номером цикла и вердиктами, чтобы журнал был самодостаточен.

### Правило рабочих часов (FR-734/735, NFR-733)

Интервал дня для даты `D` и уровня `L`:

1. `D.weekday()` входит в `L.workdays`; иначе день нерабочий.
2. `calendar.day_kind(D)` не из `off`, `holiday`, `day_off`; иначе день нерабочий (праздник календаря сильнее
   уровня — так решает пункт «нерабочие дни — календарь» SPEC-011).
3. `start = max(L.day_start, calendar.day_start)`, `end = min(L.day_end, calendar.day_end)`; для `short`
   `end = min(L.day_end, calendar.day_end − 1 час)` — час снимается с конца рабочего дня календаря, а не с
   интервала уровня (уровень 09:00–12:00 на сокращённом дне остаётся 09:00–12:00). Для `all_day` интервал —
   все 24 часа рабочего дня (поля `day_start`/`day_end` не используются), праздники календаря по-прежнему
   пропускаются. Если `start ≥ end`, день пропускается.
4. `deadline(start, minutes)` идёт по дням вперёд, пока не израсходует минуты; `minutes_between(a, b)` считает
   израсходованные рабочие минуты так же. Обе функции чистые и принимают снимок расписания (`schedule`) и
   функцию вида дня — в тестах подменяются календарём-фикстурой.

Эррата SPEC-011: в сценарии 1 было «17:50 + 30 минут → 09:30», а по правилу выходит **09:20** (10 минут до 18:00
и 20 минут утром). Владелец 2026-11-24 велел поправить пример на 09:20 и переподписать спеку — SPEC-011 v5,
пример исправлен, план основан на 09:20.

### Применение уровня и ответственный по умолчанию

- Уровень выбирается по критичности, затем по категории (конфликт — критичность, SPEC-011). Ответственный по
  умолчанию уровня назначается, только если у категории нет своего `default_assignee`; при создании и смене
  полей проверяется участие сотрудника в очереди заявки — не участник: поле игнорируется, в журнал пишется
  `ticket.assignee_skipped` (метка и подписи полей — в `audit_labels`, в интерфейсе не показывается).
- Смена категории, критичности или очереди проходит через `services/transfer.py` (там же, где сейчас меняется
  категория). Пока нет первого ответа, пересчёт обновляет и `Ticket`, и текущий `SlaCycle`: `level`,
  `level_title`, `queue`/`queue_name`, `category`/`category_name`, `schedule` и оба срока от начала цикла. Если
  цикла ещё не было (заявка создана без уровня), а уровень появился — создаётся цикл `number=1`, `is_current=True`
  с теми же снимками и сроками. После первого ответа пересчёта нет.

## Контракты

### Уровни обслуживания (FR-730…737, 755, 756, 757)

| Маршрут | Право | Ответ |
|---|---|---|
| `GET /servicedesk/sla/` | `servicedesk.sla` | список уровней с привязками и архивом |
| `GET/POST /servicedesk/sla/new/` | `servicedesk.sla` | форма; ошибки у полей, 400 |
| `GET/POST /servicedesk/sla/<pk>/` | `servicedesk.sla` | форма правки и привязок |
| `POST /servicedesk/sla/<pk>/archive/` | `servicedesk.sla` | архив и возврат (HTMX-строка) |

### Очередь и карточка (FR-738…742)

| Маршрут | Право | Ответ |
|---|---|---|
| `GET /tickets/?due=overdue` | `access.menu_visible` + существующий пресет | просроченные: реакция прошла без ответа, решение прошло без закрытия **или заявка закрыта позже срока решения** |
| `GET /tickets/?due=today` | то же | ближайший активный срок (реакция, если ответа нет, иначе решение) — сегодня по Москве |
| `GET /tickets/count/?due=…` | то же | число для фильтра рядом с существующими счётчиками |
| `GET /tickets/<number>/` | доступ к заявке | блок `_sla.html`: уровень, оба срока, факты, вердикты, «срок не задан» |

`due` — поле `Filters` и разбор в `_read`; сочетается с пресетами `mine`/`my_queues`/`closed`; неизвестное
значение — как пустое (действующее правило списка).

### Отчёт (FR-746…750, NFR-731, NFR-735)

| Маршрут | Право | Ответ |
|---|---|---|
| `GET /servicedesk/reports/?period=day|week|month|custom&from=&to=&queue=&sla=&category=&assignee=` | `servicedesk.reports` | страница отчёта |
| `GET /servicedesk/reports/export/…` | `servicedesk.reports` | xlsx, имя `tickets-YYYY-MM-DD.xlsx`, журнал `servicedesk.report_exported` |

Область — `managed_units` пользователя (очереди узлов и вложенных); администратор без отметки — 403. Период:
`day/week/month` считаются по Москве, `custom` — от `from` до `to` включительно; больше 370 дней — ошибка поля и
400. Отчёт считает **только текущий цикл** заявки (`is_current=True`): после открытия заново прошлый цикл
остаётся в журнале и в отчёт не попадает (SPEC-011, 5б). Создано — по `Ticket.created_at`, закрыто — по
`SlaCycle.closed_at` текущего цикла; фильтры очереди, категории и исполнителя и нагрузка — по снимкам цикла
(`queue`/`queue_name`, `category`/`category_name`, `assignee_name`), поэтому история не меняется после передачи
заявки или смены ответственного; средние — из готовых `reaction_minutes` и `solution_minutes`. Доля в срок по
реакции — `reaction_met=True` к сумме `reaction_met=True/False`; заявки, закрытые без первого ответа
(`reaction_met IS NULL`), в знаменатель не входят и показываются отдельной строкой «закрыто без ответа». Доля в
срок по решению — `solution_met=True` к сумме `True/False` закрытых циклов. Просрочки по уровням — по
`level_title`; нагрузка — «закрыто на исполнителя» по `assignee_name`. Показатель «оценка заявителей» —
колонка без значений (CAP-35 вне среза).

Excel: лист **«Показатели»** — те же числа и период; лист **«Заявки»** — до 20 000 строк цикла: номер, создана,
закрыта, очередь, уровень, срок реакции и факт, срок решения и факт, вердикты, вид закрытия, исполнитель.
Темы, текста, адреса и имени заявителя в файле нет.

### Частые ответы (FR-751…754)

| Маршрут | Право | Ответ |
|---|---|---|
| `GET /servicedesk/answers/` | `access.menu_visible` | видимые личные и общие шаблоны |
| `GET/POST /servicedesk/answers/new/` | та же; общий — ещё `servicedesk.answers` | форма |
| `GET/POST /servicedesk/answers/<pk>/edit/` | владелец личного или `servicedesk.answers` | форма правки |
| `POST /servicedesk/answers/<pk>/archive/` | то же | архив/возврат |
| `GET /servicedesk/answers/<pk>/insert/?ticket=<number>` | доступ к заявке (`access.can_work`) и видимость шаблона | HTMX-фрагмент с текстом для подстановки |

Личный шаблон виден владельцу, общий — держателю `servicedesk.answers` и участникам сервис-деска; архивный
шаблон и чужой личный — 404.

### Уведомления и задания (FR-743…745, NFR-732, NFR-734)

Три вида: `servicedesk.sla_due_soon` (order 230), `servicedesk.sla_overdue` (231), `servicedesk.sla_digest` (232).
Получатели: ответственный; руководитель очереди — новая функция `structure.heads_of_unit(unit_id)` — отметки
руководителя и заместителя самого узла и всех его предков (руководитель ИТ-отдела получает и по вложенным
очередям), без повторов. Напоминание за `sla_reminder_hours` рабочих часов до срока и отметка просрочки
создают `SlaNotice` (с ключом срока: `reaction`/`solution`) и уведомление в одной транзакции; повторный тик
видит строку и молчит. Сводка: `sla_digest` идущий каждый час (`10 * * * *`), но отправляется только в рабочем
дне и в первый час после `WorkCalendar.day_start`; получатели — `heads_of_unit` по всем доступным очередям,
повтор в тот же день отсекает `SlaDigest` уникальностью `(recipient, day)`.

## Интеграции

- **Календарь (SPEC-002)** — `org.services.calendar`: `day_kind`, `WorkCalendar.day_start/day_end`, `day_kind`
  учитывает особые дни; правило пересечения — выше. Своих календарей у уровня нет.
- **Уведомления (SPEC-004)** — `notify.services.dispatch`; тихие часы и каналы — настройки сотрудника; внешние
  каналы получают только событие и ссылку.
- **Почта и файлы** — без изменений; факт реакции фиксируется в `services/replies.py` при `queued`-ответе.
- **Внешние системы** (Telegram/MAX/Zabbix/АСДОБ) — новых вызовов нет.

## Проверка

### Серверные тесты

| Файл | Что закрывает |
|---|---|
| `test_sd_sla_models.py` | модели, `default_permissions`, ограничения, уникальность привязок, архив (FR-730…733) |
| `test_sd_sla_deadlines.py` | правило интервала: суббота уровня при выходном календаре, `short` (уровень 09–12 остаётся 09–12), праздник, `all_day`, 28.02/29.02/01.03, вечер пятницы; `minutes_between` (FR-734/735, NFR-733) |
| `test_sd_sla_ticket.py` | подбор по критичности/категории, снимок, пересчёт до первого ответа, ответственный уровня и конфликт с категорией, заявка без уровня (FR-734…737) |
| `test_sd_sla_cycles.py` | первый ответ (`queued`, `waiting_files`, `not_sent`, комментарий), ручное и авто-закрытие, открытие заново, `is_current` (старый цикл не текущий), уникальность `(ticket, number)`, вердикты (FR-738…740) |
| `test_sd_sla_views.py` | уровни, `due=overdue` (в том числе закрытая позже срока) и `due=today` с пресетами, счётчики, блок карточки, права и 403 (FR-730…742, 757) |
| `test_sd_sla_audit.py` | журнал: уровень, привязки, шаблон, выгрузка и `ticket.assignee_skipped` — с автором, временем и подписями полей; русский/Москва на страницах (FR-755, 758) |
| `test_sd_sla_notify.py` | три вида, получатели (ответственный, `heads_of_unit` включая предков), отдельные напоминания по реакции и решению, границы 1/24/25 часов, опережение, без повторов, внешний текст без темы (FR-743/744, NFR-732/734) |
| `test_sd_reports.py` | показатели за период, только текущий цикл (после reopen прошлый не считается), фильтры и нагрузка по снимкам, знаменатель доли в срок без «закрыто без ответа», область `managed_units`, 370/371 день, границы суток по Москве, неизменность истории после правки уровня, календаря, передачи заявки и смены ответственного, пустой отчёт, оценка пуста, 403 (FR-746…750, NFR-735) |
| `test_sd_reports_excel.py` | два листа, те же числа, 20 000 строк ≤ 10 с, нет темы/текста/адреса, чужие очереди отсутствуют, журнал (FR-748, NFR-731) |
| `test_sd_answers.py` | общие/личные, видимость, архив, категория у общего, вставка `?ticket=`, чужой личный 404 (FR-751…754) |
| `test_sd_sla_cron.py` | обе записи в расписании, замок тика, повтор после перезапуска до/во время/после записи, сводка в окне `day_start`, один раз в день (NFR-732/734) |
| `test_sd_sla_core_changes.py` | права `core 0016` и выдачи, меню (4 пункта), метки журнала, `stand_reset` с ключами `sla`/`digest`, хвост `INSTALLED_APPS` не меняется |

### Браузер (Playwright, `t11`)

`t11_01` — уровень и привязки; `t11_02` — сроки в заявке и блок карточки; `t11_03` — просрочка, `due` и счётчик;
`t11_04` — отчёт и Excel; `t11_05` — вставка общего и личного шаблона; `t11_06` — 360 px и русский/Москва.
Данные браузерных сценариев — стенд-фикстуры среза (свой seed), не `fill_tickets.py`.

### Нагрузка (NFR-730)

Профиль `ServiceDeskUser` расширяется: страница отчёта `?period=week` и `?due=overdue`, имена добавляются в
`SD_PAGES` и `_check_sd_p95`. `fill_tickets.py` получает `LOAD_TICKETS_SLA=1`: уровни, привязки и сроки у 20 %
заявок, чтобы отчёт и просрочка измерялись на живых данных. Прогон — по правилам T-7304 (холодная машина,
`systemd-run --user`, порог 2,5). 500 мс NFR-730 относятся к страницам и фрагментам, не к выгрузке (у неё
NFR-731 — 10 с).

### Ворота

`tools/verify.sh --быстро`, `manage.py check`, `git diff --check`; красный серверный прогон до реализации и
зелёный полный — по правилу среза.

## Правки прежних тестов (нужно разрешение владельца)

| Файл и строка | Было | Станет | Почему |
|---|---|---|---|
| `tests/test_permissions.py:42` | 22 права | 25 прав | три новых `servicedesk.*` |
| `tests/test_org_permissions.py:140-153` | у «Руководителя» ровно `staff.view`, `feed.post_all`; `set(titles)` и набор администратора | плюс `servicedesk.reports`; `set(titles)` собран из `PERMISSIONS_011` | начальная выдача (FR-756) |
| `tests/test_sd_boundaries.py:472` | ровно 4 вида уведомлений | 7 видов | три новых вида |
| `tests/test_sd_boundaries.py:481` | меню «Заявки», «Сервис-деск» | плюс «Уровни обслуживания», «Отчёт по заявкам» | пункты меню |
| `tests/test_sd_audit.py:120-122` | у `ticket.closed`/`ticket.autoclosed` ровно `{"status"}`; точный набор кодов меток | плюс `cycle`, `level`, `reaction_due`, `solution_due`, `verdicts` и код `ticket.assignee_skipped` | журнал самодостаточен (Б3) |
| `tests/test_sd_deploy.py:424` | `len(...) == 27` записей cron | 29 записей | восьмой deploy-тест, тоже считает cron |
| `apps/servicedesk/audit_labels.py` `FIELDS` | нет подписей новых полей | подписи `cycle`, `level`, `reaction_due`, `solution_due`, `verdicts` | журнал показывает поля по-русски |
| `tests/test_kb_deploy.py:134`, `test_lists_deploy.py:169`, `test_feed_deploy.py:245`, `test_messenger_deploy.py:340`, `test_notify_deploy.py:321`, `test_tasks_deploy.py:243`, `test_instructions_deploy.py:188` | `len(...) == 27` записей cron | 29 записей | `sla_tick`, `sla_digest` |
| `tests/test_sd_stand_restore.py` | сброс чистит только `servicedesk:form:*` | плюс `servicedesk:sla:*`, `servicedesk:digest:*` и новые таблицы | `stand_reset` |
| `tests/support_servicedesk.py` | константы прав и видов | `PERMISSIONS_011`, `TITLES_011`, `KINDS_011` | общие помощники тестов |

Правки — отдельной задачей после разрешения; до него прежние тесты красные только в перечисленных местах.

## Риски

1. **Расчёт рабочих часов на границах** — вероятность средняя. Что делаем: правило интервала из четырёх шагов,
   таблица границ (вечер пятницы, `short`, праздник, суббота уровня, 29 февраля), сверка с `org.calendar`.
2. **История средних «плывёт»** — вероятность средняя. Что делаем: минуты и вердикты пишутся в `SlaCycle` один
   раз, отчёт читает готовые числа; тест «правка уровня и календаря не меняет прошлые средние».
3. **Открытие заново теряет вердикты** — вероятность средняя. Что делаем: старый `SlaCycle` не удаляется, журнал
   получает номер цикла и вердикты; тест закрытия с просрочкой и reopen.
4. **Отчёт медленный на 110 тыс. заявок** — вероятность средняя. Что делаем: агрегаты по индексам
   `(closed_at)`, `(cycle_started_at)`, `(level)`; `EXPLAIN` в тесте; запасной ход — кэш страницы на 60 с.
5. **Дубли напоминаний и сводки** — вероятность средняя. Что делаем: `SlaNotice` и `SlaDigest` с уникальностью
   в БД, замок тика, тест перезапуска.
6. **Область отчёта шире замысла** — вероятность средняя. Что делаем: `managed_units` строго, 403 администратору
   без отметки, тест «участник очереди не видит свою очередь в отчёте».
7. **Ответственный по умолчанию уровня** — вероятность низкая. Что делаем: приоритет категории, проверка
   участия в очереди, событие `assignee_skipped`, тест на неучастника.
8. **Совпадение тиков в единственном `maintenance`-воркере** — вероятность средняя. Что делаем: замок
   `sla:tick` TTL 4 минуты, порционные выборки по индексу срока, `job_timeout=300`.
9. **Ломаются прежние тесты прав, видов, меню, cron и стенда** — вероятность высокая. Что делаем: таблица правок
   выше, отдельная задача с разрешения владельца, `PERMISSIONS_011` в помощниках.
10. **Шаблон виден не тому** — вероятность низкая. Что делаем: видимость в службе, 404 на чужой личный и
   архивный, проверка `access.can_work` в маршруте вставки.
