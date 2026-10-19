"""Перерисовка статей и версий после смены правил вывода (план 005, «Модель данных»; контракт 13, C-13).

Запускается без `E2E_STAND`: это команда обновления. Порциями по возрастанию номера, каждая порция — своя
транзакция; `updated_at`, `updated_by`, `version_no` и `text` не меняются, журнал и события не пишутся.
"""
import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.knowledge.models import Article, ArticleVersion
from apps.knowledge.services import files, render, vectors

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Перерисовывает html и plain всех статей и html всех версий порциями."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=200, help="статей в порции (1–1000, по умолчанию 200)")

    def handle(self, *args, **options):
        size = options["batch_size"]
        if not 1 <= size <= 1000:
            raise CommandError("--batch-size: целое от 1 до 1000.")
        articles = versions = 0
        last = 0
        while True:
            batch = list(Article.objects.filter(pk__gt=last).order_by("pk")[:size])
            if not batch:
                break
            last = batch[-1].pk
            with transaction.atomic():
                for article in batch:
                    done = self._rerender(article)
                    if done is not None:
                        articles += 1
                        versions += done
        self.stdout.write(f"kb_rerender: articles={articles} versions={versions}")

    def _rerender(self, article: Article) -> int | None:
        """Перерисовывает одну статью и её версии; ошибка рендера — в журнал, обход продолжается."""
        files_map = files.files_map(article)  # вне try: отсутствие функции или сбой запроса падают явно
        try:
            result = render.render(article.text, files_map, article.pk)
            version_html = [(v.pk, render.render(v.text, files_map, article.pk).html)
                            for v in ArticleVersion.objects.filter(article=article).only("pk", "text")]
        except Exception as exc:  # noqa: BLE001 — одна плохая статья не должна останавливать обход
            log.warning("kb_rerender: статья %s не перерисована: %s", article.pk, type(exc).__name__)
            return None
        Article.objects.filter(pk=article.pk).update(html=result.html, plain=result.plain)
        for pk, html in version_html:
            ArticleVersion.objects.filter(pk=pk).update(html=html)
        if article.state == Article.State.PUBLISHED:
            vectors.refresh([article.pk])
        return len(version_html)
