"""Соединение WebSocket ленты (срез 007)."""

import json
from datetime import datetime, timezone as dt_timezone
from urllib.parse import parse_qs, urlencode, quote

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone

from apps.core.ws import SessionGuardMixin
from apps.feed.services import page, unread, visibility
from apps.feed.models import Post, Recipient

CHECK_INTERVAL = 25  # секунд между проверками сессии
LIMIT_BYTES = 16384
MAX_IDS = 300


def _positive_id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdigit() and value[0] != "0":
        return int(value)
    return None


def _parse_ids(items):
    """Список номеров: только положительные целые, не более MAX_IDS."""
    result = []
    if isinstance(items, (list, tuple)):
        for item in items:
            number = _positive_id(item)
            if number is not None and number not in result:
                result.append(number)
    return result[:MAX_IDS]


def _moment(value):
    """Aware datetime из ISO-строки или datetime."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime) or timezone.is_naive(value):
        return None
    return value.astimezone(dt_timezone.utc)


def _filter_query(user, flt, since):
    """Видимые записи позже since, кроме своих, с фильтром соединения."""
    posts = visibility.visible_posts(user).filter(published_at__gt=since).exclude(author_id=user.pk)
    if flt.f == "important":
        posts = posts.filter(kind=Post.Kind.IMPORTANT)
    elif flt.f == "events":
        posts = posts.filter(kind=Post.Kind.EVENT)
    elif flt.f == "mine":
        posts = posts.filter(author_id=user.pk)
    elif flt.f == "mentions":
        posts = posts.filter(recipients__via=Recipient.Via.MENTION, recipients__user_id=user.pk)
    if flt.author is not None:
        posts = posts.filter(author_id=flt.author)
    start = page._boundary(flt.date_from)
    end = page._boundary(flt.date_to, following=True)
    if start is not None:
        posts = posts.filter(published_at__gte=start)
    if end is not None:
        posts = posts.filter(published_at__lt=end)
    return posts


@database_sync_to_async
def _pending_posts(user, flt, since):
    """Словарь id → published_at для pending-записей (один запрос)."""
    return dict(_filter_query(user, flt, since).values_list("pk", "published_at"))


def _matches_filter(meta, flt, user_id, since):
    """Подходит ли meta-событие new под фильтр и since без запросов к базе."""
    published = _moment(meta.get("published_at"))
    since = _moment(since)
    if published is None or since is None or published <= since:
        return False
    author = meta.get("author")
    if author == user_id:
        return False
    kind = meta.get("kind", "post")
    if flt.f == "important" and kind != "important":
        return False
    if flt.f == "events" and kind != "event":
        return False
    if flt.f == "mine" and author != user_id:
        return False
    if flt.f == "mentions" and user_id not in set(meta.get("mentioned", [])):
        return False
    if flt.author is not None and author != flt.author:
        return False
    if flt.date_from is not None:
        start = page._boundary(flt.date_from)
        if start is not None and published < start:
            return False
    if flt.date_to is not None:
        end = page._boundary(flt.date_to, following=True)
        if end is not None and published >= end:
            return False
    return True


def _banner_context(count, flt, since):
    values = {}
    if flt.f != "all":
        values["f"] = flt.f
    if flt.author is not None:
        values["author"] = str(flt.author)
    if flt.date_from is not None:
        values["from"] = flt.date_from.isoformat()
    if flt.date_to is not None:
        values["to"] = flt.date_to.isoformat()
    if since is not None:
        values["since"] = since.isoformat()
    link = urlencode(values, quote_via=quote) if values else ""
    return {"count": count, "link": link, "since": since}


def _render_banner(count, flt, since):
    from django.template.loader import render_to_string

    return render_to_string("feed/_new_banner.html", _banner_context(count, flt, since)).strip()


class FeedConsumer(SessionGuardMixin, AsyncWebsocketConsumer):
    """Соединение `/ws/feed/`: личная группа, sync/add, кадры о записях и плашка «Новых записей»."""

    user_id = None
    post_id = None
    flt = None
    ids = None
    since = None
    pending = None

    def check_interval(self) -> float:
        return CHECK_INTERVAL

    async def on_check(self) -> None:
        user = self.scope.get("user")
        if user is not None and user.pk is not None:
            await database_sync_to_async(
                user.refresh_from_db, thread_sensitive=True
            )(fields=("activated_at", "created_at"))

    async def connect(self):
        if not await self.guard_connect():
            return
        user = self.scope.get("user")
        self.user_id = user.pk
        self.flt = page.parse_filter(parse_qs(self.scope.get("query_string", b"").decode("utf-8")))
        post_param = parse_qs(self.scope.get("query_string", b"").decode("utf-8")).get("post", [None])[0]
        if post_param is not None and post_param.isdigit():
            self.post_id = int(post_param)
        if self.post_id is not None:
            self.ids = {self.post_id}
        else:
            self.ids = set()
        self.pending = {}
        await self.accept()
        try:
            await self.channel_layer.group_add(self._group(), self.channel_name)
        except Exception:
            await self.close(code=1011)
            return
        self.start_guard()

    async def disconnect(self, code):
        self.stop_guard()
        await self.channel_layer.group_discard(self._group(), self.channel_name)

    def _group(self):
        return f"feed.u.{self.user_id}"

    async def receive(self, text_data=None, bytes_data=None):
        if text_data is None:
            return
        if len(text_data.encode("utf-8")) > LIMIT_BYTES:
            await self.close(code=1009)
            return
        try:
            payload = json.loads(text_data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return
        if not isinstance(payload, dict):
            return
        if "sync" in payload:
            await self._handle_sync(payload.get("sync"))
        elif "add" in payload:
            await self._handle_add(payload)

    async def _handle_sync(self, payload):
        since = None
        ids = []
        if isinstance(payload, dict):
            since = _moment(payload.get("since"))
            ids = _parse_ids(payload.get("ids"))
        if since is None:
            since = timezone.now()
        self.since = since
        self.ids = set(ids)
        user = self.scope.get("user")
        self.pending = await _pending_posts(user, self.flt, self.since)
        parts = ['<div id="feed-synced" hx-swap-oob="true"></div>']
        if self.post_id is None and self.pending:
            parts.append(_render_banner(len(self.pending), self.flt, self.since))
        await self.send(text_data="".join(parts))

    async def _handle_add(self, payload):
        add_payload = payload.get("add") if isinstance(payload, dict) else payload
        since = _moment(payload.get("since")) if isinstance(payload, dict) else None
        if isinstance(add_payload, dict):
            ids = _parse_ids(add_payload.get("ids"))
        elif isinstance(add_payload, (list, tuple)):
            ids = _parse_ids(add_payload)
        else:
            ids = []
        room = MAX_IDS - len(self.ids)
        if room > 0:
            self.ids.update(ids[:room])
        if since is not None:
            self.since = since
            self.pending = {
                pk: published for pk, published in self.pending.items()
                if published > since
            }
            if self.post_id is None:
                await self.send(text_data=_render_banner(len(self.pending), self.flt, self.since))

    async def feed_event(self, event):
        action = event.get("action")
        post_id = event.get("post")
        if post_id is None:
            return
        tracked = self.post_id == post_id or post_id in self.ids
        if action == "new":
            if self.post_id is not None:
                return
            meta = event.get("meta") or {}
            if _matches_filter(meta, self.flt, self.user_id, self.since):
                published = _moment(meta.get("published_at"))
                if published is not None:
                    self.pending[post_id] = published
                await self.send(text_data=_render_banner(len(self.pending), self.flt, self.since))
            return
        if action == "delete":
            if post_id in self.pending:
                del self.pending[post_id]
                if self.post_id is None:
                    await self.send(text_data=_render_banner(len(self.pending), self.flt, self.since))
            if tracked:
                await self._send_variant(event)
            return
        if tracked:
            await self._send_variant(event)

    async def _send_variant(self, event):
        role = "author"
        owner = event.get("owner")
        if owner != self.user_id:
            role = "moderator" if self.user_id in set(event.get("moderators", [])) else "reader"
        link_staff = self.user_id in set(event.get("staff_viewers", []))
        key = f"{role}:{int(link_staff)}"
        html = event.get("variants", {}).get(key)
        if html:
            await self.send(text_data=html)
