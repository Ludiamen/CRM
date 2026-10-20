"""Службы базы знаний (PLAN-005; CONTRACT-005, раздел 5).

Здесь же — исключения отказов формы (раздел 5.1): отдельного модуля `errors.py` в перечне модулей плана нет.
Представление ловит `KnowledgeError`, отвечает 200 с формой и сообщением у поля `field`; служба при отказе
ничего не пишет (ни строк, ни журнала, ни событий).
"""


class KnowledgeError(Exception):
    """Отказ формы: `code` — машинный код отказа, `field` — имя поля формы или пустая строка (отказ без поля)."""

    def __init__(self, code: str, field: str = ""):
        super().__init__(code)
        self.code = code
        self.field = field


class ArticleError(KnowledgeError):
    """Отказ службы статей."""


class RubricError(KnowledgeError):
    """Отказ службы рубрик."""


class TagError(KnowledgeError):
    """Отказ приведения тегов."""


class VersionError(KnowledgeError):
    """Отказ службы версий."""


class FileRefused(KnowledgeError):
    """Отказ при прикреплении файла к статье."""


class SettingsError(KnowledgeError):
    """Отказ службы настроек (срок корзины)."""


class VersionConflict(ArticleError):
    """Сохранение поверх чужой правки: `who` — ФИО последнего сохранившего, `when` — время его сохранения,
    `current_version` — номер версии на момент отказа, `base_version` — номер, с которого правили."""

    def __init__(self, *, who: str, when, current_version: int, base_version: int):
        super().__init__("stale_version", "")
        self.who = who
        self.when = when
        self.current_version = current_version
        self.base_version = base_version
