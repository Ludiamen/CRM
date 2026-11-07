"""Сервис ленты: срок хранения и ночное задание (срез 007; CONTRACT-007, 5.5).

Ночное задание идёт тремя шагами плана («Срок хранения и ночное задание»):
показы записей старше 31 дня (раздел «Непрочитанное»), записи старше срока
пачками по 1 000 и непривязанные файлы старше 24 часов. «Сейчас» приходит
параметром из ``timezone.now()`` задания один раз (решение 59 задач) и уходит
в каждый шаг плейсхолдером ``%s``. Пачка — способом плана: ORM-каскад в своей
транзакции; повторная проверка на настоящих моделях (T-7229, до реализации) —
1,4 с на 1 000 записей, проверки ссылок ``feed_shown`` при фиксации идут по
индексу внешнего ключа (решение 60), без просмотра таблицы показов. Пачка замыкает
существующие записи ``select_for_update`` до сбора путей, а непривязанные файлы
выбираются и замыкаются в самой транзакции с перепроверкой «без записи и комментария»
(T-7229, ревью: сбор до замка оставлял сирот ``StoredFile`` и уничтожал файлы,
конкурентно привязываемые ``files.bind``). ``VACUUM``
задание не зовёт: место возвращает autovacuum (решение плана).
"""
import pathlib
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.core.models import Comment, StoredFile
from apps.core.services import audit
from apps.core.services import files as core_files
from apps.feed.models import FeedFile, Post
from apps.feed.services import feed_settings

BATCH_SIZE = 1000          # пачка удалений (решение 9 задач)
SHOWN_KEEP_DAYS = 31       # показы записей старше этого чистятся первым шагом (план)
UNBOUND_FILE_HOURS = 24    # непривязанные файлы старше этого удаляются (план)
ACTION = "feed.retention_purged"

SELECT_BATCH_SQL = "SELECT id FROM feed_post WHERE published_at < %s ORDER BY published_at, id LIMIT 1000"
DELETE_SHOWN_SQL = (
    "DELETE FROM feed_shown WHERE post_id IN (SELECT id FROM feed_post WHERE published_at < %s)"
)


def boundary(now, years: int):
    """Граница срока: календарная замена года, 29 февраля → 28 февраля (план)."""
    try:
        return now.replace(year=now.year - years)
    except ValueError:  # 29 февраля в невисокосном году — день 28
        return now.replace(year=now.year - years, day=28)


def count_older(years: int, now=None) -> int:
    """Число записей с ``published_at`` раньше границы нового срока (второй шаг настройки).

    Граница — та же, по которой режёт ночное задание (``boundary``), «сейчас» — единое
    время шага параметром (решение 59 задач): число показывается про тот же момент,
    в который считалась бы граница подтверждённого уменьшения.
    """
    if now is None:
        now = timezone.now()
    return Post.objects.filter(published_at__lt=boundary(now, years)).count()


def select_batch(boundary, limit: int = BATCH_SIZE) -> list[int]:
    """Номера записей одной пачки: ``published_at < %s`` от старых к новым.

    Лимит пачки — константа плана, в тексте запроса литералом ``LIMIT 1000``
    (решение 9 задач); время — параметром (решение 59 задач). Нестандартный
    предел нужен только проверкам, значение — целое из кода, не ввод.
    """
    sql = SELECT_BATCH_SQL if limit == BATCH_SIZE else _batch_sql(limit)
    with connection.cursor() as cursor:
        cursor.execute(sql, [boundary])
        return [row[0] for row in cursor.fetchall()]


def _batch_sql(limit: int) -> str:
    """Тот же литерал выборки с нестандартным пределом пачки."""
    return SELECT_BATCH_SQL[: -len(str(BATCH_SIZE))] + str(int(limit))


def purge_batch(ids, now=None) -> int:
    """Одна пачка в своей транзакции; возвращает число действительно удалённых записей.

    Порядок плана: замок существующих записей пачки, пути файлов и эскизов, комментарии
    ядра пачки одним вызовом ``Comment.objects.filter(object_ref__in=refs).delete()``
    (каскад ORM на ``FeedComment``, ``CommentLike`` и файлы комментариев), записи (каскад
    адресатов, отметок, прочтений, ответов, показов и файлов записи), строки
    ``StoredFile``; диск стирается после фиксации. Замок ``select_for_update`` берётся до
    сбора путей (T-7229, ревью): правки/комментарии ленты идут под таким же замком записи,
    а добавление комментария держит отложенная проверка внешнего ключа — конкурентная
    привязка либо фиксируется до замка (файл уже собран и уходит вместе с записью), либо
    не проходит и откатывается; сирот ``StoredFile`` не остаётся. Запись, которой между
    выборкой и пачкой уже нет, пропускается без ошибки и в число не входит (решение 50
    задач, NFR-610): ``ids`` пересобирается из замкнутых строк. ``now`` — единое «сейчас»
    запуска (решение 59).
    """
    ids = list(ids or [])
    if not ids:
        return 0
    paths: list[pathlib.Path] = []
    stored_ids: list = []
    with transaction.atomic():
        ids = [post.pk for post in Post.objects.select_for_update().order_by("id").filter(pk__in=ids)]
        refs = [f"feed.post:{post_id}" for post_id in ids]
        for row in FeedFile.objects.filter(post_id__in=ids).select_related("file"):
            stored_ids.append(row.file_id)
            paths.append(core_files.attachment_path(row.file))
            if row.thumb:
                paths.append(pathlib.Path(settings.PROTECTED_ROOT) / row.thumb)
        Comment.objects.filter(object_ref__in=refs).delete()
        _, per_model = Post.objects.filter(pk__in=ids).delete()
        if stored_ids:
            StoredFile.objects.filter(pk__in=stored_ids).delete()
        if paths:
            transaction.on_commit(lambda: _erase_paths(paths))
    return per_model.get(Post._meta.label, 0)


def run(now=None) -> int:
    """Три шага по порядку плана; возвращает число удалённых записей.

    Показы записей старше 31 дня чистятся первым шагом: каскад пачки и проверки
    ссылок при фиксации не зависят от размера таблицы показов (F1 Ф11, решение
    60). Цикл пачек заканчивается после неполной пачки (К57); повторный запуск
    ничего не находит. Журнал — одна запись ``feed.retention_purged`` с числом
    удалённых записей, только если оно больше нуля (FR-639).
    """
    if now is None:
        now = timezone.now()

    with connection.cursor() as cursor:
        cursor.execute(DELETE_SHOWN_SQL, [now - timedelta(days=SHOWN_KEEP_DAYS)])

    settings_row = feed_settings.get()
    term = boundary(now, settings_row.retention_years)
    total = 0
    while True:
        ids = select_batch(term)
        if not ids:
            break
        total += purge_batch(ids, now)
        if len(ids) < BATCH_SIZE:
            break

    _purge_unbound_files(now)

    if total > 0:
        audit.record(ACTION, object_type="feed.settings", object_id=str(settings_row.pk),
                     after={"posts": total})
    return total


def _purge_unbound_files(now) -> None:
    """Шаг 3: непривязанные ``FeedFile`` старше 24 часов — строка, ``StoredFile``, диск.

    Кандидаты выбираются и замыкаются ``select_for_update`` в самой транзакции с условиями
    «без записи и без комментария» (T-7229, ревью): конкурентная привязка ``files.bind``
    либо фиксируется до замка — тогда условие выборки её исключает, файл остаётся
    привязанным, — либо ждёт на замке строки, а после удаления строки условный UPDATE
    привязки не находит строку и отказывает; удаляются ровно замкнутые строки, привязанные
    файлы чистка не трогает.
    """
    cutoff = now - timedelta(hours=UNBOUND_FILE_HOURS)
    with transaction.atomic():
        rows = list(
            FeedFile.objects.select_for_update()
            .filter(post__isnull=True, comment__isnull=True, uploaded_at__lt=cutoff)
            .select_related("file")
        )
        if not rows:
            return
        paths: list[pathlib.Path] = []
        stored_ids: list = []
        for row in rows:
            stored_ids.append(row.file_id)
            paths.append(core_files.attachment_path(row.file))
            if row.thumb:
                paths.append(pathlib.Path(settings.PROTECTED_ROOT) / row.thumb)
        FeedFile.objects.filter(pk__in=[row.pk for row in rows]).delete()
        StoredFile.objects.filter(pk__in=stored_ids).delete()
        transaction.on_commit(lambda: _erase_paths(paths))


def _erase_paths(paths) -> None:
    """Стирает файлы с диска после фиксации; отсутствующий файл — не ошибка."""
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
