"""T-2107: карточка сотрудника и свои поля (FR-133…135, FR-150, FR-151). Сценарий 10 спеки."""
import datetime
import json
import re
from html.parser import HTMLParser

import pytest

from tests import support
from tests.support import HX, model

pytestmark = pytest.mark.django_db

SECRET_DATE_FORMS = ("1953-03-05", "05.03.1953", "1953")


# --- помощники файла ----------------------------------------------------------------------------

class _CardReader(HTMLParser):
    """Читает карточку: кнопки и панели вкладок, поля `data-field`, поля форм, `[role=alert]`."""

    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source",
             "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.buttons: dict[str, dict] = {}
        self.panels: dict[str, dict] = {}
        self.fields: dict[str, dict] = {}
        self.input_names: list[str] = []
        self.cards: list[dict] = []
        self.forms: dict[str, list[str]] = {}  # action формы -> имена её полей
        self.panel_hooks: dict[str, set[str]] = {}  # панель вкладки -> зацепки `data-*` внутри неё
        self.labels: dict[str, str] = {}  # `data-field-label="<имя>"` -> текст подписи (п. 20 дополнения контракта)
        self._label: list = []  # [имя поля, тег, глубина]
        self._open: list[list] = []  # [имя поля, тег, глубина]
        self._form: str | None = None
        self._panel: list = []  # [имя панели, тег, глубина]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for entry in self._open:
            if entry[1] == tag:
                entry[2] += 1
        if self._panel and self._panel[1] == tag:
            self._panel[2] += 1
        if self._label and self._label[1] == tag:
            self._label[2] += 1
        if "data-field-label" in a and not self._label and tag not in self._VOID:
            self._label = [a["data-field-label"], tag, 1]
            self.labels[self._label[0]] = ""
        if "data-tab-panel" in a and not self._panel and tag not in self._VOID:
            self._panel = [a["data-tab-panel"], tag, 1]
            self.panel_hooks.setdefault(a["data-tab-panel"], set())
        if self._panel:
            self.panel_hooks[self._panel[0]].update(k for k in a if k.startswith("data-"))
        if tag == "form":
            self._form = a.get("action", "")
            self.forms.setdefault(self._form, [])
        if "data-tab-button" in a:
            self.buttons[a["data-tab-button"]] = a
        if "data-tab-panel" in a:
            self.panels[a["data-tab-panel"]] = a
        if "data-card" in a:
            self.cards.append(a)
        if tag in ("input", "select", "textarea") and a.get("name"):
            self.input_names.append(a["name"])
            if self._form is not None:
                self.forms[self._form].append(a["name"])
        if "data-field" in a:
            name = a["data-field"]
            self.fields[name] = {"text": "", "empty": a.get("data-empty")}
            self._open.append([name, tag, 1])

    def handle_endtag(self, tag):
        if tag == "form":
            self._form = None
        if self._panel and self._panel[1] == tag:
            self._panel[2] -= 1
            if self._panel[2] == 0:
                self._panel = []
        if self._label and self._label[1] == tag:
            self._label[2] -= 1
            if self._label[2] == 0:
                self._label = []
        for entry in list(self._open):
            if entry[1] == tag:
                entry[2] -= 1
                if entry[2] == 0:
                    self._open.remove(entry)

    def handle_data(self, data):
        if self._label:
            self.labels[self._label[0]] += data
        for entry in self._open:
            self.fields[entry[0]]["text"] += data

    def text(self, name: str) -> str:
        return " ".join(self.fields[name]["text"].split())

    def label(self, name: str) -> str:
        """Подпись поля `name`: элемент `[data-field-label]` есть, текст непустой."""
        assert name in self.labels, f"у поля {name} нет подписи [data-field-label]"
        return " ".join(self.labels[name].split())


LABELS = {"internal_phone": "Внутренний телефон", "workplace": "Место работы", "birth_date": "Дата рождения",
          "units": "Подразделение", "head": "Руководитель", "position": "Должность",
          "email": "Почта", "phone": "Телефон", "state": "Состояние"}  # подписи — дополнения 20 и 30


def assert_labels(reader, *names):
    """Подписи полей по-русски рядом со своими `[data-field]` (дополнение 20)."""
    for name in names:
        assert name in reader.fields, name
        assert reader.label(name) == LABELS[name], (name, reader.label(name))


def read_card(client, path: str, **extra) -> tuple[_CardReader, str]:
    response = client.get(path, **extra)
    assert response.status_code == 200, f"{path}: {response.status_code}"
    html = response.content.decode()
    reader = _CardReader()
    reader.feed(html)
    return reader, html


def has_alert(response) -> bool:
    return re.search(r'role="alert"', response.content.decode()) is not None


def viewer_staff_view():
    """Коллега: только право «staff.view» (ни `accounts.manage`, ни `accounts.view_logins`)."""
    return support.make_with_permissions("staff.view")


def own_post(client, user, **over):
    """POST `/me/` со всеми полями формы; по умолчанию — текущие значения (ничего не меняется)."""
    data = {"phone": user.phone, "contacts": "", "internal_phone": user.internal_phone,
            "workplace": user.workplace, "birth_date": ""}
    if user.birth_date:
        data["birth_date"] = user.birth_date.strftime("%d.%m.%Y")
    data.update(over)
    return client.post("/me/", data)


def edit_post(client, target, **over):
    """POST `/staff/<id>/edit/` со всеми полями формы администратора; по умолчанию — текущие значения."""
    data = {"full_name": target.full_name, "position": target.position, "phone": target.phone,
            "email": target.email, "contacts": "", "internal_phone": target.internal_phone,
            "workplace": target.workplace}
    data.update(over)
    return client.post(f"/staff/{target.pk}/edit/", data)


def user_events(user, **filters):
    return list(model("core.AuditEvent").objects.filter(
        action="user.updated", object_id=str(user.pk), **filters).order_by("id"))


def reload(user):
    return model("core.User").objects.get(pk=user.pk)


# --- вкладки (FR-135) ---------------------------------------------------------------------------

def test_card_tabs_profile_and_security_empty_fields_not_filled():
    """FR-135: у чужой карточки две вкладки в одном ответе (и во фрагменте HTMX), открыт «Профиль»;
    пустые поля — «не заполнено»; без прав на «Безопасность» вкладки и её данных нет."""
    target = support.make_employee(position="Инженер")
    admin_client = support.logged_in(support.make_admin())
    reader, html = read_card(admin_client, f"/staff/{target.pk}/")
    assert reader.cards and reader.cards[0].get("data-user-id") == str(target.pk)
    assert set(reader.buttons) == {"profile", "security"}
    assert set(reader.panels) == {"profile", "security"}
    assert reader.buttons["profile"].get("aria-selected") == "true"
    assert reader.buttons["security"].get("aria-selected") != "true"
    assert "hidden" not in reader.panels["profile"], "по умолчанию открыт «Профиль»"
    assert "hidden" in reader.panels["security"], "неактивная панель несёт атрибут hidden"
    assert "Профиль" in html and "Безопасность" in html
    # пустые поля — «не заполнено», заполненные — нет
    for name in ("internal_phone", "workplace", "birth_date", "units"):
        assert reader.fields[name]["empty"] == "true", name
        assert "не заполнено" in reader.text(name), name
    assert reader.fields["position"]["empty"] == "false" and "Инженер" in reader.text("position")
    assert_labels(reader, "internal_phone", "workplace", "birth_date", "units", "head", "position", "email", "phone")
    assert reader.fields["head"]["empty"] == "true", "у человека без членств руководитель не назначен"
    assert "state" in reader.fields, "у accounts.manage в «Безопасности» есть состояние учётной записи"
    assert_labels(reader, "state")
    # поле units у уволенного тоже выводится: «не заполнено» (дополнение 13)
    gone = support.make_employee(position="Инженер", state="dismissed")
    gone_reader, _ = read_card(admin_client, f"/staff/{gone.pk}/")
    assert gone_reader.fields["units"]["empty"] == "true" and "не заполнено" in gone_reader.text("units")
    # поля заполнены — признак пустоты снимается
    User = model("core.User")
    User.objects.filter(pk=target.pk).update(internal_phone="1234", workplace="Кабинет 5")
    filled, _ = read_card(admin_client, f"/staff/{target.pk}/")
    assert filled.fields["internal_phone"]["empty"] == "false" and "1234" in filled.text("internal_phone")
    assert filled.fields["workplace"]["empty"] == "false" and "Кабинет 5" in filled.text("workplace")
    # фрагмент HTMX: без <html>, обе панели на месте
    fragment = admin_client.get(f"/staff/{target.pk}/", **HX)
    assert fragment.status_code == 200
    fragment_html = fragment.content.decode()
    assert "<html" not in fragment_html.lower()
    fragment_reader = _CardReader()
    fragment_reader.feed(fragment_html)
    assert set(fragment_reader.panels) == {"profile", "security"}
    assert "hidden" in fragment_reader.panels["security"]
    # смотрящий без accounts.manage и accounts.view_logins: вкладки «Безопасность» нет вовсе
    colleague = support.logged_in(viewer_staff_view())
    plain, plain_html = read_card(colleague, f"/staff/{target.pk}/")
    assert set(plain.buttons) == {"profile"} and set(plain.panels) == {"profile"}
    assert colleague.get(f"/staff/{target.pk}/logins/").status_code == 403
    assert "state" not in plain.fields, "состояние — только у accounts.manage"
    assert f"/staff/{target.pk}/block/" not in plain_html and f"/staff/{target.pk}/logins/" not in plain_html
    assert plain.fields["internal_phone"]["empty"] == "false"
    assert_labels(plain, "internal_phone", "workplace", "birth_date", "position")


def test_own_card_has_both_tabs():
    """FR-135: свою карточку (`/me/`) сотрудник видит с обеими вкладками, хотя прав у него нет;
    вкладка «Безопасность» несёт тот же блок, что `/me/security/`."""
    me = support.make_employee()
    client = support.logged_in(me)
    reader, html = read_card(client, "/me/")
    assert reader.cards and reader.cards[0].get("data-user-id") == str(me.pk)
    assert set(reader.buttons) == {"profile", "security"}
    assert set(reader.panels) == {"profile", "security"}
    assert reader.buttons["profile"].get("aria-selected") == "true"
    assert "hidden" not in reader.panels["profile"] and "hidden" in reader.panels["security"]
    assert "data-backup-remaining" in reader.panel_hooks["security"], \
        "в панели «Безопасность» — блок резервных кодов, как в /me/security/"
    assert "data-backup-remaining" in client.get("/me/security/").content.decode()
    for name in ("internal_phone", "workplace", "birth_date"):
        assert reader.fields[name]["empty"] == "true" and "не заполнено" in reader.text(name), name
    assert_labels(reader, "internal_phone", "workplace", "birth_date")
    # форма своих полей — на странице
    assert {"internal_phone", "workplace", "birth_date"} <= set(reader.input_names)


# --- внутренний телефон и место работы (FR-133) ---------------------------------------------------

def test_internal_phone_and_workplace_edited_by_self_and_by_accounts_manage():
    """FR-133: внутренний телефон и место работы правят сам сотрудник (`/me/`) и администратор
    с `accounts.manage` (`/staff/<id>/edit/`); коллега с `staff.view` их видит, но не правит."""
    me = support.make_employee(phone="+7 900 000-00-01", position="Инженер")
    client = support.logged_in(me)
    done = own_post(client, me, internal_phone="1234", workplace="Москва, Кабинет 12")
    assert done.status_code == 302 and done["Location"].endswith("/me/")
    me = reload(me)
    assert (me.internal_phone, me.workplace) == ("1234", "Москва, Кабинет 12")
    assert me.phone == "+7 900 000-00-01", "телефон не тронут"
    [event] = user_events(me)
    assert event.actor_id == me.pk
    assert event.before == {"internal_phone": "", "workplace": ""}
    assert event.after == {"internal_phone": "1234", "workplace": "Москва, Кабинет 12"}
    # коллега видит значения
    colleague = support.logged_in(viewer_staff_view())
    seen, _ = read_card(colleague, f"/staff/{me.pk}/")
    assert "1234" in seen.text("internal_phone") and "Кабинет 12" in seen.text("workplace")
    # коллега не правит: 403 и база не меняется
    assert edit_post(colleague, me, internal_phone="9999", workplace="Чужое").status_code == 403
    assert reload(me).internal_phone == "1234"
    # сотрудник без accounts.manage не правит и свою запись через форму администратора
    assert edit_post(client, me, internal_phone="9999").status_code == 403
    assert reload(me).internal_phone == "1234"
    # администратор правит оба поля
    admin = support.make_admin()
    admin_client = support.logged_in(admin)
    done = edit_post(admin_client, me, internal_phone="5678", workplace="Казань, Офис 3")
    assert done.status_code == 302 and done["Location"].endswith(f"/staff/{me.pk}/")
    me = reload(me)
    assert (me.internal_phone, me.workplace) == ("5678", "Казань, Офис 3")
    last = user_events(me, actor=admin)
    assert len(last) == 1
    assert last[0].before == {"internal_phone": "1234", "workplace": "Москва, Кабинет 12"}
    assert last[0].after == {"internal_phone": "5678", "workplace": "Казань, Офис 3"}
    # правка администратора не затирает дату рождения сотрудника
    me.birth_date = datetime.date(1953, 3, 5)
    me.save(update_fields=["birth_date"])
    assert edit_post(admin_client, me, workplace="Казань, Офис 4").status_code == 302
    assert reload(me).birth_date == datetime.date(1953, 3, 5)


# --- дата рождения (FR-134) ---------------------------------------------------------------------

def test_birth_date_entered_changed_cleared_only_by_self():
    """FR-134: дату рождения вводит, меняет и стирает сам сотрудник (ДД.ММ.ГГГГ и ГГГГ-ММ-ДД);
    неверная дата — 200 с `[role=alert]`, база не меняется; хранится полностью."""
    me = support.make_employee()
    client = support.logged_in(me)
    assert me.birth_date is None
    done = own_post(client, me, birth_date="05.03.1953")
    assert done.status_code == 302 and done["Location"].endswith("/me/")
    assert reload(me).birth_date == datetime.date(1953, 3, 5)
    own, _ = read_card(client, "/me/")
    assert own.fields["birth_date"]["empty"] == "false" and "05.03.1953" in own.text("birth_date")
    # меняет — вторым форматом
    assert own_post(client, me, birth_date="1954-04-06").status_code == 302
    assert reload(me).birth_date == datetime.date(1954, 4, 6)
    # неверные значения не меняют базу
    for broken in ("31.02.1954", "вчера", "1954-13-40"):
        bad = own_post(client, me, birth_date=broken)
        assert bad.status_code == 200 and has_alert(bad), broken
        assert reload(me).birth_date == datetime.date(1954, 4, 6), broken
    # стирает
    assert own_post(client, me, birth_date="").status_code == 302
    me = reload(me)
    assert me.birth_date is None
    own, _ = read_card(client, "/me/")
    assert own.fields["birth_date"]["empty"] == "true" and "не заполнено" in own.text("birth_date")
    # ни коллега, ни администратор не меняют и не стирают чужую дату
    me.birth_date = datetime.date(1953, 3, 5)
    me.save(update_fields=["birth_date"])
    colleague = support.logged_in(viewer_staff_view())
    assert edit_post(colleague, me, birth_date="01.01.2000").status_code == 403
    admin_client = support.logged_in(support.make_admin())
    for value in ("01.01.2000", ""):
        refused = edit_post(admin_client, me, birth_date=value)
        assert refused.status_code == 200 and has_alert(refused), repr(value)
        assert reload(me).birth_date == datetime.date(1953, 3, 5), repr(value)


def test_colleagues_see_day_and_month_year_only_self():
    """FR-134: коллега и администратор видят день и месяц рождения, но не год; полную дату видит
    только сам сотрудник в `/me/`; своя карточка `/staff/<свой id>/` — как у любой (день и месяц, решение 15)."""
    User = model("core.User")
    marked = support.make_employee(full_name="Иванова Анна")
    User.objects.filter(pk=marked.pk).update(birth_date=datetime.date(1953, 3, 5))
    january = support.make_employee(full_name="Петров Пётр")
    User.objects.filter(pk=january.pk).update(birth_date=datetime.date(1987, 1, 21))
    december = support.make_employee(full_name="Сидоров Семён")
    User.objects.filter(pk=december.pk).update(birth_date=datetime.date(1990, 12, 1))
    for viewer in (viewer_staff_view(), support.make_admin()):
        client = support.logged_in(viewer)
        seen, html = read_card(client, f"/staff/{marked.pk}/")
        assert seen.fields["birth_date"]["empty"] == "false"
        assert_labels(seen, "birth_date")
        assert "5 марта" in seen.text("birth_date")
        assert "1953" not in seen.text("birth_date")
        assert "05.03.1953" not in html and "1953-03-05" not in html
        assert "21 января" in read_card(client, f"/staff/{january.pk}/")[0].text("birth_date")
        first = read_card(client, f"/staff/{december.pk}/")[0].text("birth_date")
        assert "1 декабря" in first and "01 декабря" not in first and "1990" not in first
    # без даты у коллеги — «не заполнено»
    nobody = support.make_employee()
    empty, _ = read_card(support.logged_in(viewer_staff_view()), f"/staff/{nobody.pk}/")
    assert empty.fields["birth_date"]["empty"] == "true" and "не заполнено" in empty.text("birth_date")
    # сам видит полную дату в /me/, а по /staff/<свой id>/ — день и месяц
    me_client = support.logged_in(marked)
    own, _ = read_card(me_client, "/me/")
    assert "05.03.1953" in own.text("birth_date")
    via_staff, staff_html = read_card(me_client, f"/staff/{marked.pk}/")
    assert "5 марта" in via_staff.text("birth_date") and "1953" not in via_staff.text("birth_date")
    assert "05.03.1953" not in staff_html


def test_admin_form_has_no_birth_date_and_direct_post_refused():
    """FR-134: в форме администратора нет поля даты рождения, а сервис правки чужой записи
    отклоняет `birth_date` и при прямом вызове, и при прямом POST; остальное в запросе не применяется."""
    from apps.core.services import accounts

    me = support.make_employee(position="Инженер")
    me.birth_date = datetime.date(1953, 3, 5)
    me.save(update_fields=["birth_date"])
    admin = support.make_admin()
    admin_client = support.logged_in(admin)
    reader, _ = read_card(admin_client, f"/staff/{me.pk}/")
    edit_fields = reader.forms.get(f"/staff/{me.pk}/edit/")
    assert edit_fields is not None, "в карточке есть форма правки чужой записи"
    assert {"internal_phone", "workplace", "full_name"} <= set(edit_fields)
    assert "birth_date" not in reader.input_names, "в карточке чужой записи поля даты рождения нет"
    assert "birth_date" not in edit_fields
    # прямой POST: 200 с [role=alert], ничего не меняется (в том числе другие поля того же запроса)
    events_before = len(user_events(me))
    for value in ("01.01.2000", "", "1953-03-06"):
        refused = edit_post(admin_client, me, position="Директор", birth_date=value)
        assert refused.status_code == 200 and has_alert(refused), repr(value)
        fresh = reload(me)
        assert fresh.birth_date == datetime.date(1953, 3, 5), repr(value)
        assert fresh.position == "Инженер", repr(value)
    assert len(user_events(me)) == events_before
    # сервис: отказ и без побочных эффектов
    for value in (datetime.date(2000, 1, 1), None):
        with pytest.raises(accounts.AccountError) as raised:
            accounts.update_profile(me, actor=admin, birth_date=value)
        assert "Дату рождения меняет только сам сотрудник" in str(raised.value)
    assert reload(me).birth_date == datetime.date(1953, 3, 5)
    assert len(user_events(me)) == events_before
    # допустимые новые поля сервис принимает
    accounts.update_profile(me, actor=admin, internal_phone="4321", workplace="Офис")
    assert (reload(me).internal_phone, reload(me).workplace) == ("4321", "Офис")


# --- журнал (FR-150, FR-151) --------------------------------------------------------------------

def test_card_fields_events_birth_date_as_changed_or_cleared_only():
    """FR-150, FR-151: `user.updated` пишется только при изменении; `internal_phone` и `workplace` —
    только изменённые; `birth_date` — только в `after` словом «изменено» или «очищено», без значения даты."""
    from apps.core.services import accounts

    me = support.make_employee(phone="+7 900 000-00-02", position="Инженер")
    admin = support.make_admin()
    date = datetime.date(1953, 3, 5)

    def own(**over):
        args = {"phone": me.phone, "contacts": "", "internal_phone": me.internal_phone,
                "workplace": me.workplace, "birth_date": me.birth_date}
        args.update(over)
        result = accounts.update_own_profile(me, **args)
        me.refresh_from_db()
        return result

    own()
    assert user_events(me) == [], "ничего не изменилось — события нет"
    # дата рождения введена: до — пусто, после — только слово
    own(birth_date=date)
    [first] = user_events(me)
    assert (first.before, first.after) == ({}, {"birth_date": "изменено"})
    assert first.actor_id == me.pk
    # дата изменена
    own(birth_date=datetime.date(1954, 4, 6))
    second = user_events(me)[1]
    assert (second.before, second.after) == ({}, {"birth_date": "изменено"})
    # та же дата — события нет
    own(birth_date=datetime.date(1954, 4, 6))
    assert len(user_events(me)) == 2
    # дата стёрта
    own(birth_date=None)
    third = user_events(me)[2]
    assert (third.before, third.after) == ({}, {"birth_date": "очищено"})
    own(birth_date=None)
    assert len(user_events(me)) == 3, "стирать нечего — события нет"
    assert me.birth_date is None
    # внутренний телефон и место работы — только изменённые, со значениями
    own(internal_phone="1111", workplace="Офис А", birth_date=date)
    fourth = user_events(me)[3]
    assert fourth.before == {"internal_phone": "", "workplace": ""}
    assert fourth.after == {"internal_phone": "1111", "workplace": "Офис А", "birth_date": "изменено"}
    own(workplace="Офис Б")
    fifth = user_events(me)[4]
    assert (fifth.before, fifth.after) == ({"workplace": "Офис А"}, {"workplace": "Офис Б"})
    # телефон и контакты пишутся оба, если изменилось хоть одно
    own(phone="+7 900 000-00-03")
    sixth = user_events(me)[5]
    assert set(sixth.before) == {"phone", "contacts"} and set(sixth.after) == {"phone", "contacts"}
    assert sixth.after["phone"] == "+7 900 000-00-03"
    # правка администратора: только изменённые ключи, действующий — администратор
    accounts.update_profile(me, actor=admin, workplace="Офис В")
    [by_admin] = user_events(me, actor=admin)
    assert (by_admin.before, by_admin.after) == ({"workplace": "Офис Б"}, {"workplace": "Офис В"})
    accounts.update_profile(me, actor=admin, workplace="Офис В")
    assert len(user_events(me, actor=admin)) == 1, "то же значение — события нет"
    # значение даты рождения не встречается ни в одном событии пользователя
    dumped = json.dumps([[e.before, e.after] for e in user_events(me)], ensure_ascii=False)
    for form in SECRET_DATE_FORMS + ("1954", "1954-04-06", "06.04.1954"):
        assert form not in dumped, form
    # то же при правке через страницу /me/
    client = support.logged_in(me)
    assert own_post(client, me, birth_date="07.08.1960").status_code == 302
    page_event = user_events(me)[-1]
    assert (page_event.before, page_event.after) == ({}, {"birth_date": "изменено"})
    dumped = json.dumps([[e.before, e.after] for e in user_events(me)], ensure_ascii=False)
    assert "1960" not in dumped and "07.08" not in dumped
