# Срез 010 «Поручения» — состояние и точный следующий шаг

Обновлено: 2026-11-23, после закрытия Этапа 1 (T-10004…T-10008).

## Что сделано в Этапе 1

| Задача | Результат |
|---|---|
| T-10001 | каркас `apps/instructions`, `INSTALLED_APPS`, include, пустые точки |
| T-10002 | `Purpose.INSTRUCTION` + миграция `core 0014`, тест |
| T-10003 | права `instructions.use/assign` + `core 0015`, тест |
| T-10004 | `backend/tests/CONTRACT-010.md` — 15 разделов, коды/тексты, маршруты, зацепки, помощники, таблица T-10111 |
| T-10005 | `backend/tests/support_instructions.py` — поручения, даты, отчёты, переносы, реестр/дисциплина, SQL |
| T-10006 | `backend/tests/e2e/helpers_instructions.py` — cast, страницы, отчёт/решения, переносы, закрытие, Excel, 360 |
| T-10007 | `urls.py` — реестр, фрагмент, настройки; `views/pages.py`; `templates/instructions/_list.html`; cron 27 записей (сделано ранее) |
| T-10008 | `apps/instructions/stand.py`, регистрация `stand_reset` последней, `e2e_instructions_seed`, `tests/test_instructions_stand.py` |
| T-10009/T-10010 | nginx 25m, статика/`_assets` (сделаны до передачи) |

Проверки Этапа 1:

- `manage.py check` — 0 ошибок;
- срез: `tests/test_instructions_models.py`, `test_instructions_core_changes.py`, `test_instructions_stand.py` —
  **6 passed** (`crm-work/slice010/stage1/stage1-tests.log`);
- ворота `tools/verify.sh --быстро` — SDD 130/0/0, tools 176/176, конституция 6/6, секреты и источники чисто,
  vendor 0 ошибок;
- ожидаемые падения прежних тестов из-за `stand_reset`/cron/`APPS_TAIL` — **7**, все в таблице T-10111
  (`crm-work/slice010/stage1/T-10111-before.log`).

## Этап 2 — начало (2026-11-23)

| Задача | Результат |
|---|---|
| T-10101 | `tests/test_instructions_models.py` — 10 новых тестов (поля/пределы, индексы, справочник, участники, даты, итоговый отчёт и части, переносы, напоминания, настройки, файлы/связи с задачами); красный лог `crm-work/slice010/stage2/T-10101-red.log` (10 failed, 1 passed — T-10002) |
| T-10102 | `tests/test_instructions_access.py` — 12 тестов (кто ставит, видимость, только чтение, правка, отчёт/часть, перенос, снятие, блокировка, увольнение контролёра/исполнителя, перевод, 404/403); красный лог `.../T-10102-red.log` (12 failed) |

Оба файла собираются (`--collect-only`) и падают по отсутствию моделей/служб — это ожидаемый красный Этап 2.

## Точный следующий шаг

1. **T-10111 — только после разрешения владельца.** Показать владельцу таблицу TASKS-010 (22 строки с 18а) и
   замер: падают `test_tasks_stand`, `test_feed_stand`, `test_lists_stand`, `test_messenger_stand`,
   `test_kb_deploy` (порядок `stand_reset`, `APPS_TAIL`, cron 24→27). Без разрешения не править.
2. **Этап 2 — продолжить красные тесты** (T-10101/T-10102 сделаны): следующий файл — **T-10103**
   `tests/test_instructions_create.py` + `test_instructions_basis.py` (создание, основание, журнал, состав),
   затем T-10104 dates, T-10105 reports, T-10106 close, T-10107 transfers, T-10108 reminders, T-10109 registry,
   T-10110 discipline, T-10112…T-10124, T-10150. Имена — дословно из `CONTRACT-010.md`; код среза импортировать
   внутри тестов, чтобы сбор проходил до Этапа 3.
4. **T-10159 стенд** — только после разрешения владельца (копия, сборка, миграции, перезапуск, health).
5. **T-10160 красный прогон** — весь серверный набор; каждый новый тест падает, кроме тестов Этапа 1; причина
   записана; прежние зелёные или перечислены в T-10111.
6. Только после T-10160 — Этап 3 (партии кода T-10201…T-10260).

## Команды

```bash
cd /home/gpgr/Документы/CRM
# серверные тесты среза (общая блокировка обязательна)
flock /home/gpgr/Документы/crm-work/slice005/stage2/test.lock \
  docker compose -f deploy/docker-compose.yml --profile test run --rm --no-deps test -q \
  tests/test_instructions_models.py tests/test_instructions_core_changes.py tests/test_instructions_stand.py
# ворота
tools/verify.sh --быстро
# подпись/состояние документов
python3 tools/sdd.py проверить
```

## Ограничения

- Тесты с общей БД — только под `flock` и последовательно; завершённые прогоны не перезапускать.
- Правки прежних тестов — только T-10111 и только с разрешения владельца, диффом «было / стало».
- `git push` и подписи — владелец; коммиты агент делает сам.
- Модели, миграции и службы Этапа 3 не начинать до T-10160.