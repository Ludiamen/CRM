"""T-7127: уведомления ленты — кто что получает, приоритет (FR-611, FR-619, FR-629, FR-630). Сценарии 3, 5, 6, 7, 9
спеки среза 007.

План: «Уведомления» (кто что получает, одно событие — одно уведомление, ссылки и `object_ref`), «Правка и удаление»
(новым адресатам); CONTRACT-007: 2.2, 4.2, 5.3, 5.5 (`notify_rules.RuleEvent`, `notify_rules.decide`, `PRIORITY`),
5.8 («Создание уведомлений», «Правило приоритета напрямую»), 7.2, решения 47 и 51 задач. Действия идут службами среза
(`posts.publish`, `posts.edit`, `comments.add`, `likes.toggle_*`), результат читается из `notify.Notification`. Код
среза на уровне модуля не импортируется: имена берутся внутри тестов (CONTRACT-007, шапка).
"""
import importlib
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from tests import support
from tests import support_feed as fd
from tests import support_org as org
from tests.support import model

pytestmark = pytest.mark.django_db

FOR_YOU, MENTION, COMMENT = "feed.for_you", "feed.mention", "feed.comment"
IMPORTANT, INVITE, CHANGED, LIKE = "feed.important", "feed.invite", "feed.event_changed", "feed.like"
PRIORITY = (MENTION, INVITE, CHANGED, IMPORTANT, FOR_YOU, COMMENT)


# --- помощники только этого файла ---------------------------------------------------------------------------

def _posts():
    return importlib.import_module("apps.feed.services.posts")


def _comments():
    return importlib.import_module("apps.feed.services.comments")


def _likes():
    return importlib.import_module("apps.feed.services.likes")


def _visibility():
    return importlib.import_module("apps.feed.services.visibility")


def _rules():
    return importlib.import_module("apps.feed.services.notify_rules")


def _p(user) -> str:
    return f"p{user.pk}"


def _u(unit) -> str:
    return f"u{unit.pk}"


def _mark(user) -> str:
    return f"@[{user.pk}]"


def _writer(name: str = "Анна Автор") -> fd.Session:
    return fd.as_writer(full_name=name)


def _person(name: str | None = None, **extra):
    if name:
        extra["full_name"] = name
    return support.make_employee(**extra)


def _feed_notes(user=None, kind: str | None = None):
    notes = model("notify.Notification").objects.filter(kind__startswith="feed.")
    if user is not None:
        notes = notes.filter(user=user)
    if kind is not None:
        notes = notes.filter(kind=kind)
    return notes


def _got() -> list:
    """Все уведомления ленты: пары (номер получателя, вид), по возрастанию."""
    return sorted(_feed_notes().values_list("user_id", "kind"))


def _want(*pairs) -> list:
    return sorted((user.pk, code) for user, code in pairs)


def _ids() -> set:
    return set(_feed_notes().values_list("pk", flat=True))


def _new(before: set) -> list:
    """Уведомления ленты, которых не было в `before` (множество номеров): пары (получатель, вид)."""
    return sorted(_feed_notes().exclude(pk__in=before).values_list("user_id", "kind"))


def _future(days: int = 3, hours: int = 0) -> object:
    return (timezone.now() + timedelta(days=days, hours=hours)).replace(second=0, microsecond=0)


def _event(start, end=None, title: str = "Собрание отдела", place: str = "Корпус 1") -> dict:
    end = end or start + timedelta(hours=1)
    return {"event_title": title, "event_place": place, "event_start": fd.moscow_text(start),
            "event_end": fd.moscow_text(end)}


def _publish(author, text: str, *, to, kind: str = "post", **fields):
    """Публикация службой; `author` — `Session`; `to` — значения поля `to` (`all`, `u<id>`, `p<id>`)."""
    data = {"kind": kind, "text": text, "to": list(to), **fields}
    return _posts().publish(author.user, data)


def _publish_event(author, *, to, text: str = "", start=None, **over):
    start = start or _future()
    return _publish(author, text, to=to, kind="event", **_event(start, **over))


def _publish_important(author, text: str, *, to, term: str = "day"):
    return _publish(author, text, to=to, kind="important", term=term)


def _saved_to(post) -> list:
    out = ["all"] if post.to_all else []
    for row in model("feed.Recipient").objects.filter(post=post, via="to").order_by("pk"):
        out.append(f"u{row.unit_id}" if row.kind == "unit" else f"p{row.user_id}")
    return out


def _edit(author, post, *, add_to=(), **over):
    """Правка службой: те же поля, что у записи (текст, сохранённые адресаты, поля события), поверх — `over`."""
    post = model("feed.Post").objects.get(pk=post.pk)
    data = {"text": post.text, "to": _saved_to(post) + list(add_to)}
    if post.kind == "event":
        data.update(event_title=post.event_title, event_place=post.event_place,
                    event_start=fd.moscow_text(post.event_start), event_end=fd.moscow_text(post.event_end))
    data.update(over)
    return _posts().edit(author.user, post.pk, data)


def _note(user, kind: str):
    return _feed_notes(user, kind).get()


# --- публикация (FR-611, FR-629, FR-630) --------------------------------------------------------------------

def test_for_you_with_post_ref_and_card_url_only_to_personal_recipients_not_via_all_or_unit():
    """FR-629: «Запись для вас» — только адресату «Кому» лично; через «Всем» и подразделение не приходит; автору
    уведомления нет; ссылка — карточка записи, `object_ref` — `feed.post:<id>`; текст — «<ФИО>: запись для вас — «…»»."""
    author = _writer("Анна Автор")
    personal, via_unit, other = _person(), _person(), _person()
    unit = org.make_unit("Отдел ИТ")
    org.make_member(via_unit, unit)
    post = _publish(author, "Прошу взглянуть на документ", to=["all", _u(unit), _p(personal)])
    assert _got() == _want((personal, FOR_YOU))
    note = _note(personal, FOR_YOU)
    assert note.url == f"/feed/{post.pk}/"
    assert note.object_ref == f"feed.post:{post.pk}"
    assert note.text == "Анна Автор: запись для вас — «Прошу взглянуть на документ»"
    assert not _feed_notes(via_unit).exists() and not _feed_notes(other).exists()


def test_plain_post_to_all_or_unit_without_mentions_creates_no_notifications():
    """FR-629 (сценарий 9 п. 2): обычная запись «Всем» или подразделению без упоминаний уведомлений не создаёт."""
    author = _writer()
    member, other = _person(), _person()
    unit = org.make_unit("Отдел ИТ")
    org.make_member(member, unit)
    _publish(author, "Всем доброе утро", to=["all"])
    _publish(author, "Отделу — собрание", to=[_u(unit)])
    assert _feed_notes().count() == 0, "ни одного уведомления ленты"
    assert model("notify.Notification").objects.filter(user__in=[member, other]).count() == 0


def test_publish_mentioned_from_other_unit_gets_mention_and_sees_post():
    """FR-611, FR-629: упомянутый сотрудник чужого подразделения получает «Вас упомянули» и видит запись; участник
    подразделения-адресата без упоминания уведомления не получает."""
    author = _writer()
    unit_a, unit_b = org.make_unit("Отдел А"), org.make_unit("Отдел Б")
    mentioned, plain = _person(), _person()
    org.make_member(mentioned, unit_b)
    org.make_member(plain, unit_a)
    post = _publish(author, f"Нужен совет {_mark(mentioned)}", to=[_u(unit_a)])
    assert _got() == _want((mentioned, MENTION))
    assert _visibility().can_see(mentioned.pk, post.pk) is True
    assert _visibility().can_see(plain.pk, post.pk) is True and not _feed_notes(plain).exists()
    note = _note(mentioned, MENTION)
    assert (note.url, note.object_ref) == (f"/feed/{post.pk}/", f"feed.post:{post.pk}")


def test_new_event_participants_get_invite_author_does_not():
    """FR-629, FR-630: участникам нового события — «Приглашение на событие» (лично и через подразделение); автору и
    тому, кто записи не видит, — нет."""
    author = _writer()
    first, second, member, outsider = _person(), _person(), _person(), _person()
    unit = org.make_unit("Отдел ИТ")
    org.make_member(member, unit)
    post = _publish_event(author, to=[_p(first), _p(second), _u(unit)])
    assert _got() == _want((first, INVITE), (second, INVITE), (member, INVITE))
    assert not _feed_notes(author).exists() and not _feed_notes(outsider).exists()
    assert _note(first, INVITE).object_ref == f"feed.post:{post.pk}"


def test_new_important_everyone_seeing_gets_important_author_does_not():
    """FR-629, FR-630: новая важная запись «Всем» — «Важная запись» каждому действующему сотруднику, кроме автора;
    уволенный и заблокированный не получают."""
    author = _writer()
    first, second = _person(), _person()
    dismissed, blocked = _person(state="dismissed"), _person(state="blocked")
    _publish_important(author, "Завтра отключение сети", to=["all"])
    active = model("core.User").objects.filter(state="active").exclude(pk=author.user.pk)
    assert {first.pk, second.pk} <= set(active.values_list("pk", flat=True))
    assert _got() == sorted((user.pk, IMPORTANT) for user in active)
    assert not _feed_notes(author.user).exists()
    assert not _feed_notes(dismissed).exists() and not _feed_notes(blocked).exists()


def test_important_personal_with_mention_gives_single_mention():
    """FR-630 (сценарий 9 п. 6): важная запись лично с упоминанием — одно «Вас упомянули», а не три."""
    author = _writer()
    target = _person()
    _publish_important(author, f"Срочно, {_mark(target)}", to=[_p(target)])
    assert _got() == _want((target, MENTION))
    assert _feed_notes(target).count() == 1


def test_own_like_and_self_mention_give_no_notification():
    """FR-630: своя отметка и упоминание самого себя уведомлений не дают; комментарий автора к своей записи — тоже."""
    author = _writer()
    addressee = _person()
    post = _publish(author, f"Заметка для себя {_mark(author.user)}", to=[_p(addressee)])
    assert _got() == _want((addressee, FOR_YOU))
    written = _comments().add(author.user, post.pk, "Мой комментарий")
    _likes().toggle_post(author.user, post.pk)
    _likes().toggle_comment(author.user, written.pk)
    assert _got() == _want((addressee, FOR_YOU)), "у автора по своим действиям ничего нет"


def test_dismissed_recipient_or_mentioned_gets_nothing():
    """FR-630: уволенному и заблокированному, упомянутым в тексте, уведомления не создаются и адресатами записи они
    не становятся; действующий получает своё."""
    author = _writer()
    dismissed, blocked = _person(state="dismissed"), _person(state="blocked")
    post = _publish_important(author, f"Важно {_mark(dismissed)} {_mark(blocked)}", to=["all"])
    active = model("core.User").objects.filter(state="active").exclude(pk=author.user.pk)
    assert _got() == sorted((user.pk, IMPORTANT) for user in active) and active.exists()
    assert not _feed_notes(dismissed).exists() and not _feed_notes(blocked).exists()
    assert not model("feed.Recipient").objects.filter(post=post, user__in=[dismissed, blocked]).exists()


def test_recipients_only_from_audience_at_event_moment_transferred_commenter_gets_nothing():
    """FR-630: получатели — только из `audience` в момент события: комментатор, переведённый из подразделения-адресата,
    нового комментария не получает; автор записи и видящий — да."""
    author = _writer()
    unit = org.make_unit("Отдел ИТ")
    moved, newcomer = _person(), _person()
    org.make_member(moved, unit)
    org.make_member(newcomer, unit)
    post = _publish(author, "Запись отделу", to=[_u(unit)])
    fd.comment(post, moved, "Ранний комментарий")
    model("org.Membership").objects.filter(user=moved, unit=unit).delete()
    assert _visibility().can_see(moved.pk, post.pk) is False
    _comments().add(newcomer, post.pk, "Новый комментарий")
    assert _got() == _want((author.user, COMMENT))
    assert not _feed_notes(moved).exists()


# --- правка записи (FR-629, FR-630) -------------------------------------------------------------------------

def test_edit_adding_person_to_important_gives_important():
    """FR-629, FR-630: правкой добавлен человек в важную запись — ему «Важная запись»; прежним адресатам и автору — нет."""
    author = _writer()
    first, added = _person(), _person()
    post = _publish_important(author, "Важное объявление", to=[_p(first)])
    before = _ids()
    _edit(author, post, add_to=[_p(added)])
    assert _new(before) == _want((added, IMPORTANT))
    assert _note(added, IMPORTANT).object_ref == f"feed.post:{post.pk}"


def test_edit_adding_person_to_important_with_new_mention_gives_mention_only():
    """FR-629, FR-630: добавленному правкой и упомянутому новым маркером — одно «Вас упомянули», «Важной записи» нет."""
    author = _writer()
    first, added = _person(), _person()
    post = _publish_important(author, "Важное объявление", to=[_p(first)])
    before = _ids()
    _edit(author, post, add_to=[_p(added)], text=f"Важное объявление {_mark(added)}")
    assert _new(before) == _want((added, MENTION))


def test_edit_adding_unit_to_important_notifies_only_newly_seeing():
    """FR-629: добавлено подразделение в важную запись — «Важная запись» только тем, кто раньше её не видел; видевший
    лично и входящий в новое подразделение уведомления не получает."""
    author = _writer()
    seen_before, newcomer = _person(), _person()
    unit = org.make_unit("Отдел ИТ")
    org.make_member(seen_before, unit)
    org.make_member(newcomer, unit)
    other = _person()
    post = _publish_important(author, "Важное объявление", to=[_p(seen_before), _p(other)])
    before = _ids()
    _edit(author, post, add_to=[_u(unit)])
    assert _new(before) == _want((newcomer, IMPORTANT))


def test_edit_event_added_person_gets_invite_mentioned_gets_mention():
    """FR-611, FR-629, FR-630: в событии, правкой добавленному участнику — «Приглашение на событие», упомянутому
    новым маркером — «Вас упомянули»; прежний участник и автор — ничего."""
    author = _writer()
    old, invited, mentioned = _person(), _person(), _person()
    post = _publish_event(author, to=[_p(old)])
    before = _ids()
    _edit(author, post, add_to=[_p(invited), _p(mentioned)], text=f"Подробности {_mark(mentioned)}")
    assert _new(before) == _want((invited, INVITE), (mentioned, MENTION))


def test_edit_message_added_personally_gets_for_you_added_via_unit_or_all_gets_nothing():
    """FR-629: у обычной записи добавленному лично — «Запись для вас»; добавленному подразделением или через «Всем» —
    уведомления нет (буква FR-629)."""
    author = _writer()
    first_unit, second_unit = org.make_unit("Отдел А"), org.make_unit("Отдел Б")
    old_member, new_member, personal = _person(), _person(), _person()
    org.make_member(old_member, first_unit)
    org.make_member(new_member, second_unit)
    post = _publish(author, "Запись отделу", to=[_u(first_unit)])
    before = _ids()
    _edit(author, post, add_to=[_p(personal)])
    assert _new(before) == _want((personal, FOR_YOU))
    before = _ids()
    _edit(author, post, add_to=[_u(second_unit)])
    assert _new(before) == [], "добавленный подразделением — без уведомления"
    before = _ids()
    _edit(author, post, add_to=["all"])
    assert _new(before) == [], "добавленные через «Всем» — без уведомлений"


def test_edit_new_mention_marker_gives_mention_already_mentioned_gets_nothing():
    """FR-611, FR-629: новый маркер при правке — «Вас упомянули»; ранее упомянутый тем же маркером повторно ничего не
    получает."""
    author = _writer()
    addressee, early, late = _person(), _person(), _person()
    post = _publish(author, f"Смотрите {_mark(early)}", to=[_p(addressee)])
    assert _got() == sorted([(addressee.pk, FOR_YOU), (early.pk, MENTION)])
    before = _ids()
    _edit(author, post, text=f"Смотрите {_mark(early)} и {_mark(late)}")
    assert _new(before) == _want((late, MENTION))


# --- правка события (FR-619, FR-629, FR-630) ----------------------------------------------------------------

def test_event_start_end_or_place_change_sends_event_changed_to_participants_except_author():
    """FR-619, FR-629: смена начала, конца или места — каждому участнику «Событие изменено» (три правки — три
    уведомления), автору — нет."""
    author = _writer()
    first, second = _person(), _person()
    start = _future()
    post = _publish_event(author, to=[_p(first), _p(second)], start=start)
    expected = _want((first, CHANGED), (second, CHANGED))
    before = _ids()
    _edit(author, post, event_start=fd.moscow_text(start + timedelta(minutes=30)))
    assert _new(before) == expected, "начало"
    before = _ids()
    _edit(author, post, event_end=fd.moscow_text(start + timedelta(hours=2)))
    assert _new(before) == expected, "конец"
    before = _ids()
    _edit(author, post, event_place="Корпус 2")
    assert _new(before) == expected, "место"
    note = _feed_notes(first, CHANGED).order_by("-pk").first()
    assert (note.url, note.object_ref) == (f"/feed/{post.pk}/", f"feed.post:{post.pk}")


def test_event_change_with_added_participant_gives_invite_not_event_changed():
    """FR-619, FR-630: если одной правкой меняется место и добавляется участник, новому — «Приглашение», а не
    «Событие изменено»; прежний участник получает «Событие изменено»."""
    author = _writer()
    old, added = _person(), _person()
    post = _publish_event(author, to=[_p(old)])
    before = _ids()
    _edit(author, post, add_to=[_p(added)], event_place="Корпус 2")
    assert _new(before) == _want((old, CHANGED), (added, INVITE))


def test_event_place_change_with_new_mention_of_participant_gives_mention_only():
    """FR-619, FR-630: участнику, которого одной правкой с новым местом упомянули, — одно «Вас упомянули»; второй
    участник получает «Событие изменено»."""
    author = _writer()
    mentioned, other = _person(), _person()
    post = _publish_event(author, to=[_p(mentioned), _p(other)])
    before = _ids()
    _edit(author, post, event_place="Корпус 2", text=f"Подробности {_mark(mentioned)}")
    assert _new(before) == _want((mentioned, MENTION), (other, CHANGED))
    assert _feed_notes(mentioned).count() == 1, "упомянутому участнику — ровно одно уведомление"


def test_event_title_or_description_edit_sends_no_notifications():
    """FR-619: правка названия и описания события уведомлений не создаёт."""
    author = _writer()
    first = _person()
    post = _publish_event(author, to=[_p(first)], text="Прежнее описание")
    before = _ids()
    _edit(author, post, event_title="Новое название", text="Новое описание")
    assert _new(before) == []


def test_extending_important_term_or_repeated_importance_sends_nothing():
    """FR-629: продление срока и повторная важность (после истечения) уведомлений не дают: запись не новая."""
    author = _writer()
    first = _person()
    post = _publish_important(author, "Важное объявление", to=[_p(first)])
    before = _ids()
    _edit(author, post, term="week")
    assert _new(before) == [], "продление срока"
    model("feed.Post").objects.filter(pk=post.pk).update(important_until=timezone.now() - timedelta(days=1))
    _edit(author, post, term="month")
    assert _new(before) == [], "повторная важность после истечения срока"
    assert model("feed.Post").objects.get(pk=post.pk).important_until > timezone.now()


# --- комментарии и отметки (FR-611, FR-629, FR-630) ---------------------------------------------------------

def test_comment_notifies_post_author_and_previous_commenters_not_commenter_with_anchor_url():
    """FR-629, FR-630: комментарий — автору записи и прежним комментаторам, не самому комментатору и не стороннему;
    ссылка — с якорем комментария, `object_ref` — запись."""
    author = _writer()
    earlier, newcomer, bystander = _person(), _person(), _person()
    post = _publish(author, "Запись для обсуждения", to=["all"])
    fd.comment(post, earlier, "Ранний комментарий")
    written = _comments().add(newcomer, post.pk, "Новый комментарий")
    assert _got() == _want((author.user, COMMENT), (earlier, COMMENT))
    assert not _feed_notes(newcomer).exists() and not _feed_notes(bystander).exists()
    for user in (author.user, earlier):
        note = _note(user, COMMENT)
        assert note.url == f"/feed/{post.pk}/#c{written.pk}"
        assert note.object_ref == f"feed.post:{post.pk}"


def test_comment_mention_gives_mention_over_comment_kind_and_makes_recipient():
    """FR-611, FR-629, FR-630: упомянутому в комментарии — «Вас упомянули» (а не «Новый комментарий»), он становится
    адресатом записи и видит её; автор записи получает «Новый комментарий»."""
    author = _writer()
    addressee, outsider = _person(), _person()
    post = _publish(author, "Запись одному человеку", to=[_p(addressee)])
    before = _ids()
    assert _visibility().can_see(outsider.pk, post.pk) is False
    written = _comments().add(addressee, post.pk, f"Позову коллегу {_mark(outsider)}")
    assert _new(before) == _want((author.user, COMMENT), (outsider, MENTION))
    note = _note(outsider, MENTION)
    assert note.url == f"/feed/{post.pk}/#c{written.pk}" and note.object_ref == f"feed.post:{post.pk}"
    assert model("feed.Recipient").objects.filter(post=post, user=outsider, via="mention").exists()
    assert _visibility().can_see(outsider.pk, post.pk) is True


def test_like_notifies_author_post_ref_for_post_comment_ref_and_anchor_for_comment():
    """FR-629: «Нравится» записи — её автору (`object_ref` записи, ссылка на карточку); «Нравится» комментария — его
    автору (`object_ref` с номером комментария, ссылка с якорем)."""
    author = _writer()
    commenter, liker = _person(), _person()
    post = _publish(author, "Запись для отметок", to=["all"])
    written = fd.comment(post, commenter, "Комментарий")
    _likes().toggle_post(liker, post.pk)
    _likes().toggle_comment(liker, written.pk)
    assert _got() == _want((author.user, LIKE), (commenter, LIKE))
    on_post = _note(author.user, LIKE)
    assert (on_post.url, on_post.object_ref) == (f"/feed/{post.pk}/", f"feed.post:{post.pk}")
    on_comment = _note(commenter, LIKE)
    assert on_comment.url == f"/feed/{post.pk}/#c{written.pk}"
    assert on_comment.object_ref == f"feed.post:{post.pk}:c{written.pk}"


def test_likes_of_post_and_comment_of_same_author_give_two_notifications():
    """FR-629: отметки записи и комментария одного автора не склеиваются — два уведомления с разными `object_ref`."""
    author = _writer()
    liker = _person()
    post = _publish(author, "Запись автора", to=["all"])
    written = _comments().add(author.user, post.pk, "Комментарий автора")
    _likes().toggle_post(liker, post.pk)
    _likes().toggle_comment(liker, written.pk)
    notes = list(_feed_notes(author.user, LIKE))
    assert len(notes) == 2
    assert {note.object_ref for note in notes} == {f"feed.post:{post.pk}", f"feed.post:{post.pk}:c{written.pk}"}


# --- транзакция и правило приоритета (FR-630) ---------------------------------------------------------------

def test_notifications_created_by_dispatch_create_inside_action_transaction(monkeypatch):
    """FR-630: `dispatch.create` зовётся внутри транзакции действия — публикации, комментария, отметки: на входе
    открыта вложенная транзакция (глубина больше исходной), строки действия уже записаны."""
    from apps.notify.services import dispatch

    real = dispatch.create
    seen = []

    def spy(kind_code, drafts):
        drafts = list(drafts)
        seen.append({"kind": kind_code, "depth": len(connection.savepoint_ids), "drafts": drafts,
                     "posts": model("feed.Post").objects.count(), "comments": model("core.Comment").objects.count(),
                     "likes": model("feed.PostLike").objects.count()})
        return real(kind_code, drafts)

    monkeypatch.setattr("apps.notify.services.dispatch.create", spy)
    author = _writer()
    target, commenter = _person(), _person()
    base = len(connection.savepoint_ids)

    post = _publish(author, "Запись", to=[_p(target)])
    publish_calls = [call for call in seen if call["kind"] == FOR_YOU]
    assert publish_calls, "публикация зовёт `dispatch.create` для «Запись для вас»"
    assert all(call["depth"] > base and call["posts"] == 1 for call in publish_calls)

    seen.clear()
    _comments().add(commenter, post.pk, "Комментарий")
    comment_calls = [call for call in seen if call["kind"] == COMMENT]
    assert comment_calls and all(call["depth"] > base and call["comments"] == 1 for call in comment_calls)

    seen.clear()
    _likes().toggle_post(commenter, post.pk)
    like_calls = [call for call in seen if call["kind"] == LIKE]
    assert like_calls and all(call["depth"] > base and call["likes"] == 1 for call in like_calls)
    assert _got() == sorted([(target.pk, FOR_YOU), (author.user.pk, COMMENT), (author.user.pk, LIKE)])


def test_notify_rules_decide_applies_full_priority_order():
    """FR-630 (решение 51 задач): `notify_rules.decide(RuleEvent(...))` без действий — один вид на получателя по
    порядку «Вас упомянули» → «Приглашение» → «Событие изменено» → «Важная запись» → «Запись для вас» → «Новый
    комментарий»; без действующего, уволенного и не из `audience`; «Нравится» — без конкуренции."""
    rules = _rules()
    assert tuple(rules.PRIORITY) == PRIORITY
    author = _person("Анна Автор")
    mention, personal, plain = _person(), _person(), _person()
    dismissed, outside = _person(state="dismissed"), _person()
    everyone = {author.pk, mention.pk, personal.pk, plain.pk, dismissed.pk}

    def decide(actor=author, **fields) -> dict:
        result = rules.decide(rules.RuleEvent(actor_id=actor.pk, **fields))
        assert all(draft.user_id == user for user, (_code, draft) in result.items())
        return {user: code for user, (code, _draft) in result.items()}

    start = _future()
    event_post = fd.make_event(author, start=start, to=[personal, mention])
    important_post = fd.make_important(author, to=[personal, mention])
    plain_post = fd.make_post(author, to=[personal, mention])
    people = frozenset({personal.pk, mention.pk, dismissed.pk, outside.pk})

    # публикация: упоминание сильнее всего; затем вид записи; «лично» — только у обычной записи
    base = dict(action="publish", audience=frozenset(everyone), to_people=people, mentioned=frozenset({mention.pk}))
    assert decide(post=event_post, **base) == {mention.pk: MENTION, personal.pk: INVITE, plain.pk: INVITE}
    assert decide(post=important_post, **base) == {mention.pk: MENTION, personal.pk: IMPORTANT, plain.pk: IMPORTANT}
    assert decide(post=plain_post, **base) == {mention.pk: MENTION, personal.pk: FOR_YOU}

    # правка события: добавленный участник — приглашение, прежние — «Событие изменено», упомянутые — «Вас упомянули»
    new_one, new_mentioned = _person(), _person()
    edit_base = dict(action="edit", before=frozenset({author.pk, personal.pk, mention.pk}),
                     audience=frozenset({author.pk, personal.pk, mention.pk, new_one.pk, new_mentioned.pk}),
                     to_people=frozenset({new_one.pk}), mentioned=frozenset({new_mentioned.pk, mention.pk}))
    assert decide(post=event_post, event_changed=True, **edit_base) == {
        new_one.pk: INVITE, new_mentioned.pk: MENTION, mention.pk: MENTION, personal.pk: CHANGED}
    assert decide(post=event_post, event_changed=False, **edit_base) == {
        new_one.pk: INVITE, new_mentioned.pk: MENTION, mention.pk: MENTION}
    unit_added = _person()
    wide = dict(edit_base, audience=edit_base["audience"] | {unit_added.pk})
    assert decide(post=important_post, **wide) == {
        new_one.pk: IMPORTANT, unit_added.pk: IMPORTANT, new_mentioned.pk: MENTION, mention.pk: MENTION}
    assert decide(post=plain_post, **wide) == {
        new_one.pk: FOR_YOU, new_mentioned.pk: MENTION, mention.pk: MENTION}

    # комментарий: упоминание сильнее «Нового комментария»; автор записи и прежние комментаторы; не сам комментатор
    commenter, previous, bystander = _person(), _person(), _person()
    written = fd.comment(plain_post, commenter, "Комментарий")
    audience = frozenset({author.pk, commenter.pk, previous.pk, mention.pk, bystander.pk})
    assert decide(commenter, action="comment", post=plain_post, comment=written, audience=audience,
                  commenters=frozenset({previous.pk, mention.pk}), mentioned=frozenset({mention.pk})) == {
        author.pk: COMMENT, previous.pk: COMMENT, mention.pk: MENTION}

    # «Нравится» — отдельное действие: только автору, не себе
    liker = _person()
    assert decide(liker, action="like", post=plain_post, audience=frozenset({author.pk, liker.pk})) == {
        author.pk: LIKE}
    assert decide(author, action="like", post=plain_post, audience=frozenset({author.pk})) == {}
