"""Записи ленты для нагрузочного прогона среза 007 (NFR-601…NFR-603, NFR-612; PLAN-007, «Нагрузка»;
CONTRACT-007, 14.3): добавляет записи ленты до LOAD_POSTS (по умолчанию 50000) и комментарии до
LOAD_COMMENTS (по умолчанию 200000), отметки — в долях замера F1.

Распределение — как в замере F1 (crm-work/slice007/plan/facts/F1-db.md, «Условия замера»): виды —
85 % сообщений, 10 % важных со сроком 14 суток, 5 % событий (начало через 1–72 часа после публикации);
адресаты — 20 % «Всем», 40 % подразделениям (1–2), 40 % людям (1–10; без структуры подразделений вся
эта доля уходит людям); упоминания — у 10 % записей и 5 % комментариев (маркеры `@[<номер>]` в тексте,
строки адресатов `via='mention'`); отметки — «Нравится» ~2,95 на запись и ~1 на комментарий,
«Прочитано» ~18 на важную запись, ответы событий ~13,6 на событие («Пойду» вдвое чаще «Не смогу»).
Время публикации размазано по трём годам и округлено до часа: совпадения времени проверяют курсор
«Ещё записи» (F1 Ф1). Число комментариев на запись — со скошенным хвостом до 60 («тяжёлые» записи
F1 Ф6). Авторы — первые 50 действующих сотрудников, адресаты и отметившие — первые 200, подразделения —
из структуры стенда. Показы не создаются: строки старше 31 дня чистит ночное задание (план), а
непрочитанное прогона набирается живыми показами; уведомления не создаются — их создадут публикации
самого прогона. Тексты — из словаря настоящих русских слов ИТ-тематики, встроенного в скрипт (тот же
приём, что `fill_lists.py`); без имён, похожих на ПДн, файлов и секретов.

Что делает: создаёт записи, строки адресатов и упоминаний, комментарии ядра со строками `FeedComment`
(`object_ref` — `feed.post:<номер записи>`, строчными, как служба ленты), пересчитывает векторы поиска
теми же UPDATE, что служба, создаёт отметки. Повторный запуск добирает до цели: уже созданные строки
не меняются и не удаляются. Пачки по 250 записей/комментариев в своей транзакции, цели и объёмы пачек
не строят больших списков в памяти. Работает ТОЛЬКО при E2E_STAND=1 (как e2e_reset_stand); данные
убирает следующий сброс приёмки. Каталог tests в образ не входит, поэтому скрипт подаётся на вход shell:

    docker compose -f deploy/docker-compose.yml --profile dev exec -T -e LOAD_POSTS=50000 \
        -e LOAD_COMMENTS=200000 standtools python manage.py shell --no-imports \
        < backend/tests/load/fill_feed.py

Вывод: `fill_feed: posts=<число> comments=<число> likes=<число>` (в `likes` — отметки «Нравится»
записей и комментариев).
"""
import os
import random
import sys

if os.environ.get("E2E_STAND") != "1":
    sys.exit("Скрипт работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено.")

from datetime import timedelta  # noqa: E402

from django.db import transaction  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.core.models import Comment, User  # noqa: E402
from apps.feed.models import (CommentLike, EventAnswer, FeedComment, Post,  # noqa: E402
                              PostLike, ReadMark, Recipient)
from apps.feed.services import search  # noqa: E402

CHUNK = 250               # записей или комментариев в одной пачке (как fill_lists.py)
FLUSH = 2000              # строк отметок в одной пачке
POSTS_LIMIT = 500000      # безопасные границы целей из окружения
COMMENTS_LIMIT = 2000000
SPREAD_DAYS = 3 * 365 - 1   # записи за три года, внутри срока хранения по умолчанию
IMPORTANT_DAYS = 14       # срок важной записи замера F1
EVENT_HOURS = (1, 72)     # начало события после публикации
COMMENT_CAP = 60          # хвост числа комментариев на запись (F1 Ф6: максимум 61)
LIKE_CAP = 8              # «Нравится» на запись, хвост замера F1
COMMENT_LIKE_CAP = 4
COMMENT_LIKE_WEIGHTS = (36, 37, 18, 6, 3)   # 0…4 отметки на комментарий, в среднем ~1
# доли замера F1: 147590 отметок на 50000 записей, 199057 на 200000 комментариев,
# 90447 «Прочитано» на 5000 важных, 33906 ответов на 2500 событий
LIKES_PER_POST = 147590 / 50000
COMMENT_LIKES_PER_COMMENT = 199057 / 200000
READS_PER_IMPORTANT = 90447 / 5000
ANSWERS_PER_EVENT = 33906 / 2500
KIND_SHARES = (("post", 85), ("important", 10), ("event", 5))
TO_ALL_SHARE, TO_UNIT_SHARE, TO_USER_SHARE = 20, 40, 40
POST_MENTION_SHARE, COMMENT_MENTION_SHARE = 0.10, 0.05
WORDS = (
    "принтер картридж бумага сканер монитор клавиатура мышь ноутбук компьютер сервер сеть кабель роутер коммутатор "
    "интернет почта письмо вложение пароль логин учётная запись доступ права папка файл документ диск резервная копия "
    "восстановление программа установка обновление лицензия антивирус вирус защита шифрование сертификат подпись токен "
    "телефон гарнитура камера видеосвязь собрание календарь проектор экран розетка питание аккумулятор зарядка "
    "драйвер система настройка параметр профиль пользователь сотрудник отдел заявка обращение инструкция регламент "
    "порядок процедура проверка ошибка сбой отказ перезагрузка зависание память процессор температура вентилятор "
    "договор поставка гарантия ремонт склад кабинет этаж здание номер тариф оператор карта носитель удостоверяющий центр"
).split()


def phrase(rng: random.Random, low: int = 1, high: int = 4) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(rng.randint(low, high)))


def make_text(rng: random.Random) -> str:
    return " ".join(phrase(rng, 5, 10).capitalize() + "." for _ in range(rng.randint(1, 3)))


def make_comment_text(rng: random.Random) -> str:
    return " ".join(phrase(rng, 3, 7).capitalize() + "." for _ in range(rng.randint(1, 2)))


def _target(name: str, default: int, high: int) -> int:
    """Цель из окружения; не целое число или вне безопасных границ — отказ до любого изменения."""
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        sys.exit(f"{name} — не целое число: {raw!r}; ничего не изменено.")
    if not 1 <= value <= high:
        sys.exit(f"{name} вне пределов от 1 до {high}: {value}; ничего не изменено.")
    return value


def _spread(counts: list[int], missing: int, cap: int, rng: random.Random) -> int:
    """Подогнать сумму счётчиков под `missing`, не выходя за `cap`; возвращает достижимую цель."""
    missing = min(missing, cap * len(counts))
    total = sum(counts)
    while total != missing:
        index = rng.randrange(len(counts))
        if total > missing and counts[index] > 0:
            counts[index] -= 1
            total -= 1
        elif total < missing and counts[index] < cap:
            counts[index] += 1
            total += 1
    return missing


rng = random.Random(20261107)
posts_target = _target("LOAD_POSTS", 50000, POSTS_LIMIT)
comments_target = _target("LOAD_COMMENTS", 200000, COMMENTS_LIMIT)
authors = list(User.objects.filter(state="active").order_by("pk")[:50])
if not authors:
    sys.exit("Нет действующих сотрудников: сначала подготовьте учётные записи; ничего не изменено.")
author_ids = [user.pk for user in authors]
people = list(User.objects.filter(state="active").order_by("pk").values_list("pk", flat=True)[:200])
units: list[int] = []
try:
    from apps.org.services import structure

    units = [unit.id for unit in structure.all_units()]
except Exception:  # noqa: BLE001 — без структуры подразделений доля адресатов уходит людям
    pass
now = timezone.now()
kind_pool = tuple(kind for kind, share in KIND_SHARES for _ in range(share))
max_people = max(1, len(people))


def _mentions(share: float, low: int, high: int) -> list[int]:
    """Упомянутые действующие сотрудники: маркеры текста и строки адресатов `via='mention'`."""
    if rng.random() >= share:
        return []
    size = rng.randint(low, min(high, max_people))
    return list(dict.fromkeys(rng.sample(people, size)))


def _new_post() -> tuple[Post, list[int], list[int], list[int]]:
    """Запись с полями вида и текстом с маркерами упоминаний; ограничения моделей соблюдены."""
    kind = rng.choice(kind_pool)
    published = (now - timedelta(days=rng.randint(0, SPREAD_DAYS), hours=rng.randrange(24))
                 ).replace(minute=0, second=0, microsecond=0)
    text = make_text(rng)
    mentioned = _mentions(POST_MENTION_SHARE, 1, 2)
    if mentioned:
        text += " " + " ".join(f"@[{user_id}]" for user_id in mentioned)
    roll = rng.randrange(100)
    to_all, unit_ids, user_ids = False, [], []
    if roll < TO_ALL_SHARE:
        to_all = True
    elif roll < TO_ALL_SHARE + TO_UNIT_SHARE and units:
        unit_ids = rng.sample(units, rng.randint(1, min(2, len(units))))
    else:
        user_ids = rng.sample(people, rng.randint(1, min(TO_USER_SHARE // 4, max_people)))
    post = Post(author=rng.choice(authors), kind=kind, text=text, to_all=to_all, published_at=published)
    if kind == "important":
        post.important_until = published + timedelta(days=IMPORTANT_DAYS)
    elif kind == "event":
        post.event_title = phrase(rng, 2, 4).capitalize()[:200]
        post.event_place = phrase(rng, 1, 2).capitalize()[:200]
        post.event_start = published + timedelta(hours=rng.randint(*EVENT_HOURS))
        post.event_end = post.event_start + timedelta(hours=rng.randint(1, 4))
        # напоминание «уже отправлено»: cron напоминаний работает каждую минуту и не должен
        # рассылать тысячи уведомлений по наполнению
        post.reminded_for_start = post.event_start
    return post, unit_ids, user_ids, mentioned


def _recipient_rows(posts) -> list:
    rows = []
    for post, unit_ids, user_ids, mentioned in posts:
        for unit_id in unit_ids:
            rows.append(Recipient(post=post, kind=Recipient.Kind.UNIT, unit_id=unit_id,
                                  via=Recipient.Via.TO, published_at=post.published_at))
        for user_id in user_ids:
            rows.append(Recipient(post=post, kind=Recipient.Kind.USER, user_id=user_id,
                                  via=Recipient.Via.TO, published_at=post.published_at))
        for user_id in mentioned:
            rows.append(Recipient(post=post, kind=Recipient.Kind.USER, user_id=user_id,
                                  via=Recipient.Via.MENTION, published_at=post.published_at))
    return rows


def _create_posts(missing: int) -> None:
    """Пачки записей с адресатами и векторами поиска; уже созданные записи не трогаются."""
    while missing > 0:
        size = min(CHUNK, missing)
        with transaction.atomic():
            made = [_new_post() for _ in range(size)]
            Post.objects.bulk_create([row[0] for row in made])
            Recipient.objects.bulk_create(_recipient_rows(made), ignore_conflicts=True)
            search.vectors(post_ids=[row[0].pk for row in made])
        missing -= size


def _comment_span(published) -> int:
    """Сколько секунд доступно комментарию: от публикации до минуты назад, не меньше нуля."""
    return max(0, int((now - published).total_seconds()) - 60)


def _create_comments(missing: int) -> None:
    """Комментарии к записям по счётчикам со скошенным хвостом; векторы — теми же UPDATE, что служба."""
    if missing <= 0:
        return
    post_rows = list(Post.objects.order_by("pk").values_list("pk", "published_at"))
    if not post_rows:
        return
    cap = max(COMMENT_CAP, -(-missing // len(post_rows)))
    counts = [min(cap, int(rng.expovariate(1 / 4.0))) for _ in post_rows]
    _spread(counts, missing, cap, rng)
    buffer: list[Comment] = []
    mention_rows: list[Recipient] = []
    for (post_id, published), count in zip(post_rows, counts):
        if not count:
            continue
        span = _comment_span(published)
        for _ in range(count):
            text = make_comment_text(rng)
            mentioned = _mentions(COMMENT_MENTION_SHARE, 1, 2)
            if mentioned:
                text += " " + " ".join(f"@[{user_id}]" for user_id in mentioned)
                mention_rows.extend(
                    Recipient(post_id=post_id, kind=Recipient.Kind.USER, user_id=user_id,
                              via=Recipient.Via.MENTION, published_at=published)
                    for user_id in mentioned)
            buffer.append(Comment(object_ref=f"feed.post:{post_id}", author_id=rng.choice(author_ids),
                                  text=text,
                                  created_at=published + timedelta(seconds=rng.randrange(span + 1))))
        if len(buffer) >= CHUNK:
            _flush_comments(buffer, mention_rows)
    _flush_comments(buffer, mention_rows)


def _flush_comments(buffer: list[Comment], mention_rows: list[Recipient]) -> None:
    """Пачка комментариев: ядро, строки ленты, упоминания, векторы; буферы опустошаются."""
    if not buffer:
        return
    with transaction.atomic():
        Comment.objects.bulk_create(buffer)
        FeedComment.objects.bulk_create(
            [FeedComment(comment_id=comment.pk, post_id=int(comment.object_ref.rsplit(":", 1)[1]))
             for comment in buffer])
        if mention_rows:
            Recipient.objects.bulk_create(mention_rows, ignore_conflicts=True)
        search.vectors(comment_ids=[comment.pk for comment in buffer])
    buffer.clear()
    mention_rows.clear()


def _create_post_likes(missing: int) -> None:
    """«Нравится» записей: ~2,95 на запись, отметившие — случайные действующие сотрудники."""
    if missing <= 0:
        return
    post_rows = list(Post.objects.order_by("pk").values_list("pk", "published_at"))
    if not post_rows:
        return
    cap = min(LIKE_CAP, max_people)
    counts = [min(cap, int(rng.expovariate(1 / LIKES_PER_POST))) for _ in post_rows]
    _spread(counts, missing, cap, rng)
    buffer: list[PostLike] = []
    for (post_id, published), count in zip(post_rows, counts):
        for user_id in rng.sample(people, count):
            span = max(0, int((now - published).total_seconds()))
            buffer.append(PostLike(post_id=post_id, user_id=user_id,
                                   created_at=published + timedelta(seconds=rng.randrange(span + 1))))
        if len(buffer) >= FLUSH:
            _flush_likes(buffer)
    _flush_likes(buffer)


def _flush_likes(buffer) -> None:
    if not buffer:
        return
    with transaction.atomic():
        PostLike.objects.bulk_create(buffer, ignore_conflicts=True)
    buffer.clear()


def _create_comment_likes(missing: int) -> None:
    """«Нравится» комментариев: ~1 на комментарий, страницы по номерам без большого списка."""
    if missing <= 0:
        return
    buffer: list[CommentLike] = []
    created = 0
    last_pk = 0
    while created < missing:
        rows = list(Comment.objects.filter(object_ref__startswith="feed.post:", pk__gt=last_pk)
                    .order_by("pk").values_list("pk", "object_ref", "created_at")[:FLUSH])
        if not rows:
            break
        last_pk = rows[-1][0]
        for comment_id, object_ref, commented_at in rows:
            if created >= missing:
                break
            count = min(rng.choices(range(COMMENT_LIKE_CAP + 1), weights=COMMENT_LIKE_WEIGHTS)[0],
                        missing - created)
            for user_id in rng.sample(people, count):
                span = max(0, int((now - commented_at).total_seconds()))
                buffer.append(CommentLike(comment_id=comment_id, post_id=int(object_ref.rsplit(":", 1)[1]),
                                          user_id=user_id,
                                          created_at=commented_at + timedelta(seconds=rng.randrange(span + 1))))
            created += count
        if len(buffer) >= FLUSH:
            _flush_comment_likes(buffer)
    _flush_comment_likes(buffer)


def _flush_comment_likes(buffer) -> None:
    if not buffer:
        return
    with transaction.atomic():
        CommentLike.objects.bulk_create(buffer, ignore_conflicts=True)
    buffer.clear()


def _create_read_marks(missing: int) -> None:
    """«Прочитано» важных записей: ~18 на запись, время — между публикацией и концом срока."""
    if missing <= 0:
        return
    rows = list(Post.objects.filter(kind="important").order_by("pk")
                .values_list("pk", "published_at", "important_until"))
    if not rows:
        return
    cap = min(max_people, 40)
    counts = [min(cap, max(0, int(rng.gauss(READS_PER_IMPORTANT, 6)))) for _ in rows]
    _spread(counts, missing, cap, rng)
    buffer: list[ReadMark] = []
    for (post_id, published, until), count in zip(rows, counts):
        end = min(until or now, now)
        span = max(0, int((end - published).total_seconds()))
        for user_id in rng.sample(people, count):
            buffer.append(ReadMark(post_id=post_id, user_id=user_id,
                                   read_at=published + timedelta(seconds=rng.randrange(span + 1))))
        if len(buffer) >= FLUSH:
            _flush_marks(buffer, ReadMark)
    _flush_marks(buffer, ReadMark)


def _create_answers(missing: int) -> None:
    """Ответы событий: ~13,6 на событие, «Пойду» вдвое чаще «Не смогу»."""
    if missing <= 0:
        return
    rows = list(Post.objects.filter(kind="event").order_by("pk")
                .values_list("pk", "published_at", "event_start"))
    if not rows:
        return
    cap = min(max_people, 40)
    counts = [min(cap, max(0, int(rng.gauss(ANSWERS_PER_EVENT, 5)))) for _ in rows]
    _spread(counts, missing, cap, rng)
    buffer: list[EventAnswer] = []
    for (post_id, published, start), count in zip(rows, counts):
        end = min(start or now, now)
        span = max(0, int((end - published).total_seconds()))
        for user_id in rng.sample(people, count):
            answer = EventAnswer.Answer.GO if rng.random() < 2 / 3 else EventAnswer.Answer.NO
            buffer.append(EventAnswer(post_id=post_id, user_id=user_id, answer=answer,
                                      answered_at=published + timedelta(seconds=rng.randrange(span + 1))))
        if len(buffer) >= FLUSH:
            _flush_marks(buffer, EventAnswer)
    _flush_marks(buffer, EventAnswer)


def _flush_marks(buffer, model) -> None:
    if not buffer:
        return
    with transaction.atomic():
        model.objects.bulk_create(buffer, ignore_conflicts=True)
    buffer.clear()


_create_posts(max(0, posts_target - Post.objects.count()))
_create_comments(max(0, comments_target - FeedComment.objects.count()))
_create_post_likes(max(0, round(Post.objects.count() * LIKES_PER_POST) - PostLike.objects.count()))
_create_read_marks(max(0, round(Post.objects.filter(kind="important").count() * READS_PER_IMPORTANT)
                        - ReadMark.objects.count()))
_create_answers(max(0, round(Post.objects.filter(kind="event").count() * ANSWERS_PER_EVENT)
                     - EventAnswer.objects.count()))
_create_comment_likes(max(0, round(FeedComment.objects.count() * COMMENT_LIKES_PER_COMMENT)
                          - CommentLike.objects.count()))
print(f"fill_feed: posts={Post.objects.count()} comments={FeedComment.objects.count()} "
      f"likes={PostLike.objects.count() + CommentLike.objects.count()}")
