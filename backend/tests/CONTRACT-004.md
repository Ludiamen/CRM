# Контракт имён тестов Этапа 2 среза 004 (T-4101…T-4151)

Тесты написаны до кода и задают имена, которых нет в PLAN-004. Реализация (Этап 3) берёт их
отсюда. Имена плана (модели и поля раздела «Модель данных», маршруты «Контрактов», коды
событий таблицы «Журнал», очередь `notify`, право `notify.manage`, шина `apps/core/events.py` и
её события, две новые точки расширения `notification_kinds` и `top_bar_items`, задания
`send_delivery`, `notify_tick`, `notify_retention`, службы `worker-notify`, `notify-poller`,
`fakebots`, команды `notify_poll`, `notify_vapid_keys`, `e2e_notify_tick`) здесь не повторяются
и не меняются, кроме случаев, когда тест уточняет их форму (такие строки помечены
«уточнение»). Имена срезов 001-003 (`tests/CONTRACT.md`, `CONTRACT-002.md`, `CONTRACT-003.md`)
не меняются: что меняется в этих файлах вместе со срезом 004, перечислено в разделе 12
(перечень T-4138, п. 18). Значения, которых в плане, спеке и задачах нет, выбраны контрактом
и помечены «выбор контракта»; решения Opus по задачам называются «решение N задач», решения
Opus по вопросам этого контракта — «решение A1»…«решение E25» (раздел 16).

Помощники тестов: `tests/support_notify.py` (пишет T-4100, отдельной задачей после контракта;
фикстуры из него подключаются через `tests/conftest.py`, который правит та же задача) и
`tests/e2e/helpers_notify.py` (пишет T-4140). В колонке «Тесты» стоят задачи T-41xx или файлы,
которые берут имя. Рабочие записи автора контракта лежат вне репозитория.

Части этого файла: шапка и разделы 1-5 и подраздел «A» раздела 16 — часть a; разделы 6-7 —
часть b; разделы 8-12 — часть c; разделы 13-15 — часть d. Подразделы «B», «C», «D» раздела 16
дописывают свои части. Подраздел «E» — решения Opus по проверке контракта (партии K1-K5).

Правила для всех тестов среза:
- время (решение 3 задач): службы берут время из `django.utils.timezone.now()`; тесты тихих
  часов, срока письма и сводки ставят часы фикстурой `clock` (класс `Clock` из
  `tests/factories.py`: `.set(moment)`, `.advance(**kwargs)`); Valkey и RQ живут по
  настоящему времени, поэтому тесты, где участвует очередь, сдвигают отметки базы
  (`created_at`, `due_at`, `enqueued_at`, `lease_until`) прямой записью в поле;
- задания очереди `notify` (отправка, обход, сводка) и ночное удаление тест выполняет
  помощником синхронно, не дожидаясь рабочего процесса (раздел 7, помощник часть b);
- всё, что идёт «после фиксации» (обработчики шины, постановка заданий, рассылка в группы),
  проверяется внутри `with django_capture_on_commit_callbacks(execute=True):` (фикстура
  подключается параметром теста);
- имена кода среза 004 тесты импортируют внутри функций теста (или через `support.model`),
  а не на уровне модуля: сбор (`pytest --collect-only`) должен проходить до появления кода;
  `tests/support_notify.py` на уровне модуля тоже не импортирует `apps.notify`;
- Web Push в серверных тестах — подменённая отправка без сети (решение 5 задач): помощник
  подменяет точку транспорта `apps.integrations.webpush.client.transport` (раздел 5.3),
  перехватывает адрес, заголовки и тело, отдаёт заданный ответ; нагрузку тест расшифровывает
  тестовыми ключами браузера; флагов, ослабляющих проверку адреса подписки, нет;
- боты (решение 4 задач): модульные тесты получателей и раскладки идут на фальшивых
  адаптерах из `support_notify.py` (`fake_bot_send`, раздел 1.1); служба опроса, привязка, ответы ботов и коды ошибок — на
  учебной службе `fakebots` (раздел 1); живых ботов в автоматических тестах нет;
- соединение `/ws/notify/` (решение 6 задач): `asgiref.testing.ApplicationCommunicator`, тест
  ведёт его через `async_to_sync` из своего потока; `transaction=True` в проекте не работает;
  слой каналов — Valkey, база 15, её чистит фикстура `valkey_clean`; два медленных теста
  («соединение без сообщений живёт дольше 10 с», «100 одновременных подключений») — только
  в T-4122;
- секреты в тестовых данных (решение 23 задач): векторы RFC 8291, ключи и токены собираются
  в коде (`bytes.fromhex(...)`, генерация на месте), в именах переменных нет слов `secret`,
  `token`, `key`, `password`; токены ботов тестов — сгенерированные строки не по форме токена
  Telegram; в файлах, ответах и сообщениях об ошибках только `***`;
- подписчики `notify` (решение 24 задач): тесты прежних срезов с `bus_spy` и
  `execute=True` теперь запускают и подписчиков `notify`; их сбой шина пишет в лог и не
  роняет тест; тесты `notify` проверяют, что в журнале приложения нет ошибок подписчиков:
  `caplog`, логгер `apps.core.events`, нет записей уровня `ERROR`;
- пропусков нет, кроме двух живых тестов корня MAX в `test_max_trust.py` (T-4121,
  решение 8 задач): они пропускаются без выхода в интернет, на стенде выполняются;
- тесты ходят по путям плана (раздел «Контракты»), а не по именам маршрутов; модели берутся
  через `support.model("notify.Delivery")` и так далее;
- Playwright (T-4140…T-4151): Web Push проверяется только в кругах Chromium и Edge, тесты
  помечены для этих браузеров, а не пропускаются по условию (решение 8 задач).

Разделы:
1. Среда запуска.
2. Модели и поля.
3. Ядро: точки расширения, виды, события, `ws_state`, безопасность.
4. org и сервис-деск: `direct_members`, события, виды заявок.
5. Адаптеры: Telegram, MAX, Web Push, шаг опроса.
6. Сервисы `notify` — пишет часть b.
7. Задания RQ и ключи Valkey — пишет часть b.
8. Команды стенда — пишет часть c.
9. Журнал — пишет часть c.
10. Письма — пишет часть c.
11. Соединение `/ws/notify/` — пишет часть c.
12. Что меняется в прежних контрактах — пишет часть c.
13. Маршруты и поля форм — пишет часть d.
14. Зацепки разметки — пишет часть d.
15. Тексты — пишет часть d.
16. Вопросы к Opus (подразделы по частям: A, B, C, D).

## 1. Среда запуска

В колонке «Статус»: «есть» — уже сделано на Этапе 1 и описано по файлам (тест проверяет
факт); «Этап 3» — требование, которого в файлах ещё нет; «уточнение» — меняет прежний
контракт; «T-4100» — пишет помощник теста (отдельная задача после контракта).

### 1.1. Учебная служба ботов `fakebots`

| Что | Статус | Требование | Тесты |
|---|---|---|---|
| Служба `fakebots` | есть | в `deploy/docker-compose.yml`: образ `python:3.12-slim-bookworm`, `profiles: ["dev", "test"]`, `restart: unless-stopped`, команда `python -u /srv/server.py`, том `./fakebots:/srv:ro`, порт `127.0.0.1:8099:8099` (внутри сети compose — 8099; переменная окружения службы `FAKEBOTS_PORT`, по умолчанию 8099), проверка здоровья `python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8099/_test/health', timeout=3)"` раз в 5 с, 20 повторов; токенов в описании службы нет | T-4130 test_compose_fakebots_only_in_dev_and_test_profiles |
| Служба `test` и `fakebots` | есть | `depends_on` службы `test` содержит `fakebots` с `condition: service_healthy`; в `environment` службы `test`: `TELEGRAM_API_BASE: http://fakebots:8099` и `MAX_API_BASE: http://fakebots:8099/max` (значения из `deploy/docker-compose.yml`, не из `.env`); токенов ботов в compose нет | T-4130, T-4119, T-4120 |
| Токены ботов в тестах | T-4100 | токены тесту задаёт фикстура `bots_on` (выбор контракта): она ставит `settings.TELEGRAM_BOT_TOKEN` и `settings.MAX_BOT_TOKEN` сгенерированными строками вида `"t-" + secrets.token_hex(8)` (не по форме токена Telegram), берёт `settings.TELEGRAM_API_BASE` и `settings.MAX_API_BASE` из окружения службы `test`, включает каналы (`NotifySettings.telegram_enabled`, `max_enabled`) и перед тестом вызывает `/_test/reset`; тест не читает `deploy/.env` | T-4118…T-4121 |
| Клиент `fakebots` в тестах | T-4100 | `support_notify.FakeBots` (адрес из `settings.TELEGRAM_API_BASE` без пути, то есть `http://fakebots:8099`): `.health()`, `.put_telegram(event_or_list) -> list[int]`, `.put_max(event_or_list) -> int`, `.sent(channel) -> list[dict]`, `.fail(channel, status, *, method="*", count=1, retry_after=1)`, `.reset()` — каждый вызывает служебный адрес из таблицы 1.2. Только серверные тесты: приёмка (T-4140…T-4151) `support_notify` не импортирует (в её процессе нет настроек Django) — её клиент пишет T-4140 в `tests/e2e/helpers_notify.py` (имя выбирает T-4140) с теми же методами и адресом из `E2E_FAKEBOTS_URL` (по умолчанию `http://127.0.0.1:8099`; решение E23) | T-4118…T-4120; приёмка T-4145, T-4150 — через клиент `helpers_notify` |
| Включённый Web Push | T-4100 | фикстура `webpush_on` (решение E11): ставит `settings.VAPID_PRIVATE_KEY` и `settings.VAPID_PUBLIC_KEY` парой из `crypto.generate_vapid_keys()` (создаётся на месте, решение 23 задач), `settings.VAPID_SUBJECT = "mailto:noreply@example.test"`, `settings.WEBPUSH_ALLOWED_HOSTS` — значение по умолчанию (1.3), `NotifySettings.webpush_enabled = True`; подписку создаёт помощник `support_notify.subscribe(user, *, host="fcm.googleapis.com", path=None, keys=None) -> PushSubscription` через `push.save` с адресом `https://<host>/<path или случайная строка>` и ключами `browser_keys()` (или переданными `keys`); без `webpush_on` канал выключен (`settings.channel_on("webpush")` ложно) | T-4102, T-4109, T-4112, T-4115, T-4116, T-4125…T-4127 |
| Фальшивые адаптеры ботов | T-4100 | помощник `support_notify.fake_bot_send(channel, *, raises=None, message_id="1")` (решение E16) — контекстный менеджер: подменяет `apps.integrations.<channel>.client.send_message` записывающей функцией (`.calls` — список `(chat_id, text, button)`); при `raises` (экземпляр или класс `ChannelGone`, `RetryLater`, `BadRequest`, `BadToken`) поднимает его, иначе возвращает `message_id`; служба `delivery` зовёт клиентов через модуль (`telegram_client.send_message(...)`), поэтому подмена атрибута модуля работает; берут модульные тесты получателей, раскладки и итогов `send_delivery` (решение 4 задач), а служба опроса, привязка, ответы ботов и коды ответов — `fakebots` | T-4109, T-4112, T-4113, T-4122 |

### 1.2. Адреса `fakebots` (факт по `deploy/fakebots/server.py`, T-4005)

Токены принимаются любые непустые и нигде не запоминаются; в журнал службы токен не
пишется (в пути запроса он заменяется на `/bot***`). Тело запроса — JSON или
`application/x-www-form-urlencoded`; параметры Telegram берутся из адресной строки и тела
вместе. Ответ — JSON в UTF-8. В адресах ниже вместо знака запроса стоит слово «параметры».

| Адрес | Требование | Тесты |
|---|---|---|
| Telegram: `/bot<токен>/<метод>` | ответ `{"ok": true, "result": …}`; метод неизвестен — 404 `{"ok": false, "error_code": 404, "description": "Not Found"}`; тело не JSON — 400. `getMe` → `result` = `{"id": 7000001, "is_bot": true, "first_name": "Портал (стенд)", "username": "stand_notify_bot"}` | T-4119, T-4120 |
| Telegram `getUpdates` | параметры `offset`, `timeout` (не больше 50 с), `limit` (1…100, по умолчанию 100), `allowed_updates` (список или строка JSON); события с `update_id` ниже `offset` подтверждены и удаляются; ожидание до `timeout` секунд, пока нет подходящих событий; `result` — список событий с `update_id` | T-4120 test_telegram_poll_requests_use_offset_timeout_25_and_allowed_updates, test_telegram_offset_is_last_update_id_plus_1 |
| Telegram `sendMessage` | нужны `chat_id` и непустой `text`, иначе 400 `Bad Request: …`; служба запоминает `message_id` (с 1 по порядку), `chat_id`, `text`, `parse_mode`, `reply_markup`, `link_preview_options`, `time`; `result` — `{"message_id", "from", "chat": {"id", "type": "private"}, "date", "text"}` | T-4119 |
| Telegram `deleteWebhook` | `result: true`; вызовы службой не хранятся (тест проверяет их по запросам к адаптеру, раздел 5.1) | T-4120 test_delete_webhook_called_on_first_start_without_dropping_pending_updates |
| MAX: `GET /max/me` | `MAX_API_BASE` уже оканчивается на `/max`, адреса адаптера — `/me`, `/updates`, `/messages` после него; пустой или отсутствующий заголовок `Authorization` — 401 `{"code": "verify.token", "message": "No access token"}`; токен проверяется только на непустоту; ответ `{"user_id": 8000001, "name": "Портал (стенд)", "username": "stand_notify_bot"}` | T-4119, T-4120 |
| MAX: `GET /max/updates` | параметры `marker`, `timeout` (по умолчанию 30, не больше 90 с), `limit` (до 1000), `types` (через запятую); переданный `marker` подтверждает всё до него; ответ `{"updates": […], "marker": N}`, где `marker` — номер следующего события (у пустого ответа — текущий хвост) | T-4120 test_max_poll_requests_use_timeout_25_types_and_marker, test_max_marker_is_taken_from_previous_response |
| MAX: `POST /max/messages` | параметры `chat_id` или `user_id` (целые), иначе 400 `{"code": "proto.payload", …}`; тело `text`, `format`, `attachments`, `notify`; служба запоминает `message_id` (`"mid.N"`), `chat_id`, `user_id`, `text`, `format`, `attachments`, `notify`, `disable_link_preview`, `time`; ответ `{"message": {"sender", "recipient": {"chat_id", "chat_type": "dialog", "user_id"}, "timestamp", "body": {"mid", "seq", "text", "attachments"}}}` | T-4119 |
| Служебный `GET /_test/health` | 200 `{"ok": true}` | T-4130, T-4131 |
| Служебный `POST /_test/telegram/updates` | тело — одно событие (объект), список или объект с ключом `updates`; служба ставит каждому `update_id` по порядку с 1; ответ `{"ok": true, "update_ids": [...]}`; иначе 400 | T-4118, T-4120 |
| Служебный `POST /_test/max/updates` | тело — как у Telegram; служба добавляет `timestamp` (мс), если его нет; ответ `{"ok": true, "marker": N}` (номер следующего события) | T-4118, T-4120 |
| Служебный `GET /_test/sent` | параметр `channel` (`telegram` или `max`, иначе 400); ответ `{"ok": true, "messages": [...]}` — все сообщения канала по порядку отправки, ключи — как запоминает `sendMessage` (строки выше) | T-4119, T-4120, T-4145 |
| Служебный `POST /_test/fail` | тело `{"channel": "telegram"/"max", "status": 401, 403, 409, 429 или 500, "method": имя метода или "*" (по умолчанию "*"), "count": сколько запросов (по умолчанию 1), "retry_after": секунды (по умолчанию 1)}`; следующие `count` запросов к методу получают ошибку; имена методов — `getMe`, `getUpdates`, `sendMessage`, `deleteWebhook` и `me`, `updates`, `messages`; тело ошибки Telegram — `{"ok": false, "error_code": N, "description": …}`, у 429 ещё `parameters.retry_after` и заголовок `Retry-After`; тело ошибки MAX — `{"code": …, "message": …}`, у 429 заголовок `Retry-After`; другое `status` — 400 | T-4119, T-4120, T-4150 |
| Служебный `POST /_test/reset` | очищает события, отправленные сообщения, заказанные сбои и счётчики; ответ `{"ok": true}` | T-4100 (фикстура), T-4131 test_stand_reset_of_notify_resets_fakebots |
| Форма входящих событий | Telegram: `{"message": {"chat": {"id": число, "type": "private"/"group"/"supergroup"/"channel"}, "from": {"id": число}, "text": строка}}` и `{"my_chat_member": {"chat": {...}, "new_chat_member": {"status": "kicked"/"member"}}}`; MAX: `{"update_type": "bot_started", "chat_id": число, "user": {"user_id": число}}`, `{"update_type": "bot_stopped", "chat_id": число, "user": {"user_id": число}}`, `{"update_type": "message_created", "message": {"sender": {"user_id": число}, "recipient": {"chat_id": число, "chat_type": "dialog"/"chat"/"channel"}, "body": {"text": строка}}}`; формы собраны по F3 Ф3, Ф6, Ф11, Ф14; значения `kicked` и `chat_type` сверяются на настоящих ботах в T-4307 | T-4118, T-4120, T-4145 |

### 1.3. Развёртывание, настройки и файлы

| Что | Статус | Требование | Тесты |
|---|---|---|---|
| Служба `worker-notify` | Этап 3 | образ `crm-portal:local`, `env_file: .env`, `restart: unless-stopped`, `environment: DATABASE_MIGRATE_URL: ""`, команда начинается `rq worker -c config.rq_settings` и оканчивается именем очереди `notify` (ключ `--with-scheduler` тест не проверяет), `deploy: replicas: 2`, без `container_name`, без `profiles`, без тома `protected` (решение 24 задач), `depends_on` содержит `web` и `valkey` с `condition: service_healthy` | T-4130 test_compose_has_worker_notify_on_queue_notify_with_two_replicas, test_compose_notify_services_follow_worker_pattern_env_file_restart_healthy_dependencies_no_profile |
| Служба `notify-poller` | Этап 3 | те же образ, `env_file`, `restart`, `DATABASE_MIGRATE_URL: ""`, `depends_on`, без `profiles` и `container_name`; команда `python manage.py notify_poll`; ровно одна копия: ключа `deploy.replicas` нет или он равен 1 (тест принимает оба; второй опрашивающий получает от Telegram 409) | T-4130 test_compose_has_notify_poller_single_replica_with_notify_poll_command |
| Входящий доступ ботов | Этап 3 | веб-крючков нет: в `apps/notify/urls.py` и `config/urls.py` нет маршрута для приёма событий ботов, у `worker-notify` и `notify-poller` нет `ports` (порт `fakebots` — `127.0.0.1:8099`, только профили `dev` и `test`, раздел 1.1) | T-4130 test_bots_are_polled_no_webhook_route_or_inbound_port |
| `CHANNEL_LAYERS` | есть | `config/settings.py`: `{"default": {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [{"address": VALKEY_URL, "socket_timeout": 30, "max_connections": 300, "socket_connect_timeout": 2}], "prefix": "crm-asgi"}}}`; в тестах `VALKEY_URL` оканчивается на `/15` | T-4130 test_channel_layers_use_valkey_with_socket_timeout_30_max_connections_300_connect_timeout_2_and_prefix, T-4122 |
| `INSTALLED_APPS` | есть | `apps.notify` — последний элемент, после `apps.servicedesk` | T-4130 test_notify_is_last_in_installed_apps |
| `config/asgi.py` | есть | `ProtocolTypeRouter` с ключами `http` (приложение Django) и `websocket` (`AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(notify.routing.websocket_urlpatterns)))`); имя списка маршрутов — `websocket_urlpatterns` | T-4130 test_asgi_has_protocol_type_router_origin_validator_and_session_auth |
| Очередь `notify` | есть | `RQ_QUEUES["notify"] == {"URL": VALKEY_URL, "DEFAULT_TIMEOUT": 120}`; задания находятся в очереди так: `[j for j in django_rq.get_queue("notify").jobs if j.func_name == "apps.notify.tasks.send_delivery"]` | T-4130 test_rq_queues_include_notify |
| Задание `notify_tick` | Этап 3 | `config/cron.py`: `register(...)` с `name="notify_tick"`, функция `apps.notify.tasks.notify_tick`, очередь `notify`, `interval=30` (секунд, без строки `cron`), `job_timeout=120` | T-4130 test_cron_notify_tick_interval_30_queue_notify_timeout_120 |
| Задание `notify_retention` | Этап 3 | `name="notify_retention"`, функция `apps.notify.tasks.notify_retention`, очередь `maintenance`, `cron="40 23 * * *"` (UTC; 02:40 по Москве), `job_timeout=600` | T-4130 test_cron_notify_retention_at_23_40_utc_queue_maintenance_timeout_600 |
| Число заданий `config/cron.py` | Этап 3, уточнение | всего 16: прежние 14 (срезы 001-003) не меняются, два новых — выше; таблица `NOTIFY_JOBS` в `test_sd_deploy.py` (правка T-4138, п. 12) | T-4130, T-4138 |
| nginx | Этап 3 | в `nginx.conf` и `nginx.prod.conf` — `location /ws/` с повторёнными `proxy_pass`, `proxy_http_version 1.1`, `Upgrade`, `Connection`, `proxy_set_header` из `location /` (не наследуются), `proxy_read_timeout 3600s`, `proxy_send_timeout 3600s`, `proxy_buffering off` | T-4130 test_dev_nginx_has_location_ws_with_upgrade_timeouts_3600_and_buffering_off, test_prod_nginx_has_location_ws_with_upgrade_timeouts_3600_and_buffering_off |
| CSP | Этап 3 | в политику добавляется `worker-src 'self'`; `connect-src 'self'` остаётся | T-4130 test_csp_has_worker_src_self |
| Зависимости | есть | `backend/requirements.txt`: `channels==4.3.2`, `channels-redis==4.3.0`, `websockets==17.2`, `msgpack==1.2.3`, `asgiref==3.12.1`; `requirements-dev.txt`: `websocket-client==1.9.2` | T-4130 test_requirements_pin_new_dependencies_to_exact_versions, test_requirements_dev_pin_websocket_client |
| Переменные окружения (восемь) | есть | `config/settings.py` читает при запуске, всё через `django-environ`: `TELEGRAM_BOT_TOKEN` (str, `""`), `MAX_BOT_TOKEN` (`""`), `VAPID_PRIVATE_KEY` (`""`; 32 байта, base64url), `VAPID_PUBLIC_KEY` (`""`; 65 байт, base64url), `VAPID_SUBJECT` (`""`), `TELEGRAM_API_BASE` (`https://api.telegram.org`), `MAX_API_BASE` (`https://platform-api2.max.ru`), `WEBPUSH_ALLOWED_HOSTS` (список; по умолчанию `["fcm.googleapis.com", "jmt17.google.com", "*.notify.windows.com", "updates.push.services.mozilla.com"]`); службы читают `settings` при каждом вызове, а не при импорте, поэтому тесты подменяют их фикстурой `settings` | T-4130 test_settings_declare_bot_and_vapid_variables_with_empty_defaults, test_settings_api_base_and_webpush_hosts_have_documented_defaults, test_webpush_allowed_hosts_default_is_four_checked_push_services |
| `deploy/.env.example` | есть, уточнение | три секрета (`TELEGRAM_BOT_TOKEN`, `MAX_BOT_TOKEN`, `VAPID_PRIVATE_KEY`) — действующие строки `ИМЯ=` с пустым значением (заглушка `***` сошла бы за «ключ задан»); остальные пять — закомментированные строки `# ИМЯ=значение` (выбор контракта; так в файле сейчас) | T-4130 test_env_example_lists_new_variables_with_secrets_empty; правка test_stack::test_env_example_has_only_placeholders (T-4138, п. 16) |
| Список секретов `test_stack.py` | Этап 3, уточнение | `SECRET_ENV_NAMES` дополняется тремя именами выше (T-4138, п. 16) | T-4130 test_secret_variables_are_in_secrets_list_of_stack_test |
| Значения стенда | Этап 3 (решение 21 задач) | `tools/make_dev_env.py` для имён из таблицы `СТЕНД` считает пустое значение незаданным; ставит `TELEGRAM_API_BASE=http://fakebots:8099`, `MAX_API_BASE=http://fakebots:8099/max`, токены ботов — сгенерированные строки не по форме токена Telegram; пару VAPID стенда создаёт Opus командой `notify_vapid_keys` и дописывает в `deploy/.env`, значения в отчёты не попадают | T-4138 п. 15; `tools/test_make_dev_env.py` |
| Корень MAX | есть, уточнение | файл `backend/apps/integrations/max/certs/russian_trusted_root_ca.crt` (**`.crt`, а не `.pem`**: решение владельца 2026-10-10, `SOURCE.md` рядом; план и задачи называют `.pem`, потому что `test_deploy_files.py` считает закрытым ключом любой `.pem` вне `deploy/certs/`); файл — один сертификат PEM; срок действия до 2032-02-27 21:04:15 UTC (`notAfter`; тест сравнивает дату в UTC — по Москве это уже 28 февраля); константа контракта `ROOT_CA_SHA256 = "D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31"` — отпечаток SHA-256 сертификата в DER-форме (так его публикует Минцифры и показывает `ssl.PEM_cert_to_DER_cert`), а не хеш самого файла; тест считает `hashlib.sha256(ssl.PEM_cert_to_DER_cert(текст_файла)).hexdigest()` и сравнивает с константой без двоеточий в нижнем регистре | T-4121 test_root_file_sha256_equals_pinned_value, test_root_file_is_single_certificate_valid_until_2032_02_27, test_root_file_lies_in_max_adapter_certs_directory |
| `htmx-ext-ws` | есть (файл, лицензия, `VERSIONS.md`, `_assets.html`); Этап 3 (ключ в `verify_vendor.py`) | файл `backend/static/vendor/htmx-ext-ws-2.0.4.min.js`, рядом `LICENSE-htmx-ext-ws` (0BSD), запись с sha256 в `static/vendor/VERSIONS.md`, строка `<script src="{% static 'vendor/htmx-ext-ws-2.0.4.min.js' %}" defer></script>` в `templates/_assets.html` после `htmx-2.0.11.min.js`; ключа `htmx-ext-ws` в таблице `ПАКЕТЫ` файла `tools/verify_vendor.py` сейчас нет — его добавляет T-4138, пп. 13-14 | T-4130 test_new_dependencies_have_open_licenses_in_components_table (решение E19: «таблица компонентов» — метаданные установленных `channels`, `channels-redis`, `msgpack`, `asgiref`, `websockets`, `websocket-client` через `importlib.metadata` с теми же признаками открытой лицензии, что у `test_stack.py::test_requirements_pinned_and_licensed`, файл `static/vendor/LICENSE-htmx-ext-ws` (0BSD) и запись `htmx-ext-ws` в `static/vendor/VERSIONS.md`; документ плана тест не разбирает); T-4138 |
| `deploy/RESTORE.md` | Этап 3 | в шагах остановки и запуска названы `worker-notify` и `notify-poller` (рядом с `worker-inbox`) | T-4130 test_restore_guide_names_worker_notify_and_notify_poller_in_stop_and_start_steps |
| Команда `notify_vapid_keys` | Этап 3 | `manage.py notify_vapid_keys` печатает в stdout ровно две строки `VAPID_PRIVATE_KEY=<base64url 32 байта>` и `VAPID_PUBLIC_KEY=<base64url 65 байт>`; ничего не пишет в базу и в журнал (подробности формата — раздел 8) | T-4130 test_vapid_keys_command_prints_pair_for_env, test_vapid_keys_command_writes_nothing_to_journal_or_database |

## 2. Модели и поля

Метка приложения — `notify`; таблицы называются по умолчанию (`notify_notification`,
`notify_delivery`, …). Внешние ключи на `core.User` и `core.KnownDevice` объявлены с
`related_name="+"` (обратных связей к ядру нет), поэтому тесты ищут
`Notification.objects.filter(user=user)`, а не `user.<имя>_set`; связи внутри `notify`
называются так: `Delivery.notification` — `related_name="deliveries"`, `Delivery.digest` —
`related_name="deliveries"`. Значения `choices` тест сравнивает как строки; в модели они
объявлены вложенными `TextChoices` с теми же значениями. Отказ базы в ограничении тест ловит
как `django.db.IntegrityError` внутри `with transaction.atomic():`; отказ сервиса — раздел 6.
Время — `DateTimeField` с поясом; «пусто» — `null=True`.

### 2.1. Каналы, состояния, причины

| Имя | Что | Тесты |
|---|---|---|
| Каналы каталога и таблицы сотрудника (уточнение формы) | постоянный кортеж `kinds.CHANNELS == ("portal", "email", "push", "telegram", "max")` в этом порядке; такие коды стоят в `NotificationKind.default_channels`, `NotifySettings.defaults`, `UserNotifySettings.matrix` (кроме `portal`, см. ниже) | T-4101 test_channels_are_exactly_portal_email_push_telegram_max_in_order |
| Каналы доставки (уточнение формы) | `Delivery.Channel`: `email`, `webpush`, `telegram`, `max`; у доставки нет канала `portal` (запись и есть канал) и нет `push` | T-4109, T-4113 |
| Связь `push` и `webpush` | столбец `push` таблицы — один; он включает и системное уведомление во вкладке (рассылка в группу, доставки нет), и Web Push: ячейка `push` у вида создаёт `Delivery(channel="webpush")`; остальные каналы `email`, `telegram`, `max` совпадают по имени; код `portal` в `matrix` и `defaults` не хранится (выбор контракта): портал включён всегда и `prefs.effective` добавляет его сам; сервис записи отбрасывает `portal` из списка | T-4101, T-4102, T-4109 |
| `Delivery.State` | `waiting`, `sending`, `held`, `sent`, `failed`, `skipped`, `digested` | T-4109…T-4113 |
| `UserNotifySettings.QuietMode` | `calendar` («По рабочему календарю компании»), `own` («Свои часы»), `none` («Без тихих часов») | T-4110, T-4125 |
| `ChatBinding.Channel`, `BindCode.Channel`, `BotChat.Channel`, `BotState.Channel` | `telegram`, `max` | T-4118, T-4120 |
| Коды `Delivery.reason`, состояние `skipped` | `user_blocked` (учётная запись заблокирована), `user_dismissed` (уволен), `channel_disabled` (канал выключен администратором или токен не задан), `channel_off` (у вида канал уже выключен; письмо), `not_bound` (нет привязки Telegram или MAX), `no_subscriptions` (у сотрудника нет подписок Web Push), `tab_open` (вкладка открыта, FR-331), `read` (уведомление уже прочитано), `not_relevant` (`still_relevant` ложь) — состав закрыт, код — латиница, строчные, `_` | T-4109, T-4111…T-4113, T-4116, T-4119, T-4128 |
| Коды `Delivery.reason`, состояние `failed` | `expired` (следующий повтор вышел бы за 24 часа от создания), `bad_request` (неповторяемый ответ: у Web Push — 400, 413 и любой 4xx, кроме 401, 403, 404, 410, 429, решение B5; у ботов — `BadRequest`, 5.1), `channel_unbound` (канал отвязан), `no_subscriptions` (все подписки отвечали 404 или 410), `redirect` (ответ 3xx push-сервиса); письмо, не доставленное почтовым модулем, состояние доставки не меняет (решение A5) | T-4113, T-4116, T-4119 |
| `reason` у `waiting`, `sent`, `held`, `digested`, `sending` | пустая строка `""` | T-4113 |

### 2.2. Модели

| Модель | Поля и значения по умолчанию | Ограничения и как тест узнаёт отказ | Тесты |
|---|---|---|---|
| `NotifySettings` | `webpush_enabled`, `telegram_enabled`, `max_enabled` (`BooleanField`, `False`); `email_delay_minutes` (`PositiveSmallIntegerField`, 15; границы сервиса 5-120); `retention_days` (`PositiveSmallIntegerField`, 90; 30-365); `defaults` (`JSONField`, `dict`, `{}`); `channel_status` (`JSONField`, `dict`, `{}`); `updated_at` (`auto_now`) | одна строка `pk=1`: создаёт миграция данных; второй строки модель не запрещает, сервис всегда берёт `pk=1` (`settings.get()`); границы проверяет сервис `settings.update`, а не база | T-4127, T-4129, T-4130 |
| `NotifySettings.defaults` | `{"<код вида>": ["email", "push", "telegram", "max"], …}` — значения: подсписок кодов из `email`, `push`, `telegram`, `max` в порядке каталога без повторов; вида нет в словаре — действуют `default_channels` вида (без `portal`); пустой список означает «все внешние каналы выключены» | T-4102, T-4127 |
| `NotifySettings.channel_status` | `{"<канал>": {"at": "<ISO-8601 со смещением>", "code": "<код>"}}`; ключи канала — `webpush`, `telegram`, `max`; коды — `bad_token` (ответ 401 бота — токен не принят; у Web Push ответ 401 или 403 — подпись VAPID не принята, решение B5), `unavailable` (5xx, сеть, таймаут), `rate_limited` (429); в записи нет текста ответа, адресов и токенов; запись канала очищается после удачной отправки в канал; удачный шаг опроса бота очищает только запись с кодом `bad_token`; опрос пишет только `bad_token` (решения A3, E4) | T-4119 test_401_writes_token_not_accepted_with_time_to_channel_status, T-4127 |
| `UserNotifySettings` | `user` (`OneToOneField(core.User, on_delete=CASCADE, related_name="+")`); `matrix` (`JSONField`, `dict`, `{}`: пусто, пока сотрудник не сохранял ячейки, тогда действуют `defaults`); `quiet_mode` (по умолчанию `calendar`); `own_days` (`JSONField`, список целых 0-6 по возрастанию без повторов; по умолчанию `[]`; **день 0 — понедельник**, как `WorkCalendar.work_weekdays` среза 002); `own_start`, `own_end` (`TimeField`, `null=True`, по умолчанию пусто; сервис не даёт сохранить `own` без дней и времени); `digest_due_at` (`DateTimeField`, `null=True`) | уникальность `user` (`IntegrityError`); частичный индекс `notify_usettings_digest_due` на `digest_due_at` с условием «не пусто» | T-4110, T-4112, T-4125, T-4128 |
| `UserNotifySettings.matrix` | `{"<код вида>": ["email", "push", "telegram", "max"], …}`, значения — как у `defaults`; виды `mandatory` в `matrix` не записываются | T-4102, T-4125 |
| `Notification` | `user` (`ForeignKey(core.User, CASCADE, related_name="+")`); `kind` (`CharField(64)`); `text` (`CharField(300)`); `url` (`CharField(300)`, путь внутри портала); `object_ref` (`CharField(64, blank=True)`, по умолчанию `""`); `created_at` (`DateTimeField`, по умолчанию `timezone.now`, не `auto_now_add`: тест задаёт время при создании); `read_at` (`null=True`) | индексы с именами: `notify_notif_user_created` (`user`, `-created_at`), `notify_notif_unread` (`user`, условие `read_at` пусто), `notify_notif_obj_unread` (`user`, `object_ref`, условие `read_at` пусто), `notify_notif_created` (`created_at`); тест читает их из `Notification._meta.indexes` (имя и условие) | T-4101, T-4123, T-4124, T-4128 |
| `Digest` | `user` (`ForeignKey`, CASCADE, `related_name="+"`); `created_at` (по умолчанию `timezone.now`); `count_email`, `count_message` (`PositiveIntegerField`, 0); `notification_ids` (`JSONField`, список целых, `[]`) | индекс `notify_digest_user_created` (`user`, `created_at`) | T-4112, T-4128 |
| `Delivery` | `notification` (`ForeignKey(Notification, CASCADE, null=True, related_name="deliveries")`); `digest` (`ForeignKey(Digest, CASCADE, null=True, related_name="deliveries")`); `channel`; `state` (по умолчанию `waiting`); `due_at` (`null=True`: у `held` срока нет); `enqueued_at` (`null=True`); `lease_until` (`null=True`); `attempts` (`PositiveSmallIntegerField`, 0); `log` (`JSONField`, список, `[]`); `mail_id` (`PositiveIntegerField(null=True)`: номер письма почтового модуля, не внешний ключ); `reason` (`CharField(32, blank=True)`, `""`). «Создание» доставки для срока 24 часа — `notification.created_at` или `digest.created_at` | `UniqueConstraint` `notify_delivery_notif_channel` (`notification`, `channel`) и `notify_delivery_digest_channel` (`digest`, `channel`); `CheckConstraint` `notify_delivery_one_target`: ровно одно из `notification`, `digest` не пусто; частичные индексы `notify_delivery_waiting_due` (`due_at`, условие `state = waiting`) и `notify_delivery_sending_lease` (`lease_until`, условие `state = sending`); любой отказ — `IntegrityError` | T-4109, T-4112, T-4113, T-4128 |
| `Delivery.log` | список записей по порядку попыток; запись — словарь с ключами `at` (строка ISO-8601 со смещением, время попытки), `outcome` (`ok`, `retry`, `failed`, `gone`, `skipped`), `code` (целое — код ответа, либо `null` для сети и таймаута), `reason` (короткий код: `""`, `timeout`, `network`, `server_error`, `rate_limited`, `redirect`, `bad_request`, `bad_token`, `gone`, `channel_unbound`), у Web Push ещё `sub` (номер `PushSubscription`, без адреса); в записи нет адресов, токенов, текстов уведомлений и ключей браузера; результат по каждой подписке Web Push — отдельная запись, итоговой записи попытки у Web Push нет (решение E17); удача подписки — `outcome="ok"` с её `sub` | T-4113 test_each_attempt_written_to_log_with_time_and_outcome_without_addresses_and_tokens, T-4116, T-4119 |
| `PushSubscription` | `user` (`ForeignKey`, CASCADE, `related_name="+"`); `endpoint` (`CharField(1000)`); `p256dh` (`CharField(128)`), `auth` (`CharField(64)`) — base64url как прислал браузер; `device` (`ForeignKey(core.KnownDevice, CASCADE, null=True, related_name="+")`); `browser`, `platform` (`CharField(100, blank=True)`); `created_at` (по умолчанию `timezone.now`); `last_ok_at` (`null=True`) | `UniqueConstraint` `notify_push_endpoint_unique` на `endpoint` (`IntegrityError` при создании второй строки напрямую; сервис `push.save` вместо этого переносит подписку на нового владельца, раздел 6); удаление `KnownDevice` удаляет подписку каскадом | T-4115, T-4116, T-4117 |
| `ChatBinding` | `user` (`ForeignKey`, CASCADE, `related_name="+"`); `channel` (`telegram`, `max`); `chat_id` (`CharField(64)`, строка); `bound_at` (по умолчанию `timezone.now`) | `UniqueConstraint` `notify_binding_chat_unique` (`channel`, `chat_id`) и `notify_binding_user_channel_unique` (`user`, `channel`) — `IntegrityError` | T-4118, T-4119, T-4128 |
| `BindCode` | `user` (`ForeignKey`, CASCADE, `related_name="+"`); `channel`; `code_hash` (`CharField(64)`: SHA-256 строки из восьми цифр в UTF-8, 64 символа шестнадцатеричной записи в нижнем регистре); `expires_at`; `used_at` (`null=True`); использованный и истёкший код удаляет ближайший обход (решение B4, 6.13) | `UniqueConstraint` `notify_bindcode_one_active` (`user`, `channel`, условие `used_at` пусто) — `IntegrityError`; индекс `notify_bindcode_channel_hash` (`channel`, `code_hash`) | T-4118 |
| `BotChat` | `channel`; `chat_id` (`CharField(64)`); `started_at` (`DateTimeField`, по умолчанию `timezone.now`: строка создаётся, когда диалог начат — `/start` в Telegram, `bot_started` в MAX); `bad_attempts` (`PositiveSmallIntegerField`, 0); `window_started_at` (`null=True`) | `UniqueConstraint` `notify_botchat_unique` (`channel`, `chat_id`); строки нет у чата без начатого диалога (ответ бота такому чату — решение A2, 6.14) | T-4118, T-4120, T-4128 |
| `BotState` | `channel` (`primary_key=True`, `telegram`/`max`); `cursor` (`CharField(64, blank=True)`: Telegram — последний обработанный `update_id` строкой (в запрос идёт `offset = int(cursor) + 1`, решение E6), MAX — `marker` строкой; пусто — курсора нет); `bot_username` (`CharField(64, blank=True)`); `updated_at` (`auto_now`); `last_error` (`CharField(32, blank=True)`: код без текста — `conflict` (409), `bad_token`, `unavailable`, `""`) | первичный ключ `channel`: вторая строка того же канала — `IntegrityError` | T-4120 |

### 2.3. Миграция данных и права

| Что | Требование | Тесты |
|---|---|---|
| Право `notify.manage` | миграция данных `notify` (по образцу `servicedesk/0003_initial_data.py`) создаёт право с названием «Настройка уведомлений» и выдаёт его роли «Администратор портала»; других ролей оно не получает; роли «Сотрудник» и «Руководитель» без права | T-4127, T-4138 пп. 3-5 |
| `PERMISSIONS_004` | в `tests/support_notify.py`: `PERMISSIONS_004 = ("notify.manage",)`; число прав после установки — 13: семь среза 001 (`PERMISSIONS`), три среза 002, два среза 003 и это; `TITLES_004 = {"notify.manage": "Настройка уведомлений"}`; там же `POINTS_004 = ("notification_kinds", "top_bar_items")` (T-4138 п. 1) | T-4138 пп. 3-5 |
| Строка `NotifySettings` | миграция создаёт `NotifySettings(pk=1, webpush_enabled=False, telegram_enabled=False, max_enabled=False, email_delay_minutes=15, retention_days=90, defaults={}, channel_status={})` | T-4127, T-4130 |
| Прочие таблицы после установки | пусты: нет уведомлений, доставок, подписок, привязок, кодов, сводок, `UserNotifySettings`, `BotChat`, `BotState` | T-4128 |
| Права роли приложения | новые таблицы получают полный набор прав через `ALTER DEFAULT PRIVILEGES`: ночное удаление и чистка кодов идут под `crm_app` без своих `GRANT` | T-4128 (ночное удаление под ролью `crm_app`) |

## 3. Ядро: точки расширения, виды, события, `ws_state`, безопасность

### 3.1. Точки расширения `apps/core/extensions.py`

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `POINTS` | уточнение CONTRACT-003 § 3.2: кортеж из пятнадцати имён в таком порядке (решение 19 задач): `menu_items`, `role_sources`, `role_usage`, `audit_labels`, `staff_directory`, `card_sections`, `day_marks`, `home_notices`, `stand_reset`, `unit_usage`, `file_purposes`, `mail_renderers`, `login_links`, `notification_kinds`, `top_bar_items`. `org` регистрируется только в первых девяти (в двух новых не регистрируется); `servicedesk` — в `notification_kinds` (одна функция) плюс прежние девять точек (`SERVICEDESK_POINTS` в `test_sd_boundaries.py`, CONTRACT-003 § 3.2); `notify` — в `menu_items`, `audit_labels`, `card_sections`, `stand_reset`, `mail_renderers`, `notification_kinds`, `top_bar_items`; ядро — в `notification_kinds` (одна функция, три вида безопасности); функции — обычные функции модулей `apps.<имя>…` (`func.__module__`) | T-4138 п. 1-2; T-4101 |
| `notification_kinds` | `func() -> list[NotificationKind]`: без параметров, зовётся при каждом вызове `kinds.catalog()`; возвращает свежие объекты (регистрации живут в памяти процесса); порядок возврата не важен — `kinds.catalog()` сортирует по `(order, порядок регистрации функций)` | T-4101 test_catalog_is_reassembled_from_extension_point_on_each_call, test_kind_registered_through_extension_point_appears_without_changing_notify_code |
| `top_bar_items` | `func() -> list[TopBarItem]`: без параметров; `context.shell` (`apps/core/context.py`) для вошедшего сотрудника без ограниченной сессии кладёт в контекст шаблона ключ `top_bar` — список словарей `{"key": str, "template": str, "context": dict}` в порядке `order` (при равенстве — порядок регистрации), где `context` — результат `TopBarItem.context(request)`; каждая функция точки и каждый `context` зовутся не больше одного раза за запрос; без регистраций `top_bar == []`, а шапка совпадает с шапкой после среза 003; на странице входа и при ограниченной сессии `top_bar` не кладётся (выбор контракта); `templates/base.html` выводит каждый элемент в блоке `top-actions` перед ссылками профиля подключая шаблон элемента и передавая ему контекст этого элемента | T-4131 test_without_notify_registrations_header_has_no_bell, T-4123 |
| `NotificationKind` | `@dataclass(frozen=True)` в `apps.core.extensions`, рядом с `MailRenderer`; поля по порядку: `code: str`, `title: str`, `module: str` (обязательные); `events: tuple[str, ...] = ()`; `build: Callable[[str, dict], list[Draft]]` (по умолчанию — функция, возвращающая `[]`); `external_text: str = ""`; `default_channels: tuple[str, ...] = ("portal",)`; `mandatory: bool = False`; `available: Callable[[User], bool]` (по умолчанию всегда `True`); `still_relevant: Callable[[int, str], bool]` (по умолчанию всегда `True`); `order: int = 0`. `build(event, data)` получает имя события и словарь его данных (ключи — раздел 3.2 и 4.2), `available(user)` — объект пользователя, `still_relevant(user_id, object_ref)` — номер сотрудника и `Notification.object_ref`. Каналы в `default_channels` — коды из `kinds.CHANNELS` (с `portal`); тесты передают кортежи | T-4101 test_kind_has_code_title_module_default_channels_mandatory_and_order |
| `Draft` | `@dataclass(frozen=True)` в `apps.core.extensions`: `user_id: int`, `text: str` (одна строка до 300 знаков), `url: str` (путь внутри портала), `object_ref: str = ""` | T-4101 test_build_returns_drafts_with_recipient_text_url_and_object_ref |
| `TopBarItem` | `@dataclass(frozen=True)` в `apps.core.extensions`: `key: str`, `order: int`, `template: str` (путь шаблона), `context: Callable[[HttpRequest], dict]` | T-4123, T-4131 |
| Сброс реестров | как в CONTRACT-003 § 3.2: `with extensions.empty():` (на время блока все пятнадцать реестров пусты, потом возвращаются; код обходит `POINTS`, поэтому две новые точки сбрасываются сами) или фикстура `no_extensions`; внутри блока `kinds.catalog() == []` (пустой список, не ошибка), `top_bar == []`; подписки шины фикстура `no_extensions` не снимает — тест берёт и `events.empty()` (фикстура `bus`); тестовый вид тест регистрирует внутри `extensions.empty()` помощником `support_notify.register_kind(kind)` (он вызывает `extensions.register("notification_kinds", lambda: [kind])` и подписывает `dispatch` на `kind.events`); каталог без сервис-деска (T-4101 test_catalog_without_servicedesk_registrations_has_core_and_notify_kinds_only) тест собирает внутри `extensions.empty()` двумя вызовами — `extensions.register("notification_kinds", apps.core.notify_kinds.notification_kinds)` и `extensions.register("notification_kinds", apps.notify.extensions.notification_kinds)` (решение E12; снять одну регистрацию нельзя, `unregister` нет) | T-4101, T-4109, T-4131 |
| Регистрация ядра | вид безопасности регистрирует `apps/core/notify_kinds.py` (функция `notification_kinds()`), вызов `extensions.register("notification_kinds", notify_kinds.notification_kinds)` стоит в `CoreConfig.ready()` | T-4101, T-4105 |
| Виды `notify` | `apps/notify/extensions.py` регистрирует функцию `notification_kinds()` с одним видом «Канал отвязан» (`notify.channel_unbound`, `events=()`, `mandatory=True`) | T-4101, T-4119 |

### 3.2. Каталог видов: коды, названия, порядок

`kinds.catalog() -> list[NotificationKind]` — сервис `notify` (подписи — раздел 6): собирает
виды всех функций точки, сортирует по `(order, порядок регистрации)`, отказывает при повторе
кода. Повтор кода — `django.core.exceptions.ImproperlyConfigured` (выбор контракта; тот же
отказ даёт `apps.get_app_config("notify").check_kinds()`, его в конце зовёт `ready()`, а сам он зовёт `kinds.check()`:
так повтор не заменяется молча, а останавливает запуск).

| Код | Название (`title`) | Модуль (`module`) | `order` | `mandatory` | `default_channels` | `events` | Тесты |
|---|---|---|---|---|---|---|---|
| `servicedesk.new_in_queue` | Новая заявка в моей очереди | Сервис-деск | 10 | `False` | `("portal", "email", "push", "telegram", "max")` | `servicedesk.ticket_created`, `servicedesk.ticket_transferred`, `servicedesk.ticket_reopened` | T-4101, T-4106 |
| `servicedesk.assigned` | Мне назначили заявку | Сервис-деск | 20 | `False` | все пять | `servicedesk.ticket_created`, `servicedesk.assignee_changed` | T-4101, T-4106 |
| `servicedesk.requester_replied` | Заявитель ответил | Сервис-деск | 30 | `False` | все пять | `servicedesk.reply_received` | T-4101, T-4107 |
| `servicedesk.reply_failed` | Ответ заявителю не ушёл | Сервис-деск | 40 | `False` | все пять | `servicedesk.reply_not_sent`, `servicedesk.mail_failed` | T-4101, T-4107 |
| `core.new_device` | Вход с нового устройства | Ядро | 110 | `True` | `("portal",)` | `core.new_device` | T-4101, T-4105 |
| `core.password_changed` | Пароль изменён | Ядро | 120 | `True` | `("portal",)` | `core.password_changed` | T-4101, T-4105 |
| `core.second_factor_reset` | Второй фактор сброшен | Ядро | 130 | `True` | `("portal",)` | `core.second_factor_reset` | T-4101, T-4105 |
| `notify.channel_unbound` | Канал отвязан | Уведомления | 200 | `True` | `("portal",)` | `()` | T-4101, T-4119 |

Числа `order` выбраны контрактом (в плане задан только порядок строк таблицы: четыре вида
сервис-деска, три вида безопасности, «Канал отвязан»). `external_text` видов сервис-деска —
дословно FR-317: «Новая заявка в вашей очереди», «Вам назначена заявка», «Заявитель ответил по
вашей заявке», «Ответ заявителю не ушёл» (в порядке таблицы); у видов `mandatory` —
пустая строка `""`. Заголовки, названия и модули тест сверяет со столбцами таблицы буквально.

### 3.3. События ядра (шина `apps/core/events.py`)

Подписчик получает `handler(**data)`; значения — как в CONTRACT-003 § 3.1 (подписи шины не
меняются). Имена и ключи данных ниже; других ключей нет. `user_id`, `actor_id`, `device_ids` —
целые номера.

| Событие | Данные | Кто и где публикует | Тесты |
|---|---|---|---|
| `core.new_device` | `user_id: int`, `browser: str`, `platform: str` (оба — `devices.parse_user_agent(user_agent)`), `at: datetime` (с поясом, `timezone.now()`) | `login.complete` внутри `transaction.atomic()` в том же условии, что `_mail_new_device` (`touched is not None and touched.is_new and known_before`), непосредственно перед вызовом `_mail_new_device`; для первого устройства, известного устройства и ограниченной сессии (`limited=True`, `touched is None`) не публикуется | T-4105 test_new_device_event_published_for_new_not_first_device_with_browser_platform_at, test_new_device_event_not_published_for_first_device, test_new_device_event_not_published_for_known_device, test_new_device_event_published_exactly_where_core_mail_is_sent |
| `core.password_changed` | `user_id`, `actor_id` | `passwords.change_password` (смена в профиле: `actor_id=user.pk`) и `passwords.reset_password` (восстановление по ссылке: `actor_id=user.pk`, как у записи журнала `password.changed`, где действующее лицо — сам сотрудник); публикуется рядом с `mail.send("password_changed", …)` | T-4105 test_password_changed_event_published_on_profile_change, test_password_changed_event_published_on_recovery |
| `core.second_factor_reset` | `user_id`, `actor_id` (`actor.pk`, `None`, если действие системы) | `accounts.reset_second_factor` в той же транзакции, где закрываются сессии и уходит письмо | T-4105 test_second_factor_reset_event_published_with_user_and_actor |
| `core.user_dismissed` | `user_id`, `actor_id` | `accounts.dismiss`; подписчик `notify` — `cleanup.on_dismissed(**data)` | T-4105 test_user_dismissed_event_published_with_user_and_actor, test_dismissed_event_removes_subscriptions_bindings_codes_and_settings_but_keeps_notification_records |
| `core.user_rehired` | `user_id`, `actor_id` | `accounts.rehire`; подписчик `notify` — `cleanup.on_rehired(**data)`: удаляет прежние уведомления сотрудника | T-4105 test_user_rehired_event_published_with_user_and_actor, test_rehired_event_deletes_former_notifications_of_employee |
| `core.logged_out` | `user_id`, `device_ids: list[int]` (номера `KnownDevice`; по возрастанию, без повторов, без пустых), `reason: str` (`"logout"` или `"logout_everywhere"`) | (1) `login.logout` — выход кнопкой: номер устройства читается из `UserSession` (внешний ключ `device`, значение `device_id`) **до** `sessions.end(request)`, потому что `end` удаляет запись; публикуется только когда пользователь вошёл; `reason="logout"`, `device_ids` — список из одного номера или `[]`, если у сессии нет устройства; (2) `sessions.logout_everywhere` — устройства остальных сессий (без текущей; те, у кого `device_id` не пусто) читаются **до** `close_all`, которое удаляет записи; `reason="logout_everywhere"`; событие публикуется и при пустом списке (выбор контракта); подписчик `notify` — `push.on_logged_out(**data)`. Не публикуется: истечение по бездействию (`SessionGuardMiddleware`), закрытие сессии в другом месте, смена пароля, сброс второго фактора, блокировка | T-4105 test_logout_button_publishes_logged_out_with_device_of_current_session, test_logout_everywhere_publishes_devices_of_other_sessions_without_current, test_logged_out_device_ids_exclude_sessions_without_device, test_no_logged_out_event_on_idle_expiry, test_no_logged_out_event_when_session_closed_elsewhere; T-4117 test_logged_out_event_carries_device_taken_before_session_end |
| События не публикуются | приглашение, ссылка восстановления пароля, блокировка и разблокировка — только письма ядра | T-4105 test_blocking_invitation_and_recovery_link_publish_no_notification_event |
| Письма ядра | не меняются: `new_device`, `password_changed`, `second_factor_reset` уходят теми же вызовами `mail.send` | T-4105 test_core_mails_new_device_password_and_second_factor_are_unchanged |

### 3.4. `sessions.ws_state` и проверка соединения

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `sessions.ws_state` | `ws_state(session, user) -> str` в `apps/core/services/sessions.py`. `session` — объект сессии Django (`SessionBase`, `scope["session"]` соединения; у него `.session_key` и `.get(...)`), не запрос. `user` — `scope["user"]` (пользователь или `AnonymousUser`). Проверки в таком порядке, по тем же правилам, что `SessionGuardMiddleware`: (1) `user` не вошёл — `"anonymous"`; (2) нет `session.session_key`, нет строки `UserSession` с этим ключом или строка принадлежит другому — `"session_missing"`; (3) бездействие истекло: `timezone.now() - row.last_activity` больше `session.get(IDLE_KEY)` минут (если ключа нет — `security_settings.get().idle_timeout_minutes`) — `"idle_expired"`; (4) `session.get(LIMITED_KEY)` истинно (вход без второго фактора не закончен) — `"limited"`; (5) `passwords.must_change(user, security_settings.get())` — `"password_expired"`; иначе `"ok"`. Набор значений закрыт. Функция только читает: `sessions.touch` не зовёт и не меняет строку `UserSession` (сообщения по соединению сессию не продлевают) | T-4122 test_connect_without_session_accepts_then_closes_with_4401, test_connect_with_foreign_session_closes_with_4401, test_connect_with_idle_expired_session_closes_with_4401, test_connect_without_second_factor_closes_with_4401, test_connect_with_expired_password_closes_with_4401, test_message_over_socket_does_not_extend_session_idle_time |
| Решение по значению | `"ok"` — соединение продолжается; любое другое значение — обработчик сначала принимает соединение (`accept`), затем закрывает его кодом 4401 (при проверке раз в 25 с — просто закрывает); смена пароля меняет ключ сессии: у старой сессии нет строки `UserSession` — значение `"session_missing"` на ближайшей проверке | T-4122 test_check_closes_socket_on_next_tick_after_password_change, test_check_every_25_seconds_closes_socket_after_logout |

### 3.5. Три вида безопасности ядра

Файл `apps/core/notify_kinds.py`; функция `notification_kinds() -> list[NotificationKind]`.
Создаётся только запись на портале: у видов `mandatory=True`, доставок нет, сводка не берёт
(FR-305). `external_text=""`, `available` и `still_relevant` — по умолчанию (`available` для
таблицы не нужна: виды `mandatory` в ней идут отдельной строкой).

| Код | `build(event, data)` → `[Draft(...)]` | Тесты |
|---|---|---|
| `core.new_device` | один `Draft(user_id=data["user_id"], text="Вход с нового устройства (<browser>, <ДД.ММ.ГГГГ ЧЧ:ММ>)", url="/me/security/", object_ref="")`; `<browser>` — `data["browser"]` как есть (его вычислил `devices.parse_user_agent`), время — `data["at"]`, переведённое в Europe/Moscow функцией `timezone.localtime` и записанное по шаблону `%d.%m.%Y %H:%M` (решение 17 задач; платформа в текст не входит); пример: «Вход с нового устройства (Chrome 126, 10.10.2026 14:05)» (`parse_user_agent` даёт семейство и старшую версию; приёмка сверяет браузер с тем, что `devices.parse_user_agent` вернул для её `User-Agent` — у безголового Chrome семейство может быть другим, — а не с буквальным «Chrome»; выбор контракта, решение E27) | T-4108 test_text_new_device_has_browser_and_time, test_new_device_time_is_europe_moscow |
| `core.password_changed` | один `Draft(user_id=data["user_id"], text="Пароль изменён", url="/me/security/", object_ref="")` | T-4108 test_text_password_changed |
| `core.second_factor_reset` | один `Draft(user_id=data["user_id"], text="Второй фактор сброшен", url="/me/security/", object_ref="")` | T-4108 test_text_second_factor_reset |

`Draft.url` у видов безопасности — `/me/security/` (решение A1; в плане адреса нет).
Получатель — `data["user_id"]` даже когда `actor_id` равен ему (смена пароля в профиле:
сотрудник видит запись о своём действии). Событие `core.second_factor_reset` создаёт запись в
момент сброса, а сотрудник увидит её на колокольчике после повторного входа. Тесты
«создаёт запись без доставок»: T-4105 test_security_events_create_portal_record_without_deliveries.

## 4. org и сервис-деск

### 4.1. `structure.direct_members`

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `structure.direct_members` | `direct_members(unit_id: int) -> list[PersonRef]` в `apps/org/services/structure.py`; `PersonRef` — как у `queue_people` (`id`, `full_name`, `position`, `apps/org/services/refs.py`). Один запрос к `Membership` узла `unit_id` (только сам узел, без вложенных и вышестоящих), с `select_related("user")`; в ответе: члены узла в состояниях `active` и `blocked` (заблокированные входят: запись на портале им создаётся); исключены состояния `dismissed` и `invited`; руководитель и заместитель этого узла входят своим членством; руководитель вышестоящего узла и держатель «Все заявки» без членства — не входят; порядок `(full_name, id)`; без повторов; несуществующий узел — `[]` | T-4106 test_direct_members_include_concurrent_head_and_deputy_of_queue_node, test_direct_members_exclude_upper_node_head_and_all_tickets_holder_without_membership; T-4107 test_blocked_employee_gets_portal_record_without_external_deliveries, test_invited_employee_who_never_logged_in_gets_no_record, test_dismissed_employee_gets_no_record |

### 4.2. События сервис-деска

Помощники `apps/servicedesk/services/events.py` получают новые поля **обязательными
именованными параметрами** (решение 20 задач): вызов без параметра — `TypeError`. Прежние ключи
данных (`number`, `queue_id`, `assignee_before_id`, `assignee_after_id`) остаются; новые поля
только добавляются. Параметр `actor_id` — `actor.pk` у действия сотрудника и `None`, если
действие системы или `actor` не передан. Константы имён событий — как сейчас, плюс новые:
`TICKET_TRANSFERRED = "servicedesk.ticket_transferred"`, `TICKET_REOPENED =
"servicedesk.ticket_reopened"`, `REPLY_NOT_SENT = "servicedesk.reply_not_sent"`,
`MAIL_FAILED = "servicedesk.mail_failed"`, `OBJECT_VIEWED = "object.viewed"`.

| Помощник | Ключи данных события и места публикации | Тесты |
|---|---|---|
| `ticket_created(ticket, *, actor_id, channel)` (уточнение) | `number`, `queue_id`, `assignee_before_id=None`, `assignee_after_id`, `actor_id`, `channel` (`"mail"`, `"form"`, `"staff"` — значение аргумента `channel` у `tickets.create`); `actor_id` — номер создателя-сотрудника (`created_by.pk`) при `channel="staff"`, иначе `None`; публикует `tickets.create` | T-4103 test_ticket_created_by_mail_has_channel_mail_and_no_actor, test_ticket_created_by_open_form_has_channel_form_and_no_actor, test_ticket_created_by_staff_has_channel_staff_and_creator_actor |
| `assignee_changed(ticket, *, before_id, after_id, actor_id)` (уточнение) | `number`, `queue_id`, `assignee_before_id`, `assignee_after_id`, `actor_id`; публикуют `assignment._set_assignee`, `assignment.clear_assignee`, `reconcile` (сверка: `actor_id=None`); «Взять себе» — `actor_id` равен `assignee_after_id`; групповое назначение — событие на каждую заявку; при создании ответственный по умолчанию или «Взять себе» отдельного события не даёт: он виден в `assignee_after_id` события `ticket_created` (`tickets.create` публикует только его); при смене категории ответственный по умолчанию — событие `assignee_changed` от `assignment.apply_default_assignee` (через `_set_assignee`) с `actor_id` действующего сотрудника, после `ticket_transferred` (решение E9; T-4103 test_default_assignee_on_create_and_on_category_change_carry_actor_of_the_action при создании проверяет `ticket_created`, при смене категории — `assignee_changed`) | T-4103 (шесть тестов `assignee_*`, `take_*`, `group_*`, `default_*`, `clear_*`, `reconcile_*`) |
| `reply_received(ticket, *, via, author_kind, entry_id)` (уточнение) | `number`, `queue_id`, `assignee_before_id`, `assignee_after_id` (оба — текущий ответственный), `actor_id=None` (задаётся помощником, не параметром), `via`, `author_kind`, `entry_id`; `via` — `"appended"` или `"reopened"`; `author_kind` — `"requester"`, если адрес автора письма совпадает с адресом заявителя заявки, иначе `"participant"`; `entry_id` — номер созданного элемента ленты `incoming`; публикует `tickets.add_incoming` | T-4103 test_reply_received_appended_from_requester_has_via_author_kind_and_entry_id, test_reply_received_from_copy_participant_has_author_kind_participant, test_reply_received_has_actor_none |
| `ticket_closed(ticket, *, actor_id)` (уточнение) | `number`, `queue_id`, `assignee_before_id`, `assignee_after_id`, `actor_id`; `closing.close` — `actor.pk`; автозакрытие (`closing.autoclose_one`) — `actor_id=None` (решение 16 задач) | T-4103 test_ticket_closed_by_employee_carries_actor_and_autoclose_has_actor_key; T-4138 пп. 8-10 |
| `ticket_transferred(ticket, *, from_queue_id, actor_id)` (новое) | `number`, `from_queue_id`, `to_queue_id` (= `ticket.queue_id` после переноса), `actor_id`, `assignee_after_id` (= `ticket.assignee_id` на момент публикации: после возможного снятия ответственного и до назначения ответственного по умолчанию при смене категории; `None`, если ответственного сняли или его не было); публикует `transfer._move` в самом конце, после `assignee_changed(after=None)` от `clear_assignee`, — и для `transfer`, и для `change_category` (решение E9; получателей вид считает по состоянию заявки в базе, 4.3) | T-4104 test_ticket_transferred_on_transfer_has_from_to_actor_and_assignee_after, test_ticket_transferred_on_category_change_has_from_to_and_assignee_after, test_ticket_transferred_assignee_after_is_none_when_assignee_cleared |
| `ticket_reopened(ticket, *, via, actor_id)` (новое) | `number`, `queue_id` (после возможного переноса в очередь по умолчанию), `via` (`"mail"` или `"manual"` — значение `via` у `closing.reopen`), `actor_id` (`None` при `via="mail"`), `assignee_id` (= `ticket.assignee_id` после возможного снятия); публикует `closing.reopen` — в самом конце, после снятия ответственного и переноса | T-4104 test_ticket_reopened_by_mail_has_via_mail_and_queue_and_assignee, test_ticket_reopened_manually_has_via_manual_and_actor, test_ticket_reopened_published_after_assignee_cleared_and_move_to_default_queue |
| `reply_not_sent(ticket, *, entry_id, reason, author_id)` (новое) | `number`, `entry_id`, `reason` (`"quarantine"`, `"encrypted"`, `"ticket_closed"`), `author_id` (автор ответа), `actor_id=None` (задаётся помощником); публикует `replies._not_sent` | T-4104 test_reply_not_sent_for_quarantine_has_reason_author_entry_and_no_actor, …_encrypted_archive_…, …_closed_ticket_… |
| `mail_failed(ticket, *, mail_kind, entry_id)` (новое) | `number`, `mail_kind` (`"confirmation"`, `"assigned"`, `"reply"`, `"closed"`, `"reopened"`, `"autoclosed"`), `entry_id` (`int` или `None`, когда у письма нет элемента ленты), `actor_id=None` (задаётся помощником); публикует `replies.on_mail_failed` в конце, после записи события ленты; вид письма берётся из имени шаблона письма | T-4104 test_mail_failed_published_for_each_mail_kind_with_no_actor, test_mail_failed_has_entry_id_none_when_mail_has_no_timeline_entry |
| `object_viewed(user, ticket)` (новое) | событие `object.viewed`, данные `object_ref: str` (`f"servicedesk.ticket:{ticket.pk}"`) и `user_id: int`; публикует GET-представление `ticket_card` (`apps/servicedesk/views/ticket_card.py`) один раз на успешный GET — и для слайдера, и для страницы целиком; не публикуется для чужой и несуществующей заявки (404) и при POST-действиях карточки | T-4104 test_object_viewed_published_on_get_of_ticket_slider_and_page, test_object_viewed_not_published_on_post_actions_of_ticket; T-4124 |
| Порядок при открытии письмом | `intake`: `closing.reopen(via="mail")`, затем `tickets.add_incoming(via="reopened")`; подписчики вызываются в порядке публикации: `servicedesk.ticket_reopened`, затем `servicedesk.reply_received(via="reopened")` | T-4104 test_mail_reopen_publishes_ticket_reopened_before_reply_received; T-4107 |
| Прежние поля | все прежние ключи сохраняются | T-4103 test_old_event_fields_are_kept_after_adding_new_ones |

`tickets.add_incoming(ticket, *, author_email, author_name="", text, at=None, inbound_id=None,
cc=(), via="appended") -> TicketEntry` (уточнение формы): новый необязательный параметр `via`
со значениями `"appended"` (по умолчанию) и `"reopened"`; другое значение — `ValueError`
(выбор контракта). `intake` передаёт `via="reopened"` после `closing.reopen`. Тесты:
T-4103 test_add_incoming_via_parameter_defaults_to_appended.

Ссылки на заявку не смешиваются: `Notification.url` — путь `/tickets/<номер>/` (по номеру
заявки `number`); `Notification.object_ref` и данные `object.viewed` — `servicedesk.ticket:<pk>`
(по первичному ключу `Ticket.pk`); `related_ref` письма заявки почтового модуля — `ticket:<pk>`
(тоже первичный ключ, как в срезе 003: `letters.py` ставит `f"ticket:{ticket.pk}"`,
`replies.on_mail_failed` ищет `Ticket` по `pk` и берёт `number` для события; решение E8).

### 4.3. Виды заявок: `apps/servicedesk/notify_kinds.py`

Функция точки `notification_kinds() -> list[NotificationKind]` возвращает четыре вида из
таблицы 3.2 (коды, названия, порядок, `external_text`, `default_channels`, `events`); константы
`NEW_IN_QUEUE`, `ASSIGNED`, `REQUESTER_REPLIED`, `REPLY_FAILED` — коды видов. Регистрирует её
`ServicedeskConfig.ready()`. Тесты берут виды из `kinds.catalog()` и вызывают
`kind.build(event, data)`, `kind.available(user)`, `kind.still_relevant(user_id, object_ref)`.

| Функция | Подпись и что возвращает | Тесты |
|---|---|---|
| `build(event, data)` каждого вида | `build(event: str, data: dict) -> list[Draft]`; `data` — данные события (раздел 4.2) без изменений; состояние заявки читается из базы по `data["number"]`, не из данных события (текущий ответственный, очередь, вид статуса); получатель — только тот, у кого `access.can_work(user, ticket)`, и не `actor_id` события (FR-314, FR-315); получатели — пользователи в состояниях `active` и `blocked` (уволенных и приглашённых нет; общая фильтрация — `dispatch`, раздел 6); заявки нет в базе — `[]`; для события вида, которого нет в `events` — `[]`. `Draft.url` — `/tickets/<номер>/`; `Draft.object_ref` — `servicedesk.ticket:<pk>`; тема в тексте обрезается до 100 знаков по символам (больше 100 — первые 99 и «…»); названия очереди — название узла | T-4106, T-4107, T-4108 |
| `new_in_queue.build` | по таблице плана «События и получатели»: `ticket_created`, `ticket_transferred`, `ticket_reopened` при отсутствии ответственного — `direct_members(<очередь>)` без `actor_id`; при `ticket_transferred` очередь — `to_queue_id`; при `ticket_created` очередь — `queue_id` | T-4106 |
| `assigned.build` | `ticket_created` с ответственным, не равным `actor_id`; `assignee_changed` с `assignee_after_id`, не равным `actor_id` и не пустым — один `Draft` ответственному | T-4106 |
| `requester_replied.build` | `reply_received` при ответственном — один `Draft` ему (при `via` и `appended`, и `reopened`) | T-4107 |
| `reply_failed.build` | `reply_not_sent` с `reason` `quarantine` или `encrypted` и ответственным — «Ответ по заявке #N не отправлен: вложение в карантине» / «…: вложение — архив с паролем»; `ticket_closed` — ничего; `mail_failed` с ответственным — «Письмо по заявке #N не доставлено»; ответственного нет — `[]` | T-4107, T-4108 |
| `available(user)` | `new_in_queue.available(user) -> bool`: сотрудник — прямой участник хотя бы одного узла-очереди (`Queue` + `Membership`, руководитель и заместитель этого же узла считаются прямыми); `assigned`, `requester_replied`, `reply_failed`: пункт «Заявки» виден (участник очереди, держатель «Все заявки» или ответственный хотя бы по одной заявке — тот же признак, что у меню среза 003); руководитель вышестоящего узла, не отмеченный в очереди, — `False` для `new_in_queue` | T-4102 test_available_* |
| `still_relevant(user_id, object_ref)` | `-> bool`: сотрудник не уволен, заявка перечитана из базы (`Ticket` по `pk` из `object_ref`), `access.scope(user, fresh=True)`, затем `access.can_work(user, ticket)`; для `new_in_queue` ещё: у заявки нет ответственного и она не закрыта (`kind != "closed"`); заявки нет, `object_ref` пуст или чужого модуля, пользователя нет — `False` | T-4107 test_still_relevant_* |

## 5. Адаптеры

### 5.1. Общее для адаптеров ботов и Web Push

Модуль `apps/integrations/channel.py` (выбор контракта; одно место для обоих клиентов ботов и
Web Push; клиенты импортируют из него и переэкспортируют имена, так что `client.ChannelGone`
работает):

| Имя | Что | Тесты |
|---|---|---|
| `Response` | `NamedTuple`: `status: int`, `headers: dict[str, str]` (ключи — в нижнем регистре), `body: bytes` | T-4116, T-4119 |
| `ChannelError` | `Exception`; конструктор `ChannelError(method: str, code: int \| None = None, *, reason: str = "")`; атрибуты `.method`, `.code`, `.reason`; `str(exc)` — `"<метод> <код>"`, а при `code=None` — `"<метод> <reason>"`; в тексте нет адреса запроса и токена (NFR-312): метод — имя метода Telegram (`sendMessage`) или `"GET /me"`, `"GET /updates"`, `"POST /messages"` у MAX | T-4119 test_adapter_exception_text_has_method_and_code_without_request_url, test_token_not_in_adapter_exceptions |
| `ChannelGone(ChannelError)` | ответ 403: бот заблокирован, пользователь удалён или остановил бота | T-4119 |
| `RetryLater(ChannelError)` (уточнение формы: план пишет `RetryLater(after)`, здесь `after` — именованный) | 429, 5xx, сеть, таймаут, и 409 Telegram; дополнительный именованный аргумент `after: int \| None = None` (секунды до повтора: Telegram — `parameters.retry_after`, MAX — заголовок `Retry-After` целым числом; иначе `None`), атрибут `.after`; `reason` — `"timeout"`, `"network"` или `""`; у 409 `code == 409`; `RetryLater` всегда несёт `code` (ответ) или непустой `reason` (сеть, таймаут) | T-4119 test_429_with_retry_after_gives_retry_later, test_5xx_network_and_timeout_give_retry_later; T-4120 |
| `BadRequest(ChannelError)` | ответ 400 и любой другой неповторяемый ответ (404, 3xx и подобные) | T-4119 test_400_gives_bad_request_and_delivery_fails_without_retry |
| `BadToken(ChannelError)` | ответ 401: токен не принят — ошибка настройки | T-4119 test_401_keeps_binding_and_retries_by_schedule |
| Точка транспорта | в каждом из трёх клиентов (`telegram/client.py`, `max/client.py`, `webpush/client.py`) — заменяемая на уровне модуля функция `transport(request: urllib.request.Request, timeout: float) -> Response` (выбор контракта; тест подменяет её `monkeypatch.setattr(client, "transport", fake)` и видит адрес, заголовки, тело и таймаут). Настоящая функция строит открывающее устройство `urllib` **без обработчика перенаправлений** (ответ 3xx возвращается как `Response`, а не исполняется), превращает `HTTPError` в `Response`, таймаут — в `TimeoutError`, прочие сбои сети — в `OSError`; клиент переводит `TimeoutError` в `RetryLater(reason="timeout")`, `OSError` — в `RetryLater(reason="network")`. Токен и адрес запроса в тексты ошибок не попадают | T-4116 test_redirect_3xx_is_not_followed_and_fails_without_retries, T-4119, T-4120 |
| Чтение настроек | клиенты читают `settings.TELEGRAM_API_BASE`, `settings.TELEGRAM_BOT_TOKEN`, `settings.MAX_API_BASE`, `settings.MAX_BOT_TOKEN` при каждом вызове (тест подменяет их фикстурой `settings`); пустой токен — функция не вызывает сеть и поднимает `BadToken(method, 401)` | T-4119, T-4120 |
| Таймауты | константы модуля каждого клиента ботов: `POLL_SOCKET_TIMEOUT = 40` (опрос), `SEND_SOCKET_TIMEOUT = 15` (отправка и прочие методы); они передаются в `transport` вторым аргументом; ожидание на стороне службы — `timeout=25` | T-4120 test_poll_socket_timeout_is_40_seconds_and_send_timeout_15 |
| Перехват запросов ботов | помощник `support_notify.bots_capture(module, *, passthrough=True, responses=None)` (решение E15) — контекстный менеджер над `module.transport` (`module` — `apps.integrations.telegram.client` или `apps.integrations.max.client`): `.requests` — список объектов с `.url`, `.method`, `.headers` (ключи в нижнем регистре), `.body`, `.json` (разобранное тело или `None`), `.params` (параметры адресной строки и тела JSON вместе), `.timeout`; `passthrough=True` — запрос уходит настоящей функцией на `fakebots`, `False` — ответ из `responses` (один `Response` или список по порядку); в адресе Telegram токен — тест не печатает `.url` целиком | T-4119, T-4120 |

### 5.2. Клиенты Telegram и MAX

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `telegram.client.get_me` | `get_me() -> dict`: `GET <TELEGRAM_API_BASE>/bot<токен>/getMe`, возвращает `result` (ключ `username`); ссылка на бота — `https://t.me/<username>` | T-4120 test_bot_name_is_refreshed_on_each_loop_start |
| `telegram.client.get_updates` | `get_updates(offset: int \| None, *, timeout: int = 25) -> list[dict]`: `getUpdates` запросом `POST` с телом JSON (`Content-Type: application/json`): `offset` (если не `None`), `timeout`, `allowed_updates=["message", "my_chat_member"]` списком (решение E15); сокет — `POLL_SOCKET_TIMEOUT`; возвращает `result` | T-4120 test_telegram_poll_requests_use_offset_timeout_25_and_allowed_updates |
| `telegram.client.send_message` | `send_message(chat_id: str, text: str, *, button: tuple[str, str] \| None = None) -> str`: `sendMessage` запросом `POST` с телом JSON: `chat_id`, `text` (обрезается до 4096 знаков простым срезом `[:4096]`), `parse_mode="HTML"`, `link_preview_options={"is_disabled": true}`, при `button=(подпись, адрес)` — `reply_markup={"inline_keyboard": [[{"text": подпись, "url": адрес}]]}`; возвращает `str(message_id)`; клиент текст не экранирует: `html.escape` делает вызывающая служба (`delivery.send_delivery`, 6.9, решение E14) | T-4119 test_telegram_send_uses_html_parse_mode_and_disabled_link_preview, test_telegram_message_has_link_button_to_notifications_page_only, test_telegram_text_is_cut_to_4096_characters |
| `telegram.client.delete_webhook` | `delete_webhook() -> None`: `deleteWebhook` запросом `POST` с телом JSON `{"drop_pending_updates": false}` | T-4120 test_delete_webhook_called_on_first_start_without_dropping_pending_updates |
| Telegram: перевод ответов | 401 → `BadToken`; 403 → `ChannelGone`; 400 → `BadRequest`; 409 → `RetryLater(code=409)`; 429 → `RetryLater(after=parameters.retry_after)`; 5xx, сеть, таймаут → `RetryLater`; остальное → `BadRequest` | T-4119, T-4120 |
| `max.client.get_me` | `get_me() -> dict`: `GET <MAX_API_BASE>/me`, заголовок `Authorization: <токен>` (без слова `Bearer`; F3 Ф9: apiKey в заголовке `Authorization`, форму значения сверяет T-4307); возвращает объект бота (ключ `username`); ссылка на бота — `https://max.ru/<username>` (выбор контракта: в плане «имя бота», для ссылки годится только `username`) | T-4120 |
| `max.client.get_updates` | `get_updates(marker: int \| None, *, timeout: int = 25) -> tuple[list[dict], int \| None]`: `GET /updates` с параметрами `timeout`, `types=bot_started,bot_stopped,message_created`, `marker` (если не `None`); возвращает пару (`updates`, `marker` ответа) | T-4120 test_max_poll_requests_use_timeout_25_types_and_marker, test_max_marker_is_taken_from_previous_response |
| `max.client.send_message` | `send_message(chat_id: str, text: str, *, button: tuple[str, str] \| None = None) -> str`: `POST /messages` с параметром `chat_id` в адресе и телом `{"text": …, "format": "html"}` (текст обрезается до 4000 знаков срезом), при `button` (F3 Ф12) — `"attachments": [{"type": "inline_keyboard", "payload": {"buttons": [[{"type": "link", "text": подпись, "url": адрес}]]}}]`; возвращает `message.body.mid` | T-4119 test_max_send_uses_format_html_and_link_button_attachment, test_max_text_is_cut_to_4000_characters, test_telegram_url_has_base_bot_token_and_method_and_max_token_goes_in_header |
| MAX: перевод ответов | 401 → `BadToken`; 403 → `ChannelGone`; 400 → `BadRequest`; 429 → `RetryLater(after=Retry-After или None)`; 5xx, сеть, таймаут → `RetryLater`; остальное → `BadRequest` | T-4119 |
| Построитель контекста TLS | `max.client.ssl_context() -> ssl.SSLContext`: `ssl.create_default_context(cafile=str(CA_FILE))`, где `CA_FILE = pathlib.Path(__file__).parent / "certs" / "russian_trusted_root_ca.crt"` (константа модуля); системное хранилище не загружается: `ctx.get_ca_certs()` содержит ровно один сертификат — корень Минцифры; для адресов `https` транспорт MAX использует этот контекст, для `http` (на `fakebots`) — нет; у клиента Telegram свой построитель `telegram.client.ssl_context() -> ssl.SSLContext` — `ssl.create_default_context()` без `cafile` (системное хранилище); корня Минцифры в нём нет: среди `get_ca_certs(binary_form=True)` нет сертификата с отпечатком `ROOT_CA_SHA256`; `transport` каждого клиента зовёт `ssl_context()` своего модуля при каждом запросе к адресу `https` (атрибут модуля, тест может его подменить; решение E13) | T-4121 test_max_adapter_context_is_built_with_cafile_and_holds_only_that_root, test_max_adapter_does_not_load_system_trust_store, test_telegram_adapter_uses_system_trust_store_and_not_the_ministry_root, test_live_tls_to_platform_api2_max_ru_passes_with_ministry_root, test_live_tls_to_api_telegram_org_is_rejected_with_ministry_root |

### 5.3. Web Push: `crypto.py` и `client.py`

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `crypto.CryptoError` | `ValueError` в `apps/integrations/webpush/crypto.py`; тексты — фиксированные и без ключей: «неверные ключи подписки», «неверный ключ VAPID», «нагрузка слишком длинная»; ключи, соли и подписи в текст не попадают (NFR-312) | T-4114 test_private_key_not_in_exception_on_bad_key_material, test_private_key_not_in_exception_on_bad_subscription_keys |
| `crypto.encrypt` | `encrypt(payload: bytes, p256dh: str, auth: str, *, salt: bytes \| None = None, sender_private_key: bytes \| None = None) -> bytes`: `p256dh` и `auth` — строки base64url, как их присылает браузер и как они хранятся (с дополнением или без); `salt` — 16 байт (по умолчанию случайные), `sender_private_key` — 32 байта скаляра P-256 (по умолчанию новый на каждый вызов); результат — полное тело aes128gcm: `salt (16) ‖ rs (4 байта, 4096) ‖ idlen (1 байт, 65) ‖ открытый ключ отправителя (65)` и шифртекст одной записью; открытый текст до 3993 байт включительно, больше — `CryptoError`; запись заканчивается разделителем `0x02` (последняя запись) | T-4114 test_rfc8291_appendix_a_ciphertext_matches_byte_for_byte, test_rfc8291_appendix_a_header_is_salt_rs_idlen_and_sender_key, test_encrypt_makes_single_record_with_rs_4096, test_encrypt_accepts_plaintext_of_3993_bytes, test_encrypt_rejects_plaintext_of_3994_bytes, test_encrypted_payload_of_about_100_bytes_decrypts_with_browser_keys, test_encrypt_uses_new_salt_and_new_sender_key_on_each_call |
| `crypto.encrypt_detail` | `encrypt_detail(payload, p256dh, auth, *, salt=None, sender_private_key=None) -> Encrypted` (выбор контракта: промежуточные значения RFC 8291 для побайтной сверки, чтобы тесты не лезли в закрытые имена); `Encrypted` — `NamedTuple`: `body: bytes` (то же, что вернёт `encrypt`), `ecdh_secret: bytes`, `ikm: bytes`, `content_key: bytes` (16 байт), `nonce: bytes` (12 байт), `salt: bytes`, `sender_public: bytes` (65); `encrypt(...)` равна `encrypt_detail(...).body` | T-4114 test_rfc8291_appendix_a_ecdh_secret_and_ikm_match, test_rfc8291_appendix_a_content_key_and_nonce_match |
| `crypto.vapid` | `vapid(endpoint: str, private_key: str, subject: str) -> str`: `private_key` — base64url 32 байта (`settings.VAPID_PRIVATE_KEY`); возвращает значение заголовка `Authorization`: `vapid t=<JWT>, k=<открытый ключ base64url без дополнения>`; открытый ключ вычисляется из закрытого; JWT: заголовок `{"typ": "JWT", "alg": "ES256"}`, полезная часть `{"aud": "<схема>://<хост[:порт]>" адреса подписки без пути, "exp": int(timezone.now().timestamp()) + 43200, "sub": subject}`, подпись ES256 — 64 байта `r ‖ s`; «сейчас» берётся из `timezone.now()` (тесты ставят `Clock`); плохой ключ — `CryptoError` | T-4114 test_vapid_signature_verifies_with_public_key, test_vapid_signature_is_es256_raw_64_bytes_and_header_alg, test_vapid_aud_is_origin_of_subscription_endpoint_without_path, test_vapid_exp_is_12_hours_after_now, test_vapid_sub_equals_given_subject, test_vapid_authorization_header_has_vapid_t_and_k_parts |
| `crypto.generate_vapid_keys` | `generate_vapid_keys() -> tuple[str, str]`: (закрытый 32 байта base64url без дополнения, открытый 65 байт base64url без дополнения); её зовёт команда `notify_vapid_keys` (8.2) | T-4130 test_vapid_keys_command_prints_pair_for_env |
| Константы теста RFC 8291 | приложение A RFC 8291 (открытый текст, `as_private`, `as_public`, `ua_private`, `ua_public`, `auth_secret`, `salt`, `ecdh_secret`, `ikm`, `content_key`, `nonce`, шифртекст) собираются в `support_notify` через `bytes.fromhex(...)` и `base64.urlsafe_b64decode`; имена констант — `RFC8291_PLAINTEXT`, `RFC8291_SENDER_PRIV`, `RFC8291_SENDER_PUB`, `RFC8291_RECEIVER_PRIV`, `RFC8291_RECEIVER_PUB`, `RFC8291_AUTH`, `RFC8291_SALT`, `RFC8291_ECDH`, `RFC8291_IKM`, `RFC8291_CEK`, `RFC8291_NONCE`, `RFC8291_BODY` (по одному значению на имя; значения — из приложения A, с проверкой по тексту RFC) | T-4100 (помощник), T-4114 |
| `client.send` | `send(subscription, payload: bytes, ttl: int = 43200, urgency: str = "normal", topic: str \| None = None, timeout: float = 10) -> Sent` в `apps/integrations/webpush/client.py`; `subscription` — любой объект с атрибутами `endpoint`, `p256dh`, `auth` (строка модели `PushSubscription` или `types.SimpleNamespace`); `payload` — тело JSON `{"title", "url", "tag"}` в байтах (шифрует сам `send`; собирает `delivery.send_webpush`, 6.9); запрос `POST <endpoint>` с заголовками `Authorization` (от `crypto.vapid(endpoint, settings.VAPID_PRIVATE_KEY, settings.VAPID_SUBJECT)`), `TTL: 43200`, `Urgency: normal`, `Content-Encoding: aes128gcm`, `Content-Type: application/octet-stream`, `Topic` — только если `topic` не `None`; возвращает `Sent(status: int, retry_after: int \| None)` — `NamedTuple`; `retry_after` — секунды: заголовок `Retry-After` целым числом либо датой HTTP (тогда секунды от `timezone.now()` до даты, не меньше 0); нет заголовка — `None`; ответ 3xx, 4xx, 5xx — не исключение, а `Sent`; сеть — `client.SendError("network")`, таймаут — `client.SendError("timeout")` (`SendError(Exception)` с атрибутом `.reason`); исключения клиентов ботов (`ChannelGone` и другие) Web Push не поднимает; перенаправления не выполняются (раздел 5.1) | T-4116 test_request_has_ttl_43200_normal_urgency_vapid_and_aes128gcm_headers, test_response_429_delays_retry_until_retry_after, test_response_500_retries_by_schedule, test_network_error_and_timeout_retry_by_schedule, test_redirect_3xx_is_not_followed_and_fails_without_retries |
| Подмена отправки | помощник `support_notify.webpush_capture(status=201, headers=None, error=None, *, by_endpoint=None, on_request=None)` — контекстный менеджер: подменяет `client.transport`, записывает вызовы (`.requests` — список объектов с `.url`, `.method`, `.headers` — словарь с ключами **в нижнем регистре** (`ttl`, `urgency`, `topic`, `content-encoding`, `content-type`, `authorization`; `urllib.request.Request` хранит их как `Ttl`, `Content-encoding`, помощник приводит), `.body`, `.timeout`), отвечает заданным `Response`, при `error` (`"timeout"` или `"network"`) поднимает `TimeoutError` или `OSError`; `by_endpoint` — словарь «адрес подписки → `Response`, `"timeout"` или `"network"`», он главнее общего ответа (разные итоги разным подпискам); `on_request(request)` зовётся перед ответом (так тест сдвигает часы для бюджета 90 с); `.decrypt(request, keys) -> dict` расшифровывает тело ключами браузера `keys`; пара ключей браузера — `support_notify.browser_keys() -> BrowserKeys` (`NamedTuple`: `p256dh`, `auth` — base64url без дополнения, как у браузера; `private` — 32 байта закрытого скаляра P-256; `auth_raw` — 16 байт), новая пара на каждый вызов (решение E15) | T-4115, T-4116 |

### 5.4. Шаг опроса ботов

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `bots.poll_once` | в `apps/notify/services/bots.py` (T-4213): `poll_once(channel: str, *, wait: int = 25) -> float` — один шаг цикла опроса без ожидания и без бесконечного цикла; цикл `notify_poll` зовёт его в потоке на бота и ждёт возвращённое число секунд. Порядок: (1) канал не активен (`bots.active(channel)` ложно: выключен администратором или токен пуст) — сеть не трогается, результат `PAUSE_IDLE`; (2) курсор из `BotState` (нет строки — создаётся с пустым курсором); (3) `get_updates(offset или marker, timeout=wait)`: Telegram — `offset = int(cursor) + 1`, MAX — `marker = int(cursor)` (курсора нет — `None`); (4) каждое событие — `handle_update(channel, update)` в своей транзакции (раздел 6); сбой одного события не откатывает предыдущие; исключение из `handle_update` (кроме ошибок адаптера при ответе — их ловит сама `handle_update`) `poll_once` не ловит: остальные события пачки не обрабатываются, курсор не записывается, исключение уходит в `run_loop` (8.2; решение E18); (5) курсор записывается в `BotState` один раз после обработки пачки (Telegram — `str(последний update_id пачки)`, MAX — `str(marker ответа)`; решение E6); при сбое пачки курсор не записывается, событие придёт снова и обрабатывается повторяемо; (6) успех — `BotState.last_error = ""`; если в `channel_status` канала код `bad_token` — `settings.clear_channel_error(channel)` (опрос стирает только то, что мог записать сам; ошибки отправки `unavailable`, `rate_limited` очищает удачная отправка; решение E4), результат `0.0`. Ошибки: `RetryLater` с `code == 409` — `last_error = "conflict"`, результат `PAUSE_CONFLICT`; `BadToken` — `last_error = "bad_token"`, `settings.note_channel_error(channel, "bad_token")` (решение E4), результат `PAUSE_BAD_TOKEN`; `RetryLater` — `last_error = "unavailable"`, результат `max(1, after)`, если служба назвала `after`, иначе `PAUSE_ERROR`; `ChannelGone`, `BadRequest` — `last_error = "unavailable"`, результат `PAUSE_ERROR` (решение A4); 409 и сбои, кроме `BadToken`, `channel_status` не пишут (E4); шаг не поднимает исключений адаптера наружу | T-4120 test_telegram_offset_is_last_update_id_plus_1, test_max_marker_is_taken_from_previous_response, test_cursor_is_saved_in_database_after_batch, test_each_event_is_handled_in_its_own_transaction, test_cursor_not_saved_when_batch_fails_and_event_repeats_safely, test_telegram_409_pauses_30_seconds_and_writes_last_error, test_loop_idles_when_channel_disabled_or_token_missing |
| Паузы | константы модуля `bots`: `PAUSE_CONFLICT = 30` (план: пауза 30 с при 409), `PAUSE_IDLE = 60` (план: проверка раз в минуту), `PAUSE_ERROR = 5`, `PAUSE_BAD_TOKEN = 60` (решение A4) | T-4120 |
| `bots.start_cycle` | `start_cycle(channel: str) -> bool` — начало цикла (решение E5, уточняет A6): канал не активен (`bots.active(channel)` ложно) — `False` без сети и без записей; иначе обновляет `BotState.bot_username` из `get_me` и у Telegram вызывает `delete_webhook()` (`drop_pending_updates=false`), успех — `True`; ошибка адаптера записывается в `last_error` (у `BadToken` ещё `note_channel_error(channel, "bad_token")`), не поднимается, результат `False`. `bots.active(channel) -> bool` — `settings.channel_on(channel)` (переключатель включён и токен задан). Зовёт `run_loop` (8.2): при старте потока и снова, когда канал стал активен после неактивности; пока `start_cycle` не удался — перед каждым шагом; после удачного старта на шагах опроса не зовётся | T-4120 test_delete_webhook_called_on_first_start_without_dropping_pending_updates (проверяет вызов при старте и `drop_pending_updates=false`), test_bot_name_is_refreshed_on_each_loop_start |
| Два потока | потоки Telegram и MAX независимы: сбой и пауза одного не задерживают другой | T-4120 test_loops_of_two_bots_run_independently |

## 6. Сервисы `notify`

Модули лежат в `apps/notify/services/<модуль>.py` (пятнадцать: `kinds`, `prefs`, `settings`,
`quiet`, `dispatch`, `live`, `reading`, `delivery`, `mail`, `digest`, `push`, `binding`, `bots`,
`retention`, `cleanup`); тесты зовут `apps.notify.services.<модуль>` внутри функций теста
(правила в шапке). Колонка «Тесты» — задача или файл, который берёт имя. Всё, что не названо
публичным в 6.1, внутреннее: тесты зовут его, но другие срезы — нет.

### 6.1. Общее для всех модулей

| Что | Требование | Тесты |
|---|---|---|
| Ошибка | **Одна на весь `notify`**: `apps.notify.services.NotifyError(Exception)` (файл `apps/notify/services/errors.py`, экспорт из `services/__init__.py`), как `ServiceDeskError` (`code`, `message`), с добавленным именованным `field`: `__init__(self, code: str, message: str, *, field: str = "")`, атрибуты `code`, `message`, `field` (имя поля формы или пусто), `str(error)` равна `message`. Тест узнаёт причину по `error.code`, поле — по `error.field`; текст сверяет только там, где раздел 15 даёт дословный. Чужое или несуществующее уведомление, подписка, привязка — не `NotifyError`, а `django.http.Http404` из сервиса (выбор контракта, как у `servicedesk`). Ошибка шины, слоя каналов и адаптеров ботов наружу из сервиса не поднимается там, где это сказано в строке функции | T-4115, T-4118, T-4125, T-4127 |
| Подписи | действия сотрудника над своим принимают `user` (объект `User`) первым и `ip=None` только по ключу; действия администратора и системы — `actor` и `ip` только по ключу (`actor=None` — «система»: журнал пишется без автора); объекты других модулей сервис получает числом (`user_id`) там, где это сказано | T-4125, T-4127 |
| Транзакция | каждая функция, меняющая данные, работает в своём `transaction.atomic()`; вложенный вызов — точка сохранения; запрос в сеть (адаптеры ботов и Web Push) идёт вне транзакции с замком строки доставки (раздел 6.9) | T-4113, T-4116 |
| Время | только `django.utils.timezone.now()` (правило шапки); аргумента `now` у функций нет, кроме явно названного | T-4110…T-4113 |
| Журнал | `apps.core.services.audit.record(action, *, actor=None, object_type, object_id, before, after, ip)`; коды, объекты и ключи «было / стало» — раздел 9; нет ключей `url`, `link`, `code`, `token`, нет идентификаторов чатов, адресов подписок, текстов уведомлений | T-4129 |
| Публичное и внутреннее | публичны для других срезов только `kinds.catalog()` и `reading.mark_object(user_id, object_ref)` (план, «Контракты»); основной путь — точка `notification_kinds` и события шины; остальные имена раздела — внутренние: их зовут представления `notify`, задания и тесты; модели `notify` другие приложения не импортируют | T-4131 |
| Границы | `apps/notify/**` не импортирует `apps.servicedesk`; из `apps.org` — только `apps.org.services.calendar`; ядро, org и сервис-деск не импортируют `notify` | T-4131 test_notify_does_not_import_servicedesk, test_notify_does_not_import_org_except_calendar_service, test_core_org_and_servicedesk_do_not_import_notify |
| Логгеры | `logging.getLogger(__name__)` в каждом модуле, то есть `apps.notify.services.<модуль>`; предупреждения и сбои адаптеров пишутся туда; токены, адреса подписок и тексты ошибок ответов в записи не попадают (NFR-312) | T-4110, T-4119 test_token_not_in_application_log_on_errors, T-4122 |
| Подписки шины | `NotifyConfig.ready()` (последним среди приложений) вызывает `dispatch.subscribe_all()` и подписывает: `object.viewed` — `reading.on_object_viewed`; `core.logged_out` — `push.on_logged_out`; `core.user_dismissed` — `cleanup.on_dismissed`; `core.user_rehired` — `cleanup.on_rehired`; затем `check_kinds()`. Все подписчики — функции с именованными параметрами из таблицы событий (разделы 3.3, 4.2) | T-4105, T-4106, T-4117, T-4124, T-4128 |

### 6.2. Коды причин `NotifyError.code`

Коды `Delivery.reason` (раздел 2.1) и результаты `handle_update` (6.14) — отдельные наборы:
здесь только коды ошибки. «Поле» — `error.field`.

| Код | Где и когда | Поле | Тесты |
|---|---|---|---|
| `out_of_range` | `settings.update`: `email_delay_minutes` не из 5…120 или `retention_days` не из 30…365 (или не целое число); текст «Значение поля «<название>» должно быть от A до B» | имя поля | T-4127 test_email_wait_outside_5_to_120_refused_by_field, test_retention_days_outside_30_to_365_refused_by_field |
| `keys_missing` | `settings.update`: включение канала `webpush_enabled`, `telegram_enabled`, `max_enabled`, когда `keys_set` ложно; текст — раздел 15 («ключи задаются в окружении установки») | имя переключателя | T-4127 test_enable_channel_without_keys_refused_with_environment_explanation |
| `bad_defaults` | `settings.update`: в `defaults` код вида не из каталога или вид `mandatory`, значение не список, канал не из `email`, `push`, `telegram`, `max` (`portal` отбрасывается молча, ошибки нет) | `defaults` | T-4127 |
| `bad_quiet_mode` | `prefs.save`: `quiet_mode` не из `calendar`, `own`, `none` | `quiet_mode` | T-4125 |
| `own_no_days` | `quiet.validate_own_hours`: дней нет | `own_days` | T-4110 test_own_hours_rejects_no_days; T-4125 test_own_hours_without_any_day_rejected_with_message |
| `own_bad_day` | то же: день не целое число 0-6 | `own_days` | T-4110 |
| `own_incomplete` | то же: нет «с» или «до» | `own_start` | T-4110 |
| `own_same_time` | то же: «с» равно «до» | `own_end` | T-4110 test_own_hours_rejects_equal_start_and_end; T-4125 |
| `too_long` | `push.check_endpoint`: адрес длиннее 1000 знаков (проверяется первой) | `endpoint` | T-4115 test_endpoint_longer_than_1000_is_rejected |
| `bad_endpoint` | то же: пусто или адрес не разбирается | `endpoint` | T-4115 |
| `bad_scheme` | то же: схема не `https` | `endpoint` | T-4115 test_endpoint_not_https_is_rejected |
| `has_credentials` | то же: в адресе логин или пароль | `endpoint` | T-4115 test_endpoint_with_login_or_password_is_rejected |
| `bad_port` | то же: порт не 443 (без порта и явный 443 допустимы) | `endpoint` | T-4115 test_endpoint_with_port_other_than_443_is_rejected, test_endpoint_with_explicit_port_443_is_accepted |
| `bad_host` | то же: хост не совпал с `WEBPUSH_ALLOWED_HOSTS` целиком (внутренний адрес, чужой хост, `evilnotify.windows.com`); порядок проверок: `too_long`, `bad_endpoint`, `bad_scheme`, `has_credentials`, `bad_port`, `bad_host` | `endpoint` | T-4115 test_endpoint_with_foreign_host_is_rejected, test_endpoint_evilnotify_windows_com_is_rejected, test_endpoint_with_internal_network_address_is_rejected, test_endpoint_subdomain_of_notify_windows_com_is_accepted, test_allowed_hosts_are_taken_from_setting |
| `bad_keys` | `push.save`: `p256dh` или `auth` пусты, длиннее 128 и 64 знаков или не base64url | `p256dh` или `auth` | T-4115 |
| `bad_channel` | `binding.new_code`, `binding.unbind`: канал не `telegram` и не `max` (представление отвечает 404 раньше) | `channel` | T-4118 |
| `channel_disabled` | `binding.new_code`: канал не включён (`settings.channel_on` ложно); кнопки в этом случае нет | `channel` | T-4118 test_bind_button_absent_and_disabled_text_shown_when_channel_off_or_token_missing |
| `chat_taken` | `binding.bind`: чат этого канала уже привязан к другой учётной записи | `channel` | T-4118 test_chat_bound_to_other_account_is_rejected_with_explanation |
| `unknown_kind` | `kinds.get`, `dispatch.create`: кода вида нет в каталоге | `kind` | T-4119 |

Повтор кода вида в каталоге — не `NotifyError`, а `ImproperlyConfigured` (раздел 3.2).

### 6.3. `kinds`

| Имя | Подпись | Возврат | Отказ | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `CHANNELS`, `EXTERNAL` | постоянные кортежи | `CHANNELS == ("portal", "email", "push", "telegram", "max")`; `EXTERNAL == ("email", "push", "telegram", "max")` (каналы таблицы без `portal`) | нет | нет | T-4101 test_channels_are_exactly_portal_email_push_telegram_max_in_order |
| `catalog` | `catalog()` | `list[NotificationKind]`: собирает виды всех функций точки `notification_kinds` при каждом вызове (кэша нет), сортирует по `(order, порядок регистрации функций)`; без регистраций (`extensions.empty()`) — `[]` | `ImproperlyConfigured` при повторе `code` (нет молчаливой замены) | нет | T-4101 (все), T-4102 |
| `get` | `get(code)` | `NotificationKind` из `catalog()` по коду | `NotifyError("unknown_kind")` | нет | T-4119 |
| `for_event` | `for_event(name)` | `list[NotificationKind]`: виды, у которых `name` в `events`, в порядке каталога | нет | нет | T-4106, T-4109 |
| `event_names` | `event_names()` | `list[str]`: все имена событий видов каталога без повторов, в порядке первого появления; по нему `dispatch.subscribe_all` подписывает обёртки | нет | нет | T-4101, T-4109 |
| `check` | `check()` | `None`: зовёт `catalog()`, отказ тот же (`NotifyConfig.ready()` зовёт `check_kinds()`, а тот — `kinds.check()`) | `ImproperlyConfigured` | нет | T-4101 test_duplicate_kind_code_fails_app_startup_instead_of_silent_replace |

### 6.4. `prefs` (действующая таблица и сохранение)

Возврат `effective` — неизменяемые структуры (`@dataclass(frozen=True)` в `prefs.py`):

| Тип | Поля | Смысл | Тесты |
|---|---|---|---|
| `Row` | `kind: NotificationKind`, `cells: dict[str, bool]` | ячейка «включён у вида» без учёта доступности канала; ключи `portal` (всегда `True`), `email`, `push`, `telegram`, `max` в порядке `kinds.CHANNELS`; значения — `on` ячейки | T-4102, T-4109, T-4125 |
| `Channel` | `available: bool`, `reason: str` | `reason` — `""`, `channel_disabled` (выключен администратором или нет ключей), `not_bound` (нет привязки), для Web Push — `no_subscriptions` | T-4102, T-4109, T-4125 |
| `Table` | `rows: list[Row]`, `channels: dict[str, Channel]`, `fixed: list[NotificationKind]`, `web_push_available: bool`, `web_push_reason: str` | `rows` — виды, у которых `available(user)` истина и не `mandatory`, в порядке каталога; `fixed` — виды `mandatory` (две сводные строки «Безопасность: всегда» и «Канал отвязан: всегда, только на портале», 14.3, 15.5); `channels` — все пять ключей (`portal` и `email` всегда доступны; `telegram`, `max` — канал включён администратором, токен задан и привязка есть; `push` — всегда `available=True`: разрешение браузера знает только скрипт страницы); `web_push_available` — Web Push включён администратором, ключи заданы (`settings.channel_on("webpush")`) и есть хотя бы одна подписка (T-4100, решение 34 задач); `web_push_reason` — `""` (доступен), `channel_disabled`, `no_subscriptions` | T-4102, T-4109, T-4125 |

«Включён» и «доступен» разные: на странице галочка стоит, когда ячейка включена
и канал доступен. Признак `data-show` системного уведомления во вкладке зависит только от
включённой ячейки `push` вида и тихих часов, а не от `web_push_available`
(T-4109 test_group_fragment_data_show_*).

| Имя | Подпись | Возврат | Отказ | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `effective` | `effective(user)` | `Table`; значение ячейки: `matrix` сотрудника (если вид в нём есть), иначе `NotifySettings.defaults` (если вид есть), иначе `default_channels` вида без `portal`; строки без строки `UserNotifySettings` — как при пустом `matrix` | нет | ничего | T-4102, T-4125 |
| `channels_for` | `channels_for(user_id, kind)` | `list[str]`: внешние каналы (`email`, `push`, `telegram`, `max`) вида, включённые у сотрудника, в порядке каталога; по тому же правилу, что ячейки `effective`, но без учёта доступности (её проверяет `dispatch`) | нет | ничего | T-4102, T-4109 |
| `channel_states` | `channel_states(user_id)` | `dict[str, Channel]` как `Table.channels`; зовёт `effective`, `dispatch` и `delivery` | нет | ничего | T-4102 test_telegram_and_max_available_only_with_enabled_channel_token_and_binding, T-4109 |
| `row_of` | `row_of(user_id)` | `UserNotifySettings` или `None` | нет | ничего | T-4110, T-4128 |
| `save` | `save(user, *, table=None, quiet_mode=None, own_days=None, own_start=None, own_end=None, ip=None)` | `bool`: изменилось ли что-то. `table` — словарь `код вида -> список отмеченных каналов` для строк `effective(user).rows`; `portal` в списках отбрасывается молча, код вида не из `rows` игнорируется. Применяются только каналы с `Channel.available` (ячейки недоступных каналов не меняются, решение B1). `matrix` записывается **только если** хотя бы одна применимая ячейка отличается от действующей: тогда в него пишется снимок всех строк `rows` (значения — действующие после применения, без `portal`), записи видов, которых в `rows` нет, остаются как были; иначе `matrix` не трогается (сохранение одних тихих часов не фиксирует значения администратора). Тихие часы: `quiet_mode` (`calendar`, `own`, `none`), для `own` — `own_days`, `own_start`, `own_end` (пустой параметр — оставить прежнее значение); при `own` зовёт `quiet.validate_own_hours` по итоговым значениям, при `calendar` и `none` поля `own_*` не меняет. Строка `UserNotifySettings` создаётся при первом изменении; при отсутствии изменений строка не создаётся и журнала нет | `bad_quiet_mode`, `own_no_days`, `own_bad_day`, `own_incomplete`, `own_same_time` (откат целиком: прежние настройки не меняются) | журнал `notify.user_settings_changed` одной записью: изменённые ячейки и изменённые поля тихих часов до и после (раздел 9); после изменения режима, дней или времени — `dispatch.replan_digest(user.pk)` | T-4125 (все), T-4110 test_changing_quiet_mode_recalculates_digest_due_at, test_switch_to_none_sets_digest_due_at_now, T-4126, T-4129 |

### 6.5. `settings`

Название модуля не мешает `django.conf.settings`: внутри модуля он импортируется как `dj_settings`.
Строка настроек одна (`pk=1`); `get()` каждый раз читает базу (кэша нет).

| Имя | Подпись | Возврат | Отказ | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `get` | `get()` | `NotifySettings` (`pk=1`) | нет | ничего | T-4127, T-4129 |
| `keys_set` | `keys_set(channel)` | `bool`; `channel` — `webpush` (заданы все три: `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_SUBJECT`), `telegram` (`TELEGRAM_BOT_TOKEN`), `max` (`MAX_BOT_TOKEN`); читает `django.conf.settings` при каждом вызове; значений не показывает и не возвращает | `ValueError` для другого имени | ничего | T-4127 test_webpush_keys_set_only_when_all_three_variables_are_set, test_telegram_and_max_keys_set_when_bot_token_is_set |
| `channel_on` | `channel_on(channel)` | `bool`: переключатель `<канал>_enabled` включён **и** `keys_set(channel)`; ключ убрали из окружения — `False`, хотя переключатель включён | `ValueError` | ничего | T-4127 test_key_removed_from_environment_makes_channel_off_though_switch_is_on, test_disabled_channel_is_unavailable_to_employees |
| `update` | `update(*, actor, ip=None, **fields)` | `NotifySettings`; `fields` — `webpush_enabled`, `telegram_enabled`, `max_enabled` (bool), `email_delay_minutes` (5…120), `retention_days` (30…365), `defaults` (словарь целиком: заменяет прежний; значения приводятся к порядку каталога без повторов и без `portal`); другие ключи — `TypeError`; `select_for_update` строки `pk=1` | `out_of_range`, `keys_missing`, `bad_defaults`; выключить канал можно всегда | журнал `notify.settings_changed` — только изменившиеся поля до и после (по видам у `defaults`); ничего не изменилось — записи нет; значений ключей в журнале и ответах нет | T-4127, T-4129 test_admin_settings_change_writes_was_became_event, test_save_without_changes_writes_no_event |
| `note_channel_error` | `note_channel_error(channel, code)` | `None`; пишет `channel_status[channel] = {"at": <ISO со смещением>, "code": code}` (`code` — `bad_token`, `unavailable`, `rate_limited`); зовут `delivery` (6.9) и `bots` (только `bad_token`, 5.4, решение E4) | нет | без журнала; `select_for_update` | T-4119 test_401_writes_token_not_accepted_with_time_to_channel_status |
| `clear_channel_error` | `clear_channel_error(channel)` | `None`; удаляет запись канала после удачной отправки в канал (`delivery`) или после удачного шага опроса бота, если в записи код `bad_token` (`bots`; решения A3, E4); записи нет — ничего не пишет | нет | без журнала | T-4119, T-4127 |
| `channel_error` | `channel_error(channel)` | `dict` с ключами `at`, `code` или `None` (страница администратора) | нет | ничего | T-4127 test_page_shows_bot_name_and_last_error_time_and_code_of_channel |

### 6.6. `quiet`

Время считается по Москве (`timezone.localtime`, NFR-307); аргумент `moment` — любое время с
поясом. Первый аргумент — `UserNotifySettings` или `None` (нет строки — режим `calendar`).
День 0 — понедельник. Конец интервала в рабочее время не входит (`start <= t < end`, решение 32).

| Имя | Подпись | Возврат | Отказ | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `is_working` | `is_working(prefs, moment)` | `bool`. `calendar` — `apps.org.services.calendar.is_working_time(moment)`; `own` — день `moment` отмечен и `start <= время < end`; при `start > end` интервал идёт через полночь и относится ко дню начала: рабочее, если день `moment` отмечен и время `>= start`, либо отмечен вчерашний день и время `< end`; праздники не учитываются; `none` — всегда `True` | нет | ничего | T-4110 (все `calendar_mode_*`, `own_hours_*`, `none_mode_*`, test_times_are_computed_in_moscow_zone, test_employee_without_settings_row_is_in_calendar_mode) |
| `next_start` | `next_start(prefs, moment)` | `datetime` с поясом (Москва) или `None`. `calendar` — `calendar.next_working_start(moment)` (сам `moment`, если он в рабочее время; `None`, если за 400 суток рабочего дня нет); `own` — `moment`, если `is_working`, иначе ближайшее начало интервала (день из `own_days`, время `own_start`, строго позже `moment`); `none` — `moment`. `None` бывает только у `calendar` | нет | ничего; предупреждения не пишет (его пишет `dispatch.plan_digest`) | T-4110 test_calendar_mode_next_start_*, test_own_hours_next_start_*, test_none_mode_next_start_is_now |
| `validate_own_hours` | `validate_own_hours(days, start, end)` | `tuple[list[int], datetime.time, datetime.time]`: дни по возрастанию без повторов, `start`, `end` | `own_no_days`, `own_bad_day`, `own_incomplete`, `own_same_time`; «с» позже «до» допустимо | ничего | T-4110 test_own_hours_rejects_*, test_own_hours_accepts_start_later_than_end; T-4125 |

### 6.7. `dispatch`

Подписчик шины получает `handler(**data)` (правила шапки: сбой подписчика шина пишет в лог
`apps.core.events`, действие не откатывает). Каждый обработчик шины работает в своей транзакции
(`events.publish`), поэтому «после фиксации» ниже — фиксация этой транзакции.

| Имя | Подпись | Возврат | Отказ | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `handler_for` | `handler_for(name)` | функция `handler(**data)`, которая зовёт `on_event(name, **data)`; для одного `name` всегда тот же объект (кэш: повторная подписка шиной игнорируется) | нет | нет | T-4109 test_event_wrapper_passes_event_name_to_handler |
| `subscribe_all` | `subscribe_all()` | `None`: `events.subscribe(name, handler_for(name))` для каждого `name` из `kinds.event_names()`; зовёт `ready()`; помощник `support_notify.register_kind` зовёт `events.subscribe(name, dispatch.handler_for(name))` для событий своего вида | нет | нет | T-4109, T-4101 |
| `on_event` | `on_event(name, **data)` | `list[int]`: номера созданных `Notification` в порядке создания; для каждого вида из `kinds.for_event(name)` — `kind.build(name, data)`, затем `create` | нет; чужой вид и событие без видов — `[]` | см. `create` | T-4106, T-4107, T-4109 |
| `create` | `create(kind_code, drafts)` | `list[int]`: номера созданных записей. Общие правила получателей: `Draft.user_id` существует и в состоянии `active` или `blocked` (уволенный и приглашённый — пропускаются без ошибки); получатель без прав на сам объект отсеивает `build` вида, не `create`. Одна запись `Notification` на `Draft` (`kind`, `text`, `url`, `object_ref`, `created_at=timezone.now()`), доставки по каналам вида получателя: `kind.mandatory` — доставок нет; получатель `blocked` — доставок нет; иначе для каждого канала из `prefs.channels_for(user_id, kind)`, который доступен (`prefs.channel_states`; для `push` — `web_push_available`): `email` — `Delivery(waiting, due_at=создано + email_delay_minutes)`; `push` (канал доставки `webpush`), `telegram`, `max` — рабочее время получателя (`quiet.is_working`): `waiting`, `due_at=сейчас`, `enqueued_at=сейчас`; тихие часы: `held`, `due_at=None`. Прямое создание (без события) использует `bots`/`binding` для вида `notify.channel_unbound` | `unknown_kind` | в одной транзакции: записи, доставки, `plan_digest(user_id)` для каждого получателя с новой `held`; после фиксации (`transaction.on_commit`): `live.push(user_ids, toasts=…)` одним вызовом на все группы события и `delivery.enqueue(<номера waiting со сроком «сейчас»>)`; письмо в очередь при создании не ставится | T-4109 (все), T-4106, T-4119 test_channel_unbound_is_portal_only_and_not_held_by_quiet_hours |
| `plan_digest` | `plan_digest(user_id)` | `datetime \| None`: гарантирует строку `UserNotifySettings`; считает `quiet.next_start(строка, сейчас)`; `digest_due_at` = меньшее из прежнего и нового; следующего начала нет (`None`) — срок не ставится и в логгер `apps.notify.services.dispatch` пишется `WARNING` (в тексте нет данных сотрудника, кроме номера); возвращает итоговый `digest_due_at` | нет | запись `digest_due_at` | T-4109 test_held_delivery_sets_digest_due_at_to_next_working_start, test_digest_due_at_keeps_earlier_value; T-4110 test_calendar_mode_no_next_start_means_no_digest_planned_and_warning_logged |
| `replan_digest` | `replan_digest(user_id)` | `datetime \| None`: пересчёт после смены тихих часов: есть доставки `held` сотрудника — `digest_due_at = quiet.next_start(строка, сейчас)` (для `none` — сейчас; прежнее значение заменяется, а не берётся меньшее; `None` — предупреждение, как у `plan_digest`); `held` нет — `digest_due_at = None` | нет | запись `digest_due_at` | T-4110 test_changing_quiet_mode_recalculates_digest_due_at, test_switch_to_none_sets_digest_due_at_now, test_switch_to_none_without_held_deliveries_plans_no_digest; T-4112 test_quiet_hours_change_digest_sent_at_new_working_start |

Данные системного уведомления во вкладке (`toasts` у `live.push`) собирает `create` для каждого
получателя: ключи `text` (= `Notification.text`), `url` (`/notifications/<id>/open/`), `tag`
(`n-<id>`), `show` (`True`, если у вида включена ячейка `push` получателя и сейчас не тихие часы,
иначе `False`); у видов `mandatory` ячейки нет — `show=False`. Значения экранирует шаблон
разметки (раздел 11).

### 6.8. `live` и `reading`

| Имя | Подпись | Возврат | Отказ | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `live.group` | `group(user_id)` | `str`: `"notify.u.<id>"` | нет | нет | T-4122, T-4118 |
| `live.push` | `push(user_ids, *, toasts=None, binding=None)` (уточнение формы плана: число на колокольчике у каждого сотрудника своё, поэтому оно считается внутри) | `None`. `user_ids` — номера; одно обращение к слою каналов (`async_to_sync`, цикл `group_send` по группам), один запрос `COUNT` по частичному индексу на всех. В группу уходит сообщение слоя `{"type": "notify.update", "count": <непрочитанных>, "toast": <словарь из 6.7 или None>, "binding": <"telegram", "max" или None>}`; обработчик соединения принимает его методом `notify_update` (разметка — раздел 11); `toasts` — `Mapping[int, dict]`, `binding` — канал, чей блок привязки обновить | слой берёт `get_channel_layer()` при каждом вызове — имя импортировано в модуль `live` (`from channels.layers import get_channel_layer`), тест подменяет `apps.notify.services.live.get_channel_layer` (решение E13); перехватывает любое исключение слоя каналов (Valkey недоступен, ожидание дольше 2 с): пишет `WARNING` в `apps.notify.services.live`, не поднимает | сеть | T-4122 test_live_push_survives_channel_layer_failure_without_raising, test_push_reaches_only_sockets_of_target_user, T-4109 test_group_fragment_*, T-4118 test_binding_block_is_pushed_to_user_group_after_bind |
| `live.is_online` | `is_online(user_id)` | `bool`: в ключе `notify:online:<id>` (раздел 7.4) есть элемент с оценкой не старше 60 секунд от `timezone.now()` | нет | ничего | T-4122 test_presence_is_online_when_entry_younger_than_60_seconds, test_presence_is_offline_when_entry_older_than_60_seconds; T-4116 |
| `live.mark_online`, `live.mark_offline` | `mark_online(user_id, connection_id)`, `mark_offline(user_id, connection_id)` | `None`; зовёт обработчик соединения (часть c): `mark_online` — при подключении и каждые 25 с, `mark_offline` — при отключении (убирает элемент этого соединения; другие вкладки остаются) | нет | запись ключа (7.4) | T-4122 test_presence_removed_after_disconnect_and_stays_with_other_tab |
| `reading.unread_count` | `unread_count(user_id)` | `int`: число непрочитанных (по частичному индексу `notify_notif_unread`) | нет | ничего | T-4123, T-4122 |
| `reading.open` | `open(user, notification_id)` | `str`: `Notification.url`; запись своя и непрочитанная — `read_at = timezone.now()` | `Http404`: чужое или несуществующее (запись не меняется) | если число изменилось — `live.push([user.pk])` | T-4124 test_open_own_marks_read_and_redirects_to_url, test_open_foreign_notification_returns_404_and_stays_unread, test_open_pushes_decreased_count_to_group |
| `reading.read` | `read(user, notification_id)` | `bool`: изменилось ли (уже прочитанное — `False`, без рассылки) | `Http404`, как у `open` | рассылка нового числа, если изменилось | T-4124 test_read_marks_one_notification_without_redirect, test_no_count_push_when_mark_changes_nothing |
| `reading.read_all` | `read_all(user)` | `int`: сколько своих непрочитанных отмечено одним `UPDATE` | нет | рассылка, если больше 0 | T-4124 test_read_all_marks_all_own_unread_and_count_becomes_zero, test_read_all_does_not_touch_other_users_notifications |
| `reading.mark_object` | `mark_object(user_id, object_ref)` (**публичная**) | `int`: сколько отмечено одним `UPDATE` непрочитанных этого сотрудника с этим `object_ref`; пустой `object_ref` — `0` без запроса | нет | рассылка нового числа, если отмечено больше 0 | T-4124 test_ticket_card_open_pushes_new_count_lower_by_three, test_ticket_card_open_leaves_other_tickets_and_users_notifications_unread |
| `reading.on_object_viewed` | `on_object_viewed(*, object_ref, user_id)` | `None`: подписчик `object.viewed`; зовёт `mark_object` | нет | как у `mark_object` | T-4124 test_ticket_card_get_as_slider_marks_all_ticket_notifications_read, test_ticket_card_get_as_page_marks_all_ticket_notifications_read |

### 6.9. `delivery`

Константы модуля (тест может подменять их `monkeypatch`): `LEASE_SECONDS = 240`,
`REQUEUE_AFTER_SECONDS = 120`, `WEBPUSH_BUDGET_SECONDS = 90`, `BATCH = 200`,
`MAX_AGE = datetime.timedelta(hours=24)`, `RETRY_DELAYS = (60, 300, 900, 3600)` (секунды после
1, 2, 3, 4 попытки), `RETRY_LATER = 10800` (после пятой и далее).

| Имя | Подпись | Возврат | Отказ | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `next_due` | `next_due(created_at, attempts, now, *, retry_after=None)` | `datetime \| None`: `attempts` — число уже сделанных попыток, включая только что не удавшуюся (после первой неудачи `attempts == 1` → `now + RETRY_DELAYS[0]` секунд; 5 и больше → `now + RETRY_LATER` секунд; решение E17); срок = `now` + 1, 5, 15 минут, 1 час (попытки 1…4), затем +3 часа; `retry_after` (секунды) — срок не раньше `now + retry_after`; срок позже `created_at + 24 часа` — `None` (доставка `failed`, причина `expired`) | нет | ничего (чистая функция) | T-4113 test_retry_schedule_is_1_5_15_minutes_1_hour_then_3_hours, test_delivery_failed_when_next_retry_would_pass_24_hours_from_creation, test_rate_limit_429_moves_due_not_earlier_than_retry_after_* |
| `enqueue` | `enqueue(delivery_ids)` | `None`: ставит `tasks.send_delivery(id)` по одному заданию на номер (раздел 7.2); в той же транзакции `enqueued_at = timezone.now()` | нет | задание уходит после фиксации (`on_db_commit`) | T-4109 test_immediate_deliveries_enqueued_after_commit, T-4113 test_repeated_enqueue_of_same_delivery_is_harmless |
| `external_text` | `external_text(delivery)` | `str`: внешний текст для Telegram, MAX и Web Push: `external_text` вида (раздел 3.2) у доставки уведомления; «У вас N новых уведомлений» (склонение, раздел 15) у доставки сводки, `N = Digest.count_message`; адреса, номера и темы заявок не входят | нет | ничего | T-4108 test_external_texts_*, test_message_has_no_ticket_number_subject_names_or_addresses |
| `send_delivery` | `send_delivery(delivery_id)` | `str`: итог — `"noop"` (строки нет, состояние не `waiting` или срок не наступил), либо состояние строки после вызова: `"sent"`, `"waiting"` (повтор), `"failed"`, `"skipped"`. Порядок: (1) короткая транзакция — `select_for_update(skip_locked=True)`, только `state=waiting`, `due_at <= сейчас`; `state=sending`, `lease_until = сейчас + LEASE_SECONDS`; (2) проверки без сети, первая сработавшая даёт `skipped` с причиной из 2.1 и `lease_until=None`: учётная запись `blocked` — `user_blocked`, `dismissed` — `user_dismissed`; канал не включён (`settings.channel_on`) — `channel_disabled`; нет привязки (Telegram, MAX) — `not_bound`; нет подписок (Web Push) — `no_subscriptions`; Web Push и `live.is_online` — `tab_open`; (3) отправка вне транзакции: Telegram и MAX — `<канал>_client.send_message(binding.chat_id, html.escape(external_text(delivery)), button=(BUTTON_LABEL, settings.PORTAL_URL.rstrip("/") + "/notifications/"))` (клиенты зовутся через модуль, 1.1); `BUTTON_LABEL = "Открыть уведомления"` — константа модуля `delivery`, текст контракта (решение E14); Web Push — `send_webpush` (ниже); (4) вторая короткая транзакция: запись попытки в `log` (у `webpush` итоговой записи нет — записи подписок пишет `send_webpush`, решение E17), `attempts + 1` (один раз на вызов), `lease_until=None`, итог. Итоги: успех — `sent` и `settings.clear_channel_error`; `ChannelGone` — привязка снимается (`binding.unbind(..., reason="bot_unavailable")`), `failed` с причиной `channel_unbound`; `BadRequest` — `failed`, `bad_request`; `BadToken` — привязка остаётся, `settings.note_channel_error(channel, "bad_token")`, повтор по `next_due`; `RetryLater` — `note_channel_error` (`rate_limited` при 429, иначе `unavailable`), повтор по `next_due(..., retry_after=exc.after)`; повтор — `waiting`, новый `due_at`, `enqueued_at=None`; `next_due` дал `None` — `failed`, `expired`. Адреса, токены и ключи в `log` не пишутся | не поднимает ошибок адаптера; сбой за пределами адаптера — исключение задания | см. итоги | T-4113 (все), T-4116, T-4119, T-4127 test_disabled_channel_deliveries_are_skipped_with_reason_channel_off (имя неточно: причина `channel_disabled`, решение B6); T-4108 test_subject_markup_never_reaches_bot_message_and_dynamic_parts_are_html_escaped и T-4119 test_dynamic_parts_of_message_are_html_escaped: вид регистрируется `support_notify.register_kind` с `external_text`, содержащим `<b>&`, текст сообщения — с `&lt;b&gt;&amp;` (решение E14) |
| `send_webpush` | `send_webpush(delivery)` | внутренняя часть шага (3) для канала `webpush`: нагрузка — JSON в UTF-8 `{"title": external_text(delivery), "url": "/notifications/", "tag": "n-<Notification.pk>"}` (у сводки `"tag": "digest"`; план «Web Push», решение E14); запрос на каждую подписку сотрудника (по возрастанию номера), которой нет среди записей `log` с `outcome="ok"` и `sub` (повтор шлёт только без удачной отметки); итог подписки сразу дописывается в `log` короткой транзакцией (`sub` — номер подписки). 2xx — `ok`, `last_ok_at = сейчас`; 404 и 410 — подписка удаляется (`push.drop`, причина `gone`), `outcome="gone"`; 400 и 413 — подписка остаётся, `bad_request`; 429 — повтор: в `next_due(..., retry_after=…)` идёт наибольший `Retry-After` среди подписок, ответивших 429 в этом вызове (ни у одной нет заголовка — `None`; решение E26); 5xx, `SendError("network")`, `SendError("timeout")` — повтор; 3xx — `redirect` без повторов; 401 и 403 — повтор по расписанию, подписка остаётся, запись `log` с `outcome="retry"` и `reason="bad_token"`; любой другой 4xx, кроме 404, 410, 413, 429, — как 400: подписка остаётся, `bad_request` (решение B5); повторяемые итоги — 5xx, сеть, таймаут, 429, 401, 403: первые три пишут `settings.note_channel_error("webpush", "unavailable")`, 429 — `"rate_limited"`, 401 и 403 — `"bad_token"`; удача — `clear_channel_error("webpush")`. Через `WEBPUSH_BUDGET_SECONDS` (по `timezone.now()`) после начала новых подписок не начинает, доставка возвращается в `waiting` с прежним `due_at` и `enqueued_at=None` (`attempts + 1` и в этом случае, решение E17). Итог доставки: хотя бы одна подписка удалась (в этой или прежних попытках) — `sent`; иначе есть повторяемые — `waiting` по расписанию; иначе подписок не осталось — `failed`, `no_subscriptions`; иначе `redirect`, если был 3xx, иначе `bad_request` | нет | как у `send_delivery` | T-4116 (все); ветви 401, 403 и прочих 4xx решения B5 именем теста не покрыты (покрытия нет; тест добавляет следующая версия задач) |
| `tick` | `tick()` | `dict[str, int]` с ключами `emails` (письма, обработанные `mail.send_due`), `released` (возвращены из `sending` в `waiting`), `requeued`, `digests`, `codes`. Шаги по порядку: (1) `mail.send_due()`; (2) сначала доставки `waiting` каналов `webpush`, `telegram`, `max` со сроком в прошлом и `enqueued_at` пустым или старше `REQUEUE_AFTER_SECONDS` — `enqueue` (порциями по `BATCH`), затем доставки `sending` с `lease_until < сейчас` — `waiting`, `lease_until=None`, `enqueued_at=None` (порядок плана, решение E7: возвращённую доставку ставит в очередь следующий обход, в `requeued` этого обхода она не входит); (3) сотрудники с `digest_due_at <= сейчас` — `tasks.build_digest(user_id)` в очередь `notify`; (4) `binding.purge_expired_codes()` — использованные и истёкшие коды (решение B4). Строки берёт порциями по `BATCH` | нет | как у шагов | T-4113 test_tick_*, T-4111, T-4112 test_tick_enqueues_digest_build_only_for_due_users, T-4118 test_tick_deletes_expired_codes_and_keeps_active_ones |

### 6.10. `mail`

| Имя | Подпись | Возврат | Отказ | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `renderers` | `renderers()` | `[MailRenderer(prefix="notify.", render=render)]`; регистрация: `extensions.register("mail_renderers", mail.renderers)` | нет | нет | T-4108, T-4111 |
| `render` | `render(message, context)` | `Rendered(body, [])`; `message` — `MailMessage`, `context` — `{"delivery": <номер>}` (других ключей нет); по `message.template` (`notify.item`, `notify.digest`) собирает простой текст из базы **в момент отправки**: название портала, текст уведомления (у сводки — список «текст — ссылка»), ссылку `PORTAL_URL` + `/notifications/<id>/open/`, строку со ссылкой на «Мои уведомления»; доставки или уведомления уже нет — нейтральный текст «Уведомление больше недоступно» и ссылка на `/notifications/`. Шаблон письма — раздел 10 | нет | ничего | T-4111 test_renderer_reads_text_from_database_at_send_time, test_renderer_neutral_text_when_notification_deleted, test_job_context_contains_only_delivery_number; T-4108 |
| `message_id_for` | `message_id_for(delivery_id)` | `str` `Message-ID`: `email.utils.make_msgid(idstring=f"notify.{delivery_id}", domain=<часть после «@» у email.utils.parseaddr(settings.DEFAULT_FROM_EMAIL)[1]>)` (значение настройки может быть вида «Имя <адрес>»; как `letters.new_message_id`); двойную постановку он не отсекает | нет | нет | T-4111 test_send_rendered_called_with_required_arguments |
| `queue_item` | `queue_item(delivery)` | `int`: номер `MailMessage`; зовёт `send_rendered("notify.item", user.email, subject=<external_text вида>, cc=[], reply_to="", message_id=message_id_for(id), references="", auto_submitted="auto-generated", related_ref=f"notify.delivery:{id}", attachments=[], context={"delivery": id})`; тема — без номера и темы заявки | нет | задание почты — после фиксации (`on_db_commit`) | T-4111 test_send_rendered_called_with_required_arguments, test_subject_is_external_text_without_ticket_number_and_title |
| `queue_digest` | `queue_digest(delivery)` | `int`: номер `MailMessage` шаблона `notify.digest`; тема «За нерабочее время: N уведомлений» (склонение, раздел 10); остальные аргументы как у `queue_item`, `related_ref` — `notify.delivery:<номер>` доставки сводки | нет | после фиксации | T-4112 test_digest_email_delivery_is_digest_email_with_mail_id, test_digest_email_subject_declension_by_count |
| `send_due` | `send_due()` | `int`: сколько доставок `email` обработано. Для каждой доставки `waiting`, канал `email`, `due_at <= сейчас` (порциями по `delivery.BATCH`; каждая в своей транзакции под `select_for_update(skip_locked=True)`) — заново проверяет по порядку: пользователь `blocked` — `skipped` `user_blocked`, `dismissed` — `user_dismissed`; уведомление прочитано — `skipped` `read`; `kind.still_relevant(user_id, object_ref)` ложно — `skipped` `not_relevant`; канал «Почта» у вида выключен (`prefs.channels_for`) — `skipped` `channel_off`; сейчас тихие часы (`quiet.is_working`) — `held`, `due_at=None`, `dispatch.plan_digest`; иначе `queue_item`, `mail_id`, `sent`, `attempts=1`, запись в `log` (`outcome="ok"`). Письмо, не доставленное почтовым модулем, состояние не меняет (решение A5). Пересечение обходов (T-4111 test_overlapping_ticks_send_one_email, решение E10): транзакция теста не даёт второму соединению увидеть строки, поэтому тест проверяет два последовательных `send_due()` — одно `MailMessage`, а в запросе выбора доставок (`CaptureQueriesContext`) — `FOR UPDATE SKIP LOCKED`; состояние доставки перепроверяется под замком (имя теста неточно: проверяются повтор и запрос, а не настоящее пересечение; решения E10, E25) | нет | как у шагов | T-4111 (все), T-4113 |

### 6.11. `digest`

| Имя | Подпись | Возврат | Отказ | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `build` | `build(user_id)` | `Digest \| None`. Шаги (план, «Тихие часы и сводка»): (1) сотрудник `blocked` — его `held` становятся `skipped` `user_blocked`, `digest_due_at` очищается, итог `None`; сейчас не рабочее время (`quiet.is_working`) — `dispatch.replan_digest`, итог `None`; (2) доставки `held` сотрудника под замком; по каждому уведомлению: прочитано — `skipped` `read`; `still_relevant` ложно — `skipped` `not_relevant`; (3) письмо: оставшиеся уведомления с доставкой `email` в `held` — одна доставка `Delivery(digest, email)` (`sent`, `mail_id` из `mail.queue_digest`, `attempts=1`); (4) сообщение: первый канал по порядку `telegram`, `max`, `webpush`, у которого есть хотя бы одна оставшаяся `held`; `Delivery(digest, <канал>, waiting, due_at=сейчас, enqueued_at=сейчас)`; `N` — число `held` этого канала (`Digest.count_message`), у письма — `Digest.count_email`; (5) все использованные `held` — `digested`, `digest_due_at = None`. `Digest.notification_ids` — номера всех вошедших уведомлений. Нет ни письма, ни сообщения — `Digest` не создаётся, итог `None`. Сводка в другой канал не переносится (план): канал выбирается только по наличию `held`, без проверки привязки, — если сотрудник отвязал канал, доставка сводки получит `skipped` `not_bound` (следствие решения B2; решение E20); Web Push при открытой вкладке пропускает `send_delivery` (`tab_open`) | нет | `Digest`, доставки; после фиксации — `delivery.enqueue` доставки-сообщения | T-4112 (все), T-4128 test_blocked_employee_skipped_by_tick_and_digest_and_mail_letter |

### 6.12. `push`

| Имя | Подпись | Возврат | Отказ | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `check_endpoint` | `check_endpoint(endpoint)` | `None`; порядок проверок и коды — 6.2; `WEBPUSH_ALLOWED_HOSTS` читается из `django.conf.settings` при каждом вызове; шаблон `*.<хост>` совпадает, когда хост оканчивается на `.<хост>` (сам `<хост>` и `evil<хост>` — нет), без учёта регистра | `too_long`, `bad_endpoint`, `bad_scheme`, `has_credentials`, `bad_port`, `bad_host` | ничего | T-4115 (проверка адреса) |
| `save` | `save(user, *, endpoint, p256dh, auth, device_id=None, user_agent="", ip=None)` | `PushSubscription`. Проверяет адрес и ключи; браузер и платформа — `devices.parse_user_agent(user_agent)`; подписка с тем же адресом у другой учётной записи удаляется (причина `moved`); у сотрудника то же значение адреса — обновляются ключи и устройство, второй строки нет; после сохранения больше 10 подписок — самая старая (по `created_at`, затем номеру) удаляется (причина `limit`); проверочное сообщение не отправляется | `bad_keys` и коды `check_endpoint`; при отказе ничего не сохранено | журнал `notify.push_subscribed` (браузер, платформа; без адреса и ключей) и `notify.push_removed` у каждой удалённой | T-4115 (все), T-4129 test_push_subscription_by_employee_writes_event_with_browser_and_platform |
| `list_for` | `list_for(user_id)` | `list[PushSubscription]` по убыванию `created_at` | нет | ничего | T-4115 test_subscribed_device_is_listed_and_push_column_becomes_available, T-4126 |
| `delete` | `delete(user, subscription_id, *, ip=None)` | `None`; удаляет свою подписку | `Http404`: чужая или несуществующая | журнал `notify.push_removed` от сотрудника | T-4115 test_user_deletes_own_subscription_from_list, test_deleting_foreign_subscription_returns_404, T-4126 |
| `drop` | `drop(subscription_id, *, reason)` | `None`; система удаляет подписку; `reason` — `gone` (ответ 404 или 410), `logout`, `dismissed`, `moved`, `limit` | нет | журнал `notify.push_removed` от системы с причиной | T-4116 test_response_404_deletes_subscription_and_logs_by_system, T-4129 test_push_removal_by_system_on_service_refusal_logout_and_dismissal_writes_event_with_reason |
| `on_logged_out` | `on_logged_out(*, user_id, device_ids, reason)` | `None`: подписчик `core.logged_out`; удаляет подписки сотрудника, чьё `device_id` в `device_ids` (причина `logout`); подписки без устройства и других устройств остаются | нет | журнал по каждой | T-4117 (все) |

### 6.13. `binding`

| Имя | Подпись | Возврат | Отказ | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `NewCode` | `NamedTuple` | `code: str` (восемь цифр, `"%08d"`), `expires_at: datetime`; открытый код существует только в этом возврате | нет | нет | T-4118 |
| `new_code` | `new_code(user, channel)` | `NewCode`: код из `secrets.randbelow(10**8)`, не совпадающий с действующим (не использован, не просрочен) кодом другого сотрудника в этом канале (при совпадении берётся другой); в базе `BindCode(code_hash=SHA-256, expires_at=сейчас + 10 минут)`; прежний неиспользованный код этого сотрудника в этом канале удаляется в той же транзакции | `bad_channel`, `channel_disabled` | записи; журнала нет | T-4118 test_bind_code_has_8_digits, test_bind_code_expires_in_10_minutes, test_bind_code_is_stored_only_as_sha256_hash, test_bind_code_differs_from_active_code_of_other_user_in_channel, test_new_code_deletes_previous_unused_code_in_same_transaction |
| `get` | `get(user_id, channel)` | `ChatBinding \| None` | нет | ничего | T-4118, T-4119 |
| `bind` | `bind(user_id, channel, chat_id, *, ip=None)` | `ChatBinding`; привязка того же канала к другому чату заменяет прежнюю (одна транзакция); `chat_id` — строка | `chat_taken` | журнал `notify.channel_bound` (канал, без `chat_id`); после фиксации `live.push([user_id], binding=channel)` | T-4118 test_rebinding_channel_to_another_chat_replaces_previous_binding, test_binding_block_is_pushed_to_user_group_after_bind, T-4129 |
| `unbind` | `unbind(user, channel, *, actor=None, ip=None, reason="")` (`user` — объект или номер: системные вызовы из `cleanup` и `bots` могут передать номер; сотрудник, отвязывающий себя, передаёт `actor=user`) | `bool`: была ли привязка. Удаляет привязку и все неиспользованные коды сотрудника в канале; ожидающих доставок не трогает: отправка без привязки даёт `skipped` с причиной `not_bound`, а доставка, на которой пришёл `ChannelGone`, — `failed` с причиной `channel_unbound` (это делает `send_delivery`; решение B2); `reason` — `""` (сотрудник), `bot_unavailable` (`ChannelGone`, `kicked`, `bot_stopped`), `dismissed`; привязки не было — `False`, коды всё равно удаляются, журнала нет | `bad_channel` | журнал `notify.channel_unbound` (от сотрудника или системы, причина, без `chat_id`); при `reason="bot_unavailable"` — запись вида `notify.channel_unbound` через `dispatch.create("notify.channel_unbound", [Draft(user_id, text, "/me/notifications/", "")])`, текст «Telegram отвязан: бот недоступен» или «MAX отвязан: бот недоступен» (раздел 15; адрес — решение A1) | T-4119 test_unbind_*, test_telegram_403_unbinds_chat_and_creates_channel_unbound_notification, test_delivery_to_unbound_channel_fails_with_reason_channel_unbound (имя неточно: тест проверяет доставку, на которой `send_delivery` получил `ChannelGone` — `failed`, `channel_unbound`; отправка без привязки — `skipped`, `not_bound`; решения B2, E25); T-4120; T-4126 |
| `purge_expired_codes` | `purge_expired_codes()` | `int`: удалено `BindCode` с `used_at` не пусто или `expires_at < сейчас` (решение B4: использованный код удаляет ближайший обход, не позже 30 с после использования) | нет | удаление | T-4118 test_tick_deletes_expired_codes_and_keeps_active_ones; T-4128 test_binding_code_deleted_by_sweep_after_10_minutes, test_binding_code_deleted_after_use |

### 6.14. `bots`

Шаг опроса `poll_once`, `start_cycle`, паузы `PAUSE_CONFLICT`, `PAUSE_IDLE` — раздел 5.4. Решение
Opus A4 уточняет паузу: `PAUSE_ERROR = 5` (секунд, значение при сбое без `Retry-After`),
`PAUSE_BAD_TOKEN = 60` (после `BadToken`, 401); при `RetryLater` с `after` шаг возвращает
`max(1, after)`, иначе `PAUSE_ERROR`; 409 — `PAUSE_CONFLICT`. Решение E5 (уточняет A6): `start_cycle`
зовётся в начале цикла — при старте потока и когда канал снова стал активен (5.4, 8.2). Константы привязки: `MAX_ATTEMPTS = 5`,
`WINDOW_MINUTES = 10`.

| Имя | Подпись | Возврат | Отказ | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `bot_link` | `bot_link(channel)` | `str \| None`: `https://t.me/<username>` или `https://max.ru/<username>` по `BotState.bot_username`; имени ещё нет — `None` (страница показывает «Ссылка появится, когда бот подключится»); код и токен в адрес не входят | нет | ничего | T-4118 test_bot_link_has_no_code_or_secrets_in_url, test_bot_link_replaced_by_hint_when_bot_name_unknown |
| `reply_text` | `reply_text(key, channel)` | `str`: текст ответа бота по ключу из `REPLY_KEYS` (раздел 15) | `KeyError` для чужого ключа | ничего | T-4118, T-4119 |
| `handle_update` | `handle_update(channel, update)` | `str`: код результата из таблицы ниже. `channel` — `telegram` или `max`; `update` — одно событие в форме раздела 1.2. Работает в своей `transaction.atomic()` (шаг опроса вызывает её на каждое событие отдельно). Ответ бота отправляется **после фиксации** (`transaction.on_commit`), поэтому откатившееся событие ответа не даёт; ошибки адаптера при ответе ловятся, пишутся `WARNING` в `apps.notify.services.bots` без токена и адреса, наружу не идут (`ChannelGone` при ответе снимает привязку чата, если она есть) | нет | `BotChat`, `BindCode.used_at`, `ChatBinding`; журнал и рассылка — через `binding` | T-4118, T-4120 |

Правила `handle_update` (по порядку; `chat_id` — строка):
- личный чат — Telegram: `message.chat.type == "private"`; MAX: событие `bot_started` или
  `message_created` с `recipient.chat_type == "dialog"`; группы, каналы, события без текста и
  неизвестные типы — `ignored` без ответа;
- начало диалога — Telegram: текст начинается с `/start`; MAX: `bot_started`: строка `BotChat`
  создаётся (если её нет), ответ `ask_code`, результат `dialog_started`;
- текст из личного чата без `BotChat` (решение A2): код не принимается, строка не создаётся,
  счётчика нет, ответ `ask_code`, результат `ask_code`;
- текст из начатого чата: окно неверных кодов — если `window_started_at` пусто или старше
  `WINDOW_MINUTES`, окно начинается заново (`bad_attempts = 0`); при `bad_attempts >= MAX_ATTEMPTS`
  — результат `too_many`, ответ `too_many`, код не проверяется (решение B3); иначе текст (после
  `strip`) хешируется SHA-256 и сверяется с `BindCode` канала: действующий код (`used_at` пусто,
  `expires_at > сейчас`) и чат не привязан к другой учётной записи — `binding.bind`, `used_at`
  ставится, результат `bound`, ответ `bound`; чат привязан к другой учётной записи — результат
  `chat_taken`, ответ `chat_taken` (в счётчик не входит, код не тратится, решение B3); код этого же
  чата, уже использованный для действующей привязки, — результат `repeat` без ответа (повтор
  события после сбоя, решение B3; различим, пока обход не удалил использованный код — до 30 с, решение E1: тест `repeat` обход между событиями не зовёт); любой другой текст (неизвестный, просроченный, использованный)
  — `bad_attempts += 1`, результат `code_invalid`, ответ `code_invalid`;
- привязка снимается событием — Telegram: `my_chat_member` в личном чате с
  `new_chat_member.status == "kicked"`; MAX: `bot_stopped`: есть привязка этого чата —
  `binding.unbind(user, channel, actor=None, reason="bot_unavailable")`, результат `unbound`;
  привязки нет — `ignored`; у Telegram чат не личный — `ignored` (у MAX `bot_stopped` типа чата не несёт);
- события из групп и `kicked` в группе игнорируются без ответа и без записи.

| Результат | Ответ бота (ключ из `REPLY_KEYS`) | Тесты |
|---|---|---|
| `dialog_started` | `ask_code` | T-4118 test_telegram_start_marks_dialog_started_and_bot_asks_for_code, test_max_bot_started_marks_dialog_started_and_bot_asks_for_code |
| `ask_code` | `ask_code` | T-4118 test_code_from_chat_without_started_dialog_is_not_accepted |
| `bound` | `bound` | T-4118 test_valid_telegram_code_binds_chat_marks_code_used_and_bot_confirms, test_valid_max_code_binds_chat_marks_code_used_and_bot_confirms |
| `code_invalid` | `code_invalid` | T-4118 test_expired_code_is_rejected_with_hint_and_no_binding, test_used_code_is_rejected_with_hint_and_no_binding, test_text_not_matching_any_code_gets_refusal_with_hint |
| `chat_taken` | `chat_taken` | T-4118 test_chat_bound_to_other_account_is_rejected_with_explanation |
| `too_many` | `too_many` | T-4118 test_sixth_wrong_code_in_10_minutes_gets_too_many_attempts, test_five_wrong_codes_are_answered_normally_and_window_resets_after_10_minutes |
| `repeat` | нет ответа | T-4118 test_repeated_event_after_failure_gives_one_binding_and_one_reply |
| `unbound` | нет ответа | T-4120 test_my_chat_member_kicked_in_private_chat_unbinds_and_notifies, test_bot_stopped_unbinds_max_chat_and_notifies |
| `ignored` | нет ответа | T-4118 test_code_from_group_chat_is_ignored_without_reply; T-4120 test_my_chat_member_kicked_in_group_is_ignored |

`REPLY_KEYS = ("ask_code", "bound", "code_invalid", "chat_taken", "too_many")` — ключи текстов
ответов; сами тексты (у `bound` — свой для Telegram и MAX) пишет раздел 15.

### 6.15. `retention` и `cleanup`

| Имя | Подпись | Возврат | Отказ | Запись и после фиксации | Тесты |
|---|---|---|---|---|---|
| `retention.BATCH` | константа `1000` | размер порции удаления; тест подменяет её `monkeypatch` и считает порции по числу запросов или вызовов | нет | нет | T-4128 test_nightly_retention_deletes_in_batches_of_1000 |
| `retention.run` | `run()` | `dict[str, int]`: удалено — `notifications`, `digests`, `codes`, `botchats`. Уведомления с `created_at < сейчас − retention_days` (доставки уходят каскадом), сводки старше того же срока (каскадом их доставки), `BindCode` с `used_at` не пусто или `expires_at < сейчас` (`binding.purge_expired_codes`, решение B4), `BotChat` с `started_at < сейчас − 30 суток`, у которых нет `ChatBinding` того же канала и чата. Уведомления и сводки удаляются порциями по `BATCH` (порция — своя транзакция, цикл до порции короче `BATCH`). История заявки не затрагивается | нет | удаление; журнала нет | T-4128 (все `nightly_retention_*`, test_botchat_without_binding_older_than_30_days_deleted_bound_or_newer_kept, test_nightly_retention_deletes_expired_binding_codes, test_ticket_history_stays_in_ticket_after_notification_is_deleted) |
| `cleanup.on_dismissed` | `on_dismissed(*, user_id, actor_id)` | `None`: подписчик `core.user_dismissed`. В одной транзакции: доставки сотрудника (по уведомлению или сводке) в состояниях `waiting`, `held`, `sending` — `skipped`, причина `user_dismissed`, `lease_until=None`; подписки Web Push удаляются (`push.drop(..., reason="dismissed")`); привязки Telegram и MAX и коды удаляются (`binding.unbind(..., reason="dismissed")`, записи вида нет); строка `UserNotifySettings` удаляется; `Notification` и `Digest` остаются до срока хранения | нет | журнал `notify.push_removed` и `notify.channel_unbound` от системы с причиной `dismissed`, без идентификаторов чатов | T-4128 test_dismissal_*, T-4129 test_dismissal_cleanup_writes_events_for_bindings_and_subscriptions; T-4105; T-4120 test_dismissal_event_removes_bindings_and_codes_so_nothing_is_sent |
| `cleanup.on_rehired` | `on_rehired(*, user_id, actor_id)` | `None`: подписчик `core.user_rehired`; удаляет все прежние `Notification` сотрудника (доставки каскадом) и его `Digest` | нет | удаление | T-4128 test_rehire_deletes_previous_notifications_of_employee; T-4105 |

## 7. Задания RQ и ключи Valkey

Расписание (`name`, `cron` или `interval`, `job_timeout`, очередь) стоит в разделе 1.3; здесь
нет его повтора. Задания лежат в `apps/notify/tasks.py` и тонкие: каждое зовёт один сервис.

### 7.1. Функции заданий

`func_name` в очереди — `apps.notify.tasks.<функция>`. Аргументы позиционные, как написано.

| Функция | Очередь | Что зовёт | Аргументы | Возврат | Срок и повторы | Тесты |
|---|---|---|---|---|---|---|
| `send_delivery(delivery_id)` | `notify` | `delivery.send_delivery(delivery_id)` | один, номер `Delivery` | строка итога (6.9) | `job_timeout=180` при постановке (`job.timeout == 180`); повторов RQ нет — повторы по `due_at` | T-4109, T-4113, T-4116, T-4119 |
| `notify_tick()` | `notify` | `delivery.tick()` | нет (cron зовёт без аргументов) | словарь `tick` (6.9) | `job_timeout=120`, `interval=30` (раздел 1.3) | T-4111, T-4113, T-4130 |
| `build_digest(user_id)` | `notify` | `digest.build(user_id)` | один, номер `User` (имя функции — выбор контракта: имя `digest.build` занято сервисом) | `Digest.pk` или `None` | `job_timeout=120` при постановке (`DEFAULT_TIMEOUT` очереди) | T-4112 test_tick_enqueues_digest_build_only_for_due_users |
| `notify_retention()` | `maintenance` | `retention.run()` | нет | словарь `run` (6.15) | `job_timeout=600`, `cron="40 23 * * *"` (раздел 1.3) | T-4128, T-4130 |

Функция задания не ловит исключения сервиса.

### 7.2. Постановка

- `send_delivery` и `build_digest` ставятся так: `django_rq.get_queue("notify",
  commit_mode="on_db_commit").enqueue(tasks.<функция>, <номер>, job_timeout=...)` (тот же
  механизм, что у `mail.services.enqueue`): внутри транзакции задание попадает в очередь только
  после её фиксации, вне транзакции — сразу. Своего `on_commit` у служб нет;
- аргумент один, позиционный: `job.args == (delivery_id,)`; срок — `job.timeout` (целое число);
- одна доставка — одно задание на постановку; повторная постановка той же доставки безвредна
  (второе задание выходит с `"noop"`); `job_id` не задаётся;
- письма уведомлений ставит `mail.send_due` через `send_rendered` (очередь `mail`, раздел 10), а не
  задание `notify`;
- в очереди `notify` задания находятся так: `[j for j in django_rq.get_queue("notify").jobs if
  j.func_name == "apps.notify.tasks.send_delivery"]`.

### 7.3. Как тест выполняет задания и проверяет постановку

| Помощник (`tests/support_notify.py`, пишет T-4100) | Что делает | Тесты |
|---|---|---|
| `run_jobs(queue_name="notify")` | выполняет все задания очереди, стоящие к этому моменту, `SimpleWorker([queue], connection=queue.connection).work(burst=True)` (как `support_mail.deliver`): в том же процессе и той же транзакции теста; повторы по `due_at` не ждёт; возвращает число выполненных | T-4109, T-4111…T-4113, T-4116, T-4119 |
| `run_tick()` | зовёт `tasks.notify_tick()` напрямую внутри `django_capture_on_commit_callbacks(execute=True)`; возвращает словарь `tick`; задания, поставленные обходом, затем выполняет `run_jobs()` | T-4111…T-4113, T-4118 |
| `run_retention()` | зовёт `tasks.notify_retention()` напрямую; возвращает словарь `run` | T-4128 |
| `queued(function="send_delivery", queue_name="notify")` | список заданий очереди по `func_name` `apps.notify.tasks.<function>` | T-4109, T-4111, T-4112 |

Правила проверки «поставлено после фиксации»:
- тест открывает транзакцию сам: `with django_capture_on_commit_callbacks(execute=True):`
  и внутри `with transaction.atomic():` вызывает действие (событие шины, `dispatch.create`,
  `digest.build`); до выхода из блока `queued()` пуст, после выхода — ровно по одному заданию
  на каждую доставку `waiting` со сроком «сейчас»; доставка `email` в очередь `notify` не попадает;
- вне `atomic()` (и вне `on_commit`) `on_db_commit` ставит задание сразу: такой тест «после
  фиксации» не проверит;
- Valkey и RQ живут по настоящему времени: сроки `due_at` и `enqueued_at` тест сдвигает прямой
  записью в поле (правило шапки); `Clock` на очередь не действует;
- очереди между тестами чистит `valkey_clean` (раздел шапки); ожидание рабочего процесса в тестах
  не используется.

### 7.4. Ключи Valkey среза 004

Клиент — `apps.core.services.valkey.conn()`; база 15 в тестах, чистится `valkey_clean`.

| Ключ | Тип и значение | Срок | Кто пишет | Тесты |
|---|---|---|---|---|
| `notify:online:<id>` | упорядоченное множество (`ZADD`); `<id>` — номер сотрудника; элемент — имя соединения (`channel_name` слоя каналов, одно на вкладку); оценка — `timezone.now().timestamp()` (секунды с долями) в момент отметки | `EXPIRE 120` при каждой отметке (страховка от остатков); элементы старше 120 секунд `mark_online` убирает сам (`ZREMRANGEBYSCORE`); «онлайн» — есть элемент не старше 60 секунд (`live.ONLINE_WINDOW = 60`); вкладка обновляет отметку раз в 25 секунд | `live.mark_online` (подключение и проверка раз в 25 с), `live.mark_offline` (отключение: `ZREM` одного элемента) | T-4122 test_presence_*; T-4116 test_open_tab_presence_skips_webpush_even_if_browser_denied_notifications, test_no_live_connection_sends_webpush, test_presence_older_than_60_seconds_does_not_block_webpush (тест ставит элемент сам: `conn().zadd("notify:online:<id>", {"c1": <оценка>})`); T-4131 |
| `crm-asgi:*` слоя каналов | служебные ключи `channels_redis` с префиксом `crm-asgi` (раздел 1.3), база 15 | по настройкам слоя | слой каналов | T-4122 |
| `rq:*` | очереди `notify` и `maintenance`, реестры заданий | как у RQ | RQ | T-4130 |

Других ключей у среза нет: блокировки обхода нет (двойную постановку отсекает
`select_for_update(skip_locked=True)`), кэша счётчика колокольчика нет. Сброс стенда `notify`
(раздел 8) удаляет `notify:online:*` (`scan_iter(match="notify:online:*")` и `delete`), курсоры
`BotState` и очередь `notify`; прочие ключи не трогает (решение 25 задач).

## 8. Команды стенда

Команды лежат в `apps/notify/management/commands/`: `e2e_notify_tick.py`, `e2e_notify_fill.py`
(только стенд), `notify_vapid_keys.py`, `notify_poll.py` (не защищены флагом стенда); функция
сброса —
`apps/notify/stand.py`. Тесты зовут команды `call_command(...)`; вывод читают через `StringIO`
(`stdout=`); отказ — `django.core.management.CommandError` (в консоли — сообщение в `stderr` и код
выхода 1; ошибка разбора аргументов — код 2). Образец — раздел 8 CONTRACT-003.

### 8.1. Общее для команд `e2e_notify_*`

| Что | Требование | Тесты |
|---|---|---|
| Защита | команда работает только при `E2E_STAND=1` в окружении; иначе `CommandError("Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено.")` — тот же текст, что у константы `REFUSAL` команд `e2e_*` сервис-деска (`e2e_run_job`, `e2e_backdate`) и у строки отказа `e2e_reset_stand`; проверка идёт раньше любого чтения базы, Valkey и `fakebots`: тест оборачивает вызов в `django_assert_num_queries(0)` и сверяет, что данные не изменились. Тест включает стенд `monkeypatch.setenv("E2E_STAND", "1")` | T-4131 test_e2e_notify_tick_refused_without_e2e_stand; для `e2e_notify_fill` — T-4142…T-4149 через помощник приёмки |
| Соединения | тесты команд идут с обычным `django_db` (соединения `migrate` нет): команды пишут в базу через `default` | T-4131 |
| Вывод | одна строка в `stdout`, заканчивается переводом строки; формат — по таблицам ниже; адреса почты, тексты уведомлений и значения ключей в строку не попадают | T-4131 |
| Код выхода | 0 — выполнено; отказ — `CommandError` (1); неверный аргумент разбора (не число и подобное) — 2 | T-4131 |
| Запуск с хоста | приёмка запускает команды в службе `standtools` (у неё `E2E_STAND=1`, `env_file: .env`, значит те же `TELEGRAM_API_BASE`, `MAX_API_BASE` и соединение `migrate`), шаблон команды — `helpers_sd._stand_prefix()` (переменная `E2E_STAND_CMD`); новые помощники приёмки `helpers_notify.py` (T-4140) зовут `helpers_sd._stand_command("e2e_notify_tick", …)` и `("e2e_notify_fill", …)`; имена этих помощников пишет T-4140 | T-4140 |
| Браузеры приёмки | в фикстуре `browser` (`tests/e2e/conftest.py`, правка T-4138 п. 17) круги `chromium` и `edge` запускаются с `ignore_default_args=["--disable-background-networking"]` (иначе подписка Google не работает, plan.md:1305-1308), остальные аргументы прежние; круг `firefox` не меняется; `helpers_notify` своего запуска браузера не заводит (решение E23) | T-4138, T-4140, T-4144 |

### 8.2. Команды

| Команда | Командная строка | Что делает и что выводит | Тесты |
|---|---|---|---|
| `e2e_notify_tick` | `e2e_notify_tick [--shift N] [--age-codes M] [--age-days D] [--retention]`; `N`, `M`, `D` — целые от 1 (`N`, `M` — минуты, не больше 525600; `D` — дни, не больше 36500); 0, отрицательное число или больше предела — `CommandError` | Выполняет **обход**, а не задания: сначала режимы сдвига (в таком порядке: `--age-days`, `--age-codes`, `--shift`), затем всегда `tasks.notify_tick()` (`delivery.tick()`, 6.9), затем, если задан `--retention`, `tasks.notify_retention()` (`retention.run()`). Поставленные обходом задания (`send_delivery`, `build_digest`) команда сама не выполняет: их берёт `worker-notify` стенда; письма обход ставит в очередь `mail` (их шлёт `worker-mail`). Сдвиги — прямой записью `update` без `save()` по **всем** строкам (стенд один; ограничения по сотруднику нет): `--shift N` — у доставок `state="waiting"` с непустым `due_at`: `due_at -= N минут`, `enqueued_at = None` (иначе шаг (2) обхода не переставил бы доставку раньше `REQUEUE_AFTER_SECONDS`); `held`, `digest_due_at` не трогает (решение C1: срок сводки приёмка доводит сменой режима на «Без тихих часов» — `replan_digest` ставит «сейчас» — или своими часами вокруг текущего времени, а значение `digest_due_at` проверяет чтением базы через `helpers.stand_shell`; решение E23); `--age-codes M` — `BindCode.expires_at -= M минут` у всех кодов; `--age-days D` — `Notification.created_at` и `Digest.created_at` назад на `D` суток и у всех доставок непустые `due_at`, `enqueued_at`, `lease_until` на столько же (срок 24 часа в `next_due` считается от сдвинутого создания). Вывод: `notify_tick: shifted=<число доставок> aged_codes=<число кодов> aged_rows=<число уведомлений и сводок> emails=<число> released=<число> requeued=<число> digests=<число> codes=<число>` (ключи `emails`, `released`, `requeued`, `digests`, `codes` — словарь `tick`, 6.9); при `--retention` строка дописывается ` retention_notifications=<число> retention_digests=<число> retention_codes=<число> retention_botchats=<число>` (словарь `retention.run()`); режим не задан — соответствующее число `0` | T-4131 test_e2e_notify_tick_shift_moves_waiting_deliveries_back_and_runs_tick_when_e2e_stand; T-4140 (`--shift 5`), T-4146, T-4149 (`--retention`), T-4150 (`--age-days`) |
| `e2e_notify_fill` | `e2e_notify_fill ПОЧТА N [--read K]`; `ПОЧТА` — рабочий адрес сотрудника (`User.email`, без учёта регистра); `N` — целое от 1 до 1000; `K` — целое от 0 до `N`, по умолчанию 0 | Создаёт сотруднику `N` уведомлений напрямую (`Notification.objects.bulk_create`), без доставок, без событий шины и без записи в журнал: вид — `core.password_changed` (решение C2: код всегда есть в каталоге, ядро не зависит от других модулей), `text` — «Тестовое уведомление <i>» (`i` от 1 до `N`), `url` — `/notifications/`, `object_ref` — `""`; `created_at = сейчас − (N − i) секунд` (больше номер — новее, порядок на странице «новые сверху» детерминирован); `K` самых старых (`i` от 1 до `K`) созданы прочитанными (`read_at = created_at`). После создания зовёт `live.push([user.pk])` (открытые вкладки получают новое число; сбой слоя каналов — предупреждение, не отказ). Сотрудник не найден — `CommandError("Сотрудник с таким адресом не найден.")` (адрес в текст не входит). Вывод: `notify_fill: created=<N> read=<K> unread=<N-K>` | T-4149 (пункты 10.1 и 10.4) |
| `notify_vapid_keys` | без аргументов; **не** защищена `E2E_STAND` (решение 21 задач: Opus запускает её в контейнере для пары VAPID стенда; решение C3) | Печатает в `stdout` ровно две строки, каждая с переводом строки, в таком порядке: `VAPID_PRIVATE_KEY=<base64url без дополнения, 32 байта (43 знака)>` и `VAPID_PUBLIC_KEY=<base64url без дополнения, 65 байт (87 знаков), первый байт 0x04>` — значения даёт `crypto.generate_vapid_keys()` (5.3); других строк (заголовков, подсказок) нет, `stderr` пуст; каждый запуск — новая пара. Открытый ключ вычисляется из закрытого (тест выводит открытый ключ из напечатанного закрытого и сравнивает). Ничего не читает и не пишет в базе и Valkey (`django_assert_num_queries(0)`), журнал не трогает (`AuditEvent.objects.count()` до и после равно), `NotifySettings` не меняет, значения в журнал приложения (логгеры) не пишет. Тест не печатает значения и в сообщениях проверок пишет только `***` | T-4130 test_vapid_keys_command_prints_pair_for_env, test_vapid_keys_command_writes_nothing_to_journal_or_database |
| `notify_poll` | без аргументов; не защищена `E2E_STAND`; служба `notify-poller` запускает `python manage.py notify_poll` | Запуск: два потока, `notify-poll-telegram` и `notify-poll-max`; каждый ведёт цикл `run_loop` (решение E5): `started = False`; на каждом шаге — канал не активен (`bots.active`) — `started = False` и ожидание `bots.PAUSE_IDLE`; иначе, если `started` ложно, `started = bots.start_cycle(канал)`; затем `pause = bots.poll_once(канал)` и ожидание `pause` секунд (`stop.wait(pause)`: ожидание прерывается сигналом остановки). Остановка: сигналы `SIGTERM` и `SIGINT` взводят общее событие остановки; потоки дочитывают текущий шаг (запрос ожидает до 25 с, сокет — до 40 с, раздел 5.1) и выходят; процесс завершается кодом 0. Сбой шага вне адаптера (`poll_once` сам ловит ошибки адаптеров, 5.4; исключение `handle_update` он пропускает наружу, решение E18) не убивает поток: он записывается в логгер и поток после паузы `bots.PAUSE_ERROR` продолжает (выбор контракта). Журнал приложения (логгер `apps.notify.management.commands.notify_poll`): при старте потока — `INFO` с названием канала; при сбое — `WARNING` с названием канала и именем класса исключения; токенов, адресов запросов, текстов ответов нет (NFR-312). Записи в журнал событий (`AuditEvent`) команда не делает. Модульная точка проверки: функция модуля `run_loop(channel: str, stop: threading.Event) -> None` — тело потока; тест подменяет `bots.active`, `bots.start_cycle` и `bots.poll_once` записывающими фальшивками, запускает два потока с двумя каналами и проверяет, что пауза одного не задерживает другой. Сам запуск процесса и сигналы модульными тестами не проверяются: их проверяют тест развёртывания (команда службы, одна копия, раздел 1.3) и стенд | T-4120 test_loops_of_two_bots_run_independently, test_loop_idles_when_channel_disabled_or_token_missing; T-4130 test_compose_has_notify_poller_single_replica_with_notify_poll_command |

### 8.3. Сброс стенда: точка `stand_reset` среза

Команда ядра `e2e_reset_stand` зовёт функции точки `stand_reset` в обратном порядке регистрации
(CONTRACT-003, 8.3). Приложения регистрируют точки в порядке `INSTALLED_APPS` (`org`,
`servicedesk`, `notify`), поэтому функция `notify` идёт **первой** при сбросе, раньше `servicedesk`
и
`org` (данные `notify` ссылаются на сотрудников, но не держат `PROTECT`-ссылок на узлы). Функция
среза — `apps.notify.stand.stand_reset()`, без аргументов, регистрируется в
`apps/notify/extensions.py`; работает через соединение `migrate`, если оно настроено (как
`apps.servicedesk.stand.stand_reset`), иначе через `default`. Общая очистка таблиц ядра с каскадом
(`TRUNCATE … CASCADE`) уже стёрла часть таблиц среза, ссылающихся на `core_user`, поэтому функция не
рассчитывает на их строки. Результат — состояние после миграций (2.3), кроме `BotState`:

| Что | Результат | Тесты |
|---|---|---|
| Данные среза | стёрты все строки `Delivery`, `Notification`, `Digest`, `PushSubscription`, `ChatBinding`, `BindCode`, `BotChat`, `UserNotifySettings` (доставки — раньше уведомлений и сводок) | T-4131 test_stand_reset_of_notify_clears_slice_data |
| Настройки | `NotifySettings` пересоздана: одна строка `pk=1` со значениями миграции данных (2.3: каналы выключены, 15 минут, 90 дней, `defaults={}`, `channel_status={}`) | T-4131 test_stand_reset_of_notify_clears_slice_data |
| `BotState` | строки **не удаляются** (имя бота остаётся до следующего старта цикла: сброс выключает каналы, и `start_cycle` позовётся снова, когда приёмка их включит, решение E5): у каждой строки `cursor = ""` и `last_error = ""`, `bot_username` остаётся (решение C10) | T-4131 test_stand_reset_of_notify_clears_presence_in_valkey_and_polling_cursors |
| Присутствие | в Valkey удалены ключи `notify:online:*` (`scan_iter(match="notify:online:*")` и `delete`); прочие ключи (в том числе `crm-asgi:*` слоя каналов и `rq:*`) не тронуты (7.4, решение 25 задач) | T-4131 test_stand_reset_of_notify_clears_presence_in_valkey_and_polling_cursors |
| Очередь | `django_rq.get_queue("notify").empty()`; очереди `mail`, `maintenance` и прочие не трогает | T-4131 test_stand_reset_of_notify_clears_slice_data |
| `fakebots` | `POST <база>/_test/reset` (1.2), где база — `settings.TELEGRAM_API_BASE` (одна служба отвечает и за Telegram, и за MAX); вызов делается **только если адрес не равен `https://api.telegram.org`** (иначе на установке с настоящим Telegram сброс обратился бы к чужой службе — решение C11); тайм-аут 5 с; сбой сети или ответ не 200 — `WARNING` в логгер `apps.notify.stand` без адреса и токена, сброс не отказывает | T-4131 test_stand_reset_of_notify_resets_fakebots |

Тесты сброса помечаются `pytest.mark.django_db(databases=["default", "migrate"])`; данные, которые
функция должна увидеть, тест создаёт через соединение `migrate` (`Model.objects.using("migrate")`),
результат читает так же. Тест подменяет `settings.TELEGRAM_API_BASE` значением из окружения службы
`test` (`http://fakebots:8099`) и ставит событие в `fakebots` помощником `FakeBots.put_telegram`
(раздел 1.1). Тест вызывает не только саму функцию, но и команду: `monkeypatch.setenv("E2E_STAND",
"1")` и
`call_command("e2e_reset_stand")`.

Приёмка (T-4140…T-4151): круг начинается с `helpers_sd.reset_stand_and_relogin()` (CONTRACT-003,
8.3), которая зовёт `e2e_reset_stand` и тем самым точку `notify`.

## 9. Журнал

Запись — `apps.core.services.audit.record(action, *, actor=None, object_type, object_id, before,
after, ip)` (раздел 6.1). Писать их могут только сервисы раздела 6 (`settings`, `prefs`, `binding`,
`push`, `cleanup`); в той же транзакции, что и изменение. Остальные правила — как в 9.1
CONTRACT-003.

### 9.1. Общие правила

- `actor` — сотрудник или администратор, выполнивший действие; у действий системы (отказ
  push-сервиса, выход, увольнение, событие бота, перенос подписки, предел подписок) — `None`; `ip`
  — адрес запроса у действий в интерфейсе, `None` у системных и у действий по событию бота;
- `object_type` — латинский код вида объекта, русское название — `OBJECT_TYPES` файла
  `apps/notify/audit_labels.py`; `object_id` — строка;
- у личных событий (`notify.user_settings_changed`, `notify.channel_*`, `notify.push_*`)
  `object_type="user"` (вид объекта ядра «сотрудник», `notify` его не переопределяет), `object_id` —
  номер сотрудника, которому принадлежат настройка, привязка или подписка (решение C4);
- у настроек администратора `object_type="notify_settings"` («настройки уведомлений»),
  `object_id="1"`;
- `before`, `after` — словари; ключи только из таблицы ниже; пустой словарь допустим; ключей
  `url`, `link`, `code`, `codes`, `token`, `key`, `secret` в записях нет (их значения журнал
  заменяет
  на `***`, `SECRET_FIELDS` в `apps/core/services/audit.py`); у ключа действия сотрудника `reason`
  нет
  (есть только у действий системы);
- в записях **нет**: текстов уведомлений и писем, идентификаторов чатов Telegram и MAX (ни как
  ключа, ни как значения), адресов подписок Web Push, ключей `p256dh` и `auth`, ключей VAPID,
  токенов
  ботов, кодов привязки и их хешей, адресов почты;
- сами уведомления, доставки, сводки, сообщения ботов, отметки «прочитано», ошибки каналов
  (`channel_status`), чистка кодов и ночное удаление в журнал не пишутся (FR-341, FR-333);
- русские названия — `ACTIONS`, `FIELDS`, `OBJECT_TYPES`, `VALUES` файла
  `apps/notify/audit_labels.py`; функция `audit_labels()` возвращает
  `{"actions", "fields", "object_types", "values"}` и регистрируется в точке `audit_labels` (3.1);
  каждый записываемый ключ (и ключ вложенного словаря) имеет русскую подпись (решение 29 задач,
  `test_audit_every_written_key_has_russian_label`);
- ключи не должны менять смысл ключей других модулей: `channel` и `reason` берутся с тем же смыслом,
  что у `servicedesk` и ядра, а их `VALUES` дополняются (внутренние словари `values` объединяются);
  таблица `table` у `servicedesk` не используется — у `notify` ключ называется `cells`.

### 9.2. Коды событий журнала

Шесть кодов таблицы плана «Журнал». Тесты: T-4129 (`test_notify_audit.py`), там же, где указано в
разделе 6.

| Код (русское название в `ACTIONS`) | Объект | Кто | `before` | `after` | Пишет |
|---|---|---|---|---|---|
| `notify.settings_changed` («Настройки уведомлений изменены») | `notify_settings`, `"1"` | администратор (`actor`), `ip` запроса | только изменившиеся поля: `webpush_enabled`, `telegram_enabled`, `max_enabled` (bool), `email_delay_minutes`, `retention_days` (целые) и `defaults` (словарь «<название вида> → список каналов (`email`, `push`, `telegram`, `max`) или `null`», только по видам, чьи каналы изменились; `null` — вида не было в словаре, действовали каналы вида; решение C5) | те же ключи с новыми значениями; значения ключей и токенов нет; ничего не изменилось — записи нет | `settings.update` (6.5) |
| `notify.user_settings_changed` («Личные настройки уведомлений изменены») | `user`, номер сотрудника | сам сотрудник, `ip` запроса | только изменившееся: `cells` (словарь «<название вида> → список включённых внешних каналов в порядке каталога», по изменённым видам; без `portal`), `quiet_mode` (`calendar`, `own`, `none`), `own_days` (список целых 0-6), `own_start`, `own_end` (строки `ЧЧ:ММ`) | те же ключи с новыми значениями; нет изменений — записи нет | `prefs.save` (6.4): одна запись на сохранение |
| `notify.channel_bound` («Канал уведомлений привязан») | `user`, номер сотрудника | сам сотрудник (`actor` — он), `ip=None` (привязка идёт событием бота) | `{"bound": false}`; при замене привязки другим чатом — `{"channel": "<канал>", "bound": true}` | `{"channel": "telegram"\|"max", "bound": true}`; без `chat_id` | `binding.bind` (6.13) |
| `notify.channel_unbound` («Канал уведомлений отвязан») | `user`, номер сотрудника | сам сотрудник — вручную (`ip` запроса); система (`actor=None`) — `bot_unavailable` (`ChannelGone`, `kicked`, `bot_stopped`) и `dismissed` | `{"channel": "<канал>", "bound": true}` | `{"bound": false}`, у действий системы ещё `"reason": "bot_unavailable"` или `"dismissed"` (у ручной отвязки ключа `reason` нет) | `binding.unbind` (6.13), `cleanup.on_dismissed` (6.15); привязки не было — записи нет |
| `notify.push_subscribed` («Устройство подписано на push») | `user`, номер сотрудника | сам сотрудник, `ip` запроса | `{}` | `{"browser": "<браузер>", "platform": "<платформа>"}` (`devices.parse_user_agent`); адреса и ключей нет | `push.save` (6.12): пишется при создании подписки или переносе адреса с другой учётной записи; обновление ключей уже существующей подписки того же сотрудника записи не даёт (решение C6) |
| `notify.push_removed` («Подписка push удалена») | `user`, номер **владельца** удалённой подписки | сам сотрудник — `push.delete` (`ip` запроса); система (`actor=None`) — `push.drop` | `{"browser": "<браузер>", "platform": "<платформа>"}` удалённой подписки | `{}` у удаления сотрудником; у системы `{"reason": "<код>"}` — `gone` (ответ 404 или 410), `logout` (выход из портала), `dismissed` (увольнение), `moved` (адрес перенесён на другую учётную запись; объект — прежний владелец), `limit` (больше 10 подписок; удаляется самая старая) | `push.delete`, `push.drop`, `push.save`, `push.on_logged_out`, `cleanup.on_dismissed` |

Названия значений (`VALUES`): `quiet_mode` — `calendar` «по рабочему календарю компании», `own`
«свои часы», `none` «без тихих часов»; `channel` дополняется `telegram` «Telegram», `max` «MAX»
(`mail`, `form`, `staff` — прежние, `servicedesk`); `reason` дополняется `bot_unavailable` «бот
недоступен», `dismissed` «увольнение», `gone` «подписка недействительна», `logout` «выход из
портала», `moved` «подписка перенесена на другую учётную запись», `limit` «больше десяти подписок»
(прежние `manual`, `transfer`, `dismissal` не переопределяются; `dismissal` у `org` и `dismissed` у
`notify` — разные значения). Названия полей (`FIELDS`): `webpush_enabled` «Web Push включён»,
`telegram_enabled` «Telegram включён», `max_enabled` «MAX включён», `email_delay_minutes` «срок до
письма, минут», `retention_days` «срок хранения уведомлений, дней», `defaults` «значения по
умолчанию», `cells` «ячейки таблицы», `quiet_mode` «тихие часы», `own_days` «дни своих часов»,
`own_start` «свои часы: с», `own_end` «свои часы: до», `bound` «привязан», `browser` «браузер»,
`platform` «платформа» (ключи `channel`, `reason` уже имеют названия в других модулях и не
повторяются). `OBJECT_TYPES`: `notify_settings` «настройки уведомлений». Имя действия
`notify.channel_unbound` совпадает с кодом вида уведомления `notify.channel_unbound` (3.2): это
разные пространства имён (журнал и каталог видов).

Тесты не должны находить запись по тексту: они читают `AuditEvent.objects.filter(action=…)`.
Дополнительно T-4129: журнал только дописывается (роль приложения не имеет UPDATE и DELETE),
ночное удаление `retention.run()` и чистка кодов записей журнала не трогают.

## 10. Письма

Письма уведомлений идут через `mail.queue_item` и `mail.queue_digest` (6.10) и `send_rendered`
почтового модуля (очередь `mail`); тело собирает рендерер `notify` в момент отправки (`mail.render`,
префикс `notify.`).

### 10.1. Шаблоны, заголовки и поля `MailMessage`

| Что | Значение | Тесты |
|---|---|---|
| Шаблоны | ровно два: `notify.item` (одно уведомление) и `notify.digest` (сводка); файлы текстов — `backend/templates/notify/mail/notify_item.txt` и `notify_digest.txt` (простой текст Django, без автоэкранирования, как `templates/servicedesk/mail/*.txt`) | T-4108, T-4111, T-4112 |
| Кому | `To` — `User.email` сотрудника (рабочий адрес); копии нет (`cc=[]`); `reply_to=""` (заголовок не пишется); `references=""` | T-4111 test_send_rendered_called_with_required_arguments |
| `Subject` у `notify.item` | внешний текст вида (`external_text`, 3.2), например «Новая заявка в вашей очереди»; номера и темы заявки нет (тема попала бы в журнал почты, у которого срока хранения нет) | T-4111 test_subject_is_external_text_without_ticket_number_and_title; T-4108 |
| `Subject` у `notify.digest` | «За нерабочее время: N уведомлений» с числом `Digest.count_email` и склонением по правилу решения 14 задач (форма слова — по разделу 15): `1 уведомление`, `2…4 уведомления`, `5…20 уведомлений`, `21 уведомление`, `22 уведомления`, `25 уведомлений`, `11…14` и `111…114` — «уведомлений», `101 уведомление`; проверяются не меньше трёх форм | T-4112 test_digest_email_subject_declension_by_count |
| `Message-ID` | `mail.message_id_for(delivery_id)`: `email.utils.make_msgid(idstring=f"notify.{delivery_id}", domain=<часть после «@» у email.utils.parseaddr(settings.DEFAULT_FROM_EMAIL)[1]>)`; значение вида `<…>` и оканчивается на `.notify.<номер>@<домен>>` (так `make_msgid` дописывает `idstring`); сохраняется в `MailMessage.message_id` до отправки | T-4111 test_send_rendered_called_with_required_arguments |
| `Auto-Submitted` | `auto-generated` (`MailMessage.auto_submitted`); других служебных заголовков, кроме `X-Portal-Template` (`MailMessage.template`), нет | T-4111 |
| `related_ref` | `notify.delivery:<номер доставки>` (не длиннее 64 знаков); у сводки — номер доставки сводки (`Delivery(digest, email)`) | T-4111, T-4112 |
| `attachments` | `[]` | T-4111 |
| Контекст задания | `context={"delivery": <номер доставки>}`; `job.meta["context"]` в очереди `mail` равен `{"delivery": <номер>}` (после `public_context`; ключей `url`, `link`, `code`, `token`, `password` нет — они вошли бы в `SECRET_CONTEXT`, а текст и номер заявки в Valkey не попадают) | T-4111 test_job_context_contains_only_delivery_number |
| `MailMessage.mail_id` доставки | номер `MailMessage` (6.10) | T-4111, T-4112 |
| Как тест читает письмо | **текст** — вызовом `mail.render(MailMessage.objects.get(pk=delivery.mail_id), {"delivery": delivery.pk}).body` (рендерер — чистая функция чтения базы; тест сверяет строки тела по порядку); **заголовки и доставку** (`Auto-Submitted`, `Message-ID`, адрес, `X-Portal-Template`) — через Mailpit фикстурой `mailpit` после `support_mail.deliver()` (как в T-3118); постановку и аргументы `send_rendered` — подменой `apps.integrations.mail.services.send_rendered` записывающей функцией (модуль `notify.services.mail` импортирует модуль почты и зовёт `mail_services.send_rendered(...)`, а не импортирует имя; решение E13) или чтением `MailMessage`; приёмка читает письма из Mailpit (`helpers.wait_mail`) | T-4108, T-4111, T-4112, T-4140 |

### 10.2. Тело письма (выбор контракта; тексты — не из спеки, решение C7)

`mail.render(message, context)` берёт данные из базы в момент вызова. Угловые скобки — подстановки;
пустая строка между блоками — одна. `<PORTAL_URL>` — `settings.PORTAL_URL` без завершающего `/`.
Название портала — `PortalSettings.name`.

`notify.item` — строки тела по порядку:
1. `<название портала>`
2. пустая строка
3. `<Notification.text>` (полный текст уведомления, с номером и темой заявки: в теле их можно, в
   теме
   и в `job.meta` нельзя)
4. пустая строка
5. `Открыть: <PORTAL_URL>/notifications/<id>/open/`
6. пустая строка
7. `Настроить уведомления: <PORTAL_URL>/me/notifications/`

`notify.digest` — строки тела по порядку:
1. `<название портала>`
2. пустая строка
3. `За нерабочее время: <N> <уведомление|уведомления|уведомлений>:` (заголовок списка; форма — как
   в теме)
4. по одной строке на уведомление: `<Notification.text> — <PORTAL_URL>/notifications/<id>/open/`
5. пустая строка
6. `Все уведомления: <PORTAL_URL>/notifications/`
7. `Настроить уведомления: <PORTAL_URL>/me/notifications/`

В список сводки входят уведомления из `Digest.notification_ids`, у которых есть доставка `email` в
состоянии `digested` (то есть вошедшие в письмо), по порядку `(created_at, id)`; уже удалённые
строки
(срок хранения, повторный приём) пропускаются; `N` — число оставшихся строк (при удалении части
уведомлений письмо честно меньше темы, выбор контракта).

Нейтральный текст (`Notification` или `Delivery` уже удалены; у сводки — не осталось ни одной строки
списка), тело по порядку: `<название портала>`, пустая строка, `Уведомление больше недоступно.`,
пустая строка, `Все уведомления: <PORTAL_URL>/notifications/`. Тема в этом случае остаётся прежней
(она сохранена в `MailMessage.subject` при постановке).

В теле писем нет паролей, кодов привязки, токенов и ссылок входа (FR-316).
Тест: T-4111 test_renderer_reads_text_from_database_at_send_time,
test_renderer_neutral_text_when_notification_deleted;
T-4112; T-4108.

## 11. Соединение `/ws/notify/`

### 11.1. Путь, Origin, проверки

| Что | Требование | Тесты |
|---|---|---|
| Путь | `apps/notify/routing.py`: `websocket_urlpatterns = [path("ws/notify/", NotifyConsumer.as_asgi())]`; обработчик `NotifyConsumer(AsyncWebsocketConsumer)` в `apps/notify/consumers.py`; приложение для тестов — `config.asgi.application` (весь маршрутизатор с проверкой Origin и сессией, раздел 1.3) | T-4122 |
| Origin | проверяет `AllowedHostsOriginValidator` по `ALLOWED_HOSTS` до обработчика: нет заголовка `Origin` или хост чужой — соединение закрывается до `accept` (в `ApplicationCommunicator`: первый ответ приложения — `websocket.close`, без `websocket.accept`; помощник возвращает «отказ», 11.4) | T-4122 test_connect_without_origin_is_refused, test_connect_with_foreign_origin_is_refused |
| Подключение | (1) `state = await database_sync_to_async(sessions.ws_state)(scope["session"], scope["user"])` (3.4); (2) `state != "ok"` — `await accept()`, затем `await close(code=4401)` (решения 22 и 35 задач; расширение `ws` после 4401 не переподключается); (3) `"ok"` — `accept`, `group_add("notify.u.<id>", channel_name)` (имя группы — `live.group(id)`, 6.8), `live.mark_online(user_id, channel_name)`, отправка кадра с текущим числом (11.3), запуск фоновой проверки (11.2) | T-4122 test_connect_without_session_accepts_then_closes_with_4401, test_connect_with_foreign_session_closes_with_4401, test_connect_with_idle_expired_session_closes_with_4401, test_connect_without_second_factor_closes_with_4401, test_connect_with_expired_password_closes_with_4401, test_connect_sends_current_unread_count_and_resends_after_reconnect |
| Отключение | отмена фоновой проверки, `group_discard`, `live.mark_offline(user_id, channel_name)` (убирает только это соединение; другие вкладки остаются) | T-4122 test_presence_removed_after_disconnect_and_stays_with_other_tab |
| Сообщения клиента | `receive` игнорирует любые входящие кадры; `sessions.touch` не зовёт и строку `UserSession` не меняет | T-4122 test_message_over_socket_does_not_extend_session_idle_time |

### 11.2. Проверка раз в 25 секунд: `CHECK_INTERVAL`

| Что | Требование | Тесты |
|---|---|---|
| Константа | `CHECK_INTERVAL = 25` (секунды, `int` или `float`) — **константа модуля** `apps/notify/consumers.py` (выбор контракта; решение 35 задач допускает атрибут класса или модуля — берётся модуль). Обработчик читает её при **каждом** ожидании как `consumers.CHECK_INTERVAL` (через модуль, а не `from … import`), не один раз при подключении | T-4122 test_check_every_25_seconds_closes_socket_after_logout |
| Как помощник подменяет | `monkeypatch.setattr("apps.notify.consumers.CHECK_INTERVAL", 0.2)` до подключения; тест ждёт ближайшей проверки (`wait_close(timeout=2.0)`), а не 25 секунд | T-4122 test_check_every_25_seconds_closes_socket_after_logout, test_check_closes_socket_after_logout_from_all_devices, test_check_closes_socket_after_idle_expiry, test_check_closes_socket_on_next_tick_after_password_change |
| Что делает проверка | каждые `CHECK_INTERVAL` секунд: `live.mark_online(user_id, channel_name)` (обновить отметку, 7.4), затем `ws_state`; не `"ok"` — `await close(code=4401)` (как при подключении; расширение `ws` после 4401 не переподключается, тесты `test_check_*` сверяют код 4401); `"ok"` — ничего не отправляет | T-4122 |
| Долгое ожидание | соединение без сообщений остаётся открытым дольше 10 секунд, и проверка не закрывает здоровое соединение (`CHECK_INTERVAL` остаётся 25) | T-4122 test_idle_connection_without_messages_stays_open_longer_than_10_seconds |
| 100 соединений | сто одновременных соединений одного процесса получают по кадру с числом; слой каналов не исчерпывает пул (раздел 1.3) | T-4122 test_100_concurrent_connections_in_one_process_get_count |

### 11.3. Сообщения сервера (кадры HTML)

Сообщение слоя каналов `{"type": "notify.update", "count": int, "toast": dict | None, "binding":
"telegram" | "max" | None}`
(6.8) обрабатывает метод `notify_update(self, event)`: он отправляет клиенту **один** текстовый
кадр,
склеенный из фрагментов в таком порядке: фрагмент числа, фрагмент системного уведомления (если
`toast` задан), блок привязки (если `binding` задан). При подключении клиенту отправляется один кадр
только с фрагментом числа. Сообщения клиента не нужны, другого направления нет. Каждый фрагмент —
корневой элемент с `hx-swap-oob="true"` и своим `id` (расширение `ws` заменяет элемент страницы с
тем
же `id`; без `id` на странице вставка молча пропала бы); значения атрибутов и текст экранирует
шаблон Django (NFR-311). Решение 22 задач: у фрагментов нет `role="status"` и `role="alert"`,
атрибутов `data-error` и `data-warning`.

| Фрагмент | Разметка и значения | Тесты |
|---|---|---|
| Число | `<span id="notify-count" hx-swap-oob="true" data-count="<N>" …>…</span>`: `data-count` — точное число непрочитанных (целое, `0` включительно); текст внутри — `<N>`, при `N` больше 99 — `99+`; при `0` элемент остаётся, скрыт классом (имя класса и остальные атрибуты шапки — раздел 14, часть d; тест находит фрагмент по `id` и читает `data-count` и текст) | T-4122 test_connect_sends_current_unread_count_and_resends_after_reconnect; T-4109 test_group_fragment_carries_new_count; T-4124 |
| Системное уведомление | `<div id="notify-toast" hx-swap-oob="true" data-text="<текст>" data-url="/notifications/<id>/open/" data-tag="n-<id>" data-show="1"></div>`: `data-text` — `Notification.text`, `data-url` — путь открытия уведомления, `data-tag` — `n-<id>`, `data-show` — `1` или `0` (6.7: `1`, если у вида включена ячейка `push` получателя и сейчас не тихие часы); у видов `mandatory` — `0`; элемент пустой (без содержимого); значения тест читает после разбора разметки и не находит в сыром кадре неэкранированных `<`, `>`, `"` | T-4122 test_push_sends_toast_fragment_with_text_url_and_tag, test_toast_shown_flag_on_when_browser_push_kind_enabled_and_not_quiet, test_toast_shown_flag_off_when_browser_push_disabled_or_quiet_hours, test_toast_values_are_html_escaped; T-4109 test_group_fragment_data_show_* |
| Блок привязки | `<div id="notify-binding-<канал>" hx-swap-oob="true">…</div>`, канал — `telegram` или `max`; корень — тот же элемент, что у блока привязки страницы «Мои уведомления» (идентификатор `notify-binding-<канал>`, разметка внутри блока — раздел 14, часть d; сервер собирает его тем же шаблоном блока для получателя сообщения, состояние «Привязан» или «Не привязан» читается из базы при отправке кадра); решение C8 | T-4118 test_binding_block_is_pushed_to_user_group_after_bind |

Разбор кадров в тестах — стандартный `html.parser.HTMLParser` (как в других тестах проекта),
помощник
`support_notify.ws_fragments(frame) -> dict[str, Fragment]` (ключ — `id` корня; `Fragment` —
`NamedTuple` `tag`, `attrs: dict[str, str]`, `text`).

### 11.4. Помощник тестов на `ApplicationCommunicator`

Решение 6 задач: `asgiref.testing.ApplicationCommunicator`, тест ведёт его через `async_to_sync` из
своего потока, чтобы `database_sync_to_async` обработчика шёл в потоке теста и видел его данные
(`transaction=True` в проекте не работает). Каждый вызов `async_to_sync` по отдельности создаёт свой
цикл событий, а `ApplicationCommunicator` привязан к циклу, где создан, поэтому **весь сценарий
теста
с соединением идёт одним вызовом `async_to_sync`** (решение C9). Помощники пишет T-4100 в
`tests/support_notify.py`:

| Имя | Подпись и поведение | Тесты |
|---|---|---|
| `ws_run` | `ws_run(scenario, *, timeout: float = 60.0) -> object`: `async_to_sync(scenario)(hub)`, где `scenario` — `async def scenario(hub)`; `hub` — `WsHub`; по выходу (в том числе по исключению) все открытые соединения отключаются и их приложения дожидаются | T-4122, T-4109, T-4118, T-4124 |
| `WsHub.connect` | `await hub.connect(client=None, *, origin: str \| None = "http://testserver", cookie: str \| None = None, path: str = "/ws/notify/") -> WsClient`: собирает `scope` (`type="websocket"`, `path`, `raw_path`, `query_string=b""`, `headers` — `host: testserver`, `origin` (если не `None`), `cookie` (если есть), `client`, `server`, `scheme="ws"`, `subprotocols=[]`), создаёт `ApplicationCommunicator(config.asgi.application, scope)`, посылает `websocket.connect` и ждёт первый ответ не дольше 2 с: `websocket.accept` — `.accepted = True`; `websocket.close` — `.accepted = False`, `.close_code` из ответа (`code` или 1000). Куки: у `client` (Django `Client`, вошедший средствами тестов, так что строка `UserSession` создана) берётся значение `settings.SESSION_COOKIE_NAME` из `client.cookies`; явный `cookie` (строка `имя=значение`) главнее; `client=None` и `cookie=None` — заголовка `cookie` нет | T-4122 |
| `WsHub.do` | `await hub.do(func, *args, **kwargs)`: `sync_to_async(func)(*args, **kwargs)` (в потоке теста); так сценарий создаёт данные, зовёт сервисы и задания (`run_jobs`, `live.push`) между ожиданиями; задание рабочего процесса, которое зовёт `live.push`: `send_delivery` под `fake_bot_send("telegram", raises=ChannelGone)` → `binding.unbind` → `dispatch.create` → `live.push`, `run_jobs()` внутри `django_capture_on_commit_callbacks(execute=True)` (решение E13) | T-4122 test_push_from_rq_worker_reaches_open_socket_within_2_seconds |
| `WsHub.sleep` | `await hub.sleep(seconds)` — `asyncio.sleep` | T-4122 test_idle_connection_without_messages_stays_open_longer_than_10_seconds |
| `WsClient.receive` | `await client.receive(timeout: float = 2.0) -> str \| None`: ждёт следующий вывод приложения (`communicator.receive_output(timeout)`); текстовый кадр (`websocket.send`, ключ `text`) возвращает строкой; `websocket.close` запоминает в `.close_code` и возвращает `None`; тайм-аут (`asyncio.TimeoutError`) — `None` (так тест видит «кадра нет»); перед каждым ожиданием проверяет, не завершилось ли приложение с исключением, и поднимает его | T-4122, T-4109 |
| `WsClient.wait_close` | `await client.wait_close(timeout: float = 2.0) -> int \| None`: читает выводы, пропуская текстовые кадры, до `websocket.close`; возвращает `code` (или 1000, если ключа нет) либо `None` по тайм-ауту | T-4122 |
| `WsClient.send` | `await client.send(text: str)`: `websocket.receive` с `text` | T-4122 test_message_over_socket_does_not_extend_session_idle_time |
| `WsClient.disconnect` | `await client.disconnect()`: `websocket.disconnect` с кодом 1000 и ожидание завершения приложения (до 2 с) | T-4122 |
| Поля | `.accepted: bool`, `.close_code: int \| None` | T-4122 |
| `ws_fragments` | см. 11.3 | T-4122, T-4109, T-4118 |

Тест заранее подменяет `CHECK_INTERVAL` (11.2) и читает присутствие `live.is_online` через
`hub.do`. Два медленных теста (11 секунд простоя и сто соединений) идут только в T-4122.

## 12. Что меняется в прежних контрактах

Перечень T-4138, п. 18 (impact.md, п. 11). Сами файлы не правятся этой частью: их правит T-4138
(второй заход, пп. 13-18) с разрешения владельца по диффу. Номера строк сверены командами
`sed -n` и `grep -n` 2026-10-10 по состоянию файлов после T-3138 (строки на месте; в
`CONTRACT-002.md` и `CONTRACT.md` часть правок среза 003 уже внесена, поэтому «Было» — то, что в
файле сейчас). Длинные ячейки даны выдержкой «…»; T-4138 берёт полный текст из файла дословно.
«Стало»
согласовано с разделами 1-7 и 11 этого контракта.

### 12.1. `CONTRACT.md`

| Строка | Было | Стало |
|---|---|---|
| 199 | `\| `deploy/docker-compose.yml` \| сервисы `web`, `worker`, `worker-mail`, `worker-inbox`, `scheduler`, `backup`, `nginx`, `postgres`, `valkey`, `mailpit`, `dovecot`; `profiles: ["dev"]` только у `mailpit`, `profiles: ["dev", "test"]` у `dovecot`; … `worker-inbox`: то же с очередью `inbox` (раздел 1 CONTRACT-003); `scheduler`: … \|` | в перечне служб после `worker-inbox` добавлены `worker-notify`, `notify-poller`, после `dovecot` — `fakebots`; к `profiles: ["dev", "test"]` у `dovecot` добавлено «и у `fakebots`»; после «`worker-inbox`: то же с очередью `inbox`» — «`worker-notify`: то же без `--with-scheduler` с очередью `notify`, две копии; `notify-poller`: `python manage.py notify_poll`, одна копия (раздел 1.3 CONTRACT-004)»; в конце ячейки — «`location /ws/` в `nginx.conf` и `nginx.prod.conf` (раздел 1.3 CONTRACT-004); служба `test` ждёт `fakebots`»; остальной текст ячейки прежний |
| 311 | `  Рабочие процессы: `rq worker -c config.rq_settings --with-scheduler` с очередями `files` (`worker`), `mail maintenance` (`worker-mail`) и `inbox` (`worker-inbox`),` | `  Рабочие процессы: `rq worker -c config.rq_settings --with-scheduler` с очередями `files` (`worker`), `mail maintenance` (`worker-mail`) и `inbox` (`worker-inbox`), `rq worker -c config.rq_settings notify` (`worker-notify`, без `--with-scheduler`), опрос ботов — `python manage.py notify_poll` (`notify-poller`),` |
| 332 | `  `service_completed_successfully`; у web, worker, worker-mail, worker-inbox и scheduler` | `  `service_completed_successfully`; у web, worker, worker-mail, worker-inbox, worker-notify, notify-poller и scheduler` |
| 334 | `  `standtools` и `test`; служба `backup` получает только … у `worker-mail` и `worker-inbox` — `DATABASE_MIGRATE_URL: ""`, как у `worker`. Тест — test_deploy_files::test_owner_credentials_only_in_one_shot_migrate_service (…).` | то же, и после «у `worker-mail` и `worker-inbox`» добавлено «, `worker-notify` и `notify-poller`» (у них `DATABASE_MIGRATE_URL: ""`); тест тот же, его перечень служб не меняется |

Строки 16 (перечень файлов) и 312-313 (расписание) не меняются: файлы среза 004 описывает
`CONTRACT-004.md`, задания среза 004 стоят в разделе 1.3 этого контракта.

### 12.2. `CONTRACT-002.md`

| Строка | Было | Стало |
|---|---|---|
| 5 | `таблицы «Журнал», `perms:<id>`, очередь `files`, девять точек расширения (в срезе 003 их тринадцать, CONTRACT-003 § 3.2), `Unit`, `Membership`,` | `… девять точек расширения (в срезе 003 их тринадцать, CONTRACT-003 § 3.2; в срезе 004 — пятнадцать, CONTRACT-004 § 3.1), `Unit`, `Membership`,` |
| 40 | `\| worker \| команда `rq worker -c config.rq_settings --with-scheduler files` (только очередь `files`), `deploy: replicas: 2`; том `protected` на тот же путь, что у `web` (`/app/protected`); очереди `mail maintenance` и `inbox` — службы `worker-mail` и `worker-inbox` с тем же томом \| …` | то же, и в конце ячейки «Требование» дописано: «очередь `notify` — служба `worker-notify` без тома `protected` (CONTRACT-004 § 1.3); тест среза 001 про `worker` не меняется» |
| 42 | `\| cron \| … срез 003 добавляет восемь заданий (CONTRACT-003 § 1 и 7), всего в файле четырнадцать вызовов `register`; шесть прежних — без изменений \| test_deploy_files::test_cron_registers_preview_purge_quarantine_cleanup_and_scan_requeue (правка — п. (11) T-3138 …) \|` | «… срез 003 добавляет восемь заданий (CONTRACT-003 § 1 и 7), срез 004 — два (`notify_tick`, `notify_retention`, CONTRACT-004 § 1.3), всего в файле шестнадцать вызовов `register`; шесть прежних — без изменений»; тест тот же (правка `== 14` → `== 16` в `test_sd_deploy.py` — п. (12) T-4138; `test_deploy_files.py` не меняется, он проверяет шесть прежних по именам) |
| 127 | `\| `permissions.menu_for` \| уточнение: … Порядок: «Заявки» 5, «Сотрудники» 10, «Структура» 20, «Календарь» 30, «Роли и права» 40, «Журнал событий» 50, «Настройки портала» 60, «Сервис-деск» 65, «Безопасность и политика» 70 … \|` | порядок: «Заявки» 5, «Сотрудники» 10, «Структура» 20, «Календарь» 30, «Роли и права» 40, «Журнал событий» 50, «Настройки портала» 60, «Уведомления» 62, «Сервис-деск» 65, «Безопасность и политика» 70; остальной текст ячейки прежний (пункт «Уведомления» — `/settings/notifications/`, право `notify.manage`, без `badge`; решение 10 задач) |
| 283 | `\| `POINTS` \| кортеж из тринадцати имён (девять прежних по порядку: … `stand_reset` — и `unit_usage`, `file_purposes`, `mail_renderers`, `login_links`, CONTRACT-003 § 3.2); `org` регистрирует … в первых девяти точках; остальные четыре — `servicedesk` \| … \|` | `кортеж из пятнадцати имён (тринадцать прежних по порядку и `notification_kinds`, `top_bar_items`, CONTRACT-004 § 3.1); `org` регистрирует … в первых девяти точках; в `unit_usage`, `file_purposes`, `mail_renderers`, `login_links` — `servicedesk` (и `notify` в `mail_renderers`), в `notification_kinds` — `servicedesk`, ядро и `notify`, в `top_bar_items` — `notify`; тест `test_org_registers_all_nine_extension_points` (п. (1) T-4138: `POINTS_004`, равенство и `all_points` на 15 имён)` |
| 286 | `\| `clear` \| `clear() -> None`: очищает все тринадцать реестров \| test_extensions \|` | `… очищает все пятнадцать реестров …` |
| 633-634 | `3. A8: элемент меню … порядок 5, 10, 20, 30, 40, 50, 60, 65, 70.` | `… порядок 5, 10, 20, 30, 40, 50, 60, 62, 65, 70.` |

Строки 288, 797-800 (`menu_items`, `menu_for`) не меняются: пункт «Уведомления» не вводит новых
ключей
описания.

### 12.3. `CONTRACT-003.md`

| Строка | Было | Стало |
|---|---|---|
| 111 | `\| Очереди RQ \| есть \| `RQ_QUEUES["inbox"]` и `RQ_QUEUES["maintenance"]` в `config/settings.py` (`URL: VALKEY_URL`, `DEFAULT_TIMEOUT: 120`); … \|` | то же, и в конце ячейки «Требование» дописано: «в срезе 004 добавлена очередь `notify` (`RQ_QUEUES["notify"] == {"URL": VALKEY_URL, "DEFAULT_TIMEOUT": 120}`, CONTRACT-004 § 1.3); тест `test_rq_queues_include_inbox_and_maintenance` проверяет только `inbox` и `maintenance` и не меняется» |
| 112 | `\| `config/cron.py` \| Этап 3 \| восемь новых заданий через `register(..., name=...)`; … правка T-3138, п. 11 (…): `== 6` → `== 14` (`test_deploy_files.py:383`); … \|` | то же; в конце ячейки дописано: «в срезе 004 число вызовов `register` — шестнадцать (два новых: `notify_tick`, `notify_retention`, CONTRACT-004 § 1.3); правка п. (12) T-4138 `test_sd_deploy.py::test_cron_has_eight_new_jobs_with_expected_queues_and_poll_mailbox_every_minute`: «ровно 14» → 16, разбор `cron_registrations()` читает и `interval`, таблица `NOTIFY_JOBS`» |
| 113 | `\| `deploy/RESTORE.md` \| Этап 3 \| шаги по порядку (…): остановить `web`, `worker`, `worker-mail`, `worker-inbox`, `scheduler`; … \|` | то же, в шагах остановки и запуска после `worker-inbox` — `worker-notify`, `notify-poller` (CONTRACT-004 § 1.3); тест `test_sd_deploy.py` проверяет подмножество служб и не меняется |
| 238 | `\| `servicedesk.ticket_created`, `servicedesk.assignee_changed`, `servicedesk.reply_received`, `servicedesk.ticket_closed` \| данные у всех четырёх: `number`, `queue_id`, `assignee_before_id`, `assignee_after_id` (…); публикуют модули `servicedesk` (перечень по 6.13). Подписчиков в срезе нет \| … \|` | прежние ключи сохраняются; добавлено: «`actor_id: int \| None` у всех четырёх; `ticket_created` ещё `channel`; `reply_received` ещё `via`, `author_kind`, `entry_id`; новые события `servicedesk.ticket_transferred`, `servicedesk.ticket_reopened`, `servicedesk.reply_not_sent`, `servicedesk.mail_failed`, `object.viewed` (CONTRACT-004 § 3.3 и 4.2); подписчики — `notify` (CONTRACT-004 § 6.1)» вместо «Подписчиков в срезе нет» |
| 244 | `\| `POINTS` \| уточнение CONTRACT-002 § 5: кортеж из тринадцати имён в таком порядке: … `login_links`. `org` по-прежнему регистрируется ровно в девяти первых …; `servicedesk` — в `menu_items`, `unit_usage`, … `stand_reset`, `home_notices` (…) \|` | «кортеж из пятнадцати имён: тринадцать прежних и `notification_kinds`, `top_bar_items` в конце (решение 19 задач, CONTRACT-004 § 3.1); `servicedesk` — ещё в `notification_kinds`; регистрации `notify` и ядра в новых точках — CONTRACT-004 § 3.1»; тест `test_extension_points_include_unit_usage_file_purposes_mail_renderers_login_links`: `POINTS_13` → 15 имён (п. (2) T-4138) |
| 249 | `… «Заявки» — `order` 5; «Сервис-деск» — `order` 65 (решение 10 задач) \| …` | `… «Заявки» — `order` 5; «Уведомления» — `order` 62 (решение 10 задач среза 004); «Сервис-деск» — `order` 65 …` |
| 264 | `\| `PERMISSIONS_003` \| в `tests/support_servicedesk.py`: … у «Администратора портала» после установки — `PERMISSIONS + PERMISSIONS_002 + PERMISSIONS_003` (двенадцать кодов) … \|` | то же, и дописано: «в срезе 004 — тринадцать кодов: `PERMISSIONS + PERMISSIONS_002 + PERMISSIONS_003 + PERMISSIONS_004`, `PERMISSIONS_004 = ("notify.manage",)` в `tests/support_notify.py` (CONTRACT-004 § 2.3); у «Руководителя» и «Сотрудника» нового права нет» |
| 692-706 | раздел `6.13. events`: «ключи данных — те, что раздел 3.1 даёт для четырёх событий …»; таблица: `ticket_created(ticket)`, `assignee_changed(ticket, *, before_id, after_id)`, `reply_received(ticket)`, `ticket_closed(ticket)`; константы четырёх событий | подписи по CONTRACT-004 § 4.2: `ticket_created(ticket, *, actor_id, channel)`, `assignee_changed(ticket, *, before_id, after_id, actor_id)`, `reply_received(ticket, *, via, author_kind, entry_id)`, `ticket_closed(ticket, *, actor_id)` (параметры обязательные, решение 20 задач; вызов без параметра — `TypeError`); к константам добавлены `TICKET_TRANSFERRED`, `TICKET_REOPENED`, `REPLY_NOT_SENT`, `MAIL_FAILED`, `OBJECT_VIEWED`; новые помощники `ticket_transferred`, `ticket_reopened`, `reply_not_sent`, `mail_failed`, `object_viewed`; в строке `register` текст «Подписчиков…» не меняется (`register()` подписывает `access.changed` и `mail.failed`, как раньше); абзац перед таблицей: «ключи данных — по CONTRACT-004 § 4.2 (прежние четыре и новые)» |
| 1086 | `  четырнадцать вызовов `register` (шесть прежних и восемь новых).` | `  шестнадцать вызовов `register` (шесть прежних, восемь новых среза 003 и два среза 004).` |
| 1131-1143 | `### 8.3. … зовёт функции точки `stand_reset` в **обратном порядке регистрации** … данные среза держат `PROTECT`-ссылки на узлы `org`. С одним `org` порядок прежний. …` | после «С одним `org` порядок прежний» дописано: «в срезе 004 порядок регистрации — `org`, `servicedesk`, `notify`, при сбросе — `notify`, `servicedesk`, `org` (CONTRACT-004 § 8.3); данные `notify` не держат `PROTECT`-ссылок на узлы»; остальные строки таблицы не меняются |

Строки 1475-1500 (раздел 11 `CONTRACT-003.md`, перечень T-3138) — история, не правятся. Приёмка
срезов 001-003 не меняется, кроме п. (17) T-4138 (`tests/e2e/conftest.py`).

## 13. Маршруты и поля форм

Части d принадлежат разделы 13-15. Колонка «Тесты» называет серверные файлы
(`test_notify_pages.py` — T-4123, `test_notify_pages_2.py` — T-4124, `test_notify_prefs.py` —
T-4125, `test_notify_prefs_2.py` — T-4126, `test_notify_admin.py` — T-4127) и файлы приёмки
(`e2e/test_e01…e12`). Сервисы, которые зовёт маршрут, — раздел 6; тексты — раздел 15; зацепки
разметки — раздел 14. Таблица маршрутов — «Контракты» плана (plan.md:1087-1119); новых путей
контракт не вводит. Соединение `/ws/notify/` — раздел 11, здесь не повторяется. Правила как в
CONTRACT-003 § 12 («НХ» — запрос HTMX, заголовок `HX-Request: true`):

- все формы — POST с CSRF; без входа любой путь, кроме `/sw.js`, — 302 на `/login/` (с `next`);
  другой метод, чем в таблице, — 405;
- ответ на запрос НХ — фрагмент без `<html>`, на обычный — полная страница;
- **отказ сервиса** (`NotifyError`, код — 6.2) на POST — **всегда 200** с тем же шаблоном (и на
  запрос НХ: HTMX не вставляет ответы 4xx); база не меняется (откат целиком, 6.4-6.5); у отказа
  поля — `[data-error="<error.field>"][data-code="<код>"]` рядом с полем (без роли); у отказа без
  поля — `[role=alert][data-code="<код>"]` страницы или фрагмента. Это **соглашение срезов 001-003
  для форм**; решение 22 задач (без `role="status"`, `role="alert"`, `data-error`, `data-warning`)
  относится **только** к колокольчику и кадрам живых обновлений (раздел 14, 14.1): там эти
  атрибуты запрещены, на страницах форм они обязательны (так их находят `helpers.alert_text` и
  `status_text`);
- **успех**: обычный POST — 302 на адрес из таблицы и сообщение `[role=status]` (флеш-механизм
  ядра `_flashes.html`) на странице назначения; НХ-POST — 200 с фрагментом, названным в таблице,
  либо 200 с пустым телом и заголовком `HX-Redirect` (как в CONTRACT-003 § 12);
- **403 и 404**: `/settings/notifications/` — нет права `notify.manage` — 403 (на GET и на POST,
  до любой работы сервиса); чужое или несуществующее уведомление, подписка, привязка — **404**
  (не 403: FR-342) и запись не меняется; неизвестное значение `<канал>` в пути (не `telegram` и не
  `max`) — 404 раньше всего прочего; неверный формат номера в пути (не число) — 404;
- **флажки**: значение `1` (у ячеек — `<код вида>:<канал>`, см. 13.2); нет поля в теле — снят;
- отказов 4xx на запрос НХ нет, кроме 403 и 404 прямого обращения и ответов JSON (13.3).

### 13.1. Уведомления, колокольчик, прочитано

| Путь | Метод, параметры, поля | Что ожидают тесты | Тесты |
|---|---|---|---|
| `/notifications/` | GET; `f` (`unread` — только непрочитанные; пусто и любое другое значение — все), `page` (целое от 1; не число и меньше 1 — первая страница, больше числа страниц — последняя: правила `Paginator.get_page`) | 200 полной страницы; свои уведомления, новые сверху (`created_at` по убыванию, затем номер по убыванию), по 50 на страницу; чужих нет (FR-342); пустой список — `[data-empty-state="notifications"]` (14.2); без входа — 302 | T-4123 test_list_page_shows_50_newest_first_with_kind_text_time_unread_mark, test_list_page_page_param_returns_next_50, test_list_filter_unread_shows_only_unread_and_all_shows_every_one, test_empty_list_shows_no_notifications_text, test_list_page_does_not_show_other_users_notifications, test_list_page_requires_login; e2e/test_e10_page |
| `/notifications/bell/` | GET | 200 фрагмент `[data-bell-panel]` (14.1) на любой запрос (НХ или обычный: страницы у адреса нет): последние 10 своих уведомлений, новые сверху, «Все уведомления» (`/notifications/`) и «Настройки» (`/me/notifications/`); пустой список — `[data-empty-state="bell"]`; без входа — 302 | T-4123 test_bell_fragment_lists_last_10_with_all_and_settings_links, test_bell_fragment_shows_only_own_notifications; e2e/test_e10_page test_e10_bell_click_shows_last_10_notifications_and_all_notifications_link |
| `/notifications/<id>/open/` | GET | `reading.open`: своё — 302 на `Notification.url` и `read_at` поставлен; чужое или несуществующее — 404, запись не меняется; в тело ничего не пишется (GET меняет состояние: план «Контракты»); POST — 405 | T-4124 test_open_own_marks_read_and_redirects_to_url, test_open_foreign_notification_returns_404_and_stays_unread, test_open_nonexistent_notification_returns_404, test_open_pushes_decreased_count_to_group; e2e/test_e10_page |
| `/notifications/<id>/read/` | POST; необязательные скрытые поля `f`, `page` (чтобы вернуться на ту же страницу списка) | `reading.read`; обычный POST — 302 на `/notifications/` (с `f` и `page`, если переданы и допустимы; иначе без параметров); НХ — 200 фрагмент строки `li[data-notification="<id>"]` (14.2) уже в состоянии «прочитано» (`data-unread="0"`, отметки и кнопки «Прочитать» нет), строка остаётся в списке (в фильтре «непрочитанные» — до перезагрузки); чужое или несуществующее — 404; GET — 405; число на колокольчике приходит по соединению (`live.push`), в ответе его нет | T-4124 test_read_marks_one_notification_without_redirect, test_read_foreign_notification_returns_404, test_read_rejects_get_method, test_read_notification_stays_in_list, test_no_count_push_when_mark_changes_nothing; e2e/test_e10_page test_e10_mark_read_button_marks_notification_read_without_navigation |
| `/notifications/read-all/` | POST; необязательное скрытое поле `f` | `reading.read_all`; обычный POST — 302 на `/notifications/` (с `f`); НХ — 200 с пустым телом и `HX-Redirect: /notifications/` (с `f`); чужих не затрагивает; GET — 405 | T-4124 test_read_all_marks_all_own_unread_and_count_becomes_zero, test_read_all_does_not_touch_other_users_notifications; e2e/test_e10_page test_e10_read_all_with_30_unread_marks_all_read_and_counter_zero |
| `/sw.js` | GET | 200, `Content-Type: application/javascript`, `Cache-Control: no-store`; **без `login_required`**: гость получает 200 (сервис-воркер подключается только со страниц вошедшего, а страница входа его не регистрирует); истёкшую по бездействию или ограниченную сессию отвечает перенаправлением промежуточный слой ядра, не представление (согласование строки `/sw.js` в «Контрактах» плана и T-4230: в представлении проверки входа нет, а перенаправление при истёкшей сессии — работа `SessionGuardMiddleware`); тело содержит обработчики `push` и `notificationclick`; POST — 405 | T-4115 test_notify_webpush.py::test_sw_js_served_as_javascript_with_no_store_and_without_login; e2e/test_e05_webpush |

Открытие карточки заявки (`GET /tickets/<номер>/`) отмечает уведомления о ней прочитанными через
событие `object.viewed` (4.2, 6.8): отдельного маршрута нет. Тесты: T-4124 (все `test_ticket_card_*`).

### 13.2. «Мои уведомления» (`/me/notifications/`)

Страница вошедшего сотрудника; чужой страницы нет (в пути нет номера сотрудника, поле `user` в
теле игнорируется: T-4125 test_post_changes_only_own_settings_ignoring_foreign_user_id).

| Путь | Метод, параметры, поля | Что ожидают тесты | Тесты |
|---|---|---|---|
| `/me/notifications/` | GET | 200 полной страницы: таблица «вид × канал» из `prefs.effective(request.user)`, тихие часы из строки `UserNotifySettings` (нет строки — режим «По рабочему календарю компании»), блок Web Push, блоки привязок Telegram и MAX, разметка — раздел 14.3; без входа — 302 | T-4125, T-4126 test_page_shows_calendar_mode_selected_for_employee_without_settings_row |
| `/me/notifications/` | POST: `table` (скрытое `1` — «таблица отправлена»), `cell` (повторяющееся, одна запись на отмеченную ячейку, значение `<код вида>:<канал>`, канал — `email`, `push`, `telegram`, `max`; код вида содержит точки и не содержит двоеточия), `quiet_mode` (`calendar`, `own`, `none`), `own_days` (повторяющееся, значения `0`-`6`, 0 — понедельник), `own_start`, `own_end` (`ЧЧ:ММ`, строка поля `input[type=time]`) | `prefs.save` (6.4). Сборка вызова: **таблица** — если есть `table`, `table = {код вида: [каналы из cell этого вида]}` для **каждого** вида из `effective(user).rows` (вид без отмеченных ячеек — пустой список, то есть «все внешние выключены»); `portal` в значениях и коды видов не из `rows` сервис отбрасывает; нет `table` — `table=None`, ячейки не трогаются (так тест «сохранение одних тихих часов» присылает только `quiet_mode`). Ячейки недоступных каналов (`Channel.available` ложно) форма не присылает, сервис оставляет прежнее значение (решение B1); ячейка `push` присылается всегда — её флажок на странице есть всегда и не имеет атрибута `disabled` (14.3). **Тихие часы** — нет `quiet_mode` — `quiet_mode=None`, часы не трогаются; `quiet_mode=own` — представление передаёт `own_days` **списком** (отсутствие поля — пустой список, то есть отказ `own_no_days`) и `own_start`, `own_end` строками (пустая строка — «оставить прежнее значение», 6.4; нет значения и прежнего — `own_incomplete`); `calendar` и `none` — `own_*` не передаются и не меняются. Успех — 302 на `/me/notifications/` и `[role=status]` «Настройки уведомлений сохранены.»; НХ — 200 с пустым телом и `HX-Redirect: /me/notifications/`. Отказ (`bad_quiet_mode`, `own_no_days`, `own_bad_day`, `own_incomplete`, `own_same_time`) — 200 той же страницы (НХ — фрагмент `#notify-prefs-root` с `hx-swap="outerHTML"`), у поля `[data-error]`: `quiet_mode`, `own_days`, `own_start` (у `own_incomplete`), `own_end` (у `own_same_time`), текст — 15.4; введённые значения остаются в форме; прежние настройки не меняются, журнала нет | T-4125 (все), T-4110, T-4126 test_audit_*; e2e/test_e04_my_settings |
| `/me/notifications/push/` | POST, `Content-Type: application/json`, тело — форма `PushSubscription.toJSON()` браузера: `{"endpoint": строка, "keys": {"p256dh": строка, "auth": строка}}` (выбор контракта; плоской формы нет); заголовок `X-CSRFToken` (скрипт берёт значение из скрытого поля страницы, как `htmx-glue.js`) | `push.save(user, endpoint=…, p256dh=…, auth=…, device_id=<устройство сессии из `UserSession.device_id` или `None`>, user_agent=<заголовок User-Agent>, ip=<адрес запроса>)`. Успех — 200 JSON `{"ok": true, "id": <номер подписки>}`; **отказ — 400 JSON** `{"ok": false, "code": "<код>", "field": "<поле>", "message": "<текст 15.4>"}` (это не запрос НХ и не форма: скрипту нужен статус; выбор контракта, решение D3); коды — `too_long`, `bad_endpoint`, `bad_scheme`, `has_credentials`, `bad_port`, `bad_host`, `bad_keys` (6.2) и два кода представления: `bad_json` (тело не JSON, не объект или нет `endpoint` или `keys`) и `channel_disabled` (Web Push выключен администратором или нет ключей: `settings.channel_on("webpush")` ложно; представление проверяет раньше `push.save`; кнопки на странице при этом нет, FR-336); без входа — 302; GET — 405; чужой номер устройства в сессии не принимается (устройство берётся из сессии, не из тела) | T-4115 (все, через представление: подписка сохранена с браузером и платформой по User-Agent, подписка с тем же адресом у другой учётной записи удалена, 11-я вытесняет старейшую), T-4126, T-4129; e2e/test_e05_webpush |
| `/me/notifications/push/<id>/delete/` | POST | `push.delete(user, id)`; обычный POST — 302 на `/me/notifications/` и `[role=status]` «Устройство удалено.»; НХ — 200 фрагмент `#notify-devices` (список устройств без удалённого); чужая или несуществующая подписка — 404; GET — 405 | T-4115 test_user_deletes_own_subscription_from_list, test_deleting_foreign_subscription_returns_404; T-4126 test_delete_own_device_keeps_second_device, test_delete_foreign_device_returns_404 |
| `/me/notifications/bind/<канал>/` | POST, полей нет; `<канал>` — `telegram` или `max` | `binding.new_code(user, channel)`; **ответ всегда 200** (код открытый и хранится только в возврате сервиса: после 302 страница показать его не смогла бы, решение D1): НХ — фрагмент блока `#notify-binding-<канал>` (14.3) с `[data-bind-code]` (восемь цифр), сроком `[data-bind-expires]` («действует 10 минут») и `a[data-bot-link]` без кода в адресе либо подсказкой `[data-bot-link-hint]`, если имени бота нет (`bots.bot_link` пусто); обычный POST — полная страница `/me/notifications/` с тем же блоком. Канал выключен администратором или токен не задан (`channel_disabled`) — 200, в блоке `[data-state="disabled"]` с текстом «Канал отключён администратором» и `[data-error="channel"][data-code="channel_disabled"]`, кода нет; повторное нажатие даёт новый код (прежний неиспользованный удалён, 6.13); код нигде, кроме этого ответа, не показывается (повторный GET страницы его не содержит, в `Location`, журнале и ссылке на бота его нет) | T-4118 (страничные: test_bind_button_absent_and_disabled_text_shown_when_channel_off_or_token_missing, test_bot_link_has_no_code_or_secrets_in_url, test_bot_link_replaced_by_hint_when_bot_name_unknown), T-4126 test_bind_button_shown_for_enabled_unbound_telegram_and_max; e2e/test_e06_bots test_e06_bind_shows_code_valid_ten_minutes_and_bot_link_without_code_only_to_the_employee |
| `/me/notifications/unbind/<канал>/` | POST, полей нет | `binding.unbind(user, channel, actor=user, ip=…)`; идемпотентна (привязки не было — тот же ответ); обычный POST — 302 на `/me/notifications/` и `[role=status]` «Telegram отвязан.» или «MAX отвязан.» (текст контракта); НХ — 200 блок `#notify-binding-<канал>` в состоянии «не привязан» (`[data-state="unbound"]`); чужой привязки нет по определению (привязка берётся по сотруднику и каналу) | T-4126 test_bound_channel_shows_bound_status_and_unbind_button, test_unbind_by_employee_writes_channel_unbound_journal_by_employee_without_chat_id; e2e/test_e06_bots test_e06_unbind_stops_messages_and_bot_ignores_old_codes |

Блок привязки, который сервер вставляет в кадр `notify.update` (11.3), — тот же шаблон, что в этом
ответе и на странице: по соединению приходит состояние «Привязан» (`[data-state="bound"]`), код
в кадре не передаётся.

### 13.3. Страница администратора (`/settings/notifications/`)

Право — `notify.manage`; нет права — 403 на GET и на POST (одинаково, без обращения к сервису);
без входа — 302; пункт меню «Уведомления» (`menu_items`, `order` 62, `/settings/notifications/`)
виден только с правом (T-4127 test_menu_item_notifications_visible_only_with_manage_permission).

| Путь | Метод, параметры, поля | Что ожидают тесты | Тесты |
|---|---|---|---|
| `/settings/notifications/` | GET | 200 полной страницы: три блока каналов, таблица значений по умолчанию, поля сроков (разметка — 14.4); значений ключей и токенов в ответе нет вообще (ни в тексте, ни в `value`, ни в `data-*`: проверяется поиском сгенерированных значений тестового окружения в теле) | T-4127 test_page_shows_three_channels_with_switch_keys_state_and_default_values, test_page_shows_no_key_or_token_values, test_page_shows_bot_name_and_last_error_time_and_code_of_channel; e2e/test_e08_admin |
| `/settings/notifications/` | POST: `channels` (скрытое `1`: «переключатели отправлены»), `webpush_enabled`, `telegram_enabled`, `max_enabled` (флажки `1`), `limits` (скрытое `1`: «сроки отправлены»), `email_delay_minutes`, `retention_days` (целые), `defaults_present` (скрытое `1`: «таблица отправлена»), `cell` (повторяющееся, как в 13.2: `<код вида>:<канал>`, канал — `email`, `push`, `telegram`, `max`) | `settings.update(actor=request.user, ip=…, **fields)` (6.5). Сборка: переключатели передаются, только если есть `channels` (отсутствующий флажок — `False`); сроки — только если есть `limits` (пустое или нечисловое значение — передаётся как есть, сервис отвечает `out_of_range`); `defaults` — только если есть `defaults_present`: словарь `{код вида: [каналы из cell]}` **по всем нематериальным видам каталога** (`mandatory` в таблице нет; вид без отмеченных ячеек — пустой список), и он заменяет прежний целиком (6.5): поэтому страница всегда присылает всю таблицу, а тест без `defaults_present` значений не меняет. Успех — 302 на `/settings/notifications/` и `[role=status]` «Настройки уведомлений сохранены.»; изменений не было — тот же ответ, записи в журнале нет. Отказ (`out_of_range`, `keys_missing`, `bad_defaults`) — 200 той же страницы, `[data-error="<error.field>"][data-code]`: `email_delay_minutes`, `retention_days`, `webpush_enabled`/`telegram_enabled`/`max_enabled` (у `keys_missing` — имя переключателя), `defaults`; тексты — 15.4; **ничего не сохранено** (в том числе остальные поля той же отправки); выключить канал можно всегда; значения ключей и токенов в ответе нет и при отказе | T-4127 (все), T-4129 test_admin_settings_change_writes_was_became_event, test_save_without_changes_writes_no_event; e2e/test_e08_admin |

Форма страницы — с атрибутом `novalidate`: пределы сроков проверяет сервис (`out_of_range` с
текстом), браузер не должен останавливать отправку раньше (приёмка T-4147 ждёт отказ сервера).
То же — у формы 13.2 (`novalidate`: «начало равно концу» и «нет дней» проверяет сервис).

## 14. Зацепки разметки

Тесты ищут элементы по атрибутам `data-*`, идентификаторам и `role`, не по классам и не по тексту,
кроме случаев, где подпись названа дословно (раздел 15). В разметке нет встроенных скриптов и
обработчиков (CSP): поведение — внешние файлы (`static/js/notify.js` — T-4233,
`static/js/notify-push.js` — T-4231). Время — по Москве, `<time data-at="<ISO 8601 со смещением>">`
с видимым текстом `ДД.ММ.ГГГГ ЧЧ:ММ` (как в CONTRACT-003 § 13). Списки существующих `data-*`
срезов 001-003 — в CONTRACT-003 § 13.1; для того же смысла новых имён не заводится: переиспользуются
`[data-empty-state]`, `[data-narrow="cards"]`, `[data-section]`, `[data-action]`, `form[data-form]`,
`[data-error]`, `[data-code]`, `[data-at]`, `[data-field]`.

Общие проверки страниц среза (T-4123, T-4125, T-4127, T-4151): `<meta name="viewport">` на каждой
странице 13.1-13.3; `<html lang="ru">`; время — по Москве; ни одной горизонтальной прокрутки при
ширине 360 px (`[data-narrow="cards"]` у таблицы 14.3). Проверка «страница по-русски»
(`test_every_slice_page_is_russian` в части CONTRACT-003) для срезов 004 допускает в `title`, `h1`,
подписях `button` **слова-исключения** `push`, `Push`, `Web Push`, `Telegram`, `MAX` (так названы
каналы в FR-302, FR-324, FR-325; решение D2).

### 14.1. Колокольчик и кадры живых обновлений

Колокольчик — шаблон элемента `top_bar_items` (`templates/notify/bell.html`; context-процессор
ядра кладёт его в `top_bar`, `base.html` выводит внутри `.top-actions` **до** ссылок профиля). Его
нет у гостя и у ограниченной сессии. **Решение 22 задач**: у колокольчика, `#notify-count`,
`#notify-toast` и кадров `/ws/notify/` нет `role="status"`, `role="alert"`, `data-error`,
`data-warning`; допускается `aria-live="polite"` (без роли) и `aria-label`.

| Зацепка | Что | Тесты |
|---|---|---|
| `#notify-bell[data-bell]` | корень колокольчика: `hx-ext="ws"` и `ws-connect="/ws/notify/"` (один элемент на странице; других `ws-connect` на странице нет); атрибут `data-ws` — состояние соединения (решение E21): шаблон рисует `data-ws="connecting"`, `notify.js` ставит `open` после **первого кадра** сервера (событие `htmx:wsAfterMessage`: кадр с числом уходит после `group_add` и `live.mark_online`, значит присутствие уже записано) и `closed` по `htmx:wsClose`; приёмка перед событием, которое проверяет живое обновление или пропуск Web Push при открытой вкладке, ждёт `#notify-bell[data-ws="open"]`; роли и `aria-live` у признака нет (решение 22); внутри — кнопка, число, пустой элемент системного уведомления, контейнер панели; в шаблон включён `<script src="{% static 'js/notify.js' %}" defer>` | T-4123 test_bell_in_top_bar_has_count_and_toast_elements, test_bell_carries_ws_connect_to_notify_socket, test_bell_not_rendered_for_anonymous_user |
| `button[data-bell-toggle]` | кнопка колокольчика с иконкой `icons/bell.html` (`aria-hidden`) и `aria-label="Уведомления"`; `hx-get="/notifications/bell/"`, `hx-trigger="click"` (по нажатию, не при загрузке), `hx-target="#notify-bell-panel"`, `hx-swap="innerHTML"`; при загрузке страницы запрос панели не уходит | T-4123 test_bell_fragment_lists_last_10_with_all_and_settings_links; e2e/test_e10_page |
| `#notify-count` | `<span id="notify-count" class="… [d-none]" data-count="<N>">` — **точное** число непрочитанных (целое, `0` включительно); текст — `<N>`, при `N > 99` — `99+`; при `N == 0` элемент остаётся в разметке, класс `d-none` (Bootstrap) **есть** при `0` и **нет** при `N > 0` (имя класса — решения C8 и D10); в кадре сервера та же разметка с `hx-swap-oob="true"` (11.3), в странице атрибута `hx-swap-oob` нет; один шаблон (`templates/notify/_count.html`) рисует и страницу, и кадр | T-4123 test_bell_count_element_present_but_hidden_at_zero, test_bell_count_shows_99_at_99_and_99_plus_above; T-4122, T-4109, T-4124 (по `data-count`); e2e |
| `#notify-toast` | пустой `<div id="notify-toast" data-text="" data-url="" data-tag="" data-show="0">` на странице; кадр заменяет его тем же элементом с `data-text`, `data-url`, `data-tag`, `data-show` (11.3); без содержимого; `notify.js` слушает вставку и при `data-show="1"` и разрешении браузера показывает уведомление конструктором `new Notification(<data-text>, {tag: <data-tag>, data: {url: <data-url>}})`; нажатие (`onclick`) открывает `data-url` в этой вкладке и закрывает уведомление (выбор контракта, решение E22) (FR-320). Push при закрытой вкладке показывает сервис-воркер: `self.registration.showNotification(title, {tag, data: {url}})` по нагрузке (6.9); `notificationclick` закрывает уведомление и открывает `url` того же источника, иначе «/» (план «Web Push»). Как видит приёмка (решение E22): во вкладке — init-скрипт подменяет `window.Notification` обёрткой, которая записывает `title`, `tag`, `data` и сам объект в `window.__e2eNotifications` и зовёт настоящий конструктор; нажатие — `dispatchEvent(new Event("click"))` записанного объекта; при закрытой вкладке — `registration.getNotifications()` с новой страницы того же контекста (`title`, `data.url`); если безголовый Chrome уведомлений сервис-воркера не отдаёт или нажатие не открывает окно, T-4144 задаёт вопрос Opus, а не придумывает способ | T-4123 test_bell_in_top_bar_has_count_and_toast_elements; T-4122; e2e/test_e01_new_ticket (системное уведомление), e2e/test_e05_webpush |
| `#notify-bell-panel[data-bell-panel]` | контейнер раскрывающейся панели; до первого нажатия пуст; после — ответ `/notifications/bell/` (ниже); раскрытием управляет скрипт оболочки (Alpine или Bootstrap): тест ждёт `[data-bell-panel] [data-bell-list]` | T-4123, e2e/test_e10_page |
| `[data-bell-list]` и `li[data-notification="<id>"]` | список последних 10 (разметка строки — 14.2, поле `data-field="kind"` в панели не обязательно); пустой список — `[data-empty-state="bell"]` с текстом «У вас нет уведомлений» | T-4123 |
| `a[data-bell-all]`, `a[data-bell-settings]` | «Все уведомления» (`/notifications/`) и «Настройки» (`/me/notifications/`) — всегда, даже при пустом списке | T-4123 test_bell_fragment_lists_last_10_with_all_and_settings_links |

### 14.2. Список «Уведомления» (`/notifications/`)

| Зацепка | Что | Тесты |
|---|---|---|
| `[data-notify-list]` | корень страницы: внутри `nav[data-notify-filter]`, форма «Прочитать все», `ul[data-notifications]`, `nav[data-pager]` (если страниц больше одной) | T-4123 |
| `nav[data-notify-filter] a[data-filter="all\|unread"]` | «Все» (`/notifications/`) и «Непрочитанные» (`/notifications/?f=unread`); активный — `aria-current="true"`; по умолчанию активен `all` | T-4123 test_list_page_has_filter_switch_read_all_and_mark_read_controls, test_list_filter_unread_shows_only_unread_and_all_shows_every_one |
| `li[data-notification="<id>"][data-unread="1\|0"]` | строка уведомления (тест ищет `ul[data-notifications] li[data-notification=…]`); `data-unread="1"` у непрочитанного; порядок строк — новые сверху; ни `[data-kind]`, ни `[role]` у строки нет (правило CONTRACT-003 § 13.1 о `[data-kind]` без тега сохраняется: вид — в `data-field`) | T-4123, T-4124, e2e/test_e10_page |
| `[data-field="text"]` | текст уведомления — ссылка `a[data-open][href="/notifications/<id>/open/"]` (адрес открытия, не прямой `Notification.url`); текст экранирует шаблон (NFR-311) | T-4123 test_list_page_shows_50_newest_first_with_kind_text_time_unread_mark; e2e/test_e12_criteria test_e12_ticket_subject_with_markup_shown_as_text_on_portal_and_in_mail |
| `[data-field="kind"]` | название вида из каталога (`NotificationKind.title`, 3.2); вида нет в каталоге (удалён модулем) — пусто | T-4123 |
| `time[data-at]` | время создания (формат выше) | T-4123, e2e/test_e12_criteria test_e12_notification_pages_show_russian_text_and_moscow_time |
| `[data-unread-mark]` | отметка «не прочитано» (текст «новое»): есть только у строки с `data-unread="1"` | T-4123 |
| `form[data-form="read"]` и `button[data-action="read"]` | у **непрочитанной** строки: форма на `/notifications/<id>/read/` с кнопкой «Прочитать»; у прочитанной формы нет; НХ: `hx-post`, `hx-target="closest li"`, `hx-swap="outerHTML"`; скрытые поля `f`, `page` | T-4123, T-4124, e2e/test_e10_page |
| `form[data-form="read-all"]` и `button[data-action="read-all"]` | форма на `/notifications/read-all/` с кнопкой «Прочитать все»; есть всегда, пока список не пуст; скрытое поле `f` | T-4123, e2e/test_e10_page |
| `[data-empty-state="notifications"]` | пустой список (на любой странице списка, без строк): текст из 15.5; кнопок нет | T-4123 test_empty_list_shows_no_notifications_text; e2e/test_e10_page |
| `nav[data-pager] a[data-page-prev]`, `a[data-page-next]`, `[data-page-current]` | переход по страницам (`?page=`, с сохранением `f`); `[data-page-current]` — номер текущей страницы; без соседней страницы ссылки нет | T-4123 test_list_page_page_param_returns_next_50 |

### 14.3. «Мои уведомления» (`/me/notifications/`)

Корень — `[data-notify-prefs]#notify-prefs-root`. Внутри (по порядку): основная форма
`form[data-form="notify-prefs"]` (таблица и тихие часы, один POST, 13.2), раздел `[data-section="push"]`,
блоки привязок `#notify-binding-telegram` и `#notify-binding-max`. Блоки привязок и раздел push **вне**
основной формы (вложенных форм нет).

| Зацепка | Что | Тесты |
|---|---|---|
| `[data-narrow="cards"]` | у контейнера таблицы «вид × канал»: на узкой ширине таблица складывается в карточки по виду; признак тот же, что у `#tickets-grid` (CONTRACT-003); проверка 360 px без горизонтальной прокрутки | T-4125 test_page_markup_has_card_layout_without_wide_table_at_narrow_width; e2e/test_e04_my_settings test_e04_page_at_360px_width_has_no_horizontal_scroll |
| `table[data-notify-table]` | таблица: заголовки столбцов по порядку — «На портале», «Почта», «Push в браузере», «Telegram», «MAX» (`th[data-channel="portal\|email\|push\|telegram\|max"]`); после `push` идут `telegram`, затем `max` | T-4125 test_table_has_five_channel_columns_in_order |
| `tr[data-notify-kind="<код вида>"]` | строка вида из `effective(user).rows`: `[data-field="title"]` (название), `[data-field="module"]` (модуль); ячейки — `td[data-channel="<канал>"]` по пять на строку, в порядке столбцов | T-4125 test_table_rows_show_kind_title_and_module, test_queue_kind_hidden_for_employee_who_is_not_direct_queue_member, test_queue_kind_shown_for_direct_queue_member |
| ячейка `portal` | `td[data-channel="portal"][data-locked="1"]` с `input[type=checkbox][checked][disabled]` **без `name`**: отмечена всегда, не меняется и ничего не присылает (поле `cell` со значением `…:portal` сервис отбрасывает) | T-4125 test_portal_column_checked_and_locked_for_every_kind, test_post_cannot_switch_off_portal_channel |
| ячейка `email` | `td[data-channel="email"]` с `input[type=checkbox][name="cell"][value="<код вида>:email"]`, `checked`, если ячейка включена; почта доступна всегда | T-4125 test_unchecking_mail_cell_saves_own_matrix_and_keeps_portal |
| ячейка `push` | `td[data-channel="push"][data-available="1\|0"][data-reason="<""\|no_subscriptions\|channel_disabled>"]` — **признак и причина из `Table.web_push_available` и `web_push_reason`** (6.4); внутри **всегда** `input[type=checkbox][name="cell"][value="<код вида>:push"]`, `checked` при включённой ячейке, **без атрибута `disabled`** (так флажок попадает в тело формы, решение B1, и сервис хранит значение; решение D5); недоступность — `data-available="0"` и подсказка `[data-hint]` (15.5): `no_subscriptions` — «Разрешите push на этом устройстве», `channel_disabled` — «Push при закрытой вкладке отключён администратором»; скрипт `notify-push.js` при `data-available="0"` (и пока у браузера нет разрешения) ставит `data-locked="1"` и не даёт менять флажок (отменяет щелчок), значение при этом уходит прежним | T-4125 test_browser_push_column_unavailable_without_subscription_with_allow_hint, test_channel_disabled_by_admin_column_unavailable_with_disabled_hint; e2e/test_e04_my_settings test_e04_unlinked_telegram_column_disabled_with_hint_and_push_column_disabled_until_device_allowed |
| ячейки `telegram`, `max` | доступны (канал включён, токен задан, привязка есть) — как `email`, `data-available="1"`; недоступны — `td[data-channel="telegram\|max"][data-available="0"][data-reason="<channel_disabled\|not_bound>"]` **без `input`** и с `[data-hint]`: `not_bound` — «Привяжите Telegram» («Привяжите MAX»), `channel_disabled` — «Канал отключён администратором» | T-4125 test_unbound_telegram_and_max_columns_unavailable_with_bind_hint, test_channel_disabled_by_admin_column_unavailable_with_disabled_hint |
| `tr[data-notify-fixed="security"]` и `tr[data-notify-fixed="channel_unbound"]` | ровно две сводные строки видов `mandatory` **без `input`** (спека, сценарий 4 п. 4; раздел 6.4; решение Opus по D4): первая — «Безопасность: всегда» (три вида безопасности ядра), вторая — «Канал отвязан: всегда, только на портале»; лежат в `tbody[data-fixed-rows]` после строк видов | T-4125 test_mandatory_security_kinds_shown_as_always_row_without_checkboxes, test_channel_unbound_kind_shown_portal_only_row_without_checkboxes; e2e/test_e04_my_settings test_e04_security_and_channel_unlinked_kinds_shown_as_separate_rows_without_checkboxes, e2e/test_e09_security; T-4151 test_e12_catalog_shows_four_service_desk_kinds_three_security_kinds_…: три вида безопасности в таблице идут одной строкой, поэтому тест видит их по самим записям (`core.*`) или через `helpers.stand_shell` (`kinds.catalog()`) |
| `input[type=hidden][name="table"][value="1"]` | признак «таблица отправлена» (13.2) | T-4125 |
| `fieldset[data-quiet]` | тихие часы: три `input[type=radio][name="quiet_mode"]` со значениями `calendar`, `own`, `none` (подписи — 2.1); выбран режим из строки сотрудника (нет строки — `calendar`: T-4126 test_page_shows_calendar_mode_selected_for_employee_without_settings_row); семь `input[type=checkbox][name="own_days"]` значений `0`-`6` (подписи «Пн»…«Вс»), `input[type=time][name="own_start"]`, `input[type=time][name="own_end"]` (подписи «с» и «до»), значения из строки сотрудника в формате `ЧЧ:ММ`; поля `own_*` есть всегда (не только при `own`) | T-4125 test_quiet_mode_calendar_own_hours_and_none_are_saved, test_table_and_quiet_hours_saved_with_one_post; e2e/test_e04_my_settings |
| `[data-error="quiet_mode\|own_days\|own_start\|own_end"]` | отказ тихих часов у поля (13.2, 15.4), с `data-code` | T-4125 test_own_hours_with_start_equal_to_end_rejected_with_message, test_own_hours_without_any_day_rejected_with_message, test_rejected_input_on_htmx_request_returns_200_with_error_fragment; e2e/test_e04_my_settings test_e04_own_hours_with_start_equal_to_end_or_no_days_refused_with_explanation |
| `button[type=submit][data-action="save-prefs"]` | «Сохранить» (одна на форму) | T-4125 |
| `[data-section="push"]` | раздел «Push в браузере» (внутри — ниже); его атрибут `data-web-push="on\|off"` — Web Push включён администратором и ключи заданы (`settings.channel_on("webpush")`) | T-4126 test_push_button_shown_when_web_push_enabled, test_push_button_hidden_and_disabled_by_admin_text_shown_when_web_push_off |
| `button[type=button][data-action="push-permission"]` | «Разрешить уведомления браузера» (решение 34 задач): **есть всегда**, в том числе при выключенном Web Push; скрипт скрывает кнопку, когда разрешение уже дано или запрещено; запрос разрешения только по нажатию (при загрузке страницы разрешение не запрашивается, FR-320) | T-4126, e2e/test_e05_webpush test_e05_allow_browser_notifications_button_present_when_web_push_disabled_and_enables_tab_push, test_e05_opening_pages_does_not_request_browser_permission_until_button_pressed |
| `button[type=button][data-action="push-subscribe"]` | «Включить push на этом устройстве»: **есть только при `data-web-push="on"`**; атрибуты `data-vapid-public="<VAPID_PUBLIC_KEY>"` (открытый ключ: не секрет), `data-subscribe-url="/me/notifications/push/"`, `data-sw-url="/sw.js"`; скрипт скрывает кнопку, если у этого устройства уже есть подписка; нажатие запрашивает разрешение (если ещё нет), регистрирует `/sw.js`, подписывает и отправляет JSON (13.2); закрытая администратором — кнопки нет | T-4126 test_push_button_shown_when_web_push_enabled; e2e/test_e05_webpush test_e05_enable_push_on_device_after_consent_saves_subscription_lists_device_and_enables_push_column |
| `[data-push-disabled-text]` | только при `data-web-push="off"`: «Push при закрытой вкладке отключён администратором» (15.5) | T-4126 test_push_button_hidden_and_disabled_by_admin_text_shown_when_web_push_off; e2e/test_e05_webpush test_e05_push_disabled_by_admin_hides_button_shows_disabled_text_and_tab_push_still_works |
| `[data-push-denied]` | пояснение, как разрешить уведомления в настройках браузера (15.5); в разметке есть всегда с атрибутом `hidden`, скрипт показывает его, когда браузер запретил уведомления портала (`Notification.permission === "denied"` или отказ в ответ на запрос), и тогда обе кнопки скрыты и подписки нет | e2e/test_e05_webpush test_e05_denied_permission_leaves_no_subscription_and_explains_how_to_allow_in_browser_settings |
| `#notify-devices`, `ul[data-devices]`, `li[data-device="<id подписки>"]` | список подписок сотрудника (`push.list_for`, новые сверху): `[data-field="browser"]`, `[data-field="platform"]`, `time[data-at]` (дата создания); `form[data-form="device-delete"]` на `/me/notifications/push/<id>/delete/` с `button[data-action="device-delete"]` «Удалить»; чужих строк нет; пусто — `[data-empty-state="devices"]` | T-4126 test_device_list_shows_browser_platform_and_date_of_own_subscriptions, test_device_list_does_not_show_foreign_subscriptions, test_delete_own_device_keeps_second_device; e2e/test_e05_webpush test_e05_two_devices_removing_one_stops_push_to_it_and_other_still_gets_push |
| `#notify-binding-<канал>[data-channel="<канал>"][data-state="unbound\|bound\|disabled"]` | **корень блока привязки** — один и тот же элемент в странице, в ответе `bind` и `unbind` и в кадре `notify.update` (11.3, C8; заменяется целиком, `hx-swap-oob="true"` только в кадре); заголовок — «Telegram» или «MAX» | T-4118 test_binding_block_is_pushed_to_user_group_after_bind; T-4126; e2e/test_e06_bots |
| блок `unbound` | `form[data-form="bind"]` на `/me/notifications/bind/<канал>/` с `button[data-action="bind"]` «Привязать» (НХ: `hx-post`, `hx-target="#notify-binding-<канал>"`, `hx-swap="outerHTML"`); код и ссылка — только в ответе `bind`: `[data-bind-code]` (восемь цифр, текст), `[data-bind-expires]` («Код действует 10 минут»), `a[data-bot-link][href]` (`https://t.me/<имя>` или `https://max.ru/<имя>`, без кода) **или** `[data-bot-link-hint]` («Ссылка появится, когда бот подключится»); у `unbound` без только что выданного кода их нет | T-4126 test_bind_button_shown_for_enabled_unbound_telegram_and_max; T-4118; e2e/test_e06_bots |
| блок `bound` | `[data-bound]` с текстом «Привязан»; `form[data-form="unbind"]` на `/me/notifications/unbind/<канал>/` с `button[data-action="unbind"]` «Отвязать»; кнопки «Привязать» нет; код и ссылка не показываются | T-4126 test_bound_channel_shows_bound_status_and_unbind_button; T-4118 test_binding_block_is_pushed_to_user_group_after_bind; e2e/test_e06_bots test_e06_valid_code_sent_to_bot_binds_channel_bot_confirms_and_page_shows_bound |
| блок `disabled` | `[data-disabled-text]` с текстом «Канал отключён администратором»; кнопок «Привязать» и «Отвязать» нет (даже у привязанного, пока канал выключен или нет токена: привязка сохранена, но управлять ею выключенным каналом нельзя — T-4126 test_disabled_or_tokenless_channel_shows_disabled_text_without_buttons) | T-4126; e2e/test_e06_bots test_e06_channel_off_by_admin_or_token_missing_hides_bind_button_and_shows_disabled_text |
| `section[data-section="notifications"]` в карточке профиля | раздел «Мои уведомления» во вкладке «Профиль» (`card_sections`, `CardSection(key="notifications", tab="profile", …)`), **только у владельца** (у чужой карточки раздела нет); внутри `a[data-action="my-notifications"][href="/me/notifications/"]` «Мои уведомления» | T-4126 test_profile_card_shows_my_notifications_section_only_to_owner, test_profile_card_of_other_employee_has_no_my_notifications_section |

### 14.4. Страница администратора (`/settings/notifications/`)

Корень — `[data-notify-settings]`; форма — `form[data-form="notify-settings"]` (`novalidate`, 13.3) с
скрытыми `channels=1`, `limits=1`, `defaults_present=1` и одной `button[type=submit][data-action="save-settings"]`
«Сохранить».

| Зацепка | Что | Тесты |
|---|---|---|
| `section[data-channel-block="webpush\|telegram\|max"]` | блок канала (по порядку: Web Push, Telegram, MAX); внутри — переключатель, состояние ключей, имя бота (у `telegram`, `max`), последняя ошибка | T-4127 test_page_shows_three_channels_with_switch_keys_state_and_default_values; e2e/test_e08_admin |
| `input[type=checkbox][name="webpush_enabled\|telegram_enabled\|max_enabled"]` | переключатель канала, `checked`, если включён (значение переключателя, **не** `channel_on`: ключ убрали — переключатель стоит, канал не работает); **не `disabled`** и при незаданных ключах (иначе не показать отказ `keys_missing`) | T-4127 test_enable_channel_without_keys_refused_with_environment_explanation, test_key_removed_from_environment_makes_channel_off_though_switch_is_on |
| `[data-keys="set\|unset"]` | состояние ключей из `settings.keys_set(канал)`: текст «ключи заданы» или «ключи не заданы» (15.5); значений нет | T-4127 test_webpush_keys_set_only_when_all_three_variables_are_set, test_telegram_and_max_keys_set_when_bot_token_is_set, test_page_shows_no_key_or_token_values |
| `[data-bot-name]` | имя бота из `BotState.bot_username` (у `telegram`, `max`; пусто — элемента нет) | T-4127 test_page_shows_bot_name_and_last_error_time_and_code_of_channel |
| `[data-channel-error]` | последняя ошибка канала (`settings.channel_error`): `data-code="<bad_token\|unavailable\|rate_limited>"`, текст по коду (15.5) и `time[data-at]` с временем записи; ошибки нет — элемента нет | T-4127 test_page_shows_bot_name_and_last_error_time_and_code_of_channel; T-4119 test_401_writes_token_not_accepted_with_time_to_channel_status; e2e/test_e08_admin |
| `table[data-defaults-table]` и `tr[data-notify-kind="<код вида>"]` | значения «вид × канал» по умолчанию: строки — все виды каталога **кроме `mandatory`** (независимо от доступности администратору); столбцы `td[data-channel="email\|push\|telegram\|max"]` с `input[type=checkbox][name="cell"][value="<код вида>:<канал>"]`, `checked` по действующим значениям (`defaults` вида или `default_channels` без `portal`); столбца «На портале» нет; `[data-narrow="cards"]` как в 14.3 | T-4127 test_page_shows_three_channels_with_switch_keys_state_and_default_values, test_changed_defaults_apply_to_employee_who_did_not_save_table; e2e/test_e08_admin test_e08_changed_defaults_apply_to_employees_who_did_not_change_table_and_not_to_those_who_did |
| `input[name="email_delay_minutes"]`, `input[name="retention_days"]` | сроки (тип `number`, **без `min`/`max`**: пределы проверяет сервер; подписи — 15.4); значение — действующее (15 и 90 по умолчанию) | T-4127 test_limit_boundaries_accepted_and_defaults_are_15_minutes_and_90_days |
| `[data-error="email_delay_minutes\|retention_days\|webpush_enabled\|telegram_enabled\|max_enabled\|defaults"]` | отказы (13.3) с `data-code`; текст — 15.4 | T-4127; e2e/test_e08_admin test_e08_mail_term_3_minutes_or_retention_10_days_refused_with_allowed_ranges, test_e08_enabling_channel_without_environment_keys_refused_with_explanation |
| пункт меню `a.menu-item[href="/settings/notifications/"]` | «Уведомления»; только с `notify.manage`; в `#main-menu` | T-4127 test_menu_item_notifications_visible_only_with_manage_permission |

## 15. Тексты

Тексты, которые ищут тесты. Правила поиска — как в CONTRACT-003 § 14: текст берётся как подстрока
видимого текста ответа (или `NotifyError.message`, или поле `message` JSON), регистр первой буквы
не проверяется; знаки «<…>» в таблицах — подставляемое значение. Колонка «Источник»: адрес строки
спеки (`spec.md:N`), плана (`plan.md:N`), задач (`tasks.md:N`, «решение N») — текст дословный;
«текст контракта» — подпись выбрана автором части, тест сверяет такой текст только по коду
причины или по `data-*` (его читает владелец на ручном проходе T-4301); «по аналогии» — вариант
для второго канала по образцу строки плана. Подписи тела писем и тема сводки (10.1-10.2,
решение C7: расхождений нет, здесь не повторяются) не переписываются.

### 15.1. Тексты уведомлений на портале и в письме (FR-316)

Тексты вносит `build` вида: виды заявок — 4.3, виды безопасности — 3.5, «Канал отвязан» — 6.13.
Подстановки: `#N` — номер заявки, `Тема` — тема заявки, обрезанная до 100 знаков по 4.3 (больше
100 — первые 99 знаков и «…»), `Очередь` — название узла-очереди (4.3).

| Вид | Текст | Источник |
|---|---|---|
| `servicedesk.new_in_queue` | «Новая заявка #N в очереди «Очередь»: Тема» | spec.md:496 (FR-316) |
| `servicedesk.assigned` | «Вам назначена заявка #N: Тема» | spec.md:497 |
| `servicedesk.requester_replied` | «Заявитель ответил в заявке #N: Тема» | spec.md:498 |
| `servicedesk.reply_failed`, событие `mail_failed` | «Письмо по заявке #N не доставлено» | spec.md:499 |
| `servicedesk.reply_failed`, `reason="quarantine"` | «Ответ по заявке #N не отправлен: вложение в карантине» | spec.md:500 |
| `servicedesk.reply_failed`, `reason="encrypted"` | «Ответ по заявке #N не отправлен: вложение — архив с паролем» | spec.md:501 |
| `notify.channel_unbound` | «Telegram отвязан: бот недоступен» и «MAX отвязан: бот недоступен» | spec.md:502; plan.md:843 |
| `core.new_device` | «Вход с нового устройства (<браузер>, <ДД.ММ.ГГГГ ЧЧ:ММ>)»; браузер — `devices.parse_user_agent`, время — по Москве (3.5); пример «Вход с нового устройства (Chrome 126, 10.10.2026 14:05)» | spec.md:503; plan.md:981; tasks.md:480 (решение 17) |
| `core.password_changed` | «Пароль изменён» | spec.md:504; plan.md:981 |
| `core.second_factor_reset` | «Второй фактор сброшен» | spec.md:505; plan.md:982 |

Ссылка записи (`Notification.url`): виды заявок — `/tickets/<номер>/` (4.3); виды безопасности — `/me/security/`;
«Канал отвязан» — `/me/notifications/` (решение A1).

Письмо по уведомлению: тема — `external_text` вида (15.2), тело — разделы 10.1 и 10.2; текст
уведомления целиком (с номером и темой) стоит в теле письма, в теме и в `job.meta` — нет. Тест
сверяет текст в списке портала с `Notification.text` и с тем, что `kind.build` вернул.

### 15.2. Тексты внешних каналов (FR-317)

Telegram, MAX и Web Push (заголовок push; ссылка — страница уведомлений, 5.2, 5.3), тема письма
(10.1): номера, темы заявок, имён и адресов нет.

| Вид | Текст | Источник |
|---|---|---|
| `servicedesk.new_in_queue` | «Новая заявка в вашей очереди» | spec.md:512-513 (FR-317) |
| `servicedesk.assigned` | «Вам назначена заявка» | spec.md:513 |
| `servicedesk.requester_replied` | «Заявитель ответил по вашей заявке» | spec.md:513 |
| `servicedesk.reply_failed` | «Ответ заявителю не ушёл» | spec.md:513-514 |
| подпись кнопки сообщения Telegram и MAX (`delivery.BUTTON_LABEL`) | «Открыть уведомления» | текст контракта: в спеке и плане подписи нет (plan.md:777-778 — «только адрес страницы»), решение E14 |
| сводка (Telegram, MAX, Web Push) | «У вас N новых уведомлений», склонение — 15.6 | tasks.md:474 (решение 14); plan.md:733 |
| системное уведомление браузера во вкладке | текст портала (`Notification.text`, 15.1): оно показывается в браузере сотрудника | spec.md:513-515 (FR-317, FR-320) |

У видов `mandatory` внешнего текста нет (`external_text == ""`, 3.2).

### 15.3. Ответы ботов (`REPLY_KEYS`, 6.14)

Текст берёт `bots.reply_text(ключ, канал)`; ключ `bound` — свой для Telegram и MAX.

| Ключ | Канал | Текст | Источник |
|---|---|---|---|
| `ask_code` | оба | «Отправьте код из раздела «Мои уведомления» портала» | plan.md:808-809; решение Opus A2 (тот же текст на сообщение из чата без начатого диалога) |
| `bound` | Telegram | «Telegram привязан к вашей учётной записи портала» | plan.md:816; spec.md:243 |
| `bound` | MAX | «MAX привязан к вашей учётной записи портала» | plan.md:816-817 («MAX привязан …») по аналогии |
| `code_invalid` | оба | «Код недействителен или просрочен. Получите новый код в портале» | plan.md:820-821 |
| `chat_taken` | оба | «Этот чат уже привязан к другой учётной записи портала» | plan.md:818-819 |
| `too_many` | оба | «Слишком много попыток, попробуйте позже» | plan.md:823 |

Ответы без кнопки и без ссылки; сообщение — простой текст (в нём нет кода, идентификаторов чата
и номера учётной записи, NFR-312). Тест сверяет `sent(channel)[-1]["text"]` с текстом строки
целиком.

### 15.4. Отказы форм и страницы (код → текст)

Текст ищется в `[data-error="<поле>"]` или `[role=alert]` (13), у JSON — в `message`; тест сверяет
код (`data-code`, `code`), а текст — только у строк, где в колонке «Тест ищет» стоит «подстроку».

| Код (6.2) | Текст | Источник | Тест ищет |
|---|---|---|---|
| `out_of_range`, `email_delay_minutes` | «Значение поля «Срок письма, минут» должно быть от 5 до 120» | 6.2 (шаблон), spec.md:627 (FR-335), название поля — текст контракта | подстроку «от 5 до 120» |
| `out_of_range`, `retention_days` | «Значение поля «Срок хранения, дней» должно быть от 30 до 365» | то же | подстроку «от 30 до 365» |
| `keys_missing` | «Канал «<Web Push, Telegram или MAX>» нельзя включить: ключи задаются в окружении установки» | plan.md:1020-1021; spec.md:312 | подстроку «ключи задаются в окружении установки» |
| `bad_defaults` | «Значения по умолчанию заданы неверно» | текст контракта | код |
| `bad_quiet_mode` | «Выберите один из трёх вариантов тихих часов» | текст контракта | код |
| `own_no_days` | «Отметьте хотя бы один день недели для своих часов» | spec.md:193 (сценарий 4: «понятное объяснение»), текст контракта | код |
| `own_bad_day` | «День недели указан неверно» | текст контракта | код |
| `own_incomplete` | «Укажите время начала и конца своих часов» | текст контракта | код |
| `own_same_time` | «Начало и конец своих часов не должны совпадать» | spec.md:193, текст контракта | код |
| `channel_disabled` (привязка) | «Канал отключён администратором» | spec.md:252; plan.md:994-995 | подстроку |
| `too_long`, `bad_endpoint`, `bad_scheme`, `has_credentials`, `bad_port`, `bad_host`, `bad_keys`, `bad_json`, `channel_disabled` (JSON push) | «Подписку этого устройства сохранить не удалось» (один текст на все коды; различает `code`) | текст контракта | код |
| успех, сохранение настроек (оба экрана) | «Настройки уведомлений сохранены.» | текст контракта | `[role=status]` непустой |
| успех, удаление устройства | «Устройство удалено.» | текст контракта | `[role=status]` непустой |
| успех, отвязка | «Telegram отвязан.» или «MAX отвязан.» | текст контракта | `[role=status]` непустой |

Названия видов и модулей берутся из каталога (3.2); названия режимов — из 2.1; названия каналов —
из 15.5. Отказы чужого и несуществующего — 404 без текста: страница ошибки ядра, подробностей нет
(FR-342).

### 15.5. Подписи и подсказки страниц

| Где | Текст | Источник |
|---|---|---|
| заголовки столбцов таблицы | «На портале», «Почта», «Push в браузере», «Telegram», «MAX» | spec.md:535; plan.md:992-993 |
| строка `tr[data-notify-fixed="security"]` (14.3) | «Безопасность: всегда» | plan.md:428; spec.md:183 (сценарий 4 п. 4); решение D4 |
| строка `tr[data-notify-fixed="channel_unbound"]` (14.3) | «Канал отвязан: всегда, только на портале» | plan.md:429; spec.md:183-184; решение D4 |
| подсказка ячейки `telegram` не привязан | «Привяжите Telegram»; у MAX — «Привяжите MAX» (по аналогии) | spec.md:180; plan.md:994 |
| подсказка ячейки `push`, нет подписки | «Разрешите push на этом устройстве» | plan.md:994; spec.md:180 |
| подсказка ячейки `telegram`, `max` при выключенном канале | «Канал отключён администратором» | plan.md:995; spec.md:252 |
| подсказка ячейки `push` при выключенном Web Push | «Push при закрытой вкладке отключён администратором» (тот же текст, что у раздела, 14.3; текст контракта: плана для ячейки нет, решение D5) | spec.md:219 |
| раздел push при выключенном Web Push | «Push при закрытой вкладке отключён администратором» | spec.md:219; plan.md:999-1001 |
| кнопка 1 | «Разрешить уведомления браузера» | tasks.md:533 (решение 34) |
| кнопка 2 | «Включить push на этом устройстве» | spec.md:207; plan.md:676; tasks.md:533 |
| браузер запретил уведомления (`[data-push-denied]`) | «Браузер запретил уведомления для этого сайта. Разрешите их в настройках браузера (значок слева от адреса страницы) и обновите страницу» | spec.md:210-211 (смысл: «объясняет, как разрешить в настройках браузера»), текст контракта |
| привязка, кнопки и статус | «Привязать», «Привязан», «Отвязать» | spec.md:243-249; plan.md:1002-1003 |
| срок кода (`[data-bind-expires]`) | «Код действует 10 минут» | spec.md:241 (FR-325); текст контракта (формулировка) |
| нет имени бота (`[data-bot-link-hint]`) | «Ссылка появится, когда бот подключится» | plan.md:806 |
| привязка выключена (`[data-disabled-text]`) | «Канал отключён администратором» | spec.md:252 |
| устройств нет (`[data-empty-state="devices"]`) | «Устройств с push пока нет» | текст контракта |
| список, пусто (`[data-empty-state="notifications"]`) | «У вас нет уведомлений»; при `f=unread` и пустой выборке — «Непрочитанных уведомлений нет» | spec.md:367; plan.md:651 (FR-319); вторая — текст контракта |
| панель колокольчика, пусто (`[data-empty-state="bell"]`) | «У вас нет уведомлений» | spec.md:367 (по смыслу), текст контракта |
| колокольчик, панель | «Все уведомления» и «Настройки» | spec.md:522; plan.md:576-577, 1099 |
| список, фильтр | «Все» и «Непрочитанные» | spec.md:525 (FR-319: «все / непрочитанные») |
| список, действия | «Прочитать все» и «Прочитать» (отметка у каждого) | spec.md:358, 525; plan.md:651, 657 (в плане действие названо «Отметить прочитанным» — 657; кнопка — «Прочитать», как в FR-319) |
| отметка непрочитанного | «новое» | текст контракта |
| заголовки страниц | `h1`: «Уведомления» (список), «Мои уведомления», «Настройки уведомлений» (страница администратора); `title` — то же | spec.md:535; plan.md:1012 («Настройки портала → Уведомления»); h1 администратора — текст контракта |
| тихие часы, режимы | «По рабочему календарю компании», «Свои часы», «Без тихих часов» | spec.md:544-545 (FR-323); 2.1 |
| тихие часы, поля | «с» и «до»; дни — «Пн», «Вт», «Ср», «Чт», «Пт», «Сб», «Вс» | текст контракта |
| администратор, ключи | «ключи заданы» и «ключи не заданы» | spec.md:309 (сценарий 8), spec.md:633 (FR-336); plan.md:1016 |
| администратор, ошибка канала | `bad_token` — «токен не принят» (у Web Push — «ключи не приняты»); `unavailable` — «канал недоступен»; `rate_limited` — «слишком много запросов»; рядом время | plan.md:849 (первая); остальные — текст контракта |
| название каналов администратора | «Web Push», «Telegram», «MAX» | plan.md:1016; spec.md:309 |
| кнопка сохранения | «Сохранить» | текст контракта |

### 15.6. Склонение чисел (решение 14 задач)

Правило русского языка, формы по `n` (целое от 1): если `n % 100` от 11 до 14 — «много» (3-я форма);
иначе `n % 10 == 1` — «один» (1-я форма); `n % 10` от 2 до 4 — «несколько» (2-я форма); иначе — 3-я
форма. Источник: tasks.md:474 (решение 14: «1 уведомление, 2 уведомления, 5 уведомлений»; тесты
сводки и писем проверяют три формы); применение — тема письма 10.1 («За нерабочее время: N
уведомлений») и текст «У вас N новых уведомлений» (15.2).

| N | Тема письма (10.1) | Сообщение (Telegram, MAX, Web Push) |
|---|---|---|
| 1, 21, 101 | «1 уведомление», «21 уведомление», «101 уведомление» | «У вас 1 новое уведомление», «У вас 21 новое уведомление» (решение Opus D7: прилагательное согласуется) |
| 2-4, 22, 24 | «2 уведомления», «22 уведомления» | «У вас 2 новых уведомления», «У вас 22 новых уведомления» |
| 5-20, 25, 100 | «5 уведомлений», «11 уведомлений», «25 уведомлений» | «У вас 5 новых уведомлений», «У вас 11 новых уведомлений», «У вас 25 новых уведомлений» |
| 11-14, 111-114 | «уведомлений» | «новых уведомлений» |

Тест (T-4108 test_external_texts_*, T-4112 test_digest_email_subject_declension_by_count и
test_digest_message_*) проверяет не меньше трёх форм (1, 2-4, 5-20) и граничные 11-14, 21, 22, 25,
101, 111.

## 16. Вопросы к Opus

### A. Часть a (разделы 1-5)

Формат: номер, суть, варианты, что предлагает автор части. Решения Opus вписываются в
разделы 1-5 отдельной сверкой; до этого тесты по спорному месту не пишутся.

| № | Суть | Варианты | Предложение |
|---|---|---|---|
| A1 | Куда ведёт ссылка записи (`Draft.url`, `Notification.url`) у видов `core.new_device`, `core.password_changed`, `core.second_factor_reset` и у `notify.channel_unbound`: в плане адреса для них нет (у видов заявок — `/tickets/<номер>/`). От ответа зависят тесты T-4105, T-4108, T-4119, T-4123 (ссылка `/notifications/<id>/open/` переходит по `url`) | 1) страница уведомлений `/notifications/` для всех четырёх; 2) безопасность — карточка профиля (устройства и пароль), «Канал отвязан» — `/me/notifications/`; 3) главная `/` | вариант 2: сотрудник попадает туда, где может проверить устройства и привязку; если адрес профиля в срезах 001-002 не фиксирован одним путём, вариант 1 |
| A2 | Что делает бот на сообщение из личного чата, где диалог не начат (нет `BotChat`): FR-325 говорит «код не принимается», но не говорит, отвечает ли бот. Тест T-4118 test_code_from_chat_without_started_dialog_is_not_accepted проверяет привязку и число сообщений бота | 1) молчит, привязки нет; 2) отвечает подсказкой «Отправьте код из раздела «Мои уведомления» портала» (как после `/start`), привязки нет | вариант 2: сотрудник не остаётся без объяснения; счётчик неверных попыток в таком чате не ведётся (строки `BotChat` нет) |
| A3 | Очищается ли запись канала в `NotifySettings.channel_status` после удачной отправки: план называет «последнюю ошибку» с временем; страница администратора по ней показывает «токен не принят» (сценарий 8, FR-337) | 1) запись остаётся до следующей ошибки; 2) удачная отправка или удачный шаг опроса канала удаляет запись канала | вариант 2: иначе «токен не принят» висит после исправления токена |
| A4 | Пауза `PAUSE_ERROR` цикла опроса после сбоя, который не 409 (сеть, 5xx, 429, 401): в плане паузы названы только для 409 (30 с) и выключенного канала (60 с); без паузы цикл при отказе службы шлёт запросы без перерыва | 1) постоянные 5 с; 2) для 429 — `RetryLater.after` (не меньше 1 с), иначе 5 с; 3) нарастающая 5, 10, 20, 40, 60 с и сброс после успеха | вариант 2: самая простая из согласных с документацией ботов; тест проверяет возвращаемое число секунд |
| A5 | Меняет ли состояние доставки `email` событие `mail.failed` для письма `notify.delivery:<номер>`: сейчас `sent` значит «передано почтовому модулю» (план, «Письма»), а исход SMTP виден только в журнале почты; сценарии 3.1 и 3.3 говорят «письмо не доставлено после всех попыток», но про доставку уведомления не сказано | 1) доставка остаётся `sent`, ничего не меняется; 2) `notify` подписывается на `mail.failed`, по `related_ref` находит доставку и переводит её в `failed` с причиной `mail_failed` | вариант 1: план закрывает «без новых механизмов»; тогда причины `mail_failed` нет, и в разделе 2.1 она не заведена |
| A6 | Когда Telegram-цикл вызывает `deleteWebhook`: план говорит «при первом запуске» | 1) один раз, пока нет строки `BotState`; 2) при каждом старте цикла | вариант 2 (в разделе 5.4 записан он): вызов безвреден, а webhook, заданный позже вручную, иначе тихо остановит опрос — уточнён решениями A6 и E5 |

**Решения Opus по вопросам A (2026-10-10).** Части b–d опираются на них; в разделы 1–5 внесено, где отмечено.
- A1: ссылка видов безопасности — `/me/security/` (страница «Безопасность» профиля, `apps/core/urls.py`;
  внесено в раздел 3); вида «Канал отвязан» — `/me/notifications/`.
- A2: из личного чата без начатого диалога бот отвечает той же подсказкой, что на `/start` («Отправьте код из
  раздела «Мои уведомления» портала»), код не принимает; групповые чаты — без ответа (решение задач, план).
- A3: запись канала в `channel_status` очищается после удачной отправки в этот канал. Расширено решением E4.
- A4: `PAUSE_ERROR` — `RetryLater.after`, если служба его назвала, иначе 5 с; после `BadToken` (401) — 60 с.
- A5: `mail.failed` состояние доставки `email` не меняет: `sent` значит «передано почтовому модулю», исход —
  в журнале доставки почты (план «Письма»).
- A6: вариант 2 с уточнением: `start_cycle` зовётся один раз в начале потока, то есть один раз за запуск процесса
  службы опроса, — это и есть «при первом запуске» плана; при каждом шаге опроса `deleteWebhook` не вызывается. Уточнено решением E5.

### B. Часть b (разделы 6-7)

Формат — как в подразделе A. Решения Opus по вопросам A (в том числе A2-A6 для `bots` и
`settings`) применены в разделах 6-7 дословно. До решений по B тесты по спорным местам не пишутся.

| № | Суть | Варианты | Предложение |
|---|---|---|---|
| B1 | Как `prefs.save` обращается с ячейками недоступных каналов: у недоступного столбца (Telegram без привязки, канал выключен) нет галочки, форма его не присылает, а значит «не отмечено» нельзя отличить от «не менял». Тот же риск у столбца `push`, который скрипт страницы блокирует до разрешения браузера (сервер разрешения не знает, решение 34 задач). От ответа зависят T-4125 test_unchecking_mail_cell_saves_own_matrix_and_keeps_portal, test_save_with_changed_cell_writes_matrix, T-4102 test_saving_only_quiet_hours_does_not_freeze_admin_defaults_into_matrix | 1) ячейки недоступных каналов сохраняют прежнее значение (в разделе 6.4 записан он; для `push` страница присылает значение скрытым полем, раздел 13 части d); 2) недоступный канал в снимке всегда выключен; 3) форма присылает значения всех ячеек, сервер пишет как есть | вариант 1: сотрудник, привязавший Telegram позже, не обнаружит выключенного канала |
| B2 | Что происходит с ожидающими доставками, когда привязка снимается: план говорит «доставка в этот канал — `failed`, причина «канал отвязан»» только в разделе «Канал отвязан», а различить «привязки не было» (`skipped`, `not_bound`) и «отвязан» при отправке без пометки нельзя | 1) `binding.unbind` (любой причины, кроме увольнения) переводит доставки `waiting` и `held` сотрудника в этом канале в `failed` с причиной `channel_unbound`, а `send_delivery` без привязки даёт `skipped` `not_bound` (был записан в 6.13; не принят — решение B2); 2) доставки остаются, `send_delivery` без привязки всегда даёт `skipped` `not_bound`, причина `channel_unbound` только у доставки, на которой пришёл `ChannelGone` | вариант 1: «Отвязать» по FR-326 прекращает отправку немедленно и сводка не тратит сообщение на канал без привязки; тест T-4119 test_delivery_to_unbound_channel_fails_with_reason_channel_unbound становится однозначным |
| B3 | Границы счётчика неверных кодов и повтора события (FR-325, план «Привязка» п. 3-4): (а) проверяется ли предел раньше кода: правильный код после пятой неверной попытки; (б) считается ли в попытки код, принятый, но чат привязан к другому, и тратится ли код; (в) как отличить повтор уже обработанного события от неверного кода | (а) 1) предел раньше проверки кода (записано: переборщик не узнает, что угадал); 2) верный код проходит всегда; (б) 1) в счётчик не входит, код не тратится (записано); 2) входит, код тратится; (в) 1) текст — использованный код, по которому этот же чат уже привязан, даёт `repeat` без ответа (записано); 2) ответ «Код недействителен» повторяется | варианты по умолчанию, как записано в разделе 6.14: тесты T-4118 test_sixth_wrong_code_in_10_minutes_gets_too_many_attempts, test_repeated_event_after_failure_gives_one_binding_and_one_reply |
| B4 | Когда удаляется использованный код привязки: FR-339 говорит «после использования», но строку с `used_at` нужно хранить, чтобы повторный ввод получил «недействителен или просрочен» (план «Привязка» п. 3), а часть тестов T-4128 называет удаление «после использования» | 1) использованные коды удаляются тем же обходом по `expires_at < сейчас` (то есть не позже чем через 10 минут после выдачи; не принят — решение B4); 2) использованный код удаляется сразу при привязке, повтор получает `code_invalid` как неизвестный | вариант 1: повтор события после сбоя остаётся различимым (`repeat`), 10 минут хранения хеша не нарушают FR-339 |
| B5 | Ответы push-сервиса, которых нет в таблице плана: 401 и 403 (сервис не принял подпись VAPID — ошибка настройки, как 401 у ботов), а также прочие 4xx кроме 400, 404, 410, 413, 429 | 1) 401 и 403 — повтор по расписанию и запись `channel_status["webpush"]` с кодом `bad_token` (администратор может исправить ключи за 24 часа); прочие 4xx — `failed` `bad_request`; 2) все такие ответы — `failed` `bad_request` без повторов | вариант 1: те же правила, что у `BadToken` ботов (план, «Канал отвязан»); подписка в обоих вариантах не удаляется |
| B6 | Имя подписанного теста T-4127 `test_disabled_channel_deliveries_are_skipped_with_reason_channel_off` говорит `channel_off`, а раздел 2.1 (часть a) закрепляет `channel_disabled` для канала, выключенного администратором или без токена, и `channel_off` только для выключенной у вида ячейки (письмо) | 1) оставить раздел 2.1: у доставки в выключенный администратором канал причина `channel_disabled`, имя теста неточное, тест проверяет `channel_disabled` (записано в 6.9); 2) объединить коды в `channel_off` | вариант 1: у двух разных причин разные коды; имя теста — только название |

**Решения Opus по вопросам B (2026-10-10).** Части c–d и авторы тестов опираются на них.
- B1: `prefs.save` для ячеек, которых форма не прислала (недоступные каналы), сохраняет прежнее значение;
  столбец `push` форма присылает всегда (на сервере он доступен).
- B2: ручная отвязка (`binding.unbind`) ожидающих доставок не трогает; отправка без привязки — `skipped` с причиной
  `not_bound`. Доставка, на которой пришёл `ChannelGone`, — `failed` с причиной `channel_unbound`.
- B3: принято как предложено: предел неверных кодов проверяется раньше кода; `chat_taken` в попытки не входит и
  код не тратит; тот же код из чата, который уже привязан этим кодом к этому сотруднику, — результат `repeat`
  без ответа бота.
- B4: FR-339 «удаляются … после использования»: обход удаляет коды с `used_at` не пусто и коды с истёкшим
  `expires_at` (не позже 30 с после использования); ночное удаление — то же. Окно повтора — решение E1.
- B5: принято: 401 и 403 push-сервиса — повтор по расписанию и `channel_status["webpush"]` с кодом `bad_token`;
  прочие 4xx (кроме 404, 410, 413, 429) — `failed` с причиной `bad_request`.
- B6: причина остаётся `channel_disabled` (раздел 2.1); имя подписанного теста T-4127 со словом `channel_off`
  неточно, тест проверяет причину по контракту.

### C. Часть c (разделы 8-12)

Формат — как в подразделах A и B. Решения Opus по вопросам A и B учтены дословно (в том числе A3,
A4, A6, B1-B6
для разделов 8-12). До решений по C тесты по спорным местам не пишутся; предложение автора части —
не решение.

| № | Суть | Варианты | Предложение |
|---|---|---|---|
| C1 | `e2e_notify_tick --shift N` сдвигает `due_at` ожидающих (`waiting`) доставок и обнуляет `enqueued_at` (иначе шаг (2) обхода не переставил бы доставку раньше `REQUEUE_AFTER_SECONDS = 120`). Нужно ли сдвигать ещё `UserNotifySettings.digest_due_at` (сценарий 7 «утренняя сводка», решение 7 задач) | 1) нет: сводка — после смены «своих часов» (`replan_digest` ставит срок «сейчас», 6.7) или после `--shift` письма в тихие часы; 2) да: `digest_due_at` у сотрудников со сроком в будущем сдвигается назад на `N` минут | вариант 1 (записан в разделе 8.2): так приёмка проверяет путь «тихие часы кончились», а не искусственно сдвинутый срок; если сценарий 7 п. 3-4 без смены часов не получится, вернуться ко 2 |
| C2 | Вид уведомлений, которые создаёт `e2e_notify_fill` (план и решение 33 говорят «тестового вида»; регистрировать новый вид в каталоге для стенда нельзя: он появился бы в таблице «Мои уведомления» у всех) | 1) `core.password_changed` — вид ядра, всегда есть в каталоге, доставок у него нет (записан в разделе 8.2); 2) `servicedesk.new_in_queue` — видимый «Новая заявка…», но каталог без `servicedesk` не знает вид; 3) запись без существующего вида (страница не найдёт название) | вариант 1: страница «Уведомления» покажет название «Пароль изменён» и текст «Тестовое уведомление N»; приёмка T-4149 проверяет число, порядок, прочитанность, а не название вида |
| C3 | `notify_vapid_keys` не защищена `E2E_STAND` (команда нужна Opus в контейнере на любой установке: пара VAPID создаётся один раз и дописывается в `.env`; на «боевой» установке такого флага нет). Команда ничего не пишет в базу | 1) не защищена (записано); 2) защищена, пара создаётся другим способом | вариант 1: плана иного пути не называет (`cryptography` на стандартном Python ключ P-256 не создаст, решение 21 задач); значения в вывод тестов не попадают |
| C4 | `object_type` и `object_id` личных событий журнала (`notify.user_settings_changed`, `notify.channel_*`, `notify.push_*`): план говорит «объект — сотрудник» | 1) `user` и номер сотрудника-владельца (записано в 9.1; объект как у `membership.*`, `user.*`, фильтр журнала по сотруднику находит и эти события); 2) свой вид `notify_user` | вариант 1; у `notify.push_removed` с причиной `moved` объект — прежний владелец подписки, а не новый |
| C5 | Вложенные ключи «было / стало» у `notify.settings_changed` (`defaults`) и `notify.user_settings_changed` (`cells`): по плану ключ — вид уведомления; код вида (`servicedesk.new_in_queue`) без русской подписи нарушил бы `test_audit_every_written_key_has_russian_label` (решение 29 задач), а `notify` не может перечислить в `FIELDS` коды чужих модулей | 1) ключ вложенного словаря — русское название вида (`NotificationKind.title`) на момент записи, значения — коды каналов (записано в 9.2); 2) ключ — код вида, а `audit_labels()` собирает подписи из `kinds.catalog()` при каждом вызове | вариант 1: проще и подпись всегда по-русски; недостаток — переименование вида меняет ключ в новых записях |
| C6 | Пишет ли `push.save` событие `notify.push_subscribed`, когда сотрудник повторно сохраняет подписку с тем же адресом (обновление ключей и устройства; страница вызывает `save` при каждом «Включить push») | 1) нет: событие только при создании строки или переносе адреса (записано в 9.2); 2) да, при каждом вызове | вариант 1: иначе журнал заполняется одинаковыми записями при каждом заходе на страницу |
| C7 | Тексты тела писем (раздел 10.2): план даёт состав (название портала, текст, ссылка, строка со ссылкой на «Мои уведомления»; у сводки — список «текст — ссылка»), а подписи «Открыть:», «Настроить уведомления:», «Все уведомления:», «За нерабочее время: N …:» и нейтральный текст «Уведомление больше недоступно.» в спеке и плане не заданы дословно (кроме нейтрального текста и темы сводки); раздел 15 (часть d) пишет тексты | 1) оставить подписи раздела 10.2, раздел 15 их не повторяет и не меняет; 2) раздел 15 становится единственным источником подписей, раздел 10.2 ссылается на него | вариант 1 до решения; в части d нужно сверить, что раздел 15 не расходится с 10.2 |
| C8 | Блок привязки в кадре сервера (`#notify-binding-<канал>`) и признак `data-count` числа: план называет блок «обновлённым блоком привязки» без идентификатора; идентификатор и скрывающий класс принадлежат разметке страницы (раздел 14, часть d) | 1) идентификатор `notify-binding-<канал>` корня блока страницы и `data-count` у `#notify-count` — общие для кадра (раздел 11.3) и страницы; часть d обязана их взять (записано); 2) блок обновляется целиком запросом HTMX, кадр несёт только сигнал | вариант 1: так решение 22 и NFR-301 выполняются без второго запроса; часть d сверяет идентификатор в разделе 14 |
| C9 | Помощник соединения (решение 6 задач): `ApplicationCommunicator` привязан к циклу событий, в котором создан, а каждый отдельный вызов `async_to_sync` создаёт свой цикл, поэтому тест, который вызывает `async_to_sync` на каждое ожидание, не получит ответов приложения. Контракт предлагает сценарий одной асинхронной функцией внутри одного `async_to_sync` (`ws_run`, `WsHub.do` для синхронных действий, раздел 11.4); у T-4100 это проверяется пробой при написании помощника | 1) один `async_to_sync` на сценарий (записано в 11.4); 2) отдельный поток с собственным циклом событий и очередью команд (но тогда `database_sync_to_async` обработчика идёт не в потоке теста и не видит его данных — решение 6 нарушается) | вариант 1; если проба в T-4100 покажет, что thread-sensitive исполнитель не отдаёт синхронные вызовы потоку теста, решение 6 нужно пересмотреть |
| C10 | Сброс стенда `notify`: строки `BotState` не удаляются, а получают `cursor=""` и `last_error=""` (имя бота остаётся). Если удалить строки, `bot_username` пропадёт, а `start_cycle` по решению A6 (в редакции E5: при старте потока и когда канал снова стал активен) вызывается не при каждом шаге, и до этого момента ссылка на бота на странице «Мои уведомления» не появится (строки `BotState` всё равно остаются, 8.3), что ломает сценарий 6 п. 1 в последующих кругах. Раздел 2.3 перечисляет `BotState` среди таблиц, «пустых после установки» | 1) строки остаются, курсоры очищены (записано в 8.3); 2) строки удаляются, приёмка перезапускает `notify-poller` после сброса | вариант 1; раздел 2.3 относится к установке, а не к сбросу стенда |
| C11 | Сброс `fakebots` из `stand_reset` идёт по `settings.TELEGRAM_API_BASE`; на установке с настоящим Telegram этот адрес — `https://api.telegram.org`, и сброс обратился бы к настоящей службе | 1) вызов только если адрес не `https://api.telegram.org` (записано в 8.3), сбой сети — предупреждение; 2) вызов по отдельной переменной окружения (например, адрес `fakebots`), задаваемой только на стенде | вариант 1: новой переменной окружения контракт не вводит (набор из восьми закреплён разделом 1.3) |
| C12 | Наблюдение: раздел 6.13 (часть b) и решение Opus B2 расходятся. Раздел 6.13 в строке `unbind` записывает вариант B2-1 («доставки `waiting` и `held` сотрудника в этом канале — `failed`, причина `channel_unbound`»), а решение B2 (2026-10-10) принимает вариант 2: ручная отвязка ожидающих доставок не трогает, отправка без привязки — `skipped` `not_bound`, `failed` `channel_unbound` — только у доставки, на которой пришёл `ChannelGone`. На журнал (раздел 9) это не влияет | — | раздел 6.13 приводится в соответствие с решением B2 отдельной сверкой Opus (разделы 1-7 эта часть не правит) — снято: 6.13 приведён |
| C13 | `--age-days`, `--age-codes`, `--shift` сдвигают **все** строки стенда, без отбора по сотруднику; приёмка T-4149 (ночное удаление: часть уведомлений старше срока хранения, часть нет) создаёт «старые» уведомления, сдвигает, затем создаёт новые | 1) все строки (записано в 8.2); 2) необязательный аргумент `--user ПОЧТА` | вариант 1 до тех пор, пока приёмка не потребует отбора |
| C14 | Уточнение к разделу 3.4 (часть a): там при проверке раз в 25 с обработчик «просто закрывает». Раздел 11.2 понимает это как `close(code=4401)` без второго `accept`: код один и тот же при подключении и при проверке, расширение `ws` после 4401 не переподключается | 1) 4401 в обоих случаях (записано); 2) код по умолчанию 1000 при проверке | вариант 1: тесты `test_check_*` сверяют код однозначно |

**Решения Opus по вопросам C (2026-10-10).** Все предложения C1–C11, C13, C14 приняты как записано в разделах 8–11.
Уточнения: C2 — `e2e_notify_fill` создаёт записи настоящего вида `core.password_changed`, а не «тестового вида»
решения 33 задач (на стенде тестовый вид не регистрируется; для страниц 10.1 и 10.4 вид неважен); C9 — один
`async_to_sync` на весь сценарий соединения (`ws_run`) — обязательное правило помощника. C12 (находка): раздел 6.13,
строка `unbind`, приведён к решению B2 (ручная отвязка доставок не трогает).

### D. Часть d (разделы 13-15)

Формат — как в подразделах A-C. Решения Opus по вопросам A, B и C учтены дословно (B1 — в 13.2 и
14.3; C2, C7, C8 — в 14.1 и 15). До решений по D тесты по спорным местам не пишутся;
предложение автора части — не решение.

| № | Суть | Варианты | Предложение |
|---|---|---|---|
| D1 | Ответ `POST /me/notifications/bind/<канал>/` без НХ: открытый код хранится только в возврате `binding.new_code` (в базе — хеш), поэтому после 302 на `GET /me/notifications/` показать код нечем (флеш-механизм ядра положил бы код в сессию, то есть в хранилище, а не «только в ответ»). План говорит «Страница показывает код и ссылку» (plan.md:802-806) | 1) НХ — фрагмент блока `#notify-binding-<канал>`, обычный POST — **200 полной страницы** с тем же блоком, без перенаправления (записано в 13.2); 2) код кладётся во флеш сессии и показывается после 302 | вариант 1: код не попадает ни в сессию, ни в `Location`, ни в журнал |
| D2 | Проверка «страница по-русски» (`test_every_slice_page_is_russian` срезов 002-003: нет латинских слов в `title`, `h1`, подписях `button`) для среза 004 даёт ложные срабатывания: подписи требуют слов «push», «Push в браузере», «Telegram», «MAX», «Web Push» (FR-302, FR-324, FR-325, FR-335 — дословно) | 1) в проверке среза 004 список слов-исключений `push`, `Push`, `Web Push`, `Telegram`, `MAX` (записано в разделе 14); 2) подписи без латиницы («Пуш») — расходятся со спекой | вариант 1 |
| D3 | Подписка `POST /me/notifications/push/` (13.2): форма тела и отказ. План даёт «адрес, ключи `p256dh` и `auth`» без формы, а правило «отказ — 200» (plan, «Контракты») выведено для HTMX, а здесь запрос делает скрипт `fetch` | форма: 1) `PushSubscription.toJSON()` — `{"endpoint", "keys": {"p256dh", "auth"}}` (записано); 2) плоская `{"endpoint", "p256dh", "auth"}`. Отказ: а) 400 JSON `{"ok": false, "code", "field", "message"}` (записано: скрипту нужен статус, HTMX тут нет); б) 200 JSON с `ok: false`. Два кода представления, которых нет в 6.2: `bad_json`, `channel_disabled` (Web Push выключен: кнопки нет, но запрос можно прислать руками) | 1 и а): готовый объект браузера без пересборки; коды представления остаются вне `NotifyError` |
| D4 | Строки обязательных видов: раздел 6.4 называет их «Безопасность: всегда» и «Канал отвязан: всегда» (по плану `Table.fixed`), а в именах T-4125 и приёмки сказано «отдельными строками без галочек» (`test_mandatory_security_kinds_shown_as_always_row_without_checkboxes`, `test_e04_security_and_channel_unlinked_kinds_shown_as_separate_rows…`) | 1) одна строка на каждый вид `mandatory` (четыре строки), ячейка «всегда» (было записано в 14.3; не принят — решение D4); 2) две сводные строки «Безопасность» и «Канал отвязан» | вариант 1: тест находит строку по коду вида и видит её название (FR-321: «показаны строкой «всегда»») |
| D5 | Ячейка `push` (решение B1 и решение 34 задач): сервер считает столбец `push` доступным всегда (6.4), а сотрудник должен видеть блокировку «Разрешите push на этом устройстве». Контракт: флажок есть всегда, **без `disabled`** (иначе браузер не пришлёт значение и B1 нарушится), блокировку несут `data-available="0"`, `data-reason` (из `web_push_available` и `web_push_reason`) и скрипт (`data-locked`, отмена щелчка). Подсказка при `channel_disabled`: плана для ячейки нет — взят текст раздела «Push при закрытой вкладке отключён администратором», а не «Канал отключён администратором» (во вкладке push при этом работает, spec.md:219-220) | 1) как записано; 2) при `channel_disabled` ячейка `push` — `data-available="0"` с «Канал отключён администратором», как у Telegram и MAX | вариант 1; тест T-4125 test_channel_disabled_by_admin_column_unavailable_with_disabled_hint проверяет `data-available="0"` и `data-reason="channel_disabled"`, а текст — по коду |
| D6 | Как форма превращается в вызовы сервисов (13.2, 13.3): флажки при снятии не присылаются, а `prefs.save` и `settings.update` различают «не менял» и «снял». Контракт вводит скрытые признаки: `table=1` (ячейки сотрудника), `channels=1`, `limits=1`, `defaults_present=1` (администратор); тихие часы — по наличию `quiet_mode`; при `own` `own_days` передаётся списком (пустой — `own_no_days`), пустые `own_start`, `own_end` — «оставить прежнее» (6.4). Без признака блок не меняется (тест, присылающий одно поле, остальное не затирает) | 1) признаки как записано; 2) каждое поле формы всегда считается присланным, и тест присылает все поля | вариант 1: тесты и приёмка пишутся короче, а затирание значений администратора случайным неполным POST исключено |
| D7 | Согласование прилагательного в «У вас N новых уведомлений» (FR-317, решение 14 задач): буквальный текст верен только при N от 5 (и 2-4: «новых уведомления»); для 1 и 21 по правилам языка — «новое уведомление» | 1) согласовать: «У вас 1 новое уведомление», «У вас 2 новых уведомления», «У вас 5 новых уведомлений» (записано в 15.6); 2) оставить «новых» при любом N, склонять только существительное | вариант 1: решение 14 требует «по правилам русского языка»; тема письма (10.1) прилагательного не содержит |
| D8 | Тексты, которых нет в спеке и плане дословно (маркируются в 15 как «текст контракта» или «по аналогии»): «MAX привязан к вашей учётной записи портала» и «Привяжите MAX» (плана — «…» и один Telegram), объяснение запрета браузера, флеш-сообщения сохранения, удаления и отвязки, названия полей сроков «Срок письма, минут» и «Срок хранения, дней», тексты отказов тихих часов и подписки, подписи ошибок канала `unavailable` и `rate_limited`, «Устройств с push пока нет», «Непрочитанных уведомлений нет» | 1) принять; тест сверяет их только по коду и `data-*`, владелец читает на T-4301 (записано в 15); 2) спросить владельца до написания тестов | вариант 1: тексты безопасно менять без правки тестов |
| D9 | Наблюдение, не вопрос. `/sw.js` без входа (13.1): план сначала говорит, что при истёкшей сессии ответ — перенаправление (его даёт промежуточный слой), а T-4230 и тест `test_sw_js_served_as_javascript_with_no_store_and_without_login` — что `login_required` нет. Контракт примиряет их так: в представлении проверки входа нет (гость — 200), перенаправление при истёкшей или ограниченной сессии даёт `SessionGuardMiddleware` (проверяется e2e); если guard пропускает гостя без сессии на `/sw.js`, расхождения нет | — | Opus подтверждает при сверке T-4230 с кодом `SessionGuardMiddleware` (список путей без входа) |
| D10 | Скрывающий класс `#notify-count` при нуле — `d-none` (Bootstrap 5.3.8, ответ на вопрос C8: имя классу ставила часть d); тест проверяет `data-count` и наличие класса в разметке, а не вычисленный стиль, кроме приёмки (`toBeHidden`) | 1) `d-none`; 2) свой класс в `portal.css` | вариант 1: класс уже в подключённой таблице стилей |
| D11 | Сверка раздела 10.2 с разделом 15 (вопрос C7, предложение 1): подписи тела писем («Открыть:», «Настроить уведомления:», «Все уведомления:», «За нерабочее время: N … :», «Уведомление больше недоступно.») остаются в 10.2, раздел 15 их не повторяет; тема сводки и склонение — 10.1 и 15.6 дают одни и те же формы | — | расхождений нет |

**Решения Opus по вопросам D (2026-10-10).** D1–D3, D5–D11 приняты как записано в разделах 13–15. D4 — нет:
спека (сценарий 4 п. 4) называет одну строку «Безопасность: всегда» и одну «Канал отвязан: всегда, только на
портале»; раздел 14.3 приведён к двум сводным строкам `tr[data-notify-fixed="security"]` и
`tr[data-notify-fixed="channel_unbound"]` (так же раздел 6.4, `Table.fixed`). D7 — «У вас 1 новое уведомление»,
«2 новых уведомления», «5 новых уведомлений».

### E. Решения Opus по проверке контракта (партии K1-K5, 2026-10-10)

Проверка коммита 5988a13 пятью партиями (покрытие имён тестов T-4101…T-4151, утверждения о коде, тексты и тихие
решения). Внесены решения, которые уже были приняты, но не дошли до разделов: A4 (5.4), B4 (2.2, 6.9, 6.13, 6.15),
B5 (2.1, 2.2, 6.9); пометки «вопрос X» в разделах 1-15 заменены на «решение X». Новые решения:
- E1: после B4 повтор события (`repeat`) различим, пока обход не удалил использованный код (до 30 с); позже тот же текст
  даёт `code_invalid`. Тест `repeat` обход между событиями не зовёт.
- E2, E3: номера не заняты (A4 и B5 внесены как приняты).
- E4: A3 шире: шаг опроса при `BadToken` пишет `channel_status` с кодом `bad_token`, удачный шаг очищает запись канала, только если в ней `bad_token` (ошибки отправки остаются до удачной отправки);
  прочие сбои опроса (409, сеть, 5xx, 429) — только `BotState.last_error`. Страница администратора показывает
  `channel_status`.
- E5 (уточняет A6): `start_cycle(channel) -> bool` — начало цикла: при старте потока и снова, когда канал стал активен
  после неактивности; пока не удался — перед каждым шагом. Неактивный канал — без сети и записей. Иначе канал,
  включённый администратором после запуска службы, остался бы без имени бота и без `deleteWebhook`.
- E6: курсор Telegram — последний обработанный `update_id` (план, «Модель данных»), в запрос — `offset = курсор + 1`.
- E7: шаг (2) обхода — в порядке плана: сначала постановка `waiting`, затем возврат `sending`.
- E8: `related_ref` письма заявки — `ticket:<pk>` (код среза 003).
- E9: при создании заявки отдельного `assignee_changed` нет; `ticket_transferred` публикуется в конце `_move`.
- E10: пересечение обходов проверяется двумя последовательными `send_due` и `FOR UPDATE SKIP LOCKED` в запросе.
- E11-E13: помощники и точки подмены — `webpush_on`, `subscribe`, каталог без сервис-деска, `send_rendered`,
  `live.get_channel_layer`, `telegram.client.ssl_context`.
- E14: сообщение бота — `html.escape(external_text)` и кнопка «Открыть уведомления» (текст контракта: в спеке и плане
  подписи нет, владелец читает её на T-4301 и T-4307) со ссылкой `PORTAL_URL/notifications/`; «динамическая часть» в
  тестах экранирования — `external_text` тестового вида с разметкой.
- E15-E17: `webpush_capture` (ответ по адресу подписки, крючок перед ответом), `BrowserKeys`, `bots_capture`, формы
  запросов Telegram, `fake_bot_send`; у Web Push в `log` только записи подписок; `attempts` у `next_due` — число
  сделанных попыток.
- E18: исключение `handle_update` поднимается из `poll_once`, курсор не записывается.
- E19: «таблица компонентов» — метаданные установленных пакетов, лицензия и запись `htmx-ext-ws`.
- E20: канал сводки — по плану (первый с `held`); следствие B2 — `skipped` `not_bound`; вопрос — в следующую версию плана.
- E21: `#notify-bell[data-ws]` — признак готовности соединения после первого кадра.
- E22: вкладка показывает уведомление конструктором `Notification`, сервис-воркер — `showNotification`; как видит приёмка;
  нажатие во вкладке открывает ссылку в той же вкладке и закрывает уведомление, воркер по нажатию закрывает уведомление
  и открывает ссылку того же источника (выбор контракта; FR-320 и план говорят только «открывает ссылку»).
- E23: клиент `fakebots` приёмки — в `helpers_notify.py`; запуск Chrome и Edge; срок сводки в приёмке.
- E24: тихие выборы частей c-d приняты: возврат на тот же `f` и `page` после «Прочитать»; блок `disabled` без кнопок
  (сценарий 6 спеки, имя теста T-4126); отказ настроек администратора ничего не сохраняет; h1 «Настройки уведомлений».
- E25: неточные имена подписанных тестов помечены в ячейке «Тесты» по образцу B6 (T-4119 …unbound_channel… — B2;
  T-4111 test_overlapping_ticks_send_one_email — E10).
- E26: при 429 на нескольких подписках Web Push срок повтора считается по наибольшему `Retry-After` из них.
- E27: приёмка (T-4148) сверяет браузер в тексте «Вход с нового устройства» с тем, что `devices.parse_user_agent` вернул
  для её `User-Agent`, а не с буквальным «Chrome» (у безголового Chrome семейство может быть другим).
- Покрытия нет: ветви 401, 403 и прочих 4xx Web Push (решение B5) — ни одно имя T-4116 их не называет; тест добавляет
  следующая версия задач (очередь HANDOFF).

## 17. Дополнения Opus по вопросам исполнителей Этапа 2

Дописываются по ходу волн тестов; номера не меняются, строки выше не сдвигаются. Дополнение главнее текста разделов
1-16 (из двух дополнений — с большим номером). «Затрагивает» — задачи и файлы, которые обязаны ему следовать.

1. **Сбой `handle_update` в тестах шага опроса** (2026-10-10, проверка параметров P2). Чтобы проверить решение E18
   (исключение из `handle_update` поднимается из `poll_once`, курсор не записан, предыдущие события зафиксированы), тест
   подменяет `apps.notify.services.bots.handle_update` обёрткой: на заданном событии она поднимает исключение, на
   остальных зовёт настоящую функцию. Поэтому `poll_once` зовёт `handle_update` как имя модуля `bots` при каждом вызове
   (обычный вызов функции модуля), а не через ссылку, сохранённую заранее. Подмена разрешена только в этих двух тестах.
   Затрагивает: T-4120 (`test_cursor_not_saved_when_batch_fails_and_event_repeats_safely`,
   `test_each_event_is_handled_in_its_own_transaction`), реализацию T-4213.
2. **`ws_run` и `close_old_connections`** (2026-10-10, проба T-4100, решения 6 задач и C9). `channels.db.database_sync_to_async`
   зовёт `close_old_connections()` до и после вызова; внутри транзакции теста это закрывает соединение и рвёт транзакцию
   (`connection is closed`). `support_notify.ws_run` на время сценария подменяет `channels.db.close_old_connections` пустой
   функцией и возвращает прежнее значение в `finally`; на работу обработчика вне тестов это не влияет. Обработчик
   соединения не должен звать `close_old_connections` или закрывать соединение базы сам. Затрагивает: T-4109, T-4118,
   T-4122, T-4124 (через `ws_run`), реализацию T-4216 (`consumers.py`).
3. **Возврат фикстуры `bots_on`** (2026-10-10, T-4100). Фикстура возвращает клиент `support_notify.FakeBots` (уже
   сброшенный `/_test/reset`): тест пишет `bots_on.put_telegram(...)`, `bots_on.sent("telegram")`. `FakeBots` отказывает
   (`RuntimeError`), если адрес оканчивается на `telegram.org`: серверный тест не может уйти в настоящий Telegram.
   Затрагивает: T-4109, T-4112, T-4118…T-4120, T-4122, T-4125…T-4127, T-4131.
4. **Подписка Web Push с устройством** (2026-10-10, проверка параметров P1). У `support_notify.subscribe` параметра
   устройства нет (§ 1.1): подписка создаётся без устройства. Тест, которому нужна подписка устройства сессии (выход,
   «забыть устройство», «закрыть сессию», каскад), создаёт её сам: `push.save(user, endpoint=<https-адрес разрешённого
   хоста>, p256dh=…, auth=…, device_id=<UserSession.device_id сессии клиента>)` с ключами `support_notify.browser_keys()`,
   либо через представление `POST /me/notifications/push/` (§ 13.2: устройство берётся из сессии). Затрагивает: T-4105,
   T-4115, T-4117.
5. **Расшифровка нагрузки Web Push** (2026-10-10, проверка помощника). `webpush_capture(...).decrypt(request, keys)` требует
   у расшифрованной записи разделитель последней записи `0x02` (§ 5.3, `crypto.encrypt`); другой разделитель — `ValueError`
   помощника, то есть тест упадёт на неверном шифровании. Затрагивает: T-4108, T-4116.
6. **`prefs.channels_for(user_id, kind)` — `kind` объект** (2026-10-10, вопрос T-4101). Второй аргумент — объект
   `NotificationKind` (как его возвращают `kinds.get(code)` и `kinds.for_event(name)`), а не код вида; так же его зовут
   `dispatch.create` и `mail.send_due`. Затрагивает: T-4101, T-4102, T-4109, T-4111, T-4112.
7. **Вложенные обработчики «после фиксации»** (2026-10-10, вопрос T-4107; проверено по Django 5.2.17). Фикстура
   `django_capture_on_commit_callbacks(execute=True)` и `support_notify.run_tick()` (тот же `TestCase.captureOnCommitCallbacks`)
   исполняют и обработчики, поставленные во время исполнения других (цепочки `mail.failed` → `servicedesk.mail_failed` →
   `dispatch` и подобные): своих помощников, разбирающих `connection.run_on_commit`, тесты не заводят. Затрагивает: все
   задачи; T-4107 — заменить свой помощник `_settle` фикстурой.
8. **`push.save` и выключенный Web Push** (2026-10-10, вопрос T-4105). Сервис `push.save` (§ 6.12) не проверяет, включён
   ли Web Push: отказ `channel_disabled` даёт только представление `POST /me/notifications/push/` (§ 13.2) раньше вызова
   сервиса. Тест, создающий подписку сервисом, включать канал не обязан; страницы и доставка по-прежнему требуют
   `webpush_on`. Затрагивает: T-4105, T-4115, T-4117.
9. **Ссылка на тест в § 6.9** (2026-10-10, вопрос T-4108). В строке `external_text` (§ 6.9) имя
   `test_message_has_no_ticket_number_subject_names_or_addresses` — тест T-4119 (`test_notify_bots_2.py`), а не T-4108;
   T-4108 проверяет то же своими `test_external_texts_*`. Проверку склонения «У вас N новых уведомлений» (§ 15.6) T-4108
   держит в `test_external_texts_of_four_sd_kinds_are_verbatim`, T-4112 — в своих тестах сводки. Затрагивает: T-4108,
   T-4119.
10. **`prefs.save(table=…)` без строки вида** (2026-10-10, вопрос T-4102). Вид из `effective(user).rows`, которого нет среди
    ключей `table`, не меняется (его ячейки остаются действующими); пустой список у вида — «все внешние каналы выключены».
    Представление (§ 13.2) по-прежнему присылает все строки. Затрагивает: T-4102, T-4125.
11. **Бюджет 90 с у Web Push и итог доставки** (2026-10-10, вопрос T-4116; план «Отправка», шаг 3). Если бюджет
    `WEBPUSH_BUDGET_SECONDS` вышел, а подписки, которым ещё не слали, остались, — доставка `waiting` с прежним `due_at`
    и `enqueued_at=None`, даже если какая-то подписка уже ответила 2xx: оставшиеся получат push при продолжении. Правило
    «хотя бы одна подписка удалась — `sent`» (§ 6.9) действует, когда подписок без попытки в этом вызове не осталось.
    Затрагивает: T-4116 (`test_job_after_90_seconds_starts_no_new_subscription_and_returns_delivery_to_waiting`), T-4113.
12. **Заголовок `Topic` у Web Push** (2026-10-10, вопрос T-4116). `send_webpush` зовёт `client.send` без `topic`: заголовка
    `Topic` у доставок нет (план его не называет). Затрагивает: T-4116.
13. **Очередь заявки в `build` видов сервис-деска** (2026-10-10, вопрос проверки R-1-d). `build` берёт очередь, ответственного
    и состояние заявки из базы по `data["number"]` на момент обработки события (§ 4.3, первая строка таблицы); слова
    «при `ticket_transferred` очередь — `to_queue_id`, при `ticket_created` — `queue_id`» (§ 4.3, `new_in_queue.build`)
    означают, что в обычном случае эти значения совпадают с текущей очередью в базе, а не что очередь берётся из данных
    события. Затрагивает: реализацию T-4202 (виды сервис-деска); T-4106, T-4107 — тесты от этого не зависят.
14. **Сводка: какие `held` становятся `digested` и когда очищается срок** (2026-10-10, вопросы T-4112; план «Тихие часы
    и сводка», шаг 5). «Использованные» доставки шага (5) § 6.11 — все `held` сотрудника, прошедшие проверки шага (2):
    доставки `email`, вошедшие в письмо, доставки выбранного канала сообщения **и доставки невыбранных каналов**
    сообщения (`max`, `webpush` при выбранном `telegram` и т. п.): одна сводка заменяет их все, отдельных сообщений в
    невыбранные каналы нет. `digest_due_at = None` ставится всегда, когда шаг (1) пройден (рабочее время), — и тогда,
    когда `Digest` не создан (все `held` отсеяны шагом (2) или их не было). Затрагивает: T-4112, реализацию T-4211.
15. **Тексты `CryptoError`, дубли в `enqueue`, последняя попытка в `log`** (2026-10-10, вопросы проверки R-2-c и T-4114,
    T-4113). (а) Три текста `CryptoError` § 5.3 дословные (выбор контракта, как § 15): тест вправе сравнивать
    `str(exc)` равенством; плохие `p256dh` или `auth` — «неверные ключи подписки», плохой закрытый ключ VAPID у `vapid` —
    «неверный ключ VAPID», плохой `sender_private_key` у `encrypt` (точка для тестов) — «неверные ключи подписки»,
    длинная нагрузка — «нагрузка слишком длинная». (б) `delivery.enqueue(ids)` с повтором номера в одном списке ставит
    одно задание на номер; тесты на повторы опираются на повторные вызовы, а не на дубли в одном списке. (в) Попытка,
    после которой `next_due` вернул `None`, пишется в `log` с `outcome="failed"` и `reason` самой попытки (`server_error`
    для 5xx, `timeout`, `network`, `rate_limited`, `bad_token`); `Delivery.reason = "expired"`. Ответ 5xx у ботов и
    Web Push — `reason="server_error"`. Затрагивает: T-4113, T-4114, T-4116, T-4119, реализацию T-4207, T-4209.
16. **Длина `PushSubscription.browser` и `platform`** (2026-10-10, вопрос проверки R-2-d; уточнение § 2.2). Поля —
    `CharField(128, blank=True)`, как у моделей устройств ядра: `devices.parse_user_agent` отдаёт до 128 знаков.
    Затрагивает: T-4115, реализацию T-4203.
17. **Исход `failed` в `Delivery.log`** (2026-10-10, вопрос проверки R-2-e; уточнение § 2.2). `outcome="failed"` пишется у
    неповторяемых итогов (`bad_request`, `redirect`, `channel_unbound`) и у последней попытки (дополнение 15 (в));
    `outcome="gone"` — у подписки, ответившей 404 или 410. Затрагивает: T-4113, T-4116, T-4119.
18. **Таблица «Мои уведомления» без строк видов и порядок причин Web Push** (2026-10-10, вопросы проверки R-1-a).
    (а) `table[data-notify-table]` с пятью заголовками и `tbody[data-fixed-rows]` (две сводные строки, решение D4) есть
    на странице всегда, в том числе когда у сотрудника нет ни одной строки вида (`effective(user).rows == []`).
    (б) `Table.web_push_reason`: Web Push выключен администратором или ключей нет — `channel_disabled` (главнее), иначе
    подписок нет — `no_subscriptions`, иначе `""`; так же `Channel.reason` у Telegram и MAX: `channel_disabled` главнее
    `not_bound`. (в) Порядок ключей словаря `Table.channels` не задан (порядок задан только у `Row.cells`).
    Затрагивает: T-4101, T-4102, T-4125, реализацию T-4204.
19. **Подмена `secrets.randbelow` в тестах кода привязки** (2026-10-10, вопрос T-4118). `binding.new_code` зовёт
    `secrets.randbelow(10**8)` через модуль (`import secrets`; не `from secrets import randbelow`), поэтому тест подменяет
    `monkeypatch.setattr(secrets, "randbelow", …)` — только в тестах совпадения кода с действующим кодом другого
    сотрудника и дополнения нулями до восьми цифр. Адрес кнопки сообщения бота проверяет T-4119 (решение E14), T-4118 его
    не проверяет. Затрагивает: T-4118, реализацию T-4213.
20. **Уточнения по проверке волны 3** (2026-10-10, R-3-a, R-3-b, R-3-e). (а) Запись `Delivery.log` попытки, на которой
    пришёл `ChannelGone`: `outcome="failed"`, `code=403`, `reason="channel_unbound"`. (б) Скрытые поля формы «Прочитать»
    (§ 14.2): `page` — номер текущей страницы списка (`"1"` на первой), `f` — текущий фильтр (`"unread"` или пусто); у
    «Прочитать все» — только `f`. (в) Ответ `/notifications/bell/` — содержимое панели (список, «Все уведомления»,
    «Настройки»), которое вставляется внутрь `#notify-bell-panel[data-bell-panel]` (`hx-swap="innerHTML"`); сам контейнер в
    ответ не входит. (г) Окно неверных кодов (§ 6.14): при перезапуске окна `window_started_at = сейчас` и `bad_attempts = 0`
    — на текущем тексте из начатого чата, до сверки кода. (д) `POST /me/notifications/bind/<канал>/` и
    `/unbind/<канал>/` без входа — 302 на `/login/` (общее правило § 13). Затрагивает: T-4118, T-4119, T-4123, T-4124,
    реализацию T-4213 (боты) и T-4230 (маршруты и страницы).
21. **Уточнения по вопросам волны 4** (2026-10-10, T-4125, T-4126, T-4127, T-4129, T-4131). (а) Отказ «Мои уведомления» на
    НХ-запрос — фрагмент с корнем `#notify-prefs-root` (§ 13.2); `hx-target="#notify-prefs-root"` и `hx-swap="outerHTML"`
    стоят на форме, тест проверяет корень фрагмента и `[data-error]`. `[data-hint]` недоступной ячейки лежит внутри её
    `td[data-channel]`. Подписи сводных строк — § 15.5 (подстрока допустима). (б) Журнал `notify.user_settings_changed` до
    первого сохранения: «было» у `quiet_mode` — `"calendar"`, у `own_days` — `[]`, у `own_start`/`own_end` — `null`; в записи
    только изменившиеся ключи. (в) Журнал `notify.settings_changed`, ключ `defaults`: вид попадает в запись, только если
    изменился его **действующий** список каналов (нет в словаре — действуют `default_channels` без `portal`); «было» —
    `null`, если вида не было в словаре (решение C5), «стало» — `null`, если вид из словаря убран; форма, присылающая всю
    таблицу, неизменённых видов в запись не добавляет. (г) Отказ `settings.update` — одна `NotifyError` (первая по порядку
    проверки полей), на странице один `[data-error]`. (д) `quiet_mode` в POST `/me/notifications/` необязателен (§ 13.2);
    присланный `calendar` при прежнем `calendar` изменением не считается. (е) Раздел «Мои уведомления» карточки — на своём
    профиле `/me/` (разделы `card_sections(user, user)`) и на `/staff/<id>/` только когда зритель — владелец; у чужой
    карточки раздела нет. (ж) Тесты сброса стенда (§ 8.3) фикстуры `bots_on` и `webpush_on` не берут: они пишут
    `NotifySettings` через соединение `default` и держат строку, которую сброс через `migrate` пересоздаёт; адрес `fakebots`
    — из `settings.TELEGRAM_API_BASE`, клиент — `support_notify.FakeBots()`; ожидающие события учебной службы тест читает
    закрытым `FakeBots._call` (помощник наш) или прямым запросом `getUpdates`. (з) Ключ `requeued` вывода
    `e2e_notify_tick` — ключ словаря `tick` (§ 6.9): число доставок, поставленных шагом (2) обхода. Затрагивает: T-4125,
    T-4126, T-4127, T-4129, T-4131, реализацию T-4215, T-4231, T-4232.
