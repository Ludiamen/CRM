"""Общие фикстуры pytest (T-009, T-010).

- Тестовая база создаётся и мигрируется под crm_owner (алиас `migrate`), а
  запросы теста идут под crm_app (алиас `default`) — как на настоящей установке
  (NFR-008): права по умолчанию и защита журнала проверяются теми же ролями.
  Следствие: `django_db(transaction=True)` не работает (сброс таблиц требует
  прав владельца) — для on_commit есть `django_capture_on_commit_callbacks`.
- Valkey очищается перед каждым тестом; рабочую базу 0 тесты не трогают:
  в VALKEY_URL тестового запуска стоит номер базы 15 (compose, сервис test).
- RQ — настоящий Valkey, без eager-режима.
"""
import pytest
import redis
from django.conf import settings

from tests import factories
from tests.support_servicedesk import bus, bus_spy, fake_mailbox, live_mailbox  # noqa: F401  (фикстуры среза 003, CONTRACT-003 § 3.1, § 5.2)


@pytest.fixture(scope="session")
def django_db_setup(request, django_test_environment, django_db_blocker):
    from django.db import connections

    if "migrate" not in settings.DATABASES:
        pytest.exit("DATABASE_MIGRATE_URL не задан: схему тестовой базы создаёт crm_owner", returncode=3)
    keepdb = request.config.getoption("reuse_db", False)
    owner, app = connections["migrate"], connections["default"]
    with django_db_blocker.unblock():
        старое_имя = owner.settings_dict["NAME"]
        test_name = owner.creation.create_test_db(verbosity=0, autoclobber=True, keepdb=keepdb, serialize=False)
        app.close()
        app.settings_dict["NAME"] = test_name
    yield
    with django_db_blocker.unblock():
        app.close()
        owner.creation.destroy_test_db(старое_имя, verbosity=0, keepdb=keepdb)


@pytest.fixture(autouse=True)
def valkey_clean(request):
    """Пустой Valkey перед каждым тестом (счётчики блокировок, кэш, очереди).

    Проходы Playwright (метка e2e) идут с хоста против стенда и Valkey не трогают.
    """
    if request.node.get_closest_marker("e2e"):
        yield None
        return
    client = redis.Redis.from_url(settings.VALKEY_URL)
    if client.connection_pool.connection_kwargs.get("db", 0) == 0:
        pytest.exit("тесты не чистят базу 0 Valkey: в VALKEY_URL укажите другую (…/15)", returncode=3)
    client.flushdb()
    yield client
    client.close()


@pytest.fixture
def password() -> str:
    return factories.new_password()


@pytest.fixture
def mailpit() -> factories.MailpitClient:
    client = factories.MailpitClient()
    client.clear()
    return client


@pytest.fixture
def clock():
    c = factories.Clock().start()
    yield c
    c.stop()


@pytest.fixture
def totp():
    return factories.totp_code


@pytest.fixture
def protected_root(settings, tmp_path):
    """Каталог тома `protected` во временной папке теста (CONTRACT-002 § 1): `settings.PROTECTED_ROOT`."""
    settings.PROTECTED_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def no_extensions():
    """Тело теста идёт внутри `apps.core.extensions.empty()` (CONTRACT-002 § 5).

    Пока `extensions.empty` нет, фикстура падает понятной ошибкой при использовании, а не при сборе."""
    try:
        from apps.core import extensions
        empty = extensions.empty
    except (ImportError, AttributeError):
        pytest.fail("нет apps.core.extensions.empty(): фикстура no_extensions ждёт код среза 002 (CONTRACT-002 § 5)")
    with empty():
        yield
