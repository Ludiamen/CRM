"""Служба частых ответов (FR-751…754)."""
from django.db import transaction
from django.db.models import Q

from apps.core.services import audit

from ..models import AnswerTemplate
from . import access
from .errors import ServiceDeskError

TITLE_RANGE = "Название шаблона — от 1 до 100 знаков"
TEXT_RANGE = "Текст шаблона — от 1 до 10 000 знаков"
CATEGORY_PERSONAL = "Личный шаблон нельзя привязать к категории"


def _error(code, message):
    raise ServiceDeskError(code, message)


def _clean(values):
    title = str(values.get("title", "") or "").strip()
    text = str(values.get("text", "") or "").strip()
    if not 1 <= len(title) <= 100:
        _error("answer_title_range", TITLE_RANGE)
    if not 1 <= len(text) <= 10000:
        _error("answer_text_range", TEXT_RANGE)
    owner = values.get("owner")
    category = values.get("category")
    if owner is not None and category is not None:
        _error("answer_category_personal", CATEGORY_PERSONAL)
    return {"title": title, "text": text, "owner": owner, "category": category}


def _snapshot(answer):
    return {
        "title": answer.title,
        "text": answer.text,
        "owner": answer.owner.full_name if answer.owner_id else "",
        "category": answer.category.name if answer.category_id else "",
        "archived": answer.archived,
    }


def visible(user, *, include_archived=True):
    """Шаблоны, доступные сотруднику: его личные и общие для участника сервис-деска."""
    if not access.menu_visible(user):
        return AnswerTemplate.objects.none()
    query = Q(owner=user) | Q(owner__isnull=True)
    result = AnswerTemplate.objects.filter(query).select_related("owner", "category")
    if not include_archived:
        result = result.filter(archived=False)
    return result.order_by("archived", "title", "pk")


def get_visible(user, pk, *, active_only=False):
    answers = visible(user, include_archived=not active_only)
    return answers.filter(pk=pk).first()


@transaction.atomic
def create(*, actor=None, ip=None, **values):
    fields = _clean(values)
    answer = AnswerTemplate.objects.create(**fields)
    audit.record("servicedesk.answer_created", actor=actor, ip=ip, object_type="servicedesk",
                 object_id=answer.pk, after=_snapshot(answer))
    return answer


@transaction.atomic
def update(answer, *, actor=None, ip=None, **values):
    answer = AnswerTemplate.objects.select_for_update().get(pk=answer.pk)
    answer = AnswerTemplate.objects.select_related("owner", "category").get(pk=answer.pk)
    current = {"title": answer.title, "text": answer.text, "owner": answer.owner, "category": answer.category}
    fields = _clean({**current, **values})
    before = _snapshot(answer)
    for key, value in fields.items():
        setattr(answer, key, value)
    answer.save(update_fields=["title", "text", "owner", "category", "updated_at"])
    after = _snapshot(answer)
    if before != after:
        audit.record("servicedesk.answer_changed", actor=actor, ip=ip, object_type="servicedesk",
                     object_id=answer.pk, before=before, after=after)
    return answer


@transaction.atomic
def archive(answer, *, actor=None, ip=None):
    answer = AnswerTemplate.objects.select_for_update().get(pk=answer.pk)
    before = {"archived": answer.archived}
    answer.archived = not answer.archived
    answer.save(update_fields=["archived", "updated_at"])
    audit.record("servicedesk.answer_archived", actor=actor, ip=ip, object_type="servicedesk",
                 object_id=answer.pk, before=before, after={"archived": answer.archived})
    return answer


restore = archive
