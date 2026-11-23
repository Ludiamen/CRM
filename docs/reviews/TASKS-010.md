---
id: REV-TASKS-010
вид: отчёт
статус: черновик
версия: 1
проверяет: TASKS-010 sha256:ea65fdca31ca80c2a8895d68c677d044ae54321e35559d40702d6f4fb1b84cb2
исполнитель: crm-implementer
модель: alibaba-token-plan/deepseek-v4.1-flash-1017
дата: 2026-11-23
---

# Отчёт среза 010 «Поручения» (Этапы 1–2)

Вердикт: **Этап 1 закрыт, Этап 2 закрыт по тестам, идёт красный прогон T-10160.** Код Этапа 3 не начат до
завершения красного прогона (решение 3 задач).

## Этап 1 — каркас, контракт, помощники, стенд

| Задача | Результат |
|---|---|
| T-10001 | каркас `apps.instructions`, `INSTALLED_APPS`, include, иконки/шаблоны/статика |
| T-10002 | `Purpose.INSTRUCTION` + `core 0014` |
| T-10003 | права `instructions.use/assign` + `core 0015` |
| T-10004 | `backend/tests/CONTRACT-010.md` — 15 разделов; 52 кода отказов; К1–К23 |
| T-10005 | `backend/tests/support_instructions.py` |
| T-10006 | `backend/tests/e2e/helpers_instructions.py` (+ `cast_for`) |
| T-10007 | реестр/фрагмент/настройки, cron 27 записей |
| T-10008 | `apps/instructions/stand.py`, `stand_reset` последней, `e2e_instructions_seed`, тесты стенда |
| T-10009/T-10010 | nginx `25m`, статика `_assets` |

Проверки: `manage.py check` — 0; срез — `crm-work/slice010/stage1/stage1-tests.log` (6 passed); ворота
`tools/verify.sh --быстро` — SDD 130/0/0, tools 176/176, конституция 6/6, секреты/источники/vendor чисто.

## T-10111 — правки прежних тестов

Владелец 2026-11-23 разрешил все строки таблицы T-10111. Применены строки 1, 2, 5, 6, 8/19, 9, 10: cron 27,
хвост приложений 9, права 22, `Purpose` 8, порядок `stand_reset`, четыре `25m`. Проверка — **353 passed**
(`crm-work/slice010/stage1/T-10111-after-final.log`); до правок — 37 failed (`T-10111-measure.log`). Строки
11–16, 18, 18а и 22 остаются на партии Этапа 3; T-10111 в `tasks.md` остаётся `[ ]`, как T-9011 среза 009.

## Этап 2 — красные тесты

Собрано **186 серверных тестов** (`crm-work/slice010/stage2/collect.txt`) в 20 файлах:

| Задачи | Файлы | Тестов |
|---|---|---|
| T-10101, T-10102 | models (10 новых), access | 22 |
| T-10103 | create, basis | 17 |
| T-10104…T-10107 | dates, reports, close, transfers | 39 |
| T-10108 | reminders | 17 |
| T-10109, T-10110 | registry, discipline | 17 |
| T-10112, T-10113 | tasks, notify | 14 |
| T-10114…T-10116 | digest, settings, files | 19 |
| T-10117…T-10120 | audit, retention, boundaries, seed | 18 |
| T-10121…T-10124 | deploy, core_changes, stand | 20 (из них 6 ожидаемо красные) |
| T-10150 | `fill_instructions.py`, `InstructionUser` | код профиля |

Браузерные сценарии — 10 файлов `tests/e2e/test_t10_*.py`; локаторы — зацепки CONTRACT-010 6.3.

## Красный прогон (T-10160)

`crm-work/slice010/stage2/red/red-20261123-222524/full.log`, 50 мин 52 с: **4628 passed, 171 failed**. Из 186
тестов среза падают **169** — ровно новые тесты Этапа 2; 17 проходят и относятся к артефактам Этапа 1 (Purpose,
права, приложения/адреса/cron/nginx/статика, стенд) — они и должны быть зелёными. Прочие срезы зелёные, кроме двух
регрессий, найденных и исправленных:

| Регрессия | Причина | Исправление |
|---|---|---|
| `test_feed_boundaries::test_feed_registers_eight_notification_kinds_file_purpose_audit_labels_and_stand_reset` | строка 8 T-10111: `stand_reset` ленты теперь `[-4]`, не `[-3]` | индекс поправлен; тест не ослаблен |
| `test_tasks_plan::test_plan_column_choice_in_card_is_visible_only_to_plan_owner` | дефект шаблона среза 009: `data-task-field="plan_column"` стоял на форме правки у всех редакторов | атрибут формы условный (только ответственному); выбор колонки у владельца сохранён |

Контрольная проверка после исправлений: `test_tasks_plan`, `test_feed_boundaries`, `test_tasks_core_changes` —
**33 passed** (`crm-work/slice010/stage2/recheck-unexpected2.log`). Итог красного прогона для среза 010 —
**169 ожидаемых падений новых тестов**, прежние зелёные.

## Стенд (T-10159)

Копия `before-T10159-20261123-222353` (dump/media/protected/env, mode 600, проверены), сборка web/nginx,
миграции, перезапуск, health/image gates; `standtools` видит `apps.instructions`, `/instructions/` — 302,
reset не выполнялся. Лог — `crm-work/slice010/stage2/stand/update-*/update.log`.

## Решения контракта, добавленные по ходу

- **К21** — периодичность отчётных дат не хранится в модели: `build/rebuild` получают её из формы.
- **К22** — `stage` напоминания: `due`, `overdue`, `r3`, `r1` или `d<offset>` (1–60).
- **К23** — форма строк реестра (`Instruction` с `.state`) и дисциплины (две шкалы: `final_in_time`,
  `final_overdue`; `closed` в ответе).
- Дополнены коды `discipline_forbidden`, зацепки `instruction-ladder`, `instruction-task`.

## Этап 3 — код (T-10201…T-10217)

Реализованы модели и миграции `instructions 0001/0002`, настройки и справочник, доступ и увольнение, создание и
правка, отчётные даты, отчёты и части, снятие и переносы, реестр с пресетами и SQL-параметрами, лестница
напоминаний и тихие часы, 10 видов уведомлений (каталог 40), недельная сводка, дисциплина и Excel, файлы с
ClamAV/X-Accel, журнал и история, срок хранения, связь с задачами, меню/настройки и 360 px. Все **186** тестов
среза зелёные; по T-10111 применены строки 11–13, 18, 18а (меню 20, каталог 40) и обновлены прежние тесты меню.

Полный зелёный прогон T-10260, попытка 1 (`full-20261124-001005`): **4791 passed / 8 failed**, все восемь —
последствия новых подписей журнала, видов уведомлений и полей даты:
- `title`/`assignee` в подписях журнала приведены к общим («заголовок», «ответственный»), добавлены недостающие
  ключи (`closed_at`, `report`, `date`, `reason`, `old/new`, `state`, `comment`, `author`, `reminder`, `user`,
  `ladder`, `reports`, `files`);
- каталог без базы знаний: 27 → 37 видов; у задач проверка «после прежних модулей» учитывает поручения;
- родные `input[type=date]` заменены на текстовые `data-datefield-input` (карточка, создание, дисциплина).

Контрольный набор — **77 passed** (`crm-work/slice010/stage3/T-10260-fixes1.log`).

**Повторный полный прогон — ЗЕЛЁНЫЙ: 4799 passed, 0 failed**, 52 мин 31 с
(`crm-work/slice010/stage3/T-10260/full-20261124-010525/full.log`, exit 0). Сверка с красным T-10160
(4628 passed / 171 failed): +171 тест, ровно все падавшие стали зелёными, потерь нет. Это же — полный прогон
T-10300.
## Ворота (T-10303)

`tools/verify.sh --быстро` — **всё прошло** (`crm-work/slice010/stage4-gates.log`): SDD 130/0/0, тесты инструментов
176/176, конституция 6/6, секреты и источники чисто, vendor 0 ошибок (3 замечания о новых версиях Bootstrap,
Alpine.js, SortableJS), `git diff --check` чист.

## Инварианты по диффу (T-10306)

| Инвариант | Результат | Чем подтверждён |
|---|---|---|
| модуль-приложение | PASS: отдельное `apps.instructions`, зависит от `tasks`, связи через точки и публичные службы | `test_instructions_boundaries` (импорты, связи моделей, единственная подписка `core.user_dismissed`) |
| настройка-без-кода | PASS: виды основания, лестница и срок хранения — данные | `test_instructions_basis`, `test_instructions_settings`, `test_instructions_seed` |
| ПДн / 152-ФЗ | PASS: администратор чужих не видит, во внешних каналах только событие и ссылка | `test_instructions_access`, `test_instructions_notify` |
| аудит-изменений | PASS: журнал дополняется, подписи всех кодов, текст отчётов и удаления не пишется | `test_instructions_audit`, `test_instructions_retention` |
| SQL только параметры | PASS: фильтры, поиск и цепочка узлов — параметрами, `= ANY(%s)` | `test_instructions_registry::test_sql_parameters_and_chain_any`, `test_instructions_discipline::test_sql_uses_parameters_and_chain_array` |
| стек-интерфейс | PASS: страницы на HTMX, своих скриптов состояния нет, `instructions.js` — каркас | `test_instructions_deploy` (статика/CSP), e2e `test_t10_*` |
| тест-на-требование | PASS: у каждого FR/NFR есть тест, кроме NFR-720 (ждёт T-10304) | таблица ниже |
| спека-прежде-кода | PASS: код Этапа 3 начат после T-10160 | красный прогон `red-20261123-222524` |

## Требования (T-10307)

| Требование | Проверка | Результат |
|---|---|---|
| FR-700 поля и основание | models, create | PASS |
| FR-701 справочник | basis, settings, seed | PASS |
| FR-702 кто ставит | access, create | PASS |
| FR-703 контролёр | access, create | PASS |
| FR-704 исполнитель/соисполнители | create, reminders | PASS |
| FR-705 отчётные даты | dates | PASS |
| FR-706 отчёт | reports | PASS |
| FR-707 снятие | close, reports | PASS |
| FR-708 перенос | transfers | PASS |
| FR-709 лестница | reminders | PASS |
| FR-710 тихие часы | reminders | PASS |
| FR-711 уведомления | notify, reminders | PASS |
| FR-712 сводка | digest | PASS |
| FR-713 реестр | registry | PASS |
| FR-714 дисциплина | discipline | PASS |
| FR-715 Excel | discipline | PASS |
| FR-716 задачи | tasks | PASS |
| FR-717 статусы | dates, registry | PASS |
| FR-718 журнал/история | audit | PASS |
| FR-719 404 | access | PASS |
| FR-720 360 px | e2e `t10_10` | ожидает T-10302 |
| FR-721 видимость | access, registry | PASS |
| FR-722 увольнение/смена | access, core_changes | PASS |
| FR-723 части | reports | PASS |
| NFR-720 p95 | нагрузка | не замерялся (T-10304 — после решения владельца) |
| NFR-721 SQL | registry, discipline | PASS |
| NFR-722 файлы | files, deploy | PASS |
| NFR-723 внешний текст | notify | PASS |
| NFR-724 идемпотентность | reminders, digest, retention | PASS |
| NFR-725 360/браузеры | e2e 4 круга | ожидает T-10302 |
| NFR-726 русский/Москва | deploy | PASS |
| NFR-727 журнал | audit | PASS |
| NFR-728 профиль | deploy, load | PASS (код профиля); замер — T-10304 |
| NFR-729 хранение | retention, settings | PASS |

## Проход в браузере (T-10301/T-10302)

Стенд обновлён до кода среза: копия `before-T10159-20261124-015940`, миграции `instructions 0001/0002`, 11 таблиц
`instructions*`, `/instructions/` 302. Первый Chromium-круг нашёл дефект формы: `create_instruction` не заполнял
дату основания, а серверные разборы принимали только ISO, тогда как поле даты портала показывает `ДД.ММ.ГГГГ`.
Исправлено: помощник заполняет дату основания; `services.instructions._as_date`, `services.dates` и
`services.transfers` принимают оба формата. Дальше сценарии уточнены: пресет реестра «контроль», обязательные поля
в проверке пустого названия, форма отчёта и блок лестницы в карточке, ожидания состояний без учёта регистра,
срок переноса позже текущего.

**Chromium — 10/10 зелёные** (`crm-work/slice010/stage4/browser/run-chromium-20261124-022415/main-pytest.txt`).
Firefox, Edge и Яндекс запущены следом.
