"""T-11305: ручной проход по стенду (Playwright, шаги как у человека).

Вход администратором, уровень с привязкой, заявки со сроками, просрочка и фильтр, отчёт и Excel,
вставка частого ответа, 360 px. Снимки экрана и итог — в crm-work/slice011/stage4/T-11305/.
Секреты читаются из /tmp/t11305/creds.txt и в отчёт не попадают.
"""
import json
import re
import shutil
import ssl
import time
from pathlib import Path

from django_otp.oath import TOTP
from playwright.sync_api import expect, sync_playwright

BASE = "https://127.0.0.1:8031"
OUT = Path("/home/gpgr/Документы/CRM/crm-work/slice011/stage4/T-11305")
SHOTS = OUT / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)
email, password, key = Path("/tmp/t11305/creds.txt").read_text().strip().split("|")
time.sleep(31)  # код TOTP не повторяется в одном 30-секундном шаге
result = {"steps": [], "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def step(name, ok, note=""):
    result["steps"].append({"step": name, "ok": bool(ok), "note": note})
    print(f"{'OK ' if ok else 'FAIL'} {name} {note}")


with sync_playwright() as p:
    browser = p.chromium.launch()
    context = browser.new_context(ignore_https_errors=True, viewport={"width": 1366, "height": 900},
                                  locale="ru-RU", timezone_id="Europe/Moscow")
    page = context.new_page()

    page.goto(f"{BASE}/login/")
    page.fill("input[name=email]", email)
    page.fill("input[name=password]", password)
    page.click("button[type=submit]")
    expect(page.locator("input[name=code]")).to_be_visible()
    page.fill("input[name=code]", str(TOTP(bytes.fromhex(key), step=30, digits=6).token()).zfill(6))
    page.click("button[type=submit]")
    expect(page.locator("#top-bar")).to_be_visible()
    step("вход администратора", True, page.locator("#top-bar").first.inner_text()[:60])

    # 1. Уровень с привязкой к категории
    page.goto(f"{BASE}/servicedesk/sla/new/")
    form = page.locator('[data-sla-page="new"]')
    expect(form).to_be_visible()
    form.locator('[data-sla-field="title"]').fill("Ручной проход")
    form.locator('[data-sla-field="priority"]').fill("5")
    form.locator('[data-sla-field="reaction_minutes"]').fill("30")
    form.locator('[data-sla-field="solution_minutes"]').fill("240")
    form.locator('[data-sla-field="workdays"]').select_option(["0", "1", "2", "3", "4"])
    category_values = [value for value in form.locator('[data-sla-field="category"] option').evaluate_all(
        "options => options.map(option => option.value)") if value]
    if category_values:
        form.locator('[data-sla-field="category"]').select_option([category_values[0]])
    with page.expect_response(lambda r: r.request.method == "POST") as posted:
        form.locator("button[type=submit]").click()
    response = posted.value
    page.wait_for_load_state()
    if response.status >= 400:
        page.screenshot(path=str(SHOTS / "01-sla-error.png"), full_page=True)
        step("уровень создан с привязкой", False, f"POST {response.status}: {page.content()[:300]}")
    row = page.locator('[data-sla-id]').filter(has_text="Ручной проход").first
    expect(row).to_be_visible()
    page.screenshot(path=str(SHOTS / "01-sla-created.png"), full_page=True)
    step("уровень создан с привязкой", True, row.inner_text().replace("\n", " ")[:80])

    # 2. Заявка со сроками: открываем наполнение и смотрим карточку
    page.goto(f"{BASE}/tickets/?preset=all")
    ticket_row = page.locator("tr", has_text="E2E SLA: в срок").first
    expect(ticket_row).to_be_visible()
    page.goto(BASE + ticket_row.locator('a[href^="/tickets/"]').first.get_attribute("href"))
    sla = page.locator("[data-sla]")
    expect(sla).to_be_visible()
    expect(sla.locator("[data-reaction-due]")).to_be_visible()
    expect(sla.locator("[data-solution-due]")).to_be_visible()
    page.screenshot(path=str(SHOTS / "02-card-deadlines.png"), full_page=True)
    step("карточка заявки со сроками", True, sla.inner_text().replace("\n", " ")[:100])

    # 3. Просрочка и фильтр
    page.goto(f"{BASE}/tickets/?due=overdue")
    rows = page.locator("tr", has_text="E2E SLA")
    count = rows.count()
    expect(page.locator('[data-due="overdue"]')).to_be_visible()
    page.screenshot(path=str(SHOTS / "03-overdue-filter.png"), full_page=True)
    step("фильтр просроченных", count >= 1, f"строк: {count}")

    # 4. Отчёт и Excel
    page.goto(f"{BASE}/servicedesk/reports/?period=month")
    expect(page.locator("[data-report-page]")).to_be_visible()
    created = page.locator('[data-report-row][data-key="created"]').inner_text()
    report = page.locator("[data-report-page]")
    report.screenshot(path=str(SHOTS / "04-report.png"))
    with page.expect_download() as download:
        page.locator("[data-report-export]").click()
    path = Path("/tmp/t11305/export.xlsx")
    shutil.copy(download.value.path(), path)
    size = path.stat().st_size
    from openpyxl import load_workbook

    book = load_workbook(path, read_only=True)
    sheets = book.sheetnames
    step("отчёт и Excel", size > 0 and set(sheets) == {"Показатели", "Заявки"},
         f"{created.replace(chr(10), ' ')}; файл {size} Б, листы {sheets}")

    # 5. Частый ответ
    page.goto(f"{BASE}/tickets/?preset=all")
    ticket_row = page.locator("tr", has_text="E2E SLA: в срок").first
    page.goto(BASE + ticket_row.locator('a[href^="/tickets/"]').first.get_attribute("href"))
    tools = page.locator("[data-answer-tools]").first
    if tools.count() == 0:
        print("DEBUG url", page.url, "tools", tools.count(), "answers", page.locator("[data-answer-select]").count())
        print(page.locator("main").first.inner_text()[:300])
    expect(tools).to_be_visible()
    select = tools.locator("[data-answer-select]")
    option = select.locator("option").nth(1).get_attribute("value")
    select.select_option(option)
    tools.locator("[data-answer-insert]").click()
    textarea = page.locator("textarea[name=text]").first
    expect(textarea).not_to_have_value("")
    page.screenshot(path=str(SHOTS / "05-answer-inserted.png"), full_page=True)
    step("вставка частого ответа", True, textarea.input_value()[:80])

    # 6. 360 px
    narrow = context.new_page()
    narrow.set_viewport_size({"width": 360, "height": 800})
    for url in ("/servicedesk/sla/", "/servicedesk/reports/?period=month", "/servicedesk/answers/",
                "/tickets/?preset=all"):
        narrow.goto(f"{BASE}{url}")
        narrow.wait_for_load_state()
        width = narrow.evaluate("Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)")
        inner = narrow.evaluate("window.innerWidth")
        expect(narrow.locator("body")).to_be_visible()
        ok = width <= inner + 1
        narrow.screenshot(path=str(SHOTS / f"06-360-{re.sub(r'[^a-z]+', '-', url.lower()).strip('-')}.png"),
                          full_page=False)
        step(f"360 px {url}", ok, f"ширина {width} при окне {inner}")

    context.close()
    browser.close()

result["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
(OUT / "walkthrough.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
failed = [s for s in result["steps"] if not s["ok"]]
print(f"итог: шагов {len(result['steps'])}, провалено {len(failed)}")
raise SystemExit(1 if failed else 0)
