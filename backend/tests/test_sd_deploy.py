"""T-3135: развёртывание и расписание среза 003 (FR-210, NFR-206, NFR-210). Сценарии — «Запуск», «Интеграции»,
«Копии» плана и § 1 контракта.

Читает файлы `deploy/` (служба `test` монтирует их в /app/deploy только для чтения), `backend/config/cron.py` и
`backend/config/settings.py`, как test_deploy_files.py срезов 001–002 (образец стиля). Время `rq cron` — по UTC:
ночные задания назначены по Москве минус три часа (таблица «Расписание» § 1).
"""
import ast
import re

import pytest

from tests.support import BACKEND_DIR, repo_file

WORKERS = ("worker", "worker-mail", "worker-inbox")
NEW_JOBS = {
    # имя: (очередь, строка cron по UTC, job_timeout)
    "poll_mailbox": ("inbox", "* * * * *", 600),
    "requeue_inbound": ("inbox", "*/5 * * * *", 300),
    "autoclose": ("maintenance", "5 * * * *", 600),
    "reconcile_assignees": ("maintenance", "25 * * * *", 600),
    "purge_inbound": ("maintenance", "10 23 * * *", 600),
    "anonymize_tickets": ("maintenance", "20 23 * * *", 600),
    "purge_requester_previews": ("maintenance", "30 23 * * *", 300),
    "purge_orphan_files": ("maintenance", "50 23 * * *", 600),
}
NOTIFY_JOBS = {
    # имя: (очередь, интервал в секундах или None, строка cron по UTC или None, job_timeout); CONTRACT-004 § 1.3
    "notify_tick": ("notify", 30, None, 120),
    "notify_retention": ("maintenance", None, "40 23 * * *", 600),
}
KNOWLEDGE_JOBS = {
    # имя: (очередь, интервал в секундах или None, строка cron по UTC или None, job_timeout); CONTRACT-005, раздел 1.2
    "purge_trash": ("maintenance", None, "45 23 * * *", 600),
}
LISTS_JOBS = {
    # имя: (функция, очередь, интервал в секундах или None, строка cron по UTC или None, job_timeout); CONTRACT-006,
    # раздел 1.2: имя задания не совпадает с именем функции, поэтому сверка — отдельно от цикла «имя = функция»
    "lists_reminders": ("remind_deadlines", "maintenance", None, "0 5 * * *", 600),
}
# время по Москве (час, минута) у ночных заданий — из таблицы «Расписание» § 1
MOSCOW_NIGHT = {
    "purge_inbound": (2, 10), "anonymize_tickets": (2, 20),
    "purge_requester_previews": (2, 30), "purge_orphan_files": (2, 50),
}
OLD_JOBS = {
    "purge_login_history": "10 3 * * *", "purge_expired_links": "20 3 * * *",
    "purge_expired_sessions": "30 3 * * *", "purge_import_previews": "40 3 * * *",
    "purge_quarantine": "50 3 * * *", "requeue_pending_scans": "0 * * * *",
}


def deploy_text(*parts: str) -> str:
    return repo_file("deploy", *parts).read_text(encoding="utf-8")


def uncommented(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def compose_services() -> dict[str, str]:
    """Блоки служб docker-compose.yml: имя → текст (без комментариев)."""
    blocks, current, in_services = {}, None, False
    for line in uncommented(deploy_text("docker-compose.yml")).splitlines():
        if re.match(r"^services:\s*$", line):
            in_services = True
        elif re.match(r"^\S", line):
            in_services = False
        elif in_services and (m := re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)):
            current = m.group(1)
            blocks[current] = ""
        elif in_services and current:
            blocks[current] += line + "\n"
    return blocks


def block(name: str) -> str:
    services = compose_services()
    assert name in services, f"в docker-compose.yml нет службы {name}"
    return services[name]


def depends_on(service_block: str) -> dict[str, str]:
    result, in_section, current = {}, False, None
    for line in service_block.splitlines():
        if re.match(r"^    depends_on:\s*$", line):
            in_section = True
        elif in_section and re.match(r"^    \S", line):
            in_section = False
        elif in_section and (m := re.match(r"^      ([A-Za-z0-9_-]+):\s*$", line)):
            current = m.group(1)
            result[current] = ""
        elif in_section and current:
            result[current] += line + "\n"
    return result


def env_keys(service_block: str) -> dict[str, str]:
    """Ключи раздела `environment` службы (словарная форма): имя → значение как в файле."""
    result, in_section = {}, False
    for line in service_block.splitlines():
        if re.match(r"^    environment:\s*$", line):
            in_section = True
        elif in_section and re.match(r"^    \S", line):
            in_section = False
        elif in_section and (m := re.match(r"^      ([A-Za-z0-9_]+):\s*(.*?)\s*$", line)):
            result[m.group(1)] = m.group(2)
    return result


def command_of(service_block: str) -> str:
    """Команда службы одной строкой (строка, `>-` или список) без кавычек и скобок."""
    lines = service_block.splitlines()
    for i, line in enumerate(lines):
        if m := re.match(r"^    command:\s*(.*)$", line):
            parts = [m.group(1)]
            for follow in lines[i + 1:]:
                if re.match(r"^      \S", follow) and not re.match(r"^    \S", follow):
                    parts.append(follow.strip())
                else:
                    break
            text = " ".join(parts)
            text = re.sub(r"^[>|][-+]?\s*", "", text)
            return re.sub(r"\s+", " ", re.sub(r"[\[\]\"',]", " ", text)).strip()
    return ""


def rq_queues(service_block: str) -> list[str]:
    """Очереди из команды `rq worker -c config.rq_settings --with-scheduler <очереди>` (по порядку)."""
    command = command_of(service_block)
    m = re.fullmatch(r"rq worker -c config\.rq_settings --with-scheduler ([a-z ]+)", command)
    assert m, f"ожидается `rq worker -c config.rq_settings --with-scheduler <очереди>`, найдено: {command!r}"
    return m.group(1).split()


def mounts(service_block: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"^\s+-\s*[\"']?([^\s\"']+:[^\s\"']+)[\"']?\s*$", service_block, re.M)]


def top_volume_names() -> set[str]:
    names, inside = set(), False
    for line in uncommented(deploy_text("docker-compose.yml")).splitlines():
        if re.match(r"^volumes:\s*$", line):
            inside = True
        elif re.match(r"^\S", line):
            inside = False
        elif inside and (m := re.match(r"^  ([A-Za-z0-9_-]+):", line)):
            names.add(m.group(1))
    return names


def cron_registrations() -> list[dict]:
    """Вызовы `register(...)` в config/cron.py (разбор дерева): функция, очередь, расписание (`cron` или `interval`), имя, job_timeout."""
    tree = ast.parse((BACKEND_DIR / "config" / "cron.py").read_text(encoding="utf-8"))
    constants = {node.targets[0].id: node.value.value for node in ast.walk(tree)
                 if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                 and isinstance(node.value, ast.Constant)}

    def value(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return constants.get(node.id)
        return None

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "register":
            first = node.args[0] if node.args else None
            function = first.id if isinstance(first, ast.Name) else getattr(first, "attr", None)
            keys = {kw.arg: value(kw.value) for kw in node.keywords}
            found.append({"function": function, "queue": keys.get("queue_name"), "cron": keys.get("cron"),
                          "interval": keys.get("interval"), "name": keys.get("name"), "job_timeout": keys.get("job_timeout"),
                          "has_job_timeout": "job_timeout" in keys})
    return found


def cron_by_name() -> dict[str, dict]:
    result = {}
    for item in cron_registrations():
        assert item["name"] not in result, f"задание {item['name']} зарегистрировано дважды"
        result[item["name"]] = item
    return result


# --- nginx ------------------------------------------------------------------------------------------------------

def nginx_text(name: str) -> str:
    return uncommented(deploy_text(name))


def location_body(text: str, header: str, *, required: bool = True) -> str | None:
    """Тело `location <header> { … }` (header — регулярное выражение между `location` и `{`)."""
    m = re.search(r"location\s+" + header + r"\s*\{", text)
    if not m:
        assert not required, f"нет location {header}"
        return None
    depth, i = 1, m.end()
    while depth and i < len(text):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[m.end():i - 1]


def directives(body: str) -> list[str]:
    return [re.sub(r"\s+", " ", part).strip() for part in body.split(";") if part.strip()]


REQUEST_LOCATION = r"=\s+/request/"
TICKETS_LOCATION = r"~\s+\^/tickets/\(new/\|\[0-9\]\+/reply/\)\$"
ATTACHMENTS_LOCATION = r"/protected/attachments/"
INBOUND_LOCATION = r"/protected/inbound/"
KB_FILES_LOCATION = r"~\s+\^/kb/\[0-9\]\+/files/\$"


def _check_form_location(name: str, header: str) -> None:
    text = nginx_text(name)
    body = location_body(text, header)
    own = directives(body)
    assert "client_max_body_size 55m" in own, f"{name}: нет `client_max_body_size 55m;`"
    main = directives(location_body(text, r"/"))
    required = ("proxy_pass ", "proxy_set_header ", "proxy_read_timeout ")  # дополнение 39 (б): прочие proxy_* по желанию
    proxy_main = {d for d in main if d.startswith(required)}
    proxy_own = {d for d in own if d.startswith("proxy_")}
    assert any(d.startswith("proxy_pass ") for d in proxy_own), f"{name}: нет proxy_pass"
    assert any(d.startswith("proxy_set_header ") for d in proxy_own), f"{name}: нет proxy_set_header"
    assert any(d.startswith("proxy_read_timeout ") for d in proxy_own), f"{name}: нет proxy_read_timeout"
    assert proxy_main <= proxy_own, f"{name}: не повторены директивы location /: {sorted(proxy_main - proxy_own)}"
    assert re.findall(r"client_max_body_size\s+6m\s*;", text), f"{name}: общий 6m в http остаётся"


# --- службы -----------------------------------------------------------------------------------------------------

def test_worker_service_runs_only_files_queue_with_two_replicas():
    """NFR-206: служба `worker` слушает только очередь `files` с `--with-scheduler`, две копии (`deploy.replicas: 2`);
    `mail` и `inbox` ушли в другие службы."""
    worker = block("worker")
    assert rq_queues(worker) == ["files"]
    assert re.search(r"^    deploy:\s*\n      replicas:\s*[\"']?2[\"']?\s*$", worker, re.M), "worker: deploy.replicas: 2"
    assert not re.search(r"^\s+replicas:", block("scheduler"), re.M), "scheduler — одна копия"


def test_worker_mail_service_runs_mail_and_maintenance_queues():
    """NFR-206: `worker-mail` — та же команда с очередями `mail maintenance` в таком порядке, том `protected`,
    `DATABASE_MIGRATE_URL` пуст (владельца схемы нет)."""
    service = block("worker-mail")
    assert rq_queues(service) == ["mail", "maintenance"]
    assert "protected:/app/protected" in mounts(service)
    assert re.search(r"DATABASE_MIGRATE_URL:\s*[\"']{2}\s*$", service, re.M)
    assert not re.search(r"^\s+profiles:", service, re.M)


def test_worker_inbox_service_runs_inbox_queue():
    """NFR-206: `worker-inbox` — та же команда с очередью `inbox`, том `protected`, `DATABASE_MIGRATE_URL` пуст."""
    service = block("worker-inbox")
    assert rq_queues(service) == ["inbox"]
    assert "protected:/app/protected" in mounts(service)
    assert re.search(r"DATABASE_MIGRATE_URL:\s*[\"']{2}\s*$", service, re.M)
    assert not re.search(r"^\s+profiles:", service, re.M)


def test_all_workers_have_protected_volume_and_with_scheduler():
    """NFR-206: у всех трёх рабочих служб том `protected` на тот же путь, что у `web` (не только для чтения) и
    `--with-scheduler`; очереди служб не пересекаются и вместе дают files, mail, maintenance, inbox."""
    web_mount = [m for m in mounts(block("web")) if m.startswith("protected:")]
    assert web_mount == ["protected:/app/protected"]
    seen = []
    for name in WORKERS:
        service = block(name)
        assert "protected:/app/protected" in mounts(service), f"{name}: том protected на /app/protected без :ro"
        assert re.search(r"rq worker\b.*--with-scheduler", command_of(service)), f"{name}: --with-scheduler"
        seen += rq_queues(service)
    assert sorted(seen) == ["files", "inbox", "mail", "maintenance"], f"очереди служб: {seen}"


def test_workers_have_no_container_name():
    """NFR-206: ни у одной службы нет `container_name` (иначе две копии `worker` не запустить)."""
    for name, service in compose_services().items():
        assert not re.search(r"^\s+container_name:", service, re.M), f"{name}: container_name не задаётся"
    for name in WORKERS:
        block(name)


def test_dovecot_in_dev_and_test_profiles_pinned_by_digest():
    """NFR-206: служба `dovecot` — образ `dovecot/dovecot:2.4.5` по дайджесту, профили `dev` и `test`, пароль
    `{PLAIN}${IMAP_PASSWORD:-}`; проверки здоровья нет (в образе нет оболочки)."""
    service = block("dovecot")
    assert re.search(r"^    image:\s*dovecot/dovecot:2\.4\.5@sha256:[0-9a-f]{64}\s*$", service, re.M)
    assert re.search(r"^    profiles:\s*\[\s*[\"']dev[\"']\s*,\s*[\"']test[\"']\s*\]\s*$", service, re.M)
    assert env_keys(service).get("USER_PASSWORD", "").strip("\"'") == "{PLAIN}${IMAP_PASSWORD:-}"
    assert not re.search(r"^    healthcheck:", service, re.M)


def test_dovecot_config_mounted_read_only_and_port_set():
    """NFR-206: `99-test.conf` смонтирован `:ro` на `/etc/dovecot/conf.d/99-test.conf`, порт `127.0.0.1:31143:31143`;
    в файле ровно `auth_allow_cleartext = yes` и `ssl = no`."""
    service = block("dovecot")
    assert "./dovecot/99-test.conf:/etc/dovecot/conf.d/99-test.conf:ro" in mounts(service)
    assert "127.0.0.1:31143:31143" in mounts(service)
    lines = [line.strip() for line in uncommented(deploy_text("dovecot", "99-test.conf")).splitlines() if line.strip()]
    assert sorted(lines) == ["auth_allow_cleartext = yes", "ssl = no"]


def test_test_service_depends_on_dovecot_started_and_worker_services_have_no_profile():
    """NFR-206: `depends_on` службы `test` содержит `dovecot` с `service_started` (не `service_healthy`); службы
    worker, worker-mail, worker-inbox, scheduler, backup без ключа `profiles`."""
    dovecot = depends_on(block("test")).get("dovecot")
    assert dovecot is not None, "у test нет зависимости от dovecot"
    assert re.search(r"^\s+condition:\s*service_started\s*$", dovecot, re.M)
    assert "service_healthy" not in dovecot
    for name in ("worker", "worker-mail", "worker-inbox", "scheduler", "backup"):
        assert not re.search(r"^\s+profiles:", block(name), re.M), f"{name}: profiles не задаётся"


def test_backup_service_on_postgres_alpine_with_crond_and_moscow_tz():
    """NFR-210: `backup` на `postgres:17-alpine`, `entrypoint` и `command` запускают `crond -f`, `TZ: Europe/Moscow`;
    `deploy/backup/crontab` — строка `30 1 * * *` с вызовом `/backup/backup.sh`."""
    service = block("backup")
    assert re.search(r"^    image:\s*postgres:17-alpine\s*$", service, re.M)
    assert re.search(r"^    entrypoint:", service, re.M) and re.search(r"^    command:", service, re.M)
    assert re.search(r"\bcrond\b.*-f", command_of(service)), f"command: {command_of(service)!r}"
    entry = re.search(r"^    entrypoint:(.*(?:\n      .*)*)", service, re.M).group(1)
    assert "crond" in entry or "crond" in command_of(service)
    assert env_keys(service).get("TZ", "").strip("\"'") == "Europe/Moscow"
    crontab = [line.split() for line in uncommented(deploy_text("backup", "crontab")).splitlines() if line.strip()]
    assert any(parts[:5] == ["30", "1", "*", "*", "*"] and "/backup/backup.sh" in parts[5:] for parts in crontab), (
        f"в crontab нет строки `30 1 * * *` с /backup/backup.sh: {crontab}")


def test_backup_mounts_protected_and_media_read_only():
    """NFR-210: у `backup` смонтированы `./backup:/backup:ro`, том `backups` на `/backups`, тома `protected` и `media`
    только для чтения; из `.env` — только `DATABASE_MIGRATE_URL` через `environment`, без `env_file`."""
    service = block("backup")
    found = mounts(service)
    assert "./backup:/backup:ro" in found
    assert "backups:/backups" in found
    assert "backups" in top_volume_names(), "том backups не объявлен в volumes"
    for volume in ("protected", "media"):
        assert any(re.fullmatch(rf"{volume}:/\S+:ro", m) for m in found), f"{volume}: только для чтения"
        assert not any(m.startswith(f"{volume}:") and not m.endswith(":ro") for m in found), f"{volume}: без :ro"
    assert not re.search(r"^\s+env_file:", service, re.M), "решение C9: env_file у backup нет"
    keys = env_keys(service)
    assert set(keys) <= {"DATABASE_MIGRATE_URL", "TZ"}, f"лишние переменные: {sorted(set(keys) - {'TZ'})}"
    assert keys.get("DATABASE_MIGRATE_URL") and not re.fullmatch(r"[\"']{2}", keys["DATABASE_MIGRATE_URL"]), (
        "у backup DATABASE_MIGRATE_URL берётся из .env, не пуст")


def test_backup_script_dumps_archives_volumes_and_deletes_older_than_14_days():
    """NFR-210: `backup.sh` снимает `pg_dump -Fc -d "$DATABASE_MIGRATE_URL"` (`crm-ГГГГ-ММ-ДД.dump`), делает две
    упаковки `tar` (`protected-….tgz`, `media-….tgz`), стирает копии старше 14 дней; пароля в тексте нет."""
    text = deploy_text("backup", "backup.sh")
    assert 'pg_dump -Fc -d "$DATABASE_MIGRATE_URL"' in text
    assert "crm-" in text and ".dump" in text and "/backups" in text
    assert re.search(r"\btar\b", uncommented(text)), "тома упаковываются tar (две упаковки — можно и циклом)"
    code = uncommented(text)
    assert "protected-" in code and "media-" in code and ".tgz" in code, "имена двух архивов томов"
    assert "-mtime +14" in text and "-delete" in text
    assert not re.search(r"://[^:@/\s]+:(?!\*\*\*)[^@\s$]+@", code), "пароль в адресе"
    assert not re.search(r"PGPASSWORD\s*=\s*[^\s$\"']", code), "пароль в тексте скрипта"


def test_clamav_service_enables_alert_encrypted_archive():
    """NFR-206: в `environment` службы `clamav` — `CLAMD_CONF_AlertEncryptedArchive: "yes"`; других `CLAMD_CONF_*` и
    `FRESHCLAM_CONF_*` в compose нет."""
    keys = env_keys(block("clamav"))
    assert keys.get("CLAMD_CONF_AlertEncryptedArchive", "").strip("\"'") == "yes"
    everything = uncommented(deploy_text("docker-compose.yml"))
    assert set(re.findall(r"CLAMD_CONF_\w+", everything)) == {"CLAMD_CONF_AlertEncryptedArchive"}
    assert "FRESHCLAM_CONF_" not in everything


def test_clamav_timeout_120_in_all_services_and_settings_default():
    """NFR-206: `CLAMAV_TIMEOUT` по умолчанию 120 в `environment` служб web, worker, worker-mail, worker-inbox, test;
    в `config/settings.py` — `default=120`; в `.env.example` — только строка `# CLAMAV_TIMEOUT=120`."""
    for name in ("web", "worker", "worker-mail", "worker-inbox", "test"):
        value = env_keys(block(name)).get("CLAMAV_TIMEOUT", "").strip("\"'")
        assert value == "${CLAMAV_TIMEOUT:-120}", f"{name}: CLAMAV_TIMEOUT={value!r}"
    settings_text = (BACKEND_DIR / "config" / "settings.py").read_text(encoding="utf-8")
    assert re.search(r"^CLAMAV_TIMEOUT\s*=\s*env\.int\(\s*[\"']CLAMAV_TIMEOUT[\"']\s*,\s*default=120\s*\)", settings_text, re.M)
    example = deploy_text(".env.example").splitlines()
    assert any(re.fullmatch(r"#\s*CLAMAV_TIMEOUT=120", line.strip()) for line in example)
    assert not any(re.match(r"\s*CLAMAV_TIMEOUT\s*=", line) for line in example)


# --- расписание -------------------------------------------------------------------------------------------------

def test_cron_has_eight_new_jobs_with_expected_queues_and_poll_mailbox_every_minute():
    """FR-210, NFR-206: `config/cron.py` регистрирует восемь новых заданий (имя = функция из
    `apps.servicedesk.tasks`) в очередях `inbox` и `maintenance`, не в `mail`; опрос ящика — каждую минуту; два задания
    среза 004 — `notify_tick` (очередь `notify`, `interval=30`, `job_timeout=120`) и `notify_retention` (`maintenance`,
    `40 23 * * *`, 600); задание среза 005 — `purge_trash` (`maintenance`, `45 23 * * *`, 600); задание среза 006 — `lists_reminders` (функция `remind_deadlines`, `maintenance`, `0 5 * * *`, 600); два задания среза 007 — `feed_reminders` (функция `remind_events`, `notify`, `* * * * *`, 120) и `feed_retention` (функция `retention_night`, `maintenance`, `35 23 * * *`, 600); всего двадцать вызовов `register`; `scheduler` — одна копия с `rq cron`."""
    registered = cron_by_name()
    for name, (queue, cron, _timeout) in NEW_JOBS.items():
        assert name in registered, f"в cron.py нет задания {name}"
        assert registered[name]["queue"] == queue, f"{name}: очередь {registered[name]['queue']}"
        assert registered[name]["queue"] != "mail"
        assert registered[name]["function"] == name, f"{name}: функция {registered[name]['function']}"
    assert registered["poll_mailbox"]["cron"] == "* * * * *"
    assert registered["poll_mailbox"]["queue"] == "inbox"
    for name, (queue, interval, cron, timeout) in {**NOTIFY_JOBS, **KNOWLEDGE_JOBS}.items():
        assert name in registered, f"в cron.py нет задания {name}"
        assert registered[name]["function"] == name, f"{name}: функция {registered[name]['function']}"
        assert registered[name]["queue"] == queue, f"{name}: очередь {registered[name]['queue']}"
        assert registered[name]["interval"] == interval, f"{name}: interval={registered[name]['interval']!r}"
        assert registered[name]["cron"] == cron, f"{name}: cron={registered[name]['cron']!r}"
        assert registered[name]["job_timeout"] == timeout, f"{name}: job_timeout={registered[name]['job_timeout']!r}"
    for name, (function, queue, interval, cron, timeout) in LISTS_JOBS.items():
        assert name in registered, f"в cron.py нет задания {name}"
        assert registered[name]["function"] == function, f"{name}: функция {registered[name]['function']}"
        assert registered[name]["queue"] == queue, f"{name}: очередь {registered[name]['queue']}"
        assert registered[name]["interval"] == interval, f"{name}: interval={registered[name]['interval']!r}"
        assert registered[name]["cron"] == cron, f"{name}: cron={registered[name]['cron']!r}"
        assert registered[name]["job_timeout"] == timeout, f"{name}: job_timeout={registered[name]['job_timeout']!r}"
    from tests.support_feed import FEED_JOBS

    for name, (function, queue, interval, cron, timeout) in FEED_JOBS.items():
        assert name in registered, f"в cron.py нет задания {name}"
        assert registered[name]["function"] == function, f"{name}: функция {registered[name]['function']}"
        assert registered[name]["queue"] == queue, f"{name}: очередь {registered[name]['queue']}"
        assert registered[name]["interval"] == interval, f"{name}: interval={registered[name]['interval']!r}"
        assert registered[name]["cron"] == cron, f"{name}: cron={registered[name]['cron']!r}"
        assert registered[name]["job_timeout"] == timeout, f"{name}: job_timeout={registered[name]['job_timeout']!r}"
    assert len(cron_registrations()) == 20, (
        "шесть прежних, восемь среза 003, два среза 004, один среза 005, один среза 006 и два среза 007")
    source = (BACKEND_DIR / "config" / "cron.py").read_text(encoding="utf-8")
    assert re.search(r"from apps\.servicedesk\.tasks import", source)
    scheduler = block("scheduler")
    assert re.search(r"rq cron config\.cron", command_of(scheduler))
    assert not re.search(r"^\s+replicas:", scheduler, re.M)


def test_cron_times_are_utc_for_moscow_schedule():
    """NFR-206: строки cron — по UTC (Москва минус три часа): ночные задания в 02:10, 02:20, 02:30, 02:50 по Москве —
    `10/20/30/50 23 * * *`; часовые — `5 * * * *` и `25 * * * *`; пятиминутные — `*/5 * * * *`."""
    registered = cron_by_name()
    for name, (hour, minute) in MOSCOW_NIGHT.items():
        utc_hour = (hour - 3) % 24
        assert utc_hour == 23
        assert registered[name]["cron"] == f"{minute} {utc_hour} * * *", f"{name}: {registered[name]['cron']}"
    assert registered["autoclose"]["cron"] == "5 * * * *"
    assert registered["reconcile_assignees"]["cron"] == "25 * * * *"
    assert registered["requeue_inbound"]["cron"] == "*/5 * * * *"
    for name, (_queue, cron, _timeout) in NEW_JOBS.items():
        assert registered[name]["cron"] == cron, name


def test_cron_every_new_job_has_explicit_job_timeout_from_plan_table_old_six_unchanged():
    """NFR-206: у каждого из восьми новых заданий явный целый `job_timeout` по таблице плана (600, 300, 600, 600, 600,
    600, 300, 600); прежние шесть строк срезов 001 и 002 (очередь, расписание) не изменились (`job_timeout` у них не проверяется, дополнение 39 (в))."""
    registered = cron_by_name()
    for name, (_queue, _cron, timeout) in NEW_JOBS.items():
        assert registered[name]["has_job_timeout"], f"{name}: нет job_timeout"
        assert isinstance(registered[name]["job_timeout"], int) and registered[name]["job_timeout"] == timeout, (
            f"{name}: job_timeout={registered[name]['job_timeout']!r}, нужно {timeout}")
    for name, cron in OLD_JOBS.items():
        assert name in registered, f"пропало прежнее задание {name}"
        assert registered[name]["cron"] == cron, f"{name}: расписание изменено"
        assert registered[name]["queue"] == "mail", f"{name}: очередь изменена"


def test_rq_queues_include_inbox_and_maintenance():
    """NFR-206: `RQ_QUEUES` содержит `inbox` и `maintenance` (адрес Valkey, `DEFAULT_TIMEOUT` 120) рядом с `mail` и
    `files`; очереди открываются через django_rq."""
    import django_rq
    from django.conf import settings

    for name in ("inbox", "maintenance", "mail", "files"):
        assert name in settings.RQ_QUEUES, name
        assert settings.RQ_QUEUES[name]["DEFAULT_TIMEOUT"] == 120, name
        assert settings.RQ_QUEUES[name]["URL"] == settings.VALKEY_URL, name
        assert django_rq.get_queue(name).name == name


# --- nginx ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["nginx.conf", "nginx.prod.conf"])
def test_nginx_request_form_location_has_55m_and_repeats_proxy_directives(name):
    """NFR-206: `location = /request/` — `client_max_body_size 55m;` и повторённые `proxy_pass`, `proxy_set_header`,
    `proxy_read_timeout` из `location /` (они не наследуются); общий `6m` остаётся."""
    _check_form_location(name, REQUEST_LOCATION)


@pytest.mark.parametrize("name", ["nginx.conf", "nginx.prod.conf"])
def test_nginx_executor_forms_regex_location_has_55m_and_repeats_proxy_directives(name):
    """NFR-206: `location ~ ^/tickets/(new/|[0-9]+/reply/)$` — `55m` и повторённые proxy-директивы из `location /`."""
    _check_form_location(name, TICKETS_LOCATION)


@pytest.mark.parametrize("name", ["nginx.conf", "nginx.prod.conf"])
def test_nginx_knowledge_files_regex_location_has_55m_and_repeats_proxy_directives(name):
    """NFR-206, CONTRACT-005: `location ~ ^/kb/[0-9]+/files/$` — `55m` и повторённые proxy-директивы из `location /`
    (загрузка файлов статьи базы знаний)."""
    _check_form_location(name, KB_FILES_LOCATION)


@pytest.mark.parametrize("name", ["nginx.conf", "nginx.prod.conf"])
def test_nginx_protected_attachments_and_inbound_internal_with_octet_stream_and_nosniff(name):
    """NFR-206: перед `location /protected/` — `/protected/attachments/` и `/protected/inbound/` с `internal;`,
    своим `alias`, `default_type application/octet-stream;` и `nosniff`; общий `/protected/` для фото не изменён."""
    text = nginx_text(name)
    general = re.search(r"location\s+/protected/\s*\{", text)
    assert general, f"{name}: нет общего location /protected/"
    for header, alias in ((ATTACHMENTS_LOCATION, "/srv/protected/attachments/"), (INBOUND_LOCATION, "/srv/protected/inbound/")):
        m = re.search(r"location\s+" + header + r"\s*\{", text)
        assert m and m.start() < general.start(), f"{name}: {header} должен стоять перед /protected/"
        own = directives(location_body(text, header))
        assert "internal" in own
        assert f"alias {alias}" in own
        assert "default_type application/octet-stream" in own
        assert 'add_header X-Content-Type-Options "nosniff" always' in own
    photo = directives(location_body(text, r"/protected/"))
    assert "default_type image/jpeg" in photo and "alias /srv/protected/" in photo


@pytest.mark.parametrize("name", ["nginx.conf", "nginx.prod.conf"])
def test_nginx_protected_attachment_locations_have_no_cache_control(name):
    """NFR-206: в `/protected/attachments/` и `/protected/inbound/` нет `add_header Cache-Control` (его ставит Django:
    `no-store`); у общего `/protected/` для фото он остаётся."""
    text = nginx_text(name)
    for header in (ATTACHMENTS_LOCATION, INBOUND_LOCATION):
        body = location_body(text, header)
        assert not re.search(r"Cache-Control", body, re.I), f"{name}: {header} без Cache-Control"
        assert not re.search(r"\bexpires\b", body), f"{name}: {header} без expires"
    assert re.search(r"add_header\s+Cache-Control", location_body(text, r"/protected/"))


def test_nginx_prod_config_matches_dev_for_new_locations():
    """NFR-206: в `nginx.prod.conf` те же пять новых `location` (четыре среза 003 и `/kb/<N>/files/` среза 005) и те же директивы, что в `nginx.conf`, кроме значения
    `X-Forwarded-Proto` (`$scheme` в dev, `$portal_proto` в prod); `location /` — образец."""
    dev, prod = nginx_text("nginx.conf"), nginx_text("nginx.prod.conf")

    def normal(items):
        return sorted(d for d in items if not d.startswith("proxy_set_header X-Forwarded-Proto"))

    for header in (REQUEST_LOCATION, TICKETS_LOCATION, KB_FILES_LOCATION, ATTACHMENTS_LOCATION, INBOUND_LOCATION, r"/"):
        assert normal(directives(location_body(dev, header))) == normal(directives(location_body(prod, header))), header
    for text, value in ((dev, "$scheme"), (prod, "$portal_proto")):
        for header in (REQUEST_LOCATION, TICKETS_LOCATION, KB_FILES_LOCATION):
            assert f"proxy_set_header X-Forwarded-Proto {value}" in directives(location_body(text, header))


# --- восстановление и переменные --------------------------------------------------------------------------------

def test_restore_md_describes_plan_steps_in_order():
    """NFR-210: `deploy/RESTORE.md` по порядку — остановить web, worker, worker-mail, worker-inbox, scheduler;
    `pg_restore --clean --if-exists` от `crm_owner`; тома protected и media из копий одной ночи;
    `servicedesk_after_restore` через службу `migrate`; запустить службы."""
    text = deploy_text("RESTORE.md")
    stop = re.search(r"(?<!\w)[Оо]станов", text)
    assert stop, "нет шага остановки служб"
    after_stop = text[stop.start():]
    restore = after_stop.find("pg_restore --clean --if-exists")
    assert restore > 0, "нет `pg_restore --clean --if-exists` после остановки"
    stopped = after_stop[:restore]
    for service in ("web", "worker", "worker-mail", "worker-inbox", "scheduler"):
        assert re.search(rf"(?<![\w-]){re.escape(service)}(?![\w-])", stopped), f"остановка: нет службы {service}"
    after_restore = after_stop[restore:]
    assert "crm_owner" in text
    assert re.search(r"protected-[^\s]*\.tgz", text) and re.search(r"media-[^\s]*\.tgz", text), (
        "копии томов одной ночи: имена protected-….tgz и media-….tgz")
    volumes_at = [after_restore.find(word, len("pg_restore")) for word in ("protected", "media")]
    after_script = after_restore.find("servicedesk_after_restore")
    assert after_script > 0, "нет `servicedesk_after_restore`"
    assert all(0 < pos < after_script for pos in volumes_at), "тома protected и media — после базы и до servicedesk_after_restore"
    around = after_restore[max(0, after_script - 200):after_script + 200]
    assert re.search(r"(?<![\w-])migrate(?![\w-])", around), "команда идёт через службу migrate"
    assert re.search(r"[Зз]апуст", after_restore[after_script:]), "последний шаг — запустить службы"


def test_env_example_has_new_variables_with_placeholders_only():
    """NFR-206: в `deploy/.env.example` — `IMAP_PASSWORD=***` (не закомментирована), `IMAP_HOST`, `IMAP_PORT`,
    `IMAP_SECURITY`, `IMAP_USER`, `IMAP_FOLDER`, `IMAP_TIMEOUT`, `SERVICEDESK_MAILBOX` — закомментированными строками
    `# ИМЯ=значение` с безопасными значениями; других действующих строк с ними нет."""
    lines = [line.strip() for line in deploy_text(".env.example").splitlines()]
    active = {m.group(1): m.group(2) for line in lines if (m := re.match(r"^([A-Z_]+)=(.*)$", line))}
    assert active.get("IMAP_PASSWORD") == "***"
    commented = {m.group(1): m.group(2) for line in lines if (m := re.match(r"^#\s*([A-Z_]+)=(.*)$", line))}
    for name in ("IMAP_HOST", "IMAP_PORT", "IMAP_SECURITY", "IMAP_USER", "IMAP_FOLDER", "IMAP_TIMEOUT", "SERVICEDESK_MAILBOX"):
        assert name in commented, f"нет строки `# {name}=…`"
        assert name not in active, f"{name} не должна быть действующей"
    assert commented["SERVICEDESK_MAILBOX"] == "tickets@example.com"
    assert commented["IMAP_SECURITY"] == "ssl"
    assert commented["IMAP_FOLDER"] == "INBOX"
    assert re.fullmatch(r"\d+", commented["IMAP_PORT"]) and re.fullmatch(r"\d+", commented["IMAP_TIMEOUT"])
