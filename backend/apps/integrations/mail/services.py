"""Публичный интерфейс модуля почты (PLAN-001, «Исходящая почта»).

T-230 (следующий проход) создаёт `MailMessage(status="queued")` и по `on_commit`
ставит задание RQ в очередь `mail` с единственным позиционным аргументом —
номером письма. Пока это заглушка: сервисы ядра обращаются к ней по контракту.

`related_user` — пользователь, которому адресовано письмо (поле `MailMessage.related_user`).
"""


def send(template: str, to: str, context: dict, *, related_user=None):
    """Ставит письмо в очередь. Заглушка до T-230."""
    raise NotImplementedError("integrations.mail.services.send реализуется в T-230")
