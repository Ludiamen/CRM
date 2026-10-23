"""История статьи: восстановление, удаление версии, сравнение (PLAN-005, «История, сравнение, восстановление,
удаление версии»; FR-411, FR-412, FR-414, FR-449).

Версия не правится: у неё нет функции изменения. Сравнение живёт здесь же (модуля `diff` в перечне плана нет).
"""
from bisect import bisect_left
from collections import Counter
from difflib import SequenceMatcher
from typing import NamedTuple

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404

from apps.core.services import audit

from ..models import Article, ArticleVersion, Rubric
from . import VersionError, access, articles, pdn

DIFF_LIMIT = 2000
# Предел изменённой части для подробного построчного сравнения (проверка безопасности 2026-10-23, CONTRACT-005 п. 80):
# время SequenceMatcher растёт квадратично; худший случай 2 000 строк — около 0,5 с, 10 000 — 11 с, 50 000 — минуты.
MAX_DIFF_LINES = 2000


class FieldDiff(NamedTuple):
    """Изменившееся поле: `name` — `title`, `rubric` или `tags`."""

    name: str
    before: str
    after: str


class DiffLine(NamedTuple):
    """Строка текста: `kind` — `same`, `add` или `del`."""

    kind: str
    text: str


class Comparison(NamedTuple):
    """Сравнение двух версий: `new > old`; `more` — сколько изменённых строк сверх 2 000 не показано."""

    old: int
    new: int
    fields: list
    lines: list
    more: int


def _opcodes(before: list, after: list) -> list:
    """Опкоды построчного сравнения в виде `SequenceMatcher.get_opcodes()`.

    Общее начало и общий конец отбрасываются заранее (обычная правка меняет середину). Середина не длиннее
    `MAX_DIFF_LINES` сравнивается `SequenceMatcher`; длиннее — выравнивается по опорным строкам, которые встречаются ровно
    один раз в каждой версии (наибольшая возрастающая цепочка их позиций, как в patience diff), и `SequenceMatcher`
    сравнивает только промежутки между опорами. Промежуток длиннее предела с обеих сторон — одна замена: сравнение там
    грубее, но верное и быстрое; показ FR-411 «первые 2 000 и Ещё N» тот же."""
    head = 0
    limit = min(len(before), len(after))
    while head < limit and before[head] == after[head]:
        head += 1
    tail = 0
    while tail < limit - head and before[-1 - tail] == after[-1 - tail]:
        tail += 1
    result = [("equal", 0, head, 0, head)] if head else []
    middle = before[head:len(before) - tail], after[head:len(after) - tail]
    if max(len(middle[0]), len(middle[1])) <= MAX_DIFF_LINES:
        result += _gap(*middle, head, head)
    else:
        result += _anchored(*middle, head, head)
    if tail:
        result.append(("equal", len(before) - tail, len(before), len(after) - tail, len(after)))
    return _merged(result)


def _gap(before: list, after: list, i: int, j: int) -> list:
    """Опкоды одного промежутка (сдвинуты на `i`, `j`): вставка, удаление, подробное сравнение или одна замена."""
    if not before and not after:
        return []
    if not before:
        return [("insert", i, i, j, j + len(after))]
    if not after:
        return [("delete", i, i + len(before), j, j)]
    if max(len(before), len(after)) > MAX_DIFF_LINES:
        return [("replace", i, i + len(before), j, j + len(after))]
    return [(tag, i1 + i, i2 + i, j1 + j, j2 + j)
            for tag, i1, i2, j1, j2 in SequenceMatcher(None, before, after, autojunk=True).get_opcodes()]


def _anchored(before: list, after: list, i: int, j: int) -> list:
    """Выравнивание по уникальным в обеих версиях строкам: O(n log n), промежутки между опорами — `_gap`."""
    seen_before, seen_after = Counter(before), Counter(after)
    where_after = {line: k for k, line in enumerate(after) if seen_after[line] == 1}
    pairs = [(k, where_after[line]) for k, line in enumerate(before) if seen_before[line] == 1 and line in where_after]
    tails, tail_at, back = [], [], [-1] * len(pairs)
    for n, (_, b) in enumerate(pairs):
        place = bisect_left(tails, b)
        if place:
            back[n] = tail_at[place - 1]
        if place == len(tails):
            tails.append(b)
            tail_at.append(n)
        else:
            tails[place], tail_at[place] = b, n
    chain, n = [], tail_at[-1] if tail_at else -1
    while n >= 0:
        chain.append(pairs[n])
        n = back[n]
    chain.reverse()
    result, prev_a, prev_b = [], 0, 0
    for a, b in chain + [(len(before), len(after))]:
        result += _gap(before[prev_a:a], after[prev_b:b], i + prev_a, j + prev_b)
        if a < len(before):
            result.append(("equal", i + a, i + a + 1, j + b, j + b + 1))
        prev_a, prev_b = a + 1, b + 1
    return result


def _merged(opcodes: list) -> list:
    """Соседние опкоды `equal` склеиваются в один (как у `SequenceMatcher`)."""
    merged: list = []
    for code in opcodes:
        if merged and code[0] == "equal" and merged[-1][0] == "equal" and merged[-1][2] == code[1]:
            merged[-1] = ("equal", merged[-1][1], code[2], merged[-1][3], code[4])
        else:
            merged.append(code)
    return merged


def restore(user, article_id: int, number: int, confirm_pdn: bool = False) -> articles.SaveResult:
    """Восстанавливает версию как новое сохранение (шаги 1, 2, 5–7); комментарий «Восстановлено из версии N»."""
    with transaction.atomic():
        article = articles.lock_article(user, article_id)
        version = ArticleVersion.objects.filter(article=article, number=number).first()
        if version is None:
            raise Http404("Версии нет")
        # рубрика версии удалена (пусто) — статья остаётся в текущей рубрике (FR-412)
        rubric = None
        if version.rubric_id is not None:
            rubric = Rubric.objects.select_for_update().filter(pk=version.rubric_id).first()
        if rubric is None:
            rubric = Rubric.objects.select_for_update().get(pk=article.rubric_id)
        tag_names = list(version.tags)
        if articles.same_as_current(article, version.title, version.text, rubric.pk, tag_names):
            return articles.SaveResult("no_changes", article, None, [])
        if article.state == Article.State.PUBLISHED and not confirm_pdn:
            found = pdn.find(version.title, version.text)
            if found:
                return articles.SaveResult("pdn_warning", article, None, found)
        new_version = articles.write_edit(
            article, user, title=version.title, text=version.text, rubric=rubric, tag_names=tag_names,
            comment=f"Восстановлено из версии {number}")
    return articles.SaveResult("saved", article, new_version, [])


def delete(user, article_id: int, number: int) -> None:
    """Удаляет версию (управляющий); текущую удалить нельзя; журнал `knowledge.version_deleted`."""
    with transaction.atomic():
        article = Article.objects.select_for_update().filter(pk=article_id).first()
        if article is None:
            raise Http404("Статьи нет")
        if article.state == Article.State.TRASH:
            raise access.ArticleGone
        if not access.can_manage(user):
            raise PermissionDenied
        version = ArticleVersion.objects.filter(article=article, number=number).first()
        if version is None:
            raise Http404("Версии нет")
        if number == article.version_no:
            raise VersionError("current_version")
        version.delete()
        audit.record("knowledge.version_deleted", actor=user, object_type=articles.OBJECT_TYPE,
                     object_id=article.pk, before={"number": article.pk, "title": article.title, "version": number})


def compare(article: Article, a: int, b: int) -> Comparison:
    """Сравнивает две версии: старший номер — «стало». Одной из версий нет — `VersionError("deleted")`."""
    numbers = sorted({a, b})
    found = {v.number: v for v in ArticleVersion.objects.filter(article=article, number__in=numbers)}
    if len(found) != len(numbers):
        raise VersionError("deleted")
    old, new = found[numbers[0]], found[numbers[-1]]
    fields = []
    if old.title != new.title:
        fields.append(FieldDiff("title", old.title, new.title))
    if old.rubric_name != new.rubric_name:
        fields.append(FieldDiff("rubric", old.rubric_name, new.rubric_name))
    old_tags, new_tags = sorted(old.tags), sorted(new.tags)
    if old_tags != new_tags:
        fields.append(FieldDiff("tags", ", ".join(old_tags), ", ".join(new_tags)))
    before_lines, after_lines = old.text.split("\n"), new.text.split("\n")
    opcodes = _opcodes(before_lines, after_lines)
    lines: list[DiffLine] = []
    shown = more = 0
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            if more == 0:
                lines.extend(DiffLine("same", text) for text in after_lines[j1:j2])
            continue
        changes = [DiffLine("del", text) for text in before_lines[i1:i2]] \
            + [DiffLine("add", text) for text in after_lines[j1:j2]]
        room = max(DIFF_LIMIT - shown, 0)
        lines.extend(changes[:room])
        shown += min(room, len(changes))
        more += max(len(changes) - room, 0)
    return Comparison(old.number, new.number, fields, lines, more)
