"""Подписи действий ленты в журнале (срез 007).

Русские подписи кодов действий, видов объектов и ключей «было / стало» из плана («Журнал», CONTRACT-007, 8.2):
четыре действия (`feed.post_deleted`, `feed.comment_deleted`, `feed.retention_changed`, `feed.retention_purged`),
три вида объекта (`feed.post`, `feed.comment`, `feed.settings`) и шесть ключей; подпись ключа `posts` — дословно
«Удалено по сроку, записей» (план, сценарий 12 п. 4).

Регистрируется в точке ядра `audit_labels` (`extensions.register_all`); ядро сливает словари точек, при совпадении
ключа побеждает поздний. Ключей `author`, `published_at`, `created_at`, `post`, `years`, `posts` в общем словаре
`fields` ядра и прежних модулей нет (факт, CONTRACT-007, 8.2), слияние чужих подписей не меняет. Словарь `values`
пуст: ФИО, время по Москве и числа служба пишет по-русски, а общий ключ значений изменил бы чужие подписи.
Модели не импортируются.
"""

ACTIONS = dict([
    ("feed.post_deleted", "Чужая запись ленты удалена"),
    ("feed.comment_deleted", "Чужой комментарий ленты удалён"),
    ("feed.retention_changed", "Срок хранения ленты изменён"),
    ("feed.retention_purged", "Записи ленты удалены по сроку"),
])
FIELDS = dict([
    ("author", "автор"), ("published_at", "опубликовано"), ("created_at", "написано"),
    ("post", "номер записи"), ("years", "срок хранения, лет"), ("posts", "Удалено по сроку, записей"),
])
OBJECT_TYPES = dict([
    ("feed.post", "запись ленты"), ("feed.comment", "комментарий ленты"), ("feed.settings", "настройки ленты"),
])


def audit_labels() -> dict:
    """Функция точки `audit_labels`: действия, поля, виды объектов; значений для перевода нет."""
    return {"actions": dict(ACTIONS), "fields": dict(FIELDS), "object_types": dict(OBJECT_TYPES), "values": {}}
