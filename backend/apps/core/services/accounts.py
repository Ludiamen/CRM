"""Учётные записи (T-221, FR-001…008, FR-010, FR-019, FR-024, FR-044).

Удаления записей нет: ни в сервисах, ни в маршрутах (FR-005). Профиль правит
администратор; сотрудник — только свой телефон и контакты (FR-006). Записи заводит
только администратор (FR-007), саморегистрации нет.
"""
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.models import BackupCodeDevice, EncryptedTOTPDevice, Role, User, UserState
from apps.integrations.mail import services as mail

from . import audit, backup_codes, links, lockout, roles, sessions, totp

SORTABLE = {"full_name", "email", "position", "state", "created_at", "activated_at"}
PROFILE_FIELDS = ("full_name", "position", "phone", "email", "contacts")


class AccountError(Exception):
    """Нарушено правило учётных записей; текст — для человека."""


def parse_contacts(value) -> list[str]:
    """Контакты: по строке на контакт (из формы) или готовый список."""
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = str(value or "").splitlines()
    return [str(item).strip() for item in items if str(item).strip()]


def _clean_email(email: str, *, exclude: User | None = None) -> str:
    email = (email or "").strip()
    try:
        validate_email(email)
    except ValidationError:
        raise AccountError("Укажите рабочую почту в виде имя@домен.") from None
    clash = User.objects.filter(email__iexact=email)
    if exclude is not None:
        clash = clash.exclude(pk=exclude.pk)
    if clash.exists():
        raise AccountError("Запись с такой почтой уже есть.")
    return email


def _snapshot(user: User) -> dict:
    return {"email": user.email, "full_name": user.full_name, "position": user.position, "phone": user.phone,
            "contacts": list(user.contacts or [])}


def list_staff(*, state: str | None = None, role_id=None, query: str | None = None, sort: str | None = None):
    """Список для `/staff/`: фильтры по состоянию и роли, поиск по ФИО и почте, сортировка из белого списка."""
    qs = User.objects.all().prefetch_related("roles")
    if state in {s.value for s in UserState}:
        qs = qs.filter(state=state)
    if role_id not in (None, ""):
        try:
            qs = qs.filter(roles__pk=int(role_id))
        except (TypeError, ValueError):
            qs = qs.none()
    if query and query.strip():
        needle = query.strip()
        qs = qs.filter(Q(full_name__icontains=needle) | Q(email__icontains=needle))
    order = sort or "full_name"
    if order.lstrip("-") not in SORTABLE:
        order = "full_name"
    return qs.distinct().order_by(order, "pk")


def create_user(*, email: str, full_name: str, position: str, phone: str = "", contacts=None, role_ids=(),
                actor, ip=None, invite: bool = True) -> User:
    """Заводит приглашённую запись; ссылка активации на 72 часа и письмо (FR-001, FR-008)."""
    email = _clean_email(email)
    full_name, position = (full_name or "").strip(), (position or "").strip()
    if not full_name:
        raise AccountError("Укажите ФИО.")
    if not position:
        raise AccountError("Укажите должность.")
    selected = list(Role.objects.filter(pk__in=list(role_ids)))
    if not selected:
        raise AccountError("Выберите хотя бы одну роль.")
    try:
        with transaction.atomic():
            user = User(email=email, full_name=full_name, position=position, phone=(phone or "").strip(),
                        contacts=parse_contacts(contacts), state=UserState.INVITED)
            user.set_unusable_password()
            user.save()
            user.roles.set(selected)
            audit.record("user.created", actor=actor, object_type="user", object_id=user.pk,
                         after={**_snapshot(user), "state": user.state, "roles": sorted(r.name for r in selected)}, ip=ip)
            if invite:
                links.send_invitation(user, created_by=actor, ip=ip)
    except IntegrityError:
        raise AccountError("Запись с такой почтой уже есть.") from None
    return user


def create_first_admin(email: str, full_name: str = "") -> tuple[User, str]:
    """Первый администратор (команда `create_first_admin`): ссылка активации печатается, письма нет."""
    email = _clean_email(email)
    admin_role = roles.admin_role()
    if admin_role is None:
        raise AccountError("Нет начальной роли администратора: примените миграции.")
    with transaction.atomic():
        if User.objects.exists():
            raise AccountError("В базе уже есть учётные записи: первого администратора создают только в пустой базе.")
        user = User(email=email, full_name=(full_name or "").strip() or "Администратор портала",
                    position="Администратор портала", state=UserState.INVITED)
        user.set_unusable_password()
        user.save()
        user.roles.set([admin_role])
        link, code = links.issue(user, "activation")
        audit.record("user.created", actor=None, object_type="user", object_id=user.pk,
                     after={**_snapshot(user), "state": user.state, "roles": [admin_role.name]})
    return user, code


def update_profile(user: User, *, actor, ip=None, **fields) -> User:
    """Правка профиля администратором: ФИО, должность, телефон, почта, контакты (FR-005)."""
    unknown = set(fields) - set(PROFILE_FIELDS)
    if unknown:
        raise AccountError("Это поле профиля менять нельзя: " + ", ".join(sorted(unknown)) + ".")
    new = {}
    for name, value in fields.items():
        if name == "contacts":
            new[name] = parse_contacts(value)
        elif name == "email":
            new[name] = _clean_email(value, exclude=user)
        else:
            new[name] = (value or "").strip()
    if not new.get("full_name", user.full_name) or not new.get("position", user.position):
        raise AccountError("ФИО и должность не могут быть пустыми.")
    with transaction.atomic():
        before_all = _snapshot(user)
        for name, value in new.items():
            setattr(user, name, value)
        user.save()
        after_all = _snapshot(user)
        changed = [name for name in new if before_all[name] != after_all[name]]
        if changed:
            audit.record("user.updated", actor=actor, object_type="user", object_id=user.pk,
                         before={n: before_all[n] for n in changed}, after={n: after_all[n] for n in changed}, ip=ip)
    return user


def update_own_contacts(user: User, *, phone: str, contacts, ip=None) -> User:
    """Сотрудник правит только свой телефон и контакты (FR-006)."""
    with transaction.atomic():
        before = {"phone": user.phone, "contacts": list(user.contacts or [])}
        user.phone, user.contacts = (phone or "").strip(), parse_contacts(contacts)
        user.save(update_fields=["phone", "contacts"])
        after = {"phone": user.phone, "contacts": user.contacts}
        if before != after:
            audit.record("user.updated", actor=user, object_type="user", object_id=user.pk, before=before, after=after, ip=ip)
    return user


def block(user: User, reason: str, *, actor, ip=None) -> None:
    """Блокировка: сессии закрываются сразу, ссылки гаснут (FR-005, FR-011, FR-019)."""
    if user.state == UserState.BLOCKED:
        return
    if actor is not None and actor.pk == user.pk:
        raise AccountError("Свою запись заблокировать нельзя.")
    roles.guard_last_admin(user, action="заблокировать его")  # RoleError — вызывающий показывает текст
    reason = (reason or "").strip()
    with transaction.atomic():
        previous = user.state
        user.blocked_from, user.state, user.blocked_reason = previous, UserState.BLOCKED, reason
        user.save(update_fields=["blocked_from", "state", "blocked_reason"])
        links.revoke(user)
        sessions.close_all(user)
        audit.record("user.blocked", actor=actor, object_type="user", object_id=user.pk,
                     before={"state": previous}, after={"state": UserState.BLOCKED, "reason": reason}, ip=ip)


def unblock(user: User, *, actor, ip=None) -> None:
    """Разблокировка возвращает прежнее состояние: приглашённая запись остаётся приглашённой (нужна новая ссылка)."""
    if user.state != UserState.BLOCKED:
        return
    back = user.blocked_from or (UserState.ACTIVE if user.activated_at else UserState.INVITED)
    with transaction.atomic():
        user.state, user.blocked_from, user.blocked_reason = back, "", ""
        user.save(update_fields=["state", "blocked_from", "blocked_reason"])
        audit.record("user.unblocked", actor=actor, object_type="user", object_id=user.pk,
                     before={"state": UserState.BLOCKED}, after={"state": back}, ip=ip)


def resend_invitation(user: User, *, actor, ip=None):
    """«Отправить приглашение заново»: прежняя ссылка гаснет, уходит новое письмо (FR-010)."""
    if user.state != UserState.INVITED:
        raise AccountError("Приглашение можно отправить только неактивированной записи.")
    with transaction.atomic():
        return links.send_invitation(user, created_by=actor, ip=ip)


def reset_second_factor(user: User, *, actor, ip=None) -> None:
    """Сброс второго фактора (FR-024): ключ и резервные коды гаснут, сессии закрываются, сотруднику — письмо."""
    if actor is not None and actor.pk == user.pk:
        raise AccountError("Свой второй фактор сбросить нельзя: это делает другой администратор.")
    with transaction.atomic():
        devices = EncryptedTOTPDevice.objects.filter(user=user).count()
        EncryptedTOTPDevice.objects.filter(user=user).delete()
        BackupCodeDevice.objects.filter(user=user).delete()  # коды удаляются каскадом
        sessions.close_all(user)
        audit.record("totp.reset", actor=actor, object_type="user", object_id=user.pk,
                     before={"devices": devices}, after={"devices": 0}, ip=ip)
        mail.send("second_factor_reset", user.email, {"full_name": user.full_name}, related_user=user)


def set_profile_in_activation(user: User, *, phone: str, contacts, ip=None) -> None:
    """Шаг «профиль» мастера активации: телефон и контакты; изменение — в журнал, как у профиля (FR-044)."""
    update_own_contacts(user, phone=phone, contacts=contacts, ip=ip)


def complete_activation(user: User, link=None, *, ip=None) -> None:
    """Последний шаг мастера: запись активна, ссылка гаснет (FR-011, FR-013).

    `link=None` — активацию завершают из ограниченной сессии (прервали мастер после пароля):
    действующая ссылка, если она есть, гасится.
    """
    if not totp.has_confirmed(user) or backup_codes.device_of(user) is None:
        raise AccountError("Подключите второй фактор и сохраните резервные коды.")
    if not user.has_usable_password():
        raise AccountError("Сначала задайте пароль.")
    with transaction.atomic():
        user.state, user.activated_at = UserState.ACTIVE, timezone.now()
        user.save(update_fields=["state", "activated_at"])
        if link is not None:
            links.consume(link)
        else:
            links.revoke(user, "activation")
        audit.record("user.activated", actor=user, object_type="user", object_id=user.pk,
                     before={"state": UserState.INVITED}, after={"state": UserState.ACTIVE}, ip=ip)


def unlock_login(user: User, *, actor, ip=None) -> bool:
    """«Снять блокировку входа» записи (FR-038); событие пишется, если блокировка была."""
    removed = lockout.unlock_account(str(user.pk))
    if removed:
        audit.record("account.unlocked", actor=actor, object_type="user", object_id=user.pk, ip=ip)
    return removed


def unlock_ip(address: str, *, actor, ip=None) -> bool:
    removed = lockout.unlock_ip(address)
    if removed:
        audit.record("ip.unlocked", actor=actor, object_type="ip", object_id=address, ip=ip)
    return removed


def lock_overview() -> dict:
    """Для страницы блокировок: заблокированные записи и адреса с оставшимся временем."""
    keys = [key for key in lockout.locked_account_keys() if key.isdigit()]
    by_pk = User.objects.in_bulk([int(key) for key in keys])
    accounts = [(by_pk[int(key)], lockout.lock_ttl("account", key)) for key in keys if int(key) in by_pk]
    ips = [(address, lockout.lock_ttl("ip", address)) for address in lockout.locked_ips()]
    return {"accounts": accounts, "ips": ips}
