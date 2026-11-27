"""Проверка и сохранение шаблонов маршрутов (PLAN-014, T-14010)."""
from django.db import transaction

from apps.core.services import audit
from apps.org.models import Unit
from apps.org.services import structure

from ..models import ApprovalStage, ApprovalStageParticipant, ApprovalTemplate
from .errors import ApprovalError

MAX_STAGES = 20
MAX_PARTICIPANTS = 50


def validate(template: ApprovalTemplate) -> None:
    """Проверить шаблон, его этапы и участников; ошибка — `ApprovalError`."""
    name = (template.name or "").strip()
    if not 1 <= len(name) <= 150:
        raise ApprovalError("template_invalid", "Название шаблона — от 1 до 150 знаков")
    if template.subject_type not in ApprovalTemplate.Subject.values:
        raise ApprovalError("template_invalid", "Выберите субъект шаблона")
    if len(template.description or "") > 2000:
        raise ApprovalError("template_invalid", "Описание — не длиннее 2 000 знаков")
    stages = list(template.stages.order_by("order", "pk"))
    if not 1 <= len(stages) <= MAX_STAGES:
        raise ApprovalError("template_invalid", "У шаблона должно быть от 1 до 20 этапов")
    orders = [stage.order for stage in stages]
    if orders != list(range(1, len(stages) + 1)):
        raise ApprovalError("template_invalid", "Порядок этапов — 1…N без пропусков")
    for stage in stages:
        _validate_stage(stage, template)


def _validate_stage(stage: ApprovalStage, template: ApprovalTemplate) -> None:
    title = (stage.title or "").strip()
    if not 1 <= len(title) <= 100:
        raise ApprovalError("template_invalid", "Название этапа — от 1 до 100 знаков")
    if stage.mode not in ApprovalStage.Mode.values:
        raise ApprovalError("template_invalid", "Неизвестный режим этапа")
    if stage.rule not in ApprovalStage.Rule.values:
        raise ApprovalError("template_invalid", "Неизвестное правило этапа")
    if stage.mode == ApprovalStage.Mode.SEQUENTIAL and stage.rule != ApprovalStage.Rule.ALL:
        raise ApprovalError("template_invalid", "Для последовательного этапа доступно только «ждут всех»")
    if stage.deadline_hours is not None and not 1 <= stage.deadline_hours <= 720:
        raise ApprovalError("template_invalid", "Срок этапа — от 1 до 720 часов")
    parts = list(stage.participants.order_by("order", "pk"))
    if not 1 <= len(parts) <= MAX_PARTICIPANTS:
        raise ApprovalError("template_invalid", "У этапа должно быть от 1 до 50 участников")
    seen: set[tuple[str, int]] = set()
    for part in parts:
        key = (part.kind, part.user_id if part.kind == "employee" else part.unit_id)
        if key in seen:
            raise ApprovalError("template_invalid", "Участник повторяется в этапе")
        seen.add(key)
        if part.kind == ApprovalStageParticipant.Kind.EMPLOYEE:
            if part.user is None or part.user.state != "active":
                raise ApprovalError("template_invalid", "Сотрудник уволен, заблокирован или не найден")
        elif part.kind == ApprovalStageParticipant.Kind.UNIT_HEAD:
            if part.unit is None or not Unit.objects.filter(pk=part.unit_id).exists():
                raise ApprovalError("template_invalid", "Подразделение не найдено")
        elif part.kind == ApprovalStageParticipant.Kind.QUEUE_HEAD:
            if template.subject_type != ApprovalTemplate.Subject.TICKET:
                raise ApprovalError("template_invalid", "Руководитель очереди доступен только для заявки")
            if part.unit is not None:
                raise ApprovalError("template_invalid", "Для руководителя очереди подразделение не выбирается")
        else:
            raise ApprovalError("template_invalid", "Неизвестный вид участника")


@transaction.atomic
def save_template(template: ApprovalTemplate, *, actor, stages: list[dict], ip=None) -> ApprovalTemplate:
    """Сохранить шаблон и заменить его этапы; проверка — до записи."""
    created = template._state.adding
    template.full_clean(exclude=["author"])
    for data in stages:
        if data.get("mode") == "sequential" and data.get("rule") != "all":
            raise ApprovalError("template_invalid", "Для последовательного этапа доступно только «ждут всех»")
        if not str(data.get("title") or "").strip():
            raise ApprovalError("template_invalid", "У этапа должно быть название")
        if not data.get("participants"):
            raise ApprovalError("template_invalid", "У этапа должен быть участник")
    template.save()
    template.stages.all().delete()
    for index, data in enumerate(stages, start=1):
        stage = ApprovalStage.objects.create(
            template=template, order=index, title=data["title"], mode=data["mode"],
            rule=data["rule"], deadline_hours=data.get("deadline_hours"))
        for order, part in enumerate(data.get("participants", []), start=1):
            ApprovalStageParticipant.objects.create(
                stage=stage, order=order, kind=part["kind"],
                user_id=part.get("user_id"), unit_id=part.get("unit_id"))
    validate(template)
    audit.record("approvals.template_created" if created else "approvals.template_updated",
                 actor=actor, object_type="approvals.template", object_id=template.pk,
                 after={"name": template.name, "subject_type": template.subject_type,
                        "enabled": template.enabled, "stages": len(stages)}, ip=ip)
    return template


@transaction.atomic
def set_enabled(template: ApprovalTemplate, enabled: bool, *, actor, ip=None) -> ApprovalTemplate:
    template.enabled = enabled
    template.save(update_fields=["enabled", "updated_at"])
    audit.record("approvals.template_enabled" if enabled else "approvals.template_disabled",
                 actor=actor, object_type="approvals.template", object_id=template.pk,
                 after={"enabled": enabled}, ip=ip)
    return template


def resolve_participants(stage: ApprovalStage, subject_type: str, subject) -> dict[int, object]:
    """Разрешить участников этапа на момент запуска: id сотрудника → пользователь."""
    users: dict[int, object] = {}
    for part in stage.participants.order_by("order", "pk"):
        if part.kind == ApprovalStageParticipant.Kind.EMPLOYEE:
            candidates = [part.user]
        elif part.kind == ApprovalStageParticipant.Kind.UNIT_HEAD:
            candidates = structure.unit_heads(part.unit_id) if part.unit_id else []
        else:
            queue_id = getattr(subject, "queue_id", None)
            candidates = structure.heads_of_unit(queue_id) if queue_id else []
        for user in candidates:
            if user is not None and getattr(user, "state", "") == "active":
                users.setdefault(user.pk, user)
    return users
