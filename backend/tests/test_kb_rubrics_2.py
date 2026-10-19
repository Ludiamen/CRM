"""T-5111: рубрики — перенос, удаление, подписка, страница рубрики (FR-404, FR-418, FR-419, FR-421, FR-437, FR-438).

Сценарии «Рубрики, теги, главная» спеки среза 005. Службы `rubrics` и `subscriptions` вызываются напрямую (коды отказов
по разделу 5.4 контракта), страницы — по путям раздела 10.4, разметка — по зацепкам разделов 11.1, 11.2, тексты — по
разделу 12. Гонки — без потоков (раздел 16 контракта): последовательные вызовы и advisory-замок по SQL (`advisory_locks`).
Код среза на уровне модуля не импортируется: имена берутся внутри тестов.
"""
import html as html_lib
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest

from tests import support
from tests import support_kb as kb

pytestmark = pytest.mark.django_db

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
RUBRICS_LOCK = "knowledge.rubrics"


# --- помощники только этого файла ------------------------------------------------------------------------

class _Dom(HTMLParser):
    """Плоский разбор разметки: узел — тег, атрибуты, текст внутри, предки."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes: list = []
        self._stack: list = []

    def _open(self, tag, attrs):
        node = SimpleNamespace(tag=tag, attrs={k: (v if v is not None else "") for k, v in attrs}, parts=[],
                               ancestors=list(self._stack))
        self.nodes.append(node)
        return node

    def handle_starttag(self, tag, attrs):
        node = self._open(tag, attrs)
        if tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs)

    def handle_endtag(self, tag):
        if any(n.tag == tag for n in self._stack):
            while self._stack:
                if self._stack.pop().tag == tag:
                    break

    def handle_data(self, data):
        for node in self._stack:
            node.parts.append(data)


def _dom(response) -> list:
    parser = _Dom()
    parser.feed(response.content.decode())
    parser.close()
    for node in parser.nodes:
        node.text = "".join(node.parts)
    return parser.nodes


def _find(response, tag: str | None = None, **attrs) -> list:
    """Узлы с тегом `tag` (если задан) и атрибутами; в `attrs` дефис записывается подчёркиванием: `data_error`."""
    want = {name.replace("_", "-"): value for name, value in attrs.items()}
    return [n for n in _dom(response)
            if (tag is None or n.tag == tag) and all(n.attrs.get(k) == v for k, v in want.items())]


def _text(response) -> str:
    return html_lib.unescape(response.content.decode())


def _article_ids(response) -> list[int]:
    """Номера статей в строках списка по порядку (внутри `[data-kb-list]`, а у фрагмента — все строки)."""
    nodes = _dom(response)
    scoped = any("data-kb-list" in n.attrs for n in nodes)
    return [int(n.attrs["data-article-id"]) for n in nodes
            if n.tag == "li" and "data-article-id" in n.attrs
            and (not scoped or any("data-kb-list" in a.attrs for a in n.ancestors))]


def _more_buttons(response) -> list:
    return _find(response, "button", data_action="more")


def _rubrics():
    from apps.knowledge.services import rubrics

    return rubrics


def _subs():
    from apps.knowledge.services import subscriptions

    return subscriptions


def _state() -> list[tuple]:
    """Снимок всех рубрик: номер, родитель, глубина, название, признак «по умолчанию»."""
    return sorted(support.model("knowledge.Rubric").objects.values_list("pk", "parent_id", "depth", "name",
                                                                         "is_default"))


def _events(action: str) -> list:
    return list(support.model("core.AuditEvent").objects.filter(action=action).order_by("id"))


def _refused(call, code: str, field: str):
    """Служба отказывает (`RubricError`) с кодом и полем; возвращает исключение."""
    from apps.knowledge.services import RubricError

    with pytest.raises(RubricError) as caught:
        call()
    assert caught.value.code == code, f"ждали {code}, получили {caught.value.code}: {caught.value}"
    assert caught.value.field == field, f"поле отказа {code}: ждали {field!r}, получили {caught.value.field!r}"
    return caught.value


def _post_move(session, rubric, parent):
    return session.client.post(f"/kb/rubrics/{rubric.pk}/move/", {"parent": parent.pk if parent else ""})


def _assert_field_refusal(response, field: str, code: str, text: str | None = None):
    """Отказ у поля: 200 и `[data-error=field][data-code=code]`; `text` (подстрока) — внутри этого элемента
    (раздел 17, п. 38: элемент содержит текст сообщения)."""
    assert response.status_code == 200
    found = _find(response, data_error=field, data_code=code)
    assert found, f"нет [data-error={field}][data-code={code}]"
    if text is not None:
        assert any(text in html_lib.unescape(node.text) for node in found), \
            f"текст «{text}» не внутри [data-error={field}]"


def _assert_no_cycle():
    parents = dict(support.model("knowledge.Rubric").objects.values_list("pk", "parent_id"))
    for start in parents:
        seen, node = set(), start
        while node is not None:
            assert node not in seen, f"цикл в дереве рубрик через {node}"
            seen.add(node)
            node = parents[node]


def _published_of(rubric, count: int, clock, author):
    """`count` опубликованных статей рубрики; каждая следующая правилась позже предыдущей (часы фикстуры)."""
    made = []
    for _ in range(count):
        clock.advance(seconds=1)
        made.append(kb.make_published(rubric=rubric, author=author, vectors=False))
    return made


# --- перенос (FR-418) ----------------------------------------------------------------------------------------

def test_move_into_self_refused(clock):
    """FR-418: перенос рубрики в саму себя — отказ `parent_self` у поля `parent`; дерево и журнал не меняются."""
    manager = kb.as_manager()
    tree = kb.rubric_tree({"Сети": {"VPN": {}}})
    before = _state()

    _refused(lambda: _rubrics().move(manager.user, tree["Сети"].pk, tree["Сети"].pk), "parent_self", "parent")
    response = _post_move(manager, tree["VPN"], tree["VPN"])

    _assert_field_refusal(response, "parent", "parent_self",
                          "Нельзя перенести рубрику в саму себя")
    assert _state() == before
    assert _events("knowledge.rubric_moved") == []


def test_move_next_to_sibling_with_same_name_case_insensitive_refused(clock):
    """FR-418 (решение 34 задач): сосед с тем же названием без учёта регистра — `name_duplicate` у поля `name`,
    и под родителем, и в корне; рубрика остаётся на месте; без совпадения перенос проходит."""
    manager = kb.as_manager()
    tree = kb.rubric_tree({"Сети": {"VPN": {}}, "Почта": {"vpn": {}}, "Vpn": {}, "Файлы": {}})
    mover = tree["vpn"]
    before = _state()

    _refused(lambda: _rubrics().move(manager.user, mover.pk, tree["Сети"].pk), "name_duplicate", "name")
    _refused(lambda: _rubrics().move(manager.user, mover.pk, None), "name_duplicate", "name")
    response = _post_move(manager, mover, tree["Сети"])

    _assert_field_refusal(response, "name", "name_duplicate",
                          "Рубрика с таким названием уже есть на этом уровне")
    assert _state() == before
    assert _events("knowledge.rubric_moved") == []

    moved = _rubrics().move(manager.user, mover.pk, tree["Файлы"].pk)
    assert moved.parent_id == tree["Файлы"].pk and moved.depth == 2


def test_move_into_descendant_refused_with_explanation(clock):
    """FR-418: перенос под потомка (подрубрику и подподрубрику) — `parent_descendant` у поля `parent` с объяснением."""
    manager = kb.as_manager()
    tree = kb.rubric_tree({"Сети": {"VPN": {"Клиенты": {}}}})
    before = _state()

    _refused(lambda: _rubrics().move(manager.user, tree["Сети"].pk, tree["VPN"].pk), "parent_descendant", "parent")
    _refused(lambda: _rubrics().move(manager.user, tree["Сети"].pk, tree["Клиенты"].pk), "parent_descendant", "parent")
    response = _post_move(manager, tree["Сети"], tree["Клиенты"])

    _assert_field_refusal(response, "parent", "parent_descendant",
                          "Нельзя перенести рубрику в её подрубрику")
    assert _state() == before
    assert _events("knowledge.rubric_moved") == []


def test_move_exceeding_depth_refused_with_explanation(clock):
    """FR-418: глубина нового места плюс высота поддерева больше трёх — `depth_exceeded` у поля `parent`
    с текстом «Не глубже трёх уровней»; ровно три уровня допустимы."""
    manager = kb.as_manager()
    tree = kb.rubric_tree({"Сети": {"VPN": {}}, "Почта": {"Ящики": {}}, "Файлы": {}})
    before = _state()

    _refused(lambda: _rubrics().move(manager.user, tree["Сети"].pk, tree["Ящики"].pk), "depth_exceeded", "parent")
    response = _post_move(manager, tree["Сети"], tree["Ящики"])

    _assert_field_refusal(response, "parent", "depth_exceeded",
                          "Не глубже трёх уровней")
    assert _state() == before
    assert _events("knowledge.rubric_moved") == []

    edge = _rubrics().move(manager.user, tree["Файлы"].pk, tree["Ящики"].pk)      # глубина места 3, высота 1
    assert edge.depth == 3
    deep = _rubrics().move(manager.user, tree["Сети"].pk, tree["Почта"].pk)       # Сети 2, VPN 3
    assert deep.depth == 2
    tree["VPN"].refresh_from_db()
    assert tree["VPN"].depth == 3


def test_move_recomputes_depth_of_subtree(clock):
    """FR-418, FR-438: после переноса `depth` всего поддерева пересчитан; журнал `knowledge.rubric_moved` —
    `before`/`after` с `name` и `path` (раздел 8.1)."""
    manager = kb.as_manager()
    tree = kb.rubric_tree({"Корень": {"Сети": {"VPN": {}}}, "Зона": {}})
    Rubric = support.model("knowledge.Rubric")

    moved = _rubrics().move(manager.user, tree["Сети"].pk, None)

    assert moved.parent_id is None and moved.depth == 1
    assert Rubric.objects.get(pk=tree["VPN"].pk).depth == 2
    events = _events("knowledge.rubric_moved")
    assert len(events) == 1
    event = events[0]
    assert event.actor_id == manager.user.pk
    assert (event.object_type, event.object_id) == ("knowledge.rubric", str(tree["Сети"].pk))
    assert event.before == {"name": "Сети", "path": "Корень / Сети"}
    assert event.after == {"name": "Сети", "path": "Сети"}

    _rubrics().move(manager.user, tree["Сети"].pk, tree["Зона"].pk)
    assert Rubric.objects.get(pk=tree["Сети"].pk).depth == 2
    assert Rubric.objects.get(pk=tree["VPN"].pk).depth == 3
    assert Rubric.objects.get(pk=tree["Корень"].pk).depth == 1
    last = _events("knowledge.rubric_moved")[-1]
    assert last.before == {"name": "Сети", "path": "Сети"}
    assert last.after == {"name": "Сети", "path": "Зона / Сети"}


def test_concurrent_opposite_moves_do_not_make_cycle(clock):
    """FR-418 (план: «два встречных переноса не дают цикла»): без потоков (раздел 16) — запись дерева идёт под
    замком `pg_advisory_xact_lock(hashtextextended('knowledge.rubrics', 0))`, а второй из встречных переносов,
    дошедший после первого, видит новое дерево и получает отказ `parent_descendant`."""
    manager = kb.as_manager()
    tree = kb.rubric_tree({"Икс": {}, "Игрек": {}})

    first_sql = kb.sql_of(_rubrics().move, manager.user, tree["Икс"].pk, tree["Игрек"].pk)
    assert kb.AdvisoryLock("exclusive", RUBRICS_LOCK) in kb.advisory_locks(first_sql)

    def opposite():
        _rubrics().move(manager.user, tree["Игрек"].pk, tree["Икс"].pk)

    second_sql = kb.sql_of(_swallow, opposite)
    assert kb.AdvisoryLock("exclusive", RUBRICS_LOCK) in kb.advisory_locks(second_sql)
    _refused(opposite, "parent_descendant", "parent")
    _assert_no_cycle()
    Rubric = support.model("knowledge.Rubric")
    assert Rubric.objects.get(pk=tree["Икс"].pk).parent_id == tree["Игрек"].pk
    assert Rubric.objects.get(pk=tree["Игрек"].pk).parent_id is None
    assert len(_events("knowledge.rubric_moved")) == 1


def _swallow(call):
    """Вызов, отказ которого не интересует: нужен только SQL."""
    from apps.knowledge.services import RubricError

    try:
        call()
    except RubricError:
        pass


def test_move_and_rename_keep_articles_and_article_urls(clock):
    """FR-418, FR-404: после переноса и переименования рубрики статьи остались в ней, адрес статьи тот же,
    страница статьи показывает новый путь рубрики."""
    manager = kb.as_manager()
    reader = kb.as_reader()
    tree = kb.rubric_tree({"Сети": {}, "Офис": {}})
    article = kb.make_published(rubric=tree["Сети"], title="Как настроить VPN")
    Article = support.model("knowledge.Article")

    moved = manager.client.post(f"/kb/rubrics/{tree['Сети'].pk}/move/", {"parent": tree["Офис"].pk})
    renamed = manager.client.post(f"/kb/rubrics/{tree['Сети'].pk}/rename/", {"name": "Связь"})

    assert moved.status_code == 302 and renamed.status_code == 302
    fresh = Article.objects.get(pk=article.pk)
    assert fresh.rubric_id == tree["Сети"].pk
    assert fresh.state == "published" and fresh.title == "Как настроить VPN"
    page = reader.client.get(f"/kb/{article.pk}/")
    assert page.status_code == 200
    assert _find(page, "article", data_article_id=str(article.pk), data_article_state="published")
    shown = _find(page, data_field="rubric")
    assert shown, "нет [data-field=rubric] на странице статьи"
    assert "Офис" in shown[0].text and "Связь" in shown[0].text
    assert "Сети" not in shown[0].text


# --- удаление (FR-419) ---------------------------------------------------------------------------------------

def test_delete_with_subrubrics_refused_move_first(clock):
    """FR-419: рубрика с подрубриками не удаляется (`not_empty`, «Сначала перенесите»); после переноса подрубрики
    удаление проходит и пишет `knowledge.rubric_deleted`."""
    manager = kb.as_manager()
    tree = kb.rubric_tree({"Сети": {"VPN": {}}, "Почта": {}})
    before = _state()

    _refused(lambda: _rubrics().delete(manager.user, tree["Сети"].pk), "not_empty", "")
    response = manager.client.post(f"/kb/rubrics/{tree['Сети'].pk}/delete/")

    assert response.status_code == 200
    assert _find(response, role="alert", data_code="not_empty")
    assert "Сначала перенесите" in _text(response)
    assert _state() == before
    assert _events("knowledge.rubric_deleted") == []

    _rubrics().move(manager.user, tree["VPN"].pk, tree["Почта"].pk)
    done = manager.client.post(f"/kb/rubrics/{tree['Сети'].pk}/delete/")
    assert done.status_code == 302 and done["Location"] == "/kb/rubrics/"
    assert not support.model("knowledge.Rubric").objects.filter(pk=tree["Сети"].pk).exists()
    events = _events("knowledge.rubric_deleted")
    assert len(events) == 1
    assert (events[0].object_type, events[0].object_id) == ("knowledge.rubric", str(tree["Сети"].pk))
    assert events[0].actor_id == manager.user.pk
    assert events[0].before == {"name": "Сети", "path": "Сети"} and events[0].after == {}


def test_delete_with_published_draft_articles_refused(clock):
    """FR-419: рубрика с опубликованной статьёй или с черновиком не удаляется (`not_empty`)."""
    manager = kb.as_manager()
    with_published = kb.make_rubric("С опубликованной")
    with_draft = kb.make_rubric("С черновиком")
    kb.make_published(rubric=with_published)
    kb.make_draft(rubric=with_draft)
    before = _state()

    for rubric in (with_published, with_draft):
        _refused(lambda rubric=rubric: _rubrics().delete(manager.user, rubric.pk), "not_empty", "")
    response = manager.client.post(f"/kb/rubrics/{with_draft.pk}/delete/")

    assert response.status_code == 200 and _find(response, role="alert", data_code="not_empty")
    assert _state() == before
    assert _events("knowledge.rubric_deleted") == []


def test_delete_with_trashed_article_refused(clock):
    """FR-419: статья в корзине тоже держит рубрику — `not_empty`; рубрика цела."""
    manager = kb.as_manager()
    rubric = kb.make_rubric("С корзиной")
    kb.make_trashed(rubric=rubric)
    kb.make_trashed(rubric=rubric, was="draft")
    before = _state()

    _refused(lambda: _rubrics().delete(manager.user, rubric.pk), "not_empty", "")

    assert _state() == before
    assert _events("knowledge.rubric_deleted") == []


def test_default_rubric_general_not_deletable(clock):
    """FR-419: рубрику «Общее» удалить нельзя — `default_undeletable` с текстом раздела 12; рубрика на месте."""
    manager = kb.as_manager()
    general = kb.general_rubric()
    before = _state()

    _refused(lambda: _rubrics().delete(manager.user, general.pk), "default_undeletable", "")
    response = manager.client.post(f"/kb/rubrics/{general.pk}/delete/")

    assert response.status_code == 200
    assert _find(response, role="alert", data_code="default_undeletable")
    assert "Рубрику «Общее» нельзя удалить" in _text(response)
    assert _state() == before
    assert _events("knowledge.rubric_deleted") == []


def test_default_rubric_general_not_movable_under_other(clock):
    """FR-419: «Общее» не переносится под другую рубрику — `default_immovable` у поля `parent`; остаётся корнем."""
    manager = kb.as_manager()
    general = kb.general_rubric()
    other = kb.make_rubric("Другая")
    before = _state()

    _refused(lambda: _rubrics().move(manager.user, general.pk, other.pk), "default_immovable", "parent")
    response = _post_move(manager, general, other)

    _assert_field_refusal(response, "parent", "default_immovable",
                          "Рубрику «Общее» нельзя перенести")
    assert _state() == before
    assert _events("knowledge.rubric_moved") == []
    general.refresh_from_db()
    assert general.parent_id is None and general.is_default


def test_default_rubric_general_can_be_renamed(clock):
    """FR-419: «Общее» можно переименовать; признак «по умолчанию» остаётся; журнал `knowledge.rubric_renamed`."""
    manager = kb.as_manager()
    general = kb.general_rubric()

    response = manager.client.post(f"/kb/rubrics/{general.pk}/rename/", {"name": "Прочее"})

    assert response.status_code == 302
    general.refresh_from_db()
    assert general.name == "Прочее" and general.is_default and general.parent_id is None
    events = _events("knowledge.rubric_renamed")
    assert len(events) == 1
    assert events[0].object_id == str(general.pk)
    assert events[0].before == {"name": "Общее", "path": "Общее"}
    assert events[0].after == {"name": "Прочее", "path": "Прочее"}


# --- подписка (FR-437, FR-421) ---------------------------------------------------------------------------------

def _subscribed_flag(response) -> tuple:
    buttons = _find(response, "button", data_action="kb-subscribe")
    assert len(buttons) == 1, f"кнопок kb-subscribe: {len(buttons)}"
    return buttons[0].attrs.get("data-subscribed"), buttons[0].text.strip()


def test_subscribe_button_toggles_subscribe_unsubscribe(clock):
    """FR-437, FR-421: кнопка «Подписаться» создаёт подписку и становится «Отписаться»; повторное нажатие снимает её
    (обычный POST — 302 на страницу рубрики, НХ — фрагмент кнопки с новым `data-subscribed`). Право не нужно."""
    reader = kb.as_reader()
    rubric = kb.make_rubric("Сети")
    Subscription = support.model("knowledge.RubricSubscription")
    page_path, action = f"/kb/rubrics/{rubric.pk}/", f"/kb/rubrics/{rubric.pk}/subscribe/"

    assert _subscribed_flag(reader.client.get(page_path)) == ("false", "Подписаться")

    first = reader.client.post(action)
    assert first.status_code == 302 and first["Location"] == page_path
    assert Subscription.objects.filter(user=reader.user, rubric=rubric).count() == 1
    assert _subscribed_flag(reader.client.get(page_path)) == ("true", "Отписаться")

    second = reader.client.post(action, headers={"HX-Request": "true"})
    assert second.status_code == 200
    assert "<html" not in second.content.decode()
    assert _subscribed_flag(second) == ("false", "Подписаться")
    assert not Subscription.objects.filter(user=reader.user, rubric=rubric).exists()

    third = reader.client.post(action, headers={"HX-Request": "true"})
    assert _subscribed_flag(third) == ("true", "Отписаться")
    assert Subscription.objects.filter(user=reader.user, rubric=rubric).count() == 1


def test_subscription_covers_subrubrics(clock):
    """FR-437: подписка на рубрику действует на её подрубрики — получатели вида «Статья в рубрике по подписке» для
    статьи подрубрики включают подписчика родителя; подписчик другой ветки и подписчик подрубрики при статье в
    родителе — нет (раздел 7.2 контракта)."""
    from apps.knowledge.notify_kinds import notification_kinds

    tree = kb.rubric_tree({"Сети": {"VPN": {}}, "Почта": {}})
    parent_fan, sibling_fan, child_fan, publisher = (support.make_employee() for _ in range(4))
    kb.subscribe(parent_fan, tree["Сети"])
    kb.subscribe(sibling_fan, tree["Почта"])
    kb.subscribe(child_fan, tree["VPN"])
    kind = next(k for k in notification_kinds() if k.code == "knowledge.rubric_subscription")

    def recipients(article):
        data = {"article_id": article.pk, "actor_id": publisher.pk, "rubric_id": article.rubric_id}
        return {draft.user_id for draft in kind.build("knowledge.article_published", data)}

    in_child = kb.make_published(rubric=tree["VPN"])
    assert recipients(in_child) == {parent_fan.pk, child_fan.pk}
    in_parent = kb.make_published(rubric=tree["Сети"])
    assert recipients(in_parent) == {parent_fan.pk}


def test_subscription_visible_and_changeable_only_by_owner(clock):
    """FR-437: подписку видит и меняет только сам сотрудник — чужая подписка не видна на странице, нажатие кнопки
    меняет только свою; поле `user` в запросе игнорируется."""
    owner, stranger = kb.as_reader(), kb.as_reader()
    rubric = kb.make_rubric("Сети")
    Subscription = support.model("knowledge.RubricSubscription")
    page_path, action = f"/kb/rubrics/{rubric.pk}/", f"/kb/rubrics/{rubric.pk}/subscribe/"
    owner.client.post(action)

    assert _subscribed_flag(stranger.client.get(page_path)) == ("false", "Подписаться")
    assert _subscribed_flag(owner.client.get(page_path)) == ("true", "Отписаться")

    stranger.client.post(action, {"user": owner.user.pk})
    assert set(Subscription.objects.filter(rubric=rubric).values_list("user_id", flat=True)) == {
        owner.user.pk, stranger.user.pk}

    stranger.client.post(action, {"user": owner.user.pk})
    assert set(Subscription.objects.filter(rubric=rubric).values_list("user_id", flat=True)) == {owner.user.pk}
    assert _subscribed_flag(owner.client.get(page_path)) == ("true", "Отписаться")
    assert _subscribed_flag(stranger.client.get(page_path)) == ("false", "Подписаться")


def test_subscriptions_deleted_with_rubric_cascade(clock):
    """FR-437, FR-419: подписки удаляются вместе с рубрикой (каскад); подписки на другую рубрику остаются."""
    manager = kb.as_manager()
    fans = [support.make_employee() for _ in range(2)]
    doomed, kept = kb.make_rubric("Удаляемая"), kb.make_rubric("Остаётся")
    Subscription = support.model("knowledge.RubricSubscription")
    for fan in fans:
        assert _subs().toggle(fan, doomed.pk) is True
    assert _subs().toggle(fans[0], kept.pk) is True
    assert Subscription.objects.filter(rubric=doomed).count() == 2

    _rubrics().delete(manager.user, doomed.pk)

    assert not support.model("knowledge.Rubric").objects.filter(pk=doomed.pk).exists()
    assert not Subscription.objects.filter(rubric_id=doomed.pk).exists()
    assert list(Subscription.objects.values_list("user_id", "rubric_id")) == [(fans[0].pk, kept.pk)]


# --- страница рубрики (FR-421) -----------------------------------------------------------------------------------

def test_rubric_page_lists_published_of_rubric_and_subrubrics(clock):
    """FR-421: страница рубрики — опубликованные статьи самой рубрики и подрубрик (всех уровней) по времени правки
    вниз; статьи чужой ветки не показываются."""
    reader = kb.as_reader()
    author = kb.as_editor().user
    tree = kb.rubric_tree({"Сети": {"VPN": {"Клиенты": {}}}, "Почта": {}})
    in_vpn = kb.make_published(rubric=tree["VPN"], author=author)
    clock.advance(minutes=1)
    in_root = kb.make_published(rubric=tree["Сети"], author=author)
    clock.advance(minutes=1)
    in_clients = kb.make_published(rubric=tree["Клиенты"], author=author)
    clock.advance(minutes=1)
    foreign = kb.make_published(rubric=tree["Почта"], author=author)

    page = reader.client.get(f"/kb/rubrics/{tree['Сети'].pk}/")

    assert page.status_code == 200
    assert _find(page, data_kb_page="rubric")
    assert _article_ids(page) == [in_clients.pk, in_root.pk, in_vpn.pk]
    assert foreign.pk not in _article_ids(page)
    child_page = reader.client.get(f"/kb/rubrics/{tree['VPN'].pk}/")
    assert _article_ids(child_page) == [in_clients.pk, in_vpn.pk]


def test_rubric_page_excludes_drafts_and_trash(clock):
    """FR-421: черновики и статьи в корзине (бывшие опубликованными и бывшие черновиками) на странице рубрики и
    подрубрики не показываются."""
    reader = kb.as_reader()
    author = kb.as_editor().user
    tree = kb.rubric_tree({"Сети": {"VPN": {}}})
    shown = kb.make_published(rubric=tree["Сети"], author=author)
    clock.advance(minutes=1)
    hidden = [kb.make_draft(rubric=tree["Сети"], author=author),
              kb.make_trashed(rubric=tree["Сети"], author=author),
              kb.make_trashed(rubric=tree["VPN"], was="draft", author=author),
              kb.make_draft(rubric=tree["VPN"], author=author)]
    clock.advance(minutes=1)
    shown_in_child = kb.make_published(rubric=tree["VPN"], author=author)

    page = reader.client.get(f"/kb/rubrics/{tree['Сети'].pk}/")

    assert page.status_code == 200
    ids = _article_ids(page)
    assert ids == [shown_in_child.pk, shown.pk]
    assert not {a.pk for a in hidden} & set(ids)


def test_rubric_page_paginates_20_with_offset(clock):
    """FR-421: по 20 статей, «Показать ещё» (`data-action="more"`, `data-next-offset`) отдаёт следующие 20 фрагментом
    и пропадает на последней порции; ошибочный `offset` читается как 0."""
    reader = kb.as_reader()
    author = kb.as_editor().user
    rubric = kb.make_rubric("Много статей")
    made = _published_of(rubric, 45, clock, author)
    newest_first = [a.pk for a in reversed(made)]
    path = f"/kb/rubrics/{rubric.pk}/"

    first = reader.client.get(path)
    assert first.status_code == 200
    assert _article_ids(first) == newest_first[:20]
    buttons = _more_buttons(first)
    assert [b.attrs.get("data-next-offset") for b in buttons] == ["20"]

    second = reader.client.get(path, {"offset": 20}, headers={"HX-Request": "true"})
    assert second.status_code == 200 and "<html" not in second.content.decode()
    assert _article_ids(second) == newest_first[20:40]
    assert [b.attrs.get("data-next-offset") for b in _more_buttons(second)] == ["40"]

    third = reader.client.get(path, {"offset": 40}, headers={"HX-Request": "true"})
    assert third.status_code == 200
    assert _article_ids(third) == newest_first[40:]
    assert _more_buttons(third) == []

    for bad in ("-5", "abc", ""):
        again = reader.client.get(path, {"offset": bad})
        assert again.status_code == 200
        assert _article_ids(again) == newest_first[:20], f"offset={bad!r} должен читаться как 0"


# --- журнал: подписка не пишется (FR-438) -------------------------------------------------------------------------

def test_subscribe_and_unsubscribe_write_no_journal_record(clock):
    """FR-437, FR-438: подписка и отписка (страницей и службой) не пишут в журнал; сами действия состоялись."""
    reader = kb.as_reader()
    rubric = kb.make_rubric("Сети")
    AuditEvent = support.model("core.AuditEvent")
    Subscription = support.model("knowledge.RubricSubscription")
    action = f"/kb/rubrics/{rubric.pk}/subscribe/"
    count = AuditEvent.objects.count()

    reader.client.post(action)
    assert Subscription.objects.filter(user=reader.user, rubric=rubric).exists()
    reader.client.post(action, headers={"HX-Request": "true"})
    assert not Subscription.objects.filter(user=reader.user, rubric=rubric).exists()
    assert _subs().toggle(reader.user, rubric.pk) is True
    assert _subs().toggle(reader.user, rubric.pk) is False

    assert AuditEvent.objects.count() == count
    assert not AuditEvent.objects.filter(action__startswith="knowledge.").exists()
