"""Создание, правка и удаление записей ленты (T-7214/T-7216/T-7217/T-7220)."""

import pathlib
from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from django.core.exceptions import PermissionDenied

from apps.core import widgets
from apps.core.extensions import Draft
from apps.core.services import audit
from apps.core.services import comments as core_comments
from apps.core.services import files as core_files
from apps.core.models import StoredFile
from apps.feed.models import FeedFile, Post, Recipient
from apps.feed.services import events, files, important, mentions, pdn, recipients, search, text, visibility
from apps.feed.services import live as _live
from apps.feed.services.errors import FeedError, PdnFound
from apps.feed.services.notify_rules import RuleEvent, decide


def _get(data, name, default=""):
    if hasattr(data, "get"):
        return data.get(name, default)
    return default


def publish(user, data, *, now=None) -> Post:
    """Опубликовать запись: поля вида, адресаты и вектор атомарно."""
    kind = _get(data, "kind", Post.Kind.POST)
    if kind not in Post.Kind.values:
        kind = Post.Kind.POST

    text = str(_get(data, "text", "")).replace("\x00", "")
    if kind != Post.Kind.EVENT and not text.strip():
        raise FeedError("empty_text", "text")
    if len(text) > 10_000:
        raise FeedError("too_long", "text", {"limit": "10000"})

    mentions.extract(text)
    targets = recipients.parse(visibility.viewer(user), data)
    found = pdn.find_plain(text)
    if found and str(_get(data, "pdn_confirmed", "")) not in ("1", "true", "True"):
        raise PdnFound(found)

    file_ids, _ = _file_inputs(data)

    published_at = now if now is not None else timezone.now()
    important_until = None
    event_fields = {}
    if kind == Post.Kind.EVENT:
        event = events.validate(data, now=published_at)
        event_fields = {"event_title": event.title, "event_place": event.place,
                        "event_start": event.start, "event_end": event.end,
                        "remind_at": events.remind_at(event.start, published_at)}
    if kind == Post.Kind.IMPORTANT:
        term = _get(data, "term")
        date = widgets.parse_date(_get(data, "until")) if term == "date" else None
        important_until = important.until(term, date, published_at.astimezone(widgets.MOSCOW).date())
    with transaction.atomic():
        post = Post.objects.create(
            author=user,
            kind=kind,
            text=text,
            to_all=targets.to_all,
            published_at=published_at,
            important_until=important_until,
            **event_fields,
        )
        rows = [
            Recipient(post=post, kind=Recipient.Kind.UNIT, unit_id=unit_id,
                      via=Recipient.Via.TO, published_at=published_at)
            for unit_id in targets.unit_ids
        ]
        rows.extend(
            Recipient(post=post, kind=Recipient.Kind.USER, user_id=user_id,
                      via=Recipient.Via.TO, published_at=published_at)
            for user_id in targets.user_ids
        )
        if rows:
            Recipient.objects.bulk_create(rows)
        mentioned_ids = mentions.sync(post, text)
        search.vectors(post_ids=[post.pk])
        files.bind(user, file_ids, post=post)

        # Уведомления публикации: фактическая аудитория, упомянутые и личные адресаты «Кому»; автору — ничего.
        if apps.is_installed("apps.notify"):
            from apps.notify.services import dispatch

            decisions = decide(
                RuleEvent(
                    actor_id=user.pk,
                    action="publish",
                    post=post,
                    audience=visibility.audience(post),
                    mentioned=frozenset(mentioned_ids),
                    to_people=frozenset(targets.user_ids),
                )
            )
            for uid, (kind_code, _) in decisions.items():
                dispatch.create(
                    kind_code,
                    [
                        Draft(
                            user_id=uid,
                            text=_notify_text(kind_code, post),
                            url=f"/feed/{post.pk}/",
                            object_ref=f"feed.post:{post.pk}",
                        )
                    ],
                )

        transaction.on_commit(lambda: _live.publish_event(post.pk, "new", owner_id=user.pk))
    post.refresh_from_db()
    return post


def _erase_paths(paths) -> None:
    """Стирает файлы с диска после фиксации; отсутствующий файл — не ошибка."""
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def delete(user, post_id: int) -> None:
    """Удалить запись ленты одной транзакцией: файлы, комментарии, аудит, диск после фиксации."""
    with transaction.atomic():
        try:
            post = Post.objects.select_for_update().get(pk=post_id)
        except Post.DoesNotExist as exc:
            raise Http404 from exc
        if not visibility.can_see(user.pk, post.pk):
            raise Http404
        if not visibility.can_delete(user, post):
            raise PermissionDenied

        # Снимок до каскада: рассылку подключает T-7222b.
        before_audience = visibility.audience(post)
        post_author_id = post.author_id
        post_pk = post.pk
        is_moderator = user.pk != post_author_id
        published_at = post.published_at
        paths: list[pathlib.Path] = []
        stored_ids: list[str] = []
        for feed_file in FeedFile.objects.filter(post=post).select_related("file"):
            paths.append(core_files.attachment_path(feed_file.file))
            stored_ids.append(str(feed_file.file_id))
            if feed_file.thumb:
                paths.append(pathlib.Path(settings.PROTECTED_ROOT) / feed_file.thumb)

        transaction.on_commit(
            lambda: _live.publish_event(
                post_pk, "delete", recipients=before_audience, owner_id=post_author_id
            )
        )
        core_comments.delete_for(f"feed.post:{post_id}")
        post.delete()
        if stored_ids:
            StoredFile.objects.filter(pk__in=stored_ids).delete()
        if is_moderator:
            audit.record(
                "feed.post_deleted",
                actor=user,
                object_type="feed.post",
                object_id=post_id,
                before={
                    "author": post.author.full_name,
                    "published_at": published_at.astimezone(widgets.MOSCOW).strftime("%d.%m.%Y %H:%M"),
                },
            )
        if paths:
            transaction.on_commit(lambda: _erase_paths(paths))


def _recipient_targets(post) -> recipients.Targets:
    """Сохранённые адресаты `to` записи."""
    to_all = post.to_all
    unit_ids: list[int] = []
    user_ids: list[int] = []
    for row in Recipient.objects.filter(post=post, via=Recipient.Via.TO):
        if row.kind == Recipient.Kind.UNIT:
            unit_ids.append(row.unit_id)
        else:
            user_ids.append(row.user_id)
    return recipients.Targets(to_all, tuple(unit_ids), tuple(user_ids))


def _int_ids(values):
    """Номера из значений формы."""
    if values is None:
        return []
    if hasattr(values, "getlist"):
        values = values.getlist("files") or values.getlist("remove") or []
    if isinstance(values, (str, bytes)):
        values = [values]
    ids = []
    for value in values:
        text = str(value).strip()
        if text.isdigit():
            ids.append(int(text))
    return ids


def _file_inputs(data):
    """Разобрать списки files/remove с учётом QueryDict.

    Дедупликация выполняется после нормализации в int-ID, поэтому разные
    текстовые представления одного номера ("1", "01", " 1 ") не приводят
    к повторному удалению и неверному расчёту предела файлов.
    """
    files, remove = [], []
    if hasattr(data, "getlist"):
        files = data.getlist("files") if "files" in data else []
        remove = data.getlist("remove") if "remove" in data else []
    else:
        files = data.get("files") if isinstance(data.get("files"), (list, tuple)) else []
        remove = data.get("remove") if isinstance(data.get("remove"), (list, tuple)) else []
    return list(dict.fromkeys(_int_ids(files))), list(dict.fromkeys(_int_ids(remove)))


def _notify_text(kind_code: str, post: Post) -> str:
    """Тексты уведомлений записи по шаблонам плана (CONTRACT-007, 7.2); весь текст — не длиннее 300 (К26)."""
    author_name = post.author.full_name
    snippet = text.snippet(post.text, 100)
    if kind_code == "feed.event_changed":
        title = text.snippet(post.event_title, 60)
        place = text.snippet(post.event_place, 60)
        stamp = post.event_start.astimezone(widgets.MOSCOW).strftime("%d.%m.%Y %H:%M")
        return text.snippet(f"Событие «{title}» изменено: {stamp}, {place}", 300)
    if kind_code == "feed.mention":
        return text.snippet(f"{author_name} упомянул(а) вас: «{snippet}»", 300)
    if kind_code == "feed.invite":
        title = text.snippet(post.event_title, 60)
        stamp = post.event_start.astimezone(widgets.MOSCOW).strftime("%d.%m.%Y %H:%M")
        return text.snippet(f"{author_name} приглашает на событие «{title}» {stamp}", 300)
    if kind_code == "feed.important":
        return text.snippet(f"Важная запись от {author_name}: «{snippet}»", 300)
    if kind_code == "feed.for_you":
        return text.snippet(f"{author_name}: запись для вас — «{snippet}»", 300)
    return snippet


def edit(user, post_id: int, data, *, now=None) -> Post:
    """Править запись: текст, адресаты, файлы, срок важного, поля события."""
    from apps.feed.services import live

    post = visibility.get_post(user, post_id)
    if not visibility.can_edit(user, post):
        raise PermissionDenied

    text = str(_get(data, "text", "")).replace("\x00", "")
    if post.kind != Post.Kind.EVENT and not text.strip():
        raise FeedError("empty_text", "text")
    if len(text) > 10_000:
        raise FeedError("too_long", "text", {"limit": "10000"})

    mentioned_ids = mentions.extract(text)

    viewer = visibility.viewer(user)
    saved_targets = _recipient_targets(post)
    targets = recipients.parse(viewer, data, saved=saved_targets)

    file_ids, remove_ids = _file_inputs(data)

    event_fields = {}
    event_changed = False
    if post.kind == Post.Kind.EVENT:
        event = events.validate(data, now=timezone.now() if now is None else now, editing=post)
        old_start, old_end, old_place = post.event_start, post.event_end, post.event_place
        event_changed = (event.start != old_start or event.end != old_end or event.place != old_place)
        new_remind_at = post.remind_at
        if event.start != old_start:
            new_remind_at = events.edit_remind_at(post, event.start, timezone.now() if now is None else now)
        event_fields = {
            "event_title": event.title,
            "event_place": event.place,
            "event_start": event.start,
            "event_end": event.end,
            "remind_at": new_remind_at,
        }

    important_until = post.important_until
    if post.kind == Post.Kind.IMPORTANT:
        term_sent = False
        if hasattr(data, "__contains__"):
            term_sent = "term" in data
        elif isinstance(data, dict):
            term_sent = "term" in data
        if term_sent:
            term = _get(data, "term")
            today = widgets.moscow_today() if now is None else now.astimezone(widgets.MOSCOW).date()
            if term == "date":
                date = widgets.parse_date(_get(data, "until"))
                saved_last_day = (
                    post.important_until.astimezone(widgets.MOSCOW).date() - timedelta(days=1)
                    if post.important_until else None
                )
                if date is None or date != saved_last_day:
                    important_until = important.until(term, date, today)
            else:
                candidate = important.until(term, None, today)
                if candidate != important_until:
                    important_until = candidate

    pdn_texts = [text]
    if post.kind == Post.Kind.EVENT:
        pdn_texts.extend([event_fields["event_title"], event_fields["event_place"]])
    found = pdn.find_plain(*pdn_texts)
    if found and str(_get(data, "pdn_confirmed", "")) not in ("1", "true", "True"):
        raise PdnFound(found)

    before_audience = visibility.audience(post)

    with transaction.atomic():
        post = Post.objects.select_for_update().get(pk=post.pk)

        # «Убрать» при правке — только файлы этой записи; строки — в транзакции, диск — после фиксации.
        current_files = {
            ff.pk: ff
            for ff in FeedFile.objects.filter(post=post, comment__isnull=True).select_related("file")
        }
        for rid in remove_ids:
            if rid not in current_files:
                raise FeedError("file_missing", "files")
        gone_stored: list[str] = []
        gone_paths: list[pathlib.Path] = []
        for rid in remove_ids:
            ff = current_files[rid]
            gone_stored.append(str(ff.file_id))
            gone_paths.append(core_files.attachment_path(ff.file))
            if ff.thumb:
                gone_paths.append(pathlib.Path(settings.PROTECTED_ROOT) / ff.thumb)
            ff.delete()
        if gone_stored:
            StoredFile.objects.filter(pk__in=gone_stored).delete()

        # Привязка новых файлов условным UPDATE с проверкой числа строк и пределом 10.
        files.bind(user, file_ids, post=post)

        # Адресаты: сохранённые остаются, добавляются новые.
        new_units = set(targets.unit_ids) - set(saved_targets.unit_ids)
        new_users = set(targets.user_ids) - set(saved_targets.user_ids)
        published_at = post.published_at
        new_rows = [
            Recipient(post=post, kind=Recipient.Kind.UNIT, unit_id=unit_id,
                      via=Recipient.Via.TO, published_at=published_at)
            for unit_id in new_units
        ]
        new_rows.extend(
            Recipient(post=post, kind=Recipient.Kind.USER, user_id=user_id,
                      via=Recipient.Via.TO, published_at=published_at)
            for user_id in new_users
        )
        if new_rows:
            Recipient.objects.bulk_create(new_rows)
        if not post.to_all and targets.to_all:
            post.to_all = True

        new_mentions = mentions.sync(post, text, old_text=post.text)

        post.text = text
        post.edited_at = timezone.now() if now is None else now
        if post.kind == Post.Kind.IMPORTANT:
            post.important_until = important_until
        if post.kind == Post.Kind.EVENT:
            for key, value in event_fields.items():
                setattr(post, key, value)
        post.save()

        search.vectors(post_ids=[post.pk])

        # Уведомления только новым адресатам/упоминаниям и об изменении события.
        after_audience = visibility.audience(post)

        if apps.is_installed("apps.notify"):
            from apps.notify.services import dispatch

            decisions = decide(
                RuleEvent(
                    actor_id=user.pk,
                    action="edit",
                    post=post,
                    audience=after_audience,
                    before=before_audience,
                    mentioned=frozenset(new_mentions),
                    to_people=frozenset(new_users),
                    event_changed=event_changed,
                )
            )
            for uid, (kind_code, _) in decisions.items():
                dispatch.create(
                    kind_code,
                    [
                        Draft(
                            user_id=uid,
                            text=_notify_text(kind_code, post),
                            url=f"/feed/{post.pk}/",
                            object_ref=f"feed.post:{post.pk}",
                        )
                    ],
                )

        transaction.on_commit(lambda: live.publish_event(post.pk, "post", owner_id=user.pk))
        if gone_paths:
            transaction.on_commit(lambda: _erase_paths(gone_paths))

    post.refresh_from_db()
    return post
