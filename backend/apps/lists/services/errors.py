"""Отказы служб `lists` (CONTRACT-006, 5.1; модуль — решение контракта, написан Opus до круга а2 — И4)."""
from apps.core.widgets import MOSCOW


class ListsError(Exception):
    """Отказ службы: `code` — ключ `apps.lists.texts.TEXTS`, `field` — код поля (`"title"`, `"name"`, `"description"`
    у названий), `params` — подстановки текста; `message` — готовый текст по-русски."""

    def __init__(self, code: str, *, field: str = "", params: dict | None = None):
        self.code = code
        self.field = field
        self.params = dict(params or {})
        super().__init__(code)

    @property
    def message(self) -> str:
        from apps.lists.texts import TEXTS

        text = TEXTS.get(self.code, "")
        return text.format(**self.params) if self.params else text

    def __str__(self) -> str:
        return self.message or self.code


class ValuesInvalid(ListsError):
    """Отказы нескольких полей формы записи сразу: `errors` — код поля или `"title"` → `ListsError` (в том числе
    `unique_taken`, ответ Opus О2). Своего текста в `TEXTS` нет."""

    def __init__(self, errors: dict[str, ListsError]):
        self.errors = dict(errors)
        super().__init__("values_invalid")

    @property
    def message(self) -> str:
        return "; ".join(error.message for error in self.errors.values())


class RecordGone(ListsError):
    """Запись удалена навсегда, пока её правили («Запись удалена»)."""

    def __init__(self):
        super().__init__("record_gone")


class RecordArchived(ListsError):
    """Запись в архиве — правка и привязки отказаны («Запись в архиве»)."""

    def __init__(self):
        super().__init__("record_archived")


class VersionConflict(ListsError):
    """Запись уже сохранил другой сотрудник: `who` — `User` (`updated_by`), `when` — `updated_at`; в тексте — ФИО и
    «ДД.ММ.ГГГГ ЧЧ:ММ» по Москве (CONTRACT-006, 12.1)."""

    def __init__(self, who, when):
        self.who = who
        self.when = when
        moment = when.astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M") if when else ""
        super().__init__("version_conflict", params={"who": getattr(who, "full_name", "") or "", "when": moment})
