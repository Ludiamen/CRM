"""Мелкие помощники моделей.

`now()` вызывает `django.utils.timezone.now` при каждом обращении, поэтому подмена
времени в тестах (и в отладке) действует и на значения полей по умолчанию:
ссылка `default=timezone.now` запомнила бы настоящую функцию.
"""
from django.utils import timezone


def now():
    return timezone.now()
