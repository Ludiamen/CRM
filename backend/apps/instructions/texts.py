"""Тексты и исключение служб поручений (CONTRACT-010, 5.2, 12.1; К3).

Ключ `TEXTS` — код отказа (`data-code`, `InstructionsError.code`); `{count}` — единственная подстановка
(`retention_decrease`).
"""


class InstructionsError(Exception):
    """Отказ службы поручений: код, поле и подстановки; текст — из `TEXTS`."""

    def __init__(self, code: str, field: str = "", params: dict | None = None):
        self.code = code
        self.field = field
        self.params = params or {}
        self.message = TEXTS.get(code, code).format(**self.params)
        super().__init__(self.message)


TEXTS = {
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
    "discipline_forbidden": "Отчёт по дисциплине доступен руководителям подразделений",
}