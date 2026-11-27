"""Условия правил: шесть операторов и псевдополя (T-13020; SPEC-013, FR-797/798)."""
from apps.automation.services import conditions


def test_six_operators():
    values = {"priority": 2, "assignee": None, "changed": ["priority", "category"]}
    assert conditions.match(values, [{"field": "priority", "op": "=", "value": 2}])
    assert conditions.match(values, [{"field": "priority", "op": "≠", "value": 3}])
    assert conditions.match(values, [{"field": "priority", "op": "в", "value": [1, 2]}])
    assert conditions.match(values, [{"field": "priority", "op": "не в", "value": [3, 4]}])
    assert conditions.match(values, [{"field": "assignee", "op": "пусто", "value": None}])
    assert conditions.match(values, [{"field": "priority", "op": "не пусто", "value": None}])


def test_changed_field_matches_any_changed_name():
    values = {"changed": ["priority", "category"]}
    assert conditions.match(values, [{"field": "changed_field", "op": "в", "value": ["category"]}])
    assert not conditions.match(values, [{"field": "changed_field", "op": "в", "value": ["queue"]}])
    assert conditions.match(values, [{"field": "changed_field", "op": "=", "value": "priority"}])
