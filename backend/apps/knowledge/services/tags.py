"""Теги статей: приведение введённой строки и подсказка (PLAN-005, «Рубрики, теги, главная»; FR-420)."""
from ..models import Tag
from . import TagError

MAX_TAGS = 10
MAX_TAG_LENGTH = 40
SUGGEST_LIMIT = 10


def normalize(raw: str) -> list[str]:
    """Строка через запятую → список тегов: без пробелов по краям, внутренние пробелы — один, строчные.

    Пустые выбрасываются, повторы склеиваются (остаётся первое вхождение, порядок ввода сохраняется). Проверки —
    после склейки: тег длиннее 40 знаков — `tag_too_long`, больше 10 тегов — `tags_too_many` (поле `tags`).
    В базу не ходит.
    """
    result: list[str] = []
    for part in (raw or "").split(","):
        name = " ".join(part.split()).lower()
        if name and name not in result:
            result.append(name)
    if any(len(name) > MAX_TAG_LENGTH for name in result):
        raise TagError("tag_too_long", "tags")
    if len(result) > MAX_TAGS:
        raise TagError("tags_too_many", "tags")
    return result


def suggest(q: str) -> list[str]:
    """До 10 имён тегов опубликованных статей, начинающихся с `q` без учёта регистра (`%` и `_` — обычные знаки).

    Право править проверяет представление.
    """
    q = (q or "").strip()
    if not q:
        return []
    names = (Tag.objects.filter(name__istartswith=q, article__state="published")
             .order_by("name").values_list("name", flat=True).distinct()[:SUGGEST_LIMIT])
    return list(names)
