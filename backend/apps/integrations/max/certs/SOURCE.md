# Корень «Russian Trusted Root CA» для адаптера MAX

- Файл: `russian_trusted_root_ca.crt` (в PLAN-004 и TASKS-004 назван `.pem`; расширение `.crt` — решение владельца
  2026-10-10: тест `test_deploy_files.py` считает закрытым ключом любой `.pem` вне `deploy/certs/`).
- Назначение: единственный доверенный корень в соединениях адаптера MAX с `platform-api2.max.ru` (ADR-0011 п. 13;
  PLAN-004, «Новые компоненты и лицензии», «Telegram и MAX» → доверие TLS). Системное хранилище сертификатов не
  меняется.
- Источник: https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer (файловый сервер Госуслуг), скачан
  2026-10-10.
- Субъект и издатель: `C=RU, O=The Ministry of Digital Development and Communications, CN=Russian Trusted Root CA`
  (самоподписанный).
- Срок: 2022-03-01 — 2032-02-27.
- SHA-256: `D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31`.
- Сверка отпечатка с публикацией на gosuslugi.ru/crt в браузере — владелец, T-4307 (TASKS-004).
