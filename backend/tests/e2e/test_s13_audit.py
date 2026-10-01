"""T-147: сценарий 13 — журнал событий (FR-044, FR-045, FR-046, FR-047, NFR-002)."""
import csv
import io
import secrets
import statistics
import time
from datetime import datetime

from playwright.sync_api import expect

from tests.e2e import helpers

ACCESS_PREFIXES = ("login.", "logout", "account.", "ip.", "totp.", "backup_code", "invitation.", "password.",
                   "link.", "sessions.", "user.")
NOT_ACCESS = ("role.", "security_settings.", "portal_settings.", "mail.")


def test_s13_presets_filters_sort_and_csv_export(admin_page, employee, new_context):
    """Сценарий 13, п. 1-6: пресет «Вход и доступ» оставляет события доступа; «Найти» обновляет только
    таблицу (фильтр остаётся тем же элементом) и отвечает быстро; в записи видно «было / стало», а паролей,
    секретов и резервных кодов нет; записи нельзя изменить или удалить; сотрудник без права получает отказ;
    «Выгрузить выбранное» отдаёт CSV с текущей выборкой (FR-044…FR-047)."""
    acc = employee()  # события входа, приглашения и активации
    helpers.sign_in(new_context().new_page(), acc)

    # роль для пресета «Права и роли»
    admin_page.goto("/roles/new/")
    form = admin_page.locator('form[action="/roles/new/"]')
    form.locator("[name=name]").fill(f"Журнал-{secrets.token_hex(3)}")
    form.locator('input[name=permissions][value="audit.view"]').check()
    form.locator("button[type=submit]").click()

    admin_page.goto("/audit/")
    expect(admin_page.locator("#audit-filter")).to_be_visible()
    admin_page.evaluate("document.querySelector('#audit-filter').dataset.mark = 'kept'")

    # п. 1: пресет «Вход и доступ»
    admin_page.locator('a[href*="preset=access"]').first.click()
    expect(admin_page.locator("tr[data-event-id]").first).to_be_visible()
    actions = [r.get_attribute("data-action") for r in admin_page.locator("tr[data-event-id]").all()]
    assert actions and all(a.startswith(ACCESS_PREFIXES) for a in actions), actions
    assert not [a for a in actions if a.startswith(NOT_ACCESS)]
    assert "login.success" in actions
    # п. 2: обновилась только таблица
    assert admin_page.evaluate("document.querySelector('#audit-filter').dataset.mark") == "kept"

    # п. 2: период и пользователь + «Найти»; быстрый ответ (NFR-002, 95 % — по 20 запросам)
    today = datetime.now().strftime("%Y-%m-%d")
    filt = admin_page.locator("#audit-filter")
    filt.locator("[name=date_from]").fill(today)
    filt.locator("[name=date_to]").fill(today)
    user_field = filt.locator("[name=user]")
    if user_field.evaluate("e => e.tagName") == "SELECT":
        user_field.select_option(acc.id)
    else:
        user_field.fill(acc.id)
    filt.get_by_role("button", name="Найти").click()
    expect(admin_page.locator("tr[data-event-id]").first).to_be_visible()
    assert admin_page.evaluate("document.querySelector('#audit-filter').dataset.mark") == "kept"
    timings = []
    for _ in range(20):
        t = time.monotonic()
        response = admin_page.request.get(f"/audit/?date_from={today}&date_to={today}&user={acc.id}",
                                          headers={"HX-Request": "true"})
        assert response.status == 200
        timings.append(time.monotonic() - t)
    assert sorted(timings)[int(len(timings) * 0.95) - 1] < 0.5, f"p95 журнала {statistics.quantiles(timings, n=20)[-1]:.2f} с"

    # сортировка по времени: по возрастанию и убыванию
    admin_page.goto("/audit/?sort=at")
    asc = [datetime.fromisoformat(r.get_attribute("data-at")) for r in admin_page.locator("tr[data-event-id]").all()]
    assert asc == sorted(asc)
    admin_page.goto("/audit/?sort=-at")
    desc = [datetime.fromisoformat(r.get_attribute("data-at")) for r in admin_page.locator("tr[data-event-id]").all()]
    assert desc == sorted(desc, reverse=True)

    # п. 3: «было / стало» видны; секретов нет
    admin_page.goto("/audit/?preset=roles")
    row = admin_page.locator("tr[data-event-id][data-action='role.created']").first
    expect(row).to_be_visible()
    page_text = admin_page.locator("body").inner_text().lower()
    assert "было" in page_text and "стало" in page_text
    text = helpers.audit_text(admin_page)
    secrets_ = [acc.password, acc.totp_secret.replace(" ", ""), acc.link and helpers.code_of(acc.link), *acc.backup_codes]
    assert not [s for s in secrets_ if s and s in text], "в журнале есть пароль, ключ, код ссылки или резервный код"

    # п. 4: изменить и удалить нельзя
    event_id = admin_page.locator("tr[data-event-id]").first.get_attribute("data-event-id")
    for verb in ("Удалить", "Изменить", "Редактировать"):
        assert admin_page.get_by_role("button", name=verb).count() == 0
    for method, path in (("post", f"/audit/{event_id}/delete/"), ("post", f"/audit/{event_id}/"),
                         ("delete", f"/audit/{event_id}/")):
        status = getattr(admin_page.request, method)(path, max_redirects=0).status
        assert status in (403, 404, 405), f"{method.upper()} {path} дал {status}"

    # п. 5: сотрудник без права просмотра
    assert acc.page.goto("/audit/").status == 403

    # п. 6: выгрузка текущей выборки
    admin_page.goto("/audit/?preset=roles")
    shown = admin_page.locator("tr[data-event-id]").count()
    with admin_page.expect_download() as info:
        admin_page.locator('a[href*="/audit/export.csv"]').first.click()
    download = info.value
    body = open(download.path(), encoding="utf-8-sig").read()
    rows = list(csv.reader(io.StringIO(body)))
    assert len(rows) - 1 >= shown >= 1, "в выгрузке меньше записей, чем в таблице выборки"
    assert all("role." in line for line in body.splitlines()[1:] if line.strip()), "выгрузка шире выбранного пресета"
