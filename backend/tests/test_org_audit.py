"""T-2115: журнал среза 002 (FR-150, FR-151, NFR-106). Сценарии 1–7 спеки среза 002 (журнал — сквозной).

Все события среза пишутся настоящими вызовами служб (CONTRACT-002 §§ 3, 4, 6); код среза на уровне
модуля не импортируется (сбор проходит до появления кода).
"""
import json
import re
import secrets
from datetime import date, time
from html import unescape
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction
from django.db.utils import ProgrammingError

from tests import factories, support
from tests import support_org as org
from tests.support import model

pytestmark = pytest.mark.django_db(databases=["default", "migrate"])

IP = "198.51.100.77"
BIRTH = date(1987, 3, 21)
BIRTH_TEXTS = ("1987-03-21", "21.03.1987")
# «21.03» ловит частичный вывод даты; «1987» и «03-21» не ищем: могут встретиться в uuid и номерах
BIRTH_PARTS = ("21.03",)
DAY = date(2026, 7, 15)

# Все коды § 6 контракта и вид объекта каждого.
CODE_TYPES = {
    "unit.created": "unit", "unit.updated": "unit", "unit.moved": "unit", "unit.deleted": "unit",
    "unit.marks_changed": "unit", "unit.roles_changed": "unit",
    "membership.added": "user", "membership.removed": "user", "membership.transferred": "user",
    "user.dismissed": "user", "user.rehired": "user", "user.updated": "user",
    "photo.uploaded": "user", "photo.checked": "user", "photo.deleted": "user",
    "staff_import.completed": "staff_import",
    "calendar.settings_changed": "calendar", "calendar.year_loaded": "calendar", "calendar.day_changed": "calendar",
}
SLICE_CODES = tuple(CODE_TYPES)

# Ключи «было/стало» из таблицы § 6.
FIELD_KEYS = (
    "kind", "name", "description", "parent", "parent_id", "heads", "deputies", "roles", "unit", "unit_id", "mode",
    "mark", "reason", "units", "state", "phone", "contacts", "internal_phone", "workplace", "birth_date",
    "file_id", "size", "content_type", "result", "signature", "files", "file_name", "send_invites", "created",
    "skipped", "errors", "units_created", "work_weekdays", "day_start", "day_end", "year", "totals", "date",
)
# Значения полей, которым § 6 требует русские названия.
TOTALS_KEYS = ("holidays_on_weekdays", "moved_days_off", "moved_workdays", "short_days", "work_days")
# Ключи, значения которых — целые JSON (дополнение 7), и сами числа, которые тест знает точно.
INT_KEYS = ("unit_id", "parent_id", "size", "year", "created", "skipped", "errors", "units_created")
# Ключи `before` / `after` по таблице § 6 (`None` — сторона пуста или тест её не читает).
KEYS = {
    "unit.created": (None, {"kind", "name", "description", "parent"}),
    "unit.updated": ({"name", "description"}, {"name", "description"}),
    "unit.moved": ({"parent", "parent_id"}, {"parent", "parent_id"}),
    "unit.deleted": ({"kind", "name", "parent", "roles"}, None),
    "unit.marks_changed": ({"heads", "deputies"}, {"heads", "deputies"}),
    "unit.roles_changed": ({"roles"}, {"roles"}),
    "membership.added": (None, {"unit", "unit_id", "mode", "mark"}),
    "membership.removed": ({"unit", "unit_id", "mark", "reason"}, None),
    "membership.transferred": ({"units"}, {"units"}),
    "user.dismissed": ({"state", "roles"}, {"state"}),
    "user.rehired": ({"state"}, {"state", "roles"}),
    "user.updated": ({"phone", "contacts", "internal_phone", "workplace"},
                     {"phone", "contacts", "internal_phone", "workplace", "birth_date"}),
    "photo.uploaded": (None, {"file_id", "size", "content_type"}),
    "photo.checked": (None, {"file_id", "result"}),
    "photo.deleted": ({"files"}, None),
    "staff_import.completed": (None, {"file_name", "send_invites", "created", "skipped", "errors", "units_created"}),
    "calendar.settings_changed": ({"work_weekdays", "day_start", "day_end"}, {"work_weekdays", "day_start", "day_end"}),
    "calendar.year_loaded": ({"year", "totals"}, {"year", "totals", "file_name"}),  # before — дополнение 34
    "calendar.day_changed": ({"date", "kind"}, {"date", "kind"}),
}
OPTIONAL_KEYS = {("photo.checked", "after"): {"signature"}}
VALUE_CODES = {
    "kind": ("department", "team"), "mode": ("transfer", "concurrent"), "mark": ("head", "deputy"),
    "reason": ("manual", "transfer", "dismissal"), "result": ("clean", "quarantine"),
    "state": ("dismissed", "invited", "active"),
}


def has_cyrillic(text: str) -> bool:
    return bool(re.search("[А-Яа-яЁё]", text))


def is_russian(text: str, code: str) -> bool:
    return text != code and has_cyrillic(text)


def event_text(event) -> str:
    return json.dumps([event.action, event.object_type, event.object_id, event.before, event.after], ensure_ascii=False)


def slice_events():
    return list(model("core.AuditEvent").objects.filter(action__in=SLICE_CODES).order_by("id"))


# --- сквозной прогон: каждое действие среза настоящим вызовом службы -----------------------------

def drive(monkeypatch):
    """Выполняет по одному действию на каждый код § 6. Возвращает контекст с шагами (ожидаемые и записанные коды)."""
    from apps.core.services import accounts, files
    from apps.core.tasks import scan_file
    from apps.org.services import calendar, calendar_file, membership, people, staff_import, structure, unit_roles

    Event = model("core.AuditEvent")
    ctx = SimpleNamespace(steps=[], named={}, marks={}, photo_name=f"лицо-{secrets.token_hex(3)}.png")

    def step(expected, call, name=None):
        last = Event.objects.order_by("-id").values_list("id", flat=True).first() or 0
        result = call()
        made = [e for e in Event.objects.filter(id__gt=last, action__in=SLICE_CODES).order_by("id")]
        got = [e.action for e in made]  # коды среза 001 (invitation.sent, user.created…) здесь не считаются
        ctx.steps.append((tuple(expected), got))
        if name:
            ctx.named[name] = made
        return result

    admin = support.make_admin(full_name="Админов Админ")
    user = support.make_employee(full_name="Иванов Иван")
    other_user = support.make_employee(full_name="Петров Пётр")
    ctx.admin, ctx.user, ctx.other_user = admin, user, other_user
    root = org.root_unit()
    role = factories.make_role(permissions=("staff.view",))
    ctx.root, ctx.role = root, role

    net = step(["unit.created"], lambda: structure.create_unit(
        kind="department", name="Сеть", parent=root, description="", actor=admin, ip=IP))
    support_unit = step(["unit.created"], lambda: structure.create_unit(
        kind="department", name="Поддержка", parent=root, actor=admin, ip=IP))
    servers = step(["unit.created"], lambda: structure.create_unit(
        kind="department", name="Серверы", parent=net, actor=admin, ip=IP))
    ctx.net, ctx.support_unit, ctx.servers = net, support_unit, servers
    step(["unit.updated"], lambda: structure.update_unit(
        net, name="Сетевой отдел", description="Сети и связь", actor=admin, ip=IP))
    step(["unit.moved"], lambda: structure.move_unit(servers, support_unit, actor=admin, ip=IP), name="move")

    step(["membership.added", "membership.added"], lambda: membership.add_members(
        net, [user, other_user], mode=membership.CONCURRENT, actor=admin, ip=IP), name="concurrent")
    step(["membership.removed", "membership.added", "membership.transferred"], lambda: membership.add_members(
        support_unit, [user], mode=membership.TRANSFER, actor=admin, ip=IP), name="transfer_add")
    step(["membership.removed", "membership.added", "membership.transferred"], lambda: membership.transfer_member(
        other_user, net, support_unit, actor=admin, ip=IP), name="transfer_member")
    step(["membership.removed"], lambda: membership.remove_member(other_user, support_unit, actor=admin, ip=IP),
         name="remove")
    step(["unit.marks_changed"], lambda: membership.set_marks(support_unit, heads=[user], actor=admin, ip=IP),
         name="marks")
    step(["unit.roles_changed"], lambda: unit_roles.set_unit_roles(support_unit, [role], actor=admin, ip=IP),
         name="roles")

    temp = step(["unit.created"], lambda: structure.create_unit(
        kind="department", name="Временный", parent=root, actor=admin, ip=IP))
    step(["unit.roles_changed"], lambda: unit_roles.set_unit_roles(temp, [role], actor=admin, ip=IP))
    step(["unit.deleted"], lambda: structure.delete_unit(temp, actor=admin, ip=IP), name="delete")

    user.refresh_from_db()
    ctx.state_before_dismiss = user.state
    # § 4.3: сначала `accounts.dismiss` (`user.dismissed`), затем `membership.removed` по узлам по возрастанию `path`.
    step(["user.dismissed", "membership.removed"], lambda: people.dismiss(user, actor=admin, ip=IP), name="dismiss")
    step(["user.rehired"], lambda: people.rehire(user, actor=admin, ip=IP))

    step(["user.updated"], lambda: accounts.update_own_profile(
        other_user, phone="+7 900 111-22-33", contacts="@ivanov", internal_phone="204", workplace="Кабинет 7",
        birth_date=BIRTH, ip=IP), name="profile")

    def upload():
        return files.upload_photo(
            other_user, SimpleUploadedFile(ctx.photo_name, org.png_bytes(), content_type="image/png"),
            actor=other_user, ip=IP)

    first = step(["photo.uploaded"], upload, name="upload1")
    org.scan_clean(monkeypatch)
    step(["photo.checked"], lambda: scan_file(str(first.id)), name="check1")
    second = step(["photo.uploaded"], upload, name="upload2")
    org.scan_found(monkeypatch)
    step(["photo.checked"], lambda: scan_file(str(second.id)), name="check2")
    ctx.first_id, ctx.second_id = str(first.id), str(second.id)
    second.refresh_from_db()
    ctx.quarantine_path = files.photo_path(second)
    step(["photo.deleted"], lambda: files.delete_photo(other_user, actor=admin, ip=IP), name="photo_deleted")

    tag = secrets.token_hex(3)
    ctx.marks = {"error": f"метка-ошибка-{tag}", "skipped": f"метка-пропуск-{tag}", "note": f"метка-заметка-{tag}"}
    headers = org.STAFF_HEADERS + ("Заметка",)
    rows = [
        {**org.staff_row(), "Заметка": ctx.marks["note"]},
        {**org.staff_row(email=f"нет-почты-{ctx.marks['error']}", position=ctx.marks["error"]), "Заметка": ctx.marks["note"]},
        {**org.staff_row(email=other_user.email, last_name=ctx.marks["skipped"], position=ctx.marks["skipped"]),
         "Заметка": ctx.marks["note"]},
    ]
    ctx.import_headers = headers
    preview = staff_import.make_preview(org.staff_csv(rows, headers=headers), file_name="staff-people.csv", actor=admin, ip=IP)
    step(["staff_import.completed"], lambda: staff_import.confirm(preview, send_invites=False, actor=admin, ip=IP),
         name="import")

    step(["calendar.settings_changed"], lambda: calendar.update_settings(
        work_weekdays=[0, 1, 2, 3, 4, 5], day_start=time(8, 0), day_end=time(20, 0), actor=admin, ip=IP),
         name="settings")
    upload_item = calendar_file.make_preview(
        org.calendar_fixture("cal2026.csv"), year=2026, file_name="cal2026.csv", actor=admin, ip=IP)
    step(["calendar.year_loaded"], lambda: calendar_file.apply(upload_item, actor=admin, ip=IP), name="year")
    prior = calendar.day_kind(DAY)
    kind = "holiday" if prior != "holiday" else "workday"
    ctx.day_kind_before = prior if prior in ("holiday", "day_off", "workday", "short") else ""
    ctx.day_kind_after = kind
    step(["calendar.day_changed"], lambda: calendar.set_day(DAY, kind, actor=admin, ip=IP), name="day")
    return ctx


def check_values(ctx):
    """Значения `before`/`after` по таблице § 6 для шагов сквозного прогона (имена шагов — в `drive`)."""
    named = ctx.named
    net, support_unit, servers, root = ctx.net, ctx.support_unit, ctx.servers, ctx.root
    user, other = ctx.user, ctx.other_user
    net_name = "Сетевой отдел"  # к моменту перемещения и членств сеть уже переименована

    moved, = named["move"]
    assert moved.before == {"parent": net_name, "parent_id": net.pk}
    assert moved.after == {"parent": "Поддержка", "parent_id": support_unit.pk}
    deleted, = named["delete"]
    assert deleted.before["kind"] == "department" and deleted.before["name"] == "Временный"
    assert deleted.before["parent"] == root.name and deleted.before["roles"] == [ctx.role.name]
    marks, = named["marks"]
    assert marks.before == {"heads": [], "deputies": []}
    assert marks.after == {"heads": [user.full_name], "deputies": []}
    roles, = named["roles"]
    assert roles.before == {"roles": []} and roles.after == {"roles": [ctx.role.name]}  # дополнение 37

    # Порядок людей внутри одного вызова контракт не задаёт — сопоставление по object_id.
    assert sorted(e.object_id for e in named["concurrent"]) == sorted([str(user.pk), str(other.pk)])
    for event in named["concurrent"]:
        assert event.after == {"unit": net_name, "unit_id": net.pk, "mode": "concurrent", "mark": ""}
    removed, added, transferred = named["transfer_add"]
    assert removed.object_id == added.object_id == transferred.object_id == str(user.pk)
    assert removed.before == {"unit": net_name, "unit_id": net.pk, "mark": "", "reason": "transfer"}
    assert added.after == {"unit": "Поддержка", "unit_id": support_unit.pk, "mode": "transfer", "mark": ""}
    assert transferred.before == {"units": [net_name]} and transferred.after == {"units": ["Поддержка"]}
    removed, added, transferred = named["transfer_member"]
    assert removed.object_id == added.object_id == transferred.object_id == str(other.pk)
    assert removed.before == {"unit": net_name, "unit_id": net.pk, "mark": "", "reason": "transfer"}
    assert added.after == {"unit": "Поддержка", "unit_id": support_unit.pk, "mode": "transfer", "mark": ""}
    assert transferred.before == {"units": [net_name]} and transferred.after == {"units": ["Поддержка"]}
    manual, = named["remove"]
    assert manual.object_id == str(other.pk)
    assert manual.before == {"unit": "Поддержка", "unit_id": support_unit.pk, "mark": "", "reason": "manual"}

    dismissed, removed = named["dismiss"]
    assert dismissed.object_id == removed.object_id == str(user.pk)
    assert dismissed.before["state"] == ctx.state_before_dismiss and dismissed.after == {"state": "dismissed"}
    assert isinstance(dismissed.before["roles"], list) and dismissed.before["roles"] == sorted(dismissed.before["roles"])
    assert removed.before == {"unit": "Поддержка", "unit_id": support_unit.pk, "mark": "head", "reason": "dismissal"}
    rehired, = [e for e in slice_events() if e.action == "user.rehired"]
    assert rehired.before == {"state": "dismissed"}
    assert rehired.after == {"state": "invited", "roles": ["Сотрудник ИТ"]}

    profile, = named["profile"]
    assert profile.before.keys() == {"phone", "contacts", "internal_phone", "workplace"}
    assert profile.after.keys() == {"phone", "contacts", "internal_phone", "workplace", "birth_date"}
    assert profile.after["internal_phone"] == "204" and profile.after["workplace"] == "Кабинет 7"
    assert profile.after["contacts"] == "@ivanov" and profile.after["birth_date"] == "изменено"

    up1, = named["upload1"]
    up2, = named["upload2"]
    for event, file_id in ((up1, ctx.first_id), (up2, ctx.second_id)):
        assert event.after == {"file_id": file_id, "size": len(org.png_bytes()), "content_type": "image/png"}
    check1, = named["check1"]
    check2, = named["check2"]
    assert check1.after == {"file_id": ctx.first_id, "result": "clean"}  # подписи у чистого файла нет
    assert check2.after["file_id"] == ctx.second_id and check2.after["result"] == "quarantine"
    assert isinstance(check2.after["signature"], str) and check2.after["signature"]
    photo_deleted, = named["photo_deleted"]
    assert photo_deleted.before["files"] == [ctx.first_id]  # файл в карантине (второй) не входит, B14

    done, = named["import"]
    assert done.after["file_name"] == "staff-people.csv" and done.after["send_invites"] is False
    assert (done.after["created"], done.after["skipped"], done.after["errors"]) == (1, 1, 1)

    settings, = named["settings"]
    assert settings.before == {"work_weekdays": [0, 1, 2, 3, 4], "day_start": "09:00", "day_end": "18:00"}
    assert settings.after == {"work_weekdays": [0, 1, 2, 3, 4, 5], "day_start": "08:00", "day_end": "20:00"}
    year, = named["year"]
    assert year.after["year"] == 2026 and year.after["file_name"] == "cal2026.csv"
    assert year.before == {}  # год раньше не был загружен (§ 6)
    assert set(year.after["totals"]) == set(TOTALS_KEYS)
    for key in TOTALS_KEYS:
        value = year.after["totals"][key]
        assert isinstance(value, int) and not isinstance(value, bool), (key, value)
    day, = named["day"]
    assert day.before == {"date": DAY.isoformat(), "kind": ctx.day_kind_before}
    assert day.after == {"date": DAY.isoformat(), "kind": ctx.day_kind_after}


# --- 1. каждое действие среза пишет событие с названием по-русски -------------------------------

def test_every_slice_action_writes_event_with_russian_label(protected_root, monkeypatch):
    """FR-150: вызов службы -> ожидаемый код; для каждого кода § 6 есть событие нужного вида объекта, название кода,
    полей и значений — по-русски в `audit_labels`; `photo.checked` пишет «система», остальные — действующее лицо."""
    from apps.core.services import audit_labels, audit_search

    ctx = drive(monkeypatch)
    for number, (expected, got) in enumerate(ctx.steps, start=1):
        # порядок событий внутри шага — по возрастанию id (перевод: removed → added → transferred)
        assert tuple(got) == expected, f"шаг {number}: ожидали {list(expected)}, записано {got}"

    events = slice_events()
    by_code = {}
    for event in events:
        by_code.setdefault(event.action, []).append(event)
    assert set(by_code) == set(SLICE_CODES), sorted(set(SLICE_CODES) ^ set(by_code))
    for code, kind in CODE_TYPES.items():
        for event in by_code[code]:
            assert event.object_type == kind and isinstance(event.object_id, str) and event.object_id, code
            assert isinstance(event.before, dict) and isinstance(event.after, dict), code
            if code == "user.updated" and event.object_id != str(ctx.other_user.pk):
                continue
            for side in ("before", "after"):
                required = KEYS[code][0 if side == "before" else 1]
                data = getattr(event, side)
                if required is not None:
                    allowed = required | OPTIONAL_KEYS.get((code, side), set())
                    assert required <= set(data) <= allowed, (code, side, sorted(data))
                for key in INT_KEYS:  # дополнение 7: числа — целые JSON, не строки и не bool
                    if key in data:
                        assert isinstance(data[key], int) and not isinstance(data[key], bool), (code, side, key, data[key])
            if code == "photo.checked":
                assert event.actor_id is None
            else:
                assert event.actor_id is not None, code
    assert by_code["calendar.year_loaded"][0].object_id == "2026"
    assert by_code["calendar.day_changed"][0].object_id == DAY.isoformat()
    assert by_code["staff_import.completed"][0].object_id.isdigit()
    check_values(ctx)

    titles = dict(audit_search.known_actions())
    for code in SLICE_CODES:
        assert code in titles, f"{code}: нет в known_actions"
        assert is_russian(titles[code], code), (code, titles[code])
    assert audit_labels.object_title("unit") == "узел"
    assert audit_labels.object_title("staff_import") == "загрузка"
    assert audit_labels.object_title("calendar") == "календарь"

    keys = set(FIELD_KEYS) | set(TOTALS_KEYS)
    for event in events:
        keys |= set(event.before) | set(event.after)
        for side in (event.before, event.after):
            for value in side.values():
                if isinstance(value, dict):  # вложенные словари (`totals`): их ключи тоже названы по-русски
                    keys |= set(value)
    for key in sorted(keys):
        assert is_russian(audit_labels.label(key), key), f"поле {key} не переведено: {audit_labels.label(key)!r}"
    for field, values in VALUE_CODES.items():
        for value in values:
            assert is_russian(audit_labels.text(field, value), value), (field, value)
    assert audit_labels.text("state", "dismissed") == "уволен"
    assert audit_labels.text("state", "active") == "активен"  # значения среза 001 после слияния сохранились
    assert audit_labels.text("state", "invited") == "приглашён"


# --- 2. дата рождения в журнал не попадает ---------------------------------------------------------

def test_birth_date_value_absent_in_all_events(protected_root, monkeypatch):
    """FR-151: у `user.updated` дата рождения — только «изменено» или «очищено» (в `after`, `before` пуст); значения
    даты рождения нет ни в одном событии журнала, ни в формате ГГГГ-ММ-ДД, ни в ДД.ММ.ГГГГ."""
    from apps.core.services import accounts

    ctx = drive(monkeypatch)
    person = support.make_employee(full_name="Сидоров Сидор")

    def own(**over):
        values = dict(phone=person.phone, contacts=person.contacts, internal_phone=person.internal_phone,
                      workplace=person.workplace, birth_date=None, ip=IP)
        values.update(over)
        return accounts.update_own_profile(person, **values)

    Event = model("core.AuditEvent")
    last = Event.objects.order_by("-id").values_list("id", flat=True).first()
    own(birth_date=BIRTH)
    person.refresh_from_db()
    assert person.birth_date == BIRTH
    set_event, = Event.objects.filter(id__gt=last, action="user.updated", object_id=str(person.pk))
    assert set_event.before == {} and set_event.after == {"birth_date": "изменено"}

    last = Event.objects.order_by("-id").values_list("id", flat=True).first()
    own(birth_date=None)
    person.refresh_from_db()
    assert person.birth_date is None
    clear_event, = Event.objects.filter(id__gt=last, action="user.updated", object_id=str(person.pk))
    assert clear_event.before == {} and clear_event.after == {"birth_date": "очищено"}

    # Шаг сквозного прогона: дата вместе с другими полями — тоже только пометка.
    mixed = [e for e in Event.objects.filter(action="user.updated", object_id=str(ctx.other_user.pk))
             if "birth_date" in e.after]
    assert len(mixed) == 1 and mixed[0].after["birth_date"] == "изменено" and "birth_date" not in mixed[0].before
    # правило A2: `phone` и `contacts` пишутся оба, если изменилось хоть одно; `before` — старые значения
    # изменённых полей, `birth_date` — только в `after`.
    four = {"phone", "contacts", "internal_phone", "workplace"}
    assert set(mixed[0].before) == four and set(mixed[0].after) == four | {"birth_date"}

    texts = [event_text(e) for e in Event.objects.all()]
    assert len(texts) >= len(SLICE_CODES)
    for text in texts:
        for needle in BIRTH_TEXTS + BIRTH_PARTS:
            assert needle not in text, (needle, text)


# --- 3. содержимого файлов и путей в событиях нет ---------------------------------------------------

def test_file_contents_absent_in_all_events(protected_root, monkeypatch):
    """FR-151: ни в одном событии нет текста из файла сотрудников (в том числе из пропущенных, ошибочных строк и
    лишних колонок), из файла календаря, имени загруженного снимка и путей на диске."""
    from apps.core.services import files

    ctx = drive(monkeypatch)
    texts = [event_text(e) for e in model("core.AuditEvent").objects.all()]
    done, = model("core.AuditEvent").objects.filter(action="staff_import.completed")
    assert done.after["file_name"] == "staff-people.csv"
    assert done.after["created"] == 1 and done.after["skipped"] == 1 and done.after["errors"] == 1
    assert "content" not in done.after and "rows" not in done.after

    needles = [*ctx.marks.values(), "Заметка", *org.CALENDAR_HEADERS, ctx.photo_name,
               str(protected_root), str(ctx.quarantine_path), "/incoming/", "/quarantine/", "-512.jpg", "-96.jpg"]
    for text in texts:
        for needle in needles:
            assert needle not in text, (needle, text)
    photo_stored = model("core.StoredFile").objects.filter(status="quarantine").first()
    assert photo_stored is not None and str(files.photo_path(photo_stored)) == str(ctx.quarantine_path)


# --- 4. фильтр вида объекта ---------------------------------------------------------------------

def test_object_type_filter_has_unit_import_and_calendar():
    """FR-150: в выпадающем списке вида объекта добавлены «узел», «загрузка», «календарь» (значения `unit`,
    `staff_import`, `calendar`), прежние значения остались; фильтр отбирает события нужного вида."""
    from apps.core.services import audit_labels
    from apps.core.services.audit import record

    admin = support.make_admin()
    created = {}
    for code, kind, object_id in (("unit.created", "unit", "5"), ("staff_import.completed", "staff_import", "6"),
                                  ("calendar.year_loaded", "calendar", "2026"), ("user.updated", "user", "7")):
        created[kind] = record(code, actor=admin, object_type=kind, object_id=object_id, before={}, after={"name": "x"}, ip=IP)
    client = support.logged_in(admin, ip=IP)

    html = client.get("/audit/").content.decode()
    select = re.search(r'<select[^>]*id="id_object_type".*?</select>', html, re.S).group(0)
    options = {value: " ".join(unescape(re.sub("<[^>]+>", "", label)).split())
               for value, label in re.findall(r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', select, re.S)}
    assert options["unit"] == "узел" and options["staff_import"] == "загрузка" and options["calendar"] == "календарь"
    for old, title in (("user", "сотрудник"), ("link", "ссылка"), ("mail", "письмо"), ("role", "роль"),
                       ("ip", "адрес"), ("security_settings", "настройки безопасности"),
                       ("portal_settings", "настройки портала")):
        assert options[old] == title, old

    for kind in ("unit", "staff_import", "calendar"):
        page = client.get(f"/audit/?object_type={kind}").content.decode()
        ids = {int(n) for n in re.findall(r'data-event-id="(\d+)"', page)}
        assert ids == {created[kind].pk}, kind
        assert audit_labels.object_label(kind, "5") == f"{audit_labels.object_title(kind)} № 5"
        assert f'<span class="obj-ref">{audit_labels.object_title(kind)} №' in page
    assert audit_labels.object_label("calendar", "2026") == "календарь № 2026"


# --- 5. названия на странице и в выгрузке одни и те же --------------------------------------------

def test_slice_labels_same_on_page_and_in_csv(protected_root, monkeypatch):
    """FR-150: страница `/audit/` и выгрузка `/audit/export.csv` берут названия события, вида объекта, полей и
    значений из одного места (`audit_labels`): по каждому коду среза «Событие», «Было» и «Стало» совпадают, а
    ключей по-латыни в них нет."""
    import csv
    import io

    from apps.core.services import audit_labels, audit_search

    ctx = drive(monkeypatch)
    client = support.logged_in(ctx.admin, ip=IP)
    titles = dict(audit_search.known_actions())

    def cell_text(html: str) -> str:
        return " ".join(unescape(re.sub("<[^>]+>", " ", html)).split())

    def has_key(text: str, key: str) -> bool:
        return re.search(rf"(?<![\w.]){re.escape(key)}(?![\w.])", text) is not None

    for code in SLICE_CODES:
        events = {e.pk: e for e in model("core.AuditEvent").objects.filter(action=code)}
        assert events, code
        page = client.get(f"/audit/?action={code}&sort=at").content.decode()
        rows = {int(pk): body for pk, body in re.findall(r'<tr data-event-id="(\d+)"[^>]*>(.*?)</tr>', page, re.S)}
        assert set(rows) == set(events), code
        export = client.get(f"/audit/export.csv?action={code}&sort=at").content.decode("utf-8-sig")
        records = list(csv.reader(io.StringIO(export)))
        csv_rows = {int(r[0]): r for r in records[1:]}
        assert set(csv_rows) == set(events), code

        for pk, event in events.items():
            cells = [cell_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", rows[pk], re.S)]
            record = csv_rows[pk]
            assert record[3] == titles[code] and record[4] == code, code
            assert cells[2].startswith(titles[code]), (code, cells[2])
            assert record[5] == audit_labels.object_title(event.object_type) and record[6] == event.object_id
            assert cells[3] == audit_labels.object_label(event.object_type, event.object_id), (code, cells[3])
            for index, side in ((4, "before"), (5, "after")):
                pairs = audit_labels.side_pairs(event, side)
                assert record[index + 3] == "; ".join(f"{name}: {value}" for name, value in pairs), (code, side)
                for name, value in pairs:
                    assert f"{name}: {value}" in cells[index], (code, side, name, value, cells[index])
                nested = {k for v in getattr(event, side).values() if isinstance(v, dict) for k in v}
                for key in (*getattr(event, side), *nested):
                    assert not has_key(cells[index], key), (code, side, key, cells[index])
                    assert not has_key(record[index + 3], key), (code, side, key, record[index + 3])
                if side == "after" and code in ("calendar.year_loaded", "staff_import.completed"):
                    # дополнение 29: вложенные итоги — по-русски «название: число», без латинских ключей и `{`
                    for text in (cells[index], record[index + 3]):
                        assert "{" not in text and "}" not in text, (code, text)
                        assert re.search(r"[А-Яа-яЁё][^:;{}]*: \d+", text), (code, text)
                        for key in TOTALS_KEYS:
                            assert not has_key(text, key), (code, key, text)
                    if code == "calendar.year_loaded":
                        for key in TOTALS_KEYS:
                            title = audit_labels.label(key)
                            assert is_russian(title, key) and f"{title}: " in cells[index], (key, cells[index])
                            assert f"{title}: " in record[index + 3], (key, record[index + 3])


# --- 6. журнал только дописывается ---------------------------------------------------------------

def test_slice_events_in_append_only_journal(protected_root, monkeypatch, clock):
    """NFR-106: события среза лежат в том же журнале «только дописывается»: crm_app не может ни изменить, ни
    удалить их; код `org` не удаляет и не правит журнал; задания среза (очистка просмотров, карантина) и
    ночные очистки среза 001 через 4 года не трогают ни одного события."""
    from pathlib import Path

    from apps.core import tasks as core_tasks
    from apps.core.services import retention
    from apps.org import tasks as org_tasks

    Event = model("core.AuditEvent")
    drive(monkeypatch)
    codes = list(SLICE_CODES)
    ids = list(Event.objects.filter(action__in=codes).values_list("id", flat=True))
    assert len(ids) >= len(codes)

    with connection.cursor() as cur:
        cur.execute("SELECT has_table_privilege('crm_app', 'core_auditevent', 'UPDATE'), "
                    "has_table_privilege('crm_app', 'core_auditevent', 'DELETE'), "
                    "has_table_privilege('crm_app', 'core_auditevent', 'TRUNCATE')")
        assert cur.fetchone() == (False, False, False)
    with pytest.raises(ProgrammingError), transaction.atomic():
        Event.objects.filter(action__in=codes).update(action="tampered")
    with pytest.raises(ProgrammingError), transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("DELETE FROM core_auditevent WHERE action = ANY(%s)", [codes])
    with pytest.raises(ProgrammingError), transaction.atomic():
        Event.objects.filter(action__in=codes).delete()
    assert list(Event.objects.filter(action__in=codes).values_list("id", flat=True).order_by("id")) == sorted(ids)

    org_root = support.BACKEND_DIR / "apps" / "org"
    sources = [p for p in Path(org_root).rglob("*.py") if "migrations" not in p.parts]
    assert sources, "нет кода apps/org"
    for path in sources:
        for line in path.read_text(encoding="utf-8").splitlines():
            assert not (re.search(r"auditevent", line, re.I) and re.search(r"\.delete\(|_raw_delete|truncate|\.update\(", line, re.I)), (
                f"{path}: правка журнала: {line.strip()}")

    clock.advance(days=4 * 365)
    org_tasks.purge_previews()
    core_tasks.purge_quarantine()
    for name in ("purge_login_history", "purge_expired_links", "purge_expired_sessions"):
        getattr(retention, name)()
    assert sorted(Event.objects.filter(action__in=codes).values_list("id", flat=True)) == sorted(ids)
