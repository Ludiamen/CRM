"""Сервис: этикетки и QR (срез 006; PLAN-006, «Этикетки»; CONTRACT-006, 5.7, 11.9, решения 10 и 50).

Адрес в QR — `PORTAL_URL` и путь карточки, без строки запроса и сведений сеанса. Картинка — SVG в `data:`-ссылке
(CSP `img-src 'self' data:`), сравнивается с выводом `qrcode` побайтно.
"""
import base64
import io

import qrcode
from django.conf import settings
from qrcode.image.svg import SvgPathImage

from apps.lists.models import Record
from apps.lists.services import schema, values

LIMIT = 100
DATA_URI = "data:image/svg+xml;base64,"


def card_url(record) -> str:
    """Абсолютный адрес карточки записи: `PORTAL_URL` без «/» на конце + `/lists/<id>/<n>/`."""
    return f"{settings.PORTAL_URL.rstrip('/')}/lists/{record.list_id}/{record.number}/"


def qr_data_uri(url: str) -> str:
    """QR-код адреса как `data:image/svg+xml;base64,…` (`SvgPathImage`, `box_size=10`, `border=4`)."""
    out = io.BytesIO()
    qrcode.make(url, image_factory=SvgPathImage, box_size=10, border=4).save(out)
    return DATA_URI + base64.b64encode(out.getvalue()).decode("ascii")


def build(lst, records, viewer) -> list[dict]:
    """Этикетки записей по порядку: название списка и записи, значение первого видимого уникального поля или «№ N»,
    адрес карточки и QR. Скрытые поля не используются."""
    unique = [field for field in schema.visible_fields(lst) if field.unique]
    items = []
    for record in records:
        value = ""
        for field in unique:
            value = values.display(field, (record.values or {}).get(field.code), viewer)
            if value:
                break
        url = card_url(record)
        items.append({"list": lst.name, "title": record.title, "value": value or f"№ {record.number}",
                      "url": url, "qr": qr_data_uri(url)})
    return items


def records_by_numbers(lst, numbers) -> list[Record]:
    """Записи списка по номерам в порядке запроса; несуществующие номера пропускаются."""
    found = {r.number: r for r in Record.objects.filter(list=lst, number__in=list(numbers))}
    return [found[n] for n in numbers if n in found]
