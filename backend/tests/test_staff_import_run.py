"""T-2111: предпросмотр и выполнение загрузки сотрудников (FR-137…142, FR-151, NFR-103). Сценарий 5 спеки среза 002."""
import json
import time
from datetime import timedelta
from html.parser import HTMLParser

import pytest
from django.utils import timezone

from tests import factories, support, support_mail
from tests import support_org as org
from tests.support import model

pytestmark = pytest.mark.django_db

CREATED_PREFIXES = ("user.", "unit.", "membership.", "invitation.", "staff_import.")


# --- разбор разметки (помощник только этого файла) ---------------------------------------------

class _El:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.kids = tag, attrs, parent, []

    def walk(self):
        yield self
        for kid in self.kids:
            if isinstance(kid, _El):
                yield from kid.walk()

    def text(self) -> str:
        parts = [kid if isinstance(kid, str) else kid.text() for kid in self.kids]
        return " ".join(" ".join(parts).split())

    def find_all(self, tag=None, **want):
        """Элементы с тегом `tag` и атрибутами `want` (`data_x` -> `data-x`; True — любое значение)."""
        wanted = {key.replace("_", "-"): value for key, value in want.items()}
        found = []
        for el in self.walk():
            if tag is not None and el.tag != tag:
                continue
            if all(name in el.attrs and (value is True or el.attrs[name] == str(value)) for name, value in wanted.items()):
                found.append(el)
        return found


class _Builder(HTMLParser):
    _VOID = {"input", "br", "img", "hr", "meta", "link", "area", "base", "col", "source", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _El("#root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        el = _El(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.kids.append(el)
        if tag not in self._VOID:
            self.cur = el

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(_El(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.kids.append(data)


def dom(response) -> _El:
    builder = _Builder()
    builder.feed(response.content.decode("utf-8", "replace"))
    return builder.root


# --- данные и вызовы ----------------------------------------------------------------------------

def service():
    from apps.org.services import staff_import

    return staff_import


def admin():
    """Администратор загрузки: оба права, `accounts.manage` и `org.manage`."""
    return support.make_with_permissions("accounts.manage", "org.manage", "staff.view", full_name="Загружающий Админ")


def root_name() -> str:
    return org.root_unit().name


def row(**over) -> dict:
    return org.staff_row(**over)


def preview(rows, actor, *, name: str = "people.csv", xlsx: bool = False):
    content = org.staff_xlsx(rows) if xlsx else org.staff_csv(rows)
    return service().make_preview(content, file_name=name, actor=actor)


def confirm(item, actor, *, send_invites: bool = False):
    return service().confirm(item, send_invites=send_invites, actor=actor)


def numbered(item) -> dict:
    return {r["number"]: r for r in item.rows}


def counts() -> dict:
    return {"users": model("core.User").objects.count(), "units": model("org.Unit").objects.count(),
            "members": model("org.Membership").objects.count()}


def events(*prefixes, **filters) -> list:
    qs = model("core.AuditEvent").objects.filter(**filters).order_by("id")
    return [e for e in qs if e.action.startswith(prefixes)] if prefixes else list(qs)


def import_events() -> int:
    """Число событий загрузки и созданных ею объектов (для проверки «ничего не записано»)."""
    return len(events(*CREATED_PREFIXES))


def get_page(actor, item):
    client = support.logged_in(actor)
    response = client.get(f"/structure/import/{item.pk}/")
    assert response.status_code == 200, "страница загрузки не открылась"
    return dom(response)


def email_of_length(n: int, tag: str) -> str:
    """Годная по форме почта ровно из `n` знаков (локальная часть 64 знака, метки домена до 61 знака)."""
    local = (tag + "a" * 64)[:64]
    domain_len = n - len(local) - 1
    labels, left = [], domain_len - len(".com")
    while left > 0:
        size = min(61, left)
        if left - size == 1:  # после точки должна остаться непустая метка
            size -= 1
        labels.append("b" * size)
        left -= size + 1
    email = f"{local}@{'.'.join(labels)}.com"
    assert len(email) == n, f"помощник собрал почту из {len(email)} знаков вместо {n}"
    return email


def row_el(root: _El, number: int) -> _El:
    found = root.find_all("tr", data_import_row=True, data_row_number=number)
    assert len(found) == 1, f"в таблице нет строки {number} (data-import-row, data-row-number)"
    return found[0]


# --- тесты --------------------------------------------------------------------------------------

def test_row_errors_email_names_position_lengths_head_flag():
    """FR-139: ошибки строки по кодам — почта, ФИО, должность, длины полей, флаг руководителя; годные строки проходят."""
    actor, root = admin(), root_name()
    good_email = factories.new_email("good")
    rows = [
        row(email=""),                                                  # 1
        row(email="не-почта"),                                          # 2
        row(last_name=""),                                              # 3
        row(first_name=""),                                             # 4
        row(position=""),                                               # 5
        row(position="д" * 256),                                        # 6
        row(phone="1" * 65),                                            # 7
        row(internal_phone="1" * 33),                                   # 8
        row(workplace="к" * 256),                                       # 9
        row(head="может", unit_path=root),                              # 10
        row(head="да", unit_path=""),                                   # 11
        row(email=f"  {good_email.upper()} ", head="да", unit_path=root),  # 12
        row(position="д" * 255, head="нет"),                            # 13
        row(last_name="Ф" * 100, first_name="И" * 100, middle_name="О" * 54),  # 14 ФИО 256 знаков
        row(last_name="Ф" * 100, first_name="И" * 100, middle_name="О" * 53),  # 15 ФИО 255 знаков
        row(phone="1" * 64),                                            # 16 телефон ровно 64
        row(internal_phone="1" * 32),                                   # 17 внутренний ровно 32
        row(email=email_of_length(255, "p")),                           # 18 почта 255 знаков
        row(email=email_of_length(254, "q")),                           # 19 почта 254 знака
    ]
    item = preview(rows, actor)
    by = numbered(item)
    expected = {1: "email_missing", 2: "email_invalid", 3: "last_name_missing", 4: "first_name_missing",
                5: "position_missing", 6: "too_long", 7: "too_long", 8: "too_long", 9: "too_long",
                10: "head_invalid", 11: "head_without_unit", 14: "too_long", 18: "too_long"}
    assert [r["number"] for r in item.rows] == list(range(1, 20)), "строки идут по порядку файла с номера 1"
    for number, code in expected.items():
        assert by[number]["result"] == "error", f"строка {number}: ожидали ошибку"
        assert by[number]["code"] == code, f"строка {number}: код {by[number]['code']!r}, ожидали {code!r}"
        assert by[number]["reason"].strip(), f"строка {number}: причина по-русски не названа"
        assert by[number]["hint"] == ""
    for number in (12, 13, 15, 16, 17, 19):
        assert by[number]["result"] == "will_create" and by[number]["code"] == "" and by[number]["reason"] == ""
    assert by[12]["email"] == good_email.lower(), "почта в строке — без крайних пробелов и в нижнем регистре"
    assert by[12]["head"] is True and by[13]["head"] is False
    assert by[12]["unit_path"] == root and by[10]["unit_path"] == root
    assert item.state == "preview"
    assert item.summary["created"] == 6 and item.summary["skipped"] == 0 and item.summary["errors"] == 13
    assert item.summary["units_created"] == 0
    # страница: подпись «ошибка: <причина>» у строки с ошибкой и «будет создан» у годной
    root_el = get_page(actor, item)
    assert "ошибка" in row_el(root_el, 1).text().lower()
    assert row_el(root_el, 1).find_all(None, data_row_result="error")[0] is row_el(root_el, 1)
    assert row_el(root_el, 1).find_all(None, data_row_reason=True)[0].text()
    assert "будет создан" in row_el(root_el, 12).text().lower()


def test_duplicate_email_in_file_and_existing_including_dismissed_hint():
    """FR-139: первая почта в файле «будет создан», повторы и почты портала — «пропущен»; у уволенного подсказка."""
    actor = admin()
    existing = support.make_employee(email=factories.new_email("have"))
    dismissed = support.make_employee(email=factories.new_email("gone"), state="dismissed", totp=False)
    a, b = factories.new_email("a"), factories.new_email("b")
    item = preview([
        row(email=a),                       # 1
        row(email=a.upper()),               # 2 повтор в файле без учёта регистра
        row(email=existing.email.upper()),  # 3 есть в портале
        row(email=dismissed.email),         # 4 уволенный
        row(email=b),                       # 5
        row(email=b),                       # 6
    ], actor)
    by = numbered(item)
    assert [by[n]["result"] for n in range(1, 7)] == ["will_create", "skipped", "skipped", "skipped",
                                                      "will_create", "skipped"]
    assert [by[n]["code"] for n in (2, 3, 4, 6)] == ["email_repeated", "email_taken", "email_taken_dismissed",
                                                     "email_repeated"]
    assert [by[n]["hint"] for n in range(1, 7)] == ["", "", "", "dismissed", "", ""]
    assert item.summary["created"] == 2 and item.summary["skipped"] == 4 and item.summary["errors"] == 0
    root_el = get_page(actor, item)
    assert "будет создан" in row_el(root_el, 1).text().lower()
    for number in (2, 3, 4, 6):
        el = row_el(root_el, number)
        assert el.find_all(None, data_row_result="skipped")[0] is el
        assert "такая почта уже есть" in el.text().lower(), f"строка {number}: нет «такая почта уже есть»"
    assert row_el(root_el, 4).find_all(None, data_row_hint="dismissed"), "у уволенного нет подсказки"
    assert "уволен: верните его из карточки" in row_el(root_el, 4).text().lower()
    for number in (1, 2, 3, 5, 6):
        assert not row_el(root_el, number).find_all(None, data_row_hint=True), f"строка {number}: лишняя подсказка"


def test_path_root_first_team_on_path_error_missing_parts_become_departments_listed_once():
    """FR-137, FR-138: путь начинается с корня; команда на пути — ошибка; недостающие части — отделы, каждый один раз."""
    actor, root = admin(), root_name()
    org.make_tree({"Сервис": {"team:Дежурные": {}}, "team:Дежурные2": {}})
    long150, long151 = "х" * 150, "х" * 151
    item = preview([
        row(unit_path=f"{root} / Сеть / Поддержка"),            # 1
        row(unit_path=f"{root.upper()} / сеть / ПОДДЕРЖКА"),    # 2 те же узлы, иной регистр
        row(unit_path=root),                                    # 3 только корень
        row(unit_path="Чужой отдел / Сеть"),                    # 4
        row(unit_path=f"{root} / Сервис / Дежурные"),           # 5 команда в конце пути
        row(unit_path=f"{root} / Сервис / Дежурные / Глубже"),  # 6 команда посреди пути
        row(unit_path=f"{root} / Дежурные2"),                   # 7 команда прямо под корнем
        row(unit_path=f"{root} //Сеть"),                        # 8 пустая часть
        row(unit_path=f"{root} / {long151}"),                   # 9 часть длиннее 150
        row(unit_path=f"{root} / {long150}"),                   # 10 ровно 150
        row(unit_path=f"{root} / Сервис / Новый"),              # 11 существующий + новый
    ], actor)
    by = numbered(item)
    assert [by[n]["result"] for n in (1, 2, 3, 10, 11)] == ["will_create"] * 5
    assert by[4]["code"] == "path_root_mismatch"
    assert by[5]["code"] == by[6]["code"] == by[7]["code"] == "path_team"
    assert by[8]["code"] == "path_invalid"
    assert by[9]["code"] == "too_long"
    for number in (4, 5, 6, 7, 8, 9):
        assert by[number]["result"] == "error" and by[number]["reason"].strip(), f"строка {number}"
    expected = [f"{root} / Сеть", f"{root} / Сеть / Поддержка", f"{root} / {long150}", f"{root} / Сервис / Новый"]
    assert sorted(item.summary["new_units"]) == sorted(expected)
    assert len(item.summary["new_units"]) == len(set(item.summary["new_units"])), "узел назван больше одного раза"
    assert item.summary["units_created"] == 4
    listed = [li.text() for block in get_page(actor, item).find_all(None, data_import_new_units=True)
              for li in block.find_all("li")]
    assert sorted(listed) == sorted(expected), "страница перечисляет создаваемые отделы по одному на элемент"


def test_departments_only_from_rows_to_be_created():
    """FR-139: отделы берутся только из строк «будет создан»; строки с ошибкой и «пропущен» отделов не создают."""
    actor, root = admin(), root_name()
    existing = support.make_employee(email=factories.new_email("have"))
    twice = factories.new_email("twice")
    item = preview([
        row(email="", unit_path=f"{root} / Ошибка"),                            # 1 ошибка
        row(unit_path=f"{root} / Ошибка2", head="возможно"),                    # 2 ошибка
        row(email=existing.email, unit_path=f"{root} / Пропуск"),               # 3 пропущен
        row(email=twice, unit_path=f"{root} / Новый"),                          # 4 будет создан
        row(email=twice, unit_path=f"{root} / Повтор"),                         # 5 пропущен (повтор)
        row(unit_path=f"{root} / Новый"),                                       # 6 будет создан
    ], actor)
    assert [numbered(item)[n]["result"] for n in range(1, 7)] == ["error", "error", "skipped", "will_create",
                                                                  "skipped", "will_create"]
    assert item.summary["new_units"] == [f"{root} / Новый"]
    assert item.summary["units_created"] == 1
    assert item.summary["created"] == 2 and item.summary["skipped"] == 2 and item.summary["errors"] == 2
    listed = [li.text() for block in get_page(actor, item).find_all(None, data_import_new_units=True)
              for li in block.find_all("li")]
    assert listed == [f"{root} / Новый"]
    confirm(item, actor)
    names = set(model("org.Unit").objects.values_list("name", flat=True))
    assert "Новый" in names
    assert not names & {"Ошибка", "Ошибка2", "Пропуск", "Повтор"}, "отделы из лишних строк созданы"


def test_preview_creates_nothing():
    """FR-139: предпросмотр ничего не создаёт: ни записей, ни отделов, ни членств, ни писем, ни событий создания."""
    actor, root = admin(), root_name()
    before, events_before = counts(), import_events()
    jobs_before = len(support_mail.mail_jobs())
    mail_before = model("mail.MailMessage").objects.count()
    links_before = model("core.OneTimeLink").objects.count()
    item = preview([row(unit_path=f"{root} / Новый / Вложенный", head="да"), row(), row(email="")], actor)
    assert (item.state, item.file_format, model("org.StaffImport").objects.count()) == ("preview", "csv", 1)
    assert counts() == before
    assert import_events() == events_before, "предпросмотр записал события создания"
    assert model("mail.MailMessage").objects.count() == mail_before
    assert model("core.OneTimeLink").objects.count() == links_before
    assert len(support_mail.mail_jobs()) == jobs_before
    keys = {"number", "email", "last_name", "first_name", "middle_name", "position", "phone", "internal_phone",
            "workplace", "unit_path", "head", "result", "code", "reason", "hint"}
    assert all(set(r) == keys for r in item.rows), "ключи строки до выполнения не по контракту"
    summary = item.summary
    assert (summary["created"], summary["skipped"], summary["errors"], summary["units_created"]) == (2, 0, 1, 2)
    assert summary["not_loaded"] == []
    assert len(summary["new_units"]) == 2
    reloaded = model("org.StaffImport").objects.get(pk=item.pk)
    assert reloaded.rows == item.rows and reloaded.state == "preview"
    root_el = get_page(actor, item)
    assert root_el.find_all(None, data_import_preview=True), "нет блока [data-import-preview]"
    form = root_el.find_all("form", data_form="import-confirm")
    assert len(form) == 1
    flag = form[0].find_all("input", type="checkbox", name="send_invites")
    assert len(flag) == 1 and flag[0].attrs.get("value") == "1"
    assert "отправить приглашения сразу" in form[0].text().lower()
    assert form[0].find_all("button", type="submit")
    assert not root_el.find_all(None, data_result_summary=True), "итог показан до подтверждения"


def test_confirm_creates_invited_users_with_staff_role_units_memberships_head_mark():
    """FR-137, FR-139: подтверждение создаёт приглашённых с ролью «Сотрудник ИТ», отделы, членства и отметку руководителя."""
    actor, root = admin(), root_name()
    existing = support.make_employee(email=factories.new_email("have"))
    path = f"{root} / Сеть / Поддержка"
    ea, eb, ec = (factories.new_email(x) for x in "abc")
    item = preview([
        row(email=ea, last_name="Иванов", first_name="Иван", middle_name="Иванович", position="Инженер",
            phone="+7 900 111-22-33", internal_phone="201", workplace="Кабинет 7", unit_path=path, head="да"),
        row(email=eb, unit_path=path, head="нет"),
        row(email=ec, unit_path="", head=""),
        row(email="", unit_path=f"{root} / Сеть"),
        row(email=existing.email),
    ], actor)
    before = counts()
    done = confirm(item, actor)
    assert done.state == "done"
    assert (done.summary["created"], done.summary["skipped"], done.summary["errors"],
            done.summary["units_created"]) == (3, 1, 1, 2)
    after = counts()
    assert (after["users"] - before["users"], after["units"] - before["units"],
            after["members"] - before["members"]) == (3, 2, 2)
    User, Unit = model("core.User"), model("org.Unit")
    a, b, c = (User.objects.get(email=e) for e in (ea, eb, ec))
    assert a.full_name == "Иванов Иван Иванович" and a.position == "Инженер"
    assert (a.phone, a.internal_phone, a.workplace) == ("+7 900 111-22-33", "201", "Кабинет 7")
    for user in (a, b, c):
        assert user.state == "invited" and not user.has_usable_password(), "войти до активации нельзя"
        assert sorted(user.roles.values_list("name", flat=True)) == ["Сотрудник ИТ"]
    net, support_unit = Unit.objects.get(name="Сеть"), Unit.objects.get(name="Поддержка")
    assert net.kind == support_unit.kind == "department"
    assert net.parent_id == org.root_unit().pk and support_unit.parent_id == net.pk
    assert support_unit.path == f"{net.path}{support_unit.pk}/"
    Membership = model("org.Membership")
    assert [(m.unit_id, m.mark) for m in Membership.objects.filter(user=a)] == [(support_unit.pk, "head")]
    assert [(m.unit_id, m.mark) for m in Membership.objects.filter(user=b)] == [(support_unit.pk, "")]
    assert not Membership.objects.filter(user=c).exists()
    assert not User.objects.filter(email="").exists()
    # события: создание записей, отделов и членств; отметка руководителя — в `membership.added`
    created = events("user.created", object_type="user")
    assert sorted(e.after["email"] for e in created if e.after.get("email") in (ea, eb, ec)) == sorted([ea, eb, ec])
    assert all(e.actor_id == actor.pk for e in created)
    assert all(e.after["roles"] == ["Сотрудник ИТ"] for e in created if e.after.get("email") in (ea, eb, ec))
    unit_events = events("unit.created")
    assert [e.after["name"] for e in unit_events] == ["Сеть", "Поддержка"], "отделы создаются от верхнего к нижнему"
    assert unit_events[1].after["parent"] == "Сеть" and unit_events[1].after["kind"] == "department"
    added = {e.object_id: e.after for e in events("membership.added")}
    assert added[str(a.pk)]["mark"] == "head" and added[str(b.pk)]["mark"] == ""
    assert added[str(a.pk)]["mode"] == "" and added[str(b.pk)]["mode"] == "", "членство из загрузки — с mode=\"\""
    assert str(c.pk) not in added
    assert not events("unit.marks_changed"), "отметка из загрузки не пишет unit.marks_changed"


def test_confirm_twice_shows_same_result_does_nothing(django_capture_on_commit_callbacks):
    """FR-139: повторное подтверждение показывает прежний итог и ничего не выполняет, нового события и писем нет."""
    actor, root = admin(), root_name()
    existing = support.make_employee(email=factories.new_email("have"))
    item = preview([row(unit_path=f"{root} / Новый"), row(), row(email=existing.email)], actor)
    created_emails = [r["email"] for r in item.rows if r["result"] == "will_create"]
    client = support.logged_in(actor)
    url = f"/structure/import/{item.pk}/"
    with django_capture_on_commit_callbacks(execute=True):
        first = client.post(url, {"send_invites": "1"})
    assert first.status_code == 302 and first["Location"] == url
    messages = model("mail.MailMessage").objects.filter(template="invitation")
    assert sorted(m.to for m in messages) == sorted(created_emails), "письма — ровно созданным строкам"
    state = (counts(), len(events()), len(events("staff_import.completed")), model("mail.MailMessage").objects.count(),
            len(events("invitation.sent")), len(support_mail.mail_jobs()))
    assert state[2] == 1 and state[3] == 2 and state[4] == 2 and state[5] == 2
    snapshot = model("org.StaffImport").objects.get(pk=item.pk)
    assert snapshot.state == "done"
    with django_capture_on_commit_callbacks(execute=True):
        second = client.post(url, {"send_invites": "1"})
    assert second.status_code == 302 and second["Location"] == url
    assert (counts(), len(events()), len(events("staff_import.completed")), model("mail.MailMessage").objects.count(),
            len(events("invitation.sent")), len(support_mail.mail_jobs())) == state
    with django_capture_on_commit_callbacks(execute=True):
        again = service().confirm(snapshot, send_invites=True, actor=actor)
    assert again.state == "done" and again.summary == snapshot.summary and again.rows == snapshot.rows
    assert len(events()) == state[1] and model("mail.MailMessage").objects.count() == state[3]
    shown = client.get(url)
    summary = dom(shown).find_all(None, data_result_summary=True)
    assert len(summary) == 1
    assert "создано 2, пропущено 1, с ошибками 0" in summary[0].text().lower()


def test_confirm_rechecks_emails_taken_since_preview():
    """FR-139: при подтверждении почта проверяется заново: занятая за время предпросмотра строка пропускается."""
    actor, root = admin(), root_name()
    taken, gone, free = (factories.new_email(x) for x in ("taken", "gone", "free"))
    item = preview([
        row(email=taken, unit_path=f"{root} / Только из занятой"),
        row(email=gone),
        row(email=free),
    ], actor)
    assert [r["result"] for r in item.rows] == ["will_create"] * 3
    support.make_employee(email=taken.upper())
    support.make_employee(email=gone, state="dismissed", totp=False)
    done = confirm(item, actor)
    by = numbered(done)
    assert [by[n]["result"] for n in (1, 2, 3)] == ["skipped", "skipped", "created"]
    assert "такая почта уже есть" in by[1]["reason"].lower()
    User = model("core.User")
    assert User.objects.filter(email__iexact=taken).count() == 1 and User.objects.filter(email=gone).count() == 1
    assert User.objects.get(email=free).state == "invited"
    assert (done.summary["created"], done.summary["skipped"], done.summary["errors"]) == (1, 2, 0)
    assert not model("org.Unit").objects.filter(name="Только из занятой").exists(), \
        "отдел из пропущенной при подтверждении строки создан"
    assert done.summary["units_created"] == 0


def test_row_failure_rolls_back_only_that_row(monkeypatch, django_capture_on_commit_callbacks):
    """FR-139, FR-140: отказ базы в одной строке откатывает только её (запись, отдел, событие, письмо); остальные созданы."""
    from django.db import DataError

    from apps.core.services import accounts

    actor, root = admin(), root_name()
    emails = [factories.new_email(f"r{i}") for i in range(1, 4)]
    item = preview([
        row(email=emails[0], unit_path=f"{root} / Первый"),
        row(email=emails[1], unit_path=f"{root} / Откат"),
        row(email=emails[2], unit_path=f"{root} / Откат"),
    ], actor)
    assert [r["result"] for r in item.rows] == ["will_create"] * 3
    raw_message = "СЫРОЕ-СООБЩЕНИЕ-БАЗЫ-ДЛИННОЕ-ЗНАЧЕНИЕ"
    real = accounts.create_user

    def failing(**kwargs):
        user = real(**kwargs)  # запись и всё, что она поставила, уже сделано — откатить должна точка сохранения строки
        if kwargs["email"].strip().lower() == emails[1].lower():
            raise DataError(raw_message)
        return user

    monkeypatch.setattr("apps.core.services.accounts.create_user", failing)
    with django_capture_on_commit_callbacks(execute=True):
        done = confirm(model("org.StaffImport").objects.get(pk=item.pk), actor, send_invites=True)
    by = numbered(done)
    assert [by[n]["result"] for n in (1, 2, 3)] == ["created", "error", "created"]
    assert by[2]["reason"].strip() and raw_message not in by[2]["reason"], "в причине — не сырое сообщение базы"
    User, Unit = model("core.User"), model("org.Unit")
    assert not User.objects.filter(email=emails[1]).exists(), "запись откатанной строки осталась"
    assert User.objects.filter(email__in=[emails[0], emails[2]]).count() == 2
    assert Unit.objects.filter(name="Откат").count() == 1, "отдел «Откат» должен быть создан ровно один раз — строкой 3"
    third = User.objects.get(email=emails[2])
    assert list(third.memberships.values_list("unit__name", flat=True)) == ["Откат"]
    assert not model("org.Membership").objects.filter(user__email=emails[1]).exists()
    assert (done.summary["created"], done.summary["errors"], done.summary["units_created"]) == (2, 1, 2)
    assert [e.after["email"] for e in events("user.created") if e.after.get("email") in emails] == [emails[0], emails[2]]
    assert [e.after["name"] for e in events("unit.created")].count("Откат") == 1, "событие отдела откатанной строки осталось"
    # письма: только созданным строкам; для откатанной нет ни письма, ни задания, ни события
    messages = model("mail.MailMessage").objects.filter(template="invitation")
    assert sorted(m.to for m in messages) == sorted([emails[0], emails[2]])
    assert not messages.filter(to__iexact=emails[1]).exists()
    assert len(support_mail.mail_jobs()) == 2
    assert len(events("invitation.sent")) == 2
    assert {e.object_id for e in events("invitation.sent")} == {str(User.objects.get(email=e).pk) for e in (emails[0], emails[2])}


def test_reimport_creates_zero_users_units_memberships():
    """FR-139: тот же файл второй раз — все строки «пропущен», новых записей, отделов и членств нет."""
    actor, root = admin(), root_name()
    content = org.staff_csv([
        row(unit_path=f"{root} / Сеть / Поддержка", head="да"),
        row(unit_path=f"{root} / Сеть"),
        row(),
    ])
    first = confirm(service().make_preview(content, file_name="people.csv", actor=actor), actor)
    assert first.summary["created"] == 3 and first.summary["units_created"] == 2
    before, events_before = counts(), import_events()
    second_preview = service().make_preview(content, file_name="people.csv", actor=actor)
    assert [r["result"] for r in second_preview.rows] == ["skipped"] * 3
    assert [r["code"] for r in second_preview.rows] == ["email_taken"] * 3
    assert second_preview.summary["new_units"] == [] and second_preview.summary["units_created"] == 0
    second = confirm(second_preview, actor)
    assert second.state == "done"
    assert [r["result"] for r in second.rows] == ["skipped"] * 3
    assert (second.summary["created"], second.summary["skipped"], second.summary["errors"],
            second.summary["units_created"]) == (0, 3, 0, 0)
    assert counts() == before
    new_events = [e.action for e in events(*CREATED_PREFIXES)][events_before:]
    assert new_events == ["staff_import.completed"], f"повторная загрузка записала лишнее: {new_events}"


def test_invitations_only_with_flag_after_commit(django_capture_on_commit_callbacks):
    """FR-140: без флажка писем нет; с флажком приглашения идут созданным и только после фиксации транзакции."""
    actor, root = admin(), root_name()
    existing = support.make_employee(email=factories.new_email("have"))
    rows = lambda: [row(unit_path=f"{root} / Сеть"), row(), row(email=""), row(email=existing.email)]  # noqa: E731

    off = preview(rows(), actor)
    with django_capture_on_commit_callbacks(execute=True):
        confirm(off, actor, send_invites=False)
    assert model("mail.MailMessage").objects.filter(template="invitation").count() == 0
    assert support_mail.mail_jobs() == []
    assert not events("invitation.sent")
    assert model("core.OneTimeLink").objects.filter(user__state="invited").count() == 0
    assert model("core.User").objects.filter(state="invited").count() == 2
    assert [e.after["send_invites"] for e in events("staff_import.completed")] == [False]

    fresh = [row(unit_path=f"{root} / Сеть"), row(), row(email=""), row(email=existing.email)]
    on = preview(fresh, actor, name="again.csv")
    recipients = [r["email"] for r in on.rows if r["result"] == "will_create"]
    assert len(recipients) == 2
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        done = confirm(on, actor, send_invites=True)
    assert done.state == "done" and done.summary["created"] == 2
    assert support_mail.mail_jobs() == [], "письма поставлены в очередь до фиксации транзакции"
    for callback in callbacks:
        callback()
    messages = model("mail.MailMessage").objects.filter(template="invitation").order_by("id")
    assert sorted(m.to for m in messages) == sorted(recipients), "приглашения — только созданным"
    assert len(support_mail.mail_jobs()) == 2
    assert len(events("invitation.sent")) == 2
    assert {e.object_id for e in events("invitation.sent")} == {
        str(model("core.User").objects.get(email=e).pk) for e in recipients}
    assert [e.after["send_invites"] for e in events("staff_import.completed")][-1] is True


def test_rows_trimmed_after_done_unconfirmed_preview_purged_after_day():
    """FR-141: после выполнения от строки остаются номер, почта, итог и причина; неподтверждённый предпросмотр старше суток удаляется."""
    actor, root = admin(), root_name()
    existing = support.make_employee(email=factories.new_email("have"))
    item = preview([row(unit_path=f"{root} / Сеть"), row(email=existing.email), row(email="")], actor)
    done = confirm(item, actor)
    stored = model("org.StaffImport").objects.get(pk=done.pk)
    for source in (done, stored):
        assert all(set(r) == {"number", "email", "result", "reason"} for r in source.rows), \
            "после выполнения остаются только number, email, result, reason"
        assert [(r["number"], r["result"]) for r in source.rows] == [(1, "created"), (2, "skipped"), (3, "error")]
        assert source.rows[0]["reason"] == "", "у созданной строки причины нет"
        assert source.rows[1]["reason"].strip() and source.rows[2]["reason"].strip()
        assert source.rows[1]["email"] == existing.email
        assert source.summary.get("new_units") is None, "после выполнения в итоге нет ключа new_units"
        assert (source.summary["created"], source.summary["skipped"], source.summary["errors"]) == (1, 1, 1)
    assert "last_name" not in json.dumps(stored.rows) and "Тестов" not in json.dumps(stored.rows)
    # ночная очистка
    old = preview([row()], actor, name="old.csv")
    fresh = preview([row()], actor, name="fresh.csv")
    old_done = confirm(preview([row()], actor, name="old_done.csv"), actor)
    StaffImport = model("org.StaffImport")
    now = timezone.now()
    StaffImport.objects.filter(pk=old.pk).update(created_at=now - timedelta(hours=25))
    StaffImport.objects.filter(pk=fresh.pk).update(created_at=now - timedelta(hours=23))
    StaffImport.objects.filter(pk__in=[old_done.pk, done.pk]).update(created_at=now - timedelta(days=3))
    from apps.org.tasks import purge_previews

    assert purge_previews() == 1
    assert not StaffImport.objects.filter(pk=old.pk).exists(), "предпросмотр старше суток не удалён"
    assert StaffImport.objects.filter(pk=fresh.pk).exists(), "свежий предпросмотр удалён"
    assert StaffImport.objects.filter(pk__in=[done.pk, old_done.pk]).count() == 2, "выполненную загрузку удалять нельзя"
    assert purge_previews() == 0


def test_import_completed_event_and_per_object_events_without_file_content():
    """FR-142, FR-151: итоговое событие загрузки (кто, файл, итоги) и события на каждый объект; содержимого файла в журнале нет."""
    actor, root = admin(), root_name()
    existing = support.make_employee(email=factories.new_email("have"))
    ea, eb = factories.new_email("a"), factories.new_email("b")
    marker_name, marker_phone = "Уникальнофамильев", "+7 999 555-44-33"
    item = preview([
        row(email=ea, last_name=marker_name, phone=marker_phone, unit_path=f"{root} / Сеть / Поддержка", head="да"),
        row(email=eb),
        row(email=existing.email),
        row(email="сломано без собаки", last_name=marker_name + "2"),
    ], actor, name="Список сотрудников.csv")
    done = confirm(item, actor, send_invites=False)
    completed = events("staff_import.completed")
    assert len(completed) == 1
    event = completed[0]
    assert (event.object_type, event.object_id, event.actor_id) == ("staff_import", str(done.pk), actor.pk)
    assert event.after == {"file_name": "Список сотрудников.csv", "send_invites": False,
                           "created": 2, "skipped": 1, "errors": 1, "units_created": 2}
    assert all(type(event.after[k]) is int for k in ("created", "skipped", "errors", "units_created"))
    dump = json.dumps([event.before, event.after], ensure_ascii=False)
    for secret in (ea, eb, existing.email, marker_name, marker_phone, "сломано"):
        assert secret not in dump, f"в событии загрузки есть содержимое файла: {secret!r}"
    user_pks = {str(u.pk) for u in model("core.User").objects.filter(email__in=[ea, eb])}
    assert {e.object_id for e in events("user.created", object_type="user") if e.object_id in user_pks} == user_pks
    assert len(events("unit.created")) == 2
    assert {e.object_id for e in events("membership.added")} == {str(model("core.User").objects.get(email=ea).pk)}
    assert all(e.actor_id == actor.pk for e in events(*CREATED_PREFIXES))
    whole = json.dumps([[e.before, e.after] for e in events("staff_import.")], ensure_ascii=False)
    assert "Почта" not in whole and "Фамилия" not in whole
    # то, что сделала загрузка, найти в журнале по виду объекта «загрузка»
    assert events(object_type="staff_import") == completed


def test_preview_1000_rows_under_10_seconds_csv_and_xlsx():
    """NFR-103: предпросмотр 1000 строк (CSV и XLSX) строится быстрее 10 секунд."""
    actor, root = admin(), root_name()
    for fmt in ("csv", "xlsx"):
        rows = [row(email=f"load{fmt}{i}@example.test", last_name=f"Фамилия{i}", unit_path=f"{root} / Отдел {i % 50}",
                    head="да" if i % 50 == 0 else "нет") for i in range(1000)]
        content = org.staff_xlsx(rows) if fmt == "xlsx" else org.staff_csv(rows)
        assert len(content) <= 1_048_576
        started = time.perf_counter()
        item = service().make_preview(content, file_name=f"people.{fmt}", actor=actor)
        elapsed = time.perf_counter() - started
        assert elapsed < 10, f"предпросмотр {fmt} на 1000 строк занял {elapsed:.1f} с (предел 10 с)"
        assert item.file_format == fmt and len(item.rows) == 1000
        assert item.summary["created"] == 1000 and item.summary["units_created"] == 50
        assert len(item.summary["new_units"]) == 50


def test_created_event_includes_internal_phone_and_workplace():
    """Доп. 69 (а): `user.created` называет `internal_phone` и `workplace` (загрузка и создание без них)."""
    from apps.core.services import accounts

    actor, root = admin(), root_name()
    email = factories.new_email("evt")
    item = preview([row(email=email, internal_phone="201", workplace="Кабинет 7", unit_path=root)], actor)
    confirm(item, actor)
    user = model("core.User").objects.get(email=email)
    [event] = events("user.created", object_id=user.pk)
    assert event.after["internal_phone"] == "201" and event.after["workplace"] == "Кабинет 7"

    plain = accounts.create_user(email=factories.new_email("plain"), full_name="Без Полей", position="Инженер",
                                 role_ids=[support.role_by_name(support.STAFF_ROLE).pk], actor=actor, invite=False)
    [event] = events("user.created", object_id=plain.pk)
    assert "internal_phone" in event.after and "workplace" in event.after
    assert event.after["internal_phone"] == "" and event.after["workplace"] == ""
