"""Поле «Создадим чат для всего отдела» точки `unit_form_parts` (срез 008, T-8205).

PLAN-008 «Точки расширения ядра и шина событий», «Виды чатов и создание» (чат отдела); CONTRACT-008 § 3.1–3.2,
3.4, 12.6. Запись рисует галочку `input[name="messenger_chat"]` только для отдела и только пока чата у узла нет;
на создании узла, где узла ещё нет (`unit is None`), и для команды/корня — пустая строка. `on_saved` зовётся после
сохранения узла и при галочке создаёт чат (`department.create`); повторный вызов второй чат не делает.

Запись — экземпляр подкласса `core.extensions.UnitFormPart`, объявленный в этом модуле: `without_messenger` снимает
регистрации по `__module__`, поэтому у подкласса он `apps.messenger.unit_form`, а не ядра.
"""
from dataclasses import dataclass

from django.template.loader import render_to_string

from apps.core import extensions

KEY = "messenger_chat"
ORDER = 10
TEMPLATE = "messenger/_unit_form_field.html"
# Условие обработчика — значение галочки в форме узла (обычная форма отправляет `on`).
CHECKED = "on"


@dataclass(frozen=True)
class ChatUnitFormPart(extensions.UnitFormPart):
    """Запись мессенджера в точке `unit_form_parts`; `__module__` — этот модуль, для `without_messenger`."""


def render(request, unit) -> str:
    """Галочка для отдела без чата; у узла с чатом — «Чат отдела создан» без поля (12.6)."""
    if unit is None or unit.is_root or unit.kind != "department":
        return ""
    from apps.messenger.models import Chat

    created = Chat.objects.filter(kind=Chat.Kind.DEPARTMENT, unit_id=unit.pk).exists()
    return render_to_string(TEMPLATE, {"created": created})


def on_saved(unit, post, actor, ip=None) -> None:
    """После сохранения узла с галочкой создаёт чат отдела (идемпотентно по номеру узла)."""
    if unit is None or unit.is_root or unit.kind != "department" or post.get(KEY) != CHECKED:
        return
    from apps.messenger.services import department

    department.create(unit, actor)


class UnitFormRegistration(ChatUnitFormPart):
    """Регистрация точки: сама запись `UnitFormPart`, вызываемая как функция (для `org` — `.order`/`render`)."""

    @property
    def __name__(self) -> str:
        return "form_parts"

    def __call__(self) -> list:
        return [self]


def unit_form_parts():
    """Регистрация точки `unit_form_parts`: одна запись — чат отдела, порядок 10 (CONTRACT-008, 3.4)."""
    return UnitFormRegistration(key=KEY, order=ORDER, render=render, on_saved=on_saved)
