"""Смена ключей шифрования полей (PLAN-001, «Окружение целиком», NFR-011).

Порядок: новый ключ ставится первым в `FIELD_ENCRYPTION_KEYS`, затем эта команда
перешифровывает `EncryptedTOTPDevice.key_encrypted` и `OneTimeLink.code_encrypted`
через `MultiFernet.rotate()`, и только после неё старый ключ убирают из списка.
Всё делается в одной транзакции: если хоть один шифротекст не открывается ни одним
ключом списка, команда падает и не меняет ни одной строки. Печатает только число
записей — ключи и значения не выводятся и в журнал не пишутся.
"""
from cryptography.fernet import InvalidToken
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import EncryptedTOTPDevice, OneTimeLink
from apps.core.services import crypto

CHUNK = 500


class Command(BaseCommand):
    help = "Перешифровывает ключи TOTP и коды ссылок первым ключом из FIELD_ENCRYPTION_KEYS."

    def handle(self, *args, **options):
        fernet = crypto.fernet()
        total = 0
        try:
            with transaction.atomic():
                for model, field in ((EncryptedTOTPDevice, "key_encrypted"), (OneTimeLink, "code_encrypted")):
                    rows = model.objects.exclude(**{field: ""}).order_by("pk").values_list("pk", field)
                    batch = []
                    for pk, token in rows.iterator(chunk_size=CHUNK):
                        batch.append((pk, fernet.rotate(token.encode()).decode()))
                        if len(batch) >= CHUNK:
                            total += self._save(model, field, batch)
                            batch = []
                    total += self._save(model, field, batch)
        except InvalidToken:
            raise CommandError(
                "Не удалось расшифровать запись ни одним ключом из FIELD_ENCRYPTION_KEYS: "
                "старый ключ убран из списка слишком рано. Ничего не изменено."
            ) from None
        self.stdout.write(f"Перешифровано записей: {total}")

    @staticmethod
    def _save(model, field, batch) -> int:
        for pk, token in batch:
            model.objects.filter(pk=pk).update(**{field: token})
        return len(batch)
