"""Общие помощники серверных тестов среза 010 «Поручения» (T-10005; CONTRACT-010, 5.4).

Код среза (`apps.instructions`) на уровне модуля не импортируется: сбор тестов проходит до появления кода, а
падения видны поимённо при вызове. Модели берутся лениво через `support.model(...)`; службы — внутри функций.
Пароли и секреты — только из `tests.factories`; настоящих ПДн в помощниках нет.
"""
import contextlib
import datetime
from html.parser import HTMLParser

from django.db import connection
from django.test.utils import CaptureQueriesContext

from tests import support, support_org

PERMISSIONS_010 = ("instructions.use", "instructions.assign")

PAGE_PATHS = (
    "/instructions/",
    "/instructions/new/",
    "/instructions/discipline/",
    "/settings/instructions/",
    "/settings/instructions/basis/",
)


# --- люди и роли ---------------------------------------------------------------------------------

def staff_user(**extra):
    """Сотрудник с встроенной ролью «Сотрудник ИТ» (у неё `instructions.use` и `instructions.assign`)."""
    return support.make_employee(roles=[support.role_by_name(support.STAFF_ROLE)], **extra)


def viewer(**extra):
    """Сотрудник с правами `instructions.use` и `instructions.assign` через свою роль."""
    return support.make_with_permissions(*PERMISSIONS_010, **extra)


def head_of(unit, **extra):
    """Сотрудник — руководитель узла `unit` (членство с `mark="head"`)."""
    user = staff_user(**extra)
    support_org.make_member(user, unit, mark="head")
    return user


def deputy_of(unit, **extra):
    """Сотрудник — заместитель узла `unit` (членство с `mark="deputy"`)."""
    user = staff_user(**extra)
    support_org.make_member(user, unit, mark="deputy")
    return user


def _today():
    from apps.core.widgets import moscow_today

    return moscow_today()


# --- поручения и справочники ---------------------------------------------------------------------

def make_basis(title="Приказ", position=0, active=True):
    """Строка `InstructionBasisKind`; повторное название получает суффикс, уникальность модели не ломается."""
    Kind = support.model("instructions.InstructionBasisKind")
    candidate, counter = title, 1
    while Kind.objects.filter(title=candidate).exists():
        counter += 1
        candidate = f"{title} {counter}"
    return Kind.objects.create(title=candidate, position=position, active=active)


def make_basis_kinds():
    """Четыре вида основания данных установки (как `instructions 0002`)."""
    return [make_basis(title, position=index)
            for index, title in enumerate(("Приказ", "Протокол совещания", "Письмо", "Устное указание"))]


def make_instruction(title="Поручение", *, author=None, controller=None, assignee=None, basis=None,
                     basis_number="12", basis_date=None, deadline=None, text="", members=(), ladder=None,
                     **extra):
    """Поручение через ORM; по умолчанию автор = контролёр = исполнитель = свежий `staff_user`."""
    Instruction = support.model("instructions.Instruction")
    author = author or staff_user()
    assignee = assignee or author
    controller = controller or author
    basis = basis or make_basis()
    deadline = deadline or (_today() + datetime.timedelta(days=30))
    return Instruction.objects.create(
        title=title, text=text, basis_kind=basis, basis_number=basis_number,
        basis_date=basis_date or _today(), author=author, controller=controller, assignee=assignee,
        deadline=deadline, original_deadline=deadline, ladder={} if ladder is None else ladder, **extra)


def add_coexecutor(instruction, user):
    """Строка `InstructionMember` с ролью `coexecutor`."""
    return support.model("instructions.InstructionMember").objects.create(
        instruction=instruction, user=user, role="coexecutor")


def add_report_date(instruction, due_date, position=0, state="waiting"):
    """Строка `InstructionReportDate` (даты в одном поручении уникальны)."""
    return support.model("instructions.InstructionReportDate").objects.create(
        instruction=instruction, due_date=due_date, position=position, state=state)


# --- запросы -------------------------------------------------------------------------------------

def submit_report(client, instruction, *, date=None, text="Отчёт", files=(), **extra):
    """`POST /instructions/<id>/reports/`; `date` — номер отчётной даты (пусто — к сроку)."""
    data = {"text": text, "files": list(files)}
    if date is not None:
        data["date"] = getattr(date, "pk", date)
    return client.post(f"/instructions/{instruction.pk}/reports/", data, **extra)


def add_part(client, instruction, report_date, *, text="Часть", files=(), **extra):
    """`POST /instructions/<id>/parts/` для отчётной даты."""
    return client.post(f"/instructions/{instruction.pk}/parts/",
                       {"date": getattr(report_date, "pk", report_date), "text": text, "files": list(files)},
                       **extra)


def accept_report(client, report, *, comment="", **extra):
    """`POST /instructions/reports/<id>/accept/`."""
    return client.post(f"/instructions/reports/{report.pk}/accept/", {"comment": comment}, **extra)


def return_report(client, report, *, comment="Доработать", **extra):
    """`POST /instructions/reports/<id>/return/` с причиной возврата."""
    return client.post(f"/instructions/reports/{report.pk}/return/", {"comment": comment}, **extra)


def request_transfer(client, instruction, *, new_deadline, reason="Причина", **extra):
    """`POST /instructions/<id>/transfers/`."""
    return client.post(f"/instructions/{instruction.pk}/transfers/",
                       {"new_deadline": new_deadline, "reason": reason}, **extra)


def decide_transfer(client, transfer, *, approve=True, comment="", **extra):
    """`POST /instructions/transfers/<id>/approve/` или `…/reject/`."""
    action = "approve" if approve else "reject"
    return client.post(f"/instructions/transfers/{transfer.pk}/{action}/", {"comment": comment}, **extra)


def post_ladder(client, instruction, *, offsets=(), due=True, overdue=True, **extra):
    """`POST /instructions/<id>/ladder/` с порогами в рабочих днях."""
    return client.post(f"/instructions/{instruction.pk}/ladder/",
                       {"offsets": list(offsets), "due": "1" if due else "", "overdue": "1" if overdue else ""},
                       **extra)


def reminders_of(instruction):
    """Напоминания поручения по возрастанию момента, затем номера."""
    return list(support.model("instructions.InstructionReminder").objects
                .filter(instruction=instruction).order_by("moment", "pk"))


# --- разбор разметки -----------------------------------------------------------------------------

class _RegistryParser(HTMLParser):
    """Собирает строки реестра: `[data-instruction-id]` и `[data-instruction-state]` внутри строки."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-instruction-id" in attrs:
            state = attrs.get("data-instruction-state", "")
            self.rows.append({"id": int(attrs["data-instruction-id"]), "state": state,
                              "title": attrs.get("data-instruction-title", "")})


def registry_rows(response_or_html):
    """Разбор реестра: список `{"id", "state", "title"}` в порядке документа."""
    html = getattr(response_or_html, "content", response_or_html)
    if isinstance(html, bytes):
        html = html.decode()
    parser = _RegistryParser()
    parser.feed(html)
    return parser.rows


class _DisciplineParser(HTMLParser):
    """Собирает строки `[data-discipline-row]` с числами из `data-*`."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-discipline-row" in attrs:
            self.rows.append({
                "unit": attrs.get("data-unit", ""),
                "person": attrs.get("data-person", ""),
                "in_time": int(attrs.get("data-in-time", 0) or 0),
                "with_transfer": int(attrs.get("data-with-transfer", 0) or 0),
                "overdue": int(attrs.get("data-overdue", 0) or 0),
            })


def discipline_rows(response_or_html):
    """Разбор отчёта дисциплины: список `{"unit", "person", "in_time", "with_transfer", "overdue"}`."""
    html = getattr(response_or_html, "content", response_or_html)
    if isinstance(html, bytes):
        html = html.decode()
    parser = _DisciplineParser()
    parser.feed(html)
    return parser.rows


# --- SQL и синтетические контакты ----------------------------------------------------------------

def capture_sql(call):
    """SQL вызова списком (как `support_tasks`/`support_feed`)."""
    with CaptureQueriesContext(connection) as ctx:
        call()
    return [query["sql"] for query in ctx.captured_queries]


def _pairs(call):
    pairs = []

    def wrapper(execute, sql, params, many, context):
        pairs.append((sql if isinstance(sql, str) else str(sql), params))
        return execute(sql, params, many, context)

    with connection.execute_wrapper(wrapper):
        call()
    return pairs


@contextlib.contextmanager
def _queries_ctx():
    holder = {}

    def wrapper(execute, sql, params, many, context):
        holder.setdefault("pairs", []).append((sql if isinstance(sql, str) else str(sql), params))
        return execute(sql, params, many, context)

    with connection.execute_wrapper(wrapper):
        yield holder.setdefault("pairs", [])


def queries_with_params(call=None):
    """SQL вызова с параметрами: список пар или контекст, если `call` не передан (NFR-721)."""
    return _queries_ctx() if call is None else _pairs(call)


def email_of(user) -> str:
    """Синтетическая почта для проверок вывода (настоящих ПДн нет)."""
    return f"user{user.pk}@example.test"


def phone_of(user) -> str:
    """Синтетический телефон для проверок вывода (настоящих ПДн нет)."""
    return f"+7 900 000-00-{int(user.pk) % 100:02d}"


def instructions_pages() -> tuple[str, ...]:
    """Адреса страниц среза для обходов разметки и проверок статики (CONTRACT-010, 6.3)."""
    return PAGE_PATHS