"""T-108 (дополнение): границы настроек безопасности (FR-027, NFR-005, NFR-006). Сценарий 17.2.

Таблица границ — «Решения Opus по вопросам этапа 2а» в tests/CONTRACT.md: администратор только ужесточает
утверждённые значения; значение на границе принимается, за границей — отказ формы с объяснением (в тексте есть
нарушенная граница), записанное значение не меняется, в журнал ничего не пишется.
"""
import pytest

from tests import support
from tests.support import model

pytestmark = pytest.mark.django_db

# поле: (нижняя граница, верхняя граница); None у password_max_age_days — «выключено» допустимо отдельно
BOUNDS = {
    "password_min_length": (12, 128),
    "password_history": (5, 24),
    "password_max_age_days": (30, 365),
    "idle_timeout_minutes": (5, 60),
    "account_lock_limit": (3, 5),
    "account_lock_minutes": (15, 1440),
    "ip_lock_limit": (5, 100),
    "ip_lock_min_accounts": (2, 20),
    "ip_lock_window_minutes": (5, 60),
    "ip_lock_minutes": (15, 1440),
    "login_history_days": (30, 365),
}
ACCEPTED = [(f, v) for f, (lo, hi) in BOUNDS.items() for v in (lo, hi)]
REJECTED = [(f, v, bound) for f, (lo, hi) in BOUNDS.items() for v, bound in ((lo - 1, lo), (hi + 1, hi))]


def admin_client():
    return support.logged_in(support.make_with_permissions("settings.security"), ip="198.51.100.210")


def current(field):
    return getattr(model("core.SecuritySettings").objects.get(), field)


def updates():
    return model("core.AuditEvent").objects.filter(action="security_settings.updated").count()


def test_bounds_table_matches_contract_fields():
    """Таблица границ покрывает все поля политики из формы."""
    assert set(BOUNDS) == set(support.SECURITY_FIELDS)


@pytest.mark.parametrize("field,value", ACCEPTED, ids=[f"{f}={v}" for f, v in ACCEPTED])
def test_value_on_bound_is_accepted(field, value):
    """Сценарий 17.2: значение на границе допустимо — форма сохраняется."""
    done = support.post_security_settings(admin_client(), **{field: value})
    assert done.status_code == 302, f"{field}={value}: {done.status_code}"
    assert current(field) == value
    assert updates() <= 1


@pytest.mark.parametrize("field,value,bound", REJECTED, ids=[f"{f}={v}" for f, v, _ in REJECTED])
def test_value_beyond_bound_is_rejected_with_explanation(field, value, bound):
    """Сценарий 17.2: за границей — отказ формы с объяснением, какая граница нарушена; значение и журнал не меняются."""
    before = current(field)
    done = support.post_security_settings(admin_client(), **{field: value})
    assert done.status_code == 200, f"{field}={value} должно отклоняться, получили {done.status_code}"
    assert str(bound) in done.content.decode(), f"в отказе нет границы {bound}"
    assert current(field) == before and updates() == 0


def test_max_age_off_or_within_30_365_only():
    """Срок пароля: пусто («нет») допустимо, 0 и отрицательные — нет, 30…365 — да."""
    client = admin_client()
    assert support.post_security_settings(client, password_max_age_days=90).status_code == 302
    assert support.post_security_settings(client, password_max_age_days=None).status_code == 302
    assert current("password_max_age_days") is None
    for bad in (0, -1, 29, 366):
        assert support.post_security_settings(client, password_max_age_days=bad).status_code == 200, bad
    assert current("password_max_age_days") is None


def test_not_a_number_is_rejected():
    """Нечисловое и дробное значение — отказ, как и выход за границы."""
    client = admin_client()
    for field in ("password_min_length", "account_lock_limit", "ip_lock_limit"):
        for junk in ("abc", "12.5", "1e3", " "):
            before = current(field)
            assert support.post_security_settings(client, **{field: junk}).status_code == 200, (field, junk)
            assert current(field) == before
    assert updates() == 0


def test_one_bad_value_saves_nothing():
    """Форма сохраняется целиком или не сохраняется: одно значение за границей — остальные правки тоже не применяются."""
    client = admin_client()
    done = support.post_security_settings(client, password_min_length=20, account_lock_limit=2)
    assert done.status_code == 200
    assert current("password_min_length") == 12 and current("account_lock_limit") == 5 and updates() == 0


def test_cannot_weaken_below_approved_values_even_in_combination():
    """Нельзя ослабить ни одно утверждённое значение: допустимые границы не шире утверждённых по умолчанию (12, 5, 60 мин, 5 попыток)."""
    client = admin_client()
    weaker = {"password_min_length": 8, "password_history": 3, "idle_timeout_minutes": 120, "account_lock_limit": 10,
              "account_lock_minutes": 5, "ip_lock_minutes": 5, "login_history_days": 7}
    for field, value in weaker.items():
        assert support.post_security_settings(client, **{field: value}).status_code == 200, f"{field}={value} ослабляет политику"
    support.post_security_settings(client, **weaker)
    row = model("core.SecuritySettings").objects.get()
    assert (row.password_min_length, row.password_history, row.idle_timeout_minutes, row.account_lock_limit) == (12, 5, 60, 5)
    assert updates() == 0
