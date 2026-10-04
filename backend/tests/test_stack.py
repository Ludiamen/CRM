"""T-100: каркас и стек (NFR-007…009, NFR-011, FR-018, FR-055).

Часть проверок смотрит на корень репозитория (deploy/): контейнеру тестов он
должен быть смонтирован (см. tests/CONTRACT.md, «Среда запуска»).
"""
import importlib
import re
import sys
from importlib import metadata

import pytest
from django.conf import settings

from tests import support
from tests.support import BACKEND_DIR, REPO_ROOT, repo_file

SECRET_ENV_NAMES = {
    "DJANGO_SECRET_KEY", "FIELD_ENCRYPTION_KEYS", "BACKUP_CODE_PEPPER", "POSTGRES_PASSWORD",
    "CRM_OWNER_PASSWORD", "CRM_APP_PASSWORD", "SMTP_PASSWORD",
}
PLAN_ENV_NAMES = SECRET_ENV_NAMES | {
    "DATABASE_URL", "DATABASE_MIGRATE_URL", "VALKEY_URL", "PORTAL_URL", "TRUSTED_PROXIES",
    "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_FROM", "SMTP_SECURITY",
}


def test_project_layout_matches_plan():
    """NFR-009 (опора): дерево PLAN-001 «Где живёт код» есть и импортируется."""
    for rel in ("config/settings.py", "config/urls.py", "config/asgi.py", "config/cron.py",
                "apps/core/__init__.py", "apps/integrations/mail/__init__.py",
                "apps/core/management/commands/create_first_admin.py",
                "apps/core/management/commands/rotate_field_keys.py",
                "templates", "static/vendor", "tests", "tests/e2e"):
        assert (BACKEND_DIR / rel).exists(), f"по плану должен быть backend/{rel}"
    for name in ("apps.core.models", "apps.core.services.audit", "apps.integrations.mail.models",
                 "apps.integrations.mail.services"):
        importlib.import_module(name)
    for rel in ("docker-compose.yml", "Dockerfile", "nginx.conf", ".env.example", "postgres-init"):
        assert (repo_file("deploy") / rel).exists(), f"по плану должен быть deploy/{rel}"


def test_vendor_assets_present_with_licenses():
    """NFR-007: Bootstrap, HTMX и Alpine (CSP-сборка) лежат в static/vendor с лицензиями и сверенными хешами; CDN нет."""
    vendor = BACKEND_DIR / "static" / "vendor"
    files = {
        "bootstrap css": next(vendor.glob("bootstrap-*.min.css")),
        "bootstrap js": next(vendor.glob("bootstrap-*.bundle.min.js")),
        "htmx": next(vendor.glob("htmx-*.min.js")),
        "alpine csp": next(vendor.glob("alpine-*.csp.min.js")),
    }
    for licence in ("LICENSE-bootstrap", "LICENSE-htmx", "LICENSE-alpine"):
        assert (vendor / licence).stat().st_size > 200, f"{licence} пуст"
    versions = (vendor / "VERSIONS.md").read_text(encoding="utf-8")
    assert re.search(r"Проверено:\s*\d{4}-\d{2}-\d{2}", versions), "в VERSIONS.md нет даты проверки"
    for name, path in files.items():
        assert support.sha256_file(path) in versions, f"хеш {path.name} ({name}) не записан в VERSIONS.md"
        assert path.name in versions
    from django.contrib.staticfiles import finders

    for path in files.values():
        assert finders.find(f"vendor/{path.name}"), f"staticfiles не находит vendor/{path.name}"
    templates = list((BACKEND_DIR / "templates").rglob("*.html"))
    assert templates, "шаблонов нет: статика ни на чём не подключена"
    combined = "\n".join(t.read_text(encoding="utf-8") for t in templates)
    for prefix in ("vendor/bootstrap-", "vendor/htmx-", "vendor/alpine-"):
        assert prefix in combined, f"шаблоны не подключают {prefix}* (через {{% static %}})"
    for template in templates:
        assert not re.search(r"""(src|href)=["']https?://""", template.read_text(encoding="utf-8")), (
            f"{template.name}: внешний адрес в шаблоне (CDN запрещён CSP)")


def test_env_example_has_only_placeholders():
    """FR-055: в .env.example только заглушки; все переменные плана и настроек описаны."""
    lines = repo_file("deploy", ".env.example").read_text(encoding="utf-8").splitlines()
    values, commented = {}, set()
    for line in lines:
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
        else:
            # решение Opus A1 (T-2119, п. 10): имя описано и строкой `# ИМЯ=значение`
            found = re.match(r"^#\s*([A-Z][A-Z0-9_]*)=", line.strip())
            if found:
                commented.add(found.group(1))
    assert PLAN_ENV_NAMES <= set(values), f"не описаны: {sorted(PLAN_ENV_NAMES - set(values))}"
    for name in SECRET_ENV_NAMES:
        assert values[name] in ("", "***"), f"{name}: в примере должна быть заглушка ***"
    for name in ("DATABASE_URL", "DATABASE_MIGRATE_URL"):
        assert re.search(r"://[^:@/]+:\*\*\*@", values[name]), f"{name}: пароль в адресе должен быть ***"
    read = set(re.findall(r'env(?:\.\w+)?\(\s*"([A-Z_]+)"', (BACKEND_DIR / "config/settings.py").read_text(encoding="utf-8")))
    described = set(values) | commented
    assert read <= described, f"settings.py читает, а .env.example не описывает: {sorted(read - described)}"
    assert not (BACKEND_DIR.parent / "deploy" / ".env.example").stat().st_mode & 0o111


def _dist_name(requirement: str) -> str:
    return re.split(r"[\[=<>!~; ]", requirement, maxsplit=1)[0]


def test_requirements_pinned_and_licensed():
    """NFR-011 (бесплатные компоненты): версии закреплены `==`, лицензии открытые."""
    pins = []
    for file in ("requirements.txt", "requirements-dev.txt"):
        for line in (BACKEND_DIR / file).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-r"):
                continue
            assert re.match(r"^[A-Za-z0-9_.\-]+(\[[a-z,]+\])?==\d+(\.\d+)*$", line), f"версия не закреплена: {line}"
            pins.append(_dist_name(line).lower().replace("_", "-"))
    required = {"django", "psycopg", "rq", "django-rq", "django-otp", "cryptography", "qrcode", "argon2-cffi",
                "ua-parser", "django-csp", "gunicorn", "uvicorn", "uvicorn-worker", "pillow", "django-environ",
                "pytest", "pytest-django", "pytest-playwright", "locust"}
    assert required <= set(pins), f"нет в requirements: {sorted(required - set(pins))}"
    open_markers = ("mit", "bsd", "apache", "lgpl", "unlicense", "psf", "python software", "hpnd", "isc", "0bsd", "mpl")
    for name in pins:
        meta = metadata.metadata(name)
        declared = " ".join([meta.get("License-Expression", ""), meta.get("License", "")[:300]]).lower()
        classifiers = " ".join(c for c in meta.get_all("Classifier", []) if c.startswith("License")).lower()
        text = declared if declared.strip() else classifiers
        assert any(m in text for m in open_markers), f"{name}: открытая лицензия не опознана ({text[:80]!r})"
        assert "proprietary" not in text and "commercial" not in text, f"{name}: платная лицензия"
    # всё, что код среза импортирует из чужих пакетов, должно быть в requirements
    stdlib, owners = sys.stdlib_module_names, metadata.packages_distributions()
    for path in list((BACKEND_DIR / "apps").rglob("*.py")) + list((BACKEND_DIR / "config").rglob("*.py")):
        for top in re.findall(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)", path.read_text(encoding="utf-8"), re.M):
            if top in stdlib or top in ("apps", "config", "tests", "django"):
                continue
            dists = {d.lower().replace("_", "-") for d in owners.get(top, [])}
            assert dists & set(pins), f"{path.relative_to(BACKEND_DIR)}: пакет {top} не закреплён в requirements"


def test_admin_not_installed():
    """FR-018: встроенной админки Django нет, администрирование — свой раздел с проверкой прав."""
    assert "django.contrib.admin" not in settings.INSTALLED_APPS
    assert "apps.core" in settings.INSTALLED_APPS and "apps.integrations.mail" in settings.INSTALLED_APPS, (
        "тесты идут на настройках без приложений среза (пока config.settings не подключён в pytest.ini)")
    assert settings.AUTH_USER_MODEL == "core.User"
    urls_source = (BACKEND_DIR / "config" / "urls.py").read_text(encoding="utf-8")
    assert "admin.site" not in urls_source
    client = support.make_client()
    for path in ("/admin/", "/admin/login/", "/django-rq/"):
        assert client.get(path).status_code == 404, f"{path} должен быть 404"


@pytest.mark.django_db
def test_database_engine_is_postgresql():
    """NFR-008: база — только PostgreSQL 17, запросы идут под ролью crm_app."""
    from django.db import connection

    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"
    assert settings.DATABASES["migrate"]["ENGINE"] == "django.db.backends.postgresql"
    with connection.cursor() as cur:
        cur.execute("SELECT current_user, current_setting('server_version_num')::int")
        user, version = cur.fetchone()
    assert (user, version >= 170000) == ("crm_app", True)
    assert settings.SESSION_ENGINE == "django.contrib.sessions.backends.db"
    with connection.cursor() as cur:
        cur.execute("SELECT tableowner FROM pg_tables WHERE tablename IN ('core_user', 'core_auditevent')")
        assert [r[0] for r in cur.fetchall()] == ["crm_owner", "crm_owner"], "таблицы среза создаёт и держит crm_owner"


# Слова конституции собраны из частей, чтобы файл сам не задевал ворота.
FORBIDDEN_WORDS = [a + b for a, b in (
    ("fast", "api"), ("fl", "ask"), ("lara", "vel"), ("sym", "fony"), ("exp", "ress"), ("nest", "js"),
    ("ra", "ils"), ("sp", "ring"), ("cel", "ery"), ("re", "act"), ("v", "ue"), ("ang", "ular"),
    ("sve", "lte"), ("nu", "xt"), ("next", "js"), ("my", "sql"), ("maria", "db"), ("mongo", "db"),
    ("sqli", "te3"), ("ora", "cle"), ("ms", "sql"), ("bit", "rix"), ("bx", "24"),
)]


def test_no_forbidden_words_in_backend_and_deploy():
    """Конституция (стек, бд, эталон-не-копия): запрещённых слов нет в backend/ и deploy/."""
    pattern = re.compile(r"\b(" + "|".join(FORBIDDEN_WORDS) + r")\b", re.IGNORECASE)
    found = []
    for root in (BACKEND_DIR, repo_file("deploy")):
        for path in root.rglob("*"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if (not path.is_file() or "static/vendor/" in rel or path.name == ".env" or "__pycache__" in rel
                    or path.stat().st_size > 1_000_000):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    found.append(f"{rel}:{number}")
    assert not found, found


LITERAL_PATTERNS = [
    re.compile(r"(?i)(password|passwd|secret|api_?key|token)\s*[:=]\s*['\"][^'\"$*{]{4,}['\"]"),
    re.compile(r"(?:^|[\s\-])[A-Z0-9_]*PASSWORD\s*[=:]\s*[^\s\"'$*{()]{4,}\s*$"),
    re.compile(r"(set_password|create_user|authenticate|login)\([^)]*['\"][^'\"]{6,}['\"]\s*\)"),
]


def _literal_hits(text: str) -> list[int]:
    return [n for n, line in enumerate(text.splitlines(), 1)
            if any(p.search(line) for p in LITERAL_PATTERNS[:2])]


def test_no_literal_passwords_in_tests():
    """NFR-011: в тестах нет паролей и секретов литералом (решение владельца 2026-09-29)."""
    probe = "pass" + "word = " + "'" + "abcdef" + "'"  # собран из частей: сам файл не должен совпасть
    assert _literal_hits(probe), "детектор не ловит литерал"
    assert not _literal_hits("password = secrets.token_urlsafe(16)")
    offenders = []
    for path in (BACKEND_DIR / "tests").rglob("*.py"):
        for number in _literal_hits(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(BACKEND_DIR)}:{number}")
    assert not offenders, offenders


# ---- Срез 002 (T-2118): каркас и компоненты ----

SLICE_002_TREE = (
    # (путь от backend/, файл или каталог) — ровно блок плана PLAN-002 «Где живёт код»
    ("apps/org/__init__.py", "file"), ("apps/org/apps.py", "file"), ("apps/org/models.py", "file"),
    ("apps/org/extensions.py", "file"), ("apps/org/audit_labels.py", "file"), ("apps/org/urls.py", "file"),
    ("apps/org/views", "dir"), ("apps/org/migrations", "dir"), ("apps/org/services", "dir"),
    ("apps/org/services/structure.py", "file"), ("apps/org/services/membership.py", "file"),
    ("apps/org/services/people.py", "file"), ("apps/org/services/unit_roles.py", "file"),
    ("apps/org/services/calendar.py", "file"), ("apps/org/services/calendar_file.py", "file"),
    ("apps/org/services/staff_import.py", "file"),
    ("apps/integrations/clamav/__init__.py", "file"), ("apps/integrations/clamav/client.py", "file"),
    ("apps/integrations/clamav/services.py", "file"), ("apps/core/extensions.py", "file"),
    ("templates/org", "dir"), ("templates/calendar", "dir"), ("templates/widgets", "dir"),
    ("templates/widgets/date_field.html", "file"), ("static/js/datefield.js", "file"),
    ("tests/fixtures/calendar", "dir"), ("tests/e2e", "dir"),
)


def test_slice_002_layout_matches_plan():
    """NFR-108 (опора): дерево PLAN-002 «Где живёт код» есть; apps.org подключено, clamav — пакет без моделей."""
    for rel, kind in SLICE_002_TREE:
        path = BACKEND_DIR / rel
        assert path.is_file() if kind == "file" else path.is_dir(), f"по плану должен быть backend/{rel} ({kind})"
    assert "apps.org" in settings.INSTALLED_APPS
    assert not any(a.startswith("apps.integrations.clamav") for a in settings.INSTALLED_APPS), \
        "адаптер clamd не приложение Django: в INSTALLED_APPS не входит"
    from django.apps import apps

    assert apps.get_app_config("org").name == "apps.org"
    for name in ("apps.org.services.structure", "apps.org.services.membership", "apps.org.services.people",
                 "apps.org.services.unit_roles", "apps.org.services.calendar", "apps.org.services.calendar_file",
                 "apps.org.services.staff_import", "apps.org.extensions", "apps.org.audit_labels", "apps.org.urls",
                 "apps.org.views", "apps.integrations.clamav.client", "apps.integrations.clamav.services",
                 "apps.core.extensions"):
        importlib.import_module(name)
    assert not [m for m in apps.get_models() if m.__module__.startswith("apps.integrations.clamav")]


def test_requirements_include_slice_002_packages():
    """NFR-108: openpyxl 3.1.x, et-xmlfile 2.x и defusedxml 0.7.x закреплены `==` в requirements.txt и установлены."""
    lines = {}
    for line in (BACKEND_DIR / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        match = re.match(r"^([A-Za-z0-9_.\-]+)==(\d+(?:\.\d+)*)$", line)
        if match:
            lines[match.group(1).lower().replace("_", "-")] = match.group(2)
    for name, prefix, classifier in (
            ("openpyxl", "3.1.", "License :: OSI Approved :: MIT License"),
            ("et-xmlfile", "2.", "License :: OSI Approved :: MIT License"),
            ("defusedxml", "0.7.", "License :: OSI Approved :: Python Software Foundation License")):
        assert name in lines, f"{name} не закреплён == в requirements.txt"
        assert lines[name].startswith(prefix), f"{name}=={lines[name]}: по плану {prefix}x"
        assert metadata.version(name) == lines[name], f"{name}: установлена не закреплённая версия"
        meta = metadata.metadata(name)
        classifiers = [c for c in meta.get_all("Classifier", []) if c.startswith("License")]
        # лицензия плана (MIT, MIT, PSF-2.0) — точное совпадение классификатора пакета, не подстрока
        assert classifier in classifiers, f"{name}: классификатор лицензии {classifiers}, по плану {classifier!r}"
    assert "clamd" not in lines, "пакет clamd с PyPI не берём: клиент свой (план)"


def test_openpyxl_uses_defusedxml():
    """NFR-108: openpyxl подхватил defusedxml (openpyxl.xml.DEFUSEDXML истинно) и отвергает XML-бомбу."""
    import defusedxml
    import openpyxl.xml
    from openpyxl.xml.functions import fromstring

    assert defusedxml.__version__.startswith("0.7.")
    assert openpyxl.xml.DEFUSEDXML is True
    bomb = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa">'
            '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><lolz>&b;&b;&b;</lolz>')
    with pytest.raises(defusedxml.DefusedXmlException):
        fromstring(bomb)
