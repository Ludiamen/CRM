"""T-7224: функции склейки текста «Новый комментарий» и «Нравится» (FR-629, PLAN-007 «Склейка с обновлением текста»)."""

from datetime import timedelta

import pytest

from django.utils import timezone

from tests import support
from tests import support_feed as ff

pytestmark = pytest.mark.django_db


def _at(minutes: int):
    """Синтетический момент через `minutes` минут от вызова."""
    return timezone.now() + timedelta(minutes=minutes)


@pytest.fixture
def scene():
    author = support.make_employee(full_name="Анна Автор")
    recipient = support.make_employee(full_name="Пётр Получатель")
    post = ff.make_post(author, to=[recipient], text="Запись для обсуждения")
    return author, recipient, post


@pytest.fixture
def likers():
    return [support.make_employee(full_name="Лев Первый"),
            support.make_employee(full_name="Мира Вторая"),
            support.make_employee(full_name="Нина Третья")]


def _post_like(post, user, minutes: int):
    return support.model("feed.PostLike").objects.create(post=post, user=user, created_at=_at(minutes))


def _comment_like(comment, post, user, minutes: int):
    return support.model("feed.CommentLike").objects.create(comment=comment, post=post, user=user,
                                                             created_at=_at(minutes))


def test_comment_coalesce_counts_other_comments_after_since_plus_one(scene):
    """N — комментарии других после `since` плюс один; отрывок — текст записи (план «Склейка»)."""
    from apps.feed.notify_kinds import comment_coalesce_text

    _, recipient, post = scene
    ff.comment(post, support.make_employee(full_name="Борис Первый"), "Первый", created_at=_at(0))
    ff.comment(post, support.make_employee(full_name="Вера Вторая"), "Второй", created_at=_at(1))
    ff.comment(post, support.make_employee(full_name="Глеб Третий"), "Третий", created_at=_at(2))
    ref = f"feed.post:{post.pk}"
    assert comment_coalesce_text(recipient.pk, ref, _at(0)) == "Новых комментариев: 3 к записи «Запись для обсуждения»"
    assert comment_coalesce_text(recipient.pk, ref, _at(1)) == "Новых комментариев: 2 к записи «Запись для обсуждения»"


def test_comment_coalesce_excludes_recipient_own_comments(scene):
    """Комментарии самого получателя в число новых не входят."""
    from apps.feed.notify_kinds import comment_coalesce_text

    _, recipient, post = scene
    ff.comment(post, support.make_employee(full_name="Борис Первый"), "Первый", created_at=_at(0))
    ff.comment(post, recipient, "Ответ получателя", created_at=_at(1))
    ff.comment(post, support.make_employee(full_name="Вера Вторая"), "Второй", created_at=_at(2))
    assert comment_coalesce_text(recipient.pk, f"feed.post:{post.pk}", _at(0)) == \
        "Новых комментариев: 2 к записи «Запись для обсуждения»"


def test_comment_coalesce_single_comment_gives_ordinary_text(scene):
    """При N = 1 — обычный текст: ФИО последнего комментатора других и отрывок записи (план)."""
    from apps.feed.notify_kinds import comment_coalesce_text

    _, recipient, post = scene
    ff.comment(post, support.make_employee(full_name="Борис Первый"), "Первый", created_at=_at(0))
    assert comment_coalesce_text(recipient.pk, f"feed.post:{post.pk}", _at(5)) == \
        "Борис Первый прокомментировал(а) запись «Запись для обсуждения»"


def test_comment_coalesce_rejects_comment_refs_garbage_and_missing_post(scene):
    """Форма со ссылкой на комментарий, мусор, несуществующая запись и сверхдлинный номер — пустой текст."""
    from apps.feed.notify_kinds import comment_coalesce_text

    _, recipient, post = scene
    note = ff.comment(post, support.make_employee(full_name="Борис Первый"), "Первый", created_at=_at(0))
    for bad in ("", "nope", f"feed.post:{post.pk}:c{note.pk}", f"feed.post:{post.pk + 10**6}",
                "feed.post:" + "9" * 5000, None):
        assert comment_coalesce_text(recipient.pk, bad, _at(0)) == "", bad


def test_like_coalesce_post_last_liker_and_extra_after_since(scene, likers):
    """Запись: последний отметивший и N — отметившие после `since`; при N = 0 скобки нет (план)."""
    from apps.feed.notify_kinds import like_coalesce_text

    author, _, post = scene
    for i, liker in enumerate(likers):
        _post_like(post, liker, i)
    ref = f"feed.post:{post.pk}"
    assert like_coalesce_text(author.pk, ref, _at(0)) == "Нравится Нина Третья (и ещё 2): «Запись для обсуждения»"
    assert like_coalesce_text(author.pk, ref, _at(2)) == "Нравится Нина Третья: «Запись для обсуждения»"


def test_like_coalesce_excludes_recipient_own_likes(scene, likers):
    """Отметка самого получателя не считается и не становится «последним отметившим»."""
    from apps.feed.notify_kinds import like_coalesce_text

    author, _, post = scene
    _post_like(post, likers[0], 0)
    _post_like(post, author, 1)
    _post_like(post, likers[1], 2)
    assert like_coalesce_text(author.pk, f"feed.post:{post.pk}", _at(0)) == \
        "Нравится Мира Вторая (и ещё 1): «Запись для обсуждения»"


def test_like_coalesce_comment_ref_uses_comment_likes_and_snippet(scene, likers):
    """Комментарий: считаются отметки этого комментария, отрывок — текст комментария (план, исключение)."""
    from apps.feed.notify_kinds import like_coalesce_text

    author, _, post = scene
    commenter = support.make_employee(full_name="Клим Комментатор")
    note = ff.comment(post, commenter, "Мой комментарий", created_at=_at(0))
    _comment_like(note, post, likers[0], 1)
    _comment_like(note, post, likers[1], 2)
    ref = f"feed.post:{post.pk}:c{note.pk}"
    assert like_coalesce_text(commenter.pk, ref, _at(1)) == "Нравится Мира Вторая (и ещё 1): «Мой комментарий»"
    assert like_coalesce_text(commenter.pk, ref, _at(2)) == "Нравится Мира Вторая: «Мой комментарий»"


def test_like_coalesce_rejects_garbage_and_foreign_comment(scene, likers):
    """Мусор, чужая запись, комментарий другой записи и сверхдлинный номер — пустой текст."""
    from apps.feed.notify_kinds import like_coalesce_text

    author, recipient, post = scene
    other_post = ff.make_post(author, to=[recipient], text="Другая запись")
    note = ff.comment(post, support.make_employee(full_name="Клим Комментатор"), "Мой комментарий", created_at=_at(0))
    foreign = ff.comment(other_post, support.make_employee(full_name="Лев Первый"), "Чужой", created_at=_at(0))
    _post_like(post, likers[0], 1)
    for bad in ("", "nope", f"feed.post:{post.pk + 10**6}", "feed.post:" + "9" * 5000,
                f"feed.post:{post.pk}:c{foreign.pk}", f"feed.post:{other_post.pk}:c{note.pk}", None):
        assert like_coalesce_text(author.pk, bad, _at(0)) == "", bad


def test_coalesce_texts_snippet_100_and_total_300(scene, likers):
    """Отрывок — не длиннее 100 знаков, весь текст склейки — не длиннее 300 (план «Тексты»)."""
    from apps.feed.notify_kinds import comment_coalesce_text, like_coalesce_text

    author, recipient, _ = scene
    long_text = " ".join(f"слово{i}" for i in range(40))
    post = ff.make_post(author, to=[recipient], text=long_text)
    ff.comment(post, support.make_employee(full_name="Борис Первый"), "Первый", created_at=_at(0))
    ff.comment(post, support.make_employee(full_name="Вера Вторая"), "Второй", created_at=_at(1))
    counted = comment_coalesce_text(recipient.pk, f"feed.post:{post.pk}", _at(0))
    piece = counted[counted.index("«") + 1:counted.rindex("»")]
    assert len(piece) <= 100 and piece.endswith("…")
    assert len(counted) <= 300

    long_name = "Длинные Фамилия Имя Отчество Второе" + "о" * 170
    _post_like(post, support.make_employee(full_name=long_name), 2)
    liked = like_coalesce_text(recipient.pk, f"feed.post:{post.pk}", _at(0))
    assert len(liked) <= 300 and liked.endswith("…")
