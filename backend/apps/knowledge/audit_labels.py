"""Подписи событий журнала базы знаний по-русски (PLAN-005, «Журнал»; CONTRACT-005, 8.2).

Регистрируется в точке ядра `audit_labels` (`extensions.register_all`); ядро сливает словари точек (поздние побеждают)
в одном месте, общем для страницы `/audit/` и выгрузки CSV. Общие ключи `number` и `name` подписаны так же, как у
сервис-деска, иначе подпись его записей изменилась бы. Модели не импортируются.
"""

ACTIONS = dict([
    ("knowledge.article_created", "Статья создана"), ("knowledge.article_published", "Статья опубликована"),
    ("knowledge.article_trashed", "Статья перенесена в корзину"),
    ("knowledge.article_restored", "Статья возвращена из корзины"),
    ("knowledge.article_purged", "Статья удалена навсегда"), ("knowledge.version_deleted", "Версия статьи удалена"),
    ("knowledge.comment_deleted", "Чужой комментарий удалён"),
    ("knowledge.rubric_created", "Рубрика создана"), ("knowledge.rubric_renamed", "Рубрика переименована"),
    ("knowledge.rubric_moved", "Рубрика перенесена"), ("knowledge.rubric_deleted", "Рубрика удалена"),
    ("knowledge.trash_days_changed", "Срок корзины изменён"),
])
FIELDS = dict([
    ("number", "номер"), ("name", "название"), ("title", "заголовок"), ("version", "номер версии"),
    ("path", "путь"), ("days", "срок, дней"), ("by_term", "по сроку"),
])
OBJECT_TYPES = dict([("knowledge.article", "статья"), ("knowledge.rubric", "рубрика")])


def audit_labels() -> dict:
    """Функция точки `audit_labels`: действия, поля, виды объектов; значений для перевода нет."""
    return {"actions": dict(ACTIONS), "fields": dict(FIELDS), "object_types": dict(OBJECT_TYPES), "values": {}}
