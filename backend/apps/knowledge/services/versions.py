"""История статьи: восстановление, удаление версии, сравнение (PLAN-005, «История, сравнение, восстановление,
удаление версии»; FR-411, FR-412, FR-414, FR-449).

Версия не правится: у неё нет функции изменения. Сравнение живёт здесь же (модуля `diff` в перечне плана нет).
"""
from difflib import SequenceMatcher
from typing import NamedTuple

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404

from apps.core.services import audit

from ..models import Article, ArticleVersion, Rubric
from . import VersionError, access, articles, pdn

DIFF_LIMIT = 2000


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
    lines: list[DiffLine] = []
    shown = more = 0
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, before_lines, after_lines, autojunk=True).get_opcodes():
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
