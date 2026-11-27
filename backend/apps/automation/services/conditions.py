"""Условия правил автоматизации (PLAN-013, T-13020; SPEC-013, FR-797/798)."""
OPERATORS = ("=", "≠", "в", "не в", "пусто", "не пусто")
_EMPTY = (None, "", [], ())


def _actual(values: dict, field: str):
    if field == "changed_field":
        return values.get("changed") or []
    return values.get(field)


def _is_empty(value) -> bool:
    return value in _EMPTY


def one(values: dict, condition: dict) -> bool:
    """Проверить одно условие по снимку значений субъекта."""
    field, op, expected = condition.get("field"), condition.get("op"), condition.get("value")
    actual = _actual(values, field)
    if op in ("=", "равно"):
        if field == "changed_field":
            return expected in actual
        return actual == expected
    if op in ("≠", "не равно"):
        if field == "changed_field":
            return expected not in actual
        return actual != expected
    if op in ("в", "входит в"):
        wanted = expected if isinstance(expected, (list, tuple, set)) else (expected,)
        if field == "changed_field":
            return any(item in wanted for item in actual)
        return actual in wanted
    if op in ("не в", "не входит в"):
        wanted = expected if isinstance(expected, (list, tuple, set)) else (expected,)
        if field == "changed_field":
            return not any(item in wanted for item in actual)
        return actual not in wanted
    if op == "пусто":
        return _is_empty(actual)
    if op == "не пусто":
        return not _is_empty(actual)
    return False


def match(values: dict, conditions: list) -> bool:
    """Все условия одновременно; пустой список — совпало."""
    return all(one(values, condition) for condition in conditions or ())
