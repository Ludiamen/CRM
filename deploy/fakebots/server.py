"""Учебная служба ботов (PLAN-004, «Запуск»): часть Bot API Telegram и MAX для стенда и тестов.

Только стандартная библиотека. Состояние — в памяти процесса под замком. Токены принимаются
любые непустые и нигде не запоминаются и не пишутся в журнал. В установку не входит.
Порт — переменная окружения FAKEBOTS_PORT (по умолчанию 8099).
"""
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

TG_BOT = {"id": 7000001, "is_bot": True, "first_name": "Портал (стенд)", "username": "stand_notify_bot"}
MAX_BOT = {"user_id": 8000001, "name": "Портал (стенд)", "username": "stand_notify_bot"}
TG_MAX_TIMEOUT = 50
MAX_MAX_TIMEOUT = 90
FAIL_STATUSES = (401, 403, 409, 429, 500)
TOKEN_RE = re.compile(r"/bot[^/\s?]*")


class State:
    """Всё изменяемое состояние службы; одна блокировка и одно условие ожидания на всё."""

    def __init__(self):
        self.cond = threading.Condition()
        self.reset()

    def reset(self):
        with self.cond:
            self.tg_updates = []      # события Telegram с update_id
            self.tg_next_id = 1
            self.max_updates = []     # (seq, событие) ещё не подтверждённые
            self.max_next_seq = 1     # marker = номер следующего будущего события
            self.sent = {"telegram": [], "max": []}
            self.fails = []           # {"channel","method","status","count","retry_after"}
            self.tg_msg_id = 0
            self.max_msg_id = 0
            self.cond.notify_all()


STATE = State()


def tg_error(status, description, retry_after=None):
    body = {"ok": False, "error_code": status, "description": description}
    if retry_after is not None:
        body["parameters"] = {"retry_after": retry_after}
    return status, body


def max_error(status, code, message):
    return status, {"code": code, "message": message}


def injected_error(channel, method):
    """Если для метода заказан сбой — вернуть (status, body, retry_after), иначе None."""
    with STATE.cond:
        for item in STATE.fails:
            if item["channel"] == channel and item["method"] in (method, "*") and item["count"] > 0:
                item["count"] -= 1
                status, ra = item["status"], item["retry_after"]
                break
        else:
            return None
    if channel == "telegram":
        text = {
            401: "Unauthorized",
            403: "Forbidden: bot was blocked by the user",
            409: "Conflict: terminated by other getUpdates request; make sure that only one bot instance is running",
            429: "Too Many Requests: retry after %d" % ra,
            500: "Internal Server Error",
        }[status]
        st, body = tg_error(status, text, ra if status == 429 else None)
    else:
        code, text = {
            401: ("verify.token", "Invalid access_token"),
            403: ("chat.denied", "Bot has no access to this chat"),
            409: ("conflict", "Conflict"),
            429: ("too.many.requests", "Too many requests"),
            500: ("internal.error", "Internal server error"),
        }[status]
        st, body = max_error(status, code, text)
    return st, body, (ra if status == 429 else None)


def as_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def wait_for(predicate, timeout):
    """Ждать под STATE.cond (вызывать с захваченным замком) до timeout секунд, пока predicate() ложно."""
    deadline = time.monotonic() + timeout
    while not predicate():
        left = deadline - time.monotonic()
        if left <= 0:
            return False
        STATE.cond.wait(left)
    return True


# ---------------------------------------------------------------- Telegram

def tg_get_updates(params):
    offset = as_int(params.get("offset"))
    timeout = min(max(as_int(params.get("timeout"), 0), 0), TG_MAX_TIMEOUT)
    limit = min(max(as_int(params.get("limit"), 100), 1), 100)
    allowed = params.get("allowed_updates")
    if isinstance(allowed, str):
        try:
            allowed = json.loads(allowed) if allowed else None
        except ValueError:
            allowed = None
    if not isinstance(allowed, list) or not allowed:
        allowed = None

    def pick():
        found = [u for u in STATE.tg_updates if offset is None or u["update_id"] >= offset]
        if allowed is not None:
            found = [u for u in found if any(k in allowed for k in u if k != "update_id")]
        return found[:limit]

    with STATE.cond:
        if offset is not None:  # всё, что ниже offset, подтверждено
            STATE.tg_updates = [u for u in STATE.tg_updates if u["update_id"] >= offset]
        wait_for(lambda: bool(pick()), timeout)
        return 200, {"ok": True, "result": pick()}


def tg_send_message(params):
    chat_id = params.get("chat_id")
    text = params.get("text")
    if chat_id in (None, ""):
        return tg_error(400, "Bad Request: chat_id is empty")
    if not isinstance(text, str) or not text:
        return tg_error(400, "Bad Request: message text is empty")
    now = time.time()
    with STATE.cond:
        STATE.tg_msg_id += 1
        mid = STATE.tg_msg_id
        STATE.sent["telegram"].append({
            "message_id": mid, "chat_id": chat_id, "text": text,
            "parse_mode": params.get("parse_mode"),
            "reply_markup": params.get("reply_markup"),
            "link_preview_options": params.get("link_preview_options"),
            "time": now,
        })
    chat = {"id": chat_id, "type": "private"}
    return 200, {"ok": True, "result": {"message_id": mid, "from": TG_BOT, "chat": chat,
                                         "date": int(now), "text": text}}


def handle_telegram(method, params):
    inj = injected_error("telegram", method)
    if inj:
        return inj
    if method == "getMe":
        res = 200, {"ok": True, "result": TG_BOT}
    elif method == "getUpdates":
        res = tg_get_updates(params)
    elif method == "sendMessage":
        res = tg_send_message(params)
    elif method == "deleteWebhook":
        res = 200, {"ok": True, "result": True}
    else:
        res = tg_error(404, "Not Found")
    return res[0], res[1], None


# ---------------------------------------------------------------- MAX

def max_get_updates(query):
    marker = as_int(query.get("marker"))
    timeout = min(max(as_int(query.get("timeout"), 30), 0), MAX_MAX_TIMEOUT)
    limit = min(max(as_int(query.get("limit"), 100), 1), 1000)
    types = query.get("types")
    types = [t for t in types.split(",") if t] if types else None

    def pick():
        found = [(s, u) for s, u in STATE.max_updates if types is None or u.get("update_type") in types]
        return found[:limit]

    with STATE.cond:
        if marker is not None:  # переданный marker подтверждает всё до него
            STATE.max_updates = [(s, u) for s, u in STATE.max_updates if s >= marker]
        wait_for(lambda: bool(pick()), timeout)
        found = pick()
        # marker ответа — номер следующего события; для пустого ответа — текущий хвост
        new_marker = found[-1][0] + 1 if found else STATE.max_next_seq
        return 200, {"updates": [u for _, u in found], "marker": new_marker}


def max_send_message(query, body):
    chat_id = as_int(query.get("chat_id"))
    user_id = as_int(query.get("user_id"))
    if chat_id is None and user_id is None:
        return max_error(400, "proto.payload", "chat_id or user_id is required")
    text = body.get("text")
    now = time.time()
    with STATE.cond:
        STATE.max_msg_id += 1
        mid = "mid.%d" % STATE.max_msg_id
        STATE.sent["max"].append({
            "message_id": mid, "chat_id": chat_id, "user_id": user_id, "text": text,
            "format": body.get("format"), "attachments": body.get("attachments"),
            "notify": body.get("notify"),
            "disable_link_preview": query.get("disable_link_preview"),
            "time": now,
        })
        seq = STATE.max_msg_id
    message = {
        "sender": {"user_id": MAX_BOT["user_id"], "name": MAX_BOT["name"],
                   "username": MAX_BOT["username"], "is_bot": True},
        "recipient": {"chat_id": chat_id if chat_id is not None else user_id,
                      "chat_type": "dialog", "user_id": user_id},
        "timestamp": int(now * 1000),
        "body": {"mid": mid, "seq": seq, "text": text, "attachments": body.get("attachments")},
    }
    return 200, {"message": message}


def handle_max(method, verb, query, body, authorized):
    if not authorized:
        st, b = max_error(401, "verify.token", "No access token")
        return st, b, None
    inj = injected_error("max", method)
    if inj:
        return inj
    if method == "me" and verb == "GET":
        res = 200, dict(MAX_BOT)
    elif method == "updates" and verb == "GET":
        res = max_get_updates(query)
    elif method == "messages" and verb == "POST":
        res = max_send_message(query, body)
    else:
        res = max_error(404, "not.found", "Not found")
    return res[0], res[1], None


# ---------------------------------------------------------------- служебные адреса

def as_event_list(body):
    if isinstance(body, dict) and isinstance(body.get("updates"), list):
        body = body["updates"]
    if isinstance(body, dict):
        body = [body]
    if not isinstance(body, list) or not all(isinstance(e, dict) for e in body):
        return None
    return body


def handle_test(verb, path, query, body):
    if path == "/_test/health" and verb == "GET":
        return 200, {"ok": True}
    if path == "/_test/telegram/updates" and verb == "POST":
        events = as_event_list(body)
        if events is None:
            return 400, {"ok": False, "description": "ожидается событие или список событий"}
        ids = []
        with STATE.cond:
            for event in events:
                event = dict(event)
                event["update_id"] = STATE.tg_next_id
                ids.append(STATE.tg_next_id)
                STATE.tg_next_id += 1
                STATE.tg_updates.append(event)
            STATE.cond.notify_all()
        return 200, {"ok": True, "update_ids": ids}
    if path == "/_test/max/updates" and verb == "POST":
        events = as_event_list(body)
        if events is None:
            return 400, {"ok": False, "description": "ожидается событие или список событий"}
        with STATE.cond:
            for event in events:
                event = dict(event)
                event.setdefault("timestamp", int(time.time() * 1000))
                STATE.max_updates.append((STATE.max_next_seq, event))
                STATE.max_next_seq += 1
            marker = STATE.max_next_seq
            STATE.cond.notify_all()
        return 200, {"ok": True, "marker": marker}
    if path == "/_test/sent" and verb == "GET":
        channel = (query.get("channel") or "")
        if channel not in ("telegram", "max"):
            return 400, {"ok": False, "description": "channel: telegram или max"}
        with STATE.cond:
            return 200, {"ok": True, "messages": list(STATE.sent[channel])}
    if path == "/_test/fail" and verb == "POST":
        if not isinstance(body, dict):
            return 400, {"ok": False, "description": "ожидается объект"}
        channel, status = body.get("channel"), body.get("status")
        method = str(body.get("method") or "*").lstrip("/")
        if channel not in ("telegram", "max") or status not in FAIL_STATUSES:
            return 400, {"ok": False, "description": "channel telegram|max, status 401|403|409|429|500"}
        count = as_int(body.get("count"), 1)
        retry_after = as_int(body.get("retry_after"), 1)
        with STATE.cond:
            STATE.fails.append({"channel": channel, "method": method, "status": status,
                                "count": count, "retry_after": retry_after})
        return 200, {"ok": True}
    if path == "/_test/reset" and verb == "POST":
        STATE.reset()
        return 200, {"ok": True}
    return 404, {"ok": False, "description": "Not Found"}


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "fakebots"

    def log_message(self, fmt, *args):
        # одна строка на запрос; токены маскируются, тел и строки запроса с параметрами нет
        line = "%s %s" % (self.address_string(), fmt % args)
        sys.stderr.write(TOKEN_RE.sub("/bot***", line) + "\n")

    def log_request(self, code="-", size="-"):
        path = TOKEN_RE.sub("/bot***", urlsplit(self.path).path)
        sys.stderr.write("%s %s %s\n" % (self.command, path, code))

    def _read_body(self):
        length = as_int(self.headers.get("Content-Length"), 0)
        raw = self.rfile.read(length) if length > 0 else b""
        if not raw.strip():
            return {}
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if ctype == "application/x-www-form-urlencoded":
            return {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace")).items()}
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return None

    def _reply(self, status, body, retry_after=None):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if retry_after is not None:
            self.send_header("Retry-After", str(retry_after))
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, verb):
        parts = urlsplit(self.path)
        path = parts.path
        query = {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
        body = self._read_body()
        if path.startswith("/_test/"):
            if body is None:
                return self._reply(400, {"ok": False, "description": "тело не JSON"})
            return self._reply(*handle_test(verb, path, query, body))
        if path == "/max" or path.startswith("/max/"):
            if body is None:
                return self._reply(*max_error(400, "proto.payload", "Invalid JSON"))
            method = path[len("/max"):].strip("/")
            authorized = bool((self.headers.get("Authorization") or "").strip())
            return self._reply(*handle_max(method, verb, query, body if isinstance(body, dict) else {},
                                           authorized))
        m = re.fullmatch(r"/bot([^/]+)/([A-Za-z]+)", unquote(path))
        if m:
            if body is None:
                return self._reply(*tg_error(400, "Bad Request: can't parse JSON"))
            params = dict(query)
            if isinstance(body, dict):
                params.update(body)
            return self._reply(*handle_telegram(m.group(2), params))
        return self._reply(404, {"ok": False, "error_code": 404, "description": "Not Found"})

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64


def make_server(host="0.0.0.0", port=None):
    if port is None:
        port = int(os.environ.get("FAKEBOTS_PORT", "8099"))
    return Server((host, port), Handler)


if __name__ == "__main__":
    srv = make_server()
    print("fakebots слушает порт %d" % srv.server_address[1], flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
