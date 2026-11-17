"""Состав и права участия: `members`, `is_member`, `can_write`, `visible_chats`, `get_chat` (срез 008, T-8202).

CONTRACT-008 § 5.1, 6 (места V1–V13); PLAN-008, «Состав чата», «Права и неприкосновенность». Одна функция состава
`members(chat)` и одна точка решения о доступе `get_chat(user, chat_id)`: невидимый, несуществующий и удалённый чат
отвечают одинаковым `Http404` без подробностей (FR-669). Состав чата отдела и «Общего чата» считается на момент
просмотра, строк `ChatMember` у них нет. Модели `org`, `notify` и `feed` не импортируются: подразделения — публичные
функции `org.services.structure` под `apps.is_installed("apps.org")`, номер узла в чате — число.
"""
from django.apps import apps
from django.db.models import Q
from django.http import Http404

from apps.core.models import User, UserState
from apps.messenger.models import Chat, ChatMember

# «Действующий» в плане — состояние не `dismissed` и не `invited`; заблокированный в состав входит (FR-660).
MEMBER_STATES = (UserState.ACTIVE, UserState.BLOCKED)
# Кому чаты не показываются: уволенному портал закрыт, приглашённый ещё не сотрудник.
HIDDEN_STATES = (UserState.DISMISSED, UserState.INVITED)
# уволенный не входит ни в один состав (FR-643, 650).
DISMISSED = UserState.DISMISSED

_ACTIVE_KINDS = (Chat.Kind.PERSONAL, Chat.Kind.GROUP)


def _user_id(user) -> int | None:
    return getattr(user, "pk", None)


def _dismissed(user) -> bool:
    return getattr(user, "state", None) == DISMISSED


def _unit_chain(user) -> frozenset[int]:
    """Цепочка узлов сотрудника для видимости чатов отдела; без `apps.org` — пусто (как у ленты)."""
    if not apps.is_installed("apps.org"):
        return frozenset()

    from apps.org.services import structure

    return structure.unit_chain_ids(user)


def members(chat) -> frozenset[int]:
    """Состав чата: личный и групповой — строки `ChatMember` без выхода, отдел — поддерево узла, общий — действующие.

    Единственная функция состава (FR-650). Заблокированные входят (история и «Прочитали N из M»), уволенные — нет.
    У чата отдела и «Общего чата» строк участников нет: состав считается на момент просмотра.
    """
    kind = chat.kind
    if kind in _ACTIVE_KINDS:
        rows = (ChatMember.objects
                .filter(chat=chat, left_at__isnull=True)
                .exclude(user__state=DISMISSED)
                .values_list("user_id", flat=True))
        return frozenset(rows)
    if kind == Chat.Kind.DEPARTMENT:
        if not apps.is_installed("apps.org") or chat.unit_id is None:
            return frozenset()

        from apps.org.services import structure

        # `subtree_member_ids` отсеивает уволенных сам (CONTRACT-008, 4.1).
        return frozenset(structure.subtree_member_ids([chat.unit_id]))
    if kind == Chat.Kind.GENERAL:
        # Один запрос: заблокированные входят, приглашённые и уволенные — нет.
        return frozenset(User.objects.filter(state__in=MEMBER_STATES).values_list("pk", flat=True))
    return frozenset()


def is_member(user, chat) -> bool:
    """Участие по тому же правилу, что `members(chat)`; уволенный не участник."""
    user_id = _user_id(user)
    if user_id is None or _dismissed(user):
        return False
    kind = chat.kind
    if kind in _ACTIVE_KINDS:
        return (ChatMember.objects
                .filter(chat=chat, user_id=user_id, left_at__isnull=True)
                .exclude(user__state=DISMISSED)
                .exists())
    if kind == Chat.Kind.DEPARTMENT:
        # Сотрудник узла или вложенного узла видит чат отдела: цепочка содержит номер его узла, и он же входит
        # в поддерево. Сотрудник родительского узла в поддерево не входит и в цепочке этого узла не имеет.
        return chat.unit_id is not None and chat.unit_id in _unit_chain(user)
    if kind == Chat.Kind.GENERAL:
        return getattr(user, "state", None) in MEMBER_STATES
    return False


def can_write(user, chat) -> bool:
    """Писать может участник в действующем состоянии; выключенный «Общий чат» и диалог с уволенным — нет."""
    state = getattr(user, "state", None)
    if state not in MEMBER_STATES:
        return False
    if chat.kind == Chat.Kind.GENERAL and not _general_enabled():
        return False
    if not is_member(user, chat):
        return False
    if chat.kind == Chat.Kind.PERSONAL:
        # Существующий диалог с уволенным остаётся видимым и читаемым, но отправка блокируется (FR-645).
        return not (ChatMember.objects
                    .filter(chat=chat, left_at__isnull=True, user__state=DISMISSED)
                    .exists())
    return True


def visible_chats(user):
    """Видимые чаты: свои личный и групповой, чаты отдела по цепочке узлов, «Общий чат» — только включённый.

    Возвращает набор `Chat` (ленивый запрос); уволенному и приглашённому — пусто.
    """
    user_id = _user_id(user)
    if user_id is None or getattr(user, "state", None) in HIDDEN_STATES:
        return Chat.objects.none()

    condition = Q(kind__in=_ACTIVE_KINDS, members__user_id=user_id, members__left_at__isnull=True)
    chain = _unit_chain(user)
    if chain:
        condition |= Q(kind=Chat.Kind.DEPARTMENT, unit_id__in=chain)
    if _general_enabled():
        condition |= Q(kind=Chat.Kind.GENERAL)
    return Chat.objects.filter(condition).distinct()


def get_chat(user, chat_id: int) -> Chat:
    """Единственная точка решения о доступе: невидимый, несуществующий и удалённый чат — один и тот же `Http404`."""
    try:
        return visible_chats(user).get(pk=chat_id)
    except Chat.DoesNotExist as exc:
        raise Http404 from exc


def _general_enabled() -> bool:
    from apps.messenger.services import messenger_settings

    return bool(messenger_settings.get().general_chat_enabled)