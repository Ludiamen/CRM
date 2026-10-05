"""Сброс данных `org` на стенде приёмки (точка расширения `stand_reset`; CONTRACT-002 § 5, дополнение 39).

Возвращает данные модуля к состоянию сразу после миграций (`0002_initial_data`): структура из одного
корня с исходными именем и описанием, без участников и ролей; календарь по умолчанию — одна строка
со значениями модели, без загруженных лет, ручных дней, загрузок календаря и сотрудников.
Фото и их файлы относятся к ядру и стираются командой `e2e_reset_stand`.
"""
from django.db import connections, transaction

from apps.org.models import CalendarUpload, CalendarYear, Membership, SpecialDay, StaffImport, Unit, UnitRole, WorkCalendar
from apps.org.services import calendar

# Исходные значения корня — как в миграции данных `0002_initial_data` (имя модуля начинается с цифры)
ROOT_NAME = "ИТ-отдел"
ROOT_NAME_KEY = "ит-отдел"


def stand_reset() -> None:
    """Стирает данные `org` до исходных; идёт под владельцем схемы (алиас `migrate`), если он настроен."""
    db = "migrate" if "migrate" in connections.databases else "default"
    with transaction.atomic(using=db):
        Membership.objects.using(db).all().delete()
        UnitRole.objects.using(db).all().delete()
        for model in (CalendarYear, SpecialDay, CalendarUpload, StaffImport):
            model.objects.using(db).all().delete()
        units = Unit.objects.using(db)
        # листья вперёд: родитель защищён от удаления, пока есть дети
        for depth in sorted(set(units.filter(is_root=False).values_list("depth", flat=True)), reverse=True):
            units.filter(is_root=False, depth=depth).delete()
        root = units.get(is_root=True)
        root.name, root.name_key, root.description, root.kind = ROOT_NAME, ROOT_NAME_KEY, "", Unit.Kind.DEPARTMENT
        root.save(using=db, update_fields=["name", "name_key", "description", "kind"])
        WorkCalendar.objects.using(db).all().delete()
        WorkCalendar.objects.using(db).create()  # значения по умолчанию заданы в модели
    calendar.bump_version()  # кэш отметок месяца привязан к номеру версии
