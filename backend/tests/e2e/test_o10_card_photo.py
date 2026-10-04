"""T-2146: сценарий 10 — сотрудник заполняет карточку: фото, внутренний телефон, место работы, дата рождения
(FR-132, FR-133, FR-134, FR-135, NFR-108). Фото проверяет настоящий clamd стенда."""
import re
import secrets
import time

from playwright.sync_api import expect

from tests import support_org
from tests.e2e import helpers
from tests.e2e.helpers_org import (add_members, audit_rows, audit_sides, create_unit, direct_get, direct_post, has_alert,
                                   member_row, open_structure, root_id, unique_name, upload_file,
                                   wait_photo_checked)

PHOTO_LIMIT = 60.0  # FR-132: антивирус проверяет фото не дольше 1 минуты
PHOTO_SRC = r"/staff/{id}/photo/[0-9a-f-]{{36}}/(512|96)/"


def _own_card(page):
    """Корень карточки на `/me/`: `[data-card]` (§ 9.3)."""
    return page.locator("[data-card]").first


def _upload_photo(page, content: bytes, *, name: str = "photo.png", mime: str = "image/png",
                  capture_me: bool = False):
    """Загрузка фото формой `form[action="/me/photo/"]` (поле `photo`, § 8.1) на странице `/me/`; ждёт ответ POST.
    С `capture_me=True` (только для принятого файла: после POST идёт редирект) возвращает тело ответа
    `GET /me/` сразу после загрузки — самое раннее состояние страницы; иначе возвращает None."""
    page.goto("/me/")
    form = page.locator('form[action="/me/photo/"]')
    expect(form).to_have_count(1)
    body = None
    if capture_me:
        with page.expect_response(lambda r: r.request.method == "GET" and r.url.rstrip("/").endswith("/me")) as got:
            with page.expect_navigation():  # ждём сам ответ POST (доп. 51), а не появление сообщения
                upload_file(form, content, field="photo", name=name, mime=mime)
        body = got.value.text()
    else:
        with page.expect_navigation():
            upload_file(form, content, field="photo", name=name, mime=mime)
    page.wait_for_load_state()
    return body


def _fill_own_fields(page, *, internal_phone=None, workplace=None, birth_date=None) -> None:
    """Форма `/me/` (`form[action="/me/"]`, поля `internal_phone`, `workplace`, `birth_date`): заполняет только
    заданные поля (дата — текстом `ДД.ММ.ГГГГ`, пустая строка стирает; доп. 57), отправляет и ждёт 302 на `/me/`."""
    page.goto("/me/")
    form = page.locator('form[action="/me/"]')
    expect(form).to_have_count(1)
    if internal_phone is not None:
        form.locator("[name=internal_phone]").fill(internal_phone)
    if workplace is not None:
        form.locator("[name=workplace]").fill(workplace)
    if birth_date is not None:
        form.locator("input[data-datefield-input][name=birth_date]").fill(birth_date)
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    assert page.url.rstrip("/").endswith("/me"), f"после сохранения свои поля не открылись: {page.url}"
    assert helpers.status_text(page), "после сохранения нет сообщения об успехе (доп. 51)"


def _colleague_card(page, user_id):
    """Открывает `/staff/<id>/` и возвращает локатор карточки `[data-card][data-user-id]`."""
    page.goto(f"/staff/{user_id}/")
    card = page.locator(f'[data-card][data-user-id="{user_id}"]').first
    expect(card).to_be_visible()
    return card


def test_o10_clean_photo_shown_within_one_minute_in_card_list_and_structure(admin_page, employee):
    """Сценарий 10, п. 1: до проверки в карточке, списке и «Структуре» — заглушка с инициалами; сотрудник
    загружает PNG, настоящий clamd стенда проверяет его не позже минуты, после этого фото показано в его
    карточке, в списке «Сотрудники» и в «Структуре», выдаётся как JPEG (FR-132)."""
    tag = secrets.token_hex(3)
    acc = employee(full_name=f"Фотов{tag} Пётр Иванович")
    own = acc.page
    src_pattern = re.compile(PHOTO_SRC.format(id=acc.id))

    open_structure(admin_page)
    team = create_unit(admin_page, unique_name("Фото"), kind="team", parent_id=root_id(admin_page))
    add_members(admin_page, team, [acc.id], q=f"Фотов{tag}")

    def list_photo():
        admin_page.goto(f"/staff/?q=Фотов{tag}")
        return helpers.staff_row(admin_page, acc.email).locator('[data-cell="photo"] [data-photo]')

    def structure_photo():
        open_structure(admin_page, team)
        return member_row(admin_page, acc.id).locator("[data-photo]")

    # п. 1: до загрузки — заглушка с инициалами «ФП» везде, картинки нет
    own.goto("/me/")
    own_photo = _own_card(own).locator("[data-photo]").first
    expect(own_photo.locator('[data-photo-placeholder][data-initials="ФП"]')).to_have_count(1)
    expect(own_photo.locator("img[data-photo-img]")).to_have_count(0)
    for place in (list_photo(), structure_photo()):
        expect(place.locator('[data-photo-placeholder][data-initials="ФП"]')).to_have_count(1)
        expect(place.locator("img[data-photo-img]")).to_have_count(0)

    # п. 1: загрузка PNG и ожидание проверки настоящим clamd (не позже минуты)
    started = time.monotonic()
    me_body = _upload_photo(own, helpers.make_png(400, 300), capture_me=True)
    # Ответ GET /me/ сразу после загрузки: если в нём статус «pending» — должен быть текст «Фото проверяется» и
    # не должно быть своей картинки; если статуса уже нет, clamd успел — это допустимо. Надёжно состояние
    # «проверяется» закрывает серверный test_photo::test_initials_placeholder_until_clean_in_card_list_and_structure
    # (антивирус там подменён); в браузере воркер задержать нельзя, состояние не управляемо.
    if 'data-photo-status="pending"' in me_body:
        assert "Фото проверяется" in me_body, "в состоянии pending нет текста «Фото проверяется»"
        assert "data-photo-img" not in me_body, "пока фото проверяется, показана картинка вместо заглушки"
    pending = own.locator('[data-card] [data-photo-status="pending"]')
    if pending.count():  # и в уже отрисованной странице, если статус ещё не снят
        expect(pending.first).to_contain_text("Фото проверяется")
        expect(own.locator('[data-card] img[data-photo-img]')).to_have_count(0)
    assert wait_photo_checked(own, "/me/", timeout=PHOTO_LIMIT) == "clean", "чистое фото не принято"
    assert time.monotonic() - started <= PHOTO_LIMIT + 10, "проверка чистого фото заняла больше минуты"

    # п. 1: фото в карточке, статусов проверки нет, фото отдаётся как JPEG
    expect(own.locator('[data-card] [data-photo-status]')).to_have_count(0)
    img = _own_card(own).locator("img[data-photo-img]").first
    expect(img).to_have_attribute("src", src_pattern)
    response = direct_get(own, img.get_attribute("src"))
    assert response.status == 200, f"фото не выдано: {response.status}"
    assert response.headers.get("content-type", "").startswith("image/jpeg")
    assert response.body()[:2] == b"\xff\xd8", "выданное фото — не JPEG"

    # п. 1: то же фото в списке «Сотрудники» и в «Структуре» (глазами администратора)
    expect(list_photo().locator("img[data-photo-img]")).to_have_attribute("src", src_pattern)
    expect(list_photo().locator("[data-photo-placeholder]")).to_have_count(0)
    expect(structure_photo().locator("img[data-photo-img]")).to_have_attribute("src", src_pattern)
    expect(structure_photo().locator("[data-photo-placeholder]")).to_have_count(0)


def test_o10_fake_png_refused(employee):
    """Сценарий 10, п. 2: файл, не являющийся PNG или JPEG по содержимому, хотя имя оканчивается на «.png»
    (подпись PNG без картинки; строка EICAR под именем «.png»), портал отклоняет с понятным отказом, заглушка
    остаётся, «проверяется» не появляется (FR-132, NFR-108)."""
    acc = employee(full_name=f"Подделкин{secrets.token_hex(3)} Иван Петрович")
    own = acc.page
    for label, content in (("подпись PNG без картинки", support_org.fake_png()),
                           ("EICAR под именем .png", support_org.eicar_bytes())):
        _upload_photo(own, content, name="photo.png", mime="image/png")
        expect(own.locator("[role=alert]").first, label).to_be_visible()
        assert helpers.alert_text(own), f"отказ без текста: {label}"
        # ничего не принято: на странице нет картинки и статуса проверки, а после перезагрузки — заглушка
        expect(own.locator("img[data-photo-img]"), label).to_have_count(0)
        own.goto("/me/")
        expect(_own_card(own).locator("[data-photo-placeholder]").first, label).to_be_visible()
        expect(own.locator("img[data-photo-img]"), label).to_have_count(0)
        expect(own.locator("[data-photo-status]"), label).to_have_count(0)


def test_o10_internal_phone_workplace_and_birth_date_visibility(admin_page, employee):
    """Сценарий 10, п. 5, 6, 8: сотрудник вводит внутренний телефон, место работы и дату рождения — коллега и
    администратор видят телефон и место, а у даты только день и месяц, год видит лишь сам сотрудник; администратор
    правит телефон и место в карточке; сотрудник стирает дату — поле «не заполнено», в журнале нет значений
    даты (FR-133, FR-134)."""
    tag = secrets.token_hex(3)
    owner = employee(full_name=f"Датин{tag} Пётр Иванович")
    viewer = employee(full_name=f"Зритель{tag} Иван Петрович")

    # п. 5-6: сотрудник заполняет свои поля; в своей карточке дата полная
    _fill_own_fields(owner.page, internal_phone="4455", workplace=f"Кабинет {tag}", birth_date="15.03.1961")
    card = _own_card(owner.page)
    expect(card.locator('[data-field="internal_phone"]')).to_contain_text("4455")
    expect(card.locator('[data-field="workplace"]')).to_contain_text(f"Кабинет {tag}")
    expect(card.locator('[data-field="birth_date"]')).to_contain_text("15.03.1961")
    for hook, label in (("internal_phone", "Внутренний телефон"), ("workplace", "Место работы"),
                        ("birth_date", "Дата рождения")):
        expect(card.locator(f'[data-field-label="{hook}"]')).to_contain_text(label)

    # п. 5-6: коллега и администратор видят телефон и место; дата — только «15 марта», года нет
    for who, page in (("коллега", viewer.page), ("администратор", admin_page)):
        seen = _colleague_card(page, owner.id)
        expect(seen.locator('[data-field="internal_phone"]'), who).to_contain_text("4455")
        expect(seen.locator('[data-field="workplace"]'), who).to_contain_text(f"Кабинет {tag}")
        expect(seen.locator('[data-field="birth_date"]'), who).to_have_text(re.compile(r"^\s*15 марта\s*$"))
        field_text = seen.locator('[data-field="birth_date"]').inner_text()
        assert "1961" not in field_text and "15.03" not in field_text, f"{who} увидел год рождения"

    # п. 5: те же поля правит администратор с правом «управлять учётными записями»
    _colleague_card(admin_page, owner.id)
    edit = admin_page.locator(f'form[action="/staff/{owner.id}/edit/"]')
    expect(edit).to_have_count(1)
    edit.locator("[name=internal_phone]").fill("9911")
    edit.locator("[name=workplace]").fill(f"Склад {tag}")
    with admin_page.expect_navigation():
        edit.locator("button[type=submit]").click()
    admin_page.wait_for_load_state()
    assert helpers.status_text(admin_page), "после правки администратором нет сообщения об успехе (доп. 51)"
    seen = _colleague_card(viewer.page, owner.id)
    expect(seen.locator('[data-field="internal_phone"]')).to_contain_text("9911")
    expect(seen.locator('[data-field="workplace"]')).to_contain_text(f"Склад {tag}")
    expect(seen.locator('[data-field="birth_date"]')).to_have_text(re.compile(r"^\s*15 марта\s*$"))  # дата цела

    # п. 8: сотрудник стирает дату — «не заполнено»; в журнале изменение записано, значений даты нет
    before_clear = len(audit_rows(admin_page, "user.updated", owner.id))
    _fill_own_fields(owner.page, birth_date="")
    cleared = _own_card(owner.page).locator('[data-field="birth_date"]')
    expect(cleared).to_have_attribute("data-empty", "true")
    expect(cleared).to_contain_text("не заполнено")
    expect(_colleague_card(viewer.page, owner.id).locator('[data-field="birth_date"]')).to_contain_text("не заполнено")
    rows = audit_rows(admin_page, "user.updated", owner.id)
    assert len(rows) > before_clear, "стирание даты рождения не записано в журнал"
    # только ячейки «было/стало» (доп. 58): в строке целиком есть время события «ДД.ММ.ГГГГ ЧЧ:ММ:СС»
    sides = audit_sides(admin_page, "user.updated", owner.id)
    for was, became in sides:
        for cell in (was, became):
            assert "1961" not in cell and "15.03" not in cell and "03-15" not in cell, "в журнале есть значение даты"
    assert "очищено" in sides[0][1].lower(), f"в «стало» самого нового события нет «очищено» (§ 6): {sides[0]!r}"


def test_o10_admin_cannot_touch_birth_date_can_delete_photo(admin_page, employee):
    """Сценарий 10, п. 7: администратор не может изменить или стереть дату рождения чужой записи (в форме поля нет,
    прямой запрос отказывает, дата цела); чужое фото он удаляет, у коллеги без права такой возможности нет
    (FR-132, FR-134)."""
    tag = secrets.token_hex(3)
    owner = employee(full_name=f"Удалов{tag} Пётр Иванович")
    other = employee(full_name=f"Чужой{tag} Иван Петрович")
    own = owner.page

    # подготовка: чистое фото (проверка идёт параллельно со следующими шагами) и дата рождения
    _upload_photo(own, helpers.make_png(300, 300))
    _fill_own_fields(own, birth_date="15.03.1961")

    # п. 7: в форме администратора поля даты нет, а прямой запрос с датой отказывает, дата цела
    _colleague_card(admin_page, owner.id)
    edit = admin_page.locator(f'form[action="/staff/{owner.id}/edit/"]')
    expect(edit).to_have_count(1)
    expect(edit.locator("[name=birth_date]")).to_have_count(0)
    expect(edit.locator("[data-datefield]")).to_have_count(0)
    # доп. 61: присланное `birth_date`, в том числе пустая строка, — отказ 200 с [role=alert]
    for value in ("01.01.1999", ""):  # изменить и стереть
        response = direct_post(admin_page, f"/staff/{owner.id}/edit/", {
            "full_name": f"Удалов{tag} Пётр Иванович", "position": "Инженер", "phone": "", "email": owner.email,
            "contacts": "", "internal_phone": "", "workplace": "", "birth_date": value})
        assert response.status == 200 and has_alert(response), f"прямой запрос с датой {value!r}: {response.status}"
    own.goto("/me/")
    expect(_own_card(own).locator('[data-field="birth_date"]')).to_contain_text("15.03.1961")

    # п. 7: администратор удаляет чужое фото; ссылка на него больше не отдаёт файл
    assert wait_photo_checked(own, "/me/", timeout=PHOTO_LIMIT) == "clean", "чистое фото не принято"
    old_src = _own_card(own).locator("img[data-photo-img]").first.get_attribute("src")
    assert direct_get(own, old_src).status == 200
    _colleague_card(other.page, owner.id)
    expect(other.page.locator(f'form[action="/staff/{owner.id}/photo/delete/"]')).to_have_count(0)  # у коллеги нет
    assert direct_post(other.page, f"/staff/{owner.id}/photo/delete/").status == 403

    _colleague_card(admin_page, owner.id)
    delete = admin_page.locator(f'form[action="/staff/{owner.id}/photo/delete/"]')
    expect(delete).to_have_count(1)
    with admin_page.expect_navigation():
        helpers.submit(delete)
    admin_page.wait_for_url(re.compile(rf"/staff/{owner.id}/$"))
    assert helpers.status_text(admin_page), "после удаления фото нет сообщения об успехе (доп. 51)"
    expect(admin_page.locator(f'[data-card][data-user-id="{owner.id}"] img[data-photo-img]')).to_have_count(0)
    own.goto("/me/")
    expect(_own_card(own).locator("[data-photo-placeholder]").first).to_be_visible()
    expect(_own_card(own).locator("img[data-photo-img]")).to_have_count(0)
    assert direct_get(own, old_src).status == 404, "удалённое фото всё ещё выдаётся"
    assert len(audit_rows(admin_page, "photo.deleted", owner.id)) == 1, "удаление фото не записано в журнал"


def test_o10_two_tabs(admin_page, employee):
    """Сценарий 10, п. 9: у карточки две вкладки «Профиль» и «Безопасность» — на своей странице и у администратора
    на чужой; по умолчанию открыт «Профиль»; пустые поля — «не заполнено» (FR-135)."""
    acc = employee(full_name=f"Вкладкин{secrets.token_hex(3)} Пётр Иванович")
    own = acc.page

    for who, page, url, security_hook in (
            ("своя карточка", own, "/me/", "[data-backup-remaining]"),
            ("администратор", admin_page, f"/staff/{acc.id}/", '[data-security-part="account"]')):
        page.goto(url)
        card = page.locator(f'[data-card][data-user-id="{acc.id}"]').first
        expect(card, who).to_be_visible()
        buttons = card.locator("[data-tab-button]")
        expect(buttons, who).to_have_count(2)  # вкладок ровно две
        profile = card.locator('[data-tab-button="profile"]')
        security = card.locator('[data-tab-button="security"]')
        for button, title in ((profile, "Профиль"), (security, "Безопасность")):
            expect(button, who).to_have_count(1)
            expect(button, who).to_have_attribute("role", "tab")
            expect(button, who).to_have_attribute("type", "button")
            expect(button, who).to_contain_text(title)
        # по умолчанию открыт «Профиль», панель «Безопасность» скрыта
        expect(profile, who).to_have_attribute("aria-selected", "true")
        expect(card.locator('[data-tab-panel="profile"]'), who).to_be_visible()
        expect(card.locator('[data-tab-panel="security"]'), who).to_be_hidden()
        # переключение на «Безопасность» и обратно
        security.click()
        expect(security, who).to_have_attribute("aria-selected", "true")
        expect(card.locator('[data-tab-panel="security"]'), who).to_be_visible()
        expect(card.locator(f'[data-tab-panel="security"] {security_hook}').first, who).to_be_attached()
        expect(card.locator('[data-tab-panel="profile"]'), who).to_be_hidden()
        profile.click()
        expect(profile, who).to_have_attribute("aria-selected", "true")
        expect(card.locator('[data-tab-panel="profile"]'), who).to_be_visible()
        expect(card.locator('[data-tab-panel="security"]'), who).to_be_hidden()

    # FR-135: у только что заведённого пустые поля показаны как «не заполнено»
    card = _colleague_card(admin_page, acc.id)
    for name in ("internal_phone", "workplace", "birth_date", "units"):
        field = card.locator(f'[data-field="{name}"]')
        expect(field, name).to_have_attribute("data-empty", "true")
        expect(field, name).to_contain_text("не заполнено")
    expect(card.locator('[data-field="head"]')).to_have_attribute("data-empty", "true")
    expect(card.locator('[data-field="head"]')).to_contain_text("не назначен")
