"""Статьи стенда для нагрузочного прогона среза 005 (NFR-401, NFR-402, NFR-412; PLAN-005, «Скорость»): добавляет статьи до
LOAD_ARTICLES (по умолчанию 5000) — объём базы знаний за несколько лет.

Что делает: заводит рубрики до LOAD_RUBRICS (по умолчанию 60, три уровня; недостающие создаются) и теги до LOAD_TAGS (по
умолчанию 200); добавляет недостающие статьи (повторный запуск добирает до цели): 90 % опубликованы, 10 % черновики; у части
статей по 2-5 версий (для истории и сравнения) и 0-5 комментариев. Тексты собираются из словаря настоящих русских слов
ИТ-тематики, встроенного в скрипт (словарь составлен для нагрузки и не взят из внешних источников). Авторы — сотрудники с
правом `knowledge.edit` (нет таких — любые действующие). Векторы поиска считает служба `vectors.refresh` тем же SQL, что при
сохранении статьи. Работает ТОЛЬКО при E2E_STAND=1 (как e2e_reset_stand); данные убирает следующий сброс приёмки. Каталог tests
в образ не входит, поэтому скрипт подаётся на вход shell:

    docker compose -f deploy/docker-compose.yml --profile dev exec -T -e LOAD_ARTICLES=5000 standtools \
        python manage.py shell --no-imports < backend/tests/load/fill_articles.py

Вывод: `fill_articles: articles=<n> published=<n> drafts=<n> versions=<n> comments=<n>` (числа — всё в базе знаний).
"""
import os
import random
import sys

if os.environ.get("E2E_STAND") != "1":
    sys.exit("Скрипт работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено.")

from datetime import timedelta  # noqa: E402

from django.db import transaction  # noqa: E402
from django.db.models import Count  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.core.models import Comment, User  # noqa: E402
from apps.knowledge.models import Article, ArticleVersion, Rubric, Tag  # noqa: E402
from apps.knowledge.services import render, vectors  # noqa: E402

CHUNK = 250
WORDS = (
    "принтер картридж бумага сканер монитор клавиатура мышь ноутбук компьютер сервер сеть кабель роутер коммутатор "
    "интернет почта письмо вложение пароль логин учётная запись доступ права папка файл документ диск резервная копия "
    "восстановление программа установка обновление лицензия антивирус вирус защита шифрование сертификат подпись токен "
    "телефон гарнитура камера видеосвязь собрание календарь проектор экран розетка питание аккумулятор зарядка "
    "драйвер система настройка параметр профиль пользователь сотрудник отдел заявка обращение инструкция регламент "
    "порядок процедура проверка ошибка сбой отказ перезагрузка зависание медленно быстро память процессор температура "
    "вентилятор шум браузер вкладка закладка расширение страница ссылка форма таблица отчёт база данные запрос "
    "подключение удалённый рабочий стол виртуальная частная сеть адрес маска шлюз имя домен сервис служба очередь "
    "задание расписание журнал событие уведомление сообщение чат канал группа список контакт справочник шаблон "
    "образ накопитель флешка архив пакет скрипт команда терминал консоль каталог раздел строка значение"
).split()
VERBS = ("настроить", "проверить", "заменить", "установить", "обновить", "восстановить", "подключить", "отключить",
         "перезапустить", "очистить")
PHRASES = ("Если проблема повторяется, обратитесь в ИТ-отдел.", "Перед началом сохраните открытые документы.",
           "Действие занимает несколько минут.", "Проверьте результат и закройте заявку.",
           "Порядок действий описан ниже.")


def sentence(rng: random.Random, low: int = 6, high: int = 12) -> str:
    words = [rng.choice(WORDS) for _ in range(rng.randint(low, high))]
    return f"{rng.choice(VERBS).capitalize()} {' '.join(words)}."


def make_text(rng: random.Random, paragraphs: int) -> str:
    parts = [f"## {rng.choice(WORDS).capitalize()} {rng.choice(WORDS)}"]
    for _ in range(paragraphs):
        parts.append(" ".join(sentence(rng) for _ in range(rng.randint(2, 4))) + " " + rng.choice(PHRASES))
    parts.append("- " + "\n- ".join(sentence(rng, 3, 6) for _ in range(rng.randint(2, 4))))
    return "\n\n".join(parts)


def make_tags(count: int, rng: random.Random) -> list:
    """Теги до `count`: слова словаря, затем пары `слово-слово`; недостающие создаются."""
    names = list(dict.fromkeys(WORDS))
    pairs = [f"{a}-{b}" for a in names[:40] for b in names[40:80]]
    rng.shuffle(pairs)
    names = (names + pairs)[:count]
    have = set(Tag.objects.filter(name__in=names).values_list("name", flat=True))
    Tag.objects.bulk_create([Tag(name=name) for name in names if name not in have], ignore_conflicts=True)
    return list(Tag.objects.filter(name__in=names).order_by("pk"))


def make_rubrics(count: int, rng: random.Random) -> list:
    """Рубрики трёх уровней вместе с «Общее»; названия — слова словаря с номером, недостающие создаются."""
    default = Rubric.objects.get(is_default=True)
    result = [default]
    roots = max(3, count // 12)
    for n in range(1, roots + 1):
        result.append(Rubric.objects.get_or_create(name=f"{rng.choice(WORDS).capitalize()} {n}", parent=None,
                                                   defaults={"depth": 1})[0])
    level1 = result[1:]
    second = []
    for n in range(1, (count - len(result)) // 2 + 1):
        parent = level1[n % len(level1)]
        second.append(Rubric.objects.get_or_create(name=f"{rng.choice(WORDS).capitalize()} {n}", parent=parent,
                                                   defaults={"depth": 2})[0])
    result += second
    n = 0
    while second and len(result) < count:
        n += 1
        parent = second[n % len(second)]
        result.append(Rubric.objects.get_or_create(name=f"{rng.choice(WORDS).capitalize()} {n}", parent=parent,
                                                   defaults={"depth": 3})[0])
    return result


def make_authors() -> list:
    authors = list(User.objects.filter(state="active", roles__permissions__code="knowledge.edit").distinct()
                   .order_by("pk")[:50])
    return authors or list(User.objects.filter(state="active").order_by("pk")[:50])


def fill(target: int, rubrics: list, tags: list, authors: list, rng: random.Random) -> None:
    now = timezone.now()
    missing = target - Article.objects.count()
    while missing > 0:
        size = min(CHUNK, missing)
        with transaction.atomic():
            articles, plan = [], []
            for _ in range(size):
                author = rng.choice(authors)
                created = now - timedelta(days=rng.randint(0, 1095), minutes=rng.randint(0, 1439))
                published = rng.random() < 0.9
                count = rng.choice((1, 1, 1, 2, 3, 4, 5)) if rng.random() < 0.3 else 1
                texts = [make_text(rng, rng.randint(2, 5) + step) for step in range(count)]
                title = f"{rng.choice(WORDS).capitalize()} {rng.choice(WORDS)} {rng.choice(WORDS)}"
                rendered = [render.render(text, {}, None) for text in texts]
                rubric = rng.choice(rubrics)
                updated = created + timedelta(hours=count)
                articles.append(Article(
                    title=title, text=texts[-1], html=rendered[-1].html, plain=rendered[-1].plain, rubric=rubric,
                    state="published" if published else "draft", author=author, created_at=created,
                    updated_by=author, updated_at=updated, version_no=count,
                    published_at=created if published else None))
                plan.append((author, created, texts, rendered, rubric, rng.sample(tags, rng.randint(0, 4)),
                             rng.randint(0, 5) if published else 0))
            Article.objects.bulk_create(articles)
            through = Article.tags.through
            versions, links, comments = [], [], []
            for article, (author, created, texts, rendered, rubric, picked, notes) in zip(articles, plan):
                links += [through(article_id=article.pk, tag_id=tag.pk) for tag in picked]
                names = sorted(tag.name for tag in picked)
                versions += [ArticleVersion(
                    article=article, number=number, author=author, created_at=created + timedelta(hours=number - 1),
                    comment="", title=article.title, text=text, html=rendered[number - 1].html, rubric=rubric,
                    rubric_name=rubric.name, tags=names) for number, text in enumerate(texts, 1)]
                comments += [Comment(object_ref=f"knowledge.article:{article.pk}", author=rng.choice(authors),
                                     text=sentence(rng), created_at=created + timedelta(days=1, minutes=n))
                             for n in range(notes)]
            through.objects.bulk_create(links)
            ArticleVersion.objects.bulk_create(versions)
            Comment.objects.bulk_create(comments)
            vectors.refresh([article.pk for article in articles])
        missing -= size


rng = random.Random(20260505)
authors = make_authors()
if not authors:
    sys.exit("Нет действующих сотрудников: сначала подготовьте учётные записи; ничего не изменено.")
tags = make_tags(int(os.environ.get("LOAD_TAGS", "200")), rng)
rubrics = make_rubrics(int(os.environ.get("LOAD_RUBRICS", "60")), rng)
fill(int(os.environ.get("LOAD_ARTICLES", "5000")), rubrics, tags, authors, rng)
states = dict(Article.objects.values_list("state").annotate(n=Count("pk")))
print(f"fill_articles: articles={Article.objects.count()} published={states.get('published', 0)} "
      f"drafts={states.get('draft', 0)} versions={ArticleVersion.objects.count()} "
      f"comments={Comment.objects.filter(object_ref__startswith='knowledge.article:').count()}")
