"""T-7102b: строка адресатов записи и полный список адресатов (FR-603, FR-604, FR-606, FR-607, FR-611).
Сценарий 5 спеки; CONTRACT-007, разделы 5.3 (`recipients.line`, `recipients.full`), 10.2 (`/feed/<id>/to/`), 12.3.

Порядок строки (план, «Запись в ленте и карточка»): «Всем», названия узлов, ФИО людей без повторов; порядок внутри
узлов и внутри людей план не задаёт, поэтому тесты сравнивают их как множества. Код среза на уровне модуля не
импортируется.
"""
from html.parser import HTMLParser

import pytest

from tests import support
from tests import support_feed as ff
from tests import support_org as org
from tests.support import HX

pytestmark = pytest.mark.django_db

UNIT_DELETED = "Подразделение удалено"


def _employee(name: str, **extra):
    return support.make_employee(full_name=name, **extra)


def _session(user) -> ff.Session:
    return ff.Session(user, support.logged_in(user))


class _Collect(HTMLParser):
    """Начальные теги с атрибутом `attr` и теги `tag` (помощник только этого файла)."""

    def __init__(self, attr: str):
        super().__init__(convert_charrefs=True)
        self.attr = attr
        self.found: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        values = {name: ("" if value is None else value) for name, value in attrs}
        if self.attr in values:
            self.found.append((tag, values))


def _with_attr(html: str, attr: str) -> list[tuple[str, dict]]:
    parser = _Collect(attr)
    parser.feed(html)
    parser.close()
    return parser.found


def _to_part(html: str, post) -> str:
    part = ff.post_part(html, post.pk, "to")
    assert part is not None, "в записи нет части #feed-post-<id>-to"
    return part.text


def test_recipients_line_shows_unit_deleted_for_removed_unit_and_keeps_person():
    """FR-603, FR-607: удалённое подразделение — «Подразделение удалено», адресат-человек остаётся."""
    from apps.feed.services import recipients

    unit = org.make_unit("Временный отдел")
    person = _employee("Петров И. И.")
    author = _employee("Автор Авторов")
    post = ff.make_post(author, to=[unit, person])
    assert recipients.line(post).items == ["Временный отдел", "Петров И. И."]

    unit.delete()

    line = recipients.line(post)
    assert line.items == [UNIT_DELETED, "Петров И. И."]
    assert line.more == 0
    html = _session(author).client.get(f"/feed/{post.pk}/").content.decode()
    text = _to_part(html, post)
    assert UNIT_DELETED in text and "Петров И. И." in text
    assert "Временный отдел" not in text


def test_recipients_line_all_unit_names_people_once_and_dismissed_marked():
    """FR-603, FR-607: «Всем»; названия узлов; ФИО людей один раз (строки `to` и `mention` одного человека — одна);
    уволенный — «ФИО (уволен)»."""
    from apps.feed.services import recipients

    author = _employee("Автор Авторов")
    assert recipients.line(ff.make_post(author, to=["all"])).items == ["Всем"]

    first, second = org.make_unit("Отдел ИТ"), org.make_unit("Бухгалтерия")
    twice = _employee("Иванов Иван Иванович")
    gone = _employee("Сидоров Сергей Сергеевич", state="dismissed")
    post = ff.make_post(author, to=[first, second, twice, gone], mentions=[twice])

    line = recipients.line(post)
    assert line.more == 0
    assert len(line.items) == 4
    assert sorted(line.items[:2]) == ["Бухгалтерия", "Отдел ИТ"]
    assert sorted(line.items[2:]) == ["Иванов Иван Иванович", "Сидоров Сергей Сергеевич (уволен)"]
    assert line.items.count("Иванов Иван Иванович") == 1

    html = _session(author).client.get(f"/feed/{post.pk}/").content.decode()
    text = _to_part(html, post)
    assert text.count("Иванов Иван Иванович") == 1
    assert "Сидоров Сергей Сергеевич" in text and "(уволен)" in text
    assert "Отдел ИТ" in text and "Бухгалтерия" in text


def test_recipients_line_over_five_shows_first_five_and_more_four_counting_comment_mention():
    """FR-603, FR-607, FR-611: адресатов девять (два узла, пять людей, двое упомянутых в комментарии) — первые пять и
    «и ещё 4»; упомянутые в комментарии считаются; ссылка ведёт на `/feed/<id>/to/`."""
    from apps.feed.services import recipients

    author = _employee("Автор Авторов")
    units = [org.make_unit(f"Отдел {i}") for i in (1, 2)]
    people = [_employee(f"Адресат Номер{i}") for i in range(1, 6)]
    mentioned = [_employee(f"Упомянутый Номер{i}") for i in range(1, 3)]
    post = ff.make_post(author, to=[*units, *people])
    ff.comment(post, author, "Коллеги, посмотрите", mentions=mentioned)

    line, full = recipients.line(post), recipients.full(post)
    assert len(full) == 9
    assert len(line.items) == 5 and line.more == 4
    assert line.items == full[:5]

    html = _session(author).client.get(f"/feed/{post.pk}/").content.decode()
    part = _to_part(html, post)
    assert "и ещё 4" in part
    assert len(_with_attr(html, "data-to-item")) == 5   # в строке ровно пять элементов, остальные — по ссылке
    more = [attrs for tag, attrs in _with_attr(html, "data-to-more")]
    assert [m.get("hx-get") for m in more] == [f"/feed/{post.pk}/to/"]


def test_recipients_full_list_fragment_includes_comment_mention_unit_deleted_and_dismissed():
    """FR-603, FR-607, FR-611: `/feed/<id>/to/` — полный список без обрезки: упомянутый в комментарии, удалённое
    подразделение, уволенный."""
    from apps.feed.services import recipients

    author = _session(_employee("Автор Авторов"))
    unit = org.make_unit("Временный отдел")
    live_unit = org.make_unit("Отдел ИТ")
    gone = _employee("Сидоров Сергей Сергеевич", state="dismissed")
    people = [_employee(f"Адресат Номер{i}") for i in range(1, 5)]
    mentioned = _employee("Упомянутый Комментатором")
    post = ff.make_post(author.user, to=[unit, live_unit, gone, *people])
    ff.comment(post, author.user, "Смотрите", mentions=[mentioned])
    unit.delete()

    response = author.client.get(f"/feed/{post.pk}/to/", **HX)
    assert response.status_code == 200
    body = response.content.decode()
    lists = [attrs for tag, attrs in _with_attr(body, "data-feed-list") if tag == "ul"]
    assert [attrs["data-feed-list"] for attrs in lists] == ["recipients"]
    assert len(recipients.full(post)) == 8
    assert UNIT_DELETED in body and "Отдел ИТ" in body
    assert "Упомянутый Комментатором" in body
    assert "Сидоров Сергей Сергеевич" in body and "(уволен)" in body
    for person in people:
        assert person.full_name in body


def test_recipients_full_list_returns_404_for_non_viewer():
    """FR-604, FR-606: не видящему запись `/feed/<id>/to/` отвечает так же, как для несуществующей записи."""
    author, addressee = _employee("Автор Авторов"), _employee("Адресат Личный")
    post = ff.make_post(author, to=[addressee])
    outsider = _session(_employee("Посторонний Лиц"))
    hidden = outsider.client.get(f"/feed/{post.pk}/to/")
    missing = outsider.client.get("/feed/999999/to/")
    assert hidden.status_code == 404
    assert support.same_failure(hidden, missing)
    assert _session(addressee).client.get(f"/feed/{post.pk}/to/").status_code == 200
