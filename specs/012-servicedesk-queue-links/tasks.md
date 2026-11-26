---
id: TASKS-012
вид: задачи
статус: утверждён
версия: 5
зависит_от: PLAN-012
основан_на: PLAN-012 sha256:dae37607295697e411bf3c64de1ecd0a279029c4db561a16e2867d757503d5a0
подпись: Максим | 2026-11-25T21:46+03:00 | sha256:e81e03166f046e1b798bf86dea4ddd8d24b19b15da01c5dbe4a9a724e5490b63
---

# Задачи среза 012: Заявки: очередь и связи

Формат строки: `- [ ] T-NNNNN [P] [исполнитель] описание — файлы или тест — (FR-NNN / NFR-NNN)`.
`[P]` означает, что задача не правит общий файл соседней задачи и может идти параллельно.
Исполнители: `code` — код и тесты, `arch` — контракт, стенд, прогоны и сверка, `человек` —
ручной проход и разрешения. Код и документы не подписываются исполнителем.

## Правила выполнения

- Этапы выполняются последовательно: этап 3 начинается только после красного прогона T-12113,
  этап 4 — после зелёного прогона реализации.
- Один автор на общий файл. `backend/apps/servicedesk/models.py` изменяет только T-12004;
  `backend/apps/servicedesk/urls.py` — только T-12010; `backend/apps/servicedesk/notify_kinds.py`
  — только T-12208; `reports.py` — только T-12213; `backend/apps/tasks/models.py` — только T-12005.
  `backend/config/cron.py` не меняется.
- `backend/apps/servicedesk/stand.py` изменяет только T-12014/T-12222 одним автором;
  `backend/apps/tasks/stand.py` — только T-12015/T-12223 одним автором. Шаблоны разделены:
  T-12221 — `servicedesk/list/`, `settings/`, `form/`; T-12219 — `servicedesk/queues/`; T-12218 — `servicedesk/card/`;
  T-12211 — `servicedesk/mail/`; T-12212 — `rating/`; T-12213 — `reports/`; T-12217 — `tasks/`.
- Задача рассчитана не более чем на полдня; файл тестов — не более примерно 25 тестов.
  Большой набор делится на `_2`, не ослабляется.
- Секреты в выводе и отчётах — только `***`; реальные ПДн в seed, нагрузке и артефактах не
  используются.
- `config/cron.py` не добавляет задания: распределение выполняется сразу, дата доступности
  проверяется при обращении, таймер присутствия и cron вне среза.
- Полные и нагрузочные прогоны запускаются через `systemd-run --user` с парой файлов
  `*.status`, `*.log`, `*.exit`; работающий или завершённый прогон не дублируется.

## Этап 1 — каркас, контракт, данные, помощники, стенд

- [x] T-12001 [arch] `CONTRACT-012`: маршруты очередей, правила, наблюдателей, оценки и задач; параметры `?ticket=N`;
  коды отказов (`no_access`, `not_participant`, `observer_readonly`, `queue_rule_mode`, `rating_code`,
  `rating_expired`, `rating_rate_limited`, `task_ticket_hidden`, `task_assignee_forbidden`); `data-*` для
  форм, частей карточки, оценки и журнала; ответы HTMX и обычные; русские подписи событий — `backend/tests/CONTRACT-012.md` —
  (FR-759 / FR-766 / FR-770 / FR-773 / FR-779)
- [x] T-12002 [P] [code] поля `User.unavailable_until`, примечание, `unavailable_by`, `unavailable_at`;
  миграция `core 0017` от `0016`, ограничения дат и обратимость; `default_permissions` не меняется —
  `backend/apps/core/models/accounts.py`, `backend/apps/core/migrations/0017_user_unavailability.py` —
  (FR-765 / FR-780)
- [x] T-12003 [P] [code] публичная служба `org/services/availability.py` для проверки руководителя узла и
  `core/services/accounts.set_availability` с проверками самого сотрудника и администратора; проверку
  руководителя выполняет `org`-служба; подготовить контракты профиля и карточки сотрудника —
  `backend/apps/org/services/availability.py`,
  `backend/apps/core/services/accounts.py`, `backend/apps/core/views/me.py`, `backend/apps/core/views/staff_actions.py`,
  `backend/apps/org/views/members.py` — (FR-765)
- [x] T-12004 [arch] модели `QueueRule`, `QueueObserver`, `TicketRating`, индексы, partial unique и
  `token_hash` unique; снимки закрытия/цикла; миграция `servicedesk 0005` после `core 0017` и `servicedesk 0004`;
  один автор `models.py` — `backend/apps/servicedesk/models.py`,
  `backend/apps/servicedesk/migrations/0005_queue_links.py` — (FR-759 / FR-766 / FR-769 / FR-771)
- [x] T-12005 [P] [arch] поле `Task.ticket_number` nullable, положительное, индекс `(ticket_number,deleted_at)`,
  без FK; миграция `tasks 0002` после `tasks 0001`, без зависимости на модель `servicedesk`; один автор
  `tasks/models.py` — `backend/apps/tasks/models.py`, `backend/apps/tasks/migrations/0002_ticket_number.py` —
  (FR-776 / FR-777)
- [x] T-12006 [P] [code] каркас `can_view/can_work`: observer даёт чтение очереди и карточки, но не работу;
  перевести видимые заявки, меню, `get_for`, listing, поиск и `public.briefs` на `can_view`, все мутации
  оставить на `can_work`; кандидаты исключают наблюдателей, уволенных и недоступных — `backend/apps/servicedesk/services/access.py`,
  `listing.py`, `search.py`, `public.py` — (FR-767 / FR-777 / FR-780)
- [x] T-12007 [P] [code] контракты `distribution.py`: режимы `off/evenly/strictly/all`, кандидаты,
  `select_for_update` правила/очереди, причины возврата и идемпотентное событие; порядок приоритетов
  зафиксировать без реализации — `backend/apps/servicedesk/services/distribution.py` — (FR-759 / FR-760 / FR-761 /
  FR-762 / FR-763 / FR-764 / NFR-736)
- [x] T-12008 [P] [code] контракт `rating.py`: цикл, генерация 12 знаков Crockford base32, hash с retry
  до трёх попыток, срок 7 дней, POST-сессия и rate limit 5/15 минут на IP+заявку; код не попадает в URL,
  лог и интерфейс — `backend/apps/servicedesk/services/rating.py` — (FR-769 / FR-770 / FR-771 / NFR-738)
- [x] T-12009 [P] [code] публичные контракты `servicedesk/services/task_links.py` и
  `tasks/services/task_links.py`: `task_seed` требует `can_work`, `create_from_ticket` — единственная
  точка `assignee_authorized`; обратного создания нет — `backend/apps/servicedesk/services/task_links.py`,
  `backend/apps/tasks/services/task_links.py` — (FR-773 / FR-774 / FR-775 / FR-778)
- [x] T-12010 [arch] маршруты-заглушки и контракты представлений для правил/наблюдателей, `/rate/?ticket=N`,
  `/tasks/new/?ticket=N`, блоков карточек и отчёта; один автор обоих `urls.py`, HTMX/обычные ответы и 403 —
  `backend/apps/servicedesk/urls.py`, `backend/apps/tasks/urls.py` — (FR-759 / FR-766 / FR-770 / FR-773 / FR-781)
- [x] T-12011 [P] [arch] зафиксировать каркас контрактов шаблонов очереди, настроек, карточки, оценок,
  отчёта и блоков задач; русские тексты, `data-*`, 360 px без горизонтальной прокрутки; шаблоны
  распределены между T-12221, T-12219, T-12218, T-12211, T-12212, T-12213 и T-12217 — `backend/tests/CONTRACT-012.md` —
  (FR-767 / FR-770 / FR-772 / FR-776 / FR-781 / FR-782)
- [x] T-12012 [P] [arch] расширение `audit_labels.py` без новых notification kinds: режим получателей
  по `can_view`, события observer/распределения/оценки/связи и идемпотентный ключ
  заявка+получатель+срок; реализация `notify_kinds.py` остаётся одному автору T-12208 —
  `backend/apps/servicedesk/audit_labels.py` — (FR-768 / FR-779 / NFR-739)
- [x] T-12013 [P] [arch] зафиксировать контракт отчёта: среднее с одним знаком, число оценок, «—»,
  фильтр по `closed_at_snapshot`, те же фильтры в Excel; реализация `reports.py` остаётся одному
  автору T-12213 — `backend/tests/CONTRACT-012.md` — (FR-772 / NFR-740)
- [x] T-12014 [P] [code] расширить только `servicedesk/stand.py`: удаление `TicketRating`, `QueueObserver`,
  `QueueRule`, rate-limit и rating-сессий; не удалять Task и поля core; зарегистрировать порядок сброса —
  `backend/apps/servicedesk/stand.py` — (FR-780)
- [x] T-12015 [P] [code] расширить только `tasks/stand.py`: очистка Task и `ticket_number` штатным сбросом
  tasks; не удалять таблицы servicedesk; проверить идемпотентность повторного reset —
  `backend/apps/tasks/stand.py` — (FR-776 / FR-780)
- [x] T-12016 [P] [arch] тестовые фабрики и E2E seed: четыре режима, участники, наблюдатель, недоступный,
  циклы рейтинга, задача из заявки, синтетические данные без ПДн; помощники `open_ticket`, `set_availability`,
  `rate_ticket`, `open_task`, `check_360` — `backend/tests/support_servicedesk.py`,
  `backend/tests/e2e/helpers_t12.py`, `backend/apps/servicedesk/management/commands/e2e_queue_links_seed.py` —
  (FR-759 / FR-765 / FR-768 / FR-772 / FR-776)
- [x] T-12017 [P] [arch] подготовить отдельный список правок прежних тестов и разрешительный флаг; правки
  не выполнять: `test_sd_access.py`, `test_sd_boundaries.py`, `test_notify_catalog.py`, `test_notify_prefs.py`,
  `test_sd_audit.py`, `test_sd_reports.py`, `test_sd_reports_excel.py`, `test_sd_stand_restore.py`,
  deploy/меню tests и `test_tasks_*.py` — `backend/tests/…`, раздел «Правки прежних тестов» ниже —
  (FR-767 / FR-768 / FR-772 / FR-779)
- [x] T-12018 [P] [arch] расширить профиль производительности и загрузчик без cron: 110 тыс. заявок,
  550 тыс. сообщений, наблюдатели/режимы/рейтинги/задачи, страницы очереди/карточки/настройки и
  50 публичных заявителей рейтинга — `backend/tests/load/locustfile.py`, `backend/tests/load/fill_tickets.py` —
  (NFR-737 / NFR-738)

## Этап 2 — красные тесты

Каждый тест в этом этапе должен быть красным до реализации; тесты каркаса миграций и стенда
допускаются зелёными только после фиксации результата T-12004/T-12014/T-12015.

- [x] T-12101 [P] [code] модели и ограничения: режимы, one-to-one, активный observer, снимки рейтинга,
  срок/балл, unique `token_hash` и collision retry, `ticket_number`, unavailable fields — `backend/tests/test_sd_012_models.py` —
  (FR-759 / FR-765 / FR-766 / FR-771 / FR-776)
- [x] T-12102 [P] [code] доступ и область: `can_view/can_work`, меню, список, поиск, `get_for`, briefs,
  полная карточка observer, все мутации 403, руководитель очереди и unavailable права —
  `backend/tests/test_sd_012_access.py` — (FR-765 / FR-766 / FR-767 / FR-777 / FR-780)
- [x] T-12103 [P] [code] распределение: настройка, приоритет `take_by/category/SLA/distribution`, evenly,
  strictly, all, кандидаты, возврат manual/reconcile/unavailable/transfer/category, закрытые не трогаются —
  `backend/tests/test_sd_012_distribution.py` — (FR-759 / FR-760 / FR-761 / FR-762 / FR-763 / FR-764 / FR-765)
- [x] T-12104 [P] [code] конкуренция NFR-736: параллельные create/take для evenly и strictly, один указатель,
  один ответственный, одно событие и идемпотентный повтор — `backend/tests/test_sd_012_concurrency.py` —
  (NFR-736)
- [x] T-12105 [P] [code] рейтинг: manual close с ответом/без ответа, autoclose, POST-код, CSRF, 7 дней,
  5 неверных вводов за 15 минут IP+заявка, короткая сессия, reopen и история — `backend/tests/test_sd_012_rating.py` —
  (FR-769 / FR-770 / FR-771 / NFR-738)
- [x] T-12106 [P] [code] задача: `task_seed` требует `can_work`, observer и tasks без `tasks.use` отклоняются,
  `create_from_ticket` — единственная точка `assignee_authorized`, предзаполнение и обычные права; обе
  стороны связи, свежие тема/статус, видимость по двум модулям, soft delete, отсутствие reverse sync и
  связи у заявителя — `backend/tests/test_sd_012_tasks.py` —
  (FR-773 / FR-774 / FR-775 / FR-776 / FR-777 / FR-778 / NFR-740)
- [x] T-12107 [P] [code] наблюдательские уведомления, аудит всех действий, русский/Москва и NFR-739 для
  новой заявки, просрочки и оценки с ключом заявка+получатель+срок и повторами до/во время/после —
  `backend/tests/test_sd_012_notify_audit.py` — (FR-768 / FR-779 / FR-782 / NFR-739)
- [x] T-12108 [P] [code] отчёт и Excel: среднее с одним знаком, число, «—», `closed_at_snapshot`, снимки
  фильтров, managed_units, отсутствие ПДн/темы/переписки — `backend/tests/test_sd_012_reports.py` —
  (FR-772)
- [x] T-12109 [P] [code] контракт и представления: все маршруты, коды отказов, HTMX/обычные ответы,
  `data-*`, подписи журнала, публичная rating-страница и кнопка задачи — `backend/tests/test_sd_012_contract.py` —
  (FR-759 / FR-766 / FR-770 / FR-773 / FR-779 / FR-781)
- [x] T-12110 [P] [arch] E2E-красные сценарии `test_t12_01`…`test_t12_07` и helpers: распределение,
  observer, unavailable, rating, task link, rights/audit, 360 px/Moscow — `backend/tests/e2e/test_t12_*.py` —
  (FR-759 / FR-765 / FR-767 / FR-770 / FR-776 / FR-781 / FR-782)
- [x] T-12111 [P] [code] производительность: p95 500 мс для очереди, карточки, настройки и блока задач
  на 100 пользователях; rating p95 500 мс и 50 заявителей с rate limit — `backend/tests/test_sd_012_performance.py` —
  (NFR-737 / NFR-738)
- [x] T-12112 [P] [code] стенд, seed и миграции: проверка двух независимых stand_reset, порядка core →
  servicedesk → tasks, отсутствия ПДн, очистки rate-limit/сессий и задач — `backend/tests/test_sd_012_stand.py`;
  прежний `test_sd_stand_restore.py` не правится до T-12301 и разрешения владельца — (FR-780)
- [x] T-12113 [arch] красный серверный прогон новых тестов и первичная фиксация; запуск через
  `systemd-run --user` с `stage2.status`, `stage2.log`, `stage2.exit`; остановка при неожиданном падении
  вне плана, без повторного запуска завершённых прогонов — `crm-work/slice012/stage2/` —
  (FR-759 / FR-782 / NFR-736 / NFR-737 / NFR-738 / NFR-739 / NFR-740)

## Этап 3 — реализация партиями

Партии идут в порядке: доступ и недоступность; распределение; оценка; задачи; уведомления/аудит;
отчёт; интерфейс и стенд. После каждой партии выполняется весь серверный набор. Общий файл не
правят параллельно.

- [x] T-12201 [code] реализовать `can_view/can_work`, observer scope, списки, поиск, `get_for`, briefs и
  read-only карточку; все мутации оставить на `can_work` — `backend/apps/servicedesk/services/access.py`,
  `listing.py`, `search.py`, `public.py`, views — (FR-766 / FR-767 / FR-777)
- [x] T-12202 [code] реализовать availability: `set_availability`, проверку руководителя узла, профиль,
  карточку сотрудника, аудит и возврат открытых заявок при недоступности; без cron — `backend/apps/core/services/accounts.py`,
  `backend/apps/org/services/availability.py`, `backend/apps/core/views/me.py`,
  `backend/apps/core/views/staff_actions.py`, `backend/apps/org/views/members.py` — (FR-765)
- [x] T-12203 [code] реализовать миграции подготовленных моделей, применить порядок `core 0017`,
  `servicedesk 0005`, `tasks 0002`, выполнить `manage.py check` и проверить ограничения —
  `backend/apps/core/migrations/0017_user_unavailability.py`,
  `backend/apps/servicedesk/migrations/0005_queue_links.py`,
  `backend/apps/tasks/migrations/0002_ticket_number.py` — (FR-759 / FR-765 / FR-766 / FR-771 / FR-776)
- [x] T-12204 [code] реализовать `distribution.py`: кандидаты, off/evenly/strictly/all, блокировки,
  указатель, причины возврата, исключение недоступных/наблюдателей и идемпотентность —
  `backend/apps/servicedesk/services/distribution.py` — (FR-759 / FR-760 / FR-761 / FR-762 / FR-763 / FR-764 / NFR-736)
- [x] T-12205 [code] подключить распределение к `tickets.create` после `take_by`, категории и SLA;
  сохранить явного/дефолтного ответственного и одно событие — `backend/apps/servicedesk/services/tickets.py`,
  `assignment.py` — (FR-760 / FR-761 / FR-762 / FR-763)
- [x] T-12206 [code] подключить возврат после ручного снятия и `reconcile`; при unavailable возвращать
  только открытые заявки, ручное назначение недоступному оставить разрешённым — `assignment.py`,
  `reconcile.py`, `distribution.py` — (FR-764 / FR-765)
- [x] T-12207 [code] подключить возврат/распределение после transfer и смены категории без ответственного,
  закрытые заявки не распределять — `backend/apps/servicedesk/services/transfer.py`,
  `services/tickets.py`, `services/closing.py` — (FR-764)
- [x] T-12208 [code] реализовать получателей и идемпотентность существующих уведомлений по `can_view`,
  включая all, новую уже назначенную заявку и просрочку; новых видов не добавлять — `backend/apps/servicedesk/notify_kinds.py` —
  (FR-763 / FR-768 / NFR-739)
- [x] T-12209 [code] реализовать audit labels и записи режима, observers, unavailable, distribution с причиной,
  rating и task link; системный actor пуст — `backend/apps/servicedesk/audit_labels.py`,
  `backend/apps/core/services/audit.py` — (FR-759 / FR-766 / FR-765 / FR-779)
- [x] T-12210 [code] реализовать `rating.py`: цикл, token hash unique/retry, ссылка, срок, current/history,
  rate limit 5/15 IP+заявка, короткая сессия и reopen — `backend/apps/servicedesk/services/rating.py` —
  (FR-769 / FR-770 / FR-771 / NFR-738)
- [x] T-12211 [code] подключить рейтинг к manual close только при ответе исполнителя, не подключать к autoclose,
  письмо со ссылкой и кодом в тексте; расширить renderer без кода в URL — `closing.py`, `letters.py`,
  `backend/templates/servicedesk/mail/` — (FR-769 / FR-770)
- [x] T-12212 [code] реализовать открытые rating views: GET формы, POST кода/балла, CSRF, общее истечение,
  короткая сессия и русские тексты; маршрут уже объявлен T-12010 — `backend/apps/servicedesk/views/rating.py`,
  `backend/templates/servicedesk/rating/` — (FR-770 / FR-781 / FR-782)
- [x] T-12213 [code] реализовать показатель отчёта и Excel по `closed_at_snapshot`, current rating,
  снимкам очереди/уровня/категории/исполнителя, среднее/число/«—» — `backend/apps/servicedesk/services/reports.py`,
  `backend/apps/servicedesk/views/reports.py`, `backend/templates/servicedesk/reports/` — (FR-772)
- [x] T-12214 [code] реализовать `servicedesk/services/task_links.py`: task_seed только `can_work`,
  последнее сообщение заявителя, тема, ссылка и активный ответственный; блок задач с актуальными данными —
  `backend/apps/servicedesk/services/task_links.py`, `views/ticket_card.py` — (FR-773 / FR-774 / FR-776)
- [x] T-12215 [code] реализовать `tasks/services/task_links.py::create_from_ticket` как единственную
  точку `assignee_authorized`; повторно проверять `can_work`, `tasks.use`, номер и активного ответственного —
  `backend/apps/tasks/services/task_links.py` — (FR-773 / FR-775)
- [x] T-12216 [code] расширить `tasks.services.tasks.create` флагом `assignee_authorized`: разрешать без
  `tasks.assign` только активного ответственного заявки, остальных проверять обычными правами; прямой
  `create` без точки связи не получает исключение — `backend/apps/tasks/services/tasks.py` — (FR-775)
- [x] T-12217 [code] реализовать `/tasks/new/?ticket=N`, предзаполнение, блок «Заявка», видимость и
  soft delete; заявитель и скрытая заявка не получают блок — `backend/apps/tasks/views/pages.py`,
  `backend/templates/tasks/` — (FR-773 / FR-774 / FR-776 / FR-777 / FR-778 / NFR-740)
- [x] T-12218 [code] подключить блок «Задачи» и актуальную карточку заявки; скрыть кнопки и прямые POST
  наблюдателя; сохранить can_view для чтения вложений/переписки — `backend/apps/servicedesk/views/ticket_card.py`,
  `views/tickets_list.py`, `backend/templates/servicedesk/card/`, `listing.py` — (FR-767 / FR-773 / FR-776 / FR-777)
- [x] T-12219 [code] реализовать страницы правил и наблюдателей с проверкой `servicedesk.manage` или
  `managed_units`, добавлением/снятием и журналом; менять только данные очереди — `backend/apps/servicedesk/views/settings.py`,
  `services/queues.py`, `backend/templates/servicedesk/queues/` — (FR-759 / FR-766 / FR-780)
- [x] T-12220 [code] подключить меню, точки расширения, части карточки и регистрацию новых сервисов без
  новых глобальных прав — `backend/apps/servicedesk/extensions.py`, `backend/apps/tasks/extensions.py` —
  (FR-759 / FR-766 / FR-776 / FR-780)
- [x] T-12221 [P] [code] завершить шаблоны списка, настроек и формы, HTMX/обычные ответы, `data-*`,
  тексты по-русски, Europe/Moscow и раскладку 360 px; очереди — T-12219, карточка, почта, оценка, отчёты
  и задачи — у своих задач — `backend/templates/servicedesk/{list,settings,form}/` — (FR-767 / FR-770 / FR-781 / FR-782)
- [x] T-12222 [P] [code] реализовать только servicedesk stand-reset: новые модели и rating keys/session,
  без удаления задач и core availability — `backend/apps/servicedesk/stand.py` — (FR-780)
- [x] T-12223 [P] [code] реализовать только tasks stand-reset: очистку Task и ticket_number, без удаления
  servicedesk-моделей; проверить общий порядок `e2e_reset_stand` — `backend/apps/tasks/stand.py` —
  (FR-776 / FR-780)
- [x] T-12224 [P] [arch] реализовать E2E seed/helpers и синтетический набор всех семи сценариев, включая
  все режимы, observer, unavailable, rating, task link и 360 px — `backend/apps/servicedesk/management/commands/e2e_queue_links_seed.py`,
  `backend/tests/e2e/helpers_t12.py`, `backend/tests/e2e/test_t12_*.py` — (FR-759 / FR-765 / FR-768 / FR-772 / FR-776 / FR-781)
- [x] T-12225 [arch] зелёный серверный прогон после реализации партий, сверка с T-12113 и фиксация
  единственного первичного результата; запуск через `systemd-run --user` с `stage3.status`, `stage3.log`,
  `stage3.exit` — `crm-work/slice012/stage3/` — (FR-759 / FR-782 / NFR-736 / NFR-740)

## Этап 4 — приёмка

- [x] T-12300 [arch] полный серверный прогон новых и разрешённых прежних тестов, `manage.py check`,
  `tools/verify.sh --быстро`, `git diff --check`; артефакты через `systemd-run --user`
  (`stage4.status`, `stage4.log`, `stage4.exit`) — `crm-work/slice012/stage4/server/` —
  (FR-759 / FR-782 / NFR-736 / NFR-740)
- [x] T-12301 [arch] регрессия прежних тестов по таблице ниже; если падает тест вне разрешённого списка —
  остановка и решение владельца, тест не ослаблять — `backend/tests/…` —
  (FR-767 / FR-768 / FR-772 / FR-779)
- [x] T-12302 [arch] браузерная приёмка: семь сценариев `test_t12_01`…`test_t12_07` в Chromium, Firefox,
  Edge и Яндекс.Браузере; `test_t12_07` дополнительно проверяет 360 px, русский интерфейс и Москву; всего
  7 сценариев × 4 браузера — `backend/tests/e2e/test_t12_*.py` — (FR-759 / FR-765 / FR-767 / FR-770 /
  FR-776 / FR-781 / FR-782)
- [x] T-12303 [arch] нагрузка NFR-737 на холодной машине: 100 одновременных пользователей, 110 тыс.
  заявок и 550 тыс. сообщений, очередь/карточка/настройки/задачи p95 не более 500 мс; systemd-файлы
  `load737.status`, `load737.log`, `load737.exit` — `backend/tests/load/locustfile.py`,
  `crm-work/slice012/stage4/load/` — (NFR-737)
- [x] T-12304 [arch] нагрузка NFR-738: 50 одновременных заявителей, rating p95 не более 500 мс,
  перебор кода невозможен, пять неверных вводов за 15 минут на IP+заявку; systemd-файлы
  `load738.status`, `load738.log`, `load738.exit` — `backend/tests/load/locustfile.py`,
  `crm-work/slice012/stage4/load/` — (NFR-738)
- [x] T-12305 [человек] ручной проход без ПДн: создать заявку во всех режимах, проверить observer,
  unavailable, rating manual/autoclose/reopen, задачу с обеих сторон, права и прямой отказ —
  `crm-work/slice012/stage4/manual/` — (FR-759 / FR-765 / FR-768 / FR-770 / FR-776 / FR-780)
- [x] T-12306 [arch] отчёт приёмки: среднее/число/«—», период по `closed_at_snapshot`, фильтры,
  Excel без темы/текста/адресов/ПДн, свежесть статуса и soft delete — `crm-work/slice012/stage4/report.md` —
  (FR-772 / NFR-740)
- [x] T-12307 [arch] проверить миграционный порядок, повторный stand reset, отсутствие изменений
  `config/cron.py`, отсутствие новых глобальных прав, секретов и ПДн в diff/артефактах —
  `crm-work/slice012/stage4/gates/` — (FR-780 / NFR-739)
- [x] T-12308 [arch] проверить идемпотентность новых уведомлений и аудита повторным запуском до, во время
  и после создания; сверить одну запись на заявку/получателя/срок — `crm-work/slice012/stage4/notify/` —
  (FR-768 / FR-779 / NFR-739)
- [x] T-12309 [arch] обновить отчёт проверки TASKS-012 фактами прогонов, покрытием FR/NFR, известными
  ограничениями и ссылками на первичные артефакты; сохранить секреты как `***` —
  `docs/reviews/TASKS-012.md` — (FR-759 / FR-782 / NFR-736 / NFR-740)
- [x] T-12310 [человек] передать владельцу результат приёмки, список разрешённых правок прежних тестов
  и нерешённых рисков; подпись документов и `git push` не выполнять — `crm-work/slice012/stage4/` —
  (FR-759 / FR-782 / NFR-736 / NFR-740)

## Правки прежних тестов — только с разрешения владельца

Эти изменения не входят в обычную реализацию и выполняются только отдельными задачами T-12017/T-12301
после явного разрешения. Никаких ослаблений проверок, замены 403 на 200 или удаления точных наборов.

| Файл/область | Было | Станет | Почему |
|---|---|---|---|
| `backend/tests/test_sd_access.py` | `visible_tickets` и `can_work` совпадают | отдельные `can_view/can_work`, observer читает и не мутирует | FR-767 |
| `backend/tests/test_sd_boundaries.py` | меню/границы и прежняя семантика доступа | новые observer/read-only и queue settings контракты; число notification kinds не увеличивается | FR-759 / FR-767 / FR-768 |
| `backend/tests/test_notify_catalog.py` | точный старый каталог видов | тот же каталог, расширенные получатели и идемпотентность без новых видов | FR-768 / NFR-739 |
| `backend/tests/test_notify_prefs.py` | старые строки предпочтений | прежние строки с режимом `can_view` для observer | FR-768 |
| `backend/tests/test_sd_audit.py` | старый точный набор кодов/полей | режим, observer, unavailable, distribution, rating, task link | FR-779 |
| `backend/tests/test_sd_reports.py` | «Оценка заявителей» пуста | среднее с одним знаком, число, «—», снимок `closed_at_snapshot` | FR-772 |
| `backend/tests/test_sd_reports_excel.py` | выгрузка без оценки | показатель и число оценок, без ПДн/темы/переписки | FR-772 |
| `backend/tests/test_sd_stand_restore.py` | сброс не знает новых моделей оценки/очереди | проверка только servicedesk reset и разделения tasks reset | FR-780 |
| deploy tests (`test_*_deploy.py`) | старые числа маршрутов/меню/регистраций | новые маршруты/части карточек, без изменений `config/cron.py` | FR-759 / FR-776 |
| menu tests (`test_org_permissions.py`, `test_tasks_core_changes.py`, `test_sd_boundaries.py`) | старый список пунктов | пункт очередей/связей в пределах существующих прав | FR-759 / FR-780 |
| `backend/tests/test_tasks_*.py` | у Task нет `ticket_number` и блока заявки | nullable indexed field, видимость по двум сервисам, exception только ответственному | FR-773 / FR-776 / FR-777 |

## Покрытие требований

| Требование | Задачи | Тесты |
|---|---|---|
| FR-759 | T-12001, T-12004, T-12103, T-12204, T-12219 | `test_sd_012_contract.py::test_rule_routes`, `test_sd_012_models.py::test_queue_rule`, `test_sd_012_distribution.py::test_rule_change_and_audit`, `test_t12_01` |
| FR-760 | T-12007, T-12103, T-12205 | `test_sd_012_distribution.py::test_create_priority`, `test_t12_01` |
| FR-761 | T-12007, T-12103, T-12204 | `test_sd_012_distribution.py::test_evenly`, `test_t12_01` |
| FR-762 | T-12007, T-12103, T-12204 | `test_sd_012_distribution.py::test_strictly`, `test_t12_01` |
| FR-763 | T-12012, T-12103, T-12204, T-12208 | `test_sd_012_distribution.py::test_all_notify`, `test_sd_012_notify_audit.py::test_all`, `test_t12_01` |
| FR-764 | T-12007, T-12103, T-12206, T-12207 | `test_sd_012_distribution.py::test_return_paths`, `test_t12_03` |
| FR-765 | T-12002, T-12003, T-12006, T-12102, T-12103, T-12202 | `test_sd_012_access.py::test_unavailable`, `test_sd_012_distribution.py::test_unavailable_skipped`, `test_t12_03` |
| FR-766 | T-12001, T-12004, T-12102, T-12219 | `test_sd_012_access.py::test_observer_manage`, `test_t12_02` |
| FR-767 | T-12006, T-12102, T-12201, T-12218 | `test_sd_012_access.py::test_observer_readonly`, `test_t12_02` |
| FR-768 | T-12012, T-12107, T-12208 | `test_sd_012_notify_audit.py::test_observer_notify`, `test_t12_02` |
| FR-769 | T-12008, T-12105, T-12210, T-12211 | `test_sd_012_rating.py::test_manual_close_sends`, `test_t12_04` |
| FR-770 | T-12001, T-12008, T-12105, T-12212 | `test_sd_012_rating.py::test_code_post`, `test_sd_012_rating.py::test_rate_limit`, `test_sd_012_rating.py::test_expired`, `test_t12_04` |
| FR-771 | T-12004, T-12105, T-12210 | `test_sd_012_rating.py::test_reopen`, `test_sd_012_models.py::test_rating_current`, `test_t12_04` |
| FR-772 | T-12013, T-12108, T-12213 | `test_sd_012_reports.py::test_rating_average`, `test_sd_012_reports.py::test_excel`, `test_t12_04` |
| FR-773 | T-12009, T-12106, T-12214, T-12215, T-12217 | `test_sd_012_tasks.py::test_button_and_rights`, `test_sd_012_tasks.py::test_direct_service_rejects_observer`, `test_t12_05` |
| FR-774 | T-12009, T-12106, T-12214, T-12217 | `test_sd_012_tasks.py::test_prefill`, `test_t12_05` |
| FR-775 | T-12009, T-12106, T-12215, T-12216 | `test_sd_012_tasks.py::test_assignee_exception`, `test_t12_05` |
| FR-776 | T-12005, T-12009, T-12106, T-12214, T-12217, T-12218, T-12223 | `test_sd_012_tasks.py::test_both_sides`, `test_sd_012_tasks.py::test_soft_delete`, `test_t12_05` |
| FR-777 | T-12006, T-12102, T-12106, T-12201, T-12217, T-12218 | `test_sd_012_tasks.py::test_visibility`, `test_sd_012_access.py::test_observer_no_task`, `test_t12_05` |
| FR-778 | T-12009, T-12106, T-12217 | `test_sd_012_tasks.py::test_no_reverse_sync`, `test_t12_05` |
| FR-779 | T-12001, T-12012, T-12107, T-12209, T-12308 | `test_sd_012_notify_audit.py::test_audit_events`, `test_t12_06` |
| FR-780 | T-12002, T-12006, T-12014, T-12015, T-12102, T-12112, T-12202, T-12219, T-12222, T-12223, T-12307 | `test_sd_012_access.py::test_queue_head_scope`, `test_sd_012_stand.py::test_reset`, `test_t12_06` |
| FR-781 | T-12001, T-12010, T-12011, T-12109, T-12110, T-12212, T-12221, T-12302 | `test_t12_07` |
| FR-782 | T-12011, T-12107, T-12110, T-12211, T-12212, T-12221, T-12302 | `test_sd_012_notify_audit.py::test_texts_moscow`, `test_t12_07` |
| NFR-736 | T-12007, T-12104, T-12204, T-12225 | `test_sd_012_concurrency.py::test_parallel_create`, `test_sd_012_concurrency.py::test_parallel_take` |
| NFR-737 | T-12018, T-12111, T-12225, T-12303 | `test_sd_012_performance.py::test_queue_card_p95` |
| NFR-738 | T-12008, T-12105, T-12111, T-12210, T-12304 | `test_sd_012_rating.py::test_rate_limit`, `test_sd_012_performance.py::test_rating_page`, `test_t12_04` |
| NFR-739 | T-12012, T-12107, T-12208, T-12308 | `test_sd_012_notify_audit.py::test_idempotent_new_overdue_rating`, `test_t12_02` |
| NFR-740 | T-12009, T-12106, T-12214, T-12217, T-12306 | `test_sd_012_tasks.py::test_fresh_status`, `test_sd_012_tasks.py::test_soft_delete`, `test_t12_05` |

## Решения по задачам

1. `assignee_authorized` не является общим обходом прав: его принимает только
   `tasks.services.task_links.create_from_ticket`, после повторной проверки `can_work`,
   `tasks.use`, заявки и активного ответственного. Любой другой исполнитель проходит обычную
   проверку `tasks.assign`; прямой `tasks.services.tasks.create` флаг не получает.
2. `servicedesk.services.task_links.task_seed` требует `can_work`, а не `can_view`; observer
   никогда не получает seed. `tasks.services.task_links` повторяет проверку, чтобы прямой POST
   не обошёл представление.
3. `token_hash` уникален на уровне БД; коллизия генерации повторяет вставку не более трёх раз,
   затем возвращает безопасную общую ошибку без раскрытия состояния токена.
4. Rate limit — не более пяти неверных кодов за 15 минут по паре IP+номер заявки; код не пишется
   в URL, журнал, события, seed или отчёт.
5. Рейтинг отчёта фильтруется по `closed_at_snapshot`, а не по текущему состоянию заявки;
   `is_current` исключает погашенные оценки после reopen, история остаётся в базе.
6. `servicedesk/stand.py` очищает только свои модели и ключи оценки; `tasks/stand.py` очищает
   Task и `ticket_number`; общий `e2e_reset_stand` очищает core availability. Нельзя удалять
   чужие таблицы из stand-reset приложения.
7. `config/cron.py` не изменяется. Автораспределение вызывается синхронно при создании/возврате,
   доступность вычисляется при обращении по дате, а фонового задания для среза нет.
8. Нагрузка и полный прогон выполняются только через `systemd-run --user` с сохраняемыми
   `status/log/exit`; в отчёт попадают только сводные результаты и `***` вместо секретов/ПДн.

## Риски

Гонка в evenly/strictly требует реального PostgreSQL concurrency-теста и проверки уникального
аудита. Разделение `can_view/can_work` может затронуть старые ожидания списка, поиска и меню;
поэтому изменения старых тестов изолированы и требуют разрешения. Исключение
`assignee_authorized` опасно при прямом вызове и закрывается двойной проверкой в обеих службах.
Оценка имеет внешний POST-контур: риск перебора закрывается энтропией Crockford-кода, hash,
CSRF, rate limit и короткой сессией. Отчёт может дрейфовать после передачи заявки; снимки и
`closed_at_snapshot` проверяются отдельными тестами. Параллельные stand-reset и нагрузка не
запускаются одновременно с миграциями или серверным прогоном.
