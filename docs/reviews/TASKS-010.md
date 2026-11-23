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

Запущен `crm-work/slice010/stage2/red/run-red.sh` через systemd (`crm-T10160-red-*`), весь серверный набор.
Результат — `crm-work/slice010/stage2/red/<run>/full.log`, `full.exit`, `status`. Числа и разбор — после
завершения; новые тесты обязаны падать, кроме тестов Этапа 1, прежние — зелёные или перечислены в T-10111.

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

## Дальше

После зелёной сверки красного прогона — Этап 3, партия 1: T-10201 (модели, миграция `instructions 0001`,
настройки, справочник), T-10202 (права, видимость, увольнение), затем T-10203…T-10206.