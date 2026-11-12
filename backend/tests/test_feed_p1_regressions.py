"""T-7260: серверные регрессии фиксов P1 приёмки среза 007 (browser-gate, триаж 106 — G1/G2/G3/G5/G7).

Каждый тест — RED до продуктовой правки и GREEN после:
- G1: строка адресатов записи (`recipients.line`) показывает персонального адресата краткой формой
  «Фамилия И. О.» (FR-603, сценарий 5: «→ Группа сети, Петров И. И.»), полный список `/feed/<id>/to/`
  остаётся с полными ФИО (FR-603: «полный список по нажатию»), пометка «(уволен)» сохраняется;
- G2: поле срока «До даты» — нативный `input[type=date]` с атрибутами `min`/`max` (CONTRACT-007 10.2,
  К42/К61: границы проверяет браузер, сервер остаётся главным); прочие поля дат портала без границ
  (birth_date, фильтры аудита и ленты) остаются текстовым виджетом с сеткой (FR-148);
- G3: счётчик `[data-feed-reads-count]` у автора и модератора — ссылка на `/feed/<id>/reads/`
  (CONTRACT-007 12.3: «счётчик … (ссылка)»; 10.2 GET возвращает `[data-feed-list="reads"]`),
  прочим — неинтерактивный текст без ссылки (403-семантика);
- G5: у `event_title`/`event_place` нет `maxlength="200"` — ввод не обрезается до отправки,
  отказ `too_long` возвращает сервер с причиной у поля (FR-642);
- G7: в `form#feed-filters` есть видимый `input[data-feed-picker="author"]` и контейнер
  `[data-feed-pick-list="author"]` при скрытом `input[name="author"]` (CONTRACT-007 12.2, 757).

Без БД/Valkey: `recipients` зовётся с объектами-заглушками, шаблоны рендерятся напрямую,
как в test_feed_dom_targets_regressions.py. G6 (e2e-хелперы f09/f11) браузерным проходом — здесь
не проверяется; его закрывают сами сценарии T-7260.
"""
from datetime import datetime, timezone as dt_timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def valkey_clean(request):
    """Этот файл не использует БД/Valkey: шаблоны и сервис — без стенда."""
    yield None


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

BASE_DIR = Path(__file__).resolve().parent.parent


class _Attr:
    """Простой держатель атрибутов (имитация объектов контекста без ORM)."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.children = []

    def walk(self):
        for child in self.children:
            if isinstance(child, _Node):
                yield child
                yield from child.walk()

    def find(self, tag=None, **attrs):
        wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
        found = []
        for node in self.walk():
            if tag is not None and node.tag != tag:
                continue
            ok = True
            for name, value in wanted.items():
                if value is True:
                    if name not in node.attrs:
                        ok = False
                        break
                elif value is False:
                    if name in node.attrs:
                        ok = False
                        break
                elif node.attrs.get(name) != value:
                    ok = False
                    break
            if ok:
                found.append(node)
        return found

    def first(self, tag=None, **attrs):
        found = self.find(tag, **attrs)
        return found[0] if found else None

    def text(self) -> str:
        return " ".join(part.strip() for part in _texts(self) if part.strip()).strip()


def _texts(node):
    for child in node.children:
        if isinstance(child, str):
            yield child
        else:
            yield from _texts(child)


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = _Node("#root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in _VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(_Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def _tree(html: str) -> _Node:
    parser = _Tree()
    parser.feed(html)
    return parser.root


def _render(template_name: str, context: dict) -> str:
    """Рендерит шаблон напрямую, без context-процессоров (не требует БД)."""
    source = (BASE_DIR / "templates" / template_name).read_text(encoding="utf-8")
    from django.template import Context, Template

    return Template(source).render(Context(context))


# --- G1: строка адресатов — «Фамилия И. О.» ------------------------------------------------------------------------


def _post_row_users(full_name, state="active", pk=7, user_id=11):
    post = _Attr(pk=pk, to_all=False)
    rows = [_Attr(unit_id=None, user_id=user_id, user=None)]
    users = {user_id: _Attr(full_name=full_name, state=state)}
    return post, rows, users


def test_recipients_line_shortens_person_to_surname_and_initials():
    """G1 (FR-603, сценарий 5): персональный адресат в строке — «Фамилия И. О.», не полное ФИО."""
    from apps.feed.services import recipients

    post, rows, users = _post_row_users("Иванов Иван Иванович")
    line = recipients.line(post, rows=rows, users=users, units={})
    assert line.items == ["Иванов И. И."], line.items


def test_recipients_line_short_name_handles_two_parts_and_single_word():
    """G1: у имени из двух слов — одна буква; из одного слова — без инициалов (не ломается)."""
    from apps.feed.services import recipients

    post, rows, users = _post_row_users("Автор Авторов")
    assert recipients.line(post, rows=rows, users=users, units={}).items == ["Автор А."]
    post, rows, users = _post_row_users("Безымянный")
    assert recipients.line(post, rows=rows, users=users, units={}).items == ["Безымянный"]


def test_recipients_line_short_name_of_already_short_name_is_stable():
    """G1: «Петров И. И.» не меняется от повторного сокращения (регрессия прежних тестов)."""
    from apps.feed.services import recipients

    post, rows, users = _post_row_users("Петров И. И.")
    assert recipients.line(post, rows=rows, users=users, units={}).items == ["Петров И. И."]


def test_recipients_line_keeps_dismissed_mark_after_shortening():
    """G1 (FR-607): пометка «(уволен)» остаётся после сокращения ФИО."""
    from apps.feed.services import recipients

    post, rows, users = _post_row_users("Сидоров Сергей Сергеевич", state="dismissed")
    line = recipients.line(post, rows=rows, users=users, units={})
    assert line.items == ["Сидоров С. С. (уволен)"], line.items


def test_recipients_full_list_keeps_full_names():
    """G1 (FR-603: «полный список по нажатию»): `/feed/<id>/to/` остаётся с полными ФИО."""
    from apps.feed.services import recipients

    post, rows, users = _post_row_users("Иванов Иван Иванович")
    items = recipients.full(post, rows=rows, users=users, units={})
    assert items == ["Иванов Иван Иванович"], items


# --- G2: «До даты» — нативный input[type=date] с min/max -----------------------------------------------------------


def _widget(minimum=None, maximum=None):
    from apps.core.widgets import PortalDateInput

    attrs = {"id": "id_feed_until"}
    if minimum is not None:
        attrs["min"] = minimum
    if maximum is not None:
        attrs["max"] = maximum
    return PortalDateInput().render("until", "", attrs=attrs)


def test_portal_date_input_with_bounds_renders_native_date_input():
    """G2 (К42/К61): с границами виджет — нативный `input[type=date]` с `min`/`max`, без обёртки сетки."""
    html = _widget(minimum="2026-11-12", maximum="2027-11-11")
    doc = _tree(html)
    field = doc.first("input", name="until")
    assert field is not None, "поле until не отрисовано"
    assert field.attrs.get("type") == "date", f"type={field.attrs.get('type')!r}: validity не видит диапазон"
    assert field.attrs.get("min") == "2026-11-12"
    assert field.attrs.get("max") == "2027-11-11"
    assert doc.first(data_datefield=True) is None, "нативное поле не должно нести обёртку сетки"
    assert doc.first("button", data_datefield_open=True) is None


def test_portal_date_input_normalizes_native_value_to_iso():
    """G2: значение нативного поля — `ГГГГ-ММ-ДД` (ДД.ММ.ГГГГ от прямой отправки приводится)."""
    from apps.core.widgets import PortalDateInput

    html = PortalDateInput().render("until", "12.11.2026", attrs={"min": "2026-11-13", "max": "2027-11-12"})
    field = _tree(html).first("input", name="until")
    assert field.attrs.get("value") == "2026-11-12"
    html = PortalDateInput().render("until", "не дата", attrs={"min": "2026-11-13", "max": "2027-11-12"})
    assert _tree(html).first("input", name="until").attrs.get("value") in ("", None)


def test_portal_date_input_without_bounds_keeps_portal_text_widget():
    """G2 (FR-148, регрессия смежных полей): без границ — прежний текстовый виджет с сеткой и кнопкой."""
    from apps.core.widgets import PortalDateInput

    html = PortalDateInput().render("birth_date", "05.03.1990", attrs={"id": "id_birth_date"})
    doc = _tree(html)
    field = doc.first("input", name="birth_date")
    assert field is not None and field.attrs.get("type") == "text"
    assert "data-datefield-input" in field.attrs
    assert field.attrs.get("value") == "05.03.1990" and field.attrs.get("placeholder") == "ДД.ММ.ГГГГ"
    assert doc.first("button", data_datefield_open=True) is not None, "нет кнопки «Выбрать дату»"
    assert doc.first(data_datefield_picker=True) is not None


def _form_context(**overrides) -> dict:
    context = {
        "form_values": {
            "text": "", "until": "", "event_title": "", "event_place": "",
            "event_start": "", "event_end": "", "kind": "post", "term": "day",
        },
        "form_kinds": (("post", "Сообщение"), ("important", "Важное"), ("event", "Событие")),
        "form_terms": (("day", "День"), ("week", "Неделя"), ("month", "Месяц"), ("date", "До даты")),
        "form_can_all": True,
        "form_pills": [{"value": "all", "label": "Всем"}],
        "form_mentioned": [],
        "form_files": [],
        "form_mention_names": "{}",
        "form_until": "",
        "form_errors": {},
        "pdn_found": False,
        "form_oob": False,
    }
    context.update(overrides)
    return context


def test_feed_form_until_is_native_date_with_min_and_max():
    """G2 (К61, 10.2): в форме публикации поле срока — `input[type=date]` с `min`/`max` (как их передаёт вид)."""
    html = _render("feed/_form.html", _form_context(form_until=_widget("2026-11-12", "2027-11-11")))
    field = _tree(html).first("input", name="until")
    assert field is not None, "поле until не отрисовано"
    assert field.attrs.get("type") == "date", f"type={field.attrs.get('type')!r}"
    assert field.attrs.get("min") == "2026-11-12" and field.attrs.get("max") == "2027-11-11"


def test_feed_views_pass_native_bounds_to_until_widget():
    """G2: представления формы и правки передают виджету `min`/`max`, а не `data-min`/`data-max`."""
    source = (BASE_DIR / "apps" / "feed" / "views" / "posts.py").read_text(encoding="utf-8")
    assert "data-min" not in source and "data-max" not in source, "границы срока остались в data-атрибутах"


# --- G3: счётчик «Прочитали» — ссылка на списки ---------------------------------------------------------------------


_UNTIL = datetime(2026, 11, 20, 12, 0, tzinfo=dt_timezone.utc)
_OPENED = datetime(2026, 11, 11, 9, 0, tzinfo=dt_timezone.utc)


def _imp_context(*, author=False, moderator=False):
    viewer_pk = 1 if author else 2
    return {
        "request": _Attr(user=_Attr(pk=viewer_pk)),
        "post": _Attr(pk=7, author_id=1, important_until=_UNTIL),
        "card": _Attr(read_count=2, read_total=5, read=False),
        "item": _Attr(is_moderator=moderator),
        "opened": _OPENED,
    }


def test_reads_counter_is_link_to_reads_for_author():
    """G3 (12.3: «счётчик … (ссылка)»): у автора счётчик — ссылка `/feed/<id>/reads/` с hx-get."""
    html = _render("feed/_important.html", _imp_context(author=True))
    doc = _tree(html)
    counter = doc.first(data_feed_reads_count=True)
    assert counter is not None, "счётчик не найден"
    assert counter.tag == "a", f"счётчик — {counter.tag}, а не ссылка"
    assert counter.attrs.get("href") == "/feed/7/reads/"
    assert counter.attrs.get("hx-get") == "/feed/7/reads/"
    assert counter.text() == "Прочитали 2 из 5", counter.text()


def test_reads_counter_is_link_to_reads_for_moderator():
    """G3: у модератора-адресата счётчик — та же ссылка (403-семантика у прочих)."""
    html = _render("feed/_important.html", _imp_context(moderator=True))
    counter = _tree(html).first(data_feed_reads_count=True)
    assert counter.tag == "a" and counter.attrs.get("href") == "/feed/7/reads/"


def test_reads_counter_is_plain_text_without_link_for_other_viewers():
    """G3 (12.3, 10.2): прочим — неинтерактивный счётчик «Прочитали N», ссылки на списки нет."""
    html = _render("feed/_important.html", _imp_context())
    doc = _tree(html)
    counter = doc.first(data_feed_reads_count=True)
    assert counter is not None and counter.tag == "span", "у адресата без права счётчик должен быть текстом"
    assert counter.text() == "Прочитали 2", counter.text()
    assert doc.first("a", href="/feed/7/reads/") is None, "ссылка на списки доступна без права"


def test_frame_reads_counter_is_link_for_author_or_moderator():
    """G3: в OOB-кадре `-imp` счётчик — та же ссылка (согласование `_frame_important.html`)."""
    context = {
        "post": _Attr(pk=7, author_id=1, important_until=_UNTIL),
        "card": _Attr(read_count=2, read_total=5),
        "is_author_or_moderator": True,
        "opened": _OPENED,
    }
    html = _render("feed/_frame_important.html", context)
    doc = _tree(html)
    counter = doc.first(data_feed_reads_count=True)
    assert counter is not None and counter.tag == "a", "счётчик кадра не ссылка"
    assert counter.attrs.get("href") == "/feed/7/reads/" and counter.attrs.get("hx-get") == "/feed/7/reads/"
    assert counter.text() == "Прочитали 2 из 5", counter.text()


def test_frame_reads_counter_is_plain_text_without_link_for_others():
    """G3: в кадре для прочих — текст без ссылки."""
    context = {
        "post": _Attr(pk=7, author_id=1, important_until=_UNTIL),
        "card": _Attr(read_count=2, read_total=5),
        "is_author_or_moderator": False,
        "opened": _OPENED,
    }
    doc = _tree(_render("feed/_frame_important.html", context))
    counter = doc.first(data_feed_reads_count=True)
    assert counter is not None and counter.tag == "span"
    assert doc.first("a", href="/feed/7/reads/") is None


# --- G5: поля события без maxlength ---------------------------------------------------------------------------------


def _form_edit_context(**overrides) -> dict:
    context = _form_context()
    context.update({
        "form_kind": "event",
        "post": _Attr(pk=7),
        "form_files": [],
        "form_new_files": [],
        "form_remove": set(),
    })
    context.update(overrides)
    return context


def test_publish_form_has_no_maxlength_on_event_title_and_place():
    """G5 (FR-642): `maxlength="200"` у полей события глушит серверный отказ `too_long` — атрибута быть не должно."""
    doc = _tree(_render("feed/_form.html", _form_context()))
    for name in ("event_title", "event_place"):
        field = doc.first("input", name=name)
        assert field is not None, f"нет поля {name}"
        assert "maxlength" not in field.attrs, f"{name}: maxlength обрезает ввод до отправки"


def test_edit_form_has_no_maxlength_on_event_title_and_place():
    """G5: то же в форме правки записи."""
    doc = _tree(_render("feed/_form_edit.html", _form_edit_context()))
    for name in ("event_title", "event_place"):
        field = doc.first("input", name=name)
        assert field is not None, f"нет поля {name}"
        assert "maxlength" not in field.attrs, f"{name}: maxlength обрезает ввод до отправки"


# --- G7: видимый подбор автора в фильтрах ---------------------------------------------------------------------------


def _body_context(**overrides) -> dict:
    context = {
        "layout": "layouts/fragment.html",
        "ws_url": "/ws/feed/",
        "opened": _OPENED,
        "filter_options": (("all", "Все"),),
        "filter_values": {"f": "all"},
        "date_from": "",
        "date_to": "",
        "flt": _Attr(f="all"),
        "posts": [],
        "important": None,
        "filtered": False,
    }
    context.update(overrides)
    return context


def test_filters_form_has_visible_author_picker_and_pick_list():
    """G7 (12.2, 757): в `form#feed-filters` — видимый `input[data-feed-picker="author"]` и его список."""
    doc = _tree(_render("feed/body.html", _body_context()))
    form = doc.first("form", id="feed-filters")
    assert form is not None, "форма фильтров не найдена"
    field = form.first("input", data_feed_picker="author")
    assert field is not None, "нет видимого поля подбора автора"
    assert field.attrs.get("type") == "text"
    assert field.attrs.get("name") is None, "подбираемое поле не отправляет своё значение"
    hidden = form.first("input", name="author")
    assert hidden is not None and hidden.attrs.get("type") == "hidden", "скрытое поле author пропало"
    assert form.first("div", data_feed_pick_list="author") is not None, "нет контейнера подсказок автора"


def test_filters_author_field_is_filled_with_chosen_author_name():
    """G7 (12.2: «выбранные значения — отмечены/заполнены»): выбранного автора поле показывает ФИО."""
    doc = _tree(_render("feed/body.html", _body_context(
        filter_values={"f": "all", "author": "11"}, filter_author_name="Иванов Иван Иванович")))
    form = doc.first("form", id="feed-filters")
    field = form.first("input", data_feed_picker="author")
    assert field.attrs.get("value") == "Иванов Иван Иванович"
    assert form.first("input", name="author").attrs.get("value") == "11"


def test_home_context_supplies_author_name_for_filters():
    """G7: `_context` главной передаёт шаблону ФИО выбранного автора (`filter_author_name`)."""
    source = (BASE_DIR / "apps" / "feed" / "views" / "home.py").read_text(encoding="utf-8")
    assert "filter_author_name" in source, "вид не передаёт ФИО автора для видимого поля фильтра"
