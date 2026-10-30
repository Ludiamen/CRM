"""T-7132: журнал ленты (FR-639, NFR-607). Сценарии 4 (удаление модератором), 12 (срок хранения) и 13 (права)
спеки среза 007.

Контракт: CONTRACT-007 — 8.1 (коды, типы объектов, ключи «было / стало»), 8.2 (подписи), 3.3 (точка `audit_labels`),
10.2 (адреса действий), 5.4–5.5 (службы настройки и срока хранения). Действия совершаются настоящими службами и
адресами: модератор удаляет чужое по `/feed/<id>/delete/` и `/feed/comments/<cid>/delete/`, срок хранения меняет
`feed_settings.save`, ночное задание — `support_feed.run_retention(now)`. Время в журнале — строка по Москве
«ДД.ММ.ГГГГ ЧЧ:ММ», номера — целые JSON, ФИО — строка (решение контракта К27). Код среза импортируется внутри функций.
"""
import json
import re
from datetime import timedelta

import pytest
from django.db import ProgrammingError, connection, transaction
from django.utils import timezone

from tests import support
from tests import support_feed as fd
from tests.support import model

pytestmark = pytest.mark.django_db

CODES = ("feed.post_deleted", "feed.comment_deleted", "feed.retention_changed", "feed.retention_purged")
OBJECT_TYPE_OF_ACTION = {
    "feed.post_deleted": "feed.post",
    "feed.comment_deleted": "feed.comment",
    "feed.retention_changed": "feed.settings",
    "feed.retention_purged": "feed.settings",
}
# допустимые ключи «было / стало» по действиям (раздел 8.1)
ALLOWED_BY_ACTION = {
    "feed.post_deleted": {"author", "published_at"},
    "feed.comment_deleted": {"author", "created_at", "post"},
    "feed.retention_changed": {"years"},
    "feed.retention_purged": {"posts"},
}
ALL_KEYS = {"author", "published_at", "created_at", "post", "years", "posts"}
ACTION_TITLES = {
    "feed.post_deleted": "Чужая запись ленты удалена",
    "feed.comment_deleted": "Чужой комментарий ленты удалён",
    "feed.retention_changed": "Срок хранения ленты изменён",
    "feed.retention_purged": "Записи ленты удалены по сроку",
}
OBJECT_TITLES = {"feed.post": "запись ленты", "feed.comment": "комментарий ленты", "feed.settings": "настройки ленты"}
FIELD_TITLES = {
    "author": "автор", "published_at": "опубликовано", "created_at": "написано", "post": "номер записи",
    "years": "срок хранения, лет", "posts": "Удалено по сроку, записей",
}

# метки текста, названия и места: в журнал попасть не должны
TEXT_MARK = "Текст-метка-журнала-1"
COMMENT_MARK = "Комментарий-метка-журнала-2"
TITLE_MARK = "Название-метка-журнала-3"
PLACE_MARK = "Место-метка-журнала-4"

# моменты — от настоящего времени, чтобы срок хранения не удалил данные теста с годами; до минуты (формат журнала)
PUBLISHED = (timezone.now() - timedelta(days=20)).replace(second=0, microsecond=0)
WRITTEN = PUBLISHED + timedelta(hours=18, minutes=35)


def _events(*actions: str) -> list:
    return list(model("core.AuditEvent").objects.filter(action__in=actions or CODES).order_by("id"))


def _feed_events() -> list:
    return list(model("core.AuditEvent").objects.filter(action__startswith="feed.").order_by("id"))


def _admin():
    return support.make_with_permissions("settings.portal", full_name="Администратор Настройки")


def _set_years(years: int) -> None:
    model("feed.FeedSettings").objects.update_or_create(pk=1, defaults={"retention_years": years})


def _delete_post(session, post) -> None:
    response = session.client.post(f"/feed/{post.pk}/delete/")
    assert response.status_code == 302
    assert not model("feed.Post").objects.filter(pk=post.pk).exists()


def _delete_comment(session, comment) -> None:
    response = session.client.post(f"/feed/comments/{comment.pk}/delete/")
    assert response.status_code == 302
    assert not model("core.Comment").objects.filter(pk=comment.pk).exists()


def _everything() -> dict:
    """Совершает все четыре действия настоящими службами и адресами; возвращает участников и объекты."""
    from apps.feed.services import feed_settings

    author = support.make_employee(full_name="Автор Записи")
    commenter = support.make_employee(full_name="Автор Комментария")
    moderator = fd.as_moderator(full_name="Модератор Ленты")
    post = fd.make_event(author, start=timezone.now() + timedelta(days=5), title=TITLE_MARK, place=PLACE_MARK,
                         to=("all",), text=TEXT_MARK, published_at=PUBLISHED)
    other = fd.make_post(author, to=("all",), text=TEXT_MARK, published_at=PUBLISHED)
    comment = fd.comment(other, commenter, COMMENT_MARK, created_at=WRITTEN)
    _delete_post(moderator, post)
    _delete_comment(moderator, comment)

    admin = _admin()
    _set_years(3)
    feed_settings.save(admin, 1, confirmed=True)

    now = timezone.now()
    old = [fd.make_post(author, to=("all",), text=TEXT_MARK, published_at=now - timedelta(days=4 * 366))
           for _ in range(2)]
    assert fd.run_retention(now) == len(old)
    return {"author": author, "commenter": commenter, "moderator": moderator, "post": post, "other": other,
            "comment": comment, "admin": admin}


# --- удаление модератором -----------------------------------------------------------------------------------

def test_moderator_deleting_others_post_writes_post_deleted_with_actor_author_and_published_at_without_text():
    """FR-639: модератор удалил чужую запись — одна запись журнала `feed.post_deleted`: объект `feed.post` и номер
    записи, действующий — модератор; в `before` — ФИО автора и время публикации по Москве; текста нет."""
    author = support.make_employee(full_name="Автор Записи")
    moderator = fd.as_moderator()
    post = fd.make_post(author, to=("all",), text=TEXT_MARK, published_at=PUBLISHED)
    _delete_post(moderator, post)
    events = _events("feed.post_deleted")
    assert len(events) == 1
    event = events[0]
    assert (event.object_type, event.object_id) == ("feed.post", str(post.pk))
    assert event.actor_id == moderator.user.pk
    assert event.before == {"author": "Автор Записи", "published_at": fd.moscow_text(PUBLISHED)}
    assert re.fullmatch(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}", event.before["published_at"])
    assert event.after == {}
    assert TEXT_MARK not in json.dumps([event.before, event.after], ensure_ascii=False)


def test_moderator_deleting_others_comment_writes_comment_deleted_with_actor_author_time_and_post_id_without_text():
    """FR-639: модератор удалил чужой комментарий — одна запись `feed.comment_deleted`: объект `feed.comment` и номер
    комментария, действующий — модератор; в `before` — ФИО автора комментария, время комментария по Москве и номер
    записи (целое); текста комментария нет; запись остаётся."""
    author = support.make_employee(full_name="Автор Записи")
    commenter = support.make_employee(full_name="Автор Комментария")
    moderator = fd.as_moderator()
    post = fd.make_post(author, to=("all",), published_at=PUBLISHED)
    comment = fd.comment(post, commenter, COMMENT_MARK, created_at=WRITTEN)
    _delete_comment(moderator, comment)
    assert model("feed.Post").objects.filter(pk=post.pk).exists()
    events = _events("feed.comment_deleted")
    assert len(events) == 1
    event = events[0]
    assert (event.object_type, event.object_id) == ("feed.comment", str(comment.pk))
    assert event.actor_id == moderator.user.pk
    assert event.before == {"author": "Автор Комментария", "created_at": fd.moscow_text(WRITTEN), "post": post.pk}
    assert re.fullmatch(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}", event.before["created_at"])
    assert isinstance(event.before["post"], int)
    assert event.after == {}
    assert COMMENT_MARK not in json.dumps([event.before, event.after], ensure_ascii=False)
    assert _events("feed.post_deleted") == []


def test_author_editing_and_deleting_own_comment_writes_no_audit_even_if_author_is_moderator():
    """FR-639: автор правит и удаляет свой комментарий — журнал не пишется, даже если он модератор."""
    author = support.make_employee()
    moderator = fd.as_moderator()
    post = fd.make_post(author, to=("all",), published_at=PUBLISHED)
    comment = fd.comment(post, moderator.user, "Свой комментарий модератора")
    before = _feed_events()
    response = moderator.client.post(f"/feed/comments/{comment.pk}/edit/", {"text": "Исправленный комментарий"})
    assert response.status_code == 302
    assert model("core.Comment").objects.get(pk=comment.pk).text == "Исправленный комментарий"
    _delete_comment(moderator, comment)
    assert _feed_events() == before


def test_author_deleting_own_post_writes_no_audit_even_if_author_is_moderator():
    """FR-639: автор удаляет свою запись — журнал не пишется, даже если он модератор."""
    moderator = fd.as_moderator()
    post = fd.make_post(moderator.user, to=("all",), published_at=PUBLISHED)
    before = _feed_events()
    _delete_post(moderator, post)
    assert _feed_events() == before


# --- срок хранения ------------------------------------------------------------------------------------------

def test_retention_change_writes_retention_changed_on_feed_settings_with_years_before_after():
    """FR-639: изменение срока хранения — запись `feed.retention_changed` на `feed.settings` с номером «1»; в `before`
    и `after` — только `years` (было и стало); действующий — администратор; уменьшение и увеличение пишутся оба."""
    from apps.feed.services import feed_settings

    _set_years(3)
    admin = _admin()
    feed_settings.save(admin, 1, confirmed=True)
    feed_settings.save(admin, 5)
    events = _events("feed.retention_changed")
    assert len(events) == 2
    for event in events:
        assert (event.object_type, event.object_id) == ("feed.settings", "1")
        assert event.actor_id == admin.pk
    assert (events[0].before, events[0].after) == ({"years": 3}, {"years": 1})
    assert (events[1].before, events[1].after) == ({"years": 1}, {"years": 5})
    assert isinstance(events[0].before["years"], int)


def test_retention_purge_writes_one_retention_purged_with_posts_count_per_run():
    """FR-639: ночное задание, удалившее записи, пишет ровно одну запись `feed.retention_purged` за запуск: объект
    `feed.settings`/«1», действующего нет, `after` — `{"posts": N}` по числу записей (комментарии в N не входят)."""
    _set_years(3)
    author, reader = support.make_employee(), support.make_employee()
    now = timezone.now()
    old = [fd.make_post(author, to=[reader], published_at=now - timedelta(days=4 * 366)) for _ in range(3)]
    for post in old:
        fd.comment(post, reader, created_at=now - timedelta(days=4 * 366))
    fresh = fd.make_post(author, to=[reader], published_at=now - timedelta(days=30))
    assert fd.run_retention(now) == 3
    events = _events("feed.retention_purged")
    assert len(events) == 1
    event = events[0]
    assert (event.object_type, event.object_id) == ("feed.settings", "1")
    assert event.actor_id is None
    assert event.after == {"posts": 3}
    assert event.before == {}
    assert model("feed.Post").objects.filter(pk=fresh.pk).exists()


def test_retention_run_that_deletes_nothing_writes_no_retention_purged():
    """FR-639: запуск, ничего не удаливший (свежие записи; повтор после удаления), в журнал не пишет."""
    _set_years(3)
    author = support.make_employee()
    now = timezone.now()
    fd.make_post(author, to=("all",), published_at=now - timedelta(days=10))
    assert fd.run_retention(now) == 0
    assert _events("feed.retention_purged") == []
    fd.make_post(author, to=("all",), published_at=now - timedelta(days=4 * 366))
    assert fd.run_retention(now) == 1
    assert len(_events("feed.retention_purged")) == 1
    assert fd.run_retention(now) == 0
    assert len(_events("feed.retention_purged")) == 1, "повторный запуск дописал журнал"


# --- состав записей -----------------------------------------------------------------------------------------

def test_audit_object_types_are_feed_post_feed_comment_and_feed_settings():
    """FR-639: после всех четырёх действий тип объекта каждой записи — `feed.post`, `feed.comment` или `feed.settings`
    и соответствует действию (раздел 8.1); `object_id` — число в виде строки."""
    _everything()
    events = _events()
    assert {event.action for event in events} == set(CODES), "не все четыре действия записаны"
    for event in events:
        assert event.object_type == OBJECT_TYPE_OF_ACTION[event.action], event.action
        assert event.object_id.isdigit(), (event.action, event.object_id)
    assert {event.object_type for event in events} == set(OBJECT_TITLES)


def test_audit_before_after_keys_are_only_those_of_plan_table_for_four_codes():
    """FR-639, NFR-607: ключи `before` и `after` — только из набора своего действия (раздел 8.1), вместе — ровно шесть
    ключей `author`, `published_at`, `created_at`, `post`, `years`, `posts`; ядро не скрыло значения (`***`)."""
    _everything()
    events = _events()
    assert {event.action for event in events} == set(CODES), "не все четыре действия записаны"
    seen: set = set()
    for event in events:
        for side in (event.before, event.after):
            seen |= set(side)
            assert set(side) <= ALLOWED_BY_ACTION[event.action], (event.action, sorted(side))
            assert "***" not in side.values(), event.action
    assert seen == ALL_KEYS, seen


def test_audit_records_of_feed_have_no_post_or_comment_text_title_or_place():
    """FR-639, NFR-607: в записях журнала ленты нет текста записи и комментария, названия и места события и нет
    ключей `text`, `title`, `place`, `event_title`, `event_place`."""
    _everything()
    events = _feed_events()
    assert len(events) >= len(CODES)
    dump = json.dumps([[event.object_type, event.object_id, event.before, event.after] for event in events],
                      ensure_ascii=False)
    for marker in (TEXT_MARK, COMMENT_MARK, TITLE_MARK, PLACE_MARK):
        assert marker not in dump, marker
    for event in events:
        for side in (event.before, event.after):
            assert not set(side) & {"text", "title", "place", "event_title", "event_place", "comment", "files"}, \
                event.action


def test_publish_edit_comment_like_read_and_answer_write_no_audit():
    """FR-639: публикация, правка, комментарий, «Нравится», «Прочитано» и ответ на событие в журнал ленты не пишут."""
    writer = fd.as_writer()
    reader = fd.as_plain()
    before = _feed_events()
    start = fd.moscow_text(timezone.now() + timedelta(days=3))
    end = fd.moscow_text(timezone.now() + timedelta(days=3, hours=2))
    Post = model("feed.Post")

    assert writer.client.post("/feed/posts/", {"kind": "post", "text": "Обычная запись", "to": ["all"]}) \
        .status_code == 302
    plain = Post.objects.get(kind="post")
    assert writer.client.post("/feed/posts/", {"kind": "important", "text": "Важная запись", "to": ["all"],
                                               "term": "day"}).status_code == 302
    important = Post.objects.get(kind="important")
    assert writer.client.post("/feed/posts/", {"kind": "event", "text": "Событие", "to": ["all"], "event_title": "Сбор",
                                               "event_place": "Зал", "event_start": start, "event_end": end}) \
        .status_code == 302
    event = Post.objects.get(kind="event")

    assert writer.client.post(f"/feed/{plain.pk}/edit/", {"text": "Исправленная запись", "to": ["all"]}) \
        .status_code == 302
    assert Post.objects.get(pk=plain.pk).edited_at is not None
    assert reader.client.post(f"/feed/{plain.pk}/comments/", {"text": "Ответ читателя"}).status_code == 302
    assert model("feed.FeedComment").objects.filter(post=plain).count() == 1
    assert reader.client.post(f"/feed/{plain.pk}/like/").status_code == 302
    assert model("feed.PostLike").objects.filter(post=plain).count() == 1
    assert reader.client.post(f"/feed/{important.pk}/read/").status_code == 302
    assert model("feed.ReadMark").objects.filter(post=important).count() == 1
    assert reader.client.post(f"/feed/{event.pk}/answer/", {"answer": "go"}).status_code == 302
    assert model("feed.EventAnswer").objects.filter(post=event).count() == 1

    assert _feed_events() == before


# --- подписи ------------------------------------------------------------------------------------------------

def _written_names(events) -> set:
    names: set = set()
    for event in events:
        names |= set(event.before) | set(event.after)
    return names


def test_audit_labels_cover_every_feed_action_object_type_and_written_key():
    """FR-639: точка `audit_labels` даёт подписи четырёх действий, трёх видов объекта и шести ключей раздела 8.2;
    словарь значений пуст; ядро после слияния отдаёт те же слова; у каждого записанного настоящими действиями ключа
    подпись есть."""
    from apps.core.services import audit_labels as core_labels
    from apps.core.services import audit_search
    from apps.feed import audit_labels as own

    data = own.audit_labels()
    assert set(data) == {"actions", "fields", "object_types", "values"}
    assert data["actions"] == ACTION_TITLES
    assert data["object_types"] == OBJECT_TITLES
    assert {name: data["fields"].get(name) for name in FIELD_TITLES} == FIELD_TITLES
    assert data["values"] == {}
    cyrillic = re.compile("[а-яА-ЯёЁ]")
    for title in list(data["actions"].values()) + list(data["fields"].values()) + list(data["object_types"].values()):
        assert cyrillic.search(title), title

    titles = dict(audit_search.known_actions())
    for action, title in ACTION_TITLES.items():
        assert titles.get(action) == title, action
    for kind, title in OBJECT_TITLES.items():
        assert core_labels.object_title(kind) == title, kind
    for name, title in FIELD_TITLES.items():
        assert core_labels.label(name) == title, name

    _everything()
    written = _written_names(_events())
    assert written == ALL_KEYS
    for name in written:
        assert data["fields"].get(name), f"нет подписи ключа {name}"
        assert core_labels.label(name) == data["fields"][name], name


def test_audit_label_of_posts_key_is_deleted_by_retention_posts_count():
    """FR-639: подпись ключа `posts` — дословно «Удалено по сроку, записей» (сценарий 12 п. 4): в словаре среза, в
    ядре после слияния и при показе записи журнала `feed.retention_purged`."""
    from apps.core.services import audit_labels as core_labels
    from apps.core.templatetags.portal import pairs
    from apps.feed import audit_labels as own

    assert own.audit_labels()["fields"]["posts"] == "Удалено по сроку, записей"
    assert core_labels.label("posts") == "Удалено по сроку, записей"
    _set_years(3)
    now = timezone.now()
    fd.make_post(support.make_employee(), to=("all",), published_at=now - timedelta(days=4 * 366))
    assert fd.run_retention(now) == 1
    event = _events("feed.retention_purged")[0]
    shown = pairs(event.after)
    assert shown and shown[0][0] == "Удалено по сроку, записей"


# --- права в ролях и неизменяемость -------------------------------------------------------------------------

def test_changing_post_all_and_moderate_in_role_writes_role_updated_with_rights_before_after():
    """FR-639: смена прав «Писать всем» и «Модерировать ленту» в роли пишет прежний журнал ролей ядра — `role.updated`
    со списком прав «было / стало»; права показываются названиями."""
    from apps.core.services import roles
    from apps.core.templatetags.portal import pairs
    from tests import factories

    role = factories.make_role(name="Роль для журнала ленты", permissions=("feed.post_all",))
    admin = support.make_admin()
    roles.update_role(role, role.name, ["feed.moderate"], actor=admin)
    roles.update_role(role, role.name, ["feed.moderate", "feed.post_all"], actor=admin)
    events = list(model("core.AuditEvent").objects.filter(action="role.updated", object_id=str(role.pk)).order_by("id"))
    assert len(events) == 2
    assert all(event.object_type == "role" and event.actor_id == admin.pk for event in events)
    assert events[0].before["permissions"] == ["feed.post_all"]
    assert events[0].after["permissions"] == ["feed.moderate"]
    assert events[1].before["permissions"] == ["feed.moderate"]
    assert events[1].after["permissions"] == ["feed.moderate", "feed.post_all"]
    assert pairs({"permissions": ["feed.post_all"]})[0][1] == "Писать всем"
    assert pairs({"permissions": ["feed.moderate"]})[0][1] == "Модерировать ленту"


def test_app_role_cannot_update_or_delete_feed_audit_rows():
    """NFR-607: у роли приложения нет UPDATE, DELETE, TRUNCATE на журнал; правка и удаление записей `feed.*`
    отвергаются базой, строки остаются прежними (тот же тест, что SPEC-006 NFR-508)."""
    Event = model("core.AuditEvent")
    _everything()
    ids = sorted(event.pk for event in _events())
    assert ids
    columns = ("id", "action", "object_type", "object_id", "before", "after", "actor_id")
    snapshot = list(Event.objects.filter(id__in=ids).order_by("id").values_list(*columns))
    codes = list(CODES)

    with connection.cursor() as cur:
        cur.execute("SELECT has_table_privilege('crm_app', 'core_auditevent', 'UPDATE'), "
                    "has_table_privilege('crm_app', 'core_auditevent', 'DELETE'), "
                    "has_table_privilege('crm_app', 'core_auditevent', 'TRUNCATE')")
        assert cur.fetchone() == (False, False, False)
    with pytest.raises(ProgrammingError), transaction.atomic():
        Event.objects.filter(action__in=codes).update(action="tampered")
    with pytest.raises(ProgrammingError), transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("DELETE FROM core_auditevent WHERE action = ANY(%s)", [codes])
    assert list(Event.objects.filter(id__in=ids).order_by("id").values_list(*columns)) == snapshot
