"""Ночная очистка корзины базы знаний сразу (только при E2E_STAND=1; CONTRACT-005, 13).

`e2e_kb_purge`: то же, что задание `purge_trash`; срок берётся из `KnowledgeSettings.trash_days`. Вывод — одна строка
`kb_purge: purged=<n> skipped=<n> failed=<число>`; при сбоях после вывода — `CommandError` с номерами статей.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.knowledge.services import retention
from apps.knowledge.stand import require_stand


class Command(BaseCommand):
    help = "Выполняет ночную очистку корзины сразу (только при E2E_STAND=1)."

    def handle(self, *args, **options):
        require_stand()
        result = retention.purge_trash()
        self.stdout.write(f"kb_purge: purged={result.purged} skipped={result.skipped} failed={len(result.failed)}")
        if result.failed:
            raise CommandError("Сбой удаления статей из корзины: " + ", ".join(str(n) for n in result.failed))
