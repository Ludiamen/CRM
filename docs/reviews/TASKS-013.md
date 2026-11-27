---
id: REV-TASKS-013
вид: отчёт
статус: черновик
версия: 1
проверяет: TASKS-013 sha256:02bc35114d98fe0bff4a5fb07c48fa5082caacf2fb7ed056ead4ae9a77b28d62
исполнитель: opencode
дата: 2026-11-27
---

# Отчёт приёмки среза 013 «Канбан и автоматика»

## Итог

Срез 013 реализует CAP-74, CAP-72 и CAP-66: канбан заявок, автоматику стадий задач и правила-роботы.
Полный серверный прогон — **5032 passed, 0 failed, 3 deselected**, 55:21; браузеры 4×4, нагрузка
пройдена. Независимое ревью кода — `docs/reviews/TASKS-013-CODE.md` (0 находок).

## Полный серверный прогон

- Файл: `crm-work/slice013/stage4/full11.log`; итог: **5032 passed, 0 failed, 3 deselected**, 55:21.

## Браузеры

`crm-work/slice013/stage4/browser/`:

| Браузер | t13 до drag-теста | Итог |
|---|---|---|
| Chromium | 4 passed | 4 passed |
| Firefox | 4 passed | 4 passed |
| Edge | 4 passed | 4 passed |
| Яндекс.Браузер | 4 passed | 4 passed |

## Нагрузка

- NFR-742: `crm-work/slice013/stage4/load/load742.*` — доска p95 400 мс, колонка 130 мс, 100 пользователей,
  110 004 заявки, ошибок 0 (`load742.status=passed`).
- NFR-741: `crm-work/slice013/stage4/load/rules.*` — 200 правил, 100 событий, p95 96,9 мс
  (`rules.status=passed`).
- NFR-745: `backend/tests/test_sd_board_queries.py` — не больше 12 запросов; индексы `sd_ticket_board_sort2`
  и `sd_ticket_board_status`.

## Стенд

- Копия `before-T13000-20261127-093838` (проверена); сборка web/nginx; миграции `core 0018`, `automation 0001`,
  `servicedesk 0006`, `0007`, `0008`; reset не выполнялся. Health/image gates пройдены. После правок форм
  и `priority_order` образ web пересобран; финальный браузерный круг — 4×4.

## Ручной проход

- `crm-work/slice013/stage4/manual/checklist.md`; скриншоты `board-desktop.png`, `board-360.png`,
  `rule-form.png`. Проверены доска, колонки, карточки, перенос через меню, форма правила, 360 px;
  серверные сценарии действий, задержек, порогов и прав — в полном прогоне. Замечаний нет.

## Замечания и исправления

- `automation.stand_reset` чистил default-базу вместо `migrate` — исправлено.
- Полные прогоны `full3`/`full6` выявили устаревшие ожидания тестов и конфликт подписи `priority` — исправлено.
- Нагрузка выявила лишнюю выборку списка на доске, отсутствие индекса по статусу и дорогой расчёт `scope`
  администратора — доска ускорена, добавлены индексы и `priority_order`.
- Код-ревью: 9 замечаний закрыто, затем 2 остаточных (preset, глубина отложенной цепочки) — закрыты.
