"""Задания RQ: отправка доставки, обход, сводка, ночное удаление (PLAN-004, «Где живёт код»; CONTRACT-004, 7.1).

Задания тонкие: каждое зовёт один сервис и не ловит его исключений. Службы импортируются внутри функций: служба
отправки сама ставит эти задания в очередь.
"""


def send_delivery(delivery_id):
    """Отправка одной доставки; возвращает строку итога (`noop`, `sent`, `waiting`, `failed`, `skipped`)."""
    from apps.notify.services import delivery

    return delivery.send_delivery(delivery_id)


def notify_tick():
    """Обход раз в 30 секунд: письма, повторная постановка, возврат зависших, сводки, просроченные коды."""
    from apps.notify.services import delivery

    return delivery.tick()


def build_digest(user_id):
    """Сборка сводки сотрудника; возвращает номер `Digest` или `None`."""
    from apps.notify.services import digest

    return digest.build(user_id)


def notify_retention():
    """Ночное удаление уведомлений, сводок, кодов и чатов бота; возвращает словарь итогов."""
    from apps.notify.services import retention

    return retention.run()
