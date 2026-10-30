---
id: TASKS-007
вид: задачи
статус: утверждён
версия: 2
зависит_от: PLAN-007
основан_на: PLAN-007 sha256:bb28b5833b6e954f080037fff8e47ffad95af410f030381020872a473e328bb1
подпись: Максим | 2026-10-30T10:17+03:00 | sha256:522f8da5f261f801cb177ad7ba6f4c0a7430e9b3c5406751d3fb984db59c3310
подпись: Максим | 2026-10-30T12:15+03:00 | sha256:645fb5586eab84ad175f9702db36b3c084c19c6fe88a4dba0fdc3023a7371fef
---

# Задачи среза 007

Формат строки: `- [ ] T-NNNN [P] [исполнитель] описание — путь или тест — (FR-NNN)`.
`[P]` — можно делать параллельно с соседними задачами. Исполнитель — haiku / sonnet / opus / человек (по разделу
«Разделение работы между моделями» в docs/sdd-process.md). Задачи собраны из PLAN-007 и SPEC-007 (15 сценариев,
FR-601…642, NFR-601…614). Задач вне плана здесь нет. Решения, которых план не принимал, собраны в разделе «Решения
Opus по задачам» в конце файла; решения владельца названы как решения владельца (с датой), решения плана — как решения
плана.

Как читать и исполнять:
- **Нумерация.** Номера среза 007 четырёхзначные: Этап 1 — T-7001…, Этап 2 — T-7100…, Этап 3 — T-7200…, Этап 4 —
  T-7300…. Требования среза нумеруются с шести сотен (FR-601…, NFR-601…). Задачи T-7138 (правка тестов прежних срезов),
  T-7159 (стенд) и T-7160 (красный прогон) закрывают Этап 2 и идут до первой задачи Этапа 3.
- **Порядок.** Этапы идут подряд. Внутри этапа задача без `[P]` начинается, когда закончены все предыдущие, а задачи с
  `[P]` не зависят от соседей и не правят общих с ними файлов. Этап 3 идёт партиями (раздел «Этап 3»); после каждой
  партии — весь серверный набор.
- **Тест-на-требование.** В Этапе 2 у каждого теста в скобках стоит FR или NFR, который он закрывает. Запись
  `файл::имя_теста` и есть связь T-NNNN → FR → тест. Приёмка сценариев 1–15 — сценарии Playwright
  `backend/tests/e2e/test_fNN_*.py` (по сценарию на файл, план: «Проход в браузере»). У каждой задачи Этапа 3 названы
  файлы тестов Этапа 2, которые она делает зелёными.
- **Красный прежде зелёного.** Задачи Этапа 3 не начинаются, пока не сделан красный прогон T-7160: тесты сначала падают,
  и это записано. Тест не ослабляют, чтобы он прошёл. Правят код, а правка теста допускается только с причиной в отчёте
  и только по правилам ниже.
- **Регрессия срезов 001–006.** После каждой партии Этапа 3 прогоняется весь серверный набор. Тесты и инструменты
  прежних срезов меняются только одной задачей — T-7138 (раздел плана «Прежние тесты, которые придётся поправить» и
  анализ влияния `crm-work/slice007/tasks/impact.md`), после T-7101 и без `[P]`. Правку любого теста прежнего среза
  система разрешений останавливает: до правки Opus спрашивает владельца с диффом, по одному тесту; исполнитель правит
  только после ответа. Если в Этапе 3 упадёт тест прежнего среза, которого нет в перечне T-7138, его не ослабляют:
  исполнитель останавливается, решение принимает Opus, вписывает его в раздел решений, и только потом правка идёт по
  тому же правилу (с разрешения владельца, по одному тесту).
- **Изменения кода прежних срезов** (план: «Проверка» → «Изменения кода прежних срезов»). Файлы ядра, `org`, `notify`,
  `knowledge`, `config/` и `deploy/`, которые меняет срез, перечислены в таблице плана; каждое изменение делает одна
  задача Этапа 3, названная в решении 30, и только вместе с тестом прежнего поведения (тесты T-7137, T-7126a и T-7126b и
  прежние тесты, которые план называет в столбце «Что не меняется»). Других правок кода прежних срезов нет: если
  исполнителю понадобится иная, он останавливается, Opus решает и вписывает решение в раздел решений до правки кода.
  Исключение одно — каркас T-7001 добавляет строку `apps.feed` в `INSTALLED_APPS` и подключение пустых адресов `feed`
  под `apps.is_installed` (решение 3).
- **Границы модуля `feed`** (план: «Модуль и выключение», «Где живёт код», «Сверка с конституцией»). `feed` не
  импортирует модели `org`, `notify`, `knowledge`, `servicedesk`, `lists`, `search`; из ядра зовёт только публичные
  функции (`core.services.comments.add/update/list_for/delete/delete_for`, `core.services.pdn_patterns`,
  `core.views.pages.collect_notices`, `core.ws.SessionGuardMixin`, `core.services.uploads`, `core.services.files`,
  `core.services.permissions`, `audit.record`, файловые ответы ядра), из `org` — только `apps.org.services.structure`
  (`unit_chain_ids`, `subtree_member_ids`, `unit_chains`, `all_units`, `unit_refs`), из `notify` — только
  `apps.notify.services.dispatch.create` и `apps.notify.services.live.group`; каждый вызов `org` и `notify` — под
  `apps.is_installed`. Ядро и прежние модули (`core`, `org`, `servicedesk`, `notify`, `knowledge`, `lists`, `search`) не
  импортируют `feed`. Новая точка ядра одна — `home_body` (в конце `POINTS`; точек становится восемнадцать); `feed`
  регистрирует записи в `menu_items`, `home_body`, `search_providers`, `notification_kinds`, `file_purposes`,
  `audit_labels`, `stand_reset`, а `home_notices` только читает (функцией ядра `pages.collect_notices`). Маршрут
  `/ws/feed/` подключается в `config/asgi.py`, адреса `/feed/…` — в `config/urls.py`, задания `feed_*` — в
  `config/cron.py`, всё под `apps.is_installed("apps.feed")`. Номер узла в адресатах хранится числом без внешнего ключа.
  Подписок шины у `feed` нет; уведомления — прямым вызовом `dispatch.create`.
- **Размер.** Одна задача — не больше полудня работы одного исполнителя. Задание агенту — не больше ~50 вызовов. Файл
  тестов — не больше ~25 тестов; большее делится на задачи и файлы `test_x.py`, `test_x_2.py`. Задача Этапа 3, которая
  не укладывается, останавливается; Opus делит её буквами (`T-72NNa`, `T-72NNb`) и вписывает это в решения.
- **Общие файлы тестов** — у каждого один автор: `backend/tests/CONTRACT-007.md` пишет только T-7100,
  `backend/tests/support_feed.py` — только T-7101, `backend/tests/e2e/helpers_feed.py` — только T-7140a. Параллельные
  исполнители держат свои помощники внутри своего файла теста, а общие файлы не правят; недостающее имя — вопрос Opus.
- **Общие файлы кода** (Этап 3) — у каждого один автор за раз; задачи, которые их правят, идут без `[P]` (перечень —
  решение 29 в конце файла). Тексты отказов, адреса, зацепки `data-*`, коды закрытия и сообщения слоя каналов
  исполнители кода берут дословно из `CONTRACT-007.md`.
- **Браузеры приёмки** (правило владельца 2026-10-21, `crm-work/slice005/owner-answers-2026-10-21-stage4.md`): приёмка
  среза 007 — все четыре браузера (Chromium, Firefox, Edge, Яндекс Браузер); приёмка срезов 001–006 — Chromium и Яндекс
  Браузер, круги отбираются ключом pytest `-k` по имени круга (как в T-6302). `backend/tests/e2e/conftest.py` уже
  содержит четыре круга (`PROJECTS`) и не правится. Playwright запускается из хостового окружения `CRM/.venv`.
- **Секреты — только `***`** (в коде, документах, отчётах, выводе команд). Это правило ставится в задание каждому
  исполнителю. Новых секретов срез не вводит. Файлы окружения (`deploy/.env` и любые `.env`), `state/`, `creds*.csv`,
  `activation.txt` не открываются.
- **SQL — только параметры** (инвариант «sql-только-параметры», NFR-608): литерал SQL с `%s` и списком параметров
  (видимость с цепочкой узлов массивом `= ANY(%s)`, курсор, счётчик непрочитанных, поиск, векторы — по образцу
  `knowledge/services/vectors.py`); никаких f-строк, `%`-подстановки и склейки строк с вводом. Ключи фильтров и
  параметры `/ws/feed/` — белый список, значения — параметрами; `ws-connect`, `hx-get` и ссылки строятся из разобранных
  значений.
- **Отчёты подагентов.** Подагенту инструмент Write для отчётов запрещён: черновики и отчёты в `crm-work` пишутся через
  Bash heredoc.
- **Тесты и контейнер.** Нельзя монтировать файлы в `backend/` контейнера и класть временные тесты в `backend/tests`:
  пробы — во временном каталоге вне репозитория. Тесты сервера —
  `docker compose -f deploy/docker-compose.yml --profile test run --rm test`; прогоны длиннее нескольких минут (полный
  набор, приёмка, нагрузка) запускаются через `systemd-run --user`, чтобы пережить обрыв сессии. Запущенный стенд (web,
  web-heavy, worker, worker-mail, worker-inbox, worker-notify, notify-poller, scheduler, nginx, standtools) исполнители не
  останавливают и не пересоздают: сбросы, пересборки, остановки служб и обновления стенда делает Opus с разрешения
  владельца и только после копии стенда (`backup-stand.sh`). Приёмка идёт на пустом стенде (сброс перед каждым кругом);
  после сна ноутбука перед прогоном перезапускаются worker-ы RQ.
- **Зависимости.** Новых пакетов план не вводит (план: «Новые компоненты и лицензии»): Channels, channels-redis, redis,
  Pillow, uvicorn, websockets, locust, websocket-client уже закреплены, `htmx-ext-ws` 2.0.4 уже вендорный. Если
  исполнителю понадобится пакет, он останавливается и спрашивает Opus; принятый пакет ставится и в
  `backend/requirements.txt`, и в хостовое окружение `CRM/.venv` (из него идёт приёмка Playwright).
- **Если задание расходится с планом,** исполнитель останавливается и спрашивает Opus. Решение сначала вписывается в
  раздел «Решения Opus по задачам», и только потом меняется код.
- Ссылки на разделы плана — в названии задачи или в `(план: …)`.

## Этап 1 — подготовка

- [x] T-7001 [sonnet] каркас по блоку «Где живёт код» плана; сверх блока — ничего: `backend/apps/feed/` (`apps.py` с
  классом `FeedConfig` и меткой `feed`, пустые `models.py`, `texts.py`, `notify_kinds.py`, `audit_labels.py`,
  `extensions.py` с пустой `register_all()`, `stand.py`, `tasks.py`, `consumers.py`, `routing.py` с пустым
  `websocket_urlpatterns`, `urls.py` с пустым `urlpatterns`; пакеты `migrations/`, `management/commands/`, `views/` с
  пустыми `home.py`, `posts.py`, `comments.py`, `likes.py`, `important.py`, `events.py`, `files.py`, `pickers.py`,
  `settings.py`; пакет `services/` с пустыми `visibility.py`, `posts.py`, `recipients.py`, `mentions.py`, `text.py`,
  `pdn.py`, `important.py`, `events.py`, `reminders.py`, `comments.py`, `likes.py`, `unread.py`, `live.py`, `files.py`,
  `thumbs.py`, `search.py`, `retention.py`, `notify_rules.py`, `feed_settings.py`, `page.py`), каталог
  `backend/templates/feed/`, пустые `backend/static/feed/feed.js`, `feed.css`; в `INSTALLED_APPS` — `apps.feed` последним,
  после `apps.search` (решение плана); в `config/urls.py` — `include("apps.feed.urls")` под
  `apps.is_installed("apps.feed")` (пустой список адресов, поведение портала не меняется; решение 3). Маршрут
  `/ws/feed/` в `config/asgi.py`, слой `publish`, задания cron, миграции, регистрации точек, иконка — в Этапе 3. В
  отчёте `docs/reviews/TASKS-007.md` задача заводит пустые подразделы «Ранние факты: T-7003», «… T-7004», «… T-7005»,
  «… T-7006», «… T-7007» и «Подготовка: зависимости (T-7002)» (решение 27). Новых зависимостей нет. После каркаса
  сервер и тесты срезов 001–006 зелёные, кроме проверок хвоста `INSTALLED_APPS` из перечня T-7138 (`test_kb_deploy.py`,
  `test_notify_deploy.py`, `test_lists_deploy.py` — тесты места приложения; решение 3) — backend/apps/feed/,
  backend/templates/feed/, backend/static/feed/, backend/config/settings.py, backend/config/urls.py — (план: «Где живёт
  код», «Модуль и выключение», «Прежние тесты, которые придётся поправить»; FR-641)
- [x] T-7002 [P] [sonnet] проверка «новых зависимостей нет» (план: «Новые компоненты и лицензии»): в тестовом контейнере и
  в хостовом `CRM/.venv` импортируются и совпадают с `backend/requirements.txt` и `requirements-dev.txt` версии
  `channels` 4.3.2, `channels_redis` 4.3.0, `redis` 8.1.0, `Pillow` 13.0.0 (в том числе `PIL.ImageOps.exif_transpose`,
  `Image.draft`, запись WebP — `PIL.features.check("webp")`, первый кадр GIF), `uvicorn` 0.54.0, `uvicorn-worker` 0.4.0,
  `gunicorn` 26.2.0, `websockets` 17.2, `locust` 2.46.6, `websocket-client` 1.9.2; в хостовом окружении — `playwright`
  1.63.0; `backend/static/vendor/htmx-ext-ws-2.0.4.min.js` и `htmx-2.0.11.min.js` на месте и записаны в `VERSIONS.md`;
  `test_stack.py::test_requirements_pinned_and_licensed` зелёный; `requirements.txt` не меняется, строки «Срез 007» нет.
  Расхождение версий хоста и контейнера или отсутствие WebP — остановиться и спросить Opus — отчёт
  docs/reviews/TASKS-007.md, раздел «Подготовка: зависимости (T-7002)» — (FR-634, NFR-612; план: «Новые компоненты и
  лицензии»; инвариант «бесплатные-компоненты»)
- [x] T-7003 [P] [opus] ранний замер видимости варианта B для числа непрочитанных и блока важных и замер числа многим
  (план: «Риски» — «вариант видимости B для счётчика непрочитанных не мерили … замер в Этапе 1», «`unread.counts` …
  замер — задача Этапа 1, предел — 50 мс на 100 получателей»; docs/reviews/PLAN-007.md, «Что не проверялось»): на
  временном контейнере `postgres:17-alpine` (имя `tasks007-db`, порт из диапазона 127.0.0.1:31600–31619; стенд и
  контейнер `postgres` не трогать; контейнер остаётся до конца T-7007 и удаляется ею) — таблицы по модели плана («Модель
  данных» → «Приложение `feed`»: `Post`, `Recipient` с частичными индексами, `Shown` без индекса по записи, `ReadMark`,
  комментарии со ссылкой `object_ref`) и данные по условиям F1 (50 000 записей, 200 000 комментариев, 100 сотрудников,
  30 узлов глубиной до 4; скрипты `/tmp/facts007-db/01_schema.sql`, `02_data.sql`, если ещё на месте, иначе заново по
  `crm-work/slice007/plan/facts/F1-db.md`, «Условия замера»); замер функцией по образцу F1 (29 сотрудников × 3, медиана
  / p95 / макс, первый прогон отброшен, `EXPLAIN (ANALYZE, BUFFERS)` у худшего): (1) `unread.count` литералом плана
  («Непрочитанное» → «Число», `LIMIT 100`, видимость B с цепочкой массивом); (2) блок важных литералом плана («Лента,
  курсор…» → «Блок важных»); (3) `unread.counts` на 100 получателей одним запросом по описанию плана (пары «сотрудник —
  узел» массивами, ветки «Всем», «узел», «человек», минус показы и свои, потолок 100) — сверка с сотней одиночных
  `count` (равенство по каждому) и время. Пределы — решение 42: p95 числа или блока больше 10 мс либо `counts` больше 50
  мс (предел плана) — остановиться: запасной ход плана (ветки UNION ALL для счётчика; для `counts` — ход «Рисков»)
  выбирает Opus с владельцем до Этапа 3; машина в момент замера записывается (`/proc/loadavg`) — отчёт
  docs/reviews/TASKS-007.md, раздел «Ранние факты: T-7003» — (FR-602, FR-614, FR-626, NFR-601, NFR-608; план: «Риски»)
- [x] T-7004 [P] [opus] ранний замер `permissions_of` на 100 получателей (план: «Живые обновления» → «Рассылка», шаг 3 —
  держатели «Модерировать ленту», `staff.view` и `accounts.manage` среди получателей правами ядра на момент рассылки;
  docs/reviews/PLAN-007.md, «Что не проверялось»): на стенде через `manage.py shell` службы `web`, только чтением:
  `core.services.permissions.permissions_of(user, fresh=True)` (кэш не читается и не пишется) по 100 действующим учёткам
  с личными ролями и ролями узлов из `role_sources` (если на стенде меньше 100 действующих — по всем, с пересчётом на
  100 в отчёте); время всего цикла (лучший из трёх) и число запросов (`CaptureQueriesContext`); тёплый кэш ядра не
  мерится — прогрев кэша был бы записью на стенде. Данных не пишет, служб не останавливает, стенд не сбрасывает —
  отдельного разрешения владельца не нужно, но не во время приёмки и полного прогона (решение 27). Больше 100 мс на 100
  получателей — остановиться: способ (один запрос «право → роли → сотрудники» с ролями узлов через `org` или иное)
  выбирает Opus до T-7222a; замер на 100 учётках повторяет нагрузка T-7304 (решение 27) — отчёт
  docs/reviews/TASKS-007.md, раздел «Ранние факты: T-7004» — (FR-628, NFR-602; план: «Живые обновления»)
- [x] T-7005 [P] [sonnet] ранняя проверка отправки сообщения клиентом через расширение `ws` (план: «Живые обновления» →
  «`FeedConsumer`» — «`feed.js` шлёт JSON методом `send` обёртки сокета, которую расширение `ws` отдаёт в событии
  `htmx:wsOpen`; серверного элемента `ws-send` нет; F2 Ф8»; «htmx-ext-ws в Firefox и WebKit не проверяли»): во временном
  каталоге вне репозитория — страница с копиями вендорных `htmx-2.0.11.min.js` и `htmx-ext-ws-2.0.4.min.js` (только
  чтение из `backend/static/vendor/`), внешним скриптом и заголовком CSP как у портала (`script-src 'self'`,
  `style-src 'self'`, `connect-src 'self'`), и малое приложение ASGI на `uvicorn` хостового `CRM/.venv` с эхо-сокетом;
  Playwright из `CRM/.venv` в Chromium, Firefox, Edge и Яндекс Браузере (теми же способами запуска, что `PROJECTS` в
  `backend/tests/e2e/conftest.py`): (1) в `htmx:wsOpen` есть `event.detail.socketWrapper.send`, сообщение JSON доходит
  до сервера при каждом открытии, в том числе после переподключения; (2) ответный кадр `hx-swap-oob` (служебный
  `#feed-synced`) вставляется, кадр без цели даёт `htmx:oobErrorNoTarget` в консоли (подтверждение F2 Ф6);
  (3) `htmx:oobBeforeSwap` позволяет отменить вставку `beforeend`, если элемент с тем же `id` уже есть; (4) закрытие
  сервером кодами 1011, 1012, 1013 и обрывом соединения без кадра закрытия (клиент видит 1006) — переподключение и
  задержка, 1000 и 1001 — нет, событие `htmx:wsClose` приходит; (5) вставленный `<script>` под CSP не исполняется.
  Расхождение с планом в любом браузере — остановиться и спросить Opus (план: «Риски», запасной ход для 1000/1001) —
  отчёт docs/reviews/TASKS-007.md, раздел «Ранние факты: T-7005» — (FR-627, FR-628, NFR-605; план: «Живые обновления»,
  «CSP», «Риски»)
- [x] T-7006 [P] [opus] ранняя проверка кода закрытия соединений при плавном перезапуске (план: «Риски» —
  «Переподключение вкладок после выкладки: код закрытия uvicorn при плавном перезапуске не проверен (1012 — вернутся,
  1000/1001 — нет)»): малое приложение ASGI с сокетом во временном каталоге вне репозитория; запуск тем же способом, что
  служба `web` (`gunicorn` с `uvicorn_worker.UvicornWorker`, число процессов и тайм-ауты — как в
  `deploy/docker-compose.yml`), во временном контейнере образа `crm-portal:local` (имя `tasks007-uv`, порт
  из диапазона 127.0.0.1:31620–31639, без сети стенда, каталог пробы смонтирован вне `backend/`, контейнер удаляется
  после работы; решение 27); клиент — `websocket-client` хостового окружения, десять соединений; события: `SIGHUP`
  главному процессу (перезагрузка процессов), `SIGTERM` (как `docker stop` и пересоздание контейнера при `up -d`),
  остановка одного процесса-исполнителя; записать код и причину закрытия у клиента и время до закрытия. Итог задаёт
  обработку `htmx:wsClose` в `feed.js` (T-7223): при 1000/1001 — переподключение по запасному ходу плана; повторная
  проверка на стенде — при первом обновлении стенда в Этапе 4 (T-7305) — отчёт docs/reviews/TASKS-007.md, раздел «Ранние
  факты: T-7006» — (FR-627, NFR-614; план: «Риски»)
- [x] T-7007 [opus] (после T-7003, на её контейнере) ранний замер ORM-каскада ночной очистки на 1 000 записей (план:
  «Срок хранения и ночное задание», шаг 2 — «замер Ф12 шёл сырым SQL, время ORM-пачки с каскадом не мерили»; «Риски»;
  docs/reviews/PLAN-007.md, «Что не проверялось»; решение 27): во временном каталоге вне репозитория — одноразовый
  проект Django 5.2 хостового `CRM/.venv` с моделями, повторяющими таблицу плана (`Post`, `Recipient`, `FeedComment`,
  `PostLike`, `CommentLike`, `ReadMark`, `EventAnswer`, `Shown` с `db_index=False`, `FeedFile`) и упрощёнными копиями
  `core.Comment` (поля и индекс (`object_ref`, `created_at`, `id`)) и `core.StoredFile` с теми же связями
  (`related_name="+"`, CASCADE, PROTECT) и с обработчиками сигналов удаления, если они есть у моделей ядра (выяснить
  чтением `backend/apps/core/`); миграции в базу контейнера `tasks007-db` (отдельная схема или база, данные T-7003 не
  трогать), наполнение `bulk_create` по распределению F1 (на 1 000 удаляемых записей — около 4 000 комментариев,
  отметки, файлы, прочтения, ответы, показы); пачка ночного задания по плану:
  `Comment.objects.filter(object_ref__in=refs).delete()`, затем `Post.objects.filter(pk__in=ids).delete()`, строки
  `StoredFile`, в одной транзакции; время пачки (лучший и худший из пяти на свежих данных), число и вид запросов
  (`CaptureQueriesContext`). Пачка дольше 5 с или вид запросов, при котором 17 пачек F1 не уложатся в `job_timeout=600`,
  — остановиться: запасной ход плана (удаление пачки сырым SQL по образцу замера) выбирает Opus до T-7229 (решение 42),
  а первым шагом T-7229 идёт короткая повторная проверка на настоящих моделях (решение 27); в конце — удалить контейнер
  `tasks007-db` и временный каталог — отчёт docs/reviews/TASKS-007.md, раздел «Ранние факты: T-7007» — (FR-638, NFR-610;
  план: «Срок хранения и ночное задание», «Риски»)
- [x] T-7008 [человек] прочитать раздел «Решения Opus по задачам» в конце этого файла и согласиться с ним; затем
  подписать TASKS-007 (`python3 tools/sdd.py подписать --кто … specs/007-feed/tasks.md`). Задачи подписываются до
  начала Этапа 2 — tasks.md: статус «утверждён» — (инвариант «спека-прежде-кода»)

## Этап 2 — тесты (пишутся до кода и падают)

Общие правила тестов — решения 2, 5, 6, 7, 9, 18–25, 31 и 49 в конце файла; номера требований у тестов — решение 26.

- [x] T-7100 [sonnet] контракт имён среза. `backend/tests/CONTRACT-007.md` по структуре CONTRACT-006 (план: «Контракты»
  → `tests/CONTRACT-007.md` — среда и числа, модели и данные установки, ядро и записи точек, прежние модули (`org`,
  `notify`, `knowledge`), службы `feed` и точки подмены для тестов гонок и сбоев (слой каналов, ClamAV, время),
  помощники `tests/support_feed.py`, виды уведомлений и таблица «код вида → модуль», журнал, поиск, маршруты, сообщения
  слоя каналов и кадры, зацепки `data-*`, тексты, команды стенда, правки прежних контрактов, вопросы и решения): имена,
  которых нет в плане, но которые нужны тестам — поля форм и параметры маршрутов из «Контрактов» плана (`kind`, `text`,
  `to=all|u<id>|p<id>`, поля срока важного и события, `files`, `pdn_confirmed`, `answer=go|no`, `scope`, `have`, `q`,
  `f`, `author`, `from`, `to`, `before`, `opened`, `since`, `post`, «убрать» файлы при правке, поле срока хранения и
  подтверждение), зацепки `data-*` для приёмки (`data-post-id`, `data-comment-id`, `#menu-badge-feed[data-count]`,
  `data-menu-live-badge`, `#feed-live[data-ws]`, `data-opened`, `#feed-new`, `#feed-synced`, `data-file-state`,
  `data-mention`, части записи `feed-post-<id>`, `-to`, `-body`, `-files`, `-imp`, `-event`, `-likers`, `-comments`,
  `-ccount`, якорь `#c<id>`, блок важных, фильтры, форма и «таблетки» «Кому», таблетка «упомянут», подсказки, плашка,
  списки отметивших, прочитавших, ответивших, адресатов, группа «Лента» выдачи, страница срока хранения), тексты отказов
  дословно из `feed/texts.py` по разделу плана «Тексты отказов» (FR-642 и три текста решений плана), тексты интерфейса
  («Записей пока нет», «По фильтру записей нет», «Новых записей: N», «Подразделение удалено», «уволен», «и ещё N»,
  «изменено», «было важным», «Прочитали N из M», «Удалить запись вместе с комментариями?», «Ближайшее ночное задание
  удалит записей: N»), коды и ключи журнала (таблица плана, `before`/`after`, подписи `audit_labels`), типы объектов
  журнала (`feed.post`, `feed.comment`, `feed.settings`), имена функций служб (`visibility.viewer/visible_posts/
  get_post/can_see/audience/can_edit/can_delete/can_comment`, `posts.publish/delete`, `recipients.parse/line`,
  `mentions.extract`, `text.render_plain/snippet`, `pdn.find_plain`, `important.until/stats`, `events.validate`,
  `reminders`, `comments`, `likes`, `unread.count/counts`, `live`, `files`, `thumbs`, `search.vectors`, `retention`,
  `notify_rules.decide`, `feed_settings.get`, `page`, `tasks.remind_events/retention_night`) и точки их подмены (выборка
  задания напоминаний и пачки ночного задания — для «действия между выборкой и замком»; слой `publish`; построение
  эскиза — для сбоя), исключения служб, сообщения слоя каналов (`feed.event` с ключами, `notify.html`) и сообщения
  клиента (`sync`, `add`), коды закрытия (4401, 1009, 1011, 1013), имена групп (`feed.u.{id}`, `notify.u.{id}`), формат
  `object_ref` (`feed.post:<id>`, `feed.post:<id>:c<cid>`), восемь видов уведомлений с кодами, названиями, `order`
  70…77, каналами, внешними текстами и шаблонами текстов, записи точек `feed` с ключами и порядками, новые публичные
  функции ядра и `org` (`comments.update`, `pdn_patterns.EMAIL/PHONE`, `pages.collect_notices`, `ws.SessionGuardMixin`,
  `structure.subtree_member_ids/unit_chains`), поля `NotificationKind.channels/coalesce_text`, ключ `live_badge` пункта
  меню, команды стенда `e2e_feed_shift --minutes N` и `e2e_feed_retention --age-days N [--posts <номера через запятую>]`
  со строками вывода `feed_shift: shifted=<N> reminded=<M> important=<K>` и `feed_retention: aged=<N> deleted=<M>`,
  `fill_feed.py` и строка итога `fill_feed: posts=… comments=… likes=…`, числа среза (восемнадцать точек, двадцать
  вызовов `register` cron, восемнадцать прав, двадцать видов уведомлений, пятнадцать полей `NotificationKind`, `order`
  группы поиска 60, четырнадцать пунктов меню администратора, один `location` 25m, два ключа `CHANNEL_LAYERS`,
  `apps.feed` последним), значения констант `support_feed.py` для правок T-7138 (`TITLES_007`, `POINTS_007`,
  `APPS_TAIL`, `FEED_KINDS`, `FEED_JOBS` и производные; источник — `impact.md`, «Общее»). Сверх перечня плана —
  уточнения решений по задачам: перечень публичных функций ядра и прежних модулей, которые зовёт `feed` (решение 46; на
  него опирается тест границ T-7136); `mentions.sync(...)` возвращает множество впервые упомянутых номеров (решение 47);
  текст отказа «Укажите начало и конец события» (решение 48); раздел «Точки подмены для тестов гонок и сбоев» —
  `dispatch.create` из `feed.services.reminders` и `feed.services.posts`, логгер `apps.feed.tasks`,
  `apps.feed.consumers.CHECK_INTERVAL` (интервал проверки сессии, читается при каждом ожидании, решение 7), `ws_state` в
  цикле проверки, ошибка слоя в `FeedConsumer`, тестовый потребитель на примеси `SessionGuardMixin` (решение 49), вход
  `notify_rules.decide` (решение 51), подмена «запись удалена между проверкой видимости и вставкой `FeedComment`»
  (`feed.services.comments`), подмена «отметка уже создана другим запросом» (`feed.services.likes`), шпион слоя
  `publish` `support_feed.layer_spy()` (считает `group_send` по группам), `support_feed.without_org()` (подмена
  `apps.is_installed("apps.org")`); `support_feed.reload_asgi_without_feed()` (решение 52); тест `asgi` (T-7126a)
  сверяет включение списка `feed.routing.websocket_urlpatterns` в маршруты, а не его содержимое, маршрут `ws/feed/`
  проверяют тесты потребителя T-7124 после T-7223; зацепки «Ответить» `data-reply-id`, `data-reply-name` (решение 13);
  403 у `/settings/feed/` без права `settings.portal` (решение 11); границы команд стенда (решение 10), ключ `--posts` и
  сдвиг `important_until` (решение 54); время в SQL — только параметром из `timezone.now()`, один раз на действие
  (решение 59); раздел «Помощники приёмки» — имена `helpers_feed.py` по строке T-7140a, в том числе `block_ws(context)`
  на `BrowserContext.route_web_socket` Playwright 1.63 (перехват `/ws/feed/` и `/ws/notify/` с закрытием; решения 8,
  55). Там же — «что меняется в прежних контрактах» (таблица «было / стало» для T-7138; сами `CONTRACT.md` и
  `CONTRACT-002…006` не правятся). Контракт проверяется до запуска T-7101 — backend/tests/CONTRACT-007.md — (FR-642;
  план: «Контракты», «Тексты отказов», «Проверка»)
- [x] T-7101 [sonnet] общие помощники тестов по принятому контракту T-7100: `backend/tests/support_feed.py` по образцу
  `support_lists.py` (без `@pytest.fixture`, без импорта `apps.feed` на уровне модуля — модели лениво, код среза внутри
  функций, сбор тестов проходит до появления кода): `PERMISSIONS_007`, `TITLES_007`, `POINTS_007`, `APPS_TAIL`,
  `FEED_KINDS` (восемь строк формата `TABLE` из `test_notify_catalog.py`: код, название, модуль «Лента», `order` 70…77
  по порядку таблицы плана, обязательность, каналы по умолчанию, события, внешний текст; у `feed.like` текст пустой и
  `channels=("portal",)`, решение 43 (а)), `FEED_CODES`, `FEED_TITLES`, `FEED_MODULE`, `FEED_LIKE`, `FEED_BOXED` (все
  виды ленты, кроме `feed.like`), `FEED_JOBS` (формат `LISTS_JOBS` из `test_sd_deploy.py`), `make_post(author, kind,
  to=…, mentions=…)`, `make_event`, `make_important`, `comment`, `like`, `attach(post|comment)` (с подменой ClamAV,
  состояния «чистый», «проверяется», «карантин»), `as_moderator`, `without_post_all(role)`, `without_feed()` (снятие
  регистраций `apps.feed` из реестра точек на время теста, как `without_lists`), `run_seed()` (функция `seed` миграции
  `feed 0002` напрямую), `run_reminders(now)`, `run_retention(now)`, `ws_client(user, query)` (своё подключение по
  образцу `support_notify.WsHub.connect` (тот кладёт `query_string` пустым, а `support_notify.py` не правится:
  `ws_client` строит свой `scope`, берёт оттуда `WsClient`, `_application()` и приёмы `ws_run`) с путём `/ws/feed/` и
  строкой запроса из `query` в `query_string`), `layer_down()` (подмена слоя `publish` таймаутом), `layer_spy()` (шпион
  слоя `publish`: считает `group_send` по группам), `without_org()` (подмена `apps.is_installed("apps.org")` на время
  теста), `reload_asgi_without_feed()` (перезагрузка `config.asgi` с подменой `django.apps.apps.is_installed` и
  возвратом модуля после теста, решение 52), `capture_sql`, подмена «действие между выборкой и замком» (задание
  напоминаний, пачка ночного задания), подмена «запись удалена между проверкой видимости и вставкой `FeedComment`» в
  `feed.services.comments` (проверка отката — под `SET CONSTRAINTS ALL IMMEDIATE`, иначе внешний ключ в тесте
  проверяется только в конце) и подмена «отметка уже создана другим запросом между проверкой и вставкой» в
  `feed.services.likes` (записи и комментария), сбор картинок в памяти для эскизов (JPEG с EXIF, PNG с прозрачностью,
  GIF из нескольких кадров, картинка больше 40 Мп), `email_of`/`phone_of`, список страниц среза для проверок «тексты
  по-русски» и «без `style=`». Писатели T-7102… стартуют после неё — backend/tests/support_feed.py — (план: «Проверка» →
  «Серверные тесты»)
- [x] T-7102a [P] [sonnet] тесты видимость, аудитория, права действий (план: «Видимость и аудитория записи», «Модель
  данных» — `Recipient`, «Контракты» — `/feed/<id>/`; деление — решение 45) —
  backend/tests/test_feed_visibility.py::test_visibility_table_post_by_employee_parametrized_authors_and_addressees_only
  (FR-605, FR-606);
  backend/tests/test_feed_visibility.py::test_unit_newcomer_sees_earlier_post_and_transferred_employee_stops_seeing
  (FR-605);
  backend/tests/test_feed_visibility.py::test_unit_and_person_from_other_department_both_see_post_and_line_shows_unit_and_person
  (FR-603, FR-605);
  backend/tests/test_feed_visibility.py::test_deleted_unit_grants_nobody_while_person_and_author_still_see (FR-605,
  FR-607); backend/tests/test_feed_visibility.py::test_unit_with_addressed_post_is_deleted_without_refusal (FR-607);
  backend/tests/test_feed_visibility.py::test_moderator_not_addressee_gets_404_on_card_like_everyone (FR-604, FR-606);
  backend/tests/test_feed_visibility.py::test_moderator_mentioned_in_comment_then_sees_card_and_may_delete_post (FR-606,
  FR-611);
  backend/tests/test_feed_visibility.py::test_user_mentioned_in_comment_becomes_addressee_and_sees_card_with_all_comments
  (FR-604, FR-605, FR-611);
  backend/tests/test_feed_visibility.py::test_mention_in_post_text_adds_mention_recipient_and_grants_visibility (FR-605,
  FR-611); backend/tests/test_feed_visibility.py::test_viewer_computed_once_per_request_and_cached_on_request_user
  (FR-606);
  backend/tests/test_feed_visibility.py::test_viewer_chain_is_member_units_and_ancestors_from_org_unit_chain_ids
  (FR-605); backend/tests/test_feed_visibility.py::test_without_org_chain_is_empty_and_unit_recipients_grant_nothing
  (FR-605);
  backend/tests/test_feed_visibility.py::test_visible_posts_passes_chain_as_array_parameter_without_unit_ids_in_sql_text
  (FR-606); backend/tests/test_feed_visibility.py::test_get_post_raises_same_http404_for_invisible_and_missing_post
  (FR-606); backend/tests/test_feed_visibility.py::test_can_see_agrees_with_visible_posts_for_viewer_and_non_viewer
  (FR-606);
  backend/tests/test_feed_visibility.py::test_audience_to_all_is_every_active_employee_and_author_without_dismissed_or_blocked
  (FR-605);
  backend/tests/test_feed_visibility.py::test_audience_unions_subtree_members_person_recipients_and_author_then_drops_inactive
  (FR-605); backend/tests/test_feed_visibility.py::test_dismissed_or_blocked_viewer_gets_no_posts_from_visible_posts
  (FR-605, FR-606); backend/tests/test_feed_visibility.py::test_can_edit_post_only_author_not_moderator_or_addressee
  (FR-603, FR-620);
  backend/tests/test_feed_visibility.py::test_can_delete_post_author_or_moderator_who_sees_not_moderator_who_does_not
  (FR-603, FR-606, FR-621);
  backend/tests/test_feed_visibility.py::test_comment_edit_by_its_author_only_delete_by_author_or_moderator_who_sees
  (FR-603, FR-606, FR-622);
  backend/tests/test_feed_visibility.py::test_comment_like_and_answer_allowed_to_every_viewer_and_denied_to_non_viewer
  (FR-606) — (FR-603, FR-604, FR-605, FR-606, FR-607, FR-611, FR-620, FR-621, FR-622)
- [x] T-7102b [P] [sonnet] тесты строка адресатов и полный список адресатов (план: «Запись в ленте и карточка» — строка
  адресатов, «Контракты» — `/feed/<id>/to/`; деление — решение 45) —
  backend/tests/test_feed_visibility_3.py::test_recipients_line_shows_unit_deleted_for_removed_unit_and_keeps_person
  (FR-603, FR-607);
  backend/tests/test_feed_visibility_3.py::test_recipients_line_all_unit_names_people_once_and_dismissed_marked (FR-603,
  FR-607);
  backend/tests/test_feed_visibility_3.py::test_recipients_line_over_five_shows_first_five_and_more_four_counting_comment_mention
  (FR-603, FR-607, FR-611);
  backend/tests/test_feed_visibility_3.py::test_recipients_full_list_fragment_includes_comment_mention_unit_deleted_and_dismissed
  (FR-603, FR-607, FR-611);
  backend/tests/test_feed_visibility_3.py::test_recipients_full_list_returns_404_for_non_viewer (FR-604, FR-606) —
  (FR-603, FR-604, FR-606, FR-607, FR-611)
- [x] T-7103 [P] [sonnet] тесты одна функция видимости во всех местах (план: «Видимость и аудитория записи» — перечень
  мест, «Контракты») — backend/tests/test_feed_visibility_2.py::test_invisible_post_absent_from_first_feed_page
  (FR-606); backend/tests/test_feed_visibility_2.py::test_invisible_post_absent_from_more_posts (FR-606);
  backend/tests/test_feed_visibility_2.py::test_invisible_post_absent_under_important_filter (FR-606);
  backend/tests/test_feed_visibility_2.py::test_invisible_post_absent_under_events_filter (FR-606);
  backend/tests/test_feed_visibility_2.py::test_mine_filter_excludes_post_of_other_author_where_i_am_addressee (FR-635);
  backend/tests/test_feed_visibility_2.py::test_mentions_filter_excludes_post_where_i_am_addressee_via_to_but_not_mentioned
  (FR-635); backend/tests/test_feed_visibility_2.py::test_invisible_post_absent_under_author_filter (FR-606);
  backend/tests/test_feed_visibility_2.py::test_invisible_post_absent_under_period_filter (FR-606);
  backend/tests/test_feed_visibility_2.py::test_invisible_post_card_returns_404_like_missing (FR-604, FR-606);
  backend/tests/test_feed_visibility_2.py::test_invisible_post_and_its_comments_absent_from_search_without_count
  (FR-606, FR-636); backend/tests/test_feed_visibility_2.py::test_file_of_invisible_post_returns_404_like_missing_file
  (FR-606, FR-634); backend/tests/test_feed_visibility_2.py::test_thumb_of_invisible_post_returns_404_like_missing_file
  (FR-606, FR-634); backend/tests/test_feed_visibility_2.py::test_recipients_list_of_invisible_post_returns_404
  (FR-606); backend/tests/test_feed_visibility_2.py::test_post_likers_list_of_invisible_post_returns_404 (FR-606);
  backend/tests/test_feed_visibility_2.py::test_comment_likers_list_of_invisible_post_returns_404 (FR-606);
  backend/tests/test_feed_visibility_2.py::test_reads_list_of_invisible_post_returns_404 (FR-606);
  backend/tests/test_feed_visibility_2.py::test_answers_list_of_invisible_post_returns_404 (FR-606);
  backend/tests/test_feed_visibility_2.py::test_comments_list_of_invisible_post_returns_404 (FR-606);
  backend/tests/test_feed_visibility_2.py::test_still_relevant_false_for_transferred_out_recipient_so_mail_not_sent
  (FR-606, FR-630); backend/tests/test_feed_visibility_2.py::test_live_broadcast_sends_no_frame_about_invisible_post
  (FR-606, FR-628); backend/tests/test_feed_visibility_2.py::test_feed_counter_does_not_grow_for_invisible_post (FR-606,
  FR-628); backend/tests/test_feed_visibility_2.py::test_read_answer_and_like_on_invisible_post_return_404 (FR-606);
  backend/tests/test_feed_visibility_2.py::test_new_comment_edit_and_delete_on_invisible_post_return_404 (FR-606);
  backend/tests/test_feed_visibility_2.py::test_edit_delete_and_like_of_comment_on_invisible_post_return_404 (FR-606);
  backend/tests/test_feed_visibility_2.py::test_invisible_post_response_same_code_page_and_not_found_text_as_missing
  (FR-604, FR-606) — (FR-604, FR-606, FR-628, FR-630, FR-634, FR-635, FR-636)
- [x] T-7104 [P] [sonnet] тесты главная, меню, узел числа (план: «Главная, меню и число у „Ленты“», «Точки расширения
  ядра и шина событий» — `menu_items`, `home_body`, «Модуль и выключение») —
  backend/tests/test_feed_home.py::test_home_body_order_notices_form_filters_empty_banner_important_block_feed (FR-601);
  backend/tests/test_feed_home.py::test_home_has_no_greeting_and_no_profile_or_security_cards (FR-601);
  backend/tests/test_feed_home.py::test_home_notices_block_shows_list_record_deadline_notice_above_post_form (FR-601);
  backend/tests/test_feed_home.py::test_without_feed_home_is_previous_page_with_same_notices_block (FR-641);
  backend/tests/test_feed_home.py::test_menu_feed_item_first_leads_to_root_and_home_item_absent (FR-601);
  backend/tests/test_feed_home.py::test_without_feed_menu_has_home_item_first_and_no_feed_item (FR-641);
  backend/tests/test_feed_home.py::test_feed_menu_entry_order_0_empty_permissions_badge_unread_count_live_badge_feed
  (FR-601, FR-626); backend/tests/test_feed_home.py::test_feed_menu_item_visible_to_employee_without_roles (FR-601);
  backend/tests/test_feed_home.py::test_feed_badge_node_present_at_zero_hidden_with_data_count_and_live_marker_without_data_menu_badge
  (FR-626); backend/tests/test_feed_home.py::test_feed_badge_shows_99_plus_at_120_and_100_and_digits_at_99 (FR-626);
  backend/tests/test_feed_home.py::test_other_menu_items_keep_data_menu_badge_only_above_zero_in_digits (FR-626,
  FR-641); backend/tests/test_feed_home.py::test_home_has_feed_live_node_with_ws_connect_and_data_opened (FR-601,
  FR-627); backend/tests/test_feed_home.py::test_home_has_two_ws_connect_nodes_bell_and_feed_live (FR-627);
  backend/tests/test_feed_home.py::test_anonymous_home_redirects_to_login_with_next_and_shows_no_feed (FR-601);
  backend/tests/test_feed_home.py::test_user_without_second_factor_home_redirects_to_factor_setup (FR-601) — (FR-601,
  FR-626, FR-627, FR-641)
- [x] T-7105 [P] [sonnet] тесты лента, курсор, фильтры, белый список (план: «Лента, курсор, блок важных, фильтры» —
  фильтр, курсор, ветки, «Непрочитанное» — показы по `/feed/more/`, «Контракты» — `/`, `/feed/more/`) —
  backend/tests/test_feed_page.py::test_45_posts_paginate_20_20_5_and_more_button_disappears (FR-602);
  backend/tests/test_feed_page.py::test_cursor_paginates_100_posts_with_same_published_at_without_loss_or_repeat
  (FR-602); backend/tests/test_feed_page.py::test_post_published_after_opened_not_returned_by_more (FR-602);
  backend/tests/test_feed_page.py::test_invalid_before_or_opened_returns_first_page_not_500 (FR-602, FR-635);
  backend/tests/test_feed_page.py::test_feed_without_addressed_posts_says_no_posts_yet (FR-602);
  backend/tests/test_feed_page.py::test_empty_filter_result_says_no_posts_by_filter (FR-635);
  backend/tests/test_feed_page.py::test_default_filter_all_shows_visible_posts_newest_first (FR-602, FR-635);
  backend/tests/test_feed_page.py::test_important_filter_shows_only_important_including_expired (FR-635);
  backend/tests/test_feed_page.py::test_events_filter_shows_only_events (FR-635);
  backend/tests/test_feed_page.py::test_mine_filter_shows_only_own_posts (FR-635);
  backend/tests/test_feed_page.py::test_mentions_filter_finds_mention_of_to_addressee_and_mention_in_comment (FR-635);
  backend/tests/test_feed_page.py::test_author_filter_shows_only_selected_author_posts (FR-635);
  backend/tests/test_feed_page.py::test_period_filter_is_inclusive_by_moscow_date_with_clock_at_utc_midnight (FR-635);
  backend/tests/test_feed_page.py::test_filters_combine_by_and_author_with_period_and_kind_with_period (FR-635);
  backend/tests/test_feed_page.py::test_more_applies_same_filter_as_first_page (FR-602, FR-635);
  backend/tests/test_feed_page.py::test_unknown_filter_key_bad_date_and_bad_author_ignored_with_200 (FR-635, NFR-608);
  backend/tests/test_feed_page.py::test_filter_and_cursor_values_are_sql_parameters_not_sql_text (NFR-608);
  backend/tests/test_feed_page.py::test_more_link_and_ws_connect_built_from_parsed_values_without_foreign_key (FR-635,
  NFR-608); backend/tests/test_feed_page.py::test_filter_form_uses_get_and_shows_selected_values (FR-635);
  backend/tests/test_feed_page.py::test_more_without_hx_request_writes_no_shown_and_has_no_badge_node (FR-626);
  backend/tests/test_feed_page.py::test_more_with_hx_request_writes_shown_and_returns_badge_oob (FR-626) — (FR-602,
  FR-626, FR-635, NFR-608)
- [x] T-7106 [P] [sonnet] тесты блок важных, состав записи, сборка без N+1 (план: «Лента, курсор, блок важных, фильтры»
  — блок важных, сборка карточек, «Запись в ленте и карточка» — состав) —
  backend/tests/test_feed_page_2.py::test_important_block_shown_only_for_all_and_important_without_author_or_period
  (FR-602, FR-635);
  backend/tests/test_feed_page_2.py::test_important_block_absent_for_events_mine_mentions_and_with_author_or_period
  (FR-602, FR-635);
  backend/tests/test_feed_page_2.py::test_important_block_holds_visible_unexpired_unread_others_important_with_read_button
  (FR-602, FR-614);
  backend/tests/test_feed_page_2.py::test_read_important_leaves_block_and_stands_in_feed_by_time_without_button
  (FR-614);
  backend/tests/test_feed_page_2.py::test_expired_important_not_in_block_stands_in_feed_as_regular_without_reminder
  (FR-602, FR-614); backend/tests/test_feed_page_2.py::test_own_important_not_in_block_and_stands_in_feed_by_time
  (FR-602, FR-614);
  backend/tests/test_feed_page_2.py::test_block_posts_not_repeated_in_feed_and_not_counted_in_page_of_20 (FR-602);
  backend/tests/test_feed_page_2.py::test_more_and_new_exclude_block_posts_by_sql_condition_without_ids_in_url (FR-602);
  backend/tests/test_feed_page_2.py::test_mentioned_unread_important_in_feed_by_time_under_mentions_and_only_in_block_under_all
  (FR-602, FR-635); backend/tests/test_feed_page_2.py::test_block_shown_with_empty_feed_prints_no_empty_text (FR-602);
  backend/tests/test_feed_page_2.py::test_page_query_count_equal_for_1_and_20_fully_populated_posts (NFR-601);
  backend/tests/test_feed_page_2.py::test_card_data_loaded_by_post_ids_array_parameter (NFR-601);
  backend/tests/test_feed_page_2.py::test_post_shows_author_photo_arrow_recipients_and_published_time (FR-603);
  backend/tests/test_feed_page_2.py::test_author_name_links_to_staff_card_only_for_staff_view_or_accounts_manage
  (FR-603); backend/tests/test_feed_page_2.py::test_dismissed_author_shown_with_dismissed_mark (FR-603);
  backend/tests/test_feed_page_2.py::test_edited_post_shows_edited_with_time_and_unedited_does_not (FR-603, FR-620);
  backend/tests/test_feed_page_2.py::test_post_parts_have_stable_ids_and_data_post_id (FR-603);
  backend/tests/test_feed_page_2.py::test_edit_delete_menu_none_for_reader_both_for_author_delete_only_for_moderator_who_sees
  (FR-603); backend/tests/test_feed_page_2.py::test_feed_shows_last_three_comments_and_show_all_count (FR-603) —
  (FR-602, FR-603, FR-614, FR-620, FR-635, NFR-601)
- [x] T-7107 [P] [sonnet] тесты форма, «Кому», публикация (план: «Публикация: форма, „Кому“, подсказки» — форма, «Кому»,
  публикация; «Текст и упоминания» — хранение, NUL; «Тексты отказов»; «Контракты» — `/feed/posts/`) —
  backend/tests/test_feed_posts.py::test_form_default_kind_is_post_with_three_kinds_and_fields_of_all_kinds_in_markup
  (FR-608); backend/tests/test_feed_posts.py::test_form_preselects_all_for_employee_with_post_all (FR-608, FR-610);
  backend/tests/test_feed_posts.py::test_form_without_post_all_has_no_all_option_and_offers_units_and_people (FR-610,
  FR-640); backend/tests/test_feed_posts.py::test_publish_with_to_all_without_post_all_rejected_with_reason_and_no_post
  (FR-610, FR-640, FR-642); backend/tests/test_feed_posts.py::test_server_takes_only_fields_of_selected_kind (FR-608);
  backend/tests/test_feed_posts.py::test_empty_and_whitespace_only_text_rejected_write_text_at_field_input_kept (FR-609,
  FR-642); backend/tests/test_feed_posts.py::test_text_of_10000_chars_accepted_and_10001_rejected_with_limit_at_field
  (FR-609, FR-642); backend/tests/test_feed_posts.py::test_publish_without_recipient_rejected_choose_recipient_at_field
  (FR-610, FR-642); backend/tests/test_feed_posts.py::test_50_recipients_accepted_51_rejected_unit_and_all_count_as_one
  (FR-610, FR-642); backend/tests/test_feed_posts.py::test_mentioned_people_not_counted_in_50_recipient_limit (FR-610);
  backend/tests/test_feed_posts.py::test_nonexistent_unit_dismissed_or_blocked_person_rejected_as_recipient (FR-610);
  backend/tests/test_feed_posts.py::test_invited_employee_accepted_as_recipient (FR-610);
  backend/tests/test_feed_posts.py::test_employee_without_roles_publishes_to_unit_and_people_and_sees_no_all_option
  (FR-608, FR-610, FR-640);
  backend/tests/test_feed_posts.py::test_htmx_refusal_returns_200_form_fragment_with_reason_and_entered_values (FR-642);
  backend/tests/test_feed_posts.py::test_publish_creates_post_to_rows_mention_rows_file_binding_and_vector (FR-608,
  FR-610); backend/tests/test_feed_posts.py::test_dispatch_create_error_rolls_back_post_recipients_and_file_binding
  (FR-608); backend/tests/test_feed_posts.py::test_broadcast_runs_only_after_commit (FR-608);
  backend/tests/test_feed_posts.py::test_htmx_publish_returns_cleared_form_and_own_post_on_top_with_author_to_all_and_time
  (FR-608, FR-610); backend/tests/test_feed_posts.py::test_plain_post_publish_redirects_to_home (FR-608);
  backend/tests/test_feed_posts.py::test_nul_removed_from_text_event_title_and_place (FR-609);
  backend/tests/test_feed_posts.py::test_recipient_published_at_copies_post_published_at (FR-608) — (FR-608, FR-609,
  FR-610, FR-640, FR-642)
- [x] T-7108 [P] [sonnet] тесты подсказка «Кому» и «Автор», карточка записи (план: «Публикация: форма, „Кому“,
  подсказки» — подсказка; «Запись в ленте и карточка» — карточка; «Точки расширения ядра и шина событий» —
  `object.viewed`; «Контракты» — `/feed/pick/`, `/feed/<id>/`) —
  backend/tests/test_feed_posts_2.py::test_pick_open_to_every_logged_in_employee_and_redirects_anonymous_to_login
  (FR-610); backend/tests/test_feed_posts_2.py::test_pick_to_rows_show_name_and_unit_without_position_email_and_phone
  (FR-610); backend/tests/test_feed_posts_2.py::test_pick_to_finds_employee_by_name_part_ignoring_yo (FR-610);
  backend/tests/test_feed_posts_2.py::test_pick_to_finds_unit_by_name_part_and_path_part_and_shows_path (FR-610);
  backend/tests/test_feed_posts_2.py::test_pick_to_excludes_dismissed_and_blocked_and_includes_invited (FR-610);
  backend/tests/test_feed_posts_2.py::test_pick_author_includes_active_and_dismissed_with_full_name_row (FR-635);
  backend/tests/test_feed_posts_2.py::test_pick_returns_at_most_20_rows_for_to_and_author (FR-610, FR-635);
  backend/tests/test_feed_posts_2.py::test_pick_query_shorter_than_two_chars_returns_empty (FR-610);
  backend/tests/test_feed_posts_2.py::test_pick_query_passed_as_sql_parameter (FR-610, FR-635);
  backend/tests/test_feed_posts_2.py::test_pick_returns_htmx_fragment (FR-610);
  backend/tests/test_feed_posts_2.py::test_card_shows_post_with_all_comments_and_comment_anchors (FR-604);
  backend/tests/test_feed_posts_2.py::test_card_has_ws_node_with_post_query (FR-604);
  backend/tests/test_feed_posts_2.py::test_card_publishes_object_viewed_for_post_and_each_own_comment (FR-604, FR-630);
  backend/tests/test_feed_posts_2.py::test_card_for_non_viewer_same_404_as_nonexistent (FR-604);
  backend/tests/test_feed_posts_2.py::test_literal_paths_not_confused_with_post_id_route (FR-604) — (FR-604, FR-610,
  FR-630, FR-635)
- [x] T-7109 [P] [sonnet] тесты вывод текста и безопасный вывод на странице (план: «Текст и упоминания» — вывод,
  отрывок; «Безопасный вывод, язык, узкий экран» — проба NFR-605) —
  backend/tests/test_feed_text.py::test_render_plain_evil_inputs_leave_only_allowed_tags_and_attributes (FR-609,
  NFR-605); backend/tests/test_feed_text.py::test_https_url_becomes_link_with_blank_target_and_noopener_noreferrer
  (FR-609, NFR-605); backend/tests/test_feed_text.py::test_mailto_becomes_link_and_ftp_and_javascript_stay_text (FR-609,
  NFR-605); backend/tests/test_feed_text.py::test_html_markup_in_text_shown_escaped (FR-609, NFR-605);
  backend/tests/test_feed_text.py::test_brackets_and_trailing_punctuation_left_outside_link (FR-609);
  backend/tests/test_feed_text.py::test_link_longer_than_2048_rendered_as_text (FR-609, NFR-605);
  backend/tests/test_feed_text.py::test_control_and_bidi_characters_removed_tab_newline_cr_kept (FR-609, NFR-605);
  backend/tests/test_feed_text.py::test_paragraphs_become_p_and_single_newline_becomes_br (FR-609);
  backend/tests/test_feed_text.py::test_mention_marker_renders_staff_link_with_data_mention_for_staff_viewer (FR-611);
  backend/tests/test_feed_text.py::test_mention_marker_renders_span_for_reader_without_staff_view (FR-611);
  backend/tests/test_feed_text.py::test_mention_name_with_markup_escaped_in_link_text (FR-611, NFR-605);
  backend/tests/test_feed_text.py::test_unknown_mention_id_rendered_as_text (FR-611);
  backend/tests/test_feed_text.py::test_snippet_replaces_marker_with_at_name_collapses_spaces_without_markup (FR-609,
  FR-611); backend/tests/test_feed_text.py::test_snippet_cuts_by_word_with_ellipsis_at_100_60_and_300 (FR-609);
  backend/tests/test_feed_text.py::test_page_escapes_script_markup_javascript_and_attribute_break_in_text_title_place_and_file_name
  (NFR-605); backend/tests/test_feed_text.py::test_page_builds_links_only_from_http_https_and_mailto (FR-609, NFR-605) —
  (FR-609, FR-611, NFR-605)
- [x] T-7110 [P] [sonnet] тесты упоминания (план: «Текст и упоминания» — упоминания при сохранении, в форме, в
  комментарии; «Модель данных» — упоминания строками `via='mention'`; «Публикация: форма, „Кому“, подсказки» — подсказка
  `scope=mention`) —
  backend/tests/test_feed_mentions.py::test_pick_mention_returns_only_active_employees_without_dismissed_and_units
  (FR-611);
  backend/tests/test_feed_mentions.py::test_edit_form_without_js_returns_saved_markers_and_id_to_name_map_in_data_attribute
  (FR-611, FR-620); backend/tests/test_feed_mentions.py::test_post_with_21_distinct_mentions_rejected_with_reason
  (FR-611, FR-642); backend/tests/test_feed_mentions.py::test_comment_with_21_distinct_mentions_rejected_with_reason
  (FR-611, FR-642); backend/tests/test_feed_mentions.py::test_repeated_mention_of_same_employee_does_not_consume_limit
  (FR-611);
  backend/tests/test_feed_mentions.py::test_mentioned_in_post_gets_mention_row_and_sees_post_with_name_link_to_card
  (FR-605, FR-611); backend/tests/test_feed_mentions.py::test_mentioned_already_in_to_gets_separate_mention_row
  (FR-611);
  backend/tests/test_feed_mentions.py::test_mentioned_in_comment_becomes_post_recipient_and_sees_card_with_all_comments
  (FR-605, FR-611); backend/tests/test_feed_mentions.py::test_deleting_comment_keeps_mentioned_as_recipient (FR-611,
  FR-622); backend/tests/test_feed_mentions.py::test_removing_mention_on_edit_keeps_recipient (FR-611, FR-620);
  backend/tests/test_feed_mentions.py::test_mentions_me_filter_finds_mention_of_to_recipient (FR-611, FR-635);
  backend/tests/test_feed_mentions.py::test_marker_of_dismissed_blocked_or_nonexistent_employee_stays_text_and_adds_no_recipient
  (FR-611); backend/tests/test_feed_mentions.py::test_hand_typed_marker_equals_picked_employee (FR-611);
  backend/tests/test_feed_mentions.py::test_only_id_absent_from_previous_version_of_text_is_new_mention_on_edit (FR-611,
  FR-620) — (FR-605, FR-611, FR-620, FR-622, FR-635, FR-642)
- [x] T-7111 [P] [sonnet] тесты предупреждение о ПДн (план: «Предупреждение о ПДн»; «Контракты» — `/feed/posts/`,
  `/feed/<id>/edit/`, `/feed/<id>/comments/`, `/feed/comments/<cid>/edit/`) —
  backend/tests/test_feed_pdn.py::test_email_and_phone_in_post_text_show_warning_with_found_list_and_no_post (FR-612);
  backend/tests/test_feed_pdn.py::test_warning_has_fix_and_publish_anyway_with_confirm_field (FR-612);
  backend/tests/test_feed_pdn.py::test_found_items_in_warning_are_escaped (FR-612);
  backend/tests/test_feed_pdn.py::test_pdn_in_event_title_or_place_shows_warning (FR-612);
  backend/tests/test_feed_pdn.py::test_fix_keeps_entered_values_in_form_and_creates_no_post (FR-612);
  backend/tests/test_feed_pdn.py::test_pdn_confirmed_publishes_post (FR-612);
  backend/tests/test_feed_pdn.py::test_pdn_in_comment_shows_warning_and_confirmed_saves_comment (FR-612);
  backend/tests/test_feed_pdn.py::test_pdn_on_post_edit_shows_save_anyway_and_confirmed_saves_edit (FR-612);
  backend/tests/test_feed_pdn.py::test_pdn_on_comment_edit_shows_warning_and_confirmed_saves_edit (FR-612);
  backend/tests/test_feed_pdn.py::test_found_list_without_duplicates_and_at_most_20_items (FR-612);
  backend/tests/test_feed_pdn.py::test_address_in_backticks_and_markdown_still_found (FR-612);
  backend/tests/test_feed_pdn.py::test_htmx_warning_returns_200_fragment (FR-612);
  backend/tests/test_feed_pdn.py::test_text_without_email_or_phone_publishes_without_warning (FR-612) — (FR-612)
- [x] T-7112 [P] [sonnet] тесты важное: сроки, «Прочитано», «Прочитали N из M» (план: «Важное», «Модель данных» — срок
  важного и проверка `kind`, «Контракты» — `/feed/<id>/read/`, `/feed/<id>/reads/`) —
  backend/tests/test_feed_important.py::test_day_term_published_10_10_at_15_ends_at_12_10_moscow_midnight (FR-613);
  backend/tests/test_feed_important.py::test_term_counts_from_moscow_date_when_clock_is_at_utc_midnight (FR-613,
  NFR-611); backend/tests/test_feed_important.py::test_week_term_ends_at_moscow_midnight_after_day_plus_7 (FR-613);
  backend/tests/test_feed_important.py::test_month_term_from_january_31_ends_after_february_28_or_29 (FR-613);
  backend/tests/test_feed_important.py::test_until_date_term_ends_at_moscow_midnight_after_given_date (FR-613);
  backend/tests/test_feed_important.py::test_term_choices_are_day_week_month_and_until_date (FR-613);
  backend/tests/test_feed_important.py::test_until_date_yesterday_or_today_is_refused_with_date_already_passed_at_term_field
  (FR-613, FR-642);
  backend/tests/test_feed_important.py::test_until_date_in_13_months_is_refused_with_not_later_than_year_and_tomorrow_and_one_year_are_accepted
  (FR-613, FR-642);
  backend/tests/test_feed_important.py::test_term_change_by_edit_to_past_date_or_13_months_is_refused_with_same_reasons
  (FR-613, FR-620, FR-642);
  backend/tests/test_feed_important.py::test_read_by_addressee_creates_read_mark_and_returns_post_fragment_without_read_button
  (FR-614);
  backend/tests/test_feed_important.py::test_read_post_leaves_important_block_and_stands_in_feed_by_publication_time
  (FR-614); backend/tests/test_feed_important.py::test_repeated_read_is_not_an_error_keeps_one_read_mark_and_has_no_undo
  (FR-614); backend/tests/test_feed_important.py::test_read_by_author_is_403_with_reason_and_author_sees_no_read_button
  (FR-614); backend/tests/test_feed_important.py::test_read_after_term_expired_is_403_with_reason (FR-613, FR-614);
  backend/tests/test_feed_important.py::test_expired_important_is_ordinary_post_with_was_important_and_read_count_without_button_and_block
  (FR-613, FR-614);
  backend/tests/test_feed_important.py::test_expired_important_creates_no_unread_reminders_after_reminder_and_night_jobs
  (FR-613);
  backend/tests/test_feed_important.py::test_making_expired_post_important_again_by_edit_sets_term_from_edit_date_keeps_read_marks_without_notifications
  (FR-613, FR-620);
  backend/tests/test_feed_important.py::test_editing_only_text_or_files_keeps_important_until_and_skips_date_passed_check
  (FR-620); backend/tests/test_feed_important.py::test_edit_form_shows_current_term_as_until_date_with_saved_date
  (FR-620); backend/tests/test_feed_important.py::test_author_sees_read_n_of_m_where_m_is_audience_without_author
  (FR-615);
  backend/tests/test_feed_important.py::test_fired_and_blocked_addressees_are_outside_n_m_and_lists_m_is_37_of_40
  (FR-605, FR-615); backend/tests/test_feed_important.py::test_ordinary_addressee_sees_only_read_n (FR-615);
  backend/tests/test_feed_important.py::test_reads_list_shows_read_with_time_and_unread_to_author_and_moderator_addressee
  (FR-615);
  backend/tests/test_feed_important.py::test_reads_list_is_403_to_other_viewers_and_404_to_moderator_not_addressee
  (FR-615); backend/tests/test_feed_important.py::test_db_check_ties_kind_important_to_non_empty_important_until
  (FR-613) — (FR-605, FR-613, FR-614, FR-615, FR-620, FR-642, NFR-611)
- [x] T-7113 [P] [sonnet] тесты событие: поля, ответы, списки, запреты правки (план: «Событие и напоминания» — поля,
  ответы, правка события, «Модель данных» — проверка полей события, «Контракты» — `/feed/<id>/answer/`,
  `/feed/<id>/answers/`) —
  backend/tests/test_feed_events.py::test_event_with_title_start_end_place_is_published_with_event_block_and_answer_buttons_for_participant
  (FR-616, FR-617); backend/tests/test_feed_events.py::test_event_block_has_no_answer_buttons_for_author (FR-617);
  backend/tests/test_feed_events.py::test_empty_event_title_is_refused_with_enter_event_title (FR-616, FR-642);
  backend/tests/test_feed_events.py::test_event_title_of_200_chars_is_accepted_and_201_refused_with_limit_200 (FR-616,
  FR-642); backend/tests/test_feed_events.py::test_empty_event_place_is_refused_with_enter_event_place (FR-616, FR-642);
  backend/tests/test_feed_events.py::test_event_place_of_200_chars_is_accepted_and_201_refused_with_limit_200 (FR-616,
  FR-642); backend/tests/test_feed_events.py::test_missing_event_start_or_end_is_refused_with_reason_at_field (FR-616);
  backend/tests/test_feed_events.py::test_event_start_and_end_are_taken_and_shown_in_moscow_time (FR-616);
  backend/tests/test_feed_events.py::test_event_end_equal_to_or_before_start_is_refused_with_end_after_start (FR-616,
  FR-642); backend/tests/test_feed_events.py::test_event_start_in_past_is_refused_with_start_already_passed (FR-616,
  FR-642); backend/tests/test_feed_events.py::test_event_without_text_is_published (FR-616);
  backend/tests/test_feed_events.py::test_participant_answers_go_then_changes_to_no_before_start_and_gets_event_block_fragment
  (FR-617);
  backend/tests/test_feed_events.py::test_answer_after_start_is_refused_with_answers_closed_and_buttons_are_gone
  (FR-617, FR-642); backend/tests/test_feed_events.py::test_answer_by_author_is_403 (FR-617);
  backend/tests/test_feed_events.py::test_go_and_no_counts_are_shown_to_every_viewer (FR-617);
  backend/tests/test_feed_events.py::test_answers_lists_go_no_and_not_answered_are_open_to_author (FR-617);
  backend/tests/test_feed_events.py::test_answers_lists_are_403_to_moderator_participant_and_other_viewers_who_see_counts_only
  (FR-617); backend/tests/test_feed_events.py::test_counts_and_lists_ignore_answers_of_fired_blocked_and_left_audience
  (FR-616, FR-617); backend/tests/test_feed_events.py::test_not_answered_list_excludes_fired_and_blocked_participants
  (FR-617);
  backend/tests/test_feed_events.py::test_edit_of_started_event_refuses_start_end_and_place_change_with_event_started
  (FR-619, FR-642);
  backend/tests/test_feed_events.py::test_edit_of_started_event_changes_title_and_description_without_notifications
  (FR-619); backend/tests/test_feed_events.py::test_edit_moving_start_to_past_is_refused_with_start_already_passed
  (FR-619, FR-642); backend/tests/test_feed_events.py::test_answers_are_kept_after_event_edit (FR-617, FR-619);
  backend/tests/test_feed_events.py::test_db_check_ties_kind_event_to_filled_event_fields_and_end_after_start (FR-616) —
  (FR-616, FR-617, FR-619, FR-642)
- [x] T-7114 [P] [sonnet] тесты `remind_at` и задание напоминаний (план: «Событие и напоминания» — `remind_at`, пересчёт
  при правке, задание `feed_reminders`, правило простоя) —
  backend/tests/test_feed_reminders.py::test_remind_at_on_publish_is_start_minus_hour_when_start_is_hour_or_more_ahead
  (FR-618);
  backend/tests/test_feed_reminders.py::test_event_published_30_minutes_before_start_has_no_remind_at_and_gets_no_reminder
  (FR-618);
  backend/tests/test_feed_reminders.py::test_event_next_day_gets_one_event_reminder_in_minute_of_remind_at_and_none_before
  (FR-618); backend/tests/test_feed_reminders.py::test_reminder_goes_to_audience_minus_answered_no_plus_author_always
  (FR-618); backend/tests/test_feed_reminders.py::test_employee_not_seeing_event_gets_no_reminder (FR-606, FR-618);
  backend/tests/test_feed_reminders.py::test_start_moved_to_14_sets_remind_at_13_and_reminder_comes_at_13_not_9 (FR-618,
  FR-619);
  backend/tests/test_feed_reminders.py::test_reminded_event_moved_two_hours_later_gets_second_reminder_hour_before_new_start
  (FR-619); backend/tests/test_feed_reminders.py::test_reminded_event_moved_30_minutes_later_gets_no_second_reminder
  (FR-619); backend/tests/test_feed_reminders.py::test_new_start_closer_than_hour_clears_remind_at (FR-618, FR-619);
  backend/tests/test_feed_reminders.py::test_editing_only_event_title_or_description_keeps_remind_at_and_creates_no_notifications
  (FR-619);
  backend/tests/test_feed_reminders.py::test_reminder_notification_and_reminded_mark_are_committed_together_or_not_at_all
  (FR-618, NFR-610);
  backend/tests/test_feed_reminders.py::test_reminder_selection_sql_takes_one_due_unreminded_future_event_for_update_skip_locked
  (FR-618, NFR-610); backend/tests/test_feed_reminders.py::test_two_reminder_runs_in_a_row_create_one_notification
  (NFR-610);
  backend/tests/test_feed_reminders.py::test_repeated_reminder_run_with_nothing_due_does_nothing_without_error
  (NFR-610); backend/tests/test_feed_reminders.py::test_event_deleted_after_selection_is_skipped_without_error
  (NFR-610);
  backend/tests/test_feed_reminders.py::test_failing_event_is_logged_by_post_id_without_text_other_reminders_are_sent_and_job_does_not_fail
  (FR-618, NFR-610);
  backend/tests/test_feed_reminders.py::test_failing_event_id_is_excluded_from_selection_as_sql_parameter_until_end_of_run
  (FR-618); backend/tests/test_feed_reminders.py::test_event_started_while_job_was_idle_gets_no_reminder (FR-618);
  backend/tests/test_feed_reminders.py::test_reschedule_exactly_one_hour_later_sends_no_second_reminder (FR-619);
  backend/tests/test_feed_reminders.py::test_one_run_reminds_at_most_200_events_and_next_run_takes_the_rest (FR-618) —
  (FR-606, FR-618, FR-619, NFR-610)
- [x] T-7115 [P] [sonnet] тесты ночного задания срока хранения (план: «Срок хранения и ночное задание» — граница, три
  шага, журнал, «Непрочитанное» — чистка показов, «Файлы и эскизы» — непривязанные старше суток) —
  backend/tests/test_feed_retention.py::test_post_older_than_term_by_one_day_is_deleted_with_comments_likes_of_post_and_comments_read_marks_answers_shown_and_recipients
  (FR-621, FR-638);
  backend/tests/test_feed_retention.py::test_retention_deletes_post_and_comment_files_of_all_scan_states_with_stored_files_and_disk_and_thumbs_after_commit
  (FR-621, FR-638); backend/tests/test_feed_retention.py::test_post_one_day_younger_than_term_is_kept (FR-638);
  backend/tests/test_feed_retention.py::test_term_boundary_replaces_year_and_february_29_becomes_february_28 (FR-638);
  backend/tests/test_feed_retention.py::test_retention_uses_years_from_feed_settings (FR-638);
  backend/tests/test_feed_retention.py::test_edit_and_new_comments_do_not_extend_post_term (FR-638);
  backend/tests/test_feed_retention.py::test_posts_of_fired_employees_are_deleted_by_same_term (FR-638);
  backend/tests/test_feed_retention.py::test_retention_writes_one_journal_record_retention_purged_with_posts_count_and_no_text
  (FR-639); backend/tests/test_feed_retention.py::test_retention_without_old_posts_writes_no_journal_record (FR-639,
  NFR-610);
  backend/tests/test_feed_retention.py::test_repeated_retention_run_deletes_nothing_writes_no_journal_and_raises_no_error
  (FR-638, FR-639, NFR-610);
  backend/tests/test_feed_retention.py::test_2500_old_posts_are_deleted_in_three_batches_of_1000_by_batch_spy_and_limit_1000_selects_and_journal_posts_is_2500
  (FR-638);
  backend/tests/test_feed_retention.py::test_post_deleted_between_batch_selection_and_delete_is_skipped_without_error_and_not_counted_in_journal_posts
  (NFR-610);
  backend/tests/test_feed_retention.py::test_shown_rows_of_posts_published_over_31_days_ago_are_deleted_and_younger_kept_by_post_published_at
  (FR-626, FR-638);
  backend/tests/test_feed_retention.py::test_unattached_feed_files_older_than_24_hours_are_deleted_with_stored_file_and_disk_and_younger_kept
  (FR-633, FR-638);
  backend/tests/test_feed_retention.py::test_portal_notification_of_post_deleted_by_term_remains_and_its_link_is_404
  (FR-632); backend/tests/test_feed_retention.py::test_retention_job_runs_no_vacuum (FR-638);
  backend/tests/test_feed_retention.py::test_retention_steps_run_in_order_shown_cleanup_then_post_batches_then_unattached_files_by_sql_order
  (FR-626, FR-633, FR-638) — (FR-621, FR-626, FR-632, FR-633, FR-638, FR-639, NFR-610)
- [x] T-7116 [P] [sonnet] тесты настройки срока хранения (план: «Срок хранения и ночное задание» — настройка, «Точки
  расширения ядра и шина событий» — `menu_items` «Настройки ленты», «Контракты» — `/settings/feed/`) —
  backend/tests/test_feed_settings.py::test_settings_feed_page_has_portal_settings_feed_title_and_retention_years_field_for_settings_portal
  (FR-638);
  backend/tests/test_feed_settings.py::test_settings_feed_without_settings_portal_is_403_on_get_and_post_without_calling_settings_service
  (FR-638); backend/tests/test_feed_settings.py::test_new_install_shows_retention_3_from_migration_row (FR-638);
  backend/tests/test_feed_settings.py::test_feed_settings_get_creates_row_with_3_when_missing (FR-638);
  backend/tests/test_feed_settings.py::test_retention_0_11_and_not_a_number_are_refused_with_from_1_to_10_years_and_value_is_unchanged
  (FR-638, FR-642); backend/tests/test_feed_settings.py::test_retention_1_with_confirmation_and_10_are_accepted
  (FR-638);
  backend/tests/test_feed_settings.py::test_decrease_from_3_to_1_shows_second_step_with_count_of_posts_before_new_boundary_and_confirm_button
  (FR-638); backend/tests/test_feed_settings.py::test_decrease_without_confirmation_keeps_value_and_writes_no_journal
  (FR-638);
  backend/tests/test_feed_settings.py::test_decrease_with_confirmation_saves_value_and_writes_retention_changed_with_years_before_and_after
  (FR-638, FR-639);
  backend/tests/test_feed_settings.py::test_increase_is_saved_at_once_without_second_step_and_journaled (FR-638,
  FR-639);
  backend/tests/test_feed_settings.py::test_menu_item_feed_settings_has_url_order_63_and_gear_icon_for_settings_portal
  (FR-638); backend/tests/test_feed_settings.py::test_menu_item_feed_settings_is_absent_without_settings_portal
  (FR-638); backend/tests/test_feed_settings.py::test_db_check_rejects_retention_years_outside_1_to_10 (FR-638) —
  (FR-638, FR-639, FR-642)
- [x] T-7117 [P] [sonnet] тесты правка записи (план: «Правка и удаление» — правка записи, «Контракты» —
  `/feed/<id>/edit/`, «Тексты отказов») —
  backend/tests/test_feed_edit.py::test_author_edit_updates_text_sets_edited_at_and_shows_changed_time (FR-620);
  backend/tests/test_feed_edit.py::test_edit_overwrites_text_without_keeping_edit_history (FR-620);
  backend/tests/test_feed_edit.py::test_edit_others_post_returns_403_on_get_and_post (FR-620);
  backend/tests/test_feed_edit.py::test_moderator_edit_others_post_returns_403_on_get_and_post (FR-620);
  backend/tests/test_feed_edit.py::test_edit_invisible_post_returns_404_like_nonexistent (FR-620);
  backend/tests/test_feed_edit.py::test_person_added_by_edit_sees_post_from_now_on (FR-620);
  backend/tests/test_feed_edit.py::test_unit_added_by_edit_members_see_post_from_now_on (FR-620);
  backend/tests/test_feed_edit.py::test_edit_set_without_saved_recipient_refused_only_add_recipients_unchanged (FR-620);
  backend/tests/test_feed_edit.py::test_edit_form_shows_saved_recipients_without_remove_control (FR-620);
  backend/tests/test_feed_edit.py::test_post_with_deleted_unit_and_dismissed_recipient_saves_and_keeps_them (FR-620);
  backend/tests/test_feed_edit.py::test_edit_adding_nonexistent_unit_or_dismissed_person_refused (FR-620, FR-610);
  backend/tests/test_feed_edit.py::test_edit_saved_and_new_recipients_total_50_accepted_51_refused_with_reason (FR-610,
  FR-642); backend/tests/test_feed_edit.py::test_edit_adding_all_without_post_all_refused_post_all_not_allowed (FR-610,
  FR-620); backend/tests/test_feed_edit.py::test_edit_keeps_saved_all_after_post_all_right_removed (FR-640, FR-620);
  backend/tests/test_feed_edit.py::test_edit_ignores_sent_kind_and_kind_stays_unchanged (FR-620);
  backend/tests/test_feed_edit.py::test_edit_empty_text_refused_with_reason_post_unchanged (FR-620, FR-642);
  backend/tests/test_feed_edit.py::test_edit_with_email_or_phone_shows_pdn_warning_like_publish (FR-620);
  backend/tests/test_feed_edit.py::test_edit_locks_post_row_with_select_for_update (FR-620);
  backend/tests/test_feed_edit.py::test_edit_htmx_refusal_returns_200_fragment_with_reason_and_entered_values (FR-642) —
  (FR-610, FR-620, FR-640, FR-642)
- [x] T-7118 [P] [sonnet] тесты удаление записи, правка и удаление комментария (план: «Правка и удаление» — удаление
  записи, комментарий, «Журнал», «Контракты» — `/feed/<id>/delete/`, `/feed/comments/<cid>/edit/`,
  `/feed/comments/<cid>/delete/`) —
  backend/tests/test_feed_edit_2.py::test_author_deletes_own_post_with_comments_likes_reads_answers_shown_and_recipients
  (FR-621);
  backend/tests/test_feed_edit_2.py::test_post_delete_removes_core_comments_via_delete_for_and_feed_comment_rows
  (FR-621); backend/tests/test_feed_edit_2.py::test_post_delete_removes_post_and_comment_likes (FR-621);
  backend/tests/test_feed_edit_2.py::test_post_delete_removes_post_and_comment_files_in_all_scan_states_with_stored_file_rows
  (FR-621); backend/tests/test_feed_edit_2.py::test_post_delete_erases_files_and_thumbs_from_disk_only_after_commit
  (FR-621); backend/tests/test_feed_edit_2.py::test_post_delete_missing_file_on_disk_is_not_error (FR-621);
  backend/tests/test_feed_edit_2.py::test_post_delete_locks_post_row_with_select_for_update (FR-621);
  backend/tests/test_feed_edit_2.py::test_deleted_post_link_returns_404_same_as_nonexistent (FR-621);
  backend/tests/test_feed_edit_2.py::test_moderator_who_sees_post_deletes_others_post (FR-621);
  backend/tests/test_feed_edit_2.py::test_moderator_deleting_others_post_writes_post_deleted_audit_with_author_and_time_without_text
  (FR-621, FR-639); backend/tests/test_feed_edit_2.py::test_author_deleting_own_post_writes_no_audit (FR-639);
  backend/tests/test_feed_edit_2.py::test_delete_others_visible_post_without_moderate_returns_403 (FR-621);
  backend/tests/test_feed_edit_2.py::test_delete_invisible_post_returns_404 (FR-621);
  backend/tests/test_feed_edit_2.py::test_moderator_not_recipient_gets_404_then_deletes_after_mention_in_comment
  (FR-621);
  backend/tests/test_feed_edit_2.py::test_post_and_comment_delete_keep_notifications_and_their_link_returns_404
  (FR-632);
  backend/tests/test_feed_edit_2.py::test_comment_author_edits_text_via_core_update_sets_edited_at_and_changed_mark_without_audit
  (FR-622, FR-639); backend/tests/test_feed_edit_2.py::test_comment_edit_new_mention_adds_post_recipient (FR-622);
  backend/tests/test_feed_edit_2.py::test_comment_edit_by_other_or_moderator_returns_403 (FR-622);
  backend/tests/test_feed_edit_2.py::test_comment_edit_or_delete_on_invisible_post_returns_404 (FR-622);
  backend/tests/test_feed_edit_2.py::test_comment_author_deletes_own_comment_without_audit (FR-622, FR-639);
  backend/tests/test_feed_edit_2.py::test_moderator_who_sees_post_deletes_others_comment_with_comment_deleted_audit_without_text
  (FR-622, FR-639); backend/tests/test_feed_edit_2.py::test_post_author_cannot_delete_others_comment_403 (FR-622);
  backend/tests/test_feed_edit_2.py::test_comment_delete_removes_its_likes_files_and_stored_files_and_erases_disk_after_commit
  (FR-622); backend/tests/test_feed_edit_2.py::test_comment_delete_keeps_mentioned_people_as_post_recipients (FR-622);
  backend/tests/test_feed_edit_2.py::test_comment_edit_adds_new_file_up_to_limit_3_and_removes_marked_file_with_stored_file_and_disk_after_commit
  (FR-622);
  backend/tests/test_feed_edit_2.py::test_comment_on_post_deleted_between_check_and_insert_rolls_back_without_orphan_core_comment
  (FR-621, FR-622) — (FR-621, FR-622, FR-632, FR-639)
- [x] T-7119 [P] [sonnet] тесты комментарии; комментарии базы знаний не меняются (план: «Комментарии», «Модель данных» —
  `FeedComment`, «Контракты» — `/feed/<id>/comments/`, «Тексты отказов») —
  backend/tests/test_feed_comments.py::test_viewer_adds_comment_core_comment_and_feed_comment_with_lowercase_object_ref
  (FR-623, FR-624);
  backend/tests/test_feed_comments.py::test_comment_response_appends_comment_at_bottom_with_author_and_time_and_clears_field
  (FR-623); backend/tests/test_feed_comments.py::test_non_viewer_add_or_list_comments_returns_404 (FR-623);
  backend/tests/test_feed_comments.py::test_empty_comment_refused_with_write_text_reason (FR-623, FR-642);
  backend/tests/test_feed_comments.py::test_comment_4000_chars_accepted_4001_refused_with_limit_reason (FR-623, FR-642);
  backend/tests/test_feed_comments.py::test_comment_three_files_accepted_fourth_refused_with_reason (FR-633, FR-642);
  backend/tests/test_feed_comments.py::test_comment_htmx_refusal_returns_200_fragment_with_reason_and_entered_text
  (FR-642); backend/tests/test_feed_comments.py::test_comments_flat_list_ordered_by_created_at_then_id (FR-623);
  backend/tests/test_feed_comments.py::test_feed_shows_last_three_comments_and_show_all_8 (FR-623);
  backend/tests/test_feed_comments.py::test_comments_fragment_returns_all_eight_in_order (FR-623);
  backend/tests/test_feed_comments.py::test_post_card_shows_all_comments (FR-623);
  backend/tests/test_feed_comments.py::test_comment_shows_author_photo_name_and_time (FR-623);
  backend/tests/test_feed_comments.py::test_comment_author_name_is_link_only_for_staff_view_or_accounts_manage (FR-623);
  backend/tests/test_feed_comments.py::test_comment_menu_edit_delete_shown_by_right (FR-623);
  backend/tests/test_feed_comments.py::test_comment_has_escaped_reply_hook_with_author_id_and_name (FR-623);
  backend/tests/test_feed_comments.py::test_comment_with_mentions_files_and_notifications_rolls_back_together_on_dispatch_error
  (FR-623); backend/tests/test_feed_comments.py::test_comment_live_frame_sent_only_after_commit (FR-623, FR-627);
  backend/tests/test_feed_comments.py::test_article_comment_edit_like_and_files_via_feed_urls_return_404 (FR-624);
  backend/tests/test_feed_comments.py::test_core_comment_get_fields_unchanged (FR-624);
  backend/tests/test_feed_comments.py::test_article_comments_stay_without_edit_mentions_likes_and_files (FR-624) —
  (FR-623, FR-624, FR-627, FR-633, FR-642)
- [x] T-7120 [P] [sonnet] тесты «Нравится» (план: «„Нравится“», «Контракты» — `/feed/<id>/like/`, `/feed/<id>/likes/`,
  `/feed/comments/<cid>/like/`, `/feed/comments/<cid>/likes/`) —
  backend/tests/test_feed_likes.py::test_post_like_first_press_sets_mark_second_removes (FR-625);
  backend/tests/test_feed_likes.py::test_comment_like_first_press_sets_mark_second_removes (FR-625);
  backend/tests/test_feed_likes.py::test_like_response_has_button_in_own_state_and_likers_line_with_own_name (FR-625);
  backend/tests/test_feed_likes.py::test_two_post_like_creates_in_a_row_leave_one_mark_duplicate_caught_as_existing
  (FR-625);
  backend/tests/test_feed_likes.py::test_two_comment_like_creates_in_a_row_leave_one_mark_duplicate_caught_as_existing
  (FR-625); backend/tests/test_feed_likes.py::test_two_post_like_deletes_in_a_row_raise_no_error (FR-625);
  backend/tests/test_feed_likes.py::test_two_comment_like_deletes_in_a_row_raise_no_error (FR-625);
  backend/tests/test_feed_likes.py::test_one_mark_per_user_unique_constraint_on_post_and_comment_likes (FR-625);
  backend/tests/test_feed_likes.py::test_post_likers_line_two_names_and_three_more_latest_first (FR-625);
  backend/tests/test_feed_likes.py::test_comment_likers_line_latest_first (FR-625);
  backend/tests/test_feed_likes.py::test_post_likes_fragment_lists_all_likers (FR-625);
  backend/tests/test_feed_likes.py::test_comment_likes_fragment_lists_all_likers (FR-625);
  backend/tests/test_feed_likes.py::test_author_likes_own_post_without_notification_to_self (FR-625, FR-630);
  backend/tests/test_feed_likes.py::test_author_likes_own_comment_without_notification_to_self (FR-625, FR-630);
  backend/tests/test_feed_likes.py::test_post_like_and_likes_of_invisible_post_return_404 (FR-625);
  backend/tests/test_feed_likes.py::test_comment_like_and_likes_of_invisible_post_return_404 (FR-625) — (FR-625, FR-630)
- [x] T-7121 [P] [sonnet] тесты показы и число непрочитанного (план: «Непрочитанное» — показ, число, число многим,
  обновление числа) —
  backend/tests/test_feed_unread.py::test_feed_page_records_shown_before_shell_render_and_badge_excludes_shown (FR-626);
  backend/tests/test_feed_unread.py::test_three_unread_posts_shown_on_feed_page_badge_drops_to_zero (FR-626);
  backend/tests/test_feed_unread.py::test_feed_more_with_hx_request_records_shown_and_returns_oob_badge (FR-626);
  backend/tests/test_feed_unread.py::test_feed_more_without_hx_request_records_no_shown (FR-626);
  backend/tests/test_feed_unread.py::test_feed_new_with_hx_request_records_shown_and_badge_drops_by_two (FR-626);
  backend/tests/test_feed_unread.py::test_feed_new_without_hx_request_records_no_shown (FR-626);
  backend/tests/test_feed_unread.py::test_post_card_records_shown_and_badge_excludes_post (FR-626);
  backend/tests/test_feed_unread.py::test_shown_written_by_single_insert_on_conflict_do_nothing_repeat_show_no_error
  (FR-626); backend/tests/test_feed_unread.py::test_own_post_not_counted_and_gets_no_shown_row (FR-626);
  backend/tests/test_feed_unread.py::test_edit_and_new_comment_do_not_make_shown_post_unread (FR-626);
  backend/tests/test_feed_unread.py::test_count_includes_only_posts_published_within_30_days (FR-626);
  backend/tests/test_feed_unread.py::test_count_excludes_posts_invisible_to_employee (FR-626);
  backend/tests/test_feed_unread.py::test_count_capped_at_100_badge_shows_99_plus_for_120 (FR-626);
  backend/tests/test_feed_unread.py::test_zero_unread_badge_node_hidden (FR-626);
  backend/tests/test_feed_unread.py::test_newcomer_with_50_old_and_3_new_unit_posts_counts_3_and_old_posts_in_feed
  (FR-626); backend/tests/test_feed_unread.py::test_counts_for_many_equals_count_for_each_of_100_employees (FR-626) —
  (FR-626)
- [ ] T-7122 [P] [sonnet] тесты рассылки живых обновлений: получатели при каждой рассылке (план: «Живые обновления»
  (рассылка, шаг 1, группы), «Правка и удаление» (получатели удаления снимаются до удаления)) —
  backend/tests/test_feed_live.py::test_publish_frame_is_sent_only_after_commit_into_personal_feed_groups (FR-627);
  backend/tests/test_feed_live.py::test_recipients_are_visibility_audience_computed_at_each_broadcast (FR-628, FR-606);
  backend/tests/test_feed_live.py::test_post_only_to_petrov_gives_other_open_sockets_no_banner_count_or_fragment_on_publish
  (FR-628, FR-606);
  backend/tests/test_feed_live.py::test_post_only_to_petrov_gives_other_open_sockets_no_fragment_or_count_on_comment
  (FR-628, FR-606); backend/tests/test_feed_live.py::test_employee_moved_out_of_unit_gets_no_next_broadcast_of_unit_post
  (FR-628, FR-606); backend/tests/test_feed_live.py::test_unit_newcomer_gets_next_broadcast_about_earlier_unit_post
  (FR-628); backend/tests/test_feed_live.py::test_dismissed_and_blocked_employees_are_not_recipients (FR-628, FR-606);
  backend/tests/test_feed_live.py::test_post_delete_sends_oob_delete_frame_to_those_who_saw_post_before_delete (FR-627,
  FR-628);
  backend/tests/test_feed_live.py::test_post_delete_frame_reaches_personal_addressee_although_cascade_removes_addressees
  (FR-628); backend/tests/test_feed_live.py::test_post_delete_sends_new_feed_count_to_same_viewers (FR-628, FR-627,
  FR-626); backend/tests/test_feed_live.py::test_post_edit_frame_has_action_post_and_reaches_page_with_post_in_ids
  (FR-627); backend/tests/test_feed_live.py::test_new_comment_frame_has_action_comment_and_reaches_page_with_post_in_ids
  (FR-627);
  backend/tests/test_feed_live.py::test_comment_edit_and_comment_delete_frames_have_comment_edit_and_comment_delete_actions
  (FR-627); backend/tests/test_feed_live.py::test_post_like_and_comment_like_frames_have_like_and_comment_like_actions
  (FR-627); backend/tests/test_feed_live.py::test_read_and_event_answer_frames_have_read_and_answer_actions (FR-627);
  backend/tests/test_feed_live.py::test_broadcast_goes_through_publish_layer_one_message_per_recipient_group (FR-627);
  backend/tests/test_feed_live.py::test_post_card_socket_gets_frames_about_its_post (FR-627);
  backend/tests/test_feed_live.py::test_socket_on_page_without_feed_gets_no_feed_frames (FR-627) — (FR-606, FR-626,
  FR-627, FR-628)
- [ ] T-7123 [P] [sonnet] тесты кадров: классы рендера, безопасность, слой `publish`, число «Ленты» (план: «Живые
  обновления» (шаги 2–3, формат кадров, CSP, без WebSocket), «Главная, меню и число у «Ленты»» (живое число),
  «Непрочитанное» (обновление числа), «Контракты» («Сообщения слоя каналов»)) —
  backend/tests/test_feed_live_2.py::test_layer_message_is_feed_event_with_post_action_owner_moderators_staff_viewers_variants
  (FR-627); backend/tests/test_feed_live_2.py::test_meta_only_in_new_message_and_variants_empty_only_in_new_message
  (FR-627); backend/tests/test_feed_live_2.py::test_comment_action_messages_carry_comment_id (FR-627);
  backend/tests/test_feed_live_2.py::test_variant_keys_are_role_and_link_staff_pairs_at_most_six (FR-627);
  backend/tests/test_feed_live_2.py::test_variants_hold_only_classes_present_among_recipients (FR-627);
  backend/tests/test_feed_live_2.py::test_variants_have_no_personal_like_read_or_going_state (FR-627);
  backend/tests/test_feed_live_2.py::test_moderators_are_feed_moderate_holders_among_recipients_by_personal_and_unit_roles
  (FR-628); backend/tests/test_feed_live_2.py::test_revoked_moderator_right_makes_next_frame_reader_variant (FR-628);
  backend/tests/test_feed_live_2.py::test_staff_viewers_are_recipients_with_staff_view_or_accounts_manage_at_broadcast
  (FR-627, FR-628); backend/tests/test_feed_live_2.py::test_reader_variant_has_no_edit_delete_menu_and_no_lists (FR-627,
  FR-628);
  backend/tests/test_feed_live_2.py::test_author_variant_has_edit_delete_menu_and_reads_count_moderator_variant_has_delete
  (FR-627);
  backend/tests/test_feed_live_2.py::test_link_staff_variant_shows_name_as_staff_link_other_variant_as_plain_text
  (FR-627); backend/tests/test_feed_live_2.py::test_frame_has_no_csrfmiddlewaretoken_and_no_forms (FR-627, NFR-605);
  backend/tests/test_feed_live_2.py::test_frame_action_buttons_are_hx_post_without_form (FR-627);
  backend/tests/test_feed_live_2.py::test_frame_escapes_script_bold_javascript_link_and_img_onerror_probe (NFR-605);
  backend/tests/test_feed_live_2.py::test_frame_fragments_have_no_style_or_on_event_attributes (NFR-605);
  backend/tests/test_feed_live_2.py::test_publish_with_layer_down_saves_post_and_answers_faster_than_3_seconds (NFR-614,
  FR-628); backend/tests/test_feed_live_2.py::test_comment_with_layer_down_is_saved (NFR-614, FR-628);
  backend/tests/test_feed_live_2.py::test_layer_down_writes_warning_to_application_log (NFR-614);
  backend/tests/test_feed_live_2.py::test_feed_count_frame_after_publish_is_notify_html_menu_badge_feed_oob_on_notify_socket
  (FR-626, FR-627); backend/tests/test_feed_live_2.py::test_feed_count_frame_after_deleting_unread_post (FR-626,
  FR-627); backend/tests/test_feed_live_2.py::test_feed_count_frame_after_widening_recipients_by_edit (FR-626, FR-627);
  backend/tests/test_feed_live_2.py::test_feed_count_frame_after_mention_in_comment (FR-626, FR-627) — (FR-626, FR-627,
  FR-628, NFR-605, NFR-614)
- [ ] T-7124 [P] [sonnet] тесты `FeedConsumer`: подключение и проверка сессии (план: «Живые обновления» (проверка
  сессии, `FeedConsumer`), «Контракты» (`/ws/feed/`)) —
  backend/tests/test_feed_consumers.py::test_connect_after_login_and_second_factor_is_accepted (FR-627);
  backend/tests/test_feed_consumers.py::test_connect_without_login_accepts_then_closes_with_4401 (FR-627);
  backend/tests/test_feed_consumers.py::test_connect_without_second_factor_closes_with_4401 (FR-627);
  backend/tests/test_feed_consumers.py::test_connect_with_expired_session_closes_with_4401 (FR-627);
  backend/tests/test_feed_consumers.py::test_connect_with_foreign_origin_is_refused_before_accept (FR-627);
  backend/tests/test_feed_consumers.py::test_logout_closes_socket_with_4401_within_check_interval (FR-627);
  backend/tests/test_feed_consumers.py::test_logout_from_all_devices_closes_socket_with_4401_within_check_interval
  (FR-627); backend/tests/test_feed_consumers.py::test_blocking_employee_closes_socket_with_4401_within_check_interval
  (FR-627); backend/tests/test_feed_consumers.py::test_dismissing_employee_closes_socket_with_4401_within_check_interval
  (FR-627); backend/tests/test_feed_consumers.py::test_idle_expiry_closes_socket_with_4401_within_check_interval
  (FR-627); backend/tests/test_feed_consumers.py::test_password_expiry_closes_socket_with_4401_within_check_interval
  (FR-627); backend/tests/test_feed_consumers.py::test_closed_socket_gets_no_frames_about_post_published_afterwards
  (FR-627); backend/tests/test_feed_consumers.py::test_check_interval_change_applies_on_next_wait (FR-627);
  backend/tests/test_feed_consumers.py::test_feed_check_interval_default_is_25_seconds_not_over_30 (FR-627);
  backend/tests/test_feed_consumers.py::test_ws_state_error_in_check_loop_closes_with_1013 (FR-627);
  backend/tests/test_feed_consumers.py::test_channel_layer_error_in_consumer_closes_with_1011 (FR-627);
  backend/tests/test_feed_consumers.py::test_connect_adds_socket_to_personal_group_feed_u_id (FR-627);
  backend/tests/test_feed_consumers.py::test_query_keeps_only_filter_keys_or_post_and_drops_foreign_keys (FR-627);
  backend/tests/test_feed_consumers.py::test_client_messages_do_not_extend_session_idle_time (FR-627) — (FR-627)
- [ ] T-7125 [P] [sonnet] тесты сообщений `sync`/`add`, плашки и `/feed/new/` (план: «Живые обновления» (`FeedConsumer`
  — `action="new"`, входящие сообщения, плашка, формат кадров), «Лента, курсор, блок важных, фильтры» (белый список),
  «Контракты» (`/feed/new/`, `/ws/feed/`)) —
  backend/tests/test_feed_consumers_2.py::test_sync_replaces_ids_and_always_answers_with_feed_synced_frame (FR-627);
  backend/tests/test_feed_consumers_2.py::test_sync_with_posts_after_since_sends_banner_with_their_count (FR-627);
  backend/tests/test_feed_consumers_2.py::test_sync_collects_pending_in_one_query_visible_filtered_after_since_without_own
  (FR-627, FR-628, NFR-608);
  backend/tests/test_feed_consumers_2.py::test_sync_after_reconnect_gives_banner_for_posts_published_during_outage
  (FR-627); backend/tests/test_feed_consumers_2.py::test_add_appends_ids_and_its_since_drops_pending_not_later_than_it
  (FR-627, FR-602); backend/tests/test_feed_consumers_2.py::test_client_message_over_16_kb_closes_with_1009 (FR-627);
  backend/tests/test_feed_consumers_2.py::test_ids_over_300_are_dropped (FR-627);
  backend/tests/test_feed_consumers_2.py::test_unknown_messages_and_bad_ids_are_ignored_without_server_error (FR-627,
  NFR-608); backend/tests/test_feed_consumers_2.py::test_frames_are_sent_only_about_posts_in_ids (FR-627, FR-628);
  backend/tests/test_feed_consumers_2.py::test_new_action_matches_filter_by_meta_without_database_queries (FR-627,
  FR-635); backend/tests/test_feed_consumers_2.py::test_new_banner_follows_all_important_and_events_filters (FR-627,
  FR-635); backend/tests/test_feed_consumers_2.py::test_new_banner_follows_mine_mentions_me_and_author_filters (FR-627,
  FR-635); backend/tests/test_feed_consumers_2.py::test_new_banner_follows_period_filter (FR-627, FR-635);
  backend/tests/test_feed_consumers_2.py::test_new_post_not_later_than_since_does_not_go_to_banner (FR-627);
  backend/tests/test_feed_consumers_2.py::test_own_post_does_not_go_to_banner (FR-627);
  backend/tests/test_feed_consumers_2.py::test_post_card_socket_gets_no_banner (FR-627);
  backend/tests/test_feed_consumers_2.py::test_deleting_pending_post_updates_banner_and_hides_it_at_zero (FR-627);
  backend/tests/test_feed_consumers_2.py::test_banner_is_feed_new_with_new_posts_count_text_and_link_to_feed_new
  (FR-627); backend/tests/test_feed_consumers_2.py::test_regular_and_important_posts_give_banner_new_posts_two (FR-627,
  FR-602);
  backend/tests/test_feed_consumers_2.py::test_new_comment_frame_is_beforeend_into_post_comments_and_carries_comment_id
  (FR-627); backend/tests/test_feed_consumers_2.py::test_feed_new_returns_up_to_50_visible_filtered_posts_after_since
  (FR-627, FR-602, FR-628);
  backend/tests/test_feed_consumers_2.py::test_feed_new_puts_unread_important_into_shown_important_block (FR-627,
  FR-602); backend/tests/test_feed_consumers_2.py::test_feed_new_puts_important_on_top_with_regular_when_block_hidden
  (FR-627, FR-602, FR-635);
  backend/tests/test_feed_consumers_2.py::test_feed_new_replaces_banner_with_empty_one_with_new_since (FR-627);
  backend/tests/test_feed_consumers_2.py::test_feed_new_records_shown_and_count_only_with_hx_request (FR-627, FR-602,
  FR-626) — (FR-602, FR-626, FR-627, FR-628, FR-635, NFR-608)
- [ ] T-7126a [P] [sonnet] тесты изменений `core/ws.py`, `notify/consumers.py`, `notify/services/live.py`,
  `config/asgi.py`, `CHANNEL_LAYERS`; прежнее поведение (план: «Проверка» → «Изменения кода прежних срезов» (строки
  `config/asgi.py`, `config/settings.py`, `core/ws.py`, `notify/consumers.py`, `notify/services/live.py`), «Живые
  обновления» (проверка сессии, исправление дефекта среза 004, сбой Valkey), «Главная, меню и число у «Ленты»»
  (обработчик `notify_html`)) —
  backend/tests/test_feed_core_changes_2.py::test_session_guard_with_bad_ws_state_on_connect_accepts_and_closes_4401
  (FR-627);
  backend/tests/test_feed_core_changes_2.py::test_session_guard_loop_waits_check_interval_then_calls_on_check_and_ws_state
  (FR-627); backend/tests/test_feed_core_changes_2.py::test_notify_consumer_check_interval_patch_still_applies (FR-627);
  backend/tests/test_feed_core_changes_2.py::test_notify_consumer_count_system_notice_and_group_binding_as_before
  (FR-627); backend/tests/test_feed_core_changes_2.py::test_notify_consumer_on_check_marks_presence_online (FR-627);
  backend/tests/test_feed_core_changes_2.py::test_notify_consumer_ignores_incoming_messages_as_before (FR-627);
  backend/tests/test_feed_core_changes_2.py::test_notify_consumer_check_loop_error_closes_with_1013 (FR-627);
  backend/tests/test_feed_core_changes_2.py::test_notify_html_handler_sends_ready_fragment_as_is (FR-626, FR-627);
  backend/tests/test_feed_core_changes_2.py::test_live_push_takes_publish_channel_layer (NFR-614);
  backend/tests/test_feed_core_changes_2.py::test_live_push_frame_and_parts_order_as_before (FR-627);
  backend/tests/test_feed_core_changes_2.py::test_live_push_layer_failure_only_logs_warning (NFR-614);
  backend/tests/test_feed_core_changes_2.py::test_publish_layer_has_same_host_and_prefix_2_second_timeouts_and_300_connections
  (NFR-614); backend/tests/test_feed_core_changes_2.py::test_default_layer_unchanged_and_channel_layers_have_two_keys
  (NFR-614);
  backend/tests/test_feed_core_changes_2.py::test_asgi_websocket_patterns_include_notify_routes_and_feed_routing_list_when_feed_installed
  (FR-627, FR-641);
  backend/tests/test_feed_core_changes_2.py::test_asgi_without_feed_has_no_ws_feed_route_and_ws_notify_as_before
  (FR-641) — (FR-626, FR-627, FR-641, NFR-614)
- [ ] T-7126b [P] [sonnet] тесты изменений `core/extensions.py` (поля вида) и `notify` (фильтр `channels` в шести
  местах, склейка с `coalesce_text`); прежнее поведение (план: «Проверка» → «Изменения кода прежних срезов» (строки
  `core/extensions.py`, `notify/services/dispatch.py`, `notify/services/prefs.py`, `notify/views/me.py`,
  `notify/views/admin.py`, `notify/services/settings.py`), «Уведомления» (склейка с обновлением текста, допустимые
  каналы вида)) —
  backend/tests/test_feed_core_changes_3.py::test_notification_kind_channels_and_coalesce_text_are_last_and_default_to_none
  (FR-629, FR-631);
  backend/tests/test_feed_core_changes_3.py::test_notification_kind_has_fifteen_fields_first_thirteen_in_old_order
  (FR-629, FR-631, FR-641);
  backend/tests/test_feed_core_changes_3.py::test_listed_and_channels_for_drop_channel_outside_kind_channels (FR-631);
  backend/tests/test_feed_core_changes_3.py::test_prefs_effective_has_no_cell_outside_kind_channels (FR-631);
  backend/tests/test_feed_core_changes_3.py::test_my_notifications_save_drops_channel_outside_kind_channels (FR-631);
  backend/tests/test_feed_core_changes_3.py::test_my_notifications_table_cell_outside_kind_channels_has_no_box (FR-631);
  backend/tests/test_feed_core_changes_3.py::test_admin_rows_and_post_parsing_drop_channel_outside_kind_channels
  (FR-631); backend/tests/test_feed_core_changes_3.py::test_normalized_defaults_drop_channel_outside_kind_channels
  (FR-631); backend/tests/test_feed_core_changes_3.py::test_kind_without_channels_keeps_cells_and_channels_as_before
  (FR-631);
  backend/tests/test_feed_core_changes_3.py::test_coalesce_text_updates_unread_text_with_since_as_its_creation_time
  (FR-629); backend/tests/test_feed_core_changes_3.py::test_coalesce_text_update_happens_under_coalesce_key_lock
  (FR-629); backend/tests/test_feed_core_changes_3.py::test_coalesce_text_update_keeps_url_and_sends_no_bell_frame
  (FR-629); backend/tests/test_feed_core_changes_3.py::test_coalesce_without_coalesce_text_keeps_first_text_as_before
  (FR-629) — (FR-629, FR-631, FR-641)
- [ ] T-7127 [P] [sonnet] тесты уведомлений: кто что получает, приоритет (план: «Уведомления» — кто что получает, одно
  событие — одно уведомление, ссылки и `object_ref`; «Правка и удаление» — новым адресатам) —
  backend/tests/test_feed_notify.py::test_for_you_with_post_ref_and_card_url_only_to_personal_recipients_not_via_all_or_unit
  (FR-629); backend/tests/test_feed_notify.py::test_plain_post_to_all_or_unit_without_mentions_creates_no_notifications
  (FR-629); backend/tests/test_feed_notify.py::test_publish_mentioned_from_other_unit_gets_mention_and_sees_post
  (FR-611, FR-629); backend/tests/test_feed_notify.py::test_new_event_participants_get_invite_author_does_not (FR-629,
  FR-630); backend/tests/test_feed_notify.py::test_new_important_everyone_seeing_gets_important_author_does_not (FR-629,
  FR-630); backend/tests/test_feed_notify.py::test_important_personal_with_mention_gives_single_mention (FR-630);
  backend/tests/test_feed_notify.py::test_own_like_and_self_mention_give_no_notification (FR-630);
  backend/tests/test_feed_notify.py::test_dismissed_recipient_or_mentioned_gets_nothing (FR-630);
  backend/tests/test_feed_notify.py::test_recipients_only_from_audience_at_event_moment_transferred_commenter_gets_nothing
  (FR-630); backend/tests/test_feed_notify.py::test_edit_adding_person_to_important_gives_important (FR-629, FR-630);
  backend/tests/test_feed_notify.py::test_edit_adding_person_to_important_with_new_mention_gives_mention_only (FR-629,
  FR-630); backend/tests/test_feed_notify.py::test_edit_adding_unit_to_important_notifies_only_newly_seeing (FR-629);
  backend/tests/test_feed_notify.py::test_edit_event_added_person_gets_invite_mentioned_gets_mention (FR-611, FR-629,
  FR-630);
  backend/tests/test_feed_notify.py::test_edit_message_added_personally_gets_for_you_added_via_unit_or_all_gets_nothing
  (FR-629); backend/tests/test_feed_notify.py::test_edit_new_mention_marker_gives_mention_already_mentioned_gets_nothing
  (FR-611, FR-629);
  backend/tests/test_feed_notify.py::test_event_start_end_or_place_change_sends_event_changed_to_participants_except_author
  (FR-619, FR-629);
  backend/tests/test_feed_notify.py::test_event_change_with_added_participant_gives_invite_not_event_changed (FR-619,
  FR-630); backend/tests/test_feed_notify.py::test_event_place_change_with_new_mention_of_participant_gives_mention_only
  (FR-619, FR-630); backend/tests/test_feed_notify.py::test_event_title_or_description_edit_sends_no_notifications
  (FR-619); backend/tests/test_feed_notify.py::test_extending_important_term_or_repeated_importance_sends_nothing
  (FR-629);
  backend/tests/test_feed_notify.py::test_comment_notifies_post_author_and_previous_commenters_not_commenter_with_anchor_url
  (FR-629, FR-630);
  backend/tests/test_feed_notify.py::test_comment_mention_gives_mention_over_comment_kind_and_makes_recipient (FR-611,
  FR-629, FR-630);
  backend/tests/test_feed_notify.py::test_like_notifies_author_post_ref_for_post_comment_ref_and_anchor_for_comment
  (FR-629); backend/tests/test_feed_notify.py::test_likes_of_post_and_comment_of_same_author_give_two_notifications
  (FR-629); backend/tests/test_feed_notify.py::test_notifications_created_by_dispatch_create_inside_action_transaction
  (FR-630); backend/tests/test_feed_notify.py::test_notify_rules_decide_applies_full_priority_order (FR-630) — (FR-611,
  FR-619, FR-629, FR-630)
- [ ] T-7128 [P] [sonnet] тесты уведомлений: каталог, тексты, каналы, склейка, `still_relevant` (план: «Уведомления» —
  виды, склейка с обновлением текста, допустимые каналы вида, тексты, перед письмом и сводкой) —
  backend/tests/test_feed_notify_2.py::test_catalog_eight_feed_kinds_codes_titles_module_order_available_events_coalesce
  (FR-629); backend/tests/test_feed_notify_2.py::test_feed_kinds_default_channels_portal_and_email_like_portal_only
  (FR-631);
  backend/tests/test_feed_notify_2.py::test_my_notifications_feed_section_eight_kinds_like_without_external_cells
  (FR-629, FR-631); backend/tests/test_feed_notify_2.py::test_admin_defaults_like_has_no_email_or_messenger_cells
  (FR-631);
  backend/tests/test_feed_notify_2.py::test_like_delivered_only_on_portal_even_if_matrix_or_defaults_force_email_and_bots
  (FR-631); backend/tests/test_feed_notify_2.py::test_text_of_each_kind_by_plan_template_with_author_and_snippet
  (FR-631, NFR-611); backend/tests/test_feed_notify_2.py::test_event_texts_use_moscow_time_at_utc_midnight (FR-631,
  NFR-611); backend/tests/test_feed_notify_2.py::test_title_and_place_200_cut_to_60_snippet_100_total_at_most_300
  (FR-631); backend/tests/test_feed_notify_2.py::test_snippet_without_markup_marker_becomes_at_full_name (FR-631);
  backend/tests/test_feed_notify_2.py::test_external_text_of_each_kind_constant_without_name_title_place_snippet
  (FR-631, NFR-609);
  backend/tests/test_feed_notify_2.py::test_external_channel_mention_sends_only_external_text_and_link_parametrized_telegram_max_webpush
  (FR-631, NFR-609); backend/tests/test_feed_notify_2.py::test_browser_tab_system_notification_uses_portal_text (FR-631,
  NFR-609); backend/tests/test_feed_notify_2.py::test_email_sent_only_if_unread_after_delay_with_author_and_snippet
  (FR-631);
  backend/tests/test_feed_notify_2.py::test_quiet_hours_portal_immediately_email_and_messengers_held_for_digest
  (FR-631); backend/tests/test_feed_notify_2.py::test_three_comments_coalesce_into_one_with_count_3_and_link_to_first
  (FR-629, FR-630, FR-631);
  backend/tests/test_feed_notify_2.py::test_three_likes_coalesce_text_last_liker_and_two_more_link_to_post (FR-629,
  FR-631); backend/tests/test_feed_notify_2.py::test_two_likes_on_comment_one_portal_notification_no_email_no_messenger
  (FR-629, FR-631); backend/tests/test_feed_notify_2.py::test_unlike_does_not_change_unread_notification_text (FR-629);
  backend/tests/test_feed_notify_2.py::test_delayed_email_takes_updated_coalesced_text_at_send (FR-629, FR-631);
  backend/tests/test_feed_notify_2.py::test_still_relevant_deleted_post_email_and_digest_not_sent (FR-630, FR-632);
  backend/tests/test_feed_notify_2.py::test_still_relevant_deleted_comment_email_not_sent (FR-630, FR-632);
  backend/tests/test_feed_notify_2.py::test_still_relevant_recipient_stopped_seeing_email_not_sent_link_404 (FR-606,
  FR-630);
  backend/tests/test_feed_notify_2.py::test_portal_notifications_kept_after_delete_by_author_moderator_or_retention_link_404
  (FR-630, FR-632);
  backend/tests/test_feed_notify_2.py::test_opening_card_marks_post_notifications_and_own_comment_likes_read (FR-629,
  FR-630); backend/tests/test_feed_notify_2.py::test_notification_text_with_markup_escaped_on_display (NFR-605) —
  (FR-606, FR-629, FR-630, FR-631, FR-632, NFR-605, NFR-609, NFR-611)
- [ ] T-7129 [P] [sonnet] тесты файлов: загрузка, пределы, привязка, «убрать» (план: «Файлы и эскизы» — загрузка,
  привязка, предел 30; «Модель данных» — `FeedFile`; «Контракты» — `/feed/files/`, `/feed/files/<id>/delete/`) —
  backend/tests/test_feed_files.py::test_upload_exactly_20_mb_accepted_returns_pill_with_hidden_files_id (FR-633,
  NFR-604); backend/tests/test_feed_files.py::test_upload_20_mb_plus_one_byte_refused_file_over_20_mb (FR-633, FR-642,
  NFR-604); backend/tests/test_feed_files.py::test_upload_executable_by_content_refused_type_not_accepted (FR-633,
  FR-642); backend/tests/test_feed_files.py::test_upload_password_archive_refused_type_not_accepted (FR-633, FR-642);
  backend/tests/test_feed_files.py::test_upload_image_over_40_megapixels_refused_type_not_accepted (FR-633, FR-642);
  backend/tests/test_feed_files.py::test_upload_stores_feed_purpose_pending_and_unbound_row_of_uploader (FR-633,
  NFR-604); backend/tests/test_feed_files.py::test_upload_early_refusal_post_attached_plus_have_reaches_10 (FR-633,
  FR-642); backend/tests/test_feed_files.py::test_upload_early_refusal_comment_attached_plus_have_reaches_3 (FR-633,
  FR-642); backend/tests/test_feed_files.py::test_upload_early_refusal_counts_already_attached_on_edit (FR-633, FR-642);
  backend/tests/test_feed_files.py::test_31st_unbound_upload_refused_too_many_files_without_post (FR-633);
  backend/tests/test_feed_files.py::test_publish_binds_files_by_conditional_update_with_uploader_parameter (FR-633);
  backend/tests/test_feed_files.py::test_bind_fewer_rows_than_sent_rolls_back_with_missing_id_refusal (FR-633);
  backend/tests/test_feed_files.py::test_foreign_unbound_file_id_in_files_refused_nothing_bound (FR-633);
  backend/tests/test_feed_files.py::test_binding_same_file_twice_in_a_row_second_refused_bound_once (FR-633);
  backend/tests/test_feed_files.py::test_bind_11th_file_to_post_refused_counting_attached (FR-633, FR-642);
  backend/tests/test_feed_files.py::test_bind_4th_file_to_comment_refused_counting_attached (FR-633, FR-642);
  backend/tests/test_feed_files.py::test_bind_limits_checked_under_post_select_for_update (FR-633);
  backend/tests/test_feed_files.py::test_remove_before_publish_only_own_unbound_file (FR-633);
  backend/tests/test_feed_files.py::test_remove_on_edit_foreign_unbound_or_missing_id_same_refusal_nothing_deleted
  (FR-633);
  backend/tests/test_feed_files.py::test_remove_on_edit_deletes_row_and_stored_file_in_transaction_disk_after_commit
  (FR-633); backend/tests/test_feed_files.py::test_db_check_comment_set_implies_post_set (FR-633) — (FR-633, FR-642,
  NFR-604)
- [ ] T-7130 [P] [sonnet] тесты файлов: назначение, эскизы, выдача, показ (план: «Файлы и эскизы» — назначение `feed`,
  эскиз, выдача, показ, резервная копия) —
  backend/tests/test_feed_files_2.py::test_clean_scan_moves_file_to_attachments_and_builds_thumb (FR-634);
  backend/tests/test_feed_files_2.py::test_found_scan_puts_file_to_quarantine (FR-634);
  backend/tests/test_feed_files_2.py::test_clamav_unavailable_post_and_comment_intact_file_pending_requeued (NFR-614);
  backend/tests/test_feed_files_2.py::test_storage_failure_on_clean_move_keeps_post_comment_and_file_pending_requeued
  (FR-633, NFR-614); backend/tests/test_feed_files_2.py::test_thumb_built_for_jpeg_png_gif_webp_not_for_other_files
  (FR-634); backend/tests/test_feed_files_2.py::test_thumb_at_most_1280_px_longer_side_saved_as_jpeg (FR-634);
  backend/tests/test_feed_files_2.py::test_thumb_png_with_transparency_saved_as_webp (FR-634);
  backend/tests/test_feed_files_2.py::test_thumb_rotated_by_exif_and_saved_without_exif (FR-634);
  backend/tests/test_feed_files_2.py::test_thumb_gif_uses_first_frame (FR-634);
  backend/tests/test_feed_files_2.py::test_original_and_thumb_paths_under_protected_root_thumb_field_set (FR-634,
  NFR-613);
  backend/tests/test_feed_files_2.py::test_thumb_failure_file_clean_without_thumb_log_without_name_partial_removed
  (FR-634, NFR-614);
  backend/tests/test_feed_files_2.py::test_download_clean_image_inline_other_as_attachment_via_x_accel_nosniff_no_store
  (FR-634); backend/tests/test_feed_files_2.py::test_thumb_response_x_accel_protected_thumbs_nosniff_no_store (FR-634);
  backend/tests/test_feed_files_2.py::test_thumb_of_clean_file_without_thumb_returns_404 (FR-634);
  backend/tests/test_feed_files_2.py::test_pending_file_and_thumb_404_with_still_checking_text (FR-634, FR-642);
  backend/tests/test_feed_files_2.py::test_quarantined_file_by_direct_link_404_with_quarantine_text (FR-634, FR-642);
  backend/tests/test_feed_files_2.py::test_invisible_post_file_and_thumb_not_found_like_missing_file (FR-606, FR-634);
  backend/tests/test_feed_files_2.py::test_invisible_post_pending_file_not_found_not_still_checking (FR-606, FR-642);
  backend/tests/test_feed_files_2.py::test_unbound_file_served_only_to_uploader_others_404 (FR-606, FR-634);
  backend/tests/test_feed_files_2.py::test_display_pending_name_and_mark_without_link_in_post_and_comment (FR-634);
  backend/tests/test_feed_files_2.py::test_display_quarantine_name_and_mark_without_link (FR-634);
  backend/tests/test_feed_files_2.py::test_display_clean_image_as_thumb_linking_original (FR-634);
  backend/tests/test_feed_files_2.py::test_display_clean_other_file_name_size_download (FR-634);
  backend/tests/test_feed_files_2.py::test_display_clean_image_without_thumb_shows_name_size_download (FR-634);
  backend/tests/test_feed_files_2.py::test_display_file_state_data_attribute_for_each_state (FR-634) — (FR-606, FR-633,
  FR-634, FR-642, NFR-613, NFR-614)
- [ ] T-7131 [P] [sonnet] тесты сквозного поиска и векторов (план: «Поиск»; «Точки расширения ядра» —
  `search_providers`) — backend/tests/test_feed_search.py::test_provider_key_feed_title_order_60_after_lists (FR-636,
  FR-641); backend/tests/test_feed_search.py::test_provider_available_to_every_logged_in_employee (FR-636);
  backend/tests/test_feed_search.py::test_word_form_finds_post_with_other_form_of_word (FR-636);
  backend/tests/test_feed_search.py::test_word_prefix_finds_comment_with_anchor_url (FR-636);
  backend/tests/test_feed_search.py::test_event_found_by_title_and_place_word_forms_row_shows_title (FR-636);
  backend/tests/test_feed_search.py::test_row_title_name_date_snippet_and_subtitle_post_or_comment (FR-636);
  backend/tests/test_feed_search.py::test_row_snippet_without_markup_marker_as_at_full_name (FR-636);
  backend/tests/test_feed_search.py::test_mention_marker_ids_not_searchable (FR-636);
  backend/tests/test_feed_search.py::test_invisible_post_and_its_comment_absent_from_results_and_count (FR-606, FR-636);
  backend/tests/test_feed_search.py::test_deleted_post_and_comment_not_found (FR-637);
  backend/tests/test_feed_search.py::test_edited_post_not_found_by_old_text_found_by_new (FR-637);
  backend/tests/test_feed_search.py::test_edited_comment_not_found_by_old_text_found_by_new (FR-637);
  backend/tests/test_feed_search.py::test_stop_word_query_returns_empty_without_error (FR-636);
  backend/tests/test_feed_search.py::test_results_ordered_newest_first_across_posts_and_comments (FR-636);
  backend/tests/test_feed_search.py::test_second_page_with_offset_continues_without_gaps_or_repeats_across_posts_and_comments
  (FR-636); backend/tests/test_feed_search.py::test_provider_returns_at_most_limit_plus_one_rows (NFR-603);
  backend/tests/test_feed_search.py::test_count_two_branches_limit_301_capped_at_300 (NFR-603);
  backend/tests/test_feed_search.py::test_without_feed_module_no_feed_group (FR-641);
  backend/tests/test_feed_search.py::test_query_words_passed_as_parameters_not_in_sql_text (NFR-608);
  backend/tests/test_feed_search.py::test_search_query_text_not_stored (FR-636);
  backend/tests/test_feed_search.py::test_post_vector_event_title_place_weight_a_text_weight_b_without_markers (FR-636);
  backend/tests/test_feed_search.py::test_comment_vector_kept_in_feed_comment_search (FR-636, FR-637);
  backend/tests/test_feed_search.py::test_vectors_recomputed_in_publish_post_edit_and_comment_transactions (FR-637);
  backend/tests/test_feed_search.py::test_file_contents_not_searched (FR-636) — (FR-606, FR-636, FR-637, FR-641,
  NFR-603, NFR-608)
- [ ] T-7132 [P] [sonnet] тесты журнал ленты (план: «Журнал», «Срок хранения и ночное задание», «Права среза», «Правка и
  удаление») —
  backend/tests/test_feed_audit.py::test_moderator_deleting_others_post_writes_post_deleted_with_actor_author_and_published_at_without_text
  (FR-639);
  backend/tests/test_feed_audit.py::test_moderator_deleting_others_comment_writes_comment_deleted_with_actor_author_time_and_post_id_without_text
  (FR-639);
  backend/tests/test_feed_audit.py::test_author_editing_and_deleting_own_comment_writes_no_audit_even_if_author_is_moderator
  (FR-639); backend/tests/test_feed_audit.py::test_author_deleting_own_post_writes_no_audit_even_if_author_is_moderator
  (FR-639);
  backend/tests/test_feed_audit.py::test_retention_change_writes_retention_changed_on_feed_settings_with_years_before_after
  (FR-639); backend/tests/test_feed_audit.py::test_retention_purge_writes_one_retention_purged_with_posts_count_per_run
  (FR-639); backend/tests/test_feed_audit.py::test_retention_run_that_deletes_nothing_writes_no_retention_purged
  (FR-639); backend/tests/test_feed_audit.py::test_audit_object_types_are_feed_post_feed_comment_and_feed_settings
  (FR-639); backend/tests/test_feed_audit.py::test_audit_before_after_keys_are_only_those_of_plan_table_for_four_codes
  (FR-639, NFR-607);
  backend/tests/test_feed_audit.py::test_audit_records_of_feed_have_no_post_or_comment_text_title_or_place (FR-639,
  NFR-607); backend/tests/test_feed_audit.py::test_publish_edit_comment_like_read_and_answer_write_no_audit (FR-639);
  backend/tests/test_feed_audit.py::test_audit_labels_cover_every_feed_action_object_type_and_written_key (FR-639);
  backend/tests/test_feed_audit.py::test_audit_label_of_posts_key_is_deleted_by_retention_posts_count (FR-639);
  backend/tests/test_feed_audit.py::test_changing_post_all_and_moderate_in_role_writes_role_updated_with_rights_before_after
  (FR-639); backend/tests/test_feed_audit.py::test_app_role_cannot_update_or_delete_feed_audit_rows (NFR-607) — (FR-639,
  NFR-607)
- [ ] T-7133 [P] [sonnet] тесты права и данные установки (план: «Права среза», «Права и данные установки» — миграция
  `feed 0002`, «Модель данных» — `FeedSettings`) —
  backend/tests/test_feed_seed.py::test_seed_on_slice_006_base_creates_post_all_and_moderate_permissions_with_russian_names
  (FR-640);
  backend/tests/test_feed_seed.py::test_seed_grants_post_all_to_every_role_existing_at_install_including_admin_created_role
  (FR-640); backend/tests/test_feed_seed.py::test_seed_grants_moderate_to_portal_admin_role_only (FR-640);
  backend/tests/test_feed_seed.py::test_seed_adds_feed_rights_and_keeps_prior_permissions_of_roles (FR-640);
  backend/tests/test_feed_seed.py::test_seed_without_portal_admin_role_passes_without_error (FR-640);
  backend/tests/test_feed_seed.py::test_portal_has_eighteen_permissions_after_seed (FR-640);
  backend/tests/test_feed_seed.py::test_second_seed_call_does_not_return_removed_post_all_or_moderate (FR-640);
  backend/tests/test_feed_seed.py::test_role_created_after_seed_has_no_post_all_until_checked (FR-640);
  backend/tests/test_feed_seed.py::test_employee_without_roles_has_no_post_all_right (FR-640, FR-610);
  backend/tests/test_feed_seed.py::test_seed_creates_feed_settings_row_with_three_years_when_missing (FR-640, FR-638);
  backend/tests/test_feed_seed.py::test_seed_keeps_existing_feed_settings_row_unchanged (FR-640, FR-638);
  backend/tests/test_feed_seed.py::test_removing_post_all_from_role_keeps_published_to_all_posts_visible_to_everyone
  (FR-640) — (FR-610, FR-638, FR-640)
- [ ] T-7134 [P] [sonnet] тесты сброс стенда и команды стенда (план: «Стенд и приёмка», «Права и данные установки» —
  `seed(stand=True)`, «Событие и напоминания», «Срок хранения и ночное задание») —
  backend/tests/test_feed_stand.py::test_feed_stand_reset_runs_in_transaction_under_migrate_alias (FR-640);
  backend/tests/test_feed_stand.py::test_feed_stand_reset_wipes_all_feed_tables (FR-640);
  backend/tests/test_feed_stand.py::test_feed_stand_reset_deletes_core_comments_with_feed_post_object_ref (FR-640);
  backend/tests/test_feed_stand.py::test_feed_stand_reset_wipes_feed_file_rows_stored_files_and_disk_after_commit
  (FR-640); backend/tests/test_feed_stand.py::test_feed_stand_reset_wipes_whole_thumbs_directory (FR-640);
  backend/tests/test_feed_stand.py::test_feed_stand_reset_restores_feed_settings_to_three_years (FR-640, FR-638);
  backend/tests/test_feed_stand.py::test_feed_stand_reset_returns_post_all_to_all_roles_and_moderate_to_admin_after_removal
  (FR-640);
  backend/tests/test_feed_stand.py::test_feed_stand_reset_disconnects_core_role_permissions_m2m_handler_during_seed
  (FR-640); backend/tests/test_feed_stand.py::test_feed_stand_reset_reconnects_m2m_handler_in_finally_when_seed_raises
  (FR-640); backend/tests/test_feed_stand.py::test_feed_stand_reset_is_registered_last_and_runs_first (FR-640);
  backend/tests/test_feed_stand.py::test_feed_require_stand_refuses_without_e2e_stand_flag (FR-640);
  backend/tests/test_feed_stand.py::test_e2e_feed_shift_refuses_without_e2e_stand_flag (FR-618);
  backend/tests/test_feed_stand.py::test_e2e_feed_shift_accepts_1_and_10080_minutes (FR-618);
  backend/tests/test_feed_stand.py::test_e2e_feed_shift_rejects_0_and_10081_minutes_without_changes (FR-618);
  backend/tests/test_feed_stand.py::test_e2e_feed_shift_moves_start_end_remind_at_and_reminded_for_start_of_all_events_back_without_save
  (FR-618); backend/tests/test_feed_stand.py::test_e2e_feed_shift_moves_important_until_of_important_posts_back
  (FR-613); backend/tests/test_feed_stand.py::test_e2e_feed_shift_runs_reminders_job_in_process_after_shift (FR-618);
  backend/tests/test_feed_stand.py::test_e2e_feed_shift_prints_single_line_with_shifted_reminded_and_important (FR-618);
  backend/tests/test_feed_stand.py::test_e2e_feed_retention_refuses_without_e2e_stand_flag (FR-638);
  backend/tests/test_feed_stand.py::test_e2e_feed_retention_accepts_1_and_4000_days (FR-638);
  backend/tests/test_feed_stand.py::test_e2e_feed_retention_rejects_0_and_4001_days_without_changes (FR-638);
  backend/tests/test_feed_stand.py::test_e2e_feed_retention_ages_published_at_of_posts_and_recipient_copies (FR-638);
  backend/tests/test_feed_stand.py::test_e2e_feed_retention_posts_key_ages_only_listed_posts (FR-638);
  backend/tests/test_feed_stand.py::test_e2e_feed_retention_runs_night_job_in_process_and_prints_single_line_with_aged_and_deleted
  (FR-638) — (FR-613, FR-618, FR-638, FR-640)
- [ ] T-7135 [P] [sonnet] тесты развёртывание (план: «Запуск», «Новые компоненты и лицензии», «Безопасный вывод, язык,
  узкий экран», «Нагрузка», «Проверка» — `test_feed_deploy.py`, «Модуль и выключение»; прежние записи cron сверяются по
  имени и минуте, у `notify_tick` — интервал 30 с) —
  backend/tests/test_feed_deploy.py::test_feed_is_last_in_installed_apps_after_search (FR-641);
  backend/tests/test_feed_deploy.py::test_feed_reminders_cron_entry_runs_remind_events_every_minute_in_notify_with_timeout_120
  (FR-618);
  backend/tests/test_feed_deploy.py::test_feed_retention_cron_entry_runs_retention_night_at_23_35_in_maintenance_with_timeout_600
  (FR-638); backend/tests/test_feed_deploy.py::test_feed_cron_entries_are_under_is_installed_guard (FR-641);
  backend/tests/test_feed_deploy.py::test_cron_has_no_other_entry_at_23_35 (FR-638);
  backend/tests/test_feed_deploy.py::test_cron_module_has_twenty_register_calls (FR-618, FR-638);
  backend/tests/test_feed_deploy.py::test_previous_eighteen_cron_entries_keep_names_and_minutes (FR-641);
  backend/tests/test_feed_deploy.py::test_feed_urls_are_included_under_is_installed_guard (FR-641);
  backend/tests/test_feed_deploy.py::test_nginx_dev_config_has_feed_files_location_with_25m_limit (FR-633, NFR-604);
  backend/tests/test_feed_deploy.py::test_nginx_prod_config_has_feed_files_location_with_25m_limit (FR-633, NFR-604);
  backend/tests/test_feed_deploy.py::test_feed_files_location_repeats_proxy_directives_in_both_configs (FR-633,
  NFR-604); backend/tests/test_feed_deploy.py::test_nginx_previous_four_55m_locations_and_common_6m_limit_unchanged
  (FR-633, FR-641); backend/tests/test_feed_deploy.py::test_nginx_ws_location_unchanged_in_both_configs (FR-641);
  backend/tests/test_feed_deploy.py::test_feed_files_and_thumbs_live_in_protected_volume_and_backup_script_unchanged
  (NFR-613); backend/tests/test_feed_deploy.py::test_no_new_packages_and_no_slice_007_line_in_requirements (FR-641);
  backend/tests/test_feed_deploy.py::test_channel_layers_publish_key_has_same_address_and_prefix_with_2s_timeouts
  (FR-641, NFR-614);
  backend/tests/test_feed_deploy.py::test_home_and_feed_pages_send_csp_without_unsafe_inline_in_script_src (NFR-605);
  backend/tests/test_feed_deploy.py::test_feed_templates_have_no_style_attribute (NFR-605);
  backend/tests/test_feed_deploy.py::test_feed_templates_have_no_inline_event_handlers (NFR-605);
  backend/tests/test_feed_deploy.py::test_feed_scripts_are_external_files_in_static_feed (NFR-605);
  backend/tests/test_feed_deploy.py::test_feed_pages_texts_are_russian (NFR-611);
  backend/tests/test_feed_deploy.py::test_feed_times_are_shown_in_moscow_at_utc_midnight_for_post_event_and_edited_mark
  (NFR-611);
  backend/tests/test_feed_deploy.py::test_load_suite_has_fill_feed_script_requiring_stand_flag_and_feed_user_class
  (NFR-612); backend/tests/test_feed_deploy.py::test_shown_post_has_index_so_commit_fk_check_skips_full_scan (FR-638, NFR-610) — (FR-618, FR-633, FR-638, FR-641, NFR-604, NFR-605, NFR-611, NFR-612, NFR-613, NFR-614)
- [ ] T-7136 [P] [sonnet] тесты границы модуля (план: «Модуль и выключение», «Точки расширения ядра и шина событий»,
  «Сверка с конституцией», «Модель данных») —
  backend/tests/test_feed_boundaries.py::test_core_org_notify_knowledge_servicedesk_lists_search_do_not_import_feed
  (FR-641);
  backend/tests/test_feed_boundaries.py::test_feed_does_not_import_models_of_org_notify_or_other_apps_and_imports_nothing_from_servicedesk_knowledge_lists_search
  (FR-641); backend/tests/test_feed_boundaries.py::test_feed_imports_org_only_through_services_structure (FR-641);
  backend/tests/test_feed_boundaries.py::test_feed_imports_notify_only_through_dispatch_and_live_group (FR-641);
  backend/tests/test_feed_boundaries.py::test_feed_has_is_installed_guard_for_each_org_and_notify_import (FR-641);
  backend/tests/test_feed_boundaries.py::test_points_tuple_has_eighteen_names_and_feed_uses_home_body_last (FR-641);
  backend/tests/test_feed_boundaries.py::test_feed_registers_menu_items_feed_at_root_order_0_with_live_badge_and_feed_settings_order_63
  (FR-641, FR-601);
  backend/tests/test_feed_boundaries.py::test_feed_registers_home_body_and_search_provider_feed_order_60 (FR-641);
  backend/tests/test_feed_boundaries.py::test_feed_registers_eight_notification_kinds_file_purpose_audit_labels_and_stand_reset
  (FR-641); backend/tests/test_feed_boundaries.py::test_feed_does_not_register_home_notices (FR-641);
  backend/tests/test_feed_boundaries.py::test_feed_has_no_bus_subscriptions_and_publishes_only_object_viewed (FR-641);
  backend/tests/test_feed_boundaries.py::test_home_without_feed_is_previous_home_with_module_notices (FR-641);
  backend/tests/test_feed_boundaries.py::test_menu_without_feed_has_no_feed_items_and_home_item_first (FR-641);
  backend/tests/test_feed_boundaries.py::test_search_page_without_feed_renders_without_feed_group (FR-641);
  backend/tests/test_feed_boundaries.py::test_notification_catalog_without_feed_has_no_feed_kinds (FR-641);
  backend/tests/test_feed_boundaries.py::test_asgi_routes_without_feed_app_have_no_ws_feed_and_keep_ws_notify (FR-641);
  backend/tests/test_feed_boundaries.py::test_other_modules_pages_render_without_feed (FR-641);
  backend/tests/test_feed_boundaries.py::test_feed_models_have_no_foreign_keys_to_org_or_notify_and_recipient_unit_id_is_plain_integer
  (FR-641) — (FR-601, FR-641)
- [ ] T-7137 [P] [sonnet] тесты изменения ядра, `org`, `knowledge` и прежнее поведение (план: «Изменения кода прежних
  срезов» — строки `core/extensions.py` (точка), `core/views/pages.py` и шаблоны главной, `core/context.py` и
  `menu_for`, `templates/base.html`, `core/models/files.py`, `core/services/comments.py`,
  `core/services/pdn_patterns.py` и `knowledge/services/pdn.py`, `org/services/structure.py`; «Модель данных» — «Ядро и
  прежние модули») — backend/tests/test_feed_core_changes.py::test_points_end_with_home_body_as_eighteenth_point
  (FR-641); backend/tests/test_feed_core_changes.py::test_previous_seventeen_points_keep_their_order (FR-641);
  backend/tests/test_feed_core_changes.py::test_home_body_uses_first_registered_function_and_skips_others (FR-601,
  FR-641); backend/tests/test_feed_core_changes.py::test_home_with_empty_home_body_point_renders_previous_home_template
  (FR-641); backend/tests/test_feed_core_changes.py::test_collect_notices_returns_same_as_previous_home_loop (FR-601);
  backend/tests/test_feed_core_changes.py::test_home_notices_fragment_keeps_previous_data_home_notices_notice_and_year_markup
  (FR-601, FR-641);
  backend/tests/test_feed_core_changes.py::test_shell_omits_home_item_when_menu_has_root_url_item_and_puts_that_item_first
  (FR-601); backend/tests/test_feed_core_changes.py::test_shell_without_root_url_item_puts_home_item_first (FR-641);
  backend/tests/test_feed_core_changes.py::test_menu_for_passes_live_badge_only_to_item_declaring_it (FR-626);
  backend/tests/test_feed_core_changes.py::test_menu_for_keys_of_other_items_unchanged (FR-641);
  backend/tests/test_feed_core_changes.py::test_base_renders_live_badge_node_always_hidden_at_zero_with_data_count_and_live_marker
  (FR-626); backend/tests/test_feed_core_changes.py::test_base_live_badge_shows_99_plus_above_99 (FR-626);
  backend/tests/test_feed_core_changes.py::test_base_other_items_have_data_menu_badge_only_above_zero_in_digits
  (FR-641); backend/tests/test_feed_core_changes.py::test_base_htmx_config_unchanged_with_default_allow_script_tags
  (FR-641); backend/tests/test_feed_core_changes.py::test_stored_file_purpose_feed_is_last_and_previous_values_unchanged
  (FR-633);
  backend/tests/test_feed_core_changes.py::test_comments_update_strips_edges_accepts_1_and_4000_chars_and_saves_text
  (FR-624);
  backend/tests/test_feed_core_changes.py::test_comments_update_rejects_empty_and_4001_chars_with_same_error_codes_as_add
  (FR-624); backend/tests/test_feed_core_changes.py::test_comments_add_list_for_delete_and_delete_for_behave_as_before
  (FR-624); backend/tests/test_feed_core_changes.py::test_comments_module_has_no_knowledge_or_article_words (FR-624);
  backend/tests/test_feed_core_changes.py::test_pdn_patterns_email_and_phone_keep_previous_expressions_and_knowledge_imports_them
  (FR-612); backend/tests/test_feed_core_changes.py::test_knowledge_find_and_mask_plain_give_same_results_on_string_set
  (FR-612);
  backend/tests/test_feed_core_changes.py::test_subtree_member_ids_equals_descendants_direct_members_with_secondary_jobs_without_dismissed_with_blocked_and_no_invited_in_data
  (FR-605); backend/tests/test_feed_core_changes.py::test_unit_chains_equals_unit_chain_ids_for_each_user_in_two_queries
  (FR-605); backend/tests/test_feed_core_changes.py::test_previous_structure_functions_keep_names_signatures_and_results
  (FR-605, FR-641) — (FR-601, FR-605, FR-612, FR-624, FR-626, FR-633, FR-641)
- [x] T-7140a [sonnet] обвязка приёмки (план: «Проверка», «Проход в браузере», «Стенд и приёмка»; деление — решение 45).
  Общие помощники backend/tests/e2e/helpers_feed.py (пишет только эта задача): роли и учётки сценариев (роль с правом
  «Писать всем», модератор ленты, сотрудник без прав ленты; подразделения «Отдел ИТ» с вложенной «Группой сети» и
  «Бухгалтерия», совместитель, Петров, Сидоров — через helpers.py и helpers_org.py); open_feed(context, account,
  live=True) — при live=True ждёт `#feed-live[data-ws="open"]`, при live=False (после block_ws, приёмка f08) ждёт только
  загрузки страницы; open_card(context, account, post_id); публикация формой publish / try_publish (вид, текст, «Кому»
  через подсказку, срок важного, поля события, файлы) и публикация запросом той же формы для объёмов; выбор из подсказки
  «Кому» и «@»; комментарий, «Нравится», «Прочитано», ответ на событие; чтение числа `#menu-badge-feed[data-count]` и
  ожидание его значения; ожидание плашки `#feed-new`; номера записей страницы и блока важных; загрузка файла и ожидание
  «проверяется → чистый» на ClamAV стенда, EICAR из частей; обёртки shift(minutes) над `e2e_feed_shift --minutes N`
  (сдвигает и `important_until` важных записей) и age(days, posts=None) над `e2e_feed_retention --age-days N [--posts
  <номера через запятую>]` через helpers_sd._stand_command с разбором строк `feed_shift: shifted=<N> reminded=<M>
  important=<K>` и `feed_retention: aged=<N> deleted=<M>` (решение 54); block_ws(context) — перехват `/ws/feed/` и
  `/ws/notify/` с закрытием через `BrowserContext.route_web_socket` Playwright 1.63 (решение 55); Mailpit, колокольчик и
  «Мои уведомления», учебная служба fakebots для Telegram, helpers_notify.tick для писем через 15 минут; проверка ширины
  360 px; имена помощников — одни для T-7140b…T-7154, их закрепляет контракт T-7100 в разделе «Помощники приёмки»
  (решение 8) — backend/tests/e2e/helpers_feed.py — (план: «Проверка» → «Проход в браузере»)
- [x] T-7140b [P] [sonnet] тесты приёмка сценария 1: публикация всем, подразделению и людям; кто видит, кто нет (план:
  «Проверка», «Проход в браузере», «Стенд и приёмка», «Публикация: форма, «Кому», подсказки», «Видимость и аудитория
  записи», «Запись в ленте и карточка», «Текст и упоминания», «Лента, курсор, блок важных, фильтры», «Безопасный вывод,
  язык, узкий экран», «Тексты отказов»; помощники — T-7140a) —
  backend/tests/e2e/test_f01_publish.py::test_f01_form_of_post_all_holder_opens_with_message_kind_and_all_in_to (FR-608,
  FR-610);
  backend/tests/e2e/test_f01_publish.py::test_f01_kind_switch_shows_term_field_for_important_and_event_fields_for_event_only
  (FR-608);
  backend/tests/e2e/test_f01_publish.py::test_f01_employee_without_post_all_has_no_all_in_to_and_chosen_recipient_is_removed_by_cross_before_publish
  (FR-610);
  backend/tests/e2e/test_f01_publish.py::test_f01_to_suggestion_finds_active_people_by_name_part_and_units_by_name_or_path_part_without_dismissed
  (FR-610);
  backend/tests/e2e/test_f01_publish.py::test_f01_post_to_all_appears_on_top_with_author_arrow_all_and_time_and_is_seen_by_other_active_employee
  (FR-603, FR-605, FR-608);
  backend/tests/e2e/test_f01_publish.py::test_f01_post_card_opens_at_permanent_address_for_recipient (FR-604);
  backend/tests/e2e/test_f01_publish.py::test_f01_unit_post_seen_by_nested_unit_member_and_part_timer_and_not_by_accounting_employee
  (FR-605);
  backend/tests/e2e/test_f01_publish.py::test_f01_new_unit_member_sees_earlier_post_and_transferred_member_no_longer_sees_it
  (FR-605);
  backend/tests/e2e/test_f01_publish.py::test_f01_post_to_unit_and_person_from_other_unit_seen_by_both_with_unit_and_short_name_in_recipients_line
  (FR-603, FR-605);
  backend/tests/e2e/test_f01_publish.py::test_f01_invisible_post_link_search_and_file_link_answer_like_missing_and_post_absent_from_feed
  (FR-604, FR-606);
  backend/tests/e2e/test_f01_publish.py::test_f01_empty_blank_or_over_10000_text_refused_with_reason_at_field_and_input_kept
  (FR-609, FR-642);
  backend/tests/e2e/test_f01_publish.py::test_f01_no_recipient_or_over_50_recipients_refused_with_reason_at_field_and_input_kept
  (FR-610, FR-642);
  backend/tests/e2e/test_f01_publish.py::test_f01_https_address_becomes_link_opening_in_new_tab_and_markup_shown_as_text
  (FR-609); backend/tests/e2e/test_f01_publish.py::test_f01_paragraphs_and_line_breaks_of_text_are_kept (FR-609);
  backend/tests/e2e/test_f01_publish.py::test_f01_only_mailto_becomes_link_ftp_and_javascript_stay_text_and_links_have_noopener_noreferrer
  (FR-609, NFR-605);
  backend/tests/e2e/test_f01_publish.py::test_f01_script_tag_and_attribute_breakout_in_text_shown_escaped_and_not_executed
  (NFR-605);
  backend/tests/e2e/test_f01_publish.py::test_f01_feed_of_45_posts_shows_20_then_next_20_by_more_posts_without_reload_then_last_5
  (FR-602); backend/tests/e2e/test_f01_publish.py::test_f01_employee_without_addressed_posts_sees_no_posts_yet (FR-602);
  backend/tests/e2e/test_f01_publish.py::test_f01_anonymous_visitor_goes_to_login_and_user_without_second_factor_to_factor_setup_without_feed
  (FR-601);
  backend/tests/e2e/test_f01_publish.py::test_f01_post_of_deleted_unit_seen_by_person_and_author_with_unit_deleted_and_person_in_recipients_line
  (FR-607);
  backend/tests/e2e/test_f01_publish.py::test_f01_eight_recipients_line_shows_first_five_and_4_more_and_full_list_on_click_with_mentioned_and_dismissed_mark
  (FR-603, FR-607);
  backend/tests/e2e/test_f01_publish.py::test_f01_feed_and_form_with_recipients_and_suggestions_have_no_horizontal_scroll_at_360px
  (NFR-606) — (FR-601, FR-602, FR-603, FR-604, FR-605, FR-606, FR-607, FR-608, FR-609, FR-610, FR-642, NFR-605, NFR-606)
- [x] T-7141 [P] [sonnet] тесты приёмка сценария 2: важная запись, «Прочитано», кто прочитал (план: «Проверка», «Проход
  в браузере», «Важное», «Лента, курсор, блок важных, фильтры», «Правка и удаление», «Уведомления», «Видимость и
  аудитория записи», «Безопасный вывод, язык, узкий экран», «Тексты отказов») —
  backend/tests/e2e/test_f02_important.py::test_f02_important_kind_offers_day_week_month_and_until_date_terms (FR-613);
  backend/tests/e2e/test_f02_important.py::test_f02_until_date_field_allows_choice_only_from_tomorrow_to_one_year_ahead
  (FR-613);
  backend/tests/e2e/test_f02_important.py::test_f02_week_important_post_for_unit_stands_in_block_above_feed_with_important_until_date_and_read_button
  (FR-602, FR-614);
  backend/tests/e2e/test_f02_important.py::test_f02_read_click_moves_card_from_block_into_feed_by_publish_time_without_reload_and_removes_read_button
  (FR-614);
  backend/tests/e2e/test_f02_important.py::test_f02_after_reload_read_post_stays_in_feed_out_of_block_and_read_cannot_be_undone
  (FR-614);
  backend/tests/e2e/test_f02_important.py::test_f02_author_sees_read_12_of_40_and_on_click_readers_with_time_and_non_readers
  (FR-615); backend/tests/e2e/test_f02_important.py::test_f02_ordinary_recipient_sees_only_read_12_without_lists
  (FR-615);
  backend/tests/e2e/test_f02_important.py::test_f02_moderator_among_recipients_sees_author_lists_and_moderator_not_addressed_does_not_see_post
  (FR-606, FR-615);
  backend/tests/e2e/test_f02_important.py::test_f02_after_term_expiry_unread_post_left_block_and_stands_in_feed_as_ordinary_without_reminders
  (FR-613, FR-614);
  backend/tests/e2e/test_f02_important.py::test_f02_until_date_13_months_ahead_or_yesterday_refused_with_reason_at_term_field
  (FR-613, FR-642);
  backend/tests/e2e/test_f02_important.py::test_f02_author_sees_own_important_post_in_feed_by_time_not_in_block_and_unread_recipient_sees_it_only_in_block
  (FR-602, FR-614);
  backend/tests/e2e/test_f02_important.py::test_f02_expired_day_term_post_shows_was_important_mark_and_read_5 (FR-613);
  backend/tests/e2e/test_f02_important.py::test_f02_author_edit_form_makes_expired_post_important_for_week_counted_from_edit_date_and_keeps_reads
  (FR-613, FR-620);
  backend/tests/e2e/test_f02_important.py::test_f02_petrov_added_to_to_by_edit_gets_important_post_and_when_also_mentioned_gets_you_were_mentioned
  (FR-629, FR-630);
  backend/tests/e2e/test_f02_important.py::test_f02_dismissed_and_blocked_recipients_excluded_from_m_37_and_from_both_lists
  (FR-605, FR-615);
  backend/tests/e2e/test_f02_important.py::test_f02_important_block_and_readers_lists_have_no_horizontal_scroll_at_360px
  (NFR-606) — (FR-602, FR-605, FR-606, FR-613, FR-614, FR-615, FR-620, FR-629, FR-630, FR-642, NFR-606)
- [x] T-7142 [P] [sonnet] тесты приёмка сценария 3: событие, ответы, напоминание (план: «Проверка», «Проход в браузере»,
  «Событие и напоминания», «Стенд и приёмка», «Правка и удаление», «Уведомления», «Видимость и аудитория записи»,
  «Безопасный вывод, язык, узкий экран», «Тексты отказов») —
  backend/tests/e2e/test_f03_event.py::test_f03_event_with_title_start_end_place_and_unit_published_with_event_block_and_go_and_cant_buttons_for_participants
  (FR-616, FR-617);
  backend/tests/e2e/test_f03_event.py::test_f03_end_not_after_start_past_start_empty_or_over_200_title_refused_with_reason_at_field
  (FR-616, FR-642);
  backend/tests/e2e/test_f03_event.py::test_f03_empty_or_over_200_place_refused_with_reason_at_place_field (FR-616,
  FR-642); backend/tests/e2e/test_f03_event.py::test_f03_participant_changes_go_to_cant_before_start (FR-617);
  backend/tests/e2e/test_f03_event.py::test_f03_author_sees_go_cant_and_no_answer_lists_and_other_viewers_see_only_numbers
  (FR-617);
  backend/tests/e2e/test_f03_event.py::test_f03_shift_to_hour_before_start_gives_one_event_reminder_to_participants_except_cant_answers
  (FR-618, FR-629);
  backend/tests/e2e/test_f03_event.py::test_f03_start_moved_later_gives_event_changed_and_reminder_at_hour_before_new_start_not_old
  (FR-619, FR-629);
  backend/tests/e2e/test_f03_event.py::test_f03_started_event_has_no_answer_buttons_and_direct_answer_request_refused_with_answers_closed
  (FR-617, FR-642); backend/tests/e2e/test_f03_event.py::test_f03_non_participant_gets_nothing_at_reminder_time (FR-606,
  FR-618); backend/tests/e2e/test_f03_event.py::test_f03_author_without_answer_buttons_always_gets_reminder (FR-617,
  FR-618);
  backend/tests/e2e/test_f03_event.py::test_f03_petrov_added_by_edit_gets_invitation_sidorov_mentioned_gets_you_were_mentioned_and_both_answer_and_get_reminder
  (FR-611, FR-618, FR-629, FR-630);
  backend/tests/e2e/test_f03_event.py::test_f03_moderator_participant_sees_only_go_and_cant_numbers_without_lists
  (FR-617);
  backend/tests/e2e/test_f03_event.py::test_f03_event_published_half_hour_before_start_gives_invitation_only_and_no_reminder
  (FR-618);
  backend/tests/e2e/test_f03_event.py::test_f03_event_starting_in_a_day_gives_reminder_once_shifted_to_reminder_time
  (FR-618);
  backend/tests/e2e/test_f03_event.py::test_f03_start_moved_two_hours_later_after_sent_reminder_gives_event_changed_and_new_reminder
  (FR-619); backend/tests/e2e/test_f03_event.py::test_f03_title_or_description_edit_gives_no_notifications (FR-619);
  backend/tests/e2e/test_f03_event.py::test_f03_edit_with_past_start_refused_with_start_already_passed (FR-619, FR-642);
  backend/tests/e2e/test_f03_event.py::test_f03_started_event_refuses_start_end_place_change_and_changes_title_and_description_without_notifications
  (FR-619, FR-642); backend/tests/e2e/test_f03_event.py::test_f03_dismissed_participant_absent_from_no_answer_list
  (FR-617);
  backend/tests/e2e/test_f03_event.py::test_f03_event_block_and_answer_lists_have_no_horizontal_scroll_at_360px
  (NFR-606) — (FR-606, FR-611, FR-616, FR-617, FR-618, FR-619, FR-629, FR-630, FR-642, NFR-606)
- [x] T-7143 [P] [sonnet] тесты приёмка сценария 4: комментарии (план: «Проверка», «Проход в браузере», «Комментарии»,
  «Текст и упоминания», «Файлы и эскизы», «Уведомления», «Безопасный вывод, язык, узкий экран», «Тексты отказов») —
  backend/tests/e2e/test_f04_comments.py::test_f04_sent_comment_appears_at_bottom_of_list_with_author_name_and_time
  (FR-623);
  backend/tests/e2e/test_f04_comments.py::test_f04_feed_shows_last_three_of_8_comments_and_show_all_8_opens_all_by_time_flat_without_reload
  (FR-623); backend/tests/e2e/test_f04_comments.py::test_f04_post_card_shows_all_comments (FR-623);
  backend/tests/e2e/test_f04_comments.py::test_f04_reply_inserts_author_mention_into_comment_field_and_sent_comment_shows_author_name
  (FR-611, FR-623); backend/tests/e2e/test_f04_comments.py::test_f04_empty_or_over_4000_comment_refused_with_reason
  (FR-623, FR-642); backend/tests/e2e/test_f04_comments.py::test_f04_four_files_on_comment_refused_with_reason (FR-633,
  FR-642);
  backend/tests/e2e/test_f04_comments.py::test_f04_post_author_and_earlier_commenter_get_new_comment_when_third_employee_comments
  (FR-629, FR-630);
  backend/tests/e2e/test_f04_comments.py::test_f04_three_comments_in_row_give_one_new_comment_notification_per_post
  (FR-629, FR-630);
  backend/tests/e2e/test_f04_comments.py::test_f04_my_notifications_show_one_new_comment_notification_with_3_new_and_link_to_first_unread_comment
  (FR-629, FR-630, FR-631);
  backend/tests/e2e/test_f04_comments.py::test_f04_knowledge_article_comments_still_have_no_edit_mention_like_or_files
  (FR-624); backend/tests/e2e/test_f04_comments.py::test_f04_post_card_with_comments_has_no_horizontal_scroll_at_360px
  (NFR-606) — (FR-611, FR-623, FR-624, FR-629, FR-630, FR-631, FR-633, FR-642, NFR-606)
- [x] T-7144 [P] [sonnet] тесты приёмка сценария 5: «Мне нравится» (план: «Проверка», «Проход в браузере», «„Нравится“»,
  «Уведомления», «Безопасный вывод, язык, узкий экран») —
  backend/tests/e2e/test_f05_likes.py::test_f05_like_click_sets_mark_with_own_name_and_second_click_removes_it (FR-625);
  backend/tests/e2e/test_f05_likes.py::test_f05_five_likers_line_shows_two_latest_names_and_3_more_and_full_list_on_click
  (FR-625);
  backend/tests/e2e/test_f05_likes.py::test_f05_two_likes_of_petrov_comment_give_him_one_portal_notification_without_letter_or_messenger_message
  (FR-629, FR-631); backend/tests/e2e/test_f05_likes.py::test_f05_author_liking_own_post_gets_no_notification (FR-630);
  backend/tests/e2e/test_f05_likes.py::test_f05_three_likes_give_one_like_notification_with_last_liker_kozlov_and_2_more_linking_to_post
  (FR-629, FR-631); backend/tests/e2e/test_f05_likes.py::test_f05_likers_list_has_no_horizontal_scroll_at_360px
  (NFR-606) — (FR-625, FR-629, FR-630, FR-631, NFR-606)
- [x] T-7145 [P] [sonnet] тесты приёмка сценария 6: упоминания (план: «Проверка», «Проход в браузере», «Текст и
  упоминания», «Публикация: форма, «Кому», подсказки», «Уведомления», «Тексты отказов») —
  backend/tests/e2e/test_f06_mentions.py::test_f06_at_pet_opens_suggestion_of_active_employees_without_dismissed
  (FR-611);
  backend/tests/e2e/test_f06_mentions.py::test_f06_chosen_employee_shown_in_text_as_at_full_name_and_in_to_as_mentioned_pill_without_cross
  (FR-611); backend/tests/e2e/test_f06_mentions.py::test_f06_publish_sends_at_id_marker_instead_of_chosen_full_name
  (FR-611);
  backend/tests/e2e/test_f06_mentions.py::test_f06_mentioned_petrov_from_other_unit_sees_post_with_name_link_to_his_card_and_gets_you_were_mentioned
  (FR-605, FR-611, FR-629);
  backend/tests/e2e/test_f06_mentions.py::test_f06_sidorov_mentioned_in_comment_becomes_recipient_sees_post_with_all_comments_and_gets_you_were_mentioned
  (FR-605, FR-611, FR-629); backend/tests/e2e/test_f06_mentions.py::test_f06_self_mention_gives_no_notification
  (FR-630); backend/tests/e2e/test_f06_mentions.py::test_f06_unit_name_after_at_not_offered_in_suggestion (FR-611);
  backend/tests/e2e/test_f06_mentions.py::test_f06_21_distinct_mentions_refused_with_reason_and_post_not_published
  (FR-611, FR-642) — (FR-605, FR-611, FR-629, FR-630, FR-642)
- [x] T-7146 [P] [sonnet] тесты приёмка сценария 7: правка и удаление, модератор (план: «Проверка», «Проход в браузере»,
  «Правка и удаление», «Видимость и аудитория записи», «Журнал») —
  backend/tests/e2e/test_f07_edit_delete.py::test_f07_author_edits_text_and_post_shows_new_text_and_edited_mark_with_time
  (FR-620); backend/tests/e2e/test_f07_edit_delete.py::test_f07_person_added_to_unit_post_by_edit_sees_post (FR-620);
  backend/tests/e2e/test_f07_edit_delete.py::test_f07_saved_recipients_have_no_remove_cross_and_direct_removal_request_refused
  (FR-620);
  backend/tests/e2e/test_f07_edit_delete.py::test_f07_employee_without_moderate_right_sees_no_edit_or_delete_on_others_post_and_direct_requests_refused
  (FR-620, FR-621);
  backend/tests/e2e/test_f07_edit_delete.py::test_f07_moderator_sees_delete_but_no_edit_on_others_post_and_direct_edit_refused
  (FR-620, FR-621);
  backend/tests/e2e/test_f07_edit_delete.py::test_f07_author_delete_after_confirm_removes_post_with_comments_files_and_likes_and_link_answers_like_missing
  (FR-621);
  backend/tests/e2e/test_f07_edit_delete.py::test_f07_author_edit_and_delete_of_own_post_leave_no_journal_entries
  (FR-639);
  backend/tests/e2e/test_f07_edit_delete.py::test_f07_moderator_deletes_others_post_and_journal_shows_post_deleted_with_author_time_and_deleter_without_text
  (FR-621, FR-639);
  backend/tests/e2e/test_f07_edit_delete.py::test_f07_moderator_deletes_others_comment_and_journal_entry_has_no_text
  (FR-622, FR-639);
  backend/tests/e2e/test_f07_edit_delete.py::test_f07_comment_author_edits_with_edited_mark_and_deletes_own_comment_without_journal_entries
  (FR-622, FR-639);
  backend/tests/e2e/test_f07_edit_delete.py::test_f07_post_author_sees_no_delete_on_others_comment_and_direct_request_refused
  (FR-622);
  backend/tests/e2e/test_f07_edit_delete.py::test_f07_moderator_not_addressed_gets_missing_answer_and_after_mention_in_comment_sees_and_deletes_post
  (FR-606, FR-611, FR-621) — (FR-606, FR-611, FR-620, FR-621, FR-622, FR-639)
- [x] T-7147 [P] [sonnet] тесты приёмка сценария 8: живое обновление и непрочитанное (план: «Проверка», «Проход в
  браузере», «Живые обновления», «Непрочитанное», «Главная, меню и число у «Ленты»», «Лента, курсор, блок важных,
  фильтры», «Стенд и приёмка») —
  backend/tests/e2e/test_f08_live.py::test_f08_colleague_post_gives_new_posts_1_banner_and_feed_badge_plus_1_within_2s_without_inserting_post
  (FR-626, FR-627, NFR-602);
  backend/tests/e2e/test_f08_live.py::test_f08_new_posts_2_banner_click_puts_two_posts_on_top_and_hides_banner (FR-627);
  backend/tests/e2e/test_f08_live.py::test_f08_comment_on_shown_post_appears_in_place_within_2s (FR-627, NFR-602);
  backend/tests/e2e/test_f08_live.py::test_f08_like_on_shown_post_appears_in_place_within_2s (FR-627, NFR-602);
  backend/tests/e2e/test_f08_live.py::test_f08_edit_of_shown_post_appears_in_place_within_2s (FR-627, NFR-602);
  backend/tests/e2e/test_f08_live.py::test_f08_delete_of_shown_post_removes_it_from_page_within_2s (FR-627, NFR-602);
  backend/tests/e2e/test_f08_live.py::test_f08_open_post_card_gets_new_comment_in_place_within_2s_and_no_banner (FR-627,
  NFR-602); backend/tests/e2e/test_f08_live.py::test_f08_feed_badge_changes_live_on_other_portal_page (FR-626, FR-627);
  backend/tests/e2e/test_f08_live.py::test_f08_like_button_of_comment_inserted_by_frame_sends_request_and_sets_like
  (FR-627);
  backend/tests/e2e/test_f08_live.py::test_f08_post_only_for_petrov_gives_other_open_feeds_no_banner_badge_or_fragment_on_publish_and_comment
  (FR-628);
  backend/tests/e2e/test_f08_live.py::test_f08_opening_feed_with_3_unread_posts_drops_feed_badge_to_zero_and_own_post_never_unread
  (FR-626); backend/tests/e2e/test_f08_live.py::test_f08_120_unread_posts_show_99_plus_at_feed_item (FR-626);
  backend/tests/e2e/test_f08_live.py::test_f08_without_websocket_publish_comment_like_and_more_posts_work_by_plain_requests_and_new_seen_after_reload
  (FR-628);
  backend/tests/e2e/test_f08_live.py::test_f08_logout_from_all_devices_closes_open_tab_connection_within_35s_and_no_more_fragments
  (FR-627);
  backend/tests/e2e/test_f08_live.py::test_f08_blocking_employee_closes_open_tab_connection_within_35s_and_no_more_fragments
  (FR-627);
  backend/tests/e2e/test_f08_live.py::test_f08_dismissing_employee_closes_open_tab_connection_within_35s_and_no_more_fragments
  (FR-627);
  backend/tests/e2e/test_f08_live.py::test_f08_newcomer_of_unit_with_50_old_and_3_recent_posts_has_feed_badge_3_and_old_posts_in_feed
  (FR-626);
  backend/tests/e2e/test_f08_live.py::test_f08_ordinary_and_important_posts_give_new_posts_2_and_click_puts_important_in_block_and_ordinary_on_top
  (FR-602, FR-627);
  backend/tests/e2e/test_f08_live.py::test_f08_edit_and_comment_of_shown_post_do_not_make_it_unread_or_raise_feed_badge
  (FR-626); backend/tests/e2e/test_f08_live.py::test_f08_new_posts_2_banner_click_lowers_feed_badge_by_2 (FR-626,
  FR-627); backend/tests/e2e/test_f08_live.py::test_f08_own_comment_in_same_tab_is_shown_once_after_frame_arrives
  (FR-627) — (FR-602, FR-626, FR-627, FR-628, NFR-602)
- [x] T-7148 [P] [sonnet] тесты приёмка сценария 9: уведомления ленты по каналам (план: «Проверка», «Проход в браузере»,
  «Уведомления») —
  backend/tests/e2e/test_f09_notify.py::test_f09_personal_addressee_gets_record_for_you_on_bell_with_author_and_snippet_up_to_100_chars
  (FR-629, FR-631);
  backend/tests/e2e/test_f09_notify.py::test_f09_plain_post_to_all_or_unit_without_mentions_gives_no_notification_and_raises_feed_menu_count
  (FR-626, FR-629);
  backend/tests/e2e/test_f09_notify.py::test_f09_mention_sends_telegram_only_mentioned_in_feed_text_and_link_without_name_title_or_snippet
  (FR-631, NFR-609);
  backend/tests/e2e/test_f09_notify.py::test_f09_mention_mail_comes_after_unread_term_with_author_and_snippet_and_not_if_read_before_term
  (FR-631);
  backend/tests/e2e/test_f09_notify.py::test_f09_event_invite_and_event_changed_telegram_messages_have_no_event_title_place_or_name
  (FR-631, NFR-609);
  backend/tests/e2e/test_f09_notify.py::test_f09_my_notifications_shows_feed_section_with_eight_kinds_and_employee_toggles_mail_push_telegram_max
  (FR-629, FR-631);
  backend/tests/e2e/test_f09_notify.py::test_f09_like_kind_has_only_portal_channel_in_employee_table_and_in_admin_defaults
  (FR-629, FR-631);
  backend/tests/e2e/test_f09_notify.py::test_f09_post_deleted_by_author_or_moderator_after_notification_sends_no_delayed_mail_and_bell_link_gives_not_found
  (FR-630, FR-632);
  backend/tests/e2e/test_f09_notify.py::test_f09_post_purged_by_retention_keeps_bell_notification_and_its_link_gives_not_found
  (FR-630, FR-632);
  backend/tests/e2e/test_f09_notify.py::test_f09_link_from_already_sent_mail_of_deleted_post_gives_not_found (FR-630,
  FR-632);
  backend/tests/e2e/test_f09_notify.py::test_f09_important_personal_post_with_mention_gives_single_mentioned_notification
  (FR-630); backend/tests/e2e/test_f09_notify.py::test_f09_author_mentioning_or_addressing_self_gets_no_notification
  (FR-630);
  backend/tests/e2e/test_f09_notify.py::test_f09_mention_in_quiet_hours_shows_on_portal_at_once_and_mail_and_telegram_wait_for_digest
  (FR-631);
  backend/tests/e2e/test_f09_notify.py::test_f09_employee_moved_out_of_addressee_unit_gets_no_mail_and_notification_link_gives_not_found
  (FR-630);
  backend/tests/e2e/test_f09_notify.py::test_f09_event_changed_notification_cuts_200_char_title_and_place_to_60_and_whole_text_to_300
  (FR-629, FR-631) — (FR-626, FR-629, FR-630, FR-631, FR-632, NFR-609)
- [x] T-7149 [P] [sonnet] тесты приёмка сценария 10: файлы и картинки записи (план: «Проверка», «Проход в браузере»,
  «Файлы и эскизы») —
  backend/tests/e2e/test_f10_files.py::test_f10_png_and_pdf_of_post_are_listed_as_checking_or_already_clean_without_link_then_clean
  (FR-633, FR-634);
  backend/tests/e2e/test_f10_files.py::test_f10_checking_file_direct_url_gives_not_found_with_still_checking_text
  (FR-634, FR-642);
  backend/tests/e2e/test_f10_files.py::test_f10_clean_status_appears_within_one_minute_of_attach_on_stand_clamav
  (NFR-604);
  backend/tests/e2e/test_f10_files.py::test_f10_clean_image_in_post_and_comment_shows_reduced_and_click_opens_full_image
  (FR-634); backend/tests/e2e/test_f10_files.py::test_f10_clean_pdf_shows_name_size_and_download_gives_file (FR-634);
  backend/tests/e2e/test_f10_files.py::test_f10_eicar_file_goes_to_quarantine_with_mark_and_is_not_downloadable_by_link_or_direct_url
  (FR-634, FR-642, NFR-604);
  backend/tests/e2e/test_f10_files.py::test_f10_eleventh_file_to_post_and_fourth_to_comment_are_refused_with_reason
  (FR-633, FR-642);
  backend/tests/e2e/test_f10_files.py::test_f10_file_over_20mb_executable_and_password_archive_are_refused_with_reason
  (FR-633, FR-642, NFR-604);
  backend/tests/e2e/test_f10_files.py::test_f10_executable_renamed_to_pdf_is_refused_by_content_type (FR-633, FR-642);
  backend/tests/e2e/test_f10_files.py::test_f10_author_removes_attached_file_before_publish_and_post_has_no_such_file
  (FR-633);
  backend/tests/e2e/test_f10_files.py::test_f10_author_removes_file_when_editing_post_and_its_url_gives_not_found
  (FR-633);
  backend/tests/e2e/test_f10_files.py::test_f10_file_and_image_urls_of_invisible_post_give_same_answer_as_missing_file
  (FR-606, FR-634) — (FR-606, FR-633, FR-634, FR-642, NFR-604)
- [x] T-7150 [P] [sonnet] тесты приёмка сценария 11: фильтры ленты и сквозной поиск (план: «Проверка», «Проход в
  браузере», «Лента, курсор, блок важных, фильтры», «Поиск») —
  backend/tests/e2e/test_f11_search.py::test_f11_filters_important_events_mine_and_mentions_me_show_only_such_posts
  (FR-635);
  backend/tests/e2e/test_f11_search.py::test_f11_mentions_me_filter_shows_post_where_employee_is_mentioned_only_in_comment
  (FR-635);
  backend/tests/e2e/test_f11_search.py::test_f11_author_filter_with_period_shows_that_authors_posts_published_in_period_inclusive
  (FR-635);
  backend/tests/e2e/test_f11_search.py::test_f11_author_suggestion_finds_active_and_dismissed_employees_by_part_of_name_as_full_name_rows
  (FR-635); backend/tests/e2e/test_f11_search.py::test_f11_filter_choice_is_in_page_address_and_filters_combine_by_and
  (FR-635); backend/tests/e2e/test_f11_search.py::test_f11_empty_result_of_filter_says_no_posts_by_filter (FR-635);
  backend/tests/e2e/test_f11_search.py::test_f11_unknown_filter_key_or_wrong_value_in_address_is_ignored_without_server_error
  (FR-635, NFR-608);
  backend/tests/e2e/test_f11_search.py::test_f11_top_search_finds_post_by_word_form_and_comment_by_word_start_in_feed_group_as_name_date_text_rows
  (FR-636);
  backend/tests/e2e/test_f11_search.py::test_f11_found_post_row_opens_post_card_and_found_comment_row_opens_comment_anchor
  (FR-636);
  backend/tests/e2e/test_f11_search.py::test_f11_invisible_post_and_its_comments_are_absent_and_feed_group_shows_no_count_for_them
  (FR-606, FR-636);
  backend/tests/e2e/test_f11_search.py::test_f11_deleted_post_and_old_text_of_edited_post_are_not_found_and_new_text_is_found
  (FR-637);
  backend/tests/e2e/test_f11_search.py::test_f11_deleted_comment_and_old_text_of_edited_comment_are_not_found_and_new_text_is_found
  (FR-637);
  backend/tests/e2e/test_f11_search.py::test_f11_event_found_by_title_and_place_word_forms_as_row_with_event_title
  (FR-636); backend/tests/e2e/test_f11_search.py::test_f11_feed_group_rows_go_from_newer_to_older (FR-636);
  backend/tests/e2e/test_f11_search.py::test_f11_word_only_in_attached_file_content_does_not_find_post (FR-636);
  backend/tests/e2e/test_f11_search.py::test_f11_mentions_me_filter_shows_unread_important_post_by_publication_time_without_important_block
  (FR-602, FR-635);
  backend/tests/e2e/test_f11_search.py::test_f11_all_filter_without_author_and_period_shows_same_important_post_in_block_not_repeated_in_feed
  (FR-602, FR-635); backend/tests/e2e/test_f11_search.py::test_f11_search_results_and_filters_do_not_widen_page_at_360px
  (NFR-606) — (FR-602, FR-606, FR-635, FR-636, FR-637, NFR-606, NFR-608)
- [x] T-7151 [P] [sonnet] тесты приёмка сценария 12: срок хранения и ночное задание (план: «Проверка», «Проход в
  браузере», «Срок хранения и ночное задание», «Журнал»; повтор ночного задания — `age(1, posts=[<свежая запись
  теста>])`, решение 54) —
  backend/tests/e2e/test_f12_retention.py::test_f12_new_install_feed_settings_page_shows_keep_posts_3_years (FR-638);
  backend/tests/e2e/test_f12_retention.py::test_f12_retention_0_11_or_not_a_number_is_refused_with_reason_and_value_kept
  (FR-638, FR-642);
  backend/tests/e2e/test_f12_retention.py::test_f12_decrease_from_3_to_1_shows_warning_with_number_of_posts_night_job_will_delete_and_confirm
  (FR-638); backend/tests/e2e/test_f12_retention.py::test_f12_decrease_without_confirm_leaves_retention_unchanged
  (FR-638);
  backend/tests/e2e/test_f12_retention.py::test_f12_confirmed_decrease_appears_in_journal_as_years_before_after (FR-638,
  FR-639); backend/tests/e2e/test_f12_retention.py::test_f12_increase_is_saved_at_once_without_confirm (FR-638);
  backend/tests/e2e/test_f12_retention.py::test_f12_post_aged_3_years_and_1_day_is_deleted_by_night_job_with_comments_files_likes_reads_and_event_answers
  (FR-638); backend/tests/e2e/test_f12_retention.py::test_f12_post_aged_less_than_term_is_kept_by_night_job (FR-638);
  backend/tests/e2e/test_f12_retention.py::test_f12_old_post_edited_and_commented_recently_is_deleted_by_term_from_publication
  (FR-638); backend/tests/e2e/test_f12_retention.py::test_f12_old_post_of_dismissed_employee_is_deleted_by_same_term
  (FR-638);
  backend/tests/e2e/test_f12_retention.py::test_f12_night_job_journal_shows_deleted_by_retention_posts_count_without_text
  (FR-639);
  backend/tests/e2e/test_f12_retention.py::test_f12_repeated_night_job_deletes_nothing_adds_no_journal_entry_and_gives_no_error
  (FR-638, FR-639, NFR-610);
  backend/tests/e2e/test_f12_retention.py::test_f12_feed_settings_page_without_portal_settings_right_is_forbidden
  (FR-638);
  backend/tests/e2e/test_f12_retention.py::test_f12_feed_settings_page_and_decrease_warning_do_not_widen_page_at_360px
  (NFR-606) — (FR-638, FR-639, FR-642, NFR-606, NFR-610)
- [x] T-7152 [P] [sonnet] тесты приёмка сценария 13: права «Писать всем» и «Модерировать ленту» (план: «Проверка»,
  «Проход в браузере», «Права и данные установки», «Публикация: форма, «Кому», подсказки», «Журнал») —
  backend/tests/e2e/test_f13_rights.py::test_f13_roles_page_after_install_shows_post_all_at_three_starter_roles_and_moderate_only_at_portal_admin
  (FR-640);
  backend/tests/e2e/test_f13_rights.py::test_f13_it_staff_role_without_post_all_has_no_all_option_in_to_but_units_and_people
  (FR-610, FR-640);
  backend/tests/e2e/test_f13_rights.py::test_f13_new_post_to_all_sent_bypassing_form_without_post_all_is_refused
  (FR-610); backend/tests/e2e/test_f13_rights.py::test_f13_role_rights_change_appears_in_roles_journal_as_before_after
  (FR-639); backend/tests/e2e/test_f13_rights.py::test_f13_employee_without_moderate_right_sees_no_delete_on_others_post
  (FR-621, FR-640);
  backend/tests/e2e/test_f13_rights.py::test_f13_moderate_right_given_to_role_in_interface_shows_delete_on_others_post
  (FR-621, FR-640);
  backend/tests/e2e/test_f13_rights.py::test_f13_role_created_after_install_has_no_post_all_until_it_is_checked
  (FR-640);
  backend/tests/e2e/test_f13_rights.py::test_f13_employee_without_roles_has_no_all_option_but_publishes_to_unit_and_people
  (FR-608, FR-610, FR-640);
  backend/tests/e2e/test_f13_rights.py::test_f13_adding_all_to_own_unit_post_bypassing_form_without_post_all_is_refused
  (FR-610, FR-620);
  backend/tests/e2e/test_f13_rights.py::test_f13_removing_post_all_keeps_earlier_post_to_all_visible_and_author_edits_it_keeping_all
  (FR-620, FR-640) — (FR-608, FR-610, FR-620, FR-621, FR-639, FR-640)
- [x] T-7153 [P] [sonnet] тесты приёмка сценария 14: главная, меню, узкий экран (план: «Проверка», «Проход в браузере»,
  «Главная, меню и число у «Ленты»», «Безопасный вывод, язык, узкий экран») —
  backend/tests/e2e/test_f14_home.py::test_f14_list_record_deadline_reminder_stands_as_block_above_post_form_and_feed
  (FR-601); backend/tests/e2e/test_f14_home.py::test_f14_feed_menu_item_is_first_leads_to_home_and_home_item_is_absent
  (FR-601, FR-641);
  backend/tests/e2e/test_f14_home.py::test_f14_home_with_feed_has_no_greeting_and_profile_security_and_section_cards
  (FR-601, FR-641);
  backend/tests/e2e/test_f14_home.py::test_f14_home_without_login_leads_to_login_and_back_to_feed_by_next (FR-601);
  backend/tests/e2e/test_f14_home.py::test_f14_feed_post_card_and_post_form_with_recipients_do_not_widen_page_at_360px
  (NFR-606);
  backend/tests/e2e/test_f14_home.py::test_f14_event_block_likers_list_and_search_results_do_not_widen_page_at_360px
  (NFR-606); backend/tests/e2e/test_f14_home.py::test_f14_long_link_and_long_name_wrap_and_thumbnail_fits_width_at_360px
  (NFR-606) — (FR-601, FR-641, NFR-606)
- [x] T-7154 [P] [sonnet] тесты приёмка сценария 15: предупреждение о ПДн (план: «Проверка», «Проход в браузере»,
  «Предупреждение о ПДн») —
  backend/tests/e2e/test_f15_pdn.py::test_f15_post_with_phone_and_email_shows_warning_listing_found_with_fix_and_publish_anyway
  (FR-612); backend/tests/e2e/test_f15_pdn.py::test_f15_fix_leaves_post_unpublished_and_form_open_with_entered_text
  (FR-612); backend/tests/e2e/test_f15_pdn.py::test_f15_publish_anyway_publishes_post (FR-612);
  backend/tests/e2e/test_f15_pdn.py::test_f15_comment_with_phone_or_email_shows_same_warning_and_publish_anyway_publishes_comment
  (FR-612);
  backend/tests/e2e/test_f15_pdn.py::test_f15_post_edit_adding_email_shows_warning_with_save_anyway_which_saves
  (FR-612); backend/tests/e2e/test_f15_pdn.py::test_f15_email_or_phone_in_event_title_or_place_shows_warning (FR-612);
  backend/tests/e2e/test_f15_pdn.py::test_f15_email_inside_backticks_still_shows_warning (FR-612) — (FR-612)
- [ ] T-7138 [sonnet] (после T-7101: нужны `support_feed.without_feed()` и константы `PERMISSIONS_007`, `TITLES_007`,
  `POINTS_007`, `APPS_TAIL`, `FEED_KINDS`, `FEED_CODES`, `FEED_TITLES`, `FEED_MODULE`, `FEED_LIKE`, `FEED_BOXED`, `FEED_JOBS`; без
  `[P]` — решение 31) правка тестов срезов 001–006, которые меняются вместе со срезом 007, тремя заданиями агенту
  (первое — пункты 1–26: точки, поля, хвост `INSTALLED_APPS`, сброс стенда, cron, nginx, слой каналов, права, меню;
  второе — пункты 27–43: каталог уведомлений, поиск, колокольчик; третье — приёмка, пункты 44 и 45) — серверные тесты
  (пункты 1–43 раздела «Ломаются или становятся неверными» анализа влияния `crm-work/slice007/tasks/impact.md`) и
  приёмка (пункты 44, 45). Правило: каждая правка — только с разрешения владельца, по одному тесту, с диффом; разрешение
  спрашивает Opus до правки, исполнитель правит только после ответа; точное «было / стало» — `impact.md` и раздел «Что
  меняется в прежних контрактах» `CONTRACT-007.md`; спорные пункты `impact.md` («решить в TASKS-007») — по решению 43.
  Строки `файл:строка` ниже — по коммиту e7ca1db, при сдвиге искать по утверждению. Определённо (45 пунктов): п. 1–5 —
  восемнадцать точек: `test_extensions.py:74-75, 103` (`+ POINTS_007`, «восемнадцать»), `test_kb_boundaries.py:23,
  357-359` (`POINTS_18`, 18), `:369` (`POINTS[-3:-1]` — точки среза 005, последняя — `home_body`),
  `test_lists_boundaries.py:24, 258-260` (как п. 2), `test_sd_boundaries.py:434` (`POINTS_17 + ("home_body",)`); п. 6–7
  — пятнадцать полей `NotificationKind`: `test_lists_reminders_2.py:405` (последние — `channels`, `coalesce_text`),
  `test_notify_catalog.py:148-149, 160` (список полей, `channels` и `coalesce_text` по умолчанию `None`; план этого
  теста не называет); п. 8–12 — хвост `INSTALLED_APPS` и порядок сброса стенда: `test_kb_deploy.py:118` (`[-5:]`,
  `apps.feed` последним), `test_notify_deploy.py:357` и `test_lists_deploy.py:126-127` (`[-6:] == APPS_TAIL`),
  `test_kb_deploy.py:585-586` (`apps.feed.stand` последний, перед ним `apps.lists.stand` и `apps.knowledge.stand`),
  `test_lists_stand.py:360, 361, 364` (`registered[-2]`, `names[-1] == "apps.feed.stand"`, `call_order[0] ==
  "apps.feed.stand"`); п. 13–16 — двадцать вызовов `register` в `config/cron.py`: `test_notify_deploy.py:321-322`,
  `test_kb_deploy.py:129-130`, `test_sd_deploy.py:414` (задания среза 007 — отдельным циклом по `FEED_JOBS`, не в цикле
  «имя = функция» 400–406), `test_lists_deploy.py:166`; п. 17 — `test_deploy_files.py:359-371` (блок `^/feed/files/$` с
  `25m` вычитывается отдельно от цикла `55m`); п. 18–19 — слой каналов: `test_notify_deploy.py:384-389` (ключи `default`
  и `publish`, `default` прежний), `test_notify_ws.py:638-647` (подменный слой принимает аргумент: тест не падает, но
  перестаёт проверять сбой слоя); п. 20–23 — восемнадцать прав: `test_permissions.py:35-37` (`+ PERMISSIONS_007`,
  «Писать всем» у «Сотрудника ИТ» и «Руководителя»), `test_sd_access.py:538-541` (18 прав),
  `test_org_permissions.py:137-151` (перечень, `TITLES_007`, держатели), `test_lists_seed.py:173-175` (17, затем 18); п.
  24–26 — меню: `test_org_permissions.py:682-691` (четырнадцать пунктов, «Лента» первой с `badge` и `live_badge`,
  «Настройки ленты» с `order` 63), `test_lists_access.py:863` (14), `test_sd_boundaries.py:680-685` (во втором вызове не
  возвращать регистрации `apps.feed`); п. 27–39 — каталог уведомлений (двадцать видов шести модулей):
  `test_notify_catalog.py:3, 22-53, 106-116` (`TABLE` — восемь строк «Лента», сверка `kind.channels`),
  `test_notify_catalog_2.py:228, 235-236` (`+ FEED_CODES`, `TITLES` + `FEED_TITLES`), `:304-305`, `:332` (`FEED_BOXED`,
  `feed.like: []` — решение 43 (б)), `:477`, `:493-495` (названия и модуль «Лента»), `:510` (`["push"] * 13`),
  `:518-533` (у `feed.like` в ячейках `telegram`, `max` нет `input`; план не называет), `:552, 556` (14 флажков, цикл
  без `FEED_LIKE`), `test_notify_prefs.py:208-214`, `:239-241`, `:499-501` (строки, названия, модуль, `matrix` с
  `FEED_BOXED` и `FEED_LIKE: []`), `test_kb_boundaries.py:278` (17 видов или `without_feed()`); п. 40–42 — поиск:
  `test_search_providers_2.py:306, 309`, `:328-329` (`+ "feed"`), `test_kb_boundaries.py:482-483` (`+ ["feed"]`, `+
  ["Лента"]`); п. 43 — `test_notify_pages.py:219` (колокольчик открывается на `/me/` — решение 43 (г); два `ws-connect`
  на `/` проверяет T-7104; план этого теста не называет); п. 44–45 (приёмка) — `tests/e2e/test_e04_my_settings.py:36-56,
  277, 279, 283, 352, 585` (`FEED_KINDS_E2E` в `ROWS`, модуль «Лента»), `tests/e2e/test_e12_criteria.py:57-71, 925, 937,
  940-941, 946-947` (`EXPECTED_CATALOG` — восемь видов ленты, у `feed.like` внешний текст пустой). Условно — проверить
  после реализации, заранее не правятся (если упадут — не ослаблять: остановка, решение Opus, правка по тому же правилу;
  У1 и У2 почти наверняка падают — разметка по решению 43 (в)): У1 `test_notify_admin.py:368-377`, У2
  `tests/e2e/test_e08_admin.py:376-386`, У3 `test_notify_catalog_2.py:332`, `test_notify_prefs.py:499-501`, У4
  `test_capacity.py:73`, У5 `test_search_pages.py`, У6 `test_calendar.py`, `test_org_pages.py`, `test_sd_queues.py`,
  `tests/e2e/test_d09_settings.py`, `tests/e2e/test_o11_calendar.py`, У7 `test_kb_comments.py:308-317`, У8
  `test_notify_boundaries.py`, `test_kb_boundaries.py`, `test_sd_boundaries.py` (сканы импорта), У9 `test_stack.py`,
  `test_date_field.py`, У10 `test_shell.py`, У11 `tests/e2e/test_cross_cutting.py:63-65`,
  `tests/e2e/test_e04_my_settings.py:587`, У12 `tests/e2e/test_k10_search.py`, `tests/e2e/test_l12_search.py`, У13
  `tests/e2e/test_e12_criteria.py`, `tests/e2e/test_e11_failures.py`, `tests/e2e/helpers_notify.py`, У14
  `tests/e2e/test_s01_first_admin.py`, `tests/e2e/test_s03_activation.py`, `tests/e2e/test_o04_find_colleague.py:274`,
  У15 `tests/e2e/test_e09_security.py:451`, `tests/e2e/test_e10_page.py`, У16 `test_lists_seed.py:173-176`, У17
  `test_notify_prefs.py:521, 525`, У18 `test_lists_stand.py`, `test_kb_deploy.py:519`, `e2e_reset_stand`, У19
  `test_notify_ws.py`, У20 `test_extensions.py:75, 98-103`, У21 `test_audit.py`; из плана — `test_kb_access.py:868-870,
  896-897, 910, 928`, `test_lists_seed.py:144`. Не правятся (`impact.md`: «не падают, проверено чтением»):
  `test_sd_boundaries.py:589` (строка плана неверна: тест идёт под `no_extensions`), `test_kb_boundaries.py:325`,
  `:383-393`, `test_kb_comments.py:250`, `test_sd_list_2.py:547`, `test_sd_boundaries.py:122-124`,
  `test_notify_deploy.py:359-375`, `test_notify_boundaries.py:128`, `test_core_uploads.py:436-448`; `CONTRACT.md` и
  `CONTRACT-002…006`, `tools/` — не правятся (уточнения — в `CONTRACT-007.md`) — backend/tests/, backend/tests/e2e/;
  отчёт docs/reviews/TASKS-007.md, раздел «Правки прежних тестов» — (план: «Прежние тесты, которые придётся поправить»,
  «Изменения кода прежних срезов»)
- [ ] T-7159 [opus] подготовка стенда к прогонам среза (решения 37, 38; после T-7138, до T-7160): с разрешения владельца —
  копия данных стенда (`crm-work/slice005/stage4/t5301/backup-stand.sh`, в `crm-work/stand-backup`) до первого сброса;
  проверка, что службы `clamav` (сигнатуры загружены) и `fakebots` здоровы, Mailpit отвечает, worker-ы RQ живы (после
  сна ноутбука — перезапуск); новых зависимостей и переменных нет, образ стенда пересобирается только с кодом среза
  (T-7260) — отчёт docs/reviews/TASKS-007.md, раздел «Стенд» — (план: «Проход в браузере», «Запуск»)
- [ ] T-7160 [opus] красный прогон: весь серверный набор и приёмка среза 007 на стенде (после T-7100…T-7154, T-7138 и
  T-7159; прогоны — через `systemd-run --user`, приёмка — на пустом стенде, сброс перед кругом): новые тесты падают по
  ожидаемой причине (нет кода среза); тесты срезов 001–006 зелёные, кроме тестов перечня T-7138: они уже исправлены под
  срез 007 и падают по той же причине, что и новые (отдельной строкой); отдельной строкой — тесты перечня T-7138,
  которые зеленеют только с T-7201, T-7202, T-7206, T-7213a, T-7224, T-7228, T-7230, T-7232 и T-7233 (решение 31);
  отдельной строкой — тесты «Проверить после реализации» плана и «Условно» анализа влияния — зелёные; приёмка прежних
  срезов — Chromium и Яндекс Браузер (`-k`); сводка «тест → причина» и эталон для регрессии — отчёт
  docs/reviews/TASKS-007.md, раздел «Красный прогон» — (FR-601…642, NFR-601…614; инвариант «тест-на-требование»)

## Этап 3 — реализация

Порядок — партиями по механизмам плана и зависимостям (решение 32): 1) ядро `0010` и модели `feed`; 2) изменения ядра и
прежних модулей; 3) видимость, аудитория, вывод текста; 4) лента, главная, непрочитанное; 5) публикация; 6) важное и
событие; 7) комментарии, «Нравится», правка и удаление; 8) живые обновления; 9) уведомления и напоминания; 10) файлы и
эскизы; 11) поиск; 12) ночное задание и настройка срока; 13) журнал, стенд, развёртывание, нагрузка; затем зелёный
прогон. После каждой партии — весь серверный набор (`systemd-run --user`); регрессия срезов 001–006 — остановка и решение
Opus. У задачи названы файлы тестов Этапа 2, которые она делает зелёными (часть файла — «службы» или «страницы»: файл
целиком зеленеет с последней названной задачей). Код — только SQL с параметрами; тексты отказов, адреса, зацепки `data-*`
— дословно из `CONTRACT-007.md` (решение 35). Общие файлы кода — по одному автору за раз (решение 29), поэтому `[P]`
только у задач без общих файлов с соседями.

**Партия 1 — ядро `0010` и модели `feed`**

- [ ] T-7200 [sonnet] назначение файла ядра и модели `feed` (план: «Модель данных» → «Ядро и прежние модули» —
  `core.StoredFile.Purpose`, «Приложение `feed`»; «Изменения кода прежних срезов» — строка `core/models/files.py`;
  решение 30): сначала ядро — `Purpose.FEED = "feed"` «вложение ленты» в конце вариантов и миграция
  `core/migrations/0010_storedfile_feed_purpose.py` (`AlterField` вариантов, как `0009`); затем все модели таблицы плана
  с ограничениями и индексами (`Post` — проверки «`important` ⇔ `important_until`», «`event` ⇔ поля события и `event_end
  > event_start`», индексы по времени, частичные по виду, по `important_until`, по `remind_at`, GIN по `search`;
  `Recipient` — `unit_id` числом без внешнего ключа, проверка «ровно одно из `unit_id`, `user`» и соответствие `kind`,
  частичные уникальности (`post`, `unit_id`) и (`post`, `user`, `via`), три частичных индекса; `FeedComment` —
  OneToOne на `core.Comment` с `primary_key=True` и `related_name="+"`; `PostLike`, `CommentLike`, `ReadMark`,
  `EventAnswer` с уникальностями; `Shown` с суррогатным ключом, `UniqueConstraint("user", "post")` и индексом по
  `post` (обычный `db_index` внешнего ключа, решение 60; зеленеет
  `test_feed_deploy.py::test_shown_post_has_index_so_commit_fk_check_skips_full_scan`); `FeedFile` с PROTECT на `StoredFile` и проверкой «`comment` ⇒ `post`»; `FeedSettings` с проверкой 1…10) и
  миграция `feed/migrations/0001_initial.py` (зависит от `core 0010`; имена индексов не длиннее 30 знаков). Первым делом
  обе миграции применяются на PostgreSQL 17 тестового контейнера; если ограничение не создаётся — остановиться, ход
  решает Opus (решение 28). Тесты: `test_feed_core_changes.py` (назначение `feed`), прежний `test_core_uploads.py`
  (прежние значения назначений) — backend/apps/core/models/files.py, backend/apps/core/migrations/0010_*,
  backend/apps/feed/models.py, backend/apps/feed/migrations/0001_initial.py — (FR-607, FR-611, FR-613, FR-616, FR-624,
  FR-626, FR-633, FR-638)
- [ ] T-7201 [sonnet] данные установки и тексты (план: «Права среза», «Права и данные установки», «Тексты отказов»):
  `feed/migrations/0002_initial_data.py` (зависит от `core 0002_initial_data` и `feed 0001`) — функция `seed(apps,
  schema_editor, *, stand=False)`: права `feed.post_all` «Писать всем» и `feed.moderate` «Модерировать ленту»
  (`get_or_create`); при `created` или `stand=True` — «Писать всем» всем ролям `Role.objects.all()`, «Модерировать
  ленту» — «Администратору портала» по названию (нет роли — пропуск); строка `FeedSettings(retention_years=3)`, если её
  нет; `feed/services/feed_settings.py` — `get()` создаёт строку при отсутствии; `feed/texts.py` — все тексты отказов
  FR-642, два текста для запросов в обход интерфейса и текст предела непривязанных загрузок одним словарём, дословно по
  `CONTRACT-007.md`. Тесты: `test_feed_seed.py`; прежние `test_permissions.py`, `test_sd_access.py`,
  `test_lists_seed.py`, `test_org_permissions.py` (перечень прав, в виде после T-7138); сверка словаря текстов с
  контрактом (решение 19) — backend/apps/feed/migrations/0002_initial_data.py,
  backend/apps/feed/services/feed_settings.py, backend/apps/feed/texts.py — (FR-638, FR-640, FR-642)

**Партия 2 — изменения ядра и прежних модулей** (каждая задача — с тестом прежнего поведения; решение 30)

- [ ] T-7202 [sonnet] ядро: точка и поля вида уведомления (план: «Точки расширения ядра и шина событий», «Модель данных»
  → `core.extensions`, «Контракты» → «Записи точек ядра»; «Изменения кода прежних срезов» — строка
  `core/extensions.py`): `"home_body"` в конце `POINTS` (восемнадцать точек); поля `NotificationKind.channels:
  tuple[str, ...] | None = None` и `coalesce_text: Callable[[int, str, datetime], str] | None = None` в конце записи
  (полей пятнадцать); запись `menu_items` допускает ключ `live_badge`. Порядок прежних семнадцати точек и тринадцати
  полей не меняется. Тесты: `test_feed_core_changes.py` (точка), `test_feed_core_changes_3.py` (поля вида), часть
  `test_feed_boundaries.py` (восемнадцать точек); прежние `test_extensions.py`, `test_sd_boundaries.py`,
  `test_kb_boundaries.py`, `test_lists_boundaries.py`, `test_lists_reminders_2.py` (в виде после T-7138) —
  backend/apps/core/extensions.py — (FR-629, FR-631, FR-641)
- [ ] T-7203 [P] [sonnet] ядро: главная, меню, узел живого числа (план: «Главная, меню и число у „Ленты“»; «Изменения
  кода прежних срезов» — строки `core/views/pages.py`, `templates/home.html`, `templates/_home_notices.html`,
  `core/context.py`, `core/services/permissions.py`, `templates/base.html`): `pages.collect_notices(user)` (выделена из
  `home`, тот же цикл по `home_notices`); `pages.home` отдаёт ответ первой функции точки `home_body`, точка пуста —
  прежний `home.html`; общий фрагмент `templates/_home_notices.html` с прежней разметкой `data-home-notices` /
  `data-notice` / `data-year`, `home.html` его включает; `context.shell` не добавляет «Главную», если среди пунктов
  `menu_for` есть пункт с `url="/"`, и ставит его первым; `menu_for` передаёт ключ `live_badge`, если он объявлен;
  `base.html` — у пункта с `live_badge` узел `#menu-badge-<имя>` всегда (`d-none` при 0, «99+» при числе больше 99,
  `data-count`, `data-menu-live-badge`, без `data-menu-badge`); у прочих пунктов разметка числа прежняя, `htmx-config`
  не меняется. Тесты: `test_feed_core_changes.py` (главная без точки, «Главная» без модуля, узел числа); прежние
  `test_calendar.py`, `test_org_pages.py`, `test_sd_queues.py`, `test_notify_boundaries.py`, `test_sd_list_2.py`,
  `test_sd_boundaries.py`; тесты меню из перечня T-7138 (`test_org_permissions.py`, `test_lists_access.py`,
  `test_sd_boundaries.py`) зеленеют с T-7213a и T-7230; сразу после партии 2 Opus с разрешения владельца, после копии
  стенда и обновления стенда кодом партий 1–2 (решение 38) прогоняет в Chromium приёмку прежних срезов
  `test_o11_calendar.py`, `test_d09_settings.py`, `test_cross_cutting.py` (решение 30; повтор — в T-7260) —
  backend/apps/core/views/pages.py, backend/apps/core/context.py, backend/apps/core/services/permissions.py,
  backend/templates/home.html, backend/templates/_home_notices.html, backend/templates/base.html — (FR-601, FR-626,
  FR-641)
- [ ] T-7204 [P] [sonnet] ядро: правка комментария и шаблоны ПДн (план: «Модель данных» → `core.services.comments`,
  `core.services.pdn_patterns`; «Изменения кода прежних срезов» — строки `core/services/comments.py`,
  `core/services/pdn_patterns.py`, `knowledge/services/pdn.py`): `comments.update(comment, text) -> Comment` с проверками
  `add` (пробелы по краям, 1–4000 знаков, `CommentError`); новый `core/services/pdn_patterns.py` — `EMAIL`, `PHONE`
  перенесены без изменения выражений; `knowledge/services/pdn.py` импортирует их из ядра. Поля `core.Comment` не
  меняются, в модуле комментариев нет слов `knowledge`/`article`. Тесты: `test_feed_core_changes.py` (`comments.update`,
  равенство находок на наборе строк); прежние `test_kb_comments.py`, `test_kb_boundaries.py`, `test_kb_pdn.py`,
  `test_kb_pdn_2.py` — backend/apps/core/services/comments.py, backend/apps/core/services/pdn_patterns.py,
  backend/apps/knowledge/services/pdn.py — (FR-612, FR-622, FR-624)
- [ ] T-7205 [P] [sonnet] ядро: общая проверка сессии соединений и колокольчик (план: «Живые обновления» → «Проверка
  сессии», «Исправление дефекта среза 004», «Главная, меню» → «Живое число на любой странице»; «Изменения кода прежних
  срезов» — строки `core/ws.py`, `notify/consumers.py`): новый `core/ws.py` — примесь `SessionGuardMixin` (`ws_state`
  при подключении, не «ok» — принять и закрыть 4401; цикл: сон `self.check_interval()`, хук `on_check()`, `ws_state`,
  не «ok» — 4401; ошибка в цикле — закрыть 1013); `NotifyConsumer` на примеси (`check_interval()` возвращает модульное
  `apps.notify.consumers.CHECK_INTERVAL`, `on_check` — отметка присутствия), обработчик `notify_html` отправляет готовый
  фрагмент как есть. Тесты: `test_feed_core_changes_2.py` (примесь, 1013 у колокольчика, `notify_html`); прежний
  `test_notify_ws.py` целиком (подмена `CHECK_INTERVAL` действует) — backend/apps/core/ws.py,
  backend/apps/notify/consumers.py — (FR-626, FR-627)
- [ ] T-7206 [P] [sonnet] слой `publish` и маршруты соединений (план: «Запуск» → «Слой каналов», «Живые обновления» →
  «Маршруты»; «Изменения кода прежних срезов» — строки `config/settings.py` (слой), `config/asgi.py`,
  `notify/services/live.py`): `CHANNEL_LAYERS["publish"]` — тот же адрес и префикс `crm-asgi`, `socket_timeout` 2,
  `socket_connect_timeout` 2, `max_connections` 300, слой `default` прежний; `config/asgi.py` —
  `websocket_urlpatterns = list(notify_routing.websocket_urlpatterns)` и при `apps.is_installed("apps.feed")` маршруты
  `feed.routing` (пока пустые), в маршрутизатор — эта переменная; `notify.services.live.push` шлёт через
  `get_channel_layer("publish")`, ошибки — предупреждением в журнал, как прежде. Тесты: `test_feed_core_changes_2.py`
  (слой `publish`, `asgi` с модулем и без); прежние `test_notify_deploy.py`, `test_notify_ws.py` (в виде после T-7138) —
  backend/config/settings.py, backend/config/asgi.py, backend/apps/notify/services/live.py — (FR-627, FR-641, NFR-614)
- [ ] T-7207 [P] [sonnet] `notify`: допустимые каналы вида и склейка с обновлением текста (план: «Уведомления» →
  «Допустимые каналы вида», «Склейка с обновлением текста»; «Изменения кода прежних срезов» — строки
  `notify/services/dispatch.py`, `notify/services/prefs.py`, `notify/views/me.py`, `notify/views/admin.py`,
  `notify/services/settings.py`): фильтр `kind.channels` в шести местах плана (`prefs._listed`, `prefs.effective`,
  сохранение «Моих уведомлений», `views/me._table_context`, `views/admin._rows` и разбор POST,
  `services/settings._normalized_defaults`; разметка ячейки вне перечня — решение 43); `dispatch.create` при склейке и
  заданном `kind.coalesce_text` обновляет `text` непрочитанного под прежним замком ключа склейки, без него — прежний
  пропуск. Тесты: `test_feed_core_changes_3.py` (каналы, `coalesce_text`); прежние `test_notify_coalesce.py`,
  `test_notify_admin.py` (в виде после T-7138; каталожные `test_notify_prefs.py`, `test_notify_catalog.py`,
  `test_notify_catalog_2.py` зеленеют с видами ленты — T-7224) — backend/apps/notify/services/dispatch.py, prefs.py,
  settings.py, backend/apps/notify/views/me.py, admin.py — (FR-629, FR-631)
- [ ] T-7208 [P] [sonnet] `org`: состав поддерева и цепочки многих (план: «Где живёт код» → `org/services/structure.py`;
  «Изменения кода прежних срезов» — строка `org/services/structure.py`): `subtree_member_ids(unit_ids) -> frozenset[int]`
  (сотрудники узлов и вложенных по основной работе и совместительству, без уволенных, одним запросом по
  `unit__path__startswith`) и `unit_chains(user_ids) -> dict[int, frozenset[int]]` (цепочки двумя запросами, то же, что
  `unit_chain_ids`, пачкой); таблиц нет, прежние функции не меняются. Тесты: `test_feed_core_changes.py` (сверка с
  `descendants` + `direct_members` и с `unit_chain_ids`); прежние `test_org_*.py` —
  backend/apps/org/services/structure.py — (FR-605, FR-615, FR-617, FR-626, FR-628)

**Партия 3 — видимость, аудитория, вывод текста**

- [ ] T-7209 [sonnet] видимость и права действий (план: «Видимость и аудитория записи»): `services/visibility.py` —
  `viewer(user)` (один раз на запрос, `user._feed_viewer` только у объекта запроса; `chain` — `org.services.structure.
  unit_chain_ids` под `apps.is_installed("apps.org")`, иначе пусто; `moderator`, `post_all` — правами ядра),
  `visible_posts(user)` (литерал плана: автор, `to_all`, `EXISTS` по `feed_recipient` с цепочкой массивом-параметром или
  `user_id`), `get_post(user, id)` (нет или не видна — `Http404`, ответ один), `can_see(user_id, post_id)`,
  `audience(post)` множествами (`to_all` — все действующие; узлы — `subtree_member_ids` под `is_installed`; люди —
  строки `Recipient.user`; автор; фильтр состояния одним запросом), `can_edit`, `can_delete`, `can_comment` и прочие
  права действий по плану (править — только автор; удалить — автор или модератор, если видит; комментировать,
  отмечать, отвечать — каждый, кто видит). Единственное место решений о видимости. Тесты: `test_feed_visibility.py`
  (службы: таблица «запись × сотрудник», аудитория, права действий), часть `test_feed_boundaries.py` (импорты `org` под
  `is_installed`) — backend/apps/feed/services/visibility.py — (FR-605, FR-606, FR-607, FR-620, FR-621, FR-622, FR-628)
- [ ] T-7210 [P] [sonnet] вывод текста и разбор упоминаний (план: «Текст и упоминания» → «Хранение», «Вывод», «Отрывок»,
  «Упоминания при сохранении»; «Безопасный вывод»): `services/text.py` — `render_plain(text, people, link_staff) ->
  SafeString` (единственное место `mark_safe` для текста ленты: удаление управляющих и bidi, регулярное выражение плана,
  экранирование всего вне совпадений, ссылки только `http`/`https` с хостом и `mailto:`, не длиннее 2048, хвостовая
  пунктуация и «)» вне ссылки, `target="_blank" rel="noopener noreferrer"`, маркер — ссылка на карточку сотрудника или
  `<span data-mention>` без права, неизвестный номер — текстом, абзацы и переводы строк), `snippet(text, limit)`
  (маркер → «@ФИО», без разметки, обрезка по слову с «…»); `services/mentions.py` — `extract(text)` (номера маркеров,
  предел 20 разных, повтор не расходует, недействующий и несуществующий — не адресат). Тесты: `test_feed_text.py`
  (службы, 17 злых входов), `test_feed_mentions.py` (разбор маркеров и предел) — backend/apps/feed/services/text.py,
  backend/apps/feed/services/mentions.py — (FR-609, FR-611, FR-642, NFR-605)

**Партия 4 — лента, главная, непрочитанное**

- [ ] T-7211 [sonnet] выборка страницы ленты (план: «Лента, курсор, блок важных, фильтры», «Запись в ленте и карточка» →
  «Строка адресатов»): `services/page.py` — разбор фильтра по белому списку (`f`, `author`, `from`, `to`, `before`,
  `opened`; неверное отбрасывается без ошибки), курсор `(published_at, id)` от времени открытия без OFFSET, ветки
  фильтров по индексам плана, блок важных (только при `f` = `all`/`important` без `author`, `from`, `to`; конец срока
  важного — сравнение с текущим временем параметром `%s`, решение 59; исключение номеров блока на первой странице и
  условие блока в SQL у «Ещё записи» и вставки по плашке), сборка карточек без N+1 (номера массивом, `LATERAL` для
  отметок и трёх последних комментариев, число запросов постоянно); `services/recipients.py` — `line(post, …)` («Всем»,
  названия узлов через `org.unit_refs`, «Подразделение удалено», ФИО без повторов, «уволен», первые пять и «и ещё N»).
  Тесты: `test_feed_page.py`, `test_feed_page_2.py` (службы), `test_feed_visibility_3.py` (строка адресатов) —
  backend/apps/feed/services/page.py, backend/apps/feed/services/recipients.py — (FR-602, FR-603, FR-607, FR-614,
  FR-635, NFR-601, NFR-608)
- [ ] T-7212 [sonnet] непрочитанное (план: «Непрочитанное»; первым шагом — форма литерала числа по итогу T-7003,
  решение 28): `services/unread.py` — `show(user, ids)` (одним `INSERT … ON CONFLICT DO NOTHING`, своя запись не
  пишется), `count(user)` (литерал плана с `LIMIT 100`, за 30 дней — граница параметром `%s` от `timezone.now()`,
  решение 59; без своих), `counts(user_ids)` (одним запросом множествами по `org.unit_chains`, потолок 100; без модуля
  `org` — без узлов). Тесты: `test_feed_unread.py` (службы: показ, число, «99+», новичок, сверка `counts` с `count` по
  100 сотрудникам) — backend/apps/feed/services/unread.py — (FR-626, NFR-601)
- [ ] T-7213a [sonnet] главная, «Ещё записи», меню (план: «Главная, меню и число у „Ленты“», «Запись в ленте и
  карточка», «Контракты» → `/`, `/feed/more/`; «Безопасный вывод, язык, узкий экран»; деление — решение 45):
  `views/home.py` — `body(request)` (`@login_required`; блок напоминаний через `_home_notices.html` и
  `pages.collect_notices`, форма-место, фильтры GET, пустая плашка, блок важных, 20 записей, узел `#feed-live` с
  `ws-connect` из разобранного фильтра и `data-opened`; показы до рендера оболочки) и `more` (показы и узел числа
  `hx-swap-oob` только при `HX-Request`); шаблоны `body.html`, `_post.html` и пустые части (`_post_head.html`,
  `_post_body.html`, `_post_to.html`, `_important.html`, `_event.html`, `_likes.html`, `_comments.html`,
  `_comment.html`, `_files.html`, `_form.html`, `_new_banner.html`, `_lists.html`), `_badge.html` (решение 33); ФИО
  ссылкой — только читателю с `staff.view` или `accounts.manage`; постоянные `id` частей записи и `data-post-id`; иконка
  `templates/icons/feed.html`; `feed.css` (лента, 360 px, `overflow-wrap: anywhere`, эскизы `max-width: 100%`) и
  подключение `feed.css`/`feed.js` в шаблонах (решение 34); `extensions.register_all()` — пункт `menu_items` «Лента»
  (`url="/"`, `order=0`, `visible` — каждому, `badge` — `unread.count`, `live_badge="feed"`) и `home_body`;
  `FeedConfig.ready()` зовёт `register_all()`; адреса в `urls.py`. Тесты: `test_feed_home.py`, `test_feed_page.py` и
  `test_feed_page_2.py` (страницы), `test_feed_visibility_2.py` (лента, «Ещё», фильтры), `test_feed_unread.py` (показы
  страницей и «Ещё»), `test_feed_text.py` (страница); тесты меню и главной из перечня T-7138 —
  backend/apps/feed/views/home.py, backend/apps/feed/extensions.py, apps.py, urls.py, backend/templates/feed/,
  backend/templates/icons/feed.html, backend/static/feed/feed.css — (FR-601, FR-602, FR-603, FR-606, FR-626, FR-635,
  FR-641, NFR-605, NFR-606, NFR-611)
- [ ] T-7213b [sonnet] карточка записи и полный список адресатов (план: «Запись в ленте и карточка», «Контракты» →
  `/feed/<id>/`, `/feed/<id>/to/`; деление — решение 45): `views/posts.py` — карточка `/feed/<id>/` (все
  комментарии-место, показ, публикация `object.viewed` с `object_ref="feed.post:<id>"`, узел соединения `?post=<id>`) и
  `/feed/<id>/to/`; `card.html`; адреса в `urls.py`. Тесты: `test_feed_visibility.py` (карточка),
  `test_feed_visibility_3.py` (`/to/`), `test_feed_visibility_2.py` (карточка), `test_feed_posts_2.py` (карточка),
  `test_feed_unread.py` (показ карточкой) — backend/apps/feed/views/posts.py, backend/apps/feed/urls.py,
  backend/templates/feed/ — (FR-604, FR-606, FR-626, NFR-605)

**Партия 5 — публикация**

- [ ] T-7214 [sonnet] служба публикации (план: «Публикация: форма, „Кому“, подсказки» → «„Кому“», «Публикация»; «Текст
  и упоминания»; «Предупреждение о ПДн»; «Поиск» → «Векторы»): первым шагом `services/search.py` — `vectors` (литералы
  плана для записи и комментария, маркеры в вектор не идут; единственное место расчёта вектора, его зовут T-7218,
  T-7220, T-7221); `recipients.parse(viewer, values)` («Всем» без права — «Писать всем вам не разрешено»; узел — по
  `org.unit_refs`; человек — действующий; пусто — «Выберите, кому адресована запись»; больше 50 — «Не больше 50
  адресатов»; упомянутые вне предела); `posts.publish` вида «Сообщение» в одной транзакции (запись, адресаты `to`,
  строки `mention` по маркерам, вектор; NUL удаляется разбором формы; пусто — «Напишите текст», больше 10 000 —
  «Предел: 10000 знаков» по контракту); `pdn.find_plain(*texts)` (`EMAIL`, `PHONE` ядра, без повторов, до 20). Тесты:
  `test_feed_posts.py` (службы), `test_feed_pdn.py` (находки), `test_feed_mentions.py` (упомянутый — адресат при
  публикации), `test_feed_search.py` (векторы при публикации) — backend/apps/feed/services/search.py, recipients.py,
  posts.py, pdn.py — (FR-608, FR-609, FR-610, FR-611, FR-612, FR-637, FR-640, FR-642, NFR-608)
- [ ] T-7215 [sonnet] форма публикации и подсказки (план: «Публикация» → «Форма», «Подсказка»; «Текст и упоминания» →
  «Упоминание в форме»; «Предупреждение о ПДн»; «Контракты» → `/feed/posts/`, `/feed/pick/`): `_form.html` (переключатель
  вида, поля всех видов в разметке, лишние скрываются классом через `Alpine.data`, «Всем» по умолчанию у права и нет
  пункта без права, таблетки «Кому» с крестиком); `views/posts.py` — `POST /feed/posts/` (ответ HTMX — очищенная форма и
  своя запись наверху; обычный POST — переход на `/`; отказ — 200 с формой, причиной у поля и введённым); шаг
  предупреждения о ПДн («Исправить», «Опубликовать всё равно» с `pdn_confirmed=1`); `views/pickers.py` — `/feed/pick/`
  (`scope=to|mention|author`, от двух знаков, до 20 строк, по части ФИО без учёта «ё», узлы через `org.structure.
  all_units()`, без должности и контактов); `feed.js` — таблетки «Кому», подсказка «@», соответствие «вхождение → номер»,
  таблетка «<ФИО> — упомянут», замена вхождений маркерами перед отправкой, счёт знаков. Тесты: `test_feed_posts.py`
  (страницы), `test_feed_posts_2.py` (подсказка), `test_feed_pdn.py` (форма), `test_feed_mentions.py` (подсказка «@»,
  маркеры без скрипта) — backend/apps/feed/views/posts.py, views/pickers.py, backend/apps/feed/urls.py,
  backend/templates/feed/, backend/static/feed/feed.js — (FR-608, FR-610, FR-611, FR-612, FR-635, FR-642, NFR-605,
  NFR-606)

**Партия 6 — важное и событие**

- [ ] T-7216 [sonnet] важное (план: «Важное», «Модель данных» → «Срок важного»): `services/important.py` — `until(term,
  date, today)` («День», «Неделя», «Месяц», «До даты»; полночь Europe/Moscow; «Дата уже прошла», «Срок — не позже чем
  через год»), `stats(post)` («N из M» по `audience` без автора); публикация вида «Важное» в `posts.publish`;
  `views/important.py` — `POST /feed/<id>/read/` (адресату, не автору, до конца срока — время параметром, решение 59;
  `ReadMark` `get_or_create` (повтор — без ошибки, уникальность строки, решение 6); иначе 403 с причиной; ответ — запись без кнопки) и `GET
  /feed/<id>/reads/` (автору и модератору, если видит; иначе 403); `_important.html` («Важное, важно до <дата>», «было
  важным», «Прочитали N» или «N из M»); `feed.js` — вставка карточки после «Прочитано» в ленту по времени публикации.
  Тесты: `test_feed_important.py`, `test_feed_page_2.py` (блок важных и «Прочитано») —
  backend/apps/feed/services/important.py, services/posts.py, views/important.py, backend/apps/feed/urls.py,
  backend/templates/feed/, backend/static/feed/feed.js — (FR-605, FR-613, FR-614, FR-615, FR-642, NFR-611)
- [ ] T-7217 [sonnet] событие (план: «Событие и напоминания» → «Поля», «Ответы», «`remind_at` при публикации»):
  `services/events.py` — `validate` (название и место обязательны, до 200; начало и конец по Москве; конец позже начала;
  начало не в прошлом — тексты контракта), `remind_at` (начало − 1 ч, если до начала не меньше часа, иначе пусто),
  ответы (`EventAnswer` `update_or_create`; после начала — «Ответы закрыты: событие началось»; автору — 403), числа и
  списки по `audience` без автора, «Не ответили»; публикация вида «Событие» в `posts.publish` (текст необязателен);
  `views/events.py` — `POST /feed/<id>/answer/` и `GET /feed/<id>/answers/` (только автору, модератору — 403);
  `_event.html`. Тесты: `test_feed_events.py` (поля, ответы), `test_feed_reminders.py` (`remind_at` при публикации) —
  backend/apps/feed/services/events.py, services/posts.py, views/events.py, backend/apps/feed/urls.py,
  backend/templates/feed/ — (FR-605, FR-616, FR-617, FR-618, FR-642)

**Партия 7 — комментарии, «Нравится», правка и удаление**

- [ ] T-7218 [sonnet] комментарии (план: «Комментарии», «Текст и упоминания» → «Упоминание в комментарии»):
  `services/comments.py` — добавить (`core.services.comments.add(user, "feed.post:<id>", text)`, коды ядра `empty` и
  `too_long` — тексты контракта; `FeedComment` с вектором; упоминания — строки `Recipient(via="mention")` записи; всё в
  одной транзакции; ПДн — как у записи), список плоский по `created_at, id`, последние три и «Показать все N»;
  `views/comments.py` — `GET/POST /feed/<id>/comments/` (адреса ищут только комментарии с `object_ref` `feed.post:`);
  `_comments.html`, `_comment.html` (якорь `#c<id>`, `data-comment-id`, зацепка «Ответить» с номером и ФИО автора —
  решение 13); `feed.js` — «Ответить» вставляет `@ФИО` с соответствием «вхождение → номер». Комментарии статей базы знаний
  не меняются. Тесты: `test_feed_comments.py` (без файлов), `test_feed_mentions.py` (упоминание в комментарии),
  `test_feed_visibility.py` (упомянутый в комментарии видит карточку), `test_feed_visibility_3.py` (упоминание в
  комментарии в строке адресатов), `test_feed_pdn.py` (комментарий) — backend/apps/feed/services/comments.py,
  views/comments.py, backend/apps/feed/urls.py, backend/templates/feed/, backend/static/feed/feed.js — (FR-611, FR-612,
  FR-623, FR-624, FR-642)
- [ ] T-7219 [sonnet] «Нравится» (план: «„Нравится“»): `services/likes.py` — переключатель записи и комментария
  (нарушение уникальности перехватывается как «уже есть», удаление отсутствующей строки — не ошибка; своё отметить
  можно); `views/likes.py` — `POST /feed/<id>/like/`, `POST /feed/comments/<cid>/like/`, `GET …/likes/` фрагментом;
  `_likes.html` («Нравится: <ФИО>, <ФИО> и ещё N», последние первыми). Тесты: `test_feed_likes.py` (без уведомлений) —
  backend/apps/feed/services/likes.py, views/likes.py, backend/apps/feed/urls.py, backend/templates/feed/ — (FR-625)
- [ ] T-7220 [sonnet] правка записи (план: «Правка и удаление» → «Правка записи»; «Важное» → «Срок»; «Событие и
  напоминания» → «Правка события»; «Текст и упоминания» → «Упоминание в форме»): `GET/POST /feed/<id>/edit/` — только
  автор (модератору и чужому — 403); «Кому» только расширяется («Адресатов можно только добавить»), проверки узла и
  человека — только у добавленных, всего не больше 50, «Всем» без права — отказ, сохранённое «Всем» остаётся; вид не
  меняется; `edited_at`, вектор, ПДн («Сохранить всё равно»); срок важного — только если изменены поля срока (от даты
  правки, прочтения сохраняются; «было важным» — сравнение `important_until` с текущим временем параметром, решение 59);
  событие — у начавшегося время и место не меняются, новое начало не в прошлом, пересчёт `remind_at` с
  `reminded_for_start`; форма отдаёт текст с маркерами и соответствие «номер → ФИО» в атрибуте `data-`, `feed.js`
  показывает `@ФИО` и ставит маркеры перед отправкой. Тесты: `test_feed_edit.py`, `test_feed_events.py` (правка
  события), `test_feed_important.py` (срок при правке), `test_feed_mentions.py` (правка не снимает адресата),
  `test_feed_reminders.py` (пересчёт `remind_at`) — backend/apps/feed/services/posts.py, recipients.py, events.py,
  important.py, views/posts.py, backend/apps/feed/urls.py, backend/templates/feed/, backend/static/feed/feed.js —
  (FR-610, FR-611, FR-612, FR-613, FR-619, FR-620, FR-640, FR-642)
- [ ] T-7221 [sonnet] удаление записи, правка и удаление комментария (план: «Правка и удаление» → «Удаление записи»,
  «Комментарий»; «Журнал»): `posts.delete` в одной транзакции (пути файлов и эскизов записи и комментариев, множество
  `audience` до удаления для рассылки T-7222b, `comments.delete_for`, `post.delete()`, строки `StoredFile`; модератор
  чужой — `audit.record("feed.post_deleted", …)` без текста; стирание диска после фиксации, отсутствующий файл — не
  ошибка; комментарий во время удаления откатывается без сирот — решение 15); подтверждение «Удалить запись вместе с
  комментариями?»; `POST /feed/<id>/delete/` (автор или модератор, если видит; невидимая — 404, видимая без права — 403;
  запрос HTMX и обычный — по «Контрактам» плана); `GET/POST /feed/comments/<cid>/edit/` (автор; `comments.update` ядра,
  `edited_at`, вектор, новые упоминания) и `POST /feed/comments/<cid>/delete/` (автор или модератор, если видит; автор
  записи чужие не удаляет; пути файлов до `comments.delete`; модератор чужой — `feed.comment_deleted`). Тесты:
  `test_feed_edit_2.py`, `test_feed_audit.py` (записи журнала удаления), `test_feed_mentions.py` (удаление комментария
  не снимает адресата), `test_feed_pdn.py` (правка записи, события и комментария), `test_feed_page_2.py` (меню правки и
  удаления, последние комментарии) — backend/apps/feed/services/posts.py, services/comments.py, views/posts.py,
  views/comments.py, backend/apps/feed/urls.py, backend/templates/feed/ — (FR-621, FR-622, FR-632, FR-639)

**Партия 8 — живые обновления**

- [ ] T-7222a [sonnet] служба рассылки фрагментов и числа (план: «Живые обновления» → «Рассылка», «Формат кадров», «Без
  WebSocket»; «Непрочитанное» → «Обновление числа»; «Контракты» → «Сообщения слоя каналов»; первым шагом — способ
  `permissions_of` по итогу T-7004, решение 28; деление — решение 45): `services/live.py` — получатели —
  `visibility.audience(post)` при каждой рассылке; фрагмент рендерится один раз на класс (`reader`, `author`,
  `moderator` × «открываются карточки», не больше шести); `moderators` и `staff_viewers` — правами ядра на момент
  рассылки; сообщение `feed.event` с ключами контракта в группы `feed.u.{id}`; `asyncio.gather` через
  `get_channel_layer("publish")`, все исключения — предупреждением в журнал, действие не страдает; число «Ленты»
  затронутым — `unread.counts` и сообщение `notify.html` с фрагментом `_badge.html` в группы
  `notify.services.live.group(id)` под `apps.is_installed("apps.notify")`; во фрагментах нет форм и
  `csrfmiddlewaretoken`, кнопки — `hx-post`, значения экранированы. Тесты: `test_feed_live.py` и `test_feed_live_2.py`
  (службы рассылки и кадры), `test_feed_unread.py` (обновление числа кадром) — backend/apps/feed/services/live.py,
  backend/templates/feed/ — (FR-606, FR-626, FR-627, FR-628, NFR-602, NFR-605, NFR-614)
- [ ] T-7222b [sonnet] вызовы рассылки из служб (план: «Живые обновления» → «Рассылка»; деление — решение 45): вызовы
  `live` через `transaction.on_commit` из публикации, правки, удаления (множество получателей снято до удаления —
  T-7221), комментария, правки и удаления комментария, отметок, «Прочитано», ответа. Тесты: `test_feed_live.py` и
  `test_feed_live_2.py` (целиком), `test_feed_visibility_2.py` (рассылка) — backend/apps/feed/services/posts.py,
  services/comments.py, services/likes.py, services/important.py, services/events.py — (FR-606, FR-627, FR-628, NFR-614)
- [ ] T-7223 [sonnet] соединение ленты и плашка (план: «Живые обновления» → «Маршруты», «`FeedConsumer`», «Плашка»;
  «Контракты» → `/ws/feed/`, `/feed/new/`; первым шагом — отправка `sync`/`add` по итогу T-7005 и обработка закрытия по
  итогу T-7006, решение 28): `consumers.py` — `FeedConsumer` на `core.ws.SessionGuardMixin` (`check_interval()` —
  `apps.feed.consumers.CHECK_INTERVAL` 25 с), разбор адреса по белому списку, `group_add("feed.u.{id}")`, состояние
  `ids`, `pending`, фильтр; `feed.event`: `new` — по `meta` без запросов к базе, своя запись и карточка плашки не
  получают; кадры только о записях из `ids`, вариант своего класса; удаление из `pending`; сообщения клиента `sync`
  (замена `ids`, набор `pending` одним запросом, плашка, служебный кадр `#feed-synced`) и `add`; до 300 номеров,
  сообщение больше 16 КБ — 1009, прочие игнорируются; ошибка слоя — 1011; `routing.py` — `ws/feed/`; `GET /feed/new/`
  (до 50, важные непрочитанные — в блок, если он показан; показы и число — только при `HX-Request`; пустая плашка с новым
  `since`); `_new_banner.html` «Новых записей: N»; `feed.js` — `sync` на каждое `htmx:wsOpen` методом `send` обёртки
  сокета, `add` по `htmx:afterSwap`, `data-ws="open"` по `#feed-synced`, `"closed"` по `htmx:wsClose`, отмена повторной
  вставки на `htmx:oobBeforeSwap` (`detail.shouldSwap = false`, только если элемент с тем же `id`, что у вставляемого, есть на странице и не равен `detail.target`; решение 62), `htmx:wsClose` только ставит `data-ws="closed"`, запасного хода для 1000/1001 нет (решение 63). Тесты: `test_feed_consumers.py`, `test_feed_consumers_2.py`,
  `test_feed_live_2.py` (кадр через соединение), `test_feed_unread.py` (показы плашкой) —
  backend/apps/feed/consumers.py, routing.py, views/home.py, backend/apps/feed/urls.py, backend/templates/feed/,
  backend/static/feed/feed.js — (FR-602, FR-626, FR-627, FR-628, FR-635, NFR-608)

**Партия 9 — уведомления и напоминания**

- [ ] T-7224 [sonnet] уведомления (план: «Уведомления»; решение 43 — `order` и внешний текст «Нравится»):
  `notify_kinds.py` — восемь видов `feed.*` (`module="Лента"`, `events=()`, `order` 70…77, каналы по умолчанию,
  `channels=("portal",)` у `feed.like`, `coalesce` и `coalesce_text` у `feed.comment` и `feed.like`, постоянный
  `external_text`, `still_relevant` — разбор `feed.post:<id>` и `feed.post:<id>:c<cid>`, запись и комментарий живы,
  `visibility.can_see`); `notify_rules.decide(event)` — кто что получает из `audience` в момент события, без
  действующего и уволенных, одно уведомление по приоритету плана; вызовы `dispatch.create` внутри транзакций публикации,
  правки (ставшим видеть и новым упомянутым; смена начала, конца, места — участникам), комментария, отметок — под
  `apps.is_installed("apps.notify")`; тексты плана через `text.snippet` (100 и 60 знаков, не длиннее 300, время по
  Москве); карточка публикует `object.viewed` и для «Нравится» своих комментариев; регистрация в `notification_kinds`.
  Тесты: `test_feed_notify.py`, `test_feed_notify_2.py`, `test_feed_visibility_2.py` (`still_relevant`),
  `test_feed_likes.py` (себе уведомления нет), `test_feed_posts.py` (откат вместе с `dispatch.create`),
  `test_feed_edit_2.py` (уведомления о записи остаются); прежние `test_notify_prefs.py`, `test_notify_catalog.py`,
  `test_notify_catalog_2.py`, `test_kb_boundaries.py` (строки видов ленты, в виде после T-7138) —
  backend/apps/feed/notify_kinds.py, services/notify_rules.py, services/posts.py, services/comments.py,
  services/likes.py, views/posts.py, backend/apps/feed/extensions.py — (FR-611, FR-619, FR-629, FR-630, FR-631, FR-632,
  NFR-605, NFR-609, NFR-611)
- [ ] T-7225 [sonnet] задание напоминаний (план: «Событие и напоминания» → «Задание напоминаний», «Правило простоя»):
  `services/reminders.py` и `tasks.remind_events(now=None)` (текущее время берётся из `timezone.now()` один раз и
  передаётся в выборку параметром `%s` вместо `now()` базы: так `Clock` и `run_reminders(now)` сдвигают время; то же для
  `retention_night` и сроков важного в SQL) — цикл по одной записи `… WHERE remind_at <= %s AND event_start > %s AND
  reminded_for_start IS DISTINCT FROM event_start ORDER BY remind_at LIMIT 1 FOR UPDATE SKIP LOCKED`; в той же
  транзакции получатели (`audience` минус «Не смогу», плюс автор), `dispatch.create("feed.event_reminder", …)` под
  `is_installed("apps.notify")`, `reminded_for_start = event_start`, `remind_at = NULL`; не больше 200 событий; сбойное
  событие — в лог приложения (номер, без текста) и исключение из выборки (`id <> ALL(%s)`), остальные идут, задание в
  конце ошибкой не завершается (решение 12); точка подмены выборки — по контракту. Тесты: `test_feed_reminders.py` —
  backend/apps/feed/services/reminders.py, backend/apps/feed/tasks.py — (FR-606, FR-618, FR-619, NFR-610)

**Партия 10 — файлы и эскизы**

- [ ] T-7226 [sonnet] загрузка и привязка файлов (план: «Файлы и эскизы» → «Загрузка по одному файлу», «Привязка»):
  `services/files.py` — загрузка (`core.services.uploads.reject_reason(…, max_file=20 МБ)`,
  `core.services.uploads.store(data, name, "feed")`, `ImageTooLarge` — отказ типа, строка `FeedFile` без записи; ранний
  отказ по `have` — «У записи уже 10 файлов», «У комментария уже 3 файла»; не больше 30 непривязанных — текст контракта;
  убрать свой непривязанный); привязка условным `UPDATE … WHERE post IS NULL AND comment IS NULL AND uploaded_by = %s` с
  проверкой числа строк под `select_for_update` записи — в публикации, комментарии и правке; «убрать» при правке —
  только файлы этой записи или комментария, удаление строки, `StoredFile`, диска после фиксации; `views/files.py` —
  `POST /feed/files/`, `POST /feed/files/<id>/delete/`; таблетка файла со скрытым `files=<id>`; `feed.js` — загрузка по
  одному с `scope` и `have`. Тесты: `test_feed_files.py`, `test_feed_comments.py` (три файла), `test_feed_posts.py`
  (привязка файлов при публикации и откат) — backend/apps/feed/services/files.py, services/posts.py,
  services/comments.py, views/files.py, backend/apps/feed/urls.py, backend/templates/feed/, backend/static/feed/feed.js
  — (FR-633, FR-642, NFR-604)
- [ ] T-7227 [sonnet] назначение `feed`, эскизы, выдача и показ (план: «Файлы и эскизы» → «Назначение `feed`», «Эскиз»,
  «Выдача», «Показ», «Резервная копия»): запись `FilePurpose("feed", …)` («ожидание», «чистый» — перенос в
  `attachments/` и эскиз, «карантин»; сбой ClamAV — повтор прежнего задания ядра); `services/thumbs.py` (JPEG, PNG,
  GIF, WebP → не больше 1280 px, JPEG или WebP у PNG с прозрачностью, `exif_transpose`, первый кадр GIF, `Image.draft`,
  путь `PROTECTED_ROOT/attachments/thumbs/<id>.jpg|webp`; сбой ловится отдельно от переноса, пишется без имени файла,
  частичный эскиз стирается, `thumb` пуст); `views/files.py` — `GET /feed/files/<id>/` (видимость записи первой, затем
  состояние; `inline_image` или `download`) и `GET /feed/files/<id>/thumb/` (свой ответ с `X-Accel-Redirect:
  /protected/attachments/thumbs/<имя>`, `nosniff`, `no-store`); «проверяется» и «карантин» — 404 с текстами контракта;
  `_files.html` с `data-file-state`; регистрация в `file_purposes`. Тесты: `test_feed_files_2.py`,
  `test_feed_visibility_2.py` (файл, эскиз), `test_feed_text.py` (имя файла и поля события на странице) —
  backend/apps/feed/services/thumbs.py, services/files.py, views/files.py, backend/apps/feed/extensions.py,
  backend/apps/feed/urls.py, backend/templates/feed/ — (FR-606, FR-634, FR-642, NFR-613, NFR-614)

**Партия 11 — поиск**

- [ ] T-7228 [sonnet] поставщик «Лента» (план: «Поиск» → «Поставщик»; `vectors` уже написан в T-7214):
  `services/search.py` — `SearchProvider(key="feed", title="Лента", order=60)`, `слово:*` по словам `ParsedQuery` с
  отсевом стоп-слов (`numnode`), видимость в том же SQL (запись — `visible_posts`, комментарий — видимость его записи),
  `UNION ALL` двух веток по `LIMIT limit + offset + 1`, снаружи от новых к старым, `count` — две ветки по `LIMIT 301` с
  потолком 300, `SearchRow` (заголовок «<ФИО>, <дата> — <начало текста>», у события — название; `subtitle` «Запись» или
  «Комментарий»; `url` карточки, у комментария — якорь `#c<id>`); регистрация в `search_providers`. Тесты:
  `test_feed_search.py`, `test_feed_visibility_2.py` (поиск); тесты поставщиков из перечня T-7138 —
  backend/apps/feed/services/search.py, backend/apps/feed/extensions.py — (FR-606, FR-636, FR-637, FR-641, NFR-603,
  NFR-608)

**Партия 12 — ночное задание и настройка срока**

- [ ] T-7229 [sonnet] ночное задание (план: «Срок хранения и ночное задание» → «Граница срока», «Задание»;
  «Непрочитанное» → «Чистка показов»; первым шагом — короткая повторная проверка ORM-каскада пачки на настоящих моделях (с индексом `Shown(post_id)` по решению 60: проверка при фиксации идёт без просмотра таблицы показов — по плану запроса или времени пачки на 1 000 записей, существенно ниже 1,68 с замера без индекса)
  и способ пачки по её итогу и итогу T-7007, решения 27, 28): `services/retention.py` и
  `tasks.retention_night(now=None)` (время — один раз из `timezone.now()`, во все шаги параметром `%s`, решение 59) —
  шаг 1: строки `Shown` записей старше 31 дня (по `published_at`); шаг 2: записи старше срока (календарно, 29 февраля →
  28) пачками по 1 000 с фиксацией каждой: пути файлов и эскизов,
  `Comment.objects.filter(object_ref__in=refs).delete()`, удаление записей, строки `StoredFile`, стирание диска после
  фиксации; шаг 3: непривязанные `FeedFile` старше 24 часов; журнал одной записью `feed.retention_purged` только при N >
  0; повтор ничего не находит; запись, удалённая между выбором и удалением, пропускается; `VACUUM` не зовётся; точка
  подмены выборки пачки — по контракту. Тесты: `test_feed_retention.py`, `test_feed_important.py` (после заданий
  напоминаний и ночного), `test_feed_notify_2.py` (уведомления остаются после удаления по сроку) —
  backend/apps/feed/services/retention.py, backend/apps/feed/tasks.py — (FR-621, FR-632, FR-638, FR-639, NFR-610)
- [ ] T-7230 [sonnet] настройка срока хранения (план: «Срок хранения и ночное задание» → «Настройка»; «Точки
  расширения» → пункт «Настройки ленты»): `views/settings.py` — `GET/POST /settings/feed/` под правом ядра
  `settings.portal` (без права — 403 на GET и POST без обращения к службе, решение 11); заголовок «Настройки портала →
  Лента»; поле 1–10 («Срок хранения — от 1 до 10 лет»); уменьшение — второй шаг «Ближайшее ночное задание удалит
  записей: N» и «Подтвердить», увеличение — сразу (решение 16); `audit.record("feed.retention_changed", …)` «было /
  стало»; `settings.html`; пункт `menu_items` «Настройки ленты» (`order=63`, `icon="icons/gear.html"`, `permissions=
  ("settings.portal",)`). Тесты: `test_feed_settings.py`; тесты меню из перечня T-7138 (четырнадцать пунктов) —
  backend/apps/feed/views/settings.py, backend/apps/feed/extensions.py, backend/apps/feed/urls.py,
  backend/templates/feed/ — (FR-638, FR-639, FR-642, NFR-606)

**Партия 13 — журнал, стенд, развёртывание, нагрузка**

- [ ] T-7231 [sonnet] журнал (план: «Журнал»): `audit_labels.py` — подписи четырёх действий, типов объектов
  `feed.post`, `feed.comment`, `feed.settings` и каждого ключа `before`/`after` (в том числе `posts` — «Удалено по сроку,
  записей»); регистрация в `audit_labels`; сверка, что каждое действие таблицы пишет `audit.record` без текста записи и
  комментария, а публикация, правка и удаление автором своего, комментарии, отметки, прочтения, ответы — не пишут.
  Тесты: `test_feed_audit.py` — backend/apps/feed/audit_labels.py, backend/apps/feed/extensions.py — (FR-639, NFR-607)
- [ ] T-7232 [sonnet] стенд (план: «Стенд и приёмка», «Права и данные установки»): `stand.py` — `stand_reset` под
  алиасом `migrate` (таблицы ленты и строки `core.Comment` с `object_ref` `feed.post:…` — решение 53; пути файлов и
  эскизов из строк `FeedFile`/`StoredFile`, если они есть, стирание после фиксации; каталог `attachments/thumbs/`
  целиком; `seed(stand=True)` с отключением обработчика `m2m_changed` ядра и возвратом в `finally`; `FeedSettings(3)`),
  своя `require_stand()` по образцу `lists`; команды `e2e_feed_shift --minutes N` (1…10 080; `require_stand()` первой
  строкой; сдвиг `update(F() − delta)` без `save()`; сдвигает и `important_until` важных записей; задание напоминаний в
  процессе команды; строка `feed_shift: shifted=<N> reminded=<M> important=<K>`; решение 54) и `e2e_feed_retention
  --age-days N [--posts <номера через запятую>]` (1…4 000; сдвиг `published_at` и копии в `Recipient` у всех записей
  стенда или только у названных ключом `--posts`, решение 54; ночное задание в процессе команды; строка `feed_retention:
  aged=<N> deleted=<M>`); вне границ — отказ без изменений (решение 10); регистрация в `stand_reset`. Тесты:
  `test_feed_stand.py`; тесты порядка сброса из перечня T-7138 — backend/apps/feed/stand.py,
  backend/apps/feed/management/commands/e2e_feed_shift.py, e2e_feed_retention.py, backend/apps/feed/extensions.py —
  (FR-618, FR-638, FR-640)
- [ ] T-7233 [sonnet] развёртывание (план: «Запуск»; «Изменения кода прежних срезов» — строки `config/cron.py`,
  `deploy/nginx.conf`, `deploy/nginx.prod.conf`): `config/cron.py` — `feed_reminders` (`* * * * *`, очередь `notify`,
  `job_timeout=120`, `apps.feed.tasks.remind_events`) и `feed_retention` (`35 23 * * *`, `maintenance`, `job_timeout=600`,
  `apps.feed.tasks.retention_night`) под `apps.is_installed("apps.feed")`, прежние записи и минуты не меняются;
  `location ~ ^/feed/files/$` с `client_max_body_size 25m` и повтором директив `proxy_*` в обоих конфигах (место — не
  между блоками, которые прежние тесты держат рядом), `/ws/` не меняется, адреса ленты в `web-heavy` не идут (решение
  39); `backup.sh` и `RESTORE.md` не правятся; перезапуск `scheduler` и `nginx` при обновлении — в отчёте «Стенд».
  Тесты: `test_feed_deploy.py` (cron, nginx, CSP, шаблоны, тексты), `test_feed_boundaries.py` (cron под
  `is_installed`); прежние `test_deploy_files.py`, `test_kb_deploy.py`, `test_notify_deploy.py`, `test_sd_deploy.py`,
  `test_lists_deploy.py` (в виде после T-7138) — backend/config/cron.py, deploy/nginx.conf, deploy/nginx.prod.conf —
  (FR-618, FR-633, FR-638, FR-641, NFR-604, NFR-613)
- [ ] T-7234 [opus] данные и модель нагрузки (план: «Нагрузка»; решение 39): `backend/tests/load/fill_feed.py` (только
  при `E2E_STAND=1`; `LOAD_POSTS=50000`, `LOAD_COMMENTS=200000`; адресаты, виды и отметки — по распределению F1; добор
  до цели; строка `fill_feed: posts=… comments=… likes=…`; запуск через `standtools … shell`); класс `FeedUser` в
  `backend/tests/load/locustfile.py` (два соединения на вкладку — `/ws/notify/` и `/ws/feed/` через `websocket-client`;
  лента, «Ещё записи», карточка, фильтры, сквозной поиск, подсказки «Кому» и «@», «Нравится», «Прочитано», «Пойду»,
  комментарий; один поток-публикатор: запись раз в 30 с по очереди «Всем», подразделению и людям, комментарий раз в 10
  с, с `{номер записи: monotonic}` (решение 39); событие `WS feed frame` с точной задержкой по `data-post-id` из кадра);
  прочие классы не меняются. Тесты: `test_feed_deploy.py` (наличие `fill_feed.py` и `FeedUser`) — backend/tests/load/ —
  (NFR-601, NFR-602, NFR-603, NFR-612)
- [ ] T-7260 [sonnet] зелёный прогон по областям (сначала Opus с разрешения владельца и после копии стенда обновляет
  стенд с кодом среза — решение 38): довести до зелёного T-7102…T-7154 и весь набор срезов 001–006 (после T-7138);
  приёмку прежних срезов `test_o11_calendar.py`, `test_d09_settings.py`, `test_cross_cutting.py` — повторно (решение
  30); приёмка среза 007 — четыре браузера, прежних срезов — Chromium и Яндекс Браузер (`-k`), сброс перед кругом,
  прогоны через `systemd-run --user`, Playwright из `CRM/.venv`; каждое падение — причина в отчёте; тесты не ослабляются
  — docs/reviews/TASKS-007.md, раздел «Зелёный прогон» — (FR-601…642, NFR-601…614)

## Этап 4 — финальная проверка

Опыт среза 006 (docs/reviews/TASKS-006.md, разделы «Нагрузка», «Опыт о ёмкости», «Копия», «Инварианты»): замер скорости
идёт только на остывшей машине с закрытыми программами владельца, без агентов и `docker run` во время замера, со своей
копией стенда до сброса; невыполненный замер — не повод ослаблять порог: разбор, решение владельца, новые задачи
(T-7311…, как решения 63–65 среза 006) и повтор; сверка инвариантов идёт по диффу после всех правок нагрузки.

- [ ] T-7300 [opus] прогон всех тестов сервера на PostgreSQL в контейнере (вместе со срезами 001–006; через
  `systemd-run --user`): сверить красный прогон T-7160 с зелёным; ни одного пропущенного и ослабленного теста; сводка по
  FR и NFR — docs/reviews/TASKS-007.md, раздел «Прогон тестов» — (FR-601…642, NFR-601…614)
- [ ] T-7301 [sonnet] проход в браузере (настоящий Chrome и Firefox; сначала Opus с разрешения владельца обновляет стенд,
  если код после T-7260 менялся — решение 38): сценарии 1–15 руками по спеке; живые обновления в двух окнах разных
  сотрудников (плашка, число у «Ленты», комментарий, отметка, правка, удаление — без перезагрузки; работа без
  WebSocket — обычными запросами); ширина 360 px всех страниц перечня плана (лента, карточка, форма с адресатами и
  подсказками, блоки важного и события, списки отметивших, прочитавших, ответивших, фильтры, выдача поиска, настройка
  срока); в консоли нет ошибок CSP и `htmx:oobErrorNoTarget`; картинки с телефона (поворот по EXIF), PNG с прозрачностью,
  анимированный GIF — эскизы; пункты, которые приёмка не проходит (решение 41), — здесь, в том числе ClamAV недоступен
  (остановку службы `clamav` стенда делает Opus с разрешения владельца после копии: запись цела, файл «проверяется»,
  после запуска — «чистый»); кадры с данными — вне git — docs/reviews/TASKS-007.md, раздел «Проход в браузере» —
  (FR-601…642, NFR-604, NFR-605, NFR-606, NFR-614)
- [ ] T-7302 [opus] после T-7301: прогон приёмки Playwright из `CRM/.venv` со сбросом стенда перед каждым кругом
  (пустой стенд; после сна ноутбука — перезапуск worker-ов RQ; прогоны через `systemd-run --user`; решение 37) — срез
  007 (`test_f01…f15`) кругами по Chromium, Firefox, Edge и Яндекс Браузеру (в том числе замеры `f08` ≤ 2 с в каждом
  браузере — план: «Риски», htmx-ext-ws вне Chromium); срезы 001–006 — кругами по Chromium и Яндекс Браузеру (`-k`,
  правило владельца 2026-10-21) — backend/tests/e2e/*; docs/reviews/TASKS-007.md, раздел «Приёмка» — (NFR-602,
  NFR-604, NFR-606)
- [ ] T-7303 [P] [opus] `python3 tools/sdd.py проверить` и `python3 -m unittest discover -s tools -p "test_*.py"` без
  ошибок; `tools/test_constitution.py` по `backend/` и `deploy/`; `tools/check_secrets.py` по дереву;
  `tools/verify_vendor.py` (новой сторонней статики нет, `htmx-ext-ws` 2.0.4 прежний) — вывод команд в
  docs/reviews/TASKS-007.md — (конституция: «стек-бэкенд», «стек-интерфейс», «бд», «бесплатные-компоненты»,
  «секреты-вне-кода», «секреты-в-url», «sql-только-параметры»; NFR-608)
- [ ] T-7304 [opus] скорость NFR-612 (после T-7302 и T-7303; только по согласию владельца, на остывшей машине: перед
  стартом `/proc/loadavg` за 1 и 5 минут ниже 1,5, программы владельца закрыты, во время прогона — никаких агентов,
  `docker run` и сборок; запуск через `systemd-run --user`; правила `crm-work/slice006/stage4/t6304/run4.sh`: копия
  стенда `backup-stand.sh` и сброс, запись `vmstat`/`mpstat`/`pidstat`, коды ответов журнала `nginx`, стенд на потоках
  0–2, locust на потоке 3; решение 39): `fill_feed.py` (50 000 записей, 200 000 комментариев) через `standtools … shell`;
  locust по модели нагрузки владельца (100 вошедших, вход 1/с, пауза 5–15 с, замер после входа всех) — прогон L1 с классом
  `FeedUser` (два соединения на вкладку, публикатор; публикации, в том числе «Всем») и прогон L2 со всеми классами
  срезов 001–007; пороги: страницы и фрагменты ленты p95 ≤ 500 мс, поиск (группа «Лента») ≤ 1 с, кадр до последнего
  получателя (`WS feed frame`) p95 ≤ 2 с, ошибок нет (5xx по журналу `nginx` нет); заодно — p95 ответа публикации
  (больше 500 мс — запасной ход плана: уведомления и рассылка заданием очереди `notify`, решение Opus с владельцем), CPU
  и память процессов `web`, длина очередей каналов Valkey, число непрочитанных и блок важных в варианте B, ветка
  комментариев в поиске, `unread.counts` и `permissions_of` на рассылке, время пачки ночного задания с ORM-каскадом на
  наполнении `fill_feed`, показы — в состоянии после ночной чистки (решение 61; запасной ход плана включается только при p95 публикации выше 500 мс) (план: «Риски»); страницы прежних срезов в смеси L2 — к сведению владельца (смешанная модель —
  не критерий прежних срезов, решение владельца по T-5304); по итогам — решение Opus с владельцем о запасных ходах
  «Рисков» (подписка на группы, кэш числа, `work_mem` поиска, сырой SQL пачки; если нужны — отдельными задачами T-7311…)
  — docs/reviews/TASKS-007.md, раздел «Нагрузка» — (NFR-601, NFR-602, NFR-603, NFR-612)
- [ ] T-7305 [opus] (после T-7304) наблюдения на стенде (по разрешению владельца, после копии стенда; решение 40): (1)
  прогон NFR-614 — адрес слоя `publish` подменён закрытым портом при рабочих кэше и очередях (временный модуль настроек
  вне репозитория во временном контейнере `web` того же образа в сети стенда, решение 40): публикация, комментарий и
  отметка отвечают быстрее 3 с, запись цела, предупреждение в журнале, вкладки работают обычными запросами; (2) пауза
  всего Valkey (`docker pause` службы `valkey` на 60 с) — без порога: время ответа публикации и страниц, поведение
  очередей RQ и кэша, возврат вкладок после снятия паузы (до 64 с) — в отчёт; (3) код закрытия соединений при обновлении
  службы `web` (`up -d --no-deps web`; план: «Риски») — сверка с T-7006, вкладки ленты и колокольчик возвращаются сами;
  ожидание возврата вкладок — с запасом на окно пересоздания `web` и на молчащее соединение, принятое умирающим процессом (до ≈ 50 с, затем 1006; решение 63); запасного хода `feed.js` для 1000/1001 нет, при коде закрытия, отличном от 1012/1006, — остановиться и спросить Opus. После наблюдений — стенд в прежнем виде, проверка здоровья служб —
  docs/reviews/TASKS-007.md, раздел «Наблюдения на стенде» — (FR-627, NFR-614)
- [ ] T-7306 [opus] (после T-7304) резервная копия и восстановление на стенде (с разрешения владельца, после своей копии
  стенда): запись с картинкой (эскиз построен) и комментарий с файлом; копия штатным `backup.sh` службы `backup`;
  запись удаляется (файлы и эскиз стёрты, карточка — 404); восстановление по `deploy/RESTORE.md` (шаги 1–5, остановка и
  запуск служб, в том числе `web-heavy`); после восстановления карточка открывается, оригинал (`/feed/files/<id>/`) и
  эскиз (`/feed/files/<id>/thumb/`) отдаются, файл комментария скачивается — docs/reviews/TASKS-007.md, раздел «Копия» —
  (NFR-613)
- [ ] T-7307 [opus] (после T-7304, T-7305 и всех правок по их итогам) смысловая проверка инвариантов по диффу среза:
  «модуль-приложение» (границы импорта, восемнадцать точек, `is_installed` у `org`, `notify`, маршрутов, cron),
  «настройка-без-кода» (срок, права, каналы — данные), «интеграции-через-адаптеры» (ClamAV через ядро и очередь, слой
  `publish` с тайм-аутом), «аудит-изменений» (без текста записей и комментариев), «пдн-152фз» (невидимое = несуществующее,
  внешние каналы — постоянный текст, срок хранения), «секреты-в-url» (адрес `/ws/feed/` — только фильтр),
  «sql-только-параметры» (видимость, курсор, счётчик, поиск, векторы — литералы с параметрами),
  «двухфакторная-авторизация» (соединение ленты); сверка: каждый изменённый файл прежних срезов есть в таблице плана
  «Изменения кода прежних срезов» и в решении 30, у каждого — тест прежнего поведения; лишних правок нет —
  docs/reviews/TASKS-007.md, раздел «Инварианты» — (конституция; FR-606, FR-631, FR-638, FR-639, FR-641, NFR-605,
  NFR-607, NFR-608, NFR-609)
- [ ] T-7308 [opus] прохождение требований спеки: таблица FR-601…642 и NFR-601…614 → тест → результат → ссылка на
  реализацию; NFR-601 считается выполненным только после T-7304 (замер с согласия владельца); отметки `[x]` в этом
  файле, отчёт docs/reviews/TASKS-007.md и перевод в «на-проверке» (`sdd.py на-проверку`); подпись ставит человек —
  docs/reviews/TASKS-007.md — (FR-601…642, NFR-601…614)
- [ ] T-7309 [человек] ручной проход: критерий успеха спеки «запись подразделению и человеку за 1 минуту» с замером
  (план: «Критерии успеха спеки»); отметка в отчёте — docs/reviews/TASKS-007.md, раздел «Ручной проход» — (FR-608,
  FR-610)
- [ ] T-7310 [человек] принять срез по отчёту docs/reviews/TASKS-007.md (T-7308) и проходам T-7301, T-7309. Отметки
  выполнения на отпечаток не влияют. Если по итогам среза менялся текст задач, подписать их заново —
  docs/reviews/TASKS-007.md — (инвариант «спека-прежде-кода»)

## Решения Opus по задачам

План этих деталей не задал. Ниже — решения, принятые при сборке задач; владелец принимает их подписью под задачами
(T-7008). Решения плана и решения владельца здесь не повторяются, а только называются со ссылкой. Ответы на вопросы
скелета Этапа 2 (`crm-work/slice007/tasks/opus-notes.md`, 2026-10-30) вошли как решения 7–17 с пометкой «ответ N к
скелету»; общие решения скелета (`stage2-skeleton.md`, «Общие решения») — как решения 1–6 и 18–26; ответы на вопросы
черновиков Этапа 2 и разделов задач (тот же файл, 2026-10-30) — как решения 46–58 и уточнения в решениях 1, 2, 8, 10,
27–33, 39, 40, 42, 43, 45; итоги проверки задач (партии R1–R8, 2026-10-30) — как решение 59 и уточнения в решениях 1, 2,
5, 6, 8, 26, 29, 31, 43, 45, 46, 54, 55, 58. Отступлений от поведения, заданного PLAN-007, нет; дополнения стенда и
тексты — в абзаце «Показать владельцу при подписи».

1. **Номера и имена файлов.** Номера задач четырёхзначные (T-7001…). Серверные тесты — `test_feed_<тема>.py`: 27 тем
   раздела плана «Серверные тесты», заранее поделены девять (`visibility`, `page`, `posts`, `edit`, `live`, `consumers`,
   `notify`, `files`, `core_changes` — вторые файлы `_2`), итого 36 файлов на T-7102…T-7137 и третий файл
   `test_feed_core_changes_3.py` — 37 файлов на 37 строк (при проверке задач добавлен `test_feed_visibility_3.py` у
   T-7102b — 38 файлов, решение 45); изменения кода прежних срезов — `test_feed_core_changes.py` (ядро, `org`,
   `knowledge`; T-7137), `test_feed_core_changes_2.py` (`core/ws.py`, `NotifyConsumer`, `notify_html`, `live.push`,
   `CHANNEL_LAYERS`, `config/asgi.py`; T-7126a) и `test_feed_core_changes_3.py` (поля `NotificationKind`, фильтр
   `channels`, `coalesce_text`; T-7126b): у T-7126 вышло 28 тестов, и она поделена (решение 45). Приёмка —
   `test_f01_publish.py`, `test_f02_important.py`, `test_f03_event.py`, `test_f04_comments.py`, `test_f05_likes.py`,
   `test_f06_mentions.py`, `test_f07_edit_delete.py`, `test_f08_live.py`, `test_f09_notify.py`, `test_f10_files.py`,
   `test_f11_search.py`, `test_f12_retention.py`, `test_f13_rights.py`, `test_f14_home.py`, `test_f15_pdn.py`. Имена
   тестов — английские `snake_case`; файл тестов — у одной задачи; файл больше ~25 тестов делится строками
   `T-NNNNa`/`T-NNNNb` с файлом `_3` и вопросом в черновике. Причина: план («Проверка», «Проход в браузере») называет
   темы и буквы `f`, а окончания имён не смешиваются со срезами 001–006 (`test_sNN`, `test_oNN`, `test_dNN`, `test_eNN`,
   `test_kNN`, `test_lNN`). Источник — скелет, «Общие решения».
2. **Контракт имён и общие помощники.** `backend/tests/CONTRACT-007.md` пишет только T-7100, `tests/support_feed.py` —
   только T-7101, `tests/e2e/helpers_feed.py` — только T-7140a. Opus проверяет контракт до запуска T-7101; писатели
   T-7102… стартуют после T-7101, T-7140b, T-7141… — после T-7140a. Тесты проверяют только то, что есть в PLAN-007 и
   SPEC-007, и решения этого раздела (они уточняют способ). Причина: все тесты среза опираются на одни имена; так было в
   срезах 005–006 (решение 2 TASKS-006). Источник — скелет; ответы 2026-10-30, «Общее для черновиков».
3. **Место приложения и каркас.** Место задаёт план: `apps.feed` последним, после `apps.search` («Где живёт код»). Каркас
   T-7001 добавляет эту строку и пустое подключение `include("apps.feed.urls")` под `apps.is_installed("apps.feed")` —
   единственное исключение из правила «код прежних срезов правит только задача Этапа 3» (решение 30): поведение портала
   от пустого приложения не меняется, а регистрация нужна каркасу и красному прогону. Следствие: тесты хвоста
   `INSTALLED_APPS` (`test_kb_deploy.py`, `test_notify_deploy.py`, `test_lists_deploy.py`) падают с T-7001, тесты порядка
   сброса стенда (`test_lists_stand.py`, `test_kb_deploy.py`) — с T-7232, когда `feed` зарегистрирует `stand_reset`. Все
   исправляет T-7138 до красного прогона. Причина: так сделан каркас T-6001 (решение 3 TASKS-006); задание на сборку
   задач требует регистрации в `INSTALLED_APPS` и маршрутах под `apps.is_installed` в Этапе 1.
4. **«Было / стало» прежних контрактов** — в разделе «Что меняется в прежних контрактах» `CONTRACT-007.md`, точные
   правки тестов — в `crm-work/slice007/tasks/impact.md`. Сами `CONTRACT.md` и `CONTRACT-002…006` не правятся (план:
   «Контракты»). Причина: одна точка правды для T-7138 и для красного прогона.
5. **Время и задания.** Службы берут время из `timezone.now()` (в SQL — параметром, решение 59); тесты ставят часы
   `Clock` (`tests/factories.py`), проверки «по Москве» — на UTC-полуночи (сценарий 2 п. 9). Задание напоминаний тест
   выполняет синхронно (`run_reminders(now)`), ночное — `run_retention(now)`, задания RQ — `support_notify.run_jobs`;
   приёмка сдвигает время командами `e2e_feed_shift --minutes N` и `e2e_feed_retention --age-days N` через обёртки
   `shift(minutes)` и `age(days)` (план: «Стенд и приёмка»). Причина: тесты не зависят от реального дня и часового пояса
   машины. Источник — скелет.
6. **Гонки — без потоков.** `django_db(transaction=True)` в проекте не работает (`tests/conftest.py`: база мигрирует под
   `crm_owner`, тест идёт под `crm_app`), второй поток не видит данных теста. Приёмы срезов 005–006: (а) по SQL —
   `capture_sql`/`sql_of`: выборка задания напоминаний `… FOR UPDATE SKIP LOCKED`, условный `UPDATE` привязки файлов с
   проверкой числа строк, `select_for_update` записи в правке, удалении, привязке (`assert_for_update`; у «Прочитано»
   замок не проверяется — план его не требует, повтор закрывает уникальность строки прочтения); (б) последовательные
   действия вместо одновременных — два «Нравится — создать» подряд, две привязки одного файла, два запуска задания
   напоминаний; (в) действие между выборкой и замком — подмена по образцу `support_kb.act_between_batch_and_lock`
   (запись удалена после выбора задания напоминаний и пачки ночного задания); (г) «после фиксации» —
   `django_capture_on_commit_callbacks(execute=True)`. Причина: только так тест детерминирован в среде проекта;
   буквальная одновременность держится замками и ограничениями базы. Источник — скелет.
7. **WebSocket в тестах (ответ 1 к скелету).** Помощники среза 004: `asgiref.testing.ApplicationCommunicator` через
   `support_notify.ws_run` / `WsHub` / `WsClient` и настоящий слой `channels_redis` на Valkey (база 15);
   `support_feed.ws_client` строит свой `scope` по образцу `WsHub.connect` (тот кладёт `query_string` пустым) с путём `/ws/feed/?…`; проверка сессии ускоряется подменой
   `apps.feed.consumers.CHECK_INTERVAL`; недоступный слой `publish` — `layer_down()`. Слово плана
   «WebsocketCommunicator» — общее название способа. Причина: образец `test_notify_ws.py` и CONTRACT-004 (раздел о
   соединениях) уже работают в среде проекта; `InMemoryChannelLayer` и подмены `CHANNEL_LAYERS` не нужны.
8. **Две группы приёмки (ответ 2 к скелету).** G8 — T-7140a, T-7140b…T-7147 (`helpers_feed.py`, f01…f08), G9 —
   T-7148…T-7154 (f09…f15); номера прежние, имена помощников в G9 — по описанию T-7140a. Причина: один черновик на 15
   сценариев не укладывается в предел вызовов агента-писателя (так было в решении 31 TASKS-006). Имена помощников
   приёмки — одни, по строке T-7140a (в том числе `open_feed`, `open_card`, `publish`/`try_publish`, ожидание числа
   «Ленты» и плашки, `shift(minutes)`, `age(days, posts=None)`, `block_ws(context)`); контракт T-7100 закрепляет их в
   разделе «Помощники приёмки». Строки задач G9 помощников не называют и с T-7140a не расходятся.
9. **Пачки ночного задания в тестах (ответ 3 к скелету)** — оба признака: шпион на функции пачки (вызвана 3 раза на 2
   500 записей) и три выборки с `LIMIT 1000` в `capture_sql`; способ закрепляет контракт T-7100. Причина: фиксаций в
   тесте нет (решение 6), а «три фиксации» плана видны только так.
10. **Границы команд стенда (ответ 4 к скелету).** `e2e_feed_shift --minutes N` — N от 1 до 10 080 (неделя);
    `e2e_feed_retention --age-days N` — N от 1 до 4 000 (срок хранения до 10 лет); вне границ — отказ без изменений, как
    `e2e_lists_shift`. Тест границ — в T-7134, код — T-7232. Причина: план границ не задаёт, а команда стенда не должна
    принимать бессмысленный сдвиг. Ключ `--posts` и сдвиг `important_until` — решение 54.
11. **`/settings/feed/` без права `settings.portal` (ответ 5 к скелету)** — 403 на GET и POST без обращения к службе,
    как `/settings/notifications/` среза 004. В контракт; код — T-7230. Причина: тот же образец страниц администратора.
12. **Сбой одного события в напоминаниях (ответ 6 к скелету)** — задание в конце ошибкой не завершается: сбойное пишется
    в лог приложения (номер записи, без текста), остальные уходят. Тест — «остальные получили, номер сбойного в логе,
    текста нет»; код — T-7225. Причина: план говорит только «остальные напоминания уходят»; повтор того же сбоя каждую
    минуту засорял бы журнал ошибок заданий.
13. **«Ответить» (ответ 7 к скелету).** У комментария — зацепка с номером и ФИО автора (имена атрибутов — в контракте,
    например `data-reply-id`, `data-reply-name`); серверный тест — зацепка есть и экранирована; вставка `@ФИО` в поле —
    приёмка f04; код — T-7218. Причина: вставку делает `feed.js`, сервер отвечает только за данные для неё.
14. **Сценарий 9 в браузере (ответ 8 к скелету).** Письмо через 15 минут и тихие часы — тем же способом, что приёмка
    среза 004 (`helpers_notify.tick` — команда стенда `e2e_notify_tick` со сдвигом времени уведомлений); тихие часы по
    времени сотрудника, которых приёмка среза 004 в браузере не проверяла, — серверными тестами T-7128. Причина: стенд
    не ждёт 15 минут, а способ сдвига уже есть.
15. **Комментарий во время удаления записи (ответ 9 к скелету)** — приём подмены «запись удалена между проверкой и
    вставкой»: тест — откат, `core.Comment` без `FeedComment` не остаётся; код — T-7221 (одна транзакция комментария).
    Причина: план («Правка и удаление») обещает «сирот нет», а потоков в тестах нет (решение 6).
16. **Увеличение срока хранения (ответ 10 к скелету)** — сохраняется сразу, без подтверждения (подтверждение план даёт
    только при уменьшении, FR-638); тест — да; код — T-7230.
17. **Открытые вопросы плана (ответ 11 к скелету).** План подписан владельцем 2026-10-30; его пункты «для владельца при
    подписи» и «решения плана, которые стоит увидеть» — принятые решения плана (чистка показов старше 31 дня, предел 30
    непривязанных и текст отказа, вид упоминания в поле, ссылка ФИО без права, уведомления после потери видимости и
    прочие); тесты ставят их в «Обязательно».
18. **Ответы** — по «Контрактам» плана: запись не видна, не существует или удалена; комментарий или файл невидимой
    записи; чужой непривязанный файл — 404 «Не найдено» без подробностей (тот же ответ и текст, что у несуществующего);
    запись видна, действие не разрешено — 403; отказ с сообщением — 200 с формой и введённым (запрос HTMX — фрагмент и
    причина у поля); не вошедшему — вход с `next`, без второго фактора — подключение фактора. Источник — скелет.
19. **Тексты отказов в тестах — литералы контракта.** Тесты сравнивают с дословными текстами из `CONTRACT-007.md` (FR-642
    и три текста решений плана: «Писать всем вам не разрешено», «Адресатов можно только добавить», «Слишком много файлов
    без записи: опубликуйте запись или уберите лишние»), а не импортируют `feed/texts.py`; один тест сверяет, что
    словарь `texts.py` содержит каждый текст контракта; `texts.py` пишет T-7201. Причина: тест, читающий текст из
    проверяемого кода, пропустит ошибочный текст (решение 25 TASKS-006).
20. **Замеры времени в серверных тестах — два, оба названы планом:** публикация при недоступном слое `publish` отвечает
    быстрее 3 с (NFR-614) и равное число запросов страницы на 1 и 20 записях (NFR-601, `capture_sql`). Поиск — на
    PostgreSQL тестовой базы (`russian`, GIN по `search`), объёмы малые; остальная скорость — нагрузка T-7304. Причина:
    замер на загруженной машине шумит. Источник — скелет.
21. **ClamAV в серверных тестах** — подмена `apps.integrations.clamav.services.scan` помощниками `support_org.scan_clean`,
    `scan_found`, `scan_unavailable`; `support_feed.attach(...)` берёт её же; настоящий ClamAV (EICAR) — только в
    приёмке. Причина: так в срезах 005–006 (решение 44 TASKS-006).
22. **Права, люди и выключенные модули в тестах.** Роли — `factories.make_role`, `support.role_by_name`; модератор —
    `as_moderator`; без «Писать всем» — `without_post_all(role)` или сотрудник без ролей; состояния — `make_employee(state=…)`;
    подразделения — `make_unit`, `make_member`, `make_unit_role`; без `org` или `notify` —
    `support_lists.without_app(monkeypatch, name)`; без ленты — `without_feed()` (снятие регистраций `apps.feed` из
    реестра точек, без перезагрузки `INSTALLED_APPS`). Причина: пересборка реестра приложений в тесте ломает соседние
    тесты (решение 21 TASKS-006). Источник — скелет.
23. **ПДн и секреты в тестовых данных** — адреса и телефоны собираются из частей (`email_of`, `phone_of`); в именах
    переменных нет `secret`, `token`, `key`, `password`. Причина: иначе их примут за секреты ворота и
    `tools/check_secrets.py` (решение 12 TASKS-006).
24. **Приёмка: браузеры, круги, сброс.** Срез 007 — Chromium, Firefox, Edge, Яндекс Браузер; срезы 001–006 — Chromium и
    Яндекс Браузер ключом `-k` по имени круга (правило владельца 2026-10-21); `tests/e2e/conftest.py` не правится; стенд
    сбрасывается перед кругом (`stand_reset` ленты возвращает права и срок 3); Playwright — из `CRM/.venv`; ширина
    360 px — без горизонтальной прокрутки страницы. Причина: план («Проход в браузере») и правило владельца.
25. **Тест миграции данных** `feed 0002` вызывает её функцию `seed(apps, schema_editor, *, stand=False)` напрямую
    (`run_seed()`: модуль миграции через `importlib`, реестр `django.apps.apps`); та же функция служит сбросу стенда
    (`stand=True`). Причина: миграцию нельзя «откатить и применить» в тестовой базе проекта (решение 20 TASKS-006).
26. **Покрытие** считается по тестам с явным номером требования в строках задач Этапа 2 и по задачам Этапов 1, 3, 4 с
    явными номерами в перечне в конце строки; диапазоны «FR-601…642», «NFR-601…614» не засчитываются (T-7160, T-7260,
    T-7300, T-7308 — без явных номеров; у T-7301 засчитаны только NFR, названные рядом с диапазоном); контракт T-7100
    засчитан только для FR-642; T-7101, T-7138, T-7140a, T-7159 — без своих требований; у тестов команд стенда (T-7134)
    метка FR — вспомогательная (команда служит приёмке этого требования). Причина: так считалось в срезах 005–006
    (решение 23 TASKS-006).
27. **Ранние факты — в Этапе 1, до тестов.** Что план отдал на Этап 1 или оставил непроверенным («Риски»,
    docs/reviews/PLAN-007.md «Что не проверялось»), проверяется до Этапа 2, потому что от итогов зависят тексты тестов и
    способ кода: T-7003 (число непрочитанных и блок важных в варианте B, `unread.counts` на 100) и T-7007 (ORM-каскад
    пачки ночного задания на одноразовом проекте Django с копиями моделей плана) — на временном контейнере
    `postgres:17-alpine`; T-7004 (`permissions_of` на 100) — на стенде через `manage.py shell` службы `web` только
    чтением (`fresh=True` кэш не читает и не пишет; данных не пишет, служб не трогает — разрешения владельца не нужно,
    но не во время приёмки и полного прогона; как T-6003, решение 8 TASKS-006); T-7005 (`socketWrapper.send` расширения
    `ws` в четырёх браузерах) — на временной странице вне репозитория; T-7006 (код закрытия при плавном перезапуске) —
    во временном контейнере образа `crm-portal:local` без сети стенда и портов наружу (ближе к стенду). ORM-каскад на
    одноразовом проекте Django принят; первым шагом T-7229 — короткая повторная проверка на настоящих моделях. T-7004
    идёт по имеющимся учёткам стенда с пересчётом на 100; на 100 учётках замер повторяет нагрузка T-7304. Каждая задача
    пишет в свой подраздел отчёта «Ранние факты: T-700N», подразделы заранее заводит T-7001. Нагрузка T-7304 повторяет
    замеры на `fill_feed` (план: «Нагрузка»). Причина: так было с рисками срезов 005–006 (решения 7, 8, 48 TASKS-006).
28. **Первые шаги рискованных задач.** T-7200 первым делом применяет `core 0010` и `feed 0001` на PostgreSQL 17
    тестового контейнера; T-7212 пишет литерал числа в форме, подтверждённой T-7003; T-7222a считает держателей прав
    способом по итогу T-7004; T-7223 шлёт `sync`/`add` и обрабатывает закрытие по итогам T-7005 и T-7006; T-7229 сначала
    коротко повторяет проверку ORM-каскада на настоящих моделях, затем удаляет пачку способом по итогам T-7007 и этой
    проверки. Если факт не подтвердился, исполнитель останавливается, ход выбирает Opus и вписывает сюда. Причина:
    решение 7 TASKS-006.
29. **Общие файлы кода — один автор за раз.** `config/settings.py` — T-7001 (`INSTALLED_APPS`), затем T-7206 (слой
    `publish`); `config/urls.py` — T-7001; `config/asgi.py` — T-7206; `config/cron.py`, `deploy/nginx.conf`,
    `deploy/nginx.prod.conf` — T-7233; `core/models/files.py` и `core/migrations/0010_*` — T-7200; `core/extensions.py`
    — T-7202; `core/views/pages.py`, `core/context.py`, `core/services/permissions.py`, `templates/home.html`,
    `templates/_home_notices.html`, `templates/base.html` — T-7203; `core/services/comments.py`,
    `core/services/pdn_patterns.py`, `knowledge/services/pdn.py` — T-7204; `core/ws.py`, `notify/consumers.py` — T-7205;
    `notify/services/live.py` — T-7206; `notify/services/dispatch.py`, `prefs.py`, `settings.py`, `notify/views/me.py`,
    `admin.py` — T-7207; `org/services/structure.py` — T-7208; `feed/models.py` и миграции — T-7200, T-7201;
    `feed/texts.py` — T-7201 (дальше — только по решению Opus); `feed/services/search.py` — T-7214, затем T-7228;
    `feed/services/recipients.py` — T-7211, T-7214, T-7220; `feed/services/posts.py` — по очереди T-7214, T-7216,
    T-7217, T-7220, T-7221, T-7222b, T-7224, T-7226; `feed/services/comments.py` — T-7218, T-7221, T-7222b, T-7224,
    T-7226; `feed/services/likes.py` — T-7219, T-7222b, T-7224; `feed/services/important.py` — T-7216, T-7220, T-7222b;
    `feed/services/events.py` — T-7217, T-7220, T-7222b; `feed/services/live.py` — T-7222a; `feed/services/files.py` —
    T-7226, T-7227; `feed/views/home.py` — T-7213a, T-7223; `feed/views/posts.py` — T-7213b, T-7215, T-7220, T-7221,
    T-7224; `feed/views/comments.py` — T-7218, T-7221; `feed/views/files.py` — T-7226, T-7227; `feed/extensions.py` — по
    очереди T-7213a, T-7224, T-7227, T-7228, T-7230, T-7231, T-7232; `feed/urls.py` — по очереди T-7213a, T-7213b,
    T-7215, T-7216, T-7217, T-7218, T-7219, T-7220, T-7221, T-7223, T-7226, T-7227, T-7230; `feed/tasks.py` — T-7225,
    T-7229; `templates/feed/` — T-7213a (основа и пустые части), затем по очереди T-7213b, T-7215, T-7216, T-7217,
    T-7218, T-7219, T-7220, T-7221, T-7222a, T-7223, T-7226, T-7227, T-7230; `static/feed/feed.js` — T-7215, T-7216,
    T-7218, T-7220, T-7223, T-7226; `static/feed/feed.css` — T-7213a, дальше правила добавляют задачи тех же страниц по
    очереди; `templates/icons/feed.html` — T-7213a; `backend/tests/load/` — T-7234. Поэтому `[P]` стоит только у
    T-7203…T-7208 и T-7210, у которых нет общих файлов с соседями. Причина: параллельные правки одного файла теряют
    изменения (решение 9 TASKS-006).
30. **Изменения кода прежних срезов — каждое одной задачей и с тестом прежнего поведения** (план: «Изменения кода
    прежних срезов»; столбец «Что не меняется» — источник прежних тестов): `config/settings.py` — строка
    `INSTALLED_APPS` — T-7001 (решение 3), слой `publish` — T-7206 (`test_notify_deploy.py`: слой `default` прежний);
    `config/urls.py` — T-7001 (решение 3); `config/asgi.py` — T-7206 (`test_notify_deploy.py`, `test_notify_ws.py`);
    `config/cron.py` — T-7233 (`test_*_deploy.py`: прежние записи и минуты); `core/extensions.py` — T-7202
    (`test_extensions.py`, `test_sd_boundaries.py`, `test_lists_reminders_2.py`); `core/views/pages.py`,
    `templates/home.html`, `templates/_home_notices.html` — T-7203 (`test_calendar.py`, `test_org_pages.py`,
    `test_sd_queues.py`, `test_notify_boundaries.py`, приёмка `test_o11_calendar.py`, `test_d09_settings.py`,
    `test_cross_cutting.py` — в Chromium сразу после партии 2 и снова в T-7260); `core/context.py`,
    `core/services/permissions.py` — T-7203 (`test_feed_core_changes.py` — «Главная» без модуля,
    `test_org_permissions.py`); `templates/base.html` — T-7203 (`test_sd_list_2.py`, `test_sd_boundaries.py`);
    `core/models/files.py`, `core/migrations/0010_*` — T-7200 (`test_core_uploads.py`); `core/services/comments.py` —
    T-7204 (`test_kb_comments.py`, `test_kb_boundaries.py`); `core/services/pdn_patterns.py`,
    `knowledge/services/pdn.py` — T-7204 (`test_kb_pdn.py`, `test_kb_pdn_2.py`, тест равенства находок); `core/ws.py`,
    `notify/consumers.py` — T-7205 (`test_notify_ws.py`, новый тест 1013); `notify/services/live.py` — T-7206
    (`test_notify_ws.py`); `notify/services/dispatch.py` — T-7207 (`test_notify_coalesce.py`);
    `notify/services/prefs.py`, `notify/views/me.py`, `notify/views/admin.py`, `notify/services/settings.py` — T-7207
    (`test_notify_prefs.py`, `test_notify_catalog.py`, `test_notify_catalog_2.py`, `test_notify_admin.py`);
    `org/services/structure.py` — T-7208 (`test_org_*.py`, сверка новых функций в `test_feed_core_changes.py`);
    `deploy/nginx.conf`, `deploy/nginx.prod.conf` — T-7233 (`test_deploy_files.py`, `test_lists_deploy.py`,
    `test_kb_deploy.py`). Тесты прежнего поведения изменений `core/ws.py`, `notify`, `config/asgi.py` и слоя `publish` —
    `test_feed_core_changes_2.py` (T-7126a) и `test_feed_core_changes_3.py` (T-7126b). Других правок кода прежних срезов
    нет; нужна иная — остановка, решение Opus сюда, затем код. Причина: правило проекта о прежних срезах и сверка
    T-7307.
31. **Правки тестов прежних срезов — только T-7138, после T-7101, без `[P]`.** Разрешение владельца на каждую правку
    спрашивает Opus с диффом, по одному тесту; исполнитель правит только после ответа; партиями не правится. Перечень —
    `impact.md` и раздел плана «Прежние тесты, которые придётся поправить» (на T-7138 перечень не переписывается). Тесты
    «Проверить после реализации» и «не падают» заранее не правятся; если в Этапе 3 падает тест прежнего среза вне
    перечня, — остановка, решение Opus, правка по тому же правилу. Причина: правило владельца о тестах прежних срезов;
    правки зовут `support_feed.without_feed()` и `PERMISSIONS_007` (решения 29, 46, 62 TASKS-006). В эталоне красного
    прогона T-7160 отдельной строкой — тесты перечня T-7138, которые зеленеют только с T-7201 (права), T-7202 (точки),
    T-7206 (слой `publish`), T-7213a и T-7230 (меню), T-7224 (каталог уведомлений), T-7228 (поставщики поиска), T-7232
    (порядок сброса), T-7233 (cron и nginx); до этого они падают по той же причине, что новые.
32. **Порядок партий Этапа 3** — по зависимостям, близко к перечню задания на сборку, с отступлениями: ядро `0010` идёт
    в задаче моделей (иначе `feed 0001` применялась бы без своей зависимости); вывод текста — в партии 3 (его требует
    страница ленты); `unread` — в партии 4 (его требуют число в меню и показы страницы); векторы поиска — первым шагом
    публикации (вектор считается в её транзакции, поставщик — в партии 11); задание напоминаний — в партии уведомлений
    (оно создаёт уведомление); файлы дописывают публикацию, комментарий и правку. Причина: задача не должна ссылаться на
    ненаписанный код (решение 60 TASKS-006). Порядок партий утверждён 2026-10-30; ядро `0010` в T-7200 — одной задачей,
    названной в решении 30.
33. **Владельцы шаблонов, кнопок и частей страницы.** Каждая задача Этапа 3 пишет шаблоны своих частей и кнопки своих
    действий; T-7213a заводит `_post.html` и пустые части (`_post_head.html`, `_post_body.html`, `_post_to.html`,
    `_important.html`, `_event.html`, `_likes.html`, `_comments.html`, `_comment.html`, `_files.html`, `_form.html`,
    `_new_banner.html`, `_lists.html`), чтобы `{% include %}` не давал `TemplateDoesNotExist`; ссылка на адрес следующей
    задачи — через `{% url %}` только после того, как адрес заведён (иначе — заглушка маршрута в `urls.py`); шаг
    предупреждения о ПДн пишет T-7215, комментарий и правка его включают. Причина: решение 60 TASKS-006. Единственный
    автор шага предупреждения о ПДн — T-7215 (подтверждено 2026-10-30).
34. **Подключение стилей и скриптов — как в прежних модулях.** `static/feed/feed.css` — тегом `<link>`, `feed.js` —
    `<script defer>` в шаблонах страниц ленты (тело главной, карточка, настройка срока); поведение — внешние файлы и
    `Alpine.data`, без `on…=` и `style=`; во фрагментах WebSocket скриптов нет. Причина: общий `_assets.html` знает только
    общие файлы (решение 59 TASKS-006); план: «Где живёт код», «CSP».
35. **Этап 3 — по контракту.** Тексты отказов, адреса, параметры, зацепки `data-*` (`data-post-id`, `data-comment-id`,
    `#menu-badge-feed[data-count]`, `#feed-live[data-ws]`, `#feed-new`, `#feed-synced`, `data-file-state`, части
    `feed-post-<id>-…`), ключи сообщений слоя каналов и коды закрытия исполнители кода берут дословно из
    `CONTRACT-007.md`. Причина: приёмка читает зацепки из разметки, другой выбор исполнителя уронит верную по плану
    реализацию (решение 50 TASKS-006).
36. **Разметка блоков среза** — без `role="status"`, `role="alert"`, `data-error`, `data-warning`, кроме сообщений об
    отказах формы; узел живого числа «Ленты» — без `data-menu-badge` (план); форма фильтров ленты — своя, вне
    `form#staff-filter` и `#notify-bell`. Причина: такие атрибуты ловят локаторы приёмки прежних срезов (решение 13
    TASKS-006).
37. **Стенд.** Сбросы, пересборки, остановки служб и обновления стенда делает только Opus с разрешения владельца и всегда
    после копии стенда (`crm-work/slice005/stage4/t5301/backup-stand.sh`, в `crm-work/stand-backup`); приёмка идёт на
    пустом стенде, сброс — перед каждым кругом браузеров; после сна ноутбука — перезапуск worker-ов RQ (иначе задания
    файлов, писем и cron не исполняются); длинные прогоны — через `systemd-run --user`; Playwright — из `CRM/.venv`.
    Причина: опыт срезов 005–006 (решение 11 TASKS-006 и ловушки проекта).
38. **Обновление стенда с кодом среза** делает Opus с разрешения владельца после копии перед зелёным прогоном T-7260 и
    повторно перед T-7301, если код менялся: сборка образа, миграции, затем `up -d --no-deps web web-heavy worker
    worker-mail worker-inbox worker-notify notify-poller scheduler standtools nginx` и `restart nginx`. Причина: `nginx` —
    новый `location`; `scheduler` — две записи cron; `worker-notify` — задание напоминаний очереди `notify`;
    `worker-mail` — ночное задание очереди `maintenance`; `worker` — эскизы в очереди `files`; `web-heavy` — тот же образ
    (решения 26 и 63 TASKS-006); план («Запуск») требует перезапуска `scheduler`.
39. **Нагрузка и служба `web-heavy`.** Адреса ленты в `web-heavy` не идут: план («Запуск») оставляет службы прежними,
    тяжёлых адресов у ленты нет; вывод пересматривается по итогам T-7304. Нагрузочный прогон — по правилам `run4.sh`
    среза 006 (решения 63–65 TASKS-006): согласие владельца, остывшая машина (`/proc/loadavg` за 1 и 5 минут ниже 1,5),
    закрытые программы владельца, без агентов и `docker run`, копия и сброс стенда, `vmstat`/`mpstat`/`pidstat`, коды
    `nginx`; модель владельца (100 вошедших, вход 1/с, пауза 5–15 с, замер после входа всех); L1 — `FeedUser`, L2 — все
    классы. Частота публикатора задана: запись раз в 30 с (по очереди «Всем», подразделению, людям), комментарий раз в
    10 с; веса задач читателей исполнитель T-7234 пишет в описании класса, Opus утверждает их до T-7304. T-7234
    исполняет opus: класс с двумя соединениями и точной задержкой сложнее прежних. Причина: опыт среза 006 — замер на
    занятой машине не годится, а модель нагрузки меняется только решением владельца.
40. **Наблюдения NFR-614 и паузы Valkey — на стенде, Opus с разрешения владельца, после копии** (T-7305). Подмена адреса
    слоя `publish` закрытым портом — временный модуль настроек вне репозитория поверх `config.settings` во временном
    контейнере `web` того же образа в сети стенда, запросы — прямо в этот контейнер (кэш и очереди рабочие); пауза всего
    Valkey — `docker pause` на 60 с без порога. Запускает Opus после копии стенда и с разрешения владельца, как всё, что
    рядом со стендом. Причина: план («Нагрузка») требует отдельного прогона со слоем на закрытом порту и наблюдения
    паузы, но переменной для адреса слоя не вводит; продукт ради проверки не меняется.
41. **Пункты приёмки, которые Playwright не проходит,** — серверными тестами и ручным проходом: сценарий 14 п. 4 (модуль
    выключен) — T-7104, T-7136; сценарий 8 п. 8 в части бездействия и истёкшего пароля — T-7124; тихие часы по времени
    сотрудника — T-7128 (решение 14); ClamAV недоступен — T-7130 и T-7301 с остановкой службы Opus; сбой Valkey и код
    закрытия при обновлении `web` — T-7305; критерий «за 1 минуту» — T-7309. Причина: стенд нельзя выключать по модулю и
    ломать в автоматическом круге (решение 19 TASKS-006).
42. **Пределы ранних замеров** (утверждены 2026-10-30). Число непрочитанных и блок важных — p95 не больше 10 мс (четыре
    замера варианта C из F1; число считается на каждой странице); `unread.counts` — 50 мс на 100 получателей (предел
    плана); `permissions_of` — 100 мс на 100 получателей (рассылка идёт после фиксации, но в ответе публикации считается
    её подготовка — план, «Риски»: p95 публикации ≤ 500 мс); пачка ночного задания — 5 с (17 пачек F1 и запас до
    `job_timeout=600`). Выход за предел — остановка, ход выбирает Opus с владельцем до Этапа 3. Причина: план задаёт
    предел только для `counts`, а без порога ранний замер ничего не решает.
43. **Спорные пункты анализа влияния** (`impact.md`, «решить в TASKS-007»; предложения анализа, утверждает Opus): (а)
    `order` видов ленты 70…77 — по порядку строк таблицы плана («Запись для вас» 70 … «Нравится» 77), у `feed.like`
    `external_text=""` (внешних каналов нет) — T-7224 и T-7100; (б) снимок `matrix` после первого сохранения содержит
    все строки каталога, у `feed.like` — пустой список каналов вне портала (анализ, п. 30); (в) у вида с `channels`
    ячейки вне перечня в «Моих уведомлениях» и в таблице умолчаний администратора — `td[data-channel]` без флажка с
    `data-available="0"`; прежние циклы «у каждого вида четыре флажка» проходят виды без `channels`, для видов с
    `channels` — отдельная проверка «флажков внешних каналов нет» (анализ, п. 34, У1, У2) — код T-7207, правки T-7138;
    (г) тест колокольчика «других `ws-connect` на странице нет» открывает `/me/` вместо `/` (анализ, п. 43, вариант 2) —
    T-7138; на `/` новый тест среза проверяет два узла `ws-connect` — колокольчик и `#feed-live`
    (`test_feed_home.py::test_home_has_two_ws_connect_nodes_bell_and_feed_live`, T-7104); (д) `test_sd_boundaries.py`,
    второй вызов с возвратом регистраций (анализ, п. 26) — регистрации `apps.feed` не возвращаются (тест о «срезе 002»,
    проверка ключей не ослабляется) — T-7138. Причина: план эти детали не фиксирует, а без них правки прежних тестов и
    разметка расходятся.
44. **Имена маршрутов и журнал.** Маршруты среза не содержат `regist`, `signup`; `feed/audit_labels.py` подписывает
    каждый ключ `before`/`after`; журнал только дописывается, роль приложения не имеет `UPDATE` и `DELETE` на таблицу
    журнала (NFR-607 — тот же тест, что SPEC-006 NFR-508), ни одно задание его не чистит. Причина: это проверяют прежние
    тесты (`test_accounts.py`, тест подписей журнала; решения 15, 16 TASKS-006).
45. **Деление задач.** Задача Этапа 3, не укладывающаяся в ~50 вызовов агента, останавливается; Opus делит её буквами
    (`T-72NNa`, `T-72NNb`) без сдвига номеров и вписывает сюда. Причина: сбой на середине оставил бы общий файл
    недособранным (решение 61 TASKS-006). Заранее поделены: T-7126 — на T-7126a и T-7126b (28 тестов; файлы
    `test_feed_core_changes_2.py` и `test_feed_core_changes_3.py`); T-7213 — на T-7213a (главная, «Ещё записи», меню,
    регистрации, иконка, стили и пустые части шаблонов — их включает `body.html`, решение 33) и T-7213b (карточка,
    `/to/`); T-7222 — на T-7222a (`live.py`, классы рендера, число «Ленты») и T-7222b (вызовы рассылки из служб). При
    проверке задач (2026-10-30) поделены задачи Этапа 2: T-7102 — на T-7102a (видимость, аудитория, права действий;
    `test_feed_visibility.py`) и T-7102b (строка адресатов и полный список; `test_feed_visibility_3.py`) — в T-7102
    вышло 27 тестов; T-7140 — на T-7140a (`helpers_feed.py`, единственный автор помощников приёмки) и T-7140b
    (`test_f01_publish.py`); T-7140b и T-7141… стартуют после T-7140a.
46. **Публичные функции ядра и прежних модулей, которые зовёт `feed`,** — перечень шапки («Границы модуля `feed`»)
    закрепляет `CONTRACT-007.md` (T-7100); тест границ T-7136 и исполнители Этапа 3 опираются на этот один список.
    Модуль загрузки ядра — `core.services.uploads` (`apps/core/services/uploads.py`); план называет его коротко
    `core.uploads`, задачи и контракт пишут полное имя. Причина: иначе тест границ и код сверялись бы с разными
    перечнями.
47. **Упоминания при правке и «Исправить».** «Новое» упоминание при правке наблюдается возвратом службы:
    `mentions.sync(...)` возвращает множество номеров, впервые упомянутых этим текстом (имя и сигнатуру закрепляет
    контракт T-7100); уведомление о нём — отдельным тестом T-7127. «Исправить» в предупреждении о ПДн — действие клиента
    над тем же ответом: ответ с предупреждением несёт форму с введённым, записи нет, отдельного запроса нет (тест
    T-7111). Причина: план определяет «новое» упоминание только для уведомления (FR-629), а строки адресатов у прежнего
    номера уже есть.
48. **Текст отказа «Укажите начало и конец события».** FR-616 требует оба поля события, а в FR-642 и в разделе плана
    «Тексты отказов» текста нет; новый текст — в `feed/texts.py` через контракт (T-7100, T-7201), тест T-7113 сверяет
    его дословно. Решение по задачам; показать владельцу при подписи.
49. **Точки подмены для тестов гонок и сбоев** (раздел контракта T-7100 «Точки подмены для тестов гонок и сбоев»): сбой
    создания уведомления напоминания — `dispatch.create`, вызываемый из `feed.services.reminders`, логгер —
    `apps.feed.tasks`; ошибка `ws_state` в цикле проверки — для 1013 у `FeedConsumer` (T-7124) и `NotifyConsumer`
    (T-7126a); ошибка слоя каналов в `FeedConsumer` — для 1011 (T-7124); тестовый потребитель на примеси
    `SessionGuardMixin` (T-7126a). Отдельной проверки `asyncio.gather` нет (устройство кода). Снятие права модератора в
    тестах — сменой ролей средствами ядра (`roles.update_role`), отдельного помощника нет. Причина: план этих точек не
    называет, а без одного имени писатели тестов и исполнители кода разойдутся.
50. **Ночное задание: пропуски, отрицание, требования.** Запись, удалённая между выборкой пачки и удалением, в N журнала
    `feed.retention_purged` не входит: N — число действительно удалённых записей; тест
    `test_post_deleted_between_batch_selection_and_delete_is_skipped_without_error_and_not_counted_in_journal_posts`
    (T-7115) проверяет и N. Отрицательный тест «после истечения срока важного и прогона заданий новых уведомлений нет»
    (T-7112) годится. Шаги чистки показов и непривязанных загрузок служат FR-626 и FR-633 — в T-7115 они помечены и
    этими требованиями. Причина: план не говорит, входит ли пропущенная запись в N.
51. **Файлы и уведомления.** Эскиз у «чистого» файла без эскиза — 404 «Не найдено» (тест
    `test_thumb_of_clean_file_without_thumb_returns_404` в T-7130; в «Контрактах» плана не названо) — решение по
    задачам. Полный порядок приоритета уведомлений проверяется и прямым тестом `notify_rules.decide`
    (`test_notify_rules_decide_applies_full_priority_order`, T-7127; вход закрепляет контракт), пары сквозными
    действиями остаются; в T-7127 становится 26 тестов — в пределах «~25». Каналы «Нравится» проверяются в обеих
    задачах: T-7126b — механизм на тестовом виде, T-7128 — настоящий вид `feed.like`. Причина: сквозными действиями
    встречаются не все пары приоритета.
52. **Маршруты, адреса и cron без модуля в тестах.** Маршруты `asgi`, адреса `config/urls.py` и записи `config/cron.py`
    собираются при импорте, `without_feed()` их не снимает; тесты T-7135 и T-7136 разбирают исходник `ast` (вызов под
    `apps.is_installed("apps.feed")`), а для `asgi` — перезагружают `config.asgi` с подменой
    `django.apps.apps.is_installed` и возвращают модуль после теста; помощник `support_feed.reload_asgi_without_feed()`
    называет контракт (T-7100, T-7101). Причина: решение 22 запрещает пересборку реестра приложений.
53. **Сброс стенда и комментарии ленты.** `stand_reset` ленты удаляет и строки `core.Comment` с `object_ref`
    `feed.post:…` (как `knowledge/stand.py`), даже если общий сброс ядра их уже стёр; тест
    `test_feed_stand_reset_deletes_core_comments_with_feed_post_object_ref` (T-7134), код — T-7232. Причина: комментарии
    ленты живут в таблице ядра, и сброс ленты не должен зависеть от порядка чужих сбросов.
54. **Команды стенда: срок важного и выбор записей.** `e2e_feed_shift --minutes N` сдвигает назад на N минут и
    `important_until` важных записей, строка вывода — `feed_shift: shifted=<N> reminded=<M> important=<K>`; точный конец
    срока по Москве (12.10 00:00) — серверный тест T-7112, в браузере — «после сдвига срок истёк». `e2e_feed_retention
    --age-days N` получает необязательный ключ `--posts <номера через запятую>`: стареют только эти записи (остальные
    записи круга свежие и ночным заданием не удаляются); без ключа — все записи стенда (f12 «стенд целиком»); приёмка
    f09 и f12 передаёт номера своих записей; повтор ночного задания в f12 — `age(1, posts=[<свежая запись теста>])`:
    команда сдвигает свежую запись на сутки (она не старше срока) и запускает задание, которое ничего не удаляет, нового
    ключа нет. Границы — решение 10. Правят контракт T-7100, обёртки `shift`/`age` в T-7140a, тесты T-7134 и команды
    стенда T-7232. Решение по задачам; показать владельцу при подписи. Причина: план не даёт способа дождаться конца
    срока важного на стенде, а сдвиг всех записей ломал бы соседние тесты круга.
55. **WebSocket недоступен в браузере** — `BrowserContext.route_web_socket` Playwright 1.63 (есть в хостовом
    `CRM/.venv`): перехват `/ws/feed/` и `/ws/notify/` с закрытием; помощник `block_ws(context)` в `helpers_feed.py`
    (T-7140a), имя — в контракте T-7100. Приёмка f08 (T-7147) так проверяет работу обычными запросами. Причина: план
    говорит только «без WebSocket лента работает обычными запросами».
56. **Допуск 5 минут у напоминания** — серверные тесты T-7114; приёмка f03 (T-7142) проверяет только «напоминание пришло
    после сдвига к сроку» (команда стенда выполняет задание напоминаний в процессе). Причина: частоту задания cron
    браузер не наблюдает.
57. **Роль, созданная администратором до установки,** — серверный тест данных установки T-7133; приёмка f13 (T-7152)
    проверяет три начальные роли. Причина: на сброшенном стенде такой роли нет.
58. **Уточнения черновика G1.** В перечень T-7102 (теперь T-7102a и T-7102b) дописаны FR-620, FR-621, FR-622 (права
    действий: правка записи, удаление записи, правка и удаление комментария — у соответствующих тестов); у узла
    `#feed-live` в T-7104 — FR-627 рядом с FR-601; правило «`home_body` берёт первую зарегистрированную функцию, прочие
    пропускает» проверяет тест ядра `test_home_body_uses_first_registered_function_and_skips_others` (T-7137,
    `test_feed_core_changes.py`; в черновике он был под другим именем, второй тест не добавлялся).
59. **Время в SQL — только параметром.** Все сравнения с текущим моментом в SQL — выборка задания напоминаний, блок
    важных и конец срока важного, «было важным», ночное задание (граница срока, показы старше 31 дня), окно 30 дней
    счётчика непрочитанных — берут время из `timezone.now()` один раз на действие и передают его параметром `%s`, а не
    `now()` базы; `tasks.remind_events(now=None)` и `tasks.retention_night(now=None)` принимают время параметром. Так
    часы `Clock` и `run_reminders(now)`/`run_retention(now)` управляют временем во всех тестах (решение 5). Касается
    контракта T-7100 и задач T-7211, T-7212, T-7216, T-7220, T-7225, T-7229; литералы плана с `now()` пишутся с
    параметром, поведение не меняется. Решение по задачам (проверка задач, 2026-10-30); показать владельцу при подписи.
    Причина: `Clock` подменяет только `django.utils.timezone.now`, а `now()` базы остаётся настоящим, и тесты со сдвигом
    времени на буквальном литерале плана не прошли бы.
60. **Индекс `Shown(post_id)` (решение при исполнении И3, ответ владельца 2026-10-30 «Добавить индекс»).** Ранний
   замер T-7007: внешние ключи Django отложенные, и при фиксации пачки ночного задания PostgreSQL на каждую удалённую
   запись ищет ссылки в `Shown` по `post_id`; без индекса — просмотр таблицы целиком, 1,68 с на 1 000 записей при
   37 тыс. строк показов и около 77 с при 1,37 млн (если ночная чистка показов не шла). Поэтому у `Shown.post` —
   обычный индекс внешнего ключа (после чистки — меньше 1 МБ), вопреки строке плана «индекса (`post_id`) нет» (план,
   «Модель данных»; довод плана учитывал только каскад ORM). Затрагивает T-7200 (модель и миграция) и T-7229 (повтор
   замера первым шагом — проверка при фиксации без просмотра таблицы).
61. **`unread.counts` (решение при исполнении И2, ответ владельца 2026-10-30 «Как в плане»).** Ранний замер T-7003:
   45 мс медиана, 53 мс p95 на 100 получателей после ночной чистки показов (предел плана 50 мс, машина занята). Код —
   как в плане; запасной ход плана («Риски»: рассылка и уведомления — заданием очереди `notify`) включается, только
   если в нагрузке T-7304 p95 публикации выше 500 мс. Расчётное состояние таблицы показов — после ночной чистки (решение
   плана о чистке показов старше 31 дня).

62. **Условие отмены повторной вставки в `feed.js` (решение при исполнении И4, ранний факт T-7005).** На
   `htmx:oobBeforeSwap` вставка отменяется (`detail.shouldSwap = false`), только если элемент с тем же `id`, что у
   вставляемого, на странице есть и не равен `detail.target`. Условие «в кадре есть `id`, который уже на странице»
   неверно: у кадров `true`/`outerHTML` первый элемент фрагмента — сам заменяющий узел, и отменялись бы служебный
   `#feed-synced` и правка `#c<id>`. Уточняет механизм плана («Живые обновления» → `FeedConsumer`), поведение не
   меняет; затрагивает T-7223 и тест приёмки f08 «свой комментарий один раз».

63. **Закрытие соединений при перезапуске (решение при исполнении И5, ранний факт T-7006).** При SIGHUP,
   SIGTERM и `docker stop` gunicorn с `UvicornWorker` закрывает соединения кодом 1012, при SIGKILL исполнителя —
   обрыв (1006); 1000 и 1001 не наблюдались, оба кода htmx-ext-ws переподключает сам. Запасной ход плана («Риски»:
   переподключение при 1000/1001) в `feed.js` не вводится; T-7223 по `htmx:wsClose` только ставит `data-ws="closed"`.
   Молчащее соединение, принятое умирающим процессом сразу после SIGHUP (до ≈ 50 с, затем 1006), и окно пересоздания
   `web` учитываются в сроке ожидания проверки T-7305 через nginx.


**Показать владельцу при подписи.** Единственное отступление от PLAN-007 — решение 60 (индекс `Shown(post_id)` вместо «индекса нет», одобрено владельцем 2026-10-30); остальное — дополнения стенда и тексты —
ниже. Владельцу стоит увидеть: решение 3 (исключение каркаса T-7001 — строка `INSTALLED_APPS` и пустое подключение
адресов `feed`), решение 12 (задание напоминаний не завершается ошибкой из-за одного события), решение 39 (адреса ленты
не идут в `web-heavy`; частота публикатора нагрузки), решение 40 (способ подмены слоя `publish` на стенде), решение 42
(пределы ранних замеров), решение 43 (спорные пункты анализа влияния), а также решения по задачам: новый текст отказа
«Укажите начало и конец события» (решение 48), 404 у эскиза «чистого» файла без эскиза (решение 51), ключ `--posts` у
`e2e_feed_retention` и сдвиг `important_until` командой `e2e_feed_shift` (решение 54), границы команд стенда (решение
10), время в SQL параметром вместо `now()` базы в литералах плана (решение 59), полное имя модуля загрузки
`core.services.uploads` вместо `core.uploads` плана (решение 46), индекс `Shown(post_id)` (решение 60, ответ владельца), `unread.counts` как в плане со сроком проверки в T-7304 (решение 61, ответ владельца), условие отмены повторной вставки в `feed.js` (решение 62) и отказ от запасного хода при закрытии соединений (решение 63).

## Покрытие FR/NFR → задачи

Столбец «Этап 2» — задачи тестов, у которых хотя бы один тест помечен требованием (пересчитано по итоговым строкам задач
этого файла; контракт T-7100 — только FR-642; T-7101, T-7138, T-7140a, T-7159, T-7160 и диапазоны «FR-601…642» не
засчитываются — решение 26); столбец «Этапы 1, 3, 4» — задачи подготовки, реализации и проверки с явным номером в
перечне в конце строки.

| Требование | Этап 2 (тесты) | Этапы 1, 3, 4 |
|---|---|---|
| FR-601 | T-7104, T-7136, T-7137, T-7140b, T-7153 | T-7203, T-7213a |
| FR-602 | T-7105, T-7106, T-7125, T-7140b, T-7141, T-7147, T-7150 | T-7003, T-7211, T-7213a, T-7223 |
| FR-603 | T-7102a, T-7102b, T-7106, T-7140b | T-7211, T-7213a |
| FR-604 | T-7102a, T-7102b, T-7103, T-7108, T-7140b | T-7213b |
| FR-605 | T-7102a, T-7110, T-7112, T-7137, T-7140b, T-7141, T-7145 | T-7208, T-7209, T-7216, T-7217 |
| FR-606 | T-7102a, T-7102b, T-7103, T-7114, T-7122, T-7128, T-7130, T-7131, T-7140b, T-7141, T-7142, T-7146, T-7149, T-7150 | T-7209, T-7213a, T-7213b, T-7222a, T-7222b, T-7225, T-7227, T-7228, T-7307 |
| FR-607 | T-7102a, T-7102b, T-7140b | T-7200, T-7209, T-7211 |
| FR-608 | T-7107, T-7140b, T-7152 | T-7214, T-7215, T-7309 |
| FR-609 | T-7107, T-7109, T-7140b | T-7210, T-7214 |
| FR-610 | T-7107, T-7108, T-7117, T-7133, T-7140b, T-7152 | T-7214, T-7215, T-7220, T-7309 |
| FR-611 | T-7102a, T-7102b, T-7109, T-7110, T-7127, T-7142, T-7143, T-7145, T-7146 | T-7200, T-7210, T-7214, T-7215, T-7218, T-7220, T-7224 |
| FR-612 | T-7111, T-7137, T-7154 | T-7204, T-7214, T-7215, T-7218, T-7220 |
| FR-613 | T-7112, T-7134, T-7141 | T-7200, T-7216, T-7220 |
| FR-614 | T-7106, T-7112, T-7141 | T-7003, T-7211, T-7216 |
| FR-615 | T-7112, T-7141 | T-7208, T-7216 |
| FR-616 | T-7113, T-7142 | T-7200, T-7217 |
| FR-617 | T-7113, T-7142 | T-7208, T-7217 |
| FR-618 | T-7114, T-7134, T-7135, T-7142 | T-7217, T-7225, T-7232, T-7233 |
| FR-619 | T-7113, T-7114, T-7127, T-7142 | T-7220, T-7224, T-7225 |
| FR-620 | T-7102a, T-7106, T-7110, T-7112, T-7117, T-7141, T-7146, T-7152 | T-7209, T-7220 |
| FR-621 | T-7102a, T-7115, T-7118, T-7146, T-7152 | T-7209, T-7221, T-7229 |
| FR-622 | T-7102a, T-7110, T-7118, T-7146 | T-7204, T-7209, T-7221 |
| FR-623 | T-7119, T-7143 | T-7218 |
| FR-624 | T-7119, T-7137, T-7143 | T-7200, T-7204, T-7218 |
| FR-625 | T-7120, T-7144 | T-7219 |
| FR-626 | T-7104, T-7105, T-7115, T-7121, T-7122, T-7123, T-7125, T-7126a, T-7137, T-7147, T-7148 | T-7003, T-7200, T-7203, T-7205, T-7208, T-7212, T-7213a, T-7213b, T-7222a, T-7223 |
| FR-627 | T-7104, T-7119, T-7122, T-7123, T-7124, T-7125, T-7126a, T-7147 | T-7005, T-7006, T-7205, T-7206, T-7222a, T-7222b, T-7223, T-7305 |
| FR-628 | T-7103, T-7122, T-7123, T-7125, T-7147 | T-7004, T-7005, T-7208, T-7209, T-7222a, T-7222b, T-7223 |
| FR-629 | T-7126b, T-7127, T-7128, T-7141, T-7142, T-7143, T-7144, T-7145, T-7148 | T-7202, T-7207, T-7224 |
| FR-630 | T-7103, T-7108, T-7120, T-7127, T-7128, T-7141, T-7142, T-7143, T-7144, T-7145, T-7148 | T-7224 |
| FR-631 | T-7126b, T-7128, T-7143, T-7144, T-7148 | T-7202, T-7207, T-7224, T-7307 |
| FR-632 | T-7115, T-7118, T-7128, T-7148 | T-7221, T-7224, T-7229 |
| FR-633 | T-7115, T-7119, T-7129, T-7130, T-7135, T-7137, T-7143, T-7149 | T-7200, T-7226, T-7233 |
| FR-634 | T-7103, T-7130, T-7149 | T-7002, T-7227 |
| FR-635 | T-7103, T-7105, T-7106, T-7108, T-7110, T-7125, T-7150 | T-7211, T-7213a, T-7215, T-7223 |
| FR-636 | T-7103, T-7131, T-7150 | T-7228 |
| FR-637 | T-7131, T-7150 | T-7214, T-7228 |
| FR-638 | T-7115, T-7116, T-7133, T-7134, T-7135, T-7151 | T-7007, T-7200, T-7201, T-7229, T-7230, T-7232, T-7233, T-7307 |
| FR-639 | T-7115, T-7116, T-7118, T-7132, T-7146, T-7151, T-7152 | T-7221, T-7229, T-7230, T-7231, T-7307 |
| FR-640 | T-7107, T-7117, T-7133, T-7134, T-7152 | T-7201, T-7214, T-7220, T-7232 |
| FR-641 | T-7104, T-7126a, T-7126b, T-7131, T-7135, T-7136, T-7137, T-7153 | T-7001, T-7202, T-7203, T-7206, T-7213a, T-7228, T-7233, T-7307 |
| FR-642 | T-7100, T-7107, T-7110, T-7112, T-7113, T-7116, T-7117, T-7119, T-7129, T-7130, T-7140b, T-7141, T-7142, T-7143, T-7145, T-7149, T-7151 | T-7201, T-7210, T-7214, T-7215, T-7216, T-7217, T-7218, T-7220, T-7226, T-7227, T-7230 |
| NFR-601 | T-7106 | T-7003, T-7211, T-7212, T-7234, T-7304 |
| NFR-602 | T-7147 | T-7004, T-7222a, T-7234, T-7302, T-7304 |
| NFR-603 | T-7131 | T-7228, T-7234, T-7304 |
| NFR-604 | T-7129, T-7135, T-7149 | T-7226, T-7233, T-7301, T-7302 |
| NFR-605 | T-7109, T-7123, T-7128, T-7135, T-7140b | T-7005, T-7210, T-7213a, T-7213b, T-7215, T-7222a, T-7224, T-7301, T-7307 |
| NFR-606 | T-7140b, T-7141, T-7142, T-7143, T-7144, T-7150, T-7151, T-7153 | T-7213a, T-7215, T-7230, T-7301, T-7302 |
| NFR-607 | T-7132 | T-7231, T-7307 |
| NFR-608 | T-7105, T-7125, T-7131, T-7150 | T-7003, T-7211, T-7214, T-7223, T-7228, T-7303, T-7307 |
| NFR-609 | T-7128, T-7148 | T-7224, T-7307 |
| NFR-610 | T-7114, T-7115, T-7151, T-7135 | T-7007, T-7225, T-7229 |
| NFR-611 | T-7112, T-7128, T-7135 | T-7213a, T-7216, T-7224 |
| NFR-612 | T-7135 | T-7002, T-7234, T-7304 |
| NFR-613 | T-7130, T-7135 | T-7227, T-7233, T-7306 |
| NFR-614 | T-7123, T-7126a, T-7130, T-7135 | T-7006, T-7206, T-7222a, T-7222b, T-7227, T-7301, T-7305 |

Итог: у каждого требования FR-601…642 и NFR-601…614 есть задача Этапа 2 и задача Этапов 1, 3, 4. Только наличием файлов
нагрузки в серверных тестах (без своего замера в Этапе 2): NFR-612 — его проверяет прогон T-7304.
