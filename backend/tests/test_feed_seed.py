"""T-7133: права и данные установки среза 007 — миграция данных `feed 0002` (права «Писать всем» и «Модерировать
ленту», выдача ролям, строка `FeedSettings`) (FR-610, FR-638, FR-640). Сценарий 13 спеки («Права и данные установки»).

Контракт: CONTRACT-007 — 2.3 (миграция данных), 1.4 (восемнадцать прав), 5.9 (`run_seed`, `without_post_all`,
`PERMISSIONS_007`, `TITLES_007`, `HOLDERS_007`). Вызовы идут на соединении `default` (`run_seed(using="default")`):
тестовая база уже мигрирована, поэтому каждый тест сначала возвращает её к виду «до миграции данных» своим
`_clear()` (в `support_feed` помощника `clear_seed` нет — временная замена внутри файла, как `support_lists.clear_seed`).
Код среза импортируется внутри функций.
"""
import pytest

from tests import support
from tests import support_feed as fd

pytestmark = pytest.mark.django_db

ADMIN_ROLE = support.ADMIN_ROLE
MANAGER_ROLE = support.MANAGER_ROLE
STAFF_ROLE = support.STAFF_ROLE
BUILTIN_ROLES = (ADMIN_ROLE, MANAGER_ROLE, STAFF_ROLE)


def _model(label: str):
    return support.model(label)


def _role(name: str):
    return _model("core.Role").objects.get(name=name, is_builtin=True)


def _codes(role) -> set:
    return set(role.permissions.values_list("code", flat=True))


def _holders(code: str) -> set:
    """Названия ролей, у которых есть право `code`."""
    return set(_model("core.Role").objects.filter(permissions__code=code).values_list("name", flat=True))


def _clear() -> None:
    """«До миграции данных»: прав ленты и строки настройки нет; кэш прав сброшен (каскадное удаление строк выдачи
    сигнала `m2m_changed` не шлёт)."""
    from apps.core.services import permissions

    _model("core.Permission").objects.filter(code__in=fd.PERMISSIONS_007).delete()
    _model("feed.FeedSettings").objects.all().delete()
    permissions.forget_all()
    assert not _model("core.Permission").objects.filter(code__in=fd.PERMISSIONS_007).exists()
    assert not _model("feed.FeedSettings").objects.exists()


def _seeded() -> None:
    _clear()
    fd.run_seed(using="default")


# --- права и их названия ------------------------------------------------------------------------------------

def test_seed_on_slice_006_base_creates_post_all_and_moderate_permissions_with_russian_names():
    """FR-640: на базе среза 006 (прав ленты нет, шестнадцать прав) `seed` создаёт `feed.post_all` («Писать всем») и
    `feed.moderate` («Модерировать ленту») с русскими названиями, по одной строке каждого (раздел 2.3)."""
    _clear()
    Permission = _model("core.Permission")
    assert Permission.objects.count() == 16
    fd.run_seed(using="default")
    for code in fd.PERMISSIONS_007:
        rows = list(Permission.objects.filter(code=code))
        assert len(rows) == 1, code
        assert rows[0].title == fd.TITLES_007[code], code
        assert not rows[0].title.isascii(), code
    assert fd.TITLES_007 == {"feed.post_all": "Писать всем", "feed.moderate": "Модерировать ленту"}


def test_seed_grants_post_all_to_every_role_existing_at_install_including_admin_created_role():
    """FR-640: «Писать всем» получают все роли, существующие на момент установки: три начальные («Администратор
    портала», «Руководитель», «Сотрудник ИТ») и роль, созданная администратором до установки (не встроенная)."""
    _clear()
    Role = _model("core.Role")
    created_by_admin = Role.objects.create(name="Роль, созданная администратором до установки", is_builtin=False)
    everyone = set(Role.objects.values_list("name", flat=True))
    assert created_by_admin.name in everyone and set(BUILTIN_ROLES) <= everyone
    fd.run_seed(using="default")
    assert _holders("feed.post_all") == everyone
    assert "feed.post_all" in _codes(Role.objects.get(pk=created_by_admin.pk))
    for name in BUILTIN_ROLES:
        assert "feed.post_all" in _codes(_role(name)), name


def test_seed_grants_moderate_to_portal_admin_role_only():
    """FR-640: «Модерировать ленту» выдаётся только роли «Администратор портала»; «Руководитель», «Сотрудник ИТ» и
    роль, созданная администратором, права не получают."""
    _clear()
    custom = _model("core.Role").objects.create(name="Своя роль до установки", is_builtin=False)
    fd.run_seed(using="default")
    assert _holders("feed.moderate") == {ADMIN_ROLE}
    assert "feed.moderate" not in _codes(_role(MANAGER_ROLE))
    assert "feed.moderate" not in _codes(_role(STAFF_ROLE))
    assert "feed.moderate" not in _codes(_model("core.Role").objects.get(pk=custom.pk))
    assert fd.HOLDERS_007["feed.moderate"] == (ADMIN_ROLE,)


def test_seed_adds_feed_rights_and_keeps_prior_permissions_of_roles():
    """FR-640: выдача — добавление, а не замена: все прежние права ролей (начальных и созданной) остаются, названия
    чужих прав не перезаписываются."""
    _clear()
    Role, Permission = _model("core.Role"), _model("core.Permission")
    prior_permission = Permission.objects.get(code="audit.view")
    custom = Role.objects.create(name="Роль с прежним правом", is_builtin=False)
    custom.permissions.add(prior_permission)
    _role(STAFF_ROLE).permissions.add(prior_permission)
    names = BUILTIN_ROLES + (custom.name,)
    before = {name: _codes(Role.objects.get(name=name)) for name in names}
    assert "audit.view" in before[custom.name] and "audit.view" in before[STAFF_ROLE]
    Permission.objects.filter(code="audit.view").update(title="Свой заголовок права")
    fd.run_seed(using="default")
    expected_extra = {name: {"feed.post_all"} | ({"feed.moderate"} if name == ADMIN_ROLE else set())
                      for name in names}
    for name in names:
        assert _codes(Role.objects.get(name=name)) == before[name] | expected_extra[name], name
    assert Permission.objects.get(code="audit.view").title == "Свой заголовок права"


def test_seed_without_portal_admin_role_passes_without_error():
    """FR-640: роли «Администратор портала» нет (встроенная переименована) — `seed` не падает: права создаются,
    «Писать всем» получают все роли, «Модерировать ленту» не получает никто (раздел 2.3: `filter().first()`)."""
    _clear()
    Role = _model("core.Role")
    Role.objects.filter(name=ADMIN_ROLE, is_builtin=True).update(name="Администратор портала (старая)")
    assert not Role.objects.filter(name=ADMIN_ROLE).exists()
    fd.run_seed(using="default")
    assert _model("core.Permission").objects.filter(code__in=fd.PERMISSIONS_007).count() == 2
    assert not Role.objects.filter(permissions__code="feed.moderate").exists()
    assert _holders("feed.post_all") == set(Role.objects.values_list("name", flat=True))


def test_portal_has_eighteen_permissions_after_seed():
    """FR-640: до `seed` в портале шестнадцать прав, после — восемнадцать; `feed.post_all` и `feed.moderate` — два
    последних по порядку создания (раздел 1.4 контракта; порядок между собой не проверяется)."""
    _clear()
    Permission = _model("core.Permission")
    assert Permission.objects.count() == 16
    fd.run_seed(using="default")
    assert Permission.objects.count() == 18
    assert set(Permission.objects.order_by("-pk").values_list("code", flat=True)[:2]) == set(fd.PERMISSIONS_007)


# --- однократность ------------------------------------------------------------------------------------------

def test_second_seed_call_does_not_return_removed_post_all_or_moderate():
    """FR-640: миграция выполняется один раз — снятое администратором право повторный вызов без `stand` не возвращает:
    «Писать всем» снято у «Сотрудника ИТ», «Модерировать ленту» — у «Администратора портала»; права не дублируются."""
    _seeded()
    through = _model("core.Role").permissions.through
    fd.without_post_all(STAFF_ROLE)
    through.objects.filter(role=_role(ADMIN_ROLE), permission__code="feed.moderate").delete()
    assert "feed.post_all" not in _codes(_role(STAFF_ROLE))
    assert "feed.moderate" not in _codes(_role(ADMIN_ROLE))
    fd.run_seed(using="default")
    assert "feed.post_all" not in _codes(_role(STAFF_ROLE)), "повторный seed вернул «Писать всем»"
    assert "feed.moderate" not in _codes(_role(ADMIN_ROLE)), "повторный seed вернул «Модерировать ленту»"
    assert _holders("feed.post_all") == set(_model("core.Role").objects.values_list("name", flat=True)) - {STAFF_ROLE}
    for code in fd.PERMISSIONS_007:
        assert _model("core.Permission").objects.filter(code=code).count() == 1, code


def test_role_created_after_seed_has_no_post_all_until_checked():
    """FR-640: роль, созданная после установки, права «Писать всем» не имеет (повторный `seed` его не выдаёт); его
    сотруднику даёт галочка — смена прав роли средствами ядра."""
    from apps.core.services import permissions, roles

    _seeded()
    late = _model("core.Role").objects.create(name="Роль после установки", is_builtin=False)
    fd.run_seed(using="default")
    assert _codes(late) == set()
    user = support.make_employee(roles=[late])
    assert not permissions.has_permission(user, "feed.post_all")
    roles.update_role(late, late.name, ["feed.post_all"], actor=support.make_admin())
    assert _codes(late) == {"feed.post_all"}
    # кэш прав после смены роли сбрасывается только после фиксации (в тесте её нет): читаем без кэша
    assert "feed.post_all" in permissions.permissions_of(user, fresh=True)


def test_employee_without_roles_has_no_post_all_right():
    """FR-640, FR-610: сотрудник без ролей права «Писать всем» не имеет: служба видимости это знает, а запись «Всем» в
    обход формы отклоняется кодом `post_all_denied` и не создаётся."""
    from apps.core.services import permissions
    from apps.feed.services import visibility

    _seeded()
    user = support.make_employee()
    assert not permissions.has_permission(user, "feed.post_all")
    assert visibility.viewer(user).post_all is False
    Post = _model("feed.Post")
    before = Post.objects.count()
    response = support.logged_in(user).post("/feed/posts/", {"kind": "post", "text": "Текст для всех", "to": ["all"]})
    assert response.status_code == 200
    assert 'data-code="post_all_denied"' in response.content.decode("utf-8")
    assert Post.objects.count() == before


# --- настройка срока ----------------------------------------------------------------------------------------

def test_seed_creates_feed_settings_row_with_three_years_when_missing():
    """FR-640, FR-638: строки настройки нет — `seed` создаёт `FeedSettings(pk=1, retention_years=3)` ровно одну."""
    _clear()
    Settings = _model("feed.FeedSettings")
    fd.run_seed(using="default")
    rows = list(Settings.objects.all())
    assert [(row.pk, row.retention_years) for row in rows] == [(1, 3)]
    assert rows[0].updated_by_id is None and rows[0].updated_at is None


def test_seed_keeps_existing_feed_settings_row_unchanged():
    """FR-640, FR-638: строка настройки уже есть (администратор поставил 7 лет) — `seed` её не меняет и не дублирует."""
    _clear()
    Settings = _model("feed.FeedSettings")
    Settings.objects.create(pk=1, retention_years=7)
    fd.run_seed(using="default")
    assert [(row.pk, row.retention_years) for row in Settings.objects.all()] == [(1, 7)]


# --- снятие права и записи «Всем» ---------------------------------------------------------------------------

def test_removing_post_all_from_role_keeps_published_to_all_posts_visible_to_everyone():
    """FR-640: снятие «Писать всем» уже опубликованные записи «Всем» не отзывает: запись остаётся видна другому
    сотруднику без права, у записи остаётся `to_all`, автор по-прежнему правит её как свою (FR-620)."""
    from apps.feed.services import visibility

    _seeded()
    writer = fd.as_writer()
    reader = fd.as_plain()
    post = fd.make_post(writer.user, to=("all",))
    role = writer.user.roles.get()
    fd.without_post_all(role)
    assert "feed.post_all" not in _codes(role)

    assert _model("feed.Post").objects.get(pk=post.pk).to_all is True
    assert post.pk in set(visibility.visible_posts(reader.user).values_list("pk", flat=True))
    assert reader.client.get(f"/feed/{post.pk}/").status_code == 200
    author = _model("core.User").objects.get(pk=writer.user.pk)
    assert visibility.can_edit(author, post) is True
    assert writer.client.get(f"/feed/{post.pk}/edit/").status_code == 200
