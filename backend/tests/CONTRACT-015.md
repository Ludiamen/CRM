# CONTRACT-015: конструктор процессов (срез 015, CAP-104)

Контракт для T-15003/T-15004 (красные тесты) и T-15002…T-15005. Основа — подписанные SPEC-015
(`621fafa9…`) и PLAN-015 (`385b34e4…`). Правила имён и отказов — как в CONTRACT-006: службы `lists`
поднимают `ListsError`/`Http404`/`PermissionDenied`, представления отвечают 404/403, форма — 200 с
подсветкой; коды ошибок перехода — 409.

## 1. Модели и поля

### 1.1. `ListProcess` (`lists_listprocess`)

| Поле | Тип | Null | Правило |
|---|---|---|---|
| `list` | OneToOne `lists.List` | нет | `on_delete=CASCADE`, `related_name="process"`; один процесс на список |
| `title` | `CharField(100)` | нет | пусто = название списка |
| `author` | FK `core.User` | да | `PROTECT`; задаётся при первом включении, меняется при повторном |
| `enabled` | `BooleanField` | нет | по умолчанию `False` |
| `launch_mode` | `CharField(8)` | нет | `manual` / `schedule`, по умолчанию `manual` |
| `schedule_period` | `CharField(8)` | да | `daily` / `weekly` / `monthly`; пусто при `manual` |
| `schedule_weekday` | `PositiveSmallIntegerField` | да | 1…7, только `weekly` |
| `schedule_monthday` | `PositiveSmallIntegerField` | да | 1…28, только `monthly` |
| `schedule_time` | `TimeField` | да | по Москве; обязательно при `schedule` |
| `title_template` | `CharField(200)` | нет | `{дата}` подставляется |
| `created_at`, `updated_at` | `DateTimeField` | нет | `lists.models.now` |

Ограничения: ровно одна пара «период + день» (`daily` — оба пусты; `weekly` — только день недели;
`monthly` — только день месяца); при `schedule` время не пусто. Индекс `(enabled, launch_mode)`.

### 1.2. `ProcessStage` (`lists_processstage`)

`process` FK CASCADE, `title` 100, `order` PositiveInteger, `kind` `open`/`closed` (по умолчанию `open`).
Уникальность `(process, order)`, `(process, Lower(title))`; индекс `(process, order)`.
Порядок переставляется в транзакции через временные отрицательные значения.

### 1.3. `ProcessStageAccess` (`lists_processstageaccess`)

`stage` FK CASCADE, `level` `read`/`edit`, `role` FK `core.Role` PROTECT null, `unit_id` число null.
Ровно один субъект; уникальность `(stage, level, role)` и `(stage, level, unit_id)`; индексы по роли и узлу.
Пустой набор строк = «как у списка»; явный набор обязан содержать хотя бы одну строку.

### 1.4. `ProcessStageField` (`lists_processstagefield`)

`stage` FK CASCADE, `field` FK `Field` CASCADE; уникальность `(stage, field)`; индекс `(field)`.
Поле — видимое поле того же списка, тип любой, включая `file`; «Название» не входит.

### 1.5. `Record.stage`

FK `ProcessStage` `PROTECT`, `null`, `blank`; индекс `(list, stage)`. Стадия — только процесс того же списка.
`PROTECT` запрещает удалить стадию с записями; `stage=NULL` — запись без стадии.

### 1.6. `StageMove` (`lists_stagemove`)

`record` FK CASCADE, `base_version` PositiveInteger, `from_stage_key` PositiveInteger null,
`to_stage_key` PositiveInteger (не null), `from_stage`/`to_stage` FK `SET_NULL` null, `from_title`/`to_title`
100, `actor` FK PROTECT null, `at` DateTime. Уникальность `(record, base_version, to_stage_key)`; индекс
`(record, at)`. `to_stage_key` — неизменяемый снимок идентификатора цели; повтор ищется по нему, а не по FK.

### 1.7. `ProcessLaunch` (`lists_processlaunch`)

`process` FK CASCADE, `period_start` DateField, `status` `created`/`skipped`/`failed`, `record` FK
`lists.Record` `SET_NULL` null, `reason` 200, `created_at`. Уникальность `(process, period_start)`; индекс
`(status, period_start)`.

## 2. Статусы и перечисления

- `ListProcess.LaunchMode`: `manual`, `schedule`.
- `ListProcess.Period`: `daily`, `weekly`, `monthly`.
- `ProcessStage.Kind`: `open`, `closed`.
- `StageMove` — не статус, а строка перехода.
- `ProcessLaunch.Status`: `created`, `skipped`, `failed`.
- `Change.Kind` расширяется `stage` — «Стадия» в истории; строка: `field="stage"`, `name="Стадия"`,
  `before`/`after` — названия или «Без стадии».

## 3. Отказы

| Код | Исключение | HTTP | Когда |
|---|---|---|---|
| `stage_required` | `StageRequired(fields)` | 200 форма / 409 JSON | обязательное поле целевой или текущей стадии пусто |
| `stage_forbidden` | `StageForbidden` | 403 / 409 JSON | нет права записи текущей стадии или целевая не видна |
| `stage_changed` | `StageChanged` | 409 | ожидаемая текущая стадия не совпала |
| `version_conflict` | `VersionConflict` | 409 | версия записи не равна `base_version` и повтора нет |
| `process_absent` | `ListsError` | 404 | процесса нет или он выключен там, где нужен |
| `stage_absent` | `ListsError` | 404 | стадии нет, она чужого процесса/списка |
| `stage_has_records` | `ListsError` | 200 форма | удаление стадии с записями |
| `stage_last_open` | `ListsError` | 200 форма | удаление последней открытой/единственной стадии |
| `stage_access_empty` | `ListsError` | 200 форма | явный пустой набор прав стадии |
| `stage_field_hidden` | `ListsError` | 200 форма | обязательное поле скрыто/чужое |
| `stage_schedule_invalid` | `ListsError` | 200 форма | период, день и время не согласованы |
| `unique_taken` | `ListsError` | 200 форма | значение занято; у скрытой записи без номера и ссылки |

Тексты — в `apps/lists/texts.py`; `StageRequired.message` собирает список названий полей.

## 4. Права стадии

`stage_scope(user, lst)`:

- `None` — процесс выключен или у пользователя `lists.manage` (ограничений стадии нет).
- Иначе `read`/`edit` — номера стадий, где сотрудник входит в набор чтения/правки; пустой набор стадии
  наследует права списка (все стадии читаемы/правимы по списку).

`can_read_record(user, record)`:

```
список читается И (record.stage is None ИЛИ stage_scope is None ИЛИ stage в read∪edit)
```

`can_edit_record`:

```
список правится И (record.stage is None ИЛИ stage_scope is None ИЛИ stage в edit)
```

Управляющий списками — всегда `True` для чтения и правки. Подразделение — цепочка узлов сотрудника,
предки включены (`access.scope`). Кэш — `user._lists_stage_scope` на запрос.

`record_condition(user, lst)` — `None` для управляющего/выключенного процесса, иначе
`Q(stage__isnull=True) | Q(stage_id__in=read∪edit)`. Применяется во всех выборках: таблица, доска, поиск
(включая `_exact_ids`), выгрузка, ссылки, история, значения, файлы, импорт, архив/массовые, заявки, подсказки,
этикетки, значения фильтра.

## 5. Переход

Вход: `record`, `target_stage`, `base_version`, `expected_stage`, `values` (dict, необязательно), `title`
(необязательно), `actor`.

1. `access.lock_list(lst.pk, shared=True)` → `Record.objects.select_for_update()`.
2. Проверить **чтение** записи по актуальным правам (`can_read_record`), иначе `Http404`. Это до любого
   ответа, включая повтор и переход на ту же стадию.
3. Найти `StageMove(record, base_version, to_stage_key=target.pk)`; найден — вернуть `MoveResult(stage=target,
   version=record.version, repeated=True)` без записи.
4. Если версия `record.version != base_version` — `VersionConflict`.
5. Если `expected_stage` не совпала с `record.stage_id` (NULL — `None`) — `StageChanged`.
6. Если `target` не того процесса/списка — `stage_absent`; если не читается — `StageForbidden`.
7. Если у пользователя нет правки текущей стадии (для `stage=None` — правки списка) — `StageForbidden`.
8. Итоговые значения: `dict(record.values)`; для каждого присланного кода: пустая строка/пустой список →
   удалить, иначе `values.parse`, как в `records.save`; отсутствующие коды сохраняют значения. `title`:
   отсутствует — прежний, прислан — проверить и заменить.
9. Обязательные поля: коды целевой стадии (вход) и текущей (выход); значение непустое; для `file` —
   `RecordFile(record, field)` существует. Пусто — `StageRequired` со списком кодов.
10. В одной транзакции: `record.values`, `record.title`, `record.stage`, `record.version += 1`,
    `record.updated_by/at`, `StageMove(from_stage_key=old_id|null, to_stage_key=target.pk, from_title, to_title,
    actor)`, `Change(kind="stage")`, `audit.record("lists.record_stage_changed", ...)`.
11. `IntegrityError` уникального ключа `StageMove` — перечитать и вернуть сохранённый результат.

`MoveResult`: `record`, `stage`, `version`, `repeated`.

## 6. Создание, правка, файлы, архив, импорт

- `records.create`: при включённом процессе требует чтения первой открытой стадии; `stage=first_open`.
- `records.save`: при включённом процессе требует `can_edit_record`; обязательные поля текущей стадии
  проверяются на итоговом состоянии, очистка — `StageRequired`.
- `records.create_system`: без проверки прав; значения по умолчанию, `stage=first_open`, `created_by=author`.
- `imports.confirm`: до строк — чтение первой открытой стадии; `will_update` — `can_edit_record` и
  обязательные поля владельца, иначе строка-ошибка; скрытый владелец в предпросмотре без номера/названия.
- `files.attach/delete`: `can_edit_record`; удаление последнего файла обязательного поля текущей стадии —
  `StageRequired`; нечитаемая запись — 404; отказ — 403 без HTML блока.
- `archive.restore`: стадия сохраняется; если `stage=NULL` и процесс включён — `first_open`; поля не
  требуются.

## 7. Плановый запуск

- Период: `daily` — дата; `weekly` — понедельник недели; `monthly` — 1-е число; ключ — `period_start` (МСК).
- Срок: московские дата + `schedule_time`; тик раз в минуту.
- `ProcessLaunch` создаётся первой строкой в точке сохранения: `skipped`; затем:
  - процесс выключен, нет открытой стадии, обязательные поля первой стадии не заполняются умолчаниями →
    `skipped` + причина + журнал;
  - иначе `records.create_system` в точке сохранения → `created`, `record`;
  - ошибка → откат точки сохранения, `failed`, причина, журнал; повтор только в следующем периоде.
- Заголовок: шаблон `{дата}` → ДД.ММ.ГГГГ; пусто → «Название процесса — ДД.ММ.ГГГГ».
- Простой: текущий период один раз, одна запись журнала `lists.process_launch_missed` с числом пропущенных.
- Удаление списка/процесса — каскад; тик не видит.

## 8. Журнал

`lists.process_changed`, `lists.process_enabled`, `lists.process_disabled`,
`lists.process_stage_changed`, `lists.process_stage_deleted`, `lists.process_stage_moved`,
`lists.process_stage_access_changed`, `lists.process_stage_fields_changed`,
`lists.record_stage_changed`, `lists.process_launch_created`, `lists.process_launch_skipped`,
`lists.process_launch_failed`, `lists.process_launch_missed`.

В `before/after`: идентификаторы, названия стадий, числа. Название записи и значения полей не пишутся.
Ручные действия — `actor=user`; минутное задание — `actor=None`.

## 9. Маршруты

| Метод и путь | Право | Ответ |
|---|---|---|
| GET/POST `/lists/<id>/settings/process/` | `lists.manage` | 200 страница / 302 |
| GET/POST `/lists/<id>/settings/process/stages/new/` | `lists.manage` | 200 / 302 |
| GET/POST `/lists/<id>/settings/process/stages/<stage>/` | `lists.manage` | 200 / 302 |
| POST `/lists/<id>/settings/process/stages/<stage>/move/` | `lists.manage` | 302 |
| POST `/lists/<id>/settings/process/stages/<stage>/delete/` | `lists.manage` | 302 / 200 отказ |
| GET `/lists/<id>/board/` | чтение списка | 200 |
| GET `/lists/<id>/board/column/<stage>/` | чтение списка | 200 фрагмент |
| POST `/lists/<id>/board/move/` | правка стадии | 200 HTML/JSON, 403/409 |
| GET/POST `/lists/<id>/<number>/stage/` | правка стадии | 200 / 302 |

`stage` в адресе колонки — `int` или `none` для «Без стадии». Перенос принимает `number`, `stage`,
`base_version`, `expected`; ответ JSON при `Accept: application/json`, иначе HTML доски.

## 10. Тест-план

- `test_lists_process.py` — настройка, автор, включение/повторное включение, стадии, удаление, порядок,
  выключение.
- `test_lists_process_access.py` — формула прав, сужение, пустой набор, роли/узлы, скрытие на всех
  поверхностях, 404, управляющий, выключенный процесс.
- `test_lists_process_required.py` — вход/выход/правка, итоговое состояние, отсутствие/очистка, файл,
  скрытие поля, первая стадия.
- `test_lists_process_move.py` — порядок проверок, `base_version`, повтор, гонка 20, разные цели, цикл,
  устаревшая форма, «Без стадии», удаление стадии и повтор по `to_stage_key`.
- `test_lists_process_board.py` — колонки, счётчики, 50, «показать ещё», архив, сортировка, перенос.
- `test_lists_process_grid.py` — столбец, фильтр, сортировка, выгрузка, загрузка, поиск, подсказки.
- `test_lists_process_schedule.py` — день/неделя/месяц, МСК, `created/skipped/failed`, простой,
  выключение, обязательные поля, удаление, параллельные тики.
- `test_lists_process_journal.py` — действия, авторы, отсутствие названия и значений, история.
