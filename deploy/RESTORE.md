# Восстановление портала из резервной копии

Документ описывает порядок восстановления базы и файлов портала из копий одной ночи. Копии делает служба `backup`
(скрипт `backup.sh`): дамп базы и два архива томов с одной и той же отметкой даты; лежат они в томе `backups`. Все шаги выполняет администратор
в каталоге `deploy/`, по порядку. Потеря данных ограничена сутками (RPO 24 часа): всё, что создано после копии, пропадёт.

## Шаг 1. Остановить службы

Остановите службы, которые пишут в базу и тома: `web`, `worker`, `worker-mail`, `worker-inbox`, `worker-notify`, `notify-poller`, `scheduler`. Остановите и службу
`backup`: иначе ночная копия в 01:30 может снять полувосстановленную базу.

    docker compose stop web worker worker-mail worker-inbox worker-notify notify-poller scheduler backup

База (`postgres`), `valkey` и остальные службы продолжают работать.

## Шаг 2. Восстановить базу

Дамп `crm-<дата>.dump` лежит в томе `backups`; он смонтирован в службе `backup` (на `/backups`), и в ней же есть `pg_restore`
и задан `DATABASE_MIGRATE_URL` (адрес базы владельца схемы `crm_owner`; пароль в нём, в команде и в этом документе его
нет: `***`). Дамп восстанавливается со сносом прежних объектов; `<дата>` — отметка ночи копии, например `2026-10-07`:

    docker compose run --rm --no-deps backup 'pg_restore --clean --if-exists --no-owner --role=crm_owner -d "$DATABASE_MIGRATE_URL" /backups/crm-<дата>.dump'

## Шаг 3. Восстановить тома protected и media

Тома берутся из копий той же ночи, что и дамп: `protected-<дата>.tgz` и `media-<дата>.tgz`. Распакуйте архив каждого
тома в свой том (`protected`, затем `media`; `<проект>` — имя проекта compose, префикс имён томов; в этом развёртывании — `crm`, тома
`crm_protected`, `crm_media`, `crm_backups`). Сначала проверяется, что архив есть, и только затем том очищается (вместе с
файлами на точку) и распаковывается; при опечатке в дате или имени тома очистка не начнётся. Владельцы файлов сохраняются.

    docker run --rm -v <проект>_protected:/data -v <проект>_backups:/backup:ro alpine sh -c "test -f /backup/protected-<дата>.tgz && find /data -mindepth 1 -delete && tar -xzf /backup/protected-<дата>.tgz -C /data"
    docker run --rm -v <проект>_media:/data -v <проект>_backups:/backup:ro alpine sh -c "test -f /backup/media-<дата>.tgz && find /data -mindepth 1 -delete && tar -xzf /backup/media-<дата>.tgz -C /data"

## Шаг 4. Сдвинуть номера заявок и разобрать письма

Команда выполняется от владельца схемы через службу `migrate` (в ней есть `DATABASE_MIGRATE_URL`; у роли приложения
`crm_app` на последовательности только `USAGE`, а для `setval` нужна запись):

    docker compose run --rm migrate python manage.py servicedesk_after_restore

Оговорка: у службы `migrate` включено `RUN_MIGRATIONS=1`, поэтому её entrypoint сначала применит миграции, а затем
выполнит команду.

Команда сдвигает последовательность `servicedesk_ticket_number` на 1000 номеров вперёд от наибольшего из её значения и
наибольшего номера заявки в базе, поэтому номера, выданные после копии, повторно не выдаются. Повторный запуск безопасен
и сдвигает ещё на 1000. Затем она ставит разбор письмам во входящих в состоянии `received`. Вывод:
`after_restore: sequence=<N> max_number=<M> requeued=<K>`.

Письма, пришедшие после копии, опрос ящика заберёт сам. Заявки, созданные после копии, теряются в пределах RPO.

## Шаг 5. Запустить службы

Запустите остановленные службы, включая `backup`, и проверьте вход и список заявок:

    docker compose up -d web worker worker-mail worker-inbox worker-notify notify-poller scheduler backup

Уведомления после восстановления: файл `.env` восстановлением не меняется и в копию не входит. Токены ботов и ключи VAPID
(`TELEGRAM_BOT_TOKEN`, `MAX_BOT_TOKEN`, `VAPID_PRIVATE_KEY`) лежат только в нём; перенесите их на новое место вместе с
`.env` (значения в документе — `***`). Пару VAPID не выпускайте заново: подписки браузеров привязаны к прежнему открытому
ключу. Очереди и присутствие в `valkey` восстановления не требуют; недоставленные уведомления `worker-notify` разберёт
сам обходом доставок.
