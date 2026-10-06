"""T-3133: общие правила страниц среза 003 (FR-236, FR-241, FR-275, NFR-207, NFR-208, NFR-214).

Сценарии 1–15 спеки (страницы формы, списка, карточки и настроек). Перечень страниц — маршруты GET из таблиц 12.1–12.6
контракта (13, строка 1689). Страницы, которые по контракту всегда отдаются фрагментом (`/tickets/count/`, подсказки,
диалоги), в перечень полных страниц не входят: для них проверяется только отсутствие встроенных скриптов.
Имена кода среза 003 импортируются внутри тестов; помощники разметки и мира тестов лежат в этом файле.
"""
import re
import uuid
from datetime import datetime, timezone as dt_timezone
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from tests import support, support_org, support_servicedesk as sd
from tests.support import HX, model

pytestmark = pytest.mark.django_db

MOSCOW = ZoneInfo("Europe/Moscow")
HX_GRID = {**HX, "HTTP_HX_TARGET": "tickets-grid"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
N_VISIBLE, N_FOREIGN, N_VISIBLE_2, N_MISSING = 4001, 4002, 4003, 987654
PAYLOAD = "<script>alert(1)</script><b>жирный</b>\n<img src=x onerror=alert(2)>"


# --- разметка (как в test_org_permissions) ------------------------------------------------------------

class Node:
    def __init__(self, tag, attrs, parent=None):
        self.tag, self.attrs, self.parent, self.children, self.chunks = tag, dict(attrs), parent, [], []

    def walk(self):
        for child in self.children:
            yield child
            yield from child.walk()

    def find_all(self, tag=None, **attrs):
        """Потомки с тегом `tag` и атрибутами (`True` — атрибут есть, строка — равен ей); дефисы пишутся как `_`."""
        wanted = {key.replace("_", "-"): value for key, value in attrs.items()}
        return [n for n in self.walk() if (tag is None or n.tag == tag)
                and all((k in n.attrs) if v is True else n.attrs.get(k) == v for k, v in wanted.items())]

    def text(self) -> str:
        return " ".join(("".join(self.chunks) + " " + " ".join(c.text() for c in self.children)).split())


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root", {})
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.current)
        self.current.children.append(node)
        if tag not in VOID_TAGS:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(Node(tag, {k: (v or "") for k, v in attrs}, self.current))

    def handle_endtag(self, tag):
        node = self.current
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.current = node.parent

    def handle_data(self, data):
        self.current.chunks.append(data)


def html_of(response) -> str:
    return response.content.decode("utf-8", "replace")


def dom(response_or_html) -> Node:
    builder = _Builder()
    builder.feed(response_or_html if isinstance(response_or_html, str) else html_of(response_or_html))
    return builder.root


def is_full_page(response) -> bool:
    return bool(re.search(r"<html[\s>]", html_of(response), re.I))


def shape(response, numbers=()) -> tuple:
    """Вид ответа для сравнения «недоступная = несуществующая»: статус, адрес перехода, тело без токена CSRF и номеров."""
    body = re.sub(r'name="csrfmiddlewaretoken" value="[^"]*"', "", html_of(response))
    for number in numbers:
        body = body.replace(str(number), "NNN")
    return response.status_code, response.get("Location", ""), re.sub(r"\s+", " ", body)


# --- мир теста ---------------------------------------------------------------------------------------

def _world(*, with_files: bool = False) -> SimpleNamespace:
    """Две очереди, три заявки, сотрудники: `viewer` (участник A), `nobody` (ничего), `manager` (`servicedesk.manage`),
    `all_holder` (все права срезов 001–002 и «Все заявки», но не «Настройка сервис-деска»)."""
    model("core.PortalSettings").objects.update(name="Портал ИТ-отдела")
    qa = sd.make_queue(support_org.make_unit("Очередь А"))  # кириллические названия: проверка «нет латиницы» не на случайных данных
    qb = sd.make_queue(support_org.make_unit("Очередь Б"))
    sd.configure_servicedesk(domains=["corp.example"], default_queue=qa)
    category = sd.make_category("Принтеры", queue=qa, on_form=True)
    viewer = support.make_with_permissions()
    support_org.make_member(viewer, qa.unit)
    nobody = support.make_with_permissions()
    manager = support.make_with_permissions("servicedesk.manage")
    all_holder = support.make_with_permissions(*support.PERMISSIONS, *support.PERMISSIONS_002, "servicedesk.all")
    requester = sd.make_requester(full_name="Иван Петров")
    t_visible = sd.make_ticket(queue=qa, requester=requester, number=N_VISIBLE, subject="Не печатает принтер",
                               last_message_from="requester")
    t_foreign = sd.make_ticket(queue=qb, requester=requester, number=N_FOREIGN, subject="Сломался сервер",
                               last_message_from="requester")
    t_visible_2 = sd.make_ticket(queue=qa, requester=requester, number=N_VISIBLE_2, subject="Нужен доступ")
    w = SimpleNamespace(qa=qa, qb=qb, category=category, viewer=viewer, nobody=nobody, manager=manager,
                        all_holder=all_holder, requester=requester, t_visible=t_visible, t_foreign=t_foreign,
                        t_visible_2=t_visible_2, high=model("servicedesk.Priority").objects.get(name_key="высокая"))
    for ticket in (t_visible, t_foreign):
        sd.make_entry(ticket, "incoming", text="Текст письма")
        sd.make_entry(ticket, "reply", author=viewer, text="Ответ исполнителя", send_state="queued")
        sd.make_entry(ticket, "comment", author=viewer, text="Внутренняя заметка")
    w.participant_visible = sd.make_participant(t_visible)
    w.participant_foreign = sd.make_participant(t_foreign)
    w.reply_foreign = ticket_entry(t_foreign, "reply")
    w.reply_visible = ticket_entry(t_visible, "reply")
    w.requester_import = model("servicedesk.RequesterImport").objects.create(
        created_by=manager, created_at=timezone.now(), file_name="заявители.csv", file_format="csv", state="preview",
        delete_missing=False, rows=[], summary={"added": 0, "updated": 0, "unchanged": 0, "errors": 0, "deleted": 0},
        new_units=[])
    return w


def ticket_entry(ticket, kind):
    return model("servicedesk.TicketEntry").objects.filter(ticket=ticket, kind=kind).first()


def _full_pages(w) -> dict:
    """Полные страницы среза (GET без НХ), по одному ответу на путь: путь -> ответ. Каждый ответ — 200."""
    from apps.servicedesk.services import form

    anon = support.make_client()
    pages = {"/request/": anon.get("/request/")}
    session = anon.session
    form.remember_done(session, "ivan@corp.example")
    session.save()
    pages["/request/done/"] = anon.get("/request/done/")
    viewer = support.logged_in(w.viewer)
    for path in ("/tickets/", "/tickets/?preset=all", "/tickets/new/", f"/tickets/{N_VISIBLE}/"):
        pages[path] = viewer.get(path)
    manager = support.logged_in(w.manager)
    paths = ["/servicedesk/", "/servicedesk/queues/", f"/servicedesk/queues/?unmark={w.qb.unit_id}",
             "/servicedesk/requesters/", "/servicedesk/requesters/import/",
             f"/servicedesk/requesters/import/{w.requester_import.pk}/", "/servicedesk/inbound/"]
    paths += [f"/servicedesk/dictionaries/{kind}/" for kind in
              ("categories", "priorities", "complexities", "statuses", "sources", "client-units")]
    for path in paths:
        pages[path] = manager.get(path)
    for path, response in pages.items():
        assert response.status_code == 200, f"{path}: {response.status_code}"
    return pages


def _fragments(w) -> dict:
    """Ответы, которые по контракту всегда фрагмент (или запрос НХ): путь -> ответ (для проверки встроенных скриптов)."""
    viewer = support.logged_in(w.viewer)
    base = f"/tickets/{N_VISIBLE}"
    out = {
        "/tickets/count/": viewer.get("/tickets/count/"),
        "/tickets/new/queue/": viewer.get(f"/tickets/new/queue/?category={w.category.pk}", **HX),
        f"{base}/ HX": viewer.get(f"{base}/", **HX),
        f"{base}/assignees/": viewer.get(f"{base}/assignees/?q=а", **HX),
        f"{base}/transfer/": viewer.get(f"{base}/transfer/", **HX),
        f"{base}/close/": viewer.get(f"{base}/close/", **HX),
        f"{base}/participants/remove/": viewer.get(f"{base}/participants/{w.participant_visible.pk}/remove/", **HX),
        "/tickets/ HX grid": viewer.get("/tickets/", **HX_GRID),
        "/tickets/ HX": viewer.get("/tickets/", **HX),
    }
    out["/servicedesk/queues/ HX"] = support.logged_in(w.manager).get("/servicedesk/queues/", **HX)
    return out


# --- NFR-207: русский язык и время по Москве ---------------------------------------------------------

def test_every_slice_page_is_russian():
    """NFR-207: у каждой страницы среза `<html lang="ru">`, а в `<title>`, `h1` и подписях `button` нет латинских слов."""
    w = _world()
    for path, response in _full_pages(w).items():
        tree = dom(response)
        roots = tree.find_all("html")
        assert roots and roots[0].attrs.get("lang") == "ru", f"{path}: нет <html lang=\"ru\">"
        parts = [n.text() for tag in ("title", "h1", "button") for n in tree.find_all(tag)]
        assert any(n.text() for n in tree.find_all("title")), f"{path}: пустой <title>"
        for text in parts:
            assert not re.search(r"[A-Za-z]{2,}", text), f"{path}: латинское слово в заголовке или кнопке: {text!r}"


def test_slice_pages_show_time_in_moscow():
    """NFR-207: каждый `time[data-at]` на страницах среза — `ДД.ММ.ГГГГ ЧЧ:ММ` по Москве, равный `data-at` в поясе портала."""
    w = _world()
    instant = datetime(2026, 3, 10, 22, 30, tzinfo=dt_timezone.utc)  # в Москве уже 11.03.2026 01:30
    expected = "11.03.2026 01:30"
    assert instant.astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M") == expected
    for ticket in (w.t_visible,):
        type(ticket).objects.filter(pk=ticket.pk).update(created_at=instant, last_message_at=instant)
    model("servicedesk.TicketEntry").objects.filter(ticket=w.t_visible).update(at=instant)
    inbound = sd.make_inbound(ticket=w.t_visible, status="processed", outcome="appended")
    type(inbound).objects.filter(pk=inbound.pk).update(received_at=instant)
    viewer, manager = support.logged_in(w.viewer), support.logged_in(w.manager)
    responses = {
        "/tickets/?preset=all": viewer.get("/tickets/?preset=all"),
        f"/tickets/{N_VISIBLE}/": viewer.get(f"/tickets/{N_VISIBLE}/"),
        f"/tickets/{N_VISIBLE}/ HX": viewer.get(f"/tickets/{N_VISIBLE}/", **HX),
        "/servicedesk/inbound/": manager.get("/servicedesk/inbound/"),
    }
    for path, response in responses.items():
        assert response.status_code == 200, f"{path}: {response.status_code}"
        times = dom(response).find_all("time", **{"data-at": True})
        if path != "/servicedesk/inbound/":
            assert times, f"{path}: нет ни одного time[data-at]"
            assert expected in {t.text() for t in times}, f"{path}: нет времени {expected} (Москва), есть {[t.text() for t in times]}"
        for node in times:
            shown = node.text()
            assert re.fullmatch(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}", shown), f"{path}: формат времени {shown!r}"
            moment = datetime.fromisoformat(node.attrs["data-at"])
            assert moment.tzinfo is not None, f"{path}: в data-at нет пояса"
            assert moment.astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M") == shown, (
                f"{path}: текст {shown!r} не равен data-at={node.attrs['data-at']!r} по Москве")


# --- NFR-208: узкая ширина и фрагменты ---------------------------------------------------------------

def test_slice_pages_have_viewport_meta_for_360px():
    """NFR-208: на каждой полной странице среза есть `<meta name="viewport">` с шириной устройства (360 px)."""
    w = _world()
    for path, response in _full_pages(w).items():
        metas = [m for m in dom(response).find_all("meta", name="viewport")]
        assert metas, f"{path}: нет <meta name=\"viewport\">"
        assert "width=device-width" in metas[0].attrs.get("content", ""), f"{path}: {metas[0].attrs}"


def test_slice_pages_use_narrow_width_classes():
    """NFR-208: список заявок несёт признаки узкой раскладки: `#tickets-grid[data-narrow="cards"]`, `details[data-filter-panel]`;
    `<meta name="viewport">` — на всех страницах перечня (контракт 13, строка 1690)."""
    w = _world()
    pages = _full_pages(w)
    for path in ("/tickets/", "/tickets/?preset=all"):
        tree = dom(pages[path])
        grids = tree.find_all(id="tickets-grid")
        assert len(grids) == 1 and grids[0].attrs.get("data-narrow") == "cards", f"{path}: нет #tickets-grid[data-narrow=cards]"
        panels = tree.find_all("details", **{"data-filter-panel": True})
        assert panels, f"{path}: нет details[data-filter-panel]"
        assert panels[0].find_all("form", id="tickets-filter"), f"{path}: фильтр не внутри details[data-filter-panel]"
    grid_only = support.logged_in(w.viewer).get("/tickets/", **HX_GRID)
    grids = dom(grid_only).find_all(id="tickets-grid")
    assert grids and grids[0].attrs.get("data-narrow") == "cards", "сетка при подмене через НХ потеряла data-narrow"
    for path, response in pages.items():
        assert dom(response).find_all("meta", name="viewport"), f"{path}: нет <meta name=\"viewport\">"


def test_open_form_has_viewport_and_narrow_markup():
    """NFR-208: открытая форма `/request/` — своя страница без меню с `<meta name="viewport">`, `<html lang="ru">`; все поля формы
    лежат в одной `form[data-form="request"]`."""
    w = _world()
    for client in (support.make_client(), support.logged_in(w.viewer)):
        response = client.get("/request/")
        assert response.status_code == 200
        tree = dom(response)
        metas = tree.find_all("meta", name="viewport")
        assert metas and "width=device-width" in metas[0].attrs.get("content", "")
        assert tree.find_all("html")[0].attrs.get("lang") == "ru"
        assert not tree.find_all(id="main-menu"), "на открытой форме есть левое меню"
        forms = tree.find_all("form", **{"data-form": "request"})
        assert len(forms) == 1
        for field in ("email", "name", "client_unit", "category", "subject", "text", "files", "consent"):
            assert forms[0].find_all(name=field), f"поле {field} вне form[data-form=request]"


def test_htmx_request_returns_fragment_without_base_layout():
    """NFR-208: запрос НХ — фрагмент без `<html>` и меню; `HX-Target: tickets-grid` — только сетка; карточка — слайдер."""
    w = _world()
    viewer = support.logged_in(w.viewer)
    grid_only = viewer.get("/tickets/", **HX_GRID)
    assert grid_only.status_code == 200 and not is_full_page(grid_only)
    tree = dom(grid_only)
    assert tree.find_all(id="tickets-grid"), "в ответе на подмену сетки нет #tickets-grid"
    assert not tree.find_all("nav", **{"data-presets": True}) and not tree.find_all("form", id="tickets-filter"), (
        "при HX-Target tickets-grid ответ содержит панель фильтра или пресеты")
    other = viewer.get("/tickets/", **HX)
    assert other.status_code == 200 and not is_full_page(other) and not dom(other).find_all(id="main-menu")
    assert dom(other).find_all(**{"data-tickets-list": True}), "прочий запрос НХ: нет страницы списка без базового шаблона"
    card = viewer.get(f"/tickets/{N_VISIBLE}/", **HX)
    assert card.status_code == 200 and not is_full_page(card)
    tree = dom(card)
    assert any("slider-panel" in n.attrs.get("class", "").split() for n in tree.walk()), "нет .slider-panel"
    assert tree.find_all(**{"data-ticket-card": True, "data-layout": "slider"})
    new_form = viewer.get("/tickets/new/", **HX)
    assert new_form.status_code == 200 and not is_full_page(new_form)
    manager = support.logged_in(w.manager)
    for path in ("/servicedesk/queues/", "/servicedesk/requesters/", "/servicedesk/inbound/",
                 "/servicedesk/dictionaries/categories/"):
        response = manager.get(path, **HX)
        assert response.status_code == 200 and not is_full_page(response), f"{path}: НХ вернул страницу целиком"


def test_plain_request_returns_full_page():
    """NFR-208: обычный запрос — страница целиком с меню у вошедшего; у открытой формы меню нет; у списка и карточки свои корни."""
    w = _world()
    pages = _full_pages(w)
    for path, response in pages.items():
        assert is_full_page(response), f"{path}: обычный запрос вернул не страницу целиком"
        has_menu = bool(dom(response).find_all(id="main-menu"))
        assert has_menu == (not path.startswith("/request/")), f"{path}: меню {'есть' if has_menu else 'нет'}"
    tree = dom(pages["/tickets/"])
    assert tree.find_all("nav", **{"data-presets": True}) and tree.find_all("form", id="tickets-filter")
    assert tree.find_all("form", id="tickets-bulk") and tree.find_all(id="tickets-grid")
    card = dom(pages[f"/tickets/{N_VISIBLE}/"])
    assert card.find_all(**{"data-ticket-card": True, "data-layout": "page"}), "прямой адрес карточки: нет [data-layout=page]"
    menu_links = {n.attrs.get("href") for n in dom(pages["/tickets/"]).find_all("a") if "menu-item" in n.attrs.get("class", "")}
    assert "/tickets/" in menu_links
    manager_links = {n.attrs.get("href") for n in dom(pages["/servicedesk/"]).find_all("a")
                     if "menu-item" in n.attrs.get("class", "")}
    assert "/servicedesk/" in manager_links


# --- FR-275, FR-236: отказы ---------------------------------------------------------------------------

def _manage_requests(w, ids) -> list:
    """Маршруты `/servicedesk/…` из таблицы 12.6: (метод, путь, данные). `ids` — существующие и несуществующие номера."""
    cat, miss = ids.category, ids.missing
    req, imp, inbound = ids.requester, ids.requester_import, ids.inbound
    kinds = ("categories", "priorities", "complexities", "statuses", "sources", "client-units")
    out = [("GET", "/servicedesk/", {}), ("POST", "/servicedesk/", {"autoclose_days": "5"}),
           ("GET", "/servicedesk/queues/", {}), ("GET", f"/servicedesk/queues/?unmark={w.qb.unit_id}", {}),
           ("POST", "/servicedesk/queues/", {"action": "mark", "unit": w.qb.unit_id}),
           ("POST", "/servicedesk/queues/", {"action": "unmark", "unit": w.qb.unit_id, "confirm": "1"}),
           ("GET", "/servicedesk/dictionaries/bogus/", {}), ("GET", "/servicedesk/dictionaries/categories/new/", {}),
           ("POST", "/servicedesk/dictionaries/categories/new/", {"name": "Новая", "queue": w.qa.unit_id}),
           ("GET", "/servicedesk/requesters/", {}), ("GET", "/servicedesk/requesters/?q=ivan", {}),
           ("GET", "/servicedesk/requesters/import/", {}), ("POST", "/servicedesk/requesters/import/", {}),
           ("GET", "/servicedesk/requesters/import/sample.csv", {}), ("GET", "/servicedesk/requesters/import/sample.xlsx", {}),
           ("GET", f"/servicedesk/requesters/import/{imp}/", {}), ("POST", f"/servicedesk/requesters/import/{imp}/", {}),
           ("GET", "/servicedesk/inbound/", {}), ("GET", "/servicedesk/inbound/?count=1", {}),
           ("POST", f"/servicedesk/inbound/{inbound}/retry/", {}), ("POST", f"/servicedesk/inbound/{miss}/retry/", {})]
    out += [("GET", f"/servicedesk/dictionaries/{kind}/", {}) for kind in kinds]
    for number in (cat, miss):
        base = f"/servicedesk/dictionaries/categories/{number}"
        out += [("GET", f"{base}/edit/", {}), ("POST", f"{base}/edit/", {"name": "Другое имя"}),
                ("POST", f"{base}/archive/", {}), ("POST", f"{base}/restore/", {}),
                ("GET", f"{base}/delete/", {}), ("POST", f"{base}/delete/", {"confirm": "1"})]
    for number in (req, miss):
        base = f"/servicedesk/requesters/{number}"
        out += [("GET", f"{base}/edit/", {}), ("POST", f"{base}/edit/", {"name": "Иван"}),
                ("GET", f"{base}/delete/", {}), ("POST", f"{base}/delete/", {"confirm": "1"})]
    return out


def test_manage_routes_return_403_without_permission():
    """FR-275: все маршруты `/servicedesk/…` без права «Настройка сервис-деска» дают 403 (в том числе для несуществующего
    номера, неизвестного вида справочника и запроса НХ), без входа — 302 на `/login/`, и ничего не меняют."""
    w = _world()
    inbound = sd.make_inbound()
    ids = SimpleNamespace(category=w.category.pk, requester=w.requester.pk, missing=N_MISSING, inbound=inbound.pk,
                         requester_import=w.requester_import.pk)
    requests = _manage_requests(w, ids)
    counts = lambda: tuple(model(m).objects.count() for m in  # noqa: E731
                           ("servicedesk.Queue", "servicedesk.Category", "servicedesk.Requester", "servicedesk.InboundMail"))
    before = counts()
    settings_before = list(model("servicedesk.ServiceDeskSettings").objects.values())
    for label, user in (("без прав", w.nobody), ("«Все заявки» и права срезов 001–002", w.all_holder)):
        client = support.logged_in(user)
        for method, path, data in requests:
            for headers in ({}, HX):
                response = getattr(client, method.lower())(path, data, **headers) if method == "POST" else client.get(path, **headers)
                assert response.status_code == 403, f"{label}: {method} {path} {headers}: {response.status_code}, ждали 403"
    anonymous = support.make_client()
    for method, path, data in requests:
        response = anonymous.post(path, data) if method == "POST" else anonymous.get(path)
        assert response.status_code == 302 and response["Location"].startswith("/login/"), (
            f"без входа: {method} {path}: {response.status_code} {response.get('Location')}")
    assert counts() == before, "отказанные запросы изменили данные"
    assert list(model("servicedesk.ServiceDeskSettings").objects.values()) == settings_before
    manager = support.logged_in(w.manager)
    assert manager.get("/servicedesk/").status_code == 200 and manager.get("/servicedesk/requesters/").status_code == 200


def _foreign_cases(w):
    """Пары (кто, заявка вне его видимости, ещё заявка, которую он видит или `None`)."""
    return [("участник очереди A", w.viewer, support.logged_in(w.viewer), w.t_foreign, w.t_visible),
            ("сотрудник без очередей", w.nobody, support.logged_in(w.nobody), w.t_visible, None)]


def test_inaccessible_ticket_card_returns_404_same_as_missing():
    """FR-236: карточка недоступной заявки отвечает так же, как несуществующая (404, одно и то же тело, не 403 и не
    переход), и для обычного запроса, и для НХ; своя заявка открывается; без входа — 302 на `/login/`."""
    w = _world()
    for label, _actor, client, foreign, own in _foreign_cases(w):
        for headers in ({}, HX):
            hidden = client.get(f"/tickets/{foreign.number}/", **headers)
            missing = client.get(f"/tickets/{N_MISSING}/", **headers)
            assert hidden.status_code == 404, f"{label} {headers}: {hidden.status_code}"
            assert missing.status_code == 404
            assert shape(hidden, (foreign.number, N_MISSING)) == shape(missing, (foreign.number, N_MISSING)), (
                f"{label} {headers}: ответы на недоступную и несуществующую заявку различаются")
            assert foreign.subject not in html_of(hidden), "в отказе есть тема чужой заявки"
        if own is not None:
            assert client.get(f"/tickets/{own.number}/").status_code == 200
    response = support.make_client().get(f"/tickets/{N_FOREIGN}/")
    assert response.status_code == 302 and response["Location"].startswith("/login/")


def _ticket_requests(w, actor, ticket):
    """Маршруты `/tickets/<номер>/…` из 12.4: (метод, окончание адреса после номера, данные)."""
    entry = ticket_entry(ticket, "reply")
    participant = ticket.participants.first()
    closed = model("servicedesk.Status").objects.get(kind="closed", is_default=True)
    in_progress = model("servicedesk.Status").objects.get(kind="in_progress", is_default=True)
    return [
        ("GET", "assignees/?q=а", {}), ("GET", "transfer/", {}), ("GET", "close/", {}),
        ("GET", f"participants/{participant.pk}/remove/", {}),
        ("POST", "take/", {}), ("POST", "assign/", {"assignee": actor.pk}),
        ("POST", "transfer/", {"queue": w.qb.unit_id, "reason": "проверка"}),
        ("POST", "category/", {"category": w.category.pk, "confirm": "1"}),
        ("POST", "fields/", {"priority": w.high.pk}), ("POST", "status/", {"status": in_progress.pk}),
        ("POST", "reply/", {"text": "ответ"}), ("POST", f"reply/{entry.pk}/resend/", {}),
        ("POST", "comment/", {"text": "заметка"}), ("POST", "close/", {"status": closed.pk, "resolution": "решено"}),
        ("POST", "reopen/", {}), ("POST", f"participants/{participant.pk}/remove/", {"confirm": "1"}),
    ]


def _snapshot(ticket):
    return (list(type(ticket).objects.filter(pk=ticket.pk).values()),
            list(model("servicedesk.TicketEntry").objects.order_by("id").values_list("id", "ticket_id", "kind", "text")),
            list(model("servicedesk.TicketParticipant").objects.order_by("id").values_list("id", "removed_at")),
            model("mail.MailMessage").objects.count())


def test_inaccessible_ticket_actions_return_404_same_as_missing():
    """FR-236: каждое действие над недоступной заявкой (все маршруты 12.4, GET и POST, в том числе с чужими номерами элемента
    ленты и участника) даёт тот же 404, что и несуществующая заявка, раньше проверки прав и полей; заявка не меняется;
    у видимой заявки чужой элемент ленты и чужой участник — тоже 404 (дополнение 2, п. 4), ничего не меняется."""
    w = _world()
    for label, actor, client, foreign, _own in _foreign_cases(w):
        before = _snapshot(foreign)
        for headers in ({}, HX):
            for method, tail, data in _ticket_requests(w, actor, foreign):
                call = (lambda path: client.post(path, data, **headers)) if method == "POST" else (
                    lambda path: client.get(path, **headers))
                hidden = call(f"/tickets/{foreign.number}/{tail}")
                missing = call(f"/tickets/{N_MISSING}/{tail}")
                where = f"{label}: {method} {tail} {headers}"
                assert hidden.status_code == 404, f"{where}: {hidden.status_code}, ждали 404 (403 здесь не бывает)"
                assert shape(hidden, (foreign.number, N_MISSING)) == shape(missing, (foreign.number, N_MISSING)), (
                    f"{where}: ответ на недоступную заявку отличается от ответа на несуществующую")
        assert _snapshot(foreign) == before, f"{label}: отказанные действия изменили заявку, ленту, участников или письма"
    viewer = support.logged_in(w.viewer)
    own_before = (_snapshot(w.t_visible), _snapshot(w.t_foreign))
    for headers in ({}, HX):
        for tail, data in ((f"reply/{w.reply_foreign.pk}/resend/", {}),
                           (f"participants/{w.participant_foreign.pk}/remove/", {"confirm": "1"})):
            response = viewer.post(f"/tickets/{N_VISIBLE}/{tail}", data, **headers)
            assert response.status_code == 404, f"видимая заявка, чужой объект: POST {tail} {headers}: {response.status_code}"
        response = viewer.get(f"/tickets/{N_VISIBLE}/participants/{w.participant_foreign.pk}/remove/", **headers)
        assert response.status_code == 404, f"видимая заявка, чужой участник: GET {headers}: {response.status_code}"
    assert (_snapshot(w.t_visible), _snapshot(w.t_foreign)) == own_before, "чужие номера объектов изменили данные"
    for path in (f"/tickets/{N_FOREIGN}/take/", f"/tickets/{N_FOREIGN}/comment/"):
        response = support.make_client().post(path, {"text": "x"})
        assert response.status_code == 302 and response["Location"].startswith("/login/")


def test_inaccessible_attachment_and_source_email_return_404_same_as_missing(protected_root):
    """FR-236: вложение и исходное письмо недоступной заявки (и вложение или письмо чужой заявки в адресе своей) дают тот же
    404, что и несуществующие; у видящего чистое вложение и письмо выдаются через `X-Accel-Redirect`."""
    from apps.core.services import files

    w = _world()
    StoredFile, Attachment, Entry = model("core.StoredFile"), model("servicedesk.Attachment"), model("servicedesk.TicketEntry")
    stored, inbounds = {}, {}
    for key, ticket in (("own", w.t_visible), ("foreign", w.t_foreign)):
        entry = ticket_entry(ticket, "incoming")
        file = StoredFile.objects.create(purpose="attachment", owner=None, size=5, sha256="0" * 64,
                                         content_type="text/plain", status="clean")
        path = files.attachment_path(file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"12345")
        Attachment.objects.create(ticket=ticket, entry=entry, file=file, name=f"{key}.txt", size=5, rejected="",
                                  created_at=timezone.now())
        mail = sd.make_inbound(ticket=ticket, status="processed", outcome="appended")
        Entry.objects.filter(pk=entry.pk).update(inbound=mail)
        raw = Path(str(protected_root)) / "inbound" / f"{mail.pk}.eml"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(b"Subject: x\r\n\r\ntext")
        stored[key], inbounds[key] = file, mail
    viewer = support.logged_in(w.viewer)
    ok = viewer.get(f"/tickets/{N_VISIBLE}/files/{stored['own'].pk}/")
    assert ok.status_code == 200 and ok["X-Accel-Redirect"] == f"/protected/attachments/{stored['own'].pk}"
    ok_mail = viewer.get(f"/tickets/{N_VISIBLE}/mail/{inbounds['own'].pk}.eml")
    assert ok_mail.status_code == 200 and ok_mail["X-Accel-Redirect"] == f"/protected/inbound/{inbounds['own'].pk}.eml"
    nobody = support.logged_in(w.nobody)
    cases = [("участник A, чужая заявка", viewer, N_FOREIGN, "foreign"), ("без очередей, заявка A", nobody, N_VISIBLE, "own"),
             ("участник A, свой номер, файл и письмо чужой заявки", viewer, N_VISIBLE, "foreign")]
    for label, client, number, key in cases:
        for kind, tail, missing_tail in (
                ("файл", f"files/{stored[key].pk}/", f"files/{uuid.uuid4()}/"),
                ("письмо", f"mail/{inbounds[key].pk}.eml", f"mail/{inbounds[key].pk + 100000}.eml")):
            got = client.get(f"/tickets/{number}/{tail}")
            absent_ticket = client.get(f"/tickets/{N_MISSING}/{tail}")
            absent_object = client.get(f"/tickets/{number}/{missing_tail}")
            assert got.status_code == 404, f"{label}: {kind}: {got.status_code}, ждали 404"
            numbers = (N_FOREIGN, N_VISIBLE, N_MISSING)
            assert shape(got, numbers) == shape(absent_ticket, numbers), f"{label}: {kind}: отличается от несуществующей заявки"
            assert shape(got, numbers) == shape(absent_object, numbers), f"{label}: {kind}: отличается от несуществующего объекта"
            assert "X-Accel-Redirect" not in got


def test_requester_record_without_manage_right_same_403_for_existing_and_missing_id():
    """FR-236: без права «Настройка сервис-деска» страницы записи заявителя дают один и тот же 403 для существующего и
    несуществующего номера; с правом существующая открывается (200), несуществующая — 404; запись цела."""
    w = _world()
    existing, missing = w.requester.pk, N_MISSING
    before = list(model("servicedesk.Requester").objects.values())
    for label, user in (("без прав", w.nobody), ("«Все заявки»", w.all_holder)):
        client = support.logged_in(user)
        for suffix, method, data in (("edit/", "GET", {}), ("edit/", "POST", {"name": "Взлом"}),
                                     ("delete/", "GET", {}), ("delete/", "POST", {"confirm": "1"})):
            call = (lambda n: client.post(f"/servicedesk/requesters/{n}/{suffix}", data)) if method == "POST" else (
                lambda n: client.get(f"/servicedesk/requesters/{n}/{suffix}"))
            first, second = call(existing), call(missing)
            assert first.status_code == 403, f"{label}: {method} {suffix}: {first.status_code}"
            assert support.same_failure(first, second) or shape(first, (existing, missing)) == shape(second, (existing, missing)), (
                f"{label}: {method} {suffix}: ответы для существующей и несуществующей записи различаются")
    assert list(model("servicedesk.Requester").objects.values()) == before
    manager = support.logged_in(w.manager)
    assert manager.get(f"/servicedesk/requesters/{existing}/edit/").status_code == 200
    assert manager.get(f"/servicedesk/requesters/{missing}/edit/").status_code == 404
    assert manager.get(f"/servicedesk/requesters/{missing}/delete/").status_code == 404


def test_bulk_action_skips_inaccessible_tickets_with_explanation_and_applies_to_accessible(django_capture_on_commit_callbacks):
    """FR-236, FR-241: групповое действие применяется к доступным заявкам, недоступную пропускает с объяснением «нет доступа»
    без её номера и тем, что она не изменилась; итог «Выполнено: N; пропущено: M» — в `[data-bulk-result]`."""
    w = _world()
    viewer = support.logged_in(w.viewer)
    Ticket = model("servicedesk.Ticket")
    foreign_before = list(Ticket.objects.filter(pk=w.t_foreign.pk).values())
    with django_capture_on_commit_callbacks(execute=True):
        response = viewer.post("/tickets/bulk/", {"action": "assign", "numbers": [N_VISIBLE, N_FOREIGN], "user": w.viewer.pk})
    assert response.status_code == 200 and is_full_page(response), "обычный запрос: ждали страницу списка (решение Opus D2)"
    result = dom(response).find_all(**{"data-bulk-result": True})
    assert len(result) == 1, "нет блока [data-bulk-result]"
    text = result[0].text().lower()
    assert "выполнено: 1" in text and "пропущено: 1" in text, text
    skipped = result[0].find_all("li", **{"data-skipped": True})
    assert len(skipped) == 1 and "нет доступа" in skipped[0].text().lower(), [s.text() for s in skipped]
    assert str(N_FOREIGN) not in result[0].text(), "в итоге назван номер недоступной заявки"
    assert Ticket.objects.get(pk=w.t_visible.pk).assignee_id == w.viewer.pk, "доступная заявка не изменена"
    assert list(Ticket.objects.filter(pk=w.t_foreign.pk).values()) == foreign_before, "недоступная заявка изменена"
    with django_capture_on_commit_callbacks(execute=True):
        fragment = viewer.post("/tickets/bulk/", {"action": "priority", "numbers": [N_VISIBLE_2, N_FOREIGN], "priority": w.high.pk},
                               **HX)
    assert fragment.status_code == 200 and not is_full_page(fragment)
    result = dom(fragment).find_all(**{"data-bulk-result": True})
    assert result, "НХ: нет блока [data-bulk-result]"
    assert "выполнено: 1" in result[0].text().lower() and "пропущено: 1" in result[0].text().lower()
    assert len(result[0].find_all("li", **{"data-skipped": True})) == 1
    assert str(N_FOREIGN) not in result[0].text()
    assert Ticket.objects.get(pk=w.t_visible_2.pk).priority_id == w.high.pk
    assert list(Ticket.objects.filter(pk=w.t_foreign.pk).values()) == foreign_before
    with django_capture_on_commit_callbacks(execute=True):
        nothing = viewer.post("/tickets/bulk/", {"action": "priority", "numbers": [N_FOREIGN], "priority": w.high.pk}, **HX)
    assert nothing.status_code == 200 and "выполнено: 0" in dom(nothing).find_all(**{"data-bulk-result": True})[0].text().lower()
    # дополнение 38 (а): номер, которого нет в базе, пропускается с той же причиной «нет доступа», номер не раскрывается
    with django_capture_on_commit_callbacks(execute=True):
        absent = viewer.post("/tickets/bulk/", {"action": "priority", "numbers": [N_VISIBLE, N_MISSING], "priority": w.high.pk}, **HX)
    assert absent.status_code == 200
    result = dom(absent).find_all(**{"data-bulk-result": True})
    assert result and "выполнено: 1" in result[0].text().lower() and "пропущено: 1" in result[0].text().lower()
    skipped = result[0].find_all("li", **{"data-skipped": True})
    assert len(skipped) == 1 and "нет доступа" in skipped[0].text().lower(), [s.text() for s in skipped]
    assert str(N_MISSING) not in result[0].text(), "в итоге назван несуществующий номер"


# --- NFR-214: нет исполняемого кода и экранирование --------------------------------------------------

def test_slice_pages_have_no_inline_scripts_or_handlers():
    """NFR-214: на страницах и во фрагментах среза нет встроенных скриптов (`script` только с `src`), обработчиков событий
    (`on…`, `hx-on…`) и ссылок `javascript:`."""
    w = _world()
    responses = {**_full_pages(w), **_fragments(w)}
    for path, response in responses.items():
        for node in dom(response).walk():
            if node.tag == "script":
                assert node.attrs.get("src"), f"{path}: встроенный <script>"
                assert not "".join(node.chunks).strip(), f"{path}: у <script src> есть тело"
            for name, value in node.attrs.items():
                assert not re.fullmatch(r"on[a-z]+", name.lower()) and not name.lower().startswith("hx-on"), (
                    f"{path}: обработчик события {name} у <{node.tag}>")
                if name in ("href", "src", "action", "formaction", "hx-get", "hx-post"):
                    assert not value.strip().lower().startswith("javascript:"), f"{path}: javascript: в {name}"


def _assert_escaped(response, label: str, expected_entries: int) -> None:
    raw = html_of(response)
    assert "<script>alert(1)</script>" not in raw and "<b>жирный</b>" not in raw and "<img src=x" not in raw, (
        f"{label}: разметка из текста попала в ответ неэкранированной")
    tree = dom(raw)
    texts = tree.find_all(**{"data-entry-text": True})
    assert len(texts) >= expected_entries, f"{label}: элементов [data-entry-text] {len(texts)}, ждали {expected_entries}"
    escaped = [t for t in texts if "<script>alert(1)</script><b>жирный</b>" in t.text()]
    assert len(escaped) >= expected_entries, f"{label}: текст не показан как текст"
    for node in texts:
        assert {c.tag for c in node.walk()} <= {"br"}, f"{label}: в [data-entry-text] есть разметка {[c.tag for c in node.walk()]}"
    for node in tree.walk():
        assert "onerror" not in node.attrs, f"{label}: атрибут onerror у <{node.tag}>"
        assert not (node.tag == "img" and node.attrs.get("src") == "x"), f"{label}: <img src=x> из текста"


def test_mail_html_in_ticket_card_is_escaped_not_rendered():
    """NFR-214: HTML письма (текст, тема, имя заявителя) в карточке и в списке показан текстом: экранирован, не исполняется."""
    w = _world()
    ticket = sd.make_ticket(queue=w.qa, requester=w.requester, number=4010, subject="<b>жирная</b> тема", requester_name="<i>курсив</i>")
    sd.make_entry(ticket, "incoming", text=PAYLOAD, author_name="<i>курсив</i>", author_email="x@corp.example")
    viewer = support.logged_in(w.viewer)
    for headers in ({}, HX):
        response = viewer.get("/tickets/4010/", **headers)
        assert response.status_code == 200
        _assert_escaped(response, f"карточка {headers}", 1)
        raw = html_of(response)
        assert "<b>жирная</b>" not in raw and "<i>курсив</i>" not in raw, "тема или имя заявителя не экранированы"
        for node in dom(response).find_all(**{"data-field": "subject"}):
            assert not node.find_all("b"), "в поле темы есть разметка из темы"
            assert "<b>жирная</b> тема" in node.text()
    listing = viewer.get("/tickets/?preset=all")
    assert "<b>жирная</b>" not in html_of(listing) and "<i>курсив</i>" not in html_of(listing)
    assert "&lt;b&gt;жирная&lt;/b&gt;" in html_of(listing), "тема в списке не экранирована"


def test_form_reply_and_comment_html_is_escaped_not_rendered():
    """NFR-214: HTML из открытой формы, ответа и комментария исполнителя в карточке показан текстом, не разметкой."""
    w = _world()
    email = "petr@corp.example"
    anonymous = support.make_client()
    posted = anonymous.post("/request/", {"email": email, "name": "Пётр Сидоров", "client_unit": "", "category": w.category.pk,
                                          "subject": "<b>жирная</b> форма", "text": PAYLOAD, "consent": "1"})
    assert posted.status_code == 302 and posted["Location"] == "/request/done/", (
        f"форма не принята: {posted.status_code} {[n.text() for n in dom(posted).find_all(role='alert')]}")
    ticket = model("servicedesk.Ticket").objects.get(requester_email=email)
    viewer = support.logged_in(w.viewer)
    reply = viewer.post(f"/tickets/{ticket.number}/reply/", {"text": PAYLOAD})
    assert reply.status_code == 302, f"ответ не принят: {reply.status_code}"
    comment = viewer.post(f"/tickets/{ticket.number}/comment/", {"text": PAYLOAD})
    assert comment.status_code == 302, f"комментарий не принят: {comment.status_code}"
    for headers in ({}, HX):
        response = viewer.get(f"/tickets/{ticket.number}/", **headers)
        assert response.status_code == 200
        _assert_escaped(response, f"карточка заявки с формы {headers}", 3)
        assert "<b>жирная</b>" not in html_of(response), "тема заявки с формы не экранирована"
    kinds = {n.attrs.get("data-kind") for n in dom(viewer.get(f"/tickets/{ticket.number}/")).find_all("li", **{"data-entry": True})}
    assert {"incoming", "reply", "comment"} <= kinds
