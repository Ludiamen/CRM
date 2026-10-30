"""T-7142: сценарий 3 — событие, ответы, напоминание (FR-606, FR-611, FR-616, FR-617, FR-618, FR-619, FR-629, FR-630,
FR-642, NFR-606).

Общее для файла (шаблон e2e/template.md, CONTRACT-007.md, разделы 7.2, 10, 12, 13, 14.1, 14.4):
- люди и узлы круга — `helpers_feed.feed_cast` (один раз на круг браузера; сессии сохранены в
  `Account.storage_state`); приглашённый без активации (`_person`) остаётся участником события и годится для увольнения;
- время — Europe/Moscow (`_now`, поля `datetime-local`, К42); начало события при публикации берётся с запасом (часы
  вперёд), а к сроку напоминания событие подводит `helpers_feed.shift(N)`: напоминание — за час до начала, поэтому
  `shift` сдвигает на «запас минус час плюс минута», и начало остаётся в будущем (иначе по правилу простоя
  напоминания нет);
- `shift` сдвигает события ВСЕХ записей стенда и выполняет задание напоминаний; поэтому число `reminded` из его ответа
  не проверяется, а напоминания и приглашения ищутся по строкам «Моих уведомлений» (`helpers_feed.my_notifications`) с
  уникальным названием события; тексты видов — раздел 7.2 контракта («Через час: «<название>»», «<ФИО> приглашает на
  событие «<название>»», «Событие «<название>» изменено», «упомянул(а) вас»);
- допуск 5 минут у напоминания — серверные тесты T-7114 (решение 56 задач): здесь только «пришло после сдвига к сроку»;
- локальные помощники файла: `_edit_event` (правка записи `/feed/<id>/edit/`, поля раздела 10.2; форма — первая
  форма `[data-feed-page="edit"]`, кнопка — первая `button[type=submit]`), `_dismiss`, `_wait_note`, `_novalidate`;
- локаторы — раздел 12 контракта, тексты отказов — раздел 13.
"""
import re
import secrets
import types
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers, helpers_feed, helpers_org

_CASTS: dict = {}
PLACE = "Корпус 2, ауд. 101"


# --- Общие помощники файла -----------------------------------------------------------------------------------------

def _now() -> datetime:
    """Московское «сейчас» без секунд и пояса: так значения заполняют поля `datetime-local`."""
    return datetime.now(ZoneInfo("Europe/Moscow")).replace(second=0, microsecond=0, tzinfo=None)


def _dt(minutes: int) -> datetime:
    return _now() + timedelta(minutes=minutes)


def _word() -> str:
    return "".join(secrets.choice("абвгдежзиклмнопрстуф") for _ in range(10))


def _title() -> str:
    return "Событие " + _word()


def _event(title: str, start: int = 180, length: int = 120, place: str = PLACE) -> dict:
    """Поля события: начало через `start` минут, длительность `length` минут."""
    return {"title": title, "place": place, "start": _dt(start), "end": _dt(start + length)}


def _token() -> str:
    return helpers_org.unique_name("к")[2:]


def _unit_name(page, unit_id) -> str:
    helpers_org.open_structure(page, unit_id)
    return helpers_org.unit_link(page, unit_id).inner_text().strip().splitlines()[0].strip()


def _dismiss(page, user_id) -> None:
    """Увольнение из карточки (образец — test_o07_dismiss)."""
    page.goto(f"/staff/{user_id}/")
    page.locator('[data-action="dismiss"]').first.click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(page.locator("[data-dismissed-badge]").first).to_be_visible()


def _person(admin_page, surname: str, token: str) -> tuple:
    name = f"{surname}{token} Иван Иванович"
    return helpers.create_employee(admin_page, factories.new_email("emp"), full_name=name), name


def _open(new_context, account):
    return helpers_feed.open_feed(new_context(), account)


def _notes(page, *markers) -> list:
    return [t for t in helpers_feed.my_notifications(page) if all(m in t for m in markers)]


def _wait_note(page, *markers, count: int = 1, timeout: int = 30_000) -> list:
    """Ждёт в «Моих уведомлениях» не меньше `count` строк со всеми `markers`; возвращает их."""
    deadline = datetime.now().timestamp() + timeout / 1000
    while True:
        found = _notes(page, *markers)
        if len(found) >= count or datetime.now().timestamp() > deadline:
            assert len(found) >= count, f"в «Моих уведомлениях» строк с {markers}: {len(found)}, нужно {count}"
            return found
        page.wait_for_timeout(1_000)


def _reminders(page, title: str) -> list:
    return _notes(page, "Через час", title)


def _novalidate(page) -> None:
    """Проверку полей форм браузером отключаем: нужен ответ сервера с причиной у поля, а не подсказка браузера."""
    page.evaluate("() => { document.querySelectorAll('form#feed-form').forEach(f => { f.noValidate = true; }); }")


def _set_dt(field, value: datetime) -> None:
    kind = (field.get_attribute("type") or "text").lower()
    field.fill(value.strftime("%Y-%m-%dT%H:%M") if kind == "datetime-local" else value.strftime("%d.%m.%Y %H:%M"))


def _pick_to(page, form, label: str) -> None:
    field = form.locator('input[data-feed-picker="to"]')
    pills = form.locator("[data-to-pill]")
    before = pills.count()
    field.fill("")
    field.press_sequentially(label.split()[0], delay=30)
    option = page.locator(f'[data-feed-pick-list] [data-pick-label="{label}"]').first
    expect(option).to_be_visible(timeout=10_000)
    option.click()
    expect(pills).to_have_count(before + 1)


def _edit_event(page, post_id, *, title=None, place=None, start=None, end=None, text=None, to=(), mention=None) -> list:
    """Правка записи-события автором: `/feed/<id>/edit/`; возвращает коды отказов из ответа (пусто — сохранено)."""
    page.goto(f"/feed/{post_id}/edit/")
    page.wait_for_load_state()
    expect(page.locator('[data-feed-page="edit"]')).to_be_visible()
    form = page.locator('[data-feed-page="edit"] form').first
    form.evaluate("f => { f.noValidate = true; }")
    for name, value in (("event_title", title), ("event_place", place)):
        if value is not None:
            form.locator(f'[name="{name}"]').fill(value)
    for name, value in (("event_start", start), ("event_end", end)):
        if value is not None:
            _set_dt(form.locator(f'[name="{name}"]'), value)
    body = form.locator('textarea[name="text"]')
    if text is not None:
        body.fill(text)
    for label in to:
        _pick_to(page, form, label)
    if mention:
        body.click()
        body.press("End")
        helpers_feed.pick_mention(page, body, mention.split()[0], mention)
    with page.expect_response(lambda r: r.request.method == "POST" and f"/feed/{post_id}/edit/" in r.url) as info:
        form.locator("button[type=submit]").first.click()
    codes = re.findall(r'data-code="([^"]*)"', info.value.text())
    page.wait_for_load_state()
    return codes


def _block(page, post_id):
    return page.locator(f"#feed-post-{post_id}-event")


def _answer_buttons(page, post_id):
    return _block(page, post_id).locator('button[data-action="answer"]')


def _count(page, post_id, value: str):
    return _block(page, post_id).locator(f'[data-feed-answers-count="{value}"]')


def _digit(number: int) -> re.Pattern:
    return re.compile(rf"(^|\D){number}(\D|$)")


def _open_answers(page, post_id):
    """Автор нажимает ссылку списков ответов; возвращает фрагмент `[data-feed-list="answers"]`."""
    _block(page, post_id).locator("a[data-feed-answers-link]").first.click()
    lists = page.locator('[data-feed-list="answers"]')
    expect(lists).to_be_visible()
    return lists


@pytest.fixture
def cast(admin_page, mailpit, new_context, stand_admin):
    """Круг людей и узлов сценариев (`feed_cast`), один на круг браузера."""
    found = _CASTS.get(stand_admin.email)
    if found is None:
        base = helpers_feed.feed_cast(admin_page, mailpit, new_context)
        for account in (base.writer, base.moderator, base.plain, base.it_member, base.net_member, base.part_timer,
                        base.accountant, base.petrov, base.sidorov):
            account.storage_state = account.page.context.storage_state()
            account.page = None
        found = types.SimpleNamespace(**base._asdict())
        found.it_name = _unit_name(admin_page, base.it_unit)
        found.net_name = _unit_name(admin_page, base.net_unit)
        found.acc_name = _unit_name(admin_page, base.accounting_unit)
        _CASTS[stand_admin.email] = found
    return found


# --- Тесты ---------------------------------------------------------------------------------------------------------

def test_f03_event_with_title_start_end_place_and_unit_published_with_event_block_and_go_and_cant_buttons_for_participants(
        new_context, cast):
    """П. 1: событие «Переезд серверной», начало завтра 10:00, конец 12:00, место «Корпус 2, ауд. 101», адресат
    «Отдел ИТ» — запись с блоком события; у участников кнопки «Пойду» и «Не смогу» (FR-616, FR-617)."""
    tomorrow = _now() + timedelta(days=1)
    start, end = tomorrow.replace(hour=10, minute=0), tomorrow.replace(hour=12, minute=0)
    title = "Переезд серверной " + _word()
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "", kind="event", to=[("unit", cast.it_name)],
                                   event={"title": title, "place": PLACE, "start": start, "end": end})
    block = _block(page, post_id)
    expect(block).to_contain_text(title)
    expect(block).to_contain_text(PLACE)
    expect(block.locator("time[data-at]").first).to_have_text(start.strftime("%d.%m.%Y %H:%M"))
    expect(block.locator("time[data-at]").nth(1)).to_have_text(end.strftime("%d.%m.%Y %H:%M"))
    expect(_answer_buttons(page, post_id)).to_have_count(0)  # у автора кнопок нет
    tab = _open(new_context, cast.it_member)
    expect(_block(tab, post_id)).to_contain_text(title)
    expect(_block(tab, post_id).locator('button[data-action="answer"][value="go"]')).to_have_text("Пойду")
    expect(_block(tab, post_id).locator('button[data-action="answer"][value="no"]')).to_have_text("Не смогу")


def test_f03_end_not_after_start_past_start_empty_or_over_200_title_refused_with_reason_at_field(new_context, cast):
    """П. 2: конец раньше начала или равен ему, начало в прошлом, пустое название и название длиннее 200 знаков — отказ
    с причиной у поля (FR-616, FR-642)."""
    page = _open(new_context, cast.writer)
    before = helpers_feed.post_ids(page)
    start = 180
    cases = (
        ({**_event(_title(), start), "end": _dt(start)}, "event_end", "event_end_before_start", "Конец должен быть позже начала"),
        ({**_event(_title(), start), "end": _dt(start - 30)}, "event_end", "event_end_before_start", "Конец должен быть позже начала"),
        (_event(_title(), -60, 120), "event_start", "event_start_passed", "Начало уже прошло"),
        (_event("", start), "event_title", "event_title_required", "Укажите название события"),
        (_event("я" * 201, start), "event_title", "too_long", "Предел: 200 знаков"),
    )
    for event, field, code, text in cases:
        _novalidate(page)
        codes = helpers_feed.try_publish(page, "", kind="event", event=event)
        assert (field, code) in codes, (code, codes)
        expect(page.locator(f'[data-error="{field}"][data-code="{code}"]')).to_contain_text(text)
    assert helpers_feed.post_ids(page) == before


def test_f03_empty_or_over_200_place_refused_with_reason_at_place_field(new_context, cast):
    """П. 11: пустое место или место длиннее 200 знаков — отказ с причиной у поля места (FR-616, FR-642)."""
    page = _open(new_context, cast.writer)
    before = helpers_feed.post_ids(page)
    for place, code, text in (("", "event_place_required", "Укажите место события"),
                              ("м" * 201, "too_long", "Предел: 200 знаков")):
        _novalidate(page)
        codes = helpers_feed.try_publish(page, "", kind="event", event=_event(_title(), 180, place=place))
        assert ("event_place", code) in codes, (code, codes)
        expect(page.locator(f'[data-error="event_place"][data-code="{code}"]')).to_contain_text(text)
    assert helpers_feed.post_ids(page) == before


def test_f03_participant_changes_go_to_cant_before_start(new_context, cast):
    """П. 3: участник ответил «Пойду», передумал до начала и нажал «Не смогу» — ответ сменился (FR-617)."""
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "", kind="event", to=[("unit", cast.it_name)], event=_event(_title()))
    tab = _open(new_context, cast.it_member)
    helpers_feed.answer(tab, post_id, "go")
    expect(_count(tab, post_id, "go")).to_contain_text(_digit(1))
    expect(_count(tab, post_id, "no")).to_contain_text(_digit(0))
    helpers_feed.answer(tab, post_id, "no")
    expect(_count(tab, post_id, "go")).to_contain_text(_digit(0))
    expect(_count(tab, post_id, "no")).to_contain_text(_digit(1))
    tab.reload()
    tab.wait_for_load_state()
    expect(_count(tab, post_id, "no")).to_contain_text(_digit(1))


def test_f03_author_sees_go_cant_and_no_answer_lists_and_other_viewers_see_only_numbers(new_context, cast):
    """П. 3: автор видит списки «Пойдут», «Не смогут», «Не ответили», остальные — только числа (FR-617)."""
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "", kind="event", to=[("unit", cast.it_name)], event=_event(_title()))
    helpers_feed.answer(_open(new_context, cast.it_member), post_id, "go")
    helpers_feed.answer(_open(new_context, cast.net_member), post_id, "no")
    viewer = _open(new_context, cast.part_timer)
    expect(_count(viewer, post_id, "go")).to_contain_text(_digit(1))
    expect(_count(viewer, post_id, "no")).to_contain_text(_digit(1))
    expect(_block(viewer, post_id).locator("a[data-feed-answers-link]")).to_have_count(0)
    assert helpers_org.direct_get(viewer, f"/feed/{post_id}/answers/").status == 403
    page.reload()
    page.wait_for_load_state()
    lists = _open_answers(page, post_id)
    expect(lists.locator('[data-feed-answers="go"]')).to_contain_text(cast.it_member.full_name)
    expect(lists.locator('[data-feed-answers="no"]')).to_contain_text(cast.net_member.full_name)
    expect(lists.locator('[data-feed-answers="none"]')).to_contain_text(cast.part_timer.full_name)
    expect(lists.locator('[data-feed-answers="none"]')).not_to_contain_text(cast.it_member.full_name)


def test_f03_shift_to_hour_before_start_gives_one_event_reminder_to_participants_except_cant_answers(
        new_context, cast):
    """П. 4: за час до начала участники, кроме ответивших «Не смогу», получают одно напоминание «Напоминание о
    событии» (FR-618, FR-629)."""
    title = _title()
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "", kind="event", to=[("unit", cast.it_name)], event=_event(title, 180))
    going, cant, silent = (_open(new_context, cast.it_member), _open(new_context, cast.net_member),
                           _open(new_context, cast.part_timer))
    helpers_feed.answer(going, post_id, "go")
    helpers_feed.answer(cant, post_id, "no")
    assert _reminders(going, title) == [], "напоминание пришло раньше срока"
    helpers_feed.shift(121)
    assert len(_wait_note(going, "Через час", title)) == 1
    assert len(_wait_note(silent, "Через час", title)) == 1
    assert _reminders(cant, title) == [], "напоминание получил ответивший «Не смогу»"
    helpers_feed.shift(1)  # повторный проход задания второго напоминания не даёт
    assert len(_reminders(going, title)) == 1 and len(_reminders(silent, title)) == 1


def test_f03_start_moved_later_gives_event_changed_and_reminder_at_hour_before_new_start_not_old(new_context, cast):
    """П. 5: автор перенёс начало позже — участники получают «Событие изменено», а напоминание приходит за час до
    нового начала, а не прежнего (FR-619, FR-629)."""
    title = _title()
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "", kind="event", to=[("unit", cast.it_name)], event=_event(title, 180))
    tab = _open(new_context, cast.it_member)
    assert _edit_event(page, post_id, start=_dt(360), end=_dt(480)) == []
    _wait_note(tab, f"Событие «{title}» изменено")
    helpers_feed.shift(121)  # срок прежнего напоминания наступил
    assert _reminders(tab, title) == [], "напоминание пришло за час до прежнего начала"
    helpers_feed.shift(181)  # срок нового напоминания наступил
    assert len(_wait_note(tab, "Через час", title)) == 1


def test_f03_started_event_has_no_answer_buttons_and_direct_answer_request_refused_with_answers_closed(
        new_context, cast):
    """П. 6: событие началось — кнопок ответа нет; ответ запросом в обход страницы отклонён «Ответы закрыты: событие
    началось» (FR-617, FR-642)."""
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "", kind="event", to=[("unit", cast.it_name)], event=_event(_title(), 120))
    tab = _open(new_context, cast.it_member)
    expect(_answer_buttons(tab, post_id)).to_have_count(2)
    helpers_feed.shift(150)
    tab.reload()
    tab.wait_for_load_state()
    expect(_answer_buttons(tab, post_id)).to_have_count(0)
    response = helpers_org.direct_post(tab, f"/feed/{post_id}/answer/", {"answer": "go"})
    assert response.status == 200, response.status
    body = response.text()
    assert 'data-code="answers_closed"' in body and "Ответы закрыты: событие началось" in body, body[:300]


def test_f03_non_participant_gets_nothing_at_reminder_time(new_context, cast):
    """П. 7: сотруднику, который не участник события и не видит запись, в срок напоминания ничего не приходит
    (FR-606, FR-618)."""
    title = _title()
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "", kind="event", to=[("unit", cast.it_name)], event=_event(title, 180))
    outsider = _open(new_context, cast.accountant)
    expect(outsider.locator(f"#feed-post-{post_id}")).to_have_count(0)
    helpers_feed.shift(121)
    insider = _open(new_context, cast.it_member)
    _wait_note(insider, "Через час", title)
    assert _notes(outsider, title) == [], "не участнику пришло уведомление о событии"
    assert helpers_org.direct_get(outsider, f"/feed/{post_id}/").status == 404


def test_f03_author_without_answer_buttons_always_gets_reminder(new_context, cast):
    """П. 8: в срок напоминания автор события получает его всегда, хотя кнопок ответа у него нет (FR-617, FR-618)."""
    title = _title()
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "", kind="event", to=[("person", cast.it_member.full_name)],
                                   event=_event(title, 180))
    expect(_answer_buttons(page, post_id)).to_have_count(0)
    helpers_feed.answer(_open(new_context, cast.it_member), post_id, "no")
    helpers_feed.shift(121)
    assert len(_wait_note(page, "Через час", title)) == 1
    assert _reminders(_open(new_context, cast.it_member), title) == []  # ответивший «Не смогу» — без напоминания


def test_f03_petrov_added_by_edit_gets_invitation_sidorov_mentioned_gets_you_were_mentioned_and_both_answer_and_get_reminder(
        new_context, cast):
    """П. 9: автор правкой добавляет в «Кому» Петрова, а в описании упоминает Сидорова — Петров получает «Приглашение на
    событие», Сидоров — «Вас упомянули»; оба могут ответить и получат напоминание (FR-611, FR-618, FR-629, FR-630)."""
    title = _title()
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "", kind="event", to=[("unit", cast.it_name)], event=_event(title, 180))
    petrov, sidorov = _open(new_context, cast.petrov), _open(new_context, cast.sidorov)
    assert _notes(petrov, title) == [] and _notes(sidorov, title) == []
    assert _edit_event(page, post_id, text="Описание события: ", to=[cast.petrov.full_name],
                       mention=cast.sidorov.full_name) == []
    _wait_note(petrov, "приглашает на событие", title)
    _wait_note(sidorov, "упомянул(а) вас")
    for tab in (_open(new_context, cast.petrov), _open(new_context, cast.sidorov)):
        expect(_answer_buttons(tab, post_id)).to_have_count(2)
        helpers_feed.answer(tab, post_id, "go")
    helpers_feed.shift(121)
    assert len(_wait_note(petrov, "Через час", title)) == 1
    assert len(_wait_note(sidorov, "Через час", title)) == 1


def test_f03_moderator_participant_sees_only_go_and_cant_numbers_without_lists(new_context, cast):
    """П. 10: модератор ленты — участник события: видит только числа «Пойдут» и «Не смогут», списки видит только автор
    (FR-617)."""
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "", kind="event", event=_event(_title()),
                                   to=[("person", cast.moderator.full_name), ("person", cast.it_member.full_name)])
    helpers_feed.answer(_open(new_context, cast.it_member), post_id, "go")
    tab = _open(new_context, cast.moderator)
    expect(_count(tab, post_id, "go")).to_contain_text(_digit(1))
    expect(_count(tab, post_id, "no")).to_contain_text(_digit(0))
    expect(_block(tab, post_id).locator("a[data-feed-answers-link]")).to_have_count(0)
    assert helpers_org.direct_get(tab, f"/feed/{post_id}/answers/").status == 403


def test_f03_event_published_half_hour_before_start_gives_invitation_only_and_no_reminder(new_context, cast):
    """П. 12: событие опубликовано за полчаса до начала — участники получили только приглашение, напоминания нет
    (FR-618)."""
    title = _title()
    page = _open(new_context, cast.writer)
    helpers_feed.publish(page, "", kind="event", to=[("unit", cast.it_name)], event=_event(title, 30, 60))
    tab = _open(new_context, cast.it_member)
    _wait_note(tab, "приглашает на событие", title)
    helpers_feed.shift(31)  # наступило начало
    assert _reminders(tab, title) == [], "напоминание пришло у события, опубликованного менее чем за час"
    assert len(_notes(tab, "приглашает на событие", title)) == 1


def test_f03_event_starting_in_a_day_gives_reminder_once_shifted_to_reminder_time(new_context, cast):
    """П. 12: у события с началом через сутки напоминание приходит после сдвига к сроку напоминания (FR-618). Допуск
    5 минут проверяет серверный T-7114."""
    title = _title()
    page = _open(new_context, cast.writer)
    helpers_feed.publish(page, "", kind="event", to=[("unit", cast.it_name)], event=_event(title, 1450, 60))
    tab = _open(new_context, cast.it_member)
    _wait_note(tab, "приглашает на событие", title)
    assert _reminders(tab, title) == []
    helpers_feed.shift(1400)  # remind_at (за 1390 мин до сдвига) наступил, начало ещё впереди
    assert len(_wait_note(tab, "Через час", title)) == 1


def test_f03_start_moved_two_hours_later_after_sent_reminder_gives_event_changed_and_new_reminder(new_context, cast):
    """П. 13: напоминание уже пришло, автор переносит начало на два часа позже — участники получают «Событие
    изменено» и новое напоминание (FR-619)."""
    title = _title()
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "", kind="event", to=[("unit", cast.it_name)], event=_event(title, 180))
    tab = _open(new_context, cast.it_member)
    helpers_feed.shift(121)
    assert len(_wait_note(tab, "Через час", title)) == 1
    start = _dt(59) + timedelta(hours=2)  # текущее начало после сдвига — через 59 минут; переносим на два часа позже
    assert _edit_event(page, post_id, start=start, end=start + timedelta(hours=2)) == []
    _wait_note(tab, f"Событие «{title}» изменено")
    helpers_feed.shift(121)
    assert len(_wait_note(tab, "Через час", title, count=2)) == 2


def test_f03_title_or_description_edit_gives_no_notifications(new_context, cast):
    """П. 13: правка только названия или описания уведомлений не даёт (FR-619)."""
    title, new_title = _title(), _title()
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "Описание", kind="event", to=[("unit", cast.it_name)], event=_event(title))
    tab = _open(new_context, cast.it_member)
    _wait_note(tab, "приглашает на событие", title)
    before = _notes(tab, title)
    assert _edit_event(page, post_id, title=new_title, text="Новое описание") == []
    page.goto(f"/feed/{post_id}/")
    expect(page.locator(f"#feed-post-{post_id}-event")).to_contain_text(new_title)
    tab.wait_for_timeout(3_000)  # уведомления создаются в транзакции правки: через несколько секунд их бы уже видели
    assert _notes(tab, new_title) == [], "правка названия дала уведомление"
    assert _notes(tab, "изменено", title) == []
    assert _notes(tab, title) == before


def test_f03_edit_with_past_start_refused_with_start_already_passed(new_context, cast):
    """П. 13: при правке начало в прошлом — отказ «Начало уже прошло» (FR-619, FR-642)."""
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "", kind="event", to=[("unit", cast.it_name)], event=_event(_title()))
    codes = _edit_event(page, post_id, start=_dt(-60), end=_dt(60))
    assert "event_start_passed" in codes, codes
    expect(page.locator('[data-error="event_start"][data-code="event_start_passed"]')).to_contain_text("Начало уже прошло")


def test_f03_started_event_refuses_start_end_place_change_and_changes_title_and_description_without_notifications(
        new_context, cast):
    """П. 13: у начавшегося события начало, конец и место изменить нельзя, а название и описание меняются без
    уведомлений (FR-619, FR-642)."""
    title, new_title = _title(), _title()
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "Описание", kind="event", to=[("unit", cast.it_name)],
                                   event=_event(title, 120, 120))
    tab = _open(new_context, cast.it_member)
    helpers_feed.shift(150)  # событие началось, ещё не закончилось
    for kwargs in ({"place": "Новое место " + _word()}, {"start": _dt(60), "end": _dt(180)}):
        codes = _edit_event(page, post_id, **kwargs)
        assert "event_started" in codes, (kwargs, codes)
        expect(page.locator('[data-code="event_started"]').first).to_contain_text(
            "Событие началось: время и место не меняются")
    before = _notes(tab, title)
    assert _edit_event(page, post_id, title=new_title, text="Описание уточнено") == []
    page.goto(f"/feed/{post_id}/")
    expect(page.locator(f"#feed-post-{post_id}-event")).to_contain_text(new_title)
    tab.wait_for_timeout(3_000)
    assert _notes(tab, new_title) == [] and _notes(tab, "изменено", title) == []
    assert _notes(tab, title) == before


def test_f03_dismissed_participant_absent_from_no_answer_list(admin_page, new_context, cast):
    """П. 14: участник события уволен — его нет в «Не ответили» (FR-617)."""
    token = _token()
    leaver_id, leaver_name = _person(admin_page, "Уволенов", token)
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "", kind="event", event=_event(_title()),
                                   to=[("person", cast.it_member.full_name), ("person", leaver_name)])
    page.reload()
    page.wait_for_load_state()
    assert leaver_name in _open_answers(page, post_id).locator('[data-feed-answers="none"]').inner_text()
    _dismiss(admin_page, leaver_id)
    card = helpers_feed.open_card(new_context(), cast.writer, post_id)
    lists = _open_answers(card, post_id)
    expect(lists.locator('[data-feed-answers="none"]')).to_contain_text(cast.it_member.full_name)
    expect(lists).not_to_contain_text(leaver_name)


def test_f03_event_block_and_answer_lists_have_no_horizontal_scroll_at_360px(new_context, cast):
    """Блок события и списки ответов на ширине 360 px — без горизонтальной прокрутки (NFR-606)."""
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "", kind="event", to=[("unit", cast.it_name), ("unit", cast.acc_name)],
                                   event=_event("Длинное название " + "ж" * 80, 180, place="Место " + "м" * 80))
    helpers_feed.answer(_open(new_context, cast.it_member), post_id, "go")
    tab = _open(new_context, cast.accountant)
    expect(_block(tab, post_id)).to_be_visible()
    assert helpers_feed.check_360(tab)
    page.reload()
    page.wait_for_load_state()
    _open_answers(page, post_id)
    assert helpers_feed.check_360(page)
