"""Regression checks for mixed feed-picker result sets."""

import re

import pytest

from tests import support
from tests import support_feed as sf
from tests import support_org as org

pytestmark = pytest.mark.django_db


def test_to_picker_mixes_people_and_units_within_stable_shared_limit():
    session = sf.as_plain()
    people = [support.make_employee(totp=False, full_name=f"Смешанный поиск {number:02d}")
              for number in range(25)]
    unit = org.make_unit("Смешанный поиск подразделения")

    def pick():
        response = session.client.get("/feed/pick/", {"scope": "to", "q": "смешанный поиск"})
        assert response.status_code == 200
        return re.findall(r'data-pick-value="([^"]+)"', response.content.decode("utf-8"))

    first = pick()
    second = pick()

    assert len(first) <= 20
    expected_people = {f"p{person.pk}" for person in people}
    assert expected_people.intersection(first)
    assert f"u{unit.pk}" in first
    assert second == first
