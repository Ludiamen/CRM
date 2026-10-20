"""Фоновые задания базы знаний (PLAN-005, «Корзина и ночная очистка»).

Задание тонкое: зовёт службу и не ловит её исключений. Службы импортируются внутри функции.
"""


def purge_trash() -> None:
    """Ночная очистка корзины (cron `45 23 * * *`, очередь `maintenance`); сбой статей — `PurgeFailed` после обхода."""
    from apps.knowledge.services import retention

    result = retention.purge_trash()
    if result.failed:
        raise retention.PurgeFailed(result.failed)
