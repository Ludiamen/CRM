---
id: REF-SRC
вид: эталон
статус: черновик
версия: 1
зависит_от: SDD-PROCESS
---

# Реестр источников эталона

Каждое утверждение об эталоне («1С-Битрикс24: Корпоративный портал», коробка)
ссылается на источник отсюда. Проверку, что каждый `SRC-NNN` из документов
зарегистрирован, делает `tools/sdd.py`.

Диапазоны номеров: `SRC-001…099` и `SRC-101…199` — страницы в интернете
(группы модулей «люди и общение» и «работа и процессы»); `SRC-201…299` —
дистрибутив пробной коробки `/home/gpgr/Документы/bitrix24_encode`, главный
модуль 26.150.0 от 2026-02-19 (пути даны от `bitrix/modules/`, если не указано
иное); дальше — снимки экранов демо-стенда (`/home/gpgr/Документы/bitrix-demo`).

## Надёжность источников

- **Дистрибутив — самый точный источник по коробке.** Языковые файлы
  `lang/ru/**.php` — это дословный текст интерфейса именно этой версии;
  страницы справки часто описывают облако или устаревшие редакции.
- **SRC-003 — обзорная страница из 14 пунктов.** Сверка показала, что на ней
  нет ни «лайков», ни упоминаний, ни форума, почты, типов отсутствий: из 51
  ссылки черновика на неё подтвердились около 15 (в основном про рабочие
  группы), остальные перепривязаны к дистрибутиву.
- **SRC-104 — документация API для разработчика**, а не поведение для
  пользователя: как источник возможностей открытых линий не используется.

## Страницы документации

| Источник | Что это | Где | Про что | Дата обращения | Опорная фраза |
|---|---|---|---|---|---|
| SRC-001 | Корпоративный портал — Модули и функции | https://dev.1c-bitrix.ru/user_help/components/intranet/index.php | коробка | 2026-09-29 | управления задачами и поручениями, организации коллективных событий |
| SRC-002 | Веб-мессенджер | https://dev.1c-bitrix.ru/user_help/service/im/index.php | коробка | 2026-09-29 | инструмент, дополняющий обычные способы общения |
| SRC-003 | Корпоративный портал: Основные функции | https://www.1c-bitrix.ru/solutions/corp/features.php | коробка | 2026-09-29 | Живая лента, единый мессенджер с видеозвонками |
| SRC-004 | Календарь событий 2.0 (комплексный компонент) | https://dev.1c-bitrix.ru/user_help/components/content/calendar/calendar.php | коробка | 2026-09-29 | четыре типа календарей: компания, события, группы, пользователь |
| SRC-005 | Собрания и планерки | https://dev.1c-bitrix.ru/user_help/components/intranet/meetings/meetings.php | коробка | 2026-09-29 | комплексный компонент для управления собраниями |
| SRC-006 | Веб-мессенджер. Настройки модуля | https://dev.1c-bitrix.ru/user_help/service/im/settings.php | коробка | 2026-09-29 | видеозвонки, личные диалоги, групповые чаты, открытые чаты |
| SRC-007 | Структура компании (комплексный компонент) | https://dev.1c-bitrix.ru/user_help/components/intranet/intranet_search/intranet_structure.php | коробка | 2026-09-29 | выводит дерево структуры компании со списком сотрудников |
| SRC-008 | Учёт рабочего времени | https://dev.1c-bitrix.ru/user_help/service/timeman/index.php | коробка | 2026-09-29 | ведет учет рабочего времени и учет поставленных и выполненных задач |
| SRC-009 | Список опросов | https://dev.1c-bitrix.ru/user_help/service/vote/vote_list.php | коробка | 2026-09-29 | в каждый опрос может входить один и более вопросов |
| SRC-010 | Форум. Описание модуля | https://dev.1c-bitrix.ru/user_help/service/forum/index.php | коробка | 2026-09-29 | создавать необходимое число форумов, гибкий контроль доступа |
| SRC-011 | Блоги. Описание модуля | https://dev.1c-bitrix.ru/user_help/service/blogs/index.php | коробка | 2026-09-29 | создавать неограниченное число блогов, управлять правами доступа |
| SRC-101 | Задачи (КП). Описание модуля | https://dev.1c-bitrix.ru/user_help/content/tasks/index.php | коробка | 2026-09-29 | управления задачами на портале |
| SRC-102 | CRM (КП) | https://dev.1c-bitrix.ru/user_help/components/crm/index.php | коробка | 2026-09-29 | система для увеличения уровня продаж |
| SRC-103 | Открытые линии (КП). Настройки модуля | https://dev.1c-bitrix.ru/user_help/settings/imopenlines/settings.php | коробка | 2026-09-29 | форма настроек модуля Открытые линии |
| SRC-104 | Открытые линии REST API (D7) | https://dev.1c-bitrix.ru/api_d7/bitrix/imopenlines/index.php | коробка | 2026-09-29 | классы модуля Открытые линии, ядро D7 |
| SRC-105 | Бизнес-процессы. Описание модуля | https://dev.1c-bitrix.ru/user_help/service/bizproc/index.php | коробка | 2026-09-29 | автоматизация бизнес-процессов организации |
| SRC-106 | Диск (КП) — курс администратора | https://dev.1c-bitrix.ru/learning/course/index.php?COURSE_ID=48&CHAPTER_ID=02746 | коробка | 2026-09-29 | работа с документами и совместная работа |
| SRC-107 | Техподдержка. Описание модуля | https://dev.1c-bitrix.ru/user_help/service/support/index.php | коробка | 2026-09-29 | организовать систему обращений посетителей |
| SRC-108 | Администратор системы Битрикс24 (КП) | https://dev.1c-bitrix.ru/learning/course/?COURSE_ID=48&INDEX=Y | коробка | 2026-09-29 | все пользователи получают доступ согласно правам |
| SRC-109 | Настройка работы с документами (Диск) | https://dev.1c-bitrix.ru/learning/course/index.php?COURSE_ID=48&LESSON_ID=13066 | коробка | 2026-09-29 | совместному редактированию требуется HTTPS |
| SRC-110 | Организация работы службы поддержки | https://dev.1c-bitrix.ru/learning/course/index.php?COURSE_ID=48&LESSON_ID=2617 | коробка | 2026-09-29 | организовать систему для обращений |
| SRC-111 | Как работать с чатами в открытых линиях | https://helpdesk.bitrix24.ru/open/28489438/ | общее (справка Битрикс24) | 2026-09-29 | «Нажмите на скрепку и выберите, что хотите создать: задачу или встречу» |
| SRC-112 | Как настроить очередь сотрудников в открытых линиях | https://helpdesk.bitrix24.ru/open/26228062/ | общее (справка Битрикс24) | 2026-09-29 | «обращения будут равномерно распределяться между сотрудниками в очереди» |

## Дистрибутив

| Источник | Что это | Где | Про что | Дата обращения | Опорная фраза |
|---|---|---|---|---|---|
| SRC-201 | Дистрибутив «1С-Битрикс24: Корпоративный портал» (пробная коробка), главный модуль 26.150.0 от 2026-02-19: список модулей bitrix/modules/ с названиями и описаниями из lang/ru/install/index.php | /home/gpgr/Документы/bitrix24_encode/bitrix/modules/ (копия выписки: scratchpad/modules-dist.tsv) | коробка | 2026-09-29 | «1С-Битрикс24: Корпоративный портал» (install.config, productName) |
| SRC-202 | Настройки рейтинга (кнопка «Нравится») | main/lang/ru/admin/rating_settings.php | коробка | 2026-09-29 | Текст кнопки "Мне нравится" до голосования |
| SRC-203 | Комментарии к записям живой ленты | socialnetwork/lang/ru/classes/general/log_comments.php | коробка | 2026-09-29 | Код события живой ленты не верен |
| SRC-204 | Умное слежение за лентой (упоминания в тексте) | socialnetwork/lang/ru/classes/general/log_follow.php | коробка | 2026-09-29 | события, в которых вы являетесь автором, получателем или упомянуты в тексте |
| SRC-205 | Фильтр обсуждений живой ленты | socialnetwork/lang/ru/lib/helper/ui/discussions/discussionsfilter.php | коробка | 2026-09-29 | Важные сообщения; Автор; Избранные записи пользователя |
| SRC-206 | Упоминание пользователя в чате | im/lang/ru/lib/V2/Message/Send/MentionService.php | коробка | 2026-09-29 | Упомянул вас в чате "#TITLE#" |
| SRC-207 | Типы отсутствия сотрудника | intranet/lang/ru/lib/userabsence.php | коробка | 2026-09-29 | отпуск ежегодный; командировка; больничный; отгул за свой счет |
| SRC-208 | Благодарности и их типы | socialnetwork/lang/ru/lib/helper/gratitude.php, lib/component/loglist/gratitude.php | коробка | 2026-09-29 | Благодарности типа «#GRAT_NAME#» |
| SRC-209 | Доска почёта (заголовок раздела) | intranet/lang/ru/public/company/leaders.php | коробка | 2026-09-29 | Доска почета |
| SRC-210 | Wiki: страница по умолчанию, история версий | wiki/install/components/bitrix/wiki.show/lang/ru/component.php | коробка | 2026-09-29 | По каждой странице ведется история, где можно вернуться к любой предыдущей версии |
| SRC-211 | Wiki: категории (рубрики) | wiki/install/components/bitrix/wiki.categories/lang/ru/.description.php, wiki.category/lang/ru/.description.php | коробка | 2026-09-29 | Выводит страницу со списком категорий |
| SRC-212 | Wiki: обсуждение страницы | wiki/install/components/bitrix/wiki.discussion/lang/ru/.description.php | коробка | 2026-09-29 | Выводит обсуждение Wiki страницы |
| SRC-213 | Wiki: теги страницы | wiki/install/components/bitrix/wiki.show/templates/.default/lang/ru/template.php | коробка | 2026-09-29 | Теги |
| SRC-214 | Облако тегов (компонент поиска) | search/install/components/bitrix/search.tags.cloud/.../lang/ru/.description.php | коробка | 2026-09-29 | Вывод ключевых слов (облака тегов) |
| SRC-215 | Wiki: поиск по базе знаний | wiki/install/components/bitrix/wiki/templates/.default/lang/ru/search.php, .../search.page/.default/lang/ru/template.php | коробка | 2026-09-29 | Результаты поиска; Создать страницу %LINK% в этом вики-проекте |
| SRC-216 | Почта: параметры почтового ящика | mail/lang/ru/admin/mail_mailbox_edit.php | коробка | 2026-09-29 | Максимальное количество сообщений, принимаемых за одно соединение |
| SRC-217 | Почта: правило фильтрации писем | mail/lang/ru/admin/mail_filter_edit.php | коробка | 2026-09-29 | Вероятность что сообщение спам; При принудительном вызове правила |
| SRC-218 | Почта: пометка письма как спама | mail/lang/ru/admin/mail_message_view.php | коробка | 2026-09-29 | Пометить как спам |
| SRC-219 | Почта: уведомление о новом письме | mail/lang/ru/lib/integration/im/notification.php | коробка | 2026-09-29 | Новое письмо |
| SRC-220 | Календарь: событие — приглашение участника | calendar/lang/ru/classes/general/calendar_notify.php | коробка | 2026-09-29 | приглашает вас принять участие во встрече |
| SRC-221 | Календарь: форма события (участники, место) | calendar/lang/ru/classes/general/editeventform_js.php | коробка | 2026-09-29 | Количество участников превышает количество мест переговорной |
| SRC-222 | Календарь: автосинхронизация (Google/Office365) | calendar/lang/ru/options.php | коробка | 2026-09-29 | Синхронизировать календари автоматически, по подписке (Push-события от Google/Office365) |
| SRC-223 | DAV: синхронизация CalDAV (iPhone/iPad) | dav/lang/ru/help.php | коробка | 2026-09-29 | поддерживают, например, мобильные устройства iPhone и iPad |
| SRC-224 | Опросы: однократное голосование | vote/lang/ru/classes/general/vote.php | коробка | 2026-09-29 | Вы не можете дважды принимать участие в этом опросе |
| SRC-225 | Опросы: диаграммы результатов | vote/lang/ru/classes/general/channel.php | коробка | 2026-09-29 | Гистограмма; Круговая диаграмма |
| SRC-226 | Опросы: уровень анонимности | vote/lang/ru/lib/vote/anonymity.php | коробка | 2026-09-29 | обычный / публичный (все голоса видны) / анонимный |
| SRC-227 | Wiki: права доступа к модулю | wiki/lang/ru/install/index.php | коробка | 2026-09-29 | Создание/изменение страниц; Удаление страниц и истории |
| SRC-228 | Почта: описание модуля при установке | mail/lang/ru/install/index.php | коробка | 2026-09-29 | Почтовый модуль, для получения почты, фильтрации писем и выполнения заданных действий |
| SRC-250 | Задачи: чек-лист, наблюдатели, проект | bitrix/modules/tasks/lang/ru/lib/item/task/template.php; classes/general/task.php; lib/grid/project/grid.php | коробка | 2026-09-29 | «Чек-лист»; «Наблюдатели»; «Проект» |
| SRC-251 | CRM: роботы автоматизации и воронка (категория сделок) | bitrix/modules/crm/lang/ru/lib/automation/helper.php; lib/automation/tunnelmanager.php | коробка | 2026-09-29 | «Роботы»; «Нет возможности создать туннель в одной воронке» |
| SRC-252 | Открытые линии: интеграция с CRM | bitrix/modules/imopenlines/lang/ru/lib/crm.php | коробка | 2026-09-29 | «На основе контактной информации создан новый лид» |
| SRC-253 | Открытые линии: оценка ответов, очередь операторов, история диалога | bitrix/modules/imopenlines/lang/ru/lib/integrations/report/handlers/mark.php; lib/queue.php; options.php; lib/security/permissions.php; install/events/set_events.php | коробка | 2026-09-29 | «Оценки»; «Диалог снят с оператора, так как оператор в отпуске»; «История переписки в рамках сессии Открытой линии» |
| SRC-254 | Открытые линии: автоматические сообщения (приветствие, нерабочее время, нет ответа) | bitrix/modules/imopenlines/lang/ru/lib/automaticaction/welcome.php; noanswer.php; worktime.php | коробка | 2026-09-29 | WELCOME_MESSAGE_TEXT; WORKTIME_DAYOFF_TEXT |
| SRC-255 | Коннекторы внешних мессенджеров и соцсетей (список компонентов) | bitrix/modules/imconnector/install/components/bitrix/ (imconnector.facebook, .fbinstagram, .fbinstagramdirect, .telegrambot, .viber, .vkgroup, .whatsappbyedna, .whatsappbytwilio, .ok, .avito, .wechat, .livechat) | коробка | 2026-09-29 | список каталогов-коннекторов мессенджеров и соцсетей |
| SRC-256 | Дизайнер бизнес-процессов — отдельный модуль коробки | bitrix/modules/bizprocdesigner/lang/ru/install/index.php; admin/bizproc_wf_settings.php | коробка | 2026-09-29 | «Модуль для проектирования, создания и изменения бизнес-процессов»; «Автоматически запускать: При добавлении / При изменении»; «Триггеры» |
| SRC-257 | Бизнес-процессы: история выполнения, условия, задания | bitrix/modules/bizproc/lang/ru/admin/bizproc_log.php; lib/automation/engine/conditiongroup.php; admin/task.php; admin/task_list.php | коробка | 2026-09-29 | «История выполнения бизнес-процесса»; «Условие»; «Задание»; «Делегировать» |
| SRC-258 | Бизнес-процессы: демо-шаблоны (почта, задача, параллельная группа), вызов REST | bitrix/modules/bizproc/lang/ru/templates/expert.php; templates/vote1st.php; templates/dblapprove.php; lib/restactivity.php | коробка | 2026-09-29 | «назначается экспертная группа, каждый участник которой может высказать своё мнение»; «Почтовое сообщение» |
| SRC-259 | Диск: Мой/Общий/групповой диск, версии, публичные ссылки, квоты | bitrix/modules/disk/lang/ru/lib/uf/controller.php; options.php; lib/file.php; lib/controller/file.php; lib/controller/baseobject.php; bitrix/modules/intranet/lang/ru/lib/Site/Sections/DiskSection.php | коробка | 2026-09-29 | «Мой диск»; «Общий диск»; «Диск группы»; «Разрешить квотирование хранилищ»; «Разрешить использовать публичные ссылки» |
| SRC-260 | Диск: совместное редактирование через OnlyOffice, предпросмотр Google Viewer | bitrix/modules/disk/lang/ru/lib/document/onlyoffice/editor/configbuilder.php; lib/document/googleviewerhandler.php | коробка | 2026-09-29 | «Редактируйте вместе. Обсуждайте. Делитесь.»; «Google Viewer» |
| SRC-261 | Техподдержка: точное описание модуля и роли | bitrix/modules/support/lang/ru/install/index.php | коробка | 2026-09-29 | «Модуль позволяющий организовать на сайте систему обращений посетителей к группе техподдержки»; «клиент техподдержки»; «сотрудник техподдержки» |
| SRC-262 | Техподдержка: категория, критичность, оценка ответов, источник, сложность | bitrix/modules/support/lang/ru/admin/ticket_edit.php; classes/general/dictionary.php | коробка | 2026-09-29 | «Категория обращения»; «Критичность обращения»; «Оценка ответов» |
| SRC-263 | Техподдержка: уровни SLA | bitrix/modules/support/lang/ru/admin/ticket_sla_edit.php; admin/ticket_sla_list.php | коробка | 2026-09-29 | «Уровень техподдержки (SLA)»; «Время реакции на сообщение клиента» |
| SRC-264 | Техподдержка: группа сотрудников техподдержки | bitrix/modules/support/lang/ru/admin/ticket_group_edit.php | коробка | 2026-09-29 | «Группа сотрудников техподдержки» |
| SRC-265 | Техподдержка: частые ответы (шаблоны), купоны | bitrix/modules/support/lang/ru/admin/ticket_dict_list.php; admin/ticket_coupon_edit.php; options.php | коробка | 2026-09-29 | «Частые ответы»; «Уровень поддержки по умолчанию для купонов» |
| SRC-266 | Администрирование: журнал событий, резервное копирование, пользовательские поля | bitrix/modules/main/lang/ru/admin/event_log.php; admin/dump.php; classes/general/usertypemanager.php; admin/userfield_edit.php | коробка | 2026-09-29 | «Журнал событий»; «Резервное копирование» |
| SRC-267 | Проактивная защита: двухэтапная авторизация, IP-стоп-лист | bitrix/modules/security/lang/ru/install/index.php; options_user_settings.php; admin/security_iprule_list.php | коробка | 2026-09-29 | «Двухэтапная авторизация»; «Стоп-лист»; «Модуль проактивной защиты сайта» |
| SRC-268 | AD/LDAP интеграция — отдельный модуль коробки | bitrix/modules/ldap/lang/ru/install/index.php | коробка | 2026-09-29 | «Модуль для работы с Active Directory и LDAP» |
| SRC-269 | Администрирование мобильного приложения | bitrix/modules/mobileapp/lang/ru/admin/mobile_designer.php; admin/menu.php | коробка | 2026-09-29 | административные страницы конструктора мобильного приложения |
| SRC-270 | Облачные хранилища — серверное подключение S3-совместимого хранилища | bitrix/modules/clouds/lang/ru/install/index.php; admin/clouds_storage_edit.php | коробка | 2026-09-29 | «Модуль поддержки облачных хранилищ файлов»; «Провайдер»; «Регион»; «Контейнер» |
