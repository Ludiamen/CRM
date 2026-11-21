# T-8307 — прохождение требований SPEC-008 (черновик таблицы для отчёта)

Источник требования — `specs/008-messenger/spec.md` (FR-643…673, NFR-701…709, 40 строк); тесты — Этап 2
(`backend/tests/test_messenger_*.py`, e2e `m01…m13`) и прежние наборы; реализация — Этап 1/3.
Прогоны: сервер — T-8300 (4400 + 265 + 91), браузер — T-8302, ворота — T-8303. Столбец «Результат» заполняется
после T-8302; до него серверная часть «passed», браузерная — «T-8302».

| Требование | Тест | Реализация | Результат |
|---|---|---|---|
| FR-643 | `test_messenger_models`, `test_messenger_chats`, `test_messenger_permissions`, e2e `m13` | `models.py` (четыре вида), `services/{members,chats}.py`, `migrations/0001` | сервер — passed; e2e — T-8302 |
| FR-644 | `test_messenger_page`, e2e `m01`, `m12` | `services/chats.py::rows`, `views/pages.py`, `_list.html` | сервер — passed; e2e — T-8302 |
| FR-645 | `test_messenger_personal`, `test_messenger_chats`, e2e `m01` | `services/chats.py::personal`, `views/chats.py::create/people`, `_card_write.html` | сервер — passed; e2e — T-8302 |
| FR-646 | `test_messenger_group`, e2e `m02` | `services/chats.py::create/add_members/remove_members`, `views/chats.py::members_change` | сервер — passed; e2e — T-8302 |
| FR-647 | `test_messenger_group`, e2e `m02` | `services/chats.py::leave`, `views/chats.py::leave`, `_confirm.html` | сервер — passed; e2e — T-8302 |
| FR-648 | `test_messenger_group`, `test_messenger_audit`, e2e `m02` | `services/chats.py::delete`, `views/chats.py::delete`, `services/live.py` | сервер — passed; e2e — T-8302 |
| FR-649 | `test_messenger_unit_form`, `test_messenger_department`, e2e `m03` | `services/department.py`, `unit_form.py`, `apps/org/views/structure_forms.py` | сервер — passed; e2e — T-8302 |
| FR-650 | `test_messenger_department`, `test_messenger_core_changes`, e2e `m03` | `services/members.py` (состав на момент просмотра), `department.on_unit_deleted` | сервер — passed; e2e — T-8302 |
| FR-651 | `test_messenger_general`, `test_messenger_settings`, e2e `m04` | `services/chats.py::general`, `services/messenger_settings.py`, `views/settings.py` | сервер — passed; e2e — T-8302 |
| FR-652 | `test_messenger_messages`, `test_messenger_text`, e2e `m01`, `m05` | `services/messages.py::send` (пределы 4 000, NUL, 20 упоминаний) | сервер — passed; e2e — T-8302 |
| FR-653 | `test_messenger_text`, `test_messenger_core_changes`, e2e `m05` | `core/services/text.py`, `messenger/services/text.py` | сервер — passed; e2e — T-8302 |
| FR-654 | `test_messenger_messages`, e2e `m05` | `services/messages.py` (цитата одного уровня), `_message.html` | сервер — passed; e2e — T-8302 |
| FR-655 | `test_messenger_mentions`, e2e `m06` | `services/mentions.py`, `views/mentions.py`, `messenger.js` | сервер — passed; e2e — T-8302 |
| FR-656 | `test_messenger_messages`, e2e `m05` | `services/messages.py::edit`, `_message.html` («изменено») | сервер — passed; e2e — T-8302 |
| FR-657 | `test_messenger_messages`, `test_messenger_files`, e2e `m05` | `services/messages.py::delete`, `_message.html` («Сообщение удалено») | сервер — passed; e2e — T-8302 |
| FR-658 | `test_messenger_page`, e2e `m01` | `services/page.py::history` (курсор без OFFSET), `views/pages.py`, `_history.html` | сервер — passed; e2e — T-8302 |
| FR-659 | `test_messenger_read`, e2e `m08` | `services/read.py`, `_read_line_frame.html` | сервер — passed; e2e — T-8302 |
| FR-660 | `test_messenger_unread`, `test_messenger_live`, e2e `m08` | `services/unread.py`, `services/live.py`, `_badge.html`, `notify.html` | сервер — passed; e2e — T-8302 |
| FR-661 | `test_messenger_live`, `test_messenger_consumers`, e2e `m08` | `services/live.py`, `consumers.py`, `tasks.publish_event`, `routing.py` | сервер — passed; e2e — T-8302 |
| FR-662 | `test_messenger_files, test_messenger_files_2`, `test_messenger_deploy`, e2e `m07` | `services/files.py`, `views/files.py`, `core/services/thumbs.py`, `deploy/nginx*.conf` | сервер — passed; e2e — T-8302 |
| FR-663 | `test_messenger_notify, test_messenger_notify_2, test_messenger_notify_3`, e2e `m09` | `notify_kinds.py`, `notify_rules.py` | сервер — passed; e2e — T-8302 |
| FR-664 | `test_messenger_notify, test_messenger_notify_2, test_messenger_notify_3`, e2e `m06`, `m09` | `notify_rules.py::decide`, `notify_kinds.py` | сервер — passed; e2e — T-8302 |
| FR-665 | `test_messenger_notify, test_messenger_notify_2, test_messenger_notify_3`, `test_notify_prefs*` | каналы — данные `notify` (кода мессенджера нет) | сервер — passed; e2e — T-8302 |
| FR-666 | `test_messenger_notify, test_messenger_notify_2, test_messenger_notify_3`, `test_messenger_live`, e2e `m08`, `m09` | `notify_rules.py` (себе нет, склейка, `still_relevant`) | сервер — passed; e2e — T-8302 |
| FR-667 | `test_messenger_notify_2, test_messenger_notify_3`, `test_notify_pages*`, e2e `m09` | `notify/views/pages.py` (`bell_link`, 302), `messenger/views/notifications.py`, `notify/_list_body.html` | сервер — passed; e2e — T-8302 |
| FR-668 | `test_messenger_search`, e2e `m10` | `services/search.py` (провайдер 61, `ts_headline`), `views/messages.py::chat_search` | сервер — passed; e2e — T-8302 |
| FR-669 | `test_messenger_chats`, `test_messenger_files, test_messenger_files_2`, `test_messenger_search`, e2e `m13` | `services/members.py::get_chat` во всех чтениях; 404/4404 | сервер — passed; e2e — T-8302 |
| FR-670 | `test_messenger_retention`, `test_messenger_settings`, e2e `m11` | `services/retention.py`, `tasks.retention_night`, `config/cron.py` | сервер — passed; e2e — T-8302 |
| FR-671 | `test_messenger_audit`, e2e `m02`, `m03`, `m11` | `chats.delete`, `messenger_settings`, `retention`, `audit_labels.py` | сервер — passed; e2e — T-8302 |
| FR-672 | `test_messenger_department`, e2e `m03` | `views/chats.py::delete` (администратор, подтверждение) | сервер — passed; e2e — T-8302 |
| FR-673 | e2e `m12` | `templates/messenger/*`, `static/messenger/messenger.css` | T-8302 (360 px, две колонки) |
| NFR-701 | `test_messenger_live`, `test_messenger_consumers`, e2e `m08`; locust `WS messenger frame` | `services/live.py`, `consumers.py` | сервер passed; порог — T-8304, поведение — T-8302 |
| NFR-702 | e2e `m12` в четырёх браузерах | `messenger.css` | T-8302 |
| NFR-703 | `test_messenger_search` (`capture_sql`), `test_messenger_page`, границы | параметры SQL во всех `cursor.execute`; белый список ключей | сервер passed |
| NFR-704 | `test_messenger_files, test_messenger_files_2`, e2e `m07` | `services/files.py` (20 МБ, 40 Мп), `nginx` 25m | сервер passed; ClamAV стенда — T-8302 |
| NFR-705 | `test_messenger_notify, test_messenger_notify_2, test_messenger_notify_3` | `notify_kinds.external_text` (постоянный текст) | сервер passed |
| NFR-706 | `test_messenger_retention` | `services/retention.py` (повтор без записей журнала) | сервер passed |
| NFR-707 | `test_messenger_deploy` (наличие профиля) | `tests/load/locustfile.py::MessengerUser`, `fill_messenger.py` | покрыто формально; замер — T-8304 после решения владельца |
| NFR-708 | `test_messenger_deploy` (русский, Москва), e2e `m01`…`m13` | `texts.py`, шаблоны, `page.py` (Europe/Moscow) | сервер — passed; e2e — T-8302 |
| NFR-709 | `test_messenger_audit` (права роли, тест SPEC-006 NFR-508) | журнал ядра, `audit_labels.py`; только дополнение | сервер passed |

**Итог для T-8307:** 40 строк; 39 подтверждаются сервером и/или воротами сразу, 5 ждут браузера (FR-673,
NFR-701 в части поведения, NFR-702, NFR-704 в части ClamAV стенда, NFR-708 в части вёрстки), NFR-707 — только
формально до T-8304. Перевод TASKS-008 в «на-проверке» (`sdd.py на-проверку`) — после T-8302.