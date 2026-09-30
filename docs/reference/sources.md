---
id: REF-SRC
вид: эталон
статус: на-проверке
версия: 2
зависит_от: SDD-PROCESS
подпись: Максим | 2026-09-30T08:43+03:00 | sha256:b072d1f3cc0d04b2ac82cfbd9e432e7d90f03ce01c0fbccab60e590c21ab79c5
---

# Реестр источников эталона

Каждое утверждение об эталоне («1С-Битрикс24: Корпоративный портал», коробка)
ссылается на источник отсюда. Проверку, что каждый `SRC-NNN` из документов
зарегистрирован, делает `tools/sdd.py`.

Диапазоны номеров: `SRC-001…099` и `SRC-101…199` — страницы в интернете
(группы модулей «люди и общение» и «работа и процессы»); `SRC-201…299` —
дистрибутив пробной коробки `/home/gpgr/Документы/bitrix24_encode`, главный
модуль 26.150.0 от 2026-02-19 (пути даны от `bitrix/modules/`, если не указано
иное); `SRC-401…` — снимки экранов тестового портала владельца (коробка,
2026-09-30), файлы лежат вне репозитория в `/home/gpgr/Документы/bitrix-demo/screens/`:
на части снимков видны данные владельца стенда, поэтому в git они не кладутся.

## Надёжность источников

- **Дистрибутив — самый точный источник по коробке.** Языковые файлы
  `lang/ru/**.php` — это дословный текст интерфейса именно этой версии;
  страницы справки часто описывают облако или устаревшие редакции.
- **Дистрибутив перепроверен 2026-09-30.** Копия пропадала с машины, и
  владелец скачал пробную коробку заново в тот же каталог. Версия та же
  (главный модуль 26.150.0 от 2026-02-19, 95 модулей). Все 93 источника
  SRC-201…360 подтверждены повторно: файл на месте, опорная фраза в нём есть.
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
| SRC-003 | Корпоративный портал: Основные функции | https://www.1c-bitrix.ru/solutions/corp/features.php | коробка | 2026-09-29 | «Общайтесь в Живой ленте»; «в едином мессенджере для всей компании: пишите и делайте видеозвонки» |
| SRC-004 | Календарь событий 2.0 (комплексный компонент) | https://dev.1c-bitrix.ru/user_help/components/content/calendar/calendar.php | коробка | 2026-09-29 | четыре типа календарей: компания, события, группы, пользователь |
| SRC-005 | Собрания и планерки | https://dev.1c-bitrix.ru/user_help/components/intranet/meetings/meetings.php | коробка | 2026-09-29 | комплексный компонент для управления собраниями |
| SRC-006 | Веб-мессенджер. Настройки модуля | https://dev.1c-bitrix.ru/user_help/service/im/settings.php | коробка | 2026-09-29 | «групповой чат»; «Открытые чаты»; «Общий чат» |
| SRC-007 | Структура компании (комплексный компонент) | https://dev.1c-bitrix.ru/user_help/components/intranet/intranet_search/intranet_structure.php | коробка | 2026-09-29 | выводит дерево структуры компании со списком сотрудников |
| SRC-008 | Учёт рабочего времени | https://dev.1c-bitrix.ru/user_help/service/timeman/index.php | коробка | 2026-09-29 | ведет учет рабочего времени и учет поставленных и выполненных задач |
| SRC-009 | Список опросов | https://dev.1c-bitrix.ru/user_help/service/vote/vote_list.php | коробка | 2026-09-29 | в каждый опрос может входить один и более вопросов |
| SRC-010 | Форум. Описание модуля | https://dev.1c-bitrix.ru/user_help/service/forum/index.php | коробка | 2026-09-29 | создавать необходимое число форумов, гибкий контроль доступа |
| SRC-011 | Блоги. Описание модуля | https://dev.1c-bitrix.ru/user_help/service/blogs/index.php | коробка | 2026-09-29 | создавать неограниченное число блогов, управлять правами доступа |
| SRC-101 | Задачи (КП). Описание модуля | https://dev.1c-bitrix.ru/user_help/content/tasks/index.php | коробка | 2026-09-29 | управления задачами на портале |
| SRC-102 | CRM (КП) | https://dev.1c-bitrix.ru/user_help/components/crm/index.php | коробка | 2026-09-29 | система, предназначенная для повышения уровня продаж, оптимизации маркетинга и улучшения обслуживания клиентов |
| SRC-103 | Открытые линии (КП). Настройки модуля | https://dev.1c-bitrix.ru/user_help/settings/imopenlines/settings.php | коробка | 2026-09-29 | форма настроек модуля Открытые линии |
| SRC-104 | Открытые линии REST API (D7) | https://dev.1c-bitrix.ru/api_d7/bitrix/imopenlines/index.php | коробка | 2026-09-29 | классы модуля Открытые линии, относящихся к ядру D7 |
| SRC-105 | Бизнес-процессы. Описание модуля | https://dev.1c-bitrix.ru/user_help/service/bizproc/index.php | коробка | 2026-09-29 | автоматизация бизнес-процессов организации |
| SRC-106 | Диск (КП) — курс администратора | https://dev.1c-bitrix.ru/learning/course/index.php?COURSE_ID=48&CHAPTER_ID=02746 | коробка | 2026-09-29 | работа с документами и совместная работа |
| SRC-107 | Техподдержка. Описание модуля | https://dev.1c-bitrix.ru/user_help/service/support/index.php | коробка | 2026-09-29 | организовать на вашем сайте систему обращений посетителей |
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
| SRC-204 | Умное слежение за лентой (упоминания в тексте) | socialnetwork/lang/ru/classes/general/log_follow.php | коробка | 2026-09-29 | событий, в которых вы являетесь автором, получателем или упомянуты в тексте |
| SRC-205 | Фильтр обсуждений живой ленты | socialnetwork/lang/ru/lib/helper/ui/discussions/discussionsfilter.php | коробка | 2026-09-29 | Важные сообщения; Автор; Избранные записи пользователя |
| SRC-206 | Упоминание пользователя в чате | im/lang/ru/lib/V2/Message/Send/MentionService.php | коробка | 2026-09-29 | Упомянул вас в чате "#TITLE#" |
| SRC-207 | Типы отсутствия сотрудника | intranet/lang/ru/lib/userabsence.php | коробка | 2026-09-29 | отпуск ежегодный; командировка; больничный; отгул за свой счет |
| SRC-208 | Благодарности и их типы | socialnetwork/lang/ru/lib/helper/gratitude.php, lib/component/loglist/gratitude.php | коробка | 2026-09-29 | Благодарности типа «#GRAT_NAME#» |
| SRC-209 | Доска почёта (заголовок раздела) | intranet/lang/ru/public/company/leaders.php | коробка | 2026-09-29 | Доска почета |
| SRC-210 | Wiki: страница по умолчанию, история версий | wiki/install/components/bitrix/wiki.show/lang/ru/component.php | коробка | 2026-09-29 | По каждой странице ведется история, где можно вернуться к любой предыдущей версии |
| SRC-211 | Wiki: категории (рубрики) | wiki/install/components/bitrix/wiki.categories/lang/ru/.description.php, wiki.category/lang/ru/.description.php | коробка | 2026-09-29 | Выводит страницу со списком категорий |
| SRC-212 | Wiki: обсуждение страницы | wiki/install/components/bitrix/wiki.discussion/lang/ru/.description.php | коробка | 2026-09-29 | Выводит обсуждение Wiki страницы |
| SRC-213 | Wiki: теги страницы | wiki/install/components/bitrix/wiki.show/templates/.default/lang/ru/template.php | коробка | 2026-09-29 | Теги |
| SRC-214 | Облако тегов (компонент поиска) | search/install/components/bitrix/search.tags.cloud/lang/ru/.description.php | коробка | 2026-09-29 | Вывод ключевых слов (облака тегов) |
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
| SRC-226 | Опросы: уровень анонимности | vote/lang/ru/lib/vote/anonymity.php | коробка | 2026-09-29 | «обычный (пользователь сам решает)»; «публичный (все голоса видны)»; «анонимный» |
| SRC-227 | Wiki: права доступа к модулю | wiki/lang/ru/install/index.php | коробка | 2026-09-29 | Создание/изменение страниц; Удаление страниц и истории |
| SRC-228 | Почта: описание модуля при установке | mail/lang/ru/install/index.php | коробка | 2026-09-29 | Почтовый модуль, для получения почты, фильтрации писем и выполнения заданных действий |
| SRC-250 | Задачи: чек-лист, наблюдатели, проект | bitrix/modules/tasks/lang/ru/lib/item/task/template.php; classes/general/task.php; lib/grid/project/grid.php | коробка | 2026-09-29 | «Чек-лист»; «Наблюдатели»; «Проект» |
| SRC-251 | CRM: роботы автоматизации и воронка (категория сделок) | bitrix/modules/crm/lang/ru/lib/automation/helper.php; lib/automation/tunnelmanager.php | коробка | 2026-09-29 | «Роботы»; «Нет возможности создать туннель в одной воронке» |
| SRC-252 | Открытые линии: интеграция с CRM | bitrix/modules/imopenlines/lang/ru/lib/crm.php | коробка | 2026-09-29 | «На основе контактной информации создан новый лид» |
| SRC-253 | Открытые линии: оценка ответов, очередь операторов, история диалога | bitrix/modules/imopenlines/lang/ru/lib/integrations/report/handlers/mark.php; lib/queue.php; options.php; lib/security/permissions.php; install/events/set_events.php | коробка | 2026-09-29 | «Оценки»; «Диалог снят с оператора, так как оператор находится в отпуске»; «История переписки в рамках сессии Открытой линии» |
| SRC-254 | Открытые линии: автоматические сообщения (приветствие, нерабочее время, нет ответа) | imopenlines/lang/ru/lib/model/config.php | коробка | 2026-09-29 | «Текст автоответа на первое сообщение»; «Правило для сообщений во вне рабочее время»; «Текст при отсутствии ответа» |
| SRC-255 | Коннекторы внешних мессенджеров и соцсетей (список компонентов) | bitrix/modules/imconnector/install/components/bitrix/ (imconnector.facebook, .fbinstagram, .fbinstagramdirect, .telegrambot, .viber, .vkgroup, .whatsappbyedna, .whatsappbytwilio, .ok, .avito, .wechat, .livechat) | коробка | 2026-09-29 | список каталогов-коннекторов мессенджеров и соцсетей |
| SRC-256 | Дизайнер бизнес-процессов — отдельный модуль коробки | bitrix/modules/bizprocdesigner/lang/ru/install/index.php; admin/bizproc_wf_settings.php | коробка | 2026-09-29 | «Модуль для проектирования, создания и изменения бизнес-процессов»; «Автоматически запускать:»; «При добавлении»; «При изменении»; «Триггеры» |
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
| SRC-269 | Администрирование мобильного приложения | bitrix/modules/mobileapp/lang/ru/admin/mobile_designer.php; admin/menu.php | коробка | 2026-09-29 | «Конструктор мобильного приложения»; «Конструктор мобильных приложений» |
| SRC-270 | Облачные хранилища — серверное подключение S3-совместимого хранилища | bitrix/modules/clouds/lang/ru/install/index.php; admin/clouds_storage_edit.php | коробка | 2026-09-29 | «Модуль поддержки облачных хранилищ файлов»; «Провайдер»; «Регион»; «Контейнер» |
| SRC-271 | Задачи: триггеры, которые меняют стадию задачи | tasks/lang/ru/lib/integration/bizproc/automation/trigger/ (status.php, expired.php, expiredsoon.php, tasksfieldchangedtrigger.php, webhook.php, app.php) | коробка | 2026-09-29 | «Меняет стадию, если сотрудник просрочил задачу» |
| SRC-272 | Задачи: схемы автоматизации «Мой план» и «Статусы», стадии статусов | tasks/lang/ru/lib/integration/bizproc/automation/engine/templatesscheme.php | коробка | 2026-09-29 | «Мой план»; «Статусы»; «Ждёт контроля» |
| SRC-273 | Задачи: право на роботов, подчинённость в правах и фильтре | tasks/lang/ru/lib/access/permission/permissiondictionary.php (TASK_ROBOT_EDIT, HINT_TASK_ASSIGNEE_EDIT); tasks/lang/ru/lib/helper/filter.php (TASKS_FILTER_PARAMS_SUBORDINATE) | коробка | 2026-09-29 | «Руководитель наследует право на редактирование задачи от своих подчиненных» |
| SRC-274 | Управление персоналом: подчинённость отделов и команд, руководители и заместители | humanresources/lang/ru/lib/Access/Permission/PermissionDictionary.php; humanresources/lang/ru/lib/Integration/UI/RoleProvider.php | коробка | 2026-09-29 | «Изменение названия, описания и подчинённости» |
| SRC-275 | Автоматизация: когда срабатывает робот на стадии | bizproc/install/components/bitrix/bizproc.automation/templates/.default/lang/ru/template.php | коробка | 2026-09-29 | «Робот сработает сразу после перехода документа в конкретный статус» |
| SRC-301 | HR: увольнение сотрудника из структуры (отдельное от блокировки действие) | humanresources/install/js/humanresources/company-structure/department-content/lang/ru/config.php ($MESS[HUMANRESOURCES_COMPANY_STRUCTURE_DEPARTMENT_CONTENT_TAB_USERS_USER_ACTION_MENU_FIRE_POPUP_DESCRIPTION_M]) | коробка | 2026-09-29 | «не сможет зайти в этот Битрикс24 и будет удалён из структуры компании» |
| SRC-302 | HR: автопривязка чатов/каналов/коллаб к отделу и команде | humanresources/install/js/humanresources/company-structure/chart-wizard/lang/ru/config.php ($MESS[HUMANRESOURCES_COMPANY_STRUCTURE_WIZARD_BINDCHAT_HINT_TITLE]) | коробка | 2026-09-29 | «Весь отдел добавится в нужные чаты и каналы автоматически» |
| SRC-303 | HR: сотрудник-совместитель — членство сразу в нескольких отделах | humanresources/install/js/humanresources/company-structure/chart-wizard/lang/ru/config.php ($MESS[HUMANRESOURCES_COMPANY_STRUCTURE_WIZARD_EMPLOYEE_SAVE_MODE_ADD_USERS_DESCRIPTION]) | коробка | 2026-09-29 | «Сотрудники останутся во всех отделах, куда их добавили» |
| SRC-304 | HR: рабочие отчёты подчинённых — кто из руководителей их получает | humanresources/install/js/humanresources/company-structure/chart-wizard/lang/ru/config.php ($MESS[HUMANRESOURCES_COMPANY_STRUCTURE_WIZARD_DEPARTMENT_SETTINGS_REPORTS_DESCRIPTION]) | коробка | 2026-09-29 | «Выберите, кто из руководителей или заместителей будет получать рабочие отчёты сотрудников отдела» |
| SRC-305 | HR: согласование отпусков и командировок руководителем/заместителем | humanresources/install/js/humanresources/company-structure/chart-wizard/lang/ru/config.php ($MESS[HUMANRESOURCES_COMPANY_STRUCTURE_WIZARD_TEAM_RIGHTS_HINT_1]) | коробка | 2026-09-29 | «согласовывать отпуска и командировки сотрудников» |
| SRC-306 | HR: право «Приглашение новых сотрудников в Битрикс24» | humanresources/lang/ru/lib/Access/Permission/PermissionDictionary.php ($MESS[HUMAN_RESOURCES_USER_INVITE_MSGVER_1]) | коробка | 2026-09-29 | «Приглашение новых сотрудников в Битрикс24» |
| SRC-307 | Интранет: настройка расписания работы и праздников компании/по отделам | intranet/lang/ru/lib/Settings/ScheduleSettings.php ($MESS[INTRANET_SETTINGS_FIELD_LABEL_HOLIDAYS]) | коробка | 2026-09-29 | «Вы можете добавлять любые праздники и выходные дни» |
| SRC-308 | Интранет: защита от утечки данных — водяные знаки на компьютере | intranet/lang/ru/lib/Settings/SecuritySettings.php ($MESS[INTRANET_SETTINGS_FIELD_LABEL_WATER_MARKS_ENABLED]) | коробка | 2026-09-29 | «Водяные знаки для защиты данных на компьютере» |
| SRC-309 | Интранет: автосообщение об увольнении/новом сотруднике в общий чат/ленту | intranet/lang/ru/lib/Settings/CommunicationSettings.php ($MESS[INTRANET_SETTINGS_FIELD_LABEL_ALLOW_LEAVE_MESSAGE], [INTRANET_SETTINGS_FIELD_HINT_SHOW_MESSAGE_NEW_EMPLOYEE_LF_ON]) | коробка | 2026-09-29 | «Отправлять автоматическое сообщение об увольнении сотрудника в "Общий чат"» |
| SRC-310 | Main: уведомление о входе с нового устройства | main/lang/ru/lib/authentication/device.php ($MESS[main_device_message_MSGVER_1]) | коробка | 2026-09-29 | «В ваш аккаунт выполнен вход с нового устройства» |
| SRC-311 | Main: список избранного (личные закладки) | main/lang/ru/admin/favorite_list.php ($MESS[MAIN_RECORDS_LIST]) | коробка | 2026-09-29 | «Список избранного» |
| SRC-312 | Main: CAPTCHA против автоматической регистрации/входа | main/lang/ru/classes/general/user.php ($MESS[MAIN_FUNCTION_REGISTER_CAPTCHA]) | коробка | 2026-09-29 | «Слово для защиты от автоматической регистрации введено неверно» |
| SRC-313 | Main: политика паролей и сессий | main/lang/ru/lib/authentication/policy/rulescollection.php ($MESS[GP_PASSWORD_CHANGE_DAYS], [GP_PASSWORD_LENGTH], [GP_SESSION_TIMEOUT]) | коробка | 2026-09-29 | «Требовать смены пароля через указанное количество дней» |
| SRC-314 | Security: проактивный фильтр (WAF) от известных веб-атак | security/lang/ru/admin/security_filter.php ($MESS[SEC_FILTER_NOTE]) | коробка | 2026-09-29 | «обеспечивает защиту от большинства известных атак на веб-приложения» (перед фразой — «<b>Проактивный фильтр</b>») |
| SRC-315 | Search: статистика поисковых фраз (что искали, куда пришли) | search/lang/ru/admin/search_phrase_stat.php ($MESS[SEARCH_PHS_TITLE], [SEARCH_PHS_404]) | коробка | 2026-09-29 | «Статистика поисковых фраз» |
| SRC-316 | Socialnetwork: коллаба — приглашение внешнего гостя в рабочее пространство | socialnetwork/lang/ru/lib/Collab/Control/Invite/InvitationService.php ($MESS[SONET_COLLAB_INVITE_TEXT]) | коробка | 2026-09-29 | «Приглашение в коллабу "#NAME#"» |
| SRC-317 | Socialnetwork: задача из записи или комментария живой ленты | socialnetwork/lang/ru/lib/commentaux/createtask.php ($MESS[SONET_COMMENTAUX_CREATETASK_POST_BLOG_POST]) | коробка | 2026-09-29 | «Создана задача "#TASK_NAME#" на основании сообщения Живой ленты» |
| SRC-318 | Socialnetwork: поделиться записью ленты с новыми получателями | socialnetwork/lang/ru/lib/commentaux/share.php ($MESS[SONET_COMMENTAUX_SHARE_TEXT]) | коробка | 2026-09-29 | «Новый получатель: #SHARE_LIST#» |
| SRC-319 | Imbot: модуль чат-ботов — боты как участники диалогов | imbot/lang/ru/install/index.php ($MESS[IMBOT_MODULE_DESCRIPTION]) | коробка | 2026-09-29 | «Модуль чат-боты для Битрикс24» |
| SRC-320 | Call: AI-расшифровка и резюме видеозвонков (BitrixGPT) | call/lang/ru/lib/Integration/AI/CallAISettings.php ($MESS[CALL_SETTINGS_COPILOT_HEADER]) | коробка | 2026-09-29 | «BitrixGPT расшифрует видеозвонок, переведет его в текст, выделит главное» |
| SRC-321 | Im: реакции на отдельные сообщения в чате | im/lang/ru/lib/V2/Message/Reaction/ReactionItem.php ($MESS[IM_MESSAGE_REACTION_NAME_LIKE_MSGVER_1]) | коробка | 2026-09-29 | «Нравится»; «Смеюсь»; «Удивляюсь» (реакции на сообщение) |
| SRC-322 | Im: закрепление диалога и сообщения в чате | im/lang/ru/js_common.php ($MESS[IM_M_OL_PIN_ON]); im/lang/ru/lib/V2/Link/Pin/PinService.php | коробка | 2026-09-29 | «Закрепить диалог» |
| SRC-323 | Im: напоминание о сообщении в чате | im/lang/ru/lib/V2/Link/Reminder/ReminderService.php ($MESS[IM_CHAT_REMINDER_REMIND_NOTIFICATION]) | коробка | 2026-09-29 | «Вы просили напомнить вам о сообщении в чате "#CHAT_TITLE#"» |
| SRC-324 | Im: задача прямо из сообщения или целого чата | im/lang/ru/lib/V2/Link/Task/TaskService.php ($MESS[IM_CHAT_TASK_SERVICE_FROM_MESSAGE_NEW_TITLE]) | коробка | 2026-09-29 | «Задача на основании сообщения из чата "#CHAT_TITLE#"» |
| SRC-325 | Landing («Сайты 24»): «База знаний» — отдельный тип сайта в конструкторе, свои права и привязка к группе | landing/lang/ru/lib/site.php ($MESS[LANDING_TYPE_KNOWLEDGE]); lib/rights.php ($MESS[LANDING_RIGHTS_R_KNOWLEDGE24]); lib/connector/socialnetwork.php ($MESS[LANDING_CONNECTOR_SN_TITLE], [LANDING_CONNECTOR_SN_PERMS_EDIT]) | коробка | 2026-09-29 | «База знаний»; «Создание новых баз знаний»; «Кто может редактировать Базу знаний» |
| SRC-326 | Wiki: право на визуальный редактор страниц (WYSIWYG) отдельно от вики-разметки | wiki/lang/ru/install/index.php ($MESS[WIKI_PERM_X]) | коробка | 2026-09-29 | «Создание/изменение страниц в визуальном редакторе» |
| SRC-327 | Support: право читать/получать уведомления группы у участника независимо от назначения | support/lang/ru/admin/ticket_usergroup_edit.php ($MESS[SUP_UGE_USER_CAN_READ_GROUP_MESS], [SUP_UGE_USER_CAN_MAIL_GROUP_MESS]) | коробка | 2026-09-29 | «Пользователь может читать тикеты группы»; «Пользователь может получать уведомления группы» |
| SRC-350 | Задачи: Скрам — бэклог, спринты, диаграмма сгорания | tasks/install/components/bitrix/tasks.scrum/lang/ru/class.php ($MESS['TASKS_SCRUM_SYSTEM_ERROR_ADD_SPRINT']); tasks/lang/ru/lib/scrum/service/sprintservice.php ($MESS['TASKS_SCRUM_SPRINT_START_NOT_TASKS_ERROR']); tasks/install/components/bitrix/tasks.scrum.burn.down/lang/ru/class.php ($MESS['TASKS_SCRUM_BURN_DOWN_TITLE']) | коробка | 2026-09-30 | «Невозможно запустить спринт без задач» |
| SRC-351 | Задачи: потоки — автоматическое распределение повторяющихся задач между командой исполнителей | tasks/install/js/tasks/flow/edit-form/lang/ru/config.php ($MESS['TASKS_FLOW_EDIT_FORM_DISTRIBUTION_QUEUE_HINT'], $MESS['TASKS_FLOW_EDIT_FORM_DISTRIBUTION_IMMUTABLE_HINT']) | коробка | 2026-09-30 | «Новая задача будет автоматически назначена на следующего сотрудника в очереди» |
| SRC-352 | Задачи: учёт времени — таймер выполнения задачи, плановые трудозатраты | tasks/lang/ru/lib/rest/controllers/task.php ($MESS['TASKS_FAILED_START_TASK_TIMER']); tasks/lang/ru/lib/helper/filter.php ($MESS['TASKS_FILTER_TIME_ESTIMATE'], $MESS['TASKS_FILTER_ALLOW_TIME_TRACKING']) | коробка | 2026-09-30 | «Не удалось запустить таймер выполнения задачи» |
| SRC-353 | Задачи: диаграмма Ганта — сроки и зависимости между задачами (4 типа связей) | tasks/lang/ru/gantt.php ($MESS['TASKS_GANTT_CIRCULAR_DEPENDENCY_V2']); tasks/lang/ru/lib/grid/task/row/content/linktype.php ($MESS['TASKS_GRID_ROW_GANTT_FINISH_START']) | коробка | 2026-09-30 | «Нельзя создавать циклическую зависимость» |
| SRC-354 | RPA («Роботизация бизнеса») — конструктор пользовательских типов процессов со своими стадиями и полями | rpa/lang/ru/install/index.php ($MESS['RPA_MODULE_DESCRIPTION']); rpa/install/components/bitrix/rpa.type.detail/templates/.default/lang/ru/template.php ($MESS['RPA_LAUNCH_MANUAL'], $MESS['RPA_LAUNCH_SCHEDULE']); rpa/install/components/bitrix/rpa.stage.detail/lang/ru/class.php ($MESS['RPA_STAGE_MANDATORY_FIELDS_TITLE']) | коробка | 2026-09-30 | «Модуль для организации роботизации бизнеса (RPA)» |
| SRC-355 | Универсальные списки — настраиваемые справочники/реестры с произвольными полями, экспорт в Excel, каталог бизнес-процессов | lists/lang/ru/install/index.php ($MESS['LISTS_MODULE_DESCRIPTION']); lists/install/components/bitrix/lists.export.excel/lang/ru/class.php ($MESS['CC_BLL_DOWNLOAD']); lists/install/components/bitrix/lists.catalog.processes/lang/ru/class.php ($MESS['CC_LCP_TITLE']) | коробка | 2026-09-30 | «Модуль для организации работы с различной информацией из публичной части сайта» |
| SRC-356 | Планерки и собрания — повестка дня, протокол, пункт повестки превращается в задачу | meeting/lang/ru/install/index.php ($MESS['MEETING_MODULE_DESCRIPTION']); meeting/install/components/bitrix/meeting.edit/templates/.default/lang/ru/agenda.php ($MESS['ME_AGENDA_ADD_TASK'], $MESS['ME_PROTO']) | коробка | 2026-09-30 | «Модуль для организации и проведения планерок и собраний» |
| SRC-357 | Календарь: планировщик — показывает занятость приглашённых при подборе времени встречи | calendar/lang/ru/classes/general/calendar.php ($MESS['EC_PLANNER2'], $MESS['EC_NO_GUEST_MESS']) | коробка | 2026-09-30 | «Добавьте участников для просмотра их занятости» |
| SRC-358 | Календарь: публичная ссылка на свободные слоты (calendar sharing) — приглашаемый сам выбирает время | calendar/lang/ru/classes/general/calendar.php ($MESS['CALENDAR_SHARING_COMPONENT_OG_DESCRIPTION']); calendar/lang/ru/lib/sharing/helper.php | коробка | 2026-09-30 | «Здесь вы можете выбрать удобное время для встречи» |
| SRC-359 | Генератор документов — шаблоны .docx/.xlsx с полями слияния (в т.ч. подпись/печать), привязка к разделам | documentgenerator/lang/ru/install/index.php ($MESS['DOCUMENTGENERATOR_MODULE_DESCRIPTION']); documentgenerator/install/components/bitrix/documentgenerator.placeholders/lang/ru/class.php ($MESS['DOCGEN_PLACEHOLDERS_TYPE_STAMP_TITLE']); documentgenerator/install/components/bitrix/documentgenerator.templates/lang/ru/class.php ($MESS['DOCGEN_TEMPLATE_LIST_PROVIDERS']) | коробка | 2026-09-30 | «Модуль для генерации документов» |
| SRC-360 | Открытые линии: перенаправление диалога — оператор передаёт обращение другому сотруднику или в другую линию | imopenlines/lang/ru/lib/model/operatortransfer.php ($MESS['OPERATOR_TRANSFER_ENTITY_TRANSFER_USER_ID_FIELD'], $MESS['OPERATOR_TRANSFER_ENTITY_TRANSFER_LINE_ID_FIELD']); imopenlines/lang/ru/lib/queue/queue.php ($MESS['IMOL_QUEUE_SESSION_TRANSFER_OPERATOR_OFFLINE']) | коробка | 2026-09-30 | «ID пользователя для перенаправления» |
| SRC-276 | Мессенджер: пользователь сам выбирает каналы уведомлений | im/lang/ru/js_im.php (IM_SETTINGS_NC_1_NEW, IM_SETTINGS_NC_2, IM_SETTINGS_NC_4) | коробка | 2026-09-30 | «Получать стандартные уведомления на:» |

## Снимки экранов тестового портала

| Источник | Что это | Где | Про что | Дата обращения | Опорная фраза |
|---|---|---|---|---|---|
| SRC-401 | Страница входа: обычная форма логина и пароля внутри оболочки портала | bitrix-demo/screens/001-login-page.png (/auth/) | коробка, демо-стенд | 2026-09-30 | Пожалуйста, авторизуйтесь: |
| SRC-402 | Главная (Живая лента), левое меню развёрнуто, верхняя панель, правая колонка счётчиков | bitrix-demo/screens/002-home-feed-menu-expanded.png (/stream/) | коробка, демо-стенд | 2026-09-30 | Написать сообщение … |
| SRC-403 | Главная, левое меню свёрнуто до значков | bitrix-demo/screens/003-home-feed-menu-collapsed.png (/stream/) | коробка, демо-стенд | 2026-09-30 | Написать сообщение … |
| SRC-404 | Колокольчик открывает мессенджер поверх страницы на вкладке уведомлений, пустой список | bitrix-demo/screens/004-notifications-in-messenger.png (/stream/ (поверх страницы)) | коробка, демо-стенд | 2026-09-30 | У вас нет новых уведомлений |
| SRC-405 | Меню профиля из аватара: рабочий день, тема, быстрый вход, выход | bitrix-demo/screens/005-profile-menu.png (/stream/ (поверх страницы)) | коробка, демо-стенд | 2026-09-30 | Начать рабочий день |
| SRC-406 | Мессенджер, вкладка «Настройки»: Оформление, Уведомления, Горячие клавиши | bitrix-demo/screens/006-messenger-settings-tab.png (/stream/ (поверх страницы)) | коробка, демо-стенд | 2026-09-30 | Настройки |
| SRC-407 | Мессенджер: список чатов слева, окно «Общий чат» справа, поле ввода | bitrix-demo/screens/007-messenger-chat-window.png (/stream/ (поверх страницы)) | коробка, демо-стенд | 2026-09-30 | Общайтесь с коллегами, обменивайтесь мнениями, делитесь эмоциями |
| SRC-408 | Мессенджер: меню создания чата (групповой чат, канал, видеоконференция) | bitrix-demo/screens/008-messenger-new-chat-menu.png (/stream/ (поверх страницы)) | коробка, демо-стенд | 2026-09-30 | Групповой чат |
| SRC-409 | Настройки уведомлений пользователя: звук, режим, каналы доставки | bitrix-demo/screens/009-messenger-notification-settings.png (/stream/ (поверх страницы)) | коробка, демо-стенд | 2026-09-30 | Куда отправлять уведомления |
| SRC-410 | Список сотрудников: сетка, колонки, групповое действие, пагинация | bitrix-demo/screens/010-employees-grid.png (/company/) | коробка, демо-стенд | 2026-09-30 | Поиск сотрудника |
| SRC-411 | Список сотрудников: панель фильтра с пресетами (Все, Гости, В компании, Уволены, Приглашены) | bitrix-demo/screens/011-employees-filter-presets.png (/company/) | коробка, демо-стенд | 2026-09-30 | Сохранить фильтр |
| SRC-412 | Структура компании (прежняя страница): только название корневого подразделения | bitrix-demo/screens/012-company-structure-legacy.png (/company/structure.php) | коробка, демо-стенд | 2026-09-30 | Экспорт сотрудников в Outlook |
| SRC-413 | Новая структура компании: окно-анонс возможностей поверх схемы | bitrix-demo/screens/013-hr-structure-intro.png (/hr/structure/) | коробка, демо-стенд | 2026-09-30 | Новый визуальный конструктор структуры |
| SRC-414 | Схема структуры: карточка подразделения и боковая панель с руководителями и подчинёнными | bitrix-demo/screens/014-hr-structure-chart-department-panel.png (/hr/structure/) | коробка, демо-стенд | 2026-09-30 | В отделе нет руководителей |
| SRC-415 | Карточка сотрудника в слайдере поверх списка, вкладки профиля | bitrix-demo/screens/015-profile-card-slider.png (/company/personal/user/3/) | коробка, демо-стенд | 2026-09-30 | Контактная информация |
| SRC-416 | Карточка сотрудника: меню «Еще» с настройкой и скрытием вкладок | bitrix-demo/screens/016-profile-tabs-customize-menu.png (/company/personal/user/3/) | коробка, демо-стенд | 2026-09-30 | Настроить меню |
| SRC-417 | Двухэтапная авторизация: страница подключения по шагам (секрет на экране не попал) | bitrix-demo/screens/017-security-two-factor.png (/company/personal/user/3/security/) | коробка, демо-стенд | 2026-09-30 | Настройка дополнительной защиты |
| SRC-418 | Пароли приложений для внешних программ | bitrix-demo/screens/018-security-app-passwords.png (/company/personal/user/3/passwords/) | коробка, демо-стенд | 2026-09-30 | Пароли приложений |
| SRC-419 | Слайдер безопасности: пароль, выход со всех устройств, разделы настроек | bitrix-demo/screens/019-security-settings-slider.png (/company/personal/user/3/common_security/) | коробка, демо-стенд | 2026-09-30 | Защитите свой аккаунт и будьте уверены, что личные и корпоративные данные в безопасности |
| SRC-420 | История входов: поверх таблицы открылась справка о том, что функцию надо включить в настройках | bitrix-demo/screens/020-login-history-help.png (/company/personal/user/3/common_security/ (слайдер)) | коробка, демо-стенд | 2026-09-30 | Настройка работы истории входов в коробке |
| SRC-421 | История входов: таблица с колонками устройство, платформа, браузер, IP; пуста | bitrix-demo/screens/021-login-history-table.png (/company/personal/user/3/common_security/ (слайдер)) | коробка, демо-стенд | 2026-09-30 | Нет данных |
| SRC-422 | Виджет «Пригласить сотрудников»: счётчик лицензии, структура, коллабы | bitrix-demo/screens/022-invite-widget.png (/stream/ (поверх страницы)) | коробка, демо-стенд | 2026-09-30 | Пригласите сотрудников |
| SRC-423 | Меню «Настройки» внизу левого меню | bitrix-demo/screens/023-left-menu-settings-menu.png (/stream/ (поверх страницы)) | коробка, демо-стенд | 2026-09-30 | Настройка левого меню |
| SRC-424 | Подменю настройки левого меню: настроить пункты, свернуть, добавить ссылку, вернуть по умолчанию | bitrix-demo/screens/024-left-menu-customize-submenu.png (/stream/ (поверх страницы)) | коробка, демо-стенд | 2026-09-30 | Настроить пункты |
| SRC-425 | Поиск верхней панели: результаты по сотрудникам, диску, задачам и разделам «Искать в» | bitrix-demo/screens/025-top-search-popup.png (/stream/ (поверх страницы)) | коробка, демо-стенд | 2026-09-30 | Искать в |
| SRC-426 | Создание задачи в слайдере: поля и необязательные блоки-плитки, справа чат задачи | bitrix-demo/screens/026-task-create-slider.png (/company/personal/user/3/tasks/task/edit/0/) | коробка, демо-стенд | 2026-09-30 | Название задачи |
| SRC-427 | Список задач: сетка, счётчики, групповое действие, пагинация | bitrix-demo/screens/027-tasks-list-grid.png (/company/personal/user/3/tasks/) | коробка, демо-стенд | 2026-09-30 | Мои задачи |
| SRC-428 | Панель фильтра задач: пресеты слева, поля справа, «Сохранить фильтр» | bitrix-demo/screens/028-tasks-filter-presets.png (/company/personal/user/3/tasks/) | коробка, демо-стенд | 2026-09-30 | Сохранить фильтр |
| SRC-429 | Карточка задачи в слайдере поверх списка, справа чат и события | bitrix-demo/screens/029-task-card-slider.png (/company/personal/user/3/tasks/task/view/2/) | коробка, демо-стенд | 2026-09-30 | Постановщик |
| SRC-430 | Карточка задачи: меню действий | bitrix-demo/screens/030-task-card-menu.png (/company/personal/user/3/tasks/task/view/2/) | коробка, демо-стенд | 2026-09-30 | Создать подзадачу |
| SRC-431 | Лента: форма новой записи с полем «Кому» | bitrix-demo/screens/031-feed-post-form.png (/stream/) | коробка, демо-стенд | 2026-09-30 | Всем сотрудникам |
| SRC-432 | Лента: выбор адресатов записи (Всем сотрудникам, сотрудники, гость) | bitrix-demo/screens/032-feed-recipients-picker.png (/stream/) | коробка, демо-стенд | 2026-09-30 | Пригласить гостя |
| SRC-433 | Лента: типы записей в меню «Ещё» (Благодарность, Важное сообщение, Процессы) | bitrix-demo/screens/033-feed-post-types-menu.png (/stream/) | коробка, демо-стенд | 2026-09-30 | Важное сообщение |
| SRC-434 | Лента: меню «Ещё» у записи (закрепить, избранное, задача из записи) | bitrix-demo/screens/034-feed-post-more-menu.png (/stream/) | коробка, демо-стенд | 2026-09-30 | Добавить в избранное |
| SRC-435 | Лента: поле комментария под записью развёрнуто | bitrix-demo/screens/035-feed-comment-form.png (/stream/) | коробка, демо-стенд | 2026-09-30 | Создать документ |
| SRC-436 | Лента: меню параметров ленты («Умное слежение») | bitrix-demo/screens/036-feed-options-menu.png (/stream/) | коробка, демо-стенд | 2026-09-30 | Умное слежение |
| SRC-437 | База знаний: пустой список, создание новой базы | bitrix-demo/screens/037-knowledge-base-index.png (/kb/) | коробка, демо-стенд | 2026-09-30 | Новая база знаний |
| SRC-438 | Универсальные списки: страница без содержимого (нет списков или нет прав) | bitrix-demo/screens/038-lists-index-empty.png (/services/lists/) | коробка, демо-стенд | 2026-09-30 | Списки |
| SRC-439 | Группы и проекты: сетка с фильтром «Активные», пустая | bitrix-demo/screens/039-workgroups-list.png (/workgroups/) | коробка, демо-стенд | 2026-09-30 | Создайте группу или проект |
| SRC-440 | Телефонный User-Agent: окно с предложением открыть мобильное приложение | bitrix-demo/screens/040-mobile-app-prompt.png (/stream/) | коробка, демо-стенд | 2026-09-30 | Чтобы войти в Битрикс24, откройте приложение |
| SRC-441 | Главная при ширине 390 px: форма записи обрезана, колонка счётчиков выходит за экран | bitrix-demo/screens/041-mobile-feed-390.png (/stream/) | коробка, демо-стенд | 2026-09-30 | Мои задачи |
| SRC-442 | Список задач при ширине 390 px: сетка шире экрана, прокручивается вбок | bitrix-demo/screens/042-mobile-tasks-list-390.png (/company/personal/user/3/tasks/) | коробка, демо-стенд | 2026-09-30 | Выберите действие |
| SRC-443 | Карточка задачи при ширине 390 px: слайдер шире экрана, правая часть срезана | bitrix-demo/screens/043-mobile-task-card-390.png (/company/personal/user/3/tasks/task/view/2/) | коробка, демо-стенд | 2026-09-30 | Постановщик |
| SRC-444 | Настройки портала: слайдер с разделами; содержимое тестовому пользователю не загружается | bitrix-demo/screens/044-portal-settings.png (/configs/) | коробка, тестовый портал владельца | 2026-09-30 | «Мой Битрикс24», «Сотрудники», «Расписание», «Безопасность» |
| SRC-445 | Лента: форма с вкладками, запись с адресатами, кнопки «Нравится» и «Комментировать» и пустое поле комментария; автозапись «Добавлен новый сотрудник»; блок «Мои задачи» со счётчиками | bitrix-demo/screens/045-feed-post-with-comment.png (/stream/) | коробка, тестовый портал владельца | 2026-09-30 | «Добавлен новый сотрудник» |
| SRC-446 | Лента: форма «Важное сообщение» — адресаты и срок важности | bitrix-demo/screens/046-feed-important-form.png (/stream/) | коробка, тестовый портал владельца | 2026-09-30 | «сообщение будет важным: неделю» |
| SRC-447 | Лента: опубликованное важное сообщение с подтверждением прочтения | bitrix-demo/screens/047-feed-important-post.png (/stream/) | коробка, тестовый портал владельца | 2026-09-30 | «С сообщением ознакомлен, уже подтвердили прочтение» |
| SRC-448 | Виджет приглашения: структура, сотрудники с лимитом лицензии, коллабы | bitrix-demo/screens/048-invite-dialog.png (/services/lists/, верхняя панель) | коробка, тестовый портал владельца | 2026-09-30 | «Сотрудники 2 из 25», «Смогут работать еще 23» |
| SRC-449 | Журнал изменений в разделе «Сервисы»: тестовому пользователю закрыт | bitrix-demo/screens/049-change-log.png (/services/event_list.php) | коробка, тестовый портал владельца | 2026-09-30 | «Журнал изменений», «ACCESS_DENIED» |
