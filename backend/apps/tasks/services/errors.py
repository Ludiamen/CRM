"""Отказы служб задач (срез 009; CONTRACT-009, 5.2, 12.1).

`TasksError` несёт код (ключ `TEXTS`), поле формы для `[data-error="<поле>"]` и подстановки. Тексты — словарь
раздела 12.1; тесты берут их литералами и импортом не пользуются. Неизвестный код отдаёт наружу код, не текст.
"""
from apps.tasks.models import Task

TEXTS = {
    "title_range": "Название задачи — от 1 до 300 знаков",
    "description_long": "Описание — не длиннее 10 000 знаков",
    "deadline_past": "Срок не может быть раньше сегодняшнего дня",
    "assignee_dismissed": "Сотрудник уволен: задачу поставить нельзя",
    "assignee_forbidden": "Поставить задачу этому сотруднику нельзя",
    "member_dismissed": "Сотрудник уволен: в состав не добавить",
    "member_duplicate": "Этот сотрудник уже в составе задачи",
    "member_is_assignee": "Исполнитель уже назначен: в составе его не указывают",
    "edit_forbidden": "Нет права менять поля задачи",
    "status_invalid": "Неизвестный статус задачи",
    "status_forbidden": "Нет права менять статус задачи",
    "move_forbidden": "Нет права менять это поле задачи",
    "plan_forbidden": "Двигать карточки в чужом плане нельзя",
    "overdue_move": "Из «Просрочены» переносить нельзя",
    "board_unknown": "Неизвестная доска",
    "value_invalid": "Неизвестное значение переноса",
    "comment_empty": "Напишите комментарий",
    "comment_too_long": "Предел: 10 000 знаков",
    "comment_forbidden": "Комментировать может только тот, кто видит задачу",
    "files_limit": "Не больше 10 файлов к комментарию",
    "file_too_big": "Файл больше 20 МБ",
    "file_type": "Файл такого типа не принимается",
    "file_missing": "Файл не найден",
    "reminders_limit": "Не больше 10 напоминаний на задачу",
    "reminder_forbidden_other": "Напоминание можно поставить только себе",
    "reminder_deadline_required": "Для «за N рабочих дней» нужен срок задачи",
    "reminder_days_range": "Число рабочих дней — от 1 до 30",
    "reminder_date_invalid": "Дата напоминания — ДД.ММ.ГГГГ",
    "column_title_range": "Название колонки — от 1 до 100 знаков",
    "column_title_taken": "Колонка с таким названием уже есть",
    "column_last": "Последнюю колонку удалить нельзя",
    "category_title_range": "Название категории — от 1 до 100 знаков",
    "category_title_taken": "Категория с таким названием уже есть",
    "retention_range": "Срок хранения — от 1 до 10 лет",
    "delete_forbidden": "Нет права удалять задачу",
    "delete_confirm": "Удалить задачу без возможности вернуть?",
    "retention_decrease": "Ближайшая уборка удалит задач: {count}",
    "category_delete_confirm": "Удалить категорию? Задачи останутся без категории",
}


class TasksError(Exception):
    """Отказ службы задач: код, поле формы и подстановки текста."""

    def __init__(self, code: str, field: str = "", params: dict | None = None):
        self.code = code
        self.field = field
        self.params = dict(params or {})
        super().__init__(code)

    @property
    def message(self) -> str:
        """Готовый текст отказа; неизвестный код — пустая строка (наружу уходит код)."""
        text = TEXTS.get(self.code, "")
        return text.format(**self.params) if self.params else text

    def __str__(self) -> str:
        return self.message or self.code


STATUSES = tuple(Task.Status.values)