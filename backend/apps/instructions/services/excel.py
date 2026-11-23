"""Выгрузка дисциплины в Excel (срез 010, T-10210; FR-715; CONTRACT-010, 11).

Лист «Дисциплина», те же числа, что на странице. Только значения; openpyxl уже в зависимостях.
"""
import io

from openpyxl import Workbook

HEADERS = ("Подразделение", "Сотрудник", "Исполнено в срок", "С переносом", "Просрочено", "Всего",
           "По сроку с переносами: в срок", "По сроку с переносами: просрочено")


def build(data) -> bytes:
    """Собрать книгу `.xlsx` из ответа `discipline.rows`."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Дисциплина"
    sheet.append(list(HEADERS))
    for row in data.get("rows", []):
        sheet.append([row.get("unit", ""), row.get("person", ""), row.get("in_time", 0),
                      row.get("with_transfer", 0), row.get("overdue", 0), row.get("total", 0),
                      row.get("final_in_time", 0), row.get("final_overdue", 0)])
    totals = data.get("totals", {})
    sheet.append(["Итого", "", totals.get("in_time", 0), totals.get("with_transfer", 0),
                  totals.get("overdue", 0), totals.get("total", 0), totals.get("final_in_time", 0),
                  totals.get("final_overdue", 0)])
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()