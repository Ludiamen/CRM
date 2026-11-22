"""T-9114: ежедневная сводка по задачам подчинённых — один раз в день, «горящие», цепочка, без дублей (FR-691).

Источники: PLAN-009 «Уведомления и сводка» (`tasks_digest` каждые 15 минут в рабочий день; атомарный
`cache.add("tasks:digest:<дата>:<user>", 1, timeout=…)`; при успехе — одно уведомление `tasks.subordinate_digest`
с просроченными и «горящими» задачами подчинённых — срок сегодня или «скоро» в пределах рабочего дня; получатели —
руководитель и заместитель цепочки; повторный цикл без дублей); CONTRACT-009: 5.1 (`digest.send(now)`,
`tasks_digest(now=…)`), 5.3 (кэш сводки — Valkey, фикстура `valkey_clean`), 9.3, К18 (ключ
`tasks:digest:<дата>:<user>`, значение `1`), NFR-715.

Задание зовётся синхронно с `now=…`; часы машины ставятся фикстурой `clock` только для «сегодня» по Москве.
Код среза импортируется внутри тестов, модели — через `support.model`; сбор проходит до появления кода.
"""
import datetime
from datetime import date
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache

from tests import support
from tests import support_org
from tests import support_tasks as tasks_helpers

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime.datetime(2026, 11, 23, 10, 0, tzinfo=MSK)        # понедельник, рабочий день
SATURDAY = datetime.datetime(2026, 11, 21, 10, 0, tzinfo=MSK)
DIGEST = "tasks.subordinate_digest"


# --- помощники файла ---------------------------------------------------------------------------------------------

def _digest(now):
    from apps.tasks.tasks import tasks_digest

    return tasks_digest(now=now)


def _notes(kind: str = DIGEST):
    return support.model("notify.Notification").objects.filter(kind=kind)


def _recipients() -> set[int]:
    return set(_notes().values_list("user_id", flat=True))


def _people():
    """Дерево: верхний узел с руководителем и заместителем, вложенный — тоже; исполнитель — во вложенном."""
    units = support_org.make_tree({"Верхний узел сводки": {"Нижний узел сводки": {}}})
    top, nested = units["Верхний узел сводки"], units["Нижний узел сводки"]
    people = {
        "top": top,
        "nested": nested,
        "head_top": tasks_helpers.head_of(top, full_name="Руководитель Верхнего"),
        "deputy_top": tasks_helpers.deputy_of(top, full_name="Заместитель Верхнего"),
        "head_nested": tasks_helpers.head_of(nested, full_name="Руководитель Нижнего"),
        "deputy_nested": tasks_helpers.deputy_of(nested, full_name="Заместитель Нижнего"),
        "worker": tasks_helpers.staff_user(full_name="Исполнитель Сводки"),
        "author": tasks_helpers.staff_user(full_name="Постановщик Сводки"),
    }
    support_org.make_member(people["worker"], nested)
    return people


def _chain(people) -> set[int]:
    return {people[key].pk for key in ("head_top", "deputy_top", "head_nested", "deputy_nested")}


def _task(people, deadline, *, status="new", title="Задача сводки"):
    return tasks_helpers.make_task(author=people["author"], assignee=people["worker"], deadline=deadline,
                                   status=status, title=title)


def _key(day: date, user) -> str:
    """Ключ сводки по контракту К18."""
    return f"tasks:digest:{day.isoformat()}:{getattr(user, 'pk', user)}"


# --- 9.3: «горящие» задачи и получатели ------------------------------------------------------------------------

def test_digest_goes_to_head_and_deputy_of_chain_once_per_person(clock):
    """FR-691 (CONTRACT-009, 9.3): в рабочий день задание отправляет по одному `tasks.subordinate_digest`
    руководителю и заместителю всей цепочки (оба узла), даже если «горящих» задач несколько; возвращает число
    созданных уведомлений; посторонним и постановщику — ничего."""
    clock.set(NOW)
    people = _people()
    _task(people, date(2026, 11, 20), title="Просроченная сводки")
    _task(people, date(2026, 11, 23), title="Сегодняшняя сводки")
    _task(people, date(2026, 11, 23), title="Вторая сегодняшняя")

    sent = _digest(NOW)

    assert sent == 4, f"задание вернуло {sent} уведомлений"
    assert _recipients() == _chain(people), f"получатели сводки: {_recipients()}"
    for user_id in _chain(people):
        assert _notes().filter(user_id=user_id).count() == 1, f"у {user_id} больше одной сводки"
    assert people["worker"].pk not in _recipients() and people["author"].pk not in _recipients()
    assert set(_notes().values_list("text", flat=True)) == {"Сводка по задачам подчинённых"}


def test_digest_skips_when_no_hot_tasks(clock):
    """FR-691 (CONTRACT-009, 9.3): «горящие» — срок сегодня или «скоро» в пределах рабочего дня; задача со сроком
    через неделю и завершённая сегодня сводку не рождают, уведомлений нет."""
    clock.set(NOW)
    people = _people()
    _task(people, date(2026, 12, 1), title="Далёкая не горящая")
    _task(people, date(2026, 11, 23), status="done", title="Завершённая сегодня")

    assert _digest(NOW) == 0, "сводка создана без «горящих» задач"
    assert not _notes().exists()


def test_digest_not_sent_on_non_working_day(clock):
    """FR-691 (CONTRACT-009, 9.3): сводка идёт только в рабочий день — в субботу задание ничего не отправляет,
    даже при просроченной задаче подчинённого."""
    clock.set(SATURDAY)
    people = _people()
    _task(people, date(2026, 11, 20), title="Просроченная в субботу")

    assert _digest(SATURDAY) == 0
    assert not _notes().exists()


def test_digest_not_sent_for_own_tasks_or_empty_unit(clock):
    """FR-691: сводка — о задачах подчинённых; собственная «горящая» задача руководителя и узел без подчинённых
    уведомлений не дают."""
    clock.set(NOW)
    lonely = tasks_helpers.staff_user(full_name="Руководитель Без Подчинённых")
    own = tasks_helpers.make_task(author=lonely, assignee=lonely, deadline=date(2026, 11, 20),
                                  title="Своя просроченная")

    assert _digest(NOW) == 0, "сводка ушла по собственной задаче сотрудника без подчинённых"
    assert not _notes().filter(user=lonely).exists()
    assert own.pk


# --- К18, NFR-715: один раз в день, атомарный cache.add ---------------------------------------------------------

def test_digest_uses_atomic_cache_add_key(clock):
    """FR-691, NFR-715 (CONTRACT-009, К18): занятый ключ `tasks:digest:<дата>:<user>` не даёт отправить сводку —
    задание пользуется атомарным `cache.add`, а не «проверил и записал»; чужая дата ключа не мешает."""
    clock.set(NOW)
    people = _people()
    _task(people, date(2026, 11, 23), title="Сегодняшняя для ключа")
    for user_id in _chain(people):
        assert cache.add(_key(NOW.date(), user_id), 1, timeout=3600) is True

    assert _digest(NOW) == 0, "сводка отправлена при занятых ключах"
    assert not _notes().exists()

    cache.delete(_key(NOW.date(), people["head_top"]))
    assert _digest(NOW) == 1
    assert _recipients() == {people["head_top"].pk}


def test_second_cycle_same_day_creates_no_duplicates(clock):
    """NFR-715 (CONTRACT-009, 9.3): повторный цикл в тот же день не создаёт второго уведомления — первый запуск
    ставит ключи, второй возвращает 0, число записей не меняется."""
    clock.set(NOW)
    people = _people()
    _task(people, date(2026, 11, 20), title="Просроченная для повтора")

    first = _digest(NOW)
    created = _notes().count()
    second = _digest(NOW + datetime.timedelta(minutes=15))

    assert first == 4 and created == 4
    assert second == 0, f"повторный цикл вернул {second}"
    assert _notes().count() == created, "повторный цикл задвоил сводку"


def test_next_day_sends_new_digest(clock):
    """FR-691: ключ сводки — на дату; на следующий рабочий день руководитель получает новую сводку."""
    clock.set(NOW)
    people = _people()
    task = _task(people, date(2026, 11, 20), title="Просроченная на два дня")
    assert _digest(NOW) == 4

    tomorrow = datetime.datetime(2026, 11, 24, 10, 0, tzinfo=MSK)
    clock.set(tomorrow)
    task.deadline = date(2026, 11, 24)
    task.save(update_fields=["deadline"])

    assert _digest(tomorrow) == 4, "на следующий день сводка не ушла"
    assert _notes().filter(user=people["head_top"]).count() == 2