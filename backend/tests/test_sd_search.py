"""T-3125: поиск заявок и столбец `Ticket.search` (FR-278, FR-290, NFR-213). Сценарий 14 спеки среза 003.

Службы — `apps.servicedesk.services.search` (CONTRACT-003 § 6.21: `parse`, `apply`, `search`, `index`, `rebuild`,
`write_vector`), `tickets.create`, `tickets.add_incoming`, `tickets.update_fields`, `replies.reply`,
`replies.comment`, `retention.anonymize_one`; зацепки списка — § 13.2, текст подсказки — § 14.2. Заявки, которым нужен
столбец поиска, создаются службой `tickets.create` (фабрика `make_ticket` ходит мимо неё и столбца не строит); заявки
для проверки номера — фабрикой, их столбец пуст. Код среза на уровне модуля не импортируется (шапка контракта).
Тесты идут в обычной `django_db` без выполнения `on_commit`: запись вектора, сделанная после фиксации, не будет видна.
"""
import re

import pytest
from django.db import DataError

from tests import factories, support, support_org, support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

HINT_PHRASE = "введите хотя бы 2 буквы"      # CONTRACT-003 § 14.2; регистр первой буквы не проверяется (§ 14)


# --- помощники файла -------------------------------------------------------------------------------------

def _desk():
    """Очередь по умолчанию и домены: приём открыт; возвращает очередь."""
    queue = sd.make_queue()
    sd.configure_servicedesk(domains=["corp.test"], default_queue=queue)
    return queue


def _holder():
    """Сотрудник с правом «Все заявки»: видит и ведёт любую заявку."""
    return support.make_with_permissions("servicedesk.all")


def _fresh(user):
    return model("core.User").objects.get(pk=user.pk)


def _mk(subject="Не работает принтер", text="Принтер на втором этаже не печатает", name="", email=None, queue=None):
    """Заявка службой `tickets.create` (письмо): столбец `search` строится как у настоящей заявки."""
    from apps.servicedesk.services import tickets

    kw = {}
    if queue is not None:
        kw["category"] = sd.make_category(queue=queue)
    created = tickets.create(
        channel=tickets.MAIL, subject=subject, text=text, requester_email=email or factories.new_email("req"),
        requester_name=name, inbound_id=sd.make_inbound().pk, **kw)
    return created.ticket


def _incoming(ticket, text, **kw):
    from apps.servicedesk.services import tickets

    return tickets.add_incoming(ticket, author_email=factories.new_email("req"), text=text, **kw)


def _found(user, query, limit=50) -> list[int]:
    """Номера заявок результата `search.search` в порядке выдачи."""
    from apps.servicedesk.services import search

    return [t.number for t in search.search(_fresh(user), query, limit).tickets]


def _in_column(ticket, tsquery: str) -> bool:
    """Совпадает ли столбец `search` заявки с запросом `to_tsquery('russian', …)` (проверка самого столбца)."""
    from django.contrib.postgres.search import SearchQuery

    query = SearchQuery(tsquery, config="russian", search_type="raw")
    return model("servicedesk.Ticket").objects.filter(pk=ticket.pk, search=query).exists()


def _padded(head: str, tail: str, length: int) -> str:
    """Текст ровно `length` знаков: слово `head` в начале, слово `tail` в самом конце, между ними — повторы «дом»."""
    pad = length - len(head) - len(tail) - 2
    filler = ("дом " * (pad // 4 + 1))[:pad]
    text = f"{head} {filler} {tail}"
    assert len(text) == length
    return text


def _grid_numbers(response) -> set[int]:
    """Номера строк сетки: `tr[data-ticket="<номер>"]` (§ 13.2)."""
    return {int(n) for n in re.findall(r'<tr[^>]*\bdata-ticket="(\d+)"', response.content.decode("utf-8", "replace"))}


def _hint_text(response) -> str | None:
    """Текст элемента `[data-hint="short"]` или `None`, если его нет (§ 13.2)."""
    match = re.search(r'<([a-z0-9]+)\b[^>]*\bdata-hint="short"[^>]*>(.*?)</\1>',
                      response.content.decode("utf-8", "replace"), re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", match.group(2)).split()) if match else None


# --- запрос: слова, «ё», словоформы, приставка ----------------------------------------------------------

def test_search_yo_and_ye_give_same_tickets():
    """FR-278: «еж» и «ёж» находят одни и те же заявки (конфигурация `russian` сводит «е» и «ё», своих замен нет)."""
    _desk()
    holder = _holder()
    with_yo = _mk(subject="Ёж в серверной", text="Нашли в стойке")
    with_ye = _mk(subject="Еж у входа", text="Нашли у двери")
    _mk(subject="Дверь не закрывается", text="Заедает замок")
    by_ye, by_yo, by_upper = _found(holder, "еж"), _found(holder, "ёж"), _found(holder, "ЁЖ")
    assert set(by_ye) == set(by_yo) == set(by_upper) == {with_yo.number, with_ye.number}


def test_search_word_forms_found():
    """FR-278: словоформы находятся (русская морфология конфигурации `russian`): «принтера» — по «принтер»."""
    _desk()
    holder = _holder()
    ticket = _mk(subject="Поломка принтера", text="Из мониторов виден только один")
    _mk(subject="Нет сети", text="Кабель отошёл")
    for query in ("принтер", "принтеру", "принтерами", "монитор", "монитора"):
        assert _found(holder, query) == [ticket.number], query


def test_search_prefix_found():
    """FR-278: слово ищется как приставка («принт» находит «принтер»); середина слова не находится."""
    _desk()
    holder = _holder()
    ticket = _mk(subject="Принтер на втором этаже", text="Не печатает")
    assert _found(holder, "принт") == [ticket.number]
    assert _found(holder, "прин") == [ticket.number]
    assert _found(holder, "нтер") == []


def test_search_by_part_of_address():
    """FR-278: адрес заявителя находится по части («ivanov», «corp») и целиком; «@ . _ / -» в столбце — пробелы."""
    _desk()
    holder = _holder()
    ticket = _mk(subject="Нет доступа", text="Прошу открыть", email="Ivanov.Petr@corp.test")
    other = _mk(subject="Нет доступа к почте", text="Прошу открыть", email=factories.new_email("req"))
    assert _found(holder, "ivanov") == [ticket.number]
    assert _found(holder, "petr") == [ticket.number]
    assert _found(holder, "ivanov.petr@corp.test") == [ticket.number]
    assert ticket.number in _found(holder, "corp") and other.number not in _found(holder, "ivanov")


def test_search_by_requester_name_case_insensitive():
    """FR-278: ФИО заявителя ищется без учёта регистра и «е/ё»."""
    _desk()
    holder = _holder()
    ticket = _mk(subject="Нет доступа", text="Прошу открыть", name="Иванов Пётр Сергеевич")
    _mk(subject="Нет доступа к почте", text="Прошу открыть", name="Сидоров Олег")
    for query in ("иванов", "ИВАНОВ", "ИвАнОв", "петр", "ПЕТР", "пётр", "Иванов Пётр"):
        assert _found(holder, query) == [ticket.number], query


def test_search_by_subject_and_message_text():
    """FR-278: тема и текст сообщения — разные места поиска; находятся оба, лишнего нет; порядок — по номеру вниз."""
    _desk()
    holder = _holder()
    by_subject = _mk(subject="Сломался сканер бухгалтерии", text="Ничего не работает")
    by_text = _mk(subject="Просьба", text="Не включается сканер после обновления")
    unrelated = _mk(subject="Просьба о доступе", text="Нужен доступ к папке")
    assert _found(holder, "сканер") == [by_text.number, by_subject.number]
    assert unrelated.number not in _found(holder, "сканер")
    assert _found(holder, "бухгалтерии") == [by_subject.number]
    assert _found(holder, "обновления") == [by_text.number]
    assert _found(holder, "сканер", 1) == [by_text.number]


# --- номер и короткие слова -----------------------------------------------------------------------------

def test_search_by_number_and_hash_number():
    """FR-278: «123» и «#123» — точное совпадение номера плюс поиск по тексту; «1230» точно не совпадает."""
    from apps.servicedesk.services import search

    _desk()
    holder = _holder()
    exact = sd.make_ticket(number=123, subject="Без связи")               # столбец пуст: находится только по номеру
    sd.make_ticket(number=1230, subject="Без связи")
    by_text = sd.make_ticket(number=7, subject="Заказ 123 офис")
    search.rebuild(by_text)
    sd.make_ticket(number=8, subject="Совсем другое")
    assert search.parse("#123").number == 123 and search.parse("123").number == 123
    assert _found(holder, "123") == [exact.number, by_text.number]
    assert _found(holder, "#123") == [exact.number, by_text.number]


def test_search_hash_number_works_with_short_word():
    """FR-278: «#5» (слово короче двух знаков) ищет заявку №5 точно; текстового запроса нет, подсказки нет."""
    from apps.servicedesk.services import search

    _desk()
    holder = _holder()
    target = sd.make_ticket(number=5, subject="Без связи")
    sd.make_ticket(number=55, subject="Без связи")
    sd.make_ticket(number=6, subject="Без связи")
    parsed = search.parse("#5")
    assert (parsed.number, parsed.words, parsed.raw, parsed.hint) == (5, [], "", "")
    assert _found(holder, "#5") == [target.number]
    assert _found(holder, "5") == [target.number]
    assert search.search(_fresh(holder), "#5", 50).hint == ""


def test_search_stop_words_only_gives_empty_list_without_error():
    """FR-278: слова только из стоп-слов («не на и») дают пустой список без ошибки; подсказки «2 буквы» нет."""
    from apps.servicedesk.services import search

    _desk()
    holder = _holder()
    _mk(subject="Не работает принтер", text="Принтер на втором этаже не печатает")
    parsed = search.parse("не на и")
    assert parsed.words == ["не", "на"] and parsed.raw == "не:* & на:*" and parsed.hint == ""   # «и» — один знак
    result = search.search(_fresh(holder), "не на и", 50)
    assert result.tickets == [] and result.hint == ""
    response = support.logged_in(holder).get("/tickets/", {"preset": "all", "q": "не на и"})
    assert response.status_code == 200
    assert not _grid_numbers(response) and _hint_text(response) is None


def test_search_words_shorter_than_two_chars_skipped_with_hint():
    """FR-278: слова короче двух знаков пропускаются; остались только они — подсказка «введите хотя бы 2 буквы»."""
    from apps.servicedesk.services import search

    _desk()
    holder = _holder()
    ticket = _mk(subject="Не работает принтер", text="Принтер на втором этаже не печатает")
    other = _mk(subject="Нет сети", text="Кабель отошёл")
    parsed = search.parse("а б в")
    assert (parsed.words, parsed.number, parsed.raw, parsed.hint) == ([], None, "", "short")
    result = search.search(_fresh(holder), "а б", 50)
    assert result.hint == "short" and {t.number for t in result.tickets} == {ticket.number, other.number}
    mixed = search.parse("а принтер")
    assert (mixed.words, mixed.raw, mixed.hint) == (["принтер"], "принтер:*", "")
    assert _found(holder, "а принтер") == [ticket.number]
    client = support.logged_in(holder)
    short = client.get("/tickets/", {"preset": "all", "q": "а б"})
    assert short.status_code == 200 and HINT_PHRASE[1:] in (_hint_text(short) or "")
    good = client.get("/tickets/", {"preset": "all", "q": "а принтер"})
    assert _hint_text(good) is None and _grid_numbers(good) == {ticket.number}


def test_search_more_than_eight_words_cut_to_eight():
    """FR-278: берутся не больше восьми слов запроса, лишние отброшены (по порядку); заявка с первыми восемью — найдена."""
    from apps.servicedesk.services import search

    _desk()
    holder = _holder()
    words = ["кабель", "монитор", "сервер", "принтер", "клавиатура", "роутер", "коммутатор", "розетка",
             "картридж", "сканер"]
    query = " ".join(words[:3] + ["а"] + words[3:])    # короткое слово среди первых восьми: сначала отбрасывается (доп. 32 (а))
    parsed = search.parse(query)
    assert parsed.words == words[:8]
    assert parsed.raw == " & ".join(f"{w}:*" for w in words[:8])
    only_eight = _mk(subject="Комплект", text=" ".join(words[:8]))
    all_ten = _mk(subject="Комплект целиком", text=" ".join(words))
    without_third = _mk(subject="Комплект без одного", text=" ".join(words[:2] + words[3:8]))
    assert _found(holder, query) == [all_ten.number, only_eight.number]
    assert without_third.number not in _found(holder, query)


# --- безопасность запроса -------------------------------------------------------------------------------

def test_search_special_chars_and_quotes_do_not_break_query():
    """FR-278, NFR-213: кавычки, скобки, «& | ! : * <->», обратная косая не ломают запрос; слова находятся."""
    from apps.servicedesk.services import search

    _desk()
    holder = _holder()
    ticket = _mk(subject="Принтер и сканер", text="Не работают оба")
    queries = ['принтер "сканер"', "принтер 'сканер'", "(принтер) & (сканер)", "принтер | сканер", "!принтер",
               "принтер:* <-> сканер", "принтер\\ сканер", "принтер; сканер --", "принтер, сканер."]
    for query in queries:
        assert ticket.number in _found(holder, query), query
    for query in ("'", '"', "&|!()<->:*\\", "'\"", "((("):
        search.search(_fresh(holder), query, 50)                       # без исключения
    response = support.logged_in(holder).get("/tickets/", {"preset": "all", "q": 'принтер" \'& | !('})
    assert response.status_code == 200 and ticket.number in _grid_numbers(response)


def test_search_injection_string_passed_as_parameter_raw_type():
    """NFR-213: строка запроса уходит параметром `to_tsquery` (тип `raw`), а не подстановкой в SQL."""
    from apps.servicedesk.services import search

    _desk()
    holder = _holder()
    _mk(subject="Принтер", text="Не печатает")
    before = model("servicedesk.Ticket").objects.count()
    attack = "принтер'); DROP TABLE servicedesk_ticket; --"
    queryset = search.apply(model("servicedesk.Ticket").objects.all(), attack)
    sql, params = queryset.query.sql_with_params()
    lowered = sql.lower()
    assert "to_tsquery" in lowered and "plainto_tsquery" not in lowered and "websearch_to_tsquery" not in lowered
    assert "принтер" not in lowered and "drop" not in lowered
    assert any(isinstance(p, str) and "принтер:*" in p and "drop:*" in p for p in params)
    assert _found(holder, attack) == []                                  # слов «drop», «table» в заявке нет
    assert model("servicedesk.Ticket").objects.count() == before


def test_search_only_among_visible_tickets():
    """FR-278: поиск идёт только среди видимых заявок (очереди пользователя и заявки, где он ответственный)."""
    _desk()
    queue_a, queue_b, queue_c = sd.make_queue(), sd.make_queue(), sd.make_queue()
    user = support.make_employee()
    support_org.make_member(user, queue_a.unit)
    mine = _mk(subject="Сканер в бухгалтерии", text="Не включается", queue=queue_a)
    assigned = _mk(subject="Сканер в складе", text="Не включается", queue=queue_b)
    assigned.assignee = user
    assigned.save(update_fields=["assignee"])
    foreign = _mk(subject="Сканер в приёмной", text="Не включается", queue=queue_c)
    other_a = _mk(subject="Сеть в бухгалтерии", text="Не работает", queue=queue_a)
    assert set(_found(user, "сканер")) == {mine.number, assigned.number}
    assert foreign.number not in _found(user, "сканер") and other_a.number not in _found(user, "сканер")
    assert set(_found(_holder(), "сканер")) == {mine.number, assigned.number, foreign.number}
    assert _found(support.make_employee(), "сканер") == []
    response = support.logged_in(user).get("/tickets/", {"preset": "all", "q": "сканер"})
    assert _grid_numbers(response) == {mine.number, assigned.number}


# --- столбец search: сборка и дописывание ---------------------------------------------------------------

def test_search_column_built_on_create_from_number_subject_requester_first_message():
    """FR-278: при создании столбец собран из номера, темы, адреса и ФИО заявителя и текста первого сообщения."""
    _desk()
    text = "Не сканирует документы"
    ticket = _mk(subject="Сломался сканер", text=text, name="Иванов Пётр", email="Ivanov.Petr@corp.test")
    ticket.refresh_from_db()
    assert ticket.search_len == len(text)
    assert _in_column(ticket, f"{ticket.number}:*")
    assert _in_column(ticket, "сканер:*")
    assert _in_column(ticket, "документ:*")
    assert _in_column(ticket, "иванов:*") and _in_column(ticket, "петр:*")
    assert _in_column(ticket, "ivanov:*") and _in_column(ticket, "corp:*") and _in_column(ticket, "petr:*")
    assert not _in_column(ticket, "принтер:*") and not _in_column(ticket, "сидоров:*")


def test_search_appended_by_incoming_mail_reply_and_comment():
    """FR-278: письмо заявителя, ответ и внутренний комментарий дописываются в столбец; `search_len` растёт на их знаки."""
    from apps.servicedesk.services import replies

    _desk()
    holder = _holder()
    ticket = _mk(subject="Просьба", text="Нужна помощь")
    ticket.refresh_from_db()
    length = ticket.search_len
    assert _found(holder, "ноутбук") == [] and _found(holder, "проектор") == [] and _found(holder, "модем") == []

    text = "Добавляю про ноутбук"
    _incoming(ticket, text)
    ticket.refresh_from_db()
    length += len(text)
    assert _found(holder, "ноутбук") == [ticket.number] and ticket.search_len == length

    text = "Проверим модем завтра"
    replies.reply(ticket, text=text, actor=_fresh(holder))
    ticket.refresh_from_db()
    length += len(text)
    assert _found(holder, "модем") == [ticket.number] and ticket.search_len == length

    text = "Заметка про проектор"
    replies.comment(ticket, text=text, actor=_fresh(holder))
    ticket.refresh_from_db()
    length += len(text)
    assert _found(holder, "проектор") == [ticket.number] and ticket.search_len == length
    assert _found(holder, "ноутбук") == [ticket.number] and _found(holder, "помощь") == [ticket.number]


def test_search_message_over_100k_chars_tail_not_searchable_but_visible():
    """FR-278: от одного сообщения в поиск идёт не больше 100 тыс. знаков; остаток виден в карточке, но не находится."""
    from apps.servicedesk.services import search

    _desk()
    holder = _holder()
    ticket = _mk(subject="Длинное письмо", text="Начало разговора")
    ticket.refresh_from_db()
    before = ticket.search_len
    full = search.LIMIT_MESSAGE + 50
    entry = _incoming(ticket, _padded("альфаслово", "омегахвост", full))
    ticket.refresh_from_db()
    assert ticket.search_len - before == search.LIMIT_MESSAGE
    assert _found(holder, "альфаслово") == [ticket.number]
    assert _found(holder, "омегахвост") == []
    entry.refresh_from_db()
    assert len(entry.text) == full and entry.text.endswith("омегахвост")
    card = support.logged_in(holder).get(f"/tickets/{ticket.number}/")
    assert card.status_code == 200 and "омегахвост" in card.content.decode("utf-8", "replace")


def test_search_ticket_over_300k_chars_stops_appending():
    """FR-278: на заявку — не больше 300 тыс. знаков: сообщение, не помещающееся в остаток, берётся до предела; дальше — нет."""
    from apps.servicedesk.services import search

    _desk()
    holder = _holder()
    ticket = _mk(subject="Огромная переписка", text="Первое сообщение заявки с длиной в сорок знаков.")
    ticket.refresh_from_db()
    first = ticket.search_len
    step = search.LIMIT_MESSAGE
    _incoming(ticket, _padded("альфаслово", "омегаодин", step))
    _incoming(ticket, _padded("бетаслово", "омегадва", step))
    ticket.refresh_from_db()
    assert ticket.search_len == first + 2 * step
    assert _found(holder, "омегаодин") == [ticket.number] and _found(holder, "омегадва") == [ticket.number]

    third = _incoming(ticket, _padded("гаммаслово", "омегатри", step))        # остаток предела — step - first знаков
    ticket.refresh_from_db()
    assert ticket.search_len == search.LIMIT_TICKET
    assert _found(holder, "гаммаслово") == [ticket.number] and _found(holder, "омегатри") == []
    third.refresh_from_db()
    assert len(third.text) == step

    fourth = _incoming(ticket, "дельтаслово после предела")
    ticket.refresh_from_db()
    assert ticket.search_len == search.LIMIT_TICKET
    assert _found(holder, "дельтаслово") == []
    assert ticket.entries.filter(pk=fourth.pk, text="дельтаслово после предела").exists()


def test_search_dataerror_message_saved_not_in_search_len_set_to_limit(monkeypatch):
    """FR-278: `DataError` при записи вектора — сообщение записано, в поиск не попало, `search_len` = предел."""
    from apps.servicedesk.services import search

    _desk()
    holder = _holder()
    ticket = _mk(subject="Обычная заявка", text="Первое сообщение")
    calls = []

    def raising(ticket_id, parts):
        calls.append(ticket_id)
        raise DataError("string is too long for tsvector")

    monkeypatch.setattr(search, "write_vector", raising)
    entry = _incoming(ticket, "Сообщение про картридж")                   # без исключения
    assert calls and set(calls) == {ticket.pk}
    ticket.refresh_from_db()
    assert ticket.entries.filter(pk=entry.pk, text="Сообщение про картридж").exists()
    assert ticket.search_len == search.LIMIT_TICKET
    assert not _in_column(ticket, "картридж:*") and _in_column(ticket, "первое:*")
    monkeypatch.undo()
    _incoming(ticket, "Следующее сообщение про планшет")                  # предел достигнут — дописывания нет
    ticket.refresh_from_db()
    assert ticket.search_len == search.LIMIT_TICKET and _found(holder, "планшет") == []


# --- пересборка столбца ---------------------------------------------------------------------------------

def test_search_rebuilt_on_requester_name_edit_in_ticket():
    """FR-278: правка ФИО заявителя в заявке пересобирает столбец целиком: старого имени нет, тексты и `search_len` целы."""
    from apps.servicedesk.services import tickets

    _desk()
    holder = _holder()
    text = "Не работает монитор"
    ticket = _mk(subject="Монитор", text=text, name="Кузнецов Андрей")
    assert _found(holder, "кузнецов") == [ticket.number]
    changed = tickets.update_fields(ticket, actor=_fresh(holder), requester_name="Смирнов Борис")
    assert "requester_name" in changed
    ticket.refresh_from_db()
    assert _found(holder, "смирнов") == [ticket.number] and _found(holder, "борис") == [ticket.number]
    assert _found(holder, "кузнецов") == [] and _found(holder, "андрей") == []
    assert _found(holder, "монитор") == [ticket.number]
    assert ticket.search_len == len(text)


def test_search_rebuilt_on_anonymize_from_number_and_subject():
    """FR-278, FR-290: обезличивание пересобирает столбец только из номера и темы: ФИО, адрес и тексты не находятся."""
    from apps.servicedesk.services import retention

    _desk()
    holder = _holder()
    ticket = _mk(subject="Сломался сканер бухгалтерии", text="Уникальнаяфраза в письме", name="Фролов Игорь",
                 email="Frolov.Igor@corp.test")
    assert _found(holder, "фролов") == [ticket.number] and _found(holder, "уникальнаяфраза") == [ticket.number]
    ticket.kind = "closed"
    ticket.status = model("servicedesk.Status").objects.get(kind="closed", is_default=True)
    ticket.closed_at = ticket.created_at
    ticket.save(update_fields=["kind", "status", "closed_at"])
    sd.backdate(ticket, "closed_at", days=366 * 4)
    assert retention.anonymize_one(ticket.pk) is True
    ticket.refresh_from_db()
    assert ticket.anonymized_at is not None
    assert _found(holder, "сканер") == [ticket.number] and _found(holder, f"#{ticket.number}") == [ticket.number]
    for word in ("фролов", "игорь", "frolov", "уникальнаяфраза"):
        assert _found(holder, word) == [], word
    assert _in_column(ticket, f"{ticket.number}:*") and not _in_column(ticket, "corp:*")
