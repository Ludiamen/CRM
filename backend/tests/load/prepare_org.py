"""Структура стенда для нагрузочного прогона среза 002 (NFR-101, NFR-102; PLAN-002 «Проверка», «Скорость»).

Готовит на стенде дерево из LOAD_UNITS узлов (по умолчанию 200, считая корень — «до 200 узлов», NFR-101)
и членства LOAD_ORG_USERS сотрудников нагрузки (по умолчанию 100; это записи `load-…@example.org`,
которые готовит prepare_users.py, поэтому запускать после него). Узлы — отделы, по пять потомков у узла,
имена `Нагрузка узел NNN`; сотрудники раскладываются по созданным узлам по кругу, у каждого десятого узла
первый участник — руководитель. Часть сотрудников (LOAD_ORG_PHOTOS, по умолчанию 50) получает чистое фото
с настоящими файлами 512 и 96 (чтобы карточка и список показывали фото, как в жизни: фото — для реалистичной нагрузки, решение Opus 2026-10-04).

Узлы и членства пишутся через ORM, без событий журнала. Повторный запуск безопасен: членства сотрудников
нагрузки пересоздаются, недостающие узлы добираются до LOAD_UNITS. Работает ТОЛЬКО при E2E_STAND=1 (как
e2e_reset_stand); данные убирает следующий сброс приёмки. Каталог tests в образ не входит, поэтому скрипт
подаётся на вход shell:

    docker compose -f deploy/docker-compose.yml --profile dev exec -T standtools \
        python manage.py shell --no-imports < backend/tests/load/prepare_org.py
"""
import hashlib
import io
import os
import sys

from django.db import transaction
from django.utils import timezone

if os.environ.get("E2E_STAND") != "1":
    sys.exit("Скрипт работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено.")

from apps.core.models import StoredFile, User  # noqa: E402
from apps.core.services import files  # noqa: E402
from apps.org.models import Membership, Unit  # noqa: E402

UNIT_PREFIX = "Нагрузка узел"
CHILDREN = 5


def name_key(text: str) -> str:
    return " ".join(text.split()).lower().replace("ё", "е")


def make_unit(name: str, parent: Unit) -> Unit:
    unit = Unit.objects.create(name=name, name_key=name_key(name), kind="department", parent=parent,
                               depth=parent.depth + 1, path="")
    unit.path = f"{parent.path}{unit.pk}/"
    unit.save(update_fields=["path"])
    return unit


def photo_bytes(size: int, seed: int) -> bytes:
    from PIL import Image

    image = Image.new("RGB", (size, size), (40 + seed * 37 % 180, 80 + seed * 53 % 150, 120 + seed * 29 % 120))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=80)
    return buffer.getvalue()


def attach_photo(user: User, seed: int) -> None:
    content = {512: photo_bytes(512, seed), 96: photo_bytes(96, seed)}
    stored = StoredFile.objects.create(owner=user, purpose="photo", status="clean", content_type="image/jpeg",
                                       size=len(content[512]), sha256=hashlib.sha256(content[512]).hexdigest(),
                                       scanned_at=timezone.now())
    for size, data in content.items():
        path = files.photo_path(stored, size)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    user.photo = stored
    user.photo_pending = None
    user.save(update_fields=["photo", "photo_pending"])


target_units = int(os.environ.get("LOAD_UNITS", "200"))
target_people = int(os.environ.get("LOAD_ORG_USERS", "100"))
target_photos = int(os.environ.get("LOAD_ORG_PHOTOS", "50"))

with transaction.atomic():
    root = Unit.objects.get(is_root=True)
    people = list(User.objects.filter(email__startswith="load-", email__endswith="@example.org", state="active")
                  .order_by("email")[:target_people])
    if not people:
        sys.exit("Нет сотрудников нагрузки (load-…@example.org): сначала prepare_users.py. Ничего не изменено.")
    Membership.objects.filter(user__in=people).delete()

    made = list(Unit.objects.filter(name__startswith=UNIT_PREFIX).order_by("path"))
    queue = [root] + made
    parents = {unit.pk: 0 for unit in queue}
    for unit in made:  # сколько потомков уже у узла: родителю не больше CHILDREN
        parents[unit.parent_id] = parents.get(unit.parent_id, 0) + 1
    free = [unit for unit in queue if parents[unit.pk] < CHILDREN]
    number = len(made)
    while Unit.objects.count() < target_units:
        parent = free[0]
        number += 1
        unit = make_unit(f"{UNIT_PREFIX} {number:03d}", parent)
        made.append(unit)
        parents[unit.pk] = 0
        parents[parent.pk] += 1
        free.append(unit)
        if parents[parent.pk] >= CHILDREN:
            free.pop(0)

    author = people[0]
    for index, user in enumerate(people):
        unit = made[index % len(made)] if made else root
        Membership.objects.create(user=user, unit=unit, mark="head" if index < len(made) and index % 10 == 0 else "",
                                  created_by=author)
    for index, user in enumerate(people[:target_photos]):
        if user.photo_id is None:
            attach_photo(user, index)

print(f"узлов: {Unit.objects.count()}, членств сотрудников нагрузки: {Membership.objects.filter(user__in=people).count()}, "
      f"с фото: {User.objects.filter(pk__in=[u.pk for u in people], photo__isnull=False).count()}")
