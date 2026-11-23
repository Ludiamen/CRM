"""Срез 010 «Поручения»: создание и основания (T-10103; FR-700…704).

`apps.instructions.services.instructions.create/update` и права постановки — CONTRACT-010, разделы 4–6, 12. Код
среза импортируется внутри тестов: сбор проходит до появления моделей и служб.
"""
import datetime

import pytest

from tests import support, support_org
from tests import support_instructions as ins

pytestmark = pytest.mark.django_db


def instructions():
    from apps.instructions.services import instructions as module
    return module


def errors():
    from apps.instructions import texts
    return texts


def _tree():
    return support_org.make_tree({"Отдел": {"Группа": {}}, "Чужой": {}})


def _people():
    tree = _tree()
    head = ins.head_of(tree["Отдел"])
    assignee = support.make_employee()
    support_org.make_member(assignee, tree["Группа"])
    return tree, head, assignee


def _data(**extra):
    _, _head, assignee = _people()
    base = {"title": "Проверить регламент", "text": "Текст поручения", "basis_kind": ins.make_basis(),
            "basis_number": "12-01", "basis_date": ins._today(), "assignee": assignee,
            "deadline": ins._today() + datetime.timedelta(days=14)}
    base.update(extra)
    return base


def _err(call):
    with pytest.raises(errors().InstructionsError) as caught:
        call()
    return caught.value


def test_create_saves_fields_controller_and_audit():
    """FR-700, FR-703: создание сохраняет поля, `original_deadline = deadline`, контролёр по умолчанию — автор;
    журнал `instructions.created` — номер, название, исполнитель, срок, основание."""
    tree, head, assignee = _people()
    data = _data()
    row = instructions().create(head, **data)

    assert row.pk and row.title == data["title"] and row.text == data["text"]
    assert row.basis_kind_id == data["basis_kind"].pk
    assert (row.basis_number, row.basis_date) == (data["basis_number"], data["basis_date"])
    assert (row.author_id, row.controller_id, row.assignee_id) == (head.pk, head.pk, assignee.pk)
    assert row.deadline == data["deadline"] and row.original_deadline == data["deadline"]
    assert row.ladder == {} and row.closed_at is None

    event = support.model("core.AuditEvent").objects.get(action="instructions.created",
                                                         object_id=str(row.pk))
    assert event.object_type == "instructions.instruction"
    for key in ("title", "assignee", "deadline", "basis"):
        assert key in event.after, key


def test_title_text_limits_and_required():
    """FR-700: название 1–300 (`title_range`), текст до 10 000 (`text_long`); отказ — `InstructionsError`
    с кодом и полем (CONTRACT-010, 12.1)."""
    _, head, _ = _people()
    for title in ("", "я" * 301):
        err = _err(lambda title=title: instructions().create(head, **_data(title=title)))
        assert (err.code, err.field) == ("title_range", "title")
    err = _err(lambda: instructions().create(head, **_data(text="я" * 10_001)))
    assert (err.code, err.field) == ("text_long", "text")


def test_basis_view_number_and_date_are_required_and_known():
    """FR-700, FR-701: основание обязательно — вид, номер и дата (`basis_required` у своего поля); неизвестный или
    выключенный вид — `basis_unknown`."""
    _, head, _ = _people()
    for field in ("basis_kind", "basis_number", "basis_date"):
        err = _err(lambda field=field: instructions().create(head, **_data(**{field: None if field != "basis_number" else ""})))
        assert (err.code, err.field) == ("basis_required", field)
    inactive = ins.make_basis("Письмо", active=False)
    err = _err(lambda: instructions().create(head, **_data(basis_kind=inactive)))
    assert (err.code, err.field) == ("basis_unknown", "basis_kind")


def test_deadline_required_and_not_in_past_but_today_allowed():
    """FR-700: срок обязателен (`deadline_required`), раньше сегодняшнего — `deadline_past`, сегодня — можно."""
    _, head, _ = _people()
    err = _err(lambda: instructions().create(head, **_data(deadline=None)))
    assert (err.code, err.field) == ("deadline_required", "deadline")
    err = _err(lambda: instructions().create(head, **_data(deadline=ins._today() - datetime.timedelta(days=1))))
    assert (err.code, err.field) == ("deadline_past", "deadline")
    row = instructions().create(head, **_data(deadline=ins._today()))
    assert row.deadline == ins._today()


def test_assignee_required_forbidden_and_dismissed():
    """FR-702, FR-704: исполнитель обязателен (`assignee_required`); ставить можно только подчинённому
    (`assignee_forbidden`); уволенному — `assignee_dismissed`."""
    tree, head, assignee = _people()
    err = _err(lambda: instructions().create(head, **_data(assignee=None)))
    assert (err.code, err.field) == ("assignee_required", "assignee")
    outsider = support.make_employee()
    support_org.make_member(outsider, tree["Чужой"])
    err = _err(lambda: instructions().create(head, **_data(assignee=outsider)))
    assert (err.code, err.field) == ("assignee_forbidden", "assignee")

    dismissed = support.make_employee(state="dismissed")
    support_org.make_member(dismissed, tree["Группа"])
    err = _err(lambda: instructions().create(head, **_data(assignee=dismissed)))
    assert (err.code, err.field) == ("assignee_dismissed", "assignee")


def test_members_duplicate_assignee_and_dismissed():
    """FR-704: соисполнители без повторов (`member_duplicate`), без исполнителя (`member_is_assignee`), только
    действующие (`member_dismissed`)."""
    tree, head, assignee = _people()
    peer = support.make_employee()
    support_org.make_member(peer, tree["Группа"])
    err = _err(lambda: instructions().create(head, **_data(members=(peer, peer))))
    assert (err.code, err.field) == ("member_duplicate", "members")
    err = _err(lambda: instructions().create(head, **_data(members=(assignee,))))
    assert (err.code, err.field) == ("member_is_assignee", "members")
    dismissed = support.make_employee(state="dismissed")
    support_org.make_member(dismissed, tree["Группа"])
    err = _err(lambda: instructions().create(head, **_data(members=(dismissed,))))
    assert (err.code, err.field) == ("member_dismissed", "members")


def test_controller_must_be_active_and_can_be_changed_by_author():
    """FR-703: контролёром можно назначить другого действующего сотрудника; уволенный — `controller_dismissed`;
    меняет контролёра автор с журналом `instructions.changed`."""
    _, head, assignee = _people()
    controller = ins.staff_user()
    row = instructions().create(head, **_data(controller=controller))
    assert row.controller_id == controller.pk
    dismissed = support.make_employee(state="dismissed")
    err = _err(lambda: instructions().create(head, **_data(controller=dismissed)))
    assert (err.code, err.field) == ("controller_dismissed", "controller")

    new_controller = ins.staff_user()
    instructions().update(head, row, controller=new_controller)
    row.refresh_from_db()
    assert row.controller_id == new_controller.pk
    event = support.model("core.AuditEvent").objects.get(action="instructions.changed",
                                                         object_id=str(row.pk))
    assert event.before["controller"] != event.after["controller"]


def test_update_refused_for_non_author_and_closed():
    """FR-700, FR-703: поля меняет автор (`edit_forbidden` у остальных); после снятия с контроля правка запрещена."""
    _, head, assignee = _people()
    row = instructions().create(head, **_data())
    err = _err(lambda: instructions().update(assignee, row, title="Новое"))
    assert (err.code, err.field) == ("edit_forbidden", "title")
    row.closed_at = _now()
    row.save(update_fields=["closed_at"])
    err = _err(lambda: instructions().update(head, row, title="Новое"))
    assert (err.code, err.field) == ("edit_forbidden", "title")


def _now():
    from django.utils import timezone

    return timezone.now()


def test_create_page_and_post_render_errors_and_redirect(client):
    """CONTRACT-010, 6.2: `GET /instructions/new/` — форма; успешный POST — 302 на карточку; отказ — 200 с
    `[data-error="title"][data-code="title_range"]`."""
    tree, head, assignee = _people()
    client.force_login(head)
    page = client.get("/instructions/new/")
    assert page.status_code == 200 and b'data-instructions-page="new"' in page.content

    data = _data(assignee=assignee)
    data.update({"basis_kind": data["basis_kind"].pk, "assignee": assignee.pk,
                 "basis_date": data["basis_date"].isoformat(), "deadline": data["deadline"].isoformat()})
    bad = client.post("/instructions/new/", {**data, "title": ""})
    assert bad.status_code == 200
    assert b'data-error="title"' in bad.content and b'data-code="title_range"' in bad.content

    good = client.post("/instructions/new/", data)
    row = support.model("instructions.Instruction").objects.get(title=data["title"])
    assert good.status_code == 302 and good["Location"] == f"/instructions/{row.pk}/"


def test_form_offers_only_managed_people_and_existing_basis_kinds(client):
    """FR-702, FR-701: форма создания показывает управляемых сотрудников и виды основания из справочника; чужие
    сотрудники в списке отсутствуют; новый вид доступен без правки кода."""
    tree, head, assignee = _people()
    outsider = support.make_employee()
    support_org.make_member(outsider, tree["Чужой"])
    kind = ins.make_basis("Протокол совещания", position=7)
    client.force_login(head)
    page = client.get("/instructions/new/")
    html = page.content.decode()
    assert f'value="{assignee.pk}"' in html and f'value="{outsider.pk}"' not in html
    assert kind.title in html


def test_texts_contain_every_contract_refusal():
    """CONTRACT-010, 12.1: словарь `TEXTS` содержит каждый код и текст; службы берут текст отсюда."""
    TEXTS = errors().TEXTS
    expected = {
        "title_range": "Название поручения — от 1 до 300 знаков",
        "text_long": "Текст поручения — не длиннее 10 000 знаков",
        "basis_required": "Основание обязательно: вид, номер и дата",
        "basis_unknown": "Такого вида основания нет в справочнике",
        "deadline_required": "Укажите срок исполнения",
        "deadline_past": "Срок не может быть раньше сегодняшнего дня",
        "assignee_required": "Выберите ответственного исполнителя",
        "assignee_forbidden": "Поставить поручение этому сотруднику нельзя",
        "assignee_dismissed": "Сотрудник уволен: поручение поставить нельзя",
        "controller_dismissed": "Сотрудник уволен: контролёром не назначить",
        "member_dismissed": "Сотрудник уволен: в соисполнители не добавить",
        "member_duplicate": "Этот сотрудник уже в составе поручения",
        "member_is_assignee": "Исполнитель уже назначен: в соисполнители его не указывают",
        "periodicity_invalid": "Периодичность — еженедельно, ежемесячно или ежеквартально",
        "date_past": "Отчётная дата не может быть в прошлом",
        "date_not_before_deadline": "Отчётная дата — раньше срока исполнения",
        "dates_locked": "Периодичность не сменить: по отчётным датам уже есть отчёты",
        "edit_forbidden": "Нет права менять поручение",
        "report_forbidden": "Отчёт пишет ответственный исполнитель поручения",
        "report_empty": "Напишите текст отчёта",
        "report_long": "Текст отчёта — не длиннее 10 000 знаков",
        "report_limit": "Не больше 10 файлов к отчёту или части",
        "report_closed": "Поручение снято с контроля: отчёты не принимаются",
        "report_date_unknown": "Такой отчётной даты в поручении нет",
        "part_forbidden": "Часть отчёта добавляет соисполнитель или ответственный",
        "part_duplicate": "Часть к этой дате уже добавлена",
        "decision_forbidden": "Принимает и возвращает отчёт только контролёр",
        "decision_state": "Отчёт уже рассмотрен",
        "return_comment_required": "Укажите причину возврата или отказа",
        "transfer_forbidden": "Перенос просит ответственный исполнитель",
        "transfer_state": "По поручению уже есть запрос переноса",
        "transfer_decided": "Запрос переноса уже рассмотрен",
        "transfer_deadline": "Новый срок — позже текущего",
        "transfer_reason": "Причина переноса — от 1 до 1 000 знаков",
        "transfer_closed": "Поручение снято с контроля: перенос не оформить",
        "close_forbidden": "Снять с контроля может только контролёр",
        "close_no_report": "Нужен принятый итоговый отчёт",
        "close_transfer_pending": "Сначала решите запрос переноса",
        "close_confirm": "Снять поручение с контроля?",
        "ladder_invalid": "Лестница: от 1 до 60 рабочих дней, по возрастанию, без повторов",
        "file_too_big": "Файл больше 20 МБ",
        "file_type": "Файл такого типа не принимается",
        "file_missing": "Файл не найден",
        "retention_range": "Срок хранения — от 1 до 10 лет",
        "retention_decrease": "Ближайшая уборка удалит поручений: {count}",
        "basis_title_range": "Название вида — от 1 до 100 знаков",
        "basis_title_taken": "Вид с таким названием уже есть",
        "basis_delete_confirm": "Удалить вид основания?",
        "task_forbidden": "Создать задачу можно с правом работы с задачами",
        "task_missing": "Задача не найдена или недоступна",
    }
    assert expected.items() <= TEXTS.items()