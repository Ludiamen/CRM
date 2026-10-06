"""T-118: конфигурация развёртывания (FR-011, FR-039, FR-053, NFR-001, NFR-003, NFR-006, NFR-007, NFR-011).

Читает файлы `deploy/` (сервис `test` монтирует их в /app/deploy только для чтения) и `backend/config/cron.py`.
Договорённости (tests/CONTRACT.md): сертификат стенда лежит в `deploy/certs/` (выпускает `deploy/dev-cert.sh`, в git
не попадает — `deploy/.gitignore`), nginx читает его из `/etc/nginx/certs/`.
"""
import os
import re
import stat

from tests.support import BACKEND_DIR, REPO_ROOT, repo_file


def deploy_text(name: str) -> str:
    return repo_file("deploy", name).read_text(encoding="utf-8")


def uncommented(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def nginx() -> str:
    return uncommented(deploy_text("nginx.conf"))


def compose_services() -> dict[str, str]:
    """Блоки сервисов docker-compose.yml: имя → текст (без комментариев)."""
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


def test_nginx_real_ip_only_from_trusted_proxies():
    """NFR-006, NFR-007: адрес клиента берётся из X-Forwarded-For только от доверенных прокси (TRUSTED_PROXIES), а не от кого угодно."""
    conf = nginx()
    sources = re.findall(r"set_real_ip_from\s+([^;]+);", conf)
    includes = re.findall(r"include\s+([^;]*(?:proxies|real_ip)[^;]*);", conf)
    assert sources or includes, "нет set_real_ip_from (прямо или через include)"
    for source in sources:
        assert source.strip() not in ("0.0.0.0/0", "::/0", "all", "*"), f"доверие всем адресам: {source}"
        assert "TRUSTED_PROXIES" in source or re.match(r"^[0-9a-fA-F:.]+(/\d+)?$", source.strip()), source
    assert re.search(r"real_ip_header\s+X-Forwarded-For\s*;", conf, re.I)
    assert re.search(r"real_ip_recursive\s+on\s*;", conf)
    forwarded = re.findall(r"proxy_set_header\s+X-Forwarded-For\s+([^;]+);", conf)
    assert forwarded and all(v.strip() == "$remote_addr" for v in forwarded), (
        "в Django заголовок уходит со значением $remote_addr: чужой X-Forwarded-For от недоверенного не передаётся")
    assert "TRUSTED_PROXIES" in deploy_text("docker-compose.yml") + deploy_text("nginx.conf") + deploy_text("Dockerfile")


def test_nginx_media_nosniff_and_access_log_format():
    """NFR-007: /media/ с nosniff; журнал доступа не пишет строку запроса и куки, адрес — без параметров (путь $uri)."""
    conf = nginx()
    media = re.search(r"location\s+(?:\^~\s+)?/media/\s*\{(.*?)\n\s*\}", conf, re.S)
    assert media, "нет location /media/"
    assert re.search(r"add_header\s+X-Content-Type-Options\s+[\"']?nosniff[\"']?\s+always\s*;", media.group(1))
    for name in ("nginx.conf", "nginx.prod.conf"):
        text = uncommented(deploy_text(name))
        # отдаются только PNG и JPEG с типом по расширению, прочее под /media/ — 404 (PLAN-001 версии 3)
        image = re.search(r"location\s+~\*?\s+\^/media/\(\.\+\\\.\(\?:png\|jpe\?g\)\)\$\s*\{(.*?)\n\s*\}", text, re.S)
        assert image, f"{name}: нет location /media/ только для png, jpg, jpeg"
        assert re.search(r"types\s*\{\s*image/png\s+png;\s*image/jpeg\s+jpg\s+jpeg;\s*\}", image.group(1))
        assert re.search(r"add_header\s+X-Content-Type-Options\s+[\"']?nosniff[\"']?\s+always\s*;", image.group(1))
        rest = re.search(r"location\s+/media/\s*\{(.*?)\n\s*\}", text, re.S)
        assert rest and re.search(r"return\s+404\s*;", rest.group(1)), f"{name}: прочее под /media/ должно давать 404"
        assert "alias /srv/media/;" not in text, f"{name}: каталог /media/ не отдаётся целиком"
    formats = dict(re.findall(r"log_format\s+(\w+)\s+([^;]+);", conf))
    used = re.findall(r"access_log\s+\S+\s+(\w+)", conf)
    assert used and all(name in formats for name in used), "access_log должен использовать свой log_format"
    for name in used:
        fmt = formats[name]
        for banned in ("$request ", "$request\"", "$request'", "$request_uri", "$args", "$query_string", "$is_args",
                       "$http_cookie", "$http_authorization", "$request_body", "$http_referer"):
            assert banned not in fmt + " ", f"в формате журнала {name} есть {banned}"
        assert "$uri" in fmt or "$request_method" in fmt, "в журнале должен быть путь без параметров"


def test_dev_cert_script_and_nginx_dev_tls_config():
    """NFR-007: TLS стенда — свой самоподписанный сертификат (dev-cert.sh) в nginx, перенаправление HTTP → HTTPS, современные протоколы."""
    script_path = repo_file("deploy", "dev-cert.sh")
    assert os.stat(script_path).st_mode & stat.S_IXUSR, "dev-cert.sh должен быть исполняемым"
    script = script_path.read_text(encoding="utf-8")
    assert re.search(r"set -[a-z]*e", script) and "openssl req" in script and "-x509" in script
    assert "127.0.0.1" in script and "subjectAltName" in script and "certs" in script
    conf = nginx()
    assert re.search(r"listen\s+[^;]*\bssl\b", conf)
    assert re.search(r"ssl_certificate\s+/etc/nginx/certs/[^;]+;", conf) and re.search(r"ssl_certificate_key\s+/etc/nginx/certs/[^;]+;", conf)
    protocols = re.search(r"ssl_protocols\s+([^;]+);", conf)
    assert protocols and not {"SSLv3", "TLSv1", "TLSv1.1"} & set(protocols.group(1).split())
    assert re.search(r"return\s+30[18]\s+https://", conf), "нет перенаправления на HTTPS"
    nginx_block = compose_services()["nginx"]
    assert "./certs:/etc/nginx/certs" in nginx_block and re.search(r"127\.0\.0\.1:8031:", nginx_block)
    assert "certs/" in deploy_text(".gitignore").splitlines() or "/certs/" in deploy_text(".gitignore").splitlines()


def test_no_forwarded_proto_spoofing_and_no_private_key_in_repo():
    """NFR-007, NFR-011: X-Forwarded-Proto не подделывается константой (стенд держит настоящий TLS); закрытых ключей в репозитории нет."""
    conf = nginx()
    for value in re.findall(r"proxy_set_header\s+X-Forwarded-Proto\s+([^;]+);", conf):
        assert value.strip().startswith("$"), f"X-Forwarded-Proto задан константой: {value}"
    everything = conf + deploy_text("docker-compose.yml") + (BACKEND_DIR / "config" / "settings.py").read_text(encoding="utf-8")
    assert not re.search(r"X-Forwarded-Proto[\"']?\s*[:=,]\s*[\"']?https", everything, re.I), "подмена схемы константой"
    assert not re.search(r"HTTP_X_FORWARDED_PROTO[\"']?\s*[:=]\s*[\"']https", everything)
    found = []
    for root in (REPO_ROOT / "deploy", BACKEND_DIR):
        for path in root.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts or path.stat().st_size > 2_000_000:
                continue
            if path.suffix in (".key", ".pem", ".p12", ".pfx") or path.name in ("id_rsa", "id_ed25519"):
                found.append(str(path.relative_to(REPO_ROOT)))
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", text) and path.name != "test_deploy_files.py":
                found.append(str(path.relative_to(REPO_ROOT)))
    assert not found or all("deploy/certs/" in f.replace(os.sep, "/") for f in found), f"закрытый ключ в репозитории: {found}"
    assert "certs/" in deploy_text(".gitignore"), "каталог сертификатов стенда должен быть в .gitignore"


def test_compose_services_and_dev_profile_mailpit():
    """FR-053, NFR-003: в compose — web, worker, scheduler, nginx, postgres, valkey; mailpit — только в профиле dev."""
    services = compose_services()
    assert {"web", "worker", "scheduler", "nginx", "postgres", "valkey", "mailpit"} <= set(services)
    assert re.search(r"profiles:\s*\[?\s*[\"']?dev[\"']?\s*\]?", services["mailpit"])
    for name in ("web", "worker", "scheduler", "nginx", "postgres", "valkey"):
        assert "profiles:" not in services[name], f"{name} не должен зависеть от профиля"
    assert "valkey-server" in services["valkey"] and "postgres:17" in services["postgres"]
    assert not re.search(r"ports:\s*\n\s*-\s*[\"']?(?:5432|6379)", services["postgres"] + services["valkey"]), "базы наружу не публикуются"


def test_owner_credentials_only_in_one_shot_migrate_service():
    """Инвариант «аудит-изменений» (PLAN-001 версии 3): учётные данные владельца схемы получают только разовая
    служба migrate и standtools профиля dev; у web, worker и scheduler DATABASE_MIGRATE_URL пуст, web ждёт миграций."""
    services = compose_services()
    migrate = services["migrate"]
    assert re.search(r"RUN_MIGRATIONS:\s*[\"']?1", migrate)
    assert re.search(r"restart:\s*[\"']?no", migrate), "migrate — разовая служба"
    for name in ("web", "worker", "scheduler"):
        assert re.search(r"DATABASE_MIGRATE_URL:\s*[\"']{2}", services[name]), f"{name}: DATABASE_MIGRATE_URL должен быть пуст"
        assert "RUN_MIGRATIONS" not in services[name]
    assert re.search(r"migrate:\s*\n\s*condition:\s*service_completed_successfully", services["web"])


def test_worker_runs_with_scheduler_and_cron_service_present():
    """FR-053: рабочие процессы — `rq worker --with-scheduler` (паузы повторов): `worker` — очередь files, `worker-mail` —
    mail и maintenance, `worker-inbox` — inbox; отдельный сервис — `rq cron` для ночных заданий."""
    services = compose_services()
    for name, queues in (("worker", "files"), ("worker-mail", "mail maintenance"), ("worker-inbox", "inbox")):
        assert name in services, f"в docker-compose.yml нет службы {name}"
        one_line = services[name].replace("\n", " ")
        assert re.search(r"rq\s+worker\b[^\n]*--with-scheduler|--with-scheduler[^\n]*rq\s+worker", one_line), name
        assert re.search(rf"--with-scheduler {queues}(?: |$)", _compose_one_line(services[name])), (
            f"{name} слушает очереди {queues}")
    assert re.search(r"rq\s+cron\s+config\.cron", services["scheduler"].replace("\n", " "))
    assert "--with-scheduler" not in services["scheduler"]


def test_web_runs_uvicorn_worker_class_from_uvicorn_worker_package():
    """NFR-001: web — gunicorn с классом uvicorn_worker.UvicornWorker (отдельный пакет), а не устаревший uvicorn.workers."""
    text = compose_services()["web"] + deploy_text("Dockerfile")
    assert re.search(r"gunicorn", text) and "uvicorn_worker.UvicornWorker" in text
    assert "uvicorn.workers" not in text
    assert re.search(r"config\.asgi(:application)?", text)



def test_web_gunicorn_control_socket_disabled():
    """Этап 4: управляющий сокет gunicorn 25.1+ (gunicornc) не нужен и не должен создаваться — флаг в обоих местах запуска."""
    for text in (compose_services()["web"], deploy_text("Dockerfile")):
        assert "--no-control-socket" in text


def test_database_pool_only_for_web():
    """NFR-002 (PLAN-001 версия 4): пул соединений psycopg включён у web (ASGI); у worker и scheduler его нет."""
    services = compose_services()
    assert re.search(r'DATABASE_POOL:\s*"?1"?', services["web"])
    for name in ("worker", "scheduler", "migrate"):
        assert "DATABASE_POOL" not in services[name], name
    settings_text = (BACKEND_DIR / "config" / "settings.py").read_text(encoding="utf-8")
    assert re.search(r'env\.bool\("DATABASE_POOL"', settings_text) and '["pool"] = True' in settings_text

def test_cron_registers_history_and_expired_links_and_sessions_cleanup():
    """FR-039, FR-011: config/cron.py регистрирует ночные задания: история входов, просроченные ссылки, просроченные сессии."""
    source = uncommented((BACKEND_DIR / "config" / "cron.py").read_text(encoding="utf-8"))
    assert len(re.findall(r"\bregister\(", source)) >= 3
    for function in ("purge_login_history", "purge_expired_links", "purge_expired_sessions"):
        assert re.search(rf"register\(\s*{function}\b", source), f"{function} не зарегистрирована"
    assert "apps.core.services.retention" in source
    assert re.search(r"cron\s*=|interval\s*=", source)


# ---------------------------------------------------------------------------------------------------------------------
# Срез 002 (T-2117): служба ClamAV, worker с очередью files, nginx для фото, новые ночные задания.
# Сценарии — NFR-105 (антивирус в основном наборе), FR-132 (фото сотрудников), FR-141, NFR-108 (границы входа).
# Источник решений по образу — docs/reviews/TASKS-002.md, «Решения Opus по итогам T-2001» (п. 1–5);
# контракт — tests/CONTRACT-002.md, § 1 и § 3.
# ---------------------------------------------------------------------------------------------------------------------

def _compose_block(name: str) -> str:
    services = compose_services()
    assert name in services, f"в docker-compose.yml нет службы {name}"
    return services[name]


def _compose_depends_on(block: str) -> dict[str, str]:
    """Раздел depends_on блока службы: имя зависимости → её строки (без комментариев)."""
    result, in_section, current = {}, False, None
    for line in block.splitlines():
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


def _compose_one_line(block: str) -> str:
    return re.sub(r"\s+", " ", block)


def _cron_registrations() -> list[dict]:
    """Вызовы `register(...)` в config/cron.py: функция, очередь, расписание, имя (разбор дерева, без запуска модуля)."""
    import ast

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
                          "name": keys.get("name")})
    return found


def test_clamav_service_pinned_internal_port_healthcheck_and_volume():
    """NFR-105: служба clamav — в основном наборе, образ закреплён тегом 1.4.6, порт 3310 не публикуется наружу, том
    clamav-db, проверка здоровья `clamdcheck.sh` с заданными сроками; ни web, ни worker не ждут её здоровья."""
    block = _compose_block("clamav")
    assert "profiles:" not in block, "clamav входит в основной набор, а не в профиль"
    assert re.search(r"^    image:\s*[\"']?clamav/clamav:1\.4\.6[\"']?\s*$", block, re.M), "образ clamav/clamav:1.4.6 (тегом выпуска)"
    assert not re.search(r"^    ports:", block, re.M), "порт 3310 доступен только внутри сети compose"
    assert not re.search(r"\b3310:", block), "порт 3310 не публикуется на хост"
    assert re.search(r"^    volumes:\s*\n(?:\s+-.*\n)*?\s+-\s*[\"']?clamav-db:/var/lib/clamav[\"']?\s*$", block, re.M), (
        "том clamav-db — ровно на /var/lib/clamav, без :ro и подкаталога (дополнение 40)")
    top = re.search(r"^volumes:\s*\n((?:[ ]+.*\n|\n)*)", uncommented(deploy_text("docker-compose.yml")) + "\n", re.M)
    assert top and re.search(r"^  clamav-db:", top.group(1), re.M), "том clamav-db не объявлен в разделе volumes"
    health = re.search(r"^    healthcheck:\s*\n((?:      .*\n)+)", block, re.M)
    assert health, "проверка здоровья должна быть задана в compose явно"
    text = health.group(1)
    assert re.search(r"test:\s*\[\s*[\"']CMD[\"']\s*,\s*[\"']clamdcheck\.sh[\"']\s*\]", text)
    for key, value in (("interval", "10s"), ("timeout", "5s"), ("retries", "6"), ("start_period", "120s")):
        assert re.search(rf"^\s+{key}:\s*[\"']?{value}[\"']?\s*$", text, re.M), f"healthcheck.{key} должен быть {value}"
    for name in ("web", "worker"):
        assert "clamav" not in _compose_depends_on(_compose_block(name)), f"{name} не зависит от здоровья clamav"


def test_freshclam_conf_mounted_with_default_mirror():
    """NFR-105: deploy/clamav/freshclam.conf смонтирован в clamav только для чтения; в нём ровно пять действующих
    строк файла образа 1.4.6 (зеркало database.clamav.net) и закомментированный пример PrivateMirror; переменных
    FRESHCLAM_CONF_* и FRESHCLAM_CHECKS в compose нет (/init правит по ним файл командой sed -i); из CLAMD_CONF_* есть
    только `CLAMD_CONF_AlertEncryptedArchive: "yes"` (срез 003; clamd.conf не смонтирован, правка идёт через окружение)."""
    block = _compose_block("clamav")
    assert re.search(r"-\s*[\"']?\./clamav/freshclam\.conf:/etc/clamav/freshclam\.conf:ro[\"']?\s*$", block, re.M), (
        "bind ./clamav/freshclam.conf → /etc/clamav/freshclam.conf с :ro")
    lines = deploy_text("clamav/freshclam.conf").splitlines()
    active = [re.sub(r"\s+", " ", line.strip()) for line in lines if line.strip() and not line.strip().startswith("#")]
    assert active == [
        "UpdateLogFile /var/log/clamav/freshclam.log",
        "DatabaseOwner clamav",
        "DatabaseMirror database.clamav.net",
        "ScriptedUpdates yes",
        "NotifyClamd /etc/clamav/clamd.conf",
    ], f"действующие строки freshclam.conf: {active}"
    assert any(re.match(r"^\s*#\s*PrivateMirror\s+\S+", line) for line in lines), "нет закомментированного примера PrivateMirror"
    everything = uncommented(deploy_text("docker-compose.yml"))
    assert not re.search(r"FRESHCLAM_CONF_", everything)
    clamd_conf = re.findall(r"^\s*(CLAMD_CONF_\w+):\s*[\"']?([^\s\"']*)[\"']?\s*$", everything, re.M)
    assert clamd_conf == [("CLAMD_CONF_AlertEncryptedArchive", "yes")], f"из CLAMD_CONF_* разрешена одна: {clamd_conf}"
    assert len(re.findall(r"CLAMD_CONF_", everything)) == 1, "CLAMD_CONF_* упомянута вне этой строки"
    assert re.search(r"CLAMD_CONF_AlertEncryptedArchive:", block), "CLAMD_CONF_AlertEncryptedArchive — в службе clamav"
    assert "FRESHCLAM_CHECKS" not in everything, "частота обновления баз — как в образе"


def test_worker_listens_files_before_mail_and_mounts_protected():
    """FR-132, NFR-105: worker слушает только очередь files (проверка фото не ждёт писем: очереди mail, maintenance и inbox —
    службы worker-mail и worker-inbox), планировщик повторов включён, том protected у всех трёх служб смонтирован на тот
    же путь, что у web."""
    worker = _compose_block("worker")
    command = _compose_one_line(worker)
    assert re.search(r"command:\s*rq worker -c config\.rq_settings --with-scheduler files(?: |$)", command), (
        "ожидается `rq worker -c config.rq_settings --with-scheduler files`")
    assert not re.search(r"--with-scheduler files \S", re.search(r"command:[^\n]*", worker).group(0)), (
        "worker слушает только очередь files")
    web_mount = re.search(r"-\s*[\"']?(protected:\S+?)[\"']?\s*$", _compose_block("web"), re.M)
    for name in ("worker", "worker-mail", "worker-inbox"):
        mount = re.search(r"-\s*[\"']?(protected:\S+?)[\"']?\s*$", _compose_block(name), re.M)
        assert mount, f"у {name} не смонтирован том protected"
        assert web_mount and mount.group(1) == web_mount.group(1) == "protected:/app/protected", name
        assert not mount.group(1).endswith(":ro"), f"{name} пишет файлы (перекодированные фото, вложения)"


def test_clamav_env_defaults_in_compose_commented_in_env_example():
    """NFR-105: CLAMAV_HOST, CLAMAV_PORT, CLAMAV_TIMEOUT имеют в compose значения по умолчанию (clamav, 3310, 120) у web,
    worker, worker-mail, worker-inbox и test, а в deploy/.env.example перечислены только закомментированными строками."""
    defaults = {"CLAMAV_HOST": "clamav", "CLAMAV_PORT": "3310", "CLAMAV_TIMEOUT": "120"}
    for service in ("web", "worker", "worker-mail", "worker-inbox", "test"):
        block = _compose_block(service)
        for name, default in defaults.items():
            pattern = rf"^\s+{name}:\s*[\"']?(?:\$\{{{name}:-{default}\}}|{default})[\"']?\s*$"
            assert re.search(pattern, block, re.M), f"{service}: {name} со значением по умолчанию {default}"
    example = deploy_text(".env.example").splitlines()
    for name, default in defaults.items():
        assert any(re.fullmatch(rf"#\s*{name}={default}", line.strip()) for line in example), f"нет строки `# {name}={default}`"
        assert not any(re.match(rf"\s*{name}\s*=", line) for line in example), f"{name} в .env.example не должна быть действующей"


def test_test_service_waits_for_healthy_clamav():
    """NFR-105: служба test зависит от clamav с условием service_healthy, без `required: false` (clamav входит в
    основной набор, compose запускает её сам); зависимости среза 001 сохранены."""
    depends = _compose_depends_on(_compose_block("test"))
    assert "clamav" in depends, "у test нет зависимости от clamav"
    assert re.search(r"^\s+condition:\s*service_healthy\s*$", depends["clamav"], re.M)
    assert "required" not in depends["clamav"], "required: false у clamav не нужен"
    for name in ("postgres", "valkey"):
        assert re.search(r"condition:\s*service_healthy", depends.get(name, "")), name


def test_nginx_body_size_6m_and_protected_location_internal_with_headers():
    """FR-132, NFR-108: в nginx.conf и nginx.prod.conf лимит тела запроса 6m в `http` (фото до 5 МБ в форме), 55m — только
    в двух `location` формы и ответа (срез 003), а /protected/ — внутреннее расположение с alias на том, nosniff, типом
    image/jpeg и Cache-Control private, max-age=86400 (общий /protected/ для фото срезом 003 не меняется)."""
    form_locations = (r"location\s*=\s*/request/\s*\{([^{}]*)\}",
                      r"location\s*~\s*\^/tickets/\(new/\|\[0-9\]\+/reply/\)\$\s*\{([^{}]*)\}")
    for name in ("nginx.conf", "nginx.prod.conf"):
        text = uncommented(deploy_text(name))
        for pattern in form_locations:
            found = re.findall(pattern, text)
            assert len(found) == 1, f"{name}: нет ровно одного location {pattern}"
            assert re.findall(r"client_max_body_size\s+([^;]+);", found[0]) == ["55m"], f"{name}: в location формы нужен 55m"
            text = re.sub(pattern, "", text, count=1)
        sizes = re.findall(r"client_max_body_size\s+([^;]+);", text)
        assert sizes == ["6m"], f"{name}: вне location формы и ответа client_max_body_size один и равен 6m, найдено {sizes}"
        location = re.search(r"location\s+/protected/\s*\{(.*?)\n\s*\}", text, re.S)
        assert location, f"{name}: нет location /protected/"
        body = location.group(1)
        assert re.search(r"^\s*internal\s*;", body, re.M), f"{name}: /protected/ должен быть internal"
        assert re.search(r"alias\s+/srv/protected/\s*;", body)
        assert re.search(r"add_header\s+X-Content-Type-Options\s+[\"']?nosniff[\"']?\s*(?:always\s*)?;", body)
        assert re.search(r"add_header\s+Cache-Control\s+[\"']private,\s*max-age=86400[\"']\s*(?:always\s*)?;", body), (
            f"{name}: Cache-Control private, max-age=86400")
        assert re.search(
            r"default_type\s+image/jpeg\s*;|types\s*\{[^}]*image/jpeg|add_header\s+Content-Type\s+[\"']?image/jpeg", body
        ), f"{name}: тип image/jpeg (default_type, types или add_header Content-Type)"


def test_cron_registers_preview_purge_quarantine_cleanup_and_scan_requeue():
    """FR-132, FR-141, NFR-105: config/cron.py регистрирует purge_import_previews (03:40), purge_quarantine (03:50),
    requeue_pending_scans (каждый час) в очереди mail, ничего не дублируя; три задания среза 001 остались. Шесть прежних
    заданий проверяются по именам, общее число вызовов `register` — нет: задания среза 003 проверяет test_sd_deploy."""
    registrations = _cron_registrations()
    by_name = {}
    for item in registrations:
        assert item["name"] not in by_name, f"задание {item['name']} зарегистрировано дважды"
        by_name[item["name"]] = item
    assert {k: (v["function"], v["cron"]) for k, v in by_name.items() if k in (
        "purge_login_history", "purge_expired_links", "purge_expired_sessions")} == {
        "purge_login_history": ("purge_login_history", "10 3 * * *"),
        "purge_expired_links": ("purge_expired_links", "20 3 * * *"),
        "purge_expired_sessions": ("purge_expired_sessions", "30 3 * * *"),
    }, "задания среза 001 изменены"
    expected = {
        "purge_import_previews": ("purge_previews", "40 3 * * *"),
        "purge_quarantine": ("purge_quarantine", "50 3 * * *"),
        "requeue_pending_scans": ("requeue_pending_scans", "0 * * * *"),
    }
    for name, (function, cron) in expected.items():
        assert name in by_name, f"{name} не зарегистрировано"
        assert (by_name[name]["function"], by_name[name]["cron"], by_name[name]["queue"]) == (function, cron, "mail"), by_name[name]
    source = uncommented((BACKEND_DIR / "config" / "cron.py").read_text(encoding="utf-8"))
    assert "apps.org.tasks" in source and "apps.core.tasks" in source
