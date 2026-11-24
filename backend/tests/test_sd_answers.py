"""Красные серверные тесты частых ответов (T-11110, FR-751…754)."""

import pytest

from tests import support
from tests import support_org as org
from tests import support_servicedesk as sd


pytestmark = pytest.mark.django_db


def _member(queue, *permissions):
    user = support.make_with_permissions(*permissions)
    org.make_member(user, queue.unit)
    return user


def _body(response):
    return response.content.decode("utf-8", "replace")


def test_answers_list_is_available_to_service_desk_participant_and_shows_requests_menu():
    queue = sd.make_queue()
    participant = _member(queue)

    response = support.logged_in(participant).get("/servicedesk/answers/")

    assert response.status_code == 200
    assert 'data-answer-page="list"' in _body(response)
    assert "Заявки" in _body(response)


def test_personal_answer_is_visible_only_to_its_owner():
    queue = sd.make_queue()
    owner = _member(queue)
    other = _member(queue)
    answer = sd.make_answer(owner=owner, title="Только мне")

    owner_response = support.logged_in(owner).get("/servicedesk/answers/")
    other_response = support.logged_in(other).get("/servicedesk/answers/")

    assert owner_response.status_code == 200
    assert answer.title in _body(owner_response)
    assert other_response.status_code == 200
    assert answer.title not in _body(other_response)


def test_common_answer_is_visible_to_all_participants_but_not_to_outsider():
    queue = sd.make_queue()
    participant = _member(queue)
    outsider = support.make_employee()
    answer = sd.make_answer(title="Общий ответ")

    participant_response = support.logged_in(participant).get("/servicedesk/answers/")
    outsider_response = support.logged_in(outsider).get("/servicedesk/answers/")

    assert participant_response.status_code == 200
    assert answer.title in _body(participant_response)
    assert outsider_response.status_code == 403


def test_common_answer_creation_requires_servicedesk_answers_permission():
    queue = sd.make_queue()
    participant = _member(queue)
    holder = _member(queue, "servicedesk.answers")

    denied = support.logged_in(participant).post(
        "/servicedesk/answers/new/",
        {"title": "Общий", "text": "Текст", "kind": "common"},
    )
    allowed = support.logged_in(holder).post(
        "/servicedesk/answers/new/",
        {"title": "Общий держателя", "text": "Текст", "kind": "common"},
    )

    assert denied.status_code == 403
    assert allowed.status_code in (200, 302)


def test_participant_creates_personal_answer_but_category_is_rejected():
    queue = sd.make_queue()
    participant = _member(queue)
    category = sd.make_category(queue=queue)

    response = support.logged_in(participant).post(
        "/servicedesk/answers/new/",
        {"title": "Личный", "text": "Текст", "category": category.pk},
    )

    body = _body(response)
    assert response.status_code == 400
    assert 'data-error="category"' in body
    assert 'data-code="answer_category_personal"' in body


def test_answer_title_and_text_ranges_return_contract_error_codes():
    queue = sd.make_queue()
    participant = _member(queue)

    title_response = support.logged_in(participant).post(
        "/servicedesk/answers/new/",
        {"title": "", "text": "Текст"},
    )
    text_response = support.logged_in(participant).post(
        "/servicedesk/answers/new/",
        {"title": "Корректное название", "text": ""},
    )

    assert title_response.status_code == 400
    assert 'data-error="title"' in _body(title_response)
    assert 'data-code="answer_title_range"' in _body(title_response)
    assert text_response.status_code == 400
    assert 'data-error="text"' in _body(text_response)
    assert 'data-code="answer_text_range"' in _body(text_response)


def test_archived_answer_is_absent_from_suggestions_but_present_in_archive():
    queue = sd.make_queue()
    participant = _member(queue)
    active = sd.make_answer(title="Действующий")
    archived = sd.make_answer(title="Архивный", archived=True)

    response = support.logged_in(participant).get("/servicedesk/answers/")

    body = _body(response)
    assert response.status_code == 200
    assert active.title in body
    assert archived.title in body
    assert f'data-answer-id="{archived.pk}"' in body
    assert "архив" in body.lower()
    assert archived.title not in body.split("архив", 1)[0]


def test_owner_and_answers_holder_can_archive_and_restore_answer():
    queue = sd.make_queue()
    owner = _member(queue)
    holder = _member(queue, "servicedesk.answers")
    answer = sd.make_answer(owner=owner, title="Архивируемый")

    archive = support.logged_in(owner).post(
        f"/servicedesk/answers/{answer.pk}/archive/", {}
    )
    answer.refresh_from_db()
    archived_state = answer.archived
    restore = support.logged_in(holder).post(
        f"/servicedesk/answers/{answer.pk}/archive/", {}
    )
    answer.refresh_from_db()

    assert archive.status_code in (200, 302)
    assert archived_state is True
    assert restore.status_code in (200, 302)
    assert answer.archived is False


def test_insert_returns_answer_text_only_when_user_can_work_on_ticket():
    queue = sd.make_queue()
    participant = _member(queue)
    outsider = support.make_employee()
    ticket = sd.make_ticket(queue=queue)
    answer = sd.make_answer(owner=participant, text="Текст для textarea")
    client = support.logged_in(participant)

    inserted = client.get(
        f"/servicedesk/answers/{answer.pk}/insert/?ticket={ticket.number}"
    )
    denied = support.logged_in(outsider).get(
        f"/servicedesk/answers/{answer.pk}/insert/?ticket={ticket.number}"
    )

    assert inserted.status_code == 200
    assert _body(inserted).strip() == answer.text
    assert denied.status_code == 404


def test_insert_rejects_archived_and_foreign_personal_answers():
    queue = sd.make_queue()
    owner = _member(queue)
    other = _member(queue)
    ticket = sd.make_ticket(queue=queue)
    archived = sd.make_answer(owner=owner, archived=True, text="Архив")
    foreign = sd.make_answer(owner=other, text="Чужой")
    client = support.logged_in(owner)

    archived_response = client.get(
        f"/servicedesk/answers/{archived.pk}/insert/?ticket={ticket.number}"
    )
    foreign_response = client.get(
        f"/servicedesk/answers/{foreign.pk}/insert/?ticket={ticket.number}"
    )

    assert archived_response.status_code == 404
    assert foreign_response.status_code == 404
