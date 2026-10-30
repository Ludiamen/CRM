"""T-7134: сброс стенда `feed` и команды стенда `e2e_feed_shift`, `e2e_feed_retention` (FR-613, FR-618, FR-638,
FR-640). Сценарии «Права и данные установки», «Событие и напоминания», «Срок хранения» (команды стенда) спеки 007.

Контракт: CONTRACT-007 — 1.3 (сброс стенда), 2.3 (миграция данных), 14.1 и 14.2 (команды стенда; решения 10 и 54
задач). Сброс проверяется прямым вызовом `apps.feed.stand.stand_reset()` (команда `e2e_reset_stand` здесь не
запускается: она чистит все таблицы ядра); данные сброса создаются и читаются через соединение `migrate`, как в
`test_lists_stand.py` (у соединений разные транзакции; фабрики `support_feed` пишут через `default`, поэтому здесь
свои помощники — временная замена внутри файла). Том `protected` во всех тестах сброса — временный каталог
(фикстура `protected_root`): сброс стирает каталог эскизов. Подмены служб — через атрибуты модулей: функция `seed`
миграции подменяется на модуле, а не на копии. Команды работают на соединении `default`; время ставит фикстура `clock`.
"""
import contextlib
import importlib
import re
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.db.models.signals import m2m_changed, post_save
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests import factories, support
from tests import support_feed as fd

MIGRATE = pytest.mark.django_db(databases=["default", "migrate"])
PLAIN = pytest.mark.django_db

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."
SHIFT_LINE = re.compile(r"feed_shift: shifted=(\d+) reminded=(\d+) important=(\d+)\n")
RETENTION_LINE = re.compile(r"feed_retention: aged=(\d+) deleted=(\d+)\n")
FEED_MODELS = ("FeedFile", "CommentLike", "FeedComment", "PostLike", "ReadMark", "EventAnswer", "Shown", "Recipient",
               "Post")


# --- помощники сброса (свои: фабрики support_feed пишут через `default`) ------------------------------------------

def _on(model_name: str):
    return support.model(model_name).objects.using("migrate")


def _person(name: str):
    """Сотрудник, созданный через `migrate` (на `default` строка не видна: у соединений разные транзакции)."""
    User = support.model("core.User")
    user = User(email=factories.new_email(), full_name=name, state="active")
    user.set_password(factories.new_password())
    user.save(using="migrate")
    return user


def _stored(purpose: str, status: str, data: bytes, *, write: bool = True):
    """`StoredFile` через `migrate` и путь его файла на диске (`incoming/`, `attachments/`, `quarantine/`)."""
    from apps.core.services import files as core_files

    stored = _on("core.StoredFile").create(
        purpose=purpose, owner=None, size=len(data), sha256="0" * 64, content_type="application/octet-stream",
        status=status, scanned_at=timezone.now() if status != "pending" else None)
    path = core_files.attachment_path(stored)
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return stored, path


def _feed_file(stored, name: str, uploaded_by, *, post=None, comment=None, thumb: str = ""):
    return _on("feed.FeedFile").create(post=post, comment=comment, file=stored, name=name, thumb=thumb,
                                       uploaded_by=uploaded_by, uploaded_at=timezone.now())


@contextlib.contextmanager
def _commit_callbacks(capture):
    """После фиксации: исполняет `on_commit` обоих соединений; алиас стирания файлов (`migrate`, К-9) проверяет тест
    стирания файлов."""
    with capture(using="default", execute=True) as on_default, capture(using="migrate", execute=True) as on_migrate:
        yield on_default, on_migrate


def _counts(*names: str) -> dict[str, int]:
    return {name: _on(f"feed.{name}").count() for name in names}


def _everything_on_migrate(author, reader) -> dict:
    """По одной строке во всех таблицах `feed` через `migrate`: запись, событие, важная запись, адресаты, показы,
    прочтение, ответ, «Нравится» записи и комментария, комментарий ядра и его строка ленты, непривязанный файл,
    строка настройки со сроком 7 лет."""
    now = timezone.now()
    post = _on("feed.Post").create(author=author, kind="post", text="Запись стенда", to_all=False, published_at=now)
    event = _on("feed.Post").create(
        author=author, kind="event", text="", to_all=True, published_at=now, event_title="Событие стенда",
        event_place="Зал", event_start=now + timedelta(days=3), event_end=now + timedelta(days=3, hours=1),
        remind_at=now + timedelta(days=3, minutes=-60))
    important = _on("feed.Post").create(author=author, kind="important", text="Важное стенда", to_all=True,
                                        published_at=now, important_until=now + timedelta(days=2))
    _on("feed.Recipient").create(post=post, kind="user", user=reader, via="to", published_at=now)
    _on("feed.Recipient").create(post=post, kind="unit", unit_id=999, via="to", published_at=now)
    _on("feed.Shown").create(user=reader, post=post, shown_at=now)
    _on("feed.ReadMark").create(post=important, user=reader, read_at=now)
    _on("feed.EventAnswer").create(post=event, user=reader, answer="go", answered_at=now)
    _on("feed.PostLike").create(post=post, user=reader, created_at=now)
    core_comment = _on("core.Comment").create(object_ref=f"feed.post:{post.pk}", author=reader, text="Комментарий стенда",
                                              created_at=now)
    feed_comment = _on("feed.FeedComment").create(comment=core_comment, post=post)
    _on("feed.CommentLike").create(comment=core_comment, post=post, user=author, created_at=now)
    stored, _ = _stored("feed", "clean", b"unbound", write=False)
    unbound = _feed_file(stored, "без записи.txt", author)
    _on("feed.FeedSettings").all().delete()
    settings_row = _on("feed.FeedSettings").create(pk=1, retention_years=7, updated_by=author, updated_at=now)
    return {"post": post, "event": event, "important": important, "comment": core_comment,
            "feed_comment": feed_comment, "unbound": unbound, "settings": settings_row}


def _core_handler_connected() -> bool:
    """Подключён ли обработчик `m2m_changed` прав ядра (`dispatch_uid="core-perms-role-permissions"`)."""
    from apps.core.services import permissions

    receivers = m2m_changed._live_receivers(support.model("core.Role").permissions.through)
    sync = receivers[0] if isinstance(receivers, tuple) else receivers
    return permissions._role_permissions_changed in sync


def _seed_module():
    return importlib.import_module("apps.feed.migrations.0002_initial_data")


# --- сброс стенда (прямой вызов функции точки, контракт 1.3) ------------------------------------------------------

@MIGRATE
def test_feed_stand_reset_runs_in_transaction_under_migrate_alias(protected_root, django_capture_on_commit_callbacks):
    """FR-640: весь сброс (стирание и `seed`) идёт под алиасом `migrate` внутри одной `transaction.atomic`: в SQL
    соединения `migrate` стоит `SAVEPOINT` (вложенная в тестовую транзакцию `atomic`) раньше первого `DELETE` и
    `RELEASE SAVEPOINT` позже последнего `DELETE` и `INSERT`, откатов нет; на соединении `default` нет ни одного
    запроса к таблицам `feed_*` (раздел 1.3)."""
    from apps.feed.stand import stand_reset

    _everything_on_migrate(_person("Автор Стенда"), _person("Читатель Стенда"))
    with CaptureQueriesContext(connections["migrate"]) as migrate_log, \
            CaptureQueriesContext(connections["default"]) as default_log:
        with _commit_callbacks(django_capture_on_commit_callbacks):
            stand_reset()
    sqls = [q["sql"] for q in migrate_log.captured_queries]
    deletes = [i for i, sql in enumerate(sqls) if sql.startswith('DELETE FROM "feed_')]
    inserts = [i for i, sql in enumerate(sqls) if sql.startswith('INSERT INTO "feed_feedsettings"')]
    assert deletes, "сброс ничего не стёр на соединении migrate"
    assert inserts, "seed не создал настройку на соединении migrate"
    opened = [i for i, sql in enumerate(sqls) if sql.startswith("SAVEPOINT")]
    released = [i for i, sql in enumerate(sqls) if sql.startswith("RELEASE SAVEPOINT")]
    assert opened and released, "стирание и seed не завёрнуты в transaction.atomic(using=migrate)"
    assert opened[0] < deletes[0], "первое стирание раньше входа в транзакцию"
    writes = [i for i, sql in enumerate(sqls) if sql.startswith(("DELETE FROM", "INSERT INTO"))]
    assert released[-1] > max(writes), "стирание или seed выполнены после выхода из транзакции"
    assert not [sql for sql in sqls if sql.startswith("ROLLBACK")], "сброс откатывался"
    on_default = [q["sql"] for q in default_log.captured_queries if "feed_" in q["sql"]]
    assert not on_default, f"запросы к таблицам feed на соединении default: {on_default[:2]}"


@MIGRATE
def test_feed_stand_reset_wipes_all_feed_tables(protected_root, django_capture_on_commit_callbacks):
    """FR-640: стираются все таблицы `feed`: записи (все виды), адресаты, показы, прочтения, ответы, «Нравится» записей
    и комментариев, комментарии ленты, файлы; строка настройки возвращается заново; сотрудники и роли не стираются
    (раздел 1.3)."""
    from apps.feed.stand import stand_reset

    author, reader = _person("Автор Стенда"), _person("Читатель Стенда")
    data = _everything_on_migrate(author, reader)
    assert all(count > 0 for count in _counts(*FEED_MODELS).values()), _counts(*FEED_MODELS)

    with _commit_callbacks(django_capture_on_commit_callbacks):
        stand_reset()

    assert _counts(*FEED_MODELS) == {name: 0 for name in FEED_MODELS}, "после сброса остались строки feed"
    for label in ("post", "event", "important"):
        assert not _on("feed.Post").filter(pk=data[label].pk).exists(), label
    assert _counts("FeedSettings") == {"FeedSettings": 1}
    assert _on("core.User").filter(pk__in=[author.pk, reader.pk]).count() == 2, "сотрудник стёрт"
    assert _on("core.Role").filter(is_builtin=True).count() >= 3, "роли стёрты (их стирает команда e2e_reset_stand)"


@MIGRATE
def test_feed_stand_reset_deletes_core_comments_with_feed_post_object_ref(
        protected_root, django_capture_on_commit_callbacks):
    """FR-640: сброс удаляет строки `core.Comment` с `object_ref` `feed.post:…` — и с записью ленты, и «осиротевшие» (без
    строки `FeedComment` и записи: общий сброс ядра мог стереть их раньше); комментарии статей и других модулей
    остаются (решение 53 задач)."""
    from apps.feed.stand import stand_reset

    author, reader = _person("Автор Стенда"), _person("Читатель Стенда")
    data = _everything_on_migrate(author, reader)
    now = timezone.now()
    orphan = _on("core.Comment").create(object_ref="feed.post:999999", author=reader, text="Сирота", created_at=now)
    foreign = [_on("core.Comment").create(object_ref=ref, author=reader, text="Чужой", created_at=now)
               for ref in ("knowledge.article:5", "lists.record:3")]

    with _commit_callbacks(django_capture_on_commit_callbacks):
        stand_reset()

    assert not _on("core.Comment").filter(object_ref__startswith="feed.post:").exists()
    assert not _on("core.Comment").filter(pk__in=[data["comment"].pk, orphan.pk]).exists()
    assert sorted(_on("core.Comment").filter(pk__in=[c.pk for c in foreign]).values_list("object_ref", flat=True)) \
        == ["knowledge.article:5", "lists.record:3"], "стёрты комментарии не ленты"


@MIGRATE
def test_feed_stand_reset_wipes_feed_file_rows_stored_files_and_disk_after_commit(
        protected_root, django_capture_on_commit_callbacks):
    """FR-640: файлы ленты во всех состояниях (`pending` — `incoming/`, `clean` — `attachments/`, `quarantine` —
    `quarantine/`, без файла на диске) и эскиз стираются: строки `FeedFile` и их `StoredFile` — сразу, файлы и эскиз на
    диске — только после фиксации (`on_commit` соединения `migrate`): пока обратные вызовы не исполнены, оригиналы на
    месте; файлы других назначений (`attachment`, `knowledge`) не тронуты (раздел 1.3)."""
    from apps.feed.stand import stand_reset

    author = _person("Автор Стенда")
    post = _on("feed.Post").create(author=author, kind="post", text="Запись с файлами", to_all=True,
                                   published_at=timezone.now())
    made = []
    for status, name, write in (("pending", "a.txt", True), ("clean", "b.png", True), ("quarantine", "c.txt", True),
                                ("clean", "d.txt", False)):
        stored, path = _stored("feed", status, name.encode(), write=write)
        thumb = ""
        thumb_path = None
        if name == "b.png":
            thumb = f"attachments/thumbs/{stored.pk}.jpg"
            thumb_path = protected_root / thumb
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            thumb_path.write_bytes(b"thumb")
        _feed_file(stored, name, author, post=post, thumb=thumb)
        made.append((stored, path, write, thumb_path))
    kept = [_stored(purpose, "clean", purpose.encode()) for purpose in ("attachment", "knowledge")]
    assert [path.exists() for _, path, _, _ in made] == [True, True, True, False]

    with _commit_callbacks(django_capture_on_commit_callbacks) as (on_default, on_migrate):
        stand_reset()
        for stored, path, write, _ in made:
            assert not _on("core.StoredFile").filter(pk=stored.pk).exists(), "StoredFile файла ленты остался"
            assert path.exists() == write, "файл на диске тронут до фиксации"
    assert on_migrate, "стирание файлов с диска не поставлено в on_commit соединения migrate"

    assert _on("feed.FeedFile").count() == 0
    for stored, path, _, thumb_path in made:
        assert not path.exists(), f"файл ленты остался на диске: {path.parent.name}"
        if thumb_path is not None:
            assert not thumb_path.exists(), "эскиз остался на диске"
    for stored, path in kept:
        assert _on("core.StoredFile").filter(pk=stored.pk).exists(), f"StoredFile {stored.purpose} стёрт"
        assert path.read_bytes() == stored.purpose.encode(), f"файл {stored.purpose} тронут"


@MIGRATE
def test_feed_stand_reset_wipes_whole_thumbs_directory(protected_root, django_capture_on_commit_callbacks):
    """FR-640: каталог `PROTECTED_ROOT/attachments/thumbs/` стирается целиком: и эскизы без строк в базе (строки стёр
    общий сброс ядра), и вложенные файлы; соседние файлы `attachments/` не тронуты (план, «Стенд и приёмка»)."""
    from apps.feed.stand import stand_reset

    thumbs = protected_root / "attachments" / "thumbs"
    (thumbs / "nested").mkdir(parents=True)
    strays = [thumbs / "1001.jpg", thumbs / "1002.webp", thumbs / "nested" / "1003.jpg"]
    for path in strays:
        path.write_bytes(b"stray thumb")
    neighbour = protected_root / "attachments" / "42"
    neighbour.write_bytes(b"original of another module")
    assert all(path.exists() for path in strays)

    with _commit_callbacks(django_capture_on_commit_callbacks):
        stand_reset()

    for path in strays:
        assert not path.exists(), f"эскиз без строки остался: {path.name}"
    assert not thumbs.exists() or not any(thumbs.rglob("*")), "каталог эскизов не пуст"
    assert neighbour.read_bytes() == b"original of another module", "тронут файл вне каталога эскизов"


@MIGRATE
def test_feed_stand_reset_restores_feed_settings_to_three_years(protected_root, django_capture_on_commit_callbacks):
    """FR-640, FR-638: срок хранения, изменённый администратором (7 лет, автор и время правки), после сброса —
    `FeedSettings(pk=1, retention_years=3)`, одна строка, без автора и времени правки."""
    from apps.feed.stand import stand_reset

    _everything_on_migrate(_person("Автор Стенда"), _person("Читатель Стенда"))
    row = _on("feed.FeedSettings").get(pk=1)
    assert row.retention_years == 7 and row.updated_by_id is not None

    with _commit_callbacks(django_capture_on_commit_callbacks):
        stand_reset()

    rows = list(_on("feed.FeedSettings").all())
    assert [(r.pk, r.retention_years) for r in rows] == [(1, 3)]
    assert rows[0].updated_by_id is None and rows[0].updated_at is None


@MIGRATE
def test_feed_stand_reset_returns_post_all_to_all_roles_and_moderate_to_admin_after_removal(
        protected_root, django_capture_on_commit_callbacks):
    """FR-640: снятые в сценарии права возвращаются: «Писать всем» — всем ролям (в том числе роли, созданной
    администратором), «Модерировать ленту» — только «Администратору портала» (сброс сохраняет связи ролей, поэтому
    каждый круг браузеров начинается с состояния установки)."""
    from apps.feed.stand import stand_reset

    Role = support.model("core.Role")
    through = Role.permissions.through
    custom = _on("core.Role").create(name="Роль администратора для стенда", is_builtin=False)
    through.objects.using("migrate").filter(permission__code="feed.post_all",
                                            role__name__in=[support.STAFF_ROLE, support.MANAGER_ROLE]).delete()
    through.objects.using("migrate").filter(permission__code="feed.moderate").delete()
    assert not _on("core.Role").filter(permissions__code="feed.moderate").exists()
    assert not _on("core.Role").filter(name=support.STAFF_ROLE, permissions__code="feed.post_all").exists()

    with _commit_callbacks(django_capture_on_commit_callbacks):
        stand_reset()

    everyone = set(_on("core.Role").values_list("name", flat=True))
    assert custom.name in everyone
    assert set(_on("core.Role").filter(permissions__code="feed.post_all").values_list("name", flat=True)) == everyone
    assert set(_on("core.Role").filter(permissions__code="feed.moderate").values_list("name", flat=True)) \
        == {support.ADMIN_ROLE}
    assert _on("core.Permission").filter(code__in=fd.PERMISSIONS_007).count() == 2


@MIGRATE
def test_feed_stand_reset_disconnects_core_role_permissions_m2m_handler_during_seed(
        protected_root, monkeypatch, django_capture_on_commit_callbacks):
    """FR-640: на время `seed(stand=True)` обработчик `m2m_changed` ядра (`core-perms-role-permissions`) отключён
    (иначе его чтение через `default` ждёт незафиксированный `TRUNCATE` транзакции `migrate`) и возвращён после; `seed`
    вызван с `stand=True` на соединении `migrate` (раздел 1.3). Подмена — на модуле миграции, с проходом к настоящей
    функции."""
    from apps.feed.stand import stand_reset

    module = _seed_module()
    real = module.seed
    seen = []

    def spy(apps, schema_editor, *args, **kwargs):
        seen.append({"connected": _core_handler_connected(), "stand": kwargs.get("stand"),
                     "alias": schema_editor.connection.alias})
        return real(apps, schema_editor, *args, **kwargs)

    monkeypatch.setattr(module, "seed", spy)
    assert _core_handler_connected(), "до сброса обработчик ядра не подключён (тест неисправен)"
    with _commit_callbacks(django_capture_on_commit_callbacks):
        stand_reset()
    assert seen == [{"connected": False, "stand": True, "alias": "migrate"}], seen
    assert _core_handler_connected(), "обработчик m2m_changed прав ядра не подключён обратно"


@MIGRATE
def test_feed_stand_reset_reconnects_m2m_handler_in_finally_when_seed_raises(
        protected_root, monkeypatch, django_capture_on_commit_callbacks):
    """FR-640: `seed` бросил исключение — оно доходит до вызывающего, а обработчик `m2m_changed` ядра возвращён в
    `finally` (иначе все следующие смены прав ролей не сбрасывали бы кэш прав)."""
    from apps.feed.stand import stand_reset

    module = _seed_module()

    def broken(apps, schema_editor, *args, **kwargs):
        assert not _core_handler_connected(), "обработчик не отключён на время seed"
        raise RuntimeError("сбой seed в тесте")

    monkeypatch.setattr(module, "seed", broken)
    assert _core_handler_connected()
    with pytest.raises(RuntimeError, match="сбой seed в тесте"):
        with _commit_callbacks(django_capture_on_commit_callbacks):
            stand_reset()
    assert _core_handler_connected(), "обработчик m2m_changed не подключён обратно после исключения"


def test_feed_stand_reset_is_registered_last_and_runs_first():
    """FR-640: в точке `stand_reset` функция `apps.feed.stand.stand_reset` зарегистрирована последней, сразу после
    `apps.lists.stand.stand_reset`; команда зовёт функции в обратном порядке, поэтому `feed` стирается первым
    (раздел 1.3)."""
    from apps.core import extensions
    from apps.feed.stand import stand_reset

    registered = list(extensions.registered("stand_reset"))
    names = [func.__module__ for func in registered]
    assert registered.count(stand_reset) == 1, "stand_reset модуля feed не зарегистрирован ровно один раз"
    assert registered[-1] is stand_reset, "stand_reset модуля feed не последний"
    assert names[-2] == "apps.lists.stand", f"перед feed стоит {names[-2]}, а не lists"
    call_order = [func.__module__ for func in reversed(registered)]
    assert call_order[0] == "apps.feed.stand", "feed вызывается не первым"


@PLAIN
def test_feed_require_stand_refuses_without_e2e_stand_flag(monkeypatch, django_assert_num_queries):
    """FR-640: `require_stand()` без `E2E_STAND=1` (нет переменной, «0», пусто) бросает `CommandError(REFUSAL)` раньше
    любого запроса к базе; с `E2E_STAND=1` не бросает; `REFUSAL` — текст контракта (раздел 1.3)."""
    from apps.feed import stand

    assert stand.REFUSAL == REFUSAL
    for value in (None, "0", ""):
        if value is None:
            monkeypatch.delenv("E2E_STAND", raising=False)
        else:
            monkeypatch.setenv("E2E_STAND", value)
        with django_assert_num_queries(0):
            with pytest.raises(CommandError) as refused:
                stand.require_stand()
        assert str(refused.value) == REFUSAL, repr(value)
    monkeypatch.setenv("E2E_STAND", "1")
    assert stand.require_stand() is None


# --- команда e2e_feed_shift (контракт 14.1) -----------------------------------------------------------------------

def _run(command: str, *args) -> str:
    out = StringIO()
    call_command(command, *args, stdout=out)
    return out.getvalue()


def _shift(*args) -> str:
    return _run("e2e_feed_shift", *args)


def _retention(*args) -> str:
    return _run("e2e_feed_retention", *args)


SHIFTED_FIELDS = ("event_start", "event_end", "remind_at", "reminded_for_start", "important_until")
ALL_FIELDS = SHIFTED_FIELDS + ("published_at", "edited_at", "text", "event_title", "event_place")


def _state(post) -> dict:
    return support.model("feed.Post").objects.filter(pk=post.pk).values(*ALL_FIELDS).get()


def _moved(state: dict, delta: timedelta) -> dict:
    """Ожидаемое состояние: поля сдвига — на `delta` раньше (пустые остаются пустыми), прочие — прежние."""
    return {name: (value - delta if name in SHIFTED_FIELDS and value is not None else value)
            for name, value in state.items()}


def _stand_data(clock) -> dict:
    """Сейчас 2026-03-10 12:00 (Москва). События далеко в будущем (напоминания не наступают): `reminded` — напоминание
    уже было (`reminded_for_start = event_start`, `remind_at` пусто), `pending` — напоминание впереди (`remind_at =
    event_start − 1 ч`), `short` — начало меньше чем через час после публикации (`remind_at` пусто, напоминания не
    было); две важные записи с разными сроками; обычная запись."""
    clock.set(fd.moscow(2026, 3, 10, 12))
    Post = support.model("feed.Post")
    author, reader = support.make_employee(), support.make_employee()
    now = timezone.now()
    reminded = fd.make_event(author, start=now + timedelta(days=40), to=[reader], title="Напомнили")
    Post.objects.filter(pk=reminded.pk).update(remind_at=None, reminded_for_start=reminded.event_start)
    pending = fd.make_event(author, start=now + timedelta(days=41), to=[reader], title="Ждёт напоминания")
    short = fd.make_event(author, start=now + timedelta(days=42), to=[reader], title="Короткое")
    Post.objects.filter(pk=short.pk).update(remind_at=None, reminded_for_start=None)
    important_a = fd.make_important(author, until=now + timedelta(days=5), to=[reader])
    important_b = fd.make_important(author, until=now + timedelta(days=9), to=("all",))
    plain = fd.make_post(author, to=[reader], text="Обычная запись", edited_at=now)
    return {"author": author, "reader": reader, "reminded": reminded, "pending": pending, "short": short,
            "important_a": important_a, "important_b": important_b, "plain": plain}


def _event_posts(data):
    return [data["reminded"], data["pending"], data["short"]]


@contextlib.contextmanager
def _post_saves():
    """Считает `post_save` модели `Post`: сдвиг прямой записью (`update`) его не шлёт, `save()` — шлёт."""
    Post = support.model("feed.Post")
    calls = []

    def receiver(sender, instance, **kwargs):
        calls.append(instance.pk)

    post_save.connect(receiver, sender=Post, weak=False, dispatch_uid="t7134-post-save-spy")
    try:
        yield calls
    finally:
        post_save.disconnect(sender=Post, dispatch_uid="t7134-post-save-spy")


@PLAIN
def test_e2e_feed_shift_refuses_without_e2e_stand_flag(monkeypatch, clock, django_assert_num_queries):
    """FR-618: без `E2E_STAND=1` команда падает `CommandError(REFUSAL)` раньше любого запроса к базе (даже при
    `--minutes 0`: проверка стенда — первая строка `handle`); данные не меняются (раздел 14.1)."""
    monkeypatch.delenv("E2E_STAND", raising=False)
    data = _stand_data(clock)
    before = {label: _state(post) for label, post in data.items() if label not in ("author", "reader")}
    for number in ("1", "100", "0"):
        with django_assert_num_queries(0):
            with pytest.raises(CommandError) as refused:
                _shift("--minutes", number)
        assert str(refused.value) == REFUSAL, number
    assert {label: _state(data[label]) for label in before} == before, "отказавшая команда сдвинула данные"


@PLAIN
def test_e2e_feed_shift_accepts_1_and_10080_minutes(monkeypatch, clock):
    """FR-618: `--minutes 1` и `--minutes 10080` принимаются: начало и конец события сдвигаются ровно на 1 и затем на
    10 080 минут назад; вывод — одна строка с числами (раздел 14.1)."""
    monkeypatch.setenv("E2E_STAND", "1")
    clock.set(fd.moscow(2026, 3, 10, 12))
    author = support.make_employee()
    event = fd.make_event(author, start=timezone.now() + timedelta(days=40), to=("all",))
    start, end = event.event_start, event.event_end
    assert _shift("--minutes", "1") == "feed_shift: shifted=1 reminded=0 important=0\n"
    assert _state(event)["event_start"] == start - timedelta(minutes=1)
    assert _state(event)["event_end"] == end - timedelta(minutes=1)
    assert _shift("--minutes", "10080") == "feed_shift: shifted=1 reminded=0 important=0\n"
    assert _state(event)["event_start"] == start - timedelta(minutes=1) - timedelta(minutes=10080)
    assert _state(event)["event_end"] == end - timedelta(minutes=10081)


@PLAIN
def test_e2e_feed_shift_rejects_0_and_10081_minutes_without_changes(monkeypatch, clock):
    """FR-618: `--minutes 0` и `--minutes 10081` — `CommandError("Число вне пределов от 1 до 10080: N")`, данные не
    меняются; без `--minutes` и с нечисловым значением — тоже `CommandError` (разбор аргументов; раздел 14.1)."""
    monkeypatch.setenv("E2E_STAND", "1")
    data = _stand_data(clock)
    before = {label: _state(post) for label, post in data.items() if label not in ("author", "reader")}
    for number in ("0", "10081"):
        with pytest.raises(CommandError) as refused:
            _shift("--minutes", number)
        assert str(refused.value) == f"Число вне пределов от 1 до 10080: {number}"
    for args in ((), ("--minutes", "много")):
        with pytest.raises(CommandError):
            _shift(*args)
    assert {label: _state(data[label]) for label in before} == before, "отклонённая команда изменила данные"


@PLAIN
def test_e2e_feed_shift_moves_start_end_remind_at_and_reminded_for_start_of_all_events_back_without_save(
        monkeypatch, clock):
    """FR-618: `event_start`, `event_end`, `remind_at` и `reminded_for_start` всех событий сдвинуты на N минут раньше
    (пустые остаются пустыми; у «напомнили» `reminded_for_start` по-прежнему равно `event_start`); обычная запись, текст,
    название, место, `published_at`, `edited_at` не тронуты; запись прямая, без `save()` (раздел 14.1)."""
    monkeypatch.setenv("E2E_STAND", "1")
    data = _stand_data(clock)
    events = _event_posts(data)
    states = {post.pk: _state(post) for post in events}
    plain_before = _state(data["plain"])
    assert states[data["reminded"].pk]["reminded_for_start"] == states[data["reminded"].pk]["event_start"]
    assert states[data["pending"].pk]["remind_at"] is not None
    assert states[data["short"].pk]["remind_at"] is None

    delta = timedelta(minutes=45)
    with _post_saves() as saved:
        out = _shift("--minutes", "45")

    assert saved == [], "команда звала save() модели Post"
    assert SHIFT_LINE.fullmatch(out), out
    for post in events:
        assert _state(post) == _moved(states[post.pk], delta), post.event_title
    reminded = _state(data["reminded"])
    assert reminded["reminded_for_start"] == reminded["event_start"], "признак «напомнили» разошёлся с началом"
    assert reminded["remind_at"] is None and _state(data["short"])["reminded_for_start"] is None
    assert _state(data["plain"]) == plain_before, "обычная запись сдвинута"


@PLAIN
def test_e2e_feed_shift_moves_important_until_of_important_posts_back(monkeypatch, clock):
    """FR-613: `important_until` всех важных записей сдвинут на N минут раньше (решение 54 задач); у остальных видов
    записей поля остались пустыми; вывод считает сдвинутые важные записи (`important=2`)."""
    monkeypatch.setenv("E2E_STAND", "1")
    data = _stand_data(clock)
    until = {label: _state(data[label])["important_until"] for label in ("important_a", "important_b")}
    assert all(value is not None for value in until.values())

    out = _shift("--minutes", "90")

    assert SHIFT_LINE.fullmatch(out).group(3) == "2", out
    for label in until:
        assert _state(data[label])["important_until"] == until[label] - timedelta(minutes=90), label
    assert _state(data["plain"])["important_until"] is None
    assert all(_state(post)["important_until"] is None for post in _event_posts(data))


@PLAIN
def test_e2e_feed_shift_runs_reminders_job_in_process_after_shift(monkeypatch, clock):
    """FR-618: после сдвига команда в своём процессе (не через очередь) выполняет задание напоминаний: без сдвига
    напоминания нет (до него 10 минут), после сдвига на 15 минут `remind_at` наступил, а событие ещё не началось — создано
    уведомление `feed.event_reminder` адресату и автору, `reminded_for_start = event_start`, `remind_at` пусто
    (раздел 14.1)."""
    monkeypatch.setenv("E2E_STAND", "1")
    clock.set(fd.moscow(2026, 3, 10, 12))
    author, reader = support.make_employee(), support.make_employee()
    event = fd.make_event(author, start=timezone.now() + timedelta(minutes=70), to=[reader])
    assert event.remind_at == event.event_start - timedelta(hours=1)
    Notification = support.model("notify.Notification")
    assert fd.run_reminders(timezone.now()).reminded == 0
    assert not Notification.objects.filter(kind="feed.event_reminder").exists(), "уведомление до сдвига"

    out = _shift("--minutes", "15")

    assert SHIFT_LINE.fullmatch(out).group(1, 2) == ("1", "1"), out
    assert sorted(Notification.objects.filter(kind="feed.event_reminder").values_list("user_id", flat=True)) \
        == sorted([author.pk, reader.pk])
    row = support.model("feed.Post").objects.get(pk=event.pk)
    assert row.event_start == event.event_start - timedelta(minutes=15)
    assert row.reminded_for_start == row.event_start and row.remind_at is None


@PLAIN
def test_e2e_feed_shift_prints_single_line_with_shifted_reminded_and_important(monkeypatch, clock):
    """FR-618: вывод — ровно одна строка `feed_shift: shifted=<событий> reminded=<напоминаний> important=<важных>`
    (решение 54 задач): три события, одно из которых напомнило; две важные записи; обычная запись не считается."""
    monkeypatch.setenv("E2E_STAND", "1")
    data = _stand_data(clock)
    due = fd.make_event(data["author"], start=timezone.now() + timedelta(minutes=70), to=[data["reader"]])
    assert due.remind_at is not None
    out = StringIO()
    call_command("e2e_feed_shift", "--minutes", "15", stdout=out)
    text = out.getvalue()
    assert text.count("\n") == 1, repr(text)
    found = SHIFT_LINE.fullmatch(text)
    assert found, repr(text)
    assert found.groups() == ("4", "1", "2"), "четыре события, одно напомнило, две важные записи"


# --- команда e2e_feed_retention (контракт 14.2) ------------------------------------------------------------------

def _retention_data(clock) -> dict:
    """Сейчас 2026-03-10 12:00 (Москва); срок хранения 3 года; три записи пяти-, шести- и семидневной давности с
    адресатами `to` и `mention` (копии `published_at` в `Recipient`)."""
    clock.set(fd.moscow(2026, 3, 10, 12))
    support.model("feed.FeedSettings").objects.update_or_create(pk=1, defaults={"retention_years": 3})
    author, reader, mentioned = (support.make_employee() for _ in range(3))
    now = timezone.now()
    posts = [fd.make_post(author, to=[reader], mentions=[mentioned], published_at=now - timedelta(days=days),
                          text=f"Запись {days} дн.")
             for days in (5, 6, 7)]
    return {"author": author, "reader": reader, "mentioned": mentioned, "posts": posts}


def _published(post) -> dict:
    Post, Recipient = support.model("feed.Post"), support.model("feed.Recipient")
    return {"post": Post.objects.filter(pk=post.pk).values_list("published_at", flat=True).get(),
            "recipients": sorted(Recipient.objects.filter(post=post).values_list("published_at", flat=True))}


@PLAIN
def test_e2e_feed_retention_refuses_without_e2e_stand_flag(monkeypatch, clock, django_assert_num_queries):
    """FR-638: без `E2E_STAND=1` команда падает `CommandError(REFUSAL)` раньше любого запроса к базе (даже при
    `--age-days 0`); даты записей не меняются, записи не удаляются (раздел 14.2)."""
    monkeypatch.delenv("E2E_STAND", raising=False)
    data = _retention_data(clock)
    before = [_published(post) for post in data["posts"]]
    for number in ("1", "4000", "0"):
        with django_assert_num_queries(0):
            with pytest.raises(CommandError) as refused:
                _retention("--age-days", number)
        assert str(refused.value) == REFUSAL, number
    assert [_published(post) for post in data["posts"]] == before


@PLAIN
def test_e2e_feed_retention_accepts_1_and_4000_days(monkeypatch, clock):
    """FR-638: `--age-days 1` и `--age-days 4000` принимаются: на 1 сутки запись состарена и не удалена
    (`aged=1 deleted=0`); на 4000 суток (старше срока в 3 года) состарена и удалена ночным заданием
    (`aged=1 deleted=1`) (раздел 14.2)."""
    monkeypatch.setenv("E2E_STAND", "1")
    data = _retention_data(clock)
    post = data["posts"][0]
    start = _published(post)["post"]
    assert _retention("--age-days", "1", "--posts", str(post.pk)) == "feed_retention: aged=1 deleted=0\n"
    assert _published(post)["post"] == start - timedelta(days=1)
    assert _retention("--age-days", "4000", "--posts", str(post.pk)) == "feed_retention: aged=1 deleted=1\n"
    assert not support.model("feed.Post").objects.filter(pk=post.pk).exists()


@PLAIN
def test_e2e_feed_retention_rejects_0_and_4001_days_without_changes(monkeypatch, clock):
    """FR-638: `--age-days 0` и `--age-days 4001` — `CommandError("Число вне пределов от 1 до 4000: N")`, данные не
    меняются; без `--age-days` и с нечисловым значением — тоже `CommandError` (раздел 14.2)."""
    monkeypatch.setenv("E2E_STAND", "1")
    data = _retention_data(clock)
    before = [_published(post) for post in data["posts"]]
    for number in ("0", "4001"):
        with pytest.raises(CommandError) as refused:
            _retention("--age-days", number)
        assert str(refused.value) == f"Число вне пределов от 1 до 4000: {number}"
    for args in ((), ("--age-days", "много")):
        with pytest.raises(CommandError):
            _retention(*args)
    assert [_published(post) for post in data["posts"]] == before, "отклонённая команда изменила данные"
    assert support.model("feed.Post").objects.count() == 3


@PLAIN
def test_e2e_feed_retention_ages_published_at_of_posts_and_recipient_copies(monkeypatch, clock):
    """FR-638: без `--posts` стареют все записи стенда: `published_at` каждой и копия `Recipient.published_at` (строки
    `to` и `mention`) сдвинуты на N суток в прошлое; прочие поля записи не тронуты; записи не удалены (раздел 14.2)."""
    monkeypatch.setenv("E2E_STAND", "1")
    data = _retention_data(clock)
    before = [_published(post) for post in data["posts"]]
    texts = [support.model("feed.Post").objects.get(pk=post.pk).text for post in data["posts"]]
    assert all(len(item["recipients"]) == 2 for item in before)

    out = _retention("--age-days", "10")

    assert RETENTION_LINE.fullmatch(out).groups() == ("3", "0"), out
    for post, old, text in zip(data["posts"], before, texts):
        now = _published(post)
        assert now["post"] == old["post"] - timedelta(days=10)
        assert now["recipients"] == [moment - timedelta(days=10) for moment in old["recipients"]]
        assert now["post"] == now["recipients"][0], "копия в Recipient разошлась с записью"
        assert support.model("feed.Post").objects.get(pk=post.pk).text == text


@PLAIN
def test_e2e_feed_retention_posts_key_ages_only_listed_posts(monkeypatch, clock):
    """FR-638: с `--posts <номера через запятую>` стареют только перечисленные записи (и их `Recipient`); остальные
    не тронуты; неверный список (не целые) — `CommandError("Неверный список записей: <значение>")`, данные не
    меняются (решение 54 задач, раздел 14.2)."""
    monkeypatch.setenv("E2E_STAND", "1")
    data = _retention_data(clock)
    first, second, third = data["posts"]
    before = {post.pk: _published(post) for post in data["posts"]}

    with pytest.raises(CommandError) as refused:
        _retention("--age-days", "10", "--posts", f"{first.pk},xx")
    assert str(refused.value) == f"Неверный список записей: {first.pk},xx"
    assert {post.pk: _published(post) for post in data["posts"]} == before, "неверный список изменил данные"

    out = _retention("--age-days", "10", "--posts", f"{first.pk},{third.pk}")

    assert RETENTION_LINE.fullmatch(out).groups() == ("2", "0"), out
    for post in (first, third):
        assert _published(post)["post"] == before[post.pk]["post"] - timedelta(days=10), post.pk
        assert _published(post)["recipients"] == [m - timedelta(days=10) for m in before[post.pk]["recipients"]]
    assert _published(second) == before[second.pk], "неперечисленная запись состарена"


@PLAIN
def test_e2e_feed_retention_runs_night_job_in_process_and_prints_single_line_with_aged_and_deleted(
        monkeypatch, clock):
    """FR-638: после сдвига команда в своём процессе (не через очередь) запускает ночное задание: две записи, состаренные
    на 4000 суток, удалены вместе с комментарием, третья осталась; в журнале одна запись `feed.retention_purged` с
    `posts=2`; вывод — ровно одна строка `feed_retention: aged=<N> deleted=<M>` (раздел 14.2)."""
    monkeypatch.setenv("E2E_STAND", "1")
    data = _retention_data(clock)
    first, second, third = data["posts"]
    comment = fd.comment(first, data["reader"], "Комментарий к удаляемой записи")
    out = StringIO()

    call_command("e2e_feed_retention", "--age-days", "4000", "--posts", f"{first.pk},{second.pk}", stdout=out)

    text = out.getvalue()
    assert text.count("\n") == 1, repr(text)
    assert RETENTION_LINE.fullmatch(text), repr(text)
    assert RETENTION_LINE.fullmatch(text).groups() == ("2", "2")
    Post = support.model("feed.Post")
    assert not Post.objects.filter(pk__in=[first.pk, second.pk]).exists()
    assert Post.objects.filter(pk=third.pk).exists()
    assert not support.model("core.Comment").objects.filter(pk=comment.pk).exists()
    events = list(support.model("core.AuditEvent").objects.filter(action="feed.retention_purged"))
    assert len(events) == 1 and events[0].after == {"posts": 2}
