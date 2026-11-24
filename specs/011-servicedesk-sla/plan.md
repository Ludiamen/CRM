---
id: PLAN-011
вид: план
статус: черновик
версия: 1
зависит_от: SPEC-011, CONST, ADR-0002, ADR-0004, ADR-0008, ADR-0019, REF-CAP, REF-UX, REF-SRC, TGT-ARCH, TGT-NFR, SPEC-002, SPEC-003, SPEC-004, SPEC-009, SPEC-010
основан_на: SPEC-011 sha256:7514b90dedd52bd7419edcdc82a850c5231949cfdbfe0df4c427b773bec8e350
---

# План среза 011: Сроки и отчёты заявок

## Сверка с конституцией

- **модуль-приложение** — новых приложений нет: срез расширяет `apps.servicedesk` (уровни SLA, сроки на заявке,
  частые ответы, отчёт); связи с ядром — через существующие точки `menu_items`, `notification_kinds`,
  `audit_labels`, `stand_reset`; календарь — через `apps.org.services.calendar`, уведомления — через
  `apps.notify.services.dispatch`.
- **настройка-без-кода** — уровни, привязки, расписание, шаблоны, права, часы напоминания — данные;
  администратор меняет их в интерфейсе.
- **пдн-152фз** — во внешние каналы (Telegram, MAX, Web Push) уходят только событие и ссылка на заявку без темы и
  текста; отчёт и Excel — внутри портала и под правом; чужие очереди в отчёт не попадают.
- **sql-только-параметры** — отчёт, фильтры очереди и отчётные выборки — параметрами; ключи фильтров, сортировок
  и периодов — из белого списка.
- **аудит-изменений** — журнал только дополняется: уровни, привязки, шаблоны, выгрузка отчёта.
- **стек-интерфейс** — HTMX, без нового JS; Excel — серверный `openpyxl` (уже в зависимостях).
- **стек-бэкенд** — Django 5.2, PostgreSQL, RQ-задания в `maintenance`; новых пакетов нет.
- **эталон-не-копия** — берём сроки и уровни из эталона, а расчёт по рабочему календарю, два срока, отчёт и
  шаблоны — свои решения по SPEC-011.

## Технический контекст

### Новые компоненты и лицензии

Новых пакетов нет: `openpyxl==3.1.5` уже в `requirements.txt` (его использует срез 010). Новых JS нет: вставка
шаблона — HTMX-запрос и подстановка текста в `textarea` небольшим кодом в `static/servicedesk/answers.js`
(без сторонних библиотек). Календарь, уведомления, файлы и Excel — существующие службы.

### Где живёт код

```
backend/apps/servicedesk/
  models.py                 + SlaLevel, SlaBinding, AnswerTemplate; поля сроков в Ticket; настройки напоминания
  migrations/0004_sla_answers.py, 0005_initial_data.py
  services/sla.py           подбор уровня, расчёт сроков, снимок, циклы, вердикты, фильтры просрочки
  services/answers.py       общие и личные шаблоны, видимость, архивирование
  services/reports.py       показатели отчёта и выгрузка xlsx
  services/settings.py      + часы напоминания
  tasks.py                  + sla_tick (напоминания и просрочка), sla_digest (сводка руководителю)
  notify_kinds.py           + servicedesk.sla_due_soon, servicedesk.sla_overdue, servicedesk.sla_digest
  audit_labels.py           + метки уровней, шаблонов и выгрузки
  extensions.py             + пункты меню «Уровни обслуживания», «Отчёт по заявкам»
  urls.py                   + маршруты уровней, отчёта и шаблонов
  views/sla.py, views/reports.py, views/answers.py    (новые)
  views/tickets_list.py, views/ticket_card.py         + фильтры срока и блок сроков в карточке
  views/ticket_new.py, services/tickets.py            + применение уровня при создании и смене полей
  services/replies.py, services/closing.py            + факты реакции, решения и нового цикла
backend/templates/servicedesk/sla/{page,_list,_form}.html
backend/templates/servicedesk/reports/page.html
backend/templates/servicedesk/answers/{page,_list,_form}.html
backend/templates/servicedesk/card/_sla.html
backend/static/servicedesk/answers.js
backend/tests/test_sd_sla_*.py, test_sd_reports_*.py, test_sd_answers_*.py, tests/e2e/test_t11_*.py
backend/tests/load/… (новых профилей нет — NFR-730 меряется классом ServiceDeskUser)
```

### Изменения ядра и прежних модулей

| Файл | Изменение | Зачем |
|---|---|---|
| данные установки `core 0016` | права `servicedesk.sla`, `servicedesk.reports`, `servicedesk.answers`; «Администратор портала» — sla и answers, роль «Руководитель» — reports; идемпотентно | FR-756 |
| `apps/servicedesk/models.py` + `0004` | три модели и поля сроков в `Ticket`; два поля в `ServiceDeskSettings` | FR-730…745 |
| `apps/servicedesk/services/settings.py` | `reminder_hours` 1–24, по умолчанию 1 | FR-743 |
| `config/cron.py` | `servicedesk_sla_tick` (`*/5`, 300), `servicedesk_sla_digest` (`10 5`, 300) в `maintenance` — после записей поручений | FR-743/744, NFR-734 |
| `templates/_assets.html` | `answers.js` для `/servicedesk/answers/` и карточки заявки | вставка шаблона |
| `apps/servicedesk/extensions.py` | пункты меню «Уровни обслуживания» (order 5, `servicedesk.sla`) и «Отчёт по заявкам» (order 6, `servicedesk.reports`) рядом с «Заявками» | навигация |
| `apps/servicedesk/stand.py` | сброс новых таблиц и полей сроков у заявок, порядок строк `stand_reset` сохраняется | стенд |

`role_sources` не регистрируется: права — данные. Nginx не меняется: файлов у среза нет.

### Запуск

Новых служб нет. Миграции: `core 0016` от `0015`, `servicedesk 0004` от `0003` и `core 0016`, `servicedesk 0005`
(данные) от `0004`. Задания идут в очереди `maintenance` (её читают `worker-mail` и `worker-1/2`).

## Модель данных

### Приложение `servicedesk` (миграция 0004)

| Модель / поле | Поля | Индексы и ограничения |
|---|---|---|
| `SlaLevel` | `title` 100, `priority` 0–99 (меньше — важнее), `reaction_minutes` 5…43 200, `solution_minutes` 5…43 200, `workdays` JSON (0–6, по умолчанию `[0,1,2,3,4]`), `day_start` 09:00, `day_end` 18:00, `all_day` bool, `default_assignee` FK `core.User` PROTECT пусто, `archived` bool, `created_at`, `updated_at` | `CheckConstraint` на минуты и `day_start < day_end` при `all_day=False`; индексы `(archived, priority)` |
| `SlaBinding` | `level` FK `SlaLevel` CASCADE, `kind` (`category`/`priority`), `category` FK PROTECT пусто, `priority` FK PROTECT пусто | `CheckConstraint`: ровно одно из `category`/`priority` по `kind`; частичные уникальные `(category)` и `(priority)` — одна привязка на категорию и на критичность |
| `AnswerTemplate` | `owner` FK `core.User` CASCADE пусто (пусто — общий), `title` 100, `text` 10 000, `category` FK PROTECT пусто (только у общего), `archived`, `created_at`, `updated_at` | индексы `(owner, archived)`, `(category)`; `CheckConstraint`: личный шаблон без категории |
| `Ticket` + | `sla` FK `SlaLevel` SET_NULL пусто, `sla_cycle_started_at` timestamptz пусто, `sla_reaction_due`, `sla_solution_due` timestamptz пусто, `sla_first_response_at` пусто | индекс `(sla_reaction_due, kind)`, `(sla_solution_due, kind)` для фильтров и задания |
| `ServiceDeskSettings` + | `sla_reminder_hours` 1–24 = 1 | `CheckConstraint` 1–24 |

Вердикты не хранятся отдельными полями: «реакция в срок» = `sla_first_response_at <= sla_reaction_due` (или
`IS NULL` до факта), «решение в срок» = `closed_at <= sla_solution_due`; при открытии заново цикл начинается
снова, поэтому закрытие прошлого цикла остаётся только в журнале (`ticket.closed` / `ticket.autoclosed`) — как
решила SPEC-011 (решение 5а/5б).

### Данные установки `servicedesk 0005`

Права и выдачи — в `core 0016` (см. выше). Уровней и шаблонов миграция не создаёт: пустые справочники, в
интерфейсе — пустые состояния (UX-13). Повторный запуск ничего не дублирует.

## Контракты

### Уровни обслуживания (FR-730…737, 755, 756, 757)

| Маршрут | Право | Ответ |
|---|---|---|
| `GET /servicedesk/sla/` | `servicedesk.sla` | список уровней с привязками и состоянием архива |
| `GET/POST /servicedesk/sla/new/` | `servicedesk.sla` | форма создания; ошибки у полей, 400 |
| `GET/POST /servicedesk/sla/<pk>/` | `servicedesk.sla` | форма правки и привязок |
| `POST /servicedesk/sla/<pk>/archive/` | `servicedesk.sla` | архивирование и возврат из архива (HTMX-строка) |

### Очередь и карточка (FR-738…742)

| Маршрут | Право | Ответ |
|---|---|---|
| `GET /tickets/?f=overdue` | `servicedesk.all` или очередь | фильтр просроченных (реакция или решение) |
| `GET /tickets/?f=today` | то же | срок сегодня |
| `GET /tickets/count/` | то же | счётчики срока рядом с существующими |
| `GET /tickets/<number>/` | доступ к заявке | блок `_sla.html`: уровень, сроки, факты, вердикты, «срок не задан» |

Сортировка по сроку добавляется в существующий белый список сортировок `listing`; ключи `overdue`/`today` —
в белый список фильтров.

### Отчёт (FR-746…750, NFR-731, NFR-735)

| Маршрут | Право | Ответ |
|---|---|---|
| `GET /servicedesk/reports/?period=day|week|month|custom&from=&to=&queue=&sla=&category=&assignee=` | `servicedesk.reports` | страница отчёта; область — `managed_units` пользователя, значения — параметрами |
| `GET /servicedesk/reports/export/…` | `servicedesk.reports` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, имя `tickets-YYYY-MM-DD.xlsx`, запись журнала `servicedesk.report_exported` |

Показатели: создано, закрыто, среднее время реакции и решения в рабочих часах, доля в срок по реакции и
решению, просрочки по уровням, нагрузка исполнителей (закрыто на исполнителя), оценка заявителей — колонка
есть, значения пусты до среза с CAP-35.

### Частые ответы (FR-751…754)

| Маршрут | Право | Ответ |
|---|---|---|
| `GET /servicedesk/answers/` | вход в портал + доступ к сервис-деску | личные и доступные общие шаблоны |
| `GET/POST /servicedesk/answers/new/` | то же; общий — `servicedesk.answers` | форма; личный шаблон создаёт любой сотрудник сервис-деска |
| `GET/POST /servicedesk/answers/<pk>/edit/` | владелец личного или `servicedesk.answers` | форма правки |
| `POST /servicedesk/answers/<pk>/archive/` | то же | архив/возврат |
| `GET /servicedesk/answers/<pk>/insert/` | доступ к заявке | HTMX-фрагмент с текстом для подстановки в `textarea` ответа |

### Уведомления и задания (FR-743…745)

Три вида: `servicedesk.sla_due_soon` (order 230), `servicedesk.sla_overdue` (231), `servicedesk.sla_digest` (232);
получатели — ответственный, руководитель очереди (по `managed_units` очереди), автор действия исключён; ссылка —
`/tickets/<number>/`, `object_ref` — `servicedesk.ticket:<pk>`; во внешние каналы только событие и ссылка.
`sla_tick` каждые 5 минут: напоминание за `reminder_hours` рабочих часов, отметка просрочки (одна на срок —
строка-маркер в Valkey, как у задач), сводка — `sla_digest` в 05:10 UTC.

## Интеграции

- **Календарь (SPEC-002)** — `org.services.calendar`: `day_kind` (рабочий/сокращённый/выходной/праздник) и
  `WorkCalendar.day_start/day_end`. Новый расчёт `sla.deadline(start, minutes, level)` идёт по рабочим дням
  календаря и интервалу уровня; своих календарей у уровня нет.
- **Уведомления (SPEC-004)** — через `notify.services.dispatch`; тихие часы и каналы — настройки сотрудника;
  внешние каналы получают только событие и ссылку.
- **Почта** — не меняется: ответы и письма идут прежними службами; факт реакции фиксируется в `replies.reply`.
- **Файлы** — не меняются.
- **Внешние системы** (Telegram/MAX/Zabbix/АСДОБ) — новых вызовов нет.

## Проверка

### Серверные тесты (Django TestCase на PostgreSQL)

| Файл | Что закрывает |
|---|---|
| `test_sd_sla_models.py` | модели, ограничения, уникальность привязок, архив (FR-730…733) |
| `test_sd_sla_deadlines.py` | расчёт рабочих часов: вечер пятницы, выходные, праздник, «круглосуточно», переход года (FR-734, FR-735) |
| `test_sd_sla_ticket.py` | подбор уровня при создании, конфликт категория/критичность, снимок, пересчёт до первого ответа, заявка без уровня (FR-734…737) |
| `test_sd_sla_cycles.py` | первый ответ (`reply`/`waiting_files`/`not_sent`), закрытие ручное и автозакрытие, открытие заново, вердикты (FR-738…740) |
| `test_sd_sla_views.py` | уровни, фильтры `overdue`/`today`, счётчик, карточка; права и 403 (FR-730…742, 757) |
| `test_sd_sla_notify.py` | три вида уведомлений, получатели, без повторов, внешний текст без темы (FR-743…745) |
| `test_sd_reports.py` | показатели за период, фильтры, область `managed_units`, пустой отчёт, оценка пуста (FR-746…750) |
| `test_sd_reports_excel.py` | те же числа в xlsx, имя файла, журнал, 20 000 строк ≤ 10 с (FR-748, NFR-731) |
| `test_sd_answers.py` | общие и личные шаблоны, видимость, архив, привязка к категории, вставка (FR-751…754) |
| `test_sd_sla_cron.py` | `sla_tick` и `sla_digest` в расписании, идемпотентность, повторы после перезапуска (NFR-732, NFR-734) |
| `test_sd_sla_core_changes.py` | права `core 0016`, меню, метки журнала, `stand_reset`, хвост `INSTALLED_APPS` не меняется |

### Браузер (Playwright, `t11`)

`t11_01` — администратор создаёт уровень и привязки; `t11_02` — заявка получает сроки и показывает блок в
карточке; `t11_03` — просрочка в очереди, фильтры и счётчик; `t11_04` — руководитель смотрит отчёт и выгружает
Excel; `t11_05` — вставка общего и личного шаблона; `t11_06` — 360 px и докладная область отчёта. Наполнение —
`fill_tickets.py` и `ServiceDeskUser` (профиль среза 003), отдельного профиля не вводим.

### Нагрузка

NFR-730 меряется профилем `ServiceDeskUser` по правилам T-7304 (холодная машина, `systemd-run --user`, порог
остывания 2,5 — решение 2026-11-21) на наполнении `fill_tickets.py` (110 000 заявок / 550 000 сообщений);
L2 — все классы. Известные дефекты NFR-612/707 и ограничение стенда записываются в отчёт.

### Ворота

`tools/verify.sh --быстро` (SDD, инструменты, конституция, секреты, источники, vendor), `manage.py check`,
`git diff --check`; полный серверный прогон — по правилу среза (зелёный полный + красный до реализации).

## Риски

1. **Расчёт рабочих часов ошибается на границах** (вечер пятницы, сокращённый день, праздник, переход года,
   DST в Москве отсутствует) — вероятность средняя: пишем свой цикл по календарю. Что делаем: табличные тесты
   на границы в `test_sd_sla_deadlines`, сверка с `org.calendar` на стенде.
2. **Автозакрытие и открытие заново ломают вердикты** — вероятность средняя: сейчас закрытие и reopen меняют
   `closed_at`, `closed_by`, `resolution`. Что делаем: фиксация фактов в `sla`-полях и журнале, тесты циклов,
   проверка повторного закрытия после reopen.
3. **Отчёт на 110 тыс. заявок медленный** — вероятность средняя. Что делаем: индексы по срокам и датам,
   агрегаты одним SQL на показатель, `EXPLAIN` в тесте, выгрузка 20 000 строк ≤ 10 с (NFR-731); запасной ход —
   агрегатный кэш на 60 с только для страницы отчёта (решение Opus при исполнении, запись в отчёте).
4. **Напоминания дублируются после перезапуска задания** — вероятность средняя. Что делаем: маркер в Valkey
   на «срок + получатель», тест с остановкой задания, как у задач (NFR-732).
5. **Права и область отчёта перепутаны** (участник очереди видит чужое) — вероятность средняя. Что делаем:
   область строго по `managed_units`, тест «участник с правом не видит очередь, где он не руководитель»,
   администратор без отметки — не видит.
6. **Смена категории/критичности после ответа пересчитывает сроки** — вероятность низкая. Что делаем: пересчёт
   только до `sla_first_response_at`, тест на заявке с ответом.
7. **Шаблоны попадают не тому сотруднику** — вероятность низкая. Что делаем: фильтр видимости в службе и тест
   на чужой личный шаблон; архивные не предлагаются.
8. **Чужие тесты среза падают из-за нового хвоста прав и cron** — вероятность высокая: срез добавляет права,
   записи cron, поля `Ticket` и пункты меню. Что делаем: таблица правок прежних тестов — отдельная задача с
   разрешения владельца, как таблица T-10111 среза 010.
