"""T-7102a: видимость записи, аудитория, права действий (FR-603, FR-604, FR-605, FR-606, FR-607, FR-611, FR-620, FR-621,
FR-622). Сценарии 2-6 спеки; CONTRACT-007, разделы 5.2, 5.3, 8.

Код среза на уровне модуля не импортируется: имена берутся внутри тестов (CONTRACT-007, шапка). Помощники — только
`support_feed.py` и прежние `support*.py`. Упоминание, создаваемое действием, идёт через службы `feed` (К44), а не
через `make_post(mentions=...)`. Записи, которые строит помощник, — прямой записью без служб.
"""
import re

import pytest
from django.http import Http404

from tests import support
from tests import support_feed as ff
from tests import support_org as org
from tests.support import HX

pytestmark = pytest.mark.django_db


def _employee(name: str = "Сотрудник Тестов", **extra):
    return support.make_employee(full_name=name, **extra)


def _session(user) -> ff.Session:
    return ff.Session(user, support.logged_in(user))


def _fresh(user):
    """Тот же сотрудник новым объектом: кэш `_feed_viewer` прежнего объекта не переносится."""
    return support.model("core.User").objects.get(pk=user.pk)


def _visible_ids(user) -> set[int]:
    from apps.feed.services import visibility

    return set(visibility.visible_posts(_fresh(user)).values_list("pk", flat=True))


def _member(unit, name: str = "Участник Узлов", **extra):
    user = _employee(name, **extra)
    org.make_member(user, unit)
    return user


def _card_status(user, post) -> int:
    return support.logged_in(user).get(f"/feed/{post.pk}/").status_code


# --- таблица «кто видит» ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("case, expected", [
    ("author", True),
    ("person_addressee", True),
    ("unit_member", True),
    ("nested_unit_member", True),
    ("parent_unit_member", False),
    ("sibling_unit_member", False),
    ("outsider", False),
    ("moderator_not_addressee", False),
    ("portal_admin_not_addressee", False),
])
def test_visibility_table_post_by_employee_parametrized_authors_and_addressees_only(case, expected):
    """FR-605, FR-606: запись видят автор и адресаты, и только они (подразделение — с вложенными узлами; предок и
    сосед не видят); модератор и администратор без адресации не видят. Запись, карточка и `can_see` согласованы."""
    from apps.feed.services import visibility

    author = _employee("Автор Авторов")
    person = _employee("Адресат Личный")
    tree = org.make_tree({"Отдел ИТ": {"Группа сети": {}}, "Бухгалтерия": {}})
    it, net, accounting = tree["Отдел ИТ"], tree["Группа сети"], tree["Бухгалтерия"]
    users = {
        "author": author,
        "person_addressee": person,
        "unit_member": _member(it, "Участник Отдела"),
        "nested_unit_member": _member(net, "Участник Группы"),
        "parent_unit_member": _member(org.root_unit(), "Участник Корня"),
        "sibling_unit_member": _member(accounting, "Участник Бухгалтерии"),
        "outsider": _employee("Посторонний Лиц"),
        "moderator_not_addressee": ff.as_moderator().user,
        "portal_admin_not_addressee": support.make_admin(),
    }
    post = ff.make_post(author, to=[it, person])
    user = users[case]
    assert (post.pk in _visible_ids(user)) is expected
    assert visibility.can_see(user.pk, post.pk) is expected
    assert _card_status(user, post) == (200 if expected else 404)


# --- состав подразделения считается на момент просмотра -----------------------------------------------------------

def test_unit_newcomer_sees_earlier_post_and_transferred_employee_stops_seeing():
    """FR-605, сценарий 4: принятый в подразделение позже видит прежнюю запись; переведённый из него перестаёт."""
    unit = org.make_unit("Отдел ИТ")
    other = org.make_unit("Бухгалтерия")
    author = _employee()
    leaver = _member(unit, "Переведённый Сотрудник")
    post = ff.make_post(author, to=[unit])
    assert post.pk in _visible_ids(leaver)

    newcomer = _employee("Новичок Отдела")
    assert post.pk not in _visible_ids(newcomer)
    org.make_member(newcomer, unit)
    assert post.pk in _visible_ids(newcomer)

    support.model("org.Membership").objects.filter(user=leaver, unit=unit).delete()
    org.make_member(leaver, other)
    assert post.pk not in _visible_ids(leaver)
    assert post.pk in _visible_ids(newcomer)


def test_unit_and_person_from_other_department_both_see_post_and_line_shows_unit_and_person():
    """FR-603, FR-605, сценарий 5: запись для «Группа сети» и Петрова из другого отдела — видят оба; на записи
    «→ Группа сети, Петров И. И.»."""
    from apps.feed.services import recipients

    tree = org.make_tree({"Отдел ИТ": {"Группа сети": {}}, "Бухгалтерия": {}})
    net = tree["Группа сети"]
    petrov = _member(tree["Бухгалтерия"], "Петров И. И.")
    net_member = _member(net, "Сетевой Инженер")
    author = _employee("Автор Авторов")
    post = ff.make_post(author, to=[net, petrov])

    assert post.pk in _visible_ids(petrov)
    assert post.pk in _visible_ids(net_member)
    assert recipients.line(post).items == ["Группа сети", "Петров И. И."]
    for user in (petrov, net_member):
        html = support.logged_in(user).get(f"/feed/{post.pk}/").content.decode()
        line = ff.post_part(html, post.pk, "to")
        assert line is not None
        assert "Группа сети" in line.text and "Петров И. И." in line.text


# --- удалённый узел ----------------------------------------------------------------------------------------------

def test_deleted_unit_grants_nobody_while_person_and_author_still_see():
    """FR-605, FR-607: по удалённому подразделению запись больше никто не видит; адресат-человек и автор видят."""
    from apps.feed.services import visibility

    unit = org.make_unit("Временный отдел")
    member = _member(unit, "Бывший Участник")
    person = _employee("Адресат Личный")
    author = _employee("Автор Авторов")
    post = ff.make_post(author, to=[unit, person])
    assert post.pk in _visible_ids(member)

    support.model("org.Membership").objects.filter(unit=unit).delete()
    unit.delete()

    assert post.pk not in _visible_ids(member)
    assert visibility.can_see(member.pk, post.pk) is False
    assert post.pk in _visible_ids(person)
    assert post.pk in _visible_ids(author)
    assert member.pk not in visibility.audience(post)
    assert {person.pk, author.pk} <= visibility.audience(post)


def test_unit_with_addressed_post_is_deleted_without_refusal():
    """FR-607: удаление подразделения записи ленты не блокируют; запись остаётся."""
    from apps.org.services import structure

    unit = org.make_unit("Пустой отдел")
    author = _employee()
    post = ff.make_post(author, to=[unit])

    structure.delete_unit(unit, actor=support.make_admin())   # не поднимает OrgError

    assert not support.model("org.Unit").objects.filter(pk=unit.pk).exists()
    assert support.model("feed.Post").objects.filter(pk=post.pk).exists()
    assert post.pk in _visible_ids(author)


# --- модератор и упоминание --------------------------------------------------------------------------------------

def test_moderator_not_addressee_gets_404_on_card_like_everyone():
    """FR-604, FR-606: модератор без адресации видит запись как все — 404, как у несуществующей."""
    author, other = _employee("Автор Авторов"), _employee("Адресат Личный")
    post = ff.make_post(author, to=[other])
    moderator = ff.as_moderator()
    card = moderator.client.get(f"/feed/{post.pk}/")
    missing = moderator.client.get("/feed/999999/")
    assert card.status_code == 404
    assert support.same_failure(card, missing)
    assert post.pk not in _visible_ids(moderator.user)


def test_moderator_mentioned_in_comment_then_sees_card_and_may_delete_post(django_capture_on_commit_callbacks):
    """FR-606, FR-611: упомянутый в комментарии модератор становится адресатом: видит карточку и вправе удалить запись."""
    from apps.feed.services import comments, visibility

    author, commenter = _employee("Автор Авторов"), _employee("Комментатор Тестов")
    post = ff.make_post(author, to=[commenter])
    moderator = ff.as_moderator()
    assert moderator.client.get(f"/feed/{post.pk}/").status_code == 404

    with django_capture_on_commit_callbacks(execute=True):
        comments.add(commenter, post.pk, f"Посмотрите @[{moderator.user.pk}]")

    assert moderator.client.get(f"/feed/{post.pk}/").status_code == 200
    assert visibility.can_delete(_fresh(moderator.user), post) is True
    with django_capture_on_commit_callbacks(execute=True):
        response = moderator.client.post(f"/feed/{post.pk}/delete/", **HX)
    assert response.status_code == 200
    assert not support.model("feed.Post").objects.filter(pk=post.pk).exists()


def test_user_mentioned_in_comment_becomes_addressee_and_sees_card_with_all_comments(
        django_capture_on_commit_callbacks):
    """FR-604, FR-605, FR-611: упомянутый в комментарии добавляется в адресаты записи и видит карточку со всеми
    комментариями, в том числе написанными до упоминания."""
    from apps.feed.services import comments, visibility

    author, commenter = _employee("Автор Авторов"), _employee("Комментатор Тестов")
    mentioned = _session(_employee("Упомянутый Сотрудник"))
    post = ff.make_post(author, to=[commenter])
    ff.comment(post, author, "Первый комментарий до упоминания")
    assert mentioned.client.get(f"/feed/{post.pk}/").status_code == 404

    with django_capture_on_commit_callbacks(execute=True):
        comments.add(commenter, post.pk, f"Второй комментарий @[{mentioned.user.pk}]")

    recipient = support.model("feed.Recipient").objects.get(post=post, user=mentioned.user, via="mention")
    assert recipient.kind == "user"
    assert mentioned.user.pk in visibility.audience(post)
    response = mentioned.client.get(f"/feed/{post.pk}/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Первый комментарий до упоминания" in body
    assert "Второй комментарий" in body


def test_mention_in_post_text_adds_mention_recipient_and_grants_visibility(django_capture_on_commit_callbacks):
    """FR-605, FR-611: упомянутый в тексте записи получает строку `via="mention"` и видит запись."""
    from apps.feed.services import posts

    author, addressee = _employee("Автор Авторов"), _employee("Адресат Личный")
    mentioned = _session(_employee("Упомянутый Сотрудник"))
    with django_capture_on_commit_callbacks(execute=True):
        post = posts.publish(author, {"text": f"Коллеги, @[{mentioned.user.pk}] посмотрите", "to": [f"p{addressee.pk}"]})

    rows = support.model("feed.Recipient").objects.filter(post=post, user=mentioned.user)
    assert [(row.kind, row.via) for row in rows] == [("user", "mention")]
    assert post.pk in _visible_ids(mentioned.user)
    assert mentioned.client.get(f"/feed/{post.pk}/").status_code == 200


# --- Viewer -----------------------------------------------------------------------------------------------------

def test_viewer_computed_once_per_request_and_cached_on_request_user():
    """FR-606: `viewer(user)` считается один раз на объект запроса и хранится в `user._feed_viewer`; новый объект
    сотрудника считает заново."""
    from apps.feed.services import visibility

    unit = org.make_unit("Отдел ИТ")
    user = _member(unit)
    with ff.capture_sql() as first:
        viewer = visibility.viewer(user)
    assert first, "первый вызов обращается к базе (цепочка узлов)"
    assert user._feed_viewer is viewer
    with ff.capture_sql() as second:
        again = visibility.viewer(user)
    assert again is viewer
    assert list(second) == []
    assert not hasattr(_fresh(user), "_feed_viewer")


def test_viewer_chain_is_member_units_and_ancestors_from_org_unit_chain_ids():
    """FR-605: `Viewer.chain` — узлы сотрудника и их предки, включая корень (`unit_chain_ids`); поля `Viewer`
    названы по контракту."""
    from apps.feed.services import visibility
    from apps.org.services import structure

    tree = org.make_tree({"Отдел ИТ": {"Группа сети": {}}, "Бухгалтерия": {}})
    user = _member(tree["Группа сети"])
    org.make_member(user, tree["Бухгалтерия"])   # совместительство

    viewer = visibility.viewer(user)
    expected = {org.root_unit().pk, tree["Отдел ИТ"].pk, tree["Группа сети"].pk, tree["Бухгалтерия"].pk}
    assert isinstance(viewer.chain, frozenset)
    assert viewer.chain == structure.unit_chain_ids(user) == expected
    assert viewer._fields == ("id", "chain", "moderator", "post_all", "link_staff")
    assert viewer.id == user.pk
    assert viewer.moderator is False and viewer.post_all is False
    assert visibility.viewer(ff.as_moderator().user).moderator is True
    assert visibility.viewer(ff.as_writer().user).post_all is True


def test_without_org_chain_is_empty_and_unit_recipients_grant_nothing():
    """FR-605: без модуля `org` цепочка пуста, строки подразделений ничего не дают; люди и автор видят."""
    from apps.feed.services import visibility

    unit = org.make_unit("Отдел ИТ")
    member = _member(unit)
    person = _employee("Адресат Личный")
    author = _employee("Автор Авторов")
    post = ff.make_post(author, to=[unit, person])
    assert post.pk in _visible_ids(member)

    with ff.without_org():
        assert visibility.viewer(_fresh(member)).chain == frozenset()
        assert post.pk not in _visible_ids(member)
        assert post.pk in _visible_ids(person)
        assert post.pk in _visible_ids(author)
        assert visibility.audience(post) == frozenset({person.pk, author.pk})


def test_visible_posts_passes_chain_as_array_parameter_without_unit_ids_in_sql_text():
    """FR-606: цепочка узлов — параметром-массивом (`= ANY(%s)`), номера узлов в тексте SQL не стоят."""
    from apps.feed.services import visibility

    tree = org.make_tree({"Отдел ИТ": {"Группа сети": {}}})
    user = _member(tree["Группа сети"])
    ff.make_post(_employee("Автор Авторов"), to=[tree["Группа сети"]])
    chain = set(support.model("org.Unit").objects.filter(pk__in=[
        org.root_unit().pk, tree["Отдел ИТ"].pk, tree["Группа сети"].pk]).values_list("pk", flat=True))

    with ff.queries_with_params() as pairs:
        list(visibility.visible_posts(_fresh(user)))

    selects = [(sql, params) for sql, params in pairs if "feed_recipient" in sql]
    assert selects, "видимость читает feed_recipient одним запросом"
    for sql, params in selects:
        assert "ANY(" in sql.upper().replace(" (", "(")
        assert any(isinstance(p, (list, tuple, set, frozenset)) and set(p) == chain for p in params)
        for unit_id in chain:
            assert not re.search(rf"(?<![\w.]){unit_id}(?![\w])", sql), f"номер узла {unit_id} стоит в тексте SQL"


# --- get_post, can_see, audience -----------------------------------------------------------------------------------

def test_get_post_raises_same_http404_for_invisible_and_missing_post():
    """FR-606: `get_post` — запись или `Http404`, одинаково для невидимой и несуществующей."""
    from apps.feed.services import visibility

    author, outsider = _employee("Автор Авторов"), _employee("Посторонний Лиц")
    post = ff.make_post(author, to=[_employee("Адресат Личный")])
    assert visibility.get_post(author, post.pk).pk == post.pk
    with pytest.raises(Http404) as invisible:
        visibility.get_post(outsider, post.pk)
    with pytest.raises(Http404) as missing:
        visibility.get_post(outsider, 999999)
    assert type(invisible.value) is type(missing.value)
    assert str(invisible.value) == str(missing.value)


def test_can_see_agrees_with_visible_posts_for_viewer_and_non_viewer():
    """FR-606: `can_see(user_id, post_id)` совпадает с `visible_posts` для видящего и не видящего; несуществующий
    номер — `False`."""
    from apps.feed.services import visibility

    author, addressee, outsider = _employee("Автор Авторов"), _employee("Адресат Личный"), _employee("Посторонний Лиц")
    post = ff.make_post(author, to=[addressee])
    for user in (author, addressee, outsider):
        assert visibility.can_see(user.pk, post.pk) is (post.pk in _visible_ids(user))
    assert visibility.can_see(addressee.pk, post.pk) is True
    assert visibility.can_see(outsider.pk, post.pk) is False
    assert visibility.can_see(author.pk, 999999) is False


def test_audience_to_all_is_every_active_employee_and_author_without_dismissed_or_blocked():
    """FR-605: аудитория «Всем» — все с `state` не `blocked` и не `dismissed`, и автор; уволенных и заблокированных нет."""
    from apps.feed.services import visibility

    author, active = _employee("Автор Авторов"), _employee("Действующий Тестов")
    dismissed = _employee("Уволенный Тестов", state="dismissed")
    blocked = _employee("Заблокированный Тестов", state="blocked")
    post = ff.make_post(author, to=["all"])
    audience = visibility.audience(post)
    assert isinstance(audience, frozenset)
    assert {author.pk, active.pk} <= audience
    assert dismissed.pk not in audience and blocked.pk not in audience
    everyone_active = set(support.model("core.User").objects.exclude(
        state__in=("blocked", "dismissed")).values_list("pk", flat=True))
    assert audience == everyone_active | {author.pk}


def test_audience_unions_subtree_members_person_recipients_and_author_then_drops_inactive():
    """FR-605: аудитория — участники узла и вложенных (основная работа и совместительство), люди из строк, автор;
    затем отбрасываются уволенные и заблокированные."""
    from apps.feed.services import visibility

    tree = org.make_tree({"Отдел ИТ": {"Группа сети": {}}, "Бухгалтерия": {}})
    it, net = tree["Отдел ИТ"], tree["Группа сети"]
    in_unit = _member(it, "Участник Отдела")
    in_nested = _member(net, "Участник Группы")
    part_timer = _member(tree["Бухгалтерия"], "Совместитель Тестов")
    org.make_member(part_timer, net)
    dismissed_member = _member(net, "Уволенный Участник", state="dismissed")
    blocked_member = _member(it, "Заблокированный Участник", state="blocked")
    person = _employee("Адресат Личный")
    dismissed_person = _employee("Уволенный Адресат", state="dismissed")
    outsider = _employee("Посторонний Лиц")
    author = _employee("Автор Авторов")

    post = ff.make_post(author, to=[it, person, dismissed_person])

    assert visibility.audience(post) == frozenset(
        {in_unit.pk, in_nested.pk, part_timer.pk, person.pk, author.pk})
    assert outsider.pk not in visibility.audience(post)
    assert dismissed_member.pk not in visibility.audience(post)
    assert blocked_member.pk not in visibility.audience(post)
    assert dismissed_person.pk not in visibility.audience(post)


@pytest.mark.parametrize("state", ["dismissed", "blocked"])
def test_dismissed_or_blocked_viewer_gets_no_posts_from_visible_posts(state):
    """FR-605, FR-606: недействующий сотрудник — пустой набор, даже со своей записью и «Всем»."""
    from apps.feed.services import visibility

    inactive = _employee("Недействующий Тестов", state=state)
    other = _employee("Автор Авторов")
    own = ff.make_post(inactive, to=[other])
    for_all = ff.make_post(other, to=["all"])
    direct = ff.make_post(other, to=[inactive])
    assert list(visibility.visible_posts(inactive)) == []
    assert not {own.pk, for_all.pk, direct.pk} & _visible_ids(inactive)
    assert visibility.can_see(inactive.pk, for_all.pk) is False


# --- права действий ----------------------------------------------------------------------------------------------

def test_can_edit_post_only_author_not_moderator_or_addressee():
    """FR-603, FR-620: править запись может только автор, не модератор и не адресат."""
    from apps.feed.services import visibility

    author, addressee = _employee("Автор Авторов"), _employee("Адресат Личный")
    moderator = ff.as_moderator().user
    outsider = _employee("Посторонний Лиц")
    post = ff.make_post(author, to=[addressee, moderator])
    assert visibility.can_edit(_fresh(author), post) is True
    assert visibility.can_edit(_fresh(addressee), post) is False
    assert visibility.can_edit(_fresh(moderator), post) is False   # модератор видит, но не правит
    assert visibility.can_edit(_fresh(outsider), post) is False
    assert _session(addressee).client.get(f"/feed/{post.pk}/edit/").status_code == 403


def test_can_delete_post_author_or_moderator_who_sees_not_moderator_who_does_not():
    """FR-603, FR-606, FR-621: удалить запись — автор или модератор, который её видит; модератор без доступа и
    адресат не могут."""
    from apps.feed.services import visibility

    author, addressee = _employee("Автор Авторов"), _employee("Адресат Личный")
    seeing_moderator = ff.as_moderator().user
    blind_moderator = ff.as_moderator().user
    post = ff.make_post(author, to=[addressee, seeing_moderator])
    assert visibility.can_delete(_fresh(author), post) is True
    assert visibility.can_delete(_fresh(seeing_moderator), post) is True
    assert visibility.can_delete(_fresh(blind_moderator), post) is False
    assert visibility.can_delete(_fresh(addressee), post) is False
    moderator_author = ff.as_moderator().user
    own = ff.make_post(moderator_author, to=[addressee])
    assert visibility.can_delete(_fresh(moderator_author), own) is True
    assert _session(addressee).client.post(f"/feed/{post.pk}/delete/").status_code == 403
    assert support.model("feed.Post").objects.filter(pk=post.pk).exists()


def test_comment_edit_by_its_author_only_delete_by_author_or_moderator_who_sees():
    """FR-603, FR-606, FR-622: править комментарий — только его автор; удалить — автор или модератор, который видит
    запись; автор записи чужие комментарии не удаляет."""
    from apps.feed.services import visibility

    author, commenter = _employee("Автор Авторов"), _employee("Комментатор Тестов")
    seeing_moderator = ff.as_moderator().user
    blind_moderator = ff.as_moderator().user
    post = ff.make_post(author, to=[commenter, seeing_moderator])
    note = ff.comment(post, commenter, "Мой комментарий")

    assert visibility.can_edit_comment(_fresh(commenter), note) is True
    assert visibility.can_edit_comment(_fresh(author), note) is False
    assert visibility.can_edit_comment(_fresh(seeing_moderator), note) is False

    assert visibility.can_delete_comment(_fresh(commenter), post, note) is True
    assert visibility.can_delete_comment(_fresh(seeing_moderator), post, note) is True
    assert visibility.can_delete_comment(_fresh(author), post, note) is False
    assert visibility.can_delete_comment(_fresh(blind_moderator), post, note) is False

    author_session = _session(author)
    assert author_session.client.post(f"/feed/comments/{note.pk}/edit/", {"text": "Чужая правка"}).status_code == 403
    assert author_session.client.post(f"/feed/comments/{note.pk}/delete/").status_code == 403
    assert support.model("core.Comment").objects.filter(pk=note.pk, text="Мой комментарий").exists()


def test_comment_like_and_answer_allowed_to_every_viewer_and_denied_to_non_viewer():
    """FR-606: комментировать, отмечать, отвечать на событие может каждый, кто видит запись (кроме автора события —
    у него отказ по FR-617, здесь не проверяется); не видящему — 404."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.feed.services import visibility

    author, viewer, outsider = _employee("Автор Авторов"), _session(_employee("Адресат Личный")), \
        _session(_employee("Посторонний Лиц"))
    start = timezone.now() + timedelta(hours=3)
    event = ff.make_event(author, start=start, to=[viewer.user])
    note = ff.comment(event, author, "Комментарий автора")

    assert visibility.can_comment(_fresh(viewer.user), event) is True
    assert visibility.can_comment(_fresh(outsider.user), event) is False

    allowed = [viewer.client.post(f"/feed/{event.pk}/comments/", {"text": "Ответ видящего"}),
               viewer.client.post(f"/feed/{event.pk}/like/"),
               viewer.client.post(f"/feed/comments/{note.pk}/like/"),
               viewer.client.post(f"/feed/{event.pk}/answer/", {"answer": "go"})]
    assert [r.status_code for r in allowed] == [r.status_code for r in allowed if r.status_code in (200, 302)]
    denied = [outsider.client.post(f"/feed/{event.pk}/comments/", {"text": "Чужой комментарий"}),
              outsider.client.post(f"/feed/{event.pk}/like/"),
              outsider.client.post(f"/feed/comments/{note.pk}/like/"),
              outsider.client.post(f"/feed/{event.pk}/answer/", {"answer": "go"})]
    assert [r.status_code for r in denied] == [404, 404, 404, 404]
