# Сторонняя статика (без CDN, NFR-007)

Файлы лежат в репозитории без правок: их содержимое совпадает с файлами из
пакетов реестра npm. Инварианты конституции к ним не применяются (поле
`не_проверять` в `docs/constitution.json`). Сверку выполняет
`python3 tools/verify_vendor.py` (она же — часть `tools/verify.sh`): скачивает
пакеты из реестра, сверяет sha256 и тексты лицензий, ищет `new Function` в
Alpine и внешние адреса в Bootstrap и HTMX, сообщает, если в своей ветке
вышла версия новее.

Проверено: 2026-10-01 (Sonnet, задача T-003).

## Bootstrap 5.3.8

- **Версия**: 5.3.8 (последняя в ветке 5.3 на 2026-10-01)
- **Лицензия**: MIT (`LICENSE-bootstrap`, взят из пакета)
- **Пакет**: https://registry.npmjs.org/bootstrap/-/bootstrap-5.3.8.tgz

| Файл | Файл в пакете | SHA256 |
|------|---------------|--------|
| bootstrap-5.3.8.min.css | package/dist/css/bootstrap.min.css | d85327d99c7a3ee1f9b5d0500d1370acea3ad2db39c163c2f51f232baedbdede |
| bootstrap-5.3.8.bundle.min.js | package/dist/js/bootstrap.bundle.min.js | e4fd49181388c48ec5040bd3fe66f57c29c8e67fcd8502b3354b96ec7ab47cc7 |

## HTMX 2.0.11

- **Версия**: 2.0.11 (последняя в ветке 2.x на 2026-10-01; ветка `next` 4.x — предварительная)
- **Лицензия**: 0BSD (`LICENSE-htmx`, взят из пакета)
- **Пакет**: https://registry.npmjs.org/htmx.org/-/htmx.org-2.0.11.tgz

| Файл | Файл в пакете | SHA256 |
|------|---------------|--------|
| htmx-2.0.11.min.js | package/dist/htmx.min.js | d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717 |

## Alpine.js CSP 3.17.4

- **Версия**: 3.17.4 (`@alpinejs/csp`, последняя в ветке 3.x на 2026-10-01)
- **Лицензия**: MIT (`LICENSE-alpine`: текст `LICENSE.md` репозитория alpinejs/alpine на теге v3.17.4; в самом пакете файла лицензии нет, в `package.json` указано MIT)
- **Пакет**: https://registry.npmjs.org/@alpinejs/csp/-/csp-3.17.4.tgz

| Файл | Файл в пакете | SHA256 |
|------|---------------|--------|
| alpine-3.17.4.csp.min.js | package/dist/cdn.min.js | 0d18d7f8d7910e2e0212f0f056b12f50bebc3abb7d88d2f7c7cb4c336fe4519a |

## Расхождения, найденные при проверке (T-003)

1. Bootstrap 5.3.3 был не последним в ветке 5.3: вышла 5.3.8. Файлы заменены
   на 5.3.8 (имена `bootstrap-5.3.8.*`), `LICENSE-bootstrap` взят из пакета
   (был с годами 2011-2024, теперь по тексту пакета).
2. `LICENSE-alpine` в черновике Haiku не совпадал с текстом проекта
   («Alpine.js contributors», 2021-2024); заменён текстом из репозитория
   alpinejs/alpine (v3.17.4).
3. Остальное совпало: sha256 HTMX 2.0.11 и Alpine CSP 3.17.4 равны хешам
   файлов из пакетов; `LICENSE-htmx` побайтно равен лицензии пакета; в Alpine
   нет `new Function`; во внешних адресах Bootstrap и HTMX — только
   комментарии заголовков и `xmlns` в data-URI, запросов наружу они не делают.
4. В Bootstrap остались комментарии `sourceMappingURL=…map`: файлов `.map`
   нет, запрос идёт только при открытых инструментах разработчика и CSP не
   нарушает.

## Лицензии

Тексты лицензий — в файлах `LICENSE-*` рядом.
