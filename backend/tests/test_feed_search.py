"""T-7131: сквозной поиск и векторы ленты (FR-606, FR-636, FR-637, FR-641, NFR-603, NFR-608). Сценарий 14 спеки 007.

Поставщик группы «Лента» (`search.search_providers()`, ключ `feed`, порядок 60, видимость в том же SQL), строка выдачи
(ФИО, дата по Москве, отрывок, подсказка «Запись» / «Комментарий», ссылка с якорем), порядок от новых к старым, порции
`limit + 1` и смещение, число с потолком 300, векторы записи (вес A у названия и места события, вес B у текста без
маркеров) и комментария (`FeedComment.search`), пересчёт в транзакциях публикации, правки и комментария, слова
запроса только параметрами, текст запроса нигде не сохраняется. Гонок нет. Тексты и подсказки — литералы раздела 9
контракта (решение 19 задач). Код среза на уровне модуля не импортируется (CONTRACT-007, шапка).
"""
import importlib
import logging
import re
from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from django.contrib.postgres.search import SearchQuery
from django.db import connection

from tests import support
from tests import support_feed as fd
from tests import support_lists as sl
from tests.support import model

pytestmark = pytest.mark.django_db


# --- помощники файла ---------------------------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.feed.services.{name}")


def _provider():
    found = _svc("search").search_providers()
    assert len(found) == 1, found
    return found[0]


def _parsed(query: str):
    from apps.search.parse import parse

    return parse(query)


def _fresh(user):
    return model("core.User").objects.get(pk=user.pk)


def _rows(user, query: str, limit: int = 50, offset: int = 0) -> list:
    return _provider().search(_fresh(user), _parsed(query), limit, offset)


def _urls(user, query: str, limit: int = 50, offset: int = 0) -> list[str]:
    return [row.url for row in _rows(user, query, limit, offset)]


def _count(user, query: str) -> tuple:
    return _provider().count(_fresh(user), _parsed(query))


def _group_keys(user) -> list[str]:
    from apps.search import services

    return [provider.key for provider in services.providers(_fresh(user))]


def _post_url(post) -> str:
    return f"/feed/{post.pk}/"


def _comment_url(post, comment) -> str:
    return f"/feed/{post.pk}/#c{comment.pk}"


def _world():
    """Автор с правом «Писать всем» (ФИО задано) и читатель."""
    writer = fd.as_writer(full_name="Сидорова Анна")
    reader = fd.as_plain(full_name="Петров Пётр")
    return writer, reader


def _post_weights(post, word: str) -> set[str]:
    """Веса, с которыми слово есть в `feed_post.search` (через `to_tsquery('russian', 'слово:<вес>')` базы)."""
    assert model("feed.Post")._meta.db_table == "feed_post"
    found = set()
    with connection.cursor() as cursor:
        for mark in "ABCD":
            cursor.execute("SELECT search @@ to_tsquery('russian', %s) FROM feed_post WHERE id = %s",
                           [word + ":" + mark, post.pk])
            if cursor.fetchone()[0]:
                found.add(mark)
    return found


def _comment_matches(comment, word: str) -> bool:
    return model("feed.FeedComment").objects.filter(pk=comment.pk, search=SearchQuery(word, config="russian")).exists()


def _post_matches(post, word: str) -> bool:
    return model("feed.Post").objects.filter(pk=post.pk, search=SearchQuery(word, config="russian")).exists()


def _null_vectors(post=None, comment=None) -> None:
    with connection.cursor() as cursor:
        if post is not None:
            cursor.execute("UPDATE feed_post SET search = NULL WHERE id = %s", [post.pk])
        if comment is not None:
            cursor.execute("UPDATE feed_feedcomment SET search = NULL WHERE comment_id = %s", [comment.pk])


# --- 1. поставщик ---------------------------------------------------------------------------------------------

def test_provider_key_feed_title_order_60_after_lists():
    """FR-636, FR-641: в точке `search_providers` одна запись из `apps.feed`; поставщик `("feed", "Лента", 60)`;
    в сборщике поиска группа идёт после «Списков» (50)."""
    from apps.core import extensions

    registered = [func for func in extensions.registered("search_providers") if func.__module__.startswith("apps.feed")]
    assert len(registered) == 1
    provider = _provider()
    assert (provider.key, provider.title, provider.order) == fd.FEED_SEARCH == ("feed", "Лента", 60)
    assert callable(provider.search) and callable(provider.count) and callable(provider.available)
    lst = sl.make_list(created_by=support.make_employee())
    reader = sl.as_reader(lst)
    keys = _group_keys(reader.user)
    assert "lists" in keys and "feed" in keys
    assert keys.index("lists") < keys.index("feed")


def test_provider_available_to_every_logged_in_employee():
    """FR-636: группа доступна каждому вошедшему сотруднику: без ролей, с правом «Писать всем», модератору."""
    provider = _provider()
    for session in (fd.as_plain(), fd.as_writer(), fd.as_moderator()):
        assert provider.available(_fresh(session.user)) is True
        assert "feed" in _group_keys(session.user)


# --- 2. что находится и как выглядит строка ------------------------------------------------------------------

def test_word_form_finds_post_with_other_form_of_word():
    """FR-636: слово запроса находит запись по другой форме слова («серверной» → «серверная»); слова, которого в
    записи нет, нет в выдаче; строка ведёт на `/feed/<id>/`."""
    writer, reader = _world()
    post = fd.make_post(writer.user, to=("all",), text="Серверная закрыта на профилактику")
    fd.make_post(writer.user, to=("all",), text="Совсем другая запись про принтеры")
    assert _urls(reader.user, "серверной") == [_post_url(post)]
    assert _urls(reader.user, "профилактики") == [_post_url(post)]
    assert _urls(reader.user, "несуществующееслово") == []


def test_word_prefix_finds_comment_with_anchor_url():
    """FR-636: начало слова («коммут») находит комментарий; строка ведёт к комментарию (`/feed/<id>/#c<cid>`), подсказка
    — «Комментарий»."""
    writer, reader = _world()
    post = fd.make_post(writer.user, to=("all",), text="Плановые работы в сети")
    comment = fd.comment(post, writer.user, "Коммутатор доступа заменён")
    rows = _rows(reader.user, "коммут")
    assert [(row.url, row.subtitle) for row in rows] == [(_comment_url(post, comment), "Комментарий")]


def test_event_found_by_title_and_place_word_forms_row_shows_title():
    """FR-636: событие находится по словоформам названия («пожарной» → «Пожарная тревога») и места («корпусе» →
    «Главный корпус»); в строке вместо текста — название события."""
    writer, reader = _world()
    start = datetime(2026, 12, 20, 9, 0, tzinfo=dt_timezone.utc)
    event = fd.make_event(writer.user, start=start, title="Пожарная тревога", place="Главный корпус", to=("all",),
                          text="Описание, которое в строке не показывается")
    for query in ("пожарной", "корпусе"):
        rows = _rows(reader.user, query)
        assert [row.url for row in rows] == [_post_url(event)], query
        assert "Пожарная тревога" in rows[0].title, query
        assert "Описание, которое" not in rows[0].title, query


def test_row_title_name_date_snippet_and_subtitle_post_or_comment():
    """FR-636: строка — «<ФИО>, <ДД.ММ.ГГГГ> — <начало текста>», подсказка «Запись» или «Комментарий»; дата у записи —
    публикации, у комментария — его создания, по Москве (21:30 UTC — уже следующий день); длинный текст обрезан по
    слову с «…» (отрывок не длиннее 100 знаков вместе с «…»)."""
    writer, reader = _world()
    commenter = fd.as_plain(full_name="Кузнецов Олег")
    published = datetime(2026, 5, 11, 21, 30, tzinfo=dt_timezone.utc)
    post = fd.make_post(writer.user, to=("all",), text="Заменили коммутатор в серверной", published_at=published)
    comment = fd.comment(post, commenter.user, "Коммутатор заменили вчера", created_at=fd.moscow(2026, 5, 14, 9, 0))
    rows = {row.url: row for row in _rows(reader.user, "коммутатор")}
    assert set(rows) == {_post_url(post), _comment_url(post, comment)}
    record = rows[_post_url(post)]
    assert (record.title, record.subtitle) == ("Сидорова Анна, 12.05.2026 — Заменили коммутатор в серверной", "Запись")
    answer = rows[_comment_url(post, comment)]
    assert (answer.title, answer.subtitle) == ("Кузнецов Олег, 14.05.2026 — Коммутатор заменили вчера", "Комментарий")
    long_text = "маршрутизатор " + "слово " * 60
    long_post = fd.make_post(writer.user, to=("all",), text=long_text, published_at=published)
    (long_row,) = _rows(reader.user, "маршрутизатор")
    snippet = long_row.title.split(" — ", 1)[1]
    assert snippet.endswith("…") and len(snippet) <= 100 and snippet.startswith("маршрутизатор")
    assert long_row.url == _post_url(long_post)


def test_row_snippet_without_markup_marker_as_at_full_name():
    """FR-636: в отрывке строки маркер упоминания показан как «@ФИО» (без `@[id]`), лишние пробелы и переводы строк
    схлопнуты."""
    writer, reader = _world()
    mentioned = fd.as_plain(full_name="Громова Елена")
    post = fd.make_post(writer.user, to=("all",), text="Привет,\n\n  проверь пожалуйста", mentions=(mentioned.user,))
    (row,) = _rows(reader.user, "проверь")
    assert row.url == _post_url(post)
    snippet = row.title.split(" — ", 1)[1]
    assert "@Громова Елена" in snippet and "@[" not in snippet
    assert "\n" not in snippet and "  " not in snippet


def test_mention_marker_ids_not_searchable():
    """FR-636: номера из маркеров `@[id]` в вектор не идут: запрос по номеру сотрудника ничего не находит, а вектор
    записи не содержит такой лексемы."""
    writer, reader = _world()
    mentioned = fd.as_plain()
    post = fd.make_post(writer.user, to=("all",), text="Прошу посмотреть", mentions=(mentioned.user,))
    assert f"@[{mentioned.user.pk}]" in post.text
    assert _rows(reader.user, str(mentioned.user.pk)) == []
    with connection.cursor() as cursor:
        cursor.execute("SELECT search @@ to_tsquery('russian', %s) FROM feed_post WHERE id = %s",
                       [str(mentioned.user.pk), post.pk])
        assert cursor.fetchone()[0] is False


# --- 3. видимость, удаление, правка -----------------------------------------------------------------------------

def test_invisible_post_and_its_comment_absent_from_results_and_count():
    """FR-606, FR-636: запись, которую сотрудник не видит, и её комментарии не попадают ни в выдачу, ни в число;
    адресат находит и запись, и комментарий; число — точное."""
    writer, reader = _world()
    outsider = fd.as_plain()
    private = fd.make_post(writer.user, to=(reader.user,), text="Закрытая рассылка про хризантемы")
    fd.comment(private, reader.user, "Хризантемы в комментарии")
    open_post = fd.make_post(writer.user, to=("all",), text="Открытая запись про хризантемы")
    assert len(_rows(reader.user, "хризантемы")) == 3 and _count(reader.user, "хризантемы") == (3, False)
    assert _urls(outsider.user, "хризантемы") == [_post_url(open_post)]
    assert _count(outsider.user, "хризантемы") == (1, False)
    nobody = fd.as_plain()
    only_private = fd.make_post(writer.user, to=(reader.user,), text="Только для читателя про орхидеи")
    assert _urls(reader.user, "орхидеи") == [_post_url(only_private)]
    assert _rows(nobody.user, "орхидеи") == [] and _count(nobody.user, "орхидеи") == (0, False)


def test_deleted_post_and_comment_not_found(django_capture_on_commit_callbacks):
    """FR-637: удалённая запись (вместе с комментариями) и удалённый комментарий не находятся."""
    writer, reader = _world()
    kept = fd.make_post(writer.user, to=("all",), text="Остаётся про глицинии")
    comment = fd.comment(kept, writer.user, "Комментарий про фиалки")
    doomed = fd.make_post(writer.user, to=("all",), text="Уйдёт про незабудки")
    fd.comment(doomed, writer.user, "Комментарий про ромашки")
    assert _urls(reader.user, "фиалки") and _urls(reader.user, "незабудки") and _urls(reader.user, "ромашки")
    with django_capture_on_commit_callbacks(execute=True):
        _svc("comments").delete(writer.user, comment.pk)
        _svc("posts").delete(writer.user, doomed.pk)
    assert _rows(reader.user, "фиалки") == []
    assert _rows(reader.user, "незабудки") == [] and _rows(reader.user, "ромашки") == []
    assert _urls(reader.user, "глицинии") == [_post_url(kept)]


def test_edited_post_not_found_by_old_text_found_by_new(django_capture_on_commit_callbacks):
    """FR-637: после правки записи старый текст не находится, новый находится; другая запись не затронута."""
    writer, reader = _world()
    post = fd.make_post(writer.user, to=("all",), text="Купили кофемашину")
    other = fd.make_post(writer.user, to=("all",), text="Соседняя запись про кофемашину")
    assert len(_rows(reader.user, "кофемашина")) == 2
    with django_capture_on_commit_callbacks(execute=True):
        _svc("posts").edit(writer.user, post.pk, {"text": "Купили чайник", "to": ["all"]})
    assert _urls(reader.user, "кофемашина") == [_post_url(other)]
    assert _urls(reader.user, "чайник") == [_post_url(post)]


def test_edited_comment_not_found_by_old_text_found_by_new(django_capture_on_commit_callbacks):
    """FR-637: после правки комментария старый текст не находится, новый находится по тому же адресу с якорем."""
    writer, reader = _world()
    post = fd.make_post(writer.user, to=("all",), text="Запись без искомых слов")
    comment = fd.comment(post, reader.user, "Принтер сломался")
    assert _urls(reader.user, "принтер") == [_comment_url(post, comment)]
    with django_capture_on_commit_callbacks(execute=True):
        _svc("comments").edit(reader.user, comment.pk, "Сканер сломался")
    assert _rows(reader.user, "принтер") == []
    assert _urls(reader.user, "сканер") == [_comment_url(post, comment)]


def test_stop_word_query_returns_empty_without_error():
    """FR-636: запрос из одних стоп-слов («как», «что») не даёт ошибки: выдача пуста, число `(0, False)`; стоп-слово
    рядом со значимым отбрасывается, значимое находит запись."""
    writer, reader = _world()
    post = fd.make_post(writer.user, to=("all",), text="Как обновить прошивку, что делать с роутером")
    for query in ("как", "что", "как что"):
        parsed = _parsed(query)
        assert parsed.hint == "", query
        assert _provider().search(_fresh(reader.user), parsed, 20, 0) == [], query
        assert _provider().count(_fresh(reader.user), parsed) == (0, False), query
    assert _urls(reader.user, "как прошивку") == [_post_url(post)]


# --- 4. порядок, порции, число ---------------------------------------------------------------------------------

def _timeline(writer, count: int, word: str = "регламент") -> list[str]:
    """Чередующиеся записи и комментарии со словом `word` с убывающим временем; возвращает адреса от новых к старым."""
    base = datetime(2026, 6, 1, 8, 0, tzinfo=dt_timezone.utc)
    items = []
    last_post = None
    for step in range(count):
        moment = base + timedelta(minutes=step)
        if step % 2 == 0:
            last_post = fd.make_post(writer.user, to=("all",), text=f"Запись {word}", published_at=moment)
            items.append(_post_url(last_post))
        else:
            comment = fd.comment(last_post, writer.user, f"Комментарий {word}", created_at=moment)
            items.append(_comment_url(last_post, comment))
    return list(reversed(items))


def test_results_ordered_newest_first_across_posts_and_comments():
    """FR-636: записи и комментарии идут одним списком от новых к старым по времени публикации и создания."""
    writer, reader = _world()
    expected = _timeline(writer, 4)
    assert _urls(reader.user, "регламент") == expected


def test_second_page_with_offset_continues_without_gaps_or_repeats_across_posts_and_comments():
    """FR-636: порции по 5 со смещениями 0, 5, 10 вместе дают весь список в том же порядке без пропусков и
    повторов; лишняя строка порции («есть ещё») в список не входит."""
    writer, reader = _world()
    expected = _timeline(writer, 12)
    pages = [_urls(reader.user, "регламент", limit=5, offset=offset)[:5] for offset in (0, 5, 10)]
    assert [url for page in pages for url in page] == expected
    assert len(set(expected)) == 12


def test_provider_returns_at_most_limit_plus_one_rows():
    """NFR-603: при `limit=5` поставщик отдаёт не больше 6 строк (лишняя — признак «есть ещё»): 6 с начала, 2 со
    смещения 10 из 12, пусто за концом."""
    writer, reader = _world()
    _timeline(writer, 12)
    assert len(_urls(reader.user, "регламент", limit=5, offset=0)) == 6
    assert len(_urls(reader.user, "регламент", limit=5, offset=5)) == 6
    assert len(_urls(reader.user, "регламент", limit=5, offset=10)) == 2
    assert _urls(reader.user, "регламент", limit=5, offset=12) == []


def test_count_two_branches_limit_301_capped_at_300():
    """NFR-603: число — две ветки (записи и комментарии), каждая под `LIMIT 301`; сумма больше 300 даёт
    `(300, True)`, меньше — точное `(n, False)`."""
    writer, reader = _world()
    posts = [fd.make_post(writer.user, to=("all",), text="Запись про накладные") for _ in range(151)]
    assert _count(reader.user, "накладные") == (151, False)
    for post in posts:
        fd.comment(post, writer.user, "Комментарий про накладные")
    with fd.capture_sql() as sqls:
        number, capped = _count(reader.user, "накладные")
    assert (number, capped) == (300, True)
    limits = [match for sql in sqls for match in re.findall(r"\bLIMIT\s+301\b", sql, re.I)]
    assert len(limits) >= 2, f"ждали две ветки под LIMIT 301, нашли {len(limits)}"


# --- 5. модуль, параметры, текст запроса -------------------------------------------------------------------------

def test_without_feed_module_no_feed_group():
    """FR-641: без модуля `feed` группы «Лента» нет ни в сборщике, ни на странице `/search/`, прочие группы работают;
    с модулем группа на странице есть."""
    writer, reader = _world()
    fd.make_post(writer.user, to=("all",), text="Ромашка в ленте")
    lst = sl.make_list(created_by=support.make_employee())
    sl.make_record(lst, "Ромашка в списке")
    viewer = sl.as_reader(lst)
    page = viewer.client.get("/search/", {"q": "ромашка"}).content.decode("utf-8")
    assert 'data-search-group="feed"' in page and 'data-search-group="lists"' in page
    with fd.without_feed():
        assert "feed" not in _group_keys(viewer.user) and "lists" in _group_keys(viewer.user)
        page = viewer.client.get("/search/", {"q": "ромашка"}).content.decode("utf-8")
        assert 'data-search-group="feed"' not in page and 'data-search-group="lists"' in page
    assert "feed" in _group_keys(viewer.user)


def test_query_words_passed_as_parameters_not_in_sql_text():
    """NFR-608: слова запроса уходят в SQL параметрами: ни в одном запросе к таблицам ленты слова нет в тексте SQL,
    а среди параметров оно есть; запрос с кавычками и знаками `tsquery` не ломает выдачу и не трогает таблицу."""
    writer, reader = _world()
    post = fd.make_post(writer.user, to=("all",), text="Запись для проверки")
    fd.comment(post, writer.user, "Комментарий для проверки")
    marker = "zqxfeedword"
    with fd.queries_with_params() as pairs:
        _rows(reader.user, marker)
        _count(reader.user, marker)
    feed_pairs = [(sql, params) for sql, params in pairs if "feed_post" in sql or "feed_feedcomment" in sql]
    assert feed_pairs, "запросов к таблицам ленты не было"
    assert all(marker not in sql for sql, _ in feed_pairs), "слово запроса попало в текст SQL"

    def flat(params):
        out = []
        for value in params or ():
            out.extend(value if isinstance(value, (list, tuple, set)) else [value])
        return [str(item) for item in out]

    assert any(marker in item for _, params in feed_pairs for item in flat(params)), "слова нет среди параметров"
    for hostile in ("o'reilly", "a'b & c | !d :* (e)", "'; drop table feed_post; --", "проверки:* & !(x"):
        parsed = _parsed(hostile)
        _provider().search(_fresh(reader.user), parsed, 20, 0)
        _provider().count(_fresh(reader.user), parsed)
    assert model("feed.Post").objects.filter(pk=post.pk).exists()


def test_search_query_text_not_stored(caplog):
    """FR-636 (SPEC-005 FR-446): после запросов ко всем адресам поиска метки-слова нет ни в одной строке моделей базы,
    ни в журнале событий, ни в журнале приложения."""
    from django.apps import apps as registry

    marker = "zqxmarkerfeed"
    writer, reader = _world()
    fd.make_post(writer.user, to=("all",), text="Запись для поиска")
    Event = model("core.AuditEvent")
    before = Event.objects.count()
    caplog.set_level(logging.DEBUG)
    for path, params in (("/search/popup/", {"q": marker}), ("/search/", {"q": marker}),
                         ("/search/count/", {"q": marker, "group": "feed"}),
                         ("/search/more/", {"q": marker, "group": "feed", "offset": "0"})):
        assert reader.client.get(path, params).status_code == 200, path
    assert _urls(reader.user, marker) == [] and _count(reader.user, marker) == (0, False)
    assert Event.objects.count() == before
    holders = []
    for model_class in registry.get_models():
        if not model_class._meta.managed:
            continue
        for row in model_class._default_manager.values():
            if marker in str(row):
                holders.append(model_class._meta.label)
                break
    assert holders == [], f"запрос найден в моделях: {holders}"
    for record in caplog.records:
        if record.name.startswith("django.db"):
            continue
        text = " ".join([record.getMessage(), str(record.exc_text or ""), str(record.args),
                         str(record.__dict__.get("request", ""))])
        assert marker not in text, f"запрос в записи логгера {record.name}"


# --- 6. векторы -------------------------------------------------------------------------------------------------

def test_post_vector_event_title_place_weight_a_text_weight_b_without_markers():
    """FR-636: служба `search.vectors(post_ids=…)` строит вектор записи: название и место события — вес A, текст —
    вес B, маркер `@[id]` в вектор не идёт (номер не ищется)."""
    writer, _ = _world()
    mentioned = fd.as_plain()
    start = datetime(2026, 12, 20, 9, 0, tzinfo=dt_timezone.utc)
    event = fd.make_event(writer.user, start=start, title="Пожарная тревога", place="Главный корпус", to=("all",),
                          text="Эвакуация сотрудников", mentions=(mentioned.user,))
    _null_vectors(post=event)
    assert _post_weights(event, "пожарная") == set()
    _svc("search").vectors(post_ids=[event.pk])
    assert _post_weights(event, "пожарная") == {"A"}
    assert _post_weights(event, "корпус") == {"A"}
    assert _post_weights(event, "эвакуация") == {"B"}
    assert _post_weights(event, "сотрудников") == {"B"}
    assert _post_weights(event, str(mentioned.user.pk)) == set()


def test_comment_vector_kept_in_feed_comment_search(django_capture_on_commit_callbacks):
    """FR-636, FR-637: вектор комментария хранится в `FeedComment.search` (у `core.Comment` поля вектора нет): служба
    `search.vectors(comment_ids=…)` строит его, добавление комментария службой тоже заполняет его."""
    writer, reader = _world()
    post = fd.make_post(writer.user, to=("all",), text="Запись без искомых слов")
    comment = fd.comment(post, writer.user, "Заменили патч-корд")
    assert "search" not in {field.name for field in model("core.Comment")._meta.get_fields()}
    _null_vectors(comment=comment)
    assert not _comment_matches(comment, "патч-корд")
    _svc("search").vectors(comment_ids=[comment.pk])
    assert _comment_matches(comment, "патч-корд")
    with django_capture_on_commit_callbacks(execute=True):
        added = _svc("comments").add(reader.user, post.pk, "Проверили розетку")
    assert _comment_matches(added, "розетку")
    assert not _post_matches(post, "розетку")


def test_vectors_recomputed_in_publish_post_edit_and_comment_transactions(django_capture_on_commit_callbacks):
    """FR-637: вектор пересчитывается в самой транзакции публикации, правки записи, добавления и правки комментария:
    запись и комментарий находятся по новому тексту до выполнения действий «после фиксации»."""
    writer, reader = _world()
    with django_capture_on_commit_callbacks(execute=False):
        post = _svc("posts").publish(writer.user, {"kind": "post", "text": "Привезли кофемашину", "to": ["all"]})
        assert _post_matches(post, "кофемашину")
        _svc("posts").edit(writer.user, post.pk, {"text": "Привезли холодильник", "to": ["all"]})
        assert _post_matches(post, "холодильник") and not _post_matches(post, "кофемашину")
        comment = _svc("comments").add(reader.user, post.pk, "Поставили в кухне")
        assert _comment_matches(comment, "кухне")
        _svc("comments").edit(reader.user, comment.pk, "Поставили в переговорной")
        assert _comment_matches(comment, "переговорной") and not _comment_matches(comment, "кухне")


def test_file_contents_not_searched():
    """FR-636: содержимое файлов не ищется: слово, которое есть только внутри файла записи и комментария, ничего не
    находит."""
    writer, reader = _world()
    post = fd.make_post(writer.user, to=("all",), text="Запись с приложением")
    comment = fd.comment(post, writer.user, "Комментарий с приложением")
    fd.attach(post, "отчёт.txt", "хризолитовый отчёт о закупках".encode("utf-8"), write=True)
    fd.attach(comment, "акт.txt", "хризолитовый акт приёмки".encode("utf-8"), write=True)
    assert _rows(reader.user, "хризолитовый") == []
    assert _count(reader.user, "хризолитовый") == (0, False)
    assert len(_rows(reader.user, "приложением")) == 2
