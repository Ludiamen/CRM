"""Записи стенда для нагрузочного прогона среза 006 (NFR-501…NFR-504, NFR-513; PLAN-006, «Нагрузка»; CONTRACT-006, 13.2):
добавляет записи в шесть стартовых списков до LOAD_LISTS_TOTAL (по умолчанию 50000), из них в «Оборудовании» — до
LOAD_LISTS_EQUIPMENT (по умолчанию 10000); остальные списки получают недостающее по долям (лицензии 8, расходники 6,
сертификаты 6, договоры 10, SIM-карты 10 частей из 40).

Что делает: по полям каждого списка (из базы, не из текста контракта) заполняет значения по типам: строки и многострочные
тексты — из словаря настоящих русских слов ИТ-тематики, встроенного в скрипт (словарь составлен для нагрузки и не взят из
внешних источников); уникальные поля — `<код>-<номер записи>`; числа, деньги, даты (сроки — от -30 до +400 суток от
сегодняшнего дня по Москве), списки значений, сотрудники, подразделения, ссылки на записи «Оборудования»; файлы не создаются.
Заводит строки `UniqueValue` и одну строку истории «создана» на запись, вектор поиска считает служба `vectors.refresh`
тем же SQL, что при сохранении записи. Повторный запуск добирает до цели: уже созданные записи не меняются. Авторы —
действующие сотрудники (первые 50). Работает ТОЛЬКО при E2E_STAND=1 (как e2e_reset_stand); данные убирает следующий сброс
приёмки. Каталог tests в образ не входит, поэтому скрипт подаётся на вход shell:

    docker compose -f deploy/docker-compose.yml --profile dev exec -T -e LOAD_LISTS_TOTAL=50000 standtools \
        python manage.py shell --no-imports < backend/tests/load/fill_lists.py

Вывод: `fill_lists: lists=<число списков> records=<число записей во всех списках>`.
"""
import os
import random
import sys

if os.environ.get("E2E_STAND") != "1":
    sys.exit("Скрипт работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено.")

from datetime import timedelta  # noqa: E402

from django.db import transaction  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.core.models import User  # noqa: E402
from apps.core.widgets import moscow_today  # noqa: E402
from apps.lists.models import Change, Choice, Field, List, Record, UniqueValue  # noqa: E402
from apps.lists.services import unique, vectors  # noqa: E402

CHUNK = 250
SHARES = {"licenses": 8, "consumables": 6, "signatures": 6, "contracts": 10, "sims": 10}
WORDS = (
    "принтер картридж бумага сканер монитор клавиатура мышь ноутбук компьютер сервер сеть кабель роутер коммутатор "
    "интернет почта письмо вложение пароль логин учётная запись доступ права папка файл документ диск резервная копия "
    "восстановление программа установка обновление лицензия антивирус вирус защита шифрование сертификат подпись токен "
    "телефон гарнитура камера видеосвязь собрание календарь проектор экран розетка питание аккумулятор зарядка "
    "драйвер система настройка параметр профиль пользователь сотрудник отдел заявка обращение инструкция регламент "
    "порядок процедура проверка ошибка сбой отказ перезагрузка зависание память процессор температура вентилятор "
    "договор поставка гарантия ремонт склад кабинет этаж здание номер тариф оператор карта носитель удостоверяющий центр"
).split()


def phrase(rng: random.Random, low: int = 1, high: int = 4) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(rng.randint(low, high)))


def make_text(rng: random.Random) -> str:
    return " ".join(phrase(rng, 5, 10).capitalize() + "." for _ in range(rng.randint(1, 3)))


class Pool:
    """Допустимые значения справочных полей, прочитанные из базы один раз."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.today = moscow_today()
        self.people = list(User.objects.filter(state="active").order_by("pk").values_list("pk", flat=True)[:200])
        self.choices: dict[int, list[int]] = {}
        for field_id, pk in Choice.objects.filter(archived=False).order_by("order").values_list("field_id", "pk"):
            self.choices.setdefault(field_id, []).append(pk)
        self.units: list[int] = []
        try:
            from apps.org.services import structure

            self.units = [unit.id for unit in structure.all_units()]
        except Exception:  # noqa: BLE001 — без структуры подразделений поле остаётся пустым
            pass
        self.equipment: list[int] = []

    def value(self, field: Field, number: int):
        """Значение поля в форме хранения; `None` — поле пустое."""
        rng, kind = self.rng, field.type
        if rng.random() < 0.08 and not field.unique:
            return None
        if kind == "string":
            return f"{field.code}-{number:07d}" if field.unique else phrase(rng).capitalize()
        if kind == "text":
            return make_text(rng)
        if kind == "number":
            return str(rng.randint(0, 500))
        if kind == "money":
            return f"{rng.randint(100, 900000)}.{rng.randint(0, 99):02d}"
        if kind == "date":
            if (field.settings or {}).get("deadline"):
                return (self.today + timedelta(days=rng.randint(-30, 400))).isoformat()
            return (self.today - timedelta(days=rng.randint(0, 1500))).isoformat()
        if kind == "bool":
            return rng.random() < 0.5
        if kind == "choice":
            pool = self.choices.get(field.pk)
            return [rng.choice(pool)] if pool else None
        if kind == "person":
            return [rng.choice(self.people)] if self.people else None
        if kind == "unit":
            return [rng.choice(self.units)] if self.units else None
        if kind == "record":
            if not self.equipment:
                return None
            size = rng.randint(1, 2) if field.multiple else 1
            return sorted(set(rng.sample(self.equipment, min(size, len(self.equipment)))))
        return None  # файлы и прочее: записи без файлов


def fill_list(lst: List, target: int, pool: Pool, authors: list, rng: random.Random) -> None:
    """Добавляет записи списка до `target` (всего); номера продолжают `next_number`."""
    fields = list(Field.objects.filter(list=lst).order_by("order"))
    missing = target - Record.objects.filter(list=lst).count()
    now = timezone.now()
    while missing > 0:
        size = min(CHUNK, missing)
        with transaction.atomic():
            start = List.objects.select_for_update().get(pk=lst.pk).next_number
            records = []
            for offset in range(size):
                number = start + offset
                author = rng.choice(authors)
                created = now - timedelta(days=rng.randint(0, 1095), minutes=rng.randint(0, 1439))
                values = {}
                for field in fields:
                    value = pool.value(field, number)
                    if value is not None:
                        values[field.code] = value
                records.append(Record(
                    list=lst, number=number, title=f"{phrase(rng, 2, 3).capitalize()} {number}"[:200], values=values,
                    archived=False, created_at=created, created_by=author, updated_at=created, updated_by=author))
            Record.objects.bulk_create(records)
            Change.objects.bulk_create([Change(record=record, at=record.created_at, actor=record.created_by,
                                               kind=Change.Kind.CREATED, changes=[]) for record in records])
            rows = []
            for field in fields:
                if not field.unique:
                    continue
                for record in records:
                    norm = unique.normalize(field, record.values.get(field.code))
                    if norm:
                        rows.append(UniqueValue(list=lst, field=field, norm_value=norm, record=record))
            UniqueValue.objects.bulk_create(rows, ignore_conflicts=True)
            vectors.refresh([record.pk for record in records])
            List.objects.filter(pk=lst.pk).update(next_number=start + size)
        missing -= size


rng = random.Random(20260606)
authors = list(User.objects.filter(state="active").order_by("pk")[:50])
if not authors:
    sys.exit("Нет действующих сотрудников: сначала подготовьте учётные записи; ничего не изменено.")
by_code = {lst.code: lst for lst in List.objects.filter(code__in=["equipment", *SHARES])}
if "equipment" not in by_code:
    sys.exit("Нет стартовых списков (миграция lists 0002): ничего не изменено.")
total = int(os.environ.get("LOAD_LISTS_TOTAL", "50000"))
equipment_target = int(os.environ.get("LOAD_LISTS_EQUIPMENT", "10000"))
pool = Pool(rng)
fill_list(by_code["equipment"], equipment_target, pool, authors, rng)
pool.equipment = list(Record.objects.filter(list=by_code["equipment"]).order_by("pk").values_list("pk", flat=True)[:5000])
rest = max(0, total - equipment_target)
parts = sum(SHARES.values())
for code, share in SHARES.items():
    if code in by_code:
        fill_list(by_code[code], rest * share // parts, pool, authors, rng)
print(f"fill_lists: lists={List.objects.count()} records={Record.objects.count()}")
