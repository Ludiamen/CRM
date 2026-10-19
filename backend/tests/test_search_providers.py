"""T-5126: поставщики сквозного поиска — реестр, «Заявки», «Статьи» (FR-441, FR-442, FR-443, FR-444, FR-445, FR-447).

Сценарии 10 и 11 спеки среза 005. Поставщиков берут из сборщика `apps.search.services.providers(user)` (контракт 9.2),
по ключам `tickets` и `articles` (9.3), и вызывают их записи `SearchProvider.search/count` (3.2). «Заявки» — раздел 4.4,
«Статьи — два шага» — раздел 9.4 (`head_count` из `apps.knowledge.services.search`). Заявкам для поиска нужен столбец
`Ticket.search`: его строит `servicedesk.services.search.index` (прежняя служба среза 003); для тысячи заявок столбец
пишется одним запросом. Статьи создают фабрики `support_kb` (векторы — `set_vectors`) или службы `articles` (проверка
векторов и предела 100 000 знаков). Код среза 005 на уровне модуля не импортируется (шапка CONTRACT-005).
"""
import re
from datetime import timedelta

import pytest
from django.contrib.postgres.search import SearchQuery
from django.db import connection
from django.utils import timezone

from tests import support, support_servicedesk as sd
from tests import support_kb as kb
from tests.support import model

pytestmark = pytest.mark.django_db

BASE_NUMBER = 900_000          # номера заявок теста: выше любой последовательности стенда, ниже предела целого


# --- помощники файла: поставщики ---------------------------------------------------------------------------

def _fresh(user):
    return model("core.User").objects.get(pk=user.pk)


def _provider(user, group: str):
    """Запись поставщика группы `group` из сборщика (`search.services.providers`)."""
    from apps.search import services

    found = [item for item in services.providers(_fresh(user)) if item.key == group]
    assert found, f"сборщик не дал группу {group}"
    return found[0]


def _parsed(query: str):
    from apps.search.parse import parse

    return parse(query)


def _rows(user, group: str, query: str, limit: int = 20, offset: int = 0) -> list:
    return _provider(user, group).search(_fresh(user), _parsed(query), limit, offset)


def _count(user, group: str, query: str) -> tuple:
    return _provider(user, group).count(_fresh(user), _parsed(query))


def _ticket_numbers(rows) -> list[int]:
    """Номера заявок строк в порядке выдачи: из адреса `/tickets/<номер>/`."""
    return [int(re.fullmatch(r"/tickets/(\d+)/", row.url).group(1)) for row in rows]


def _article_ids(rows) -> list[int]:
    return [int(re.fullmatch(r"/kb/(\d+)/", row.url).group(1)) for row in rows]


# --- помощники файла: заявки -------------------------------------------------------------------------------

def _ticket(subject: str, *, queue, number: int | None = None, assignee=None):
    """Заявка фабрикой со столбцом поиска, собранным службой `search.index` (номер, тема, заявитель)."""
    from apps.servicedesk.services import search

    ticket = sd.make_ticket(queue=queue, subject=subject, number=number, assignee=assignee)
    search.index(ticket)
    return ticket


def _bulk_tickets(count: int, subject: str, queue) -> None:
    """`count` заявок с одной темой одним `bulk_create`; столбец поиска — одним `UPDATE` (номер и тема, как у `index`)."""
    Ticket = model("servicedesk.Ticket")
    template = sd.make_ticket(queue=queue, subject=subject)
    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval('servicedesk_ticket_number') FROM generate_series(1, %s)", [count - 1])
        numbers = [row[0] for row in cursor.fetchall()]
    Ticket.objects.bulk_create([
        Ticket(number=number, subject=subject, requester=template.requester, requester_email=template.requester_email,
               requester_name=template.requester_name, queue=template.queue, priority=template.priority,
               status=template.status, kind=template.kind, source=template.source, created_at=template.created_at,
               last_message_at=template.last_message_at) for number in numbers])
    assert Ticket._meta.db_table == "servicedesk_ticket"
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE servicedesk_ticket SET search = to_tsvector('russian', number::text || ' ' || subject) "
            "WHERE subject = %s", [subject])
    assert Ticket.objects.filter(subject=subject).count() == count


def _holder():
    """Сотрудник с правом «Все заявки»: видит любую заявку."""
    return support.make_with_permissions("servicedesk.all")


# --- помощники файла: статьи -------------------------------------------------------------------------------

def _article_service():
    import importlib

    return importlib.import_module("apps.knowledge.services.articles")


def _form(**over):
    values = dict(title="Принтер", text="Текст статьи", rubric_id=kb.general_rubric().pk, tags="", comment="")
    values.update(over)
    return _article_service().ArticleForm(**values)


def _head_count(query: str) -> int:
    from apps.knowledge.services import search

    return search.head_count(_parsed(query))


def _hit(article, column: str, word: str) -> bool:
    """Совпадает ли столбец вектора статьи (`search_head` или `search_full`) со словом."""
    return model("knowledge.Article").objects.filter(
        pk=article.pk, **{column: SearchQuery(word, config="russian")}).exists()


def _step2_articles(count: int, word: str, author) -> list:
    """`count` опубликованных статей, где слово есть только в тексте (в заголовке его нет): шаг 2."""
    return [kb.make_published(title=f"Заметка {number}", text=f"{word} заметка", author=author) for number in range(count)]


# --- реестр ------------------------------------------------------------------------------------------------

def test_assembler_runs_extra_registered_provider_without_changes():
    """FR-445: запись, добавленная в точку `search_providers`, попадает в выдачу без правки `search`: группа стоит по
    `order` среди прежних, при равном `order` — в порядке регистрации; её `search` вызывается с запросом и правами."""
    from apps.core import extensions
    from apps.search import services

    viewer = _holder()
    calls = []

    def make_provider(group: str, order: int):
        def search(user, parsed, limit, offset):
            calls.append((group, user.pk, parsed.raw, limit, offset))
            return [extensions.SearchRow(title=f"Строка {group}", subtitle="", url=f"/extra/{group}/")]

        def available(user):
            return True

        return extensions.SearchProvider(group, f"Группа {group}", order, search, lambda user, parsed: (1, False),
                                         available)

    first, second = make_provider("extra_a", 15), make_provider("extra_b", 15)
    registry = extensions._registry["search_providers"]
    saved = list(registry)

    def register_first():
        return [first]

    def register_second():
        return [second]

    try:
        extensions.register("search_providers", register_first)
        extensions.register("search_providers", register_second)
        order = [item.key for item in services.providers(_fresh(viewer))]
        groups = services.page(_fresh(viewer), _parsed("принтер"))
    finally:
        registry[:] = saved
    assert order.index("extra_a") < order.index("extra_b")
    assert order.index("tickets") < order.index("extra_a") and order.index("extra_b") < order.index("articles")
    assert [item.key for item in groups if item.key.startswith("extra_")] == ["extra_a", "extra_b"]
    extra = next(item for item in groups if item.key == "extra_a")
    assert extra.title == "Группа extra_a" and [row.title for row in extra.rows] == ["Строка extra_a"]
    assert ("extra_a", viewer.pk, "принтер:*", services.PAGE_LIMIT, 0) in calls
    assert "extra_a" not in [item.key for item in services.providers(_fresh(viewer))]


# --- заявки ------------------------------------------------------------------------------------------------

def test_tickets_found_by_subject_word_start_and_other_word_form_all_words_required():
    """FR-443: слово ищется по началу и словоформе («принт», «принтеру» находят «принтера»); все слова должны
    совпасть: лишнее слово, которого нет в заявке, убирает её из выдачи."""
    queue = sd.make_queue()
    viewer = _holder()
    with_both = _ticket("Поломка принтера и монитора", queue=queue)
    only_printer = _ticket("Принтер на втором этаже", queue=queue)
    _ticket("Нет сети в кабинете", queue=queue)
    for query in ("принт", "принтеру", "принтерами"):
        assert set(_ticket_numbers(_rows(viewer, "tickets", query))) == {with_both.number, only_printer.number}, query
    assert _ticket_numbers(_rows(viewer, "tickets", "принтер монитор")) == [with_both.number]
    assert _ticket_numbers(_rows(viewer, "tickets", "принтер ноутбук")) == []


def test_tickets_only_visible_to_user():
    """FR-444: в группе только заявки, видимые сотруднику (SPEC-003 FR-234): свою по ответственности он находит,
    чужую с тем же словом — нет; держатель «Все заявки» видит обе; число группы считает только видимые."""
    queue = sd.make_queue()
    plain = support.make_employee()
    own = _ticket("Принтер в бухгалтерии", queue=queue, assignee=plain)
    foreign = _ticket("Принтер в приёмной", queue=queue)
    assert _ticket_numbers(_rows(plain, "tickets", "принтер")) == [own.number]
    assert _count(plain, "tickets", "принтер") == (1, False)
    assert set(_ticket_numbers(_rows(_holder(), "tickets", "принтер"))) == {own.number, foreign.number}


def test_invisible_ticket_number_gives_no_row():
    """FR-444: заявка, найденная по номеру, но невидимая сотруднику, строки не даёт — не отличается от несуществующей;
    тому, кто её видит, та же заявка по тому же номеру — первая строка."""
    queue = sd.make_queue()
    plain = support.make_employee()
    _ticket("Заявка сотрудника", queue=queue, number=BASE_NUMBER + 1, assignee=plain)
    hidden = _ticket("Чужая заявка", queue=queue, number=BASE_NUMBER + 2)
    query = f"#{hidden.number}"
    assert _rows(plain, "tickets", query) == []
    assert _rows(plain, "tickets", str(hidden.number)) == []
    assert _ticket_numbers(_rows(_holder(), "tickets", query)) == [hidden.number]


def test_ticket_row_has_number_subject_state_queue_and_url():
    """FR-441: строка заявки — «#N Тема», состояние и очередь одной строкой, адрес `/tickets/<N>/`, шаблон строки
    `search/rows/_ticket.html` с названием состояния и очереди в `context`."""
    queue = sd.make_queue()
    ticket = _ticket("Поломка принтера", queue=queue)
    rows = _rows(_holder(), "tickets", "принтер")
    assert len(rows) == 1
    row = rows[0]
    assert row.title == f"#{ticket.number} Поломка принтера"
    assert row.url == f"/tickets/{ticket.number}/"
    assert row.template == "search/rows/_ticket.html"
    assert row.context["state"] == ticket.status.name
    assert row.context["queue"] == queue.unit.name
    assert ticket.status.name in row.subtitle and queue.unit.name in row.subtitle


def test_ticket_by_number_is_first_without_duplicate_in_main_selection():
    """FR-443: «900123» ищет и заявку с этим номером: она первая в группе и один раз, остальные совпадения текста идут
    за ней по номеру вниз."""
    queue = sd.make_queue()
    number = BASE_NUMBER + 123
    target = _ticket("Сеть не работает", queue=queue, number=number)
    older = _ticket(f"Повтор заказа {number}", queue=queue, number=BASE_NUMBER + 124)
    newer = _ticket(f"Ссылка на заказ {number}", queue=queue, number=BASE_NUMBER + 125)
    _ticket("Заявка про другое", queue=queue, number=BASE_NUMBER + 126)
    for query in (str(number), f"#{number}"):
        numbers = _ticket_numbers(_rows(_holder(), "tickets", query))
        assert numbers == [target.number, newer.number, older.number], query
        assert numbers.count(target.number) == 1


def _twenty_five_with_number_row(queue):
    """25 заявок, где в теме есть номер 900500, и заявка с этим номером. Возвращает (заявка по номеру, основные номера)."""
    number = BASE_NUMBER + 500
    target = _ticket("Заявка по номеру", queue=queue, number=number)
    main = [_ticket(f"Заказ {number} позиция {index}", queue=queue, number=BASE_NUMBER + 600 + index).number
            for index in range(25)]
    return target, sorted(main, reverse=True)


def test_ticket_number_row_sits_above_twenty_main_rows_on_first_page():
    """FR-442, FR-443: на первой странице строка по номеру стоит над двадцатью основными строками сверх `limit`
    (21 строка), основные — по номеру вниз."""
    queue = sd.make_queue()
    target, main = _twenty_five_with_number_row(queue)
    numbers = _ticket_numbers(_rows(_holder(), "tickets", str(target.number), limit=20, offset=0))
    assert len(numbers) == 21
    assert numbers[0] == target.number
    assert numbers[1:] == main[:20]


def test_ticket_show_more_keeps_number_row_out_and_loses_no_row():
    """FR-442: «Показать ещё» (offset 20) не повторяет строку по номеру, смещение считается по основному запросу:
    вторая страница — остальные пять основных строк, вместе со страницей один ни одной потерянной и повторённой."""
    queue = sd.make_queue()
    target, main = _twenty_five_with_number_row(queue)
    viewer = _holder()
    first = _ticket_numbers(_rows(viewer, "tickets", str(target.number), limit=20, offset=0))
    second = _ticket_numbers(_rows(viewer, "tickets", str(target.number), limit=20, offset=20))
    assert target.number not in second
    assert second == main[20:]
    assert first[1:] + second == main and len(set(first + second)) == 26


def test_ticket_count_capped_at_1001_shows_1000_plus():
    """FR-442: 1001 подходящая заявка — подсчёт упирается в потолок: `(1000, True)`, страница пишет «1000+»."""
    queue = sd.make_queue()
    _bulk_tickets(1001, "Принтер в архиве", queue)
    assert _count(_holder(), "tickets", "принтер") == (1000, True)


def test_ticket_count_below_cap_is_exact():
    """FR-442: ровно 1000 заявок — число точное, без плюса: `(1000, False)`; малая группа считается точно (3)."""
    queue = sd.make_queue()
    viewer = _holder()
    _bulk_tickets(1000, "Принтер в архиве", queue)
    for index in range(3):
        _ticket(f"Сканер номер {index}", queue=queue)
    assert _count(viewer, "tickets", "принтер") == (1000, False)
    assert _count(viewer, "tickets", "сканер") == (3, False)


# --- статьи: отбор и строка --------------------------------------------------------------------------------

def test_articles_only_published_in_results():
    """FR-444, FR-447: в группе «Статьи» только опубликованные; черновик и статья в корзине с тем же словом не
    находятся (у них векторы пусты), опубликованная — находится."""
    reader = kb.as_reader().user
    published = kb.make_published(title="Принтер: настройка")
    draft = kb.make_draft(title="Принтер: черновик")
    trashed = kb.make_trashed(title="Принтер: удалена")
    assert draft.search_head is None and trashed.search_head is None
    assert _article_ids(_rows(reader, "articles", "принтер")) == [published.pk]


def test_draft_and_trashed_articles_hidden_from_author_and_manager():
    """FR-444, FR-447: черновик и статья в корзине не выдаются и автору, и управляющему; опубликованная — выдаётся."""
    author = kb.as_editor().user
    manager = kb.as_manager().user
    published = kb.make_published(title="Принтер в бухгалтерии", author=author)
    kb.make_draft(title="Принтер в черновике автора", author=author)
    kb.make_trashed(title="Принтер в корзине автора", author=author)
    kb.make_draft(title="Принтер в чужом черновике")
    for user in (author, manager):
        assert _article_ids(_rows(user, "articles", "принтер")) == [published.pk]
        assert _count(user, "articles", "принтер") == (1, False)


def test_article_row_has_title_rubric_and_kb_url():
    """FR-441: строка статьи — заголовок, название рубрики, адрес `/kb/<id>/`; шаблон строки общий (пустой)."""
    rubric = kb.make_rubric("Сети и доступ")
    article = kb.make_published(title="Как настроить принтер", rubric=rubric)
    rows = _rows(kb.as_reader().user, "articles", "принтер")
    assert len(rows) == 1
    assert rows[0].title == "Как настроить принтер"
    assert rows[0].subtitle == "Сети и доступ"
    assert rows[0].url == f"/kb/{article.pk}/"
    assert rows[0].template == ""


# --- статьи: совпадение ------------------------------------------------------------------------------------

def test_article_found_by_other_word_form():
    """FR-443: словоформа находит статью: «принтерами» и «принтер» — по заголовку «Настройка принтеров»;
    регистр и «е/ё» не важны."""
    reader = kb.as_reader().user
    article = kb.make_published(title="Настройка принтеров", text="Шаги для администратора")
    kb.make_published(title="Настройка сети", text="Шаги для администратора")
    for query in ("принтерами", "принтер", "ПРИНТЕР", "принт"):
        assert _article_ids(_rows(reader, "articles", query)) == [article.pk], query


def test_article_found_by_title_tags_and_body():
    """FR-443: статья находится по заголовку, по тегу и по тексту; каждый запрос находит ровно свою статью."""
    reader = kb.as_reader().user
    by_title = kb.make_published(title="Принтер", text="Общий текст")
    by_tag = kb.make_published(title="Заметка про доступ", text="Общий текст", tags=("vpn",))
    by_body = kb.make_published(title="Заметка про оборудование", text="Нужен новый монитор")
    assert _article_ids(_rows(reader, "articles", "принтер")) == [by_title.pk]
    assert _article_ids(_rows(reader, "articles", "vpn")) == [by_tag.pk]
    assert _article_ids(_rows(reader, "articles", "монитор")) == [by_body.pk]


def test_article_all_words_must_match():
    """FR-443: все слова запроса должны совпасть; слова могут быть в заголовке, тегах и тексте вперемешку;
    слово, которого нет нигде, убирает статью."""
    reader = kb.as_reader().user
    full = kb.make_published(title="Принтер", text="Рядом стоит монитор")
    kb.make_published(title="Принтер", text="Рядом стоит сканер")
    assert _article_ids(_rows(reader, "articles", "принтер монитор")) == [full.pk]
    assert _article_ids(_rows(reader, "articles", "монитор принтер")) == [full.pk]
    assert _article_ids(_rows(reader, "articles", "принтер роутер")) == []


def test_article_body_indexed_only_first_100000_chars():
    """FR-443: в индекс идёт только начало текста — первые 100 000 знаков `plain`: слово внутри предела статью
    находит, слово за пределом — нет (статья создана и опубликована службами)."""
    articles = _article_service()
    user = kb.as_editor().user
    inside, outside = "зиндар", "квазор"
    text = "дом " * 24_990 + inside + " " + "дом " * 20 + outside
    assert text.index(outside) > 100_000 > text.index(inside) + len(inside)
    article = articles.create(user, _form(title="Длинная статья", text=text))
    articles.publish(user, article.pk, 1)
    reader = kb.as_reader().user
    assert _article_ids(_rows(reader, "articles", inside)) == [article.pk]
    assert _rows(reader, "articles", outside) == []
    stored = model("knowledge.Article").objects.get(pk=article.pk)
    assert len(stored.plain) <= 100_000
    assert not _hit(stored, "search_full", outside)


# --- статьи: два шага --------------------------------------------------------------------------------------

def test_article_step1_all_words_in_head_ranks_above_step2(clock):
    """FR-443: статья, где все слова запроса в заголовке и тегах (шаг 1), стоит выше статьи, где слова разнесены
    между заголовком и текстом (шаг 2), даже если вторая правилась позже."""
    reader = kb.as_reader().user
    clock.set(kb.moscow(2026, 3, 10, 9))
    head_article = kb.make_published(title="Принтер и монитор", text="Общий текст")
    clock.advance(hours=5)
    body_article = kb.make_published(title="Принтер", text="Рядом стоит монитор")
    assert _head_count("принтер монитор") == 1
    assert _article_ids(_rows(reader, "articles", "принтер монитор")) == [head_article.pk, body_article.pk]


def test_article_split_words_head_and_body_goes_to_step2():
    """FR-443: одно слово в заголовке, другое в тексте — статья в шаге 2: в малом векторе её нет (`head_count` 0),
    выдача её находит."""
    reader = kb.as_reader().user
    article = kb.make_published(title="Принтер", text="Рядом стоит монитор")
    assert _head_count("принтер монитор") == 0
    assert _article_ids(_rows(reader, "articles", "принтер монитор")) == [article.pk]
    assert _hit(article, "search_full", "принтер монитор")
    assert not _hit(article, "search_head", "принтер монитор")


def test_article_step2_ordered_by_recency(clock):
    """FR-443: шаг 2 идёт по времени правки: свежая статья выше старой, порядок не зависит от порядка создания."""
    reader = kb.as_reader().user
    author = kb.as_editor().user
    clock.set(kb.moscow(2026, 3, 10, 9))
    middle = kb.make_published(title="Заметка про оборудование", text="Нужен монитор", author=author)
    clock.advance(days=1)
    newest = kb.make_published(title="Заметка про закупки", text="Нужен монитор", author=author)
    clock.set(kb.moscow(2026, 3, 8, 9))
    oldest = kb.make_published(title="Заметка про склад", text="Нужен монитор", author=author)
    assert _head_count("монитор") == 0
    assert _article_ids(_rows(reader, "articles", "монитор")) == [newest.pk, middle.pk, oldest.pk]


def test_article_step2_capped_at_300_candidates():
    """FR-443: шаг 2 берёт не больше 300 кандидатов — самых новых по `updated_at DESC, id DESC` (контракт, раздел 17,
    п. 28): при 305 подходящих статьях выдача — 300 строк, число — `(300, True)`, пять самых старых в выдаче нет."""
    reader = kb.as_reader().user
    articles = _step2_articles(305, "монитор", kb.as_editor().user)
    base = timezone.now()
    # время правки убывает с ростом номера в списке: самые старые — последние пять (и не самые новые по `id`)
    for index, article in enumerate(articles):
        model("knowledge.Article").objects.filter(pk=article.pk).update(updated_at=base - timedelta(minutes=index))
    rows = _rows(reader, "articles", "монитор", limit=400, offset=0)
    assert len(rows) == 300 and len(set(_article_ids(rows))) == 300
    assert set(_article_ids(rows)) == {article.pk for article in articles[:300]}
    assert not {article.pk for article in articles[300:]} & set(_article_ids(rows))
    assert _count(reader, "articles", "монитор") == (300, True)


def test_article_count_has_plus_when_step2_hits_cap():
    """FR-442: 2 статьи шага 1 и 301 шага 2 — число `(2 + 300, True)`: страница пишет «302+»."""
    reader = kb.as_reader().user
    author = kb.as_editor().user
    kb.make_published(title="Монитор Dell", author=author)
    kb.make_published(title="Монитор Samsung", author=author)
    _step2_articles(301, "монитор", author)
    assert _head_count("монитор") == 2
    assert _count(reader, "articles", "монитор") == (302, True)


def test_article_count_exact_when_step2_below_cap():
    """FR-442: 2 статьи шага 1 и 3 шага 2 — число точное `(5, False)`, без плюса; черновик с тем же словом не считается."""
    reader = kb.as_reader().user
    author = kb.as_editor().user
    kb.make_published(title="Монитор Dell", author=author)
    kb.make_published(title="Монитор Samsung", author=author)
    _step2_articles(3, "монитор", author)
    kb.make_draft(title="Монитор в черновике", author=author)
    assert _count(reader, "articles", "монитор") == (5, False)


def test_article_offset_crosses_step_boundary_without_loss_or_repeat(clock):
    """FR-442: «Показать ещё» на границе шагов не теряет и не повторяет строк: при 3 статьях шага 1 и 4 шага 2
    страницы по 1, 2, 3 и 4 строки в сумме дают ту же выдачу, что один вызов, шаг 1 идёт первым."""
    reader = kb.as_reader().user
    author = kb.as_editor().user
    clock.set(kb.moscow(2026, 3, 10, 9))
    head = []
    for index in range(3):
        clock.advance(hours=1)
        head.append(kb.make_published(title=f"Монитор модель {index}", author=author).pk)
    body = []
    for index in range(4):
        clock.advance(hours=1)
        body.append(kb.make_published(title=f"Заметка {index}", text="Нужен монитор", author=author).pk)
    assert _head_count("монитор") == 3
    full = _article_ids(_rows(reader, "articles", "монитор", limit=100, offset=0))
    assert len(full) == 7 and set(full[:3]) == set(head) and set(full[3:]) == set(body)
    for size in (1, 2, 3, 4):
        paged = []
        for offset in range(0, 8, size):
            paged += _article_ids(_rows(reader, "articles", "монитор", limit=size, offset=offset))
        assert paged == full, size


# --- статьи: векторы ---------------------------------------------------------------------------------------

def test_article_vectors_updated_on_save_publish_trash_restore():
    """FR-447: векторы поиска — `NULL` у черновика; при публикации заполняются; при сохранении опубликованной
    пересчитываются (старое слово не находится, новое находится); при удалении в корзину — `NULL`; при возврате
    опубликованной — считаются заново. Группа «Статьи» повторяет это в выдаче."""
    articles = _article_service()
    manager = kb.as_manager().user
    reader = kb.as_reader().user
    Article = model("knowledge.Article")
    created = articles.create(manager, _form(title="Принтер", text="сканер документов", tags="vpn"))
    draft = Article.objects.get(pk=created.pk)
    assert draft.search_head is None and draft.search_full is None
    assert _rows(reader, "articles", "принтер") == []

    articles.publish(manager, created.pk, 1)
    article = Article.objects.get(pk=created.pk)
    assert _hit(article, "search_head", "принтер") and _hit(article, "search_head", "vpn")
    assert _hit(article, "search_full", "сканер")
    assert _article_ids(_rows(reader, "articles", "сканер")) == [article.pk]

    assert articles.save(manager, created.pk, 1, _form(title="Картридж", text="заправка тонер", tags="wifi")).kind == "saved"
    article = Article.objects.get(pk=created.pk)
    assert _hit(article, "search_head", "картридж") and _hit(article, "search_head", "wifi")
    assert _hit(article, "search_full", "тонер")
    assert not _hit(article, "search_head", "принтер") and not _hit(article, "search_full", "сканер")
    assert not _hit(article, "search_head", "vpn")
    assert _rows(reader, "articles", "сканер") == []
    assert _article_ids(_rows(reader, "articles", "тонер")) == [article.pk]

    articles.trash(manager, created.pk)
    article = Article.objects.get(pk=created.pk)
    assert article.search_head is None and article.search_full is None
    assert _rows(reader, "articles", "тонер") == []

    articles.restore(manager, created.pk)
    article = Article.objects.get(pk=created.pk)
    assert article.state == "published"
    assert _hit(article, "search_head", "картридж") and _hit(article, "search_full", "тонер")
    assert _article_ids(_rows(reader, "articles", "тонер")) == [article.pk]
