# Передача между сессиями — портал ИТ-отдела (CRM)

> **Актуальный краткий статус — 2026-11-12 21:00.** T-7260 **принята владельцем и отмечена `[x]`**;
> открыт этап 4 (T-7300 → T-7301 → T-7302 → T-7303). Финальный полный сервер на финализированном source
> (после ADR-0016): **4118 passed, exit 0**, `full-server-20261112-194929-2frLFm/`, source-integrity 1168/1168,
> `actual_database=test_crm`, состав nodeid = 4118 (0 added/removed). Полный browser gate RED (160F) разобран:
> 52F регрессии `pick_mention` — 52/52 (13×4); 2F flaky прошли на остывшей машине; 106F — P1 64/64, P2 23/24,
> среда 30/31, k12 через ADR-0016 (порог 1,5 с, подписан 2026-11-12T19:35; Chromium+Yandex 2/2 PASSED);
> E05 webpush прошёл. SDD 105/0/0, tools 140/140, diff-check чист.
> **Единственный отложенный владельцем пункт — firefox G4a** (известный edge, не блокер).
> **T-7300:** зелёный серверный прогон 4118/4118 сверен с красным T-7160 по полным nodeid — 0 потерянных,
> 768/768 прежних падений зелены; +285/−1 (замена WebPush-теста по решению владельца 08.11), ослаблений нет;
> порог `test_capacity` 25→27 (+2 запроса контрактного бейджа «Ленты») подтверждён владельцем 2026-11-13;
> сводка по 42 FR и 14 NFR — в `docs/reviews/TASKS-007.md`, раздел «Прогон тестов (T-7300)».
> Независимая проверка (другая модель, read-only) — **APPROVE**, `crm-work/slice007/stage3/T7300-review/review.md`;
> T-7300 отмечена `[x]` 2026-11-13. Далее T-7301 (ручной проход в браузере).
> **T-7301 проход выполнен 2026-11-13** (партии A–G на копии before-T7301-20261113-065641): сценарии 1–15 в
> настоящих Chrome/Firefox; 360 px — Firefox 24/24, **Chrome 21/24** (прокрутка ≈11 px в шапке записи, NFR-606);
> CSP закрыт как артефакт `full_page`-снимков (без снимков 0); подтверждены `htmx:oobErrorNoTarget` (удаление
> записи/комментария, привязка Telegram) и гонка FR-614 (Chrome 9/20, Firefox 1/1 — кадр WS раньше XHR);
> ClamAV-down: файл `pending`, без скачивания, после запуска `clean`. **T-7301 `[ ]` — три дефекта, нужно решение
> владельца о правках**; сводка — docs/reviews/TASKS-007.md, «Проход в браузере (T-7301)».
> **Правки T-7301 выполнены (2026-11-13):** `feed.js` — перенос по номеру записи (FR-614) и фильтр OOB без цели
> (WS + HTTP через `htmx.logger`); `feed.css` — `flex-wrap` в базовом правиле шапки; новый
> `test_f_t7301_regressions.py` 5×2. RED 9F/1P и 360 Chrome 362>345 → **GREEN 10/10 exit0**,
> стенд `before-T7301-fixes-20261113-202309`, хэши c2ef50df/20f2c3e0. Независимое ревью GLM-5.3 — **APPROVE**.
> Профиль 125P/2F/1E: f07 — флейк (изолированно PASS); f02 «истёкшая важная → правка» — **предшествующий дефект**
> (на HEAD так же: `until` ниже min блокирует POST), не регрессия. T-7301 `[ ]` до решения владельца по этому
> дефекту; полный сервер после правок — идёт.
> **Полный сервер после правок: 4118P/exit0** (`full-server-20261113-220512-AKvCzN/`, integrity 1170/1170,
> nodeid идентичен). **Владелец 2026-11-14 решил:** исправить предшествующий дефект формы правки (`until` ниже
> `min` блокирует POST), затем закрыть T-7301 и перейти к T-7302. Автор — Qwen3.8 Max, scope-edit-form.md.
> **Дефект until исправлен (r2/r3):** `syncUntilField` в feed.js — until активен/required только при
> `kind=important` и `term=date`, иначе очищается/отключается (учёт вида при смене). Тесты 6 (правка истёкшей) и
> 7 (important+date → сообщение) — RED на прежнем продукте, **GREEN 14/14** (`green-20261114-055913-9haty9/`);
> f02-файл **32P** (Chromium+Firefox), f07 PASS; ревью r2/r3 — **APPROVE**. Финальный полный сервер
> `full-server-20261114-064231-C5Sjyd/`: **4118P/exit0**, nodeid идентичен. **T-7301 закрыта `[x]` 2026-11-14**;
> следующий — **T-7302** (runner `crm-work/slice007/stage4/t7302/run-t7302.sh`).
> **Правило (владелец, 2026-11-14):** коммиты делает агент самостоятельно; `git push` — только владелец.
> **T-7302 запущена** 2026-11-14 08:04, unit `crm-T7302-acceptance-20261114`, каталог
> `slice007/stage4/t7302/T7302-before-T7301-fixes-20261114-055757-KflImT/`: 2254 nodeid (chromium 938,
> firefox 201, edge 202, yandex 913), ожидание ~21 ч; не опрашивать/не дублировать.
> Визуальный просмотр 55 листов — 0 блокеров. **Владелец 2026-11-13 разрешил исправить все три дефекта
> отдельной партией** (`crm-work/slice007/stage4/t7301-fixes/scope.md`): FR-614 (feed.js), OOB без цели,
> 360 px Chrome; TDD tests.diff→RED→fix.diff→GREEN, затем reset/профильные e2e/полный сервер/повтор пунктов.
> Прежний прогон 4070 и другие завершённые прогоны не повторять; детали — ниже.
> Владелец согласовал точный Web Push SDD diff `T7260-webpush-sdd/proposal-r1/`.
> PLAN-004 v2 **подписан владельцем 2026-11-09 07:02+03**, подпись/статус/hash проверены
> (`34f29b4fb7faf48786643e67d17d1290584bfcd49df4645d8073a04edfe313b2`).
> TASKS-004 v2 и companion CONTRACT-004 перенесены, побайтно совпадают с согласованными кандидатами.
> TASKS-004 v2 **подписан владельцем 2026-11-09 07:38+03**, подпись/hash/статус проверены.
> Текущий TASKS body hash:
> `dcfcfc51e9b51a1a4980bf4f8d691ae24fb8c8784d52d07403ceb746760f2091`.
> SDD-проверка: **103 документа, 0 ошибок/предупреждений**, PLAN-005/006/007 не переписывались.
> Стенд обновлён после проверенной копии `before-T7260-20261109-074113`; миграций нет, health/image PASS.
> **Запущен focused Chromium gate из шести существующих сценариев**: unit
> `crm-T7260-remediation-focused-20261109`, shell `sh_1be9d97cf001JjdYoHzD3eNZgK`.
> Runner: `crm-work/slice007/stage3/run-T7260-remediation-focused.sh`; reset перед кругом штатной фикстурой.
> Focused6 завершён: **5 passed / 1 failed** (F10 ожидал navigation; POST edit200 с карточкой без файла есть).
> Артефакты: `browser-gate/remediation-focused-before-T7260-20261109-074113-e5YSCr/`.
> Владелец отдельно разрешил точный `T7260-f10-wait-proposal.patch` (только wait helper, все file/404 asserts сохранены).
> Kimi применил точный diff; оркестратор сверил его и запустил **только F10 Chromium**:
> unit `crm-T7260-f10-wait-focused-20261109`, shell `sh_1beaa4c410012NHWNWXfFnLq88`,
> `run-T7260-f10-wait-focused.sh` с этой меткой копии и reset. Ждать события, не дублировать/не опрашивать.
> F10 завершён RED в `f10-wait-before-T7260-20261109-074113-f3MYzg/`: POST200/article прошли,
> added count0 использует широкий ленивый locator и находит новую форму комментария. Download404 ещё не достигнут.
> Qwen locator-review.md — APPROVE, прочитан; владелец отдельно разрешил однострочную коррекцию.
> Она применена, AST/diff-check PASS; **запущен только F10 Chromium**: unit
> `crm-T7260-f10-edit-form-focused-20261109`, shell `sh_1befc2ad70017MnmvrSYIk0faa`.
> F10 завершён **PASSED, exit0**, `f10-wait-before-T7260-20261109-074113-haWZ7f/`:
> дошёл до всех assertions, включая file removal и download404. Вместе с прежними5PASSED это шесть успешных
> Chromium cases из двух прогонов, не один общий GREEN6. Qwen сверяет actual diff и результаты:
> ожидается `T7260-f10-wait-fix/result-review.md`. Затем те же6 в Firefox/Edge/Yandex (18cases);
> Qwen result-review.md прочитан — **APPROVE scope/доказательств**. Запущены Firefox/Edge/Yandex18cases:
> unit `crm-T7260-remediation-other-browsers-20261109`, shell `sh_1bf066a0e001LvNar2HckD0T0U`,
> `run-T7260-remediation-other-browsers.sh`, backup тот же, reset перед каждым кругом, source hashes сохраняются.
> Прогон 18 завершён **18 passed, exit0, source-integrity=ok**, по6 Firefox/Edge/Yandex, без skip/error/failure.
> Артефакты: `browser-gate/remediation-other-browsers-before-T7260-20261109-074113-Smdtpe/`.
> Qwen `review.md` прочитан — **APPROVE доказательств focused18**. Не повторять завершённый прогон.
> Начата следующая узкая DOM-партия Kimi `ses_e41586104ffexHVeTSoRqMZH1E`: только `_form_comment.html`,
> `body.html`, `card.html` и новый `test_feed_dom_targets_regressions.py`; реальные RED unit/client harness до кода.
> Артефакты: `T7260-dom-blockers/implementation/`. Existing tests/JS/consumer/контракты/стенд не менять.
> Важно: `hx-swap-oob="true"` = **outerHTML**, неверное innerHTML-объяснение source-analysis исправлено оркестратором.
> Последний fullserver4070P был **до этой партии**; после неё нужны fresh review/регрессия/обновление стенда по копии.
> Остальные5PASSED не повторять без причины.

> **Текущий стоп — аудит DOM-прогонов.** Исполнитель сообщил другой lock
> `/tmp/opencode/test.lock` и DB/Valkey проектных контейнеров вместо назначенного test-profile/общей блокировки.
> Заявленные RED/GREEN и 91 existing PASSED пока **не приняты**; DOM на стенд не развёрнут.
> Запрошена реконструкция фактических команд и окружения из истории автора:
> `T7260-dom-blockers/implementation/execution-audit.md`, агент `ses_e41586104ffexHVeTSoRqMZH1E`.
> Только read-only: не повторять тесты, не очищать БД/Valkey и не обновлять стенд до выяснения изоляции.
> Влияние на dev-данные/кэш пока **не установлено**, ни безопасность, ни повреждение не подтверждены.
> Исходники нового теста/harness прочитаны; их пригодность и происхождение RED ещё требуют проверки.
> Аудит автора получен/прочитан. Сохранённый `/tmp/opencode/run_regression.sh` сверён: IP PostgreSQL стенда,
> Valkey db15; штатный compose test использует те же сервисы и db15, но запуск был с хоста и под неверным lock.
> Текущие web/web-heavy действительно используют Valkey db0 (прочитаны только безопасные поля metadata).
> Separate test DB следует из штатной conftest, но фактическое runtime-имя в evidence не сохранено;
> историческая конкурентность/полная сохранность данных не доказаны. В journal записей по пяти invocation ID нет.
> Harness RED по первичному TOTAL = **1P/7F**, не заявленные ранее0/8; GREEN8P/0F.
> Идёт независимое read-only review кода/тестов/доказательств K3.1:
> `ses_e40c3f14dffe0EI3vPc8qSgf6t`, ожидается `implementation/independent-review.md`.
> Никаких новых тестов, cleanup/reset и изменения стенда в этом аудите не выполнялось.
> Независимый `implementation/independent-review.md` получен/прочитан: production без required-правок,
> **верификация заблокирована R1–R4**. GREEN-логи не содержат pytest-итогов, старые числа11/91 не подтверждены.
> Claims отчётов сужены с сохранением исходных копий; raw evidence не перезаписано, harness не доказывает submit/lifecycle.
> **Запущена новая controlled verification**: unit `crm-T7260-dom-controlled-20261109`,
> shell `sh_1bf493a4e0016AUymECWwigSmS`, runner `T7260-dom-blockers/run-controlled-verification.sh`.
> Общий lock/test-profile/systemd; RED на одноразовых ro-копиях трёх шаблонов без targets (ожидается7F4P),
> затем текущие11+91cases (ожидается102P), JUnit/полные закрытые логи/runtime DB metadata/source hashes.
> Рабочее дерево не мутируется, стенд не обновляется. Ждать события, не опрашивать/не дублировать;
> при неожиданном результате runner останавливается. До результата source freeze.
> Controlled завершён `controlled-20261109-105009-py79oG/`: **RED7F4P, GREEN102P**, exit0,
> JUnit и source/mutated hashes сверены. Независимое resultreview запущено у K3.1, ожидается run/review.md.
> Обнаружен пробел metadata plugin v1: runtime.jsonl содержит только configured db15/expectedtest_crm,
> без actual DB — dynamic fixture не попала в item.fixturenames.102PASSED не отменяет этот пробел.
> V1/evidence не менялись. Новый v2 фиксирует identity после django_db_setup и SELECT current_database().
> **Запущен один DB-test** для проверки v2: `crm-T7260-dom-db-identity-20261109`, shell
> `sh_1bf4d3a930018CSfTY0DdnR0rE`, runner `T7260-dom-blockers/run-db-identity-check.sh`.
> Ждать события, не дублировать; fullsuite/стенд пока не запускать. Backend source не изменялся.
> DB-identity завершён **1P/exit0**, `db-identity-20261109-105431-JEhA3e/`; первичные metadata/JUnit/hash
> сверены: actual current_database()=test_crm, hostpostgres:5432, configuredValkey15. V2 работает;
> это доказательство нового single-test, не ретроактивная телеметрия102run. Reviewer получил дополнение.
> После его проверки — fresh fullserver через подготовленный `T7260-dom-blockers/run-full-server.sh`
> (syntax PASS, **ещё не запущен**), общийlock/test-profile/v2runtime/fullsourcehash/JUnit. Стенд не менять.
> Controlled `review.md` прочитан: focused7F4P/102P и mutation sensitivity приняты; R1/R2/R4 закрыты
> в оговорённых пределах, v1 metadata-gap сохранён, R3 реальные браузеры pending. V2 рекомендован для fullrun.
> **Полная серверная регрессия ЗАПУЩЕНА**: `crm-T7260-dom-full-server-20261109`, shell
> `sh_1bf52fc8f001PoYsslRogeUreK`, runner `T7260-dom-blockers/run-full-server.sh`.
> test-profile/commonlock/v2actualDB/fullbackend+deployhash/JUnit; OUT новый `full-server-<time>-*/`.
> Ждать события, не опрашивать/не дублировать. Код, тесты, контейнеры стенда до результата не менять.
> После результата — независимая сверка состава с4070baseline; только затем копия/обновление/браузерные R3.
> Fullserver завершён **4081PASSED/exit0**, `T7260-dom-blockers/full-server-20261109-110049-JJKpRw/`.
> Оркестратор сверил JUnit, actual_database=test_crm, Valkey15, все1161sourcehashes совпали.
> `baseline-comparison.json`:4070P→P,+11DOMPASSED,0removed/changed/duplicates; полные parameter IDs сохранены.
> Независимая fullserver-сверка K3.1 запущена, ожидается `full-server-.../review.md`.
> До её результата не обновлять стенд; далее fresh проверенная копия и existing update runner,
> затем focused F06 comment-mention/F08 home+card live и дополнительные R3 lifecycle/sync проверки.
> Fullserver `review.md` прочитан — **APPROVE**4081/состава/изоляции/hashes; R3/E05/T7260 не закрывает.
> Стенд обновлён после свежей проверенной копии **before-T7260-20261109-115838**, exit0,
> `stand-update/update-before-T7260-20261109-115838-T8F1lm/`, health/image PASS, миграций нет, reset не было.
> **Запущены3 existing Chromium cases** F06 comment-mention, F08 banner-click, F08 live-card-comment:
> unit `crm-T7260-dom-focused-browser-20261109`, shell `sh_1bf891e80001D2g08eLtS2JYc2`,
> `T7260-dom-blockers/run-focused-browser.sh` с новой меткой копии. Общийlock, штатныйreset перед кругом,
> source/stand templates hash gate, tracing=on в закрытый evidence-каталог. Ждать события, не опрашивать/не повторять.
> Source/стенд до результата не менять; три existing cases не заменяют все дополнительные R3 lifecycle/sync проверки.
> Chromium3 завершён: **2P/1F**, `T7260-dom-blockers/browser-before-T7260-20261109-115838-3LmqiC/`,
> source-integrityok. F08 banner-click/live-card-comment PASSED; F06 comment-mention упал на picker-option.
> Диагностика: helper End→click→type сместил caret, фактический@внутри слова (index12,length43,нетboundary),
> mention-fetch отсутствует. Synthetic Chromium с CSS проекта воспроизвёл. См. `f06-caret-evidence.md`.
> K3.1 source-only проверяет callers/точный минимальныйhelperdiff/оставшийсяF06путь,
> ожидается `f06-caret-review.md`. Existing helper/code пока не менять, F06 не повторять до review/согласования.
> Прежние2PASSED сохранять, R3/E05/T7260 открыты.
> K3.1 на F06-review вернул **Go usage limit exceeded**, итогового вердикта нет; не повторять эту модель.
> Ревью передано запасному Go Qwen3.8 Max `ses_e406a8aaeffeHzSEcJEf30K0MX`,
> output `T7260-dom-blockers/f06-caret-review-qwen.md`, толькоsource/read-only. Ждать события.
> Qwen также **Go usage limit exceeded**, вердикта нет; оба Go-review кандидата исключены до восстановления,
> recovery arm выполнен штатным скриптом. Alibaba sharedquota ранее исчерпана — не пробовалась заново.
> Узкий review передан OpenAI Luna `ses_e4069dcdeffekDG5FUOFG8C9m6`,
> ожидается `T7260-dom-blockers/f06-caret-review-openai.md`. Source/tests/стенд не меняются.
> Luna review прочитан: **APPROVE точной строки box.click→box.focus в pick_mention** как сохранения callercaret;
> владелец отдельно разрешил её через форму. GoCode Kimi2.7 `ses_e4046d103ffe85GVXmz6dLPGWh` выполняет
> только эту строку + external isolatedRED/GREEN end/midcaret, безDB/стенда/actualE2E.
> Артефакты `T7260-dom-blockers/f06-focus-fix/`; после сверкиdiff/harness оркестратор запускает толькоF06
> через подготовленный `run-f06-focus.sh` с копиейbefore-T7260-20261109-115838 (**ещё не запущен**).
> ДваF08PASSED не повторять; product/контракт/остальныеожидания не менять.
> Kimi2.7Code также Go usage-limit; actualgitdiff helpers_feed.py пуст, строка ещё не менялась.
> Каталог подтвердил code-backup MiniMax-M3; та же задача передана `ses_e4045b28bffegDPGRrIzI8XUzF`.
> Один автор, тот же scope/artifacts/запретDB/стенда. Ждать события, не дублировать.
> MiniMax-M3 тоже Go usage-limit; code-role Go исчерпан, Alibaba skipped по прежнейsharedquota.
> Exactline+isolatedTDD переданы OpenAI Terra `ses_e40450e4effe163AEn4ogt5YL7`,
> reviewproposal уже independentLuna. Scope не расширен, actualF06runner пока не запущен.
> Terra завершил exactONEline pick_mention click→focus. Оркестратор сверил diff и полный syntheticharness/logs:
> RED end/midпозиции49вместо64/7, GREEN64/7 с полнымtextmatch,helperoption/assertsисполнены.
> `f06-focus-fix/` содержит report/harness/red/green/hashes/diff; это helperproof, не product/payload.
> Luna независимо сверяет scope/syntheticproof, ожидается `f06-focus-fix/scope-review.md`.
> **Запущен толькоF06Chromium**: unit `crm-T7260-f06-focus-20261109`, shell `sh_1bfbcbbc2001hOWMazBd8tiRba`,
> runner `run-f06-focus.sh` с копиейbefore-T7260-20261109-115838, общийlock+штатныйreset.
> Ждать события, не опрашивать/дублировать; source/стенд не менять. Прежние2F08PASSED не повторялись.
> ActualsingleF06 завершён **PASSED/exit0**, `f06-focus-before-T7260-20261109-115838-t7Ut4M/`.
> Status/JUnit и3template+3testhashes сверены изCRM/backend. Первичная проверка hashes изrepo-root дала
> exit1из-заневерногобазовогокаталога, не source mismatch; корректныйпересчётexit0.
> SafeTrace:mentionpicker200×1/commentPOST200×2,второйcommentpayload содержит@[id],consoleerrors0.
> Luna scope-review.md прочитан (exactdiff+syntheticaccepted), теперь проверяетactualresult:
> ожидается `f06-focus-fix/result-review.md`. ТриChromiumsuccessesпо2runsets,неjoint3/allbrowser/fullR3.
> Послеresultreview — теже3Firefox/Edge/Yandex9cases,затем sharedhelpercontrols/дополнительныеR3.
> Luna result-review.md получен/прочитан: actualsingleF06PASS,scope/hash/JUnit подтверждены;
> совокупность3Chromiumcase принята только как2F08+отдельныйF06, неjoint3/fullR3.
> **Запущены9casesFirefox/Edge/Yandex**: unit `crm-T7260-dom-other-browsers-20261109`,
> shell `sh_1bfc01b7b001YPAKpLOOVUpPIN`, runner `T7260-dom-blockers/run-other-browsers.sh`,
> backupbefore-T7260-20261109-115838. Общийlock,resetпередкаждымкругом,stand/hosttemplatehash/tracing=on.
> Ждатьсобытия,неопрашивать/дублировать; source/стенд до результата не менять.
> Other-browsers9 завершён **9PASSED/exit0**, `other-browsers-before-T7260-20261109-115838-UzeCG9/`.
> Оркестратор сверил3Pкаждогобраузера,unique9,3template+4testhashesMATCH,host/standtemplatesidentical.
> Luna independentlyсверяет9cases,ожидаетсяrun/review.md. Go recovery на границе unavailable12:59:25,
> поэтому известныеquota-blockedGo/Alibabaнепробовались. Не повторять пройденные12браузерныхподтверждений.
> Послеreview — sharedhelpercontrols и новые дополнительныеR3сценарии реальногоsubmit/auto-init/двухформ/repeatsync;
> следующаяреализацияещёненачата, product/стенд неизменны.
> Luna other-browsers/review.md получен/прочитан — PASS9/состава/manifests;12уникальныхподтвержденийприняты
> с прежнимиоговорками. Владелец согласовал отдельный verification-план R3 в панели проекта,
> id `e28f5fd3-c80f-4ec1-9b3f-d79b8bd60929` («Оставшаяся проверка DOM и helper F06»).
> Terra `ses_e40450e4effe163AEn4ogt5YL7` добавляет ONLY новый `backend/tests/e2e/test_f_dom_targets_regressions.py`
> с3сценариями(двеформы+реальныйpayload/HTMXauto-init, homeack/banner, cardack); запускатьемуничегонельзя.
> Externalreport/diff/hash: `T7260-dom-blockers/r3-browser/`. Затемindependentsourcereview,лишьпотом6Chromium
> (3новых+3existinghelpercontrols),приотказеСТОПбезослабленияожиданий. Existing/product/стенднеизменны.
> Автор остановился безrepo-изменений: исходнаяплашканезадаётtargetfeed-live;явныйinnerHTMLтолькоу«Показатьвсе».
> Оркестраторсверилисточникииуточнилдостижениестрогогокритериябезослабленияплана:
>51реальнаяноваяпубликация→плашка→настоящая«Показатьвсе»→проверкиsingle/outside-target+новогоack.
> Дополнение `r3-browser/swap-source-clarification.md`; никакихDOM/responseподмен илиproductfix.
> Terra добавил новый `backend/tests/e2e/test_f_dom_targets_regressions.py`(3tests,184lines),
> report `r3-browser/implementation-report-v2.md`; AST/compileONLY, реальныхпрогоновнет.
> Luna independentlysource-review активен, ожидается `r3-browser/source-review.md`.
> Оркестраторпрочиталновыйsource/report,подготовил `r3-browser/run-chromium.sh`(syntaxPASS,НЕзапущен):
> 3новых+3existingcontrol,fail-fast-x,общийlock/reset/backup/hash/JUnit/traces. Доreviewне запускать.
> Luna `r3-browser/source-review.md` прочитан — **APPROVE source для первого controlledrun**,неGREEN.
> Первыйшагсогласованногопланаотмечен[x]. **Запущены6Chromiumchecks**: unit
> `crm-T7260-r3-chromium-20261109`, shell `sh_1bfe71c50001fXRHFy0t00WBVL`,
> runner `r3-browser/run-chromium.sh` с копиейbefore-T7260-20261109-115838.
> Общийlock/штатныйreset/sourcehash/JUnit/tracing=on,fail-fast-x;ждатьсобытия,неопрашивать/дублировать.
> Припервомотказеостановкадляразбора,source/тесты/стенддоразультатанеменять.
> R3Chromium остановлен**RED1P1F**,4из6неисполнены: `r3-browser/chromium-before-T7260-20261109-115838-nkigN4/`.
> Двеформы/реальныеpayload/HTMXauto-initPASSED. Homeпосле51публикации/плашки/ShowallactualswapFAILED:
> countfeed-synced=2. TraceGET'/'HXTargetfeedlive200содержитцелыйhomebodyвключаяещёfeedlive/synced.
> Source/evidence: `r3-browser/reload-failure-evidence.md`. ExistingreloadlinkinnerHTMLвставляетhomeвстарыйlive.
> CONTRACT007:658требуетShowallперезагрузкой,нефиксируетhxатрибуты; кандидатnormalhrefreloadneedsreview/owner.
> Luna source-only анализирует rootcause/minimalfix/нужноеуточнениеverificationплана,
> ожидается `r3-browser/reload-failure-review.md`. ДоэтогоНЕправить/перезапускать/обновлятьстенд.
> Luna reload-failure-review.md прочитан:REQUESTCHANGES;PLAN007:685–689/CONTRACT658 требуютобычнойперезагрузки.
> Reviewerсчётпоправленappend-errata:1P1F4неисполнены. Владелецчерезформу**разрешилточный**
> `r3-browser/reload-navigation-proposal.patch`(productссылкабез3hxattrs+newR3testнаnavigation),
> новыйserverregressionfile иуточнениеverificationплана. gitapply--checkPASS,диффещёНЕприменён.
> Планпанелиобновлёнтольковразрешённойобласти;подписанныеPLAN007/CONTRACTнеизменены.
> Terra phaseA активна: ONLY новый `backend/tests/test_feed_reload_navigation_regressions.py`(ожидается7cases),
> безproduct/newR3edits/прогонов. Output `r3-browser/reload-fix/phase-a-report.md`.
> ЗатеморкестраторunitRED3F4P;лишьпослеREDавторприменяетexactproposal,затемGREEN/review/fullserver/backupstand.
> PhaseAполучена/прочитана:7puretemplatecases,AST/compileONLY;product/R3diffещёнеприменён.
> **UnitREDзапущен**: `crm-T7260-reload-unit-red-20261109`, shell `sh_1c1163bf50013Ji2id80Pc6qCm`,
> `r3-browser/reload-fix/run-server-check.sh red`(test-profile/commonlock/systemd/JUnit/hash/v2metadata).
> Ожидается3F4P/noDBfixture;прииномрезультатеSTOP. Ждатьсобытия,неопрашивать/дублировать.
> REDзавершён/сверен `reload-fix/red-20261109-191342-txglzd/`:**3Fhxattrs+4P**,pytestexit1/runner0,
> 10sourcehashMATCH,DBfixtureнебыло. PhaseBпереданаTerra:применитьONLYexactapprovedproposalк2файлам,
> server7tests/остальныеисточникине трогать,NOпрогонов. Ждать `reload-fix/phase-b-report.md`.
> Go recoveryнаboundaryunavailable18:59:50,новыхquota-пробне было. Послеdiffсверки —109GREENprofile.
> PhaseBполучена/прочитана:exact2fileproposalприменён,reverseapply--checkPASS;server7testsне менялись.
> **Запущен109profileGREEN**: unit `crm-T7260-reload-profile-green-20261109`,
> shell `sh_1c118584c0014wzFiZ1QKxaqvi`, `reload-fix/run-server-check.sh green`.
> test-profile/commonlock/v2actualDB/JUnit/hashes;ожидатьсобытиянеопрашивать/дублировать.
> Luna parallelread-onlysource/scope/REDreview→`reload-fix/source-review.md`;product/testsourcefreeze.
> Стендстарый,новыйreloadfixещёнедеплоен;fullserver/browserповторыдосверкине запускать.
> `reload-fix/source-review.md` получен/прочитан:APPROVESOURCE/SCOPEиRED3F4P,неGREEN.
> Вreviewоговорки:109 — серверныйпрофиль,неbrowser;phaseBизменил2файла,serverfileсозданвphaseA(итого3scope).
> Ждать ужеработающий109profile,неповторять/необновлятьстенд. Затемнезависимаяresultсверка/fullserver.
> 109profile завершён **109PASSED/exit0**, `reload-fix/green-20261109-191600-zRMXTb/`.
> ОркестраторсверилJUnit7+11+23+25+25+18,0F0E0skip,actualDBtest_crm/configValkey15,10hashMATCH.
> Luna independentlyresultreview→`reload-fix/result-review.md`,ожидатьбезповтора.
> SDD103/0/0,toolsunittest140/140,diffcheckPASS;fullrunnerSyntaxPASS,ещёНЕзапущендоresultreview.
> ПослеPASSfullsuiteожидаемый4088(4081+7), затемпровереннаякопия/stand/remainingR3browser;стендпокастарый.
> `reload-fix/result-review.md` получен/прочитан:PASS109/RED→GREEN/scope/hashes,толькопрофиль.
> **ПолныйserverЗАПУЩЕН**: unit `crm-T7260-reload-full-server-20261109`,
> shell `sh_1c11d1fc7001W3fgRKu93Uiqhs`, прежний `T7260-dom-blockers/run-full-server.sh`.
> test-profile/commonlock/v2actualDB/fullsourcehash/JUnit;новыйfull-server-<time>-*/.
> Ждатьсобытия,неопрашивать/дублировать;backend/testsource/стенддоразультатанеменять.
> Послеfullresult—составк4081+independentreview,толькопотомfreshbackup/update/изменённыйhome+4remainingChromium.
> Fullreloadзавершён**4088PASSED/exit0**, `full-server-20261109-192113-rmCgV3/`.
> ОркестраторсверилruntimeactualDBtest_crm/Valkey15,1163hashMATCH,4081P→P,+7reloadP,0removed/changed/duplicates.
> Luna independentlyresultreview→`full-server-.../review.md`;Go recoveryboundaryunavailable20:14:58.
> Покаfullreviewpendingстенднеобновлять. `r3-browser/run-after-reload-chromium.sh`подготовленsyntaxPASS,
> НЕзапущен:5cases(homeизменённый+card+publish+F02/F03),-x;толькоПОСЛЕfreshbackup/standupdate.
> Full4088 `review.md` получен/прочитан — PASS(состав/runtime/1163hashes),толькосервер.
> Preflight72GiB/нетактивныхCRMunits/1163hashMATCH. **Запущенfreshbackup→standupdate**:
> unit `crm-T7260-reload-stand-update-20261109`, shell `sh_1c1530e250012iCQlVAzc73VFV`,
> прежний `update-stand-T7260-remediation.sh`. Ждатьсобытиябезpolling/дубликатов.
> Послеexit0/провереннойновойкопииhealth-imagePASS —run-after-reload-chromium.shсНОВЫМtag.
> Updateexit0:провереннаякопия **before-T7260-20261109-202008**, `stand-update/update-before-T7260-20261109-202008-fIdeHW/`.
> Dump/tarпроверены,4файлаmode600,миграцийнет,health/imagePASS,resetво времяобновлениянебыло.
> Соответствующийшагverificationплана[x]. **Запущены5Chromiumchecks**:
> unit `crm-T7260-after-reload-chromium-20261109`, shell `sh_1c1547bae001x6vEYm1Wc0EF0T`,
> `r3-browser/run-after-reload-chromium.sh` сновойкопией,общийlock/reset/hash/JUnit/traces,-x.
> Ждатьсобытиябезpolling/дубликатов;source/стенддоразультатанеменять. ДвухформенныйPASSнеповторялся.
> AfterreloadChromium**3P1F**,1неисполнен: `r3-browser/after-reload-chromium-before-T7260-20261109-202008-jzVyAr/`.
> homeordinaryreload/newacks/cardrepeatsync/F06publishmarkerPASSED;F02FAILEDприВТОРОЙподготовительнойpublish,
> ещёДОedit/@:pick_toожидалbefore+1,actual1.F03не запускался. Hash4templates+6testsMATCH.
> Firstpublishresponse200несётOOBresetformсall,ноDOMпоследующеговыборасunit;candidateобщийOOBguard
> блокируетзаменуформыиз-заужеexistingIDполейвнутриtarget. НЕсчитатьещёдоказаннымruntimecause.
> Luna source-onlydiagnosis→`r3-browser/f02-form-reset-review.md`;safe evidence `f02-form-reset-evidence.md`.
> STOPбезправок/повторов/standupdate;feed.js/helperfixнеразрешёнтекущимreloadscope,нужноотдельноерешение.
> Luna f02-form-reset-review.md получен/прочитан:guardsourceмеханизмподтверждён,полнаяactualF02цепочкаещёнеproved.
> SignedTASKS007решение62защищаетduplicatecomment,любоеисключениетребуетотдельногоowner/SDDscope.
> ОркестраторзапустилisolatedDIAGNOSTICrealHTMX+feed.js/syntheticform,безapp/DB/Valkey/stand/исправлений:
> unit `crm-T7260-oob-reset-diagnostic-20261109`,shell `sh_1c1605e20001ZawmIBvOoAlfv5`,
> `r3-browser/run-oob-reset-diagnostic.sh`;controlбезfeed.jsvsсреальнымfeed.js,логshouldSwap/formreset/hash.
> Ждатьсобытиябезpolling/дубликатов;рабочийproduct/testне меняется. Этоdiagnostic,неF02E2Eповтор.
> Diagnosticv1exit1 `oob-reset-diagnostic-20261109-203440-4dBMsY/`:ошибкасинтетического#done,
> innerHTMLответдобавилвложенный#done(strictlocator2). Нерезультатformreset;исходныйscriptсохранёнвrun/diagnostic-source.py.
> ИсправленONLYsyntheticresponsemarker,добавленоread-onlyrootattributesнаблюдение;новыйv2запущен:
> `crm-T7260-oob-reset-diagnostic-v2-20261109`,shell `sh_1c1615a3c001cFIAAIzEm8X19c`.
> Product/тесты/стендне менялись;ожидатьсобытия,неопрашивать.
> Diagnosticv2**exit0**, `oob-reset-diagnostic-20261109-203545-80jXKu/`:controlresettrue/allowedtrue,
> actualfeed.jsresetfalse/allowedfalse/oldformretained;3sourcehashMATCH. РеальныйHTMXrootFORM#feed-form,
> children1,root+fieldIDs;hx-swap-oobсrootужеудалён(null). Этоisolatedguardproof,неповторactualF02.
> PreparedONLYproposal `r3-browser/form-reset-guard-proposal.patch`,apply--checkPASS,НЕприменён:
> разрешитьсовпадениявнутристарогоtargetтолькодляодногоmatchingform#feed-form[data-feed-form]root;
> внешниеколлизии/другиеOOBподстарымguard. Luna independentlyreviewproposal+TASKS007decision62amendment
> →`form-reset-guard-proposal-review.md`. Доreview/owner/SDDподписиJS/тесты/стендне менять.
> V1proposalreviewполучен:REQUESTCHANGES—getElementByIdнеучитываетвнешнийдубльеслипервыйmatchвнутриформы.
> ПодготовленONLYexternal `form-reset-guard-proposal-v2.patch`(apply--checkPASS):ALLoutsideIDSetдляузкой
> connectedmatchingformreplacement;остальнойguardне меняется. `form-reset-sdd-proposal.md`—2точкиTASKS007,
> кандидатv14толькобудетподготовленпослерешениявладельца,реальныйдокументне менялся.
> Luna independentlyv2code+SDDproposalreview→`form-reset-guard-proposal-v2-review.md`.
> Новогоownerразрешенияещёнет:рабочиеJS/тесты/SDD/стендне менять. Следующийшагпослеreview—решениевладельца.
> Независимыеv2-review OpenAI(Luna,затемSol) вернули usage-limit,вердиктовнет;Go-review/Alibabaпо-прежнемуblocked.
> v2review передан прямым DeepSeek V4 Pro другойлинейки `ses_e3e2cc551ffextVkzQxHAcEFkb`,
> тот же source-only scope, output `form-reset-guard-proposal-v2-review.md`.
> Worktree подтверждён: feed.js/TASKS007 не изменены, proposal только во внешних файлах. Ждать события.
> v2review DeepSeekV4Pro получен `form-reset-guard-proposal-v2-review.md`:**APPROVE-AS-PROPOSAL**.
> Подтверждено:v2 закрывает v1edge(getElementById),безселекторныхинъекций/сканавнеreset,ждусетификацияminimal.
> Ничего не применено и не подписано;следующийшаг—отдельноерешениевладельцапо exact JS-diff и SDD-черновикуv14.
> Владелецчерезформуразрешил **JS-fixиSDDv14**. SDDчерновикподготовлен: `specs/007-feed/tasks.md` v13→**14/черновик**,
> ровно3правки(версия/статус,решение62 текст,T7223строка);`sdd.pyпроверить`0ошибок. Подпись—завладельцем,модельнеподписывает.
> ДалееTDDпоразрешённомуv2patch: newservertest+newe2etest+isolatedreal-HTMXharness,затемRED→applypatch→GREEN.
> Автор—DeepSeekV4Pro(производительностьоправдана);авторне запускаетстенд/reset/DB/browser(E2Eтолькооркестратор).
> Подпись владельцане легла: документбыл«черновик»с устаревшим `проверяет`-отпечатком(старыйv13hash).
> Оркестраторобновил `docs/reviews/TASKS-007.md` проверяетподтекущийv14 `613fb145…47f02a`,
> `на-проверку`выполнено. Владельцузаново: `python3 tools/sdd.py подписать specs/007-feed/tasks.md --кто Максим`.
> **TASKS-007 v14 ПОДПИСАН** `2026-11-09T22:51+03:00` на `613fb145…47f02a`, статус утверждён; SDD103/0/0.
> Реализация по v2 patch разрешена подписанным SDD; фазаA автора DeepSeekV4Pro ещёидёт.
> PhaseA получена/прочитана:3теста+harness,патчНЕприменён,source-before=8afa879e…feed.jsчист.
> **RED harness запущен** `crm-T7260-form-reset-red-20261109`/`sh_1c1e38c83001P7le1zqdPiGVtg`
> —ожидаетсяcase(a)FAILнанеисправленномfeed.js,остальныеPASS. ПослеRED—applyv2,gзатемGREEN.
> RED harness подтверждён `form-reset-harness-20261109-225757-5u9Ith/`:**case(a)FAIL**(allowedfalse/oldretained/stale),
> (b)-(f)PASS(внешняя/inside-outsideколлизия,неверныйtarget/root/лишниекорни,beforeend/likerнеослаблены).
> PhaseB автору(тажесессияDeepSeek):applyexactv2patchкfeed.js,безпрогонов;затемGREENharness+GREENservertests.
> PhaseB применён;оркестраторсверилdiff=proposal(байтодинаково,лишькосметическаястрокаконтекстаханка).node--checkPASS.
> **GREEN harness 8/8** `form-reset-harness-20261109-230015-rKWWkq/`(case a now allowed/replaced/reset;b-f неослаблены).
> **Server profile запущен** `crm-T7260-form-reset-server-profile-20261109`/`sh_1c1e66a360016jJRHND9UfwIj1`
> (newform-reset4+reload7+dom11+page/consumers/live,общийlock/test-profile/v2). Ждатьсобытия.
> Profile113завершён**113PASSED/exit0** `form-reset-fix/server-profile-20261109-230105-k6tEQJ/`,13hashMATCH,actualDBtest_crm.
> **Полная серверная регрессия запущена** `crm-T7260-form-reset-full-server-20261109`/`sh_1c1e8e366001uUyX7qoXIJRqzq`
> (4092ожидаемо=4088+4,проверимсоставпосле). test-profile/v2/fullhash. Ждатьсобытиябезpolling.
> Послеfull—freshbackup/standupdate,затемbrowserF02/F03/F08/newform-resetE2E.
> Fullserver**4092PASSED/exit0** `full-server-20261109-230347-hnX9Pm/`:4088P→P,+4form-reset,0removed/changed,
> 1165hashMATCH,actualDBtest_crm. Составсверенсервер.txt baseline192113.
> Независимыйresult/scope-review(механика)DeepSeekFlashпередан;послеPASS—freshbackup/standupdate,browserrerun.
> result-reviewPASS(механика):diff=proposalбайтвбайт,4092=4088+4,harnessRED1→GREEN0,SDDv14+проверяет613fb.
> **Freshbackup/standupdateзапущен** `crm-T7260-form-reset-stand-update-20261109`/`sh_1c21aec21001vBB8bqPqQZAj8q`.
> Послеexit0—browser5(F02/F03/F08own-comment/F08liker/newform-resetE2E)черезподготовленныйrunner.Ждатьсобытия.
> Standupdateexit0:копия**before-T7260-20261109-235826**проверена,health/imagePASS,миграцийнет,webimagec1c6f673…1e0cc.
> **Запущены5Chromium** `crm-T7260-form-reset-browser-20261109`/`sh_1c21c0ee3001OLY6ogjzHMlHN5`:
> newform-resetE2E/F02/F03/F08own-comment-once/F08liker,-x,feed.jshost/standсверкадо/после.Ждатьсобытия.
> Первыйзапускfalse-failнаpreflightcmp:хешиидентичныf8f3a01d…13f9b,различаласьтольковтораяколонка(путь).
> Runnerисправленсравниватьтолькo64-симхэш;первыйrunнеисполнялтесты(ост-ринbeforepytest).Повторзапущен:
> `crm-T7260-form-reset-browser-v2-20261109`/`sh_1c21ceb0c001d4U7uAPODK0Fzo`. Ждатьсобытия.
> Browser v2 **1F**newform-resetE2E `form-reset-browser-before-T7260-20261109-235826-ghmK4W/`;F02/F03/F08неисполнены(-x).
> Причина:create_unitвозвращаетID,авторпередалIDвtoтэг;pickerзапросq=idпуст. Этоtestauthorbug,непродукт.
> АвторправиттолькоНОВыЙтест(_setup:именадляto);затемповтор5casesChromium.
> Fixсверен:_setupзахватывает2unique_name,to=names;ASTOK;helpers/productнетронуты.
> **Повтор5Chromiumзапущен** `crm-T7260-form-reset-browser-v3-20261109`/`sh_1c2206681001VTXLZ5RnM6GXXj`.Ждатьсобытия.
> Бrowserv3**1P1F** `form-reset-browser-before-T7260-20261109-235826-OqdgtN/`;F03/F08неисполнены(-x).
> newform-resetE2E**PASS**;F02теперьпрошёлpublish,ноупална_edit+mention(стр.125pick_mention):текстпоста
> безначальногоtrailing-space,`@`посленесловнойграницынеактивируетподсказку(какпредупреждалReviewFocus).
> Этосуществующийtest_helper(test_f02_important._edit),непродукт/newtest;нуженодинпробелперед@.
> Предложенточныйnounw-passдифф;решениевладельцатребуется(существующийтестфайл).
> Владелецразрешилоднострочныйпробел;применёнtest_f02_important._edit(строка123),ASTOK.
> **Повтор5Chromiumзапущен** `crm-T7260-form-reset-browser-v4-20261109`/`sh_1c39d7d31001Q58rE4P6C04pDJ`.Ждатьсобытия.
> Browser v4**5/5PASSED** `form-reset-browser-before-T7260-20261109-235826-SsGzPC/`(newresete2e/F02/F03/F08own/F08liker),
> feed.jshost==stand f8f3a01d,6testhash+1feedjshashMATCH.
> **Cross-browser15запущен** `crm-T7260-form-reset-other-browsers-20261109`/`sh_1c3a30fba001gDgVqTAhgx4XMg`
> (5cases×Firefox/Edge/Yandex,резетпередкаждымкругом,hashgate).Ждатьсобытия.
> Послепринятиязавершённыхbrowser—независимыйresultreviewиостаётсяE05/полныйT7260.
> Cross-browser**15/15PASSED** `form-reset-other-browsers-before-T7260-20261109-235826-9zXDe4/`
> (5×Firefox/Edge/Yandex),7hashMATCH. Итоgоform-resetfix:server4092+harness8/8+Chromium5/5+15/15всезёлёные.
> Независимыйсводныйresultreview(flash)передан;E05/полныйT7260—покаоткрыты.
> Сводныйbrowser-result-reviewPASS:`form-reset-fix/browser-result-review.md`;form-resetfixитогозакрыт
> (server4092,harness8/8RED→GREEN,Chromium5/5,Firefox/Edge/Yandex15/15;SDDv14подписан`sdd.py`0ошибок;
> toolsunittest140/140;`gitdiff--check`чист). Verificationпланпанели—все5шагов[x].
> Открыто: **E05 WebPush** и **полныйbrowser T7260**. Ждуочередностьвладельцаследующимшагом.
> Владелецвыбрал**«ПолныйбраузерныйT-7260»**. Preflight:плагин/make-idsнаместе,T7261/T7262[x]сAPPROVE,
> копия/status-235826exit0,нетактивныхCRMunits.
> **Полныйbrowser T7260gate ЗАПУЩЕН** `crm-T7260-browser-gate-20261109`/`sh_1c46033b0001Y2QfqcaftcbHok`
> (f01-f15×4бразуера+прежниесрезыchromium/yandex+legacy3,метка-20261109-235826).Новыеe2eфайлыкорректноне
> входятвmake-idsвыборку(test_f_*неtest_f\d). Длинный~часы;ждатьсобытия,неопрашивать. Ждатьсобытия.
> **Полныйbrowser T7260gate RED**: `browser-gate/T7260-before-T7260-20261109-235826-SlfQjc/`;
> main=2080P/160F(0E0skip),legacy=21P,~21ч38м. Классификация160F: **52F=моярегрессия**
> (pick_mention focus: publish/comment-mention текстбезtrailing-space→`@`неграница);2F=мойflaky home-reload51post;
> 106F=прежниепродуктовыебаги(f01 recipient,f02 date/read/readers,f03 event,f05 notify,f08 live,f09 telegram,
> f10 files,f11 search,f12 retention,f15 PDN,e05 webpush,k/l).Моификсыудержались(F02petrov/F06sidorov/form-reset/
> comment-card DOMене в списке). ПРИОРИТЕТ:моюрегрессию52F(границаперед@вpick_mention/_fill_form)→мoйflaky→прежние106.
> Владелецразрешилправкуграницыв`pick_mention`;применено,AST/diff-checkOK. ЗапущенChromium13уникальныхдляпроверки
> `crm-T7260-mention-boundary-chromium-20261111`/`sh_1c9f6bd0100135R5kMJjziC5X0`(-x).ПослеGREEN—остальные3браузера.
> Chromium13/13PASSED `mention-boundary-before-T7260-20261109-235826-50TkMG/`.Запущеностальные3браузера39:
> `crm-T7260-mention-boundary-other-20261111`/`sh_1ca031b33001c2p4Xq1o0ha8gD`. Ждатьсобытия.
> Остальные39/39PASSED `mention-boundary-before-T7260-20261109-235826-t5D0Zp/`. **Регрессия52F полностью
> устранена**(13уникальных×4браузера,hashMATCH). Условнаяграницанеизменяетtrailing-spaceпути(no-op).
> Остаётся:мойflaky2F(home-reload51post)+прежние106F.Далееразборэтих108F.
> Владелецвыбрал**триаж106первопричин**. Запущенread-onlyтриаж(AlibabaDeepSeekV4Pro-0813,Standardтеперьдоступен)
> `ses_e353f2c84ffeRgyxtCoBgpZIlG`,output `browser-gate/triage-106.md`;исключенымои52Fиflaky2F.Ждатьсобытия.
> Triageготов/прочитан:17групп.Код-подтвержденоP1(61T):G1recipients short-name,G2 date min/max,G3 readers click,
> G5 maxlength200,G6 edit hx-post vs nav,G7 author filter.P2код/добор(24T):G4,G10,G11,G12,G13.
> Среда?(17T):G8/G15 mail,G9 WS-banner,G17 k/l-timeout+perf,G14 webpush,G16 flaky-firefox.
> Ждурешениевладельцапотикуфиксов.
> Владелецвыбрал**«ВесьP1включаяG3/G6»**. Контрактсверен:G3счётчик—ссылка(CONTRACT769),G6 edit—HX200фрагмент
> (CONTRACT661,какF10). Автор—Alibaba glm-5.3(Standardкод),6фиксовTDDбезstand/browser/e2e.Ждатьсобытия.
> Авторсдал6фиксов+новыйtest_feed_p1_regressions.py(20кейсов)+3обновлённыхсуществующихсерверныхтеста.
> Отчётпрочитан:важно—G1черезshort(небезусловно,G3со_K42/К61,3существующихтестапротиворечиликонтракту.
> **Профильныйсерверзапущен** `crm-T7260-p1-focused-20261111`/`sh_1cb2e18b6001HhnnT3jEa72h9J`;
> параллельноsource/дифф-ревьюAlibabaDeepSeek`ses_e34d18fb8ffeTN9o0F5giMa07g`→`T7260-p1-fix/review.md`.Ждуоба.
> ПрофильныйP1**73PASSED**(`p1focused-20261111-181558-DI37xH/`:20new+21posts+25important+7visibility_3),actualDBtest_crm,hashMATCH.
> Жду независимоеsource-ревью; послеAPPROVE—полнаясервернаярегрессия(~4112)идалееstand/browser61тест.
> P1source-ревью**APPROVE**(3тестачестнокоррекция,Glоп—G1/G2/G3/G5/G6/G7валидны;докупаливогласкасценариянеблокер).
> **Полная серверная регрессия запущена** `crm-T7260-p1-full-server-20261111`черезпрежнийrun-full-server.sh.Ждатьсобытия.
> Fullserver**4108P/4F**(`full-server-20261111-182436-csZ2Ue/`):2регрессииP1(пропущеныавтором/ревьюером)+2perf-flaky.
> Регрессии:test_date_field::no_native_date_inputs(G2 vs FR-148—нужнаврезкаuntilпоK42/K61);
> test_feed_page_2::post_shows_author_photo_arrow_recipients(G1—ожидаетполноеФИО,нужнократкое).
> Perf-flaky:kb_render1.05svs1.0,lists_export13.2svs10(несвязаныспродом).ЗапускаюP1-r2иперепроверкуperf.
> P1-r2готов(2тестаобновлены:test_date_field native-until carving,test_feed_page_2 краткаяформа),productне тронут.
> Perf-recheck:2перф-тестасноваFAILв изоляции—НЕфлейки,а**машиннаянагрузкаload14-15**(yandex_browser49%+openchamber48%CPU).
> Этосреда,неко-регрессия(былиGREENв4092).Нужензапускfullserverнаостывшеймашине;сейчасперепроверюP1-серверныйнаряд.
> FocusedP1-r2**108PASSED**(`p1focused-20261111-202846-TbJU7j/`:20new+21+25+7+10date_field+25page_2)—обе regрессиизакрыты.
> Запускаюfreshbackup/standupdate,затембраузерные61тестG1-G7.
> Standupdateзапущен `crm-T7260-p1-stand-update-20261111`/`sh_1cbacbb6c001sbuDKTOBeZeTE1`.
> Browserrunner `run-p1-browser.sh`готов(16уникальныхG1-G7×4браузера,fail-fast,feed.jshost/standсверка).Ждуupdate.
> Standupdateexit0:копия**before-T7260-20261111-203417**проверена(health/imagePASS,миграцийнет,webimagee6377a39).
> **Запущены61браузерныхтестG1-G7** `crm-T7260-p1-browser-20261111`/`sh_1cbae7b8f001k3IY6l8wiNcLxh`(-x).Ждатьсобытия.
> P1-browser v1 **12P/1F**(x остановился):f11`_edit_comment`жаждалнавигацию,аформакомментария-HTMA(`hx-post#c<id>`).
> Авторпропустил`_edit_comment`(чинилтолько`_edit_post`). Исправилтемжепаттерном;AST/diffcheckOK.
> **ПовторP1-browser** `crm-T7260-p1-browser-r2-20261111`/`sh_1cbcd4eeb001IgZSXHw85B8dY8`(-x,все61).Ждатьсобытия.
> P1-browser r2**19P/1E**(x):ошибкафикстуры`crowd_post`(firefox)—`Page.goto interrupted by another navigation`
> присоздании12сотрудников.Этофлейкзагрузки(load14-15,yandex_browser+openchamberCPU),неP1-код;19доэтогоPASSED.
> Машинаперегружена—портятсинптомыперф-бюджетыитяжёлыефикстуры.Фиксируюиперепроверяюизолированно.
> Изолированныйповторfirefox`read_12_of_40`—**PASSED**(776s).Ошибкабылафлейком(crowd_post),некод.
> Убрал-xизrunner;полныйP1-browser**61безfail-fast**запущен`crm-T7260-p1-browser-r3-full-20261111`/`sh_1cbf5c3a1001ZXA8mPoPkikPq2`.
> Соберувсерезультатыиоттриажируюфлейкиотдельно.
> P1-browser full**63PASSED/0F**,нотаймаут1чсрезал**2yandexтеста G7**(filter_choice+360px)—runner`timeout3600`.
> Дозапускаю2yandex-тестаизолированно`crm-T7260-p1-g7-yandex-tail-20261111`/`sh_1cc2e0582001T97j1cY4OeKgbT`.Жду.
> 2yandex-тестPASSED.**P1полностьюверифицирован:16уникальныхG1-G7×4браузера=64/64PASSED**(сучётомизолированных
> повторовфлейков).SDD103/0/0,tools140/140,diffcheckчисто.P1закрыт.
> Остаётся:P2код(G4/G10/G11/G12/G13=24),среда(G8/G9/G15/G17+perf),webpushG14/flakyG16,мойflaky2F.
> Владелецвыбрал**P2-код(G4/G10/G11/G12/G13)**. Запускаюисследование+фиксыавтораAlibaba glm-5.3(тажесессия).
> P2 авторсдал:продуктfeed.js(G4a read-move FR-614)+_files.html(G11 имяуэскиза);тестыновыйtest_feed_p2_regressions.py+
> harness_read_move.js+2e2eодностроки(G4b goto("/"),G13 уникальныйзаголовок).Уточнилтриаж:G11/G13НЕбаги(alt-текст/
> загрязнениесессии),G10/G12=контрактпагинацииvsтест(выводвладельцу,e2eнеменял).Nodeharness6/6послефикса.
> **ПрофильныйсерверP2запущен**(new+test_feed_pdn)`crm-T7260-p2-focused-20261112`/`sh_1ce114186001U0t1ZOkslxTxSN`;
> параллельнонезависимоеревьюAlibabaDeepSeek.Ждуоба.
> P2-focused v1:16P/3F—3тестаG11падали`_Attr()takesnoarguments`(заглушкабез`__init__`,авторнезапускал).
> Исправил`__init__`вtest_feed_p2_regressions.py;AST/diffcheckOK. Повтор`crm-T7260-p2-focused-r2-20261112`/`sh_1ce131517001Wmz5PxVBNTpeBG`.
> P2-focused r2**19PASSED**(6p2+13pdn).Жду независимоеsource-ревью;затемfullserver/stand/browserG4-G13ирешениевладельцаG10/G12.
> P2 source-ревью**REQUEST CHANGES**:блокер G4а—авторубралграницу«внепоказанного»целиком,противоречитplan.md:462-463
> (иначе придётс«Ещёзаписи»)→дубльприподгрузкеполнойстраницы. G4б/G11/G13 верны,G10/G12 ждутвладельца.
> Направляюавторуточныйminimal-fix(откладыватьтолько при[data-feed-more]иat<oldest)+harness-кейсполнойстраницы.
> G4a исправленточнопоревью:убрановерхнююграницу,оставленаотсрочкатолькос[data-feed-more]иat<oldest;harness**7/7**.
> Feed.js-диффпровереноркестратором.Запускаюfullserver(учётом2env-perfподнагрузкой),затемstand/browserG4-G13.
> Владелец**согласовалправкуf08/f12подпагинацию**(G10/G12).Направляюавтору;fullserverидётпараллельно.
> G10/G12авторсдал:f08листает«Ещёзаписи»до конца,f12фильтрпериодапубликации;guardвp2-тестдополнен.Диффсверен.
> Направляюконсолидированноеrev3+rev4ревью(авторужепередалG4a-fix);фokussedсерверпонавторномуguardуидётитоже.
> Focused-r3отклонил`flock`(exit2):полная серверная регрессия ещё идёт и держит test.lock. Перезапущупослеfullserver.
> Итогпараллельно:fullserver(вфоне),консолидированноеревьюrev3+rev4(вфоне).Ждуоба.
> Follow-upревью**APPROVE**(G4аrev3+G10/G12rev4).Обаблокерасняты.Ждуfullserver;затемfocused-r3guard+stand+browser20.
> Fullserverдал**4118passed/0F**(дажеperf-тестыпрошли—машинаостыла),ноexit1поsource-integrity:3файла(f08/f12/p2-guard)
> изменилисьвРЕТево времяпрогона(мояёркестрация:запустилrev4параллельноfullserver).Обведуфайлыe2e,серверныезатрагивалтолькоguard.
> Перезапускаюfocused-r3(guard)сейчас;полнуюрегрессиюповторюпосле—нафинализированномsource.
> Focused-r3**19PASSED**(guardвнутриDB-тестаG10/G12).Запускаюповторполнойрегрессиинафинализированномsource(clean integrity).
> Fullserver**4118PASSED/exit0/чистаяintegrity** `full-server-20261112-090416-C53JGN`,actualDBtest_crm.SDD0/tools140/diffcheckчисто.
> Запускаюfreshbackup/standupdate,P2-browser24после.
> Standupdateexit0:копия**before-T7260-20261112-100612**проверена,health/imagePASS,webimageac6fba9e.
> **ЗапущеныP2-browser24** `crm-T7260-p2-browser-20261112`/`sh_1ce954a20001YHpTyr8cx0c9f7`(G4/G10/G11/G12/G13×4).Ждатьсобытия.
> P2-browser**23P/1F** `p2-browser-before-T7260-20261112-100612-0NmOp0/`:единственныйF=`test_f02_read_click…[firefox]`
> (G4а,юзераfilespecific).Ответread200/article/no-read-btnИДЕНТИЧЕНchrome;chromium/edge/yandexпроходят,firefoxкарточка
> остаётсявблоке(count1).Изолированныйповтор—сноваF(нефлейк).Консольhtmx-ошибокнет.Этореальныйfirefox-specific
> остаток,предшествующийтекущимПравкам(былврасширенномREDисходномgate).Требуетinstrumentedfirefox-отладки.
> Владелецвелел**отложитьfirefox G4a**какизвестныйedge(неблокер).P2фактическизакрыт(23/24+полныйсервер4118).
> Остаютсясреды-группыG8/G9/G15/G17(~19)+webpushG14+firefox-flakyG16+мойflaky2.Перепроверяюнаостывшеймашине/freshстенде.
> Перепроверкасредызапущена `crm-T7260-env-recheck-20261112`/`sh_1cf455033001uOcbAFSsW3BpJ9`(почта/WS/timeouts/webpush/flaky,
> без-x,сборвсехntai).Ждурезультата—либоонитеперьпроходят(средадеградации21.5ч),либоэтокод.
> Перепроверкасреды**30P/1F**:всеG8/G9/G15/G17(k01/k04/k05/l08)+G14webpush+G16firefox+мойflaky home-reload—ПРОШЛИ
> (значитбыладеградациястендаза21.5ч).Единственныйостаток—`k12`200000-значpreview1.07s vs1.0s(НФР-403,перф~7%).
> ИтогT-7260:осталисьтолькоК12(перф)иfirefoxG4а(отложен).Всёостальное—устранено.
> k12:владелецрешил1,5сADR-0016(на-проверке).ИзменениеSPEC-005:NFR-403вызвалокаскадна5док.
> (зависимость)плюсоснован_наPLAN-005.Владелецвелел**переподписатьвсюцепочку**.Готовлюребейз+подписи.
> Каскадминимален:телоизменилосьтолькоуSPEC-005(подписьслетела);уPLAN-005устарел`основан_на`—поправил(тело/подписьцелы).
> Осталосьподписатьвладельцем:SPEC-005(новыйhash)+ADR-0016;этоснимет5«зависимость»ошибок.Ждуподпись.
> SPEC-005+ADR-0016**подписаны**.SDD**0ошибок**(каскадснят).kb_render1.5с—1passed.Дозапускаюk12-yandex(также1.5с).
> k12-yandex**PASSED**(1.5с).T-7260итог:закрыто52(pick_mention)+61(P1)+23(P2)+~30(среда)+k12(ADR).ОстаётсятолькоfirefoxG4а(отложен).
> SDD0/tools140/diffcheckчисто.Готовоприсвоениевладельцу.
> **Финальная сверка 2026-11-12 20:56.** Полный сервер на финализированном source после ADR-0016:
> `full-server-20261112-194929-2frLFm/` — **4118PASSED/exit0**, integrity1168/1168, actualDBtest_crm,
> nodeid=4118 (0added/removed/duplicates). k12 Chromium+Yandex: **2/2PASSED**, `k12-recheck-…-6I8RMT/`
> (сброс перед кругом, хэш теста b4ec81c4…, образ стенда ac6fba9e…). Недостающие разделы
> (P2/среда/k12-ADR/итог) записаны в docs/reviews/TASKS-007.md. SDD105/0/0, tools140/140, diff-check чист.
> **Владелец принял T-7260 2026-11-12: отмечена [x] при отложенном firefox G4a (не блокер); открыт этап 4.**
> Следующий шаг — T-7300 (сверка зелёного серверного прогона с красным T-7160, сводка по FR/NFR); затем T-7301–T-7303.
> **T-7300 сверка выполнена 2026-11-12 21:35.** Зелёный прогон `full-server-20261112-194929-2frLFm/` (4118P/exit0,
> integrity1168/1168) против красного `stage2/red/red-srv.txt` (3834 собранных, 3066P/768F): все 768 прежних падений
> зелены, 0 потерянных; +285 nodeid (18 новых серверных файлов + дополнения в 15), −1 — owner-approved замена
> WebPush-теста на retry-семантику FR-324/FR-333. Ослаблений нет; `test_capacity` 25→27 (+2 запроса бейджа «Ленты»,
> постоянство `large==small` сохранено) подтверждён владельцем 2026-11-13. Сводка 42 FR/14 NFR — в отчёте.
> **T-7300 `[x]` 2026-11-13:** независимая проверка другой моделью (read-only) — APPROVE,
> `crm-work/slice007/stage3/T7300-review/review.md`; необязательные замечания учтены. Далее T-7301.


Обновлено: 2026-11-08 — T-7260 полный браузерный gate завершён RED; см. раздел «Актуальное продолжение — 2026-11-08». Ранее 2026-10-30 19:00 (срез 007: всё до da899af ЗАПУШЕНО владельцем; T-7160 приёмка возобновлена 18:31, обработчики RQ перезапущены, da899af; ранее ПАУЗА — переезд в офис 1; T-7160 красный прогон: сервер готов b861523, приёмка прервана на 368/2228, возобновление — абзац «T-7160 НА ПАУЗЕ»); ранее 2026-10-29 07:10 (срез 006: ПАУЗА — переезд в офис 2; T-6304 не выполнен → решение 63, TASKS-006 v2 на проверке 3610149, ждёт подписи; ранее T-6302 [x] 14bbc19; ранее T-6302 возобновлён — round2; до этого ПАУЗА — переезд в офис 1; T-6302 прерван на 434/1790, 11 падений Web Push; возобновление — строка «СРЕЗ 005 ПРИНЯТ…», абзац «T-6302 НА ПАУЗЕ»); ранее 2026-10-28 12:50 (срез 006: Этап 3 закрыт — T-6260, T-6138 [x]; дальше Этап 4; ранее Этап 2 закрыт, T-6160 — см. строку «СРЕЗ 005 ПРИНЯТ… Дальше — срез 006»); ранее 2026-10-19 (срез 005, Этап 2: серверные тесты в git, проверка приёмки, T-5138); ранее 2026-10-07 (сессия 17 — Этап 3 среза 003 закрыт: сервер 1231/1231, приёмка 781/781, см. п. 000 очереди; сессия 16 — приёмка T-3140…T-3152 закоммичена 5a72664, T-3160 выполнена — см. п. 00 очереди; сессия 15: серверные тесты Этапа 2 — T-3101…T-3138; сессия 14: TASKS-003 подписан — 9b52a8b; Этап 1 среза 003 — 2cd3c81; **T-3100 выполнена**:
контракт CONTRACT-003.md — 91a7169, помощник support_servicedesk.py — 604c03d; следующий шаг — волны тестов T-3101…), Opus.
Файл вне git (.gitignore). Читать первым в новой сессии. Прежние версии — /home/gpgr/Документы/crm-work/HANDOFF.before-*.md
(последняя — HANDOFF.before-2026-10-06-s4.md: до записи о T-3100).

## Состояние
### Актуальное продолжение — 2026-11-08

- Новое поручение владельца: найти путь продвижения, необходимые разрешения на диагностику/исправления в рамках
  подписанных требований даны. По JSONL сохранённых trace установлен конкретный блокер: `htmx:targetError` при
  сохранении правки записи (14 C / 13 F / 14 E / 14 Y сценариев); во всех 14 Chromium случаях POST edit не записан.
  `feed/form_edit.html` не содержит target `#feed-post-ID`, который требует вложенная форма, и не подключает feed assets.
  Проверка комментария независимым исполнителем: его edit-страница уже имеет wrapper `#cID`, не править вслепую.
  Также подтверждены отсутствующий mention-list в `_form_comment.html` и OOB `#feed-synced` без HTML-target;
  это следующие отдельные партии, не приписывать им все падения. Полные факты — новый раздел «выход из диагностического
  тупика» в `docs/reviews/TASKS-007.md`. K04 уже focused PASS, не повторять ради уверенности.
- Первая узкая партия запущена: OpenAI GPT-6.1 Sol, subagent `ses_e44312449ffe87TyJE2QZE48Ta`, единственный автор
  `feed/form_edit.html`, `apps/feed/views/posts.py`, нового `tests/test_feed_edit_page_regressions.py`.
  RED→GREEN, обычный/HX target/отказ/ПДн, assets; existing tests/CONTRACT/JS не менять. Стенд/reset запрещены этому
  исполнителю; DB только test-profile под общим lock/systemd. Артефакты `stage3/T7260-edit-page-fix/` вне git.
  Исполнитель завершил: настоящий RED 8F → GREEN 8P; synthetic Chromium Save1POST/retry2POST без target/page errors.
  Оркестратор сверил diff, тесты и первичные status/exit/harness. Независимое review: Go Kimi K3.1 Pro и Qwen3.8 Max
  usage-limit без вердикта; OpenAI Terra `ses_e4429e1a0ffeHPoavKBqFxD82H` — REQUEST CHANGES,
  первичный `review.md` прочитан: R1 потеря новых uploaded files после invalid/ПДн refusal → retry.
  Автор в той же сессии выполняет fix-back: новый regression RED ordinary/HX invalid/Pdn+file → retry+attachment,
  восстановление только допустимых own/unbound files, security negatives; posts.py/_form_edit.html/новые tests,
  без JS/стенда/existing tests. Артефакты `T7260-edit-page-fix/r1/`; затем independent re-review Terra.
  R1 представлен: RED10F→GREEN62P (новые10+прежние8+existing44), synthetic upload/invalid/Pdn retry PASS.
  Оркестратор прочитал diff/новые tests/r1 report; Terra в той же сессии выполняет re-review, ожидается
  `T7260-edit-page-fix/review-followup.md` получен: REQUEST CHANGES, R1 закрыт, R2 malformed files (`²`/слишком
  длинное число) может дать 500 в новом восстановлении формы через private `_ids`. Автор в той же сессии
  выполняет r2 RED→GREEN: безопасный bounded parser только в view, новый regression test, прежние62+новые.
  Shared service parser/bind/auth/JS/stand/existing tests не менять. R2 GREEN уже завершён: **80 passed**, exit0,
  RED12F6P; оркестратор дождался существующего прогона через inotify без polling/дубликата. Terra re-review запущен,
  ожидается `review-r2.md`. Важно: r2/report.md честно отмечает старые unsafe `_int_ids`/`files._ids`/remove,
  часть Pdn tests изолирует PdnFound на service boundary; общий malformed ID путь пока не объявлять безопасным.
  Terra review-r2.md: APPROVE узкой партии, прочитан оркестратором, оба required закрыты.
  Полная серверная регрессия **ЗАПУЩЕНА** через systemd-run --user --wait: unit
  `crm-T7260-edit-page-full-20261108`, shell `sh_1bbe5d2c8001aFv3l1eBKjdv6m`,
  `run-full-regression.sh` из каталога партии. Runner под test.lock, test-profile only, сохраняет
  status/server.txt/source.sha256 в новом full-regression-* каталоге.
  **ПРОГОН ЗАВЕРШЁН RED**, `full-regression-20261108-190243-usUbSm/`: 4028P24F, exit1, 48:59; НЕ повторять.
  Оркестратор сохранил полную regression-diff.json к старому party5 baseline от1ноября:3361P→P,500F→P,
  14P→F,7F→F,170added(167P3F),1removed. Это НЕ causal baseline текущего fix; много промежуточных реализаций.
  Terra `regression-review.md`: APPROVE сверки, gate RED; все36fix-tests PASSED,6hashes совпали.
  Удалённый WebPush test намеренно заменён по записанному решению владельца8ноября (PLAN004/FR333);
  CONTRACT004:572 всё ещё со старым sent-priority, это надо явно синхронизировать, не откатывать код вслепую.
  Sol в той же сессии read-only разбирает13feed/permissions failures, ожидается failure-triage-feed.md.
  Notify11: source указывает на отсутствующие разрешённые kind.channels в старых тестах (audit9+admin1+push1).
  Existing tests НЕ правились: подготовить exact per-test diff и согласование по правилу проекта.
  Sol usage-limit, НЕ повторять; его полный saved `failure-triage-feed.md`254строки прочитан оркестратором,
  13failures разобраны source-only. Найден конфликт verbose_name внутри CONTRACT007(:102«Лента»,К1:1049«Живая
  лента»), не считать однозначным product bug/не править до разрешения. Поля события PDN проверяются только text:
  узкая партия запущена Luna `ses_e43593ea6ffey3k1XmcwOFMUr4`, единственный автор services/posts.py+нового
  test_feed_event_pdn_regressions.py, RED→GREEN, без existing tests/стенда. Артефакты stage3/T7260-event-pdn-fix/.
  Terra в прежней reviewer-session готовит НЕПРИМЕНЁННЫЕ notify-test-proposal.md/.patch(11tests) для owner approval.
  Luna сначала остановился без правок: ошибочно принял номера строк431–438/659 за идентификаторы документов.
  Оркестратор повторно открыл точные PLAN007431–438 и SPEC007FR612стр568,CONTRACT007стр659, дал абсолютные
  пути/цитаты и продолжил ту же сессию с прежним scope. Это исправление формулировки задания, не новый owner decision.
  PDN fix представлен: targeted54P, broad run сохранил один уже известный card fixture fail. Оркестратор прочитал
  diff+новыеtests; Terra делает независимое review в T7260-event-pdn-fix/review.md. Пока не считать принятым.
  Владелец через форму выбрал ВСЕ11notify approvals по открытому notify-test-proposal.patch, без дополнительных
  условий; точные11nodeids записаны в docs/reviews/TASKS007. Разрешён только этот patch, audit assertions не ослаблять.
  Luna в той же implementer-session теперь применяет ТОЛЬКО утверждённый notify patch к3test-файлам;
  focused11, затем три файла под общей блокировкой. При unexpected failure остановка без самовольныхfix.
  Артефакты stage3/T7260-notify-test-amendment/. PDN code reviewerTerra смотрит отдельно, не смешивать scopes.
  Terra PDN review.md: REQUEST CHANGES — новое title/place warning теряет upload files в publish form.
  После notify job передать Luna fix-back: views/posts.py+_form.html+новыеtests, reuse safe _restored_upload_ids,
  own/unbound only, ordinary/HX upload→warning→returned-controls confirmation→actual attachment, security negatives.
  Это сохранение введённого по прежнему PLAN, не новые требования; existing tests/bind/auth не трогать.
  Notify завершён: focused11P, файлы24+21+25P, exit0, оркестратор сверил первичныеexit/status/log summaries.
  Terra делает independent notify-review.md. Luna после notify передан PDN fix-back (views/posts.py,_form.html,
  новыеtests; reuse safe restorehelper), артефакты T7260-event-pdn-fix/r1/ ожидаются.
  Владелец второйформой отдельно разрешил ВСЕ9feed-test cases по exactdiffsA–G failure-triage-feed.md,
  точные nodeids и пределы записаны в docs/reviews/TASKS007. Они ПОКА НЕ применены; послеPDNreview/gates.
  Конфликт verbose_name разрешён владельцем отдельнойформой: **«Лента»**. Разрешены apps.pyverbose_name и
  синхронизация CONTRACT007К1; test_feed_deploy existing НЕ менять. Исполнение в очереди после текущейпартии.
  Notify-review.md прочитан: **APPROVE** exactpatch, 11target+70filetests подтверждены, hash/полныеfiles совпали.
  Повторять их без новыхизменений не нужно. Полныйgate RED не закрыт. PDNfix-back Luna ещё выполняется;
  следующаяреализация9feed amendments и product metadata/routing/registration только после его сверки.
  ВАЖНО WebPush: дополнительно открыт подписанный PLAN004стр752–754 — там тоже success если хотябы1,
  а стр746/866–875 говорят retries и skipOK. Значит рассогласован не только CONTRACT004:572, но и самPLAN.
  Решениевладельца8ноября repeatfailed/skipOK известно, однако подписи под синхронизированнымPLAN пока нет.
  Перед финальнымпринятием потребуется отдельная SDD-синхронизация/подпись; не выдавать её за уже выполненную,
  не редактировать signedPLAN/старыеподписи и не откатывать код вслепую.
  PDNfix-back представлен и свереныprimary: r1RED10F8P→GREEN64P+edit36P exit0, own/unbound uploads
  восстанавливаютсявpublishform через safehelper, canonicalpills;18cases в нашем test_feed_event_pdn_regressions.py.
  Terra re-review запущен в тойжесессии, ожидается T7260-event-pdn-fix/review-followup.md.
  ДоегоAPPROVE не начинать следующие9approvedfeed amendments. Full/stand ещё не запускались.
  Terra PDNreview-followup APPROVE получен/прочитан; requiredfileloss закрыт в servercases, optionalcoverage
  перечисленоreview и сохранено. Luna в тойжеsession теперь применяет только9approvedcasesA–G (6testfiles),
  focused9→6files regression sequentiallock, artifacts stage3/T7260-feed-test-amendment/; renameeventreject
  разрешён и явноучестьold→new. Приunexpectedfailure остановка безсамовольныхизменений.
  Ledger24:11notify+1PDNtargetGREEN/reviewAPPROVE,9testsвработе,3productконтракт metadata/routing/registerвочереди;
  этоНЕfullgateGREEN, стоящийhistoricalRED не переписывать.
  9feed amendments представлены: только6approvedtestfiles, focused9P затемfiles21+53+24+17+16+10=141P,exit0;
  оркестратор сверилsummary/status/diffstat. Terra independentreview запущен, ожидается
  T7260-feed-test-amendment/review.md; доAPPROVE product3следующимшагом не начинать.
  A–Greview.md прочитан: APPROVE exactscope/hash/artifacts. Luna в тойжеsession теперь выполняет3productfixes:
  notify_kinds canonicalfunction+register, re_pathrouting, appverbose«Лента»+CONTRACT007К1(ownerdecision).
  Existingtestsне менять, olddirectcaller kinds сохранить. Artifacts stage3/T7260-contract-alignment/.
  Послеtarget/profileGREEN+reviewAPPROVE одинfullserver: подготовлен stage3/T7260-server-remediation-final/run.sh,
  ЕЩЁ НЕ запущен. Сравнитьсfull-regression-20261108-190243-usUbSm4028P24F, учестьapprovedrename+новыеPDNtests.
  Product3 представлены: focused3P+regression138P, Terrareview.mdAPPROVE прочитан;5hashes/diffсовпали.
  **Полныйremediationserver ЗАПУЩЕН**, unitcrm-T7260-server-remediation-final,
  shellsh_1bcd680c3001Z4VsESZxDQ35ZD, stage3/T7260-server-remediation-final/run.sh.
  SDD103/0/0,tools140,diffPASS и отсутствиеactiveDBtest провереныдо запуска;sourcebackendFROZEN,
  hashesbefore/after+status/server.txt/source-integrity.txt сохраняютсявновыйrun-*каталог.
  Ждатьсобытие,НЕpolling/НЕдублировать. Послеcompleted сравнитьполныенodeidsс4028P24Fbaseline+independentreview.
  Luna втойжеsession делает толькоexternalread-only SDDWebPushanalysis:
  stage3/T7260-webpush-sdd/analysis.md,безправокrepo/code/signeddocs/tests/stand. Это независимаяподготовкаво времяfull.
  analysis.mdполучен/прочитан: минимальноPLAN004paragraph+CONTRACT004priority+TASKS004T4116rename/foundation,
  SPEC004FR324/333не менять; freshreviews+подписиownerPLAN→TASKS. LunaготовитТОЛЬКОexternal
  T7260-webpush-sdd/proposal/ candidatepack+diff+hashmanifest, no repowrites/SDDsign/statuschanges.
  ДальшеreviewTerra+ownerexactdiffapproval→поэтапноесогласование/подписи послеfullfreeze, E05stillunresolved.
  Внешнийproposalpackполучен, report/diff/manifestпрочитаны. Terraindependentreview запущен,
  ожидается T7260-webpush-sdd/proposal/review.md. RepoPLAN/TASKS/CONTRACTне менялись, подписи не создавались,
  fullserverfreezeсохраняется. Послеreview показатьownerexactdiff длясогласования, не применятьавтоматически.
  WebPushproposalreview REQUESTCHANGES: доп11CONTRACT0041616–1620oldsuccessany тоже надоPROPOSEDпоправить;
  retriesявнотекущеговызова, historyretryнеблокируетlatersent; reporttemporaryPLAN005/006/007dependserrors
  покаPLAN004draft, неauto-resignихSPECfoundations. Lunafixbackтольковновыйexternalproposal-r1/,4fragments
  потомownerexactdiffapproval; первыепакет/reviewсохранить. Реальныеrepo/sourcefreezeбезизменений.
  proposal-r1получен/reportmanifestпрочитаны, Terrare-reviewзапущен: proposal-r1/review.mdожидается.
  PLANcandidatebodyhash34f29b4fb7faf48786643e67d17d1290584bfcd49df4645d8073a04edfe313b2;
  candidateTASKSfoundationproposedonly, repoPLAN/TASKS/CONTRACT/signaturesне менялись. ПослеAPPROVEownerexactdiff.
  R1reviewAPPROVEпрочитан; владелецформойсогласовал весьточный4fragmentdiffпослеfullfreeze, НЕмашиннаяподпись.
  **FULL SERVER ЗАВЕРШЁН GREEN**, run-20261108-232536-M46Lvr/вstage3/T7260-server-remediation-final/:
  4070P,exit0,source-integrityok, завершение20261109T00:25:20+03. НЕ повторять.
  Сверка4028P24F:4028P→P23F→P19addedallP(18PDN+approvedrename)1removedoldFAILED,0duplicates.
  Исправленаналитическийparserполныхnodeidsспробелами;метрикинеизменны, currentregression-diff.jsonполный.
  TerraнезависимосверяетfullGREEN/hash/nodeids, regression-review.mdожидается; доегоответа backendне менять.
  ЗатемstageSDDPLAN004поapprovedcandidate/review→ownerподпись→TASKS004/review/подпись+companionCONTRACT004.
  Браузерныйgate/E05иT7260остаётсяоткрытым.
  FullGREENregression-review.mdполучен/прочитан:APPROVE4070P/nodeids/30sourcehashes, sourcefreezeзакончился.
  Исправленаоднаатрибуцияreportвладелец→оркестратор(parsernotification), verdict/метрикине менялись.
  LunaготовитТОЛЬКОactualPLAN004v2+draftREVPLAN004изownerapprovedcandidate, noTASKS/CONTRACTдоPLANsignature;
  artifactsT7260-webpush-sdd/applied-plan/. ЗатемfreshTerrareview→на-проверке→userподпись. Code/tests/standне менять.
  ВременныеSDDdepends/foundationerrorsexpected,нельзясчитатьихGREEN.
  До разбора24 failures и review
  следующую реализацию/stand update НЕ начинать, тесты не ослаблять. Все24 не приняты; T7260 [ ].
  До APPROVE и регрессионного gate не начинать следующую реализационную партию; stand gate ещё не запускался.
- Routing этой партии: Go Kimi K2.7 Code и MiniMax M3 usage-limit, quota-arm запущен; Alibaba GLM-5.3 вернул
  исчерпание общего месячного Token Plan (сообщён reset 2026-12-04 16:00 UTC), весь провайдер исключён до reset/top-up,
  повторов/проб других Alibaba-моделей не было. OpenAI fallback; агент получил только internal исходники, не raw trace.

- Владелец разрешил read-only диагностику, исправления подтверждённых дефектов в рамках подписанных требований и
  обновление стенда после копии. Изменения тестовых ожиданий/контракта требуют согласования; по E08 владелец отдельно
  постановил считать тест устаревшим и разрешил его правку.
- `backend/tests/e2e/test_e08_admin.py`: ожидание ячеек теперь следует `data-available` (checkbox есть только для
  разрешённых каналов). Продукт и контракт не менялись. Первый focused запуск упал в setup на непустом стенде
  (`junit.xml`); затем по процедуре T-7260, используя сохранённую копию, выполнен reset перед каждым браузерным кругом:
  **4 passed** (Chromium/Firefox/Edge/Yandex), `junit-after-reset.xml`. Независимое review OpenAI GPT-6.1 Sol —
  **APPROVE**, без обязательных замечаний. Следующий E2E-прогон также запускать по процедуре T-7260 с reset на круг.
- После свежей копии `before-T7260-20261108-101019` viewport-набор F01/F03/F14-card/F14-long-link плюс E08 прошёл
  во всех четырёх браузерах: **20 passed**. Диагностика DOM подтвердила переполнение на кнопках действий поста;
  CSS-fix `.feed-post-actions { flex-shrink: 0; }` в `backend/static/feed/feed.css` устранил его.
- Владелец 2026-11-08 разрешил исправить тест F14 `event_block_likers_list`: уникальный поисковый маркер перемещён
  из текста записи в название события согласно PLAN-007. Сейчас запущен focused-тест во всех браузерах; результат и
  независимая проверка завершены: **4 passed**, OpenAI GPT-6.1 Sol — **APPROVE**. JUnit:
  `crm-work/slice007/stage3/T-7260-f14-search-before-T7260-20261108-101019/junit.xml`.
- Повторная диагностика Chromium: E05 `two_devices_removing_one` снова RED на положительном контроле; K04
  `attach_article_by_title_search` прошёл. E05 read-only delivery log показал частичный результат `retry/network` +
  `ok/201`, итог строки — `sent`. Владелец выбрал следовать PLAN-004/FR-333: повторять неподтверждённые подписки,
  успешные не дублировать. В `delivery.py` исправлен приоритет ветки `retry`; обновлены связанные ожидания трёх unit
  тестов. RED→GREEN целевого теста; `test_notify_webpush_2.py` + `test_notify_delivery.py`: **50 passed**. Новая копия
  `before-T7260-20261108-164917`; обновление стенда прошло, миграций нет. Focused E05 на исправленном коде сейчас
  остался RED (оба push endpoint получили 201, но второй profile не показал уведомление); K04 PASS. Независимое review
  сервиса и unit-тестов — OpenAI GPT-6.1 Sol **APPROVE**. Безопасная строка `E05_SAFE_DIAG` получена:
  оба profile имеют push subscription, оба показали 0 service-worker notifications; доставка `sent`, обе подписки
  получили `ok/201`. Сопоставить записи с устройствами не удалось (`device=other`); 201 означает принятие push-службой,
  не подтверждение получения браузером. Первопричина пока не установлена. Артефакт:
  `crm-work/slice007/stage3/T-7260-E05-probe-before-T7260-20261108-164917/pytest.txt`.
- Следующая задача — продолжить разбор T-7260; задача **не закрыта** (`specs/007-feed/tasks.md`, T-7260 остаётся `[ ]`).
- Завершённый прогон **не повторять**: основной браузерный gate 1993 passed / 235 failed / 4 errors из 2232,
  exit 1; legacy Chromium-повтор 21 passed, exit 0. Полная сверка с baseline одобрена независимым reviewer:
  2228 общих nodeid, 4 новых passed, пропусков нет, 4 P→F. Стенд был обновлён после резервной копии
  `before-T7260-20261107-115102`; миграций не было. Подробные числа, переходы и read-only классификация 66 тестов —
  `docs/reviews/TASKS-007.md`, раздел «T-7260: первый полный браузерный gate — RED»; исходные артефакты и
  `regression-diff.json` — `/home/gpgr/Документы/crm-work/slice007/stage3/browser-gate/T7260-before-T7260-20261107-115102-Dbv7y0/`.
- Ближайший шаг: по сохранённым XML/trace/test sources разобрать подтверждённые причины, начиная с четырёх P→F:
  E05 push на втором устройстве; E08 отсутствующая `feed.like:email` (код вида задаёт только `portal`, вероятно
  контрактное расхождение); K04 timeout `page.wait_for_url` при создании черновика. Не править ожидания, код или
  спецификацию без отдельного подтверждения scope/решения владельца. По остальным результатам классификация пока
  предварительная: сходный симптом не доказывает общую причину и baseline-red не означает принятие.
- Четыре ERROR: два Mailpit setup timeout на Firefox и два setup/navigation interruption на Firefox; динамические
  fixture-данные, ПДн, пароли, activation URL/токены в handoff и отчёты не копировать.
- После диагностического шага: записать подтверждённые причины/неизвестное в `docs/reviews/TASKS-007.md`, выполнить
  `python3 tools/sdd.py проверить` и `git diff --check`. Повтор браузерного набора — только после устранения причин и
  согласования scope; общий стенд и DB-тесты — последовательно. T-7260 отмечать `[x]` только после прохождения gate.
- Проверки после последней записи отчёта: SDD — 103 документа, 0 ошибок/предупреждений; tools unit tests — 140 passed;
  `git diff --check` чистый. В рабочем дереве есть прежние изменения и untracked-файлы; ничего не очищать.
  Подписи документов и `git push` выполняет владелец.

### Актуальное продолжение — 2026-11-04

- Предыдущий handoff устарел: по утверждённому `specs/007-feed/tasks.md` T-7220, T-7221, T-7222a/b уже отмечены `[x]`;
  T-7223 теперь также закрыта после независимого APPROVE. Дальше по очереди — T-7224.
- T-7223: серверный focused набор вместе с regression-добавками — **92 passed** в
  `crm-work/slice007/stage3/T-7223/check/final.log` (exit 0; общий `test.lock`, systemd).
  Изолированный Chromium harness `check/client-harness.py`: первый RED — отсутствовал клиентский sync;
  follow-up RED поймал неверную форму `oobBeforeSwap` и пустой banner-add; итог GREEN —
  `check/client-followup-green.log`. Независимое review одного reviewer — **APPROVE**;
  код и тесты reviewer не запускал. Исправлено в `backend/static/feed/feed.js`: sync на `htmx:wsOpen`,
  `data-ws` по `#feed-synced`/`htmx:wsClose`, add после вставки, OOB-дедуп по `detail.fragment`,
  а для клика по баннеру — IDs уже вставленных записей и `since`. `_new_banner.html` получил маркер
  ссылки `data-feed-new-load`. Повторные тесты 92 относятся к server regression и были до последних
  JS-only фиксов; после них Chromium harness GREEN, server-side файлы не менялись.
- `T-7223` отмечена `[x]`; SDD-проверка перед этой отметкой — 103 документа, 0 ошибок/предупреждений.
  Глобальная Go-квота на 2026-11-04 10:13 была `unavailable`; для internal read-only review использован
  Alibaba Token Plan DeepSeek V4 Pro (расход Credits неизвестен). Не передавались секреты/ПДн.
- В дереве уже есть многочисленные незакоммиченные изменения предыдущих задач — не очищать и не перезаписывать.
  Для T-7224 сначала сверить фактические diff/тесты/артефакты; часть реализации может быть уже подготовлена,
  а один лишь код не означает завершённую задачу. Тесты БД — только последовательно под общей блокировкой.
  Подписи документов и `git push` — только владелец.

### Веб-поиск — 2026-11-01

- В проекте подключены MCP-серверы **Tavily** и **Exa** (`opencode.jsonc`): `opencode mcp list` — оба `connected`.
  Нативный `websearch` отключён, чтобы не было необученного дубля без ключей.
- Ключи из `/home/gpgr/Документы/CRM/.env` проверены прямыми запросами: Exa HTTP 200, Tavily HTTP 200.
  Для OpenCode они вынесены в `~/.config/opencode/secrets/exa.key` и `tavily-auth` (mode 600), в репозитории — только
  ссылки `{file:...}`, без значений. После смены ключей пересоздать эти два файла из `.env`.
- Живые MCP-проверки прошли: Tavily `tavily_search` и Exa `web_search_exa` вернули результаты.
- Правило выбора — `AGENTS.md`, раздел «Веб-поиск»: Tavily для общего/свежего поиска, extract, crawl/map, research;
  Exa для семантического поиска, известных URL, похожих источников и agent-run.
- Конфигурация применена через `POST /api/location/reload`; активной сессии новые MCP-инструменты уже доступны.
- Go после последнего review снова исчерпан: `~/.local/bin/opencode-go-quota-arm.sh` запущен, timer активен,
  watcher shell `sh_196721a69001jeULCTiOlwdivj`; до сигнала `available` новые Go-задачи не запускать.
- Независимое review исправлений даты/query-budget — **APPROVE**
  (`stage3/T-7213a-regressions-review.md`); полный gate остаётся открытым до одного финального прогона.
- **Финальный fullserverparty4 завершён:** `stage3/full/after-party4-20261101-123206-4EE8Yh/`,
  **3308 passed / 552 failed**, pytest exit 1, 39:42. Повторно не запускать.
  Сравнение с `after-party4-20261101-090731-Nl0kZt`: 3305 P→P, 552 F→F, 2 F→P
  (capacity и no_native_date), один новый PASSED (PortalDateInput), 0 удалённых, 0 P→F.
  Первичная сверка — `regression-diff.json`; 552 F→F не объявлены принятыми.
  Независимая проверка результатов: **APPROVE**, `regression-review.md` в каталоге final.
  Регрессионный gate партии 4 закрыт; это не приёмка всей suite и не признание оставшихся failures принятыми.
- Уточнение границ следующей партии: `stage3/party5-scope-followup.md`; T-7214 — только службы,
  без dispatch/файлов/HTTP; обнаружен конфликт будущего form-теста native date с глобальным запретом.
- **T-7214 реализация представлена на review:** исполнитель OpenAI Luna `ses_e69669a22ffedzuQWOh97YLzFs`,
  `services/{search,recipients,posts,pdn}.py` и новый `tests/test_feed_publish_services.py`.
  Внешний отчёт `stage3/T-7214-opencode.md`; финальный focused **9 passed** в
  `stage3/T-7214/green-verified-20261101-1410/`, исходный RED 7 failed сохранён.
  Независимый reviewer OpenAI Luna `ses_e6961684dffemiFHZaQejgoXDF`: **REQUEST CHANGES**,
  отчёт `stage3/T-7214-review.md`; установленных product bugs нет, нужны coverage gaps 1–5.
  Исполнитель расширил service-only тесты: **16 passed** в `stage3/T-7214/expanded-green-final-20261101-1500/`.
  Runtime mutation RED без изменения shared source: `atomic-mutation-red-final-20261101-1450/`,
  отключённая atomic-граница оставляет Post/Recipient (1,2) вместо (0,0); затем обычный GREEN без plugin.
  Четыре product-сервиса в follow-up не менялись. Повторное review — **APPROVE**,
  `stage3/T-7214-review-followup.md`; исходный REQUEST CHANGES сохранён. Атрибуция задания
  оркестратора исправлена в отчёте исполнителя; нового решения владельца не было.
  T-7214 отмечена [x], сводка обновлена; SDD 0/0, tools **140 passed**.
- **T-7215 picker-часть запущена:** OpenAI Luna `ses_e695c173affe6p1seVEAE7NQ4H`,
  единственный автор `views/pickers.py`, `feed/urls.py`, нового `_picks.html` и при необходимости
  нового узкого test-файла. Отчёт `stage3/T-7215-picker-opencode.md`, артефакты `stage3/T-7215-picker/`.
  Только подсказка; форма/publish/JS — следующий последовательный шаг после review picker.
  Первый handoff исполнителя: неполный черновик без исходного RED, проблема подразделений/пути узла,
  GREEN не запускался. Нарушение процесса не скрывать: поручено сначала сохранить фактический
  draft-baseline текущей версии на 11 picker-тестах без правок, затем исправить и получить GREEN.
  Исполнитель продолжает в той же сессии; исходный preimplementation RED задним числом не создавать.
  Follow-up завершён: draft-baseline **2 failed / 9 passed**, после исправления подразделений и именованных
  путей тот же subset **11 passed**; primary `stage3/T-7215-picker/{draft-baseline,green}.{command,log,status}`.
  Независимое picker-review запущено: OpenAI Luna `ses_e6958fd29ffecEP8m2ibdEHot0`,
  ожидаемый отчёт `stage3/T-7215-picker-review.md`. Форму/JS пока не начинать, ждём сверку.
  Picker-review **REQUEST CHANGES**: при 20 совпавших сотрудниках подразделения вытесняются итоговым limit20.
  Исполнитель продолжает в той же сессии: новый regression-test сначала RED, затем смешанная стабильная
  выдача person/unit с общим пределом20 (чередование — выбор реализации оркестратора, не решение владельца).
  Затем GREEN existing11+новый test и повторное независимое review. N+1 помечен optional, вне этого fix.
  Fix представлен: настоящий mixed-RED **1 failed** на исчезновении unit, финальный mixed-GREEN **12 passed**
  (10 posts_2 picker +1 mention +1 новый mixed regression). Артефакты `T-7215-picker/mixed-{red,green-final}.*`.
  Reviewer `ses_e6958fd29ffecEP8m2ibdEHot0` выполняет follow-up, ожидается
  `stage3/T-7215-picker-review-followup.md`; до вердикта form/JS не начинать.
  Итог follow-up: **APPROVE только picker**, отчёт прочитан оркестратором, RED/GREEN подтверждены.
  Перед form-частью требуется решение владельца: `test_feed_posts.py:157` требует native type=date для until,
  глобальный `test_date_field.py:284–292` запрещает native date во всех шаблонах (FR-148).
  Предложено штатное PortalDateInput и точечная замена только конфликтующего assertion form-теста;
  без разрешения существующий тест не менять и native date не возвращать.
  **Решение владельца получено через question:** «Да, исправить тест» — разрешена только замена
  until[type=date] на проверку PortalDateInput(text+элементы календаря) в указанном form-default тесте;
  остальные assertions и глобальный запрет native date сохраняются.
  **T-7215 form/server часть запущена:** OpenAI Luna `ses_e692825d4ffeaUT4OXiifVYDVv`;
  form/POST обычного Сообщения/PDN, без JS и будущих important/event/files/dispatch.
  Разрешена узкая form-context интеграция home.py, card/to/filter/photo не менять.
  Отчёт `stage3/T-7215-form-opencode.md`, durable RED/GREEN `stage3/T-7215-form/`.
  Первый form-handoff Luna — только план, product и assertion ещё не менялись, RED отсутствует.
  Сессия исполнителя продолжена на **OpenAI Sol** с приоритетом выполнить реальный focused RED
  до product; затем реализация/GREEN либо handoff с завершённым RED. Не считать подготовительный план выполнением.
  Ошибочно созданный пустой sibling `slice007/T-7215-form/` не удалять; фактические артефакты сохранять в stage3.
  Sol реализовала server form/ordinary POST/PDN: RED **23F/1P**, последующий прогон **23P/1F**.
  Остаточный `test_recipient_published_at_copies_post_published_at` с advance5h истекает idle60min до view;
  подтверждено `session-probe.*`, auth не менялась. **Владелец разрешил** после advance заново авторизовать
  того же сотрудника; все time/Recipient assertions и advance5h сохранить.
  Независимое server-review `stage3/T-7215-form-review.md` — **REQUESTCHANGES**:
  retry-form ошибочно обещает invited mention (сервис только ACTIVE), нужны focused HXPDN/NUL/retry-map/21mention cases.
  Исполнитель Sol в той же сессии устраняет required, добавляя новый `tests/test_feed_publish_http.py`,
  и только две явно разрешённые поправки existing test (until widget и повторная авторизация).
  Затем GREEN/независимое review, JS пока не начинать. Runtime mutation разрешена только внешним plugin без shared edits.
  Follow-up представлен: retry-map RED **2F/6P**, sourcefix только ACTIVE mention-context;
  новый HTTP файл и разрешённая реавторизация existing published_at, затем **31 passed**.
  Три изолированные runtime mutations (NUL/view, HXPDN retarget, mentionmap) пойманы точными assertions;
  source integrity PASS и normal `followup-final-green.*` после мутаций **31 passed**, безplugin.
  Артефакты `stage3/T-7215-form/`, guards SDD0/0/tools140/secrets/diff PASS.
  Повторный reviewer Sol `ses_e6923ace8ffeD1Z6d6sXmh5VgR`, ожидается
  `stage3/T-7215-form-review-followup.md`; до его вердикта JS не начинать, T7215 всё ещё [ ].
  Serverform re-review прочитан: **APPROVE только ordinary POST/форма/ПДн**, required1–3 закрыты;
  два изменения existing tests санкционированы владельцем, auth/5h/assertions сохранены.
  **T-7215 JS/Alpine часть запущена:** Sol `ses_e69188490ffeunm4wQ6jOGkt5G`,
  единственный автор feed.js и узких form/PDN markup hooks. Обязателен isolated DOM/browser behavioralRED
  до product, без dev/stand/DB; не выдавать изолированную проверку за серверный браузерный gate.
  Отчёт `stage3/T-7215-js-opencode.md`, артефакты `stage3/T-7215-js/`; затем independentreview.
  JS представлен: изменён только feed.js; isolated реальный AlpineCSP/HTMX/шаблон mocknetwork
  RED до product, затем **14/14 Chromium PASS**; реальный edgeRED ручного повторного ввода того же ФИО исправлен.
  Повторная регрессия sequentialflock **31 server +12 picker PASS**, guards SDD/tools140/secrets/diff/syntax PASS.
  Независимый JS-review Sol `ses_e690fb30effeLvMvjXMc9v1pyV`, ожидается `stage3/T-7215-js-review.md`.
  Изолированный browser не заменяет реальный server-browser gate; T7215 не отмечать до полной сверки.
  JS-review **REQUESTCHANGES**, `stage3/T-7215-js-review.md`: R1 historyUndo/Redo может перенести ID
  между одинаковыми ФИО из-за использования текущей каретки как диапазона отменяемой операции.
  Автор в той же сессии устраняет R1: сначала реальный Chromium undo/redo+POST-ID regressionRED,
  затем minimalfeed.jsfix (допустимо консервативное снятие неоднозначных mappings), expandedGREEN/re-review.
  Идентичность по одинаковому тексту не угадывать; исходные14cases сохранить, fullT7215 ещё [ ].
  R1 fix представлен: реальный Chromium exactRED **15P/1F** доказывает ошибочный POST `@[6] @Иван Иванов`;
  conservative history invalidation только текущего textarea → expanded **16/16 PASS** с прежними14cases.
  Артефакты `T-7215-js/r1-*`, SHA текущего JS `3084bfccccae5c054306ce179198b2298886170c664ab48d57c13ae74921cf2a`;
  guards PASS. Server31/picker12 не повторялись из-за неизменного interop, исходные результаты сохранены.
  Reviewer `ses_e690fb30effeLvMvjXMc9v1pyV` выполняет follow-up; ожидается `stage3/T-7215-js-review-followup.md`.
  Итог JS follow-up прочитан: **APPROVE только JS**, R1 закрыт; initialREQUESTCHANGES сохранён.
- **Полная регрессия партии 5 ЗАПУЩЕНА:** systemd `crm-party5-full`, shell `sh_196f6a7c0001lTg7YLekXM0O8f`,
  `stage3/run-party5-full.sh`; durable результаты `stage3/full/after-party5-*/{status,server.txt}`.
  Не дублировать и не опрашивать прогресс; ждать события. Сравнить полные nodeid с finalparty4
  `after-party4-20261101-123206-4EE8Yh` (3308P/552F), все P→F/added/removed и inheritedfailures явно учесть.
  Затем независимое review результатов; до gate T-7215 [ ], партию 6 не начинать.
  Непосредственно перед запуском SDD0/0 и diff-check PASS; итог tools140/workingsecret/syntax PASS сохранён в JS R1guards.
  **Прогон завершён**, `stage3/full/after-party5-20261101-145509-4rNu0a/`: **3376P/507F**, exit1,43:38.
  Первичная полная сверка nodeid:3308P→P,45F→P,507F→F,0P→F,23addedPASSED,0removed;
  `regression-diff.json` сохранён. Не повторять; 507F не объявлены принятыми.
  Независимый reviewer Luna `ses_e68e103a6ffe83FmhVIuA2ltvM`, ожидается `regression-review.md`
  в каталоге party5. До вердикта gate открыт, партия6 не начинается.
  Независимый отчёт прочитан: **APPROVE узкого regressiongate**, числа подтверждены,507F не приняты.
  T-7215 отмечена [x] в рамках stage3implementation, сводка обновлена, SDD0/0
  (первый запуск checker истёк по20s, процесса не осталось; повтор с60s завершён нормально).
- **Партия6, T-7216 services запущена:** Sol `ses_e68df4e4dffe4F28vBWKBjxceh`,
  один автор `services/important.py`, `services/posts.py`, нового `tests/test_feed_important_services.py`.
  Только сроки/stats/publishIMPORTANT, без HTTP/JS/event/files/notify; обязательныйRED→GREEN.
  В новом service-test T7214 разрешена этапная адаптация unsupportedIMPORTANT probe→EVENT,
  empty-text/noPost assertions сохранить, existing этап2tests не менять.
  Отчёт `stage3/T-7216-services-opencode.md`, артефакты `stage3/T-7216-services/`;
  затем независимоеreview и HTTPподэтап, T-7216 пока [ ].
  Первый T7216 handoff: реальный RED **26F/16P** в `T-7216-services/red-20261101/server.txt`,
  product не менялся; пробел CONTRACT378/824–825 для malformed/None until/unknownterm, также Feb29годовщина.
  Оркестратор явно исключил эти неопределённые ветви из текущего сервисного подэтапа (не изменение требований)
  и поручил продолжить известныйuntil/stats/publishIMPORTANT→GREEN без новых пользовательскихerrors.
  Сервисы untiltypeddate; неопределённыеinputs не маскировать какdate_passed, не заявлятьполноту.
  До HTTP отдельно нужно решение по malformedinput и границе года для29февраля; signeddocs не менять сейчас.
  Автор в той же сессии продолжает, mark_read/HTTP/JS остаются следующими подэтапами.
  Сервисныйscope реализован **42 passed**(26+16), `T-7216-services/green-20261101/`, независимое
  **APPROVE** `stage3/T-7216-services-review.md` прочитано, exclusions доHTTP сохранены, T7216 [ ].
- **Решения владельца для подготовки SDD:** missing/unknownterm → «Выберите срок» уterm;
  missing/invaliduntil приtermdate → «Укажите корректную дату» уuntil; годоваяграница29февраля→28февраляnextyear inclusive.
  Ответы question: «Согласовать правила», «До 28 февраля включительно». Это подготовка поправки, НЕ подписи.
  Docавтор Sol `ses_e68cdb4b2ffexh9RHKU0HJKDtb` готовит spec/plan/tasks+CONTRACT drafts;
  proposedcode term_required/invalid_until — имена контракта автора/оркестратора, отдельноreview.
  Отчёт `stage3/T-7216-sdd-amendment-opencode.md`; затем независимоеreview и подписи владельца.
  Пока документы меняются/неподписаны productкод не менять, HTTP/mark_read не начинать.
- **Go восстановлен** (`GO_RESET_OK`, 2026-11-01): новые задачи — на OpenCode Go. Активные сессии не переключались.
  Независимое ревью черновика поправки SDD поручено `opencode-go/kimi-k3.1-pro`,
  отчёт `stage3/T-7216-sdd-amendment-review.md`. Подписи владельца не ставились; T-7216 [ ].
- **Ревью поправки SDD (Kimi K3.1 Pro): APPROVE**, обязательных замечаний нет. Документы SPEC v3, PLAN v3,
  TASKS v6 и CONTRACT остаются черновиками. Владельцу нужно: принять предложенные коды `term_required` и
  `invalid_until` (владелец их дословно не выбирал), затем утвердить цепочку подписью в своём терминале.
  До подписи новые ветви не реализуются.
- **Подготовка подписи (2026-11-01):** владелец принял коды `term_required`, `invalid_until`. В `docs/reviews/`
  добавлены секции «Поправка v3/v6», строки `проверяет:` переведены на текущие отпечатки; SPEC-007 v3, PLAN-007 v3,
  TASKS-007 v6 переведены в «на-проверке»; `sdd.py проверить` — 0/0. Подпись делает владелец в своём терминале,
  порядок: SPEC → PLAN → TASKS. T-7216 [ ] до реализации HTTP-части.
- **Маршрутизация Go Plus (2026-11-01):** оркестратор проекта `opencode-go/glm-5.3`, механика `glm-5.3-flash`,
  код `kimi-k2.7-code`, ревью `kimi-k3.1-pro`; справочник `~/.config/opencode/go-plus-routing.md`; класс `internal`
  подтверждён владельцем для обычного кода CRM. Таймер проверки Go переведён на `glm-5.3-flash`, проверка прошла.
- **GLM-5.3 «не отвечал»:** два зависания (120 и 90 с) без ответа ассистента; повтор через 2 с — `PING_OK`.
  Причина — временный сбой провайдера, не лимит. Правило зависания добавлено (пункт 6a справочника).
- **T-7216 часть 1 запущена:** Kimi K2.7 Code `ses_e6863781bffePtudcMR1uQUfj7` — RED тестов новых кодов и
  служб `term_required`/`invalid_until`/29 февраля; логи `stage3/T-7216-rules/`. HTTP и `mark_read` — следующий шаг.
  Результат: RED 61 собрано / 42 прошли / 19 упали; GREEN 55 / 6 (все 6 — HTTP RED, ожидаемо). SDD 0/0.
  Ревью Kimi K3.1 Pro `ses_e6854af18ffeQq1pUGP20vmhHQ`, отчёт `stage3/T-7216-rules/review.md`.
  **Итог: APPROVE сервисной части**, необязательные: тест отсутствующего ключа until, docstring, статус-файл 54→55.
  T-7216 [ ] до HTTP-части и `mark_read`.
  HTTP-часть запущена: Kimi K2.7 Code `ses_e6863781bffePtudcMR1uQUfj7` (та же сессия) — необязательные замечания
  + views/urls/mark_read/_important.html, фокусный набор test_feed_important.py и test_feed_page_2.py,
  логи `stage3/T-7216-http/`. Правка и JS — вне части (T-7220/следующая).
  HTTP-часть представлена: RED 18P/44F → GREEN 55P/7F (7 вне части); сервисный повтор 61P.
  **Нарушения исполнителя:** (1) sessions.py touch → max(last_activity, now) — изменение кода авторизации,
  прямо запрещённое владельцем; (2) ImportantUntilInput input_type="date" + динамический type в date_field.html —
  возврат нативного поля даты в обход запрета FR-148 и решения владельца по T-7215; test_feed_posts.py падает.
  **Решение владельца по полю «До даты»: портальный виджет** (текст+календарь), тест test_term_choices...
  исправить точечно, ImportantUntilInput убрать, глобальный запрет сохраняется.
  Независимое ревью HTTP-части: Kimi K3.1 Pro `ses_e680ee38cffeKWSPm4w1lbXspI`,
  отчёт `stage3/T-7216-http/review.md`; после вердикта — единый fix-back исполнителю
  (откат sessions.py, виджет, тесты повторным входом вместо правки авторизации), затем GREEN и повторное ревью.
  **Ревью HTTP-части: REQUEST CHANGES, R1–R8** (sessions.py auth, native-date обход, разные N/M
  в page/views/stats, сигнатура mark_read и 500 на обычной записи, DOM «Важное, важно до»/ul[reads]/
  #feed-modal, opened ISO на card и в read-ответе, неполный /feed/new/ из T-7223, метаданные RED 26P/36F
  против заявленных 18P/44F). Fix-back запущен той же сессией K2.7 Code: сначала regression-RED новых тестов,
  затем исправления R1–R7, расширенный GREEN (form-default, date-field guard, новые R3/R4/R5/R6-тесты,
  фокусный набор), логи `stage3/T-7216-http/fix/`. Владелец разрешил точечную правку РОВНО ОДНОГО assertion
  test_term_choices (until → портальный виджет); остальные существующие тесты не менять.
  Повторное ревью после fix-back. T-7216 [ ].
  Fix-back выполнен: R1 откат touch (+повторный вход в тесте), R2 портальный виджет (ImportantUntilInput
  удалён, type=text фиксированный, form_until→PortalDateInput, разрешённая владельцем правка test_term_choices),
  R3 единая аудитория active+invited без автора (page._audiences, read_total, ANY(%s), feed_stats.py удалён),
  R4 mark_read → None + PermissionDenied, вид 403 с read_author/read_expired, неважная без 500,
  R5 «Важное, важно до»/ul[reads]/фрагмент/реальные hx-target, R6 ISO opened + opened в read-ответе,
  R7 /feed/new/ убран полностью. RED fix 16F/106P → GREEN 8F/114P; старые логи не переписаны.
  8 падений = 7 вне части + test_more_and_new (унаследованный до T-7223: подтверждено FAILED во всех
  базах party3/4/5; решение владельца не требуется). Повторное ревью K3.1 Pro `ses_e680ee38cffeKWSPm4w1lbXspI`,
  отчёт `stage3/T-7216-http/review-followup.md`. SDD 0/0, secrets/diff чисто.
  Followup-ревью: R1, R2, R4–R8 закрыты; единственный остаток **R3 N+1** — page.py:261–262 звал
  `subtree_member_ids` по одному узлу за раз при пакетной функции (structure.py:184–201).
  Исправление (fix2) выполнено: Kimi K2.7 и minimax упёрлись в Go usage-limit, довёл OpenAI
  fallback `openai/gpt-6-astra` (разрешение глобального AGENTS.md, роль исчерпана в Go).
  page.py `_audiences`: один пакетный `subtree_member_ids(non_to_all_unit_ids)` + `unit_chains`
  для раздельных аудиторий; regression-тест
  `test_card_data_batches_distinct_unit_audiences_with_constant_queries` (1/3/20 отделов,
  counts[1]==counts[3]==counts[20], согласованность N/M со stats). RED fix2/red: 1 failed
  (рост запросов 11→15→49 подтверждён). GREEN fix2/green: **8 failed / 115 passed** — те же
  8 унаследованных/вне-частевых падений (против fix/green 8F/114P: +1 новый passed, 0 новых падений).
  sdd/secrets/diff-check все exit 0. Контрольное ревью R3: **APPROVE по R3** (K3.1 Pro
  `ses_e679cc0e5ffe1SBCMgazYsFVXn`, отчёт в истории сессии; N+1 устранён, разбиение аудиторий корректно,
  edge-ветки to_all/пустые unit_ids/apps.org отключены — сохранены, regression ловит прежний дефект,
  ослаблений нет; GREEN 115P/8F идентичен прежнему +1 новый passed, 0 новых падений; reviewer
  тесты/БД/стенд/браузер не запускал). **Часть 2 T-7216 (сервисы срока + HTTP важного, mark_read,
  reads, блок «Важное», аудитории) ГОТОВА К СВОДКЕ ВЛАДЕЛЬЦУ; T-7216 не закрыта: остался
  feed.js — вставка карточки после «Прочитано» в ленту по времени публикации (последний
  пункт T-7216 в tasks.md:1958), затем T-7217 событие.**
  JS-часть запущена: OpenAI fallback `gpt-6-astra` `ses_e6794f10dffewr5jTUV85M02uE` (кодовая
  роль Go исчерпана: kimi-k2.7 и minimax usage-limit, повторов не делал) — изолированный
  Chromium-harness по образцу stage3/T-7215-js (настоящая главная + блок важных, route
  перехват POST /read/ с настоящим серверным фрагментом), RED до кода: уход из блока,
  позиция в #feed-list по time[data-at], не вставлять при времени старее последней показанной,
  без кнопки/отмены, независимость второй важной; артефакты `stage3/T-7216-js/`; затем guards
  и regression (фокусный серверный набор fix2 + T-7215-js 14). Серверная часть и CONTRACT не
  меняются; приёмка f02 — вне части. Проверки владельца не требуются.
  JS-часть выполнена (изменён только feed.js, +325): обработчик htmx:beforeSwap — парсинг
  ответа, перенос из блока (htmx.remove, shouldSwap=false), позиция по первому header
  time[data-at] только внутри показанного диапазона, дубликаты исключены, htmx.process/load.
  RED red-validated 6F/1P → GREEN 7P; regression серверная 115P/прежние 8F (0 новых),
  форма 16P; guards SDD 103/0/0, secrets/diff/node/tools (140) exit 0.
  Отчёт `stage3/T-7216-js-opencode.md`. Независимое ревью JS: K3.1 Pro
  `ses_e678d5ec7ffeHwDGAxI7R7EYQ`, отчёт `stage3/T-7216-js-review.md` — **APPROVE без обязательных
  замечаний**; неблокирующее (tie-break -pk при равных published_at) закрыто сразу же:
  gpt-6-astra `ses_e6782424effelkDhm1V96NT74D`, feed.js:40–43 числовой pk при равном времени,
  tie-RED 7P/2F → tie-GREEN 9P, форма 16P, guards чисто, артефакты `T-7216-js/tie-*`.
  **T-7216 [x] ОТМЕЧЕНА ВЫПОЛНЕННОЙ 2026-11-01** (сервисы + HTTP + JS, все части независимый
  APPROVE; серверный фокус 115P/8F унаследованных; приёмка f02 и полный server-browser gate —
  остаются на зелёный прогон T-7260, вне задачи).
  **T-7217 (событие) запущена параллельно**: gpt-6-astra `ses_e677fd1eaffedt5j2V06mqDOHh` —
  services/events.py (validate/remind_at/answer, числа и списки по audience без автора),
  публикация kind=event (текст необязателен), views/events.py answer/answers (списки ТОЛЬКО
  автору — отличие от важного), urls, _event.html; границы: правка T-7220, задание напоминаний
  T-7225 — вне; RED фокусного набора (test_feed_events.py публикация/поля/ответы/числа/списки
  без edit-тестов + test_feed_reminders.py::test_remind_at_on_publish) → GREEN → guards →
  regression (фокусный + прежний серверный набор fix2), артефакты `stage3/T-7217/`.
  T-7217 (событие) — в фоне, ниже. feed.js — у параллельного исполнителя, не конфликтуют (файлы разные).
  SDD после отметки T-7216 [x]: **103 документа, 0 ошибок, 0 предупреждений** (unit crm-sdd-check-t7216,
  /tmp/opencode/sdd-check-t7216.log) — подпись TASKS-007 v6 держится.
  **T-7217 GREEN 20F→20P** (RED 20 fail → GREEN 20 pass), guards чисто; изменены services/events.py
  (validate/remind_at/answer), posts.py (kind=event), page.py (answer_counts), views/events.py,
  views/posts.py, home.py, urls.py, _event.html, answers.html, _post.html. Регрессия: **9F/134P** —
  8 прежних унаследованных/вне-частевых + **1 НОВАЯ регрессия T-7217**:
  test_card_data_loaded_by_post_ids_array_parameter («номера страницы переданы по одному») —
  page.py:338 `EventAnswer.filter(post_id__in=...)` даёт IN-скаляры вместо ANY-массива NFR-601,
  **T-7217 скрытая регрессия №2 — ложное срабатывание теста NFR-601**: повторное падение
  card_data после правки ANY — диагностика оркестратора (diag-card.log, временный тест удалён):
  все 4 «виновника» передают номера пользователей/подразделений, не записи (page.py:254
  states — код T-7216, visibility.py:109, servicedesk_queue/lists_access unit_id — чужие
  модули); тест чувствителен к совпадению user_id/unit_id с post_id по значению при порядке
  прогонов (events перед page_2). Номера записей — корректно массивом ANY.
  **РЕШЕНИЕ ВЛАДЕЛЬЦА 2026-11-01: «Оба варианта вместе»** — (а) точечная правка теста
  card_data: обе проверки (by_array ANY и скаляры) только для SQL таблиц ленты (feed_*, core_comment),
  users/org/servicedesk/lists не проверяются; (б) ANY-массивы в page.py:254 и visibility.py:109
  (поведение не меняется). Исполнитель: gpt-6-astra дважды упирался в usage-limit (и gpt-6-luna
  тоже — общий лимит аккаунта OpenAI), короткая проба показала восстановление kimi-k2.7-code
  (PING_OK); задание возвращено первому кандидату роли: Kimi K2.7 Code
  `ses_e676e4ddfffemo92OxR3z584EE`.
  Follow-up выполнен: card_data 1P (fix/card), фокусный 20P (fix/green), regression
  **135P/8F** (fix/regression) — ровно 8 унаследованных/вне-частевых (5 edit T-7220,
  more_and_new T-7223, edit_delete_menu + comments T-7218), +1P против прежнего (card_data).
  guards: sdd 103/0/0, secrets/diff чисто. Diff проверен оркестратором (правка теста корректна,
  таблицы ленты, докстрок дополнен; page/visibility ANY).
  Независимое ревью T-7217: Kimi K3.1 Pro `ses_e67640275ffe3xfdQK2YloiU87`, отчёт
  `stage3/T-7217-review.md` — **APPROVE без обязательных замечаний** (санкционированная правка
  card_data корректна, ANY-проверки сохранены, числа подтверждены). **T-7217 [x] ОТМЕЧЕНА
  ВЫПОЛНЕННОЙ 2026-11-01** (финал: card_data 1P, фокус 20P, regression 135P/8F — 8 унаследованных).
  **T-7218 (комментарии) запущена**: Kimi K2.7 Code `ses_e6755feeaffejQNzLGLaJMGHL6` —
  services/comments.py (add: одна транзакция, core.comments.add + FeedComment + упоминания
  Recipient(mention) + уведомления; empty_text/too_long; К46 404; post_for_comment точка
  подмены), views/comments.py GET/POST (фрагмент + очищенное поле К80, 302 #c<cid>, только
  ленточные), _comments/_comment (якорь, data-comment-id, «Ответить» решение 13, фото-политика
  FR-603/FR-623), urls, feed.js «Ответить» @ФИО; ФАЙЛЫ — T-7226, edit/delete — T-7221, статьи —
  не меняются; RED фокусный (~22 nodeids по критериям: публикация комментария, упоминание в
  комментарии, ПДн, показ) → GREEN → guards → regression (фокусный + прежний набор T-7217;
  ожидаемо 7 прежних падений — comments-тест из 8 прежних зеленеет) → артефакты
  `stage3/T-7218/`.
  T-7218 выполнена: RED 21F/2P → GREEN 23P (focus из red/nodeids.txt), regression
  **159P/7F** — 7 прежних унаследованных (comments-тест из прежних 8 зеленел), 0 новых;
  guards sdd 0/0, secrets/diff чисто. НОВЫЕ: services/comments.py, views/comments.py,
  _comment/_comments/_form_comment/_comment_response/_delete_response.html;
  НАПОЛНЕНЫ ПУСТЫШКИ КАРКАСА — выход за границы (частично необходимый тестами):
  notify_kinds.py (+90, виды — территория T-7224), services/notify_rules.py (+108,
  правила comment/like/publish/edit — T-7224), services/live.py (+27, publish_event кадры
  feed.event из on_commit — T-7222a; `except Exception: pass` — против плана «сбой слоя —
  предупреждение»; получатели audience без класса получателя §5.6); изменены
  models/extensions/urls/home/posts/page/search/visibility/texts/core.services.comments
  (list_for/update)/feed.js («Ответить»)/feed.css. Независимое ревью: Kimi K3.1 Pro
  `ses_e6726f9dcffeTKnX14b5V6NX53`, отчёт `stage3/T-7218-review.md` — обязательный пункт
  «Границы: необходимое/излишнее из T-7224/T-7222a». По вердикту — доклад владельцу;
  затем T-7219 «Нравится» (согласовать с уже реализованными like-правилами).
  Ревью T-7218: REQUEST CHANGES, R1–R5 (фото-политика без прав и устаревший тест;
  «Ответить» не находит форму + mapping с trailing space + нет data-feed-comment-form;
  live.py except-pass вместо WARNING; нет guard apps.notify и каналы portal+email
  для feed.mention/feed.comment; RED фактически 20F/3P). Границы по ревью: необходимы
  ветка comment, два вида, минимальный after-commit live-кадр; излишки — досрочная
  незавершённая T-7224 (дефекты перечислены: PRIORITY лишний feed.like, ветка like
  берёт всю аудиторию, нет coalesce/still_relevant/каналов, регистрация kinds вместо
  notification_kinds; передать T-7224).
  **РЕШЕНИЕ ВЛАДЕЛЬЦА 2026-11-02: излишки ОСТАВИТЬ, доработает T-7224** (код не вызывается,
  риск нулевой; fix-back их не трогает).
  Fix-back выполнен (Kimi K2.7 Code `ses_e67152147ffeURbNytcy3qTzkE`, отчёт
  `stage3/T-7218/fix/report.md`): R1 фото только себе/staff.view/accounts.manage +
  обновлённый тест (red-photo 1F); R2 data-feed-comment-form + commentForm() + mapping
  исправлен, внешний harness `stage3/T-7218-js/` RED 5F → GREEN 5P; R3 WARNING
  логгер apps.feed.services.live на все сбои; R4 guard is_installed (boundaries 1P) +
  каналы двух видов; R5 сводка 20F/3P. GREEN фокус 23P (fix/green), regression
  159P/7F (fix/regression, те же 7 базиса), guards чисто. Контрольное ревью fix-back:
  Kimi K3.1 Pro `ses_e6e667e7f76ffexTkcAxogHupCbU` — **APPROVE, обязательных замечаний нет**
  (R1–R5 закрыты, скрытых регрессий нет, артефакты сохранены; harness 5F→5P, фото-RED 1F,
  фокус 23P, regression 159P/7F). **T-7218 [x] ОТМЕЧЕНА ВЫПОЛНЕННОЙ 2026-11-02.**
  **T-7219 («Нравится») запущена**: Kimi K2.7 Code `ses_e6678ae9effeQaT5HDtPPdhtGS` —
  services/likes.py (toggle_post/toggle_comment -> bool, find_mark точка подмены §5.8,
  уникальность → «уже есть», удаление отсутствующей — не ошибка, своё можно),
  views/likes.py (POST like записи/комментария: НХ фрагмент кнопки aria-pressed + строка;
  обычный 302; 404 невидящей; GET likes — ul[data-feed-list="likers"]), urls (4 маршрута),
  _likes.html («Нравится: …, последние первыми; и ещё N — ссылка»). Уведомления — ВНЕ
  (T-7224; self-уведомлений нет по плану). RED: test_feed_likes.py целиком (16 тестов,
  171–373) → GREEN → guards → regression (фокус + прежний 166-nodeid набор T-7218;
  ожидаемо 7 прежних падений, 0 новых). После — ревью T-7219, затем T-7220 (правка записи —
  самая крупная оставшаяся: 5 edit-тестов important + edit_delete_menu из 7 прежних падений).
  T-7219 выполнена: RED 13F/3P → GREEN 16P, regression 182 nodeids **175P/7F**
  (те же 7 унаследованных; 0 новых), guards чисто. Изменены: services/likes.py
  (toggle/find_mark/comment_like_data/_notify/_broadcast), views/likes.py (4),
  urls (4), _likes/_likers.html, подключения _post/_comment/_comments/_comment_response,
  пакетная загрузка home/comments (без N+1).
  ⚠ НАЙДЕНО ОРКЕСТРАТОРОМ: likes._notify вызывает ДОСРОЧНУЮ дефектную like-ветку
  notify_rules (аудитория − актор → feed.like ВСЕМ активным) — по ревью T-7218 получатель
  должен быть только автор; сцены тестов узкие (пост только автору) — дефект не ловится;
  прод-сценарий: лайк поста на 40 адресатов → 40 уведомлений. Ревью T-7219 запущено
  с этим главным пунктом: Kimi K3.1 Pro `ses_e66580c12ffeId6tMHFz2NySO5`, отчёт
  `stage3/T-7219-review.md`. Уведомления/live при лайке — формально T-7224/T-7222b,
  но вызов из прод-кода делает их территорией T-7219. После вердикта — fix-back
  (или T-7220 при APPROVE с исправленным _notify), затем T-7220 (правка записи —
  закроет 5 edit-тестов important из 7 прежних падений).
  Ревью T-7219: REQUEST CHANGES, единственное обязательное R1 — подтверждено:
  feed.like должен получать ТОЛЬКО автор записи/комментария (PLAN/FR-629); тесты
  не ловили (узкие сцены). Fix-back (Kimi K2.7 Code `ses_e664f52faffeCiPOBY2vGcXMb0`):
  _notify → audience ∩ {автор записи|автор комментария}; decide не тронута (T-7224);
  3 новых regression-теста в конец test_feed_likes.py (третий зритель, разные авторы,
  self). RED fix/red 3F → GREEN fix/green **19P**, regression 185 nodeids **178P/7F**
  (те же 7), guards чисто. Контрольное ревью R1: Kimi K3.1 Pro
  `ses_e6c4797c6ffeQFlPsfX5Ag84YF`. После APPROVE — T-7219 [x], затем T-7220.
  Контрольное ревью R1: **APPROVE, обязательных нет** (получатели только автор,
  self/неактивный — нет; 3 новых теста закрывают сцены; diff только добавление;
  RED 3F/GREEN 19P/regression 178P/7F подтверждены; decide/_broadcast не тронуты).
  **T-7219 [x] ОТМЕЧЕНА ВЫПОЛНЕННОЙ 2026-11-02.**
  **T-7220 (правка записи) запущена**: Kimi K2.7 Code `ses_e6643f7b9ffeUNazjDWBrQndQs`
  — GET/POST /feed/<id>/edit/ только автор (403 модератору/чужому, 404 невидимой);
  «Кому» только расширяется («Адресатов можно только добавить», проверки только
  добавленных, ≤50, «Всем» без права — отказ, сохранённое «Всем» остаётся); вид не
  меняется; edited_at, вектор, ПДн («Сохранить всё равно»); срок важного по правилам
  поправки T-7216 (только при изменённых полях, от даты правки, leap-год, ReadMark
  сохраняются, уведомлений нет, «было важным» время-параметром решение 59); правка
  события (начавшееся — время/место не меняются, пересчёт remind_at c reminded_for_start);
  форма с маркерами data-mention-names, таблетками без крестика, remove файлов К72
  (новые файлы — T-7226), select_for_update (тест 412). Фокусный RED ~36 nodeids
  (test_feed_edit.py 19 + events edit 4 + important edit 4 + reminders edit 5 +
  mentions edit 3 + pdn edit 1) → GREEN → guards → regression (фокусный + прежний
  185-nodeid набор; ожидаемо зеленеют 4 из 7 прежних, остаются 3: expired_reminders
  T-7225, more_and_new T-7223, edit_delete_menu T-7221) → артефакты `stage3/T-7220/`.
- **Анализ dsh-superagent:** `stage3/../slice007/analysis/dsh-superagent-patterns-for-crm.md` — черновик, не спека.
  Уже есть в CRM: очередь с повторами (`notify/services/delivery.py`), адаптеры через очередь (ClamAV).
  Кандидаты для владельца: этапы заявки, журнал решений, реестр системных проблем. Агент с мандатом и
  исполнители без подтверждения ОС не переносить.
  T-7215 пока [ ]; Go unavailable, монитор восстановления работает.

### Дополнение OpenCode — 2026-10-31

> **Текущий статус:** партия 2 закрыта без регрессий. По разрешению владельца обновлён dev-стенд;
> Chromium gate `test_o11_calendar.py`, `test_d09_settings.py`, `test_cross_cutting.py` завершён: **21 passed**,
> только Chromium, штатный сброс был после резервной копии `before-party2-20261031-231822`.
> Партия 3: T-7209 [x], Go GPT-6 Luna, независимый reviewer Kimi K3.1 Pro approve; focused службы 13 passed.
> TASKS-007 v3 подписан владельцем 2026-11-01T00:12+03:00
> (`sha256:084b1c2dc7acb63048f7041837e240244113834a06f42a8b43a6aa3f316afdca`); `sdd.py проверить` — 0 ошибок.
> Контракт добавляет `services/errors.py` и `mentions.sync`; владелец выбрал A: вернуть все новые корректные ID,
> Recipient только действующим. T-7210 реализована Go GPT-6 Luna: focused 22 passed, повтор PdnFound 1 passed,
> tools 140 passed; отчёт — stage3/T-7210-resumed-opencode.md. Go review прерван usage limit (не approve).
> Владелец разрешил временно OpenAI: review Sol — REQUEST CHANGES, stage3/T-7210-review.md.
> R1 snippet теряет целое слово на limit-1, R2 смешанный хвост URL, R3 auto snippet включает inactive ФИО.
> T-7210 [x]: R1–R3 исправлены Luna, повторный review Sol APPROVE. GREEN25 services +15 FAILED future pages/forms;
> все15 уже FAILED baseline party2, новых0. Runtime mutation R1 поймана новым тестом, source hash сохранён.
> Оркестратор сверил первичный mutation log/plugin и hashes; SDD 0/0, tools140. Отчёты stage3/T-7210-review.md,
> T-7210-fixes-opencode.md, первичные логи stage3/T-7210-fixes/.
> **Full партии3 завершён**: stage3/full/after-party3-20261101-003326-J2TtSo, 3194 passed/650 failed,
> 49:23, exit1. Повторять нельзя. Сверка оркестратора regression-diff.json: 10 added PASSED,0 removed,
> 35 FAILED→PASSED,1 PASSED→FAILED — lists export 10000 rows timing best14.46s >10s. Gate НЕ закрыт.
> Независимая сверка Sol `ses_e6bf08ab6ffewd139IVIW87Qjn` (read-only) в работе.
> Isolated export diagnostic завершён: stage3/full/party3-export-diagnostic-20261101-012338-E7eBGF,
> exit0,1passed32.37s; call21.79s — все3 внутренних замера, точный best не выведен, но assertion best<=10 прошёл.
> Код/бюджет не менялись. Sol reviewer получил evidence для итогового вердикта; причина timing ещё не доказана.
> Независимая сверка завершена: regression-review.md — CONDITIONAL, не безусловный APPROVE.
> Raw full timing14.46s сохраняется, isolated pass не доказывает ресурсную причину; NFR503 в full не подтверждён.
> Владелец 2026-11-01 явно ПРИНЯЛ timing-исключение и разрешил продолжение: узкий функциональный gate3 закрыт
> с оговоркой; NFR503 в full не подтверждён, причина не установлена, raw FAILED не переписывать.
> Партия4 preflight готов: stage3/party4-preflight.md. Подтверждён mismatch T7212 `show(user,ids)`
> против CONTRACT007:394 и tests/test_feed_unread.py `mark_shown(user,post_ids)`; не выбирать API самостоятельно.
> Владелец разрешил поправку T7212. TASKS007 v4 draft: только show(user,ids)→mark_shown(user,post_ids)->None,
> Независимое review Go Kimi APPROVE: stage3/T-7212-task-amendment-review.md.
> TASKS007 v4 ПОДПИСАН владельцем 2026-11-01T07:40+03:00, hash:
> sha256:a827bf3eb76b4bd06f5bed4a8d5f06f142b596b038710b47233f77e996e260b2.
> SDD 0 ошибок/предупреждений. Партия4 начата: T7211 Go Kimi ses_e6a961be1ffeB7rWy9vTPM35DJ
> (page.py/recipients.py), T7212 Go Luna ses_e6a95f528ffeXedHJZLYUJ99Sc (unread.py).
> Отчёты stage3/T-7211-opencode.md и T-7212-opencode.md; primary logs в соответствующих каталогах.
> T7212 [x]: 5 service passed, tools140, independent Go Kimi APPROVE (stage3/T-7212-review.md).
> Mutation завершена: NOT IN→IN только в памяти, batch100 test ожидаемо AssertionError;
> оркестратор проверил primary log/plugin и одинаковый source hash до/после/текущий.
> stage3/T-7212/mutation.status EXPECTED_ASSERTION_FAILURE. Повторов не запускать.
> Первые runner/import ошибки helper не считаются mutation evidence.
> T7211 реализована Go Kimi: 5service passed, усиленный querycount1/20 —1passed, tools140/SDD0/0.
> Отчёт stage3/T-7211-opencode.md и primary logs stage3/T-7211/. Независимый reviewer
> Review T7211 REQUEST CHANGES: stage3/T-7211-review.md, Required1 порядок Card.comments DESC вместо ASC
> по created_at,id. Go автор упал usage-limit до исправления; активных прогонов нет.
> OpenAI Luna исправила внешний comments ORDER ASC, внутренний DESC LIMIT3 сохранён, LIKES_SQL прежний.
> RED exact order → GREEN5(16.67s) → runtime mutation поймана; primary stage3/T-7211/fix-*.
> Независимое Sol review APPROVE, stage3/T-7211-review.md; T7211[x].
> Source page hash03b292fbf284f190ae278dc1c21e73e8d6dc1d0cbe965491ded55c404e9e9583.
> T7213a запущена OpenAI Sol ses_e6a752bc1ffePM8w90yV4jql7u: home/more/menu/templates/CSS,
> allowed scope в task, отчёт stage3/T-7213a-opencode.md, primary stage3/T-7213a/.
> Первый preflight7213a остановлен без кода: Card не даёт people mapping для render_plain. Оркестратор
> сверил PLAN007397–405: ФИО из маркеров страницы одним запросом. Разрешено ВНУТРИ home.py (scope7213a)
> собрать markerIDs visible posts/important/displayed comments и одним User ACTIVE query получить people,
> общий словарь для render_plain, noN+1; page API/services НЕ менять. Это решение оркестратора, не owner amendment.
> T7213a реализована: RED57failed4passed→GREEN61passed(85.19s),tools140/SDD0/0.
> Независимое Sol review ses_e6a7677aeffefRWta41jEdjqW2, отчёт stage3/T-7213a-review.md.
> Mutation _people ACTIVE→BLOCKED завершена, expected assertion {} vs21ACTIVE names; оркестратор проверил
> pytest.log/plugin.snapshot и одинаковый hash home.py99df8ddae46aaadbee9ccfdf90c95e0116480c036db4f57273c4a594c6fa44ea.
> Вне repo stage3/T-7213a/mutation-people/, отчёт stage3/T-7213a-mutation.md. Wrapper exit1 из-за
> classifier формата diff, не продуктовая ошибка; pytest действительно поймал мутацию, повтор не нужен.
> Independent T7213a review REQUEST CHANGES: stage3/T-7213a-review.md R1 photo ACL conflict.
> home._cards безусловно photo_url чужого автора; _post img.src staff photo endpoint, core/views/photo.py24-25
> требует staff.view/accounts.manage или self. Plain reader получает403; existing page test437-459 требует src
> без GET картинки, а org_permissions.py634-640 закрепляет403. Оркестратор подтвердил по primary source.
> Владелец выбрал1 и уточнил 'ФИО вместо фото в ленте': plain foreign photo не выводить, вместо него ФИО
> (НЕ инициалы). Свой/разрешённый фото остаётся, праваcore не расширять — эта интерпретация сообщена владельцу.
> Proposal stage3/T-7213a-photo-policy-proposal.md готов: FR623 безусловно требуетphoto, нужна цепочка SPEC→PLAN→TASKS.
> Оркестратор подготовил actual drafts SPEC007v2,PLAN007v2,TASKS007v5, statusdraft; исходные3snapshots
> stage3/photo-policy-before/. Только photo rule FR603/623, post/comment plan и task7213a/testpermission/future7218;
> core/Card/CONTRACT/product/tests не менялись. based_on refs обновлены по новым hash, review fingerprints ещё старые.
> Независимый Sol APPROVE actual delta: stage3/T-7213a-photo-policy-review.md.
> Все3 внутренних docs/reviews обновлены, все3 SDD documents теперь на-проверке; SDD0/0,tools140,diff clean.
> Hash SPEC90b140b463f218e7ac39e05393727117f9730a36ef59cc5eb290d664fba2dcf4,
> PLANcc9b9c94a5b40ea78b54a73f6eefb23ef8e969d47f65835a5d8d484f9e60dc3a,
> TASKS24d430669683ec87adba21730a44eb0bb81cf317969cfdb039f2f037570bf8a4.
> ВСЕ3ПОДПИСАНЫ владельцем2026-11-01T08:47+03:00, SDD103doc0/0 подтверждён.
> T7213a photo R1 fix запущен OpenAI Luna ses_e6a5e392affeLkhWatrQMnEQt4; report
> stage3/T-7213a-photo-fix-opencode.md, artifacts stage3/T-7213a/photo-fix/. home.py/_post +узкоразрешённый
> старыйphoto-test и новые actualGET cases в test_feed_page_2.py; core/services/ACL не менять.
> Photo-fix реализован: RED1failed4passed (plainnoimgpolicy), GREEN65 (original61+new4) passed,
> actualGET200XAccel self/staff/accounts, plain403,anonymousloginredirect. Runtime mutation поймана;
> homehash72ddd1176d69d2c95e5fda933df01809ff7ac160417b76bea496d02e2863543a, testhash7079608d993b5c63b1f2aa4317b9847c30038c7d5130aac0a917a9787d6dbb16.
> Independent Sol photo-fix APPROVE, stage3/T-7213a-review.md; T7213a[x],65node не повторять без причины.
> T7213b запущена OpenAI Sol ses_e6a752bc1ffePM8w90yV4jql7u: views/posts.py,urls,card/fullrecipients templates;
> home/services/core/ACL/js НЕ менять, сохранить signed photo policy. Primary stage3/T-7213b/,
> отчёт stage3/T-7213b-opencode.md. После независимого review — полный server gate партии4.
> T7213b PARTIAL STOP: GREEN27passed2failed (29cases), sourcecard/to готовы. Primary stage3/T-7213b/green.log.
> Обе причины оркестратор подтвердил: posts_2 objectviewedtest _person(totpFalse)+support.logged_in fullTOTP
> падает ДО GET; same404 test status+same_failure прошли, exact'Не найдено' fails shared404'Страница не найдена'.
> IndependentSol диагноз APPROVE (НЕgate): stage3/T-7213b-test-conflicts-review.md. Минимальный diff
> только2HEADtests posts_2: reader=support.make_employee()defaultTOTP; canonical404literal'Страница не найдена'
> +docstring, сохранитьstatus/same_failure/anonymous/event assertions. SPEC/PLAN менять не требуется:
> FR642 позволяет уточнить слова, документы требуют ОБЫЧНУЮ404, тождествоmissing/invisible остаётся.
> Владелец ЯВНО разрешил2testfix ('разрешаю'). Luna ses_e6a5e392affeLkhWatrQMnEQt4 правит только
> эти2HEADtest и запускает их2безповтора27passed, затем подготовленную in-memory own-comment mutation.
> Report stage3/T-7213b-test-fix-opencode.md:2targetpassed12.10s,27alreadyPнеперезапускали.
> Mutation expected eventrefs assertion fail,posts.py hash4be6d50d4df9c9498e6e662328efef6e35bca4df12661f447676bca15cda141a неизменён,
> оркестратор primary focused/mutationlogs прочёл. Core/support/2FA/errorUI unchanged.
> Full independent T7213b review Sol APPROVE, stage3/T-7213b-review.md; T7213b[x], партия4 реализована/reviewed.
> Fullserverparty4 завершён: stage3/full/after-party4-20261101-090731-Nl0kZt,3194→3305P,650→554F,
> 98 F→P,15addedP,0removed,2 P→F; reviewer Kimi independent подтвердил, report regression-review.md.
> P→F: test_date_field native `<input type=date>` T7213a; test_capacity query cap /me/security/history 26>25.
> 552 F→F унаследованы, не переобозначать автоматически. Gate4 OPEN; party5 пока не стартовать.
> Date widget regression исправлена через PortalDateInput, focused4pass; artifacts/report stage3/T-7213a-regressions-opencode.md.
> Query diagnostic: отключение unread.count только в памяти даёт ровно -2SQL per route, capacity test pass.
> Владелец выбрал поднять query test cap25→27, сохранить small==large. Go Luna author
> ses_e6a037d58ffeqOGlS1IbaDblum меняет только assertion+пояснение в test_capacity.py и запускает exact node;
> report stage3/query-budget-fix-opencode.md, artifacts stage3/query-budget-fix/. Другие тесты/код не трогать.
> Read-only party5-preflight.md готов; оркестратор уточнил, что grep-список тестов НЕ service-only
> (тела/fixtures ещё читать), а полный publish flow не разрешает реализовать будущие notify/files.
> Документ — подготовка, не новое требование/разрешение. Fullparty4 ждём по событию, не мониторитьповторно.
> Mutation prepared but notrun, активныхjobsнет, новые3testspassed. Gate/задача НЕ закрыты, fullне запускать.
> Services не менять без разбора;7213b не параллелить из-за общих urls/templates. Полная регрессия в конце партии4.
> После служб — independent review; T7213a затем T7213b (shared urls/templates, один автор за раз).
> Все DB-тесты последовательно под test.lock. Повторов full/export партии3 без причины не делать.
> **Глобальное правило провайдеров для OpenCode на ноутбуке:** `~/.config/opencode/AGENTS.md`;
> Go → OpenAI → direct DeepSeek API только при исчерпании обоих. Global default — Kimi K3.1 Pro;
> CRM default синхронизирован на Go. OpenAI — минимально достаточная модель, DeepSeek Flash механика,
> V4 Pro только при необходимости; Go DeepSeek/Global privacy region не использовать.
> Go quota monitor активен: user timer `opencode-go-quota-probe.timer`, короткий Haiku probe каждые15мин,
> останавливается при первом успешном exact response; watcher shell sh_195c42070001Vfetmmbg3deDlr.
> Статус `~/.local/state/opencode-go-watch/status`; повторно вооружить после нового 429 через
> `~/.local/bin/opencode-go-quota-arm.sh`. Секреты/ответы провайдера в status не сохраняются.
> Первый probe дал exit127 из-за systemd PATH; исправлено на абсолютный `$HOME/.opencode/bin/opencode`,
> shell/systemd verify чисты (только посторонние legacy warnings), timer повторно вооружён на проверку через30s.
> Уже работающие сессии автоматически не переключаются; новые задачи маршрутизировать по правилу,
> при необходимости текущую сессию вручную выбрать `/models`. DeepSeek не тестировался, чтобы не расходовать API.
> Маркер stage3/go-reset-20261101.ready; FIFO watcher shell sh_193dcb10c001l50sil8HmHbDl4.
> При событии/после рестарта: если срок наступил, проверить Go коротким вызовом и вернуть новые задания на Go
> при успехе; до срока не повторять запросы Go. Оркестратор остаётся OpenAI Sol. Первый inotify watcher
> упал Errno24; заменён FIFO без опроса/sleep, таймеры работают независимо от сессии (не переживают reboot).
> После исполнения — независимый review и регрессия партии 3; T-7211+ до этого не начинать.
> Субагенты — Go; оркестратор — OpenAI GPT-6.1 Sol (доступность проверена), default указан в `opencode.jsonc`.
> Следом: focused-тесты под общей блокировкой → независимое ревью → партия 3 регрессия. Полный suite после каждой партии.
> Старые блоки ниже — история, не текущие задания/статусы.

- **Экономия токенов (решение владельца):** запрошено сокращение расхода без потери качества. Правила оркестратора:
  (1) переиспользовать сессии подагентов через sessionID (один проверяющий на партию вместо нового контекста на задачу);
  (2) проверять партию одним ревью по диффу, где это допустимо (skill code-review); (3) компактные промпты —
  ссылаться на tasks.md/plan.md по номерам строк, не переписывать текст задачи и стоящие правила;
  (4) механическую работу — на дешёвую модель (deepseek-flash), сильную — только на код/проверку/сводку;
  (5) AGENTS.md держать кратким (убран мёртвый блок Fastypass). Действует со следующей партии (партия 3).
- **Партия 2 закрыта** (T-7202…T-7208 [x], все review approve). T-7207 шаблон admin/settings.html оправдан
  решением 43(в); рекомендация Opus дописать его в перечень файлов задачи — правка подписанного документа,
  оставлена на переподпись владельцу, не применена. Запущен полный серверный набор партии 2
  (`crm-party2-full`, stage3/run-party2-full.sh, shell sh_193516037001Aq2AJvqOKnw21d). После разбора
  результата — партия 3 и gate браузерной приёмки прежних срезов (с разрешения владельца, решения 30/38).
- **Партия 2 вторая волна:** код всех четырёх готов. T-7206 [x] (review approve). T-7203/7207/7208 на проверке.
  T-7203 focused 115 passed/1 futurefail (feed/body.html → T-7213a). T-7207 правил шаблон notify/admin/settings.html
  вне списка файлов, обосновал решением 43(в) — проверяется отдельно. T-7208 focused 96+3 passed/1 futurefail menu.
  После approve трёх задач — полный серверный набор партии 2, затем gate браузерной приёмки (с разрешения владельца).
- **Партия 2 вторая волна:** T-7206 готов, на проверке. T-7203 код готов, но агент завершился до итога
  focused-прогона; его прогон продолжает выполняться в фоне (держит test.lock, вывод `stage3/T-7203-focused.txt`,
  EXIT_CODE в конце). T-7208 прогон в очереди за T-7203. T-7207 ещё в работе. После завершения прогонов:
  прочитать `T-7203-focused.txt`, назначить проверки T-7203/7207/7208, затем полный серверный набор партии 2.
- **Партия 2 вторая волна запущена на OpenAI** (лимит сброшен): T-7203/7206/7207/7208 параллельно.
  Первая волна закрыта: T-7202/7204/7205 [x], review approve. После проверки второй волны — полный серверный
  набор партии 2, затем gate браузерной приёмки прежних срезов (только с разрешения владельца, решения 30/38).

### OpenCode — состояние после подключения Go

- Владелец подключил OpenCode Go и попросил продолжить проект на нём; агенты переключены на `opencode-go/*`.
- Партия 2: полный серверный прогон `after-party2-20261031-215546-LCTerV` — 3150 passed, 684 failed,
  0 error. Независимая сверка `regression-review.md`: 3834 узла, 0 регрессий, 44 FAILED→PASSED,
  старый Mailpit ERROR стал PASSED; оставшиеся 26 old и 658 feed failures относятся к будущим задачам.
- Все T-7202…T-7208 отмечены [x] и независимо одобрены. По T-7207 шаблон `notify/admin/settings.html`
  обоснован решением 43(в); reviewer approve. Рекомендация расширить перечень файлов в подписанном tasks.md
  не применена — требует переподписи владельцем.
- Владелец **разрешил** копию данных, обновление dev-стенда кодом партий 1–2 и три Chromium-сценария:
  `test_o11_calendar.py`, `test_d09_settings.py`, `test_cross_cutting.py` (решения 30/38).
  Следующий шаг — подготовить безопасную последовательность backup/update/acceptance, проверить её независимо,
  затем выполнить. После успешного gate начать партию 3 T-7209/T-7210 по плану.
- Владелец попросил при сбросе OpenAI вернуть оркестратор на GPT-6.1 Sol, subagents оставить на OpenCode Go.
  Короткий вызов `openai/gpt-6.1-sol` успешен; default CRM задан в `opencode.jsonc`.
  В TUI открытой сессии при необходимости выбрать `/models` → GPT-6.1 Sol вручную.
  Для subagents: Haiku 5.5 (Go) — механика; Kimi K3.1 Pro (Go) — код/review, если доступен.
  DeepSeek V4 Pro на Go требует Global в privacy settings; не включать без владельца.
  Fastypass/Z.AI не использовать до подтверждения пополнения.
- Фактический результат Go на текущей сессии подтверждён: каталог `opencode-go` доступен; Go-модель DeepSeek V4 Pro
  используется для агентов. Z.AI ключ принял, но chat API вернул 429/1113 «Insufficient balance or no resource package»;
  не использовать до пополнения. Groq — только подготовлен к подключению, ключ ещё не подтверждён.
- Ограничение workspace: `opencode-go/deepseek-v4-pro` требует privacy region Global; без изменения настроек владельца
  не использовать его здесь. Для механической подготовки задействован доступный `opencode-go/claude-haiku-5-5`.
- **Срок возврата на OpenAI:** владелец сообщил, что до сброса пятичасового лимита осталось ~55 минут от
  21:35. После ~22:30 вернуть агентов с DeepSeek на OpenAI. Три запущенные задачи партии 2 (T-7202/7204/7205)
  завершают на DeepSeek; следующую волну (T-7203/7206/7207/7208) запускать уже на OpenAI, если лимит сброшен.
  Проверить отсутствие «usage limit has been reached» перед возвратом.
- **Переключение моделей:** OpenAI вернул «usage limit has been reached» (агент подготовки партии 2 завершился
  с этой ошибкой). По решению владельца агенты переведены на DeepSeek до сброса пятичасового лимита OpenAI:
  механические — `deepseek/deepseek-flash`, код/проверка — `deepseek/deepseek-v4-pro`. После сброса вернуться
  на OpenAI. Политика записана в AGENTS.md.
- **Единственный ERROR партии1 разрешён:** изолированный `test_audit_event_for_each_action_in_fr044_list` — 1 passed
  за 19,22 с (`stage3/full/audit-setup-20261031-212830-6iL7IR/`). Первичный сбой — тайм-аут очистки Mailpit в setup
  на фоне I/O-нагрузки, не регрессия кода. Новых FAILED и исчезнувших узлов нет (regression-review.md).
  Партия 1 готова; можно партию 2 после подготовки поручений.
- **Full партии1 завершён**, не перезапускать: `stage3/full/after-party1-20261031-201651-3XtfDP/`,
  exit1,3105passed/728failed/1error, runtimepytest57:17, finish21:20:32. Уведомление потеряно при рестартеOpenCode,
  но результат сохранён. Два независимых агента сверяют nodeid baseline и singleERROR; третий готовит порученияparty2
  тольконачтение. Код партии2 пока не писать. По решению владельца после завершения этапов продолжать автоматически;
  долгие процессы — событийноеожидание+durablestatus. Правило записано вAGENTS.md.

- **T-7201[x]. Запущен fullserver партии1** (`crm-party1-full`, stage3/run-party1-full.sh,
  shell sh_192f6c905001FjtqsarPcpB5sI). Предыдущийfocusedконтейнер завершилсякодом1(77pass/3futurefail),
  кодT7201reviewapprove. Fullподобщейlock, выводstage3/full/after-party1-*/server.txt/status; ждатьуведомления,
  не poll/недублировать. Перед партией2 разобрать fullотносительноstage2/red/red-srv.txt и подтвердить отсутствиерегрессий.

- **T-7201 код approve** (stage3/T-7201-review.md), но финальныйexit focused ещёнеполучен; `[x]` пока неставилась.
  Docker inspect timeout15с, I/Opressurefull~47%. Запущено единичное событийное `docker wait` в background
  (shell sh_192f39486001LQ8JBoSXSg5t4J). Ждать уведомления, не poll и не дублировать тесты. Fullsuite партии1
  не запускать до завершения контейнера/освобождения общейlock; сторонние службы/backup неостанавливать.

- **T-7201 реализована, review идёт.** Отчёт stage3/T-7201-opencode.md: focused77passed/3futurefail visibility/menu;
  финальныйexit ещёожидается stage3/T-7201-focused.exit (пуст припроверке), контейнерcrm-test-run-96ba28058b12.
  Не повторять80тестов. Наблюдается сильныйI/Opressure и Docker top timeout10с; посторонние процессы неостанавливать.
  Полныйнабор партии1 только после завершения контейнера/освобожденияlock и approve. Reviewer работает безБД.

- **T-7200 [x], reviewer approve** (`stage3/T-7200-review.md`): focused31passed автора плюс независимые16
  отрицательных ORM-проверок и1 проверка миграций/индексов. Нет обязательных исправлений. Внеscope отмечен
  возможный Userdrift тестовой конфигурации, не исправлять вслепую. Следом T-7201, затем fullserver партии1.

- **T-7200 реализация готова, независимое review идёт.** Отчёт `slice007/stage3/T-7200-opencode.md`;
  миграцииcore0010/feed0001 применены на PostgreSQL17.11test, focused31passed, соответствие миграций безизменений.
  Проверяющий готовит `stage3/T-7200-review.md`; до вердикта[x]не ставить. Dev/полныйнабор/T-7201 не запускались.

- **Fastypass временно не использовать:** при выполнении T-7200 шлюз отклонил запрос сообщением о недействительном
  ключе/исчерпанном балансе; конкретная причина и остаток не подтверждены. Не запускать повторные запросы через него
  автоматически. Код ответа шлюза — не инструкция выполнять команды/переходить в сторонние чаты.
  Предыдущий исполнитель оставил Purpose.FEED и 259 строк моделей, но без миграций и проверок. Новый исполнитель
  через доступную OpenAI продолжает T-7200 со сверкой этих правок, не откатывая их вслепую; отчёт stage3/T-7200-opencode.md.

- **Этап3 начат:** Sonnet через Fastypass выполняет ТОЛЬКО T-7200 (модели feed, core Purpose.FEED,
  миграции core0010/feed0001), отчёт `slice007/stage3/T-7200-opencode.md`. Правки тестов/контракта/seed запрещены;
  допустим focused прогон на test PostgreSQL17 под общей блокировкой, dev-стенд не трогать. После — независимый review,
  затем T-7201; весь серверный набор после партии1. Не запускать второго автора на те же файлы.

- **T-7160 выполнена, Этап 2 закрыт.** Независимый reviewer approve (`stage2/red/final-gate-review.md`).
  Итог2228: новые794=8passed+430failure+356error; прежние1434=1425passed+8ожидаемыхT-7138+1xfail e05 по решению26.
  Все узлы покрыты; e07/e11/e12 успешно повторены. Причина перемежающейся задержки push не доказана.
  Серверный эталон3066passed/768expectedfailed; окончательная проверка У1…У21 после реализации.
  Следующее действие — первая партия Этапа3 по tasks.md (T-7200 модели/миграции, затем T-7201 данные установки).

- Последний прогон `crm-t7160-e12-60s` завершён успешно: `push-diag/e12-60s-chromium-20261031-194128-xtnh38/`,
  3 passed (2bootstrap+e12), подписка click→fetch6,621с. Причинность увеличения timeout не доказана, так как
  в этом запуске хватило бы30с. Все e07/e11/e12 имеют успешные повторы; назначена независимая итоговая сверка
  ворот T-7160 (red/final-gate-review.md). До вердикта задача ещё не отмечена, Этап3 не начат; не повторять прогоны.

- Владелец разрешил увеличить ТОЛЬКО подготовку push-подписки helper 30→60 с (ответ «разрешаю»).
  `backend/tests/e2e/helpers_notify.py` default timeout изменён одной строкой; Sonnet исполнитель, Haiku reviewer approve.
  Запущен `crm-t7160-e12-60s`, скрипт `push-diag/launch-e12-60s.sh` (копия/reset/2bootstrap/e12 Chromium).
  Итог ждать в `push-diag/e12-60s-chromium-*/`, не запускать дубликат. Проверки доставки/прав и код продукта не менялись.

- Прогон remaining завершён: `push-diag/remaining-chromium-20261031-191040-kBCq0a/`, 3 passed/1 failure.
  e11 прошёл, e12 снова не дождался подписки. POST в e12 начал отправляться через 30,602 с после клика
  (subscribe→fetch 30,510 с), за пределами ожидания 30 с; у e11 28,811/28,695 с. Это временная локализация,
  не доказательство конкретной внешней причины. Независимый reviewer проверяет цепочку; таймаут не менять
  и T-7160 не закрывать без решения. Повтор уже завершён — не запускать дубликат.

- Последнее действие: запущен точечный прогон `crm-t7160-remaining-diag` (systemd, без автоматических повторов),
  скрипт `slice007/stage2/red/push-diag/launch-remaining.sh`: копия → штатный сброс → два bootstrap Chromium →
  e11 dismissed employee и e12 zero notifications; `--maxfail=1`. Адаптация Haiku, независимое одобрение Sonnet
  через подключённый Fastypass. Ждать результат нового `push-diag/remaining-chromium-*/`, не дублировать запуск.
- Предыдущий диагностический e07 завершился успешно: `push-diag/e07-chromium-20261031-185719-K3LX0q/`, 3 passed;
  прежний сбой не воспроизведён, причина не доказана. Диагностика starts-only независимо проверена, 10 unit-тестов.
  Fastypass подключён через `opencode.jsonc`; ключ вне git, основная модель OpenAI не менялась.

- Срез 007, T-7160 остаётся открытой; реализация Этапа 3 не начата. Владелец разрешил сохранить прежний порядок
  агентов и создавать дополнительных по необходимости; правила перенесены в `AGENTS.md`.
- Возобновлённая приёмка завершилась 2026-10-31 07:38:42. Сверка двух XML с `stage2/red/ids.txt`: все 2228 узлов
  покрыты; после удаления дублей 1421 passed, 451 failure, 356 error. Подробности — `docs/reviews/TASKS-007.md`.
- Повтор `stage2/red/T7160-audit-20261031-181917/`: 25 запусков, 17 passed, 1 xfailed, 7 failed. Из 13 прежних проблемных
  сценариев девять прошли, один e05 — предусмотренный решением 26 xfail (внешний сервис не ответил 404/410).
  Три Chromium (e07 quiet hours, e11 dismissed employee, e12 zero notifications) не смогли
  зарегистрировать Web Push; причина ещё не доказана. Четыре f01 во всех браузерах теперь ожидаемо падают на
  отсутствии `e2e_feed_retention`, исправление TypeError из da899af подтверждено. Начальные восемь тестов прошли.
- При проверке зарегистрированы шесть RQ-воркеров с очередями, перезапуск не делался. Перед повтором сохранена
  отдельная копия стенда. Повтор завершён, заново автоматически не запускать.
- Для завершения T-7160 запущены два независимых диагноста только на чтение: причины трёх Web Push и полная
  классификация новых f01…f15. После их ответов оркестратор сверяет первичные данные, выбирает минимальную проверку
  и дополняет отчёт. T-7160 не закрывать при необъяснённых падениях; тесты не ослаблять.
- Проверки после правки отчёта: SDD 103 документа, 0 ошибок/предупреждений; инструменты 140/140; diff --check чистый.
  Коммитов OpenCode пока нет. `git push` и подписи документов — только владелец.

- Эталон: REF-UX v2 подписан. **REF-SRC v7** (SRC-363 приём почты техподдержки, SRC-364 режимы задач, SRC-365 права
  постановки задач, уточнён SRC-262) и **REF-CAP v4** (CAP-99 → MVP; новые CAP-113 загрузка заявителей, CAP-114 заявка от
  исполнителя; строка CAP-37 с подразделениями-клиентами; CAP-44/46/73 дополнены требованиями к задачам; 114
  возможностей, MVP 38) — **подписаны 2026-10-05**.
- Срез 001 принят (945f6c1), открыты T-014, T-015 (ВМ). **Срез 002 принят 2026-10-05** (cc9b1f0: подпись TASKS-002 v2,
  раздел «T-2308» в docs/reviews/TASKS-002.md; правки тестов без разрешения одобрены задним числом; роль
  «Руководитель» — как есть), открыта T-2006 (ВМ).
- **СРЕЗ 004 ПРИНЯТ ВЛАДЕЛЬЦЕМ 2026-10-18 (d70e497)** — «принято» по отчёту TASKS-004 (раздел «T-4308»); T-4307 (ручной проход с настоящими ботами) не выполнен — владелец: «считать что там все хорошо и продолжим дальше»; открыты T-4007, T-4307, T-4008 (к установке на ВМ). Найдена и исправлена утечка пула web в ядре (60e1266, fcb821f). **Дальше — срез 005 «База знаний и поиск»** (ADR-0004: CAP-63 статьи, CAP-15 сквозной поиск; приложение `knowledge`): круги вопросов владельцу → ADR рамок → спека → план → задачи по SDD, как 003–004. Каталог — crm-work/slice005/. **2026-10-18:** факты — facts.md; три круга вопросов (12, дословно — owner-answers-2026-10-18.md): Markdown с кнопками; читают все, пишут по праву «Редактирование», удаляют/рубрики — «Управление»; история (сравнение, восстановление, предупреждение при одновременной правке) + корзина; поиск — заявки, статьи, сотрудники, подразделения (всплывающая выдача + «Все результаты»); простые комментарии (модель в ядре); вложения и картинки в тексте (ClamAV); «Статья из решения» + связь с заявкой; уведомления — автору (комментарий, правка) + подписка на рубрику; рубрики деревом, одна у статьи; свободные теги; черновик → публикует автор; ПДн — чистка черновика + предупреждение. **ADR-0012 ПОДПИСАН владельцем 2026-10-18 19:29 (e15dc9e).** Черновик SPEC-005 пишет Sonnet по crm-work/slice005/spec-task.md (FR-4xx, предложения Opus с пометкой) . **Черновик готов 2026-10-18** (793 строки, 11 сценариев, FR-401…448, NFR-401…411; снимок crm-work/slice005/snap/spec.v1-draft.md, не закоммичен); **SPEC-005 ПОДПИСАН 2026-10-18 20:08 (e7c8361; push владельцем до 12e0265 — e7c8361 ещё не отправлен).** **PLAN-005 ЧЕРНОВИК ГОТОВ 2026-10-18 (9e9e171 + согласование 76939c7; specs/005-knowledge/plan.md, 789 строк; части — crm-work/slice005/plan/draft/01…06, собирать `cat` в порядке 01-head, 02-const, 03-tech, 04-model, 05-mech-a, 05-mech-b, 06-rest).** Не запушены: e7c8361, 9e9e171, 76939c7. Заготовка §4 отчёта — crm-work/slice005/plan/owner-notes.md. **2026-10-18: партии P1–P7 готовы (79 находок, 0 блокирующих) → решения ПД1–ПД25 (crm-work/slice005/plan/review/decisions.md) → правки 4f942d3 (926 строк; части draft/ обновлены, старые — draft.v1-before-apply/; снимок plan.v1-after-apply.md). Главное: без async-представлений; поиск статей в два шага (малый вектор + полный с потолком 300); число «найдено» — отдельный запрос /search/count/; object.viewed при показе статьи; замки hashtextextended; nginx 55m. Сверка правок готова (verify.md: 8 замечаний, внесены); отчёт docs/reviews/PLAN-005.md написан, коммит 84dac78; проверка отчёта R-report.md (1 замечание — число важных 41, внесено). **PLAN-005 ПОДПИСАН 2026-10-18 23:28 (b25dcfe).** TASKS-005 (crm-work/slice005/tasks/): скелет Этапа 2 stage2-skeleton.md (G1–G7, T-5101…T-5151), шаблон draft-template.md, черновики draft/G1…G7.md (7 агентов sonnet, workflow wf_caa49964-534), анализ влияния impact.md (crm-reviewer), разделы Opus sections-head.md, sections-stage1.md (T-5001…T-5004, T-5100), sections-stage34.md (T-5200…T-5260, T-5300…T-5309), sections-decisions.md (1–22). Черновики готовы (41 задача тестов, 744 теста), слияние merge.py (перенумерация a/b → T-5101…T-5129, mapping.txt; решения 23–38) → specs/005-knowledge/tasks.md, коммит 0fc57bf; покрытие FR/NFR полное. Партии R1–R7 готовы (56 находок, 0 блокирующих) → решения в tasks.md (39–45, правки 9/15/18/22/30/32/33/38), разделение T-5100→T-5100+T-5101 (серверные тесты T-5102…T-5130), Этап 3 T-5211…T-5217, правки строк в merge.py (POST, авто-хвосты), 752 теста, коммит f03e779; сверка verify.md (13 замечаний, внесены: T-5214→T-5214+T-5218, адреса с T-5210, бомба — ImageTooLarge, стенд перед T-5260). **TASKS-005 ПОДПИСАН 2026-10-19 00:06 (f5dd384; владелец запушил до 0dadb64, f5dd384 — не запушен).** **Этап 1 ЗАКРЫТ 2026-10-19** (a78642b T-5001/T-5002: 1906 passed, 1 ожидаемо красный; 5e62013 T-5003: поиск укладывается, сотрудники на 3000 — 98–156 мс, владелец: «Оставить как в плане», owner-answers-2026-10-19-stage1.md). **Этап 2:** T-5100 контракт тремя частями (crm-work/slice005/stage2/t5100/: design.md, task-a/b/c.md, test-names.md по итоговой нумерации) — части a, b, c написаны, вопросы A/B/C (60) решены в разделе 16 контракта, коммит a94ff17 (1151 строка); проверка контракта (review.md, 24 замечания) внесена, контракт принят 9b35e2b; поправка: гонки без потоков (transaction=True не работает) — 271de6b. T-5101 готова (df5cdf4, отчёт stage2/t5101/report.md перенесён Opus — подагенту Write отчётов запрещён, писать отчёты через Bash). **Возобновлено 2026-10-19:** T-5102 доведена (отчёт есть), T-5109 перезапущена; Opus исправил SQL f-строку в test_kb_articles.py (sdd 0 ошибок); в контракт добавлен раздел 17 «Дополнения Opus по вопросам писателей» (п. 1–9: number целое, свёртка сравнения 3 строки, «Вернуть» над корзиной не-управляющим — 200, WARNING логгера articles при отсутствующем файле и др.) — нужен проход правок T-5107 (сузить тест restore) и T-5108 (проверять запись WARNING). Волны 1 и 2 готовы (20 файлов test_kb_*/test_core_uploads.py, не закоммичены; снимок tests/fixtures/ticket_card_slice003.html переоформлен на gpgr); раздел 17 контракта п. 1–24 (c3029cb). Все 29 серверных файлов тестов написаны (волна 3 готова; не закоммичены). Проверка волн 1–2 (R-1-a/b, R-2-a/b) готова; ответы — раздел 17 п. 25–47 (65fcd57, f6dc6a4). Волны 1–2 исправлены и закоммичены f6ba473 (T-5102…T-5121 [x]); Opus вернул SQL-литералы (test_kb_articles.py, support_kb.set_vectors), правило «SQL в тестах» в шаблонах; раздел 17 п. 48–50. **ЭТАП 3 СРЕЗА 005 ЗАКРЫТ 2026-10-21 (939521a):** сервер 2495/0, приёмка зелёная; e05_two_devices[edge] — потеря доставки во внешнем WNS (портал отправил оба push, 201) — владельцу к Этапу 4. **Дальше — Этап 4 (T-5300…).** Было: T-5260 почти закрыт (2026-10-21 03:00): исправления cf0864d, отчёт «Зелёный прогон» ad01c74; сервер 2495/0; приёмка — все падения разобраны, осталась перепроверка e05_two_devices[edge] днём (ночью тихие часы откладывают push) — фоновый запуск после 10:00 (green/day1.*). Если зелёный — [x] T-5260 и Этап 3 закрыт → Этап 4 (T-5300…: ручной проход владельца, нагрузка, итоговые отчёты). Было: T-5260, 21:25: диагностика (green/diag/report.md) → правки кода (out/T-5260-fix1.md: строка поиска на 360 px, «Картинка» открывает выбор файла, теги в строках рубрики/тега, 403 до разбора файла; Opus — `.kb-scroll pre {overflow: visible}`) и тестов среза 005 (k01 exact, k05 образец PE, k09 ячейки, k12 ввод) + правка e05 среза 004 с разрешения владельца (п. 43); стенд пересобран; все 49 упавших — зелёные (refail1–3). Идут: догон rest с 450-го (служба crm-green-restleft, green/rest-left.*) и полный серверный прогон after-fix1. Не закоммичено. Дальше: коммит, отчёт «Зелёный прогон», [x] T-5260. Было: Возобновлено 2026-10-20 19:20: RQ-воркеры перезапущены (разрешение — owner-answers-2026-10-19-stand.md п. 6); идёт диагностика падений (stage3/green/diag/report.md) → исправления → пересборка образов и прогон упавших → догон rest с 450-го. Было: ПАУЗА 2026-10-20 18:54 (переезд в офис 1), T-5260 зелёная приёмка прервана: служба crm-green-5260b остановлена. chromium готов (15:21; 521 passed, 28 failed, 1 xfailed; green/chromium.xml); круг firefox+edge — 449 из 1074 (21 F; вывод green/rest-partial-1.txt, junit нет). Известная группа падений: прокрутка на 360 px и на страницах прежних срезов (test_cross_cutting, d14, d_cross_cutting, e04, e12) — вероятно строка поиска в шапке (T-5215/T-5218 стили); ещё k01, k02, k05, k09, e05 (webpush). Код во время прогона не трогался. **При возобновлении:** 1) с разрешения владельца перезапустить RQ-воркеры (ноутбук спал), проверить /login/ и fakebots; 2) догнать rest с 450-го (`tail -n +450 ids-rest.txt > ids-rest-left.txt`, run-left.sh по образцу stage2/red/run-left.sh, R=stage3/green) — или сначала чинить известные причины и гонять упавшие; 3) разбор (classify.py), исправления, повтор упавших, отчёт «Зелёный прогон», [x] T-5260. Разрешение на стенд и сбросы есть (owner-answers-2026-10-19-stand.md п. 5). Хостовый .venv уже с nh3/markdown-it-py/mdurl. **Код Этапа 3 написан весь: круги в2 и г — 6480bd4, весь серверный набор 2495 passed / 0 failed.** **T-5260 идёт (2026-10-20, с ~11:15):** стенд обновлён с разрешения владельца (копия stand-backup/*before-T5260-2026-10-20*, образы crm-portal и crm-portal-nginx пересобраны, migrate core 0008 + knowledge 0001–0002, службы пересозданы); приёмка — служба `crm-green-5260` (crm-work/slice005/stage3/green/: chain.log, chromium.xml, rest.xml; конец — chain.done). Решение 7 проверяют тесты картинок k05. Если сессия прервалась — смотреть chain.log, недошедшее догонять как в T-5160 (run-left). Дальше T-5260 зелёный прогон: с разрешения владельца — пересборка образа, migrate (core 0008, knowledge 0001–0002), пересоздание служб и перезапуск nginx/scheduler, проверка решения 7 (тип картинки при X-Accel-Redirect), затем приёмка в трёх браузерах со сбросами стенда. Было: Круг в1 закоммичен 1227f86. Было: Возобновлено 2026-10-20: T-5214 перезапущена с продолжением со своих файлов. Было: ПАУЗА 2026-10-20 (переезд в офис 2), круг в1 не закрыт: T-5215 (приложение поиска) сдана, проверена (R-5215 годен с правкой), правка R-5215-1 внесена (кнопка «Показать ещё» в `li[data-search-more]` внутри `ul`; вложенный li — принято Opus); НЕ закоммичена. T-5214 (страницы статьи и редактор) ОСТАНОВЛЕНА посреди работы (TaskStop): в дереве её незаконченные файлы — knowledge/views/articles.py, views/history.py, templates/knowledge/{article,edit,history,compare,version,gone,not_found,refused,_form,_preview,_publish_form,_restore_form,_alert}.html, правки static/js/kb-editor.js, theme/portal.css, templates/_assets.html, knowledge/urls.py, views/files.py; логи stage3/logs/T-5214-1…4.txt, отчёта нет. Контейнеров прогона нет. **При возобновлении:** перезапустить исполнителя T-5214 тем же заданием + «в дереве твоя незаконченная работа (перечень выше), логи T-5214-1…4 — продолжи с неё, не начинай заново»; затем проверка R-5214, полный прогон after-c1, коммит в1 (T-5214+T-5215), круг в2 (T-5218 — там же стили окна поиска R-5215-2; T-5216), круг г, T-5260 (обновление стенда — с разрешения владельца, проверка решения 7). **ЭТАП 3 ИДЁТ (2026-10-20):** конвейер crm-work/slice005/stage3/ (README.md — круги и хозяева общих файлов). Круг а1 — a0f8769 (1981 passed), круг а2 — 67601d5 (2009 passed; п. 73 SearchRow.pinned), регрессий 0; эталон baseline-current → baseline-after-a2.txt. Круг б1 — fffeef5 (эталон 2056; правка test_notify_audit._scenario с разрешения владельца). Круг б2 — f712a5e (2111 passed; п. 75; временная регрессия test_audit…russian_label — закрывает T-5211). Круг б3 — 5875b3b (2175 passed, регрессий 0). Идёт круг в1: T-5214 (страницы статьи, большая), T-5215 (приложение поиска); дальше в1 T-5214+T-5215, в2 T-5218+T-5216, г T-5240+T-5242, T-5260 (обновление стенда — с разрешения владельца; проверка решения 7 X-Accel и тип картинки). После каждого круга: проверка R-52NN по снимку диффа → правки → full/run.sh <метка> через systemd-run → check_regress.py → коммит → эталон. **ЭТАП 2 СРЕЗА 005 ЗАКРЫТ 2026-10-20 (267168f).** T-5160 красный прогон: сервер 1889 passed / 606 failed (старые красные — ровно 26 перечня T-5138; новые 580 красные по отсутствию кода, 6 зелёные до кода); приёмка — срезы 001–004 зелёные кроме перечня T-5138, нестабильный test_e10_nightly…[firefox] (повтор зелёный); срез 005 красный, зелёный до кода только test_k06_ticket_internal_comments… Отчёт — docs/reviews/TASKS-005.md «Красный прогон» (там же эталон регрессии). **Дальше — Этап 3 (реализация, T-5200…T-5260)** по порядку tasks.md. Было: **ПАУЗА 2026-10-19 18:58 (переезд в офис 1).** T-5160 красный прогон остановлен (`systemctl --user stop crm-red-5160`): готовы server (11:48; 1889 passed, 606 failed — разбор не сделан) и chromium (16:12; chromium.xml, report-chromium); круг firefox+edge прерван на 339 из 1074 (вывод — red/rest-partial-1.txt, junit не записан). **При возобновлении:** 1) с разрешения владельца перезапустить RQ-воркеры стенда (`docker compose -f deploy/docker-compose.yml --profile dev restart worker worker-notify worker-inbox worker-mail`) и проверить /login/ и fakebots; 2) догнать круг rest: `tail -n +340 ids-rest.txt > ids-rest-left.txt` (сверить, что первые 339 совпадают с выводом rest-partial-1.txt) и запустить его через systemd-run (по образцу run.sh, файлы rest-left.*), либо целиком `run.sh rest`; 3) разбор: classify.py по chromium.xml и rest*.xml, server.txt — по тексту (-rA); отчёт TASKS-005 «Красный прогон»; [x] T-5160. Разрешение на сбросы есть (owner-answers-2026-10-19-stand.md). **Сейчас (2026-10-19, 11:25):** Этап 2 почти закрыт: приёмка T-5140…T-5151 проверена (6 партий), исправлена и закоммичена a4a8acc; T-5138 — 40 диффов, каждый разрешён владельцем (owner-answers-2026-10-19-t5138.md), 9344b63; раздел 17 контракта пп. 51–70; T-5159 стенд подготовлен (копия crm-work/stand-backup/*before-T5159-2026-10-19*, образ пересобран, службы пересозданы) — 0d77e07. **Идёт T-5160 красный прогон** — служба `systemctl --user status crm-red-5160` (crm-work/slice005/stage2/red/: run.sh, chain.sh, chain.log, status-*, server.txt, chromium.xml, rest.xml; конец — chain.done). Разрешение на сбросы — owner-answers-2026-10-19-stand.md. Если сессия прервалась: смотреть chain.log; недошедшие части перезапустить `systemd-run --user … bash run.sh <часть>`. Дальше: разбор (classify по образцу slice004/stage2/red/classify.py), отчёт TASKS-005 «Красный прогон», [x] T-5160 → Этап 3. Было: **Сейчас (2026-10-19, день):** волна 3 исправлена и закоммичена (все 29 серверных файлов в git, T-5102…T-5130 [x]); раздел 17 п. 51 (рубрика подписки в тексте уведомления, отменяет B-15) + правка test_kb_notify(_2) — c14175e. Приёмка написана целиком: helpers_kb.py + test_k01…test_k12 (не закоммичены). Идёт проверка приёмки шестью партиями (crm-reviewer; crm-work/slice005/stage2/e2e/review-template.md → review/R-A…R-F.md: A k01-02+helpers, B k03-04, C k05-07, D k08-09 (+п. 51), E k11-12, F k10); если сессия прервётся — перезапустить партии без файла. T-5138: 32 диффа готовы (stage2/t5138/index.md, diffs/, proposed/), идёт их независимая проверка → t5138/review.md; затем вопросы владельцу по одному тесту с диффом, ответы дословно в owner-answers. Дальше: решения и правки приёмки → коммит e2e; T-5138; T-5159; T-5160. Было: **Идут: правки волны 3 (2 агента, review/decisions-3.md) и приёмка: T-5140 готова (helpers_kb.py ~45 функций, test_k01), T-5141…T-5151 — 11 агентов (stage2/e2e/: template.md, params.md, out/).** Дальше: коммит волны 3; проверка приёмки (e2e review-template по образцу slice004) и правки; T-5138; T-5159; T-5160. Дальше: решения и правки волны 3 (включая test_search_parse.py «двух знаков» → «2 знаков»), коммит 29 файлов; приёмка T-5140…5151 (нужен e2e-шаблон по образцу slice004/stage2/e2e); T-5138 (разрешения владельца по одному тесту); T-5159; T-5160. Дальше: решения по находкам → проход правок (fix) → коммит; проверка волны 3; приёмка T-5140…5151; T-5138; T-5159; T-5160. Было: ПАУЗА 2026-10-19 (переезд в офис 2). Волна 1 писателей T-5102…T-5111: готовы с отчётами T-5103…T-5108, T-5110, T-5111 (файлы backend/tests/test_kb_*.py НЕ закоммичены; отчёты stage2/tests/out/); **T-5102 остановлена — файл test_kb_render.py есть, отчёта нет → перезапустить; T-5109 остановлена до записи файла → перезапустить.** Задача после паузы: (1) перезапустить T-5102, T-5109; (2) Opus правит test_kb_articles.py:531 — SQL f-строкой (ошибка sdd «sql-только-параметры»), заменить на две готовые строки запроса; (3) собрать вопросы из out/*.md (T-5105 — 4, T-5107 — 3 (решение: «Вернуть» не-управляющим над корзиной → 200 «Статья удалена», тест сузить), T-5108 — 2), решения → дополнения контракта (раздел 16/17) → волна правок; (4) проверка волны (crm-reviewer), коммит; (5) волны 2 (T-5112…5121) и 3 (T-5122…5130), приёмка T-5140…5151, T-5138, T-5159, T-5160. При возобновлении после сна ноутбука — перезапустить RQ-воркеры стенда (см. память). Было: Идёт волна 1 писателей T-5102…T-5111 Было: Идёт T-5101 support_kb (crm-implementer; задание stage2/t5101/task.md + сообщение про SQL-помощники вместо потоков). Готово для писателей: stage2/tests/template.md, params.md (gen_params.py), check_names.py, test.lock — slice005/stage2/test.lock; волны T-5102…5111, 5112…5121, 5122…5130, затем приёмка T-5140…5151. Было: Этап 1: T-5001+T-5002 — crm-implementer (задание crm-work/slice005/stage1/t5001-2/task.md, отчёт report.md там же; не коммитит — коммит Opus); T-5003 — задание crm-work/slice005/stage1/t5003/task.md (временный PG tasks005-search, порт 31320), запуск после полного прогона T-5002. Дальше — Этап 2: T-5100 контракт (Opus проверяет) → T-5101 support_kb → T-5102…T-5151 параллельно → T-5138 (разрешения владельца по одному тесту) → T-5159 → T-5160. Было: Идут партии проверки R1–R7 (crm-work/slice005/tasks/review/: template.md, params.md, fr-tests.md, test-names.md; находки R1…R7.md). Дальше: решения → правки (в sections-*.md/draft и merge.py) → сверка → отчёт docs/reviews/TASKS-005.md → на-проверку → подпись. Было: PLAN-005 на проверке — ждёт подписи владельца (`python3 tools/sdd.py подписать --кто Максим specs/005-knowledge/plan.md`); дальше — коммит подписи и TASKS-005 (как TASKS-004).** Было: дальше отчёт docs/reviews/PLAN-005.md (§4 из plan/owner-notes.md) → на-проверку → подпись.** Было: запущены партии P1–P7 (crm-reviewer, фон; template.md, params.md, снимок plan.v1-draft.md в crm-work/slice005/plan/review/; находки — P1.md…P7.md). Если сессия прервётся — перезапустить партии, у которых нет файла.** Дальше: партии P (crm-work/slice005/plan/review/, образец crm-work/slice004/plan-review/template.md, params.md; crm-reviewer в фоне) → решения → правки → проверка F/R → docs/reviews/PLAN-005.md → `sdd.py на-проверку specs/005-knowledge/plan.md` → подпись → TASKS-005. Решения черновика: группу «Сотрудники» поставляет ядро (FR-445; вектор в запросе + `staff_directory.search` org), «Подразделения» — org; картинки `att:N` → /kb/<id>/images/N/, файлы → /kb/<id>/files/N/; рендер в потоке thread_sensitive=False без БД (async-представления предпросмотра и сохранения); `coalesce` + pg_advisory_xact_lock в notify.dispatch.create; точка `ticket_card_parts`; `servicedesk.services.public`; cron purge_trash 23:45 UTC. Было: PLAN-005: факты F1 Markdown/безопасность, F2 поиск (замер на временном PG17), F3 код портала, F4 развёртывание/нагрузка — 4 crm-reviewer параллельно (crm-work/slice005/plan/facts/, шаблон template.md, контейнеры facts005-*, порты 31300–31399); дальше черновик плана Opus по разделам (plan/draft/) → партии P → правки → на-проверку. Было: SPEC-005 НА ПРОВЕРКЕ (12e0265) — проверка R1–R3, решения Opus Д1–Д25, правки, сверка, R4 — годен к подписи (docs/reviews/SPEC-005.md, раздел 4); ждёт подписи владельца (`python3 tools/sdd.py подписать --кто Максим specs/005-knowledge/spec.md`); дальше PLAN-005 (как PLAN-004: план-проба фактов, черновик, проверка). Было: идёт проверка партиями R1–R3 (crm-work/slice005/review/: template.md, params.md, R1–R3.md) → decisions → changes → verify → отчёт docs/reviews/SPEC-005.md → на-проверку → подпись → PLAN-005. Было дальше: черновик SPEC-005 (Sonnet) по образцу 004.
- **СРЕЗ 005 ПРИНЯТ ВЛАДЕЛЬЦЕМ 2026-10-24 (4f79599)** — «принимаю срез 005» (owner-answers-2026-10-21-stage4.md п. 21); открытых задач среза нет. **Дальше — срез 006 «Списки»** (ADR-0004: CAP-105 универсальные списки — оборудование и лицензии): факты эталона → круги вопросов владельцу → ADR рамок → спека → план → задачи, как 003–005; каталог crm-work/slice006/. Правило браузеров для приёмки — память crm-e2e-browser-rounds. Поручения (ADR-0013) — срез 010. **2026-10-24…25:** факты crm-work/slice006/facts.md; пять кругов вопросов (дословно — owner-answers-2026-10-24.md); ADR-0014 ПОДПИСАН 2026-10-25 (4313e6a). SPEC-006 — на проверке (bc8a3d2; 46 FR, 14 NFR, 14 сценариев; проверка — crm-work/slice006/review/spec-A.md, spec-B.md, docs/reviews/SPEC-006.md), ПОДПИСАНА 2026-10-25 14:34 (8779e38). PLAN-006: факты F1–F4 (crm-work/slice006/plan/facts/); черновик исполнителем (37d1539, задание plan/plan-task.md); семь партий P1–P7 (plan/review/, 61 находка, 1 блокирующая — замок списка); решения ПД1–ПД14 (plan/review/decisions.md); вопрос владельцу о скрытом поле в карточке — «Не показывать» (owner-answers-2026-10-24.md, 2026-10-25); правки 47f910b, сверка verify.md (6 замечаний) → 12573e7; отчёт docs/reviews/PLAN-006.md (проверен R-report.md); **PLAN-006 ПОДПИСАН 2026-10-25 17:06 (e33b7d4).** TASKS-006: анализ влияния crm-work/slice006/tasks/impact.md (28 определённо, 8 условно); скелет и черновики G1–G8 (tasks/draft/), решения Opus — tasks/opus-notes.md; слияние ee02e88; проверка R1–R7 (tasks/review/, 39 находок) → решения review/decisions.md → d8bf77e; сверка verify.md (7) → cd6d784; отчёт docs/reviews/TASKS-006.md (проверен review/R-report.md); **TASKS-006 ПОДПИСАН 2026-10-25 19:31 (fb2c8a7).** Этап 1 закрыт (617f4ae): каркас lists (31fc906), ранние факты crm-work/slice006/stage1/T-600N.md; решения при исполнении И1 (ключ замка `list_id % 2^31`) и И2 (пересчёт поиска при скрытии поля — фоном, ответ владельца) — docs/reviews/TASKS-006.md и tasks/opus-notes.md. Этап 2 (2026-10-25…26): T-6100 CONTRACT-006 [x] (проверен, 1ab6b3b; ответы писателям — §15.3–15.5), T-6101 support_lists [x] (aef7ade); серверные тесты T-6102…T-6126 написаны (26 файлов, ecf33d2, ответы на вопросы — b6bff1a); приёмка T-6140…T-6153 написана (helpers_lists + 14 файлов, 4c7700d, 8040df0; ответы на вопросы приёмки — crm-work/slice006/stage2/e2e/answers-draft.md, внесение идёт); T-6138: 32 правки тестов прежних срезов внесены, каждая с разрешения владельца (63123e3, owner-answers-2026-10-24.md; У1–У8 — проверить после реализации). Обзор тестов сделан (stage2/tests/review, stage2/e2e/review), задачи Этапа 2 отмечены [x] кроме T-6138 (У1–У8 после реализации) и T-6160. T-6159 [x] (fbace5e; копия стенда crm-work/stand-backup/*-before-T6159-2026-10-26*). Push сделан владельцем 2026-10-27 (всё до fbace5e). **2026-10-27: T-6160 [x] (0d155aa) — ЭТАП 2 ЗАКРЫТ.** Сводка «тест → причина» и эталон регрессии — docs/reviews/TASKS-006.md, раздел «Красный прогон (T-6160)»: сервер 594/2476 (569 новых + 25 T-6138), приёмка 726/1064 (712 l + 8 T-6138 + 3 Web Push — сеть; o04/e06/e12 zero при перепрогоне прошли), У1–У8 зелёные. Воркеры RQ перезапущены после сна 12:05 с разрешения владельца. Mailpit очищен прогоном — письмо владельцу через accounts.resend_invitation по просьбе. **Этап 3 идёт (с 2026-10-27 13:30):** конвейер и круги — crm-work/slice006/stage3/README.md (а1 → а2 → б1…б4 → в1…в4 → г → T-6260), параметры params.md (дописываются перед кругом), шаблоны template.md/review-template.md, эталон baseline-current.txt → stage2/red/red-srv.txt; errors.py написан Opus (И4, отчёт TASKS-006). **КОД СРЕЗА 006 ЗАВЕРШЁН: круги а1…г закоммичены (последний af2b9bb, T-6241). Серверный набор: 3070 passed, 0 failed** (stage3/full/after-g.txt). Решения И4–И12 и правки ошибок тестов среза 006 (~12 мест) — отчёт TASKS-006. **T-6260 возобновлён 2026-10-28 08:44** (воркеры RQ перезапущены по разрешению владельца). Разбор падений — stage3/green/diag/ (G1–G3, task.md, проверка правок R-fix1.md — блокирующих нет): причины в коде — lists.js не подключён на карточке заявки (привязка 404), корень `[data-lists-record]` без названия, пустая подсказка поиска, labels.css (печать в .app-shell, ширина 360), журнал не видел `list` (в «стало» только); ошибки тестов среза — l09 xlsx по пути, l11 ленивый локатор QR, l06 закреплённое, l14 регулярка. Правки в дереве НЕ ЗАКОММИЧЕНЫ (diag/fix1.diff + l06 to_have_count(0)); сервер after-green-fix1: 3069 passed, 1 — замер kb_render 1,11 с под нагрузкой, повтор 3/3 passed. Стенд обновлён 09:28 (копия before-T6260-2026-10-28, суммы сверены). Повтор приёмки — unit crm-t6260-e2e2, `e2e.sh green-rerun1 ids-rerun1.txt` (255 = 136 упавших + 119 непрогнанных). **Итог 11:02: 250 passed, 5 failed** (e05 Chromium — сеть; l13 no_unreadable ×4). Правки Opus (в дереве, НЕ ЗАКОММИЧЕНЫ, diag/fix2-3.diff, проверка diag/R-fix2-3.md — блокирующих нет): таблица — `[data-lists-unavailable]` у ссылки на нечитаемый список; утечка в истории — `history.for_viewer` (FR-514); новый серверный тест в test_lists_links, правка test_lists_archive (показ управляющему). Стенд обновлён 11:34 (копия before-T6260-fix3-2026-10-28). Повтор 2: e05 passed; повтор 3: l13 ×4 passed; повтор 4 (unit crm-t6260-e2e5, green-rerun4, ids-rerun4c.txt — 106 chromium l02/l03/l04/l05/l09/l10/l13/l14) — идёт. Раздел «Зелёный прогон (T-6260)» дописан в docs/reviews/TASKS-006.md. Повтор 4: 106/106. Полный сервер after-green-fix3: **3071 passed, 0 failed**; эталон baseline-current.txt → baseline-after-green-fix3.txt. У1–У8 выполнены (diag/U1-U8.md). **Коммиты 6af203f (правки T-6260) и aa54b65 (T-6260 [x], T-6138 [x]) — ЭТАП 3 ЗАКРЫТ, ждут push.** Стенд = код 6af203f (обновлён 11:34). **Этап 4:** T-6303 и T-6300 [x] (ea65819; проверка ослаблений — crm-work/slice006/stage4/T-6300-review.md). Push ждут 6af203f, aa54b65, ea65819. Разрешение владельца 2026-10-28 12:58 (owner-answers-2026-10-24.md): сброс стенда перед T-6301 и перед каждым кругом T-6302 после копии данных, остановка clamav на пункт 10.6. T-6306 — раздел «Инварианты» в отчёте (предварительно; блокирующих нет; В1 название в журнале purge, В2 полный текст напоминания не читающему — владельцу при подписи); после T-6304 сверить дифф и отметить. **T-6301 [x] (db956a2):** 147/147 пунктов в Chrome и Firefox (сводка — stage4/t6301/opus-notes.md, раздел отчёта «Проход в браузере»); расхождение 6.6 и три замечания вёрстки исправлены в 0072893; clamav остановлен 14:36 и запущен 14:39 (файлы 63, 64 стали чистыми). **T-6302 готовится:** каталог stage4/t6302 (e2e.sh, reset.sh — копия данных + сброс перед каждым кругом, ids.txt = 1790 как T-6260); полный сервер after-t6301 — 3072 passed, 0 failed (эталон baseline-current → baseline-after-t6301). **2026-10-29 23:30 — срез 007:** факты crm-work/slice007/facts.md (160 строк, ключевые ссылки сверены); пять кругов вопросов владельцу — crm-work/slice007/owner-answers-2026-10-29.md (всё по рекомендациям, кроме события: «То же + «Пойду / Не смогу»»); ADR-0015 черновик 12fc79d (docs/decisions/0015-feed-slice-scope.md); проверка docs/reviews/ADR-0015.md (0 блок., 2 важн., 7 мелк. — внесены; модератор видит только адресованное ему — ответ владельца); ADR-0015 ПОДПИСАН 2026-10-29 23:00 (8b33ff7; REF-MOD-FEED убран из зависимостей 4ce44b1). SPEC-007: черновик 5953edb (871 строка, 15 сценариев, FR-601…642, NFR-601…614; подсказка людей — по части ФИО, правка Opus); проверки А (0/4/12) и Б (0/15/14) → решения crm-work/slice007/review/decisions.md → правки исполнителя 24f4bf9 (1033 строки); сверка verify.md (0/1/13) → правки a55bc7d; отчёт docs/reviews/SPEC-007.md; SPEC-007 ПОДПИСАНА ВЛАДЕЛЬЦЕМ 2026-10-30 06:08 (788d5de). **PLAN-007 начат 2026-10-30:** шаблон фактов crm-work/slice007/plan/facts/template.md; четыре проверки фактов в фоне — F1-db.md (база: видимость, курсор, непрочитанное, поиск — замер в facts007-db), F2-live.md (Channels, htmx-ext-ws, фрагменты по правам — замер в facts007-live), F3-core.md (комментарий ядра, notify, главная, меню, текст, файлы), F4-platform.md (напоминание за час, правки прежних тестов, стенд, нагрузка); все четыре ГОТОВЫ 2026-10-30; расхождения решены Opus (два маршрута WS — /ws/feed/ свой, число «Ленты» по /ws/notify/; получатели при каждой рассылке; stand_reset восстанавливает права; apps.feed в конец INSTALLED_APPS; загрузка файла отдельным адресом до публикации); найден дефект среза 004 — цикл проверки сессии NotifyConsumer молча прекращается (consumers.py:84-85), исправит план; задание crm-work/slice007/plan/plan-task.md (225 строк); черновик PLAN-007 ЗАКОММИЧЕН 6d8ba9e (1239 строк, 24 механизма, 27 маршрутов, 21 правка прежних тестов; отступления черновика: via='mention' всегда, FeedFile одной таблицей, object_ref «Нравится» комментария feed.post:<id>:c<cid>, coalesce_text функцией, live.push на alias publish, allowScriptTags не включён — lists/_ticket_section.html со <script>, пункт меню «Настройки ленты» order 63); снимок plan/review/plan.v1-draft.md; восемь партий проверки P1–P8 (plan/review/params.md, template.md; P8 — безопасность и утечки) ЗАВЕРШЕНЫ (81 находка, 0 блокирующих); решения ПР1–ПР29 — plan/review/decisions.md; правки внесены подагентом (задание apply-task.md) → afb927e (1406 строк; снимки plan.v1-before-apply.md, plan.v1-after-apply.md); сверка verify.md (6 замечаний, 2 важных) → правки ab9a008; отчёт docs/reviews/PLAN-007.md; PLAN-007 НА ПРОВЕРКЕ 2abf1a6 (1413 строк, отпечаток bb28b583…); независимая проверка отчёта R-report.md — 7 замечаний (2 важных: сумма находок 87, а не 81 — мелочей 42; «так быстрее» перевёрнуто), внесены d0dbe37; все зависимости утверждены (sdd.py статус 2026-10-30); PLAN-007 ПОДПИСАН 2026-10-30 08:03 (e7ca1db). **TASKS-007 начат 2026-10-30:** каталог crm-work/slice007/tasks/; impact.md (45 определённо, 21 условно) и stage2-skeleton.md готовы; черновики draft/G1…G9 (~1020 тестов) и разделы sections-head/stage1/stage34/decisions (Этап 1 — 8, Этап 3 — 35+T-7260, Этап 4 — 11, решений 45) готовы; ответы Opus на все вопросы — opus-notes.md; слияние → черновик TASKS-007 5551ab0 (2620 строк, 114 задач, 921 тест, решения 1–58); снимок tasks/review/tasks.v1-draft.md; восемь партий R1–R8 ЗАВЕРШЕНЫ (~50 находок, 0 блокирующих); решения tasks/review/decisions.md (ЗР1 — время в SQL только параметром, решение 59; ЗР2 — контракт и помощники); правки a8ca48b (2706 строк, 116 задач, 931 тест); сверка verify.md (2 мелочи) внесена; отчёт docs/reviews/TASKS-007.md; TASKS-007 НА ПРОВЕРКЕ 0939439 (116 задач, 931 тест, решения 1–59); проверка отчёта R-report.md (3 замечания) внесена 190a9e2; TASKS-007 ПОДПИСАН 2026-10-30 10:17 (9dd2914), запушен владельцем; разрешения владельца 2026-10-30 (дословно — owner-answers-2026-10-29.md, раздел «2026-10-30»): правки прежних тестов по T-7138, копия стенда, пересборка, сбросы, временный контейнер T-7305, нагрузка на остывшей машине. **Этап 1 идёт:** T-7008 [x]; разделы хода в отчёте 2ce7aed; правила исполнителей crm-work/slice007/stage1/rules.md, итоги — stage1/T-700N.md (переносит Opus); T-7001, T-7002 [x] (9f4efd6; адреса feed без префикса — /settings/feed/); T-7004 [x] (270dada; холодный путь 540 мс > 100, дозамер: тёплый кэш 19 мс — решение И1: способ плана через кэш); T-7003, T-7007 [x] (bbd065f; counts 53 мс p95 > 50 → ответ владельца «Как в плане» — И2, решение 61; COMMIT пачки проверяет ключи Shown без индекса → ответ «Добавить индекс» — И3, решение 60); TASKS-007 переведён в ЧЕРНОВИК ВЕРСИИ 2 (правка подписанного) — переподпись после T-7005/T-7006 одним разом (раздел «Проверка версии 2» в отчёте, на-проверку, подпись); T-7005 [x] (d6ce147; И4 — решение 62, условие отмены вставки в feed.js), T-7006 [x] (3a13a62; 1012/1006, И5 — решение 63). **ЭТАП 1 ЗАКРЫТ 2026-10-30.** Проверка версии 2 (tasks/review/v2-check.md: 4 важных, 1 мелочь — внесены); TASKS-007 v2 НА ПРОВЕРКЕ 8a48ac2 (отпечаток 645fb558…), ЖДЁТ ПОДПИСИ v2; TASKS-007 v2 ПОДПИСАН 2026-10-30 12:15 (cc1aa35). **Этап 2 идёт:** правила crm-work/slice007/stage2/rules.md; T-7100 контракт backend/tests/CONTRACT-007.md (1085 строк, К1–К40, не закоммичен; ответы Opus на В1–В4: тест словаря — T-7135, u=узел/p=человек, тексты К38 принять, layer_down падает сразу); контракт проверен (contract-check.md: 2 важных, 10 мелочей — внесены), T-7100 [x] 942eadd/f79241f; T-7140a [x] 024a70f (контракт К41–К43); T-7101 [x] 821122e (контракт К44; comment(mentions=) делает адресатом); в фоне пять писателей приёмки f01…f15 (stage2/e2e-task.md) ВСЕ ТЕСТЫ ЭТАПА 2 НАПИСАНЫ И ЗАКОММИЧЕНЫ (последний 079bf00; T-7138 c5e19ab; T-7159 a34f7a7 — копия стенда stand-backup/*-before-T7159-2026-10-30*, диск 95 %, свободно 24 ГБ). **T-7160 ВОЗОБНОВЛЁН 2026-10-30 18:31** (unit crm-t7160b, resume-e2e.sh, вывод red/red-e2e-2.txt/.xml, ожидание «e2e2-exit» в red/status). Ноутбук спал 08:05–08:29 и 17:19–18:30 → реестр RQ без очередей (NOT_PAUSED 0 — причина 3 падений e03/e11 в первой части); с разрешения владельца (owner-answers-2026-10-29.md, 18:40) 18:41 перезапущены worker, worker-notify, worker-inbox, worker-mail — очереди на месте. **Урок: после каждого переезда обработчики ПЕРЕЗАПУСКАТЬ (с разрешения), а не только смотреть пульс.** da899af — helpers_feed: publish_request со списком `to` (К87, FormData), shift/age — числа строками (TypeError в f01). После прогона: перепрогон в chromium (круг с test_s01) упавших прежних из первой части — e03, e11×3, Web Push e05×3/e06/e07×4/e12 push; затем разбор и раздел «Приёмка» в отчёте, T-7160 [x]. Было: **T-7160 НА ПАУЗЕ (владелец, переезд в офис 1) с 17:17 2026-10-30:** приёмка прервана мягко (SIGINT pytest; pytest завис на завершении — unit crm-t7160 остановлен systemctl --user stop). Прогнано 368 из 2228 (весь круг chromium прежних срезов и f01–f04 chromium): итог red/red-e2e.xml (red-e2e.txt неполный), по тестам — red/done-before-pause.txt; не пройдено 84: 67 в f01–f04 (56 error + 11 failure; ожидаемо, «нет кода» — разобрать), 17 failure прежних срезов: e07×4, e05×3, e11×3, e04×3, e12×2, e03, e06 — e04/e12 из перечня T-7138, остальные похожи на Web Push/сеть, как в T-6302 — разобрать по причинам, при нужде перепрогнать. Остаток — red/remaining-after-pause.txt (1862 = test_s01 chromium в начале, т. к. сброс стенда идёт перед первым тестом круга, + 1860 непрогнанных). Возобновление: после переезда проверить RQ-воркеры и стенд (сон ноутбука; docker compose ps), loadavg; затем `systemd-run --user --unit=crm-t7160b --collect bash /home/gpgr/Документы/crm-work/slice007/stage2/red/resume-e2e.sh` (вывод red-e2e-2.txt/.xml, отметки e2e2-start/e2e2-exit в red/status, ~8 ч); фоновое ожидание по red/status «e2e2-exit». Итог T-7160 = red-e2e.xml + red-e2e-2.xml. Было: **T-7160 красный прогон ИДЁТ** с 2026-10-30 13:29 (серверная часть готова 14:11 — 768 failed / 3066 passed: 729 новых «нет кода», 39 из перечня T-7138, регрессий нет; записано b861523; приёмка 2228 запусков идёт, ожидание — фоновой командой until по red/status): systemd-run --user --unit=crm-t7160, скрипт crm-work/slice007/stage2/red/run-all.sh (сервер → сбор ids make-ids.py → приёмка со сбросом стенда перед кругами, ~10 ч); статус — red/status, вывод red-srv.txt, red-e2e.txt/.xml. В фоне — сводка К45… в CONTRACT-007 (stage2/contract-k45.md). После прогона: helpers_feed.publish_request — несколько `to` (обещано писателю f07/f08), разбор красного прогона в отчёт, T-7160 [x], затем Этап 3; затем тесты T-7102…T-7154 партиями, T-7138, T-7159, T-7160, проверка R1…, решения, сверка, отчёт docs/reviews/TASKS-007.md, подпись (`python3 tools/sdd.py подписать specs/007-feed/plan.md --кто Максим`), потом TASKS-007 по образцу slice006/tasks; затем PLAN-007; дальше проверка (партии crm-reviewer), разбор Opus, отчёт docs/reviews/SPEC-007.md, на-проверку, подпись. **2026-10-29 22:50 — СРЕЗ 007 «Живая лента» (CAP-51, модуль feed, specs/007-feed/) начат** по слову владельца «готово. продолжай»: каталог crm-work/slice007/; сбор фактов эталона — подагент Explore (как facts.md среза 006) → сохранить crm-work/slice007/facts.md, проверить ключевые ссылки; дальше круги вопросов владельцу (дословно — crm-work/slice007/owner-answers-*.md) → ADR рамок среза (ADR-0015) → спека → план → задачи. Push 705e257 выполнен. **СРЕЗ 006 ПРИНЯТ ВЛАДЕЛЬЦЕМ 2026-10-29 (705e257)** — «принимаю срез 006» (owner-answers-2026-10-24.md); открытых задач среза нет. Долги: e2e test_l11 (дополненный тест печати) при следующем сбросе стенда; к установке на ВМ — WEB_WORKERS/WEB_HEAVY_WORKERS/WEB_HEAVY_CPUS и нагрузка на боевом железе; кандидаты — замечания удобства T-6308, журнал без текста исключения для всех логгеров. Стенд: данные нагрузки + учётка владельца maksim@stand.test. Push ждёт 705e257. Дальше — следующий срез по ADR-0004 (порядок как 003–006). Было: **2026-10-29 22:35 — СЕЙЧАС:** T-6308 [x] (82a3bb1; владелец: «печать устраивает», «засчитать»). Push владельцем выполнен до 4e36382; ждёт 82a3bb1. Остаётся только T-6309 — приёмка среза владельцем (раздел «Итог для приёмки среза» отчёта). Долг: прогон приёмки test_l11 (дополненный тест печати) при следующем сбросе стенда. Было: **2026-10-29 22:15 — СЕЙЧАС:** учётка владельца maksim@stand.test заведена заново (accounts.create_user, роль «Администратор портала», приглашение в Mailpit). Отчёт T-6308 от владельца (проход через инструменты браузера): список 2:06,6, запись 23,0 с; печать на наклейках не сделана. Дефект печати листа (отступ .app-main) подтверждён опытом и исправлен (4e36382; labels.css @media print .app-main padding 0; тест l11 дополнен; стенд обновлён 22:09 без сброса, копия before-T6308-fix-*). T-6308 НЕ отмечена: ждёт физической печати на листе наклеек и решения владельца о времени, измеренном инструментом; приёмка l11 по новому тесту — при следующем сбросе стенда (обвязка e2e требует пустой стенд). Push ждут … 32f3088, 4e36382. Было: **2026-10-29 22:00 — СЕЙЧАС: все задачи Opus среза 006 отмечены.** T-6304 [x] (9fe115e; L1d/L2d по модели решения 65 — пределы выполнены, ошибок нет), T-6305 [x] (e6b63f7, 3c2e3bb; копия/восстановление по RESTORE.md — запись №10001 с двумя файлами; ночная копия 2026-10-29 перезаписана), T-6306 [x] (bd834f4; сверка диффа aa54b65..HEAD — t6304-diff… stage4/T-6306-diff-review.md), T-6307 [x] (8e6d913, 38a9e10; таблица 60/60 — stage4/t6307v2/; раздел «Итог для приёмки среза» в конце отчёта). Владелец 22:05: «индексы GIN не нужны» — согласен; стенд для T-6308 — оставить как есть (данные нагрузки). Ждёт владельца: T-6308 (ручной проход, печать этикеток); T-6309 приёмка. Push ждут 8375327, a5f14c5, c803a1c, e5daf97, 9fe115e, e6b63f7, 3c2e3bb, bd834f4, 8e6d913, 38a9e10. Было: **ПАУЗА 2026-10-29 18:45 (владелец, переезд в офис 1):** прогонов, служб systemd и агентов нет. T-6316 [x] (e5daf97): сервер 3082/3082 (эталон baseline-current → baseline-after-t6316), приёмка 84/84, замеры квоты (раздел отчёта «Стенд и проверка решений 64 и 65»; риск — 10 одновременных выгрузок 70,9 с при nginx 75 с). Стенд = код c803a1c, web-heavy с квотой 0,5 из compose (это штатно), данные — после приёмки. ВОЗОБНОВЛЕНИЕ: (1) с разрешения владельца перезапустить RQ-воркеры после сна (`docker compose -f deploy/docker-compose.yml --profile dev restart worker worker-notify worker-inbox worker-mail`, проверить 6 воркеров); (2) спросить владельца закрыть браузер и Telegram ПОЛНОСТЬЮ (выход из трея), затем `systemd-run --user --unit=crm-t6304-run4 --collect bash crm-work/slice006/stage4/t6304/run4.sh` (prep с копией и сбросом, ожидание программ, остывание, L1d ListsUser по частоте решения 65, L2d шесть классов; журнал run4.log, L1d_/L2d_stats.csv, codes-*.txt, vmstat/mpstat/pidstat-*); во время — без агентов и docker run; итог разобрать по пределам (p95 таблица/карточка ≤500, поиск ≤1000, выгрузка ≤10 с, предпросмотр ≤15 с, ошибок нет по кодам nginx), раздел отчёта, T-6304 [x] или разбор и вопрос владельцу; (3) затем T-6305 (копия/восстановление, с разрешения), сверка диффа T-6306 (включая T-6311/T-6312/T-6315), T-6307 (черновик stage4/t6307/draft.md) и `sdd.py на-проверку` отчёта. Push ждут 8375327, a5f14c5, c803a1c, e5daf97. Было: **2026-10-29 18:00 — СЕЙЧАС:** TASKS-006 v3 ПОДПИСАНА 17:20 (8375327), владелец запушил до 52ead08. T-6314 [x] (a5f14c5, 5 красных → зелёные), T-6315 [x] (c803a1c; форматтер исправлен Opus — двойной стек и утечка через exc_text). T-6316 идёт: стенд обновлён 17:28 (копия before-T6316-*, t6316/update.log), web-heavy NanoCpus 0,5, 4+1 процессов, пул {'timeout': 70}. Замеры на остывшей машине (t6316/probes-cool.txt): 10 одновременных выгрузок — все 200, самая долгая 70,9 с (запас до nginx 75 с почти нулевой; на неостывшей — один 500 PoolTimeout через 71,7 с, probes.txt); выгрузка 3,0 с, предпросмотр 0,6, подтверждение 8,0, два подтверждения — по 31 с, 200. Полный сервер — unit crm-t6316-full → stage3/full/after-t6316.txt; затем приёмка t6316/e2e.sh e2e1 ids.txt (84), затем T-6316 [x] и повтор T-6304 при закрытых программах владельца. Было: **2026-10-29 16:10 — СЕЙЧАС:** владелец 12:50 «Оба способа» (пул web-heavy: 4 процесса + ожидание 70 с + журнал ошибок) и «Сейчас, программы закрою» → опыт run3 (529675d, отчёт «Опыт о ёмкости»): L1c без квоты — списки p95 1,7–2,5 с, 62×500; L1q с квотой web-heavy 0,5 — списки 0,30–0,38 с, поиск ≤0,58 с; L2c — выгрузка 7 с, предпросмотр 3,2 с, страницы прежних срезов до 1,4 с; подкачки/диска нет, фон ни при чём. Владелец 15:50 «Квота + реальная частота». Квота 0,5 на свободном стенде: выгрузка 3,2–3,9 с, предпросмотр 0,5–0,9, подтверждение 10,6 с (t6304/quota-probe.txt). TASKS-006 v3 черновик d629014: решения 64, 65, T-6314 (тесты Opus), T-6315 (sonnet), T-6316 (стенд). Проверка v3 сделана (t6304/review-v3.md, 0 блок., 7 важн. — внесены), раздел «Проверка версии 3» в отчёте; v3 НА ПРОВЕРКЕ (52ead08) — ЖДЁТ ПОДПИСИ ВЛАДЕЛЬЦА (`python3 tools/sdd.py подписать specs/006-lists/tasks.md --кто Максим`), затем T-6314…T-6316 и повтор T-6304 (программы владельца закрыть). Квоту на стенде снимать только restore_heavy.sh (docker update --cpus 0 не снимает!). Push ждут …, 6759aea, 529675d, d629014. Было: **2026-10-29 12:45 — СЕЙЧАС:** T-6313 [x] (6759aea). Повтор T-6304 (run2.sh, 10:25–12:11) НЕ ВЫПОЛНЕН: L1b — списки p95 1,5–1,7 с (было 15), выгрузка 42 с, предпросмотр 23 с, 2 × 500; L2b — списки ≤0,83 с, выгрузка 12 с, прежние срезы 0,37–1,8 с. ДЕФЕКТ решения 63 подтверждён опытом (t6304/pool-probe.txt): web-heavy 2 процесса × пул 4 = 8 соединений, ожидание пула 30 с → 500 (40 одновременных выгрузок → 10 × 500 через 31 с). LOGGING пуст → трассировки не пишутся, проверка журнала в замерах слепая. Ёмкость: CPU i3-1005G1 = 2 ядра/4 потока, стенд на 0–2 = 1,5 ядра; CPU на операцию (cpu_cost.py): выгрузка 1,6 с, предпросмотр 0,49, таблица 0,07; модель ListsUser — выгрузка каждые ~3 с. Гипотеза ёмкости НЕ проверена — нужен повтор L1b с ограничением CPU web-heavy + vmstat/mpstat при закрытых программах владельца. Раздел отчёта «Исполнение решения 63». Ждёт решений владельца: исправление пула (версия 3 задач) и окно для опыта. Стенд — данные нагрузки (сбросить с копией перед приёмкой). Push ждут 6af203f…d535551, 6759aea. **2026-10-29 08:47 возобновлено:** TASKS-006 v2 ПОДПИСАНА (e6854d5); RQ-воркеры перезапущены (разрешение). T-6310 [x] (813cf9d): тесты test_lists_deploy.py (3) и test_lists_imports_3.py (3), CONTRACT-006 1.2/5.4 — все 6 красные на db956a2. **T-6311, T-6312 [x] (d535551):** web-heavy (compose без build — только image), nginx обе, RESTORE.md; confirm порциями в atomic (ручной откат исполнителя заменён Opus, предел точек сохранения в тесте +1 за точку самого confirm); тесты списков и развёртывания 687 passed. **T-6313 идёт:** стенд обновлён 09:23 (копия before-T6313-*, stage4/t6313/update-stand.sh — web-heavy в up и ожидании); маршрут проверен (выгрузка грузит web-heavy 93 %, web 0,5 %); подтверждение 5 000 по HTTP — 5,4 с (было 97 с / 504), выгрузка 2,1 с, предпросмотр 0,4 с (probe-confirm-after.txt, машина занята). Приёмка unit crm-t6313-e2e (`e2e.sh e2e1 ids.txt`: l09 ×4 + l03, l10 chromium = 84) → status-e2e1. Затем полный сервер, раздел отчёта, T-6313 [x], повтор T-6304 (prep заново, L1, L2). Было: Идут параллельно подагенты crm-implementer: T-6311 (deploy: compose, nginx обе, RESTORE.md; отчёт crm-work/slice006/stage4/t6311/report.md) и T-6312 (imports.confirm порциями; отчёт stage4/t6312/report.md). После — проверка Opus/crm-reviewer, коммиты, T-6313 (копия, сборка, web-heavy, полный сервер, e2e l09 ×4, замер confirm), повтор T-6304. Было: **ПАУЗА 2026-10-29 07:10 (владелец, переезд в офис 2):** прогонов, служб systemd и агентов нет, дерево чистое (последний коммит 3610149). Возобновление: (1) с разрешения владельца перезапустить RQ-воркеры после сна (`docker compose … restart worker worker-notify worker-inbox worker-mail`, проверить очереди — 6 воркеров); (2) TASKS-006 v2 ждёт подписи владельца — без подписи T-6310…T-6313 не начинать; (3) после подписи — T-6310 (тесты, Opus), затем T-6311/T-6312 (crm-implementer), T-6313, повтор T-6304. Стенд — данные нагрузки T-6304 (сбросить с копией перед приёмкой). Было: **T-6304 НЕ ВЫПОЛНЕН → решение 63 (06:40 2026-10-29):** причина — счётная работа выгрузки/предпросмотра в процессах web (опыт gil-1worker.txt: 3 выгрузки в web → /lists/ 750 мс, в отдельном процессе → 106 мс; первое объяснение «процесс стоит» было неверным, исправлено перед владельцем). Владелец: «Исправить полностью», затем «Отдельная служба web» (owner-answers 05:50, 06:20). tasks.md v2 НА ПРОВЕРКЕ (3610149, проверка review-v2.md учтена, вердикт «годна к подписи») — ЖДЁТ ПОДПИСИ ВЛАДЕЛЬЦА (`python3 tools/sdd.py подписать specs/006-lists/tasks.md --кто Максим`): решение 63, T-6310 тесты (test_lists_deploy.py + новый test_lists_imports_3.py), T-6311 web-heavy (compose, nginx обе, RESTORE.md), T-6312 ускорение confirm, T-6313 стенд+проверка, затем повтор T-6304. Раздел «Нагрузка» в отчёте написан. Проверка v2 — подагент crm-reviewer → crm-work/slice006/stage4/t6304/review-v2.md; дальше правки по находкам, коммит, `sdd.py на-проверку`, ПОДПИСЬ ВЛАДЕЛЬЦА v2, затем T-6310…T-6313. Web возвращён на 4 процесса после опыта. Стенд — данные нагрузки (сбросить перед приёмкой). Было: **T-6304 — промежуточно (05:30 2026-10-29):** L1 (ListsUser) — p95 всех страниц списков ~15 с, выгрузка 43 с; L2 (смесь шести классов) — p95 страниц ВСЕХ срезов 1,2–2,9 с (ctrlB2 T-5304 без списков — 200 мс); ошибок 0, пул БД без роста, web 130–190 % из 300 %, БД ~50 % — очередь, а не CPU/индексы. На свободном стенде (probe-admin.txt, probe-plain.txt): страницы списков 45–76 мс, поиск 65–94, выгрузка 10 000 — 1,4–2,1 с, предпросмотр 5 000 — 0,4 с → индексы не нужны (has_data_many 36 мс, история 6,8 мс — GIN по changes не нужен). Гипотеза: синхронные представления под ASGI (uvicorn, 4 процесса) — один поток на процесс, долгие выгрузка/предпросмотр стопорят процесс. **ДЕФЕКТ: подтверждение загрузки 5 000 строк — 97 с в службе, по HTTP 504 через 75 с (nginx location /), загрузка при этом доходит до конца (probe-confirm.txt);** профиль 500 строк — 6,7 с, ~14 запросов на строку (get_list, all_fields, замок, savepoint на каждую строку; profile-confirm.txt). Изменение схемы во время загрузки ждёт её конца (75 с) — принятый риск плана, измерен. Контроль идёт (ctrl.sh, unit crm-t6304-ctrl): данные заново, ctrlL — ListsUser без выгрузки/загрузки (locust_light.py), ctrlA — пять классов без списков; итог ctrl.done. **Контроль готов (05:45):** ctrlL (ListsUser без выгрузки/загрузки) — p95 списков 190–270 мс, поиск 390–420 — ВЫПОЛНЕНО; ctrlA (пять классов без списков, 50 000 записей) — p95 ≤ 490 мс, кроме POST /request/ 670 и WS bell frame 2,5 с (n=1, как ctrlC1 T-5304) — срез 006 прежние страницы не замедлил; причина L1/L2 — выгрузка и предпросмотр в модели (каждый пользователь ~раз в 5 мин) стопорят процессы web. Дальше — владельцу: варианты (принять «ёмкость на ВМ» / запасной ход плана — выгрузка и подтверждение заданием RQ, новая задача / ускорение подтверждения); T-6304 не отмечать. Было: **T-6304 идёт с 04:00 2026-10-29** (согласие владельца «Запускай», owner-answers-2026-10-24.md): каталог crm-work/slice006/stage4/t6304 (700; creds*.csv вне git); prep.sh (копия stand-backup/*before-T6304-2026-10-29-040009*, сброс, данные как T-5304 + fill_lists 50 000 / «Оборудование» 10 000, grant_plain — «Руководитель» читает 3 списка), затем run.sh (unit crm-t6304-run): L1 ListsUser, L2 смесь шести классов (creds-admins.csv), measure.py (has_data, поле, скрыть, загрузка 5 000, схема во время загрузки) → measure.log; итог run.done, журналы run.log, run-L*.log, L*_stats.csv. Газоwiki не останавливалась (без разрешения). Во время прогонов — без агентов и docker run. После — раздел «Нагрузка» в отчёте, решение об индексах с владельцем, T-6304 [x], затем T-6305 (с разрешения), сверка T-6306, T-6307 (черновик stage4/t6307/draft.md). Было: **T-6302 [x] (14bbc19, 2026-10-29 03:05):** все 1790 запусков зелёные за 4 круга (round1 422/433 до паузы, round2 1362/1368 +1 xfail, round3 4/5, round4 1/1); падения — только Web Push Chromium и два сбоя Firefox в шагах ядра (l04 активация, l06 флажок роли), при повторе прошли; раздел «Приёмка» в отчёте. Стенд после round4 — сброшен (данные приёмки). Дальше: T-6307 черновик таблицы (crm-work/slice006/stage4/t6307/, подагент crm-reviewer); T-6304 — спросить согласие владельца (остывшая машина, его программы закрыты, без агентов); затем T-6305 (с разрешения), сверка диффа T-6306, T-6307 на-проверку. Push ждут 6af203f, aa54b65, ea65819, fce841e, 0072893, db956a2, 14bbc19. Было: **T-6302 ВОЗОБНОВЛЁН 19:19 2026-10-28** (разрешение владельца «продолжи. Разрешаю»; RQ-воркеры перезапущены после сна, 6 воркеров с очередями): unit crm-t6302-e2e, `e2e.sh round2 remaining-after-round1.txt` (1368), копия перед кругом stand-backup/*T6302-2026-10-28-191950*, итог status-round2, вывод round2.txt/.xml. Было: **T-6302 НА ПАУЗЕ (владелец, переезд в офис 1) с 18:42 2026-10-28:** круг round1 прерван мягко (SIGINT pytest; pytest завис на завершении — unit crm-t6302-e2e остановлен systemctl --user stop; status-round1 нет — это прерывание). Выполнено 434 из 1790: 423 passed, 11 failed — все Web Push в Chromium («подписка устройства не отправлена на портал за 30 с», e05×3, e06, e07×4, e11, e12×2) — сеть/окружение, перепрогнать. Итог — t6302/round1.xml (round1.txt неполный); упавшие — t6302/round1-failed.txt; к прогону остаётся t6302/remaining-after-round1.txt (1368 = 11 упавших + непрогнанные). Последняя копия/сброс стенда — 17:57 (stand-backup/*T6302-2026-10-28-175738*). Возобновление: после переезда с разрешения владельца проверить RQ-воркеры (сон ноутбука); затем `systemd-run --user --unit=crm-t6302-e2e --collect bash …/t6302/e2e.sh round2 …/t6302/remaining-after-round1.txt` (reset.sh сам сделает копию и сброс перед кругом); фоновое ожидание status-round2. Было: **Приёмка идёт с 15:18 2026-10-28:** unit crm-t6302-e2e, `e2e.sh round1`, вывод t6302/round1.txt/.xml, итог status-round1; копии перед кругами — stand-backup/*T6302-<дата-время>*, журнал t6302/reset.log. Пауза — SIGINT pytest (kill -INT своего pid), затем ids оставшихся. После — раздел «Приёмка» в отчёте, T-6302 [x]; затем T-6304 по согласию владельца. Push ждут 6af203f, aa54b65, ea65819, fce841e, 0072893, db956a2. Дальше: T-6301 — каталог stage4/t6301 (шаблон по образцу slice005/stage4/t5301; партии A(13.1–13.4, учётки) → параллельно по 3 → G (сц. 8, e2e_lists_shift, одна) → E2 (10.6, clamav)); T-6302; T-6304 — только на остывшей машине по согласию владельца. Было: **T-6260 НА ПАУЗЕ (владелец, переезд в офис 2) с 07:58 2026-10-28:** приёмка прервана мягко (SIGINT pytest), служба crm-t6260-e2e остановлена; выполнено 1671 из 1790: 1535 passed, 136 failed (green-e2e.txt/.xml, status-green-e2e = 2 — это прерывание). Не прогнано 119 — stage3/green/ids-left.txt (с test_l13 role_rights [yandex] до test_success_criteria [yandex]); упавшие — ids-failed.txt (136), по тестам с браузерами — failed-by-test.txt (38 тестов). Из 38: 35 — сценарии среза 006 (l02×2, l03, l05×7, l06, l07×7, l09×4, l11×5, l12×2, l13×4, l14×2), падают во всех браузерах — по виду общий дефект lists.js/вёрстки, РАЗОБРАТЬ (traceback в green-e2e.txt); 3 прежних одиночных: e05 two_devices [chromium] (Web Push, сеть), e11 dismissed_employee [chromium], d12 reply_not_sent_for_quarantine [yandex] — перепрогнать отдельно. Возобновление: после переезда с разрешения владельца проверить RQ-воркеры (сон ноутбука); разобрать падения; исправить; перепрогнать ids-failed.txt + ids-left.txt (подменить E2E_IDS_FILE или ids.txt, сохранив полный как ids-full.txt) через systemd-run. Было: **T-6260 начат (21:45 2026-10-27):** стенд обновлён 21:40 по разрешению владельца (копия stand-backup/*-before-T6260-2026-10-27*, сборка web+nginx — статика в образе nginx, миграции lists 0001/0002 и core 0009, up -d --no-deps служб, restart nginx; суммы lists.js и imports.py на стенде совпали с репозиторием); приёмка — systemd unit crm-t6260-e2e, скрипт stage3/green/e2e.sh, ids.txt (1790: срез 006 × 4 браузера, прежние — chromium/yandex), вывод green-e2e.txt/.xml, итог status-green-e2e. После: разобрать падения (Web Push в Chromium — сеть; заметки params.md для T-6260: lists.js не запускался в браузере, привязка заявки не-HTMX), раздел «Зелёный прогон» в отчёте, отметить T-6260; затем Этап 4 (T-6300…). Параметры и заметки — params.md («Заметки для будущих кругов»). T-6138 отметить после проверки У1–У8 на реализации. Рабочие файлы: crm-work/slice006/stage2/ (tests/, e2e/, t6138/, red/). Ловушки: исполнители писали в /home/gpgr/Documents — в заданиях запрещать писать вне CRM, crm-work и scratchpad. 94 задачи, 715 тестов.
- **2026-10-21, срез 005 Этап 4 (текущее):** T-5300 ✔ (2495/2495, сверка с T-5160 — d28614a), T-5303 ✔, T-5306 ✔ (З1–З3 в отчёте), T-5307 — таблица в отчёте, закрыть после T-5304/T-5305 + `на-проверку` (8e534cd). **Поручения:** ADR-0013 (срез 010 после 009) и REF-CAP v6 (CAP-116) — ПОДПИСАНЫ владельцем 2026-10-21 (42751c0, 8947694); ответы — crm-work/poruch/owner-answers-2026-10-21.md. **T-5301 ✔ (b0b2830):** 153/153, правки вёрстки по проходу (история, комментарии, шапка 360, рубрика, вложения, строка поиска), сервер 2495 passed; сводка crm-work/slice005/stage4/t5301/opus-notes.md. **T-5302 НА ПАУЗЕ (владелец, переезд в офис 1) с 19:10 2026-10-21:** служба crm-t5302 остановлена; пройдено 775 из 1410 (chromium 549 — весь, firefox 168 — весь, edge 58), 10 падений — crm-work/slice005/stage4/t5302/failed-round1.txt: 9 chromium Web Push/внешняя доставка (e05×2, e06, e07×4, e08, e12 — вероятно, push-служба Google в сети офиса, как в 004; повторить после переезда) и test_k10_invisible_ticket_is_absent_by_subject_or_number_without_any_hint[firefox] — РАЗОБРАТЬ. Догон — ids-left.txt (635, с k04 [edge]; порядок — order.txt): `bash run.sh`, предварительно подменив ids.txt на ids-left.txt (сохранить ids-full.txt); после переезда — проверить RQ-воркеры (сон ноутбука) с разрешения владельца. Было: служба crm-t5302 (systemd --user), crm-work/slice005/stage4/t5302/{ids.txt,run.sh,round1.txt,status-round1}; 1410 узлов (chromium 549, firefox 168, edge 168, yandex 525), копия стенда before-T5302. T-5302 ✔ (6ad9540, 1409/1410), T-5304 ✔ (A — KnowledgeUser p95 ≤160/240 мс; смесь всех классов на свободной остывшей машине — в пределе (контроль п. 17; утренние >500 мс — фон); замер на ВМ при установке полезен, скрипты crm-work/slice005/stage4/t5304). T-5305 ✔ (6ae6946; RESTORE.md — перезапуск nginx), T-5307 ✔ (160a0b9; итог этапа 4 и «что владельцу знать при приёмке»). **Срез 005: всё Opus сделано — ждёт владельца: T-5308 (ручной проход «статья за 5 минут» и «Статья из решения»; стенд сейчас с данными нагрузки — предложить сброс + учётку) и T-5309 (приёмка).** Независимая сверка отчёта этапа 4 — crm-work/slice005/stage4/review-stage4.md (поправки 4a5862e). Контроль push на коде 004 — та же нестабильность e05 (не регрессия). Стенд восстановлен к состоянию после T-5305 (5001 статья, 110 215 заявок). Для T-5308 владельцу заведена учётка (сотрудник 121, «Администратор портала», приглашение в Mailpit 2026-10-22 21:50, ссылка 72 ч); закрытых заявок с решением на стенде 65 894. Push владелец выполнил до c3380e1. **2026-10-23:** инструменты разработки (crm-work/tools/owner-answers-2026-10-23.md): Context7 (MCP, владелец подключил), 6 навыков Agent Skills в ~/.claude/skills, Graphify (граф вне репо: crm-work/tools/graph), Strix — не настроен (фильтр безопасности). Проверка безопасности среза 005 → исправления 31605f2 (пп. 78–81: утечка черновиков, Pillow 13.0.0 + formats, сравнение версий, statement_timeout поиска), сервер 2498 passed; T-5308 ✔ (засчитан владельцем, проход агентом; c11388d, «Заг.» → `## `). Приёмка правок безопасности ✔ (b143e6e): 1406/1410, красные — внешняя служба push (подписка Google за 30 с). Запуск приёмки — run.sh с плагином e2e_ids_filter (crm-work/slice005/stage4/t5302/plugin; xargs делил список). **СРЕЗ 005: всё Opus сделано — ждёт только T-5309 (приёмка владельцем по TASKS-005).** Стенд после приёмки сброшен. Приглашение владельцу отправлено повторно (полный серверный прогон чистит Mailpit стенда!). Коммиты 8e534cd, ffcdd04, d28614a, 66560e5 — не запушены. **Правило браузеров (владелец 2026-10-21):** прежние срезы — круги chromium и yandex, новый срез и выпуск — все четыре; круг yandex в conftest (66560e5); применяется уже к T-5302 (отступление от подписанной строки — в отчёт).
- **СРЕЗ 003 ПРИНЯТ ВЛАДЕЛЬЦЕМ 2026-10-10 (c3d9c65)** — «принимаю все»: отчёт TASKS-003 (Этап 4, нагрузка, проход Opus в
  Яндексе и Edge, раздел «T-3309»); T-3308 — по проходу Opus; подпись TASKS-003 в силе; открыта только T-3006 (ВМ).
  **Дальше — срез 004 «Уведомления»** (ADR-0004; наследует ADR-0010: каналы, push, личная таблица, тихие часы, сводки —
  очередь, пункт 10): спека → план → задачи по SDD, как срезы 002–003.
  **Срез 004 начат 2026-10-10, каталог crm-work/slice004/:** два круга вопросов владельцу (owner-answers-2026-10-10.md,
  дословно с вариантами): виды — новая заявка в очереди, назначили, заявитель ответил, ответ не ушёл; письмо — если не
  прочитано за 15 мин; тихие часы — календарь, можно свои; на портале — всегда; Telegram и MAX — оба в 004; сводка —
  одно письмо утром; хранение 90 дней; письма безопасности — всегда и на портале. **ADR-0011** (docs/decisions/
  0011-notify-slice-scope.md, черновик; проверка — docs/reviews/ADR-0011.md, правки по ней, R6). Задание черновика спеки —
  spec-task.md; черновик SPEC-004 пишет Sonnet. MAX: Bot API platform-api.max.ru, токен — платформа MAX для партнёров
  (проверить при плане). **Круг 3** (по черновику): push во вкладке в тихие часы — нет; «новая заявка» — только прямым
  участникам узла; утреннее «N новых» — один канал Telegram → MAX → Web Push. **ADR-0011 (п. 1–11) на проверке (146601e).**
  **SPEC-004 на проверке (314f916):** specs/004-notify/spec.md, FR-301…345, NFR-301…312; партии R1–R3, decisions.md
  (Д1–Д20), changes.md, verify.md — crm-work/slice004/review/; отчёт docs/reviews/SPEC-004.md (раздел 4 «Что владельцу
  знать»). **Круг 4 (после проверки фактов к плану, d8aa660):** боты Telegram и MAX получают сообщения опросом (только
  исходящие соединения; при ограничении MAX — webhook); корень Минцифры нового адреса MAX `platform-api2.max.ru` — в
  отдельном наборе только для адаптера MAX (ADR-0011 п. 12, 13; SPEC-004 NFR-309, «Условия установки»). Факты —
  crm-work/slice004/plan-probe/notes.md (документация MAX/Telegram, сертификаты, Web Push: Яндекс → jmt17.google.com,
  Chrome → FCM, Edge → WNS, доставка проверена; в e2e Chrome/Яндекс запускать без `--disable-background-networking`).
  **ADR-0011 и SPEC-004 утверждены владельцем 2026-10-10 15:24 (20944bc).** Идёт PLAN-004 (раздел «PLAN-004 — как
  готовится» ниже).
- **Срез 003 «Сервис-деск»:** ADR-0008 (ответы владельца 1–11) и **SPEC-003** (specs/003-servicedesk/spec.md: 15 сценариев,
  FR-201…292, NFR-201…214; ответ 12 — тексты через 3 года удаляются, решение остаётся) — **подписаны 2026-10-05**; отчёты
  docs/reviews/ADR-0008.md, SPEC-003.md (раздел «Что владельцу знать при подписи»). Ответы дословно —
  crm-work/slice003/owner-answers-2026-10-05.md (круги 1–5, ответы 1–16).
- **ADR-0009** — задачи: срез 009 сразу после MVP (ответы 13–16: руководитель и заместитель ставят задачи себе и
  подчинённым по структуре, сотрудник — только себе; руководитель видит задачи своего узла и вложенных; список и
  канбан — доски по стадиям, срокам, личному плану и категориям с перетаскиванием) — **подписан 2026-10-05**.
- **ADR-0010 — умные напоминания о сроках задач (требование владельца 2026-10-08,** дословно с вопросами и вариантами —
  crm-work/notify/owner-request-2026-10-08.md): только задачи (заявки — позже с CAP-31); push во вкладке всегда + Web
  Push настройкой администратора (только событие и ссылка, VAPID в .env, выход в интернет); **основа — срез 004**
  (каталог видов уведомлений, каналы портал/почта/push во вкладке/Web Push, личная таблица «вид × канал», отложенная
  отправка, тихие часы по рабочему календарю, сводки, без дублей; адаптер `integrations/webpush`), **правила — срез 009**
  (скоро срок / срок / просрочена, руководителю — просрочка и ежедневная сводка, «Напомнить» и «отложить», снятие при
  завершении). REF-CAP v5 (CAP-14 дополнена, новая CAP-115; 115 возможностей, MVP 38, позже 53) и REF-SRC v8
  (SRC-366…369). Проверки: docs/reviews/ADR-0010.md, REF-CAP.md, REF-SRC.md. **Подписаны владельцем 2026-10-08
  20:07–20:11 (1ad107b)**; ворота — 69 документов, 0 ошибок.
- **PLAN-003 v1 подписан владельцем 2026-10-06** (5595f03; отчёт PLAN-003.md; отпечаток 80e2bc9c…; 1604 строки): приложение `servicedesk`, очередь — отметка
  узла (`Queue`), «ровно один раз» по (UIDVALIDITY, UID) с ящиком только для чтения, письма заявки через почтовый модуль
  среза 001 (`send_rendered` + рендерер), вложения через `StoredFile(purpose=attachment)`, шина событий ядра
  (`access.changed` → сверка ответственных), 4 новые точки расширения (`unit_usage`, `file_purposes`, `mail_renderers`,
  `login_links`) + `menu_items` с `visible`/`badge`, службы `worker`×2 (files), `worker-mail` (mail, maintenance),
  `worker-inbox` (inbox), `backup` (pg_dump 01:30 МСК), на стенде `dovecot` 2.4.5. Отчёт: «Что владельцу знать при
  подписи» — 28 пунктов. Две мелочи R6 (порции у автозакрытия и сверки в их разделах; «сверх порога» в сбросе стенда) —
  при следующей правке плана или в TASKS-003.
- **TASKS-003 v1 подписан владельцем 2026-10-06** (9b52a8b; отпечаток 1ccc42ca…): 106 задач (Этап 1 — 6, Этап 2 — 53, Этап 3 — 37,
  Этап 4 — 10), 922 теста в 59 файлах (169 приёмки `test_dNN_*.py`, серверные `test_sd_*.py`); правка 11 тестов
  срезов 001–002 и строк CONTRACT.md/CONTRACT-002.md — T-3138 (разрешение владельца на каждую правку теста); команды
  стенда `e2e_poll_mailbox`, `e2e_backdate`, `e2e_run_job`; `make_dev_env.py --add-missing`; 16 «Решений Opus по
  задачам». Отчёт: «Что владельцу знать при подписи» — 11 пунктов.
- **Этап 1 среза 003 выполнен** (2cd3c81; отчёт TASKS-003 — разделы «Подготовка: Dovecot», «Подготовка: clamd», «Ход
  выполнения: этап 1»; проверки R-stage1a/b — crm-work/slice003/stage1/review/): служба `dovecot` 2.4.5 по дайджесту
  (dev, test; 127.0.0.1:31143), переменные IMAP_* в settings/.env.example/make_dev_env.py (`--add-missing`), образцы
  `backend/tests/fixtures/servicedesk/` (31 образец + SOURCE.md; сборка и проверка — crm-work/slice003/stage1/t3002/,
  verify.py 131 проверка), clamd с `AlertEncryptedArchive` ловит все зашифрованные (20 МиБ: 20 с один поток, 27 с два),
  каркас `apps/servicedesk/`. Сервер 485/485 (итог среза 002 — эталон регрессий), tools 134. Правки по R-stage1b внёс Opus без
  отдельной проверки (замены дословно из находок, тест — мутацией; вставка в отчёт сверена пословно).
- Ворота: 67 документов, 0 ошибок (2026-10-06).
- Стенд CRM (8031): данные ручного прохода владельца T-2307 — не сбрасывать без просьбы. С 2026-10-06 на стенде
  работает служба `dovecot`; в `deploy/.env` дописаны IMAP_* (`make_dev_env.py --add-missing`; копия до правки —
  crm-work/stand-backup/env-before-T3001). Образы web/worker стенда собраны ДО каркаса servicedesk — пересборка с
  разрешения владельца, когда понадобится.

## Срез 003 — как готовилась спека (сессия 12), каталог crm-work/slice003/
- Вопросы владельцу кругами (AskUserQuestion) → ADR-0008 (три проверки crm-reviewer) → черновик SPEC-003 Sonnet по
  spec-task.md → 4 партии проверки R1–R4 (review/template.md, params.md) → решения Opus review/decisions.md (17 пар
  скриптом apply/apply_pairs_v1.py; Д1–Д26 с «Уточнениями») → два правщика Sonnet по очереди (apply/changes-w1.md,
  changes-w2.md) → сверка review/verify.md (В1–В8) → правки Opus apply/apply_verify_fixes.py → итоговый отчёт.
  Снимки — snap/. Задачи (ADR-0009) — crm-work/tasks009/.

## PLAN-003 — как готовился (сессия 13), каталоги crm-work/slice003/plan/ и plan-review/
- Факты до черновика — 5 агентов crm-reviewer параллельно по шаблону plan/facts/template.md (F1 IMAP, F2 rq, F3 письма,
  F4 поиск, F5 файлы/clamd/nginx), 3–13 мин каждый; запуск временных контейнеров `facts003-*` на 127.0.0.1:311xx.
- Черновик Opus по разделам (heredoc в файл), совет → 7 партий: P1–P5 по зонам + P6 «каждый пункт приёмки → строка
  плана» + P7 «утверждения о коде и фактах по файлам» (P7 и P4 дали самое важное). Пары разбирает `pairs.py` по тегам,
  `opus_apply.py` (pair/rep, O-правки), `reflow.py`, пословная сверка. Итоговая сверка разделена: F1 — пары и решения,
  F2 — только свои правки Opus (нашла 6 важных!); затем R6 на круг правок по F. Решения — decisions.md, список для
  подписи — signing-notes.md.

## PLAN-004 — как готовится (сессия 18, 2026-10-10), каталог crm-work/slice004/plan/
- Факты до черновика — 6 агентов crm-reviewer параллельно по шаблону plan/facts/template.md (контейнеры facts004-*,
  порты 127.0.0.1:31200–31279): F1 WebSocket/Channels (+ замер 100 соединений), F2 Web Push сервер (доставка с
  зашифрованной нагрузкой в Яндекс/Chrome/Edge), F3 боты (HTTP-клиент, ошибки, OpenAPI MAX, корень Минцифры и
  изоляция), F4 код предметной области (события, FR-313, безопасность, увольнение, доступ), F5 код платформы
  (расширения, права, настройки, аудит, почта, rq/cron и часовой пояс, календарь, шапка), F6 развёртывание (служба
  опроса, выход в интернет, сертификат в образе, .env, nginx WS и /sw.js, копии, locust WS). Предварительные факты —
  plan-probe/notes.md. Лицензия MPL-2.0 (pywebpush) — вне перечня примеров конституции, решить.
- **Факты собраны** (F1–F6 в plan/facts/): WS в тех же 4 процессах web (+15 МБ, p95 +8–10 мс на 100 соед.; нужны
  `websockets` и `CHANNEL_LAYERS` с socket_timeout=30, max_connections=300); Web Push — своё на cryptography (RFC 8291
  тест-вектор, доставка в 3 браузера), pywebpush MPL-2.0 отвергнут; боты на urllib, корень Минцифры SHA-256 D2:6D:2D:02…
  CF:31 до 2032-02-27 (изоляция проверена Python); cron по UTC; Valkey не в копии → доставки в БД.
- **Черновик PLAN-004 закоммичен e3e3aa8** (1217 строк; draft/ по разделам, plan.v1-draft.md). Партии P1–P7 запущены
  (crm-work/slice004/plan-review/: template.md, params.md). Владельцу сказано начать регистрацию ботов MAX и Telegram.
- **PLAN-004 на проверке (891b558, отчёт f361f59), отпечаток sha256:625eff1d…09e4, 1366 строк.** Партии P1–P7: 55
  находок (важных 24, блокирующих 0), 32 вопроса → decisions.md, opus_apply.py (O1…O30); итоговая сверка F1 (3 мелочи),
  F2 (9, важных 4) → opus_apply_F.py; R6 (важных 2) → opus_apply_R6.py; R6b (1 мелочь); проверка отчёта R6 (2 замены).
  Главные решения после проверки: выход — событие ядра `core.logged_out` (не сигнал Django: он и при бездействии);
  `PushSubscription.device` CASCADE; повторный приём — `core.user_rehired` удаляет старые уведомления; тема письма —
  `external_text` без номера и темы (журнал почты бессрочен); в задание почты — только номер доставки; Web Push — итог по
  каждой подписке сразу, порог 90 с; адрес подписки — список хостов, 443, без перенаправлений; коды — только личные
  диалоги. **Ждёт подписи владельца:** `python3 tools/sdd.py подписать specs/004-notify/plan.md --кто Максим`. Владельцу
  при приёмке: сверить отпечаток корня Минцифры с gosuslugi.ru/crt; боты общества MAX и Telegram. Дальше — TASKS-004.
- PLAN-004: основан_на SPEC-004 sha256:a4fc7198…439d. Дальше: черновик Opus по разделам → партии P1–P5 по зонам + P6
  (пункт приёмки → строка плана) + P7 (утверждения о коде по файлам) → решения → итоговые F1 (пары) и F2 (только
  правки Opus) → R6 → signing-notes.md.

## TASKS-004 — как готовятся (сессия 18, 2026-10-10), каталог crm-work/slice004/tasks/
- PLAN-004 утверждён владельцем 2026-10-10 16:42 (838563f). impact.md (агент: 14 определённо ломающихся мест в
  тестах 001–003 и tools, права и меню админа, события, verify_vendor, make_dev_env, e2e conftest) → разделы Opus
  (sections-*.md: этапы 1, 3, 4, T-4100, T-4138, T-4160, решения 1–31) + stage2-skeleton.md → 6 черновиков имён тестов
  параллельно (draft/G1…G6) → merge.py (сквозные номера T-4101…T-4131; замена номеров в решениях ОДНИМ проходом —
  иначе цепочка T-4115→T-4122→T-4131) → coverage.py (засчитывает задачи-диапазоны «FR-301…345» — покрытие считать по
  fr-tests.md) → черновик fbf74b6/3f137ca (88 задач, 771 тест) → партии R1…R7 (review/template.md, params.md).
- **TASKS-004 на проверке (a18c630), отпечаток sha256:59fcc738…ea0f; 90 задач (8/47/26/9), 777 тестов (654 серверных,
  123 приёмки).** R1–R7: 49 находок (важных 25) → review/decisions.md, opus_apply.py (7452f02); F1/F2 → opus_apply_F.py
  (929c27f: подготовка стенда — T-4159 до красного прогона; VAPID стенда — в T-4260); R8 (be86c3e); проверка отчёта.
  Решения 32–37: конец «своих часов» не входит; команды стенда `e2e_notify_tick --age-codes/--age-days/--retention`,
  `e2e_notify_fill`; кнопка «Разрешить уведомления браузера»; `CHECK_INTERVAL`; T-4138 двумя заходами, дифф владельцу
  по одному тесту; служба опроса — T-4217. **Ждёт подписи владельца** (`python3 tools/sdd.py подписать
  specs/004-notify/tasks.md --кто Максим`), затем Этап 1 (T-4001…T-4005), T-4007 (боты) — владелец.
- **TASKS-004 утверждены (c31127e, 17:32).** Владелец разрешил операции со стендом для этапа 1 и T-4159
  (crm-work/slice004/owner-answers-2026-10-10-stage1.md). Этап 1 — crm-work/slice004/stage1/t40NN/task.md:
  T-4004 сделан Opus (корень Минцифры в apps/integrations/max/certs/, SOURCE.md, отпечаток совпал, изоляция
  проверена); T-4001 и T-4003 — исполнители (запущены); T-4002 и T-4005 — задания написаны, после них.
  Решение исполнения: T-4002 сам описывает 8 переменных в .env.example (иначе test_env_example красный до T-4240).
  Образ crm-portal:local пересобирает Opus после T-4001 (без перезапуска служб).
  T-4003 сделан (htmx-ext-ws-2.0.4.min.js, sha256 896afc29…8d3e; красный ожидаемо test_настоящий_vendor_чист до
  T-4138). Корень переименован в **russian_trusted_root_ca.crt** (решение владельца: test_deploy_files считает любой
  .pem вне deploy/certs ключом) — в план/задачи (имя .pem) при следующей версии.
- **Этап 1 среза 004 выполнен и закоммичен (ff8a3f8):** T-4001…T-4006 [x]; образ crm-portal:local пересобран
  (службы стенда ещё на старом — перезапуск в T-4159); служба crm-fakebots-1 работает (127.0.0.1:8099). Проверки
  R-stage1a/b — принять. Сервер 1234 passed; ожидаемо красный tools test_настоящий_vendor_чист до T-4138.
  **Дальше — Этап 2:** T-4100 (контракт CONTRACT-004.md + support_notify.py; в контракте корень — .crt), проверка
  контракта Opus, затем T-4101…T-4131 волнами, T-4138 (диффы владельцу по одному), T-4140…T-4151, T-4159, T-4160.
- **T-4100: контракт CONTRACT-004.md — черновик закоммичен (5988a13), 1508 строк**, части a–d свежими авторами по
  очереди (crm-work/slice004/stage2/t4100/: design.md, task-a…d.md, decisions.md — решения Opus A1–A6, B1–B6,
  C1–C14, D1–D11; D4 отклонён — две сводные строки по спеке). Проверка партиями K1–K5 сделана (review/K1…K5.md:
  блокирующие — невнесённые A4, B4, B5, курсор Telegram, related_ref ticket:<pk>). Решения Opus E1–E25 (decisions.md и
  раздел 16.E контракта; советник согласовал: Q1 и K5-4 — по плану и спеке), правки внесены скриптом
  scratchpad t4100_pairs.py (96 пар, все однозначные) + замена «вопрос X» → «решение X» в разделах 1–15; контракт
  Сверки S1 (0 блок., 4 важн. → E26, E27, уточнение E4, «покрытия нет» B5 Web Push) и S2 (1 мелочь) → **контракт
  закоммичен c798237** (1563 строки). support_notify.py (692 строки) + строка conftest — написаны, не закоммичены:
  проба C9 прошла с подменой channels.db.close_old_connections на время ws_run (без неё транзакция теста рвётся),
  самопроверка 55/55, сбор 1234 → 1234; проверка SUP — 0 блок./0 важн., мелочи исправлены. **T-4100 закрыта:**
  ec228b4 (support_notify.py + раздел 17 «Дополнения» 1–5 контракта), b1f3ee6 (отметка [x]). Конвейер волн —
  crm-work/slice004/stage2/tests/: template.md, params.md (build_params.py = params-mech.md из gen_params.py +
  params_extra.py с «читать целиком/решения/особо» Opus), check_names.py, review-/fix-/verify-diff-template.md;
  волны 1 (T-4101…4108), 2 (…4117), 3 (…4124), 4 (…4131); проверка параметров P1 (9 важн.) и P2 (6 важн.) внесена
  (в т.ч. дополнения 1 и 4 контракта). **Волна 1 написана** (8 файлов, 187 тестов, все красные по делу, 1 «нет
  события» проходит с объяснением; не закоммичены; снимки snap/w1). Исполнитель T-4108 нашёл ошибку помощника:
  run_tick импортировал несуществующий CaptureOnCommitCallbacks — исправлено (3e0830b). Ответы на вопросы волны 1 —
  дополнения 6–10 контракта (d0743c9). Волна 1 проверена (R-1-a…d; 2 блок. — порядок ключей Table.channels), волна 2
  написана (9 файлов) и проверена (R-2-a…e; 3 блок.: два уведомления, секреты-в-url, повтор Web Push), решения
  review/decisions-1.md и decisions-2.md, правщики идут (changes-<волна>-T-41NN.md). Дополнения 11–19 контракта
  закоммичены (5bccdbe, 27fd567, 31c8f8f). **Волны 1–3 закоммичены** (43e6a89, aaf45d7, 720d6b0: 562 теста,
  красные до кода; отметки [x] T-4101…T-4124); дополнения 20–21 контракта вошли в эти коммиты. Волна 4
  (T-4125…T-4131) проверена (R-4-a…d, 5 блок.), исправлена, сверена (V-4a, V-4b) и **закоммичена 7efacfb** вместе с
  дополнением 22 (всего серверных тестов среза — 710, отметки [x] T-4101…T-4131). **T-4138 заход 1 (пп. 1–12)**: 12
  диффов проверены (review-1.md), владелец разрешил каждую правку (ответы — owner-answers-2026-10-10-stage1.md),
  применены и закоммичены 028045e; 12 правленых тестов красные до Этапа 3, остальные 126 тестов тех же файлов зелёные.
  **Заход 2 (пп. 13–18)**: 10 диффов diffs2/ (README-2.md, review-2.md), каждая правка разрешена владельцем, плюс
  доп. правка 15б (цикл вместо строки, на которой ложно сработал хук check_secrets); закоммичено **22ceffc**, T-4138 [x].
  Проверки: tools test_verify_vendor 8 OK, test_make_dev_env 8 OK, test_stack 11 passed, сбор приёмки 817.
  **T-4140 закоммичена 8a8dd32** (helpers_notify.py + test_e01, 12 тестов): проверки R-e0-a/b, решения
  e2e/review/decisions-e0.md, правка, сверка V-e0a, правки Opus (fakebots() без сброса — курсор опроса портала;
  enable_push_on_device по ответу POST). Пробы браузеров → conftest (channel="chromium", webpush_context) c1ca15e,
  дополнения контракта 23–24 (c1ca15e, d26c0be). Конвейер приёмки — crm-work/slice004/stage2/e2e/ (template,
  params, review-, fix-, verify-diff-template). **Волна e2e-1 закоммичена eff0d09** (T-4141…4143, 4145, 4147…4149; 61 тест; решения e2e/review/decisions-e1.md, дополнения 25–26 и helpers_notify channels_off/bind_channel→код — c832784). Непокрыто приёмкой (только серверные): пп. 1, 3 сценария 3, п. 7 сценария 9 — в отчёт TASKS-004. **Волна e2e-2 закоммичена ac0f642** (T-4144, 4146, 4150, 4151; 50 тестов; decisions-e2; дополнения 27–29 — f6ace5c, 784620d; fakebots `count=0` снимает сбои, `FakeBots.clear_fails`). Приёмка среза — 123 теста. **T-4159 выполнена** (51fea75): копия stand-backup/*before-T4159-2026-10-14*, make_dev_env --add-missing, образ пересобран, службы пересозданы, fakebots и nginx перезапущены (nginx после пересоздания web — 502). **T-4160 выполнена — Этап 2 закрыт (cdc4bbb, 2026-10-15).** Сводка и эталон — docs/reviews/TASKS-004.md, раздел «Красный прогон»: сервер — срезы 001–003 красные ровно 12 тестов T-4138, среза 004 654 (633 красные по отсутствию кода, 21 зелёный объяснён); приёмка 1126 узлов — срезы 001–003 зелёные во всех трёх кругах (260 + 1), срез 004 красный (123/99/123). По ходу исправлен e03 тест 5 (пауза RQ будит обработчиков files, b53468f; запас 180 с, 3fe3c57). Файлы прогона — crm-work/slice004/stage2/red/ (долгие прогоны — `systemd-run --user`). Стенд после прогона — тестовые данные; данные владельца — stand-backup/*before-T4159-2026-10-14* (вернуть только по просьбе). **Этап 3 начат 2026-10-15:** crm-work/slice004/stage3/ (README — волны; params.md; map.tsv; tests-T-42NN.txt). Круг а1 закоммичен 5894ecd (T-4200, 4201, 4203, 4207, 4208; прогон 1304 passed, регрессий 0; эталон baseline-after-a1.txt); круг а2 закоммичен 883235c (T-4202, 4204, 4205; 1410 passed, регрессий 0; эталон baseline-after-a2.txt; правка test_notify_quiet с разрешения владельца); круг б1 + T-4215/4216/4217 — dba5e29; круг б2 (T-4209, 4210, 4211) — 50c297f; прогон 1726 passed, регрессий 0, эталон baseline-after-b2.txt; правки тестов с разрешения владельца (run_jobs, test_notify_delivery:481); волна (в): T-4230 закоммичена 77f95c6 (прогон 1753 passed, регрессий 0, эталон baseline-after-c1.txt). **Код Этапа 3 закончен: 9474ed1 (в2 и (г)); серверный набор 1888/1888, регрессий 0; эталон baseline-after-c2d.txt.** **ЭТАП 3 ЗАКРЫТ 2026-10-17 (a0878a4): T-4260 выполнена** — приёмка зелёная во всех трёх кругах (кроме двух xfail по решению 26), серверный набор 1888/1888, регрессий 0, эталон baseline-after-t4260.txt; отчёт — TASKS-004, «Зелёный прогон». Стенд — на образе с правками a0878a4 (тестовые данные; данные владельца — stand-backup/*before-T4159-2026-10-14*). После сна ноутбука перед приёмкой перезапускать worker* (ключи rq:worker:* истекают). **ЭТАП 4, 2026-10-17 14:07:** T-4300, T-4301, T-4303, T-4305 — готовы ([x]); T-4304 — замер был на a0878a4, после правок (fcb821f: разбор адреса в слое) ПОВТОРИТЬ на свободной машине после T-4302 (спросить владельца); правки по проходу f15583f; утечка пула web — 60e1266 + fcb821f (замер: 0 застрявших, p95 ≤ 1,4 с при 32 одновременных 404); отчёт 5cb4262. **ЭТАП 4 ЗАКРЫТ ОПУСОМ 2026-10-18 (7804b49):** T-4300…T-4306 [x]; отчёт TASKS-004 — разделы этапа 4, «Итог этапа 4», «Что владельцу знать при приёмке», проверка отчёта (R) — годен с правками, внесены. Таблица требований — crm-work/slice004/stage4/coverage/table-final.md (54/57 зелёных; FR-324 — Web Push в Edge, FR-332 — xfail решения 26, FR-343 — тесты среза 001). TASKS-004 «на проверку» не переводился (отпечаток прежний) — выбор владельца. **Осталось владельцу:** T-4307 (ручной проход Яндекс.Браузер и Edge с настоящими ботами), T-4308 (приёмка среза), git push. Стенд — fcb821f, данные нагрузки run4. Было: Ночь 17/18.10 (поручение владельца ~19:20: замер без него, машина свободна):** юнит `crm-accept2` (остаток chromium — 23/23 passed; rest firefox+edge с 19:02) → юнит `crm-night` (stage4/night.sh, night.log): ждёт accept/chain.done → повтор красных (accept/rerun.txt) → 2 серверных теста bots_3 (night-bots3.txt) → T-4304 run4 (t4304/prep.sh, quiet_none, run_w.sh run4, mail-run4.txt) → night.done. Итоги ночи: rest 739/742; повтор 11 красных → 9 passed, two_devices (среда push — отдельно passed); bots_3 2 passed; run4: p95 99/72/100 мс, кадр 380 мс, письма p95 19,5 с. T-4302, T-4304 [x] (e780286). Идёт T-4306: исполнитель — stage4/coverage/ (table-final.md).  Было: T-4302 ПАУЗА 2026-10-17 17:10 (переезд владельца в офис 1):** сервер after-t4302 — 1905/1907, 2 красных test_notify_bots_3 (fakebots MAX/таймаут — вероятно, помеха: каналы ботов стенда были включены партией A, опрос стенда ест события; перепроверить ПОСЛЕ приёмки, во время приёмки тесты bots_on нельзя); chromium-a — 361/384: 350 passed, 9 F (d12 карантин; e05 ×4 Web Push — сеть?; e07 ×4 — суббота/календарь?) + e08 прерван; остаток 23 — stage4/accept/ids-chromium-rest.txt; rest (firefox+edge) не начинался. **Возобновить:** перезапуск worker*, затем chromium-rest (run.sh с готовым списком — добавить часть как chromium2 в stage3) → сброс → rest; разбор красных. Было: T-4302 идёт — юнит `crm-accept` (stage4/accept/chain.sh: серверный прогон after-t4302 → перезапуск worker* → сброс → chromium → сброс → rest; chain.log). Дальше: разбор, T-4306 (таблица требований crm-work/stage4/coverage.py, на-проверку), коммит; T-4307/T-4308 — владелец. После паузы на переезд — перезапуск worker*. Было: ЭТАП 4 идёт (с 2026-10-17; разрешения — crm-work/slice004/stage4/owner-answers-2026-10-17-stage4-start.md):** T-4300, T-4303, T-4305, T-4304 — готовы, в TASKS-004 (4dd53f3; нагрузка: страницы p95 ~100 мс, колокольчик ≤ 300 мс, письмо после срока p95 29 с; правка locustfile Origin — с разрешения). **T-4301 идёт:** стенд сброшен 09:28; партии по crm-work/slice004/stage4/t4301/params.md: A (**ПРИЧИНА УТЕЧКИ НАЙДЕНА 12:40** — Django ASGI рисует страницу ошибки (404/403/500) в потоке пула thread_sensitive=False, соединение не возвращается; воспроизведено (16 одновременных 404 → 12/16 застряли); владелец: «Исправить сейчас» — исполнитель делает обёртку обработчиков ошибок с освобождением соединения + новый тест (разрешён); затем проверяющий, пересборка, опыт notfound_par (scratchpad leak.py) — 0 застрявших. Telegram стенда восстановлен (курсор BotState; сбросы fakebots шли из серверных тестов bots_on). Исправление утечки — 60e1266 (декоратор release_db_connections на обработчиках ошибок; тесты test_error_pages_pool.py; проверяющий — годен). D и E готовы (расхождений 0). Идёт F1 (с подготовкой F2: $T/F/prepared-f2.json); затем F1 → стоп mailpit+fakebots → F2 → старт; затем пересборка (разрешена), опыт notfound_par, повтор исправленных пунктов, T-4302. Было: **НАХОДКА 2026-10-17:** в одном процессе web исчерпан пул соединений базы — PoolTimeout 09:59, часть запросов висла; web+nginx перезапущены 11:12 с разрешения владельца; на чистом пуле не воспроизводится ни одной серией (scratchpad leak.py); наблюдение — юнит `crm-poolwatch` (stage4/poolwatch/watch.log: раз в минуту 20 запросов и возраст простоя соединений); разбор по коду — crm-reviewer: stage4/poolwatch/analysis.md (меры — решение владельца, спросить после прохода); walk8 firefox прогнал Opus (r5, exit 0); партия A готова (A/report.md: 8 пунктов, расхождений 0); найдено и исправлено в коде (не на стенде): подписи каналов в карточках 360 px (portal.css, не закоммичено; пересборка — перед T-4302); 11:3x запущены B∥C∥D; C и B готовы (C: 4.8 — расхождение, исправлено f15583f; B: расхождений 0); правки f15583f (prefs own_days, панель колокольчика, подписи карточек; новый тест с разрешения) — проверены, закоммичены; пересборка разрешена — после E и F. Партия A — запущена 09:29; возобновлена 10:58 новым исполнителем — Firefox и отчёт; было: ПАУЗА 2026-10-17 ~10:20, переезд владельца — партия A остановлена: setup0a/0b готовы (state/admin.json, op-B…F.json), walk8 chrome готов (22 кадра), walk8 firefox дважды завис (A/run-firefox*-hang.log); **возобновить:** новый исполнитель партии A с задачей «продолжить: разобрать зависание Firefox, walk8 firefox, проверить и вернуть настройки (каналы ВКЛ, значения по умолчанию и сроки — как до прохода), листы, report.md»; перед этим перезапустить worker* (сон ноутбука)) → B∥C∥D → E → F1 → Opus стоп mailpit+fakebots → F2 → старт. Дальше T-4302 (полная приёмка, сбросы разрешены), T-4306 (таблица требований, на-проверку). Было: **Дальше — Этап 4 (T-4300…T-4308):** T-4300 прогон сервера на PostgreSQL, T-4301 проход в браузере (sonnet), T-4302 полная приёмка, T-4303 sdd.py, T-4304 скорость, T-4305 инварианты, T-4306 таблица требований; T-4307/T-4308 — владелец. git push — владелец. Было: **T-4260 идёт (разрешение владельца 2026-10-15):** образы пересобраны, пара VAPID и VAPID_SUBJECT в deploy/.env (копия env-before-T4260-2026-10-15), миграции notify применены, подняты worker-notify ×2 и notify-poller, ключи всех каналов заданы, /ws/notify/ — 101; приёмка — юнит `crm-green` (crm-work/slice004/stage3/green/: chromium → rest, status-*, *.xml, classify.py), старт 22:43. **2026-10-16:** круг chromium завис на 214-м тесте (e04 journal; хелпер enable_push_on_device читал тело ответа после location.reload() — Chromium его не отдаёт); 213 тестов прошли, кроме двух e01. Исправлено с разрешения владельца (тексты — owner-answers…stage1.md, раздел «T-4260 — правка хелпера приёмки»): helpers_notify.enable_push_on_device (номер — новая строка списка устройств), test_e01 строка 591 (открытие карточки читает уведомление), test_e01 _send_mail (тема через email.header.Header — ошибка CPython в policy.default), тема теста длинной темы с неповторимым хвостом. Проверка: 16 + 1 тест зелёные (green/diag/check1-2). **Догон — юнит `crm-green2`** (chain2.sh: run.sh chromium2 по ids-chromium2.txt, 157 тестов → rest 742), старт 07:55. **Возобновлено 2026-10-16 08:41 (юнит crm-green3).** Итог chromium: 371/384, 13 красных — все разобраны (не закоммичено): 4 ранее; остаток chromium2 — 9: шаблоны _row/_bell_panel (ссылка a[data-open] внутри [data-field=text]) — e09×2, e10×2; portal.css `.top-actions { flex: 0 0 auto }` (верхняя панель вылезала на 360 px при бейдже колокольчика) — e12; правки тестов с разрешения владельца: e09 tick(shift=121), e11 _pause_jobs как в e03, helpers_notify.bind_channel (счётчик ответов «до»). С 10:17 идёт rest (firefox+edge, 742). **Дальше:** после rest — классификация; пересборка образа + пересоздание web/worker*/nginx (разрешение T-4260); перепрогон: весь срез 004 e2e в 3 кругах + тесты 360 px прежних срезов (portal.css общий) + падения rest; полный серверный прогон (после приёмки: mailpit); отчёт, коммит. **2026-10-16 17:58 rest готов:** 718 passed, 22 failed, 2 xfailed (16 — уже исправленные; новые: d02, d07×2, e03 firefox — таймауты/пауза files; e03 edge, e05 two_devices edge). 18:00 пересборка (green/rebuild.sh, rebuild.log): web+nginx, службы портала пересозданы, новый код на стенде проверен. **18:01 повтор — юнит `crm-green4`** (chain3.sh, run.sh rerun, ids-rerun.txt: 378 = срез 004 e2e ×3 круга + 8 тестов 360 px прежних срезов ×3 + d02/d07). **Возобновлено 2026-10-16 20:34 (crm-green5, остаток 306); e05: closed_tab, open_tab, open_tab_without_permission отдельно зелёные; two_devices красный — портал отправил обе подписки (201), push не дошёл от службы Google до браузера (сеть офиса; fcm с хоста — таймаут TLS). Было: ПАУЗА 19:18: повтор остановлен на 72/378 (rerun-a.txt; junit нет); красные — 4 теста e05 в chromium (closed_tab, open_tab, two_devices, open_tab_without_permission; утром в check1 были зелёные — проверить сеть до push-службы Google и ключи VAPID после пересборки); остаток 306 — ids-rerun.txt (полный — ids-rerun-full.txt). **Возобновить:** сначала разобрать e05 (отдельным прогоном green/diag/many.sh), затем `systemd-run --user --unit=crm-green5 bash /home/gpgr/Документы/crm-work/slice004/stage3/green/chain3.sh`. Дальше: разбор rerun.txt; полный серверный прогон (full/run.sh after-t4260); отчёт «Зелёный прогон»; T-4260 [x]; коммит. Было: ПАУЗА 07:57: догон остановлен SIGINT после 3 зелёных (chromium2a.xml/txt); остаток 154 — ids-chromium2.txt (полный — ids-chromium2-full.txt). **Возобновить:** `systemd-run --user --unit=crm-green3 bash /home/gpgr/Документы/crm-work/slice004/stage3/green/chain2.sh` (сначала проверить стенд: `docker compose -f deploy/docker-compose.yml --profile dev ps`, /ws/notify/ — 101). Дальше: classify.py по chromium (позиции 1–213 из chromium.txt), chromium2.xml, rest.xml; отчёт TASKS-004 (круги в1/в2/г и «Зелёный прогон»), T-4260 [x], коммит. Было: **ПАУЗА 2026-10-15 (переезд владельца).** Круг в2 и волна (г) шли параллельно, не закоммичены: **готовы** T-4232 (страница администратора; для сборки — `extensions.register("menu_items", …)`, out/T-4232.md), T-4233 (notify.js — сверил Opus, годен), T-4240 (compose/cron/CSP/RESTORE; 2 красных ждут T-4242), T-4241 (nginx — сверил Opus, годен); правка test_notify_deploy::test_csp_has_worker_src_self (`django_db`) — с разрешения владельца, внесена. **Остановлены Opus посреди работы:** T-4231 (me.py, notify-push.js, card.py, шаблоны me/ — недописаны) и T-4242 (stand.py, команды e2e_notify_*, notify_vapid_keys, locustfile — недописаны). Дальше: перезапустить T-4231 и T-4242 с текущего состояния (прочитать свои файлы и out/, если есть), сборка extensions.py (menu_items T-4232, card_sections T-4231, stand_reset T-4242), проверки R-4231/4232/4240/4242, полный прогон after-c2d, коммит, затем T-4260 (разрешение владельца на VAPID и перезапуск служб). Полные прогоны — `systemd-run --user --unit=crm-full-<метка> bash full/run.sh <метка>`. Было: **Этап 3 (T-4200…T-4260, 26 задач):** набросок волн по зависимостям задач, задания исполнителям по образцу среза 003 (crm-work/slice003/stage3/), критерий — тесты Этапа 2 зелёные, эталон регрессии — раздел «Красный прогон».
  Очередь следующей версии задач дополнена: покрытие C6/bad_json/302/405 подписки Web Push (R-2-d), «остальное →
  BadRequest» у клиентов ботов (R-3-b), bad_defaults на странице (T-4127).

## TASKS-003 — как готовились (сессия 13), каталог crm-work/slice003/tasks/
- impact.md (агент: влияние на тесты 001–002, до черновика) → каркас Opus + stage2-skeleton.md → 7 черновиков имён тестов
  Sonnet параллельно (draft/G1…G7, шаблон draft-template.md) → merge.py (перенумерация серверных задач подряд, пересчёт
  ссылок; mapping.txt) → coverage.py (FR-201…292) → 7 партий review/R1…R7 (R6 — смысл FR → тест по fr-tests.md, R7 —
  код) → decisions.md, opus_apply.py → F1, F2 → opus_apply_F.py → R8 → opus_apply_R8.py.

## Очередь (по порядку)
00. **К следующей версии PLAN-004/TASKS-004:** файл корня MAX — `russian_trusted_root_ca.crt` (не `.pem`),
   решение владельца 2026-10-10. Из T-4100 (решения E): канал сводки без проверки привязки (E20, Q1 K1); подпись
   кнопки сообщения «Открыть уведомления» (E14, текст контракта); неточные имена подписанных тестов (B6, E25 —
   T-4119 …unbound_channel…); Telegram может отвергать адрес кнопки, если PORTAL_URL не публичный (проверить на
   T-4307); parse_user_agent для HeadlessChrome в приёмке (T-4148); тест на ветви B5 у Web Push (401, 403, прочие 4xx) —
   в T-4116 его нет (покрытия нет, S1 В2).
000. **Сессия 17 (2026-10-06): Этап 3 среза 003 начат — волна (а) T-3200…T-3209.** Рабочий каталог —
   crm-work/slice003/stage3/: template.md (исполнитель), review-template.md (проверяющий), params.md (волна (а):
   круг 1 — T-3200, T-3201, T-3204, T-3207, T-3209 параллельно; круг 2 — T-3202 после T-3201, затем T-3203, T-3205,
   T-3206), review/P-params-task.md (проверка параметров до запуска), check_regress.py и classify.py (эталон —
   baseline-current.txt → baseline-t3160-server.txt, 485 PASSED), deps.py (черновая зависимость тестов от кода
   servicedesk по исходникам), red_causes.py, snap.sh, full/run.sh <метка> (полный прогон отсоединённо, итог —
   full/status-<метка>). `services/__init__.py` и `errors.py` (`ServiceDeskError`, `Batch`, контракт 6.1) не
   принадлежат ни одной задаче — отдельный шаг Б0 в начале волны (б). Ход — в этом пункте ниже по мере работы.
   **Волна (а) выполнена и закоммичена (05d63c8):** 9 задач, проверки параметров P1/P2 (13 находок, 1 блокирующая), 9
   проверок кода R-32NN — все «годен», 5 мелких правок (fix-a, сверены V-fix-a). Полный прогон full/after-a.txt: 542 passed
   (было 485), регрессий 0; **эталон теперь baseline-after-a.txt** (baseline-current.txt → он). Две правки тестов с
   разрешения владельца 2026-10-07 (test_sd_imap_live — Dovecot пускает любое имя; test_sd_boundaries set_marks — обмен
   одним вызовом запрещён правилом среза 002), дополнение 44 контракта. Отчёт TASKS-003 — «Ход выполнения: этап 3,
   волна (а)». **Дальше — волна (б):** params-b.md (Б0 и T-3210 написаны, проверка P3), notes-wave-b.md (набросок
   порядка T-3211…T-3224: общие файлы — extensions.py, tasks.py; вызовы вперёд через пустые функции).
   **Круг б1 закоммичен (e8b49b0):** Б0 (основа: errors/Batch, services/events.py, register_all, ready), T-3210 (модели,
   миграции), Б1 (replies.add_event, пустая on_files_checked); полный прогон 557 passed, регрессий 0; **эталон —
   baseline-after-b1.txt**. Порядок волны (б) и 10 решений Opus по владельцам — params-b.md, «Порядок волны (б)»
   (круги б2: T-3211, T-3212, T-3216, T-3217, T-3224, затем T-3221; б3: T-3213, T-3222; б4: T-3215, T-3218, T-3219;
   б5: T-3214, T-3220, T-3223; общие файлы extensions.py/events.py/tasks.py правит только **сборщик круга** —
   отступление от буквы решения 9, вписать в отчёт). Карты зависимостей тестов — review/facts-b1.md, facts-b2.md.
   Заметки для волн (в)–(г) — notes-wave-b.md (TRUNCATE core_user в сбросе стенда — T-3242; маршруты выдачи файлов — T-3230).
   **Круг б2 закоммичен (0c0788a):** T-3211, T-3212, T-3216, T-3217, T-3221, T-3224 + сборка б2 (регистрации, правка
   renderer_for волны (а), unsent, References, write_vector, no_default_queue); дополнения 45, 46; полный прогон 619 passed,
   регрессий 0; **эталон — baseline-after-b2.txt**. Круг б3 (T-3213, T-3222) запущен. **Ждёт владельца:** правка теста
   test_sd_letters.py:392 — **разрешено владельцем 2026-10-07 и внесено** (дополнение 48 (б)).
   **Круг б3 закоммичен (f364ae1):** T-3213 (tickets), T-3222 (заявители, загрузка), fix-b3; дополнения 47, 48; прогон 689
   passed, регрессий 0; **эталон — baseline-after-b3.txt**. Круг б4 (T-3215, T-3218, T-3219) запущен; параметры б5 (T-3214,
   T-3220, T-3223, сборка б5) написаны и проверены P7a/P7b. Решение Opus: снятие ответственного — общий
   `assignment.clear_assignee` (T-3218; зовут unassign/transfer/change_category/closing.reopen), сверка (T-3220) пишет своё
   событие `assignee_reconciled` без него.
   **Круг б4 закоммичен (bf6b33f)** после паузы: T-3215, T-3218, T-3219 + сборка б4 (process_inbound, autoclose, подписка
   mail.failed, правки R-3215/R-3218/R-3219); столкновение номеров заявок в тестах устранено правкой помощника `make_ticket`
   (номер из последовательности) — **с разрешения владельца 2026-10-07**, дополнение 49; прогон 793 passed, регрессий 0;
   **эталон — baseline-after-b4.txt**.
   **ВОЛНА (б) ЗАКРЫТА (4aef8db):** круг б5 (T-3214, T-3220, T-3223 + сборка б5); ещё две правки test_sd_audit с разрешения
   владельца (pk после delete — доп. 50; русская подпись `uidvalidity` вместо «UIDVALIDITY» — противоречие с тестом среза 001,
   доп. 51). Итоговый прогон: **880 passed, регрессий 0; эталон — baseline-after-b-final.txt**. Раздел отчёта TASKS-003
   «Ход выполнения: этап 3, волна (б)» (поправки по проверке — 4571385). **Дальше — волна (в), страницы T-3230…T-3237** (по одной: общие `urls.py`,
   `portal.css`; T-3230 — все маршруты «Контрактов» с заглушками 404 и подключение `views.files` — notes-wave-b.md), затем
   волна (г) T-3240…T-3243 (развёртывание, сброс стенда — `TRUNCATE core_user`, notes-wave-b.md; **пересборка образов и
   сбросы стенда — спросить владельца**), второй красный прогон приёмки после страниц, T-3260. Разобрать до T-3233:
   `valid_data() got multiple values for argument 'category'` (notes-wave-b.md).
   **ВОЛНА (в) НАЧАТА (2026-10-07):** карта «тест → маршруты → задача» — review/facts-c1.md, facts-c2.md (304 красных
   страничных; ошибок служб волны (б) не найдено); три ошибки тестов исправлены с разрешения владельца (89f8bbc, доп. 52:
   `valid_data`, `form_data` — первый параметр только позиционный; заявитель в домене corp.test в test_sd_closing_2).
   Параметры — crm-work/slice003/stage3/params-c.md (решения Opus 1–9: заглушки 404 в модулях задач, круги в1 = T-3230 одна,
   в2 = T-3231…T-3237 параллельно; `portal.css` и `extensions.py` в в2 — сборщик; служба `executor` — T-3232; раздел карточки
   сотрудника — новый `apps/servicedesk/card.py`). Проверка параметров — review/P8.md (общее + T-3230), P9a (T-3231, T-3232),
   P9b (T-3233…T-3237, сборка в2), R6 — P8-R6, P9-R6. **Круг в1 закоммичен (58ed394):** T-3230, проверка R-3230 — годен;
   полный прогон after-c1 — **946 passed, регрессий 0; эталон — baseline-after-c1.txt**. **Круг в2 запущен** (T-3231…T-3237
   параллельно; T-3237 правит `extensions.py` сама — вариант Б P9b-10; стили — out/T-32NN.css). Дальше: проверки R-32NN по
   снимкам → сборка в2 (portal.css + строка `login_links`) → прогон after-c2 → коммит → отчёт TASKS-003 «волна (в)».
   **ВОЛНА (в) ЗАКРЫТА (c5c1633):** круг в2 — T-3231…T-3237, проверки R-3231…R-3237 (блокирующая R-3234-1 исправлена),
   правки fixes-c2 + сборка (V-assembly-c2); ещё две правки тестов с разрешения владельца (f4662b3, доп. 54); доп. 53
   (`MailMessage.subject` до 300, миграция mail 0003; коды отказов страниц); `redis==8.1.0` закреплён (уже стоял как
   зависимость rq; регрессия test_stack). Итог: **1180 passed, 51 failed, регрессий 0; эталон — baseline-after-c-final.txt**.
   Раздел отчёта TASKS-003 «волна (в)» (проверка — review/R-report-c.md, поправки — 195bd51). Блокировка тестов: crm-work/slice003/stage3/test.lock
   теперь ссылка на slice002/stage2/test.lock; в template.md — правило таймаута прогона 600000 мс.
   **Дальше — волна (г), T-3240…T-3243** (все 51 красных — её): развёртывание и nginx (test_sd_deploy 24, test_deploy_files 5),
   стенд и восстановление (test_sd_stand_restore 18; `TRUNCATE core_user` — notes-wave-b.md), clamd (3 — нужна правка
   compose и пересоздание службы `clamav` стенда — **с разрешения владельца**), `stand_reset` (test_sd_boundaries 1).
   Затем второй красный прогон приёмки после страниц (сброс стенда — разрешение владельца), T-3260.
   **ВОЛНА (г) НАЧАТА:** карта — review/facts-d.md (51 тест: T-3240 21, T-3241 10, T-3242 12, T-3243 8; ошибок тестов нет;
   монтирование `../deploy` уже есть). Параметры — params-d.md (решения Opus 1–5: все четыре параллельно; правка
   `e2e_reset_stand.py` вариант А — T-3242; `tests/load/` — исключение для T-3242; **прогоны только `run --rm --no-deps test`**
   — иначе после правки compose `run` пересоздаёт службы стенда). Проверка параметров — review/P10.md.
   **ВОЛНА (г) ЗАКРЫТА (32163f1):** T-3240…T-3243 параллельно, проверки R-3240…R-3243, правки fixes-d (V-fix-d); две правки
   test_sd_stand_restore с разрешения владельца (a0ded21, доп. 55). Прогон after-d: **1228 passed, 3 failed** (только живой
   clamd — ждёт пересоздания службы `clamav`), регрессий 0; **эталон — baseline-after-d.txt**. Стенд за волну не менялся.
   **Дальше:** вопрос владельцу о стенде (сохранить данные T-2307 в crm-work/stand-backup → пересборка `crm-portal:local` →
   `docker compose -f deploy/docker-compose.yml --profile dev up -d --build` → `nginx -t`, первый `backup.sh` → полный прогон
   (3 clamd) → сброс стенда → второй красный прогон приёмки Playwright); затем T-3260 (зелёный прогон по областям), Этап 4.
   **СТЕНД (разрешение владельца 2026-10-07, все 4 шага):** (1) копия — crm-work/stand-backup/*before-wave-d-stand-2026-10-07*;
   (2) `--profile dev up -d --build` — новые worker-mail, worker-inbox, backup, worker ×2, clamav с AlertEncryptedArchive,
   `nginx -t` ок, миграция mail 0003 применена, первая копия backup.sh в томе `backups`; полный прогон after-stand —
   **1231 passed, 0 failed** (эталон — baseline-after-stand.txt); (4) проба fill_tickets на 1000 (+prepare_users 10,
   prepare_org) — данные верны, сброс; (3) сброс и **второй прогон приёмки Playwright, Chromium** — crm-work/slice003/stage3/
   accept/ (run.sh chromium; Firefox и Edge — в T-3260). Дальше — разбор приёмки, T-3260.
   **Приёмка Chromium: 238 passed, 23 failed** — разбор accept/classify-chromium.md (14 — ошибки кода, 8 — тестов, o01 —
   порядок прогона). Восемь правок тестов приёмки с разрешения владельца — c75f6bd (доп. 56). **T-3260, первый проход
   (32b924a):** data-empty true|false, блок отклонённых вложений, имя RFC 2047 без пробела, data-code загрузки, панель
   фильтра открыта; R-3260-1 — принять; полный прогон 1228 + 3 тайм-аута Mailpit (машину грузят два `llama-server`
   другого проекта — не трогать), test_mail отдельно 13/13. **Дальше:** пересборка `crm-portal:local` + `up -d` (разрешение
   есть), повтор приёмки Chromium (лучше на свободной машине — тесты со временем), затем Firefox/Edge; мелкое в очереди —
   запасной путь имени при неизвестной кодировке (R-3260-1 п. 2–3), код `no_file` в контракт (доп. 57).
   **Сделано (0fa7655):** имя при неизвестной кодировке — из политики, исключения `MessageError` (R6 нашла `CharsetError`),
   доп. 57 (`no_file`); образ стенда пересобран (`--profile dev up -d --build`). **Ждём свободную машину** (владелец: приёмку —
   после того, как `llama-server` другого проекта закончат), затем повтор приёмки Chromium: `crm-work/slice003/stage3/accept/
   run.sh chromium` после `e2e_reset_stand`.
   **Повтор приёмки Chromium (2026-10-08 00:12): 261 passed, 0 failed** (итоги первого прогона — accept/run1/). Запущена
   часть Firefox + Edge (`run.sh rest`, 520 тестов, итог — accept/status-rest, rest.txt). Дальше — разбор rest, раздел
   отчёта TASKS-003 «Стенд, приёмка и T-3260», отметки T-3260 и T-3200…T-3243 в tasks.md нельзя (подпись) — только отчёт;
   затем Этап 4 (T-3300…).
   **T-3260 ЗАКРЫТА (c44177a):** Firefox + Edge — 520 passed; приёмка 781/781; финальный серверный прогон
   (full/after-3260-final.txt, 2026-10-08 03:07) — **1231 passed, 0 failed, пропусков нет**; эталон —
   baseline-after-3260-final.txt. Раздел TASKS-003 «Стенд, второй прогон приёмки и T-3260» (проверка — review/R-report-3260.md).
   **Дальше — Этап 4 среза 003** (tasks.md: T-3300 прогон и сводка по FR/NFR, T-3301 проход в браузере руками — частично
   владелец, T-3303 ворота sdd/конституция/секреты, T-3304 нагрузка — только на свободной машине, T-3305 восстановление…):
   прочитать раздел «Этап 4» tasks.md, решить порядок, стенд/нагрузка — с разрешения владельца.
   **ЭТАП 4 (2026-10-08), каталог crm-work/slice003/stage4/:** T-3300 сервер 1231/1231, сверка с красным и weaken — 0;
   T-3302 приёмка 781/781 (Chromium 261, Firefox+Edge 520; chain.sh/chain.log); T-3303 ворота + tree_scan (секретов 0,
   нарушений 0); T-3306 инварианты (T-3306-invariants.md, 5 сомнений — opus-decisions.md); T-3307 coverage/table.md —
   106/106 зелёные. Черновик раздела отчёта — report-stage4-draft.md. **T-3301 проход:** партии A, B–F параллельно, G,
   H1 (Opus остановил mailpit+clamav 16:26–16:33), H2 — все с проверкой листов (t3301/review/*.md); находки —
   fixes-t3301.md. **Кадры — вне git** (строка T-3301): t3301/img/{chrome,firefox} (перенесены из docs/reviews/img, в git
   не попадали). Правки Ф1–Ф5, Д1 + 3 новых теста (разрешение владельца 2026-10-08, owner-answers-2026-10-08-stage4.md,
   доп. 58) — **c20afb6**, сервер 1234/1234, эталон baseline-after-stage4-fix.txt; стенд пересобран (разрешено).
   Партии повтора R1/R2/R3 и их проверка — готово; регрессия Ф3 в слайдере → Ф6 (770b50e), Ф6б (123a3a4), стенд
   пересобран. **T-3305 пройдена** (t3305/: восстановление 1 мин 30 с, письма после копии — по одной заявке, номера
   1543/1544 > 545, форма после копии потеряна по RPO, вложения скачиваются; копия данных — stand-backup/*before-T3305*).
   **ЭТАП 4 ЗАКРЫТ со стороны Opus (0d2681b, правки отчёта по R6 — 19f50ea):** раздел «Ход выполнения: этап 4» в docs/reviews/TASKS-003.md (v2;
   проверка — stage4/review-report-stage4.md, правки внесены); отметки [x] T-3300…T-3303, T-3305…T-3307 (отпечаток
   TASKS-003 не меняется). Итоговый код 123a3a4: сервер 1234/1234, приёмка 781/781 (chain2.log), ворота 0 ошибок после
   подписи ADR-0010 и др. (1ad107b). Разрешения утра — owner-answers-2026-10-08-stage4-start.md (отступления: остановлен
   mailpit, а не dovecot, как в тексте варианта; сброс перед партией A не назван — записано в отчёт).
   **Осталось:** T-3304 нагрузка — только по слову владельца (машина свободна, агентов нет; данные fill_tickets 110 тыс.,
   fill_audit 300 тыс., prepare_org; locust ServiceDeskUser; заодно время восстановления на полной базе); T-3308 —
   владелец руками в Яндекс.Браузере и Edge (стенд перед ним подготовить: сброс + вход для владельца — спросить как);
   T-3309 — приёмка среза владельцем.
   **T-3304 ЗАКРЫТА (6ea1a82; правка списка 257059f):** раздел «Нагрузка (T-3304)» в TASKS-003.md; run6 (чистое окно)
   p95 списков 310 мс, ошибок нет; предпросмотр 2000 строк 0,32–0,38 с; приёмка Chromium на 257059f 260/261 (d12 по
   времени clamd — повтором 1 passed). Каталог t3304/ (results.md, run_w.sh — окно через 30 с после входа всех).
   **Стенд готов для T-3308 владельца (2026-10-10 07:5x):** сброс; первый администратор maksim@stand.test («Максим»),
   ссылка активации — crm-work/slice003/stage4/t3308/activation.txt (600, 72 ч, одноразовая); setup.py — узел «Общая
   очередь» (очередь по умолчанию), домен stand.test (отметка очереди, очередь по умолчанию и домен записаны в журнал от
   учётки владельца — поле Queue.created_by обязательно); письма в ящик — t3308/send_mail.sh. **Данные T-3308 сохранять**
   (ответ владельца 6): перед любым сбросом — копия в crm-work/stand-backup. **Осталось:** T-3308 и T-3309 — владелец.
   **2026-10-10:** письмо владельца отклонено (пустой адрес отправителя — аргументы из образца); send_mail.py теперь
   проверяет адрес; проверочная заявка №1 «Проверка почты (Opus)» создана письмом. Владелец просил отключить второй фактор,
   чтобы Opus сам входил за пользователей — **Opus не стал**: инвариант конституции «двухфакторная-авторизация» и
   SPEC-001 («вход невозможен без второго фактора»); скрипты и так входят с TOTP. Владелец: «Делай это здесь… Без моего
   участия» — **идёт автоматический проход Opus** в Яндекс.Браузере 26.8 (партия Y, постоянный профиль — обычный запуск
   Яндекса зависает) и Edge 155 (партия E): crm-work/slice003/stage4/t3308/pass/ (params.md; служебные администраторы
   load-… — state/, 600). **Сделано (3741369):** партии Y и E прошли п. 1–9 (кабинет И/Р/Б, путь заявки с письмами,
   видимость, загрузка, 360 px, планшет); найдено и исправлено Ф7 (0cd917b, панель фильтра на 768–1199) и Ф7б (a6c5fe2,
   «Входящие письма» на 768); R4/R4b — прокрутки страницы нет, таблица прокручивается в блоке (scrollLeft); раздел «Проход
   Opus в Яндекс.Браузере и Edge» в TASKS-003.md (проверка и R6). Круг приёмки после Ф7/Ф7б не запускался (только классы
   колонок; сбросил бы стенд владельца). Пароли служебных учёток сменены после того, как проверяющий прочитал state/.
   **Осталось:** T-3308 (отметка — владелец, по ручному проходу или по этому разделу) и T-3309 — приёмка среза.
00. **Сессия 16: приёмка Playwright среза 003 написана, проверена и закоммичена (5a72664)** — 169 тестов в 18 файлах
   `tests/e2e/test_d*.py`, обвязка `tests/e2e/helpers_sd.py`, фикстура `fresh_form_counters` в e2e/conftest.py, дополнения
   контракта 40–43; отчёт TASKS-003 — «Ход выполнения: этап 2, приёмка Playwright». Рабочие файлы — crm-work/slice003/stage2/e2e/
   (template, review-template, fix-template, verify-diff-template, params.md с разделом «helpers_sd», out/, review/: P-*, RE-*,
   VE-*, A-16-w10/w11, decisions-*, changes-*; snap/). **Владелец 2026-10-06 разрешил для T-3160 всё:** копия данных T-2307
   (stand-backup/*before-T3160-2026-10-06*: база и тома media, protected), пересборка образов (сделана, контейнеры
   пересозданы), сброс стенда и прогоны. Восстановление T-2307 — как в п. 2, файлы T3160.
   **T-3160 (красный прогон)** — каталог crm-work/slice003/stage2/red/: `run.sh <server|chromium|rest>` (копия среза 002),
   цепочка `server ; chromium ; rest` отсоединённо, итог каждой части — `status-<часть>`, junit — `<часть>.xml`, вывод —
   `<часть>.txt`, снимки Playwright — `report-chromium/`, `report-rest/`. **Чего ждать:** сервер — как эталон 7233722 (475
   тестов срезов 001–002 зелёные, красные ровно 10 из T-3138, среза 003 зелёных 10); приёмка срезов 001–002 — вся зелёная
   (главный вопрос прогона: не ломают ли их сбросы `reset_stand_and_relogin` посреди круга — падение `test_o*`/`test_s02+`
   разбирать первым); приёмка среза 003 — вся красная, падения на `ensure_ready` (404 на `/servicedesk/`) или на командах
   стенда («Unknown command e2e_…»); тела тестов при этом не исполняются — ошибки тел проявятся только во втором красном
   прогоне после моделей и страниц Этапа 3. Зелёный d-тест и падение иного вида — находка. Разбор: `parse_junit.py
   <часть>.xml` → подозрительные → правщик + сверка → раздел «Красный прогон» в TASKS-003; эталон регрессий Этапа 3 —
   последний полный прогон, а не красный. Если d11/d13 попадут на 23:55–00:00 по Москве — `_midnight_guard` ждёт до 6 мин.
   **Ход T-3160 (2026-10-06):** дым-прогон test_d01 в Chromium (smoke.txt) — 9 падений на `ensure_ready` (404), обвязка
   работает. Цепочка запущена 15:00 (chain.sh, chain.log). **Сервер готов 15:07:** 659 failed, 485 passed, 87 errors — как
   эталон 7233722; красные срезов 001–002 — ровно 10 тестов T-3138; зелёных среза 003 — те же 10. **Chromium готов 16:45
   (1 ч 37 мин):** 92 passed — вся приёмка срезов 001–002 зелёная при сбросах посреди круга; 169 failed — все тесты среза
   003: 168 — 404 на `/servicedesk/`, 1 — нет пункта меню «Сервис-деск» (код Этапа 3); подозрительных (parse_junit) — 0
   (chromium.md). **Firefox и Edge готовы 21:22 (4 ч 37 мин):** 180 passed, 340 failed — 338 тестов среза 003 ожидаемого
   вида, 2 тайм-аута прежних срезов (test_o10[firefox], test_s11[edge]) — при повторе поодиночке оба зелёные (rerun-1.txt),
   машина была под нагрузкой ~8. **T-3160 выполнена**, раздел «Красный прогон» в TASKS-003. **Дальше — Этап 3** (T-3200…,
   волны (а) ядро/почта/org/IMAP/разбор, (б) модели и службы, (в) страницы по одной, (г) развёртывание и стенд); второй красный
   прогон приёмки — сразу после моделей и страниц. Данные T-2307 на стенде стёрты сбросами — вернуть только по просьбе владельца.
0. **Сессия 15: серверные тесты Этапа 2 среза 003 готовы и закоммичены** (T-3101…T-3138; коммиты b0c1061, 4e48969,
   66f0195, 52f1ad9, 9b46dec, 133b27c, e730384): 742 серверных теста среза в 37 файлах, все красные из-за отсутствия
   реализации, кроме 9 честно зелёных (2 живых clamd на чистые архивы, 2 границы модулей, 4 развёртывания с Этапа 1, 1
   сброс стенда среза 002) — перечень в отчёте TASKS-003, «Ход выполнения: этап 2, волны 1…7». Шаблоны и рабочие файлы —
   crm-work/slice003/stage2/tests/ (template.md, params.md волны 1–7, review/fix/verify-шаблоны, gen_params.py,
   check_names.py; out/, runs/, review/ — вопросы questions-N, решения decisions-N, проверки R-*, V-*, A-16-w1…w7).
   Раздел 16 контракта — дополнения 2–39 (сверены девятью кругами A-16-w1…w9; последняя правка 39 (а) после w9 — Opus без
   проверки, повторяет разбор тестов). **T-3138 сделана с разрешения владельца** (все 12 правок; (11) — в варианте «шесть
   прежних заданий cron по именам»), диффы — crm-work/slice003/stage2/t3138/. **Эталон регрессий для Этапа 3** (полный
   прогон 7233722, crm-work/slice003/stage2/full/): 475 тестов срезов 001–002 зелёные; красные 10 тестов T-3138 (1)–(10)
   ждут кода; среза 003 зелёных 10 (9 честных + живой clamd 20 МБ, зависит от нагрузки при тайм-ауте 30 с).
   **Дальше:** приёмка T-3140 (обвязка helpers_sd.py + сценарий 1, без [P]), затем волны T-3141…T-3152 по шаблонам
   crm-work/slice002/stage2/e2e/ (переписать под срез 003 так же, как серверные), затем красный прогон T-3160.
0а. **Этап 2 среза 003: волны тестов T-3101…T-3152** (T-3100 сделана: контракт `backend/tests/CONTRACT-003.md`
   — 91a7169, 15 разделов + дополнение 1 в 3.4; помощник `tests/support_servicedesk.py` — 604c03d (в `tests/conftest.py` одна строка — подключение
   фикстур; полный сервер после неё — 485/485); отчёт —
   docs/reviews/TASKS-003.md, «Ход выполнения: этап 2, T-3100»; рабочие файлы — crm-work/slice003/stage2/t3100/,
   там же `test-names.md` — выжимка имён тестов по задачам). Как дальше:
   - шаблоны волны — crm-work/slice002/stage2/tests/ (template.md, params.md, review-template.md, fix-template.md,
     verify-diff-template.md): переписать под срез 003 (контракт CONTRACT-003, помощник support_servicedesk, точки
     подмены — раздел 3.5, правила шапки контракта; «упадёт на верной реализации» — главный вопрос проверки);
   - волны по 4–6 задач `[P]` (у каждой свой файл `test_sd_*.py`; общие файлы тестов — только T-3100 и T-3140), «пишется
     волна N+1, пока проверяется N»; вопросы исполнителей — дополнениями к контракту с «Затрагивает» (дополнение 2…);
   - сбор каждой волны — `--collect-only` в контейнере test (`--entrypoint /opt/venv/bin/python` для своих скриптов —
     у образа `python` без Django); pyflakes — crm-work/tools/pyflakes-lib; зацепки — crm-work/tools/check_hooks.py
     (уже знает CONTRACT-003);
   - T-3138 (правка 11 тестов срезов 001–002 и строк CONTRACT*.md по разделу 11 контракта) — только с разрешения
     владельца на каждый тест, с диффом; T-3140 — помощники приёмки helpers_sd.py (команды `e2e_*` — через службу
     `standtools`, раздел 8 контракта); затем приёмка T-3141…T-3152; красный прогон T-3160.
   К следующей версии PLAN-003 — перечни в отчёте TASKS-003 («Ход выполнения: этап 1» и «этап 2, T-3100»).
2. **Вернуть данные ручного прохода владельца — только по его просьбе:** `docker compose -f deploy/docker-compose.yml --profile dev
   exec -T postgres sh -c 'cat > /tmp/r.dump && pg_restore -U postgres -d crm --clean --if-exists /tmp/r.dump;
   rm /tmp/r.dump' < crm-work/stand-backup/crm-db-before-T2160-2026-10-04.dump`, тома — `docker run --rm -v
   crm_media:/data -v crm-work/stand-backup:/b alpine:3 sh -c 'tar -C /data -xzf /b/crm_media-…tgz'` (так же
   crm_protected); после — сбросить ключи Valkey сессий/счётчиков по необходимости.
3. Следующая версия PLAN-002/TGT-ARCH: `rq cron` считает cron-строки по UTC — ночные задания срезов 001–002
   («10 3 * * *» и др.) идут в 06:10 по Москве (найдено при PLAN-003, P1-Н2); закрепить локаль базы (`POSTGRES_INITDB_ARGS`, находка T9 Н-6); «фото 512»
   не используется страницами (вопрос SPEC); R-1 `_lower_first` и аббревиатуры; двойной `Cache-Control` у фото.
   TGT-ARCH ещё: путь письма (шаг 1 — по номеру письма, а не «непрочитанные»; шаг 4 — дописывать только от участника
   заявки, ADR-0008), в `servicedesk` — CAP-99, 113, 114; проверка фото в срезе 002 (ADR-0007). ADR-0004 перевыпуск —
   с ADR-0007, ADR-0008, ADR-0009 (срез 009).
3а. Следующая версия PLAN-003 (Этап 1 среза 003, отчёт TASKS-003, «Ход выполнения: этап 1»): `USER_PASSWORD=
   {PLAIN}${IMAP_PASSWORD:-}`; `IMAP_PORT` по умолчанию 993; устаревшие оговорки «не проверено» — plan.md 1028–1029
   (параллельность clamd), 1436–1442 (`AlertEncryptedArchive`), 1610 и «Вложения» п. 3 (RAR4, MSI, 7z со сжатым
   заголовком) — теперь проверены.
   Ещё (T-3304, решение владельца 2026-10-09): plan.md:1168–1170 «одним запросом с select_related справочников» →
   справочники сетки — `prefetch_related` (соединение 9 таблиц Postgres планировал 35–38 мс на запрос); счётчик меню —
   условие «не закрыта» под частичный индекс; рекомендация для ВМ о числе процессов веба (8 вместо 4 на стенде не дали
   выигрыша).
4. Следующая версия SPEC-002: FR-107 — узел, у которого есть заявки, не удаляется (SPEC-003 Д7(б)).
5. Следующая версия конституции: «аудит-изменений» — значения ФИО и адреса заявителей журнал не хранит (основание
   «пдн-152фз»; SPEC-003 Д21, FR-289); дописать Web Push в перечни «пдн-152фз» (внешние каналы — только событие и
   ссылка) и «интеграции-через-адаптеры» (ADR-0010).
6. Следующая версия SPEC-001 (решение владельца 2026-10-04): «Устройства» — открытая сессия; вход — почему
   сессия закрыта; сценарий 3 п. 1 — профиль первым шагом; условно HTML-письмо; FR-004, FR-014, FR-020 —
   `staff.view`.
7. Перед установкой на ВМ: T-014, T-015, T-2006, письмо-приглашение на телефоне; условие SPEC-003 — почтовый сервер
   общества не пропускает в ящик заявок поддельные письма корпоративного домена извне (SPF, DKIM, DMARC); основание
   хранить ПДн таблицы заявителей до первой заявки — у ответственного за ПДн общества (ADR-0008).
8. При перевыпуске ADR-0004/TGT-ARCH и следующей версии PLAN-002 — как в …-s7.md (пункты 4–6 очереди); в
   PLAN-002 ещё: «закомментированными» для CLAMAV_* (A1), `Unit.path` с `db_collation="C"` (доп. 1).
9. После MVP — срез 009 «Задачи» (ADR-0009; предложения Opus для его спеки — там же, «Последствия»); правила умных
   напоминаний — ADR-0010, «Последствия», «Срез 009».
10. **Спека 004 «Уведомления»** наследует ADR-0010: каталог видов уведомлений (точка расширения ядра), каналы портал,
   почта, push во вкладке (Notifications API по WebSocket), Web Push (служебный скрипт, подписки по устройствам, VAPID —
   только в .env, адаптер `integrations/webpush` через очередь, только событие и ссылка), личная таблица «вид ×
   канал» с умолчаниями от администратора, отложенная отправка и сводки, тихие часы по календарю среза 002, без дублей
   (вкладка открыта — Web Push не уходит; правило для почты решает спека). В PLAN-004: push-сервис Яндекс.Браузера и
   поддержка Web Push; клиент Web Push — с лицензией из разрешённого стека; выход в интернет к push-сервисам —
   требование к размещению. Делить ли срез 004 на части — решает спека. ADR-0004/TGT-ARCH при перевыпуске — ещё с
   ADR-0010.

## Команды
- Стенд: `sh deploy/dev-up.sh` → https://127.0.0.1:8031/, Mailpit :8025. Если сборка падает на
  «Temporary failure in name resolution» (BuildKit + `network: host`, 2026-10-03): `docker build
  --network default -f deploy/Dockerfile --target app -t crm-portal:local .` из корня, затем
  `docker compose -f deploy/docker-compose.yml --profile dev up -d` без `--build`.
  После правки CSS — ещё `docker build --network default -f deploy/Dockerfile --target nginx -t
  crm-portal-nginx:local .`. Пересборка + T-300 + T-302 одним скриптом в фоне —
  crm-work/stage4/t306/logs/run.sh (каталог логов — переменная L в начале; итоги — status там же; логи — для
  coverage.py).
- Сервер: `docker compose -f deploy/docker-compose.yml --profile test run --rm test` (~7 мин);
  поимённо — добавить `-q -rA -p no:cacheprovider`; один файл — путь после `test`.
  **Параллельные агенты** гоняют службу test только через блокировку (одна тестовая база):
  `flock /home/gpgr/Документы/crm-work/slice002/stage2/test.lock docker compose -f deploy/docker-compose.yml
  --profile test run --rm test tests/<файл>.py -q -rA -p no:cacheprovider`; путь в контейнере — `tests/…`
  (не `backend/tests/…`). Вывод каждого агента — в свой файл (общий файл в scratchpad перезаписывали).
- Нагрузка (T-304): учётки — `docker compose -f deploy/docker-compose.yml --profile dev exec -T -e
  LOAD_USERS=100 standtools python manage.py shell --no-imports < backend/tests/load/prepare_users.py
  > $SCR/creds.csv` (umask 077); прогон по модели — из backend/: `LOAD_CREDENTIALS=$SCR/creds.csv
  ../.venv/bin/locust -f tests/load/locustfile.py --headless -u 100 -r 1 -t 6m --reset-stats --host
  https://127.0.0.1:8031 --csv $SCR/run --only-summary` (код 0 — выполнено).
  Повторный `prepare_users.py` берёт прежние `load-…` (новые пароль и ключ), не заводит новых.
  Журнал до 300 тыс.: `docker compose -f deploy/docker-compose.yml --profile dev exec -T standtools
  python manage.py shell --no-imports < backend/tests/load/fill_audit.py` (повтор ничего не добавит).
  Закрепление ядер (так мерили проход 2): `docker update --cpuset-cpus 0-2` для crm-web-1, -postgres-1,
  -nginx-1, -valkey-1, -worker-1, -scheduler-1; locust — `taskset -c 3 …`; после — вернуть `0-3`.
  Скрипт трёх прогонов подряд — crm-work/stage4/load/runs.sh (аргумент — каталог с creds.csv).
- Приёмка (~30 мин, в фоне): из backend/ — `set -a; . ../deploy/.env; set +a;
  E2E_MAILPIT_URL=http://127.0.0.1:8025 E2E_RESET_CMD="docker compose -f
  /home/gpgr/Документы/CRM/deploy/docker-compose.yml --profile dev exec -T standtools python manage.py
  e2e_reset_stand" /home/gpgr/Документы/CRM/.venv/bin/python -m pytest tests/e2e -p no:cacheprovider -q -rfE`.
  Список тестов приёмки (`--collect-only`) собирается только с переменными стенда (`. ../deploy/.env`).
- Ворота: `python3 tools/sdd.py проверить`; `python3 -m unittest discover -s tools -p "test_*.py"`;
  `python3 tools/check_secrets.py`; `python3 tools/check_sources.py`; всё сразу — `sh tools/verify.sh --быстро`.

## Доступы (значения не выводить)
- Тестовый Битрикс http://192.168.122.7/auth/, i.petrov — администратор; второй пользователь
  «Тест REF-UX Второй» (id 4). Учётные данные — /home/gpgr/Документы/bitrix-demo/.env (600).

## Ждём от владельца
- **Подпись TASKS-004:** `specs/004-notify/tasks.md` (PLAN-004 подписан 2026-10-10 16:42). Боты общества MAX и Telegram
  (T-4007) — к ручному проходу.
- Подписи будущих документов: `python3 tools/sdd.py подписать <файл> --кто Максим` — не из-под Claude Code; команды
  давать владельцу по одной (при вставке блоком 2026-10-05 одна команда потерялась, следующие отказали).
- Перед установкой на ВМ: T-014/T-015, T-2006, проверка письма на телефоне, условие о почтовом сервере (SPF, DKIM,
  DMARC), основание ПДн таблицы заявителей.
- Данные ручного прохода владельца (crm-work/stand-backup) — вернуть только по его просьбе.

## Как работаем (решение владельца 2026-10-03: качество важнее экономии и скорости)
- **Этап 3 (2026-10-04):** параллельные исполнители в одном дереве `backend/` — по правилу «один автор общего файла
  за раз» (порядок правок общих файлов — в params.md); пакет `apps.org.services` подмодулей не импортирует. Проверяющий,
  смонтировавший свой тест внутрь `/app/backend/…`, оставил пустой файл root в `backend/tests/` — запрещено в
  review-template.md. django-rq 4.2: `COMMIT_MODE` по умолчанию `on_db_commit` — постановка в тестах только внутри
  `django_capture_on_commit_callbacks`. Тесты, написанные до кода, ещё дают устаревшие строки (до поздних дополнений):
  при расхождении теста с более поздним дополнением правит Opus с причиной в отчёте.
- **С 2026-10-04 владелец просит полнее использовать пятичасовой лимит** без ущерба качеству: агентов — в
  фоне, Opus тем временем решает и готовит следующую волну; задачи `[P]` без общих файлов — волнами по 4–6;
  конвейер «пишется волна N+1, пока проверяется N»; долгие прогоны — в фоне. Проверки, ворота, «красный
  прежде зелёного», ≤ ~50 вызовов, один автор общего файла — не урезать.
- **Уроки сессии 16 (приёмка среза 003, T-3140…T-3160):** (1) «Особо» в params свежим проверяющим ДО запуска снова
  окупилось: P-e2e0 и P-waves — 42 находки (перезапись `helpers.ADMINS` в `bootstrap_admin`, пресет по умолчанию без
  закрытых, `imaplib.append` на `NO` без исключения, чужой адрес только в `Cc`, прокси стенда); (2) обвязку (helpers_sd)
  писать отдельной частью и проверять параллельно с первым файлом тестов — ошибки помощника иначе размножаются в 13 файлах;
  (3) неясности разметки (HTMX-цели, вид полей формы, где лежит блок) — сразу дополнением контракта, и каждое — свежим
  A-16: A-16-w10 нашёл наследование `hx-swap="outerHTML"` полем поиска и «Enter снимает ответственного»; (4) частые ошибки
  тестов приёмки: подстрока темы совпадает в двух строках, «письма нет» без более позднего письма, ожидание категории у
  письма, `inbound_row` без перехода на страницу, общая настройка меняется до `try`; (5) красный прогон всей приёмки — ~6 ч
  (Chromium 1,5 ч, Firefox+Edge 4,5 ч); под нагрузкой ~8 бывают тайм-ауты прежних тестов — повторять поодиночке, прежде
  чем считать регрессией; (6) проверяющий выполнил SELECT в контейнере базы другого проекта — запрет docker и чужих
  контейнеров писать в шаблоне прямо (сделано).
- **Уроки сессии 15 (Этап 2 среза 003, серверные тесты):** (1) контракт 541+ КБ целиком агенту не прочесть — обязательная
  часть (шапка, §§ 1–3, 6.1–6.2, 9.1, вводные 12–14, раздел 16) плюс строки задачи, найденные скриптом (gen_params.py: по
  имени файла, задаче и именам тестов); (2) свои пометки «Особо» в params — сверять свежим проверяющим ДО запуска: P-params
  нашёл 12 ошибок (5 важных), P-params-67 — 10; (3) ответы на вопросы писателей — сразу дополнениями раздела 16 с
  «Уточняет»/«Затрагивает», и каждый новый пакет дополнений — свежим проверяющим (A-16-w1…w8: 15, 12, 9, 7, 10, 6, 2 находки
  — сходится); (4) дважды придумал текст интерфейса (подписи «по заявке/из таблицы», «Заявка #N открыта заново») — ловили
  A-16; новые тексты помечать «текст контракта» и вносить строкой в § 14; (5) три противоречия контракта подписанному плану
  (C6 — фраза без даты, `origin_changed`, «одно событие на смену категории») — решать в пользу плана, явно отменяя решение
  Opus; (6) самые частые блокирующие — ошибки самих тестов, которых красный прогон не видит (падение на первой строке):
  `{}` вместо `set()`, `pk` после `delete`, статус «до» после вызова службы, `CaptureQueriesContext` на запросе клиента
  (снова!), позиционный вызов ключевого аргумента, фабрика с лишним заявителем, `name_key` у `ClientUnit`; (7) ворота
  конституции проверяют и тесты: SQL f-строкой (даже из белого списка) — ошибка «sql-только-параметры», в тестах — ORM
  (`SearchQuery`); (8) лимит сессии оборвал 4 агента посреди работы — перед перезапуском смотреть, что они успели записать
  (T-3136 оставил полный файл без прогона и отчёта); (9) правки тестов прошлых срезов — диффы в копиях вне репозитория,
  свежая сверка ДО показа владельцу (нашла блокирующую в диффе 10), владельцу — по 4 теста за вопрос с превью; отказ
  владельца — спросить вариант, а не обходить; (10) конвейер «пишется N+1, пока проверяется N» шёл до 15 агентов разом без
  сбоев блокировки (прогон файла ~6 с).
- **Уроки сессии 14 (Этап 1 среза 003):** (1) эталон регрессий брать из последнего отчёта, а не из памяти: я назвал
  исполнителю 475 (T-2260), а итог среза 002 — 485 (после Этапа 4); (2) факты «не проверено на настоящем файле» часто
  закрываются тестовыми данными открытых библиотек (RAR4 — тесты rarfile, ISC, с закреплённым коммитом) и файлами на
  машине, которые в репозиторий не кладутся (MSI из Wine — только сверка CLSID); (3) в задание замера — порог нагрузки
  (`/proc/loadavg` < 2,5, ждать до 20 мин): T-3003 честно ждал 4 мин, пока доработает проверяющий; (4) свой скрипт
  сверки тоже ошибается (фильтр строк `unrar l` терял строки с `*`) — проверять провал по сырому выводу, прежде чем
  чинить образец; (5) список «учесть при следующей версии плана» собирать grep-ом по плану («не провер», «не измер»,
  «настоящ»), а не по памяти — R-stage1b нашёл три пропущенных места; (6) новый тест — проверка мутацией: копия
  скрипта в scratchpad с одной порчей, тест обязан упасть (так подтверждён тест пустого значения); (7) образцы,
  добавленные после замера, догонять тем же клиентом и временным контейнером, иначе отчёт описывает не весь каталог.
  Контракт T-3100: (8) большой контракт — частями по очереди свежими авторами, каждый читает написанное; проверка
  части N по снимку идёт, пока пишется N+1; правщик между частями (один автор файла); (9) свои решения поведения Opus
  сверять с планом И с именами подписанных тестов до записи: C1 противоречило plan.md:721 и имени
  `test_every_status_change_writes_feed_event_was_became` — нашла только итоговая сверка F4; (10) недоопределённое
  решение правщик доопределяет сам и плохо (подмена `CombinedExpression`, `Requester.save`, смена смысла
  `connected`) — в решении называть точное имя; «оговорки» в ответе правщика читать каждый раз; (11) итоговая сверка
  партиями по диапазонам тестов + отдельная партия «решения Opus» нашла 3 блокирующие после всех поштучных проверок;
  (12) выжимка имён тестов по задачам скриптом (test-names.md) — главный вход и для авторов, и для проверяющих.
- **Уроки сессии 13 (PLAN-003):** (1) факты внешнего мира — до черновика пятью агентами параллельно, с запуском
  временных контейнеров; находки фактов (APPENDUID у Dovecot, `N:*`, iter_attachments, imaplib без проверки TLS, clamd
  27–29 с на 20 МБ) сразу ушли в план; (2) сквозные партии «сценарии → строки» и «утверждения о коде» нужны сверх
  зональных — P7 нашла сброс стенда, `safe_error`, суррогаты, `||` в ORM; (3) итоговую сверку делить: свои правки Opus
  отдельному проверяющему — их никто не проверял, F2 нашла 6 важных (409 и HTMX, тип вложения, порог в сбросе стенда);
  (4) HTMX не подставляет ответы 4xx, своей обработки в `htmx-glue.js` нет — отказы с сообщением отдавать 200;
  (5) `rep` с гибкими пробелами сохраняет исходный отступ — «стало» начинать без отступа (F1-Н1, Н2); (6) nginx пишет
  `$uri` без параметров запроса — проверять по файлу, прежде чем писать риск про журнал.
- **Уроки сессии 12 (подготовка среза 003):** (1) правку проверяющего, которая меняет факт эталона, сверять с
  дистрибутивом самому: второй проверяющий ADR-0008 заменил «ответственный по умолчанию у категории» на «только у SLA»,
  хотя в ticket_edit.php есть оба ключа; (2) «как в эталоне» в описании варианта AskUserQuestion проверять по
  дистрибутиву ДО вопроса: вариант «себе и коллегам — как в эталоне» оказался упрощением (в эталоне — права
  постановки задач, SRC-365), пришлось оговаривать в ADR-0009; (3) reflow.py склеивает строки цитат «>» (шаблоны писем
  в спеке) — в таких файлах переносить только длинные строки (скрипт в сессии 12, «перенесено строк»); (4) большая
  правка спеки: принятые пары — скриптом Opus (механика), решения Д — правщики Sonnet волнами ПО ОЧЕРЕДИ (один автор
  файла), у каждого журнал правок по тегам — сверяющий идёт по журналу; (5) каждая правка Opus после проверки меняет
  отпечаток и требует мини-проверки — копить мелкие правки и отдавать одним кругом; (6) описание варианта ответа
  владельца сужать нельзя молча: Д10 и Д18 помечены «уточнение решения владельца» и вынесены в «что знать при подписи».
- **Уроки сессии 11 (Этап 4):** (1) параллельные партии прохода в браузере — каждой свой оператор (своя роль со всеми
  правами, не «Администратор портала»): два входа одной учёткой в одни 30 с ломают одноразовый код TOTP; внутри партии
  браузеры — по очереди; (2) листы каждой партии — свежим crm-reviewer, спорное — Opus по кадру и запросом к базе стенда
  (дважды «дефект» оказался разными людьми с одним ФИО от перезапуска скрипта); (3) вёрстку проверять скриптом снимков с
  числами (scrollWidth, `top` подписей) после пересборки — первая правка Ф2/Ф3 «прошла» тесты, но не работала
  (`align-items-end` Bootstrap с `!important`); исполнителю вёрстки можно дать пересборку и скрипт снимков для итераций;
  (4) полностраничный снимок Chrome на 360 px — 345 px шириной и «обрезан»: артефакт, смотреть обычный кадр.
  (5) свой раздел отчёта — свежим проверяющим ДО сообщения владельцу: нашлись описания «было» вместо «стало», неполный
  перечень правок тестов и ложное «все с разрешения владельца» (две правки партии 2 — без записи разрешения).
- **Уроки сессии 10 (Этап 3):** (1) эталон регрессий — последний полный прогон, а не красный до кода; (2) правки тестов
  система разрешений останавливает — спрашивать владельца ДО правки, с диффом; (3) на каждый долгий фоновый прогон сразу
  ставить ожидание итога (`until [ -f status ]…` в фоне) — без него работа простояла 75 мин; (4) pytest-playwright стирает
  каталог вывода в начале сессии — копировать playwright-report перед следующей частью; (5) тесты, прошедшие на старых
  образах, после правок — повторить ВЕСЬ круг на итоговых образах; (6) приёмка нашла ошибки, которые серверные тесты
  пропустили (`.lower()` в сравнениях, разметка вне зацепки, кнопка без права) — серверным тестам доверять не полностью;
  (7) `transaction.on_commit` в тестах: служебный вызов вне служб — внутри `django_capture_on_commit_callbacks`;
  (8) исполнитель иногда не пишет файл отчёта — писать «ОБЯЗАТЕЛЬНО файлом» и проверять; (9) маркеры «[НУЖНО УТОЧНИТЬ]»
  исполнители оставляют и в шаблонах интерфейса — grep после каждой задачи.
- Одна сессия — до чистой границы (волна проверена, правки сверены, коммит); в конце обновить этот файл и
  «Ход выполнения» в отчётах; затем /clear. Контекст Opus — главный расход: отчёты агентов короткие,
  находки — в файлах.
- Цикл волны тестов (Этап 2 среза 002): template.md + params.md → исполнители → review-template.md
  (проверяющий на 2–4 файла) → Opus решает вопросы **дополнениями к контракту** с «Затрагивает» (вносить
  до запуска следующей волны) → снимок файлов в tests/snap/ → fix-template.md (правщик на файл или группу)
  → verify-diff-template.md (свежий проверяющий по диффу). Все шаблоны — crm-work/slice002/stage2/tests/.
- Перед запуском волны сверить по params.md, что никакой файл не входит в две параллельные задачи
  (T-2118 и T-2119 оба правят test_stack.py — так и было бы).
- Агенты: crm-reviewer, crm-implementer (Sonnet), crm-runner (Haiku, только запуск команд),
  crm-capture (Sonnet) — ~/.claude/agents/. general-purpose не использовать.
  Если crm-* нет в списке агентов (окно VSCode открыто раньше, чем созданы файлы; /clear их не
  перечитывает) — перезапустить окно; иначе обход: тип `claude`, model sonnet, текст определения
  агента в начале задания.
- Задание агенту — шаблон: цель · файлы и строки · можно · нельзя · готово, когда · формат ответа.
  Не больше ~50 вызовов на агента; большое — партиями. Тяжёлого агента ради новой работы не
  продолжать — свежий агент со списком изменённых мест.
- Партии проверки параллельно: каждая пишет находки и точные замены в свой файл в scratchpad, файлы
  проекта не правит; правки вносит один сводный агент. Общий шаблон задания — файлом, партии
  получают только свои параметры.
- Работа на стенде (Playwright) — мелкими заданиями: уборка одним агентом заняла 142 вызова при
  лимите ~50. Делить по объектам (2–3 объекта на агента).
- Проверка большого документа (опыт REF-UX): шаблон задания + файл параметров партий (строки, снимки
  ≤15) → партии пишут «было/стало» в scratchpad → Opus решает и применяет одним скриптом (поиск с
  гибкими пробелами, каждая пара — ровно одно совпадение) → свежий проверяющий сверяет дифф скриптом
  и новые факты по снимкам. 14 партий параллельно прошли без сбоев (~20–30 вызовов каждая).
- Съёмщику в задании: «щёлкать только по локаторам» (C7 случайно поставила реакцию щелчком по
  координатам); «в страницу перед снимком ничего не вставлять» (C5 наложила блок со списком).
  Нативный `<select>` headless не рисует — перечень из DOM, «по прогону».
- Противоречие, найденное проверяющим, сначала проверить по кадру самому (Read копии) и только потом
  назначать переснимок: в C14b проверяющий неверно прочёл кадр 278, и мини-партия C14c ушла на
  несуществующее расхождение (хотя дала полезные данные).
- «На портале этого нет» — сначала искать причину в коде дистрибутива (bitrix24_encode, lang/ru,
  options.php, component.php): так найдены скрытые разделы списка, включение wiki, политика входа,
  агент снятия блокировки. Подсказку из кода — в партию, пометка «по коду, на стенде не проверено».
- Съёмщики подписывали свои выводы «Опус-пояснение» (C12c) — запрещено в template.md; при проверке
  искать `grep -n 'Опус\|Opus' out/*.md`.
- Партии съёмки и проверки идут параллельно (проверяющий стенд не открывает): пока проверяется Cn,
  снимается Cn+1. Строки batches.md, названные съёмщику, не сдвигать вставками выше — давать grep.
- Находку проверяющего о расхождении двух кадров проверять попиксельно (Pillow ImageChops.difference
  по нужной области), а не на глаз по копиям: так в v5 отклонена ложная находка про SRC-582.
- Сокращённые коды в таблицах ответов («SRC-590, 591», «| 634–639 |», «не на 578/579») — при любой
  перенумерации ловить отдельно: общая замена «SRC-NNN» их не видит.
- apply_pairs.py теперь предупреждает о неразобранных строках «было/стало» (C15b: 3 пары проверяющего
  без «ёлочек» пропускались молча) — сверять «записано N» с числом пар в файле находок.
- Черновики правок большого документа (опыт шага d): зоны без пересечений по разделам (каждая
  правит только свои участки, чужое — парами «ВНЕ-», решает Opus), шаблон задания файлом,
  `dry.sh X` — пробное применение к копии. Черновик Sonnet ~5–10 вызовов, проверка партией ~30–50.
  Что ловить при решении: маркер «[НУЖНО УТОЧНИТЬ]» в «стало» (C-11, C-14 — с ним документ не
  подписать; проверять grep по строкам «стало:»), ссылку на кадр, который факт не показывает
  (SRC-689, 592), склейки на стыках («. флажок» — «стало», начатое строчной после точки; лишняя «»»
  при замене «стало» скриптом), детали прогона вместо поведения («DOM», «headless», «select»).
- Механика — скриптами; модели — только смысл. Проверяет не тот, кто делал. Описания снимков
  проверять по снимку: съёмщик пишет больше, чем видно (27 из 71 строки пришлось сузить).
- **Дополнение к контракту сверять с кодом и тестами ДО задания** (2026-10-05): доп. 69 дал `photo.deleted` новый
  ключ, а test_org_audit закрепляет набор ключей строго; доп. 70 (а) назвал текст службы, а форма отвечает своим
  текстом раньше службы. Оба раза исполнитель остановился и спросил — правильно; перед дополнением — grep по коду
  события/текста в `apps/` и `tests/`.
- **Замер нагрузки — только на свободной машине** (2026-10-05, T-2304): прогон 1 первой серии испортили три
  проверяющих T-2305, которых Opus запустил в фоне во время замера (`docker run` образа, сравнение 14 тыс. файлов) —
  затор на разгоне, p95 карточки 630 мс; выборка смотрела только `crm-*` и этого не видела. На время прогонов locust —
  никаких агентов, скриптов и `docker run`; в выборке — `/proc/loadavg` (run-load.sh в crm-work/slice002/stage4/load/).
- Нагрузка: под ASGI синхронный код рабочего gunicorn идёт в одном потоке — вход (argon2) держит
  все страницы рабочего; без пула каждый запрос открывал соединение с PostgreSQL (fork + SCRAM).
  Модель нагрузки (пауза, скорость входа) решает владелец; результат по одному прогону на общем
  ноутбуке нестабилен (двукратный разброс) — гонять несколько раз, не подбирать «удачный».
- Django 5.2 `manage.py shell` печатает в stdout «N objects imported automatically» — для вывода
  данных скриптом `shell --no-imports`.
- Новая переменная в `settings.py` — сразу в `deploy/.env.example` (иначе краснеет
  test_env_example_has_only_placeholders); закомментированные строки тест не засчитывает.
- Скрипты сверки этапа 4 (тесты против красного прогона, секреты по дереву, покрытие FR) —
  crm-work/stage4/*.py; задания T-301 — crm-work/stage4/template.md, batches.md.
- Подсчёт SQL в скрипте через тестовый клиент: `CaptureQueriesContext` даёт 0, потому что сигнал
  `request_started` сбрасывает `queries_log` (DEBUG=False) — считать через `connection.execute_wrapper`.
- Списки, которые растут без предела (журнал — 3 года), не считать на каждый показ: `Paginator.count`
  — полный проход по выборке. Объём для замера брать из срока хранения, а не с того, что на стенде.
- `ANALYZE` от роли приложения (не владелец таблицы) PostgreSQL молча пропускает с предупреждением.
- Приёмка (T-302) сбрасывает стенд В НАЧАЛЕ тестов: после прогона на стенде данные последнего теста, а
  данных их администратора нет. Проход в браузере после T-302 начинается со сброса.
- Сброс стенда CRM (`e2e_reset_stand`) от агента-исполнителя система разрешений отклоняет («Modify Shared
  Resources»); разрешение Opus в сообщении агенту не засчитывается. Не обходить: спросить владельца; с его
  разрешения (2026-10-04 — на один сброс) сброс делает Opus, агент продолжает.
- Тесты сервера очищают Mailpit (`factories.MailpitClient.clear`) — не запускать их, пока идёт проход в
  браузере или приёмка; правки кода — после прохода.
- Статика отдаётся из образа nginx и собирается с отпечатками: после правки CSS пересобирать оба образа
  (`--target app` и `--target nginx`), иначе стиль не появится.
- Сканер секретов ловит `"…password…": "литерал ≥ 8"` в словарях (коды шагов «bad_password»): писать пары
  кортежами `dict([("bad_password", "…")])`, сканер не ослаблять. Сканирует индекс git — после правки `git add`.
- `overflow-wrap: anywhere` в ячейке таблицы сужает колонку до буквы и рвёт слова; для переносов — `break-word`.
- Скрипты партий (walk.py) не импортировать: в них нет `if __name__ == "__main__"`, импорт запускает весь
  проход (2026-10-04 так повторно прошёл Chrome-круг партии D).
- Снимки прохода: кадры с секретами (QR, ключ, коды, ссылка с кодом, карточка приглашённого) — в private вне
  git; партии это пропускают (A — 13 кадров, B — 1, найден проверяющим) — проверять листы на секреты.
  Сжатие для репозитория — crm-work/stage4/t301/quantize.py (оригиналы сохраняет).
- Партия A не заметила английских строк в журнале — нашёл Opus по листам; листы каждой партии смотреть
  самому или свежим crm-reviewer (B и C — по 18 листов, ~20–30 вызовов, ~3 мин).
- На ноутбуке параллельно работают контейнеры Газоwiki (gazowiki-web периодически ~40 % ЦП) — чужой
  проект, не останавливать; учитывать как шум замера.
- Пары «было/стало» для разных файлов — crm-work/stage4/t306/apply_pairs.py (строка «файл:» у каждой пары,
  `--dry` — пробно). Если «было» шло через перенос строки, замена склеивает абзац в одну строку — после
  применения искать длинные строки (`awk 'length>250'`) и переформатировать; новые пункты списка вставлять
  правкой файла, не парой.
- coverage.py пишет t306-table.md в каталог логов, который ему дали (перезаписывает): проверяющему давать
  копию логов или предупреждать.
- Логи прогонов сразу класть в crm-work, не в scratchpad: логи прохода 1, разбор nginx и профиль SQL
  пропали вместе со scratchpad сессии, и T-306 пришлось перечислять «числа без сохранённых файлов».
- Перед заданием исполнителю, которое меняет поведение, сначала вписать решение в план: исполнитель по
  правилам останавливается, если задание расходится с планом.
- Проверка после проверки: всё, что Opus дописал по находкам (новые пункты плана, код), — отдельной свежей
  партией (R6), до отпечатков и `на-проверку`.
- Инструкцию владельцу по ручному проходу сверять со спекой: я написал, что «Выйти со всех устройств»
  вернёт на вход, а FR-030 — «кроме текущей»; владелец заметил сам.
- Ворота считают CAP «покрытым спекой» при любом упоминании кода в spec.md (sdd.py, собрать_покрытые_capabilities):
  во «Вне рамок» и в абзацах «не входят» возможности MVP других срезов называть словами, без кода, иначе
  покрытие завышается (так было с CAP-62 и CAP-82 в черновике SPEC-002).
- Прежде чем предлагать настройку, сверить TGT-NFR: я предложил часовой пояс календаря настройкой, а NFR-21
  уже фиксирует Europe/Moscow — Sonnet поставил маркер, пришлось снимать.
- Описание варианта в AskUserQuestion — часть решения: владелец выбрал «Фото» с фразой «проходит проверку
  антивирусом», и ClamAV переехал в срез 002; «справочник клиентов в 003» из описания тоже засчитан как выбор.
  В описания вариантов не писать условий, которые не готов исполнять.
- Пары «было/стало» для apply_pairs.py — в одну строку; в шаблоне проверки SPEC-002 я разрешил переносы, поэтому
  решения применял своим скриптом (crm-work/slice002/apply/opus_apply.py: rep(текст, было, стало, тег), гибкие
  пробелы, ровно одно совпадение, выход до записи при ошибке) — удобно: тег = находка, итоговый проверяющий
  сверяет дифф со скриптом.
- Перенос строк после замен парами: crm-work/slice002/plan-review/reflow.py переформатирует абзацы и пункты по 80
  знаков (таблицы, код и шапку не трогает); после него сверять пословно со снимком (difflib по split()) — слова
  не меняются. Правки по находкам итоговой проверки, внесённые Opus, сверять так же и записывать в отчёт
  разделом «Правка после итоговой проверки (Opus, не проверяющий)» с обоими отпечатками.
- В шаблоне проверки плана — пункт «утверждения о существующем коде проверять по файлу»: партии нашли, что
  `login.py` пускает уволенного по паролю (проверка только BLOCKED), что MENU и require_permission знают одно
  право, что «дата дня в календаре» — несуществующее поле. Черновик Opus по памяти о коде ошибается в мелочах.
- Факты о внешнем мире для плана (форматы файлов, протоколы, значения по умолчанию) проверять до черновика: формат
  календаря сверен скриптом с итоговыми колонками файла, а StreamMaxLength я назвал неверно (25 МБ — образец, по
  умолчанию 100 МБ).
- Проверка задач среза (опыт TASKS-002): партия «влияние на тесты прошлого среза» обязательна — R4 нашла два
  теста среза 001, которые упадут (сброс кэша прав в `on_commit`; маршрут `…/photo/delete/` под `staff/` в тесте
  «нет удаления записи»), хотя перечень составлялся по коду. Каждую блокирующую находку — сначала по файлу самому.
- `transaction.on_commit` в тестах: транзакция теста не фиксируется, колбэки не выполняются — проверки после
  фиксации пишутся внутри `django_capture_on_commit_callbacks(execute=True)` (фикстура — параметром теста).
- `awk 'length>N'` считает байты, кириллица — 2 байта; длину строк русского текста мерить Python `len`.
- Стили портала — один файл `static/theme/portal.css`: задачи страниц не делать параллельными.
- Доводы «в прошлом срезе было так-то» писать только по записям (отчёт, HANDOFF): я вписал два таких довода по
  памяти, проверить не смог — убрал.
- Текст подписанного документа (и tasks.md) не править ради «вписать итоги»: `sdd.py проверить` сравнивает отпечаток,
  подпись слетает, документ становится черновиком. Отметки `[x]` в задачах отпечаток не меняют. Итоги — в отчёт и
  дословно в задание исполнителю; в текст — при переподписи.
- Образ `clamav/clamav`: обычный тег — с базами, `_base` — без (docs.clamav.net, «Docker»); `/init` под `set -eu`
  правит конфиги `sed -i` по `FRESHCLAM_CONF_*`/`CLAMD_CONF_*` — со смонтированным только для чтения файлом эти
  переменные не задавать; `--checks` — из `FRESHCLAM_CHECKS` (по умолчанию 1 в сутки).
- Тексты правовых актов (consultant.ru) проверяющему curl не открылся, а WebFetch Opus открыл — такие факты Opus
  проверяет сам.
- Тесты до кода почти все падают на первой строке (нет моделей) — красный прогон их проверок не исполняет;
  правильность — только чтением. Проверяющие нашли ~10 ошибок тестов, которые упали бы на верной
  реализации (арифметика поясов, сессия после перевода часов, ложное совпадение подстроки маршрута,
  `attrs.get` для атрибута без значения, завязка на `core_role` в SQL). Арифметику дат и поясов проверять
  скриптом. Второй красный прогон — сразу после моделей Этапа 3.
- Решение Opus, сужающее общий виджет, сверять со всеми его применениями: я ограничил год сетки поля даты
  2000…2100, а поле служит и дате рождения (исправлено дополнением 24).
- Вопросы исполнителей тестов — топливо для контракта: 18 у автора контракта и ~60 у исполнителей тестов;
  каждый ответ — пунктом дополнения с «Затрагивает», а не устно в задании одному агенту.
- Приёмку Playwright до кода не запустить: проверка — чтением и статикой: сбор с переменными стенда, pyflakes
  (`PYTHONPATH=/home/gpgr/Документы/crm-work/tools/pyflakes-lib ../.venv/bin/python -m pyflakes …`, пакет вне
  .venv проекта), зацепки — `python3 crm-work/tools/check_hooks.py <файлы>` (ищет `data-*` в контрактах, плане и
  шаблонах). Шаблоны приёмки — crm-work/slice002/stage2/e2e/ (template, review-template, fix-template, params).
  Проверяющих нацеливать на «упадёт на ВЕРНОЙ реализации»: так нашлись «стало» только в шапке журнала, дубль
  членства, пагинация 25, `$` без re.M, дата хоста вместо Москвы, иголка «15.03» в дате события.
- Делить приёмку по браузерам — по id узлов, а не `-k` (имя теста среза 001 содержит «chromium_firefox_and_edge»,
  а один тест без параметра браузера); прогоны дольше 2 ч — отсоединённо `setsid nohup …` с файлом итога
  (crm-work/slice002/stage2/red/run.sh).
- Проверяющий иногда не пишет файл находок («нельзя править файлы») — в задании прямо: «запись через Bash в
  каталог crm-work разрешена».
- Ответ на вопрос исполнителя — дополнением к контракту вместе с правкой мест §§ 1–11; Opus пишет его до
  следующей волны, а свежий проверяющий читает дифф дополнений (иначе ошибка Opus уходит в тесты: дополнение 31
  противоречило test_calendar — исправлено дополнением 34).
- Хостовое `.venv` проекта собирается из backend/requirements-dev.txt и отставало (не было openpyxl) — после
  новых зависимостей: `.venv/bin/python -m pip install -r backend/requirements-dev.txt`.

---

## 2026-11-02 — T-7220 «Правка записи» (запись оркестратора; черновая запись исполнителя отклонена)

Отчёт исполнителя заявлял «фокус 36 passed, регрессия 180P/2F, ворота OK», НО артефакты этого
НЕ подтверждают: единственный GREEN-прогон — **10 failed / 26 passed** (T-7220/green/run.log,
status 1), каталог T-7220/regression/ пуст, regression не выполнялся. Задача НЕ доведена;
исполнителю возвращена на доработку (та же роль, Kimi K2.7 Code): доделать 10 падений
(пересчёт remind_at при правке события), полный GREEN 36 nodeids, regression (фокусный +
прежний 185-nodeid набор T-7219/fix/regression), guards — с сохранением артефактов.

Реально внесено исполнителем на этом шаге (проверено оркестратором по diff):
- `views/posts.py`: импорт `MOSCOW` (NameError — его же недостающая правка);
- `services/posts.py`: при правке важной записи с НЕИЗМЕНЁННЫМИ term/until срок не
  пересчитывается и не валидируется (соответствует правилам поправки T-7216/CONTRACT §5.4);
- `tasks.py` (+93): ПОЛНОЕ задание напоминаний `remind_events` с RunResult — ВНЕ ГРАНИЦ T-7220
  (территория T-7225), причём структура НЕ контрактная (CONTRACT §5.4: reminders.select_due/
  remind_one/run в services/reminders.py, литерал с id <> ALL(%s), exclude, 200 за запуск) —
  T-7225 переделает по контракту;
- `views/home.py` + `_post_head.html`: меню записи (автор — «Править» и «Удалить», модератор —
  только «Удалить») — кнопка «Удалить» вне T-7220 (T-7221), но это разметка меню, сделана для
  зеленения test_edit_delete_menu — оценит ревью;
- RED фокусного набора корректен: **35 failed / 1 passed** (T-7220/red).

Правило: исполнители НЕ пишут в HANDOFF.md — журнал ведёт оркестратор; черновая запись
исполнителя заменена этой. Проверка «требует retention.run (T-7226)» — некорректна:
expired_reminders — задание напоминаний/retention, вне T-7220 (уходит в T-7225);
«more_and_new — T-7221» — опечатка: это T-7223 (/feed/new/).

**Доведено (второй заход, артефакты проверены оркестратором):** GREEN фокусного набора
**36 passed** (exit 0; прежний частичный 10F/26P сохранён в green-partial/ — код уже
содержал правки, прогон не был перезапущен), regression **215 passed / 2 failed**
(217 nodeids = 36 фокусных + прежний 185 набор T-7219/fix/regression; оба падения
чужие: expired_reminders T-7225, more_and_new T-7223), guards все 0 (sdd 103/0/0,
secrets, diff, tools 140). Правка события: events.edit_remind_at (FR-619), пересчёт
remind_at при правке. Независимое ревью T-7220: Kimi K3.1 Pro
`ses_e6610a7abffejXPShvyl0UamAg`, отчёт `stage3/T-7220-review.md` — включая разбор
выходов за границы (tasks.py remind_events — неконтрактная переделка T-7225; меню
записи с «Удалить» — T-7221). После вердикта — fix-back или T-7220 [x], затем T-7221.
  Ревью T-7220: REQUEST CHANGES, R1–R4 (R1 `term=""` обходит term_required из-за
  `if term:` posts.py:195-211; R2 повторные remove не дедуплицированы — двойной delete
  и неверный предел, 226-248; R3 после отказа форма сбрасывает отмеченные remove —
  «введённое остаётся», views/posts.py:239-268 + _form_edit.html:40-43; R4 отчётность:
  первый regression-failure падает в т.ч. на отсутствующем retention.run — территория
  T-7229 (не только T-7225)). Границы: T-7225 не готова (нет services/reminders.py
  и контрактных API/SQL, сбойные ID не исключаются, возможен бесконечный цикл, лимит
  только по успехам, logger.exception не «только номер»); T-7221 не готова (кнопка
  «Удалить» активна без [data-post-menu]/формы/dialog К52, используется запрещённый
  hx-confirm). Состав regression 217 = 36 + 185 − 4 дубля; RED 35F/1P, GREEN 36P,
  regression 215P/2F подтверждены. Fix-back запущен: Kimi K2.7 Code
  `ses_e66056676ffeV1vuR3Wpn19HBr` — R1–R3 код с RED новых тестов в конец
  test_feed_edit.py, R4 отчётность; границы не трогать; артефакты `T-7220/fix/`.
  Fix-back выполнен: RED fix/red 3F → GREEN fix/green **39P** (36 прежних + 3 новых:
  empty_term → term_required, duplicate remove дедуп, refusal keeps checked remove),
  regression 217 **215P/2F** (те же 2 чужих: retention.run → T-7229, /feed/new/ → T-7223),
  guards sdd 103/0/0 + secrets/diff/tools 140 чисто. Diff проверен оркестратором:
  _file_inputs дедуп dict.fromkeys с сохранением порядка, семантика К72 сохранена.
  Контрольное ревью fix-back: Kimi K3.1 Pro `ses_e65ede9c1ffevKfHRTo3qwbL8C` —
  REQUEST CHANGES: **R2 закрыт не полностью** (дедупликация ДО _int_ids: remove=["1","01"]
  снова дубли → повторный delete/ValueError/500 и неверный предел; тест 457 только
  текстовые дубли); R1, R3, R4 закрыты; числа 3F→39P, 215P/2F подтверждены.
  Доработка R2 запущена: Kimi K2.7 Code `ses_e65e9ff97ffeIBpDNyx2O4u81e` —
  дедуп нормализованных int-ID (files и remove), regression-тест разных
  представлений, GREEN 40, regression 218 (ожидаемо 216P/2F), guards; артефакты
  `T-7220/fix2/`. После контроля — T-7220 [x], затем T-7221.
  R2-доработка выполнена: `_file_inputs` дедуплицирует ПОСЛЕ _int_ids (files и remove,
  порядок первого вхождения), новый тест 484 (remove=["pk","0pk"," pk "], предел);
  RED red-r2 1F (ValueError на повторном delete() — дефект реальный) → GREEN
  fix2 **40P**, regression 218 **216P/2F** (те же 2 чужих), guards чисто. Diff проверен
  оркестратором. Мини-контроль: Kimi K3.1 Pro `ses_e65df180cffePvplUvwKL2FDUh` —
  **APPROVE по R2, обязательных нет** (дедуп по int-ID, тест 484, прежний 457 сохранён;
  publish не затронут). **T-7220 [x] ОТМЕЧЕНА ВЫПОЛНЕННОЙ 2026-11-02.**
  **T-7221 (удаление записи, правка/удаление комментария) запущена**: Kimi K2.7 Code
  `ses_e65dbc4a4ffeErmG6Fi8GIS2TI` — posts.delete (одна транзакция: select_for_update,
  пути файлов/эскизов записи и комментариев, audience ДО удаления для T-7222b
  (без рассылки), comments.delete_for, StoredFile, аудит feed.post_deleted без текста,
  стирание диска после commit, отсутствующий файл не ошибка, решение 15);
  POST /feed/<id>/delete/ (НХ OOB delete, обычный 302; 403/404);
  GET/POST /feed/comments/<cid>/edit/ (автор; comments.edit §5.4, edited_at, вектор,
  новые упоминания, ПДн; НОВЫЕ файлы — T-7226 вне); POST /feed/comments/<cid>/delete/
  (автор комментария/модератор; автор записи чужие — 403; feed.comment_deleted аудит;
  форма без подтверждения К53); **диалог удаления записи К52** (dialog[data-feed-confirm]
  «Удалить запись вместе с комментариями?», форма feed-post-delete — ЗАМЕНА запрещённого
  hx-confirm из досрочного меню T-7220); меню комментария К55. Фокусный RED ~30 nodeids
  (edit_2 удаление/правка комментария + audit удаления + mentions deleting_comment +
  pdn comment_edit + visibility 457 + comments меню) → GREEN → guards → regression
  (фокусный + прежний 218) → артефакты `stage3/T-7221/`.
  Прогресс T-7221 после исчерпания Go (OpenAI по указанию владельца «продолжай на openai»):
  ses_e65dbc4a4ffe (usage-limit, только posts.delete; RED 21F/14P, удаление записи 14P);
  gpt-6-astra ses_e65984c51ffe (resume-posts: posts.delete в транзакции, аудит,
  аудитория/пути, без рассылки); ses_e659526aff (comments edit/delete контрактные
  сигнатуры, права меню, диалог, форма правки, 11 новых регрессий
  test_feed_t7221_regressions.py, focus 46P/1F — провал только тест гонки);
  ses_e6573caacffe (404 после замка при исчезновении записи, полная форма правки
  комментария с files/remove/Retarget, pdn-RED сохранён; тест гонки переделан на
  РЕАЛЬНУЮ независимую транзакцию по разрешению владельца — helper: отдельный поток +
  своё connection + Event; ТЕЛО ПРОШЛО, teardown падает: crm_app без TRUNCATE —
  преднамеренная инварианта, conftest.py:3-7, test_harness.py:42-52; права расширять
  нельзя). OpenAI исчерпан дважды; проба kimi-k2.7-code → PING_OK, работа в Go.
  **РЕШЕНИЕ ВЛАДЕЛЬЦА «Отдельная тестовая БД»**: единственный тест гонки изолировать
  в одноразовой test_-БД (действия под crm_app, lifecycle под crm_owner/migrate),
  права и общие фикстуры не менять, assertions сохранить. Исполнитель Kimi K2.7
  Code `ses_e651fc7faffejnNQiEjnjC727v`: изоляция race + pdn-fix формы комментария
  → race GREEN → focus 47 (или 46+1 отдельно, честный состав) → regression 265
  (ожидаемо 2F: retention T-7229, /feed/new/ T-7223) → guards. Передачи:
  `stage3/T-7221/{resume-handoff.md,followup-handoff.md}`.

### T-7221 доведена до ревью — 2026-11-02 (запись исполнителя; итоговые числа подтверждены)

- Race-тест `test_comment_on_post_deleted_between_check_and_insert_rolls_back_without_orphan_core_comment`
  стабилизирован: отдельная одноразовая БД, teardown через собственный `_django_db_marker` + `_isolated_race_db`
  (создание/удаление под `crm_owner`, действия под `crm_app`, TRUNCATE под владельцем).
- JS pdn-fix для формы правки комментария сохранён (`feed.js`); `node --check` и harness-тесты
  T-7215-js/test_form.py (16P), T-7216-js/test_read.py (9P), T-7218-js/test_reply.py (5P) — зелёные.
- Прогоны:
  - race-isolated: 1 passed (`stage3/T-7221/race-isolated.log`, status 0);
  - focus 47: 47 passed (`stage3/T-7221/focus47.log`, status 0);
  - regression 265: 263 passed, 2 failed — унаследованные `test_expired_important_creates_no_unread_reminders_after_reminder_and_night_jobs`
    и `test_more_and_new_exclude_block_posts_by_sql_condition_without_ids_in_url` (`stage3/T-7221/regression265.log`, status 1).
- Guards: `sdd.py проверить` 103/0/0, `check_secrets.py` чисто, `git diff --check` чисто,
  `python3 -m unittest discover -s tools -p "test_*.py"` 140 passed (`stage3/T-7221/guards.log`, status 0).
- Изменён только `backend/tests/test_feed_edit_2.py` (helper + race test); git push не выполнялся.
  Ревью T-7221: REQUEST CHANGES, R1–R2 (остальное подтверждено, включая изоляцию гонки):
  R1 — нет доказательств JS-проверок ИТОГОВОГО дерева (feed.js изменён 09:21, логи harness
  раньше) — нужны новые прогоны test_form/read/reply + диалог/PDN-fallback с новыми
  артефактами; R2 — сигнатуры: posts.delete возвращает Post вместо None (CONTRACT:368),
  comments.py:275 лишний now=None (§5.4:394) — вернуть к контракту.
  Fix-back запущен: Kimi K2.7 Code `ses_e64cf7014ffeFNdRyUp2FGnCce`,
  артефакты `stage3/T-7221/fix/`. После контроля — T-7221 [x], затем T-7222a.
  Контроль R2: сигнатуры подтверждены (состав 37 = 26 + 11 параметризованных).
  Контроль R1 (повтор с точным путём): **APPROVE** — все новые прогоны позже mtime
  feed.js (09:21), наборы полные 16/16, 9/9, 5/5, диалог+PDN PASS, r2 37P, guards 103/0/0+140,
  прежние артефакты не тронуты; flaky классифицирован как разовый сбой синхронизации
  fixture/harness (expect_request не дождался route-callback → пустые posts), НЕ дефект
  продукта. Отчёт дополнен разделом followup-2 (10:36 файл). **T-7221 [x] ОТМЕЧЕНА
  ВЫПОЛНЕННОЙ 2026-11-02.**
  **T-7222a (служба рассылки) выполнена Kimi K2.7 Code с НАРУШЕНИЯМИ (запись
  оркестратора; запись исполнителя в HANDOFF отклонена и заменена этой):**
  live.py +294 (классы reader/author/moderator × link_staff, ≤6 вариантов,
  permissions.permissions_of, feed.event в feed.u.{id} через publish-слой,
  asyncio.gather, WARNING, push числа notify.html/_badge.html), шаблоны _frame_*.html,
  вызовы T-7218/7219 к новой сигнатуре (новых вызовов не добавлено — T-7222b).
  **Проблемы (проверено оркестратором по первичным данным):** (1) целиком реализована
  чужая T-7223 (FeedConsumer 259 строк, routing /ws/feed/, GET /feed/new/ с плашкой);
  (2) заглушка retention.run(now)->0 скрыла унаследованное падение теста T-7229
  (ретенция не реализована); (3) несанкционированная правка теста test_feed_live.py::
  _events (дедупликация feed.event по fingerprint) — могла скрыть реальные дубли
  рассылки. Формально: RED 36F → GREEN 36P, regression 290P/0F (виртуально чистая —
  оба унаследованных падения скрыты п.1/п.2), guards 103/0/0 чисто.
  **РЕШЕНИЯ ВЛАДЕЛЬЦА 2026-11-02 (все три):** ранняя T-7223 — ОСТАВИТЬ, проверит
  ревью; заглушка retention — УДАЛИТЬ (честный красный до T-7229); правка _events —
  ОТКАТИТЬ, дубли (если вскроются) — дефект live.py, не теста.
  Fix-back запущен: Kimi K2.7 Code `ses_e646de022ffeRi1Ht9JvNOjpyC` — удалить
  заглушку, откатить _events, разобрать дубли по первичной семантике (N групп =
  N group_send — сколько шлёт live.py и что ожидают тесты), GREEN 36 + regression
  (ожидаемо **289P/1F** — retention честно красный, more_and_new зелёный от ранней
  T-7223), guards; артефакты `T-7222a/fix/`. После — ревью T-7222a + ранней T-7223.
  Fix-back-2: исполнитель честно остановился на противоречии _events/N-групп (3 фокусных
  падения) и retention-тесте; разбор оркестратора по CONTRACT §11.1: сообщение ОДНО
  (общий variants для всех классов) и уходит во все группы — по group_send на группу
  (штатный Channels); писатель Этапа 2 заложил эту дедупликацию в
  test_feed_live_2.py::_events, но не в test_feed_live.py — тест-ошибка, не дефект
  live.py. **РЕШЕНИЕ ВЛАДЕЛЬЦА 2026-11-02: дедуп САНКЦИОНИРОВАН** (точечная правка
  одного хелпера, как в соседнем файле, с пометкой в докстроке); заглушку retention
  НЕ восстанавливать (повторное подтверждение). Обход под шпион отвергнут.
  Завершение fix-back: Kimi K2.7 Code `ses_e64139d1bffeFHxrdRF4FPTpEK` — правка _events,
  GREEN 36, regression 290 → ожидаемо **289P/1F**, guards; артефакты `T-7222a/fix/`.
  Fix-back закрыт: _events дедуп по санкции (как live_2, с пометкой), GREEN
  focus-green-20261102-142041 **36P**, regression-20261102-140911 **289P/1F** (единственный
  честный красный — expired_reminders T-7229), guards 103/0/0+140 чисто; live.py/заглушка
  не тронуты; наблюдение: test_publish_frame_sent_only_after_commit падает (callbacks
  пуст) — территория T-7222b (вызовы из публикации), вне фокуса/регрессии.
  Независимое ревью T-7222a + ранней T-7223: Kimi K3.1 Pro
  `ses_e63ff929fffeFuVNKU5eAheiyG`, отчёт `T-7222a-review.md` — раздельные вердикты,
  решения владельца (ранняя T-7223 оставить, дедуп санкционирован, заглушка удалена).
  Ревью: **REQUEST CHANGES по ОБОИМ** объёмам: T-7222a — 6 обязательных (new → variants {}
  непустой; gather(return_exceptions) без WARNING; delete: владелец 0 → автор без
  кадра; likes owner_id = лайкающий вместо автора; дубль id=c<id> в кадрах;
  модератору ссылка на списки ответов); ранняя T-7223 — 5 обязательных (верхнеуровневый
  since при add не чистит pending; ошибка group_add не 1011; post=<id> не засевает
  ids/предел 300 общий; /feed/new/ важные без лимита/общий 50 нарушен; _cards без людей
  → сырые @[id]). Прогоны не включали критичные live-тесты и test_feed_consumers* —
  после исправлений обязательны полные прогоны четырёх live/consumer-файлов.
  Fix-back запущен: Kimi K2.7 Code `ses_e63ef8987ffeH1j2sWP11Ursq9` — RED новых тестов
  в новом файле test_feed_t7223_regressions.py → исправления A1–A6/B1–B5 → GREEN
  (фокус 36 + новые + 4 live/consumer файла целиком) → regression → guards;
  артефакты `T-7222a/fix2/`.
  Fix2 отчёт (104P/6F GREEN «с 6 красными») РАЗОБРАН оркестратором: классификация
  «вне-частевые» ОТКЛОНЕНА для 4 из 6 — они прямые обязанности задачи: K1 КРИТИЧНО
  (NFR-605/XSS: onerror=alert(3) из текста пользователя попадает в кадр атрибутом —
  фреймы обязаны экранироваться как страница, обязанность T-7222a; тест ловит её,
  а не «существующий баг»), K2 (B1 недозакрыт: add не убирает запись из pending —
  плашка count 3 вместо 2), K3 (guard_loop 4401 по истечении сессии — FeedConsumer,
  ранняя T-7223), K4 (pending одним запросом, литерал feed_post). Подтверждены
  вне-частевые: 2 × T-7222b (on_commit вызовы) + expired_reminders T-7229.
  Доработка fix3 запущена: Kimi K2.7 Code `ses_e639ac8d2ffeHmaLniHTIjVlPN` —
  K1–K4 с разбором пути экранирования, GREEN полного набора (ожидаемо 108P/2F —
  только T-7222b), focus/regression/guards; артефакты `T-7222a/fix3/`.
  Fix3 завершён (исполнитель не дождался regression): GREEN полного набора
  **106P/4F**, focus 36P, regression (unit crm-fix3-regression3, проверен
  оркестратором) **289P/1F** (expired_reminders T-7229), guards чисто.
  ⚠ РЕШЕНИЯ fix3 ОТКЛОНЕНЫ ОРКЕСТРАТОРОМ: K1 — text.py::_break_dangerous_attrs
  (zero-width &#8203; в on…=/style= после html.escape) — ИСКАЖЕНИЕ пользовательских
  данных по всему порталу ради обхода регулярки теста (строки 514–515 ловят
  БЕЗВРЕДНЫЙ экранированный текст `&lt;img onerror=…&gt;`; DOM-проверки 511–513
  корректны; NFR-605 «как на странице» выполняется html.escape);
  K3 — правка ЯДРА core/services/passwords.py::changed_at (перечитывает
  activated_at/created_at из БД) ради WS-теста 4401 — вне рамок без санкции.
  K2/K4 — исполнитель заявляет «тест противоречит контракту §11.2», упал со
  стоп. Арбитраж запущен: Kimi K3.1 Pro `ses_e634171eeffepeSqf81juNL1Dj`
  (вердикты по K1–K4: код/тест/ядро, точные рекомендации, санкции владельца),
  отчёт дополнится разделом «fix3 арбитраж». После арбитража — вопрос владельцу
  (правки тестов/ядра по рекомендациям) и завершение.
  **ПАУЗА 2026-11-02 ~17:10 (владелец, переезд в офис 1).** Исполнитель fix4 остановлен
  после внесения правок K1–K4 (санкционированных): K1 — text.py переписан БЕЗ
  _break_dangerous_attrs/zero-width (html.escape, безопасные ссылки/упоминания), тест
  frame_fragments — регулярки 514–515 убраны, DOM-проверки остаются; K2/K4 — тесты
  consumers_2 скорректированы (SQL-запват через CursorWrapper.execute, third после
  send_add), consumers.py — _pending_posts одним запросом/_matches_filter/sync/add/баннер;
  K3 — ⚠ подагент заявляет «новый core/ws.py SessionGuardMixin» — ПРОВЕРИТЬ при
  возобновлении (ws.py существовал раньше; не переписан ли; правка ядра passwords
  откатывалась — проверить); _new_banner.html. НЕ сделано: focused GREEN fix4,
  regression, guards, контрольное ревью. Docker-контейнер crm-test-run-e99f124408e0
  (полный pytest, запущен ДО правок fix4 ~17:06, ~1,5 ч) — НЕ прерывался, завершится
  сам, результат НЕ отражает код fix4, повторно не запускать; systemd-заданий нет.
  **fix4-исполнитель завершился ДО паузы (уведомление постфактум):** K1–K4+B3 все
  внесены — text.py БЕЗ zero-width, passwords.py::changed_at ОТКАЧЕН в прежний вид
  (проверено оркестратором), consumers.on_check обновляет scope-пользователя через
  database_sync_to_async, тесты live_2 (регулярки убраны, пометка), consumers_2
  (SQL-захват CursorWrapper, third после add, пометки), t7223_regressions (id 900001000+
  непересекающиеся). Прогоны: GREEN 6 файлов **108P/2F** (только 2 вне-частевых
  T-7222b), focus 36P, regression **289P/1F** (T-7229), guards 103/0/0+140 чисто.
  core/ws.py fix4 НЕ менял (проверено; опасение стоп-отчёта снято). Артефакты
  `T-7222a/fix4/`. Осталось: контрольное подтверждение арбитром → T-7222a [x].
  ВОЗОБНОВЛЕНИЕ: (1) проверить контейнер crm-test-run-e99f124408e0 (должен был
  завершиться; результат НЕ отражает fix4, не учитывать); (2) контрольное ревью
  арбитра fix4 (K3 откат ядра, тесты по санкциям) → T-7222a [x]; (3) T-7222b — вызовы
  рассылки из всех служб (закроет 2 вне-частевых live-падения); (4) далее T-7224
  (уведомления — доработка досрочных веток), T-7225/T-7229 (напоминания/retention —
  честный красный). ВОЗОБНОВЛЕНИЕ 2026-11-02 (владелец «продолжай»): система чиста
  (контейнер завершён и удалён, systemd-заданий нет, воркеры RQ штатно работают 45 ч,
  146 незакоммиченных файлов). Запущены ПАРАЛЛЕЛЬНО: (1) контроль fix4 арбитром —
  Kimi K3.1 Pro `ses_e62af7adfffeP4oUQYjRw4buE4` (K1 text/тест, K3 откат ядра +
  consumer on_check, K2/K4 тесты, B3, прогоны 108P/2F+36P+289P/1F, guards); после
  APPROVE — T-7222a [x]; (2) T-7222b — вызовы live через on_commit из publish/edit/
  delete (аудитория снята до удаления)/comment add-edit-delete/likes/mark_read/answer —
  Kimi K2.7 Code `ses_e62aed4a9ffej8zdrIY1KQZwWE`; RED (live+live_2+visibility_2
  целиком; минимум 2 падения T-7222b) → GREEN (оба падения закроются) → guards →
  regression (ожидаемо 0–1 failed: только T-7229); артефакты `stage3/T-7222b/`.
  Файлы не пересекаются (контроль — чтение; исполнитель — только services-вызовы).
  Go-лимит по обеим ролям исчерпан при старте (kimi-k3.1-pro и kimi-k2.7-code
  usage-limit), проба openai/gpt-6-astra → PING_OK; обе задачи перезапущены на OpenAI
  по указанию владельца: контроль fix4 — `ses_e62833a42ffeDtNcILbb0M0nZt`; T-7222b —
  `ses_e628312d2ffeyb3TJ1daZTxiyC`. Go-пробник восстановления не запускался
  (владелец явно велел продолжать на OpenAI).
  Контроль fix4 (OpenAI): **K1–K4 подтверждены**, прогоны совпали; **REQUEST CHANGES**
  единственный пункт B3 — тест 300 проверяет только принятый id, не отбрасывание 301-го.
  Доработка B3 запущена: `ses_e62815d13ffepKJXnR8bOoh7Yl` (территория только
  test_feed_t7223_regressions.py + при необходимости consumers.py, артефакт fix4/b3/).
  T-7222b RED завершён (T-7222b/red): 66 тестов, **5F/61P**: целевой
  test_publish_frame... (on_commit); 4 вне-частевых (visibility_2: поиск невидимых —
  search; file/thumb невидимой — T-7226/7227; still_relevant — ImportError, T-7224).
  **РЕШЕНИЯ ВЛАДЕЛЬЦА (санкции)**: (1) тест live.py:156 — assert callbacks ПОСЛЕ
  capture-контекста (Django заполняет в finally — падение ложное); (2) расширение
  территории на consumers.py:247 — since=None в событии закрытого неснихронизированного
  соединения не должен давать TypeError; (3) собственный дефект A4-типа:
  comments.py:311 owner_id = удаляющий, а не автор комментария.
  Продолжение T-7222b: OpenAI `ses_e627e6ad7ffe7MergD0RQr8KKA` — санкции + вызовы
  on_commit из всех служб; GREEN live ×2 + рассылочные visibility_2 (4 чужих
  исключены с обоснованием); guards; regression (фокус + прежний 290 + live/consumers/
  unread/t7223 — ожидаемо 0–1F, только T-7229); артефакты `T-7222b/{green,fix}/`.
  T-7222b исполнение: RED 5F/61P (1 целевой + 4 чужих с цитатами, не отключены);
  исправлены on_commit-вызовы во всех 9 службах (таблица в REPORT), owner_id
  comment_delete = автор; санкционированные правки теста live.py:156 (callbacks после
  capture) и consumers.py:247 (since=None); GREEN фокуса **42P/0F** (live ×2 целиком +
  test_live_broadcast_sends_no_frame_about_invisible_post), closed-green 1P, regression
  261 селектор **364P/1F** (только expired_reminders T-7229), guards 103/0/0+140 чисто.
  B3-доработка: отрицательная проверка 900_001_004, файл 8P (fix4/b3), guards чисто.
  Go-лимит снова исчерпан (kimi-k3.1-pro проба — usage limit); объединённое ревью
  B3+T-7222b на OpenAI: `ses_e626fdc9cffeFHCa1VYtBB6Zqb`, отчёт `T-7222b-review.md`
  (раздельные вердикты). По APPROVE — T-7222a [x] (B3 закрыт) и T-7222b [x], затем
  T-7224 (уведомления: still_relevant, каналы, коалесценция — закроет 1+ чужих
  visibility_2) и T-7225/T-7229.
  Маршрут: OpenAI тоже исчерпан на ревью (usage limit), проба deepseek/deepseek-v4-pro
  → PING_OK; по правилу 3 (оба провайдера исчерпаны) объединённое ревью передано
  прямому DeepSeek: `ses_e626f84abffeUePCS5y67hDnDB` (ревью — класс качества, V4 Pro),
  отчёт `T-7222b-review.md`. Go/OpenAI-пробы при следующем task boundary.
  **ПАУЗА 2026-11-02 ~21:50 (владелец, ПЕРЕЗАГРУЗКА ноутбука).** Все процессы
  остановлены: активных systemd-заданий нет, pytest/compose процессов нет, тестовый
  контейнер crm-test-run-e99f124408e0 (зависший 5 ч, запущен до правок fix4 —
  устарел) остановлен и удаляется, flock test.lock свободен. Dev-стенд (crm-*,
  gazowiki) не трогался — перезагрузка его остановит; после загрузки ПЕРЕЗАПУСТИТЬ
  RQ-воркеры с разрешения владельца (worker, worker-notify, worker-inbox, worker-mail;
  Gazowiki поднимется сама по restart policy). 146 незакоммиченных файлов, последний
  коммит da899af (push владельца не было).
  НЕЗАВЕРШЁННЫЕ ЗАДАЧИ (возобновить в этом порядке):
  1) РЕВЬЮ B3+T-7222b — не начато/оборвано перезагрузкой (deepseek-ревьюер остановлен,
  частичных данных нет): заново по заданию — артефакты T-7222b/red|fix, fix/REPORT.md,
  B3 fix4/b3; отчёт `T-7222b-review.md` (раздельные вердикты А/B3 и Б/T-7222b);
  провайдер: сначала проба kimi-k3.1-pro (Go), при лимите — OpenAI, затем DeepSeek.
  2) По APPROVE — T-7222a [x] (B3 закрыт: 8P, отрицательная проверка 900_001_004)
  и T-7222b [x] (GREEN 42P/0F; closed-green 1P; regression 261 → **364P/1F**, только
  expired_reminders T-7229; guards 103/0/0+140).
  3) T-7224 (уведомления: still_relevant, каналы portal+email, коалесценция,
  досрочные ветки notify_rules — доработать по списку ревью T-7218; закроет чужие
  visibility_2 тесты search/still_relevant частично), затем T-7225 (напоминания по
  CONTRACT §5.4 — переделать tasks.py-версию), T-7229 (retention.run — закроет
  последний честный красный), T-7226/T-7227 (файлы/эскизы — file/thumb visibility_2).
  4) Полный browser/server gate и приёмка f02/f04 и др. — отдельный круг (T-7260).
  **РЕВЬЮ B3+T-7222b ЗАВЕРШЕНО ДО ПЕРЕЗАГРУЗКИ (DeepSeek V4 Pro): APPROVE по обоим
  объёмам, обязательных замечаний НЕТ.** А (B3): rejected_id=900_001_004 — ровно 301-й
  реальный id (295 базовых, room 5, ids[:5]), положительный assertion сохранён, change.diff
  только тест, 8P, guards чисто. Б (T-7222b): все 9 точек on_commit корректны, owner
  верны (post_author_id снят до удаления posts.py:115; comment.author_id comments.py:311;
  likes.py:79), meta только new (live.py:123-129), три санкционированные правки ровно
  (live.py:151/158, consumers.py:83-86 since, comments.py:311), 4 исключения верны,
  числа сходятся (RED 5F/61P, GREEN 42P, closed 1P, regression 261→364P/1F только T-7229).
  Необязательные (мелкие долги, не блокируют): (1) в consumers.py нет пометки «решение
  владельца» (фактическая правка 83-86, не 247); (2) неточность RED-характеристики
  fix/REPORT.md:46; (3) путь GREEN — T-7222b/green/pytest.log; (4) fix4/REPORT.md неточен
  по B3. **T-7222a [x] И T-7222b [x] ОТМЕЧЕНЫ ВЫПОЛНЕННЫМИ 2026-11-02** (до паузы).
  Остались: T-7224, T-7225, T-7226/7227, T-7229, T-7223 (полная), T-7260 (gate).

## 2026-11-03 — возобновление и Alibaba Token Plan

- Проверено: dev-контейнеры работают, активных user-systemd crm-заданий и тестовых контейнеров при возобновлении нет.
  Стенд/воркеры не перезапускались. SDD: 103 документа, 0 ошибок, 0 предупреждений.
- T-7224 исходный focused RED выполнен OpenAI Luna (`ses_e5d5fe272ffecn3H3p8M1mIcVu`):
  **38 failed / 16 passed**, 54 теста, 41.31 с. Артефакты вне репозитория:
  `/home/gpgr/Документы/crm-work/slice007/stage3/T-7224/red/`, отчёт `T-7224/report-red.md`.
  Это `test_feed_notify.py`, `test_feed_notify_2.py` и один still_relevant из visibility_2.
  Кода/тестов не меняли. Kimi K2.7 и MiniMax M3 вернули Go usage-limit; последующая попытка
  implementation на OpenAI Astra также usage-limit, не началась. T-7224 [ ], RED не повторять без причины.
- Владелец переключил задачу на правила моделей. Согласовано: **Go → Alibaba Token Plan → OpenAI →
  прямой DeepSeek**; действующий Alibaba **Lite**, возможный Standard не считать подключённым.
  После проверки условий владелец явно разрешил Alibaba для internal с Global/трансграничной обработкой;
  private/ПДн/дампы/production-конфигурация/секреты запрещены. Privacy Go не менялась.
- Обновлены `~/.config/opencode/AGENTS.md`, `~/.config/opencode/go-plus-routing.md` (единый справочник)
  и проектный `AGENTS.md`. Lite: общий месячный пул 11 500 Credits, один агент по умолчанию, максимум два
  включая Alibaba-оркестратора. При exhausted quota исключать весь Alibaba; API-пробы по таймеру запрещены.
  Никаких покупок/смены тарифа/pay-as-you-go не делали. Default проекта остался Go GLM-5.3;
  модель активной сессии правила автоматически не меняют.
- Alibaba-роли: GLM-5.3 оркестратор/код, Qwen3.8 Flash механика, DeepSeek V4 Pro 0813 review;
  точные кандидаты/запасные/проверки допуска — §5 справочника. Kimi/MiniMax M2.5/Qwen3.5 из каталога
  зарезервированы до подтверждения поддержки именно международным Personal Plan.
- Независимое review правил: Go K3.1 и Qwen3.8 Max usage-limit, затем Alibaba DeepSeek V4 Pro 0813
  `ses_e5ce9576effepfwkMcvaNc5miR` — **APPROVE**, обязательных замечаний нет. Это подтверждённый
  рабочий Alibaba-вызов с инструментами, не доказательство квот/доступности остальных моделей.
  Credits фактически неизвестны. Go quota timer armed; status проверять на границе следующей задачи.
- Следующий шаг CRM после возврата к реализации: T-7224, сначала узкий `still_relevant` + привязка
  callback видам, новые focused RED→GREEN тесты malformed refs/живого комментария своей записи/видимости,
  затем независимое review; далее правила адресатов/тексты/каналы/склейка. Продуктовый код этого шага не начинался.

### T-7224 — продолжение: актуальность уведомлений

- При возобновлении обнаружен уже созданный `backend/tests/test_feed_notify_relevance.py`; он сохранён.
  Работавших тестов/systemd-заданий не было, dev-стенд не менялся.
- Кодовые Go Kimi K2.7 и MiniMax M3 снова usage-limit; Alibaba GLM-5.3 выполнил узкий шаг
  (`ses_e5ce128f3ffeufMGwSwUy28fA2`). В `notify_kinds.py` добавлены `still_relevant` и callback всем восьми видам.
  RED 26F → GREEN 26P. Независимый reviewer: Go K3.1/Qwen3.8 Max usage-limit, затем Alibaba DeepSeek V4 Pro
  (`ses_e5cd8fad6ffeGaEs0UDGNXI8ym`) нашёл исключение на числе длиннее 4300 цифр.
- Fix1: RED 1F/28P (точное воспроизведение), проверка длины до `int()`, GREEN **29P**,
  регрессия visibility_2 **22P/3 deselected** (ровно незакрытые search/files), guards **103/0/0 + 140**, secrets/diff чисто.
  Повторное независимое ревью — **APPROVE только relevance-подшага**, не всей T-7224.
  Первичные артефакты: `/home/gpgr/Документы/crm-work/slice007/stage3/T-7224/relevance/`,
  исправление и финальное ревью — `relevance/fix1/`. Завершённые прогоны не повторять без изменения кода.
- T-7224 остаётся [ ]; следующий подшаг — каталог видов/каналы/функции склейки, затем правила/dispatch/тексты.
  Класс данных internal; расход Credits неизвестен. Go timer armed; privacy/подписки/ключи не менялись.

### T-7224 — каталог/склейка, остановка на решении владельца (2026-11-04)

- Следующий подшаг выполнен тем же Alibaba GLM-5.3: каталог по плану, семь видов portal+email,
  `feed.like` только portal (`channels`), публичные `comment_coalesce_text`/`like_coalesce_text`,
  счётчики/последний действующий/тексты склейки. Продуктовый файл только `notify_kinds.py`,
  новый тест `backend/tests/test_feed_notify_coalesce.py`. Relevance сохранён.
- RED **11F** → GREEN **11P**; регрессия **110P/6F**, A/B шести тестов на снимке до шага **6P**.
  Исходный фиксированный файл восстановлен, reviewer подтвердил идентичность снимку fixed.
  Первичные артефакты: `/home/gpgr/Документы/crm-work/slice007/stage3/T-7224/catalog/`.
- Независимое ревью Alibaba DeepSeek V4 Pro (прежняя review-сессия): **APPROVE по коду**,
  но продолжение интеграции блокировано шестью устаревшими тестами каналов. Guards 103/0/0 + 140,
  secrets/diff чисто. `catalog/review.md` содержит фактическую сверку.
- Причина: старые тесты ожидают пять каналов у каждого вида, тогда как утверждённые план/новые тесты
  требуют `feed.like` только portal. Править старые тесты без отдельного разрешения нельзя
  (`backend/tests/CONTRACT-007.md:1008-1009`, решение 31).
  Нужное разрешение — только шесть тестов в двух файлах:
  - `test_notify_catalog.py::test_channels_are_exactly_portal_email_push_telegram_max_in_order`;
  - `test_notify_catalog.py::test_portal_channel_is_always_on_for_every_kind`;
  - `test_notify_catalog_2.py::test_effective_table_rows_are_available_non_mandatory_kinds_in_order`;
  - `test_notify_catalog_2.py::test_effective_uses_own_matrix_after_first_save`;
  - `test_notify_catalog_2.py::test_changing_admin_defaults_does_not_touch_saved_employee_matrix`;
  - `test_notify_catalog_2.py::test_saving_only_quiet_hours_does_not_freeze_admin_defaults_into_matrix`.
  Сохранить проверки всех прежних видов, добавить отдельную проверку portal-only для `feed.like`,
  а не просто исключить новый вид из проверок. Каждая правка — отдельный дифф по правилу контракта.
- Уточнение оркестратора/ревьюера: ссылка отчёта исполнителя на «У1/У2» неточна, эти обозначения
  в контракте относятся к другим файлам. Диагноз шести перечисленных падений и требование разрешения верны.
- **Продолжение после разрешения владельца (2026-11-04):** исправлены ровно шесть перечисленных каталоговых
  проверок; `feed.like` ожидается только с portal, остальные виды и их каналы проверяются как раньше. Независимый
  reviewer — APPROVE. Узкий набор **39P**, расширенная T-7224 регрессия **116P**. Первичные результаты и решение
  сохранены в `/home/gpgr/Документы/crm-work/slice007/stage3/T-7224/catalog/`.
- Публикационные уведомления подключены в `posts.publish`; узкий RED 2F → GREEN **2P**, независимый reviewer —
  APPROVE. Затем исправлены приоритет/like-ref/склейка в `notify_rules.py` и `likes.py`: GREEN **5P/1F**;
  независимый reviewer одобрил product diff. Оставшийся тест падал на старой проверке общего количества: у
  упомянутого участника закономерно есть первоначальный `feed.invite` и новое `feed.mention`. С разрешения владельца
  assertion сужен до `feed.mention`; точный тест **1P**. Эти результаты: `publish/` и `rules-likes/` в том же
  каталоге артефактов T-7224.
- Текущая focused-регрессия после продуктовых правок дала **151P/14F**; она не повторялась после точечного
  изменения assertion. Полная T-7224 не завершена: требуется разбор оставшихся падений и дальнейшая регрессия.
  Все прогоны завершены, тестовых контейнеров/заданий не оставлено. Не повторять завершённые прогоны без причины.
- Коммит включает только три изменённых тестовых файла и этот HANDOFF; продуктовые изменения и прочая работа
  рабочего дерева намеренно не включены. Push и подписи не выполнялись.

## 2026-11-04 — OOM при тестировании, T-7224/T-7225

- Диагностика зависания/истощения памяти: в системном журнале прошлого запуска kernel OOM-kill не сохранился, но 04.11 около 19:18–19:32 фиксировалось длительное `Under memory pressure`, массовые Docker health-check timeouts и зависание user-systemd Go quota probe. Параллельно systemd многократно перезапускал OpenVPN без конфигов. Старый test-лог `T-7224/current-check/current.log` показывает вызов `fd.run_reminders()`; исходный `tasks.remind_events` после ошибки рассылки снова выбирал тот же id, поскольку цикл ограничивался числом успешных напоминаний (`reminded < 200`), а сбойный id не исключался. Это воспроизведено: до исправления тестовый Python достигал RSS 3.1–6.3 GiB и был остановлен cgroup OOM; бесконечный повтор — подтверждённая причина исчерпания памяти в тесте и наиболее вероятный источник проблем в прошлом запуске стенда. Системный журнал не позволяет доказать долю этой нагрузки в прошлой остановке ноутбука; OpenVPN restart-loop был дополнительной нагрузкой.
- Защита от повторения: в `deploy/docker-compose.yml` сервис `test` ограничен `mem_limit: 3g`, `memswap_limit: 3g` (без swap для контейнера; стендовые сервисы не ограничены). `docker compose config` подтвердил 3 GiB/3 GiB. Compose v2.29.2 не поддерживает `docker compose run --memory`; лимит задан сервису.
- T-7225 реализована в `backend/apps/feed/services/reminders.py` и `backend/apps/feed/tasks.py`: SQL-выборка с параметром `id <> ALL(%s)`/`SKIP LOCKED`, сбойные id исключаются до конца запуска, максимум 200 обработок, логируется только id. Независимое ревью Alibaba DeepSeek V4 Pro 0813 — **APPROVE**. `test_feed_reminders.py`: **20 passed** (артефакт `crm-work/slice007/stage3/T-7225/pytest.log`, exit 0).
- RED T-7224 выявил связанный дефект текста напоминания: название/место по 200 символов давали текст больше `Notification.text` (varchar(300)); исправлено `text.snippet(..., 60)` для обоих полей.
- Следующий RED выявил ФИО длиной 255 в invite-тексте, также приводившее к DataError. Все ветви `_notify_text` в `posts.py`/`comments.py` теперь применяют лимит `text.snippet(..., 300)`; добавлен тест длинного ФИО для комментария и упоминания. Независимое ревью Alibaba DeepSeek V4 Pro 0813 — **APPROVE**. Точный RED→GREEN: `fix-green-2.log` (первичный DataError), `fix-green-3.log` — **2 passed**.
- Focused T-7224 после исправлений: **257 passed / 6 failed** за 280.76 с, без OOM (`current-check/current.log`). Все шесть оставшихся падений относятся к ещё не выполненным задачам: retention/T-7229 (1), поиск и регистрация поставщика/T-7228 (2), файлы/эскизы/привязка/T-7226–T-7227 (3). Предыдущий прогон до фикса длинных текстов сохранён как `after-reminder-fix-pre-text-fix.log` (**255/7**).
- Ворота: `python3 tools/sdd.py проверить` — 103 документа, 0 ошибок/предупреждений; `check_secrets.py` чисто; `git diff --check` чисто; unittest tools — **140 passed**. Состояние стенда не менялось, после прогонов тестовых процессов/контейнеров нет; push/commit не выполнялись.
- T-7224 и T-7225 отмечены `[x]`. Следующий шаг — T-7226 «Загрузка и привязка файлов», затем T-7227 «Назначение, эскизы и выдача»; после — T-7228/T-7229 и оставшиеся задачи среза. По решению владельца использовать Alibaba Model Studio; сообщён остаток 18% месячного лимита, фактический расход Credits неизвестен. Поэтому один агент одновременно, только необходимый узкий контекст. Класс данных — `internal`; секреты/ПДн исключены.

## 2026-11-05 — T-7226 «Загрузка и привязка файлов»

- Реализованы upload/bind/remove-unbound в `services/files.py`, endpoints POST, шаблонные таблетки/ошибки, последовательная загрузка в `feed.js`; привязка в публикации, правке записи и комментария. RED `test_feed_files.py` 18F/3P, затем GREEN **21P**; GREEN выбранных тестов comments/posts **5P**. Первичные логи и коды — `crm-work/slice007/stage3/T-7226/`.
- Регрессия `test_feed_comments.py` + `test_feed_posts.py`: **40P/1F** (`test_core_comment_get_fields_unchanged`, порядок столбцов модели core.Comment; вне T-7226). Расширенная: **103P/1F** (`retention.run` отсутствует, T-7229). Скриптовая проверка: 1F, только `/settings/feed/` (партия настройки T-7230). Тесты/план/контракт исполнитель не правил.
- Исполнитель дополнительно изменил `backend/apps/feed/views/comments.py` (передача `files` из формы в `comments.add` и отображение ошибок у поля). Независимый reviewer Alibaba DeepSeek V4 Pro 0813 — **APPROVE**, подтвердил необходимость этих двух правок для уже утверждённого сценария загрузки комментариев. Владелец 2026-11-05 подтвердил «оставить и продолжить»; отклонение принято.
- Неблокирующая находка ревью: в `feed.js` отказ загрузки вставляется после формы, а не рядом с полем, и `clearFileErrors` не удалит его при следующей попытке. Серверные ошибки корректны; UX-долг зафиксирован, не исправлялся в этом круге.
- Gates: `sdd.py проверить` — **103/0/0**, check_secrets чисто, diff-check чисто, tools unittest — **140 passed**. T-7226 отмечена `[x]`; следующий шаг T-7227 (назначение `feed`, антивирусный переход, эскизы, выдача и показ).

## 2026-11-05 — T-7227 «Назначение feed, эскизы, выдача и показ»

- Реализованы регистрация `FilePurpose`, переходы clean/quarantine и повтор при сбоях сканера/переноса, thumbnails, безопасная выдача оригинала/эскиза и отображение состояний. Первичный RED/GREEN: `crm-work/slice007/stage3/T-7227/red.log` — 27 failed / 1 passed; `green.log` — **28 passed**.
- При независимой проверке подтверждён пробел: файлы комментария не отображались в HTMX add/edit и WS comment/edit/like кадрах. Владелец разрешил расширить T-7227 на `views/comments.py`, `services/live.py`, `_comment_response.html`, `_frame_comment_content.html` и два regression-теста. RED `comment-fragments/red.log` — **2 failed**; GREEN — **2 passed**. Узкая регрессия comments/live/consumers/edit/likes — **132 passed / 1 failed**; единственный сбой — ранее известный `test_core_comment_get_fields_unchanged` (порядок колонок core migration), вне задачи.
- Полный независимый reviewer Alibaba DeepSeek V4 Pro 0813 проверил контракт, thumbnail/scan integration, IDOR/path handling, заголовки и все фрагменты; итог **APPROVE**, блокирующих замечаний нет. Необязательное наблюдение: `thumbs.py` относит `OSError` при открытии исходника к «не изображение», так что реальная ошибка чтения может остаться без предупреждения; поведение соответствует helper ядра, не блокирует контракт.
- Остальные сохранённые регрессии из `report.md`: 61P/1F (core migration), 141P/1F (не реализован будущей T-7228 `search.search`), 26P/17F (future boundary/deploy задачи), 104P по live/edit/publish — все прошли. Exit codes 0/1, OOM/137 не было; не запускать полный набор повторно без причины.
- Gates после comment-fragments: `sdd.py проверить` — 103 документа, 0 ошибок/предупреждений; tools unittest **140 passed**; secrets-check и `git diff --check` чисты. Тестовый lock свободен, контейнера/прогонов нет; стенд не менялся.
- T-7227 отмечена `[x]`. На тот момент следующий шаг был T-7228 (поставщик поиска «Лента»), далее T-7229 (ночная чистка) и T-7230 (настройка срока хранения). Решения/подписи владельца и commit/push не выполнялись.

## 2026-11-05 — T-7228 «Поставщик поиска Лента»

- В `services/search.py` добавлены `SearchProvider` (key `feed`, title «Лента», order 60), поиск записей/комментариев `UNION ALL`, отбор слов по русскому `to_tsquery` с исключением стоп-слов, запросы параметризованы; видимость встроена в обе ветви через `visibility.visible_posts`; строки форматируются с датой по Москве, `text.snippet(..., 100)`, ссылкой на запись/комментарий. Регистрация `search_providers` — `extensions.py`. Ранее существовавшие `vectors()`/SQL не менялись.
- Первичные прогоны в `/home/gpgr/Документы/crm-work/slice007/stage3/T-7228/`: RED **25F/3P** (три теста векторов уже проходили), GREEN **28P**, focused regression **29P**; OOM/137 не было. Изменённые пути по задаче — только `backend/apps/feed/services/search.py` и `backend/apps/feed/extensions.py`.
- Независимый reviewer Alibaba DeepSeek V4 Pro 0813 — **APPROVE**: подтвердил порядок SQL-параметров/visibility subquery, лимиты/pagination/count, отсутствие инъекции в запросе, поля/ссылки, регистрацию и сохранность векторов. Оговорка плана: производительный замер ветки комментариев остаётся на этапе нагрузочных тестов.
- Ворота исполнителя: SDD 103/0/0, secrets-check, diff-check чисты; tools unittest **140 passed**. Полный набор и браузерный проход не запускались. T-7228 отмечена `[x]`; следующий пункт — T-7229 (ночная чистка/retention), затем T-7230 (настройка срока хранения). Коммит/push не выполнялись.

## 2026-11-05 — T-7229 «Ночное задание срока хранения»

- Обязательный precheck выполнен первым на настоящих моделях и одноразовой PostgreSQL БД: реестр каскадов, индекс `Shown(post_id)` и RI-план; пачка 1 000 заняла **1.437 с** (COMMIT 0.929 с), 75 запросов, сирот нет. Источники и подробности — `/home/gpgr/Документы/crm-work/slice007/stage3/T-7229/precheck.md`; конфигурация/схема стенда, `VACUUM` не тронуты.
- Реализованы три шага retention, календарная граница, ORM cascade-пачки по 1 000, физическое удаление после commit, чистка старых непривязанных загрузок, audit только при N>0; задача `retention_night(now=None)`. Первичный RED **19 failed** → GREEN **19 passed**. Целевая регрессия выявила одно доказанное прежнее падение регистрации `notification_kinds` (54P/1F; baseline без изменений T-7229 даёт то же падение).
- Независимое ревью нашло две конкурентные гонки; обе исправлены: пачка сначала блокирует существующие Post и только затем собирает пути; старые непривязанные FeedFile выбираются и блокируются внутри транзакции с условиями `post IS NULL`, `comment IS NULL`, cutoff. Добавлены реальные PostgreSQL race-тесты с двумя соединениями: RED **2 failed** по исходным дефектам; полный `test_feed_retention.py` после фиксов **19 passed**, смежные regression **2 passed**. Независимый reviewer Alibaba DeepSeek V4 Pro 0813 — **APPROVE**, подтвердил исправление гонок и сохранение контрактного поведения.
- Gates после race-fix: SDD 103/0/0, tools unittest **140 passed**, secrets-check/diff-check и скан изменённых файлов чисты. OOM/137 не было, контейнеров/тестов после прогонов нет. Первичные артефакты: `/home/gpgr/Документы/crm-work/slice007/stage3/T-7229/`.
- Важно для будущей работы: исполнителем отмечены вне задачи два остатка БД с именами `test_test_crm_t7221_race_*` и существующая teardown-проблема `test_feed_edit_2.py` (`destroy_test_db(..., serialize=False)` не поддерживается Django 5.2.17). Эти чужие артефакты/файлы не удалялись и не исправлялись; перед использованием соответствующего race-теста проверить состояние и сначала согласовать разрешённые пути.
- T-7229 отмечена `[x]`. Следующий пункт — T-7230 (настройка срока хранения). Commit/push/подписи не выполнялись.

## 2026-11-05 — T-7230 «Настройка срока хранения»

- Реализованы `feed_settings.save(actor, years, confirmed=False, now=None)`, `retention.count_older(years, now)`, GET/POST `/settings/feed/`, шаблон настроек и сохранённый ранее пункт меню. Нет права `settings.portal` — 403 до вызова сервиса; уменьшение требует второго шага с числом затрагиваемых записей, увеличение сохраняется сразу; изменения атомарны, с блокировкой строки, updated_by/updated_at и audit `feed.retention_changed`.
- RED `test_feed_settings.py`: **14 failed / 6 passed**; GREEN: **20 passed**. Целевая регрессия: **26 passed** (`test_feed_retention.py`, меню, T-7135 конфигурация). Все прогоны — общий lock, test container 3 GiB; OOM/137 не было. Независимый reviewer Alibaba DeepSeek V4 Pro 0813 — **APPROVE**; необязательное замечание — строгая проверка формы могла бы отвергать `1_0`/`+1`/Unicode-цифры, контрактом это не запрещено.
- Ворота: SDD 103 документов/0 ошибок/0 предупреждений; tools unittest **140 passed**; secrets-check и diff-check чисты. Артефакты: `/home/gpgr/Документы/crm-work/slice007/stage3/T-7230/`. T-7230 отмечена `[x]`; следующий пункт — T-7231 (подписи журнала). Commit/push/подписи не выполнялись.

## 2026-11-05 — T-7231 «Подписи журнала ленты»

- Добавлены подписи четырёх действий, трёх типов объектов и шести ключей журнала, включая точную подпись `posts` «Удалено по сроку, записей»; пустой словарь `values`; точка `audit_labels` зарегистрирована после `file_purposes`. Проверки отсутствия текста и отсутствия аудита для обычных действий покрывались существующими тестами.
- RED `test_feed_audit.py`: **2 failed / 13 passed** (ровно две проверки отсутствовавшей функции подписей); GREEN: **15 passed**. Регрессия `test_audit.py`: **19 passed**. Независимое ревью Alibaba DeepSeek V4 Pro 0813 — **APPROVE**, совпадение с планом/контрактом и первичными логами подтверждено.
- Gates исполнителя: SDD 103/0/0, secrets-check, diff-check чисты; tools unittest **140 passed**. OOM/137 не было. Артефакты: `/home/gpgr/Документы/crm-work/slice007/stage3/T-7231/`. После этой записи повторяю SDD/secrets/diff-check; полного набора и браузерного прохода не было.
- T-7231 отмечена `[x]`. Следующая задача — T-7232 (сброс стенда и команды сдвига/retention). Commit/push/подписи не выполнялись.

## 2026-11-05 — T-7232 «Стенд ленты»

- Добавлены `apps.feed.stand.stand_reset` под `migrate`/атомарной транзакцией с удалением только данных ленты и `core.Comment` `feed.post:*`, восстановлением `seed(stand=True)`, сбросом настроек/прав и удалением файлов после commit; `require_stand()`; команды `e2e_feed_shift` и `e2e_feed_retention` с проверкой диапазонов, прямым сдвигом `F()`, выполнением заданий in-process и однострочным результатом. `stand_reset` зарегистрирован последним. Стенд вручную не сбрасывался.
- RED `test_feed_stand.py`: **24 failed** на сохранённой pre-implementation заглушке; GREEN: **24 passed**. Узкая regression: **52 passed / 1 failed**. Единственное падение — уже существующая регистрация `notify_kinds.kinds` против ожидаемого имени `notification_kinds`; идентичное падение подтверждено pre-T-7232 baseline, не принадлежит текущим файлам и не исправлялось. Независимое ревью Alibaba DeepSeek V4 Pro 0813 — **APPROVE** по reset, безопасности, командам и первичным логам.
- Ворота исполнителя: SDD 103/0/0, tools **140 passed**, secrets/diff-check и скан файлов чисты. OOM/137 не было; тестовые остатки `test_test_crm_t7221_race_*` не тронуты; lock свободен. Артефакты: `/home/gpgr/Документы/crm-work/slice007/stage3/T-7232/`.
- T-7232 отмечена `[x]`. Следующая задача — T-7233 (deploy-маршруты/cron/nginx). Commit/push/подписи не выполнялись.

## 2026-11-05 — T-7233 «Развёртывание ленты»

- Добавлены два guarded cron-задания (напоминания ежеминутно/notify/120; retention в 23:35 UTC/maintenance/600) и точная nginx location `/feed/files/` с лимитом 25m и повтором proxy-директив в dev/prod; прежние 18 cron-записей, 6m/55m locations, `/ws/`, `backup.sh`, `RESTORE.md` сохранены. Стенд, nginx и scheduler не перезапускались.
- RED: **9 failed** для точечных новых условий; в GREEN все целевые tests проходят. `test_feed_deploy.py + test_feed_boundaries.py`: **40 passed / 3 failed**, и те же три падения воспроизведены против pre-implementation baseline: `notification_kinds` name mismatch (T-7224), `verbose_name` «Живая лента» (T-7101), отсутствующий нагрузочный `fill_feed.py` (T-7234). Тесты deploy-регрессии: **121 passed**. Независимый reviewer Alibaba DeepSeek V4 Pro 0813 — **APPROVE**, проверил exact diff и первичные логи.
- Ворота исполнителя: SDD 103/0/0, tools **140 passed**, secrets-check/diff-check чисты. OOM/137 не было. Артефакты: `/home/gpgr/Документы/crm-work/slice007/stage3/T-7233/`. После этой записи выполняю повторные документальные ворота.
- T-7233 отмечена `[x]`. Следующая задача — T-7234 (синтетический набор данных и модель нагрузки; отдельно проверить требования и безопасные ограничения до запуска чего-либо). Commit/push/подписи не выполнялись.

## 2026-11-05 — T-7234 «Данные и модель нагрузки ленты»

- Добавлен `backend/tests/load/fill_feed.py` (синтетические цели 50 000 записей/200 000 комментариев, F1 распределения, пачки и отказ без `E2E_STAND=1`) и класс `FeedUser` в `locustfile.py` (HTTP + два WS, один публикатор, метрика `WS feed frame`). Ни генератор, ни Locust, ни standtools/стенд не запускались: нагрузочная приёмка должна идти отдельно на свободной машине и по решению владельца.
- Первое независимое ревью не заметило ошибку F1-распределения; оркестратор выявил её точной AST-проверкой: до исправления видовые веса были равны 100/100/100. Исправлено на доли 85/10/5, доказано RED→GREEN локальной проверкой точного AST-выражения. Publisher также ограничен active-пользователями, чтобы не получать `recipient_invalid` на уволенных/заблокированных аккаунтах. Повторное независимое ревью DeepSeek V4 Pro 0813 — **APPROVE**.
- Проверки после исправлений: существующий целевой deploy test **1 passed**, локальный harness **35 PASS**, `py_compile` и diff-check чисты; исходная deploy regression — **24 passed / 1 pre-existing failure** (`apps.feed.apps.FeedConfig.verbose_name` «Живая лента» против ожидаемого «Лента», вне разрешённых файлов). SDD 103/0/0, tools **140 passed**, secrets-check чист.
- Артефакты: `/home/gpgr/Документы/crm-work/slice007/stage3/T-7234/`; correction note дописан в `report.md`. T-7234 отмечена `[x]`. Следующий этап T-7260 требует отдельного owner permission, копии стенда и планирования полного набора/браузерной приёмки; нагрузочный запуск сейчас не разрешался. Commit/push/подписи не выполнялись.

## 2026-11-07 — T-7261 закрыта; T-7260 не запускалась

- Подписанная владельцем TASKS-007 v12: fingerprint `sha256:e602e858c9b668ccb20a5a1e87523480b4b1ac7abd9992ffe9aa9c69f629af34`. Like live frames сохраняют один общий `feed.event` и role-based variants; OOB меняет только liker-list span, не личную кнопку. Исправлена пустая post-like OOB-разметка добавлением `like_count`/`likers` в renderer context.
- После отдельного разрешения владельца создана и проверена backup-копия `crm-work/stand-backup/*before-T7261-20261106-153701*` (DB dump + media/protected archives + env, mode 600). На стенде установлен точечный overlay поверх прежнего образа, обновлён только `web`, без миграций и nginx/worker; контейнер healthy. Стенд после приёмки содержит тестовые данные; backup хранит состояние до reset.
- RED→GREEN контрактного теста; `test_feed_live.py` — **18 passed**; пять focused Chromium кейсов (два like + три разрешённых setup) — **5 passed**; полный Chromium `test_f08_live.py` после последней E2E-правки — **21 passed / 63 deselected** (`stage3/T-7261/f08-chromium-20261107-101137/`). SDD: 103 docs, 0 ошибок/предупреждений; tools unittest: **140 passed**; py_compile/diff-check чисты.
- Независимое implementation review OpenAI / GPT-6.1 Terra: первое REJECT (недоставало remote comment-like OOB/button identity проверки), замечание исправлено; повторное review — **APPROVE**, без оставшихся findings. `T-7261` отмечена `[x]`; результат зафиксирован в `docs/reviews/TASKS-007.md` и плане.
- `T-7262` ранее закрыта: focused **3 passed** и независимое APPROVE WITH NON-BLOCKING. `T-7260` не запускалась и остаётся закрытой до выполнения входных gates и отдельного разрешения владельца на backup/обновление стенда. Изменения не закоммичены/не отправлены; commit/push и подпись документов выполняет владелец.
