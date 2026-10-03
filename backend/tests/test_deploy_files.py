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
    """FR-053: рабочий процесс — `rq worker --with-scheduler` (паузы повторов), отдельный сервис — `rq cron` для ночных заданий."""
    services = compose_services()
    assert re.search(r"rq\s+worker\b[^\n]*--with-scheduler|--with-scheduler[^\n]*rq\s+worker", services["worker"].replace("\n", " "))
    assert re.search(r"\bmail\b", services["worker"]), "рабочий слушает очередь mail"
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
